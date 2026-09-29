from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from pyboy_adapter import BackendCapabilityError, PyBoyAdvance


class PeekBackend:
    def __init__(self) -> None:
        self.screen = SimpleNamespace(ndarray=np.zeros((160, 240, 3), dtype=np.uint8))
        self._emulation_cycles = 123

    @property
    def memory(self) -> object:
        raise AssertionError("adapter must use public peek APIs, not backend memory")

    def frame(self, count: int) -> None:
        del count

    def press_key(self, key: object) -> None:
        del key

    def release_key(self, key: object) -> None:
        del key

    def timing_checkpoint(self) -> int:
        return self._emulation_cycles

    def peek_u8(self, address: int) -> int:
        return address + 8

    def peek_u16(self, address: int) -> int:
        return address + 16

    def peek_u32(self, address: int) -> int:
        return address + 32


def adapter_for(backend: object) -> PyBoyAdvance:
    adapter = object.__new__(PyBoyAdvance)
    adapter._emulator = backend
    adapter._frame_count = 0
    return adapter


def test_adapter_uses_only_public_peek_apis() -> None:
    adapter = adapter_for(PeekBackend())
    assert adapter.peek_u8(1) == 9
    assert adapter.peek_u16(1) == 17
    assert adapter.peek_u32(1) == 33
    assert adapter.capabilities()["read_telemetry"] is True
    assert adapter.timing_checkpoint() == 123
    assert adapter.capabilities()["timing_telemetry"] is True


def test_adapter_reports_missing_public_peek_capability() -> None:
    backend = PeekBackend()
    backend.peek_u16 = None  # type: ignore[method-assign]
    adapter = adapter_for(backend)
    assert adapter.capabilities()["read_telemetry"] is False
    with pytest.raises(BackendCapabilityError, match="read_telemetry"):
        adapter.require_capabilities("read_telemetry")
    with pytest.raises(BackendCapabilityError, match="peek_u16"):
        adapter.peek_u16(0x02000000)
    backend.timing_checkpoint = None  # type: ignore[method-assign]
    with pytest.raises(BackendCapabilityError, match="timing_checkpoint"):
        adapter.timing_checkpoint()


def test_frame_observer_sees_the_completed_batch_without_changing_frame_count() -> None:
    adapter = adapter_for(PeekBackend())
    observed: list[tuple[int, tuple[int, ...]]] = []
    adapter._frame_observer = lambda pixels, frame_count: observed.append(
        (frame_count, pixels.shape)
    )

    adapter.frame(3)

    assert adapter.frame_count == 3
    assert observed == [(3, (160, 240, 3))]
