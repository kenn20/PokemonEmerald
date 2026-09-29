"""Fail-closed PyBoyAdvance capability and fresh-process replay probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
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


# Candidate locations from the current calibration probe. They are retained
# only as a disposable investigation record: the probe ended at the title
# screen, so none is promoted into the qualified production map.
STARTER_PHASE_ADDRESS = 0x020370B8
STARTER_CURSOR_ADDRESS = 0x020370C2
STARTER_RESULT_ADDRESS = 0x020370C4
PROVISIONAL_BPEE_V10_STARTER_STATE_MAP: tuple[RamObservation, ...] = (
    RamObservation("starter_phase", STARTER_PHASE_ADDRESS, 16),
    RamObservation("starter_cursor", STARTER_CURSOR_ADDRESS, 16),
    RamObservation("selected_species", STARTER_RESULT_ADDRESS, 16),
)

# Jev stays disabled until a route reaching Birch's menu validates these
# fields across three fresh runs.
VALIDATED_BPEE_V10_STARTER_STATE_MAP: tuple[RamObservation, ...] = ()

STARTER_SPECIES_IDS = {"TREECKO": 277, "TORCHIC": 255, "MUDKIP": 258}


def _observation_bytes(item: RamObservation) -> range:
    if item.width not in (8, 16, 32):
        raise ValueError(f"unsupported RAM observation width: {item.width}")
    if not EWRAM_START <= item.address < EWRAM_START + 256 * 1024:
        raise ValueError(f"RAM observation is outside EWRAM: 0x{item.address:08X}")
    return range(item.address - EWRAM_START, item.address - EWRAM_START + item.width // 8)


def validate_cursor_transition(
    before: bytes,
    after: bytes,
    cursor: RamObservation,
) -> tuple[int, ...]:
    """Require a cursor move to alter only the named cursor field."""

    from starter_route import diff_ewram

    changed = diff_ewram(before, after)
    allowed = set(_observation_bytes(cursor))
    unexpected = tuple(
        item.address for item in changed if item.address - EWRAM_START not in allowed
    )
    if unexpected:
        raise RuntimeError(
            "cursor transition changed unexpected EWRAM addresses: "
            + ", ".join(f"0x{address:08X}" for address in unexpected[:8])
        )
    if not changed:
        raise RuntimeError("cursor transition did not change EWRAM")
    return tuple(item.address for item in changed)


def qualify_route_replay(
    adapter_factory: Callable[[], ReplayAdapter],
    *,
    identity: dict[str, str],
    route: RouteSpec,
    runs: int,
    observations: tuple[RamObservation, ...],
    evidence_dir: Path | None = None,
    before_route_step: Callable[[int, str, int], None] | None = None,
    after_route_step: Callable[[int, str, int], None] | None = None,
) -> dict[str, object]:
    """Replay a named route in fresh instances and validate its RAM contract."""

    from pyboy_adapter import GbaKey
    from starter_route import run_route_with_evidence, snapshot_ewram

    if runs < 3:
        raise ValueError("runs must be at least 3")
    route.validate()
    by_name = {item.name: item for item in observations}
    required = {"starter_phase", "starter_cursor", "selected_species"}
    if not required <= by_name.keys():
        raise RuntimeError("starter RAM map must name phase, cursor, and species")
    runs_evidence: list[dict[str, object]] = []
    for run in range(1, runs + 1):
        adapter = adapter_factory()
        run_dir = None if evidence_dir is None else evidence_dir / f"run-{run}"
        checkpoints, snapshots = run_route_with_evidence(
            adapter,
            route,
            evidence_dir=run_dir,
            before_step=(
                None
                if before_route_step is None
                else lambda step, step_index: before_route_step(run, step.name, step_index)
            ),
            after_step=(
                None
                if after_route_step is None
                else lambda step, step_index: after_route_step(run, step.name, step_index)
            ),
        )
        checkpoint_rows = [item.__dict__ for item in checkpoints]
        checkpoint = next(
            item for item in checkpoint_rows
            if item["name"] == route.evidence.starter_checkpoint
        )
        starter_values = observe_ram_snapshot(
            snapshots[route.evidence.starter_checkpoint], observations
        )
        if starter_values["starter_phase"] != 1:
            raise RuntimeError(
                f"route run {run} checkpoint {route.evidence.starter_checkpoint!r} "
                f"at frame {checkpoint['frame_count']} "
                f"(framebuffer {checkpoint['framebuffer_sha256']}) "
                f"has starter_phase={starter_values['starter_phase']}, expected 1"
            )
        if not 0 <= starter_values["starter_cursor"] < 3:
            raise RuntimeError(
                f"route run {run} checkpoint has invalid cursor "
                f"{starter_values['starter_cursor']}"
            )
        changed_cursor = validate_cursor_transition(
            snapshots[route.evidence.cursor_before],
            snapshots[route.evidence.cursor_after],
            by_name["starter_cursor"],
        )
        # The route ends at the visible starter menu.  Measure confirmation
        # here so the same disposable route can also be used by acceptance,
        # where Jev must make the choice before the A press.
        confirm_before = snapshots[route.evidence.confirm_before]
        adapter.tap(GbaKey.A)
        confirm_after = snapshot_ewram(adapter)
        snapshots[route.evidence.confirm_after] = confirm_after
        if run_dir is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / f"{route.evidence.confirm_after}.ewram.bin").write_bytes(
                confirm_after
            )
        selected_after = observe_ram(adapter, observations)
        if selected_after["selected_species"] not in STARTER_SPECIES_IDS.values():
            raise RuntimeError(
                f"route run {run} confirmation produced invalid species "
                f"{selected_after['selected_species']}"
            )
        runs_evidence.append(
            {
                "checkpoints": checkpoint_rows,
                "starter_checkpoint": checkpoint,
                "starter_observation": starter_values,
                "ewram_sha256": {
                    name: hashlib.sha256(value).hexdigest()
                    for name, value in snapshots.items()
                },
                "confirmation": {
                    "before_sha256": hashlib.sha256(confirm_before).hexdigest(),
                    "after_sha256": hashlib.sha256(confirm_after).hexdigest(),
                    "selected_species": selected_after["selected_species"],
                },
                "cursor_changed_addresses": [f"0x{address:08X}" for address in changed_cursor],
            }
        )
    normalized = []
    for item in runs_evidence:
        comparable = dict(item)
        comparable["checkpoints"] = [
            {key: value for key, value in row.items() if key != "screenshot"}
            for row in item["checkpoints"]
        ]
        normalized.append(json.dumps(comparable, sort_keys=True))
    if len(set(normalized)) != 1:
        raise RuntimeError(f"fresh route runs diverged: {runs_evidence}")
    return {
        "qualified": True,
        "rom": identity,
        "runs": runs,
        "route": runs_evidence[0],
        "observations": [item.__dict__ for item in observations],
    }

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


def observe_ram_snapshot(
    snapshot: bytes, observations: tuple[RamObservation, ...]
) -> dict[str, int]:
    """Decode named little-endian fields from a complete EWRAM snapshot."""

    if len(snapshot) != 256 * 1024:
        raise ValueError("EWRAM snapshot has the wrong size")
    result: dict[str, int] = {}
    for item in observations:
        offsets = _observation_bytes(item)
        result[item.name] = int.from_bytes(
            snapshot[offsets.start : offsets.stop], "little"
        )
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
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("/tmp/emerald-calibration-evidence"),
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="show the exact route replay in a human-facing window",
    )
    parser.add_argument(
        "--ui-pause",
        action="store_true",
        help="pause the UI replay after every named route checkpoint",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    viewer = None
    evidence_dir = args.evidence_dir

    def factory() -> PyBoyAdvance:
        adapter = PyBoyAdvance(
            args.rom,
            args.bios,
            skip_bios=False,
            emulation_speed=1 if viewer is not None else 0,
            frame_observer=None if viewer is None else viewer.show_frame,
        )
        adapter.require_capabilities("frames", "keys", "pixels", "read_telemetry", "timing_telemetry")
        return adapter

    try:
        if args.ui_pause and not args.ui:
            raise ValueError("--ui-pause requires --ui")
        if args.ui:
            from live_viewer import LiveViewer

            viewer = LiveViewer()
            evidence_dir = args.evidence_dir / datetime.now().strftime("ui-%Y%m%d-%H%M%S")
        identity = rom_identity(args.rom)
        from starter_route import load_route_spec

        route = load_route_spec(args.route)
        observations = VALIDATED_BPEE_V10_STARTER_STATE_MAP
        if not observations:
            observations = PROVISIONAL_BPEE_V10_STARTER_STATE_MAP
        # Backend diagnostics belong on stderr; stdout is one machine-readable
        # result for the calibration driver.
        with redirect_stdout(sys.stderr):
            result = qualify_route_replay(
                factory,
                identity=identity,
                route=route,
                runs=args.runs,
                observations=observations,
                evidence_dir=evidence_dir,
                before_route_step=(
                    None
                    if viewer is None
                    else lambda run, step_name, step_index: viewer.set_status(
                        f"Qualification run {run}/{args.runs} · step {step_index}: {step_name}"
                    )
                ),
                after_route_step=(
                    None
                    if viewer is None or not args.ui_pause
                    else lambda run, step_name, step_index: viewer.wait_for_continue(
                        f"Qualification run {run}/{args.runs} · completed step {step_index}: {step_name}"
                    )
                ),
            )
        if not VALIDATED_BPEE_V10_STARTER_STATE_MAP:
            result = {
                "qualified": False,
                "rom": identity,
                "evidence": result,
                "error": "route evidence passed, but the production starter-state map remains disabled until manually promoted",
            }
            print(json.dumps(result, sort_keys=True))
            return 1
    except (BackendCapabilityError, OSError, RuntimeError, TypeError, ValueError) as exc:
        if viewer is not None:
            try:
                viewer.wait_until_closed(f"Qualification failed: {exc} — close this window to finish")
            except RuntimeError:
                pass
        print(json.dumps({"qualified": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    if viewer is not None:
        viewer.wait_until_closed("Qualification passed — close this window to finish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
