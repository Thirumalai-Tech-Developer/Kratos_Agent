import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFile } from "node:fs/promises";
import {
  RegularBrowserConnection,
  validBrowserToken,
} from "../src/kratos_agent/brain/chatgpt_regular_browser.mjs";

test("browser receiver rejects unauthenticated and stale results", async () => {
  const token = "private-local-browser-token-for-test";
  const connection = new RegularBrowserConnection({ token });
  connection.port = 0; // Use an isolated port for this protocol test.
  await connection.start();
  const base = "http://127.0.0.1:" + connection.server.address().port;
  const headers = {
    Authorization: "Bearer " + token,
    "Content-Type": "application/json",
  };
  try {
    assert.equal((await fetch(base + "/work")).status, 401);
    const command = connection.command("inspect", {}, 1000);
    const work = await (await fetch(base + "/work", { headers })).json();
    assert.equal(work.action, "inspect");
    assert.deepEqual(
      await (await fetch(base + "/work", { headers })).json(),
      {},
    );
    assert.equal(
      (
        await fetch(base + "/result", {
          headers,
          method: "POST",
          body: JSON.stringify({ id: "stale", result: "wrong" }),
        })
      ).status,
      409,
    );
    await fetch(base + "/result", {
      headers,
      method: "POST",
      body: JSON.stringify({
        id: work.id,
        result: { url: "https://chatgpt.com/", tab_id: 7 },
      }),
    });
    assert.equal((await command).tab_id, 7);
  } finally {
    await connection.close();
  }
});

test("credential receiver rejects model and page commands", async () => {
  const connection = new RegularBrowserConnection({
    token: "private-local-browser-token-for-test",
  });
  for (const action of ["evaluate", "chatgpt-turn", "conversation-tab"])
    await assert.rejects(
      connection.command(action),
      /Unsupported cookie collector/,
    );
  assert.equal(connection.evaluate, undefined);
  assert.equal(validBrowserToken("Bearer wrong", connection.token), false);
});

test("browser failure diagnostics include only a fixed public reason", async () => {
  const token = "private-local-browser-token-for-test";
  const connection = new RegularBrowserConnection({ token });
  connection.port = 0;
  await connection.start();
  const headers = {
    Authorization: "Bearer " + token,
    "Content-Type": "application/json",
  };
  const base = "http://127.0.0.1:" + connection.server.address().port;
  try {
    for (const reason of ["capture", "private-cookie-do-not-expose"]) {
      const command = connection.command("inspect", {}, 1000);
      const rejection = assert.rejects(
        command,
        (error) =>
          error.code === "browser_response_incomplete" &&
          error.reason === (reason === "capture" ? "capture" : null),
      );
      const work = await (await fetch(base + "/work", { headers })).json();
      await fetch(base + "/result", {
        headers,
        method: "POST",
        body: JSON.stringify({
          id: work.id,
          error: "browser_response_incomplete",
          error_reason: reason,
        }),
      });
      await rejection;
      const health = await (await fetch(base + "/health", { headers })).json();
      assert.deepEqual(health.last_failure, {
        code: "browser_response_incomplete",
        reason: reason === "capture" ? "capture" : null,
      });
      assert.ok(!JSON.stringify(health).includes("private-cookie"));
    }
  } finally {
    await connection.close();
  }
});

test("a missing extension fails before the model response deadline", async () => {
  const connection = new RegularBrowserConnection({
    token: "private-local-browser-token-for-test",
    deliveryTimeout: 20,
  });
  connection.port = 0;
  await connection.start();
  try {
    await assert.rejects(
      connection.command("inspect", {}, 240000),
      (error) => error.code === "browser_extension_unavailable",
    );
    assert.equal(connection.pending, null);
  } finally {
    await connection.close();
  }
});

test("a delivered collection retains its result deadline", async () => {
  const token = "private-local-browser-token-for-test";
  const connection = new RegularBrowserConnection({
    token,
    deliveryTimeout: 100,
  });
  connection.port = 0;
  await connection.start();
  const headers = {
    Authorization: "Bearer " + token,
    "Content-Type": "application/json",
  };
  const base = "http://127.0.0.1:" + connection.server.address().port;
  try {
    const command = connection.command("inspect", {}, 1000);
    const work = await (await fetch(base + "/work", { headers })).json();
    await new Promise((resolve) => setTimeout(resolve, 150));
    await fetch(base + "/result", {
      headers,
      method: "POST",
      body: JSON.stringify({ id: work.id, result: "model answer" }),
    });
    assert.equal(await command, "model answer");
  } finally {
    await connection.close();
  }
});

