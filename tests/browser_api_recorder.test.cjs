const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(
  path.join(__dirname, "../scripts/browser_api_recorder.js"),
  "utf8",
);

function fixture(
  fetch = () => Promise.resolve(new Response("ok")),
  withDom = false,
) {
  class Socket extends EventTarget {
    constructor(url) {
      super();
      this.url = url;
      this.sent = [];
    }
    send(data) {
      this.sent.push(data);
    }
  }
  class Source extends EventTarget {
    constructor(url) {
      super();
      this.url = url;
      this.readyState = 1;
    }
  }
  class Xhr extends EventTarget {
    constructor() {
      super();
      this.responseType = "";
      this.status = 200;
      this.responseText = "";
      this.headers = {};
    }
    open(method, url) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(key, value) {
      this.headers[key] = value;
    }
    getAllResponseHeaders() {
      return "content-type: application/json\r\n";
    }
    send(body) {
      this.sent = body;
      this.responseURL = this.url;
      this.responseText = '{"answer":"hello","access_token":"xhr-secret"}';
      this.dispatchEvent(new Event("progress"));
      this.dispatchEvent(new Event("loadend"));
    }
  }
  const beacon = () => true;
  const sandbox = {
    fetch,
    WebSocket: Socket,
    EventSource: Source,
    XMLHttpRequest: Xhr,
    navigator: { sendBeacon: beacon },
    location: {
      href: "https://chat.example.test/chat/123",
      hostname: "chat.example.test",
    },
    Headers,
    Request,
    Response,
    URL,
    URLSearchParams,
    FormData,
    Blob,
    TextDecoder,
    ArrayBuffer,
    setTimeout: (callback, delay) => {
      const timer = setTimeout(callback, delay);
      timer.unref();
      return timer;
    },
    clearTimeout,
    console: { info() {} },
  };
  const downloads = [];
  if (withDom) {
    const objects = new Map();
    class BrowserUrl extends URL {
      static createObjectURL(blob) {
        objects.set("blob:recording", blob);
        return "blob:recording";
      }
      static revokeObjectURL(url) {
        objects.delete(url);
      }
    }
    class Element {
      constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.style = {};
        this.handlers = new Map();
      }
      appendChild(child) {
        this.children.push(child);
        child.parent = this;
        return child;
      }
      append(...children) {
        children.forEach((child) => this.appendChild(child));
      }
      attachShadow() {
        return (this.shadow = new Element("shadow"));
      }
      addEventListener(name, handler) {
        this.handlers.set(name, handler);
      }
      remove() {
        if (this.parent)
          this.parent.children = this.parent.children.filter(
            (child) => child !== this,
          );
      }
      click() {
        if (this.tag === "a")
          downloads.push({
            filename: this.download,
            blob: objects.get(this.href),
          });
        this.handlers.get("click")?.();
      }
    }
    const body = new Element("body");
    sandbox.document = {
      body,
      documentElement: body,
      createElement: (tag) => new Element(tag),
    };
    sandbox.URL = BrowserUrl;
  }
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  return {
    sandbox,
    api: sandbox.kratosApiRecorder,
    original: { fetch, Socket, Source, Xhr, beacon },
    downloads,
  };
}

