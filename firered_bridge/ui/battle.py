from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..constants.addresses import *  # noqa: F403
from ..game_data import get_ability_name, get_item_name, get_move_name, get_species_name
from ..memory import mgba
from ..player.party import get_status_name_from_mask
from ..text import encoding as text_encoding
from ..util.bytes import _u16le_from, _u32le_from, _u8_from

def _battle_position_name(pos: int) -> str:
    # pokefirered/include/constants/battle.h (enum BattlerPosition)
    return {
        0: "PLAYER_LEFT",
        1: "OPPONENT_LEFT",
        2: "PLAYER_RIGHT",
        3: "OPPONENT_RIGHT",
    }.get(int(pos) & 0xFF, f"UNKNOWN_{pos}")


def _battle_side_from_pos(pos: int) -> str:
    return "player" if (int(pos) & BATTLER_BIT_SIDE) == 0 else "enemy"


def _battle_flank_from_pos(pos: int) -> str:
    return "left" if (int(pos) & BATTLER_BIT_FLANK) == 0 else "right"


def _battle_screen_position_name(pos: int) -> str:
    """
    Map battler positions to a "screen / player perspective" naming.

    pokefirered/include/constants/battle.h notes that opponent flanks are drawn corresponding
    to their perspective, meaning:
      - OPPONENT_RIGHT appears on the left side of the screen
      - OPPONENT_LEFT appears on the right side of the screen
    """
    pos_i = int(pos) & 0xFF
    if _battle_side_from_pos(pos_i) == "enemy":
        if _battle_flank_from_pos(pos_i) == "left":
            return "OPPONENT_RIGHT"
        return "OPPONENT_LEFT"
    return _battle_position_name(pos_i)


def _battle_screen_flank_from_pos(pos: int) -> str:
    side = _battle_side_from_pos(pos)
    flank = _battle_flank_from_pos(pos)
    if side == "enemy":
        return "left" if flank == "right" else "right"
    return flank


def _parse_battle_pokemon(raw: bytes) -> Dict[str, Any]:
    if not raw or len(raw) < BATTLE_POKEMON_SIZE:
        return {
            "speciesId": 0,
            "species": None,
            "nickname": None,
            "level": 0,
            "hp": {"current": 0, "max": 0},
            "status": "NONE",
            "statusRaw": 0,
            "movesRaw": [0, 0, 0, 0],
            "moves": [None, None, None, None],
            "pp": [0, 0, 0, 0],
            "itemId": 0,
            "itemName": None,
            "abilityId": 0,
            "ability": None,
            "types": [],
        }

    species_id = _u16le_from(raw, 0x00)
    moves_raw = [_u16le_from(raw, 0x0C + (i * 2)) for i in range(4)]
    pp = [_u8_from(raw, 0x24 + i) for i in range(4)]
    hp_cur = _u16le_from(raw, 0x28)
    level = _u8_from(raw, 0x2A)
    hp_max = _u16le_from(raw, 0x2C)
    item_id = _u16le_from(raw, 0x2E)
    nickname_raw = raw[0x30 : 0x30 + 11]
    ability_id = _u8_from(raw, 0x20)
    t1 = _u8_from(raw, 0x21)
    t2 = _u8_from(raw, 0x22)
    status_raw = _u32le_from(raw, 0x4C)

    types: List[str] = []
    if species_id != 0:
        t1_name = POKEMON_TYPE_MAP.get(int(t1), f"TYPE_UNKNOWN({t1})")
        if t1_name:
            types.append(t1_name)
        if int(t2) != int(t1) and int(t2) != 255:
            t2_name = POKEMON_TYPE_MAP.get(int(t2), f"TYPE_UNKNOWN({t2})")
            if t2_name:
                types.append(t2_name)

    return {
        "speciesId": int(species_id),
        "species": get_species_name(int(species_id)) if species_id else None,
        "nickname": text_encoding.decode_gba_string(nickname_raw, 11) if species_id else None,
        "level": int(level),
        "hp": {"current": int(hp_cur), "max": int(hp_max)},
        "status": get_status_name_from_mask(int(status_raw)),
        "statusRaw": int(status_raw),
        "movesRaw": [int(m) for m in moves_raw],
        "moves": [get_move_name(int(m)) if int(m) else None for m in moves_raw],
        "pp": [int(v) for v in pp],
        "itemId": int(item_id),
        "itemName": get_item_name(int(item_id)) if item_id else None,
        "abilityId": int(ability_id),
        "ability": get_ability_name(int(ability_id)) if ability_id else None,
        "types": types,
    }


