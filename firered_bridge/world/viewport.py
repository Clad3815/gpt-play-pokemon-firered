from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..constants.addresses import MAPGRID_COLLISION_MASK, MAPGRID_METATILE_ID_MASK, MAPGRID_UNDEFINED
from ..constants.behaviors import (
    ARROW_WARP_DELTA_BY_BEHAVIOR_ID,
    INTERACTIVE_METATILE_BEHAVIOR_IDS,
    INTERACTIVE_METATILE_TILE_BY_BEHAVIOR_ID,
    MAX_VIEWPORT_HEIGHT,
    MAX_VIEWPORT_WIDTH,
    RED_CARPET_BEHAVIOR_IDS,
    STAIR_WARP_DELTA_BY_BEHAVIOR_ID,
    TEMPORARY_WALL_TILES_BY_MAP,
    WARP_VISUAL_TILE_BY_BEHAVIOR_ID,
    is_silph_co_door_bg_event,
    is_silph_co_locked_door_metatile,
    _init_behavior_id_tables,
)
from ..constants.tiles import (
    MINIMAP_CODE_DOOR,
    MINIMAP_CODE_FREE_GROUND,
    MINIMAP_CODE_INTERACTIVE,
    MINIMAP_CODE_LOCKED_DOOR,
    MINIMAP_CODE_NPC,
    MINIMAP_CODE_RED_CARPET,
    MINIMAP_CODE_STAIRS,
    MINIMAP_CODE_TEMPORARY_WALL,
    MINIMAP_CODE_WARP,
    MINIMAP_CODE_WALL,
    MINIMAP_TILES,
    OBJECT_EVENT_TILE_BY_TYPE,
    TILE_BLOCKED,
    TILE_DOOR,
    TILE_INTERACTIVE,
    TILE_LOCKED_DOOR,
    TILE_NPC,
    TILE_RED_CARPET,
    TILE_STAIRS,
    TILE_WARP,
    VIEWPORT_TILE_PASSABILITY,
    _oob_tile_for_coord,
    minimap_code_for_tile,
)

# Viewport trimming + overlays
# =============================================================================


