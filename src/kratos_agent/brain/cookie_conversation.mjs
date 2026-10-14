/* Persist the real executor conversation IDs across the private pipe workers. */
import { createHash } from "node:crypto";

export function sseConversation(provider, raw, sent) {
  let parent;
  for (const line of raw.split(/\r?\n/)) {
    if (!line.startsWith("data:")) continue;
    let event;
    try { event = JSON.parse(line.slice(5).trim()); } catch { continue; }
    if (provider === "deepseek-web" && Number.isSafeInteger(event.response_message_id) && event.response_message_id > 0)
      parent = event.response_message_id;
  }
  if (provider === "deepseek-web" && typeof sent?.chat_session_id === "string" && parent)
    return { chat_session_id: sent.chat_session_id, parent_message_id: parent };
  return null;
}

export function kimiConversation(module, bytes) {
  let offset = 0, chatId, parentId;
  while (offset < bytes.length) {
    const { consumed, frame } = module.decodeConnectFrame(bytes, offset);
    if (consumed <= 0) break;
    offset += consumed;
    const event = frame?.message;
    if (typeof event?.chat?.id === "string" && event.chat.id) chatId = event.chat.id;
    if (typeof event?.chat_id === "string" && event.chat_id) chatId = event.chat_id;
    if (event?.message?.role === "assistant" && typeof event.message.id === "string" && event.message.id)
      parentId = event.message.id;
  }
  return chatId && parentId ? { chat_id: chatId, parent_id: parentId } : null;
}

export async function executorConversation(provider, module, executor, input, captured, execute) {
  const prior = input.conversation?.new ? null : input.conversation?.native;
  let native = null;
  let lost = false;
  const originalFetch = globalThis.fetch;
  const reads = [];
  let restoreRotator;
  let qwenKey;
  if (provider === "deepseek-web" && prior?.chat_session_id) {
    const token = module.extractUserToken({ apiKey: captured.apiKey, providerSpecificData: captured.data });
    if (!token) throw new Error("Missing DeepSeek session credential");
    module.sessionCache.set(token, { sessionId: prior.chat_session_id, createdAt: Date.now(), promptCount: 0, maxPrompts: 1000 });
  }
  if (provider === "doubao-web") {
    const rotator = module.dolaSessionRotator;
    const acquire = rotator.acquire;
    const reset = rotator.reset;
    rotator.acquire = async options => {
      if (lost) throw new Error("Browser conversation context was lost");
      native = prior?.localConversationId ? { ...prior } : await options.createFn();
      return { data: native, reused: !!prior?.conversationId, rotated: false };
    };
    rotator.reset = () => { lost = true; };
    restoreRotator = () => { rotator.acquire = acquire; rotator.reset = reset; };
  }
  if (provider === "qwen-browser") {
    qwenKey = createHash("sha256").update(JSON.stringify([
      input.account_id || "", captured.data.token, input.payload.model.slice(provider.length + 1), input.conversation?.key,
    ])).digest("hex");
    if (prior?.chatId && prior.responseId) executor.conversations.set(qwenKey, {
      ...prior, completed: 0, exchanges: [], summary: "", updatedAt: Date.now(),
    });
  }
  globalThis.fetch = async (url, options = {}) => {
    const endpoint = new URL(String(url));
    const deepseek = provider === "deepseek-web" && endpoint.origin === "https://chat.deepseek.com" && endpoint.pathname === "/api/v0/chat/completion";
    const kimi = provider === "kimi-web" && endpoint.origin === "https://www.kimi.ai" && endpoint.pathname === "/apiv2/kimi.gateway.chat.v1.ChatService/Chat";
    let sent;
    if (deepseek && typeof options.body === "string") {
      sent = JSON.parse(options.body);
      if (prior?.chat_session_id === sent.chat_session_id) sent.parent_message_id = prior.parent_message_id;
      options = { ...options, body: JSON.stringify(sent) };
    }
    if (kimi && prior?.chat_id && options.body instanceof Uint8Array) {
      const { frame } = module.decodeConnectFrame(options.body, 0);
      const request = frame?.message;
      if (!request?.message) throw new Error("Invalid Kimi conversation request");
      request.chat_id = prior.chat_id;
      request.message.parent_id = prior.parent_id;
      options = { ...options, body: module.frameConnectMessage(JSON.stringify(request)) };
    }
    if (provider === "deepseek-web" && prior?.chat_session_id && endpoint.pathname === "/api/v0/chat_session/create") {
      lost = true;
      throw new Error("Browser conversation context was lost");
    }
    const response = await originalFetch(url, options);
    if ((deepseek || kimi) && response.ok && response.body) {
      const copy = response.clone();
      const readMetadata = (async () => {
        const reader = copy.body.getReader();
        const decoder = new TextDecoder();
        let size = 0, raw = "";
        const chunks = [];
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            size += value.byteLength;
            if (size > 16 * 1024 * 1024) throw new Error("Browser stream metadata limit exceeded");
            if (kimi) chunks.push(value);
            else {
              raw += decoder.decode(value, { stream: true });
              const observed = sseConversation(provider, raw, sent);
              if (observed) { native = observed; break; }
            }
          }
          if (kimi) {
            const bytes = new Uint8Array(size);
            let position = 0;
            for (const chunk of chunks) { bytes.set(chunk, position); position += chunk.length; }
            native = kimiConversation(module, bytes);
          } else native = native || sseConversation(provider, raw, sent);
        } finally { void reader.cancel().catch(() => {}); }
      })();
      readMetadata.catch(() => {});
      reads.push(readMetadata);
    }
    return response;
  };
  try {
    const result = await execute();
    await Promise.all(reads);
    if (lost) return { error: "browser_conversation_lost", status: 409 };
    if (qwenKey) {
      const actual = executor.conversations.get(qwenKey);
      if (actual?.chatId && actual.responseId) native = { chatId: actual.chatId, responseId: actual.responseId };
    }
    return { result, ...(native ? { conversation: { native } } : {}) };
  } finally {
    globalThis.fetch = originalFetch;
    restoreRotator?.();
  }
}
