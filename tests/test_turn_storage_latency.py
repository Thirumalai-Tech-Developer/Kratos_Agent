"""Remote persistence must not delay inference or Stop, and must survive restarts."""
import json
import sqlite3
import threading
import time

import requests

from kratos_agent.core.d1_client import D1DatabaseClient
from kratos_agent.core.event_store import EventStore
from kratos_agent.core.execution_control import execution_scope
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent


def test_turn_events_persist_before_slow_remote_sync(tmp_path, monkeypatch):
    db = D1DatabaseClient(account_id='account', database_id='database', api_token='test-token', local_db_path=tmp_path / 'db.sqlite')
    entered = threading.Event()
    release = threading.Event()
    def slow_remote(sql, params):
        entered.set()
        release.wait(3)
        raise requests.Timeout('offline')
    monkeypatch.setattr(db, '_execute_remote', slow_remote)
    store = EventStore(tmp_path / 'session', db=db)
    try:
        started = time.monotonic()
        with execution_scope(threading.Event()):
            store.append(RuntimeEvent(EventKind.AGENT_STARTED, {'query': 'hii'}, 'turn'))
            assert time.monotonic() - started < 0.5
            rows = db.execute('SELECT * FROM agentic_events')
            assert len(rows) == 1
        assert entered.wait(1)
        assert json.loads(store.path.read_text())['payload']['query'] == 'hii'
        assert db._execute_local('SELECT * FROM _kratos_d1_outbox', [])
    finally:
        release.set()
        db.close()


def test_remote_outbox_replays_after_restart(tmp_path, monkeypatch):
    path = tmp_path / 'db.sqlite'
    db = D1DatabaseClient(account_id='account', database_id='database', api_token='test-token', local_db_path=path)
    monkeypatch.setattr(db, '_execute_remote', lambda *args: (_ for _ in ()).throw(requests.Timeout('offline')))
    with execution_scope(threading.Event()):
        db.execute('INSERT INTO agentic_events (id, session_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?)', ['event', 'session', 'agent.started', 1, '{}'])
    db.close()
    synced = []
    replacement = D1DatabaseClient(account_id='account', database_id='database', api_token='test-token', local_db_path=path)
    monkeypatch.setattr(replacement, '_execute_remote', lambda sql, params: synced.append((sql, params)) or [])
    try:
        with execution_scope(threading.Event()):
            assert replacement.execute('SELECT id FROM agentic_events') == [{'id': 'event'}]
        deadline = time.monotonic() + 2
        while replacement._execute_local('SELECT * FROM _kratos_d1_outbox', []) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert any(params and params[0] == 'event' for _, params in synced)
        assert not replacement._execute_local('SELECT * FROM _kratos_d1_outbox', [])
    finally:
        replacement.close()


def test_unsynced_session_keeps_complete_disk_history(tmp_path, monkeypatch):
    from kratos_agent.core.memory import AgenticMemory

    db = D1DatabaseClient(account_id='account', database_id='database', api_token='test-token', local_db_path=tmp_path / 'db.sqlite')
    monkeypatch.setattr(db, '_execute_remote', lambda *args: (_ for _ in ()).throw(requests.Timeout('offline')))
    try:
        memory = AgenticMemory(sessions_dir=tmp_path / 'sessions', db=db)
        session = memory.active_session
        memory.record_turn('Earlier turn', 'Earlier reply')
        memory.record_turn('Latest turn', 'Latest reply')
        # The mirror predates local-first persistence and lacks the older turn.
        db._execute_local('DELETE FROM turns WHERE turn_index = 0', [])
        assert db.has_pending_writes
        assert memory.load_session(session.session_id)
        assert [turn['user'] for turn in memory.active_session.turns] == ['Earlier turn', 'Latest turn']
    finally:
        db.close()


def test_outbox_does_not_sync_to_a_different_database(tmp_path, monkeypatch):
    path = tmp_path / 'db.sqlite'
    original = D1DatabaseClient(account_id='account', database_id='original', api_token='test-token', local_db_path=path)
    monkeypatch.setattr(original, '_execute_remote', lambda *args: (_ for _ in ()).throw(requests.Timeout('offline')))
    with execution_scope(threading.Event()):
        original.execute('INSERT INTO agentic_events (id, session_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?)', ['event', 'session', 'agent.started', 1, '{}'])
    original.close()
    other = D1DatabaseClient(account_id='account', database_id='other', api_token='test-token', local_db_path=path)
    synced = []
    monkeypatch.setattr(other, '_execute_remote', lambda sql, params: synced.append((sql, params)) or [])
    try:
        with execution_scope(threading.Event()):
            other.execute('SELECT id FROM agentic_events')
        assert not other.has_pending_writes
        assert other._execute_local('SELECT * FROM _kratos_d1_outbox', [])
        assert not synced
    finally:
        other.close()


def test_lost_remote_acknowledgement_does_not_duplicate_training_event(tmp_path, monkeypatch):
    db = D1DatabaseClient(account_id='account', database_id='database', api_token='test-token', local_db_path=tmp_path / 'local.sqlite')
    lost_ack = threading.Event()
    remote_path = tmp_path / 'remote.sqlite'
    def remote(sql, params):
        with sqlite3.connect(remote_path) as conn:
            conn.execute(sql, params)
        if params and params[0] == 'event' and not lost_ack.is_set():
            lost_ack.set()
            raise requests.Timeout('Acknowledgement lost after commit')
        return []
    monkeypatch.setattr(db, '_execute_remote', remote)
    try:
        with execution_scope(threading.Event()):
            db.execute('INSERT INTO agentic_events (id, session_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?)', ['event', 'session', 'agent.started', 1, '{}'])
        assert lost_ack.wait(2)
        deadline = time.monotonic() + 2
        while db._remote_retry_at == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert db.has_pending_writes
        db._remote_retry_at = 0
        db._sync_wake.set()
        while db.has_pending_writes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not db.has_pending_writes
        with sqlite3.connect(remote_path) as conn:
            assert conn.execute('SELECT COUNT(*) FROM agentic_events').fetchone()[0] == 1
    finally:
        db.close()
