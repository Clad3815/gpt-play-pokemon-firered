from __future__ import annotations

"""
Compatibility facade.

Historically, this project implemented all RAM parsing and state-building logic in this module.
It has since been split into focused modules (memory/constants/text/ui/world/player/state) to
reduce duplication and improve maintainability.
"""

from . import mgba_client as _mgba_client
from .config import MGBA_API_URL

# Symbol lookup (pokefirered.sym)
from .memory.symbols import sym_addr, sym_addrs, sym_addrs_by_prefix, sym_entry

# mGBA read wrappers + optional metrics
from .memory.mgba import MgbaReadMetrics, mgba_read8, mgba_read16, mgba_read32, mgba_read_range, mgba_read_ranges
from .memory.mgba import mgba_read_range_bytes, mgba_read_ranges_bytes

# High-level control (Lua socket endpoint)
from .memory.control import ensure_overworld_control_initialized, mgba_control, mgba_control_status

# Static constants
from .constants.addresses import *  # noqa: F403
from .constants.behaviors import *  # noqa: F403
from .constants.tiles import *  # noqa: F403

# Text decoding / TextPrinter helpers
from .text.encoding import *  # noqa: F403
from .text.text_printer import *  # noqa: F403

# Player data helpers
from .player.bag import *  # noqa: F403
from .player.party import *  # noqa: F403
from .player.pc import *  # noqa: F403
from .player.save import *  # noqa: F403
from .player.snapshot import *  # noqa: F403

# World/map helpers
from .world.collision import *  # noqa: F403
from .world.events import *  # noqa: F403
from .world.map_read import *  # noqa: F403
from .world.viewport import *  # noqa: F403

# UI detection
from .ui.battle import *  # noqa: F403
from .ui.dialog import _DIALOG_SNAPSHOT_RANGES, _DIALOG_SNAPSHOT_RANGES_EXT, get_dialog_state
from .ui.menus import *  # noqa: F403

# Top-level state builders
from .state.builders import build_full_state, build_input_trace_state, update_fog_of_war_for_current_map

