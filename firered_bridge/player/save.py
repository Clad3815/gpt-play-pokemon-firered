from __future__ import annotations

import logging
import os
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from ..constants.addresses import (
    CURRENT_MAP_HEADER_ADDR,
    FLAG_BADGE01,
    FLAG_SYS_NATIONAL_DEX,
    FLAG_SYS_POKEDEX_GET,
    GSAVEBLOCK1_PTR_ADDR,
    GSAVEBLOCK2_PTR_ADDR,
    GTEXT_FERRY_ADDR,
    MAP_HEADER_REGION_MAP_SECTION_ID_OFFSET,
    MAPSEC_DYNAMIC,
    KANTO_DEX_COUNT,
    NATIONAL_DEX_COUNT,
    NATIONAL_DEX_VAR_VALUE,
    NATIONAL_MAGIC_VALUE,
    NUM_BADGES,
    NUM_DEX_FLAG_BYTES,
    POKEDEX_NATIONAL_MAGIC_OFFSET,
    POKEDEX_OWNED_OFFSET,
    SB1_FLAGS_OFFSET,
    SB1_VARS_OFFSET,
    SB2_POKEDEX_OFFSET,
    SB2_PLAYER_NAME_OFFSET,
    SB2_PLAY_TIME_HOURS_OFFSET,
    SB2_PLAY_TIME_MINUTES_OFFSET,
    SSPECIES_TO_NATIONAL_POKEDEX_NUM_ADDR,
    SSPECIES_TO_NATIONAL_POKEDEX_NUM_SIZE,
    SSAVE_INFO_WINDOWID_ADDR,
    VARS_START,
    VAR_NATIONAL_DEX,
    WINDOW_NONE,
    WINDOW_SIZE,
    GWINDOWS_ADDR,
)
from ..memory import mgba
from ..text import encoding as text_encoding

_BENCH_LOGGER = logging.getLogger("firered_bridge.bench")
_SAVEINFO_DEBUG = os.getenv(
    "FIRERED_BRIDGE_DEBUG_SAVE_INFO",
    "",
).strip() not in ("", "0", "false", "False")


def _flag_get_from_sb1(sb1_ptr: int, flag_id: int) -> bool:
    if sb1_ptr == 0 or flag_id <= 0:
        return False
    try:
        flags_base = sb1_ptr + SB1_FLAGS_OFFSET
        byte_offset = int(flag_id) // 8
        bit_offset = int(flag_id) % 8
        flag_byte = int(mgba.mgba_read8(flags_base + byte_offset))
        return ((flag_byte >> bit_offset) & 1) == 1
    except Exception:
        return False


def _var_get_from_sb1(sb1_ptr: int, var_id: int) -> int:
    if sb1_ptr == 0:
        return int(var_id)
    if var_id < VARS_START:
        return int(var_id)
    try:
        idx = int(var_id) - VARS_START
        return int(mgba.mgba_read16(sb1_ptr + SB1_VARS_OFFSET + (idx * 2)))
    except Exception:
        return int(var_id)


def _is_national_dex_enabled(sb1_ptr: int, sb2_ptr: int) -> bool:
    """
    Mirror pokefirered/src/event_data.c:IsNationalPokedexEnabled().
    """
    try:
        if sb1_ptr == 0 or sb2_ptr == 0:
            return False

        magic = int(mgba.mgba_read8(sb2_ptr + SB2_POKEDEX_OFFSET + POKEDEX_NATIONAL_MAGIC_OFFSET))
        if magic != NATIONAL_MAGIC_VALUE:
            return False

        if _var_get_from_sb1(sb1_ptr, VAR_NATIONAL_DEX) != NATIONAL_DEX_VAR_VALUE:
            return False

        return _flag_get_from_sb1(sb1_ptr, FLAG_SYS_NATIONAL_DEX)
    except Exception:
        return False


_SPECIES_TO_NATIONAL_POKEDEX_NUM_TABLE: Optional[List[int]] = None


