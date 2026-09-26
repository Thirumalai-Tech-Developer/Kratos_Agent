# KRATOS OMNI — ARCHITECTURAL SPECIFICATION

## One Brain. Many SDK Capabilities. Realtime Multimodal Interface.

> **ABSOLUTE ARCHITECTURAL INVARIANT:**
>
> **KRATOS HAS ONLY ONE MODEL.**
>
> There is exactly one intelligence concept inside Kratos: **The Kratos Omni Model**.
>
> External SDKs are **NOT** alternative Kratos models or brains.
> They are **Layer C Execution Capabilities / SDK Adapters**.
>
> Gemini Live is **optional realtime multimodal I/O (ears, eyes, voice)**, not a separate coding model.
>
> **Kratos does not have five brains. Kratos has one brain.**

---

## 1. System Topology

```text
                           USER
                            │
                     text / voice / vision
                            │
                            ▼
                      GEMINI LIVE
                    optional realtime
                   (ears / eyes / voice)
                            │
                            ▼
                     KRATOS OMNI
                       ONE MODEL
                            │
              reasoning / planning / decisions
                            │
                            ▼
                  KRATOS EXECUTION FABRIC
                            │
          ┌─────────────────┼──────────────────┐
          │                 │                  │
          ▼                 ▼                  ▼
      Claude SDK        Codex SDK          Kimi SDK
      capability        capability        capability
          │                 │                  │
          ├─────────────────┼──────────────────┤
          │                 │                  │
          ▼                 ▼                  ▼
    DeepSeek Harness   Antigravity SDK    Native Kratos
      capability        capability        capability
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │
                            ▼
                      KRATOS TOOLS
                  (canonical registry)
                            │
                            ▼
                       VERIFICATION
                       (Truth Gate)
                            │
                            ▼
                       KRATOS OMNI
                            │
                            ▼
                      GEMINI LIVE
                            │
                            ▼
                           USER
```

---

## 2. The Three Conceptual Layers

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Layer A: OMNI INTELLIGENCE (Sole Authority)                           │
│  - OmniModel, OmniPlanner, OmniContext, OmniDecisionEngine            │
│  - Intent understanding, reasoning, task decomposition                │
│  - Context compression, capability requirement synthesis              │
│  - Objective error diagnosis, replanning, and response synthesis      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer B: KRATOS ORCHESTRATION & STATE MANAGEMENT                      │
│  - TaskManager & TaskGraph (Directed acyclic graph of tasks)          │
│  - Persistent Memory (Episodic, Semantic, Procedural, Working)        │
│  - Canonical EventBus & EventStore (Unified AgentEvent stream)        │
│  - Canonical ToolRegistry & MCP Translation Layer                      │
│  - VerificationManager (Objective proof, syntax & test assertions)    │
│  - ResourceLockManager (Atomic path mutation & concurrency locks)     │
│  - CircuitBreaker & Health Monitor (Ready, Degraded, Offline, Disabled)│
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer C: EXECUTION FABRIC (Runtime Capabilities / Hands)              │
│  - Claude Agent SDK Adapter (Subagents, hooks, MCP, streaming)        │
│  - Codex SDK Adapter (Turn control, interruption, steering, vision)   │
│  - Kimi Agent SDK Adapter (Streaming, tool approvals, long-context)   │
│  - DeepSeek Harness Adapter (Persistent JSON-RPC, workspace patches)   │
│  - Google Antigravity SDK Adapter (Verified cloud & sandbox execution)│
│  - Kratos Native Engine (Hermetic local execution & subprocesses)     │
│  - Computer Use, Browser Automation, Shell, and Filesystem             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Architectural Rules

### Rule 1: No Model Routers or Personality Shifts
- External SDKs are never registered as Kratos models.
- There is no model router selecting between Claude, Codex, Kimi, DeepSeek, or Antigravity as thinking entities.
- The system never says "Claude is smarter" or "Codex is the coding brain".
- Instead:
  $$\text{OMNI Decision} \longrightarrow \text{Required Capabilities} \longrightarrow \text{Execution Backend}$$

### Rule 2: Kratos Owns All Persistent Memory
- External SDK sessions maintain ephemeral turn state only.
- Long-term episodic memory, project knowledge, and learned procedures reside exclusively in Kratos memory.
- Context is assembled dynamically via `ProviderContextBridge` with strict content-aware compaction ensuring task directives are never evicted.

### Rule 3: Single Canonical Tool Registry
- Tools are implemented once in `kratos_agent.core.tools`.
- `ToolAdapter` translates this single source of truth into:
  - OpenAI tool schema for Codex / Kratos Native
  - Anthropic tool schema for Claude
  - Model Context Protocol (MCP) tool format for Kimi and external agents
- Every tool execution is traced with SHA-256 argument/result hashes, duration, and status.

### Rule 4: Authoritative Verification Gatekeeper (False Completion Defense)
- **An SDK saying "done" does NOT complete a Kratos task.**
- Provider output is untrusted data.
- Completion requires objective evidence:
  1. Files exist and are non-empty.
  2. AST syntax check passes without `SyntaxError`.
  3. Tests execute and pass with zero exit code.
  4. Declared output symbols or side effects are physically verified.

### Rule 5: Secret Protection & Prompt Injection Defense
- API keys, OAuth Bearer tokens, private keys, and passwords are unconditionally redacted via `redact_secrets()` before entering:
  - Event payloads
  - Voice narration
  - Web UI streams
  - CLI logs
  - Provider context prompts
- External repository files and tool outputs are quarantined as untrusted data and cannot override Kratos system policy.

### Rule 6: Hermetic Backward Compatibility
- Kratos operates with 100% functionality when all external SDKs and Gemini Live are disabled.
- The native Kratos runtime provides all fundamental execution capabilities (file editing, shell execution, git workflows, browser automation, and verification).
