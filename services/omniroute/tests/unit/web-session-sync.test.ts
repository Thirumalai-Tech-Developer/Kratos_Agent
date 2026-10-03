import assert from "node:assert/strict";
import { test } from "node:test";
import {
  blockedConnection,
  metaAuthorization,
  normalizeSnapshot,
  syncConfig,
} from "../../scripts/ops/webSessionSyncCore";

const jwt = (exp: number) =>
  `eyJhbGciOiJIUzI1NiJ9.${Buffer.from(JSON.stringify({ exp })).toString("base64url")}.signature`;
const snapshot = (token: string) => ({
  cookies: [{ name: "auth", value: "cookie", domain: ".qwen.ai", expires: -1 }],
  storage: { token },
  userAgent: "Browser",
});

test("Qwen renewal changes the fingerprint and uses the fresh bearer token", () => {
  const first = normalizeSnapshot("qwen-browser", snapshot(jwt(4102444800)));
  const renewed = normalizeSnapshot("qwen-browser", snapshot(jwt(4102444900)));
  assert.ok(first && renewed);
  assert.equal(renewed.apiKey, jwt(4102444900));
  assert.equal(renewed.data.cookie, "auth=cookie");
  assert.notEqual(first.fingerprint, renewed.fingerprint);
  assert.equal(
    normalizeSnapshot("qwen-browser", snapshot(jwt(4102444900)))?.fingerprint,
    renewed.fingerprint
  );
});

test("Expired bearer credentials cannot overwrite a working connection", () => {
  assert.equal(normalizeSnapshot("qwen-browser", snapshot(jwt(1))), null);
});

test("Model-only changes sync even when the browser credential is unchanged", () => {
  const base = snapshot(jwt(4102444800));
  const first = normalizeSnapshot("qwen-browser", {
    ...base,
    models: [{ id: "qwen-ui-observed", name: "Observed Qwen", selectable: true }],
  });
  const changed = normalizeSnapshot("qwen-browser", {
    ...base,
    models: [{ id: "qwen-ui-observed", name: "Observed Qwen", selectable: false }],
  });
  assert.ok(first && changed);
  assert.equal(first.apiKey, changed.apiKey);
  assert.notEqual(first.fingerprint, changed.fingerprint);
  assert.deepEqual(changed.data.browserModels, [
    { id: "qwen-ui-observed", name: "Observed Qwen", selectable: false },
  ]);
  const unobserved = normalizeSnapshot("qwen-browser", base);
  assert.equal(unobserved?.data.browserModels, undefined);
  const cleared = normalizeSnapshot("qwen-browser", { ...base, models: [] });
  assert.deepEqual(cleared?.data.browserModels, []);
});

test("Cookie provider captures only live cookies on the authorized domain", () => {
  const result = normalizeSnapshot("claude-web", {
    storage: {},
    userAgent: "Browser",
    cookies: [
      { name: "sessionKey", value: "valid", domain: ".claude.ai", expires: -1 },
      { name: "expired", value: "old", domain: ".claude.ai", expires: 1 },
      { name: "sessionKey", value: "attacker", domain: "claude.ai.attacker.test", expires: -1 },
    ],
  });
  assert.ok(result);
  assert.equal(result.data.cookie, "sessionKey=valid");
  assert.equal(result.apiKey, null);
});

test("Local-storage JSON wrappers and Kimi current tokens are normalized", () => {
  const result = normalizeSnapshot("kimi-web", {
    cookies: [],
    storage: { access_token: JSON.stringify({ value: jwt(4102444800) }) },
    userAgent: "Browser",
  });
  assert.ok(result);
  assert.equal(result.apiKey, jwt(4102444800));
});

test("Meta requires its companion token and only captures the legitimate websocket URL", () => {
  assert.equal(
    metaAuthorization("wss://gateway.meta.ai/ws/clippy?Authorization=ecto1%3Avalue"),
    "ecto1:value"
  );
  assert.equal(
    metaAuthorization("wss://gateway.meta.ai.attacker.test/ws/clippy?Authorization=ecto1%3Avalue"),
    undefined
  );
  const base = {
    storage: {},
    userAgent: "Browser",
    cookies: [{ name: "ecto_1_sess", value: "session", domain: ".meta.ai", expires: -1 }],
  };
  assert.equal(normalizeSnapshot("muse-spark-web", base), null);
  assert.equal(
    normalizeSnapshot("muse-spark-web", { ...base, authorization: "ecto1:value" })?.data
      .authorization,
    "ecto1:value"
  );
});

test("Account restrictions stay terminal and unsupported sites are excluded", () => {
  assert.ok(blockedConnection({ testStatus: "banned" }));
  assert.ok(blockedConnection({ lastErrorType: "credits_exhausted" }));
  assert.equal(blockedConnection({ testStatus: "expired" }), false);
  assert.equal(syncConfig("volcengine-console"), undefined);
  assert.equal(syncConfig("unknown-web"), undefined);
});
