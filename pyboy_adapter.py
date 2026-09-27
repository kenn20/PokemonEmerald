"""Small, headless adapter for the PyBoy Advance emulator.

Phase 1 deliberately exposes only deterministic frame stepping and pixels.  Key
input and memory access belong to later phases and are not part of this API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


class PyBoyAdvance:
    """Own a PyBoy Advance instance and count frames stepped through it."""

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
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        """Number of frames requested through this adapter."""

        return self._frame_count

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
