import { after, afterEach, beforeEach, describe, it } from "node:test";
import assert from "node:assert/strict";
import { DoubaoWebExecutor, dolaSessionRotator } from "../../open-sse/executors/doubao-web.ts";

const COOKIE = "sessionid=test-dola; ttwid=test-ttwid; s_v_web_id=verify_test";
const originalFetch = globalThis.fetch;
const encoder = new TextEncoder();

after(async () => (await import("../../src/lib/db/core.ts")).resetDbInstance());

function frame(event: string, data: unknown, terminated = true): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}${terminated ? "\n\n" : ""}`;
}

function textFrame(text: string, terminated = true): string {
  return frame(
    "STREAM_CHUNK",
    { content: { content_block: [{ content: { text_block: { text } } }] } },
    terminated
  );
}

function sse(body: BodyInit | null): Response {
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

function execute(stream = true, signal: AbortSignal | null = null) {
  return new DoubaoWebExecutor().execute({
    model: "dola-speed",
    body: { messages: [{ role: "user", content: "hello" }] },
    credentials: {
      apiKey: COOKIE,
      providerSpecificData: { minPromptsPerPage: 7, maxPromptsPerPage: 7 },
    },
    stream,
    signal,
  });
}

function dataFrames(raw: string): Array<Record<string, unknown>> {
  return raw
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:") && !line.includes("[DONE]"))
    .map((line) => JSON.parse(line.slice(5)) as Record<string, unknown>);
}

describe("Dola streaming recovery", { timeout: 10_000 }, () => {
  beforeEach(() => dolaSessionRotator.clear());
  afterEach(() => {
    globalThis.fetch = originalFetch;
    dolaSessionRotator.clear();
  });

  it("preserves rate limits without rotating or retrying the conversation", async () => {
    let calls = 0;
    globalThis.fetch = async () => {
      calls += 1;
      if (calls === 1) return sse(textFrame("answer"));
      return new Response("Too many requests", { status: 429, headers: { "Retry-After": "120" } });
    };
    await execute(false);
    const result = await execute(false);
    assert.equal(calls, 2);
    assert.equal(result.response.status, 429);
    assert.equal(result.response.headers.get("Retry-After"), "120");
  });

  it("preserves a final SSE text frame without a blank-line terminator", async () => {
    globalThis.fetch = async () => sse(textFrame("Final answer 😀", false));
    const result = await execute();
    const raw = await result.response.text();
    assert.match(raw, /Final answer 😀/);
    assert.doesNotMatch(raw, /empty response/);
    assert.equal((raw.match(/data: \[DONE\]/g) || []).length, 1);
  });

  for (const body of [null, frame("SSE_REPLY_END", {})]) {
    it(`emits a typed error for ${body === null ? "a missing body" : "an empty reply"}`, async () => {
      globalThis.fetch = async () => sse(body);
      const result = await execute();
      const raw = await result.response.text();
      const frames = dataFrames(raw);
      assert.ok(
        frames.some((item) => item.error),
        "empty output must be an error frame"
      );
      assert.ok(
        frames.every((item) => !item.choices),
        "must not invent assistant text"
      );
      assert.match(raw, /empty response/i);
    });
  }

  it("preserves an upstream STREAM_ERROR as a sanitized error, not assistant text", async () => {
    globalThis.fetch = async () =>
      sse(frame("STREAM_ERROR", { message: "Rate limited\nat C:/private/secret.ts:10:1" }));
    const result = await execute();
    const raw = await result.response.text();
    const frames = dataFrames(raw);
    assert.ok(frames.some((item) => item.error));
    assert.ok(frames.every((item) => !item.choices));
    assert.match(raw, /Rate limited/);
    assert.doesNotMatch(raw, /secret\.ts|C:\/private/);
  });

  it("recognizes data-only event envelopes so non-stream errors cannot look successful", async () => {
    globalThis.fetch = async () =>
      sse(
        `data: ${JSON.stringify({ event: "STREAM_ERROR", data: { message: "Rate limited" } })}\n\n` +
          textFrame("partial")
      );
    const result = await execute(false);
    assert.equal(result.response.status, 429);
    assert.match(await result.response.text(), /Rate limited/);
  });

  it("cancels and releases the upstream reader when the downstream cancels", async () => {
    let cancelled = false;
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(textFrame("first")));
      },
      cancel() {
        cancelled = true;
      },
    });
    globalThis.fetch = async () => sse(upstreamBody);
    const result = await execute();
    const reader = result.response.body!.getReader();
    await reader.read();
    await reader.cancel();
    await new Promise<void>((resolve) => setImmediate(resolve));
    assert.equal(cancelled, true);
    assert.equal(upstreamBody.locked, false);
  });

  it("stops and releases the upstream reader after the provider terminal event", async () => {
    let cancelled = false;
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(textFrame("answer") + frame("SSE_REPLY_END", {})));
      },
      cancel() {
        cancelled = true;
      },
    });
    globalThis.fetch = async () => sse(upstreamBody);
    const result = await execute();
    const raw = await result.response.text();
    assert.match(raw, /answer/);
    assert.equal(cancelled, true);
    assert.equal(upstreamBody.locked, false);
  });

  it("returns a non-streaming answer at the terminal event without waiting for connection close", async () => {
    let cancelled = false;
    globalThis.fetch = async () =>
      sse(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode(textFrame("answer") + frame("SSE_REPLY_END", {})));
          },
          cancel() {
            cancelled = true;
          },
        })
      );
    const result = await Promise.race([
      execute(false),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 200)),
    ]);
    assert.ok(result, "terminal SSE event must finish the non-streaming response");
    assert.equal((await result.response.json()).choices[0].message.content, "answer");
    assert.equal(cancelled, true);
  });

  it("binds retry acknowledgements to the fresh conversation used by the next request", async () => {
    const payloads: Array<Record<string, unknown>> = [];
    let count = 0;
    globalThis.fetch = async (_url, init) => {
      const payload = JSON.parse(String(init?.body)) as Record<string, unknown>;
      payloads.push(payload);
      count += 1;
      if (count === 2) return new Response("stale conversation", { status: 400 });
      const conversation = count === 1 ? "conversation-original" : "conversation-fresh";
      return sse(
        frame("SSE_ACK", {
          ack_client_meta: { conversation_id: conversation, section_id: `section-${conversation}` },
        }) + textFrame("answer")
      );
    };
    await execute(false);
    const retried = await execute(false);
    await execute(false);
    assert.equal(count, 4);
    const retryMeta = payloads[2].client_meta as Record<string, unknown>;
    const nextMeta = payloads[3].client_meta as Record<string, unknown>;
    assert.equal(nextMeta.conversation_id, "conversation-fresh");
    assert.equal(nextMeta.last_section_id, "section-conversation-fresh");
    assert.equal(nextMeta.local_conversation_id, retryMeta.local_conversation_id);
    assert.equal(
      (retried.transformedBody.client_meta as Record<string, unknown>).local_conversation_id,
      retryMeta.local_conversation_id
    );
  });
});
