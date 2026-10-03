import test from "node:test";
import assert from "node:assert/strict";
import {
  parseJsonCookiesToHeader,
  normalizeSessionCookieHeader,
  extractCookieValue,
  buildGrokCookieHeader,
} from "../../src/lib/providers/webCookieAuth.ts";
import * as sessionCredentials from "../../src/shared/providers/webSessionCredentials.ts";
const {
  hasUsableWebSessionCredential,
  buildWebSessionProviderSpecificData,
  getWebSessionCredentialRequirement,
  resolveWebSessionImportApiKey,
} = sessionCredentials as typeof sessionCredentials & {
  buildWebSessionProviderSpecificData: (
    requirement: ReturnType<typeof sessionCredentials.getWebSessionCredentialRequirement>,
    credential: string
  ) => Record<string, unknown>;
};

test("cookie object maps and storage-state exports preserve companions and equals", () => {
  const input = JSON.stringify({ cookies: { sessionKey: "session==", companion: "device=value" } });
  assert.equal(parseJsonCookiesToHeader(input), "sessionKey=session==; companion=device=value");
  assert.equal(
    normalizeSessionCookieHeader(input, "sessionKey"),
    "sessionKey=session==; companion=device=value"
  );
  assert.equal(extractCookieValue(input, "sessionKey"), "session==");
});

test("named extraction never substitutes an unrelated cookie for authentication", () => {
  assert.equal(extractCookieValue("cf_clearance=challenge", "sso"), "");
  assert.equal(extractCookieValue('[{"name":"other","value":"value"}]', "sso"), "");
  assert.equal(extractCookieValue("sso=value==", "sso"), "value==");
});

test("Grok browser JSON retains its write and clearance companions", () => {
  const input = JSON.stringify({
    cookies: [
      { name: "sso", value: "session==", domain: ".grok.com" },
      { name: "sso-rw", value: "write==", domain: ".grok.com" },
      { name: "cf_clearance", value: "clearance", domain: ".grok.com" },
      { name: "__cf_bm", value: "bot", domain: ".grok.com" },
      { name: "sso", value: "wrong-domain", domain: "grok.com.attacker.test" },
    ],
  });
  assert.equal(
    buildGrokCookieHeader(input),
    "sso=session==; sso-rw=write==; cf_clearance=clearance; __cf_bm=bot"
  );
});

test("provider domain filtering discards unrelated and expired browser cookies", () => {
  const input = JSON.stringify([
    { name: "sessionKey", value: "active", domain: ".claude.ai", expirationDate: 4_000_000_000 },
    { name: "companion", value: "keep", domain: "claude.ai", expires: -1 },
    { name: "sessionKey", value: "expired", domain: ".claude.ai", expires: 1 },
    { name: "sessionKey", value: "attacker", domain: "claude.ai.attacker.test" },
    { name: "sessionKey", value: "unrelated", domain: ".example.test" },
  ]);
  assert.equal(
    normalizeSessionCookieHeader(input, "sessionKey", { domains: ["claude.ai"] }),
    "sessionKey=active; companion=keep"
  );
});

test("browser JSON cannot smuggle cookie delimiters or header line breaks", () => {
  for (const entry of [
    { name: "sessionKey; other", value: "x" },
    { name: "sessionKey", value: "x; other=y" },
    { name: "sessionKey", value: "x\r\nAuthorization: secret" },
  ])
    assert.throws(() => parseJsonCookiesToHeader(JSON.stringify([entry])), /Invalid cookie JSON/);
  assert.throws(
    () => normalizeSessionCookieHeader("sessionKey=x\r\nother=y", "sessionKey"),
    /Invalid cookie header/
  );
  assert.throws(
    () => normalizeSessionCookieHeader("[not JSON", "sessionKey"),
    /Invalid cookie JSON/
  );
});

test("optional web metadata is never sufficient authentication", () => {
  for (const [provider, data] of [
    ["doubao-web", { ttwid: "device", device_id: "123", msToken: "challenge" }],
    ["notion-web", { space_id: "workspace", notion_browser_id: "browser" }],
    ["gemini-web", { "__Secure-1PSIDTS": "timestamp" }],
    ["copilot-m365-web", { chathubPath: "/chat", userTenant: "tenant" }],
    ["promptql", { projectId: "project", cookie: "other=value" }],
    ["maxai", { userId: "user", deviceId: "device" }],
    ["uc", { sid: "session", uid: "user" }],
  ] as const)
    assert.equal(hasUsableWebSessionCredential(provider, data), false, provider);
});

test("empty named cookies and unrelated Cookie headers do not pass the auth contract", () => {
  for (const provider of ["perplexity-web", "grok-web", "claude-web", "doubao-web"]) {
    assert.equal(
      hasUsableWebSessionCredential(provider, { cookie: "unrelated=value" }),
      false,
      provider
    );
  }
  assert.equal(hasUsableWebSessionCredential("claude-web", { cookie: "sessionKey=" }), false);
  assert.equal(
    hasUsableWebSessionCredential("claude-web", { cookie: "sessionKey=valid; device=companion" }),
    true
  );
});

test("bulk cookie import stores real named values rather than copying the full header to all keys", () => {
  const requirement = getWebSessionCredentialRequirement("doubao-web");
  const credential = "sessionid=session==; ttwid=device; s_v_web_id=fp; other=keep";
  const data = buildWebSessionProviderSpecificData(requirement, credential);
  assert.deepEqual(data, {
    cookie: credential,
    sessionid: "session==",
    ttwid: "device",
    s_v_web_id: "fp",
  });
  assert.equal(hasUsableWebSessionCredential("doubao-web", data), true);
});

