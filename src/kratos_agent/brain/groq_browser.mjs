import { createHash } from "node:crypto";
import { RegularBrowserConnection } from "./chatgpt_regular_browser.mjs";

export function parseGroqReply(body) {
  let text = "", finished = false;
  for (const line of body.split(/\r?\n/)) {
    if (line === "data: [DONE]") { finished = true; continue; }
    if (line.startsWith("0:")) { const part = JSON.parse(line.slice(2)); if (typeof part !== "string") throw new Error("Invalid Groq text"); text += part; }
    else if (line.startsWith("d:")) { const done = JSON.parse(line.slice(2)); if (done.finishReason === "stop") finished = true; }
    else if (line.startsWith("data:")) {
      const event = JSON.parse(line.slice(5).trim());
      if (event.type === "error" || event.error) throw new Error("Groq website returned an error");
      if (event.type === "text-delta" && typeof event.delta === "string") text += event.delta;
      if (event.type === "finish" && (!event.finishReason || event.finishReason === "stop")) finished = true;
      for (const choice of event.choices || []) {
        if (typeof choice.delta?.content === "string") text += choice.delta.content;
        if (choice.finish_reason === "stop") finished = true;
      }
    }
    else if (line.startsWith("3:")) throw new Error("Groq website returned an error");
  }
  if (!finished || !text.trim()) throw new Error("Groq website response is incomplete");
  return text;
}

export async function groqProviderMain(input) {
  const browser = new RegularBrowserConnection({ ...input.browser_connection, provider: "groq-web" });
  await browser.start();
  try {
    const snapshot = await browser.inspect(30000);
    const subjectFor = snapshot => {
      const token = snapshot.storage_state.cookies.find(c => c.name === "__session")?.value;
      let subject = "guest-" + (snapshot.cookie_store_id || "regular");
      if (token) {
        try { subject = JSON.parse(Buffer.from(token.split(".")[1], "base64url")).sub || token; }
        catch { subject = token; }
      }
      return createHash("sha256").update("groq-web:" + subject).digest("hex");
    };
    const subject = subjectFor(snapshot);
    if (input.subject && input.subject !== subject) return { error: "account_changed", status: 401 };
    const models = [{ id: "groq-web/browser-current", display_name: "Groq Chat — model selected on website",
      supports_vision: false, supports_tool_calling: false, local_tool_bridge: true, supports_reasoning: false,
      effort_tiers: [], access_verified: false, context_limits_available: false }];
    let text, conversation;
    if (input.mode === "complete") {
      if (input.payload.model !== models[0].id) return { error: "model_not_available_for_account", status: 400 };
      if (input.conversation) await browser.ownConversation(input.conversation);
      const prompt = input.payload.messages.map(m => `${m.role}: ${m.content}`).join("\n\n");
      const result = await browser.command("groq-turn", { prompt });
      text = parseGroqReply(result.body);
      conversation = await browser.conversationState();
    }
    const fresh = await browser.inspect();
    if (subjectFor(fresh) !== subject) return { error: "account_changed", status: 401 };
    return { subject, models, email: "", storage_state: fresh.storage_state,
      ...(text ? { text, conversation } : {}) };
  } finally { await browser.close(); }
}
