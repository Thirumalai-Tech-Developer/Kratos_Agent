# ⚔️ KRATOS AGENT

<div align="center">

```
  ██╗  ██╗██████╗   █████╗ ████████╗ ██████╗  ███████╗
  ██║ ██╔╝██╔══██╗ ██╔══██╗╚══██╔══╝██╔═══██╗ ██╔════╝
  █████╔╝ ██████╔╝ ███████║   ██║   ██║   ██║ ███████╗
  ██╔═██╗ ██╔══██╗ ██╔══██║   ██║   ██║   ██║ ╚════██║
  ██║  ██╗██║  ██║ ██║  ██║   ██║   ╚██████╔╝ ███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝  ╚══════╝
```

### *"Do not be sorry. Be better."* — Ghost of Sparta

**Autonomous Software Engineering CLI Agent with Direct Terminal Access, Claude Code Sub-Agents, Autonomous Tool Forging, and Multi-Session Agentic Memory.**

[![Python](https://img.shields.io/badge/Python-3.14%2B-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/managed%20by-uv-DE5FE9.svg)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Prompts](https://img.shields.io/badge/Claude%20Code%20Prompts-695%2B-red.svg)](https://github.com/Piebald-AI/claude-code-system-prompts)
[![Skills](https://img.shields.io/badge/Skills-148%2B-gold.svg)](#-skills-ecosystem)

</div>

---

## ⚡ Overview

**Kratos Agent** is a full-featured terminal AI engineer designed for deep developer autonomy, workspace engineering, and shell execution. It executes multi-step plans, writes full-stack applications, creates its own tools dynamically on demand, and includes the complete **Claude Code System Prompts & Sub-Agents suite** (695+ system prompts, sub-agents, data protocols, and tools).

---

## 🚀 Key Features

- 🧠 **695+ Claude Code Prompts & Sub-Agents**: Subagent workflows (Explore, Plan, Code Review, Security Review, Simplify, Summarizer) and senior engineering guidelines.
- 🗡️ **Autonomous Tool Forging**: When a capability or tool doesn't exist, Kratos automatically writes the Python implementation to `tools.py`, registers it in `tools_list.json`, and hot-reloads it in real-time.
- 📁 **Multi-Session Agentic Memory**: Isolated session storage (`.kratos/sessions/`) that tracks multi-turn conversations, tool calls, and executed commands with instant session switching (`/session`).
- ⚡ **Direct Terminal Execution**: Non-blocking terminal access with live output streaming and background server management (`dev`, `start`, `node`, `vite`).
- 🤖 **Multi-Model LLM Engine**: Seamlessly switch between `gemini-3.6-flash-high`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, and GPT models on the fly.
- 🔍 **Slash Command Hygiene**: Automatic duplicate slash normalization (`//help` → `/help`) and live autocompletion with `@file` attachment support.
- 📦 **140+ Packaged Skills**: Rich domain knowledge covering React 19, Tailwind CSS, TypeScript, Docx, PDF generation, security testing, and scientific databases.

---

## 📦 Installation & Quickstart

### 1. Clone & Sync Dependencies
```bash
# Clone the repository
git clone https://github.com/Thirumalai-Tech-Developer/Kratos_Agent.git
cd Kratos_Agent

# Sync all dependencies with uv
uv sync
```

### 2. Launch Kratos CLI
```bash
# Start the interactive terminal shell
uv run kratos-agent

# Or execute a direct query
uv run kratos-agent "Create a full-stack React and Vite application with Three.js"
```

---

## 🔑 Authentication & Configuration

Kratos Agent supports two authentication mechanisms: **Multi-Account OAuth Pool (`accounts.json`)** and **Environment Variables (`.env`)**.

### 1. Multi-Account Pool (`accounts.json`)
Create an `accounts.json` in the root directory. Kratos automatically rotates across accounts on rate limits (`HTTP 429` / `401`):

```json
{
  "accounts": [
    {
      "name": "primary_account",
      "email": "developer@example.com",
      "access_token": "ya29.a0AdMD6...",
      "refresh_token": "1//03-IfXeay...",
      "expires_at": "1787545667",
      "project_id": "your-google-project-id",
      "token_type": "Bearer",
      "auth_method": "oauth",
      "provider": "agy"
    },
    {
      "name": "backup_account",
      "email": "backup@example.com",
      "access_token": "ya29.a0AdMD7...",
      "refresh_token": "1//03-IfXeaz...",
      "expires_at": "1787545667",
      "project_id": "your-google-project-id",
      "token_type": "Bearer",
      "auth_method": "oauth",
      "provider": "agy"
    }
  ]
}
```

#### Key Fields:
- `access_token` & `refresh_token`: OAuth credentials for Antigravity / Gemini Cloud Code endpoint.
- `project_id`: Google Cloud project identifier.
- `_rate_limit_until`: Timestamp automatically set by Kratos when an account is temporarily on cooldown.

### 2. Environment Variables (`.env`)
Alternatively, provide direct Gemini or custom gateway API keys in `.env`:

```env
# Google / Gemini API Keys
GEMINI_API_KEY="AIzaSy..."

# Default Model Selection
KRATOS_MODEL="gemini-3.6-flash-high"
```

---

## 📜 CLI Slash Commands Reference

| Command | Description |
| :--- | :--- |
| `/session [list\|new\|load\|show\|rm]` | Manage isolated agentic memory sessions |
| `/model [name]` | Switch LLM with ↑/↓ arrow keys or name |
| `/prompts [query]` | Search and view 695+ Claude Code system prompts |
| `/review [target]` | Run senior 5-angle code review on recent changes |
| `/simplify [target]` | Run 4-angle code cleanup, deduplication & refactor sweep |
| `/security [target]` | Run high-confidence vulnerability & exploit audit |
| `/skill [add\|list\|show\|rm]` | Add or manage skills from URL or Internet |
| `/create-tool [desc]` | Autonomously forge and hot-reload a new tool |
| `/tools` | Inspect all active and self-created tools |
| `/compact` | Compress conversation history & optimize tokens |
| `/reload` (or `/r`) | Live hot-reload all source code, tools & skills |
| `/memory` | View persistent agentic memory & executed commands |
| `/accounts` | View configured accounts and key pools |
| `/health` | Check in-process engine & pool status |
| `/reset` | Reset multi-turn conversation memory |
| `/clear` | Clear terminal screen |
| `/help` | Show commands reference overview |
| `/exit` (or `/quit`) | Exit Kratos Agent |

---

## 🏗️ Architecture Layout

```
Kratos_Agent/
├── .kratos/
│   ├── claude_code_prompts/    # 695+ Indexed Claude Code Prompts & Subagents
│   ├── sessions/               # Multi-Session Agentic Memory Files
│   └── skills/                 # Packaged Skills (Review, Simplify, Security, etc.)
├── src/
│   └── kratos_agent/
│       ├── antigravity/        # Antigravity LLM Client & Multi-Key Pool
│       │   ├── accounts.py     # Multi-Account Token Manager
│       │   ├── chat_model.py   # LangChain Chat Model Binding
│       │   ├── client.py       # CloudCode Antigravity Client
│       │   └── gemini_direct.py # Direct Gemini API Key Pool
│       ├── core/
│       │   ├── memory.py       # Multi-Session Memory Engine
│       │   ├── prompt_library.py # 695+ Prompts Indexer & Search Engine
│       │   ├── planner.py      # Dynamic Step Execution Planner
│       │   ├── skills.py       # Skills Manager & YAML Parser
│       │   ├── compactor.py    # Conversation Context Compressor
│       │   └── reloader.py     # Live Code & Tool Reloader
│       ├── utils/
│       │   ├── tools.py        # Core Tools (write_file, terminal, search, etc.)
│       │   ├── tools_list.json # Tools Manifest
│       │   └── tool_creator.py # Autonomous Tool Forger & Synthesizer
│       ├── cli.py              # Interactive prompt_toolkit Terminal Shell
│       └── main.py             # Runtime Orchestrator & CLI Entry Point
├── pyproject.toml              # Project Config & Dependencies
└── README.md
```

---

## 🛡️ License

This project is licensed under the MIT License.
