from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..constants.addresses import (
    GBATTLETEXTBUFF1_ADDR,
    GBATTLETEXTBUFF2_ADDR,
    GBATTLETEXTBUFF3_ADDR,
    GBATTLETEXTBUFF_SIZE,
    GDISPLAYEDSTRINGBATTLE_ADDR,
    GDISPLAYEDSTRINGBATTLE_SIZE,
    GSTRINGVAR1_ADDR,
    GSTRINGVAR1_SIZE,
    GSTRINGVAR2_ADDR,
    GSTRINGVAR2_SIZE,
    GSTRINGVAR3_ADDR,
    GSTRINGVAR3_SIZE,
    GSTRINGVAR4_ADDR,
    GSTRINGVAR4_SIZE,
    STEXTPRINTERS_ADDR,
    TEXTPRINTER_ACTIVE_OFFSET,
    TEXTPRINTER_CURRENTCHAR_OFFSET,
    TEXTPRINTER_SIZE,
)
from ..memory import mgba
from ..util.bytes import _u8_from, _u32le_from
from .encoding import PROMPT_CHARS, TEXT_TERMINATOR, decode_gba_string, read_string_buffer

TEXT_POINTER_REGIONS: List[Tuple[int, int]] = [
    (0x02000000, 0x0203FFFF),  # EWRAM
    (0x03000000, 0x03007FFF),  # IWRAM
    (0x08000000, 0x09FFFFFF),  # ROM
]

TEXT_BUFFERS: List[Tuple[int, int]] = [
    (GSTRINGVAR4_ADDR, GSTRINGVAR4_SIZE),
    (GSTRINGVAR1_ADDR, GSTRINGVAR1_SIZE),
    (GSTRINGVAR2_ADDR, GSTRINGVAR2_SIZE),
    (GSTRINGVAR3_ADDR, GSTRINGVAR3_SIZE),
    (GDISPLAYEDSTRINGBATTLE_ADDR, GDISPLAYEDSTRINGBATTLE_SIZE),
    (GBATTLETEXTBUFF1_ADDR, GBATTLETEXTBUFF_SIZE),
    (GBATTLETEXTBUFF2_ADDR, GBATTLETEXTBUFF_SIZE),
    (GBATTLETEXTBUFF3_ADDR, GBATTLETEXTBUFF_SIZE),
]

def _get_text_buffer_for_ptr(ptr: int) -> Optional[Tuple[int, int]]:
    for base, size in TEXT_BUFFERS:
        if base <= ptr < base + size:
            return base, size
    return None


def _get_region_bounds(ptr: int) -> Optional[Tuple[int, int]]:
    for start, end in TEXT_POINTER_REGIONS:
        if start <= ptr <= end:
            return (start, end)
    return None


def _extract_visible_text_from_raw(raw: Sequence[int], offset: int, max_len: int = 200) -> str:
    if not raw:
        return ""

    if offset < 0:
        offset = 0
    if offset > len(raw):
        offset = len(raw)

    search_end = offset
    if offset > 0 and raw[offset - 1] in PROMPT_CHARS:
        search_end = offset - 1
    elif offset > 0 and raw[offset - 1] == TEXT_TERMINATOR:
        # Some callers may pass a pointer that has advanced one byte past the terminator.
        search_end = offset - 1
    elif offset < len(raw) and (raw[offset] == TEXT_TERMINATOR or raw[offset] in PROMPT_CHARS):
        search_end = offset

    page_start = 0
    for j in range(search_end - 1, -1, -1):
        if raw[j] == TEXT_TERMINATOR or raw[j] in PROMPT_CHARS:
            page_start = j + 1
            break

    # When decoding from a memory window (ROM/EWRAM/IWRAM), the slice may contain earlier terminators
    # unrelated to the current string. Clamp to the first "page end" marker after page_start.
    page_end = None
    for idx in range(page_start, len(raw)):
        if raw[idx] == TEXT_TERMINATOR or raw[idx] in PROMPT_CHARS:
            page_end = idx
            break
    if page_end is not None and search_end > page_end:
        search_end = page_end

    if search_end < page_start:
        return ""

    page_bytes = raw[page_start:search_end]
    return decode_gba_string(page_bytes, max_len, stop_at_prompt=True)


def _extract_visible_text_from_ptr(current_ptr: int) -> str:
    buf = _get_text_buffer_for_ptr(current_ptr)
    if buf:
        base, size = buf
        raw = mgba.mgba_read_range_bytes(base, size)
        return _extract_visible_text_from_raw(raw, current_ptr - base)

    region = _get_region_bounds(current_ptr)
    if not region:
        return ""

    start, end = region
    window = 512
    base = max(start, current_ptr - window)
    size = min(window * 2, end - base + 1)
    raw = mgba.mgba_read_range_bytes(base, size)
    return _extract_visible_text_from_raw(raw, current_ptr - base)


