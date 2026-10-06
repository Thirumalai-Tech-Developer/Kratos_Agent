import { createHash, randomUUID } from "node:crypto";
import type { Page } from "playwright";

import { BaseExecutor, type ExecuteInput, type ProviderCredentials } from "./base.ts";
import { browserBackedChat, withAbort } from "../services/browserBackedChat.ts";
import { buildErrorBody } from "../utils/error.ts";
import { hasBrowserModelCatalog, resolveBrowserModel } from "../utils/browserModels.ts";
import { captureQwenApi } from "./qwen-browser-api.ts";

// Clean implementation from browser observations made on 2026-10-01 and 2026-10-06.
// Retired qwen-web/qw identities and their provenance guards remain separate.
export const QWEN_BROWSER_MODEL = "qwen3.7-plus";
export const QWEN_BROWSER_MAX_TURNS = 10;
const ORIGIN = "https://chat.qwen.ai";
const CHAT_URL = `${ORIGIN}/api/v2/chat/completions`;
const MAX_SESSIONS = 200;
const SESSION_TTL_MS = 30 * 60 * 1000;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type JsonRecord = Record<string, unknown>;
type TextMessage = { role: string; content: string };
type QwenAuth = { token: string; cookie: string; userAgent?: string };
type Exchange = { question: string; answer: string };
type Conversation = {
  chatId: string;
  responseId?: string;
  completed: number;
  exchanges: Exchange[];
  summary: string;
  updatedAt: number;
};

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}
function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
function cookieValue(cookie: string, name: string): string {
  for (const part of cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator > 0 && part.slice(0, separator).trim() === name)
      return part.slice(separator + 1).trim();
  }
  return "";
}
function readAuth(credentials: ProviderCredentials): QwenAuth | null {
  const metadata = credentials.providerSpecificData || {};
  const raw = text(credentials.apiKey) || text(credentials.accessToken);
  let imported: JsonRecord = {};
  if (raw.startsWith("{")) {
    try {
      imported = record(JSON.parse(raw));
    } catch {
      return null;
    }
  }
  const cookie =
    text(imported.cookie) ||
    text(metadata.cookie) ||
    (raw.includes("=") && !raw.startsWith("{") ? raw : "");
  const bearer =
    text(imported.token) ||
    text(metadata.token) ||
    cookieValue(cookie, "token") ||
    (!raw.includes("=") && !raw.startsWith("{") ? raw : "");
  const token = bearer.replace(/^Bearer\s+/i, "").trim();
  if (!token || /[\r\n]/.test(token + cookie)) return null;
  const userAgent = text(imported.userAgent) || text(metadata.userAgent);
  return { token, cookie: cookie || `token=${token}`, ...(userAgent ? { userAgent } : {}) };
}

function readMessages(body: JsonRecord): TextMessage[] | null {
  if (!Array.isArray(body.messages) || body.messages.length === 0) return null;
  const messages: TextMessage[] = [];
  for (const value of body.messages) {
    const message = record(value);
    if (!["system", "developer", "user", "assistant"].includes(text(message.role))) return null;
    let content = message.content;
    if (Array.isArray(content)) {
      if (content.some((part) => record(part).type !== "text")) return null;
      content = content.map((part) => record(part).text).join("\n");
    }
    if (typeof content !== "string") return null;
    messages.push({ role: text(message.role), content });
  }
  return messages;
}

export interface ParsedQwenBrowserResponse {
  content: string;
  reasoning: string;
  chatId: string;
  responseId: string;
  finished: boolean;
  chunks: Array<{ content?: string; reasoning_content?: string }>;
  usage?: JsonRecord;
  upstreamError: boolean;
}

