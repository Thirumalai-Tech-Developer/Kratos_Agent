"""
Global Hotkey Listener for Panic Button.
Listens for Ctrl+Alt+Shift+F12 OS-wide to trigger the emergency stop.
"""
import logging
import threading

logger = logging.getLogger(__name__)

class PanicHotkeyListener:
    def __init__(self):
        self.listener_thread = None
        self._stop_event = threading.Event()
        
    def _on_activate(self):
        logger.warning("PANIC HOTKEY DETECTED: Ctrl+Alt+Shift+F12")
        from kratos_agent.ccs.safety_ops import safety
        safety.panic()

    def _run_listener(self):
        try:
            from pynput import keyboard
            # Define the exact combination
            combination = {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.Key.shift, keyboard.Key.f12}
            # Or use GlobalHotKeys
            hotkey = '<ctrl>+<alt>+<shift>+<f12>'
            
            with keyboard.GlobalHotKeys({hotkey: self._on_activate}) as h:
                h.join()
        except ImportError:
            logger.error("pynput not installed. Global panic hotkey disabled.")
        except Exception as e:
            logger.error(f"Failed to bind global hotkey: {e}")

    def start(self):
        if self.listener_thread is None or not self.listener_thread.is_alive():
            self.listener_thread = threading.Thread(target=self._run_listener, daemon=True)
            self.listener_thread.start()
            logger.info("Panic hotkey listener started (Ctrl+Alt+Shift+F12).")

    def stop(self):
        self._stop_event.set()
        # pynput listeners are daemon threads so they die with the process

panic_hotkey = PanicHotkeyListener()
