"""Microphone input capture with real-time VAD, device selection, and instant interruption for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
import math
import struct
import time
from typing import Any, Callable, Dict, List, Optional

from .events import LiveState, LiveStatusHub

logger = logging.getLogger(__name__)

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def get_input_devices() -> List[Dict[str, Any]]:
    """Enumerate all available audio input devices (microphones)."""
    devices: List[Dict[str, Any]] = []

    # 1. Try sounddevice
    try:
        import sounddevice as sd
        all_devs = sd.query_devices()
        try:
            default_in = sd.default.device[0]
        except Exception:
            default_in = -1

        hostapis = sd.query_hostapis()

        for idx, dev in enumerate(all_devs):
            max_in = dev.get("max_input_channels", 0)
            if max_in > 0:
                ha_idx = dev.get("hostapi", 0)
                ha_name = hostapis[ha_idx]["name"] if ha_idx < len(hostapis) else ""
                # Skip WDM-KS devices: PortAudio does not support blocking read API on WDM-KS
                if "wdm" in ha_name.lower():
                    continue
                devices.append({
                    "index": idx,
                    "name": dev.get("name", f"Microphone {idx}"),
                    "hostapi": ha_name,
                    "channels": max_in,
                    "default_samplerate": dev.get("default_samplerate", 16000),
                    "is_default": (idx == default_in),
                })
        if devices:
            return devices
    except Exception as e:
        logger.debug(f"[Microphone] sounddevice device query failed: {e}")

    # 2. Try pyaudio fallback
    try:
        import pyaudio
        pya = pyaudio.PyAudio()
        try:
            default_info = pya.get_default_input_device_info()
            default_idx = default_info.get("index", -1)
        except Exception:
            default_idx = -1

        for i in range(pya.get_device_count()):
            try:
                info = pya.get_device_info_by_index(i)
                max_in = info.get("maxInputChannels", 0)
                if max_in > 0:
                    devices.append({
                        "index": i,
                        "name": info.get("name", f"Microphone {i}"),
                        "hostapi": info.get("hostApi", ""),
                        "channels": max_in,
                        "default_samplerate": info.get("defaultSampleRate", 16000),
                        "is_default": (i == default_idx),
                    })
            except Exception:
                continue
        pya.terminate()
    except Exception as e:
        logger.debug(f"[Microphone] pyaudio device query failed: {e}")

    return devices


def _calculate_rms(data: bytes) -> int:
    """Calculates RMS (Root Mean Square) energy of 16-bit signed PCM audio."""
    if not data:
        return 0

    if _HAS_NUMPY:
        try:
            samples = np.frombuffer(data, dtype=np.int16)
            if len(samples) == 0:
                return 0
            return int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        except Exception:
            pass

    # Pure Python / struct fallback
    count = len(data) // 2
    if count == 0:
        return 0
    try:
        shorts = struct.unpack(f"<{count}h", data)
        return int(math.sqrt(sum(s * s for s in shorts) / count))
    except Exception:
        return 0


def get_windows_endpoint_mute_states() -> Dict[str, bool]:
    """Queries Windows CoreAudio endpoint mute states for active audio capture devices."""
    import sys
    states: Dict[str, bool] = {}
    if sys.platform != "win32":
        return states
    try:
        import ctypes
        from ctypes import wintypes
        ole32 = ctypes.oledll.ole32
        ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', wintypes.BYTE * 8)]

        CLSID_MMDeviceEnumerator = GUID(0xBCDE0395, 0xE52F, 0x467C, (wintypes.BYTE * 8)(0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E))
        IID_IMMDeviceEnumerator = GUID(0xA95664D2, 0x9614, 0x4F35, (wintypes.BYTE * 8)(0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6))
        IID_IAudioEndpointVolume = GUID(0x5CDF2C82, 0x841E, 0x4546, (wintypes.BYTE * 8)(0x97, 0x22, 0x0C, 0xF7, 0x40, 0x78, 0x22, 0x9A))

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]
        PKEY_Device_FriendlyName = PROPERTYKEY(GUID(0xA45C254E, 0xDF1C, 0x4EFD, (wintypes.BYTE * 8)(0x80, 0x20, 0x67, 0xD1, 0x46, 0xA8, 0x50, 0xE0)), 14)

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [('vt', wintypes.WORD), ('wReserved1', wintypes.WORD), ('wReserved2', wintypes.WORD), ('wReserved3', wintypes.WORD), ('pwszVal', wintypes.LPWSTR), ('dummy', wintypes.BYTE * 8)]

        class IMMDevice(ctypes.Structure): pass
        class IMMDeviceEnumerator(ctypes.Structure): pass
        class IMMDeviceCollection(ctypes.Structure): pass
        class IPropertyStore(ctypes.Structure): pass

        IMMDeviceEnumerator._fields_ = [('lpVtbl', ctypes.POINTER(ctypes.c_void_p))]
        IMMDeviceCollection._fields_ = [('lpVtbl', ctypes.POINTER(ctypes.c_void_p))]
        IMMDevice._fields_ = [('lpVtbl', ctypes.POINTER(ctypes.c_void_p))]
        IPropertyStore._fields_ = [('lpVtbl', ctypes.POINTER(ctypes.c_void_p))]

        pEnum = ctypes.POINTER(IMMDeviceEnumerator)()
        if ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, 1, ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(pEnum)) != 0:
            return states

        pCol = ctypes.POINTER(IMMDeviceCollection)()
        EnumAudioEndpoints = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(IMMDeviceCollection)))(pEnum.contents.lpVtbl[3])
        if EnumAudioEndpoints(pEnum, 1, 1, ctypes.byref(pCol)) != 0:
            return states

        colVtbl = pCol.contents.lpVtbl
        GetCount = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT))(colVtbl[3])
        Item = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.POINTER(IMMDevice)))(colVtbl[4])

        count = wintypes.UINT()
        GetCount(pCol, ctypes.byref(count))

        for i in range(count.value):
            pDev = ctypes.POINTER(IMMDevice)()
            Item(pCol, i, ctypes.byref(pDev))
            devVtbl = pDev.contents.lpVtbl

            OpenPropertyStore = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(IPropertyStore)))(devVtbl[4])
            pStore = ctypes.POINTER(IPropertyStore)()
            name = ""
            if OpenPropertyStore(pDev, 0, ctypes.byref(pStore)) == 0:
                GetValue = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(pStore.contents.lpVtbl[5])
                val = PROPVARIANT()
                if GetValue(pStore, ctypes.byref(PKEY_Device_FriendlyName), ctypes.byref(val)) == 0:
                    if val.vt == 31 and val.pwszVal:
                        name = val.pwszVal

            Activate = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(devVtbl[3])
            pVol = ctypes.c_void_p()
            if Activate(pDev, ctypes.byref(IID_IAudioEndpointVolume), 1, None, ctypes.byref(pVol)) == 0:
                volVtbl = ctypes.cast(pVol, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                GetMute = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL))(volVtbl[15])
                is_muted = wintypes.BOOL()
                if GetMute(pVol, ctypes.byref(is_muted)) == 0:
                    if name:
                        states[name.lower().strip()] = bool(is_muted.value)
    except Exception as e:
        logger.debug(f"[Microphone] Could not query Windows endpoint mute states: {e}")
    return states


_WARNED_DEVICES: set[tuple[str, str]] = set()


class MicrophoneListener:
    """Captures 16kHz 16-bit PCM audio from microphone, detects speech/VAD, and queues for Gemini Live."""

    def __init__(
        self,
        out_queue: asyncio.Queue[Dict[str, Any]],
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        device: Optional[int | str] = None,
        vad_threshold: int = 80,
        vad_silence_seconds: float = 1.2,
        on_speech_started: Optional[Callable[[], Any]] = None,
        on_speech_stopped: Optional[Callable[[], Any]] = None,
        on_interruption: Optional[Callable[[], Any]] = None,
        status_hub: Optional[LiveStatusHub] = None,
    ) -> None:
        self.out_queue = out_queue
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device = device
        self.vad_threshold = vad_threshold
        self.vad_silence_seconds = vad_silence_seconds
        self.on_speech_started = on_speech_started
        self.on_speech_stopped = on_speech_stopped
        self.on_interruption = on_interruption
        self.status_hub = status_hub

        self.is_running = False
        self.is_muted = False
        self._stream: Any = None

        # Resolve initial device info
        try:
            self.device_index, self.device_name = self._resolve_device()
        except Exception:
            self.device_index = None
            self.device_name = "Default Microphone"

        # VAD state
        self.is_user_speaking: bool = False
        self._last_speech_time: float = 0.0

    def mute(self) -> None:
        self.is_muted = True
        if self.status_hub:
            self.status_hub.update(muted=True, microphone_health="muted")

    def unmute(self) -> None:
        self.is_muted = False
        mute_states = get_windows_endpoint_mute_states()
        is_hw_muted = self._is_device_muted(self.device_name, mute_states) if self.device_name else False
        if self.status_hub:
            self.status_hub.update(
                muted=is_hw_muted,
                microphone_health="muted" if is_hw_muted else ("online" if self.is_running else "offline"),
            )

    def health_check(self) -> Dict[str, Any]:
        """Returns structured microphone health without crashing if muted (§36)."""
        mute_states = get_windows_endpoint_mute_states()
        is_hw_muted = self._is_device_muted(self.device_name, mute_states) if self.device_name else False
        available = self.device_index is not None or bool(get_input_devices())
        muted = self.is_muted or is_hw_muted
        health_state = "muted" if muted else ("online" if self.is_running else ("offline" if not available else "starting"))
        return {
            "device": self.device_name,
            "device_index": self.device_index,
            "available": available,
            "muted": muted,
            "hardware_muted": is_hw_muted,
            "software_muted": self.is_muted,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "is_running": self.is_running,
            "health": health_state,
            "error": None,
        }

    def _resolve_device(self) -> tuple[Optional[int], str]:
        """Resolves device index and display name from configured device setting."""
        devices = get_input_devices()
        if not devices:
            return None, "Default Microphone"

        mute_states = get_windows_endpoint_mute_states()

        # Explicit integer or integer string
        if self.device is not None:
            dev_str = str(self.device).strip()
            if dev_str.isdigit():
                idx = int(dev_str)
                for d in devices:
                    if d["index"] == idx:
                        self._check_and_warn_muted(d["name"], mute_states)
                        return idx, d["name"]
                logger.warning(f"[Microphone] Specified device index {idx} not found in available devices.")

            # String matching by substring
            lower_target = dev_str.lower()
            for d in devices:
                if lower_target in d["name"].lower():
                    self._check_and_warn_muted(d["name"], mute_states)
                    return d["index"], d["name"]
            logger.warning(f"[Microphone] Specified device '{self.device}' not found. Falling back to default.")

        # Default device
        default_dev = None
        for d in devices:
            if d.get("is_default"):
                default_dev = d
                break
        if not default_dev and devices:
            default_dev = devices[0]

        # Check if default device is muted in Windows
        if default_dev:
            def_name = default_dev["name"]
            is_def_muted = self._is_device_muted(def_name, mute_states)

            if is_def_muted:
                warn_key = (def_name.lower().strip(), "muted")
                if warn_key not in _WARNED_DEVICES:
                    _WARNED_DEVICES.add(warn_key)
                    logger.warning(
                        f"[Microphone] ⚠️ Default device '{def_name}' is currently MUTED in Windows (laptop mic mute key F4 / Fn+F4 or Windows Settings)."
                    )
                # Search for an active unmuted alternative (skip generic pseudo-devices)
                for alt_d in devices:
                    if alt_d["index"] == default_dev["index"]:
                        continue
                    alt_lower = alt_d["name"].lower()
                    if any(pseudo in alt_lower for pseudo in ("sound mapper", "primary sound capture", "stereo mix")):
                        continue
                    if not self._is_device_muted(alt_d["name"], mute_states):
                        logger.info(
                            f"[Microphone] 🔄 Auto-switched to active unmuted microphone: [{alt_d['index']}] '{alt_d['name']}'"
                        )
                        return alt_d["index"], alt_d["name"]

                # No unmuted alternative found, warn user explicitly once
                warn_msg = f"Microphone '{def_name}' is MUTED in Windows. Unmute via laptop keyboard (F4 / Fn+F4) or Windows Sound Settings."
                if warn_key not in _WARNED_DEVICES:
                    _WARNED_DEVICES.add(warn_key)
                    logger.warning(f"[Microphone] ⚠️ {warn_msg}")
                if self.status_hub:
                    self.status_hub.update(microphone_health="muted", muted=True, last_error=warn_msg)

            return default_dev["index"], default_dev["name"]

        return devices[0]["index"], devices[0]["name"]

    def _is_device_muted(self, dev_name: str, mute_states: Dict[str, bool]) -> bool:
        """Helper to match device name against Windows CoreAudio mute states."""
        dev_lower = dev_name.lower().strip()
        for k, muted in mute_states.items():
            if k in dev_lower or dev_lower in k:
                return muted
        return False

    def _check_and_warn_muted(self, dev_name: str, mute_states: Dict[str, bool]) -> None:
        """Warn user once if explicitly configured device is muted (§35)."""
        if self._is_device_muted(dev_name, mute_states):
            warn_key = (dev_name.lower().strip(), "muted")
            warn_msg = f"Configured microphone '{dev_name}' is MUTED in Windows. Unmute via laptop keyboard (F4 / Fn+F4) or Windows Sound Settings."
            if warn_key not in _WARNED_DEVICES:
                _WARNED_DEVICES.add(warn_key)
                logger.warning(f"[Microphone] ⚠️ {warn_msg}")
            if self.status_hub:
                self.status_hub.update(microphone_health="muted", muted=True, last_error=warn_msg)


    def _process_audio_chunk(self, data: bytes) -> None:
        """Processes real-time audio chunk for VAD and queues for Gemini Live."""
        rms = _calculate_rms(data)

        # 1. Voice Activity Detection (VAD)
        now = time.monotonic()
        if rms >= self.vad_threshold:
            if not self.is_user_speaking:
                self.is_user_speaking = True
                logger.debug(f"[Microphone] Speech started (RMS: {rms} >= {self.vad_threshold})")
                if self.on_speech_started:
                    try:
                        self.on_speech_started()
                    except Exception as e:
                        logger.warning(f"[Microphone] on_speech_started error: {e}")
                if self.on_interruption:
                    try:
                        self.on_interruption()
                    except Exception as e:
                        logger.warning(f"[Microphone] on_interruption error: {e}")
            self._last_speech_time = now
        else:
            if self.is_user_speaking and (now - self._last_speech_time) >= self.vad_silence_seconds:
                self.is_user_speaking = False
                logger.debug(f"[Microphone] Speech stopped after {self.vad_silence_seconds:.1f}s silence")
                if self.on_speech_stopped:
                    try:
                        self.on_speech_stopped()
                    except Exception as e:
                        logger.warning(f"[Microphone] on_speech_stopped error: {e}")

        # 2. Queue for Gemini Live
        payload = {
            "data": data,
            "mime_type": f"audio/pcm;rate={self.sample_rate}",
        }
        try:
            self.out_queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop oldest to preserve real-time low latency
            try:
                self.out_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.out_queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def run(self) -> None:
        """Runs the microphone capture loop continuously."""
        self.is_running = True

        use_sounddevice = False
        try:
            import sounddevice as sd
            use_sounddevice = True
        except ImportError:
            pass

        if use_sounddevice:
            await self._run_sounddevice()
        else:
            await self._run_pyaudio()

    async def _run_sounddevice(self) -> None:
        import sounddevice as sd

        try:
            self.device_index, self.device_name = self._resolve_device()
            logger.info(f"[Microphone] Using input device [{self.device_index}]: {self.device_name}")
        except Exception as e:
            logger.warning(f"[Microphone] Could not query input device: {e}")
            self.device_index = None
            self.device_name = "Default Microphone"

        try:
            stream_kwargs: Dict[str, Any] = {
                "samplerate": self.sample_rate,
                "blocksize": self.chunk_size,
                "channels": self.channels,
                "dtype": "int16",
            }
            if self.device_index is not None:
                stream_kwargs["device"] = self.device_index

            self._stream = sd.RawInputStream(**stream_kwargs)
            self._stream.start()
            if self.status_hub:
                self.status_hub.clear_error("microphone")
                self.status_hub.update(microphone_active=True, microphone_health="online")
        except Exception as e:
            err_msg = f"Failed to open microphone stream ({type(e).__name__}): {e}"
            logger.warning(f"[Microphone] {err_msg}")
            if self.status_hub:
                self.status_hub.update(microphone_active=False, microphone_health="error")
                self.status_hub.report_error("microphone", err_msg)
            self.is_running = False
            return

        try:
            while self.is_running:
                data, overflowed = await asyncio.to_thread(
                    self._stream.read, self.chunk_size
                )
                if self.is_muted or not data:
                    await asyncio.sleep(0.01)
                    continue

                raw_bytes = bytes(data)
                self._process_audio_chunk(raw_bytes)

        except asyncio.CancelledError:
            pass
        except RuntimeError as e:
            if "cannot schedule new futures after shutdown" not in str(e):
                logger.warning(f"[Microphone] Runtime error during audio capture: {e}")
        except Exception as e:
            logger.warning(f"[Microphone] Error during audio capture: {e}")
            if self.status_hub:
                self.status_hub.update(microphone_health="error")
                self.status_hub.report_error("microphone", f"Microphone capture error: {e}")
        finally:
            self.is_running = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self.status_hub:
                self.status_hub.update(microphone_active=False, microphone_health="offline")

    async def _run_pyaudio(self) -> None:
        try:
            import pyaudio
        except ImportError:
            err_msg = "Neither sounddevice nor pyaudio is installed. Microphone offline."
            logger.warning(f"[Microphone] {err_msg}")
            if self.status_hub:
                self.status_hub.update(microphone_active=False, last_error=err_msg)
            self.is_running = False
            return

        pya = None
        try:
            pya = pyaudio.PyAudio()
            self.device_index, self.device_name = self._resolve_device()
            logger.info(f"[Microphone] PyAudio using input device [{self.device_index}]: {self.device_name}")

            stream_kwargs: Dict[str, Any] = {
                "format": pyaudio.paInt16,
                "channels": self.channels,
                "rate": self.sample_rate,
                "input": True,
                "frames_per_buffer": self.chunk_size,
            }
            if self.device_index is not None:
                stream_kwargs["input_device_index"] = self.device_index

            self._stream = await asyncio.to_thread(pya.open, **stream_kwargs)
            if self.status_hub:
                self.status_hub.update(microphone_active=True)
        except Exception as e:
            err_msg = f"Failed to open PyAudio input ({type(e).__name__}): {e}"
            logger.warning(f"[Microphone] {err_msg}")
            if self.status_hub:
                self.status_hub.update(microphone_active=False, last_error=err_msg)
            self.is_running = False
            if pya:
                try:
                    pya.terminate()
                except Exception:
                    pass
            return

        try:
            kwargs = {"exception_on_overflow": False}
            while self.is_running:
                data = await asyncio.to_thread(
                    self._stream.read, self.chunk_size, **kwargs
                )
                if self.is_muted or not data:
                    await asyncio.sleep(0.01)
                    continue

                raw_bytes = bytes(data) if not isinstance(data, bytes) else data
                self._process_audio_chunk(raw_bytes)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[Microphone] Error during PyAudio capture: {e}")
            if self.status_hub:
                self.status_hub.update(microphone_health="error")
                self.status_hub.report_error("microphone", f"PyAudio capture error: {e}")
        finally:
            self.is_running = False
            if self._stream:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if pya:
                try:
                    pya.terminate()
                except Exception:
                    pass
            if self.status_hub:
                self.status_hub.update(microphone_active=False)

    def stop(self) -> None:
        self.is_running = False
        if self._stream:
            try:
                if hasattr(self._stream, "stop"):
                    self._stream.stop()
                elif hasattr(self._stream, "stop_stream"):
                    self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self.status_hub:
            self.status_hub.update(microphone_active=False)


def get_microphone_health() -> Dict[str, Any]:
    """Module-level helper to check microphone health without instantiating listener (§36)."""
    devices = get_input_devices()
    mute_states = get_windows_endpoint_mute_states()
    default_dev = next((d for d in devices if d.get("is_default")), (devices[0] if devices else None))
    dev_name = default_dev["name"] if default_dev else "No Microphone Detected"
    is_muted = False
    if default_dev:
        dev_lower = dev_name.lower().strip()
        for k, muted in mute_states.items():
            if k in dev_lower or dev_lower in k:
                is_muted = muted
                break
    return {
        "device": dev_name,
        "available": bool(devices),
        "muted": is_muted,
        "sample_rate": 16000,
        "channels": 1,
        "error": None if devices else "No audio input devices detected",
    }

