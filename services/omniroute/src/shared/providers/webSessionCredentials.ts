import { WEB_COOKIE_PROVIDERS } from "@/shared/constants/providers";
import {
  extractCookieValue,
  normalizeSessionCookieHeader,
  parseJsonCookiesToHeader,
  stripCookieInputPrefix,
} from "@/lib/providers/webCookieAuth";
import { decodeJwtPayloadExp } from "@/shared/utils/webCookieExpiry";
import { getExtractionConfig } from "@omniroute/open-sse/services/tokenExtractionConfig";
import { matchesCookieDomain } from "@omniroute/open-sse/utils/cookieDomain";

export type WebSessionCredentialRequirement =
  | {
      kind: "cookie" | "token";
      credentialName: string;
      placeholder: string;
      acceptsFullCookieHeader: boolean;
      storageKeys: readonly string[];
      /**
       * #5465 — Optional i18n key for a provider-specific credential hint that
       * REPLACES the generic "Required cookie: {credential}…" copy. Use when the
       * generic template is confusing (e.g. t3.chat needs a localStorage value
       * AND the Cookie header, so the one-line cookie hint reads circular).
       */
      hintKey?: string;
      hintFallback?: string;
      /** Provider-specific replacement for the generic four-step DevTools guide. */
      guideSteps?: readonly string[];
      guideNote?: string;
    }
  | {
      kind: "none";
      credentialName: "";
      placeholder: "";
      acceptsFullCookieHeader: false;
      storageKeys: readonly [];
    };

