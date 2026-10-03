import crypto from "node:crypto";
import { z } from "zod";

export const EXTENDED_KINDS = ["email", "pagerduty", "teams"] as const;
export type ExtendedKind = (typeof EXTENDED_KINDS)[number];

export function isExtendedKind(kind: string): kind is ExtendedKind {
  return EXTENDED_KINDS.some((value) => value === kind);
}

const emailConfig = z.object({
  apiKey: z.string().trim().min(1).max(500),
  from: z.string().trim().min(1).max(320),
  to: z.string().trim().email(),
});
const pagerDutyConfig = z.object({ routingKey: z.string().trim().min(1).max(500) });

export function validateExtendedMetadata(kind: ExtendedKind, metadata: Record<string, string>) {
  if (kind === "email") return emailConfig.safeParse(metadata).success;
  if (kind === "pagerduty") return pagerDutyConfig.safeParse(metadata).success;
  return true;
}

/** A single adapter serves both actual events and the configuration test button. */
export function buildExtendedDelivery(
  kind: ExtendedKind,
  url: string,
  metadata: Record<string, string>,
  event: string,
  data: Record<string, unknown>,
  timestamp: string
): { url: string; headers: Record<string, string>; body: Record<string, unknown> } {
  const summary = `Kratos Studio: ${event}`;
  const details = JSON.stringify({ event, timestamp, data }, null, 2);
  const deliveryId = crypto.createHash("sha256").update(details).digest("hex");
  if (kind === "email") {
    const config = emailConfig.parse(metadata);
    return {
      url: "https://api.resend.com/emails",
      headers: { Authorization: `Bearer ${config.apiKey}`, "Idempotency-Key": deliveryId },
      body: { from: config.from, to: [config.to], subject: summary, text: details },
    };
  }
  if (kind === "pagerduty") {
    const config = pagerDutyConfig.parse(metadata);
    return {
      url: "https://events.pagerduty.com/v2/enqueue",
      headers: {},
      body: {
        routing_key: config.routingKey,
        event_action: "trigger",
        dedup_key: deliveryId,
        payload: { summary, source: "kratos-studio", severity: "warning", timestamp, custom_details: data },
      },
    };
  }
  return {
    url,
    headers: {},
    body: {
      type: "message",
      attachments: [{
        contentType: "application/vnd.microsoft.card.adaptive",
        contentUrl: null,
        content: {
          $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
          type: "AdaptiveCard",
          version: "1.2",
          body: [{ type: "TextBlock", text: summary, weight: "Bolder", wrap: true },
                 { type: "TextBlock", text: details.slice(0, 12000), wrap: true }],
        },
      }],
    },
  };
}

export function redactExtendedPayload(body: Record<string, unknown>): Record<string, unknown> {
  return "routing_key" in body ? { ...body, routing_key: "[redacted]" } : body;
}
