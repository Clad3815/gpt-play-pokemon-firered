from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ModuleNotFoundError:  # pragma: no cover - optional for unit tests
    FastAPI = None  # type: ignore[assignment,misc]
    CORSMiddleware = None  # type: ignore[assignment,misc]

try:
    from pydantic import BaseModel
except ModuleNotFoundError:  # pragma: no cover - optional for unit tests
    BaseModel = object  # type: ignore[assignment,misc]

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional for unit tests
    load_dotenv = None  # type: ignore[assignment,misc]

if load_dotenv is not None:
    # Load root `.env` before importing bridge modules that read env at import time.
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)

from firered_bridge.game_data import ensure_game_data_loaded
from firered_bridge import game_data
from firered_bridge.game_state import (
    build_full_state,
    build_input_trace_state,
    mgba_control,
    mgba_control_status,
    update_fog_of_war_for_current_map,
)
from firered_bridge.constants.tiles import (
    MINIMAP_CODE_BOULDER,
    MINIMAP_CODE_NPC,
    MINIMAP_CODE_TEMPORARY_WALL,
    MINIMAP_CODE_WALL,
    MINIMAP_TILES,
)
from firered_bridge.mgba_client import mgba_hold_button, mgba_press_buttons
from firered_bridge.mgba_client import mgba_reset, mgba_save_state_file, mgba_screenshot
from firered_bridge.player import snapshot as player_snapshot
from firered_bridge.world import collision as world_collision
from firered_bridge.world import map_read as world_map_read


def _facing_to_orientation_id(facing: object) -> int:
    match str(facing or "").strip().lower():
        case "down":
            return 100
        case "up":
            return 101
        case "left":
            return 102
        case "right":
            return 103
        case _:
            return 100


