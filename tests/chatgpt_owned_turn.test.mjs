import assert from "node:assert/strict";
import test from "node:test";
import { runOwnedCookieTurn } from "../src/kratos_agent/brain/chatgpt_owned_turn.mjs";

function fixture() {
  const calls = [];
  let text = "",
    listener;
  const composer = {
    innerText: async () => text,
    focus: async () => {},
    evaluate: async (_fn, value) => {
      text = value;
      return true;
    },
    filter() {
      return this;
    },
    last() {
      return this;
    },
  };
  const page = {
    evaluate: async (fn, args) => {
      calls.push(fn.name);
      if (fn.name === "chatgptComposerSelection")
        return { modelSelected: true };
      if (fn.name === "chatgptEffortSelection")
        return { min: 0, max: 4, value: 1 };
      if (fn.name === "chatgptAssistantSnapshot")
        return { count: 1, keys: ["old-answer"] };
      if (fn.name === "chatgptCompletedAssistant") {
        assert.equal(args.prompt, "own-prompt");
        assert.equal(args.submittedMessage.id, "owned-user");
        return {
          text: "new-answer",
          conversationId: "actual-conversation",
          turnExchangeId: "new-assistant",
        };
      }
      return 1;
    },
    keyboard: { press: async (key) => calls.push(key) },
    locator: (selector) =>
      selector.includes('button[aria-label="Send message"]')
        ? {
            filter() {
              return this;
            },
            first() {
              return this;
            },
            click: async () => page.getByTestId("send-button").click(),
          }
        : composer,
    on: (_name, fn) => {
      listener = fn;
    },
    off: () => {
      listener = null;
    },
    getByTestId: (id) => ({
      click: async () => {
        calls.push(id);
        listener({
          url: () => "https://chatgpt.com/backend-api/f/conversation",
          ok: () => true,
          request: () => ({
            postData: () =>
              JSON.stringify({
                messages: [
                  {
                    id: "owned-user",
                    author: { role: "user" },
                    content: { parts: [text] },
                  },
                ],
              }),
          }),
          text: async () => "data: [DONE]\n\n",
        });
      },
    }),
  };
  return { page, calls };
}
test("executor browser submits and returns only the newly completed matching turn", async () => {
  const { page, calls } = fixture();
  const result = await runOwnedCookieTurn(
    page,
    { kind: "picker", effortIndex: 1 },
    { prompt: "own-prompt" },
    () => true,
    () => ({}),
  );
  assert.equal(result.text, "new-answer");
  assert.equal(result.endTurn, true);
  assert.ok(calls.includes("send-button"));
});
test("cancelled or unavailable model never submits a message", async () => {
  const { page, calls } = fixture();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    runOwnedCookieTurn(
      page,
      {},
      { prompt: "own", signal: controller.signal },
      () => true,
      () => {},
    ),
    /Aborted/,
  );
  assert.equal(calls.length, 0);
  page.evaluate = async () => ({ error: "browser_model_unavailable" });
  await assert.rejects(
    runOwnedCookieTurn(
      page,
      {},
      { prompt: "own" },
      () => true,
      () => {},
    ),
    /browser_model_unavailable/,
  );
  assert.ok(!calls.includes("send-button"));
});

test("a missing saved conversation parent cannot submit a follow-up", async () => {
  const { page, calls } = fixture();
  page.waitForFunction = async () => {
    throw new Error("parent missing");
  };
  await assert.rejects(
    runOwnedCookieTurn(
      page,
      { kind: "picker", effortIndex: 1 },
      { prompt: "own-prompt" },
      () => true,
      () => ({}),
      { remote: { conversation_id: "saved", parent_message_id: "parent" } },
    ),
    /browser_conversation_lost/,
  );
  assert.ok(!calls.includes("send-button"));
});

test("thinking control moves one acknowledged slider step at a time", async () => {
  const { page, calls } = fixture();
  const evaluate = page.evaluate;
  let value = 4;
  page.evaluate = async (fn, args) =>
    fn.name === "chatgptEffortSelection"
      ? { min: 1, max: 5, value }
      : fn.name === "chatgptEffortState"
        ? { min: 1, max: 5, value }
        : evaluate(fn, args);
  const press = page.keyboard.press;
  page.keyboard.press = async (key) => {
    if (key === "ArrowLeft" || key === "ArrowRight") {
      calls.push(key);
      setTimeout(() => {
        value += key === "ArrowLeft" ? -1 : 1;
      }, 10);
    } else await press(key);
  };
  const result = await runOwnedCookieTurn(
    page,
    { kind: "picker", effortIndex: 1 },
    { prompt: "own-prompt" },
    () => true,
    () => ({}),
  );
  assert.equal(result.text, "new-answer");
  assert.equal(value, 2);
  assert.deepEqual(
    calls.filter((k) => k === "ArrowLeft" || k === "ArrowRight"),
    ["ArrowLeft", "ArrowLeft"],
  );
});
