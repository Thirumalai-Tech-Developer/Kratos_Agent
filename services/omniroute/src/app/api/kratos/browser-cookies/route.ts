import { isTrustedLoopbackInternalServiceRequest } from "@/lib/api/internalServiceAuth";
import { BrowserCookieHandoffError, handoffBrowserCookies } from "@/lib/kratos/browserCookieHandoff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const MAX_BYTES = 12 * 1024 * 1024;
const headers = { "Cache-Control": "no-store" };

export async function POST(request: Request) {
  // Locality is the server/pipeline's trusted TCP verdict, never a Host header.
  if (!isTrustedLoopbackInternalServiceRequest(request) || request.headers.has("origin"))
    return Response.json({ error: "unauthorized_cookie_handoff" }, { status: 403, headers });
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))
    return Response.json({ error: "invalid_cookie_snapshot" }, { status: 400, headers });
  const length = Number(request.headers.get("content-length") || 0);
  if (!Number.isSafeInteger(length) || length < 0 || length > MAX_BYTES)
    return Response.json({ error: "cookie_snapshot_too_large" }, { status: 413, headers });
  try {
    if (!request.body) throw new BrowserCookieHandoffError(400, "invalid_cookie_snapshot");
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BYTES) { await reader.cancel(); throw new BrowserCookieHandoffError(413, "cookie_snapshot_too_large"); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    return Response.json(await handoffBrowserCookies(payload), { headers });
  } catch (error) {
    const status = error instanceof BrowserCookieHandoffError ? error.status : error instanceof SyntaxError ? 400 : 503;
    const code = error instanceof BrowserCookieHandoffError ? error.code : status === 400 ? "invalid_cookie_snapshot" : "gateway_store_unavailable";
    // Raw exceptions can contain cookie envelopes, request bodies or DB secrets.
    return Response.json({ error: code }, { status, headers });
  }
}
