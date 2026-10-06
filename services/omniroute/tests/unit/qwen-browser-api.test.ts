import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { randomUUID } from "node:crypto";
import {
  QwenBrowserExecutor,
  parseQwenBrowserResponse,
} from "../../open-sse/executors/qwen-browser.ts";
import type { ExecuteInput } from "../../open-sse/executors/base.ts";
import {
  __setBrowserBackedChatOverrideForTesting,
  __resetBrowserBackedChatOverrideForTesting,
} from "../../open-sse/services/browserBackedChat.ts";
import { resetDbInstance } from "../../src/lib/db/core.ts";

// Anonymized protocol from the Oct 6 manual Qwen recording. No credentials or user history.
const CHAT_ID = "11111111-1111-4111-8111-111111111111";
const RESPONSE_ID = "22222222-2222-4222-8222-222222222222";
function frames(answer = "Hello! How can I help you today?", responseId = RESPONSE_ID) {
  const summary = {
    choices: [
      {
        delta: {
          role: "assistant",
          content: "",
          phase: "thinking_summary",
          status: "typing",
          extra: { summary_thought: { content: ["Considering a greeting."] } },
        },
      },
    ],
  };
  return [
    {
      "response.created": {
        chat_id: CHAT_ID,
        parent_id: randomUUID(),
        response_id: responseId,
        response_index: "0",
      },
    },
    summary,
    summary,
    { choices: [{ delta: { phase: "thinking_summary", content: "", status: "finished" } }] },
    {
      choices: [
        { delta: { role: "assistant", content: answer, phase: "answer", status: "typing" } },
      ],
      usage: {
        input_tokens: 1200,
        output_tokens: 108,
        total_tokens: 1308,
        output_tokens_details: { reasoning_tokens: 94 },
      },
    },
    {
      choices: [{ delta: { role: "assistant", content: "", phase: "answer", status: "finished" } }],
      response_id: responseId,
    },
  ]
    .map((frame) => `data: ${JSON.stringify(frame)}\n\n`)
    .join("");
}
function input(): ExecuteInput {
  return {
    model: "qwen3.7-plus",
    stream: false,
    body: {
      messages: [{ role: "user", content: "Hi" }],
      metadata: { session_id: "fixture-session" },
    },
    credentials: {
      connectionId: "fixture",
      apiKey: JSON.stringify({
        token: "fixture-token",
        cookie: "token=fixture-token",
        userAgent: "Fixture Browser",
      }),
    },
  };
}
type Call = { url: string; body: Record<string, unknown>; headers: Headers };
function api(
  completion: () => Response = () =>
    new Response(frames(), { headers: { "content-type": "text/event-stream" } })
) {
  const calls: Call[] = [];
  const fetcher: typeof fetch = async (url, init) => {
    const path = String(url);
    calls.push({
      url: path,
      body: JSON.parse(String(init?.body)),
      headers: new Headers(init?.headers),
    });
    return path.endsWith("/chats/new")
      ? Response.json({ success: true, data: { id: CHAT_ID } })
      : completion();
  };
  return { calls, executor: new QwenBrowserExecutor({ fetch: fetcher }) };
}
afterEach(() => __resetBrowserBackedChatOverrideForTesting());
after(() => resetDbInstance());

test("captured summary snapshots deduplicate; answer finish and server response id are decoded", () => {
  const parsed = parseQwenBrowserResponse(frames());
  assert.equal(parsed.reasoning, "Considering a greeting.");
  assert.equal(parsed.content, "Hello! How can I help you today?");
  assert.equal(parsed.finished, true);
  assert.equal(parsed.responseId, RESPONSE_ID);
  assert.equal(parsed.usage?.prompt_tokens, 1200);
  assert.equal(parsed.usage?.completion_tokens, 108);
  assert.equal(parsed.usage?.total_tokens, 1308);
});

test("known Qwen model uses captured API protocol and imported auth without a second browser", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("API must not open a browser"));
  const { executor, calls } = api();
  const result = await executor.execute(input());
  assert.equal(result.status, 200);
  assert.equal(
    (await result.json()).choices[0].message.content,
    "Hello! How can I help you today?"
  );
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, "https://chat.qwen.ai/api/v2/chats/new");
  assert.deepEqual(calls[0].body.models, ["qwen3.7-plus"]);
  assert.equal(calls[1].url, `https://chat.qwen.ai/api/v2/chat/completions?chat_id=${CHAT_ID}`);
  assert.equal(calls[1].headers.get("authorization"), "Bearer fixture-token");
  assert.equal(calls[1].headers.get("cookie"), "token=fixture-token");
  assert.equal(calls[1].headers.get("source"), "h5");
  assert.equal(calls[1].headers.get("version"), "0.3.12");
  assert.equal(calls[1].body.version, "2.1");
  assert.equal(calls[1].body.incremental_output, true);
  const messages = calls[1].body.messages as Array<Record<string, unknown>>;
  assert.equal(messages[0].user_action, "chat");
  assert.equal(messages[0].content, "Hi");
  assert.deepEqual(messages[0].files, []);
  assert.equal(calls[1].body.parent_id, null);
});

test("answer finish terminates a split SSE stream even when the connection stays open", async () => {
  let cancelled = false;
  const raw = frames();
  const { executor } = api(
    () =>
      new Response(
        new ReadableStream({
          start(controller) {
            const bytes = new TextEncoder().encode(raw);
            controller.enqueue(bytes.slice(0, bytes.length - 8));
            controller.enqueue(bytes.slice(bytes.length - 8));
          },
          cancel() {
            cancelled = true;
          },
        }),
        { headers: { "content-type": "text/event-stream" } }
      )
  );
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("API must not open a browser"));
  const result = await Promise.race([
    executor.execute({ ...input(), stream: true }),
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 300)),
  ]);
  assert.ok(result, "must stop at the answer terminal event, without [DONE]");
  assert.equal(result.status, 200);
  assert.match(await result.text(), /data: \[DONE\]/);
  assert.equal(cancelled, true);
});

