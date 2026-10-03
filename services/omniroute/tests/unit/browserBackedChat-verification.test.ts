import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, describe, it } from "node:test";
import { browserBackedChat } from "../../open-sse/services/browserBackedChat.ts";
import { shutdownPool } from "../../open-sse/services/browserPool.ts";

after(async () => {
  await shutdownPool("verification-test");
});

describe("browserBackedChat verification challenge", () => {
  it("returns promptly when a submitted chat is blocked by a visible challenge", async () => {
    const server = createServer((request, response) => {
      if (request.url === "/") {
        response.writeHead(200, { "Content-Type": "text/html" });
        response.end(`<!doctype html><textarea id="chat-input"></textarea>
          <button id="send">Send</button><div id="challenge" hidden>Please complete security verification</div>
          <script>document.querySelector('#send').onclick = async () => {
            await fetch('/api/v1/chats/new', { method: 'POST' });
            document.querySelector('#challenge').hidden = false;
          };</script>`);
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end("{}");
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      assert.ok(address && typeof address !== "string");
      const origin = `http://127.0.0.1:${address.port}`;
      const result = await browserBackedChat({
        poolKey: "verification-test",
        chatUrl: `${origin}/api/v2/chat/completions`,
        chatPageUrl: origin,
        chatUrlMatchDomain: "127.0.0.1",
        inputSelector: "#chat-input",
        submitButtonSelector: "#send",
        verificationChallengeText: "Please complete security verification",
        userMessage: "hi",
        reuseContext: false,
      });
      assert.equal(result.status, 403);
      assert.equal(JSON.parse(result.body.toString()).error.type, "verification_required");
      assert.ok(result.timing.captureResponseMs < 10_000);
      assert.ok(result.observedPostUrls?.includes(`${origin}/api/v1/chats/new`));
    } finally {
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve()))
      );
    }
  });
});
