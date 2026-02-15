from __future__ import annotations

from typing import Dict, Tuple

from ..game_data import get_behavior_name
from ..memory.symbols import sym_addr
from .tiles import *  # re-exported tile ids for behavior mapping

# Metatile behaviors / règles de classification
# =============================================================================

# NOTE: Keep FireRed grass detection aligned with metatile_behavior.c.
GRASS_BEHAVIOR_NAMES = {"TALL_GRASS", "CYCLING_ROAD_PULL_DOWN_GRASS"}
THIN_ICE_BEHAVIOR_NAMES = {"ICE", "THIN_ICE"}
CRACKED_ICE_BEHAVIOR_NAMES = {"CRACKED_ICE"}
# FireRed: MetatileBehavior_IsCrackedFloor() returns FALSE.
CRACKED_FLOOR_BEHAVIOR_NAMES: set[str] = set()

# FireRed: MetatileBehavior_IsDiveable => FAST_WATER..DEEP_WATER.
DIVEABLE_WATER_BEHAVIOR_NAMES = {"FAST_WATER", "DEEP_WATER"}

# FireRed has no dedicated "red carpet" metatile behavior id. Indoor exits that behave
# like FireRed red-carpet warps are encoded as SOUTH_ARROW_WARP (ex: house entrances).
RED_CARPET_BEHAVIOR_NAMES: set[str] = {"SOUTH_ARROW_WARP"}

# Interactive metatiles (specific, visible "press A" objects) used by
# pokefirered/src/field_control_avatar.c:GetInteractedMetatileScript.
INTERACTIVE_METATILE_BEHAVIOR_NAMES = {
    "PC",
    "REGION_MAP",
    "BOOKSHELF",
    "POKEMART_SHELF",
    "FOOD",
    "IMPRESSIVE_MACHINE",
    "BLUEPRINTS",
    "VIDEO_GAME",
    "BURGLARY",
    "COMPUTER",
    "TRAINER_TOWER_MONITOR",
    "TELEVISION",
    "CABINET",
    "KITCHEN",
    "DRESSER",
    "SNACKS",
    "PAINTING",
    "POWER_PLANT_MACHINE",
    "TELEPHONE",
    "ADVERTISING_POSTER",
    "FOOD_SMELLS_TASTY",
    "TRASH_BIN",
    "CUP",
    "BLINKING_LIGHTS",
    "NEATLY_LINED_UP_TOOLS",
    "CABLE_CLUB_WIRELESS_MONITOR",
    "QUESTIONNAIRE",
    "BATTLE_RECORDS",
    "INDIGO_PLATEAU_SIGN_1",
    "INDIGO_PLATEAU_SIGN_2",
    "POKEMART_SIGN",
    "POKEMON_CENTER_SIGN",
}

INTERACTIVE_METATILE_TILE_BY_BEHAVIOR = {
    "PC": TILE_PC,
    "REGION_MAP": TILE_REGION_MAP,
    "TELEVISION": TILE_TELEVISION,
    "BOOKSHELF": TILE_BOOKSHELF,
    "POKEMART_SHELF": TILE_SHOP_SHELF,
    "TRASH_BIN": TILE_TRASH_CAN,
}

MAX_VIEWPORT_WIDTH = 15
MAX_VIEWPORT_HEIGHT = 10

LEDGE_DIRECTIONS = {
    "JUMP_EAST": TILE_LEDGE_EAST,
    "JUMP_WEST": TILE_LEDGE_WEST,
    "JUMP_NORTH": TILE_LEDGE_NORTH,
    "JUMP_SOUTH": TILE_LEDGE_SOUTH,
}
WATERFALL_TILE_NAME = "WATERFALL"

# Warp visuals (replace generic warp icon by a grouped, visual tile)
WARP_VISUAL_DOOR_BEHAVIORS = {
    "CAVE_DOOR",
    "WARP_DOOR",
}
WARP_VISUAL_ESCALATOR_BEHAVIORS = {"UP_ESCALATOR", "DOWN_ESCALATOR"}
WARP_VISUAL_LADDER_BEHAVIORS = {"LADDER"}
WARP_VISUAL_HOLE_BEHAVIORS = {"FALL_WARP"}
WARP_VISUAL_STAIRS_BEHAVIORS = {
    "UP_RIGHT_STAIR_WARP",
    "UP_LEFT_STAIR_WARP",
    "DOWN_RIGHT_STAIR_WARP",
    "DOWN_LEFT_STAIR_WARP",
}
WARP_VISUAL_ENTRANCE_BEHAVIORS: set[str] = set()
WARP_VISUAL_ARROW_BEHAVIORS = {
    "EAST_ARROW_WARP",
    "WEST_ARROW_WARP",
    "NORTH_ARROW_WARP",
    "SOUTH_ARROW_WARP",
}
WARP_VISUAL_PAD_BEHAVIORS = {
    "LAVARIDGE_1F_WARP",
    "REGULAR_WARP",
    "UNION_ROOM_WARP",
}

