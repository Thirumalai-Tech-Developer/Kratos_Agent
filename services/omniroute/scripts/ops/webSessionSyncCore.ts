import { createHash } from "node:crypto";
import {
  getExtractionConfig,
  type TokenExtractionConfig,
} from "../../open-sse/services/tokenExtractionConfig";
import { matchesCookieDomain } from "../../open-sse/utils/cookieDomain";
import { browserModelsSchema, type BrowserModel } from "../../open-sse/utils/browserModels";
import { decodeJwtPayloadExp } from "../../src/shared/utils/webCookieExpiry";
import {
  buildWebSessionProviderSpecificData,
  getWebSessionCredentialRequirement,
  hasUsableWebSessionCredential,
  resolveWebSessionImportApiKey,
} from "../../src/shared/providers/webSessionCredentials";

export const CONSUMER_PROVIDERS = [
  "qwen-browser",
  "doubao-web",
  "kimi-web",
  "deepseek-web",
  "claude-web",
  "gemini-web",
  "grok-web",
  "perplexity-web",
  "zai-web",
  "muse-spark-web",
  "huggingchat",
  "poe-web",
  "lmarena",
  "v0-web",
  "blackbox-web",
];

export function syncConfig(provider: string): TokenExtractionConfig | undefined {
  if (!CONSUMER_PROVIDERS.includes(provider)) return undefined;
  if (provider === "qwen-browser") {
    return {
      providerId: provider,
      displayName: "Qwen",
      loginUrl: "https://chat.qwen.ai/",
      homeUrl: "https://chat.qwen.ai",
      cookieDomain: ".qwen.ai",
      tokenSources: [
        { type: "localStorage", key: "token" },
        { type: "localStorage", key: "accessToken" },
      ],
      instructions: "Sign in normally in this browser profile.",
      pollingConfig: { pollInterval: 30000, timeout: 300000, minLoginTime: 0 },
    };
  }
  return getExtractionConfig(provider);
}

export interface SyncCookie {
  name: string;
  value: string;
  domain: string;
  path?: string;
  expires?: number;
}
export interface BrowserSnapshot {
  cookies: SyncCookie[];
  storage: Record<string, string>;
  userAgent: string;
  authorization?: string;
  models?: BrowserModel[];
}

function unwrap(value: string): string {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      for (const key of ["token", "value", "access_token", "accessToken", "userToken"]) {
        if (typeof record[key] === "string") return record[key];
      }
    }
  } catch {
    /* Opaque credentials are normal. */
  }
  return value;
}

export function normalizeSnapshot(provider: string, snapshot: BrowserSnapshot, now = Date.now()) {
  const config = syncConfig(provider);
  const requirement = getWebSessionCredentialRequirement(provider);
  if (!config || !requirement || requirement.kind === "none") return null;
  const domain = config.cookieDomain || new URL(config.homeUrl).hostname;
  const cookies = snapshot.cookies.filter(
    (cookie) =>
      cookie.value &&
      matchesCookieDomain(cookie.domain, domain) &&
      (!cookie.expires || cookie.expires === -1 || cookie.expires * 1000 > now)
  );
  const pairs = new Map<string, string>();
  // Prefer the most specific path, without duplicating Cookie-header names.
  for (const cookie of [...cookies].sort((a, b) => (b.path?.length || 0) - (a.path?.length || 0))) {
    if (!pairs.has(cookie.name)) pairs.set(cookie.name, cookie.value);
  }
  const envelope: Record<string, string> = {
    cookie: [...pairs]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, value]) => `${name}=${value}`)
      .join("; "),
    userAgent: snapshot.userAgent,
  };
  const expiryCandidates: number[] = [];
  for (const source of config.tokenSources) {
    const value =
      source.type === "cookie"
        ? pairs.get(source.name)
        : source.type === "localStorage" || source.type === "sessionStorage"
          ? snapshot.storage[source.key]
          : undefined;
    if (!value) continue;
    const token = unwrap(value);
    const expiry = decodeJwtPayloadExp(token);
    if (expiry !== null && expiry <= now) continue;
    if (expiry !== null) expiryCandidates.push(expiry);
    const key =
      source.type === "cookie" ? source.name : source.type !== "header" ? source.key : "token";
    envelope[key] = token;
    if (requirement.kind === "token" && !envelope.token) envelope.token = token;
  }
  if (provider === "muse-spark-web") {
    if (!snapshot.authorization?.startsWith("ecto1:")) return null;
    envelope.authorization = snapshot.authorization;
  }
  const credential = JSON.stringify(envelope);
  let data: Record<string, unknown>;
  try {
    data = buildWebSessionProviderSpecificData(requirement, credential, { domains: [domain] });
  } catch {
    return null;
  }
  // Provider credential parsers may omit this companion even when executors use it.
  // Preserve the UA from the original signed-in Chrome, including cookie-only sync.
  if (snapshot.userAgent.trim()) data.userAgent = snapshot.userAgent;
  if (snapshot.models !== undefined) {
    const observed = browserModelsSchema.safeParse(snapshot.models);
    if (!observed.success) return null;
    data.browserModels = observed.data;
  }
  if (provider === "muse-spark-web") data.authorization = snapshot.authorization;
  if (expiryCandidates.length)
    data.cookieExpiresAt = new Date(Math.min(...expiryCandidates)).toISOString();
  if (!hasUsableWebSessionCredential(provider, data)) return null;
  const apiKey = resolveWebSessionImportApiKey(requirement, credential, data);
  // Hashes stay in memory. Tokens and cookies are never written to logs or sidecar files.
  const fingerprint = createHash("sha256").update(JSON.stringify({ apiKey, data })).digest("hex");
  return { apiKey, data, fingerprint };
}

export function metaAuthorization(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== "wss:" ||
      parsed.hostname !== "gateway.meta.ai" ||
      parsed.pathname !== "/ws/clippy"
    )
      return undefined;
    const value = parsed.searchParams.get("Authorization");
    return value?.startsWith("ecto1:") ? value : undefined;
  } catch {
    return undefined;
  }
}

export function blockedConnection(connection: Record<string, unknown>): boolean {
  return ["banned", "credits_exhausted"].some(
    (status) =>
      connection.testStatus === status ||
      connection.lastErrorType === status ||
      connection.errorCode === status
  );
}
