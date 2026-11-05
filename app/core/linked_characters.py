"""Linked characters — one mind in several bodies (core, public).

A LINKED character (a body) names a LEADING character in its profile
(``linked_to``). The leader owns the mind: what makes the leader's inner self
is read by every body of the family, and only ONE family member stands in the
world at a time — the others are DORMANT (``characters.status = 'dormant'``,
see ``app.models.character.DORMANT_STATUS``). Spec:
``docs/superpowers/specs/2026-11-05-linked-characters-design.md``.

What this module owns:

* the link map (``leader_of`` / ``bodies_of`` / ``family_of`` / ``mind_of`` /
  ``present_member``) — one cached query over ``profile_json.linked_to``,
  invalidated by every profile save that changes the link and by a delete;
* the locked profile fields (``LOCKED_PROFILE_FIELDS``) a body reads LIVE from
  its leader, and the shared soul sections (``soul_owner``);
* linking, unlinking and creating a body (``link`` / ``unlink`` /
  ``create_linked``), with the refusal states of a swap (``swap_refusal``);
* the two raw placement helpers dormancy needs (``make_dormant`` /
  ``place_at``) — written directly, because the structured location setter
  runs compliance, party drag, discovery and journey aborts, all of which
  belong to a character that MOVES, not to one leaving or re-entering the
  world.

The core names no package here: transformations (``plugins/transformation``)
are only one trigger of a swap.
"""
from __future__ import annotations

import threading
from contextlib import ExitStack
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("linked_characters")

#: Profile fields a body never stores: they are read live from the leader.
LOCKED_PROFILE_FIELDS: Tuple[str, ...] = ("gender", "age")

#: Soul sections a body MAY share with its leader (``goals`` never: a body has
#: its own goals — user decision).
SHAREABLE_SOUL_SECTIONS: Tuple[str, ...] = (
    "soul", "beliefs", "lessons", "personality", "presence", "tasks",
    "roleplay_rules")

#: What a body shares when its profile names no list.
DEFAULT_SHARED_SOUL: Tuple[str, ...] = ("soul", "beliefs", "lessons")

#: Refusal codes of :func:`swap_refusal` → the English reason a panel shows.
SWAP_REFUSAL_TEXT: Dict[str, str] = {
    "journey": "Travelling right now — wait until the journey ends.",
    "sleeping": "Asleep right now — wake them first.",
    "interaction": "Busy with someone (a pair interaction or an open invitation).",
    "prop_action": "In the middle of a furniture action.",
    "reading": "Reading something right now.",
    "party": "In a party — leave it first.",
}

#: :func:`link` of a character that is some user's active avatar.
AVATAR_REFUSAL_TEXT = "Pick another avatar for {user} first: {name} is their active character."

PROFILE_KEY = "linked_to"
SHARED_KEY = "shared_soul_sections"


# ---------------------------------------------------------------------------
# The link map
# ---------------------------------------------------------------------------

_lock = threading.RLock()
#: db path -> {"body": {body: (leader, shared tuple or None)}, "lead": {leader: [bodies]}}
_cache: Dict[str, Dict[str, Any]] = {}


def _db_key() -> str:
    from app.core.db import get_db_path
    return str(get_db_path())


_EMPTY_MAP: Dict[str, Any] = {"body": {}, "lead": {}}


def _load_map() -> Dict[str, Any]:
    """The link map of the current world — ONE query, cached per DB path.

    No world open (storage not initialised) = nobody is linked; nothing is
    cached for it.
    """
    try:
        key = _db_key()
    except Exception:  # noqa: BLE001 — StorageNotInitialised and friends
        return _EMPTY_MAP
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        import json
        from app.core.db import get_connection
        body: Dict[str, Tuple[str, Optional[Tuple[str, ...]]]] = {}
        lead: Dict[str, List[str]] = {}
        try:
            rows = get_connection().execute(
                "SELECT name, json_extract(profile_json, '$.linked_to'), "
                "       json_extract(profile_json, '$.shared_soul_sections') "
                "FROM characters WHERE json_valid(profile_json) "
                "  AND COALESCE(json_extract(profile_json, '$.linked_to'), '') <> ''"
            ).fetchall()
        except Exception as e:  # noqa: BLE001 — no table yet = no links,
            logger.debug("link map query failed: %s", e)  # and nothing cached
            return _EMPTY_MAP
        for name, leader, shared_raw in rows:
            shared: Optional[Tuple[str, ...]] = None
            if shared_raw is not None:
                try:
                    parsed = json.loads(shared_raw)
                except (TypeError, ValueError):
                    parsed = []
                if isinstance(parsed, list):
                    shared = tuple(s for s in (str(x) for x in parsed)
                                   if s in SHAREABLE_SOUL_SECTIONS)
            body[name] = (str(leader), shared)
            lead.setdefault(str(leader), []).append(name)
        for names in lead.values():
            names.sort()
        built = {"body": body, "lead": lead}
        _cache[key] = built
        return built


