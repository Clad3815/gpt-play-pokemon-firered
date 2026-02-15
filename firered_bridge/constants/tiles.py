from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .addresses import MAP_OFFSET, MAPGRID_COLLISION_MASK, MAPGRID_UNDEFINED

# Tiles / Minimap (SINGLE SOURCE OF TRUTH)
# =============================================================================

# Passabilité (emojis) — "tile ids" dans map_data
TILE_WALKABLE = "🟫"
TILE_WALKABLE_BLOCK_NORTH = "🟫↑🚫"
TILE_WALKABLE_BLOCK_SOUTH = "🟫↓🚫"
TILE_WALKABLE_BLOCK_EAST = "🟫→🚫"
TILE_WALKABLE_BLOCK_WEST = "🟫←🚫"
TILE_WALKABLE_BLOCK_NORTHEAST = "🟫↑→🚫"
TILE_WALKABLE_BLOCK_NORTHWEST = "🟫↑←🚫"
TILE_WALKABLE_BLOCK_SOUTHEAST = "🟫↓→🚫"
TILE_WALKABLE_BLOCK_SOUTHWEST = "🟫↓←🚫"
TILE_BLOCKED = "⛔"
TILE_WARP = "🌀"
TILE_NPC = "👤"
TILE_WATER = "🌊"
TILE_WATERFALL = "💧↑"
TILE_WATER_CURRENT_LEFT = "🌊←"
TILE_WATER_CURRENT_RIGHT = "🌊→"
TILE_WATER_CURRENT_UP = "🌊↑"
TILE_WATER_CURRENT_DOWN = "🌊↓"
TILE_DIVE_WATER = "🌊🫧"
TILE_LEDGE_EAST = "⛛→"
TILE_LEDGE_WEST = "⛛←"
TILE_LEDGE_NORTH = "⛛↑"
TILE_LEDGE_SOUTH = "⛛↓"
TILE_INTERACTIVE = "✨"  # PC, signs, clocks, bookshelves, etc.
TILE_BOULDER = "🪨"
TILE_CUTTABLE_TREE = "🌳"
TILE_BREAKABLE_ROCK = "🪨⛏️"
TILE_GRASS = "🌿"
TILE_RED_CARPET = "🟥"
TILE_THIN_ICE = "🧊"
TILE_CRACKED_ICE = "🧊⚡"
TILE_CRACKED_FLOOR = "🟫⚡"
TILE_STRENGTH_SWITCH = "🔘"
TILE_TEMPORARY_WALL = "🧱⏳"
TILE_LOCKED_DOOR = "🚪🔒"
TILE_OOB_WALKABLE = "⬜"
TILE_OOB_COLLISION = "⬛"
TILE_DOOR = "🚪"
TILE_LADDER = "🪜"
TILE_ESCALATOR = "🛗"
TILE_HOLE = "🕳️"
TILE_STAIRS = "🧗"
TILE_ENTRANCE = "🏔️"
TILE_WARP_ARROW = "➡️"
TILE_ARROW_FLOOR_LEFT = "←"
TILE_ARROW_FLOOR_RIGHT = "→"
TILE_ARROW_FLOOR_UP = "↑"
TILE_ARROW_FLOOR_DOWN = "↓"
TILE_SPINNER_RIGHT = "🌀→"
TILE_SPINNER_LEFT = "🌀←"
TILE_SPINNER_UP = "🌀↑"
TILE_SPINNER_DOWN = "🌀↓"
TILE_STOP_SPINNER = "🌀⏹️"

# Interactive metatiles (specific, visible "press A" objects)
TILE_PC = "🖥️"
TILE_REGION_MAP = "🗺️"
TILE_TELEVISION = "📺"
TILE_BOOKSHELF = "📚"
TILE_TRASH_CAN = "🗑️"
TILE_SHOP_SHELF = "🛒"
TILE_ITEM_BALL = "🎁"

OBJECT_EVENT_TILE_BY_TYPE: Dict[str, str] = {
    "ITEM_BALL": TILE_ITEM_BALL,
    "PUSHABLE_BOULDER": TILE_BOULDER,
    "CUT_TREE": TILE_CUTTABLE_TREE,
    "ROCK_SMASH_ROCK": TILE_BREAKABLE_ROCK,
}


@dataclass(frozen=True, slots=True)
class MinimapTileDef:
    """Définition d'une tuile minimap + sa sémantique.

    IMPORTANT:
    - Ce dict est LA source de vérité pour:
      - minimap_legend (code -> label)
      - mapping tile->code
      - collision flag (tile -> bool)
    """

    glyph: str
    label: str
    tile_id: str
    passability: bool = True
    is_base_terrain: bool = True
    show_in_legend: bool = True


