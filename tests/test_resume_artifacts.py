from types import SimpleNamespace

from kratos_agent.core.resume_artifacts import resume_artifacts


def test_resume_uses_existing_outputs_from_the_same_task(tmp_path):
    (tmp_path / 'app.py').write_text('print(42)')
    session = SimpleNamespace(turns=[
        {'user': 'Create app.py', 'plan': {'goal': 'Build app'}, 'files_changed': {'created': ['app.py']}, 'tools_used': []},
        {'user': 'continue', 'plan': {'goal': 'Build app'}, 'files_changed': {'created': []}, 'tools_used': []},
    ])
    assert resume_artifacts(session, tmp_path, 'Build app') == ['app.py']


def test_legacy_turns_restore_written_outputs_but_skip_deleted_helpers(tmp_path):
    (tmp_path / 'app.py').write_text('print(42)')
    session = SimpleNamespace(turns=[{'user': 'Create app', 'tools_used': [
        {'name': 'write_file', 'arguments': {'file_path': 'app.py'}},
        {'name': 'write_file', 'arguments': {'file_path': 'temporary-check.py'}},
    ]}, {'user': 'continue', 'tools_used': []}])
    assert resume_artifacts(session, tmp_path, 'Build app') == ['app.py']


def test_resume_does_not_claim_files_from_an_unrelated_task(tmp_path):
    (tmp_path / 'other.py').write_text('other work')
    session = SimpleNamespace(turns=[{'user': 'Other task', 'plan': {'goal': 'Other task'}, 'files_changed': {'created': ['other.py']}}])
    assert resume_artifacts(session, tmp_path, 'Build app') == []


def test_resume_keeps_deleted_files_and_outside_paths_out_of_verification(tmp_path):
    (tmp_path / 'old.py').write_text('old file')
    session = SimpleNamespace(turns=[{'user': 'Build app', 'files_changed': {'created': ['old.py', '../outside.py']}},
                                     {'user': 'continue', 'files_changed': {'deleted': ['old.py']}}])
    assert resume_artifacts(session, tmp_path, 'Build app') == []
