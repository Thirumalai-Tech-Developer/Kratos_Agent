"""Gemini Live session manager for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any, Callable, Dict, Optional

from google import genai
from google.genai import types

from .audio import AudioManager
from .config import LiveConfig
from .events import LiveState, LiveStatusHub
from .router import LiveRouter
from .lifecycle import LiveTurn, LiveTurnState
from kratos_agent.diagnostics.errors import error_from_exception

from kratos_agent.master.prompts import KRATOS_MASTER_SYSTEM_PROMPT
from kratos_agent.master.supervisor import get_master_supervisor

logger = logging.getLogger(__name__)

LIVE_SYSTEM_PROMPT = """You are Gemini/Omni, the single semantic intelligence layer of Kratos Agent.

Your responsibilities:
- understand the user's natural language, voice, screen and camera context;
- resolve references, ambiguity and intended outcomes from meaning;
- decide information vs action;
- decompose complex missions;
- select a canonical capability when known;
- supply structured arguments, constraints, expected state and visual context;
- use execute_mission for ALL computer actions;
- use observe for fresh visual grounding, search for external information, get_task_status for status/errors,
  cancel_task to stop work, continue_task to resume, and ask_user only when ambiguity truly blocks execution.

You do NOT execute OS actions yourself. Master orchestrates missions. Slave performs physical actions.
Never use a phrase parser, keyword heuristic, or exact sentence pattern to infer intent.
Question-shaped requests such as "can you play..." remain action requests when the user is asking you to do them.
Same meaning in English, Tamil, Tanglish, Hindi or mixed language must converge on the same structured mission.

For executable missions, call execute_mission in the same turn. Prefer a canonical capability such as:
browser.youtube.play, whatsapp.send_message, browser.navigate, app.launch, filesystem.write,
terminal.execute, code.test, code.edit.
If the exact capability is unknown, set capability to null and preserve the complete mission.

Live computer tools execute asynchronously. Treat the function response from Kratos as the only authoritative completion signal; progress/filler speech is not completion. Never block the Live receive stream waiting for a tool.
Never report task completion without evidence supplied by Kratos.
Never replace a useful diagnostic with the phrase "system error".
When the user asks what failed or why, call get_task_status and explain component, stage, capability,
actual error, recovery attempted, and current state.
For failed missions, read the returned `diagnostic_summary` or structured `error` fields and tell the user
the actual cause and recovery action. Do not substitute vague guesses such as a delegation or thinker failure
unless that exact cause appears in the returned diagnostic.

