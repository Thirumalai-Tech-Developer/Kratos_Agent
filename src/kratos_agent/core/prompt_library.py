from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

DEFAULT_PROMPTS_DIR = Path.cwd() / ".kratos" / "claude_code_prompts"

class ClaudePrompt:
    def __init__(self, filename: str, path: Path, title: str, description: str, category: str, content: str, token_count: Optional[int] = None):
        self.filename = filename
        self.path = path
        self.title = title
        self.description = description
        self.category = category
        self.content = content
        self.token_count = token_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "token_count": self.token_count,
            "path": str(self.path)
        }

class PromptLibrary:
    """Indexes, parses, and provides access to all 515+ Claude Code system prompts, subagents, and tools."""
    
    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR
        self.prompts: Dict[str, ClaudePrompt] = {}
        self.categories: Dict[str, List[ClaudePrompt]] = {
            "agent": [],
            "system": [],
            "data": [],
            "skill": [],
            "tool": [],
            "reminder": []
        }
        self.load_prompts()

    def load_prompts(self):
        """Discovers and parses all markdown prompt files from the prompts directory."""
        self.prompts = {}
        for cat in self.categories:
            self.categories[cat] = []

        if not self.prompts_dir.exists():
            return

        sys_prompts_dir = self.prompts_dir / "system-prompts"
        target_dirs = [sys_prompts_dir] if sys_prompts_dir.exists() else [self.prompts_dir]

        for base_dir in target_dirs:
            if not base_dir.exists():
                continue
            for md_file in base_dir.glob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8", errors="replace")
                    title, desc, cat, body, tks = self._parse_prompt_file(md_file.name, text)
                    prompt_obj = ClaudePrompt(
                        filename=md_file.name,
                        path=md_file,
                        title=title,
                        description=desc,
                        category=cat,
                        content=body,
                        token_count=tks
                    )
                    
                    key = md_file.stem.lower()
                    self.prompts[key] = prompt_obj
                    if cat in self.categories:
                        self.categories[cat].append(prompt_obj)
                    else:
                        self.categories.setdefault(cat, []).append(prompt_obj)
                except Exception:
                    pass

    def _parse_prompt_file(self, filename: str, text: str) -> Tuple[str, str, str, str, Optional[int]]:
        """Parses HTML comment frontmatter and markdown body from a prompt file."""
        title = filename.replace(".md", "").replace("-", " ").title()
        description = "Claude Code prompt component"
        category = "system"
        body = text
        token_count = None

        if filename.startswith("agent-prompt-"):
            category = "agent"
        elif filename.startswith("data-"):
            category = "data"
        elif filename.startswith("skill-"):
            category = "skill"
        elif filename.startswith("tool-description-") or filename.startswith("tool-parameter-"):
            category = "tool"
        elif filename.startswith("system-reminder-"):
            category = "reminder"
        elif filename.startswith("system-prompt-"):
            category = "system"

        # Check for HTML comment frontmatter
        comment_match = re.match(r"^<!--\s*(.*?)\s*-->\s*\n(.*)$", text, re.DOTALL)
        if comment_match:
            fm_text = comment_match.group(1)
            body = comment_match.group(2).strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    v = v.strip().strip("'\"")
                    if k == "name":
                        title = v
                    elif k in ("description", "desc"):
                        description = v
                    elif k in ("tokens", "tokencount", "token_count"):
                        try:
                            token_count = int(v)
                        except ValueError:
                            pass

        return title, description, category, body, token_count

    def get_prompt(self, name: str) -> Optional[ClaudePrompt]:
        """Retrieves a prompt by key, filename, or partial match."""
        cleaned = name.lower().replace(".md", "").strip()
        if cleaned in self.prompts:
            return self.prompts[cleaned]
        
        # Try finding prefix
        for key, p in self.prompts.items():
            if cleaned in key or cleaned in p.title.lower():
                return p
        return None

    def search_prompts(self, query: str, limit: int = 15) -> List[ClaudePrompt]:
        """Performs full-text and metadata search across all indexed prompts."""
        q = query.lower().strip()
        if not q:
            return list(self.prompts.values())[:limit]

        results = []
        for key, prompt in self.prompts.items():
            score = 0
            if q in prompt.title.lower():
                score += 10
            if q in prompt.description.lower():
                score += 5
            if q in key:
                score += 7
            if q in prompt.content.lower():
                score += 2
            
            if score > 0:
                results.append((score, prompt))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def get_subagent_prompt(self, agent_name: str) -> str:
        """Retrieves specialized subagent instructions for standard workflows."""
        key_map = {
            "explore": "agent-prompt-explore",
            "plan": "agent-prompt-plan-mode-enhanced",
            "general": "agent-prompt-general-purpose",
            "code_review": "agent-prompt-code-review-minimal-mode",
            "code-review": "agent-prompt-code-review-minimal-mode",
            "review": "agent-prompt-code-review-minimal-mode",
            "security": "agent-prompt-security-review-slash-command",
            "security_review": "agent-prompt-security-review-slash-command",
            "simplify": "agent-prompt-simplify-slash-command",
            "summarize": "agent-prompt-conversation-summarization",
            "debugger": "skill-debugging",
            "debug": "skill-debugging"
        }

        target_key = key_map.get(agent_name.lower().strip(), agent_name.lower().strip())
        prompt = self.get_prompt(target_key)
        if prompt:
            return prompt.content
        return ""

    def get_engineering_guidelines(self) -> str:
        """Constructs a consolidated, high-fidelity software engineering instruction prompt from Claude Code rules."""
        keys = [
            "system-prompt-doing-tasks-software-engineering-focus",
            "system-prompt-doing-tasks-security",
            "system-prompt-doing-tasks-no-unnecessary-additions",
            "system-prompt-doing-tasks-no-compatibility-hacks",
            "system-prompt-doing-tasks-no-unnecessary-error-handling",
            "system-prompt-prefer-editing-existing-files",
            "system-prompt-outcome-first-communication-style",
            "system-prompt-tone-and-style-code-references",
            "system-prompt-executing-actions-with-care",
            "system-prompt-action-safety-and-truthful-reporting"
        ]

        sections = []
        for k in keys:
            p = self.get_prompt(k)
            if p and p.content:
                # Clean template variables like ${...}
                cleaned_content = re.sub(r'\$\{[^}]*\}', '', p.content).strip()
                if cleaned_content:
                    sections.append(f"### {p.title}\n{cleaned_content}")

        if not sections:
            return """### Software Engineering Principles
- Lead with outcomes and deliver complete, working code.
- Read files before modifying and prefer editing existing files over creating duplicates.
- Avoid unnecessary compatibility hacks, speculative error wrappers, or unsolicited code scaffolding.
- Reference code with exact file paths and line numbers (`file:line`).
- Execute all actions carefully and verify changes with terminal checks before concluding."""

        return "\n\n".join(sections)

# Global prompt library singleton
prompt_library = PromptLibrary()
