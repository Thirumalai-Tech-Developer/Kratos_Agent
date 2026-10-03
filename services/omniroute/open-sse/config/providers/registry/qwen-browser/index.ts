import type { RegistryEntry } from "../../shared.ts";

export const qwen_browserProvider: RegistryEntry = {
  id: "qwen-browser",
  alias: "qwb",
  format: "openai",
  executor: "qwen-browser",
  baseUrl: "https://chat.qwen.ai",
  authType: "apikey",
  authHeader: "bearer",
  models: [
    {
      id: "qwen3.7-plus",
      name: "Qwen3.7-Plus",
      toolCalling: false,
      supportsVision: false,
      supportsReasoning: true,
    },
  ],
};
