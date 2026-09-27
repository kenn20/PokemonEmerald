from __future__ import annotations

from pathlib import Path

import pytest

from jev_policy import JsonlPolicyClient, LegalOption, PolicyError, RecordedPolicy


OPTIONS = (LegalOption("TREECKO", "Treecko"), LegalOption("TORCHIC", "Torchic"))


def test_recorded_policy_rejects_choice_outside_legal_options() -> None:
    policy = RecordedPolicy({"choose_starter": "MUDKIP"})
    with pytest.raises(PolicyError, match="legal options"):
        policy.choose("choose_starter", {"phase": "starter_choice"}, OPTIONS)


def test_jsonl_policy_accepts_existing_jev_answer_shape(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.py"
    sidecar.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        "assert request['purpose'] == 'choose_starter'\n"
        "assert request['questions']['decision']['type'] == 'choice'\n"
        "print(json.dumps({'answers': {'decision': {'type': 'choice', 'choice': 'TORCHIC'}}}))\n",
        encoding="utf-8",
    )
    policy = JsonlPolicyClient(["python", str(sidecar)])
    assert policy.choose("choose_starter", {"phase": "starter_choice"}, OPTIONS) == "TORCHIC"


def test_jsonl_policy_rejects_malformed_response(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.py"
    sidecar.write_text("print('not json')\n", encoding="utf-8")
    policy = JsonlPolicyClient(["python", str(sidecar)])
    with pytest.raises(PolicyError, match="invalid JSON"):
        policy.choose("choose_starter", {}, OPTIONS)
