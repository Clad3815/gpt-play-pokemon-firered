"""Thin wrapper around the mGBA bridge (socket or HTTP)."""

from __future__ import annotations

import json
import re
import socket
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import (
    HTTP_TIMEOUT,
    MGBA_API_URL,
    MGBA_SOCKET_HOST,
    MGBA_SOCKET_PORT,
    MGBA_SOCKET_PORT_MAX,
    MGBA_SOCKET_TIMEOUT,
    MGBA_TRANSPORT,
    READ_RANGE_CHUNK,
)

__all__ = [
    "mgba_read8",
    "mgba_read16",
    "mgba_read32",
    "mgba_read_range",
    "mgba_read_range_bytes",
    "mgba_read_ranges",
    "mgba_read_ranges_bytes",
    "mgba_press_buttons",
    "mgba_hold_button",
    "mgba_screenshot",
    "mgba_save_state_file",
    "mgba_reset",
]

_TERMINATION_MARKER = "<|END|>"
_DEFAULT_RETURN = "<|SUCCESS|>"
_ERROR_RETURN = "<|ERROR|>"


class _MGBASocketClient:
    def __init__(
        self,
        host: str,
        port_min: int,
        port_max: int,
        timeout: float,
    ) -> None:
        self._host = host
        self._port_min = port_min
        self._port_max = max(port_min, port_max)
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buffer = ""
        self._lock = threading.Lock()
        self._connected_port: Optional[int] = None

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._buffer = ""
        self._connected_port = None

    def _connect(self) -> None:
        if self._sock is not None:
            return
        last_error: Optional[Exception] = None
        for port in range(self._port_min, self._port_max + 1):
            try:
                sock = socket.create_connection((self._host, port), timeout=self._timeout)
                sock.settimeout(self._timeout)
                self._sock = sock
                self._connected_port = port
                return
            except OSError as exc:
                last_error = exc
                continue
        raise ConnectionError(
            f"Unable to connect to mGBA socket on {self._host}:{self._port_min}-{self._port_max}: {last_error}"
        )

    def _send(self, message: str) -> None:
        if self._sock is None:
            raise ConnectionError("Socket not connected")
        payload = (message + _TERMINATION_MARKER).encode("utf-8")
        self._sock.sendall(payload)

    def _recv_until_marker(self) -> str:
        if self._sock is None:
            raise ConnectionError("Socket not connected")
        while True:
            marker_idx = self._buffer.find(_TERMINATION_MARKER)
            if marker_idx != -1:
                msg = self._buffer[:marker_idx]
                self._buffer = self._buffer[marker_idx + len(_TERMINATION_MARKER) :]
                return msg
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Socket closed by peer")
            self._buffer += chunk.decode("utf-8", errors="replace")

    def request(self, message: str) -> str:
        with self._lock:
            for attempt in range(2):
                try:
                    self._connect()
                    self._send(message)
                    return self._recv_until_marker()
                except (OSError, ConnectionError):
                    self.close()
                    if attempt == 1:
                        raise
            raise ConnectionError("Socket request failed")


_SOCKET_CLIENT: Optional[_MGBASocketClient] = None


def _use_socket() -> bool:
    return MGBA_TRANSPORT.lower() != "http"


def _socket_client() -> _MGBASocketClient:
    global _SOCKET_CLIENT
    if _SOCKET_CLIENT is None:
        _SOCKET_CLIENT = _MGBASocketClient(
            MGBA_SOCKET_HOST, MGBA_SOCKET_PORT, MGBA_SOCKET_PORT_MAX, MGBA_SOCKET_TIMEOUT
        )
    return _SOCKET_CLIENT


def _fmt_addr(value: int) -> str:
    return f"0x{value:X}"


def _parse_hex_csv(text: str) -> List[int]:
    text = text.strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return [int(p, 16) for p in parts]


def _parse_hex_string(text: str) -> List[int]:
    text = text.strip()
    if not text:
        return []
    return list(bytes.fromhex(text))


def _parse_hex_string_bytes(text: str) -> bytes:
    text = text.strip()
    if not text:
        return b""
    return bytes.fromhex(text)


def _req_get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    return requests.get(url, params=params, timeout=HTTP_TIMEOUT)


