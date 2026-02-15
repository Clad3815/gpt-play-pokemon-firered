from __future__ import annotations

from dataclasses import dataclass
import bisect
from typing import Callable, Protocol, Sequence, Tuple


class MemoryReader(Protocol):
    def u8(self, addr: int) -> int: ...

    def u16(self, addr: int) -> int: ...

    def u32(self, addr: int) -> int: ...

    def read_bytes(self, addr: int, size: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class LiveMemoryReader:
    """Reader backed by callables (typically mGBA read functions)."""

    read8: Callable[[int], int]
    read16: Callable[[int], int]
    read32: Callable[[int], int]
    read_range_bytes: Callable[[int, int], bytes]

    def u8(self, addr: int) -> int:
        return int(self.read8(int(addr))) & 0xFF

    def u16(self, addr: int) -> int:
        return int(self.read16(int(addr))) & 0xFFFF

    def u32(self, addr: int) -> int:
        return int(self.read32(int(addr))) & 0xFFFFFFFF

    def read_bytes(self, addr: int, size: int) -> bytes:
        addr_i = int(addr)
        size_i = int(size)
        if size_i <= 0:
            return b""
        try:
            return bytes(self.read_range_bytes(addr_i, size_i))
        except Exception:
            # Test-friendly fallback: avoid needing a patched range reader.
            return bytes([self.u8(addr_i + i) for i in range(size_i)])


@dataclass(frozen=True, slots=True)
class SnapshotSegment:
    start: int
    data: bytes

    @property
    def end(self) -> int:
        return int(self.start) + len(self.data)


@dataclass(frozen=True, slots=True)
class SnapshotMemoryReader:
    """Reader backed by a set of captured (addr, bytes) segments."""

    segments: Tuple[SnapshotSegment, ...]
    _starts: Tuple[int, ...]

    @classmethod
    def from_ranges(
        cls, ranges: Sequence[Tuple[int, int]], chunks: Sequence[bytes]
    ) -> "SnapshotMemoryReader":
        segs = [
            SnapshotSegment(int(addr), bytes(chunk))
            for (addr, _len), chunk in zip(ranges, chunks)
            if int(addr) != 0 and isinstance(chunk, (bytes, bytearray))
        ]
        segs.sort(key=lambda s: s.start)
        starts = tuple(s.start for s in segs)
        return cls(segments=tuple(segs), _starts=starts)

    def _segment_for(self, addr: int, size: int) -> tuple[SnapshotSegment, int]:
        addr_i = int(addr)
        size_i = int(size)
        if size_i <= 0:
            raise KeyError("Empty read")

        i = bisect.bisect_right(self._starts, addr_i) - 1
        if i < 0 or i >= len(self.segments):
            raise KeyError(f"Address not in snapshot: 0x{addr_i:X}")
        seg = self.segments[i]

        off = addr_i - seg.start
        end = addr_i + size_i
        if off < 0 or end > seg.end:
            raise KeyError(f"Read spans missing snapshot bytes: 0x{addr_i:X}+{size_i}")
        return seg, off

    def u8(self, addr: int) -> int:
        seg, off = self._segment_for(addr, 1)
        return seg.data[off]

    def u16(self, addr: int) -> int:
        seg, off = self._segment_for(addr, 2)
        d = seg.data
        return d[off] | (d[off + 1] << 8)

    def u32(self, addr: int) -> int:
        seg, off = self._segment_for(addr, 4)
        d = seg.data
        return d[off] | (d[off + 1] << 8) | (d[off + 2] << 16) | (d[off + 3] << 24)

    def read_bytes(self, addr: int, size: int) -> bytes:
        seg, off = self._segment_for(addr, size)
        return bytes(seg.data[off : off + int(size)])

