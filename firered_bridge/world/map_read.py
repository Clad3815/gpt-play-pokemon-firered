from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any, Dict, List, Optional, Tuple

from ..constants.addresses import (
    BACKUP_MAP_DATA_PTR_OFFSET,
    BACKUP_MAP_LAYOUT_ADDR,
    BACKUP_MAP_LAYOUT_HEIGHT_OFFSET,
    BACKUP_MAP_LAYOUT_WIDTH_OFFSET,
    BYTES_PER_TILE,
    CURRENT_MAP_HEADER_ADDR,
    MAP_HEADER_MAP_LAYOUT_OFFSET,
    MAP_LAYOUT_HEIGHT_OFFSET,
    MAP_LAYOUT_MAPGRID_OFFSET,
    MAP_LAYOUT_PRIMARY_TILESET_OFFSET,
    MAP_LAYOUT_SECONDARY_TILESET_OFFSET,
    MAP_LAYOUT_WIDTH_OFFSET,
    MAP_OFFSET,
    PRIMARY_TILESET_METATILE_COUNT,
    SECONDARY_TILESET_METATILE_COUNT,
    TILESET_METATILE_ATTRIBUTES_POINTER_OFFSET,
)
from ..game_data import get_behavior_name
from ..memory import mgba
from ..util.bytes import _u32le_from

# Map reading (main + backup), tilesets & behaviors
# =============================================================================

@dataclass(frozen=True, slots=True)
class _MapStaticCache:
    key: Tuple[int, int, int, int]  # (layout_base, backup_w, backup_h, backup_data_ptr)
    main_w: int
    main_h: int
    grid_ptr: int
    main_beh: List[int]


_BEHAVIOR_BY_ATTR_PTR_CACHE: Dict[Tuple[int, int], List[int]] = {}
_MAP_STATIC_CACHE: _MapStaticCache | None = None


