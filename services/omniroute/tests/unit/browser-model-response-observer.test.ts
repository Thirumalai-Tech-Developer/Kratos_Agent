import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createContext, runInContext } from "node:vm";
import type { BrowserModel } from "../../open-sse/utils/browserModels";

const source = await readFile(
  new URL("../../scripts/ops/browserSyncExtension/modelObserver.js", import.meta.url),
  "utf8"
);
async function observe(url: string, payload: unknown) {
  const messages: Array<{ source: string; models: BrowserModel[] }> = [];
  let calls = 0;
  const response = new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
  });
  Object.defineProperty(response, "url", { value: url });
  const window = {
    fetch: async () => {
      calls++;
      return response;
    },
    postMessage: (message: (typeof messages)[number], origin: string) => {
      assert.equal(origin, "https://chat.z.ai");
      messages.push(message);
    },
  };
  runInContext(
    source,
    createContext({
      window,
      location: { origin: "https://chat.z.ai" },
      URL,
      TextDecoder,
      Uint8Array,
    })
  );
  const result = await window.fetch();
  assert.equal(result, response);
  // The passive clone is intentionally asynchronous and never delays the site's request.
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(calls, 1);
  return messages;
}
test("Normal model response emits only names, IDs, availability and capabilities", async () => {
  const messages = await observe("https://chat.z.ai/api/models", {
    data: [
      {
        id: "x-preview-l",
        name: "GLM-5.3-Flash",
        apiKey: "must-not-be-exported",
        info: { is_active: true, meta: { capabilities: { vision: true, think: true } } },
      },
      { id: "hidden", name: "Hidden Model", info: { meta: { hidden: true } } },
    ],
  });
  assert.equal(messages.length, 1);
  assert.equal(messages[0].models[0].supportsVision, true);
  assert.equal(messages[0].models[0].supportsThinking, true);
  assert.equal(messages[0].models[1].selectable, false);
  assert.equal(JSON.stringify(messages).includes("must-not-be-exported"), false);
});
test("Conversation and cross-origin responses never become model metadata", async () => {
  const payload = { data: [{ id: "fabricated", name: "Assistant suggestion" }] };
  assert.equal((await observe("https://chat.z.ai/api/chat/completions", payload)).length, 0);
  assert.equal((await observe("https://different.test/api/models", payload)).length, 0);
});