def get_battle_state(*, in_battle: Optional[bool] = None, snapshot: Optional[List[bytes]] = None) -> Dict[str, Any]:
    """
    Read battle state (active battlers + their current BattlePokemon data).

    Designed to be robust for single-player speedrun use:
    - Uses gBattlerPositions to classify player/enemy side.
    - Filters absent battlers via gAbsentBattlerFlags.
    - Works for single and double battles.
    """
    if in_battle is None:
        in_battle = is_in_battle()

    if not in_battle:
        return {"isActive": False, "data": {"player": [], "enemy": []}}

    ranges = [
        (GBATTLETYPEFLAGS_ADDR, 4),
        (GBATTLERSCOUNT_ADDR, 1),
        (GABSENTBATTLERFLAGS_ADDR, 1),
        (GBATTLERPOSITIONS_ADDR, BATTLE_MAX_BATTLERS),
        (GBATTLERPARTYINDEXES_ADDR, BATTLE_MAX_BATTLERS * 2),
        (GBATTLEMONS_ADDR, GBATTLEMONS_SIZE),
        (GACTIVEBATTLER_ADDR, 1),
    ]

    if snapshot is None:
        try:
            raw = mgba.mgba_read_ranges_bytes(ranges)
        except Exception:
            raw = []
    else:
        raw = snapshot

    if len(raw) < len(ranges):
        return {"isActive": True, "data": {"player": [], "enemy": []}}

    battle_type_flags = _u32le_from(raw[0], 0) if len(raw[0]) >= 4 else 0
    battlers_count = int(raw[1][0]) if raw[1] else 0
    absent_flags = int(raw[2][0]) if raw[2] else 0
    positions = list(raw[3][:BATTLE_MAX_BATTLERS]) if raw[3] else [0, 1, 2, 3]

    party_indexes: List[int] = []
    if raw[4] and len(raw[4]) >= (BATTLE_MAX_BATTLERS * 2):
        for i in range(BATTLE_MAX_BATTLERS):
            party_indexes.append(int(_u16le_from(raw[4], i * 2)))
    else:
        party_indexes = [0, 0, 0, 0]

    mons_raw = raw[5] if raw[5] else b""
    active_battler = int(raw[6][0]) if raw[6] else 0

    def _is_absent(battler_id: int) -> bool:
        return (absent_flags & (1 << battler_id)) != 0

    player: List[Dict[str, Any]] = []
    enemy: List[Dict[str, Any]] = []

    max_id = BATTLE_MAX_BATTLERS
    if 0 < battlers_count <= BATTLE_MAX_BATTLERS:
        max_id = battlers_count

    for battler_id in range(max_id):
        if _is_absent(battler_id):
            continue
        off = battler_id * BATTLE_POKEMON_SIZE
        mon = _parse_battle_pokemon(mons_raw[off : off + BATTLE_POKEMON_SIZE])
        if int(mon.get("speciesId") or 0) == 0:
            continue

        pos = int(positions[battler_id]) if battler_id < len(positions) else battler_id
        side = _battle_side_from_pos(pos)
        flank = _battle_flank_from_pos(pos)

        entry = {
            "battlerId": int(battler_id),
            "position": _battle_position_name(pos),
            "side": side,
            "flank": flank,
            "partyIndex": int(party_indexes[battler_id]) if battler_id < len(party_indexes) else 0,
            **mon,
        }

        if side == "player":
            player.append(entry)
        else:
            enemy.append(entry)

    def _sort_key(entry: Dict[str, Any]) -> int:
        pos_name = str(entry.get("position") or "")
        return 0 if pos_name.endswith("_LEFT") else 1

    player.sort(key=_sort_key)
    enemy.sort(key=_sort_key)

    return {
        "isActive": True,
        "typeFlags": int(battle_type_flags),
        "isTrainerBattle": bool(battle_type_flags & BATTLE_TYPE_TRAINER),
        "isDoubleBattle": bool(battle_type_flags & BATTLE_TYPE_DOUBLE),
        "isSafariBattle": bool(battle_type_flags & BATTLE_TYPE_SAFARI),
        "battlersCount": int(battlers_count),
        "activeBattlerId": int(active_battler),
        "data": {"player": player, "enemy": enemy},
    }


