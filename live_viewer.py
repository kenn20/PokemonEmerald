"""Human-facing, read-only display for a running emulator test."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image


class LiveViewerClosed(RuntimeError):
    """Raised when an interactive test continues after its viewer is closed."""


class LiveViewer:
    """Render framebuffer observations without owning emulator input or state."""

    def __init__(self, *, scale: int = 3) -> None:
        if isinstance(scale, bool) or not isinstance(scale, int) or scale <= 0:
            raise ValueError("viewer scale must be a positive integer")
        try:
            import tkinter as tk
            from PIL import ImageTk
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise RuntimeError("--ui requires Tk support in the active Python environment") from exc

        self._tk: Any = tk
        self._image_tk: Any = ImageTk
        try:
            self._root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - desktop dependent
            raise RuntimeError("--ui could not open a desktop window") from exc
        self._root.title("Pokémon Emerald test viewer")
        self._scale = scale
        self._closed = False
        self._status = "Starting test…"
        self._photo: Any | None = None
        self._continue_signal = tk.BooleanVar(self._root, value=False)
        self._status_label = tk.Label(self._root, anchor="w")
        self._status_label.pack(fill="x")
        self._continue_button = tk.Button(
            self._root,
            text="Continue (Space)",
            command=self._continue_after_checkpoint,
            state="disabled",
        )
        self._continue_button.pack(fill="x")
        self._frame_label = tk.Label(self._root)
        self._frame_label.pack()
        self._root.bind("<space>", self._continue_after_checkpoint)
        self._root.protocol("WM_DELETE_WINDOW", self.close)
        self._pump()

    def set_status(self, status: str) -> None:
        self._require_open()
        self._status = status
        self._status_label.configure(text=status)
        self._root.title(f"Pokémon Emerald test viewer — {status}")
        self._pump()

    def show_frame(self, pixels: np.ndarray, frame_count: int) -> None:
        """Render one observed emulator frame; it never sends game input."""

        self._require_open()
        if pixels.shape != (160, 240, 3):
            raise ValueError(f"viewer received unexpected framebuffer shape {pixels.shape}")
        image = Image.fromarray(np.asarray(pixels, dtype=np.uint8), "RGB")
        if self._scale != 1:
            image = image.resize((240 * self._scale, 160 * self._scale), Image.Resampling.NEAREST)
        self._photo = self._image_tk.PhotoImage(image)
        self._frame_label.configure(image=self._photo)
        self._status_label.configure(text=f"{self._status} · frame {frame_count}")
        self._pump()

    def wait_until_closed(self, status: str) -> None:
        """Keep the final emulator frame visible until the human closes the window."""

        self.set_status(status)
        try:
            self._root.wait_window()
        except self._tk.TclError as exc:  # pragma: no cover - desktop dependent
            raise LiveViewerClosed("the test viewer closed unexpectedly") from exc

    def wait_for_continue(self, status: str) -> None:
        """Pause a UI replay after a named checkpoint until Space is pressed."""

        self._require_open()
        self._continue_signal.set(False)
        self._continue_button.configure(state="normal")
        self._continue_button.focus_set()
        self.set_status(f"{status} — press Space to continue")
        try:
            self._root.wait_variable(self._continue_signal)
        except self._tk.TclError as exc:  # pragma: no cover - desktop dependent
            raise LiveViewerClosed("the test viewer was closed at a checkpoint") from exc
        finally:
            if not self._closed:
                self._continue_button.configure(state="disabled")
        self._require_open()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._root.destroy()

    def _require_open(self) -> None:
        if self._closed:
            raise LiveViewerClosed("the test viewer was closed before the test completed")

    def _pump(self) -> None:
        try:
            self._root.update_idletasks()
            self._root.update()
        except self._tk.TclError as exc:  # pragma: no cover - desktop dependent
            self._closed = True
            raise LiveViewerClosed("the test viewer was closed before the test completed") from exc

    def _continue_after_checkpoint(self, _event: Any = None) -> str:
        self._continue_signal.set(True)
        return "break"
