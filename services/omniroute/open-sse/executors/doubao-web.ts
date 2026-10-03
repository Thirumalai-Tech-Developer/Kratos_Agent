/**
 * DoubaoWebExecutor — Dola Global web chat via dola.com.
 *
 * The provider id remains `doubao-web` for compatibility with existing saved
 * provider connections, but the global consumer service now runs through Dola.
 *
 * Endpoint: POST https://www.dola.com/chat/completion
 * Auth: Session cookies from www.dola.com
 */
import { randomUUID } from "node:crypto";
import { BaseExecutor, type ExecuteInput } from "./base.ts";
import {
  buildErrorBody,
  makeExecutorErrorResult as makeErrorResult,
  normalizeCookie,
} from "../utils/error.ts";
import {
  WebSessionRotator,
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
  prepareWebSessionMessages,
} from "../services/webSessionRotator.ts";

export interface DolaSessionData {
  localConversationId: string;
  conversationId?: string;
  sectionId?: string;
}

export const dolaSessionRotator = new WebSessionRotator<DolaSessionData>();

const BASE_URL = "https://www.dola.com";
const CHAT_URL = `${BASE_URL}/chat/completion`;
const DEFAULT_MODEL = "dola-speed";
const DOLA_BOT_ID = "7339470689562525703";
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36";

type JsonRecord = Record<string, unknown>;

export interface DolaTextExtractionState {
  deferUntilAnswer: boolean;
  answerStarted: boolean;
  bufferedDeltas: string[];
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function toString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function toContentText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function parseJsonRecord(raw: string): JsonRecord | null {
  if (!raw.startsWith("{")) return null;
  try {
    return asRecord(JSON.parse(raw));
  } catch {
    return null;
  }
}

function randomNumericId(length = 19): string {
  // crypto-backed, UNBIASED digits (CodeQL js/insecure-randomness +
  // js/biased-cryptographic-random): a synthetic device/web id, not a secret.
  // A raw `cryptoByte % 10` is biased (256 is not a multiple of 10), so each
  // digit is drawn by rejection sampling — discard bytes in the biased tail so
  // the remaining range divides evenly, then reduce.
  const digit = (max: number): number => {
    const limit = 256 - (256 % max); // largest multiple of `max` that fits in a byte
    const buf = new Uint8Array(1);
    let b: number;
    do {
      globalThis.crypto.getRandomValues(buf);
      b = buf[0];
    } while (b >= limit);
    return b % max;
  };
  let id = String(digit(9) + 1);
  for (let i = 1; i < length; i += 1) id += String(digit(10));
  return id;
}

function deterministicNumericId(seed: string, length = 19): string {
  if (!seed) return randomNumericId(length);
  let hash = 0n;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31n + BigInt(seed.charCodeAt(i))) & 0xffffffffffffffffn;
  }
  let str = (hash > 0n ? hash : -hash).toString();
  while (str.length < length) {
    hash = (hash * 131n + 7n) & 0xffffffffffffffffn;
    str += (hash > 0n ? hash : -hash).toString();
  }
  return str.slice(0, length);
}

function contentToText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        const item = asRecord(part);
        if (item.type === "text") return toContentText(item.text);
        if (typeof item.text === "string") return item.text;
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

function isDolaReasoningModel(modelId: string): boolean {
  return modelId === "dola-pro" || modelId === "dola-deep-think";
}

function createDolaTextExtractionState(modelId: string): DolaTextExtractionState {
  const deferUntilAnswer = isDolaReasoningModel(modelId);
  return {
    deferUntilAnswer,
    answerStarted: !deferUntilAnswer,
    bufferedDeltas: [],
  };
}

function isDolaAnswerBoundary(block: JsonRecord): boolean {
  return block.block_type === 10040 && block.is_finish === true;
}

export function foldMessages(messages: unknown): string {
  if (!Array.isArray(messages) || messages.length === 0) return "";
  if (messages.length === 1) {
    const item = asRecord(messages[0]);
    return contentToText(item.content);
  }
  return messages
    .map((message) => {
      const item = asRecord(message);
      const role = toString(item.role) || "user";
      const text = contentToText(item.content);
      return text ? `${role}: ${text}` : "";
    })
    .filter(Boolean)
    .join("\n\n");
}

