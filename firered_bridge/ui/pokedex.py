from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..constants.addresses import (
    CB2_OPEN_POKEDEX_ADDR,
    CB2_POKEDEX_ADDR,
    GPOKEDEXENTRIES_ADDR,
    GTASKS_ADDR,
    GTEXT_5MARKS_POKEMON_ADDR,
    GTEXT_HT_HEIGHT_ADDR,
    GTEXT_WT_WEIGHT_ADDR,
    NUM_TASKS,
    SPOKEDEXVIEW_PTR_ADDR,
    TASK_DEXSCREEN_CATEGORY_SUBMENU_ADDR,
    TASK_DEXSCREEN_CHARACTERISTIC_ORDER_ADDR,
    TASK_DEXSCREEN_NUMERICAL_ORDER_ADDR,
    TASK_DEXSCREEN_REGISTER_MON_TO_POKEDEX_ADDR,
    TASK_DEXSCREEN_REGISTER_NON_KANTO_MON_ADDR,
    TASK_DEXSCREEN_SHOW_MON_PAGE_ADDR,
    TASK_FUNC_OFFSET,
    TASK_ISACTIVE_OFFSET,
    TASK_POKEDEX_SCREEN_ADDR,
    TASK_SIZE,
)
from ..game_data import get_species_name
from ..memory import mgba
from ..player import save as player_save
from ..text.encoding import decode_gba_string
from ..util.bytes import _u16le_from, _u32le_from, _u8_from

# =============================================================================
# Pokédex UI extraction (pokefirered/src/pokedex_screen.c)
# =============================================================================

# struct PokedexScreenData sizeof = 0x70 in FireRed.
_POKEDEX_SCREEN_DATA_SIZE = 0x70

# struct PokedexScreenData offsets (pokefirered/src/pokedex_screen.c)
_OFF_TASK_ID = 0x00
_OFF_STATE = 0x01
_OFF_DATA0 = 0x02
_OFF_DATA1 = 0x03
_OFF_MODE_SELECT_INPUT = 0x0C  # u32
_OFF_PAGE_SPECIES = 0x18  # u16 pageSpecies[4]
_OFF_CATEGORY = 0x28
_OFF_FIRST_PAGE_IN_CATEGORY = 0x29
_OFF_LAST_PAGE_IN_CATEGORY = 0x2A
_OFF_PAGE_NUM = 0x2B
_OFF_NUM_MONS_ON_PAGE = 0x2C
_OFF_CATEGORY_CURSOR_POS_IN_PAGE = 0x2D
_OFF_CHARACTERISTIC_MENU_INPUT = 0x30  # u32
_OFF_KANTO_ORDER_ITEMS_ABOVE = 0x34
_OFF_KANTO_ORDER_CURSOR_POS = 0x36
_OFF_CHARACTERISTIC_ORDER_ITEMS_ABOVE = 0x38
_OFF_CHARACTERISTIC_ORDER_CURSOR_POS = 0x3A
_OFF_NATIONAL_ORDER_ITEMS_ABOVE = 0x3C
_OFF_NATIONAL_ORDER_CURSOR_POS = 0x3E
_OFF_DEX_ORDER_ID = 0x42
_OFF_ORDERED_DEX_COUNT = 0x48
_OFF_DEX_SPECIES = 0x5A
_OFF_NUM_SEEN_KANTO = 0x66
_OFF_NUM_OWNED_KANTO = 0x68
_OFF_NUM_SEEN_NATIONAL = 0x6A
_OFF_NUM_OWNED_NATIONAL = 0x6C

# include/pokedex_screen.h
_DEX_CATEGORY_NAMES = {
    0: "GRASSLAND",
    1: "FOREST",
    2: "WATERS EDGE",
    3: "SEA",
    4: "CAVE",
    5: "MOUNTAIN",
    6: "ROUGH TERRAIN",
    7: "URBAN",
    8: "RARE",
}

_DEX_ORDER_NAMES = {
    0: "NUMERICAL (KANTO)",
    1: "A TO Z",
    2: "TYPE",
    3: "LIGHTEST",
    4: "SMALLEST",
    5: "NUMERICAL (NATIONAL)",
}


def _mask_thumb(ptr: int) -> int:
    return int(ptr) & 0xFFFFFFFE


def _read_gba_cstring(ptr: int, max_len: int = 96) -> str:
    if int(ptr) == 0:
        return ""
    try:
        raw = mgba.mgba_read_range_bytes(int(ptr), int(max_len))
        return decode_gba_string(raw, max_len) or ""
    except Exception:
        return ""


