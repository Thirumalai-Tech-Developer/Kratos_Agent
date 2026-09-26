"""Real Agent-Generated Planning Engine for Kratos Agent.

The Agent/LLM directly analyzes the user's request, workspace context, and repository
to formulate a tailored, structured execution plan before implementation begins.
No static universal 4-step templates.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

from kratos_agent.core.task_manager import ExecutionPlan, TaskItem, TaskState


class IntentKind(str, Enum):
    CHAT = "chat"
    QUESTION = "question"
    CODING_TASK = "coding_task"
    FILE_TASK = "file_task"
    COMPLEX_AGENT_TASK = "complex_agent_task"

    @property
    def requires_plan(self) -> bool:
        """Only coding, file, and complex agent tasks trigger the structured planning pipeline."""
        return self in (IntentKind.CODING_TASK, IntentKind.FILE_TASK, IntentKind.COMPLEX_AGENT_TASK)


def classify_intent(query: str, history: list[Any] | None = None) -> IntentKind:
    """Accurately classifies user intent to keep simple conversation clean while planning coding tasks."""
    q = query.strip().lower()
    q_norm = re.sub(r"[?!.,;:]", " ", q).strip()
    words = q_norm.split()

    # 1. Casual Chat / Greetings / Courtesy / Identity
    greetings = {"hi", "hello", "hey", "hola", "sup", "greetings", "good morning", "good evening", "good afternoon", "how are you", "how are u", "who are you", "who are u", "howdy", "yo", "help", "help me", "thanks", "thank you", "thx", "cool", "awesome", "nice", "ok", "okay", "bye", "goodbye"}
    if q_norm in greetings or any(q.startswith(g + " ") or q.startswith(g + "!") or q.startswith(g + ",") for g in ("hi", "hello", "hey", "hola", "who are you")):
        if len(words) <= 4 and not any(k in q for k in ("create", "build", "make", "fix", "code", "write", "refactor", "add", "implement")):
            return IntentKind.CHAT

    # 2. Capability, Help, and Skill Inquiries (Never plan casual capabilities questions)
    capability_phrases = (
        "what you can do",
        "what can you do",
        "what do you do",
        "what can kratos do",
        "what does kratos do",
        "what are you capable of",
        "what are your capabilities",
        "what are your features",
        "what are your skills",
        "what are your tools",
        "what tools do you have",
        "what skills do you have",
        "what can you help me with",
        "what can you help with",
        "what can you build",
        "tell me what you can do",
        "tell me about yourself",
        "show me what you can do",
        "how can you help",
        "how can you assist",
        "who made you",
        "who created you",
        "what is kratos",
        "list your capabilities",
        "list your tools",
        "list your skills",
        "show your tools",
        "show your skills",
        "list tools",
        "list skills",
    )
    if any(phrase in q_norm for phrase in capability_phrases):
        return IntentKind.QUESTION

    # 3. Conceptual Questions & Knowledge Queries
    question_starters = (
        "what is", "what are", "what does", "what do", "who is", "who are",
        "why is", "why are", "why does", "why do", "how does", "how do",
        "how is", "how can i", "how to", "can you explain", "could you explain",
        "explain what", "explain how", "tell me about", "define ", "is there",
        "are there", "difference between", "pros and cons"
    )
    if any(q.startswith(qs) for qs in question_starters):
        if not any(k in q for k in ("create", "build", "make", "write a", "implement", "fix", "refactor", "scaffold", "webapp", "website", "app")):
            return IntentKind.QUESTION

    # 4. Simple Code Explanation / Workspace Inspection
    if q.startswith("explain") or q.startswith("describe") or q.startswith("summarize") or q.startswith("where is") or q.startswith("find where") or q.startswith("show me where") or q.startswith("walk me through"):
        if not any(k in q for k in ("and create", "and fix", "and refactor", "and build", "and modify", "and write")):
            return IntentKind.QUESTION

    # 5. Basic calculation questions
    if q.startswith("add ") and any(num in q for num in ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "numbers")):
        return IntentKind.QUESTION

    # 6. Informational Questions ending with '?' (No imperative mutation verbs)
    if q.endswith("?"):
        imperative_verbs = ("create", "build", "scaffold", "implement", "refactor", "fix", "write a", "make a", "develop a", "deploy")
        if not any(verb in q for verb in imperative_verbs):
            return IntentKind.QUESTION

    # 7. Complex Multi-Step Scaffolding Tasks (Explicit creation of new full projects)
    complex_indicators = (
        "create a webapp", "create a website", "create an app", "create a full", "build a webapp",
        "build a website", "build an app", "build a full", "scaffold a", "scaffold", "three.js", "threejs",
        "full stack webapp", "fullstack webapp"
    )
    if any(ind in q for ind in complex_indicators):
        return IntentKind.COMPLEX_AGENT_TASK

    # 8. Operational & Autonomous Execution Tasks (Download, run, play, execute, automate)
    operational_keywords = (
        "download", "clone", "fetch", "play", "run", "launch", "automate",
        "install", "start", "stop", "restart", "deploy"
    )
    if any(k in q for k in operational_keywords):
        return IntentKind.CODING_TASK

    # 9. Standard Coding / Refactoring / Modification Tasks
    coding_keywords = (
        "create", "build", "make", "implement", "develop", "refactor", "fix", "debug",
        "rewrite", "generate", "add a", "update", "patch", "setup", "configure",
        "write a", "write", "modify", "delete", "remove", "migrate", "test"
    )
    if any(k in q for k in coding_keywords):
        return IntentKind.CODING_TASK

    # 10. File-specific Tasks
    if any(k in q for k in ("write file", "edit file", "delete file", "run test", "run build", "check file", "inspect", "report", "readme", ".py", ".ts", ".tsx", ".js", ".html", ".css", ".json", ".md")):
        return IntentKind.FILE_TASK

    # 11. Short queries or single-word inputs without coding actions
    if len(words) <= 3 and not any(k in q for k in ("build", "create", "make", "fix", "run", "play")):
        return IntentKind.CHAT

    # 12. Default fallback for general non-coding statements
    return IntentKind.CHAT


def should_create_plan(query: str) -> bool:
    """Determines whether a user prompt warrants a structured multi-step execution plan."""
    intent = classify_intent(query)
    return intent.requires_plan


PLANNING_SYSTEM_PROMPT = """You are Kratos Planner, the strategic planning module for the Kratos autonomous agent.
Analyze the user's request and workspace context, then generate a tailored, realistic, multi-step execution plan.

