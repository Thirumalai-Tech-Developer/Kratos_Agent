/**
 * Veo HTTP RPC Module for Gemini Web
 *
 * Reverse-engineered HTTP pipeline for Google Veo video generation on Gemini Web:
 * 1. Extract WIZ tokens (`SNlM0e`, `cfb2h`, `FdrFJe`) from https://gemini.google.com/app
 * 2. POST StreamGenerate with Tool Code 16 (`[[16]]`) and aspect ratio mapping (2: portrait, 1: landscape)
 * 3. Poll batchexecute RPC `hNvQHb` for the completed video artifact
 * 4. Sanitize escaped URLs (stripping backslashes: `c\=` -> `c=`, `\&` -> `&`, `\/` -> `/`)
 *
 * Zero Playwright dependency, fast, and works in headless/containerized environments.
 */

import { randomUUID } from "node:crypto";
import { mergeAbortSignals, type ExecuteInput } from "../base.ts";

export type VideoOrientation = "landscape" | "portrait" | "square";

export interface VideoGenerationArtifact {
  url?: string;
  b64_json?: string;
  format: string;
}

export interface ExecuteVideoHttpOptions {
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

export interface GeminiWizData {
  atToken: string;
  blLabel: string;
  fSid: string;
  /** Set-Cookie values from the response, parsed to name=value pairs for merging */
  refreshedCookies?: Array<{ name: string; value: string }>;
}

interface CachedWizData extends GeminiWizData {
  expiresAt: number;
}

const wizDataCache = new Map<string, CachedWizData>();
const WIZ_DATA_TTL_MS = 60 * 60 * 1000; // 1 hour

export const GEMINI_USER_AGENT =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36";

export function getCachedWizData(cookie: string): GeminiWizData | null {
  const cached = wizDataCache.get(cookie);
  if (!cached) return null;
  if (Date.now() > cached.expiresAt) {
    wizDataCache.delete(cookie);
    return null;
  }
  return { atToken: cached.atToken, blLabel: cached.blLabel, fSid: cached.fSid };
}

export function setCachedWizData(cookie: string, data: GeminiWizData): void {
  wizDataCache.set(cookie, {
    ...data,
    expiresAt: Date.now() + WIZ_DATA_TTL_MS,
  });
}

export function clearCachedWizData(cookie?: string): void {
  if (cookie) {
    wizDataCache.delete(cookie);
  } else {
    wizDataCache.clear();
  }
}

/**
 * Clean Google Video URL by stripping JSON backslash escape sequences
 * (e.g. `c\=` -> `c=`, `\&` -> `&`, `\/` -> `/`) that cause download 400s.
 */
export function cleanGoogleVideoUrl(raw: string): string {
  if (!raw || typeof raw !== "string") return "";
  let url = raw
    .replace(/\\u0026/g, "&")
    .replace(/\\u003d/g, "=")
    .replace(/\\u002F/g, "/")
    .replace(/&amp;/g, "&");

  // Strip ALL escape backslashes (\=, \&, \/) entirely
  url = url.split("\\").join("");

  // Remove any trailing quotes, brackets or whitespace
  url = url.replace(/["')\]\s]+$/, "");
  return url.trim();
}

/**
 * Scan raw text/payload for official Veo download link or CDN stream.
 */
export function inspectTextForVideoUrl(rawText: string): string | null {
  if (!rawText || typeof rawText !== "string") return null;

  const text = cleanGoogleVideoUrl(rawText);

  // 1. Match official contribution download URL
  const downloadMatch = text.match(
    /https:\/\/contribution\.usercontent\.google\.com\/download\?[^\s"'<>]+/i
  );
  if (downloadMatch) {
    return cleanGoogleVideoUrl(downloadMatch[0]);
  }

  // 2. Match Google CDN direct video stream (lh3, lh4, etc. with /gg/)
  const cdnMatch = text.match(
    /https:\/\/lh\d*\.googleusercontent\.com\/gg\/[^\s"'<>]+/i
  );
  if (cdnMatch) {
    return cleanGoogleVideoUrl(cdnMatch[0]);
  }

  // 3. Any direct googleusercontent video URL
  const gVideoMatch = text.match(
    /https:\/\/[a-zA-Z0-9.-]+\.googleusercontent\.com\/[^\s"'<>]*(?:video|mp4|\/gg\/)[^\s"'<>]*/i
  );
  if (gVideoMatch) {
    return cleanGoogleVideoUrl(gVideoMatch[0]);
  }

  // 4. googlevideo.com CDN
  const gvMatch = text.match(/https:\/\/[a-zA-Z0-9.-]+\.googlevideo\.com\/[^\s"'<>]+/i);
  if (gvMatch) {
    return cleanGoogleVideoUrl(gvMatch[0]);
  }

  // 5. Match general MP4 URL
  const mp4Match = text.match(/https:\/\/[^"'\s\\]+\.mp4(?:\?[^"'\s\\]+)?/i);
  if (mp4Match) {
    return cleanGoogleVideoUrl(mp4Match[0]);
  }

  return null;
}

/**
 * Detect transient high-traffic / capacity limit rejection from Gemini Web.
 */
export function checkGeminiWebRejectionReason(
  text: string
): "high_traffic_busy" | "policy_violation" | "internal_error" | "captcha_required" | null {
  if (!text || typeof text !== "string") return null;
  const lower = text.toLowerCase();
  if (
    lower.includes("getting a lot of requests right now") ||
    lower.includes("couldn't do that because i'm getting a lot of requests") ||
    lower.includes("please try again later") ||
    lower.includes("high demand") ||
    lower.includes("temporarily unavailable") ||
    lower.includes("too many requests") ||
    lower.includes("capacity limit")
  ) {
    return "high_traffic_busy";
  }
  if (
    lower.includes("i cannot create video") ||
    lower.includes("i can't create video") ||
    lower.includes("against our safety guidelines") ||
    lower.includes("cannot fulfill this request") ||
    lower.includes("i am unable to generate")
  ) {
    return "policy_violation";
  }
  if (
    lower.includes("unusual traffic from your computer network") ||
    lower.includes("recaptcha") ||
    lower.includes("/sorry/index")
  ) {
    return "captcha_required";
  }
  if (
    lower.includes("i encountered an error doing what you asked") ||
    lower.includes("i encountered an error. please try again") ||
    lower.includes("i encountered an error") ||
    lower.includes("could you try again") ||
    lower.includes("something went wrong")
  ) {
    return "internal_error";
  }
  return null;
}

/**
 * Extract WIZ_global_data (`SNlM0e`, `cfb2h`, `FdrFJe`) from Gemini HTML page.
 */
export function extractWizData(html: string): GeminiWizData | null {
  if (!html || typeof html !== "string") return null;

  const atMatch =
    html.match(/"SNlM0e"\s*:\s*"([^"]+)"/) ||
    html.match(/'SNlM0e'\s*:\s*'([^']+)'/) ||
    html.match(/\[\s*"SNlM0e"\s*,\s*null\s*,\s*"([^"]+)"\s*\]/) ||
    html.match(/"thykhd"\s*:\s*"([^"]+)"/) ||
    html.match(/'thykhd'\s*:\s*'([^']+)'/);
  const atToken = atMatch ? atMatch[1] : "";

  const blMatch =
    html.match(/"cfb2h"\s*:\s*"([^"]+)"/) ||
    html.match(/'cfb2h'\s*:\s*'([^']+)'/) ||
    html.match(/\[\s*"cfb2h"\s*,\s*null\s*,\s*"([^"]+)"\s*\]/);
  const blLabel = blMatch ? blMatch[1] : "boq_assistant-bard-web-server_20260907.07_p0";

  const fsidMatch =
    html.match(/"FdrFJe"\s*:\s*"([^"]+)"/) ||
    html.match(/'FdrFJe'\s*:\s*'([^']+)'/) ||
    html.match(/\[\s*"FdrFJe"\s*,\s*null\s*,\s*"([^"]+)"\s*\]/) ||
    html.match(/"f\.sid"\s*:\s*"([^"]+)"/) ||
    html.match(/'f\.sid'\s*:\s*'([^']+)'/);
  const fSid = fsidMatch ? fsidMatch[1] : "";

