from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .. import mgba_client as _mgba_client
from ..constants.addresses import *  # noqa: F403
from ..memory import mgba
from ..memory.reader import SnapshotMemoryReader
from ..player.save import get_save_info_window_state
from ..player.snapshot import _is_waiting_for_a_or_b_press, _read_global_script_context_native
from ..player.snapshot import are_field_controls_locked, is_in_battle
from ..text.encoding import decode_gba_string
from ..text.text_printer import find_active_textprinter_text, get_full_dialog_text, get_textprinter_text_for_window
from ..util.bytes import _u16le_from, _u32le_from, _u8_from
from . import battle
from . import fly_map
from . import menus
from . import pokedex

_DIALOG_SNAPSHOT_RANGES: List[Tuple[int, int]] = [
    (SCRIPT_LOCK_FIELD_CONTROLS, 1),
    (IN_BATTLE_BIT_ADDR, 1),
    (GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET, 4),
    (GTASKS_ADDR, NUM_TASKS * TASK_SIZE),
    (STEXTPRINTERS_ADDR, 32 * TEXTPRINTER_SIZE),
    (GSTRINGVAR4_ADDR, 500),
    # START menu state (max 9 actions)
    (START_MENU_WINDOW_ID_ADDR, 1),
    (START_MENU_NUM_ACTIONS_ADDR, 1),
    (START_MENU_CURSOR_POS_ADDR, 1),
    (START_MENU_ACTIONS_ADDR, 9),
    # Generic menu/window state for YES/NO fallback
    (SMENU_ADDR, 0x0C),
    (SYESNO_WINDOWID_ADDR, 1),
    (GWINDOWS_ADDR, 32 * WINDOW_SIZE),
    (SSAVE_INFO_WINDOWID_ADDR, 1),
    # Quest Log recap playback overlay (quest_log.c)
    (GQUEST_LOG_STATE_ADDR, 1),
    (GQUEST_LOG_PLAYBACK_STATE_ADDR, 1),
    (SQUEST_LOG_WINDOW_IDS_ADDR, QUEST_LOG_WINDOW_COUNT),
    # Player PC item storage state (player_pc.c)
    # FireRed: these are not contiguous in RAM, keep them as separate ranges.
    (GPLAYER_PC_ITEM_PAGE_INFO_ADDR, 0x0C),
    (SITEM_STORAGE_MENU_PTR_ADDR, 4),
    (SITEM_STORAGE_LIST_MENU_STATE_ADDR, 0x0C),
    # Pokémon Storage System (pokemon_storage_system.c) UI vars:
    # sChooseBoxMenu, sStorage, sInPartyMenu, sCurrentBoxOption, sDepositBoxId, sCursorArea, sCursorPosition, ...
    (SPOKE_STORAGE_CHOOSE_BOX_MENU_PTR_ADDR, 0x80),
    # Battle UI (for battle dialog/menu reconstruction)
    (GDISPLAYEDSTRINGBATTLE_ADDR, GDISPLAYEDSTRINGBATTLE_SIZE),
    (GBATTLESCRIPTCURRINSTR_ADDR, 4),
    (GBATTLECOMMUNICATION_ADDR, GBATTLECOMMUNICATION_SIZE),
    (GBATTLETYPEFLAGS_ADDR, 4),
    (GBATTLERSCOUNT_ADDR, 1),
    (GABSENTBATTLERFLAGS_ADDR, 1),
    (GBATTLERPOSITIONS_ADDR, BATTLE_MAX_BATTLERS),
    (GBATTLEMONS_ADDR, GBATTLEMONS_SIZE),
    (GACTIVEBATTLER_ADDR, 1),
    (GBATTLERCONTROLLERFUNCS_ADDR, BATTLE_MAX_BATTLERS * 4),
    (GACTIONSELECTIONCURSOR_ADDR, BATTLE_MAX_BATTLERS),
    (GMOVESELECTIONCURSOR_ADDR, BATTLE_MAX_BATTLERS),
    (GMULTIUSEPLAYERCURSOR_ADDR, 1),
    (GBATTLE_BG0_Y_ADDR, 2),
    # Party menu (party_menu.c)
    (GPARTY_MENU_ADDR, 0x14),
    (GPLAYER_PARTY_COUNT_ADDR, 1),
    (SPARTY_MENU_INTERNAL_PTR_ADDR, 4),
    (PARTY_BASE_ADDR, PARTY_SIZE * POKEMON_DATA_SIZE),
]

_DIALOG_SNAPSHOT_RANGES_EXT: List[Tuple[int, int]] = [
    *_DIALOG_SNAPSHOT_RANGES,
    # Used by get_battle_state() but not dialog detection.
    (GBATTLERPARTYINDEXES_ADDR, BATTLE_MAX_BATTLERS * 2),
]


