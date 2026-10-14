import { createServer } from "node:http";
import { randomUUID, timingSafeEqual } from "node:crypto";

export function validBrowserToken(header, token) {
  const actual = Buffer.from(header || "");
  const expected = Buffer.from("Bearer " + token);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export class RegularBrowserConnection {
  constructor({
    token,
    port = 20130,
    timeout = 240000,
    deliveryTimeout = 35000,
    provider = "chatgpt-web",
    conversation = null,
  }) {
    if (
      typeof token !== "string" ||
      token.length < 32 ||
      !Number.isInteger(port) ||
      port < 1024 ||
      port > 65535
    )
      throw new Error("Invalid browser connection");
    this.token = token;
    this.port = port;
    this.timeout = timeout;
    this.deliveryTimeout = deliveryTimeout;
    this.provider = provider;
    this.conversation = conversation;
    this.requestId = "kratos-" + randomUUID();
    this.pending = null;
    this.tabId = null;
    this.pageUrl = "";
    this.lastBrowserPoll = null;
    this.completedCommands = 0;
    this.failedCommands = 0;
    this.lastFailure = null;
    this.cancelled = false;
  }

  async start() {
    this.server = createServer(async (request, response) => {
      response.setHeader("Cache-Control", "no-store");
      response.setHeader("Content-Type", "application/json");
      if (!validBrowserToken(request.headers.authorization, this.token)) {
        response.writeHead(401).end("{}");
        return;
      }
      if (request.method === "GET" && request.url === "/health") {
        response.end(
          JSON.stringify({
            ready: true,
            browser_contacted: this.lastBrowserPoll !== null,
            completed_commands: this.completedCommands,
            failed_commands: this.failedCommands,
            last_failure: this.lastFailure,
            pending_action: this.pending?.command.action || null,
            command_delivered: this.pending?.delivered || false,
            cancelled: this.cancelled,
          }),
        );
        return;
      }
      if (request.method === "POST" && request.url === "/cancel") {
        this.cancelled = true;
        if (this.pending) {
          clearTimeout(this.pending.timer);
          clearTimeout(this.pending.deliveryTimer);
          this.pending.reject(new Error("Browser request cancelled"));
          this.pending = null;
        }
        response.end(JSON.stringify({ cancelled: true }));
        return;
      }
      if (request.method === "GET" && request.url === "/work") {
        this.lastBrowserPoll = Date.now();
        if (!this.pending || this.pending.delivered) response.end("{}");
        else {
          this.pending.delivered = true;
          clearTimeout(this.pending.deliveryTimer);
          response.end(JSON.stringify(this.pending.command));
        }
        return;
      }
      if (request.method !== "POST" || request.url !== "/result") {
        response.writeHead(404).end("{}");
        return;
      }
      try {
        const chunks = [];
        let size = 0;
        for await (const chunk of request) {
          size += chunk.length;
          if (size > 32 * 1024 * 1024) throw new Error("Result too large");
          chunks.push(chunk);
        }
        const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (
          !this.pending ||
          body.id !== this.pending.command.id ||
          !this.pending.delivered
        ) {
          response.writeHead(409).end("{}");
          return;
        }
        const pending = this.pending;
        this.pending = null;
        clearTimeout(pending.timer);
        clearTimeout(pending.deliveryTimer);
        if (body.error) {
          this.failedCommands++;
          const error = new Error("Regular browser command failed");
          error.code = [
            "browser_tab_missing",
            "browser_debugger_unavailable",
            "browser_draft_present",
            "browser_page_busy",
            "browser_model_unavailable",
            "browser_effort_unavailable",
            "browser_submit_unavailable",
            "browser_response_incomplete",
          ].includes(body.error)
            ? body.error
            : "browser_operation_failed";
          error.reason = [
            "http",
            "network",
            "body",
            "frames",
            "timeout",
            "capture",
          ].includes(body.error_reason)
            ? body.error_reason
            : null;
          this.lastFailure = { code: error.code, reason: error.reason };
          pending.reject(error);
        } else {
          this.completedCommands++;
          pending.resolve(body.result);
        }
        response.end("{}");
      } catch {
        response.writeHead(400).end("{}");
      }
    });
    await new Promise((resolve, reject) => {
      this.server.once("error", reject);
      this.server.listen(this.port, "127.0.0.1", resolve);
    });
  }

  command(action, data = {}, timeout = this.timeout) {
    if (!["inspect", "release"].includes(action))
      return Promise.reject(new Error("Unsupported cookie collector command"));
    if (this.cancelled && action !== "release")
      return Promise.reject(new Error("Browser request cancelled"));
    if (this.pending)
      return Promise.reject(new Error("Browser command already pending"));
    return new Promise((resolve, reject) => {
      const id = randomUUID();
      const timer = setTimeout(() => {
        clearTimeout(this.pending?.deliveryTimer);
        this.pending = null;
        const error = new Error("Browser extension did not respond");
        error.code = "browser_extension_unavailable";
        reject(error);
      }, timeout);
      const deliveryTimer = setTimeout(
        () => {
          if (this.pending?.command.id !== id || this.pending.delivered) return;
          clearTimeout(timer);
          this.pending = null;
          const error = new Error(
            "Browser extension did not receive the request",
          );
          error.code = "browser_extension_unavailable";
          reject(error);
        },
        Math.min(timeout, this.deliveryTimeout),
      );
      this.pending = {
        resolve,
        reject,
        timer,
        deliveryTimer,
        delivered: false,
        command: {
          id,
          ...data,
          action,
          tab_id: this.tabId,
          request_id: this.requestId,
          provider: this.provider,
          conversation: this.conversation,
        },
      };
    });
  }

  async inspect(timeout = this.timeout) {
    const result = await this.command("inspect", {}, timeout);
    if (
      !result ||
      new URL(result.url).origin !==
        {
          "chatgpt-web": "https://chatgpt.com",
          "qwen-browser": "https://chat.qwen.ai",
          "doubao-web": "https://www.dola.com",
          "gemini-web": "https://gemini.google.com",
          "deepseek-web": "https://chat.deepseek.com",
          "kimi-web": "https://www.kimi.ai",
          "muse-spark-web": "https://www.meta.ai",
          "groq-web": "https://chat.groq.com",
          "grok-web": "https://grok.com",
          "claude-web": "https://claude.ai",
          "perplexity-web": "https://www.perplexity.ai",
          "zai-web": "https://chat.z.ai",
        }[this.provider]
    )
      throw new Error("Open your signed-in ChatGPT tab");
    this.tabId = result.tab_id ?? null;
    this.pageUrl = result.url;
    return result;
  }

  async close() {
    if (!this.server) return;
    if (this.pending) {
      clearTimeout(this.pending.timer);
      clearTimeout(this.pending.deliveryTimer);
      this.pending.reject(new Error("Browser connection closed"));
      this.pending = null;
    }
    if (this.tabId !== null)
      await this.command("release", {}, 2000).catch(() => {});
    await new Promise((resolve) => this.server.close(resolve));
  }
}