  if (!atToken) return null;
  return { atToken, blLabel, fSid };
}

/**
 * Fetch and extract Gemini Web WIZ data using existing session cookies.
 */
export async function fetchGeminiWebWizData(
  cookie: string,
  entryUrl: string = "https://gemini.google.com/app",
  signal?: AbortSignal | null,
  log?: ExecuteInput["log"]
): Promise<GeminiWizData | null> {
  const cached = getCachedWizData(cookie);
  if (cached) return cached;

  const fetchSignal = AbortSignal.timeout(10_000);
  const combinedSignal = signal ? mergeAbortSignals(signal, fetchSignal) : fetchSignal;

  try {
    const resp = await fetch(entryUrl, {
      method: "GET",
      headers: {
        "User-Agent": GEMINI_USER_AGENT,
        Cookie: cookie,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
      },
      signal: combinedSignal,
    });

    if (!resp.ok) {
      log?.warn?.("GEMINI-WEB", `Failed to fetch Gemini Web home page: HTTP ${resp.status}`);
      return null;
    }

    if (resp.url.includes("accounts.google.com")) {
      log?.warn?.("GEMINI-WEB", "Session expired: redirected to Google accounts login");
      return null;
    }

    const html = await resp.text();
    const data = extractWizData(html);
    if (!data) {
      log?.warn?.("GEMINI-WEB", "Could not extract WIZ tokens (SNlM0e) from Gemini Web HTML response");
      return null;
    }

    // Capture Set-Cookie headers so callers can persist rotated session tokens.
    // Node fetch uses `getSetCookie()` for multiple Set-Cookie headers.
    const setCookieHeaders: string[] = typeof resp.headers.getSetCookie === "function"
      ? resp.headers.getSetCookie()
      : (resp.headers.get("set-cookie") || "").split(/,(?=[^ ])/);

    if (setCookieHeaders.length > 0) {
      const refreshedCookies: Array<{ name: string; value: string }> = [];
      for (const raw of setCookieHeaders) {
        const nameValue = raw.split(";")[0]?.trim();
        if (!nameValue) continue;
        const eqIdx = nameValue.indexOf("=");
        if (eqIdx > 0) {
          refreshedCookies.push({
            name: nameValue.slice(0, eqIdx),
            value: nameValue.slice(eqIdx + 1),
          });
        }
      }
      if (refreshedCookies.length > 0) {
        data.refreshedCookies = refreshedCookies;
      }
    }

    setCachedWizData(cookie, data);
    return data;
  } catch (err) {
    log?.warn?.(
      "GEMINI-WEB",
      `Error fetching Gemini WIZ data: ${err instanceof Error ? err.message : String(err)}`
    );
    return null;
  }
}

