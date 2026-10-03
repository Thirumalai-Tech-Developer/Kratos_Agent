/* Observe the page's own model-list responses; never make requests or read chats. */
(() => {
  if (globalThis.__kratosModelResponsesObserved) return;
  globalThis.__kratosModelResponsesObserved = true;
  function parseCatalog(payload) {
    const rows = Array.isArray(payload?.data)
      ? payload.data
      : Array.isArray(payload?.models)
        ? payload.models
        : [];
    return rows.slice(0, 200).flatMap((model) => {
      if (
        !model ||
        typeof model.id !== "string" ||
        !/^[a-zA-Z0-9_.:-]{1,200}$/.test(model.id) ||
        typeof model.name !== "string" ||
        !model.name.trim() ||
        model.name.length > 120 ||
        /[\r\n]/.test(model.name)
      )
        return [];
      const capabilities = model.info?.meta?.capabilities || model.capabilities || {};
      const vision = typeof capabilities.vision === "boolean" ? capabilities.vision : undefined;
      const thinking =
        typeof capabilities.think === "boolean"
          ? capabilities.think
          : typeof capabilities.reasoning === "boolean"
            ? capabilities.reasoning
            : undefined;
      return [
        {
          id: model.id,
          name: model.name.trim(),
          selectable:
            model.info?.is_active !== false &&
            model.info?.meta?.hidden !== true &&
            model.disabled !== true &&
            model.selectable !== false,
          ...(typeof model.free === "boolean" ? { free: model.free } : {}),
          ...(vision === undefined
            ? {}
            : { supportsVision: vision, inputModalities: vision ? ["text", "image"] : ["text"] }),
          ...(thinking === undefined ? {} : { supportsThinking: thinking }),
        },
      ];
    });
  }
  async function observe(response) {
    try {
      const url = new URL(response.url);
      // This matches a normal page request such as Z.ai's observed /api/models.
      if (
        url.origin !== location.origin ||
        !/^\/api\/(?:v\d+\/)?models\/?$/.test(url.pathname) ||
        !response.ok ||
        !response.headers.get("Content-Type")?.includes("json")
      )
        return;
      const copy = response.clone();
      const reader = copy.body?.getReader();
      if (!reader) return;
      const chunks = [];
      let length = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > 2 * 1024 * 1024) {
          await reader.cancel();
          return;
        }
        chunks.push(value);
      }
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      const models = parseCatalog(JSON.parse(new TextDecoder().decode(bytes)));
      if (models.length)
        window.postMessage({ source: "kratos-model-catalog", models }, location.origin);
    } catch {
      /* Failed metadata observations cannot interrupt the provider page. */
    }
  }
  const original = window.fetch;
  window.fetch = function (...args) {
    return original.apply(this, args).then((response) => {
      void observe(response);
      return response;
    });
  };
  // Expose no page data; the pure parser is useful for local extension regression tests.
})();
