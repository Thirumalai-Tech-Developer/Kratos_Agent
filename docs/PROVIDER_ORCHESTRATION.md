# KRATOS BEAST // MULTI-SDK PROVIDER ORCHESTRATION

## Layer C Execution Fabric, Capability Routing, and Multi-Agent Workflows

---

## 1. Provider Contract (`AgentBackend` / `ExecutionBackend`)

Every execution runtime implements the protocol defined in `kratos_agent.providers.base`:

```python
class AgentBackend(Protocol):
    name: str

    async def start_session(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession: ...

    async def run(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AgentRun: ...

    async def stream(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[AgentEvent]: ...

    async def steer(self, task_id: str, instruction: str) -> bool: ...

    async def interrupt(self, task_id: str) -> bool: ...

    async def close(self) -> None: ...

    def capabilities(self) -> AgentCapabilities: ...

    async def health_check(self) -> ProviderHealth | dict[str, Any]: ...
```

---

## 2. Capability Matrix & Requirements Matching

Each adapter declares verified capabilities via `AgentCapabilities`:

```python
AgentCapabilities(
    file_editing=True,
    shell_execution=True,
    git_workflows=True,
    streaming=True,
    image_input=True,
    subagents=True,
    tool_calling=True,
    mcp=True,
    session_persistence=True,
    steering=True,
    interruption=True,
    sandbox=True,
    long_running=True,
    reasoning=True,
    max_context_tokens=128000,
)
```

The router matches `TaskRequirements` against these capabilities:
- Missing hard requirements immediately disqualify the candidate.
- Matching capabilities award weighted bonus points.
- Lower latency and healthy circuit breakers prioritize the highest-scoring candidate.

---

## 3. Coordinated Multi-Agent Workflows

### A. Multi-Agent Review Workflow
OMNI orchestrates an implementation pass followed by parallel specialized reviews:

```text
OMNI (Root Task)
 │
 ├── 1. Implement Changes ────────► Primary Coder (e.g. Codex)
 │                                        │
 │                                        ▼ (Output)
 ├── 2. Parallel Specialist Reviews
 │    ├── Security Review ────────► Specialist 1 (e.g. Claude)
 │    └── Architecture Review ────► Specialist 2 (e.g. Kimi)
 │                                        │
 │                                        ▼ (Findings)
 └── 3. Verification Gate ────────► Deduplicate & verify against test suite
```

Review findings are parsed into structured schemas:
- `severity`: critical, high, medium, low, info
- `file`: relative file path
- `line`: line number
- `finding`: description of potential flaw
- `evidence`: code snippet or proof
- `recommendation`: remediation steps
- `confidence`: numerical confidence score (0.0 – 1.0)

### B. Implementation Consensus Workflow
For critical tasks, OMNI can command two competing implementations:

```text
OMNI
 │
 ├── Isolated Workspace A (.kratos/consensus/task/workspace_A) ──► Candidate A
 └── Isolated Workspace B (.kratos/consensus/task/workspace_B) ──► Candidate B
          │                                                              │
          └──────────────────────────────┬───────────────────────────────┘
                                         ▼
                         Objective Verification (Tests + Lint + AST)
                                         ▼
                         Highest-Scoring Winner Promoted
```

Selection is strictly based on objective test and verification outcomes, never on vendor branding.

---

## 4. ResourceLockManager & Concurrency Safety

To prevent conflicting concurrent mutations during parallel execution:
- Tracks `reads`, `writes`, and `side_effects` per active task.
- Enforces mutual exclusion:
  - No task can write to a file currently being read or written by another task.
  - Side-effect barriers prevent simultaneous environment modifications.
- Tasks wait safely and release locks on completion or error.

---

## 5. Diagnostics & CLI Doctor

Inspect backend status and health at any time:

```bash
# Run CLI doctor
uv run kratos providers doctor

# Interactive slash command in Kratos CLI
/providers
/providers health
/providers inspect codex
```
