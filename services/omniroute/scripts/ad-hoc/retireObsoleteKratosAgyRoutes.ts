import fs from "node:fs/promises";
import path from "node:path";

import { DATA_DIR, resetDbInstance } from "../../src/lib/db/core.ts";
import {
  getCustomModels,
  getModelCompatOverrides,
  removeCustomModel,
} from "../../src/lib/db/models.ts";

const provider = "agy";
const targets = new Set([
  "agy/gemini-3.7-flash-fast",
  "gemini-3.7-flash-fast",
  "agy/gemini-3.7-flash-high",
  "gemini-3.7-flash-high",
]);
const allowedFields = new Set(["id", "name", "source", "apiFormat", "supportedEndpoints"]);

try {
  const original = await getCustomModels(provider);
  const obsolete = original.filter((model) => targets.has(model.id));
  if (obsolete.some((model) => Object.keys(model).some((key) => !allowedFields.has(key)))) {
    throw new Error(
      "Obsolete route metadata changed; refusing to retire it without preserving its fields"
    );
  }
  const overrides = getModelCompatOverrides(provider).filter((model) => targets.has(model.id));
  if (overrides.length > 0) {
    throw new Error(
      "Obsolete routes now contain additional compatibility settings; refusing to remove them"
    );
  }
  const backupDirectory = path.join(DATA_DIR, "maintenance");
  await fs.mkdir(backupDirectory, { recursive: true });
  const backupPath = path.join(backupDirectory, `obsolete-agy-routes-${Date.now()}.json`);
  await fs.writeFile(backupPath, JSON.stringify({ provider, models: obsolete }, null, 2), {
    flag: "wx",
  });
  const removed = [];
  for (const model of obsolete) {
    if (await removeCustomModel(provider, model.id)) removed.push(model.id);
  }
  const remaining = await getCustomModels(provider);
  if (remaining.some((model) => targets.has(model.id))) {
    throw new Error("An obsolete route was not removed");
  }
  console.log(JSON.stringify({ removed, remaining: remaining.length, backup: backupPath }));
} finally {
  resetDbInstance();
}
