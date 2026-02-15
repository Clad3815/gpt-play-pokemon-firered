from __future__ import annotations

from .. import mgba_client as _mgba_client
from ..constants.addresses import (
    CB2_OVERWORLD_ADDR,
    GMAIN_ADDR,
    OBJECT_EVENTS_ADDR,
    PLAYER_AVATAR_ADDR,
    SCRIPT_LOCK_FIELD_CONTROLS,
)

_OVERWORLD_CONTROL_INIT_DONE = False


def _fmt_addr_hex(addr: int) -> str:
    return f"0x{addr:X}"


def ensure_overworld_control_initialized() -> None:
    """
    Initialize the Lua-side overworld control system with symbol addresses.

    This is required for the `bridge.control` endpoint added in
    `mgba/scripts/FireRedBridgeSocketServer.lua`.
    """
    global _OVERWORLD_CONTROL_INIT_DONE
    if _OVERWORLD_CONTROL_INIT_DONE:
        return

    addrs = [
        PLAYER_AVATAR_ADDR,
        OBJECT_EVENTS_ADDR,
        GMAIN_ADDR,
        CB2_OVERWORLD_ADDR,
        SCRIPT_LOCK_FIELD_CONTROLS,
    ]
    payload = "[" + ",".join(_fmt_addr_hex(a) for a in addrs) + "]"

    resp = _mgba_client._socket_request(f"bridge.controlInit,{payload}").strip()
    if resp != "controlInit.ok":
        raise RuntimeError(f"Unexpected response to bridge.controlInit: {resp!r}")

    _OVERWORLD_CONTROL_INIT_DONE = True


def mgba_control(command: str) -> str:
    """
    Send a high-level control command to the mGBA Lua socket server.

    Supported commands (case-insensitive):
      a, b, start, select, l, r,
      up, down, left, right,
      face_up, face_down, face_left, face_right

    The Lua implementation applies "smart" 1-tile movement only when the game is in overworld
    and field controls are unlocked; otherwise d-pad inputs degrade to a short tap (useful in menus).
    """
    ensure_overworld_control_initialized()
    resp = _mgba_client._socket_request(f"bridge.control,{command}").strip()
    if resp != "control.ok":
        raise RuntimeError(f"Unexpected response to bridge.control: {resp!r}")
    return resp


def mgba_control_status() -> str:
    """
    Return a debug/status string from the Lua socket server for overworld control gating.
    """
    ensure_overworld_control_initialized()
    return _mgba_client._socket_request("bridge.controlStatus").strip()
