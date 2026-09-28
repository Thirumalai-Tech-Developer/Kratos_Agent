$ErrorActionPreference = "Stop"

Write-Host "Building Kratos Agent Standalone Windows Executable (.exe)..."
uv run --project $PSScriptRoot --extra build python (Join-Path $PSScriptRoot "build_exe.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

