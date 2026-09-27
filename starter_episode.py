"""Recorded-policy starter episode controller.

Live Jev is intentionally not configured here.  The caller must first supply
an observation from a qualified BPEE v1.0 state map.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from jev_policy import RecordedPolicy
from pyboy_adapter import GbaKey
from starter_branch import StarterLayout, StarterObservation, choose_starter, compile_pokeball_move


class EpisodeAdapter(Protocol):
    def tap(self, key: GbaKey, hold_frames: int = 1, settle_frames: int = 1) -> None: ...


class StarterPostconditionError(RuntimeError):
    """Raised when a semantic choice did not yield its measured result."""


def run_recorded_starter_episode(
    adapter: EpisodeAdapter,
    policy: RecordedPolicy,
    observation: StarterObservation,
    layout: StarterLayout,
    verify_choice: Callable[[str], bool],
) -> str:
    """Choose, execute, and verify one starter without enabling live policy."""

    choice = choose_starter(policy, observation)
    for key in compile_pokeball_move(observation.cursor_index, choice, layout):
        adapter.tap(key)
    if not verify_choice(choice):
        raise StarterPostconditionError(f"starter postcondition failed for {choice}")
    return choice