def _render_map_region_with_overlays(
    full: Dict[str, Any],
    startX: int,
    startY: int,
    endX: int,
    endY: int,
    *,
    tile_values: Optional[List[int]] = None,
    behaviors: Optional[List[int]] = None,
    include_offscreen_npcs: bool = False,
    return_filtered: bool = True,
    backup_tiles: Optional[List[int]] = None,
    backup_width: int = 0,
    backup_height: int = 0,
) -> Tuple[List[List[str]], List[List[int]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    width = int(full.get("width", 0) or 0)
    height = int(full.get("height", 0) or 0)
    map_name = str(full.get("map_name") or "")
    if width <= 0 or height <= 0:
        return [], [], [], []

    temporary_wall_locs: Dict[str, str] = TEMPORARY_WALL_TILES_BY_MAP.get(str(full.get("map_name") or ""), {})
    has_behavior_snapshot = bool(tile_values and behaviors and width > 0)
    if has_behavior_snapshot:
        _init_behavior_id_tables()

    # Object events (NPCs + special objects like boulders / berry trees)
    object_locs: Dict[str, str] = {}
    filtered_npcs: List[Dict[str, Any]] = [] if return_filtered else []
    for n in full.get("npcs", []):
        pos = n.get("position")
        if not (pos and len(pos) == 2):
            continue
        if (not include_offscreen_npcs) and n.get("isOffScreen", False):
            continue
        coord = f"{pos[0]},{pos[1]}"
        obj_type = str(n.get("type") or "")
        object_locs[coord] = OBJECT_EVENT_TILE_BY_TYPE.get(obj_type, TILE_NPC)
        if return_filtered and startX <= pos[0] < endX and startY <= pos[1] < endY:
            filtered_npcs.append(n)

    # BG Events (interactive elements, hidden items already filtered out)
    bg_interactive_locs: Dict[str, str] = {}
    silph_co_door_bg_coords: set[str] = set()
    filtered_bg_events: List[Dict[str, Any]] = [] if return_filtered else []
    for bg in full.get("bg_events", []):
        pos = bg.get("position")
        if not (pos and len(pos) == 2):
            continue
        coord = f"{pos[0]},{pos[1]}"
        bg_interactive_locs[coord] = TILE_INTERACTIVE
        script_addr = int(bg.get("scriptAddr") or 0)
        if is_silph_co_door_bg_event(map_name=map_name, script_addr=script_addr):
            silph_co_door_bg_coords.add(coord)
        if return_filtered and startX <= pos[0] < endX and startY <= pos[1] < endY:
            filtered_bg_events.append(bg)

    # Warp events (fallback overlay when behavior-based warp visuals are unavailable).
    warp_locs: set[str] = set()
    for warp in full.get("warp_events", []):
        pos = warp.get("position")
        if not (pos and len(pos) == 2):
            continue
        warp_locs.add(f"{pos[0]},{pos[1]}")

    # Render region (npc > interactive > warp_visual > base terrain)
    trimmed: List[List[str]] = []
    trimmed_codes: List[List[int]] = []
    base_grid: List[List[int]] = (
        full.get("minimap_data", {}).get("grid", []) if isinstance(full.get("minimap_data"), dict) else []
    )

    map_data = full.get("map_data", [])
    tv = tile_values or []
    beh = behaviors or []
    tv_len = len(tv)
    beh_len = len(beh)

    # Extra overlay: when an arrow-warp tile faces into an in-bounds collision tile,
    # mark that adjacent collision tile as a "door" (ex: cave exit rocks).
    #
    # FireRed-specific rule: for red carpet exits (SOUTH_ARROW_WARP), if the tile
    # directly below is a wall, mark that wall tile as a visible door.
    adjacent_door_locs: set[str] = set()
    if has_behavior_snapshot and ARROW_WARP_DELTA_BY_BEHAVIOR_ID:
        total = min(tv_len, width * height)
        for i in range(total):
            sval = tv[i]
            if sval == MAPGRID_UNDEFINED:
                continue
            # Some maps use arrow-warp behaviors on decorative wall tiles.
            # Only treat arrow-warp adjacency as a "door" when the source tile
            # itself is walkable (collision-free), otherwise it creates false positives.
            source_collision_bits = (sval & MAPGRID_COLLISION_MASK) >> 10
            if source_collision_bits != 0:
                continue
            metatile_id = sval & MAPGRID_METATILE_ID_MASK
            if metatile_id >= beh_len:
                continue
            beh_id = beh[metatile_id]
            delta = ARROW_WARP_DELTA_BY_BEHAVIOR_ID.get(beh_id)
            if delta is None:
                continue
            dx, dy = delta
            # Red-carpet exits only generate a door on their DOWN side.
            if beh_id in RED_CARPET_BEHAVIOR_IDS and (dx != 0 or dy != 1):
                continue
            x = i % width
            y = i // width
            tx = x + dx
            ty = y + dy
            if not (0 <= tx < width and 0 <= ty < height):
                continue
            ti = ty * width + tx
            if ti < 0 or ti >= tv_len:
                continue
            tval = tv[ti]
            if tval == MAPGRID_UNDEFINED:
                continue
            collision_bits = (tval & MAPGRID_COLLISION_MASK) >> 10
            if collision_bits != 0:
                adjacent_door_locs.add(f"{tx},{ty}")

    # Stair warp visual correction:
    # - render stairs on the orientation-shifted tile
    # - render the source tile as red carpet
    stair_target_locs: set[str] = set()
    stair_source_locs: set[str] = set()
    if has_behavior_snapshot and STAIR_WARP_DELTA_BY_BEHAVIOR_ID:
        total = min(tv_len, width * height)
        for i in range(total):
            metatile_id = tv[i] & MAPGRID_METATILE_ID_MASK
            if metatile_id >= beh_len:
                continue
            beh_id = beh[metatile_id]
            delta = STAIR_WARP_DELTA_BY_BEHAVIOR_ID.get(beh_id)
            if delta is None:
                continue
            x = i % width
            y = i // width
            dx, dy = delta
            tx = x + dx
            ty = y + dy
            if not (0 <= tx < width and 0 <= ty < height):
                continue
            stair_source_locs.add(f"{x},{y}")
            stair_target_locs.add(f"{tx},{ty}")

    for y in range(startY, endY):
        row_out: List[str] = []
        row_codes: List[int] = []
        for x in range(startX, endX):
            in_bounds = 0 <= x < width and 0 <= y < height
            coord = f"{x},{y}"
            if in_bounds:
                if coord in object_locs:
                    t = object_locs[coord]
                    code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_NPC)
                else:
                    beh_id = -1
                    metatile_id = -1
                    if has_behavior_snapshot:
                        idx = y * width + x
                        if 0 <= idx < tv_len:
                            metatile_id = int(tv[idx] & MAPGRID_METATILE_ID_MASK)
                            if 0 <= metatile_id < beh_len:
                                beh_id = beh[metatile_id]

                    # Interactive overlays (BG events + metatile behaviors). Behavior-based interactives
                    # can override the generic BG-event icon at the same coord.
                    interactive_tile: Optional[str] = bg_interactive_locs.get(coord)
                    if beh_id != -1 and beh_id in INTERACTIVE_METATILE_BEHAVIOR_IDS:
                        interactive_tile = INTERACTIVE_METATILE_TILE_BY_BEHAVIOR_ID.get(beh_id, TILE_INTERACTIVE)

                    # Base terrain (kept so warp fallback can still use the real underlying collision state
                    # even when an interactive/bg overlay is present on the same coordinate).
                    base_tile = TILE_BLOCKED
                    base_code = MINIMAP_CODE_WALL
                    if 0 <= y < len(base_grid) and 0 <= x < len(base_grid[y]):
                        base_code = int(base_grid[y][x])
                        td = MINIMAP_TILES.get(base_code)
                        base_tile = td.tile_id if td else TILE_BLOCKED
                    else:
                        # Fallback for older callers/tests that provide only map_data.
                        row_src = map_data[y] if 0 <= y < len(map_data) else None
                        if row_src and 0 <= x < len(row_src):
                            parts = row_src[x].split(":")
                            base_tile = parts[1] if len(parts) > 1 else TILE_BLOCKED
                            base_code = minimap_code_for_tile(base_tile, default_code=MINIMAP_CODE_WALL)
                        else:
                            base_tile = TILE_BLOCKED
                            base_code = MINIMAP_CODE_WALL

                    # Default visible layer (interactive/floor/base), before warp/door overrides.
                    t = base_tile
                    code = base_code
                    is_locked_silph_door = (
                        metatile_id != -1
                        and is_silph_co_locked_door_metatile(map_name=map_name, metatile_id=metatile_id)
                    )
                    if is_locked_silph_door:
                        t = TILE_LOCKED_DOOR
                        code = MINIMAP_CODE_LOCKED_DOOR
                    elif interactive_tile is not None:
                        # Silph Co Card Key doors keep their BG event scripts after opening.
                        # Once the metatile is no longer a locked barrier, preserve walkable
                        # base terrain instead of forcing a permanent interactive overlay.
                        if coord in silph_co_door_bg_coords and base_code not in (
                            MINIMAP_CODE_WALL,
                            MINIMAP_CODE_TEMPORARY_WALL,
                        ):
                            t = base_tile
                            code = base_code
                        else:
                            t = interactive_tile
                            code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_INTERACTIVE)
                    elif coord in temporary_wall_locs and base_code == MINIMAP_CODE_WALL:
                        t = temporary_wall_locs[coord]
                        code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_WALL)

                    # Warp/door overlays have priority over generic interactive markers.
                    if coord in adjacent_door_locs:
                        t = TILE_DOOR
                        code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_DOOR)
                    elif coord in stair_target_locs:
                        t = TILE_STAIRS
                        code = MINIMAP_CODE_STAIRS
                    elif coord in stair_source_locs:
                        t = TILE_RED_CARPET
                        code = MINIMAP_CODE_RED_CARPET
                    elif (
                        beh_id != -1
                        and not is_locked_silph_door
                        and beh_id not in RED_CARPET_BEHAVIOR_IDS
                        and beh_id not in ARROW_WARP_DELTA_BY_BEHAVIOR_ID
                    ):
                        warp_tile = WARP_VISUAL_TILE_BY_BEHAVIOR_ID.get(beh_id)
                        if warp_tile:
                            # Door-like behavior without an actual warp target is usually a scripted
                            # machine/decoration door (ex: Bill's teleporter), not a usable exit.
                            if (
                                warp_tile == TILE_DOOR
                                and coord not in warp_locs
                                and coord not in adjacent_door_locs
                            ):
                                t = TILE_INTERACTIVE
                                code = MINIMAP_CODE_INTERACTIVE
                            else:
                                t = warp_tile
                                code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_WARP)
                    elif (
                        coord in warp_locs
                        and not is_locked_silph_door
                        and beh_id not in RED_CARPET_BEHAVIOR_IDS
                        and beh_id not in ARROW_WARP_DELTA_BY_BEHAVIOR_ID
                    ):
                        # Warp-event fallback:
                        # - blocked underlying tile + interactive/bg event (wall hole) => show as door
                        # - otherwise, keep the legacy "walkable only" warp overlay.
                        if base_code == MINIMAP_CODE_WALL and interactive_tile is not None:
                            t = TILE_DOOR
                            code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_DOOR)
                        elif code not in (MINIMAP_CODE_WALL, MINIMAP_CODE_TEMPORARY_WALL, MINIMAP_CODE_LOCKED_DOOR):
                            t = TILE_WARP
                            code = MINIMAP_CODE_WARP
            else:
                t = _oob_tile_for_coord(x, y, backup_tiles, backup_width, backup_height)
                code = minimap_code_for_tile(t, default_code=MINIMAP_CODE_WALL)

            row_out.append(f"{coord}:{t}")
            row_codes.append(code)

        trimmed.append(row_out)
        trimmed_codes.append(row_codes)

    return trimmed, trimmed_codes, filtered_npcs, filtered_bg_events