class _MinimapSnapshotStore:
    """
    Thread-safe minimap snapshot cache.

    Important: this cache must be served without touching mGBA so it remains responsive
    while `/sendCommands` is executing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._data: Dict[str, Any] | None = None

    def update(
        self,
        *,
        map_id: str | None = None,
        map_name: str | None = None,
        player_x: int | None = None,
        player_y: int | None = None,
        orientation: int | None = None,
        visibility_reduced: bool | None = None,
        visibility_window_width_tiles: int | None = None,
        visibility_window_height_tiles: int | None = None,
        visibility_hint: str | None = None,
        grid: object | None = None,
    ) -> None:
        updated = False
        now_ms = int(time.time() * 1000.0)

        with self._lock:
            next_data: Dict[str, Any] = dict(self._data or {})

            if map_id is not None and next_data.get("map_id") != map_id:
                next_data["map_id"] = map_id
                updated = True
            if map_name is not None and next_data.get("map_name") != map_name:
                next_data["map_name"] = map_name
                updated = True
            if player_x is not None and next_data.get("player_x") != int(player_x):
                next_data["player_x"] = int(player_x)
                updated = True
            if player_y is not None and next_data.get("player_y") != int(player_y):
                next_data["player_y"] = int(player_y)
                updated = True
            if orientation is not None and next_data.get("orientation") != int(orientation):
                next_data["orientation"] = int(orientation)
                updated = True

            if visibility_reduced is not None and next_data.get("visibility_reduced") != bool(visibility_reduced):
                next_data["visibility_reduced"] = bool(visibility_reduced)
                updated = True
            if (
                visibility_window_width_tiles is not None
                and next_data.get("visibility_window_width_tiles") != int(visibility_window_width_tiles)
            ):
                next_data["visibility_window_width_tiles"] = int(visibility_window_width_tiles)
                updated = True
            if (
                visibility_window_height_tiles is not None
                and next_data.get("visibility_window_height_tiles") != int(visibility_window_height_tiles)
            ):
                next_data["visibility_window_height_tiles"] = int(visibility_window_height_tiles)
                updated = True
            if visibility_hint is not None and next_data.get("visibility_hint") != str(visibility_hint):
                next_data["visibility_hint"] = str(visibility_hint)
                updated = True

            if grid is not None:
                # Store by reference. Endpoint will deep-copy on read to avoid concurrent mutation issues.
                next_data["grid"] = grid
                updated = True

            if not updated:
                return

            self._seq += 1
            next_data["seq"] = int(self._seq)
            next_data["updatedAtMs"] = now_ms
            self._data = next_data

    def snapshot(self) -> Dict[str, Any] | None:
        with self._lock:
            cur = self._data
            if not cur:
                return None
            out = dict(cur)

        grid = out.get("grid")
        if isinstance(grid, list):
            try:
                grid_copy: List[List[int | None]] = []
                for row in grid:
                    if not isinstance(row, list):
                        grid_copy = []
                        break
                    grid_copy.append(list(row))
                out["grid"] = grid_copy
                out["height"] = len(grid_copy)
                out["width"] = len(grid_copy[0]) if grid_copy and isinstance(grid_copy[0], list) else 0
                out["hasGrid"] = bool(grid_copy)
            except Exception:
                out["grid"] = None
                out["height"] = 0
                out["width"] = 0
                out["hasGrid"] = False
        else:
            out["grid"] = None
            out["height"] = 0
            out["width"] = 0
            out["hasGrid"] = False

        return out


_MINIMAP_SNAPSHOT = _MinimapSnapshotStore()

_SAVESTATE_BACKUP_LOCK = threading.Lock()
_LAST_SAVESTATE_BACKUP_TS: float | None = None


def _update_minimap_snapshot_from_trace(state: Dict[str, Any]) -> None:
    if not isinstance(state, dict):
        return
    player = state.get("player") if isinstance(state.get("player"), dict) else {}
    m = state.get("map") if isinstance(state.get("map"), dict) else {}

    pos = player.get("position")
    if isinstance(pos, list) and len(pos) >= 2:
        try:
            player_x = int(pos[0])
            player_y = int(pos[1])
        except Exception:
            player_x = None
            player_y = None
    else:
        player_x = None
        player_y = None

    g = m.get("group")
    n = m.get("number")
    map_id = f"{int(g)}-{int(n)}" if isinstance(g, int) and isinstance(n, int) else None
    map_name = m.get("name") if isinstance(m.get("name"), str) else None
    facing = player.get("facing")
    orientation = _facing_to_orientation_id(facing) if isinstance(facing, str) and facing.strip() else None

    _MINIMAP_SNAPSHOT.update(
        map_id=map_id,
        map_name=map_name,
        player_x=player_x,
        player_y=player_y,
        orientation=orientation,
    )


def _update_minimap_snapshot_from_full_state(state: Dict[str, Any]) -> None:
    if not isinstance(state, dict):
        return

    player = state.get("player") if isinstance(state.get("player"), dict) else {}
    m = state.get("map") if isinstance(state.get("map"), dict) else {}

    pos = player.get("position")
    if isinstance(pos, list) and len(pos) >= 2:
        try:
            player_x = int(pos[0])
            player_y = int(pos[1])
        except Exception:
            player_x = None
            player_y = None
    else:
        player_x = None
        player_y = None

    g = m.get("group")
    n = m.get("number")
    map_id = f"{int(g)}-{int(n)}" if isinstance(g, int) and isinstance(n, int) else None
    map_name = m.get("name") if isinstance(m.get("name"), str) else None
    facing = player.get("facing")
    orientation = _facing_to_orientation_id(facing) if isinstance(facing, str) and facing.strip() else None

    full_map = m.get("fullMap") if isinstance(m.get("fullMap"), dict) else {}
    minimap_data = full_map.get("minimap_data") if isinstance(full_map.get("minimap_data"), dict) else {}
    grid = minimap_data.get("grid")

    visibility = m.get("visibility") if isinstance(m.get("visibility"), dict) else {}
    reduced = bool(visibility.get("reduced")) if isinstance(visibility, dict) else None
    vw = visibility.get("widthTiles") if isinstance(visibility, dict) else None
    vh = visibility.get("heightTiles") if isinstance(visibility, dict) else None
    hint = visibility.get("hint") if isinstance(visibility, dict) else None
    try:
        vw_int = int(vw) if vw is not None else None
    except Exception:
        vw_int = None
    try:
        vh_int = int(vh) if vh is not None else None
    except Exception:
        vh_int = None
    hint_str = str(hint) if isinstance(hint, str) and hint else None

    _MINIMAP_SNAPSHOT.update(
        map_id=map_id,
        map_name=map_name,
        player_x=player_x,
        player_y=player_y,
        orientation=orientation,
        visibility_reduced=reduced,
        visibility_window_width_tiles=vw_int,
        visibility_window_height_tiles=vh_int,
        visibility_hint=hint_str,
        grid=grid,
    )

def _setup_bench_logging() -> None:
    if os.environ.get("FIRERED_BENCHMARK", "0") != "1":
        return
    logger = logging.getLogger("firered_bridge.bench")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False


class SendCommandsBody(BaseModel):
    # Accepted formats:
    # - `commands: string[]` (e.g. ["up", "a_until_end_of_dialog"])
    # - `commands: object[]` (e.g. {type: "control", command: "up"})
    # Both are normalized in `send_commands`.
    commands: List[Any]


_AFTER_TAP_DELAY_S = 2.0
_AFTER_TAP_BUTTONS = {"a", "b", "l", "r", "start", "select"}
_DIRECTIONAL_CONTROL_COMMANDS = {"up", "down", "left", "right"}
_OVERWORLD_SMART_CONTROL_COMMANDS = {
    "up",
    "down",
    "left",
    "right",
    "face_up",
    "face_down",
    "face_left",
    "face_right",
}
# Wait long enough for forced overworld motions (spinner tiles, scripted turns/moves)
# before issuing the next queued directional control input.
_MOVE_CONTROL_IDLE_TIMEOUT_S = 3.0
_MOVE_CHANGE_TIMEOUT_S = 0.2
_MOVE_LOCK_GRACE_S = 0.12


def _sleep_remaining_since(since: float, *, total_s: float) -> None:
    remaining = float(total_s) - (time.monotonic() - float(since))
    if remaining > 0:
        time.sleep(remaining)


def _should_delay_after_buttons(buttons: object) -> bool:
    if not isinstance(buttons, list):
        return False
    for b in buttons:
        if not isinstance(b, str):
            continue
        if b.strip().lower() in _AFTER_TAP_BUTTONS:
            return True
    return False


def _buttons_include_a(buttons: object) -> bool:
    if not isinstance(buttons, list):
        return False
    for b in buttons:
        if isinstance(b, str) and b.strip().lower() == "a":
            return True
    return False


def _is_a_like_command(ctype: object, cmd: Dict[str, Any]) -> bool:
    if ctype == "press":
        return _buttons_include_a(cmd.get("buttons"))
    if ctype == "control":
        normalized = _normalize_control_command(str(cmd.get("command") or ""))
        return normalized in {"a", "a_until_end_of_dialog"}
    return False


def _should_capture_before_passability_snapshot(
    *,
    ctype: object,
    cmd: Dict[str, Any],
    before_state: Dict[str, Any],
) -> bool:
    if not _is_a_like_command(ctype, cmd):
        return False
    if ctype == "control":
        normalized = _normalize_control_command(str(cmd.get("command") or ""))
        if normalized == "a_until_end_of_dialog":
            return True

    dialog = before_state.get("dialog") if isinstance(before_state, dict) else {}
    emulator = before_state.get("emulator") if isinstance(before_state, dict) else {}
    in_dialog = bool(dialog.get("inDialog")) if isinstance(dialog, dict) else False
    field_locked = bool(emulator.get("fieldControlsLocked")) if isinstance(emulator, dict) else False
    all_locked = bool(emulator.get("allControlsLocked")) if isinstance(emulator, dict) else False
    return in_dialog or field_locked or all_locked


def _is_passable_minimap_code(code: int) -> bool:
    td = MINIMAP_TILES.get(int(code))
    if td is not None:
        return bool(td.passability)
    return int(code) not in {
        MINIMAP_CODE_WALL,
        MINIMAP_CODE_TEMPORARY_WALL,
        MINIMAP_CODE_NPC,
        MINIMAP_CODE_BOULDER,
    }


def _capture_map_passability_snapshot() -> Optional[Dict[str, Any]]:
    """
    Snapshot current map passability grid from live RAM.
    Used as a fallback for A-triggered scripted setmetatile changes.
    """
    try:
        snap = player_snapshot._read_player_snapshot()
        map_group = int(snap["map_group"])
        map_num = int(snap["map_num"])
        map_name = game_data.get_map_name(map_group, map_num) or f"Unknown({map_group}-{map_num})"

        main_w, main_h, main_tiles, main_beh, _bw, _bh, _bt = world_map_read._read_map_tiles_and_behaviors_fast()
        if int(main_w) <= 0 or int(main_h) <= 0 or not isinstance(main_tiles, list) or not main_tiles:
            return None

        col = world_collision.process_tiles_to_collision_map(
            main_tiles,
            int(main_w),
            main_beh if isinstance(main_beh, list) else [],
            int(snap.get("elevation", 0) or 0),
            bool(snap.get("surfing")),
            include_map_data=False,
        )
        grid = col.get("minimap_data", {}).get("grid", []) if isinstance(col.get("minimap_data"), dict) else []
        width = int(col.get("width", 0) or 0)
        height = int(col.get("height", 0) or 0)
        if width <= 0 or height <= 0 or not isinstance(grid, list):
            return None

        passable: List[List[bool]] = []
        for row in grid:
            if not isinstance(row, list):
                return None
            passable.append([_is_passable_minimap_code(int(code)) for code in row])

        return {
            "mapId": f"{map_group}-{map_num}",
            "mapName": str(map_name),
            "width": int(width),
            "height": int(height),
            "passable": passable,
        }
    except Exception:
        return None

def _diff_passability_transitions(
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
) -> tuple[List[tuple[int, int]], List[tuple[int, int]]]:
    if not before or not after:
        return ([], [])
    if before.get("mapId") != after.get("mapId"):
        return ([], [])

    bw = int(before.get("width", 0) or 0)
    bh = int(before.get("height", 0) or 0)
    aw = int(after.get("width", 0) or 0)
    ah = int(after.get("height", 0) or 0)
    if bw <= 0 or bh <= 0 or aw <= 0 or ah <= 0:
        return ([], [])

    w = min(bw, aw)
    h = min(bh, ah)
    bgrid = before.get("passable")
    agrid = after.get("passable")
    if not isinstance(bgrid, list) or not isinstance(agrid, list):
        return ([], [])

    walls_to_free: List[tuple[int, int]] = []
    free_to_walls: List[tuple[int, int]] = []
    for y in range(h):
        if y >= len(bgrid) or y >= len(agrid):
            break
        brow = bgrid[y]
        arow = agrid[y]
        if not isinstance(brow, list) or not isinstance(arow, list):
            continue
        for x in range(w):
            if x >= len(brow) or x >= len(arow):
                break
            old_passable = bool(brow[x])
            new_passable = bool(arow[x])
            if (not old_passable) and new_passable:
                walls_to_free.append((int(x), int(y)))
            elif old_passable and (not new_passable):
                free_to_walls.append((int(x), int(y)))
    return (walls_to_free, free_to_walls)


def _normalize_control_command(command: str) -> str:
    return command.strip().lower().replace("-", "_")


def _is_directional_control_command(command: object) -> bool:
    if not isinstance(command, str):
        return False
    return _normalize_control_command(command) in _DIRECTIONAL_CONTROL_COMMANDS


def _trace_map_tuple(state: Dict[str, Any]) -> tuple[int, int] | None:
    m = state.get("map") or {}
    g = m.get("group")
    n = m.get("number")
    if isinstance(g, int) and isinstance(n, int):
        return (g, n)
    return None


def _trace_position_tuple(state: Dict[str, Any]) -> tuple[int, int] | None:
    p = (state.get("player") or {}).get("position")
    if (
        isinstance(p, list)
        and len(p) >= 2
        and isinstance(p[0], int)
        and isinstance(p[1], int)
    ):
        return (int(p[0]), int(p[1]))
    return None


def _append_step_trace_event(step: Dict[str, Any], message: str) -> None:
    trace = step.get("trace") if isinstance(step.get("trace"), dict) else {}
    events = trace.get("events") if isinstance(trace.get("events"), list) else []
    events.append(str(message))
    trace["events"] = events
    step["trace"] = trace


def _parse_control_status(status: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (status or "").split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k] = v
    return out


def _wait_for_control_idle(timeout_s: float = 3.0, poll_s: float = 0.02) -> Dict[str, Any]:
    """
    Poll `bridge.controlStatus` until Lua control queue is idle.

    Note: This does *not* wait for the generic keyEventQueue used by press/hold/taps.
    """
    start = time.monotonic()
    last_raw: str | None = None
    last_parsed: Dict[str, str] | None = None

    while (time.monotonic() - start) < timeout_s:
        raw = mgba_control_status()
        parsed = _parse_control_status(raw)
        last_raw, last_parsed = raw, parsed
        if parsed.get("queue") == "0" and parsed.get("active") == "none":
            return {
                "ok": True,
                "timedOut": False,
                "raw": raw,
                "parsed": parsed,
                "waitMs": int((time.monotonic() - start) * 1000.0),
            }
        time.sleep(poll_s)

    return {
        "ok": False,
        "timedOut": True,
        "raw": last_raw,
        "parsed": last_parsed,
        "waitMs": int((time.monotonic() - start) * 1000.0),
    }


def _trace_key_fields(state: Dict[str, Any]) -> Dict[str, Any]:
    player = state.get("player") or {}
    emulator = state.get("emulator") or {}
    dialog = state.get("dialog") or {}
    return {
        "pos": tuple(player.get("position") or (None, None)),
        "facing": player.get("facing"),
        "fieldLocked": emulator.get("fieldControlsLocked"),
        "allLocked": emulator.get("allControlsLocked"),
        "inBattle": emulator.get("inBattle"),
        "inDialog": dialog.get("inDialog"),
        "menuType": dialog.get("menuType"),
        "visibleText": dialog.get("visibleText"),
    }


def _wait_for_trace_change(before_state: Dict[str, Any], timeout_s: float, poll_s: float = 0.05) -> Dict[str, Any]:
    """
    Poll `build_input_trace_state()` until a meaningful change is observed, or timeout.
    """
    before_key = _trace_key_fields(before_state)
    start = time.monotonic()
    last = before_state
    while (time.monotonic() - start) < timeout_s:
        cur = build_input_trace_state()
        last = cur
        if _trace_key_fields(cur) != before_key:
            return cur
        time.sleep(poll_s)
    return last


def _wait_for_trace_change_or_lock(before_state: Dict[str, Any], timeout_s: float, poll_s: float = 0.02) -> Dict[str, Any]:
    """
    Poll until a meaningful trace change is observed OR a full input lock appears, or timeout.
    """
    before_key = _trace_key_fields(before_state)
    start = time.monotonic()
    last = before_state
    while (time.monotonic() - start) < timeout_s:
        cur = build_input_trace_state()
        last = cur
        if _trace_key_fields(cur) != before_key:
            return cur
        if _is_all_controls_locked(cur):
            return cur
        time.sleep(poll_s)
    return last


def _is_all_controls_locked(state: Dict[str, Any]) -> bool:
    emulator = state.get("emulator") or {}
    return bool(emulator.get("allControlsLocked"))


def _wait_for_all_controls_unlocked(start_state: Dict[str, Any], timeout_s: float, poll_s: float = 0.05) -> Dict[str, Any]:
    """
    Poll `build_input_trace_state()` until `emulator.allControlsLocked` becomes False, or timeout.
    """
    start = time.monotonic()
    last = start_state
    while (time.monotonic() - start) < timeout_s:
        if not _is_all_controls_locked(last):
            return last
        time.sleep(poll_s)
        last = build_input_trace_state()
    return last


def _wait_for_lock_transition_window(
    start_state: Dict[str, Any], window_s: float, poll_s: float = 0.02, stable_polls_required: int = 2
) -> tuple[Dict[str, Any], bool]:
    """
    Observe a short post-change window to catch late lock transitions.
    Returns (last_state, lock_detected).
    """
    start = time.monotonic()
    last = start_state
    last_key = _trace_key_fields(start_state)
    stable_unlocked_polls = 0
    if _is_all_controls_locked(last):
        return (last, True)
    while (time.monotonic() - start) < max(0.0, float(window_s)):
        time.sleep(poll_s)
        cur = build_input_trace_state()
        last = cur
        if _is_all_controls_locked(cur):
            return (cur, True)
        cur_key = _trace_key_fields(cur)
        if cur_key == last_key:
            stable_unlocked_polls += 1
        else:
            stable_unlocked_polls = 0
            last_key = cur_key
        if stable_unlocked_polls >= max(1, int(stable_polls_required)):
            return (cur, False)
    return (last, False)


def _wait_for_after_state(
    before_state: Dict[str, Any],
    *,
    change_timeout_s: float,
    unlock_timeout_s: float,
    lock_grace_s: float = 0.6,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Wait for a post-input state suitable for `/sendCommands` "after":

    - Wait for a meaningful change OR a full input lock.
    - Then watch a short grace window for delayed locks (race: lock can appear after first state change).
    - If fully locked, wait until inputs are unlocked again.

    Returns `(after_state, wait_info)`.
    """
    wait_info: Dict[str, Any] = {
        "lockDetected": False,
        "waitedForUnlock": False,
        "unlockTimedOut": False,
        "lockGraceWindowMs": int(max(0.0, float(lock_grace_s)) * 1000.0),
        "changeWaitMs": 0,
        "lockWindowMs": 0,
        "unlockWaitMs": 0,
    }

    change_started = time.monotonic()
    after0 = _wait_for_trace_change_or_lock(before_state, timeout_s=change_timeout_s)
    wait_info["changeWaitMs"] = int((time.monotonic() - change_started) * 1000.0)

    if _is_all_controls_locked(after0):
        wait_info["lockDetected"] = True
        wait_info["waitedForUnlock"] = True
        unlock_started = time.monotonic()
        unlocked = _wait_for_all_controls_unlocked(after0, timeout_s=unlock_timeout_s)
        wait_info["unlockWaitMs"] = int((time.monotonic() - unlock_started) * 1000.0)
        wait_info["unlockTimedOut"] = bool(_is_all_controls_locked(unlocked))
        return (unlocked, wait_info)

    lock_window_started = time.monotonic()
    after1, late_lock_detected = _wait_for_lock_transition_window(after0, window_s=lock_grace_s)
    wait_info["lockWindowMs"] = int((time.monotonic() - lock_window_started) * 1000.0)
    if late_lock_detected:
        wait_info["lockDetected"] = True
        wait_info["waitedForUnlock"] = True
        unlock_started = time.monotonic()
        unlocked = _wait_for_all_controls_unlocked(after1, timeout_s=unlock_timeout_s)
        wait_info["unlockWaitMs"] = int((time.monotonic() - unlock_started) * 1000.0)
        wait_info["unlockTimedOut"] = bool(_is_all_controls_locked(unlocked))
        return (unlocked, wait_info)

    return (after1, wait_info)

