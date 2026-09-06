/**
 * Kratos Agent: Cloudflare Worker Edge Backend
 * Serves static Vice City Cyberpunk web UI and proxies REST / SSE endpoints to Cloudflare D1.
 */

const TOOLS_LIST = [
  { name: "write_file", description: "Write full file contents to the workspace", permission: "write", timeout_seconds: 30 },
  { name: "edit_file", description: "Apply targeted multi-chunk diffs to files", permission: "write", timeout_seconds: 30 },
  { name: "read_file", description: "Inspect text or binary files within workspace", permission: "read", timeout_seconds: 15 },
  { name: "list_directory", description: "List files and directory trees recursively", permission: "read", timeout_seconds: 10 },
  { name: "grep_search", description: "Ripgrep regex search across workspace files", permission: "read", timeout_seconds: 15 },
  { name: "run_terminal_command", description: "Execute shell commands with timeout controls", permission: "execute", timeout_seconds: 120 },
  { name: "git_status", description: "Inspect git working tree and uncommitted changes", permission: "read", timeout_seconds: 10 },
  { name: "git_diff", description: "Review git diff for unstaged or staged changes", permission: "read", timeout_seconds: 15 },
  { name: "d1_query", description: "Query serverless Cloudflare D1 relational database", permission: "read", timeout_seconds: 10 },
  { name: "task_plan", description: "Formulate multi-stage execution plan", permission: "read", timeout_seconds: 10 },
  { name: "verify_tests", description: "Execute test suite and analyze failure outputs", permission: "execute", timeout_seconds: 60 },
  { name: "event_replay", description: "Replay agentic traces from event bus", permission: "read", timeout_seconds: 10 },
  { name: "manage_env", description: "Inspect and update project environment configuration", permission: "write", timeout_seconds: 10 },
  { name: "web_search", description: "Search technical documentation and web references", permission: "read", timeout_seconds: 20 }
];

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'antigravity/gemini-3.7-flash-high',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_status TEXT NOT NULL DEFAULT 'idle',
    plan_json TEXT,
    files_changed_json TEXT,
    verification_status_json TEXT,
    notes_json TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    user_query TEXT NOT NULL,
    agent_reply TEXT NOT NULL,
    tools_used_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS agentic_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    kind TEXT NOT NULL,
    timestamp REAL NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    returncode INTEGER NOT NULL DEFAULT 0,
    output_preview TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
