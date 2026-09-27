from __future__ import annotations

import pytest

from jev_policy import RecordedPolicy
from pyboy_adapter import GbaKey
from starter_branch import StarterLayout, StarterObservation
from starter_episode import StarterPostconditionError, run_recorded_starter_episode


class FakeEpisodeAdapter:
    def __init__(self) -> None:
        self.keys: list[GbaKey] = []

    def tap(self, key: GbaKey, hold_frames: int = 1, settle_frames: int = 1) -> None:
        self.keys.append(key)


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