def _get_species_to_national_pokedex_num_table() -> List[int]:
    global _SPECIES_TO_NATIONAL_POKEDEX_NUM_TABLE
    if _SPECIES_TO_NATIONAL_POKEDEX_NUM_TABLE is not None:
        return _SPECIES_TO_NATIONAL_POKEDEX_NUM_TABLE
    raw = mgba.mgba_read_range_bytes(SSPECIES_TO_NATIONAL_POKEDEX_NUM_ADDR, SSPECIES_TO_NATIONAL_POKEDEX_NUM_SIZE)
    table: List[int] = []
    for off in range(0, len(raw), 2):
        if off + 1 >= len(raw):
            break
        table.append(int.from_bytes(raw[off : off + 2], "little"))
    _SPECIES_TO_NATIONAL_POKEDEX_NUM_TABLE = table
    return table


def get_national_pokedex_num(species_id: int) -> int:
    """
    Convert internal FireRed SPECIES_* id to National Dex number (for sprites / UI).

    Mirrors pokefirered/src/pokemon.c:SpeciesToNationalPokedexNum() by reading
    the sSpeciesToNationalPokedexNum table from emulator memory (ROM region).
    """
    try:
        sid = int(species_id)
        if sid <= 0:
            return 0
        table = _get_species_to_national_pokedex_num_table()
        idx = sid - 1
        if 0 <= idx < len(table):
            return int(table[idx])
        return 0
    except Exception:
        return 0


_NATIONAL_DEX_TO_SPECIES_ID_TABLE: Optional[Dict[int, int]] = None


def _get_national_dex_to_species_id_table() -> Dict[int, int]:
    global _NATIONAL_DEX_TO_SPECIES_ID_TABLE
    if _NATIONAL_DEX_TO_SPECIES_ID_TABLE is not None:
        return _NATIONAL_DEX_TO_SPECIES_ID_TABLE

    table: Dict[int, int] = {}
    for species_id, nat in enumerate(_get_species_to_national_pokedex_num_table(), start=1):
        nat_i = int(nat)
        if nat_i <= 0:
            continue
        table[nat_i] = int(species_id)

    _NATIONAL_DEX_TO_SPECIES_ID_TABLE = table
    return table


def get_species_id_for_national_dex(national_dex_no: int) -> int:
    """
    Best-effort conversion from National Dex number -> internal SPECIES_* id.

    Mirrors pokefirered/src/pokemon.c:NationalPokedexNumToSpecies(), but uses a cached inverse
    of the ROM table sSpeciesToNationalPokedexNum for speed.
    """
    try:
        nd = int(national_dex_no)
        if nd <= 0:
            return 0
        return int(_get_national_dex_to_species_id_table().get(nd, 0))
    except Exception:
        return 0


def get_kanto_dex_num_from_national(national_dex_no: int) -> int:
    """
    Convert National Dex number -> Kanto Dex number used by FireRed local mode.

    FireRed local dex is the first 151 National entries, so the conversion is
    identity in range [1..KANTO_DEX_COUNT], otherwise 0.
    """
    try:
        nd = int(national_dex_no)
        if 1 <= nd <= int(KANTO_DEX_COUNT):
            return nd
        return 0
    except Exception:
        return 0


_MAPSEC_NAME_CACHE: Dict[int, str] = {}
_MAPSEC_NAMES_FROM_REPO: Optional[List[str]] = None


def _load_repo_mapsec_names() -> List[str]:
    global _MAPSEC_NAMES_FROM_REPO
    if _MAPSEC_NAMES_FROM_REPO is not None:
        return _MAPSEC_NAMES_FROM_REPO

    candidates = [
        Path(__file__).resolve().parents[2] / "pokefirered" / "src" / "data" / "region_map" / "region_map_sections.json",
    ]

    for path in candidates:
        try:
            raw = path.read_text("utf-8")
            data = json.loads(raw)
            sections = data.get("map_sections")
            if not isinstance(sections, list):
                continue
            names: List[str] = []
            for sec in sections:
                if isinstance(sec, dict):
                    nm = sec.get("name")
                    names.append(str(nm) if isinstance(nm, str) else "")
                else:
                    names.append("")
            if names:
                _MAPSEC_NAMES_FROM_REPO = names
                return _MAPSEC_NAMES_FROM_REPO
        except Exception:
            continue

    _MAPSEC_NAMES_FROM_REPO = []
    return _MAPSEC_NAMES_FROM_REPO


