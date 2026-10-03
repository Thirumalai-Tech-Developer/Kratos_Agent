import { randomUUID } from "node:crypto";
import type { Page } from "playwright";

/** Observe a cloned fetch stream without changing the provider UI's response. */
export async function installSseCapture(
  page: Page,
  chatUrl: string,
  completion: { phase: string; status: string },
  maxBytes: number
): Promise<string> {
  const key = `__omniroute_${randomUUID().replaceAll("-", "")}`;
  await page.addInitScript(
    ({ key, chatUrl, completion, maxBytes }) => {
      type Capture = { text: string; done: boolean; failed: boolean };
      const captures = window as unknown as Record<string, Capture>;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const request = args[0];
        const method = args[1]?.method || (request instanceof Request ? request.method : "GET");
        const expected = new URL(chatUrl);
        const observed = new URL(response.url);
        if (
          method.toUpperCase() !== "POST" ||
          observed.origin !== expected.origin ||
          observed.pathname !== expected.pathname ||
          !response.headers.get("content-type")?.includes("text/event-stream")
        )
          return response;
        const capture: Capture = { text: "", done: false, failed: false };
        captures[key] = capture;
        const reader = response.clone().body?.getReader();
        if (!reader) {
          capture.failed = true;
          capture.done = true;
          return response;
        }
        void (async () => {
          let bytes = 0;
          let pending = "";
          const decoder = new TextDecoder();
          const protocol = {
            isDone(event: string): boolean {
              const data = event
                .split(/\r?\n/)
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).trimStart())
                .join("\n");
              if (data.trim() === "[DONE]") return true;
              try {
                const frame = JSON.parse(data) as {
                  error?: unknown;
                  choices?: Array<{
                    delta?: { phase?: string; status?: string };
                    finish_reason?: string | null;
                  }>;
                };
                return (
                  !!frame.error ||
                  !!frame.choices?.some(
                    (choice) =>
                      (choice.delta?.phase === completion.phase &&
                        choice.delta?.status === completion.status) ||
                      choice.finish_reason === "stop"
                  )
                );
              } catch {
                return false;
              }
            },
          };
          try {
            while (true) {
              const { value, done } = await reader.read();
              bytes += value?.byteLength || 0;
              if (bytes > maxBytes) {
                capture.failed = true;
                break;
              }
              const chunk = decoder.decode(value, { stream: !done });
              capture.text += chunk;
              pending += chunk;
              const events = pending.split(/\r?\n\r?\n/);
              pending = events.pop() || "";
              if (events.some((event) => protocol.isDone(event)) || done) break;
            }
          } catch {
            capture.failed = true;
          } finally {
            capture.done = true;
            // Cancelling the clone may wait for the original stream. Do not await it.
            void reader.cancel().catch(() => {});
          }
        })();
        return response;
      };
    },
    { key, chatUrl, completion, maxBytes }
  );
  return key;
}

export async function readSseCapture(page: Page, key: string, timeout: number): Promise<string> {
  await page.waitForFunction(
    (key) => (window as unknown as Record<string, { done?: boolean }>)[key]?.done === true,
    key,
    { timeout }
  );
  const capture = await page.evaluate((key) => {
    const captures = window as unknown as Record<string, { text: string; failed: boolean }>;
    const result = captures[key];
    delete captures[key];
    return result;
  }, key);
  if (!capture || capture.failed)
    throw new Error("Browser chat stream capture failed or exceeded its size limit");
  return capture.text;
}
