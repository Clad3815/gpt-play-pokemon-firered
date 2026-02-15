from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..constants.addresses import (
    CB2_FLY_MAP_ADDR,
    CB2_OPEN_FLY_MAP_ADDR,
    GMAIN_ADDR,
    GMAIN_CALLBACK2_OFFSET,
    GSAVEBLOCK1_PTR_ADDR,
    SB1_FLAGS_OFFSET,
    SMAPCURSOR_PTR_ADDR,
    SFLYMAP_PTR_ADDR,
    SYSTEM_FLAGS_START,
)
from ..memory import mgba
from ..text.text_printer import get_textprinter_text_for_window

# =============================================================================
# Fly map (CB2_OpenFlyMap / CB2_FlyMap) detection and text reconstruction
# =============================================================================

# struct MapCursor from pokefirered/src/region_map.c
_MAPCURSOR_X_OFFSET = 0x00  # s16
_MAPCURSOR_Y_OFFSET = 0x02  # s16
_MAPCURSOR_SELECTED_MAPSEC_OFFSET = 0x14  # u16
_MAPCURSOR_SELECTED_MAPSEC_TYPE_OFFSET = 0x16  # u16
_MAPCURSOR_SELECTED_DUNGEON_TYPE_OFFSET = 0x18  # u16
_MAPCURSOR_SNAPSHOT_LEN = 0x1A

# region_map.c map section types (FireRed)
_MAPSEC_TYPE_LABELS = {
    0: "NONE",
    1: "ROUTE",
    2: "VISITED",
    3: "NOT_VISITED",
    4: "UNKNOWN",
}

# Loaded from pokefirered/src/data/region_map/region_map_sections.json (repo data, not emulator RAM).
_MAPSECS: Optional[List[Dict[str, Any]]] = None
_MAPSEC_ID_BY_CONST: Dict[str, int] = {}
_MAPSEC_NONE_ID: Optional[int] = None  # enum appends MAPSEC_NONE after the JSON list
_MAPSEC_TO_WORLD_MAP_FLAG_CONST: Dict[str, str] = {}
_WORLD_MAP_FLAG_CONST_TO_ID: Dict[str, int] = {}


def _read_u32(addr: int) -> int:
    try:
        return int(mgba.mgba_read32(int(addr)))
    except Exception:
        return 0


def _read_range_bytes(addr: int, size: int) -> bytes:
    try:
        return mgba.mgba_read_range_bytes(int(addr), int(size))
    except Exception:
        return b""


def _u16le(raw: bytes, off: int) -> int:
    if off < 0 or (off + 1) >= len(raw):
        return 0
    return int(raw[off]) | (int(raw[off + 1]) << 8)


def _s16le(raw: bytes, off: int) -> int:
    val = _u16le(raw, off)
    return val - 0x10000 if (val & 0x8000) else val


def _load_map_sections() -> None:
    global _MAPSECS, _MAPSEC_ID_BY_CONST, _MAPSEC_NONE_ID
    if _MAPSECS is not None:
        return
    _MAPSECS = []
    _MAPSEC_ID_BY_CONST = {}
    _MAPSEC_NONE_ID = None

    try:
        repo_root = Path(__file__).resolve().parents[2]
        candidates = [
            repo_root / "pokefirered" / "src" / "data" / "region_map" / "region_map_sections.json",
        ]
        sections: Optional[List[Any]] = None
        for path in candidates:
            try:
                raw = path.read_text("utf-8")
                data = json.loads(raw)
                cand = data.get("map_sections")
                if isinstance(cand, list):
                    sections = cand
                    break
            except Exception:
                continue
        if not isinstance(sections, list):
            return
        for i, sec in enumerate(sections):
            if not isinstance(sec, dict):
                continue
            sec_id = sec.get("id")
            if isinstance(sec_id, str) and sec_id:
                _MAPSEC_ID_BY_CONST[sec_id] = int(i)
            _MAPSECS.append(sec)

        _MAPSEC_NONE_ID = len(_MAPSECS)
    except Exception:
        return


