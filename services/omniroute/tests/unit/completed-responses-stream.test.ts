import assert from "node:assert/strict";
import { test } from "node:test";
import { ensureResponsesSse } from "../../open-sse/transformer/completedResponsesStream.ts";

test("assembled search fallback produces a complete Responses SSE lifecycle", async () => {
  const body = { id: "resp-test", object: "response", status: "completed", usage: { total_tokens: 12 }, output: [
    { id: "search-1", type: "web_search_call", status: "completed", action: { type: "search", query: "test" } },
    { id: "msg-1", type: "message", role: "assistant", status: "completed", content: [{ type: "output_text", text: "result", annotations: [{ type: "url_citation", url: "https://example.com" }] }] },
  ] };
  const response = await ensureResponsesSse(Response.json(body));
  assert.match(response.headers.get("content-type") || "", /event-stream/);
  const events = (await response.text()).split("\n").filter((line) => line.startsWith("data: ")).map((line) => JSON.parse(line.slice(6)));
  assert.equal(events[0].type, "response.created");
  assert.equal(events.at(-1).type, "response.completed");
  assert.deepEqual(events.at(-1).response, body);
  assert.ok(events.some((event) => event.type === "response.web_search_call.completed"));
  assert.equal(events.find((event) => event.type === "response.output_text.delta").delta, "result");
  assert.deepEqual(events.map((event) => event.sequence_number), events.map((_, i) => i));
});
test("native streams and upstream failures pass through", async () => {
  for (const response of [new Response("data: x\n\n", { headers: { "content-type": "text/event-stream" } }), new Response("denied", { status: 401 })]) {
    assert.equal(await ensureResponsesSse(response), response);
  }
});
test("invalid assembled response cannot report completion", async () => {
  assert.equal((await ensureResponsesSse(Response.json({ unexpected: true }))).status, 502);
});