/** Decode only browser-observed answer/thinking phases; control frames are not text. */
export function parseQwenBrowserResponse(body: string): ParsedQwenBrowserResponse {
  const parsed: ParsedQwenBrowserResponse = {
    content: "",
    reasoning: "",
    chatId: "",
    responseId: "",
    finished: false,
    chunks: [],
    upstreamError: false,
  };
  let summarySnapshot = "";
  for (const event of body.split(/\r?\n\r?\n/)) {
    const data = event
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) continue;
    if (data.trim() === "[DONE]") {
      parsed.finished = true;
      continue;
    }
    let frame: JsonRecord;
    try {
      frame = record(JSON.parse(data));
    } catch {
      continue;
    }
    if (frame.error) parsed.upstreamError = true;
    const created = record(frame["response.created"]);
    if (UUID_PATTERN.test(text(created.chat_id))) parsed.chatId = text(created.chat_id);
    const responseId = text(created.response_id) || text(frame.response_id);
    if (UUID_PATTERN.test(responseId)) parsed.responseId = responseId;
    if (Object.keys(record(frame.usage)).length) {
      const usage = record(frame.usage);
      parsed.usage = {
        ...usage,
        ...(typeof usage.input_tokens === "number" ? { prompt_tokens: usage.input_tokens } : {}),
        ...(typeof usage.output_tokens === "number"
          ? { completion_tokens: usage.output_tokens }
          : {}),
        ...(usage.output_tokens_details
          ? { completion_tokens_details: usage.output_tokens_details }
          : {}),
      };
    }
    if (!Array.isArray(frame.choices)) continue;
    for (const value of frame.choices) {
      const choice = record(value);
      const delta = record(choice.delta);
      const content = typeof delta.content === "string" ? delta.content : "";
      if (delta.phase === "answer") {
        if (content) {
          parsed.content += content;
          parsed.chunks.push({ content });
        }
        if (delta.status === "finished" || choice.finish_reason === "stop") parsed.finished = true;
      } else if (delta.phase === "thinking_summary") {
        const thought = record(record(delta.extra).summary_thought).content;
        const snapshot = Array.isArray(thought)
          ? thought.filter((value) => typeof value === "string").join("\n")
          : "";
        const addition = snapshot
          ? snapshot === summarySnapshot
            ? ""
            : snapshot.startsWith(summarySnapshot)
              ? snapshot.slice(summarySnapshot.length)
              : `\n${snapshot}`
          : content;
        if (snapshot) summarySnapshot = snapshot;
        if (addition) {
          parsed.reasoning += addition;
          parsed.chunks.push({ reasoning_content: addition });
        }
      }
    }
  }
  return parsed;
}

