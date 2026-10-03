/**
 * Session manager for DeepSeek Web (chat.deepseek.com).
 *
 * Reserves at most ten attempts before rotating to a fresh page. Preserves all used
 * pages on DeepSeek without deleting them.
 */

export interface DeepSeekSessionEntry {
  sessionId: string;
  createdAt: number;
  promptCount: number;
  maxPrompts: number;
}

import {
  DEFAULT_PAGE_MIN_PROMPTS,
  DEFAULT_PAGE_MAX_PROMPTS,
  getRandomPromptLimit,
} from "../../services/webSessionRotator.ts";

export { DEFAULT_PAGE_MIN_PROMPTS, DEFAULT_PAGE_MAX_PROMPTS, getRandomPromptLimit };
const CACHE_MAX_SIZE = 100;
const pending = new Map<string, Promise<void>>();

export const sessionCache = new Map<string, DeepSeekSessionEntry>();

export function evictOldest(cache: Map<string, unknown>): void {
  if (cache.size >= CACHE_MAX_SIZE) {
    const first = cache.keys().next().value;
    if (first) cache.delete(first);
  }
}

export interface AcquireSessionPageOptions {
  userToken: string;
  accessToken: string;
  minPrompts: number;
  maxPrompts: number;
  signal?: AbortSignal | null;
  createSessionFn: (token: string, sig?: AbortSignal | null) => Promise<string>;
}

export interface SessionPageResult {
  sessionId: string;
  reused: boolean;
  promptCount: number;
  maxPrompts: number;
  rotated: boolean;
}

/**
 * Acquire a session page. Reuses existing page if within prompt limit (5..7),
 * otherwise creates a fresh page and resets the prompt counter.
 */
export async function acquireSessionPage(
  opts: AcquireSessionPageOptions
): Promise<SessionPageResult> {
  const previous = pending.get(opts.userToken) || Promise.resolve();
  const operation = previous.then(() => acquireReservedPage(opts));
  const tail = operation.then(() => {}, () => {});
  pending.set(opts.userToken, tail);
  try {
    return await operation;
  } finally {
    if (pending.get(opts.userToken) === tail) pending.delete(opts.userToken);
  }
}

async function acquireReservedPage(opts: AcquireSessionPageOptions): Promise<SessionPageResult> {
  const cached = sessionCache.get(opts.userToken);
  if (cached && cached.promptCount < cached.maxPrompts) {
    cached.promptCount += 1;
    return {
      sessionId: cached.sessionId,
      reused: true,
      promptCount: cached.promptCount,
      maxPrompts: cached.maxPrompts,
      rotated: false,
    };
  }

  const created = await opts.createSessionFn(opts.accessToken, opts.signal);
  const limit = getRandomPromptLimit(opts.minPrompts, opts.maxPrompts);
  const entry: DeepSeekSessionEntry = {
    sessionId: created,
    createdAt: Date.now(),
    promptCount: 1,
    maxPrompts: limit,
  };
  evictOldest(sessionCache);
  sessionCache.set(opts.userToken, entry);
  return { sessionId: created, reused: false, promptCount: 1, maxPrompts: limit, rotated: !!cached };
}

export function resetSession(userToken: string): void {
  sessionCache.delete(userToken);
}