export function extractCookieValue(cookieHeader: string, name: string): string {
  const pattern = new RegExp(`(?:^|;\\s*)${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^;]*)`);
  const value = pattern.exec(cookieHeader)?.[1] ?? "";
  try {
    return decodeURIComponent(value).trim();
  } catch {
    return value.trim();
  }
}

function extractQueryValue(raw: string, name: string): string {
  if (!raw.includes("?") && !raw.includes("&")) return "";
  try {
    const urlMatch = raw.match(/https?:\/\/[^\s'"]+/);
    const target = urlMatch
      ? urlMatch[0]
      : raw.startsWith("http")
        ? raw
        : `https://www.dola.com/?${raw.replace(/^[?&]+/, "")}`;
    const url = new URL(target);
    return toString(url.searchParams.get(name));
  } catch {
    return "";
  }
}

export function resolveDolaFingerprint(
  cookieHeader: string,
  providerSpecificData?: unknown,
  rawCredential = ""
): string {
  const data = asRecord(providerSpecificData);
  return (
    toString(data.s_v_web_id) ||
    toString(data.sVWebId) ||
    extractCookieValue(cookieHeader, "s_v_web_id") ||
    toString(data.fp) ||
    extractCookieValue(cookieHeader, "fp") ||
    extractQueryValue(rawCredential, "fp")
  );
}

export function parseTabularCookies(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  const lines = raw.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\t+|\s{2,}/);
    if (parts.length >= 2) {
      const name = parts[0].trim();
      const value = parts[1].trim();
      if (name && value && !name.includes(" ") && !name.includes(";")) {
        result[name] = value;
      }
    }
  }
  return result;
}

export function buildDolaCookieHeader(
  rawCredential: string,
  providerSpecificData?: unknown
): string {
  const providerData = asRecord(providerSpecificData);
  const raw = normalizeCookie(rawCredential.trim());
  const tabular = parseTabularCookies(raw);
  const parsed = parseJsonRecord(raw);
  const data = { ...providerData, ...tabular, ...(parsed ?? {}) };
  const explicitCookie = normalizeCookie(toString(data.cookie));
  const directCookie = raw && !parsed && Object.keys(tabular).length === 0 ? raw : "";
  const cookieSource = explicitCookie || directCookie;

  if (cookieSource.includes("=")) return cookieSource;

  const cookieNames = [
    "sessionid",
    "ttwid",
    "s_v_web_id",
    "fp",
    "device_id",
    "web_id",
    "tea_uuid",
    "msToken",
    "sessionid_ss",
    "sid_guard",
    "sid_tt",
    "sid_ucp_v1",
    "ssid_ucp_v1",
    "uid_tt",
    "uid_tt_ss",
    "odin_tt",
    "passport_csrf_token",
    "passport_csrf_token_default",
    "passport_auth_status",
    "passport_auth_status_ss",
    "store-country-code",
    "store-country-code-src",
    "store-idc",
    "user_language_code",
  ];
  const parts = cookieNames
    .map((name) => {
      const value = toString(data[name]);
      return value ? `${name}=${value}` : "";
    })
    .filter(Boolean);

  if (parts.length > 0) return parts.join("; ");
  return raw ? `sessionid=${raw}` : "";
}