def _req_post(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    return requests.post(url, params=params, json=json_body, timeout=HTTP_TIMEOUT)


def _socket_request(message: str) -> str:
    resp = _socket_client().request(message)
    if resp.startswith(_ERROR_RETURN):
        raise RuntimeError(f"mGBA socket error for '{message}': {resp}")
    return resp


def mgba_read8(addr: int) -> int:
    """
    Read a single byte from emulator memory.

    Some mgba-http builds have issues with /read8 for certain address ranges.
    We fall back to /read16 (aligned) and extract the requested byte.
    """
    if _use_socket():
        try:
            resp = _socket_request(f"bridge.read8,{_fmt_addr(addr)}")
            if resp == _DEFAULT_RETURN:
                raise RuntimeError("mGBA socket read8 returned no data")
            return int(resp.strip())
        except ConnectionError:
            pass
    try:
        r = _req_get(f"{MGBA_API_URL}/read8", params={"address": f"0x{addr:X}"})
        r.raise_for_status()
        return int(r.text)
    except requests.RequestException:
        aligned = addr & ~1
        word = mgba_read16(aligned)
        if addr & 1:
            return (word >> 8) & 0xFF
        return word & 0xFF


def mgba_read16(addr: int) -> int:
    if _use_socket():
        try:
            resp = _socket_request(f"bridge.read16,{_fmt_addr(addr)}")
            if resp == _DEFAULT_RETURN:
                raise RuntimeError("mGBA socket read16 returned no data")
            return int(resp.strip())
        except ConnectionError:
            pass
    r = _req_get(f"{MGBA_API_URL}/read16", params={"address": f"0x{addr:X}"})
    r.raise_for_status()
    return int(r.text)


def mgba_read32(addr: int) -> int:
    if _use_socket():
        try:
            resp = _socket_request(f"bridge.read32,{_fmt_addr(addr)}")
            if resp == _DEFAULT_RETURN:
                raise RuntimeError("mGBA socket read32 returned no data")
            return int(resp.strip())
        except ConnectionError:
            pass
    r = _req_get(f"{MGBA_API_URL}/read32", params={"address": f"0x{addr:X}"})
    r.raise_for_status()
    return int(r.text)


def mgba_read_range(addr: int, length: int) -> List[int]:
    if length <= 0:
        return []
    if _use_socket():
        try:
            if length <= READ_RANGE_CHUNK:
                resp = _socket_request(f"bridge.readRangeHex,{_fmt_addr(addr)},{length}")
                if resp == _DEFAULT_RETURN or resp == _ERROR_RETURN:
                    resp = _socket_request(f"bridge.readRange,{_fmt_addr(addr)},{length}")
                    if resp == _DEFAULT_RETURN:
                        return []
                    return _parse_hex_csv(resp)
                try:
                    return _parse_hex_string(resp)
                except ValueError:
                    return _parse_hex_csv(resp)
            ranges: List[Tuple[int, int]] = []
            read = 0
            while read < length:
                chunk_len = min(READ_RANGE_CHUNK, length - read)
                ranges.append((addr + read, chunk_len))
                read += chunk_len
            return _read_ranges_socket(ranges)
        except ConnectionError:
            pass

    all_bytes: List[int] = []
    read = 0
    while read < length:
        chunk_len = min(READ_RANGE_CHUNK, length - read)
        r = _req_get(
            f"{MGBA_API_URL}/readRange",
            params={"address": f"0x{(addr + read):X}", "length": chunk_len},
        )
        r.raise_for_status()
        text = r.text.strip()
        chunk: Optional[List[int]] = None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                chunk = parsed
        except (json.JSONDecodeError, ValueError):
            chunk = None

        if chunk is None and text.startswith("[") and text.endswith("]"):
            try:
                start_idx = text.find("[")
                bracket_count = 0
                end_idx = start_idx
                for i in range(start_idx, len(text)):
                    if text[i] == "[":
                        bracket_count += 1
                    elif text[i] == "]":
                        bracket_count -= 1
                        if bracket_count == 0:
                            end_idx = i + 1
                            break
                parsed = json.loads(text[start_idx:end_idx])
                if isinstance(parsed, list):
                    chunk = parsed
            except (json.JSONDecodeError, ValueError):
                chunk = None

        if chunk is None:
            try:
                parts = [p.strip() for p in text.split(",") if p.strip()]
                chunk = []
                # mGBA HTTP scripts commonly return bytes as comma-separated hex pairs without 0x,
                # e.g. "6d,00,7e,45". In that format, digits-only values like "45" are still hex.
                # Detect this and parse consistently as hex; otherwise fall back to mixed CSV parsing.
                if parts and all(re.fullmatch(r"[0-9a-fA-F]{2}", p) for p in parts):
                    chunk = [int(p, 16) for p in parts]
                else:
                    for part in parts:
                        if part.startswith(("0x", "0X")):
                            chunk.append(int(part, 16))
                        elif any(c in part.lower() for c in "abcdef"):
                            chunk.append(int(part, 16))
                        else:
                            chunk.append(int(part, 10))
            except ValueError as exc:
                preview = text[:200]
                raise RuntimeError(
                    f"readRange: failed to parse response as CSV or JSON: {exc}, response preview: {preview}"
                ) from exc

        if not isinstance(chunk, list):
            raise RuntimeError(
                f"readRange: failed to parse response, got {type(chunk)}, response preview: {text[:200]}"
            )

        all_bytes.extend(chunk)
        read += len(chunk)
    return all_bytes


def _read_ranges_socket(ranges: List[Tuple[int, int]]) -> List[int]:
    if not ranges:
        return []
    flat = []
    for addr, length in ranges:
        flat.append(_fmt_addr(addr))
        flat.append(str(length))
    payload = "[" + ",".join(flat) + "]"
    resp = _socket_request(f"bridge.readRangesHex,{payload}")
    if resp == _DEFAULT_RETURN or resp == _ERROR_RETURN:
        resp = _socket_request(f"bridge.readRanges,{payload}")
    if resp == _DEFAULT_RETURN:
        return []
    segments = resp.split("|")
    out: List[int] = []
    for segment in segments:
        if segment.strip() == "":
            continue
        try:
            out.extend(_parse_hex_string(segment))
        except ValueError:
            out.extend(_parse_hex_csv(segment))
    return out


def _read_ranges_socket_bytes(ranges: List[Tuple[int, int]]) -> bytes:
    if not ranges:
        return b""
    flat = []
    for addr, length in ranges:
        flat.append(_fmt_addr(addr))
        flat.append(str(length))
    payload = "[" + ",".join(flat) + "]"
    resp = _socket_request(f"bridge.readRangesHex,{payload}")
    if resp == _DEFAULT_RETURN or resp == _ERROR_RETURN:
        resp = _socket_request(f"bridge.readRanges,{payload}")
    if resp == _DEFAULT_RETURN:
        return b""
    segments = resp.split("|")
    out = bytearray()
    for segment in segments:
        if segment.strip() == "":
            continue
        try:
            out.extend(_parse_hex_string_bytes(segment))
        except ValueError:
            out.extend(bytes(_parse_hex_csv(segment)))
    return bytes(out)


def mgba_read_ranges(ranges: List[Tuple[int, int]]) -> List[List[int]]:
    if not ranges:
        return []
    if _use_socket():
        try:
            flat = []
            for addr, length in ranges:
                flat.append(_fmt_addr(addr))
                flat.append(str(length))
            payload = "[" + ",".join(flat) + "]"
            resp = _socket_request(f"bridge.readRangesHex,{payload}")
            if resp == _DEFAULT_RETURN or resp == _ERROR_RETURN:
                resp = _socket_request(f"bridge.readRanges,{payload}")
            if resp == _DEFAULT_RETURN:
                return [[] for _ in ranges]
            segments = resp.split("|")
            results: List[List[int]] = []
            for segment in segments:
                if segment.strip() == "":
                    results.append([])
                else:
                    try:
                        results.append(_parse_hex_string(segment))
                    except ValueError:
                        results.append(_parse_hex_csv(segment))
            return results
        except ConnectionError:
            pass

    results = []
    for addr, length in ranges:
        results.append(mgba_read_range(addr, length))
    return results


def mgba_read_ranges_bytes(ranges: List[Tuple[int, int]]) -> List[bytes]:
    if not ranges:
        return []
    if _use_socket():
        try:
            flat = []
            for addr, length in ranges:
                flat.append(_fmt_addr(addr))
                flat.append(str(length))
            payload = "[" + ",".join(flat) + "]"
            resp = _socket_request(f"bridge.readRangesHex,{payload}")
            if resp == _DEFAULT_RETURN or resp == _ERROR_RETURN:
                resp = _socket_request(f"bridge.readRanges,{payload}")
            if resp == _DEFAULT_RETURN:
                return [b"" for _ in ranges]
            segments = resp.split("|")
            results: List[bytes] = []
            for segment in segments:
                if segment.strip() == "":
                    results.append(b"")
                else:
                    try:
                        results.append(_parse_hex_string_bytes(segment))
                    except ValueError:
                        results.append(bytes(_parse_hex_csv(segment)))
            return results
        except ConnectionError:
            pass

    return [mgba_read_range_bytes(addr, length) for addr, length in ranges]


def mgba_read_range_bytes(addr: int, length: int) -> bytes:
    if length <= 0:
        return b""
    if _use_socket():
        try:
            if length <= READ_RANGE_CHUNK:
                resp = _socket_request(f"bridge.readRangeHex,{_fmt_addr(addr)},{length}")
                if resp == _DEFAULT_RETURN or resp == _ERROR_RETURN:
                    resp = _socket_request(f"bridge.readRange,{_fmt_addr(addr)},{length}")
                    if resp == _DEFAULT_RETURN:
                        return b""
                    return bytes(_parse_hex_csv(resp))
                try:
                    return _parse_hex_string_bytes(resp)
                except ValueError:
                    return bytes(_parse_hex_csv(resp))
            ranges: List[Tuple[int, int]] = []
            read = 0
            while read < length:
                chunk_len = min(READ_RANGE_CHUNK, length - read)
                ranges.append((addr + read, chunk_len))
                read += chunk_len
            return _read_ranges_socket_bytes(ranges)
        except ConnectionError:
            pass

    return bytes(mgba_read_range(addr, length))


def mgba_press_buttons(buttons: List[str]) -> Dict[str, Any]:
    if _use_socket():
        try:
            payload = ";".join(buttons)
            resp = _socket_request(f"bridge.pressButtons,{payload}")
            if resp != _ERROR_RETURN:
                return {"ok": True, "endpoint": "socket"}
        except Exception:
            pass

    tried = []
    try:
        url = f"{MGBA_API_URL}/pressButtons"
        r = _req_post(url, json_body={"buttons": buttons})
        if r.ok:
            return {"ok": True, "endpoint": url}
        tried.append((url, r.status_code, r.text))
    except Exception as exc:  # pragma: no cover - defensive logging
        tried.append(("pressButtons", "EXC", str(exc)))

    try:
        url = f"{MGBA_API_URL}/press"
        r = _req_post(url, params={"buttons": ",".join(buttons)})
        if r.ok:
            return {"ok": True, "endpoint": url}
        tried.append((url, r.status_code, r.text))
    except Exception as exc:  # pragma: no cover - defensive logging
        tried.append(("press", "EXC", str(exc)))
    return {"ok": False, "tried": tried}


def mgba_hold_button(button: str, frames: int) -> Dict[str, Any]:
    if _use_socket():
        try:
            resp = _socket_request(f"bridge.holdButton,{button},{frames}")
            if resp != _ERROR_RETURN:
                return {"ok": True, "endpoint": "socket"}
        except Exception:
            pass

    tried = []
    try:
        url = f"{MGBA_API_URL}/holdButton"
        r = _req_post(url, params={"button": button, "frames": frames})
        if r.ok:
            return {"ok": True, "endpoint": url}
        tried.append((url, r.status_code, r.text))
    except Exception as exc:
        tried.append(("holdButton", "EXC", str(exc)))

    try:
        url = f"{MGBA_API_URL}/hold"
        r = _req_post(url, params={"name": button, "frames": frames})
        if r.ok:
            return {"ok": True, "endpoint": url}
        tried.append((url, r.status_code, r.text))
    except Exception as exc:
        tried.append(("hold", "EXC", str(exc)))
    return {"ok": False, "tried": tried}


def mgba_screenshot(filepath: str) -> Dict[str, Any]:
    """
    Ask the mGBA Lua socket bridge to write a PNG screenshot to `filepath`.

    NOTE: This requires the socket transport and a Lua bridge that implements
    `bridge.screenshot,<filepath>` using `emu:screenshot(filepath)`.
    """
    if not isinstance(filepath, str) or not filepath.strip():
        return {"ok": False, "error": "Invalid filepath"}

    if not _use_socket():
        return {"ok": False, "error": "Screenshot is only supported with MGBA_TRANSPORT=socket"}

    try:
        _socket_request(f"bridge.screenshot,{filepath}")
        return {"ok": True, "endpoint": "socket"}
    except Exception as exc:  # pragma: no cover - depends on mGBA runtime
        return {"ok": False, "error": str(exc)}


def mgba_save_state_file(filepath: str) -> Dict[str, Any]:
    """
    Ask the mGBA Lua socket bridge to write a savestate file to `filepath`.

    NOTE: This requires the socket transport and a Lua bridge that implements
    `bridge.saveStateFile,<filepath>` using `emu:saveStateFile(filepath)`.
    """
    if not isinstance(filepath, str) or not filepath.strip():
        return {"ok": False, "error": "Invalid filepath"}

    if not _use_socket():
        return {"ok": False, "error": "Savestate backup is only supported with MGBA_TRANSPORT=socket"}

    try:
        resp = _socket_request(f"bridge.saveStateFile,{filepath}")
        if resp.strip().lower() == "false":
            return {"ok": False, "endpoint": "socket", "error": "saveStateFile returned false"}
        return {"ok": True, "endpoint": "socket", "result": resp.strip()}
    except Exception as exc:  # pragma: no cover - depends on mGBA runtime
        return {"ok": False, "error": str(exc)}


def mgba_reset() -> Dict[str, Any]:
    """
    Soft reset the emulator core.

    Requires the socket transport and a Lua bridge that implements `bridge.reset`
    using `emu:reset()`.
    """
    if not _use_socket():
        return {"ok": False, "error": "Reset is only supported with MGBA_TRANSPORT=socket"}

    try:
        _socket_request("bridge.reset")
        return {"ok": True, "endpoint": "socket"}
    except Exception as exc:  # pragma: no cover - depends on mGBA runtime
        return {"ok": False, "error": str(exc)}
