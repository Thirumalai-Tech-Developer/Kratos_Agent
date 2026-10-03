// #7859: adding a token to "Gemini Web (Free)" always failed the connection test with
// "Redirect blocked for GET https://gemini.google.com/app (302)". Root cause:
// validateGeminiWebProvider() probes https://gemini.google.com/app via validationRead(),
// which uses the `validationRead` safeOutboundFetch preset (allowRedirect: false). Gemini
// Web responds with a 302 to a public host (e.g. accounts.google.com) for EVERY session —
// valid or not — so safeOutboundFetch always throws SafeOutboundFetchError with code
// REDIRECT_BLOCKED *before* the "200/302 = valid" status check the function's own comment
// describes ever runs. The throw fell through to the generic catch → toValidationErrorResult(),
// which always returned `valid: false`, making the provider permanently unusable.
//
// Fix: catch REDIRECT_BLOCKED explicitly and treat a redirect to a PUBLIC host as success
// (the session probe reached Gemini and got redirected onward — that is what a valid
// session looks like). A redirect to a PRIVATE/internal host must still be rejected — that
// would be a genuine SSRF signal, not a valid Gemini session.
import test from "node:test";
import assert from "node:assert/strict";

const { validateGeminiWebProvider } =
  await import("../../src/lib/providers/validation/webProvidersB.ts");

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

// #9407 refined this contract: a redirect to accounts.google.com/ServiceLogin is
// specifically an EXPIRED session (valid:false with re-paste guidance), while other
// public accounts.google.com paths remain valid-with-warning. The original #7859
// regression (public redirect must not fall through to the generic catch → invalid)
// is still covered — by the non-ServiceLogin variant below.
test("gemini-web validator: 302 redirect to ServiceLogin → expired session (#9407)", async () => {
  globalThis.fetch = async (url) => {
    const target = String(url);
    if (target.includes("gemini.google.com/app")) {
      return new Response(null, {
        status: 302,
        headers: { location: "https://accounts.google.com/ServiceLogin" },
      });
    }
    throw new Error(`unexpected fetch: ${target}`);
  };

  const result = await validateGeminiWebProvider({
    apiKey: "__Secure-1PSID=eyJvalidsession",
  });

  assert.equal(result.valid, false);
  assert.match(result.error || "", /Session expired/i);
});

test("gemini-web validator: 302 redirect to a PUBLIC host → valid (regression #7859)", async () => {
  globalThis.fetch = async (url) => {
    const target = String(url);
    if (target.includes("gemini.google.com/app")) {
      return new Response(null, {
        status: 302,
        headers: { location: "https://accounts.google.com/signin/continue" },
      });
    }
    throw new Error(`unexpected fetch: ${target}`);
  };

  const result = await validateGeminiWebProvider({
    apiKey: "__Secure-1PSID=eyJvalidsession",
  });

  assert.equal(result.valid, true);
  assert.equal(result.error, null);
});

test("gemini-web validator: 302 redirect to a PRIVATE host stays invalid (no SSRF)", async () => {
  globalThis.fetch = async (url) => {
    const target = String(url);
    if (target.includes("gemini.google.com/app")) {
      return new Response(null, {
        status: 302,
        headers: { location: "http://169.254.169.254/latest/meta-data/" },
      });
    }
    throw new Error(`unexpected fetch: ${target}`);
  };

  const result = await validateGeminiWebProvider({
    apiKey: "__Secure-1PSID=eyJvalidsession",
  });

  assert.equal(result.valid, false);
  assert.equal((result as { securityBlocked?: boolean }).securityBlocked, true);
});

test("gemini-web validator: 200 response with large headers (>16KB) succeeds without header overflow", async () => {
  globalThis.fetch = async (url) => {
    const target = String(url);
    if (target.includes("gemini.google.com/app")) {
      const headers = new Headers();
      headers.set("content-type", "text/html; charset=utf-8");
      // Simulate Google's massive ~20KB reporting-endpoints header payload
      headers.set(
        "reporting-endpoints",
        'default="/_/BardChatUi/web-reports?context=' + "x".repeat(20000) + '"'
      );
      return new Response("<!doctype html><html><body>Gemini</body></html>", {
        status: 200,
        headers,
      });
    }
    throw new Error(`unexpected fetch: ${target}`);
  };

  const result = await validateGeminiWebProvider({
    apiKey: "__Secure-1PSID=eyJvalidsession",
  });

  assert.equal(result.valid, true);
  assert.equal(result.error, null);
});

test("upstream maxHeaderSize defaults to at least 128KB", async () => {
  const { DEFAULT_MAX_HEADER_SIZE, getUpstreamMaxHeaderSize } =
    await import("../../open-sse/utils/proxyDispatcher.ts");
  assert.ok(DEFAULT_MAX_HEADER_SIZE >= 131072);
  assert.equal(getUpstreamMaxHeaderSize({}), DEFAULT_MAX_HEADER_SIZE);
  assert.equal(getUpstreamMaxHeaderSize({ OMNIROUTE_MAX_HEADER_SIZE: "262144" }), 262144);
});

test("toValidationErrorResult extracts inner cause on fetch failed", async () => {
  const { toValidationErrorResult } =
    await import("../../src/lib/providers/validation/transport.ts");
  const cause = new Error("Headers Overflow Error");
  (cause as { code?: string }).code = "UND_ERR_HEADERS_OVERFLOW";
  const err = new Error("fetch failed");
  (err as { cause?: unknown }).cause = cause;

  const res = toValidationErrorResult(err);
  assert.equal(res.valid, false);
  assert.equal(res.error, "fetch failed: Headers Overflow Error (UND_ERR_HEADERS_OVERFLOW)");
});
