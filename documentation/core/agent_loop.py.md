# Subsystem: Autonomous Execution Core
## Module: `kratos_agent.core.agent_loop`

Source File: [`src/kratos_agent/core/agent_loop.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/agent_loop.py)

---

### 1. Architectural Purpose & Overview

The `AgentLoop` class is the central autonomous execution engine of Kratos. It receives a high-level user instruction or mission and drives the iterative cycle of:
1. **Context Construction**: Assembles conversation history, cognitive memory, loaded skills, workspace state, and tool schemas.
2. **Model Deliberation**: Prompts the LLM Brain to decide the next action or emit tool calls.
3. **Approval Gating**: Evaluates tool permissions against Sovereign vs Supervised modes.
4. **Tool Execution**: Dispatches tool calls to the `ToolRegistry`, sandboxed subprocesses, or background workers.
5. **False Completion Detection**: Authoritatively verifies that the requested goal was actually achieved (e.g. verifying files exist on disk, services are listening, or tests pass) rather than blindly believing the LLM's verbal claim of completion.
6. **Self-Correction & Recovery**: Detects repeated failing commands, infinite inspection loops, or stalled processes, intervening to prompt alternate strategies.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI / API
    participant Loop as AgentLoop
    participant Ctx as ContextBuilder
    participant Brain as BrainChatModel
    participant Gate as ApprovalGate
    participant Registry as ToolRegistry / Sandbox
    participant Verifier as VerificationManager

    User->>CLI: "Build a REST API in FastAPI"
    CLI->>Loop: run(user_request)
    loop Iterative Execution (Bounded Max Steps)
        Loop->>Ctx: assemble_context()
        Ctx-->>Loop: context_messages
        Loop->>Brain: invoke(context_messages)
        Brain-->>Loop: AIMessage(content, tool_calls)
        alt Contains Tool Calls
            Loop->>Gate: check_permission(tool_call)
            Gate-->>Loop: (allowed, reason)
            Loop->>Registry: execute(tool_call)
            Registry-->>Loop: ToolResult
            Loop->>Loop: record_step(tool_call, ToolResult)
        else Model Claims "Done"
            Loop->>Verifier: verify_completion(state, workspace)
            alt Verified Truthful
                Verifier-->>Loop: VerificationSuccess
                Loop-->>CLI: Final Success Output
            else False Completion Detected
                Verifier-->>Loop: VerificationFailure(reason)
                Loop->>Loop: Inject critique into context
            end
        end
    end
```

---

### 2. Key Classes & Methods

#### Class `AgentLoop`

##### Constructor
```python
AgentLoop(
    context: ContextBuilder,
    instructions: InstructionEngine,
    tools: ToolRegistry,
    model: BaseChatModel,
    emit: Callable[[AgentEvent], None] | None = None,
    workspace: Path | None = None,
    max_steps: int = 48,
    approval_mode: ApprovalMode = ApprovalMode.SOVEREIGN,
)
```
- `context`: Manages conversation context budgeting and token compression.
- `instructions`: Dynamically constructs system directives and behavioral rules.
- `tools`: Authoritative catalog of callable tools with permission metadata.
- `model`: Brain chat model for decision generation.
- `emit`: Event callback function publishing telemetry to UI/TUI/web.
- `workspace`: Working directory root on the host machine.
- `max_steps`: Hard upper bound on reasoning loops (default: 48, max: 64).
- `approval_mode`: Sovereign (autonomous) or Supervised (human-in-the-loop).

##### Core Execution: `run(user_request: str) -> AgentRunState`
Executes the autonomous loop until:
- The task is verified complete by the `VerificationManager`.
- The hard step limit (`max_steps`) is reached.
- An unrecoverable termination condition or user interrupt occurs.

##### Worker Execution: `_execute_tool_call_worker(call: ToolCall, gate: Callable) -> ToolResult`
- Runs tool execution in a background thread or sandboxed worker.
- Enforces loop-bounding heuristics:
  - **Identical Failed Shell Detection**: Blocks models from running the exact same failed shell command twice consecutively.
  - **Inspection Loop Guard**: Caps repetitive `grep_search` or `read_file` loops on the same file patterns without writing code.
  - **Self-Tool Creator Scoping**: Reusable tool creation (`self_tool_creator`) is restricted unless the user explicitly requested tool creation.

---

### 3. False Completion Gating

Kratos distinguishes itself by rejecting hallucinated or verbal completions:
- If a model says *"I have completed creating the website"*, Kratos checks:
  1. Did the agent write files?
  2. Are the expected artifacts present in `workspace`?
  3. Did the command exit with code 0?
- If the verification fails, Kratos injects a high-priority system critique:
  > *"You claimed completion, but the verification contract failed: index.html was not written. Continue working."*