# Codes numériques (inchangés pour ne rien casser côté client)
MINIMAP_CODE_WALL = 0
MINIMAP_CODE_FREE_GROUND = 1
MINIMAP_CODE_FREE_GROUND_BLOCK_NORTH = 68
MINIMAP_CODE_FREE_GROUND_BLOCK_SOUTH = 69
MINIMAP_CODE_FREE_GROUND_BLOCK_EAST = 70
MINIMAP_CODE_FREE_GROUND_BLOCK_WEST = 71
MINIMAP_CODE_FREE_GROUND_BLOCK_NORTHEAST = 72
MINIMAP_CODE_FREE_GROUND_BLOCK_NORTHWEST = 73
MINIMAP_CODE_FREE_GROUND_BLOCK_SOUTHEAST = 74
MINIMAP_CODE_FREE_GROUND_BLOCK_SOUTHWEST = 75
MINIMAP_CODE_TALL_GRASS = 2
MINIMAP_CODE_WATER = 3
MINIMAP_CODE_WATERFALL = 4
MINIMAP_CODE_LEDGE_EAST = 5
MINIMAP_CODE_LEDGE_WEST = 6
MINIMAP_CODE_LEDGE_NORTH = 7
MINIMAP_CODE_LEDGE_SOUTH = 8
MINIMAP_CODE_WARP = 9
MINIMAP_CODE_NPC = 10
MINIMAP_CODE_INTERACTIVE = 11
# 12 (Hidden item) volontairement non exposé / non utilisé (anti-cheat)
MINIMAP_CODE_PC = 14
MINIMAP_CODE_REGION_MAP = 15
MINIMAP_CODE_TELEVISION = 16
MINIMAP_CODE_BOOKSHELF = 18
MINIMAP_CODE_TRASH_CAN = 21
MINIMAP_CODE_SHOP_SHELF = 22
MINIMAP_CODE_RED_CARPET = 23
MINIMAP_CODE_OOB_WALKABLE = 24
MINIMAP_CODE_OOB_COLLISION = 25
MINIMAP_CODE_DOOR = 26
MINIMAP_CODE_LADDER = 27
MINIMAP_CODE_ESCALATOR = 28
MINIMAP_CODE_HOLE = 29
MINIMAP_CODE_STAIRS = 30
MINIMAP_CODE_ENTRANCE = 31
MINIMAP_CODE_WARP_ARROW = 32
MINIMAP_CODE_BOULDER = 33
MINIMAP_CODE_CUTTABLE_TREE = 35
MINIMAP_CODE_BREAKABLE_ROCK = 36
MINIMAP_CODE_ARROW_FLOOR_LEFT = 44
MINIMAP_CODE_ARROW_FLOOR_RIGHT = 45
MINIMAP_CODE_ARROW_FLOOR_UP = 46
MINIMAP_CODE_ARROW_FLOOR_DOWN = 47
MINIMAP_CODE_THIN_ICE = 48
MINIMAP_CODE_CRACKED_ICE = 49
MINIMAP_CODE_WATER_CURRENT_LEFT = 50
MINIMAP_CODE_WATER_CURRENT_RIGHT = 51
MINIMAP_CODE_WATER_CURRENT_UP = 52
MINIMAP_CODE_WATER_CURRENT_DOWN = 53
MINIMAP_CODE_DIVE_WATER = 54
MINIMAP_CODE_ITEM_BALL = 55
MINIMAP_CODE_SPINNER_RIGHT = 60
MINIMAP_CODE_SPINNER_LEFT = 61
MINIMAP_CODE_SPINNER_UP = 62
MINIMAP_CODE_SPINNER_DOWN = 63
MINIMAP_CODE_STOP_SPINNER = 64
MINIMAP_CODE_STRENGTH_SWITCH = 65
MINIMAP_CODE_TEMPORARY_WALL = 66
MINIMAP_CODE_LOCKED_DOOR = 67
MINIMAP_CODE_CRACKED_FLOOR = 140

