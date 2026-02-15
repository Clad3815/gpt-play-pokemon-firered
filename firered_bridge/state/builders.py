from __future__ import annotations

import hashlib
import logging
from contextlib import nullcontext
from time import perf_counter
from typing import Any, Dict, List, Tuple

from .. import fog_of_war
from .. import game_data
from ..config import MGBA_API_URL
from ..constants.addresses import *  # noqa: F403
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
    MINIMAP_LEGEND,
    MINIMAP_CODE_BOULDER,
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
    TILE_INTERACTIVE,
    TILE_LOCKED_DOOR,
    TILE_NPC,
    TILE_DOOR,
    VIEWPORT_TILE_PASSABILITY,
    minimap_code_for_tile,
)
from ..memory.mgba import MgbaReadMetrics, _mgba_metrics_context, _try_mgba_read_ranges_bytes_no_fallback
from ..player import bag as player_bag
from ..player import party as player_party
from ..player import pc as player_pc
from ..player import snapshot as player_snapshot
from ..ui import battle as ui_battle
from ..ui import dialog as ui_dialog
from ..world import collision as world_collision
from ..world import events as world_events
from ..world import map_read as world_map_read
from ..world import viewport as world_viewport

_BENCH_ENABLED = True
_BENCH_LOGGER = logging.getLogger("firered_bridge.bench")
if _BENCH_ENABLED:
    _BENCH_LOGGER.setLevel(logging.INFO)
    if not _BENCH_LOGGER.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        _BENCH_LOGGER.addHandler(_handler)
    _BENCH_LOGGER.propagate = False

_BAG_CACHE_TTL_S = 0.8
_PC_CACHE_TTL_S = 1.5
_BAG_FORCE_REFRESH_MENU_TYPES = {
    "bagMenu",
    "itemStorageList",
    "itemStorageMenu",
}
_PC_FORCE_REFRESH_MENU_TYPES = {
    "pokemonStorage",
    "pokemonStoragePcMenu",
    "playerPcMenu",
    "itemStorageList",
    "itemStorageMenu",
}
_LAST_BAG_CACHE_KEY: int | None = None
_LAST_BAG_CACHE_TS: float = 0.0
_LAST_BAG_CACHE_STATE: Dict[str, Any] | None = None
_LAST_PC_CACHE_KEY: int | None = None
_LAST_PC_CACHE_TS: float = 0.0
_LAST_PC_CACHE_STATE: Dict[str, Any] | None = None
_LAST_DIALOG_CACHE_KEY: Tuple[int, int, int, bytes] | None = None
_LAST_DIALOG_CACHE_STATE: Dict[str, Any] | None = None

# Construction de l'objet complet (requestData)
# =============================================================================


def _movement_mode_for_player(*, diving: bool, surfing: bool, biking: bool, bike_type: str | None) -> str:
    if bool(diving):
        return "DIVE"
    if bool(surfing):
        return "SURF"
    if bool(biking):
        if isinstance(bike_type, str) and bike_type:
            return bike_type
        return "BIKE"
    return "WALK"