WARP_VISUAL_TILE_BY_BEHAVIOR: Dict[str, str] = {
    **{b: TILE_DOOR for b in WARP_VISUAL_DOOR_BEHAVIORS},
    **{b: TILE_ESCALATOR for b in WARP_VISUAL_ESCALATOR_BEHAVIORS},
    **{b: TILE_LADDER for b in WARP_VISUAL_LADDER_BEHAVIORS},
    **{b: TILE_HOLE for b in WARP_VISUAL_HOLE_BEHAVIORS},
    **{b: TILE_STAIRS for b in WARP_VISUAL_STAIRS_BEHAVIORS},
    **{b: TILE_ENTRANCE for b in WARP_VISUAL_ENTRANCE_BEHAVIORS},
    **{b: TILE_WARP_ARROW for b in WARP_VISUAL_ARROW_BEHAVIORS},
    **{b: TILE_WARP for b in WARP_VISUAL_PAD_BEHAVIORS},
}

# Directional stair-warp visual correction:
# - RIGHT stairs are rendered one tile to the left.
# - LEFT stairs are rendered one tile to the right.
# The original behavior tile is then treated as red-carpet/entry floor.
STAIR_WARP_DELTA_BY_BEHAVIOR: Dict[str, Tuple[int, int]] = {
    "UP_RIGHT_STAIR_WARP": (1, 0),
    "DOWN_RIGHT_STAIR_WARP": (1, 0),
    "UP_LEFT_STAIR_WARP": (-1, 0),
    "DOWN_LEFT_STAIR_WARP": (-1, 0),
}

# Arrow-warps (special-case visuals for cave exits / ledges into walls)
#
# Some arrow-warp tiles face an adjacent collision tile (ex: cave exit rocks).
# We mark that adjacent collision tile as a door overlay.
ARROW_WARP_DELTA_BY_BEHAVIOR: Dict[str, Tuple[int, int]] = {
    "EAST_ARROW_WARP": (1, 0),
    "WEST_ARROW_WARP": (-1, 0),
    "NORTH_ARROW_WARP": (0, -1),
    "SOUTH_ARROW_WARP": (0, 1),
}

ARROW_WARP_DELTA_BY_BEHAVIOR_ID: Dict[int, Tuple[int, int]] = {}
STAIR_WARP_DELTA_BY_BEHAVIOR_ID: Dict[int, Tuple[int, int]] = {}

# Forced movement arrows (Walk/Slide tiles).
#
# These tiles push the player one step in the arrow direction and effectively prevent moving
# against the flow (field_player_avatar.c: GetForcedMovementByMetatileBehavior()).
FORCED_MOVEMENT_ARROW_TILE_BY_BEHAVIOR: Dict[str, str] = {
    "WALK_EAST": TILE_ARROW_FLOOR_RIGHT,
    "WALK_WEST": TILE_ARROW_FLOOR_LEFT,
    "WALK_NORTH": TILE_ARROW_FLOOR_UP,
    "WALK_SOUTH": TILE_ARROW_FLOOR_DOWN,
    "SLIDE_EAST": TILE_ARROW_FLOOR_RIGHT,
    "SLIDE_WEST": TILE_ARROW_FLOOR_LEFT,
    "SLIDE_NORTH": TILE_ARROW_FLOOR_UP,
    "SLIDE_SOUTH": TILE_ARROW_FLOOR_DOWN,
}

# Water currents (surfable forced movement).
WATER_CURRENT_TILE_BY_BEHAVIOR: Dict[str, str] = {
    "EASTWARD_CURRENT": TILE_WATER_CURRENT_RIGHT,
    "WESTWARD_CURRENT": TILE_WATER_CURRENT_LEFT,
    "NORTHWARD_CURRENT": TILE_WATER_CURRENT_UP,
    "SOUTHWARD_CURRENT": TILE_WATER_CURRENT_DOWN,
}