def get_dialog_state(
    snapshot: Optional[List[bytes]] = None,
    *,
    sec_key: Optional[int] = None,
    sb1_ptr: Optional[int] = None,
    sb2_ptr: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get the current dialog/menu state.
    Returns the currently visible text and all pages for context.
    Also detects START menu, bag, trainer card, option menu and yes/no prompts.
    """
    @dataclass(frozen=True, slots=True)
    class _DialogBuffers:
        field_locked: bool
        in_battle: bool
        callback2: int
        tasks_raw: Optional[bytes] = None
        text_printers_raw: Optional[bytes] = None
        gstringvar4_raw: Optional[bytes] = None
        start_menu_window_id: Optional[int] = None
        start_menu_num_actions: Optional[int] = None
        start_menu_cursor_pos: Optional[int] = None
        start_menu_actions_raw: Optional[bytes] = None
        smenu_raw: Optional[bytes] = None
        yesno_window_id: Optional[int] = None
        windows_raw: Optional[bytes] = None
        save_info_window_id: Optional[int] = None
        quest_log_state_raw: Optional[bytes] = None
        quest_log_playback_state_raw: Optional[bytes] = None
        quest_log_window_ids_raw: Optional[bytes] = None
        player_pc_item_page_info_raw: Optional[bytes] = None
        item_storage_menu_ptr_raw: Optional[bytes] = None
        item_pc_list_menu_state_raw: Optional[bytes] = None
        poke_storage_ptr_raw: Optional[bytes] = None
        poke_choose_box_menu_ptr_raw: Optional[bytes] = None
        poke_in_party_menu_raw: Optional[bytes] = None
        poke_current_box_option_raw: Optional[bytes] = None
        poke_deposit_box_id_raw: Optional[bytes] = None
        poke_cursor_area_raw: Optional[bytes] = None
        poke_cursor_position_raw: Optional[bytes] = None
        gdisplayedstringbattle_raw: Optional[bytes] = None
        battle_script_curr_instr_raw: Optional[bytes] = None
        battle_communication_raw: Optional[bytes] = None
        battle_type_flags_raw: Optional[bytes] = None
        battlers_count_raw: Optional[bytes] = None
        absent_battlers_raw: Optional[bytes] = None
        battler_positions_raw: Optional[bytes] = None
        battle_mons_raw: Optional[bytes] = None
        active_battler_raw: Optional[bytes] = None
        battler_controller_funcs_raw: Optional[bytes] = None
        action_selection_cursor_raw: Optional[bytes] = None
        move_selection_cursor_raw: Optional[bytes] = None
        multi_use_player_cursor_raw: Optional[bytes] = None
        battle_bg0_y_raw: Optional[bytes] = None
        party_menu_raw: Optional[bytes] = None
        party_count_raw: Optional[bytes] = None
        party_internal_ptr_raw: Optional[bytes] = None
        party_raw: Optional[bytes] = None

    def _default_result(*, field_locked: bool, window0_printer_active: bool) -> Dict[str, Any]:
        return {
            "inDialog": False,
            "fieldControlsLocked": bool(field_locked),
            "textPrinterActive": bool(window0_printer_active),
            "menuType": None,
            "visibleText": None,
            "allPages": None,
            "currentPage": 0,
            "pageCount": 0,
            "startMenu": None,
            "bagMenu": None,
            "tmCase": None,
            "partyMenu": None,
            "summaryScreen": None,
            "trainerCard": None,
            "optionMenu": None,
            "titleMenu": None,
            "titleScreen": None,
            "saveInfo": None,
            "choiceMenu": None,
            "itemStorage": None,
            "pokemonStorage": None,
            "playerPcMenu": None,
            "berryCrushRankings": None,
            "battleUi": None,
            "pokedex": None,
            "flyMap": None,
            "elevatorMenu": None,
            "controlsGuide": None,
            "pikachuIntro": None,
            "questLogPlayback": None,
            "whiteOutRecovery": None,
        }

    def _read_snapshot_buffers(reader: SnapshotMemoryReader) -> Optional[_DialogBuffers]:
        def _safe_u8(addr: int) -> Optional[int]:
            try:
                return int(reader.u8(addr))
            except Exception:
                return None

        def _safe_u32(addr: int) -> Optional[int]:
            try:
                return int(reader.u32(addr))
            except Exception:
                return None

        def _safe_bytes(addr: int, size: int) -> Optional[bytes]:
            try:
                return reader.read_bytes(addr, size)
            except Exception:
                return None

        field_locked_raw = _safe_u8(SCRIPT_LOCK_FIELD_CONTROLS)
        if field_locked_raw is None:
            try:
                field_locked_raw = int(mgba.mgba_read8(SCRIPT_LOCK_FIELD_CONTROLS))
            except Exception:
                field_locked_raw = 0

        in_battle_raw = _safe_u8(IN_BATTLE_BIT_ADDR)
        if in_battle_raw is None:
            try:
                in_battle_raw = int(mgba.mgba_read8(IN_BATTLE_BIT_ADDR))
            except Exception:
                in_battle_raw = 0

        callback2_raw = _safe_u32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        if callback2_raw is None:
            try:
                callback2_raw = int(mgba.mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET))
            except Exception:
                callback2_raw = 0

        return _DialogBuffers(
            field_locked=bool(field_locked_raw != 0),
            in_battle=bool((in_battle_raw & IN_BATTLE_BITMASK) != 0),
            callback2=int(callback2_raw),
            tasks_raw=_safe_bytes(GTASKS_ADDR, NUM_TASKS * TASK_SIZE),
            text_printers_raw=_safe_bytes(STEXTPRINTERS_ADDR, 32 * TEXTPRINTER_SIZE),
            gstringvar4_raw=_safe_bytes(GSTRINGVAR4_ADDR, 500),
            start_menu_window_id=_safe_u8(START_MENU_WINDOW_ID_ADDR),
            start_menu_num_actions=_safe_u8(START_MENU_NUM_ACTIONS_ADDR),
            start_menu_cursor_pos=_safe_u8(START_MENU_CURSOR_POS_ADDR),
            start_menu_actions_raw=_safe_bytes(START_MENU_ACTIONS_ADDR, 9),
            smenu_raw=_safe_bytes(SMENU_ADDR, 0x0C),
            yesno_window_id=_safe_u8(SYESNO_WINDOWID_ADDR),
            windows_raw=_safe_bytes(GWINDOWS_ADDR, 32 * WINDOW_SIZE),
            save_info_window_id=_safe_u8(SSAVE_INFO_WINDOWID_ADDR),
            quest_log_state_raw=_safe_bytes(GQUEST_LOG_STATE_ADDR, 1),
            quest_log_playback_state_raw=_safe_bytes(GQUEST_LOG_PLAYBACK_STATE_ADDR, 1),
            quest_log_window_ids_raw=_safe_bytes(SQUEST_LOG_WINDOW_IDS_ADDR, QUEST_LOG_WINDOW_COUNT),
            player_pc_item_page_info_raw=_safe_bytes(GPLAYER_PC_ITEM_PAGE_INFO_ADDR, 0x0C),
            item_storage_menu_ptr_raw=_safe_bytes(SITEM_STORAGE_MENU_PTR_ADDR, 4),
            item_pc_list_menu_state_raw=_safe_bytes(SITEM_STORAGE_LIST_MENU_STATE_ADDR, 0x0C),
            poke_storage_ptr_raw=_safe_bytes(SPOKE_STORAGE_PTR_ADDR, 4),
            poke_choose_box_menu_ptr_raw=_safe_bytes(SPOKE_STORAGE_CHOOSE_BOX_MENU_PTR_ADDR, 4),
            poke_in_party_menu_raw=_safe_bytes(SPOKE_STORAGE_IN_PARTY_MENU_ADDR, 1),
            poke_current_box_option_raw=_safe_bytes(SPOKE_STORAGE_CURRENT_BOX_OPTION_ADDR, 1),
            poke_deposit_box_id_raw=_safe_bytes(SPOKE_STORAGE_DEPOSIT_BOX_ID_ADDR, 1),
            poke_cursor_area_raw=_safe_bytes(SPOKE_STORAGE_CURSOR_AREA_ADDR, 1),
            poke_cursor_position_raw=_safe_bytes(SPOKE_STORAGE_CURSOR_POSITION_ADDR, 1),
            gdisplayedstringbattle_raw=_safe_bytes(GDISPLAYEDSTRINGBATTLE_ADDR, GDISPLAYEDSTRINGBATTLE_SIZE),
            battle_script_curr_instr_raw=_safe_bytes(GBATTLESCRIPTCURRINSTR_ADDR, 4),
            battle_communication_raw=_safe_bytes(GBATTLECOMMUNICATION_ADDR, GBATTLECOMMUNICATION_SIZE),
            battle_type_flags_raw=_safe_bytes(GBATTLETYPEFLAGS_ADDR, 4),
            battlers_count_raw=_safe_bytes(GBATTLERSCOUNT_ADDR, 1),
            absent_battlers_raw=_safe_bytes(GABSENTBATTLERFLAGS_ADDR, 1),
            battler_positions_raw=_safe_bytes(GBATTLERPOSITIONS_ADDR, BATTLE_MAX_BATTLERS),
            battle_mons_raw=_safe_bytes(GBATTLEMONS_ADDR, GBATTLEMONS_SIZE),
            active_battler_raw=_safe_bytes(GACTIVEBATTLER_ADDR, 1),
            battler_controller_funcs_raw=_safe_bytes(GBATTLERCONTROLLERFUNCS_ADDR, BATTLE_MAX_BATTLERS * 4),
            action_selection_cursor_raw=_safe_bytes(GACTIONSELECTIONCURSOR_ADDR, BATTLE_MAX_BATTLERS),
            move_selection_cursor_raw=_safe_bytes(GMOVESELECTIONCURSOR_ADDR, BATTLE_MAX_BATTLERS),
            multi_use_player_cursor_raw=_safe_bytes(GMULTIUSEPLAYERCURSOR_ADDR, 1),
            battle_bg0_y_raw=_safe_bytes(GBATTLE_BG0_Y_ADDR, 2),
            party_menu_raw=_safe_bytes(GPARTY_MENU_ADDR, 0x14),
            party_count_raw=_safe_bytes(GPLAYER_PARTY_COUNT_ADDR, 1),
            party_internal_ptr_raw=_safe_bytes(SPARTY_MENU_INTERNAL_PTR_ADDR, 4),
            party_raw=_safe_bytes(PARTY_BASE_ADDR, PARTY_SIZE * POKEMON_DATA_SIZE),
        )

    def _compute(buffers: _DialogBuffers, *, mode: str) -> Dict[str, Any]:
        callback2 = int(buffers.callback2) & 0xFFFFFFFF

        # Only count the window0 TextPrinter as dialog evidence (other windows can be used for UI).
        window0_printer_active = False
        try:
            if buffers.text_printers_raw is not None:
                window0_printer_active = _u8_from(buffers.text_printers_raw, TEXTPRINTER_ACTIVE_OFFSET) != 0
            else:
                window0_printer_active = mgba.mgba_read8(STEXTPRINTERS_ADDR + TEXTPRINTER_ACTIVE_OFFSET) != 0
        except Exception:
            window0_printer_active = False

        result = _default_result(field_locked=buffers.field_locked, window0_printer_active=window0_printer_active)

        def _norm_text(s: Optional[str]) -> str:
            if not isinstance(s, str):
                return ""
            return " ".join(s.split()).strip().lower()

        def _append_section_once(base: Optional[str], section: Optional[str]) -> Optional[str]:
            sec = str(section or "").strip()
            if not sec:
                return base
            base_txt = str(base or "").strip()
            if not base_txt:
                return sec
            if _norm_text(sec) in _norm_text(base_txt):
                return base_txt
            return f"{base_txt}\n\n{sec}"

        def _read_save_prompt_fallback() -> Optional[str]:
            """
            Resolve the save dialog prompt when YES/NO is visible but TextPrinter has already finished.
            """
            # 1) Try window0 text printer, including inactive printer.
            try:
                txt = get_textprinter_text_for_window(
                    0,
                    text_printers_raw=buffers.text_printers_raw,
                    gstringvar4_raw=buffers.gstringvar4_raw,
                    gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
                    include_inactive=True,
                )
            except Exception:
                txt = None
            if isinstance(txt, str) and txt.strip():
                return txt.strip()

            # 2) Try gStringVar4 current page.
            try:
                guess = (
                    decode_gba_string(buffers.gstringvar4_raw, 200, stop_at_prompt=True)
                    if buffers.gstringvar4_raw is not None
                    else decode_gba_string(mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500), 200, stop_at_prompt=True)
                )
            except Exception:
                guess = ""
            if isinstance(guess, str) and guess.strip():
                return guess.strip()

            # 3) Static FireRed save prompt strings from ROM.
            for addr in (
                GTEXT_WOULD_YOU_LIKE_TO_SAVE_THE_GAME_ADDR,
                GTEXT_ALREADY_SAVE_FILE_WOULD_LIKE_TO_OVERWRITE_ADDR,
                GTEXT_DIFFERENT_GAME_FILE_ADDR,
            ):
                try:
                    ai = int(addr or 0)
                except Exception:
                    ai = 0
                if ai == 0:
                    continue
                try:
                    raw = mgba.mgba_read_range_bytes(ai, 160)
                    txt = decode_gba_string(raw, 160, stop_at_prompt=True)
                except Exception:
                    txt = ""
                if isinstance(txt, str) and txt.strip():
                    return txt.strip()
            return None

        def _save_info_window_visible() -> bool:
            wid_raw = buffers.save_info_window_id
            if wid_raw is None:
                try:
                    wid_raw = int(mgba.mgba_read8(SSAVE_INFO_WINDOWID_ADDR))
                except Exception:
                    return False
            wid = int(wid_raw)
            return wid != WINDOW_NONE and 0 <= wid < 32

        def _any_text_printer_active() -> bool:
            try:
                if buffers.text_printers_raw is not None and len(buffers.text_printers_raw) >= (32 * TEXTPRINTER_SIZE):
                    for i in range(32):
                        off = (i * TEXTPRINTER_SIZE) + TEXTPRINTER_ACTIVE_OFFSET
                        if _u8_from(buffers.text_printers_raw, off) != 0:
                            return True
                    return False
                for i in range(32):
                    printer_addr = STEXTPRINTERS_ADDR + (i * TEXTPRINTER_SIZE)
                    if mgba.mgba_read8(printer_addr + TEXTPRINTER_ACTIVE_OFFSET) != 0:
                        return True
            except Exception:
                return False
            return False

        def _read_whiteout_recovery_state() -> Optional[Dict[str, Any]]:
            """
            Detect the whiteout recovery overlay text:
            "{PLAYER} scurried to a POKéMON CENTER..."

            The text is rendered by Task_RushInjuredPokemonToCenter in a dedicated
            window and can be visible even when its TextPrinter is already inactive.
            """
            try:
                task_addr = int(TASK_RUSH_INJURED_POKEMON_TO_CENTER_ADDR or 0)
            except Exception:
                task_addr = 0
            if task_addr == 0:
                return None

            task_id = menus._find_active_task_by_func(task_addr, buffers.tasks_raw)
            if task_id is None:
                return None

            try:
                state = int(menus._read_task_data_u16(int(task_id), 0, buffers.tasks_raw))
            except Exception:
                state = -1

            # field_screen_effect.c:
            # 1/4 = printing whiteout message, 2/5+ = fade/cleanup (no text expected).
            if state not in {1, 4}:
                return None

            window_id: Optional[int]
            try:
                window_id = int(menus._read_task_data_u16(int(task_id), 1, buffers.tasks_raw))
            except Exception:
                window_id = None

            visible_text: Optional[str] = None
            if isinstance(window_id, int) and 0 <= window_id < 32 and window_id != WINDOW_NONE:
                visible_text = get_textprinter_text_for_window(
                    window_id,
                    text_printers_raw=buffers.text_printers_raw,
                    gstringvar4_raw=buffers.gstringvar4_raw,
                    gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
                    include_inactive=True,
                )

            if not visible_text:
                try:
                    gsv4 = (
                        buffers.gstringvar4_raw
                        if buffers.gstringvar4_raw is not None
                        else mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
                    )
                    guess = decode_gba_string(gsv4, 220, stop_at_prompt=True)
                except Exception:
                    guess = ""
                visible_text = guess.strip() if isinstance(guess, str) and guess.strip() else None

            if not visible_text:
                for addr in (GTEXT_PLAYER_SCURRIED_TO_CENTER_ADDR, GTEXT_PLAYER_SCURRIED_BACK_HOME_ADDR):
                    try:
                        ai = int(addr or 0)
                    except Exception:
                        ai = 0
                    if ai == 0:
                        continue
                    try:
                        raw = mgba.mgba_read_range_bytes(ai, 180)
                        txt = decode_gba_string(raw, 180, stop_at_prompt=True)
                    except Exception:
                        txt = ""
                    if isinstance(txt, str) and txt.strip():
                        visible_text = txt.strip()
                        break

            return {
                "taskId": int(task_id),
                "state": int(state),
                "windowId": int(window_id) if isinstance(window_id, int) else None,
                "visibleText": visible_text,
            }

        # Compute "in dialog" more strictly: field lock alone is not enough (warp/transitions).
        in_dialog = False
        if buffers.in_battle:
            in_dialog = True
        elif buffers.field_locked:
            if window0_printer_active:
                in_dialog = True
            else:
                script_mode, native_ptr = _read_global_script_context_native()
                if _is_waiting_for_a_or_b_press(script_mode, native_ptr):
                    in_dialog = True
        result["inDialog"] = bool(in_dialog)

        # Fast-path: idle overworld with no text printer and no visible menu windows.
        # This avoids running all menu detectors on every frame when nothing is open.
        try:
            cb2_masked = int(callback2) & 0xFFFFFFFE
            overworld_cb2 = (int(CB2_OVERWORLD_ADDR) & 0xFFFFFFFE) if int(CB2_OVERWORLD_ADDR) != 0 else 0
            start_menu_open = (
                buffers.start_menu_window_id is not None
                and int(buffers.start_menu_window_id) != WINDOW_NONE
            )
            yesno_open = (
                buffers.yesno_window_id is not None
                and int(buffers.yesno_window_id) != WINDOW_NONE
            )
            if (
                not bool(buffers.in_battle)
                and not bool(buffers.field_locked)
                and overworld_cb2 != 0
                and cb2_masked == overworld_cb2
                and not start_menu_open
                and not yesno_open
                and not _save_info_window_visible()
                and not _any_text_printer_active()
            ):
                return result
        except Exception:
            pass

        birch_speech_active = (
            menus._is_new_game_birch_speech_active(buffers.tasks_raw)
            if buffers.tasks_raw is not None
            else menus._is_new_game_birch_speech_active()
        )
        dialog_read_safe = bool(in_dialog) or bool(birch_speech_active)

        title_screen = menus.get_title_screen_press_start_state(callback2=callback2, tasks_raw=buffers.tasks_raw)
        if title_screen:
            result["inDialog"] = True
            result["menuType"] = "titleScreen"
            result["titleScreen"] = title_screen
            result["visibleText"] = menus.TITLE_SCREEN_PRESS_START_VISIBLE_TEXT
            return result

        naming = menus.get_naming_screen_state(callback2=callback2)
        if naming:
            result["inDialog"] = True
            result["menuType"] = "namingScreen"
            result["choiceMenu"] = naming
            result["visibleText"] = naming.get("visibleText")
            return result

        controls_guide = menus.get_controls_guide_state(buffers.tasks_raw)
        if controls_guide:
            result["inDialog"] = True
            result["menuType"] = "controlsGuide"
            result["controlsGuide"] = controls_guide
            result["visibleText"] = controls_guide.get("visibleText")
            result["allPages"] = controls_guide.get("allPages")
            result["pageCount"] = int(controls_guide.get("pageCount") or 0)
            result["currentPage"] = int((controls_guide.get("page") or {}).get("number") or 0)
            return result

        pikachu_intro = menus.get_pikachu_intro_state(
            buffers.tasks_raw,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
        )
        if pikachu_intro:
            result["inDialog"] = True
            result["menuType"] = "pikachuIntro"
            result["pikachuIntro"] = pikachu_intro
            result["visibleText"] = pikachu_intro.get("visibleText")
            result["allPages"] = pikachu_intro.get("allPages")
            result["pageCount"] = int(pikachu_intro.get("pageCount") or 0)
            result["currentPage"] = int((pikachu_intro.get("page") or {}).get("number") or 0)
            return result

        quest_log_playback = menus.get_quest_log_playback_state(
            quest_log_state_raw=buffers.quest_log_state_raw,
            quest_log_playback_state_raw=buffers.quest_log_playback_state_raw,
            quest_log_window_ids_raw=buffers.quest_log_window_ids_raw,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
        )
        if quest_log_playback:
            result["inDialog"] = True
            result["menuType"] = "questLogPlayback"
            result["questLogPlayback"] = quest_log_playback
            result["visibleText"] = quest_log_playback.get("visibleText")
            return result

        fly_state = fly_map.get_fly_map_state(
            callback2=callback2,
            sb1_ptr=sb1_ptr,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
        )
        if fly_state:
            result["inDialog"] = True
            result["menuType"] = "flyMap"
            result["flyMap"] = fly_state
            result["visibleText"] = fly_state.get("visibleText")
            return result

        pokedex_state = pokedex.get_pokedex_state(
            callback2=callback2,
            tasks_raw=buffers.tasks_raw,
            sb1_ptr=sb1_ptr,
            sb2_ptr=sb2_ptr,
        )
        if pokedex_state:
            result["inDialog"] = True
            result["menuType"] = "pokedex"
            result["pokedex"] = pokedex_state
            result["choiceMenu"] = pokedex_state.get("choiceMenu")
            result["visibleText"] = pokedex_state.get("visibleText")
            return result

        poke_storage_ui = menus.get_pokemon_storage_system_state(
            callback2=callback2,
            windows_raw=buffers.windows_raw,
            smenu_raw=buffers.smenu_raw,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            storage_ptr_raw=buffers.poke_storage_ptr_raw,
            choose_box_menu_ptr_raw=buffers.poke_choose_box_menu_ptr_raw,
            in_party_menu_raw=buffers.poke_in_party_menu_raw,
            current_box_option_raw=buffers.poke_current_box_option_raw,
            deposit_box_id_raw=buffers.poke_deposit_box_id_raw,
            cursor_area_raw=buffers.poke_cursor_area_raw,
            cursor_position_raw=buffers.poke_cursor_position_raw,
        )
        if poke_storage_ui:
            result["inDialog"] = True
            result["menuType"] = "pokemonStorage"
            result["pokemonStorage"] = poke_storage_ui
            result["visibleText"] = poke_storage_ui.get("visibleText")
            if poke_storage_ui.get("actionMenu") is not None:
                result["choiceMenu"] = poke_storage_ui.get("actionMenu")

            yesno_menu = menus.get_yes_no_menu_state(
                buffers.tasks_raw,
                yesno_window_id=buffers.yesno_window_id,
                smenu_raw=buffers.smenu_raw,
                windows_raw=buffers.windows_raw,
            )
            if yesno_menu:
                result["choiceMenu"] = yesno_menu
                cursor = int(yesno_menu.get("cursorPosition", 0) or 0)
                options = yesno_menu.get("options") if isinstance(yesno_menu.get("options"), list) else []
                choice_lines = []
                for i, opt in enumerate(options):
                    prefix = "►" if i == cursor else " "
                    choice_lines.append(f"{prefix}{opt}")
                if choice_lines:
                    if result.get("visibleText"):
                        result["visibleText"] += "\n\n" + "\n".join(choice_lines)
                    else:
                        result["visibleText"] = "\n".join(choice_lines)
            return result

        berry_crush = menus.get_berry_crush_rankings_state(buffers.tasks_raw)
        if berry_crush:
            result["inDialog"] = True
            result["menuType"] = "berryCrushRankings"
            result["berryCrushRankings"] = berry_crush
            result["visibleText"] = berry_crush.get("visibleText")
            return result

        poke_storage_pc_menu = menus.get_pokemon_storage_pc_menu_state(buffers.tasks_raw, buffers.smenu_raw)
        if poke_storage_pc_menu:
            result["inDialog"] = True
            result["menuType"] = "pokemonStoragePcMenu"
            result["choiceMenu"] = poke_storage_pc_menu
            result["visibleText"] = poke_storage_pc_menu.get("visibleText")
            return result

        player_pc_menu = menus.get_player_pc_menu_state(buffers.tasks_raw, buffers.smenu_raw)
        if player_pc_menu:
            result["inDialog"] = True
            result["menuType"] = "playerPcMenu"
            result["choiceMenu"] = player_pc_menu
            result["playerPcMenu"] = player_pc_menu
            result["visibleText"] = player_pc_menu.get("visibleText")
            return result

        item_storage_list = menus.get_item_storage_list_state(
            tasks_raw=buffers.tasks_raw,
            smenu_raw=buffers.smenu_raw,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            item_storage_menu_ptr_raw=buffers.item_storage_menu_ptr_raw,
            player_pc_item_page_info_raw=buffers.player_pc_item_page_info_raw,
            item_pc_list_state_raw=buffers.item_pc_list_menu_state_raw,
            sb1_ptr=sb1_ptr,
        )
        if item_storage_list:
            result["inDialog"] = True
            result["menuType"] = "itemStorageList"
            result["itemStorage"] = item_storage_list
            result["visibleText"] = item_storage_list.get("visibleText")
            context_menu = item_storage_list.get("contextMenu") if isinstance(item_storage_list, dict) else None
            if isinstance(context_menu, dict):
                result["choiceMenu"] = context_menu

            # Toss confirmations use the YES/NO menu system.
            yesno_menu = menus.get_yes_no_menu_state(
                buffers.tasks_raw,
                yesno_window_id=buffers.yesno_window_id,
                smenu_raw=buffers.smenu_raw,
                windows_raw=buffers.windows_raw,
            )
            if yesno_menu:
                result["choiceMenu"] = yesno_menu
                cursor = int(yesno_menu.get("cursorPosition", 0) or 0)
                options = yesno_menu.get("options") if isinstance(yesno_menu.get("options"), list) else []
                choice_lines = []
                for i, opt in enumerate(options):
                    prefix = "►" if i == cursor else " "
                    choice_lines.append(f"{prefix}{opt}")
                if choice_lines:
                    if result.get("visibleText"):
                        result["visibleText"] += "\n\n" + "\n".join(choice_lines)
                    else:
                        result["visibleText"] = "\n".join(choice_lines)

            return result

        item_storage_menu = menus.get_item_storage_menu_state(buffers.tasks_raw, buffers.smenu_raw)
        if item_storage_menu:
            result["inDialog"] = True
            result["menuType"] = "itemStorageMenu"
            result["itemStorage"] = item_storage_menu
            result["choiceMenu"] = item_storage_menu
            result["visibleText"] = item_storage_menu.get("visibleText")
            return result

        start_menu = menus.get_start_menu_state(
            buffers.tasks_raw,
            start_menu_window_id=buffers.start_menu_window_id,
            start_menu_num_actions=buffers.start_menu_num_actions,
            start_menu_cursor_pos=buffers.start_menu_cursor_pos,
            start_menu_actions_raw=buffers.start_menu_actions_raw,
        )
        if start_menu:
            result["menuType"] = "startMenu"
            result["inDialog"] = True
            result["startMenu"] = start_menu
            options_text = []
            for opt in start_menu.get("options", []):
                prefix = "►" if opt.get("selected") else ""
                options_text.append(f"{prefix}{opt.get('name', '')}")
            result["visibleText"] = "\n".join(options_text)
            return result

        tm_case = menus.get_tm_case_state(
            callback2=callback2,
            tasks_raw=buffers.tasks_raw,
            smenu_raw=buffers.smenu_raw,
            sec_key=sec_key,
        )
        if tm_case:
            result["menuType"] = "tmCase"
            result["inDialog"] = True
            result["tmCase"] = tm_case
            result["choiceMenu"] = tm_case.get("contextMenu")
            result["visibleText"] = tm_case.get("visibleText")
            return result

        bag_menu = menus.get_bag_menu_state(
            callback2=callback2,
            tasks_raw=buffers.tasks_raw,
            smenu_raw=buffers.smenu_raw,
            sec_key=sec_key,
        )
        if bag_menu:
            result["menuType"] = "bagMenu"
            result["inDialog"] = True
            result["bagMenu"] = bag_menu
            result["choiceMenu"] = bag_menu.get("contextMenu")
            result["visibleText"] = bag_menu.get("visibleText")

            # Bag "item message" overlays (TM/HM boot text, toss confirmations, etc.) are rendered in a
            # separate window (ITEMWIN_MESSAGE) that is not window0. When printed instantly, the
            # TextPrinter can be inactive even though the message is still visible.
            message_window_id: Optional[int] = None
            message_text: Optional[str] = None
            dialog_data: Optional[Dict[str, Any]] = None
            try:
                wid = bag_menu.get("messageWindowId")
                if isinstance(wid, int) and wid != WINDOW_NONE and 0 <= wid < 32:
                    message_window_id = int(wid)
            except Exception:
                message_window_id = None

            if message_window_id is not None:
                message_text = get_textprinter_text_for_window(
                    message_window_id,
                    text_printers_raw=buffers.text_printers_raw,
                    gstringvar4_raw=buffers.gstringvar4_raw,
                    gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
                    include_inactive=True,
                )

                # Provide multi-page context when the bag message window is visible.
                dialog_data = get_full_dialog_text(buffers.gstringvar4_raw)
                if dialog_data:
                    result["allPages"] = dialog_data["pages"]
                    result["pageCount"] = dialog_data["pageCount"]

            # YES/NO prompts inside the bag (e.g. "Teach FLASH to a POKéMON?") reuse the global menu system.
            yesno_menu = menus.get_yes_no_menu_state(
                buffers.tasks_raw,
                yesno_window_id=buffers.yesno_window_id,
                smenu_raw=buffers.smenu_raw,
                windows_raw=buffers.windows_raw,
            )
            if yesno_menu:
                result["choiceMenu"] = yesno_menu

            if message_window_id is not None:
                if not message_text:
                    # Fallback: if the TextPrinter state is unavailable, choose a sensible page.
                    pages = dialog_data.get("pages") if isinstance(dialog_data, dict) else None
                    if isinstance(pages, list) and pages:
                        if yesno_menu:
                            message_text = str(pages[-1])
                            result["currentPage"] = int(len(pages))
                        else:
                            message_text = str(pages[0])
                            result["currentPage"] = 1
                    else:
                        guess = decode_gba_string(
                            buffers.gstringvar4_raw or mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500),
                            200,
                            stop_at_prompt=True,
                        )
                        message_text = guess or None
                        if message_text and int(result.get("pageCount") or 0) == 1:
                            result["currentPage"] = 1

                if message_text:
                    result["visibleText"] = message_text

                if message_text and int(result.get("currentPage") or 0) == 0:
                    pages = dialog_data.get("pages") if isinstance(dialog_data, dict) else None
                    if isinstance(pages, list) and pages:
                        for i, page in enumerate(pages):
                            if message_text.strip() == str(page).strip():
                                result["currentPage"] = i + 1
                                break

                if int(result.get("pageCount") or 0) == 1 and int(result.get("currentPage") or 0) == 0:
                    result["currentPage"] = 1

            if yesno_menu:
                cursor = int(yesno_menu.get("cursorPosition", 0) or 0)
                options = yesno_menu.get("options") if isinstance(yesno_menu.get("options"), list) else []
                choice_lines = []
                for i, opt in enumerate(options):
                    prefix = "►" if i == cursor else " "
                    choice_lines.append(f"{prefix}{opt}")
                if choice_lines:
                    if result.get("visibleText"):
                        result["visibleText"] += "\n\n" + "\n".join(choice_lines)
                    else:
                        result["visibleText"] = "\n".join(choice_lines)

            return result

        trainer_card = menus.get_trainer_card_state(callback2=callback2)
        if trainer_card:
            result["menuType"] = "trainerCard"
            result["inDialog"] = True
            result["trainerCard"] = trainer_card
            badge_str = f"{trainer_card['badgeCount']}/8 badges"
            result["visibleText"] = (
                "TRAINER CARD\n"
                f"IDNo.{trainer_card['trainerIdFormatted']}\n"
                f"NAME: {trainer_card['playerName']}\n"
                f"MONEY: {trainer_card['moneyFormatted']}\n"
                f"TIME: {trainer_card['playTime']}\n"
                f"BADGES: {badge_str}"
            )
            return result

        option_menu = menus.get_option_menu_state(callback2=callback2, tasks_raw=buffers.tasks_raw)
        if option_menu:
            result["menuType"] = "optionMenu"
            result["inDialog"] = True
            result["optionMenu"] = option_menu
            cursor = option_menu.get("cursorPosition", 0)
            lines = [
                f"{'►' if cursor == 0 else ' '}TEXT SPEED: {option_menu['textSpeed']}",
                f"{'►' if cursor == 1 else ' '}BATTLE SCENE: {option_menu['battleScene']}",
                f"{'►' if cursor == 2 else ' '}BATTLE STYLE: {option_menu['battleStyle']}",
                f"{'►' if cursor == 3 else ' '}SOUND: {option_menu['sound']}",
                f"{'►' if cursor == 4 else ' '}BUTTON MODE: {option_menu['buttonMode']}",
                f"{'►' if cursor == 5 else ' '}FRAME: TYPE{option_menu['frameType']}",
                f"{'►' if cursor == 6 else ' '}CANCEL",
            ]
            result["visibleText"] = "OPTION\n" + "\n".join(lines)
            return result

        title_menu = menus.get_title_menu_state(callback2=callback2, tasks_raw=buffers.tasks_raw)
        if title_menu:
            result["menuType"] = "titleMenu"
            result["inDialog"] = True
            result["titleMenu"] = title_menu
            options_text = []
            for opt in title_menu.get("options", []):
                prefix = "►" if opt.get("selected") else ""
                options_text.append(f"{prefix}{opt.get('name', '')}".rstrip())
            result["visibleText"] = "\n".join([line for line in options_text if line])
            return result

        party_menu = menus.get_party_menu_state(
            callback2=callback2,
            party_menu_raw=buffers.party_menu_raw,
            party_count_raw=buffers.party_count_raw,
            party_internal_ptr_raw=buffers.party_internal_ptr_raw,
            party_raw=buffers.party_raw,
            smenu_raw=buffers.smenu_raw,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
        )
        if party_menu:
            result["menuType"] = "partyMenu"
            result["inDialog"] = True
            result["partyMenu"] = party_menu

            # The party menu can show an overlay YES/NO prompt (e.g. when learning a new move).
            # Detect it here because the global dialog path returns early for partyMenu.
            yesno_menu = menus.get_yes_no_menu_state(
                buffers.tasks_raw,
                yesno_window_id=buffers.yesno_window_id,
                smenu_raw=buffers.smenu_raw,
                windows_raw=buffers.windows_raw,
            )
            if yesno_menu:
                result["choiceMenu"] = yesno_menu
            else:
                result["choiceMenu"] = party_menu.get("actionMenu")

            result["visibleText"] = party_menu.get("visibleText")

            dialog_data = get_full_dialog_text(buffers.gstringvar4_raw)
            if dialog_data:
                result["allPages"] = dialog_data["pages"]
                result["pageCount"] = dialog_data["pageCount"]

                # When possible, infer the current page by matching the party menu's bottom text.
                bottom_text = party_menu.get("bottomText")
                if isinstance(bottom_text, str) and bottom_text and isinstance(dialog_data.get("pages"), list):
                    for i, page in enumerate(dialog_data["pages"]):
                        if bottom_text.strip() == str(page).strip():
                            result["currentPage"] = i + 1
                            break

                if int(result.get("pageCount") or 0) == 1 and int(result.get("currentPage") or 0) == 0:
                    result["currentPage"] = 1

            if yesno_menu:
                cursor = int(yesno_menu.get("cursorPosition", 0) or 0)
                options = yesno_menu.get("options") if isinstance(yesno_menu.get("options"), list) else []
                choice_lines = []
                for i, opt in enumerate(options):
                    prefix = "►" if i == cursor else " "
                    choice_lines.append(f"{prefix}{opt}")
                if choice_lines:
                    if result.get("visibleText"):
                        result["visibleText"] += "\n\n" + "\n".join(choice_lines)
                    else:
                        result["visibleText"] = "\n".join(choice_lines)

            return result

        shop_buy_menu = menus.get_shop_buy_menu_state(callback2=callback2, tasks_raw=buffers.tasks_raw)
        if shop_buy_menu:
            result["menuType"] = "shopBuyMenu"
            result["inDialog"] = True
            result["choiceMenu"] = shop_buy_menu
            result["visibleText"] = shop_buy_menu.get("visibleText")
            return result

        summary_screen = menus.get_pokemon_summary_state(
            callback2=callback2,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
        )
        if summary_screen:
            result["menuType"] = "summaryScreen"
            result["inDialog"] = True
            result["summaryScreen"] = summary_screen
            result["choiceMenu"] = summary_screen.get("choiceMenu")
            result["visibleText"] = summary_screen.get("visibleText")
            return result

        summary_screen = menus.get_pokemon_summary_select_move_state(callback2=callback2, tasks_raw=buffers.tasks_raw)
        if summary_screen:
            result["menuType"] = "summaryMoveReplace"
            result["inDialog"] = True
            result["summaryScreen"] = summary_screen
            result["choiceMenu"] = summary_screen.get("choiceMenu")
            result["visibleText"] = summary_screen.get("visibleText")
            return result

        elevator_menu = menus.get_elevator_menu_state(
            buffers.tasks_raw,
            buffers.smenu_raw,
            text_printers_raw=buffers.text_printers_raw,
            gstringvar4_raw=buffers.gstringvar4_raw,
            gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
        )
        if elevator_menu:
            result["menuType"] = "elevatorMenu"
            result["inDialog"] = True
            result["choiceMenu"] = elevator_menu
            result["elevatorMenu"] = elevator_menu
            result["visibleText"] = elevator_menu.get("visibleText")
            return result

        whiteout_recovery = _read_whiteout_recovery_state()
        if whiteout_recovery:
            result["inDialog"] = True
            result["menuType"] = "dialog"
            result["whiteOutRecovery"] = whiteout_recovery
            visible = whiteout_recovery.get("visibleText")
            if isinstance(visible, str) and visible.strip():
                result["visibleText"] = visible.strip()

            dialog_data = get_full_dialog_text(buffers.gstringvar4_raw)
            if dialog_data:
                result["allPages"] = dialog_data["pages"]
                result["pageCount"] = dialog_data["pageCount"]
                if int(result.get("currentPage") or 0) == 0 and int(result.get("pageCount") or 0) > 0:
                    result["currentPage"] = 1
            return result

        if mode == "slow" and not in_dialog:
            choice_menu = (
                menus.get_shop_choice_menu_state(buffers.tasks_raw, buffers.smenu_raw)
                or menus.get_multichoice_menu_state(
                    buffers.tasks_raw, buffers.smenu_raw, gstringvar4_raw=buffers.gstringvar4_raw
                )
                or menus.get_yes_no_menu_state(
                    buffers.tasks_raw,
                    yesno_window_id=buffers.yesno_window_id,
                    smenu_raw=buffers.smenu_raw,
                    windows_raw=buffers.windows_raw,
                )
                or menus.get_player_pc_menu_state(buffers.tasks_raw, buffers.smenu_raw)
            )
            if choice_menu:
                result["inDialog"] = True
                result["menuType"] = "dialog"
                result["choiceMenu"] = choice_menu

                try:
                    visible = find_active_textprinter_text(include_inactive_window0=True)
                except TypeError:
                    visible = find_active_textprinter_text()
                if visible:
                    result["visibleText"] = visible
                else:
                    try:
                        if buffers.gstringvar4_raw is not None:
                            guess = decode_gba_string(buffers.gstringvar4_raw, 200, stop_at_prompt=True)
                        else:
                            gsv4 = mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
                            guess = decode_gba_string(gsv4, 200, stop_at_prompt=True)
                    except Exception:
                        guess = ""
                    if guess:
                        result["visibleText"] = guess

                prompt_text = choice_menu.get("promptText") if isinstance(choice_menu, dict) else None
                if isinstance(prompt_text, str) and prompt_text:
                    if result.get("visibleText"):
                        result["visibleText"] = f"{result['visibleText']}\n\n{prompt_text}"
                    else:
                        result["visibleText"] = prompt_text
                elif (
                    isinstance(choice_menu, dict)
                    and str(choice_menu.get("type") or "") == "yesNo"
                    and _save_info_window_visible()
                ):
                    save_prompt = _read_save_prompt_fallback()
                    if save_prompt:
                        result["visibleText"] = _append_section_once(result.get("visibleText"), save_prompt)

                choice_lines = []
                cursor = int(choice_menu.get("cursorPosition", 0) or 0)
                options = choice_menu.get("options") if isinstance(choice_menu.get("options"), list) else []
                for i, opt in enumerate(options):
                    prefix = "►" if i == cursor else " "
                    choice_lines.append(f"{prefix}{opt}")
                choice_text = "\n".join(choice_lines)
                if choice_text:
                    if result["visibleText"]:
                        result["visibleText"] += f"\n\n{choice_text}"
                    else:
                        result["visibleText"] = choice_text

                if _save_info_window_visible():
                    save_info = get_save_info_window_state()
                    if save_info:
                        result["saveInfo"] = save_info
                        save_text = save_info.get("visibleText")
                        if isinstance(save_text, str) and save_text:
                            if result["visibleText"]:
                                result["visibleText"] = f"{save_text}\n\n{result['visibleText']}"
                            else:
                                result["visibleText"] = save_text

            return result

        if buffers.in_battle:
            battle_text: Optional[str] = None
            if mode == "snapshot":
                try:
                    battle_text = find_active_textprinter_text(
                        text_printers_raw=buffers.text_printers_raw,
                        gstringvar4_raw=buffers.gstringvar4_raw,
                        gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
                        include_inactive_window0=True,
                    )
                except TypeError:
                    battle_text = find_active_textprinter_text(include_inactive_window0=True)
            else:
                try:
                    battle_text = find_active_textprinter_text(include_inactive_window0=True)
                except TypeError:
                    battle_text = find_active_textprinter_text()

            if not battle_text:
                battle_text = battle._decode_battle_displayed_string(buffers.gdisplayedstringbattle_raw)

            battle_type_flags = (
                _u32le_from(buffers.battle_type_flags_raw, 0)
                if buffers.battle_type_flags_raw and len(buffers.battle_type_flags_raw) >= 4
                else int(mgba.mgba_read32(GBATTLETYPEFLAGS_ADDR))
            )
            battlers_count = (
                int(buffers.battlers_count_raw[0])
                if buffers.battlers_count_raw and len(buffers.battlers_count_raw) >= 1
                else int(mgba.mgba_read8(GBATTLERSCOUNT_ADDR))
            )
            absent_flags = (
                int(buffers.absent_battlers_raw[0])
                if buffers.absent_battlers_raw and len(buffers.absent_battlers_raw) >= 1
                else int(mgba.mgba_read8(GABSENTBATTLERFLAGS_ADDR))
            )
            positions = (
                list(buffers.battler_positions_raw[:BATTLE_MAX_BATTLERS])
                if buffers.battler_positions_raw and len(buffers.battler_positions_raw) >= BATTLE_MAX_BATTLERS
                else list(mgba.mgba_read_range_bytes(GBATTLERPOSITIONS_ADDR, BATTLE_MAX_BATTLERS))
            )
            battle_mons_raw = (
                buffers.battle_mons_raw
                if buffers.battle_mons_raw and len(buffers.battle_mons_raw) >= GBATTLEMONS_SIZE
                else mgba.mgba_read_range_bytes(GBATTLEMONS_ADDR, GBATTLEMONS_SIZE)
            )
            active_battler = (
                int(buffers.active_battler_raw[0])
                if buffers.active_battler_raw and len(buffers.active_battler_raw) >= 1
                else int(mgba.mgba_read8(GACTIVEBATTLER_ADDR))
            )
            controller_funcs_raw = (
                buffers.battler_controller_funcs_raw
                if buffers.battler_controller_funcs_raw and len(buffers.battler_controller_funcs_raw) >= (BATTLE_MAX_BATTLERS * 4)
                else mgba.mgba_read_range_bytes(GBATTLERCONTROLLERFUNCS_ADDR, BATTLE_MAX_BATTLERS * 4)
            )
            action_cursors = (
                buffers.action_selection_cursor_raw
                if buffers.action_selection_cursor_raw and len(buffers.action_selection_cursor_raw) >= BATTLE_MAX_BATTLERS
                else mgba.mgba_read_range_bytes(GACTIONSELECTIONCURSOR_ADDR, BATTLE_MAX_BATTLERS)
            )
            move_cursors = (
                buffers.move_selection_cursor_raw
                if buffers.move_selection_cursor_raw and len(buffers.move_selection_cursor_raw) >= BATTLE_MAX_BATTLERS
                else mgba.mgba_read_range_bytes(GMOVESELECTIONCURSOR_ADDR, BATTLE_MAX_BATTLERS)
            )
            multi_cursor = (
                int(buffers.multi_use_player_cursor_raw[0])
                if buffers.multi_use_player_cursor_raw and len(buffers.multi_use_player_cursor_raw) >= 1
                else int(mgba.mgba_read8(GMULTIUSEPLAYERCURSOR_ADDR))
            )
            bg0_y = (
                _u16le_from(buffers.battle_bg0_y_raw, 0)
                if buffers.battle_bg0_y_raw and len(buffers.battle_bg0_y_raw) >= 2
                else int(mgba.mgba_read16(GBATTLE_BG0_Y_ADDR))
            )

            ui_state = battle._detect_battle_ui_state(
                battle_type_flags=battle_type_flags,
                battlers_count=battlers_count,
                absent_flags=absent_flags,
                positions=positions,
                battle_mons_raw=battle_mons_raw,
                active_battler_fallback=active_battler,
                controller_funcs_raw=controller_funcs_raw,
                action_selection_cursor_raw=action_cursors,
                move_selection_cursor_raw=move_cursors,
                multi_cursor=multi_cursor,
                bg0_y=bg0_y,
                battle_script_curr_instr_raw=buffers.battle_script_curr_instr_raw,
                battle_communication_raw=buffers.battle_communication_raw,
            )

            lines: List[str] = []
            if battle_text:
                lines.append(battle_text)

            if ui_state:
                result["battleUi"] = ui_state
                result["menuType"] = ui_state["type"]
                result["choiceMenu"] = {
                    "type": ui_state["type"],
                    "cursorPosition": ui_state.get("cursorPosition", 0),
                    "selectedOption": ui_state.get("selectedOption"),
                    "options": ui_state.get("options", []),
                }
                menu_lines = battle._format_battle_ui_lines(ui_state)
                if menu_lines:
                    if lines:
                        lines.append("")
                    lines.extend(menu_lines)
            else:
                result["menuType"] = "battle"

            if lines:
                result["visibleText"] = "\n".join(lines)
            return result

        # Generic dialog / menus (PC prompts, script menus, etc.) can be visible even when
        # sLockFieldControls is not set, so do not early-return based solely on `in_dialog`.
        try:
            visible = find_active_textprinter_text(
                text_printers_raw=buffers.text_printers_raw,
                gstringvar4_raw=buffers.gstringvar4_raw,
                gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
                include_inactive_window0=dialog_read_safe,
            )
        except TypeError:
            visible = find_active_textprinter_text()
        if visible:
            result["visibleText"] = visible

        save_info = get_save_info_window_state() if _save_info_window_visible() else None
        if save_info:
            result["saveInfo"] = save_info
            save_text = save_info.get("visibleText")
            if isinstance(save_text, str) and save_text:
                if result["visibleText"]:
                    result["visibleText"] = f"{save_text}\n\n{result['visibleText']}"
                else:
                    result["visibleText"] = save_text

        if dialog_read_safe:
            dialog_data = get_full_dialog_text(buffers.gstringvar4_raw)
            if dialog_data:
                result["allPages"] = dialog_data["pages"]
                result["pageCount"] = dialog_data["pageCount"]
                if visible and dialog_data["pages"]:
                    for i, page in enumerate(dialog_data["pages"]):
                        if visible.strip() == page.strip():
                            result["currentPage"] = i + 1
                            break

        choice_menu = (
            menus.get_shop_choice_menu_state(buffers.tasks_raw, buffers.smenu_raw)
            or menus.get_multichoice_menu_state(
                buffers.tasks_raw, buffers.smenu_raw, gstringvar4_raw=buffers.gstringvar4_raw
            )
            or menus.get_yes_no_menu_state(
                buffers.tasks_raw,
                yesno_window_id=buffers.yesno_window_id,
                smenu_raw=buffers.smenu_raw,
                windows_raw=buffers.windows_raw,
            )
            or menus.get_new_game_birch_gender_menu_state(
                buffers.tasks_raw, smenu_raw=buffers.smenu_raw, gstringvar4_raw=buffers.gstringvar4_raw
            )
            or menus.get_player_pc_menu_state(buffers.tasks_raw, buffers.smenu_raw)
        )
        if choice_menu:
            result["choiceMenu"] = choice_menu
            prompt_text = choice_menu.get("promptText") if isinstance(choice_menu, dict) else None
            if isinstance(prompt_text, str) and prompt_text:
                if choice_menu.get("type") == "multichoice" and int(choice_menu.get("multichoiceId") or 0) == int(MULTI_PC):
                    result["visibleText"] = prompt_text
                elif not result.get("visibleText"):
                    result["visibleText"] = prompt_text
            elif (
                isinstance(choice_menu, dict)
                and str(choice_menu.get("type") or "") == "yesNo"
                and _save_info_window_visible()
            ):
                save_prompt = _read_save_prompt_fallback()
                if save_prompt:
                    result["visibleText"] = _append_section_once(result.get("visibleText"), save_prompt)

            if mode == "snapshot" and not result.get("visibleText"):
                try:
                    prompt_visible = find_active_textprinter_text(
                        text_printers_raw=buffers.text_printers_raw,
                        gstringvar4_raw=buffers.gstringvar4_raw,
                        gdisplayedstringbattle_raw=buffers.gdisplayedstringbattle_raw,
                        include_inactive_window0=True,
                    )
                except TypeError:
                    prompt_visible = find_active_textprinter_text()
                if prompt_visible:
                    result["visibleText"] = prompt_visible
                else:
                    guess = decode_gba_string(buffers.gstringvar4_raw, 200, stop_at_prompt=True) if buffers.gstringvar4_raw else ""
                    if guess:
                        result["visibleText"] = guess

            choice_lines = []
            cursor = int(choice_menu.get("cursorPosition", 0) or 0)
            options = choice_menu.get("options") if isinstance(choice_menu.get("options"), list) else []
            for i, opt in enumerate(options):
                prefix = "►" if i == cursor else " "
                choice_lines.append(f"{prefix}{opt}")
            choice_text = "\n".join(choice_lines)
            if choice_text:
                if result["visibleText"]:
                    result["visibleText"] += f"\n\n{choice_text}"
                else:
                    result["visibleText"] = choice_text

        pages = result.get("allPages")
        if not result.get("visibleText") and isinstance(pages, list) and pages:
            current_page = int(result.get("currentPage") or 0)
            idx = (current_page - 1) if 0 < current_page <= len(pages) else 0
            result["visibleText"] = pages[idx]

        if int(result.get("pageCount") or 0) == 1 and int(result.get("currentPage") or 0) == 0:
            result["currentPage"] = 1

        has_dialog_evidence = bool(result.get("visibleText") or result.get("choiceMenu") or result.get("saveInfo"))
        if in_dialog or has_dialog_evidence:
            result["inDialog"] = True
            result["menuType"] = "dialog"

        return result

    if snapshot is None:
        try:
            snapshot = _mgba_client.mgba_read_ranges_bytes(_DIALOG_SNAPSHOT_RANGES)
        except Exception:
            snapshot = None
        else:
            mgba._record_mgba_read_ranges_bytes(_DIALOG_SNAPSHOT_RANGES, snapshot)

    if snapshot is not None and len(snapshot) >= len(_DIALOG_SNAPSHOT_RANGES):
        snap_reader = SnapshotMemoryReader.from_ranges(_DIALOG_SNAPSHOT_RANGES, snapshot[: len(_DIALOG_SNAPSHOT_RANGES)])
        snap_buffers = _read_snapshot_buffers(snap_reader)
        if snap_buffers is not None:
            return _compute(snap_buffers, mode="snapshot")

    # Slow fallback (no snapshot available)
    try:
        field_locked = are_field_controls_locked()
    except Exception:
        field_locked = False
    try:
        in_battle = is_in_battle()
    except Exception:
        in_battle = False
    try:
        callback2 = int(mgba.mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET))
    except Exception:
        callback2 = 0
    try:
        save_info_window_id = int(mgba.mgba_read8(SSAVE_INFO_WINDOWID_ADDR))
    except Exception:
        save_info_window_id = None

    return _compute(
        _DialogBuffers(
            field_locked=field_locked,
            in_battle=in_battle,
            callback2=callback2,
            save_info_window_id=save_info_window_id,
        ),
        mode="slow",
    )


# =============================================================================
