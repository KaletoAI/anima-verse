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