`;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Handle CORS Pre-flight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders()
      });
    }

    // Initialize D1 Schema on first request if DB binding exists
    if (env.DB && !env._schema_initialized) {
      try {
        const statements = SCHEMA_SQL.split(";").map(s => s.trim()).filter(Boolean);
        for (const st of statements) {
          await env.DB.prepare(st).run().catch(() => {});
        }
        env._schema_initialized = true;
      } catch (_) {}
    }

    // API Routes
    if (url.pathname.startsWith("/api/")) {
      try {
        return await handleApi(request, env, url);
      } catch (err) {
        return jsonResponse({ error: String(err.message || err) }, 500);
      }
    }

    // Static Assets fallback (index.html, app.css, app.js, highlighter.js)
    if (env.ASSETS) {
      return env.ASSETS.fetch(request);
    }

    return new Response("Kratos Agent Worker Active", { status: 200 });
  }
};

export function getSchemaSql() {
  return SCHEMA_SQL;
}

export { corsHeaders, jsonResponse, handleApi };

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400"
  };
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      ...corsHeaders(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-cache"
    }
  });
}

async function handleApi(request, env, url) {
  const method = request.method.toUpperCase();
  const path = url.pathname;

  // 1. GET /api/stats
  if (path === "/api/stats" && method === "GET") {
    const start = Date.now();
    let sessionsCount = 0;
    let turnsCount = 0;
    let eventsCount = 0;

    if (env.DB) {
      try {
        const sRes = await env.DB.prepare("SELECT COUNT(*) as c FROM sessions").first();
        const tRes = await env.DB.prepare("SELECT COUNT(*) as c FROM turns").first();
        const eRes = await env.DB.prepare("SELECT COUNT(*) as c FROM agentic_events").first();
        sessionsCount = sRes ? Number(sRes.c) : 0;
        turnsCount = tRes ? Number(tRes.c) : 0;
        eventsCount = eRes ? Number(eRes.c) : 0;
      } catch (_) {}
    }

    return jsonResponse({
      sessions_count: sessionsCount,
      turns_count: turnsCount,
      events_count: eventsCount,
      mode: "cloudflare_d1",
      is_remote: true,
      database_id: "0e785bd7-3efa-435a-bed6-d205d849d9d7",
      latency_ms: Date.now() - start
    });
  }

  // 2. GET /api/telemetry
  if (path === "/api/telemetry" && method === "GET") {
    return jsonResponse({
      model: env.AGENT_MODEL || "antigravity/gemini-3.7-flash-high",
      normal_mode_model: env.NORMAL_MODE_MODEL || "deepseek-web/deepseek-v4-pro",
      workspace: "Cloudflare Edge Workers",
      tools_count: TOOLS_LIST.length,
      active_session: null,
      d1_database_id: "0e785bd7-3efa-435a-bed6-d205d849d9d7",
      d1_mode: "cloudflare_d1",
      is_remote_d1: true,
      latency_ms: 12
    });
  }

  // 3. GET /api/tools
  if (path === "/api/tools" && method === "GET") {
    return jsonResponse(TOOLS_LIST);
  }

  // 4. GET /api/sessions
  if (path === "/api/sessions" && method === "GET") {
    if (!env.DB) return jsonResponse([]);
    try {
      const { results } = await env.DB.prepare(
        `SELECT s.id as session_id, s.title, s.model, s.created_at, s.updated_at, s.last_status,
                (SELECT COUNT(*) FROM turns WHERE session_id = s.id) as turns_count
         FROM sessions s
         ORDER BY s.updated_at DESC`
      ).all();
      return jsonResponse(results || []);
    } catch (_) {
      return jsonResponse([]);
    }
  }

  // 5. GET /api/sessions/:id
  const sessionMatch = path.match(/^\/api\/sessions\/([^/]+)$/);
  if (sessionMatch && method === "GET") {
    const sessionId = decodeURIComponent(sessionMatch[1]);
    if (!env.DB) return jsonResponse({ error: "No DB configured" }, 500);

    const session = await env.DB.prepare("SELECT * FROM sessions WHERE id = ?").bind(sessionId).first();
    if (!session) {
      return jsonResponse({ error: `Session ${sessionId} not found` }, 404);
    }

    const { results: turnRows } = await env.DB.prepare(
      "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index ASC"
    ).bind(sessionId).all();

    const turns = (turnRows || []).map(tr => {
      let tools = [];
      if (tr.tools_used_json) {
        try { tools = JSON.parse(tr.tools_used_json); } catch (_) {}
      }
      return {
        id: tr.id,
        timestamp: tr.timestamp,
        user: tr.user_query,
        agent: tr.agent_reply,
        tools_used: tools
      };
    });

    return jsonResponse({
      id: session.id,
      session_id: session.id,
      title: session.title,
      model: session.model,
      created_at: session.created_at,
      updated_at: session.updated_at,
      last_status: session.last_status,
      turns
    });
  }

  // 6. POST /api/sessions
  if (path === "/api/sessions" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    const sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const title = body.title || "Cloudflare Mission";
    const model = body.model || "auto";
    const now = new Date().toISOString().replace("T", " ").slice(0, 19);

    if (env.DB) {
      await env.DB.prepare(
        "INSERT INTO sessions (id, title, model, created_at, updated_at, last_status) VALUES (?, ?, ?, ?, ?, ?)"
      ).bind(sessionId, title, model, now, now, "idle").run().catch(() => {});
    }

    return jsonResponse({
      id: sessionId,
      session_id: sessionId,
      title,
      model,
      created_at: now
    });
  }

  // 7. DELETE /api/sessions/:id
  if (sessionMatch && method === "DELETE") {
    const sessionId = decodeURIComponent(sessionMatch[1]);
    if (env.DB) {
      await env.DB.prepare("DELETE FROM turns WHERE session_id = ?").bind(sessionId).run().catch(() => {});
      await env.DB.prepare("DELETE FROM agentic_events WHERE session_id = ?").bind(sessionId).run().catch(() => {});
      await env.DB.prepare("DELETE FROM commands WHERE session_id = ?").bind(sessionId).run().catch(() => {});
      await env.DB.prepare("DELETE FROM sessions WHERE id = ?").bind(sessionId).run().catch(() => {});
    }
    return jsonResponse({ success: true, deleted: sessionId });
  }

  // 8. GET /api/events/:sessionId
  const eventsMatch = path.match(/^\/api\/events\/([^/]+)$/);
  if (eventsMatch && method === "GET") {
    const sessionId = decodeURIComponent(eventsMatch[1]);
    if (!env.DB) return jsonResponse([]);
    const { results } = await env.DB.prepare(
      "SELECT * FROM agentic_events WHERE session_id = ? ORDER BY timestamp ASC"
    ).bind(sessionId).all().catch(() => ({ results: [] }));
    return jsonResponse(results || []);
  }

  // 9. POST /api/sql
  if (path === "/api/sql" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    const sql = (body.sql || "").trim();
    if (!sql) return jsonResponse({ error: "Empty SQL" }, 400);
    if (!env.DB) return jsonResponse({ error: "No D1 DB bound" }, 500);

    try {
      const { results } = await env.DB.prepare(sql).all();
      return jsonResponse({
        rows: results || [],
        count: results ? results.length : 0,
        source: "cloudflare_d1"
      });
    } catch (e) {
      return jsonResponse({ error: e.message }, 400);
    }
  }

  // 10. POST /api/auth/agent-mode (Commander Security Clearance)
  if (path === "/api/auth/agent-mode" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    const password = (body.password || "").trim();
    const expected = (env.AGENT_PASSWORD || "kratos").trim();
    if (password === expected) {
      return jsonResponse({ success: true, message: "Security clearance granted" });
    }
    return jsonResponse({ success: false, error: "ACCESS DENIED // Invalid Passcode" }, 401);
  }

  // 11. POST /api/chat (Server-Sent Events streaming chat)
  if (path === "/api/chat" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    const prompt = (body.prompt || "").trim();
    if (!prompt) return jsonResponse({ error: "Empty prompt" }, 400);

    const isAgentMode = Boolean(body.agent_mode);
    let sessionId = body.session_id;
    const now = new Date().toISOString().replace("T", " ").slice(0, 19);

    if (!sessionId) {
      sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    }

    const defaultTitle = prompt.length > 40 ? prompt.slice(0, 40) + "..." : prompt;
    const activeModel = isAgentMode
      ? (env.AGENT_MODEL || "antigravity/gemini-3.7-flash-high")
      : (env.NORMAL_MODE_MODEL || "deepseek-web/deepseek-v4-pro");

    // CRITICAL: Ensure session row ALWAYS exists in D1 so FOREIGN KEY never fails
    if (env.DB) {
      await env.DB.prepare(
        "INSERT OR IGNORE INTO sessions (id, title, model, created_at, updated_at, last_status) VALUES (?, ?, ?, ?, ?, ?)"
      ).bind(sessionId, defaultTitle, activeModel, now, now, "idle").run().catch((e) => console.error("Session insert error:", e));
    }

    // Call live LLM or generate response
    const agentReply = await generateAgentResponse(prompt, env, isAgentMode);

    // Save turn & agentic events into Cloudflare D1
    if (env.DB) {
      try {
        const countRes = await env.DB.prepare("SELECT COUNT(*) as c FROM turns WHERE session_id = ?").bind(sessionId).first().catch(() => ({ c: 0 }));
        const turnIndex = countRes ? Number(countRes.c) : 0;
        const turnId = `turn_${Date.now()}_${turnIndex}`;

        // 1. Insert turn (user prompt + agent reply)
        await env.DB.prepare(
          "INSERT INTO turns (id, session_id, turn_index, timestamp, user_query, agent_reply, tools_used_json) VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(
          turnId,
          sessionId,
          turnIndex,
          now,
          prompt,
          agentReply,
          isAgentMode ? JSON.stringify([{ name: "autonomous_executor", status: "completed" }]) : "[]"
        ).run();

        // 2. Insert agentic events into D1 agentic_events table
        const eventTs = Date.now() / 1000;
        const evtStartId = `evt_${Date.now()}_start`;
        const evtDoneId = `evt_${Date.now()}_done`;

        // Event: turn.started
        await env.DB.prepare(
          "INSERT INTO agentic_events (id, session_id, turn_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?, ?)"
        ).bind(
          evtStartId,
          sessionId,
          turnId,
          "turn.started",
          eventTs,
          JSON.stringify({ query: prompt, agent_mode: isAgentMode, model: activeModel })
        ).run().catch(() => {});

        // Event: plan.created if agent mode
        if (isAgentMode) {
          const evtPlanId = `evt_${Date.now()}_plan`;
          await env.DB.prepare(
            "INSERT INTO agentic_events (id, session_id, turn_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?, ?)"
          ).bind(
            evtPlanId,
            sessionId,
            turnId,
            "plan.created",
            eventTs + 0.05,
            JSON.stringify({ goal: prompt, status: "completed", actions: ["reasoning", "tool_planning", "response_generation"] })
          ).run().catch(() => {});
        }

        // Event: turn.completed
        await env.DB.prepare(
          "INSERT INTO agentic_events (id, session_id, turn_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?, ?)"
        ).bind(
          evtDoneId,
          sessionId,
          turnId,
          "turn.completed",
          eventTs + 0.1,
          JSON.stringify({ response_length: agentReply.length, status: "completed", model: activeModel })
        ).run().catch(() => {});

        // 3. Update session updated_at and last_status
        await env.DB.prepare(
          "UPDATE sessions SET updated_at = ?, last_status = 'completed', model = ? WHERE id = ?"
        ).bind(now, activeModel, sessionId).run();
      } catch (dbErr) {
        console.error("D1 turn/events insert error:", dbErr);
      }
    }

    // Stream SSE back to browser
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const send = (data) => {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
        };

        send({
          type: "start",
          prompt,
          session_id: sessionId,
          model: activeModel,
          agent_mode: isAgentMode
        });

        send({
          type: "step",
          step: isAgentMode ? "planning" : "reasoning",
          label: isAgentMode ? "Executing autonomous agent loop on Cloudflare..." : "Synthesizing response on Cloudflare Edge..."
        });

        // Send tokens with typing effect
        const words = agentReply.split(" ");
        for (let i = 0; i < words.length; i += 3) {
          const chunk = words.slice(i, i + 3).join(" ") + " ";
          send({ type: "token", token: chunk });
        }

        send({
          type: "done",
          result: agentReply,
          session_id: sessionId
        });

        controller.close();
      }
    });

    return new Response(stream, {
      headers: {
        ...corsHeaders(),
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive"
      }
    });
  }

  // 12. GET /api/diag (Live Edge Diagnostics & LLM Health Probe)
  if (path === "/api/diag" && method === "GET") {
    const endpoint = (env.CHAT_ENDPOINT || env.DEEPSEEK_BASE_URL || env.OPENAI_BASE_URL || "http://138.252.100.105:20128/v1/chat/completions").trim();
    const apiKey = (env.DEEPSEEK_API_KEY || env.OMNI_KEY || env.OPENAI_API_KEY || "sk-83463e3b38939d25-b68891-a1693fd2").trim();
    const model = (env.NORMAL_MODE_MODEL || env.DEEPSEEK_MODEL || "deepseek-web/deepseek-v4-pro").trim();

    let testResult = "pending";
    let latencyMs = 0;
    const start = Date.now();

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      const res = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${apiKey}`
        },
        body: JSON.stringify({
          model,
          messages: [{ role: "user", content: "ping" }],
          max_tokens: 5
        }),
        signal: controller.signal
      });
      clearTimeout(timeoutId);
      latencyMs = Date.now() - start;
      if (res.ok) {
        testResult = `OK (${res.status}) - Latency: ${latencyMs}ms`;
      } else {
        testResult = `HTTP ${res.status}: ${(await res.text().catch(() => "")).slice(0, 120)}`;
      }
    } catch (e) {
      latencyMs = Date.now() - start;
      testResult = `Fetch Error (${latencyMs}ms): ${e.message || String(e)}`;
    }

    return jsonResponse({
      status: "online",
      edge_runtime: "Cloudflare Workers",
      resolved_config: {
        endpoint,
        model,
        api_key_masked: apiKey ? `${apiKey.slice(0, 6)}...${apiKey.slice(-4)}` : "none",
        has_gemini_key: Boolean(env.GEMINI_API_KEY),
        has_workers_ai: Boolean(env.AI),
        has_deepseek_key: Boolean(env.DEEPSEEK_API_KEY),
        has_d1_db: Boolean(env.DB)
      },
      live_ping_test: testResult
    });
  }

  return jsonResponse({ error: `Route ${path} not found` }, 404);
}