def trim_map_to_viewport(
    full: Dict[str, Any],
    player_xy: Tuple[int, int],
    tile_values: Optional[List[int]] = None,
    behaviors: Optional[List[int]] = None,
    *,
    viewport_width: int = MAX_VIEWPORT_WIDTH,
    viewport_height: int = MAX_VIEWPORT_HEIGHT,
    backup_tiles: Optional[List[int]] = None,
    backup_width: int = 0,
    backup_height: int = 0,
) -> Dict[str, Any]:
    if full.get("width", 0) == 0 or full.get("height", 0) == 0:
        return {
            "map_name": full.get("map_name", ""),
            "width": 0,
            "height": 0,
            "tile_passability": VIEWPORT_TILE_PASSABILITY,
            "map_data": [],
            "minimap_data": {"grid": []},
            "player_state": full.get("player_state", {}),
            "npcs": [],
            "bg_events": [],
            "connections": [],
        }

    playerX, playerY = player_xy
    viewport_width = int(viewport_width) if int(viewport_width) > 0 else MAX_VIEWPORT_WIDTH
    viewport_height = int(viewport_height) if int(viewport_height) > 0 else MAX_VIEWPORT_HEIGHT

    halfW = viewport_width // 2
    halfH = viewport_height // 2
    startX = playerX - halfW
    startY = playerY - halfH
    endX = startX + viewport_width
    endY = startY + viewport_height

    trimmed, trimmed_codes, filtered_npcs, filtered_bg_events = _render_map_region_with_overlays(
        full,
        startX,
        startY,
        endX,
        endY,
        tile_values=tile_values,
        behaviors=behaviors,
        include_offscreen_npcs=False,
        backup_tiles=backup_tiles,
        backup_width=backup_width,
        backup_height=backup_height,
    )

    connections = full.get("connections", [])

    return {
        "map_name": full.get("map_name", ""),
        "width": full.get("width", 0),
        "height": full.get("height", 0),
        "tile_passability": VIEWPORT_TILE_PASSABILITY,
        "map_data": trimmed,
        "minimap_data": {"grid": trimmed_codes, "origin": [startX, startY]},
        "player_state": full.get("player_state", {}),
        "npcs": filtered_npcs,
        "bg_events": filtered_bg_events,
        "connections": connections,
    }


# =============================================================================
