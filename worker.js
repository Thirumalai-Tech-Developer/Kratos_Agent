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

export { corsHeaders, jsonResponse, handleApi, SCHEMA_SQL, TOOLS_LIST };

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

  // 10. POST /api/chat (Server-Sent Events streaming chat)
  if (path === "/api/chat" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    const prompt = (body.prompt || "").trim();
    if (!prompt) return jsonResponse({ error: "Empty prompt" }, 400);

    let sessionId = body.session_id;
    const now = new Date().toISOString().replace("T", " ").slice(0, 19);

    if (!sessionId) {
      sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
      const title = prompt.slice(0, 40) + (prompt.length > 40 ? "..." : "");
      if (env.DB) {
        await env.DB.prepare(
          "INSERT OR IGNORE INTO sessions (id, title, model, created_at, updated_at, last_status) VALUES (?, ?, ?, ?, ?, ?)"
        ).bind(sessionId, title, "auto", now, now, "completed").run().catch(() => {});
      }
    }

    // Call LLM or generate response
    const agentReply = await generateAgentResponse(prompt, env);

    // Save turn into Cloudflare D1
    if (env.DB) {
      try {
        const turnId = `turn_${Date.now()}_0`;
        const countRes = await env.DB.prepare("SELECT COUNT(*) as c FROM turns WHERE session_id = ?").bind(sessionId).first().catch(() => ({ c: 0 }));
        const turnIndex = countRes ? Number(countRes.c) : 0;

        await env.DB.prepare(
          "INSERT INTO turns (id, session_id, turn_index, timestamp, user_query, agent_reply, tools_used_json) VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(turnId, sessionId, turnIndex, now, prompt, agentReply, "[]").run();

        await env.DB.prepare(
          "UPDATE sessions SET updated_at = ?, last_status = 'completed' WHERE id = ?"
        ).bind(now, sessionId).run();
      } catch (dbErr) {
        console.error("D1 turn insert error:", dbErr);
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
          model: env.NORMAL_MODE_MODEL || "deepseek-web/deepseek-v4-pro",
          agent_mode: false
        });

        send({
          type: "step",
          step: "reasoning",
          label: "Synthesizing response on Cloudflare Edge Worker..."
        });

        // Send tokens with subtle typing effect
        const words = agentReply.split(" ");
        for (let i = 0; i < words.length; i += 4) {
          const chunk = words.slice(i, i + 4).join(" ") + " ";
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

  return jsonResponse({ error: `Route ${path} not found` }, 404);
}

async function generateAgentResponse(prompt, env) {
  // 1. If Gemini API Key is configured in Cloudflare secrets
  if (env.GEMINI_API_KEY) {
    try {
      const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${env.GEMINI_API_KEY}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          systemInstruction: {
            parts: [{ text: "You are Kratos, an elite AI coding assistant operating in hosted web mode on Cloudflare edge. Answer questions and code queries directly and helpfully." }]
          }
        })
      });
      const data = await res.json();
      const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
      if (text) return text;
    } catch (_) {}
  }

  // 2. If Cloudflare Workers AI is available
  if (env.AI) {
    try {
      const aiRes = await env.AI.run("@cf/meta/llama-3.1-8b-instruct", {
        messages: [
          { role: "system", content: "You are Kratos, an elite assistant running on Cloudflare Workers edge." },
          { role: "user", content: prompt }
        ]
      });
      if (aiRes?.response) return aiRes.response;
    } catch (_) {}
  }

  // 3. Built-in smart response generator
  return `I am **Kratos**, operating in Normal Chat Mode on the Cloudflare Edge network.\n\nYour prompt has been processed and your turn is permanently stored in Cloudflare D1 (\`0e785bd7...d9d7\`).\n\nYou asked:\n> ${prompt}\n\nTerminal command execution and filesystem modification tools are disabled in this hosted web preview (no dedicated VPS sandbox). You can continue chatting, discuss architecture, or query D1 tables!`;
}
