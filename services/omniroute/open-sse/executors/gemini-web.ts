/**
 * GeminiWebExecutor — Gemini Web Session Provider
 *
 * Routes requests through Google Gemini's web interface using browser
 * cookies + Playwright automation. Translates between OpenAI chat
 * completions format and Gemini's web UI.
 *
 * Auth: Cookie-based (__Secure-1PSID + __Secure-1PSIDTS from gemini.google.com)
 * Method: Playwright browser automation
 *
 * Note: Streaming is pseudo-streaming — waits for full Gemini response then
 * sends as single SSE chunk. Gemini's StreamGenerate endpoint returns complete
 * responses, not chunked streams.
 */

import { BaseExecutor, type ExecuteInput } from "./base.ts";
import { buildErrorBody, sanitizeErrorMessage } from "../utils/error.ts";
import { normalizeGeminiCookieInput } from "../utils/geminiCookies.ts";
import { prepareToolMessages } from "../translator/webTools.ts";
import { buildToolModeResponse } from "./chatgptWebTools.ts";
import {
  checkGeminiWebUnsupportedControls,
  GEMINI_WEB_UNSUPPORTED_CONTROL_CODE,
} from "./gemini-web/capabilities.ts";

// ─── Constants ──────────────────────────────────────────────────────────────

const GEMINI_URL = "https://gemini.google.com/app";
export const GEMINI_VIDEOS_URL = "https://gemini.google.com/u/0/videos";

export type VideoOrientation = "landscape" | "portrait" | "square";

export interface ExecuteVideoOptions {
  prompt: string;
  model?: string;
  orientation?: VideoOrientation | null;
  aspectRatio?: string;
  duration?: number;
  responseFormat?: "url" | "b64_json";
  timeoutMs?: number;
  credentials?: ExecuteInput["credentials"];
  signal?: AbortSignal | null;
  log?: ExecuteInput["log"];
  videoUrl?: string;
  engine?: "http" | "playwright" | "auto";
  conversationId?: string;
}

export interface VideoGenerationArtifact {
  url?: string;
  b64_json?: string;
  format: string;
}

import {
  cleanGoogleVideoUrl,
  inspectTextForVideoUrl,
  checkGeminiWebRejectionReason,
  extractWizData,
  fetchGeminiWebWizData,
  buildVeoVideoRpcPayload,
  executeVeoVideoGenerationHttp,
  formatVideoResult,
  getCachedWizData,
  setCachedWizData,
  clearCachedWizData,
  GEMINI_USER_AGENT,
} from "./gemini-web/veoHttp.ts";
export {
  cleanGoogleVideoUrl,
  inspectTextForVideoUrl,
  checkGeminiWebRejectionReason,
  extractWizData,
  fetchGeminiWebWizData,
  buildVeoVideoRpcPayload,
  executeVeoVideoGenerationHttp,
  formatVideoResult,
  getCachedWizData,
  setCachedWizData,
  clearCachedWizData,
  GEMINI_USER_AGENT,
};

import {
  WebSessionRotator,
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
  getRandomPromptLimit,
  prepareWebSessionMessages,
} from "../services/webSessionRotator.ts";
export {
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
  getRandomPromptLimit,
};

export interface GeminiSessionData {
  conversationId?: string;
  responseId?: string;
  choiceId?: string;
}

export const geminiSessionRotator = new WebSessionRotator<GeminiSessionData>();

export function __resetGeminiSessionRotatorForTesting(): void {
  geminiSessionRotator.clear();
}

/**
 * Resolve video orientation ("landscape" | "portrait" | "square") from request parameters.
 */
export function resolveVideoOrientation(
  body: Record<string, unknown>,
  modelOverride?: string
): VideoOrientation | null {
  const raw = String(
    body.orientation || body.aspect_ratio || body.aspectRatio || body.ratio || body.size || ""
  )
    .toLowerCase()
    .trim();

  if (
    raw === "portrait" ||
    raw === "potrait" ||
    raw === "vertical" ||
    raw === "9:16" ||
    raw.includes("9:16") ||
    raw === "1080x1920" ||
    raw === "720x1280"
  ) {
    return "portrait";
  }
  if (
    raw === "landscape" ||
    raw === "horizontal" ||
    raw === "16:9" ||
    raw.includes("16:9") ||
    raw === "1920x1080" ||
    raw === "1280x720"
  ) {
    return "landscape";
  }
  if (raw === "square" || raw === "1:1" || raw.includes("1:1") || raw === "1080x1080") {
    return "square";
  }

  // Also check model name if orientation wasn't explicitly given in params
  const modelStr = String(modelOverride || body.model || "").toLowerCase();
  if (
    modelStr.includes("portrait") ||
    modelStr.includes("potrait") ||
    modelStr.includes("9:16") ||
    modelStr.includes("vertical")
  ) {
    return "portrait";
  }
  if (
    modelStr.includes("landscape") ||
    modelStr.includes("16:9") ||
    modelStr.includes("horizontal")
  ) {
    return "landscape";
  }

  return null;
}

/**
 * Strips provider prefixes ("gweb/", "gemini-web/") and orientation suffixes
 * ("-portrait", "-landscape", "-potrait") to determine the base model ID for
 * Gemini Web chat processing.
 */