export const WEB_SESSION_CREDENTIAL_REQUIREMENTS = {
  "qwen-browser": {
    kind: "token",
    credentialName: "Qwen browser token + full Cookie header",
    placeholder: '{"token":"...","cookie":"...","userAgent":"..."}',
    acceptsFullCookieHeader: true,
    storageKeys: ["token", "accessToken", "cookie", "userAgent"],
    hintFallback:
      "Use the token from chat.qwen.ai Local Storage with the complete Cookie header from the same signed-in browser, or paste a full Cookie header/browser export containing the named token cookie.",
  },
  "chatgpt-web": {
    kind: "cookie",
    credentialName: "Playwright storage-state JSON",
    placeholder: '{"cookies":[...],"origins":[...]}',
    acceptsFullCookieHeader: false,
    storageKeys: ["storageState", "cookies", "origins"],
    hintFallback:
      "Export storageState from a browser context that is already signed in to chatgpt.com, then paste the complete JSON object. Raw Cookie headers are intentionally rejected.",
    guideSteps: [
      "Sign in to chatgpt.com in a dedicated browser profile.",
      "Export that profile's Playwright-compatible storageState object.",
      "Paste the complete JSON object here and validate it before saving.",
    ],
    guideNote: "The credential is encrypted at rest and is used only by the local browser context.",
  },
  "chatgpt-web-codex": {
    kind: "cookie",
    credentialName: "ChatGPT Cookie header (full)",
    placeholder: "__Secure-next-auth.session-token=...; cf_clearance=...",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "sessionToken", "session-token", "__Secure-next-auth.session-token"],
  },
  "zenmux-free": {
    kind: "cookie",
    credentialName: "Cookie header (full)",
    placeholder: "paste the full Cookie header from zenmux.ai",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie"],
  },
  "tencent-aistudio-web": {
    kind: "cookie",
    credentialName: "Cookie header (full)",
    placeholder: "paste the full Cookie header from aistudio.tencent.ai",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie"],
  },
  "tinycms-web": {
    kind: "token",
    credentialName: "app-config-uuid",
    placeholder: "R...",
    acceptsFullCookieHeader: false,
    storageKeys: ["apiKey", "token", "uuid", "app-config-uuid"],
  },
  "grok-web": {
    kind: "cookie",
    credentialName: "sso + sso-rw",
    placeholder: "sso=...; sso-rw=...",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "sso", "sso-rw", "userAgent"],
    // #7567 — grok.com's cf_clearance cookie is pinned to IP + User-Agent + TLS
    // fingerprint of the browser that earned it, so pasting it from a different
    // machine/IP causes a 403 that is actually correct Cloudflare behavior. Point
    // users at the Custom User-Agent field under Advanced Settings + same IP/proxy,
    // instead of the generic (and here misleading) single-cookie hint.
    hintKey: "grokWebCookieHint",
    hintFallback:
      "grok.com's cf_clearance cookie is pinned to the IP, User-Agent, and TLS fingerprint of the browser where you copied it — pasting it from a different machine/IP causes a 403. Paste sso and sso-rw here, then open Advanced Settings and fill Custom User-Agent with the EXACT User-Agent string of that same browser, and use the same IP/proxy for this connection.",
  },
  "gemini-web": {
    kind: "cookie",
    credentialName: "__Secure-1PSID (optional: __Secure-1PSIDTS)",
    placeholder: "__Secure-1PSID=...; __Secure-1PSIDTS=...",
    hintKey: "geminiWebCookieHint",
    hintFallback:
      'Accepted formats: full Cookie header without the "Cookie:" prefix, a single __Secure-1PSID value, or browser-export JSON such as {"cookies":{"__Secure-1PSID":"...","__Secure-1PSIDTS":"...","__Secure-1PSIDCC":"..."}}.',
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "__Secure-1PSID", "__Secure-1PSIDTS"],
  },
  "notion-web": {
    kind: "cookie",
    credentialName: "token_v2 (optional: space_id, notion_browser_id)",
    placeholder: "token_v2=...; space_id=...; notion_browser_id=...",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "token_v2", "space_id", "notion_browser_id"],
  },
  "gemini-business": {
    kind: "cookie",
    credentialName: "__Secure-1PSID (optional: __Secure-1PSIDTS)",
    placeholder: "__Secure-1PSID=...; __Secure-1PSIDTS=... (from business.gemini.google)",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "__Secure-1PSID", "__Secure-1PSIDTS"],
  },
  "perplexity-web": {
    kind: "cookie",
    credentialName: "__Secure-next-auth.session-token",
    placeholder: "__Secure-next-auth.session-token=...",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "sessionToken", "session-token", "__Secure-next-auth.session-token"],
  },
  hyperagent: {
    kind: "cookie",
    credentialName: "Session Cookie",
    placeholder: "Paste full Cookie header from hyperagent.com",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "sessionCookie", "authCookie"],
  },
  "blackbox-web": {
    kind: "cookie",
    credentialName: "__Secure-authjs.session-token",
    placeholder: "__Secure-authjs.session-token=...; other=value",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "sessionToken", "__Secure-authjs.session-token"],
  },
  "muse-spark-web": {
    kind: "cookie",
    // #9502: the WS protocol (#7528) needs both the ecto_1_sess cookie (GraphQL
    // warmup/mode-switch) and a separate ecto1:... WS auth token (Authorization
    // query param on wss://gateway.meta.ai/ws/clippy). The executor extracts the
    // ecto1: token from the apiKey field via /ecto1:[^\s;]+/i.
    credentialName: "ecto_1_sess + ecto1: WS auth token",
    placeholder:
      "ecto_1_sess=...; ecto1:... (WS auth token from meta.ai DevTools → Network → WS → clippy)",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "ecto_1_sess", "abra_sess", "authorization"],
  },
  "claude-web": {
    kind: "cookie",
    credentialName: "sessionKey",
    placeholder: "sessionKey=... or full Cookie header from claude.ai",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "sessionKey"],
  },
  "deepseek-web": {
    kind: "token",
    credentialName: "userToken",
    placeholder: "userToken=... or paste raw userToken",
    acceptsFullCookieHeader: false,
    storageKeys: ["token", "userToken"],
  },
  "copilot-web": {
    kind: "token",
    credentialName: "access_token",
    placeholder: "access_token=... or a DevTools HAR export",
    acceptsFullCookieHeader: false,
    storageKeys: ["token", "access_token", "accessToken"],
  },
  "copilot-m365-web": {
    kind: "token",
    credentialName: "access_token + chathubPath",
    placeholder: "access_token=...; chathubPath=redacted",
    acceptsFullCookieHeader: false,
    storageKeys: ["token", "access_token", "accessToken", "chathubPath", "userTenant"],
  },
  "t3-web": {
    kind: "cookie",
    credentialName: "convex-session-id + Cookie header",
    placeholder: "convex-session-id=abc123...; Cookie: ...",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "convex-session-id", "convexSessionId"],
    // #5465 — the generic cookie hint reads circular for t3.chat (needs a
    // localStorage value AND the Cookie header); use the step-by-step DevTools
    // copy that already ships translated in every locale.
    hintKey: "t3ChatWebCookieHint",
  },
  "adapta-web": {
    kind: "cookie",
    credentialName: "__client",
    placeholder: "__client=... or full Cookie header from agent.adapta.one",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "__client"],
  },
  "inner-ai": {
    kind: "cookie",
    credentialName: "token + email",
    placeholder: "token_value user@example.com",
    acceptsFullCookieHeader: false,
    storageKeys: ["token", "cookie", "email"],
  },
  huggingchat: {
    kind: "cookie",
    credentialName: "full Cookie header (hf-chat + token)",
    placeholder:
      "hf-chat=...; token=...; aws-waf-token=... (full Cookie header from huggingface.co)",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "hf-chat"],
  },
  "yuanbao-web": {
    kind: "cookie",
    credentialName: "full Cookie header (hy_user + hy_token)",
    placeholder: "hy_user=...; hy_token=... (full Cookie header from yuanbao.tencent.com)",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "hy_user", "hy_token"],
  },
  "poe-web": {
    kind: "cookie",
    credentialName: "p-b",
    placeholder: "p-b=... or full Cookie header from poe.com",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "p-b"],
  },
  "venice-web": {
    kind: "cookie",
    credentialName: "session",
    placeholder: "session=... or full Cookie header from venice.ai",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "session"],
  },
  "v0-vercel-web": {
    kind: "cookie",
    credentialName: "user_session (v0.app) or legacy __vercel_session",
    placeholder: "user_session=...; v0_browser_id=...",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "user_session", "__vercel_session"],
  },
  "kimi-web": {
    kind: "token",
    credentialName: "access_token",
    placeholder: "access_token from www.kimi.com localStorage",
    acceptsFullCookieHeader: true,
    storageKeys: ["token", "access_token", "accessToken", "cookie", "kimi-auth"],
  },
  "doubao-web": {
    kind: "cookie",
    credentialName: "Cookie header or completion request URL from www.dola.com",
    placeholder:
      "sessionid=...; ttwid=...; s_v_web_id=... (or full Request URL / cURL from DevTools Network)",
    acceptsFullCookieHeader: true,
    storageKeys: [
      "cookie",
      "sessionid",
      "ttwid",
      "s_v_web_id",
      "fp",
      "device_id",
      "web_id",
      "msToken",
    ],
  },
  "duckduckgo-web": {
    kind: "cookie",
    credentialName: "duckai",
    placeholder: "duckai=... or full Cookie header from duckduckgo.com",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "duckai"],
  },
  "t3-chat-web": {
    kind: "token",
    credentialName: "token",
    placeholder: "Paste your T3 Chat token from t3.chat (Local Storage → token)",
    acceptsFullCookieHeader: false,
    storageKeys: ["token"],
  },
  "chatglm-web": {
    kind: "cookie",
    credentialName: "chatglm_session",
    placeholder: "chatglm_session=... or full Cookie header from chatglm.cn",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "chatglm_session"],
  },
  "xiaomimimo-web": {
    kind: "cookie",
    credentialName: "session",
    placeholder: "session=... or full Cookie header from aistudio.xiaomimimo.com",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "session"],
  },
  "manus-web": {
    kind: "cookie",
    credentialName: "manus_session",
    placeholder: "manus_session=... or full Cookie header from manus.im",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "manus_session"],
  },
  "zai-web": {
    kind: "token",
    credentialName: 'Local Storage value named "token"',
    placeholder: "eyJ... (chat.z.ai → DevTools → Application → Local Storage → token)",
    acceptsFullCookieHeader: false,
    storageKeys: ["token"],
    hintKey: "zaiWebCredentialHint",
    hintFallback:
      'Copy only the "token" value from chat.z.ai Local Storage. Do not copy a Cookie header. OmniRoute uses its browser transport to obtain the per-request CAPTCHA proof.',
    guideSteps: [
      "Open chat.z.ai and sign in.",
      "Open DevTools → Application → Local Storage → https://chat.z.ai.",
      'Find the row named "token" and copy only its value. Do not copy any Cookie header.',
      "Paste the token below and check the connection. OmniRoute handles the per-request CAPTCHA through its browser transport.",
    ],
    guideNote:
      "Treat the token like a password. Browser transport is enabled by default; do not set OMNIROUTE_BROWSER_POOL=off for this connection. If Z.ai signs you out or the token expires, repeat these steps with the new value.",
  },
  lmarena: {
    kind: "cookie",
    // arena.ai's auth cookie is `arena-auth-prod-v1` (the legacy hint said `session`,
    // which never matched the real cookie name and confused users). #3810
    //
    // #4271: LMArena migrated to Supabase SSR chunked cookies — the single
    // `arena-auth-prod-v1` cookie is now empty and the session is split across
    // `arena-auth-prod-v1.0`, `arena-auth-prod-v1.1`, … Users must paste the FULL
    // Cookie header so the executor can reconstruct the single cookie from chunks.
    credentialName: "full Cookie header (arena-auth-prod-v1.0 + arena-auth-prod-v1.1)",
    placeholder:
      "arena-auth-prod-v1.0=...; arena-auth-prod-v1.1=...; other=value (full Cookie header from arena.ai)",
    acceptsFullCookieHeader: true,
    storageKeys: [
      "cookie",
      "arena-auth-prod-v1",
      "arena-auth-prod-v1.0",
      "arena-auth-prod-v1.1",
      "session",
    ],
    hintKey: "lmarenaWebCookieHint",
    hintFallback:
      "Open arena.ai, sign in, then copy the full Cookie header from a Network request. Include arena-auth-prod-v1.0 and arena-auth-prod-v1.1 (and further chunks if present), preferably with cf_clearance. Do not paste only the empty arena-auth-prod-v1 cookie. Optional: providerSpecificData.recaptchaV3Token if create-evaluation still returns 403.",
  },
  promptql: {
    kind: "token",
    credentialName: "Bearer JWT (optional: projectId, session Cookie)",
    placeholder: "eyJ...  (Authorization Bearer from prompt.ql.app)",
    acceptsFullCookieHeader: false,
    storageKeys: ["token", "jwt", "apiKey", "projectId", "project_id", "cookie"],
  },
  "adobe-firefly": {
    // Prefer IMS access_token JWT (Bearer). Cookie from firefly.adobe.com alone
    // only mints a guest IMS token. Kind stays "cookie" for multi-account UX;
    // resolveAdobeAccessToken auto-detects JWT vs cookie and rejects guests.
    kind: "cookie",
    credentialName: "IMS access_token JWT (recommended) or multi-domain Cookie",
    placeholder:
      "Paste eyJ… JWT from Authorization: Bearer on firefly-3p generate request (not page Cookie alone)",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "token", "access_token", "accessToken"],
  },
  "conol-web": {
    kind: "cookie",
    credentialName: "__Secure-better-auth.session_token",
    placeholder: "__Secure-better-auth.session_token=... or full Cookie header from conol.ai",
    acceptsFullCookieHeader: true,
    storageKeys: ["cookie", "__Secure-better-auth.session_token"],
  },
  maxai: {
    kind: "token",
    credentialName: "MaxAI access token (Bearer) + device id",
    placeholder:
      "Use browser sign-in — OmniRoute mints the MaxAI access token, device id, and user id for you",
    acceptsFullCookieHeader: false,
    storageKeys: [
      "accessToken",
      "access_token",
      "maxaiAccessToken",
      "deviceId",
      "maxaiDeviceId",
      "userId",
      "maxaiUserId",
    ],
  },
  uc: {
    // UC (uncensored.com) persona: auth is the durable Clerk `__client` cookie
    // (a JWT with no exp) plus the session id + user id, all stored in
    // providerSpecificData. The executor mints a short-lived `__session` JWT per
    // connect from `__client`; it never reads `apiKey`. Storage keys mirror the
    // aliases resolveUcCredential() accepts (ucClientCookie/clientCookie/__client,
    // ucSid/sid, ucUid/uid, ucCookies/cookies).
    kind: "cookie",
    credentialName: "Clerk __client cookie + session id + user id",
    placeholder: "__client=...; then set session id (sid) and user id (uid)",
    acceptsFullCookieHeader: true,
    storageKeys: [
      "cookie",
      "cookies",
      "ucCookies",
      "ucClientCookie",
      "clientCookie",
      "__client",
      "ucSid",
      "sid",
      "ucUid",
      "uid",
    ],
  },
} satisfies Record<string, WebSessionCredentialRequirement> &
  Record<keyof typeof WEB_COOKIE_PROVIDERS, WebSessionCredentialRequirement>;