def build_full_state() -> Dict[str, Any]:
    global _LAST_BAG_CACHE_KEY, _LAST_BAG_CACHE_TS, _LAST_BAG_CACHE_STATE
    global _LAST_PC_CACHE_KEY, _LAST_PC_CACHE_TS, _LAST_PC_CACHE_STATE
    global _LAST_DIALOG_CACHE_KEY, _LAST_DIALOG_CACHE_STATE

    bench_enabled = _BENCH_ENABLED
    metrics_ctx = _mgba_metrics_context() if bench_enabled else nullcontext(None)
    with metrics_ctx as mgba_metrics:
        if bench_enabled:
            t0 = perf_counter()
            last = t0
            steps: List[Tuple[str, float]] = []
            stats: Dict[str, Any] = {}

            def mark(name: str) -> None:
                nonlocal last
                now = perf_counter()
                steps.append((name, (now - last) * 1000.0))
                last = now
        else:
            stats = {}

            def mark(_name: str) -> None:
                return

        snap = player_snapshot._read_player_snapshot()
        mark("player")

        in_battle = snap["in_battle"]
        field_locked = snap["field_locked"]

        x, y = snap["x"], snap["y"]
        facing = snap["facing"]
        elev = snap["elevation"]
        surfing = snap["surfing"]
        biking = snap["biking"]
        diving = snap["diving"]
        bike_type = snap.get("bike_type") if isinstance(snap.get("bike_type"), str) else None
        money = snap["money"]
        badges = snap["badges"]
        important_events = snap.get("important_events") if isinstance(snap.get("important_events"), dict) else {}

        map_group, map_num = snap["map_group"], snap["map_num"]
        map_name = game_data.get_map_name(map_group, map_num) or f"Unknown({map_group}-{map_num})"
        mark("map_meta")

        flash_needed, flash_active, strength_enabled = player_snapshot._read_flash_and_strength_state(
            sb1_ptr=snap.get("sb1_ptr")
        )
        visibility = player_snapshot._read_visibility_window_state(
            sb1_ptr=snap.get("sb1_ptr"),
            sb2_ptr=snap.get("sb2_ptr"),
            flash_needed=bool(flash_needed),
            flash_active=bool(flash_active),
        )

        ui_snapshot = _try_mgba_read_ranges_bytes_no_fallback(ui_dialog._DIALOG_SNAPSHOT_RANGES_EXT)
        ui_snapshot_by_addr: Dict[int, bytes] | None = None
        if ui_snapshot is not None:
            # NOTE: ui_snapshot follows ui_dialog._DIALOG_SNAPSHOT_RANGES_EXT. Do NOT rely on fixed
            # indices here; always map by address to avoid subtle mismatches when ranges change.
            ui_snapshot_by_addr = {
                int(addr): seg for (addr, _len), seg in zip(ui_dialog._DIALOG_SNAPSHOT_RANGES_EXT, ui_snapshot)
            }
        dialog_cache_hit = False
        if ui_snapshot is not None:
            # Strict dialog cache key based on full dialog snapshot bytes.
            # No heuristic aliasing: if RAM bytes differ, we recompute.
            sig = hashlib.blake2b(digest_size=16)
            snapshot_len = len(ui_dialog._DIALOG_SNAPSHOT_RANGES)
            for seg in ui_snapshot[:snapshot_len]:
                b = bytes(seg) if not isinstance(seg, bytes) else seg
                sig.update(len(b).to_bytes(4, "little", signed=False))
                sig.update(b)
            dialog_key = (
                int(snap.get("security_key") or 0),
                int(snap.get("sb1_ptr") or 0),
                int(snap.get("sb2_ptr") or 0),
                sig.digest(),
            )
            if _LAST_DIALOG_CACHE_KEY == dialog_key and _LAST_DIALOG_CACHE_STATE is not None:
                dialog_state = _LAST_DIALOG_CACHE_STATE
                dialog_cache_hit = True
            else:
                dialog_state = ui_dialog.get_dialog_state(
                    ui_snapshot,
                    sec_key=snap.get("security_key"),
                    sb1_ptr=snap.get("sb1_ptr"),
                    sb2_ptr=snap.get("sb2_ptr"),
                )
                _LAST_DIALOG_CACHE_KEY = dialog_key
                _LAST_DIALOG_CACHE_STATE = dialog_state
        else:
            dialog_state = ui_dialog.get_dialog_state(
                sec_key=snap.get("security_key"),
                sb1_ptr=snap.get("sb1_ptr"),
                sb2_ptr=snap.get("sb2_ptr"),
            )
            _LAST_DIALOG_CACHE_KEY = None
            _LAST_DIALOG_CACHE_STATE = None
        if bench_enabled:
            stats["dialog_cache"] = "hit" if dialog_cache_hit else "miss"
        mark("dialog")
        all_controls_locked = player_snapshot.are_all_controls_locked(
            field_controls_locked=field_locked,
            in_battle=in_battle,
            dialog_state=dialog_state,
        )
        if in_battle and ui_snapshot_by_addr is not None:
            battle_snapshot = [
                ui_snapshot_by_addr.get(GBATTLETYPEFLAGS_ADDR, b""),
                ui_snapshot_by_addr.get(GBATTLERSCOUNT_ADDR, b""),
                ui_snapshot_by_addr.get(GABSENTBATTLERFLAGS_ADDR, b""),
                ui_snapshot_by_addr.get(GBATTLERPOSITIONS_ADDR, b""),
                ui_snapshot_by_addr.get(GBATTLERPARTYINDEXES_ADDR, b""),
                ui_snapshot_by_addr.get(GBATTLEMONS_ADDR, b""),
                ui_snapshot_by_addr.get(GACTIVEBATTLER_ADDR, b""),
            ]
            if (
                len(battle_snapshot[0]) >= 4
                and len(battle_snapshot[1]) >= 1
                and len(battle_snapshot[2]) >= 1
                and len(battle_snapshot[3]) >= BATTLE_MAX_BATTLERS
                and len(battle_snapshot[4]) >= (BATTLE_MAX_BATTLERS * 2)
                and len(battle_snapshot[5]) >= GBATTLEMONS_SIZE
                and len(battle_snapshot[6]) >= 1
            ):
                battle = ui_battle.get_battle_state(in_battle=True, snapshot=battle_snapshot)
            else:
                battle = ui_battle.get_battle_state(in_battle=in_battle)
        else:
            battle = ui_battle.get_battle_state(in_battle=in_battle)
        mark("battle")

        # Main map
        (
            main_w,
            main_h,
            main_tiles,
            main_beh,
            backup_w,
            backup_h,
            backup_tiles,
        ) = world_map_read._read_map_tiles_and_behaviors_fast()
        if bench_enabled:
            stats.update(
                {
                    "main_w": main_w,
                    "main_h": main_h,
                    "main_tiles": len(main_tiles),
                    "main_beh": len(main_beh),
                    "backup_w": backup_w,
                    "backup_h": backup_h,
                    "backup_tiles": len(backup_tiles),
                }
            )
        mark("map_tiles")

        col_main = world_collision.process_tiles_to_collision_map(
            main_tiles,
            main_w,
            main_beh,
            elev,
            surfing,
            include_map_data=False,
        )
        mark("collision")
        npcs = world_events.get_current_map_npcs(map_group=map_group, map_num=map_num, sb1_ptr=snap.get("sb1_ptr"))
        bg_events = world_events.get_current_map_bg_events(map_group=map_group, map_num=map_num)
        warp_events = world_events.get_current_map_warp_events(map_group=map_group, map_num=map_num)
        connections = world_events.get_current_map_connections(map_group=map_group, map_num=map_num)
        if bench_enabled:
            stats.update(
                {
                    "npcs": len(npcs),
                    "bg_events": len(bg_events),
                    "warp_events": len(warp_events),
                    "connections": len(connections),
                }
            )
        mark("events")

        player_state = {
            "position": [x, y],
            "facing": facing,
            "elevation": elev,
            "surfing": surfing,
            "biking": biking,
            "diving": diving,
        }

        full_map_base = {
            "map_name": map_name,
            "width": col_main["width"],
            "height": col_main["height"],
            "tile_passability": col_main["tile_passability"],
            "map_data": col_main["map_data"],
            "minimap_data": col_main.get("minimap_data", {"grid": []}),
            "player_state": player_state,
            "npcs": npcs,
            "bg_events": bg_events,
            "warp_events": warp_events,
            "connections": connections,
        }

        viewport_width = int(visibility.get("widthTiles") or MAX_VIEWPORT_WIDTH)
        viewport_height = int(visibility.get("heightTiles") or MAX_VIEWPORT_HEIGHT)

        view_map = world_viewport.trim_map_to_viewport(
            full_map_base,
            (x, y),
            tile_values=main_tiles,
            behaviors=main_beh,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            backup_tiles=backup_tiles,
            backup_width=backup_w,
            backup_height=backup_h,
        )
        mark("view_map")

        full_map_data, full_map_codes, _fn, _fbg = world_viewport._render_map_region_with_overlays(
            full_map_base,
            0,
            0,
            int(full_map_base.get("width", 0) or 0),
            int(full_map_base.get("height", 0) or 0),
            tile_values=main_tiles,
            behaviors=main_beh,
            include_offscreen_npcs=True,
            return_filtered=False,
        )
        mark("full_map")

        fog_grid: fog_of_war.FogGrid | None = None
        try:
            fog_map_id = fog_of_war.map_id_for(map_group, map_num)
            map_w = int(full_map_base.get("width", 0) or 0)
            map_h = int(full_map_base.get("height", 0) or 0)

            view_minimap = view_map.get("minimap_data") if isinstance(view_map, dict) else None
            view_grid = (
                view_minimap.get("grid")
                if isinstance(view_minimap, dict) and isinstance(view_minimap.get("grid"), list)
                else []
            )
            view_h = len(view_grid) if isinstance(view_grid, list) else 0
            view_w = len(view_grid[0]) if view_h > 0 and isinstance(view_grid[0], list) else 0

            origin = view_minimap.get("origin") if isinstance(view_minimap, dict) else [0, 0]
            origin_x = int(origin[0]) if isinstance(origin, list) and len(origin) >= 1 else 0
            origin_y = int(origin[1]) if isinstance(origin, list) and len(origin) >= 2 else 0

            if map_w > 0 and map_h > 0:
                def _get_code(xx: int, yy: int) -> int:
                    return int(full_map_codes[yy][xx])

                def _updater(g: fog_of_war.FogGrid) -> None:
                    fog_of_war.refresh_discovered(g, _get_code)
                    if view_w > 0 and view_h > 0:
                        fog_of_war.discover_rect(
                            g,
                            start_x=origin_x,
                            start_y=origin_y,
                            end_x=origin_x + view_w,
                            end_y=origin_y + view_h,
                            map_width=map_w,
                            map_height=map_h,
                            get_code=_get_code,
                        )

                fog_grid = fog_of_war.update_grid(
                    map_id=fog_map_id,
                    width=map_w,
                    height=map_h,
                    persist=not bool(all_controls_locked),
                    updater=_updater,
                )
        except Exception:
            fog_grid = None

        minimap_grid_out = fog_grid if fog_grid is not None else full_map_codes
        map_data_out = full_map_data
        npcs_out = npcs
        bg_events_out = bg_events

        if fog_grid is not None and full_map_data:
            masked: List[List[str]] = []
            for yy, row in enumerate(full_map_data):
                out_row: List[str] = []
                for xx, cell in enumerate(row):
                    if 0 <= yy < len(fog_grid) and 0 <= xx < len(fog_grid[yy]) and fog_grid[yy][xx] is None:
                        if isinstance(cell, str) and ":" in cell:
                            coord, _t = cell.split(":", 1)
                            out_row.append(f"{coord}:❓")
                        else:
                            out_row.append(f"{xx},{yy}:❓")
                    else:
                        out_row.append(cell)
                masked.append(out_row)
            map_data_out = masked

            def _is_discovered_pos(pos: object) -> bool:
                if not (isinstance(pos, list) and len(pos) == 2):
                    return False
                try:
                    px = int(pos[0])
                    py = int(pos[1])
                except Exception:
                    return False
                return 0 <= py < len(fog_grid) and 0 <= px < len(fog_grid[py]) and fog_grid[py][px] is not None

            npcs_out = [n for n in npcs if _is_discovered_pos(n.get("position"))]
            bg_events_out = [bg for bg in bg_events if _is_discovered_pos(bg.get("position"))]

        full_map = dict(full_map_base)
        full_map["tile_passability"] = VIEWPORT_TILE_PASSABILITY
        full_map["map_data"] = map_data_out
        full_map["npcs"] = npcs_out
        full_map["bg_events"] = bg_events_out
        full_map["warp_events"] = warp_events
        full_map["minimap_data"] = {
            "grid": minimap_grid_out,
            "origin": [0, 0],
        }

        # Extract battle type overrides for active battlers (e.g. Color Change ability)
        battle_type_overrides: Dict[int, List[str]] = {}
        if in_battle and battle.get("isActive"):
            battle_data = battle.get("data", {})
            for side in ("player", "enemy"):
                for mon in battle_data.get(side, []):
                    if mon.get("side") == "player":
                        party_idx = int(mon.get("partyIndex", -1))
                        types = mon.get("types")
                        if 0 <= party_idx < PARTY_SIZE and isinstance(types, list) and types:
                            battle_type_overrides[party_idx] = types

        party_raw: bytes | None = None
        if ui_snapshot_by_addr is not None:
            raw = ui_snapshot_by_addr.get(PARTY_BASE_ADDR)
            expected = int(PARTY_SIZE) * int(POKEMON_DATA_SIZE)
            if isinstance(raw, (bytes, bytearray)) and len(raw) >= expected:
                party_raw = bytes(raw[:expected])

        party = player_party.get_party_data(
            party_raw=party_raw,
            battle_type_overrides=battle_type_overrides if battle_type_overrides else None,
        )
        mark("party")
        now_ts = perf_counter()
        menu_type = str(dialog_state.get("menuType") or "")

        sec_key_for_cache = int(snap.get("security_key") or 0)
        if sec_key_for_cache == 0 and _LAST_BAG_CACHE_KEY is not None:
            bag_key = int(_LAST_BAG_CACHE_KEY)
        else:
            bag_key = sec_key_for_cache
        bag_force_refresh = menu_type in _BAG_FORCE_REFRESH_MENU_TYPES or bool(in_battle)
        bag_cache_valid = (
            (not bag_force_refresh)
            and _LAST_BAG_CACHE_STATE is not None
            and _LAST_BAG_CACHE_KEY == bag_key
            and ((now_ts - float(_LAST_BAG_CACHE_TS)) <= float(_BAG_CACHE_TTL_S))
        )
        if bench_enabled:
            stats["bag_cache"] = "hit" if bag_cache_valid else "miss"
            stats["menu_type"] = menu_type or "none"
            stats["in_battle"] = int(bool(in_battle))
        if bag_cache_valid:
            bag = _LAST_BAG_CACHE_STATE
        else:
            bag = player_bag.get_bag_contents(snap.get("security_key"))
            if bag_key != 0:
                _LAST_BAG_CACHE_KEY = bag_key
            _LAST_BAG_CACHE_TS = now_ts
            _LAST_BAG_CACHE_STATE = bag
        mark("bag")

        sb1_for_cache = int(snap.get("sb1_ptr") or 0)
        if sb1_for_cache == 0 and _LAST_PC_CACHE_KEY is not None:
            pc_key = int(_LAST_PC_CACHE_KEY)
        else:
            pc_key = sb1_for_cache
        pc_force_refresh = menu_type in _PC_FORCE_REFRESH_MENU_TYPES
        pc_cache_valid = (
            (not pc_force_refresh)
            and _LAST_PC_CACHE_STATE is not None
            and _LAST_PC_CACHE_KEY == pc_key
            and ((now_ts - float(_LAST_PC_CACHE_TS)) <= float(_PC_CACHE_TTL_S))
        )
        if bench_enabled:
            stats["pc_cache"] = "hit" if pc_cache_valid else "miss"
        if pc_cache_valid:
            pc = _LAST_PC_CACHE_STATE
        else:
            pc = player_pc.get_pc_state(sb1_ptr=snap.get("sb1_ptr"))
            if pc_key != 0:
                _LAST_PC_CACHE_KEY = pc_key
            _LAST_PC_CACHE_TS = now_ts
            _LAST_PC_CACHE_STATE = pc
        mark("pc")

        if bench_enabled:
            if mgba_metrics is not None:
                mgba_total_calls = (
                    mgba_metrics.read8_calls
                    + mgba_metrics.read16_calls
                    + mgba_metrics.read32_calls
                    + mgba_metrics.read_range_calls
                    + mgba_metrics.read_ranges_calls
                    + mgba_metrics.read_range_bytes_calls
                    + mgba_metrics.read_ranges_bytes_calls
                )
                stats.update(
                    {
                        "mgba_calls": mgba_total_calls,
                        "mgba_ranges": mgba_metrics.ranges_read,
                        "mgba_bytes_req": mgba_metrics.bytes_requested,
                        "mgba_bytes_ret": mgba_metrics.bytes_returned,
                        "mgba_read8": mgba_metrics.read8_calls,
                        "mgba_read16": mgba_metrics.read16_calls,
                        "mgba_read32": mgba_metrics.read32_calls,
                        "mgba_read_range": mgba_metrics.read_range_calls,
                        "mgba_read_ranges": mgba_metrics.read_ranges_calls,
                        "mgba_read_range_bytes": mgba_metrics.read_range_bytes_calls,
                        "mgba_read_ranges_bytes": mgba_metrics.read_ranges_bytes_calls,
                    }
                )

            total_ms = (perf_counter() - t0) * 1000.0
            steps_str = ",".join(f"{name}={ms:.1f}ms" for name, ms in steps)
            stats_str = ",".join(f"{k}={v}" for k, v in stats.items())
            _BENCH_LOGGER.info("bench build_full_state total=%.1fms %s %s", total_ms, steps_str, stats_str)

        return {
            "gameVersion": "FIRERED",
            "importantEvents": important_events,
            "emulator": {
                "mgbaApiUrl": MGBA_API_URL,
                "inBattle": in_battle,
                "fieldControlsLocked": field_locked,
                "allControlsLocked": bool(all_controls_locked),
            },
            "battle": battle,
            "player": {
                "position": [x, y],
                "facing": facing,
                "elevation": elev,
                "surfing": surfing,
                "biking": biking,
                "bikeType": bike_type,
                "diving": diving,
                "movementMode": _movement_mode_for_player(
                    diving=bool(diving),
                    surfing=bool(surfing),
                    biking=bool(biking),
                    bike_type=bike_type,
                ),
                "strengthEnabled": bool(strength_enabled),
                "safariZoneStepsRemaining": int(snap.get("safari_zone_steps_remaining") or 0),
                "safariZoneActive": bool(snap.get("safari_zone_active")),
                "money": money,
                "badges": badges,
            },
            "map": {
                "group": map_group,
                "number": map_num,
            "name": map_name,
            "minimap_legend": MINIMAP_LEGEND,  # dérivé de MINIMAP_TILES
            "flashNeeded": bool(flash_needed),
            "flashActive": bool(flash_active),
            "visibility": visibility,
            "viewMap": view_map,
            "fullMap": full_map,
            "connections": connections,
        },
            "dialog": dialog_state,
            "party": party,
            "bag": bag,
            "pc": pc,
        }


