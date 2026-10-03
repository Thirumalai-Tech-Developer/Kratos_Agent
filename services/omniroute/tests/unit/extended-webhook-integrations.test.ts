import { test, after } from "node:test";
import assert from "node:assert/strict";
import { buildExtendedDelivery, redactExtendedPayload, validateExtendedMetadata } from "../../src/lib/webhooks/integrations/extended";
import { deliverRaw } from "../../src/lib/webhookDispatcher";

const timestamp = "2026-09-29T00:00:00Z";
test("email uses Resend with stable idempotency and no credentials in payload", () => {
  const args = ["email", "https://ignored.example", { apiKey: "test-secret", from: "alerts@example.com", to: "user@example.com" }, "test.ping", { message: "hello" }, timestamp] as const;
  const delivery = buildExtendedDelivery(...args);
  assert.equal(delivery.url, "https://api.resend.com/emails");
  assert.equal(delivery.headers.Authorization, "Bearer test-secret");
  assert.deepEqual(delivery.body.to, ["user@example.com"]);
  assert.equal(delivery.headers["Idempotency-Key"], buildExtendedDelivery(...args).headers["Idempotency-Key"]);
  assert.ok(!JSON.stringify(delivery.body).includes("test-secret"));
});

test("PagerDuty uses Events v2 and redacts routing key in diagnostics", () => {
  const delivery = buildExtendedDelivery("pagerduty", "", { routingKey: "private-key" }, "test.ping", {}, timestamp);
  assert.equal(delivery.body.event_action, "trigger");
  assert.equal(delivery.body.routing_key, "private-key");
  assert.equal(redactExtendedPayload(delivery.body).routing_key, "[redacted]");
  assert.equal(delivery.url, "https://events.pagerduty.com/v2/enqueue");
});

test("Teams builds a Workflows adaptive card", () => {
  const delivery = buildExtendedDelivery("teams", "https://example.com/workflow", {}, "test.ping", { message: "hello" }, timestamp);
  assert.equal(delivery.body.type, "message");
  const attachment = (delivery.body.attachments as Array<Record<string, unknown>>)[0];
  assert.equal(attachment.contentType, "application/vnd.microsoft.card.adaptive");
  assert.ok(JSON.stringify(attachment).includes("hello"));
});

test("incomplete email and pagerduty configs fail validation", () => {
  assert.equal(validateExtendedMetadata("email", { apiKey: "key" }), false);
  assert.equal(validateExtendedMetadata("pagerduty", {}), false);
});

test("delivery sends adapter headers and blocks redirects", async (t) => {
  const calls: RequestInit[] = [];
  t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
    calls.push(init);
    return new Response("accepted", { status: 202 });
  });
  const result = await deliverRaw("https://api.resend.com/emails", { text: "hello" }, { Authorization: "Bearer test" });
  assert.equal(result.success, true);
  assert.equal(result.status, 202);
  assert.equal(calls[0].redirect, "error");
  assert.equal((calls[0].headers as Record<string, string>).Authorization, "Bearer test");
});


test("all three integrations record real dispatcher delivery outcomes", async (t) => {
  const { createWebhook, getWebhook, deleteWebhook } = await import("../../src/lib/db/webhooks");
  const { getDeliveries } = await import("../../src/lib/db/webhookDeliveries");
  const { dispatchEvent, encryptMetadata } = await import("../../src/lib/webhookDispatcher");
  const received: string[] = [];
  t.mock.method(globalThis, "fetch", async (url: string) => {
    received.push(url);
    return new Response("", { status: url.includes("pagerduty") ? 400 : 202 });
  });
  const definitions = [
    { kind: "email", url: "https://api.resend.com/emails", metadata: { apiKey: "test", from: "sender@example.com", to: "to@example.com" } },
    { kind: "pagerduty", url: "https://events.pagerduty.com/v2/enqueue", metadata: { routingKey: "test" } },
    { kind: "teams", url: "https://example.com/teams", metadata: {} },
  ] as const;
  const hooks = definitions.map((item) => createWebhook({
    kind: item.kind, url: item.url, events: ["test.ping"], metadataEncrypted: encryptMetadata(item.metadata),
  }));
  try {
    await dispatchEvent("test.ping", { message: "test" });
    assert.equal(received.length, 3);
    for (const hook of hooks) {
      const deliveries = getDeliveries(hook.id, 10);
      assert.equal(deliveries.length, 1);
      assert.equal(deliveries[0].status, hook.kind === "pagerduty" ? "failed" : "success");
      assert.equal(getWebhook(hook.id)?.failure_count, hook.kind === "pagerduty" ? 1 : 0);
    }
  } finally {
    for (const hook of hooks) deleteWebhook(hook.id);
  }
});

after(async () => { (await import("../../src/lib/db/core")).resetDbInstance(); });
