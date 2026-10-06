import { randomUUID } from "node:crypto";
import { withAbort } from "../services/browserBackedChat.ts";

const ORIGIN = "https://chat.qwen.ai";
const MAX_BODY_BYTES = 2 * 1024 * 1024;
type JsonRecord = Record<string, unknown>;
export type QwenApiCapture = {
  status: number;
  body: string;
  chatId: string;
  retryAfter: string | null;
};
type ApiRequest = {
  fetcher: typeof fetch;
  auth: { token: string; cookie: string; userAgent?: string };
  model: string;
  userMessage: string;
  chatId?: string;
  parentId?: string;
  signal: AbortSignal;
};
function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}
function terminal(event: string): boolean {
  const data = event
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (data.trim() === "[DONE]") return true;
  try {
    const frame = record(JSON.parse(data));
    if (frame.error) return true;
    return (
      Array.isArray(frame.choices) &&
      frame.choices.some((value) => {
        const choice = record(value);
        const delta = record(choice.delta);
        return (
          delta.phase === "answer" &&
          (delta.status === "finished" || choice.finish_reason === "stop")
        );
      })
    );
  } catch {
    return false;
  }
}

/** A Qwen answer terminal frame can arrive before the HTTP connection closes. */
async function readBody(response: Response, signal: AbortSignal, sse: boolean): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let body = "";
  let pending = "";
  try {
    for (;;) {
      const { done, value } = await withAbort(reader.read(), signal);
      if (done) return body + decoder.decode();
      bytes += value.byteLength;
      if (bytes > MAX_BODY_BYTES) throw new Error("Qwen response exceeded the capture budget");
      const chunk = decoder.decode(value, { stream: true });
      body += chunk;
      if (!sse) continue;
      pending += chunk;
      for (;;) {
        const separator = /\r?\n\r?\n/.exec(pending);
        if (!separator) break;
        const event = pending.slice(0, separator.index);
        pending = pending.slice(separator.index + separator[0].length);
        if (terminal(event)) return body.slice(0, body.length - pending.length);
      }
    }
  } finally {
    // Do not let an upstream connection delay cancellation or hold the session lock.
    void reader.cancel().catch(() => {});
  }
}

/** Normal authenticated requests observed in the user's Oct 6 Qwen browser capture. */
export async function captureQwenApi(request: ApiRequest): Promise<QwenApiCapture> {
  const { fetcher, auth, model, userMessage, signal } = request;
  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    Authorization: `Bearer ${auth.token}`,
    Cookie: auth.cookie,
    Version: "0.3.12",
    source: "h5",
    Timezone: new Date().toString(),
    ...(auth.userAgent ? { "User-Agent": auth.userAgent } : {}),
  };
  const post = (url: string, body: JsonRecord) =>
    withAbort(
      fetcher(url, {
        method: "POST",
        headers: { ...headers, "X-Request-Id": randomUUID(), "X-Accel-Buffering": "no" },
        body: JSON.stringify(body),
        signal,
        redirect: "error",
      }),
      signal
    );
  let chatId = request.chatId || "";
  if (!chatId) {
    const created = await post(`${ORIGIN}/api/v2/chats/new`, {
      chatId: "",
      models: [model],
      project_id: "",
      timestamp: Date.now(),
      chat_type: "t2t",
      chat_mode: "normal",
    });
    const body = await readBody(created, signal, false);
    if (created.status !== 200)
      return {
        status: created.status,
        body,
        chatId: "",
        retryAfter: created.headers.get("retry-after"),
      };
    const payload = record(JSON.parse(body));
    const id = record(payload.data).id;
    if (
      payload.success !== true ||
      typeof id !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
    ) {
      return { status: 502, body, chatId: "", retryAfter: null };
    }
    chatId = id;
  }
  const parentId = request.parentId || null;
  const timestamp = Math.floor(Date.now() / 1000);
  const completion = await post(
    `${ORIGIN}/api/v2/chat/completions?chat_id=${encodeURIComponent(chatId)}`,
    {
      stream: true,
      version: "2.1",
      incremental_output: true,
      chatId,
      chat_id: chatId,
      parentId: parentId || "",
      parent_id: parentId,
      chat_mode: "normal",
      model,
      timestamp,
      messages: [
        {
          id: null,
          fid: randomUUID(),
          parentId,
          parent_id: parentId,
          childrenIds: [randomUUID()],
          role: "user",
          content: userMessage,
          user_action: "chat",
          files: [],
          timestamp,
          models: [model],
          model: "",
          chat_type: "t2t",
          sub_chat_type: "t2t",
          feature_config: {
            thinking_enabled: true,
            output_schema: "phase",
            research_mode: "normal",
            auto_thinking: false,
            thinking_mode: "Thinking",
            thinking_format: "summary",
            auto_search: true,
          },
          extra: { meta: { subChatType: "t2t" } },
        },
      ],
    }
  );
  const sse =
    completion.status === 200 &&
    (completion.headers.get("content-type") || "").includes("text/event-stream");
  const body = await readBody(completion, signal, sse);
  return {
    status: completion.status,
    body,
    chatId,
    retryAfter: completion.headers.get("retry-after"),
  };
}