export function getWebSessionCredentialRequirement(
  providerId: unknown
): WebSessionCredentialRequirement | null {
  if (typeof providerId !== "string") return null;
  return (
    WEB_SESSION_CREDENTIAL_REQUIREMENTS[
      providerId as keyof typeof WEB_SESSION_CREDENTIAL_REQUIREMENTS
    ] ?? null
  );
}

export function canUpdateProviderApiKey(authType: unknown, providerId: unknown): boolean {
  if (authType === "apikey") return true;
  if (authType !== "cookie") return false;
  return getWebSessionCredentialRequirement(providerId)?.kind === "token";
}

export function requiresWebSessionCredential(providerId: unknown): boolean {
  const requirement = getWebSessionCredentialRequirement(providerId);
  return !!requirement && requirement.kind !== "none";
}

function hasNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

// Storage keys include device/workspace hints. Only these actual authentication
// fields may satisfy the credential contract. Each inner group is required;
// outer groups are alternatives. Upstream validation still decides validity.
const AUTHENTICATION_KEY_GROUPS: Record<string, readonly (readonly string[])[]> = {
  "chatgpt-web-codex": [["__Secure-next-auth.session-token"]],
  "qwen-browser": [["token"]],
  "tinycms-web": [["app-config-uuid"]],
  "grok-web": [["sso"]],
  "gemini-web": [["__Secure-1PSID"]],
  "gemini-business": [["__Secure-1PSID"]],
  "notion-web": [["token_v2"]],
  "perplexity-web": [["__Secure-next-auth.session-token"]],
  "blackbox-web": [["__Secure-authjs.session-token"]],
  "muse-spark-web": [["ecto_1_sess"], ["abra_sess"]],
  "claude-web": [["sessionKey"]],
  "deepseek-web": [["token"]],
  "copilot-web": [["access_token"]],
  "copilot-m365-web": [["access_token"]],
  "t3-web": [["convex-session-id"]],
  "adapta-web": [["__client"], ["__session"]],
  "inner-ai": [["token"]],
  huggingchat: [["hf-chat"]],
  "yuanbao-web": [["hy_user", "hy_token"]],
  "poe-web": [["p-b"]],
  "venice-web": [["session"], ["venice_session"]],
  "v0-vercel-web": [["user_session"], ["__vercel_session"], ["__Secure-next-auth.session-token"]],
  "kimi-web": [["access_token"], ["kimi-auth"]],
  "doubao-web": [["sessionid"]],
  "duckduckgo-web": [["duckai"]],
  "t3-chat-web": [["token"]],
  "chatglm-web": [["chatglm_session"]],
  "xiaomimimo-web": [["session"]],
  "manus-web": [["manus_session"]],
  "zai-web": [["token"]],
  lmarena: [["arena-auth-prod-v1"], ["arena-auth-prod-v1.0", "arena-auth-prod-v1.1"], ["session"]],
  promptql: [["token"]],
  "conol-web": [["__Secure-better-auth.session_token"]],
  maxai: [["accessToken"]],
  uc: [["__client", "sid", "uid"]],
};

