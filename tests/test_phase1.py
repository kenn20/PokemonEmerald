from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import prototype


def test_missing_rom_is_reported(tmp_path: Path) -> None:
    bios = tmp_path / "bios.bin"
    bios.write_bytes(b"\0" * prototype.BIOS_SIZE)
    with pytest.raises(prototype.AssetError, match="ROM does not exist"):
        prototype.validate_assets(tmp_path / "missing.gba", bios)


def test_missing_bios_is_reported(tmp_path: Path) -> None:
    rom = tmp_path / "game.gba"
    rom.write_bytes(b"rom")
    with pytest.raises(prototype.AssetError, match="BIOS does not exist"):
        prototype.validate_assets(rom, tmp_path / "missing.bin")


def test_invalid_bios_size_is_reported(tmp_path: Path) -> None:
    rom = tmp_path / "game.gba"
    bios = tmp_path / "bios.bin"
    rom.write_bytes(b"rom")
    bios.write_bytes(b"\0" * (prototype.BIOS_SIZE - 1))
    with pytest.raises(prototype.AssetError, match="exactly 16384 bytes"):
        prototype.validate_assets(rom, bios)


def test_image_export_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenImage:
        def save(self, *args: object, **kwargs: object) -> None:
            raise OSError("disk full")

    monkeypatch.setattr(prototype.Image, "fromarray", lambda *args, **kwargs: BrokenImage())
    pixels = np.zeros((prototype.FRAME_HEIGHT, prototype.FRAME_WIDTH, 3), dtype=np.uint8)
    with pytest.raises(OSError, match="failed to export screenshot"):
        prototype.export_png(pixels, tmp_path / "title.png")


def test_fake_adapter_frame_counter() -> None:
    class FakeAdapter:
        frame_count = 0

        def frame(self, count: int = 1) -> None:
            self.frame_count += count

        def pixels(self) -> np.ndarray:
            return np.zeros((prototype.FRAME_HEIGHT, prototype.FRAME_WIDTH, 3), dtype=np.uint8)

    adapter = FakeAdapter()
    result = prototype.capture(adapter, 900, Path("artifacts/test-title.png"))
    assert adapter.frame_count == 900
    assert result["frames"] == 900
    assert result["framebuffer_dimensions"] == {"width": 240, "height": 160}
    assert result["framebuffer_width"] == 240
    assert result["framebuffer_height"] == 160
