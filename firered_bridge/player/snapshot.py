from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .. import game_data
from ..constants.addresses import (
    BADGES,
    CB2_DO_CHANGE_MAP_ADDR,
    CB2_LOAD_MAP_ADDR,
    CURRENT_MAP_HEADER_ADDR,
    FLAG_DEFEATED_AGATHA,
    FLAG_DEFEATED_BRUNO,
    FLAG_DEFEATED_CHAMP,
    FLAG_DEFEATED_LANCE,
    FLAG_DEFEATED_LORELEI,
    FLAG_GOT_HM03,
    FLAG_GOT_POKE_FLUTE,
    FLAG_HIDE_HIDEOUT_GIOVANNI,
    FLAG_HIDE_SAFFRON_ROCKETS,
    FLAG_HIDE_SS_ANNE,
    FLAG_SYS_SAFARI_MODE,
    FLAG_SYS_USE_FLASH,
    FLAG_SYS_USE_STRENGTH,
    FLAG_SYS_GAME_CLEAR,
    FLAG_SYS_POKEDEX_GET,
    FLAG_SYS_POKEMON_GET,
    FACING_DIRECTION_MAP,
    GMAIN_ADDR,
    GMAIN_CALLBACK2_OFFSET,
    GPALETTE_FADE_ADDR,
    GSAFARI_ZONE_STEP_COUNTER_ADDR,
    GSAVEBLOCK1_PTR_ADDR,
    IN_BATTLE_BIT_ADDR,
    IN_BATTLE_BITMASK,
    MAP_HEADER_CAVE_OFFSET,
    MAP_HEADER_MAP_LAYOUT_ID_OFFSET,
    OBJECT_EVENT_COUNT,
    OBJECT_EVENT_CURRENT_ELEVATION_MASK,
    OBJECT_EVENT_ELEVATION_OFFSET,
    OBJECT_EVENT_FACING_DIR_OFFSET,
    OBJECT_EVENT_SIZE,
    OBJECT_EVENTS_ADDR,
    OBJECT_EVENTS_PLAYER_INDEX,
    PALETTE_FADE_ACTIVE_MASK32,
    PALETTE_FADE_BITFIELDS_OFFSET,
    PLAYER_AVATAR_ADDR,
    PLAYER_AVATAR_FLAG_ACRO_BIKE,
    PLAYER_AVATAR_FLAG_BIKING,
    PLAYER_AVATAR_FLAG_DIVING,
    PLAYER_AVATAR_FLAG_MACH_BIKE,
    PLAYER_AVATAR_FLAG_SURFING,
    SAVESTATE_FLAGS_OFFSET,
    SAVESTATE_MONEY_OFFSET,
    SAVESTATE_OBJECT_POINTER_ADDR,
    SCRIPT_CONTEXT_MODE_OFFSET,
    SCRIPT_CONTEXT_NATIVE_PTR_OFFSET,
    SCRIPT_LOCK_FIELD_CONTROLS,
    SCRIPT_MODE_NATIVE,
    SCRIPT_MODE_STOPPED,
    SECURITY_KEY_OFFSET,
    SECURITY_KEY_POINTER_ADDR,
    SB1_FLASH_LEVEL_OFFSET,
    SB2_PYRAMID_LIGHT_RADIUS_OFFSET,
    SGLOBAL_SCRIPT_CONTEXT_ADDR,
    IS_FIELD_MESSAGE_BOX_HIDDEN_ADDR,
    WAIT_FOR_A_OR_B_PRESS_ADDR,
)
from ..constants.behaviors import MAX_VIEWPORT_HEIGHT, MAX_VIEWPORT_WIDTH
from ..memory import mgba
from ..util.bytes import _u16le_from, _u32le_from, _u8_from
from .save import _flag_get_from_sb1

# pokefirered/src/field_screen_effect.c: sFlashLevelToRadius[]
_FLASH_LEVEL_TO_RADIUS_PX = [200, 72, 64, 56, 48, 40, 32, 24, 0]
_ELITE_FOUR_FLAGS = (
    FLAG_DEFEATED_LORELEI,
    FLAG_DEFEATED_BRUNO,
    FLAG_DEFEATED_AGATHA,
    FLAG_DEFEATED_LANCE,
)
_LOW_IMPORTANT_EVENT_FLAGS = (
    FLAG_HIDE_HIDEOUT_GIOVANNI,
    FLAG_HIDE_SAFFRON_ROCKETS,
    FLAG_HIDE_SS_ANNE,
    FLAG_GOT_HM03,
    FLAG_GOT_POKE_FLUTE,
)


