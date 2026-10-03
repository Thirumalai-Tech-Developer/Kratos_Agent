import assert from "node:assert/strict";
import test from "node:test";

import { executableBrowserModels } from "../../src/lib/providerModels/browserModelDiscovery.ts";
import { resolveBrowserModel, browserModelsSchema } from "../../open-sse/utils/browserModels.ts";
import { mergeProviderModelListing } from "../../src/lib/providers/mergeProviderModelListing.ts";
import { MuseSparkWebExecutor } from "../../open-sse/executors/muse-spark-web.ts";
import { resetDbInstance } from "../../src/lib/db/core.ts";

test.after(() => resetDbInstance());

const observed = [
  { id: "qwen-ui-qwen3.8-max", name: "Qwen3.8-Max", selectable: true, free: true },
  {
    id: "qwen-ui-qwen3.8-omni-flash",
    name: "Qwen3.8-Omni-Flash",
    selectable: true,
    free: true,
    supportsVision: true,
  },
  { id: "locked", name: "Locked", selectable: false, free: true },
  { id: "paid", name: "Paid", selectable: true, free: false },
];

test("browser model collection validates metadata and excludes locked/paid choices", () => {
  assert.equal(
    browserModelsSchema.safeParse([{ ...observed[0], name: "bad\nlabel" }]).success,
    false
  );
  assert.deepEqual(
    executableBrowserModels("qwen-browser", observed).map((model) => model.id),
    observed.slice(0, 2).map((model) => model.id)
  );
  assert.equal(resolveBrowserModel({ browserModels: observed }, "paid"), null);
  assert.equal(resolveBrowserModel({ browserModels: observed }, "invented"), null);
});

test("Qwen text-only transport never advertises vision it cannot accept", () => {
  const models = executableBrowserModels("qwen-browser", observed);
  assert.ok(models.every((model) => model.supportsVision === false));
  assert.ok(models.every((model) => JSON.stringify(model.inputModalities) === '["text"]'));
});

test("protocol providers expose verified routes and preserve declared vision", () => {
  const models = executableBrowserModels("zai-web", [
    { id: "GLM-5v-Turbo", name: "GLM-5V-Turbo", selectable: true, free: true },
    { id: "invented-glm", name: "Unknown", selectable: true, free: true },
  ]);
  assert.deepEqual(
    models.map((model) => model.id),
    ["GLM-5v-Turbo"]
  );
  assert.equal(models[0].supportsVision, true);
  assert.deepEqual(models[0].inputModalities, ["text", "image"]);
  assert.deepEqual(executableBrowserModels("unregistered-web", observed), []);
});

test("Qwen synced picker replaces stale default without injecting Cursor modes", () => {
  const models = mergeProviderModelListing({
    providerId: "qwen-browser",
    registryModels: [{ id: "qwen3.7-plus", name: "Qwen3.7-Plus" }],
    syncedModels: executableBrowserModels("qwen-browser", observed),
    customModels: [],
  });
  assert.deepEqual(
    models.map((model) => model.id),
    observed.slice(0, 2).map((model) => model.id)
  );
  assert.ok(models.every((model) => model.owned_by === "qwen-browser"));
});

test("Meta rejects an unknown model instead of silently selecting Fast", async () => {
  const result = await new MuseSparkWebExecutor().execute({
    model: "unknown-meta-model",
    body: { messages: [{ role: "user", content: "hi" }] },
    stream: false,
    credentials: {},
  });
  assert.equal(result.response.status, 400);
  assert.match(await result.response.text(), /Unsupported Meta AI Web model/);
});