def find_active_textprinter_text(
    *,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
    include_inactive_window0: bool = False,
) -> Optional[str]:
    """
    Scan all 32 TextPrinters to find the currently visible dialog/battle text.

    For robustness we prioritize:
    - Window 0 (dialog box) over other windows
    - Pointers into known text buffers (battle + gStringVar*) over generic regions
    - Otherwise fall back to decoding from the pointer region (EWRAM/IWRAM/ROM)

    Notes:
    - Many messages/menu prompts are printed instantly (text speed 0 or TEXT_SKIP_DRAW),
      leaving no "active" text printer. In that case, the last window-0 printer template
      can still be a useful hint while a dialog is on screen, so callers can opt into
      considering the window-0 printer even when it's inactive.
    """
    try:
        def _score(window_id: int, current_ptr: int) -> int:
            score = 0
            if int(window_id) == 0:
                score += 100

            buf = _get_text_buffer_for_ptr(int(current_ptr))
            if buf is not None:
                base, _size = buf
                if base == GDISPLAYEDSTRINGBATTLE_ADDR:
                    score += 90
                elif base == GSTRINGVAR4_ADDR:
                    score += 80
                elif base in (GSTRINGVAR1_ADDR, GSTRINGVAR2_ADDR, GSTRINGVAR3_ADDR):
                    score += 70
                elif base in (GBATTLETEXTBUFF1_ADDR, GBATTLETEXTBUFF2_ADDR, GBATTLETEXTBUFF3_ADDR):
                    score += 60
                else:
                    score += 50
                return score

            region = _get_region_bounds(int(current_ptr))
            if region is None:
                return score
            start, _end = region
            # ROM strings are common in menus (e.g. PC prompts); rank them below known buffers.
            if start == 0x08000000:
                score += 20
            else:
                score += 40
            return score

        def _decode_best(candidates: List[Tuple[int, int, int]]) -> Optional[str]:
            if not candidates:
                return None
            candidates.sort(key=lambda item: item[0], reverse=True)
            for _score_val, _win, ptr in candidates:
                # Prefer decoding from known buffers when available (avoids extra reads).
                if (
                    GDISPLAYEDSTRINGBATTLE_ADDR <= ptr < (GDISPLAYEDSTRINGBATTLE_ADDR + GDISPLAYEDSTRINGBATTLE_SIZE)
                    and gdisplayedstringbattle_raw is not None
                ):
                    offset = ptr - GDISPLAYEDSTRINGBATTLE_ADDR
                    if offset < len(gdisplayedstringbattle_raw):
                        text = _extract_visible_text_from_raw(gdisplayedstringbattle_raw, offset, 200)
                        if text and len(text) > 2:
                            return text

                if GSTRINGVAR4_ADDR <= ptr < (GSTRINGVAR4_ADDR + GSTRINGVAR4_SIZE) and gstringvar4_raw is not None:
                    offset = ptr - GSTRINGVAR4_ADDR
                    if offset < len(gstringvar4_raw):
                        text = _extract_visible_text_from_raw(gstringvar4_raw, offset, 200)
                        if text and len(text) > 2:
                            return text

                text = _extract_visible_text_from_ptr(ptr)
                if text and len(text) > 2:
                    return text
            return None

        if text_printers_raw is None:
            # Slow path: read each printer header directly.
            candidates: List[Tuple[int, int, int]] = []
            for i in range(32):
                printer_addr = STEXTPRINTERS_ADDR + (i * TEXTPRINTER_SIZE)
                active = mgba.mgba_read8(printer_addr + TEXTPRINTER_ACTIVE_OFFSET)
                if active == 0:
                    continue
                current_ptr = mgba.mgba_read32(printer_addr + TEXTPRINTER_CURRENTCHAR_OFFSET)
                if current_ptr == 0:
                    continue
                candidates.append((_score(i, current_ptr), i, int(current_ptr)))

            if gstringvar4_raw is None:
                gstringvar4_raw = mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
            if gdisplayedstringbattle_raw is None:
                gdisplayedstringbattle_raw = mgba.mgba_read_range_bytes(
                    GDISPLAYEDSTRINGBATTLE_ADDR, GDISPLAYEDSTRINGBATTLE_SIZE
                )

            text = _decode_best(candidates)
            if text:
                return text

            if include_inactive_window0:
                try:
                    ptr0 = int(mgba.mgba_read32(STEXTPRINTERS_ADDR + TEXTPRINTER_CURRENTCHAR_OFFSET))
                except Exception:
                    ptr0 = 0
                if ptr0:
                    return _decode_best([(_score(0, ptr0), 0, ptr0)])

            return None

        # Snapshot path: use the captured printers + buffers.
        if gstringvar4_raw is None:
            gstringvar4_raw = mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
        if gdisplayedstringbattle_raw is None:
            gdisplayedstringbattle_raw = mgba.mgba_read_range_bytes(
                GDISPLAYEDSTRINGBATTLE_ADDR, GDISPLAYEDSTRINGBATTLE_SIZE
            )

        candidates: List[Tuple[int, int, int]] = []
        for i in range(32):
            off = (i * TEXTPRINTER_SIZE) + TEXTPRINTER_CURRENTCHAR_OFFSET
            active_off = (i * TEXTPRINTER_SIZE) + TEXTPRINTER_ACTIVE_OFFSET
            if _u8_from(text_printers_raw, active_off) == 0:
                continue
            current_ptr = _u32le_from(text_printers_raw, off)
            if current_ptr == 0:
                continue
            candidates.append((_score(i, current_ptr), i, int(current_ptr)))

        text = _decode_best(candidates)
        if text:
            return text

        if include_inactive_window0:
            ptr0 = _u32le_from(text_printers_raw, TEXTPRINTER_CURRENTCHAR_OFFSET)
            if ptr0:
                return _decode_best([(_score(0, ptr0), 0, int(ptr0))])

        return None
    except Exception:
        return None


