"""Turn review preserves preexisting edits and rejects stale or unsafe restores."""
import json
import subprocess
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from kratos_agent.core.change_review import (
    ChangeReview,
    ReviewConflict,
    capture_before_tool,
    checkpoint_turn,
)
from kratos_agent.web.server import KratosServer, KratosWebHandler


def test_turn_hook_captures_changes_on_failure(tmp_path):
    file = tmp_path / 'source.py'
    file.write_text('before')
    review = ChangeReview(tmp_path)
    runtime = SimpleNamespace(change_review=review, memory=SimpleNamespace(active_session=SimpleNamespace(session_id='session')))

    @checkpoint_turn
    def run(self, query):
        file.write_text('edited before failure')
        raise RuntimeError('Model failed')

    with pytest.raises(RuntimeError, match='Model failed'):
        run(runtime, 'Fix source')
    checkpoint = review.list()[0]
    assert checkpoint['session_id'] == 'session'
    assert checkpoint['changes'][0]['path'] == 'source.py'
    review.restore(checkpoint['id'], ['source.py'])
    assert file.read_text() == 'before'


def test_capture_failure_does_not_block_turn():
    def fail(*args):
        raise OSError('Read-only storage')
    runtime = SimpleNamespace(change_review=SimpleNamespace(begin=fail), memory=None)

    @checkpoint_turn
    def run(self, query):
        return 'task ran'

    assert run(runtime, 'Run') == 'task ran'


def test_deferred_checkpoint_does_not_scan_workspace_for_chat(tmp_path):
    review = ChangeReview(tmp_path)
    runtime = SimpleNamespace(change_review=review, memory=None)

    @checkpoint_turn(defer=True)
    def run(self, query):
        return 'Hello!'

    assert run(runtime, 'hii') == 'Hello!'
    assert not review.store.exists()


