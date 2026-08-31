"""Real Agent-Generated Planning Engine for Kratos Agent.

The Agent/LLM directly analyzes the user's request, workspace context, and repository
to formulate a tailored, structured execution plan before implementation begins.
No static universal 4-step templates.
"""
from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def classify_intent(query: str, history: Optional[List[Any]] = None) -> IntentKind:
    """Accurately classifies user intent to keep simple conversation clean while planning coding tasks."""
    q = query.strip().lower()

    # 1. Casual Chat / Greetings
    greetings = {"hi", "hello", "hey", "hola", "sup", "greetings", "good morning", "good evening", "how are you", "who are you"}
    if q in greetings or any(q.startswith(g + " ") or q.startswith(g + "!") or q.startswith(g + ",") for g in ("hi", "hello", "hey", "hola")):
        if len(q.split()) <= 4 and not any(k in q for k in ("create", "build", "make", "fix", "code", "write", "refactor", "add", "implement")):
            return IntentKind.CHAT

    # 2. Conceptual Questions & Knowledge Queries
    question_starters = ("what is", "what are", "who is", "who are", "why is", "why are", "how does", "how do", "can you explain", "explain what", "tell me about", "define ")
    if any(q.startswith(qs) for qs in question_starters):
        if not any(k in q for k in ("create", "build", "make", "write a", "implement", "fix", "refactor", "scaffold", "webapp", "website", "app")):
            return IntentKind.QUESTION

    # 3. Simple Code Explanation / Workspace Inspection
    if q.startswith("explain") or q.startswith("describe") or q.startswith("summarize") or q.startswith("where is") or q.startswith("find where"):
        if not any(k in q for k in ("and create", "and fix", "and refactor", "and build", "and modify", "and write")):
            return IntentKind.QUESTION

    # 3b. Basic calculation questions
    if q.startswith("add ") and any(num in q for num in ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "numbers")):
        return IntentKind.QUESTION

    # 4. Complex Multi-Step / Scaffolding / Autonomous Coding Tasks
    complex_indicators = (
        "create a webapp", "create a website", "create an app", "create a full", "build a webapp",
        "build a website", "build an app", "build a full", "scaffold", "three.js", "threejs",
        "spiderman", "spider-man", "game", "dashboard", "full stack", "fullstack", "clone", "portfolio"
    )
    if any(ind in q for ind in complex_indicators):
        return IntentKind.COMPLEX_AGENT_TASK

    # 5. Standard Coding / Refactoring / Modification Tasks
    coding_keywords = (
        "create", "build", "make", "implement", "develop", "refactor", "fix", "debug",
        "rewrite", "generate", "add a", "update", "patch", "setup", "configure", "install",
        "write a", "write", "modify", "delete", "remove", "migrate", "test"
    )
    if any(k in q for k in coding_keywords):
        return IntentKind.CODING_TASK

    # 6. File-specific Tasks
    if any(k in q for k in ("write file", "edit file", "delete file", "run test", "run build", "check file", ".py", ".ts", ".tsx", ".js", ".html", ".css", ".json")):
        return IntentKind.FILE_TASK

    # 7. Short queries or single-word inputs
    if len(q.split()) <= 3 and not any(k in q for k in ("build", "create", "make", "fix", "run")):
        return IntentKind.CHAT

    return IntentKind.CODING_TASK


def should_create_plan(query: str) -> bool:
    """Determines whether a user prompt warrants a structured multi-step execution plan."""
    intent = classify_intent(query)
    return intent.requires_plan


