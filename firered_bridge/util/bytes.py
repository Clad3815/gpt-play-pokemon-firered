from __future__ import annotations

def _u8_from(raw: bytes, offset: int) -> int:
    if offset < 0 or offset >= len(raw):
        return 0
    return raw[offset]


def _u16le_from(raw: bytes, offset: int) -> int:
    if offset < 0 or (offset + 1) >= len(raw):
        return 0
    return raw[offset] | (raw[offset + 1] << 8)


def _u32le_from(raw: bytes, offset: int) -> int:
    if offset < 0 or (offset + 3) >= len(raw):
        return 0
    return raw[offset] | (raw[offset + 1] << 8) | (raw[offset + 2] << 16) | (raw[offset + 3] << 24)




def _s8_from_u8(val: int) -> int:
    return val - 256 if val > 127 else val


def _s16_from_u16(val: int) -> int:
    return val - 65536 if val > 32767 else val


