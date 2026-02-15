from __future__ import annotations

from typing import Sequence

from ..memory import mgba

TEXT_TERMINATOR = 0xFF

GBA_CHARMAP = {
    0x00: " ",
    0xAB: "!",
    0xAC: "?",
    0xAD: ".",
    0xAE: "-",
    0xAF: "·",
    0xB0: "…",
    0xB1: '"',
    0xB2: '"',
    0xB3: "'",
    0xB4: "'",
    0xB5: "♂",
    0xB6: "♀",
    0xB8: ",",
    0xB9: "×",
    0xBA: "/",
    # Numbers
    0xA1: "0",
    0xA2: "1",
    0xA3: "2",
    0xA4: "3",
    0xA5: "4",
    0xA6: "5",
    0xA7: "6",
    0xA8: "7",
    0xA9: "8",
    0xAA: "9",
    # Uppercase
    0xBB: "A",
    0xBC: "B",
    0xBD: "C",
    0xBE: "D",
    0xBF: "E",
    0xC0: "F",
    0xC1: "G",
    0xC2: "H",
    0xC3: "I",
    0xC4: "J",
    0xC5: "K",
    0xC6: "L",
    0xC7: "M",
    0xC8: "N",
    0xC9: "O",
    0xCA: "P",
    0xCB: "Q",
    0xCC: "R",
    0xCD: "S",
    0xCE: "T",
    0xCF: "U",
    0xD0: "V",
    0xD1: "W",
    0xD2: "X",
    0xD3: "Y",
    0xD4: "Z",
    # Lowercase
    0xD5: "a",
    0xD6: "b",
    0xD7: "c",
    0xD8: "d",
    0xD9: "e",
    0xDA: "f",
    0xDB: "g",
    0xDC: "h",
    0xDD: "i",
    0xDE: "j",
    0xDF: "k",
    0xE0: "l",
    0xE1: "m",
    0xE2: "n",
    0xE3: "o",
    0xE4: "p",
    0xE5: "q",
    0xE6: "r",
    0xE7: "s",
    0xE8: "t",
    0xE9: "u",
    0xEA: "v",
    0xEB: "w",
    0xEC: "x",
    0xED: "y",
    0xEE: "z",
    0xEF: "►",
    0xF0: ":",
    0x1B: "é",
    # Control chars
    0xFE: "\n",  # New line
}

# Chars that pause/wait for input - text after these isn't visible yet
PROMPT_CHARS = {0xFA, 0xFB}  # CHAR_PROMPT_SCROLL, CHAR_PROMPT_CLEAR


def decode_gba_string(raw_bytes: Sequence[int], max_len: int = 500, stop_at_prompt: bool = False) -> str:
    """
    Decode GBA Pokemon text encoding to UTF-8 string.
    """
    result = []
    i = 0
    while i < len(raw_bytes) and i < max_len:
        byte = raw_bytes[i]
        if byte == TEXT_TERMINATOR:
            break

        if stop_at_prompt and byte in PROMPT_CHARS:
            break

        # Handle control codes (FC xx, FD xx) - skip command and param
        if byte == 0xFC or byte == 0xFD:
            i += 2
            continue

        char = GBA_CHARMAP.get(byte)
        if char is not None:
            result.append(char)
        i += 1

    return "".join(result).strip()


def read_string_buffer(addr: int, max_len: int = 256, visible_only: bool = False) -> str:
    """Read and decode a string buffer from memory."""
    try:
        raw = mgba.mgba_read_range_bytes(addr, max_len)
        return decode_gba_string(raw, max_len, stop_at_prompt=visible_only)
    except Exception:
        return ""


def _read_gba_cstring(ptr: int, max_len: int = 64) -> str:
    """Read a ROM/EWRAM/IWRAM encoded GBA string until 0xFF (or max_len)."""
    if ptr == 0:
        return ""
    try:
        raw = mgba.mgba_read_range(ptr, max_len)
        return decode_gba_string(raw, max_len)
    except Exception:
        return ""
