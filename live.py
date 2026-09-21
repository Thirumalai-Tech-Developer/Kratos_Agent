# live.py

"""
Gemini Live API - Audio + Camera + Screen + Text

Install:
    python -m pip install -U google-genai opencv-python pyaudio pillow mss python-dotenv

Environment:
    GEMINI_API_KEY=your_api_key_here

Run:
    python live.py
    python live.py --mode camera
    python live.py --mode screen
    python live.py --mode none

Commands:
    Type a message and press Enter.
    Type q and press Enter to quit.

Important:
    Use headphones to avoid microphone/speaker feedback.
"""

import argparse
import asyncio
import io
import os
import traceback

import cv2
import mss
import pyaudio
from dotenv import load_dotenv
from PIL import Image

from google import genai
from google.genai import types


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "API key not found.\n"
        "Set GEMINI_API_KEY in your .env file or environment."
    )


# ============================================================
# AUDIO CONFIGURATION
# ============================================================

FORMAT = pyaudio.paInt16
CHANNELS = 1

SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000

CHUNK_SIZE = 1024


# ============================================================
# MODEL
# ============================================================

MODEL = "gemini-3.8-live-extended-thinking"

DEFAULT_MODE = "camera"


# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(
    api_key=API_KEY,
)


# ============================================================
# LIVE CONFIG
# ============================================================

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],

    # Extended thinking
    thinking_config=types.ThinkingConfig(
        thinking_level="high",
    ),

    # Voice
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name="Zephyr"
            )
        )
    ),

    # Transcription
    input_audio_transcription=types.AudioTranscriptionConfig(),

    output_audio_transcription=types.AudioTranscriptionConfig(),

    # Context compression
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=25600,
        sliding_window=types.SlidingWindow(
            target_tokens=12800
        ),
    ),
)


# ============================================================
# PYAudio
# ============================================================

pya = pyaudio.PyAudio()


# ============================================================
# MAIN LOOP
# ============================================================

