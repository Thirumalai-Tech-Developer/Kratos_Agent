import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  YuanbaoWebExecutor,
  yuanbaoSessionRotator,
} from "../../open-sse/executors/yuanbao-web.ts";
import { DEFAULT_PAGE_MIN_PROMPTS, DEFAULT_PAGE_MAX_PROMPTS } from "../../open-sse/services/webSessionRotator.ts";

describe("YuanbaoWebExecutor Antiban Page Rotation & Session Reuse", () => {
  beforeEach(() => {
    yuanbaoSessionRotator.clear();
  });

  it("reuses the same conversation page across consecutive prompts within limit", async () => {
    const executor = new YuanbaoWebExecutor();
    let conversationCreateCount = 0;
    const conversationIdsCreated: string[] = [];
    const chatUrlsCalled: string[] = [];

    const mockFetch = (async (url: string | URL | Request, _init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/user/agent/conversation/create")) {
        conversationCreateCount++;
        const newId = `conv-${conversationCreateCount}`;
        conversationIdsCreated.push(newId);
        return new Response(JSON.stringify({ id: newId }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/api/chat/")) {
        chatUrlsCalled.push(urlStr);
        return new Response('data: {"type":"text","content":"hi"}\n\ndata: {"stopReason":"stop"}\n\n', {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      const cookie = "hy_source=web; hy_user=user123; hy_token=token456";

      // Send 5 prompts with fixed limit of 5 prompts
      for (let i = 1; i <= 5; i++) {
        const res = await executor.execute({
          model: "deepseek-v3",
          body: { messages: [{ role: "user", content: `prompt ${i}` }] },
          credentials: {
            apiKey: cookie,
            providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
          },
          stream: false,
          signal: null,
        } as never);

        assert.equal(res.response.status, 200);
      }

      // Exactly 1 conversation created for the first 5 prompts
      assert.equal(conversationCreateCount, 1);
      assert.equal(conversationIdsCreated[0], "conv-1");
      // All 5 chat requests targeted conv-1
      assert.equal(chatUrlsCalled.length, 5);
      for (const calledUrl of chatUrlsCalled) {
        assert.ok(calledUrl.endsWith("/api/chat/conv-1"));
      }

      // 6th prompt should rotate to a fresh conversation page
      const res6 = await executor.execute({
        model: "deepseek-v3",
        body: { messages: [{ role: "user", content: "prompt 6" }] },
        credentials: {
          apiKey: cookie,
          providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
        },
        stream: false,
        signal: null,
      } as never);

      assert.equal(res6.response.status, 200);
      assert.equal(conversationCreateCount, 2);
      assert.equal(conversationIdsCreated[1], "conv-2");
      assert.ok(chatUrlsCalled[5].endsWith("/api/chat/conv-2"));
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("recovers from a stale reused conversation by creating a fresh one and retrying", async () => {
    const executor = new YuanbaoWebExecutor();
    let conversationCreateCount = 0;
    let chatCallCount = 0;

    const mockFetch = (async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/user/agent/conversation/create")) {
        conversationCreateCount++;
        return new Response(JSON.stringify({ id: `conv-${conversationCreateCount}` }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/api/chat/")) {
        chatCallCount++;
        // First chat call succeeds, second fails with 404 (stale), third (retry) succeeds
        if (chatCallCount === 2) {
          return new Response(JSON.stringify({ message: "conversation expired" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response('data: {"type":"text","content":"ok"}\n\ndata: {"stopReason":"stop"}\n\n', {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      const cookie = "hy_source=web; hy_user=user789; hy_token=tokenABC";

      // 1st prompt: creates conv-1
      const res1 = await executor.execute({
        model: "deepseek-v3",
        body: { messages: [{ role: "user", content: "hello" }] },
        credentials: { apiKey: cookie },
        stream: false,
        signal: null,
      } as never);
      assert.equal(res1.response.status, 200);
      assert.equal(conversationCreateCount, 1);

      // 2nd prompt: reused conv-1 returns 404, should recover with conv-2 and succeed
      const res2 = await executor.execute({
        model: "deepseek-v3",
        body: { messages: [{ role: "user", content: "hello again" }] },
        credentials: { apiKey: cookie },
        stream: false,
        signal: null,
      } as never);
      assert.equal(res2.response.status, 200);
      assert.equal(conversationCreateCount, 2);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("defaults to ten attempts per conversation", () => {
    assert.equal(DEFAULT_PAGE_MIN_PROMPTS, 10);
    assert.equal(DEFAULT_PAGE_MAX_PROMPTS, 10);
  });
});
