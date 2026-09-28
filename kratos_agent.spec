# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

workspace_dir = os.path.abspath(SPECPATH)
src_dir = os.path.join(workspace_dir, "src")

# Data files collection
datas = [
    (os.path.join(src_dir, "kratos_agent", "utils", "tools_list.json"), "kratos_agent/utils"),
]

# Include the application banner when available.
for optional_file, dest in [
    ("kratos_banner.png", "."),
]:
    p = os.path.join(workspace_dir, optional_file)
    if os.path.exists(p):
        datas.append((p, dest))

hidden_imports = [
    "dotenv",
    "rich",
    "rich.console",
    "rich.panel",
    "rich.markdown",
    "rich.table",
    "rich.text",
    "rich.syntax",
    "prompt_toolkit",
    "prompt_toolkit.styles",
    "prompt_toolkit.formatted_text",
    "prompt_toolkit.completion",
    "prompt_toolkit.application",
    "prompt_toolkit.key_binding",
    "prompt_toolkit.layout",
    "kratos_agent",
    "kratos_agent.main",
    "kratos_agent.cli",
    "kratos_agent.brain",
    "kratos_agent.brain.config",
    "kratos_agent.brain.client",
    "kratos_agent.brain.tool_calls",
    "kratos_agent.brain.brain",
    "kratos_agent.sdk",
    "kratos_agent.sdk.client",
    "kratos_agent.sdk.agent",
    "kratos_agent.core",
    "kratos_agent.core.agent_loop",
    "kratos_agent.core.approval_mode",
    "kratos_agent.core.compactor",
    "kratos_agent.core.context_pipeline",
    "kratos_agent.core.event_store",
    "kratos_agent.core.git_tools",
    "kratos_agent.core.hooks",
    "kratos_agent.core.instruction_engine",
    "kratos_agent.core.mcp_runtime",
    "kratos_agent.core.memory",
    "kratos_agent.core.model_adapter",
    "kratos_agent.core.planner",
    "kratos_agent.core.project_memory",
    "kratos_agent.core.prompt_library",
    "kratos_agent.core.risk_policy",
    "kratos_agent.core.reloader",
    "kratos_agent.core.runtime_contracts",
    "kratos_agent.core.skills",
    "kratos_agent.core.subagents",
    "kratos_agent.core.tool_runtime",
    "kratos_agent.core.verification_manager",
    "kratos_agent.output.speech_directives",
    "kratos_agent.live.config",
    "kratos_agent.live.runtime",
    "kratos_agent.live.session",
    "kratos_agent.live.vision",
    "kratos_agent.computer.browser.playwright",
    "kratos_agent.computer.gui.backends.coordinate",
    "kratos_agent.utils",
    "kratos_agent.utils.step_tracker",
    "kratos_agent.utils.tool_creator",
    "kratos_agent.utils.tools",
    "ddgs",
    "fastapi",
    "uvicorn",
    "requests",
    "google.genai",
    "mcp",
    "mss",
    "comtypes",
    "pynput",
    "pyautogui",
]

icon_path = os.path.join(workspace_dir, "kratos.ico")
if not os.path.exists(icon_path):
    icon_path = None

a = Analysis(
    [os.path.join(workspace_dir, "kratos_entry.py")],
    pathex=[src_dir, workspace_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "notebook", "ipython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="kratos-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