def _read_game_text(ptr: int, max_len: int = 200) -> str:
    return _read_gba_cstring(int(ptr), int(max_len))


def _format_no(num: int) -> str:
    n = max(0, int(num))
    return f"No{n:03d}"


def _format_height_imperial(height_dm: int) -> str:
    try:
        h = int(height_dm)
        if h <= 0:
            return ""
        inches_x100 = (h * 10000) // 254
        if (inches_x100 % 10) >= 5:
            inches_x100 += 10
        feet = inches_x100 // 120
        inches = (inches_x100 - (feet * 120)) // 10
        return f"{int(feet)}'{int(inches):02d}\""
    except Exception:
        return ""


def _format_weight_lbs(weight_hg: int) -> str:
    try:
        w = int(weight_hg)
        if w <= 0:
            return ""
        lbs_x100 = (w * 100000) // 4536
        if (lbs_x100 % 10) >= 5:
            lbs_x100 += 10
        lbs_x10 = lbs_x100 // 10
        whole = lbs_x10 // 10
        tenths = lbs_x10 % 10
        return f"{int(whole)}.{int(tenths)} lbs."
    except Exception:
        return ""


def _read_tasks_raw(tasks_raw: Optional[bytes]) -> Optional[bytes]:
    if tasks_raw is not None:
        return tasks_raw
    try:
        return mgba.mgba_read_range_bytes(GTASKS_ADDR, NUM_TASKS * TASK_SIZE)
    except Exception:
        return None


def _task_func_for_id(task_id: int, tasks_raw: Optional[bytes]) -> Optional[int]:
    raw = _read_tasks_raw(tasks_raw)
    if raw is None:
        return None
    try:
        tid = int(task_id)
        if tid < 0 or tid >= int(NUM_TASKS):
            return None
        base = tid * TASK_SIZE
        if (base + TASK_SIZE) > len(raw):
            return None
        if int(_u8_from(raw, base + TASK_ISACTIVE_OFFSET)) == 0:
            return None
        return int(_u32le_from(raw, base + TASK_FUNC_OFFSET))
    except Exception:
        return None


def _task_kind(task_func: Optional[int]) -> str:
    if task_func is None:
        return "unknown"
    func = _mask_thumb(int(task_func))

    if int(TASK_POKEDEX_SCREEN_ADDR) != 0 and func == _mask_thumb(int(TASK_POKEDEX_SCREEN_ADDR)):
        return "topMenu"
    if int(TASK_DEXSCREEN_NUMERICAL_ORDER_ADDR) != 0 and func == _mask_thumb(int(TASK_DEXSCREEN_NUMERICAL_ORDER_ADDR)):
        return "orderedList"
    if int(TASK_DEXSCREEN_CHARACTERISTIC_ORDER_ADDR) != 0 and func == _mask_thumb(int(TASK_DEXSCREEN_CHARACTERISTIC_ORDER_ADDR)):
        return "orderedList"
    if int(TASK_DEXSCREEN_CATEGORY_SUBMENU_ADDR) != 0 and func == _mask_thumb(int(TASK_DEXSCREEN_CATEGORY_SUBMENU_ADDR)):
        return "category"
    if int(TASK_DEXSCREEN_SHOW_MON_PAGE_ADDR) != 0 and func == _mask_thumb(int(TASK_DEXSCREEN_SHOW_MON_PAGE_ADDR)):
        return "monPage"

    reg_candidates = {
        _mask_thumb(int(addr))
        for addr in (TASK_DEXSCREEN_REGISTER_NON_KANTO_MON_ADDR, TASK_DEXSCREEN_REGISTER_MON_TO_POKEDEX_ADDR)
        if int(addr) != 0
    }
    if func in reg_candidates:
        return "registering"

    return "unknown"


def _read_selected_species_from_struct(view_raw: bytes) -> Optional[int]:
    try:
        # ordered list path: low 16 bits of characteristicMenuInput stores species id.
        ch_input = int(_u32le_from(view_raw, _OFF_CHARACTERISTIC_MENU_INPUT))
        species = int(ch_input & 0xFFFF)
        if 1 <= species <= 411:
            return species
    except Exception:
        pass

    try:
        species = int(_u16le_from(view_raw, _OFF_DEX_SPECIES))
        if 1 <= species <= 411:
            return species
    except Exception:
        pass

    return None