async function settled(api) {
  for (let attempts = 0; attempts < 200; attempts += 1) {
    if (api.status().activeReaders === 0) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.fail("Recorder body reader did not finish");
}

test("SSE recording preserves the application's promise/body and masks credentials across chunks", async () => {
  const encoder = new TextEncoder();
  const parts = [
    'event: delta\ndata: {"access_token":"split-',
    'secret","model":"qwen-plus","token":{"id":2,"text":"Hello"}}\n\n',
    "data: [DONE]\n\n",
  ];
  const response = new Response(
    new ReadableStream({
      start(controller) {
        for (const part of parts) controller.enqueue(encoder.encode(part));
        controller.close();
      },
    }),
    { headers: { "content-type": "text/event-stream" } },
  );
  const promise = Promise.resolve(response);
  const f = fixture(() => promise);
  try {
    const observed = f.sandbox.fetch(
      "https://chat.example.test/api/chat?access_token=url-secret",
      {
        method: "POST",
        headers: { Authorization: "Bearer header-secret" },
        body: JSON.stringify({
          model: "qwen-plus",
          prompt: "hi",
          client_secret: "request-secret",
          max_tokens: 128,
        }),
      },
    );
    assert.equal(observed, promise);
    assert.equal(await observed, response);
    assert.equal(await response.text(), parts.join(""));
    await settled(f.api);
    const log = f.api.snapshot();
    const item = log.records[0];
    assert.equal(item.request.credentialsMode, "same-origin");
    assert.equal(item.request.body.value.max_tokens, 128);
    assert.equal(item.response.body.events[0].event, "delta");
    assert.equal(item.response.body.events[0].data.token.text, "Hello");
    assert.equal(item.response.body.events[1].data, "[DONE]");
    for (const secret of [
      "split-secret",
      "url-secret",
      "header-secret",
      "request-secret",
    ])
      assert.ok(!JSON.stringify(log).includes(secret));
  } finally {
    f.api.dispose();
  }
});

test("Request objects are cloned without consuming the site's request body", async () => {
  const request = new Request("https://chat.example.test/api/chat", {
    method: "POST",
    body: '{"model":"fast","token":"request-token"}',
  });
  const f = fixture(() =>
    Promise.resolve(
      new Response('{"text":"hi"}', {
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  try {
    const response = await f.sandbox.fetch(request);
    assert.equal(
      await request.text(),
      '{"model":"fast","token":"request-token"}',
    );
    await response.text();
    await settled(f.api);
    const item = f.api.snapshot().records[0];
    assert.equal(item.request.body.value.model, "fast");
    assert.equal(item.request.body.value.token, "[REDACTED]");
  } finally {
    f.api.dispose();
  }
});

test("Fetch errors retain their original identity and Stop restores native methods", async () => {
  const error = new Error("network failed");
  const f = fixture(() => Promise.reject(error));
  await assert.rejects(
    f.sandbox.fetch("/api/chat"),
    (actual) => actual === error,
  );
  assert.equal(f.api.snapshot().records[0].state, "error");
  f.api.stop();
  assert.equal(f.sandbox.fetch, f.original.fetch);
  assert.equal(f.sandbox.WebSocket, f.original.Socket);
  assert.equal(f.sandbox.navigator.sendBeacon, f.original.beacon);
  f.api.dispose();
  assert.equal(f.sandbox.kratosApiRecorder, undefined);
});

test("XHR payloads/headers remain unchanged while its exported response is sanitized", () => {
  const f = fixture();
  try {
    const xhr = new f.sandbox.XMLHttpRequest();
    xhr.open("POST", "https://chat.example.test/api/reply");
    xhr.setRequestHeader("Authorization", "Bearer xhr-header-secret");
    const body = '{"prompt":"hi"}';
    xhr.send(body);
    assert.equal(xhr.sent, body);
    assert.equal(xhr.headers.Authorization, "Bearer xhr-header-secret");
    const item = f.api.snapshot().records[0];
    assert.equal(item.response.body.value.answer, "hello");
    assert.equal(item.response.body.value.access_token, "[REDACTED]");
    assert.equal(item.request.headers.Authorization, "[REDACTED]");
  } finally {
    f.api.dispose();
  }
});

test("WebSockets retain native instances and existing sockets continue logging after Clear", () => {
  const f = fixture();
  try {
    const socket = new f.sandbox.WebSocket(
      "wss://chat.example.test/stream?token=socket-secret",
    );
    assert.ok(socket instanceof f.original.Socket);
    const actual = '{"prompt":"hello","access_token":"frame-secret"}';
    socket.send(actual);
    assert.equal(socket.sent[0], actual);
    socket.dispatchEvent(
      new MessageEvent("message", { data: '{"text":"reply"}' }),
    );
    let item = f.api.snapshot().records[0];
    assert.equal(item.frames.length, 2);
    assert.equal(item.frames[1].body.value.text, "reply");
    assert.ok(!JSON.stringify(item).includes("socket-secret"));
    assert.ok(!JSON.stringify(item).includes("frame-secret"));
    f.api.clear();
    assert.equal(f.api.snapshot().records.length, 0);
    socket.dispatchEvent(new MessageEvent("message", { data: "next reply" }));
    item = f.api.snapshot().records[0];
    assert.equal(item.frames[0].body.value, "next reply");
    f.api.stop();
    socket.send("after stop");
    assert.equal(socket.sent.at(-1), "after stop");
    assert.equal(f.api.snapshot().records[0].frames.length, 1);
  } finally {
    f.api.dispose();
  }
});

test("EventSource records registered named events without changing app callbacks", () => {
  const f = fixture();
  try {
    const source = new f.sandbox.EventSource(
      "https://chat.example.test/events",
    );
    let received;
    source.addEventListener("delta", (event) => {
      received = event.data;
    });
    source.dispatchEvent(
      new MessageEvent("delta", { data: '{"text":"hello"}' }),
    );
    assert.equal(received, '{"text":"hello"}');
    const item = f.api.snapshot().records[0];
    assert.equal(item.frames[0].event, "delta");
    assert.equal(item.frames[0].body.value.text, "hello");
  } finally {
    f.api.dispose();
  }
});

test("Entry limits drop old logs and beacon delivery result remains unchanged", () => {
  const f = fixture();
  try {
    for (let i = 0; i < 350; i += 1)
      assert.equal(
        f.sandbox.navigator.sendBeacon(`/analytics/${i}`, "data"),
        true,
      );
    assert.equal(f.api.status().entries, 300);
    assert.equal(f.api.status().droppedEntries, 50);
    f.api.clear();
    assert.equal(f.api.status().entries, 0);
    assert.equal(f.api.status().droppedEntries, 0);
  } finally {
    f.api.dispose();
  }
});

test("Bounded response capture does not truncate the application's response", async () => {
  const actual = "x".repeat(2 * 1024 * 1024);
  const f = fixture(() => Promise.resolve(new Response(actual)));
  try {
    const response = await f.sandbox.fetch("/api/large");
    assert.equal((await response.text()).length, actual.length);
    await settled(f.api);
    const body = f.api.snapshot().records[0].response.body;
    assert.equal(body.truncated, true);
    assert.equal(body.value.length, 1024 * 1024);
  } finally {
    f.api.dispose();
  }
});

test("Stopping an active stream only cancels the recorder's reader", async () => {
  let controller;
  const encoder = new TextEncoder();
  const f = fixture(() =>
    Promise.resolve(
      new Response(
        new ReadableStream({
          start(value) {
            controller = value;
          },
        }),
      ),
    ),
  );
  try {
    const response = await f.sandbox.fetch("/api/stream");
    controller.enqueue(encoder.encode("before "));
    await new Promise((resolve) => setTimeout(resolve, 10));
    f.api.stop();
    controller.enqueue(encoder.encode("after"));
    controller.close();
    assert.equal(await response.text(), "before after");
    await settled(f.api);
    assert.equal(f.api.status().recording, false);
  } finally {
    f.api.dispose();
  }
});

test("Download log button creates a local JSON download with no request", async () => {
  let calls = 0;
  const f = fixture(() => {
    calls += 1;
    return Promise.resolve(new Response("reply"));
  }, true);
  try {
    await (await f.sandbox.fetch("/api/chat")).text();
    await settled(f.api);
    const panel = f.sandbox.document.body.children.find(
      (element) => element.id === "kratos-api-recorder",
    );
    const box = panel.shadow.children.find(
      (element) => element.className === "box",
    );
    const controls = box.children.at(-1);
    controls.children[0].click();
    assert.equal(calls, 1);
    assert.equal(f.downloads.length, 1);
    assert.match(f.downloads[0].filename, /^kratos-api-chat\.example\.test-/);
    const log = JSON.parse(await f.downloads[0].blob.text());
    assert.equal(log.format, "kratos-browser-api-log");
    assert.equal(log.records[0].response.body.value, "reply");
    controls.children[2].click();
    assert.equal(f.api.status().recording, false);
    controls.children[0].click();
    assert.equal(f.downloads.length, 2);
  } finally {
    f.api.dispose();
  }
});