# Directional edge collisions on otherwise walkable tiles.
# These are not full walls: only specific edges are blocked by movement checks.
DIRECTIONAL_IMPASSABLE_TILE_BY_BEHAVIOR: Dict[str, str] = {
    "IMPASSABLE_NORTH": TILE_WALKABLE_BLOCK_NORTH,
    "IMPASSABLE_SOUTH": TILE_WALKABLE_BLOCK_SOUTH,
    "IMPASSABLE_EAST": TILE_WALKABLE_BLOCK_EAST,
    "IMPASSABLE_WEST": TILE_WALKABLE_BLOCK_WEST,
    "IMPASSABLE_NORTHEAST": TILE_WALKABLE_BLOCK_NORTHEAST,
    "IMPASSABLE_NORTHWEST": TILE_WALKABLE_BLOCK_NORTHWEST,
    "IMPASSABLE_SOUTHEAST": TILE_WALKABLE_BLOCK_SOUTHEAST,
    "IMPASSABLE_SOUTHWEST": TILE_WALKABLE_BLOCK_SOUTHWEST,
}

# Spinner tiles (Viridian Gym panels).
SPINNER_TILE_BY_BEHAVIOR: Dict[str, str] = {
    "SPIN_RIGHT": TILE_SPINNER_RIGHT,
    "SPIN_LEFT": TILE_SPINNER_LEFT,
    "SPIN_UP": TILE_SPINNER_UP,
    "SPIN_DOWN": TILE_SPINNER_DOWN,
    "STOP_SPINNING": TILE_STOP_SPINNER,
}

# Victory Road style boulder floor switches.
STRENGTH_SWITCH_TILE_BY_BEHAVIOR: Dict[str, str] = {
    "STRENGTH_BUTTON": TILE_STRENGTH_SWITCH,
}

DEEP_WATER_TILES = {"FAST_WATER", "DEEP_WATER", "OCEAN_WATER"}
SURFABLE_WATER_TILES = {
    "POND_WATER",
    "FAST_WATER",
    "DEEP_WATER",
    "WATERFALL",
    "OCEAN_WATER",
    "UNUSED_WATER",
    "CYCLING_ROAD_WATER",
    *set(WATER_CURRENT_TILE_BY_BEHAVIOR.keys()),
}
WALKABLE_WATER_TILES = {"SHALLOW_WATER", "PUDDLE"}

# -----------------------------------------------------------------------------
# Behavior IDs (static tables)
#
# We avoid converting behavior_id -> name inside hot loops (map collision/overlays).
# These tables are derived once from `get_behavior_name()` and remain valid across
# requests (no dynamic state cached).
# -----------------------------------------------------------------------------

_BEHAVIOR_ID_TABLES_READY = False
_BEHAVIOR_ID_BY_NAME: Dict[str, int] = {}

GRASS_BEHAVIOR_IDS: set[int] = set()
RED_CARPET_BEHAVIOR_IDS: set[int] = set()
SURFABLE_WATER_BEHAVIOR_IDS: set[int] = set()
DIVEABLE_WATER_BEHAVIOR_IDS: set[int] = set()
INTERACTIVE_METATILE_BEHAVIOR_IDS: set[int] = set()
THIN_ICE_BEHAVIOR_IDS: set[int] = set()
CRACKED_ICE_BEHAVIOR_IDS: set[int] = set()
CRACKED_FLOOR_BEHAVIOR_IDS: set[int] = set()

LEDGE_BEHAVIOR_ID_TO_TILE: Dict[int, str] = {}
FORCED_MOVEMENT_ARROW_BEHAVIOR_ID_TO_TILE: Dict[int, str] = {}
WATER_CURRENT_BEHAVIOR_ID_TO_TILE: Dict[int, str] = {}
DIRECTIONAL_IMPASSABLE_BEHAVIOR_ID_TO_TILE: Dict[int, str] = {}
SPINNER_BEHAVIOR_ID_TO_TILE: Dict[int, str] = {}
STRENGTH_SWITCH_BEHAVIOR_ID_TO_TILE: Dict[int, str] = {}
WATERFALL_BEHAVIOR_ID: int = -1

WARP_VISUAL_TILE_BY_BEHAVIOR_ID: Dict[int, str] = {}
INTERACTIVE_METATILE_TILE_BY_BEHAVIOR_ID: Dict[int, str] = {}


