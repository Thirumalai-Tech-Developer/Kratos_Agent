"use client";

import { SlackConfigForm, type SlackConfig } from "./integrations/SlackConfigForm";
import { TelegramConfigForm, type TelegramConfig } from "./integrations/TelegramConfigForm";
import { DiscordConfigForm, type DiscordConfig } from "./integrations/DiscordConfigForm";
import { CustomConfigForm, type CustomConfig } from "./integrations/CustomConfigForm";
import type { WebhookKind } from "../shared/IntegrationCard";

interface Step2ConfigureIntegrationProps {
  kind: WebhookKind;
  slack: SlackConfig;
  telegram: TelegramConfig;
  discord: DiscordConfig;
  custom: CustomConfig;
  extended: Record<string, string>;
  onChangeExtended: (value: Record<string, string>) => void;
  onChangeSlack: (v: SlackConfig) => void;
  onChangeTelegram: (v: TelegramConfig) => void;
  onChangeDiscord: (v: DiscordConfig) => void;
  onChangeCustom: (v: CustomConfig) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
  isEditing?: boolean;
}

export function Step2ConfigureIntegration({
  kind,
  slack,
  telegram,
  discord,
  custom,
  extended,
  onChangeExtended,
  onChangeSlack,
  onChangeTelegram,
  onChangeDiscord,
  onChangeCustom,
  t,
  isEditing,
}: Step2ConfigureIntegrationProps) {
  if (["email", "pagerduty", "teams"].includes(kind)) {
    const fields = kind === "email" ? [["from", "Sender (verified in Resend)"], ["to", "Recipient email"], ["apiKey", "Resend API key"]]
      : kind === "pagerduty" ? [["routingKey", "PagerDuty Events API v2 routing key"]]
      : [["url", "Teams Workflows webhook URL"]];
    return <div className="space-y-4">
      <p className="text-sm text-text-muted">{kind === "email" ? "Email is delivered through your Resend account."
        : kind === "teams" ? "Use a Teams workflow with the webhook trigger set to Anyone."
        : "Events trigger alerts through your PagerDuty integration."}</p>
      {isEditing && kind !== "teams" && <p className="text-sm text-text-muted">Leave a field blank to keep its saved value.</p>}
      {fields.map(([key, label]) => <label key={key} className="block space-y-1 text-sm text-text-main">
        <span>{label}</span>
        <input className="w-full rounded-lg border border-border bg-surface px-3 py-2"
          type={key === "apiKey" || key === "routingKey" ? "password" : key === "to" ? "email" : "text"}
          autoComplete="off" value={extended[key] ?? ""}
          onChange={(event) => onChangeExtended({ ...extended, [key]: event.target.value })} />
      </label>)}
    </div>;
  }
  if (kind === "slack") return <SlackConfigForm value={slack} onChange={onChangeSlack} t={t} />;
  if (kind === "telegram")
    return (
      <TelegramConfigForm
        value={telegram}
        onChange={onChangeTelegram}
        t={t}
        isEditing={isEditing}
      />
    );
  if (kind === "discord")
    return <DiscordConfigForm value={discord} onChange={onChangeDiscord} t={t} />;
  return <CustomConfigForm value={custom} onChange={onChangeCustom} t={t} isEditing={isEditing} />;
}

export type { SlackConfig, TelegramConfig, DiscordConfig, CustomConfig };
