/** Persist extension credentials through the running gateway's encrypted store. */
import { createHash } from "node:crypto";
import { z } from "zod";
import { blockedConnection, normalizeSnapshot } from "../../../scripts/ops/webSessionSyncCore.ts";
import { normalizeChatGptWebStorageState } from "../../../open-sse/utils/chatgptWebExecutorAdapter.ts";
import { encodeChatGptWebCodexSecrets } from "../../../open-sse/executors/chatgpt-web-codex/credentials.ts";

const domains: Record<string, string[]> = {
  "chatgpt-web": ["chatgpt.com", "openai.com"], "qwen-browser": ["qwen.ai"],
  "doubao-web": ["dola.com"], "gemini-web": ["google.com"], "deepseek-web": ["deepseek.com"],
  "kimi-web": ["kimi.ai"], "grok-web": ["grok.com"], "claude-web": ["claude.ai"],
  "perplexity-web": ["perplexity.ai"], "zai-web": ["z.ai"],
};
const cookieSchema = z.object({
  name: z.string().min(1).max(1024), value: z.string().max(65536), domain: z.string().min(1).max(256),
  path: z.string().startsWith("/").max(4096), expires: z.number().finite().optional(),
  httpOnly: z.boolean().optional(), secure: z.boolean().optional(),
  sameSite: z.enum(["Strict", "Lax", "None"]).optional(),
}).strict();
const originSchema = z.object({
  origin: z.string().max(2048),
  localStorage: z.array(z.object({ name: z.string().max(1024), value: z.string().max(262144) }).strict()).max(1024),
}).strict();
export const browserCookieHandoffSchema = z.object({
  provider: z.string().refine(value => value in domains),
  account_id: z.string().regex(/^[a-f0-9]{24}$/),
  action: z.enum(["sync", "expired", "disconnect"]).default("sync"),
  storage_state: z.object({ cookies: z.array(cookieSchema).max(4096), origins: z.array(originSchema).max(32) }).strict().optional(),
  user_agent: z.string().max(2048).optional(), cookie_store_id: z.string().max(128).nullable().optional(),
}).strict().refine(value => value.action !== "sync" || !!value.storage_state);

type Input = z.infer<typeof browserCookieHandoffSchema>;
type Row = Record<string, unknown>;
export type HandoffRepository = {
  getConnections: (provider: string) => Promise<Row[]>;
  create: (data: Row) => Promise<Row | null>;
  update: (id: string, data: Row) => Promise<unknown>;
  seal: (data: Row) => string;
};
export class BrowserCookieHandoffError extends Error {
  constructor(public readonly status: number, public readonly code: string) { super(code); }
}
const fail = (status: number, code: string): never => { throw new BrowserCookieHandoffError(status, code); };
const record = (value: unknown): Row => value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};

export function captureGatewayCookies(input: Input) {
  const state = input.storage_state;
  if (!state) return fail(400, "invalid_cookie_snapshot");
  const allowed = (value: string) => domains[input.provider].some(domain => value === domain || value.endsWith("." + domain));
  if (state.cookies.some(cookie => !allowed(cookie.domain.toLowerCase().replace(/^\./, ""))))
    return fail(400, "invalid_cookie_domain");
  for (const entry of state.origins) {
    let url: URL;
    try { url = new URL(entry.origin); } catch { return fail(400, "invalid_cookie_origin"); }
    if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash || url.pathname !== "/" || !allowed(url.hostname))
      return fail(400, "invalid_cookie_origin");
  }
  if (input.provider === "chatgpt-web") {
    let normalized: ReturnType<typeof normalizeChatGptWebStorageState>;
    try { normalized = normalizeChatGptWebStorageState(state); } catch { return fail(400, "invalid_cookie_snapshot"); }
    if (!normalized.cookies.some(cookie => /^(?:__Secure-)?(?:next-auth|authjs)\.session-token(?:\.\d+)?$/.test(cookie.name)
      && cookie.value && (cookie.expires === -1 || cookie.expires > Date.now() / 1000)))
      return fail(400, "invalid_cookie_snapshot");
    const apiKey = encodeChatGptWebCodexSecrets({ storageState: { ...normalized } });
    return { provider: "chatgpt-web-codex", usage: "native_codex_only", apiKey,
      data: { storageState: normalized, ...(input.user_agent ? { userAgent: input.user_agent } : {}) } as Row,
      fingerprint: createHash("sha256").update(JSON.stringify([apiKey, input.user_agent || ""])).digest("hex") };
  }
  const captured = normalizeSnapshot(input.provider, { cookies: state.cookies,
    storage: Object.fromEntries(state.origins.flatMap(origin => origin.localStorage.map(item => [item.name, item.value]))),
    userAgent: input.user_agent || "" });
  if (!captured) return fail(400, "invalid_cookie_snapshot");
  return { ...captured, provider: input.provider, usage: "chat_completions" };
}