const AUTHENTICATION_ALIASES: Record<string, readonly string[]> = {
  "__Secure-next-auth.session-token": ["sessionToken", "session-token", "next-auth.session-token"],
  "__Secure-authjs.session-token": ["sessionToken"],
  "app-config-uuid": ["apiKey", "token", "uuid"],
  "convex-session-id": ["convexSessionId"],
  access_token: ["token", "accessToken"],
  token: ["userToken", "jwt", "apiKey", "accessToken"],
  accessToken: ["access_token", "maxaiAccessToken"],
  __client: ["ucClientCookie", "clientCookie"],
  sid: ["ucSid"],
  uid: ["ucUid"],
};

function credentialValue(value: unknown, names: readonly string[]): string {
  if (!hasNonEmptyString(value)) return "";
  const raw = stripCookieInputPrefix(value);
  if (raw.startsWith("{")) {
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "";
      for (const key of [...names, "value"]) {
        if (hasNonEmptyString(parsed[key])) return credentialValue(parsed[key], names);
      }
      return "";
    } catch {
      return "";
    }
  }
  if (raw.startsWith("[")) return "";
  if (/[\x00-\x20\x7f;]/.test(raw)) return "";
  const expiry = decodeJwtPayloadExp(raw);
  if (expiry !== null && expiry <= Date.now()) return "";
  return raw;
}

