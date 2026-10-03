import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { kratosTarget, proxyKratos } from "../../src/lib/kratos/proxy.ts";
import { isLocalOnlyPath } from "../../src/server/authz/routeGuard.ts";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; delete process.env.KRATOS_INTERNAL_TOKEN; delete process.env.KRATOS_GATEWAY_URL; });

test("agent execution and workspace proxy are local-only", () => {
  assert.equal(isLocalOnlyPath("/api/kratos/chat"), true);
  assert.equal(isLocalOnlyPath("/dashboard/kratos/workspace/index.html"), true);
});
test("proxy targets are fixed loopback and reject traversal", () => {
  assert.equal(kratosTarget(["chat"], "api").pathname, "/api/chat");
  for (const path of [["..", "secret"], ["http://evil"], ["a\\b"]]) assert.throws(() => kratosTarget(path, "api"));
});
test("missing service configuration fails visibly", async () => {
  const response = await proxyKratos(new Request("http://localhost/api/kratos/health"), ["health"], "api");
  assert.equal(response.status, 503);
  assert.ok(!(await response.text()).includes("at /"));
});
test("streaming body is passed through and credentials never reach the browser", async () => {
  process.env.KRATOS_INTERNAL_TOKEN = "private-token";
  globalThis.fetch = async (_url, options) => {
    assert.equal(new Headers(options?.headers).get("X-Kratos-Internal-Token"), "private-token");
    assert.equal(new Headers(options?.headers).get("cookie"), null);
    return new Response("data: {\"type\":\"done\"}\n\n", { headers: { "Content-Type": "text/event-stream", "X-Kratos-Internal-Token": "private-token" } });
  };
  const response = await proxyKratos(new Request("http://localhost/api/kratos/chat", { method: "POST", body: "{}", headers: { Cookie: "dashboard-session" } }), ["chat"], "api");
  assert.equal(response.headers.get("X-Kratos-Internal-Token"), null);
  assert.match(await response.text(), /done/);
});
test("cross-origin execution is denied", async () => {
  process.env.KRATOS_INTERNAL_TOKEN = "private-token";
  const response = await proxyKratos(new Request("http://localhost/api/kratos/chat", { method: "POST", headers: { Origin: "https://example.com" } }), ["chat"], "api");
  assert.equal(response.status, 403);
});
test("browser-facing Studio origin works when Next uses an internal URL", async () => {
  process.env.KRATOS_INTERNAL_TOKEN = "private-token";
  process.env.KRATOS_GATEWAY_URL = "http://127.0.0.1:20228";
  globalThis.fetch = async () => new Response("workspace asset");
  const request = new Request("http://localhost:3000/dashboard/kratos/workspace/assets/app.js", {
    headers: { Origin: "http://127.0.0.1:20228" },
  });
  const response = await proxyKratos(request, ["assets", "app.js"], "workspace");
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "workspace asset");
});

import { after } from "node:test";
after(async () => { (await import("../../src/lib/db/core")).resetDbInstance(); });
