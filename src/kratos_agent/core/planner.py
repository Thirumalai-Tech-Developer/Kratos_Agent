from __future__ import annotations

import json
import re
import sys
from typing import List, Dict, Optional, Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(highlight=False)

class PlanStep:
    def __init__(self, title: str, status: str = "pending"):
        self.title = title
        # status: "pending", "running", "completed", "failed"
        self.status = status
        self.details: Optional[str] = None

class ExecutionPlan:
    """Tracks and renders live step-by-step execution plans dynamically formulated by the Model Agent."""
    def __init__(self, title: str = "Execution Plan"):
        self.title = title
        self.steps: List[PlanStep] = []

    def set_steps(self, step_titles: List[str]):
        self.steps = [PlanStep(t, "pending") for t in step_titles if t.strip()]

    def add_step(self, title: str, status: str = "pending"):
        if title.strip():
            self.steps.append(PlanStep(title.strip(), status))

    def start_step(self, idx: int):
        if 0 <= idx < len(self.steps):
            self.steps[idx].status = "running"

    def complete_step(self, idx: int, details: Optional[str] = None):
        if 0 <= idx < len(self.steps):
            self.steps[idx].status = "completed"
            self.steps[idx].details = details

    def fail_step(self, idx: int, error: Optional[str] = None):
        if 0 <= idx < len(self.steps):
            self.steps[idx].status = "failed"
            self.steps[idx].details = error

    def render(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(width=4, justify="center")
        table.add_column(style="bold white")

        for idx, step in enumerate(self.steps, 1):
            if step.status == "completed":
                icon = "[bold green]✔[/bold green]"
                text = f"[bold green]{idx}. {step.title}[/bold green]"
            elif step.status == "running":
                icon = "[bold yellow]⚡[/bold yellow]"
                text = f"[bold yellow]{idx}. {step.title}[/bold yellow] [italic cyan](In Progress...)[/italic cyan]"
            elif step.status == "failed":
                icon = "[bold red]✖[/bold red]"
                text = f"[bold red]{idx}. {step.title}[/bold red]"
            else:
                icon = "[dim #6C7086]○[/dim #6C7086]"
                text = f"[dim #9399B2]{idx}. {step.title}[/dim #9399B2]"

            table.add_row(icon, text)
            if step.details:
                table.add_row("", f"  [dim italic]{step.details}[/dim italic]")

        return Panel(
            table,
            title=f"[bold gold1]PLAN: {self.title.upper()}[/bold gold1]",
            title_align="left",
            border_style="gold1",
            padding=(0, 2)
        )

def should_create_plan(query: str) -> bool:
    """Determines whether a user prompt warrants a multi-step execution plan."""
    q = query.strip().lower()
    
    # 1. Questions, greetings, calculations, searches NEVER need a plan
    question_starters = ("who", "what", "where", "when", "why", "how", "tell", "explain", "is", "are", "which", "hi", "hello", "search", "calculate")
    if any(q.startswith(w) for w in question_starters):
        return False

    if "search in google" in q or "google search" in q or "who is" in q or "what is" in q:
        return False

    # 2. Multi-step building/scaffolding/creation tasks DO warrant a plan
    action_keywords = ["create", "build", "scaffold", "generate website", "make a website", "make an app", "refactor", "develop"]
    return any(k in q for k in action_keywords)

def generate_dynamic_plan(query: str, brain: Optional[Any] = None) -> Optional[ExecutionPlan]:
    """Uses the LLM Model Agent to formulate a custom execution plan ONLY when needed."""
    if not should_create_plan(query):
        return None

    plan = ExecutionPlan(title="Execution Plan")
    
    # Ask the model agent to dynamically generate steps for complex tasks
    if brain and hasattr(brain, "client"):
        prompt = (
            f"You are Kratos Agent planner. Given the user query: \"{query}\"\n"
            "Formulate 3 to 5 concise, actionable execution steps to accomplish this task directly in the workspace.\n"
            "Return ONLY a valid JSON list of step title strings, with no markdown formatting.\n"
            "Example: [\"Scaffold Vite React project in workspace\", \"Configure TailwindCSS and theme\", \"Implement interactive components\", \"Verify production build\"]"
        )
        try:
            model_name = getattr(brain, "model_name", "gemini-3.6-flash-high")
            reply = brain.client.generate(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_retries=3
            )
            clean = reply.strip()
            if "```" in clean:
                clean = re.sub(r"```[a-zA-Z]*\n?", "", clean).replace("```", "").strip()
            
            match = re.search(r"\[.*?\]", clean, re.DOTALL)
            if match:
                step_list = json.loads(match.group(0))
                if isinstance(step_list, list) and step_list:
                    plan.set_steps([str(s) for s in step_list if isinstance(s, (str, int))])
                    return plan
        except Exception:
            pass

    # Fallback for action tasks
    parts = [p.strip() for p in re.split(r",|and|then|using", query, flags=re.IGNORECASE) if p.strip()]
    if len(parts) >= 2:
        steps = [f"Plan & initialize: {parts[0]}"]
        for p in parts[1:]:
            steps.append(f"Execute: {p}")
        steps.append("Verify output & compile results in workspace")
        plan.set_steps(steps)
    else:
        plan.set_steps([
            f"Initialize: {query[:50]}...",
            "Execute operations in workspace directory",
            "Verify build and finalize output"
        ])

    return plan
