import { createHash } from "node:crypto";
import { executorConversation } from "./cookie_conversation.mjs";
export async function readExecutorCompletion(result) {
  const response = result instanceof Response ? result : result?.response;
  if (!(response instanceof Response))
    return { error: "browser_turn_failed", status: 502 };
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = String(body?.error?.message || "");
    const browserFailure = [
      "browser_conversation_lost",
      "browser_draft_present",
      "browser_page_busy",
      "browser_model_unavailable",
      "browser_effort_unavailable",
      "browser_submit_unavailable",
      "browser_response_incomplete",
    ].find((code) => message.includes(code));
    const categories = [
      [
        /first-party.*(?:module|contract)|module.*(?:load|export|contract)/i,
        "browser_module_unavailable",
      ],
      [
        /conversation.*(?:handoff|terminal|assistant|end.turn)|stream decoding|direct.*conversation/i,
        "browser_stream_incomplete",
      ],
      [
        /unsupported model|unsupported reasoning|requires.*(?:body|prompt|messages)|does not support tools/i,
        "browser_request_invalid",
      ],
    ];
    const error =
      browserFailure ||
      categories.find(([pattern]) => pattern.test(message))?.[1] ||
      "browser_turn_failed";
    return { error, status: error === "browser_conversation_lost" ? 409 : response.status };
  }
  const body = await response.json();
  const message = body.choices?.[0]?.message;
  let text = message?.content;
  if (Array.isArray(message?.tool_calls) && message.tool_calls.length) {
    try {
      text = JSON.stringify({
        text: text || "",
        tool_calls: message.tool_calls.map((call) => ({
          name: call.function.name,
          arguments: JSON.parse(call.function.arguments),
        })),
      });
    } catch {
      return { error: "browser_stream_incomplete", status: 502 };
    }
  }
  if (typeof text !== "string" || !text.trim())
    return { error: "empty_browser_response", status: 502 };
  return { text };
}

export const WEB_EXECUTORS = {
  "qwen-browser": {
    registry: "qwen-browser",
    export: "qwen_browserProvider",
    executor: "qwen-browser",
    class: "QwenBrowserExecutor",
  },
  "doubao-web": {
    registry: "doubao/web",
    export: "doubao_webProvider",
    executor: "doubao-web",
    class: "DoubaoWebExecutor",
  },
  "gemini-web": {
    registry: "gemini/web",
    export: "gemini_webProvider",
    executor: "gemini-web",
    class: "GeminiWebExecutor",
  },
  "deepseek-web": {
    registry: "deepseek/web",
    export: "deepseek_webProvider",
    executor: "deepseek-web",
    class: "DeepSeekWebExecutor",
  },
  "kimi-web": {
    registry: "kimi/web",
    export: "kimi_webProvider",
    executor: "kimi-web",
    class: "KimiWebExecutor",
  },
  "muse-spark-web": {
    registry: "muse-spark-web",
    export: "muse_spark_webProvider",
    executor: "muse-spark-web",
    class: "MuseSparkWebExecutor",
  },
  "grok-web": {
    registry: "grok-web",
    export: "grok_webProvider",
    executor: "grok-web",
    class: "GrokWebExecutor",
  },
  "claude-web": {
    registry: "claude/web",
    export: "claude_webProvider",
    executor: "claude-web",
    class: "ClaudeWebExecutor",
  },
  "perplexity-web": {
    registry: "perplexity/web",
    export: "perplexity_webProvider",
    executor: "perplexity-web",
    class: "PerplexityWebExecutor",
  },
  "zai-web": {
    registry: "zai-web",
    export: "zai_webProvider",
    executor: "zai-web",
    class: "ZaiWebExecutor",
  },
};

export function sessionIdentity(provider, captured, snapshot) {
  const primary = {
    "doubao-web": "sessionid",
    "gemini-web": "__Secure-1PSID",
    "muse-spark-web": "ecto_1_sess",
  }[provider];
  const session = primary
    ? snapshot.storage_state.cookies.find((cookie) => cookie.name === primary)
        ?.value
    : captured.data.token ||
      captured.data.userToken ||
      captured.data.accessToken ||
      captured.apiKey;
  if (!session) throw new Error("Provider session cookie is unavailable");
  return createHash("sha256")
    .update(provider + ":" + session)
    .digest("hex");
}

