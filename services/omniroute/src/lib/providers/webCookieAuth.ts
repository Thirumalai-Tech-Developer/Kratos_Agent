import { matchesCookieDomain } from "@omniroute/open-sse/utils/cookieDomain";

export interface CookieNormalizationOptions {
  /** Only constrain exports that carry domain metadata. Raw headers have none. */
  domains?: readonly string[];
  nowMs?: number;
}

const COOKIE_NAME = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;

export function stripCookieInputPrefix(rawValue: string): string {
  const trimmed = (rawValue || "").trim();
  if (!trimmed) return "";

  const withoutBearer = trimmed.replace(/^bearer\s+/i, "");
  return withoutBearer.replace(/^cookie:/i, "").trim();
}

/**
 * Parse a JSON array of cookie objects and produce a Cookie header string.
 *
 * Accepts the format exported by browser cookie-editor extensions / DevTools:
 * ```json
 * [
 *   {"name":"sso","value":"eyJ0eXAi...","domain":".example.com","path":"/"},
 *   {"name":"sso-rw","value":"eyJOTHER..."}
 * ]
 * ```
 *
 * Also accepts {cookies:[...]} storage-state exports and {cookies:{name:value}}
 * maps. Expired cookies are omitted; known provider domains can constrain exports
 * carrying domain metadata. Other browser metadata never enters the header.
 *
 * @param rawValue - The user-provided cookie string (possibly JSON).
 * @returns A Cookie header string, null if the input is not JSON (pass-through).
 * @throws {Error} If a JSON entry is missing the required `name` or `value` field.
 */
export function parseJsonCookiesToHeader(
  rawValue: string,
  options: CookieNormalizationOptions = {}
): string | null {
  const trimmed = (rawValue || "").trim();
  if (!trimmed || (!trimmed.startsWith("[") && !trimmed.startsWith("{"))) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return null;
  }

  if (!Array.isArray(parsed)) {
    if (!parsed || typeof parsed !== "object" || !("cookies" in parsed)) return null;
    const cookies = (parsed as Record<string, unknown>).cookies;
    if (Array.isArray(cookies)) parsed = cookies;
    else if (cookies && typeof cookies === "object") {
      parsed = Object.entries(cookies).map(([name, value]) => ({ name, value }));
    } else throw new Error("Invalid cookie JSON: 'cookies' must be an array or object");
  }
  const entries = parsed as unknown[];
  if (entries.length === 0) return "";

  const parts: string[] = [];
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`Invalid cookie JSON at index ${i}: expected an object`);
    }
    const record = entry as Record<string, unknown>;

    if (typeof record.name !== "string" || !record.name) {
      throw new Error(`Invalid cookie JSON at index ${i}: missing required field 'name'`);
    }
    if (typeof record.value !== "string") {
      throw new Error(`Invalid cookie JSON at index ${i}: missing required field 'value'`);
    }
    if (!COOKIE_NAME.test(record.name) || /[\x00-\x1f\x7f;]/.test(record.value)) {
      throw new Error(`Invalid cookie JSON at index ${i}: invalid name or value`);
    }
    if (record.domain !== undefined) {
      if (typeof record.domain !== "string" || !record.domain.trim()) {
        throw new Error(`Invalid cookie JSON at index ${i}: invalid domain`);
      }
      if (
        options.domains?.length &&
        !options.domains.some((domain) => matchesCookieDomain(record.domain as string, domain))
      )
        continue;
    }
    const expires = record.expirationDate ?? record.expires;
    if (expires !== undefined && expires !== null && expires !== -1) {
      if (typeof expires !== "number" || !Number.isFinite(expires)) {
        throw new Error(`Invalid cookie JSON at index ${i}: invalid expiry`);
      }
      if (expires * 1000 <= (options.nowMs ?? Date.now())) continue;
    }
    parts.push(`${record.name}=${record.value}`);
  }

  return parts.join("; ");
}

export function normalizeSessionCookieHeader(
  rawValue: string,
  defaultCookieName: string,
  options: CookieNormalizationOptions = {}
): string {
  const stripped = stripCookieInputPrefix(rawValue);
  if (!stripped) return "";
  if (/[\x00-\x1f\x7f]/.test(stripped) && !stripped.startsWith("[") && !stripped.startsWith("{")) {
    throw new Error("Invalid cookie header: control characters are not permitted");
  }

  const jsonResult = parseJsonCookiesToHeader(stripped, options);
  if (jsonResult !== null) {
    return jsonResult;
  }
  if (stripped.startsWith("[") || stripped.startsWith("{")) {
    throw new Error("Invalid cookie JSON: expected a browser cookie export");
  }

  if (stripped.includes("=")) {
    // Some supported providers accept composite credentials, such as Muse's
    // ecto1: WebSocket token alongside cookie pairs. Keep that legacy input;
    // named authentication extraction still ignores unrelated segments.
    return stripped;
  }

  return `${defaultCookieName}=${stripped}`;
}

/**
 * Extract a single cookie's value from whatever the user pasted. Handles:
 *   - bare value:                    "eyJ0eXAi..."          → "eyJ0eXAi..."
 *   - single pair:                   "sso=eyJ0eXAi..."      → "eyJ0eXAi..."
 *   - full DevTools cookie blob:     "foo=1; sso=eyJ...; bar=2" → "eyJ..."
 * Returns "" if a blob is given that does not contain the named cookie.
 */
