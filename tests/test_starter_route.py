from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pyboy_adapter import GbaKey
from qualification import EWRAM_START
from starter_route import EWRAM_SIZE, RouteStep, diff_ewram, load_route, run_route, snapshot_ewram


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