RULES:
1. Each task MUST be specific, concrete, and directly relevant to the user's exact request.
2. Do NOT output generic, vague placeholder tasks.
3. Match tasks directly to the user's explicit objective:
   - If the user asks to download, install, locate, or fetch existing software (e.g. games, tools, desktop apps, packages), plan to: (1) search the web to identify official/legitimate sources, (2) open and inspect the source page, (3) locate the genuine Windows/Linux download link, (4) perform the download, and (5) physically verify that the file exists on the filesystem.
   - NEVER immediately refuse a download request merely because the title is copyrighted or commercial. Search for official releases, legal open-source remakes/ports, or legitimate distributors first. Only if no legitimate source exists, truthfully report that. NEVER fabricate downloads or invent links.
   - If the user asks to find, search, compare, locate, or open a website, ALWAYS plan to use web/browser tools rather than answering from stale memory.
   - If the user asks to build, create, or scaffold a project, sequence tasks through architecture, core implementation, features/styling, and verification.
   - If the user asks to debug, fix, or refactor, sequence tasks through reproduction/diagnosis, root-cause fix, and test verification.
4. Each task should specify its appropriate `verification` type:
   - "none": Normal code editing, logic writing, or design tasks.
   - "build": Syntax check, compilation, or build verification (e.g. vite build, cargo check, tsc).
   - "tests": Unit/integration test suites or runtime execution checks.
   - "browser": Dedicated frontend browser UI verification (ONLY for Web UI projects on dedicated verification tasks).
   - "file": File existence and size verification on disk (for download, export, and generation tasks).