def build_input_trace_state() -> Dict[str, Any]:
    """
    Lightweight state snapshot for input tracing.

    Intended for `/sendCommands` so we can report "before/after" per input without
    computing full maps, party, bag, etc.
    """
    snap = player_snapshot._read_player_snapshot()
    map_group, map_num = snap["map_group"], snap["map_num"]
    map_name = game_data.get_map_name(map_group, map_num) or f"Unknown({map_group}-{map_num})"
    dialog_state = ui_dialog.get_dialog_state(sb1_ptr=snap.get("sb1_ptr"), sb2_ptr=snap.get("sb2_ptr"))
    all_controls_locked = player_snapshot.are_all_controls_locked(
        field_controls_locked=snap.get("field_locked"),
        in_battle=snap.get("in_battle"),
        dialog_state=dialog_state,
    )

    return {
        "gameVersion": "FIRERED",
        "emulator": {
            "mgbaApiUrl": MGBA_API_URL,
            "inBattle": snap["in_battle"],
            "fieldControlsLocked": snap["field_locked"],
            "allControlsLocked": bool(all_controls_locked),
        },
        "player": {
            "position": [snap["x"], snap["y"]],
            "facing": snap["facing"],
            "elevation": snap["elevation"],
            "surfing": snap["surfing"],
            "biking": snap["biking"],
            "diving": snap["diving"],
        },
        "map": {
            "group": map_group,
            "number": map_num,
            "name": map_name,
        },
        "dialog": dialog_state,
    }


