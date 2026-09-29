"""Three-fresh-run Jev starter acceptance harness.

The route is supplied by the operator and stays outside production.  The
harness recreates the emulator for every run, reads only the qualified map,
and exits non-zero on any policy, input, or postcondition failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jev_policy import JsonlDecisionLog, JsonlPolicyClient
from pyboy_adapter import PyBoyAdvance
from qualification import (
    STARTER_SPECIES_IDS,
    VALIDATED_BPEE_V10_STARTER_STATE_MAP,
    observe_ram,
    rom_identity,
)
from starter_branch import StarterLayout
from starter_episode import run_jev_starter_episode
from starter_route import load_route_spec, run_route_with_evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--bios", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--policy-command", nargs="+")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--expected-species", choices=("TREECKO", "TORCHIC", "MUDKIP"), required=True)
    parser.add_argument(
        "--ui",
        action="store_true",
        help="show the exact route and Jev choice replay in a human-facing window",
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
    try:
        if args.ui_pause and not args.ui:
            raise ValueError("--ui-pause requires --ui")
        if args.runs < 3:
            raise ValueError("--runs must be at least 3")
        if not VALIDATED_BPEE_V10_STARTER_STATE_MAP:
            raise RuntimeError(
                "BPEE v1.0 starter-state map is not validated; live Jev remains disabled"
            )
        identity = rom_identity(args.rom)
        route = load_route_spec(args.route)
        policy = JsonlPolicyClient(args.policy_command)
        if args.ui:
            from live_viewer import LiveViewer

            viewer = LiveViewer()
        results = []
        route_checkpoints = []
        for run in range(1, args.runs + 1):
            adapter = PyBoyAdvance(
                args.rom,
                args.bios,
                skip_bios=False,
                emulation_speed=1 if viewer is not None else 0,
                frame_observer=None if viewer is None else viewer.show_frame,
            )
            adapter.require_capabilities(
                "frames", "keys", "pixels", "read_telemetry", "timing_telemetry"
            )
            checkpoints, _ = run_route_with_evidence(
                adapter,
                route,
                before_step=(
                    None
                    if viewer is None
                    else lambda step, step_index: viewer.set_status(
                        f"Acceptance run {run}/{args.runs} · step {step_index}: {step.name}"
                    )
                ),
                after_step=(
                    None
                    if viewer is None or not args.ui_pause
                    else lambda step, step_index: viewer.wait_for_continue(
                        f"Acceptance run {run}/{args.runs} · completed step {step_index}: {step.name}"
                    )
                ),
            )
            route_checkpoints.append([checkpoint.__dict__ for checkpoint in checkpoints])
            decision_log = JsonlDecisionLog(args.log)
            try:
                if viewer is not None:
                    viewer.set_status(f"Acceptance run {run}/{args.runs} · Jev chooses starter")
                choice = run_jev_starter_episode(
                    adapter,
                    policy,
                    StarterLayout(("TREECKO", "TORCHIC", "MUDKIP")),
                    lambda expected: (
                        expected == args.expected_species
                        and observe_ram(adapter, VALIDATED_BPEE_V10_STARTER_STATE_MAP)[
                            "selected_species"
                        ]
                        == STARTER_SPECIES_IDS[expected]
                    ),
                    decision_log,
                )
            finally:
                decision_log.close()
            if choice != args.expected_species:
                raise RuntimeError(
                    f"run {run} Jev chose {choice}; expected {args.expected_species}"
                )
            results.append({"choice": choice, "verified": True})
        if len({json.dumps(item, sort_keys=True) for item in route_checkpoints}) != 1:
            raise RuntimeError("fresh starter routes diverged")
        result = {"qualified": True, "rom": identity, "runs": results}
        print(json.dumps(result, sort_keys=True))
        if viewer is not None:
            viewer.wait_until_closed("Acceptance passed — close this window to finish")
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        if viewer is not None:
            try:
                viewer.wait_until_closed(f"Acceptance failed: {exc} — close this window to finish")
            except RuntimeError:
                pass
        print(json.dumps({"qualified": False, "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
