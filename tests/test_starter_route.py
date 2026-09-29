from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pyboy_adapter import GbaKey
from qualification import EWRAM_START
from starter_route import (
    EWRAM_SIZE,
    MAX_ROUTE_FRAMES,
    MAX_STEP_FRAMES,
    RouteEvidence,
    RouteSpec,
    RouteStep,
    diff_ewram,
    load_route,
    run_route_with_evidence,
    run_route,
    snapshot_ewram,
)


class FakeRouteAdapter:
    def __init__(self) -> None:
        self.frame_count = 0
        self.keys: list[GbaKey] = []
        self.memory = bytearray(EWRAM_SIZE)

    def frame(self, count: int = 1) -> None:
        self.frame_count += count

    def tap(self, key: GbaKey, hold_frames: int = 1, settle_frames: int = 1) -> None:
        self.keys.append(key)
        self.frame_count += hold_frames + settle_frames

    def pixels(self) -> np.ndarray:
        return np.full((160, 240, 3), self.frame_count % 255, dtype=np.uint8)

    def peek_u8(self, address: int) -> int:
        return self.memory[address - EWRAM_START]


def test_run_route_records_named_checkpoints() -> None:
    adapter = FakeRouteAdapter()
    checkpoints = run_route(
        adapter,
        (RouteStep("wait", None, 3), RouteStep("confirm", GbaKey.A, 4)),
    )
    assert [item.name for item in checkpoints] == ["wait", "confirm"]
    assert checkpoints[-1].frame_count == 9
    assert adapter.keys == [GbaKey.A]


def test_route_evidence_reports_the_step_before_advancing() -> None:
    adapter = FakeRouteAdapter()
    spec = RouteSpec(
        steps=(RouteStep("cursor_before", None, 1),),
        evidence=RouteEvidence(
            starter_checkpoint="cursor_before",
            cursor_before="cursor_before",
            cursor_after="cursor_before",
            confirm_before="cursor_before",
            confirm_after="cursor_after",
        ),
    )
    observed: list[tuple[str, int, int]] = []
    completed: list[tuple[str, int, int]] = []

    run_route_with_evidence(
        adapter,
        spec,
        before_step=lambda step, index: observed.append((step.name, index, adapter.frame_count)),
        after_step=lambda step, index: completed.append((step.name, index, adapter.frame_count)),
    )

    assert observed == [("cursor_before", 1, 0)]
    assert completed == [("cursor_before", 1, 1)]


def test_route_step_rejects_excessive_actual_frame_cost() -> None:
    with pytest.raises(ValueError, match=str(MAX_STEP_FRAMES)):
        RouteStep("wait", None, MAX_STEP_FRAMES + 1)
    with pytest.raises(ValueError, match="frame cost"):
        RouteStep("hold", GbaKey.A, MAX_STEP_FRAMES, hold_frames=1)


def test_run_route_rejects_over_budget_before_advancing() -> None:
    adapter = FakeRouteAdapter()
    steps = tuple(
        RouteStep(f"wait-{index}", None, MAX_STEP_FRAMES)
        for index in range(MAX_ROUTE_FRAMES // MAX_STEP_FRAMES + 1)
    )
    with pytest.raises(ValueError, match="budget exceeded"):
        run_route(adapter, steps)
    assert adapter.frame_count == 0


def test_snapshot_and_diff_ewram_capture_each_changed_byte() -> None:
    adapter = FakeRouteAdapter()
    before = snapshot_ewram(adapter)
    adapter.memory[3] = 9
    adapter.memory[17] = 2
    differences = diff_ewram(before, snapshot_ewram(adapter))
    assert [(item.address, item.before, item.after) for item in differences] == [
        (EWRAM_START + 3, 0, 9),
        (EWRAM_START + 17, 0, 2),
    ]


def test_diff_ewram_rejects_incomplete_snapshots() -> None:
    with pytest.raises(ValueError, match="snapshots"):
        diff_ewram(b"", b"")


def test_load_route_validates_known_keys(tmp_path: Path) -> None:
    route = tmp_path / "route.json"
    route.write_text(json.dumps([{"name": "start", "key": "START", "frames": 30}]))
    assert load_route(route) == (RouteStep("start", GbaKey.START, 30),)
    route.write_text(json.dumps([{"name": "bad", "key": "CHEAT", "frames": 1}]))
    with pytest.raises(ValueError, match="unknown GBA key"):
        load_route(route)
