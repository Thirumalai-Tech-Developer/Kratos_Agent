// Execute ChatGPT through OmniRoute using a protected browser session.
import { createHash, randomUUID } from "node:crypto";
import { readExecutorCompletion } from "./web_cookie_bridge.mjs";
import { runOwnedCookieTurn } from "./chatgpt_owned_turn.mjs";

const ownedTabs = new Map();
export async function ownedExecutorTab(pooled, key, openPage) {
  const previous = ownedTabs.get(key);
  if (previous && previous.context === pooled.context && !previous.page.isClosed()) {
    previous.used = Date.now();
    return {...previous,reused:true};
  }
  const record = {page:await openPage(pooled),context:pooled.context,instance:randomUUID(),used:Date.now()};
  ownedTabs.set(key,record);
  if (ownedTabs.size>8) {
    const oldest=[...ownedTabs.entries()].filter(([id])=>id!==key).sort((a,b)=>a[1].used-b[1].used)[0];
    ownedTabs.delete(oldest[0]);
    await oldest[1].page.close().catch(()=>{});
  }
  return {...record,reused:false};
}
export function isRemoteConversationPage(url, remote) {
  try {const value=new URL(url);return value.origin==='https://chatgpt.com' && value.pathname==='/c/'+remote.conversation_id;}
  catch {return false;}
}

export function conversationUrl(remote) {
  if (
    !remote?.conversation_id ||
    !remote?.parent_message_id ||
    !/^[A-Za-z0-9-]+$/.test(remote.conversation_id)
  )
    throw new Error("browser_conversation_lost");
  return "https://chatgpt.com/c/" + remote.conversation_id;
}

// No prompt is submitted during these bounded navigation retries.
export async function navigateExecutorPage(
  page,
  url,
  {
    timeout = 15000,
    attempts = 2,
    pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  } = {},
) {
  if (new URL(url).origin !== "https://chatgpt.com")
    throw new Error("Invalid executor origin");
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout });
      return { ok: true };
    } catch (error) {
      const network =
        String(error?.message).match(/net::(ERR_[A-Z_]+)/)?.[1] ||
        (error?.name === "TimeoutError"
          ? "navigation_timeout"
          : "navigation_failed");
      const transient = [
        "ERR_ABORTED",
        "ERR_CONNECTION_RESET",
        "ERR_CONNECTION_CLOSED",
        "ERR_EMPTY_RESPONSE",
        "ERR_NETWORK_CHANGED",
        "ERR_TIMED_OUT",
        "navigation_timeout",
      ].includes(network);
      if (!transient || attempt + 1 === attempts) return { ok: false, network };
      await pause(250);
    }
  }
  return { ok: false, network: "navigation_failed" };
}

export function completedParent(body, Decoder, parseItems) {
  let decoder = new Decoder(),
    parent;
  for (const item of parseItems(body)) {
    if (item.event === "delta_encoding") decoder = new Decoder();
    decoder.ingest(
      (item.event === "message" ? "" : "event: " + item.event + "\n") +
        "data: " +
        item.data +
        "\n\n",
    );
    const message = decoder.snapshot()?.message;
    if (
      message?.author?.role === "assistant" &&
      message.status === "finished_successfully" &&
      message.end_turn === true &&
      typeof message.id === "string"
    )
      parent = message.id;
  }
  return parent;
}

