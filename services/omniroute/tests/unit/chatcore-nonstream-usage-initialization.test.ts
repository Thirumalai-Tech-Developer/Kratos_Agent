import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";

import { resetDbInstance } from "../../src/lib/db/core.ts";
import { handleChatCore } from "../../open-sse/handlers/chatCore.ts";

const originalFetch = globalThis.fetch;
const silentLog = { debug() {}, info() {}, warn() {}, error() {} };
afterEach(() => {
  globalThis.fetch = originalFetch;
});
after(() => {
  globalThis.fetch = originalFetch;
  resetDbInstance();
});

for (const reportedUsage of [
  undefined,
  { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6 },
]) {
  test(`successful nonstream response ${reportedUsage ? "with" : "without"} usage finishes accounting`, async () => {
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
      return Response.json({
        id: "chatcmpl-usage-init",
        object: "chat.completion",
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: "Verified answer" },
            finish_reason: "stop",
          },
        ],
        ...(reportedUsage ? { usage: reportedUsage } : {}),
      });
    };
    const body = {
      model: "usage-init-model",
      messages: [{ role: "user", content: "Hello" }],
      stream: false,
    };
    const result = await handleChatCore({
      body,
      modelInfo: { provider: "usage-init-provider", model: body.model, extendedContext: false },
      credentials: {
        apiKey: "test-only-key",
        providerSpecificData: { baseUrl: "https://usage-init.example.test/v1" },
      },
      clientRawRequest: {
        endpoint: "/v1/chat/completions",
        body,
        headers: new Headers({ accept: "application/json" }),
      },
      userAgent: "unit-test",
      isCombo: false,
      log: silentLog,
    } as Parameters<typeof handleChatCore>[0]);
    assert.equal(result.success, true);
    assert.equal(result.response.status, 200);
    assert.equal(calls, 1);
    const response = await result.response.json();
    assert.equal(response.choices[0].message.content, "Verified answer");
    if (reportedUsage) {
      assert.equal(response.usage.prompt_tokens, 4);
      assert.equal(response.usage.completion_tokens, 2);
    }
  });
}
