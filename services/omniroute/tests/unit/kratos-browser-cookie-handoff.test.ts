import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Imports can initialize dependencies: configure an isolated encrypted store first.
process.env.DATA_DIR = mkdtempSync(join(tmpdir(), "kratos-cookie-handoff-test-"));
process.env.STORAGE_ENCRYPTION_KEY = "test-only-cookie-handoff-key";
process.env.OMNIROUTE_INTERNAL_SERVICE_TOKEN = "test-only-cookie-service-token";
process.env.NODE_ENV = "test";
const { handoffBrowserCookies, BrowserCookieHandoffError } = await import("../../src/lib/kratos/browserCookieHandoff.ts");
const { POST } = await import("../../src/app/api/kratos/browser-cookies/route.ts");
const { AUTHZ_HEADER_PEER_LOCALITY } = await import("../../src/server/authz/headers.ts");
type Row = Record<string, any>;
const state = (value = "test-only-session") => ({ cookies: [{ name: "__Secure-next-auth.session-token", value,
  domain: ".chatgpt.com", path: "/", expires: -1, secure: true, httpOnly: true, sameSite: "Lax" }], origins: [] });
const input = (value = "test-only-session") => ({ provider: "chatgpt-web", account_id: "a".repeat(24), storage_state: state(value), user_agent: "test-browser" });
function repository(initial: Row[] = []) {
  const rows = [...initial];
  const writes: Row[] = [];
  return { rows, writes,
    getConnections: async (provider: string) => rows.filter(row => row.provider === provider),
    create: async (data: Row) => { const row = { ...data, id: `connection-${rows.length}` }; rows.push(row); writes.push(data); return row; },
    update: async (id: string, data: Row) => { Object.assign(rows.find(row => row.id === id)!, data); writes.push(data); },
    seal: (_data: Row) => "enc:v1:test-sealed-credential",
  };
}

test("ChatGPT handoff creates encrypted native Codex credentials, never a retired generic provider", async () => {
  const db = repository();
  const result = await handoffBrowserCookies(input(), db);
  assert.equal(result.provider, "chatgpt-web-codex");
  assert.equal(result.usage, "native_codex_only");
  assert.equal(result.enabled, true);
  assert.equal(db.rows.length, 1);
  assert.equal(db.rows[0].providerSpecificData.browserSyncCredential, "enc:v1:test-sealed-credential");
  assert.equal("storageState" in db.rows[0].providerSpecificData, false);
  assert.equal(JSON.parse(db.rows[0].apiKey).version, 2);
  assert.deepEqual(JSON.parse(db.rows[0].apiKey).storageState, state());
  assert.equal(JSON.stringify(result).includes("test-only-session"), false);
});

test("repeated and concurrent refreshes upsert the same owned connection", async () => {
  const db = repository();
  const results = await Promise.all(Array.from({ length: 5 }, () => handoffBrowserCookies(input(), db)));
  assert.equal(db.rows.length, 1);
  assert.equal(db.writes.length, 1);
  assert.ok(results.every(result => result.connection_id === results[0].connection_id));
  await handoffBrowserCookies(input("test-renewed-session"), db);
  assert.equal(db.rows.length, 1);
  assert.equal(db.writes.length, 2);
});

test("ownership markers protect unrelated manual connections and disconnect clears only this producer", async () => {
  const db = repository([{ id: "manual", provider: "chatgpt-web-codex", isActive: true, apiKey: "manual-secret", providerSpecificData: {} }]);
  const result = await handoffBrowserCookies(input(), db);
  const disconnected = await handoffBrowserCookies({ provider: "chatgpt-web", account_id: "a".repeat(24), action: "disconnect" }, db);
  assert.equal(disconnected.connection_id, result.connection_id);
  assert.equal(db.rows[0].apiKey, "manual-secret");
  assert.equal(db.rows[0].isActive, true);
  assert.equal(db.rows[1].apiKey, null);
  assert.equal(db.rows[1].isActive, false);
  assert.equal("browserSyncCredential" in db.rows[1].providerSpecificData, false);
});

test("expiration disables the owned connection; valid renewal restores it without bypassing restrictions", async () => {
  const db = repository();
  await handoffBrowserCookies(input(), db);
  await handoffBrowserCookies({ provider: "chatgpt-web", account_id: "a".repeat(24), action: "expired" }, db);
  assert.equal(db.rows[0].isActive, false);
  assert.equal(db.rows[0].testStatus, "expired");
  await handoffBrowserCookies(input("renewed"), db);
  assert.equal(db.rows[0].isActive, true);
  assert.equal(db.rows[0].testStatus, "unknown");
  db.rows[0].testStatus = "banned";
  const before = db.writes.length;
  await assert.rejects(handoffBrowserCookies(input("restricted-renewal"), db), (error: unknown) => error instanceof BrowserCookieHandoffError && error.status === 409);
  assert.equal(db.writes.length, before);
  assert.equal(db.rows[0].testStatus, "banned");
});

