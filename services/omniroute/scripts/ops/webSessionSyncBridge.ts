import { timingSafeEqual, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile, copyFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import type { TokenExtractionConfig } from "../../open-sse/services/tokenExtractionConfig";
import { browserModelsSchema } from "../../open-sse/utils/browserModels";
import { normalizeSnapshot } from "./webSessionSyncCore";

const snapshotSchema = z.object({
  cookies: z
    .array(
      z.object({
        name: z.string().max(1024),
        value: z.string().max(65536),
        domain: z.string().max(1024),
        path: z.string().max(2048).optional(),
        expires: z.number().finite().optional(),
      })
    )
    .max(500),
  storage: z.record(z.string(), z.string().max(65536)),
  userAgent: z.string().max(4096),
  authorization: z.string().max(65536).optional(),
  models: browserModelsSchema.optional(),
});

export function validBridgeToken(actual: string, expected: string): boolean {
  const left = Buffer.from(actual);
  const right = Buffer.from(`Bearer ${expected}`);
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function prepareExtension(workspace: string, configs: TokenExtractionConfig[]) {
  const directory = path.join(workspace, ".kratos/browser-sync");
  const destination = path.join(directory, "chrome-extension");
  await mkdir(destination, { recursive: true });
  const secretPath = path.join(directory, "bridge.json");
  let token: string;
  try {
    const saved = JSON.parse(await readFile(secretPath, "utf8"));
    if (typeof saved.token !== "string" || !/^[0-9a-f]{64}$/i.test(saved.token))
      throw new Error("Invalid bridge configuration");
    token = saved.token;
  } catch (error) {
    if (!(error && typeof error === "object" && "code" in error && error.code === "ENOENT"))
      throw error;
    token = randomBytes(32).toString("hex");
    await writeFile(secretPath, JSON.stringify({ token }), { mode: 0o600, flag: "wx" });
  }
  const providers = configs.map((config) => ({
    id: config.providerId,
    homeUrl: config.homeUrl,
    domain: config.cookieDomain || new URL(config.homeUrl).hostname,
    sources: config.tokenSources,
  }));
  const matches = [...new Set(configs.map((config) => new URL(config.homeUrl).origin + "/*"))];
  const hosts = [
    ...new Set(
      configs.map(
        (config) =>
          `https://*.${(config.cookieDomain || new URL(config.homeUrl).hostname).replace(/^\./, "")}/*`
      )
    ),
  ];
  const manifest = {
    manifest_version: 3,
    name: "Kratos automatic browser session sync",
    version: "1.1.1",
    description:
      "Sync renewed sessions from your original signed-in Chrome tabs to your local Kratos gateway.",
    permissions: ["cookies", "alarms", "scripting"],
    host_permissions: [...hosts, "http://127.0.0.1:20129/*"],
    background: { service_worker: "background.js" },
    action: { default_title: "Kratos automatic sync" },
    content_scripts: [
      { matches, js: ["modelDiscovery.js", "content.js"], run_at: "document_start" },
      { matches, js: ["modelObserver.js"], run_at: "document_start", world: "MAIN" },
      ...(configs.some((config) => config.providerId === "muse-spark-web")
        ? [
            {
              matches: ["https://www.meta.ai/*"],
              js: ["metaObserver.js"],
              run_at: "document_start",
              world: "MAIN",
            },
          ]
        : []),
    ],
  };
  await writeFile(path.join(destination, "manifest.json"), JSON.stringify(manifest, null, 2));
  await writeFile(
    path.join(destination, "config.js"),
    `const SYNC_CONFIG = ${JSON.stringify({ token, endpoint: "http://127.0.0.1:20129", providers })};`,
    { mode: 0o600 }
  );
  const source = path.join(path.dirname(fileURLToPath(import.meta.url)), "browserSyncExtension");
  for (const name of [
    "background.js",
    "modelDiscovery.js",
    "modelObserver.js",
    "content.js",
    "metaObserver.js",
  ])
    await copyFile(path.join(source, name), path.join(destination, name));
  return { token, directory: destination };
}

export async function startExtensionBridge(options: {
  workspace: string;
  configs: TokenExtractionConfig[];
  port?: number;
  apply: (
    provider: string,
    captured: NonNullable<ReturnType<typeof normalizeSnapshot>>
  ) => Promise<void>;
  clearModels?: (provider: string) => Promise<void>;
}) {
  const prepared = await prepareExtension(options.workspace, options.configs);
  const allowed = new Set(options.configs.map((config) => config.providerId));
  const pending = new Set<string>();
  const server = createServer(async (request, response) => {
    const respond = (status: number, body: string) => {
      response.writeHead(status, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      });
      response.end(JSON.stringify({ status: body }));
    };
    if (!validBridgeToken(request.headers.authorization || "", prepared.token)) {
      respond(401, "unauthorized");
      return;
    }
    if (request.method !== "POST" || request.url !== "/sync") {
      respond(404, "not_found");
      return;
    }
    let provider = "";
    let acquired = false;
    try {
      let length = 0;
      const parts: Buffer[] = [];
      for await (const part of request) {
        const buffer = Buffer.from(part);
        length += buffer.length;
        if (length > 256 * 1024) {
          respond(413, "too_large");
          request.resume();
          return;
        }
        parts.push(buffer);
      }
      const body = JSON.parse(Buffer.concat(parts).toString("utf8"));
      provider = typeof body.provider === "string" ? body.provider : "";
      if (!allowed.has(provider)) {
        respond(400, "unsupported_provider");
        return;
      }
      if (pending.has(provider)) {
        respond(409, "sync_in_progress");
        return;
      }
      const validated = snapshotSchema.safeParse(body.snapshot);
      if (!validated.success) {
        respond(400, "invalid_snapshot");
        return;
      }
      const captured = normalizeSnapshot(provider, validated.data);
      if (!captured) {
        if (validated.data.models?.length === 0 && options.clearModels) {
          pending.add(provider);
          acquired = true;
          await options.clearModels(provider);
          respond(202, "models_cleared");
          return;
        }
        respond(422, "sign_in_or_companion_credential_required");
        return;
      }
      pending.add(provider);
      acquired = true;
      await options.apply(provider, captured);
      respond(200, "synced");
    } catch {
      respond(503, "sync_unavailable");
    } finally {
      if (acquired) pending.delete(provider);
    }
  });
  server.headersTimeout = 10000;
  server.requestTimeout = 15000;
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(options.port ?? 20129, "127.0.0.1", () => resolve());
  });
  console.log(
    `Original-Chrome sync receiver running. Load this folder once in chrome://extensions (Load unpacked): ${prepared.directory}`
  );
  console.log(
    "Existing signed-in tabs will sync automatically. No new browser profile or login is created."
  );
  return server;
}