class AudioVideoLoop:

    def __init__(self, video_mode=DEFAULT_MODE):

        self.video_mode = video_mode

        self.audio_in_queue = asyncio.Queue()

        self.out_queue = asyncio.Queue(
            maxsize=5
        )

        self.session = None

        self.audio_stream = None


    # ========================================================
    # MICROPHONE
    # ========================================================

    def _select_input_device(self):

        # Enumerate input-capable audio devices and pick one.
        # Returns (device_index, device_name, reason_if_none).
        # Never raises -- a None index just means "no usable microphone".

        try:
            count = pya.get_device_count()
        except Exception as e:
            return None, None, f"could not enumerate audio devices ({e})"

        candidates = []

        for i in range(count):

            try:
                info = pya.get_device_info_by_index(i)
            except Exception:
                continue

            if info.get("maxInputChannels", 0) > 0:
                candidates.append(info)

        if not candidates:

            return None, None, (
                "no input-capable audio device was found. Check that a "
                "microphone is connected, and that this app/terminal has "
                "microphone permission in your OS privacy settings."
            )

        # Prefer the OS default input device when it's among the candidates.
        try:

            default_info = pya.get_default_input_device_info()

            for info in candidates:
                if info["index"] == default_info["index"]:
                    return info["index"], info.get("name", "Unknown"), None

        except Exception:
            pass  # no default device configured; fall back below

        info = candidates[0]

        return info["index"], info.get("name", "Unknown"), None


    def _diagnose_mic_error(self, error):

        # Turn a raw PyAudio/PortAudio OSError into an actionable message.

        message = str(error)

        if "-9999" in message or "Unanticipated host error" in message:

            return (
                "[Audio] Microphone error -9999 (Unanticipated host error). "
                "This is almost always one of:\n"
                "    1. Microphone permission not granted to this app/terminal "
                "in your OS privacy settings.\n"
                "    2. The selected device was unplugged, or the OS default "
                "input device changed.\n"
                "    3. The requested sample rate/channel count isn't "
                "supported by this device.\n"
                f"  Raw error: {error}"
            )

        return f"[Audio] Could not open microphone: {error}"


    async def listen_audio(self):

        print("[Audio] Detecting microphone...")

        device_index, device_name, reason = await asyncio.to_thread(
            self._select_input_device
        )

        if device_index is None:

            print(
                f"[Audio] No usable microphone found ({reason}). "
                f"Voice input is disabled for this session -- "
                f"screen/camera/text will continue to work."
            )

            return

        print(
            f"[Audio] Using microphone: {device_name}"
        )

        try:

            self.audio_stream = await asyncio.to_thread(
                pya.open,

                format=FORMAT,

                channels=CHANNELS,

                rate=SEND_SAMPLE_RATE,

                input=True,

                input_device_index=device_index,

                frames_per_buffer=CHUNK_SIZE,
            )

        except OSError as e:

            print(self._diagnose_mic_error(e))

            print(
                "[Audio] Voice input is disabled for this session -- "
                "screen/camera/text will continue to work."
            )

            return

        kwargs = {
            "exception_on_overflow": False
        }

        try:

            while True:

                try:

                    data = await asyncio.to_thread(
                        self.audio_stream.read,
                        CHUNK_SIZE,
                        **kwargs,
                    )

                except OSError as e:

                    print(
                        f"[Audio] Lost the microphone mid-session: {e}"
                    )

                    print(
                        "[Audio] Voice input has stopped -- "
                        "screen/camera/text will continue to work."
                    )

                    break

                payload = {
                    "data": data,
                    "mime_type": "audio/pcm;rate=16000",
                }

                try:

                    self.out_queue.put_nowait(
                        payload
                    )

                except asyncio.QueueFull:

                    # Drop oldest packet to keep audio real-time
                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass

                    try:
                        self.out_queue.put_nowait(
                            payload
                        )
                    except asyncio.QueueFull:
                        pass

        except asyncio.CancelledError:
            pass

        finally:

            if self.audio_stream:

                try:
                    self.audio_stream.stop_stream()
                except Exception:
                    pass

                try:
                    self.audio_stream.close()
                except Exception:
                    pass

                self.audio_stream = None


    # ========================================================
    # PLAY GEMINI AUDIO
    # ========================================================

    async def play_audio(self):

        print("[Audio] Opening speaker...")

        try:

            stream = await asyncio.to_thread(
                pya.open,

                format=FORMAT,

                channels=CHANNELS,

                rate=RECEIVE_SAMPLE_RATE,

                output=True,
            )

        except OSError as e:

            print(
                f"[Audio] Could not open speaker output: {e}"
            )

            print(
                "[Audio] Spoken responses are disabled for this session -- "
                "Gemini's text responses will still print to the console."
            )

            return

        try:

            while True:

                audio_data = await self.audio_in_queue.get()

                if not audio_data:
                    continue

                try:

                    await asyncio.to_thread(
                        stream.write,
                        audio_data,
                    )

                except OSError as e:

                    print(
                        f"[Audio] Lost the speaker output mid-session: {e}"
                    )

                    print(
                        "[Audio] Spoken responses have stopped -- "
                        "Gemini's text responses will still print to the console."
                    )

                    break

        except asyncio.CancelledError:
            pass

        finally:

            try:
                stream.stop_stream()
            except Exception:
                pass

            try:
                stream.close()
            except Exception:
                pass


    # ========================================================
    # RECEIVE GEMINI RESPONSE
    # ========================================================

    async def receive_audio(self):

        try:

            while True:

                async for response in self.session.receive():

                    server_content = response.server_content

                    if server_content is None:
                        continue


                    # ----------------------------------------
                    # INTERRUPTION
                    # ----------------------------------------

                    if server_content.interrupted:

                        while not self.audio_in_queue.empty():

                            try:
                                self.audio_in_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break


                    # ----------------------------------------
                    # MODEL AUDIO
                    # ----------------------------------------

                    if server_content.model_turn:

                        for part in server_content.model_turn.parts:

                            if part.inline_data:

                                data = part.inline_data.data

                                if data:

                                    try:

                                        self.audio_in_queue.put_nowait(
                                            data
                                        )

                                    except asyncio.QueueFull:

                                        try:
                                            self.audio_in_queue.get_nowait()
                                        except asyncio.QueueEmpty:
                                            pass

                                        try:
                                            self.audio_in_queue.put_nowait(
                                                data
                                            )
                                        except asyncio.QueueFull:
                                            pass


                    # ----------------------------------------
                    # INPUT TRANSCRIPTION
                    # ----------------------------------------

                    if server_content.input_transcription:

                        text = (
                            server_content
                            .input_transcription
                            .text
                        )

                        if text:

                            print(
                                f"\nYou: {text}",
                                end="",
                                flush=True,
                            )


                    # ----------------------------------------
                    # OUTPUT TRANSCRIPTION
                    # ----------------------------------------

                    if server_content.output_transcription:

                        text = (
                            server_content
                            .output_transcription
                            .text
                        )

                        if text:

                            print(
                                f"\nGemini: {text}",
                                end="",
                                flush=True,
                            )


                    # ----------------------------------------
                    # TURN STATUS
                    # ----------------------------------------

                    status = getattr(
                        response,
                        "interaction_status",
                        None,
                    )

                    if status == "IN_PROGRESS":

                        print(
                            "\n[Gemini] Thinking...",
                            end="",
                            flush=True,
                        )

                    elif status == "IDLE":

                        print(
                            "\n[Gemini] Ready.",
                            flush=True,
                        )


        except asyncio.CancelledError:
            pass


    # ========================================================
    # CAMERA
    # ========================================================

    def _capture_frame(self, cap):

        ret, frame = cap.read()

        if not ret:

            return None

        # OpenCV BGR -> RGB
        frame_rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB,
        )

        img = Image.fromarray(
            frame_rgb
        )

        # Limit image size
        img.thumbnail(
            [1024, 1024]
        )

        image_io = io.BytesIO()

        img.save(
            image_io,
            format="jpeg",
            quality=85,
        )

        image_io.seek(0)

        return {
            "mime_type": "image/jpeg",
            "data": image_io.read(),
        }


    async def capture_frames(self):

        print("[Camera] Opening camera...")

        cap = await asyncio.to_thread(
            cv2.VideoCapture,
            0,
        )

        if not cap.isOpened():

            print(
                "[Camera] Could not open the default camera. "
                "Camera input is disabled for this session -- "
                "audio/screen/text will continue to work."
            )

            try:
                cap.release()
            except Exception:
                pass

            return

        try:

            while True:

                frame = await asyncio.to_thread(
                    self._capture_frame,
                    cap,
                )

                if frame is None:

                    print(
                        "[Camera] Failed to capture frame."
                    )

                    break

                try:

                    self.out_queue.put_nowait(
                        frame
                    )

                except asyncio.QueueFull:

                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass

                    try:
                        self.out_queue.put_nowait(
                            frame
                        )
                    except asyncio.QueueFull:
                        pass

                # Gemini Live accepts video frames approximately
                # once per second for this type of application.
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            pass

        finally:

            cap.release()

            print(
                "[Camera] Camera released."
            )


    # ========================================================
    # SCREEN CAPTURE
    # ========================================================

    def _capture_screen(self):

        with mss.mss() as sct:

            monitor = sct.monitors[0]

            screenshot = sct.grab(
                monitor
            )

            img = Image.frombytes(
                "RGB",
                screenshot.size,
                screenshot.rgb,
            )

            # Resize if extremely large
            img.thumbnail(
                [1920, 1080]
            )

            image_io = io.BytesIO()

            img.save(
                image_io,
                format="jpeg",
                quality=80,
            )

            image_io.seek(0)

            return {
                "mime_type": "image/jpeg",
                "data": image_io.read(),
            }


    async def capture_screen(self):

        print("[Screen] Screen capture started.")

        try:

            while True:

                try:

                    frame = await asyncio.to_thread(
                        self._capture_screen
                    )

                except Exception as e:

                    print(
                        f"[Screen] Screen capture failed: {e}"
                    )

                    print(
                        "[Screen] Screen input is disabled for this session -- "
                        "audio/camera/text will continue to work."
                    )

                    break

                if frame is None:
                    break

                try:

                    self.out_queue.put_nowait(
                        frame
                    )

                except asyncio.QueueFull:

                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass

                    try:
                        self.out_queue.put_nowait(
                            frame
                        )
                    except asyncio.QueueFull:
                        pass

                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            pass


    # ========================================================
    # SEND AUDIO / VIDEO TO GEMINI
    # ========================================================

    async def send_realtime(self):

        try:

            while True:

                msg = await self.out_queue.get()

                blob = types.Blob(
                    data=msg["data"],
                    mime_type=msg["mime_type"],
                )

                mime_type = msg["mime_type"]

                if mime_type.startswith("audio/"):

                    await self.session.send_realtime_input(
                        audio=blob
                    )

                else:

                    # Video/image frames
                    await self.session.send_realtime_input(
                        video=blob
                    )

        except asyncio.CancelledError:
            pass


    # ========================================================
    # TEXT INPUT
    # ========================================================

    async def send_text(self):

        try:

            while True:

                text = await asyncio.to_thread(
                    input,
                    "\nmessage > ",
                )

                text = text.strip()

                if not text:

                    continue


                # Quit
                if text.lower() == "q":

                    print(
                        "\n[System] Exiting..."
                    )

                    break


                if self.session is None:

                    print(
                        "[Error] Gemini session is not ready."
                    )

                    continue


                # Current Live API SDK
                await self.session.send_realtime_input(
                    text=text
                )

        except asyncio.CancelledError:

            pass

        except EOFError:

            pass


    # ========================================================
    # RUN
    # ========================================================

    async def run(self):

        print()
        print("=" * 60)
        print(" GEMINI LIVE API")
        print("=" * 60)
        print(f" Model : {MODEL}")
        print(f" Mode  : {self.video_mode}")
        print("=" * 60)
        print()

        try:

            async with client.aio.live.connect(
                model=MODEL,
                config=CONFIG,
            ) as session:

                self.session = session

                print(
                    "[Gemini] Live session connected."
                )

                print(
                    "[Gemini] Waiting for input..."
                )

                async with asyncio.TaskGroup() as tg:

                    send_text_task = tg.create_task(
                        self.send_text()
                    )

                    # Audio sender
                    tg.create_task(
                        self.send_realtime()
                    )

                    # Microphone
                    tg.create_task(
                        self.listen_audio()
                    )

                    # Camera
                    if self.video_mode == "camera":

                        tg.create_task(
                            self.capture_frames()
                        )

                    # Screen
                    elif self.video_mode == "screen":

                        tg.create_task(
                            self.capture_screen()
                        )

                    # Gemini response
                    tg.create_task(
                        self.receive_audio()
                    )

                    # Audio output
                    tg.create_task(
                        self.play_audio()
                    )

                    # Wait until user types q
                    await send_text_task

                    # Stop all tasks
                    raise asyncio.CancelledError(
                        "User requested exit."
                    )

        except asyncio.CancelledError:

            print(
                "\n[System] Session stopped."
            )

        except Exception as e:

            print()
            print("=" * 60)
            print(" GEMINI LIVE ERROR")
            print("=" * 60)
            print()

            print(
                f"{type(e).__name__}: {e}"
            )

            print()

            traceback.print_exc()

            print()
            print("=" * 60)

        finally:

            self.session = None

            # Close PyAudio
            try:
                pya.terminate()
            except Exception:
                pass

            print(
                "[System] Cleanup complete."
            )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Gemini Live API Audio/Camera/Screen client"
    )

    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        choices=[
            "camera",
            "screen",
            "none",
        ],
        help="Input video source.",
    )

    args = parser.parse_args()

    loop = AudioVideoLoop(
        video_mode=args.mode
    )

    asyncio.run(
        loop.run()
    )


if __name__ == "__main__":

    main()