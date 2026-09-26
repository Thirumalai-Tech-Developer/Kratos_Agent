"""Tests for cross-provider security boundary, secret redaction, and resource locking."""

import pytest
from kratos_agent.providers.events import redact_secrets
from kratos_agent.providers.router import ResourceLockManager


def test_secret_redaction_cross_boundary():
    sensitive_prompt = "Execute curl with Authorization: Bearer secret_token_xyz_123456789 and api_key=super_secret_998877"
    safe = redact_secrets(sensitive_prompt)
    assert "secret_token_xyz" not in safe
    assert "super_secret_998877" not in safe
    assert "[REDACTED]" in safe


@pytest.mark.asyncio
async def test_resource_lock_prevents_conflicting_writes():
    lock_mgr = ResourceLockManager()

    # Task A acquires write lock on file foo.py
    acquired_a = await lock_mgr.acquire(
        task_id="task-A",
        writes=["src/auth/foo.py"],
    )
    assert acquired_a is True

    # Task B attempts to write to same file -> Must be rejected
    acquired_b = await lock_mgr.acquire(
        task_id="task-B",
        writes=["src/auth/foo.py"],
    )
    assert acquired_b is False

    # Task C attempts to read file being written by Task A -> Must be rejected
    acquired_c = await lock_mgr.acquire(
        task_id="task-C",
        reads=["src/auth/foo.py"],
    )
    assert acquired_c is False

    # Once Task A finishes and releases lock, Task B can acquire
    await lock_mgr.release("task-A")
    acquired_b_retry = await lock_mgr.acquire(
        task_id="task-B",
        writes=["src/auth/foo.py"],
    )
    assert acquired_b_retry is True
