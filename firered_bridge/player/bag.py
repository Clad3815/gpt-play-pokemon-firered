from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..constants.addresses import *  # noqa: F403
from ..game_data import get_item_name
from ..memory import mgba
from ..util.bytes import _u16le_from, _u32le_from, _u8_from
from .snapshot import get_security_key

# Sac / inventaire (quantités XOR avec security key)
# =============================================================================

# Debug flag - set BAG_DEBUG=1 env var to enable verbose bag parsing logs
BAG_DEBUG = False
_BAG_CONTENTS_CACHE_KEY: Optional[Tuple[int, Tuple[Tuple[int, int], ...], Tuple[bytes, ...]]] = None
_BAG_CONTENTS_CACHE_RESULT: Optional[Dict[str, Any]] = None


def _bag_debug(msg: str) -> None:
    """Print debug message if BAG_DEBUG is enabled."""
    if BAG_DEBUG:
        print(f"[BAG_DEBUG] {msg}")


POCKETS = {
    0: "Items",
    1: "Key Items",
    2: "Pokeballs",
    3: "TMs & HMs",
    4: "Berries",
}
POCKET_ENTRY_SIZE = 8  # struct BagPocket: 4 bytes ptr + 1 byte capacity + padding
ITEM_ENTRY_SIZE = 4  # 2 bytes itemId + 2 bytes encrypted quantity
POCKET_COUNT = 5


def _get_pocket_info(idx: int) -> Tuple[int, int]:
    addr = BAG_MAIN_ADDR + (idx * POCKET_ENTRY_SIZE)
    raw = mgba.mgba_read_range_bytes(addr, POCKET_ENTRY_SIZE)
    pointer = _u32le_from(raw, 0)
    capacity = _u8_from(raw, 4) & 0xFF
    return pointer, capacity


def _get_pocket_infos() -> List[Tuple[int, int]]:
    _bag_debug(f"Reading pocket headers from BAG_MAIN_ADDR=0x{BAG_MAIN_ADDR:08X}, size={POCKET_COUNT * POCKET_ENTRY_SIZE}")
    raw = mgba.mgba_read_range_bytes(BAG_MAIN_ADDR, POCKET_COUNT * POCKET_ENTRY_SIZE)
    _bag_debug(f"Raw pocket header bytes ({len(raw)}): {raw[:40].hex() if raw else 'EMPTY'}")
    if len(raw) < (POCKET_COUNT * POCKET_ENTRY_SIZE):
        raise RuntimeError("Bag pocket header read failed")
    infos = []
    for idx in range(POCKET_COUNT):
        off = idx * POCKET_ENTRY_SIZE
        pointer = _u32le_from(raw, off)
        capacity = _u8_from(raw, off + 4) & 0xFF
        _bag_debug(f"  Pocket {idx} ({POCKETS.get(idx, '?')}): ptr=0x{pointer:08X}, capacity={capacity}")
        infos.append((pointer, capacity))
    return infos


def _read_pocket_items(idx: int, sec_key: int) -> List[Dict[str, Any]]:
    ptr, cap = _get_pocket_info(idx)
    if ptr == 0 or cap == 0:
        return []
    total_bytes = cap * ITEM_ENTRY_SIZE
    raw = mgba.mgba_read_range_bytes(ptr, total_bytes)
    return _read_pocket_items_from_raw(raw, cap, sec_key)


def _read_pocket_items_from_raw(raw: Sequence[int], cap: int, sec_key: int) -> List[Dict[str, Any]]:
    _bag_debug(f"  Parsing pocket: raw_len={len(raw) if raw else 0}, cap={cap}, sec_key=0x{sec_key:08X}")
    if not raw or cap == 0:
        _bag_debug("    -> Empty (no raw data or cap=0)")
        return []
    key16 = sec_key & 0xFFFF
    _bag_debug(f"    key16=0x{key16:04X}")
    # Show first 32 bytes of raw for debugging
    raw_preview = bytes(raw[:min(32, len(raw))]).hex() if raw else "EMPTY"
    _bag_debug(f"    raw preview (first 32 bytes): {raw_preview}")
    items = []
    consecutive_empty = 0
    for i in range(cap):
        off = i * ITEM_ENTRY_SIZE
        if off + 3 >= len(raw):
            _bag_debug(f"    slot {i}: BREAK - off+3={off+3} >= len(raw)={len(raw)}")
            break
        item_id = (raw[off + 1] << 8) | raw[off + 0]
        enc_qty = (raw[off + 3] << 8) | raw[off + 2]
        if item_id == 0:
            consecutive_empty += 1
            # Stop only if we've seen 3+ consecutive empty slots (real end of list)
            if consecutive_empty >= 3:
                _bag_debug(f"    slot {i}: BREAK - {consecutive_empty} consecutive empty slots (end of items)")
                break
            _bag_debug(f"    slot {i}: SKIP - item_id=0 (empty slot, consecutive={consecutive_empty})")
            continue
        # Reset consecutive empty counter when we find a valid item
        consecutive_empty = 0
        qty = enc_qty ^ key16
        item_name = get_item_name(item_id) or f"Unknown Item ({item_id})"
        _bag_debug(f"    slot {i}: item_id={item_id}, enc_qty=0x{enc_qty:04X}, qty={qty}, name={item_name}")
        items.append({"name": item_name, "quantity": qty, "id": item_id})
    _bag_debug(f"    -> Parsed {len(items)} items")
    return items