def _decode_metatile_behaviors_from_attributes(raw_attrs: bytes, count: int) -> List[int]:
    """
    Decode metatile behavior IDs from FRLG metatile attributes.

    FireRed stores one 32-bit attribute per metatile
    (fieldmap.c: behavior is bits 0-8).
    """
    if not raw_attrs or count <= 0:
        return []

    total_entries = min(int(count), len(raw_attrs) // 4)
    out: List[int] = []
    for i in range(total_entries):
        off = i * 4
        attrs = _u32le_from(raw_attrs, off)
        out.append(int(attrs) & 0x1FF)  # METATILE_ATTRIBUTE_BEHAVIOR mask
    return out


def _read_map_tiles_and_behaviors_fast() -> Tuple[int, int, List[int], List[int], int, int, List[int]]:
    """
    Read main/backup map tiles and metatile behaviors with a small number of bridge calls.

    This function snapshots dynamic RAM state (map grid/backup grid) every call, but caches static
    ROM-derived data (tileset behaviors) and stable pointers per map to reduce bridge round-trips.
    """
    def _derive_main_tiles_from_backup(
        *,
        main_w: int,
        main_h: int,
        backup_w: int,
        backup_h: int,
        backup_tiles: List[int],
    ) -> Optional[List[int]]:
        """
        Use VMap (backup map layout) as the source of truth for the current map's tiles.

        The engine resolves MapGrid values (collision/elevation/metatile) from `VMap.map`
        (fieldmap.c:GetMapGridBlockAt). This matters for dynamic maps like Trainer Hill/Battle Pyramid
        and for runtime metatile changes (doors, scripts, etc).
        """
        if main_w <= 0 or main_h <= 0 or backup_w <= 0 or backup_h <= 0 or not backup_tiles:
            return None

        required_w = main_w + (MAP_OFFSET * 2 + 1)
        required_h = main_h + (MAP_OFFSET * 2)
        if backup_w < required_w or backup_h < required_h:
            return None

        if len(backup_tiles) < (backup_w * backup_h):
            return None

        out: List[int] = []
        for y in range(main_h):
            by = y + MAP_OFFSET
            start = (by * backup_w) + MAP_OFFSET
            end = start + main_w
            if start < 0 or end > len(backup_tiles):
                return None
            out.extend(backup_tiles[start:end])

        if len(out) != (main_w * main_h):
            return None
        return out

    global _MAP_STATIC_CACHE

    try:
        # Stage 1: read pointers we can address directly.
        layout_base_raw, backup_w_raw, backup_h_raw, backup_data_ptr_raw = mgba.mgba_read_ranges_bytes(
            [
                (CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_LAYOUT_OFFSET, 4),
                (BACKUP_MAP_LAYOUT_ADDR + BACKUP_MAP_LAYOUT_WIDTH_OFFSET, 4),
                (BACKUP_MAP_LAYOUT_ADDR + BACKUP_MAP_LAYOUT_HEIGHT_OFFSET, 4),
                (BACKUP_MAP_LAYOUT_ADDR + BACKUP_MAP_DATA_PTR_OFFSET, 4),
            ]
        )
        layout_base = _u32le_from(layout_base_raw, 0)
        backup_w = _u32le_from(backup_w_raw, 0)
        backup_h = _u32le_from(backup_h_raw, 0)
        backup_data_ptr = _u32le_from(backup_data_ptr_raw, 0)

        cache_key = (int(layout_base), int(backup_w), int(backup_h), int(backup_data_ptr))
        cached = _MAP_STATIC_CACHE
        if (
            cached is not None
            and cached.key == cache_key
            and int(cached.main_w) > 0
            and int(cached.main_h) > 0
            and int(cached.grid_ptr) != 0
        ):
            main_w = int(cached.main_w)
            main_h = int(cached.main_h)
            grid_ptr = int(cached.grid_ptr)
            main_beh = cached.main_beh

            # Stage 4 (cached): only read dynamic grids; behaviors are cached.
            data_ranges: List[Tuple[int, int]] = []
            data_order: List[str] = []

            main_bytes = int(main_w) * int(main_h) * BYTES_PER_TILE if main_w > 0 and main_h > 0 else 0
            backup_bytes = int(backup_w) * int(backup_h) * BYTES_PER_TILE if backup_w > 0 and backup_h > 0 else 0

            if grid_ptr and main_bytes > 0:
                data_ranges.append((grid_ptr, main_bytes))
                data_order.append("main_tiles")
            if backup_data_ptr and backup_bytes > 0:
                data_ranges.append((backup_data_ptr, backup_bytes))
                data_order.append("backup_tiles")

            data_segments = mgba.mgba_read_ranges_bytes(data_ranges) if data_ranges else []
            seg_by_name = {name: seg for name, seg in zip(data_order, data_segments)}

            raw_main = seg_by_name.get("main_tiles", b"")
            raw_main = raw_main[: (len(raw_main) & ~1)]
            main_tiles = [v[0] for v in struct.iter_unpack("<H", raw_main)] if raw_main else []

            raw_backup = seg_by_name.get("backup_tiles", b"")
            raw_backup = raw_backup[: (len(raw_backup) & ~1)]
            backup_tiles = [v[0] for v in struct.iter_unpack("<H", raw_backup)] if raw_backup else []

            derived_main = _derive_main_tiles_from_backup(
                main_w=int(main_w),
                main_h=int(main_h),
                backup_w=int(backup_w),
                backup_h=int(backup_h),
                backup_tiles=backup_tiles,
            )
            if derived_main is not None:
                main_tiles = derived_main

            return int(main_w), int(main_h), main_tiles, main_beh, int(backup_w), int(backup_h), backup_tiles

        main_w = 0
        main_h = 0
        grid_ptr = 0
        primary_tileset = 0
        secondary_tileset = 0

        if layout_base:
            # Stage 2: read layout-derived pointers/dims.
            main_w_raw, main_h_raw, grid_ptr_raw, primary_ts_raw, secondary_ts_raw = mgba.mgba_read_ranges_bytes(
                [
                    (layout_base + MAP_LAYOUT_WIDTH_OFFSET, 4),
                    (layout_base + MAP_LAYOUT_HEIGHT_OFFSET, 4),
                    (layout_base + MAP_LAYOUT_MAPGRID_OFFSET, 4),
                    (layout_base + MAP_LAYOUT_PRIMARY_TILESET_OFFSET, 4),
                    (layout_base + MAP_LAYOUT_SECONDARY_TILESET_OFFSET, 4),
                ]
            )
            main_w = _u32le_from(main_w_raw, 0)
            main_h = _u32le_from(main_h_raw, 0)
            grid_ptr = _u32le_from(grid_ptr_raw, 0)
            primary_tileset = _u32le_from(primary_ts_raw, 0)
            secondary_tileset = _u32le_from(secondary_ts_raw, 0)

        # Stage 3: tileset attribute pointers.
        attr_ranges: List[Tuple[int, int]] = []
        attr_order: List[str] = []
        if primary_tileset:
            attr_ranges.append((primary_tileset + TILESET_METATILE_ATTRIBUTES_POINTER_OFFSET, 4))
            attr_order.append("primary")
        if secondary_tileset:
            attr_ranges.append((secondary_tileset + TILESET_METATILE_ATTRIBUTES_POINTER_OFFSET, 4))
            attr_order.append("secondary")

        primary_attr_ptr = 0
        secondary_attr_ptr = 0
        if attr_ranges:
            attr_ptrs = mgba.mgba_read_ranges_bytes(attr_ranges)
            for which, raw in zip(attr_order, attr_ptrs):
                ptr = _u32le_from(raw, 0)
                if which == "primary":
                    primary_attr_ptr = ptr
                elif which == "secondary":
                    secondary_attr_ptr = ptr

        # Stage 4: actual bulk data reads (map grids + metatile behaviors).
        data_ranges: List[Tuple[int, int]] = []
        data_order: List[str] = []

        main_bytes = int(main_w) * int(main_h) * BYTES_PER_TILE if main_w > 0 and main_h > 0 else 0
        backup_bytes = int(backup_w) * int(backup_h) * BYTES_PER_TILE if backup_w > 0 and backup_h > 0 else 0
        primary_behaviors_bytes = PRIMARY_TILESET_METATILE_COUNT * 4
        secondary_behaviors_bytes = SECONDARY_TILESET_METATILE_COUNT * 4

        if grid_ptr and main_bytes > 0:
            data_ranges.append((grid_ptr, main_bytes))
            data_order.append("main_tiles")
        if backup_data_ptr and backup_bytes > 0:
            data_ranges.append((backup_data_ptr, backup_bytes))
            data_order.append("backup_tiles")
        primary_cache_key = (int(primary_attr_ptr), int(PRIMARY_TILESET_METATILE_COUNT))
        secondary_cache_key = (int(secondary_attr_ptr), int(SECONDARY_TILESET_METATILE_COUNT))
        primary_beh = _BEHAVIOR_BY_ATTR_PTR_CACHE.get(primary_cache_key) if primary_attr_ptr else None
        secondary_beh = _BEHAVIOR_BY_ATTR_PTR_CACHE.get(secondary_cache_key) if secondary_attr_ptr else None
        if primary_attr_ptr and primary_beh is None:
            data_ranges.append((primary_attr_ptr, primary_behaviors_bytes))
            data_order.append("primary_beh")
        if secondary_attr_ptr and secondary_beh is None:
            data_ranges.append((secondary_attr_ptr, secondary_behaviors_bytes))
            data_order.append("secondary_beh")

        data_segments = mgba.mgba_read_ranges_bytes(data_ranges) if data_ranges else []
        seg_by_name = {name: seg for name, seg in zip(data_order, data_segments)}

        raw_main = seg_by_name.get("main_tiles", b"")
        raw_main = raw_main[: (len(raw_main) & ~1)]
        main_tiles = [v[0] for v in struct.iter_unpack("<H", raw_main)] if raw_main else []

        raw_backup = seg_by_name.get("backup_tiles", b"")
        raw_backup = raw_backup[: (len(raw_backup) & ~1)]
        backup_tiles = [v[0] for v in struct.iter_unpack("<H", raw_backup)] if raw_backup else []

        if primary_beh is None and primary_attr_ptr:
            raw_primary_beh = seg_by_name.get("primary_beh", b"")
            if raw_primary_beh and len(raw_primary_beh) >= primary_behaviors_bytes:
                primary_beh = _decode_metatile_behaviors_from_attributes(
                    raw_primary_beh,
                    PRIMARY_TILESET_METATILE_COUNT,
                )
                _BEHAVIOR_BY_ATTR_PTR_CACHE[primary_cache_key] = primary_beh

        if secondary_beh is None and secondary_attr_ptr:
            raw_secondary_beh = seg_by_name.get("secondary_beh", b"")
            if raw_secondary_beh and len(raw_secondary_beh) >= secondary_behaviors_bytes:
                secondary_beh = _decode_metatile_behaviors_from_attributes(
                    raw_secondary_beh,
                    SECONDARY_TILESET_METATILE_COUNT,
                )
                _BEHAVIOR_BY_ATTR_PTR_CACHE[secondary_cache_key] = secondary_beh

        main_beh: List[int] = []
        if primary_beh:
            main_beh.extend(primary_beh)
        if secondary_beh:
            main_beh.extend(secondary_beh)

        derived_main = _derive_main_tiles_from_backup(
            main_w=int(main_w),
            main_h=int(main_h),
            backup_w=int(backup_w),
            backup_h=int(backup_h),
            backup_tiles=backup_tiles,
        )
        if derived_main is not None:
            main_tiles = derived_main

        _MAP_STATIC_CACHE = _MapStaticCache(
            key=cache_key,
            main_w=int(main_w),
            main_h=int(main_h),
            grid_ptr=int(grid_ptr),
            main_beh=main_beh,
        )

        return int(main_w), int(main_h), main_tiles, main_beh, int(backup_w), int(backup_h), backup_tiles
    except Exception:
        main_w = get_main_map_width()
        main_h = get_main_map_height()
        main_tiles = get_main_map_tiles(main_w, main_h) if main_w > 0 and main_h > 0 else []
        main_beh = get_main_metatile_behaviors() or []
        backup_w, backup_h = get_backup_map_dims()
        backup_tiles = get_backup_map_tiles(backup_w, backup_h) if backup_w > 0 and backup_h > 0 else []
        derived_main = _derive_main_tiles_from_backup(
            main_w=int(main_w),
            main_h=int(main_h),
            backup_w=int(backup_w),
            backup_h=int(backup_h),
            backup_tiles=backup_tiles,
        )
        if derived_main is not None:
            main_tiles = derived_main
        return main_w, main_h, main_tiles, main_beh, backup_w, backup_h, backup_tiles


def get_main_map_layout_base() -> int:
    return mgba.mgba_read32(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_LAYOUT_OFFSET)


def get_main_map_width() -> int:
    base = get_main_map_layout_base()
    return mgba.mgba_read32(base + MAP_LAYOUT_WIDTH_OFFSET)


def get_main_map_height() -> int:
    base = get_main_map_layout_base()
    return mgba.mgba_read32(base + MAP_LAYOUT_HEIGHT_OFFSET)


def get_main_map_tiles(width: int, height: int) -> List[int]:
    base = get_main_map_layout_base()
    grid_ptr = mgba.mgba_read32(base + MAP_LAYOUT_MAPGRID_OFFSET)
    total_bytes = width * height * BYTES_PER_TILE
    raw = mgba.mgba_read_range(grid_ptr, total_bytes)
    tiles = []
    for i in range(0, len(raw), 2):
        tiles.append((raw[i + 1] << 8) | raw[i])
    return tiles


def get_backup_map_dims() -> Tuple[int, int]:
    width = mgba.mgba_read32(BACKUP_MAP_LAYOUT_ADDR + BACKUP_MAP_LAYOUT_WIDTH_OFFSET)
    height = mgba.mgba_read32(BACKUP_MAP_LAYOUT_ADDR + BACKUP_MAP_LAYOUT_HEIGHT_OFFSET)
    return width, height


def get_backup_map_tiles(width: int, height: int) -> List[int]:
    data_ptr = mgba.mgba_read32(BACKUP_MAP_LAYOUT_ADDR + BACKUP_MAP_DATA_PTR_OFFSET)
    total_bytes = width * height * BYTES_PER_TILE
    raw = mgba.mgba_read_range(data_ptr, total_bytes)
    tiles = []
    for i in range(0, len(raw), 2):
        tiles.append((raw[i + 1] << 8) | raw[i])
    return tiles


def _tileset_pointers(layout_base: int) -> Tuple[int, int]:
    primary = mgba.mgba_read32(layout_base + MAP_LAYOUT_PRIMARY_TILESET_OFFSET)
    secondary = mgba.mgba_read32(layout_base + MAP_LAYOUT_SECONDARY_TILESET_OFFSET)
    return primary, secondary


def _read_metatile_behaviors_from_tileset(tileset_base: int, count: int) -> Optional[List[int]]:
    if tileset_base == 0:
        return []
    attr_ptr = mgba.mgba_read32(tileset_base + TILESET_METATILE_ATTRIBUTES_POINTER_OFFSET)
    if attr_ptr == 0:
        return None
    raw = mgba.mgba_read_range_bytes(attr_ptr, count * 4)
    return _decode_metatile_behaviors_from_attributes(raw, int(count))


def get_main_metatile_behaviors() -> Optional[List[int]]:
    layout = get_main_map_layout_base()
    primary, secondary = _tileset_pointers(layout)

    allb: List[int] = []
    a = _read_metatile_behaviors_from_tileset(primary, PRIMARY_TILESET_METATILE_COUNT)
    if a is None:
        return None
    allb.extend(a)

    if secondary != 0:
        b = _read_metatile_behaviors_from_tileset(secondary, SECONDARY_TILESET_METATILE_COUNT)
        if b is None:
            return None
        allb.extend(b)

    return allb


def get_backup_metatile_behaviors() -> Optional[List[int]]:
    # Pour la backup, on réutilise les tilesets du main
    return get_main_metatile_behaviors()


def behavior_name_from_id(behavior_id: int) -> Optional[str]:
    return get_behavior_name(behavior_id)


# =============================================================================
