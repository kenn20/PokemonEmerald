"""Deterministic input routes and EWRAM-diff capture for starter calibration.

This module is deliberately controller-owned.  It is a measurement tool used
to establish a ROM-specific starter map; it is never exposed to Jev.
"""

from __future__ import annotations

import argparse
import json
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

import numpy as np
from PIL import Image

from pyboy_adapter import GbaKey, PyBoyAdvance
from qualification import EWRAM_START, visual_fingerprint


EWRAM_SIZE = 256 * 1024
MAX_STEP_FRAMES = 600
MAX_ROUTE_FRAMES = 30_000


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
        if (
            isinstance(self.frames, bool)
            or not isinstance(self.frames, int)
            or not 0 <= self.frames <= MAX_STEP_FRAMES
        ):
            raise ValueError(
                f"route step frames must be between 0 and {MAX_STEP_FRAMES}"
            )
        if isinstance(self.hold_frames, bool) or not isinstance(self.hold_frames, int):
            raise ValueError("route step hold_frames must be an integer")
        if self.key is None and self.hold_frames != 2:
            raise ValueError("wait steps must use the default hold_frames")
        if self.key is not None and self.hold_frames <= 0:
            raise ValueError("input steps require at least one hold frame")
        if self.frame_cost > MAX_STEP_FRAMES:
            raise ValueError(
                f"route step frame cost must not exceed {MAX_STEP_FRAMES}"
            )

    @property
    def frame_cost(self) -> int:
        """Actual emulator frames consumed by this step."""

        return self.frames + (self.hold_frames if self.key is not None else 0)


@dataclass(frozen=True)
class RouteCheckpoint:
    """Visible evidence after one route step."""

    name: str
    frame_count: int
    framebuffer_sha256: str
    screenshot: str | None = None


@dataclass(frozen=True)
class RamDifference:
    """One EWRAM byte changed by a deliberately measured input."""

    address: int
    before: int
    after: int


@dataclass(frozen=True)
class RouteEvidence:
    """Optional named evidence points declared by a disposable route."""

    starter_checkpoint: str
    cursor_before: str
    cursor_after: str
    confirm_before: str
    confirm_after: str


@dataclass(frozen=True)
class RouteSpec:
    """A route plus the checkpoint names needed for calibration."""

    steps: tuple[RouteStep, ...]
    evidence: RouteEvidence

    def checkpoint_names(self) -> set[str]:
        return {step.name for step in self.steps}

    def validate(self) -> None:
        validate_route(self.steps)
        names = self.checkpoint_names()
        required = {
            self.evidence.starter_checkpoint,
            self.evidence.cursor_before,
            self.evidence.cursor_after,
            self.evidence.confirm_before,
        }
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"route evidence names are missing: {missing}")


def run_route(adapter: RouteAdapter, steps: Sequence[RouteStep]) -> tuple[RouteCheckpoint, ...]:
    """Execute a named route and capture a visible checkpoint after each step."""

    validate_route(steps)
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


