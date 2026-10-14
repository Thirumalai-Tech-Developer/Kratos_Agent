import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import psutil
import pytest

from kratos_agent.brain.account_store import AccountStore
from kratos_agent.brain.browser_executor_worker import BrowserExecutorWorkers
from kratos_agent.brain.chatgpt_web import ChatGPTWebAccounts
from kratos_agent.brain.config import BrainError, BrainTimeoutError


@pytest.fixture
def worker_command(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the private executor protocol check")
    helper = tmp_path / "worker.mjs"
    helper.write_text(
        """
import readline from 'node:readline';
import { spawn } from 'node:child_process';
let count = 0;
for await (const line of readline.createInterface({ input: process.stdin })) {
  const frame = JSON.parse(line); count += 1;
  const request = frame.request;
  if (request.delay) {
    spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
    await new Promise(resolve => setTimeout(resolve, 60000));
  }
  if (request.invalid === 'json') { process.stdout.write('private-session-not-json\\n'); continue; }
  if (request.invalid === 'oversize') { process.stdout.write('x'.repeat(10000) + '\\n'); continue; }
  if (request.invalid === 'partial') { process.stdout.write('{}'); process.exit(0); }
  if (request.invalid === 'utf8') { process.stdout.write(Buffer.from([255, 10])); continue; }
  if (request.invalid === 'id') frame.request_id = 'stale-turn';
  const result = request.invalid === 'result' ? 'private-session-string' : { pid: process.pid, count, text: request.text };
  process.stderr.write('private-session-diagnostic\\n');
  process.stdout.write(JSON.stringify({ request_id: frame.request_id, result }) + '\\n');
}
""",
        encoding="utf-8",
    )
    return [node, str(helper)]


def submit(
    pool, worker_command, tmp_path, request, *, account="one", timeout=5, cancel=None
):
    return json.loads(
        pool.request(
            account,
            tmp_path,
            request,
            command=worker_command,
            cwd=tmp_path,
            env=dict(os.environ),
            timeout=timeout,
            cancel=cancel,
        )
    )


def test_consecutive_turns_use_one_private_process(tmp_path, worker_command, caplog):
    pool = BrowserExecutorWorkers()
    try:
        first = submit(pool, worker_command, tmp_path, {"text": "private-cookie-value"})
        second = submit(pool, worker_command, tmp_path, {"text": "continued"})
        assert first["pid"] == second["pid"]
        assert [first["count"], second["count"]] == [1, 2]
        assert "private-cookie-value" not in " ".join(
            psutil.Process(first["pid"]).cmdline()
        )
        assert "private-session" not in caplog.text
    finally:
        pool.close()
    assert not psutil.pid_exists(first["pid"])


@pytest.mark.parametrize(
    "invalid", ["json", "id", "result", "oversize", "partial", "utf8"]
)
def test_invalid_frames_invalidate_without_replaying_the_turn(
    tmp_path, worker_command, invalid, monkeypatch
):
    monkeypatch.setattr(
        "kratos_agent.brain.browser_executor_worker.MAX_FRAME_BYTES", 4096
    )
    pool = BrowserExecutorWorkers()
    try:
        with pytest.raises(BrainError, match="invalid result") as caught:
            submit(pool, worker_command, tmp_path, {"invalid": invalid})
        assert "private-session" not in str(caught.value)
        assert pool.workers == {}
        recovered = submit(
            pool, worker_command, tmp_path, {"text": "new explicit request"}
        )
        assert recovered["count"] == 1
    finally:
        pool.close()


def test_concurrent_turns_are_serialized_and_correlated(tmp_path, worker_command):
    pool = BrowserExecutorWorkers()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit, pool, worker_command, tmp_path, {"text": text})
                for text in ["first", "second"]
            ]
            results = [future.result(timeout=5) for future in futures]
        assert results[0]["pid"] == results[1]["pid"]
        assert [result["text"] for result in results] == ["first", "second"]
        assert sorted(result["count"] for result in results) == [1, 2]
    finally:
        pool.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_deadlines_and_stop_kill_owned_worker_and_children_only(
    tmp_path, worker_command, cancelled
):
    pool = BrowserExecutorWorkers()
    good = submit(
        pool, worker_command, tmp_path, {"text": "keep alive"}, account="unrelated"
    )
    cancel = threading.Event()
    errors = []

    def run():
        try:
            submit(
                pool,
                worker_command,
                tmp_path,
                {"delay": True},
                account="blocked",
                timeout=1,
                cancel=cancel,
            )
        except BrainError as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    blocked_pid = None
    children = []
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        with pool.lock:
            blocked = pool.workers.get(("blocked", str(tmp_path.resolve())))
            if blocked:
                blocked_pid = blocked.process.pid
        if blocked_pid and psutil.pid_exists(blocked_pid):
            children = psutil.Process(blocked_pid).children()
            if children:
                break
        time.sleep(0.02)
    assert blocked_pid is not None and children
    started = time.monotonic()
    if cancelled:
        cancel.set()
    thread.join(timeout=3)
    try:
        assert not thread.is_alive()
        assert errors and (
            "cancelled" in str(errors[0])
            if cancelled
            else isinstance(errors[0], BrainTimeoutError)
        )
        assert time.monotonic() - started < 2
        assert not psutil.pid_exists(blocked_pid)
        assert all(not child.is_running() for child in children)
        assert psutil.pid_exists(good["pid"])
        recovered = submit(
            pool, worker_command, tmp_path, {"text": "next request"}, account="blocked"
        )
        assert recovered["pid"] != blocked_pid and recovered["count"] == 1
    finally:
        pool.close()


