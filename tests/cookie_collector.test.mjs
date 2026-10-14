import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFile } from "node:fs/promises";

const root = new URL(
  "../src/kratos_agent/brain/chatgpt_browser_extension/",
  import.meta.url,
);
async function fixture(tabs = []) {
  const requests = [];
  const cookie = {
    name: "session",
    value: "test-session",
    domain: ".chatgpt.com",
    path: "/",
    secure: true,
    httpOnly: true,
    sameSite: "lax",
  };
  const context = vm.createContext({
    URL,
    AbortSignal,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    navigator: { userAgent: "test-browser" },
    importScripts: () => {},
    KRATOS_BROWSER: {
      token: "test-token",
      endpoint: "http://127.0.0.1:20130",
      control: "http://127.0.0.1:20131",
      providers: {
        "chatgpt-web": {
          name: "ChatGPT",
          url: "https://chatgpt.com/",
          domains: ["chatgpt.com", "openai.com"],
        },
      },
    },
    chrome: {
      tabs: {
        query: async () => tabs,
        get: async (id) => tabs.find((t) => t.id === id),
        sendMessage: async () => ({
          origin: "https://chatgpt.com",
          localStorage: [{ name: "token", value: "test-storage" }],
        }),
        create: () => assert.fail("Collector must not create tabs"),
        update: () => assert.fail("Collector must not navigate or focus tabs"),
      },
      cookies: {
        getAllCookieStores: async () => [
          { id: "0", tabIds: tabs.map((t) => t.id) },
        ],
        getAll: async ({ domain }) =>
          domain === "chatgpt.com" ? [cookie, cookie] : [],
        onChanged: { addListener() {} },
      },
      runtime: {
        id: "test-extension",
        getURL: (p) => "chrome-extension://test/" + p,
        onMessage: { addListener() {} },
      },
      action: {
        setBadgeText: async () => {},
        setBadgeBackgroundColor: async () => {},
      },
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => ({ ready: true, accounts: [] }) };
    },
  });
  vm.runInContext(
    await readFile(new URL("background.js", root), "utf8"),
    context,
  );
  return { context, requests };
}
test("collects Playwright cookie state with the provider website closed", async () => {
  const { context } = await fixture();
  const snapshot = await vm.runInContext(
    "collectSnapshot('chatgpt-web', '0')",
    context,
  );
  assert.equal(snapshot.storage_state.cookies.length, 1);
  assert.equal(snapshot.storage_state.cookies[0].expires, -1);
  assert.equal(snapshot.storage_state.cookies[0].sameSite, "Lax");
  assert.equal(snapshot.storage_state.origins.length, 0);
});
test("reads storage from an existing tab without changing its URL or draft", async () => {
  const { context } = await fixture([
    { id: 8, url: "https://chatgpt.com/c/existing-chat" },
  ]);
  const snapshot = await vm.runInContext(
    "collectSnapshot('chatgpt-web', '0')",
    context,
  );
  assert.equal(
    snapshot.storage_state.origins[0].localStorage[0].value,
    "test-storage",
  );
  assert.equal(snapshot.url, "https://chatgpt.com/");
});
test("rejects model and arbitrary page commands in the collector", async () => {
  const { context } = await fixture();
  for (const action of [
    "chatgpt-turn",
    "gemini-turn",
    "groq-turn",
    "evaluate",
    "conversation-tab",
  ])
    await assert.rejects(
      vm.runInContext(`handleWork({action: '${action}'})`, context),
      /Unsupported/,
    );
});
