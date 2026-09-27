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
class StarterLayout:
    """Measured left-to-right order of Birch's three physical Poké Balls."""

    option_ids: tuple[str, str, str]

    def __post_init__(self) -> None:
        expected = {option.option_id for option in STARTER_OPTIONS}
        if set(self.option_ids) != expected or len(set(self.option_ids)) != len(self.option_ids):
            raise ValueError("starter layout must contain each legal starter exactly once")


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


def compile_pokeball_move(
    current_index: int, target_id: str, layout: StarterLayout
) -> list[GbaKey]:
    """Compile a validated physical Poké Ball choice into LEFT/RIGHT then A."""

    if not 0 <= current_index < len(layout.option_ids):
        raise ValueError(f"cursor index out of range: {current_index}")
    if target_id not in layout.option_ids:
        raise ValueError(f"unknown starter option: {target_id}")
    delta = layout.option_ids.index(target_id) - current_index
    key = GbaKey.RIGHT if delta > 0 else GbaKey.LEFT
    return [key] * abs(delta) + [GbaKey.A]
