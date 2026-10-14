import assert from "node:assert/strict";
import test from "node:test";
import {
  conversationUrl,
  ownedExecutorTab,
  isRemoteConversationPage,
  navigateExecutorPage,
  completedParent,
} from "../src/kratos_agent/brain/chatgpt_cookie_executor.mjs";
import {
  cookieProviderMain,
  readExecutorCompletion,
} from "../src/kratos_agent/brain/web_cookie_bridge.mjs";

test("continuation reopens only a validated provider conversation URL", () => {
  assert.equal(
    conversationUrl({
      conversation_id: "real-chat",
      parent_message_id: "real-assistant",
    }),
    "https://chatgpt.com/c/real-chat",
  );
  for (const remote of [
    {},
    { conversation_id: "https://evil.test", parent_message_id: "id" },
    { conversation_id: "real-chat" },
  ])
    assert.throws(() => conversationUrl(remote), /browser_conversation_lost/);
});
test("only completed assistant messages can become a continuation parent", () => {
  class Decoder {
    ingest(value) {
      this.message = JSON.parse(value.split("data: ")[1]);
    }
    snapshot() {
      return { message: this.message };
    }
  }
  const items = (body) =>
    body.map((message) => ({
      event: "message",
      data: JSON.stringify(message),
    }));
  assert.equal(
    completedParent(
      [
        {
          id: "user",
          author: { role: "user" },
          status: "finished_successfully",
          end_turn: true,
        },
      ],
      Decoder,
      items,
    ),
    undefined,
  );
  assert.equal(
    completedParent(
      [
        {
          id: "actual-parent",
          author: { role: "assistant" },
          status: "finished_successfully",
          end_turn: true,
        },
      ],
      Decoder,
      items,
    ),
    "actual-parent",
  );
});
test("a cookie provider executes using saved credentials without extension commands", async () => {
  let received;
  class Executor {
    async execute(input) {
      received = input;
      return Response.json({ choices: [{ message: { content: "reply" } }] });
    }
  }
  const state = {
    cookies: [{ name: "session", value: "test-token", domain: ".claude.ai" }],
    origins: [],
  };
  const load = async (file) =>
    file.includes("/registry/")
      ? {
          claude_webProvider: {
            id: "claude-web",
            models: [{ id: "claude-test", name: "Test" }],
          },
        }
      : file.endsWith("webSessionSyncCore.ts")
        ? {
            normalizeSnapshot: () => ({
              apiKey: "cookie-envelope",
              data: { cookie: "session=test-token" },
            }),
          }
        : { ClaudeWebExecutor: Executor };
  const result = await cookieProviderMain(
    {
      mode: "complete",
      provider_id: "claude-web",
      account_id: "one",
      storage_state: state,
      payload: {
        model: "claude-web/claude-test",
        messages: [{ role: "user", content: "hi" }],
      },
    },
    load,
  );
  assert.equal(result.text, "reply");
  assert.equal(received.credentials.apiKey, "cookie-envelope");
  assert.equal(received.credentials.connectionId, "one");
});
test("OmniRoute tool blocks are handed to Kratos schema validation as a JSON envelope", async () => {
  const result = await readExecutorCompletion(
    Response.json({
      choices: [
        {
          message: {
            content: null,
            tool_calls: [
              {
                function: {
                  name: "read_file",
                  arguments: '{"path":"README.md"}',
                },
              },
            ],
          },
        },
      ],
    }),
  );
  assert.deepEqual(JSON.parse(result.text), {
    text: "",
    tool_calls: [{ name: "read_file", arguments: { path: "README.md" } }],
  });
});

test("transient navigation failure retries before submission, with a fixed limit", async () => {
  let calls = 0;
  const page = {
    goto: async () => {
      if (++calls === 1) throw new Error("net::ERR_ABORTED");
    },
  };
  assert.deepEqual(
    await navigateExecutorPage(page, "https://chatgpt.com/", {
      pause: async () => {},
    }),
    { ok: true },
  );
  assert.equal(calls, 2);
  calls = 0;
  page.goto = async () => {
    calls++;
    throw new Error("net::ERR_CONNECTION_CLOSED private-detail");
  };
  assert.deepEqual(
    await navigateExecutorPage(page, "https://chatgpt.com/", {
      pause: async () => {},
    }),
    { ok: false, network: "ERR_CONNECTION_CLOSED" },
  );
  assert.equal(calls, 2);
});
test("navigation never retries certificate failures or leaves the provider origin", async () => {
  let calls = 0;
  const page = {
    goto: async () => {
      calls++;
      throw new Error("net::ERR_CERT_AUTHORITY_INVALID");
    },
  };
  assert.deepEqual(await navigateExecutorPage(page, "https://chatgpt.com/"), {
    ok: false,
    network: "ERR_CERT_AUTHORITY_INVALID",
  });
  assert.equal(calls, 1);
  await assert.rejects(
    navigateExecutorPage(page, "https://example.test/"),
    /Invalid executor origin/,
  );
  assert.equal(calls, 1);
});

test('consecutive requests reuse the same owned tab, separate sessions get separate tabs',async()=>{
  let opened=0;const pooled={context:{}};
  const open=async()=>{opened++;return {isClosed:()=>false,close:async()=>{}};};
  const first=await ownedExecutorTab(pooled,'test-session-a',open);
  const second=await ownedExecutorTab(pooled,'test-session-a',open);
  const other=await ownedExecutorTab(pooled,'test-session-b',open);
  assert.equal(first.page,second.page);
  assert.equal(first.instance,second.instance);
  assert.equal(second.reused,true);
  assert.notEqual(other.page,first.page);
  assert.equal(opened,2);
  assert.ok(isRemoteConversationPage('https://chatgpt.com/c/remote?model=x',{conversation_id:'remote'}));
  assert.equal(isRemoteConversationPage('https://example.test/c/remote',{conversation_id:'remote'}),false);
});