def invalidate() -> None:
    """Drop the cached link map (every world)."""
    with _lock:
        _cache.clear()


def note_saved(name: str, linked_to: str, shared: Any) -> None:
    """A profile save hook: invalidate when the stored link differs from the map.

    Called by ``save_character_profile`` after a committed write with the
    values the blob now holds — so the map is rebuilt exactly when a link or
    a shared-section list changed, not on every save.
    """
    try:
        key = _db_key()
    except Exception:  # noqa: BLE001
        return
    with _lock:
        cached = _cache.get(key)
        if cached is None:
            return
        have = cached["body"].get(name)
        if not linked_to:
            if have is not None:
                _cache.pop(key, None)
            return
        want_shared = (tuple(s for s in (str(x) for x in shared)
                             if s in SHAREABLE_SOUL_SECTIONS)
                       if isinstance(shared, list) else None)
        if have != (linked_to, want_shared):
            _cache.pop(key, None)


def leader_of(name: str) -> Optional[str]:
    """The leader a body is linked to, or None for everybody else."""
    if not name:
        return None
    hit = _load_map()["body"].get(name)
    return hit[0] if hit else None


def is_linked(name: str) -> bool:
    """Whether ``name`` is a body (its profile names a leader)."""
    return leader_of(name) is not None


def bodies_of(leader: str) -> List[str]:
    """The bodies linked to ``leader``, sorted by name ([] for a non-leader)."""
    return list(_load_map()["lead"].get(leader or "", []))


def mind_of(name: str) -> str:
    """The mind owner: the leader of a body, otherwise the name itself."""
    return leader_of(name) or name


def family_of(name: str) -> List[str]:
    """Leader first, then its bodies sorted; ``[name]`` for an unlinked character."""
    if not name:
        return []
    mind = mind_of(name)
    return [mind] + bodies_of(mind)


def present_member(name: str) -> Optional[str]:
    """The family member that is not dormant, or None when all are."""
    from app.models.character import DORMANT_STATUS, get_character_status
    for member in family_of(name):
        if get_character_status(member) != DORMANT_STATUS:
            return member
    return None


def placement_owner(name: str) -> str:
    """Whose place ``name`` has. A family has ONE place — the place of the
    member standing in the world — so a DORMANT member's place is that
    member's (``""`` while nobody of the family stands anywhere); everybody
    else is its own placement owner. Every location/room setter routes a
    write for ``name`` to this character."""
    if not name or len(family_of(name)) < 2:
        return name
    from app.models.character import DORMANT_STATUS, get_character_status
    if get_character_status(name) != DORMANT_STATUS:
        return name
    return present_member(name) or ""


def shared_soul_sections(name: str) -> Tuple[str, ...]:
    """The soul sections a body reads from its leader (``()`` when not linked)."""
    hit = _load_map()["body"].get(name or "")
    if not hit:
        return ()
    return hit[1] if hit[1] is not None else DEFAULT_SHARED_SOUL


def _section_id(section: str) -> str:
    """A soul section key from a key or its relative file path (soul/x.md)."""
    sec = (section or "").strip()
    if "/" in sec or sec.endswith(".md"):
        from app.core.soul_sections import SECTION_FILE_MAP
        for sid, rel in SECTION_FILE_MAP.items():
            if rel == sec:
                return sid
        base = sec.rsplit("/", 1)[-1]
        return base[:-3] if base.endswith(".md") else base
    return sec


def soul_owner(name: str, section: str) -> str:
    """Whose soul file ``section`` (a key like ``beliefs`` or its path
    ``soul/beliefs.md``) of ``name`` is: the leader when the section is
    shared, otherwise ``name`` itself."""
    shared = shared_soul_sections(name)
    if shared and _section_id(section) in shared:
        return leader_of(name) or name
    return name


# ---------------------------------------------------------------------------
# Refusal states
# ---------------------------------------------------------------------------

def _prop_action_running(name: str) -> bool:
    from app.core import prop_action_store as store
    from app.core.db import get_connection
    try:
        row = get_connection().execute(
            "SELECT 1 FROM prop_action_runs WHERE " + store.TAKES_PART + " "
            "AND status NOT IN ('completed','cancelled','failed') LIMIT 1",
            (name, name)).fetchone()
    except Exception:  # noqa: BLE001 — no table = no run
        return False
    return row is not None


def swap_refusal(name: str) -> str:
    """Why ``name`` cannot leave its body right now — ``""`` when it can.

    One of ``journey`` (a journey or a movement target), ``sleeping``,
    ``interaction`` (a pair interaction, an approach, an open invitation in
    either direction), ``prop_action``, ``reading`` (an item-reading
    session), ``party``. ``SWAP_REFUSAL_TEXT`` holds the reason to show.
    """
    from app.models.character import get_character_profile, is_character_sleeping
    profile = get_character_profile(name) or {}
    from app.core.travel_engine import get_journey
    if get_journey(name, profile=profile) or str(profile.get("movement_target") or "").strip():
        return "journey"
    if is_character_sleeping(name, profile=profile):
        return "sleeping"
    from app.core import interaction_engine as ie
    if (ie.get_interaction(name, profile=profile) or ie.approach_of(name)
            or ie.pending_invites_for(name) or ie.outgoing_invite_of(name)):
        return "interaction"
    if _prop_action_running(name):
        return "prop_action"
    from app.core.item_reading import active_session
    if active_session(name):
        return "reading"
    from app.core.party_engine import is_in_party
    if is_in_party(name):
        return "party"
    return ""