def _ptr_matches_any(ptr: int, candidates: Sequence[int]) -> bool:
    if not candidates:
        return False
    masked = int(ptr) & 0xFFFFFFFE
    for cand in candidates:
        if masked == (int(cand) & 0xFFFFFFFE):
            return True
    return False


def _battle_mon_display_name_from_raw(mon_raw: bytes) -> Optional[str]:
    if not mon_raw or len(mon_raw) < BATTLE_POKEMON_SIZE:
        return None
    species_id = int(_u16le_from(mon_raw, 0x00))
    if species_id == 0:
        return None
    nickname_raw = mon_raw[0x30 : 0x30 + 11]
    nick = text_encoding.decode_gba_string(nickname_raw, 11)
    if nick:
        return nick
    return get_species_name(species_id)


def _build_battle_ui_state(
    *,
    battle_type_flags: int,
    battlers_count: int,
    absent_flags: int,
    positions: Sequence[int],
    battle_mons_raw: bytes,
    active_battler: int,
    controller_func: int,
    action_cursor: int,
    move_cursor: int,
    multi_cursor: int,
) -> Optional[Dict[str, Any]]:
    """
    Infer battle UI state from controller function pointers + battle cursors.

    This lets us reliably reconstruct menus like:
    - "What will X do?" + FIGHT/BAG/POKéMON/RUN
    - Move selection list
    - Target selection (double battles)
    - Battle yes/no box
    """
    active_battler = int(active_battler) & 0xFF
    action_cursor = int(action_cursor) & 0xFF
    move_cursor = int(move_cursor) & 0xFF
    multi_cursor = int(multi_cursor) & 0xFF

    if _ptr_matches_any(controller_func, BATTLE_PLAYER_HANDLE_YES_NO_INPUT_ADDRS):
        options = ["YES", "NO"]
        cursor = 0 if multi_cursor == 0 else 1
        return {
            "type": "battleYesNo",
            "activeBattlerId": active_battler,
            "cursorPosition": int(cursor),
            "selectedOption": options[cursor] if 0 <= cursor < len(options) else None,
            "options": options,
            "layout": "list",
        }

    if _ptr_matches_any(controller_func, BATTLE_HANDLE_INPUT_CHOOSE_TARGET_ADDRS):
        max_id = int(battlers_count) if 0 < int(battlers_count) <= BATTLE_MAX_BATTLERS else BATTLE_MAX_BATTLERS
        targets: List[Dict[str, Any]] = []
        for battler_id in range(max_id):
            if (int(absent_flags) & (1 << battler_id)) != 0:
                continue
            pos = int(positions[battler_id]) if battler_id < len(positions) else battler_id
            off = battler_id * BATTLE_POKEMON_SIZE
            mon_raw = battle_mons_raw[off : off + BATTLE_POKEMON_SIZE] if battle_mons_raw else b""
            name = _battle_mon_display_name_from_raw(mon_raw) or _battle_screen_position_name(pos)
            targets.append(
                {
                    "battlerId": int(battler_id),
                    "position": _battle_screen_position_name(pos),
                    "side": _battle_side_from_pos(pos),
                    "flank": _battle_screen_flank_from_pos(pos),
                    "name": name,
                }
            )

        def _target_grid_key(t: Dict[str, Any]) -> int:
            side = str(t.get("side") or "")
            flank = str(t.get("flank") or "")
            row = 0 if side == "enemy" else 1
            col = 0 if flank == "left" else 1
            return (row * 2) + col

        targets.sort(key=_target_grid_key)

        cursor_index = 0
        for i, t in enumerate(targets):
            if int(t.get("battlerId", -1)) == multi_cursor:
                cursor_index = i
                break

        options = [f"{t['position']}: {t['name']}" for t in targets] if targets else []
        selected = options[cursor_index] if 0 <= cursor_index < len(options) else None
        return {
            "type": "battleTarget",
            "activeBattlerId": active_battler,
            "cursorBattlerId": int(multi_cursor),
            "cursorPosition": int(cursor_index),
            "selectedOption": selected,
            "options": options,
            "targets": targets,
            "layout": "list",
        }

    if _ptr_matches_any(controller_func, BATTLE_HANDLE_INPUT_CHOOSE_MOVE_ADDRS):
        off = active_battler * BATTLE_POKEMON_SIZE
        mon = _parse_battle_pokemon(battle_mons_raw[off : off + BATTLE_POKEMON_SIZE] if battle_mons_raw else b"")
        move_names = [str(m) if m else "—" for m in (mon.get("moves") or [])]
        pp = [int(v) for v in (mon.get("pp") or [])]
        while len(move_names) < 4:
            move_names.append("—")
        while len(pp) < 4:
            pp.append(0)

        cursor = int(move_cursor) if 0 <= int(move_cursor) < len(move_names) else 0
        return {
            "type": "battleMoves",
            "activeBattlerId": active_battler,
            "cursorPosition": int(cursor),
            "selectedOption": move_names[cursor] if 0 <= cursor < len(move_names) else None,
            "options": move_names,
            "pp": pp,
            "layout": "grid2x2",
        }

    if _ptr_matches_any(controller_func, BATTLE_HANDLE_INPUT_CHOOSE_ACTION_ADDRS):
        if int(battle_type_flags) & BATTLE_TYPE_SAFARI:
            options = ["BALL", "POKéBLOCK", "GO NEAR", "RUN"]
        else:
            options = ["FIGHT", "BAG", "POKéMON", "RUN"]
        cursor = int(action_cursor) if 0 <= int(action_cursor) < 4 else 0
        return {
            "type": "battleActions",
            "activeBattlerId": active_battler,
            "cursorPosition": int(cursor),
            "selectedOption": options[cursor] if 0 <= cursor < len(options) else None,
            "options": options,
            "layout": "grid2x2",
        }

    return None


