/* Observe first-party model pickers only. Chat messages are never model metadata. */
(() => {
  if (globalThis.__kratosModelDiscovery) return;
  const TRANSCRIPT = [
    "[data-message-id]",
    "[data-message-author-role]",
    "[data-testid='conversation-turn']",
    "[data-testid*='message']",
    "[role='log']",
    "article",
    ".message",
    ".markdown",
    "pre",
    "code",
    "[contenteditable='true']",
  ].join(",");
  const MENU_ROOTS = [
    "[data-model-picker]",
    "[data-model-menu]",
    "[data-model-selector-menu]",
    "[data-testid='model-menu']",
    "[data-testid='model-picker']",
    "[data-testid='model-selector-menu']",
    "[role='menu'][aria-label*='model' i]",
    "[role='listbox'][aria-label*='model' i]",
    "select[aria-label*='model' i]",
  ].join(",");
  const MODEL_ROWS = [
    "[data-model-id]",
    "[data-model]",
    "[role='option']",
    "[role='menuitem']",
    "[role='menuitemradio']",
    "[role='radio']",
    "option",
    "button[aria-label='model-item'][data-value]",
  ].join(",");
  const MODEL_ID = /^[a-zA-Z0-9_.:-]+$/;

  function visible(node) {
    if (!node || node.closest("[hidden], [aria-hidden='true']")) return false;
    const style = node.ownerDocument.defaultView.getComputedStyle(node);
    return (
      style.display !== "none" && style.visibility !== "hidden" && node.getClientRects().length > 0
    );
  }

  function booleanAttribute(node, names) {
    for (const name of names) {
      const value = node.getAttribute(name)?.toLowerCase();
      if (value === "true" || value === "1") return true;
      if (value === "false" || value === "0") return false;
    }
    return undefined;
  }

  function modelName(row) {
    const declared = row.getAttribute("data-model-name") || row.getAttribute("data-model-label");
    const label = row.querySelector(
      "[data-model-name], [data-model-label], [data-testid='model-name'], .model-name"
    );
    const text =
      declared ||
      label?.textContent ||
      (row.tagName === "OPTION" ? row.label : row.innerText || row.textContent);
    // A menu row may include a second line describing capabilities; the actual first label is retained.
    const name = String(text || "")
      .trim()
      .split(/\r?\n/)[0]
      .trim();
    return name && name.length <= 120 && !/[\r\n\u0000-\u001f]/.test(name) ? name : null;
  }

  function modelMetadata(row) {
    let supportsVision = booleanAttribute(row, ["data-supports-vision", "data-vision"]);
    let supportsThinking = booleanAttribute(row, ["data-supports-thinking", "data-thinking"]);
    let inputModalities;
    const modalities = row.getAttribute("data-input-modalities");
    if (modalities) {
      try {
        const parsed = modalities.startsWith("[")
          ? JSON.parse(modalities)
          : modalities.split(/[ ,]+/);
        if (
          Array.isArray(parsed) &&
          parsed.length &&
          parsed.every((value) => ["text", "image"].includes(value))
        )
          inputModalities = [...new Set(parsed)];
      } catch {
        /* A malformed declaration is not evidence of a capability. */
      }
    }
    for (const badge of row.querySelectorAll("[data-capability], [aria-label], [title]")) {
      const label =
        badge.getAttribute("data-capability") ||
        badge.getAttribute("aria-label") ||
        badge.getAttribute("title");
      if (/^(vision|image input|images)$/i.test(label || "") && supportsVision === undefined)
        supportsVision = true;
      if (/^(thinking|reasoning)$/i.test(label || "") && supportsThinking === undefined)
        supportsThinking = true;
    }
    if (inputModalities?.includes("image") && supportsVision === undefined) supportsVision = true;
    return {
      ...(supportsVision === undefined ? {} : { supportsVision }),
      ...(supportsThinking === undefined ? {} : { supportsThinking }),
      ...(inputModalities ? { inputModalities } : {}),
    };
  }

  function modelAccess(row) {
    const locked =
      row.matches(
        ":disabled, [aria-disabled='true'], [data-disabled='true'], [data-selectable='false'], [data-locked='true']"
      ) || !!row.querySelector("[data-locked='true'], [aria-label='Locked' i], [title='Locked' i]");
    let free = booleanAttribute(row, ["data-free", "data-is-free"]);
    const paid = booleanAttribute(row, ["data-paid", "data-requires-subscription"]);
    if (paid === true) free = false;
    const accessNodes = [
      row,
      ...row.querySelectorAll(
        "[data-tier], [data-plan], [data-entitlement], [data-testid='plan-badge']"
      ),
    ];
    for (const node of accessNodes) {
      const declared =
        node.getAttribute("data-tier") ||
        node.getAttribute("data-plan") ||
        node.getAttribute("data-entitlement") ||
        (node !== row ? node.textContent : "");
      if (
        /\b(paid|premium|subscription|upgrade|required|pro|plus)\b|付费|订阅|会员/i.test(
          declared || ""
        )
      )
        free = false;
      else if (/^(free|免费)$/i.test(String(declared || "").trim()) && free === undefined)
        free = true;
    }
    return { selectable: !locked, ...(free === undefined ? {} : { free }) };
  }

  function pickerRoots(document, provider) {
    const roots = [...document.querySelectorAll(MENU_ROOTS)];
    if (provider === "zai-web") {
      for (const item of document.querySelectorAll("button[aria-label='model-item'][data-value]")) {
        const menu = item.closest("[role='menu']");
        if (menu) roots.push(menu);
      }
    }
    if (provider === "doubao-web") {
      // Dola's normal Fast/Pro picker uses these first-party action identifiers.
      for (const item of document.querySelectorAll("[data-testid^='deep-thinking-action-item-']")) {
        const menu = item.closest("[role='menu']");
        if (menu) roots.push(menu);
      }
    }
    for (const trigger of document.querySelectorAll(
      "[aria-label='Select Model'], button[aria-label*='model' i][aria-controls]"
    )) {
      if (!visible(trigger) || trigger.closest(TRANSCRIPT)) continue;
      const controlled = document.getElementById(trigger.getAttribute("aria-controls"));
      if (controlled) roots.push(controlled);
      // Qwen's observed selector is labelled Select Model; only its expanded semantic menu is eligible.
      if (provider === "qwen-browser" && trigger.getAttribute("aria-expanded") === "true") {
        const openMenus = [...document.querySelectorAll("[role='menu'], [role='listbox']")].filter(
          (node) => visible(node) && !node.closest(TRANSCRIPT)
        );
        if (openMenus.length === 1) roots.push(openMenus[0]);
      }
    }
    return [...new Set(roots)].filter((root) => visible(root) && !root.closest(TRANSCRIPT));
  }

  function readModelPicker(document, provider) {
    const roots = pickerRoots(document, provider);
    if (!roots.length) return undefined;
    const models = new Map();
    for (const root of roots) {
      for (const row of root.querySelectorAll(MODEL_ROWS)) {
        if (row.closest(TRANSCRIPT) || (row.tagName !== "OPTION" && !visible(row))) continue;
        const name = modelName(row);
        if (!name) continue;
        let id =
          row.getAttribute("data-model-id") ||
          row.getAttribute("data-model") ||
          (provider === "zai-web" ? row.getAttribute("data-value") : null) ||
          (row.tagName === "OPTION" ? row.getAttribute("value") : null);
        if (!id && provider === "doubao-web") {
          const item = row.closest("[data-testid^='deep-thinking-action-item-']");
          if (
            item?.getAttribute("data-testid") === "deep-thinking-action-item-0" &&
            name === "Fast"
          )
            id = "dola-speed";
          if (item?.getAttribute("data-testid") === "deep-thinking-action-item-4" && name === "Pro")
            id = "dola-pro";
        }
        if (
          (!id || !MODEL_ID.test(id) || id.length > 200) &&
          provider === "qwen-browser" &&
          /^Qwen(?:\b|\d)/i.test(name)
        ) {
          const slug = name
            .normalize("NFKC")
            .toLowerCase()
            .replace(/[^a-z0-9_.:-]+/g, "-")
            .replace(/^-+|-+$/g, "");
          if (slug) id = "qwen-ui-" + slug;
        }
        if (!id || id.length > 200 || !MODEL_ID.test(id)) continue;
        if (!models.has(id))
          models.set(id, { id, name, ...modelAccess(row), ...modelMetadata(row) });
        if (models.size === 200) break;
      }
    }
    // Loading/empty popovers are not an authoritative empty entitlement list.
    return models.size ? [...models.values()] : undefined;
  }

  function signedOut(document) {
    if (/\/(auth|login|signin|sign-in)(\/|$)/i.test(document.location.pathname)) return true;
    for (const node of document.querySelectorAll(
      "button, a, [role='button'], [data-authenticated='false']"
    )) {
      if (!visible(node) || node.closest(TRANSCRIPT)) continue;
      if (
        node.getAttribute("data-authenticated") === "false" ||
        /^(log in|login|sign in|sign-in|登录)$/i.test(node.textContent?.trim() || "")
      )
        return true;
    }
    return false;
  }

  function accountIdentity(storage) {
    const identities = [];
    for (const [key, raw] of Object.entries(storage)) {
      if (typeof raw !== "string" || raw.length > 65536) continue;
      try {
        let token = raw;
        if (raw.startsWith('"') || raw.startsWith("{")) token = JSON.parse(raw);
        let claims;
        if (token && typeof token === "object") {
          claims = token;
          token = token.access_token || token.token;
        }
        if (typeof token === "string" && token.split(".").length === 3) {
          const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
          claims = JSON.parse(atob(encoded));
        }
        // These are identity hints, not token verification or authorization.
        const id = claims?.sub ?? claims?.user_id ?? claims?.uid ?? claims?.account_id;
        if (["string", "number"].includes(typeof id) && String(id).length <= 256)
          identities.push([key, String(claims.iss || ""), String(id)]);
      } catch {
        /* Opaque tokens cannot establish an account identity. */
      }
    }
    return JSON.stringify(identities.sort());
  }

  function pageOrigin(pageKey) {
    try {
      return new URL(pageKey).origin;
    } catch {
      return pageKey;
    }
  }

  function createModelTracker(document) {
    let context;
    let models;
    let everObserved = false;
    const capture = (next) => {
      if (
        context &&
        (context.provider !== next.provider ||
          pageOrigin(context.pageKey) !== pageOrigin(next.pageKey) ||
          context.authKey !== next.authKey)
      )
        models = everObserved ? [] : undefined;
      context = next;
      if (next.signedOut || signedOut(document)) {
        models = everObserved ? [] : undefined;
        return models;
      }
      const observation = readModelPicker(document, next.provider);
      if (observation !== undefined) {
        const previous = new Map((models || []).map((model) => [model.id, model]));
        models = observation.map((model) => ({ ...previous.get(model.id), ...model }));
        everObserved = true;
      }
      return models;
    };
    return {
      capture,
      receive: (entries) => {
        if (!Array.isArray(entries) || entries.length > 200) return;
        if (
          !entries.every(
            (model) =>
              model &&
              typeof model.id === "string" &&
              MODEL_ID.test(model.id) &&
              model.id.length <= 200 &&
              typeof model.name === "string" &&
              model.name.length <= 120 &&
              !/[\r\n]/.test(model.name) &&
              typeof model.selectable === "boolean"
          )
        )
          return;
        models = entries;
        everObserved = true;
      },
      observe: () => {
        if (context) capture({ ...context, pageKey: document.location.href });
      },
    };
  }

  globalThis.__kratosModelDiscovery = Object.freeze({
    readModelPicker,
    createModelTracker,
    accountIdentity,
  });
})();