export function extractCookieValue(rawValue: string, cookieName: string): string {
  let trimmed = stripCookieInputPrefix(rawValue);
  if (!trimmed) return "";
  const jsonHeader = parseJsonCookiesToHeader(trimmed);
  if (jsonHeader !== null) trimmed = jsonHeader;
  else if (trimmed.startsWith("[") || trimmed.startsWith("{")) return "";
  if (/[\x00-\x1f\x7f]/.test(trimmed)) return "";

  if (trimmed.includes(";") || trimmed.includes("=")) {
    for (const part of trimmed.split(";")) {
      const separator = part.indexOf("=");
      if (separator > 0 && part.slice(0, separator).trim() === cookieName) {
        return part.slice(separator + 1).trim();
      }
    }
    return "";
  }

  return trimmed;
}

/**
 * Build the `Cookie` header value for grok.com from whatever the user pasted.
 *
 * Always emits `sso=<value>`. When the pasted blob also carries the paired
 * `sso-rw` write cookie, it is forwarded too — Grok's anti-bot now rejects
 * requests that send `sso` without `sso-rw` (error code 7, #3063). `sso-rw` is
 * only appended when it appears as a real cookie pair in the input, so a bare
 * `sso` value (no `;`/`=`) is never mistaken for an `sso-rw` value.
 *
 * The Cloudflare cookies `cf_clearance` and `__cf_bm` are forwarded the same
 * way when present (#5350) — Cloudflare on grok.com expects the same clearance
 * the browser earned, and AIClient2API forwards them too. Like `sso-rw`, each is
 * appended only when it appears as a real cookie pair, so a bare `sso` blob
 * still produces exactly `sso=<value>` (no phantom cf keys).
 *
 * Returns "" when no `sso` value can be extracted.
 */
export function buildGrokCookieHeader(rawValue: string): string {
  const header = normalizeSessionCookieHeader(rawValue, "sso", { domains: ["grok.com"] });
  const sso = extractCookieValue(header, "sso");
  if (!sso) return "";

  const parts = [`sso=${sso}`];
  for (const name of ["sso-rw", "cf_clearance", "__cf_bm"]) {
    const value = extractCookieValue(header, name);
    if (value) parts.push(`${name}=${value}`);
  }
  return parts.join("; ");
}

/** Extract Kimi Web's current localStorage access token, with legacy cookie compatibility. */
export function extractKimiAccessToken(rawValue: string): string {
  const raw = String(rawValue ?? "").trim();
  if (!raw) return "";

  // 1. JSON dump extraction
  if (raw.startsWith("{") && raw.endsWith("}")) {
    try {
      const parsed = JSON.parse(raw);
      const access = parsed?.access_token || parsed?.token || "";
      if (access && typeof access === "string") return access.trim();
    } catch {}
  }

  const bearer = raw.match(/^(?:authorization:\s*)?bearer\s+([^;\s]+)/i);
  if (bearer) return bearer[1];

  const trimmed = stripCookieInputPrefix(raw);
  for (const key of ["access_token", "kimi-auth"]) {
    const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = trimmed.match(new RegExp(`(?:^|[\\s;])${escaped}=([^;\\s]+)`));
    if (match) return match[1];
  }

  return !trimmed.includes("=") && !trimmed.includes(";") ? trimmed : "";
}

/** Extract Kimi Web refresh_token from key-value, raw string, or localStorage JSON dump. */
export function extractKimiRefreshToken(rawValue: string): string {
  const raw = String(rawValue ?? "").trim();
  if (!raw) return "";

  // 1. JSON dump extraction
  if (raw.startsWith("{") && raw.endsWith("}")) {
    try {
      const parsed = JSON.parse(raw);
      if (parsed?.refresh_token && typeof parsed.refresh_token === "string") {
        return parsed.refresh_token.trim();
      }
    } catch {}
  }

  // 2. Key-value extraction
  const match = raw.match(/(?:^|[\s;])refresh_token=([^;\s]+)/);
  if (match) return match[1];

  return "";
}

/** Extract both access_token and refresh_token from user input. */
export function extractKimiCredentials(rawValue: string): {
  accessToken: string;
  refreshToken: string;
} {
  const raw = String(rawValue ?? "").trim();
  if (!raw) return { accessToken: "", refreshToken: "" };

  return {
    accessToken: extractKimiAccessToken(raw),
    refreshToken: extractKimiRefreshToken(raw),
  };
}

/** @deprecated Use extractKimiAccessToken; retained for existing imports. */
export function extractKimiJwt(rawValue: string): string {
  return extractKimiAccessToken(rawValue);
}

export function normalizeSessionCookieHeaders(
  rawValues: Array<string | null | undefined>,
  defaultCookieName: string
): string[] {
  const seen = new Set<string>();
  const normalizedHeaders: string[] = [];

  for (const rawValue of rawValues) {
    if (typeof rawValue !== "string") continue;
    const normalized = normalizeSessionCookieHeader(rawValue, defaultCookieName);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    normalizedHeaders.push(normalized);
  }

  return normalizedHeaders;
}
