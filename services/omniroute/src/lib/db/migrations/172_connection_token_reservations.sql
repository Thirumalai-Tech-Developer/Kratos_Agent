CREATE TABLE IF NOT EXISTS connection_token_reservations (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  tokens INTEGER NOT NULL CHECK (tokens >= 0),
  settled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_connection_token_reservations_window
  ON connection_token_reservations(connection_id, created_at);
