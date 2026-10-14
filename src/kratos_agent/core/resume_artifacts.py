"""Recover existing task outputs for verification after a continued session."""
from pathlib import Path
from typing import Any


def resume_artifacts(session: Any, workspace: Path, goal: str) -> list[str]:
    paths: set[str] = set()
    deleted: set[str] = set()
    for turn in reversed(getattr(session, 'turns', [])):
        saved_plan = turn.get('plan') or {}
        if saved_plan.get('goal') and saved_plan['goal'] != goal:
            break
        changes = turn.get('files_changed') or {}
        deleted.update(str(path) for path in changes.get('deleted', []))
        paths.update(str(path) for key in ('created', 'modified') for path in changes.get(key, []))
        for tool in turn.get('tools_used', []):
            args = tool.get('arguments') or tool.get('args') or {}
            if tool.get('name') in ('write_file', 'edit_file', 'replace_file_content'):
                path = args.get('file_path') or args.get('target_file')
                if isinstance(path, str):
                    paths.add(path)
        # Legacy turns did not save their plan or files separately. The newest
        # explicit user task and its continuation turns define the safe boundary.
        if str(turn.get('user', '')).strip().lower() not in ('continue', 'resume', '/continue'):
            break
    root = workspace.resolve()
    retained = []
    for name in sorted(paths - deleted):
        path = (root / name).resolve()
        if path.is_relative_to(root) and path.is_file():
            retained.append(path.relative_to(root).as_posix())
    return retained
