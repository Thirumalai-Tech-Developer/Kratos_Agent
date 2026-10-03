/** Authorized browser-session watcher. Does not generate chats or solve challenges. */
import { createHash } from "node:crypto";
import { readFile, mkdir, open, unlink } from "node:fs/promises";
import path from "node:path";
import { parseArgs } from "node:util";
import { chromium, type BrowserContext, type Page } from "playwright";
import { startExtensionBridge } from "./webSessionSyncBridge";
import {
  CONSUMER_PROVIDERS,
  blockedConnection,
  metaAuthorization,
  normalizeSnapshot,
  syncConfig,
} from "./webSessionSyncCore";

async function main() {
  const { values } = parseArgs({
    options: {
      workspace: { type: "string", default: process.cwd() },
      "data-dir": { type: "string" },
      providers: { type: "string", default: "qwen-browser,doubao-web,kimi-web" },
      cdp: { type: "string" },
      interval: { type: "string", default: "30" },
      once: { type: "boolean", default: false },
      list: { type: "boolean", default: false },
      help: { type: "boolean", default: false },
    },
  });
  if (values.help) {
    console.log(
      "Browser session sync: --workspace PATH --providers all [--cdp http://127.0.0.1:9222] [--list]\nUses the original signed-in Chrome via a local extension receiver by default. Load the generated unpacked extension once. Cookies and tokens update automatically; no new profile or login. Ctrl+C stops the receiver."
    );
    return;
  }
  if (values.list) {
    console.log(CONSUMER_PROVIDERS.filter((provider) => syncConfig(provider)).join("\n"));
    return;
  }
  const interval = Number(values.interval);
  if (!Number.isFinite(interval) || interval < 10 || interval > 3600)
    throw new Error("Use an interval between 10 and 3600 seconds.");
  const providers =
    values.providers === "all"
      ? CONSUMER_PROVIDERS.filter((provider) => syncConfig(provider))
      : [...new Set(values.providers.split(",").map((value) => value.trim()))];
  const configs = providers.map((provider) => {
    const config = syncConfig(provider);
    if (!config) throw new Error(`Unsupported provider: ${provider}. Use --list.`);
    return config;
  });
  const workspace = path.resolve(values.workspace);
  const dataDir = path.resolve(
    values["data-dir"] || path.join(workspace, ".kratos/studio/gateway")
  );
  const secrets = JSON.parse(await readFile(path.join(dataDir, "studio-secrets.json"), "utf8"));
  if (typeof secrets.STORAGE_ENCRYPTION_KEY !== "string" || !secrets.STORAGE_ENCRYPTION_KEY.trim())
    throw new Error("Studio encryption key is missing or invalid. Start Studio once first.");
  // Import DB only after the actual Studio directory and key have been established.
  process.env.DATA_DIR = dataDir;
  process.env.STORAGE_ENCRYPTION_KEY = secrets.STORAGE_ENCRYPTION_KEY;
  const db = await import("../../src/lib/db/providers");
  const { sealBrowserSyncCredential } = await import("../../src/lib/db/encryption");
  const { persistBrowserDiscoveredModels } =
    await import("../../src/lib/providerModels/browserModelDiscovery");
  const lockPath = path.join(workspace, ".kratos/browser-sync/sync.pid");
  await mkdir(path.dirname(lockPath), { recursive: true });
  try {
    const previous = Number(await readFile(lockPath, "utf8"));
    if (Number.isInteger(previous) && previous > 0) {
      try {
        process.kill(previous, 0);
        throw new Error("A session watcher is already running for this workspace.");
      } catch (error) {
        if (!(error && typeof error === "object" && "code" in error && error.code === "ESRCH"))
          throw error;
      }
    }
    await unlink(lockPath);
  } catch (error) {
    if (!(error && typeof error === "object" && "code" in error && error.code === "ENOENT"))
      throw error;
  }
  const lease = await open(lockPath, "wx", 0o600);
  await lease.writeFile(String(process.pid));
  await lease.close();
  const profileId = createHash("sha256")
    .update(values.cdp || "original-chrome")
    .digest("hex")
    .slice(0, 20);
  const storedFingerprints = new Map<string, string>();
  const applyCaptured = async (
    provider: string,
    captured: NonNullable<ReturnType<typeof normalizeSnapshot>>
  ) => {
    const connections = await db.getProviderConnections({ provider });
    if (connections.some((connection) => blockedConnection(connection)))
      throw new Error("Provider account restricted");
    if (storedFingerprints.get(provider) === captured.fingerprint) return;
    const current = connections.find((connection) => {
      const data = connection.providerSpecificData;
      return (
        data &&
        typeof data === "object" &&
        "browserSyncProfile" in data &&
        data.browserSyncProfile === profileId
      );
    });
    const credentialData = { ...captured.data };
    const currentData = current?.providerSpecificData;
    // A cookie renewal with no open picker must retain the last actual model observation.
    if (currentData && typeof currentData === "object") {
      const previous = currentData as Record<string, unknown>;
      if (credentialData.browserModels === undefined && Array.isArray(previous.browserModels)) {
        credentialData.browserModels = previous.browserModels;
        credentialData.browserModelsObservedAt = previous.browserModelsObservedAt;
      }
    }
    if (captured.data.browserModels !== undefined)
      credentialData.browserModelsObservedAt = new Date().toISOString();
    const providerSpecificData = {
      browserSyncCredential: sealBrowserSyncCredential(credentialData),
      browserSyncProfile: profileId,
      browserSyncedAt: new Date().toISOString(),
      ...(typeof captured.data.cookieExpiresAt === "string"
        ? { cookieExpiresAt: captured.data.cookieExpiresAt }
        : {}),
    };
    const patch: Record<string, unknown> = {
      apiKey: captured.apiKey || captured.data.cookie || null,
      providerSpecificData,
    };
    let connectionId: string;
    if (current && typeof current.id === "string") {
      connectionId = current.id;
      if (
        current.testStatus === "expired" &&
        !(
          typeof current.rateLimitedUntil === "string" &&
          Date.parse(current.rateLimitedUntil) > Date.now()
        )
      ) {
        Object.assign(patch, {
          testStatus: "unknown",
          lastError: null,
          lastErrorType: null,
          errorCode: null,
        });
      }
      await db.updateProviderConnection(current.id, patch);
    } else {
      const created = await db.createProviderConnection({
        ...patch,
        provider,
        authType: "apikey",
        name: `Browser sync ${profileId}`,
        isActive: true,
        testStatus: "unknown",
        priority: 10,
      });
      if (!created || typeof created.id !== "string")
        throw new Error("Browser sync connection could not be saved");
      connectionId = created.id;
    }
    if (credentialData.browserModels !== undefined)
      await persistBrowserDiscoveredModels(provider, connectionId, credentialData.browserModels);
    storedFingerprints.set(provider, captured.fingerprint);
    console.log(`${provider}: credentials synced to encrypted store`);
  };
  if (!values.cdp) {
    const receiver = await startExtensionBridge({
      workspace,
      configs,
      apply: applyCaptured,
      clearModels: async (provider) => {
        const connections = await db.getProviderConnections({ provider });
        const current = connections.find((connection) => {
          const data = connection.providerSpecificData;
          return (
            data &&
            typeof data === "object" &&
            "browserSyncProfile" in data &&
            data.browserSyncProfile === profileId
          );
        });
        if (!current || typeof current.id !== "string") return;
        const credentialData = { ...(current.providerSpecificData as Record<string, unknown>) };
        delete credentialData.browserSyncCredential;
        credentialData.browserModels = [];
        credentialData.browserModelsObservedAt = new Date().toISOString();
        await db.updateProviderConnection(current.id, {
          providerSpecificData: {
            browserSyncProfile: profileId,
            browserSyncCredential: sealBrowserSyncCredential(credentialData),
          },
        });
        await persistBrowserDiscoveredModels(provider, current.id, []);
        storedFingerprints.delete(provider);
      },
    });
    const stopReceiver = () => {
      receiver.closeAllConnections();
      receiver.close(() => process.exit(0));
    };
    process.on("SIGINT", stopReceiver);
    process.on("SIGTERM", stopReceiver);
    receiver.on("close", () => {
      void unlink(lockPath).catch(() => {});
    });
    return;
  }
  let context: BrowserContext;
  let disconnect: () => Promise<void>;
  if (values.cdp) {
    const endpoint = new URL(values.cdp);
    if (
      !["127.0.0.1", "localhost", "[::1]"].includes(endpoint.hostname) ||
      !["http:", "ws:"].includes(endpoint.protocol)
    )
      throw new Error("CDP must point to a local authorized browser.");
    const browser = await chromium.connectOverCDP(values.cdp);
    const contexts = browser.contexts();
    if (contexts.length !== 1) throw new Error("Expected one authorized browser context.");
    context = contexts[0];
    disconnect = () => browser.close(); // Playwright disconnects a CDP client; it does not close the user's Chrome.
  } else throw new Error("Use the original signed-in Chrome extension or local CDP.");
  const observed = new WeakSet<Page>();
  const authorizations = new WeakMap<Page, string>();
  const observe = (page: Page) => {
    if (observed.has(page)) return;
    observed.add(page);
    page.on("websocket", (socket) => {
      const authorization = metaAuthorization(socket.url());
      if (authorization) authorizations.set(page, authorization);
    });
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) authorizations.delete(page);
    });
  };
  context.pages().forEach(observe);
  context.on("page", observe);
  let stopped = false;
  let wake: (() => void) | undefined;
  const stop = () => {
    stopped = true;
    wake?.();
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  const fingerprints = new Map<string, string>();
  const statuses = new Map<string, string>();
  const report = (provider: string, status: string) => {
    if (statuses.get(provider) === status) return;
    statuses.set(provider, status);
    console.log(`${provider}: ${status}`);
  };
  context.on("close", stop);
  console.log(
    "Session watcher attached to your original Chrome. Renewed credentials sync automatically; inference availability is checked separately by the gateway."
  );
  try {
    do {
      for (const config of configs) {
        if (stopped) break;
        const provider = config.providerId;
        try {
          const connections = await db.getProviderConnections({ provider });
          if (connections.some((connection) => blockedConnection(connection))) {
            report(
              provider,
              "blocked by provider account restriction; no refresh or account substitution"
            );
            continue;
          }
          const origin = new URL(config.homeUrl).origin;
          const page = context.pages().find((candidate) => {
            try {
              return new URL(candidate.url()).origin === origin;
            } catch {
              return false;
            }
          });
          if (!page) {
            report(provider, "open its signed-in tab in this browser profile");
            continue;
          }
          const sources = config.tokenSources.filter(
            (source) => source.type === "localStorage" || source.type === "sessionStorage"
          );
          const snapshot = await page.evaluate((sources) => {
            const storage: Record<string, string> = {};
            for (const source of sources) {
              if (source.type !== "localStorage" && source.type !== "sessionStorage") continue;
              const value = (
                source.type === "localStorage" ? localStorage : sessionStorage
              ).getItem(source.key);
              if (value) storage[source.key] = value;
            }
            return { storage, userAgent: navigator.userAgent };
          }, sources);
          const captured = normalizeSnapshot(provider, {
            ...snapshot,
            cookies: await context.cookies(),
            authorization: authorizations.get(page),
          });
          if (!captured) {
            report(
              provider,
              "sign-in or required companion credential missing/expired; stored credentials retained"
            );
            continue;
          }
          if (fingerprints.get(provider) === captured.fingerprint) continue;
          await applyCaptured(provider, captured);
          fingerprints.set(provider, captured.fingerprint);
          report(provider, "credentials synced to encrypted store");
        } catch {
          report(
            provider,
            "sync unavailable; retrying next interval, existing credentials retained"
          );
        }
      }
      if (values.once || stopped) break;
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, interval * 1000);
        wake = () => {
          clearTimeout(timer);
          resolve();
        };
      });
      wake = undefined;
    } while (!stopped);
  } finally {
    process.off("SIGINT", stop);
    process.off("SIGTERM", stop);
    await disconnect();
    await unlink(lockPath).catch(() => {});
  }
}

main().catch(() => {
  console.error(
    "Browser sync could not start. Check Studio secrets, provider IDs and local receiver access. Raw errors are hidden because browser failures can contain credentials."
  );
  process.exitCode = 1;
});