export const fetchGeminiWizData = fetchGeminiWebWizData;

/**
 * Build the reverse-engineered Veo video RPC payload for StreamGenerate.
 * Enforces Tool Code 16 (`[[16]]`) and aspect ratio mapping (2 = portrait 9:16, 1 = landscape 16:9).
 */
export function buildVeoVideoRpcPayload(
  prompt: string,
  options?: {
    orientation?: VideoOrientation | null;
    aspectRatio?: string;
    conversationId?: string;
    responseId?: string;
    choiceId?: string;
    model?: string;
  }
): { reqArray: unknown[]; clientUuid: string } {
  const isPortrait =
    options?.orientation === "portrait" ||
    options?.aspectRatio === "9:16" ||
    options?.aspectRatio === "vertical" ||
    (typeof options?.model === "string" &&
      (options.model.toLowerCase().includes("portrait") ||
        options.model.toLowerCase().includes("potrait") ||
        options.model.toLowerCase().includes("9:16")));
  const aspectCode = isPortrait ? 2 : 1;

  const videoPrompt = prompt.toLowerCase().includes("video")
    ? prompt.trim()
    : `Create a video of: ${prompt.trim()}`;

  const promptItem: unknown[] = [
    videoPrompt,
    0,
    null,
    null,
    null,
    null,
    0,
    null,
    null,
    [null, null, null, null, null, null, [[null, null, null, aspectCode]]],
  ];

  const clientUuid = randomUUID().toUpperCase();

  const convState = options?.conversationId
    ? [
        options.conversationId,
        options.responseId || "",
        options.choiceId || "",
        null,
        null,
        null,
        null,
        null,
        null,
        "",
      ]
    : ["", "", "", null, null, null, null, null, null, ""];

  const reqArray: unknown[] = [
    promptItem,
    ["en"],
    convState,
    null,
    null,
    null,
    [1],
    1,
    null,
    null,
    1,
    0,
    null,
    null,
    null,
    null,
    null,
    [[0]],
    0,
    null, null, null, null, null, null, null, null,
    1,
    null, null,
    [4],
    null, null, null, null, null, null, null, null, null, null,
    [1],
    null, null, null, null, null, null, null,
    11,
    null, null, null,
    0,
    [],
    [[16]], // Tool Code 16 Activates Veo Video Engine!
    null, null, null,
    clientUuid,
    null,
    [],
    null, null, null, null, null,
    0,
    2,
    null, null, null, null, null, null, null, null, null, null,
    1, 1,
    null, null, null, null, null, null, null, null, null, null,
    0,
    null, null, null, null,
    0,
    null,
    1,
  ];

  return { reqArray, clientUuid };
}

