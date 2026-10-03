import { proxyKratos } from "@/lib/kratos/proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  return proxyKratos(request, (await context.params).path || [], "workspace");
}
