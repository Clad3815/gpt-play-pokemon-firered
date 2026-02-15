from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .. import mgba_client as _mgba_client
from ..constants.addresses import (
    BG_EVENT_ELEVATION_OFFSET,
    BG_EVENT_KIND_HIDDEN_ITEM,
    BG_EVENT_KIND_OFFSET,
    BG_EVENT_KIND_SCRIPT,
    BG_EVENT_SCRIPT_POINTER_OFFSET,
    BG_EVENT_KIND_SECRET_BASE,
    BG_EVENT_SIZE,
    CURRENT_MAP_HEADER_ADDR,
    FACING_DIRECTION_MAP,
    MAP_CONNECTION_DIRECTION_OFFSET,
    MAP_CONNECTION_MAP_GROUP_OFFSET,
    MAP_CONNECTION_MAP_NUM_OFFSET,
    MAP_CONNECTION_OFFSET_OFFSET,
    MAP_CONNECTION_SIZE,
    MAP_CONNECTIONS_CONNECTION_POINTER_OFFSET,
    MAP_CONNECTIONS_COUNT_OFFSET,
    MAP_EVENTS_BG_EVENT_COUNT_OFFSET,
    MAP_EVENTS_BG_EVENTS_POINTER_OFFSET,
    MAP_EVENTS_OBJECT_EVENT_COUNT_OFFSET,
    MAP_EVENTS_OBJECT_EVENTS_POINTER_OFFSET,
    MAP_EVENTS_WARP_EVENT_COUNT_OFFSET,
    MAP_EVENTS_WARP_EVENTS_POINTER_OFFSET,
    MAP_HEADER_MAP_CONNECTIONS_OFFSET,
    MAP_HEADER_MAP_EVENTS_OFFSET,
    OBJECT_EVENT_ACTIVE_BIT,
    OBJECT_EVENT_COUNT,
    OBJECT_EVENT_ELEVATION_OFFSET,
    OBJECT_EVENT_FLAGS_OFFSET,
    OBJECT_EVENT_FACING_DIR_OFFSET,
    OBJECT_EVENT_GRAPHICS_ID_OFFSET,
    OBJECT_EVENT_LOCAL_ID_OFFSET,
    OBJECT_EVENT_MAP_GROUP_OFFSET,
    OBJECT_EVENT_MAP_NUM_OFFSET,
    OBJECT_EVENT_MOVEMENT_TYPE_OFFSET,
    OBJECT_EVENT_OFFSCREEN_BIT,
    OBJECT_EVENT_SIZE,
    OBJECT_EVENT_X_OFFSET,
    OBJECT_EVENT_Y_OFFSET,
    OBJECT_EVENT_TEMPLATES_COUNT,
    OBJECT_EVENT_TEMPLATE_ELEVATION_OFFSET,
    OBJECT_EVENT_TEMPLATE_FLAG_ID_OFFSET,
    OBJECT_EVENT_TEMPLATE_GRAPHICS_ID_OFFSET,
    OBJECT_EVENT_TEMPLATE_LOCAL_ID_OFFSET,
    OBJECT_EVENT_TEMPLATE_MOVEMENT_RANGE_OFFSET,
    OBJECT_EVENT_TEMPLATE_MOVEMENT_TYPE_OFFSET,
    OBJECT_EVENT_TEMPLATE_SIZE,
    OBJECT_EVENT_TEMPLATE_X_OFFSET,
    OBJECT_EVENT_TEMPLATE_Y_OFFSET,
    OBJECT_EVENT_WANDERING_TYPES,
    OBJECT_EVENTS_ADDR,
    MAP_OFFSET,
    SB1_FLAGS_OFFSET,
    SB1_OBJECT_EVENT_TEMPLATES_OFFSET,
    WARP_EVENT_ELEVATION_OFFSET,
    WARP_EVENT_MAP_GROUP_OFFSET,
    WARP_EVENT_MAP_NUM_OFFSET,
    WARP_EVENT_SIZE,
    WARP_EVENT_WARP_ID_OFFSET,
    WARP_EVENT_X_OFFSET,
    WARP_EVENT_Y_OFFSET,
    GSAVEBLOCK1_PTR_ADDR,
)
from ..game_data import get_event_object_name, get_map_name
from ..memory import mgba
from ..player.save import _flag_get_from_sb1
from ..util.bytes import _s16_from_u16, _u16le_from, _u32le_from, _u8_from