def delete_refusal(name: str) -> str:
    """Why ``name`` may not be deleted right now — ``""`` when it may.

    A leader with bodies is refused (the bodies would lose their mind); a
    PRESENT body whose leader is dormant is refused (the leader would be
    stranded). A dormant body may be deleted — it stands nowhere.
    """
    bodies = bodies_of(name)
    if bodies:
        return (f"{name} leads linked characters ({', '.join(bodies)}) — "
                "unlink or delete the linked characters first.")
    leader = leader_of(name)
    if leader:
        from app.models.character import DORMANT_STATUS, get_character_status
        if (get_character_status(name) != DORMANT_STATUS
                and get_character_status(leader) == DORMANT_STATUS):
            return (f"{name} stands in the world for {leader} right now — "
                    "revert first.")
    return ""


# ---------------------------------------------------------------------------
# Placement helpers (raw: no compliance, party drag, discovery)
# ---------------------------------------------------------------------------

def make_dormant(name: str) -> bool:
    """Take ``name`` out of the world: status ``dormant``, no location, room,
    point or seat, and no off-map return marker. Stores nothing else.

    Returns True when the status was written.
    """
    from app.core import sync_topics
    from app.core.keyed_lock import keyed_lock
    from app.core.npc_pool import _unplace
    from app.models.character import (DORMANT_STATUS, get_character_current_location,
                                      get_character_profile, save_character_profile,
                                      set_character_status)
    old_loc = get_character_current_location(name) or ""
    if not set_character_status(name, DORMANT_STATUS):
        return False
    _unplace(name)
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        changed = False
        if profile.get("place") is not None:
            profile["place"] = None
            changed = True
        for key in ("_offmap_return_location", "_offmap_return_room"):
            if key in profile:
                profile.pop(key, None)
                changed = True
        stored = save_character_profile(name, profile) if changed else False
    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("location_changed", name, from_id=old_loc, to_id="", room_id="")
    except Exception:  # noqa: BLE001
        pass
    if stored:
        sync_topics.changed_at(name)
    logger.info("Dormant: %s (was at %s)", name, old_loc or "-")
    return True


def place_at(name: str, location_id: str, room_id: str = "") -> bool:
    """Put ``name`` at ``location_id``/``room_id`` by a direct profile write —
    without the location setter's compliance/party/discovery side effects.

    No room = the location's arrival room (entry room, else the ground). An
    empty location leaves the character unplaced. Returns True when stored.
    """
    from app.core import sync_topics
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (_place_on_return, _write_character_pos,
                                      get_character_profile, save_character_profile)
    loc_id = (location_id or "").strip()
    room = (room_id or "").strip()
    if loc_id and not room:
        from app.models.world import get_arrival_room_id, get_location_by_id
        loc = get_location_by_id(loc_id)
        room = get_arrival_room_id(loc) if loc else ""
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        profile["current_location"] = loc_id
        profile["current_room"] = room if loc_id else ""
        profile["place"] = None
        profile.pop("_offmap_return_location", None)
        profile.pop("_offmap_return_room", None)
        stored = save_character_profile(name, profile)
    if not stored:
        return False
    if loc_id:
        _place_on_return(name, loc_id, room)
    else:
        _write_character_pos(name, None, None)   # unplaced: no point either
    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("location_changed", name, from_id="", to_id=loc_id, room_id=room)
    except Exception:  # noqa: BLE001
        pass
    sync_topics.moved(name, "", loc_id)
    return True


# ---------------------------------------------------------------------------
# The swap and the family repair
# ---------------------------------------------------------------------------

#: Provider capability (``app.core.hooks``): ``fn(leader) -> Optional[str]``
#: names the family member that SHOULD stand in the world (a transformation
#: package answers with the body while a transformation is active). No
#: provider, or an answer outside the family = the leader.
EXPECTED_PRESENT_PROVIDER = "linked.expected_present"

#: Profile key of a DORMANT member: where it stood when it left the world
#: (``{location, room, pos_x, pos_z, pos_yaw, at}``) — what the repair puts a
#: family back on when nobody stands anywhere.
DORMANT_FROM_KEY = "dormant_from"

_STATE_PRESENCE_COLS = ("current_location", "current_room", "current_activity",
                        "current_feeling", "pose_key", "pose_flavor",
                        "location_changed_at", "activity_changed_at",
                        "pos_x", "pos_z", "pos_yaw")


