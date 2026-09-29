"""Generate the disposable Emerald-to-Birch calibration route.

The timings are intentionally data, not Python control flow: calibrators can
edit one JSON step after observing a divergence and rerun the same evidence
driver.  This file never changes production state or the checked-in RAM map.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def step(name: str, key: str | None, frames: int, hold_frames: int = 2) -> dict[str, object]:
    row: dict[str, object] = {"name": name, "frames": frames}
    if key is not None:
        row["key"] = key
        row["hold_frames"] = hold_frames
    return row


def build_route() -> dict[str, object]:
    """Return the complete human-readable first-run route skeleton.

    Text advance and movement timings are conservative calibration defaults;
    they must be proven against the target ROM before promotion.
    """

    steps: list[dict[str, object]] = [
        step("bios_to_title_1", None, 600),
        step("bios_to_title_2", None, 300),
        step("battery_warning_dismiss", "A", 90),
        step("title_new_game", "START", 120),
        step("intro_birch_1", "A", 90),
        step("intro_birch_2", "A", 90),
        step("gender_boy", "A", 60),
        step("name_screen_open", "A", 60),
        # The default name is accepted through the on-screen OK control.  The
        # repeated neutral advances are explicit so divergence is visible.
        step("name_default_wait", None, 180),
        step("name_default_confirm", "START", 90),
        step("truck_arrive", None, 600),
        step("truck_exit", "A", 120),
        step("bedroom_clock", "A", 90),
        step("bedroom_down", "DOWN", 120),
        step("bedroom_exit", "DOWN", 120),
        step("mother_dialogue_1", "A", 90),
        step("mother_dialogue_2", "A", 90),
        step("house_exit", "DOWN", 120),
        step("littleroot_walk_1", "DOWN", 180),
        step("littleroot_walk_2", "RIGHT", 180),
        step("littleroot_walk_3", "UP", 180),
        step("birch_lab_enter", "UP", 180),
        step("lab_birch_dialogue_1", "A", 90),
        step("lab_birch_dialogue_2", "A", 90),
        step("lab_birch_dialogue_3", "A", 90),
        step("lab_birch_dialogue_4", "A", 90),
        step("lab_starter_menu_load", None, 300),
        step("starter_cursor_before_move", None, 30),
        step("starter_cursor_after_move", "RIGHT", 60),
        step("birch_starter", None, 30),
    ]
    return {
        "version": 1,
        "steps": steps,
        "evidence": {
            "starter_checkpoint": "birch_starter",
            "cursor_before": "starter_cursor_before_move",
            "cursor_after": "starter_cursor_after_move",
            "confirm_before": "birch_starter",
            "confirm_after": "starter_confirmation_after",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_route(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
