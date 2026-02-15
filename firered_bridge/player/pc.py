from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..constants.addresses import *  # noqa: F403
from ..game_data import get_ability_name, get_item_name, get_move_name, get_species_name
from ..memory import mgba
from ..text import encoding as text_encoding
from ..util.bytes import _u8_from
from .party import (
    get_ability_for_species,
    get_species_id_from_growth,
    get_types_for_species,
    is_shiny,
    unshuffle_substructures,
)
from .save import get_national_pokedex_num

# PC storage (boxes + items)
# =============================================================================

_SPECIES_INFO_FULL_CACHE: Dict[int, bytes] = {}
_PC_BOX_CACHE_KEY: Optional[Tuple[int, int, bytes]] = None
_PC_BOX_CACHE_RESULT: Optional[List[Optional[Dict[str, Any]]]] = None

_MON_GENDER_MALE = 0x00
_MON_GENDER_FEMALE = 0xFE
_MON_GENDER_GENDERLESS = 0xFF

# pokefirered/include/constants/species.h (vanilla FireRed ids)
_SPECIES_NIDORAN_F = 29
_SPECIES_NIDORAN_M = 32


def _gender_from_species_and_personality(*, species_id: int, personality: int, gender_ratio: int) -> str:
    """
    Mirror pokefirered/src/pokemon.c:GetGenderFromSpeciesAndPersonality().

    Returns: "MALE" | "FEMALE" | "GENDERLESS"
    """
    sid = int(species_id)
    if sid in {_SPECIES_NIDORAN_F, _SPECIES_NIDORAN_M}:
        # pokefirered/src/pokemon_storage_system.c forces genderless display for these.
        return "GENDERLESS"

    gr = int(gender_ratio) & 0xFF
    if gr == _MON_GENDER_MALE:
        return "MALE"
    if gr == _MON_GENDER_FEMALE:
        return "FEMALE"
    if gr == _MON_GENDER_GENDERLESS:
        return "GENDERLESS"

    return "FEMALE" if gr > (int(personality) & 0xFF) else "MALE"


def _gender_symbol(gender: str) -> Optional[str]:
    if gender == "MALE":
        return "♂"
    if gender == "FEMALE":
        return "♀"
    return None


def _cube(n: int) -> int:
    nn = int(n)
    return nn * nn * nn


