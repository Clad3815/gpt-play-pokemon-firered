from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..constants.addresses import *  # noqa: F403
from ..game_data import get_ability_name, get_item_name, get_move_name, get_species_name
from ..memory import mgba
from ..text import encoding as text_encoding
from ..util.bytes import _u8_from
from .save import get_national_pokedex_num

# Equipe Pokémon (décryptage PID/OTID, sous-structures, stats...)
# =============================================================================

_SPECIES_INFO_CACHE: Dict[int, Tuple[int, int, int, int]] = {}


def get_party_count() -> int:
    count = 0
    while count < PARTY_SIZE:
        base = PARTY_BASE_ADDR + count * POKEMON_DATA_SIZE
        pid = mgba.mgba_read32(base + PID_OFFSET)
        if pid == 0:
            break
        try:
            species = get_species_id_for_slot(count)
            if species == SPECIES_NONE:
                break
        except Exception:
            break
        count += 1
    return count


def decrypt_encrypted_block(slot: int) -> Tuple[int, int, bytes]:
    base = PARTY_BASE_ADDR + slot * POKEMON_DATA_SIZE
    pid = mgba.mgba_read32(base + PID_OFFSET)
    otid = mgba.mgba_read32(base + OTID_OFFSET)
    enc = mgba.mgba_read_range_bytes(base + ENCRYPTED_BLOCK_OFFSET, ENCRYPTED_BLOCK_SIZE)
    key = pid ^ otid
    out = bytearray(ENCRYPTED_BLOCK_SIZE)
    for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
        val = int.from_bytes(enc[i : i + 4], "little") ^ key
        out[i : i + 4] = val.to_bytes(4, "little")
    return pid, otid, bytes(out)


def unshuffle_substructures(decrypted: bytes, pid: int) -> Dict[str, bytes]:
    order = SUBSTRUCTURE_ORDER[pid % 24]
    out: Dict[str, Optional[bytes]] = {"G": None, "A": None, "E": None, "M": None}
    for i, ch in enumerate(order):
        start = i * SUBSTRUCTURE_SIZE
        out[ch] = decrypted[start : start + SUBSTRUCTURE_SIZE]
    # type ignore: we've filled bytes
    return out  # type: ignore[return-value]


def get_species_id_from_growth(growth: bytes) -> int:
    return int.from_bytes(growth[0:2], "little")


def get_species_id_for_slot(slot: int) -> int:
    pid, _otid, dec = decrypt_encrypted_block(slot)
    subs = unshuffle_substructures(dec, pid)
    if subs["G"] is None:
        return SPECIES_NONE
    return get_species_id_from_growth(subs["G"])


def get_status_name_from_mask(mask: int) -> str:
    for m, name in STATUS_CONDITION_MASKS:
        if (mask & m) != 0:
            return name
    return "NONE"


def is_shiny(pid: int, otid: int) -> bool:
    tid = otid & 0xFFFF
    sid = (otid >> 16) & 0xFFFF
    pid_lo = pid & 0xFFFF
    pid_hi = (pid >> 16) & 0xFFFF
    return (tid ^ sid ^ pid_lo ^ pid_hi) < 8


def get_types_for_species(species_id: int) -> List[str]:
    if species_id == SPECIES_NONE:
        return []
    cached = _SPECIES_INFO_CACHE.get(int(species_id))
    if cached:
        b0, b1, _a1, _a2 = cached
        t1 = POKEMON_TYPE_MAP.get(int(b0), f"TYPE_UNKNOWN({b0})")
        out = [t1]
        if int(b1) != int(b0) and int(b1) != 255:
            out.append(POKEMON_TYPE_MAP.get(int(b1), f"TYPE_UNKNOWN({b1})"))
        return out
    addr = SPECIES_INFO_ADDR + (species_id * SPECIES_INFO_SIZE) + SPECIES_INFO_TYPES_OFFSET
    b = mgba.mgba_read_range_bytes(addr, 2)
    b0 = _u8_from(b, 0)
    b1 = _u8_from(b, 1)
    t1 = POKEMON_TYPE_MAP.get(b0, f"TYPE_UNKNOWN({b0})")
    out = [t1]
    if b1 != b0 and b1 != 255:
        out.append(POKEMON_TYPE_MAP.get(b1, f"TYPE_UNKNOWN({b1})"))
    return out


