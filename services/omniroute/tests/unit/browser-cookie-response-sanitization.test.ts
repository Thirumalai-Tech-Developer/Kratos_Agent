import assert from "node:assert/strict";
import test from "node:test";
import { sanitizeProviderSpecificDataForResponse } from "../../src/lib/providers/requestDefaults.ts";

test("hydrated browser credentials and sealed payloads stay out of provider responses", () => {
  const secrets = Object.fromEntries([
    "browserSyncCredential", "storageState", "storage_state", "cookies", "origins", "localStorage", "sessionStorage",
    "cookie", "token", "userToken", "access_token", "refresh_token", "id_token", "authorization", "sessionKey",
    "sessionid", "session", "sessionCookie", "userSession", "user_session", "user_session_token", "accessToken",
    "session-token", "next-auth.session-token", "__Secure-next-auth.session-token", "__Secure-authjs.session-token",
    "__Secure-1PSID", "__Secure-1PSIDTS", "__Secure-1PSIDCC", "sso", "sso-rw", "kimi-auth", "ecto_1_sess", "abra_sess",
    "token_v2", "cf_clearance",
  ].map(name => [name, `private-value-${name}`]));
  const status = { browserSyncProfile: "kratos-extension:owned", kratosCookieAccount: "owned",
    browserSyncedAt: "2026-10-13", cookieExpiresAt: "2026-10-14", browserModels: [{ id: "observed", name: "Observed" }],
    requestDefaults: { reasoningEffort: "high" }, tag: "primary", userAgent: "original browser" };
  const stored = Object.freeze({ ...secrets, ...status });
  assert.deepEqual(sanitizeProviderSpecificDataForResponse(stored), status);
  assert.equal(Object.keys(stored).length, Object.keys(secrets).length + Object.keys(status).length);
});

test("partial edit response data cannot replace or erase stored browser credentials", () => {
  const stored = { browserSyncCredential: "enc:v1:private", storageState: { cookies: [{ value: "private" }], origins: [] },
    token: "private-token", browserSyncProfile: "kratos-extension:owned", cookieExpiresAt: "saved-expiry", tag: "primary" };
  const incoming = { ...sanitizeProviderSpecificDataForResponse(stored), tag: "edited" };
  const merged = { ...stored, ...incoming };
  assert.equal(merged.browserSyncCredential, stored.browserSyncCredential);
  assert.equal(merged.storageState, stored.storageState);
  assert.equal(merged.token, stored.token);
  assert.equal(merged.tag, "edited");
});

test("chunked and renamed browser session cookies are sanitized while expiry metadata remains", () => {
  assert.deepEqual(sanitizeProviderSpecificDataForResponse({
    "__Secure-next-auth.session-token.0": "private-first-half",
    "__Secure-next-auth.session-token.1": "private-second-half",
    "authjs.session-token": "private-session", "__Host-authjs.session-token.0": "private-fragment",
    cookieExpiresAt: "saved-expiry", browserSyncedAt: "saved-sync",
  }), { cookieExpiresAt: "saved-expiry", browserSyncedAt: "saved-sync" });
});
