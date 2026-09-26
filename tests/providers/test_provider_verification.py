"""Tests for authoritative verification pipeline and false completion defense."""

import pytest
from kratos_agent.core.verification_manager import VerificationManager


def test_verification_detects_missing_and_empty_files(tmp_path):
    vm = VerificationManager(workspace=tmp_path)

    # 1. Non-existent file
    res = vm.verify_provider_task(
        task_id="t-verif-1",
        provider="codex",
        changed_files=["missing_module.py"],
        require_files=True,
    )
    assert res.passed is False
    assert any("Missing file" in d for d in res.details)

    # 2. Empty file
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("")
    res_empty = vm.verify_provider_task(
        task_id="t-verif-2",
        provider="claude",
        changed_files=[str(empty_file)],
        require_files=True,
    )
    assert res_empty.passed is False
    assert any("Empty file" in d for d in res_empty.details)


def test_verification_validates_syntax_and_declared_outputs(tmp_path):
    vm = VerificationManager(workspace=tmp_path)

    # Create valid python file
    valid_file = tmp_path / "valid.py"
    valid_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    res = vm.verify_provider_task(
        task_id="t-verif-3",
        provider="codex",
        changed_files=[str(valid_file)],
        expected_outputs=["add"],
        declared_output="Successfully implemented add function in valid.py",
        require_files=True,
    )
    assert res.passed is True
    assert any("Python syntax OK" in d for d in res.details)

    # False completion: declared output missing required token
    res_false = vm.verify_provider_task(
        task_id="t-verif-4",
        provider="codex",
        changed_files=[str(valid_file)],
        expected_outputs=["jwt_token_validation"],
        declared_output="I am done.",
        require_files=True,
    )
    assert res_false.passed is False
    assert any("missing expected content" in d for d in res_false.details)