def _format_battle_ui_lines(ui_state: Dict[str, Any]) -> List[str]:
    options = ui_state.get("options") if isinstance(ui_state.get("options"), list) else []
    cursor = int(ui_state.get("cursorPosition", 0) or 0)

    layout = str(ui_state.get("layout") or "list")
    if layout == "grid2x2" and len(options) >= 4:
        # Keep alignment for the left column (space vs arrow), but do not force a leading
        # padding character on the right column unless selected. This matches the battle UI
        # readability in plain text: "►MOVE1 MOVE2".
        top_left = ("►" if cursor == 0 else " ") + str(options[0])
        top_right = ("►" if cursor == 1 else "") + str(options[1])
        bottom_left = ("►" if cursor == 2 else " ") + str(options[2])
        bottom_right = ("►" if cursor == 3 else "") + str(options[3])
        return [f"{top_left} {top_right}".rstrip(), f"{bottom_left} {bottom_right}".rstrip()]

    lines: List[str] = []
    for i, opt in enumerate(options):
        prefix = "►" if i == cursor else " "
        lines.append(f"{prefix}{opt}")
    return lines


def _decode_battle_displayed_string(raw: Optional[bytes] = None) -> Optional[str]:
    """
    Decode the current battle message/prompt from gDisplayedStringBattle.

    Note: many battle windows print with speed=0, which bypasses TextPrinter activation.
    Reading this buffer directly is therefore more reliable than scanning sTextPrinters.
    """
    try:
        if raw is None or not raw:
            raw = mgba.mgba_read_range_bytes(GDISPLAYEDSTRINGBATTLE_ADDR, GDISPLAYEDSTRINGBATTLE_SIZE)
        if not raw:
            return None
        txt = text_encoding.decode_gba_string(raw, 200, stop_at_prompt=True)
        return txt if txt else None
    except Exception:
        return None


