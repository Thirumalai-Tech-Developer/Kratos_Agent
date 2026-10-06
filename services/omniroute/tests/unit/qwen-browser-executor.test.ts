import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Buffer } from "node:buffer";

import {
  QwenBrowserExecutor,
  parseQwenBrowserResponse,
  selectQwenModel,
} from "../../open-sse/executors/qwen-browser.ts";
import type { Page } from "playwright";
import {
  __setBrowserBackedChatOverrideForTesting,
  __resetBrowserBackedChatOverrideForTesting,
  type BrowserBackedChatRequest,
} from "../../open-sse/services/browserBackedChat.ts";
import { resetDbInstance } from "../../src/lib/db/core.ts";
import { getRegistryEntry } from "../../open-sse/config/providerRegistry.ts";
import { AI_PROVIDERS } from "../../src/shared/constants/providers.ts";
import { getExecutor } from "../../open-sse/executors/index.ts";

const CHAT_ID = "babff3bc-84c9-4fc1-a7b6-fb823ea7064e";
function response(answer = "Hello", complete = true): string {
  const frames = [
    { "response.created": { chat_id: CHAT_ID, response_id: "response-1" } },
    { choices: [{ delta: { phase: "thinking_summary", content: "Thought", status: "typing" } }] },
    { choices: [{ delta: { phase: "thinking_summary", content: "", status: "finished" } }] },
    {
      choices: [
        { delta: { role: "assistant", phase: "answer", content: answer, status: "typing" } },
      ],
    },
    ...(complete
      ? [{ choices: [{ delta: { phase: "answer", content: "", status: "finished" } }] }]
      : []),
  ];
  return frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("");
}
function capture(body = response(), status = 200, contentType = "text/event-stream") {
  return {
    status,
    contentType,
    body: Buffer.from(body),
    isStealth: false,
    timing: { acquireContextMs: 0, navigateMs: 0, submitMs: 0, captureResponseMs: 0, totalMs: 0 },
  };
}
function input(
  messages: Array<{ role: string; content: string }> = [{ role: "user", content: "Hi" }]
) {
  return {
    model: "qwen3.7-plus",
    body: { messages },
    stream: false,
    credentials: {
      connectionId: "test-connection",
      apiKey: JSON.stringify({
        token: "test-token",
        cookie: "token=test-token; refresh_token=test-refresh",
        userAgent: "Test Browser",
      }),
    },
  };
}
afterEach(() => __resetBrowserBackedChatOverrideForTesting());
after(() => resetDbInstance());

test("cancelled browser body reads release the Qwen conversation lock promptly", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => new Promise(() => {}));
  const controller = new AbortController();
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  const pending = executor.execute({ ...input(), signal: controller.signal });
  setImmediate(() => controller.abort());
  const result = await Promise.race([
    pending,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 200)),
  ]);
  assert.ok(result, "abort must settle even when the browser body never finishes");
  assert.equal(result.status, 499);
  __setBrowserBackedChatOverrideForTesting(async () => capture());
  assert.equal((await executor.execute(input())).status, 200);
});

test("new provider resolves its own catalog and aliases without reviving retired ids", async () => {
  assert.equal(getRegistryEntry("qwb")?.id, "qwen-browser");
  assert.equal(getRegistryEntry("qwen-browser")?.models[0].toolCalling, false);
  assert.equal(AI_PROVIDERS["qwen-browser"].toolCalling, "none");
  assert.ok((await getExecutor("qwb")) instanceof QwenBrowserExecutor);
  for (const id of ["qwen-web", "qw"]) {
    assert.equal(getRegistryEntry(id), null);
    await assert.rejects(
      () => getExecutor(id),
      (error: Error & { status?: number }) => error.status === 410
    );
  }
});

test("observed phase deltas return answer separately from thinking and recognize finished", () => {
  const parsed = parseQwenBrowserResponse(response("OMNIROUTE_OK"));
  assert.equal(parsed.content, "OMNIROUTE_OK");
  assert.equal(parsed.reasoning, "Thought");
  assert.equal(parsed.finished, true);
  assert.equal(parsed.chatId, CHAT_ID);
});

test("Qwen Browser restores private auth and returns nonempty JSON", async () => {
  let request: BrowserBackedChatRequest | undefined;
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    request = req;
    return capture();
  });
  const result = await new QwenBrowserExecutor({ transport: "ui" }).execute(input());
  assert.equal(result.status, 200);
  assert.equal(request?.submitButtonSelector, 'button[aria-label="Send"]:not([disabled])');
  assert.equal((await result.json()).choices[0].message.content, "Hello");
  assert.equal(request?.chatPageUrl, "https://chat.qwen.ai");
  assert.equal(request?.localStorage?.token, "test-token");
  assert.equal(request?.cookieString, "token=test-token; refresh_token=test-refresh");
  assert.equal(request?.userAgent, "Test Browser");
  assert.equal(request?.inputSelector, "textarea");
});

