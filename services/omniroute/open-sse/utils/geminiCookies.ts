type CookieRecord = Record<string, unknown>;

function cookiePairsFromJson(raw: string): string[] {
  if (!raw.startsWith("{")) return [];
  try {
    const parsed = JSON.parse(raw) as CookieRecord;
    const cookies =
      parsed.cookies && typeof parsed.cookies === "object" && !Array.isArray(parsed.cookies)
        ? (parsed.cookies as CookieRecord)
        : parsed;
    return Object.entries(cookies)
      .filter(([, value]) => typeof value === "string" && value.trim().length > 0)
      .map(([name, value]) => `${name}=${String(value).trim()}`);
  } catch {
    return [];
  }
}

function cookiePairsFromTsv(raw: string): string[] {
  if (!raw.includes("\t")) return [];
  const lines = raw.split(/\r?\n/);
  const pairs: string[] = [];
  for (const line of lines) {
    const parts = line.split("\t");
    if (parts.length >= 2) {
      const name = parts[0]?.trim();
      const value = parts[1]?.trim();
      if (name && value && !name.startsWith("#") && !name.toLowerCase().includes("name")) {
        pairs.push(`${name}=${value}`);
      }
    }
  }
  return pairs;
}

/** Normalize a pasted Gemini cookie header, bare PSID, browser-export JSON, or DevTools TSV table. */
export function normalizeGeminiCookieInput(raw: string, cookieName = "__Secure-1PSID"): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  const jsonPairs = cookiePairsFromJson(trimmed);
  if (jsonPairs.length > 0) return jsonPairs.join("; ");
  const tsvPairs = cookiePairsFromTsv(trimmed);
  if (tsvPairs.length > 0) return tsvPairs.join("; ");
  return trimmed.includes("=") ? trimmed : `${cookieName}=${trimmed}`;
}