def get_ability_for_species(species_id: int, ability_slot: int) -> Optional[str]:
    if species_id == SPECIES_NONE:
        return None
    cached = _SPECIES_INFO_CACHE.get(int(species_id))
    if cached:
        _t1, _t2, a1, a2 = cached
        aid = int(a2) if int(ability_slot) == 1 else int(a1)
        return get_ability_name(aid)
    addr = SPECIES_INFO_ADDR + (species_id * SPECIES_INFO_SIZE) + SPECIES_INFO_ABILITIES_OFFSET
    arr = mgba.mgba_read_range_bytes(addr, 2)
    aid = _u8_from(arr, 1) if ability_slot == 1 else _u8_from(arr, 0)
    return get_ability_name(aid)


def _read_species_infos(species_ids: List[int]) -> Dict[int, Tuple[int, int, int, int]]:
    uniq = [int(sid) for sid in sorted(set(int(s) for s in species_ids)) if int(sid) != int(SPECIES_NONE)]
    if not uniq:
        return {}

    missing = [sid for sid in uniq if sid not in _SPECIES_INFO_CACHE]
    if missing:
        ranges = []
        for sid in missing:
            base = int(SPECIES_INFO_ADDR) + (int(sid) * int(SPECIES_INFO_SIZE))
            ranges.append((base + int(SPECIES_INFO_TYPES_OFFSET), 2))
            ranges.append((base + int(SPECIES_INFO_ABILITIES_OFFSET), 2))

        results = mgba.mgba_read_ranges_bytes(ranges)
        idx = 0
        for sid in missing:
            types_raw = results[idx] if idx < len(results) else b""
            abil_raw = results[idx + 1] if (idx + 1) < len(results) else b""
            idx += 2

            # Only cache when both ranges were returned with expected sizes.
            if not (isinstance(types_raw, (bytes, bytearray)) and len(types_raw) >= 2):
                continue
            if not (isinstance(abil_raw, (bytes, bytearray)) and len(abil_raw) >= 2):
                continue

            t1 = int(_u8_from(types_raw, 0))
            t2 = int(_u8_from(types_raw, 1))
            a1 = int(_u8_from(abil_raw, 0))
            a2 = int(_u8_from(abil_raw, 1))
            _SPECIES_INFO_CACHE[int(sid)] = (t1, t2, a1, a2)

    return {sid: _SPECIES_INFO_CACHE[sid] for sid in uniq if sid in _SPECIES_INFO_CACHE}


def get_pokemon_data_slot(slot: int) -> Optional[Dict[str, Any]]:
    base = PARTY_BASE_ADDR + slot * POKEMON_DATA_SIZE
    nickname_raw = mgba.mgba_read_range(base + NICKNAME_OFFSET, 10)
    nickname = text_encoding.decode_gba_string(nickname_raw, 10)

    level = mgba.mgba_read8(base + LEVEL_OFFSET)
    status_cond = mgba.mgba_read32(base + STATUS_OFFSET)
    current_hp = mgba.mgba_read16(base + CURRENT_HP_OFFSET)
    max_hp = mgba.mgba_read16(base + MAX_HP_OFFSET)
    attack = mgba.mgba_read16(base + ATTACK_OFFSET)
    defense = mgba.mgba_read16(base + DEFENSE_OFFSET)
    speed = mgba.mgba_read16(base + SPEED_OFFSET)
    sp_atk = mgba.mgba_read16(base + SP_ATTACK_OFFSET)
    sp_def = mgba.mgba_read16(base + SP_DEFENSE_OFFSET)

    pid, otid, dec = decrypt_encrypted_block(slot)
    subs = unshuffle_substructures(dec, pid)
    if subs["G"] is None or subs["A"] is None or subs["E"] is None or subs["M"] is None:
        return None

    species_id = get_species_id_from_growth(subs["G"])
    if species_id == SPECIES_NONE:
        return None

    held_item_id = int.from_bytes(subs["G"][2:4], "little")
    exp = int.from_bytes(subs["G"][4:8], "little")
    pp_bonuses = subs["G"][8]
    friendship = subs["G"][9]

    m1 = int.from_bytes(subs["A"][0:2], "little")
    m2 = int.from_bytes(subs["A"][2:4], "little")
    m3 = int.from_bytes(subs["A"][4:6], "little")
    m4 = int.from_bytes(subs["A"][6:8], "little")
    pp1, pp2, pp3, pp4 = subs["A"][8], subs["A"][9], subs["A"][10], subs["A"][11]

    ev_hp = subs["E"][0]
    ev_atk = subs["E"][1]
    ev_def = subs["E"][2]
    ev_spe = subs["E"][3]
    ev_spa = subs["E"][4]
    ev_spd = subs["E"][5]

    iv_bitfield = int.from_bytes(subs["M"][4:8], "little")

    def iv_of(stat_idx: int) -> int:
        shift = stat_idx * 5
        return (iv_bitfield >> shift) & 0x1F

    is_egg = ((iv_bitfield >> 30) & 1) == 1
    ability_slot = (iv_bitfield >> 31) & 1

    types = get_types_for_species(species_id)
    ability_name = get_ability_for_species(species_id, ability_slot)

    return {
        "nickname": nickname,
        "pid": pid,
        "otid": otid,
        "level": level,
        "species": get_species_name(species_id),
        "speciesId": species_id,
        "pokedexId": get_national_pokedex_num(species_id),
        "types": types,
        "ability": ability_name,
        "statusCondition": get_status_name_from_mask(status_cond),
        "currentHP": current_hp,
        "maxHP": max_hp,
        "stats": {"attack": attack, "defense": defense, "speed": speed, "spAttack": sp_atk, "spDefense": sp_def},
        "heldItemId": held_item_id,
        "heldItemName": get_item_name(held_item_id),
        "experience": exp,
        "friendship": friendship,
        "ppBonuses": pp_bonuses,
        "moves": [get_move_name(m1), get_move_name(m2), get_move_name(m3), get_move_name(m4)],
        "movesRaw": [m1, m2, m3, m4],
        "currentPP": [pp1, pp2, pp3, pp4],
        "evs": {"hp": ev_hp, "attack": ev_atk, "defense": ev_def, "speed": ev_spe, "spAttack": ev_spa, "spDefense": ev_spd},
        "ivs": {"hp": iv_of(0), "attack": iv_of(1), "defense": iv_of(2), "speed": iv_of(3), "spAttack": iv_of(4), "spDefense": iv_of(5)},
        "isEgg": is_egg,
        "is_shiny": is_shiny(pid, otid),
        "abilitySlot": ability_slot,
    }

