import { z } from "zod";
import { buildErrorBody } from "@omniroute/open-sse/utils/error.ts";

const segmentsSchema = z.array(z.string().min(1).max(200).refine(
  (value) => !/[\\/\u0000-\u001f]/.test(value) && value !== "." && value !== ".."
)).max(16);

export function kratosTarget(segments: string[], surface: "api" | "workspace"): URL {
  const parsed = segmentsSchema.parse(segments);
  const port = z.coerce.number().int().min(1).max(65535).parse(process.env.KRATOS_AGENT_PORT || 7860);
  const path = parsed.map(encodeURIComponent).join("/");
  return new URL(`${surface === "api" ? "/api/" : "/"}${path}`, `http://127.0.0.1:${port}`);
}

export async function proxyKratos(request: Request, segments: string[], surface: "api" | "workspace") {
  const token = process.env.KRATOS_INTERNAL_TOKEN;
  if (!token) return Response.json(buildErrorBody(503, "Start Kratos Studio to connect the agent workspace."), { status: 503 });
  const origin = request.headers.get("origin");
  // Next's internal request URL can use a different host/port than the browser-facing
  // gateway. Studio supplies the latter explicitly when it starts the service.
  const allowedOrigins = new Set([new URL(request.url).origin]);
  const gatewayUrl = process.env.KRATOS_GATEWAY_URL;
  if (gatewayUrl) {
    try {
      allowedOrigins.add(new URL(gatewayUrl).origin);
    } catch {
      // An invalid gateway URL must not grant access to any additional origin.
    }
  }
  if (origin && !allowedOrigins.has(origin)) {
    return Response.json(buildErrorBody(403, "Cross-origin agent requests are not allowed."), { status: 403 });
  }
  let target: URL;
  try {
    target = kratosTarget(segments, surface);
  } catch {
    return Response.json(buildErrorBody(400, "Invalid workspace path."), { status: 400 });
  }
  target.search = new URL(request.url).search;
  const headers = new Headers({ "X-Kratos-Internal-Token": token });
  for (const name of ["content-type", "accept", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const hasBody = !["GET", "HEAD"].includes(request.method);
    const response = await fetch(target, {
      method: request.method, headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      signal: request.signal, cache: "no-store", redirect: "manual",
    });
    const outgoing = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "x-request-id"]) {
      const value = response.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    if (surface === "workspace") {
      outgoing.set("Content-Security-Policy", "frame-ancestors 'self'");
      outgoing.set("X-Frame-Options", "SAMEORIGIN");
    }
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch {
    return Response.json(buildErrorBody(503, "Kratos runtime is unavailable. Check Studio service logs."), { status: 503 });
  }
}
