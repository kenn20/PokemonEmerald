"""The first narrow Emerald semantic branch: choosing a starter."""

from __future__ import annotations

from dataclasses import dataclass

from jev_policy import LegalOption, PolicyClient, validate_choice
from pyboy_adapter import GbaKey


STARTER_OPTIONS = (
    LegalOption("TREECKO", "Choose Treecko from the three starter Poké Balls."),
    LegalOption("TORCHIC", "Choose Torchic from the three starter Poké Balls."),
    LegalOption("MUDKIP", "Choose Mudkip from the three starter Poké Balls."),
)


@dataclass(frozen=True)
class StarterObservation:
    """Stable, typed projection of the starter-menu observation."""

    cursor_index: int
    prompt_fingerprint: str

    def state(self) -> dict[str, object]:
        return {
            "phase": "starter_choice",
            "cursor_index": self.cursor_index,
            "prompt_fingerprint": self.prompt_fingerprint,
        }


def choose_starter(
    policy: PolicyClient,
    observation: StarterObservation,
) -> str:
    """Ask Jev to choose only from the three currently legal starters."""

    choice = policy.choose("choose_starter", observation.state(), STARTER_OPTIONS)
    return validate_choice(choice, STARTER_OPTIONS)


def compile_cursor_move(current_index: int, target_id: str) -> list[GbaKey]:
    """Compile a vertical starter choice into relative D-pad input."""

    if not 0 <= current_index < len(STARTER_OPTIONS):
        raise ValueError(f"cursor index out of range: {current_index}")
    targets = {option.option_id: index for index, option in enumerate(STARTER_OPTIONS)}
    if target_id not in targets:
        raise ValueError(f"unknown starter option: {target_id}")
    delta = targets[target_id] - current_index
    key = GbaKey.DOWN if delta > 0 else GbaKey.UP
    return [key] * abs(delta) + [GbaKey.A]