function namedAuthenticationValue(data: Record<string, unknown>, name: string): string {
  const names = [name, ...(AUTHENTICATION_ALIASES[name] ?? [])];
  for (const key of names) {
    const value = credentialValue(data[key], names);
    if (value) return value;
  }
  for (const key of ["cookie", "cookies", "ucCookies", "sessionCookie", "authCookie"]) {
    if (!hasNonEmptyString(data[key])) continue;
    try {
      const header = normalizeSessionCookieHeader(data[key], name);
      for (const cookieName of names) {
        const value = credentialValue(extractCookieValue(header, cookieName), names);
        if (value) return value;
      }
    } catch {
      /* A malformed export cannot authenticate. */
    }
  }
  return "";
}

export function hasUsableWebSessionCredential(
  providerId: unknown,
  providerSpecificData: unknown
): boolean {
  const requirement = getWebSessionCredentialRequirement(providerId);
  if (!requirement || requirement.kind === "none") return false;
  if (!providerSpecificData || typeof providerSpecificData !== "object") return false;

  const data = providerSpecificData as Record<string, unknown>;
  if (Array.isArray(data)) return false;
  if (hasNonEmptyString(data.cookieExpiresAt)) {
    const expiry = Date.parse(data.cookieExpiresAt);
    if (Number.isFinite(expiry) && expiry <= Date.now()) return false;
  }
  const groups = AUTHENTICATION_KEY_GROUPS[String(providerId)];
  if (groups) {
    // Qwen auth is in localStorage; an arbitrary token= cookie must never be
    // mistaken for its Bearer credential.
    if (providerId === "qwen-browser")
      return !!credentialValue(data.token ?? data.accessToken, ["token", "accessToken"]);
    return groups.some((group) => group.every((name) => !!namedAuthenticationValue(data, name)));
  }
  // Providers whose protocol uses an opaque/full header retain that contract,
  // but empty cookies and metadata-only objects are not usable credentials.
  for (const key of ["cookie", "sessionCookie", "authCookie"]) {
    if (!hasNonEmptyString(data[key])) continue;
    try {
      const header = normalizeSessionCookieHeader(data[key], "session");
      if (
        header
          .split(";")
          .some((pair) => pair.indexOf("=") > 0 && pair.slice(pair.indexOf("=") + 1).trim())
      )
        return true;
    } catch {
      /* Invalid cookie input. */
    }
  }
  if (providerId === "adobe-firefly")
    return ["token", "access_token", "accessToken"].some(
      (key) => !!credentialValue(data[key], [key])
    );
  return false;
}

