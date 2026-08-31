@echo off
echo ============================================================
echo   Building Kratos Agent Standalone Executable (.exe)
echo ============================================================
uv run --with pyinstaller --with pillow python build_exe.py
pause