5. Keep the total number of tasks between 3 and 6 milestones.
6. Return ONLY a valid JSON object matching this schema:
{
  "goal": "Clear and concise summary of the goal",
  "tasks": [
    {
      "id": "1",
      "title": "Specific, actionable task title",
      "verification": "none"
    }
  ]
}
"""


def extract_json_plan(text: str) -> dict[str, Any] | None:
    """Extracts and parses a JSON plan from raw model output or markdown code blocks."""
    if not text or not text.strip():
        return None

    # Strip thinking blocks to prevent false brace detection inside chain-of-thought
    cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"<[｜|]{1,2}[^>]*[｜|]{1,2}>", "", cleaned).strip()

    sources = [cleaned] if cleaned else []
    if text not in sources:
        sources.append(text)

    for src in sources:
        # 1. Try markdown fenced code block
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*(?:```|$)", src, re.DOTALL)
        if fenced_match:
            try:
                data = json.loads(fenced_match.group(1))
                if isinstance(data, dict) and "tasks" in data:
                    return data
            except Exception:
                fixed = re.sub(r",\s*([\]}])", r"\1", fenced_match.group(1))
                try:
                    data = json.loads(fixed)
                    if isinstance(data, dict) and "tasks" in data:
                        return data
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

        # 2. Try targeting {"goal" or {"tasks" directly
        plan_start = re.search(r'\{\s*"(?:goal|tasks)"', src)
        if plan_start:
            brace_pos = plan_start.start()
            last_brace = src.rfind("}")
            if last_brace > brace_pos:
                candidate = src[brace_pos : last_brace + 1]
                try:
                    data = json.loads(candidate)
                    if isinstance(data, dict) and "tasks" in data:
                        return data
                except Exception:
                    fixed = re.sub(r",\s*([\]}])", r"\1", candidate)
                    try:
                        data = json.loads(fixed)
                        if isinstance(data, dict) and "tasks" in data:
                            return data
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)

        # 3. Try raw first and last brace search
        first_brace = src.find("{")
        last_brace = src.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            json_str = src[first_brace : last_brace + 1]
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and "tasks" in data:
                    return data
            except Exception:
                fixed = re.sub(r",\s*([\]}])", r"\1", json_str)
                try:
                    data = json.loads(fixed)
                    if isinstance(data, dict) and "tasks" in data:
                        return data
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

    return None


def extract_numbered_steps(text: str) -> list[dict[str, Any]] | None:
    """Extracts numbered or bulleted plan steps from conversational or markdown model output."""
    if not text or not text.strip():
        return None

    # Strip thinking tags if possible, but keep text inside if that's all there is
    cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    candidate_text = cleaned if len(cleaned.splitlines()) >= 2 else text

    lines = candidate_text.splitlines()
    tasks = []
    # Pattern matching "1. ...", "1) ...", "Step 1: ...", "### 1. ..."
    pattern = re.compile(r"^\s*(?:###?\s*)?(?:Step\s*)?(\d+)[\.\):\-]\s*(.+)$", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        m = pattern.match(stripped)
        if m:
            raw_title = m.group(2).strip()
            # Clean markdown bold/italics e.g. **Scaffold Project**: description
            clean_title = re.sub(r"^\*\*([^*]+)\*\*[:\s-]*(.*)$", r"\1: \2", raw_title).strip()
            clean_title = clean_title.strip("*_` ").rstrip(":")
            # If title is a very long paragraph, take the first sentence or 80 chars
            if len(clean_title) > 90:
                parts = re.split(r"[.!?]\s+", clean_title)
                clean_title = parts[0] if len(parts[0]) >= 10 else clean_title[:85] + "..."

            if clean_title and len(clean_title) >= 4:
                title_lower = clean_title.lower()
                v_type = "build" if any(w in title_lower for w in ("build", "compile", "tsc", "bundle")) else (
                    "tests" if any(w in title_lower for w in ("test", "pytest", "spec")) else (
                        "browser" if any(w in title_lower for w in ("browser", "ui verify", "visual", "layout check")) else "none"
                    )
                )
                tasks.append({
                    "id": str(len(tasks) + 1),
                    "title": clean_title,
                    "verification": v_type,
                })

    if len(tasks) >= 2:
        return tasks
    return None


def formulate_agent_plan(
    user_query: str,
    model: Any,
    workspace: Path,
    instructions: list[dict[str, str]] | None = None,
) -> ExecutionPlan:
    """Invokes the Agent/LLM to understand the request, inspect the context, and produce a real dynamic plan."""
    # List top-level files in workspace to provide real context
    ws_files: list[str] = []
    try:
        if workspace.exists() and workspace.is_dir():
            for p in list(workspace.iterdir())[:20]:
                if not p.name.startswith("."):
                    ws_files.append(f"{p.name}/" if p.is_dir() else p.name)
    except Exception as exc:
        logger.debug("Operation error suppressed: %s", exc)

    ws_ctx = f"Workspace directory: {workspace.name}\nExisting files: {', '.join(ws_files) if ws_files else 'empty workspace'}"

    plan_request = {
        "instructions": [{"name": "planner-system", "layer": "system", "content": PLANNING_SYSTEM_PROMPT}],
        "system": PLANNING_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": f"{ws_ctx}\n\nUser Request: {user_query}\n\nFormulate the structured execution plan in JSON:",
            }
        ],
        "tools": [],
        "workspace": {"cwd": str(workspace), "platform": "windows"},
    }

    try:
        response = model.complete(plan_request)
        raw_text = getattr(response, "text", "") or ""

        # 1. Try structured JSON extraction
        parsed = extract_json_plan(raw_text)
        if parsed and isinstance(parsed, dict) and "tasks" in parsed and parsed["tasks"]:
            goal = str(parsed.get("goal", user_query)).strip()
            tasks_data = parsed["tasks"]
            task_items: list[TaskItem] = []

            for idx, item in enumerate(tasks_data, 1):
                if isinstance(item, dict):
                    tid = str(item.get("id", idx))
                    title = str(item.get("title", item.get("description", f"Task {idx}"))).strip()
                    verif = str(item.get("verification", "none")).strip().lower()
                elif isinstance(item, str):
                    tid = str(idx)
                    title = item.strip()
                    verif = "none"
                else:
                    continue

                if title:
                    task_items.append(TaskItem(id=tid, title=title, state=TaskState.PENDING, verification=verif))

            if task_items:
                return ExecutionPlan(goal=goal, tasks=task_items)

        # 2. Try numbered step extraction from model output
        numbered_steps = extract_numbered_steps(raw_text)
        if numbered_steps:
            goal = user_query.strip()
            task_items = [
                TaskItem(
                    id=step["id"],
                    title=step["title"],
                    state=TaskState.PENDING,
                    verification=step.get("verification", "none"),
                )
                for step in numbered_steps
            ]
            return ExecutionPlan(goal=goal, tasks=task_items)
    except Exception as exc:
        logger.debug("Operation error suppressed: %s", exc)

    # Dynamic query analysis fallback if model call is unreachable
    return dynamic_query_fallback_plan(user_query, workspace)


def dynamic_query_fallback_plan(query: str, workspace: Path | None = None) -> ExecutionPlan:
    """Generates an intelligent dynamic plan derived directly from the user's specific request tokens."""
    q = query.strip()
    q_clean = re.sub(r'^(please\s+|can\s+you\s+|i\s+want\s+to\s+|help\s+me\s+)', '', q, flags=re.IGNORECASE).strip()

    # Extract target file mentions if any (e.g. interface.py, src/App.tsx)
    file_matches = re.findall(r'([a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]+)', q_clean)
    target_files = [f for f in file_matches if not f.endswith(".com") and not f.endswith(".org")]

    # Normalize naming for goal (supports Spider-Man, etc.)
    goal_text = re.sub(r'\bspiderman\b', 'spider-man', q_clean, flags=re.IGNORECASE)

    is_operational = any(kw in goal_text.lower() for kw in ("download", "clone", "fetch", "get", "play", "run", "launch", "execute", "automate", "test", "inspect", "check"))

    if not is_operational and not goal_text.lower().startswith(("create", "build", "implement", "add", "fix", "refactor", "develop")):
        goal = f"Implement {goal_text[:60]}"
    else:
        goal = goal_text[:60]
    goal = goal[0].upper() + goal[1:] if goal else "Execute requested tasks"

    tasks: list[TaskItem] = []

    if is_operational:
        # Operational task milestones: Acquire -> Setup -> Execute/Play -> Verify
        tasks.append(TaskItem(id="1", title=f"Locate and acquire target resources for {goal_text[:40]}", state=TaskState.PENDING))
        tasks.append(TaskItem(id="2", title=f"Configure runtime environment and prerequisites for {goal_text[:40]}", state=TaskState.PENDING))
        tasks.append(TaskItem(id="3", title=f"Execute, run, or automate {goal_text[:40]}", state=TaskState.PENDING))
        tasks.append(TaskItem(id="4", title="Verify execution outcome and confirm completion", state=TaskState.PENDING, verification="tests"))
    else:
        # 1. Project & File Inspection
        if target_files:
            tasks.append(TaskItem(id="1", title=f"Inspect workspace and target file ({', '.join(target_files[:2])})", state=TaskState.PENDING))
        else:
            tasks.append(TaskItem(id="1", title=f"Inspect workspace and project environment for {goal_text[:40]}", state=TaskState.PENDING))

        # 2. Architecture & Design
        tasks.append(TaskItem(id="2", title=f"Design architecture and component layout for {goal_text[:45]}", state=TaskState.PENDING))

        # 3. Core Implementation
        if target_files:
            tasks.append(TaskItem(id="3", title=f"Implement core logic in {target_files[0]}", state=TaskState.PENDING))
        else:
            tasks.append(TaskItem(id="3", title=f"Implement core functionality for {goal_text[:45]}", state=TaskState.PENDING))

        # 4. Integration, Styling & Dependencies
        tasks.append(TaskItem(id="4", title=f"Configure integration, dependencies, and styling for {goal_text[:40]}", state=TaskState.PENDING))

        # 5. Verification & Testing
        tasks.append(TaskItem(id="5", title=f"Verify {goal_text[:40]} and confirm workspace integrity", state=TaskState.PENDING, verification="build"))

    return ExecutionPlan(goal=goal, tasks=tasks)
