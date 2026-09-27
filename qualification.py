"""Fail-closed PyBoyAdvance capability and fresh-process replay probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from pyboy_adapter import BackendCapabilityError, PyBoyAdvance


BPEE_V10_SHA256 = "a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af"
EWRAM_START = 0x02000000


class ReplayAdapter(Protocol):
    frame_count: int

    def frame(self, count: int = 1) -> None: ...

    def pixels(self) -> np.ndarray: ...

    def peek_u8(self, address: int) -> int: ...

    def peek_u16(self, address: int) -> int: ...

    def peek_u32(self, address: int) -> int: ...

    def timing_checkpoint(self) -> int: ...

    def require_capabilities(self, *required: str) -> None: ...


@dataclass(frozen=True)
class RamObservation:
    """One named RAM field supplied by a validated game-state map."""

    name: str
    address: int
    width: int


# This remains empty until a BPEE v1.0 starter-state map has been validated.
# Keeping the map in code, rather than accepting an arbitrary CLI label, makes
# the qualifying path fail closed against invented semantic telemetry.
VALIDATED_BPEE_V10_STARTER_STATE_MAP: tuple[RamObservation, ...] = ()

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rom_identity(rom: Path, *, expected_sha256: str = BPEE_V10_SHA256) -> dict[str, str]:
    """Record and enforce the one ROM identity this probe can qualify."""

    actual_sha256 = sha256_file(rom)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"unsupported ROM SHA-256: expected {expected_sha256}, got {actual_sha256}"
        )
    return {"path": str(rom), "sha256": actual_sha256}


def visual_fingerprint(pixels: np.ndarray) -> dict[str, object]:
    """Return a compact fingerprint suitable for checkpoint comparison."""

    if pixels.shape != (160, 240, 3):
        raise ValueError(f"unexpected framebuffer shape: {pixels.shape}")
    colors = np.unique(pixels.reshape(-1, 3), axis=0)
    return {
        "shape": list(pixels.shape),
        "sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "color_count": int(len(colors)),
    }


def probe_non_advancing_peeks(
    adapter: ReplayAdapter, *, address: int = EWRAM_START, peeks: int = 1_000
) -> dict[str, object]:
    """Prove repeated public peeks leave a visible timing checkpoint unchanged."""

    if isinstance(peeks, bool) or not isinstance(peeks, int) or peeks <= 0:
        raise ValueError("peeks must be a positive integer")
    adapter.require_capabilities(
        "frames", "pixels", "read_telemetry", "timing_telemetry"
    )
    before_frames = adapter.frame_count
    before_cycles = adapter.timing_checkpoint()
    before_fingerprint = visual_fingerprint(adapter.pixels())
    value = 0
    for _ in range(peeks):
        value = adapter.peek_u8(address)
    after_fingerprint = visual_fingerprint(adapter.pixels())
    if (
        adapter.frame_count != before_frames
        or adapter.timing_checkpoint() != before_cycles
        or after_fingerprint != before_fingerprint
    ):
        raise RuntimeError("non-advancing peek probe changed the timing or framebuffer checkpoint")
    return {
        "address": f"0x{address:08X}",
        "emulation_cycles": before_cycles,
        "peeks": peeks,
        "value": value,
    }


def capability_checkpoint(
    adapter_factory: Callable[[], ReplayAdapter], *, frames: int
) -> dict[str, object]:
    """Reach one checkpoint and prove the public peek APIs do not disturb it."""

    adapter = adapter_factory()
    adapter.frame(frames)
    return {
        "frame_count": adapter.frame_count,
        "framebuffer": visual_fingerprint(adapter.pixels()),
        "peek_probe": probe_non_advancing_peeks(adapter),
    }


def observe_ram(adapter: ReplayAdapter, observations: tuple[RamObservation, ...]) -> dict[str, int]:
    """Project only fields named by a validated semantic state map."""

    if not observations:
        raise RuntimeError("at least one named RAM observation is required")
    if len({item.name for item in observations}) != len(observations):
        raise ValueError("RAM observation names must be unique")
    readers = {8: adapter.peek_u8, 16: adapter.peek_u16, 32: adapter.peek_u32}
    result: dict[str, int] = {}
    for item in observations:
        reader = readers.get(item.width)
        if reader is None:
            raise ValueError(f"unsupported RAM observation width: {item.width}")
        result[item.name] = reader(item.address)
    return result


def qualify_replay(
    adapter_factory: Callable[[], ReplayAdapter],
    *,
    identity: dict[str, str],
    frames: int,
    runs: int,
    observations: tuple[RamObservation, ...],
) -> dict[str, object]:
    """Require matching RAM and framebuffer checkpoints from fresh instances."""

    if runs < 3:
        raise ValueError("runs must be at least 3")
    checkpoints: list[dict[str, object]] = []
    for run in range(runs):
        adapter = adapter_factory()
        adapter.frame(frames)
        peek_probe = probe_non_advancing_peeks(adapter)
        fingerprint = visual_fingerprint(adapter.pixels())
        if int(fingerprint["color_count"]) < 4:
            raise RuntimeError(
                f"run {run + 1} produced an unusably sparse framebuffer: {fingerprint}"
            )
        checkpoints.append(
            {
                "frame_count": adapter.frame_count,
                "framebuffer": fingerprint,
                "observation": observe_ram(adapter, observations),
                "peek_probe": peek_probe,
            }
        )
    if len({json.dumps(item, sort_keys=True) for item in checkpoints}) != 1:
        raise RuntimeError(f"fresh runs diverged: {checkpoints}")
    return {
        "qualified": True,
        "rom": identity,
        "runs": runs,
        "frames": frames,
        "checkpoint": checkpoints[0],
    }


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
        identity = rom_identity(args.rom)
        if not VALIDATED_BPEE_V10_STARTER_STATE_MAP:
            # The backend may print diagnostics while booting.  Keep stdout
            # reserved for the single JSON result consumed by automation.
            with redirect_stdout(sys.stderr):
                checkpoint = capability_checkpoint(factory, frames=args.frames)
            result = {
                "qualified": False,
                "rom": identity,
                "capability_checkpoint": checkpoint,
                "error": "BPEE v1.0 starter-state map is not validated; Jev remains disabled",
            }
            print(json.dumps(result, sort_keys=True))
            return 1
        result = qualify_replay(
            factory,
            identity=identity,
            frames=args.frames,
            runs=args.runs,
            observations=VALIDATED_BPEE_V10_STARTER_STATE_MAP,
        )
    except (BackendCapabilityError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"qualified": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
