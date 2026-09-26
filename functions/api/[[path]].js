/**
 * Cloudflare Pages Functions Entry Point: /api/*
 * Handles all REST and streaming endpoints for Kratos on Cloudflare Pages.
 */

import { handleApi, corsHeaders, getSchemaSql, parseSqlStatements } from "../../worker.js";

let schemaInitialized = false;

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
  if (env.DB && !schemaInitialized) {
    try {
      const rawSql = getSchemaSql();
      const statements = parseSqlStatements(rawSql);
      for (const st of statements) {
        await env.DB.prepare(st).run();
      }
      schemaInitialized = true;
    } catch (err) {
      console.error("D1 schema initialization failed:", err);
      return new Response(JSON.stringify({ error: `D1 schema initialization failed: ${err.message || err}` }), {
        status: 500,
        headers: {
          ...corsHeaders(),
          "Content-Type": "application/json; charset=utf-8"
        }
      });
    }
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