def _selected_summary(species: Optional[int], *, dex_order_id: int) -> Optional[Dict[str, Any]]:
    if species is None:
        return None
    try:
        sid = int(species)
        if sid <= 0:
            return None
        nat = int(player_save.get_national_pokedex_num(sid) or 0)
        if int(dex_order_id) == 0:
            disp = int(player_save.get_kanto_dex_num_from_national(nat) or 0)
        elif int(dex_order_id) == 5:
            disp = nat
        else:
            # Search orders still point to National species ids.
            disp = nat

        return {
            "speciesId": int(sid),
            "name": get_species_name(int(sid)) or None,
            "nationalDex": int(nat),
            "displayDex": int(disp),
        }
    except Exception:
        return None


def _build_mon_info_text(species: Optional[int]) -> str:
    if species is None:
        return "POKEDEX"

    sid = int(species)
    if sid <= 0:
        return "POKEDEX"

    nat = int(player_save.get_national_pokedex_num(sid) or 0)
    name = get_species_name(sid) or "POKEMON"

    if nat <= 0 or int(GPOKEDEXENTRIES_ADDR) == 0:
        return f"{_format_no(nat)} {name}".strip()

    try:
        entry_raw = mgba.mgba_read_range_bytes(int(GPOKEDEXENTRIES_ADDR) + (int(nat) * 0x20), 0x20)
    except Exception:
        entry_raw = b""

    category = ""
    height_text = ""
    weight_text = ""
    description = ""

    if len(entry_raw) >= 0x20:
        category_raw = entry_raw[0x00:0x0C]
        height_dm = int(_u16le_from(entry_raw, 0x0C))
        weight_hg = int(_u16le_from(entry_raw, 0x0E))
        desc_ptr = int(_u32le_from(entry_raw, 0x10))

        category_name = decode_gba_string(category_raw, 12) or ""
        if category_name:
            category = f"{category_name} POKEMON"
        else:
            category = _read_game_text(GTEXT_5MARKS_POKEMON_ADDR, 64) or "----- POKEMON"

        height_text = _format_height_imperial(height_dm)
        weight_text = _format_weight_lbs(weight_hg)
        if desc_ptr:
            description = _read_game_text(desc_ptr, 240)

    ht_label = _read_game_text(GTEXT_HT_HEIGHT_ADDR, 8) or "HT"
    wt_label = _read_game_text(GTEXT_WT_WEIGHT_ADDR, 8) or "WT"

    lines = [f"{_format_no(nat)} {name}"]
    if category:
        lines.append(category)
    if height_text:
        lines.append(f"{ht_label} {height_text}".strip())
    if weight_text:
        lines.append(f"{wt_label} {weight_text}".strip())
    if description:
        lines.extend(["", description])
    return "\n".join(lines).strip()