test("a captured Qwen picker model is routed without replacing it with the default", async () => {
  let request: BrowserBackedChatRequest | undefined;
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    request = req;
    return capture();
  });
  const candidate = {
    ...input(),
    model: "qwen-ui-qwen3.8-max",
    credentials: {
      ...input().credentials,
      providerSpecificData: {
        browserModels: [
          { id: "qwen-ui-qwen3.8-max", name: "Qwen3.8-Max", selectable: true, free: true },
        ],
      },
    },
  };
  const result = await new QwenBrowserExecutor({
    fetch: async () => assert.fail("UI-only model ids must not become guessed API ids"),
  }).execute(candidate);
  assert.equal(result.status, 200);
  assert.equal((await result.json()).model, candidate.model);
  assert.ok(request?.beforeSubmit);
});

test("Qwen UI selection clicks the requested exact label and confirms that selection", async () => {
  let selected = "Qwen Fixture";
  let clicked = "";
  const selector = {
    first() {
      return this;
    },
    async waitFor() {},
    async innerText() {
      return selected;
    },
    async click() {},
  };
  const page = {
    locator() {
      return selector;
    },
    getByText(label: string, options: { exact: boolean }) {
      assert.equal(options.exact, true);
      return {
        first() {
          return this;
        },
        last() {
          return this;
        },
        async isVisible() {
          return false;
        },
        async click() {
          clicked = label;
          selected = label;
        },
      };
    },
  } as unknown as Page;
  await selectQwenModel(page, "Qwen Fixture Max");
  assert.equal(clicked, "Qwen Fixture Max");
  assert.equal(selected, "Qwen Fixture Max");
});

test("captured locked or paid Qwen entries fail before browser submission", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("must not submit"));
  for (const model of [
    { id: "qwen-ui-locked", name: "Locked model", selectable: false, free: true },
    { id: "qwen-ui-paid", name: "Paid model", selectable: true, free: false },
  ]) {
    const result = await new QwenBrowserExecutor({ transport: "ui" }).execute({
      ...input(),
      model: model.id,
      credentials: { ...input().credentials, providerSpecificData: { browserModels: [model] } },
    });
    assert.equal(result.status, 400);
  }
});

test("an observed empty Qwen picker does not resurrect its historical default", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("must not submit"));
  for (const browserModels of [[], [{ malformed: true }]]) {
    const result = await new QwenBrowserExecutor({ transport: "ui" }).execute({
      ...input(),
      credentials: { ...input().credentials, providerSpecificData: { browserModels } },
    });
    assert.equal(result.status, 400);
  }
});

test("raw bearer token plus separate session metadata is supported", async () => {
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    assert.equal(req.localStorage?.token, "test-token");
    assert.equal(req.cookieString, "token=test-token");
    return capture();
  });
  const request = input();
  request.credentials = {
    connectionId: "test-connection",
    apiKey: "Bearer test-token",
    providerSpecificData: { cookie: "token=test-token", userAgent: "Test Browser" },
  } as typeof request.credentials;
  assert.equal((await new QwenBrowserExecutor({ transport: "ui" }).execute(request)).status, 200);
});

test("Qwen age verification is an actionable error instead of empty output", async () => {
  __setBrowserBackedChatOverrideForTesting(async () =>
    capture(
      JSON.stringify({
        error: { message: "Qwen requires age verification before it will send the chat request." },
      }),
      403,
      "application/json"
    )
  );
  const result = await new QwenBrowserExecutor({ transport: "ui" }).execute(input());
  assert.equal(result.status, 403);
  assert.equal((await result.json()).error.code, "qwen_browser_age_verification_required");
});

test("named token cookie can restore bearer state", async () => {
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    assert.equal(req.localStorage?.token, "cookie-token");
    return capture();
  });
  const request = input();
  request.credentials.apiKey = "token=cookie-token; refresh_token=test-refresh";
  assert.equal((await new QwenBrowserExecutor({ transport: "ui" }).execute(request)).status, 200);
});

test("streamed response has answer deltas, stop and DONE without thinking-as-text", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => capture());
  const result = await new QwenBrowserExecutor({ transport: "ui" }).execute({
    ...input(),
    stream: true,
  });
  assert.equal(result.headers.get("content-type"), "text/event-stream");
  const text = await result.text();
  assert.match(text, /"content":"Hello"/);
  assert.match(text, /"reasoning_content":"Thought"/);
  assert.match(text, /"finish_reason":"stop"/);
  assert.match(text, /data: \[DONE\]/);
});

for (const [name, body] of [
  ["empty", ""],
  ["thinking only", response("")],
  ["unfinished", response("Partial", false)],
  ["malformed", "data: {broken}\n\n"],
]) {
  test(`${name} response is an error, never empty success`, async () => {
    __setBrowserBackedChatOverrideForTesting(async () => capture(body));
    const result = await new QwenBrowserExecutor({ transport: "ui" }).execute(input());
    assert.equal(result.status, 502);
    assert.ok((await result.json()).error.message);
  });
}

