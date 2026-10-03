import { describe, it } from "node:test";
import assert from "node:assert/strict";
import * as rotation from "../../open-sse/services/webSessionRotator.ts";

const prepare = (
  rotation as unknown as {
    prepareWebSessionMessages: (messages: unknown, rotated: boolean) => unknown[];
  }
).prepareWebSessionMessages;

describe("bounded web conversation rotation", () => {
  it("applies the same cap and creation serialization to DeepSeek's separate manager", async () => {
    const manager = await import("../../open-sse/executors/deepseek-web/session-manager.ts");
    manager.sessionCache.clear();
    let created = 0;
    const results = await Promise.all(Array.from({ length: 11 }, () => manager.acquireSessionPage({
      userToken: "test-account",
      accessToken: "test-access",
      minPrompts: Infinity,
      maxPrompts: 999,
      createSessionFn: async () => `page-${++created}`,
    })));
    assert.equal(created, 2);
    assert.deepEqual(results.map((item) => item.sessionId), [...Array(10).fill("page-1"), "page-2"]);
    assert.equal(results[10].rotated, true);
    manager.sessionCache.clear();
  });
  it("defaults to ten attempts and rotates before attempt eleven", async () => {
    const store = new rotation.WebSessionRotator<string>();
    let created = 0;
    for (let turn = 1; turn <= 11; turn += 1) {
      const result = await store.acquire({ scopeKey: "account:model", createFn: async () => `page-${++created}` });
      assert.equal(result.maxPrompts, 10);
      assert.equal(result.data, turn <= 10 ? "page-1" : "page-2");
      assert.equal(result.promptCount, turn <= 10 ? turn : 1);
      assert.equal((result as unknown as { rotated: boolean }).rotated, turn === 11);
    }
    assert.equal(created, 2);
  });

  it("caps overrides at ten and normalizes malformed ranges to finite integers", () => {
    for (const [min, max] of [[100, 100], [Infinity, Infinity], [NaN, NaN], [10.9, 20.9]]) {
      assert.equal(rotation.getRandomPromptLimit(min, max), 10);
    }
    assert.equal(rotation.getRandomPromptLimit(10, 3), 3);
    assert.equal(rotation.getRandomPromptLimit(-4, 0), 1);
    assert.equal(rotation.getRandomPromptLimit(2.9, 2.9), 2);
  });

  it("serializes concurrent creation and reserves each attempt once", async () => {
    const store = new rotation.WebSessionRotator<string>();
    let created = 0;
    const options = { scopeKey: "account:model", createFn: async () => { created += 1; await Promise.resolve(); return `page-${created}`; } };
    const results = await Promise.all(Array.from({ length: 21 }, () => store.acquire(options)));
    assert.equal(created, 3);
    assert.deepEqual(results.map((item) => item.data), [...Array(10).fill("page-1"), ...Array(10).fill("page-2"), "page-3"]);
    assert.deepEqual(results.map((item) => item.promptCount), [...Array.from({ length: 10 }, (_, i) => i + 1), ...Array.from({ length: 10 }, (_, i) => i + 1), 1]);
  });

  it("keeps accounts independent and retries a failed creation without a stuck queue", async () => {
    const store = new rotation.WebSessionRotator<string>();
    const fail = store.acquire({ scopeKey: "a", createFn: async () => { throw new Error("creation failed"); } });
    const succeed = store.acquire({ scopeKey: "a", createFn: async () => "a-page" });
    const other = store.acquire({ scopeKey: "b", createFn: async () => "b-page" });
    await assert.rejects(fail, /creation failed/);
    assert.equal((await succeed).promptCount, 1);
    assert.equal((await other).data, "b-page");
  });
});

describe("bounded rotation handoff", () => {
  const history = [
    { role: "system", content: "Keep required system instructions." },
    { role: "developer", content: "Keep required developer instructions." },
    ...Array.from({ length: 12 }, (_, i) => [
      { role: "user", content: `question-${i + 1}` },
      { role: "assistant", content: `answer-${i + 1}` },
    ]).flat(),
    { role: "user", content: "Current request exactly." },
    { role: "assistant", tool_calls: [{ id: "current-tool" }], content: null },
    { role: "tool", tool_call_id: "current-tool", content: "Current tool evidence exactly." },
  ];

  it("leaves messages intact until a real rotation occurs", () => {
    assert.equal(prepare(history, false), history);
  });

  it("summarizes ten visible completed pairs and preserves instructions/current turn", () => {
    const result = prepare(history, true) as Array<Record<string, unknown>>;
    assert.deepEqual(result.slice(0, 2), history.slice(0, 2));
    assert.deepEqual(result.slice(-3), history.slice(-3));
    const summary = String(result[2].content);
    assert.match(summary, /reference data/);
    assert.match(summary, /question-3|answer-12/);
    assert.doesNotMatch(summary, /question-1"|question-2"|required system|Current tool/);
  });

  it("excludes old tools and unfinished tool-call answers from the summary", () => {
    const messages = [
      { role: "user", content: "visible question" },
      { role: "assistant", content: "visible answer" },
      { role: "user", content: "old tool request" },
      { role: "assistant", content: "old tool call", tool_calls: [{ id: "old" }] },
      { role: "tool", content: "private raw tool output" },
      { role: "user", content: "current" },
    ];
    const result = prepare(messages, true) as Array<Record<string, unknown>>;
    assert.match(String(result[0].content), /visible answer/);
    assert.doesNotMatch(String(result[0].content), /old tool|private raw/);
    assert.deepEqual(result.at(-1), messages.at(-1));
  });

  it("bounds excerpts and total summary size", () => {
    const messages = [...Array.from({ length: 20 }, () => [
      { role: "user", content: "q".repeat(10_000) },
      { role: "assistant", content: "a".repeat(10_000) },
    ]).flat(), { role: "user", content: "current" }];
    const result = prepare(messages, true) as Array<Record<string, unknown>>;
    assert.ok(String(result[0].content).length <= 6500);
    assert.deepEqual(result.at(-1), messages.at(-1));
    const escaped = messages.map((message) => ({ ...message, content: "\u0001".repeat(10_000) }));
    assert.ok(String((prepare(escaped, true)[0] as Record<string, unknown>).content).length <= 6500);
  });
});
