-- Kratos Agent: Cloudflare D1 Database Schema
-- Compatible with SQLite and Cloudflare D1 Serverless SQL

-- 1. Sessions Table: High-level conversation and project session records
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'antigravity/gemini-3.7-flash-high',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_status TEXT NOT NULL DEFAULT 'idle',
    plan_json TEXT,
    files_changed_json TEXT,
    verification_status_json TEXT,
    notes_json TEXT
);

-- 2. Turns Table: Ordered conversational turns and tool usage history
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    user_query TEXT NOT NULL,
    agent_reply TEXT NOT NULL,
    tools_used_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 3. Agentic Events Table: Granular execution trace and event replay log
CREATE TABLE IF NOT EXISTS agentic_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    kind TEXT NOT NULL,
    timestamp REAL NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 4. Executed Commands Table: Shell commands run during autonomous execution
CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    returncode INTEGER NOT NULL DEFAULT 0,
    output_preview TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Performance Indices
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_session_id ON turns(session_id, turn_index ASC);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON agentic_events(session_id, timestamp ASC);
CREATE INDEX IF NOT EXISTS idx_events_kind ON agentic_events(kind);
CREATE INDEX IF NOT EXISTS idx_commands_session_id ON commands(session_id, timestamp ASC);
