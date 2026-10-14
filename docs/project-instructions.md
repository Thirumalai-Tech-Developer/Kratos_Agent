# Persistent project instructions

Create `kratos.md` in the workspace root to give Kratos project guidance for every session. `KRATOS.md` is accepted as a compatibility alias. Kratos chooses one file, prefers the lowercase name, and never combines both. It does not search parent directories or automatically create a file when instructions are missing.

The file is project guidance. Current user requests take precedence, and ordinary permissions and evidence checks still apply. Paths, `@references`, includes, and command examples remain text: loading the file does not read other files or execute commands.

Kratos loads the file at startup and session activation, then refreshes it before the next user message. Instructions stay frozen during that message and are inherited by its child agents. Changes made while a task runs apply to the next message. A continued website conversation receives one saved project-guidance update rather than another full system prompt. Opening existing history after a restart or session switch also establishes the current project guidance.

Instructions must be valid UTF-8, may include a UTF-8 BOM, and are limited to 64 KiB. Invalid or oversized files are reported and omitted from the prompt. Files that resolve outside the workspace root are rejected.

The project editor uses `GET /api/project/instructions` for status and `POST /api/project/instructions` with `content` and optional `expected_digest` to save. Saving explicitly creates `kratos.md` when absent, otherwise updates the selected root file atomically. A stale digest returns a conflict so a newer edit is preserved. Saving and checking status do not change the active task's instruction snapshot.

The status contract exposes `workspace`, `path`, `file_name`, `relative_path`, `exists`, `loaded`, `content`, `digest` (also `revision`), `bytes`, `modified_at`, `error`, and `max_bytes`. `modified_at` is a Unix timestamp; absent or unreadable revisions have a null digest. The API rejects edits while a task is active.