def update_fog_of_war_for_current_map(
    *,
    discovered_out: List[Tuple[int, int]] | None = None,
    walls_to_free_out: List[Tuple[int, int]] | None = None,
    free_to_walls_out: List[Tuple[int, int]] | None = None,
) -> tuple[fog_of_war.FogGrid, Dict[str, Any]] | None:
    """
    Update the persistent fog-of-war grid for the current map.

    Intended for `/sendCommands`: call after each input so long sequences (e.g. right x50)
    discover tiles progressively instead of only at the final position.

    If `discovered_out` is provided, newly discovered (x, y) map tile positions
    (fog cell `None` -> code) are appended to that list.

    If `walls_to_free_out` / `free_to_walls_out` are provided, (x, y) map tile
    positions are appended when a discovered minimap tile changes from
    wall->ground (0->1) or ground->wall (1->0).

    """
    snap = player_snapshot._read_player_snapshot()
    # Keep fog updates active while a dialog is open so scripted map edits triggered by
    # A-presses (setmetatile barriers/switches) are reported in /sendCommands traces.
    # We still skip hard transition locks (warp/fade/map-load) where reads are transient.
    dialog_state: Dict[str, Any] | None = None
    try:
        dialog_state = ui_dialog.get_dialog_state(sb1_ptr=snap.get("sb1_ptr"), sb2_ptr=snap.get("sb2_ptr"))
    except Exception:
        dialog_state = None

    in_dialog = bool(dialog_state.get("inDialog")) if isinstance(dialog_state, dict) else False
    if (
        player_snapshot.are_all_controls_locked(
            field_controls_locked=snap.get("field_locked"),
            in_battle=snap.get("in_battle"),
            dialog_state=dialog_state,
        )
        and not in_dialog
    ):
        return None

    map_group, map_num = snap["map_group"], snap["map_num"]
    map_name = game_data.get_map_name(map_group, map_num) or f"Unknown({map_group}-{map_num})"

    x, y = snap["x"], snap["y"]
    elev = snap["elevation"]
    surfing = snap["surfing"]

    flash_needed, flash_active = player_snapshot._read_flash_state(sb1_ptr=snap.get("sb1_ptr"))
    visibility = player_snapshot._read_visibility_window_state(
        sb1_ptr=snap.get("sb1_ptr"),
        sb2_ptr=snap.get("sb2_ptr"),
        flash_needed=bool(flash_needed),
        flash_active=bool(flash_active),
    )
    viewport_width = int(visibility.get("widthTiles") or MAX_VIEWPORT_WIDTH)
    viewport_height = int(visibility.get("heightTiles") or MAX_VIEWPORT_HEIGHT)

    main_w, main_h, main_tiles, main_beh, _bw, _bh, _bt = world_map_read._read_map_tiles_and_behaviors_fast()
    if main_w <= 0 or main_h <= 0 or not main_tiles:
        return None

    col_main = world_collision.process_tiles_to_collision_map(
        main_tiles,
        main_w,
        main_beh,
        elev,
        surfing,
        include_map_data=False,
    )
    base_grid: List[List[int]] = (
        col_main.get("minimap_data", {}).get("grid", []) if isinstance(col_main.get("minimap_data"), dict) else []
    )
    map_w = int(col_main.get("width", 0) or 0)
    map_h = int(col_main.get("height", 0) or 0)
    if map_w <= 0 or map_h <= 0 or not base_grid:
        return None

    if main_beh and main_tiles:
        _init_behavior_id_tables()
        has_behavior_snapshot = True
    else:
        has_behavior_snapshot = False

    npcs = world_events.get_current_map_npcs(map_group=map_group, map_num=map_num, sb1_ptr=snap.get("sb1_ptr"))
    bg_events = world_events.get_current_map_bg_events()
    warp_events = world_events.get_current_map_warp_events()

    # Build overlay lookup tables (same logic as `_render_map_region_with_overlays`, but per-cell).
    object_locs: Dict[str, str] = {}
    for n in npcs:
        pos = n.get("position")
        if not (pos and len(pos) == 2):
            continue
        coord = f"{pos[0]},{pos[1]}"
        obj_type = str(n.get("type") or "")
        object_locs[coord] = OBJECT_EVENT_TILE_BY_TYPE.get(obj_type, TILE_NPC)

    bg_interactive_locs: Dict[str, str] = {}
    silph_co_door_bg_coords: set[str] = set()
    for bg in bg_events:
        pos = bg.get("position")
        if not (pos and len(pos) == 2):
            continue
        coord = f"{pos[0]},{pos[1]}"
        bg_interactive_locs[coord] = TILE_INTERACTIVE
        script_addr = int(bg.get("scriptAddr") or 0)
        if is_silph_co_door_bg_event(map_name=str(map_name or ""), script_addr=script_addr):
            silph_co_door_bg_coords.add(coord)

    warp_locs: set[str] = set()
    for warp in warp_events:
        pos = warp.get("position")
        if not (pos and len(pos) == 2):
            continue
        warp_locs.add(f"{pos[0]},{pos[1]}")

    temporary_wall_locs: Dict[str, str] = TEMPORARY_WALL_TILES_BY_MAP.get(str(map_name or ""), {})

    tv = main_tiles
    beh = main_beh or []
    tv_len = len(tv)
    beh_len = len(beh)

    # Door overlays derived from arrow warps.
    # FireRed-specific: include red-carpet exits (DOWN from SOUTH_ARROW_WARP)
    # when the destination tile is a collision wall.
    adjacent_door_locs: set[str] = set()
    if has_behavior_snapshot and ARROW_WARP_DELTA_BY_BEHAVIOR_ID:
        total = min(tv_len, map_w * map_h)
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
            if beh_id in RED_CARPET_BEHAVIOR_IDS and (dx != 0 or dy != 1):
                continue

            x0 = i % map_w
            y0 = i // map_w
            tx = x0 + dx
            ty = y0 + dy
            if not (0 <= tx < map_w and 0 <= ty < map_h):
                continue
            ti = ty * map_w + tx
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
        total = min(tv_len, map_w * map_h)
        for i in range(total):
            metatile_id = tv[i] & MAPGRID_METATILE_ID_MASK
            if metatile_id >= beh_len:
                continue
            beh_id = beh[metatile_id]
            delta = STAIR_WARP_DELTA_BY_BEHAVIOR_ID.get(beh_id)
            if delta is None:
                continue
            x0 = i % map_w
            y0 = i // map_w
            dx, dy = delta
            tx = x0 + dx
            ty = y0 + dy
            if not (0 <= tx < map_w and 0 <= ty < map_h):
                continue
            stair_source_locs.add(f"{x0},{y0}")
            stair_target_locs.add(f"{tx},{ty}")

    def _code_at(map_x: int, map_y: int) -> int:
        coord = f"{map_x},{map_y}"
        if coord in object_locs:
            return minimap_code_for_tile(object_locs[coord], default_code=MINIMAP_CODE_NPC)

        beh_id = -1
        metatile_id = -1
        if has_behavior_snapshot:
            idx = map_y * map_w + map_x
            if 0 <= idx < tv_len:
                metatile_id = int(tv[idx] & MAPGRID_METATILE_ID_MASK)
                if 0 <= metatile_id < beh_len:
                    beh_id = beh[metatile_id]

        interactive_tile: str | None = bg_interactive_locs.get(coord)
        if beh_id != -1 and beh_id in INTERACTIVE_METATILE_BEHAVIOR_IDS:
            interactive_tile = INTERACTIVE_METATILE_TILE_BY_BEHAVIOR_ID.get(beh_id, TILE_INTERACTIVE)

        # Base terrain code
        try:
            base_code = int(base_grid[map_y][map_x])
        except Exception:
            base_code = MINIMAP_CODE_WALL

        is_locked_silph_door = (
            metatile_id != -1
            and is_silph_co_locked_door_metatile(map_name=str(map_name or ""), metatile_id=metatile_id)
        )

        code = base_code
        if is_locked_silph_door:
            code = minimap_code_for_tile(TILE_LOCKED_DOOR, default_code=MINIMAP_CODE_LOCKED_DOOR)
        elif interactive_tile is not None:
            # Silph Co Card Key doors keep BG events even when opened by script.
            # If the barrier metatile is gone and base tile is passable, expose
            # the base terrain instead of an interactive marker.
            if coord in silph_co_door_bg_coords and base_code not in (
                MINIMAP_CODE_WALL,
                MINIMAP_CODE_TEMPORARY_WALL,
            ):
                code = int(base_code)
            else:
                code = minimap_code_for_tile(interactive_tile, default_code=MINIMAP_CODE_INTERACTIVE)
        elif coord in temporary_wall_locs and base_code == MINIMAP_CODE_WALL:
            code = minimap_code_for_tile(temporary_wall_locs[coord], default_code=MINIMAP_CODE_WALL)

        # Door overlays from arrow-warp/red-carpet adjacency have highest priority.
        if coord in adjacent_door_locs:
            return MINIMAP_CODE_DOOR
        if coord in stair_target_locs:
            return MINIMAP_CODE_STAIRS
        if coord in stair_source_locs:
            return MINIMAP_CODE_RED_CARPET

        # Warp visuals (derived from metatile behaviors; no warp events)
        if (
            beh_id != -1
            and not is_locked_silph_door
            and beh_id not in RED_CARPET_BEHAVIOR_IDS
            and beh_id not in ARROW_WARP_DELTA_BY_BEHAVIOR_ID
        ):
            warp_tile = WARP_VISUAL_TILE_BY_BEHAVIOR_ID.get(beh_id)
            if warp_tile:
                if (
                    warp_tile == TILE_DOOR
                    and coord not in warp_locs
                    and coord not in adjacent_door_locs
                ):
                    code = MINIMAP_CODE_INTERACTIVE
                else:
                    code = minimap_code_for_tile(warp_tile, default_code=MINIMAP_CODE_WARP)
        elif (
            coord in warp_locs
            and not is_locked_silph_door
            and beh_id not in RED_CARPET_BEHAVIOR_IDS
            and beh_id not in ARROW_WARP_DELTA_BY_BEHAVIOR_ID
        ):
            # Warp-event fallback:
            # - blocked underlying tile + interactive/bg event (wall hole) => door
            # - otherwise, keep legacy walkable-only warp overlay.
            if base_code == MINIMAP_CODE_WALL and interactive_tile is not None:
                code = MINIMAP_CODE_DOOR
            elif code not in (MINIMAP_CODE_WALL, MINIMAP_CODE_TEMPORARY_WALL, MINIMAP_CODE_LOCKED_DOOR):
                code = MINIMAP_CODE_WARP

        return int(code)

    half_w = int(viewport_width) // 2
    half_h = int(viewport_height) // 2
    start_x = int(x) - half_w
    start_y = int(y) - half_h
    end_x = start_x + int(viewport_width)
    end_y = start_y + int(viewport_height)

    fog_map_id = fog_of_war.map_id_for(map_group, map_num)

    discovered = discovered_out if discovered_out is not None else []
    walls_to_free = walls_to_free_out if walls_to_free_out is not None else []
    free_to_walls = free_to_walls_out if free_to_walls_out is not None else []
    fog_info: Dict[str, Any] = {}

    def _is_passable_code(code: int) -> bool:
        td = MINIMAP_TILES.get(int(code))
        if td is not None:
            return bool(td.passability)
        # Fallback for unknown codes: keep legacy "wall-like" behavior only for explicit blockers.
        return int(code) not in {
            MINIMAP_CODE_WALL,
            MINIMAP_CODE_TEMPORARY_WALL,
            MINIMAP_CODE_NPC,
            MINIMAP_CODE_BOULDER,
        }

    def _on_change(xx: int, yy: int, old: int, new: int) -> None:
        old_i = int(old)
        new_i = int(new)
        old_passable = _is_passable_code(old_i)
        new_passable = _is_passable_code(new_i)

        # Passability transitions (blocked <-> free), regardless of exact minimap code id.
        if (not old_passable) and new_passable:
            walls_to_free.append((int(xx), int(yy)))
        elif old_passable and (not new_passable):
            free_to_walls.append((int(xx), int(yy)))

    def _updater(g: fog_of_war.FogGrid) -> None:
        fog_of_war.refresh_discovered(g, _code_at, on_change=_on_change)
        fog_of_war.discover_rect(
            g,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            map_width=map_w,
            map_height=map_h,
            get_code=_code_at,
            on_discover=lambda xx, yy: discovered.append((int(xx), int(yy))),
        )

    grid = fog_of_war.update_grid(
        map_id=fog_map_id,
        width=map_w,
        height=map_h,
        updater=_updater,
        out_info=fog_info,
    )
    if bool(fog_info.get("shape_mismatch")):
        # Avoid reporting spurious "discoveries" during transient map dimension reads.
        discovered.clear()
        walls_to_free.clear()
        free_to_walls.clear()
    return (grid, visibility)