PLANNING_SYSTEM_PROMPT = """You are Kratos Planner, the strategic planning module for the Kratos autonomous coding agent.
Analyze the user's coding request and workspace context, then generate a tailored, realistic, multi-step execution plan.

RULES:
1. Each task MUST be specific, concrete, and directly relevant to the user's exact request (e.g. "Design Streamlit LLM interface in interface.py", "Implement theme toggle component in src/ThemeToggle.tsx").
2. Do NOT output generic, vague placeholder tasks like "Inspect project environment" or "Implement functionality and logic".
3. Order tasks sequentially: Architecture/Scaffolding -> Core Implementation -> Features/Styling/Integration -> Testing/Verification.
4. Each task should specify its appropriate `verification` type:
   - "none": Normal code editing, logic writing, or design tasks.
   - "build": Syntax check, compilation, or build verification (e.g. vite build, cargo check, tsc).
   - "tests": Unit/integration test suites (e.g. pytest, npm test).
   - "browser": Dedicated frontend browser UI verification (ONLY for Web UI projects on dedicated verification tasks).
   - For non-web tasks (Python CLI, Android, backend API, simple edits), do NOT use "browser" verification.
5. Keep the total number of tasks between 3 and 7 milestones.
6. Return ONLY a valid JSON object matching this schema:
{
  "goal": "Clear and concise summary of the goal",
  "tasks": [
    {
      "id": "1",
      "title": "Specific, actionable task title",
      "verification": "none"
    },
    {
      "id": "2",
      "title": "Specific, actionable task title",
      "verification": "build"
    },
    {
      "id": "3",
      "title": "Verify application and layout",
      "verification": "browser"
    }
  ]
}
"""


def extract_json_plan(text: str) -> Optional[Dict[str, Any]]:
    """Extracts and parses a JSON plan from raw model output or markdown code blocks."""
    if not text or not text.strip():
        return None

    cleaned = text.strip()

    # 1. Try markdown fenced code block
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced_match:
        try:
            return json.loads(fenced_match.group(1))
        except Exception:
            pass

    # 2. Try raw JSON object search
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        json_str = cleaned[first_brace : last_brace + 1]
        try:
            return json.loads(json_str)
        except Exception:
            # Try fixing common trailing comma issues
            fixed = re.sub(r",\s*([\]}])", r"\1", json_str)
            try:
                return json.loads(fixed)
            except Exception:
                pass

    return None


def formulate_agent_plan(
    user_query: str,
    model: Any,
    workspace: Path,
    instructions: Optional[List[Dict[str, str]]] = None,
) -> ExecutionPlan:
    """Invokes the Agent/LLM to understand the request, inspect the context, and produce a real dynamic plan."""
    # List top-level files in workspace to provide real context
    ws_files: List[str] = []
    try:
        if workspace.exists() and workspace.is_dir():
            for p in list(workspace.iterdir())[:20]:
                if not p.name.startswith("."):
                    ws_files.append(f"{p.name}/" if p.is_dir() else p.name)
    except Exception:
        pass

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
        parsed = extract_json_plan(raw_text)

        if parsed and isinstance(parsed, dict) and "tasks" in parsed and parsed["tasks"]:
            goal = str(parsed.get("goal", user_query)).strip()
            tasks_data = parsed["tasks"]
            task_items: List[TaskItem] = []

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
    except Exception:
        pass

    # Dynamic query analysis fallback if model call is unreachable
    return dynamic_query_fallback_plan(user_query, workspace)