def _bike_type_from_avatar_flags(avatar_flags: int) -> str | None:
    if (avatar_flags & PLAYER_AVATAR_FLAG_MACH_BIKE) != 0:
        return "MACH_BIKE"
    if (avatar_flags & PLAYER_AVATAR_FLAG_ACRO_BIKE) != 0:
        return "ACRO_BIKE"
    return None


def get_player_bike_type() -> str | None:
    """
    Return the current bike type as a string, or None if not on a bike.

    pokefirered defines two distinct avatar flags:
    - PLAYER_AVATAR_FLAG_MACH_BIKE
    - PLAYER_AVATAR_FLAG_ACRO_BIKE
    """
    try:
        flags = int(mgba.mgba_read8(PLAYER_AVATAR_ADDR))
        return _bike_type_from_avatar_flags(flags)
    except Exception:
        return None


def _flag_get_from_bytes(flags_base_byte: int, flags_bytes: bytes, flag_id: int) -> bool:
    """
    Read a saveblock flag bit from a pre-fetched `flags_bytes` window.
    """
    byte_offset = int(flag_id) // 8
    bit = int(flag_id) % 8
    idx = byte_offset - int(flags_base_byte)
    if 0 <= idx < len(flags_bytes):
        return (flags_bytes[idx] & (1 << bit)) != 0
    return False


def _elite_four_done_from_reader(flag_reader) -> bool:
    """
    FireRed resets individual Elite Four defeated flags after Hall of Fame.
    Keep EVENT_BEAT_ELITE_FOUR monotonic by considering GAME_CLEAR as done too.
    """
    hall_of_fame = bool(flag_reader(FLAG_SYS_GAME_CLEAR))
    if hall_of_fame:
        return True
    return all(bool(flag_reader(flag_id)) for flag_id in _ELITE_FOUR_FLAGS)


def _story_league_gate_done_from_reader(flag_reader, flag_id: int) -> bool:
    """
    Lance/Champion defeated flags are reset by Hall of Fame scripts in FireRed.
    Keep events monotonic by falling back to GAME_CLEAR.
    """
    return bool(flag_reader(flag_id)) or bool(flag_reader(FLAG_SYS_GAME_CLEAR))


def get_important_events(*, sb1_ptr: Optional[int] = None) -> Dict[str, bool]:
    """
    Minimal monotonic progress events used by the Node progress tracker (agent-compatible keys).
    """
    try:
        sb1 = int(sb1_ptr) if sb1_ptr else int(mgba.mgba_read32(SAVESTATE_OBJECT_POINTER_ADDR))
        if sb1 == 0:
            return {}

        hall_of_fame = _flag_get_from_sb1(sb1, FLAG_SYS_GAME_CLEAR)

        def _read_flag(flag_id: int) -> bool:
            if flag_id == FLAG_SYS_GAME_CLEAR:
                return hall_of_fame
            return _flag_get_from_sb1(sb1, flag_id)

        return {
            "EVENT_GOT_STARTER": _read_flag(FLAG_SYS_POKEMON_GET),
            "EVENT_GOT_POKEDEX": _read_flag(FLAG_SYS_POKEDEX_GET),
            "EVENT_SS_ANNE_LEFT": _read_flag(FLAG_HIDE_SS_ANNE),
            "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI": _read_flag(FLAG_HIDE_HIDEOUT_GIOVANNI),
            "EVENT_GOT_POKE_FLUTE": _read_flag(FLAG_GOT_POKE_FLUTE),
            "EVENT_GOT_HM03": _read_flag(FLAG_GOT_HM03),
            "EVENT_BEAT_SILPH_CO_GIOVANNI": _read_flag(FLAG_HIDE_SAFFRON_ROCKETS),
            "EVENT_BEAT_LANCE": _story_league_gate_done_from_reader(_read_flag, FLAG_DEFEATED_LANCE),
            "EVENT_BEAT_CHAMPION_RIVAL": _story_league_gate_done_from_reader(_read_flag, FLAG_DEFEATED_CHAMP),
            "EVENT_BEAT_ELITE_FOUR": _elite_four_done_from_reader(_read_flag),
            "EVENT_HALL_OF_FAME": hall_of_fame,
        }
    except Exception:
        return {}


def get_security_key() -> int:
    base_ptr = mgba.mgba_read32(SECURITY_KEY_POINTER_ADDR)
    if base_ptr == 0:
        raise RuntimeError("Security key base pointer null")
    return mgba.mgba_read32(base_ptr + SECURITY_KEY_OFFSET)


