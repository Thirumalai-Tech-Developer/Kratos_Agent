import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { startExtensionBridge } from "../../scripts/ops/webSessionSyncBridge";
import { syncConfig } from "../../scripts/ops/webSessionSyncCore";

test("Original Chrome bridge authenticates and accepts renewed credentials without destroying saved sessions", async () => {
  const workspace = await mkdtemp(path.join(tmpdir(), "kratos-sync-test-"));
  const captured: string[] = [];
  const models: unknown[] = [];
  let release: (() => void) | undefined;
  let hold = false;
  const cleared: string[] = [];
  const server = await startExtensionBridge({
    workspace,
    configs: [syncConfig("qwen-browser")!],
    port: 0,
    apply: async (_provider, credential) => {
      captured.push(credential.apiKey!);
      models.push(credential.data.browserModels);
      if (hold)
        await new Promise<void>((resolve) => {
          release = resolve;
        });
    },
    clearModels: async (provider) => {
      cleared.push(provider);
    },
  });
  try {
    const address = server.address();
    assert.ok(address && typeof address === "object");
    assert.equal(address.address, "127.0.0.1");
    const url = `http://127.0.0.1:${address.port}/sync`;
    const { token } = JSON.parse(
      await readFile(path.join(workspace, ".kratos/browser-sync/bridge.json"), "utf8")
    );
    const payload = (value: string) => ({
      provider: "qwen-browser",
      snapshot: {
        cookies: [],
        storage: { token: value },
        userAgent: "Chrome",
      },
    });
    const post = (body: unknown, authorized = true) =>
      fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authorized ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
    assert.equal((await post(payload("first"), false)).status, 401);
    assert.equal(
      (
        await post({
          provider: "qwen-browser",
          snapshot: { cookies: [{}], storage: {}, userAgent: "Chrome" },
        })
      ).status,
      400
    );
    assert.equal((await post(payload("first"))).status, 200);
    assert.equal((await post(payload("renewed"))).status, 200);
    assert.equal(
      (
        await post({
          ...payload("renewed"),
          snapshot: {
            ...payload("renewed").snapshot,
            models: [{ id: "qwen-ui-observed", name: "Observed Qwen", selectable: true }],
          },
        })
      ).status,
      200
    );
    assert.deepEqual(models.at(-1), [
      { id: "qwen-ui-observed", name: "Observed Qwen", selectable: true },
    ]);
    assert.equal(
      (
        await post({
          ...payload("renewed"),
          snapshot: {
            ...payload("renewed").snapshot,
            models: [{ id: "bad/id", name: "Invalid", selectable: true }],
          },
        })
      ).status,
      400
    );
    assert.equal((await post(payload(""))).status, 422);
    assert.equal(
      (
        await post({
          ...payload(""),
          snapshot: {
            ...payload("").snapshot,
            models: [],
          },
        })
      ).status,
      202
    );
    assert.deepEqual(cleared, ["qwen-browser"]);
    assert.deepEqual(captured, ["first", "renewed", "renewed"]);
    hold = true;
    const active = post(payload("held"));
    while (!release) await new Promise((resolve) => setTimeout(resolve, 5));
    assert.equal((await post(payload("duplicate"))).status, 409);
    assert.equal((await post(payload("second-duplicate"))).status, 409);
    release();
    assert.equal((await active).status, 200);
    assert.deepEqual(captured, ["first", "renewed", "renewed", "held"]);
  } finally {
    release?.();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(workspace, { recursive: true, force: true });
  }
});