def get_textprinter_text_for_window(
    window_id: int,
    *,
    text_printers_raw: Optional[bytes] = None,
    gstringvar4_raw: Optional[Sequence[int]] = None,
    gdisplayedstringbattle_raw: Optional[Sequence[int]] = None,
    include_inactive: bool = False,
) -> Optional[str]:
    """
    Decode the currently visible text for a specific TextPrinter (by window id).

    Motivation:
    - Some UIs (notably the Bag item message box) print dialog text into a window that is not window 0.
    - Those messages can be rendered instantly (printer inactive) while still being visible on screen.
    """
    try:
        wid = int(window_id)
        if wid < 0 or wid >= 32:
            return None

        if text_printers_raw is None:
            printer_addr = STEXTPRINTERS_ADDR + (wid * TEXTPRINTER_SIZE)
            active = int(mgba.mgba_read8(printer_addr + TEXTPRINTER_ACTIVE_OFFSET))
            if active == 0 and not include_inactive:
                return None
            current_ptr = int(mgba.mgba_read32(printer_addr + TEXTPRINTER_CURRENTCHAR_OFFSET))
        else:
            base = wid * TEXTPRINTER_SIZE
            active = int(_u8_from(text_printers_raw, base + TEXTPRINTER_ACTIVE_OFFSET))
            if active == 0 and not include_inactive:
                return None
            current_ptr = int(_u32le_from(text_printers_raw, base + TEXTPRINTER_CURRENTCHAR_OFFSET))

        if current_ptr == 0:
            return None

        # Prefer decoding from known buffers when available (avoids extra reads).
        if (
            GDISPLAYEDSTRINGBATTLE_ADDR <= current_ptr < (GDISPLAYEDSTRINGBATTLE_ADDR + GDISPLAYEDSTRINGBATTLE_SIZE)
            and gdisplayedstringbattle_raw is not None
        ):
            offset = current_ptr - GDISPLAYEDSTRINGBATTLE_ADDR
            if offset < len(gdisplayedstringbattle_raw):
                text = _extract_visible_text_from_raw(gdisplayedstringbattle_raw, offset, 200)
                if text:
                    return text

        if GSTRINGVAR4_ADDR <= current_ptr < (GSTRINGVAR4_ADDR + GSTRINGVAR4_SIZE):
            if gstringvar4_raw is None:
                gstringvar4_raw = mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
            offset = current_ptr - GSTRINGVAR4_ADDR
            if offset < len(gstringvar4_raw):
                text = _extract_visible_text_from_raw(gstringvar4_raw, offset, 200)
                if text:
                    return text

        return _extract_visible_text_from_ptr(current_ptr)
    except Exception:
        return None


def get_current_dialog_text() -> Optional[str]:
    """
    Read the currently visible dialog text.
    """
    try:
        text = find_active_textprinter_text()
        if text:
            return text

        text = read_string_buffer(GSTRINGVAR4_ADDR, 500, visible_only=True)
        if text and len(text) > 2:
            return text
        return None
    except Exception:
        return None


def get_full_dialog_text(raw: Optional[Sequence[int]] = None) -> Optional[Dict[str, Any]]:
    """
    Read the full dialog text from gStringVar4, split into pages.
    Returns all pages of the dialog for complete context.
    """
    try:
        if raw is None:
            raw = mgba.mgba_read_range_bytes(GSTRINGVAR4_ADDR, 500)
        if not raw:
            return None

        pages = []
        current_page = []
        i = 0

        while i < len(raw):
            byte = raw[i]
            if byte == TEXT_TERMINATOR:
                break

            if byte in PROMPT_CHARS:
                if current_page:
                    page_text = decode_gba_string(current_page, 200)
                    if page_text:
                        pages.append(page_text)
                    current_page = []
                i += 1
                continue

            current_page.append(byte)
            i += 1

        if current_page:
            page_text = decode_gba_string(current_page, 200)
            if page_text:
                pages.append(page_text)

        if pages:
            return {"pages": pages, "pageCount": len(pages), "fullText": "\n".join(pages)}

        return None
    except Exception:
        return None