def get_safari_zone_steps_remaining() -> int:
    try:
        return int(mgba.mgba_read16(GSAFARI_ZONE_STEP_COUNTER_ADDR))
    except Exception:
        return 0


def is_safari_zone_active(*, sb1_ptr: Optional[int] = None) -> bool:
    try:
        sb1 = int(sb1_ptr) if sb1_ptr else int(mgba.mgba_read32(SAVESTATE_OBJECT_POINTER_ADDR))
        if sb1 == 0:
            return bool(get_safari_zone_steps_remaining() > 0)
        return bool(_flag_get_from_sb1(sb1, FLAG_SYS_SAFARI_MODE))
    except Exception:
        return bool(get_safari_zone_steps_remaining() > 0)


def _read_player_snapshot() -> Dict[str, Any]:
    try:
        ranges = [
            (SAVESTATE_OBJECT_POINTER_ADDR, 4),
            (SECURITY_KEY_POINTER_ADDR, 4),
            (PLAYER_AVATAR_ADDR, 1),
            (SCRIPT_LOCK_FIELD_CONTROLS, 1),
            (IN_BATTLE_BIT_ADDR, 1),
            (
                OBJECT_EVENTS_ADDR
                + (OBJECT_EVENTS_PLAYER_INDEX * OBJECT_EVENT_SIZE)
                + OBJECT_EVENT_FACING_DIR_OFFSET,
                1,
            ),
            (
                OBJECT_EVENTS_ADDR
                + (OBJECT_EVENTS_PLAYER_INDEX * OBJECT_EVENT_SIZE)
                + OBJECT_EVENT_ELEVATION_OFFSET,
                1,
            ),
            (GSAFARI_ZONE_STEP_COUNTER_ADDR, 2),
        ]
        res = mgba.mgba_read_ranges_bytes(ranges)
        base_ptr = _u32le_from(res[0], 0) if len(res) > 0 else 0
        sec_ptr = _u32le_from(res[1], 0) if len(res) > 1 else 0
        avatar_flags = _u8_from(res[2], 0) if len(res) > 2 else 0
        bike_type = _bike_type_from_avatar_flags(int(avatar_flags))
        field_locked = (_u8_from(res[3], 0) if len(res) > 3 else 0) != 0
        in_battle = ((_u8_from(res[4], 0) if len(res) > 4 else 0) & IN_BATTLE_BITMASK) != 0
        facing_raw = _u8_from(res[5], 0) if len(res) > 5 else 0
        facing = FACING_DIRECTION_MAP.get(facing_raw & 0x07, "unknown")
        elev_byte = _u8_from(res[6], 0) if len(res) > 6 else 0
        elevation = elev_byte & OBJECT_EVENT_CURRENT_ELEVATION_MASK
        safari_steps_remaining = int(_u16le_from(res[7], 0)) if len(res) > 7 else 0
    except Exception:
        return {
            "in_battle": is_in_battle(),
            "field_locked": are_field_controls_locked(),
            "x": get_player_position()[0],
            "y": get_player_position()[1],
            "facing": get_player_facing_direction(),
            "elevation": get_player_elevation(),
            "surfing": is_player_surfing(),
            "biking": is_player_biking(),
            "bike_type": get_player_bike_type(),
            "diving": is_player_diving(),
            "money": get_player_money(),
            "badges": get_player_badges(),
            "important_events": get_important_events(),
            "safari_zone_steps_remaining": get_safari_zone_steps_remaining(),
            "safari_zone_active": is_safari_zone_active(),
            "map_group": get_current_map_group_num()[0],
            "map_num": get_current_map_group_num()[1],
            "security_key": get_security_key(),
        }

    if base_ptr == 0 or sec_ptr == 0:
        return {
            "in_battle": in_battle,
            "field_locked": field_locked,
            "x": get_player_position()[0],
            "y": get_player_position()[1],
            "facing": facing,
            "elevation": elevation,
            "surfing": (avatar_flags & PLAYER_AVATAR_FLAG_SURFING) != 0,
            "biking": (avatar_flags & PLAYER_AVATAR_FLAG_BIKING) != 0,
            "bike_type": bike_type,
            "diving": (avatar_flags & PLAYER_AVATAR_FLAG_DIVING) != 0,
            "money": get_player_money(),
            "badges": get_player_badges(),
            "important_events": get_important_events(sb1_ptr=int(base_ptr) if base_ptr else None),
            "safari_zone_steps_remaining": int(safari_steps_remaining),
            "safari_zone_active": bool(int(safari_steps_remaining) > 0),
            "map_group": get_current_map_group_num()[0],
            "map_num": get_current_map_group_num()[1],
            "security_key": get_security_key(),
            "sb1_ptr": int(base_ptr),
            "sb2_ptr": int(sec_ptr),
        }

    badge_base_byte = min(flag_id // 8 for _badge_id, _label, flag_id in BADGES)
    low_events_base_byte = min(int(flag_id) // 8 for flag_id in _LOW_IMPORTANT_EVENT_FLAGS)
    low_events_last_byte = max(int(flag_id) // 8 for flag_id in _LOW_IMPORTANT_EVENT_FLAGS)
    low_events_num_bytes = (low_events_last_byte - low_events_base_byte) + 1
    elite4_base_byte = int(FLAG_DEFEATED_LORELEI) // 8
    ranges2 = [
        (base_ptr + 0x0000, 8),  # x,y + map group/num
        (base_ptr + SAVESTATE_MONEY_OFFSET, 4),
        (base_ptr + SAVESTATE_FLAGS_OFFSET + low_events_base_byte, low_events_num_bytes),
        (base_ptr + SAVESTATE_FLAGS_OFFSET + badge_base_byte, 2),
        (base_ptr + SAVESTATE_FLAGS_OFFSET + elite4_base_byte, 1),
        (sec_ptr + SECURITY_KEY_OFFSET, 4),
    ]
    res2 = mgba.mgba_read_ranges_bytes(ranges2)

    base_block = res2[0] if len(res2) > 0 else b""
    x = _u16le_from(base_block, 0)
    y = _u16le_from(base_block, 2)
    map_group = int(_u8_from(base_block, 4)) if len(base_block) >= 5 else -1
    map_num = int(_u8_from(base_block, 5)) if len(base_block) >= 6 else -1

    enc_money = _u32le_from(res2[1], 0) if len(res2) > 1 else 0
    sec_key = _u32le_from(res2[5], 0) if len(res2) > 5 else 0
    money = enc_money ^ sec_key

    low_events_flags_bytes = res2[2] if len(res2) > 2 else b""
    flags_bytes = res2[3] if len(res2) > 3 else b""
    elite4_flag_byte = int(_u8_from(res2[4], 0)) if len(res2) > 4 else 0
    badges: Dict[str, bool] = {}
    for badge_id, _label, flag_id in BADGES:
        byte_offset = flag_id // 8
        bit = flag_id % 8
        idx = byte_offset - badge_base_byte
        have = False
        if 0 <= idx < len(flags_bytes):
            have = (flags_bytes[idx] & (1 << bit)) != 0
        badges[str(badge_id)] = bool(have)

    hall_of_fame = _flag_get_from_bytes(badge_base_byte, flags_bytes, FLAG_SYS_GAME_CLEAR)

    def _read_prefetched_flag(flag_id: int) -> bool:
        if flag_id == FLAG_SYS_GAME_CLEAR:
            return hall_of_fame
        if low_events_base_byte <= (int(flag_id) // 8) <= low_events_last_byte:
            return _flag_get_from_bytes(low_events_base_byte, low_events_flags_bytes, flag_id)
        if (int(flag_id) // 8) == elite4_base_byte:
            return (elite4_flag_byte & (1 << (int(flag_id) % 8))) != 0
        return _flag_get_from_bytes(badge_base_byte, flags_bytes, flag_id)

    important_events = {
        "EVENT_GOT_STARTER": _read_prefetched_flag(FLAG_SYS_POKEMON_GET),
        "EVENT_GOT_POKEDEX": _read_prefetched_flag(FLAG_SYS_POKEDEX_GET),
        "EVENT_SS_ANNE_LEFT": _read_prefetched_flag(FLAG_HIDE_SS_ANNE),
        "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI": _read_prefetched_flag(FLAG_HIDE_HIDEOUT_GIOVANNI),
        "EVENT_GOT_POKE_FLUTE": _read_prefetched_flag(FLAG_GOT_POKE_FLUTE),
        "EVENT_GOT_HM03": _read_prefetched_flag(FLAG_GOT_HM03),
        "EVENT_BEAT_SILPH_CO_GIOVANNI": _read_prefetched_flag(FLAG_HIDE_SAFFRON_ROCKETS),
        "EVENT_BEAT_LANCE": _story_league_gate_done_from_reader(_read_prefetched_flag, FLAG_DEFEATED_LANCE),
        "EVENT_BEAT_CHAMPION_RIVAL": _story_league_gate_done_from_reader(_read_prefetched_flag, FLAG_DEFEATED_CHAMP),
        "EVENT_BEAT_ELITE_FOUR": _elite_four_done_from_reader(_read_prefetched_flag),
        "EVENT_HALL_OF_FAME": hall_of_fame,
    }
    safari_zone_active = bool(_flag_get_from_sb1(int(base_ptr), FLAG_SYS_SAFARI_MODE))

    return {
        "in_battle": in_battle,
        "field_locked": field_locked,
        "x": x,
        "y": y,
        "facing": facing,
        "elevation": elevation,
        "surfing": (avatar_flags & PLAYER_AVATAR_FLAG_SURFING) != 0,
        "biking": (avatar_flags & PLAYER_AVATAR_FLAG_BIKING) != 0,
        "bike_type": bike_type,
        "diving": (avatar_flags & PLAYER_AVATAR_FLAG_DIVING) != 0,
        "money": money,
        "badges": badges,
        "important_events": important_events,
        "safari_zone_steps_remaining": int(safari_steps_remaining),
        "safari_zone_active": bool(safari_zone_active or int(safari_steps_remaining) > 0),
        "map_group": map_group,
        "map_num": map_num,
        "security_key": sec_key,
        "sb1_ptr": int(base_ptr),
        "sb2_ptr": int(sec_ptr),
    }


def _read_flash_state(*, sb1_ptr: Optional[int] = None) -> Tuple[bool, bool]:
    """
    Return (flash_needed, flash_active) for the current map.

    Mirror pokefirered logic:
    - flash_needed comes from gMapHeader.cave
    - flash_active comes from FLAG_SYS_USE_FLASH (saveblock1 flags)
    """
    flash_needed, flash_active, _strength_enabled = _read_flash_and_strength_state(sb1_ptr=sb1_ptr)
    return bool(flash_needed), bool(flash_active)


def _read_flash_and_strength_active_flags(*, sb1_ptr: Optional[int] = None) -> Tuple[bool, bool]:
    """
    Return (flash_active, strength_active) from the system flags byte.

    In pokefirered/include/constants/flags.h:
    - FLAG_SYS_USE_FLASH    = (SYSTEM_FLAGS + 0x28) -> 0x888
    - FLAG_SYS_USE_STRENGTH = (SYSTEM_FLAGS + 0x29) -> 0x889

    These two flags share the same byte offset, so we read that byte once.
    """
    sb1_ptr_int = int(sb1_ptr) if sb1_ptr else int(mgba.mgba_read32(GSAVEBLOCK1_PTR_ADDR))
    if sb1_ptr_int == 0:
        return False, False

    flags_base = int(sb1_ptr_int) + SAVESTATE_FLAGS_OFFSET
    byte_offset = int(FLAG_SYS_USE_FLASH) // 8  # same as FLAG_SYS_USE_STRENGTH // 8
    flag_byte = int(mgba.mgba_read8(flags_base + byte_offset))

    bit_flash = int(FLAG_SYS_USE_FLASH) % 8
    bit_strength = int(FLAG_SYS_USE_STRENGTH) % 8

    flash_active = (flag_byte & (1 << bit_flash)) != 0
    strength_active = (flag_byte & (1 << bit_strength)) != 0
    return bool(flash_active), bool(strength_active)


def _read_flash_and_strength_state(*, sb1_ptr: Optional[int] = None) -> Tuple[bool, bool, bool]:
    """
    Return (flash_needed, flash_active, strength_enabled) for the current map.

    - flash_needed comes from gMapHeader.cave
    - flash_active comes from FLAG_SYS_USE_FLASH (saveblock1 flags)
    - strength_enabled comes from FLAG_SYS_USE_STRENGTH (saveblock1 flags)
    """
    try:
        flash_needed = int(mgba.mgba_read8(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_CAVE_OFFSET)) != 0
    except Exception:
        flash_needed = False

    try:
        flash_active, strength_enabled = _read_flash_and_strength_active_flags(sb1_ptr=sb1_ptr)
    except Exception:
        flash_active = False
        strength_enabled = False

    # Outside a cave, "flash active" isn't meaningful and the flag should be cleared by the engine anyway.
    if not flash_needed:
        flash_active = False

    return bool(flash_needed), bool(flash_active), bool(strength_enabled)


def _read_visibility_window_state(
    *,
    sb1_ptr: Optional[int] = None,
    sb2_ptr: Optional[int] = None,
    flash_needed: bool = False,
    flash_active: bool = False,
) -> Dict[str, Any]:
    """
    Compute a viewport window size (in meta-tiles) for "limited visibility" areas.

    This is a universal model of FireRed's darkness systems:
    - Standard flash darkness uses SaveBlock1.flashLevel (u8 at offset 0x30)
    - Battle Pyramid uses SaveBlock2.frontier.pyramidLightRadius (u8 at offset 0xE68)

    We convert the engine's pixel radius into an odd-sized square window (1/3/5/7/9...)
    and clamp it to the normal screen bounds (15x10).

    Returns a dict intended for inclusion in the API payload (camelCase keys).
    """
    try:
        sb1 = int(sb1_ptr) if sb1_ptr else int(mgba.mgba_read32(GSAVEBLOCK1_PTR_ADDR))
    except Exception:
        sb1 = 0
    try:
        sb2 = int(sb2_ptr) if sb2_ptr else int(mgba.mgba_read32(GSAVEBLOCK2_PTR_ADDR))
    except Exception:
        sb2 = 0

    ranges: List[Tuple[int, int]] = [(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_MAP_LAYOUT_ID_OFFSET, 2)]
    if sb1:
        ranges.append((sb1 + SB1_FLASH_LEVEL_OFFSET, 1))
    if sb2:
        ranges.append((sb2 + SB2_PYRAMID_LIGHT_RADIUS_OFFSET, 1))

    map_layout_id: Optional[int] = None
    flash_level = 0
    pyramid_light_radius: Optional[int] = None

    try:
        res = mgba.mgba_read_ranges_bytes(ranges)
        map_layout_id = int(_u16le_from(res[0], 0)) if len(res) > 0 else None
        if sb1 and len(res) > 1:
            flash_level = int(_u8_from(res[1], 0))
        if sb2:
            idx = 2 if sb1 else 1
            if len(res) > idx:
                pyramid_light_radius = int(_u8_from(res[idx], 0))
    except Exception:
        map_layout_id = None
        flash_level = 0
        pyramid_light_radius = None

    # Detect Battle Pyramid by layout id (source of truth: pokefirered layouts.json).
    in_pyramid = False
    if map_layout_id is not None:
        floor_id = game_data.get_layout_id("LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_FLOOR")
        top_id = game_data.get_layout_id("LAYOUT_BATTLE_FRONTIER_BATTLE_PYRAMID_TOP")
        in_pyramid = (floor_id is not None and map_layout_id == floor_id) or (top_id is not None and map_layout_id == top_id)

    width_tiles = int(MAX_VIEWPORT_WIDTH)
    height_tiles = int(MAX_VIEWPORT_HEIGHT)
    reduced = False
    cause = "none"

    def _apply_square_window(size: int) -> None:
        nonlocal width_tiles, height_tiles, reduced
        width_tiles = int(min(int(MAX_VIEWPORT_WIDTH), int(size)))
        height_tiles = int(min(int(MAX_VIEWPORT_HEIGHT), int(size)))
        reduced = width_tiles != int(MAX_VIEWPORT_WIDTH) or height_tiles != int(MAX_VIEWPORT_HEIGHT)

    if in_pyramid and pyramid_light_radius is not None:
        # pyramidLightRadius is in pixels (same parameter as SetFlashScanlineEffectWindowBoundaries).
        radius_tiles = max(0, int(pyramid_light_radius) // 16)
        _apply_square_window(max(1, 2 * radius_tiles + 1))
        cause = "pyramid"
    elif bool(flash_needed) and (not bool(flash_active)):
        # Fallback: if we cannot read flashLevel but the map requires flash and it isn't active,
        # behave like the legacy "dark cave" mode (3x3).
        _apply_square_window(3)
        cause = "darkness"
    elif bool(flash_active) and flash_level > 0:
        # Only apply runtime flash radius when Flash is actually active.
        # On FireRed, flashLevel can remain non-zero even while the system Flash flag is off.
        idx = int(flash_level)
        if idx < 0:
            idx = 0
        if idx >= len(_FLASH_LEVEL_TO_RADIUS_PX):
            idx = len(_FLASH_LEVEL_TO_RADIUS_PX) - 1
        radius_px = int(_FLASH_LEVEL_TO_RADIUS_PX[idx])
        radius_tiles = max(0, radius_px // 16)
        _apply_square_window(max(1, 2 * radius_tiles + 1))
        cause = "darkness"

    # Human-level hint about whether using Flash could help (only meaningful in caves).
    if cause == "pyramid":
        hint = "not_applicable"
    elif bool(flash_needed):
        hint = "flash_active" if bool(flash_active) else "flash_can_help"
    else:
        hint = "not_applicable"

    return {
        "reduced": bool(reduced),
        "widthTiles": int(width_tiles),
        "heightTiles": int(height_tiles),
        "cause": str(cause),
        "hint": str(hint),
        # Debug fields (do not expose to GPT unless explicitly needed)
        "flashLevel": int(flash_level),
        "pyramidLightRadius": int(pyramid_light_radius) if pyramid_light_radius is not None else None,
        "mapLayoutId": int(map_layout_id) if map_layout_id is not None else None,
    }


def _read_strength_enabled(*, sb1_ptr: Optional[int] = None) -> bool:
    """
    Mirror pokefirered logic: Strength is enabled on the field when FLAG_SYS_USE_STRENGTH is set.

    See pokefirered/src/field_player_avatar.c: TryPushBoulder() uses FlagGet(FLAG_SYS_USE_STRENGTH).
    """
    try:
        _flash_active, strength_enabled = _read_flash_and_strength_active_flags(sb1_ptr=sb1_ptr)
        return bool(strength_enabled)
    except Exception:
        return False


def get_player_money() -> int:
    base_ptr = mgba.mgba_read32(SAVESTATE_OBJECT_POINTER_ADDR)
    enc_money = mgba.mgba_read32(base_ptr + SAVESTATE_MONEY_OFFSET)
    key = get_security_key()
    return enc_money ^ key


def read_player_flag(bit_offset: int) -> bool:
    base_ptr = mgba.mgba_read32(SAVESTATE_OBJECT_POINTER_ADDR)
    flags_base = base_ptr + SAVESTATE_FLAGS_OFFSET
    byte_offset = bit_offset // 8
    bit = bit_offset % 8
    val = mgba.mgba_read8(flags_base + byte_offset)
    return (val & (1 << bit)) != 0


def get_player_badges() -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for badge_id, _label, flag_id in BADGES:
        out[str(badge_id)] = bool(read_player_flag(flag_id))
    return out


def get_current_map_group_num() -> Tuple[int, int]:
    """
    Lit le map group et map number depuis gSaveBlock1Ptr->location.
    Struct WarpData à l'offset 0x04 dans SaveBlock1:
      - mapGroup (s8) à offset 0
      - mapNum (s8) à offset 1
    """
    try:
        base = mgba.mgba_read32(SAVESTATE_OBJECT_POINTER_ADDR)
        location_addr = base + 0x04
        map_group = mgba.mgba_read8(location_addr + 0)
        map_num = mgba.mgba_read8(location_addr + 1)
        return map_group, map_num
    except Exception:
        return (-1, -1)


def get_player_facing_direction() -> str:
    direction = mgba.mgba_read8(
        OBJECT_EVENTS_ADDR + (OBJECT_EVENTS_PLAYER_INDEX * OBJECT_EVENT_SIZE) + OBJECT_EVENT_FACING_DIR_OFFSET
    )
    masked = direction & 0x07
    return FACING_DIRECTION_MAP.get(masked, "unknown")


def get_player_position() -> Tuple[int, int]:
    base = mgba.mgba_read32(SAVESTATE_OBJECT_POINTER_ADDR)
    x = mgba.mgba_read16(base + 0x000)
    y = mgba.mgba_read16(base + 0x002)
    return x, y


def get_player_elevation() -> int:
    addr = OBJECT_EVENTS_ADDR + (OBJECT_EVENTS_PLAYER_INDEX * OBJECT_EVENT_SIZE)
    elev_byte = mgba.mgba_read8(addr + OBJECT_EVENT_ELEVATION_OFFSET)
    return elev_byte & OBJECT_EVENT_CURRENT_ELEVATION_MASK


def is_player_surfing() -> bool:
    flags = mgba.mgba_read8(PLAYER_AVATAR_ADDR)
    return (flags & PLAYER_AVATAR_FLAG_SURFING) != 0


def is_player_biking() -> bool:
    flags = mgba.mgba_read8(PLAYER_AVATAR_ADDR)
    return (flags & PLAYER_AVATAR_FLAG_BIKING) != 0


def is_player_diving() -> bool:
    flags = mgba.mgba_read8(PLAYER_AVATAR_ADDR)
    return (flags & PLAYER_AVATAR_FLAG_DIVING) != 0


def are_field_controls_locked() -> bool:
    return mgba.mgba_read8(SCRIPT_LOCK_FIELD_CONTROLS) != 0


def _is_palette_fade_active() -> bool:
    """
    Return True when a palette fade / transition is active.

    This is a strong signal that inputs are fully blocked (falling through a hole,
    warp transitions, fade-to-black, etc.).

    Note: gPaletteFade is a packed bitfield struct; we only need the `active` flag.
    In this codebase's `struct PaletteFadeControl` layout, `active` is bit 31 of the
    first 32-bit bitfield word (at offset +0x04 from gPaletteFade).
    """
    try:
        raw = mgba.mgba_read_range_bytes(GPALETTE_FADE_ADDR + PALETTE_FADE_BITFIELDS_OFFSET, 4)
        word = _u32le_from(raw, 0)
        return (word & PALETTE_FADE_ACTIVE_MASK32) != 0
    except Exception:
        return False


def _read_global_script_context_native() -> Tuple[int, int]:
    """
    Return (mode, nativePtr) for the global script context.

    Used to detect script waits satisfied by player input (e.g. waitbuttonpress / waitmessage)
    vs non-input waits (movement, palette fades, etc.).
    """
    try:
        raw = mgba.mgba_read_range_bytes(SGLOBAL_SCRIPT_CONTEXT_ADDR, 8)
        mode = _u8_from(raw, SCRIPT_CONTEXT_MODE_OFFSET)
        native_ptr = _u32le_from(raw, SCRIPT_CONTEXT_NATIVE_PTR_OFFSET)
        return int(mode), int(native_ptr)
    except Exception:
        return SCRIPT_MODE_STOPPED, 0


def _is_waiting_for_a_or_b_press(script_mode: int, native_ptr: int) -> bool:
    if int(script_mode) != SCRIPT_MODE_NATIVE:
        return False
    masked = int(native_ptr) & 0xFFFFFFFE
    return masked in {
        (WAIT_FOR_A_OR_B_PRESS_ADDR & 0xFFFFFFFE),
        (IS_FIELD_MESSAGE_BOX_HIDDEN_ADDR & 0xFFFFFFFE),
    }


def are_all_controls_locked(
    *,
    field_controls_locked: Optional[bool] = None,
    in_battle: Optional[bool] = None,
    callback2: Optional[int] = None,
    dialog_state: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Best-effort detection for when *all* player inputs are blocked (not just overworld).

    Motivation:
    - `fieldControlsLocked` (sLockFieldControls) only blocks overworld controls.
    - During transitions/animations (warp, falling, scripted movement), the game can ignore
      *all* inputs, and we want to detect that for `/sendCommands` waiting logic.

    Heuristics (ordered by strength):
    1) Palette fade active => fully locked
    2) Certain non-interactive main callbacks => fully locked
    3) If we're in an interactive menu/dialog (visibleText / choiceMenu / menuType) => not fully locked
    4) If overworld controls aren't locked => not fully locked
    5) If script engine is waiting on a dialog/input condition => not fully locked
    6) Otherwise, assume fully locked
    """
    try:
        if _is_palette_fade_active():
            return True

        if callback2 is None:
            callback2 = int(mgba.mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET))
        cb2_masked = int(callback2) & 0xFFFFFFFE
        if cb2_masked in {
            (CB2_DO_CHANGE_MAP_ADDR & 0xFFFFFFFE),
            (CB2_LOAD_MAP_ADDR & 0xFFFFFFFE),
        }:
            return True

        if in_battle is None:
            in_battle = is_in_battle()

        # Any evidence of an interactive UI/dialog means inputs are *not* fully blocked.
        interactive = False
        text_printer_active: Optional[bool] = None
        if isinstance(dialog_state, dict):
            menu_type = dialog_state.get("menuType")
            if isinstance(menu_type, str) and menu_type and menu_type != "dialog":
                interactive = True
            if dialog_state.get("choiceMenu") is not None:
                interactive = True

            # Stale text buffers can persist across transitions (ex: warp/map change) even when no
            # dialog is visible. Only treat "dialog" text as interactive evidence when we know a
            # TextPrinter is actively rendering something on-screen.
            tpa = dialog_state.get("textPrinterActive")
            if isinstance(tpa, bool):
                text_printer_active = tpa
            if isinstance(menu_type, str) and menu_type == "dialog" and bool(text_printer_active):
                interactive = True

        if bool(in_battle):
            # In battle, ignore `field_controls_locked` (it's an overworld concept).
            # If we can't see any actionable UI/text, assume animations are consuming input.
            return not interactive

        if field_controls_locked is None:
            field_controls_locked = are_field_controls_locked()
        if not bool(field_controls_locked):
            return False

        if interactive:
            return False

        script_mode, native_ptr = _read_global_script_context_native()
        if _is_waiting_for_a_or_b_press(script_mode, native_ptr):
            return False

        return True
    except Exception:
        return False


def is_in_battle() -> bool:
    bitmask = mgba.mgba_read8(IN_BATTLE_BIT_ADDR)
    return (bitmask & IN_BATTLE_BITMASK) != 0