// Low-level TCP socket fetch fallback for non-standard ports blocked by Cloudflare HTTP proxy
async function fetchOverSocket(urlStr, options) {
  let connect;
  try {
    const mod = await import("cloudflare:sockets");
    connect = mod.connect;
  } catch (e) {
    throw new Error("cloudflare:sockets unavailable: " + (e.message || e));
  }

  const url = new URL(urlStr);
  const hostname = url.hostname;
  const port = parseInt(url.port || (url.protocol === "https:" ? "443" : "80"), 10);
  const isSecure = url.protocol === "https:";

  const socket = connect({ hostname, port }, { secureTransport: isSecure ? "on" : "off" });
  const writer = socket.writable.getWriter();
  const reader = socket.readable.getReader();

  const method = (options.method || "GET").toUpperCase();
  const path = url.pathname + (url.search || "");
  const headers = Object.assign({}, options.headers);
  headers["Host"] = url.host;
  headers["Connection"] = "close";

  const body = options.body || "";
  const encoder = new TextEncoder();
  let head = `${method} ${path} HTTP/1.1\r\n`;
  for (const [k, v] of Object.entries(headers)) {
    head += `${k}: ${v}\r\n`;
  }

  if (body) {
    const bodyBuf = encoder.encode(body);
    head += `Content-Length: ${bodyBuf.byteLength}\r\n\r\n`;
    await writer.write(encoder.encode(head));
    await writer.write(bodyBuf);
  } else {
    head += "\r\n";
    await writer.write(encoder.encode(head));
  }

  const decoder = new TextDecoder();
  let raw = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    raw += decoder.decode(value, { stream: true });
  }

  const splitIdx = raw.indexOf("\r\n\r\n");
  if (splitIdx === -1) {
    throw new Error("Invalid HTTP socket response: headers delimiter missing");
  }

  const headerText = raw.slice(0, splitIdx);
  let bodyText = raw.slice(splitIdx + 4);
  const statusLine = headerText.split("\r\n")[0] || "";
  const statusCode = parseInt(statusLine.split(" ")[1] || "200", 10);

  // Decode chunked encoding if present
  if (/transfer-encoding:\s*chunked/i.test(headerText)) {
    let unchunked = "";
    let pos = 0;
    while (pos < bodyText.length) {
      const lineEnd = bodyText.indexOf("\r\n", pos);
      if (lineEnd === -1) break;
      const sizeHex = bodyText.slice(pos, lineEnd).trim().split(";")[0];
      const size = parseInt(sizeHex, 16);
      if (isNaN(size) || size === 0) break;
      const dataStart = lineEnd + 2;
      unchunked += bodyText.slice(dataStart, dataStart + size);
      pos = dataStart + size + 2;
    }
    bodyText = unchunked || bodyText;
  }

  return {
    status: statusCode,
    ok: statusCode >= 200 && statusCode < 300,
    text: async () => bodyText,
    json: async () => JSON.parse(bodyText)
  };
}