def _read_presence(conn, name: str) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """``(status, state columns, stored profile blob)`` read on ``conn``."""
    import json
    row = conn.execute("SELECT COALESCE(status,''), profile_json FROM characters WHERE name=?",
                       (name,)).fetchone()
    if row is None:
        raise LookupError(f"unknown character {name}")
    try:
        blob = json.loads(row[1] or "{}")
    except (TypeError, ValueError):
        blob = {}
    srow = conn.execute(
        f"SELECT {', '.join(_STATE_PRESENCE_COLS)} FROM character_state "
        "WHERE character_name=?", (name,)).fetchone()
    state = {c: (srow[i] if srow else None) for i, c in enumerate(_STATE_PRESENCE_COLS)}
    return row[0], state, blob if isinstance(blob, dict) else {}


def _write_presence(conn, name: str, status: str, state: Dict[str, Any],
                    blob: Dict[str, Any]) -> None:
    """Write one character's status, presence columns and profile blob on
    ``conn`` — inside the caller's transaction, nothing committed here.

    ``state`` holds :data:`_STATE_PRESENCE_COLS` keys; the report origin of
    the point (``pos_session``/``pos_seq``) is always cleared: a swap is a
    server move, never the echo of a client report.
    """
    import json
    from app.core.timeutils import utc_now_iso
    conn.execute("UPDATE characters SET status=?, profile_json=?, updated_at=? WHERE name=?",
                 (status, json.dumps(blob, ensure_ascii=False), utc_now_iso(), name))
    cols = [c for c in _STATE_PRESENCE_COLS if c in state]
    values = [state[c] for c in cols]
    cur = conn.execute(
        "UPDATE character_state SET " + ", ".join(f"{c}=?" for c in cols)
        + ", pos_session=NULL, pos_seq=NULL WHERE character_name=?",
        (*values, name))
    if cur.rowcount == 0:
        conn.execute(
            f"INSERT INTO character_state (character_name, {', '.join(cols)}) "
            f"VALUES (?{', ?' * len(cols)})", (name, *values))


def _placement_of(state: Dict[str, Any]) -> Dict[str, Any]:
    """The ``dormant_from`` record of a presence state."""
    from app.core.timeutils import utc_now_iso
    return {"location": state.get("current_location") or "",
            "room": state.get("current_room") or "",
            "pos_x": state.get("pos_x"), "pos_z": state.get("pos_z"),
            "pos_yaw": state.get("pos_yaw"), "at": utc_now_iso()}


_UNPLACED = {"current_location": "", "current_room": "",
             "pos_x": None, "pos_z": None, "pos_yaw": None}


def _drop_offmap(blob: Dict[str, Any]) -> None:
    blob.pop("_offmap_return_location", None)
    blob.pop("_offmap_return_room", None)


def _publish_presence(name: str, from_id: str, to_id: str, room_id: str) -> None:
    """The presence pair ``appear_in_world`` / ``enter_offmap_sleep`` publish."""
    from app.core import sync_topics
    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("location_changed", name, from_id=from_id, to_id=to_id,
                       room_id=room_id)
    except Exception:  # noqa: BLE001
        pass
    sync_topics.moved(name, from_id, to_id)


def _know_location(name: str, location_id: str) -> None:
    """A character always knows the location it stands in."""
    if not location_id:
        return
    from app.models.character import add_known_location, get_known_locations
    if location_id not in get_known_locations(name):
        add_known_location(name, location_id)


def _switch_avatars(old: str, new: str) -> List[str]:
    """Every user whose active character is ``old`` now controls ``new`` (and
    is allowed it). Background-safe: the users table, no request context.
    Returns the switched user ids."""
    from app.core import sync_topics
    from app.core.users import list_users, update_user
    switched: List[str] = []
    for user in list_users():
        settings = dict(user.get("settings") or {})
        if settings.get("avatar_released"):
            continue
        active = str(settings.get("active_character")
                     or settings.get("current_character") or "").strip()
        if not active or active != old:
            continue
        settings["active_character"] = new
        settings["current_character"] = new
        if settings.get("default_character") == old:
            settings["default_character"] = new
        fields: Dict[str, Any] = {"settings": settings}
        allowed = list(user.get("allowed_characters") or [])
        if new not in allowed:
            fields["allowed_characters"] = allowed + [new]
        try:
            if update_user(user["id"], **fields):
                switched.append(str(user["id"]))
        except Exception as e:  # noqa: BLE001
            logger.warning("swap: avatar of %s not switched to %s: %s",
                           user.get("username"), new, e)
    for user_id in switched:
        sync_topics.rebind_user(user_id)
    return switched


