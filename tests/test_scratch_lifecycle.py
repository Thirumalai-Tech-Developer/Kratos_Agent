from pathlib import Path
from unittest.mock import patch

import pytest

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.scratch_space import ScratchSpace
from kratos_agent.core.runtime_contracts import TerminalLatch


def test_scratch_alias_cannot_escape_and_leaves_existing_workspace_files(tmp_path):
    existing = tmp_path / "scratch" / "mine.py"
    existing.parent.mkdir()
    existing.write_text("existing")
    scratch = ScratchSpace()
    try:
        mapped = Path(scratch.resolve("scratch/probe.py"))
        assert mapped.is_relative_to(scratch.root)
        with pytest.raises(ValueError):
            scratch.resolve("scratch/../../outside.txt")
    finally:
        scratch.close()
    assert existing.read_text() == "existing"


@pytest.mark.parametrize("outcome", ["success", "failure", "interruption"])
def test_run_finally_cleans_scratch_on_every_exit(outcome):
    loop = AgentLoop.__new__(AgentLoop)
    captured = []
    def execute(*args):
        root = loop._scratch.root
        captured.append(root)
        (root / "scratch" / "raw.json").write_text("real extracted evidence")
        if outcome == "failure":
            raise RuntimeError("probe failed")
        if outcome == "interruption":
            raise KeyboardInterrupt()
        return "done", []
    with patch.object(loop, "_run", side_effect=execute):
        if outcome == "success":
            assert loop.run([], lambda spec, args: (True, ""))[0] == "done"
        else:
            with pytest.raises(RuntimeError if outcome == "failure" else KeyboardInterrupt):
                loop.run([], lambda spec, args: (True, ""))
    assert not captured[0].exists()
    assert loop._scratch is None


def test_explicit_retry_reopens_failure_but_preserves_completed_latch():
    latch = TerminalLatch()
    assert latch.try_set("failed", "FAILED")
    latch.begin_retry("failed")
    assert latch.try_set("failed", "COMPLETED")
    latch.begin_retry("failed")
    assert not latch.try_set("failed", "FAILED")