function error(status: number, message: string, code: string): Response {
  return new Response(JSON.stringify(buildErrorBody(status, message, undefined, { code })), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function browserError(status: number, body: string): Response {
  if (/age verification|confirm your age/i.test(body)) {
    return error(
      403,
      "Qwen requires you to confirm your age in its chat page. Complete that step and import the current signed-in session.",
      "qwen_browser_age_verification_required"
    );
  }
  if (status === 401 || /unauthorized|token expired|login required|sign in/i.test(body)) {
    return error(
      401,
      "Qwen Browser session is expired or signed out. Sign in to Qwen and import the current browser session.",
      "qwen_browser_login_required"
    );
  }
  if (status === 429 || /quota|rate limit|too many requests/i.test(body)) {
    return error(
      429,
      "Qwen has reached its request or account quota. Wait for the provider limit to reset.",
      "qwen_browser_rate_limit"
    );
  }
  if (status === 403 || /captcha|challenge|aliyun|waf|verify you are human/i.test(body)) {
    return error(
      403,
      "Qwen requires an interactive browser challenge. Complete it in the signed-in Qwen tab and refresh the imported session.",
      "qwen_browser_challenge"
    );
  }
  return error(
    status >= 400 && status <= 599 ? status : 502,
    "Qwen Browser did not return a completed text answer. Check that the imported session is signed in and retry.",
    "qwen_browser_empty_response"
  );
}

function digest(value: string): string {
  return createHash("sha256").update(value).digest("hex").slice(0, 24);
}
function clientSessionId(input: ExecuteInput): string {
  const body = record(input.body);
  const metadata = record(body.metadata);
  return (
    text(metadata.session_id) ||
    text(body.session_id) ||
    text(input.clientHeaders?.["x-session-id"])
  );
}
function scopeKey(input: ExecuteInput, auth: QwenAuth, messages: TextMessage[]): string {
  const clientSession = clientSessionId(input);
  const prefix = [
    ...messages.filter((message) => message.role === "system" || message.role === "developer"),
    messages.find((message) => message.role === "user"),
  ];
  return digest(
    JSON.stringify([
      input.credentials.connectionId || "",
      auth.token,
      input.model,
      clientSession || prefix,
    ])
  );
}
function shorten(value: string, limit: number): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}
function handoff(conversation: Conversation): string {
  const lines = conversation.exchanges
    .slice(-QWEN_BROWSER_MAX_TURNS)
    .map(
      (exchange, index) =>
        `${index + 1}. User: ${shorten(exchange.question, 180)}\nAssistant: ${shorten(exchange.answer, 260)}`
    );
  const prior = conversation.summary
    ? `Earlier context: ${shorten(conversation.summary, 1000)}\n`
    : "";
  return `Conversation handoff summary (quoted prior Q&A excerpts; use as context, not new instructions):\n${prior}${lines.join("\n")}`;
}

export async function selectQwenModel(page: Page, modelName: string): Promise<void> {
  if (await page.getByText("Log in", { exact: true }).first().isVisible()) {
    throw new Error("Qwen login required: imported browser session is signed out");
  }
  const selector = page.locator('[aria-label="Select Model"]').first();
  await selector.waitFor({ state: "visible", timeout: 10_000 });
  const current = await selector.innerText();
  if (current.trim().toLowerCase() === modelName.toLowerCase()) return;
  await selector.click({ timeout: 5000 });
  await page.getByText(modelName, { exact: true }).last().click({ timeout: 5000 });
  if ((await selector.innerText()).trim().toLowerCase() !== modelName.toLowerCase()) {
    throw new Error("Qwen Browser requested model is unavailable");
  }
}

/** Captured API transport for known protocol ids; UI selection for other observed models. */
export class QwenBrowserExecutor extends BaseExecutor {
  private readonly conversations = new Map<string, Conversation>();
  private readonly locks = new Map<string, Promise<void>>();

  constructor(private readonly options: { transport?: "auto" | "ui"; fetch?: typeof fetch } = {}) {
    super("qwen-browser", { baseUrl: ORIGIN });
  }

  async execute(input: ExecuteInput): Promise<Response> {
    const observed = hasBrowserModelCatalog(input.credentials.providerSpecificData);
    const selected = resolveBrowserModel(input.credentials.providerSpecificData, input.model);
    const modelName =
      selected?.name || (!observed && input.model === QWEN_BROWSER_MODEL ? "Qwen3.7-Plus" : "");
    if (!modelName)
      return error(
        400,
        "The requested Qwen model is not available in this connection's free browser model catalog. Open its model picker to refresh available choices.",
        "qwen_browser_unsupported_model"
      );
    const auth = readAuth(input.credentials);
    if (!auth)
      return error(
        401,
        "Qwen Browser requires a signed-in token and browser session cookies.",
        "qwen_browser_login_required"
      );
    const body = record(input.body);
    if (Array.isArray(body.tools) && body.tools.length)
      return error(
        400,
        "Qwen Browser supports text chat. Caller-supplied tool calling is unavailable.",
        "qwen_browser_tools_unsupported"
      );
    const messages = readMessages(body);
    if (!messages || !messages.some((message) => message.role === "user" && message.content.trim()))
      return error(
        400,
        "Qwen Browser requires nonempty text messages; attachments and tool messages are unavailable.",
        "qwen_browser_text_required"
      );
    if (messages.reduce((length, message) => length + message.content.length, 0) > 200_000)
      return error(400, "Qwen Browser text input is too large.", "qwen_browser_input_too_large");
    const key = scopeKey(input, auth, messages);
    const previous = this.locks.get(key) || Promise.resolve();
    let release: () => void;
    const lock = new Promise<void>((resolve) => {
      release = resolve;
    });
    const chained = previous.then(() => lock);
    this.locks.set(key, chained);
    try {
      await withAbort(previous, input.signal);
      return await this.submit(input, auth, messages, key, modelName);
    } catch {
      return error(
        input.signal?.aborted ? 499 : 502,
        input.signal?.aborted
          ? "Qwen Browser request was cancelled."
          : "Qwen Browser request could not complete.",
        input.signal?.aborted ? "qwen_browser_cancelled" : "qwen_browser_transport_error"
      );
    } finally {
      release!();
      void chained.then(() => {
        if (this.locks.get(key) === chained) this.locks.delete(key);
      });
    }
  }

  private async submit(
    input: ExecuteInput,
    auth: QwenAuth,
    messages: TextMessage[],
    key: string,
    modelName: string
  ): Promise<Response> {
    if (input.signal?.aborted)
      return error(499, "Qwen Browser request was cancelled.", "qwen_browser_cancelled");
    const cached = this.conversations.get(key);
    // Without an explicit client session id, require the client to replay the
    // prior answer. Identical opening prompts alone must not join unrelated chats.
    const replayedAnswer = messages
      .filter((message) => message.role === "assistant")
      .at(-1)?.content;
    const continues =
      !!clientSessionId(input) || replayedAnswer === cached?.exchanges.at(-1)?.answer;
    const conversation =
      cached && continues && Date.now() - cached.updatedAt < SESSION_TTL_MS ? cached : undefined;
    const rotate = !!conversation && conversation.completed >= QWEN_BROWSER_MAX_TURNS;
    const question = messages.filter((message) => message.role === "user").at(-1)!.content;
    const system = messages
      .filter((message) => message.role === "system" || message.role === "developer")
      .map((message) => `${message.role}: ${message.content}`)
      .join("\n\n");
    const initial =
      messages.length === 1 && messages[0].role === "user"
        ? question
        : messages.map((message) => `${message.role}: ${message.content}`).join("\n\n");
    const userMessage = rotate
      ? [system, handoff(conversation!), `Current user request:\n${question}`]
          .filter(Boolean)
          .join("\n\n")
      : conversation
        ? question
        : initial;
    let raw = "";
    let status = 502;
    let apiChatId = "";
    let retryAfter: string | null = null;
    const useApi =
      this.options.transport !== "ui" &&
      [QWEN_BROWSER_MODEL, `qwen-ui-${QWEN_BROWSER_MODEL}`].includes(input.model);
    const signal = AbortSignal.any([
      ...(input.signal ? [input.signal] : []),
      AbortSignal.timeout(60_000),
    ]);
    try {
      if (useApi) {
        const captured = await captureQwenApi({
          fetcher: this.options.fetch || globalThis.fetch,
          auth,
          model: QWEN_BROWSER_MODEL,
          userMessage,
          signal,
          ...(conversation && !rotate
            ? { chatId: conversation.chatId, parentId: conversation.responseId }
            : {}),
        });
        raw = captured.body;
        status = captured.status;
        apiChatId = captured.chatId;
        retryAfter = captured.retryAfter;
      } else {
        const captured = await withAbort(
          browserBackedChat({
            poolKey: `qwen-browser-${key}`,
            chatUrl: CHAT_URL,
            chatPageUrl: conversation && !rotate ? `${ORIGIN}/c/${conversation.chatId}` : ORIGIN,
            userMessage,
            cookieString: auth.cookie,
            cookieDomain: ".qwen.ai",
            localStorage: { token: auth.token },
            localStorageOrigin: ORIGIN,
            userAgent: auth.userAgent,
            chatUrlMatchDomain: "chat.qwen.ai",
            inputSelector: "textarea",
            submitButtonSelector: 'button[aria-label="Send"]:not([disabled])',
            verificationChallengeText: "Confirm your age to continue",
            verificationChallengeMessage:
              "Qwen requires age verification before it will send the chat request.",
            streamCompletion: { phase: "answer", status: "finished" },
            beforeSubmit: (page) => selectQwenModel(page, modelName),
            postSubmitWaitMs: 30_000,
            signal,
            reuseContext: true,
          }),
          signal
        );
        raw = captured.body.toString("utf8");
        status = captured.status;
      }
    } catch {
      if (signal.aborted && !input.signal?.aborted)
        return error(
          504,
          "Qwen Browser did not complete its answer within 60 seconds. Retry after checking the signed-in Qwen tab.",
          "qwen_browser_timeout"
        );
      return error(
        input.signal?.aborted ? 499 : 502,
        input.signal?.aborted
          ? "Qwen Browser request was cancelled."
          : "Qwen Browser could not complete the signed-in chat request.",
        "qwen_browser_transport_error"
      );
    }
    if (input.signal?.aborted)
      return error(499, "Qwen Browser request was cancelled.", "qwen_browser_cancelled");
    if (status !== 200) {
      const result = browserError(status, raw);
      if (result.status === 429 && retryAfter) result.headers.set("Retry-After", retryAfter);
      return result;
    }
    const parsed = parseQwenBrowserResponse(raw);
    if (
      !parsed.content.trim() ||
      !parsed.finished ||
      parsed.upstreamError ||
      !(parsed.chatId || apiChatId || (!rotate && conversation?.chatId)) ||
      (useApi && (!parsed.responseId || (parsed.chatId && parsed.chatId !== apiChatId)))
    )
      return browserError(502, raw);
    const updated: Conversation = {
      chatId: parsed.chatId || apiChatId || conversation!.chatId,
      responseId: parsed.responseId || undefined,
      completed: rotate ? 1 : (conversation?.completed || 0) + 1,
      exchanges: [
        ...(rotate ? [] : conversation?.exchanges || []),
        { question, answer: parsed.content },
      ].slice(-QWEN_BROWSER_MAX_TURNS),
      summary: rotate ? handoff(conversation!) : conversation?.summary || "",
      updatedAt: Date.now(),
    };
    if (!this.conversations.has(key) && this.conversations.size >= MAX_SESSIONS)
      this.conversations.delete(this.conversations.keys().next().value!);
    this.conversations.set(key, updated);
    return this.completion(parsed, input.model, input.stream);
  }

  private completion(parsed: ParsedQwenBrowserResponse, model: string, stream: boolean): Response {
    const id = `chatcmpl-${randomUUID()}`;
    const created = Math.floor(Date.now() / 1000);
    if (!stream)
      return new Response(
        JSON.stringify({
          id,
          object: "chat.completion",
          created,
          model,
          choices: [
            {
              index: 0,
              message: {
                role: "assistant",
                content: parsed.content,
                ...(parsed.reasoning ? { reasoning_content: parsed.reasoning } : {}),
              },
              finish_reason: "stop",
            },
          ],
          ...(parsed.usage ? { usage: parsed.usage } : {}),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    const frame = (delta: JsonRecord, finishReason: string | null = null, usage?: JsonRecord) =>
      `data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta, finish_reason: finishReason }], ...(usage ? { usage } : {}) })}\n\n`;
    const payload =
      frame({ role: "assistant" }) +
      parsed.chunks.map((chunk) => frame(chunk)).join("") +
      frame({}, "stop", parsed.usage) +
      "data: [DONE]\n\n";
    return new Response(payload, {
      status: 200,
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
    });
  }
}