export function buildDolaQueryParams(
  cookieHeader: string,
  providerSpecificData?: unknown,
  rawCredential = ""
): URLSearchParams {
  const data = asRecord(providerSpecificData);
  const seed =
    extractCookieValue(cookieHeader, "sessionid") || rawCredential || "dola_default_seed";
  const stableGeneratedId = deterministicNumericId(seed);

  const deviceId =
    toString(data.device_id) ||
    toString(data.deviceId) ||
    extractQueryValue(rawCredential, "device_id") ||
    extractCookieValue(cookieHeader, "device_id") ||
    stableGeneratedId;

  const webId =
    toString(data.web_id) ||
    toString(data.webId) ||
    extractQueryValue(rawCredential, "web_id") ||
    extractCookieValue(cookieHeader, "web_id") ||
    deviceId;

  const teaUuid =
    toString(data.tea_uuid) ||
    toString(data.teaUuid) ||
    extractQueryValue(rawCredential, "tea_uuid") ||
    extractCookieValue(cookieHeader, "tea_uuid") ||
    deviceId;

  const fp = resolveDolaFingerprint(cookieHeader, providerSpecificData, rawCredential);

  const countryCode =
    toString(data.region) ||
    extractCookieValue(cookieHeader, "store-country-code")?.toUpperCase() ||
    "US";

  const pcVersion = toString(data.pc_version) || toString(data.pcVersion) || "3.36.0";
  const tzName = toString(data.tz_name) || toString(data.tzName) || "Asia/Dubai";

  const params = new URLSearchParams({
    aid: "495671",
    real_aid: "495671",
    device_platform: "web",
    doubao_device_platform: "web",
    doubao_pc_version: pcVersion,
    device_id: deviceId,
    web_id: webId,
    tea_uuid: teaUuid,
    web_tab_id: randomUUID(),
    pc_version: pcVersion,
    pkg_type: "release_version",
    version_code: "20800",
    samantha_web: "1",
    web_platform: "browser",
    "use-olympus-account": "1",
    language: toString(data.language) || "en",
    region: countryCode,
    sys_region: toString(data.sys_region) || toString(data.sysRegion) || countryCode,
    tz_name: tzName,
    fp,
  });

  const msToken =
    toString(data.msToken) ||
    extractQueryValue(rawCredential, "msToken") ||
    extractCookieValue(cookieHeader, "msToken");
  if (msToken) params.set("msToken", msToken);

  // Note: a_bogus is a dynamic per-request signature over the request body
  // generated in-browser. Replaying a static a_bogus from a previous cURL causes
  // ByteDance's signature verification to fail with "We are experiencing high demand right now"
  // or "system error (is_replay: true)". We only set a_bogus if explicitly provided via
  // providerSpecificData, never from pasted credential strings.
  const aBogus = toString(data.a_bogus);
  if (aBogus) params.set("a_bogus", aBogus);

  return params;
}

export function resolveDolaDeepThinkValue(modelId: string, providerSpecificData?: unknown): 0 | 3 {
  if (modelId === "dola-pro" || modelId === "dola-deep-think") return 3;
  if (modelId === "dola-speed") return 0;
  const data = asRecord(providerSpecificData);
  const configured = toString(data.use_deep_think) || toString(data.useDeepThink);
  if (configured === "3") return 3;
  if (configured === "0") return 0;
  if (data.deepThink === true) return 3;
  return 0;
}

