from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import qualification
from qualification import (
    RamObservation,
    capability_checkpoint,
    observe_ram,
    probe_non_advancing_peeks,
    qualify_replay,
    rom_identity,
    visual_fingerprint,
)


class FakeAdapter:
    def __init__(self, pixels: np.ndarray, telemetry: bool = True, cursor: int = 4) -> None:
        self._pixels = pixels
        self._telemetry = telemetry
        self._cursor = cursor
        self.frame_count = 0
        self._emulation_cycles = 0

    def require_capabilities(self, *required: str) -> None:
        if "read_telemetry" in required and not self._telemetry:
            raise RuntimeError("missing read-only memory telemetry")

    def frame(self, count: int = 1) -> None:
        self.frame_count += count
        self._emulation_cycles += count * 280896

    def pixels(self) -> np.ndarray:
        return self._pixels.copy()

    def peek_u8(self, address: int) -> int:
        assert address == 0x02000000
        return self._cursor

    def peek_u16(self, address: int) -> int:
        return self.peek_u8(address)

    def peek_u32(self, address: int) -> int:
        return self.peek_u8(address)

    def timing_checkpoint(self) -> int:
        return self._emulation_cycles


def visible_frame(seed: int) -> np.ndarray:
    pixels = np.zeros((160, 240, 3), dtype=np.uint8)
    pixels[:, :, 0] = seed
    pixels[0, 0] = [0, 1, 2]
    pixels[0, 1] = [3, 4, 5]
    pixels[0, 2] = [6, 7, 8]
    return pixels


def test_visual_fingerprint_is_stable_for_same_pixels() -> None:
    assert visual_fingerprint(visible_frame(10)) == visual_fingerprint(visible_frame(10))


def test_peek_probe_rejects_missing_telemetry() -> None:
    with pytest.raises(RuntimeError, match="telemetry"):
        probe_non_advancing_peeks(FakeAdapter(visible_frame(10), telemetry=False))


def test_peek_probe_rejects_timing_or_framebuffer_mutation() -> None:
    class MutatingAdapter(FakeAdapter):
        def peek_u8(self, address: int) -> int:
            self.frame_count += 1
            self._emulation_cycles += 1
            return super().peek_u8(address)

    with pytest.raises(RuntimeError, match="timing or framebuffer checkpoint"):
        probe_non_advancing_peeks(MutatingAdapter(visible_frame(10)), peeks=2)


def test_capability_checkpoint_records_visible_timing_and_peek_proof() -> None:
    result = capability_checkpoint(lambda: FakeAdapter(visible_frame(10)), frames=3)
    assert result["frame_count"] == 3
    assert result["peek_probe"]["peeks"] == 1_000
    assert result["peek_probe"]["emulation_cycles"] == 842688


def test_replay_qualification_rejects_divergent_runs() -> None:
    seed = iter([10, 11, 10])
    with pytest.raises(RuntimeError, match="fresh runs diverged"):
        qualify_replay(
            lambda: FakeAdapter(visible_frame(next(seed))),
            identity={"sha256": "expected"},
            frames=3,
            runs=3,
            observations=(RamObservation("starter_cursor", 0x02000000, 8),),
        )


def test_replay_qualification_requires_three_identical_fresh_runs() -> None:
    result = qualify_replay(
        lambda: FakeAdapter(visible_frame(10)),
        identity={"sha256": "expected"},
        frames=3,
        runs=3,
        observations=(RamObservation("starter_cursor", 0x02000000, 8),),
    )
    assert result["qualified"] is True
    assert result["checkpoint"]["observation"] == {"starter_cursor": 4}
    assert result["checkpoint"]["peek_probe"]["peeks"] == 1_000


def test_observe_ram_rejects_missing_or_ambiguous_state_map() -> None:
    adapter = FakeAdapter(visible_frame(10))
    with pytest.raises(RuntimeError, match="at least one"):
        observe_ram(adapter, ())
    with pytest.raises(ValueError, match="unique"):
        observe_ram(
            adapter,
            (
                RamObservation("cursor", 0x02000000, 8),
                RamObservation("cursor", 0x02000000, 16),
            ),
        )


def test_rom_identity_records_and_enforces_sha256(tmp_path: Path) -> None:
    rom = tmp_path / "emerald.gba"
    rom.write_bytes(b"BPEE")
    expected = "61492b3c2074991ed51fa3a255f3414f9e1c78a6c27ce355996ce148afa1d96b"
    assert rom_identity(rom, expected_sha256=expected) == {
        "path": str(rom),
        "sha256": expected,
    }
    with pytest.raises(RuntimeError, match="unsupported ROM"):
        rom_identity(rom, expected_sha256="0" * 64)


def test_main_emits_one_fail_closed_json_result(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(qualification, "rom_identity", lambda rom: {"path": str(rom)})
    monkeypatch.setattr(
        qualification,
        "capability_checkpoint",
        lambda factory, *, frames: {"frame_count": frames, "peek_probe": {"peeks": 1_000}},
    )
    assert qualification.main(["--rom", "emerald.gba", "--bios", "bios.bin"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "capability_checkpoint": {"frame_count": 900, "peek_probe": {"peeks": 1_000}},
        "error": "BPEE v1.0 starter-state map is not validated; Jev remains disabled",
        "qualified": False,
        "rom": {"path": "emerald.gba"},
    }