def _detect_battle_ui_state(
    *,
    battle_type_flags: int,
    battlers_count: int,
    absent_flags: int,
    positions: Sequence[int],
    battle_mons_raw: bytes,
    active_battler_fallback: int,
    controller_funcs_raw: bytes,
    action_selection_cursor_raw: bytes,
    move_selection_cursor_raw: bytes,
    multi_cursor: int,
    bg0_y: Optional[int] = None,
    battle_script_curr_instr_raw: Optional[bytes] = None,
    battle_communication_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    controller_funcs = [0] * BATTLE_MAX_BATTLERS
    if controller_funcs_raw and len(controller_funcs_raw) >= (BATTLE_MAX_BATTLERS * 4):
        for i in range(BATTLE_MAX_BATTLERS):
            controller_funcs[i] = int(_u32le_from(controller_funcs_raw, i * 4))

    action_cursors = [0] * BATTLE_MAX_BATTLERS
    if action_selection_cursor_raw and len(action_selection_cursor_raw) >= BATTLE_MAX_BATTLERS:
        action_cursors = [int(b) for b in action_selection_cursor_raw[:BATTLE_MAX_BATTLERS]]

    move_cursors = [0] * BATTLE_MAX_BATTLERS
    if move_selection_cursor_raw and len(move_selection_cursor_raw) >= BATTLE_MAX_BATTLERS:
        move_cursors = [int(b) for b in move_selection_cursor_raw[:BATTLE_MAX_BATTLERS]]

    priority_lists = [
        BATTLE_PLAYER_HANDLE_YES_NO_INPUT_ADDRS,
        BATTLE_HANDLE_INPUT_CHOOSE_TARGET_ADDRS,
        BATTLE_HANDLE_INPUT_CHOOSE_MOVE_ADDRS,
        BATTLE_HANDLE_INPUT_CHOOSE_ACTION_ADDRS,
    ]

    for addr_list in priority_lists:
        for battler_id, func in enumerate(controller_funcs):
            if _ptr_matches_any(func, addr_list):
                return _build_battle_ui_state(
                    battle_type_flags=battle_type_flags,
                    battlers_count=battlers_count,
                    absent_flags=absent_flags,
                    positions=positions,
                    battle_mons_raw=battle_mons_raw,
                    active_battler=battler_id,
                    controller_func=func,
                    action_cursor=action_cursors[battler_id],
                    move_cursor=move_cursors[battler_id],
                    multi_cursor=multi_cursor,
                )

    battler_id = int(active_battler_fallback) & 0xFF
    if battler_id >= BATTLE_MAX_BATTLERS:
        battler_id = 0

    # Fallback: battle script-driven Yes/No boxes (e.g. switching Pokémon).
    # These do not use PlayerHandleYesNoInput; input is handled by Cmd_yesnobox*.
    try:
        script_ptr = (
            int(_u32le_from(battle_script_curr_instr_raw, 0))
            if battle_script_curr_instr_raw and len(battle_script_curr_instr_raw) >= 4
            else int(mgba.mgba_read32(GBATTLESCRIPTCURRINSTR_ADDR))
        )
    except Exception:
        script_ptr = 0

    if script_ptr:
        try:
            cmd = int(mgba.mgba_read8(script_ptr)) & 0xFF
        except Exception:
            cmd = -1

        # pokefirered/src/battle_script_commands.c: CmdTable
        # 0x5A = Cmd_yesnoboxlearnmove, 0x5B = Cmd_yesnoboxstoplearningmove, 0x67 = Cmd_yesnobox
        if cmd in (0x5A, 0x5B, 0x67):
            options = ["YES", "NO"]
            try:
                cursor_raw = (
                    int(battle_communication_raw[1])
                    if battle_communication_raw and len(battle_communication_raw) > 1
                    else int(mgba.mgba_read8(GBATTLECOMMUNICATION_ADDR + 1))
                )
            except Exception:
                cursor_raw = 0
            cursor = 0 if int(cursor_raw) == 0 else 1
            return {
                "type": "battleYesNo",
                "activeBattlerId": battler_id,
                "cursorPosition": int(cursor),
                "selectedOption": options[cursor] if 0 <= cursor < len(options) else None,
                "options": options,
                "layout": "list",
            }

    # Fallback: infer based on BG0_Y used by the battle menu state machine.
    if bg0_y is not None:
        if bg0_y == DISPLAY_HEIGHT and BATTLE_HANDLE_INPUT_CHOOSE_ACTION_ADDRS:
            forced = int(BATTLE_HANDLE_INPUT_CHOOSE_ACTION_ADDRS[0])
            return _build_battle_ui_state(
                battle_type_flags=battle_type_flags,
                battlers_count=battlers_count,
                absent_flags=absent_flags,
                positions=positions,
                battle_mons_raw=battle_mons_raw,
                active_battler=battler_id,
                controller_func=forced,
                action_cursor=action_cursors[battler_id],
                move_cursor=move_cursors[battler_id],
                multi_cursor=multi_cursor,
            )

        if bg0_y == (DISPLAY_HEIGHT * 2) and BATTLE_HANDLE_INPUT_CHOOSE_MOVE_ADDRS:
            forced = int(BATTLE_HANDLE_INPUT_CHOOSE_MOVE_ADDRS[0])
            return _build_battle_ui_state(
                battle_type_flags=battle_type_flags,
                battlers_count=battlers_count,
                absent_flags=absent_flags,
                positions=positions,
                battle_mons_raw=battle_mons_raw,
                active_battler=battler_id,
                controller_func=forced,
                action_cursor=action_cursors[battler_id],
                move_cursor=move_cursors[battler_id],
                multi_cursor=multi_cursor,
            )

    return None
