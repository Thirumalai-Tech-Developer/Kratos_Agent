"""Windows floating desktop AI assistant avatar for Kratos Multimodal Live.

Renders an always-on-top, draggable, edge-dockable, transparent floating avatar
using `kratos-illu.png` with dynamic state halos, on-demand vision, and fallback text input.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import webbrowser
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw, ImageTk

from .events import LiveState, LiveStatus, LiveStatusHub

logger = logging.getLogger(__name__)

TRANSPARENT_COLOR = "#010101"

# State color palette for the dynamic halo
STATE_COLORS: dict[LiveState, str] = {
    LiveState.CONNECTING: "#F59E0B",     # Amber pulse
    LiveState.CONNECTED: "#06B6D4",      # Cyan steady
    LiveState.LISTENING: "#10B981",      # Neon emerald green
    LiveState.THINKING: "#A855F7",       # Purple / violet
    LiveState.EXECUTING: "#6366F1",      # Electric indigo
    LiveState.SPEAKING: "#F97316",       # Fiery coral / orange
    LiveState.ERROR: "#EF4444",          # Crimson red
    LiveState.RECONNECTING: "#EA580C",   # Warning dark orange
    LiveState.IDLE: "#3B82F6",           # Calm blue
}

STATE_LABELS: dict[LiveState, str] = {
    LiveState.CONNECTING: "Connecting...",
    LiveState.CONNECTED: "Ready",
    LiveState.LISTENING: "Listening...",
    LiveState.THINKING: "Thinking...",
    LiveState.EXECUTING: "Executing...",
    LiveState.SPEAKING: "Speaking...",
    LiveState.ERROR: "Error",
    LiveState.RECONNECTING: "Reconnecting...",
    LiveState.IDLE: "Kratos Active",
}


def _make_circular_avatar(image_path: str, size: int, border_color: str | None = None) -> Image.Image:
    """Loads and crops an image to an antialiased circular avatar on transparent background."""
    if not os.path.exists(image_path):
        # Create a fallback placeholder image
        im = Image.new("RGBA", (size, size), (50, 50, 80, 255))
    else:
        im = Image.open(image_path).convert("RGBA")
        im = im.resize((size, size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    # Composite onto chroma-key transparent color
    bg = Image.new("RGBA", (size, size), (1, 1, 1, 255))
    bg.paste(im, (0, 0), mask=mask)

    if border_color:
        border_draw = ImageDraw.Draw(bg)
        border_draw.ellipse((1, 1, size - 2, size - 2), outline=border_color, width=2)

    return bg


class FloatingAvatar:
    """JARVIS-style Windows floating desktop companion for Kratos."""

    def __init__(
        self,
        image_path: str = "kratos-illu.png",
        status_hub: LiveStatusHub | None = None,
        on_text_submit: Callable[[str], Any] | None = None,
        on_screen_capture: Callable[[], Any] | None = None,
        on_mute_toggle: Callable[[], Any] | None = None,
        on_interrupt: Callable[[], Any] | None = None,
        web_url: str = "http://127.0.0.1:8000",
        avatar_size: int = 110,
    ) -> None:
        self.image_path = os.path.abspath(image_path)
        self.status_hub = status_hub
        self.on_text_submit = on_text_submit
        self.on_screen_capture = on_screen_capture
        self.on_mute_toggle = on_mute_toggle
        self.on_interrupt = on_interrupt
        self.web_url = web_url

        self.avatar_size = avatar_size
        self.canvas_width = avatar_size + 40
        self.canvas_height = avatar_size + 65

        self.current_state: LiveState = LiveState.CONNECTING
        self.current_transcript: str = ""
        self.is_docked: bool = False
        self.text_entry_visible: bool = False

        self._root: Any = None
        self._canvas: Any = None
        self._entry_frame: Any = None
        self._entry: Any = None
        self._photo_normal: Any = None
        self._photo_docked: Any = None
        self._avatar_item: Any = None
        self._ring_items: list[Any] = []
        self._status_text_item: Any = None
        self._halo_step: float = 0.0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Window drag offset coordinates
        self._drag_start_x: int = 0
        self._drag_start_y: int = 0
        self._last_undocked_x: int = 0
        self._last_undocked_y: int = 0

        if self.status_hub:
            self.status_hub.subscribe(self._on_status_updated)

    def _on_status_updated(self, status: LiveStatus) -> None:
        """Callback from LiveStatusHub when state changes."""
        if not self._root or self._stop_event.is_set():
            return
        new_state = status.current_state
        if isinstance(new_state, str):
            try:
                new_state = LiveState(new_state)
            except ValueError:
                new_state = LiveState.IDLE

        transcript = status.last_transcript or ""

        # Schedule thread-safe GUI update
        try:
            self._root.after(0, self._apply_state_update, new_state, transcript)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    def _apply_state_update(self, state: LiveState, transcript: str) -> None:
        """Applies state update on Tkinter main thread."""
        self.current_state = state
        self.current_transcript = transcript
        label = STATE_LABELS.get(state, "Active")
        if transcript and len(transcript) > 0:
            short_tx = transcript if len(transcript) <= 24 else transcript[:22] + ".."
            label = f"{label} | {short_tx}"

        if self._canvas and self._status_text_item:
            try:
                self._canvas.itemconfig(self._status_text_item, text=label)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

    def start(self) -> None:
        """Starts the floating avatar in a dedicated background thread."""
        if self._thread and self._thread.is_alive():
            return
        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("KRATOS_HEADLESS"):
            logger.info("[FloatingAvatar] Headless / Test environment detected. Skipping Tkinter window loop.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_gui, name="KratosFloatingAvatar", daemon=True)
        self._thread.start()
        logger.info("[FloatingAvatar] GUI thread started.")

    def stop(self) -> None:
        """Stops and destroys the floating avatar window."""
        self._stop_event.set()
        if self.status_hub:
            self.status_hub.unsubscribe(self._on_status_updated)
        if self._root:
            try:
                self._root.quit()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
            self._root = None
        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=1.0)
        logger.info("[FloatingAvatar] GUI stopped.")

    def _destroy_gui(self) -> None:
        if self._root:
            try:
                self._root.destroy()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
            self._root = None

    def _run_gui(self) -> None:
        """Tkinter main loop running on the dedicated GUI thread."""
        import tkinter as tk

        root = tk.Tk()
        self._root = root

        # Frameless & Always-on-Top
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        # Transparency on Windows using chroma key
        root.configure(bg=TRANSPARENT_COLOR)
        try:
            root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except Exception as e:
            logger.warning(f"[FloatingAvatar] Transparent color not supported: {e}")

        # Position in bottom-right corner
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        init_x = max(50, screen_width - self.canvas_width - 40)
        init_y = max(50, screen_height - self.canvas_height - 80)
        self._last_undocked_x = init_x
        self._last_undocked_y = init_y
        root.geometry(f"{self.canvas_width}x{self.canvas_height}+{init_x}+{init_y}")

        # Build Canvas
        canvas = tk.Canvas(
            root,
            width=self.canvas_width,
            height=self.canvas_height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            cursor="fleur",
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas = canvas

        # Prepare Avatar Images
        pil_normal = _make_circular_avatar(self.image_path, self.avatar_size)
        pil_docked = _make_circular_avatar(self.image_path, 46)
        self._photo_normal = ImageTk.PhotoImage(pil_normal)
        self._photo_docked = ImageTk.PhotoImage(pil_docked)

        # Center coordinates
        cx = self.canvas_width // 2
        cy = (self.avatar_size // 2) + 15

        # Draw Avatar Image
        self._avatar_item = canvas.create_image(cx, cy, image=self._photo_normal)

        # Draw Dynamic Halo Rings
        halo_color = STATE_COLORS.get(self.current_state, "#06B6D4")
        self._ring_items = [
            canvas.create_oval(cx - 58, cy - 58, cx + 58, cy + 58, outline=halo_color, width=3),
            canvas.create_oval(cx - 62, cy - 62, cx + 62, cy + 62, outline=halo_color, width=1),
        ]

        # Draw Status Label Pill below avatar
        self._status_text_item = canvas.create_text(
            cx,
            self.avatar_size + 30,
            text=STATE_LABELS.get(self.current_state, "Connecting..."),
            fill="#E2E8F0",
            font=("Segoe UI", 8, "bold"),
        )

        # Mouse Bindings
        canvas.bind("<Button-1>", self._on_mouse_down)
        canvas.bind("<B1-Motion>", self._on_mouse_drag)
        canvas.bind("<Double-Button-1>", self._on_double_click)
        canvas.bind("<Button-3>", self._show_context_menu)

        # Text Entry Frame (hidden by default)
        self._build_text_entry(root)

        # Start animation ticker
        self._animate_halo()

        # Run Tkinter Event Loop
        try:
            root.mainloop()
        except Exception as e:
            logger.warning(f"[FloatingAvatar] Mainloop error: {e}")

    def _build_text_entry(self, root: Any) -> None:
        """Constructs an expandable fallback text input pill."""
        import tkinter as tk

        entry_frame = tk.Frame(root, bg="#181825", bd=1, relief="solid")
        self._entry_frame = entry_frame

        entry = tk.Entry(
            entry_frame,
            bg="#181825",
            fg="#F8FAFC",
            insertbackground="#6366F1",
            relief="flat",
            font=("Segoe UI", 9),
            width=26,
        )
        entry.pack(side=tk.LEFT, padx=6, pady=4)
        self._entry = entry

        send_btn = tk.Button(
            entry_frame,
            text="➤",
            bg="#6366F1",
            fg="#FFFFFF",
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            relief="flat",
            font=("Segoe UI", 8, "bold"),
            command=self._submit_text,
            cursor="hand2",
            padx=4,
            pady=1,
        )
        send_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=4)

        entry.bind("<Return>", lambda e: self._submit_text())
        entry.bind("<Escape>", lambda e: self.toggle_text_entry())

    def toggle_text_entry(self) -> None:
        """Toggles the visibility of the fallback text entry box."""
        if not self._entry_frame or not self._root:
            return
        if self.text_entry_visible:
            self._entry_frame.place_forget()
            self.text_entry_visible = False
            # Restore original window height
            self._root.geometry(f"{self.canvas_width}x{self.canvas_height}")
        else:
            expanded_h = self.canvas_height + 36
            self._root.geometry(f"{self.canvas_width}x{expanded_h}")
            self._entry_frame.place(x=10, y=self.canvas_height - 10, width=self.canvas_width - 20)
            self._entry.focus_set()
            self.text_entry_visible = True

    def _submit_text(self) -> None:
        """Handles submission from the text entry."""
        if not self._entry:
            return
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, "end")
        self.toggle_text_entry()

        logger.info(f"[FloatingAvatar] Text input submitted: {text}")
        if self.on_text_submit:
            try:
                self.on_text_submit(text)
            except Exception as e:
                logger.warning(f"[FloatingAvatar] Error in text submit callback: {e}")

    def _on_mouse_down(self, event: Any) -> None:
        """Records initial drag position."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y

        # If agent is speaking, clicking avatar can interrupt
        if self.current_state == LiveState.SPEAKING and self.on_interrupt:
            try:
                self.on_interrupt()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

    def _on_mouse_drag(self, event: Any) -> None:
        """Moves window smoothly across the desktop."""
        if self.is_docked or not self._root:
            return
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        new_x = self._root.winfo_x() + dx
        new_y = self._root.winfo_y() + dy
        self._root.geometry(f"+{new_x}+{new_y}")
        self._last_undocked_x = new_x
        self._last_undocked_y = new_y

    def _on_double_click(self, event: Any) -> None:
        """Double click toggles edge docking / minimization."""
        self.toggle_dock()

    def toggle_dock(self) -> None:
        """Docks to the screen edge or expands back to full size."""
        if not self._root:
            return

        screen_width = self._root.winfo_screenwidth()
        current_x = self._root.winfo_x()
        current_y = self._root.winfo_y()

        if not self.is_docked:
            # Dock to nearest screen edge (left or right)
            self._last_undocked_x = current_x
            self._last_undocked_y = current_y

            dock_to_right = current_x >= (screen_width // 2)
            dock_x = (screen_width - 32) if dock_to_right else -20

            # Resize to compact badge
            self._root.geometry(f"52x52+{dock_x}+{current_y}")
            self._canvas.itemconfig(self._avatar_item, image=self._photo_docked)
            self._canvas.coords(self._avatar_item, 26, 26)
            for r in self._ring_items:
                self._canvas.itemconfigure(r, state="hidden")
            self._canvas.itemconfigure(self._status_text_item, state="hidden")
            if self.text_entry_visible:
                self.toggle_text_entry()
            self.is_docked = True
        else:
            # Undock to previous floating position
            self._root.geometry(f"{self.canvas_width}x{self.canvas_height}+{self._last_undocked_x}+{self._last_undocked_y}")
            cx = self.canvas_width // 2
            cy = (self.avatar_size // 2) + 15
            self._canvas.itemconfig(self._avatar_item, image=self._photo_normal)
            self._canvas.coords(self._avatar_item, cx, cy)
            for r in self._ring_items:
                self._canvas.itemconfigure(r, state="normal")
            self._canvas.itemconfigure(self._status_text_item, state="normal")
            self.is_docked = False

    def _show_context_menu(self, event: Any) -> None:
        """Displays Windows-native context menu on right click."""
        import tkinter as tk

        menu = tk.Menu(self._root, tearoff=0, bg="#1E1E2E", fg="#F8FAFC", activebackground="#6366F1", activeforeground="#FFFFFF")

        menu.add_command(
            label="👁️  Look at Screen",
            command=self._trigger_screen_capture,
        )
        menu.add_command(
            label="💬  Type Message...",
            command=self.toggle_text_entry,
        )
        menu.add_command(
            label="🎤  Toggle Microphone Mute",
            command=self._trigger_mute_toggle,
        )
        menu.add_separator()
        menu.add_command(
            label="📌  " + ("Undock Avatar" if self.is_docked else "Dock to Edge"),
            command=self.toggle_dock,
        )
        menu.add_command(
            label="🌐  Open Web Dashboard",
            command=lambda: webbrowser.open(self.web_url),
        )
        menu.add_separator()
        menu.add_command(
            label="✕   Hide Avatar",
            command=self.stop,
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _trigger_screen_capture(self) -> None:
        logger.info("[FloatingAvatar] Context menu triggered screen capture.")
        if self.on_screen_capture:
            try:
                self.on_screen_capture()
            except Exception as e:
                logger.warning(f"[FloatingAvatar] Screen capture trigger error: {e}")

    def _trigger_mute_toggle(self) -> None:
        logger.info("[FloatingAvatar] Context menu triggered mic mute toggle.")
        if self.on_mute_toggle:
            try:
                self.on_mute_toggle()
            except Exception as e:
                logger.warning(f"[FloatingAvatar] Mute toggle error: {e}")

    def _animate_halo(self) -> None:
        """Dynamic pulsating / rotating halo animation around the avatar."""
        if not self._root or self._stop_event.is_set():
            return

        if not self.is_docked and self._canvas:
            self._halo_step += 0.15
            color = STATE_COLORS.get(self.current_state, "#06B6D4")

            cx = self.canvas_width // 2
            cy = (self.avatar_size // 2) + 15
            base_r = (self.avatar_size // 2) + 3

            # Pulse amplitude varies with state
            if self.current_state in (LiveState.LISTENING, LiveState.SPEAKING):
                pulse = math.sin(self._halo_step * 2.0) * 4.0
            elif self.current_state in (LiveState.THINKING, LiveState.EXECUTING):
                pulse = math.sin(self._halo_step * 3.0) * 3.0
            elif self.current_state in (LiveState.CONNECTING, LiveState.RECONNECTING):
                pulse = math.sin(self._halo_step * 1.5) * 2.5
            elif self.current_state == LiveState.ERROR:
                pulse = math.sin(self._halo_step * 4.0) * 3.5
            else:
                pulse = math.sin(self._halo_step) * 1.5

            r1 = base_r + pulse
            r2 = base_r + pulse + 4.0

            try:
                self._canvas.coords(self._ring_items[0], cx - r1, cy - r1, cx + r1, cy + r1)
                self._canvas.itemconfig(self._ring_items[0], outline=color)
                self._canvas.coords(self._ring_items[1], cx - r2, cy - r2, cx + r2, cy + r2)
                self._canvas.itemconfig(self._ring_items[1], outline=color)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        try:
            self._root.after(50, self._animate_halo)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
