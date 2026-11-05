"""Persona definitions — the package table ``transformation_definitions``.

Each row binds a persona to a power item; rows are written by the
Transformation panel (Game-Admin → Characters → <character> → Skills,
``panel.py``) through ``store``. The ``alias`` is a plain label: the knower
secret and the narration name the persona by it, nothing masks a name with it.
``load()`` turns the rows into frozen :class:`Definition` objects keyed by
``id`` and skips, with one warning per record per process, every row that
lacks ``item_id``/``alias``; a disabled row is skipped silently. The panel
refuses the defects on save; the skip rule stays for rows written by hand.

The defaults below are the ONE source: the table's column defaults are built
from them (``store.ensure_schema``).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

from app.core.log import get_logger

from plugins.transformation import store

logger = get_logger("transformation")

DEFAULT_MAX_DURATION_MINUTES = 60
DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_TRANSFORM_ACTIVITY = "transforming"


@dataclass(frozen=True)
class Definition:
    id: str
    enabled: bool
    item_id: str
    alias: str
    activation_phrase: str
    revert_phrase: str
    condition_id: str
    max_duration_minutes: int
    cooldown_minutes: int
    transform_activity: str


_warned: Set[Tuple[str, str]] = set()
_lock = threading.Lock()
_cache: Tuple[Any, Optional[Dict[str, Definition]]] = (None, None)


def _warn_once(key: str, reason: str, message: str, *args: Any) -> None:
    with _lock:
        if (key, reason) in _warned:
            return
        _warned.add((key, reason))
    logger.warning(message, *args)


def _parse(rows: Any) -> Dict[str, Definition]:
    out: Dict[str, Definition] = {}
    for row in rows:
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        if not row.get("enabled", True):
            continue   # switched off in the panel: a state, not a defect — no warning
        item_id = str(row.get("item_id") or "").strip()
        alias = str(row.get("alias") or "").strip()
        if not item_id or not alias:
            _warn_once(pid, "incomplete", "Persona %s lacks item_id or alias — skipped", pid)
            continue
        out[pid] = Definition(
            id=pid, enabled=True, item_id=item_id, alias=alias,
            activation_phrase=str(row.get("activation_phrase") or "").strip(),
            revert_phrase=str(row.get("revert_phrase") or "").strip(),
            condition_id=str(row.get("condition_id") or "").strip(),
            max_duration_minutes=max(0, int(row.get("max_duration_minutes") or 0)),
            cooldown_minutes=max(0, int(row.get("cooldown_minutes") or 0)),
            transform_activity=(str(row.get("transform_activity") or "").strip()
                                or DEFAULT_TRANSFORM_ACTIVITY),
        )
    return out


def load() -> Dict[str, Definition]:
    """The usable personas, keyed by id (a fresh dict; the values are frozen).

    Cached per table write generation. The generation is captured BEFORE the
    table is read, so a snapshot read across a write is published under the
    old generation and never reused.
    """
    global _cache
    generation = store.definitions_generation()
    with _lock:
        key, defs = _cache
    if defs is not None and key == generation:
        return dict(defs)
    defs = _parse(store.list_definitions())
    with _lock:
        _cache = (generation, defs)
    return dict(defs)


def invalidate() -> None:
    """Drop the parsed table; the next ``load()`` reads it again."""
    global _cache
    with _lock:
        _cache = (None, None)


def for_item(item_id: str) -> Optional[Definition]:
    """The persona the item grants, or ``None``."""
    if not item_id:
        return None
    for definition in load().values():
        if definition.item_id == item_id:
            return definition
    return None
