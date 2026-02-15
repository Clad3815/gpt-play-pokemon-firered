from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

# =============================================================================
# Symbol lookup (pokefirered.sym)
# =============================================================================

_SYM_TABLE: Dict[str, List[Tuple[int, int, str]]] = {}
_SYM_LOADED = False
_DEFAULT_SYM_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "pokefirered.sym"))
_SYM_PATH = os.path.normpath(os.environ.get("FIRERED_SYM_PATH", _DEFAULT_SYM_PATH))
_STRICT_SYMBOLS = os.environ.get("FIRERED_BRIDGE_STRICT_SYMBOLS", "").strip() in ("1", "true", "True")

def _load_sym_table() -> None:
    global _SYM_LOADED, _SYM_TABLE
    if _SYM_LOADED:
        return
    _SYM_LOADED = True
    if not os.path.exists(_SYM_PATH):
        _SYM_TABLE = {}
        return
    table: Dict[str, List[Tuple[int, int, str]]] = {}
    try:
        with open(_SYM_PATH, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                addr_s, sym_type, size_s, name = parts[0], parts[1], parts[2], parts[3]
                try:
                    addr = int(addr_s, 16)
                    size = int(size_s, 16)
                except ValueError:
                    continue
                table.setdefault(name, []).append((addr, size, sym_type))
    except OSError:
        table = {}
    _SYM_TABLE = table


def _resolve_entries(name: str) -> List[Tuple[int, int, str]]:
    return list(_SYM_TABLE.get(name, []))


def sym_addr(
    name: str,
    *,
    size: Optional[int] = None,
    near: Optional[str] = None,
    fallback: Optional[int] = None,
) -> int:
    _load_sym_table()
    entries = _resolve_entries(name)
    if not entries:
        if fallback is not None:
            return fallback
        if _STRICT_SYMBOLS:
            raise KeyError(f"Symbol not found in sym file: {name}")
        return 0
    if size is not None:
        sized = [entry for entry in entries if entry[1] == size]
        if sized:
            entries = sized
    if near is not None and len(entries) > 1:
        near_entries = _resolve_entries(near)
        if near_entries:
            near_addr = near_entries[0][0]
            entries = sorted(entries, key=lambda entry: (abs(entry[0] - near_addr), entry[0]))
            return entries[0][0]
    entries = sorted(entries, key=lambda entry: entry[0])
    return entries[0][0]


def sym_addrs(name: str, *, size: Optional[int] = None) -> List[int]:
    """
    Return all addresses for a symbol name from pokefirered.sym.

    Some static functions can appear multiple times in the sym file (same name, different TU).
    For UI-state detection we treat any matching address as valid.
    """
    _load_sym_table()
    entries = _resolve_entries(name)
    if size is not None:
        entries = [entry for entry in entries if entry[1] == size]
    addrs = sorted({addr for addr, _sz, _typ in entries})
    return addrs


def sym_entry(
    name: str,
    *,
    size: Optional[int] = None,
    near: Optional[str] = None,
    fallback_addr: Optional[int] = None,
    fallback_size: int = 0,
    fallback_type: str = "",
) -> Tuple[int, int, str]:
    """
    Return the (addr, size, type) triple for the best match of a symbol name.

    This is useful when a ROM table size should come from the sym file rather than
    being hardcoded.
    """
    _load_sym_table()
    entries = _resolve_entries(name)
    if not entries:
        if fallback_addr is not None:
            return int(fallback_addr), int(fallback_size), str(fallback_type)
        if _STRICT_SYMBOLS:
            raise KeyError(f"Symbol not found in sym file: {name}")
        return 0, 0, ""
    if size is not None:
        sized = [entry for entry in entries if entry[1] == size]
        if sized:
            entries = sized
    if near is not None and len(entries) > 1:
        near_entries = _resolve_entries(near)
        if near_entries:
            near_addr = near_entries[0][0]
            entries = sorted(entries, key=lambda entry: (abs(entry[0] - near_addr), entry[0]))
            return entries[0]
    entries = sorted(entries, key=lambda entry: entry[0])
    return entries[0]


def sym_addrs_by_prefix(prefix: str) -> List[int]:
    """
    Return all addresses for symbols whose name starts with `prefix`.

    Used for UI detection where related functions (e.g. Task_* state machines) span many
    symbols and we want to treat any of them as equivalent evidence.
    """
    _load_sym_table()
    addrs: set[int] = set()
    for name, entries in _SYM_TABLE.items():
        if not name.startswith(prefix):
            continue
        for addr, _sz, _typ in entries:
            addrs.add(int(addr))
    return sorted(addrs)
