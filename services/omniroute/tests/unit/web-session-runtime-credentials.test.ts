import test from "node:test";
import assert from "node:assert/strict";
import * as credentials from "../../src/shared/providers/webSessionCredentials.ts";

test("bulk imported browser cookies reach executors that read apiKey", () => {
  const resolve = (
    credentials as unknown as {
      resolveWebSessionRuntimeApiKey: (
        provider: string,
        apiKey: string | null,
        data: Record<string, unknown>
      ) => string | null;
    }
  ).resolveWebSessionRuntimeApiKey;
  assert.equal(typeof resolve, "function");
  for (const [provider, cookie] of [
    ["grok-web", "sso=session; sso-rw=write; cf_clearance=clearance"],
    ["perplexity-web", "__Secure-next-auth.session-token=session; companion=device"],
    ["claude-web", "sessionKey=session; companion=device"],
    ["t3-web", "convex-session-id=session; wos-session=login"],
    ["v0-vercel-web", "user_session=session; v0_browser_id=device"],
  ])
    assert.equal(resolve(provider, null, { cookie }), cookie, provider);
  assert.equal(resolve("grok-web", "explicit", { cookie: "sso=other" }), "explicit");
  assert.equal(resolve("grok-web", null, { cookie: "cf_clearance=challenge" }), null);
  assert.equal(resolve("openai", null, { cookie: "sso=session" }), null);
  assert.equal(resolve("deepseek-web", null, { cookie: "sso=session" }), null);
});

test("Meta browser import preserves its separate WebSocket authorization", () => {
  const requirement = credentials.getWebSessionCredentialRequirement("muse-spark-web");
  const data = credentials.buildWebSessionProviderSpecificData(
    requirement,
    JSON.stringify({
      cookie: "ecto_1_sess=session; companion=device",
      authorization: "ecto1:ws-token",
    })
  );
  assert.equal(data.cookie, "ecto_1_sess=session; companion=device");
  assert.equal(data.authorization, "ecto1:ws-token");
  assert.equal(credentials.hasUsableWebSessionCredential("muse-spark-web", data), true);
});

test("Grok browser import keeps the user agent bound to its clearance cookie", () => {
  const data = credentials.buildWebSessionProviderSpecificData(
    credentials.getWebSessionCredentialRequirement("grok-web"),
    JSON.stringify({
      cookie: "sso=session; sso-rw=write; cf_clearance=clear",
      userAgent: "Mozilla/5.0 (Windows NT 10.0) Chrome/149.0.0.0 Safari/537.36",
    })
  );
  assert.equal(data.userAgent, "Mozilla/5.0 (Windows NT 10.0) Chrome/149.0.0.0 Safari/537.36");
});
