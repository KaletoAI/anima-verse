"""One hub-job flow per template piece at a time (user finding 2026-11-20, Dario).

While the "texture from cut" job of a piece ran, the dialog still offered the piece-only views' Generate buttons; the
user started both views 12 s after the cut and spent two needless image jobs — and the new views changed the drape
key, so the shirt dropped off the figure until the next Build. Every flow that spends hub jobs for ONE template piece
(``garment_cut_texture.start``, ``garment_template_views.start``) therefore claims the piece here first; a second
claim while one holds is refused with the holder's plain reason, and the routes answer it with 409. The server is
the guard: a second browser tab or a race between two clicks cannot spend jobs either; the dialog only mirrors it
(``holder`` / ``reason`` disable its buttons with the same words).

Keys are ``(character, item)``; ``what`` names the flow ("cut", "view:front", "view:back"). In-process only — a
server restart drops the claims together with the threads that held them.
"""
from __future__ import annotations

import threading
from typing import Dict, Tuple

#: The plain reason of a held claim (English; the React dialog puts it through ``t()``).
REASONS = {
    "cut": "The texture from cut is being made for this piece — wait until it is done",
    "view:front": "The front piece-only view is being made for this piece — wait until it is done",
    "view:back": "The back piece-only view is being made for this piece — wait until it is done",
}

_lock = threading.Lock()
_held: Dict[Tuple[str, str], str] = {}


def claim(character_name: str, item_id: str, what: str) -> str:
    """Claim the piece for ``what``: "" when claimed, else the plain reason of the flow that holds it."""
    key = (character_name, item_id)
    with _lock:
        holder = _held.get(key)
        if holder is not None:
            return REASONS.get(holder, holder)
        _held[key] = what
        return ""


def release(character_name: str, item_id: str, what: str) -> None:
    """Release the claim of ``what`` (a claim held by another flow stays)."""
    key = (character_name, item_id)
    with _lock:
        if _held.get(key) == what:
            _held.pop(key, None)


def holder(character_name: str, item_id: str) -> str:
    """The flow that holds the piece ("" when none)."""
    with _lock:
        return _held.get((character_name, item_id), "")


def reason(character_name: str, item_id: str) -> str:
    """The plain reason a job button of the piece is disabled for ("" when the piece is free)."""
    held = holder(character_name, item_id)
    return REASONS.get(held, held) if held else ""