Speak naturally in the user's language. Do not expose internal JSON or chain-of-thought.
"""




class LiveSession:
    """Manages the connection, send loop, and receive loop with Gemini Live API."""

    def __init__(
        self,
        config: LiveConfig,
        out_queue: asyncio.Queue[Dict[str, Any]],
        audio_manager: AudioManager,
        router: LiveRouter,
        status_hub: Optional[LiveStatusHub] = None,
        on_user_transcript: Optional[Callable[[str], None]] = None,
        on_model_transcript: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config
        self.out_queue = out_queue
        self.audio_manager = audio_manager
        self.router = router
        self.status_hub = status_hub
        self.on_user_transcript = on_user_transcript
        self.on_model_transcript = on_model_transcript

        self.session: Any = None
        self.is_running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._send_lock = asyncio.Lock()
        self._turn_complete_event: Optional[asyncio.Event] = None
        self._turn_transcript_chunks: list[str] = []
        self._last_heartbeat: float = 0.0
        self._last_logged_error: str = ""
        self._last_logged_error_time: float = 0.0
        self._active_live_turn: Optional[LiveTurn] = None
        self._pending_tool_tasks: set[asyncio.Task[Any]] = set()
        self._pending_mission_tool_ids: set[str] = set()

        # Wire speech feedback from Slave execution to Gemini Master narration
        get_master_supervisor().set_speech_callback(self._on_slave_result_feedback)

    def _on_slave_result_feedback(self, text: str) -> None:
        """Narrate background Slave completions, avoiding duplicate Live mission narration."""
        if self._pending_mission_tool_ids:
            logger.debug("[LiveSession] Suppressing background mission narration while a Live mission tool is pending.")
            return
        if self.is_running and self.session is not None and text.strip():
            asyncio.create_task(self.send_narration(text.strip()))

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return the latest sanitized Live/Slave diagnostic state."""
        now = time.time()
        heartbeat_age = None if self._last_heartbeat <= 0 else round(max(0.0, now - self._last_heartbeat), 3)
        turn = self._active_live_turn
        supervisor = get_master_supervisor()
        return {
            "model": self.config.model,
            "connected": bool(self.session is not None),
            "running": bool(self.is_running),
            "healthy": bool(self.is_healthy()),
            "heartbeat_age_s": heartbeat_age,
            "pending_tool_tasks": len(self._pending_tool_tasks),
            "pending_mission_tools": len(self._pending_mission_tool_ids),
            "active_turn_id": turn.turn_id if turn else None,
            "active_turn_state": turn.state.value if turn else None,
            "pending_tool_call_ids": sorted(turn.pending_tool_calls) if turn else [],
            "last_error": self.status_hub.status.last_error if self.status_hub else None,
            "last_error_component": self.status_hub.status.last_error_component if self.status_hub else None,
            "last_task": supervisor.active_objective,
            "active_task_id": supervisor.active_task_id,
        }

    def _track_tool_task(self, task: asyncio.Task[Any]) -> None:
        self._pending_tool_tasks.add(task)
        task.add_done_callback(self._pending_tool_tasks.discard)

    async def _run_tool_call(
        self,
        name: str,
        call_id: str,
        turn_id: str,
        args: Dict[str, Any],
    ) -> None:
        """Execute a Gemini Live tool outside the receive loop and return its result asynchronously."""
        try:
            try:
                res = await self.router.handle_tool_call(name, args)
                resp_dict = res if isinstance(res, dict) else {"result": str(res)}
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err = error_from_exception(
                    exc,
                    component="LiveSession",
                    stage="tool_dispatch",
                    task_id=get_master_supervisor().active_task_id,
                    request_id=args.get("request_id"),
                    retryable=True,
                    recovery_action="Inspect task status and retry through the structured mission pipeline.",
                )
                logger.exception("[LiveSession] tool %s failed", name)
                if self.status_hub:
                    self.status_hub.report_error("tool", err.user_message)
                resp_dict = {"status": "failed", "error": err.to_dict()}

            turn = self._active_live_turn
            if turn is not None and turn.turn_id == turn_id:
                turn.tool_result(call_id)

            response_payload = dict(resp_dict)
            response_payload["tool_call_id"] = call_id
            response_payload["turn_id"] = turn_id
            response_payload["scheduling"] = (
                "INTERRUPT" if name in ("cancel_task", "cancel_active_task") else "WHEN_IDLE"
            )
            fn_resp = types.FunctionResponse(
                name=name,
                id=call_id,
                response=response_payload,
            )

            # The tool has completed; the model receives the correlated result asynchronously.
            try:
                async with self._send_lock:
                    if self.session is not None and self.is_running:
                        await self.session.send_tool_response(function_responses=[fn_resp])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err = error_from_exception(
                    exc,
                    component="LiveSession",
                    stage="tool_result_transport",
                    task_id=get_master_supervisor().active_task_id,
                    request_id=args.get("request_id"),
                    retryable=True,
                    recovery_action="Reconnect Gemini Live and retry the structured mission.",
                )
                logger.exception("[LiveSession] failed to send tool response")
                if self.status_hub:
                    self.status_hub.report_error("live_transport", err.user_message)
        finally:
            self._pending_mission_tool_ids.discard(call_id)
            if self.status_hub and self.status_hub.status.active_task_id:
                self.status_hub.update(current_state=LiveState.EXECUTING)

    @staticmethod
    def _normalize_interaction_status(value: Any) -> Optional[str]:
        """Normalize SDK enum/string values for Gemini 3.8 Live interaction lifecycle handling."""
        if value is None:
            return None
        raw = getattr(value, "value", value)
        text = str(raw).strip().upper()
        return text or None

    @staticmethod
    def _extract_interaction_status(response: Any) -> Optional[str]:
        """Read interaction_status across SDK response layouts for forward compatibility."""
        value = getattr(response, "interaction_status", None)
        if value is None:
            server_content = getattr(response, "server_content", None)
            value = getattr(server_content, "interaction_status", None)
        if value is None:
            value = getattr(response, "interactionStatus", None)
        return LiveSession._normalize_interaction_status(value)

    def _requires_interaction_status(self) -> bool:
        """Gemini 3.8 Live Extended Thinking uses interaction_status instead of turnComplete alone."""
        return "extended-thinking" in self.config.model.lower()

    def _build_connect_config(self) -> types.LiveConnectConfig:
        config: Dict[str, Any] = dict(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.config.voice_name,
                    )
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=self.config.context_trigger_tokens,
                sliding_window=types.SlidingWindow(
                    target_tokens=self.config.context_target_tokens,
                ),
            ),
            tools=self.router.get_tool_declarations(),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=LIVE_SYSTEM_PROMPT)]
            ),
        )
        # thinking_config is only accepted by Live models that expose extended
        # thinking. Keep the same app config usable with the standard Live model.
        if self._requires_interaction_status():
            config["thinking_config"] = types.ThinkingConfig(
                thinking_level=self.config.thinking_level,
            )
        return types.LiveConnectConfig(**config)

    async def send_realtime(self) -> None:
        """Sends microphone audio and video frames from out_queue to Gemini."""
        try:
            while self.is_running and self.session is not None:
                msg = await self.out_queue.get()
                if not msg:
                    continue

                mime_type = msg.get("mime_type", "")
                data = msg.get("data", b"")
                if not data:
                    continue

                blob = types.Blob(data=data, mime_type=mime_type)

                try:
                    async with self._send_lock:
                        if mime_type.startswith("audio/"):
                            await self.session.send_realtime_input(audio=blob)
                        else:
                            await self.session.send_realtime_input(video=blob)
                except asyncio.CancelledError:
                    raise
                except Exception as frame_err:
                    logger.debug(f"[LiveSession] Realtime frame send error ({mime_type}): {frame_err}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[LiveSession] Send loop error: {e}")


    async def receive_loop(self) -> None:
        """Receive Gemini events while preserving explicit USER→TOOL→FOLLOWUP turn state."""
        self._last_user_transcript = ""
        self._output_transcript_buffer = ""
        try:
            while self.is_running and self.session is not None:
                async for response in self.session.receive():
                    if not self.is_running:
                        break

                    self._last_heartbeat = time.time()
                    if self.status_hub:
                        self.status_hub.update(last_heartbeat=self._last_heartbeat)

                    tool_call = getattr(response, "tool_call", None)
                    if tool_call and hasattr(tool_call, "function_calls"):
                        if self.status_hub:
                            self.status_hub.update(current_state=LiveState.THINKING)
                        for call in tool_call.function_calls:
                            call_id = call.id or f"call_{uuid.uuid4().hex[:8]}"
                            if self._active_live_turn is None:
                                self._active_live_turn = LiveTurn(
                                    turn_id=f"TURN-{uuid.uuid4().hex[:10].upper()}",
                                    request_id=f"REQ-{uuid.uuid4().hex[:10].upper()}",
                                    state=LiveTurnState.MODEL_THINKING,
                                )
                            turn_id = self._active_live_turn.turn_id
                            self._active_live_turn.begin_tool(call_id)
                            logger.info(
                                "[GEMINI] tool_call=%s tool_call_id=%s turn_id=%s",
                                call.name, call_id, turn_id,
                            )
                            if call.name in ("execute_mission", "delegate_task", "start_agent_task", "kratos_task", "continue_task"):
                                self._last_user_transcript = ""
                                self._pending_mission_tool_ids.add(call_id)

                            args = dict(call.args or {})
                            args.setdefault("tool_call_id", call_id)
                            args.setdefault("turn_id", turn_id)
                            args.setdefault("request_id", self._active_live_turn.request_id)

                            # Gemini Live Extended Thinking requires asynchronous tool execution;
                            # never block the receive loop on a physical computer action.
                            tool_task = asyncio.create_task(
                                self._run_tool_call(call.name, call_id, turn_id, args),
                                name=f"kratos-live-tool-{call.name}-{call_id}",
                            )
                            self._track_tool_task(tool_task)

                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue

                    if getattr(server_content, "interrupted", False):
                        from kratos_agent.live.echo_guard import get_echo_guard
                        get_echo_guard().stop_speaking()
                        self._output_transcript_buffer = ""
                        if self._turn_complete_event is not None:
                            self._turn_complete_event.set()
                        if self.status_hub:
                            self.status_hub.update(current_state=LiveState.LISTENING)
                        continue

                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn and hasattr(model_turn, "parts"):
                        if self._active_live_turn and self._active_live_turn.awaiting_model_followup:
                            self._active_live_turn.model_followup()
                        if self.status_hub and not self.status_hub.status.active_task_id:
                            self.status_hub.update(current_state=LiveState.SPEAKING)
                        for part in model_turn.parts:
                            inline = getattr(part, "inline_data", None)
                            if inline and inline.data:
                                from kratos_agent.live.echo_guard import get_echo_guard
                                get_echo_guard().start_speaking()
                                try:
                                    self.audio_manager.audio_in_queue.put_nowait(inline.data)
                                except asyncio.QueueFull:
                                    try:
                                        self.audio_manager.audio_in_queue.get_nowait()
                                    except asyncio.QueueEmpty:
                                        pass
                                    self.audio_manager.audio_in_queue.put_nowait(inline.data)

                    out_tx = getattr(server_content, "output_transcription", None)
                    if out_tx and out_tx.text:
                        text = out_tx.text.strip()
                        if text:
                            self._output_transcript_buffer += (" " if self._output_transcript_buffer else "") + text
                            self._turn_transcript_chunks.append(text)
                            if self.on_model_transcript:
                                try:
                                    self.on_model_transcript(text)
                                except Exception:
                                    pass

                    in_tx = getattr(server_content, "input_transcription", None)
                    if in_tx and in_tx.text:
                        text = in_tx.text.strip()
                        if text:
                            self._last_user_transcript = text
                            self._output_transcript_buffer = ""
                            self._turn_transcript_chunks = []
                            if self._active_live_turn is None or self._active_live_turn.state in {
                                LiveTurnState.TURN_COMPLETE,
                                LiveTurnState.USER_RESPONSE,
                            }:
                                self._active_live_turn = LiveTurn(
                                    turn_id=f"TURN-{uuid.uuid4().hex[:10].upper()}",
                                    request_id=f"REQ-{uuid.uuid4().hex[:10].upper()}",
                                )
                            self._active_live_turn.state = LiveTurnState.USER_INPUT
                            if self.on_user_transcript:
                                try:
                                    self.on_user_transcript(text)
                                except Exception:
                                    pass
                            from kratos_agent.output.voice import get_voice_buffer, get_tts_queue
                            get_voice_buffer().clear()
                            get_tts_queue().cancel_current()

                    if getattr(server_content, "turn_complete", False):
                        from kratos_agent.live.echo_guard import get_echo_guard
                        get_echo_guard().stop_speaking()
                        if not self._requires_interaction_status() and self._active_live_turn and self._active_live_turn.can_finish():
                            self._active_live_turn.state = LiveTurnState.TURN_COMPLETE
                            if self._turn_complete_event is not None:
                                self._turn_complete_event.set()
                        from kratos_agent.output.voice import get_voice_buffer
                        remaining_sentence = get_voice_buffer().flush()
                        if remaining_sentence and self.on_model_transcript:
                            try:
                                self.on_model_transcript(remaining_sentence)
                            except Exception:
                                pass

                    interaction_status = self._extract_interaction_status(response)
                    if interaction_status == "IDLE":
                        if self._active_live_turn and self._active_live_turn.can_finish():
                            self._active_live_turn.state = LiveTurnState.TURN_COMPLETE
                            if self._turn_complete_event is not None:
                                self._turn_complete_event.set()
                        if self.status_hub:
                            self.status_hub.update(
                                current_state=LiveState.EXECUTING if self.status_hub.status.active_task_id else LiveState.IDLE
                            )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            err = error_from_exception(
                exc,
                component="LiveSession",
                stage="receive_loop",
                task_id=get_master_supervisor().active_task_id,
                retryable=True,
                recovery_action="Reconnect Gemini Live and inspect the task diagnostic.",
            )
            logger.exception("[LiveSession] Receive loop error")
            if self.status_hub:
                self.status_hub.report_error("live_receive", err.user_message)

    async def send_text_input(self, text: str, end_of_turn: bool = True) -> None:
        """Sends text input directly into the Gemini Live session."""
        if self.session is None or not text.strip():
            return
        try:
            if self.status_hub:
                self.status_hub.update(current_state=LiveState.THINKING, last_transcript=text.strip())
            async with self._send_lock:
                await self.session.send(input=text.strip(), end_of_turn=end_of_turn)
        except Exception as e:
            logger.warning(f"[LiveSession] Error sending text input: {e}")

    async def send_text_turn(self, text: str, timeout: float = 600.0) -> str:
        """Sends user text as a complete turn to Gemini Live and waits for model turn completion."""
        if self.session is None or not text.strip():
            return ""

        event = asyncio.Event()
        self._turn_complete_event = event
        self._turn_transcript_chunks = []
        self._last_user_transcript = text.strip()
        self._active_live_turn = LiveTurn(
            turn_id=f"TURN-{uuid.uuid4().hex[:10].upper()}",
            request_id=f"REQ-{uuid.uuid4().hex[:10].upper()}",
            state=LiveTurnState.USER_INPUT,
        )

        try:
            if self._active_live_turn:
                self._active_live_turn.state = LiveTurnState.MODEL_THINKING
            await self.send_text_input(text.strip(), end_of_turn=True)
            # Wait for turn completion with timeout
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[LiveSession] send_text_turn timed out after {timeout}s")
            return " ".join(self._turn_transcript_chunks).strip()
        finally:
            self._turn_complete_event = None

    async def send_narration(self, text: str) -> None:
        """Prompts Gemini to speak an event update to the user."""
        if self.session is None or not text.strip():
            return
        # Sanitize narration text to prevent raw internal state from reaching Gemini
        clean = self._sanitize_narration(text.strip())
        if not clean:
            return
        prompt = (
            f"[EPHEMERAL STATUS — do NOT quote this verbatim, do NOT memorize internal values, "
            f"just convey the meaning naturally if the user asks]: {clean}"
        )
        await self.send_text_input(prompt)

    @staticmethod
    def _sanitize_narration(text: str) -> str:
        """Strips JSON-like payloads, internal identifiers, and raw debug data from narration text."""
        import re as _re
        # Remove JSON-like objects: {key:val, key:val}
        text = _re.sub(r'\{[^}]{0,200}\}', '', text)
        # Remove raw key=value pairs like err=0 or status=completed
        text = _re.sub(r'\b\w+=[\w.-]+', '', text)
        # Remove UUID-like task IDs
        text = _re.sub(r'\b[0-9a-f]{8}(-[0-9a-f]{4}){0,3}\b', '', text)
        # Remove leftover double spaces and trim
        text = _re.sub(r'\s{2,}', ' ', text).strip()
        # Remove trailing/leading punctuation artifacts
        text = text.strip(' :-=|')
        return text

    def is_healthy(self) -> bool:
        """Verifies that the session, receive loop, and heartbeat are actively operational (§15)."""
        if not self.is_running or self.session is None:
            return False
        recv_task = next((t for t in self._tasks if t.get_name() == "kratos-live-recv"), None)
        if recv_task is None or recv_task.done():
            return False
        last_hb = getattr(self, "_last_heartbeat", 0.0)
        if last_hb > 0 and (time.time() - last_hb > 90.0):
            return False
        return True

    async def run_connection_loop(self) -> None:
        """Manages the connection with retry backoff and explicit state machine transitions (§14, §15)."""
        self.is_running = True
        self._last_heartbeat = time.time()
        client = genai.Client(api_key=self.config.api_key)
        connect_config = self._build_connect_config()

        BACKOFF_DELAYS = [1.0, 2.0, 4.0, 8.0, 15.0]
        backoff_idx = 0

        while self.is_running:
            try:
                logger.info(f"[LiveSession] Connecting to Gemini Live ({self.config.model})...")
                if self.status_hub:
                    self.status_hub.update(current_state=LiveState.CONNECTING, live_health="connecting")
                async with client.aio.live.connect(
                    model=self.config.model,
                    config=connect_config,
                ) as session:
                    self.session = session
                    backoff_idx = 0
                    self._last_heartbeat = time.time()
                    logger.info("[LiveSession] Gemini Live session connected.")
                    if self.status_hub:
                        self.status_hub.clear_error("gemini")
                        self.status_hub.update(
                            gemini_connected=True,
                            live_health="online",
                            last_heartbeat=self._last_heartbeat,
                            last_error=None,
                            last_error_component=None,
                            current_state=LiveState.CONNECTED,
                        )

                    send_task = asyncio.create_task(self.send_realtime(), name="kratos-live-send")
                    recv_task = asyncio.create_task(self.receive_loop(), name="kratos-live-recv")
                    self._tasks = [send_task, recv_task]

                    done, pending = await asyncio.wait(
                        [send_task, recv_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                err_str = str(e)
                safe_err_str = re.sub(r"(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,})", "[REDACTED]", err_str)
                now = time.time()

                # Detect 1006 abnormal closure (§14)
                is_abnormal_closure = "1006" in err_str or "abnormal" in err_str.lower()
                if is_abnormal_closure:
                    logger.warning("[LiveSession] Detected 1006 abnormal closure. Transitioning to DEGRADED state...")
                    if self.status_hub:
                        self.status_hub.update(
                            gemini_connected=False,
                            current_state=LiveState.DEGRADED,
                            live_health="degraded",
                            last_error="1006 abnormal closure detected",
                            last_error_component="gemini",
                        )

                # Throttle repeated network/DNS errors to once every 60s
                if safe_err_str != self._last_logged_error or (now - self._last_logged_error_time) > 60.0:
                    if "getaddrinfo failed" in err_str:
                        logger.warning("[LiveSession] Network or DNS resolution unavailable (getaddrinfo failed). Retrying in background...")
                    else:
                        logger.warning(f"[LiveSession] Connection lost or error: {e}")
                    self._last_logged_error = safe_err_str
                    self._last_logged_error_time = now
                    if self.status_hub:
                        self.status_hub.report_error("gemini", safe_err_str)
                else:
                    logger.debug(f"[LiveSession] Reconnect attempt failed: {e}")

                retry_delay = BACKOFF_DELAYS[min(backoff_idx, len(BACKOFF_DELAYS) - 1)]
                backoff_idx = min(backoff_idx + 1, len(BACKOFF_DELAYS) - 1)

                if self.status_hub:
                    self.status_hub.update(
                        gemini_connected=False,
                        last_error=safe_err_str,
                        current_state=LiveState.RECONNECTING,
                        live_health="reconnecting",
                    )
                if not self.is_running:
                    break
                await asyncio.sleep(retry_delay)
            finally:
                self.session = None
                if self.status_hub and not self.is_running:
                    self.status_hub.update(gemini_connected=False, current_state=LiveState.DISCONNECTED, live_health="offline")


    async def stop(self) -> None:
        """Stops the session and cancels all associated tasks (§38)."""
        self.is_running = False
        if self.status_hub:
            self.status_hub.update(current_state=LiveState.STOPPING)
        for t in self._tasks:
            if not t.done():
                t.cancel()
        for t in list(self._pending_tool_tasks):
            if not t.done():
                t.cancel()
        all_tasks = [*self._tasks, *self._pending_tool_tasks]
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._tasks.clear()
        self._pending_tool_tasks.clear()
        self._pending_mission_tool_ids.clear()
        self.session = None
        if self.status_hub:
            self.status_hub.update(gemini_connected=False, current_state=LiveState.DISCONNECTED, live_health="offline")
