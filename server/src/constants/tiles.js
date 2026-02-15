// Tile definitions shared between rendering and reasoning (FireRed).
//
// IMPORTANT:
// - keys are numeric minimap codes (same codes emitted by the Python bridge)
// - values are [symbol, description]
//
// Source of truth in Python:
//   firered_bridge/constants/tiles.py

const NPC_ID = 10;

// Player orientation (server-only; not emitted by Python grid).
const PLAYER_ORIENTATION_TILES = {
  100: ["🧍↓", "Player (Facing Down)"],
  101: ["🧍↑", "Player (Facing Up)"],
  102: ["🧍←", "Player (Facing Left)"],
  103: ["🧍→", "Player (Facing Right)"],
};

const MARKDOWN_TILES = {
  0: ["⛔", "Wall (Collision/Impassable)"],
  1: ["🟫", "Free Ground"],
  68: ["🟫↑🚫", "Free Ground (North Edge Blocked: cannot enter from north)"],
  69: ["🟫↓🚫", "Free Ground (South Edge Blocked: cannot enter from south)"],
  70: ["🟫→🚫", "Free Ground (East Edge Blocked: cannot enter from east)"],
  71: ["🟫←🚫", "Free Ground (West Edge Blocked: cannot enter from west)"],
  72: ["🟫↑→🚫", "Free Ground (North+East Edges Blocked: cannot enter from north/east)"],
  73: ["🟫↑←🚫", "Free Ground (North+West Edges Blocked: cannot enter from north/west)"],
  74: ["🟫↓→🚫", "Free Ground (South+East Edges Blocked: cannot enter from south/east)"],
  75: ["🟫↓←🚫", "Free Ground (South+West Edges Blocked: cannot enter from south/west)"],
  2: ["🌿", "Tall Grass"],
  3: ["🌊", "Water"],
  4: ["💧↑", "Waterfall"],
  5: ["⛛→", "Ledge East"],
  6: ["⛛←", "Ledge West"],
  7: ["⛛↑", "Ledge North"],
  8: ["⛛↓", "Ledge South"],
  9: ["🌀", "Warp"],
  10: ["👤", "NPC (Collision)"],
  11: ["✨", "Interactive (Collision)"],
  14: ["🖥️", "PC (Collision)"],
  15: ["🗺️", "Region Map (Collision)"],
  16: ["📺", "Television (Collision)"],
  18: ["📚", "Bookshelf (Collision)"],
  21: ["🗑️", "Trash Can (Collision)"],
  22: ["🛒", "Shop Shelf (Collision)"],
  23: ["🟥", "Red Carpet"],
  24: ["⬜", "OOB (Walkable)"],
  25: ["⬛", "OOB (Collision)"],
  26: ["🚪", "Door"],
  27: ["🪜", "Ladder"],
  28: ["🛗", "Escalator"],
  29: ["🕳️", "Hole"],
  30: ["🧗", "Stairs"],
  31: ["🏔️", "Entrance"],
  32: ["➡️", "Warp Arrow"],
  33: ["🪨", "Boulder (Collision)"],
  35: ["🌳", "Cuttable Tree (Collision)"],
  36: ["🪨⛏️", "Breakable Rock (Collision)"],
  44: ["←", "Arrow Floor Left"],
  45: ["→", "Arrow Floor Right"],
  46: ["↑", "Arrow Floor Up"],
  47: ["↓", "Arrow Floor Down"],
  48: ["🧊", "Thin Ice"],
  49: ["🧊⚡", "Cracked Ice"],
  50: ["🌊←", "Water Current Left"],
  51: ["🌊→", "Water Current Right"],
  52: ["🌊↑", "Water Current Up"],
  53: ["🌊↓", "Water Current Down"],
  54: ["🌊🫧", "Dive Water"],
  55: ["🎁", "Item Ball (Collision)"],
  60: ["🌀→", "Spinner Right"],
  61: ["🌀←", "Spinner Left"],
  62: ["🌀↑", "Spinner Up"],
  63: ["🌀↓", "Spinner Down"],
  64: ["🌀⏹️", "Stop Spinner"],
  65: ["🔘", "Strength Switch"],
  66: ["🧱⏳", "Temporary Wall (Collision)"],
  67: ["🚪🔒", "Locked Door (Collision)"],
  140: ["🟫⚡", "Cracked Floor"],
};

const FALLBACK = ["❓", "Unknown"];
const SYM_PLAYER = ["🧑", "Player"];
const SYM_UNKNOWN = ["❓", "Fog of War (Unknown)"];

module.exports = {
  NPC_ID,
  MARKDOWN_TILES,
  PLAYER_ORIENTATION_TILES,
  FALLBACK,
  SYM_PLAYER,
  SYM_UNKNOWN,
};
