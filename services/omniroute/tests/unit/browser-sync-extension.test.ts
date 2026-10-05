import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createContext, runInContext } from "node:vm";
import { webcrypto } from "node:crypto";
import { normalizeSnapshot, syncConfig } from "../../scripts/ops/webSessionSyncCore";

const source = await readFile(
  new URL("../../scripts/ops/browserSyncExtension/background.js", import.meta.url),
  "utf8"
);

interface BrowserCookie {
  name: string;
  value: string;
  domain: string;
  path?: string;
  expirationDate?: number;
}

interface Tab {
  id: number;
  url: string;
}

type EventListener = (...args: unknown[]) => unknown;
const event = () => {
  const listeners: EventListener[] = [];
  return {
    addListener: (listener: EventListener) => listeners.push(listener),
    emit: async (...args: unknown[]) => {
      for (const listener of listeners) await listener(...args);
    },
  };
};

function harness(options: {
  providers: string[];
  tabs?: Tab[];
  cookies?: Record<string, BrowserCookie[]>;
  snapshots?: Record<number, Record<string, unknown>>;
  missingContentScript?: boolean;
  statuses?: Record<string, number>;
}) {
  const installed = event();
  const cookieChanged = event();
  const requests: Array<{ provider: string; snapshot: Record<string, unknown> }> = [];
  const injections: Array<{ target: { tabId: number }; files: string[]; world?: string }> = [];
  const badges: string[] = [];
  const titles: string[] = [];
  const messages: Array<{ authIdentity: string }> = [];
  let timersScheduled = 0;
  const context = createContext({
    SYNC_CONFIG: {
      token: "test-local-bridge-token",
      endpoint: "http://127.0.0.1:20129",
      providers: options.providers.map((id) => {
        const config = syncConfig(id)!;
        return {
          id,
          homeUrl: config.homeUrl,
          domain: config.cookieDomain || new URL(config.homeUrl).hostname,
          sources: config.tokenSources,
        };
      }),
    },
    importScripts: () => {},
    navigator: { userAgent: "Original Chrome worker UA" },
    URL,
    AbortSignal,
    crypto: webcrypto,
    TextEncoder,
    setTimeout: () => ++timersScheduled,
    clearTimeout: () => {},
    fetch: async (_url: string, init: RequestInit) => {
      const payload = JSON.parse(String(init.body));
      requests.push(payload);
      return new Response("{}", { status: options.statuses?.[payload.provider] || 200 });
    },
    chrome: {
      tabs: {
        query: async () => options.tabs || [],
        sendMessage: async (id: number, message: { authIdentity: string }) => {
          messages.push(message);
          if (options.missingContentScript) throw new Error("Content script unavailable");
          return options.snapshots?.[id] || { storage: {}, userAgent: "Original tab UA" };
        },
        onUpdated: event(),
      },
      cookies: {
        getAll: async ({ domain }: { domain: string }) => options.cookies?.[domain] || [],
        onChanged: cookieChanged,
      },
      action: {
        setBadgeText: async ({ text }: { text: string }) => badges.push(text),
        setTitle: async ({ title }: { title: string }) => titles.push(title),
        onClicked: event(),
      },
      runtime: { onInstalled: installed, onStartup: event() },
      scripting: {
        executeScript: async (injection: (typeof injections)[number]) => {
          injections.push(injection);
        },
      },
      alarms: { create: async () => {}, onAlarm: event() },
    },
  });
  runInContext(source, context, { filename: "background.js" });
  return {
    scan: context.scan as () => Promise<void>,
    installed,
    cookieChanged,
    requests,
    injections,
    badges,
    titles,
    messages,
    timersScheduled: () => timersScheduled,
  };
}

const claudeCookie: BrowserCookie = {
  name: "sessionKey",
  value: "test-session",
  domain: ".claude.ai",
  path: "/",
  expirationDate: 4102444800,
};

test("Cookie sessions sync from the original Chrome even when provider tabs are closed", async () => {
  const browser = harness({ providers: ["claude-web"], cookies: { "claude.ai": [claudeCookie] } });
  await browser.scan();
  assert.equal(browser.requests.length, 1);
  assert.equal(browser.requests[0].provider, "claude-web");
  assert.equal(browser.requests[0].snapshot.userAgent, "Original Chrome worker UA");
  assert.deepEqual(browser.requests[0].snapshot.cookies, [
    {
      name: "sessionKey",
      value: "test-session",
      domain: ".claude.ai",
      path: "/",
      expires: 4102444800,
    },
  ]);
  assert.equal(browser.badges.at(-1), "1");
  assert.match(browser.titles.at(-1)!, /1\/1.*synced/);
});