def _exp_for_level(growth_rate: int, level: int) -> int:
    lvl = int(level)
    if lvl <= 0:
        return 0
    if lvl == 1:
        return 1

    gr = int(growth_rate)

    if gr == 0:  # GROWTH_MEDIUM_FAST
        return _cube(lvl)
    if gr == 1:  # GROWTH_ERRATIC
        if lvl <= 50:
            return ((100 - lvl) * _cube(lvl)) // 50
        if lvl <= 68:
            return ((150 - lvl) * _cube(lvl)) // 100
        if lvl <= 98:
            return (((1911 - 10 * lvl) // 3) * _cube(lvl)) // 500
        return ((160 - lvl) * _cube(lvl)) // 100
    if gr == 2:  # GROWTH_FLUCTUATING
        if lvl <= 15:
            return ((((lvl + 1) // 3) + 24) * _cube(lvl)) // 50
        if lvl <= 36:
            return ((lvl + 14) * _cube(lvl)) // 50
        return (((lvl // 2) + 32) * _cube(lvl)) // 50
    if gr == 3:  # GROWTH_MEDIUM_SLOW
        return (6 * _cube(lvl)) // 5 - 15 * (lvl * lvl) + 100 * lvl - 140
    if gr == 4:  # GROWTH_FAST
        return (4 * _cube(lvl)) // 5
    if gr == 5:  # GROWTH_SLOW
        return (5 * _cube(lvl)) // 4

    # Fallback: treat unknown as Medium Fast.
    return _cube(lvl)


_EXPERIENCE_TABLES: Dict[int, List[int]] = {}
for _gr in range(6):
    _tbl = [0] * (MAX_LEVEL + 1)
    for _lvl in range(0, MAX_LEVEL + 1):
        _tbl[_lvl] = _exp_for_level(_gr, _lvl)
    _EXPERIENCE_TABLES[_gr] = _tbl


def _level_from_exp(exp: int, growth_rate: int) -> int:
    exp_i = int(exp)
    gr = int(growth_rate)
    table = _EXPERIENCE_TABLES.get(gr) or _EXPERIENCE_TABLES[0]
    level = 1
    while level <= MAX_LEVEL and table[level] <= exp_i:
        level += 1
    out = int(level - 1)
    return out if out >= 1 else 1


def _modify_stat_by_nature(nature: int, stat: int, stat_index: int) -> int:
    """
    Mirror pokefirered/src/pokemon.c:ModifyStatByNature().

    - nature is 0..24 (personality % 25)
    - stat_index is STAT_ATK..STAT_SPDEF (1..5)
    """
    n = int(nature)
    inc = n // 5
    dec = n % 5
    if inc == dec:
        return int(stat)

    idx = int(stat_index) - 1  # nature stats exclude HP
    if idx == inc:
        return (int(stat) * 110) // 100
    if idx == dec:
        return (int(stat) * 90) // 100
    return int(stat)


def _calc_non_hp_stat(base: int, iv: int, ev: int, level: int, nature: int, stat_index: int) -> int:
    lvl = int(level)
    n = (((2 * int(base) + int(iv) + (int(ev) // 4)) * lvl) // 100) + 5
    return _modify_stat_by_nature(nature, n, stat_index)


def _calc_max_hp(*, species_id: int, base_hp: int, iv: int, ev: int, level: int) -> int:
    if int(species_id) == SPECIES_SHEDINJA:
        return 1
    lvl = int(level)
    n = 2 * int(base_hp) + int(iv)
    return (((n + (int(ev) // 4)) * lvl) // 100) + lvl + 10


def _read_species_infos_full(species_ids: List[int]) -> Dict[int, bytes]:
    """
    Read full `struct SpeciesInfo` blobs for all unique species ids.

    Returns {species_id: bytes} where bytes is length SPECIES_INFO_SIZE.
    """
    uniq = [int(sid) for sid in sorted(set(int(s) for s in species_ids)) if int(sid) != int(SPECIES_NONE)]
    if not uniq:
        return {}

    out: Dict[int, bytes] = {}
    missing: List[int] = []
    for sid in uniq:
        cached = _SPECIES_INFO_FULL_CACHE.get(int(sid))
        if isinstance(cached, (bytes, bytearray)) and len(cached) >= int(SPECIES_INFO_SIZE):
            out[int(sid)] = bytes(cached[: int(SPECIES_INFO_SIZE)])
        else:
            missing.append(int(sid))

    if missing:
        ranges = [(int(SPECIES_INFO_ADDR) + (int(sid) * int(SPECIES_INFO_SIZE)), int(SPECIES_INFO_SIZE)) for sid in missing]
        chunks = mgba.mgba_read_ranges_bytes(ranges)
        for sid, chunk in zip(missing, chunks):
            if isinstance(chunk, (bytes, bytearray)) and len(chunk) >= int(SPECIES_INFO_SIZE):
                blob = bytes(chunk[: int(SPECIES_INFO_SIZE)])
                _SPECIES_INFO_FULL_CACHE[int(sid)] = blob
                out[int(sid)] = blob

    return out


def _parse_box_slot_to_party_schema(slot_raw: bytes) -> Optional[Dict[str, Any]]:
    """
    Parse one `struct BoxPokemon` into the same schema as `get_party_data()` entries.

    Note: Box mons do not store HP/status, so we compute stats and return healed state:
    - statusCondition: "NONE"
    - currentHP == maxHP
    """
    if not slot_raw or len(slot_raw) < BOX_POKEMON_SIZE:
        return None

    flags = int(slot_raw[BOXMON_FLAGS_OFFSET])
    has_species = ((flags >> 1) & 1) == 1
    if not has_species:
        return None

    pid = int.from_bytes(slot_raw[BOXMON_PID_OFFSET : BOXMON_PID_OFFSET + 4], "little")
    otid = int.from_bytes(slot_raw[BOXMON_OTID_OFFSET : BOXMON_OTID_OFFSET + 4], "little")
    if pid == 0:
        return None

    nickname_raw = slot_raw[BOXMON_NICKNAME_OFFSET : BOXMON_NICKNAME_OFFSET + 10]
    nickname = text_encoding.decode_gba_string(nickname_raw, 10)

    enc = slot_raw[
        BOXMON_ENCRYPTED_BLOCK_OFFSET : BOXMON_ENCRYPTED_BLOCK_OFFSET + BOXMON_ENCRYPTED_BLOCK_SIZE
    ]
    if len(enc) < BOXMON_ENCRYPTED_BLOCK_SIZE:
        return None

    key = pid ^ otid
    dec = bytearray(BOXMON_ENCRYPTED_BLOCK_SIZE)
    for i in range(0, BOXMON_ENCRYPTED_BLOCK_SIZE, 4):
        val = int.from_bytes(enc[i : i + 4], "little") ^ key
        dec[i : i + 4] = val.to_bytes(4, "little")
    subs = unshuffle_substructures(bytes(dec), pid)
    if subs["G"] is None or subs["A"] is None or subs["E"] is None or subs["M"] is None:
        return None

    species_id = get_species_id_from_growth(subs["G"])
    if species_id == SPECIES_NONE:
        return None

    held_item_id = int.from_bytes(subs["G"][2:4], "little")
    exp = int.from_bytes(subs["G"][4:8], "little")
    pp_bonuses = int(subs["G"][8])
    friendship = int(subs["G"][9])

    m1 = int.from_bytes(subs["A"][0:2], "little")
    m2 = int.from_bytes(subs["A"][2:4], "little")
    m3 = int.from_bytes(subs["A"][4:6], "little")
    m4 = int.from_bytes(subs["A"][6:8], "little")
    pp1, pp2, pp3, pp4 = int(subs["A"][8]), int(subs["A"][9]), int(subs["A"][10]), int(subs["A"][11])

    ev_hp = int(subs["E"][0])
    ev_atk = int(subs["E"][1])
    ev_def = int(subs["E"][2])
    ev_spe = int(subs["E"][3])
    ev_spa = int(subs["E"][4])
    ev_spd = int(subs["E"][5])

    iv_bitfield = int.from_bytes(subs["M"][4:8], "little")

    def iv_of(stat_idx: int) -> int:
        shift = stat_idx * 5
        return (iv_bitfield >> shift) & 0x1F

    is_egg = ((iv_bitfield >> 30) & 1) == 1
    ability_slot = (iv_bitfield >> 31) & 1

    return {
        "nickname": nickname,
        "pid": pid,
        "otid": otid,
        "level": 0,  # filled later (needs growthRate)
        "speciesId": int(species_id),
        "pokedexId": get_national_pokedex_num(species_id),
        "statusCondition": "NONE",
        "currentHP": 0,  # filled later (computed)
        "maxHP": 0,  # filled later (computed)
        "stats": {},  # filled later (computed)
        "heldItemId": held_item_id,
        "heldItemName": get_item_name(held_item_id),
        "experience": exp,
        "friendship": friendship,
        "ppBonuses": pp_bonuses,
        "moves": [get_move_name(m1), get_move_name(m2), get_move_name(m3), get_move_name(m4)],
        "movesRaw": [m1, m2, m3, m4],
        "currentPP": [pp1, pp2, pp3, pp4],
        "evs": {
            "hp": ev_hp,
            "attack": ev_atk,
            "defense": ev_def,
            "speed": ev_spe,
            "spAttack": ev_spa,
            "spDefense": ev_spd,
        },
        "ivs": {
            "hp": iv_of(0),
            "attack": iv_of(1),
            "defense": iv_of(2),
            "speed": iv_of(3),
            "spAttack": iv_of(4),
            "spDefense": iv_of(5),
        },
        "isEgg": bool(is_egg),
        "is_shiny": is_shiny(pid, otid),
        "abilitySlot": int(ability_slot),
        # Filled later (species info)
        "species": get_species_name(species_id),
        "types": [],
        "ability": None,
    }


def get_pc_current_box_id(*, storage_ptr: Optional[int] = None) -> int:
    try:
        ptr = int(storage_ptr) if storage_ptr is not None else int(mgba.mgba_read32(GPOKEMON_STORAGE_PTR_ADDR))
        if ptr == 0:
            return 0
        box_id = int(mgba.mgba_read8(ptr + POKEMON_STORAGE_CURRENT_BOX_OFFSET))
        if box_id < 0 or box_id >= TOTAL_BOXES_COUNT:
            return 0
        return box_id
    except Exception:
        return 0


def get_pc_box_mons(*, box_id: Optional[int] = None) -> Tuple[int, List[Optional[Dict[str, Any]]]]:
    """
    Return (box_id, mons) for the requested box or for the current box when box_id is None.

    The returned `mons` list is always length IN_BOX_COUNT, where empty slots are None.
    Each non-empty slot matches the `get_party_data()` per-Pokémon schema.
    """
    storage_ptr = int(mgba.mgba_read32(GPOKEMON_STORAGE_PTR_ADDR))
    if storage_ptr == 0:
        return 0, [None] * IN_BOX_COUNT

    current_box = get_pc_current_box_id(storage_ptr=storage_ptr)
    target_box = int(box_id) if box_id is not None else int(current_box)
    if target_box < 0 or target_box >= TOTAL_BOXES_COUNT:
        target_box = int(current_box)

    box_base = storage_ptr + POKEMON_STORAGE_BOXES_OFFSET + (target_box * IN_BOX_COUNT * BOX_POKEMON_SIZE)
    total_len = IN_BOX_COUNT * BOX_POKEMON_SIZE
    raw = mgba.mgba_read_range_bytes(box_base, total_len)
    if not raw or len(raw) < BOX_POKEMON_SIZE:
        return target_box, [None] * IN_BOX_COUNT

    global _PC_BOX_CACHE_KEY, _PC_BOX_CACHE_RESULT
    cache_key = (int(storage_ptr), int(target_box), bytes(raw))
    if _PC_BOX_CACHE_KEY == cache_key and _PC_BOX_CACHE_RESULT is not None:
        return target_box, _PC_BOX_CACHE_RESULT

    parsed: List[Optional[Dict[str, Any]]] = []
    species_ids: List[int] = []
    for slot in range(IN_BOX_COUNT):
        off = slot * BOX_POKEMON_SIZE
        mon = _parse_box_slot_to_party_schema(raw[off : off + BOX_POKEMON_SIZE])
        parsed.append(mon)
        if mon is not None:
            species_ids.append(int(mon.get("speciesId", 0) or 0))

    # Fill derived fields that require species info (base stats, types, abilities, growth rate).
    species_blobs = _read_species_infos_full(species_ids)
    for mon in parsed:
        if mon is None:
            continue

        sid = int(mon.get("speciesId", 0) or 0)
        blob = species_blobs.get(sid)

        base_hp = base_atk = base_def = base_spe = base_spa = base_spd = 0
        growth_rate = 0
        gender_ratio: Optional[int] = None
        types: List[str] = []
        ability_name: Optional[str] = None

        if blob is not None and len(blob) >= SPECIES_INFO_SIZE:
            base_hp = int(blob[0])
            base_atk = int(blob[1])
            base_def = int(blob[2])
            base_spe = int(blob[3])
            base_spa = int(blob[4])
            base_spd = int(blob[5])
            t1 = int(blob[SPECIES_INFO_TYPES_OFFSET])
            t2 = int(blob[SPECIES_INFO_TYPES_OFFSET + 1])
            gender_ratio = int(blob[SPECIES_INFO_GENDER_RATIO_OFFSET])
            a1 = int(blob[SPECIES_INFO_ABILITIES_OFFSET])
            a2 = int(blob[SPECIES_INFO_ABILITIES_OFFSET + 1])
            growth_rate = int(blob[0x13])

            t1_name = POKEMON_TYPE_MAP.get(t1, f"TYPE_UNKNOWN({t1})")
            types = [t1_name]
            if t2 != t1 and t2 != 255:
                types.append(POKEMON_TYPE_MAP.get(t2, f"TYPE_UNKNOWN({t2})"))

            ability_id = a2 if int(mon.get("abilitySlot", 0) or 0) == 1 else a1
            ability_name = get_ability_name(ability_id)
        else:
            # Fallback (slower): read minimal info per-species.
            types = get_types_for_species(sid)
            ability_name = get_ability_for_species(sid, int(mon.get("abilitySlot", 0) or 0))
            try:
                gender_ratio = int(
                    mgba.mgba_read8(
                        SPECIES_INFO_ADDR + (sid * SPECIES_INFO_SIZE) + SPECIES_INFO_GENDER_RATIO_OFFSET
                    )
                )
            except Exception:
                gender_ratio = None

        exp = int(mon.get("experience", 0) or 0)
        level = _level_from_exp(exp, growth_rate)
        nature = int(mon.get("pid", 0) or 0) % 25

        max_hp = _calc_max_hp(species_id=sid, base_hp=base_hp, iv=int(mon["ivs"]["hp"]), ev=int(mon["evs"]["hp"]), level=level)
        atk = _calc_non_hp_stat(base_atk, int(mon["ivs"]["attack"]), int(mon["evs"]["attack"]), level, nature, STAT_ATK)
        defense = _calc_non_hp_stat(base_def, int(mon["ivs"]["defense"]), int(mon["evs"]["defense"]), level, nature, STAT_DEF)
        speed = _calc_non_hp_stat(base_spe, int(mon["ivs"]["speed"]), int(mon["evs"]["speed"]), level, nature, STAT_SPEED)
        sp_atk = _calc_non_hp_stat(base_spa, int(mon["ivs"]["spAttack"]), int(mon["evs"]["spAttack"]), level, nature, STAT_SPATK)
        sp_def = _calc_non_hp_stat(base_spd, int(mon["ivs"]["spDefense"]), int(mon["evs"]["spDefense"]), level, nature, STAT_SPDEF)

        mon["level"] = int(level)
        mon["maxHP"] = int(max_hp)
        mon["currentHP"] = int(max_hp)
        mon["stats"] = {"attack": atk, "defense": defense, "speed": speed, "spAttack": sp_atk, "spDefense": sp_def}
        mon["types"] = types
        mon["ability"] = ability_name
        if not bool(mon.get("isEgg")) and gender_ratio is not None:
            gender = _gender_from_species_and_personality(
                species_id=sid,
                personality=int(mon.get("pid", 0) or 0),
                gender_ratio=int(gender_ratio),
            )
            mon["gender"] = gender
            mon["genderSymbol"] = _gender_symbol(gender)
        else:
            mon["gender"] = None
            mon["genderSymbol"] = None

    _PC_BOX_CACHE_KEY = cache_key
    _PC_BOX_CACHE_RESULT = parsed
    return target_box, parsed


def get_pc_items(*, sb1_ptr: Optional[int] = None) -> List[Dict[str, Any]]:
    try:
        base = int(sb1_ptr) if sb1_ptr is not None else int(mgba.mgba_read32(GSAVEBLOCK1_PTR_ADDR))
        if base == 0:
            return []
        raw = mgba.mgba_read_range_bytes(base + SB1_PC_ITEMS_OFFSET, PC_ITEMS_COUNT * ITEM_SLOT_SIZE)
        if not raw:
            return []
        items: List[Dict[str, Any]] = []
        for i in range(PC_ITEMS_COUNT):
            off = i * ITEM_SLOT_SIZE
            if off + 3 >= len(raw):
                break
            item_id = int.from_bytes(raw[off : off + 2], "little")
            qty = int.from_bytes(raw[off + 2 : off + 4], "little")
            if item_id == 0:
                continue
            items.append({"name": get_item_name(item_id) or f"Unknown Item ({item_id})", "quantity": qty, "id": item_id})
        return items
    except Exception:
        return []


def get_pc_state(*, sb1_ptr: Optional[int] = None) -> Dict[str, Any]:
    try:
        box_id, mons = get_pc_box_mons()
    except Exception:
        box_id, mons = 0, [None] * IN_BOX_COUNT

    return {
        "currentBox": int(box_id),
        "boxMons": mons,
        "items": get_pc_items(sb1_ptr=sb1_ptr),
    }


# =============================================================================
