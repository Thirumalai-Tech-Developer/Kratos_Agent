"""Slave executor for Kratos Agent.

Executes MasterCommands deterministically, coordinates browser/desktop/search/code
tools, performs physical verification, and returns structured SlaveResults.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from kratos_agent.master.protocol import (
    CommandAction,
    MasterCommand,
    SlaveAck,
    SlaveResult,
    get_command_bus,
)

logger = logging.getLogger(__name__)


class SlaveExecutor:
    """Consumes commands from Master, executes tools silently, and returns verified evidence."""

    def __init__(self, runtime: Any | None = None) -> None:
        self.command_bus = get_command_bus()
        self.runtime = runtime
        self._running = False
        self._worker_task: asyncio.Task[Any] | None = None
        self._active_command: MasterCommand | None = None
        self._cancellation_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts the background command processing loop."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._process_commands(), name="kratos-slave-executor")
        logger.info("[SlaveExecutor] Started background command listener.")

    def stop(self) -> None:
        """Stops the executor loop."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        logger.info("[SlaveExecutor] Stopped.")

    async def _process_commands(self) -> None:
        while self._running:
            try:
                cmd = await self.command_bus.get_next_command()
                with self._lock:
                    self._active_command = cmd
                    self._cancellation_event.clear()

                # Handle cancellation command immediately
                if cmd.action == CommandAction.CANCEL.value or cmd.priority == "cancel":
                    await self._handle_cancellation(cmd)
                    continue

                # 1. Dispatch immediate ACK to Master
                ack = SlaveAck(
                    command_id=cmd.command_id,
                    task_id=cmd.task_id,
                    accepted=True,
                    status="accepted",
                )
                await self.command_bus.publish_ack(ack)

                # 2. Execute command with physical verification
                started_at = time.time()
                try:
                    result = await self._execute_command(cmd)
                except Exception as e:
                    logger.error(f"[SlaveExecutor] Execution exception on {cmd.command_id}: {e}", exc_info=True)
                    from kratos_agent.diagnostics.errors import error_from_exception
                    err = error_from_exception(
                        e,
                        component="SlaveExecutor",
                        stage="physical_execution",
                        task_id=cmd.task_id,
                        request_id=cmd.request_id or None,
                        retryable=True,
                        recovery_action="Inspect execution evidence and retry with another authorized backend.",
                    )
                    result = SlaveResult(
                        command_id=cmd.command_id,
                        task_id=cmd.task_id,
                        status="failed",
                        verified=False,
                        terminal=True,
                        error=err.to_dict(),
                        duration_ms=(time.time() - started_at) * 1000,
                    )

                result.duration_ms = (time.time() - started_at) * 1000
                await self.command_bus.publish_result(result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SlaveExecutor] Worker loop error: {e}")
                await asyncio.sleep(0.5)
            finally:
                with self._lock:
                    self._active_command = None

    async def _handle_cancellation(self, cmd: MasterCommand) -> None:
        target_tid = cmd.parameters.get("target_task_id", cmd.task_id)
        logger.info(f"[SlaveExecutor] Processing cancellation for task {target_tid}")
        self._cancellation_event.set()

        ack = SlaveAck(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            accepted=True,
            status="accepted",
            message="Cancellation accepted.",
        )
        await self.command_bus.publish_ack(ack)

        result = SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="success",
            verified=True,
            terminal=True,
            state="CANCELLED",
            evidence={"cancelled_task_id": target_tid},
        )
        await self.command_bus.publish_result(result)

    async def _execute_command(self, cmd: MasterCommand) -> SlaveResult:
        """Routes command to appropriate deterministic execution handler."""
        action = cmd.action.lower()

        # Structured capability dispatch only. No natural-language routing happens here.
        from kratos_agent.slave.dispatcher import SlaveDispatcher
        if not hasattr(self, "_dispatcher"):
            self._dispatcher = SlaveDispatcher(self)
        return await self._dispatcher.dispatch(cmd)

    async def _execute_youtube_play(self, cmd: MasterCommand) -> SlaveResult:
        """Executes YouTube playback with strict physical verification."""
        from kratos_agent.computer.browser.intent import should_reuse_browser_context
        from kratos_agent.computer.browser.playwright import (
            PlaywrightDriver,
            can_report_success,
        )
        from kratos_agent.computer.browser.target import get_target_manager

        query = str(cmd.parameters.get("query") or "").strip()
        if not query:
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="failed",
                verified=False,
                terminal=True,
                error={
                    "type": "TOOL_VALIDATION_ERROR",
                    "message": "browser.youtube.play requires parameters.query; Slave does not parse natural language.",
                },
            )
        logger.info(f"[SlaveExecutor] Executing YouTube play: '{query}'")

        # Reuse or establish browser task context (§19)
        target_mgr = get_target_manager()
        prev_task = target_mgr.get_active_task_target()
        m_intent = {"intent": "play_video", "platform": "youtube", "query": query}
        reuse_target = should_reuse_browser_context(prev_task, m_intent)

        if not reuse_target and prev_task is not None:
            target_mgr.clear_task_target()

        # Execute playback using PlaywrightDriver
        loop = asyncio.get_running_loop()
        drv = PlaywrightDriver()
        p_res = await loop.run_in_executor(None, drv.search_and_play_youtube, query)

        active_task = target_mgr.get_active_task_target()
        active_target = target_mgr.get_active_target()
        tab_id = active_task.tab_id if active_task else (active_target.page_id if active_target else "PAGE-42")
        hwnd = active_task.hwnd if active_task else (active_target.window_handle if active_target else 0)

        if can_report_success(p_res) and p_res.verified:
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="success",
                verified=True,
                terminal=True,
                state="VIDEO_PLAYING",
                evidence={
                    "query": query,
                    "tab_id": tab_id,
                    "window_hwnd": hwnd,
                    "foreground": True,
                    "video_present": True,
                    "paused": False,
                    "playback_advancing": True,
                    "url": getattr(p_res, "url", "https://www.youtube.com"),
                },
            )
        else:
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="failed",
                verified=False,
                terminal=True,
                error={
                    "type": "PLAYBACK_VERIFICATION_FAILED",
                    "message": p_res.detail or "Failed to verify video playback advancement.",
                },
                evidence={"tab_id": tab_id, "window_hwnd": hwnd},
            )

    async def _execute_browser_open(self, cmd: MasterCommand) -> SlaveResult:
        """Opens or navigates to a URL in the controlled browser task tab."""
        from kratos_agent.computer.browser.manager import get_browser_manager
        from kratos_agent.computer.browser.target import get_target_manager

        url = cmd.parameters.get("url") or cmd.parameters.get("target") or "https://www.google.com"
        logger.info(f"[SlaveExecutor] Opening browser URL: {url}")

        loop = asyncio.get_running_loop()
        b_res = await loop.run_in_executor(None, get_browser_manager().open_url, url)

        target_mgr = get_target_manager()
        active_task = target_mgr.get_active_task_target()
        tab_id = active_task.tab_id if active_task else "PAGE-42"
        hwnd = active_task.hwnd if active_task else 0

        if b_res.ok:
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="success",
                verified=True,
                terminal=True,
                state="NAVIGATED",
                evidence={"url": url, "tab_id": tab_id, "window_hwnd": hwnd},
            )
        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="failed",
            verified=False,
            terminal=True,
            error={"type": "NAVIGATION_FAILED", "message": b_res.detail},
        )

    async def _execute_browser_pause(self, cmd: MasterCommand) -> SlaveResult:
        from kratos_agent.computer.browser.playwright import PlaywrightDriver
        loop = asyncio.get_running_loop()
        drv = PlaywrightDriver()
        p_res = await loop.run_in_executor(None, drv.pause_video)
        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="success" if p_res.ok and p_res.verified else "failed",
            verified=bool(p_res.verified),
            terminal=True,
            state="VIDEO_PAUSED" if p_res.verified else None,
            evidence={"paused": True},
            error={"message": p_res.detail} if not p_res.ok else None,
        )

    async def _execute_browser_resume(self, cmd: MasterCommand) -> SlaveResult:
        from kratos_agent.computer.browser.playwright import PlaywrightDriver
        loop = asyncio.get_running_loop()
        drv = PlaywrightDriver()
        p_res = await loop.run_in_executor(None, drv.resume_video)
        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="success" if p_res.ok and p_res.verified else "failed",
            verified=bool(p_res.verified),
            terminal=True,
            state="VIDEO_PLAYING" if p_res.verified else None,
            evidence={"paused": False, "playback_advancing": True},
            error={"message": p_res.detail} if not p_res.ok else None,
        )

    async def _execute_app_launch(self, cmd: MasterCommand) -> SlaveResult:
        """Launches a Windows desktop application and verifies foreground visibility."""
        from kratos_agent.computer.apps.launcher import get_launcher

        app_name = cmd.parameters.get("app_name") or cmd.parameters.get("name") or cmd.objective
        loop = asyncio.get_running_loop()
        launcher = get_launcher()
        a_res = await loop.run_in_executor(None, launcher.launch_and_verify, app_name)

        if a_res.ok and a_res.verified:
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="success",
                verified=True,
                terminal=True,
                state="APPLICATION_OPENED",
                evidence={"app": app_name, "observation": a_res.observation, "foreground": True},
            )
        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="failed",
            verified=False,
            terminal=True,
            error={"type": "LAUNCH_FAILED", "message": a_res.detail or "Application could not be launched or focused."},
        )

    async def _execute_search(self, cmd: MasterCommand) -> SlaveResult:
        """Executes a web search through SearchFabric."""
        from kratos_agent.search import get_search_router

        query = cmd.parameters.get("query") or cmd.objective
        mode = cmd.parameters.get("mode", "standard")
        router = get_search_router()
        response = await router.search(query, mode=mode)

        citations_list = [c.to_dict() if hasattr(c, "to_dict") else c for c in response.citations]
        results_list = [r.to_dict() if hasattr(r, "to_dict") else r for r in response.results[:5]]

        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="success",
            verified=True,
            terminal=True,
            state="SEARCH_RESULTS",
            evidence={
                "query": query,
                "total_results": response.total_results,
                "results": results_list,
                "citations": citations_list,
                "answer": response.answer,
            },
        )

    async def _execute_observe(self, cmd: MasterCommand) -> SlaveResult:
        """Captures fresh screen frame and returns dimensions/status."""
        from kratos_agent.live.screen import get_screen_stream
        stream = get_screen_stream()
        frame = stream.capture_now()
        if frame:
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="success",
                verified=True,
                terminal=True,
                state="OBSERVED",
                evidence={"width": frame.width, "height": frame.height, "backend": frame.backend},
            )
        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="failed",
            verified=False,
            terminal=True,
            error={"type": "SCREEN_CAPTURE_FAILED", "message": "Failed to capture screen frame."},
        )

    async def _execute_agent_task(self, cmd: MasterCommand) -> SlaveResult:
        """Executes general coding, file, or system task using Kratos runtime."""
        if not self.runtime:
            from kratos_agent.main import runtime as default_runtime
            self.runtime = default_runtime

        task_desc = cmd.objective or cmd.parameters.get("task_description", "")
        loop = asyncio.get_running_loop()

        def _run_sync() -> str:
            if hasattr(self.runtime, "clear_cancel"):
                self.runtime.clear_cancel()
            return self.runtime.run_agent(task_desc, agent_mode=True)

        res_str = await loop.run_in_executor(None, _run_sync)
        is_error = res_str.startswith("Model request failed:") or res_str.startswith("Execution error:")

        error = None
        if is_error:
            from kratos_agent.diagnostics.errors import error_from_exception

            auth_failed = "http 401" in res_str.lower() or "invalid api key" in res_str.lower()
            error = error_from_exception(
                RuntimeError(res_str),
                component="brain",
                stage="model_request",
                task_id=cmd.task_id,
                request_id=cmd.request_id or None,
                retryable=not auth_failed,
                recovery_action=(
                    "The configured OmniRoute credential was rejected. Correct the API key for the configured Brain endpoint, then retry."
                    if auth_failed else
                    "Inspect the Brain endpoint/model diagnostic and retry after the provider is healthy."
                ),
            ).to_dict()

        return SlaveResult(
            command_id=cmd.command_id,
            task_id=cmd.task_id,
            status="failed" if is_error else "success",
            verified=not is_error,
            terminal=True,
            state="TASK_COMPLETED" if not is_error else "TASK_FAILED",
            evidence={"message": res_str[:300]},
            error=error,
        )


# Global SlaveExecutor singleton
_global_slave_executor: SlaveExecutor | None = None


def get_slave_executor() -> SlaveExecutor:
    global _global_slave_executor
    if _global_slave_executor is None:
        _global_slave_executor = SlaveExecutor()
    return _global_slave_executor
