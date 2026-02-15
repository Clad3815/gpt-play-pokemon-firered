from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..constants.addresses import *  # noqa: F403
from ..game_data import get_ability_name, get_item_name, get_move_name, get_species_name, load_reference_tables
from ..memory import mgba
from ..memory.symbols import sym_addrs_by_prefix as _sym_addrs_by_prefix
from ..player import bag as player_bag
from ..player import pc as player_pc
from ..player import save as player_save
from ..player import snapshot as player_snapshot
from ..text import encoding as text_encoding
from ..text.text_printer import get_current_dialog_text, get_textprinter_text_for_window
from ..util.bytes import _s16_from_u16, _s8_from_u8, _u16le_from, _u32le_from, _u8_from

def mgba_read8(addr: int) -> int:
    return mgba.mgba_read8(addr)


def mgba_read16(addr: int) -> int:
    return mgba.mgba_read16(addr)


def mgba_read32(addr: int) -> int:
    return mgba.mgba_read32(addr)


def mgba_read_range(addr: int, length: int) -> List[int]:
    return mgba.mgba_read_range(addr, length)


def mgba_read_range_bytes(addr: int, length: int) -> bytes:
    return mgba.mgba_read_range_bytes(addr, length)


def mgba_read_ranges_bytes(ranges: List[Tuple[int, int]]) -> List[bytes]:
    return mgba.mgba_read_ranges_bytes(ranges)


def decode_gba_string(raw_bytes: Sequence[int], max_len: int = 500, stop_at_prompt: bool = False) -> str:
    return text_encoding.decode_gba_string(raw_bytes, max_len, stop_at_prompt=stop_at_prompt)


_ITEM_TM01_ID = 289  # FireRed vanilla: ITEM_TM01
_TMHM_COUNT = 58  # 50 TMs + 8 HMs
_PARTY_MSG_TEACH_WHICH_MON = 4  # pokefirered/include/constants/party_menu.h

_ITEM_DESCRIPTION_CACHE: Dict[int, str] = {}
_ITEM_MENU_ACTION_LABEL_CACHE: Dict[int, str] = {}
_PARTY_MENU_ACTION_LABEL_CACHE: Dict[int, str] = {}
_TM_CASE_MENU_ACTION_LABEL_CACHE: Dict[int, str] = {}
_MOVE_NAME_TO_ID_CACHE: Optional[Dict[str, int]] = None
_POKE_STORAGE_MENU_WINDOWID_OFFSET: Optional[int] = None
_POKE_STORAGE_BOX_TITLE_TEXT_OFFSET: Optional[int] = None
_POKE_STORAGE_MESSAGE_TEXT_OFFSET: Optional[int] = None

_LISTMENU_SILPHCO_FLOORS = 1
_ELEVATOR_MULTICHOICE_IDS = {
    20,  # MULTICHOICE_ROOFTOP_B1F
    31,  # MULTICHOICE_DEPT_STORE_ELEVATOR
    42,  # MULTICHOICE_ROCKET_HIDEOUT_ELEVATOR
}
_SCRIPT_LIST_MENU_TASK_FUNCS = (
    TASK_LISTMENU_HANDLE_INPUT_ADDR,
    TASK_SUSPEND_LIST_MENU_ADDR,
    TASK_REDRAW_SCROLL_ARROWS_AND_WAIT_INPUT_ADDR,
)
_BAG_CONTEXT_MENU_TASK_FUNCS = (
    TASK_ITEM_CONTEXT_MENU_BY_LOCATION_ADDR,
    TASK_FIELD_ITEM_CONTEXT_MENU_HANDLE_INPUT_ADDR,
)
_ITEM_PC_TASK_FUNCS = tuple(
    sorted({int(addr) for addr in _sym_addrs_by_prefix("Task_ItemPc") if int(addr) != 0})
) or (int(ITEM_STORAGE_PROCESS_INPUT_ADDR),)
_ITEM_PC_SUBMENU_TASK_FUNCS = tuple(
    sorted({int(addr) for addr in _sym_addrs_by_prefix("Task_ItemPcSubmenu") if int(addr) != 0})
)
_SCRIPT_LIST_TASK_DATA_LIST_TASK_ID_INDEX = 14
_LISTMENU_TEMPLATE_ITEMS_PTR_OFFSET = 0x00
_LISTMENU_TEMPLATE_TOTAL_ITEMS_OFFSET = 0x0C
_LISTMENU_CURSOR_POS_OFFSET = 0x18
_LISTMENU_ITEMS_ABOVE_OFFSET = 0x1A


def _party_menu_message_id_from_flags(flags: int) -> int:
    # struct PartyMenuInternal bitfields (pokefirered/src/party_menu.c):
    # chooseHalf:1, lastSelectedSlot:3, spriteIdConfirmPokeball:7, spriteIdCancelPokeball:7, messageId:14
    return (int(flags) >> 18) & 0x3FFF


def _get_tmhm_index(item_id: int) -> Optional[int]:
    idx = int(item_id) - _ITEM_TM01_ID
    if 0 <= idx < _TMHM_COUNT:
        return int(idx)
    return None


def _normalize_move_label_for_lookup(label: Optional[str]) -> str:
    txt = str(label or "").replace("_", " ").strip().upper()
    return " ".join(txt.split())


def _move_id_from_name_label(label: Optional[str]) -> Optional[int]:
    global _MOVE_NAME_TO_ID_CACHE
    norm = _normalize_move_label_for_lookup(label)
    if not norm:
        return None
    if norm in {"-", "—"}:
        return None
    if _MOVE_NAME_TO_ID_CACHE is None:
        cache: Dict[str, int] = {}
        try:
            tables = load_reference_tables()
            for mid, nm in tables.move_names.items():
                key = _normalize_move_label_for_lookup(str(nm))
                if key and key not in cache:
                    cache[key] = int(mid)
        except Exception:
            cache = {}
        _MOVE_NAME_TO_ID_CACHE = cache
    return _MOVE_NAME_TO_ID_CACHE.get(norm)


def _decode_party_mon_teach_info(raw_party: bytes, slot: int) -> Optional[Dict[str, Any]]:
    """
    Decode minimal per-Pokémon info needed for TM/HM learnability checks.

    Reads from a bulk `gPlayerParty` memory snapshot, avoiding per-field reads.
    """
    try:
        base = int(slot) * int(POKEMON_DATA_SIZE)
        if base < 0 or (base + POKEMON_DATA_SIZE) > len(raw_party):
            return None

        nickname_raw = raw_party[base + NICKNAME_OFFSET : base + NICKNAME_OFFSET + 10]
        nickname = decode_gba_string(nickname_raw, 10) or f"MON_{slot}"

        level = int(_u8_from(raw_party, base + LEVEL_OFFSET))
        current_hp = int(_u16le_from(raw_party, base + CURRENT_HP_OFFSET))
        max_hp = int(_u16le_from(raw_party, base + MAX_HP_OFFSET))

        pid = int(_u32le_from(raw_party, base + PID_OFFSET))
        otid = int(_u32le_from(raw_party, base + OTID_OFFSET))
        if pid == 0:
            return None

        enc = raw_party[base + ENCRYPTED_BLOCK_OFFSET : base + ENCRYPTED_BLOCK_OFFSET + ENCRYPTED_BLOCK_SIZE]
        if len(enc) < ENCRYPTED_BLOCK_SIZE:
            return None

        key = pid ^ otid
        dec = bytearray(ENCRYPTED_BLOCK_SIZE)
        for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
            word = _u32le_from(enc, i) ^ key
            dec[i : i + 4] = int(word & 0xFFFFFFFF).to_bytes(4, "little")

        order = SUBSTRUCTURE_ORDER[pid % 24]
        sub: Dict[str, bytes] = {}
        for i, ch in enumerate(order):
            start = i * SUBSTRUCTURE_SIZE
            sub[ch] = bytes(dec[start : start + SUBSTRUCTURE_SIZE])

        growth = sub.get("G", b"")
        attacks = sub.get("A", b"")
        misc = sub.get("M", b"")

        species_id = int(_u16le_from(growth, 0))
        moves = [
            int(_u16le_from(attacks, 0)),
            int(_u16le_from(attacks, 2)),
            int(_u16le_from(attacks, 4)),
            int(_u16le_from(attacks, 6)),
        ]
        iv_bitfield = int(_u32le_from(misc, 4))
        is_egg = ((iv_bitfield >> 30) & 1) != 0

        return {
            "slot": int(slot),
            "nickname": nickname,
            "level": level,
            "currentHP": current_hp,
            "maxHP": max_hp,
            "speciesId": species_id,
            "moves": moves,
            "isEgg": bool(is_egg),
        }
    except Exception:
        return None


def _flag_get_from_sb1(sb1_ptr: int, flag_id: int) -> bool:
    return player_save._flag_get_from_sb1(sb1_ptr, flag_id)


def get_player_money() -> int:
    return player_snapshot.get_player_money()


def get_security_key() -> int:
    return player_snapshot.get_security_key()