def _repo_root_dir() -> Path:
    # firered_mgba_bridge.py lives at the repository root.
    return Path(__file__).resolve().parent


def _to_mgba_host_path(path: Path) -> str:
    """
    Convert a WSL path (/mnt/c/...) to a Windows path (C:/...) for the mGBA Lua runtime.

    If not running under WSL, returns the path as POSIX/OS-native string.
    """
    s = str(path)
    # Typical WSL mount: /mnt/c/...
    if s.startswith("/mnt/") and len(s) > 7 and s[5].isalpha() and s[6] == "/":
        drive = s[5].upper()
        rest = s[7:]  # skip "/mnt/<drive>/"
        return f"{drive}:/{rest}"
    return s


def _wait_for_file_ready(path: Path, timeout_s: float = 0.75, poll_s: float = 0.02) -> bool:
    """
    Wait for `path` to exist and have a stable non-zero size.
    """
    start = time.monotonic()
    last_size = -1
    while (time.monotonic() - start) < timeout_s:
        try:
            if path.exists():
                size = path.stat().st_size
                if size > 0 and size == last_size:
                    return True
                last_size = size
        except Exception:
            pass
        time.sleep(poll_s)
    try:
        return path.exists() and path.stat().st_size > 0
    except Exception:
        return False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _list_savestate_backups(backup_dir: Path) -> List[Path]:
    """
    Return existing savestate backup files, newest first.
    """
    try:
        if not backup_dir.exists():
            return []
        files: List[Path] = []
        for p in backup_dir.iterdir():
            if not p.is_file():
                continue
            if not p.name.startswith("savestate_"):
                continue
            if p.suffix.lower() != ".ss0":
                continue
            files.append(p)
        with_mtime: List[tuple[float, Path]] = []
        for p in files:
            try:
                with_mtime.append((float(p.stat().st_mtime), p))
            except Exception:
                pass
        with_mtime.sort(key=lambda item: item[0], reverse=True)
        return [p for _, p in with_mtime]
    except Exception:
        return []