def _load_world_map_flag_ids() -> None:
    global _WORLD_MAP_FLAG_CONST_TO_ID
    if _WORLD_MAP_FLAG_CONST_TO_ID:
        return

    try:
        path = Path(__file__).resolve().parents[2] / "pokefirered" / "include" / "constants" / "flags.h"
        raw = path.read_text("utf-8")
    except Exception:
        return

    table: Dict[str, int] = {}
    # Example: #define FLAG_WORLD_MAP_PALLET_TOWN (SYS_FLAGS + 0x90)
    for m in re.finditer(
        r"#define\s+(FLAG_WORLD_MAP_[A-Z0-9_]+)\s+\(\s*SYS_FLAGS\s*\+\s*(0x[0-9A-Fa-f]+|\d+)\s*\)",
        raw,
    ):
        try:
            flag_name = str(m.group(1))
            offset = int(str(m.group(2)), 0)
            table[flag_name] = int(SYSTEM_FLAGS_START) + int(offset)
        except Exception:
            continue
    if table:
        _WORLD_MAP_FLAG_CONST_TO_ID = table


def _load_mapsec_to_world_map_flag_map() -> None:
    global _MAPSEC_TO_WORLD_MAP_FLAG_CONST
    if _MAPSEC_TO_WORLD_MAP_FLAG_CONST:
        return

    try:
        path = Path(__file__).resolve().parents[2] / "pokefirered" / "src" / "region_map.c"
        raw = path.read_text("utf-8")
    except Exception:
        return

    # Skip the forward declaration and target the actual function definition.
    start = raw.find("static u8 GetMapsecType(u8 mapsec)")
    if start < 0:
        return
    end = raw.find("static u8 GetDungeonMapsecType(", start)
    if end < 0:
        return

    body = raw[start:end]
    table: Dict[str, str] = {}
    case_matches = list(re.finditer(r"case\s+(MAPSEC_[A-Z0-9_]+)\s*:", body))
    for i, case_m in enumerate(case_matches):
        mapsec_const = str(case_m.group(1))
        block_start = int(case_m.end())
        block_end = int(case_matches[i + 1].start()) if (i + 1) < len(case_matches) else len(body)
        block = body[block_start:block_end]
        flag_m = re.search(r"FlagGet\((FLAG_WORLD_MAP_[A-Z0-9_]+)\)", block)
        if flag_m is None:
            continue
        table[mapsec_const] = str(flag_m.group(1))
    if table:
        _MAPSEC_TO_WORLD_MAP_FLAG_CONST = table


def _mapsec_meta(mapsec_id: int) -> Optional[Dict[str, Any]]:
    _load_map_sections()
    if _MAPSECS is None:
        return None
    if mapsec_id < 0 or mapsec_id >= len(_MAPSECS):
        return None
    meta = _MAPSECS[mapsec_id]
    return meta if isinstance(meta, dict) else None


