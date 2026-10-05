(() => {
  if (globalThis.__kratosSessionSyncInstalled) return;
  globalThis.__kratosSessionSyncInstalled = true;
  let authorization;
  const models = globalThis.__kratosModelDiscovery?.createModelTracker(document);
  if (models) {
    const observer = new MutationObserver(() => models.observe());
    observer.observe(document, { childList: true, subtree: true, attributes: true });
  }
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin) return;
    if (event.data?.source === "kratos-model-catalog") models?.receive(event.data.models);
    if (
      event.data?.source === "kratos-meta-session" &&
      typeof event.data.authorization === "string" &&
      event.data.authorization.startsWith("ecto1:")
    ) {
      authorization = event.data.authorization;
    }
  });
  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (sender.id !== chrome.runtime.id || message.type !== "capture") return;
    const storage = {};
    for (const source of message.sources || []) {
      if (
        !["localStorage", "sessionStorage"].includes(source.type) ||
        typeof source.key !== "string"
      )
        continue;
      try {
        const value = (source.type === "localStorage" ? localStorage : sessionStorage).getItem(
          source.key
        );
        if (value) storage[source.key] = value;
      } catch {
        /* No access to this storage item. */
      }
    }
    const observed = models?.capture({
      provider: message.provider,
      pageKey: location.href,
      authKey: JSON.stringify([
        message.authIdentity || null,
        globalThis.__kratosModelDiscovery?.accountIdentity(storage) || null,
      ]),
      signedOut: message.provider === "qwen-browser" && !Object.values(storage).some(Boolean),
    });
    reply({
      storage,
      userAgent: navigator.userAgent,
      authorization,
      ...(observed === undefined ? {} : { models: observed }),
    });
  });
})();