def _prune_savestate_backups(backup_dir: Path, keep: int) -> int:
    keep = max(0, int(keep))
    backups = _list_savestate_backups(backup_dir)
    deleted = 0
    for p in backups[keep:]:
        try:
            p.unlink()
            deleted += 1
        except Exception:
            pass
    return deleted


def _maybe_backup_savestate() -> Dict[str, Any]:
    """
    Rate-limited savestate backup:
    - Create at most once every 5 minutes (default).
    - Keep only the 50 newest backups (default).
    """
    enabled = _env_bool("FIRERED_SAVESTATE_BACKUP_ENABLED", True)
    try:
        interval_s = int(
            os.environ.get(
                "FIRERED_SAVESTATE_BACKUP_INTERVAL_S",
                "300",
            )
        )
    except Exception:
        interval_s = 300
    try:
        keep = int(os.environ.get("FIRERED_SAVESTATE_BACKUP_KEEP", "50"))
    except Exception:
        keep = 50

    backup_dir = Path(
        os.environ.get(
            "FIRERED_SAVESTATE_BACKUP_DIR",
            str(_repo_root_dir() / "backup_saves"),
        )
    )

    info: Dict[str, Any] = {
        "enabled": bool(enabled),
        "dir": str(backup_dir),
        "intervalSeconds": int(interval_s),
        "keep": int(keep),
    }

    if not enabled:
        info.update({"skipped": True, "skipReason": "disabled"})
        return info

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        info.update({"ok": False, "error": f"Failed to create backup dir: {exc}"})
        return info

    global _LAST_SAVESTATE_BACKUP_TS
    with _SAVESTATE_BACKUP_LOCK:
        now = time.time()

        if _LAST_SAVESTATE_BACKUP_TS is None:
            backups = _list_savestate_backups(backup_dir)
            if backups:
                try:
                    _LAST_SAVESTATE_BACKUP_TS = float(backups[0].stat().st_mtime)
                except Exception:
                    _LAST_SAVESTATE_BACKUP_TS = None

        if _LAST_SAVESTATE_BACKUP_TS is not None and (now - _LAST_SAVESTATE_BACKUP_TS) < float(interval_s):
            info.update({"skipped": True, "skipReason": "interval"})
            try:
                info["lastBackupAtMs"] = int(_LAST_SAVESTATE_BACKUP_TS * 1000.0)
            except Exception:
                pass
            # Opportunistic pruning (cheap: max 50 files).
            info["deletedOldBackups"] = _prune_savestate_backups(backup_dir, keep)
            return info

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        raw_path = backup_dir / f"savestate_{timestamp}.ss0"
        mgba_path = _to_mgba_host_path(raw_path)

        resp = mgba_save_state_file(mgba_path)
        ok = bool(resp.get("ok")) and _wait_for_file_ready(raw_path, timeout_s=2.5)
        info["created"] = True
        info["ok"] = bool(ok)
        info["path"] = str(raw_path)
        info["mgba"] = resp
        if not ok:
            info["error"] = resp.get("error") or "Savestate file not ready"
            return info

        _LAST_SAVESTATE_BACKUP_TS = now
        info["deletedOldBackups"] = _prune_savestate_backups(backup_dir, keep)
        return info