test("bulk object-cookie import normalizes while preserving all legitimate companion cookies", () => {
  const requirement = getWebSessionCredentialRequirement("claude-web");
  assert.deepEqual(
    buildWebSessionProviderSpecificData(
      requirement,
      JSON.stringify({
        cookies: {
          sessionKey: "session==",
          device_id: "device",
          other: "keep",
        },
      })
    ),
    { cookie: "sessionKey=session==; device_id=device; other=keep", sessionKey: "session==" }
  );
});

test("bulk token import never promotes optional metadata or empty wrapped token to auth", () => {
  const requirement = getWebSessionCredentialRequirement("copilot-m365-web");
  const data = buildWebSessionProviderSpecificData(
    requirement,
    JSON.stringify({ access_token: "token==", chathubPath: "/chat", userTenant: "tenant" })
  );
  assert.equal(data.token, "token==");
  assert.equal(data.chathubPath, "/chat");
  assert.equal(data.userTenant, "tenant");
  const empty = buildWebSessionProviderSpecificData(
    requirement,
    '{"access_token":"","chathubPath":"/chat"}'
  );
  assert.equal(hasUsableWebSessionCredential("copilot-m365-web", empty), false);
  for (const credential of ["chathubPath=/chat", "access_token=", "unrelated=value"]) {
    const data = buildWebSessionProviderSpecificData(requirement, credential);
    assert.equal(hasUsableWebSessionCredential("copilot-m365-web", data), false, credential);
    assert.equal(resolveWebSessionImportApiKey(requirement, credential, data), null);
  }
});

test("Qwen import keeps its real bearer token and complete browser companions separately", () => {
  const requirement = getWebSessionCredentialRequirement("qwen-browser");
  const header = "token=bearer==; browser=device; csrf=nonce";
  const fromHeader = buildWebSessionProviderSpecificData(requirement, header);
  assert.equal(fromHeader.token, "bearer==");
  assert.equal(fromHeader.cookie, header);
  assert.equal(resolveWebSessionImportApiKey(requirement, header, fromHeader), "bearer==");
  const fromExport = buildWebSessionProviderSpecificData(
    requirement,
    JSON.stringify({
      cookies: [
        { name: "token", value: "bearer==", domain: ".qwen.ai" },
        { name: "browser", value: "device", domain: ".qwen.ai" },
        { name: "token", value: "foreign", domain: ".example.test" },
      ],
    })
  );
  assert.equal(fromExport.token, "bearer==");
  assert.equal(fromExport.cookie, "token=bearer==; browser=device");
  assert.equal(hasUsableWebSessionCredential("qwen-browser", fromExport), true);
  const companionOnly = buildWebSessionProviderSpecificData(
    requirement,
    "browser=device; csrf=nonce"
  );
  assert.equal(hasUsableWebSessionCredential("qwen-browser", companionOnly), false);
});

test("expired JWT auth and expired browser-export auth cannot pass the import contract", () => {
  const expired = `${Buffer.from('{"alg":"none"}').toString("base64url")}.${Buffer.from('{"exp":1}').toString("base64url")}.signature`;
  assert.equal(hasUsableWebSessionCredential("zai-web", { token: expired }), false);
  const data = buildWebSessionProviderSpecificData(
    getWebSessionCredentialRequirement("claude-web"),
    '[{"name":"sessionKey","value":"old","domain":".claude.ai","expires":1}]'
  );
  assert.equal(hasUsableWebSessionCredential("claude-web", data), false);
});

test("composite Muse and Inner.ai imports preserve separate auxiliary credentials", () => {
  const muse = "ecto_1_sess=session; ecto1:ws-auth";
  assert.equal(normalizeSessionCookieHeader(muse, "ecto_1_sess"), muse);
  const inner = buildWebSessionProviderSpecificData(
    getWebSessionCredentialRequirement("inner-ai"),
    "token=opaque-token user@example.test"
  );
  assert.equal(inner.token, "opaque-token");
  assert.equal(inner.email, "user@example.test");
  assert.equal(inner.cookie, "opaque-token user@example.test");
  assert.equal(hasUsableWebSessionCredential("inner-ai", inner), true);
});

test("token-kind browser exports keep companions and use the configured auth-cookie name", () => {
  const data = buildWebSessionProviderSpecificData(
    getWebSessionCredentialRequirement("deepseek-web"),
    JSON.stringify({
      cookies: [
        { name: "user-token", value: "bearer==", domain: ".deepseek.com" },
        { name: "device", value: "keep", domain: ".deepseek.com" },
        { name: "user-token", value: "foreign", domain: ".example.test" },
      ],
    })
  );
  assert.equal(data.token, "bearer==");
  assert.equal(data.cookie, "user-token=bearer==; device=keep");
  assert.equal(hasUsableWebSessionCredential("deepseek-web", data), true);
});

test("Copilot HAR imports use only authenticated requests on the provider domain", () => {
  const requirement = getWebSessionCredentialRequirement("copilot-web");
  const har = (url: string) =>
    JSON.stringify({
      log: {
        entries: [
          {
            request: {
              url,
              headers: [
                { name: "Authorization", value: "Bearer access-token" },
                { name: "Cookie", value: "device=companion" },
              ],
            },
          },
        ],
      },
    });
  const data = buildWebSessionProviderSpecificData(
    requirement,
    har("https://copilot.microsoft.com/c/api/chat")
  );
  assert.equal(data.access_token, "access-token");
  assert.equal(data.cookie, "device=companion");
  assert.equal(resolveWebSessionImportApiKey(requirement, "", data), "access-token");
  assert.equal(
    hasUsableWebSessionCredential(
      "copilot-web",
      buildWebSessionProviderSpecificData(
        requirement,
        har("https://copilot.microsoft.com.attacker.test/chat")
      )
    ),
    false
  );
});