def _read_flags_bulk(sb1_ptr: int, flag_ids: List[int]) -> Optional[Dict[int, bool]]:
    """
    Read multiple flag bits from saveblock1.flags with one RAM read.
    """
    if sb1_ptr == 0:
        return None
    if not flag_ids:
        return {}

    try:
        base = int(sb1_ptr) + int(SB1_FLAGS_OFFSET)
        byte_offsets = [int(fid) // 8 for fid in flag_ids if int(fid) >= 0]
        if not byte_offsets:
            return {}
        lo = min(byte_offsets)
        hi = max(byte_offsets)
        size = (hi - lo) + 1
        raw = _read_range_bytes(base + lo, size)
        if len(raw) < size:
            return None

        out: Dict[int, bool] = {}
        for fid in flag_ids:
            fid_i = int(fid)
            if fid_i < 0:
                continue
            b_off = (fid_i // 8) - lo
            bit = fid_i % 8
            if b_off < 0 or b_off >= len(raw):
                continue
            out[fid_i] = ((int(raw[b_off]) >> bit) & 1) == 1
        return out
    except Exception:
        return None


def _build_fly_destinations(
    *,
    sb1_ptr: int,
    current_mapsec_id: int,
    current_subtitle: Optional[str],
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """
    Build the list of Fly destinations (available + locked) with cursor positions.
    """
    _load_map_sections()
    _load_world_map_flag_ids()
    _load_mapsec_to_world_map_flag_map()

    if not _MAPSEC_TO_WORLD_MAP_FLAG_CONST or not _WORLD_MAP_FLAG_CONST_TO_ID:
        return None

    specs: List[Tuple[int, int, str]] = []
    seen: set[Tuple[int, int]] = set()
    for mapsec_const, flag_const in _MAPSEC_TO_WORLD_MAP_FLAG_CONST.items():
        mapsec_id = _MAPSEC_ID_BY_CONST.get(str(mapsec_const))
        flag_id = _WORLD_MAP_FLAG_CONST_TO_ID.get(str(flag_const))
        if not isinstance(mapsec_id, int) or not isinstance(flag_id, int):
            continue
        key = (int(mapsec_id), int(flag_id))
        if key in seen:
            continue
        seen.add(key)
        specs.append((int(mapsec_id), int(flag_id), "not visited"))

    if not specs:
        return None

    # Resolve SB1 pointer if not provided.
    if sb1_ptr == 0:
        sb1_ptr = _read_u32(GSAVEBLOCK1_PTR_ADDR)

    flag_map = _read_flags_bulk(int(sb1_ptr), [flag for _mid, flag, _reason in specs]) if sb1_ptr else None
    if flag_map is None:
        return None

    entries: List[Dict[str, Any]] = []
    for mapsec_id, flag_id, lock_reason in specs:
        meta = _mapsec_meta(int(mapsec_id))
        if meta is None:
            continue

        name = meta.get("name")
        if not isinstance(name, str) or not name:
            continue

        x = int(meta.get("x", 0) or 0)
        y = int(meta.get("y", 0) or 0)
        cursor_x = x
        cursor_y = y

        unlocked = bool(flag_map.get(int(flag_id), False))
        status = "available" if unlocked else "locked"

        display_name = name
        if int(mapsec_id) == int(current_mapsec_id) and current_subtitle:
            display_name = f"{name} — {current_subtitle}"

        entries.append(
            {
                "id": meta.get("id"),
                "mapSecId": int(mapsec_id),
                "name": name,
                "displayName": display_name,
                "cursor": {"x": int(cursor_x), "y": int(cursor_y)},
                "status": status,
                "canFly": bool(unlocked),
                "lockReason": None if unlocked else lock_reason,
            }
        )

    # Sort for readability: available first, then by map position.
    def _sort_key(e: Dict[str, Any]) -> Tuple[int, int, int, str]:
        locked = 0 if bool(e.get("canFly")) else 1
        cur = e.get("cursor") if isinstance(e.get("cursor"), dict) else {}
        x = int(cur.get("x", 0) or 0)
        y = int(cur.get("y", 0) or 0)
        name = str(e.get("name") or "")
        return (locked, y, x, name)

    entries.sort(key=_sort_key)
    available = [e for e in entries if bool(e.get("canFly"))]
    locked = [e for e in entries if not bool(e.get("canFly"))]
    return {"available": available, "locked": locked}


def _iter_destination_entries(destinations: Optional[Dict[str, List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    if not isinstance(destinations, dict):
        return []
    out: List[Dict[str, Any]] = []
    for key in ("available", "locked"):
        entries = destinations.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                out.append(entry)
    return out


def _cursor_hits_destination(dest: Dict[str, Any], cursor_x: int, cursor_y: int) -> bool:
    cur = dest.get("cursor")
    if isinstance(cur, dict):
        x = int(cur.get("x", 0) or 0)
        y = int(cur.get("y", 0) or 0)
        if x == int(cursor_x) and y == int(cursor_y):
            return True

    # Backward-compatible support if an older payload still has a box field.
    box = dest.get("box")
    if not isinstance(box, dict):
        return False
    x = int(box.get("x", 0) or 0)
    y = int(box.get("y", 0) or 0)
    w = max(1, int(box.get("width", 1) or 1))
    h = max(1, int(box.get("height", 1) or 1))
    return x <= int(cursor_x) < (x + w) and y <= int(cursor_y) < (y + h)


def _find_destination_at_cursor(
    destinations: Optional[Dict[str, List[Dict[str, Any]]]],
    cursor_x: int,
    cursor_y: int,
) -> Optional[Dict[str, Any]]:
    for entry in _iter_destination_entries(destinations):
        if _cursor_hits_destination(entry, int(cursor_x), int(cursor_y)):
            return entry
    return None


def get_fly_map_state(
    *,
    callback2: Optional[int] = None,
    sb1_ptr: Optional[int] = None,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect and extract the Fly destination selection screen ("FLY to where?").

    This UI is driven by the main callback (CB2_FlyMap) and does not use the normal
    dialog window0 TextPrinter.
    """
    try:
        if callback2 is None:
            callback2 = int(mgba.mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET))

        cb2 = int(callback2) & 0xFFFFFFFE
        cb2_candidates = {
            int(addr) & 0xFFFFFFFE
            for addr in (CB2_FLY_MAP_ADDR, CB2_OPEN_FLY_MAP_ADDR)
            if int(addr) != 0
        }
        if not cb2_candidates or cb2 not in cb2_candidates:
            return None

        # Prompt in window 2 (may be printed instantly, so include inactive).
        prompt = get_textprinter_text_for_window(
            2,
            text_printers_raw=text_printers_raw,
            gstringvar4_raw=gstringvar4_raw,
            gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
            include_inactive=True,
        )
        if not prompt:
            prompt = "FLY to where?"

        fly_map_ptr = _read_u32(SFLYMAP_PTR_ADDR)
        if fly_map_ptr == 0:
            # CB2_RegionMap is shared by normal region map and fly map.
            # Without sFlyMap allocated, this is not the fly map flow.
            if cb2 != (int(CB2_OPEN_FLY_MAP_ADDR) & 0xFFFFFFFE):
                return None
            visible = f"{prompt}\n\nSelection: —\n(A: disabled)  B: Cancel"
            return {
                "type": "flyMap",
                "isReady": False,
                "prompt": prompt,
                "cursor": None,
                "selection": None,
                "visibleText": visible,
            }

        map_cursor_ptr = _read_u32(SMAPCURSOR_PTR_ADDR)
        if map_cursor_ptr == 0:
            visible = f"{prompt}\n\nSelection: —\n(A: disabled)  B: Cancel"
            return {
                "type": "flyMap",
                "isReady": False,
                "prompt": prompt,
                "cursor": None,
                "selection": None,
                "visibleText": visible,
            }

        map_cursor = _read_range_bytes(map_cursor_ptr, _MAPCURSOR_SNAPSHOT_LEN)
        if len(map_cursor) < _MAPCURSOR_SNAPSHOT_LEN:
            visible = f"{prompt}\n\nSelection: —\n(A: disabled)  B: Cancel"
            return {
                "type": "flyMap",
                "isReady": False,
                "prompt": prompt,
                "cursor": None,
                "selection": None,
                "visibleText": visible,
            }

        cursor_x = int(_s16le(map_cursor, _MAPCURSOR_X_OFFSET))
        cursor_y = int(_s16le(map_cursor, _MAPCURSOR_Y_OFFSET))
        mapsec_id = int(_u16le(map_cursor, _MAPCURSOR_SELECTED_MAPSEC_OFFSET))
        mapsec_type = int(_u16le(map_cursor, _MAPCURSOR_SELECTED_MAPSEC_TYPE_OFFSET))
        dungeon_type = int(_u16le(map_cursor, _MAPCURSOR_SELECTED_DUNGEON_TYPE_OFFSET))

        _load_map_sections()
        mapsec_type_label = _MAPSEC_TYPE_LABELS.get(mapsec_type, f"UNKNOWN_{mapsec_type}")
        # FireRed symbol exports do not expose the optional "tall mapsec name" helpers.
        subtitle: Optional[str] = None
        pos_within = 0  # FireRed MapCursor does not expose a "position within mapsec" field.
        zoomed = False  # FireRed fly map does not use the FireRed zoom cursor fields.

        sel_lines = []

        destinations = _build_fly_destinations(
            sb1_ptr=int(sb1_ptr or 0),
            current_mapsec_id=mapsec_id,
            current_subtitle=subtitle,
        )

        selected_destination = _find_destination_at_cursor(destinations, cursor_x, cursor_y)
        if selected_destination is None:
            for entry in _iter_destination_entries(destinations):
                if int(entry.get("mapSecId", -1) or -1) == mapsec_id:
                    selected_destination = entry
                    break

        selection_name: Optional[str] = None
        selection_mapsec_id = mapsec_id
        if selected_destination is not None:
            selection_name = str(selected_destination.get("displayName") or selected_destination.get("name") or "").strip() or None
            selection_mapsec_id = int(selected_destination.get("mapSecId", mapsec_id) or mapsec_id)
        elif mapsec_type in (2, 3, 4):
            if _MAPSEC_NONE_ID is not None and mapsec_id == int(_MAPSEC_NONE_ID):
                selection_name = None
            else:
                meta = _mapsec_meta(mapsec_id)
                meta_name = meta.get("name") if isinstance(meta, dict) else None
                if isinstance(meta_name, str) and meta_name:
                    selection_name = meta_name

        # FireRed accepts A when selected map section type is VISITED or UNKNOWN.
        can_fly = bool(mapsec_type in (2, 4))
        if selected_destination is not None:
            can_fly = bool(selected_destination.get("canFly"))

        if selection_name:
            sel_lines.append(f"Selection: {selection_name}")
            if subtitle:
                sel_lines.append(f"Subtitle: {subtitle}")
        else:
            sel_lines.append("Selection: —")

        cursor_line = f"Cursor: (x={cursor_x}, y={cursor_y})"
        a_action = "Fly" if can_fly and selection_name else "disabled"

        lines = [prompt, "", *sel_lines, cursor_line, "", f"(A: {a_action})  B: Cancel"]
        if destinations is not None:
            avail = destinations.get("available", [])
            locked = destinations.get("locked", [])

            lines.append("")
            lines.append(f"Available destinations ({len(avail)}):")
            for d in avail:
                cur = d.get("cursor") if isinstance(d.get("cursor"), dict) else {}
                x = int(cur.get("x", 0) or 0)
                y = int(cur.get("y", 0) or 0)

                mark = "►" if _cursor_hits_destination(d, cursor_x, cursor_y) else " "
                name_disp = str(d.get("displayName") or d.get("name") or "")
                lines.append(f"  {mark} {name_disp} @ ({x},{y})")

            lines.append("")
            lines.append(f"Locked destinations ({len(locked)}):")
            for d in locked:
                cur = d.get("cursor") if isinstance(d.get("cursor"), dict) else {}
                x = int(cur.get("x", 0) or 0)
                y = int(cur.get("y", 0) or 0)
                name_disp = str(d.get("name") or "")
                reason = d.get("lockReason")
                reason_txt = f" [{reason}]" if isinstance(reason, str) and reason else ""
                mark = "►" if _cursor_hits_destination(d, cursor_x, cursor_y) else "-"
                lines.append(f"  {mark} {name_disp} @ ({x},{y}){reason_txt}")

            lines.append("")
            lines.append("Controls: D-Pad move (Change x,y position)")

        visible = "\n".join(lines)

        return {
            "type": "flyMap",
            "isReady": True,
            "prompt": prompt,
            "cursor": {
                "zoomed": zoomed,
                "x": cursor_x,
                "y": cursor_y,
                "raw": {
                    "mapCursorX": cursor_x,
                    "mapCursorY": cursor_y,
                    "selectedMapSec": mapsec_id,
                    "selectedMapSecType": mapsec_type,
                    "selectedDungeonType": dungeon_type,
                },
            },
            "selection": {
                "mapSecId": selection_mapsec_id,
                "mapSecType": mapsec_type_label,
                "posWithinMapSec": pos_within,
                "name": selection_name,
                "subtitle": subtitle,
                "canFly": bool(can_fly and bool(selection_name)),
            },
            "destinations": destinations,
            "visibleText": visible,
        }
    except Exception:
        return None
