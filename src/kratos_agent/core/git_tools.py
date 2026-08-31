"""
Git-aware workflow tools for Kratos Agent.
Implements Claude Code + Codex + Kimi-style git integration.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def _run_git(args: List[str], cwd: Optional[str] = None, timeout: int = 30) -> Tuple[int, str, str]:
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=cwd or str(Path.cwd()), encoding="utf-8", errors="replace",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 1, "", "git not found"
    except subprocess.TimeoutExpired:
        return 1, "", f"git timed out after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


def get_git_status(cwd: Optional[str] = None) -> str:
    """Returns current git status (staged, unstaged, untracked files)."""
    rc, out, err = _run_git(["status", "--short", "--branch"], cwd=cwd)
    if rc != 0:
        return f"git status error: {err}"
    return out if out else "Working tree clean — nothing to commit."


def get_git_diff(staged: bool = False, cwd: Optional[str] = None, max_chars: int = 12000) -> str:
    """Returns the current git diff (staged or unstaged)."""
    args = ["diff", "--stat", "--patch"]
    if staged:
        args.insert(1, "--cached")
    rc, out, err = _run_git(args, cwd=cwd)
    if rc != 0:
        return f"git diff error: {err}"
    if not out:
        return "No diff found."
    return out[:max_chars] + (f"\n\n... [truncated at {max_chars} chars]" if len(out) > max_chars else "")


def get_changed_files(vs: str = "HEAD", cwd: Optional[str] = None) -> str:
    """Returns list of files changed relative to given ref."""
    rc, out, err = _run_git(["diff", "--name-status", vs], cwd=cwd)
    if rc != 0:
        rc2, out2, _ = _run_git(["ls-files", "--others", "--modified", "--deleted", "--exclude-standard"], cwd=cwd)
        return out2 if out2 else f"git diff error: {err}"
    return out if out else "No files changed."


def suggest_commit_message(diff: str = "", context: str = "", cwd: Optional[str] = None) -> str:
    """Generates a Conventional Commits style message from diff/context."""
    if not diff:
        diff = get_git_diff(staged=True, cwd=cwd) or get_git_diff(staged=False, cwd=cwd)
    lines = diff.splitlines()
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    file_matches = re.findall(r"^diff --git a/(.*) b/", diff, re.MULTILINE)
    files = [f.split("/")[-1] for f in file_matches[:3]]
    if any(k in diff.lower() for k in ("fix", "bug", "error", "exception", "crash")):
        prefix = "fix"
    elif any(k in diff.lower() for k in ("feat", "add", "new", "implement", "create")):
        prefix = "feat"
    elif any(k in diff.lower() for k in ("refactor", "simplify", "clean")):
        prefix = "refactor"
    elif any(k in diff.lower() for k in ("docs", "readme", "comment")):
        prefix = "docs"
    else:
        prefix = "chore"
    scope = files[0].replace(".py","").replace(".ts","").replace(".js","") if files else ""
    scope_str = f"({scope})" if scope else ""
    summary = context.strip() if context else f"update {', '.join(files) if files else 'codebase'} (+{added}/-{removed})"
    return f"{prefix}{scope_str}: {summary}"


def create_commit(message: str = "", stage_all: bool = True, cwd: Optional[str] = None) -> str:
    """Stages all changes and creates a git commit."""
    if stage_all:
        rc, _, err = _run_git(["add", "-A"], cwd=cwd)
        if rc != 0:
            return f"git add error: {err}"
    if not message:
        message = suggest_commit_message(cwd=cwd)
    rc, out, err = _run_git(["commit", "-m", message], cwd=cwd)
    if rc != 0:
        if "nothing to commit" in (err + out):
            return "Nothing to commit — working tree clean."
        return f"git commit error: {err}"
    return f"Committed: {message}\n{out}"


def git_push(branch: str = "", remote: str = "origin", cwd: Optional[str] = None) -> str:
    """Pushes the current branch to remote."""
    if not branch:
        rc, branch, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
        if rc != 0 or not branch:
            branch = "HEAD"
    rc, out, err = _run_git(["push", remote, branch, "--set-upstream"], cwd=cwd)
    if rc != 0:
        return f"git push error: {err}"
    return f"Pushed '{branch}' to '{remote}'.\n{out or err}"


def create_pr(title: str = "", body: str = "", base: str = "main", cwd: Optional[str] = None) -> str:
    """Creates a GitHub PR via gh CLI. Pushes branch first."""
    import subprocess as sp
    push_result = git_push(cwd=cwd)
    if "error" in push_result.lower() and "already" not in push_result.lower():
        return f"Push failed: {push_result}"
    if not title:
        title = suggest_commit_message(cwd=cwd)
    args = ["gh", "pr", "create", "--title", title, "--base", base,
            "--body", body or f"Automated PR by Kratos Agent.\n\n{title}"]
    try:
        result = sp.run(args, capture_output=True, text=True, timeout=30,
                        cwd=cwd or str(Path.cwd()), encoding="utf-8", errors="replace")
        if result.returncode != 0:
            return f"gh pr create error: {result.stderr.strip()}"
        return f"Pull Request created!\n{result.stdout.strip()}"
    except FileNotFoundError:
        return "GitHub CLI (gh) not found. Install from https://cli.github.com/"
    except Exception as exc:
        return f"PR creation error: {exc}"
