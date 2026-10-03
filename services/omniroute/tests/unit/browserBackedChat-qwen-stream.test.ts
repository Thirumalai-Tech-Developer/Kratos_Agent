import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, test } from "node:test";
import { browserBackedChat } from "../../open-sse/services/browserBackedChat.ts";
import { shutdownPool } from "../../open-sse/services/browserPool.ts";

after(async () => {
  await shutdownPool("qwen-stream-test");
  (await import("../../src/lib/db/core.ts")).resetDbInstance();
});

test("captures a completed Qwen answer while the upstream SSE connection stays open", async () => {
  const server = createServer((request, response) => {
    if (request.url === "/") {
      response.writeHead(200, { "Content-Type": "text/html" });
      response.end(`<!doctype html><textarea></textarea><button>Send</button>
        <script>document.querySelector('button').onclick = () => fetch('/completion', {method:'POST'});</script>`);
      return;
    }
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.write(
      'data: {"choices":[{"delta":{"phase":"thinking_summary","status":"finished"}}]}\n\n'
    );
    response.write('data: {"choices":[{"delta":{"phase":"answer","content":"Hello"}}]}\n\n');
    // Split the terminal event across chunks, then leave the connection open.
    response.write('data: {"choices":[{"delta":{"phase":"answer","status":');
    setTimeout(() => response.write('"finished"}}]}\n\n'), 20);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const origin = `http://127.0.0.1:${address.port}`;
    const result = await browserBackedChat({
      poolKey: "qwen-stream-test",
      chatUrl: `${origin}/completion`,
      chatPageUrl: origin,
      chatUrlMatchDomain: "127.0.0.1",
      inputSelector: "textarea",
      submitButtonSelector: "button",
      userMessage: "hi",
      streamCompletion: { phase: "answer", status: "finished" },
      signal: AbortSignal.timeout(15_000),
      reuseContext: false,
    });
    assert.equal(result.status, 200, result.body.toString());
    assert.match(result.body.toString(), /Hello/);
    assert.match(result.body.toString(), /"status":"finished"/);
    assert.ok(result.timing.captureResponseMs < 5000);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