export function abortableSleep(ms: number, signal?: AbortSignal | null): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(
      signal.reason instanceof Error ? signal.reason : new Error("Request aborted")
    );
  }
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason instanceof Error ? signal.reason : new Error("Request aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Format video generation result into URL or base64 JSON artifact.
 */
export async function formatVideoResult(
  rawUrl: string,
  responseFormat: "url" | "b64_json",
  cookie: string,
  signal?: AbortSignal | null,
  conversationId?: string | null
): Promise<{
  success: boolean;
  status: number;
  data?: VideoGenerationArtifact[];
  error?: string;
  conversationId?: string;
}> {
  const cleanUrl = cleanGoogleVideoUrl(rawUrl);

  if (responseFormat === "b64_json") {
    try {
      const fetchResp = await fetch(cleanUrl, {
        headers: {
          "User-Agent": GEMINI_USER_AGENT,
          Cookie: cookie,
        },
        signal: signal ?? undefined,
      });
      if (!fetchResp.ok) {
        throw new Error(`Failed to fetch video artifact: HTTP ${fetchResp.status}`);
      }
      const arrayBuf = await fetchResp.arrayBuffer();
      const b64 = Buffer.from(arrayBuf).toString("base64");
      return {
        success: true,
        status: 200,
        data: [{ b64_json: b64, format: "mp4" }],
        ...(conversationId ? { conversationId } : {}),
      };
    } catch (downloadErr) {
      return {
        success: false,
        status: 502,
        error: `Gemini Web generated a video but OmniRoute could not download it for b64_json: ${downloadErr instanceof Error ? downloadErr.message : String(downloadErr)}`,
      };
    }
  }

  return {
    success: true,
    status: 200,
    data: [{ url: cleanUrl, format: "mp4" }],
    ...(conversationId ? { conversationId } : {}),
  };
}

/**
 * Execute video generation using Google's reverse-engineered Veo RPC pipeline (pure HTTP).
 * Dispatches StreamGenerate with Tool Code 16 and polls hNvQHb for completion.
 */
export async function executeVeoVideoGenerationHttp(
  input: ExecuteVideoHttpOptions,
  cookie: string
): Promise<{
  success: boolean;
  status: number;
  data?: VideoGenerationArtifact[];
  error?: string;
}> {
  const {
    prompt,
    model,
    orientation,
    aspectRatio,
    responseFormat = "url",
    timeoutMs = 240_000,
    credentials,
    signal,
    log,
    videoUrl = "https://gemini.google.com/app",
    conversationId,
  } = input;

  const trimmedPrompt = prompt?.trim();
  if (!trimmedPrompt) {
    return {
      success: false,
      status: 400,
      error: "Prompt is required for Gemini Web video generation",
    };
  }

  let baseOrigin = "https://gemini.google.com";
  try {
    if (videoUrl) {
      const parsed = new URL(videoUrl);
      baseOrigin = parsed.origin;
    }
  } catch {
    /* use default origin */
  }

  // 1. Obtain WIZ tokens
  let wiz: GeminiWizData | null = null;
  const passedAt =
    typeof (credentials as Record<string, unknown> | undefined)?.at === "string"
      ? ((credentials as Record<string, unknown>).at as string)
      : typeof (credentials as Record<string, unknown> | undefined)?.atToken === "string"
        ? ((credentials as Record<string, unknown>).atToken as string)
        : typeof (credentials as Record<string, unknown> | undefined)?.SNlM0e === "string"
          ? ((credentials as Record<string, unknown>).SNlM0e as string)
          : "";

  if (passedAt) {
    wiz = {
      atToken: passedAt,
      blLabel: "boq_assistant-bard-web-server_20260907.07_p0",
      fSid: "",
    };
  } else {
    // Always fetch the chat app page where WIZ_global_data is populated
    wiz = await fetchGeminiWebWizData(cookie, "https://gemini.google.com/app", signal, log);
  }

  if (!wiz || !wiz.atToken) {
    return {
      success: false,
      status: 401,
      error:
        "Failed to extract Gemini Web authentication token (SNlM0e). Please verify that your __Secure-1PSID cookie is active and valid.",
    };
  }

  const maxRetries = 3;
  const overallStartTime = Date.now();
  const overallTimeoutMs = Math.min(timeoutMs, 240_000);
  let attempt = 0;
  let lastError = "";

  while (attempt < maxRetries && Date.now() - overallStartTime < overallTimeoutMs) {
    if (signal?.aborted) {
      throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
    }
    attempt++;
    const isRetry = attempt > 1;

    if (isRetry) {
      log?.info?.(
        "GEMINI-WEB",
        `Retrying Veo video dispatch (attempt ${attempt}/${maxRetries})`
      );
    }

    const effectiveOrientation =
      orientation ??
      (model && (model.toLowerCase().includes("portrait") || model.toLowerCase().includes("potrait"))
        ? "portrait"
        : model && model.toLowerCase().includes("landscape")
          ? "landscape"
          : null);

    const effectiveAspectRatio =
      aspectRatio ??
      (effectiveOrientation === "portrait"
        ? "9:16"
        : effectiveOrientation === "landscape"
          ? "16:9"
          : undefined);

    const { reqArray, clientUuid } = buildVeoVideoRpcPayload(trimmedPrompt, {
      orientation: effectiveOrientation,
      aspectRatio: effectiveAspectRatio,
      conversationId,
      model,
    });

    const reqCounter = Math.floor(Math.random() * 800000 + 100000);
    const streamUrl = `${baseOrigin}/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate?bl=${encodeURIComponent(wiz.blLabel)}&f.sid=${encodeURIComponent(wiz.fSid)}&hl=en&_reqid=${reqCounter}&rt=c`;

    const formData = new URLSearchParams();
    formData.append("f.req", JSON.stringify([null, JSON.stringify(reqArray)]));
    formData.append("at", wiz.atToken);

    let streamText = "";
    try {
      const resp = await fetch(streamUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Same-Domain": "1",
          "x-goog-ext-73010989-jspb": "[0]",
          "x-goog-ext-525005358-jspb": JSON.stringify([clientUuid, 1]),
          "User-Agent": GEMINI_USER_AGENT,
          Cookie: cookie,
          Origin: baseOrigin,
          Referer: `${baseOrigin}/app`,
        },
        body: formData.toString(),
        signal: signal ?? undefined,
      });

      if (!resp.ok) {
        const errText = await resp.text().catch(() => "");
        lastError = `StreamGenerate returned HTTP ${resp.status}: ${errText.slice(0, 200)}`;
        log?.warn?.("GEMINI-WEB", lastError);
        if (resp.status === 401 || resp.status === 403) {
          clearCachedWizData(cookie);
          return { success: false, status: resp.status, error: lastError };
        }
        await abortableSleep(2000 * attempt, signal);
        continue;
      }

      streamText = await resp.text();
    } catch (fetchErr) {
      lastError = fetchErr instanceof Error ? fetchErr.message : String(fetchErr);
      log?.warn?.("GEMINI-WEB", `StreamGenerate network error: ${lastError}`);
      await abortableSleep(2000 * attempt, signal);
      continue;
    }

    // Check for Google's policy violation, internal error or capacity limit response
    const rejection = checkGeminiWebRejectionReason(streamText);
    if (rejection === "policy_violation") {
      return {
        success: false,
        status: 400,
        error: "Google Veo rejected prompt due to content or safety guidelines.",
      };
    }
    if (rejection === "captcha_required") {
      return {
        success: false,
        status: 429,
        error:
          "Gemini Web requires CAPTCHA verification on gemini.google.com due to unusual traffic from this IP.",
      };
    }
    if (rejection === "internal_error") {
      return {
        success: false,
        status: 502,
        error:
          "Google Gemini reported: 'I encountered an error doing what you asked. Could you try again?' (The prompt may have triggered content safety guidelines or server-side limits)",
      };
    }
    if (rejection === "high_traffic_busy") {
      const waitTimeSec = 4 + attempt * 2;
      log?.warn?.(
        "GEMINI-WEB",
        `Google reported high demand. Auto-retrying in ${waitTimeSec}s (Attempt ${attempt}/${maxRetries})...`
      );
      await abortableSleep(waitTimeSec * 1000, signal);
      continue;
    }

    // Check if video URL is already present in stream response (cached/instant)
    const directVideoUrl = inspectTextForVideoUrl(streamText);
    if (directVideoUrl) {
      log?.info?.("GEMINI-WEB", "Veo video URL detected directly in stream response");
      return formatVideoResult(directVideoUrl, responseFormat, cookie, signal, convId);
    }

    // Extract conversation ID and async task ID
    const convMatch = streamText.match(/c_[a-zA-Z0-9_-]{6,}/i);
    const taskMatch = streamText.match(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i
    );

    const convId = convMatch ? convMatch[0] : null;
    const taskId = taskMatch ? taskMatch[0] : null;

    if (!convId) {
      lastError = "Could not find conversation ID in Gemini response";
      log?.warn?.("GEMINI-WEB", `${lastError}. Stream snippet: ${streamText.slice(0, 300)}`);
      if (attempt < maxRetries && Date.now() - overallStartTime + 5000 < overallTimeoutMs) {
        await abortableSleep(3000, signal);
        continue;
      }
      return { success: false, status: 502, error: lastError };
    }

    log?.info?.(
      "GEMINI-WEB",
      `Veo video generation dispatched: convId=${convId}${taskId ? ` taskId=${taskId}` : ""}. Polling for render...`
    );

    // 2. Polling loop
    const pollStartTime = Date.now();
    const remainingOverallMs = overallTimeoutMs - (Date.now() - overallStartTime);
    const attemptTimeoutMs = Math.max(10_000, Math.min(180_000, remainingOverallMs));
    let videoUrlResult: string | null = null;

    while (Date.now() - pollStartTime < attemptTimeoutMs) {
      if (signal?.aborted) {
        throw signal.reason instanceof Error ? signal.reason : new Error("Request aborted");
      }

      await abortableSleep(4000, signal);

      const pollReqId = Math.floor(Math.random() * 800000 + 100000);
      const historyUrl = `${baseOrigin}/_/BardChatUi/data/batchexecute?rpcids=hNvQHb&bl=${encodeURIComponent(wiz.blLabel)}&f.sid=${encodeURIComponent(wiz.fSid)}&hl=en&_reqid=${pollReqId}&rt=c`;
      const historyBody = new URLSearchParams();
      historyBody.append(
        "f.req",
        JSON.stringify([
          [
            [
              "hNvQHb",
              JSON.stringify([convId, 10, null, 1, [1], [4], null, 1]),
              null,
              "generic",
            ],
          ],
        ])
      );
      historyBody.append("at", wiz.atToken);

      try {
        const hResp = await fetch(historyUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Same-Domain": "1",
            "x-goog-ext-73010989-jspb": "[0]",
            "User-Agent": GEMINI_USER_AGENT,
            Cookie: cookie,
            Origin: baseOrigin,
            Referer: `${baseOrigin}/app/${convId}`,
          },
          body: historyBody.toString(),
          signal: signal ?? undefined,
        });

        if (!hResp.ok) {
          const errText = await hResp.text().catch(() => "");
          log?.warn?.(
            "GEMINI-WEB",
            `Polling hNvQHb returned HTTP ${hResp.status}: ${errText.slice(0, 150)}`
          );
          if (hResp.status === 401 || hResp.status === 403) {
            clearCachedWizData(cookie);
            return {
              success: false,
              status: hResp.status,
              error: `Session expired during render polling: HTTP ${hResp.status}`,
            };
          }
        } else {
          const hText = await hResp.text();
          const matchedUrl = inspectTextForVideoUrl(hText);
          if (matchedUrl) {
            videoUrlResult = matchedUrl;
            const elapsed = Math.round((Date.now() - pollStartTime) / 1000);
            log?.info?.("GEMINI-WEB", `Veo video completed in ${elapsed}s: ${videoUrlResult}`);
            break;
          }

          const pollRejection = checkGeminiWebRejectionReason(hText);
          if (pollRejection === "high_traffic_busy") {
            log?.warn?.(
              "GEMINI-WEB",
              "Generation encountered high traffic during render. Retrying dispatch..."
            );
            break;
          }
          if (pollRejection === "policy_violation") {
            return {
              success: false,
              status: 400,
              error: "Google Veo rejected prompt due to content or safety guidelines.",
            };
          }
          if (pollRejection === "captcha_required") {
            return {
              success: false,
              status: 429,
              error:
                "Gemini Web requires CAPTCHA verification on gemini.google.com during render.",
            };
          }
          if (pollRejection === "internal_error") {
            return {
              success: false,
              status: 502,
              error:
                "Google Gemini reported: 'I encountered an error doing what you asked. Could you try again?' during video render.",
            };
          }
        }
      } catch (pollErr) {
        log?.warn?.(
          "GEMINI-WEB",
          `Polling hNvQHb exception: ${pollErr instanceof Error ? pollErr.message : String(pollErr)}`
        );
      }

      // Ping kwDCne with taskId if present
      if (taskId) {
        try {
          const kwUrl = `${baseOrigin}/_/BardChatUi/data/batchexecute?rpcids=kwDCne&bl=${encodeURIComponent(wiz.blLabel)}&f.sid=${encodeURIComponent(wiz.fSid)}&hl=en&_reqid=${pollReqId + 1}&rt=c`;
          const kwBody = new URLSearchParams();
          kwBody.append(
            "f.req",
            JSON.stringify([[["kwDCne", JSON.stringify([taskId]), null, "generic"]]])
          );
          kwBody.append("at", wiz.atToken);
          void fetch(kwUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
              "X-Same-Domain": "1",
              "User-Agent": GEMINI_USER_AGENT,
              Cookie: cookie,
              Origin: baseOrigin,
              Referer: `${baseOrigin}/app/${convId}`,
            },
            body: kwBody.toString(),
          }).catch(() => {});
        } catch {
          /* ignore */
        }
      }
    }

    if (videoUrlResult) {
      return formatVideoResult(videoUrlResult, responseFormat, cookie, signal, convId);
    }
  }

  return {
    success: false,
    status: 504,
    error: lastError || "Veo video generation timed out before completion",
  };
}
