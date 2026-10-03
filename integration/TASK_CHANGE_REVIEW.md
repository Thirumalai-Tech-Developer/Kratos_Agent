# Task checkpoints and change review

Restart Studio after installing the backend changes:

```powershell
uv run --no-sync kratos-studio run --workspace .
```

Use `--cli` to enter the terminal interface. Agent turns in both interfaces capture
the workspace before execution and compare it afterward, including failed or cancelled
turns. Existing uncommitted edits are the baseline. Git's staging area is not changed.

## Web interface

Open **Changes** or choose **Review task changes** in the Ctrl+K command palette.
Select a checkpoint and file to see its unified diff. Select files, click **Restore
selected**, and confirm to restore their saved state before the task. Newly created
files are removed. Later modifications to any selected file block the entire request
before any selected files are changed. Restoration is disabled during an active task.

## CLI

```text
/changes
/diff latest src/app.py
/undo latest src/app.py --yes
```

Use a checkpoint ID from `/changes` instead of `latest` for an earlier task. Paths
containing spaces can be quoted. `/undo` restores one explicitly selected file.

## Scope and storage

- Local checkpoints live in `.kratos/checkpoints/`; they survive restarts.
- Retains 30 completed task checkpoints. This is short-term undo, not a backup service.
- Git workspaces capture tracked files and untracked files not excluded by Git.
  Other workspaces use a directory scan.
- Files are limited to 1 MB each and 256 MB per capture phase; workspaces exceeding
  25,000 supported files are not checkpointed. Capture failures are logged without
  interrupting agent execution. Skipped files appear in the review panel.
- Baseline bytes are held in memory during a task; only changed files are saved to
  disk when the turn finishes. A process crash during execution has no completed checkpoint.
- Runtime, dependencies, build outputs, linked paths, known credential files and
  databases are excluded. This does not detect every secret embedded in source code.
- Binary files can be restored; text previews are limited to 6,000 diff lines.
- Checkpoints record changes observed during a turn, including outside edits made
  concurrently. They do not attribute every edit to a specific tool or author.
- External side effects (commands, browser actions, database updates) are not undone.
- Source restoration does not rewind the conversation or rebuild the application.

Verification: backend tests cover original bytes and Git index preservation,
creation/deletion, persistent and binary snapshots, all-file conflict preflight,
credential exclusions, size limits, traversal rejection, and HTTP busy protection.
Playwright checks cover diff display, confirmation/cancel, conflicts, successful
restore, and mobile layout using synthetic checkpoint responses.