def _append_transcript_entry(transcript: List[str], text: str) -> None:
    if not text:
        return
    if not transcript:
        transcript.append(text)
        return
    last = transcript[-1]
    if text == last:
        return
    if text.startswith(last) and len(text) > len(last):
        transcript[-1] = text
        return
    transcript.append(text)


def _run_a_until_end_of_dialog(
    *,
    timeout_s: Optional[float] = None,
    poll_s: float = 0.05,
    min_press_interval_s: float = _AFTER_TAP_DELAY_S,
    max_presses: int = 80,
) -> Dict[str, Any]:
    """
    Press A every `min_press_interval_s` seconds until:
    - a visible choice is detected ("►" in visibleText), or
    - dialog ends (dialog.inDialog becomes False).

    IMPORTANT:
    - This helper will always press "A" at least once, even if you're not currently in a dialog.
      This matches the intended UX: "start a dialog (if any) and advance it until it's done".

    For each press we capture a lightweight before/after snapshot (including visibleText).
    If `emulator.allControlsLocked` is True after the post-press wait, we wait until it
    becomes False before capturing the "after".
    """
    if timeout_s is None:
        timeout_s = max(12.0, (float(max_presses) * float(min_press_interval_s)) + 5.0)

    started_at = time.monotonic()
    events: List[str] = []
    transcript: List[str] = []
    presses: List[Dict[str, Any]] = []

    def _stop_reason_from_fields(fields: Dict[str, Any]) -> Optional[str]:
        if not bool(fields.get("inDialog")):
            return "dialogEnded"
        text = fields.get("visibleText")
        if isinstance(text, str) and "►" in text:
            return "choiceDetected"
        return None

    stop_reason: Optional[str] = None
    timed_out = False
    max_presses_hit = False
    last_state: Dict[str, Any] = {}

    while True:
        now = time.monotonic()
        if (now - started_at) >= timeout_s:
            timed_out = True
            stop_reason = "timeout"
            events.append("Timeout reached, stopping.")
            break
        if len(presses) >= max_presses:
            max_presses_hit = True
            stop_reason = "maxPresses"
            events.append("Max presses reached, stopping.")
            break

        before_state = build_input_trace_state()
        last_state = before_state
        before_fields = _trace_key_fields(before_state)

        pre_stop = _stop_reason_from_fields(before_fields)
        # Choice handling:
        # - If a choice is visible *before the first press*, allow pressing A once so this helper
        #   can be used to confirm the currently-highlighted option.
        # - If a choice is visible after we've already pressed at least once, stop before pressing again
        #   to avoid auto-selecting further options unintentionally.
        if pre_stop == "choiceDetected" and presses:
            stop_reason = pre_stop
            events.append("Choice detected, stopping.")
            break
        if pre_stop == "choiceDetected" and not presses:
            events.append("Choice detected at start; pressing A once to confirm selection.")
        # If we already pressed at least once and we're now out of dialog, stop.
        # (On the first iteration we might not be in dialog yet; we still want to press A once.)
        if pre_stop == "dialogEnded" and presses:
            stop_reason = pre_stop
            events.append("Dialog ended")
            break

        before_text = before_fields.get("visibleText")
        _append_transcript_entry(transcript, before_text if isinstance(before_text, str) else "")

        mgba_control("a")
        pressed_at = time.monotonic()
        _sleep_remaining_since(pressed_at, total_s=min_press_interval_s)

        after_state = build_input_trace_state()
        last_state = after_state
        if _is_all_controls_locked(after_state):
            remaining_s = float(timeout_s) - (time.monotonic() - started_at)
            if remaining_s <= 0:
                timed_out = True
                stop_reason = "timeout"
                events.append("Timeout reached while waiting for unlock, stopping.")
                break
            after_state = _wait_for_all_controls_unlocked(after_state, timeout_s=remaining_s, poll_s=poll_s)
            last_state = after_state
            if _is_all_controls_locked(after_state):
                timed_out = True
                stop_reason = "timeout"
                events.append("Timed out waiting for unlock, stopping.")
                break

        after_fields = _trace_key_fields(after_state)
        after_text = after_fields.get("visibleText")
        _append_transcript_entry(transcript, after_text if isinstance(after_text, str) else "")

        presses.append(
            {
                "index": len(presses),
                "before": before_fields,
                "after": after_fields,
            }
        )

        post_stop = _stop_reason_from_fields(after_fields)
        if post_stop is not None:
            stop_reason = post_stop
            if stop_reason == "choiceDetected":
                events.append("Choice detected, stopping.")
            elif stop_reason == "dialogEnded":
                events.append("Dialog ended")
            break

    duration_ms = int((time.monotonic() - started_at) * 1000.0)
    if presses:
        events.append(f"Pressed A x{len(presses)}")
    return {
        "ok": True,
        "stopReason": stop_reason,
        "timedOut": timed_out,
        "maxPressesHit": max_presses_hit,
        "pressCount": len(presses),
        "autoPressCount": len(presses),
        "durationMs": duration_ms,
        "events": events,
        "transcript": transcript,
        "presses": presses,
        "finalState": last_state,
    }


