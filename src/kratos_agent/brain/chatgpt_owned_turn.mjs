// Executor-owned cookie browser. These helpers never run in the extension.
export const CHATGPT_SEND_SELECTOR =
  '[data-testid="send-button"], button[aria-label="Send"], button[aria-label="Send prompt"], button[aria-label="Send message"]';
export async function runOwnedCookieTurn(
  page,
  selection,
  request,
  insertPlainTextIntoComposer,
  parseHandoff,
  options = {},
) {
  const signal = request.signal;
  const requireActive = () => {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  };
  const fail = (code) => {
    const e = new Error(code);
    e.code = code;
    throw e;
  };
  requireActive();
  options.phase?.("model-selection");
  const model = await page.evaluate(chatgptComposerSelection, selection);
  if (!model?.modelSelected) fail(model?.error || "browser_model_unavailable");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  options.phase?.("effort-selection");
  const effort = await page.evaluate(chatgptEffortSelection, selection);
  if (!effort || effort.error)
    fail(effort?.error || "browser_effort_unavailable");
  const target = effort.min + selection.effortIndex;
  if (!Number.isInteger(target) || target < effort.min || target > effort.max)
    fail("browser_effort_unavailable");
  let current = effort;
  for (
    let step = 0;
    current.value !== target && step <= effort.max - effort.min;
    step++
  ) {
    requireActive();
    const direction = target > current.value ? 1 : -1;
    const previous = current.value;
    await page.keyboard.press(direction > 0 ? "ArrowRight" : "ArrowLeft");
    const deadline = Date.now() + 5000;
    do {
      current = await page.evaluate(chatgptEffortState);
      if (current && current.value !== previous) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    } while (Date.now() < deadline);
    if (
      !current ||
      current.min !== effort.min ||
      current.max !== effort.max ||
      current.value !== previous + direction
    )
      fail("browser_effort_unavailable");
  }
  await page.keyboard.press("Escape");
  if (current.value !== target) fail("browser_effort_unavailable");
  if (options.remote) {
    try {
      await page.waitForFunction(
        (remote) => {
          if (location.pathname !== "/c/" + remote.conversation_id)
            return false;
          return [
            ...document.querySelectorAll(
              "[data-message-id],[data-chatgpt-selection-message-id],[data-chatgpt-search-message-ids],[data-turn-id]",
            ),
          ].some((n) =>
            [
              "data-message-id",
              "data-chatgpt-selection-message-id",
              "data-chatgpt-search-message-ids",
              "data-turn-id",
            ].some((a) =>
              (n.getAttribute(a) || "")
                .split(/\s+/)
                .includes(remote.parent_message_id),
            ),
          );
        },
        options.remote,
        { timeout: 15000 },
      );
    } catch {
      fail("browser_conversation_lost");
    }
  }
  const previousAssistants = await page.evaluate(chatgptAssistantSnapshot);
  options.phase?.("composer");
  const composer = page
    .locator(
      '#prompt-textarea, [contenteditable="true"][role="textbox"], [contenteditable="true"].ProseMirror',
    )
    .filter({ visible: true })
    .last();
  if ((await composer.innerText()).trim()) fail("browser_draft_present");
  if (request.attachments?.length) fail("browser_request_invalid");
  let submittedMessage = null,
    responseBody = null,
    networkFailure = false;
  let capture = Promise.resolve();
  const listener = (response) => {
    try {
      const url = new URL(response.url());
      if (
        url.origin !== "https://chatgpt.com" ||
        !/\/f\/conversation$/.test(url.pathname)
      )
        return;
      const submitted = chatgptSubmittedMessage(
        response.request().postData(),
        request.prompt,
      );
      if (!submitted) return;
      submittedMessage = submitted;
      if (!response.ok()) {
        networkFailure = true;
        options.upstreamStatus?.(response.status());
        return;
      }
      capture = response.text().then(
        (body) => {
          responseBody = body;
        },
        () => {},
      );
    } catch {
      /* Other website responses carry no owned prompt. */
    }
  };
  page.on("response", listener);
  try {
    requireActive();
    options.phase?.("prompt-insertion");
    await composer.focus();
    if (!(await composer.evaluate(insertPlainTextIntoComposer, request.prompt)))
      fail("browser_submit_unavailable");
    const written = await composer.innerText();
    if (
      written.replace(/\s+/g, " ").trim() !==
      request.prompt.replace(/\s+/g, " ").trim()
    )
      fail("browser_submit_unavailable");
    options.phase?.("submission");
    try {
      await page
        .locator(CHATGPT_SEND_SELECTOR)
        .filter({ visible: true })
        .first()
        .click({ timeout: 10000 });
    } catch {
      fail("browser_submit_unavailable");
    }
    options.phase?.("response");
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      requireActive();
      if (networkFailure) fail("browser_turn_failed");
      const completed = await page.evaluate(chatgptCompletedAssistant, {
        prompt: request.prompt,
        previousAssistants,
        submittedMessage,
      });
      if (completed) {
        await capture;
        let conversationId = completed.conversationId;
        if (!conversationId && responseBody) {
          try {
            conversationId = parseHandoff(responseBody).conversationId;
          } catch {
            /* Direct SSE carries the conversation id as JSON. */
          }
          if (!conversationId) {
            for (const line of responseBody.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              try {
                const item = JSON.parse(line.slice(6));
                if (typeof item.conversation_id === "string")
                  conversationId = item.conversation_id;
              } catch {}
            }
          }
        }
        const parent = responseBody
          ? options.completedParent?.(responseBody)
          : undefined;
        return {
          ...completed,
          conversationId,
          turnExchangeId: parent || completed.turnExchangeId,
          status: "finished_successfully",
          endTurn: true,
        };
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    fail("browser_response_incomplete");
  } finally {
    page.off("response", listener);
    if (signal?.aborted)
      await page
        .getByTestId("stop-button")
        .click({ timeout: 500 })
        .catch(() => {});
  }
}
export async function chatgptComposerSelection(selection) {
  const visible = (selector) =>
    [...document.querySelectorAll(selector)].find(
      (node) => node.getClientRects().length,
    );
  const composerDeadline = Date.now() + 15000;
  let input;
  do {
    input = visible(
      '#prompt-textarea, [contenteditable="true"][role="textbox"], [contenteditable="true"].ProseMirror',
    );
    if (input) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  } while (Date.now() < composerDeadline);
  const stop = () =>
    visible(
      '[data-testid="stop-button"], [data-testid="stop-generating-button"], button[aria-label="Stop streaming"], button[aria-label="Stop generating"]',
    );
  if (!input) return { error: "browser_submit_unavailable" };
  if (input.innerText.trim()) return { error: "browser_draft_present" };
  if (stop()) return { error: "browser_page_busy" };
  if (
    selection?.kind !== "picker" ||
    !["GPT-5.5", "GPT-5.6 Sol"].includes(selection.modelLabel)
  )
    return { error: "browser_model_unavailable" };
  const waitFor = async (read) => {
    const deadline = Date.now() + 10000;
    do {
      const value = read();
      if (value) return value;
      await new Promise((resolve) => setTimeout(resolve, 80));
    } while (Date.now() < deadline);
    return null;
  };
  const picker = () =>
    visible(
      '[aria-label="Select ChatGPT model"], [data-testid="model-switcher-dropdown-button"]',
    );
  const items = () =>
    [
      ...document.querySelectorAll(
        '[role="menuitem"], [role="menuitemradio"], [role="option"]',
      ),
    ].filter((item) => item.getClientRects().length);
  const button = await waitFor(picker);
  if (!button) return { error: "browser_model_unavailable" };
  if (button.getAttribute("aria-expanded") !== "true") button.click();
  const matchesModel = (item) => {
    const label = (item.innerText || item.textContent)
      .replace(/\s+/g, " ")
      .trim();
    return (
      label === selection.modelLabel ||
      label.startsWith(selection.modelLabel + " ")
    );
  };
  const first = await waitFor(() =>
    items().find(
      (item) =>
        matchesModel(item) ||
        item.textContent.trim() === "Select model" ||
        item.getAttribute("aria-label") === "Select model",
    ),
  );
  if (!first) return { error: "browser_model_unavailable" };
  if (!matchesModel(first)) first.click();
  const model = await waitFor(() => items().find(matchesModel));
  if (!model) return { error: "browser_model_unavailable" };
  model.click();
  if (
    !(await waitFor(
      () =>
        model.getAttribute("aria-checked") === "true" ||
        !model.isConnected ||
        !model.getClientRects().length,
    ))
  )
    return { error: "browser_model_unavailable" };
  return { modelSelected: true };
}

export function chatgptEffortState() {
  const slider = [...document.querySelectorAll('[role="slider"]')].find(
    (n) => n.getClientRects().length,
  );
  if (!slider) return null;
  const read = (name) => {
    const raw = slider.getAttribute(name);
    return raw === null ? NaN : Number(raw);
  };
  const min = read("aria-valuemin"),
    max = read("aria-valuemax"),
    value = read("aria-valuenow");
  return [min, max, value].every(Number.isInteger) &&
    min <= value &&
    value <= max
    ? { min, max, value }
    : null;
}

export async function chatgptEffortSelection(selection) {
  const picker = [
    ...document.querySelectorAll(
      '[aria-label="Select ChatGPT model"], [data-testid="model-switcher-dropdown-button"]',
    ),
  ].find((n) => n.getClientRects().length);
  if (!picker) return { error: "browser_effort_unavailable" };
  if (picker.getAttribute("aria-expanded") !== "true") picker.click();
  const deadline = Date.now() + 10000;
  do {
    const slider = [...document.querySelectorAll('[role="slider"]')].find(
      (n) => n.getClientRects().length,
    );
    const control = slider?.closest('[role="menuitem"]');
    if (slider && control) {
      const read = (name) => {
        const raw = slider.getAttribute(name);
        return raw === null ? NaN : Number(raw);
      };
      const min = read("aria-valuemin"),
        max = read("aria-valuemax"),
        value = read("aria-valuenow");
      if (
        [min, max, value].every(Number.isInteger) &&
        min <= value &&
        value <= max &&
        min + selection.effortIndex <= max
      ) {
        control.focus();
        return { min, max, value };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 80));
  } while (Date.now() < deadline);
  return { error: "browser_effort_unavailable" };
}

export function chatgptSubmittedMessage(postData, prompt) {
  try {
    const request = JSON.parse(postData);
    const messages =
      request.messages ||
      request.input_messages ||
      (request.message ? [request.message] : []);
    if (!Array.isArray(messages)) return null;
    const message = messages.findLast(
      (item) => (item?.author?.role || item?.role) === "user",
    );
    const parts =
      message?.content?.parts ||
      (typeof message?.content === "string"
        ? [message.content]
        : message?.content);
    if (!Array.isArray(parts) || parts.length !== 1) return null;
    const text = typeof parts[0] === "string" ? parts[0] : parts[0]?.text;
    const normalized = (value) =>
      String(value || "")
        .replace(/\s+/g, " ")
        .trim();
    if (typeof text !== "string" || normalized(text) !== normalized(prompt))
      return null;
    return { id: typeof message.id === "string" ? message.id : "" };
  } catch {
    return null;
  }
}

export function chatgptAssistantSnapshot() {
  const nodes = [
    ...document.querySelectorAll(
      '[data-message-author-role="assistant"], [data-content-search-unit-key$=":assistant"]',
    ),
  ].filter((node) => node.getClientRects().length);
  const key = (node) =>
    node.getAttribute("data-message-id") ||
    node.getAttribute("data-chatgpt-search-message-ids") ||
    node
      .querySelector("[data-chatgpt-selection-message-id]")
      ?.getAttribute("data-chatgpt-selection-message-id") ||
    node.getAttribute("data-content-search-unit-key") ||
    "";
  return { count: nodes.length, keys: nodes.map(key).filter(Boolean) };
}

export function chatgptCompletedAssistant({
  prompt,
  previousAssistants,
  submittedMessage = null,
}) {
  const nodes = [
    ...document.querySelectorAll(
      '[data-message-author-role="assistant"], [data-content-search-unit-key$=":assistant"]',
    ),
  ].filter((node) => node.getClientRects().length);
  const last = nodes.at(-1);
  if (!last) return null;
  const key =
    last.getAttribute("data-message-id") ||
    last.getAttribute("data-chatgpt-search-message-ids") ||
    last
      .querySelector("[data-chatgpt-selection-message-id]")
      ?.getAttribute("data-chatgpt-selection-message-id") ||
    last.getAttribute("data-content-search-unit-key") ||
    "";
  // The website virtualizes older turns: the rendered count can stay constant
  // when a new answer replaces an unmounted old answer. Track stable identity.
  if (typeof previousAssistants === "object" && previousAssistants !== null) {
    if (
      key
        ? previousAssistants.keys.includes(key)
        : nodes.length <= previousAssistants.count
    )
      return null;
  } else if (nodes.length <= previousAssistants) return null;
  const user = [
    ...document.querySelectorAll(
      '[data-message-author-role="user"], [data-user-message-bubble]',
    ),
  ]
    .filter((node) => node.getClientRects().length)
    .at(-1);
  const normalized = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();
  if (!user) return null;
  if (!(user.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING))
    return null;
  const currentMessageIds = user
    .closest("[data-chatgpt-search-message-ids]")
    ?.getAttribute("data-chatgpt-search-message-ids")
    ?.split(/\s+/);
  if (
    submittedMessage?.id &&
    currentMessageIds &&
    !currentMessageIds.includes(submittedMessage.id)
  )
    return null;
  // Large agent prompts are truncated by the website. Expand the new prompt
  // before checking ownership, and exclude its Show more/less controls.
  // innerText preserves paragraph boundaries created by contenteditable input;
  // textContent would join adjacent paragraphs and fail on multiline context.
  let userText = user.innerText.trim();
  for (const button of [...user.querySelectorAll("button")].reverse()) {
    const label = button.innerText.trim();
    if (label && userText.endsWith(label))
      userText = userText.slice(0, -label.length).trim();
  }
  if (!submittedMessage && normalized(userText) !== normalized(prompt)) {
    const expand = [...user.querySelectorAll("button")].find(
      (button) => button.textContent.trim() === "Show more",
    );
    expand?.click();
    return null;
  }
  const article =
    last.closest("[data-talvt-turn-state], article") || last.parentElement;
  const stopped = [
    ...document.querySelectorAll(
      '[data-testid="stop-button"], [data-testid="stop-generating-button"], button[aria-label="Stop streaming"], button[aria-label="Stop generating"]',
    ),
  ].some((node) => node.getClientRects().length);
  const done = article?.querySelector(
    '[data-testid="copy-turn-action-button"], button[aria-label="Copy"], button[aria-label="Copy response"]',
  );
  const failed = article?.querySelector(
    '[role="alert"], [data-testid="conversation-error"]',
  );
  const state = article?.getAttribute("data-talvt-turn-state");
  if (stopped || !done || failed || (state && state !== "complete"))
    return null;
  const text = (
    last.querySelector(
      '[data-markdown-text-style="assistant-message"], .markdown, .prose',
    ) || last
  ).innerText;
  if (!text.trim()) return null;
  return {
    text,
    conversationId:
      location.pathname.match(/^\/c\/([A-Za-z0-9-]+)$/)?.[1] || "",
    turnExchangeId:
      last.getAttribute("data-message-id") ||
      last
        .querySelector("[data-chatgpt-selection-message-id]")
        ?.getAttribute("data-chatgpt-selection-message-id") ||
      last.getAttribute("data-chatgpt-search-message-ids")?.split(/\s+/)[0] ||
      article?.getAttribute("data-turn-id") ||
      "",
  };
}