# SINGLE DICT: legend + id + collision flag + base/overlay
MINIMAP_TILES: Dict[int, MinimapTileDef] = {
    MINIMAP_CODE_WALL: MinimapTileDef(
        glyph=TILE_BLOCKED,
        label="Wall",
        tile_id=TILE_BLOCKED,
        passability=False,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND: MinimapTileDef(
        glyph=TILE_WALKABLE,
        label="Free Ground",
        tile_id=TILE_WALKABLE,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_NORTH: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_NORTH,
        label="Free Ground (North Edge Blocked: cannot enter from north)",
        tile_id=TILE_WALKABLE_BLOCK_NORTH,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_SOUTH: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_SOUTH,
        label="Free Ground (South Edge Blocked: cannot enter from south)",
        tile_id=TILE_WALKABLE_BLOCK_SOUTH,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_EAST: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_EAST,
        label="Free Ground (East Edge Blocked: cannot enter from east)",
        tile_id=TILE_WALKABLE_BLOCK_EAST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_WEST: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_WEST,
        label="Free Ground (West Edge Blocked: cannot enter from west)",
        tile_id=TILE_WALKABLE_BLOCK_WEST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_NORTHEAST: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_NORTHEAST,
        label="Free Ground (North+East Edge Blocked: cannot enter from north/east)",
        tile_id=TILE_WALKABLE_BLOCK_NORTHEAST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_NORTHWEST: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_NORTHWEST,
        label="Free Ground (North+West Edge Blocked: cannot enter from north/west)",
        tile_id=TILE_WALKABLE_BLOCK_NORTHWEST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_SOUTHEAST: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_SOUTHEAST,
        label="Free Ground (South+East Edge Blocked: cannot enter from south/east)",
        tile_id=TILE_WALKABLE_BLOCK_SOUTHEAST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_FREE_GROUND_BLOCK_SOUTHWEST: MinimapTileDef(
        glyph=TILE_WALKABLE_BLOCK_SOUTHWEST,
        label="Free Ground (South+West Edge Blocked: cannot enter from south/west)",
        tile_id=TILE_WALKABLE_BLOCK_SOUTHWEST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_TALL_GRASS: MinimapTileDef(
        glyph=TILE_GRASS,
        label="Tall Grass",
        tile_id=TILE_GRASS,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_WATER: MinimapTileDef(
        glyph=TILE_WATER,
        label="Water",
        tile_id=TILE_WATER,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_WATERFALL: MinimapTileDef(
        glyph=TILE_WATERFALL,
        label="Waterfall",
        tile_id=TILE_WATERFALL,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_WATER_CURRENT_LEFT: MinimapTileDef(
        glyph=TILE_WATER_CURRENT_LEFT,
        label="Water Current Left",
        tile_id=TILE_WATER_CURRENT_LEFT,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_WATER_CURRENT_RIGHT: MinimapTileDef(
        glyph=TILE_WATER_CURRENT_RIGHT,
        label="Water Current Right",
        tile_id=TILE_WATER_CURRENT_RIGHT,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_WATER_CURRENT_UP: MinimapTileDef(
        glyph=TILE_WATER_CURRENT_UP,
        label="Water Current Up",
        tile_id=TILE_WATER_CURRENT_UP,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_WATER_CURRENT_DOWN: MinimapTileDef(
        glyph=TILE_WATER_CURRENT_DOWN,
        label="Water Current Down",
        tile_id=TILE_WATER_CURRENT_DOWN,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_DIVE_WATER: MinimapTileDef(
        glyph=TILE_DIVE_WATER,
        label="Dive Water",
        tile_id=TILE_DIVE_WATER,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_LEDGE_EAST: MinimapTileDef(
        glyph=TILE_LEDGE_EAST,
        label="Ledge East",
        tile_id=TILE_LEDGE_EAST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_LEDGE_WEST: MinimapTileDef(
        glyph=TILE_LEDGE_WEST,
        label="Ledge West",
        tile_id=TILE_LEDGE_WEST,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_LEDGE_NORTH: MinimapTileDef(
        glyph=TILE_LEDGE_NORTH,
        label="Ledge North",
        tile_id=TILE_LEDGE_NORTH,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_LEDGE_SOUTH: MinimapTileDef(
        glyph=TILE_LEDGE_SOUTH,
        label="Ledge South",
        tile_id=TILE_LEDGE_SOUTH,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_RED_CARPET: MinimapTileDef(
        glyph=TILE_RED_CARPET,
        label="Red Carpet",
        tile_id=TILE_RED_CARPET,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_THIN_ICE: MinimapTileDef(
        glyph=TILE_THIN_ICE,
        label="Thin Ice",
        tile_id=TILE_THIN_ICE,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_CRACKED_ICE: MinimapTileDef(
        glyph=TILE_CRACKED_ICE,
        label="Cracked Ice",
        tile_id=TILE_CRACKED_ICE,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_CRACKED_FLOOR: MinimapTileDef(
        glyph=TILE_CRACKED_FLOOR,
        label="Cracked Floor",
        tile_id=TILE_CRACKED_FLOOR,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_ARROW_FLOOR_LEFT: MinimapTileDef(
        glyph=TILE_ARROW_FLOOR_LEFT,
        label="Arrow Floor Left",
        tile_id=TILE_ARROW_FLOOR_LEFT,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_ARROW_FLOOR_RIGHT: MinimapTileDef(
        glyph=TILE_ARROW_FLOOR_RIGHT,
        label="Arrow Floor Right",
        tile_id=TILE_ARROW_FLOOR_RIGHT,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_ARROW_FLOOR_UP: MinimapTileDef(
        glyph=TILE_ARROW_FLOOR_UP,
        label="Arrow Floor Up",
        tile_id=TILE_ARROW_FLOOR_UP,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_ARROW_FLOOR_DOWN: MinimapTileDef(
        glyph=TILE_ARROW_FLOOR_DOWN,
        label="Arrow Floor Down",
        tile_id=TILE_ARROW_FLOOR_DOWN,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_SPINNER_RIGHT: MinimapTileDef(
        glyph=TILE_SPINNER_RIGHT,
        label="Spinner Right",
        tile_id=TILE_SPINNER_RIGHT,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_SPINNER_LEFT: MinimapTileDef(
        glyph=TILE_SPINNER_LEFT,
        label="Spinner Left",
        tile_id=TILE_SPINNER_LEFT,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_SPINNER_UP: MinimapTileDef(
        glyph=TILE_SPINNER_UP,
        label="Spinner Up",
        tile_id=TILE_SPINNER_UP,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_SPINNER_DOWN: MinimapTileDef(
        glyph=TILE_SPINNER_DOWN,
        label="Spinner Down",
        tile_id=TILE_SPINNER_DOWN,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_STOP_SPINNER: MinimapTileDef(
        glyph=TILE_STOP_SPINNER,
        label="Stop Spinner",
        tile_id=TILE_STOP_SPINNER,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_STRENGTH_SWITCH: MinimapTileDef(
        glyph=TILE_STRENGTH_SWITCH,
        label="Strength Switch",
        tile_id=TILE_STRENGTH_SWITCH,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_TEMPORARY_WALL: MinimapTileDef(
        glyph=TILE_TEMPORARY_WALL,
        label="Temporary Wall",
        tile_id=TILE_TEMPORARY_WALL,
        passability=False,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_OOB_WALKABLE: MinimapTileDef(
        glyph=TILE_OOB_WALKABLE,
        label="OOB",
        tile_id=TILE_OOB_WALKABLE,
        is_base_terrain=True,
    ),
    MINIMAP_CODE_OOB_COLLISION: MinimapTileDef(
        glyph=TILE_OOB_COLLISION,
        label="OOB",
        tile_id=TILE_OOB_COLLISION,
        passability=False,
        is_base_terrain=True,
    ),
    # Overlays (pas du terrain de base)
    MINIMAP_CODE_WARP: MinimapTileDef(
        glyph=TILE_WARP,
        label="Warp Pad",
        tile_id=TILE_WARP,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_NPC: MinimapTileDef(
        glyph=TILE_NPC,
        label="NPC",
        tile_id=TILE_NPC,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_INTERACTIVE: MinimapTileDef(
        glyph=TILE_INTERACTIVE,
        label="Interactive",
        tile_id=TILE_INTERACTIVE,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_PC: MinimapTileDef(
        glyph=TILE_PC,
        label="PC",
        tile_id=TILE_PC,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_REGION_MAP: MinimapTileDef(
        glyph=TILE_REGION_MAP,
        label="Region Map",
        tile_id=TILE_REGION_MAP,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_TELEVISION: MinimapTileDef(
        glyph=TILE_TELEVISION,
        label="Television",
        tile_id=TILE_TELEVISION,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_BOOKSHELF: MinimapTileDef(
        glyph=TILE_BOOKSHELF,
        label="Bookshelf",
        tile_id=TILE_BOOKSHELF,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_TRASH_CAN: MinimapTileDef(
        glyph=TILE_TRASH_CAN,
        label="Trash Can",
        tile_id=TILE_TRASH_CAN,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_SHOP_SHELF: MinimapTileDef(
        glyph=TILE_SHOP_SHELF,
        label="Shop Shelf",
        tile_id=TILE_SHOP_SHELF,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_DOOR: MinimapTileDef(
        glyph=TILE_DOOR,
        label="Door",
        tile_id=TILE_DOOR,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_LOCKED_DOOR: MinimapTileDef(
        glyph=TILE_LOCKED_DOOR,
        label="Locked Door",
        tile_id=TILE_LOCKED_DOOR,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_LADDER: MinimapTileDef(
        glyph=TILE_LADDER,
        label="Ladder",
        tile_id=TILE_LADDER,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_ESCALATOR: MinimapTileDef(
        glyph=TILE_ESCALATOR,
        label="Escalator",
        tile_id=TILE_ESCALATOR,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_HOLE: MinimapTileDef(
        glyph=TILE_HOLE,
        label="Hole",
        tile_id=TILE_HOLE,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_STAIRS: MinimapTileDef(
        glyph=TILE_STAIRS,
        label="Stairs",
        tile_id=TILE_STAIRS,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_ENTRANCE: MinimapTileDef(
        glyph=TILE_ENTRANCE,
        label="Entrance",
        tile_id=TILE_ENTRANCE,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_WARP_ARROW: MinimapTileDef(
        glyph=TILE_WARP_ARROW,
        label="Arrow Warp",
        tile_id=TILE_WARP_ARROW,
        is_base_terrain=False,
        show_in_legend=False,
    ),
    MINIMAP_CODE_BOULDER: MinimapTileDef(
        glyph=TILE_BOULDER,
        label="boulder",
        tile_id=TILE_BOULDER,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_CUTTABLE_TREE: MinimapTileDef(
        glyph=TILE_CUTTABLE_TREE,
        label="cuttable tree",
        tile_id=TILE_CUTTABLE_TREE,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_BREAKABLE_ROCK: MinimapTileDef(
        glyph=TILE_BREAKABLE_ROCK,
        label="breakable rock",
        tile_id=TILE_BREAKABLE_ROCK,
        passability=False,
        is_base_terrain=False,
    ),
    MINIMAP_CODE_ITEM_BALL: MinimapTileDef(
        glyph=TILE_ITEM_BALL,
        label="Item Ball",
        tile_id=TILE_ITEM_BALL,
        passability=False,
        is_base_terrain=False,
    ),
}

# Derivés AUTOMATIQUEMENT (pas de duplication "source")
MINIMAP_LEGEND: Dict[int, str] = {code: td.label for code, td in MINIMAP_TILES.items() if td.show_in_legend}
MINIMAP_CODE_BY_TILE: Dict[str, int] = {td.tile_id: code for code, td in MINIMAP_TILES.items()}

_NO_COLLISION_SUFFIX_TILE_IDS = {TILE_BOULDER, TILE_CUTTABLE_TREE, TILE_BREAKABLE_ROCK}

def _tile_label_with_collision(td: MinimapTileDef) -> str:
    if (not td.passability) and (td.tile_id not in _NO_COLLISION_SUFFIX_TILE_IDS):
        return f"{td.label} (Collision)"
    return td.label


BASE_TILE_PASSABILITY: Dict[str, str] = {
    td.tile_id: _tile_label_with_collision(td) for td in MINIMAP_TILES.values() if td.is_base_terrain
}
VIEWPORT_TILE_PASSABILITY: Dict[str, str] = {
    td.tile_id: _tile_label_with_collision(td) for td in MINIMAP_TILES.values() if td.show_in_legend
}
VIEWPORT_TILE_PASSABILITY["❓"] = "Fog of War (Unknown)"


def minimap_code_for_tile(tile_id: str, default_code: int = MINIMAP_CODE_FREE_GROUND) -> int:
    return MINIMAP_CODE_BY_TILE.get(tile_id, default_code)


def _oob_tile_for_coord(
    map_x: int,
    map_y: int,
    backup_tiles: Optional[List[int]],
    backup_width: int,
    backup_height: int,
) -> str:
    if not backup_tiles or backup_width <= 0 or backup_height <= 0:
        return TILE_OOB_COLLISION

    bx = map_x + MAP_OFFSET
    by = map_y + MAP_OFFSET
    if bx < 0 or by < 0 or bx >= backup_width or by >= backup_height:
        return TILE_OOB_COLLISION

    idx = by * backup_width + bx
    if idx < 0 or idx >= len(backup_tiles):
        return TILE_OOB_COLLISION

    val = backup_tiles[idx]
    if val == MAPGRID_UNDEFINED:
        return TILE_OOB_COLLISION

    collision_bits = (val & MAPGRID_COLLISION_MASK) >> 10
    return TILE_OOB_COLLISION if collision_bits != 0 else TILE_OOB_WALKABLE


# =============================================================================
