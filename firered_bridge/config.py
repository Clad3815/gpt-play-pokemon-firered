"""Central configuration for the FireRed mGBA bridge."""

from __future__ import annotations

import os
from pathlib import Path

MGBA_API_URL = os.environ.get("MGBA_API_URL", "http://localhost:5000/core")
HTTP_TIMEOUT = float(os.environ.get("MGBA_HTTP_TIMEOUT", 15.0))
READ_RANGE_CHUNK = int(os.environ.get("MGBA_READ_RANGE_CHUNK", 1024))
GAME_DATA_DIR = Path(os.environ.get("FIRERED_GAME_DATA_DIR", "game_data_firered"))
MINIMAPS_DIR = Path(os.environ.get("FIRERED_MINIMAPS_DIR", "minimaps"))

MGBA_TRANSPORT = os.environ.get("MGBA_TRANSPORT", "socket")
MGBA_SOCKET_HOST = os.environ.get("MGBA_SOCKET_HOST", "127.0.0.1")
MGBA_SOCKET_PORT = int(os.environ.get("MGBA_SOCKET_PORT", 8888))
MGBA_SOCKET_PORT_MAX = int(os.environ.get("MGBA_SOCKET_PORT_MAX", MGBA_SOCKET_PORT + 8))
MGBA_SOCKET_TIMEOUT = float(os.environ.get("MGBA_SOCKET_TIMEOUT", 2.0))
