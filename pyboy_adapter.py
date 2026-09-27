"""Small, headless adapter for the PyBoy Advance emulator.

The adapter deliberately exposes controller input and read-only telemetry.  It
does not expose the backend object or any memory-writing operation to callers.
"""

from __future__ import annotations

from pathlib import Path
from enum import Enum, auto
from typing import Any

import numpy as np


class BackendCapabilityError(RuntimeError):
    """Raised when the installed backend cannot support a requested phase."""


class PyBoyAdvance:
    """Own a PyBoy Advance instance and expose safe episode primitives."""

    FRAME_WIDTH = 240
    FRAME_HEIGHT = 160

    def __init__(
        self,
        rom: str | Path,
        bios: str | Path,
        skip_bios: bool = False,
        emulation_speed: float = 0,
    ) -> None:
        try:
            from pyboy_advance import PyBoyAdvance as BackendPyBoyAdvance
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "PyBoy Advance is not installed; install requirements.txt first"
            ) from exc

        self._emulator: Any = BackendPyBoyAdvance(
            rom=rom,
            bios=bios,
            skip_bios=skip_bios,
            emulation_speed=emulation_speed,
        )
        self._rom = rom
        self._bios = bios
        self._skip_bios = skip_bios
        self._emulation_speed = emulation_speed
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        """Number of frames requested through this adapter."""

        return self._frame_count

    def timing_checkpoint(self) -> int:
        """Read the backend's public, non-mutating emulation cycle counter."""

        reader = getattr(self._emulator, "timing_checkpoint", None)
        if not callable(reader):
            raise BackendCapabilityError(
                "installed PyBoy backend does not expose timing_checkpoint; "
                "install the SHA-pinned fork"
            )
        value = reader()
        if isinstance(value, bool) or not isinstance(value, int):
            raise BackendCapabilityError("backend timing_checkpoint did not return an integer")
        return value

    def frame(self, count: int = 1) -> None:
        """Advance exactly ``count`` frames and update the adapter counter."""

        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("frame count must be an integer")
        if count < 0:
            raise ValueError("frame count must be non-negative")
        self._emulator.frame(count)
        self._frame_count += count

    def pixels(self) -> np.ndarray:
        """Return a detached RGB framebuffer with shape ``(160, 240, 3)``."""

        pixels = np.asarray(self._emulator.screen.ndarray, dtype=np.uint8)
        expected_shape = (self.FRAME_HEIGHT, self.FRAME_WIDTH, 3)
        if pixels.shape != expected_shape:
            raise RuntimeError(
                f"unexpected framebuffer shape {pixels.shape}; expected {expected_shape}"
            )
        return pixels.copy()

    def reset(self) -> None:
        """Start a fresh emulator process-equivalent episode.

        PyBoyAdvance has no public reset or save-state API.  Reconstructing the
        backend is therefore the only supported reset primitive in this phase.
        """

        self.release_all()
        from pyboy_advance import PyBoyAdvance as BackendPyBoyAdvance

        self._emulator = BackendPyBoyAdvance(
            rom=self._rom,
            bios=self._bios,
            skip_bios=self._skip_bios,
            emulation_speed=self._emulation_speed,
        )
        self._frame_count = 0

    def press(self, key: "GbaKey") -> None:
        """Press one GBA key through the backend."""

        self._emulator.press_key(_backend_key(key))

    def release(self, key: "GbaKey") -> None:
        """Release one GBA key through the backend."""

        self._emulator.release_key(_backend_key(key))

    def release_all(self) -> None:
        """Release every key, including after a failed input action."""

        for key in GbaKey:
            self.release(key)

    def tap(self, key: "GbaKey", hold_frames: int = 1, settle_frames: int = 1) -> None:
        """Press, hold, release, and settle one key deterministically."""

        _validate_frame_count(hold_frames, "hold_frames")
        _validate_frame_count(settle_frames, "settle_frames")
        self.press(key)
        try:
            self.frame(hold_frames)
        finally:
            self.release(key)
        self.frame(settle_frames)

    def peek_u8(self, address: int) -> int:
        """Read one byte through the backend's non-advancing public API."""

        return self._peek(address, 8)

    def peek_u16(self, address: int) -> int:
        """Read one little-endian unsigned 16-bit value without advancing time."""

        return self._peek(address, 16)

    def peek_u32(self, address: int) -> int:
        """Read one little-endian unsigned 32-bit value without advancing time."""

        return self._peek(address, 32)

    def _peek(self, address: int, width: int) -> int:
        reader = getattr(self._emulator, f"peek_u{width}", None)
        if reader is None:
            raise BackendCapabilityError(
                "installed PyBoy backend does not expose the required non-advancing "
                f"peek_u{width} telemetry API; install the SHA-pinned fork"
            )
        return int(reader(address))

    def capabilities(self) -> dict[str, bool]:
        """Report capabilities without pretending missing backend APIs exist."""

        return {
            "frames": callable(getattr(self._emulator, "frame", None)),
            "keys": callable(getattr(self._emulator, "press_key", None))
            and callable(getattr(self._emulator, "release_key", None)),
            "pixels": hasattr(self._emulator, "screen"),
            "read_telemetry": all(
                callable(getattr(self._emulator, name, None))
                for name in ("peek_u8", "peek_u16", "peek_u32")
            ),
            "timing_telemetry": callable(
                getattr(self._emulator, "timing_checkpoint", None)
            ),
        }

    def require_capabilities(self, *required: str) -> None:
        missing = [name for name in required if not self.capabilities().get(name, False)]
        if missing:
            raise BackendCapabilityError(
                "backend is missing required capabilities: " + ", ".join(missing)
            )

class GbaKey(Enum):
    """The ten physical buttons available on a GBA controller."""

    A = auto()
    B = auto()
    SELECT = auto()
    START = auto()
    RIGHT = auto()
    LEFT = auto()
    UP = auto()
    DOWN = auto()
    R = auto()
    L = auto()


def _validate_frame_count(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _backend_key(key: GbaKey) -> Any:
    if not isinstance(key, GbaKey):
        raise TypeError("key must be a GbaKey")
    try:
        from pyboy_advance.constants import Key
    except ImportError as exc:  # pragma: no cover - backend-dependent
        raise RuntimeError("PyBoy Advance key input is unavailable") from exc
    names = {
        GbaKey.A: "BUTTON_A",
        GbaKey.B: "BUTTON_B",
        GbaKey.SELECT: "BUTTON_SELECT",
        GbaKey.START: "BUTTON_START",
        GbaKey.RIGHT: "DPAD_RIGHT",
        GbaKey.LEFT: "DPAD_LEFT",
        GbaKey.UP: "DPAD_UP",
        GbaKey.DOWN: "DPAD_DOWN",
        GbaKey.R: "SHOULDER_RIGHT",
        GbaKey.L: "SHOULDER_LEFT",
    }
    return getattr(Key, names[key])
