"""Core registry of quest object kinds (stage 2, plan D5).

Describes how the effects worker (:mod:`app.core.quest_effects`) and the engine's
reference-checking tick (:mod:`app.core.quest_engine`) check, remove and label a
world object that a quest run created.

This registry is core-only in stage 2 (not package-extensible); built-in kinds
registered here: ``event``, ``secret``, ``grant``, ``stat``, ``marker``.
For ``event``, an absent row whose ``ref["expires_at"]`` has already passed in
game time still counts as existing (it ran out on schedule rather than breaking).

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
    from app.core.game_time import GameTime
    from app.core.timeutils import game_time
    from app.models import events
    event_id = str((ref or {}).get("event_id") or "")
    present = events.event_exists(event_id)
    if present is False:
        expires_at = (ref or {}).get("expires_at")
        if expires_at:
            # A news line swept after its scheduled expires_at ran out as intended,
            # not as a broken reference.
            try:
                if game_time() > GameTime.parse(expires_at):
                    return True
            except (ValueError, TypeError):
                pass
    return present


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


# --- Built-in kind: secret --------------------------------------------------------------------

def _secret_exists(ref: dict) -> Optional[bool]:
    from app.models import secrets
    owner = str((ref or {}).get("owner") or "")
    secret_id = str((ref or {}).get("secret_id") or "")
    if not owner or not secret_id:
        return False
    try:
        rows = secrets.list_secrets(owner, strict=True)
    except Exception:  # noqa: BLE001
        return None
    return any(s.get("id") == secret_id for s in rows)


def _secret_remove(ref: dict) -> str:
    from app.models import secrets
    present = _secret_exists(ref)
    if present is None:
        return REMOVE_LATER
    if not present:
        return REMOVE_GONE
    owner = str((ref or {}).get("owner") or "")
    secret_id = str((ref or {}).get("secret_id") or "")
    return REMOVE_DONE if secrets.delete_secret(owner, secret_id) else REMOVE_LATER


def _secret_label(ref: dict) -> str:
    from app.models import secrets
    owner = str((ref or {}).get("owner") or "")
    secret_id = str((ref or {}).get("secret_id") or "")
    sec = secrets.get_secret(owner, secret_id) if owner and secret_id else None
    content = str((sec or {}).get("content") or "").strip()
    return content or secret_id


register_kind("secret", exists=_secret_exists, remove=_secret_remove, label=_secret_label)


# --- Built-in kind: grant ---------------------------------------------------------------------

def _grant_exists(ref: dict) -> Optional[bool]:
    from app.models import inventory
    item_id = str((ref or {}).get("item_id") or "")
    if not item_id:
        return False
    try:
        return inventory.get_item(item_id, strict=True) is not None
    except Exception:  # noqa: BLE001
        return None


def _grant_remove(ref: dict) -> str:
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    character = str((ref or {}).get("character") or "")
    item_id = str((ref or {}).get("item_id") or "")
    if not character or not item_id:
        return REMOVE_GONE
    qty = int((ref or {}).get("quantity") or 1)
    with keyed_lock("character_profile", character):
        try:
            held = inventory.get_item_quantity(character, item_id, strict=True)
        except Exception:  # noqa: BLE001
            return REMOVE_LATER
        if held <= 0:
            return REMOVE_GONE
        ok = inventory.remove_from_inventory(character, item_id, quantity=min(held, qty), force=True)
        return REMOVE_DONE if ok else REMOVE_LATER


def _grant_label(ref: dict) -> str:
    from app.models import inventory
    character = str((ref or {}).get("character") or "")
    item_id = str((ref or {}).get("item_id") or "")
    item = inventory.get_item(item_id) if item_id else None
    name = str((item or {}).get("name") or "").strip() or item_id
    return f"{name} -> {character}"


register_kind("grant", exists=_grant_exists, remove=_grant_remove, label=_grant_label)


# --- Built-in kind: stat ----------------------------------------------------------------------

def _stat_exists(ref: dict) -> Optional[bool]:
    return True


def _stat_remove(ref: dict) -> str:
    # A stat change is never undone (D5).
    return REMOVE_DONE


def _stat_label(ref: dict) -> str:
    character = str((ref or {}).get("character") or "")
    changes = (ref or {}).get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        return character
    parts = [
        f"{k} {v['old']} -> {v['new']}"
        for k, v in changes.items()
        if isinstance(v, dict) and "old" in v and "new" in v
    ]
    return f"{character}: " + ", ".join(parts) if parts else character


register_kind("stat", exists=_stat_exists, remove=_stat_remove, label=_stat_label)


# --- Built-in kind: marker --------------------------------------------------------------------

def _marker_exists(ref: dict) -> Optional[bool]:
    return True


def _marker_remove(ref: dict) -> str:
    return REMOVE_DONE


def _marker_label(ref: dict) -> str:
    return str((ref or {}).get("effect_key") or "")


register_kind("marker", exists=_marker_exists, remove=_marker_remove, label=_marker_label)