async function defaultRepository(): Promise<HandoffRepository> {
  // Never initialize a default/global database when Studio has not supplied its store.
  if (!process.env.DATA_DIR?.trim() || !process.env.STORAGE_ENCRYPTION_KEY?.trim())
    return fail(503, "gateway_store_unavailable");
  const providers = await import("../db/providers.ts");
  const { sealBrowserSyncCredential } = await import("../db/encryption.ts");
  return { getConnections: provider => providers.getProviderConnections({ provider }),
    create: data => providers.createProviderConnection(data), update: providers.updateProviderConnection,
    seal: sealBrowserSyncCredential };
}

const leases = new Map<string, Promise<unknown>>();
export async function handoffBrowserCookies(raw: unknown, repository?: HandoffRepository) {
  const parsed = browserCookieHandoffSchema.safeParse(raw);
  if (!parsed.success) return fail(400, "invalid_cookie_snapshot");
  const input = parsed.data;
  const profile = "kratos-extension:" + input.account_id;
  const provider = input.provider === "chatgpt-web" ? "chatgpt-web-codex" : input.provider;
  const key = provider + ":" + profile;
  const previous = leases.get(key) || Promise.resolve();
  const next = previous.catch(() => {}).then(async () => {
    const captured = input.action === "sync" ? captureGatewayCookies(input) : null;
    const db = repository || await defaultRepository();
    const connections = await db.getConnections(provider);
    const current = connections.find(connection => {
      const data = record(connection.providerSpecificData);
      return data.browserSyncProfile === profile && data.kratosCookieAccount === input.account_id;
    });
    const currentData = record(current?.providerSpecificData);
    const usage = input.provider === "chatgpt-web" ? "native_codex_only" : "chat_completions";
    const reply = (id: string | null, enabled: boolean, changed: boolean) => ({
      synced: true, provider, usage, connection_id: id, enabled, changed,
      action: input.action, synced_at: new Date().toISOString(),
    });
    if (input.action !== "sync") {
      if (!current || typeof current.id !== "string") return reply(null, false, false);
      const metadata: Row = { browserSyncProfile: profile, kratosCookieAccount: input.account_id,
        kratosCookieDisabled: input.action, browserSyncedAt: new Date().toISOString() };
      await db.update(current.id, { apiKey: null, providerSpecificData: metadata, isActive: false,
        ...(blockedConnection(current) ? {} : { testStatus: input.action === "expired" ? "expired" : "unknown" }) });
      return reply(current.id, false, true);
    }
    if (current && blockedConnection(current)) return fail(409, "provider_account_restricted");
    if (!captured) return fail(400, "invalid_cookie_snapshot");
    const disabledByUs = ["expired", "disconnect"].includes(String(currentData.kratosCookieDisabled || ""));
    const enabled = !current || current.isActive !== false || disabledByUs;
    if (current && typeof current.id === "string" && currentData.kratosCookieFingerprint === captured.fingerprint && !disabledByUs)
      return reply(current.id, enabled, false);
    const credentialData: Row = { ...captured.data };
    if (Array.isArray(currentData.browserModels) && credentialData.browserModels === undefined) {
      credentialData.browserModels = currentData.browserModels;
      credentialData.browserModelsObservedAt = currentData.browserModelsObservedAt;
    }
    const patch: Row = { apiKey: captured.apiKey, isActive: enabled, providerSpecificData: {
      browserSyncCredential: db.seal(credentialData), browserSyncProfile: profile,
      kratosCookieAccount: input.account_id, kratosCookieFingerprint: captured.fingerprint,
      browserSyncedAt: new Date().toISOString(),
    } };
    if (disabledByUs && current?.testStatus === "expired" && !(typeof current.rateLimitedUntil === "string"
      && Date.parse(current.rateLimitedUntil) > Date.now())) Object.assign(patch, {
      testStatus: "unknown", lastError: null, lastErrorType: null, errorCode: null,
    });
    if (current && typeof current.id === "string") {
      await db.update(current.id, patch);
      return reply(current.id, enabled, true);
    }
    const created = await db.create({ ...patch, provider, authType: "apikey", name: `Kratos browser ${input.account_id}`,
      isActive: true, testStatus: "unknown", priority: 10 });
    if (!created || typeof created.id !== "string") return fail(503, "gateway_store_unavailable");
    return reply(created.id, true, true);
  });
  leases.set(key, next);
  try { return await next; }
  finally { if (leases.get(key) === next) leases.delete(key); }
}
