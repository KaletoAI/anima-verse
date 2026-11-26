"""Core registry of quest object kinds (stage 2, plan D5).

Describes how the effects worker (:mod:`app.core.quest_effects`) and the engine's
reference-checking tick (:mod:`app.core.quest_engine`) check, remove and label a
world object that a quest run created.

This registry is core-only in stage 2 (not package-extensible); later core tasks
register additional kinds here.

Kind contract:
    ``exists(ref) -> Optional[bool]``
        ``True`` if the object still exists, ``False`` if it is confirmed gone,
        ``None`` if the read failed (never treated as "gone").
    ``remove(ref) -> str``
        One of :data:`REMOVE_DONE` (``"done"`` — removed now),
        :data:`REMOVE_GONE` (``"gone"`` — already absent), or
        :data:`REMOVE_LATER` (``"later"`` — transient failure, retry on a later pass).
    ``label(ref) -> str``
        Human-readable display label for the object.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

REMOVE_DONE = "done"
REMOVE_GONE = "gone"
REMOVE_LATER = "later"


@dataclass(frozen=True)
class ObjectKind:
    kind: str
    exists: Callable[[dict], Optional[bool]]
    remove: Callable[[dict], str]
    label: Callable[[dict], str]


_KINDS: Dict[str, ObjectKind] = {}


def register_kind(
    kind: str,
    *,
    exists: Callable[[dict], Optional[bool]],
    remove: Callable[[dict], str],
    label: Callable[[dict], str],
) -> None:
    """Register or replace an :class:`ObjectKind` by name."""
    _KINDS[kind] = ObjectKind(kind=kind, exists=exists, remove=remove, label=label)


def get_kind(kind: str) -> Optional[ObjectKind]:
    """Return the registered :class:`ObjectKind` for ``kind``, or ``None``."""
    return _KINDS.get(kind)


# --- Built-in kind: event ---------------------------------------------------------------------

def _event_exists(ref: dict) -> Optional[bool]:
    from app.models import events
    event_id = str((ref or {}).get("event_id") or "")
    return events.event_exists(event_id)


def _event_remove(ref: dict) -> str:
    from app.models import events
    event_id = str((ref or {}).get("event_id") or "")
    present = events.event_exists(event_id)
    if present is None:
        return REMOVE_LATER
    if not present:
        return REMOVE_GONE
    return REMOVE_DONE if events.delete_event(event_id) else REMOVE_GONE


def _event_label(ref: dict) -> str:
    from app.models import events
    event_id = str((ref or {}).get("event_id") or "")
    evt = events.get_event(event_id) if event_id else None
    text = str((evt or {}).get("text") or "").strip()
    return text or event_id


register_kind("event", exists=_event_exists, remove=_event_remove, label=_event_label)
