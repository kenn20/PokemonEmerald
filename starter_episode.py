"""Recorded-policy starter episode controller.

Live Jev is intentionally not configured here.  The caller must first supply
an observation from a qualified BPEE v1.0 state map.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from jev_policy import JsonlDecisionLog, PolicyClient, RecordedPolicy
from pyboy_adapter import GbaKey
from qualification import VALIDATED_BPEE_V10_STARTER_STATE_MAP, observe_ram, visual_fingerprint
from starter_branch import (
    StarterLayout,
    StarterObservation,
    STARTER_OPTIONS,
    choose_starter,
    compile_pokeball_move,
)


class EpisodeAdapter(Protocol):
    def tap(self, key: GbaKey, hold_frames: int = 1, settle_frames: int = 1) -> None: ...

    def peek_u8(self, address: int) -> int: ...

    def peek_u16(self, address: int) -> int: ...

    def peek_u32(self, address: int) -> int: ...

    def pixels(self): ...


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


def read_starter_observation(
    adapter: EpisodeAdapter,
    observations=VALIDATED_BPEE_V10_STARTER_STATE_MAP,
) -> StarterObservation:
    """Project qualified read-only RAM into the semantic Jev observation."""

    if not observations:
        raise StarterPostconditionError(
            "validated starter-state map is empty; live Jev remains disabled"
        )
    values = observe_ram(adapter, observations)
    phase = values["starter_phase"]
    cursor = values["starter_cursor"]
    if phase != 1:
        raise StarterPostconditionError(f"starter phase is not ready: {phase}")
    if not 0 <= cursor < 3:
        raise StarterPostconditionError(f"starter cursor is out of range: {cursor}")
    return StarterObservation(
        cursor_index=cursor,
        prompt_fingerprint=str(visual_fingerprint(adapter.pixels())["sha256"]),
        phase=phase,
        selected_species=values["selected_species"],
    )


def run_jev_starter_episode(
    adapter: EpisodeAdapter,
    policy: PolicyClient,
    layout: StarterLayout,
    verify_choice: Callable[[str], bool],
    decision_log: JsonlDecisionLog | None = None,
    observations=VALIDATED_BPEE_V10_STARTER_STATE_MAP,
) -> str:
    """Ask Jev for a semantic starter and fail closed around execution."""

    observation = read_starter_observation(adapter, observations)
    state = observation.state()
    try:
        choice = choose_starter(policy, observation)
    except Exception as exc:
        if decision_log is not None:
            decision_log.record(
                purpose="choose_starter",
                state=state,
                options=STARTER_OPTIONS,
                choice="",
                verified=False,
                reason=str(exc),
            )
        raise
    try:
        for key in compile_pokeball_move(observation.cursor_index, choice, layout):
            adapter.tap(key)
        verified = verify_choice(choice)
    except Exception as exc:
        if decision_log is not None:
            decision_log.record(
                purpose="choose_starter",
                state=state,
                options=STARTER_OPTIONS,
                choice=choice,
                verified=False,
                reason=str(exc),
            )
        raise
    if decision_log is not None:
        decision_log.record(
            purpose="choose_starter",
            state=state,
            options=STARTER_OPTIONS,
            choice=choice,
            verified=verified,
            reason=None if verified else "starter postcondition failed",
        )
    if not verified:
        raise StarterPostconditionError(f"starter postcondition failed for {choice}")
    return choice