@asynccontextmanager
async def lifespan(app: Any):
    # Startup
    _setup_bench_logging()
    ensure_game_data_loaded()
    yield
    # Shutdown (rien à faire ici)

def request_data() -> Dict[str, Any]:
    try:
        state = build_full_state()

        # --- Savestate backup (rate-limited) ---
        state.setdefault("emulator", {})
        state["emulator"]["saveStateBackup"] = _maybe_backup_savestate()

        # --- Screenshot (raw) ---
        # /requestData updates a screenshot file and returns its path.
        # The Node loop reads it and performs upscale x3 + optional overlay in JS.
        screenshot_dir = Path(
            os.environ.get("FIRERED_SCREENSHOT_DIR", str(_repo_root_dir() / "tmp_screenshots"))
        )
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        raw_path = screenshot_dir / "gba_raw.png"
        mgba_path = _to_mgba_host_path(raw_path)

        shot = mgba_screenshot(mgba_path)
        ok = bool(shot.get("ok")) and _wait_for_file_ready(raw_path)
        state.setdefault("emulator", {})
        state["emulator"]["screenshotOk"] = bool(ok)
        state["emulator"]["screenshotRawPath"] = str(raw_path)
        if not ok:
            state["emulator"]["screenshotError"] = shot.get("error") or "Screenshot file not ready"

        # Keep these keys stable for the Node agent contract.
        player = state.get("player") if isinstance(state.get("player"), dict) else {}
        if isinstance(player, dict):
            # Strength: should reflect the real in-game flag (not just default False).
            if "strengthEnabled" not in player:
                try:
                    from firered_bridge.player.snapshot import _read_strength_enabled

                    player["strengthEnabled"] = bool(_read_strength_enabled())
                except Exception:
                    player["strengthEnabled"] = False

            # Movement mode: prefer the concrete bike type (ACRO_BIKE / MACH_BIKE) over "BIKE".
            movement_mode = player.get("movementMode")
            if (not isinstance(movement_mode, str)) or (not movement_mode) or movement_mode == "BIKE":
                bike_type: str | None = player.get("bikeType") if isinstance(player.get("bikeType"), str) else None
                if bike_type is None and bool(player.get("biking")):
                    try:
                        from firered_bridge.player.snapshot import get_player_bike_type

                        bike_type = get_player_bike_type()
                    except Exception:
                        bike_type = None

                if bool(player.get("diving")):
                    player["movementMode"] = "DIVE"
                elif bool(player.get("surfing")):
                    player["movementMode"] = "SURF"
                elif bool(player.get("biking")):
                    player["movementMode"] = bike_type or "BIKE"
                else:
                    player["movementMode"] = "WALK"

            state["player"] = player

        # Keep a cached minimap snapshot for the UI to poll without touching mGBA.
        _update_minimap_snapshot_from_full_state(state)
        return {"ok": True, "data": state}
    except Exception as exc:  # pragma: no cover - API level safeguard
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()}


def minimap_snapshot() -> Dict[str, Any]:
    """
    Return the latest cached minimap snapshot (grid + player position/orientation).

    This endpoint must remain responsive even while `/sendCommands` is executing, so it must
    not perform any mGBA reads. It only serves the in-memory cache updated by `/requestData`
    and `/sendCommands`.
    """
    try:
        return {"ok": True, "data": _MINIMAP_SNAPSHOT.snapshot()}
    except Exception as exc:  # pragma: no cover - API level safeguard
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()}