export function buildDolaPayload(
  prompt: string,
  modelId = DEFAULT_MODEL,
  cookieHeader = "",
  providerSpecificData?: unknown,
  rawCredential = "",
  sessionOptions?: {
    localConversationId?: string;
    conversationId?: string;
    sectionId?: string;
    needCreateConversation?: boolean;
  }
): JsonRecord {
  const data = asRecord(providerSpecificData);
  const localConversationId =
    sessionOptions?.localConversationId ||
    toString(data.local_conversation_id) ||
    toString(data.localConversationId) ||
    `local_${randomNumericId(16)}`;
  const conversationId = sessionOptions?.conversationId || toString(data.conversation_id) || "";
  const sectionId = sessionOptions?.sectionId || toString(data.section_id) || "";
  const needCreateConversation = sessionOptions?.needCreateConversation ?? !conversationId;
  const blockId = randomUUID();
  const messageId = randomUUID();
  const uniqueKey = randomUUID();
  const now = Date.now();
  const deepThinkValue = resolveDolaDeepThinkValue(modelId, providerSpecificData);
  const fp = resolveDolaFingerprint(cookieHeader, providerSpecificData, rawCredential);

  return {
    client_meta: {
      local_conversation_id: localConversationId,
      conversation_id: conversationId,
      bot_id: toString(data.bot_id) || toString(data.botId) || DOLA_BOT_ID,
      last_section_id: sectionId,
      last_message_index: null,
      local_permissions: [
        { permission_name: "ACCESS_COARSE_LOCATION", status: 3 },
        { permission_name: "ACCESS_FINE_LOCATION", status: 3 },
        { permission_name: "ACCESS_BACKGROUND_LOCATION", status: 3 },
      ],
    },
    messages: [
      {
        local_message_id: messageId,
        content_block: [
          {
            block_type: 10000,
            content: {
              text_block: {
                text: prompt,
                icon_url: "",
                icon_url_dark: "",
                summary: "",
              },
              pc_event_block: "",
            },
            block_id: blockId,
            parent_id: "",
            meta_info: [],
            append_fields: [],
          },
        ],
        message_status: 0,
      },
    ],
    option: {
      send_message_scene: "",
      create_time_ms: now,
      collect_id: "",
      is_audio: false,
      answer_with_suggest: false,
      agent_mode: 2,
      tts_switch: false,
      need_deep_think: deepThinkValue,
      click_clear_context: false,
      from_suggest: false,
      is_regen: false,
      is_replace: false,
      is_from_click_option: false,
      is_from_click_softlink: false,
      disable_sse_cache: false,
      select_text_action: "",
      is_select_text: false,
      resend_for_regen: false,
      scene_type: 0,
      unique_key: uniqueKey,
      start_seq: 0,
      need_create_conversation: needCreateConversation,
      conversation_init_option: { need_ack_conversation: true },
      conversation_init_ext: { model_item_key: "0" },
      regen_query_id: [],
      edit_query_id: [],
      regen_instruction: "",
      no_replace_for_regen: false,
      message_from: 0,
      shared_app_name: "",
      shared_app_id: "",
      sse_recv_event_options: { support_chunk_delta: true },
      is_ai_playground: false,
      is_old_user: false,
      recovery_option: {
        is_recovery: false,
        req_create_time_sec: Math.floor(now / 1000),
        append_sse_event_scene: 0,
      },
      message_storage_type: 0,
      related_deleted_message_ids: {},
      connector_info_list: [],
      model_config: { model_item_key: "0", model_extra_params: {} },
      aggregate_params: {
        conversation_mode: "1",
        mode_id: "",
        model_item_key: "0",
        agent_mode: "2",
        reasoning_effort: "",
        provider_id: "",
      },
      conversation_mode: 1,
    },
    user_context: [],
    ext: {
      agent_mode: "2",
      use_deep_think: String(deepThinkValue),
      fp,
      sub_conv_firstmet_type: "1",
      collection_id: "",
      is_finish: "1",
      conversation_init_option: JSON.stringify({ need_ack_conversation: true }),
      commerce_credit_config_enable: "0",
    },
  };
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  const lines = block.split(/\r?\n/);
  const event = lines
    .find((line) => line.startsWith("event:"))
    ?.slice(6)
    .trim();
  const dataLines = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());
  if (dataLines.length === 0) return null;
  const rawData = dataLines.join("\n");
  if (rawData === "[DONE]") return { event: event || "done", data: "[DONE]" };
  try {
    const data: unknown = JSON.parse(rawData);
    // Some responses put the event name inside the data envelope instead of
    // using the SSE event field. Keep error and acknowledgement semantics.
    return { event: event || toString(asRecord(data).event), data };
  } catch {
    return null;
  }
}

function extractDolaBlockDeltas(blocks: unknown[], state?: DolaTextExtractionState): string[] {
  const deltas: string[] = [];

  for (const block of blocks) {
    const blockRecord = asRecord(block);
    if (state && isDolaAnswerBoundary(blockRecord)) {
      state.answerStarted = true;
      state.bufferedDeltas = [];
      continue;
    }

    const text = toContentText(asRecord(asRecord(blockRecord.content).text_block).text);
    if (!text) continue;

    if (!state || state.answerStarted) {
      deltas.push(text);
    } else {
      state.bufferedDeltas.push(text);
    }
  }

  return deltas;
}

function flushDolaTextExtractionState(state: DolaTextExtractionState): string[] {
  if (state.answerStarted) return [];
  const fallback = state.bufferedDeltas;
  state.bufferedDeltas = [];
  state.answerStarted = true;
  return fallback;
}

export function extractDolaTextDeltas(data: unknown, state?: DolaTextExtractionState): string[] {
  const root = asRecord(data);
  const payload = asRecord(root.data);
  const content = asRecord(root.content);
  const payloadContent = asRecord(payload.content);
  const initialBlocks = Array.isArray(content.content_block)
    ? content.content_block
    : Array.isArray(payloadContent.content_block)
      ? payloadContent.content_block
      : [];
  const patchOps = Array.isArray(root.patch_op)
    ? root.patch_op
    : Array.isArray(payload.patch_op)
      ? payload.patch_op
      : [];
  const deltas = extractDolaBlockDeltas(initialBlocks, state);

  for (const op of patchOps) {
    const patchValue = asRecord(asRecord(op).patch_value);
    const blocks = Array.isArray(patchValue.content_block) ? patchValue.content_block : [];
    deltas.push(...extractDolaBlockDeltas(blocks, state));
  }

  return deltas;
}