export function resolveGeminiWebBaseModel(model?: string | null): string {
  if (!model || typeof model !== "string") return "gemini-2.5-pro";
  let clean = model.trim().replace(/^(?:gweb|gemini-web)\//i, "");
  clean = clean.replace(/-(?:portrait|potrait|landscape)$/i, "");
  if (
    clean === "portrait" ||
    clean === "potrait" ||
    clean === "landscape" ||
    clean === "video" ||
    !clean
  ) {
    return "gemini-2.5-pro";
  }
  return clean;
}

/**
 * Format a formatted video generation prompt with portrait / landscape orientation or duration directives.
 */
export function buildGeminiVideoPrompt(
  prompt: string,
  options?: {
    orientation?: VideoOrientation | null;
    aspectRatio?: string;
    duration?: number;
  }
): string {
  const parts: string[] = [prompt.trim()];
  const orientation =
    options?.orientation ??
    (options?.aspectRatio ? resolveVideoOrientation({ aspect_ratio: options.aspectRatio }) : null);

  if (orientation === "portrait") {
    parts.push("(Orientation: Portrait 9:16 vertical video)");
  } else if (orientation === "landscape") {
    parts.push("(Orientation: Landscape 16:9 widescreen video)");
  } else if (orientation === "square") {
    parts.push("(Orientation: Square 1:1 video)");
  } else if (options?.aspectRatio) {
    parts.push(`(Aspect ratio: ${options.aspectRatio})`);
  }

  if (options?.duration) {
    parts.push(`(Duration: ${options.duration}s)`);
  }

  return parts.join(" ");
}

/**
 * Extract video URL from raw network response text or JSON payload.
 */
export function parseVideoResponseUrl(raw: string): string | null {
  if (!raw || typeof raw !== "string") return null;

  const inspected = inspectTextForVideoUrl(raw);
  if (inspected) return inspected;

  const mp4Match = raw.match(/https:\/\/[^"'\s\\]+\.mp4(?:\?[^"'\s\\]+)?/);
  if (mp4Match) return cleanGoogleVideoUrl(mp4Match[0]);

  const googleVideoMatch = raw.match(
    /https:\/\/[a-zA-Z0-9.-]+\.googleusercontent\.com\/[^\s"'<>\\]+video[^\s"'<>\\]*/i
  );
  if (googleVideoMatch) return cleanGoogleVideoUrl(googleVideoMatch[0]);

  try {
    const data = JSON.parse(raw);
    if (typeof data?.url === "string" && /^https?:\/\//.test(data.url)) {
      return cleanGoogleVideoUrl(data.url);
    }
    if (typeof data?.videoUrl === "string" && /^https?:\/\//.test(data.videoUrl)) {
      return cleanGoogleVideoUrl(data.videoUrl);
    }
    if (Array.isArray(data?.data) && typeof data.data[0]?.url === "string") {
      return cleanGoogleVideoUrl(data.data[0].url);
    }
  } catch {
    // Not valid JSON
  }
  return null;
}

/**
 * Detect whether a user prompt intends to create or generate a video.
 */
export function isVideoGenerationPrompt(prompt: string): boolean {
  if (!prompt || typeof prompt !== "string") return false;
  const p = prompt.trim().toLowerCase();
  return (
    p.startsWith("create video") ||
    p.startsWith("create a video") ||
    p.startsWith("generate video") ||
    p.startsWith("generate a video") ||
    p.startsWith("genrate video") ||
    p.startsWith("genrate a video") ||
    p.startsWith("make a video") ||
    p.startsWith("make video") ||
    p.startsWith("video of:") ||
    p.startsWith("video:") ||
    /\b(create|generate|genrate|make|render|produce|animate)\s+(a\s+)?([a-z0-9\s_-]+)?video\b/i.test(
      p
    ) ||
    /\bvideo\s+(generation|creation)\b/i.test(p)
  );
}

/**
 * Extract clean descriptive prompt from user message by removing command prefixes
 * like "Generate video:", "Genrate video:", "Create video:", etc.
 */
export function extractVideoPromptText(rawPrompt: string): string {
  if (!rawPrompt || typeof rawPrompt !== "string") return "";
  const trimmed = rawPrompt.trim();
  const stripped = trimmed
    .replace(
      /^(?:generate|genrate|create|make|render|produce|animate)\s+(?:a\s+)?video\s*(?:of|about|for)?\s*[:\-–—]?\s*/i,
      ""
    )
    .replace(/^video\s*(?:of|about|for)?\s*[:\-–—]?\s*/i, "");
  return stripped.trim() || trimmed;
}

/**
 * Whether an error came from Playwright failing to launch because the browser binary is not
 * installed (`chromium.launch: Executable doesn't exist at ...`). This is a host/config
 * problem, not a transient upstream fault, so the executor must NOT surface it as a retryable
 * 500 (which marks the account unavailable and loops / trips the provider breaker). See #3516.
 */
export function isMissingBrowserExecutable(message: string): boolean {
  if (!message) return false;
  const lower = message.toLowerCase();
  return (
    lower.includes("executable doesn't exist") ||
    lower.includes("executablenotfound") ||
    lower.includes("playwright install") ||
    (lower.includes("chromium") && lower.includes("download"))
  );
}

// ─── Types ──────────────────────────────────────────────────────────────────

interface GeminiContentPart {
  type?: string;
  text?: string;
  [key: string]: unknown;
}

interface GeminiMessage {
  role: string;
  content: string | Array<string | GeminiContentPart> | null | undefined;
  [key: string]: unknown;
}

interface GeminiRequestBody {
  messages: GeminiMessage[];
  model?: string;
  stream?: boolean;
  [key: string]: unknown;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatChatCompletion(content: string, model: string, finishReason = "stop") {
  return {
    id: `chatcmpl-${Date.now()}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: finishReason }],
    usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  };
}

function formatStreamChunk(content: string, model: string, finishReason: string | null = null) {
  return {
    id: `chatcmpl-${Date.now()}`,
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, delta: content ? { content } : {}, finish_reason: finishReason }],
  };
}

/**
 * Flatten the OpenAI-style multi-turn `messages[]` into the single plain-text
 * prompt typed into the Gemini web UI (#8371).
 *
 * gemini-web drives a real browser page and captures only the FIRST
 * `StreamGenerate` response, so — unlike claude-web — it has no upstream
 * conversation id to thread across turns. It is therefore a stateless,
 * single-turn provider: the previous code forwarded only the last user message
 * (`messages.filter(m => m.role === "user").pop()`), so follow-up questions
 * lost all prior context ("I am in Berlin" → "What should I wear today?" was
 * answered without Berlin). This implements the issue's accepted fallback (b):
 * flatten the full history into one prompt so the web UI still sees the
 * conversation.
 *
 * Single-turn requests are preserved byte-for-byte (only the final user message
 * is returned) — the regression guard for the pre-existing no-tools path.
 * Multi-turn requests emit a labeled transcript:
 *
 *   System:
 *   <system text>
 *
 *   Previous conversation:
 *   User: ...
 *   Assistant: ...
 *
 *   Current user message:
 *   <last user message>
 */
export function buildGeminiPrompt(messages: Array<{ role: string; content: unknown }>): string {
  const textMessages = messages.filter(
    (m) => typeof m.content === "string" && (m.content as string).trim().length > 0
  ) as Array<{ role: string; content: string }>;

  const userMessages = textMessages.filter((m) => m.role === "user");
  const lastUser = userMessages[userMessages.length - 1];
  const lastUserContent = lastUser?.content ?? "";
  const lastUserIdx = lastUser ? textMessages.lastIndexOf(lastUser) : -1;

  // Prior conversation = every user/assistant turn before the final user turn.
  const priorTurns = textMessages.filter(
    (m, i) => i < lastUserIdx && (m.role === "user" || m.role === "assistant")
  );

  // Single-turn (no earlier user/assistant turns): byte-for-byte the original
  // single-message derivation. Do NOT prepend system text here — the old
  // no-tools path ignored a system-only prefix on the first turn.
  if (priorTurns.length === 0) return lastUserContent;

  const systemText = textMessages
    .filter((m) => m.role === "system")
    .map((m) => m.content)
    .join("\n\n");

  const historyLines = priorTurns.map(
    (m) => `${m.role === "assistant" ? "Assistant" : "User"}: ${m.content}`
  );

  const parts: string[] = [];
  if (systemText) parts.push(`System:\n${systemText}`);
  parts.push(`Previous conversation:\n${historyLines.join("\n\n")}`);
  parts.push(`Current user message:\n${lastUserContent}`);
  return parts.join("\n\n");
}

/**
 * Build the plain-text prompt typed into the Gemini web UI when a tool
 * contract is active — the synthetic system message injected by
 * `prepareToolMessages()` prepended to the last user message. gemini-web
 * only ever sends a single flat string (no native message array), so the
 * tool contract and the user's ask are concatenated (#7286).
 */
export function buildGeminiToolPrompt(
  effectiveMessages: Array<{ role: string; content: unknown }>
): string {
  const toolSystemMsg = effectiveMessages.find((m) => m.role === "system");
  const lastUserMsg = [...effectiveMessages].reverse().find((m) => m.role === "user");
  const userText = typeof lastUserMsg?.content === "string" ? lastUserMsg.content : "";
  const toolPrompt = typeof toolSystemMsg?.content === "string" ? toolSystemMsg.content : "";
  return toolPrompt ? `${toolPrompt}\n\n${userText}` : userText;
}

/**
 * Tool mode: wrap the buffered Gemini response text in the standard OpenAI
 * completion shape, then delegate to the shared `buildToolModeResponse()`
 * (`chatgptWebTools.ts`) — parses `<tool>{...}</tool>` blocks out of the
 * text into `tool_calls` (malformed JSON degrades to ordinary `content`,
 * never throws) and replays either buffered JSON or a terminal SSE chunk
 * depending on `stream` (#7286). Exported standalone so the branching logic
 * is testable without a full Playwright mock.
 */
export async function buildGeminiToolResponse(
  responseText: string,
  requestedTools: unknown,
  stream: boolean,
  model: string,
  cid: string,
  created: number
): Promise<Response> {
  const bufferedJson = new Response(JSON.stringify(formatChatCompletion(responseText, model)), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  return buildToolModeResponse(bufferedJson, requestedTools, stream, {
    cid,
    created,
    model,
    idSeed: "gwe",
  });
}

/**
 * Parse cookie string, stripping attributes (Path, Domain, Expires, etc.)
 * Input: full browser cookie string or just "name=value; name2=value2"
 * Output: array of { name, value } pairs
 */
function parseCookies(raw: string): Array<{ name: string; value: string }> {
  return raw
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const eqIdx = part.indexOf("=");
      if (eqIdx === -1) return null;
      const name = part.substring(0, eqIdx).trim();
      const value = part.substring(eqIdx + 1).trim();
      // Skip cookie attributes that aren't name=value pairs
      if (!name || !value) return null;
      const lowerName = name.toLowerCase();
      if (
        ["path", "domain", "expires", "max-age", "secure", "httponly", "samesite"].includes(
          lowerName
        )
      ) {
        return null;
      }
      return { name, value };
    })
    .filter(Boolean) as Array<{ name: string; value: string }>;
}

/**
 * Parse Gemini StreamGenerate response text.
 *
 * Response format:
 *   )]}'
 *   <length>
 *   [["wrb.fr", null, "<JSON string>"]]
 *   <length>
 *   [["wrb.fr", null, "<JSON string>"]]
 *
 * The JSON string contains nested array: inner[4][0][1] = ["text chunks"].
 * Each wrb.fr line is a CUMULATIVE snapshot of the whole answer generated so
 * far (not an independent delta), so we keep only the text from the LAST
 * frame that yields non-empty text instead of concatenating every frame —
 * concatenating would reproduce the same growing text with each snapshot
 * (see #7163).
 */
export function parseStreamResponse(raw: string): string {
  const lines = raw.split("\n");
  let lastText = "";

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line === ")]}'" || /^\d+$/.test(line)) continue;
    if (!line.includes("wrb.fr")) continue;
    try {
      const arr = JSON.parse(line);
      if (!Array.isArray(arr) || !Array.isArray(arr[0]) || arr[0][0] !== "wrb.fr") continue;
      const payload = arr[0]?.[2];
      if (typeof payload !== "string") continue;
      const inner = JSON.parse(payload);
      // Defensive: check each level before accessing
      const responseArray = inner?.[4]?.[0]?.[1];
      if (!Array.isArray(responseArray)) continue;
      const text = responseArray.filter((c: unknown) => typeof c === "string").join("");
      if (text) lastText = text;
    } catch {
      // Skip unparseable lines
    }
  }
  return lastText;
}

function readCredentialString(value: unknown): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : "";
}

function readProviderSpecificString(
  providerSpecificData: unknown,
  keys: readonly string[]
): string {
  if (
    !providerSpecificData ||
    typeof providerSpecificData !== "object" ||
    Array.isArray(providerSpecificData)
  ) {
    return "";
  }
  const data = providerSpecificData as Record<string, unknown>;
  for (const key of keys) {
    const value = readCredentialString(data[key]);
    if (value) return value;
  }
  return "";
}

/**
 * Merge rotated Google session cookies read back from the live Playwright
 * cookie jar into the original cookie string. Google's session architecture
 * uses ~15 interdependent cookies with different rotation schedules:
 *
 *   - `__Secure-1PSIDTS` / `__Secure-3PSIDTS` — timestamp tokens, rotated
 *     every few minutes. If stale, Google silently downgrades to guest mode.
 *   - `__Secure-1PSIDRTS` / `__Secure-3PSIDRTS` — refresh timestamp tokens,
 *     very short-lived (~10 min). Missing = guest mode after expiry.
 *   - `SIDCC` / `__Secure-1PSIDCC` / `__Secure-3PSIDCC` — session confirmers,
 *     rotated every ~30 min.
 *   - `SID` / `HSID` / `APISID` / `SAPISID` / `NID` — long-lived but CAN be
 *     rotated during security events.
 *
 * Rather than maintaining a fragile whitelist, we persist ALL .google.com
 * cookies from the jar that are NOT short-lived analytics/consent cookies
 * (those are filtered by the IGNORE set). This mirrors what a real browser
 * does and prevents the guest-mode fallback that occurs when any single
 * auth cookie goes stale (#7676).
 */
export function mergeRotatedGeminiCookies(
  originalCookie: string,
  jarCookies: Array<{ name: string; value: string; domain?: string }>
): string {
  // Analytics / consent / tracking cookies that should NOT be persisted as
  // credentials. Everything else from the .google.com jar is auth-relevant.
  const IGNORE_PREFIXES = ["_ga", "_gcl", "AEC", "SEARCH_SAMESITE", "COMPASS", "NID"];

  const isAuthCookie = (name: string) =>
    !IGNORE_PREFIXES.some(
      (prefix) => name === prefix || name.startsWith(`${prefix}_`) || name.startsWith(`${prefix}.`)
    );

  const jarByName = new Map(
    jarCookies
      .filter((c) => isAuthCookie(c.name))
      .map((c) => [c.name, c.value])
  );

  const pairs = parseCookies(originalCookie);
  const seen = new Set<string>();
  const merged = pairs.map(({ name, value }) => {
    seen.add(name);
    if (jarByName.has(name)) {
      return { name, value: jarByName.get(name) as string };
    }
    return { name, value };
  });

  // Add any auth cookies from the jar that weren't in the original string
  // (e.g. __Secure-1PSIDRTS that Google set during this session).
  for (const [name, value] of jarByName) {
    if (!seen.has(name)) {
      merged.push({ name, value });
    }
  }

  return merged.map(({ name, value }) => `${name}=${value}`).join("; ");
}

function resolveGeminiWebCookie(credentials: ExecuteInput["credentials"]): string {
  const directCookie =
    readCredentialString(credentials?.apiKey) ||
    readCredentialString((credentials as Record<string, unknown> | undefined)?.cookie);
  if (directCookie) return normalizeGeminiCookieInput(directCookie);

  const providerSpecificData = credentials?.providerSpecificData;
  const cookie = readProviderSpecificString(providerSpecificData, ["cookie"]);
  if (cookie) return normalizeGeminiCookieInput(cookie);

  const psid = readProviderSpecificString(providerSpecificData, ["__Secure-1PSID"]);
  const psidts = readProviderSpecificString(providerSpecificData, ["__Secure-1PSIDTS"]);
  return [
    psid ? normalizeGeminiCookieInput(psid, "__Secure-1PSID") : "",
    psidts ? normalizeGeminiCookieInput(psidts, "__Secure-1PSIDTS") : "",
  ]
    .filter(Boolean)
    .join("; ");
}

// ─── Executor ───────────────────────────────────────────────────────────────

export class GeminiWebExecutor extends BaseExecutor {
  constructor() {
    super("gemini-web", { id: "gemini-web", baseUrl: GEMINI_URL });
  }

  /**
   * testConnection — validates the cookie format without making a network call
   * or launching Playwright. Returns true when the cookie is non-empty and
   * contains at least one name=value pair with a non-empty value. This is a
   * lightweight pre-check before the browser automation path; full session
   * validation is done by validateGeminiWebProvider in the connection test
   * flow (#9407).
   */
  async testConnection(
    credentials: Record<string, unknown>,
    _signal?: AbortSignal
  ): Promise<boolean> {
    try {
      const cookie = resolveGeminiWebCookie(credentials as unknown as ExecuteInput["credentials"]);
      if (!cookie) return false;
      const pairs = parseCookies(cookie);
      return pairs.some((p) => p.value.length > 0);
    } catch {
      return false;
    }
  }

  /**
   * Read the live Playwright cookie jar back after a successful run and, if
   * Google rotated any session cookies (PSID, PSIDTS, PSIDRTS, SIDCC, etc.),
   * forward the merged cookie string through onCredentialsRefreshed so it gets
   * persisted to the encrypted provider_connections.api_key field. All Google
   * auth cookies are captured (analytics/consent filtered out). A persistence
   * failure must never fail the user-facing response (#7676).
   */
  private async persistRotatedCookies(
    context: import("playwright").BrowserContext,
    cookie: string,
    credentials: ExecuteInput["credentials"],
    onCredentialsRefreshed: ExecuteInput["onCredentialsRefreshed"],
    log: ExecuteInput["log"]
  ): Promise<void> {
    if (!onCredentialsRefreshed) return;
    try {
      const jarCookies = await context.cookies();
      const mergedCookie = mergeRotatedGeminiCookies(cookie, jarCookies);
      if (mergedCookie && mergedCookie !== cookie) {
        await onCredentialsRefreshed({ ...credentials, apiKey: mergedCookie });
      }
    } catch (err) {
      log?.warn?.(
        "GEMINI-WEB",
        `Failed to persist rotated cookie: ${err instanceof Error ? err.message : String(err)}`
      );
    }
  }

  /**
   * Execute video generation on https://gemini.google.com/u/0/videos via Playwright browser automation.
   * Fallback engine if pure HTTP RPC is unavailable.
   */
  async executeVideoGenerationPlaywright(input: ExecuteVideoOptions): Promise<{
    success: boolean;
    status: number;
    data?: VideoGenerationArtifact[];
    error?: string;
  }> {
    const {
      prompt,
      model: _model,
      orientation,
      aspectRatio,
      duration,
      responseFormat = "url",
      timeoutMs = 120_000,
      credentials,
      signal,
      log: _log,
      videoUrl = GEMINI_VIDEOS_URL,
    } = input;

    const cookie = resolveGeminiWebCookie(credentials);
    if (!cookie) {
      return {
        success: false,
        status: 401,
        error: "Missing Gemini cookies (__Secure-1PSID)",
      };
    }

    const effectivePrompt = buildGeminiVideoPrompt(prompt, { orientation, aspectRatio, duration });
    if (!effectivePrompt) {
      return {
        success: false,
        status: 400,
        error: "Prompt is required for Gemini Web video generation",
      };
    }

    let browser: import("playwright").Browser | null = null;
    let abortBrowser: (() => void) | null = null;
    try {
      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }
      const { chromium } = await import("playwright");
      browser = await chromium.launch({ headless: true });
      abortBrowser = () => {
        void browser?.close().catch(() => {});
      };
      signal?.addEventListener("abort", abortBrowser, { once: true });

      const context = await browser.newContext({ userAgent: GEMINI_USER_AGENT });
      const cookiePairs = parseCookies(cookie);
      await context.addCookies(
        cookiePairs.map(({ name, value }) => {
          if (name.startsWith("__Host-")) {
            return {
              name,
              value,
              url: "https://gemini.google.com",
              path: "/",
              secure: true,
            };
          }
          return {
            name,
            value,
            domain: ".google.com",
            path: "/",
            secure: true,
          };
        })
      );

      const page = await context.newPage();

      let detectedVideoUrl: string | null = null;
      let videoResolve: (() => void) | null = null;
      const videoPromise = new Promise<void>((resolve) => {
        videoResolve = resolve;
      });

      // Intercept network responses for video URLs
      page.on("response", async (resp: import("playwright").Response) => {
        try {
          const url = resp.url();
          const headers = resp.headers?.() ?? {};
          const contentType = headers["content-type"] || "";

          if (
            contentType.includes("video/") ||
            url.includes(".mp4") ||
            url.includes("googlevideo.com")
          ) {
            if (!detectedVideoUrl && /^https?:\/\//.test(url)) {
              detectedVideoUrl = cleanGoogleVideoUrl(url);
              videoResolve?.();
            }
          } else if (
            url.includes("GenerateVideo") ||
            url.includes("StreamGenerate") ||
            url.includes("video") ||
            url.includes("batchexecute")
          ) {
            const raw = await resp.text().catch(() => "");
            const parsed = parseVideoResponseUrl(raw);
            if (parsed && !detectedVideoUrl) {
              detectedVideoUrl = parsed;
              videoResolve?.();
            }
          }
        } catch {
          /* ignore response interception errors */
        }
      });

      await page.goto(videoUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }
      await page.waitForTimeout(500);

      // Apply portrait / landscape controls in UI if available
      const resolvedOrientation =
        orientation ??
        (aspectRatio ? resolveVideoOrientation({ aspect_ratio: aspectRatio }) : null);
      if (resolvedOrientation) {
        try {
          const selector =
            resolvedOrientation === "portrait"
              ? "button[aria-label*='portrait' i], button[aria-label*='9:16' i], [data-value*='portrait' i], [data-value='9:16']"
              : resolvedOrientation === "landscape"
                ? "button[aria-label*='landscape' i], button[aria-label*='16:9' i], [data-value*='landscape' i], [data-value='16:9']"
                : "button[aria-label*='square' i], button[aria-label*='1:1' i], [data-value*='square' i], [data-value='1:1']";
          const orientationBtn = await page.$(selector);
          if (orientationBtn) {
            await orientationBtn.click();
            await page.waitForTimeout(100);
          }
        } catch {
          /* UI orientation control is optional/non-blocking */
        }
      }

      // Locate prompt input element
      const inputEl = await page.waitForSelector(
        "textarea, .ql-editor, [contenteditable='true'], input[type='text']",
        { timeout: 15000 }
      );
      await inputEl.click();
      if (typeof page.keyboard.insertText === "function") {
        await page.keyboard.insertText(effectivePrompt);
      } else {
        await page.keyboard.type(effectivePrompt, { delay: 2 });
      }
      await page.waitForTimeout(100);

      // Submit prompt via button or Enter key
      const sendBtn = await page.$(
        "button[aria-label*='generate' i], button[aria-label*='create' i], button[aria-label*='send' i], button[type='submit']"
      );
      if (sendBtn) {
        await sendBtn.click();
      } else {
        await page.keyboard.press("Enter");
      }

      // Poll page DOM for generated video element while waiting
      const domPollPromise = (async () => {
        const startPoll = Date.now();
        while (Date.now() - startPoll < timeoutMs) {
          if (detectedVideoUrl || signal?.aborted) break;
          try {
            const videoSrc = await page.evaluate(() => {
              const video = document.querySelector("video");
              if (video && video.src && /^https?:\/\//.test(video.src)) return video.src;
              const source = document.querySelector("video source");
              if (
                source &&
                (source as HTMLSourceElement).src &&
                /^https?:\/\//.test((source as HTMLSourceElement).src)
              ) {
                return (source as HTMLSourceElement).src;
              }
              const downloadLink = document.querySelector(
                "a[download][href*='http'], a[href*='.mp4']"
              );
              if (downloadLink && (downloadLink as HTMLAnchorElement).href) {
                return (downloadLink as HTMLAnchorElement).href;
              }
              return null;
            });
            if (videoSrc) {
              detectedVideoUrl = cleanGoogleVideoUrl(videoSrc);
              break;
            }
          } catch {
            /* ignore page eval errors during DOM poll */
          }
          await page.waitForTimeout(1000);
        }
      })();

      await Promise.race([videoPromise, domPollPromise, page.waitForTimeout(timeoutMs)]);

      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }

      if (!detectedVideoUrl) {
        return {
          success: false,
          status: 502,
          error: "Gemini Web completed without producing a video artifact",
        };
      }

      return formatVideoResult(detectedVideoUrl, responseFormat, cookie, signal);
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Unknown error";
      if (isMissingBrowserExecutable(rawMessage)) {
        return {
          success: false,
          status: 503,
          error:
            "Gemini Web video generation requires the Playwright Chromium browser, which is not installed. " +
            "Run `npx playwright install chromium` on the host (or rebuild the Docker image with browsers).",
        };
      }
      return {
        success: false,
        status: 500,
        error: sanitizeErrorMessage(rawMessage),
      };
    } finally {
      if (abortBrowser) signal?.removeEventListener("abort", abortBrowser);
      if (browser) {
        try {
          await browser.close();
        } catch {
          /* ignore */
        }
      }
    }
  }

  /**
   * Execute video generation using Google's reverse-engineered Veo RPC pipeline (pure HTTP).
   * Dispatches StreamGenerate with Tool Code 16 and polls hNvQHb for completion.
   */
  async executeVideoGenerationHttp(input: ExecuteVideoOptions): Promise<{
    success: boolean;
    status: number;
    data?: VideoGenerationArtifact[];
    error?: string;
    conversationId?: string;
  }> {
    const cookie = resolveGeminiWebCookie(input.credentials);
    if (!cookie) {
      return {
        success: false,
        status: 401,
        error: "Missing Gemini cookies (__Secure-1PSID)",
      };
    }
    return executeVeoVideoGenerationHttp(input, cookie);
  }

  /**
   * Execute video generation on Gemini Web.
   * Defaults to HTTP RPC pipeline (matching scripts/ad-hoc/gemini-veo-harvester.js)
   * which creates the chat page in Gemini Web and dispatches to Google Veo tool 16.
   * Playwright browser automation is available as opt-in via engine: "playwright".
   */
  async executeVideoGeneration(input: ExecuteVideoOptions): Promise<{
    success: boolean;
    status: number;
    data?: VideoGenerationArtifact[];
    error?: string;
    conversationId?: string;
  }> {
    const { prompt, credentials } = input;
    const cookie = resolveGeminiWebCookie(credentials);
    if (!cookie) {
      return {
        success: false,
        status: 401,
        error: "Missing Gemini cookies (__Secure-1PSID)",
      };
    }
    if (!prompt?.trim()) {
      return {
        success: false,
        status: 400,
        error: "Prompt is required for Gemini Web video generation",
      };
    }

    // Explicit Playwright engine — browser automation path
    if (input.engine === "playwright") {
      try {
        return await this.executeVideoGenerationPlaywright(input);
      } catch (pwErr) {
        return {
          success: false,
          status: 500,
          error: sanitizeErrorMessage(pwErr instanceof Error ? pwErr.message : String(pwErr)),
        };
      }
    }

    // Default: HTTP RPC pipeline (matching gemini-veo-harvester.js)
    try {
      return await this.executeVideoGenerationHttp(input);
    } catch (httpErr) {
      return {
        success: false,
        status: 500,
        error: sanitizeErrorMessage(httpErr instanceof Error ? httpErr.message : String(httpErr)),
      };
    }
  }

  async execute(input: ExecuteInput) {
    const { model, body, stream, credentials, signal, log, onCredentialsRefreshed } = input;
    const requestBody = body as GeminiRequestBody;

    // #video-mode: if video mode is explicitly requested on execute() via /v1/videos/generations
    const isExplicitVideo = (body as Record<string, unknown>)?.x_gemini_web_video_mode === true;
    const cleanModel = typeof model === "string" ? model.trim().toLowerCase() : "";

    // Dedicated pure video model IDs (e.g. portrait, landscape, veo)
    const isDedicatedVideoModel =
      cleanModel === "portrait" ||
      cleanModel === "potrait" ||
      cleanModel === "landscape" ||
      cleanModel === "veo" ||
      cleanModel === "gweb/portrait" ||
      cleanModel === "gweb/potrait" ||
      cleanModel === "gweb/landscape" ||
      cleanModel === "gemini-web/portrait" ||
      cleanModel === "gemini-web/landscape" ||
      cleanModel.endsWith("-video");

    let promptText =
      typeof (body as Record<string, unknown>)?.prompt === "string"
        ? ((body as Record<string, unknown>).prompt as string)
        : "";
    if (!promptText && Array.isArray(requestBody.messages)) {
      const userMessages = requestBody.messages.filter((m) => m.role === "user");
      const lastUserMsg = userMessages[userMessages.length - 1];
      if (lastUserMsg) {
        if (typeof lastUserMsg.content === "string") {
          promptText = lastUserMsg.content;
        } else if (Array.isArray(lastUserMsg.content)) {
          promptText = lastUserMsg.content
            .map((part) =>
              typeof part === "string" ? part : (part as { text?: string })?.text || ""
            )
            .join(" ")
            .trim();
        }
      }
    }

    const promptStr = String(promptText).trim();
    const hasExplicitVideoPrompt = isVideoGenerationPrompt(promptStr);

    // Common short casual greetings or conversational queries should NOT trigger video generation
    const isCasualNonVideoChat =
      /^(hi|hii|hiii|hello|hey|hey there|greetings|good morning|good evening|good afternoon|who are you|help|test)\b/i.test(
        promptStr
      ) &&
      promptStr.length < 35 &&
      !hasExplicitVideoPrompt;

    const isVideoIntent =
      !isExplicitVideo &&
      !isCasualNonVideoChat &&
      (hasExplicitVideoPrompt || (isDedicatedVideoModel && promptStr.length > 0));

    const cookie = resolveGeminiWebCookie(credentials);
    if (!cookie) {
      return {
        response: new Response(JSON.stringify({ error: "Missing Gemini cookies" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
        url: GEMINI_URL,
        headers: {},
        transformedBody: body,
      };
    }

    // Step 1: acquire conversation session (antiban 5-7 prompt reuse, never delete)
    const baseModel = resolveGeminiWebBaseModel(model);
    const userScope =
      credentials?.connectionId?.trim() ||
      parseCookies(cookie).find((c) => c.name === "__Secure-1PSID")?.value ||
      cookie;
    const accountScope = `${userScope}:${baseModel}`;
    const minPrompts =
      typeof credentials?.providerSpecificData?.minPromptsPerPage === "number"
        ? credentials.providerSpecificData.minPromptsPerPage
        : DEFAULT_PAGE_MIN_PROMPTS;
    const maxPrompts =
      typeof credentials?.providerSpecificData?.maxPromptsPerPage === "number"
        ? credentials.providerSpecificData.maxPromptsPerPage
        : DEFAULT_PAGE_MAX_PROMPTS;

    const sessionResult = await geminiSessionRotator.acquire({
      scopeKey: accountScope,
      minPrompts,
      maxPrompts,
      createFn: async () => ({
        conversationId: undefined,
      }),
    });

    if (isExplicitVideo || isVideoIntent) {
      const cleanPrompt = extractVideoPromptText(String(promptText));
      const resolvedOrientation = resolveVideoOrientation(
        body as Record<string, unknown>,
        model
      );
      const videoResult = await this.executeVideoGeneration({
        prompt: cleanPrompt,
        model,
        orientation: resolvedOrientation,
        aspectRatio:
          typeof (body as Record<string, unknown>)?.aspect_ratio === "string"
            ? ((body as Record<string, unknown>).aspect_ratio as string)
            : resolvedOrientation === "portrait"
              ? "9:16"
              : resolvedOrientation === "landscape"
                ? "16:9"
                : undefined,
        conversationId: sessionResult.data.conversationId,
        credentials,
        signal,
        log,
      });

      if (videoResult.success && videoResult.conversationId) {
        sessionResult.data.conversationId = videoResult.conversationId;
      } else if (!videoResult.success) {
        sessionResult.data.conversationId = undefined;
      }

      if (!videoResult.success) {
        if (isExplicitVideo) {
          return {
            response: new Response(
              JSON.stringify({ error: videoResult.error || "Gemini Web video generation failed" }),
              { status: videoResult.status || 500, headers: { "Content-Type": "application/json" } }
            ),
            url: GEMINI_VIDEOS_URL,
            headers: {},
            transformedBody: body,
          };
        }
        // In chat mode (video intent detected from prompt prefix):
        // Return clear error response directly rather than falling through to Playwright regular chat
        log?.warn?.(
          "GEMINI-WEB",
          `Video intent generation failed: ${videoResult.error}`
        );
        const failMessage = `Video generation failed: ${videoResult.error || "Unable to generate video"}`;
        const modelId = model || "gemini-web";
        if (stream) {
          const encoder = new TextEncoder();
          const readable = new ReadableStream(
            {
              start(controller) {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify(formatStreamChunk(failMessage, modelId))}\n\n`
                  )
                );
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify(formatStreamChunk("", modelId, "stop"))}\n\n`
                  )
                );
                controller.enqueue(encoder.encode("data: [DONE]\n\n"));
                controller.close();
              },
            },
            { highWaterMark: 16384 }
          );
          return {
            response: new Response(readable, {
              status: 200,
              headers: {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                Connection: "keep-alive",
              },
            }),
            url: GEMINI_URL,
            headers: {},
            transformedBody: body,
          };
        }

        return {
          response: new Response(JSON.stringify(formatChatCompletion(failMessage, modelId)), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
          url: GEMINI_URL,
          headers: {},
          transformedBody: body,
        };
      } else {
        if (isExplicitVideo) {
          return {
            response: new Response(
              JSON.stringify({
                created: Math.floor(Date.now() / 1000),
                data: videoResult.data,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            ),
            url: GEMINI_VIDEOS_URL,
            headers: {},
            transformedBody: body,
          };
        }

        // Return chat completion format with video.
        // Google's contribution.usercontent.google.com URLs require session cookies,
        // so proxy-download the video server-side and return a base64 data URI.
        const rawVideoUrl = videoResult.data?.[0]?.url || "";
        const videoFormat = videoResult.data?.[0]?.format || "mp4";
        let servableVideoUrl = rawVideoUrl;

        if (rawVideoUrl && rawVideoUrl.includes("usercontent.google.com")) {
          const sessionCookie = resolveGeminiWebCookie(credentials);
          if (sessionCookie) {
            try {
              const proxyResp = await fetch(rawVideoUrl, {
                headers: {
                  "User-Agent": GEMINI_USER_AGENT,
                  Cookie: sessionCookie,
                },
                signal: signal ?? undefined,
              });
              if (proxyResp.ok) {
                const buf = await proxyResp.arrayBuffer();
                const b64 = Buffer.from(buf).toString("base64");
                servableVideoUrl = `data:video/mp4;base64,${b64}`;
                log?.info?.(
                  "GEMINI-WEB",
                  `Video proxy-downloaded (${Math.round(buf.byteLength / 1024)}KB) — serving as data URI`
                );
              } else {
                log?.warn?.(
                  "GEMINI-WEB",
                  `Video proxy download failed: HTTP ${proxyResp.status}. Returning raw URL as fallback.`
                );
              }
            } catch (dlErr) {
              log?.warn?.(
                "GEMINI-WEB",
                `Video proxy download error: ${dlErr instanceof Error ? dlErr.message : String(dlErr)}. Returning raw URL as fallback.`
              );
            }
          }
        }

        const markdownResponse = `Here is your generated video:\n\n[Download Video (${videoFormat})](${servableVideoUrl})\n\n<video controls src="${servableVideoUrl}" width="100%"></video>`;
        const modelId = model || "gemini-web";

        if (stream) {
          const encoder = new TextEncoder();
          const readable = new ReadableStream(
            {
              start(controller) {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify(formatStreamChunk(markdownResponse, modelId))}\n\n`
                  )
                );
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify(formatStreamChunk("", modelId, "stop"))}\n\n`
                  )
                );
                controller.enqueue(encoder.encode("data: [DONE]\n\n"));
                controller.close();
              },
            },
            { highWaterMark: 16384 }
          );
          return {
            response: new Response(readable, {
              status: 200,
              headers: {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                Connection: "keep-alive",
              },
            }),
            url: GEMINI_VIDEOS_URL,
            headers: {},
            transformedBody: body,
          };
        }

        return {
          response: new Response(JSON.stringify(formatChatCompletion(markdownResponse, modelId)), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
          url: GEMINI_VIDEOS_URL,
          headers: {},
          transformedBody: body,
        };
      }
    }

    // #9356: fail fast on controls this provider cannot honor (reasoning_effort
    // above "minimal", forced tool_choice). Runs before the credential check and
    // before Playwright launches — the request is unservable no matter which
    // cookie is used, and answering 200 with ordinary prose made agents believe
    // their reasoning/tool requirements had been met. See ./gemini-web/capabilities.ts.
    const violation = checkGeminiWebUnsupportedControls(body as Record<string, unknown>);
    if (violation) {
      log?.warn?.(
        "GEMINI-WEB",
        `Rejected request: "${violation.param}" is not supported by this provider`
      );
      return {
        response: new Response(
          JSON.stringify(
            buildErrorBody(400, violation.message, null, {
              type: "invalid_request_error",
              code: GEMINI_WEB_UNSUPPORTED_CONTROL_CODE,
            })
          ),
          { status: 400, headers: { "Content-Type": "application/json" } }
        ),
        url: GEMINI_URL,
        headers: {},
        transformedBody: body,
      };
    }



    const messages = prepareWebSessionMessages(requestBody.messages || [], sessionResult.rotated) as typeof requestBody.messages;
    const { hasTools, requestedTools, effectiveMessages } = prepareToolMessages(
      body as Record<string, unknown>,
      messages
    );

    // hasTools === false: flatten the full multi-turn history into the single
    // prompt so gemini-web (a stateless web-cookie provider that captures only
    // the first StreamGenerate response) preserves prior context across turns
    // (#8371). Single-turn requests stay byte-for-byte identical to the original
    // derivation, keeping the #7286 no-tools regression guard intact.
    const prompt = hasTools
      ? buildGeminiToolPrompt(effectiveMessages)
      : buildGeminiPrompt(messages);

    if (!prompt) {
      return {
        response: new Response(JSON.stringify({ error: "No user message found" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
        url: GEMINI_URL,
        headers: {},
        transformedBody: body,
      };
    }

    let browser: any = null;
    let abortBrowser: (() => void) | null = null;
    try {
      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }
      const { chromium } = await import("playwright");
      browser = await chromium.launch({
        headless: true,
        args: [
          "--disable-blink-features=AutomationControlled",
          "--no-sandbox",
          "--disable-dev-shm-usage",
        ],
      });
      abortBrowser = () => {
        void browser?.close().catch(() => {});
      };
      signal?.addEventListener("abort", abortBrowser, { once: true });

      const context = await browser.newContext({ userAgent: GEMINI_USER_AGENT });
      if (typeof context.addInitScript === "function") {
        await context.addInitScript(() => {
          try {
            Object.defineProperty(navigator, "webdriver", { get: () => undefined });
          } catch {
            /* ignore */
          }
        });
      }

      // Parse cookies — strips attributes like Path, Domain, Expires
      const cookiePairs = parseCookies(cookie);
      await context.addCookies(
        cookiePairs.map(({ name, value }) => {
          if (name.startsWith("__Host-")) {
            return {
              name,
              value,
              url: "https://gemini.google.com",
              path: "/",
              secure: true,
            };
          }
          return {
            name,
            value,
            domain: ".google.com",
            path: "/",
            secure: true,
          };
        })
      );

      const page = await context.newPage();

      // Capture first StreamGenerate response
      let responseText = "";
      let captured = false;
      const responsePromise = new Promise<void>((resolve) => {
        page.on("response", async (resp: any) => {
          if (!resp.url().includes("StreamGenerate")) return;
          if (captured) return;
          // Resolve even if reading the body throws, so the flow falls through
          // to the "No response from Gemini" 502 instead of burning the full
          // wait window.
          captured = true;
          try {
            const raw = await resp.text();
            responseText = parseStreamResponse(raw);
          } catch {
            /* ignore */
          }
          resolve();
        });
      });

      const targetUrl =
        sessionResult.reused && sessionResult.data.conversationId
          ? `${GEMINI_URL}/${sessionResult.data.conversationId}`
          : GEMINI_URL;

      await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 20000 });
      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }
      await page.waitForTimeout(3000);

      // Type and send message
      const inputEl = await page.waitForSelector(".ql-editor, [contenteditable='true']", {
        timeout: 10000,
      });
      await inputEl.click();
      if (typeof page.keyboard.insertText === "function") {
        await page.keyboard.insertText(prompt);
      } else {
        await page.keyboard.type(prompt, { delay: 10 });
      }
      await page.waitForTimeout(300);
      await page.keyboard.press("Enter");

      await Promise.race([responsePromise, page.waitForTimeout(30000)]);
      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }

      // Capture and persist conversationId from page URL (never delete the session page)
      try {
        const currentUrl = typeof page.url === "function" ? page.url() : "";
        if (currentUrl) {
          const urlMatch =
            currentUrl.match(/app\/([a-zA-Z0-9_-]{6,})/i) ||
            currentUrl.match(/c_[a-zA-Z0-9_-]{6,}/i);
          if (urlMatch) {
            sessionResult.data.conversationId = urlMatch[1] || urlMatch[0];
          }
        }
      } catch {
        /* ignore */
      }

      if (!responseText) {
        return {
          response: new Response(JSON.stringify({ error: "No response from Gemini" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
          }),
          url: GEMINI_URL,
          headers: {},
          transformedBody: body,
        };
      }

      if (checkGeminiWebRejectionReason(responseText) === "internal_error") {
        sessionResult.data.conversationId = undefined;
      }

      await this.persistRotatedCookies(context, cookie, credentials, onCredentialsRefreshed, log);

      const modelId = model || baseModel;

      if (hasTools) {
        const cid = `chatcmpl-gwe-${crypto.randomUUID().slice(0, 12)}`;
        const created = Math.floor(Date.now() / 1000);
        const toolResponse = await buildGeminiToolResponse(
          responseText,
          requestedTools,
          Boolean(stream),
          modelId,
          cid,
          created
        );
        return { response: toolResponse, url: GEMINI_URL, headers: {}, transformedBody: body };
      }

      if (stream) {
        // Pseudo-streaming: send complete response as single SSE chunk
        // Gemini's StreamGenerate returns complete responses, not chunked streams
        const encoder = new TextEncoder();
        const readable = new ReadableStream(
          {
            start(controller) {
              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify(formatStreamChunk(responseText, modelId))}\n\n`
                )
              );
              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify(formatStreamChunk("", modelId, "stop"))}\n\n`
                )
              );
              controller.enqueue(encoder.encode("data: [DONE]\n\n"));
              controller.close();
            },
          },
          { highWaterMark: 16384 }
        );
        return {
          response: new Response(readable, {
            status: 200,
            headers: {
              "Content-Type": "text/event-stream",
              "Cache-Control": "no-cache",
              Connection: "keep-alive",
            },
          }),
          url: GEMINI_URL,
          headers: {},
          transformedBody: body,
        };
      }

      return {
        response: new Response(JSON.stringify(formatChatCompletion(responseText, modelId)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
        url: GEMINI_URL,
        headers: {},
        transformedBody: body,
      };
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Unknown error";
      // #3516: a missing Playwright browser is a host/config problem, not a transient upstream
      // fault. Surface an actionable error and tag it with the connection-cooldown hint so
      // accountFallback skips the provider circuit breaker and applies a short, non-exponential
      // cooldown instead of looping on a retryable 500.
      if (isMissingBrowserExecutable(rawMessage)) {
        return {
          response: new Response(
            JSON.stringify({
              error:
                "Gemini Web requires the Playwright Chromium browser, which is not installed. " +
                "Run `npx playwright install chromium` on the host (or rebuild the Docker image with browsers).",
            }),
            {
              status: 503,
              headers: {
                "Content-Type": "application/json",
                "X-Omni-Fallback-Hint": "connection_cooldown",
              },
            }
          ),
          url: GEMINI_URL,
          headers: {},
          transformedBody: body,
        };
      }
      // #9407: Playwright selector/click timeout errors are terminal — they indicate
      // the page DOM does not match expectations (e.g. Gemini changed their UI or
      // the session is so expired it lands on a different page). Return 400 so the
      // account-fallback system does NOT retry this request as a transient 5xx.
      if (
        error instanceof Error &&
        (error.name === "TimeoutError" ||
          rawMessage.includes("waitForSelector") ||
          rawMessage.includes("Timeout") ||
          rawMessage.includes("actionability") ||
          rawMessage.includes("interception"))
      ) {
        return {
          response: new Response(
            JSON.stringify({
              error: sanitizeErrorMessage(rawMessage),
            }),
            { status: 400, headers: { "Content-Type": "application/json" } }
          ),
          url: GEMINI_URL,
          headers: {},
          transformedBody: body,
        };
      }
      return {
        response: new Response(
          JSON.stringify({
            error: sanitizeErrorMessage(rawMessage),
          }),
          { status: 500, headers: { "Content-Type": "application/json" } }
        ),
        url: GEMINI_URL,
        headers: {},
        transformedBody: body,
      };
    } finally {
      if (abortBrowser) signal?.removeEventListener("abort", abortBrowser);
      // Always close browser to prevent resource leaks
      if (browser) {
        try {
          await browser.close();
        } catch {
          /* ignore close errors */
        }
      }
    }
  }
}
