@echo off
setlocal
pushd "%~dp0"
echo ============================================================
echo   Building Kratos Agent Standalone Executable (.exe)
echo ============================================================
uv run --project "%~dp0" --extra build python build_exe.py
set "build_status=%ERRORLEVEL%"
popd
pause
exit /b %build_status%
