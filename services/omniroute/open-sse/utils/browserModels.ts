import { z } from "zod";

/** First-party picker observations. IDs may be explicitly named UI aliases. */
export const browserModelSchema = z.object({
  id: z
    .string()
    .trim()
    .min(1)
    .max(200)
    .regex(/^[a-zA-Z0-9_.:-]+$/),
  name: z
    .string()
    .trim()
    .min(1)
    .max(120)
    .refine((value) => !/[\r\n]/.test(value)),
  selectable: z.boolean(),
  free: z.boolean().optional(),
  supportsThinking: z.boolean().optional(),
  supportsVision: z.boolean().optional(),
  inputModalities: z
    .array(z.enum(["text", "image"]))
    .max(2)
    .optional(),
});

export const browserModelsSchema = z.array(browserModelSchema).max(200);
export type BrowserModel = z.infer<typeof browserModelSchema>;

/** An observed empty or malformed picker is not permission to use an old default. */
export function hasBrowserModelCatalog(providerSpecificData: unknown): boolean {
  return (
    !!providerSpecificData &&
    typeof providerSpecificData === "object" &&
    Object.prototype.hasOwnProperty.call(providerSpecificData, "browserModels")
  );
}

export function readBrowserModels(providerSpecificData: unknown): BrowserModel[] {
  if (!providerSpecificData || typeof providerSpecificData !== "object") return [];
  const value = (providerSpecificData as Record<string, unknown>).browserModels;
  const parsed = browserModelsSchema.safeParse(value);
  if (!parsed.success) return [];
  return Array.from(new Map(parsed.data.map((model) => [model.id, model])).values());
}

/** Paid/disabled choices remain in observations but never become runnable routes. */
export function resolveBrowserModel(
  providerSpecificData: unknown,
  modelId: string
): BrowserModel | null {
  return (
    readBrowserModels(providerSpecificData).find(
      (model) => model.id === modelId && model.selectable && model.free !== false
    ) || null
  );
}