test("a manual disabled connection remains disabled on refresh", async () => {
  const db = repository();
  await handoffBrowserCookies(input(), db);
  db.rows[0].isActive = false;
  const refreshed = await handoffBrowserCookies(input("renewed"), db);
  assert.equal(refreshed.enabled, false);
  assert.equal(db.rows[0].isActive, false);
});

test("Qwen browser credentials use the existing provider normalizer", async () => {
  const db = repository();
  const result = await handoffBrowserCookies({ provider: "qwen-browser", account_id: "b".repeat(24), user_agent: "test-browser",
    storage_state: { cookies: [{ name: "session", value: "test-cookie", domain: ".qwen.ai", path: "/", expires: -1 }],
      origins: [{ origin: "https://chat.qwen.ai", localStorage: [{ name: "token", value: "test-qwen-token" }] }] } }, db);
  assert.equal(result.provider, "qwen-browser");
  assert.equal(result.usage, "chat_completions");
  assert.equal(db.rows[0].apiKey, "test-qwen-token");
});

test("malformed, unrelated and expired credentials cannot create a connection", async () => {
  for (const payload of [null, { ...input(), account_id: "../escape" }, { ...input(), surprise: "key" },
    { ...input(), storage_state: { ...state(), cookies: [{ ...state().cookies[0], domain: ".evil.example" }] } },
    { ...input(), storage_state: { cookies: [], origins: [] } },
    { ...input(), storage_state: { ...state(), cookies: [{ ...state().cookies[0], expires: 1 }] } }]) {
    const db = repository();
    await assert.rejects(handoffBrowserCookies(payload, db));
    assert.equal(db.rows.length, 0);
  }
});

test("route requires both internal auth and trusted loopback locality, rejecting browser Origins", async () => {
  for (const headers of [ {}, { "x-omniroute-internal-service-token": "wrong", [AUTHZ_HEADER_PEER_LOCALITY]: "loopback" },
    { "x-omniroute-internal-service-token": process.env.OMNIROUTE_INTERNAL_SERVICE_TOKEN!, [AUTHZ_HEADER_PEER_LOCALITY]: "remote" },
    { "x-omniroute-internal-service-token": process.env.OMNIROUTE_INTERNAL_SERVICE_TOKEN!, [AUTHZ_HEADER_PEER_LOCALITY]: "loopback", Origin: "http://127.0.0.1:20128" } ]) {
    const response = await POST(new Request("http://127.0.0.1/api/kratos/browser-cookies", { method: "POST", headers, body: JSON.stringify(input()) }));
    assert.equal(response.status, 403);
  }
});

test("actual route stores credentials encrypted in the isolated service database and returns metadata only", async () => {
  const response = await POST(new Request("http://127.0.0.1/api/kratos/browser-cookies", { method: "POST", body: JSON.stringify(input()),
    headers: { "content-type": "application/json", "x-omniroute-internal-service-token": process.env.OMNIROUTE_INTERNAL_SERVICE_TOKEN!, [AUTHZ_HEADER_PEER_LOCALITY]: "loopback" } }));
  assert.equal(response.status, 200);
  const result = await response.json();
  const { getDbInstance } = await import("../../src/lib/db/core.ts");
  const raw = getDbInstance().prepare("SELECT api_key, provider_specific_data FROM provider_connections WHERE id=?").get(result.connection_id) as Row;
  assert.ok(raw.api_key.startsWith("enc:v1:"));
  assert.equal(JSON.stringify(raw).includes("test-only-session"), false);
  const { getProviderConnectionById } = await import("../../src/lib/db/providers.ts");
  const decoded = await getProviderConnectionById(result.connection_id);
  assert.deepEqual(JSON.parse(decoded!.apiKey as string).storageState, state());
  assert.equal(result.usage, "native_codex_only");
  const { sanitizeProviderSpecificDataForResponse } = await import("../../src/lib/providers/requestDefaults.ts");
  const publicMetadata = sanitizeProviderSpecificDataForResponse(decoded!.providerSpecificData)!;
  assert.equal("storageState" in publicMetadata, false);
  assert.equal("browserSyncCredential" in publicMetadata, false);
  assert.equal(publicMetadata.browserSyncProfile, "kratos-extension:" + "a".repeat(24));
  assert.equal(JSON.stringify(publicMetadata).includes("test-only-session"), false);
  const { sealBrowserSyncCredential } = await import("../../src/lib/db/encryption.ts");
  const { updateProviderConnection } = await import("../../src/lib/db/providers.ts");
  const metadata = JSON.parse(raw.provider_specific_data);
  const models = [{ id: "observed-model", name: "Previously observed" }];
  await updateProviderConnection(result.connection_id, { providerSpecificData: {
    ...metadata, browserSyncCredential: sealBrowserSyncCredential({ storageState: state(), browserModels: models, browserModelsObservedAt: "saved-observation" }),
  } });
  await handoffBrowserCookies(input("new-test-session"));
  const renewed = await getProviderConnectionById(result.connection_id);
  assert.deepEqual(renewed!.providerSpecificData.browserModels, models);
  assert.equal(renewed!.providerSpecificData.browserModelsObservedAt, "saved-observation");
  getDbInstance().close();
});