export async function chatgptCookieMain(input, load, supportedAccountModels) {
  const { default: Executor } = await load("open-sse/executors/chatgpt-web.ts");
  const { chatgpt_webProvider: registry } = await load(
    "open-sse/config/providers/registry/chatgpt-web/index.ts",
  );
  if (input.mode === "check")
    return {
      ready: true,
      executor: "chatgpt-web.ts",
      routes: registry.models.length,
    };
  const { normalizeChatGptWebStorageState, resolveChatGptWebChromeExecutable } =
    await load("open-sse/utils/chatgptWebExecutorAdapter.ts");
  const { acquireBrowserContext, openPage, releaseBrowserContext } = await load(
    "open-sse/services/browserPool.ts",
  );
  const { PlaywrightChatGptWebBrowserSession: Session } = await load(
    "open-sse/utils/chatgptWebBrowserSession.ts",
  );
  const { insertPlainTextIntoComposer } = await load(
    "open-sse/vendor/codex-chatgpt-web/adapters/chatgpt-web/composer-edit.ts",
  );
  const { parseChatGptWebConversationHandoff: parseHandoff } = await load(
    "open-sse/utils/chatgptWebTransport.ts",
  );
  const {
    ChatGptWebDeltaV1Decoder: Decoder,
    parseChatGptWebEncodedItem: parseItems,
  } = await load("open-sse/utils/chatgptWebDeltaV1.ts");
  const { buildToolModeResponse } = await load(
    "open-sse/executors/chatgptWebTools.ts",
  );
  const state = normalizeChatGptWebStorageState(input.storage_state);
  const key =
    "kratos-cleanroom:" +
    createHash("sha256")
      .update(JSON.stringify([input.account_id || state, input.persistent ? input.conversation?.key : "one-shot"]))
      .digest("hex");
  const pooled = await acquireBrowserContext(key, {
    cookieDomain: "chatgpt.com",
    storageState: state,
    userAgent: input.user_agent || undefined,
    warmupUrl: null,
    headless: false,
    executablePath: resolveChatGptWebChromeExecutable(),
    proxyProviderKey: "chatgpt-web",
  });
  let keepContext = input.persistent === true;
  try {
    if (input.persistent) await pooled.context.addCookies(state.cookies);
    await pooled.context.addInitScript({
      content: "globalThis.__name = (value) => value;",
    });
    const tab = await ownedExecutorTab(pooled,key,openPage);
    const page = tab.page;
    const remote = input.conversation?.new ? null : input.conversation?.native;
    if (input.conversation && !input.conversation.new && !remote) return {error:"browser_conversation_lost",status:409};
    const failedNavigation = (navigation) => ({
      error: "browser_navigation_failed",
      status: 502,
      ...(input.diagnostic
        ? { phase: "navigation", diagnostic: { network: navigation.network } }
        : {}),
    });
    if (!tab.reused || input.conversation?.new || (remote && !isRemoteConversationPage(page.url(),remote))) {
      const navigation = await navigateExecutorPage(page,remote ? conversationUrl(remote) : 'https://chatgpt.com/');
      if (!navigation.ok) return failedNavigation(navigation);
    }
    const identity = await page.evaluate(async () => {
      try {
        const r = await fetch("/api/auth/session", {
          credentials: "same-origin",
        });
        const s = r.ok ? await r.json() : null;
        return s?.user?.id && s.accessToken
          ? { subject: s.user.id, email: s.user.email || "" }
          : null;
      } catch {
        return null;
      }
    });
    if (!identity) {keepContext=false; return { error: "sign_in_required", status: 401 };}
    if (input.subject && input.subject !== identity.subject) {keepContext=false; return { error: "account_changed", status: 401 };}
    let models = input.models;
    if (input.mode !== "complete" || !Array.isArray(models)) {
      const catalog = await page.evaluate(async () => {
        try {
          const s = await (
            await fetch("/api/auth/session", { credentials: "same-origin" })
          ).json();
          const r = await fetch("/backend-api/models", {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + s.accessToken },
          });
          const b = r.ok ? await r.json() : null;
          return { models: b?.models || b?.data, status: r.status };
        } catch {
          return { status: 502 };
        }
      });
      if (!Array.isArray(catalog.models))
        return {
          error: "account_model_catalog_unavailable",
          status: catalog.status,
        };
      models = supportedAccountModels(registry.models, catalog.models);
    }
    let text, conversation;
    if (input.mode === "complete") {
      if (!models.some((m) => m.id === input.payload.model))
        return { error: "model_not_available_for_account", status: 400 };
      let selection,
        phase = "session",
        upstreamStatus;
      const executor = new Executor({
        createSession: async (options) => {
          selection = options.selection;
          return new Session(page, { selection, closePageOnCleanup: false });
        },
        runTurn: async (_session, request) => {
          const result = await runOwnedCookieTurn(
            page,
            selection,
            request,
            insertPlainTextIntoComposer,
            parseHandoff,
            {
              remote,
              phase: (value) => {
                phase = value;
              },
              completedParent: (body) =>
                completedParent(body, Decoder, parseItems),
              upstreamStatus: (value) => {
                upstreamStatus = value;
              },
            },
          );
          if (result.conversationId && result.turnExchangeId)
            conversation = {
              ...(input.persistent ? {tab_instance:tab.instance} : {}),
              native: {
                conversation_id: result.conversationId,
                parent_message_id: result.turnExchangeId,
              },
            };
          return result;
        },
      });
      const result = await executor.execute({
        model: input.payload.model,
        body: input.payload,
        stream: false,
        credentials: {
          connectionId: input.account_id || key,
          providerSpecificData: { storageState: state },
        },
        signal: AbortSignal.timeout(input.timeout || 240000),
      });
      let response = result instanceof Response ? result : result.response;
      if (response.ok && input.requested_tools?.length)
        response = await buildToolModeResponse(
          response,
          input.requested_tools,
          false,
          {
            cid: key,
            created: Math.floor(Date.now() / 1000),
            model: input.payload.model,
          },
        );
      const completion = await readExecutorCompletion(response);
      if (completion.error)
        return {
          ...completion,
          ...(upstreamStatus ? { status: upstreamStatus } : {}),
          ...(input.diagnostic ? { phase } : {}),
        };
      text = completion.text;
    }
    const refreshed = await pooled.context.storageState();
    const allowed = (host) =>
      ["chatgpt.com", "openai.com"].some(
        (d) => host.replace(/^\./, "") === d || host.endsWith("." + d),
      );
    return {
      ...identity,
      models,
      cookie_store_id: input.cookie_store_id,
      user_agent: input.user_agent,
      storage_state: normalizeChatGptWebStorageState({
        cookies: refreshed.cookies.filter((c) => allowed(c.domain)),
        origins: refreshed.origins.filter((o) =>
          allowed(new URL(o.origin).hostname),
        ),
      }),
      ...(text === undefined ? {} : { text }),
      ...(conversation ? { conversation } : {}),
    };
  } finally {
    if (!keepContext) {ownedTabs.delete(key);await releaseBrowserContext(key);}
  }
}