test("Session and analytics cookie renewal preserve account identity; account changes do not", async () => {
  const cookies = {
    "claude.ai": [
      claudeCookie,
      { name: "user_id", value: "account-a", domain: ".claude.ai" },
      { name: "analytics", value: "first", domain: ".claude.ai" },
    ],
  };
  const browser = harness({
    providers: ["claude-web"],
    tabs: [{ id: 1, url: "https://claude.ai/new" }],
    cookies,
  });
  await browser.scan();
  const first = browser.messages.at(-1)!.authIdentity;
  cookies["claude.ai"][0] = { ...claudeCookie, value: "renewed-session" };
  cookies["claude.ai"][2].value = "renewed-analytics";
  await browser.scan();
  assert.equal(browser.messages.at(-1)!.authIdentity, first);
  cookies["claude.ai"][1].value = "account-b";
  await browser.scan();
  assert.notEqual(browser.messages.at(-1)!.authIdentity, first);
});

test("Missing content scripts do not prevent authenticated cookie-only sync", async () => {
  const browser = harness({
    providers: ["claude-web"],
    tabs: [{ id: 1, url: "https://claude.ai/new" }],
    missingContentScript: true,
    cookies: { "claude.ai": [claudeCookie] },
  });
  await browser.scan();
  assert.equal(browser.requests.length, 1);
  assert.equal(browser.requests[0].snapshot.userAgent, "Original Chrome worker UA");
  assert.equal(browser.badges.at(-1), "1");
});

test("One successful provider cannot hide another provider's failed sync", async () => {
  const browser = harness({
    providers: ["qwen-browser", "claude-web"],
    tabs: [{ id: 2, url: "https://chat.qwen.ai/" }],
    snapshots: { 2: { storage: { token: "test-token" }, userAgent: "Original Chrome UA" } },
    cookies: { "claude.ai": [claudeCookie] },
    statuses: { "qwen-browser": 503 },
  });
  await browser.scan();
  assert.equal(browser.badges.at(-1), "!");
  assert.match(browser.titles.at(-1)!, /1\/2.*synced/);
  assert.match(browser.titles.at(-1)!, /qwen-browser/);
});

test("No captured session is reported honestly and missing Qwen tokens require a signed-in tab", async () => {
  const browser = harness({ providers: ["qwen-browser"] });
  await browser.scan();
  assert.equal(browser.requests.length, 0);
  assert.equal(browser.badges.at(-1), "0");
  assert.match(browser.titles.at(-1)!, /0\/1.*synced/);
  assert.match(browser.titles.at(-1)!, /qwen-browser.*signed-in tab.*token/);
});

test("Existing Meta tabs receive isolated content capture and the MAIN-world observer at installation", async () => {
  const browser = harness({
    providers: ["muse-spark-web"],
    tabs: [{ id: 3, url: "https://www.meta.ai/" }],
    snapshots: { 3: { storage: {}, userAgent: "Original Chrome UA", authorization: "ecto1:test" } },
    cookies: { "meta.ai": [{ name: "ecto_1_sess", value: "test-session", domain: ".meta.ai" }] },
  });
  await browser.installed.emit();
  assert.deepEqual(
    browser.injections.map(({ files, world }) => ({ files: [...files], world })),
    [
      { files: ["modelDiscovery.js", "content.js"], world: undefined },
      { files: ["modelObserver.js"], world: "MAIN" },
      { files: ["metaObserver.js"], world: "MAIN" },
    ]
  );
});

test("Meta without its websocket companion is explicit and cannot report a successful capture", async () => {
  const browser = harness({
    providers: ["muse-spark-web"],
    cookies: { "meta.ai": [{ name: "ecto_1_sess", value: "test-session", domain: ".meta.ai" }] },
  });
  await browser.scan();
  assert.equal(browser.requests.length, 0);
  assert.equal(browser.badges.at(-1), "0");
  assert.match(browser.titles.at(-1)!, /muse-spark-web.*companion/);
});

test("Cookie-change events only schedule scans for configured domain boundaries", async () => {
  const browser = harness({ providers: ["claude-web"] });
  await browser.cookieChanged.emit({ cookie: { domain: ".unrelated.test" } });
  await browser.cookieChanged.emit({ cookie: { domain: "claude.ai.attacker.test" } });
  assert.equal(browser.timersScheduled(), 0);
  await browser.cookieChanged.emit({ cookie: { domain: ".claude.ai" } });
  assert.equal(browser.timersScheduled(), 1);
});

test("Dola normalization preserves the actual browser User-Agent for its executor", () => {
  const captured = normalizeSnapshot("doubao-web", {
    cookies: [{ name: "sessionid", value: "test-session", domain: ".dola.com" }],
    storage: {},
    userAgent: "Original Chrome provider UA",
  });
  assert.ok(captured);
  assert.equal(captured.data.userAgent, "Original Chrome provider UA");
});
