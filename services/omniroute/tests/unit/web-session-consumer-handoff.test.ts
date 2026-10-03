import { after, afterEach, beforeEach, describe, it } from "node:test";
import assert from "node:assert/strict";
import { DoubaoWebExecutor, dolaSessionRotator } from "../../open-sse/executors/doubao-web.ts";
import { CopilotWebExecutor, __resetCopilotSessionPoolForTesting } from "../../open-sse/executors/copilot-web.ts";

const originalFetch = globalThis.fetch;
const priorMessages = [
  { role: "system", content: "Original system instruction." },
  { role: "developer", content: "Original developer instruction." },
  ...Array.from({ length: 10 }, (_, index) => [
    { role: "user", content: `visible question ${index + 1}` },
    { role: "assistant", content: `visible answer ${index + 1}` },
  ]).flat(),
];
after(async () => (await import("../../src/lib/db/core.ts")).resetDbInstance());

describe("web provider rotation handoff", () => {
  beforeEach(() => {
    dolaSessionRotator.clear();
    __resetCopilotSessionPoolForTesting();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    dolaSessionRotator.clear();
    __resetCopilotSessionPoolForTesting();
  });

  it("Dola preserves instructions and current request with a summary on attempt eleven", async () => {
    const prompts: string[] = [];
    const conversations: string[] = [];
    globalThis.fetch = async (_url, init) => {
      const body = JSON.parse(String(init?.body));
      prompts.push(body.messages[0].content_block[0].content.text_block.text);
      conversations.push(body.client_meta.local_conversation_id);
      return new Response('event: STREAM_CHUNK\ndata: {"content":{"content_block":[{"content":{"text_block":{"text":"answer"}}}]}}\n\n', { headers: { "Content-Type": "text/event-stream" } });
    };
    const executor = new DoubaoWebExecutor();
    for (let turn = 1; turn <= 11; turn += 1) {
      const result = await executor.execute({
        model: "dola-speed",
        body: { messages: [...priorMessages, { role: "user", content: `Current request ${turn}.` }] },
        stream: false,
        credentials: { apiKey: "sessionid=test; ttwid=test; s_v_web_id=verify_test", providerSpecificData: { minPromptsPerPage: 999, maxPromptsPerPage: 999 } },
        signal: null,
      });
      assert.equal(result.response.status, 200);
    }
    assert.equal(new Set(conversations.slice(0, 10)).size, 1);
    assert.notEqual(conversations[10], conversations[0]);
    assert.doesNotMatch(prompts[9], /quoted reference data/);
    assert.match(prompts[10], /quoted reference data|Original system instruction|Original developer instruction/);
    assert.match(prompts[10], /visible answer 10/);
    assert.ok(prompts[10].endsWith("Current request 11."));
  });

  it("Copilot carries the compact history and developer instruction onto the new page", async () => {
    let created = 0;
    globalThis.fetch = async () => new Response(JSON.stringify({ conversationId: `page-${++created}`, remainingTurns: 100, isBlocked: false }), { headers: { "Content-Type": "application/json" } });
    const prompts: string[] = [];
    const executor = new CopilotWebExecutor();
    const methods = executor as unknown as { wsChat: (conversationId: string, prompt: string) => Promise<ReadableStream<Uint8Array>> };
    methods.wsChat = async (_conversationId, prompt) => {
      prompts.push(prompt);
      return new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n')); controller.close(); } });
    };
    for (let turn = 1; turn <= 11; turn += 1) {
      const result = await executor.execute({
        model: "copilot",
        body: { messages: [...priorMessages, { role: "user", content: `Current request ${turn}.` }] },
        stream: false,
        credentials: { apiKey: "test-token", providerSpecificData: { minPromptsPerPage: 999, maxPromptsPerPage: 999 } },
        signal: undefined,
      });
      assert.equal(result.response.status, 200);
    }
    assert.equal(created, 2);
    assert.doesNotMatch(prompts[9], /quoted reference data/);
    assert.match(prompts[10], /quoted reference data/);
    assert.match(prompts[10], /Original system instruction/);
    assert.match(prompts[10], /Original developer instruction/);
    assert.ok(prompts[10].endsWith("Current request 11."));
  });
});
