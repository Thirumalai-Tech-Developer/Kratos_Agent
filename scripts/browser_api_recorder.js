/*
 * Kratos browser API recorder — paste this whole file into DevTools Console.
 * Chat manually, then click Download log. No recording is uploaded anywhere.
 * Commands: kratosApiRecorder.download(), .snapshot(), .clear(), .stop(), .dispose()
 * Bodies contain your chat text. Common credential fields are masked on export.
 */
(() => {
  "use strict";

  const root = globalThis;
  if (root.kratosApiRecorder) {
    console.info(
      "Kratos recorder already installed. Use .download() or .dispose() before reinstalling.",
    );
    return;
  }

  const LIMITS = Object.freeze({
    records: 300,
    bodyBytes: 1024 * 1024,
    totalBytes: 20 * 1024 * 1024,
    frameBytes: 64 * 1024,
    framesPerConnection: 500,
    readers: 8,
  });
  const startedAt = new Date().toISOString();
  const records = [];
  const states = new WeakMap();
  const restores = [];
  const detach = new Set();
  const readers = new Set();
  const xhrMeta = new WeakMap();
  const socketMeta = new WeakMap();
  const sourceMeta = new WeakMap();
  const sensitiveKeys = new Set([
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "apikey",
    "password",
    "passwd",
    "passphrase",
    "clientsecret",
    "secret",
    "credentials",
    "credential",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "authtoken",
    "sessiontoken",
    "bearertoken",
    "session",
    "sessionid",
    "csrf",
    "xsrf",
    "csrftoken",
    "xsrftoken",
    "authorizationcode",
    "authcode",
    "cfclearance",
    "cfbm",
    "email",
    "phone",
    "phonenumber",
  ]);
  let enabled = true;
  let sequence = 0;
  let approximateBytes = 0;
  let dropped = 0;
  let panel;
  let label;
  let stopButton;
  let observer;
  let refreshTimer;

  function secretKey(key, value) {
    const name = String(key)
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
    // Some generation protocols call each output token {token: {text, id}}.
    if (
      name === "token" &&
      value &&
      typeof value === "object" &&
      "text" in value
    )
      return false;
    return (
      sensitiveKeys.has(name) ||
      name === "token" ||
      /(?:auth|access|refresh|csrf|xsrf|security|turnstile|recaptcha)token$/.test(
        name,
      ) ||
      /(?:apikey|clientsecret|signature|psid|psidts|psidcc)$/.test(name)
    );
  }

  function sanitizeString(value, depth = 0) {
    let text = String(value);
    if (
      depth < 20 &&
      /^[\s]*[\[{]/.test(text) &&
      text.length <= LIMITS.bodyBytes
    ) {
      try {
        return JSON.stringify(sanitize(JSON.parse(text), depth + 1));
      } catch {
        /* text or partial JSON */
      }
    }
    text = text.replace(
      /\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi,
      "Bearer [REDACTED]",
    );
    text = text.replace(
      /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*)?/g,
      "[REDACTED JWT]",
    );
    // Also cover partial JSON values at a stream or size boundary.
    text = text.replace(
      /(["'])([^"'\r\n]{1,100})\1\s*:\s*"((?:\\.|[^"\\])*)("|$)/g,
      (match, quote, key, value, end) =>
        secretKey(key, value) ? `${quote}${key}${quote}:"[REDACTED]"` : match,
    );
    text = text.replace(
      /\b([A-Za-z0-9_-]*(?:token|password|client_secret|api_key|signature))=([^\s&;,]*)/gi,
      (match, key) => (secretKey(key, "") ? `${key}=[REDACTED]` : match),
    );
    return text;
  }

  function sanitize(value, depth = 0) {
    if (depth > 30) return "[DEPTH LIMIT]";
    if (typeof value === "string") return sanitizeString(value, depth);
    if (Array.isArray(value))
      return value.map((item) => sanitize(item, depth + 1));
    if (value && typeof value === "object") {
      const result = Object.create(null);
      for (const [key, item] of Object.entries(value)) {
        result[key] = secretKey(key, item)
          ? "[REDACTED]"
          : sanitize(item, depth + 1);
      }
      return result;
    }
    return value;
  }

  function cleanUrl(value) {
    try {
      const url = new URL(String(value), root.location?.href);
      if (url.username) url.username = "REDACTED";
      if (url.password) url.password = "REDACTED";
      for (const [key, item] of [...url.searchParams.entries()]) {
        if (secretKey(key, item) || /^(?:code|state|sig)$/i.test(key))
          url.searchParams.set(key, "[REDACTED]");
      }
      if (url.hash) url.hash = sanitizeString(url.hash);
      return sanitizeString(url.href).slice(0, 8192);
    } catch {
      return sanitizeString(String(value)).slice(0, 8192);
    }
  }

  function cleanHeaders(headers) {
    const result = Object.create(null);
    try {
      for (const [key, value] of new Headers(headers || {}).entries()) {
        result[key] = secretKey(key, value)
          ? "[REDACTED]"
          : sanitizeString(value);
      }
    } catch {
      /* inaccessible or invalid headers */
    }
    return result;
  }

  function refresh() {
    if (!label || refreshTimer) return;
    refreshTimer = setTimeout(() => {
      refreshTimer = undefined;
      if (label)
        label.textContent = `${enabled ? "Recording" : "Stopped"} · ${records.length} entries · ${dropped} dropped`;
    }, 100);
  }

  function cancelReader(reader) {
    try {
      Promise.resolve(reader.cancel()).catch(() => {});
    } catch {
      /* already closed */
    }
  }

  function abandon(entry) {
    const state = states.get(entry);
    if (!state || state.removed) return;
    state.removed = true;
    approximateBytes -= state.estimate;
    for (const reader of state.readers) cancelReader(reader);
    state.requestRaw = "";
    state.responseRaw = "";
  }

  function prune() {
    while (
      records.length > LIMITS.records ||
      (approximateBytes > LIMITS.totalBytes && records.length > 1)
    ) {
      abandon(records.shift());
      dropped += 1;
    }
    refresh();
  }

  function addBytes(entry, count) {
    const state = states.get(entry);
    if (!state || state.removed) return;
    state.estimate += count;
    approximateBytes += count;
    prune();
  }

  function alive(entry) {
    return enabled && entry && states.has(entry) && !states.get(entry).removed;
  }

  function entry(kind, details = {}) {
    if (!enabled) return undefined;
    const item = {
      id: ++sequence,
      kind,
      startedAt: new Date().toISOString(),
      ...details,
    };
    states.set(item, {
      estimate: 1024,
      readers: new Set(),
      removed: false,
      requestRaw: "",
      responseRaw: "",
    });
    approximateBytes += 1024;
    records.push(item);
    prune();
    return item;
  }

  function finish(item, status) {
    if (!alive(item)) return;
    item.finishedAt = new Date().toISOString();
    item.elapsedMs = Date.parse(item.finishedAt) - Date.parse(item.startedAt);
    if (status) item.state = status;
    refresh();
  }

  function note(item, text) {
    if (!alive(item)) return;
    item.notes ||= [];
    if (item.notes.length < 20) item.notes.push(text);
  }

  function setRaw(item, side, raw) {
    if (!alive(item)) return;
    const state = states.get(item);
    const key = `${side}Raw`;
    const text = String(raw).slice(0, LIMITS.bodyBytes);
    const delta = (text.length - state[key].length) * 2;
    state[key] = text;
    addBytes(item, delta);
  }

  function textBody(raw, truncated = false, contentType = "") {
    let value;
    try {
      value = sanitize(JSON.parse(raw));
    } catch {
      value = sanitizeString(raw);
    }
    const body = {
      format: typeof value === "string" ? "text" : "json",
      contentType,
      truncated,
      value,
    };
    if (
      /text\/event-stream/i.test(contentType) ||
      /^(?:event:|data:)/m.test(raw)
    ) {
      body.format = "sse";
      // Parse complete event blocks, preserving event names and JSON structure.
      const events = [];
      for (const block of raw.split(/\r?\n\r?\n/)) {
        const data = block
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).replace(/^ /, ""))
          .join("\n");
        if (!data) continue;
        const name = block.match(/^event:\s*(.*)$/m)?.[1] || "message";
        let payload;
        try {
          payload = sanitize(JSON.parse(data));
        } catch {
          payload = sanitizeString(data);
        }
        events.push({ event: sanitizeString(name), data: payload });
      }
      body.events = events;
    }
    return body;
  }

  function observedBody(value) {
    if (value == null) return { format: "empty" };
    if (typeof value === "string")
      return textBody(
        value.slice(0, LIMITS.bodyBytes),
        value.length > LIMITS.bodyBytes,
      );
    if (
      typeof URLSearchParams !== "undefined" &&
      value instanceof URLSearchParams
    ) {
      const fields = [...value].map(([key, item]) => ({
        key,
        value: secretKey(key, item) ? "[REDACTED]" : sanitizeString(item),
      }));
      return { format: "form-urlencoded", fields };
    }
    if (typeof FormData !== "undefined" && value instanceof FormData) {
      const fields = [...value].map(([key, item]) => ({
        key,
        value: secretKey(key, item)
          ? "[REDACTED]"
          : typeof item === "string"
            ? sanitizeString(item.slice(0, LIMITS.bodyBytes))
            : { file: item.name, type: item.type, bytes: item.size },
      }));
      return { format: "multipart", fields };
    }
    if (typeof Blob !== "undefined" && value instanceof Blob)
      return { format: "binary", type: value.type, bytes: value.size };
    if (value instanceof ArrayBuffer || ArrayBuffer.isView(value))
      return { format: "binary", bytes: value.byteLength };
    return {
      format: "unobserved",
      type: Object.prototype.toString.call(value),
    };
  }

  function assignBody(item, side, value) {
    if (!alive(item)) return;
    item[side] ||= {};
    const body = observedBody(value);
    item[side].body = body;
    addBytes(item, JSON.stringify(body).length * 2);
  }

  function textual(type) {
    return (
      !type ||
      /(?:json|text\/|javascript|xml|graphql|form-urlencoded)/i.test(type)
    );
  }

  async function readClone(item, side, clone) {
    if (!alive(item)) return;
    item[side] ||= {};
    const type = clone.headers.get("content-type") || "";
    if (!textual(type)) {
      item[side].body = {
        format: "binary",
        contentType: type,
        bytes: clone.headers.get("content-length"),
      };
      if (clone.body) {
        try {
          Promise.resolve(clone.body.cancel()).catch(() => {});
        } catch {
          /* closed */
        }
      }
      return;
    }
    if (!clone.body) {
      item[side].body = { format: "empty", contentType: type };
      return;
    }
    const reader = clone.body.getReader();
    if (readers.size >= LIMITS.readers) {
      note(item, "Body skipped: concurrent-reader limit.");
      cancelReader(reader);
      return;
    }
    const state = states.get(item);
    state.readers.add(reader);
    readers.add(reader);
    const decoder = new TextDecoder();
    let bytes = 0;
    let text = "";
    let truncated = false;
    let complete = false;
    item[side].body = { format: "pending", contentType: type };
    item[side].chunks = [];
    try {
      while (alive(item)) {
        const part = await reader.read();
        if (!alive(item)) break;
        if (part.done) {
          text += decoder.decode();
          complete = true;
          break;
        }
        const take = Math.min(part.value.byteLength, LIMITS.bodyBytes - bytes);
        text += decoder.decode(part.value.subarray(0, take), { stream: true });
        bytes += take;
        setRaw(item, side, text);
        if (item[side].chunks.length < 1000)
          item[side].chunks.push({
            at: new Date().toISOString(),
            bytes: part.value.byteLength,
          });
        if (bytes >= LIMITS.bodyBytes) {
          truncated = true;
          break;
        }
      }
      if (alive(item)) {
        setRaw(item, side, text);
        item[side].body = {
          format: "captured",
          contentType: type,
          bytes,
          truncated,
          complete,
        };
        if (side === "response")
          finish(item, complete ? "complete" : "body-limited");
      }
    } catch (error) {
      note(item, `Body capture ended: ${error?.name || "Error"}.`);
    } finally {
      if (!complete) cancelReader(reader);
      state.readers.delete(reader);
      readers.delete(reader);
      try {
        reader.releaseLock();
      } catch {
        /* a cancellation may still be pending */
      }
    }
  }

  function patch(owner, key, wrapper) {
    const original = owner?.[key];
    if (typeof original !== "function") return;
    try {
      const replacement = wrapper(original);
      owner[key] = replacement;
      if (owner[key] === replacement)
        restores.push(() => {
          if (owner[key] === replacement) owner[key] = original;
        });
    } catch {
      /* some browser or site properties are read-only */
    }
  }

  function listen(
    target,
    type,
    handler,
    add = target.addEventListener,
    remove = target.removeEventListener,
  ) {
    Reflect.apply(add, target, [type, handler]);
    const undo = () => {
      Reflect.apply(remove, target, [type, handler]);
      detach.delete(undo);
    };
    detach.add(undo);
    return undo;
  }

  patch(
    root,
    "fetch",
    (original) =>
      function (input, options) {
        let item;
        if (enabled) {
          try {
            const isRequest =
              typeof Request !== "undefined" && input instanceof Request;
            item = entry("fetch", {
              request: {
                url: cleanUrl(isRequest ? input.url : input),
                method: options?.method || (isRequest ? input.method : "GET"),
                headers: cleanHeaders(
                  options?.headers ?? (isRequest ? input.headers : undefined),
                ),
                credentialsMode:
                  options?.credentials ??
                  (isRequest ? input.credentials : "same-origin"),
              },
            });
            if (options && "body" in options)
              assignBody(item, "request", options.body);
            else if (isRequest && input.body && !input.bodyUsed)
              readClone(item, "request", input.clone()).catch(() => {});
          } catch {
            /* recording must never prevent the application's request */
          }
        }
        let promise;
        try {
          promise = Reflect.apply(original, this, arguments);
        } catch (error) {
          if (alive(item)) item.error = sanitizeString(String(error));
          finish(item, "error");
          throw error;
        }
        promise
          .then(
            (response) => {
              if (!alive(item)) return;
              item.response = {
                status: response.status,
                statusText: response.statusText,
                url: cleanUrl(response.url || item.request.url),
                headers: cleanHeaders(response.headers),
                type: response.type,
              };
              item.headersAt = new Date().toISOString();
              readClone(item, "response", response.clone()).catch((error) =>
                note(item, `Response capture: ${error?.name || "Error"}.`),
              );
            },
            (error) => {
              if (alive(item)) item.error = sanitizeString(String(error));
              finish(item, "error");
            },
          )
          .catch(() => {});
        return promise;
      },
  );

  const xhrPrototype = root.XMLHttpRequest?.prototype;
  patch(
    xhrPrototype,
    "open",
    (original) =>
      function (method, url) {
        const result = Reflect.apply(original, this, arguments);
        if (enabled)
          xhrMeta.set(this, {
            method: String(method),
            url: cleanUrl(url),
            headers: Object.create(null),
          });
        return result;
      },
  );
  patch(
    xhrPrototype,
    "setRequestHeader",
    (original) =>
      function (key, value) {
        const result = Reflect.apply(original, this, arguments);
        const meta = xhrMeta.get(this);
        if (enabled && meta)
          meta.headers[key] = secretKey(key, value)
            ? "[REDACTED]"
            : sanitizeString(value);
        return result;
      },
  );
  patch(
    xhrPrototype,
    "send",
    (original) =>
      function (body) {
        if (!enabled) return Reflect.apply(original, this, arguments);
        const xhr = this;
        const meta = xhrMeta.get(xhr) || {
          method: "unknown",
          url: "opened-before-recorder",
          headers: {},
        };
        const item = entry("xhr", {
          request: { ...meta, headers: { ...meta.headers } },
        });
        assignBody(item, "request", body);
        const undos = [];
        function capture() {
          if (!alive(item)) return;
          try {
            const headers = Object.create(null);
            for (const line of xhr.getAllResponseHeaders().split(/\r?\n/)) {
              const colon = line.indexOf(":");
              if (colon > 0)
                headers[line.slice(0, colon)] = line.slice(colon + 1).trim();
            }
            item.response ||= {};
            Object.assign(item.response, {
              status: xhr.status,
              url: cleanUrl(xhr.responseURL || meta.url),
              headers: cleanHeaders(headers),
              responseType: xhr.responseType,
            });
            if (!xhr.responseType || xhr.responseType === "text") {
              const raw = xhr.responseText || "";
              setRaw(item, "response", raw);
              item.response.body = {
                format: "captured",
                contentType: headers["content-type"] || "",
                truncated: raw.length > LIMITS.bodyBytes,
              };
            } else if (xhr.responseType === "json")
              assignBody(item, "response", JSON.stringify(xhr.response));
            else item.response.body = observedBody(xhr.response);
          } catch {
            /* responseText can throw before headers or on binary responses */
          }
        }
        undos.push(listen(xhr, "progress", capture));
        undos.push(
          listen(xhr, "loadend", () => {
            capture();
            finish(item, "complete");
            for (const undo of undos) undo();
          }),
        );
        try {
          return Reflect.apply(original, this, arguments);
        } catch (error) {
          for (const undo of undos) undo();
          if (alive(item)) item.error = sanitizeString(String(error));
          finish(item, "error");
          throw error;
        }
      },
  );

  function connectionEntry(meta, kind) {
    if (!enabled) return undefined;
    if (!alive(meta.entry))
      meta.entry = entry(kind, {
        request: { url: cleanUrl(meta.url) },
        frames: [],
        droppedFrames: 0,
      });
    return meta.entry;
  }

  function frame(meta, kind, direction, data, event = "message") {
    const item = connectionEntry(meta, kind);
    if (!item) return;
    if (item.frames.length >= LIMITS.framesPerConnection) {
      item.droppedFrames += 1;
      return;
    }
    const captured = { at: new Date().toISOString(), direction, event };
    if (typeof data === "string")
      captured.body = textBody(
        data.slice(0, LIMITS.frameBytes),
        data.length > LIMITS.frameBytes,
      );
    else captured.body = observedBody(data);
    item.frames.push(captured);
    addBytes(item, JSON.stringify(captured).length * 2);
  }

  async function incomingFrame(meta, kind, data, type) {
    if (
      typeof Blob !== "undefined" &&
      data instanceof Blob &&
      data.size <= LIMITS.frameBytes
    ) {
      try {
        const text = await data.text();
        if (enabled && !text.includes("\u0000") && !text.includes("\ufffd")) {
          frame(meta, kind, "receive", text, type);
          return;
        }
      } catch {
        /* binary frame */
      }
    }
    if (data instanceof ArrayBuffer && data.byteLength <= LIMITS.frameBytes) {
      try {
        const text = new TextDecoder("utf-8", { fatal: true }).decode(data);
        if (!text.includes("\u0000")) {
          frame(meta, kind, "receive", text, type);
          return;
        }
      } catch {
        /* binary frame */
      }
    }
    frame(meta, kind, "receive", data, type);
  }

  function observeSocket(socket) {
    let meta = socketMeta.get(socket);
    if (meta) return meta;
    meta = { url: socket.url };
    socketMeta.set(socket, meta);
    connectionEntry(meta, "websocket");
    listen(socket, "message", (event) => {
      incomingFrame(meta, "websocket", event.data, "message").catch(() => {});
    });
    listen(socket, "open", () => {
      const item = connectionEntry(meta, "websocket");
      if (item) item.state = "open";
    });
    listen(socket, "error", () => {
      const item = connectionEntry(meta, "websocket");
      if (item) item.state = "error";
    });
    listen(socket, "close", (event) => {
      const item = connectionEntry(meta, "websocket");
      if (item)
        item.close = {
          code: event.code,
          reason: sanitizeString(event.reason || ""),
          wasClean: event.wasClean,
        };
      finish(item, "closed");
    });
    return meta;
  }

  patch(
    root,
    "WebSocket",
    (original) =>
      new Proxy(original, {
        construct(target, args, newTarget) {
          const socket = Reflect.construct(target, args, newTarget);
          if (enabled) {
            try {
              observeSocket(socket);
            } catch {
              /* unsupported socket */
            }
          }
          return socket;
        },
      }),
  );
  patch(
    root.WebSocket?.prototype,
    "send",
    (original) =>
      function (data) {
        const result = Reflect.apply(original, this, arguments);
        if (enabled) {
          try {
            frame(observeSocket(this), "websocket", "send", data);
          } catch {
            /* observation only */
          }
        }
        return result;
      },
  );

  const nativeSourceAdd = root.EventSource?.prototype?.addEventListener;
  const nativeSourceRemove = root.EventSource?.prototype?.removeEventListener;
  function observeSource(source, type = "message") {
    let meta = sourceMeta.get(source);
    if (!meta) {
      meta = { url: source.url, events: new Set() };
      sourceMeta.set(source, meta);
      connectionEntry(meta, "eventsource");
      listen(
        source,
        "open",
        () => {
          const item = connectionEntry(meta, "eventsource");
          if (item) item.state = "open";
        },
        nativeSourceAdd,
        nativeSourceRemove,
      );
      listen(
        source,
        "error",
        () => {
          const item = connectionEntry(meta, "eventsource");
          if (item)
            item.state = source.readyState === 2 ? "closed" : "reconnecting";
        },
        nativeSourceAdd,
        nativeSourceRemove,
      );
    }
    if (type !== "open" && type !== "error" && !meta.events.has(type)) {
      meta.events.add(type);
      listen(
        source,
        type,
        (event) => frame(meta, "eventsource", "receive", event.data, type),
        nativeSourceAdd,
        nativeSourceRemove,
      );
    }
    return meta;
  }
  patch(
    root,
    "EventSource",
    (original) =>
      new Proxy(original, {
        construct(target, args, newTarget) {
          const source = Reflect.construct(target, args, newTarget);
          if (enabled) {
            try {
              observeSource(source);
            } catch {
              /* observation only */
            }
          }
          return source;
        },
      }),
  );
  patch(
    root.EventSource?.prototype,
    "addEventListener",
    (original) =>
      function (type) {
        if (enabled) {
          try {
            observeSource(this, String(type));
          } catch {
            /* observation only */
          }
        }
        return Reflect.apply(original, this, arguments);
      },
  );

  patch(
    root.navigator,
    "sendBeacon",
    (original) =>
      function (url, data) {
        const result = Reflect.apply(original, this, arguments);
        if (enabled) {
          try {
            const item = entry("beacon", {
              request: { method: "POST", url: cleanUrl(url) },
              accepted: result,
            });
            assignBody(item, "request", data);
            finish(item, result ? "queued" : "rejected");
          } catch {
            /* observation only */
          }
        }
        return result;
      },
  );

  if (typeof root.PerformanceObserver === "function") {
    try {
      observer = new root.PerformanceObserver((list) => {
        for (const timing of list.getEntries()) {
          entry("resource-timing", {
            request: { url: cleanUrl(timing.name) },
            initiatorType: timing.initiatorType,
            durationMs: timing.duration,
            transferBytes: timing.transferSize,
            decodedBytes: timing.decodedBodySize,
            note: "Timing only; this may duplicate a fetch/XHR entry. Cross-origin timing can be restricted.",
          });
        }
      });
      observer.observe({ type: "resource", buffered: false });
    } catch {
      /* unsupported resource timing */
    }
  }

  function snapshot() {
    return {
      format: "kratos-browser-api-log",
      version: 1,
      startedAt,
      exportedAt: new Date().toISOString(),
      page: cleanUrl(root.location?.href || "unknown"),
      recording: enabled,
      limits: LIMITS,
      droppedEntries: dropped,
      redaction:
        "Common credentials masked; chat content retained. Review before sharing.",
      limitations: [
        "Page-context requests after installation. Worker/iframe bodies and previously cached native methods are not observed.",
        "Existing WebSockets are observed after their next intercepted send; existing EventSource events after an intercepted listener registration.",
        "HttpOnly cookies, browser-injected credentials, opaque CORS responses and encrypted/binary payloads are not available.",
        "A page refresh removes the recorder. Logs include prompts and answers; unknown credential formats may require manual redaction.",
      ],
      records: records.map((item) => {
        const copy = JSON.parse(JSON.stringify(item));
        const state = states.get(item);
        for (const side of ["request", "response"]) {
          const raw = state?.[`${side}Raw`];
          if (raw) {
            copy[side] ||= {};
            copy[side].body = {
              ...copy[side].body,
              ...textBody(
                raw,
                Boolean(copy[side].body?.truncated),
                copy[side].body?.contentType || "",
              ),
            };
          }
        }
        return sanitize(copy);
      }),
    };
  }

  function download() {
    const log = snapshot();
    const blob = new Blob([JSON.stringify(log, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const host = String(root.location?.hostname || "website").replace(
      /[^a-zA-Z0-9.-]/g,
      "_",
    );
    anchor.href = url;
    anchor.download = `kratos-api-${host}-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    (document.body || document.documentElement).appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    return { filename: anchor.download, entries: log.records.length };
  }

  function clear() {
    for (const item of records) abandon(item);
    records.length = 0;
    approximateBytes = 0;
    dropped = 0;
    refresh();
  }

  function stop() {
    if (!enabled) return snapshot();
    enabled = false;
    for (const reader of readers) cancelReader(reader);
    for (const undo of [...detach]) {
      try {
        undo();
      } catch {
        /* detached page */
      }
    }
    for (const undo of restores.reverse()) {
      try {
        undo();
      } catch {
        /* a later page patch may own the method */
      }
    }
    observer?.disconnect();
    if (stopButton) stopButton.disabled = true;
    if (label)
      label.textContent = `Stopped · ${records.length} entries · ${dropped} dropped`;
    return snapshot();
  }

  const api = Object.freeze({
    version: 1,
    snapshot,
    download,
    clear,
    stop,
    status: () => ({
      recording: enabled,
      entries: records.length,
      droppedEntries: dropped,
      approximateBytes,
      activeReaders: readers.size,
    }),
    dispose() {
      const saved = stop();
      panel?.remove();
      if (refreshTimer) clearTimeout(refreshTimer);
      if (root.kratosApiRecorder === api) delete root.kratosApiRecorder;
      return saved;
    },
  });
  root.kratosApiRecorder = api;

  if (typeof document !== "undefined") {
    try {
      panel = document.createElement("div");
      panel.id = "kratos-api-recorder";
      panel.style.cssText =
        "position:fixed;right:16px;bottom:16px;z-index:2147483647";
      const shadow = panel.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent =
        ":host{font:13px system-ui;color:#f3f4f6}.box{background:#111827;border:1px solid #8b5cf6;border-radius:12px;padding:12px;box-shadow:0 8px 24px #0007;max-width:380px}strong{display:block;margin-bottom:5px}.status{color:#a7f3d0;margin-bottom:10px}button{font:inherit;border:1px solid #4b5563;border-radius:7px;padding:7px 10px;background:#1f2937;color:white;cursor:pointer;margin-right:6px}button:first-child{background:#6d28d9}button:disabled{opacity:.5;cursor:default}";
      shadow.appendChild(style);
      const box = document.createElement("div");
      box.className = "box";
      const title = document.createElement("strong");
      title.textContent = "Kratos API recorder";
      label = document.createElement("div");
      label.className = "status";
      label.textContent = "Recording · 0 entries";
      const controls = document.createElement("div");
      for (const [text, handler] of [
        ["Download log", download],
        ["Clear", clear],
        ["Stop", stop],
      ]) {
        const button = document.createElement("button");
        button.textContent = text;
        button.addEventListener("click", handler);
        if (text === "Stop") stopButton = button;
        controls.appendChild(button);
      }
      box.append(title, label, controls);
      shadow.appendChild(box);
      (document.body || document.documentElement).appendChild(panel);
    } catch {
      console.info("Use kratosApiRecorder.download() to save the recording.");
    }
  }
  console.info(
    "Kratos API recorder started. Chat manually, then click Download log. Use .stop() to restore the page methods.",
  );
})();