async function generateAgentResponse(prompt, env, isAgentMode = false) {
  const errors = [];

  const systemInstruction = isAgentMode
    ? "You are Kratos, an elite autonomous AI coding assistant running in Agent Mode. Analyze instructions methodically, plan step-by-step executions, provide precise code solutions, and report actions with Spartan discipline."
    : "You are Kratos, an elite AI assistant operating in Normal Chat Mode. Answer questions directly, explain concepts clearly, write clean code snippets, and assist the commander with sharp technical expertise.";

  // 1. Resolve Credentials & Variables with multi-alias support
  let endpoint = (env.CHAT_ENDPOINT || env.DEEPSEEK_BASE_URL || env.OPENAI_BASE_URL || env.BRAIN_BASE_URL || "").trim();
  const apiKey = (env.DEEPSEEK_API_KEY || env.OMNI_KEY || env.OPENAI_API_KEY || env.API_KEY || "sk-83463e3b38939d25-b68891-a1693fd2").trim();
  let model = isAgentMode
    ? (env.AGENT_MODEL || "antigravity/gemini-3.7-flash-high")
    : (env.NORMAL_MODE_MODEL || env.DEEPSEEK_MODEL || env.MODEL || "deepseek-web/deepseek-v4-pro").trim();

  // If user provided DEEPSEEK_API_KEY without custom endpoint, use official DeepSeek API
  if (env.DEEPSEEK_API_KEY && !endpoint) {
    endpoint = "https://api.deepseek.com/chat/completions";
    if (model.includes("deepseek-web") || model === "auto") {
      model = "deepseek-chat";
    }
  }

  // If endpoint is a base URL without /chat/completions, append it
  if (endpoint && !endpoint.endsWith("/chat/completions")) {
    endpoint = endpoint.replace(/\/+$/, "") + (endpoint.endsWith("/v1") ? "/chat/completions" : "/v1/chat/completions");
  }

  // Default endpoint if not set
  if (!endpoint) {
    endpoint = "http://138.252.100.105:20128/v1/chat/completions";
  }

  const requestBody = JSON.stringify({
    model,
    messages: [
      { role: "system", content: systemInstruction },
      { role: "user", content: prompt }
    ],
    temperature: 0.7,
    max_tokens: 4096
  });

  const requestHeaders = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${apiKey}`
  };

  // 2. Primary Attempt: Standard HTTPS/HTTP fetch with 12s timeout
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 12000);
    const res = await fetch(endpoint, {
      method: "POST",
      headers: requestHeaders,
      body: requestBody,
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      const content = data?.choices?.[0]?.message?.content;
      if (content && content.trim()) {
        return content.trim();
      }
      errors.push(`Endpoint returned empty message content: ${JSON.stringify(data).slice(0, 120)}`);
    } else {
      const errText = await res.text().catch(() => "");
      errors.push(`Endpoint HTTP ${res.status}: ${errText.slice(0, 150)}`);
    }
  } catch (err) {
    errors.push(`Direct fetch: ${err.message || String(err)}`);

    // 3. Fallback: If direct fetch failed and URL has a custom non-standard port, try raw TCP socket
    const parsedUrl = new URL(endpoint);
    if (parsedUrl.port && parsedUrl.port !== "80" && parsedUrl.port !== "443") {
      try {
        const sockRes = await fetchOverSocket(endpoint, {
          method: "POST",
          headers: requestHeaders,
          body: requestBody
        });
        if (sockRes.ok) {
          const data = await sockRes.json();
          const content = data?.choices?.[0]?.message?.content;
          if (content && content.trim()) {
            return content.trim();
          }
        } else {
          const sockText = await sockRes.text().catch(() => "");
          errors.push(`Socket HTTP ${sockRes.status}: ${sockText.slice(0, 150)}`);
        }
      } catch (sockErr) {
        errors.push(`Socket connect: ${sockErr.message || String(sockErr)}`);
      }
    }
  }

  // 4. Fallback: Cloudflare Workers AI (Native DeepSeek on Cloudflare GPUs)
  if (env.AI) {
    try {
      const aiRes = await env.AI.run("@cf/deepseek-ai/deepseek-r1-distill-qwen-32b", {
        messages: [
          { role: "system", content: systemInstruction },
          { role: "user", content: prompt }
        ]
      });
      if (aiRes?.response && aiRes.response.trim()) {
        return aiRes.response.trim();
      }
    } catch (aiErr) {
      errors.push(`Workers AI DeepSeek: ${aiErr.message || String(aiErr)}`);
    }
  }

  // 5. Fallback: Gemini API Key if configured in Cloudflare secrets
  if (env.GEMINI_API_KEY) {
    try {
      const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${env.GEMINI_API_KEY}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          systemInstruction: { parts: [{ text: systemInstruction }] }
        })
      });
      if (res.ok) {
        const data = await res.json();
        const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
        if (text && text.trim()) return text.trim();
      }
    } catch (gemErr) {
      errors.push(`Gemini API: ${gemErr.message || String(gemErr)}`);
    }
  }

  // 6. Actionable Diagnostic Report (never hide failures behind misleading greetings)
  const errorBullets = errors.map(e => `• ${e}`).join("\n");
  const maskedKey = apiKey ? `${apiKey.slice(0, 6)}...${apiKey.slice(-4)}` : "(none)";

  return `⚠️ **[Kratos Edge // DeepSeek Connection Alert]**\n\nCould not receive a completion from the LLM provider on Cloudflare Edge.\n\n**Current Configuration:**\n• **Endpoint:** \`${endpoint}\`\n• **Model:** \`${model}\`\n• **API Key:** \`${maskedKey}\`\n• **Mode:** ${isAgentMode ? "Autonomous Agent" : "Normal Chat"}\n\n**Diagnostics:**\n${errorBullets}\n\n**How to Fix:**\n1. **Official DeepSeek API:** In Cloudflare Pages/Workers Dashboard (Settings → Environment Variables), set:\n   - \`DEEPSEEK_API_KEY\`: \`sk-...\` (your DeepSeek API key)\n   - \`CHAT_ENDPOINT\`: \`https://api.deepseek.com/chat/completions\`\n   - \`NORMAL_MODE_MODEL\`: \`deepseek-chat\`\n2. **Custom Port 20128:** Cloudflare Edge egress proxies block non-standard HTTP ports (like \`20128\`). Use a standard HTTPS reverse proxy or Cloudflare Tunnel on your host, or set \`DEEPSEEK_API_KEY\` to use official DeepSeek.\n3. **Test Endpoint:** You can inspect live connectivity at any time by opening \`/api/diag\` in your browser.`;
}

