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

from kratos_agent.master.prompts import KRATOS_MASTER_SYSTEM_PROMPT
from kratos_agent.master.supervisor import get_master_supervisor

logger = logging.getLogger(__name__)

LIVE_SYSTEM_PROMPT = KRATOS_MASTER_SYSTEM_PROMPT

"""
You are the voice, hearing, and vision interface of KRATOS AGENT — an autonomous computer agent that controls the user's desktop, browser, terminal, files, and applications.

You are NOT a standalone assistant. You are the sensory layer of an autonomous execution system.
Kratos Agent has FULL control of the user's computer through its own tools and execution pipeline.
YOU do not execute actions yourself. You delegate ALL actionable requests to Kratos Agent by calling `delegate_task`.

═══════════════════════════════════════════════════════
MANDATORY RULE #1 — NEVER REFUSE COMPUTER ACTIONS
═══════════════════════════════════════════════════════

You MUST NEVER say any of the following (or equivalents in any language):
- "I can't access your computer"
- "I'm not able to open applications"
- "I don't have the ability to control your screen"
- "I cannot directly interact with your device"
- "என்னால் உங்கள் சாதனத்தில் நேரடியாக செயல்பட முடியாது" (Tamil refusal)
- "मैं आपके कंप्यूटर को एक्सेस नहीं कर सकता" (Hindi refusal)
- Any statement claiming inability to perform computer/browser/file/terminal actions

Kratos Agent CAN do these things. You are its voice. When the user asks for ANY computer action, call `delegate_task` IMMEDIATELY.

═══════════════════════════════════════════════════════
MANDATORY RULE #2 — ACTION ROUTING & IMMEDIATE TOOL CALL
═══════════════════════════════════════════════════════

When the user's request contains ANY action (open, run, play, create, fix, click, type, browse):
You MUST call `delegate_task` in the VERY SAME RESPONSE TURN.
DO NOT simply say "I will set it up" or "Let me get that started" without calling `delegate_task`.
You MUST emit the `delegate_task` function call immediately along with your spoken confirmation.

DECISION QUALITY:
- Infer the user's intended outcome semantically; never require an exact command template.
- Treat action-shaped questions such as "can you play...", "could you open...", and "please send..." as execution requests when the user is asking you to perform them.
- When a specialized capability clearly fits, provide the structured action and parameters in `delegate_task` (for example browser.youtube.play with a semantic query).
- Preserve the complete natural-language objective so the Slave retains the original context.

When the user's request contains ANY of these intentions, you MUST call `delegate_task`:
- Open, close, launch, start, or switch applications (YouTube, Chrome, VS Code, Terminal, any app)
- Browse, navigate, search, click, type, scroll on websites
- Play, pause, download, stream media (videos, music, games)
- Create, modify, delete, read, write files or code
- Run, execute, test, build, deploy, install commands or programs
- Inspect, debug, fix, analyze projects or errors
- Automate any multi-step computer workflow
- SHOW something on the screen, TYPE text out, WRITE logs, or DISPLAY errors.
- ANY action that requires interacting with the computer or showing something to the user.

Examples that MUST trigger `delegate_task`:
- "Open YouTube" → delegate_task("Open YouTube in the browser")
- "Play GTA Vice City gameplay" → delegate_task("Search and play GTA Vice City gameplay video on YouTube")
- "Create a Python script" → delegate_task("Create a Python script")
- "என்ன பிழை? அதை வந்து இப்ப எனக்கு ஃபுல்லா காட்டு." → delegate_task("Show the full error logs on the screen for the user")
- "இந்த error என்னன்றத இங்கிலீஷ்ல டைப் அடிச்சு காட்டு." → delegate_task("Type out the explanation of the error in English on the screen")
- "Fix this error" → delegate_task("Fix the error in the current project")
- "Install numpy" → delegate_task("Install the numpy Python package")
- "Download this file" → delegate_task("Download the specified file")

═══════════════════════════════════════════════════════
MANDATORY RULE #3 — CHAT-ONLY ROUTING
═══════════════════════════════════════════════════════

Only answer directly (without calling start_agent_task) when the request is PURELY:
- A knowledge question: "What is Docker?", "Explain RAG", "What is machine learning?"
- An opinion request: "What do you think about this architecture?"
- A casual conversation: "How are you?", "Tell me a joke"
- An explicit explanation request: "Just explain this", "Don't change anything, explain"

If there is ANY ambiguity about whether it's a question or an action, DEFAULT TO ACTION — call `delegate_task`.

═══════════════════════════════════════════════════════
MANDATORY RULE #4 — MULTILINGUAL UNDERSTANDING
═══════════════════════════════════════════════════════

You understand Tamil, English, Hindi, Tanglish (Tamil+English), Hinglish (Hindi+English), and mixed-language requests.
Action verbs in ANY language must trigger `delegate_task`:
- Tamil: ஓபன் (open), ரன் (run), பண்ணு (do), play பண்ணு (play), போ (go), தேடு (search), உருவாக்கு (create)
- Hindi: खोलो (open), चलाओ (run), करो (do), बनाओ (create)
- English: open, run, play, create, fix, build, install, deploy, navigate, click, type, browse

═══════════════════════════════════════════════════════
MANDATORY RULE #5 — CONTINUOUS VISUAL FEEDBACK & MONITORING
═══════════════════════════════════════════════════════

When you call `delegate_task`, it will return immediately with a "started" status. Kratos will run in the background.
While Kratos is running, YOU ARE THE EYES of the system.
You MUST actively monitor the screen for changes.
When you see the screen change (e.g. YouTube opens, a game loads, a terminal shows an error, a file appears), you MUST call the `report_visual_status` tool to push that update to Kratos.
Example: "YouTube just opened and is loading." -> call `report_visual_status("YouTube is now open on screen.")`

═══════════════════════════════════════════════════════
OTHER CAPABILITIES
═══════════════════════════════════════════════════════

VISION:
- When user says "look at this", "what's on my screen", "what is this error" → call `capture_screen_context`
- If the user asks to ACT on what they see ("click that button", "fix this error on screen") → call `capture_screen_context` first, then `delegate_task` with visual_context

CONTROL:
- "Stop" / "Cancel" / "Abort" → call `cancel_active_task`
- "What are you doing?" / "Status" → call `get_task_status`
- "What error occurred?", "Why did it fail?", "Is this a connection error?", "What happened?" → call `get_task_status` and report the latest sanitized `last_error`, `last_error_component`, and connection health. Do not refuse to explain an ordinary runtime error.
- "Load past session" / "load" / "/load" → Route to `delegate_task` with "Load previous session history."

TONE:
- Confident, concise, natural spoken language
- Never expose JSON, internal state, or chain-of-thought
- Respond in the same language the user speaks
- NEVER say "Is there anything else you would like me to help you with?" or ask follow-up questions after confirming a task (§33, §35). State what happened concisely and wait silently.
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

        # Wire speech feedback from Slave execution to Gemini Master narration
        get_master_supervisor().set_speech_callback(self._on_slave_result_feedback)

    def _on_slave_result_feedback(self, text: str) -> None:
        """Called when Slave finishes execution to let Gemini Master speak the verified outcome."""
        if self.is_running and self.session is not None and text.strip():
            asyncio.create_task(self.send_narration(text.strip()))

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return the latest sanitized Live/Slave diagnostic state."""
        return {
            "model": self.config.model,
            "connected": bool(self.session is not None),
            "running": bool(self.is_running),
            "last_error": self.status_hub.status.last_error if self.status_hub else None,
            "last_error_component": self.status_hub.status.last_error_component if self.status_hub else None,
            "last_task": get_master_supervisor().active_objective,
            "active_task_id": get_master_supervisor().active_task_id,
        }


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
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            thinking_config=types.ThinkingConfig(
                thinking_level=self.config.thinking_level,
            ),
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


    # ── Refusal Intercept Guard ──────────────────────────────────────────────
    # Patterns that indicate Gemini refused instead of calling start_agent_task
    _REFUSAL_PATTERNS = [
        re.compile(r"(?i)i\s+can'?t\s+(access|control|open|interact|directly)"),
        re.compile(r"(?i)i'?m\s+not\s+able\s+to\s+(open|access|control|interact|run|execute|play)"),
        re.compile(r"(?i)i\s+don'?t\s+have\s+(the\s+)?abilit(y|ies)\s+to"),
        re.compile(r"(?i)i\s+cannot\s+(access|control|open|interact|directly|browse|navigate|click)"),
        re.compile(r"(?i)unfortunately,?\s+i\s+(can'?t|cannot|am not able|don'?t have)"),
        re.compile(r"(?i)as\s+an?\s+(ai|language model|text-based)"),
        re.compile(r"(?i)beyond\s+my\s+(current\s+)?capabilities"),
        # Tamil refusal patterns
        re.compile(r"என்னால்\s*(முடியாது|இயலாது)"),
        re.compile(r"நேரடியாக.*செயல்பட\s*முடியாது"),
        re.compile(r"நான்.*அணுக\s*முடியாது"),
        # Hindi refusal patterns
        re.compile(r"(?i)मैं.*नहीं\s*कर\s*सकत"),
        re.compile(r"(?i)यह\s+मेरे\s+बस\s+में\s+नहीं"),
    ]

    def _is_refusal(self, text: str) -> bool:
        """Detects if Gemini output is a refusal to perform a computer action."""
        if not text or len(text) < 15:
            return False
        return any(p.search(text) for p in self._REFUSAL_PATTERNS)

    _ACTION_KEYWORDS = [
        # English
        "open", "launch", "start", "play", "run", "browse", "navigate", "search",
        "create", "make", "build", "fix", "install", "download", "deploy", "delete",
        "click", "type", "scroll", "press", "show", "write", "display",
        # Tamil
        "ஓபன்", "ரன்", "பண்ணு", "போ", "தேடு", "உருவாக்கு", "காட்டு", "ப்ளே",
        # Hindi
        "खोलो", "चलाओ", "करो", "बनाओ", "दिखाओ", "ढूंढो"
    ]

    def _is_action_request(self, text: str) -> bool:
        """Determines if a user prompt requested an action that requires Kratos Agent."""
        lower = text.lower().strip()
        if any(lower.startswith(q) for q in ("what is", "what are", "why is", "why are", "who is", "who are", "explain ")):
            return False
        return any(kw in lower for kw in self._ACTION_KEYWORDS)

    async def _intercept_refusal(self, refusal_text: str) -> None:
        """When Gemini refuses, auto-submit the user's last request to Kratos Brain."""
        last_user_text = getattr(self, "_last_user_transcript", "").strip()
        if not last_user_text:
            logger.warning("[GEMINI] Refusal intercepted but no user transcript available.")
            return

        logger.warning(f"[GEMINI] Refusal intercepted: '{refusal_text[:80]}...'")
        logger.info(f"[GEMINI] Auto-routing user request to Kratos Brain: '{last_user_text[:80]}'")
        print(f"\n⚡ [GEMINI] Refusal intercepted — routing to Kratos Brain...", flush=True)
        self._last_user_transcript = ""

        # Submit the original user request to Kratos via the existing bridge
        try:
            result = await self.router.handle_tool_call(
                "start_agent_task",
                {"task_description": last_user_text},
            )
            status = result.get("status", "unknown")
            task_result = result.get("result", "")
            summary = result.get("summary", task_result[:200] if task_result else "")

            # Send the correction and result back to Gemini as context
            correction = (
                f"[SYSTEM CORRECTION]: You incorrectly refused the user's request. "
                f"Kratos Agent has executed it. Status: {status}. "
                f"Result: {summary}. "
                f"Now speak the result naturally to the user in their language. "
                f"Do NOT apologize for refusing — just report what Kratos did."
            )
            await self.send_text_input(correction)
            logger.info(f"[GEMINI] Refusal correction sent. Kratos result: {status}")
        except Exception as e:
            logger.error(f"[GEMINI] Refusal intercept failed: {e}")

    async def receive_loop(self) -> None:
        """Receives Gemini Live audio responses, transcriptions, and tool calls."""
        self._last_user_transcript: str = ""
        self._output_transcript_buffer: str = ""
        self._task_started_in_turn: bool = False
        try:
            while self.is_running and self.session is not None:
                async for response in self.session.receive():
                    if not self.is_running:
                        break

                    self._last_heartbeat = time.time()
                    interaction_status = self._extract_interaction_status(response)
                    if self.status_hub:
                        self.status_hub.update(last_heartbeat=self._last_heartbeat)

                    # 1. Check Tool Calls
                    tool_call = getattr(response, "tool_call", None)
                    if tool_call and hasattr(tool_call, "function_calls"):
                        if self.status_hub:
                            self.status_hub.update(current_state=LiveState.THINKING)
                        for call in tool_call.function_calls:
                            logger.info(f"[GEMINI] Tool call: {call.name}")
                            if call.name in ("delegate_task", "start_agent_task", "kratos_task", "continue_task"):
                                self._task_started_in_turn = True
                                self._last_user_transcript = ""  # Cleared on tool invocation

                            call_id = call.id or f"call_{uuid.uuid4().hex[:8]}"
                            try:
                                res = await self.router.handle_tool_call(call.name, call.args or {})
                                resp_dict = res if isinstance(res, dict) else {"result": str(res)}
                            except Exception as exc:
                                err_text = re.sub(r"(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,})", "[REDACTED]", str(exc)).strip()
                                logger.exception("[LiveSession] Tool '%s' failed: %s", call.name, err_text)
                                if self.status_hub:
                                    self.status_hub.report_error("tool", f"{call.name}: {type(exc).__name__}: {err_text or 'tool execution failed'}")
                                resp_dict = {
                                    "status": "error",
                                    "error_type": type(exc).__name__,
                                    "message": err_text or "Tool execution failed.",
                                }

                            # NON_BLOCKING functions require a scheduling policy in FunctionResponse.
                            scheduling = "INTERRUPT" if call.name in ("cancel_task", "cancel_active_task") else "WHEN_IDLE"
                            response_payload = dict(resp_dict)
                            response_payload["scheduling"] = scheduling
                            fn_resp = types.FunctionResponse(
                                name=call.name,
                                id=call_id,
                                response=response_payload,
                            )
                            try:
                                async with self._send_lock:
                                    await self.session.send_tool_response(
                                        function_responses=[fn_resp]
                                    )
                            except Exception as e:
                                logger.warning(f"[LiveSession] Failed to send tool response: {e}")


                    # 2. Check Server Content
                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue

                    # Interruption: User spoke while model was responding
                    if getattr(server_content, "interrupted", False):
                        logger.info("[LiveSession] Interruption detected. Clearing audio queue.")
                        self.audio_manager.handle_interruption()
                        self._output_transcript_buffer = ""
                        if self._turn_complete_event is not None:
                            self._turn_complete_event.set()
                        from kratos_agent.live.echo_guard import get_echo_guard
                        get_echo_guard().stop_speaking()
                        if self.status_hub:
                            self.status_hub.update(current_state=LiveState.LISTENING)


                    # Model Audio Output
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn and hasattr(model_turn, "parts"):
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

                    # Input Transcription (what the user said)
                    in_tx = getattr(server_content, "input_transcription", None)
                    if in_tx and in_tx.text:
                        text = in_tx.text.strip()
                        if text:
                            logger.info(f"[GEMINI] Voice input: {text}")
                            self._last_user_transcript = text
                            self._output_transcript_buffer = ""
                            self._task_started_in_turn = False

                            # Cancel any previous voice output and clear buffer on new user speech (§13)
                            from kratos_agent.output.voice import get_voice_buffer, get_tts_queue
                            get_voice_buffer().clear()
                            get_tts_queue().cancel_current()

                            if self.status_hub:
                                self.status_hub.update(
                                    current_state=LiveState.LISTENING,
                                    last_transcript=text,
                                )
                            if self.on_user_transcript:
                                try:
                                    self.on_user_transcript(text)
                                except Exception:
                                    pass
                            else:
                                print(f"\n🎤 [Voice] You: {text}", flush=True)

                    # Output Transcription (what Gemini replied)
                    out_tx = getattr(server_content, "output_transcription", None)
                    if out_tx and out_tx.text:
                        text = out_tx.text.strip()
                        if text:
                            logger.info(f"[GEMINI] Voice output chunk: {text}")
                            self._output_transcript_buffer += " " + text
                            if self._turn_complete_event is not None:
                                self._turn_transcript_chunks.append(text)
                            if self.status_hub:
                                self.status_hub.update(last_transcript=text)

                            # Buffer through VoiceBuffer to emit ONLY complete sentences (§7, §8, §9)
                            from kratos_agent.output.voice import get_voice_buffer
                            vb = get_voice_buffer()
                            vb.append(text)
                            sentence = vb.flush_sentence()
                            if sentence:
                                if self.on_model_transcript:
                                    try:
                                        self.on_model_transcript(sentence)
                                    except Exception:
                                        pass
                                else:
                                    print(f"\n⚡ [Voice] Kratos: {sentence}\n", flush=True)

                    # Check Turn Completion.
                    # For Gemini 3.8 Extended Thinking, turnComplete is only an utterance boundary.
                    if (
                        getattr(server_content, "turn_complete", False)
                        and self._requires_interaction_status()
                        and interaction_status != "IDLE"
                    ):
                        from kratos_agent.live.echo_guard import get_echo_guard
                        get_echo_guard().stop_speaking()
                        if self.status_hub:
                            self.status_hub.update(
                                current_state=LiveState.EXECUTING if self.status_hub.status.active_task_id else LiveState.THINKING
                            )
                        continue

                    if getattr(server_content, "turn_complete", False):
                        from kratos_agent.live.echo_guard import get_echo_guard
                        get_echo_guard().stop_speaking()

                        if self._turn_complete_event is not None:
                            self._turn_complete_event.set()

                        # Flush any remaining buffered voice sentence
                        from kratos_agent.output.voice import get_voice_buffer
                        vb = get_voice_buffer()
                        remaining_sentence = vb.flush()
                        if remaining_sentence:
                            if self.on_model_transcript:
                                try:
                                    self.on_model_transcript(remaining_sentence)
                                except Exception:
                                    pass
                            else:
                                print(f"\n⚡ [Voice] Kratos: {remaining_sentence}\n", flush=True)

                        # ── Refusal Intercept Guard ──
                        full_output = self._output_transcript_buffer.strip()
                        if full_output and self._is_refusal(full_output):
                            asyncio.ensure_future(self._intercept_refusal(full_output))
                        elif not self._task_started_in_turn:
                            # ── Action Dispatch Guard ──
                            # If the user requested an action and Gemini spoke without calling start_agent_task,
                            # auto-dispatch to Kratos Brain so the user's task is never dropped!
                            last_req = getattr(self, "_last_user_transcript", "").strip()
                            if last_req and self._is_action_request(last_req):
                                self._last_user_transcript = ""  # Clear so it is never re-dispatched!
                                logger.info(f"[GEMINI] Action detected without tool call. Auto-dispatching task: '{last_req[:80]}'")
                                asyncio.ensure_future(self.router.handle_tool_call("start_agent_task", {"task_description": last_req}))

                        self._output_transcript_buffer = ""
                        self._task_started_in_turn = False

                        if self.status_hub:
                            self.status_hub.update(
                                current_state=LiveState.EXECUTING if self.status_hub.status.active_task_id else LiveState.IDLE
                            )

                    elif interaction_status == "IDLE":
                        if self._turn_complete_event is not None:
                            self._turn_complete_event.set()
                        if self.status_hub:
                            self.status_hub.update(
                                current_state=LiveState.EXECUTING if self.status_hub.status.active_task_id else LiveState.IDLE
                            )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[LiveSession] Receive loop error: {e}")

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

    async def send_text_turn(self, text: str, timeout: float = 30.0) -> str:
        """Sends user text as a complete turn to Gemini Live and waits for model turn completion."""
        if self.session is None or not text.strip():
            return ""

        event = asyncio.Event()
        self._turn_complete_event = event
        self._turn_transcript_chunks = []
        self._last_user_transcript = text.strip()
        self._task_started_in_turn = False

        try:
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
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.session = None
        if self.status_hub:
            self.status_hub.update(gemini_connected=False, current_state=LiveState.DISCONNECTED, live_health="offline")