def test_worker_cache_is_bounded_and_idle_workers_close(tmp_path, worker_command):
    pool = BrowserExecutorWorkers(
        max_workers=1, idle_timeout=0.15, cleanup_interval=0.02
    )
    try:
        first = submit(pool, worker_command, tmp_path, {"text": "one"})
        second = submit(pool, worker_command, tmp_path, {"text": "two"}, account="two")
        assert first["pid"] != second["pid"]
        assert not psutil.pid_exists(first["pid"])
        deadline = time.monotonic() + 2
        while psutil.pid_exists(second["pid"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not psutil.pid_exists(second["pid"])
        assert pool.workers == {}
    finally:
        pool.close()


def storage():
    return {
        "cookies": [
            {
                "name": "session",
                "value": "private-cookie",
                "domain": "chatgpt.com",
                "path": "/",
            }
        ],
        "origins": [],
    }


def test_protected_chatgpt_completions_use_persistent_worker_and_shared_validation(
    tmp_path, monkeypatch
):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path / "auth"))
    manager._executor_workers = Mock()
    manager._executor_workers.request.return_value = json.dumps(
        {"text": "answer", "storage_state": storage()}
    ).encode()
    monkeypatch.setattr("kratos_agent.brain.chatgpt_web.shutil.which", lambda _: "node")
    monkeypatch.setattr(
        "kratos_agent.brain.chatgpt_web.subprocess.Popen",
        Mock(side_effect=AssertionError("one-shot launch")),
    )
    result = manager._run_bridge(
        {"mode": "complete", "account_id": "one", "storage_state": storage()},
        tmp_path,
        2,
    )
    assert result["text"] == "answer"
    args, kwargs = manager._executor_workers.request.call_args
    assert args[:2] == ("one", tmp_path)
    assert kwargs["command"][-1] == "--persistent"
    assert "private-cookie" not in " ".join(kwargs["command"])
    manager._executor_workers.request.return_value = (
        b'{"error":"browser_turn_failed","status":403,"phase":"submission"}'
    )
    with pytest.raises(BrainError) as caught:
        manager._run_bridge(
            {"mode": "complete", "account_id": "one", "storage_state": storage()},
            tmp_path,
            2,
        )
    assert (
        caught.value.code == "browser_turn_failed"
        and caught.value.phase == "submission"
    )


def test_disconnect_closes_only_that_accounts_worker(tmp_path):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path / "auth"))
    state = manager.store.read()
    state["web_accounts"] = {"one": {"storage_state": storage()}}
    manager.store.write(state)
    manager._executor_workers = Mock()
    manager.sign_out("one")
    manager._executor_workers.close.assert_called_once_with("one")
    assert "storage_state" not in manager.store.read()["web_accounts"]["one"]
