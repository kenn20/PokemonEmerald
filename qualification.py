"""Repeatable, fail-closed qualification gate for the PyBoy backend."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np

from pyboy_adapter import BackendCapabilityError, PyBoyAdvance


def visual_fingerprint(pixels: np.ndarray) -> dict[str, object]:
    """Return a compact fingerprint suitable for cross-process comparison."""

    if pixels.shape != (160, 240, 3):
        raise ValueError(f"unexpected framebuffer shape: {pixels.shape}")
    colors = np.unique(pixels.reshape(-1, 3), axis=0)
    return {
        "shape": list(pixels.shape),
        "sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "color_count": int(len(colors)),
    }


def qualify_repeated_boot(
    adapter_factory: Callable[[], PyBoyAdvance],
    *,
    frames: int,
    runs: int,
) -> dict[str, object]:
    """Require telemetry and an identical, visible frame across fresh runs."""

    if runs < 2:
        raise ValueError("runs must be at least 2")
    fingerprints: list[dict[str, object]] = []
    for run in range(runs):
        adapter = adapter_factory()
        adapter.require_capabilities("frames", "keys", "pixels", "read_telemetry")
        adapter.frame(frames)
        fingerprint = visual_fingerprint(adapter.pixels())
        if int(fingerprint["color_count"]) < 4:
            raise RuntimeError(
                f"run {run + 1} produced an unusably sparse framebuffer: {fingerprint}"
            )
        fingerprints.append(fingerprint)
    if len({item["sha256"] for item in fingerprints}) != 1:
        raise RuntimeError(f"fresh runs diverged: {fingerprints}")
    return {"runs": runs, "frames": frames, "fingerprint": fingerprints[0]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--bios", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=900)
    parser.add_argument("--runs", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def factory() -> PyBoyAdvance:
        return PyBoyAdvance(args.rom, args.bios, skip_bios=False, emulation_speed=0)

    try:
        result = qualify_repeated_boot(factory, frames=args.frames, runs=args.runs)
    except (BackendCapabilityError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"qualified": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"qualified": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
