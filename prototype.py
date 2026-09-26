"""Headless Phase 1 title-screen smoke test for Pokémon Emerald."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from pyboy_adapter import PyBoyAdvance


BIOS_SIZE = 16 * 1024
FRAME_WIDTH = 240
FRAME_HEIGHT = 160


class AssetError(ValueError):
    """Raised when a required local ROM or BIOS asset is unusable."""


class FrameAdapter(Protocol):
    frame_count: int

    def frame(self, count: int = 1) -> None: ...

    def pixels(self) -> np.ndarray: ...


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_assets(rom: Path, bios: Path) -> None:
    if not rom.is_file():
        raise AssetError(f"ROM does not exist or is not a file: {rom}")
    if not bios.is_file():
        raise AssetError(f"BIOS does not exist or is not a file: {bios}")
    bios_size = bios.stat().st_size
    if bios_size != BIOS_SIZE:
        raise AssetError(f"BIOS must be exactly {BIOS_SIZE} bytes; got {bios_size}")


def export_png(pixels: np.ndarray, path: Path) -> None:
    expected_shape = (FRAME_HEIGHT, FRAME_WIDTH, 3)
    if pixels.shape != expected_shape:
        raise ValueError(f"cannot export framebuffer with shape {pixels.shape}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        Image.fromarray(np.asarray(pixels, dtype=np.uint8), "RGB").save(path, format="PNG")
    except (OSError, ValueError) as exc:
        raise OSError(f"failed to export screenshot {path}: {exc}") from exc


def capture(
    adapter: FrameAdapter,
    frames: int,
    screenshot: Path,
) -> dict[str, object]:
    if isinstance(frames, bool) or not isinstance(frames, int):
        raise TypeError("frames must be an integer")
    if frames < 0:
        raise ValueError("frames must be non-negative")
    adapter.frame(frames)
    if adapter.frame_count != frames:
        raise RuntimeError(
            f"adapter stepped {adapter.frame_count} frames; expected exactly {frames}"
        )
    pixels = adapter.pixels()
    export_png(pixels, screenshot)
    width = int(pixels.shape[1])
    height = int(pixels.shape[0])
    return {
        "frames": adapter.frame_count,
        "framebuffer_dimensions": {"width": width, "height": height},
        "framebuffer_width": width,
        "framebuffer_height": height,
        "framebuffer_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "screenshot": str(screenshot),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--bios", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=900)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    validate_assets(args.rom, args.bios)
    result: dict[str, object] = {
        "rom_sha256": sha256_file(args.rom),
        "bios_sha256": sha256_file(args.bios),
    }
    adapter = PyBoyAdvance(
        rom=args.rom,
        bios=args.bios,
        skip_bios=False,
        emulation_speed=0,
    )
    result.update(capture(adapter, args.frames, args.screenshot))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (AssetError, OSError, RuntimeError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    if args.as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
