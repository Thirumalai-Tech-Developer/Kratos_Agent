import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  ZaiWebExecutor,
  zaiSessionRotator,
} from "../../open-sse/executors/zai-web.ts";
import {
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
} from "../../open-sse/services/webSessionRotator.ts";

const TEST_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6InVzZXItcm90YXRpb24tMTIzIn0.signature";
const TEST_CREDENTIAL = `token=${TEST_TOKEN}; captcha_verify_param=test-proof`;

describe("ZaiWebExecutor Antiban Page Rotation & Session Reuse", () => {
  beforeEach(() => {
    zaiSessionRotator.clear();
  });

  it("reuses the same chat page across consecutive prompts within limit", async () => {
    const executor = new ZaiWebExecutor();
    let newChatCallCount = 0;
    const createdChatIds: string[] = [];
    const completionChatIds: string[] = [];

    const mockFetch = (async (url: string | URL | Request, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/v1/chats/new")) {
        newChatCallCount++;
        const chatId = `chat-session-${newChatCallCount}`;
        createdChatIds.push(chatId);
        return new Response(JSON.stringify({ id: chatId }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/api/v2/chat/completions")) {
        const body = JSON.parse(String(init?.body));
        completionChatIds.push(body.chat_id);
        return new Response(
          'data: {"event":"chat:completion","data":{"phase":"answer","delta_content":"hello"}}\n\ndata: [DONE]\n\n',
          {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }
        );
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      // Send 5 prompts with fixed limit of 5
      for (let i = 1; i <= 5; i++) {
        const res = await executor.execute({
          model: "GLM-5.1",
          body: {
            model: "GLM-5.1",
            messages: [{ role: "user", content: `prompt ${i}` }],
          },
          credentials: {
            apiKey: TEST_CREDENTIAL,
            providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
          },
          stream: false,
          signal: null,
        } as never);

        assert.equal(res.response.status, 200);
      }

      // Exactly 1 new chat created for the first 5 prompts
      assert.equal(newChatCallCount, 1);
      assert.equal(createdChatIds[0], "chat-session-1");
      // All 5 completion requests used chat-session-1
      assert.equal(completionChatIds.length, 5);
      for (const id of completionChatIds) {
        assert.equal(id, "chat-session-1");
      }

      // 6th prompt rotates to a fresh chat page
      const res6 = await executor.execute({
        model: "GLM-5.1",
        body: {
          model: "GLM-5.1",
          messages: [{ role: "user", content: "prompt 6" }],
        },
        credentials: {
          apiKey: TEST_CREDENTIAL,
          providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
        },
        stream: false,
        signal: null,
      } as never);

      assert.equal(res6.response.status, 200);
      assert.equal(newChatCallCount, 2);
      assert.equal(createdChatIds[1], "chat-session-2");
      assert.equal(completionChatIds[5], "chat-session-2");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("recovers from a stale reused chat by creating a fresh one and retrying", async () => {
    const executor = new ZaiWebExecutor();
    let newChatCallCount = 0;
    let completionCallCount = 0;

    const mockFetch = (async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/v1/chats/new")) {
        newChatCallCount++;
        return new Response(JSON.stringify({ id: `chat-session-${newChatCallCount}` }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/api/v2/chat/completions")) {
        completionCallCount++;
        // First completion succeeds, second fails with 404 (stale chat), third (retry) succeeds
        if (completionCallCount === 2) {
          return new Response(JSON.stringify({ message: "chat not found" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(
          'data: {"event":"chat:completion","data":{"phase":"answer","delta_content":"recovered"}}\n\ndata: [DONE]\n\n',
          {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }
        );
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      // 1st prompt creates chat-session-1
      const res1 = await executor.execute({
        model: "GLM-5.1",
        body: { messages: [{ role: "user", content: "first" }] },
        credentials: { apiKey: TEST_CREDENTIAL },
        stream: false,
        signal: null,
      } as never);
      assert.equal(res1.response.status, 200);
      assert.equal(newChatCallCount, 1);

      // 2nd prompt: reused chat returns 404, should recover with chat-session-2 and succeed
      const res2 = await executor.execute({
        model: "GLM-5.1",
        body: { messages: [{ role: "user", content: "second" }] },
        credentials: { apiKey: TEST_CREDENTIAL },
        stream: false,
        signal: null,
      } as never);
      assert.equal(res2.response.status, 200);
      assert.equal(newChatCallCount, 2);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("defaults to ten attempts per conversation", () => {
    assert.equal(DEFAULT_PAGE_MIN_PROMPTS, 10);
    assert.equal(DEFAULT_PAGE_MAX_PROMPTS, 10);
  });
});