def _decode_gba_string_from_bytes(raw: bytes, max_len: int) -> str:
    if not raw:
        return ""
    return text_encoding.decode_gba_string(raw, max_len) or ""


def _read_gba_cstring_bytes(addr: int, max_len: int = 64) -> str:
    if addr == 0:
        return ""
    try:
        raw = mgba.mgba_read_range_bytes(int(addr), int(max_len))
        return _decode_gba_string_from_bytes(raw, max_len)
    except Exception:
        return ""


def _get_mapsec_display_name(mapsec_id: int) -> str:
    try:
        cached = _MAPSEC_NAME_CACHE.get(int(mapsec_id))
        if cached is not None:
            return cached
        if mapsec_id == MAPSEC_DYNAMIC:
            name = _read_gba_cstring_bytes(GTEXT_FERRY_ADDR, 32) or "FERRY"
            _MAPSEC_NAME_CACHE[int(mapsec_id)] = name
            return name
        if mapsec_id < 0:
            return ""

        # FireRed fallback: load map section display names from repo JSON data.
        names = _load_repo_mapsec_names()
        idx = int(mapsec_id)
        if 0 <= idx < len(names):
            name = str(names[idx] or "")
            if name:
                _MAPSEC_NAME_CACHE[idx] = name
            return name
        return ""
    except Exception:
        return ""


def _get_pokedex_caught_count(sb1_ptr: int, sb2_ptr: int) -> Optional[int]:
    if sb1_ptr == 0 or sb2_ptr == 0:
        return None
    if not _flag_get_from_sb1(sb1_ptr, FLAG_SYS_POKEDEX_GET):
        return None

    owned = mgba.mgba_read_range(sb2_ptr + SB2_POKEDEX_OFFSET + POKEDEX_OWNED_OFFSET, NUM_DEX_FLAG_BYTES)
    if not owned:
        return None

    def is_owned(national_dex_no: int) -> bool:
        if national_dex_no <= 0:
            return False
        bit_idx = national_dex_no - 1
        byte_idx = bit_idx // 8
        if byte_idx < 0 or byte_idx >= len(owned):
            return False
        mask = 1 << (bit_idx % 8)
        return (int(owned[byte_idx]) & mask) != 0

    if _is_national_dex_enabled(sb1_ptr, sb2_ptr):
        total = 0
        full_bytes = NATIONAL_DEX_COUNT // 8
        partial_bits = NATIONAL_DEX_COUNT % 8
        for b in owned[:full_bytes]:
            total += int(b).bit_count()
        if partial_bits and full_bytes < len(owned):
            total += (int(owned[full_bytes]) & ((1 << partial_bits) - 1)).bit_count()
        return total

    # FireRed local mode is Kanto dex (1..151).
    local_count = int(KANTO_DEX_COUNT)
    if local_count <= 0:
        return None

    total = 0
    full_bytes = local_count // 8
    partial_bits = local_count % 8
    for b in owned[:full_bytes]:
        total += int(b).bit_count()
    if partial_bits and full_bytes < len(owned):
        total += (int(owned[full_bytes]) & ((1 << partial_bits) - 1)).bit_count()
    return total


