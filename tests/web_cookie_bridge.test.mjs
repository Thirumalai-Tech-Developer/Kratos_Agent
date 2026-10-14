import assert from "node:assert/strict";
import test from "node:test";
import {
  browserModelMetadata,
  sessionIdentity,
} from "../src/kratos_agent/brain/web_cookie_bridge.mjs";

test("browser metadata exposes adjustable effort only when the executor declares it", () => {
  const models = browserModelMetadata("deepseek-web", [
    { id: "thinking", name: "Thinking", supportsReasoning: true },
  ]);
  assert.equal(models[0].supports_reasoning, true);
  assert.deepEqual(models[0].effort_tiers, []);
  assert.equal(models[0].access_verified, false);
  assert.equal(
    browserModelMetadata("gemini-web", [{id:'gemini-test',name:'Test'}])[0].id,
    "gemini-web/gemini-test",
  );
});

test("Dola identity ignores analytics cookie renewal and remains account-specific", () => {
  const snapshot = (value, analytics) => ({
    storage_state: {
      cookies: [
        { name: "sessionid", value },
        { name: "analytics", value: analytics },
      ],
    },
  });
  const credentials = { data: {}, apiKey: "credential-envelope" };
  assert.equal(
    sessionIdentity("doubao-web", credentials, snapshot("signed-in", "one")),
    sessionIdentity("doubao-web", credentials, snapshot("signed-in", "two")),
  );
  assert.notEqual(
    sessionIdentity(
      "doubao-web",
      credentials,
      snapshot("other-account", "one"),
    ),
    sessionIdentity("doubao-web", credentials, snapshot("signed-in", "one")),
  );
  assert.throws(
    () =>
      sessionIdentity("gemini-web", credentials, snapshot("signed-in", "one")),
    /unavailable/,
  );
});
