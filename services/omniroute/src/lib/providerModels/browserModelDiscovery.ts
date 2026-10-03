import { browserModelsSchema, type BrowserModel } from "@omniroute/open-sse/utils/browserModels.ts";
import { getModelsByProviderId } from "@/shared/constants/models";
import { persistDiscoveredModels } from "./modelDiscovery";

export const BROWSER_MODEL_PROVIDERS = new Set([
  "qwen-browser",
  "doubao-web",
  "kimi-web",
  "deepseek-web",
  "claude-web",
  "gemini-web",
  "grok-web",
  "perplexity-web",
  "zai-web",
  "muse-spark-web",
  "poe-web",
  "blackbox-web",
]);

/**
 * Publish only choices that the current executor can genuinely route. Unknown
 * protocol modes are collected as observations rather than advertised as chat.
 */
export function executableBrowserModels(providerId: string, value: unknown): BrowserModel[] {
  const parsed = browserModelsSchema.safeParse(value);
  if (!parsed.success) return [];
  const registryModels = new Map(
    (getModelsByProviderId(providerId) || []).map((model) => [model.id, model])
  );
  if (!BROWSER_MODEL_PROVIDERS.has(providerId)) return [];
  return Array.from(
    new Map(
      parsed.data
        .filter((model) => model.selectable && model.free !== false)
        .filter((model) => providerId === "qwen-browser" || registryModels.has(model.id))
        .map((model) => {
          const registry = registryModels.get(model.id);
          // Qwen's current transport validates text-only messages. A model's
          // upstream vision support is not usable through that transport yet.
          const supportsVision = providerId !== "qwen-browser" && registry?.supportsVision === true;
          return [
            model.id,
            {
              ...model,
              supportsVision,
              inputModalities: supportsVision ? ["text", "image"] : ["text"],
              supportsThinking: model.supportsThinking ?? registry?.supportsReasoning === true,
            } as BrowserModel,
          ] as const;
        })
    ).values()
  );
}

export async function persistBrowserDiscoveredModels(
  providerId: string,
  connectionId: string,
  observations: unknown
) {
  const models = executableBrowserModels(providerId, observations);
  return persistDiscoveredModels(
    providerId,
    connectionId,
    models.map((model) => ({
      ...model,
      supportsTools: false,
      supportedEndpoints: ["chat"],
    }))
  );
}