def _init_behavior_id_tables() -> None:
    global _BEHAVIOR_ID_TABLES_READY, WATERFALL_BEHAVIOR_ID
    if _BEHAVIOR_ID_TABLES_READY:
        return
    _BEHAVIOR_ID_TABLES_READY = True

    # Build name -> id from the canonical id -> name mapping.
    for bid in range(256):
        name = get_behavior_name(bid)
        if not name:
            continue
        _BEHAVIOR_ID_BY_NAME.setdefault(name, bid)

    def _ids(names: set[str]) -> set[int]:
        return {bid for n in names if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None}

    GRASS_BEHAVIOR_IDS.update(_ids(GRASS_BEHAVIOR_NAMES))
    RED_CARPET_BEHAVIOR_IDS.update(_ids(RED_CARPET_BEHAVIOR_NAMES))
    SURFABLE_WATER_BEHAVIOR_IDS.update(_ids(SURFABLE_WATER_TILES))
    DIVEABLE_WATER_BEHAVIOR_IDS.update(_ids(DIVEABLE_WATER_BEHAVIOR_NAMES))
    INTERACTIVE_METATILE_BEHAVIOR_IDS.update(_ids(INTERACTIVE_METATILE_BEHAVIOR_NAMES))
    THIN_ICE_BEHAVIOR_IDS.update(_ids(THIN_ICE_BEHAVIOR_NAMES))
    CRACKED_ICE_BEHAVIOR_IDS.update(_ids(CRACKED_ICE_BEHAVIOR_NAMES))
    CRACKED_FLOOR_BEHAVIOR_IDS.update(_ids(CRACKED_FLOOR_BEHAVIOR_NAMES))

    LEDGE_BEHAVIOR_ID_TO_TILE.update(
        {bid: tile for n, tile in LEDGE_DIRECTIONS.items() if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None}
    )
    WATERFALL_BEHAVIOR_ID = _BEHAVIOR_ID_BY_NAME.get(WATERFALL_TILE_NAME, -1)

    WARP_VISUAL_TILE_BY_BEHAVIOR_ID.update(
        {bid: tile for n, tile in WARP_VISUAL_TILE_BY_BEHAVIOR.items() if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None}
    )
    ARROW_WARP_DELTA_BY_BEHAVIOR_ID.update(
        {
            bid: delta
            for n, delta in ARROW_WARP_DELTA_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )
    STAIR_WARP_DELTA_BY_BEHAVIOR_ID.update(
        {
            bid: delta
            for n, delta in STAIR_WARP_DELTA_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )
    INTERACTIVE_METATILE_TILE_BY_BEHAVIOR_ID.update(
        {
            bid: tile
            for n, tile in INTERACTIVE_METATILE_TILE_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )
    FORCED_MOVEMENT_ARROW_BEHAVIOR_ID_TO_TILE.update(
        {
            bid: tile
            for n, tile in FORCED_MOVEMENT_ARROW_TILE_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )
    WATER_CURRENT_BEHAVIOR_ID_TO_TILE.update(
        {bid: tile for n, tile in WATER_CURRENT_TILE_BY_BEHAVIOR.items() if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None}
    )
    DIRECTIONAL_IMPASSABLE_BEHAVIOR_ID_TO_TILE.update(
        {
            bid: tile
            for n, tile in DIRECTIONAL_IMPASSABLE_TILE_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )
    SPINNER_BEHAVIOR_ID_TO_TILE.update(
        {
            bid: tile
            for n, tile in SPINNER_TILE_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )
    STRENGTH_SWITCH_BEHAVIOR_ID_TO_TILE.update(
        {
            bid: tile
            for n, tile in STRENGTH_SWITCH_TILE_BY_BEHAVIOR.items()
            if (bid := _BEHAVIOR_ID_BY_NAME.get(n)) is not None
        }
    )

# Silph Co locked security doors (Card Key).
#
# Source: pokefirered/include/constants/metatile_labels.h
#  - METATILE_SilphCo_HorizontalBarrier_* (0x3B0/0x3B1/0x3B8/0x3B9)
#  - METATILE_SilphCo_VerticalBarrier_*   (0x3C0..0x3C5)
#
# These metatiles are used by scripts in pokefirered/data/scripts/silphco_doors.inc
# for the closed-door state.
SILPH_CO_LOCKED_DOOR_METATILE_IDS: set[int] = {
    0x3B0,  # HorizontalBarrier_TopLeft
    0x3B1,  # HorizontalBarrier_TopRight
    0x3B8,  # HorizontalBarrier_BottomLeft
    0x3B9,  # HorizontalBarrier_BottomRight
    0x3C0,  # VerticalBarrier_TopLeft
    0x3C1,  # VerticalBarrier_TopRight
    0x3C2,  # VerticalBarrier_MidLeft
    0x3C3,  # VerticalBarrier_MidRight
    0x3C4,  # VerticalBarrier_BottomLeft
    0x3C5,  # VerticalBarrier_BottomRight
}

_SILPH_CO_DOOR_SCRIPT_SYMBOLS: tuple[str, ...] = (
    "SilphCo_2F_EventScript_Door1",
    "SilphCo_2F_EventScript_Door2",
    "SilphCo_3F_EventScript_Door1",
    "SilphCo_3F_EventScript_Door2",
    "SilphCo_4F_EventScript_Door1",
    "SilphCo_4F_EventScript_Door2",
    "SilphCo_5F_EventScript_Door1",
    "SilphCo_5F_EventScript_Door2",
    "SilphCo_5F_EventScript_Door3",
    "SilphCo_6F_EventScript_Door",
    "SilphCo_7F_EventScript_Door1",
    "SilphCo_7F_EventScript_Door2",
    "SilphCo_7F_EventScript_Door3",
    "SilphCo_8F_EventScript_Door",
    "SilphCo_9F_EventScript_Door1",
    "SilphCo_9F_EventScript_Door2",
    "SilphCo_9F_EventScript_Door3",
    "SilphCo_9F_EventScript_Door4",
    "SilphCo_10F_EventScript_Door",
    "SilphCo_11F_EventScript_Door",
)
_SILPH_CO_DOOR_SCRIPT_ADDRS: set[int] | None = None


def _silph_co_door_script_addrs() -> set[int]:
    global _SILPH_CO_DOOR_SCRIPT_ADDRS
    if _SILPH_CO_DOOR_SCRIPT_ADDRS is None:
        addrs: set[int] = set()
        for symbol_name in _SILPH_CO_DOOR_SCRIPT_SYMBOLS:
            addr = int(sym_addr(symbol_name))
            if addr != 0:
                addrs.add(addr)
        _SILPH_CO_DOOR_SCRIPT_ADDRS = addrs
    return _SILPH_CO_DOOR_SCRIPT_ADDRS


def is_silph_co_locked_door_metatile(*, map_name: str, metatile_id: int) -> bool:
    if not str(map_name or "").startswith("SILPH_CO_"):
        return False
    return int(metatile_id) in SILPH_CO_LOCKED_DOOR_METATILE_IDS


def is_silph_co_door_bg_event(*, map_name: str, script_addr: int) -> bool:
    if not str(map_name or "").startswith("SILPH_CO_"):
        return False
    if int(script_addr) == 0:
        return False
    return int(script_addr) in _silph_co_door_script_addrs()


# Map-specific temporary walls (scripted setmetatile barriers that can disappear).
# These are rendered only while the underlying mapgrid tile is currently a collision wall.
TEMPORARY_WALL_TILES_BY_MAP: Dict[str, Dict[str, str]] = {
    # pokefirered/data/maps/VictoryRoad_1F/scripts.inc
    #  - setmetatile 12,14/12,15 to RockBarrier on load
    #  - replaced when the strength switch is activated
    "VICTORY_ROAD_1_F": {
        "12,14": TILE_TEMPORARY_WALL,
        "12,15": TILE_TEMPORARY_WALL,
    },
    # pokefirered/data/maps/VictoryRoad_2F/scripts.inc
    #  - two independent rock barriers controlled by two floor switches
    "VICTORY_ROAD_2_F": {
        "13,10": TILE_TEMPORARY_WALL,
        "13,11": TILE_TEMPORARY_WALL,
        "33,16": TILE_TEMPORARY_WALL,
        "33,17": TILE_TEMPORARY_WALL,
    },
    # pokefirered/data/maps/VictoryRoad_3F/scripts.inc
    #  - single rock barrier opened by floor switch event
    "VICTORY_ROAD_3_F": {
        "12,12": TILE_TEMPORARY_WALL,
        "12,13": TILE_TEMPORARY_WALL,
    },
}

# =============================================================================
