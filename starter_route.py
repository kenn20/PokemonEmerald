"""Deterministic input routes and EWRAM-diff capture for starter calibration.

This module is deliberately controller-owned.  It is a measurement tool used
to establish a ROM-specific starter map; it is never exposed to Jev.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from pyboy_adapter import GbaKey, PyBoyAdvance
from qualification import EWRAM_START, visual_fingerprint


EWRAM_SIZE = 256 * 1024


class RouteAdapter(Protocol):
    frame_count: int

    def frame(self, count: int = 1) -> None: ...

    def tap(self, key: GbaKey, hold_frames: int = 1, settle_frames: int = 1) -> None: ...

    def pixels(self) -> np.ndarray: ...

    def peek_u8(self, address: int) -> int: ...


@dataclass(frozen=True)
class RouteStep:
    """One named, bounded controller action in a calibration route."""

    name: str
    key: GbaKey | None
    frames: int
    hold_frames: int = 2

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("route step name must not be empty")
        if isinstance(self.frames, bool) or not isinstance(self.frames, int) or self.frames < 0:
            raise ValueError("route step frames must be a non-negative integer")
        if isinstance(self.hold_frames, bool) or not isinstance(self.hold_frames, int):
            raise ValueError("route step hold_frames must be an integer")
        if self.key is None and self.hold_frames != 2:
            raise ValueError("wait steps must use the default hold_frames")
        if self.key is not None and self.hold_frames <= 0:
            raise ValueError("input steps require at least one hold frame")


@dataclass(frozen=True)
class RouteCheckpoint:
    """Visible evidence after one route step."""

    name: str
    frame_count: int
    framebuffer_sha256: str


@dataclass(frozen=True)
class RamDifference:
    """One EWRAM byte changed by a deliberately measured input."""

    address: int
    before: int
    after: int


def run_route(adapter: RouteAdapter, steps: Sequence[RouteStep]) -> tuple[RouteCheckpoint, ...]:
    """Execute a named route and capture a visible checkpoint after each step."""

    checkpoints: list[RouteCheckpoint] = []
    for step in steps:
        if step.key is None:
            adapter.frame(step.frames)
        else:
            adapter.tap(step.key, hold_frames=step.hold_frames, settle_frames=step.frames)
        pixels = adapter.pixels()
        checkpoints.append(
            RouteCheckpoint(
                name=step.name,
                frame_count=adapter.frame_count,
                framebuffer_sha256=str(visual_fingerprint(pixels)["sha256"]),
            )
        )
    return tuple(checkpoints)


def snapshot_ewram(adapter: RouteAdapter) -> bytes:
    """Capture the complete public EWRAM telemetry surface without advancing time."""

    return bytes(adapter.peek_u8(EWRAM_START + offset) for offset in range(EWRAM_SIZE))


def diff_ewram(before: bytes, after: bytes) -> tuple[RamDifference, ...]:
    """Return every changed EWRAM byte; unequal snapshot sizes are invalid evidence."""

    if len(before) != EWRAM_SIZE or len(after) != EWRAM_SIZE:
        raise ValueError(f"EWRAM snapshots must each be {EWRAM_SIZE} bytes")
    return tuple(
        RamDifference(EWRAM_START + offset, old, new)
        for offset, (old, new) in enumerate(zip(before, after))
        if old != new
    )


def load_route(path: Path) -> tuple[RouteStep, ...]:
    """Load a checked calibration route from JSON, rejecting arbitrary key values."""

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read route JSON {path}: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ValueError("route JSON must be a non-empty list")
    steps: list[RouteStep] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each route step must be an object")
        key_name = item.get("key")
        try:
            key = None if key_name is None else GbaKey[str(key_name)]
        except KeyError as exc:
            raise ValueError(f"unknown GBA key in route: {key_name!r}") from exc
        steps.append(
            RouteStep(
                name=str(item.get("name", "")),
                key=key,
                frames=item.get("frames"),
                hold_frames=item.get("hold_frames", 2),
            )
        )
    return tuple(steps)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--bios", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--diff-step", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        steps = load_route(args.route)
        names = [step.name for step in steps]
        if names.count(args.diff_step) != 1:
            raise ValueError("--diff-step must name exactly one route step")
        adapter = PyBoyAdvance(args.rom, args.bios, skip_bios=False, emulation_speed=0)
        before: bytes | None = None
        after: bytes | None = None
        checkpoints: list[RouteCheckpoint] = []
        for step in steps:
            if step.name == args.diff_step:
                before = snapshot_ewram(adapter)
            checkpoints.extend(run_route(adapter, (step,)))
            if step.name == args.diff_step:
                after = snapshot_ewram(adapter)
        assert before is not None and after is not None
        print(
            json.dumps(
                {
                    "checkpoints": [asdict(item) for item in checkpoints],
                    "diff_step": args.diff_step,
                    "ewram_diff": [asdict(item) for item in diff_ewram(before, after)],
                },
                sort_keys=True,
            )
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
