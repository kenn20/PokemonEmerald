from __future__ import annotations

import pytest

from jev_policy import RecordedPolicy
from pyboy_adapter import GbaKey
from starter_branch import StarterObservation, choose_starter, compile_cursor_move


def test_starter_choice_is_semantic_and_legal() -> None:
    observation = StarterObservation(cursor_index=0, prompt_fingerprint="birch-v1")
    policy = RecordedPolicy({"choose_starter": "MUDKIP"})
    assert choose_starter(policy, observation) == "MUDKIP"


@pytest.mark.parametrize(
    ("cursor", "target", "expected"),
    [
        (0, "TREECKO", [GbaKey.A]),
        (0, "TORCHIC", [GbaKey.DOWN, GbaKey.A]),
        (2, "TREECKO", [GbaKey.UP, GbaKey.UP, GbaKey.A]),
    ],
)
def test_compile_cursor_move_is_relative(
    cursor: int, target: str, expected: list[GbaKey]
) -> None:
    assert compile_cursor_move(cursor, target) == expected


def test_compile_cursor_move_rejects_unknown_option() -> None:
    with pytest.raises(ValueError, match="unknown starter"):
        compile_cursor_move(0, "PIKACHU")