def _move_items(src: str, dst: str, item_ids: Any) -> List[str]:
    """Move the listed carried items from ``src`` to ``dst`` with force.

    ``transferable`` and a lock do not block (the swap moves the mind's own
    things into the other body). Worn clothing (``equipped_pieces``) never
    moves; another equipped item is unequipped on ``src`` first. Returns the
    ids that moved.
    """
    from app.models.inventory import (_load_inventory, add_to_inventory,
                                      get_equipped_items, get_equipped_pieces,
                                      remove_from_inventory, unequip_item)
    moved: List[str] = []
    wanted = [str(i).strip() for i in (item_ids or ()) if str(i).strip()]
    if not wanted:
        return moved
    entries = {e.get("item_id"): e for e in (_load_inventory(src).get("inventory") or [])}
    worn = set(get_equipped_pieces(src).values())
    for item_id in dict.fromkeys(wanted):
        entry = entries.get(item_id)
        if entry is None:
            continue
        if item_id in worn:
            logger.info("swap %s -> %s: %s is worn clothing — stays", src, dst, item_id)
            continue
        if item_id in get_equipped_items(src):
            unequip_item(src, item_id, source="linked_swap")
        qty = int(entry.get("quantity") or 1)
        if not add_to_inventory(dst, item_id, quantity=qty, obtained_from=src,
                                obtained_method="swap",
                                locked=True if entry.get("locked") else None):
            logger.warning("swap %s -> %s: %s could not be added — stays", src, dst, item_id)
            continue
        remove_from_inventory(src, item_id, quantity=qty, force=True)
        moved.append(item_id)
    return moved


def swap_presence(from_name: str, to_name: str, *, items: Any = (),
                  reason: str = "") -> Dict[str, Any]:
    """Put ``to_name`` exactly where ``from_name`` stands and take
    ``from_name`` out of the world — ``{"ok", "error"}`` (+ ``"refusal"``,
    the :func:`swap_refusal` code of a refused swap, and ``"items"``, the ids
    that moved).

    Both must belong to one family, ``from_name`` must stand in the world and
    ``to_name`` must be dormant; ``from_name`` must not be in a refusal state
    (the error is then ``SWAP_REFUSAL_TEXT[code]``). Copied to ``to_name``:
    location, room, point, yaw, activity, pose key/flavor, feeling and the
    seat; ``from_name`` gets status ``dormant``, no placement, no seat, no
    off-map marker, and its placement as ``dormant_from`` for the repair.
    Both statuses and placements are written in ONE transaction (under the
    family lock, the places lock of the location and both profile locks).
    Then the listed ``items`` move with force (:func:`_move_items`), every
    user controlling ``from_name`` controls ``to_name``, and the presence
    events are published for both. ``reason`` is only logged.
    """
    from app.core.db import transaction
    from app.core.interaction_engine import profile_locks
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (DORMANT_STATUS, _notify_prop_presence,
                                      get_character_status, is_out_of_world)
    src = (from_name or "").strip()
    dst = (to_name or "").strip()
    if not src or not dst or src == dst:
        return _fail("Pick two different characters of one family.")
    if not _exists(src) or not _exists(dst):
        return _fail(f"Unknown character: {src if not _exists(src) else dst}.")
    if mind_of(src) != mind_of(dst):
        return _fail(f"{src} and {dst} are not linked characters of one family.")
    leader = mind_of(src)
    with keyed_lock("linked_family", leader):
        if is_out_of_world(get_character_status(src)):
            return _fail(f"{src} does not stand in the world.")
        if get_character_status(dst) != DORMANT_STATUS:
            return _fail(f"{dst} stands in the world already.")
        code = swap_refusal(src)
        if code:
            return {"ok": False, "error": SWAP_REFUSAL_TEXT[code], "refusal": code}
        from app.models.character import get_character_current_location
        loc_key = get_character_current_location(src) or ""
        with ExitStack() as locks:
            if loc_key:
                # LOCK ORDER: places before character_profile (places.assign).
                locks.enter_context(keyed_lock("places", loc_key))
            locks.enter_context(profile_locks(src, dst))
            try:
                with transaction() as conn:
                    _st, src_state, src_blob = _read_presence(conn, src)
                    _dt, _dst_state, dst_blob = _read_presence(conn, dst)
                    seat = src_blob.get("place") if isinstance(src_blob.get("place"), dict) else None
                    dst_blob["place"] = dict(seat) if seat else None
                    dst_blob.pop(DORMANT_FROM_KEY, None)
                    _drop_offmap(dst_blob)
                    src_blob["place"] = None
                    src_blob[DORMANT_FROM_KEY] = _placement_of(src_state)
                    _drop_offmap(src_blob)
                    _write_presence(conn, dst, "", dict(src_state), dst_blob)
                    _write_presence(conn, src, DORMANT_STATUS, dict(_UNPLACED), src_blob)
            except Exception as e:  # noqa: BLE001 — rolled back, nothing changed
                logger.error("swap %s -> %s failed and was rolled back: %s", src, dst, e)
                return _fail("The swap could not be stored.")
    loc = src_state.get("current_location") or ""
    room = src_state.get("current_room") or ""
    _notify_prop_presence(loc, room)
    try:
        _know_location(dst, loc)
    except Exception as e:  # noqa: BLE001
        logger.warning("swap: known location of %s not stored: %s", dst, e)
    moved = _move_items(src, dst, items)
    _switch_avatars(src, dst)
    _publish_presence(src, loc, "", "")
    _publish_presence(dst, "", loc, room)
    logger.info("Swap %s -> %s at %s/%s%s%s", src, dst, loc or "-", room or "-",
                f" (items: {', '.join(moved)})" if moved else "",
                f" — {reason}" if reason else "")
    return {"ok": True, "error": "", "items": moved}