def test_deferred_checkpoint_preserves_edits_from_parallel_tools(tmp_path):
    review = ChangeReview(tmp_path)
    runtime = SimpleNamespace(change_review=review, memory=None)
    (tmp_path / 'source.py').write_text('user edit')

    @checkpoint_turn(defer=True)
    def run(self, query):
        workers = [threading.Thread(target=capture_before_tool, args=(self,)) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        (tmp_path / 'source.py').write_text('agent edit')
        raise RuntimeError('failed after edit')

    with pytest.raises(RuntimeError):
        run(runtime, 'continue')
    checkpoints = review.list()
    assert len(checkpoints) == 1
    review.restore(checkpoints[0]['id'], ['source.py'])
    assert (tmp_path / 'source.py').read_text() == 'user edit'


def test_cancelled_checkpoint_prevents_tool_execution(tmp_path):
    from kratos_agent.core.execution_control import execution_scope

    cancel = threading.Event()
    cancel.set()
    runtime = SimpleNamespace(change_review=ChangeReview(tmp_path), memory=None)

    @checkpoint_turn(defer=True)
    def run(self, query):
        capture_before_tool(self)
        pytest.fail('A cancelled tool must not run')

    with execution_scope(cancel), pytest.raises(InterruptedError):
        run(runtime, 'Fix source')


def test_restore_preserves_preexisting_edits_and_git_index(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    file = tmp_path / 'app.py'
    file.write_bytes(b'staged\r\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'app.py'], check=True)
    index_before = subprocess.run(['git', '-C', str(tmp_path), 'show', ':app.py'], check=True, capture_output=True).stdout
    file.write_bytes(b'my uncommitted edit\r\n')
    review = ChangeReview(tmp_path)
    pending = review.begin('Fix app', 'session')
    file.write_bytes(b'agent edit\n')
    review.finish(pending)
    assert '-my uncommitted edit' in review.diff(pending['id'], 'app.py')['diff']
    review.restore(pending['id'], ['app.py'])
    assert file.read_bytes() == b'my uncommitted edit\r\n'
    assert subprocess.run(['git', '-C', str(tmp_path), 'show', ':app.py'], check=True, capture_output=True).stdout == index_before


def test_creation_deletion_binary_and_persistence(tmp_path):
    (tmp_path / 'old.bin').write_bytes(b'\0original')
    review = ChangeReview(tmp_path)
    pending = review.begin('Replace file')
    (tmp_path / 'old.bin').unlink()
    (tmp_path / 'new.txt').write_text('new')
    review.finish(pending)
    reloaded = ChangeReview(tmp_path)
    assert reloaded.diff(pending['id'], 'old.bin')['binary']
    reloaded.restore(pending['id'], ['old.bin', 'new.txt'])
    assert (tmp_path / 'old.bin').read_bytes() == b'\0original'
    assert not (tmp_path / 'new.txt').exists()
    assert all(change['restored'] for change in reloaded.list()[0]['changes'])


def test_conflict_stops_all_selected_files(tmp_path):
    for name in ('a.txt', 'b.txt'):
        (tmp_path / name).write_text('before')
    review = ChangeReview(tmp_path)
    pending = review.begin('Change both')
    for name in ('a.txt', 'b.txt'):
        (tmp_path / name).write_text('agent')
    review.finish(pending)
    (tmp_path / 'b.txt').write_text('later user edit')
    with pytest.raises(ReviewConflict):
        review.restore(pending['id'], ['a.txt', 'b.txt'])
    assert (tmp_path / 'a.txt').read_text() == 'agent'
    assert (tmp_path / 'b.txt').read_text() == 'later user edit'


def test_secret_and_runtime_files_are_excluded(tmp_path):
    (tmp_path / '.env').write_text('secret')
    (tmp_path / 'creds.json').write_text('secret')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'library.js').write_text('dependency')
    review = ChangeReview(tmp_path)
    pending = review.begin('Task')
    assert not pending['baseline']
    (tmp_path / '.env').write_text('changed secret')
    review.finish(pending)
    assert not review.list()[0]['changes']


def test_limits_do_not_misidentify_existing_file_as_created(tmp_path):
    review = ChangeReview(tmp_path)
    review.MAX_FILE = 8
    (tmp_path / 'large.txt').write_text('already larger than limit')
    pending = review.begin('Shrink file')
    (tmp_path / 'large.txt').write_text('small')
    review.finish(pending)
    assert review.list()[0]['skipped'] == ['large.txt']
    assert not review.list()[0]['changes']


def test_rejects_traversal_and_unknown_restore(tmp_path):
    review = ChangeReview(tmp_path)
    for name in ('../outside', '.kratos/state', '.env', 'node_modules/app'):
        with pytest.raises(ValueError):
            review._path(name)
    pending = review.begin('Empty')
    review.finish(pending)
    with pytest.raises(ValueError):
        review.restore(pending['id'], ['unknown'])
    with pytest.raises(ValueError):
        review.diff('../outside', 'app.py')


def test_link_replacement_cannot_restore_outside_workspace(tmp_path):
    file = tmp_path / 'source.txt'
    file.write_text('before')
    review = ChangeReview(tmp_path)
    pending = review.begin('Modify')
    file.write_text('after')
    review.finish(pending)
    outside = tmp_path.parent / f'{tmp_path.name}-outside.txt'
    outside.write_text('outside')
    file.unlink()
    try:
        file.symlink_to(outside)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    with pytest.raises(ValueError):
        review.restore(pending['id'], ['source.txt'])
    assert outside.read_text() == 'outside'


def test_review_http_routes_and_busy_guard(tmp_path, monkeypatch):
    monkeypatch.delenv('KRATOS_INTERNAL_TOKEN', raising=False)
    file = tmp_path / 'app.py'
    file.write_text('before')
    review = ChangeReview(tmp_path)
    pending = review.begin('Task')
    file.write_text('after')
    review.finish(pending)
    runtime = SimpleNamespace(change_review=review, _turn_lock=threading.RLock())
    server = KratosServer(('127.0.0.1', 0), KratosWebHandler, object(), object(), runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/api/changes') as response:
            assert json.load(response)['checkpoints'][0]['id'] == pending['id']
        with urlopen(base + f'/api/changes/diff?checkpoint={pending["id"]}&path=app.py') as response:
            assert '+after' in json.load(response)['diff']
        request = Request(base + '/api/changes/restore', method='POST', headers={'Content-Type': 'application/json'},
                          data=json.dumps({'checkpoint': pending['id'], 'paths': ['app.py']}).encode())
        server.turn_lock.acquire()
        try:
            with pytest.raises(HTTPError) as failure:
                urlopen(request)
            assert failure.value.code == 409
        finally:
            server.turn_lock.release()
        with urlopen(request) as response:
            assert json.load(response)['restored'] == ['app.py']
        assert file.read_text() == 'before'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
