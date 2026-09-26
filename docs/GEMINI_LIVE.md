# GEMINI LIVE // REALTIME MULTIMODAL PERCEPTION & VOICE NARRATION

## Realtime Multimodal I/O Bridge for Kratos Omni

---

## 1. Role & Identity

Gemini Live is **strictly optional realtime multimodal senses (ears, eyes) and voice narration**.

```text
                  ┌───────────────────────┐
                  │      USER INPUT       │
                  │ (Audio, Screen, Web)  │
                  └──────────┬────────────┘
                             │
                             ▼
                  ┌───────────────────────┐
                  │      GEMINI LIVE      │
                  │   Realtime Senses     │
                  └──────────┬────────────┘
                             │
                       LiveIntent
                             │
                             ▼
                  ┌───────────────────────┐
                  │      KRATOS OMNI      │
                  │       ONE BRAIN       │
                  └──────────┬────────────┘
                             │
                      Execution Tasks
                             │
                             ▼
                  ┌───────────────────────┐
                  │   EXECUTION FABRIC    │
                  │     (SDK Adapters)    │
                  └──────────┬────────────┘
                             │
                       AgentEvents
                             │
                             ▼
                  ┌───────────────────────┐
                  │    VOICE NARRATION    │
                  │  (Spoken Summaries)   │
                  └───────────────────────┘
```

Gemini Live is **NOT**:
- A competing intelligence or alternative code planner.
- Directly orchestrating tasks or bypassing the Kratos `TaskManager`.
- Allowed to persist memories or bypass the `VerificationManager`.

---

## 2. Realtime Intent Delegation

User speech is transcribed and structured into typed `LiveIntent` records:

```python
@dataclass
class LiveIntent:
    intent_type: str  # "delegate_task", "interrupt", "steer", "query"
    raw_prompt: str
    visual_context: VisualSnapshot | None = None
    priority: int = 1
```

The bridge dispatches `LiveIntent` directly into Kratos's `ProviderRouter`, where OMNI decomposes the request into task graph nodes.

---

## 3. Visual Context Sampling & Filtering

To prevent context bloat and rate-limit exhaustion, visual frames are sampled with adaptive gating:
- **Rate-limited sampling**: Max 1 snapshot per 2.0 seconds by default.
- **Hash deduplication**: If the screen hasn't changed (identical hash), frames are dropped.
- **Scoped injection**: Visual snapshots are attached only to tasks explicitly demanding vision or UI debugging.

---

## 4. Voice Narration & Speech Sanitization

Narration operates over canonical `AgentEvent` streams:
- Only events with `narratable=True` or `voice_narratable=True` are spoken.
- High-frequency token deltas (`TOKEN_DELTA`) are silenced.
- Meaningful state milestones are narrated:
  - `"Starting the task."`
  - `"Inspecting the repository."`
  - `"Editing authentication module."`
  - `"Running test suite."`
  - `"Verification passed."`
  - `"Task complete."`
- **Secret Redaction**: Every spoken phrase is processed by `sanitize_speech_text()`, stripping API keys, OAuth Bearer tokens, private keys, and passwords.

---

## 5. Fault Isolation & Disconnection Resilience

If Gemini Live disconnects:
- Core Kratos execution continues uninterrupted.
- Tasks proceed through their task graph nodes.
- Filesystem edits, tests, and verification execute normally.
- Results remain fully accessible via Web UI, CLI, and event stores.
