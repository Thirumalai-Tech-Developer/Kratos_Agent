import ctypes
from typing import Tuple

user32 = ctypes.windll.user32

KEY_MAP = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11,
    "alt": 0x12, "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25,
    "up": 0x26, "right": 0x27, "down": 0x28, "prtscr": 0x2C, "insert": 0x2D,
    "delete": 0x2E, "lwin": 0x5B, "rwin": 0x5C, "num0": 0x60, "num1": 0x61,
    "num2": 0x62, "num3": 0x63, "num4": 0x64, "num5": 0x65, "num6": 0x66,
    "num7": 0x67, "num8": 0x68, "num9": 0x69, "mul": 0x6A, "add": 0x6B,
    "sep": 0x6C, "sub": 0x6D, "dec": 0x6E, "div": 0x6F,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "numlock": 0x90, "scrolllock": 0x91,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3, "lalt": 0xA4, "ralt": 0xA5
}

EXTENDED_KEYS = {
    "pageup", "pagedown", "end", "home", "left", "up", "right", "down",
    "insert", "delete", "lwin", "rwin", "div", "ralt", "rctrl", "prtscr"
}

def get_vk_and_scancode(key: str) -> Tuple[int, int, bool]:
    """Returns (vk_code, scan_code, is_extended)"""
    key = key.lower()
    vk = KEY_MAP.get(key)
    if vk is None:
        if len(key) == 1:
            # simple alphanumeric
            vk_short = ctypes.windll.user32.VkKeyScanW(ord(key))
            vk = vk_short & 0xFF
        else:
            vk = 0
            
    # MAPVK_VK_TO_VSC = 0
    sc = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    ext = key in EXTENDED_KEYS
    return vk, sc, ext