def dynamic_query_fallback_plan(query: str, workspace: Optional[Path] = None) -> ExecutionPlan:
    """Generates an intelligent dynamic plan derived directly from the user's specific request tokens."""
    q = query.strip()
    q_clean = re.sub(r'^(please\s+|can\s+you\s+|i\s+want\s+to\s+|help\s+me\s+)', '', q, flags=re.IGNORECASE).strip()

    # Extract target file mentions if any (e.g. interface.py, src/App.tsx)
    file_matches = re.findall(r'([a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]+)', q_clean)
    target_files = [f for f in file_matches if not f.endswith(".com") and not f.endswith(".org")]

    # Extract technologies / frameworks mentioned
    techs = []
    for tech in ("streamlit", "react", "vite", "tailwind", "fastapi", "flask", "django", "nextjs", "vue", "docker", "three.js", "threejs", "sqlite", "postgres"):
        if tech in q.lower():
            techs.append(tech.capitalize())

    tech_str = " + ".join(techs) if techs else ""
    goal = f"Implement {q_clean[:60]}" if not q_clean.lower().startswith("implement") else q_clean[:60]

    tasks: List[TaskItem] = []

    # 1. Project & File Inspection
    if target_files:
        tasks.append(TaskItem(id="1", title=f"Inspect workspace and target file ({', '.join(target_files[:2])})", state=TaskState.PENDING))
    elif techs:
        tasks.append(TaskItem(id="1", title=f"Inspect existing project and {tech_str} environment", state=TaskState.PENDING))
    else:
        tasks.append(TaskItem(id="1", title=f"Analyze requirements for '{q_clean[:45]}'", state=TaskState.PENDING))

    # 2. Design & Architecture
    if "spiderman" in q.lower() or "spider-man" in q.lower():
        tasks.append(TaskItem(id="2", title="Design Spider-Man suit gallery and theme architecture", state=TaskState.PENDING))
        tasks.append(TaskItem(id="3", title="Implement Spider-Man interactive webapp components", state=TaskState.PENDING))
        tasks.append(TaskItem(id="4", title="Add hero section, suit controls, and responsive styling", state=TaskState.PENDING))
        tasks.append(TaskItem(id="5", title="Verify Spider-Man webapp and workspace integrity", state=TaskState.PENDING))
        return ExecutionPlan(goal="Create a Spider-Man web application", tasks=tasks)

    if "streamlit" in q.lower():
        tfile = target_files[0] if target_files else "interface.py"
        tasks.append(TaskItem(id="2", title=f"Design Streamlit LLM interface layout and state handling", state=TaskState.PENDING))
        tasks.append(TaskItem(id="3", title=f"Implement {tfile} with chat interface and client integration", state=TaskState.PENDING))
        tasks.append(TaskItem(id="4", title=f"Validate Streamlit execution and verify {tfile}", state=TaskState.PENDING))
        return ExecutionPlan(goal=f"Create Streamlit LLM interface in {tfile}", tasks=tasks)

    if "dark mode" in q.lower() or "dark theme" in q.lower():
        tasks.append(TaskItem(id="2", title="Design dark theme color palette and CSS variables", state=TaskState.PENDING))
        tasks.append(TaskItem(id="3", title="Implement ThemeToggle component and state persistence", state=TaskState.PENDING))
        tasks.append(TaskItem(id="4", title="Apply dark mode styles across application components", state=TaskState.PENDING))
        tasks.append(TaskItem(id="5", title="Verify theme switching and visual styling", state=TaskState.PENDING))
        return ExecutionPlan(goal=f"Add dark mode support", tasks=tasks)

    if "fix" in q.lower() or "bug" in q.lower() or "error" in q.lower():
        tasks.append(TaskItem(id="2", title=f"Diagnose root cause of {q_clean[:45]}", state=TaskState.PENDING))
        tasks.append(TaskItem(id="3", title=f"Apply targeted bug fix and verify changes", state=TaskState.PENDING))
        tasks.append(TaskItem(id="4", title="Run verification and regression checks", state=TaskState.PENDING))
        return ExecutionPlan(goal=f"Fix issue: {q_clean[:50]}", tasks=tasks)

    if "refactor" in q.lower() or "cleanup" in q.lower():
        tasks.append(TaskItem(id="2", title=f"Analyze code structure and modularization opportunities", state=TaskState.PENDING))
        tasks.append(TaskItem(id="3", title=f"Refactor components and optimize code flow", state=TaskState.PENDING))
        tasks.append(TaskItem(id="4", title="Verify no regressions and test workspace", state=TaskState.PENDING))
        return ExecutionPlan(goal=f"Refactor: {q_clean[:50]}", tasks=tasks)

    # General Dynamic Tasks for any request
    main_action = q_clean
    if target_files:
        tasks.append(TaskItem(id="2", title=f"Implement requested changes in {target_files[0]}", state=TaskState.PENDING))
    elif techs:
        tasks.append(TaskItem(id="2", title=f"Implement {tech_str} components and logic", state=TaskState.PENDING))
    else:
        tasks.append(TaskItem(id="2", title=f"Implement {main_action[:50]}", state=TaskState.PENDING))

    tasks.append(TaskItem(id="3", title="Configure integration, styling, and dependencies", state=TaskState.PENDING))
    tasks.append(TaskItem(id="4", title=f"Verify implementation and confirm workspace integrity", state=TaskState.PENDING))

    return ExecutionPlan(goal=goal, tasks=tasks)
