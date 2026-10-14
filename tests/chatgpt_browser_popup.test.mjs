import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(
  new URL("../services/omniroute/package.json", import.meta.url),
);
const { JSDOM } = require("jsdom");
const root = new URL(
  "../src/kratos_agent/brain/chatgpt_browser_extension/",
  import.meta.url,
);

async function panelFixture(initial) {
  const html = await readFile(new URL("popup.html", root), "utf8");
  const script = await readFile(new URL("popup.js", root), "utf8");
  const dom = new JSDOM(html, { runScripts: "outside-only" });
  const calls = [];
  let state = initial;
  dom.window.chrome = {
    runtime: {
      sendMessage: async (message) => {
        calls.push(message);
        return message.action === "status" ? state : { accepted: true };
      },
    },
  };
  dom.window.setInterval = () => 0;
  vm.runInContext(script, dom.getInternalVMContext());
  await new Promise((resolve) => setTimeout(resolve, 5));
  return {
    dom,
    calls,
    setState(value) {
      state = value;
    },
  };
}

const account = {
  id: "one",
  email: "owner@example.com",
  connected: true,
  active: true,
  model: "chatgpt-web/one",
  models: [
    { id: "chatgpt-web/one", display_name: "One" },
    { id: "chatgpt-web/two", display_name: "Two" },
  ],
};

test("popup shows green connected logins and selects the displayed account model", async () => {
  const { dom, calls } = await panelFixture({
    ready: true,
    accounts: [account],
    busy: false,
  });
  try {
    const document = dom.window.document;
    assert.equal(
      document.querySelector(".tag.connected").textContent,
      "Connected",
    );
    assert.match(document.querySelector(".active-label").textContent, /Active/);
    document.querySelector("#model-one").value = "chatgpt-web/two";
    [...document.querySelectorAll(".account button")]
      .find((button) => button.textContent === "Use model")
      .click();
    await new Promise((resolve) => setTimeout(resolve, 5));
    const selection = calls.find((call) => call.action === "select");
    assert.equal(selection.data.account_id, "one");
    assert.equal(selection.data.model, "chatgpt-web/two");
  } finally {
    dom.window.close();
  }
});

test("a failed login displays a red error and allows reconnecting", async () => {
  const { dom } = await panelFixture({
    ready: true,
    accounts: [account],
    busy: false,
    error: "Sign in again",
  });
  try {
    const document = dom.window.document;
    assert.equal(
      document.getElementById("notice").classList.contains("error"),
      true,
    );
    assert.equal(
      document.getElementById("notice").textContent,
      "Sign in again",
    );
    assert.equal(document.getElementById("connect").disabled, false);
  } finally {
    dom.window.close();
  }
});

test("thinking capacity sends the chosen supported tier with the model", async () => {
  const thinkingAccount = {
    ...account,
    reasoning_effort: "medium",
    models: [
      {
        id: account.model,
        display_name: "Thinking model",
        supports_reasoning: true,
        effort_tiers: ["low", "medium", "high"],
      },
      account.models[1],
    ],
  };
  const { dom, calls } = await panelFixture({
    ready: true,
    accounts: [thinkingAccount],
    busy: false,
  });
  try {
    const document = dom.window.document;
    const effort = document.getElementById("effort-one");
    assert.equal(effort.value, "medium");
    assert.equal(effort.disabled, false);
    effort.value = "high";
    [...document.querySelectorAll(".account button")]
      .find((button) => button.textContent === "Use model")
      .click();
    await new Promise((resolve) => setTimeout(resolve, 5));
    assert.equal(
      calls.find((call) => call.action === "select").data.reasoning_effort,
      "high",
    );
    const model = document.getElementById("model-one");
    model.value = account.models[1].id;
    model.dispatchEvent(new dom.window.Event("change"));
    assert.equal(effort.disabled, true);
    assert.equal(effort.value, "");
  } finally {
    dom.window.close();
  }
});

test("Connect uses the selected provider and all requested websites are listed", async () => {
  const { dom, calls } = await panelFixture({
    ready: true,
    accounts: [],
    busy: false,
  });
  try {
    const selector = dom.window.document.getElementById("provider");
    assert.deepEqual(
      [...selector.options].map((option) => option.textContent),
      ["ChatGPT", "Qwen", "Dola", "Gemini", "DeepSeek", "Kimi", "Meta AI", "Groq Chat", "Grok", "Claude", "Perplexity", "Z.ai"],
    );
    selector.value = "deepseek-web";
    dom.window.document.getElementById("connect").click();
    await new Promise((resolve) => setTimeout(resolve, 5));
    assert.equal(
      calls.find((call) => call.action === "connect").data.provider,
      "deepseek-web",
    );
  } finally {
    dom.window.close();
  }
});

test("receiver failure is red and recovery restores controls without injecting account text", async () => {
  const initial = {
    ready: true,
    accounts: [{ ...account, email: "<img src=x onerror=alert(1)>" }],
    busy: false,
  };
  const { dom, setState } = await panelFixture(initial);
  try {
    const document = dom.window.document;
    assert.equal(document.querySelectorAll("img").length, 0);
    setState({ error: "Connection panel unavailable" });
    await dom.window.refresh();
    assert.equal(
      document.querySelector("#notice.error").textContent,
      "Connection panel unavailable",
    );
    assert.equal(document.querySelector("#model-one").disabled, true);
    setState(initial);
    await dom.window.refresh();
    assert.equal(document.querySelector("#model-one").disabled, false);
    assert.equal(document.getElementById("connect").disabled, false);
  } finally {
    dom.window.close();
  }
});