test("thinking finish alone, malformed output and upstream error frames cannot become success", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("must not fall back"));
  for (const body of [
    'data: {"choices":[{"delta":{"phase":"thinking_summary","status":"finished","content":"Summary"}}]}\n\n',
    'data: {"error":{"message":"private token=secret"}}\n\n',
    "data: {broken}\n\n",
    frames()
      .replace(RESPONSE_ID, "invalid-response-id")
      .replaceAll(RESPONSE_ID, "invalid-response-id"),
  ]) {
    const { executor } = api(
      () => new Response(body, { headers: { "content-type": "text/event-stream" } })
    );
    const result = await executor.execute(input());
    assert.equal(result.status, 502);
    assert.doesNotMatch(await result.text(), /private|secret/);
  }
});

test("invalid create-chat ids fail without a completion request", async () => {
  const calls: string[] = [];
  const executor = new QwenBrowserExecutor({
    fetch: async (url) => {
      calls.push(String(url));
      return Response.json({ success: true, data: { id: "https://unexpected.test" } });
    },
  });
  assert.equal((await executor.execute(input())).status, 502);
  assert.equal(calls.length, 1);
});

test("paid models and unsupported attachments fail before the API request", async () => {
  const executor = new QwenBrowserExecutor({ fetch: async () => assert.fail("must not submit") });
  const request = input();
  assert.equal(
    (
      await executor.execute({
        ...request,
        credentials: {
          ...request.credentials,
          providerSpecificData: {
            browserModels: [
              { id: request.model, name: "Qwen3.7-Plus", selectable: true, free: false },
            ],
          },
        },
      })
    ).status,
    400
  );
  assert.equal(
    (
      await executor.execute({
        ...request,
        body: {
          messages: [
            {
              role: "user",
              content: [{ type: "image_url", image_url: { url: "https://fixture.test/image" } }],
            },
          ],
        },
      })
    ).status,
    400
  );
});

test("the observed default UI alias maps to its captured protocol id", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("must not open a browser"));
  const { executor, calls } = api();
  const request = input();
  const model = "qwen-ui-qwen3.7-plus";
  const result = await executor.execute({
    ...request,
    model,
    credentials: {
      ...request.credentials,
      providerSpecificData: {
        browserModels: [{ id: model, name: "Qwen3.7-Plus", selectable: true, free: true }],
      },
    },
  });
  assert.equal(result.status, 200);
  assert.equal((await result.json()).model, model);
  assert.equal(calls[1].body.model, "qwen3.7-plus");
});

test("continuations use the server assistant id, and rotate after ten completed QAs", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("API must not open a browser"));
  const { executor, calls } = api();
  for (let i = 0; i < 11; i++) assert.equal((await executor.execute(input())).status, 200);
  const chats = calls.filter((call) => call.url.endsWith("/chats/new"));
  const completions = calls.filter((call) => call.url.includes("/chat/completions"));
  assert.equal(chats.length, 2);
  assert.equal(completions[1].body.parent_id, RESPONSE_ID);
  assert.equal(completions[1].body.parentId, RESPONSE_ID);
  assert.equal(completions[10].body.parent_id, null);
  assert.match(
    String((completions[10].body.messages as Array<Record<string, unknown>>)[0].content),
    /handoff summary/
  );
});

test("API errors preserve quota hints, never leak secrets and never retry or open a browser", async () => {
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("must not fall back"));
  for (const status of [401, 403, 429]) {
    const { executor, calls } = api(
      () =>
        new Response("private token=secret at C:/private/file.ts:7", {
          status,
          headers: { "retry-after": "60" },
        })
    );
    const result = await executor.execute(input());
    assert.equal(result.status, status);
    assert.equal(calls.length, 2);
    assert.doesNotMatch(await result.text(), /secret|private/);
    if (status === 429) assert.equal(result.headers.get("retry-after"), "60");
  }
});

test("cancelling an API body read and a queued request settles both without another submission", async () => {
  let cancelled = false;
  let opened!: () => void;
  const ready = new Promise<void>((resolve) => {
    opened = resolve;
  });
  const { executor, calls } = api(() => {
    opened();
    return new Response(
      new ReadableStream({
        cancel() {
          cancelled = true;
        },
      }),
      { headers: { "content-type": "text/event-stream" } }
    );
  });
  __setBrowserBackedChatOverrideForTesting(async () => assert.fail("API must not open a browser"));
  const first = new AbortController();
  const pending = executor.execute({ ...input(), signal: first.signal });
  const openedResult = await Promise.race([ready.then(() => true), pending.then(() => false)]);
  assert.equal(openedResult, true, "API stream must be opened");
  const second = new AbortController();
  const queued = executor.execute({ ...input(), signal: second.signal });
  second.abort();
  const queuedResult = await Promise.race([
    queued,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 200)),
  ]);
  assert.ok(queuedResult, "cancelled queued request must settle promptly");
  assert.equal(queuedResult.status, 499);
  const third = new AbortController();
  const later = executor.execute({ ...input(), signal: third.signal });
  await new Promise<void>((resolve) => setImmediate(resolve));
  const submissionsBeforeAbort = calls.length;
  third.abort();
  first.abort();
  assert.equal((await later).status, 499);
  assert.equal(
    submissionsBeforeAbort,
    2,
    "cancelled queue entries must not let later calls bypass the running request"
  );
  assert.equal((await pending).status, 499);
  assert.equal(cancelled, true);
  assert.equal(calls.length, 2);
});