def send_commands(body: SendCommandsBody) -> Dict[str, Any]:
    sequence_before = build_input_trace_state()
    _update_minimap_snapshot_from_trace(sequence_before)
    started_in_dialog = bool((sequence_before.get("dialog") or {}).get("inDialog"))
    started_in_battle = bool((sequence_before.get("emulator") or {}).get("inBattle"))

    results: List[Dict[str, Any]] = []
    remaining_keys: List[Any] = []
    interrupted_by_dialog = False
    interrupted_by_battle = False
    interrupted_by_collision = False
    interrupted_at_index: int | None = None
    collision_streak: int = 0

    # Normalize string commands into bridge command objects.
    normalized_commands: List[Dict[str, Any]] = []
    for item in (body.commands or []):
        if isinstance(item, str):
            cmd_str = item.strip()
            if not cmd_str:
                continue
            normalized_commands.append({"type": "control", "command": cmd_str})
        elif isinstance(item, dict):
            normalized_commands.append(item)
        else:
            # ignore unknown entries
            continue

    for idx, cmd in enumerate(normalized_commands):
        step_started = time.monotonic()
        before = build_input_trace_state()

        ctype = cmd.get("type")
        cmd_dict = cmd if isinstance(cmd, dict) else {}
        before_passability_snapshot = (
            _capture_map_passability_snapshot()
            if _should_capture_before_passability_snapshot(ctype=ctype, cmd=cmd_dict, before_state=before)
            else None
        )
        step: Dict[str, Any] = {
            "index": idx,
            "type": ctype,
            "command": cmd,
            "before": before,
        }

        after: Dict[str, Any] | None = None
        control_wait_info: Dict[str, Any] | None = None
        after_wait_info: Dict[str, Any] | None = None

        if ctype == "press":
            buttons = cmd.get("buttons", [])
            if not isinstance(buttons, list) or not buttons:
                step.update({"ok": False, "error": "Invalid buttons"})
            else:
                mgba_result = mgba_press_buttons(buttons)
                pressed_at = time.monotonic()
                step["mgba"] = mgba_result
                step["ok"] = bool(mgba_result.get("ok"))
                if _should_delay_after_buttons(buttons):
                    _sleep_remaining_since(pressed_at, total_s=_AFTER_TAP_DELAY_S)
                after, after_wait_info = _wait_for_after_state(
                    before,
                    change_timeout_s=0.75,
                    unlock_timeout_s=8.0,
                    lock_grace_s=0.6,
                )
        elif ctype == "hold":
            button = cmd.get("button")
            frames = int(cmd.get("frames", 60))
            if not button:
                step.update({"ok": False, "error": "Invalid hold button"})
            else:
                mgba_result = mgba_hold_button(button, frames)
                step["mgba"] = mgba_result
                step["ok"] = bool(mgba_result.get("ok"))
                # Wait roughly for the hold to complete, but still break early on visible changes.
                approx_s = max(0.6, (frames / 60.0) + 0.2)
                hold_lock_grace_s = min(1.0, max(0.3, (max(1, frames) / 60.0) * 0.25))
                after, after_wait_info = _wait_for_after_state(
                    before,
                    change_timeout_s=min(10.0, approx_s),
                    unlock_timeout_s=8.0,
                    lock_grace_s=hold_lock_grace_s,
                )
        elif ctype == "control":
            command = cmd.get("command")
            if not isinstance(command, str) or not command.strip():
                step.update({"ok": False, "error": "Invalid control command"})
            else:
                normalized = _normalize_control_command(command)
                try:
                    if normalized == "a_until_end_of_dialog":
                        # Special: press A every ~2s, capturing before/after visibleText for each press,
                        # until a visible choice appears ("►") or dialog ends.
                        trace = _run_a_until_end_of_dialog()
                        step["mgba"] = {"ok": True, "endpoint": "control", "command": normalized}
                        step["trace"] = trace
                        step["ok"] = bool(trace.get("ok"))
                        after = trace.get("finalState") or build_input_trace_state()
                    else:
                        pressed_at: float | None = None
                        mgba_control(command)
                        if normalized in _AFTER_TAP_BUTTONS:
                            pressed_at = time.monotonic()
                        step["mgba"] = {"ok": True, "endpoint": "control"}

                        # For overworld-smart commands, wait for Lua control queue to go idle.
                        if normalized in _OVERWORLD_SMART_CONTROL_COMMANDS:
                            control_wait_info = _wait_for_control_idle(timeout_s=_MOVE_CONTROL_IDLE_TIMEOUT_S)
                            after, after_wait_info = _wait_for_after_state(
                                before,
                                change_timeout_s=_MOVE_CHANGE_TIMEOUT_S,
                                unlock_timeout_s=8.0,
                                lock_grace_s=_MOVE_LOCK_GRACE_S,
                            )
                        else:
                            # For taps (A/B/Start/Select/L/R), wait for observable state changes (dialogs, etc.).
                            if pressed_at is not None:
                                _sleep_remaining_since(pressed_at, total_s=_AFTER_TAP_DELAY_S)
                            after, after_wait_info = _wait_for_after_state(
                                before,
                                change_timeout_s=0.75,
                                unlock_timeout_s=8.0,
                                lock_grace_s=0.6,
                            )

                        step["ok"] = True
                except Exception as exc:
                    step.update({"ok": False, "error": str(exc)})
        elif ctype == "controlStatus":
            try:
                status = mgba_control_status()
                step["ok"] = True
                step["status"] = status
            except Exception as exc:
                step.update({"ok": False, "error": str(exc)})
        else:
            step.update({"ok": False, "error": f"Unknown type {ctype}"})

        if after is None:
            # Fall back to a simple post-action snapshot (even on error) for debuggability.
            try:
                after = build_input_trace_state()
            except Exception:
                after = {}

        step["after"] = after
        _update_minimap_snapshot_from_trace(after)
        wait_payload: Dict[str, Any] = {}
        if control_wait_info is not None:
            wait_payload["controlIdle"] = control_wait_info
        if after_wait_info is not None:
            wait_payload["afterState"] = after_wait_info
            if bool(after_wait_info.get("lockDetected")):
                _append_step_trace_event(step, "inputLockDetected")
            if bool(after_wait_info.get("waitedForUnlock")):
                _append_step_trace_event(step, "waitedForUnlock")
            if bool(after_wait_info.get("unlockTimedOut")):
                _append_step_trace_event(step, "unlockWaitTimedOut")
        if wait_payload:
            step["wait"] = wait_payload
        step["ms"] = int((time.monotonic() - step_started) * 1000.0)
        results.append(step)

        # --- Collision / "bumped" detection (overworld only) ---
        # If the player tried to move (up/down/left/right) but their position did not change,
        # treat it as a collision (wall/NPC/object/etc.) and warn in the trace logs.
        try:
            if ctype == "control":
                cmd_str = cmd.get("command") if isinstance(cmd, dict) else None
                normalized = _normalize_control_command(cmd_str or "")
                if normalized not in _DIRECTIONAL_CONTROL_COMMANDS:
                    collision_streak = 0
                else:
                    before_fields = _trace_key_fields(before)
                    after_fields = _trace_key_fields(after)
                    same_map = _trace_map_tuple(before) == _trace_map_tuple(after)
                    overworld_before = (
                        not bool(before_fields.get("inDialog"))
                        and not bool(before_fields.get("inBattle"))
                        and not bool(before_fields.get("fieldLocked"))
                    )
                    overworld_after = (
                        not bool(after_fields.get("inDialog"))
                        and not bool(after_fields.get("inBattle"))
                        and not bool(after_fields.get("fieldLocked"))
                    )

                    same_pos = before_fields.get("pos") == after_fields.get("pos")
                    pos = before_fields.get("pos")
                    pos_ok = (
                        isinstance(pos, tuple)
                        and len(pos) >= 2
                        and isinstance(pos[0], int)
                        and isinstance(pos[1], int)
                    )
                    if pos_ok and same_map and overworld_before and overworld_after and same_pos:
                        collision_streak += 1
                        map_name = (before.get("map") or {}).get("name") or "Unknown"
                        warn = (
                            f"WARNING: collision/no movement after '{normalized}' at {pos} on {map_name} "
                            f"(streak {collision_streak}/5)"
                        )
                        _append_step_trace_event(step, warn)
                    else:
                        collision_streak = 0
            else:
                collision_streak = 0
        except Exception:
            # Collision detection must never break command execution.
            pass

        if collision_streak >= 5:
            remaining_keys = normalized_commands[idx + 1 :]
            interrupted_by_collision = True
            interrupted_at_index = idx
            # Add a clear stop warning in logs for the step that triggered the stop.
            try:
                _append_step_trace_event(step, "WARNING: 5 collisions in a row detected. Stopping command sequence early.")
            except Exception:
                pass
            break

        # Fog-of-war discovery must happen *per input*, not only at the end of a long sequence.
        if ctype in {"press", "hold", "control"}:
            try:
                discovered_tiles: List[tuple[int, int]] = []
                walls_to_free: List[tuple[int, int]] = []
                free_to_walls: List[tuple[int, int]] = []
                fog_result = update_fog_of_war_for_current_map(
                    discovered_out=discovered_tiles,
                    walls_to_free_out=walls_to_free,
                    free_to_walls_out=free_to_walls,
                )

                if fog_result is not None:
                    grid, visibility = fog_result
                    vw = visibility.get("widthTiles") if isinstance(visibility, dict) else None
                    vh = visibility.get("heightTiles") if isinstance(visibility, dict) else None
                    hint = visibility.get("hint") if isinstance(visibility, dict) else None
                    _MINIMAP_SNAPSHOT.update(
                        grid=grid,
                        visibility_reduced=bool(visibility.get("reduced")) if isinstance(visibility, dict) else None,
                        visibility_window_width_tiles=int(vw) if vw is not None else None,
                        visibility_window_height_tiles=int(vh) if vh is not None else None,
                        visibility_hint=str(hint) if isinstance(hint, str) and hint else None,
                    )
                    if discovered_tiles or walls_to_free or free_to_walls:
                        try:
                            m = after.get("map") if isinstance(after, dict) else {}
                        except Exception:
                            m = {}
                        g = m.get("group") if isinstance(m, dict) else None
                        n = m.get("number") if isinstance(m, dict) else None
                        map_id = f"{int(g)}-{int(n)}" if isinstance(g, int) and isinstance(n, int) else None
                        map_name = m.get("name") if isinstance(m, dict) and isinstance(m.get("name"), str) else None

                        trace = step.get("trace") if isinstance(step.get("trace"), dict) else {}
                        if discovered_tiles:
                            trace["tilesDiscovered"] = {
                                "mapId": map_id,
                                "mapName": map_name,
                                "positions": [[int(x), int(y)] for (x, y) in discovered_tiles],
                            }
                        if walls_to_free or free_to_walls:
                            trace["groundWallChanged"] = {
                                "mapId": map_id,
                                "mapName": map_name,
                                "wallsToFree": [[int(x), int(y)] for (x, y) in walls_to_free],
                                "freeToWalls": [[int(x), int(y)] for (x, y) in free_to_walls],
                            }
                        step["trace"] = trace

                # Fallback for A-triggered scripts:
                # detect wall/free transitions directly from map RAM, independent of fog discovery.
                if before_passability_snapshot is not None and not (walls_to_free or free_to_walls):
                    after_passability_snapshot = _capture_map_passability_snapshot()
                    direct_walls_to_free, direct_free_to_walls = _diff_passability_transitions(
                        before_passability_snapshot, after_passability_snapshot
                    )
                    if direct_walls_to_free or direct_free_to_walls:
                        trace = step.get("trace") if isinstance(step.get("trace"), dict) else {}
                        trace["groundWallChanged"] = {
                            "mapId": before_passability_snapshot.get("mapId"),
                            "mapName": before_passability_snapshot.get("mapName"),
                            "wallsToFree": [[int(x), int(y)] for (x, y) in direct_walls_to_free],
                            "freeToWalls": [[int(x), int(y)] for (x, y) in direct_free_to_walls],
                        }
                        step["trace"] = trace
            except Exception:
                pass

        # If we started outside dialog/battle, and one starts mid-sequence, stop and return the remaining inputs.
        entered_dialog = (not started_in_dialog) and bool((after.get("dialog") or {}).get("inDialog"))
        entered_battle = (not started_in_battle) and bool((after.get("emulator") or {}).get("inBattle"))
        if entered_dialog or entered_battle:
            requeue_current = False
            if ctype == "control" and _is_directional_control_command(cmd.get("command")):
                same_map = _trace_map_tuple(before) == _trace_map_tuple(after)
                before_pos = _trace_position_tuple(before)
                after_pos = _trace_position_tuple(after)
                if same_map and before_pos is not None and before_pos == after_pos:
                    requeue_current = True

            remaining_keys = normalized_commands[idx if requeue_current else idx + 1 :]
            if entered_dialog:
                interrupted_by_dialog = True
                _append_step_trace_event(step, "interruptedByDialog")
            if entered_battle:
                interrupted_by_battle = True
                _append_step_trace_event(step, "interruptedByBattle")
            if requeue_current:
                _append_step_trace_event(step, "requeuedCurrentMovementCommand")
            interrupted_at_index = idx
            break

    # Node agent expects {status:boolean, log:string}.
    overall_status = bool(results) and all(bool(step.get("ok")) for step in results)
    
    # Wait 3 seconds
    time.sleep(3)
    
    return {
        "ok": True,
        "status": bool(overall_status),
        "log": "",
        "startedInDialog": started_in_dialog,
        "startedInBattle": started_in_battle,
        "interruptedByDialog": interrupted_by_dialog,
        "interruptedByBattle": interrupted_by_battle,
        "interruptedByCollision": interrupted_by_collision,
        "interruptedAtIndex": interrupted_at_index,
        "collisionStreak": collision_streak,
        "remaining_keys": remaining_keys,
        "results": results,
    }

def restart_console() -> Dict[str, Any]:
    """
    Soft reset the emulator.
    """
    try:
        resp = mgba_reset()
        if resp.get("ok"):
            return {"status": True, "message": "Console reset requested."}
        return {"status": False, "message": resp.get("error") or "Reset failed."}
    except Exception as exc:  # pragma: no cover
        return {"status": False, "message": str(exc)}


app: Any = None
if FastAPI is not None:
    app = FastAPI(title="FireRed All-in-One API", version="1.0", lifespan=lifespan)

    # Allow all CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.get("/requestData")(request_data)
    app.get("/minimapSnapshot")(minimap_snapshot)
    app.post("/sendCommands")(send_commands)
    app.post("/restartConsole")(restart_console)


if __name__ == "__main__":
    import uvicorn
    if app is None:  # pragma: no cover
        raise RuntimeError("fastapi is not installed; cannot start server.")
    uvicorn.run(app, host="0.0.0.0", port=8000)
