from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import json
import re
import shutil
import urllib
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console(highlight=False)

DEFAULT_SKILLS_DIR = Path.cwd() / ".kratos" / "skills"

class Skill:
    def __init__(self, name: str, description: str, path: Path, content: str = "", tags: list[str] | None = None, source_url: str | None = None):
        self.name = name
        self.description = description
        self.path = path
        self.content = content
        self.tags = tags or []
        self.source_url = source_url

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "tags": self.tags,
            "source_url": self.source_url
        }

class SkillManager:
    """Manages discovery, installation, internet fetching, and prompt injection of Kratos Skills."""
    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or DEFAULT_SKILLS_DIR
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.skills_dir.parent.parent.resolve()
        self.extra_roots: list[Path] = []
        self.source_config = self.skills_dir / "sources.json"
        self._load_extra_roots()
        self.skills: dict[str, Skill] = {}
        self.load_skills()

    def set_workspace(self, workspace: Path) -> None:
        """Point workspace skill discovery at the active project, not the launch directory."""
        self.workspace = workspace.resolve()
        self.skills_dir = self.workspace / ".kratos" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.source_config = self.skills_dir / "sources.json"
        self._load_extra_roots()
        self.load_skills()

    def _load_extra_roots(self) -> None:
        self.extra_roots = []
        if not self.source_config.exists():
            return
        try:
            values = json.loads(self.source_config.read_text(encoding="utf-8")).get("roots", [])
            self.extra_roots = [Path(value).expanduser().resolve() for value in values if isinstance(value, str)]
        except (OSError, ValueError, TypeError):
            self.extra_roots = []

    def skill_roots(self) -> list[Path]:
        """Return local Kratos, agent-skill, and workspace skill locations."""
        home = Path.home()
        roots = [
            self.skills_dir,
            self.workspace / ".agents" / "skills",
            self.workspace / ".codex" / "skills",
            self.workspace / "skills",
            home / ".agents" / "skills",
            home / ".codex" / "skills",
            *self.extra_roots,
        ]
        unique: list[Path] = []
        seen = set()
        for root in roots:
            resolved = root.resolve()
            if resolved not in seen:
                unique.append(resolved)
                seen.add(resolved)
        return unique

    def add_source_root(self, path: Path | str) -> int:
        """Import a framework skill root or plugin bundle without copying its files."""
        root = Path(path).expanduser().resolve()
        if root.is_file() and root.name.lower() == "skill.md":
            root = root.parent
        if not root.is_dir():
            raise FileNotFoundError(f"Skill source folder not found: {root}")
        candidate_roots = []
        for child in (root / "skills", root / "commands"):
            if child.is_dir():
                candidate_roots.append(child.resolve())
        if not candidate_roots:
            candidate_roots.append(root)
        found = []
        for candidate in candidate_roots:
            found.extend(folder for folder in candidate.iterdir() if folder.is_dir() and (folder / "SKILL.md").is_file())
            if (candidate / "SKILL.md").is_file():
                found.append(candidate)
            if candidate.name == "commands":
                found.extend(candidate.glob("*.md"))
        if not found:
            raise ValueError(f"No skill or instruction Markdown files found under {root}")
        for candidate in candidate_roots:
            if candidate not in self.extra_roots:
                self.extra_roots.append(candidate)
        if candidate_roots:
            self.source_config.parent.mkdir(parents=True, exist_ok=True)
            self.source_config.write_text(json.dumps({"roots": [str(item) for item in self.extra_roots]}, indent=2), encoding="utf-8")
        self.load_skills()
        return len(found)

    def load_skills(self) -> dict[str, Skill]:
        """Loads all installed skills from the skills directory."""
        self.skills = {}
        for root in self.skill_roots():
            if not root.is_dir():
                continue
            folders = [item for item in root.iterdir() if item.is_dir()]
            if (root / "SKILL.md").is_file():
                folders.append(root)
            for item in folders:
                skill_md = item / "SKILL.md"
                if skill_md.is_file():
                    try:
                        text = skill_md.read_text(encoding="utf-8", errors="replace")
                        name, desc, tags, source_url, body = self._parse_skill_md(item.name, text)
                        skill_obj = Skill(
                            name=name,
                            description=desc,
                            path=item,
                            content=body,
                            tags=tags,
                            source_url=source_url
                        )
                        # Earlier roots have higher priority (managed, workspace, then user).
                        if name.lower() not in self.skills:
                            self.skills[name.lower()] = skill_obj
                        if item.name.lower() not in self.skills:
                            self.skills[item.name.lower()] = skill_obj
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)
            if root.name == "commands":
                for command_file in sorted(root.glob("*.md"), key=lambda path: path.name.lower()):
                    try:
                        raw = command_file.read_text(encoding="utf-8", errors="replace")
                        name, desc, tags, source_url, body = self._parse_skill_md(command_file.stem, raw)
                        command = Skill(name=name, description=desc, path=command_file, content=body or raw, tags=tags, source_url=source_url)
                        if name.lower() not in self.skills:
                            self.skills[name.lower()] = command
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)
        return self.skills

    def _parse_skill_md(self, default_name: str, raw_text: str) -> tuple[str, str, list[str], str | None, str]:
        """Parses YAML frontmatter and body from SKILL.md."""
        name = default_name
        description = f"Skill {default_name}"
        tags = []
        source_url = None
        body = raw_text

        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw_text, re.DOTALL)
        if frontmatter_match:
            fm_text = frontmatter_match.group(1)
            body = frontmatter_match.group(2).strip()

            for line in fm_text.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().lower()
                    val = val.strip().strip("'\"")
                    if key == "name":
                        name = val
                    elif key in ("description", "desc"):
                        description = val
                    elif key == "tags":
                        tags = [t.strip() for t in val.split(",") if t.strip()]
                    elif key in ("url", "source", "source_url"):
                        source_url = val
        else:
            # Try to extract first heading as description
            lines = raw_text.splitlines()
            if lines and lines[0].startswith("#"):
                name = lines[0].lstrip("#").strip()
            for line in lines[1:5]:
                if line.strip() and not line.startswith("#"):
                    description = line.strip()
                    break

        return name, description, tags, source_url, body

    def add_skill_from_url(self, url: str, brain: Any | None = None) -> list[Skill]:
        """Downloads, parses, and installs skills from a remote URL or Git repository."""
        # 1. Handle Git Repositories (e.g. https://github.com/anthropics/skills.git)
        if url.endswith(".git") or ("github.com/" in url and "/raw/" not in url and not url.endswith(".md")):
            import subprocess
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="kratos_repo_"))
            try:
                console.print(f"[bold yellow]⚡ [Cloning Skill Repository][/bold yellow] [bold cyan]{url}[/bold cyan]")
                res = subprocess.run(
                    ["git", "clone", "--depth", "1", url, str(temp_dir)],
                    shell=False,
                    capture_output=True,
                    text=True
                )
                if res.returncode != 0:
                    console.print(f"[bold red]Git clone failed:[/bold red] {res.stderr}")

                # Discover all SKILL.md files in repository
                installed = []
                for skill_file in temp_dir.rglob("SKILL.md"):
                    skill_folder_name = skill_file.parent.name
                    target_dest = self.skills_dir / skill_folder_name.lower()
                    if target_dest.exists():
                        shutil.rmtree(target_dest)
                    shutil.copytree(skill_file.parent, target_dest)
                    installed.append(skill_folder_name.lower())

                # If no SKILL.md found, check for README.md as fallback
                if not installed:
                    for readme_file in temp_dir.glob("README*.md"):
                        skill_folder_name = temp_dir.name
                        target_dest = self.skills_dir / skill_folder_name.lower()
                        target_dest.mkdir(parents=True, exist_ok=True)
                        shutil.copy(readme_file, target_dest / "SKILL.md")
                        installed.append(skill_folder_name.lower())

                self.load_skills()
                result_skills = [self.skills[k] for k in installed if k in self.skills]
                return result_skills if result_skills else [Skill(name=url.split("/")[-1], description="Git Repo Skills", path=self.skills_dir)]
            finally:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

        # 2. Handle Single File / Markdown URLs
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KratosAgent/1.0"}
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_data = resp.read().decode("utf-8", errors="replace")

        # Determine skill name from URL
        parsed_url = urllib.parse.urlparse(url)
        path_slug = parsed_url.path.strip("/").split("/")[-1].replace(".md", "").replace(".txt", "")
        if path_slug.lower() in ("skill", "raw", "main", "master") and len(parsed_url.path.strip("/").split("/")) > 1:
            path_slug = parsed_url.path.strip("/").split("/")[-2]

        skill_name = re.sub(r"[^a-zA-Z0-9_-]", "-", path_slug).strip("-") or "custom-skill"

        name, desc, tags, _, body = self._parse_skill_md(skill_name, raw_data)

        # Save skill folder and file
        target_folder = self.skills_dir / skill_name.lower()
        target_folder.mkdir(parents=True, exist_ok=True)

        skill_file_content = f"""---
name: {name}
description: {desc}
tags: {', '.join(tags) if tags else 'web, custom'}
source_url: {url}
---

{body}
"""
        (target_folder / "SKILL.md").write_text(skill_file_content, encoding="utf-8")
        self.load_skills()
        skill_obj = self.skills.get(skill_name.lower()) or self.skills.get(name.lower()) or Skill(name=name, description=desc, path=target_folder, content=body, tags=tags, source_url=url)
        return [skill_obj]

    def add_skill_from_internet(self, query: str, brain: Any) -> Skill:
        """Searches the web for the requested skill/technology and synthesizes a comprehensive SKILL.md."""
        console.print(f"[bold yellow]🔍 [Searching Web for Skill Knowledge][/bold yellow] [bold cyan]{query}[/bold cyan]")

        # 1. Search web documentation
        search_results = ""
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(f"{query} best practices documentation guide cheat sheet", max_results=4))
                if results:
                    search_results = "\n\n".join([f"[{r.get('title')}]\n{r.get('body')}\nURL: {r.get('href')}" for r in results])
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

        # 2. Ask Model to forge comprehensive SKILL.md
        prompt = (
            f"You are the Kratos Skill Forge. Create an expert-level, actionable Skill Guide (SKILL.md) for: \"{query}\".\n\n"
            f"Web Research Snippets:\n{search_results}\n\n"
            "Format your output with YAML frontmatter followed by structured Markdown guidelines.\n"
            "Include:\n"
            "1. Core Principles & Architecture\n"
            "2. Best Practices & Design Patterns\n"
            "3. Common Commands, Syntax & Code Templates\n"
            "4. Critical Gotchas and Performance Tips\n\n"
            "Example format:\n"
            "---\n"
            f"name: {re.sub(r'[^a-zA-Z0-9_-]', '-', query).lower()}\n"
            f"description: Comprehensive expert guidelines and cheatsheet for {query}\n"
            "tags: documentation, expert, guide\n"
            "---\n\n"
            f"# {query.title()} Expert Skill Guide\n\n"
            "..."
        )

        model_name = getattr(brain, "model_name", "auto/best-free")
        client = getattr(brain, "client", None)
        if not client:
            from kratos_agent.brain.client import BrainClient
            client = BrainClient()

        reply = client.generate(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            max_retries=3
        )

        clean_content = reply.strip()
        if clean_content.startswith("```markdown"):
            clean_content = clean_content[11:].strip()
        elif clean_content.startswith("```"):
            clean_content = clean_content[3:].strip()
        if clean_content.endswith("```"):
            clean_content = clean_content[:-3].strip()

        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", query.lower()).strip("-") or "new-skill"
        target_folder = self.skills_dir / slug
        target_folder.mkdir(parents=True, exist_ok=True)

        name, desc, tags, _, body = self._parse_skill_md(slug, clean_content)

        final_file_text = f"""---
name: {name}
description: {desc}
tags: {', '.join(tags) if tags else 'custom, guide'}
source_url: search:{query}
---

{body}
"""
        (target_folder / "SKILL.md").write_text(final_file_text, encoding="utf-8")
        self.load_skills()
        return self.skills.get(slug) or self.skills.get(name.lower()) or Skill(name=name, description=desc, path=target_folder, content=body, tags=tags, source_url=f"search:{query}")

    def remove_skill(self, name: str) -> bool:
        """Removes an installed skill by name or slug."""
        target = self.skills_dir / name.lower()
        if target.exists() and target.is_dir():
            shutil.rmtree(target)
            self.load_skills()
            return True
        return False

    def get_all_skills_prompt(self, query: str = "") -> str:
        """Generates a compact system prompt summary of relevant active skills (capped to prevent prompt bloat)."""
        if not self.skills:
            return ""

        unique_skills = list({str(s.path): s for s in self.skills.values()}.values())

        # Prefer skills whose names, descriptions, or tags match the active task.
        # Stable tie-breaking keeps the injected catalog predictable across launches.
        q_words = set(re.findall(r'\w+', query.lower())) if query else set()
        scored = []
        for skill in unique_skills:
            corpus = set(re.findall(
                r'\w+',
                f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower(),
            ))
            score = sum(1 for word in q_words if word in corpus)
            scored.append((score, skill.name.lower(), skill))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [skill for _, _, skill in scored[:12]]

        parts = ["\nACTIVE AGENT SKILLS:"]
        for s in selected:
            desc = s.description[:80] + "…" if len(s.description) > 80 else s.description
            parts.append(f"- `{s.name}`: {desc}")

        return "\n".join(parts) + "\n"

# Singleton instance
skill_manager = SkillManager()
