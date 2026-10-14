import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const directory = fs.mkdtempSync(path.join(os.tmpdir(), "omniroute-agy-abortable-retry-"));
process.env.DATA_DIR = directory;
process.env.API_KEY_SECRET = "agy-abortable-retry-test-secret";

const { AntigravityExecutor } = await import("../../open-sse/executors/antigravity.ts");
const { resetDbInstance } = await import("../../src/lib/db/core.ts");

test.after(() => {
  resetDbInstance();
  fs.rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
});

for (const status of [429, 503]) {
  test(`abort interrupts the ${status} retry wait before another upstream attempt`, async () => {
    const controller = new AbortController();
    const reason = new Error("request cancelled");
    const executor = new AntigravityExecutor();
    const pending = executor.handleAntigravityRateLimit({
      response: new Response(JSON.stringify({ error: { message: "Too many requests" } }), {
        status,
        headers: { "content-type": "application/json", "retry-after": "30" },
      }),
      log: { debug() {}, info() {}, warn() {}, error() {} },
      urlIndex: 0,
      retryAttemptsByUrl: { 0: 0 },
      fallbackCount: 2,
      url: "https://example.com/test",
      headers: {},
      finalHeaders: {},
      transformedBody: {},
      credentials: { accessToken: "test-token" },
      stream: true,
      signal: controller.signal,
      accountId: "test-account",
      creditsMode: "off",
      creditsRetryState: { attempted: false },
    });
    setTimeout(() => controller.abort(reason), 20);
    let guard: ReturnType<typeof setTimeout> | undefined;
    try {
      const outcome = await Promise.race([
        pending.then(
          () => "retry",
          (error: unknown) => error
        ),
        new Promise((resolve) => {
          guard = setTimeout(() => resolve("still waiting"), 500);
        }),
      ]);
      assert.equal(outcome, reason);
    } finally {
      clearTimeout(guard);
    }
  });
}
