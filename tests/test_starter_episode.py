from __future__ import annotations

import pytest

from jev_policy import RecordedPolicy
from pyboy_adapter import GbaKey
from starter_branch import StarterLayout, StarterObservation
from qualification import PROVISIONAL_BPEE_V10_STARTER_STATE_MAP
from starter_episode import (
    StarterPostconditionError,
    read_starter_observation,
    run_jev_starter_episode,
    run_recorded_starter_episode,
)


class FakeEpisodeAdapter:
    def __init__(self) -> None:
        self.keys: list[GbaKey] = []

    def tap(self, key: GbaKey, hold_frames: int = 1, settle_frames: int = 1) -> None:
        self.keys.append(key)


class FakeLiveAdapter(FakeEpisodeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.values = {0x020370B8: 1, 0x020370C2: 0, 0x020370C4: 258}

    def peek_u8(self, address: int) -> int:
        return self.values[address]

    def peek_u16(self, address: int) -> int:
        return self.values[address]

    def peek_u32(self, address: int) -> int:
        return self.values[address]

    def pixels(self):
        import numpy as np
        return np.zeros((160, 240, 3), dtype=np.uint8)


def test_recorded_episode_executes_and_verifies_semantic_choice() -> None:
    adapter = FakeEpisodeAdapter()
    result = run_recorded_starter_episode(
        adapter,
        RecordedPolicy({"choose_starter": "MUDKIP"}),
        StarterObservation(cursor_index=0, prompt_fingerprint="starter-v1"),
        StarterLayout(("TREECKO", "TORCHIC", "MUDKIP")),
        lambda choice: choice == "MUDKIP",
    )
    assert result == "MUDKIP"
    assert adapter.keys == [GbaKey.RIGHT, GbaKey.RIGHT, GbaKey.A]


def test_recorded_episode_fails_closed_on_wrong_postcondition() -> None:
    with pytest.raises(StarterPostconditionError, match="TREECKO"):
        run_recorded_starter_episode(
            FakeEpisodeAdapter(),
            RecordedPolicy({"choose_starter": "TREECKO"}),
            StarterObservation(cursor_index=0, prompt_fingerprint="starter-v1"),
            StarterLayout(("TREECKO", "TORCHIC", "MUDKIP")),
            lambda choice: False,
        )


def test_live_episode_projects_ram_calls_policy_and_verifies_species() -> None:
    adapter = FakeLiveAdapter()
    result = run_jev_starter_episode(
        adapter,
        RecordedPolicy({"choose_starter": "MUDKIP"}),
        StarterLayout(("TREECKO", "TORCHIC", "MUDKIP")),
        lambda choice: choice == "MUDKIP" and adapter.values[0x020370C4] == 258,
        observations=PROVISIONAL_BPEE_V10_STARTER_STATE_MAP,
    )
    assert result == "MUDKIP"
    assert adapter.keys == [GbaKey.RIGHT, GbaKey.RIGHT, GbaKey.A]


def test_live_observation_rejects_non_starter_phase() -> None:
    adapter = FakeLiveAdapter()
    adapter.values[0x020370B8] = 0
    with pytest.raises(StarterPostconditionError, match="not ready"):
        read_starter_observation(adapter, PROVISIONAL_BPEE_V10_STARTER_STATE_MAP)