/** Normalize a bulk import without copying the Cookie blob into metadata fields. */
export function buildWebSessionProviderSpecificData(
  requirement: WebSessionCredentialRequirement | null,
  credential: string,
  options: { domains?: readonly string[] } = {}
): Record<string, unknown> {
  if (!requirement || requirement.kind === "none") return {};
  const provider =
    Object.entries(WEB_SESSION_CREDENTIAL_REQUIREMENTS).find(
      ([, value]) => value === requirement
    )?.[0] ?? "";
  const groups = AUTHENTICATION_KEY_GROUPS[provider] ?? [];
  const authenticationNames = [...new Set(groups.flat())];
  const raw = (credential || "").trim();
  if (!raw) return {};
  let envelope: Record<string, unknown> | null = null;
  if (raw.startsWith("{")) {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) envelope = parsed;
    } catch {
      throw new Error("Invalid web-session credential JSON");
    }
  }
  const data: Record<string, unknown> = {};
  if (provider === "inner-ai") {
    const input =
      envelope && hasNonEmptyString(envelope.token)
        ? envelope.token
        : stripCookieInputPrefix(raw).replace(/^token=/u, "");
    const separator = input.lastIndexOf(" ");
    const email =
      envelope && hasNonEmptyString(envelope.email)
        ? envelope.email.trim()
        : separator > 0 && input.slice(separator + 1).includes("@")
          ? input.slice(separator + 1).trim()
          : "";
    const token = credentialValue(email && separator > 0 ? input.slice(0, separator) : input, [
      "token",
    ]);
    if (token) data.token = token;
    if (email) data.email = email;
    if (token) data.cookie = email ? `${token} ${email}` : token;
    return data;
  }
  if (provider === "qwen-browser") {
    if (envelope) {
      for (const key of ["token", "accessToken", "userAgent"]) {
        if (hasNonEmptyString(envelope[key])) data[key] = envelope[key].trim();
      }
    }
    const exportedHeader = parseJsonCookiesToHeader(raw, { domains: ["qwen.ai"] });
    if (exportedHeader !== null) data.cookie = exportedHeader;
    else if (envelope && hasNonEmptyString(envelope.cookie)) {
      data.cookie = normalizeSessionCookieHeader(envelope.cookie, "", { domains: ["qwen.ai"] });
    } else if (!envelope && stripCookieInputPrefix(raw).includes("=")) {
      data.cookie = normalizeSessionCookieHeader(raw, "", { domains: ["qwen.ai"] });
    } else if (!envelope) data.token = credentialValue(raw, ["token"]);
    const token =
      credentialValue(data.token ?? data.accessToken, ["token", "accessToken"]) ||
      (hasNonEmptyString(data.cookie)
        ? credentialValue(extractCookieValue(data.cookie, "token"), ["token"])
        : "");
    if (token) data.token = token;
    return data;
  }
  if (requirement.kind === "token") {
    const config = getExtractionConfig(provider);
    const domains =
      options.domains ??
      (config ? [config.cookieDomain || new URL(config.homeUrl).hostname] : undefined);
    const exportedHeader = parseJsonCookiesToHeader(raw, { domains });
    if (exportedHeader !== null) {
      data.cookie = exportedHeader;
      let token = "";
      for (const name of authenticationNames) {
        token ||= namedAuthenticationValue(data, name);
      }
      for (const source of config?.tokenSources ?? []) {
        if (source.type === "cookie")
          token ||= credentialValue(
            extractCookieValue(exportedHeader, source.name),
            authenticationNames
          );
      }
      if (token) {
        for (const name of authenticationNames) {
          for (const key of [name, ...(AUTHENTICATION_ALIASES[name] ?? [])]) {
            if (requirement.storageKeys.includes(key)) data[key] = token;
          }
        }
      }
      return data;
    }
    if (provider === "copilot-web" && envelope?.log && typeof envelope.log === "object") {
      const entries = (envelope.log as Record<string, unknown>).entries;
      if (Array.isArray(entries)) {
        for (const entry of entries) {
          const request = entry?.request;
          if (!request || typeof request.url !== "string" || !Array.isArray(request.headers))
            continue;
          let host: string;
          try {
            host = new URL(request.url).hostname;
          } catch {
            continue;
          }
          if (!matchesCookieDomain(host, "copilot.microsoft.com")) continue;
          const authorization = request.headers.find(
            (header: { name?: string }) => header?.name?.toLowerCase() === "authorization"
          )?.value;
          const token =
            typeof authorization === "string" && /^bearer\s+/iu.test(authorization)
              ? credentialValue(authorization, ["access_token"])
              : "";
          if (!token) continue;
          data.token = token;
          data.access_token = token;
          const cookie = request.headers.find(
            (header: { name?: string }) => header?.name?.toLowerCase() === "cookie"
          )?.value;
          if (hasNonEmptyString(cookie)) data.cookie = normalizeSessionCookieHeader(cookie, "");
          return data;
        }
      }
      return data;
    }
    if (envelope) {
      for (const key of requirement.storageKeys) {
        if (hasNonEmptyString(envelope[key])) data[key] = envelope[key].trim();
      }
      for (const name of authenticationNames) {
        const value =
          namedAuthenticationValue(envelope, name) || credentialValue(envelope.value, [name]);
        if (value) {
          for (const key of [name, ...(AUTHENTICATION_ALIASES[name] ?? [])]) {
            if (requirement.storageKeys.includes(key)) data[key] = value;
          }
        }
      }
    } else {
      const stripped = stripCookieInputPrefix(raw);
      for (const pair of stripped.split(";")) {
        const separator = pair.indexOf("=");
        const key = separator > 0 ? pair.slice(0, separator).trim() : "";
        if (requirement.storageKeys.includes(key)) data[key] = pair.slice(separator + 1).trim();
      }
      let value = "";
      for (const name of authenticationNames) value ||= namedAuthenticationValue(data, name);
      // A named metadata pair must not become an opaque bearer token. The
      // double-padding case keeps bare base64 credentials usable.
      const isBareToken = !stripped.includes("=") || /^[A-Za-z0-9+/_-]+==$/u.test(stripped);
      if (!value && !stripped.includes(";") && isBareToken)
        value = credentialValue(stripped, authenticationNames);
      if (value) {
        for (const name of authenticationNames) {
          for (const key of [name, ...(AUTHENTICATION_ALIASES[name] ?? [])]) {
            if (requirement.storageKeys.includes(key)) data[key] = value;
          }
        }
      }
    }
    return data;
  }
  if (provider === "chatgpt-web") return { storageState: raw };
  const config = getExtractionConfig(provider);
  const domains =
    options.domains ??
    (config ? [config.cookieDomain || new URL(config.homeUrl).hostname] : undefined);
  const cookieInput = envelope && hasNonEmptyString(envelope.cookie) ? envelope.cookie : raw;
  const defaultName = authenticationNames[0] || "session";
  const header = normalizeSessionCookieHeader(cookieInput, defaultName, { domains });
  data.cookie = header;
  for (const key of requirement.storageKeys) {
    if (key === "cookie") continue;
    if (envelope && hasNonEmptyString(envelope[key])) data[key] = envelope[key].trim();
    const value = extractCookieValue(header, key);
    if (value) data[key] = value;
  }
  for (const name of authenticationNames) {
    const value = extractCookieValue(header, name);
    if (!value) continue;
    for (const alias of AUTHENTICATION_ALIASES[name] ?? []) {
      if (requirement.storageKeys.includes(alias)) data[alias] = value;
    }
  }
  return data;
}

