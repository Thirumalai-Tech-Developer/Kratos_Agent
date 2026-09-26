from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Sequence
from typing import Any


class TerminalExecutor:
    async def execute(
        self,
        executable: str,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        timeout: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            completed = subprocess.run(
                [executable, *list(argv)],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            return {
                "ok": completed.returncode == 0,
                "verified": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        return await asyncio.to_thread(_run)
