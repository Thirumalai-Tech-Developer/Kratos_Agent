// @ts-nocheck
import test from "node:test";
import assert from "node:assert/strict";

const dsMod = await import("../../open-sse/executors/deepseek-web.ts");
const {
  DeepSeekWebExecutor,
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
  getRandomPromptLimit,
} = dsMod;

const POW_CHALLENGE = {
  algorithm: "DeepSeekHashV1",
  challenge: "311b26ae1e0fe7375e242958ce46db5552a6c67fea3f96880dcd846c63a74286",
  salt: "1122334455667788",
  signature: "sig123",
  difficulty: 1,
  expire_at: 1778891543095,
  expire_after: 300000,
  target_path: "/api/v0/chat/completion",
};

const OK_SSE = [
  "event: ready\n",
  'data: {"request_message_id":1,"response_message_id":2}\n',
  "\n",
  'data: {"v":{"response":{"message_id":2,"fragments":[{"id":1,"type":"RESPONSE","content":"Hello"}]}}}\n',
  "\n",
  'data: {"p":"response/status","o":"SET","v":"FINISHED"}\n',
  "\n",
  "event: close\n",
  'data: {"click_behavior":"none"}\n',
].join("");

function installMock(completionOutcomes = []) {
  const original = globalThis.fetch;
  const calls = {
    create: 0,
    delete: 0,
    completion: 0,
    sessionIdsUsed: [] as string[],
  };
  let outcomeIdx = 0;
  dsMod.tokenCache?.clear();
  dsMod.sessionCache?.clear();

  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url);
    if (u.includes("/users/current")) {
      return new Response(
        JSON.stringify({ code: 0, data: { biz_data: { token: "test-token" } } }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (u.includes("/chat_session/create")) {
      calls.create += 1;
      return new Response(
        JSON.stringify({
          code: 0,
          data: { biz_data: { chat_session: { id: `session-page-${calls.create}` } } },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (u.includes("/chat_session/delete")) {
      calls.delete += 1;
      return new Response(JSON.stringify({ code: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (u.includes("/create_pow_challenge")) {
      return new Response(
        JSON.stringify({ code: 0, data: { biz_data: { challenge: POW_CHALLENGE } } }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (u.includes("/chat/completion")) {
      calls.completion += 1;
      try {
        const body = JSON.parse(opts.body);
        calls.sessionIdsUsed.push(body.chat_session_id);
      } catch {
        // ignore
      }
      const outcome = completionOutcomes[outcomeIdx++] ?? "ok";
      if (outcome === "fail") {
        return new Response(JSON.stringify({ error: "server error" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(new TextEncoder().encode(OK_SSE), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    }
    return new Response("not found", { status: 404 });
  };

  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
      dsMod.tokenCache?.clear();
      dsMod.sessionCache?.clear();
    },
  };
}

async function sendPrompt(executor, token = "user-1", providerSpecificData = {}, stream = false) {
  const result = await executor.execute({
    model: "default",
    body: { messages: [{ role: "user", content: "test prompt" }] },
    stream,
    credentials: { apiKey: token, providerSpecificData },
    signal: AbortSignal.timeout(10000),
  });
  if (result?.response) {
    await result.response.text();
  }
  return result;
}

test("getRandomPromptLimit returns value between min and max inclusive", () => {
  assert.equal(DEFAULT_PAGE_MIN_PROMPTS, 10);
  assert.equal(DEFAULT_PAGE_MAX_PROMPTS, 10);
  for (let i = 0; i < 50; i++) {
    const limit = getRandomPromptLimit(5, 7);
    assert.ok(limit >= 5 && limit <= 7, `limit ${limit} must be between 5 and 7`);
  }
});

test("deepseek-web: chats with same page for at least 5 prompts without deleting", async () => {
  const mock = installMock();
  try {
    const executor = new DeepSeekWebExecutor();
    // Send 5 prompts consecutively
    for (let i = 1; i <= 5; i++) {
      await sendPrompt(executor, "user-session-5");
    }

    // Must have used the same page for the first 5 prompts
    assert.equal(mock.calls.create, 1, "Should only create 1 page session for the first 5 prompts");
    assert.equal(mock.calls.sessionIdsUsed.length, 5);
    const firstSessionId = mock.calls.sessionIdsUsed[0];
    for (let i = 0; i < 5; i++) {
      assert.equal(mock.calls.sessionIdsUsed[i], firstSessionId, `Prompt ${i + 1} must use same page`);
    }

    // Pages must remain: chat_session/delete must NEVER be called
    assert.equal(mock.calls.delete, 0, "Pages must remain on DeepSeek; delete must not be called");
  } finally {
    mock.restore();
  }
});

test("deepseek-web: rotates to new page after prompt limit (configurable min/max)", async () => {
  const mock = installMock();
  try {
    const executor = new DeepSeekWebExecutor();
    const psd = { minPromptsPerPage: 3, maxPromptsPerPage: 3 };

    // Send 6 prompts with a fixed limit of 3 prompts per page
    for (let i = 1; i <= 6; i++) {
      await sendPrompt(executor, "user-rotate", psd);
    }

    assert.equal(mock.calls.create, 2, "Should create 2 sessions (rotated after 3 prompts)");
    assert.equal(mock.calls.sessionIdsUsed.length, 6);

    // First 3 prompts use session 1
    assert.equal(mock.calls.sessionIdsUsed[0], "session-page-1");
    assert.equal(mock.calls.sessionIdsUsed[1], "session-page-1");
    assert.equal(mock.calls.sessionIdsUsed[2], "session-page-1");

    // Next 3 prompts use session 2
    assert.equal(mock.calls.sessionIdsUsed[3], "session-page-2");
    assert.equal(mock.calls.sessionIdsUsed[4], "session-page-2");
    assert.equal(mock.calls.sessionIdsUsed[5], "session-page-2");

    // Pages remain on DeepSeek
    assert.equal(mock.calls.delete, 0, "Pages must not be deleted upon rotation");
  } finally {
    mock.restore();
  }
});

test("deepseek-web: streaming responses also preserve pages without deleting", async () => {
  const mock = installMock();
  try {
    const executor = new DeepSeekWebExecutor();
    for (let i = 1; i <= 3; i++) {
      await sendPrompt(executor, "user-stream", {}, true);
    }
    assert.equal(mock.calls.create, 1, "Single session reused across streams");
    assert.equal(mock.calls.delete, 0, "Streaming responses must not delete the session");
  } finally {
    mock.restore();
  }
});

test("deepseek-web: reused session failure retries once with a fresh page without deleting old page", async () => {
  // 1st call ok -> cached. 2nd call fails on reuse -> recovers with fresh session -> ok
  const mock = installMock(["ok", "fail", "ok"]);
  try {
    const executor = new DeepSeekWebExecutor();
    const r1 = await sendPrompt(executor, "user-recover");
    assert.ok(r1.response.ok);

    const r2 = await sendPrompt(executor, "user-recover");
    assert.ok(r2.response.ok, "Second call recovers via fresh session");

    assert.equal(mock.calls.create, 2, "Created initial page + fresh retry page");
    assert.equal(mock.calls.delete, 0, "Failed session is not deleted on DeepSeek");
  } finally {
    mock.restore();
  }
});

test("deepseek-web: explicit deleteSessionAfterUse=true opts into legacy deletion", async () => {
  const mock = installMock();
  try {
    const executor = new DeepSeekWebExecutor();
    await sendPrompt(executor, "user-optin-delete", { deleteSessionAfterUse: true });
    assert.equal(mock.calls.create, 1);
    assert.equal(mock.calls.delete, 1, "deleteSessionAfterUse: true triggers deletion");
  } finally {
    mock.restore();
  }
});
