import { test, after } from "node:test";
import assert from "node:assert/strict";
import { reserveConnectionTokens, settleConnectionTokens } from "../../src/lib/db/connectionTokenReservations";
import { resetDbInstance } from "../../src/lib/db/core";

const now = Date.UTC(2026, 8, 29, 12, 0, 5);
test("reservations reject over-budget concurrency before dispatch", () => {
  const first = reserveConnectionTokens("concurrent", 70, { tpm: 100 }, now);
  assert.equal(first.allowed, true);
  assert.equal(reserveConnectionTokens("concurrent", 40, { tpm: 100 }, now).allowed, false);
  assert.equal(reserveConnectionTokens("concurrent", 30, { tpm: 100 }, now).allowed, true);
});

test("actual usage replaces reservation exactly once", () => {
  const first = reserveConnectionTokens("settle", 90, { tpm: 100 }, now);
  assert.ok(first.allowed);
  settleConnectionTokens(first.id, 20);
  settleConnectionTokens(first.id, 80);
  assert.equal(reserveConnectionTokens("settle", 80, { tpm: 100 }, now).allowed, true);
  assert.equal(reserveConnectionTokens("settle", 1, { tpm: 100 }, now).allowed, false);
});

test("day budget survives minute reset and database reopen", () => {
  reserveConnectionTokens("restart", 70, { tpm: 100, tpd: 100 }, now);
  resetDbInstance();
  const result = reserveConnectionTokens("restart", 40, { tpm: 100, tpd: 100 }, now + 60_000);
  assert.equal(result.allowed, false);
  if (!result.allowed) assert.equal(result.window, "day");
  assert.equal(reserveConnectionTokens("restart", 40, { tpm: 100, tpd: 100 }, now + 86_400_000).allowed, true);
});

test("unknown usage remains reserved and connections remain independent", () => {
  reserveConnectionTokens("unknown", 100, { tpm: 100 }, now);
  assert.equal(reserveConnectionTokens("unknown", 1, { tpm: 100 }, now).allowed, false);
  assert.equal(reserveConnectionTokens("other", 100, { tpm: 100 }, now).allowed, true);
});

after(() => resetDbInstance());


test("connection limiter brands token rejection as local 429", async () => {
  const limiter = await import("../../open-sse/services/rateLimitManager");
  const { getTrustedLocalRateLimitError } = await import("../../open-sse/services/rateLimitManager/errors");
  limiter.enableRateLimitProtection("integration-limit");
  limiter.refreshConnectionRateLimits("integration-limit", { tpm: 100 });
  try {
    assert.ok(limiter.reserveConnectionTokenBudget("integration-limit", 80));
    assert.throws(() => limiter.reserveConnectionTokenBudget("integration-limit", 30), (error) => {
      assert.deepEqual(getTrustedLocalRateLimitError(error), { code: "RATE_LIMIT_TOKEN_BUDGET", status: 429 });
      return true;
    });
    limiter.disableRateLimitProtection("integration-limit");
    assert.equal(limiter.reserveConnectionTokenBudget("integration-limit", 1000), null);
  } finally {
    await limiter.__resetRateLimitManagerForTests();
  }
});