test("login and challenge errors are explicit and never leak upstream secrets", async () => {
  for (const [status, body] of [
    [401, '{"error":"expired token=private"}'],
    [403, "<html>Captcha Cookie: private at C:/private/file.ts:7</html>"],
  ]) {
    __setBrowserBackedChatOverrideForTesting(async () =>
      capture(String(body), Number(status), "text/html")
    );
    const result = await new QwenBrowserExecutor({ transport: "ui" }).execute(input());
    assert.equal(result.status, status);
    const text = await result.text();
    assert.match(text, Number(status) === 401 ? /sign in|expired/i : /challenge|captcha/i);
    assert.equal(text.includes("private"), false);
  }
});

test("unsupported model, vision, tools and missing auth fail before browser submission", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => {
    assert.fail("must not submit");
  });
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  assert.equal((await executor.execute({ ...input(), model: "invented-model" })).status, 400);
  assert.equal((await executor.execute({ ...input(), credentials: {} })).status, 401);
  assert.equal(
    (
      await executor.execute({
        ...input(),
        body: { ...input().body, tools: [{ type: "function" }] },
      })
    ).status,
    400
  );
  assert.equal(
    (
      await executor.execute({
        ...input(),
        body: {
          messages: [
            {
              role: "user",
              content: [{ type: "image_url", image_url: { url: "https://example.test/x" } }],
            },
          ],
        },
      })
    ).status,
    400
  );
});

test("reuse conversation through ten completed answers then handoff summary to fresh conversation", async () => {
  const requests: BrowserBackedChatRequest[] = [];
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    requests.push(req);
    return capture(response(`answer ${requests.length}`));
  });
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  const messages = [{ role: "user", content: "Remember my project Alpha" }];
  for (let turn = 0; turn < 11; turn++) {
    assert.equal((await executor.execute(input(messages))).status, 200);
    messages.push(
      { role: "assistant", content: `answer ${turn + 1}` },
      { role: "user", content: `Next ${turn + 1}` }
    );
  }
  assert.equal(requests[0].chatPageUrl, "https://chat.qwen.ai");
  for (const request of requests.slice(1, 10))
    assert.equal(request.chatPageUrl, `https://chat.qwen.ai/c/${CHAT_ID}`);
  assert.equal(requests[10].chatPageUrl, "https://chat.qwen.ai");
  assert.match(requests[10].userMessage, /summary|handoff/i);
  assert.match(requests[10].userMessage, /Alpha/);
  assert.match(requests[10].userMessage, /Next 10/);
  assert.ok(requests[10].userMessage.length < 6000);
});

test("failed responses do not count toward ten completed answers", async () => {
  const requests: BrowserBackedChatRequest[] = [];
  let failures = true;
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    requests.push(req);
    return failures ? capture("", 429) : capture();
  });
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  for (let i = 0; i < 12; i++) assert.equal((await executor.execute(input())).status, 429);
  failures = false;
  assert.equal((await executor.execute(input())).status, 200);
  assert.equal(requests[12].chatPageUrl, "https://chat.qwen.ai");
});

test("different client conversation prefixes do not share provider chat", async () => {
  const requests: BrowserBackedChatRequest[] = [];
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    requests.push(req);
    return capture();
  });
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  await executor.execute(input([{ role: "user", content: "Project A" }]));
  await executor.execute(input([{ role: "user", content: "Project B" }]));
  assert.equal(requests[1].chatPageUrl, "https://chat.qwen.ai");
  assert.notEqual(requests[0].poolKey, requests[1].poolKey);
});

test("identical stateless opening prompts do not join an unrelated prior chat", async () => {
  const requests: BrowserBackedChatRequest[] = [];
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    requests.push(req);
    return capture();
  });
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  await executor.execute(input());
  await executor.execute(input());
  assert.equal(requests[1].chatPageUrl, "https://chat.qwen.ai");
});

test("explicit client session serializes overlapping calls to one conversation", async () => {
  const requests: BrowserBackedChatRequest[] = [];
  let firstFinished = false;
  __setBrowserBackedChatOverrideForTesting(async (req) => {
    if (requests.length) assert.equal(firstFinished, true);
    requests.push(req);
    if (requests.length === 1) await new Promise<void>((resolve) => setTimeout(resolve, 10));
    firstFinished = true;
    return capture();
  });
  const executor = new QwenBrowserExecutor({ transport: "ui" });
  const request = { ...input(), body: { ...input().body, metadata: { session_id: "client-A" } } };
  const results = await Promise.all([executor.execute(request), executor.execute(request)]);
  assert.deepEqual(
    results.map((result) => result.status),
    [200, 200]
  );
  assert.equal(requests[1].chatPageUrl, `https://chat.qwen.ai/c/${CHAT_ID}`);
});
