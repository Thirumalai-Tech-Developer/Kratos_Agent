// Gemini Web video generation handler (Veo via gemini.google.com/u/0/videos).
// Family: gemini-web-video | Provider: gemini-web | Alias: gweb

import { GeminiWebExecutor, resolveVideoOrientation, type VideoOrientation } from "../../executors/gemini-web.ts";
import { saveCallLog } from "@/lib/usageDb";
import { sanitizeErrorMessage } from "../../utils/error.ts";

export async function handleGeminiWebVideoGeneration({
  model,
  provider,
  providerConfig,
  body,
  credentials,
  log,
  signal,
  executorFactory = () => new GeminiWebExecutor(),
}: {
  model: string;
  provider: string;
  providerConfig?: { baseUrl?: string };
  body: Record<string, unknown>;
  credentials?: Record<string, unknown> | null;
  log?: { info?: (...args: unknown[]) => void; error?: (...args: unknown[]) => void } | null;
  signal?: AbortSignal | null;
  executorFactory?: () => {
    executeVideoGeneration: (args: {
      prompt: string;
      model?: string;
      orientation?: VideoOrientation | null;
      aspectRatio?: string;
      duration?: number;
      responseFormat?: "url" | "b64_json";
      timeoutMs?: number;
      credentials?: Record<string, unknown> | null;
      signal?: AbortSignal | null;
      log?: unknown;
      videoUrl?: string;
    }) => Promise<{
      success: boolean;
      status: number;
      data?: Array<{ url?: string; b64_json?: string; format: string }>;
      error?: string;
    }>;
  };
}) {
  const startTime = Date.now();
  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) {
    return {
      success: false,
      status: 400,
      error: "Prompt is required for Gemini Web video generation",
    };
  }

  const cookie =
    typeof credentials?.apiKey === "string"
      ? credentials.apiKey
      : typeof (credentials as Record<string, unknown> | undefined)?.cookie === "string"
        ? ((credentials as Record<string, unknown>).cookie as string)
        : "";

  if (!cookie) {
    return {
      success: false,
      status: 401,
      error: "Gemini Web credentials missing session cookie (__Secure-1PSID)",
    };
  }

  try {
    const executor = executorFactory();
    const videoUrl = providerConfig?.baseUrl || "https://gemini.google.com/u/0/videos";
    
    // Resolve landscape and portrait control
    const orientation = resolveVideoOrientation(body, model);
    const aspectRatio =
      typeof body.aspect_ratio === "string"
        ? body.aspect_ratio
        : typeof body.aspectRatio === "string"
          ? body.aspectRatio
          : typeof body.size === "string"
            ? body.size
            : orientation === "portrait"
              ? "9:16"
              : orientation === "landscape"
                ? "16:9"
                : undefined;

    const duration =
      typeof body.duration === "number"
        ? body.duration
        : typeof body.durationSeconds === "number"
          ? body.durationSeconds
          : undefined;

    const responseFormat = body.response_format === "b64_json" ? "b64_json" : "url";
    const timeoutMs =
      typeof body.timeout_ms === "number"
        ? body.timeout_ms
        : typeof body.timeoutMs === "number"
          ? body.timeoutMs
          : 240_000;

    log?.info?.(
      "VIDEO",
      `${provider}/${model} (gemini-web) | prompt: "${prompt.slice(0, 60)}${prompt.length > 60 ? "..." : ""}" | orientation: ${orientation ?? "default"} | url: ${videoUrl}`
    );

    const result = await executor.executeVideoGeneration({
      prompt,
      model,
      orientation,
      aspectRatio,
      duration,
      responseFormat,
      timeoutMs,
      credentials,
      signal,
      log,
      videoUrl,
    });

    if (!result.success) {
      saveCallLog({
        method: "POST",
        path: "/v1/videos/generations",
        status: result.status || 500,
        model: `${provider}/${model}`,
        provider,
        duration: Date.now() - startTime,
        error: (result.error || "Unknown error").slice(0, 500),
      }).catch(() => {});
      return {
        success: false,
        status: result.status || 500,
        error: result.error || "Gemini Web video generation failed",
      };
    }

    saveCallLog({
      method: "POST",
      path: "/v1/videos/generations",
      status: 200,
      model: `${provider}/${model}`,
      provider,
      duration: Date.now() - startTime,
    }).catch(() => {});

    return {
      success: true,
      data: {
        created: Math.floor(Date.now() / 1000),
        data: result.data || [],
      },
    };
  } catch (err) {
    const errorText = sanitizeErrorMessage(err instanceof Error ? err.message : String(err));
    log?.error?.("VIDEO", `${provider} gemini-web video generation exception: ${errorText}`);
    saveCallLog({
      method: "POST",
      path: "/v1/videos/generations",
      status: 500,
      model: `${provider}/${model}`,
      provider,
      duration: Date.now() - startTime,
      error: errorText.slice(0, 500),
    }).catch(() => {});
    return { success: false, status: 500, error: errorText };
  }
}
