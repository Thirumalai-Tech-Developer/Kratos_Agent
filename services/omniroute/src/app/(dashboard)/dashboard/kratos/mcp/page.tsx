"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type Server = { name: string; enabled: boolean; transport: string; status: { state: string; tools?: number; error?: string } };

export default function KratosMcpPage() {
  const [servers, setServers] = useState<Server[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [config, setConfig] = useState("");
  const [path, setPath] = useState("");
  const [urlName, setUrlName] = useState("");
  const [url, setUrl] = useState("");
  const [transport, setTransport] = useState("streamable-http");
  const load = async () => {
    try {
      const response = await fetch("/api/kratos/mcp", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Could not load MCP connections");
      setServers(body.servers);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not load connections"); }
  };
  useEffect(() => {
    setConfig(JSON.stringify({ url: `${window.location.origin}/api/mcp/stream`, type: "streamable-http", enabled: true }, null, 2));
    void load();
  }, []);
  const change = async (payload: Record<string, unknown>) => {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/kratos/mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Configuration failed");
      setServers(body.servers);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Configuration failed"); }
    finally { setBusy(false); }
  };
  return <main className="space-y-6 p-6">
    <div><Link href="/dashboard/kratos" className="text-primary">Back to workspace</Link>
      <h1 className="mt-3 text-2xl font-semibold">Kratos MCP connections</h1>
      <p className="text-text-muted">Connected tools, resources and prompts run through Kratos permissions. Configuration changes reconnect enabled servers.</p></div>
    {error && <p role="alert" className="rounded-lg border border-red-500 p-3">{error}</p>}
    <section className="space-y-3">
      {servers.map((server) => <div key={server.name} className="flex flex-wrap items-center gap-4 rounded-lg border border-border p-4">
        <div className="flex-1"><strong>{server.name}</strong><p className="text-sm text-text-muted">{server.transport} · {server.status.state} · {server.status.tools ?? 0} tools</p>
          {server.status.error && <p className="text-sm">{server.status.error}</p>}</div>
        <button disabled={busy} onClick={() => change({ action: "toggle", name: server.name, enabled: !server.enabled })}>{server.enabled ? "Disable" : "Enable"}</button>
        <button disabled={busy} onClick={() => change({ action: "remove", name: server.name })}>Remove connection</button>
      </div>)}
      <button className="rounded-lg border border-border px-4 py-2" disabled={busy} onClick={() => change({ action: "reconnect" })}>{busy ? "Connecting…" : "Reconnect"}</button>
    </section>
    <form className="space-y-3 rounded-lg border border-border p-4" onSubmit={(event) => {
      event.preventDefault();
      try {
        const endpoint = new URL(url);
        if (!["http:", "https:"].includes(endpoint.protocol) || endpoint.username || endpoint.password) {
          throw new Error("Use an HTTP(S) URL without embedded credentials");
        }
        if (servers.some((server) => server.name === urlName)) {
          throw new Error("That name already exists. Use the configuration form below to update it.");
        }
        void change({ action: "configure", name: urlName, config: { url, type: transport, enabled: true } });
      } catch (failure) { setError(failure instanceof Error ? failure.message : "Enter a valid MCP URL"); }
    }}>
      <h2 className="text-lg font-semibold">Add an MCP URL</h2>
      <label className="block">Name<input required value={urlName} onChange={(event) => setUrlName(event.target.value)} className="mt-1 block w-full rounded border border-border bg-surface p-2" /></label>
      <label className="block">Server URL<input required type="url" placeholder="https://example.com/mcp" value={url} onChange={(event) => setUrl(event.target.value)} className="mt-1 block w-full rounded border border-border bg-surface p-2" /></label>
      <label className="block">Transport<select value={transport} onChange={(event) => setTransport(event.target.value)} className="mt-1 block rounded border border-border bg-surface p-2"><option value="streamable-http">Streamable HTTP</option><option value="sse">SSE</option></select></label>
      <p className="text-sm text-text-muted">For API key headers, use the configuration form below with environment variable references. Browser OAuth sign-in is not available yet.</p>
      <button disabled={busy} className="rounded bg-primary px-4 py-2 text-white">Add and connect</button>
    </form>
    <form className="space-y-3 rounded-lg border border-border p-4" onSubmit={(event) => {
      event.preventDefault();
      try { void change({ action: "configure", name, config: JSON.parse(config) }); }
      catch { setError("Configuration must be valid JSON"); }
    }}>
      <h2 className="text-lg font-semibold">Add or update a connection</h2>
      <label className="block">Name<input required className="mt-1 block w-full rounded border border-border bg-surface p-2" value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label className="block">MCP configuration JSON<textarea required rows={7} className="mt-1 block w-full rounded border border-border bg-surface p-2 font-mono" value={config} onChange={(event) => setConfig(event.target.value)} /></label>
      <p className="text-sm text-text-muted">Use a command with args for stdio, or a URL for HTTP/SSE. Use environment variable references for credentials. Saving an enabled command starts that server. Updating an existing name replaces its configuration.</p>
      <button disabled={busy} className="rounded bg-primary px-4 py-2 text-white">Save connection</button>
    </form>
    <form className="space-y-3 rounded-lg border border-border p-4" onSubmit={(event) => { event.preventDefault(); void change({ action: "import", path }); }}>
      <h2 className="text-lg font-semibold">Import a config or MCP plugin</h2>
      <label className="block">Local config file or plugin directory<input required value={path} onChange={(event) => setPath(event.target.value)} className="mt-1 block w-full rounded border border-border bg-surface p-2" /></label>
      <button disabled={busy} className="rounded border border-border px-4 py-2">Import and connect</button>
      <p className="text-sm text-text-muted">Supports mcpServers and mcp.servers maps, including .mcp.json plugins with PLUGIN_ROOT and PLUGIN_DATA placeholders.</p>
    </form>
    <Link href="/dashboard/mcp" className="text-primary">OmniRoute MCP server settings</Link>
  </main>;
}
