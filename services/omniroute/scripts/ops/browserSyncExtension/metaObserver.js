/* Observe only Meta's normal websocket credential, without changing requests. */
(() => {
  if (globalThis.__kratosMetaObserved || location.hostname !== "www.meta.ai") return;
  globalThis.__kratosMetaObserved = true;
  const Original = window.WebSocket;
  const Observed = new Proxy(Original, {
    construct(target, args, newTarget) {
      const socket = Reflect.construct(target, args, newTarget === Observed ? target : newTarget);
      try {
        const url = new URL(String(args[0]));
        const authorization = url.searchParams.get("Authorization");
        if (
          url.protocol === "wss:" &&
          url.hostname === "gateway.meta.ai" &&
          url.pathname === "/ws/clippy" &&
          authorization?.startsWith("ecto1:")
        ) {
          window.postMessage({ source: "kratos-meta-session", authorization }, location.origin);
        }
      } catch {
        /* Invalid/other websocket URLs are ignored. */
      }
      return socket;
    },
  });
  window.WebSocket = Observed;
})();