function extractDolaError(data: unknown): string {
  const root = asRecord(data);
  const payload = asRecord(root.data);
  const rawMsg =
    toString(root.error_msg) ||
    toString(root.message) ||
    toString(payload.message) ||
    toString(payload.error_msg) ||
    toString(payload.errorMessage);

  const extra = asRecord(root.extra);
  const decision = toString(extra.decision);
  if (
    decision.includes("slide") ||
    decision.includes("verify") ||
    rawMsg.includes("rate limited")
  ) {
    return `${rawMsg || "Rate limited"} (Dola requires captcha verification on dola.com)`;
  }

  return rawMsg;
}

function dolaErrorStatus(message: string): number {
  const normalized = message.toLowerCase();
  return /high demand|rate limit|temporarily busy|captcha/.test(normalized) ? 429 : 502;
}

export function isDolaBusyMessage(content: string): boolean {
  const normalized = content.trim().toLowerCase();
  return (
    normalized.includes("a lot of people are using the app right now") &&
    normalized.includes("try again later")
  );
}

function openAiChunk(modelId: string, content: string): JsonRecord {
  return {
    id: `chatcmpl-dola-${Date.now()}`,
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: modelId,
    choices: [{ index: 0, delta: { content }, finish_reason: null }],
  };
}

function openAiCompletion(modelId: string, content: string): JsonRecord {
  return {
    id: `chatcmpl-dola-${Date.now()}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: modelId,
    choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
  };
}

export function isDolaErrorAnswer(content: string): boolean {
  const normalized = content.trim().toLowerCase();
  return (
    normalized.includes("i encountered an error doing what you asked") ||
    (normalized.includes("could you try again") && normalized.includes("error"))
  );
}

export class DoubaoWebExecutor extends BaseExecutor {
  constructor() {
    super("doubao-web", { id: "doubao-web", baseUrl: BASE_URL });
  }

  private createHeaders(
    cookieHeader: string,
    localConversationId = "",
    providerSpecificData?: unknown
  ): Record<string, string> {
    const data = asRecord(providerSpecificData);
    const customUa = toString(data.user_agent) || toString(data.userAgent);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "User-Agent": customUa || USER_AGENT,
      Accept: "*/*",
      Referer: localConversationId
        ? `${BASE_URL}/chat/${localConversationId}`
        : `${BASE_URL}/chat/`,
      Origin: BASE_URL,
      "Agw-Js-Conv": "str, str",
    };
    if (cookieHeader) headers.Cookie = cookieHeader;
    return headers;
  }

  private async collectText(
    upstream: Response,
    modelId: string,
    sessionData?: DolaSessionData,
    signal?: AbortSignal | null
  ): Promise<{ text: string; error?: string }> {
    const state = createDolaTextExtractionState(modelId);
    const deltas: string[] = [];
    let streamError = "";
    let finished = false;
    const processBlock = (block: string) => {
      const event = parseSseBlock(block);
      if (!event) return;
      if (event.event === "STREAM_ERROR") {
        streamError = extractDolaError(event.data) || "Dola stream error";
        finished = true;
      }
      if (event.event === "SSE_ACK") {
        const root = asRecord(event.data);
        const meta = asRecord(root.ack_client_meta || asRecord(root.data).ack_client_meta);
        const convId = toString(meta.conversation_id);
        const secId = toString(meta.section_id);
        if (convId && sessionData) {
          sessionData.conversationId = convId;
          sessionData.sectionId = secId;
        }
      }
      deltas.push(...extractDolaTextDeltas(event.data, state));
      if (event.event === "SSE_REPLY_END" || event.event === "done") finished = true;
    };
    const reader = upstream.body?.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let bytes = 0;
    const onAbort = () => {
      void reader?.cancel().catch(() => {});
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      if (signal?.aborted) onAbort();
      while (reader && !finished && !signal?.aborted) {
        const { done, value } = await reader.read();
        bytes += value?.byteLength || 0;
        if (bytes > 10 * 1024 * 1024) {
          streamError = "Dola response exceeded the size limit";
          break;
        }
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          processBlock(block);
          if (finished) break;
        }
        if (done) {
          if (!finished && buffer.trim()) processBlock(buffer);
          break;
        }
      }
      if (signal?.aborted) streamError = "Dola request was cancelled";
    } catch {
      streamError = "Dola upstream stream could not be read";
    } finally {
      signal?.removeEventListener("abort", onAbort);
      await reader?.cancel().catch(() => {});
      reader?.releaseLock();
    }
    deltas.push(...flushDolaTextExtractionState(state));

    return { text: deltas.join(""), error: streamError };
  }

  private createStream(
    upstream: Response,
    modelId: string,
    signal?: AbortSignal | null,
    sessionData?: DolaSessionData
  ) {
    const encoder = new TextEncoder();
    const decoder = new TextDecoder();
    const state = createDolaTextExtractionState(modelId);
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let cancelled = false;

    return new ReadableStream<Uint8Array>({
      async start(controller) {
        let closed = false;
        let hasEmittedContent = false;
        let buffer = "";

        const emitText = (text: string) => {
          hasEmittedContent = true;
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify(openAiChunk(modelId, text))}\n\n`)
          );
        };
        const finish = (error?: string) => {
          if (closed || cancelled) return;
          if (error) {
            controller.enqueue(
              encoder.encode(
                `data: ${JSON.stringify(buildErrorBody(dolaErrorStatus(error), error))}\n\n`
              )
            );
          } else {
            for (const text of flushDolaTextExtractionState(state)) emitText(text);
            if (!hasEmittedContent) {
              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify(buildErrorBody(502, "Dola upstream returned an empty response without usable output. Verify your login on dola.com."))}\n\n`
                )
              );
            }
          }
          controller.enqueue(encoder.encode("data: [DONE]\n\n"));
          controller.close();
          closed = true;
        };
        const processBlock = (block: string) => {
          const event = parseSseBlock(block);
          if (!event) return;
          if (event.event === "STREAM_ERROR") {
            finish(extractDolaError(event.data) || "Dola stream error");
            return;
          }
          if (event.event === "SSE_ACK") {
            const root = asRecord(event.data);
            const meta = asRecord(root.ack_client_meta || asRecord(root.data).ack_client_meta);
            const convId = toString(meta.conversation_id);
            if (convId && sessionData) {
              sessionData.conversationId = convId;
              sessionData.sectionId = toString(meta.section_id);
            }
          }
          for (const text of extractDolaTextDeltas(event.data, state)) emitText(text);
          if (event.event === "SSE_REPLY_END" || event.event === "done") finish();
        };
        const onAbort = () => {
          if (closed || cancelled) return;
          closed = true;
          controller.close();
          void reader?.cancel().catch(() => {});
        };

        reader = upstream.body?.getReader();
        signal?.addEventListener("abort", onAbort, { once: true });
        try {
          if (signal?.aborted) {
            onAbort();
            return;
          }
          if (!reader) {
            finish();
            return;
          }
          while (!closed && !cancelled) {
            const { done, value } = await reader.read();
            if (closed || cancelled) break;
            if (done) {
              // Flush both the UTF-8 decoder and a final frame that lacks the
              // optional blank-line terminator before declaring empty output.
              buffer += decoder.decode();
              if (buffer.trim()) processBlock(buffer);
              finish();
              break;
            }
            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() || "";
            for (const block of blocks) {
              processBlock(block);
              if (closed || cancelled) break;
            }
          }
        } catch {
          if (!signal?.aborted && !cancelled) finish("Dola upstream stream could not be read");
        } finally {
          signal?.removeEventListener("abort", onAbort);
          await reader?.cancel().catch(() => {});
          reader?.releaseLock();
        }
      },
      async cancel(reason) {
        cancelled = true;
        await reader?.cancel(reason);
      },
    });
  }

  async execute(input: ExecuteInput) {
    const { body, credentials, signal, stream: wantStream } = input;
    const bodyObj = asRecord(body);
    const providerSpecificData = credentials?.providerSpecificData;
    const rawCredential = toString(credentials?.apiKey);
    const cookieHeader = buildDolaCookieHeader(rawCredential, providerSpecificData);
    const requestedModel = input.model || toString(bodyObj.model) || DEFAULT_MODEL;
    const modelId = requestedModel.split("/").pop() || DEFAULT_MODEL;
    if (!["dola-speed", "dola-pro", "dola-deep-think"].includes(modelId)) {
      return makeErrorResult(
        400,
        "Unsupported Dola Web model. Select Dola Speed or Dola Pro.",
        body,
        CHAT_URL
      );
    }
    let prompt = foldMessages(bodyObj.messages);
    const fingerprint = resolveDolaFingerprint(cookieHeader, providerSpecificData, rawCredential);

    const userScope =
      credentials?.connectionId?.trim() ||
      extractCookieValue(cookieHeader, "sessionid") ||
      rawCredential;
    const accountScope = `${userScope}:${modelId}`;
    const minPrompts =
      typeof providerSpecificData?.minPromptsPerPage === "number"
        ? providerSpecificData.minPromptsPerPage
        : DEFAULT_PAGE_MIN_PROMPTS;
    const maxPrompts =
      typeof providerSpecificData?.maxPromptsPerPage === "number"
        ? providerSpecificData.maxPromptsPerPage
        : DEFAULT_PAGE_MAX_PROMPTS;

    const sessionResult = await dolaSessionRotator.acquire({
      scopeKey: accountScope,
      minPrompts,
      maxPrompts,
      createFn: async () => ({
        localConversationId: `local_${randomNumericId(16)}`,
      }),
    });
    prompt = foldMessages(prepareWebSessionMessages(bodyObj.messages, sessionResult.rotated));

    const localConversationId = sessionResult.data.localConversationId;
    const conversationId = sessionResult.data.conversationId || "";
    const sectionId = sessionResult.data.sectionId || "";
    const needCreateConversation = !sessionResult.reused;

    let activeSessionData = sessionResult.data;
    let transformedBody = buildDolaPayload(
      prompt,
      modelId,
      cookieHeader,
      providerSpecificData,
      rawCredential,
      {
        localConversationId,
        conversationId,
        sectionId,
        needCreateConversation,
      }
    );
    const query = buildDolaQueryParams(cookieHeader, providerSpecificData, rawCredential);
    const url = `${CHAT_URL}?${query.toString()}`;
    let reqHeaders = this.createHeaders(cookieHeader, localConversationId, providerSpecificData);

    if (!extractCookieValue(cookieHeader, "sessionid")) {
      return {
        ...makeErrorResult(
          401,
          "Dola Web requires a www.dola.com Cookie header containing at least sessionid, ttwid, and s_v_web_id.",
          body,
          url
        ),
        headers: reqHeaders,
        transformedBody,
      };
    }
    if (!fingerprint) {
      return {
        ...makeErrorResult(
          401,
          "Dola Web requires the browser fingerprint value from www.dola.com. Add s_v_web_id=... from Cookies or fp=verify_... from a Network chat/completion request URL.",
          body,
          url
        ),
        headers: reqHeaders,
        transformedBody,
      };
    }

    let upstream: Response;
    try {
      upstream = await fetch(url, {
        method: "POST",
        headers: reqHeaders,
        body: JSON.stringify(transformedBody),
        signal,
      });
    } catch (err) {
      return {
        ...makeErrorResult(
          502,
          `Dola fetch failed: ${err instanceof Error ? err.message : "unknown"}`,
          body,
          url
        ),
        headers: reqHeaders,
        transformedBody,
      };
    }

    // Only a stale conversation can be repaired by opening another chat.
    // Account limits, expired cookies and service failures must reach the caller.
    if ([400, 404, 409].includes(upstream.status) && sessionResult.reused) {
      dolaSessionRotator.reset(accountScope);
      const retrySession = await dolaSessionRotator.acquire({
        scopeKey: accountScope,
        minPrompts,
        maxPrompts,
        createFn: async () => ({
          localConversationId: `local_${randomNumericId(16)}`,
        }),
      });
      const retryBody = buildDolaPayload(
        prompt,
        modelId,
        cookieHeader,
        providerSpecificData,
        rawCredential,
        {
          localConversationId: retrySession.data.localConversationId,
          needCreateConversation: true,
        }
      );
      const retryHeaders = this.createHeaders(
        cookieHeader,
        retrySession.data.localConversationId,
        providerSpecificData
      );
      try {
        const retryUpstream = await fetch(url, {
          method: "POST",
          headers: retryHeaders,
          body: JSON.stringify(retryBody),
          signal,
        });
        // The response and its acknowledgement belong to the replacement
        // session. Updating the old object would leave the fresh rotator entry
        // without the server conversation and section ids on the next request.
        upstream = retryUpstream;
        activeSessionData = retrySession.data;
        transformedBody = retryBody;
        reqHeaders = retryHeaders;
      } catch {
        // preserve original
      }
    }

    if (!upstream.ok) {
      const errText = await upstream.text().catch(() => "");
      const failure = makeErrorResult(upstream.status, `Dola error: ${errText}`, body, url);
      const retryAfter = upstream.headers.get("Retry-After");
      if (retryAfter) failure.response.headers.set("Retry-After", retryAfter);
      return {
        ...failure,
        headers: reqHeaders,
        transformedBody,
      };
    }

    const contentType = upstream.headers.get("Content-Type") || "";
    if (!contentType.toLowerCase().includes("text/event-stream")) {
      const text = await upstream.text().catch(() => "");
      return {
        ...makeErrorResult(502, `Dola returned non-SSE response: ${text}`, body, url),
        headers: reqHeaders,
        transformedBody,
      };
    }

    if (!wantStream) {
      let { text: content, error: streamError } = await this.collectText(
        upstream,
        modelId,
        activeSessionData,
        signal
      );

      // If Dola returned the bot-side error answer and we were reusing a conversation,
      // reset the rotator and retry once with a brand new conversation
      if (isDolaErrorAnswer(content) && sessionResult.reused) {
        dolaSessionRotator.reset(accountScope);
        const retrySession = await dolaSessionRotator.acquire({
          scopeKey: accountScope,
          minPrompts,
          maxPrompts,
          createFn: async () => ({
            localConversationId: `local_${randomNumericId(16)}`,
          }),
        });
        const retryBody = buildDolaPayload(
          prompt,
          modelId,
          cookieHeader,
          providerSpecificData,
          rawCredential,
          {
            localConversationId: retrySession.data.localConversationId,
            needCreateConversation: true,
          }
        );
        const retryHeaders = this.createHeaders(
          cookieHeader,
          retrySession.data.localConversationId,
          providerSpecificData
        );
        try {
          const retryUpstream = await fetch(url, {
            method: "POST",
            headers: retryHeaders,
            body: JSON.stringify(retryBody),
            signal,
          });
          if (retryUpstream.ok) {
            const retryRes = await this.collectText(
              retryUpstream,
              modelId,
              retrySession.data,
              signal
            );
            if (!isDolaErrorAnswer(retryRes.text) && retryRes.text.trim()) {
              content = retryRes.text;
              streamError = retryRes.error;
              activeSessionData = retrySession.data;
              transformedBody = retryBody;
              reqHeaders = retryHeaders;
            }
          }
        } catch {
          // preserve original
        }
      }

      if (streamError) {
        return {
          ...makeErrorResult(dolaErrorStatus(streamError), streamError, body, url),
          headers: reqHeaders,
          transformedBody,
        };
      }
      if (isDolaBusyMessage(content)) {
        return {
          ...makeErrorResult(429, "Dola is temporarily busy. Please try again later.", body, url),
          headers: reqHeaders,
          transformedBody,
        };
      }
      if (isDolaErrorAnswer(content)) {
        return {
          ...makeErrorResult(
            502,
            "Dola returned an internal conversation error: 'I encountered an error doing what you asked. Could you try again?'",
            body,
            url
          ),
          headers: reqHeaders,
          transformedBody,
        };
      }
      if (!content.trim()) {
        return {
          ...makeErrorResult(
            502,
            "Dola upstream returned an empty response without usable output",
            body,
            url
          ),
          headers: reqHeaders,
          transformedBody,
        };
      }
      return {
        response: new Response(JSON.stringify(openAiCompletion(modelId, content)), {
          headers: { "Content-Type": "application/json" },
        }),
        url,
        headers: reqHeaders,
        transformedBody,
      };
    }

    return {
      response: new Response(this.createStream(upstream, modelId, signal, activeSessionData), {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      }),
      url,
      headers: reqHeaders,
      transformedBody,
    };
  }
}
