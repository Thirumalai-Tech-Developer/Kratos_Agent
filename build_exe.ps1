$ErrorActionPreference = "Stop"

Write-Host "Building Kratos Agent Standalone Windows Executable (.exe)..."
uv run --with pyinstaller --with pillow python (Join-Path $PSScriptRoot "build_exe.py")