/**
 * Resolve the value that a web-session import must store in the connection's
 * `apiKey` column.
 *
 * `token`-kind providers (deepseek-web, copilot-web, copilot-m365-web,
 * t3-chat-web, …) are authenticated from `apiKey`: both the connection
 * validator (`validateDeepSeekWebProvider({ apiKey })`) and the executor
 * (`extractUserToken` → `credentials.apiKey`) read the token there — never from
 * `providerSpecificData`. The bulk web-session import used to leave `apiKey`
 * null and stash the token only in `providerSpecificData`, so imported token-kind
 * connections were never recognized. Return the credential for token-kind so the
 * import stores it where those readers look.
 *
 * `cookie`-kind providers keep `apiKey` null — their executors read the full
 * cookie from `providerSpecificData.cookie`.
 */
export function resolveWebSessionImportApiKey(
  requirement: WebSessionCredentialRequirement | null,
  credential: string,
  normalizedData?: Record<string, unknown>
): string | null {
  if (!requirement || requirement.kind !== "token") return null;
  if (normalizedData) {
    const provider =
      Object.entries(WEB_SESSION_CREDENTIAL_REQUIREMENTS).find(
        ([, value]) => value === requirement
      )?.[0] ?? "";
    for (const name of (AUTHENTICATION_KEY_GROUPS[provider] ?? []).flat()) {
      const value = namedAuthenticationValue(normalizedData, name);
      if (value) return value;
    }
    return null;
  }
  const trimmed = typeof credential === "string" ? credential.trim() : "";
  return trimmed.length > 0 ? trimmed : null;
}

/** Project imported cookies into the executor credential slot without rewriting storage. */
export function resolveWebSessionRuntimeApiKey(
  provider: string,
  apiKey: string | null | undefined,
  data: Record<string, unknown>
): string | null {
  if (hasNonEmptyString(apiKey)) return apiKey;
  const requirement = getWebSessionCredentialRequirement(provider);
  if (
    requirement?.kind !== "cookie" ||
    !requirement.acceptsFullCookieHeader ||
    !hasUsableWebSessionCredential(provider, data)
  )
    return null;
  return hasNonEmptyString(data.cookie) ? data.cookie : null;
}
