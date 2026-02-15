"""Persistent fog-of-war grids for map minimaps.

Stores one JSON file per map with the same shape as `fullMap.minimap_data.grid`,
using `null` (Python `None`) for undiscovered tiles.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, List, Optional

from . import config

FogGrid = List[List[Optional[int]]]

_LOCK_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def _lock_for_map(map_id: str) -> threading.RLock:
    with _LOCK_GUARD:
        lock = _LOCKS.get(map_id)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[map_id] = lock
        return lock


def map_id_for(group: int, number: int) -> str:
    return f"{int(group)}-{int(number)}"


def fog_path_for_map_id(map_id: str) -> Path:
    return config.MINIMAPS_DIR / f"{map_id}.json"


def _init_grid(*, width: int, height: int) -> FogGrid:
    w = max(0, int(width))
    h = max(0, int(height))
    return [[None for _ in range(w)] for _ in range(h)]


def _is_valid_grid(grid: object, *, width: int, height: int) -> bool:
    if not isinstance(grid, list):
        return False
    if len(grid) != int(height):
        return False
    for row in grid:
        if not isinstance(row, list) or len(row) != int(width):
            return False
        for cell in row:
            if cell is None:
                continue
            if isinstance(cell, bool):  # bool is int-subclass; reject explicitly
                return False
            if not isinstance(cell, int):
                return False
    return True


def _grid_shape_if_valid(grid: object) -> Optional[tuple[int, int]]:
    """
    Return (width, height) if `grid` looks like a valid fog grid, else None.

    Unlike `_is_valid_grid`, this does not require an expected shape.
    """
    if not isinstance(grid, list):
        return None

    height = len(grid)
    width: Optional[int] = None

    for row in grid:
        if not isinstance(row, list):
            return None
        if width is None:
            width = len(row)
        elif len(row) != width:
            return None
        for cell in row:
            if cell is None:
                continue
            if isinstance(cell, bool):  # bool is int-subclass; reject explicitly
                return None
            if not isinstance(cell, int):
                return None

    return (int(width or 0), int(height))


def load_or_init_grid(*, map_id: str, width: int, height: int) -> FogGrid:
    """
    Load a fog grid from disk or create a new one if missing/invalid.

    The file format is the raw grid (JSON array-of-arrays), not an object wrapper.
    """
    path = fog_path_for_map_id(map_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    lock = _lock_for_map(map_id)
    with lock:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if _is_valid_grid(data, width=width, height=height):
                    return data  # type: ignore[return-value]
            except Exception:
                pass

        grid = _init_grid(width=width, height=height)
        save_grid(map_id=map_id, grid=grid)
        return grid


def save_grid(*, map_id: str, grid: FogGrid) -> None:
    path = fog_path_for_map_id(map_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    lock = _lock_for_map(map_id)
    with lock:
        tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(grid, handle, ensure_ascii=False)
        os.replace(tmp, path)


def update_grid(
    *,
    map_id: str,
    width: int,
    height: int,
    persist: bool = True,
    updater: Callable[[FogGrid], None],
    out_info: dict[str, Any] | None = None,
) -> FogGrid:
    lock = _lock_for_map(map_id)
    with lock:
        path = fog_path_for_map_id(map_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        expected_w = max(0, int(width))
        expected_h = max(0, int(height))

        allow_write = bool(persist)

        grid: FogGrid
        should_persist = allow_write
        shape_mismatch = False
        loaded_shape: Optional[tuple[int, int]] = None

        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                # Corrupt/unreadable JSON: keep a backup and re-init.
                backup = path.with_name(f".{path.name}.corrupt.{os.getpid()}")
                if allow_write:
                    try:
                        os.replace(path, backup)
                    except Exception:
                        pass
                grid = _init_grid(width=expected_w, height=expected_h)
            else:
                loaded_shape = _grid_shape_if_valid(data)
                if loaded_shape == (expected_w, expected_h):
                    grid = data  # type: ignore[assignment]
                elif loaded_shape is not None:
                    # Shape mismatch: do NOT overwrite on disk. This can happen transiently during
                    # map transitions when we momentarily read the wrong map dimensions.
                    grid = _init_grid(width=expected_w, height=expected_h)
                    should_persist = False
                    shape_mismatch = True
                else:
                    # Not a grid: treat as corrupt and reset (but keep backup for forensics).
                    backup = path.with_name(f".{path.name}.corrupt.{os.getpid()}")
                    if allow_write:
                        try:
                            os.replace(path, backup)
                        except Exception:
                            pass
                    grid = _init_grid(width=expected_w, height=expected_h)
        else:
            grid = _init_grid(width=expected_w, height=expected_h)

        if out_info is not None:
            out_info["persisted"] = bool(should_persist)
            out_info["shape_mismatch"] = bool(shape_mismatch)
            out_info["expected_shape"] = (int(expected_w), int(expected_h))
            out_info["loaded_shape"] = loaded_shape

        updater(grid)
        if should_persist:
            save_grid(map_id=map_id, grid=grid)
        return grid


def refresh_discovered(
    grid: FogGrid,
    get_code: Callable[[int, int], int],
    on_change: Callable[[int, int, int, int], None] | None = None,
) -> None:
    """
    Update all discovered cells (non-None) using the latest RAM-derived code.
    """
    cb = on_change
    for y, row in enumerate(grid):
        for x, old_val in enumerate(row):
            if old_val is None:
                continue
            new_val = int(get_code(x, y))
            if cb is not None and old_val != new_val:
                cb(int(x), int(y), int(old_val), int(new_val))
            row[x] = new_val


def discover_rect(
    grid: FogGrid,
    *,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    map_width: int,
    map_height: int,
    get_code: Callable[[int, int], int],
    on_discover: Callable[[int, int], None] | None = None,
) -> None:
    """
    Discover tiles inside a viewport rectangle. Only writes where the fog cell is None.
    Rectangle is [start, end) (end exclusive), in absolute map coords.
    """
    w = int(map_width)
    h = int(map_height)
    if w <= 0 or h <= 0:
        return

    sx = int(start_x)
    sy = int(start_y)
    ex = int(end_x)
    ey = int(end_y)

    cb = on_discover
    for y in range(sy, ey):
        if y < 0 or y >= h:
            continue
        row = grid[y]
        for x in range(sx, ex):
            if x < 0 or x >= w:
                continue
            if row[x] is None:
                row[x] = int(get_code(x, y))
                if cb is not None:
                    cb(x, y)