def _get_bag_contents_slow(sec_key: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for idx, pname in POCKETS.items():
        try:
            out[pname] = _read_pocket_items(idx, sec_key)
        except Exception:
            out[pname] = []
    return out


def _get_bag_contents_fast(sec_key: int) -> Dict[str, Any]:
    _bag_debug(f"=== _get_bag_contents_fast START (sec_key=0x{sec_key:08X}) ===")
    infos = _get_pocket_infos()
    out: Dict[str, Any] = {}
    ranges = []
    order: List[Tuple[str, int]] = []
    for idx, pname in POCKETS.items():
        ptr, cap = infos[idx]
        if ptr == 0 or cap == 0:
            _bag_debug(f"Pocket {pname}: SKIP (ptr=0x{ptr:08X}, cap={cap})")
            out[pname] = []
            continue
        byte_size = cap * ITEM_ENTRY_SIZE
        _bag_debug(f"Pocket {pname}: will read {byte_size} bytes from 0x{ptr:08X}")
        ranges.append((ptr, byte_size))
        order.append((pname, cap))
    if not ranges:
        _bag_debug("No valid pocket ranges to read!")
        return out
    _bag_debug(f"Reading {len(ranges)} pocket data ranges...")
    chunks = mgba.mgba_read_ranges_bytes(ranges)
    _bag_debug(f"Got {len(chunks)} chunks back")

    global _BAG_CONTENTS_CACHE_KEY, _BAG_CONTENTS_CACHE_RESULT
    chunk_bytes: Tuple[bytes, ...] = tuple(bytes(c) if c is not None else b"" for c in chunks)
    pocket_sig: Tuple[Tuple[int, int], ...] = tuple((int(ptr), int(cap)) for ptr, cap in infos)
    cache_key = (int(sec_key) & 0xFFFF, pocket_sig, chunk_bytes)
    if _BAG_CONTENTS_CACHE_KEY == cache_key and _BAG_CONTENTS_CACHE_RESULT is not None:
        _bag_debug("Bag parse cache hit")
        return _BAG_CONTENTS_CACHE_RESULT

    for i, ((pname, cap), chunk) in enumerate(zip(order, chunks)):
        chunk_len = len(chunk) if chunk else 0
        _bag_debug(f"Processing pocket {pname}: chunk_len={chunk_len}, cap={cap}")
        out[pname] = _read_pocket_items_from_raw(chunk, cap, sec_key)
    _BAG_CONTENTS_CACHE_KEY = cache_key
    _BAG_CONTENTS_CACHE_RESULT = out
    _bag_debug(f"=== _get_bag_contents_fast END ===")
    return out


def get_bag_contents(sec_key: Optional[int] = None) -> Dict[str, Any]:
    if sec_key is None:
        sec_key = get_security_key()
        _bag_debug(f"get_bag_contents: fetched sec_key=0x{sec_key:08X}")
    else:
        _bag_debug(f"get_bag_contents: using provided sec_key=0x{sec_key:08X}")
    try:
        result = _get_bag_contents_fast(sec_key)
        total_items = sum(len(v) for v in result.values())
        _bag_debug(f"get_bag_contents: FAST path success, total items={total_items}")
        return result
    except Exception as e:
        _bag_debug(f"get_bag_contents: FAST path failed ({e}), falling back to SLOW")
        return _get_bag_contents_slow(sec_key)

# =============================================================================


def _count_item_quantity_in_pocket_from_raw(raw: Sequence[int], cap: int, sec_key16: int, item_id: int) -> int:
    if not raw or cap <= 0:
        return 0
    total = 0
    consecutive_empty = 0
    for i in range(cap):
        off = i * ITEM_ENTRY_SIZE
        if off + 3 >= len(raw):
            break
        cur_item_id = int(_u16le_from(raw, off))
        if cur_item_id == 0:
            consecutive_empty += 1
            # Stop only if we've seen 3+ consecutive empty slots (real end of list)
            if consecutive_empty >= 3:
                break
            continue
        consecutive_empty = 0
        if cur_item_id != item_id:
            continue
        enc_qty = int(_u16le_from(raw, off + 2))
        total += int(enc_qty ^ int(sec_key16))
    return int(total)


def count_total_item_quantity_in_bag(item_id: int, sec_key: Optional[int] = None) -> int:
    """
    Count total quantity of a specific item across all Bag pockets.

    Uses the same encryption scheme as the game (quantity XOR with security key, low 16 bits).
    """
    try:
        item_id_int = int(item_id)
    except Exception:
        return 0
    if item_id_int <= 0:
        return 0

    if sec_key is None:
        sec_key = get_security_key()
    key16 = int(sec_key) & 0xFFFF

    try:
        infos = _get_pocket_infos()
    except Exception:
        infos = []
        for idx in range(POCKET_COUNT):
            try:
                infos.append(_get_pocket_info(idx))
            except Exception:
                infos.append((0, 0))

    ranges: List[Tuple[int, int]] = []
    caps: List[int] = []
    for ptr, cap in infos:
        ptr_i = int(ptr)
        cap_i = int(cap)
        if ptr_i == 0 or cap_i <= 0:
            continue
        ranges.append((ptr_i, cap_i * ITEM_ENTRY_SIZE))
        caps.append(cap_i)

    if not ranges:
        return 0

    total = 0
    try:
        chunks = mgba.mgba_read_ranges_bytes(ranges)
        for cap_i, chunk in zip(caps, chunks):
            total += _count_item_quantity_in_pocket_from_raw(chunk, cap_i, key16, item_id_int)
        return int(total)
    except Exception:
        for (ptr_i, _len), cap_i in zip(ranges, caps):
            try:
                raw = mgba.mgba_read_range_bytes(ptr_i, cap_i * ITEM_ENTRY_SIZE)
            except Exception:
                continue
            total += _count_item_quantity_in_pocket_from_raw(raw, cap_i, key16, item_id_int)
        return int(total)


# =============================================================================