export function browserModelMetadata(provider, routes) {
  return routes
    .filter(
      (route) => provider !== "qwen-browser" || route.id === "qwen3.7-plus",
    )
    .map((route) => ({
      id: provider + "/" + route.id,
      display_name: route.name,
      supports_vision: false,
      supports_tool_calling: false,
      local_tool_bridge: true,
      supports_reasoning: route.supportsReasoning === true,
      effort_tiers: [
        ...(route.supportedThinkingEfforts ||
          (provider === "kimi-web" ? ["none", "low"] : [])),
      ],
      access_verified: false,
      context_limits_available: false,
    }));
}

export async function cookieProviderMain(input, load) {
  const provider = input.provider_id;
  if (provider === "muse-spark-web" && input.mode !== "check") return {error:"cookie_only_unsupported",status:400};
  const spec = WEB_EXECUTORS[provider];
  if (!spec) throw new Error("Unsupported cookie provider");
  const registryModule = await load(
    `open-sse/config/providers/registry/${spec.registry}/index.ts`,
  );
  const registry =
    registryModule[spec.export] ||
    Object.values(registryModule).find((value) => value?.id === provider);
  if (input.mode === "check")
    return {
      ready: true,
      provider,
      models: browserModelMetadata(provider, registry.models),
    };
  const { normalizeSnapshot } = await load("scripts/ops/webSessionSyncCore.ts");
  const snapshot = {
    storage_state: input.storage_state,
    user_agent: input.user_agent || "",
  };
  const capture = (snapshot) =>
    normalizeSnapshot(provider, {
      cookies: snapshot.storage_state.cookies,
      storage: Object.fromEntries(
        snapshot.storage_state.origins.flatMap((origin) =>
          origin.localStorage.map((item) => [item.name, item.value]),
        ),
      ),
      userAgent: snapshot.user_agent || "",
      ...(snapshot.authorization
        ? { authorization: snapshot.authorization }
        : {}),
    });
  const captured = capture(snapshot);
  if (!captured) return { error: "sign_in_required", status: 401 };
  // Bind a saved connector to this authenticated session. A changed identity
  // requires reconnecting rather than silently running as another account.
  const subject = sessionIdentity(provider, captured, snapshot);
  if (input.subject && input.subject !== subject)
    return { error: "account_changed", status: 401 };
  const models = browserModelMetadata(provider, registry.models);
  let text;
  let conversation;
  if (input.mode === "complete") {
    if (!models.some((model) => model.id === input.payload.model))
      return { error: "model_not_available_for_account", status: 400 };
    const module = await load(`open-sse/executors/${spec.executor}.ts`);
    const executor = new module[spec.class]();
    const body =
      provider === "qwen-browser"
        ? {
            ...input.payload,
            messages: [
              {
                role: "user",
                content: input.payload.messages
                  .map((m) => `${m.role}: ${m.content}`)
                  .join("\n\n"),
              },
            ],
            metadata: { session_id: input.conversation?.key },
          }
        : input.payload;
    const execution = await executorConversation(
      provider,
      module,
      executor,
      input,
      captured,
      () =>
        executor.execute({
          model: input.payload.model.slice(provider.length + 1),
          body,
          stream: false,
          credentials: {
            connectionId: input.account_id || "",
            apiKey: captured.apiKey,
            providerSpecificData: captured.data,
          },
          signal: AbortSignal.timeout(input.timeout || 240000),
        }),
    );
    if (execution.error) return execution;
    const completion = await readExecutorCompletion(execution.result);
    if (completion.error) return completion;
    text = completion.text;
    conversation = execution.conversation;
  }
  return {
    subject,
    email: "",
    provider_id: provider,
    models,
    storage_state: snapshot.storage_state,
    cookie_store_id: input.cookie_store_id,
    user_agent: input.user_agent,
    ...(text !== undefined ? { text } : {}),
    ...(conversation ? { conversation } : {}),
  };
}
