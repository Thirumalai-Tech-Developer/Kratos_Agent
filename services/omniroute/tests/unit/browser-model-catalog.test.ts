import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const directory = mkdtempSync(join(tmpdir(), "omniroute-browser-catalog-"));
process.env.DATA_DIR = directory;
const { resetDbInstance } = await import("../../src/lib/db/core.ts");
const { createProviderConnection, updateProviderConnection } =
  await import("../../src/lib/db/providers.ts");
const { persistBrowserDiscoveredModels } =
  await import("../../src/lib/providerModels/browserModelDiscovery.ts");
const catalog = await import("../../src/app/api/v1/models/catalog.ts");
const connectionModels = await import("../../src/app/api/providers/[id]/models/route.ts");
const { getCanonicalModelMetadata } = await import("../../src/lib/modelMetadataRegistry.ts");

test("web alias enrichment preserves the declared text-only transport", () => {
  for (const [provider, model] of [
    ["ds-web", "deepseek-v4-pro"],
    ["db", "dola-pro"],
  ]) {
    const metadata = getCanonicalModelMetadata({ provider, model });
    assert.ok(metadata);
    assert.deepEqual(metadata.modalities.input, ["text"]);
    assert.deepEqual(metadata.modalities.output, ["text"]);
    assert.equal(metadata.capabilities.vision, false);
  }
});

test("text-only web transports advertise text and preserve explicit vision false", async () => {
  for (const provider of ["deepseek-web", "doubao-web"]) {
    await createProviderConnection({
      provider,
      authType: "apikey",
      name: "Text fixture",
      apiKey: "fixture-token",
      isActive: true,
    });
  }
  catalog.__resetCatalogBuilderRunsForTest();
  const response = await catalog.getUnifiedModelsResponse(
    new Request("http://localhost/api/v1/models?prefix=canonical")
  );
  const body = (await response.json()) as {
    data: Array<{ id: string; input_modalities?: string[]; capabilities?: { vision?: boolean } }>;
  };
  for (const id of ["deepseek-web/deepseek-v4-pro", "doubao-web/dola-pro"]) {
    const model = body.data.find((entry) => entry.id === id);
    assert.ok(model, id);
    assert.deepEqual(model.input_modalities, ["text"]);
    assert.equal(model.capabilities?.vision, false);
  }
});

test.after(() => {
  resetDbInstance();
  rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
});

test("browser-discovered Qwen models reach gateway and per-connection catalogs", async () => {
  const connection = await createProviderConnection({
    provider: "qwen-browser",
    authType: "apikey",
    name: "Browser fixture",
    apiKey: "fixture-token",
    isActive: true,
    testStatus: "active",
  });
  const observations = [
    { id: "qwen-ui-fixture-max", name: "Qwen Fixture Max", selectable: true, free: true },
    { id: "qwen-ui-fixture-flash", name: "Qwen Fixture Flash", selectable: true, free: true },
    { id: "qwen-ui-fixture-paid", name: "Qwen Fixture Paid", selectable: true, free: false },
  ];
  await persistBrowserDiscoveredModels("qwen-browser", connection.id, observations);
  const detail = await connectionModels.GET(
    new Request(`http://localhost/api/providers/${connection.id}/models`),
    { params: { id: connection.id } }
  );
  assert.equal(detail.status, 200);
  assert.deepEqual(
    (await detail.json()).models.map((model: { id: string }) => model.id),
    observations.slice(0, 2).map((model) => model.id)
  );

  catalog.__resetCatalogBuilderRunsForTest();
  const response = await catalog.getUnifiedModelsResponse(
    new Request("http://localhost/api/v1/models?prefix=canonical")
  );
  assert.equal(response.status, 200);
  const body = (await response.json()) as {
    data: Array<{ id: string; capabilities?: { vision?: boolean } }>;
  };
  const rows = body.data.filter((model) => model.id.startsWith("qwen-browser/"));
  assert.deepEqual(
    rows.map((model) => model.id).sort(),
    observations
      .slice(0, 2)
      .map((model) => `qwen-browser/${model.id}`)
      .sort()
  );
  assert.ok(rows.every((model) => model.capabilities?.vision !== true));

  await updateProviderConnection(connection.id, { providerSpecificData: { browserModels: [] } });
  await persistBrowserDiscoveredModels("qwen-browser", connection.id, []);
  const emptyDetail = await connectionModels.GET(
    new Request(`http://localhost/api/providers/${connection.id}/models`),
    { params: { id: connection.id } }
  );
  assert.deepEqual((await emptyDetail.json()).models, []);
  catalog.__resetCatalogBuilderRunsForTest();
  const emptyResponse = await catalog.getUnifiedModelsResponse(
    new Request("http://localhost/api/v1/models?prefix=canonical")
  );
  const emptyBody = (await emptyResponse.json()) as { data: Array<{ id: string }> };
  assert.equal(
    emptyBody.data.some((model) => model.id.startsWith("qwen-browser/")),
    false
  );
});

test("Observed Z.ai picker replaces old catalog and exposes verified vision", async () => {
  const observations = [
    { id: "x-preview-l", name: "GLM-5.3-Flash", selectable: true, supportsVision: true },
    { id: "glm-5.3", name: "GLM-5.3", selectable: true, supportsVision: false },
    { id: "glm-5.2", name: "GLM-5.2", selectable: true },
    { id: "GLM-5v-Turbo", name: "GLM-5V-Turbo", selectable: false },
  ];
  const connection = await createProviderConnection({
    provider: "zai-web",
    name: "Zai browser fixture",
    authType: "apikey",
    apiKey: "fixture-token",
    isActive: true,
    providerSpecificData: { browserModels: observations },
  });
  assert.ok(connection && typeof connection.id === "string");
  await persistBrowserDiscoveredModels("zai-web", connection.id, observations);
  const detail = await connectionModels.GET(
    new Request(`http://localhost/api/providers/${connection.id}/models`),
    { params: { id: connection.id } }
  );
  assert.deepEqual((await detail.json()).models.map((model: { id: string }) => model.id).sort(), [
    "glm-5.2",
    "glm-5.3",
    "x-preview-l",
  ]);
  catalog.__resetCatalogBuilderRunsForTest();
  const response = await catalog.getUnifiedModelsResponse(
    new Request("http://localhost/api/v1/models?prefix=canonical")
  );
  const rows = (await response.json()).data.filter((model: { id: string }) =>
    model.id.startsWith("zai-web/")
  );
  assert.deepEqual(rows.map((model: { id: string }) => model.id).sort(), [
    "zai-web/glm-5.2",
    "zai-web/glm-5.3",
    "zai-web/x-preview-l",
  ]);
  assert.equal(
    rows.find((model: { id: string }) => model.id.endsWith("/x-preview-l")).capabilities.vision,
    true
  );
});