def run_route_with_evidence(
    adapter: RouteAdapter,
    spec: RouteSpec,
    *,
    evidence_dir: Path | None = None,
    before_step: Callable[[RouteStep, int], None] | None = None,
    after_step: Callable[[RouteStep, int], None] | None = None,
) -> tuple[tuple[RouteCheckpoint, ...], dict[str, bytes]]:
    """Replay a route and capture named PNG-adjacent framebuffer/RAM evidence.

    The returned RAM snapshots are complete EWRAM images.  They are kept in
    memory by the caller so qualification can compare runs without allowing
    an untrusted route file to choose arbitrary production fields.
    """

    spec.validate()
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, bytes] = {}
    checkpoints: list[RouteCheckpoint] = []
    for step_index, step in enumerate(spec.steps, start=1):
        if before_step is not None:
            before_step(step, step_index)
        if step.name in {
            spec.evidence.cursor_before,
            spec.evidence.confirm_before,
        }:
            snapshots[step.name] = snapshot_ewram(adapter)
            if evidence_dir is not None:
                (evidence_dir / f"{step.name}.ewram.bin").write_bytes(
                    snapshots[step.name]
                )
        if step.key is None:
            adapter.frame(step.frames)
        else:
            adapter.tap(step.key, hold_frames=step.hold_frames, settle_frames=step.frames)
        pixels = adapter.pixels()
        screenshot: str | None = None
        if evidence_dir is not None:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            target = evidence_dir / f"{step.name}.png"
            Image.fromarray(pixels, "RGB").save(target, format="PNG")
            screenshot = str(target)
        checkpoint = RouteCheckpoint(
            name=step.name,
            frame_count=adapter.frame_count,
            framebuffer_sha256=str(visual_fingerprint(pixels)["sha256"]),
            screenshot=screenshot,
        )
        checkpoints.append(checkpoint)
        if step.name in {
            spec.evidence.starter_checkpoint,
            spec.evidence.cursor_after,
            spec.evidence.confirm_after,
        }:
            snapshots[step.name] = snapshot_ewram(adapter)
            if evidence_dir is not None:
                (evidence_dir / f"{step.name}.ewram.bin").write_bytes(
                    snapshots[step.name]
                )
        if after_step is not None:
            after_step(step, step_index)
    return tuple(checkpoints), snapshots


def validate_route(steps: Sequence[RouteStep]) -> None:
    """Reject empty or over-budget routes before they advance the emulator."""

    if not steps:
        raise ValueError("route must contain at least one step")
    total_frames = sum(step.frame_cost for step in steps)
    if total_frames > MAX_ROUTE_FRAMES:
        raise ValueError(
            f"route frame budget exceeded: {total_frames} > {MAX_ROUTE_FRAMES}"
        )


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
    if isinstance(data, dict):
        data = data.get("steps")
    if not isinstance(data, list) or not data:
        raise ValueError("route JSON must be a non-empty list or an object with steps")
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
    route = tuple(steps)
    validate_route(route)
    return route


def load_route_spec(path: Path) -> RouteSpec:
    """Load a route and its required calibration evidence names."""

    try:
        data: Any = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read route JSON {path}: {exc}") from exc
    if isinstance(data, list):
        raise ValueError("route JSON must declare evidence checkpoints")
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError("route JSON must contain a steps list")
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("route JSON must contain an evidence object")
    try:
        spec = RouteSpec(
            steps=load_route(path),
            evidence=RouteEvidence(
                starter_checkpoint=str(evidence["starter_checkpoint"]),
                cursor_before=str(evidence["cursor_before"]),
                cursor_after=str(evidence["cursor_after"]),
                confirm_before=str(evidence["confirm_before"]),
                confirm_after=str(evidence["confirm_after"]),
            ),
        )
    except KeyError as exc:
        raise ValueError(f"route evidence is missing {exc.args[0]!r}") from exc
    spec.validate()
    return spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--bios", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--diff-step", required=True)
    parser.add_argument("--evidence-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = load_route_spec(args.route)
        steps = spec.steps
        names = [step.name for step in steps]
        if names.count(args.diff_step) != 1:
            raise ValueError("--diff-step must name exactly one route step")
        adapter = PyBoyAdvance(args.rom, args.bios, skip_bios=False, emulation_speed=0)
        before: bytes | None = None
        after: bytes | None = None
        checkpoints, snapshots = run_route_with_evidence(
            adapter, spec, evidence_dir=args.evidence_dir
        )
        if args.diff_step in snapshots:
            before = snapshots[args.diff_step]
            after_name = next(
                (name for name in (spec.evidence.cursor_after, spec.evidence.confirm_after)
                 if name != args.diff_step),
                None,
            )
            if after_name is not None:
                after = snapshots[after_name]
        if before is None or after is None:
            raise ValueError("--diff-step must name a measured before checkpoint")
        assert before is not None and after is not None
        print(
            json.dumps(
                {
                    "checkpoints": [asdict(item) for item in checkpoints],
                    "diff_step": args.diff_step,
                    "ewram_diff": [asdict(item) for item in diff_ewram(before, after)],
                    "ewram_sha256": {
                        name: hashlib.sha256(snapshot).hexdigest()
                        for name, snapshot in snapshots.items()
                    },
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
