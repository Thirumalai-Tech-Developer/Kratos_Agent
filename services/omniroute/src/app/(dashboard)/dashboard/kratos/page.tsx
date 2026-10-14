"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getUserProfile, profileRequestPath } from "@/lib/kratos/browserWorkspaceProfile.js";

export default function KratosWorkspace() {
  const [status, setStatus] = useState<"connecting" | "ready" | "busy" | "offline">("connecting");
  const [error, setError] = useState("");
  const [profile, setProfile] = useState("");
  useEffect(() => { setProfile(getUserProfile()); }, []);
  useEffect(() => {
    if (!profile) return;
    let alive = true;
    const controller = new AbortController();
    async function refresh() {
      try {
        const response = await fetch(profileRequestPath("/api/health", profile, true), { signal: controller.signal });
        if (!response.ok) throw new Error("The Kratos runtime is unavailable. Start Kratos Studio and reload this page.");
        const data = await response.json();
        if (alive) { setStatus(data.busy ? "busy" : "ready"); setError(""); }
      } catch (err) {
        if (alive) { setStatus("offline"); setError(err instanceof Error ? err.message : "Could not connect to Kratos."); }
      }
    }
    void refresh();
    const timer = setInterval(refresh, 5000);
    return () => { alive = false; controller.abort(); clearInterval(timer); };
  }, [profile]);
  async function cancel() {
    if (!profile) return;
    try {
      const response = await fetch(profileRequestPath("/api/chat/cancel", profile, true), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!response.ok) setError("Could not request cancellation. Check the runtime status.");
    } catch { setError("Could not reach the runtime to cancel the task."); }
  }
  return (
    <section className="fixed inset-0 z-[60] flex h-dvh min-h-0 flex-col bg-[#101318]">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
        <Link href="/dashboard" className="text-xs text-text-muted hover:text-text-primary">← Dashboard</Link>
        <div className="flex items-center gap-3 text-xs">
          <span role="status">{status === "busy" ? "Task running" : status === "ready" ? "Ready" : status === "offline" ? "Offline" : "Connecting…"}</span>
          {status === "busy" && <button className="rounded-lg border border-border px-3 py-2" onClick={cancel}>Stop task</button>}
          <Link href="/dashboard/providers" className="rounded-lg border border-border px-3 py-2">Providers</Link>
          {profile && <Link href={`/dashboard/kratos/mcp?profile=${profile}`} className="rounded-lg border border-border px-3 py-2">MCP and tools</Link>}
        </div>
      </div>
      {error && <p role="alert" className="rounded-lg border border-border p-4 text-text-muted">{error}</p>}
      {profile && status !== "offline" && <iframe title="Kratos agent console" src={`/dashboard/kratos/workspace/index.html?profile=${profile}`} className="min-h-0 w-full flex-1 border-0 bg-[#101318]" allow="microphone; camera" />}
    </section>
  );
}
