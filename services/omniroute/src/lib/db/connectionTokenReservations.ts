import { randomUUID } from "node:crypto";
import { getDbInstance } from "./core";

export interface ConnectionTokenLimits { tpm?: number; tpd?: number }
export type ReservationResult = { id: string; allowed: true } | { allowed: false; resetAt: number; window: "minute" | "day" };

/** Atomic admission across processes, using UTC minute/day windows. Reservations
 * survive restarts; unknown/interrupted usage retains its estimate until expiry. */
export function reserveConnectionTokens(
  connectionId: string, estimate: number, limits: ConnectionTokenLimits, now = Date.now()
): ReservationResult {
  if (!Number.isFinite(estimate) || estimate < 0) throw new Error("Invalid token reservation estimate");
  const db = getDbInstance();
  const amount = Math.ceil(estimate);
  let result: ReservationResult = { allowed: false, resetAt: now, window: "minute" };
  db.immediate(() => {
    db.prepare("DELETE FROM connection_token_reservations WHERE created_at < ?").run(now - 2 * 86_400_000);
    for (const [window, duration, limit] of [
      ["minute", 60_000, limits.tpm], ["day", 86_400_000, limits.tpd],
    ] as const) {
      if (!limit || !Number.isFinite(limit) || limit <= 0) continue;
      const start = Math.floor(now / duration) * duration;
      const row = db.prepare("SELECT COALESCE(SUM(tokens), 0) AS used FROM connection_token_reservations WHERE connection_id = ? AND created_at >= ?")
        .get(connectionId, start) as { used: number };
      if (row.used + amount > limit) {
        result = { allowed: false, resetAt: start + duration, window };
        return;
      }
    }
    const id = randomUUID();
    db.prepare("INSERT INTO connection_token_reservations(id, connection_id, created_at, tokens) VALUES (?, ?, ?, ?)")
      .run(id, connectionId, now, amount);
    result = { allowed: true, id };
  });
  return result;
}

/** Idempotent reconciliation: duplicate terminal callbacks cannot count twice. */
export function settleConnectionTokens(id: string | null, actual: number): void {
  if (!id || !Number.isFinite(actual) || actual < 0) return;
  getDbInstance().prepare("UPDATE connection_token_reservations SET tokens = ?, settled = 1 WHERE id = ? AND settled = 0")
    .run(Math.ceil(actual), id);
}