def _get_party_data_slow() -> List[Dict[str, Any]]:
    cnt = get_party_count()
    out: List[Dict[str, Any]] = []
    for i in range(cnt):
        d = get_pokemon_data_slot(i)
        if d:
            out.append(d)
    return out


def _get_party_data_fast_from_raw(raw: bytes) -> List[Dict[str, Any]]:
    total_len = PARTY_SIZE * POKEMON_DATA_SIZE
    if not raw or len(raw) < POKEMON_DATA_SIZE:
        return []
    # Defensive: only parse within the expected party buffer size.
    raw = bytes(raw[:total_len])

    temp: List[Dict[str, Any]] = []
    species_ids: List[int] = []
    for slot in range(PARTY_SIZE):
        base = slot * POKEMON_DATA_SIZE
        if (base + POKEMON_DATA_SIZE) > len(raw):
            break

        pid = int.from_bytes(raw[base + PID_OFFSET : base + PID_OFFSET + 4], "little")
        if pid == 0:
            break
        otid = int.from_bytes(raw[base + OTID_OFFSET : base + OTID_OFFSET + 4], "little")

        enc = raw[base + ENCRYPTED_BLOCK_OFFSET : base + ENCRYPTED_BLOCK_OFFSET + ENCRYPTED_BLOCK_SIZE]
        key = pid ^ otid
        dec = bytearray(ENCRYPTED_BLOCK_SIZE)
        for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
            val = int.from_bytes(enc[i : i + 4], "little") ^ key
            dec[i : i + 4] = val.to_bytes(4, "little")
        subs = unshuffle_substructures(bytes(dec), pid)
        if subs["G"] is None or subs["A"] is None or subs["E"] is None or subs["M"] is None:
            continue

        species_id = get_species_id_from_growth(subs["G"])
        if species_id == SPECIES_NONE:
            break

        nickname_raw = raw[base + NICKNAME_OFFSET : base + NICKNAME_OFFSET + 10]
        nickname = text_encoding.decode_gba_string(nickname_raw, 10)

        level = raw[base + LEVEL_OFFSET]
        status_cond = int.from_bytes(raw[base + STATUS_OFFSET : base + STATUS_OFFSET + 4], "little")
        current_hp = int.from_bytes(raw[base + CURRENT_HP_OFFSET : base + CURRENT_HP_OFFSET + 2], "little")
        max_hp = int.from_bytes(raw[base + MAX_HP_OFFSET : base + MAX_HP_OFFSET + 2], "little")
        attack = int.from_bytes(raw[base + ATTACK_OFFSET : base + ATTACK_OFFSET + 2], "little")
        defense = int.from_bytes(raw[base + DEFENSE_OFFSET : base + DEFENSE_OFFSET + 2], "little")
        speed = int.from_bytes(raw[base + SPEED_OFFSET : base + SPEED_OFFSET + 2], "little")
        sp_atk = int.from_bytes(raw[base + SP_ATTACK_OFFSET : base + SP_ATTACK_OFFSET + 2], "little")
        sp_def = int.from_bytes(raw[base + SP_DEFENSE_OFFSET : base + SP_DEFENSE_OFFSET + 2], "little")

        held_item_id = int.from_bytes(subs["G"][2:4], "little")
        exp = int.from_bytes(subs["G"][4:8], "little")
        pp_bonuses = subs["G"][8]
        friendship = subs["G"][9]

        m1 = int.from_bytes(subs["A"][0:2], "little")
        m2 = int.from_bytes(subs["A"][2:4], "little")
        m3 = int.from_bytes(subs["A"][4:6], "little")
        m4 = int.from_bytes(subs["A"][6:8], "little")
        pp1, pp2, pp3, pp4 = subs["A"][8], subs["A"][9], subs["A"][10], subs["A"][11]

        ev_hp = subs["E"][0]
        ev_atk = subs["E"][1]
        ev_def = subs["E"][2]
        ev_spe = subs["E"][3]
        ev_spa = subs["E"][4]
        ev_spd = subs["E"][5]

        iv_bitfield = int.from_bytes(subs["M"][4:8], "little")

        def iv_of(stat_idx: int) -> int:
            shift = stat_idx * 5
            return (iv_bitfield >> shift) & 0x1F

        is_egg = ((iv_bitfield >> 30) & 1) == 1
        ability_slot = (iv_bitfield >> 31) & 1

        temp.append(
            {
                "nickname": nickname,
                "pid": pid,
                "otid": otid,
                "level": level,
                "speciesId": species_id,
                "pokedexId": get_national_pokedex_num(species_id),
                "statusCondition": get_status_name_from_mask(status_cond),
                "currentHP": current_hp,
                "maxHP": max_hp,
                "stats": {
                    "attack": attack,
                    "defense": defense,
                    "speed": speed,
                    "spAttack": sp_atk,
                    "spDefense": sp_def,
                },
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
                "isEgg": is_egg,
                "is_shiny": is_shiny(pid, otid),
                "abilitySlot": ability_slot,
            }
        )
        species_ids.append(species_id)

    species_info = _read_species_infos(species_ids)
    out: List[Dict[str, Any]] = []
    for entry in temp:
        species_id = entry["speciesId"]
        types = []
        ability_name = None
        info = species_info.get(species_id)
        if info:
            t1, t2, a1, a2 = info
            t1_name = POKEMON_TYPE_MAP.get(t1, f"TYPE_UNKNOWN({t1})")
            types = [t1_name]
            if t2 != t1 and t2 != 255:
                types.append(POKEMON_TYPE_MAP.get(t2, f"TYPE_UNKNOWN({t2})"))
            ability_id = a2 if entry["abilitySlot"] == 1 else a1
            ability_name = get_ability_name(ability_id)
        else:
            types = get_types_for_species(species_id)
            ability_name = get_ability_for_species(species_id, entry["abilitySlot"])

        entry["species"] = get_species_name(species_id)
        entry["types"] = types
        entry["ability"] = ability_name
        out.append(entry)

    return out


def _get_party_data_fast() -> List[Dict[str, Any]]:
    total_len = PARTY_SIZE * POKEMON_DATA_SIZE
    raw = mgba.mgba_read_range_bytes(PARTY_BASE_ADDR, total_len)
    return _get_party_data_fast_from_raw(raw)


def get_party_data(
    *,
    party_raw: Optional[bytes] = None,
    battle_type_overrides: Optional[Dict[int, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Get party data with optional battle type overrides.

    Args:
        party_raw: Optional raw party buffer (length PARTY_SIZE * POKEMON_DATA_SIZE), typically from a snapshot.
        battle_type_overrides: Optional dict mapping party slot index (0-5) to dynamic types
                               from gBattleMons (e.g. for Color Change ability).
    """
    try:
        if party_raw is not None:
            result = _get_party_data_fast_from_raw(party_raw)
        else:
            result = _get_party_data_fast()
    except Exception:
        result = _get_party_data_slow()

    # Apply battle type overrides if provided
    if battle_type_overrides:
        for i, entry in enumerate(result):
            if i in battle_type_overrides:
                entry["types"] = battle_type_overrides[i]

    return result


# =============================================================================
