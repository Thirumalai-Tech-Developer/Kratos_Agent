import { proxyKratos } from "@/lib/kratos/proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ path?: string[] }> };
async function handle(request: Request, context: Context) {
  return proxyKratos(request, (await context.params).path || [], "api");
}
export { handle as GET, handle as POST, handle as DELETE };
