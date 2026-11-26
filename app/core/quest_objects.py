"""Core registry of quest object kinds (stage 2, plan D5).

Describes how the effects worker (:mod:`app.core.quest_effects`) and the engine's
reference-checking tick (:mod:`app.core.quest_engine`) check, remove and label a
world object that a quest run created.

This registry is core-only in stage 2 (not package-extensible); built-in kinds
registered here: ``event``, ``secret``, ``grant``, ``stat``, ``marker``,
``item``, ``room_item``, ``world_prop``, ``room_prop``, ``prop``.
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
    ref = ref or {}
    item_id = str(ref.get("item_id") or "")
    if not item_id:
        return False
    if "before" in ref:
        character = str(ref.get("character") or "")
        if not character:
            return False
        before = int(ref.get("before") or 0)
        qty = int(ref.get("quantity") or 1)
        try:
            current = inventory.get_item_quantity(character, item_id, strict=True)
        except Exception:  # noqa: BLE001
            return None
        return current >= before + qty
    # A live grant must not break its run when the avatar later uses, drops, or
    # hands on the item; only a pending row needs the inventory comparison to
    # decide whether the write happened.
    try:
        return inventory.get_item(item_id, strict=True) is not None
    except Exception:  # noqa: BLE001
        return None


def _grant_remove(ref: dict) -> str:
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    ref = ref or {}
    character = str(ref.get("character") or "")
    item_id = str(ref.get("item_id") or "")
    if not character or not item_id:
        return REMOVE_GONE
    qty = int(ref.get("quantity") or 1)
    with keyed_lock("character_profile", character):
        try:
            held = inventory.get_item_quantity(character, item_id, strict=True)
        except Exception:  # noqa: BLE001
            return REMOVE_LATER
        if "before" in ref:
            before = int(ref.get("before") or 0)
            to_reclaim = max(0, min(qty, held - before))
        else:
            to_reclaim = min(held, qty)
        if to_reclaim <= 0:
            return REMOVE_GONE
        ok = inventory.remove_from_inventory(character, item_id, quantity=to_reclaim, force=True)
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


# --- Built-in kind: item ----------------------------------------------------------------------

def _item_exists(ref: dict) -> Optional[bool]:
    from app.models import inventory
    item_id = str((ref or {}).get("item_id") or "")
    if not item_id:
        return False
    try:
        return inventory.get_item(item_id, strict=True) is not None
    except Exception:  # noqa: BLE001
        return None


def _item_remove(ref: dict) -> str:
    from app.models import inventory
    item_id = str((ref or {}).get("item_id") or "")
    if not item_id:
        return REMOVE_GONE
    try:
        res = inventory.remove_item_everywhere(item_id)
    except Exception:  # noqa: BLE001
        return REMOVE_LATER
    if res.get("shared"):
        return REMOVE_GONE
    if not res.get("found"):
        return REMOVE_GONE
    return REMOVE_DONE if res.get("deleted") else REMOVE_LATER


def _item_label(ref: dict) -> str:
    from app.models import inventory
    item_id = str((ref or {}).get("item_id") or "")
    item = inventory.get_item(item_id) if item_id else None
    name = str((item or {}).get("name") or "").strip()
    return name or item_id


register_kind("item", exists=_item_exists, remove=_item_remove, label=_item_label)


# --- Built-in kind: room_item -----------------------------------------------------------------

def _room_item_quantity(location_id: str, room_id: str, item_id: str) -> int:
    from app.models import inventory
    room_items = inventory.get_room_items(location_id, room_id, strict=True)
    return sum(int(ri.get("quantity", 1) or 1) for ri in room_items if ri.get("item_id") == item_id)


def _room_item_exists(ref: dict) -> Optional[bool]:
    from app.models import inventory
    from app.models.world import get_location_by_id, get_room_by_id
    ref = ref or {}
    location_id = str(ref.get("location_id") or "")
    room_id = str(ref.get("room_id") or "")
    item_id = str(ref.get("item_id") or "")
    if not location_id or not room_id or not item_id:
        return False
    if "before" in ref:
        before = int(ref.get("before") or 0)
        qty = int(ref.get("quantity") or 1)
        try:
            current = _room_item_quantity(location_id, room_id, item_id)
        except Exception:  # noqa: BLE001
            return None
        return current >= before + qty
    # A placement picked up by an avatar is normal play and must not break its
    # run; only a missing item definition, location, or room counts as gone.
    try:
        if inventory.get_item(item_id, strict=True) is None:
            return False
        loc = get_location_by_id(location_id, strict=True)
        if loc is None:
            return False
        return get_room_by_id(loc, room_id) is not None
    except Exception:  # noqa: BLE001
        return None


def _room_item_remove(ref: dict) -> str:
    from app.models import inventory
    ref = ref or {}
    location_id = str(ref.get("location_id") or "")
    room_id = str(ref.get("room_id") or "")
    item_id = str(ref.get("item_id") or "")
    if not location_id or not room_id or not item_id:
        return REMOVE_GONE
    qty = int(ref.get("quantity") or 1)
    try:
        current = _room_item_quantity(location_id, room_id, item_id)
    except Exception:  # noqa: BLE001
        return REMOVE_LATER
    if "before" in ref:
        before = int(ref.get("before") or 0)
        to_remove = max(0, min(qty, current - before))
    else:
        to_remove = qty
    if current <= 0 or to_remove <= 0:
        return REMOVE_GONE
    ok = inventory.remove_item_from_room(location_id, room_id, item_id, quantity=min(current, to_remove))
    return REMOVE_DONE if ok else REMOVE_LATER


def _room_item_label(ref: dict) -> str:
    from app.models import inventory
    ref = ref or {}
    location_id = str(ref.get("location_id") or "")
    room_id = str(ref.get("room_id") or "")
    item_id = str(ref.get("item_id") or "")
    item = inventory.get_item(item_id) if item_id else None
    name = str((item or {}).get("name") or "").strip() or item_id
    return f"{name} in {location_id}/{room_id}"


register_kind("room_item", exists=_room_item_exists, remove=_room_item_remove, label=_room_item_label)


# --- Built-in kind: world_prop ----------------------------------------------------------------

def _world_prop_exists(ref: dict) -> Optional[bool]:
    from app.models import world_props
    placement_id = str((ref or {}).get("placement_id") or "")
    if not placement_id:
        return False
    try:
        return any(r.get("id") == placement_id for r in world_props.list_world_props())
    except Exception:  # noqa: BLE001
        return None


def _world_prop_remove(ref: dict) -> str:
    import json
    from app.models import world_props
    ref = ref or {}
    placement_id = str(ref.get("placement_id") or "")
    if not placement_id:
        return REMOVE_GONE
    try:
        rows = world_props.list_world_props()
        cur = next((r for r in rows if r.get("id") == placement_id), None)
        if cur is None:
            return REMOVE_GONE
        written = ref.get("written")
        if isinstance(written, dict) and written:
            if json.loads(json.dumps(cur)) != json.loads(json.dumps(written)):
                return REMOVE_GONE
        if world_props.delete_world_prop(placement_id):
            return REMOVE_DONE
        still_there = any(r.get("id") == placement_id for r in world_props.list_world_props())
        return REMOVE_LATER if still_there else REMOVE_GONE
    except Exception:  # noqa: BLE001
        return REMOVE_LATER


def _world_prop_label(ref: dict) -> str:
    from app.core import props
    ref = ref or {}
    placement_id = str(ref.get("placement_id") or "")
    written = ref.get("written") if isinstance(ref.get("written"), dict) else {}
    prop_id = str(written.get("prop_id") or "")
    if not prop_id and placement_id:
        try:
            from app.models import world_props
            cur = next((r for r in world_props.list_world_props() if r.get("id") == placement_id), None)
            prop_id = str((cur or {}).get("prop_id") or "")
        except Exception:  # noqa: BLE001
            prop_id = ""
    meta = props.read_sidecar(prop_id, read_only=True) if prop_id else {}
    name = str(meta.get("name") or "").strip() or prop_id
    if name and placement_id:
        return f"{name} ({placement_id})"
    return name or placement_id


register_kind("world_prop", exists=_world_prop_exists, remove=_world_prop_remove, label=_world_prop_label)


# --- Built-in kind: room_prop -----------------------------------------------------------------

def _room_prop_exists(ref: dict) -> Optional[bool]:
    from app.models import world
    ref = ref or {}
    location_id = str(ref.get("location_id") or "")
    room_id = str(ref.get("room_id") or "")
    place_id = str(ref.get("place_id") or "")
    if not location_id or not room_id or not place_id:
        return False
    try:
        loc = world.get_location_by_id(location_id, strict=True)
        if loc is None:
            return False
        room = world.get_room_by_id(loc, room_id)
        if room is None:
            return False
        layout = room.get("layout")
        if not isinstance(layout, dict):
            return False
        return any(
            isinstance(p, dict) and p.get("id") == place_id
            for p in (layout.get("props") or [])
        )
    except Exception:  # noqa: BLE001
        return None


def _room_prop_remove(ref: dict) -> str:
    from app.models import world
    ref = ref or {}
    location_id = str(ref.get("location_id") or "")
    room_id = str(ref.get("room_id") or "")
    place_id = str(ref.get("place_id") or "")
    if not location_id or not room_id or not place_id:
        return REMOVE_GONE
    try:
        removed = world.remove_room_props(location_id, room_id, [place_id])
        return REMOVE_DONE if removed >= 1 else REMOVE_GONE
    except Exception:  # noqa: BLE001
        return REMOVE_LATER


def _room_prop_label(ref: dict) -> str:
    from app.core import props
    ref = ref or {}
    location_id = str(ref.get("location_id") or "")
    room_id = str(ref.get("room_id") or "")
    prop_id = str(ref.get("prop_id") or "")
    meta = props.read_sidecar(prop_id, read_only=True) if prop_id else {}
    name = str(meta.get("name") or "").strip() or prop_id
    return f"{name} in {location_id}/{room_id}"


register_kind("room_prop", exists=_room_prop_exists, remove=_room_prop_remove, label=_room_prop_label)


# --- Built-in kind: prop ----------------------------------------------------------------------

def _prop_exists(ref: dict) -> Optional[bool]:
    from app.core import props
    pid = str((ref or {}).get("prop_id") or "")
    if not pid:
        return False
    try:
        return bool(props.read_sidecar(pid, read_only=True))
    except Exception:  # noqa: BLE001
        return None


def _prop_remove(ref: dict) -> str:
    from app.core import props, scene_recipe
    from app.models import world, world_props
    pid = str((ref or {}).get("prop_id") or "")
    if not pid:
        return REMOVE_GONE
    try:
        if props.is_pending(pid):
            return REMOVE_LATER
        if not props.read_sidecar(pid, read_only=True):
            return REMOVE_GONE
        world_props.delete_world_props_of(pid)
        for loc in world.list_locations():
            loc_id = str(loc.get("id") or "")
            if not loc_id:
                continue
            for room in (loc.get("rooms") or []):
                if not isinstance(room, dict):
                    continue
                room_id = str(room.get("id") or "")
                layout = room.get("layout")
                if not room_id or not isinstance(layout, dict):
                    continue
                place_ids = [
                    str(p.get("id"))
                    for p in (layout.get("props") or [])
                    if isinstance(p, dict) and p.get("prop_id") == pid and p.get("id")
                ]
                if place_ids:
                    world.remove_room_props(loc_id, room_id, place_ids)
        props.delete_prop(pid)
        scene_recipe.invalidate_prop_lib_token()
        return REMOVE_DONE if not props.read_sidecar(pid, read_only=True) else REMOVE_LATER
    except Exception:  # noqa: BLE001
        return REMOVE_LATER


def _prop_label(ref: dict) -> str:
    from app.core import props
    pid = str((ref or {}).get("prop_id") or "")
    meta = props.read_sidecar(pid, read_only=True) if pid else {}
    return str(meta.get("name") or "").strip() or pid


register_kind("prop", exists=_prop_exists, remove=_prop_remove, label=_prop_label)
