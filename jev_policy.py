"""Typed semantic policy boundary for Jev.

Jev chooses among options supplied by the game adapter.  It never receives raw
emulator addresses and never emits controller keys.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class PolicyError(RuntimeError):
    """Raised when a policy response is missing, malformed, or illegal."""


@dataclass(frozen=True)
class LegalOption:
    """One semantic action currently permitted by the game state."""

    option_id: str
    description: str


class PolicyClient(Protocol):
    def choose(
        self,
        purpose: str,
        state: Mapping[str, Any],
        options: Sequence[LegalOption],
    ) -> str: ...


def validate_choice(choice: object, options: Sequence[LegalOption]) -> str:
    """Return a legal option ID or fail closed."""

    legal_ids = {option.option_id for option in options}
    if not isinstance(choice, str):
        raise PolicyError("policy choice must be a string option ID")
    if choice not in legal_ids:
        raise PolicyError(
            f"policy selected {choice!r}; legal options are {sorted(legal_ids)!r}"
        )
    return choice


class RecordedPolicy:
    """Deterministic policy used by unit tests and offline replay."""

    def __init__(self, choices: Mapping[str, str]) -> None:
        self._choices = dict(choices)

    def choose(
        self,
        purpose: str,
        state: Mapping[str, Any],
        options: Sequence[LegalOption],
    ) -> str:
        del state
        if purpose not in self._choices:
            raise PolicyError(f"recorded policy has no response for {purpose!r}")
        return validate_choice(self._choices[purpose], options)


class JsonlPolicyClient:
    """Call a Node Jev sidecar using one JSON request per process invocation."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        configured = command or os.environ.get("JEV_COMMAND")
        if not configured:
            raise PolicyError("JEV_COMMAND is required for live Jev policy calls")
        self._command = list(configured) if not isinstance(configured, str) else shlex.split(configured)
        self._timeout_seconds = timeout_seconds

    def choose(
        self,
        purpose: str,
        state: Mapping[str, Any],
        options: Sequence[LegalOption],
    ) -> str:
        if not options:
            raise PolicyError(f"cannot ask Jev to choose from no options: {purpose}")
        request = {
            "purpose": purpose,
            "state": dict(state),
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": f"Choose the legal action for {purpose}.",
                    "criteria": {option.option_id: option.description for option in options},
                }
            },
        }
        try:
            completed = subprocess.run(
                self._command,
                input=json.dumps(request) + "\n",
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PolicyError(f"Jev sidecar failed for {purpose}: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-400:]
            raise PolicyError(f"Jev sidecar exited {completed.returncode}: {detail}")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PolicyError("Jev sidecar returned invalid JSON") from exc
        choice = _extract_choice(response)
        return validate_choice(choice, options)


def _extract_choice(response: object) -> object:
    if not isinstance(response, dict):
        raise PolicyError("Jev response must be a JSON object")
    if "choice" in response:
        return response["choice"]
    answers = response.get("answers")
    if isinstance(answers, dict):
        decision = answers.get("decision")
        if isinstance(decision, dict):
            return decision.get("choice")
    raise PolicyError("Jev response has no decision choice")


class JsonlDecisionLog:
    """Append replayable semantic decisions without writing emulator state."""

    def __init__(self, path: Path) -> None:
        self._handle = path.open("a", encoding="utf-8")

    def record(
        self,
        *,
        purpose: str,
        state: Mapping[str, Any],
        options: Sequence[LegalOption],
        choice: str,
        verified: bool,
        reason: str | None = None,
    ) -> None:
        row = {
            "purpose": purpose,
            "state": dict(state),
            "legal_options": [option.option_id for option in options],
            "choice": choice,
            "verified": verified,
        }
        if reason is not None:
            row["reason"] = reason
        self._handle.write(json.dumps(row, sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()
