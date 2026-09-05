/**
 * Cloudflare Pages Functions Entry Point: /api/*
 * Handles all REST and streaming endpoints for Kratos on Cloudflare Pages.
 */

import { handleApi, corsHeaders, SCHEMA_SQL } from "../../worker.js";

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  // Handle CORS pre-flight
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: corsHeaders()
    });
  }

  // Auto-initialize D1 schema on first run if DB is bound
  if (env.DB && !env._schema_initialized) {
    try {
      const statements = SCHEMA_SQL.split(";").map(s => s.trim()).filter(Boolean);
      for (const st of statements) {
        await env.DB.prepare(st).run().catch(() => {});
      }
      env._schema_initialized = true;
    } catch (_) {}
  }

  try {
    return await handleApi(request, env, url);
  } catch (err) {
    return new Response(JSON.stringify({ error: String(err.message || err) }), {
      status: 500,
      headers: {
        ...corsHeaders(),
        "Content-Type": "application/json; charset=utf-8"
      }
    });
  }
}