def get_start_menu_state(
    tasks_raw: Optional[bytes] = None,
    *,
    start_menu_window_id: Optional[int] = None,
    start_menu_num_actions: Optional[int] = None,
    start_menu_cursor_pos: Optional[int] = None,
    start_menu_actions_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Read the START menu state if it's open.
    """
    try:
        # Task-based gating is required:
        # - gMenuCallback can be stale after closing the menu.
        # - sStartMenuWindowId can also be stale (e.g. windows freed by CleanupOverworldWindowsAndTilemaps()).
        if (
            _find_active_task_by_func(TASK_SHOW_START_MENU_ADDR, tasks_raw) is None
            and _find_active_task_by_func(START_MENU_TASK_ADDR, tasks_raw) is None
        ):
            return None

        # Window id is still useful as a sanity check (0xFF = not visible).
        window_id = int(start_menu_window_id) if start_menu_window_id is not None else int(mgba_read8(START_MENU_WINDOW_ID_ADDR))
        if window_id == WINDOW_NONE:
            return None

        num_actions = (
            int(start_menu_num_actions)
            if start_menu_num_actions is not None
            else int(mgba_read8(START_MENU_NUM_ACTIONS_ADDR))
        )
        if num_actions == 0 or num_actions > 9:
            return None

        cursor_pos = (
            int(start_menu_cursor_pos)
            if start_menu_cursor_pos is not None
            else int(mgba_read8(START_MENU_CURSOR_POS_ADDR))
        )

        if start_menu_actions_raw is not None:
            action_ids = [int(v) for v in start_menu_actions_raw[:num_actions]]
        else:
            action_ids = mgba_read_range(START_MENU_ACTIONS_ADDR, num_actions)
        if not action_ids:
            return None

        options = []
        for i, action_id in enumerate(action_ids):
            name = START_MENU_ACTION_NAMES.get(action_id, f"UNKNOWN_{action_id}")
            options.append({"index": i, "name": name, "selected": i == cursor_pos})

        return {
            "type": "startMenu",
            "options": options,
            "selectedIndex": cursor_pos,
            "selectedOption": options[cursor_pos]["name"] if cursor_pos < len(options) else None,
        }
    except Exception:
        return None


def get_bag_menu_state(
    callback2: Optional[int] = None,
    tasks_raw: Optional[bytes] = None,
    *,
    smenu_raw: Optional[bytes] = None,
    sec_key: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Read the BAG menu state if it's open.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        callback2_masked = int(callback2) & 0xFFFFFFFE
        if callback2_masked not in ((CB2_BAG_MENU_RUN_ADDR & 0xFFFFFFFE), (CB2_BAG_ADDR & 0xFFFFFFFE)):
            return None

        bag_menu_ptr = mgba_read32(GBAGMENU_PTR_ADDR)
        if bag_menu_ptr == 0:
            return None

        pocket_id = mgba_read8(GBAGPOSITION_ADDR + BAGPOSITION_POCKET_OFFSET)
        if pocket_id > 4:
            return None

        pocket_name = BAG_POCKET_NAMES.get(pocket_id, f"POCKET_{pocket_id}")

        # FireRed bag data differs from FireRed:
        # - sBagMenuDisplay (BagMenuAlloc*) stores nItems/maxShowed for 3 pockets.
        # - context menu pointer/count are separate globals.
        firered_layout = BAGMENU_WINDOW_IDS_OFFSET == 0 and BAGMENU_NUM_ITEM_STACKS_OFFSET == 10
        context_task_active = _find_active_task_by_funcs(_BAG_CONTEXT_MENU_TASK_FUNCS, tasks_raw) is not None
        message_window_id: Optional[int] = None
        hide_close_bag = False

        if firered_layout:
            meta = mgba_read_range_bytes(
                bag_menu_ptr + BAGMENU_NUM_ITEM_STACKS_OFFSET,
                BAG_MENU_NUM_POCKETS * 2,
            )
            if pocket_id >= BAG_MENU_NUM_POCKETS:
                return None

            stacks_off = 0
            shown_off = BAG_MENU_NUM_POCKETS
            num_item_stacks = int(meta[stacks_off + pocket_id]) if (stacks_off + pocket_id) < len(meta) else 0
            num_shown_items = int(meta[shown_off + pocket_id]) if (shown_off + pocket_id) < len(meta) else 8
            context_items_ptr = int(mgba_read32(SCONTEXT_MENU_ITEMS_PTR_ADDR)) if SCONTEXT_MENU_ITEMS_PTR_ADDR else 0
            context_num_items = int(mgba_read8(SCONTEXT_MENU_NUM_ITEMS_ADDR)) if SCONTEXT_MENU_NUM_ITEMS_ADDR else 0
            # FireRed keeps these globals populated even outside the context menu.
            # Gate with the actual context-menu task state to avoid stale false positives.
            context_open = bool(context_task_active and context_items_ptr != 0 and context_num_items > 0)
        else:
            # FireRed layout (legacy path kept for compatibility).
            meta_len = (BAGMENU_NUM_SHOWN_ITEMS_OFFSET + 5) - BAGMENU_WINDOW_IDS_OFFSET
            meta = mgba_read_range_bytes(bag_menu_ptr + BAGMENU_WINDOW_IDS_OFFSET, meta_len)

            flags_off = BAGMENU_FLAGS_OFFSET - BAGMENU_WINDOW_IDS_OFFSET
            context_ptr_off = BAGMENU_CONTEXT_MENU_ITEMS_PTR_OFFSET - BAGMENU_WINDOW_IDS_OFFSET
            context_num_off = BAGMENU_CONTEXT_MENU_NUM_ITEMS_OFFSET - BAGMENU_WINDOW_IDS_OFFSET
            stacks_off = BAGMENU_NUM_ITEM_STACKS_OFFSET - BAGMENU_WINDOW_IDS_OFFSET
            shown_off = BAGMENU_NUM_SHOWN_ITEMS_OFFSET - BAGMENU_WINDOW_IDS_OFFSET

            window_ids = list(meta[0:5]) if len(meta) >= 5 else []
            if len(window_ids) >= 5:
                wid = int(window_ids[4]) & 0xFF
                if wid != WINDOW_NONE and 0 <= wid < 32:
                    message_window_id = wid

            flags = int(meta[flags_off]) if 0 <= flags_off < len(meta) else 0
            hide_close_bag = (flags & BAGMENU_HIDE_CLOSE_BAG_MASK) != 0

            num_item_stacks = int(meta[stacks_off + pocket_id]) if (stacks_off + pocket_id) < len(meta) else 0
            num_shown_items = int(meta[shown_off + pocket_id]) if (shown_off + pocket_id) < len(meta) else 8
            context_items_ptr = _u32le_from(meta, context_ptr_off) if (context_ptr_off + 4) <= len(meta) else 0
            context_num_items = int(meta[context_num_off]) if 0 <= context_num_off < len(meta) else 0
            context_open = any(int(b) != WINDOW_NONE for b in window_ids[0:4]) if len(window_ids) >= 4 else False

        if num_item_stacks < 0 or num_item_stacks > 255:
            num_item_stacks = 0
        if num_shown_items <= 0 or num_shown_items > 32:
            num_shown_items = 8

        context_menu = (
            get_bag_context_menu_state(
                bag_menu_ptr,
                smenu_raw=smenu_raw,
                num_items=context_num_items,
                items_ptr=context_items_ptr,
            )
            if context_open
            else None
        )
        context_menu_open = context_menu is not None

        # Prefer the real-time ListMenu state (stored in its own task), since gBagMenuState.* may be stale.
        list_state = _find_bag_list_menu_scroll_and_row(tasks_raw)
        if list_state is not None:
            scroll_pos, selected_row = list_state
        else:
            cursor_offset = BAGPOSITION_CURSOR_OFFSET + (pocket_id * 2)
            selected_row = int(mgba_read16(GBAGPOSITION_ADDR + cursor_offset))
            scroll_offset = BAGPOSITION_SCROLL_OFFSET + (pocket_id * 2)
            scroll_pos = int(mgba_read16(GBAGPOSITION_ADDR + scroll_offset))

        if scroll_pos < 0:
            scroll_pos = 0
        if selected_row < 0:
            selected_row = 0

        # FireRed bag list includes an extra "CANCEL" row after real pocket items.
        total_entries = int(num_item_stacks) + (0 if bool(hide_close_bag) else 1)
        if total_entries < 0:
            total_entries = 0

        selected_index = scroll_pos + selected_row
        if total_entries <= 0:
            selected_index = 0
            selected_row = 0
        if total_entries > 0 and selected_index >= total_entries:
            selected_index = total_entries - 1
            selected_row = max(0, min(selected_row, max(0, num_shown_items - 1)))

        start = max(0, scroll_pos)
        if total_entries > 0 and start >= total_entries:
            start = max(0, total_entries - num_shown_items)
        end = start + max(0, num_shown_items)
        if total_entries > 0:
            end = min(end, total_entries)

        # Scroll arrows for the bag item list (up/down at the right side of the list).
        max_scroll = 0
        up_visible = False
        down_visible = False
        if int(num_shown_items) > 0 and total_entries > int(num_shown_items):
            max_scroll = max(0, total_entries - int(num_shown_items))
            up_visible = int(scroll_pos) > 0
            down_visible = int(scroll_pos) < int(max_scroll)

        # While the context menu is open, the list scroll arrows are removed in-game.
        if context_menu_open:
            up_visible = False
            down_visible = False

        # Bag pocket itemSlots pointer
        pocket_ptr, pocket_cap = player_bag._get_pocket_info(int(pocket_id))

        visible_items: List[Dict[str, Any]] = []
        lines: List[str] = [pocket_name if context_menu_open else f"< {pocket_name} >"]
        if up_visible:
            lines.append("↑")

        # Bulk-read the visible item slots once (instead of per-item mgba_read16 calls).
        slots_by_index: Dict[int, Tuple[int, int]] = {}
        if pocket_ptr != 0 and pocket_cap > 0 and start < end:
            read_start = max(int(start), 0)
            # Real pocket slots stop at num_item_stacks (the extra row is CANCEL).
            read_end = min(int(end), int(num_item_stacks), int(pocket_cap))
            if read_start < read_end:
                raw = mgba_read_range_bytes(
                    int(pocket_ptr) + (read_start * player_bag.ITEM_ENTRY_SIZE),
                    (read_end - read_start) * player_bag.ITEM_ENTRY_SIZE,
                )

                key16: int = 0
                if pocket_id != 4:
                    try:
                        key16 = (int(sec_key) if sec_key is not None else int(get_security_key())) & 0xFFFF
                    except Exception:
                        key16 = 0
                else:
                    # Key Items don't display quantities; only compute if we already have a key.
                    if sec_key is not None:
                        key16 = int(sec_key) & 0xFFFF

                for i in range(read_end - read_start):
                    off = i * player_bag.ITEM_ENTRY_SIZE
                    if off + 3 >= len(raw):
                        break
                    item_id = int(_u16le_from(raw, off)) & 0xFFFF
                    enc_qty = int(_u16le_from(raw, off + 2)) & 0xFFFF
                    qty = int(enc_qty ^ key16) if key16 else 0
                    slots_by_index[read_start + i] = (item_id, qty)

        for list_index in range(start, end):
            is_close_bag = (not hide_close_bag) and (list_index == int(num_item_stacks))

            name = None
            slot = slots_by_index.get(int(list_index)) if not is_close_bag else None
            if not name:
                if is_close_bag:
                    name = "CANCEL"
                elif slot is not None and int(slot[0]) > 0:
                    name = get_item_name(int(slot[0])) or f"ITEM_{int(slot[0])}"
                else:
                    name = f"ITEM_{list_index}"

            item_id: Optional[int] = None
            qty: Optional[int] = None

            if slot is not None:
                item_id, slot_qty = slot
                if int(item_id) <= 0:
                    item_id = None
                else:
                    qty = int(slot_qty)

            show_qty = (qty is not None) and (pocket_id != 4) and (not is_close_bag)
            label = name
            if show_qty:
                label = f"{label} x{qty}"

            prefix = ("▷" if context_menu_open else "►") if list_index == selected_index else ""
            lines.append(f"{prefix}{label}")

            visible_items.append(
                {
                    "index": int(list_index),
                    "name": name,
                    "label": label,
                    "id": item_id,
                    "quantity": qty,
                    "isCloseBag": bool(is_close_bag),
                }
            )

        if down_visible:
            lines.append("↓")

        # Description for selected entry (best-effort)
        description = ""
        selected_name = ""
        selected_item_id: Optional[int] = None
        selected_is_close_bag = False
        if total_entries > 0 and start <= selected_index < end:
            entry = visible_items[selected_index - start]
            selected_is_close_bag = bool(entry.get("isCloseBag"))
            selected_name = str(entry.get("name") or "")
            selected_item_id = entry.get("id") if isinstance(entry.get("id"), int) else None

        if selected_is_close_bag:
            try:
                description = "Close the BAG."
            except Exception:
                description = "Close the BAG."
        elif context_menu_open and selected_name:
            description = f"{selected_name} is selected."
        elif selected_item_id is not None and selected_item_id > 0:
            description = _read_item_description_from_gitems(int(selected_item_id), 200)

        if description:
            lines.append("")
            lines.append(description)

        # Context menu (USE / GIVE / TOSS / ...)
        if context_menu:
            lines.append("")
            layout = context_menu.get("layout")
            if layout == "grid":
                cells = context_menu.get("cells") if isinstance(context_menu.get("cells"), list) else []
                columns = int(context_menu.get("columns", 2) or 2)
                rows = int(context_menu.get("rows", 0) or 0)
                cursor_raw = int(context_menu.get("cursorPositionRaw", 0) or 0)

                if columns <= 0:
                    columns = 2
                if rows <= 0 and columns > 0:
                    rows = (len(cells) + columns - 1) // columns

                if columns == 2:
                    for row in range(rows):
                        left_idx = row * 2
                        right_idx = left_idx + 1
                        left_label = str(cells[left_idx]) if left_idx < len(cells) else ""
                        right_label = str(cells[right_idx]) if right_idx < len(cells) else ""
                        if not left_label and not right_label:
                            continue

                        left_prefix = "►" if left_idx == cursor_raw else " "
                        left_part = f"{left_prefix}{left_label}" if left_label else left_prefix

                        line = left_part
                        if right_label:
                            line += " "
                            if right_idx == cursor_raw:
                                line += f"►{right_label}"
                            else:
                                line += right_label
                        lines.append(line.rstrip())
                else:
                    options = context_menu.get("options") if isinstance(context_menu.get("options"), list) else []
                    cursor = int(context_menu.get("cursorPosition", 0) or 0)
                    for i, opt in enumerate(options):
                        prefix = "►" if i == cursor else " "
                        lines.append(f"{prefix}{opt}")
            else:
                options = context_menu.get("options") if isinstance(context_menu.get("options"), list) else []
                cursor = int(context_menu.get("cursorPosition", 0) or 0)
                for i, opt in enumerate(options):
                    prefix = "►" if i == cursor else " "
                    lines.append(f"{prefix}{opt}")

        return {
            "type": "bagMenu",
            "pocketId": int(pocket_id),
            "pocketName": pocket_name,
            "messageWindowId": int(message_window_id) if message_window_id is not None else None,
            "cursorPosition": int(selected_row),
            "scrollPosition": int(scroll_pos),
            "selectedIndex": int(selected_index),
            "numItemStacks": int(num_item_stacks),
            "numShownItems": int(num_shown_items),
            "hideCloseBagText": bool(hide_close_bag),
            "visibleItems": visible_items,
            "selectedItemId": selected_item_id,
            "description": description,
            "scrollIndicators": {
                "upVisible": bool(up_visible),
                "downVisible": bool(down_visible),
                "maxScroll": int(max_scroll),
                "totalEntries": int(total_entries),
            },
            "contextMenu": context_menu,
            "visibleText": "\n".join(lines),
        }
    except Exception:
        return None


def get_tm_case_state(
    callback2: Optional[int] = None,
    tasks_raw: Optional[bytes] = None,
    *,
    smenu_raw: Optional[bytes] = None,
    sec_key: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect and extract the dedicated TM CASE UI (tm_case.c).

    This screen is not the regular Bag callback/path, so it needs dedicated detection.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        cb2_masked = int(callback2) & 0xFFFFFFFE
        is_tmcase_cb = cb2_masked in (
            int(CB2_TM_CASE_IDLE_ADDR) & 0xFFFFFFFE,
            int(CB2_TM_CASE_SETUP_ADDR) & 0xFFFFFFFE,
        )
        if not is_tmcase_cb:
            return None

        # tm_case.c static state
        static_raw = mgba_read_range_bytes(STM_CASE_STATIC_RESOURCES_ADDR, 0x0C)
        selected_row = int(_u16le_from(static_raw, TMCASE_STATIC_SELECTED_ROW_OFFSET)) if len(static_raw) >= 0x0C else 0
        scroll_pos = int(_u16le_from(static_raw, TMCASE_STATIC_SCROLL_OFFSET)) if len(static_raw) >= 0x0C else 0
        menu_type = int(_u8_from(static_raw, TMCASE_STATIC_MENU_TYPE_OFFSET)) if len(static_raw) >= 0x06 else 0
        allow_select_close = bool(int(_u8_from(static_raw, TMCASE_STATIC_ALLOW_SELECT_CLOSE_OFFSET))) if len(static_raw) >= 0x06 else False

        # tm_case.c dynamic state (pointer may be NULL while setting up / tearing down)
        dynamic_ptr = int(mgba_read32(STM_CASE_DYNAMIC_RESOURCES_PTR_ADDR))
        max_shown = 5
        num_tms = 0
        context_window_id = WINDOW_NONE
        action_indices_ptr = 0
        num_actions = 0
        if 0x02000000 <= dynamic_ptr <= 0x0203FFFF:
            dyn = mgba_read_range_bytes(dynamic_ptr, 0x14)
            if len(dyn) >= 0x14:
                max_shown = int(_u8_from(dyn, TMCASE_DYNAMIC_MAX_TMS_SHOWN_OFFSET))
                num_tms = int(_u8_from(dyn, TMCASE_DYNAMIC_NUM_TMS_OFFSET))
                context_window_id = int(_u8_from(dyn, TMCASE_DYNAMIC_CONTEXT_MENU_WINDOW_ID_OFFSET))
                action_indices_ptr = int(_u32le_from(dyn, TMCASE_DYNAMIC_MENU_ACTION_INDICES_PTR_OFFSET))
                num_actions = int(_u8_from(dyn, TMCASE_DYNAMIC_NUM_MENU_ACTIONS_OFFSET))

        # TM CASE pocket is pocket index 3 in gBagPockets.
        pocket_ptr, pocket_cap = player_bag._get_pocket_info(3)
        if pocket_ptr == 0 or pocket_cap <= 0:
            return None

        key16: int = 0
        try:
            key16 = (int(sec_key) if sec_key is not None else int(get_security_key())) & 0xFFFF
        except Exception:
            key16 = 0

        total_slots = min(int(pocket_cap), _TMHM_COUNT)
        pocket_raw = mgba_read_range_bytes(int(pocket_ptr), total_slots * player_bag.ITEM_ENTRY_SIZE)

        if num_tms <= 0 or num_tms > total_slots:
            # Fallback if dynamic state isn't ready yet.
            num_tms = 0
            for i in range(total_slots):
                off = i * player_bag.ITEM_ENTRY_SIZE
                item_id_i = int(_u16le_from(pocket_raw, off))
                if item_id_i <= 0:
                    break
                num_tms += 1

        if max_shown <= 0 or max_shown > 8:
            max_shown = 5

        total_entries = int(num_tms) + 1  # + CLOSE
        if total_entries <= 0:
            total_entries = 1

        if scroll_pos < 0:
            scroll_pos = 0
        if selected_row < 0:
            selected_row = 0

        selected_index = int(scroll_pos) + int(selected_row)
        if selected_index >= total_entries:
            selected_index = total_entries - 1

        start = int(scroll_pos)
        if start >= total_entries:
            start = max(0, total_entries - int(max_shown))
        end = min(total_entries, start + int(max_shown))

        max_scroll = max(0, total_entries - int(max_shown))
        up_visible = int(scroll_pos) > 0
        down_visible = int(scroll_pos) < int(max_scroll)

        visible_items: List[Dict[str, Any]] = []
        selected_item_id: Optional[int] = None
        selected_item_label: Optional[str] = None
        selected_tm_index: Optional[int] = None
        selected_move_id: Optional[int] = None
        selected_is_close = selected_index == int(num_tms)

        for i in range(start, end):
            is_close = i == int(num_tms)
            if is_close:
                visible_items.append(
                    {
                        "index": int(i),
                        "name": "CLOSE",
                        "label": "CLOSE",
                        "id": None,
                        "quantity": None,
                        "isClose": True,
                        "isHm": False,
                        "tmhmIndex": None,
                        "moveId": None,
                        "moveName": None,
                    }
                )
                continue

            off = i * player_bag.ITEM_ENTRY_SIZE
            item_id = int(_u16le_from(pocket_raw, off)) if (off + 3) < len(pocket_raw) else 0
            enc_qty = int(_u16le_from(pocket_raw, off + 2)) if (off + 3) < len(pocket_raw) else 0
            qty = int(enc_qty ^ key16) if key16 else 0
            tm_index = _get_tmhm_index(item_id)
            move_id = int(mgba_read16(STMHM_MOVES_ADDR + (int(tm_index) * 2))) if tm_index is not None else 0
            move_name = (get_move_name(int(move_id)) or f"MOVE_{int(move_id)}").replace("_", " ") if move_id > 0 else ""
            is_hm = bool(tm_index is not None and int(tm_index) >= 50)

            if tm_index is None:
                code = f"ITEM_{item_id}"
            elif is_hm:
                code = f"HM No{(int(tm_index) - 50) + 1}"
            else:
                code = f"No{int(tm_index) + 1:02d}"

            base_label = f"{code} {move_name}".strip()
            label = base_label if is_hm else f"{base_label} x {max(0, int(qty))}"

            if i == selected_index:
                selected_item_id = int(item_id) if item_id > 0 else None
                selected_item_label = base_label
                selected_tm_index = int(tm_index) if tm_index is not None else None
                selected_move_id = int(move_id) if move_id > 0 else None

            visible_items.append(
                {
                    "index": int(i),
                    "name": move_name or code,
                    "label": label,
                    "id": int(item_id) if item_id > 0 else None,
                    "quantity": int(qty) if not is_hm else None,
                    "isClose": False,
                    "isHm": bool(is_hm),
                    "tmhmIndex": int(tm_index) if tm_index is not None else None,
                    "moveId": int(move_id) if move_id > 0 else None,
                    "moveName": move_name or None,
                    "displayCode": code,
                }
            )

        # Move details panel mirrors PrintMoveInfo() in tm_case.c.
        move_info: Dict[str, Any] = {
            "typeId": None,
            "type": "---",
            "power": None,
            "powerText": "---",
            "accuracy": None,
            "accuracyText": "---",
            "pp": None,
            "ppText": "---",
        }
        description = ""
        if selected_is_close:
            description = _read_gba_cstring(GTEXT_TMCASE_WILL_BE_PUT_AWAY_ADDR, 220) or "TM CASE will be put away."
        elif selected_item_id is not None and selected_item_id > 0:
            description = _read_item_description_from_gitems(int(selected_item_id), 220)

            if selected_move_id is not None and selected_move_id > 0:
                move_raw = mgba_read_range_bytes(
                    GBATTLE_MOVES_ADDR + (int(selected_move_id) * BATTLE_MOVE_SIZE),
                    BATTLE_MOVE_SIZE,
                )
                if len(move_raw) >= BATTLE_MOVE_SIZE:
                    power = int(_u8_from(move_raw, 1))
                    type_id = int(_u8_from(move_raw, 2))
                    accuracy = int(_u8_from(move_raw, 3))
                    pp = int(_u8_from(move_raw, 4))
                    move_info = {
                        "typeId": int(type_id),
                        "type": _move_type_label(type_id) or f"TYPE_{int(type_id)}",
                        "power": int(power),
                        "powerText": "---" if int(power) < 2 else str(int(power)),
                        "accuracy": int(accuracy),
                        "accuracyText": "---" if int(accuracy) == 0 else str(int(accuracy)),
                        "pp": int(pp),
                        "ppText": str(int(pp)),
                    }

        context_task = _find_active_task_by_func(TASK_TM_CASE_CONTEXT_MENU_HANDLE_INPUT_ADDR, tasks_raw)
        selected_field_task = _find_active_task_by_func(TASK_TM_CASE_SELECTED_FIELD_ADDR, tasks_raw)
        context_open = bool(
            context_task is not None
            or selected_field_task is not None
            or (
                context_window_id != WINDOW_NONE
                and 0 <= int(context_window_id) < 32
                and int(action_indices_ptr) != 0
                and int(num_actions) > 0
            )
        )

        context_menu: Optional[Dict[str, Any]] = None
        if context_open:
            action_ids: List[int] = []
            if action_indices_ptr != 0 and 0 < int(num_actions) <= 4:
                raw_ids = mgba_read_range_bytes(int(action_indices_ptr), int(num_actions))
                action_ids = [int(v) & 0xFF for v in raw_ids[: int(num_actions)]]
            if not action_ids:
                # Field fallback: USE / GIVE / EXIT
                action_ids = [0, 1, 2]

            uncached = [aid for aid in action_ids if aid not in _TM_CASE_MENU_ACTION_LABEL_CACHE]
            if uncached and TMCASE_MENU_ACTIONS_ADDR:
                uniq = sorted(set(int(a) & 0xFF for a in uncached))
                ranges = [(TMCASE_MENU_ACTIONS_ADDR + (aid * MENU_ACTION_SIZE), 4) for aid in uniq]
                ptr_chunks = mgba_read_ranges_bytes(ranges)
                for aid, chunk in zip(uniq, ptr_chunks):
                    ptr = int(_u32le_from(chunk, 0)) if isinstance(chunk, (bytes, bytearray)) and len(chunk) >= 4 else 0
                    label = _read_gba_cstring(ptr, 24) if ptr else ""
                    _TM_CASE_MENU_ACTION_LABEL_CACHE[int(aid)] = label or ""

            fallback_labels = {0: "USE", 1: "GIVE", 2: "EXIT"}
            options = [
                (_TM_CASE_MENU_ACTION_LABEL_CACHE.get(int(aid), "") or fallback_labels.get(int(aid), f"ACTION_{int(aid)}"))
                for aid in action_ids
            ]

            cursor = _read_menu_cursor_pos(smenu_raw)
            if cursor < 0:
                cursor = 0
            if cursor >= len(options):
                cursor = max(0, len(options) - 1)

            context_menu = {
                "type": "tmCaseContextMenu",
                "layout": "list",
                "windowId": int(context_window_id) if context_window_id != WINDOW_NONE else None,
                "cursorPosition": int(cursor),
                "selectedOption": options[cursor] if options else None,
                "options": options,
                "actionIds": [int(aid) for aid in action_ids],
            }

            # Scroll arrows are hidden while the context menu is open.
            up_visible = False
            down_visible = False

        lines: List[str] = ["TM CASE"]
        if up_visible:
            lines.append("↑")
        for entry in visible_items:
            idx = int(entry.get("index") or 0)
            prefix = ("▷" if context_open else "►") if idx == selected_index else " "
            lines.append(f"{prefix}{str(entry.get('label') or '').strip()}".rstrip())
        if down_visible:
            lines.append("↓")

        lines.append("")
        lines.append(f"TYPE {move_info.get('type') or '---'}")
        lines.append(f"POWER {move_info.get('powerText') or '---'}")
        lines.append(f"ACCURACY {move_info.get('accuracyText') or '---'}")
        lines.append(f"PP {move_info.get('ppText') or '---'}")
        if description:
            lines.append("")
            lines.extend([ln for ln in str(description).splitlines() if ln.strip()])

        if context_menu is not None:
            lines.append("")
            if selected_item_label:
                lines.append(f"{selected_item_label} is selected.")
            opts = context_menu.get("options") if isinstance(context_menu.get("options"), list) else []
            cur = int(context_menu.get("cursorPosition") or 0)
            for i, opt in enumerate(opts):
                prefix = "►" if i == cur else " "
                lines.append(f"{prefix}{opt}")

        selected_move = None
        if selected_move_id is not None and selected_move_id > 0:
            selected_move = {
                "tmhmIndex": int(selected_tm_index) if selected_tm_index is not None else None,
                "moveId": int(selected_move_id),
                "name": (get_move_name(int(selected_move_id)) or f"MOVE_{int(selected_move_id)}").replace("_", " "),
                "typeId": move_info.get("typeId"),
                "type": move_info.get("type"),
                "power": move_info.get("power"),
                "powerText": move_info.get("powerText"),
                "accuracy": move_info.get("accuracy"),
                "accuracyText": move_info.get("accuracyText"),
                "pp": move_info.get("pp"),
                "ppText": move_info.get("ppText"),
                "description": description or None,
            }

        menu_type_name = {
            0: "field",
            1: "giveParty",
            2: "sell",
            3: "givePc",
            4: "pokedude",
        }.get(int(menu_type), f"mode_{int(menu_type)}")

        return {
            "type": "tmCase",
            "menuMode": menu_type_name,
            "allowSelectClose": bool(allow_select_close),
            "cursorPosition": int(selected_row),
            "scrollPosition": int(scroll_pos),
            "selectedIndex": int(selected_index),
            "numItems": int(num_tms),
            "numShownItems": int(max_shown),
            "visibleItems": visible_items,
            "selectedItemId": int(selected_item_id) if selected_item_id is not None else None,
            "selectedMove": selected_move,
            "description": description or "",
            "scrollIndicators": {
                "upVisible": bool(up_visible),
                "downVisible": bool(down_visible),
                "maxScroll": int(max_scroll),
                "totalEntries": int(total_entries),
            },
            "contextMenu": context_menu,
            "visibleText": "\n".join(lines).strip(),
        }
    except Exception:
        return None


def get_trainer_card_state(callback2: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Read the Trainer Card state if it's being displayed.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        if (int(callback2) & 0xFFFFFFFE) != (CB2_TRAINER_CARD_ADDR & 0xFFFFFFFE):
            return None

        sb2_ptr = mgba_read32(GSAVEBLOCK2_PTR_ADDR)
        if sb2_ptr == 0:
            return None

        name_bytes = mgba_read_range(sb2_ptr + SB2_PLAYER_NAME_OFFSET, 8)
        player_name = decode_gba_string(name_bytes, 8)

        trainer_id_full = mgba_read32(sb2_ptr + SB2_TRAINER_ID_OFFSET)
        trainer_id = trainer_id_full & 0xFFFF

        play_hours = mgba_read16(sb2_ptr + SB2_PLAY_TIME_HOURS_OFFSET)
        play_minutes = mgba_read8(sb2_ptr + SB2_PLAY_TIME_MINUTES_OFFSET)
        play_seconds = mgba_read8(sb2_ptr + SB2_PLAY_TIME_SECONDS_OFFSET)

        encryption_key = mgba_read32(sb2_ptr + SB2_ENCRYPTION_KEY_OFFSET)

        sb1_ptr = mgba_read32(GSAVEBLOCK1_PTR_ADDR)
        money_encrypted = mgba_read32(sb1_ptr + SB1_MONEY_OFFSET)
        money = money_encrypted ^ encryption_key

        flags_base = sb1_ptr + SB1_FLAGS_OFFSET
        badges = []
        badge_count = 0
        for i in range(NUM_BADGES):
            flag_id = FLAG_BADGE01 + i
            byte_offset = flag_id // 8
            bit_offset = flag_id % 8
            flag_byte = mgba_read8(flags_base + byte_offset)
            has_badge = (flag_byte >> bit_offset) & 1
            badges.append(has_badge == 1)
            if has_badge:
                badge_count += 1

        play_time = f"{play_hours}:{play_minutes:02d}"

        return {
            "type": "trainerCard",
            "playerName": player_name,
            "trainerId": trainer_id,
            "trainerIdFormatted": f"{trainer_id:05d}",
            "money": money,
            "moneyFormatted": f"₽{money}",
            "playTimeHours": play_hours,
            "playTimeMinutes": play_minutes,
            "playTimeSeconds": play_seconds,
            "playTime": play_time,
            "badges": badges,
            "badgeCount": badge_count,
        }
    except Exception:
        return None


def get_option_menu_state(callback2: Optional[int] = None, tasks_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Read the Option Menu state if it's being displayed.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)

        callback2_masked = int(callback2) & 0xFFFFFFFE

        # The option menu can be visible while callback2 is either:
        # - CB2_InitOptionMenu (state machine)
        # - the option-menu MainCB2 (static function; symbol selection can be ambiguous)
        # Additionally, we can reliably identify it by its task funcs.
        option_task_addrs = {
            TASK_OPTION_MENU_FADEIN_ADDR & 0xFFFFFFFE,
            TASK_OPTION_MENU_PROCESSINPUT_ADDR & 0xFFFFFFFE,
            TASK_OPTION_MENU_SAVE_ADDR & 0xFFFFFFFE,
            TASK_OPTION_MENU_FADEOUT_ADDR & 0xFFFFFFFE,
        }

        option_task_active = False
        if tasks_raw is not None and len(tasks_raw) >= (NUM_TASKS * TASK_SIZE):
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in option_task_addrs:
                    option_task_active = True
                    break
        else:
            for i in range(NUM_TASKS):
                task_addr = GTASKS_ADDR + (i * TASK_SIZE)
                if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in option_task_addrs:
                    option_task_active = True
                    break

        if callback2_masked not in (
            CB2_INIT_OPTION_MENU_ADDR & 0xFFFFFFFE,
            CB2_OPTION_MENU_ADDR & 0xFFFFFFFE,
        ) and not option_task_active:
            return None

        sb2_ptr = mgba_read32(GSAVEBLOCK2_PTR_ADDR)
        if sb2_ptr == 0:
            return None

        # SaveBlock2 values are persisted settings (fallback when live option struct is unavailable).
        button_mode = mgba_read8(sb2_ptr + SB2_BUTTON_MODE_OFFSET)
        options_word = mgba_read16(sb2_ptr + SB2_OPTIONS_OFFSET)

        text_speed = options_word & 0x7
        frame_type = (options_word >> 3) & 0x1F
        sound = (options_word >> 8) & 0x1
        battle_style = (options_word >> 9) & 0x1
        battle_scene_off = (options_word >> 10) & 0x1

        # Prefer live values from struct OptionMenu (option_menu.c: sOptionMenuPtr) while the menu is open.
        # This captures unsaved changes and the real cursor position.
        live_text_speed: Optional[int] = None
        live_battle_scene_off: Optional[int] = None
        live_battle_style: Optional[int] = None
        live_sound: Optional[int] = None
        live_button_mode: Optional[int] = None
        live_frame_type: Optional[int] = None
        live_cursor_pos: Optional[int] = None

        if SOPTION_MENU_PTR_ADDR:
            option_ptr = int(mgba_read32(SOPTION_MENU_PTR_ADDR))
            if 0x02000000 <= option_ptr <= 0x0203FFFF:
                try:
                    # struct OptionMenu:
                    #   0x00 u16 option[7]
                    #   0x0E u16 cursorPos
                    raw = mgba_read_range_bytes(
                        option_ptr + OPTION_MENU_OPTION_ARRAY_OFFSET,
                        OPTION_MENU_CURSOR_POS_OFFSET + 2,
                    )
                    if len(raw) >= (OPTION_MENU_CURSOR_POS_OFFSET + 2):
                        live_text_speed = int(_u16le_from(raw, 0x00))
                        live_battle_scene_off = int(_u16le_from(raw, 0x02))
                        live_battle_style = int(_u16le_from(raw, 0x04))
                        live_sound = int(_u16le_from(raw, 0x06))
                        live_button_mode = int(_u16le_from(raw, 0x08))
                        live_frame_type = int(_u16le_from(raw, 0x0A))
                        live_cursor_pos = int(_u16le_from(raw, OPTION_MENU_CURSOR_POS_OFFSET))
                except Exception:
                    pass

        text_speed_idx = (
            int(live_text_speed)
            if live_text_speed is not None and 0 <= int(live_text_speed) < len(OPTION_TEXT_SPEED_NAMES)
            else int(text_speed)
        )
        battle_scene_idx = (
            int(live_battle_scene_off)
            if live_battle_scene_off is not None and 0 <= int(live_battle_scene_off) < len(OPTION_BATTLE_SCENE_NAMES)
            else int(battle_scene_off)
        )
        battle_style_idx = (
            int(live_battle_style)
            if live_battle_style is not None and 0 <= int(live_battle_style) < len(OPTION_BATTLE_STYLE_NAMES)
            else int(battle_style)
        )
        sound_idx = int(live_sound) if live_sound is not None and 0 <= int(live_sound) < len(OPTION_SOUND_NAMES) else int(sound)
        button_mode_idx = (
            int(live_button_mode)
            if live_button_mode is not None and 0 <= int(live_button_mode) < len(OPTION_BUTTON_MODE_NAMES)
            else int(button_mode)
        )
        frame_type_idx = int(live_frame_type) if live_frame_type is not None and 0 <= int(live_frame_type) <= 31 else int(frame_type)

        text_speed_name = OPTION_TEXT_SPEED_NAMES[text_speed_idx] if text_speed_idx < 3 else "FAST"
        battle_scene_name = OPTION_BATTLE_SCENE_NAMES[battle_scene_idx] if battle_scene_idx < 2 else "ON"
        battle_style_name = OPTION_BATTLE_STYLE_NAMES[battle_style_idx] if battle_style_idx < 2 else "SHIFT"
        sound_name = OPTION_SOUND_NAMES[sound_idx] if sound_idx < 2 else "MONO"
        button_mode_name = OPTION_BUTTON_MODE_NAMES[button_mode_idx] if button_mode_idx < 3 else "NORMAL"

        cursor_pos = live_cursor_pos if live_cursor_pos is not None else 0
        if live_cursor_pos is None and tasks_raw is not None:
            targets = option_task_addrs
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if (base + TASK_SIZE) > len(tasks_raw):
                    break
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in targets:
                    cursor_pos = int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET))
                    cursor_pos = cursor_pos - 65536 if cursor_pos > 32767 else cursor_pos
                    break
        elif live_cursor_pos is None:
            for i in range(NUM_TASKS):
                task_addr = GTASKS_ADDR + (i * TASK_SIZE)
                task_func = mgba_read32(task_addr + TASK_FUNC_OFFSET)
                task_func_masked = task_func & 0xFFFFFFFE
                if task_func_masked in option_task_addrs:
                    cursor_pos = int(mgba_read16(task_addr + TASK_DATA_OFFSET))
                    if cursor_pos > 32767:
                        cursor_pos = cursor_pos - 65536
                    break

        if len(OPTION_MENU_ITEMS) > 0:
            if cursor_pos < 0:
                cursor_pos = 0
            elif cursor_pos >= len(OPTION_MENU_ITEMS):
                cursor_pos = len(OPTION_MENU_ITEMS) - 1
        else:
            cursor_pos = 0

        return {
            "type": "optionMenu",
            "cursorPosition": cursor_pos,
            "selectedItem": OPTION_MENU_ITEMS[cursor_pos] if cursor_pos < len(OPTION_MENU_ITEMS) else "UNKNOWN",
            "textSpeed": text_speed_name,
            "battleScene": battle_scene_name,
            "battleStyle": battle_style_name,
            "sound": sound_name,
            "buttonMode": button_mode_name,
            "frameType": frame_type_idx + 1,
        }
    except Exception:
        return None


def get_title_menu_state(callback2: Optional[int] = None, tasks_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect and extract the title screen main menu state.

    This is the menu shown on boot with options like:
      CONTINUE / NEW GAME / MYSTERY GIFT / OPTION
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)

        callback2_masked = int(callback2) & 0xFFFFFFFE

        main_menu_cb2_addrs = {
            CB2_MAIN_MENU_ADDR & 0xFFFFFFFE,
            CB2_INIT_MAIN_MENU_ADDR & 0xFFFFFFFE,
            CB2_REINIT_MAIN_MENU_ADDR & 0xFFFFFFFE,
        }
        main_menu_task_addrs = {
            TASK_DISPLAY_MAIN_MENU_ADDR & 0xFFFFFFFE,
            TASK_HIGHLIGHT_SELECTED_MAIN_MENU_ITEM_ADDR & 0xFFFFFFFE,
            TASK_HANDLE_MAIN_MENU_INPUT_ADDR & 0xFFFFFFFE,
        }

        main_menu_task_active = False
        if tasks_raw is not None and len(tasks_raw) >= (NUM_TASKS * TASK_SIZE):
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in main_menu_task_addrs:
                    main_menu_task_active = True
                    break
        else:
            for i in range(NUM_TASKS):
                task_addr = GTASKS_ADDR + (i * TASK_SIZE)
                if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in main_menu_task_addrs:
                    main_menu_task_active = True
                    break

        if callback2_masked not in main_menu_cb2_addrs and not main_menu_task_active:
            return None

        # Prefer the input task (holds the live cursor), fall back to the draw/highlight tasks.
        task_id = _find_active_task_by_func(TASK_HANDLE_MAIN_MENU_INPUT_ADDR, tasks_raw)
        if task_id is None:
            task_id = _find_active_task_by_func(TASK_HIGHLIGHT_SELECTED_MAIN_MENU_ITEM_ADDR, tasks_raw)
        if task_id is None:
            task_id = _find_active_task_by_func(TASK_DISPLAY_MAIN_MENU_ADDR, tasks_raw)
        if task_id is None:
            return None

        if tasks_raw is not None:
            base = task_id * TASK_SIZE
            menu_type = int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET))
            curr_item = _s16_from_u16(int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + 2)))
        else:
            task_addr = GTASKS_ADDR + (task_id * TASK_SIZE)
            menu_type = int(mgba_read16(task_addr + TASK_DATA_OFFSET))
            curr_item = _s16_from_u16(int(mgba_read16(task_addr + TASK_DATA_OFFSET + 2)))

        variant_name = TITLE_MENU_VARIANT_NAMES.get(menu_type, f"UNKNOWN_{menu_type}")

        option_names = TITLE_MENU_OPTIONS.get(menu_type)
        if option_names is None:
            # FireRed uses only tMenuType (data[0]) + tCursorPos (data[1]) for this task.
            # Keep a conservative fallback shape for unknown variants.
            count = max(1, min(menu_type + 1, 10))
            option_names = [f"UNKNOWN_{i}" for i in range(count)]

        item_count = int(len(option_names))
        is_scrolled = False

        if item_count <= 0:
            return None
        if curr_item < 0:
            curr_item = 0
        elif curr_item >= item_count:
            curr_item = item_count - 1

        options = []
        for i, name in enumerate(option_names):
            options.append({"index": i, "name": name, "selected": i == curr_item})

        selected_option = options[curr_item]["name"] if 0 <= curr_item < len(options) else None

        return {
            "type": "titleMenu",
            "variant": variant_name,
            "menuTypeValue": int(menu_type),
            "itemCount": int(item_count),
            "isScrolled": bool(is_scrolled),
            "options": options,
            "selectedIndex": int(curr_item),
            "selectedOption": selected_option,
        }
    except Exception:
        return None


TITLE_SCREEN_PRESS_START_VISIBLE_TEXT = "Pokémon FireRed Version\n PRESS START\n2004 Game Freak inc."


def get_title_screen_press_start_state(
    callback2: Optional[int] = None,
    tasks_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the title screen phase where "PRESS START" is shown.

    Note: This screen is sprite-driven (no TextPrinter), so we synthesize visibleText when detected.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        callback2_masked = int(callback2) & 0xFFFFFFFE

        title_cb2_addrs = {
            CB2_INIT_TITLE_SCREEN_ADDR & 0xFFFFFFFE,
            CB2_TITLE_SCREEN_ADDR & 0xFFFFFFFE,
        }
        title_task_addrs = {
            TASK_TITLE_SCREEN_PHASE1_ADDR & 0xFFFFFFFE,
            TASK_TITLE_SCREEN_PHASE2_ADDR & 0xFFFFFFFE,
            TASK_TITLE_SCREEN_PHASE3_ADDR & 0xFFFFFFFE,
        }

        phase = None
        any_task_active = False
        if tasks_raw is not None and len(tasks_raw) >= (NUM_TASKS * TASK_SIZE):
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in title_task_addrs:
                    any_task_active = True
                    if task_func_masked == (TASK_TITLE_SCREEN_PHASE1_ADDR & 0xFFFFFFFE):
                        phase = "phase1"
                    elif task_func_masked == (TASK_TITLE_SCREEN_PHASE2_ADDR & 0xFFFFFFFE):
                        phase = "phase2"
                    elif task_func_masked == (TASK_TITLE_SCREEN_PHASE3_ADDR & 0xFFFFFFFE):
                        phase = "pressStart"
                    break
        else:
            for i in range(NUM_TASKS):
                task_addr = GTASKS_ADDR + (i * TASK_SIZE)
                if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in title_task_addrs:
                    any_task_active = True
                    if task_func_masked == (TASK_TITLE_SCREEN_PHASE1_ADDR & 0xFFFFFFFE):
                        phase = "phase1"
                    elif task_func_masked == (TASK_TITLE_SCREEN_PHASE2_ADDR & 0xFFFFFFFE):
                        phase = "phase2"
                    elif task_func_masked == (TASK_TITLE_SCREEN_PHASE3_ADDR & 0xFFFFFFFE):
                        phase = "pressStart"
                    break

        if callback2_masked not in title_cb2_addrs and not any_task_active:
            return None

        return {"type": "titleScreen", "phase": phase}
    except Exception:
        return None


_CONTROLS_GUIDE_TASK_FUNCS = (
    TASK_CONTROLS_GUIDE_LOAD_PAGE_ADDR,
    TASK_CONTROLS_GUIDE_HANDLE_INPUT_ADDR,
    TASK_CONTROLS_GUIDE_CHANGE_PAGE_ADDR,
    TASK_CONTROLS_GUIDE_CLEAR_ADDR,
)
_PIKACHU_INTRO_TASK_FUNCS = (
    TASK_PIKACHU_INTRO_LOAD_PAGE1_ADDR,
    TASK_PIKACHU_INTRO_HANDLE_INPUT_ADDR,
)
_QUEST_LOG_STATE_NAMES = {
    QL_STATE_RECORDING: "RECORDING",
    QL_STATE_PLAYBACK: "PLAYBACK",
    QL_STATE_PLAYBACK_LAST: "PLAYBACK_LAST",
}
_QUEST_LOG_PLAYBACK_STATE_NAMES = {
    QL_PLAYBACK_STATE_STOPPED: "STOPPED",
    QL_PLAYBACK_STATE_RUNNING: "RUNNING",
    QL_PLAYBACK_STATE_RECORDING: "RECORDING",
    QL_PLAYBACK_STATE_ACTION_END: "ACTION_END",
    QL_PLAYBACK_STATE_RECORDING_NO_DELAY: "RECORDING_NO_DELAY",
}


def get_controls_guide_state(tasks_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect and extract Oak Speech's early-game Controls Guide (oak_speech.c).

    This is the blue full-screen tutorial shown before Oak's speech with top bar:
      CONTROLS / {A_BUTTON}NEXT
    """
    try:
        task_id = _find_active_task_by_funcs(_CONTROLS_GUIDE_TASK_FUNCS, tasks_raw)
        if task_id is None:
            return None

        resources_ptr = int(mgba_read32(SOAK_SPEECH_RESOURCES_PTR_ADDR))
        if not (0x02000000 <= resources_ptr <= 0x0203FFFF):
            return None

        page_raw = int(mgba_read16(resources_ptr + OAK_SPEECH_CURRENT_PAGE_OFFSET))
        if page_raw < 0 or page_raw >= int(CONTROLS_GUIDE_NUM_PAGES):
            return None

        def _txt(addr: int, fallback: str, max_len: int = 320) -> str:
            try:
                if int(addr) == 0:
                    return fallback
                t = _read_gba_cstring(int(addr), int(max_len)).strip()
                return t or fallback
            except Exception:
                return fallback

        page_blocks: Dict[int, List[Tuple[int, str]]] = {
            0: [
                (GCONTROLS_GUIDE_TEXT_INTRO_ADDR, "The controls guide."),
            ],
            1: [
                (GCONTROLS_GUIDE_TEXT_DPAD_ADDR, "D-PAD"),
                (GCONTROLS_GUIDE_TEXT_ABUTTON_ADDR, "A BUTTON"),
                (GCONTROLS_GUIDE_TEXT_BBUTTON_ADDR, "B BUTTON"),
            ],
            2: [
                (GCONTROLS_GUIDE_TEXT_STARTBUTTON_ADDR, "START BUTTON"),
                (GCONTROLS_GUIDE_TEXT_SELECTBUTTON_ADDR, "SELECT BUTTON"),
                (GCONTROLS_GUIDE_TEXT_LRBUTTONS_ADDR, "L/R BUTTONS"),
            ],
        }

        all_pages: List[str] = []
        for i in range(int(CONTROLS_GUIDE_NUM_PAGES)):
            entries = page_blocks.get(i, [])
            body_parts: List[str] = []
            for addr, fallback in entries:
                txt = _txt(int(addr), fallback)
                if txt:
                    body_parts.append(txt)
            all_pages.append("\n\n".join([p for p in body_parts if p]).strip())

        current_page = int(page_raw)
        body_text = all_pages[current_page] if 0 <= current_page < len(all_pages) else ""

        header_text = _txt(int(GTEXT_CONTROLS_ADDR), "CONTROLS", 64)
        if current_page == 0:
            controls_hint = _txt(int(GTEXT_ABUTTON_NEXT_ADDR), "A NEXT", 64)
        else:
            controls_hint = _txt(int(GTEXT_ABUTTON_NEXT_BBUTTON_BACK_ADDR), "A NEXT B BACK", 80)

        parts: List[str] = []
        if header_text:
            parts.append(header_text)
        if controls_hint:
            parts.append(controls_hint)
        if body_text:
            parts.append(body_text)
        visible_text = "\n\n".join(parts).strip()

        page_names = ["page1", "page2", "page3"]

        return {
            "type": "controlsGuide",
            "taskId": int(task_id),
            "isReady": True,
            "page": {
                "index": int(current_page),
                "number": int(current_page) + 1,
                "name": page_names[current_page] if 0 <= current_page < len(page_names) else f"page{current_page + 1}",
            },
            "pageCount": int(CONTROLS_GUIDE_NUM_PAGES),
            "allPages": all_pages,
            "header": header_text or None,
            "controlsHint": controls_hint or None,
            "visibleText": visible_text or None,
        }
    except Exception:
        return None


def get_pikachu_intro_state(
    tasks_raw: Optional[bytes] = None,
    *,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect and extract Oak Speech's Pikachu intro pages (oak_speech.c).

    This is the white text panel screen after the controls guide and before Oak's speech.
    """
    try:
        task_id = _find_active_task_by_funcs(_PIKACHU_INTRO_TASK_FUNCS, tasks_raw)
        if task_id is None:
            return None

        resources_ptr = int(mgba_read32(SOAK_SPEECH_RESOURCES_PTR_ADDR))
        if not (0x02000000 <= resources_ptr <= 0x0203FFFF):
            return None

        page_raw = int(mgba_read16(resources_ptr + OAK_SPEECH_CURRENT_PAGE_OFFSET))
        if page_raw < 0:
            return None

        page_idx = int(page_raw)
        if page_idx >= int(PIKACHU_INTRO_NUM_PAGES):
            page_idx = int(PIKACHU_INTRO_NUM_PAGES) - 1
        if page_idx < 0:
            page_idx = 0

        def _txt(addr: int, fallback: str, max_len: int = 512) -> str:
            try:
                if int(addr) == 0:
                    return fallback
                t = _read_gba_cstring(int(addr), int(max_len)).strip()
                return t or fallback
            except Exception:
                return fallback

        page_text_addrs = [
            int(GPIKACHU_INTRO_TEXT_PAGE1_ADDR),
            int(GPIKACHU_INTRO_TEXT_PAGE2_ADDR),
            int(GPIKACHU_INTRO_TEXT_PAGE3_ADDR),
        ]
        page_fallbacks = [
            "In the world which you are about to enter...",
            "There are also many places where people gather...",
            "Now, why don't you tell me a little about yourself?",
        ]

        all_pages: List[str] = []
        for i in range(min(int(PIKACHU_INTRO_NUM_PAGES), len(page_text_addrs))):
            all_pages.append(_txt(page_text_addrs[i], page_fallbacks[i]))

        body_text: Optional[str] = None
        textbox_window_id = int(
            mgba_read16(
                resources_ptr + OAK_SPEECH_WINDOW_IDS_OFFSET + (int(OAK_SPEECH_WIN_INTRO_TEXTBOX_INDEX) * 2)
            )
        )
        if 0 <= textbox_window_id < 32:
            body_text = get_textprinter_text_for_window(
                textbox_window_id,
                text_printers_raw=text_printers_raw,
                gstringvar4_raw=gstringvar4_raw,
                gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
                include_inactive=True,
            )
            if isinstance(body_text, str):
                body_text = body_text.strip() or None

        if not body_text and 0 <= page_idx < len(all_pages):
            body_text = all_pages[page_idx]

        controls_hint = (
            _txt(int(GTEXT_ABUTTON_NEXT_ADDR), "A NEXT", 64)
            if page_idx == 0
            else _txt(int(GTEXT_ABUTTON_NEXT_BBUTTON_BACK_ADDR), "A NEXT B BACK", 96)
        )

        parts: List[str] = []
        if controls_hint:
            parts.append(controls_hint)
        if body_text:
            parts.append(body_text)
        visible_text = "\n\n".join(parts).strip()

        page_names = ["page1", "page2", "page3"]

        return {
            "type": "pikachuIntro",
            "taskId": int(task_id),
            "isReady": True,
            "page": {
                "index": int(page_idx),
                "number": int(page_idx) + 1,
                "name": page_names[page_idx] if 0 <= page_idx < len(page_names) else f"page{page_idx + 1}",
            },
            "pageCount": int(PIKACHU_INTRO_NUM_PAGES),
            "allPages": all_pages,
            "controlsHint": controls_hint or None,
            "visibleText": visible_text or None,
        }
    except Exception:
        return None


def get_quest_log_playback_state(
    *,
    quest_log_state_raw: Optional[bytes] = None,
    quest_log_playback_state_raw: Optional[bytes] = None,
    quest_log_window_ids_raw: Optional[bytes] = None,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect and extract the Quest Log recap overlay ("Previously on your quest...").

    This overlay is not a standard dialog box; it uses quest_log.c private windows:
    - sWindowIds[WIN_TOP_BAR]
    - sWindowIds[WIN_DESCRIPTION]
    """
    try:
        if quest_log_state_raw is not None and len(quest_log_state_raw) >= 1:
            quest_log_state = int(quest_log_state_raw[0])
        else:
            quest_log_state = int(mgba_read8(GQUEST_LOG_STATE_ADDR))

        if quest_log_state not in (QL_STATE_PLAYBACK, QL_STATE_PLAYBACK_LAST):
            return None

        if quest_log_playback_state_raw is not None and len(quest_log_playback_state_raw) >= 1:
            playback_state = int(quest_log_playback_state_raw[0])
        else:
            playback_state = int(mgba_read8(GQUEST_LOG_PLAYBACK_STATE_ADDR))

        if quest_log_window_ids_raw is not None and len(quest_log_window_ids_raw) >= QUEST_LOG_WINDOW_COUNT:
            window_ids = bytes(quest_log_window_ids_raw[:QUEST_LOG_WINDOW_COUNT])
        else:
            window_ids = mgba_read_range_bytes(SQUEST_LOG_WINDOW_IDS_ADDR, QUEST_LOG_WINDOW_COUNT)
        if len(window_ids) < QUEST_LOG_WINDOW_COUNT:
            return None

        top_wid = int(window_ids[QUEST_LOG_WIN_TOP_BAR_INDEX])
        bottom_wid = int(window_ids[QUEST_LOG_WIN_BOTTOM_BAR_INDEX])
        desc_wid = int(window_ids[QUEST_LOG_WIN_DESCRIPTION_INDEX])

        def _window_text(window_id: int) -> Optional[str]:
            if window_id == WINDOW_NONE or not (0 <= int(window_id) < 32):
                return None
            txt = get_textprinter_text_for_window(
                int(window_id),
                text_printers_raw=text_printers_raw,
                gstringvar4_raw=gstringvar4_raw,
                gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
                include_inactive=True,
            )
            if isinstance(txt, str):
                txt = txt.strip()
                if txt:
                    return txt
            return None

        header_text = _window_text(top_wid)
        description_text = _window_text(desc_wid)

        if not description_text:
            if gstringvar4_raw is None:
                gstringvar4_raw = mgba_read_range_bytes(GSTRINGVAR4_ADDR, GSTRINGVAR4_SIZE)
            guess = decode_gba_string(gstringvar4_raw, 300, stop_at_prompt=True).strip() if gstringvar4_raw else ""
            if guess:
                description_text = guess

        if not header_text:
            header_guess = _read_gba_cstring(GTEXT_QUESTLOG_PREVIOUSLY_ON_YOUR_QUEST_ADDR, 96).strip()
            if header_guess:
                header_text = header_guess

        if not header_text and not description_text:
            return None

        visible_parts: List[str] = []
        if header_text:
            visible_parts.append(header_text)
        if description_text:
            visible_parts.append(description_text)
        visible_text = "\n\n".join(visible_parts).strip() or None

        return {
            "type": "questLogPlayback",
            "isReady": bool(visible_text),
            "questLogState": int(quest_log_state),
            "questLogStateName": _QUEST_LOG_STATE_NAMES.get(int(quest_log_state), f"STATE_{quest_log_state}"),
            "playbackState": int(playback_state),
            "playbackStateName": _QUEST_LOG_PLAYBACK_STATE_NAMES.get(
                int(playback_state), f"PLAYBACK_{playback_state}"
            ),
            "windowIds": {
                "topBar": int(top_wid),
                "bottomBar": int(bottom_wid),
                "description": int(desc_wid),
            },
            "headerText": header_text,
            "descriptionText": description_text,
            "visibleText": visible_text,
        }
    except Exception:
        return None


_NEW_GAME_BIRCH_SPEECH_TASK_ADDRS_MASKED: Optional[set[int]] = None


def _new_game_birch_speech_task_addrs_masked() -> set[int]:
    global _NEW_GAME_BIRCH_SPEECH_TASK_ADDRS_MASKED
    if _NEW_GAME_BIRCH_SPEECH_TASK_ADDRS_MASKED is None:
        addrs: List[int] = []
        # FireRed uses Task_NewGameBirchSpeech* while FireRed uses Task_OakSpeech*.
        addrs.extend(_sym_addrs_by_prefix("Task_NewGameBirchSpeech"))
        addrs.extend(_sym_addrs_by_prefix("Task_OakSpeech"))
        addrs.extend(_sym_addrs_by_prefix("Task_NewGameScene"))
        _NEW_GAME_BIRCH_SPEECH_TASK_ADDRS_MASKED = {int(addr) & 0xFFFFFFFE for addr in addrs if int(addr) != 0}
    return _NEW_GAME_BIRCH_SPEECH_TASK_ADDRS_MASKED


def _is_new_game_birch_speech_active(tasks_raw: Optional[bytes] = None) -> bool:
    """
    Return True if any Professor Birch "new game speech" task is active.

    These sequences run from `main_menu.c` and can show dialog text without setting
    `sLockFieldControls`, so we treat them as safe contexts to decode inactive window-0
    TextPrinter pointers (without reintroducing warp-transition false positives).
    """
    try:
        task_addrs = _new_game_birch_speech_task_addrs_masked()
        if not task_addrs:
            return False

        if tasks_raw is not None and len(tasks_raw) >= (NUM_TASKS * TASK_SIZE):
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if (base + TASK_SIZE) > len(tasks_raw):
                    break
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func in task_addrs:
                    return True
            return False

        for i in range(NUM_TASKS):
            task_addr = GTASKS_ADDR + (i * TASK_SIZE)
            if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                continue
            task_func = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
            if task_func in task_addrs:
                return True
        return False
    except Exception:
        return False


_NEW_GAME_BIRCH_GENDER_PROMPT_FALLBACK = "Are you a boy?\nOr are you a girl?"


_BERRY_CRUSH_RANKINGS_TASK_ADDR_MASKED: Optional[int] = None


def _berry_crush_rankings_task_addr_masked() -> int:
    global _BERRY_CRUSH_RANKINGS_TASK_ADDR_MASKED
    if _BERRY_CRUSH_RANKINGS_TASK_ADDR_MASKED is None:
        _BERRY_CRUSH_RANKINGS_TASK_ADDR_MASKED = int(TASK_BERRY_CRUSH_SHOW_RANKINGS_ADDR) & 0xFFFFFFFE
    return int(_BERRY_CRUSH_RANKINGS_TASK_ADDR_MASKED)


_BERRY_CRUSH_RANKINGS_PHASE_BY_STATE: Dict[int, str] = {
    0: "open",
    1: "render",
    2: "waitInput",
    3: "close",
}


_BERRY_CRUSH_PRESSING_SPEED_CONVERSION_TABLE = [
    50000000,  # 50.000000
    25000000,  # 25.000000
    12500000,  # 12.500000
    6250000,  # 6.250000
    3125000,  # 3.125000
    1562500,  # 1.562500
    781250,  # 0.781250
    390625,  # 0.390625
]


def _berry_crush_times_per_sec_from_packing(raw: int) -> str:
    """
    Convert Berry Crush pressing speed packed u16 into the "X.YY" string shown in-game.

    In pokefirered/src/berry_crush.c this is formatted by splitting the high byte as the
    integer part and converting the low byte bits into hundredths via sPressingSpeedConversionTable.
    """
    packed = int(raw) & 0xFFFF
    int_part = (packed >> 8) & 0xFF
    frac_bits = packed & 0xFF
    score = 0
    for j, val in enumerate(_BERRY_CRUSH_PRESSING_SPEED_CONVERSION_TABLE):
        if ((frac_bits >> (7 - j)) & 1) != 0:
            score += int(val)
    frac = int(score // 1_000_000)
    return f"{int_part}.{frac:02d}"


def get_berry_crush_rankings_state(tasks_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect the Berry Crush "Pressing-Speed Rankings" overlay window.

    This UI is task-driven (Task_ShowRankings) and renders into a dedicated window.
    It is not the standard dialog box (window 0).
    """
    try:
        target = _berry_crush_rankings_task_addr_masked()
        if target == 0:
            return None

        def _build_state(
            task_id: int,
            *,
            state: int,
            window_id: int,
            pressing_speeds_raw: List[int],
        ) -> Dict[str, Any]:
            st = int(state)
            wid = int(window_id) & 0xFF
            speeds = [_berry_crush_times_per_sec_from_packing(v) for v in pressing_speeds_raw]

            lines: List[str] = ["BERRY CRUSH", "Pressing-Speed Rankings", ""]
            for i, speed in enumerate(speeds):
                players = i + 2
                lines.append(f"{players} PLAYERS: {speed} Times/sec.")

            return {
                "type": "berryCrushRankings",
                "taskId": int(task_id),
                "state": st,
                "phase": _BERRY_CRUSH_RANKINGS_PHASE_BY_STATE.get(st, f"state{st}"),
                "windowId": wid,
                "pressingSpeedsRaw": [int(v) & 0xFFFF for v in pressing_speeds_raw],
                "rankings": [
                    {"players": i + 2, "timesPerSec": str(speeds[i])} for i in range(min(4, len(speeds)))
                ],
                "visibleText": "\n".join(lines).strip(),
            }

        if tasks_raw is not None and len(tasks_raw) >= (NUM_TASKS * TASK_SIZE):
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if (base + TASK_SIZE) > len(tasks_raw):
                    break
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func != target:
                    continue
                state = int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET))
                window_id = int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + (1 * 2)))
                pressing_raw = [
                    int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + (2 * 2))),
                    int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + (3 * 2))),
                    int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + (4 * 2))),
                    int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + (5 * 2))),
                ]
                if int(state) >= 3:
                    return None
                return _build_state(i, state=state, window_id=window_id, pressing_speeds_raw=pressing_raw)
            return None

        for i in range(NUM_TASKS):
            task_addr = GTASKS_ADDR + (i * TASK_SIZE)
            if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                continue
            task_func = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
            if task_func != target:
                continue
            state = int(mgba_read16(task_addr + TASK_DATA_OFFSET))
            window_id = int(mgba_read16(task_addr + TASK_DATA_OFFSET + (1 * 2)))
            pressing_raw = [
                int(mgba_read16(task_addr + TASK_DATA_OFFSET + (2 * 2))),
                int(mgba_read16(task_addr + TASK_DATA_OFFSET + (3 * 2))),
                int(mgba_read16(task_addr + TASK_DATA_OFFSET + (4 * 2))),
                int(mgba_read16(task_addr + TASK_DATA_OFFSET + (5 * 2))),
            ]
            if int(state) >= 3:
                return None
            return _build_state(i, state=state, window_id=window_id, pressing_speeds_raw=pressing_raw)

        return None
    except Exception:
        return None


def get_new_game_birch_gender_menu_state(
    tasks_raw: Optional[bytes] = None,
    *,
    smenu_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the new-game professor intro "BOY/GIRL" gender selection menu.

    Supports both FireRed (Birch task names) and FireRed (Oak task names),
    and uses `sMenu.cursorPos` for selection.
    """
    try:
        gender_task_addrs = {
            int(addr) & 0xFFFFFFFE
            for addr in (
                TASK_NEW_GAME_BIRCH_SPEECH_CHOOSE_GENDER_ADDR,
                TASK_NEW_GAME_BIRCH_SPEECH_SLIDE_OUT_OLD_GENDER_SPRITE_ADDR,
                TASK_NEW_GAME_BIRCH_SPEECH_SLIDE_IN_NEW_GENDER_SPRITE_ADDR,
            )
            if int(addr) != 0
        }
        if not gender_task_addrs:
            return None

        active = False
        if tasks_raw is not None and len(tasks_raw) >= (NUM_TASKS * TASK_SIZE):
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in gender_task_addrs:
                    active = True
                    break
        else:
            for i in range(NUM_TASKS):
                task_addr = GTASKS_ADDR + (i * TASK_SIZE)
                if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                    continue
                task_func_masked = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func_masked in gender_task_addrs:
                    active = True
                    break

        if not active:
            return None

        cursor_pos = _read_menu_cursor_pos(smenu_raw)

        boy = _read_gba_cstring(GTEXT_BIRCH_BOY_ADDR, 16) or "BOY"
        girl = _read_gba_cstring(GTEXT_BIRCH_GIRL_ADDR, 16) or "GIRL"
        options = [boy, girl]
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        prompt_text = ""
        if gstringvar4_raw is None:
            try:
                gstringvar4_raw = mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
            except Exception:
                gstringvar4_raw = None
        if gstringvar4_raw is not None:
            prompt_text = decode_gba_string(gstringvar4_raw, 200, stop_at_prompt=True)
        if not prompt_text:
            prompt_text = _NEW_GAME_BIRCH_GENDER_PROMPT_FALLBACK

        return {
            "type": "gender",
            "cursorPosition": cursor_pos,
            "selectedOption": selected,
            "options": options,
            "promptText": prompt_text,
        }
    except Exception:
        return None


SPRITE_SIZE = 0x44
SPRITE_DATA_OFFSET = 0x2E

# struct NamingScreenData offsets (pokefirered/src/naming_screen.c)
NAMING_SCREEN_TEXT_BUFFER_OFFSET = 0x1800  # u8 textBuffer[16]
NAMING_SCREEN_TEXT_BUFFER_SIZE = 16
NAMING_SCREEN_STATE_BLOCK_OFFSET = 0x1E10  # state + windows + subsequent fields
NAMING_SCREEN_STATE_BLOCK_SIZE = 0x40
NAMING_SCREEN_CURRENT_PAGE_REL = 0x12  # currentPage relative to NAMING_SCREEN_STATE_BLOCK_OFFSET
NAMING_SCREEN_CURSOR_SPRITE_ID_REL = 0x13  # cursorSpriteId relative to NAMING_SCREEN_STATE_BLOCK_OFFSET
NAMING_SCREEN_TEMPLATE_PTR_REL = 0x18  # template pointer relative to NAMING_SCREEN_STATE_BLOCK_OFFSET
NAMING_SCREEN_TEMPLATE_NUM_REL = 0x1C  # templateNum relative to NAMING_SCREEN_STATE_BLOCK_OFFSET
NAMING_SCREEN_DEST_BUFFER_PTR_REL = 0x20  # destBuffer pointer relative to NAMING_SCREEN_STATE_BLOCK_OFFSET
NAMING_SCREEN_MON_SPECIES_REL = 0x24  # monSpecies (u16) relative to NAMING_SCREEN_STATE_BLOCK_OFFSET
NAMING_SCREEN_MON_GENDER_REL = 0x26  # monGender (u16) relative to NAMING_SCREEN_STATE_BLOCK_OFFSET

# struct NamingScreenTemplate offsets (pokefirered/src/naming_screen.c)
NAMING_SCREEN_TEMPLATE_MAX_CHARS_OFFSET = 0x01
NAMING_SCREEN_TEMPLATE_TITLE_PTR_OFFSET = 0x08

# Naming screen page ids (pokefirered/src/naming_screen.c)
_KBPAGE_SYMBOLS = 0
_KBPAGE_LETTERS_UPPER = 1
_KBPAGE_LETTERS_LOWER = 2

# Keyboard ids (pokefirered/src/naming_screen.c)
_KEYBOARD_LETTERS_LOWER = 0
_KEYBOARD_LETTERS_UPPER = 1
_KEYBOARD_SYMBOLS = 2

_NAMING_SCREEN_PAGE_LABEL = {
    _KBPAGE_SYMBOLS: "OTHERS",
    _KBPAGE_LETTERS_UPPER: "UPPER",
    _KBPAGE_LETTERS_LOWER: "LOWER",
}
_NAMING_SCREEN_NEXT_PAGE_LABEL = {
    _KBPAGE_SYMBOLS: "UPPER",
    _KBPAGE_LETTERS_UPPER: "LOWER",
    _KBPAGE_LETTERS_LOWER: "OTHERS",
}
_NAMING_SCREEN_PAGE_TO_KEYBOARD_ID = {
    _KBPAGE_SYMBOLS: _KEYBOARD_SYMBOLS,
    _KBPAGE_LETTERS_UPPER: _KEYBOARD_LETTERS_UPPER,
    _KBPAGE_LETTERS_LOWER: _KEYBOARD_LETTERS_LOWER,
}
_NAMING_SCREEN_KEYBOARD_COLS = {
    _KEYBOARD_LETTERS_LOWER: 8,
    _KEYBOARD_LETTERS_UPPER: 8,
    _KEYBOARD_SYMBOLS: 6,
}
_NAMING_SCREEN_KEYBOARD_ROWS = {
    _KEYBOARD_LETTERS_LOWER: ["abcdef .", "ghijkl ,", "mnopqrs ", "tuvwxyz "],
    _KEYBOARD_LETTERS_UPPER: ["ABCDEF .", "GHIJKL ,", "MNOPQRS ", "TUVWXYZ "],
    _KEYBOARD_SYMBOLS: ["01234   ", "56789   ", "!?♂♀/-  ", "…“”‘'   "],
}


def _format_naming_screen_visible_text(state: Dict[str, Any]) -> str:
    title = str(state.get("title") or "").strip() or "YOUR NAME?"
    page = str(state.get("currentPage") or "").strip() or "UPPER"
    next_page = str(state.get("nextPage") or "").strip() or ""
    max_chars = int(state.get("maxChars") or 0)
    if max_chars <= 0 or max_chars > 16:
        max_chars = 7

    text = str(state.get("text") or "")
    slots: List[str] = []
    for i in range(max_chars):
        if i < len(text):
            ch = text[i]
            slots.append("␠" if ch == " " else ch)
        else:
            slots.append("_")
    name_line = "".join(slots)

    cursor = state.get("cursor") if isinstance(state.get("cursor"), dict) else {}
    cursor_x = int(cursor.get("x") or 0)
    cursor_y = int(cursor.get("y") or 0)
    cursor_area = str(cursor.get("area") or "")

    kb = state.get("keyboard") if isinstance(state.get("keyboard"), dict) else {}
    kb_rows = kb.get("rows") if isinstance(kb.get("rows"), list) else []
    kb_col_count = int(kb.get("colCount") or 0)

    lines: List[str] = ["MOVE OK BACK", title, name_line, "", f"Keyboard ({page}):"]

    if kb_rows and kb_col_count > 0:
        for row_idx, row in enumerate(kb_rows):
            if not isinstance(row, list):
                continue
            cells: List[str] = []
            for col_idx in range(min(kb_col_count, len(row))):
                key = row[col_idx]
                key_s = str(key) if isinstance(key, str) else ""
                key_disp = "␠" if key_s == " " else key_s
                prefix = "►" if (cursor_area == "keys" and row_idx == cursor_y and col_idx == cursor_x) else ""
                cells.append(f"{prefix}{key_disp}")
            lines.append(" ".join(cells))

    lines.append("")
    lines.append("Buttons:")
    btn_lines = [
        (0, f"{next_page or 'PAGE'} (SELECT)"),
        (1, "BACK (B)"),
        (2, "OK (START)"),
    ]
    for btn_y, label in btn_lines:
        prefix = "►" if (cursor_area == "buttons" and btn_y == cursor_y) else " "
        lines.append(f"{prefix}{label}")

    return "\n".join([ln for ln in lines if ln is not None])


def get_naming_screen_state(callback2: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Detect and extract the naming screen (keyboard) state.

    This screen is sprite/UI-driven; dialog text printers are not reliable, so we synthesize
    a human-readable `visibleText` including a "►" cursor marker.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        cb2_masked = int(callback2) & 0xFFFFFFFE

        phase: Optional[str] = None
        if cb2_masked == (CB2_LOAD_NAMING_SCREEN_ADDR & 0xFFFFFFFE):
            phase = "loading"
        elif cb2_masked == (CB2_NAMING_SCREEN_ADDR & 0xFFFFFFFE):
            phase = "active"
        else:
            return None

        ns_ptr = int(mgba_read32(SNAMING_SCREEN_PTR_ADDR))
        if ns_ptr == 0:
            return None

        text_buf = mgba_read_range_bytes(ns_ptr + NAMING_SCREEN_TEXT_BUFFER_OFFSET, NAMING_SCREEN_TEXT_BUFFER_SIZE)
        state_raw = mgba_read_range_bytes(ns_ptr + NAMING_SCREEN_STATE_BLOCK_OFFSET, NAMING_SCREEN_STATE_BLOCK_SIZE)

        template_num = int(_u8_from(state_raw, NAMING_SCREEN_TEMPLATE_NUM_REL))
        is_mon_naming = template_num in (2, 3)
        mon_species_id = int(_u16le_from(state_raw, NAMING_SCREEN_MON_SPECIES_REL)) if is_mon_naming else 0
        mon_gender = int(_u16le_from(state_raw, NAMING_SCREEN_MON_GENDER_REL)) if is_mon_naming else 0

        current_page_raw = int(_u8_from(state_raw, NAMING_SCREEN_CURRENT_PAGE_REL))
        current_page = current_page_raw if current_page_raw in _NAMING_SCREEN_PAGE_TO_KEYBOARD_ID else _KBPAGE_LETTERS_UPPER
        page_label = _NAMING_SCREEN_PAGE_LABEL.get(current_page, "UPPER")
        next_page_label = _NAMING_SCREEN_NEXT_PAGE_LABEL.get(current_page, "OTHERS")

        keyboard_id = _NAMING_SCREEN_PAGE_TO_KEYBOARD_ID.get(current_page, _KEYBOARD_LETTERS_UPPER)
        col_count = int(_NAMING_SCREEN_KEYBOARD_COLS.get(keyboard_id, 8))
        rows_s = _NAMING_SCREEN_KEYBOARD_ROWS.get(keyboard_id, [])
        rows: List[List[str]] = []
        for r in rows_s:
            if not isinstance(r, str):
                continue
            rows.append([ch for ch in r[:col_count]])

        cursor_sprite_id = int(_u8_from(state_raw, NAMING_SCREEN_CURSOR_SPRITE_ID_REL))
        cursor_x = 0
        cursor_y = 0
        if 0 <= cursor_sprite_id < 64:
            sprite_base = GSPRITES_ADDR + (cursor_sprite_id * SPRITE_SIZE) + SPRITE_DATA_OFFSET
            spr_raw = mgba_read_range_bytes(sprite_base, 4)
            cursor_x = _s16_from_u16(_u16le_from(spr_raw, 0))
            cursor_y = _s16_from_u16(_u16le_from(spr_raw, 2))

        cursor_area = "keys"
        selected: Optional[str] = None
        if cursor_x >= col_count:
            cursor_area = "buttons"
            selected = {0: "PAGE", 1: "BACK", 2: "OK"}.get(cursor_y)
        else:
            if 0 <= cursor_y < len(rows) and 0 <= cursor_x < col_count:
                selected = rows[cursor_y][cursor_x]

        template_ptr = int(_u32le_from(state_raw, NAMING_SCREEN_TEMPLATE_PTR_REL))
        max_chars = 7
        title = ""
        if template_ptr:
            tmpl_raw = mgba_read_range_bytes(template_ptr, 12)
            max_chars_val = int(_u8_from(tmpl_raw, NAMING_SCREEN_TEMPLATE_MAX_CHARS_OFFSET))
            if 0 < max_chars_val <= 16:
                max_chars = max_chars_val
            title_ptr = int(_u32le_from(tmpl_raw, NAMING_SCREEN_TEMPLATE_TITLE_PTR_OFFSET))
            if title_ptr:
                title_raw = mgba_read_range_bytes(title_ptr, 32)
                title = decode_gba_string(title_raw, 32)

        if not title:
            if template_num == 1:
                title = "BOX NAME?"
            elif template_num in (2, 3):
                title = "'s nickname?"
            else:
                title = "YOUR NAME?"

        mon_species_name = get_species_name(mon_species_id) if mon_species_id else None
        if is_mon_naming and mon_species_name:
            # naming_screen.c builds the displayed title by prepending gSpeciesNames[monSpecies]
            # then appending template->title (which starts with a {STR_VAR_1} control code).
            # Our decoder strips the control code, leaving "'s nickname?", so we reproduce the
            # game's visible result here.
            if not str(title).startswith(mon_species_name):
                title = f"{mon_species_name}{title}"

        text = decode_gba_string(text_buf, max_chars + 1)

        state: Dict[str, Any] = {
            "type": "namingScreen",
            "phase": phase,
            "templateNum": template_num,
            "title": title,
            "text": text,
            "maxChars": int(max_chars),
            "monSpeciesId": int(mon_species_id) if mon_species_id else None,
            "monSpecies": mon_species_name,
            "monGender": int(mon_gender) if mon_species_id else None,
            "currentPage": page_label,
            "nextPage": next_page_label,
            "cursor": {
                "x": int(cursor_x),
                "y": int(cursor_y),
                "area": cursor_area,
                "selected": selected,
            },
            "keyboard": {
                "colCount": int(col_count),
                "rows": rows,
            },
        }
        state["visibleText"] = _format_naming_screen_visible_text(state)
        return state
    except Exception:
        return None


def _s8_from_u8(val: int) -> int:
    return val - 256 if val > 127 else val


def _s16_from_u16(val: int) -> int:
    return val - 65536 if val > 32767 else val


def _read_menu_cursor_pos(smenu_raw: Optional[bytes] = None) -> int:
    if smenu_raw is None:
        return _s8_from_u8(mgba_read8(SMENU_ADDR + SMENU_CURSORPOS_OFFSET))
    return _s8_from_u8(_u8_from(smenu_raw, SMENU_CURSORPOS_OFFSET))


def _read_task_data_u16(task_id: int, data_index: int, tasks_raw: Optional[bytes] = None) -> int:
    if tasks_raw is not None:
        base = (int(task_id) * TASK_SIZE) + TASK_DATA_OFFSET + (int(data_index) * 2)
        return int(_u16le_from(tasks_raw, base))
    addr = GTASKS_ADDR + (int(task_id) * TASK_SIZE) + TASK_DATA_OFFSET + (int(data_index) * 2)
    return int(mgba_read16(addr))


def _find_active_task_by_func(func_addr: int, tasks_raw: Optional[bytes] = None) -> Optional[int]:
    """Return taskId for a given TaskFunc, or None if not active."""
    if int(func_addr) == 0:
        return None
    masked = func_addr & 0xFFFFFFFE
    if tasks_raw is not None:
        for i in range(NUM_TASKS):
            base = i * TASK_SIZE
            if (base + TASK_SIZE) > len(tasks_raw):
                break
            if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                continue
            task_func = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
            if task_func == masked:
                return i
        return None

    for i in range(NUM_TASKS):
        task_addr = GTASKS_ADDR + (i * TASK_SIZE)
        if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
            continue
        task_func = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
        if task_func == masked:
            return i
    return None


def _find_active_task_by_funcs(func_addrs: Sequence[int], tasks_raw: Optional[bytes] = None) -> Optional[int]:
    """
    Return the first taskId whose TaskFunc matches any of `func_addrs` (Thumb bit ignored).

    Some UI state machines swap gTasks[taskId].func between many handlers; for those cases we treat
    any of the known functions as equivalent evidence that the UI is active.
    """
    masked_set = {int(addr) & 0xFFFFFFFE for addr in func_addrs if int(addr) != 0}
    if not masked_set:
        return None

    if tasks_raw is not None:
        for i in range(NUM_TASKS):
            base = i * TASK_SIZE
            if (base + TASK_SIZE) > len(tasks_raw):
                break
            if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                continue
            task_func = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
            if task_func in masked_set:
                return i
        return None

    for i in range(NUM_TASKS):
        task_addr = GTASKS_ADDR + (i * TASK_SIZE)
        if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
            continue
        task_func = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
        if task_func in masked_set:
            return i
    return None


def _read_elevator_floor_name() -> Tuple[Optional[int], Optional[str]]:
    try:
        if int(GSPECIALVAR_0X8005_ADDR) == 0:
            return None, None
        floor_idx = int(mgba_read16(GSPECIALVAR_0X8005_ADDR))
        if floor_idx < 0:
            return None, None

        if int(SFLOOR_NAME_POINTERS_ADDR) == 0:
            return floor_idx, None

        table_bytes = int(SFLOOR_NAME_POINTERS_SIZE)
        table_count = (table_bytes // 4) if table_bytes > 0 else 0
        if table_count <= 0 or floor_idx >= table_count:
            return floor_idx, None

        ptr = int(mgba_read32(SFLOOR_NAME_POINTERS_ADDR + (floor_idx * 4)))
        if ptr == 0:
            return floor_idx, None
        floor_name = _read_gba_cstring(ptr, 32) or None
        return floor_idx, floor_name
    except Exception:
        return None, None


def _read_script_list_menu_options(
    list_task_id: int,
    *,
    tasks_raw: Optional[bytes] = None,
) -> Tuple[List[str], int, int]:
    options: List[str] = []
    scroll_offset = 0
    selected_row = 0

    try:
        tid = int(list_task_id)
        if tid < 0 or tid >= NUM_TASKS:
            return options, scroll_offset, selected_row

        if tasks_raw is not None:
            base = tid * TASK_SIZE
            if (base + TASK_SIZE) > len(tasks_raw):
                return options, scroll_offset, selected_row
            list_base = base + TASK_DATA_OFFSET
            items_ptr = int(_u32le_from(tasks_raw, list_base + _LISTMENU_TEMPLATE_ITEMS_PTR_OFFSET))
            total_items = int(_u16le_from(tasks_raw, list_base + _LISTMENU_TEMPLATE_TOTAL_ITEMS_OFFSET))
            scroll_offset = int(_u16le_from(tasks_raw, list_base + _LISTMENU_CURSOR_POS_OFFSET))
            selected_row = int(_u16le_from(tasks_raw, list_base + _LISTMENU_ITEMS_ABOVE_OFFSET))
        else:
            list_base = GTASKS_ADDR + (tid * TASK_SIZE) + TASK_DATA_OFFSET
            items_ptr = int(mgba_read32(list_base + _LISTMENU_TEMPLATE_ITEMS_PTR_OFFSET))
            total_items = int(mgba_read16(list_base + _LISTMENU_TEMPLATE_TOTAL_ITEMS_OFFSET))
            scroll_offset = int(mgba_read16(list_base + _LISTMENU_CURSOR_POS_OFFSET))
            selected_row = int(mgba_read16(list_base + _LISTMENU_ITEMS_ABOVE_OFFSET))

        if items_ptr == 0:
            return options, scroll_offset, selected_row

        if total_items <= 0:
            return options, scroll_offset, selected_row
        if total_items > 32:
            total_items = 32

        ptr_chunks = mgba_read_ranges_bytes([(items_ptr + (i * 8), 4) for i in range(total_items)])
        text_ptrs: List[int] = []
        for i in range(total_items):
            seg = ptr_chunks[i] if i < len(ptr_chunks) else b""
            if isinstance(seg, (bytes, bytearray)) and len(seg) >= 4:
                text_ptrs.append(int(_u32le_from(seg, 0)))
            else:
                text_ptrs.append(0)

        for i, text_ptr in enumerate(text_ptrs):
            if text_ptr == 0:
                options.append(f"CHOICE_{i}")
                continue
            txt = _read_gba_cstring(int(text_ptr), 64) or f"CHOICE_{i}"
            options.append(txt)
    except Exception:
        return [], 0, 0

    return options, int(scroll_offset), int(selected_row)


def get_elevator_menu_state(
    tasks_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
    *,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect elevator floor-select UIs and reconstruct a full readable state.

    Supports:
    - Silph Co elevator (script ListMenu: LISTMENU_SILPHCO_FLOORS)
    - Department Store / Rocket Hideout / Trainer Tower elevators (multichoice)
    """
    try:
        prompt_text = get_textprinter_text_for_window(
            0,
            text_printers_raw=text_printers_raw,
            gstringvar4_raw=gstringvar4_raw,
            gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
            include_inactive=True,
        )
        if not prompt_text:
            prompt_text = _read_gba_cstring(TEXT_WANT_WHICH_FLOOR_ADDR, 128) or "Which floor do you want?"

        now_on = _read_gba_cstring(GTEXT_NOW_ON_ADDR, 32) or "Now on:"
        floor_idx, floor_name = _read_elevator_floor_name()
        current_floor_line = f"{now_on} {floor_name}".strip() if floor_name else None

        # 1) Silph Co elevator uses Script ListMenu (Task_ListMenuHandleInput), not multichoice.
        list_menu_task_id = _find_active_task_by_funcs(_SCRIPT_LIST_MENU_TASK_FUNCS, tasks_raw)
        if list_menu_task_id is not None:
            list_menu_type = int(mgba_read16(GSPECIALVAR_0X8004_ADDR)) if int(GSPECIALVAR_0X8004_ADDR) else -1
            if list_menu_type == _LISTMENU_SILPHCO_FLOORS:
                list_task_id = _read_task_data_u16(
                    int(list_menu_task_id),
                    _SCRIPT_LIST_TASK_DATA_LIST_TASK_ID_INDEX,
                    tasks_raw,
                )
                options, scroll_offset, selected_row = _read_script_list_menu_options(
                    int(list_task_id),
                    tasks_raw=tasks_raw,
                )
                if options:
                    selected_index = int(scroll_offset) + int(selected_row)
                    if selected_index < 0:
                        selected_index = 0
                    if selected_index >= len(options):
                        selected_index = len(options) - 1
                    selected_option = options[selected_index] if 0 <= selected_index < len(options) else None

                    lines: List[str] = []
                    if prompt_text:
                        lines.append(prompt_text)
                    if current_floor_line:
                        if lines:
                            lines.append("")
                        lines.append(current_floor_line)
                    if options:
                        if lines:
                            lines.append("")
                        for i, opt in enumerate(options):
                            prefix = "►" if i == selected_index else " "
                            lines.append(f"{prefix}{opt}")

                    return {
                        "type": "elevatorMenu",
                        "mode": "listMenu",
                        "taskId": int(list_menu_task_id),
                        "listTaskId": int(list_task_id),
                        "listMenuType": int(list_menu_type),
                        "promptText": prompt_text,
                        "currentFloor": {
                            "index": int(floor_idx) if floor_idx is not None else None,
                            "name": floor_name,
                            "text": current_floor_line,
                        },
                        "cursorPosition": int(selected_index),
                        "scrollOffset": int(scroll_offset),
                        "selectedRow": int(selected_row),
                        "selectedOption": selected_option,
                        "options": options,
                        "visibleText": "\n".join(lines).strip(),
                    }

        # 2) Other elevators use multichoice menus. Gate on known elevator multichoice IDs.
        multi_task_id = _find_active_task_by_func(TASK_HANDLE_MULTICHOICE_INPUT_ADDR, tasks_raw)
        if multi_task_id is None:
            return None

        mc_id = _s16_from_u16(_read_task_data_u16(int(multi_task_id), 7, tasks_raw))
        if int(mc_id) not in _ELEVATOR_MULTICHOICE_IDS:
            return None

        multichoice = get_multichoice_menu_state(
            tasks_raw,
            smenu_raw,
            gstringvar4_raw=gstringvar4_raw,
        )
        if not multichoice:
            return None

        options = [str(opt) for opt in (multichoice.get("options") or [])]
        cursor_pos = int(multichoice.get("cursorPosition", 0) or 0)
        if cursor_pos < 0:
            cursor_pos = 0
        if options and cursor_pos >= len(options):
            cursor_pos = len(options) - 1
        selected_option = options[cursor_pos] if 0 <= cursor_pos < len(options) else None

        lines: List[str] = []
        if prompt_text:
            lines.append(prompt_text)
        if current_floor_line:
            if lines:
                lines.append("")
            lines.append(current_floor_line)
        if options:
            if lines:
                lines.append("")
            for i, opt in enumerate(options):
                prefix = "►" if i == cursor_pos else " "
                lines.append(f"{prefix}{opt}")

        return {
            "type": "elevatorMenu",
            "mode": "multichoice",
            "taskId": int(multi_task_id),
            "multichoiceId": int(mc_id),
            "promptText": prompt_text,
            "currentFloor": {
                "index": int(floor_idx) if floor_idx is not None else None,
                "name": floor_name,
                "text": current_floor_line,
            },
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected_option,
            "options": options,
            "visibleText": "\n".join(lines).strip(),
        }
    except Exception:
        return None


def _find_bag_list_menu_scroll_and_row(tasks_raw: Optional[bytes] = None) -> Optional[Tuple[int, int]]:
    """
    Find the active ListMenu task used by the Bag item list and return (scrollOffset, selectedRow).

    Bag list selection is stored in the ListMenu task (ListMenuDummyTask), not reliably in gBagMenuState.
    """
    try:
        dummy_masked = LIST_MENU_DUMMY_TASK_ADDR & 0xFFFFFFFE
        move_masked = BAGMENU_MOVE_CURSOR_CALLBACK_ADDR & 0xFFFFFFFE
        print_masked = BAGMENU_ITEM_PRINT_CALLBACK_ADDR & 0xFFFFFFFE
        if tasks_raw is not None:
            for i in range(NUM_TASKS):
                base = i * TASK_SIZE
                if (base + TASK_SIZE) > len(tasks_raw):
                    break
                if _u8_from(tasks_raw, base + TASK_ISACTIVE_OFFSET) == 0:
                    continue

                task_func = _u32le_from(tasks_raw, base + TASK_FUNC_OFFSET) & 0xFFFFFFFE
                if task_func != dummy_masked:
                    continue

                move_cb = (
                    _u32le_from(tasks_raw, base + TASK_DATA_OFFSET + LISTMENU_TEMPLATE_MOVECURSORFUNC_OFFSET)
                    & 0xFFFFFFFE
                )
                item_cb = (
                    _u32le_from(tasks_raw, base + TASK_DATA_OFFSET + LISTMENU_TEMPLATE_ITEMPRINTFUNC_OFFSET)
                    & 0xFFFFFFFE
                )
                window_id = _u8_from(tasks_raw, base + TASK_DATA_OFFSET + LISTMENU_TEMPLATE_WINDOWID_OFFSET)

                # WIN_ITEM_LIST is 0 in pokefirered/src/item_menu.c
                if move_cb != move_masked or item_cb != print_masked or window_id != 0:
                    continue

                scroll = int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + LISTMENU_SCROLL_OFFSET))
                row = int(_u16le_from(tasks_raw, base + TASK_DATA_OFFSET + LISTMENU_SELECTED_ROW_OFFSET))
                return scroll, row
            return None

        for i in range(NUM_TASKS):
            task_addr = GTASKS_ADDR + (i * TASK_SIZE)
            if mgba_read8(task_addr + TASK_ISACTIVE_OFFSET) == 0:
                continue

            task_func = mgba_read32(task_addr + TASK_FUNC_OFFSET) & 0xFFFFFFFE
            if task_func != dummy_masked:
                continue

            move_cb = mgba_read32(task_addr + TASK_DATA_OFFSET + LISTMENU_TEMPLATE_MOVECURSORFUNC_OFFSET) & 0xFFFFFFFE
            item_cb = mgba_read32(task_addr + TASK_DATA_OFFSET + LISTMENU_TEMPLATE_ITEMPRINTFUNC_OFFSET) & 0xFFFFFFFE
            window_id = mgba_read8(task_addr + TASK_DATA_OFFSET + LISTMENU_TEMPLATE_WINDOWID_OFFSET)

            if move_cb != move_masked or item_cb != print_masked or window_id != 0:
                continue

            scroll = int(mgba_read16(task_addr + TASK_DATA_OFFSET + LISTMENU_SCROLL_OFFSET))
            row = int(mgba_read16(task_addr + TASK_DATA_OFFSET + LISTMENU_SELECTED_ROW_OFFSET))
            return scroll, row

        return None
    except Exception:
        return None


def _read_gba_cstring(ptr: int, max_len: int = 64) -> str:
    """Read a ROM/EWRAM/IWRAM encoded GBA string until 0xFF (or max_len)."""
    if ptr == 0:
        return ""
    try:
        raw = mgba_read_range_bytes(ptr, max_len)
        return decode_gba_string(raw, max_len)
    except Exception:
        return ""


def get_bag_context_menu_state(
    bag_menu_ptr: int,
    *,
    smenu_raw: Optional[bytes] = None,
    num_items: Optional[int] = None,
    items_ptr: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the bag item context menu (USE / GIVE / TOSS / CANCEL, etc.) and extract its options.

    The menu text comes from sItemMenuActions[actionId].text, and selection is tracked in sMenu.cursorPos.
    """
    try:
        if bag_menu_ptr == 0:
            return None

        # Context menu windows are ITEMWIN_1x1..ITEMWIN_2x3 (0..3) stored in gBagMenu->windowIds[].
        # When callers already know it's open they can pass num_items/items_ptr to avoid these reads.
        if num_items is None or items_ptr is None:
            win = mgba_read_range_bytes(bag_menu_ptr + BAGMENU_WINDOW_IDS_OFFSET, 4)
            if not win or all(int(b) == WINDOW_NONE for b in win[:4]):
                return None
            num_items = int(mgba_read8(bag_menu_ptr + BAGMENU_CONTEXT_MENU_NUM_ITEMS_OFFSET))
            items_ptr = int(mgba_read32(bag_menu_ptr + BAGMENU_CONTEXT_MENU_ITEMS_PTR_OFFSET))

        num_items_i = int(num_items)
        items_ptr_i = int(items_ptr)
        if num_items_i <= 0 or num_items_i > 12 or items_ptr_i == 0:
            return None

        raw_action_ids = mgba_read_range_bytes(items_ptr_i, num_items_i)
        action_ids = [int(b) & 0xFF for b in raw_action_ids[:num_items_i]] if raw_action_ids else []
        if not action_ids:
            return None

        # Resolve action labels from ROM, but cache them (ROM tables are static).
        cells: List[str] = []
        options: List[str] = []
        src_to_display: Dict[int, int] = {}

        uncached: List[int] = []
        for action_id in action_ids:
            if int(action_id) not in _ITEM_MENU_ACTION_LABEL_CACHE:
                uncached.append(int(action_id))

        if uncached:
            uniq = sorted(set(int(a) & 0xFF for a in uncached))
            ranges = [(SITEM_MENU_ACTIONS_ADDR + (aid * 8), 4) for aid in uniq]
            ptr_chunks = mgba_read_ranges_bytes(ranges)
            ptr_by_action: Dict[int, int] = {}
            for aid, chunk in zip(uniq, ptr_chunks):
                if isinstance(chunk, (bytes, bytearray)) and len(chunk) >= 4:
                    ptr_by_action[aid] = int(_u32le_from(chunk, 0))
            for aid in uniq:
                ptr = int(ptr_by_action.get(aid, 0))
                label = _read_gba_cstring(ptr, 32) if ptr else ""
                _ITEM_MENU_ACTION_LABEL_CACHE[aid] = label or ""

        for src_idx, action_id in enumerate(action_ids):
            label = _ITEM_MENU_ACTION_LABEL_CACHE.get(int(action_id), "") or ""
            cells.append(label)
            if label:
                src_to_display[src_idx] = len(options)
                options.append(label)

        cursor_src = _read_menu_cursor_pos(smenu_raw)
        cursor_src_int = int(cursor_src)
        if cursor_src_int < 0:
            cursor_src_int = 0
        if cursor_src_int >= num_items_i:
            cursor_src_int = num_items_i - 1

        cursor_display = src_to_display.get(cursor_src_int, 0)
        if cursor_display < 0 or cursor_display >= len(options):
            cursor_display = 0

        selected = options[cursor_display] if options else None

        return {
            "type": "bagContextMenu",
            # FireRed bag context menu is rendered as a vertical list.
            "layout": "list",
            "columns": 1,
            "rows": int(len(options)),
            "cursorPosition": int(cursor_display),
            "cursorPositionRaw": int(cursor_src_int),
            "selectedOption": selected,
            "options": options,
            "cells": cells,
            "actionIds": [int(a) for a in action_ids],
        }
    except Exception:
        return None


def _read_item_name_from_gitems(item_id: int) -> str:
    if item_id < 0 or item_id > 2048:
        item_id = 0
    base = GITEMS_ADDR + (int(item_id) * ITEM_STRUCT_SIZE)
    try:
        raw = mgba_read_range(base, ITEM_NAME_LENGTH)
        return decode_gba_string(raw, ITEM_NAME_LENGTH)
    except Exception:
        return ""


def _read_item_price_from_gitems(item_id: int) -> int:
    if item_id < 0 or item_id > 2048:
        item_id = 0
    base = GITEMS_ADDR + (int(item_id) * ITEM_STRUCT_SIZE)
    try:
        return int(mgba_read16(base + ITEM_PRICE_OFFSET))
    except Exception:
        return 0


def _read_item_description_from_gitems(item_id: int, max_len: int = 200) -> str:
    if item_id < 0 or item_id > 2048:
        item_id = 0
    cached = _ITEM_DESCRIPTION_CACHE.get(int(item_id))
    if cached is not None:
        return cached
    base = GITEMS_ADDR + (int(item_id) * ITEM_STRUCT_SIZE)
    try:
        ptr = mgba_read32(base + ITEM_DESCRIPTION_PTR_OFFSET)
        desc = _read_gba_cstring(ptr, max_len)
        _ITEM_DESCRIPTION_CACHE[int(item_id)] = desc or ""
        return desc
    except Exception:
        _ITEM_DESCRIPTION_CACHE[int(item_id)] = ""
        return ""


def _read_shop_cancel_text() -> str:
    return _read_gba_cstring(GTEXT_CANCEL2_ADDR, 32) or "CANCEL"


def _read_shop_quit_shopping_text() -> str:
    return _read_gba_cstring(GTEXT_QUIT_SHOPPING_ADDR, 128) or "Quit shopping."


def get_shop_choice_menu_state(tasks_raw: Optional[bytes] = None, smenu_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect the Poké Mart "BUY/SELL/QUIT" (or "BUY/QUIT") menu.

    IMPORTANT:
    - This menu prints strings directly from ROM (menuActions[i].text),
      so it will NOT show up in gStringVar4 text extraction.
    - FireRed stores runtime shop state in `sShopData`.
    """
    try:
        task_id = _find_active_task_by_func(TASK_SHOP_MENU_ADDR, tasks_raw)
        if task_id is None:
            return None

        mart_type_raw = int(mgba_read16(SMARTINFO_ADDR + SMARTINFO_MARTTYPE_OFFSET))
        mart_type = int(mart_type_raw & SMARTINFO_MARTTYPE_MASK)
        # FireRed uses BUY/SELL/QUIT only for regular marts (martType 0).
        count = 3 if mart_type == 0 else 2
        menu_actions_ptr = (
            int(SHOP_MENU_ACTIONS_BUY_SELL_QUIT_ADDR)
            if count == 3
            else int(SHOP_MENU_ACTIONS_BUY_QUIT_ADDR)
        )

        if count <= 0 or count > 6:
            return None

        options: List[str] = []
        for i in range(count):
            if menu_actions_ptr != 0:
                text_ptr = mgba_read32(menu_actions_ptr + (i * 8))
                txt = _read_gba_cstring(text_ptr, 32) or f"OPTION_{i}"
            else:
                txt = ["BUY", "SELL", "QUIT"][i] if count == 3 else ["BUY", "QUIT"][i]
            options.append(txt)

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        return {
            "type": "shop",
            "taskId": task_id,
            "windowId": None,
            "martType": int(mart_type),
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
        }
    except Exception:
        return None


def get_shop_buy_menu_state(callback2: Optional[int] = None, tasks_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect the Poké Mart "Buy Menu" item list screen (money + items + description).

    This UI is driven by CB2_BuyMenu and Task_BuyMenu, and the visible list selection is stored
    on sShopData (scrollOffset/selectedRow/itemsShowed).
    """
    try:
        def _task_data_u16(task_id: int, idx: int) -> int:
            if tasks_raw is not None:
                base = (int(task_id) * TASK_SIZE) + TASK_DATA_OFFSET + (int(idx) * 2)
                return int(_u16le_from(tasks_raw, base))
            addr = GTASKS_ADDR + (int(task_id) * TASK_SIZE) + TASK_DATA_OFFSET + (int(idx) * 2)
            return int(mgba_read16(addr))

        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        if (int(callback2) & 0xFFFFFFFE) != (CB2_BUY_MENU_ADDR & 0xFFFFFFFE):
            return None

        task_id: Optional[int] = None
        matched_task_func: Optional[int] = None
        mode = "itemList"
        for func_addr, label in (
            (TASK_BUY_HOW_MANY_DIALOGUE_HANDLE_INPUT_ADDR, "howMany"),
            (TASK_BUY_HOW_MANY_DIALOGUE_INIT_ADDR, "howMany"),
            (TASK_RETURN_TO_ITEM_LIST_AFTER_ITEM_PURCHASE_ADDR, "postPurchase"),
            (TASK_BUY_MENU_ADDR, "itemList"),
        ):
            if int(func_addr) == 0:
                continue
            tid = _find_active_task_by_func(func_addr, tasks_raw)
            if tid is not None:
                task_id = int(tid)
                matched_task_func = int(func_addr)
                mode = str(label)
                break
        if task_id is None:
            return None

        # FireRed: `sShopData` is a struct in EWRAM (not a pointer to another blob).
        shop_data_ptr = int(SSHOPDATA_PTR_ADDR)
        if shop_data_ptr == 0:
            return None

        total_cost = int(mgba_read32(shop_data_ptr + SHOPDATA_TOTAL_COST_OFFSET))
        items_showed = int(mgba_read16(shop_data_ptr + SHOPDATA_ITEMS_SHOWED_OFFSET))
        selected_row = int(mgba_read16(shop_data_ptr + SHOPDATA_SELECTED_ROW_OFFSET))
        scroll_offset = int(mgba_read16(shop_data_ptr + SHOPDATA_SCROLL_OFFSET_OFFSET))

        if items_showed <= 0 or items_showed > 20:
            items_showed = 8

        item_list_ptr = int(mgba_read32(shop_data_ptr + SMARTINFO_ITEMLIST_PTR_OFFSET))
        shop_item_count = int(mgba_read16(shop_data_ptr + SMARTINFO_ITEMCOUNT_OFFSET))
        mart_type = int(mgba_read16(shop_data_ptr + SMARTINFO_MARTTYPE_OFFSET)) & int(SMARTINFO_MARTTYPE_MASK)

        total_entries = shop_item_count + 1  # + CANCEL
        if total_entries <= 0 or total_entries > 1024:
            return None

        selected_index = scroll_offset + selected_row
        if selected_index < 0:
            selected_index = 0
        if selected_index >= total_entries:
            selected_index = total_entries - 1

        start = max(0, scroll_offset)
        end = min(total_entries, start + items_showed)

        entries: List[Dict[str, Any]] = []
        options: List[str] = []

        for idx in range(start, end):
            is_cancel = idx == shop_item_count
            entry: Dict[str, Any] = {"index": int(idx), "isCancel": bool(is_cancel)}
            if is_cancel:
                name = _read_shop_cancel_text()
                entry.update({"id": None, "name": name, "price": None})
                label = name
            else:
                if item_list_ptr == 0:
                    return None
                entry_id = int(mgba_read16(item_list_ptr + (idx * 2)))
                entry["id"] = entry_id
                if mart_type == 0:
                    name = _read_item_name_from_gitems(entry_id) or f"ITEM_{entry_id}"
                    price = _read_item_price_from_gitems(entry_id)
                    entry.update({"name": name, "price": int(price)})
                    label = f"{name} ₽{price}"
                else:
                    # Decorations/etc. not yet decoded from ROM tables; provide a safe fallback.
                    name = f"ITEM_{entry_id}"
                    entry.update({"name": name, "price": None})
                    label = name

            entries.append(entry)
            options.append(label)

        # Selected item description
        selected_description = ""
        selected_entry: Optional[Dict[str, Any]] = None
        if start <= selected_index < end:
            selected_entry = entries[selected_index - start]
        if selected_entry is not None:
            if selected_entry.get("isCancel"):
                selected_description = _read_shop_quit_shopping_text()
            else:
                item_id = int(selected_entry.get("id") or 0)
                selected_description = _read_item_description_from_gitems(item_id, 200)

        money = int(get_player_money())

        message_text: Optional[str] = None
        quantity_in_bag: Optional[int] = None
        selected_quantity: Optional[int] = None
        selected_item_id: Optional[int] = None
        selected_item_name: Optional[str] = None

        if mode == "howMany":
            selected_item_id = int(_task_data_u16(task_id, 5))  # tItemId
            selected_quantity = int(_s16_from_u16(_task_data_u16(task_id, 1)))  # tItemCount
            if selected_quantity <= 0:
                selected_quantity = 1

            selected_item_name = _read_item_name_from_gitems(selected_item_id) or f"ITEM_{selected_item_id}"
            message_text = f"{selected_item_name}? Certainly.\nHow many would you like?"
            try:
                quantity_in_bag = int(player_bag.count_total_item_quantity_in_bag(selected_item_id))
            except Exception:
                quantity_in_bag = None

        if mode == "postPurchase":
            if matched_task_func == int(TASK_RETURN_TO_ITEM_LIST_AFTER_ITEM_PURCHASE_ADDR):
                message_text = _read_gba_cstring(GTEXT_HERE_YOU_GO_THANK_YOU_ADDR, 200) or None
            else:
                message_text = None

        # Build a human-friendly visibleText similar to what is shown on screen.
        lines: List[str] = []
        if mode == "howMany" and message_text:
            lines.append(message_text)
            lines.append("")
            if quantity_in_bag is not None:
                lines.append(f"IN BAG: {quantity_in_bag}")
            if selected_quantity is not None:
                lines.append(f"x{selected_quantity:02d} ₽{total_cost}")
        elif mode == "postPurchase" and message_text:
            lines.append(message_text)
        else:
            lines.append(f"MONEY ₽{money}")
            for i, opt in enumerate(options):
                abs_idx = start + i
                prefix = "►" if abs_idx == selected_index else " "
                lines.append(f"{prefix}{opt}")
            if selected_description:
                lines.append("")
                lines.append(selected_description)

        return {
            "type": "shopBuyMenu",
            "taskId": int(task_id),
            "mode": mode,
            "martType": int(mart_type),
            "money": money,
            "totalCost": int(total_cost),
            "selectedItemId": selected_item_id,
            "selectedQuantity": selected_quantity,
            "quantityInBag": quantity_in_bag,
            "messageText": message_text,
            "itemCount": int(shop_item_count),
            "itemsShowed": int(items_showed),
            "scrollOffset": int(scroll_offset),
            "selectedRow": int(selected_row),
            "cursorPosition": int(selected_index),
            "selectedIndex": int(selected_index),
            "entries": entries,
            "options": options,
            "description": selected_description,
            "visibleText": "\n".join(lines),
        }
    except Exception:
        return None


def get_party_action_menu_state(
    *,
    internal_ptr: Optional[int] = None,
    internal_ptr_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the action menu shown after selecting a party Pokémon (e.g. SUMMARY / SWITCH / ITEM / CANCEL).

    This menu is built from sPartyMenuInternal->actions[] and rendered via Menu helpers,
    so the cursor position is stored in sMenu.cursorPos.
    """
    try:
        if internal_ptr is None:
            if internal_ptr_raw is not None:
                internal_ptr = int(_u32le_from(internal_ptr_raw, 0))
            else:
                internal_ptr = mgba_read32(SPARTY_MENU_INTERNAL_PTR_ADDR)
        if internal_ptr == 0:
            return None

        # Read windowId[0], actions[8], and numActions in one call.
        internal = mgba_read_range_bytes(internal_ptr + PARTY_MENU_INTERNAL_WINDOWIDS_OFFSET, 0x0C)
        window_id = int(_u8_from(internal, 0))
        if window_id == WINDOW_NONE:
            return None

        rel_num_actions = int(PARTY_MENU_INTERNAL_NUMACTIONS_OFFSET - PARTY_MENU_INTERNAL_WINDOWIDS_OFFSET)
        num_actions = int(_u8_from(internal, rel_num_actions))
        if num_actions <= 0 or num_actions > 8:
            return None

        rel_actions = int(PARTY_MENU_INTERNAL_ACTIONS_OFFSET - PARTY_MENU_INTERNAL_WINDOWIDS_OFFSET)
        action_ids = [int(_u8_from(internal, rel_actions + i)) for i in range(num_actions)]

        # sCursorOptions entry layout: { const u8 *text; void (*func)(u8 taskId); }
        ptr_ranges = [(SCURSOR_OPTIONS_ADDR + (action_id * 8), 4) for action_id in action_ids]
        ptr_segs = mgba_read_ranges_bytes(ptr_ranges)

        options: List[str] = []
        for action_id, seg in zip(action_ids, ptr_segs):
            cached = _PARTY_MENU_ACTION_LABEL_CACHE.get(int(action_id))
            if cached:
                options.append(cached)
                continue

            text_ptr = int(_u32le_from(seg, 0))
            txt = _read_gba_cstring(text_ptr, 64) or f"ACTION_{action_id}"
            if txt and not txt.startswith("ACTION_"):
                _PARTY_MENU_ACTION_LABEL_CACHE[int(action_id)] = str(txt)
            options.append(txt)

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        return {
            "type": "partyActionMenu",
            "windowId": int(window_id),
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
            "actionIds": action_ids,
        }
    except Exception:
        return None


def get_party_menu_state(
    callback2: Optional[int] = None,
    *,
    party_menu_raw: Optional[bytes] = None,
    party_count_raw: Optional[bytes] = None,
    party_internal_ptr_raw: Optional[bytes] = None,
    party_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the Party Menu (START -> POKéMON) and extract a readable list of party members.

    Example visibleText:
        ►SALAMENCE Lv50 HP 166/166
         MAGCARGO Lv38 HP 95/95
         ...
         CANCEL

    If the per-Pokémon action menu is open (after pressing A), its options are appended like other choice menus.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        callback2 = int(callback2) & 0xFFFFFFFE
        if callback2 not in (
            CB2_INIT_PARTY_MENU_ADDR & 0xFFFFFFFE,
            CB2_UPDATE_PARTY_MENU_ADDR & 0xFFFFFFFE,
        ):
            return None

        if party_menu_raw is not None:
            slot_id_raw = int(_u8_from(party_menu_raw, GPARTY_MENU_SLOTID_OFFSET))
        else:
            slot_id_raw = int(mgba_read8(GPARTY_MENU_ADDR + GPARTY_MENU_SLOTID_OFFSET))
        slot_id = _s8_from_u8(slot_id_raw)

        if party_count_raw is not None:
            party_count = int(_u8_from(party_count_raw, 0))
        else:
            party_count = int(mgba_read8(GPLAYER_PARTY_COUNT_ADDR))
        if party_count < 0 or party_count > PARTY_SIZE:
            party_count = PARTY_SIZE

        # Cancel/Confirm buttons (Confirm only exists for choose-half scenarios)
        choose_half = False
        message_id = -1
        if party_internal_ptr_raw is not None:
            internal_ptr = int(_u32le_from(party_internal_ptr_raw, 0))
        else:
            internal_ptr = mgba_read32(SPARTY_MENU_INTERNAL_PTR_ADDR)
        if internal_ptr != 0:
            flags = mgba_read32(internal_ptr + PARTY_MENU_INTERNAL_FLAGS_OFFSET)
            choose_half = (flags & 0x1) != 0
            message_id = _party_menu_message_id_from_flags(int(flags))

        teach_tmhm = False
        teach_move_id: Optional[int] = None
        teach_tm_index: Optional[int] = None
        if message_id == _PARTY_MSG_TEACH_WHICH_MON:
            try:
                item_id = int(mgba_read16(GSPECIALVAR_ITEMID_ADDR))
                teach_tm_index = _get_tmhm_index(item_id)
                if teach_tm_index is not None:
                    teach_move_id = int(mgba_read16(STMHM_MOVES_ADDR + (teach_tm_index * 2)))
                    if teach_move_id:
                        teach_tmhm = True
            except Exception:
                teach_tmhm = False

        mons: List[Dict[str, Any]] = []
        lines: List[str] = []

        raw_party = party_raw
        if raw_party is None:
            raw_party = mgba_read_range_bytes(PARTY_BASE_ADDR, PARTY_SIZE * POKEMON_DATA_SIZE)

        if teach_tmhm and teach_move_id is not None and teach_tm_index is not None:
            infos: List[Dict[str, Any]] = []
            for i in range(party_count):
                info = _decode_party_mon_teach_info(raw_party, i)
                if info is None:
                    infos = []
                    break
                infos.append(info)

            learnset_word_index = int(teach_tm_index // 32)
            learn_bit = int(teach_tm_index % 32)

            learn_words: Dict[int, int] = {}
            uniq_species = sorted(
                {
                    int(info.get("speciesId") or 0)
                    for info in infos
                    if not bool(info.get("isEgg")) and int(info.get("speciesId") or 0) != SPECIES_NONE
                }
            )
            if uniq_species:
                ranges = [(GTMHM_LEARNSETS_ADDR + (sid * 8) + (learnset_word_index * 4), 4) for sid in uniq_species]
                raw_words = mgba_read_ranges_bytes(ranges)
                for sid, seg in zip(uniq_species, raw_words):
                    learn_words[int(sid)] = int(_u32le_from(seg, 0))

            for info in infos:
                nickname = str(info.get("nickname") or "")
                level = int(info.get("level") or 0)
                current_hp = int(info.get("currentHP") or 0)
                max_hp = int(info.get("maxHP") or 0)
                species_id = int(info.get("speciesId") or 0)
                moves = info.get("moves") if isinstance(info.get("moves"), list) else []
                moves_int = [int(m) for m in moves[:4]]

                status_text = "NOT ABLE!"
                status_key = "NOT_ABLE"
                if bool(info.get("isEgg")):
                    status_text = "NOT ABLE!"
                    status_key = "NOT_ABLE"
                elif int(teach_move_id) in moves_int:
                    status_text = "LEARNED"
                    status_key = "LEARNED"
                else:
                    word = int(learn_words.get(species_id, 0))
                    can_learn = (word & (1 << learn_bit)) != 0
                    if can_learn:
                        status_text = "ABLE!"
                        status_key = "ABLE"
                    else:
                        status_text = "NOT ABLE!"
                        status_key = "NOT_ABLE"

                mons.append(
                    {
                        "slot": int(info.get("slot") or 0),
                        "nickname": nickname,
                        "level": level,
                        "currentHP": current_hp,
                        "maxHP": max_hp,
                        "teachStatus": status_key,
                        "teachStatusText": status_text,
                    }
                )

                prefix = "►" if slot_id == int(info.get("slot") or 0) else ""
                lines.append(f"{prefix}{nickname} Lv{level} {status_text}")
        else:
            for i in range(party_count):
                base = int(i) * int(POKEMON_DATA_SIZE)
                if base < 0 or (base + POKEMON_DATA_SIZE) > len(raw_party):
                    break

                nickname_raw = raw_party[base + NICKNAME_OFFSET : base + NICKNAME_OFFSET + 10]
                nickname = decode_gba_string(nickname_raw, 10) or f"MON_{i}"

                level = int(_u8_from(raw_party, base + LEVEL_OFFSET))
                current_hp = int(_u16le_from(raw_party, base + CURRENT_HP_OFFSET))
                max_hp = int(_u16le_from(raw_party, base + MAX_HP_OFFSET))

                mons.append(
                    {
                        "slot": int(i),
                        "nickname": nickname,
                        "level": level,
                        "currentHP": current_hp,
                        "maxHP": max_hp,
                    }
                )

                prefix = "►" if slot_id == i else ""
                lines.append(f"{prefix}{nickname} Lv{level} HP {current_hp}/{max_hp}")

        if choose_half:
            prefix = "►" if slot_id == PARTY_SIZE else ""
            lines.append(f"{prefix}CONFIRM")

        prefix = "►" if slot_id == (PARTY_SIZE + 1) else ""
        lines.append(f"{prefix}CANCEL")

        # Party menu messages are printed into WIN_MSG (window id PARTY_SIZE) via DisplayPartyMenuMessage.
        # Important: window text pointers can stay stale when the printer is inactive. To avoid keeping
        # old messages (e.g. "Which move should be forgotten?"), prefer active printer text first, then
        # the current gStringVar4 message snapshot, and only then fallback to inactive window text.
        bottom_text: Optional[str] = None
        window_text_active: Optional[str] = None
        window_text_inactive: Optional[str] = None
        try:
            window_text_active = get_textprinter_text_for_window(
                int(PARTY_SIZE),
                text_printers_raw=text_printers_raw,
                gstringvar4_raw=gstringvar4_raw,
                gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
                include_inactive=False,
            )
        except Exception:
            window_text_active = None

        if window_text_active:
            bottom_text = window_text_active

        if not bottom_text and gstringvar4_raw is not None:
            guess = decode_gba_string(gstringvar4_raw, 200, stop_at_prompt=True)
            if guess:
                bottom_text = guess

        if not bottom_text:
            try:
                window_text_inactive = get_textprinter_text_for_window(
                    int(PARTY_SIZE),
                    text_printers_raw=text_printers_raw,
                    gstringvar4_raw=gstringvar4_raw,
                    gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
                    include_inactive=True,
                )
            except Exception:
                window_text_inactive = None
            if window_text_inactive:
                bottom_text = window_text_inactive

        if not bottom_text:
            bottom_text = get_current_dialog_text()
        if bottom_text:
            lines.append("")
            lines.append(bottom_text)

        action_menu = get_party_action_menu_state(
            internal_ptr=int(internal_ptr),
            internal_ptr_raw=party_internal_ptr_raw,
            smenu_raw=smenu_raw,
        )
        if action_menu:
            cursor = int(action_menu.get("cursorPosition", 0) or 0)
            choice_lines: List[str] = []
            for i, opt in enumerate(action_menu.get("options", [])):
                prefix = "►" if i == cursor else " "
                choice_lines.append(f"{prefix}{opt}")
            if choice_lines:
                lines.append("")
                lines.extend(choice_lines)

        return {
            "type": "partyMenu",
            "partyCount": int(party_count),
            "slotId": int(slot_id),
            "mons": mons,
            "bottomText": bottom_text,
            "actionMenu": action_menu,
            "visibleText": "\n".join(lines),
        }
    except Exception:
        return None


_POKESUM_MODE_NAMES: Dict[int, str] = {
    0: "normal",
    1: "unk1",
    2: "selectMove",
    3: "forgetMove",
    4: "trade",
    5: "box",
}

_POKESUM_PAGE_NAMES: Dict[int, str] = {
    0: "info",
    1: "skills",
    2: "moves",
    3: "movesInfo",
    4: "unknown4",
    5: "moveDeleter",
}

_POKESUM_PAGE_TITLES: Dict[int, str] = {
    0: "POKEMON INFO",
    1: "POKEMON SKILLS",
    2: "KNOWN MOVES",
    3: "KNOWN MOVES",
    5: "KNOWN MOVES",
}

_POKESUM_PAGE_CONTROLS: Dict[int, str] = {
    0: "Controls: PAGE / CANCEL",
    1: "Controls: PAGE",
    2: "Controls: PAGE / DETAIL",
    3: "Controls: PICK",
    5: "Controls: PICK / DELETE",
}

_NATURE_NAMES: List[str] = [
    "HARDY",
    "LONELY",
    "BRAVE",
    "ADAMANT",
    "NAUGHTY",
    "BOLD",
    "DOCILE",
    "RELAXED",
    "IMPISH",
    "LAX",
    "TIMID",
    "HASTY",
    "SERIOUS",
    "JOLLY",
    "NAIVE",
    "MODEST",
    "MILD",
    "QUIET",
    "BASHFUL",
    "RASH",
    "CALM",
    "GENTLE",
    "SASSY",
    "CAREFUL",
    "QUIRKY",
]


def _decode_summary_text(raw: bytes, offset: int, length: int) -> str:
    try:
        if offset < 0 or length <= 0 or offset >= len(raw):
            return ""
        return decode_gba_string(raw[offset : offset + length], length).strip()
    except Exception:
        return ""


def _digits_to_int(value: str) -> Optional[int]:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _move_type_label(type_id: Optional[int]) -> Optional[str]:
    if type_id is None:
        return None
    return POKEMON_TYPE_MAP.get(int(type_id), f"TYPE_{int(type_id)}")


def _is_mon_original_trainer(ot_name: str, otid: int) -> Optional[bool]:
    """
    Best-effort check equivalent to IsOtherTrainer / PokeSum_BufferOtName_IsEqualToCurrentOwner.
    Returns:
      - True/False when both player name and TID are readable
      - None if save/player info is unavailable
    """
    try:
        if GSAVEBLOCK2_PTR_ADDR == 0:
            return None
        sb2_ptr = int(mgba_read32(GSAVEBLOCK2_PTR_ADDR))
        if not (0x02000000 <= sb2_ptr <= 0x0203FFFF):
            return None

        player_name_raw = mgba_read_range_bytes(sb2_ptr + SB2_PLAYER_NAME_OFFSET, 8)
        player_name = decode_gba_string(player_name_raw, 8).strip()
        if not player_name:
            return None

        player_tid = int(mgba_read16(sb2_ptr + SB2_TRAINER_ID_OFFSET))
        ot_tid = int(otid) & 0xFFFF
        return bool(player_tid == ot_tid and player_name == str(ot_name or "").strip())
    except Exception:
        return None


def _build_summary_trainer_memo_fallback(
    *,
    nature_name: Optional[str],
    is_egg: bool,
    is_bad_egg: bool,
    met_level: Optional[int],
    modern_fateful: bool,
    is_original_trainer: Optional[bool],
) -> Optional[str]:
    lines: List[str] = []
    if nature_name and not is_bad_egg:
        lines.append(f"{nature_name} nature.")

    if is_bad_egg:
        return "\n".join(lines).strip() if lines else None

    if is_egg:
        if met_level == 0:
            lines.append("Hatched from an EGG.")
        else:
            lines.append("Appears to be an EGG.")
        return "\n".join(lines).strip() if lines else None

    if modern_fateful:
        lines.append("Met in a fateful encounter.")
    elif is_original_trainer is False:
        lines.append("Met in a trade.")
    elif isinstance(met_level, int) and met_level > 0:
        lines.append(f"Met at Lv{int(met_level)}.")

    return "\n".join(lines).strip() if lines else None


def get_pokemon_summary_state(
    callback2: Optional[int] = None,
    *,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect and extract FireRed's normal Pokémon Summary screen (info/skills/moves pages).

    This intentionally does NOT handle the move-replacement workflow; that is handled by
    `get_pokemon_summary_select_move_state`.
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)

        cb2_masked = int(callback2) & 0xFFFFFFFE
        if cb2_masked not in (
            CB2_INIT_SUMMARY_SCREEN_ADDR & 0xFFFFFFFE,
            CB2_SUMMARY_SCREEN_ADDR & 0xFFFFFFFE,
        ):
            return None

        screen_ptr = int(mgba_read32(SMON_SUMMARY_SCREEN_PTR_ADDR))
        if screen_ptr == 0:
            return None
        if not (0x02000000 <= screen_ptr <= 0x0203FFFF):
            return None

        # struct PokemonSummaryScreenData (pokefirered/src/pokemon_summary_screen.c)
        # We only read the post-tilemap tail:
        # - windowIds[7] at +0x3000
        # - summary block at +0x3028
        # - state/mode/page at +0x3200..+0x328C
        # - currentMon at +0x3290
        TAIL_OFFSET = 0x3000
        TAIL_LEN = 0x2F4
        SUMMARY_REL = 0x028
        SUMMARY_LEN = 0x1D8
        WINDOW_IDS_REL = 0x000
        IS_EGG_REL = 0x200
        IS_BAD_EGG_REL = 0x204
        MODE_REL = 0x208
        CUR_PAGE_REL = 0x214
        MON_TYPES_REL = 0x220
        MOVE_TYPES_REL = 0x250
        MOVE_IDS_REL = 0x25A
        NUM_MOVES_REL = 0x264
        CURRENT_MON_REL = 0x290

        raw_tail = mgba_read_range_bytes(screen_ptr + TAIL_OFFSET, TAIL_LEN)
        if len(raw_tail) < TAIL_LEN:
            return None

        mode = int(_u8_from(raw_tail, MODE_REL))
        cur_page = int(_u8_from(raw_tail, CUR_PAGE_REL))
        if mode in (2, 3):  # move-select / forget-move handled elsewhere
            return None
        if mode < 0 or mode > 5 or cur_page < 0 or cur_page > 5:
            return None

        window_ids = [int(_u8_from(raw_tail, WINDOW_IDS_REL + i)) for i in range(7)]
        is_egg = bool(_u8_from(raw_tail, IS_EGG_REL))
        is_bad_egg = bool(_u8_from(raw_tail, IS_BAD_EGG_REL))
        summary = bytes(raw_tail[SUMMARY_REL : SUMMARY_REL + SUMMARY_LEN])
        mon_raw = bytes(raw_tail[CURRENT_MON_REL : CURRENT_MON_REL + POKEMON_DATA_SIZE])
        if len(summary) < SUMMARY_LEN or len(mon_raw) < POKEMON_DATA_SIZE:
            return None

        # PokeSummary string buffers offsets (relative to `summary`).
        species_name_txt = _decode_summary_text(summary, 0x000, 11)
        nickname_txt = _decode_summary_text(summary, 0x00C, 12)
        ot_name_txt = _decode_summary_text(summary, 0x018, 12)
        dex_no_txt = _decode_summary_text(summary, 0x03C, 5)
        ot_id_txt = _decode_summary_text(summary, 0x044, 7)
        item_name_txt = _decode_summary_text(summary, 0x04C, 13)
        gender_symbol_txt = _decode_summary_text(summary, 0x05C, 3)
        level_txt = _decode_summary_text(summary, 0x060, 7)
        hp_txt = _decode_summary_text(summary, 0x068, 9)
        stat_txt = [_decode_summary_text(summary, 0x074 + (i * 5), 5) for i in range(5)]
        move_cur_pp_txt = [_decode_summary_text(summary, 0x090 + (i * 11), 11) for i in range(5)]
        move_max_pp_txt = [_decode_summary_text(summary, 0x0C8 + (i * 11), 11) for i in range(5)]
        move_name_txt = [_decode_summary_text(summary, 0x100 + (i * 13), 13) for i in range(5)]
        move_power_txt = [_decode_summary_text(summary, 0x144 + (i * 5), 5) for i in range(5)]
        move_accuracy_txt = [_decode_summary_text(summary, 0x160 + (i * 5), 5) for i in range(5)]
        exp_points_txt = _decode_summary_text(summary, 0x17C, 9)
        exp_to_next_txt = _decode_summary_text(summary, 0x188, 9)
        ability_name_txt = _decode_summary_text(summary, 0x194, 13)
        ability_desc_txt = _decode_summary_text(summary, 0x1A4, 52)

        pid = int(_u32le_from(mon_raw, PID_OFFSET))
        otid = int(_u32le_from(mon_raw, OTID_OFFSET))
        level = int(_u8_from(mon_raw, LEVEL_OFFSET))
        cur_hp = int(_u16le_from(mon_raw, CURRENT_HP_OFFSET))
        max_hp = int(_u16le_from(mon_raw, MAX_HP_OFFSET))
        atk = int(_u16le_from(mon_raw, ATTACK_OFFSET))
        defense = int(_u16le_from(mon_raw, DEFENSE_OFFSET))
        speed = int(_u16le_from(mon_raw, SPEED_OFFSET))
        sp_atk = int(_u16le_from(mon_raw, SP_ATTACK_OFFSET))
        sp_def = int(_u16le_from(mon_raw, SP_DEFENSE_OFFSET))
        mon_nickname = decode_gba_string(mon_raw[NICKNAME_OFFSET : NICKNAME_OFFSET + 10], 10)

        species_id = 0
        held_item_id = 0
        exp_points = 0
        pp_bonuses = 0
        ability_slot = 0
        met_level: Optional[int] = None
        met_location: Optional[int] = None
        met_game: Optional[int] = None
        modern_fateful = False
        move_ids_dec = [0, 0, 0, 0]
        move_pp_current = [0, 0, 0, 0]
        mon_is_egg_data = False
        if pid != 0:
            enc = mon_raw[ENCRYPTED_BLOCK_OFFSET : ENCRYPTED_BLOCK_OFFSET + ENCRYPTED_BLOCK_SIZE]
            if len(enc) >= ENCRYPTED_BLOCK_SIZE:
                key = int(pid) ^ int(otid)
                dec = bytearray(ENCRYPTED_BLOCK_SIZE)
                for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
                    word = _u32le_from(enc, i) ^ key
                    dec[i : i + 4] = int(word & 0xFFFFFFFF).to_bytes(4, "little")

                order = SUBSTRUCTURE_ORDER[pid % 24]
                sub: Dict[str, bytes] = {}
                for i, ch in enumerate(order):
                    start = i * SUBSTRUCTURE_SIZE
                    sub[ch] = bytes(dec[start : start + SUBSTRUCTURE_SIZE])

                growth = sub.get("G", b"")
                attacks = sub.get("A", b"")
                misc = sub.get("M", b"")
                if len(growth) >= SUBSTRUCTURE_SIZE:
                    species_id = int(_u16le_from(growth, 0))
                    held_item_id = int(_u16le_from(growth, 2))
                    exp_points = int(_u32le_from(growth, 4))
                    pp_bonuses = int(_u8_from(growth, 8))
                if len(attacks) >= SUBSTRUCTURE_SIZE:
                    move_ids_dec = [
                        int(_u16le_from(attacks, 0)),
                        int(_u16le_from(attacks, 2)),
                        int(_u16le_from(attacks, 4)),
                        int(_u16le_from(attacks, 6)),
                    ]
                    move_pp_current = [
                        int(_u8_from(attacks, 8)),
                        int(_u8_from(attacks, 9)),
                        int(_u8_from(attacks, 10)),
                        int(_u8_from(attacks, 11)),
                    ]
                if len(misc) >= SUBSTRUCTURE_SIZE:
                    met_location = int(_u8_from(misc, 1))
                    met_data = int(_u16le_from(misc, 2))
                    met_level = int(met_data & 0x7F)
                    met_game = int((met_data >> 7) & 0x0F)
                    iv_bitfield = int(_u32le_from(misc, 4))
                    mon_is_egg_data = ((iv_bitfield >> 30) & 1) != 0
                    ability_slot = (iv_bitfield >> 31) & 1
                    ribbon_bits = int(_u32le_from(misc, 8))
                    modern_fateful = bool((ribbon_bits >> 31) & 1)

        move_types_raw = [int(_u16le_from(raw_tail, MOVE_TYPES_REL + (i * 2))) for i in range(5)]
        num_moves = int(_u8_from(raw_tail, NUM_MOVES_REL))
        # For the normal Summary pages, the canonical move ordering is from currentMon.
        # This keeps move names/types/PP/details aligned with what is actually shown.
        move_ids = [int(move_ids_dec[i]) for i in range(MAX_MON_MOVES)]

        uniq_move_ids = sorted({mid for mid in move_ids if int(mid) > 0})
        battle_move_entries: Dict[int, bytes] = {}
        if uniq_move_ids:
            ranges = [(GBATTLE_MOVES_ADDR + (int(mid) * BATTLE_MOVE_SIZE), BATTLE_MOVE_SIZE) for mid in uniq_move_ids]
            segs = mgba_read_ranges_bytes(ranges)
            for mid, seg in zip(uniq_move_ids, segs):
                if seg and len(seg) >= BATTLE_MOVE_SIZE:
                    battle_move_entries[int(mid)] = bytes(seg[:BATTLE_MOVE_SIZE])

        def _battle_move_field(move_id: int, offset: int) -> Optional[int]:
            seg = battle_move_entries.get(int(move_id))
            if not seg or offset < 0 or offset >= len(seg):
                return None
            return int(seg[offset])

        def _move_pp_max(slot: int, move_id: int) -> int:
            base_pp = _battle_move_field(int(move_id), 4) or 0
            pp_up_count = (int(pp_bonuses) >> (int(slot) * 2)) & 0x3
            return int(base_pp) + ((int(base_pp) * int(pp_up_count)) // 5)

        mon_type1 = int(_u8_from(raw_tail, MON_TYPES_REL + 0))
        mon_type2 = int(_u8_from(raw_tail, MON_TYPES_REL + 1))
        type_names: List[str] = []
        for tid in (mon_type1, mon_type2):
            if tid == 255:
                continue
            tname = _move_type_label(tid)
            if tname and tname not in type_names:
                type_names.append(tname)

        # Fallback to species table if monTypes were not populated.
        if not type_names and species_id > 0:
            try:
                t = mgba_read_range_bytes(SPECIES_INFO_ADDR + (species_id * SPECIES_INFO_SIZE) + SPECIES_INFO_TYPES_OFFSET, 2)
                t1 = int(_u8_from(t, 0))
                t2 = int(_u8_from(t, 1))
                for tid in (t1, t2):
                    if tid == 255:
                        continue
                    tname = _move_type_label(tid)
                    if tname and tname not in type_names:
                        type_names.append(tname)
            except Exception:
                pass

        ability_id: Optional[int] = None
        if species_id > 0:
            try:
                arr = mgba_read_range_bytes(
                    SPECIES_INFO_ADDR + (species_id * SPECIES_INFO_SIZE) + SPECIES_INFO_ABILITIES_OFFSET,
                    2,
                )
                a1 = int(_u8_from(arr, 0))
                a2 = int(_u8_from(arr, 1))
                ability_id = int(a2 if int(ability_slot) == 1 else a1)
            except Exception:
                ability_id = None

        species_name = species_name_txt or get_species_name(int(species_id)) or "POKEMON"
        nickname = nickname_txt or mon_nickname or species_name
        ability_name = ability_name_txt or (get_ability_name(int(ability_id)) if ability_id is not None else None) or ""
        held_item_name = item_name_txt or (get_item_name(int(held_item_id)) if held_item_id > 0 else "") or ""

        moves: List[Dict[str, Any]] = []
        for i in range(MAX_MON_MOVES):
            move_id = int(move_ids[i])
            move_type_id = 0
            if move_id > 0:
                mt = _battle_move_field(move_id, 2)
                if mt is not None:
                    move_type_id = int(mt)
                elif i < len(move_types_raw):
                    move_type_id = int(move_types_raw[i])
            move_type = _move_type_label(move_type_id) if move_id > 0 else None

            # Keep names aligned with type/PP/stats/description by using moveId as source of truth.
            move_name = (get_move_name(int(move_id)) or "").replace("_", " ") if move_id > 0 else ""
            if not move_name:
                move_name = str(move_name_txt[i] or "").strip()
            if not move_name or move_name == "-":
                move_name = f"MOVE_{int(move_id)}" if move_id > 0 else "—"

            current_pp = int(move_pp_current[i]) if move_id > 0 else 0
            max_pp = int(_move_pp_max(i, move_id)) if move_id > 0 else 0
            cur_pp_txt = str(move_cur_pp_txt[i] or "").strip()
            max_pp_txt = str(move_max_pp_txt[i] or "").strip()
            if not cur_pp_txt:
                cur_pp_txt = str(current_pp) if move_id > 0 else "--"
            if not max_pp_txt:
                max_pp_txt = str(max_pp) if move_id > 0 else "--"

            moves.append(
                {
                    "slot": int(i),
                    "moveId": int(move_id),
                    "name": move_name,
                    "typeId": int(move_type_id) if move_id > 0 else None,
                    "type": move_type,
                    "pp": {
                        "current": current_pp if move_id > 0 else None,
                        "max": max_pp if move_id > 0 else None,
                        "currentText": cur_pp_txt,
                        "maxText": max_pp_txt,
                    },
                    "powerText": str(move_power_txt[i] or "").strip() or ("---" if move_id <= 0 else ""),
                    "accuracyText": str(move_accuracy_txt[i] or "").strip() or ("---" if move_id <= 0 else ""),
                }
            )

        cursor_index: Optional[int] = None
        if cur_page in (3, 5) and SMOVE_SELECTION_CURSOR_POS_ADDR:
            try:
                cursor_index = int(mgba_read8(SMOVE_SELECTION_CURSOR_POS_ADDR))
            except Exception:
                cursor_index = None
        if cursor_index is not None:
            if cursor_index < 0 or cursor_index > MAX_MON_MOVES:
                cursor_index = 0

        selected_move: Optional[Dict[str, Any]] = None
        if cur_page in (3, 5) and cursor_index is not None:
            if cursor_index == MAX_MON_MOVES:
                selected_move = {"isCancel": True}
            elif 0 <= cursor_index < MAX_MON_MOVES:
                sel = moves[cursor_index]
                sel_move_id = int(sel.get("moveId") or 0)
                desc = ""
                if sel_move_id > 0:
                    try:
                        desc_ptr = int(mgba_read32(GMOVE_DESCRIPTION_POINTERS_ADDR + ((sel_move_id - 1) * 4)))
                        desc = _read_gba_cstring(desc_ptr, 220) if desc_ptr else ""
                    except Exception:
                        desc = ""
                selected_move = {
                    "slot": int(cursor_index),
                    "moveId": int(sel_move_id),
                    "name": str(sel.get("name") or ""),
                    "powerText": str(sel.get("powerText") or "---"),
                    "accuracyText": str(sel.get("accuracyText") or "---"),
                    "description": desc,
                }

        info_window_id = int(window_ids[4]) if len(window_ids) > 4 else WINDOW_NONE
        trainer_memo_text: Optional[str] = None
        if 0 <= info_window_id < 32 and info_window_id != WINDOW_NONE:
            try:
                trainer_memo_text = get_textprinter_text_for_window(
                    info_window_id,
                    text_printers_raw=text_printers_raw,
                    gstringvar4_raw=gstringvar4_raw,
                    gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
                    include_inactive=False,
                )
            except Exception:
                trainer_memo_text = None
            if not trainer_memo_text:
                try:
                    trainer_memo_text = get_textprinter_text_for_window(
                        info_window_id,
                        text_printers_raw=text_printers_raw,
                        gstringvar4_raw=gstringvar4_raw,
                        gdisplayedstringbattle_raw=gdisplayedstringbattle_raw,
                        include_inactive=True,
                    )
                except Exception:
                    trainer_memo_text = None

        nature_name: Optional[str] = None
        if pid != 0:
            nature_id = int(pid % len(_NATURE_NAMES))
            if 0 <= nature_id < len(_NATURE_NAMES):
                nature_name = _NATURE_NAMES[nature_id]

        if not trainer_memo_text:
            trainer_memo_text = _build_summary_trainer_memo_fallback(
                nature_name=nature_name,
                is_egg=bool(is_egg or mon_is_egg_data),
                is_bad_egg=bool(is_bad_egg),
                met_level=met_level,
                modern_fateful=bool(modern_fateful),
                is_original_trainer=_is_mon_original_trainer(ot_name_txt, otid),
            )

        info_page: Dict[str, Any] = {
            "dexNumberText": dex_no_txt or None,
            "dexNumber": _digits_to_int(dex_no_txt),
            "species": species_name or None,
            "types": type_names,
            "otName": ot_name_txt or None,
            "otIdText": ot_id_txt or None,
            "otId": _digits_to_int(ot_id_txt),
            "heldItemId": int(held_item_id) if int(held_item_id) > 0 else None,
            "heldItem": held_item_name or None,
            "trainerMemo": trainer_memo_text or None,
            "nature": nature_name or None,
            "metLevel": int(met_level) if isinstance(met_level, int) else None,
            "metLocation": int(met_location) if isinstance(met_location, int) else None,
            "metGame": int(met_game) if isinstance(met_game, int) else None,
            "modernFatefulEncounter": bool(modern_fateful),
        }

        skills_page: Dict[str, Any] = {
            "hp": {
                "current": int(cur_hp),
                "max": int(max_hp),
                "text": hp_txt or f"{cur_hp}/{max_hp}",
            },
            "stats": {
                "attack": {"value": int(atk), "text": stat_txt[0] or str(atk)},
                "defense": {"value": int(defense), "text": stat_txt[1] or str(defense)},
                "spAttack": {"value": int(sp_atk), "text": stat_txt[2] or str(sp_atk)},
                "spDefense": {"value": int(sp_def), "text": stat_txt[3] or str(sp_def)},
                "speed": {"value": int(speed), "text": stat_txt[4] or str(speed)},
            },
            "expPoints": _digits_to_int(exp_points_txt) if exp_points_txt else int(exp_points),
            "expPointsText": exp_points_txt or (str(exp_points) if exp_points > 0 else None),
            "nextLevel": _digits_to_int(exp_to_next_txt),
            "nextLevelText": exp_to_next_txt or None,
            "abilityId": int(ability_id) if ability_id is not None else None,
            "ability": ability_name or None,
            "abilityDescription": ability_desc_txt or None,
        }

        moves_page: Dict[str, Any] = {
            "numMoves": int(num_moves),
            "detailMode": bool(cur_page in (3, 5)),
            "cursorIndex": int(cursor_index) if cursor_index is not None else None,
            "moves": moves,
            "selectedMove": selected_move,
        }

        page_title = _POKESUM_PAGE_TITLES.get(int(cur_page), f"SUMMARY PAGE {int(cur_page)}")
        controls_hint = _POKESUM_PAGE_CONTROLS.get(int(cur_page))
        mode_name = _POKESUM_MODE_NAMES.get(int(mode), f"mode_{int(mode)}")
        page_name = _POKESUM_PAGE_NAMES.get(int(cur_page), f"page_{int(cur_page)}")

        header_chunks: List[str] = []
        if level > 0:
            header_chunks.append(f"Lv{int(level)}")
        elif level_txt:
            header_chunks.append(str(level_txt))
        if nickname:
            header_chunks.append(str(nickname))
        if gender_symbol_txt:
            header_chunks.append(str(gender_symbol_txt))
        header_line = " ".join(chunk for chunk in header_chunks if chunk)

        lines: List[str] = [page_title]
        if controls_hint:
            lines.append(controls_hint)
        if header_line:
            lines.append(header_line)
        if lines:
            lines.append("")

        if int(cur_page) == 0:
            if dex_no_txt:
                lines.append(f"No. {dex_no_txt}")
            if species_name:
                lines.append(f"Name: {species_name}")
            if type_names:
                lines.append(f"Type: {' / '.join(type_names)}")
            if ot_name_txt:
                lines.append(f"OT: {ot_name_txt}")
            if ot_id_txt:
                lines.append(f"IDNo: {ot_id_txt}")
            if held_item_name:
                lines.append(f"Item: {held_item_name}")
            if trainer_memo_text:
                lines.append("")
                lines.append("TRAINER MEMO")
                lines.extend([ln for ln in str(trainer_memo_text).splitlines() if ln.strip()])
        elif int(cur_page) == 1:
            lines.append(f"HP {skills_page['hp']['text']}")
            lines.append(f"ATTACK {skills_page['stats']['attack']['text']}")
            lines.append(f"DEFENSE {skills_page['stats']['defense']['text']}")
            lines.append(f"SP.ATK {skills_page['stats']['spAttack']['text']}")
            lines.append(f"SP.DEF {skills_page['stats']['spDefense']['text']}")
            lines.append(f"SPEED {skills_page['stats']['speed']['text']}")
            if skills_page.get("expPointsText"):
                lines.append(f"EXP. POINTS {skills_page['expPointsText']}")
            if skills_page.get("nextLevelText"):
                lines.append(f"NEXT LV. {skills_page['nextLevelText']}")
            if ability_name:
                lines.append("")
                lines.append(f"ABILITY {ability_name}")
            if ability_desc_txt:
                lines.append(str(ability_desc_txt))
        elif int(cur_page) in (2, 3, 5):
            detail_mode = bool(cur_page in (3, 5))
            for i, move in enumerate(moves):
                prefix = "►" if detail_mode and cursor_index == i else " "
                type_label = str(move.get("type") or "---")
                move_name = str(move.get("name") or "—")
                pp_data = move.get("pp") if isinstance(move.get("pp"), dict) else {}
                cur_pp_label = str(pp_data.get("currentText") or "--")
                max_pp_label = str(pp_data.get("maxText") or "--")
                lines.append(f"{prefix}{type_label} {move_name} PP {cur_pp_label}/{max_pp_label}")

            if detail_mode:
                cancel_prefix = "►" if cursor_index == MAX_MON_MOVES else " "
                lines.append(f"{cancel_prefix}CANCEL")

            if detail_mode and selected_move and not selected_move.get("isCancel"):
                lines.append("")
                lines.append(f"POWER {selected_move.get('powerText') or '---'}")
                lines.append(f"ACCURACY {selected_move.get('accuracyText') or '---'}")
                desc = str(selected_move.get("description") or "").strip()
                if desc:
                    lines.append("")
                    lines.append(desc)

        choice_menu: Optional[Dict[str, Any]] = None
        if int(cur_page) in (3, 5) and cursor_index is not None:
            options = [str(m.get("name") or "—") for m in moves] + ["CANCEL"]
            selected_opt = options[cursor_index] if 0 <= int(cursor_index) < len(options) else None
            choice_menu = {
                "type": "summaryMoves",
                "layout": "list",
                "cursorPosition": int(cursor_index),
                "selectedOption": selected_opt,
                "options": options,
            }

        visible_text = "\n".join([ln.rstrip() for ln in lines if ln is not None]).strip()
        if not visible_text:
            visible_text = page_title

        return {
            "type": "summaryScreen",
            "mode": mode_name,
            "modeValue": int(mode),
            "page": page_name,
            "pageValue": int(cur_page),
            "isEgg": bool(is_egg or mon_is_egg_data),
            "isBadEgg": bool(is_bad_egg),
            "header": {
                "title": page_title,
                "controlsHint": controls_hint,
                "level": int(level) if level > 0 else _digits_to_int(level_txt),
                "nickname": nickname or None,
                "gender": gender_symbol_txt or None,
            },
            "pokemon": {
                "speciesId": int(species_id) if species_id > 0 else None,
                "species": species_name or None,
                "nickname": nickname or None,
                "level": int(level) if level > 0 else _digits_to_int(level_txt),
                "types": type_names,
                "otName": ot_name_txt or None,
                "otId": _digits_to_int(ot_id_txt),
                "heldItemId": int(held_item_id) if int(held_item_id) > 0 else None,
                "heldItem": held_item_name or None,
                "abilityId": int(ability_id) if ability_id is not None else None,
                "ability": ability_name or None,
            },
            "infoPage": info_page,
            "skillsPage": skills_page,
            "movesPage": moves_page,
            "choiceMenu": choice_menu,
            "visibleText": visible_text,
        }
    except Exception:
        return None


def get_pokemon_summary_select_move_state(
    callback2: Optional[int] = None,
    *,
    tasks_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect and extract the Pokémon Summary Screen state when selecting a move to replace.

    This corresponds to `SUMMARY_MODE_SELECT_MOVE` (used when learning a new move and asked
    to choose which move to forget).
    """
    try:
        if callback2 is None:
            callback2 = mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET)
        cb2_masked = int(callback2) & 0xFFFFFFFE
        is_summary_callback = cb2_masked in (
            CB2_INIT_SUMMARY_SCREEN_ADDR & 0xFFFFFFFE,
            CB2_SUMMARY_SCREEN_ADDR & 0xFFFFFFFE,
        )

        screen_ptr = int(mgba_read32(SMON_SUMMARY_SCREEN_PTR_ADDR))
        if screen_ptr == 0:
            return None
        # sMonSummaryScreen is EWRAM allocated. Avoid dereferencing stale/garbage pointers.
        if not (0x02000000 <= screen_ptr <= 0x0203FFFF):
            return None

        # struct PokemonSummaryScreenData (pokefirered/src/pokemon_summary_screen.c)
        # Read the same "tail" block used by get_pokemon_summary_state; this layout is verified
        # against the FireRed source offsets (0x3208 mode, 0x3214 page, 0x325A moveIds, 0x3290 currentMon).
        TAIL_OFFSET = 0x3000
        TAIL_LEN = 0x2F4
        SUMMARY_REL = 0x028
        SUMMARY_LEN = 0x1D8
        MODE_REL = 0x208
        CUR_PAGE_REL = 0x214
        MOVE_IDS_REL = 0x25A
        STATE3270_REL = 0x270
        CURRENT_MON_REL = 0x290

        raw_tail = mgba_read_range_bytes(screen_ptr + TAIL_OFFSET, TAIL_LEN)
        if len(raw_tail) < TAIL_LEN:
            return None

        mode = int(_u8_from(raw_tail, MODE_REL))
        # pokemon_summary_screen.h:
        #   2 = PSS_MODE_SELECT_MOVE (learn via TM/HM / tutor / level-up flow)
        #   3 = PSS_MODE_FORGET_MOVE (move deleter flow)
        if mode not in (2, 3):
            return None

        # Snapshot callback2 can occasionally lag a frame behind the rendered UI.
        # When callback doesn't match, keep parsing only if summary state machine is sane.
        if not is_summary_callback:
            state3270 = int(_u8_from(raw_tail, STATE3270_REL))
            if state3270 < 0 or state3270 > 6:
                return None

        curr_page = int(_u8_from(raw_tail, CUR_PAGE_REL))
        if curr_page < 0 or curr_page > 5:
            return None

        summary = bytes(raw_tail[SUMMARY_REL : SUMMARY_REL + SUMMARY_LEN])
        mon_raw = bytes(raw_tail[CURRENT_MON_REL : CURRENT_MON_REL + POKEMON_DATA_SIZE])
        if len(summary) < SUMMARY_LEN or len(mon_raw) < POKEMON_DATA_SIZE:
            return None

        move_cur_pp_txt = [_decode_summary_text(summary, 0x090 + (i * 11), 11) for i in range(5)]
        move_max_pp_txt = [_decode_summary_text(summary, 0x0C8 + (i * 11), 11) for i in range(5)]
        move_name_txt = [_decode_summary_text(summary, 0x100 + (i * 13), 13) for i in range(5)]
        move_power_txt = [_decode_summary_text(summary, 0x144 + (i * 5), 5) for i in range(5)]
        move_accuracy_txt = [_decode_summary_text(summary, 0x160 + (i * 5), 5) for i in range(5)]

        mon_info = _decode_party_mon_teach_info(mon_raw, 0) or {}
        species_id = int(mon_info.get("speciesId") or 0)
        level = int(mon_info.get("level") or int(_u8_from(mon_raw, LEVEL_OFFSET)))
        nickname = str(mon_info.get("nickname") or "").strip()
        if not nickname:
            nickname = decode_gba_string(mon_raw[NICKNAME_OFFSET : NICKNAME_OFFSET + 10], 10).strip()
        if not nickname:
            nickname = get_species_name(species_id) or "POKEMON"

        # Build move IDs from currentMon encrypted data for the 4 known moves.
        # This avoids stale/shifted summary slots during transitions.
        current_move_ids = [0, 0, 0, 0]
        pid = int(_u32le_from(mon_raw, PID_OFFSET))
        otid = int(_u32le_from(mon_raw, OTID_OFFSET))
        if pid != 0:
            enc = mon_raw[ENCRYPTED_BLOCK_OFFSET : ENCRYPTED_BLOCK_OFFSET + ENCRYPTED_BLOCK_SIZE]
            if len(enc) >= ENCRYPTED_BLOCK_SIZE:
                key = int(pid) ^ int(otid)
                dec = bytearray(ENCRYPTED_BLOCK_SIZE)
                for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
                    word = _u32le_from(enc, i) ^ key
                    dec[i : i + 4] = int(word & 0xFFFFFFFF).to_bytes(4, "little")

                order = SUBSTRUCTURE_ORDER[pid % 24]
                sub: Dict[str, bytes] = {}
                for i, ch in enumerate(order):
                    start = i * SUBSTRUCTURE_SIZE
                    sub[ch] = bytes(dec[start : start + SUBSTRUCTURE_SIZE])

                attacks = sub.get("A", b"")
                if len(attacks) >= SUBSTRUCTURE_SIZE:
                    current_move_ids = [
                        int(_u16le_from(attacks, 0)),
                        int(_u16le_from(attacks, 2)),
                        int(_u16le_from(attacks, 4)),
                        int(_u16le_from(attacks, 6)),
                    ]

        # On-screen order should follow displayed moveNameStrBufs first.
        # Match rows to current moves by normalized name to avoid index drift.
        displayed_known_names = [str(move_name_txt[i] or "").strip() for i in range(4)]
        remaining_ids = list(current_move_ids)
        move_ids = [0, 0, 0, 0, 0]
        for i in range(4):
            nm = displayed_known_names[i]
            target_norm = _normalize_move_label_for_lookup(nm)
            picked_idx: Optional[int] = None
            if target_norm:
                for idx, mid in enumerate(remaining_ids):
                    if int(mid) <= 0:
                        continue
                    src_norm = _normalize_move_label_for_lookup(get_move_name(int(mid)))
                    if src_norm and src_norm == target_norm:
                        picked_idx = idx
                        break
            if picked_idx is not None:
                move_ids[i] = int(remaining_ids[picked_idx])
                remaining_ids[picked_idx] = 0
            elif int(current_move_ids[i]) > 0:
                move_ids[i] = int(current_move_ids[i])
            else:
                guessed = _move_id_from_name_label(nm)
                move_ids[i] = int(guessed) if guessed is not None else 0

        raw_new_move_id = int(_u16le_from(raw_tail, MOVE_IDS_REL + (4 * 2)))
        if mode == 2:
            row5_name = str(move_name_txt[4] or "").strip()
            guessed_new = _move_id_from_name_label(row5_name)
            if raw_new_move_id > 0:
                raw_name = _normalize_move_label_for_lookup(get_move_name(int(raw_new_move_id)))
                row5_norm = _normalize_move_label_for_lookup(row5_name)
                if row5_norm and raw_name and row5_norm == raw_name:
                    new_move_id = int(raw_new_move_id)
                elif guessed_new is not None:
                    new_move_id = int(guessed_new)
                else:
                    new_move_id = int(raw_new_move_id)
            else:
                new_move_id = int(guessed_new) if guessed_new is not None else 0
            move_ids[4] = int(new_move_id)
        else:
            new_move_id = 0
            move_ids[4] = 0

        # In select/forget move mode, cursor is tracked by this global in pokemon_summary_screen.c.
        try:
            cursor_index = int(mgba_read8(SMOVE_SELECTION_CURSOR_POS_ADDR)) if SMOVE_SELECTION_CURSOR_POS_ADDR else 0
        except Exception:
            cursor_index = 0
        if cursor_index < 0 or cursor_index > 4:
            cursor_index = 0

        def pretty_move_name(move_id: int) -> str:
            raw = get_move_name(int(move_id))
            if isinstance(raw, str) and raw:
                return raw.replace("_", " ")
            return f"MOVE_{move_id}"

        uniq_move_ids = sorted({mid for mid in (move_ids[:4] + ([new_move_id] if new_move_id > 0 else [])) if int(mid) > 0})
        battle_move_entries: Dict[int, bytes] = {}
        if uniq_move_ids:
            ranges = [(GBATTLE_MOVES_ADDR + (int(mid) * BATTLE_MOVE_SIZE), BATTLE_MOVE_SIZE) for mid in uniq_move_ids]
            segs = mgba_read_ranges_bytes(ranges)
            for mid, seg in zip(uniq_move_ids, segs):
                if seg and len(seg) >= BATTLE_MOVE_SIZE:
                    battle_move_entries[int(mid)] = bytes(seg[:BATTLE_MOVE_SIZE])

        def battle_move_field(move_id: int, offset: int) -> Optional[int]:
            seg = battle_move_entries.get(int(move_id))
            if not seg or offset < 0 or offset >= len(seg):
                return None
            return int(seg[offset])

        def type_label_for(move_id: int) -> str:
            type_id = battle_move_field(move_id, 2)
            name = POKEMON_TYPE_MAP.get(int(type_id), f"TYPE_{type_id}") if type_id is not None else "TYPE"
            return {"FIGHTING": "FIGHT", "ELECTRIC": "ELECT", "PSYCHIC": "PSYCH"}.get(name, name)

        moves: List[Dict[str, Any]] = []
        for i in range(4):
            mid = int(move_ids[i])
            if mid <= 0:
                moves.append(
                    {
                        "slot": int(i),
                        "moveId": 0,
                        "name": None,
                        "labelPrefix": "",
                        "pp": {"current": None, "max": None, "currentText": "--", "maxText": "--"},
                        "typeId": None,
                        "power": None,
                        "accuracy": None,
                        "powerText": "---",
                        "accuracyText": "---",
                    }
                )
                continue

            cur_txt = str(move_cur_pp_txt[i] or "").strip()
            max_txt = str(move_max_pp_txt[i] or "").strip()
            power_txt = str(move_power_txt[i] or "").strip()
            acc_txt = str(move_accuracy_txt[i] or "").strip()
            power = battle_move_field(int(mid), 1)
            accuracy = battle_move_field(int(mid), 3)

            if not power_txt:
                power_txt = "---" if power is None or int(power) < 2 else str(int(power))
            if not acc_txt:
                acc_txt = "---" if accuracy is None or int(accuracy) == 0 else str(int(accuracy))

            moves.append(
                {
                    "slot": int(i),
                    "moveId": int(mid),
                    "name": pretty_move_name(int(mid)) if mid > 0 else (str(move_name_txt[i] or "").strip() or None),
                    "labelPrefix": type_label_for(int(mid)),
                    "pp": {
                        "current": _digits_to_int(cur_txt),
                        "max": _digits_to_int(max_txt),
                        "currentText": cur_txt or "--",
                        "maxText": max_txt or "--",
                    },
                    "typeId": battle_move_field(int(mid), 2),
                    "power": int(power) if power is not None else None,
                    "accuracy": int(accuracy) if accuracy is not None else None,
                    "powerText": power_txt,
                    "accuracyText": acc_txt,
                }
            )

        new_move_obj: Dict[str, Any]
        if mode == 2 and int(new_move_id) > 0:
            base_pp = battle_move_field(int(new_move_id), 4) or 0
            new_move_obj = {
                "moveId": int(new_move_id),
                "name": pretty_move_name(int(new_move_id)),
                "labelPrefix": type_label_for(int(new_move_id)),
                "pp": {"current": int(base_pp), "max": int(base_pp), "currentText": str(int(base_pp)), "maxText": str(int(base_pp))},
                "typeId": battle_move_field(int(new_move_id), 2),
                "power": battle_move_field(int(new_move_id), 1),
                "accuracy": battle_move_field(int(new_move_id), 3),
            }
        else:
            new_move_obj = {
                "moveId": 0,
                "name": "CANCEL",
                "labelPrefix": "",
                "pp": {"current": None, "max": None, "currentText": "--", "maxText": "--"},
                "typeId": None,
                "power": None,
                "accuracy": None,
            }

        hm_message_active = _find_active_task_by_func(TASK_SUMMARY_HANDLE_CANT_FORGET_HMS_MOVES_ADDR, tasks_raw) is not None

        selected_move_id: Optional[int] = None
        selected_key: str = "unknown"
        if 0 <= cursor_index < 4:
            selected_key = f"move{cursor_index}"
            selected_move_id = int(move_ids[cursor_index]) if int(move_ids[cursor_index]) > 0 else None
        elif cursor_index == 4:
            if mode == 2 and int(new_move_id) > 0:
                selected_key = "newMove"
                selected_move_id = int(new_move_id)
            else:
                selected_key = "cancel"
                selected_move_id = None

        details: Dict[str, Any] = {}
        if hm_message_active:
            details = {"message": "HM moves can't be forgotten now."}
        elif selected_move_id is not None:
            power = battle_move_field(int(selected_move_id), 1)
            accuracy = battle_move_field(int(selected_move_id), 3)
            desc_ptr = int(mgba_read32(GMOVE_DESCRIPTION_POINTERS_ADDR + ((int(selected_move_id) - 1) * 4)))
            desc = _read_gba_cstring(desc_ptr, 220) if desc_ptr else ""
            details = {"power": power, "accuracy": accuracy, "description": desc}

        page_name = "battleMoves" if curr_page in (2, 3, 5) else f"page{curr_page}"

        options: List[str] = []
        option_meta: List[Dict[str, Any]] = []
        for i, m in enumerate(moves):
            label = str(m.get("name") or "—")
            options.append(label)
            option_meta.append({"index": int(i), "slot": int(i), "moveId": int(m.get("moveId") or 0)})

        if mode == 2:
            options.append(str(new_move_obj.get("name") or "NEW MOVE"))
            option_meta.append(
                {
                    "index": 4,
                    "slot": 4,
                    "moveId": int(new_move_obj.get("moveId") or 0),
                    "isNewMove": True,
                }
            )
        else:
            options.append("CANCEL")
            option_meta.append({"index": 4, "slot": 4, "moveId": 0, "isCancel": True})

        selected_option = options[cursor_index] if 0 <= cursor_index < len(options) else None

        lines: List[str] = []
        lines.append("KNOWN MOVES")
        lines.append("PICK / SWITCH" if mode == 2 else "PICK")
        lines.append(f"{nickname} Lv{level}" if level > 0 else nickname)
        lines.append("")

        for i, m in enumerate(moves):
            prefix = "►" if i == cursor_index else " "
            type_lbl = str(m.get("labelPrefix") or "---")
            name = str(m.get("name") or "—")
            pp = m.get("pp") if isinstance(m.get("pp"), dict) else {}
            cur_pp = str(pp.get("currentText") or "--")
            max_pp = str(pp.get("maxText") or "--")
            lines.append(f"{prefix}{type_lbl} {name} PP {cur_pp}/{max_pp}")

        tail_prefix = "►" if cursor_index == 4 else " "
        if mode == 2 and int(new_move_obj.get("moveId") or 0) > 0:
            nm_type = str(new_move_obj.get("labelPrefix") or "---")
            nm_name = str(new_move_obj.get("name") or "NEW MOVE")
            nm_pp = new_move_obj.get("pp") if isinstance(new_move_obj.get("pp"), dict) else {}
            nm_cur = str(nm_pp.get("currentText") or "--")
            nm_max = str(nm_pp.get("maxText") or "--")
            lines.append(f"{tail_prefix}{nm_type} {nm_name} PP {nm_cur}/{nm_max}")
        else:
            lines.append(f"{tail_prefix}CANCEL")

        if details:
            lines.append("")
            if "message" in details:
                lines.append(str(details.get("message") or "").strip())
            else:
                p = details.get("power")
                a = details.get("accuracy")
                lines.append(f"POWER {'---' if p is None or int(p) < 2 else int(p)}")
                lines.append(f"ACCURACY {'---' if a is None or int(a) == 0 else int(a)}")
                desc = str(details.get("description") or "").strip()
                if desc:
                    lines.append("")
                    lines.append(desc)

        choice_menu = {
            "type": "summaryMoveReplace",
            "cursorPosition": int(cursor_index),
            "selectedOption": selected_option,
            "options": options,
            "optionMeta": option_meta,
        }

        mode_name = "selectMove" if mode == 2 else "forgetMove"

        return {
            "type": "summaryScreen",
            "mode": mode_name,
            "page": page_name,
            "pokemon": {
                "nickname": nickname,
                "level": int(level),
                "speciesId": int(species_id) if species_id > 0 else None,
                "species": get_species_name(int(species_id)) if species_id else None,
            },
            "cursorIndex": int(cursor_index),
            "moves": moves,
            "newMove": new_move_obj,
            "selected": {
                "key": selected_key,
                "moveId": int(selected_move_id) if selected_move_id is not None else None,
                "name": pretty_move_name(int(selected_move_id)) if selected_move_id else None,
            },
            "hmCantForgetMessageActive": bool(hm_message_active),
            "details": details,
            "choiceMenu": choice_menu,
            "visibleText": "\n".join([ln.rstrip() for ln in lines]).strip(),
        }
    except Exception:
        return None


def get_multichoice_menu_state(
    tasks_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
    *,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    sb1_ptr: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect script multichoice menus (ScriptMenu_Multichoice).

    Extracts options from sMultichoiceLists[multichoiceId] in ROM and uses sMenu.cursorPos for selection.

    Notes:
    - Some multichoices are "dynamic" and render options manually (e.g. the Pokémon Center PC menu).
      Those require special handling because sMultichoiceLists does not contain the real options.
    """
    try:
        task_id = _find_active_task_by_func(TASK_HANDLE_MULTICHOICE_INPUT_ADDR, tasks_raw)
        if task_id is None:
            return None

        if tasks_raw is not None:
            base = task_id * TASK_SIZE
            multichoice_id_raw = _u16le_from(tasks_raw, base + TASK_DATA_OFFSET + (7 * 2))
        else:
            task_addr = GTASKS_ADDR + (task_id * TASK_SIZE)
            multichoice_id_raw = mgba_read16(task_addr + TASK_DATA_OFFSET + (7 * 2))
        multichoice_id = _s16_from_u16(multichoice_id_raw)
        if multichoice_id < 0 or multichoice_id > 512:
            return None

        # Special-case: Pokémon Center PC menu (CreatePCMultichoice / MULTI_PC).
        # In pokefirered, sMultichoiceLists[MULTI_PC] is a dummy list (Exit only),
        # and the real options are printed directly to the menu window.
        if int(multichoice_id) == int(MULTI_PC):
            prompt = _read_gba_cstring(GTEXT_WHICH_PC_SHOULD_BE_ACCESSED_ADDR, 96) or "Which PC should be accessed?"

            max_pos = (
                int(_u8_from(smenu_raw, SMENU_MAXCURSORPOS_OFFSET))
                if smenu_raw is not None
                else int(mgba_read8(SMENU_ADDR + SMENU_MAXCURSORPOS_OFFSET))
            )
            choice_count = int(max_pos) + 1
            if choice_count < 2 or choice_count > 10:
                return None

            if sb1_ptr is None:
                try:
                    sb1_ptr = int(mgba_read32(GSAVEBLOCK1_PTR_ADDR))
                except Exception:
                    sb1_ptr = 0

            has_lanette = False
            try:
                if sb1_ptr:
                    has_lanette = _flag_get_from_sb1(int(sb1_ptr), FLAG_SYS_PC_LANETTE)
            except Exception:
                has_lanette = False

            first = (
                _read_gba_cstring(GTEXT_LANETTES_PC_ADDR, 64)
                if has_lanette
                else _read_gba_cstring(GTEXT_SOMEONES_PC_ADDR, 64)
            ) or "SOMEONE'S PC"

            if gstringvar4_raw is None:
                gstringvar4_raw = mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
            players_pc = decode_gba_string(gstringvar4_raw, 64) or "PLAYER'S PC"

            options: List[str] = [first, players_pc]
            if choice_count >= 4:
                hall = _read_gba_cstring(GTEXT_HALL_OF_FAME_ADDR, 64) or "HALL OF FAME"
                options.append(hall)
            options.append(_read_gba_cstring(GTEXT_LOG_OFF_ADDR, 64) or "LOG OFF")

            # Match the actual number of options shown.
            if len(options) > choice_count:
                options = options[:choice_count]
            while len(options) < choice_count:
                options.append(f"CHOICE_{len(options)}")

            cursor_pos = _read_menu_cursor_pos(smenu_raw)
            selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"
            return {
                "type": "multichoice",
                "taskId": task_id,
                "multichoiceId": int(multichoice_id),
                "cursorPosition": int(cursor_pos),
                "selectedOption": selected,
                "options": options,
                "promptText": prompt,
                "dynamic": True,
            }

        entry_addr = SMULTICHOICE_LISTS_ADDR + (multichoice_id * 8)
        list_ptr = mgba_read32(entry_addr + 0x00)
        count = mgba_read8(entry_addr + 0x04)
        if count <= 0 or count > 20:
            return None

        options: List[str] = []
        for i in range(count):
            text_ptr = mgba_read32(list_ptr + (i * 8))
            txt = _read_gba_cstring(text_ptr, 64) or f"CHOICE_{i}"
            options.append(txt)

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        return {
            "type": "multichoice",
            "taskId": task_id,
            "multichoiceId": int(multichoice_id),
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
        }
    except Exception:
        return None


def get_player_pc_menu_state(tasks_raw: Optional[bytes] = None, smenu_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect the Player PC / Bedroom PC menu (ITEM STORAGE / MAILBOX / ...).

    This menu is not a ScriptMenu multichoice; it's a standard menu driven by PlayerPCProcessMenuInput,
    with the visible options coming from sPlayerPCMenuActions + sTopMenuOptionOrder.
    """
    try:
        task_candidates: List[int] = []
        if isinstance(TASK_PLAYER_PC_PROCESS_MENU_INPUT_ADDRS, Sequence):  # noqa: F405
            task_candidates.extend(int(a) for a in TASK_PLAYER_PC_PROCESS_MENU_INPUT_ADDRS if int(a) != 0)  # noqa: F405
        if int(TASK_PLAYER_PC_PROCESS_MENU_INPUT_ADDR) != 0:  # noqa: F405
            task_candidates.append(int(TASK_PLAYER_PC_PROCESS_MENU_INPUT_ADDR))  # noqa: F405
        if int(TASK_PLAYER_PC_DRAW_TOP_MENU_ADDR) != 0:  # noqa: F405
            task_candidates.append(int(TASK_PLAYER_PC_DRAW_TOP_MENU_ADDR))  # noqa: F405

        task_id = _find_active_task_by_funcs(task_candidates, tasks_raw)
        if task_id is None:
            return None

        num = int(mgba_read8(STOP_MENU_NUM_OPTIONS_ADDR))
        if num <= 0 or num > 8:
            return None

        order_ptr = int(mgba_read32(STOP_MENU_OPTION_ORDER_PTR_ADDR))
        if order_ptr == 0:
            return None

        order_raw = mgba_read_range_bytes(order_ptr, num)
        order = [int(b) for b in order_raw[:num]]

        options: List[str] = []
        for opt_id in order:
            text_ptr = int(mgba_read32(SPLAYER_PC_MENU_ACTIONS_ADDR + (opt_id * MENU_ACTION_SIZE) + 0x00))
            txt = _read_gba_cstring(text_ptr, 64) or f"CHOICE_{opt_id}"
            options.append(txt)

        options_upper = [str(opt or "").upper() for opt in options]
        has_item_storage = any("ITEM STORAGE" in opt for opt in options_upper)
        has_mailbox = any("MAILBOX" in opt for opt in options_upper)
        has_turnoff = any(("TURN OFF" in opt) or ("LOG OFF" in opt) for opt in options_upper)
        if not (has_item_storage and has_mailbox and has_turnoff):
            return None

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        if cursor_pos < 0 or cursor_pos >= len(options):
            cursor_pos = 0
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"
        prompt = (_read_gba_cstring(GTEXT_WHAT_WOULD_YOU_LIKE_ADDR, 96) or "").strip() or "What would you like to do?"
        lines = [prompt, ""]
        for i, opt in enumerate(options):
            lines.append(f"{'►' if i == cursor_pos else ' '}{opt}")
        visible_text = "\n".join(lines)

        return {
            "type": "playerPcMenu",
            "taskId": task_id,
            "promptText": prompt,
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
            "visibleText": visible_text,
        }
    except Exception:
        return None


def get_item_storage_menu_state(tasks_raw: Optional[bytes] = None, smenu_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect the Player PC "ITEM STORAGE" main menu:

    - WITHDRAW ITEM / DEPOSIT ITEM / TOSS ITEM / CANCEL
    - Bottom text is printed in window 0 (dialog box) but often via TEXT_SKIP_DRAW (TextPrinter inactive).

    Implementation strategy:
    - Identify the controlling task by ItemStorageMenuProcessInput.
    - Reconstruct options + descriptions from ROM tables (sItemStorage_MenuActions / sItemStorage_OptionDescriptions).
    """
    try:
        task_id = _find_active_task_by_func(ITEM_STORAGE_MENU_PROCESS_INPUT_ADDR, tasks_raw)
        if task_id is None:
            return None

        option_count = 3  # FireRed: WITHDRAW / DEPOSIT / CANCEL
        options: List[str] = []
        for i in range(option_count):
            text_ptr = int(mgba_read32(SITEM_STORAGE_MENU_ACTIONS_ADDR + (i * MENU_ACTION_SIZE) + 0x00))
            txt = _read_gba_cstring(text_ptr, 32) or f"OPTION_{i}"
            options.append(txt)

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        if cursor_pos < 0:
            cursor_pos = 0
        if cursor_pos >= len(options):
            cursor_pos = len(options) - 1 if options else 0
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        desc_ptr = int(mgba_read32(SITEM_STORAGE_OPTION_DESCRIPTIONS_ADDR + (cursor_pos * 4)))
        desc = _read_gba_cstring(desc_ptr, 128) or ""

        lines = []
        if desc:
            lines.append(desc)
            lines.append("")
        for i, opt in enumerate(options):
            prefix = "►" if i == cursor_pos else " "
            lines.append(f"{prefix}{opt}")
        visible_text = "\n".join(lines).strip() or None

        return {
            "type": "itemStorageMenu",
            "taskId": int(task_id),
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
            "descriptionText": desc or None,
            "visibleText": visible_text,
        }
    except Exception:
        return None


def _read_player_pc_item_page_info(raw: Optional[bytes]) -> Optional[Dict[str, int]]:
    if not raw or len(raw) < 11:
        return None
    # struct PlayerPCItemPageStruct (pokefirered/include/player_pc.h)
    items_above = int(_u16le_from(raw, 0))
    cursor_pos = int(_u16le_from(raw, 2))
    page_items = int(_u8_from(raw, 4))
    count = int(_u8_from(raw, 5))
    scroll_task = int(_u8_from(raw, 10))
    return {
        "cursorPos": cursor_pos,
        "itemsAbove": items_above,
        "pageItems": page_items,
        "count": count,
        "scrollIndicatorTaskId": scroll_task,
    }


def _read_pc_items_slots(*, sb1_ptr: int, used_count: int) -> List[Tuple[str, int]]:
    if not sb1_ptr or used_count <= 0:
        return []
    raw = mgba_read_range_bytes(int(sb1_ptr) + SB1_PC_ITEMS_OFFSET, PC_ITEMS_COUNT * ITEM_SLOT_SIZE)
    if not raw:
        return []
    out: List[Tuple[str, int]] = []
    for i in range(min(int(used_count), PC_ITEMS_COUNT)):
        off = i * ITEM_SLOT_SIZE
        if off + 4 > len(raw):
            break
        item_id = int.from_bytes(raw[off : off + 2], "little")
        qty = int.from_bytes(raw[off + 2 : off + 4], "little")
        if item_id == 0:
            break
        name = get_item_name(item_id) or f"ITEM_{item_id}"
        out.append((name, int(qty)))
    return out


def get_item_storage_context_menu_state(
    *,
    tasks_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the Item PC per-item submenu (WITHDRAW / GIVE / CANCEL) from item_pc.c.
    """
    try:
        if not _ITEM_PC_SUBMENU_TASK_FUNCS:
            return None
        task_id = _find_active_task_by_funcs(_ITEM_PC_SUBMENU_TASK_FUNCS, tasks_raw)
        if task_id is None:
            return None

        option_count = 3
        options: List[str] = []
        for i in range(option_count):
            text_ptr = int(mgba_read32(SITEM_PC_SUBMENU_OPTIONS_ADDR + (i * MENU_ACTION_SIZE) + 0x00))
            txt = _read_gba_cstring(text_ptr, 32) or f"OPTION_{i}"
            options.append(txt)

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        if cursor_pos < 0:
            cursor_pos = 0
        if cursor_pos >= len(options):
            cursor_pos = len(options) - 1 if options else 0
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        return {
            "type": "itemStorageContextMenu",
            "taskId": int(task_id),
            "layout": "list",
            "columns": 1,
            "rows": int(len(options)),
            "cursorPosition": int(cursor_pos),
            "cursorPositionRaw": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
        }
    except Exception:
        return None


def get_item_storage_list_state(
    *,
    tasks_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    item_storage_menu_ptr_raw: Optional[bytes] = None,
    player_pc_item_page_info_raw: Optional[bytes] = None,
    item_pc_list_state_raw: Optional[bytes] = None,
    sb1_ptr: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the Item PC "WITHDRAW ITEM" list screen (item_pc.c).

    This ListMenu state is driven by:
    - sStateDataPtr (ItemPcResources): nItems/maxShowed
    - sListMenuState (ItemPcStaticResources): scroll/row
    - gSaveBlock1Ptr->pcItems: names/quantities
    """
    try:
        # Legacy parameter kept for compatibility with older call-sites.
        _ = player_pc_item_page_info_raw

        # item_pc.c state ptr (sStateDataPtr) must be non-null.
        menu_ptr = (
            int.from_bytes(item_storage_menu_ptr_raw[:4], "little")
            if item_storage_menu_ptr_raw is not None and len(item_storage_menu_ptr_raw) >= 4
            else int(mgba_read32(SITEM_STORAGE_MENU_PTR_ADDR))
        )
        if menu_ptr == 0:
            return None

        # Require an active Item PC task to avoid stale pointer false-positives after closing the PC.
        task_id = _find_active_task_by_funcs(_ITEM_PC_TASK_FUNCS, tasks_raw)
        if task_id is None:
            return None

        # struct ItemPcResources (item_pc.c): maxShowed/nItems
        state_raw = mgba_read_range_bytes(menu_ptr, 0x14)
        if not state_raw or len(state_raw) < 8:
            return None

        n_items = int(_u8_from(state_raw, 7))
        max_showed = int(_u8_from(state_raw, 6))
        if n_items < 0 or n_items > PC_ITEMS_COUNT:
            return None
        count = int(n_items + 1)  # + CANCEL row
        page_items = int(max_showed if 1 <= max_showed <= 6 else min(6, count))
        if count <= 0:
            return None

        # struct ItemPcStaticResources (item_pc.c): savedCallback, scroll, row, initialized
        if item_pc_list_state_raw is None:
            item_pc_list_state_raw = mgba_read_range_bytes(SITEM_STORAGE_LIST_MENU_STATE_ADDR, 0x0C)
        if not item_pc_list_state_raw or len(item_pc_list_state_raw) < 8:
            return None
        items_above = int(_u16le_from(item_pc_list_state_raw, 4))
        cursor_pos = int(_u16le_from(item_pc_list_state_raw, 6))
        if items_above < 0:
            items_above = 0
        if items_above >= count:
            items_above = max(0, count - 1)
        if cursor_pos < 0:
            cursor_pos = 0
        if cursor_pos >= page_items:
            cursor_pos = max(0, page_items - 1)
        if (items_above + cursor_pos) >= count:
            cursor_pos = max(0, (count - 1) - items_above)

        items = _read_pc_items_slots(sb1_ptr=int(sb1_ptr or 0), used_count=int(n_items))

        title_text = get_textprinter_text_for_window(
            2,
            text_printers_raw=text_printers_raw,
            gstringvar4_raw=gstringvar4_raw,
            include_inactive=True,
        )
        if not isinstance(title_text, str) or not title_text.strip():
            title_text = "WITHDRAW ITEM"
        else:
            title_text = title_text.strip()

        # Description is rendered in Item PC window 1.
        message_text = get_textprinter_text_for_window(
            1,
            text_printers_raw=text_printers_raw,
            gstringvar4_raw=gstringvar4_raw,
            include_inactive=True,
        )
        if not isinstance(message_text, str) or not message_text.strip():
            message_text = None
        else:
            message_text = message_text.strip()

        context_menu = get_item_storage_context_menu_state(tasks_raw=tasks_raw, smenu_raw=smenu_raw)
        context_menu_open = context_menu is not None

        start = max(0, items_above)
        end = min(count, items_above + page_items) if page_items > 0 else count
        list_lines: List[str] = []
        for row_idx in range(start, end):
            is_cancel = row_idx == n_items
            if is_cancel:
                label = "CANCEL"
            else:
                name, qty = items[row_idx] if 0 <= row_idx < len(items) else (f"ITEM_{row_idx}", 0)
                label = f"{name} x{qty}"
            if row_idx == (items_above + cursor_pos):
                prefix = "▷" if context_menu_open else "►"
            else:
                prefix = " "
            list_lines.append(f"{prefix}{label}".rstrip())

        lines: List[str] = []
        if title_text:
            lines.append(title_text)
        if message_text:
            if lines:
                lines.append("")
            lines.append(message_text)
        if list_lines:
            if lines:
                lines.append("")
            lines.extend(list_lines)
        if context_menu:
            lines.append("")
            cm_cursor = int(context_menu.get("cursorPosition", 0) or 0)
            cm_options = context_menu.get("options") if isinstance(context_menu.get("options"), list) else []
            for i, opt in enumerate(cm_options):
                prefix = "►" if i == cm_cursor else " "
                lines.append(f"{prefix}{opt}")

        visible_text = "\n".join([ln for ln in lines if ln is not None]).strip() or None

        selected_idx = items_above + cursor_pos
        selected = "CANCEL" if selected_idx == n_items else (items[selected_idx][0] if 0 <= selected_idx < len(items) else "UNKNOWN")

        return {
            "type": "itemStorageList",
            "taskId": int(task_id) if task_id is not None else None,
            "cursorPosition": int(cursor_pos),
            "itemsAbove": int(items_above),
            "pageItems": int(page_items),
            "count": int(count),
            "selectedIndex": int(selected_idx),
            "selectedItem": selected,
            "contextMenu": context_menu,
            "visibleText": visible_text,
        }
    except Exception:
        return None


def get_pokemon_storage_pc_menu_state(tasks_raw: Optional[bytes] = None, smenu_raw: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Detect the Pokémon Storage System PC main menu (withdraw/deposit/move/exit) shown *before* entering boxes.

    Driven by Task_PCMainMenu and backed by the ROM table `sMainMenuTexts` (text + description).
    """
    try:
        task_id = _find_active_task_by_func(TASK_POKEMON_STORAGE_PC_MAIN_MENU_ADDR, tasks_raw)
        if task_id is None:
            return None

        option_count = 5  # OPTION_WITHDRAW..OPTION_EXIT in pokefirered/src/pokemon_storage_system.c
        options: List[str] = []
        descriptions: List[str] = []
        for i in range(option_count):
            base = SPOKE_STORAGE_MAIN_MENU_TEXTS_ADDR + (i * 8)
            text_ptr = int(mgba_read32(base + 0x00))
            desc_ptr = int(mgba_read32(base + 0x04))
            options.append(_read_gba_cstring(text_ptr, 64) or f"OPTION_{i}")
            descriptions.append(_read_gba_cstring(desc_ptr, 128) or "")

        cursor_pos = _read_menu_cursor_pos(smenu_raw)
        if cursor_pos < 0:
            cursor_pos = 0
        if cursor_pos >= len(options):
            cursor_pos = len(options) - 1 if options else 0
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"
        desc = descriptions[cursor_pos] if 0 <= cursor_pos < len(descriptions) else ""

        lines: List[str] = []
        if desc:
            lines.append(desc)
            lines.append("")
        for i, opt in enumerate(options):
            prefix = "►" if i == cursor_pos else " "
            lines.append(f"{prefix}{opt}")
        visible_text = "\n".join(lines).strip() or None

        return {
            "type": "pokemonStoragePcMenu",
            "taskId": int(task_id),
            "cursorPosition": int(cursor_pos),
            "selectedOption": selected,
            "options": options,
            "descriptionText": desc or None,
            "visibleText": visible_text,
        }
    except Exception:
        return None


def get_pokemon_storage_system_state(
    *,
    callback2: Optional[int] = None,
    windows_raw: Optional[bytes] = None,
    smenu_raw: Optional[bytes] = None,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    storage_ptr_raw: Optional[bytes] = None,
    choose_box_menu_ptr_raw: Optional[bytes] = None,
    in_party_menu_raw: Optional[bytes] = None,
    current_box_option_raw: Optional[bytes] = None,
    deposit_box_id_raw: Optional[bytes] = None,
    cursor_area_raw: Optional[bytes] = None,
    cursor_position_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect the Pokémon Storage System UI (box interface).

    Key signals:
    - gMain.callback2 == CB2_PokeStorage / CB2_ReturnToPokeStorage (masked)
    - sStorage pointer non-null

    Visible text:
    - The bottom prompt is printed in WIN_MESSAGE (=1) inside the storage UI.
    """
    try:
        global _POKE_STORAGE_MENU_WINDOWID_OFFSET, _POKE_STORAGE_BOX_TITLE_TEXT_OFFSET, _POKE_STORAGE_MESSAGE_TEXT_OFFSET

        cb2 = int(callback2 if callback2 is not None else mgba_read32(GMAIN_ADDR + GMAIN_CALLBACK2_OFFSET))
        masked = cb2 & 0xFFFFFFFE
        if masked not in (
            int(CB2_POKE_STORAGE_ADDR) & 0xFFFFFFFE,
            int(CB2_RETURN_TO_POKE_STORAGE_ADDR) & 0xFFFFFFFE,
        ):
            return None

        storage_ptr = (
            int.from_bytes(storage_ptr_raw[:4], "little")
            if storage_ptr_raw is not None and len(storage_ptr_raw) >= 4
            else int(mgba_read32(SPOKE_STORAGE_PTR_ADDR))
        )
        if storage_ptr == 0:
            # During very early init, callback2 may already be set but sStorage isn't ready.
            # Still treat this as active so we can surface at least the message window text.
            storage_ptr = 0

        choose_box_menu_ptr = (
            int.from_bytes(choose_box_menu_ptr_raw[:4], "little")
            if choose_box_menu_ptr_raw is not None and len(choose_box_menu_ptr_raw) >= 4
            else int(mgba_read32(SPOKE_STORAGE_CHOOSE_BOX_MENU_PTR_ADDR))
        )
        in_party_menu = (
            int(in_party_menu_raw[0])
            if in_party_menu_raw is not None and len(in_party_menu_raw) >= 1
            else int(mgba_read8(SPOKE_STORAGE_IN_PARTY_MENU_ADDR))
        )
        current_box_option = (
            int(current_box_option_raw[0])
            if current_box_option_raw is not None and len(current_box_option_raw) >= 1
            else int(mgba_read8(SPOKE_STORAGE_CURRENT_BOX_OPTION_ADDR))
        )
        deposit_box_id = (
            int(deposit_box_id_raw[0])
            if deposit_box_id_raw is not None and len(deposit_box_id_raw) >= 1
            else int(mgba_read8(SPOKE_STORAGE_DEPOSIT_BOX_ID_ADDR))
        )
        cursor_area = (
            _s8_from_u8(int(cursor_area_raw[0]))
            if cursor_area_raw is not None and len(cursor_area_raw) >= 1
            else _s8_from_u8(int(mgba_read8(SPOKE_STORAGE_CURSOR_AREA_ADDR)))
        )
        cursor_position = (
            _s8_from_u8(int(cursor_position_raw[0]))
            if cursor_position_raw is not None and len(cursor_position_raw) >= 1
            else _s8_from_u8(int(mgba_read8(SPOKE_STORAGE_CURSOR_POSITION_ADDR)))
        )

        # Current box (data storage, not UI storage).
        current_box_id: Optional[int] = None
        current_box_name: Optional[str] = None
        box_title_text: Optional[str] = None
        box_title_selected: bool = int(cursor_area) == 2  # CURSOR_AREA_BOX_TITLE
        box_mons: Optional[List[Optional[Dict[str, Any]]]] = None
        box_mons_summary: Optional[List[Optional[Dict[str, Any]]]] = None
        grid_text: Optional[str] = None
        left_panel_text: Optional[str] = None
        try:
            ps_ptr = int(mgba_read32(GPOKEMON_STORAGE_PTR_ADDR))
            if ps_ptr:
                cur_box = int(mgba_read8(ps_ptr + POKEMON_STORAGE_CURRENT_BOX_OFFSET))
                if 0 <= cur_box < TOTAL_BOXES_COUNT:
                    current_box_id = int(cur_box)
                    # boxNames[TOTAL_BOXES_COUNT][9]
                    name_addr = ps_ptr + 0x8344 + (cur_box * 9)
                    name_raw = mgba_read_range_bytes(name_addr, 9)
                    current_box_name = decode_gba_string(name_raw, 9).strip() or f"BOX{cur_box + 1}"

                    # Requested human format:
                    # - [< BOX 1 >]
                    # - ►[< BOX 1 >] when cursor is on the box-title selector.
                    box_number = int(cur_box) + 1
                    box_title_text = f"[< BOX {box_number} >]"
                    if box_title_selected:
                        box_title_text = "►" + box_title_text

                    # Box grid mons (30 slots, 6x5).
                    try:
                        _box_id, box_mons = player_pc.get_pc_box_mons(box_id=int(cur_box))
                    except Exception:
                        box_mons = None

                    if isinstance(box_mons, list) and len(box_mons) == IN_BOX_COUNT:
                        # Lightweight per-slot summary (useful for clients / debugging).
                        box_mons_summary = []
                        for m in box_mons:
                            if m is None:
                                box_mons_summary.append(None)
                                continue
                            box_mons_summary.append(
                                {
                                    "nickname": m.get("nickname"),
                                    "species": m.get("species"),
                                    "level": m.get("level"),
                                    "genderSymbol": m.get("genderSymbol"),
                                    "isEgg": m.get("isEgg"),
                                    "heldItemName": m.get("heldItemName"),
                                    "is_shiny": m.get("is_shiny"),
                                }
                            )

                        cols = 6
                        rows = IN_BOX_COUNT // cols
                        selected_slot: Optional[int] = None
                        if int(cursor_area) == 0 and 0 <= int(cursor_position) < IN_BOX_COUNT:
                            selected_slot = int(cursor_position)

                        # Header: columns A..F.
                        cell_label_width = 8
                        cell_width = 1 + cell_label_width  # marker + label
                        col_headers = []
                        for c in range(cols):
                            col_headers.append(f"{chr(ord('A') + c)}".ljust(cell_width + 1))
                        header_line = " " * 4 + "".join(col_headers).rstrip()

                        # Rows.
                        lines: List[str] = ["Grid", header_line]
                        for r in range(rows):
                            cells: List[str] = []
                            for c in range(cols):
                                slot = (r * cols) + c
                                mon = box_mons[slot] if 0 <= slot < len(box_mons) else None
                                label = "."
                                if isinstance(mon, dict):
                                    label = (
                                        str(mon.get("nickname") or "").strip()
                                        or str(mon.get("species") or "").strip()
                                        or "MON"
                                    )
                                label = label[:cell_label_width]
                                marker = "►" if (selected_slot is not None and int(slot) == int(selected_slot)) else " "
                                cells.append(f"{marker}{label:<{cell_label_width}}")
                            lines.append(f"{r + 1:<2}  " + " ".join(cells).rstrip())
                        grid_text = "\n".join(lines).strip() or None

                        # Left panel info (matches display mon in the UI for box cursor).
                        selected_mon: Optional[Dict[str, Any]] = None
                        if selected_slot is not None:
                            cand = box_mons[selected_slot]
                            if isinstance(cand, dict):
                                selected_mon = cand
                        if selected_mon is not None:
                            nick = str(selected_mon.get("nickname") or "").strip()
                            species = str(selected_mon.get("species") or "").strip()
                            lvl = selected_mon.get("level")
                            gender_sym = str(selected_mon.get("genderSymbol") or "").strip()

                            info_lines: List[str] = []
                            if nick:
                                info_lines.append(nick)
                            if species:
                                info_lines.append(f"/{species}")
                            if lvl is not None:
                                lvl_str = f"Lv{int(lvl)}"
                                info_lines.append((f"{gender_sym} {lvl_str}".strip()))
                            left_panel_text = "\n".join(info_lines).strip() or None
                        else:
                            left_panel_text = None
        except Exception:
            current_box_id = None
            current_box_name = None
            box_title_text = None
            box_mons = None
            box_mons_summary = None
            grid_text = None
            left_panel_text = None

        # sChooseBoxMenu is a pointer to a struct stored in sStorage, and is not reset to NULL when the
        # popup closes. Instead, ChooseBoxMenu_DestroySprites() clears menuSprite/menuSideSprites pointers.
        # Treat the popup as active only if menuSprite is non-null.
        choose_box_menu_active = False
        choose_box_cur_box: Optional[int] = None
        if choose_box_menu_ptr != 0:
            try:
                raw = mgba_read_range_bytes(int(choose_box_menu_ptr), 4)
                menu_sprite_ptr = int(_u32le_from(raw, 0)) if len(raw) >= 4 else 0
                if menu_sprite_ptr != 0:
                    choose_box_menu_active = True
                    try:
                        cur_raw = mgba_read_range_bytes(int(choose_box_menu_ptr) + 0x245, 1)
                        if cur_raw:
                            choose_box_cur_box = int(cur_raw[0])
                    except Exception:
                        choose_box_cur_box = None
            except Exception:
                choose_box_menu_active = False

        # WIN_MESSAGE (window 1) text is sometimes *stale* even when the message box is hidden:
        # ClearBottomWindow() clears the window tilemap/pixels but does not reset the TextPrinter pointer.
        #
        # To avoid leaking an old prompt like "... Click!" on non-dialog storage screens (e.g. deposit party selection),
        # only allow inactive TextPrinter decoding when the WIN_MESSAGE pixel buffer is non-empty.
        include_inactive_prompt = True
        message_window_visible = False
        tile_data_ptr: int = 0
        try:
            if windows_raw is not None and len(windows_raw) >= (2 * WINDOW_SIZE):
                tile_data_ptr = int(_u32le_from(windows_raw, WINDOW_SIZE + 0x08))
            else:
                tile_data_ptr = int(mgba_read32(GWINDOWS_ADDR + WINDOW_SIZE + 0x08))

            if tile_data_ptr != 0:
                if int(mgba_read8(tile_data_ptr)) == 0:
                    include_inactive_prompt = False
                    message_window_visible = False
                else:
                    message_window_visible = True
            else:
                message_window_visible = False
        except Exception:
            include_inactive_prompt = True
            message_window_visible = False

        prompt: Optional[str] = None
        if message_window_visible and storage_ptr:
            try:
                box_title_prefix: Optional[bytes] = None
                storage_base = int(mgba_read32(GPOKEMON_STORAGE_PTR_ADDR))
                if storage_base:
                    cur_box = int(mgba_read8(storage_base + POKEMON_STORAGE_CURRENT_BOX_OFFSET))
                    if 0 <= cur_box < TOTAL_BOXES_COUNT:
                        name_addr = storage_base + 0x8344 + (cur_box * 9)
                        name_raw = bytes(mgba_read_range_bytes(name_addr, 9))
                        # sStorage->boxTitleText is built via StringCopyPadded(..., c=0, BOX_NAME_LENGTH=8)
                        # so its first 9 bytes are: (name bytes pre-EOS) + padding zeros + EOS.
                        try:
                            eos_i = name_raw.index(0xFF)
                        except ValueError:
                            eos_i = -1
                        if 0 <= eos_i <= 8:
                            base = name_raw[:eos_i]
                            box_title_prefix = base + (b"\x00" * max(0, 8 - len(base))) + b"\xFF"
                        else:
                            box_title_prefix = name_raw[:9]

                message_off = _POKE_STORAGE_MESSAGE_TEXT_OFFSET
                if message_off is None and box_title_prefix is not None:
                    # Locate boxTitleText by searching for the padded current box name prefix.
                    # messageText immediately precedes it in the struct.
                    cached_title = _POKE_STORAGE_BOX_TITLE_TEXT_OFFSET
                    if cached_title is not None and cached_title >= 40:
                        _POKE_STORAGE_MESSAGE_TEXT_OFFSET = int(cached_title) - 40
                        message_off = _POKE_STORAGE_MESSAGE_TEXT_OFFSET
                    else:
                        raw_storage = mgba_read_range_bytes(int(storage_ptr), 0x8000)
                        start = 0
                        while True:
                            idx = raw_storage.find(box_title_prefix, start)
                            if idx < 0:
                                break
                            if idx >= 40:
                                _POKE_STORAGE_BOX_TITLE_TEXT_OFFSET = int(idx)
                                _POKE_STORAGE_MESSAGE_TEXT_OFFSET = int(idx) - 40
                                message_off = _POKE_STORAGE_MESSAGE_TEXT_OFFSET
                                break
                            start = idx + 1

                if message_off is not None:
                    raw_msg = mgba_read_range_bytes(int(storage_ptr) + int(message_off), 40)
                    msg = decode_gba_string(raw_msg, 200, stop_at_prompt=True).strip()
                    if msg:
                        prompt = msg
            except Exception:
                prompt = None

        if not prompt:
            prompt = get_textprinter_text_for_window(
                1,
                text_printers_raw=text_printers_raw,
                gstringvar4_raw=gstringvar4_raw,
                include_inactive=include_inactive_prompt,
            )

        # Action menu (STORE / SUMMARY / MARK / RELEASE / CANCEL, etc).
        # Note: The storage system prints menu text with TEXT_SKIP_DRAW, so TextPrinter pointers are stale.
        # We instead locate the menu items inside sStorage and decode the ROM string pointers from there.
        action_menu: Optional[Dict[str, Any]] = None
        action_menu_text: Optional[str] = None
        try:
            if smenu_raw is not None and storage_ptr:
                menu_window_id = int(_u8_from(smenu_raw, SMENU_WINDOWID_OFFSET))
                min_cursor = _s8_from_u8(int(_u8_from(smenu_raw, SMENU_MINCURSORPOS_OFFSET)))
                max_cursor = _s8_from_u8(int(_u8_from(smenu_raw, SMENU_MAXCURSORPOS_OFFSET)))
                cursor_pos = _s8_from_u8(int(_u8_from(smenu_raw, SMENU_CURSORPOS_OFFSET)))

                if (
                    menu_window_id != WINDOW_NONE
                    and 0 <= menu_window_id < 32
                    and min_cursor == 0
                    and 0 <= max_cursor <= 6
                ):
                    # Validate the referenced window is currently allocated.
                    win_bg = None
                    if windows_raw is not None and len(windows_raw) >= ((menu_window_id + 1) * WINDOW_SIZE):
                        win_bg = int(_u8_from(windows_raw, (menu_window_id * WINDOW_SIZE) + 0x00))
                    else:
                        win_bg = int(mgba_read8(GWINDOWS_ADDR + (menu_window_id * WINDOW_SIZE) + 0x00))

                    if win_bg is not None and win_bg != 0xFF:
                        # Locate the u16 menuWindowId field inside sStorage by searching for the current windowId,
                        # and validating the nearby menuWindow template (bg=0, palette=15, baseBlock=92).
                        def _find_menu_windowid_off() -> Optional[int]:
                            nonlocal storage_ptr, menu_window_id
                            global _POKE_STORAGE_MENU_WINDOWID_OFFSET

                            cached = _POKE_STORAGE_MENU_WINDOWID_OFFSET
                            if cached is not None:
                                try:
                                    raw = mgba_read_range_bytes(int(storage_ptr) + int(cached), 2)
                                    if len(raw) == 2 and int(_u16le_from(raw, 0)) == int(menu_window_id):
                                        return int(cached)
                                except Exception:
                                    pass

                            try:
                                raw_storage = mgba_read_range_bytes(int(storage_ptr), 0x4000)
                            except Exception:
                                return None

                            target = int(menu_window_id) & 0xFFFF
                            for off in range(0, len(raw_storage) - 2):
                                if int(_u16le_from(raw_storage, off)) != target:
                                    continue

                                if off < 68:
                                    continue

                                menu_items_count = int(_u8_from(raw_storage, off - 4))
                                if menu_items_count < 1 or menu_items_count > 7:
                                    continue

                                menu_unused = int(_u8_from(raw_storage, off - 2))
                                if menu_unused != 0:
                                    continue

                                # Validate the menuWindow template preceding menuItems.
                                win_off = off - 68
                                bg = int(_u8_from(raw_storage, win_off + 0x00))
                                pal = int(_u8_from(raw_storage, win_off + 0x05))
                                base_block = int(_u16le_from(raw_storage, win_off + 0x06))
                                if bg != 0 or pal != 15 or base_block != 92:
                                    continue

                                _POKE_STORAGE_MENU_WINDOWID_OFFSET = int(off)
                                return int(off)

                            return None

                        menu_windowid_off = _find_menu_windowid_off()
                        if menu_windowid_off is not None:
                            raw_header = mgba_read_range_bytes(int(storage_ptr) + (menu_windowid_off - 4), 4)
                            if len(raw_header) == 4:
                                menu_items_count = int(_u8_from(raw_header, 0))
                            else:
                                menu_items_count = 0

                            # If the current sMenu bounds don't match the sStorage menu item count, we're very likely
                            # looking at a different menu (e.g. a YES/NO prompt reusing the same window id). Avoid
                            # decoding stale action-menu contents in that case.
                            if 1 <= menu_items_count <= 7 and int(max_cursor) == (int(menu_items_count) - 1):
                                raw_items = mgba_read_range_bytes(int(storage_ptr) + (menu_windowid_off - 60), 8 * menu_items_count)
                                options: List[str] = []
                                text_ids: List[int] = []
                                for i in range(menu_items_count):
                                    base = i * 8
                                    ptr = int(_u32le_from(raw_items, base + 0))
                                    tid = int(_u32le_from(raw_items, base + 4))
                                    label = _read_gba_cstring(ptr, 64) or f"MENU_{tid}"
                                    options.append(label)
                                    text_ids.append(tid)

                                cursor = int(cursor_pos)
                                selected = options[cursor] if 0 <= cursor < len(options) else "UNKNOWN"
                                action_menu = {
                                    "type": "pokemonStorageActionMenu",
                                    "windowId": int(menu_window_id),
                                    "cursorPosition": int(cursor),
                                    "selectedOption": selected,
                                    "options": options,
                                    "textIds": text_ids,
                                }

                                menu_lines: List[str] = []
                                for i, opt in enumerate(options):
                                    prefix = "►" if i == cursor else " "
                                    menu_lines.append(f"{prefix}{opt}")
                                action_menu_text = "\n".join(menu_lines).strip() or None
        except Exception:
            action_menu = None
            action_menu_text = None

        # Party menu list (shown on several storage screens, notably DEPOSIT).
        # This is rendered outside the standard menu system, so reconstruct from gPlayerParty.
        party_slots: Optional[List[Dict[str, Any]]] = None
        party_visible_text: Optional[str] = None
        try:
            if not choose_box_menu_active and bool(in_party_menu):
                raw_party = mgba_read_range_bytes(PARTY_BASE_ADDR, PARTY_SIZE * POKEMON_DATA_SIZE)

                party_slots = []
                party_lines: List[str] = []

                option_label = {
                    0: "WITHDRAW POKéMON",
                    1: "DEPOSIT POKéMON",
                    2: "MOVE POKéMON",
                    3: "MOVE ITEMS",
                    4: "SEE YA!",
                }.get(int(current_box_option))
                if option_label:
                    party_lines.append(option_label)
                    party_lines.append("")

                for i in range(PARTY_SIZE):
                    base = int(i) * int(POKEMON_DATA_SIZE)
                    pid = int(_u32le_from(raw_party, base + PID_OFFSET))
                    is_empty = pid == 0

                    nickname = None
                    level = None
                    if not is_empty:
                        nickname_raw = raw_party[base + NICKNAME_OFFSET : base + NICKNAME_OFFSET + 10]
                        nickname = decode_gba_string(nickname_raw, 10) or f"MON_{i}"
                        level = int(_u8_from(raw_party, base + LEVEL_OFFSET))

                    party_slots.append(
                        {
                            "slot": int(i),
                            "isEmpty": bool(is_empty),
                            "nickname": nickname,
                            "level": int(level) if level is not None else None,
                        }
                    )

                    label = "(empty)" if is_empty else f"{nickname} Lv{level}"
                    prefix = "►" if (int(cursor_area) == 1 and int(cursor_position) == int(i)) else " "
                    party_lines.append(f"{prefix}{label}".rstrip())

                cancel_prefix = "►" if (int(cursor_area) == 1 and int(cursor_position) == int(PARTY_SIZE)) else " "
                party_lines.append(f"{cancel_prefix}CANCEL")

                party_visible_text = "\n".join(party_lines).strip() or None
        except Exception:
            party_slots = None
            party_visible_text = None

        choose_box: Optional[Dict[str, Any]] = None
        choose_box_text: Optional[str] = None
        box_id_for_choose = choose_box_cur_box if choose_box_cur_box is not None else deposit_box_id
        if choose_box_menu_active and 0 <= box_id_for_choose < TOTAL_BOXES_COUNT:
            storage_base = int(mgba_read32(GPOKEMON_STORAGE_PTR_ADDR))
            if storage_base:
                name_addr = storage_base + 0x8344 + (box_id_for_choose * 9)
                name_raw = mgba_read_range_bytes(name_addr, 9)
                box_name = decode_gba_string(name_raw, 9) or f"BOX{box_id_for_choose + 1}"

                box_base = storage_base + POKEMON_STORAGE_BOXES_OFFSET + (box_id_for_choose * IN_BOX_COUNT * BOX_POKEMON_SIZE)
                box_raw = mgba_read_range_bytes(box_base, IN_BOX_COUNT * BOX_POKEMON_SIZE)
                mon_count = 0
                for i in range(IN_BOX_COUNT):
                    off = (i * BOX_POKEMON_SIZE) + BOXMON_FLAGS_OFFSET
                    if off < len(box_raw):
                        flags = int(box_raw[off])
                        if ((flags >> 1) & 1) == 1:
                            mon_count += 1
                choose_box = {
                    "boxId": int(box_id_for_choose),
                    "boxName": box_name,
                    "monCount": int(mon_count),
                    "capacity": int(IN_BOX_COUNT),
                }
                choose_box_text = f"{box_name}\n{mon_count}/{IN_BOX_COUNT}"

        # Friendly cursor area labels (for tooling / debugging).
        area_label = {
            0: "box",
            1: "party",
            2: "boxTitle",
            3: "buttons",
        }.get(int(cursor_area), "unknown")

        # Storage message prompts are printed with TEXT_SKIP_DRAW, which leaves sTextPrinters[WIN_MESSAGE].currentChar stale.
        # Suppress the common "… Click!" stale PC boot text, and synthesize the "X is selected." prompt when the action menu is open.
        if prompt and "Click" in prompt:
            prompt = None
        if action_menu is not None and not prompt and int(cursor_area) == 1 and int(cursor_position) < PARTY_SIZE:
            try:
                if party_slots is not None:
                    nick = party_slots[int(cursor_position)].get("nickname")
                else:
                    base = int(cursor_position) * int(POKEMON_DATA_SIZE)
                    raw_party = mgba_read_range_bytes(PARTY_BASE_ADDR, PARTY_SIZE * POKEMON_DATA_SIZE)
                    nickname_raw = raw_party[base + NICKNAME_OFFSET : base + NICKNAME_OFFSET + 10]
                    nick = decode_gba_string(nickname_raw, 10) or None
                if nick:
                    prompt = f"{nick} is selected."
            except Exception:
                pass

        sections: List[str] = []
        if box_title_text:
            sections.append(box_title_text)

        # Top buttons ("PARTY POKéMON" / "CLOSE BOX").
        try:
            if int(cursor_area) == 3:
                party_btn = "►[PARTY POKéMON]" if int(cursor_position) == 0 else "[PARTY POKéMON]"
                close_btn = "►[CLOSE BOX]" if int(cursor_position) == 1 else "[CLOSE BOX]"
            else:
                party_btn = "[PARTY POKéMON]"
                close_btn = "[CLOSE BOX]"
            sections.append(f"{party_btn} {close_btn}".strip())
        except Exception:
            pass

        if grid_text:
            sections.append(grid_text)
        if left_panel_text:
            sections.append(left_panel_text)
        if party_visible_text:
            sections.append(party_visible_text)
        if prompt:
            sections.append(prompt)
        if action_menu_text:
            sections.append(action_menu_text)
        if choose_box_text:
            sections.append(choose_box_text)

        visible_text = "\n\n".join(sections).strip() or None

        return {
            "type": "pokemonStorage",
            "storagePtr": int(storage_ptr) if storage_ptr else None,
            "inPartyMenu": bool(in_party_menu),
            "currentBoxOption": int(current_box_option),
            "cursor": {"area": area_label, "position": int(cursor_position)},
            "currentBox": {
                "boxId": int(current_box_id) if current_box_id is not None else None,
                "boxNumber": (int(current_box_id) + 1) if current_box_id is not None else None,
                "boxName": current_box_name,
            }
            if current_box_id is not None
            else None,
            "boxMons": box_mons_summary,
            "chooseBox": choose_box,
            "partySlots": party_slots,
            "actionMenu": action_menu,
            "visibleText": visible_text,
        }
    except Exception:
        return None

def get_yes_no_menu_state(
    tasks_raw: Optional[bytes] = None,
    *,
    yesno_window_id: Optional[int] = None,
    smenu_raw: Optional[bytes] = None,
    windows_raw: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check if a YES/NO choice menu is currently displayed.
    """
    try:
        # Primary signal: task-driven yes/no menus (ScriptMenu_YesNo, DoYesNoFuncWithChoice, etc.)
        if (
            _find_active_task_by_func(TASK_HANDLE_YES_NO_INPUT_ADDR, tasks_raw) is None
            and _find_active_task_by_func(TASK_CALL_YES_OR_NO_CALLBACK_ADDR, tasks_raw) is None
        ):
            # Fallback: some yes/no prompts (e.g. START -> SAVE) do NOT create a task.
            # They simply call DisplayYesNoMenuDefaultYes() and poll Menu_ProcessInputNoWrapClearOnChoose() elsewhere.
            #
            # sYesNoWindowId alone is stale (not reset on EraseYesNoWindow), so validate that:
            # - the referenced gWindows entry is currently allocated
            # - sMenu is currently pointing at that window
            # - the menu cursor bounds match a 2-option menu
            if yesno_window_id is None:
                yesno_window_id = int(mgba_read8(SYESNO_WINDOWID_ADDR))
            if yesno_window_id == WINDOW_NONE or yesno_window_id < 0 or yesno_window_id >= 32:
                return None

            win_bg: int
            win_height: int
            if windows_raw is not None:
                win_base = int(yesno_window_id) * WINDOW_SIZE
                win_bg = int(_u8_from(windows_raw, win_base + 0x00))
                win_height = int(_u8_from(windows_raw, win_base + 0x04))
            else:
                win_base_addr = GWINDOWS_ADDR + (yesno_window_id * WINDOW_SIZE)
                win_bg = int(mgba_read8(win_base_addr + 0x00))
                win_height = int(mgba_read8(win_base_addr + 0x04))
            if win_bg == 0xFF:
                return None

            if win_height < 4:
                return None

            if smenu_raw is not None:
                menu_window_id = int(_u8_from(smenu_raw, SMENU_WINDOWID_OFFSET))
                min_cursor = _s8_from_u8(int(_u8_from(smenu_raw, SMENU_MINCURSORPOS_OFFSET)))
                max_cursor = _s8_from_u8(int(_u8_from(smenu_raw, SMENU_MAXCURSORPOS_OFFSET)))
            else:
                menu_window_id = int(mgba_read8(SMENU_ADDR + SMENU_WINDOWID_OFFSET))
                min_cursor = _s8_from_u8(int(mgba_read8(SMENU_ADDR + SMENU_MINCURSORPOS_OFFSET)))
                max_cursor = _s8_from_u8(int(mgba_read8(SMENU_ADDR + SMENU_MAXCURSORPOS_OFFSET)))
            if menu_window_id != yesno_window_id:
                return None

            if min_cursor != 0 or max_cursor != 1:
                return None

        cursor_pos = _read_menu_cursor_pos(smenu_raw)

        options = ["YES", "NO"]
        selected = options[cursor_pos] if 0 <= cursor_pos < len(options) else "UNKNOWN"

        return {"type": "yesNo", "cursorPosition": cursor_pos, "selectedOption": selected, "options": options}
    except Exception:
        return None
