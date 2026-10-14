import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from kratos_agent.web.user_workers import UserWorkerError, UserWorkerPool, validate_profile


def test_owner_keeps_existing_workspace_and_persists_across_restart(tmp_path):
    pool = UserWorkerPool(tmp_path)
    assert pool.route('a' * 32) is None
    assert UserWorkerPool(tmp_path).route('a' * 32) is None
    assert json.loads((tmp_path / '.kratos/users/owner.json').read_text())['profile'] == 'a' * 32


@pytest.mark.parametrize('profile', ['../escape', 'a' * 33, 'A' * 32, '', 'a&profile=b'])
def test_profile_cannot_escape_the_user_storage_directory(profile):
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_parallel_requests_create_only_one_worker_per_profile(tmp_path):
    pool = UserWorkerPool(tmp_path)
    pool.route('a' * 32)
    worker = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
    pool._start = Mock(return_value=worker)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(pool.route, ['b' * 32] * 8))
    assert all(result is worker for result in results)
    pool._start.assert_called_once_with('b' * 32)


def test_worker_capacity_is_bounded_without_affecting_existing_users(tmp_path):
    pool = UserWorkerPool(tmp_path, max_users=2)
    pool.route('a' * 32)
    worker = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
    pool._start = Mock(return_value=worker)
    assert pool.route('b' * 32) is worker
    with pytest.raises(UserWorkerError):
        pool.route('c' * 32)
    assert pool.route('a' * 32) is None
    assert pool.route('b' * 32) is worker


def test_child_workers_have_independent_storage_and_cancel_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv('KRATOS_INTERNAL_TOKEN', 'parent-secret')
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'shared-cloud-secret')
    pool = UserWorkerPool(tmp_path)
    with patch('kratos_agent.web.user_workers.subprocess.Popen') as start:
        pool._start('b' * 32)
        pool._start('c' * 32)
    first, second = start.call_args_list
    assert first.kwargs['cwd'] != second.kwargs['cwd']
    assert first.kwargs['env']['KRATOS_INTERNAL_TOKEN'] != second.kwargs['env']['KRATOS_INTERNAL_TOKEN']
    assert first.kwargs['env']['KRATOS_INTERNAL_TOKEN'] != 'parent-secret'
    assert first.kwargs['env']['CLOUDFLARE_API_TOKEN'] == ''
    assert first.kwargs['env']['KRATOS_DISABLE_LIVE'] == '1'
    assert first.kwargs['env']['KRATOS_COMPUTER_USE_MCP'] == '0'


def test_crashed_profile_worker_restarts_with_same_storage_identity(tmp_path):
    pool = UserWorkerPool(tmp_path)
    pool.route('a' * 32)
    old = SimpleNamespace(process=SimpleNamespace(poll=lambda: 1))
    replacement = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
    pool._workers['b' * 32] = old
    pool._start = Mock(return_value=replacement)
    assert pool.route('b' * 32) is replacement
    pool._start.assert_called_once_with('b' * 32)