# Warps, NPCs, Connexions
# =============================================================================

@dataclass(frozen=True, slots=True)
class _ObjectTemplateCacheEntry:
    sb1_ptr: int
    candidates: Tuple[Tuple[Dict[str, Any], int], ...]  # (template_dict, flag_id)
    flags_start_byte: int
    flags_len: int


_BG_EVENTS_CACHE: Dict[int, List[Dict[str, Any]]] = {}
_WARP_EVENTS_CACHE: Dict[int, List[Dict[str, Any]]] = {}
_CONNECTIONS_CACHE: Dict[int, List[Dict[str, Any]]] = {}
_OBJECT_TEMPLATES_CACHE: Dict[Tuple[int, int], _ObjectTemplateCacheEntry] = {}
_MAP_EVENTS_BASE_BY_MAP: Dict[Tuple[int, int], int] = {}
_MAP_CONNECTIONS_PTR_BY_MAP: Dict[Tuple[int, int], int] = {}


def _get_map_events_base(*, map_group: Optional[int] = None, map_num: Optional[int] = None) -> int:
    if map_group is not None and map_num is not None:
        key = (int(map_group), int(map_num))
        cached = _MAP_EVENTS_BASE_BY_MAP.get(key)
        if cached is not None:
            return int(cached)
        ptr = int(mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_EVENTS_OFFSET))
        if ptr != 0:
            _MAP_EVENTS_BASE_BY_MAP[key] = int(ptr)
        return int(ptr)
    return int(mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_EVENTS_OFFSET))


def _get_map_connections_ptr(*, map_group: Optional[int] = None, map_num: Optional[int] = None) -> int:
    if map_group is not None and map_num is not None:
        key = (int(map_group), int(map_num))
        cached = _MAP_CONNECTIONS_PTR_BY_MAP.get(key)
        if cached is not None:
            return int(cached)
        ptr = int(mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_CONNECTIONS_OFFSET))
        if ptr != 0:
            _MAP_CONNECTIONS_PTR_BY_MAP[key] = int(ptr)
        return int(ptr)
    return int(mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_CONNECTIONS_OFFSET))


