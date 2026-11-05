"""Transformation definitions — the package table ``transformation_definitions``.

Each row lets a LEADER turn into one of its linked characters (the ``body``,
``app.core.linked_characters``) while it holds the power item. Rows are
written by the Transformation panel on the leader (Game-Admin → Characters →
<leader> → Skills, ``panel.py``) through ``store``. The body's character name
is the label everywhere (status, narration, knower secret).

``load()`` turns the rows into frozen :class:`Definition` objects keyed by
``id`` and skips, with one warning per record per process, every row that
lacks its leader, body or item; a disabled row is skipped silently. Whether
the body is (still) linked to the leader is checked where it matters — the
transform (``engine``) and the panel save — not here: the link map is live.

The defaults below are the ONE source: the table's column defaults are built
from them (``store.ensure_schema``).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.log import get_logger

from plugins.transformation import store

logger = get_logger("transformation")

DEFAULT_MAX_DURATION_MINUTES = 60
DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_TRANSFORM_ACTIVITY = "transforming"


@dataclass(frozen=True)
class Definition:
    id: str
    leader: str
    body: str
    item_id: str
    activation_phrase: str
    revert_phrase: str
    max_duration_minutes: int
    cooldown_minutes: int
    transform_activity: str
    condition_id: str
    enabled: bool


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
        did = str(row.get("id") or "").strip()
        if not did:
            continue
        if not row.get("enabled", True):
            continue   # switched off in the panel: a state, not a defect — no warning
        leader = str(row.get("leader") or "").strip()
        body = str(row.get("body") or "").strip()
        item_id = str(row.get("item_id") or "").strip()
        if not leader or not body or not item_id:
            _warn_once(did, "incomplete",
                       "Transformation %s lacks its leader, body or item — skipped", did)
            continue
        out[did] = Definition(
            id=did, leader=leader, body=body, item_id=item_id,
            activation_phrase=str(row.get("activation_phrase") or "").strip(),
            revert_phrase=str(row.get("revert_phrase") or "").strip(),
            max_duration_minutes=max(0, int(row.get("max_duration_minutes") or 0)),
            cooldown_minutes=max(0, int(row.get("cooldown_minutes") or 0)),
            transform_activity=(str(row.get("transform_activity") or "").strip()
                                or DEFAULT_TRANSFORM_ACTIVITY),
            condition_id=str(row.get("condition_id") or "").strip(),
            enabled=True,
        )
    return out


def load() -> Dict[str, Definition]:
    """The usable definitions, keyed by id (a fresh dict; the values are frozen).

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


def for_leader(leader: str) -> List[Definition]:
    """The usable definitions of ``leader``, in creation order."""
    if not leader:
        return []
    return [d for d in load().values() if d.leader == leader]


def for_body(body: str) -> List[Definition]:
    """The usable definitions that turn their leader into ``body``."""
    if not body:
        return []
    return [d for d in load().values() if d.body == body]
