from __future__ import annotations

import os
import re
import json
import shutil
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

console = Console(highlight=False)

DEFAULT_SKILLS_DIR = Path.cwd() / ".kratos" / "skills"

class Skill:
    def __init__(self, name: str, description: str, path: Path, content: str = "", tags: Optional[List[str]] = None, source_url: Optional[str] = None):
        self.name = name
        self.description = description
        self.path = path
        self.content = content
        self.tags = tags or []
        self.source_url = source_url

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "tags": self.tags,
            "source_url": self.source_url
        }

class SkillManager:
    """Manages discovery, installation, internet fetching, and prompt injection of Kratos Skills."""
    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or DEFAULT_SKILLS_DIR
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills: Dict[str, Skill] = {}
        self.load_skills()

    def load_skills(self) -> Dict[str, Skill]:
        """Loads all installed skills from the skills directory."""
        self.skills = {}
        if not self.skills_dir.exists():
            return self.skills

        for item in self.skills_dir.iterdir():
            if item.is_dir():
                skill_md = item / "SKILL.md"
                if skill_md.exists():
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
                        # Index by directory folder name and parsed name
                        self.skills[item.name.lower()] = skill_obj
                        self.skills[name.lower()] = skill_obj
                    except Exception:
                        pass
        return self.skills

    def _parse_skill_md(self, default_name: str, raw_text: str) -> Tuple[str, str, List[str], Optional[str], str]:
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

    def add_skill_from_url(self, url: str, brain: Optional[Any] = None) -> List[Skill]:
        """Downloads, parses, and installs skills from a remote URL or Git repository."""
        # 1. Handle Git Repositories (e.g. https://github.com/anthropics/skills.git)
        if url.endswith(".git") or ("github.com/" in url and "/raw/" not in url and not url.endswith(".md")):
            import subprocess
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="kratos_repo_"))
            try:
                console.print(f"[bold yellow]⚡ [Cloning Skill Repository][/bold yellow] [bold cyan]{url}[/bold cyan]")
                res = subprocess.run(
                    f"git clone --depth 1 {url} \"{temp_dir}\"",
                    shell=True,
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
                except Exception:
                    pass

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
        except Exception:
            pass

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

        model_name = getattr(brain, "model_name", "gemini-3.6-flash-high")
        client = getattr(brain, "client", None)
        if not client:
            from kratos_agent.antigravity.client import AntigravityClient
            client = AntigravityClient()

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

    def get_all_skills_prompt(self) -> str:
        """Generates a compact system prompt summary of all active skills."""
        if not self.skills:
            return ""

        parts = ["\nACTIVE AGENT SKILLS & SPECIALIZED DOMAIN KNOWLEDGE:"]
        for s in self.skills.values():
            parts.append(f"- **{s.name}**: {s.description}")
            # Include brief summary of instructions if available
            brief = "\n".join([line for line in s.content.splitlines() if line.startswith("#") or line.startswith("-")][:6])
            if brief:
                parts.append(f"  Instructions:\n  {brief}")

        return "\n".join(parts) + "\n"

# Singleton instance
skill_manager = SkillManager()