def get_current_map_bg_events(*, map_group: Optional[int] = None, map_num: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Lit les BG events (éléments interactifs visibles) de la map actuelle.
    Notes:
    - Les hidden items (BG_EVENT_HIDDEN_ITEM et valeurs 5/6 traitées comme hidden item par le moteur)
      ne sont PAS retournés (anti-cheat).
    """
    base_events = _get_map_events_base(map_group=map_group, map_num=map_num)
    if base_events == 0:
        return []

    cached = _BG_EVENTS_CACHE.get(int(base_events))
    if cached is not None:
        return cached

    bg_count_raw, bg_ptr_raw = mgba.mgba_read_ranges_bytes(
        [
            (base_events + MAP_EVENTS_BG_EVENT_COUNT_OFFSET, 1),
            (base_events + MAP_EVENTS_BG_EVENTS_POINTER_OFFSET, 4),
        ]
    )
    if not bg_count_raw or len(bg_count_raw) < 1:
        return []
    if not bg_ptr_raw or len(bg_ptr_raw) < 4:
        return []

    bg_count = _u8_from(bg_count_raw, 0)
    if bg_count == 0:
        _BG_EVENTS_CACHE[int(base_events)] = []
        return []

    bg_ptr = _u32le_from(bg_ptr_raw, 0)
    if bg_ptr == 0:
        return []

    total_bytes = bg_count * BG_EVENT_SIZE
    raw = mgba.mgba_read_range_bytes(bg_ptr, total_bytes)
    if len(raw) < total_bytes:
        return []
    out: List[Dict[str, Any]] = []

    for i in range(bg_count):
        off = i * BG_EVENT_SIZE
        x = _u16le_from(raw, off + 0)
        y = _u16le_from(raw, off + 2)
        elevation = _u8_from(raw, off + BG_EVENT_ELEVATION_OFFSET)
        kind = _u8_from(raw, off + BG_EVENT_KIND_OFFSET)
        script_addr = 0
        if kind == BG_EVENT_KIND_SCRIPT:
            script_addr = int(_u32le_from(raw, off + BG_EVENT_SCRIPT_POINTER_OFFSET))

        # Hidden items intentionally omitted.
        if kind in (5, 6, BG_EVENT_KIND_HIDDEN_ITEM):
            continue

        if kind == BG_EVENT_KIND_SECRET_BASE:
            event_type = "secret_base"
        else:
            event_type = "interactive"

        out.append(
            {
                "position": [x, y],
                "type": event_type,
                "elevation": elevation,
                "scriptAddr": script_addr if script_addr != 0 else None,
            }
        )

    _BG_EVENTS_CACHE[int(base_events)] = out
    return out


def get_current_map_warp_events(*, map_group: Optional[int] = None, map_num: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Read current map warp events from MapEvents.warps.

    These are used as a fallback overlay for minimap warp/door visualization when
    behavior-derived detection is missing or ambiguous.
    """
    base_events = _get_map_events_base(map_group=map_group, map_num=map_num)
    if base_events == 0:
        return []

    cached = _WARP_EVENTS_CACHE.get(int(base_events))
    if cached is not None:
        return cached

    warp_count_raw, warp_ptr_raw = mgba.mgba_read_ranges_bytes(
        [
            (base_events + MAP_EVENTS_WARP_EVENT_COUNT_OFFSET, 1),
            (base_events + MAP_EVENTS_WARP_EVENTS_POINTER_OFFSET, 4),
        ]
    )
    if not warp_count_raw or len(warp_count_raw) < 1:
        return []
    if not warp_ptr_raw or len(warp_ptr_raw) < 4:
        return []

    warp_count = int(_u8_from(warp_count_raw, 0))
    if warp_count <= 0:
        _WARP_EVENTS_CACHE[int(base_events)] = []
        return []
    if warp_count > 64:
        return []

    warp_ptr = int(_u32le_from(warp_ptr_raw, 0))
    if warp_ptr == 0:
        return []

    total_bytes = int(warp_count) * int(WARP_EVENT_SIZE)
    raw = mgba.mgba_read_range_bytes(warp_ptr, total_bytes)
    if len(raw) < total_bytes:
        return []

    out: List[Dict[str, Any]] = []
    for i in range(warp_count):
        off = i * WARP_EVENT_SIZE
        x = int(_u16le_from(raw, off + WARP_EVENT_X_OFFSET))
        y = int(_u16le_from(raw, off + WARP_EVENT_Y_OFFSET))
        elevation = int(_u8_from(raw, off + WARP_EVENT_ELEVATION_OFFSET))
        warp_id = int(_u8_from(raw, off + WARP_EVENT_WARP_ID_OFFSET))
        dest_map_num = int(_u8_from(raw, off + WARP_EVENT_MAP_NUM_OFFSET))
        dest_map_group = int(_u8_from(raw, off + WARP_EVENT_MAP_GROUP_OFFSET))

        out.append(
            {
                "position": [x, y],
                "elevation": elevation,
                "warpId": warp_id,
                "destMapGroup": dest_map_group,
                "destMapNum": dest_map_num,
                "destMapName": get_map_name(dest_map_group, dest_map_num) or f"Unknown({dest_map_group}-{dest_map_num})",
            }
        )

    _WARP_EVENTS_CACHE[int(base_events)] = out
    return out


def _build_object_template_cache_entry(*, sb1_ptr: int) -> Optional[_ObjectTemplateCacheEntry]:
    sb1_ptr_int = int(sb1_ptr)
    if sb1_ptr_int == 0:
        return None

    base_events = mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_EVENTS_OFFSET)
    if base_events == 0:
        return _ObjectTemplateCacheEntry(sb1_ptr=sb1_ptr_int, candidates=tuple(), flags_start_byte=0, flags_len=0)

    obj_count = int(mgba.mgba_read8(base_events + MAP_EVENTS_OBJECT_EVENT_COUNT_OFFSET))
    if obj_count <= 0:
        return _ObjectTemplateCacheEntry(sb1_ptr=sb1_ptr_int, candidates=tuple(), flags_start_byte=0, flags_len=0)

    obj_count = min(obj_count, int(OBJECT_EVENT_TEMPLATES_COUNT))
    total_bytes = int(obj_count) * int(OBJECT_EVENT_TEMPLATE_SIZE)
    raw = mgba.mgba_read_range_bytes(sb1_ptr_int + SB1_OBJECT_EVENT_TEMPLATES_OFFSET, total_bytes)
    if len(raw) < total_bytes:
        return None

    candidates: List[Tuple[Dict[str, Any], int]] = []
    flag_ids: List[int] = []

    for i in range(obj_count):
        off = i * OBJECT_EVENT_TEMPLATE_SIZE
        local_id = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_LOCAL_ID_OFFSET))
        gid = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_GRAPHICS_ID_OFFSET))
        if local_id <= 0 or gid == 0:
            continue

        x_raw = _u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_X_OFFSET)
        y_raw = _u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_Y_OFFSET)
        x = int(_s16_from_u16(x_raw))
        y = int(_s16_from_u16(y_raw))

        elevation = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_ELEVATION_OFFSET))
        movement_type = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_MOVEMENT_TYPE_OFFSET))

        range_raw = _u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_MOVEMENT_RANGE_OFFSET)
        range_x = int(range_raw & 0x0F)
        range_y = int((range_raw >> 4) & 0x0F)

        flag_id = int(_u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_FLAG_ID_OFFSET))
        if flag_id > 0:
            flag_ids.append(flag_id)

        candidates.append(
            (
                {
                    "localId": local_id,
                    "graphicsId": gid,
                    "spawnPosition": [x, y],
                    "elevation": elevation,
                    "movementType": movement_type,
                    "movementRangeX": range_x,
                    "movementRangeY": range_y,
                    "flagId": flag_id,
                },
                flag_id,
            )
        )

    flags_start_byte = 0
    flags_len = 0
    if flag_ids:
        flags_start_byte = min(int(fid) // 8 for fid in flag_ids)
        flags_end_byte = max(int(fid) // 8 for fid in flag_ids)
        flags_len = max(0, int(flags_end_byte - flags_start_byte + 1))

    return _ObjectTemplateCacheEntry(
        sb1_ptr=sb1_ptr_int,
        candidates=tuple(candidates),
        flags_start_byte=int(flags_start_byte),
        flags_len=int(flags_len),
    )


def _filter_object_template_candidates(
    entry: _ObjectTemplateCacheEntry, *, sb1_ptr: int
) -> List[Dict[str, Any]]:
    sb1_ptr_int = int(sb1_ptr)
    if sb1_ptr_int == 0:
        return []

    flags_raw: Optional[bytes] = None
    if int(entry.flags_len) > 0:
        try:
            flags_raw = _mgba_client.mgba_read_range_bytes(
                sb1_ptr_int + SB1_FLAGS_OFFSET + int(entry.flags_start_byte), int(entry.flags_len)
            )
            mgba._record_mgba_read_range_bytes(int(entry.flags_len), flags_raw)
        except Exception:
            flags_raw = None

    def _flag_get_from_snapshot(flag_id: int) -> Optional[bool]:
        if flag_id <= 0:
            return False
        if flags_raw is None:
            return None
        byte_offset = int(flag_id) // 8
        bit_offset = int(flag_id) % 8
        idx = byte_offset - int(entry.flags_start_byte)
        if idx < 0 or idx >= len(flags_raw):
            return None
        flag_byte = int(flags_raw[idx])
        return ((flag_byte >> bit_offset) & 1) == 1

    out: List[Dict[str, Any]] = []
    for tpl, flag_id in entry.candidates:
        if flag_id > 0:
            is_set = _flag_get_from_snapshot(flag_id)
            if is_set is None:
                # Defensive fallback if our snapshot read is missing data.
                if _flag_get_from_sb1(sb1_ptr_int, flag_id):
                    continue
            elif is_set:
                continue
        out.append(tpl)
    return out


def _get_current_map_object_event_templates_cached(
    *,
    map_group: int,
    map_num: int,
    sb1_ptr: int,
) -> List[Dict[str, Any]]:
    sb1_ptr_int = int(sb1_ptr)
    if sb1_ptr_int == 0:
        return []

    key = (int(map_group), int(map_num))
    entry = _OBJECT_TEMPLATES_CACHE.get(key)
    if entry is None or int(entry.sb1_ptr) != sb1_ptr_int:
        built = _build_object_template_cache_entry(sb1_ptr=sb1_ptr_int)
        if built is None:
            return _read_current_map_object_event_templates(sb1_ptr_int)
        _OBJECT_TEMPLATES_CACHE[key] = built
        entry = built

    return _filter_object_template_candidates(entry, sb1_ptr=sb1_ptr_int)


def _read_current_map_object_event_templates(sb1_ptr: int) -> List[Dict[str, Any]]:
    if sb1_ptr == 0:
        return []

    base_events = mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_EVENTS_OFFSET)
    if base_events == 0:
        return []

    obj_count = int(mgba.mgba_read8(base_events + MAP_EVENTS_OBJECT_EVENT_COUNT_OFFSET))
    if obj_count <= 0:
        return []

    obj_count = min(obj_count, OBJECT_EVENT_TEMPLATES_COUNT)

    raw = mgba.mgba_read_range_bytes(sb1_ptr + SB1_OBJECT_EVENT_TEMPLATES_OFFSET, obj_count * OBJECT_EVENT_TEMPLATE_SIZE)
    candidates: List[Tuple[Dict[str, Any], int]] = []
    flag_ids: List[int] = []

    for i in range(obj_count):
        off = i * OBJECT_EVENT_TEMPLATE_SIZE
        local_id = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_LOCAL_ID_OFFSET))
        gid = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_GRAPHICS_ID_OFFSET))
        if local_id <= 0 or gid == 0:
            continue

        x_raw = _u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_X_OFFSET)
        y_raw = _u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_Y_OFFSET)
        x = int(_s16_from_u16(x_raw))
        y = int(_s16_from_u16(y_raw))

        elevation = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_ELEVATION_OFFSET))
        movement_type = int(_u8_from(raw, off + OBJECT_EVENT_TEMPLATE_MOVEMENT_TYPE_OFFSET))

        range_raw = _u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_MOVEMENT_RANGE_OFFSET)
        range_x = int(range_raw & 0x0F)
        range_y = int((range_raw >> 4) & 0x0F)

        flag_id = int(_u16le_from(raw, off + OBJECT_EVENT_TEMPLATE_FLAG_ID_OFFSET))
        if flag_id > 0:
            flag_ids.append(flag_id)

        candidates.append(
            (
                {
                    "localId": local_id,
                    "graphicsId": gid,
                    "spawnPosition": [x, y],
                    "elevation": elevation,
                    "movementType": movement_type,
                    "movementRangeX": range_x,
                    "movementRangeY": range_y,
                    "flagId": flag_id,
                },
                flag_id,
            )
        )

    flags_raw: Optional[bytes] = None
    flags_start_byte = 0
    if flag_ids:
        flags_start_byte = min(int(fid) // 8 for fid in flag_ids)
        flags_end_byte = max(int(fid) // 8 for fid in flag_ids)
        flags_len = max(0, flags_end_byte - flags_start_byte + 1)
        if flags_len:
            # Prefer a true bridge read here. If range snapshots aren't available (unit tests often
            # patch per-read fakes only), fall back to per-flag reads via `_flag_get_from_sb1`.
            try:
                flags_raw = _mgba_client.mgba_read_range_bytes(sb1_ptr + SB1_FLAGS_OFFSET + flags_start_byte, flags_len)
                mgba._record_mgba_read_range_bytes(flags_len, flags_raw)
            except Exception:
                flags_raw = None

    def _flag_get_from_snapshot(flag_id: int) -> Optional[bool]:
        if flag_id <= 0:
            return False
        if flags_raw is None:
            return None
        byte_offset = int(flag_id) // 8
        bit_offset = int(flag_id) % 8
        idx = byte_offset - flags_start_byte
        if idx < 0 or idx >= len(flags_raw):
            return None
        flag_byte = int(flags_raw[idx])
        return ((flag_byte >> bit_offset) & 1) == 1

    out: List[Dict[str, Any]] = []
    for entry, flag_id in candidates:
        if flag_id > 0:
            is_set = _flag_get_from_snapshot(flag_id)
            if is_set is None:
                # Defensive fallback if our snapshot read is missing data.
                if _flag_get_from_sb1(sb1_ptr, flag_id):
                    continue
            elif is_set:
                continue
        out.append(entry)

    return out


def get_current_map_npcs(
    *,
    map_group: Optional[int] = None,
    map_num: Optional[int] = None,
    sb1_ptr: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if map_group is None or map_num is None:
        map_group, map_num = get_current_map_group_num()
    map_group_int = int(map_group)
    map_num_int = int(map_num)

    total_bytes = OBJECT_EVENT_COUNT * OBJECT_EVENT_SIZE
    raw = mgba.mgba_read_range_bytes(OBJECT_EVENTS_ADDR, total_bytes)
    live_by_local: Dict[int, Dict[str, Any]] = {}
    for i in range(1, OBJECT_EVENT_COUNT):  # skip player at index 0
        off = i * OBJECT_EVENT_SIZE
        flags = _u32le_from(raw, off + 0)
        is_active = (flags >> OBJECT_EVENT_ACTIVE_BIT) & 1
        if not is_active:
            continue
        is_off = (flags >> OBJECT_EVENT_OFFSCREEN_BIT) & 1
        gid = _u8_from(raw, off + OBJECT_EVENT_GRAPHICS_ID_OFFSET)
        if gid == 0:
            continue
        local_id = int(_u8_from(raw, off + OBJECT_EVENT_LOCAL_ID_OFFSET))
        if local_id <= 0:
            continue

        # Safety: only keep objects for the current map.
        if int(map_group) >= 0 and int(map_num) >= 0:
            if int(_u8_from(raw, off + OBJECT_EVENT_MAP_GROUP_OFFSET)) != int(map_group):
                continue
            if int(_u8_from(raw, off + OBJECT_EVENT_MAP_NUM_OFFSET)) != int(map_num):
                continue

        movt = int(_u8_from(raw, off + OBJECT_EVENT_MOVEMENT_TYPE_OFFSET))
        x = int(_u16le_from(raw, off + OBJECT_EVENT_X_OFFSET)) - MAP_OFFSET
        y = int(_u16le_from(raw, off + OBJECT_EVENT_Y_OFFSET)) - MAP_OFFSET

        live_by_local[local_id] = {
            "objectEventId": i,
            "position": [int(x), int(y)],
            "graphicsId": int(gid),
            "movementType": movt,
            "isOffScreen": bool(is_off),
        }

    sb1_ptr_int = int(sb1_ptr) if sb1_ptr else int(mgba.mgba_read32(GSAVEBLOCK1_PTR_ADDR))
    templates = _get_current_map_object_event_templates_cached(
        map_group=map_group_int,
        map_num=map_num_int,
        sb1_ptr=sb1_ptr_int,
    )

    out: List[Dict[str, Any]] = []
    seen_local: set[int] = set()

    for tpl in templates:
        local_id = int(tpl.get("localId", 0) or 0)
        if local_id <= 0:
            continue
        seen_local.add(local_id)

        spawn_pos = tpl.get("spawnPosition") or [0, 0]
        live = live_by_local.get(local_id)

        if live is not None:
            position = live.get("position") or spawn_pos
            gid = int(live.get("graphicsId", 0) or 0)
            movement_type = int(live.get("movementType", 0) or 0)
            is_offscreen = bool(live.get("isOffScreen", False))
            object_event_id = int(live.get("objectEventId", 0) or 0)
            is_active = True
        else:
            position = spawn_pos
            gid = int(tpl.get("graphicsId", 0) or 0)
            movement_type = int(tpl.get("movementType", 0) or 0)
            # Not currently loaded in gObjectEvents.
            is_offscreen = True
            object_event_id = None
            is_active = False

        wandering = movement_type in OBJECT_EVENT_WANDERING_TYPES

        out.append(
            {
                "id": local_id,
                "localId": local_id,
                "uid": f"{map_group_int}-{map_num_int}-{local_id}",
                "objectEventId": object_event_id,
                "position": position,
                "spawnPosition": spawn_pos,
                "type": get_event_object_name(gid) or f"Unknown NPC (ID: {gid})",
                "isOffScreen": bool(is_offscreen),
                "wandering": bool(wandering),
                "graphicsId": gid,
                "movementType": movement_type,
                "movementRangeX": int(tpl.get("movementRangeX", 0) or 0),
                "movementRangeY": int(tpl.get("movementRangeY", 0) or 0),
                "flagId": int(tpl.get("flagId", 0) or 0),
                "elevation": int(tpl.get("elevation", 0) or 0),
                "isActive": bool(is_active),
            }
        )

    # Include runtime-only objects not in templates (rare, but can happen via scripts).
    for local_id, live in live_by_local.items():
        if local_id in seen_local:
            continue
        movement_type = int(live.get("movementType", 0) or 0)
        wandering = movement_type in OBJECT_EVENT_WANDERING_TYPES
        gid = int(live.get("graphicsId", 0) or 0)
        pos = live.get("position") or [0, 0]
        out.append(
            {
                "id": local_id,
                "localId": local_id,
                "uid": f"{map_group_int}-{map_num_int}-{local_id}",
                "objectEventId": int(live.get("objectEventId", 0) or 0),
                "position": pos,
                "spawnPosition": pos,
                "type": get_event_object_name(gid) or f"Unknown NPC (ID: {gid})",
                "isOffScreen": bool(live.get("isOffScreen", False)),
                "wandering": bool(wandering),
                "graphicsId": gid,
                "movementType": movement_type,
                "movementRangeX": 0,
                "movementRangeY": 0,
                "flagId": 0,
                "elevation": 0,
                "isActive": True,
            }
        )

    return out


def get_current_map_connections(*, map_group: Optional[int] = None, map_num: Optional[int] = None) -> List[Dict[str, Any]]:
    ptr = _get_map_connections_ptr(map_group=map_group, map_num=map_num)
    if ptr == 0:
        return []
    cached = _CONNECTIONS_CACHE.get(int(ptr))
    if cached is not None:
        return cached
    count_raw, arr_ptr_raw = mgba.mgba_read_ranges_bytes(
        [
            (ptr + MAP_CONNECTIONS_COUNT_OFFSET, 4),
            (ptr + MAP_CONNECTIONS_CONNECTION_POINTER_OFFSET, 4),
        ]
    )
    if not count_raw or len(count_raw) < 4:
        return []
    if not arr_ptr_raw or len(arr_ptr_raw) < 4:
        return []
    count = _u32le_from(count_raw, 0)
    if count <= 0 or count > 32:
        return []
    arr_ptr = _u32le_from(arr_ptr_raw, 0)
    if arr_ptr == 0:
        return []
    total_bytes = int(count) * int(MAP_CONNECTION_SIZE)
    raw = mgba.mgba_read_range_bytes(arr_ptr, total_bytes)
    if len(raw) < total_bytes:
        return []
    out: List[Dict[str, Any]] = []
    for i in range(count):
        off = i * MAP_CONNECTION_SIZE
        direction_raw = _u8_from(raw, off + MAP_CONNECTION_DIRECTION_OFFSET)
        direction = FACING_DIRECTION_MAP.get(direction_raw, f"unknown({direction_raw})")
        dest_group = _u8_from(raw, off + MAP_CONNECTION_MAP_GROUP_OFFSET)
        dest_num = _u8_from(raw, off + MAP_CONNECTION_MAP_NUM_OFFSET)
        off_raw = _u32le_from(raw, off + 4)
        off_val = off_raw - 0x100000000 if off_raw > 0x7FFFFFFF else off_raw
        out.append(
            {
                "direction": direction,
                "mapName": get_map_name(dest_group, dest_num) or f"Unknown({dest_group}-{dest_num})",
                "offset": off_val,
            }
        )

    dirs = {"up", "down", "left", "right"}
    present = set(c["direction"] for c in out)
    for d in dirs:
        if d not in present:
            out.append({"direction": d, "mapName": "MAP_NONE"})
    _CONNECTIONS_CACHE[int(ptr)] = out
    return out


# =============================================================================
