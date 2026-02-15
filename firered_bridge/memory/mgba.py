from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..mgba_client import mgba_read8 as _orig_mgba_read8
from ..mgba_client import mgba_read16 as _orig_mgba_read16
from ..mgba_client import mgba_read32 as _orig_mgba_read32
from ..mgba_client import mgba_read_range as _orig_mgba_read_range
from ..mgba_client import mgba_read_ranges as _orig_mgba_read_ranges
from .. import mgba_client as _mgba_client


@dataclass
class MgbaReadMetrics:
    read8_calls: int = 0
    read16_calls: int = 0
    read32_calls: int = 0
    read_range_calls: int = 0
    read_ranges_calls: int = 0
    read_range_bytes_calls: int = 0
    read_ranges_bytes_calls: int = 0
    ranges_read: int = 0
    bytes_requested: int = 0
    bytes_returned: int = 0


_MGBA_METRICS: contextvars.ContextVar[Optional[MgbaReadMetrics]] = contextvars.ContextVar(
    "firered_bridge_game_state_mgba_metrics",
    default=None,
)


@contextmanager
def _mgba_metrics_context() -> MgbaReadMetrics:
    metrics = MgbaReadMetrics()
    token = _MGBA_METRICS.set(metrics)
    try:
        yield metrics
    finally:
        _MGBA_METRICS.reset(token)


def _mgba_metrics() -> Optional[MgbaReadMetrics]:
    return _MGBA_METRICS.get()


def _record_mgba_read_ranges_bytes(ranges: Sequence[Tuple[int, int]], out: Sequence[bytes]) -> None:
    m = _mgba_metrics()
    if m is None:
        return
    m.read_ranges_bytes_calls += 1
    m.ranges_read += len(ranges)
    for _addr, length in ranges:
        m.bytes_requested += max(0, int(length))
    m.bytes_returned += sum(len(seg) for seg in out)


def _record_mgba_read_range_bytes(length: int, out: bytes) -> None:
    m = _mgba_metrics()
    if m is None:
        return
    m.read_range_bytes_calls += 1
    m.bytes_requested += max(0, int(length))
    m.bytes_returned += len(out)


def _try_mgba_read_ranges_bytes_no_fallback(ranges: Sequence[Tuple[int, int]]) -> Optional[List[bytes]]:
    """
    Best-effort readRangesBytes without the unit-test fallback to per-range reads.

    This is used when we want to explicitly detect "snapshot available" vs "not available" and
    fall back to slower, per-read parsing.
    """
    try:
        out = _mgba_client.mgba_read_ranges_bytes(list(ranges))
    except Exception:
        return None
    _record_mgba_read_ranges_bytes(ranges, out)
    return list(out)


def mgba_read_range_bytes(addr: int, length: int) -> bytes:
    """
    Read a raw byte range from emulator memory.

    Uses the socket/HTTP implementation when available, but falls back to `mgba_read_range`
    so unit tests can patch `mgba_read_range` without needing a live mGBA instance.
    """
    m = _mgba_metrics()
    if m is not None:
        m.read_range_bytes_calls += 1
        m.bytes_requested += max(0, int(length))
    try:
        out = _mgba_client.mgba_read_range_bytes(addr, length)
        if m is not None:
            m.bytes_returned += len(out)
        return out
    except Exception:
        # Fallback: tests can patch `mgba_read_range` and we'll still return bytes.
        return bytes(mgba_read_range(addr, length))


def mgba_read_ranges_bytes(ranges: List[Tuple[int, int]]) -> List[bytes]:
    """
    Read multiple (addr, length) ranges as raw bytes, preferably in one bridge call.

    Falls back to per-range `mgba_read_range` so unit tests can patch reads locally.
    """
    m = _mgba_metrics()
    if m is not None:
        m.read_ranges_bytes_calls += 1
        m.ranges_read += len(ranges)
        for _addr, length in ranges:
            m.bytes_requested += max(0, int(length))
    try:
        out = _mgba_client.mgba_read_ranges_bytes(ranges)
        if m is not None:
            m.bytes_returned += sum(len(seg) for seg in out)
        return out
    except Exception:
        return [bytes(mgba_read_range(addr, length)) for addr, length in ranges]


def mgba_read8(addr: int) -> int:
    m = _mgba_metrics()
    if m is not None:
        m.read8_calls += 1
        m.bytes_requested += 1
        m.bytes_returned += 1
    return _orig_mgba_read8(addr)


def mgba_read16(addr: int) -> int:
    m = _mgba_metrics()
    if m is not None:
        m.read16_calls += 1
        m.bytes_requested += 2
        m.bytes_returned += 2
    return _orig_mgba_read16(addr)


def mgba_read32(addr: int) -> int:
    m = _mgba_metrics()
    if m is not None:
        m.read32_calls += 1
        m.bytes_requested += 4
        m.bytes_returned += 4
    return _orig_mgba_read32(addr)


def mgba_read_range(addr: int, length: int) -> List[int]:
    m = _mgba_metrics()
    if m is not None:
        m.read_range_calls += 1
        m.bytes_requested += max(0, int(length))
    out = _orig_mgba_read_range(addr, length)
    if m is not None:
        m.bytes_returned += len(out)
    return out


def mgba_read_ranges(ranges: List[Tuple[int, int]]) -> List[List[int]]:
    m = _mgba_metrics()
    if m is not None:
        m.read_ranges_calls += 1
        m.ranges_read += len(ranges)
        for _addr, length in ranges:
            m.bytes_requested += max(0, int(length))
    out = _orig_mgba_read_ranges(ranges)
    if m is not None:
        m.bytes_returned += sum(len(seg) for seg in out)
    return out
