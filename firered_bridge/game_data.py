"""Local game data loaders (map, species, items, etc.)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import GAME_DATA_DIR


@dataclass(frozen=True)
class ReferenceTables:
    map_names: Dict[int, Dict[int, str]]
    event_object_names: Dict[int, str]
    ability_names: Dict[int, str]
    item_names: Dict[int, str]
    move_names: Dict[int, str]
    species_names: Dict[int, str]


_reference_tables: Optional[ReferenceTables] = None
_metatile_behaviors: Optional[Dict[int, str]] = None
_layout_id_table: Optional[Dict[str, int]] = None


class GameDataError(RuntimeError):
    pass


def _data_path(name: str) -> Path:
    path = GAME_DATA_DIR / f"{name}.json"
    if not path.exists():
        raise GameDataError(f"Missing data file {path}")
    return path


def _load_json(name: str) -> Any:
    path = _data_path(name)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _convert_int_keys(data: Dict[str, Any]) -> Dict[int, Any]:
    return {int(k): v for k, v in data.items()}


def load_reference_tables(force: bool = False) -> ReferenceTables:
    global _reference_tables
    if _reference_tables is not None and not force:
        return _reference_tables

    raw = _load_json("mappings")
    map_names = {int(g): {int(m): n for m, n in maps.items()} for g, maps in raw["MAP_NAME_TABLE"].items()}
    tables = ReferenceTables(
        map_names=map_names,
        event_object_names=_convert_int_keys(raw["EVENT_OBJECT_NAME"]),
        ability_names=_convert_int_keys(raw["ABILITY_NAME"]),
        item_names=_convert_int_keys(raw["ITEM_NAME"]),
        move_names=_convert_int_keys(raw["MOVE_NAME"]),
        species_names=_convert_int_keys(raw["SPECIES_NAME"]),
    )
    _reference_tables = tables
    return tables


def load_metatile_behaviors(force: bool = False) -> Dict[int, str]:
    global _metatile_behaviors
    if _metatile_behaviors is not None and not force:
        return _metatile_behaviors
    raw = _load_json("metatile_behaviors")
    _metatile_behaviors = _convert_int_keys(raw)
    return _metatile_behaviors


def ensure_game_data_loaded() -> None:
    load_reference_tables()
    load_metatile_behaviors()


def load_layout_id_table(force: bool = False) -> Dict[str, int]:
    """
    Load a mapping from layout constant name -> numeric layout id (index in gMapLayouts).

    FireRed's gMapHeader.mapLayoutId is a u16 that matches the index in the layouts table.
    We derive the mapping from the vendored pokefirered `data/layouts/layouts.json`.
    """
    global _layout_id_table
    if _layout_id_table is not None and not force:
        return _layout_id_table

    try:
        repo_root = Path(__file__).resolve().parents[1]
        layouts_path = repo_root / "pokefirered" / "data" / "layouts" / "layouts.json"
        if not layouts_path.exists():
            _layout_id_table = {}
            return _layout_id_table
        with open(layouts_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        _layout_id_table = {}
        return _layout_id_table

    layouts = raw.get("layouts") if isinstance(raw, dict) else None
    table: Dict[str, int] = {}
    if isinstance(layouts, list):
        for idx, entry in enumerate(layouts):
            if not isinstance(entry, dict):
                continue
            layout_id = entry.get("id")
            if isinstance(layout_id, str) and layout_id:
                table[layout_id] = int(idx)

    _layout_id_table = table
    return _layout_id_table


def get_layout_id(layout_constant: str) -> Optional[int]:
    """
    Return the numeric layout id for a given `LAYOUT_*` constant name, or None if unknown.
    """
    return load_layout_id_table().get(layout_constant)


def get_map_name(group: int, num: int) -> Optional[str]:
    tables = load_reference_tables()
    return tables.map_names.get(group, {}).get(num)


def get_event_object_name(graphics_id: int) -> Optional[str]:
    return load_reference_tables().event_object_names.get(graphics_id)


def get_ability_name(ability_id: int) -> Optional[str]:
    return load_reference_tables().ability_names.get(ability_id)


def get_item_name(item_id: int) -> Optional[str]:
    return load_reference_tables().item_names.get(item_id)


def get_move_name(move_id: int) -> Optional[str]:
    return load_reference_tables().move_names.get(move_id)


def get_species_name(species_id: int) -> Optional[str]:
    return load_reference_tables().species_names.get(species_id)


def get_behavior_name(behavior_id: int) -> Optional[str]:
    return load_metatile_behaviors().get(behavior_id)