def _expected_present(leader: str, family: List[str]) -> str:
    """The member the provider names, else the leader."""
    from app.core.hooks import get_provider
    fn = get_provider(EXPECTED_PRESENT_PROVIDER)
    if fn is not None:
        try:
            named = fn(leader)
        except Exception as e:  # noqa: BLE001
            logger.warning("%s(%s) failed: %s", EXPECTED_PRESENT_PROVIDER, leader, e)
            named = None
        if named and named in family:
            return named
    return leader


def _stored_placement(blob: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The ``dormant_from`` record of a blob — None without one, or when its
    location no longer exists (a deleted location is no place to return to)."""
    rec = blob.get(DORMANT_FROM_KEY)
    if not isinstance(rec, dict):
        return None
    loc_id = str(rec.get("location") or "").strip()
    if not loc_id:
        return None
    from app.models.world import get_location_by_id
    return rec if get_location_by_id(loc_id) else None


def _restore(member: str, family: List[str]) -> bool:
    """Nobody of the family stands anywhere: put ``member`` back at its own
    stored placement, else at the most recent one of any member. Never
    invents a location — no stored placement = nothing happens (warning)."""
    from app.core.db import get_connection, transaction
    conn = get_connection()
    blobs = {m: _read_presence(conn, m)[2] for m in family}
    rec = _stored_placement(blobs[member])
    if rec is None:
        recs = [r for r in (_stored_placement(b) for b in blobs.values()) if r]
        rec = max(recs, key=lambda r: str(r.get("at") or "")) if recs else None
    if rec is None:
        logger.warning("Linked family of %s: nobody stands in the world and no "
                       "placement is stored — left as it is", family[0])
        return False
    state = {"current_location": rec.get("location") or "",
             "current_room": rec.get("room") or "",
             "pos_x": rec.get("pos_x"), "pos_z": rec.get("pos_z"),
             "pos_yaw": rec.get("pos_yaw")}
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("character_profile", member):
        with transaction() as tx:
            _st, _state, blob = _read_presence(tx, member)
            blob.pop(DORMANT_FROM_KEY, None)
            blob["place"] = None
            _drop_offmap(blob)
            _write_presence(tx, member, "", state, blob)
    from app.models.character import _notify_prop_presence
    _notify_prop_presence(state["current_location"], state["current_room"])
    try:
        _know_location(member, state["current_location"])
    except Exception as e:  # noqa: BLE001
        logger.debug("repair: known location of %s: %s", member, e)
    _publish_presence(member, "", state["current_location"], state["current_room"])
    logger.warning("Linked family repair: nobody stood in the world — %s placed at %s/%s",
                   member, state["current_location"], state["current_room"] or "-")
    return True


def _take_out(member: str) -> None:
    """A second present member leaves the world (repair): its placement is
    stored as ``dormant_from``, then :func:`make_dormant`."""
    from app.core.db import get_connection
    from app.models.character import get_character_profile, save_character_profile
    from app.core.keyed_lock import keyed_lock
    _st, state, _blob = _read_presence(get_connection(), member)
    with keyed_lock("character_profile", member):
        profile = get_character_profile(member) or {}
        profile[DORMANT_FROM_KEY] = _placement_of(state)
        save_character_profile(member, profile)
    make_dormant(member)
    logger.warning("Linked family repair: %s stood in the world as a second member — "
                   "now dormant", member)


def _repair_family(leader: str) -> bool:
    from app.models.character import get_character_status, is_out_of_world
    family = [leader] + bodies_of(leader)
    changed = False
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("linked_family", leader):
        present = [m for m in family if not is_out_of_world(get_character_status(m))]
        expected = _expected_present(leader, family)
        if not present:
            if _restore(expected, family):
                changed = True
                present = [expected]
        elif len(present) > 1:
            keeper = (expected if expected in present
                      else leader if leader in present else present[0])
            for member in present:
                if member != keeper:
                    _take_out(member)
            present = [keeper]
            changed = True
        if len(present) == 1:
            for member in family:
                if member != present[0] and _switch_avatars(member, present[0]):
                    changed = True
    return changed


def repair_families() -> int:
    """Enforce "exactly one present member per family" — the number of
    families that needed a repair.

    None present: the expected member (provider
    :data:`EXPECTED_PRESENT_PROVIDER`, else the leader) stands at its own
    stored placement, else at the most recent stored placement of any member;
    with none stored the family is left alone (a location is never invented).
    Two or more present: every present member except the expected one (else
    the leader, else the first) becomes dormant. A user still controlling a
    dormant member is switched to the present one. Runs at boot and on every
    periodic tick.
    """
    repaired = 0
    for leader in sorted(_load_map()["lead"]):
        try:
            if _repair_family(leader):
                repaired += 1
        except Exception as e:  # noqa: BLE001 — one broken family must not stop the rest
            logger.error("Linked family repair of %s failed: %s", leader, e, exc_info=True)
    return repaired


# ---------------------------------------------------------------------------
# Link / unlink / create
# ---------------------------------------------------------------------------

def _fail(error: str) -> Dict[str, Any]:
    return {"ok": False, "error": error}


def _exists(name: str) -> bool:
    from app.models.character import character_exists
    return bool(name) and character_exists(name)


def _clean_shared(shared: Any) -> Tuple[List[str], str]:
    """``(sections, error)`` — the list in the canonical order, or an error."""
    if shared is None:
        return list(DEFAULT_SHARED_SOUL), ""
    if isinstance(shared, str) or not isinstance(shared, (list, tuple)):
        return [], "Shared soul sections must be a list."
    wanted = [str(s).strip() for s in shared if str(s).strip()]
    for sec in wanted:
        if sec not in SHAREABLE_SOUL_SECTIONS:
            return [], f"This soul section cannot be shared: {sec}."
    return [s for s in SHAREABLE_SOUL_SECTIONS if s in wanted], ""


def avatar_owner(name: str) -> str:
    """The username of a user whose ACTIVE character is ``name`` ("" if none).

    Background-safe (reads the users table, no request context). Linking such
    a character would leave that player controlling a dormant body.
    """
    from app.core.users import list_users
    for user in list_users():
        settings = user.get("settings") or {}
        active = str(settings.get("active_character")
                     or settings.get("current_character") or "").strip()
        if active and active == name:
            return str(user.get("username") or user.get("id") or "")
    return ""


def _grant_like_leader(body: str, leader: str) -> None:
    """Add ``body`` to ``allowed_characters`` of every user allowed ``leader``."""
    from app.core.users import list_users, update_user
    for user in list_users():
        allowed = list(user.get("allowed_characters") or [])
        if leader in allowed and body not in allowed:
            allowed.append(body)
            try:
                update_user(user["id"], allowed_characters=allowed)
            except Exception as e:  # noqa: BLE001
                logger.warning("link: allowed_characters of %s not updated: %s",
                               user.get("username"), e)


def link(body: str, leader: str, *, shared: Any = DEFAULT_SHARED_SOUL) -> Dict[str, Any]:
    """Link ``body`` to ``leader`` — ``{"ok", "error"}``.

    Refused: a self-link, an unknown character, a temporary NPC, a leader that
    is itself linked (no chains), a body that leads bodies of its own, a body
    already linked to another leader, a section outside
    ``SHAREABLE_SOUL_SECTIONS``, a body that is some user's active character
    (:func:`avatar_owner`) and a present body in a refusal state
    (:func:`swap_refusal`). A body already linked to the same leader only gets
    its shared sections updated. A newly linked body becomes DORMANT
    (:func:`make_dormant`); its own former mind rows stay untouched in storage.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (DORMANT_STATUS, get_character_profile,
                                      get_character_status, is_temporary_npc,
                                      save_character_profile)
    body = (body or "").strip()
    leader = (leader or "").strip()
    if body and body == leader:
        return _fail("A character cannot be linked to itself.")
    for who in (body, leader):
        if not _exists(who):
            return _fail(f"Unknown character: {who or '(none)'}.")
    if is_temporary_npc(body) or is_temporary_npc(leader):
        return _fail("Temporary NPCs cannot be linked.")
    sections, err = _clean_shared(shared)
    if err:
        return _fail(err)
    its_leader = leader_of(leader)
    if its_leader:
        return _fail(f"{leader} is itself linked to {its_leader} — "
                     f"link to {its_leader} instead.")
    if bodies_of(body):
        return _fail(f"{body} leads linked characters and cannot be linked "
                     "to another one.")
    current = leader_of(body)
    if current and current != leader:
        return _fail(f"{body} is already linked to {current} — unlink it first.")
    newly = current is None
    if newly:
        player = avatar_owner(body)
        if player:
            return _fail(AVATAR_REFUSAL_TEXT.format(user=player, name=body))
    if newly and get_character_status(body) != DORMANT_STATUS:
        code = swap_refusal(body)
        if code:
            return _fail(f"Cannot link {body} right now: {SWAP_REFUSAL_TEXT[code]}")
    with keyed_lock("character_profile", body):
        profile = get_character_profile(body) or {}
        profile[PROFILE_KEY] = leader
        profile[SHARED_KEY] = sections
        stored = save_character_profile(body, profile)
    invalidate()
    if not stored:
        return _fail(f"{body} could not be saved.")
    if newly:
        make_dormant(body)
        _grant_like_leader(body, leader)
        logger.info("Linked %s to %s (shared: %s)", body, leader, ", ".join(sections) or "-")
    return {"ok": True, "error": ""}


def unlink(body: str) -> Dict[str, Any]:
    """Unlink a DORMANT body — ``{"ok", "error"}``.

    The body gets status ``''`` and stands at its leader's current location
    and room (arrival room when the leader has none). A PRESENT body is
    refused ("revert first"): its leader is the dormant one. The locked fields
    it showed (the leader's gender/age, read while still linked) become its
    own stored values — an unlinked character needs its own.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (DORMANT_STATUS, get_character_current_location,
                                      get_character_current_room, get_character_profile,
                                      get_character_status, save_character_profile,
                                      set_character_status)
    body = (body or "").strip()
    leader = leader_of(body)
    if not leader:
        return _fail(f"{body or '(none)'} is not linked.")
    if get_character_status(body) != DORMANT_STATUS:
        return _fail(f"{body} stands in the world right now — revert first.")
    with keyed_lock("character_profile", body):
        profile = get_character_profile(body) or {}
        profile.pop(PROFILE_KEY, None)
        profile.pop(SHARED_KEY, None)
        stored = save_character_profile(body, profile)
    invalidate()
    if not stored:
        return _fail(f"{body} could not be saved.")
    set_character_status(body, "")
    place_at(body, get_character_current_location(leader) or "",
             get_character_current_room(leader) or "")
    logger.info("Unlinked %s from %s", body, leader)
    return {"ok": True, "error": ""}


def create_linked(leader: str, name: str) -> Dict[str, Any]:
    """Create a new body ``name`` for ``leader`` — ``{"ok", "error", "name"}``.

    Built from the leader's TEMPLATE only (nothing else is copied), with
    ``linked_to`` and the default shared sections, created DORMANT (it never
    stood anywhere — the swap places it), with the default skills and an
    empty ``known_locations``; every user allowed the leader is allowed it.
    """
    from app.core.character_name import (CharacterNameError, localized_message,
                                         validate_character_name)
    from app.models.character import (get_character_config, get_character_profile,
                                      is_temporary_npc, list_available_characters,
                                      save_character_config, save_character_profile)
    leader = (leader or "").strip()
    if not _exists(leader):
        return _fail(f"Unknown character: {leader or '(none)'}.")
    if is_temporary_npc(leader):
        return _fail("Temporary NPCs cannot be linked.")
    its_leader = leader_of(leader)
    if its_leader:
        return _fail(f"{leader} is itself linked to {its_leader} — "
                     f"link to {its_leader} instead.")
    try:
        name = validate_character_name(name or "")
    except CharacterNameError as err:
        return _fail(localized_message(err, "en"))
    lowered = name.lower()
    if any(lowered == c.lower() for c in list_available_characters(include_pooled=True)):
        return _fail(f"A character named \"{name}\" already exists.")
    template = str((get_character_profile(leader) or {}).get("template") or "")
    if not save_character_profile(name, {
            "character_name": name, "template": template,
            PROFILE_KEY: leader, SHARED_KEY: list(DEFAULT_SHARED_SOUL)},
            create_new=True):
        return _fail(f"{name} could not be saved.")
    invalidate()
    try:
        cfg = get_character_config(name) or {}
        if "known_locations" not in cfg:
            cfg["known_locations"] = []
            save_character_config(name, cfg)
    except Exception as e:  # noqa: BLE001
        logger.warning("create_linked: known_locations init for %s failed: %s", name, e)
    from app.core.character_ops import seed_default_skills
    seed_default_skills(name)
    make_dormant(name)
    _grant_like_leader(name, leader)
    logger.info("Created linked character %s for %s", name, leader)
    return {"ok": True, "error": "", "name": name}


def describe(name: str) -> Dict[str, Any]:
    """The link state for the editor: ``{leader, bodies, shared_soul_sections,
    status, shareable, candidates}``.

    ``bodies`` = ``[{name, status}]`` of a leader; ``status`` is ``dormant`` or
    ``present``; ``candidates`` = the characters ``name`` may be linked to (none
    for a leader or a temporary NPC).
    """
    from app.models.character import (DORMANT_STATUS, get_character_status,
                                      is_temporary_npc, list_available_characters)

    def _st(who: str) -> str:
        return "dormant" if get_character_status(who) == DORMANT_STATUS else "present"

    leader = leader_of(name)
    bodies = bodies_of(name)
    candidates: List[str] = []
    if not bodies and not is_temporary_npc(name):
        candidates = [c for c in list_available_characters(include_dormant=True)
                      if c != name and not is_linked(c) and not is_temporary_npc(c)]
    return {
        "leader": leader or "",
        "bodies": [{"name": b, "status": _st(b)} for b in bodies],
        "shared_soul_sections": list(shared_soul_sections(name)) if leader else [],
        "status": _st(name),
        "shareable": list(SHAREABLE_SOUL_SECTIONS),
        "candidates": candidates,
    }
