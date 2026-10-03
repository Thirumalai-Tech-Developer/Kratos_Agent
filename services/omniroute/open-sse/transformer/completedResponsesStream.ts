/** Preserve the requested SSE contract when a server tool requires assembled JSON. */
import { z } from "zod";
import { errorResponse } from "../utils/error.ts";

const responseSchema = z.object({
  id: z.string(),
  object: z.literal("response"),
  status: z.string().optional(),
  output: z.array(z.record(z.string(), z.unknown())),
}).passthrough();

export async function ensureResponsesSse(response: Response): Promise<Response> {
  if (!response.ok || response.headers.get("content-type")?.includes("text/event-stream")) return response;
  let parsed: z.infer<typeof responseSchema>;
  try {
    parsed = responseSchema.parse(await response.json());
  } catch {
    return errorResponse(502, "Gateway returned an invalid assembled Responses result.");
  }
  let sequence = 0;
  function* events(): Generator<Record<string, unknown>> {
    const initial = { ...parsed, status: "in_progress", output: [] };
    yield { type: "response.created", response: initial };
    yield { type: "response.in_progress", response: initial };
    for (const [output_index, item] of parsed.output.entries()) {
      yield { type: "response.output_item.added", output_index, item: { ...item, status: "in_progress", ...(item.type === "message" ? { content: [] } : {}) } };
      if (item.type === "web_search_call") {
        yield { type: "response.web_search_call.in_progress", output_index, item_id: item.id };
        yield { type: "response.web_search_call.searching", output_index, item_id: item.id };
        yield { type: "response.web_search_call.completed", output_index, item_id: item.id };
      }
      if (item.type === "message" && Array.isArray(item.content)) {
        for (const [content_index, value] of item.content.entries()) {
          if (!value || typeof value !== "object") continue;
          const part = value as Record<string, unknown>;
          yield { type: "response.content_part.added", output_index, content_index, item_id: item.id, part: { ...part, ...(part.type === "output_text" ? { text: "" } : {}) } };
          if (part.type === "output_text" && typeof part.text === "string") {
            for (let offset = 0; offset < part.text.length; offset += 1024) {
              yield { type: "response.output_text.delta", output_index, content_index, item_id: item.id, delta: part.text.slice(offset, offset + 1024) };
            }
            yield { type: "response.output_text.done", output_index, content_index, item_id: item.id, text: part.text };
          }
          yield { type: "response.content_part.done", output_index, content_index, item_id: item.id, part };
        }
      }
      yield { type: "response.output_item.done", output_index, item };
    }
    const terminal = parsed.status === "failed" ? "failed" : parsed.status === "incomplete" ? "incomplete" : "completed";
    yield { type: `response.${terminal}`, response: { ...parsed, status: terminal } };
  }
  const iterator = events();
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      const next = iterator.next();
      if (next.done) { controller.close(); return; }
      const event = { ...next.value, sequence_number: sequence++ };
      controller.enqueue(encoder.encode(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`));
    },
    cancel() { iterator.return(undefined); },
  });
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("content-type", "text/event-stream; charset=utf-8");
  headers.set("cache-control", "no-cache, no-transform");
  return new Response(stream, { status: response.status, headers });
}
