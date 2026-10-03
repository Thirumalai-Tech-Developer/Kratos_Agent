import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  CopilotWebExecutor,
  __resetCopilotSessionPoolForTesting,
  sessionPool,
} from "../../open-sse/executors/copilot-web.ts";
import {
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
} from "../../open-sse/services/webSessionRotator.ts";

describe("CopilotWebExecutor Antiban Page Rotation & Session Reuse", () => {
  beforeEach(() => {
    __resetCopilotSessionPoolForTesting();
  });

  it("rotates session after reaching prompt limit (5..7 prompts)", async () => {
    const executor = new CopilotWebExecutor();
    let startCallCount = 0;
    const createdConvIds: string[] = [];

    const mockFetch = (async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes("/c/api/start")) {
        startCallCount++;
        const id = `copilot-conv-${startCallCount}`;
        createdConvIds.push(id);
        return new Response(
          JSON.stringify({
            conversationId: id,
            remainingTurns: 30,
            isBlocked: false,
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Set-Cookie": "MUID=123; path=/",
            },
          }
        );
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = mockFetch;

    try {
      // Mock wsChat to return a dummy stream without opening real WebSocket
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (executor as any).wsChat = async (_convId: string) => {
        return new ReadableStream({
          start(controller) {
            const encoder = new TextEncoder();
            const chunk = {
              id: "test",
              object: "chat.completion.chunk",
              created: 12345,
              model: "copilot",
              choices: [{ index: 0, delta: { content: "hi" }, finish_reason: null }],
            };
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
            controller.enqueue(encoder.encode("data: [DONE]\n\n"));
            controller.close();
          },
        });
      };

      const token = "mock-bearer-token-copilot";

      // Execute 5 prompts with fixed limit of 5
      for (let i = 1; i <= 5; i++) {
        const res = await executor.execute({
          model: "copilot",
          body: { messages: [{ role: "user", content: `prompt ${i}` }] },
          credentials: {
            apiKey: token,
            providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
          },
          stream: true,
          signal: null,
        } as never);

        assert.equal(res.response.status, 200);
      }

      // First 5 prompts used exactly 1 start session call
      assert.equal(startCallCount, 1);
      assert.equal(createdConvIds[0], "copilot-conv-1");

      const currentSession = sessionPool.get(token);
      assert.ok(currentSession);
      assert.equal(currentSession?.conversationId, "copilot-conv-1");
      assert.equal(currentSession?.promptCount, 5);

      // 6th prompt should rotate to a new session
      const res6 = await executor.execute({
        model: "copilot",
        body: { messages: [{ role: "user", content: "prompt 6" }] },
        credentials: {
          apiKey: token,
          providerSpecificData: { minPromptsPerPage: 5, maxPromptsPerPage: 5 },
        },
        stream: true,
        signal: null,
      } as never);

      assert.equal(res6.response.status, 200);
      assert.equal(startCallCount, 2);
      assert.equal(createdConvIds[1], "copilot-conv-2");
      assert.equal(sessionPool.get(token)?.conversationId, "copilot-conv-2");
      assert.equal(sessionPool.get(token)?.promptCount, 1);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("defaults to ten attempts per conversation", () => {
    assert.equal(DEFAULT_PAGE_MIN_PROMPTS, 10);
    assert.equal(DEFAULT_PAGE_MAX_PROMPTS, 10);
  });
});