def _build_category_choice_menu(view_raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        num = int(_u8_from(view_raw, _OFF_NUM_MONS_ON_PAGE))
        if num <= 0:
            return None
        num = min(num, 4)

        cursor = int(_u8_from(view_raw, _OFF_CATEGORY_CURSOR_POS_IN_PAGE))
        cursor = max(0, min(cursor, num - 1))

        options: List[str] = []
        for i in range(num):
            species = int(_u16le_from(view_raw, _OFF_PAGE_SPECIES + (i * 2)))
            if species <= 0 or species == 0xFFFF:
                options.append("-")
                continue
            name = get_species_name(species) or f"SPECIES_{species}"
            nat = int(player_save.get_national_pokedex_num(species) or 0)
            options.append(f"{_format_no(nat)} {name}".strip())

        return {
            "type": "pokedexCategoryPage",
            "cursorPosition": int(cursor),
            "selectedOption": options[int(cursor)] if 0 <= int(cursor) < len(options) else None,
            "options": options,
        }
    except Exception:
        return None


def get_pokedex_state(
    callback2: int,
    *,
    tasks_raw: Optional[bytes] = None,
    sb1_ptr: Optional[int] = None,
    sb2_ptr: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect FireRed Pokédex UI state and produce a stable, bridge-friendly summary.
    """
    try:
        cb2 = _mask_thumb(int(callback2))
        cb2_candidates = {
            _mask_thumb(int(addr))
            for addr in (CB2_POKEDEX_ADDR, CB2_OPEN_POKEDEX_ADDR)
            if int(addr) != 0
        }
        if not cb2_candidates or cb2 not in cb2_candidates:
            return None

        view_ptr = int(mgba.mgba_read32(SPOKEDEXVIEW_PTR_ADDR))
        if view_ptr == 0:
            return {
                "screen": "loading",
                "currentPage": "loading",
                "visibleText": "POKEDEX",
                "choiceMenu": None,
            }

        view_raw = mgba.mgba_read_range_bytes(view_ptr, _POKEDEX_SCREEN_DATA_SIZE)
        if not view_raw or len(view_raw) < _POKEDEX_SCREEN_DATA_SIZE:
            return {
                "screen": "loading",
                "currentPage": "loading",
                "visibleText": "POKEDEX",
                "choiceMenu": None,
            }

        task_id = int(_u8_from(view_raw, _OFF_TASK_ID))
        state = int(_u8_from(view_raw, _OFF_STATE))
        data0 = int(_u8_from(view_raw, _OFF_DATA0))
        data1 = int(_u8_from(view_raw, _OFF_DATA1))
        mode_select_input = int(_u32le_from(view_raw, _OFF_MODE_SELECT_INPUT))

        category = int(_u8_from(view_raw, _OFF_CATEGORY))
        first_page_in_category = int(_u8_from(view_raw, _OFF_FIRST_PAGE_IN_CATEGORY))
        last_page_in_category = int(_u8_from(view_raw, _OFF_LAST_PAGE_IN_CATEGORY))
        page_num = int(_u8_from(view_raw, _OFF_PAGE_NUM))
        num_mons_on_page = int(_u8_from(view_raw, _OFF_NUM_MONS_ON_PAGE))
        category_cursor = int(_u8_from(view_raw, _OFF_CATEGORY_CURSOR_POS_IN_PAGE))

        dex_order_id = int(_u8_from(view_raw, _OFF_DEX_ORDER_ID))
        ordered_dex_count = int(_u16le_from(view_raw, _OFF_ORDERED_DEX_COUNT))

        kanto_items_above = int(_u16le_from(view_raw, _OFF_KANTO_ORDER_ITEMS_ABOVE))
        kanto_cursor_pos = int(_u16le_from(view_raw, _OFF_KANTO_ORDER_CURSOR_POS))
        characteristic_items_above = int(_u16le_from(view_raw, _OFF_CHARACTERISTIC_ORDER_ITEMS_ABOVE))
        characteristic_cursor_pos = int(_u16le_from(view_raw, _OFF_CHARACTERISTIC_ORDER_CURSOR_POS))
        national_items_above = int(_u16le_from(view_raw, _OFF_NATIONAL_ORDER_ITEMS_ABOVE))
        national_cursor_pos = int(_u16le_from(view_raw, _OFF_NATIONAL_ORDER_CURSOR_POS))

        seen_kanto = int(_u16le_from(view_raw, _OFF_NUM_SEEN_KANTO))
        owned_kanto = int(_u16le_from(view_raw, _OFF_NUM_OWNED_KANTO))
        seen_national = int(_u16le_from(view_raw, _OFF_NUM_SEEN_NATIONAL))
        owned_national = int(_u16le_from(view_raw, _OFF_NUM_OWNED_NATIONAL))

        task_func = _task_func_for_id(task_id, tasks_raw)
        task_kind = _task_kind(task_func)

        nat_enabled = False
        try:
            nat_enabled = bool(
                player_save._is_national_dex_enabled(
                    int(sb1_ptr) if sb1_ptr is not None else int(mgba.mgba_read32(player_save.GSAVEBLOCK1_PTR_ADDR)),
                    int(sb2_ptr) if sb2_ptr is not None else int(mgba.mgba_read32(player_save.GSAVEBLOCK2_PTR_ADDR)),
                )
            )
        except Exception:
            nat_enabled = bool(seen_national or owned_national)

        selected_species: Optional[int] = None
        if task_kind == "category" and state < 14 and num_mons_on_page > 0:
            idx = max(0, min(int(category_cursor), max(0, int(num_mons_on_page) - 1)))
            sp = int(_u16le_from(view_raw, _OFF_PAGE_SPECIES + (idx * 2)))
            if 1 <= sp <= 411 and sp != 0xFFFF:
                selected_species = sp

        if selected_species is None:
            selected_species = _read_selected_species_from_struct(view_raw)

        selected = _selected_summary(selected_species, dex_order_id=dex_order_id)

        base: Dict[str, Any] = {
            "screen": task_kind,
            "currentPage": task_kind,
            "task": {
                "id": int(task_id),
                "state": int(state),
                "data": [int(data0), int(data1)],
                "func": _mask_thumb(int(task_func)) if task_func is not None else None,
                "kind": task_kind,
            },
            "dexMode": "NATIONAL" if nat_enabled else "KANTO",
            "dexOrder": _DEX_ORDER_NAMES.get(int(dex_order_id), f"ORDER_{int(dex_order_id)}"),
            "counts": {
                "seenKanto": int(seen_kanto),
                "ownedKanto": int(owned_kanto),
                "seenNational": int(seen_national),
                "ownedNational": int(owned_national),
            },
            "selected": selected,
        }

        choice_menu: Optional[Dict[str, Any]] = None
        lines: List[str] = ["POKEDEX"]

        if task_kind == "topMenu":
            lines.append("TOP MENU")
            lines.append(f"SEEN  KANTO: {seen_kanto:3d}   OWNED KANTO: {owned_kanto:3d}")
            if nat_enabled:
                lines.append(f"SEEN  NAT. : {seen_national:3d}   OWNED NAT. : {owned_national:3d}")

            # modeSelectInput stores a selected item id only when A is pressed.
            if int(mode_select_input) <= 64:
                lines.append(f"SELECT INPUT: {int(mode_select_input)}")

        elif task_kind == "orderedList":
            lines.append("POKEMON LIST")
            lines.append(f"ORDER: {_DEX_ORDER_NAMES.get(int(dex_order_id), f'ORDER_{int(dex_order_id)}')}")
            lines.append(f"VISIBLE COUNT: {ordered_dex_count}")

            if int(dex_order_id) == 0:
                selected_idx = int(kanto_items_above) + int(kanto_cursor_pos)
            elif int(dex_order_id) == 5:
                selected_idx = int(national_items_above) + int(national_cursor_pos)
            else:
                selected_idx = int(characteristic_items_above) + int(characteristic_cursor_pos)
            lines.append(f"CURSOR: {max(0, selected_idx) + 1}/{max(1, int(ordered_dex_count))}")

            if isinstance(selected, dict):
                lines.append("")
                lines.append(f"{_format_no(int(selected.get('displayDex') or 0))} {selected.get('name') or 'POKEMON'}")

        elif task_kind == "category":
            # In Task_DexScreen_CategorySubmenu, states >=14 are mon data/area pages.
            if int(state) >= 14:
                sub_page = "area" if 21 <= int(state) <= 26 else "data"
                lines.append("POKEMON DATA" if sub_page == "data" else "POKEMON AREA")
                lines.append(_build_mon_info_text(selected_species))
                base["currentPage"] = sub_page
            else:
                cat_name = _DEX_CATEGORY_NAMES.get(int(category), f"CATEGORY_{int(category)}")
                total_pages = max(0, int(last_page_in_category) - int(first_page_in_category))
                page_display = (int(page_num) - int(first_page_in_category) + 1) if total_pages > 0 else 0

                lines.append(f"CATEGORY: {cat_name}")
                lines.append(f"PAGE: {max(0, page_display)}/{max(1, total_pages)}")

                choice_menu = _build_category_choice_menu(view_raw)
                if choice_menu and isinstance(choice_menu.get("options"), list):
                    lines.append("")
                    cursor = int(choice_menu.get("cursorPosition", 0) or 0)
                    for i, opt in enumerate(choice_menu["options"]):
                        prefix = "►" if i == cursor else " "
                        lines.append(f"{prefix}{opt}")

        elif task_kind == "monPage":
            # In Task_DexScreen_ShowMonPage, states 7..12 correspond to area page flow.
            sub_page = "area" if 7 <= int(state) <= 12 else "data"
            base["currentPage"] = sub_page
            lines.append("POKEMON DATA" if sub_page == "data" else "POKEMON AREA")
            lines.append(_build_mon_info_text(selected_species))

        elif task_kind == "registering":
            lines.append("REGISTERING POKEMON")
            if isinstance(selected, dict):
                lines.append(f"{_format_no(int(selected.get('nationalDex') or 0))} {selected.get('name') or 'POKEMON'}")

        else:
            lines.append("LOADING")

        return {
            **base,
            "visibleText": "\n".join([ln for ln in lines if isinstance(ln, str) and ln]).strip() or "POKEDEX",
            "choiceMenu": choice_menu,
        }

    except Exception:
        return None
