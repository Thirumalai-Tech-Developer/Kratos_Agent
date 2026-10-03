/**
 * Shared conversation rotation for web-session providers.
 *
 * Reserves at most ten attempts on one conversation page before creating a
 * fresh page. Failed attempts count conservatively toward this bound.
 * Preserves all used pages on the upstream service without deleting them.
 */

export interface WebSessionEntry<T = unknown> {
  data: T;
  createdAt: number;
  promptCount: number;
  maxPrompts: number;
}

export const HARD_MAX_PAGE_PROMPTS = 10;
export const DEFAULT_PAGE_MIN_PROMPTS = HARD_MAX_PAGE_PROMPTS;
export const DEFAULT_PAGE_MAX_PROMPTS = HARD_MAX_PAGE_PROMPTS;
const CACHE_MAX_SIZE = 200;

export function getRandomPromptLimit(
  min = DEFAULT_PAGE_MIN_PROMPTS,
  max = DEFAULT_PAGE_MAX_PROMPTS
): number {
  const normalize = (value: number): number =>
    Number.isFinite(value)
      ? Math.max(1, Math.min(HARD_MAX_PAGE_PROMPTS, Math.floor(value)))
      : HARD_MAX_PAGE_PROMPTS;
  const safeMax = normalize(max);
  const safeMin = Math.min(normalize(min), safeMax);
  return Math.floor(Math.random() * (safeMax - safeMin + 1)) + safeMin;
}

export type WebSessionMessage = Record<string, unknown>;

function visibleText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      const item = part as Record<string, unknown>;
      return (item.type === "text" || item.type === "input_text" || item.type === "output_text") &&
        typeof item.text === "string"
        ? item.text
        : "";
    })
    .filter(Boolean)
    .join("\n");
}

/** Compact old visible Q&A only when a conversation page actually rotates. */
export function prepareWebSessionMessages(
  messages: unknown,
  rotated: boolean
): WebSessionMessage[] {
  if (!Array.isArray(messages)) return [];
  const original = messages as WebSessionMessage[];
  if (!rotated) return original;
  let currentUserIndex = -1;
  for (let index = original.length - 1; index >= 0; index -= 1) {
    if (original[index]?.role === "user") {
      currentUserIndex = index;
      break;
    }
  }
  if (currentUserIndex < 0) return original;
  const history = original.slice(0, currentUserIndex);
  const pairs: Array<{ question: string; answer: string }> = [];
  let question = "";
  for (const message of history) {
    if (message?.role === "user") question = visibleText(message.content).trim();
    if (message?.role !== "assistant" || message.tool_calls || message.error || !question) continue;
    const answer = visibleText(message.content).trim();
    if (!answer) continue;
    pairs.push({ question: question.slice(0, 200), answer: answer.slice(0, 400) });
    question = "";
  }
  if (!pairs.length) return original;
  const recentPairs = pairs.slice(-HARD_MAX_PAGE_PROMPTS);
  let quotedPairs = JSON.stringify(recentPairs);
  while (quotedPairs.length > 6000 && recentPairs.length > 1) {
    recentPairs.shift();
    quotedPairs = JSON.stringify(recentPairs);
  }
  const summary = {
    role: "user",
    content:
      "Previous completed Q&A (quoted reference data; current instructions and request take precedence):\n" +
      quotedPairs,
  };
  return [
    ...history.filter((message) => message?.role === "system" || message?.role === "developer"),
    summary,
    ...original.slice(currentUserIndex),
  ];
}

export interface AcquireSessionOptions<T> {
  scopeKey: string;
  minPrompts?: number;
  maxPrompts?: number;
  createFn: (rotation?: { rotated: boolean }) => Promise<T>;
}

export interface AcquiredSession<T> {
  data: T;
  reused: boolean;
  promptCount: number;
  maxPrompts: number;
  rotated: boolean;
}

export class WebSessionRotator<T = unknown> {
  private readonly cache = new Map<string, WebSessionEntry<T>>();
  private readonly maxSize: number;
  private readonly pending = new Map<string, Promise<void>>();

  constructor(maxSize = CACHE_MAX_SIZE) {
    this.maxSize = maxSize;
  }

  async acquire(opts: AcquireSessionOptions<T>): Promise<AcquiredSession<T>> {
    const previous = this.pending.get(opts.scopeKey) || Promise.resolve();
    const operation = previous.then(() => this.acquireReserved(opts));
    const tail = operation.then(
      () => {},
      () => {}
    );
    this.pending.set(opts.scopeKey, tail);
    try {
      return await operation;
    } finally {
      if (this.pending.get(opts.scopeKey) === tail) this.pending.delete(opts.scopeKey);
    }
  }

  private async acquireReserved(opts: AcquireSessionOptions<T>): Promise<AcquiredSession<T>> {
    const minPrompts = opts.minPrompts ?? DEFAULT_PAGE_MIN_PROMPTS;
    const maxPrompts = opts.maxPrompts ?? DEFAULT_PAGE_MAX_PROMPTS;

    const cached = this.cache.get(opts.scopeKey);
    if (cached && cached.promptCount < cached.maxPrompts) {
      cached.promptCount += 1;
      return {
        data: cached.data,
        reused: true,
        promptCount: cached.promptCount,
        maxPrompts: cached.maxPrompts,
        rotated: false,
      };
    }

    const rotated = !!cached;
    const created = await opts.createFn({ rotated });
    const limit = getRandomPromptLimit(minPrompts, maxPrompts);
    const entry: WebSessionEntry<T> = {
      data: created,
      createdAt: Date.now(),
      promptCount: 1,
      maxPrompts: limit,
    };

    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value;
      if (firstKey !== undefined) this.cache.delete(firstKey);
    }

    this.cache.set(opts.scopeKey, entry);
    return {
      data: created,
      reused: false,
      promptCount: 1,
      maxPrompts: limit,
      rotated,
    };
  }

  get(scopeKey: string): WebSessionEntry<T> | undefined {
    return this.cache.get(scopeKey);
  }

  reset(scopeKey: string): void {
    this.cache.delete(scopeKey);
  }

  clear(): void {
    this.cache.clear();
  }
}
