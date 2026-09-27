from __future__ import annotations

import numpy as np
import pytest

from pyboy_adapter import BackendCapabilityError
from qualification import qualify_repeated_boot, visual_fingerprint


class FakeAdapter:
    def __init__(self, pixels: np.ndarray, telemetry: bool = True) -> None:
        self._pixels = pixels
        self._telemetry = telemetry
        self.frame_count = 0

    def require_capabilities(self, *required: str) -> None:
        if "read_telemetry" in required and not self._telemetry:
            raise BackendCapabilityError("missing read-only memory telemetry")

    def frame(self, count: int = 1) -> None:
        self.frame_count += count

    def pixels(self) -> np.ndarray:
        return self._pixels.copy()


def visible_frame(seed: int) -> np.ndarray:
    pixels = np.zeros((160, 240, 3), dtype=np.uint8)
    pixels[:, :, 0] = seed
    pixels[0, 0] = [0, 1, 2]
    pixels[0, 1] = [3, 4, 5]
    pixels[0, 2] = [6, 7, 8]
    return pixels


def test_visual_fingerprint_is_stable_for_same_pixels() -> None:
    assert visual_fingerprint(visible_frame(10)) == visual_fingerprint(visible_frame(10))


def test_qualification_rejects_missing_telemetry() -> None:
    with pytest.raises(BackendCapabilityError, match="telemetry"):
        qualify_repeated_boot(
            lambda: FakeAdapter(visible_frame(10), telemetry=False), frames=3, runs=2
        )


def test_qualification_rejects_divergent_runs() -> None:
    seed = iter([10, 11])
    with pytest.raises(RuntimeError, match="diverged"):
        qualify_repeated_boot(
            lambda: FakeAdapter(visible_frame(next(seed))), frames=3, runs=2
        )


def test_qualification_accepts_identical_visible_runs() -> None:
    result = qualify_repeated_boot(
        lambda: FakeAdapter(visible_frame(10)), frames=3, runs=2
    )
    assert result["runs"] == 2
    assert result["frames"] == 3
