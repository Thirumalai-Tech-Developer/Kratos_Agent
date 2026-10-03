import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  DoubaoWebExecutor,
  dolaSessionRotator,
} from "../../open-sse/executors/doubao-web.ts";
import {
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
} from "../../open-sse/services/webSessionRotator.ts";

const TEST_COOKIE = "sessionid=test_session_123; ttwid=test_ttwid; s_v_web_id=verify_fp_123";

describe("DoubaoWebExecutor Antiban Page Rotation & Session Reuse", () => {
  beforeEach(() => {
    dolaSessionRotator.clear();
  });

  it("reuses local_conversation_id and sets need_create_conversation false within limit", async () => {
    const executor = new DoubaoWebExecutor();
    const capturedPayloads: Array<{
      localConversationId: string;
      needCreateConversation: boolean;
    }> = [];

    const mockFetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const payload = JSON.parse(String(init?.body));
      capturedPayloads.push({
        localConversationId: payload.client_meta.local_conversation_id,
        needCreateConversation: payload.option.need_create_conversation,
      });
      return new Response(
        'data: {"event":"STREAM_CHUNK","data":{"content":{"content_block":[{"block_type":10000,"content":{"text_block":{"text":"hello"}}}]}}}\n\ndata: [DONE]\n\n',
        {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }
      );
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      // Send 5 prompts with fixed limit of 5
      for (let i = 1; i <= 5; i++) {
        const res = await executor.execute({
          model: "dola-speed",
          body: { messages: [{ role: "user", content: `prompt ${i}` }] },
          credentials: {
            apiKey: TEST_COOKIE,
            providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
          },
          stream: false,
          signal: null,
        } as never);

        assert.equal(res.response.status, 200);
      }

      assert.equal(capturedPayloads.length, 5);
      const firstLocalConvId = capturedPayloads[0].localConversationId;
      assert.ok(firstLocalConvId.startsWith("local_"));
      // 1st prompt: need_create_conversation should be true
      assert.equal(capturedPayloads[0].needCreateConversation, true);

      // 2nd through 5th prompt: reuse same localConversationId and need_create_conversation=false
      for (let i = 1; i < 5; i++) {
        assert.equal(capturedPayloads[i].localConversationId, firstLocalConvId);
        assert.equal(capturedPayloads[i].needCreateConversation, false);
      }

      // 6th prompt should rotate to a new conversation
      const res6 = await executor.execute({
        model: "dola-speed",
        body: { messages: [{ role: "user", content: "prompt 6" }] },
        credentials: {
          apiKey: TEST_COOKIE,
          providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
        },
        stream: false,
        signal: null,
      } as never);

      assert.equal(res6.response.status, 200);
      assert.equal(capturedPayloads.length, 6);
      assert.notEqual(capturedPayloads[5].localConversationId, firstLocalConvId);
      assert.equal(capturedPayloads[5].needCreateConversation, true);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("recovers from a stale reused conversation by resetting and retrying", async () => {
    const executor = new DoubaoWebExecutor();
    let callCount = 0;

    const mockFetch = (async () => {
      callCount++;
      // Call 1 succeeds, call 2 fails (stale), call 3 (retry) succeeds
      if (callCount === 2) {
        return new Response("conversation error", {
          status: 400,
          headers: { "Content-Type": "text/plain" },
        });
      }
      return new Response(
        'data: {"event":"STREAM_CHUNK","data":{"content":{"content_block":[{"block_type":10000,"content":{"text_block":{"text":"ok"}}}]}}}\n\ndata: [DONE]\n\n',
        {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }
      );
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      const res1 = await executor.execute({
        model: "dola-speed",
        body: { messages: [{ role: "user", content: "first" }] },
        credentials: { apiKey: TEST_COOKIE },
        stream: false,
        signal: null,
      } as never);
      assert.equal(res1.response.status, 200);

      // Reused conversation fails then retries and succeeds
      const res2 = await executor.execute({
        model: "dola-speed",
        body: { messages: [{ role: "user", content: "second" }] },
        credentials: { apiKey: TEST_COOKIE },
        stream: false,
        signal: null,
      } as never);
      assert.equal(res2.response.status, 200);
      assert.equal(callCount, 3);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("defaults to ten attempts per conversation", () => {
    assert.equal(DEFAULT_PAGE_MIN_PROMPTS, 10);
    assert.equal(DEFAULT_PAGE_MAX_PROMPTS, 10);
  });
});