def get_save_info_window_state() -> Optional[Dict[str, Any]]:
    """
    Detect and extract the START -> SAVE info window (location / player / badges / pokedex / time).

    This window is drawn by ShowSaveInfoWindow() in pokefirered/src/start_menu.c and remains visible
    during the save YES/NO prompt.
    """
    t0 = perf_counter()
    m0 = mgba._mgba_metrics()
    m0_counts = (
        (m0.read8_calls, m0.read16_calls, m0.read32_calls, m0.read_range_calls, m0.read_ranges_calls, m0.read_range_bytes_calls, m0.read_ranges_bytes_calls)
        if m0 is not None
        else None
    )
    try:
        if SSAVE_INFO_WINDOWID_ADDR == 0:
            return None

        fixed_ranges = [
            (SSAVE_INFO_WINDOWID_ADDR, 1),
            (GWINDOWS_ADDR, 32 * WINDOW_SIZE),
            (GSAVEBLOCK1_PTR_ADDR, 4),
            (GSAVEBLOCK2_PTR_ADDR, 4),
            (CURRENT_MAP_HEADER_ADDR + MAP_HEADER_REGION_MAP_SECTION_ID_OFFSET, 1),
        ]

        fixed = mgba._try_mgba_read_ranges_bytes_no_fallback(fixed_ranges)
        if fixed is None:
            # Slow/test fallback: use patchable per-read functions.
            window_id = int(mgba.mgba_read8(SSAVE_INFO_WINDOWID_ADDR))
            if window_id == WINDOW_NONE or window_id < 0 or window_id >= 32:
                return None

            win_base = GWINDOWS_ADDR + (window_id * WINDOW_SIZE)
            bg = int(mgba.mgba_read8(win_base + 0x00))
            if bg == 0xFF:
                return None

            width = int(mgba.mgba_read8(win_base + 0x03))
            height = int(mgba.mgba_read8(win_base + 0x04))
            left = int(mgba.mgba_read8(win_base + 0x01))
            top = int(mgba.mgba_read8(win_base + 0x02))

            # Save info window template: bg=0, left=1, top=1, width=14, height=8..10 (pokedex hidden reduces height by 2).
            if bg != 0 or width != 14 or left != 1 or top != 1 or height < 8:
                return None

            sb1_ptr = int(mgba.mgba_read32(GSAVEBLOCK1_PTR_ADDR))
            sb2_ptr = int(mgba.mgba_read32(GSAVEBLOCK2_PTR_ADDR))
            if sb1_ptr == 0 or sb2_ptr == 0:
                return None

            mapsec_id = int(mgba.mgba_read8(CURRENT_MAP_HEADER_ADDR + MAP_HEADER_REGION_MAP_SECTION_ID_OFFSET))
            location = _get_mapsec_display_name(mapsec_id)

            player_name = (
                text_encoding.decode_gba_string(mgba.mgba_read_range_bytes(sb2_ptr + SB2_PLAYER_NAME_OFFSET, 8), 8)
                or "PLAYER"
            )

            badge_count = 0
            for i in range(NUM_BADGES):
                if _flag_get_from_sb1(sb1_ptr, FLAG_BADGE01 + i):
                    badge_count += 1

            play_hours = int(mgba.mgba_read16(sb2_ptr + SB2_PLAY_TIME_HOURS_OFFSET))
            play_minutes = int(mgba.mgba_read8(sb2_ptr + SB2_PLAY_TIME_MINUTES_OFFSET))
            play_time = f"{play_hours}:{play_minutes:02d}"

            pokedex_caught = _get_pokedex_caught_count(sb1_ptr, sb2_ptr)
            nat_enabled = pokedex_caught is not None and _is_national_dex_enabled(sb1_ptr, sb2_ptr)
            dex_mode = "national" if nat_enabled else ("kanto" if pokedex_caught is not None else "none")
        else:
            # Fast path: bulk-read fixed addresses and then bulk-read saveblock slices.
            if not fixed or len(fixed) < len(fixed_ranges):
                return None

            window_id = int(fixed[0][0]) if fixed[0] else WINDOW_NONE
            if window_id == WINDOW_NONE or window_id < 0 or window_id >= 32:
                return None

            windows_raw = fixed[1] or b""
            win_off = int(window_id) * int(WINDOW_SIZE)
            if win_off < 0 or (win_off + WINDOW_SIZE) > len(windows_raw):
                return None
            win = windows_raw[win_off : win_off + WINDOW_SIZE]

            bg = int(win[0]) if len(win) > 0 else 0xFF
            if bg == 0xFF:
                return None

            left = int(win[1]) if len(win) > 1 else 0
            top = int(win[2]) if len(win) > 2 else 0
            width = int(win[3]) if len(win) > 3 else 0
            height = int(win[4]) if len(win) > 4 else 0

            # Save info window template: bg=0, left=1, top=1, width=14, height=8..10 (pokedex hidden reduces height by 2).
            if bg != 0 or width != 14 or left != 1 or top != 1 or height < 8:
                return None

            sb1_ptr = int.from_bytes(fixed[2][:4], "little") if fixed[2] and len(fixed[2]) >= 4 else 0
            sb2_ptr = int.from_bytes(fixed[3][:4], "little") if fixed[3] and len(fixed[3]) >= 4 else 0
            if sb1_ptr == 0 or sb2_ptr == 0:
                return None

            mapsec_id = int(fixed[4][0]) if fixed[4] else 0
            location = _get_mapsec_display_name(mapsec_id)

            # Dynamic ranges that depend on save block pointers.
            needed_flags = [int(FLAG_BADGE01) + i for i in range(int(NUM_BADGES))]
            needed_flags.extend([int(FLAG_SYS_POKEDEX_GET), int(FLAG_SYS_NATIONAL_DEX)])
            min_flag_byte = min(f // 8 for f in needed_flags)
            max_flag_byte = max(f // 8 for f in needed_flags)
            flags_base = int(sb1_ptr) + int(SB1_FLAGS_OFFSET)
            flags_addr = flags_base + int(min_flag_byte)
            flags_len = int(max_flag_byte - min_flag_byte + 1)

            nat_var_addr = int(sb1_ptr) + int(SB1_VARS_OFFSET) + (int(VAR_NATIONAL_DEX) - int(VARS_START)) * 2

            time_start = min(int(SB2_PLAY_TIME_HOURS_OFFSET), int(SB2_PLAY_TIME_MINUTES_OFFSET))
            time_end = max(int(SB2_PLAY_TIME_HOURS_OFFSET) + 2, int(SB2_PLAY_TIME_MINUTES_OFFSET) + 1)
            time_len = int(max(0, time_end - time_start))

            # Read from the National magic byte through the owned flags region in one buffer.
            pokedex_start = int(sb2_ptr) + int(SB2_POKEDEX_OFFSET) + int(POKEDEX_NATIONAL_MAGIC_OFFSET)
            pokedex_len = int((POKEDEX_OWNED_OFFSET - POKEDEX_NATIONAL_MAGIC_OFFSET) + NUM_DEX_FLAG_BYTES)

            dyn_ranges = [
                (flags_addr, flags_len),
                (nat_var_addr, 2),
                (int(sb2_ptr) + int(SB2_PLAYER_NAME_OFFSET), 8),
                (int(sb2_ptr) + time_start, time_len),
                (pokedex_start, pokedex_len),
            ]
            dyn = mgba._try_mgba_read_ranges_bytes_no_fallback(dyn_ranges)
            if dyn is None or len(dyn) < len(dyn_ranges):
                return None

            flags_raw = dyn[0] or b""
            nat_var_raw = dyn[1] or b""
            player_name_raw = dyn[2] or b""
            time_raw = dyn[3] or b""
            pokedex_raw = dyn[4] or b""

            def flag_get(flag_id: int) -> bool:
                if flag_id <= 0:
                    return False
                byte_offset = int(flag_id) // 8
                bit_offset = int(flag_id) % 8
                idx = byte_offset - int(min_flag_byte)
                if idx < 0 or idx >= len(flags_raw):
                    return False
                return ((int(flags_raw[idx]) >> bit_offset) & 1) == 1

            player_name = text_encoding.decode_gba_string(player_name_raw, 8) or "PLAYER"

            badge_count = 0
            for i in range(NUM_BADGES):
                if flag_get(int(FLAG_BADGE01) + int(i)):
                    badge_count += 1

            hours_off = int(SB2_PLAY_TIME_HOURS_OFFSET) - int(time_start)
            mins_off = int(SB2_PLAY_TIME_MINUTES_OFFSET) - int(time_start)
            play_hours = (
                int.from_bytes(time_raw[hours_off : hours_off + 2], "little")
                if 0 <= hours_off and (hours_off + 2) <= len(time_raw)
                else 0
            )
            play_minutes = int(time_raw[mins_off]) if 0 <= mins_off < len(time_raw) else 0
            play_time = f"{play_hours}:{play_minutes:02d}"

            pokedex_caught: Optional[int] = None
            nat_enabled = False
            if flag_get(int(FLAG_SYS_POKEDEX_GET)):
                magic = int(pokedex_raw[0]) if len(pokedex_raw) >= 1 else 0
                owned_off = int(POKEDEX_OWNED_OFFSET - POKEDEX_NATIONAL_MAGIC_OFFSET)
                owned = pokedex_raw[owned_off : owned_off + int(NUM_DEX_FLAG_BYTES)]

                if magic == int(NATIONAL_MAGIC_VALUE):
                    nat_var = int.from_bytes(nat_var_raw[:2], "little") if len(nat_var_raw) >= 2 else 0
                    if nat_var == int(NATIONAL_DEX_VAR_VALUE) and flag_get(int(FLAG_SYS_NATIONAL_DEX)):
                        nat_enabled = True

                if nat_enabled:
                    total = 0
                    full_bytes = NATIONAL_DEX_COUNT // 8
                    partial_bits = NATIONAL_DEX_COUNT % 8
                    for b in owned[:full_bytes]:
                        total += int(b).bit_count()
                    if partial_bits and full_bytes < len(owned):
                        total += (int(owned[full_bytes]) & ((1 << partial_bits) - 1)).bit_count()
                    pokedex_caught = total
                else:
                    total = 0
                    full_bytes = int(KANTO_DEX_COUNT) // 8
                    partial_bits = int(KANTO_DEX_COUNT) % 8
                    for b in owned[:full_bytes]:
                        total += int(b).bit_count()
                    if partial_bits and full_bytes < len(owned):
                        total += (int(owned[full_bytes]) & ((1 << partial_bits) - 1)).bit_count()
                    pokedex_caught = total

            dex_mode = "national" if nat_enabled else ("kanto" if pokedex_caught is not None else "none")

        duration_ms = (perf_counter() - t0) * 1000.0
        if _SAVEINFO_DEBUG or duration_ms >= 100.0:
            m1 = mgba._mgba_metrics()
            delta = None
            if m0_counts is not None and m1 is not None:
                m1_counts = (
                    m1.read8_calls,
                    m1.read16_calls,
                    m1.read32_calls,
                    m1.read_range_calls,
                    m1.read_ranges_calls,
                    m1.read_range_bytes_calls,
                    m1.read_ranges_bytes_calls,
                )
                delta = tuple(int(a) - int(b) for a, b in zip(m1_counts, m0_counts))
            _BENCH_LOGGER.info(
                "save_info_window_state duration=%.1fms dex_mode=%s pokedex=%s kanto_count=%s mgba_delta=%s",
                duration_ms,
                dex_mode,
                str(pokedex_caught),
                str(KANTO_DEX_COUNT),
                str(delta),
            )

        lines: List[str] = []
        if location:
            lines.append(location)
        lines.append(f"PLAYER: {player_name}")
        lines.append(f"BADGES: {badge_count}")
        if pokedex_caught is not None:
            lines.append(f"POKéDEX: {pokedex_caught}")
        lines.append(f"TIME: {play_time}")

        return {
            "type": "saveInfo",
            "windowId": window_id,
            "location": location,
            "playerName": player_name,
            "badgeCount": int(badge_count),
            "pokedexCaught": pokedex_caught,
            "playTimeHours": int(play_hours),
            "playTimeMinutes": int(play_minutes),
            "playTime": play_time,
            "visibleText": "\n".join(lines),
        }
    except Exception:
        return None