test("Stop cancels delivered browser work and rejects a late response", async () => {
  const token = "private-local-browser-token-for-test";
  const connection = new RegularBrowserConnection({ token });
  connection.port = 0;
  await connection.start();
  const base = "http://127.0.0.1:" + connection.server.address().port;
  const headers = {
    Authorization: "Bearer " + token,
    "Content-Type": "application/json",
  };
  try {
    const command = connection.command("inspect", {}, 300000);
    const rejected = assert.rejects(command, /cancelled/);
    const work = await (await fetch(base + "/work", { headers })).json();
    assert.equal(
      (await fetch(base + "/cancel", { method: "POST" })).status,
      401,
    );
    await fetch(base + "/cancel", { headers, method: "POST" });
    await rejected;
    assert.equal(
      (await (await fetch(base + "/health", { headers })).json()).cancelled,
      true,
    );
    assert.equal(
      (
        await fetch(base + "/result", {
          headers,
          method: "POST",
          body: JSON.stringify({ id: work.id, result: "late reply" }),
        })
      ).status,
      409,
    );
    await assert.rejects(connection.command("inspect"), /cancelled/);
  } finally {
    await connection.close();
  }
});

test("background heartbeat receives work without a provider content script", async () => {
  const source = await readFile(
    new URL(
      "../src/kratos_agent/brain/chatgpt_browser_extension/background.js",
      import.meta.url,
    ),
    "utf8",
  );
  let heartbeat;
  let interval;
  const requests = [];
  const chrome = {
    runtime: { onMessage: { addListener() {} } },
    cookies: { onChanged: { addListener() {} } },
    alarms: {
      create(name, options) {
        assert.equal(name, "kratos-cookie-refresh");
        assert.equal(options.periodInMinutes, 1);
      },
      onAlarm: {
        addListener(fn) {
          heartbeat = fn;
        },
      },
    },
  };
  vm.runInNewContext(source, {
    chrome,
    URL,
    AbortSignal,
    importScripts() {},
    setInterval(fn) {
      interval = fn;
    },
    KRATOS_BROWSER: {
      endpoint: "http://127.0.0.1:12345",
      token: "private",
      providers: {},
    },
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, json: async () => ({ accounts: [] }) };
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(requests.length, 1);
  heartbeat({ name: "kratos-browser-work" });
  await new Promise((resolve) => setImmediate(resolve));
  interval();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(requests.filter((url) => url.endsWith("/work")).length, 3);
  assert.ok(
    requests.every((url) => url.endsWith("/work") || url.endsWith("/status")),
  );
});

test("an unavailable companion changes a previously green badge to red", async () => {
  const source = await readFile(
    new URL(
      "../src/kratos_agent/brain/chatgpt_browser_extension/background.js",
      import.meta.url,
    ),
    "utf8",
  );
  const listeners = [];
  let color, badge;
  const chrome = {
    runtime: {
      getURL: (name) => "chrome-extension://test/" + name,
      onMessage: {
        addListener(fn) {
          listeners.push(fn);
        },
      },
    },
    cookies: { onChanged: { addListener() {} } },
    action: {
      setBadgeText: async ({ text }) => {
        badge = text;
      },
      setBadgeBackgroundColor: async ({ color: value }) => {
        color = value;
      },
    },
  };
  vm.runInNewContext(source, {
    chrome,
    URL,
    AbortSignal,
    importScripts() {},
    KRATOS_BROWSER: {
      control: "http://127.0.0.1:12345",
      endpoint: "http://127.0.0.1:12346",
      token: "private",
    },
    fetch: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  const reply = await new Promise((resolve) =>
    listeners[0](
      { kind: "kratos-panel", action: "status" },
      { url: chrome.runtime.getURL("popup.html") },
      resolve,
    ),
  );
  assert.equal(color, "#ef4444");
  assert.equal(badge, "!");
  assert.match(reply.error, /Keep Kratos Studio running/);
});
