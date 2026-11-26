"""World Dev free mode — undo engine for the run journal.

Replays the inverses recorded in ``world_dev_journal`` (``world_dev_runs``)
newest-first. Plan: docs/superpowers/plans/2026-11-22-world-dev-free-mode.md,
Task 3; spec docs/superpowers/specs/2026-11-22-world-dev-free-mode-design.md
("Exactness check").

EXACTNESS. ``before`` and ``written`` of a journal entry are values READ FROM
STORAGE (before: prior to the write, written: re-read after it). Before an
update is reversed, the current stored value of every key is compared with
what the agent wrote, inside the same lock span as the restoring write:

* equal keys are restored,
* differing keys are skipped with reason ``changed since`` — a newer edit by
  someone else is never clobbered.

Creations are removed when they still exist (``already gone`` otherwise, not
an error — and not an incomplete rollback: the report's ``complete`` is True
when every skip is ``already gone``, the plan's rule for
``rollback_incomplete``). A pending WRITE row without an inverse is reported as skipped
(``may have written, no inverse — see backup``) so such a rollback never ends
as a clean ``rolled_back``. Every handled entry is marked undone, so a second
``undo`` finds nothing.

A PENDING entry WITH an inverse but without ``written`` (the process ended
between the write and ``complete``) has nothing to compare against; its
inverse is applied unconditionally — the write was the run's own and never
reported back. One exception: such a ``delete_character`` (a crashed
``create_character``) acts only on a DURABLE CLAIM. The tool stores
``claimed: true`` in the inverse under the profile lock, after the absence
check and right before the profile save (and every new catalog piece id the
moment ``add_item`` returns it). With the claim a row under that name is this
create's (nobody else could store it while the lock was held) and is deleted
with its pieces; without one nothing was written — skipped as ``not
written``, which counts as complete, and a row under that name is a foreign
one that is never touched.

A cross-turn ``delete_created`` journals a write whose inverse RE-CREATES
the element from a snapshot taken under the writer's lock right before the
delete (``recreate_*``): a location through ``upsert_location``, an area
through its saver, a character by storing every row ``delete_character``
swept (same rowids) and its directory again. The re-created element is read
back and compared with the snapshot (``re-created, but differs from the
snapshot`` otherwise). A done re-creation that finds an element under the
same key skips it (``changed since`` — it is somebody else's), and every
older entry of that target is skipped as well, so the creating step never
deletes the foreign element.

Known residual of the durable claim (accepted, no code for it): when the
process dies between the persisted claim and the profile save (no row was
stored) and an admin then creates a character of that name by hand before
the Discard, ``_undo_delete_character`` sees pending + claimed + a row and
deletes the admin's character. The window is a few statements under the
profile lock, and the run's backup holds the pre-run state. A later fix
would put a creation marker (run id) on the profile and compare it before
deleting on a pending claim.

A character left standing in a place the undo deleted, or in a room a
``restore_location`` took away, stays there (nothing moves it). The undo
reports it as an INFORMATIONAL record (reason :data:`REASON_OCCUPANT`, key
``occupant``) that does not make the rollback incomplete;
:func:`discard_preview` names the same characters before the discard. A
character the same undo deletes (one the run created) is left out of both:
there is nobody left to place anew.

Inverse ops (``inverse["op"]``):
  delete_location{id} · restore_location{id, before:{key: value}} ·
  restore_position{id, before:{x, z, yaw}} · delete_terrain_area{id} ·
  restore_terrain_area{row} · delete_height_area{id} · restore_height_area{row}
  · delete_character{name, items:[ids]} · restore_character{name,
  profile:{k: before}, config:{k: before}} · restore_soul{name, file_id,
  before_text} (file_id = path relative to the character directory, as
  ``soul_writer.read_text/write_text`` take it) · restore_home_schedule{name,
  before:{home_location, home_room, daily_schedule, known_locations}} ·
  restore_body_slots{name, before:{slot: {attribute: value}}, had_key,
  slots_present} · restore_status_effects{name, before:{stat: value},
  had_key} · remove_known_places{name, ids:[place ids the call added],
  had_key} · remove_outfits{name, outfits:[ids], inventory:[item ids],
  items:[created piece ids]} (pending: {names, outfits_before,
  inventory_before, refs, items}) · recreate_location{row} · recreate_terrain_area{row, order} ·
  recreate_height_area{row, order} (row = the reader's full record, order = the
  area's paint-order identity {created_at, updated_at, rowid}) ·
  delete_world_prop{id} · recreate_world_prop{row} (row = :func:`world_prop_row`) ·
  delete_terrain_type{kind} · recreate_terrain_type{row} (row = :func:`terrain_type_row`;
  the delete skips a kind still in use — :func:`terrain_kind_users` — as ``changed
  since`` with keys ["in use"]) ·
  recreate_character{name, snapshot:{rows, files, dirs, has_dir,
  file_bytes}} (:func:`character_snapshot`) ·
  delete_items{ids} (create_item; :func:`_cleanup_items` — an item held anywhere
  stays, ``item still in use``) · restore_inventory{name, before:{item id:
  quantity or ABSENT}} (give_items; written = {item id: re-read entry}) ·
  restore_room_items{location_id, room_id, before: the room's whole ``items``
  list or ABSENT} (add_room_item; written = the room's items value after,
  :func:`room_items_value`) · restore_address{speaker (the mind), addressee,
  pair (``relationship.pair_key``), key (``relationship.address_key``), before
  (the key's value or ABSENT), text (what the step sent; "" clears),
  row_created, row_id (the row that existed, else the created one once
  attached), raw (``relationship.raw_pair_row`` of a row that existed,
  else None)} (set_address; written =
  {"value": the key's value or ABSENT, "row": ``relationship.pair_row``}) ·
  delete_secret{owner (the mind), id} (add_secret; written = the re-read
  secret, ``secrets.get_secret``) · delete_rule{id} (add_block_rule; written =
  the world-layer row as stored, ``rules.world_rule``) · delete_event{id}
  (add_event; written = the re-read event, ``events.get_event``) ·
  delete_quest_template{id} (create_quest_template; written = the re-read
  template, ``quests.get_template``; the delete skips a template whose
  revision moved on — keys ["revision"] — or that has a run — keys ["runs"])
  · restore_placement{name, before (``character.read_placement``: {profile:
  {the five PLACEMENT_KEYS: value or ABSENT}, pos: {x, z, yaw, session, seq}
  or None}), known_added (place ids the step added to the known places;
  pending: the one it was about to add), had_known_key} (place_character;
  written = {"placement": read_placement after the write, "known": the ids
  added}; the placement is one unit — any key differing is ``changed since``
  with those keys and nothing of it is written; the added known place stays,
  key "known_places" in the same skip, while the character still stands in
  the placed location) · restore_skill_config{name, skill, before (the RAW
  text of ``skills/<skill>.json`` or ABSENT), had_dir (the ``skills/``
  directory existed before the step)} (set_skill; written = the raw text
  after the write; a differing text is ``changed since`` with keys [skill],
  else ``before`` is written back verbatim or the file removed) ·
  remove_hairstyle{name, item_id (None until the lane's hairstyle is minted),
  before:{base_hairstyle, equipped_mesh_pieces: value or ABSENT}} (the media
  lane's hairstyle, ``world_dev_media.make_hairstyle``, tool ``media:hairstyle``;
  written = {"item": :func:`item_row`, "keys": the two keys re-read}; keys
  changed since are left alone, the item stays while such a key still names
  it — :func:`_undo_remove_hairstyle`)

Written shapes: restore_location / restore_home_schedule — the written map of
:func:`diff_keys`; restore_position — ``{x, z, yaw}`` (:func:`position_of`);
restore_*_area — the full re-read row; restore_character —
``{"profile": {...}, "config": {...}}``; restore_body_slots —
``{"slots": {slot: {attribute: value}}}`` (:func:`body_slot_diff`);
restore_status_effects — ``{"stats": {stat: value}}`` (the patched stats as
re-read after the write); remove_known_places — ``{"known": [ids]}`` (the
places the call added, as read back);
remove_outfits — ``{"outfits": {id: row}, "inventory": {item id: entry}}``; restore_soul — the stored text as a
plain string (or None when the write removed the file). A key that did not exist is recorded as :data:`ABSENT` (restoring it
removes the key again).

A step that RAISES is reported as ``undo failed: ...`` and still marked
undone (it is not retried by a second ``undo``) — except a delete_secret /
delete_rule / delete_event step: its row still stands, so it stays in the
journal (later previews list it, the next undo retries it) and the
delete_location / delete_character of what its written row names is skipped
in that pass (``still named by a step whose undo failed``, see
``_HOLDING_OPS``). Read errors propagate into that path; they are never read
as "absent".

Never call this inside an open ``db.transaction()`` — the journal helpers
open their own connections.
"""
import copy
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import world_dev_runs as wr
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger

logger = get_logger("world_dev_undo")

#: Marker for "this key did not exist" in before/written maps.
ABSENT: Dict[str, bool] = {"$absent": True}

REASON_CHANGED = "changed since"
REASON_GONE = "already gone"
REASON_REFUSED = "delete refused"
REASON_NO_INVERSE = "may have written, no inverse — see backup"
REASON_ITEM_IN_USE = "item still in use"
#: A pending create_character that never claimed its name: the claim is stored
#: in the journal before the profile save, so nothing of it was written.
#: Counts as complete, like "already gone".
REASON_NOT_WRITTEN = "not written"
#: A re-created element that does not read back as its snapshot.
REASON_INEXACT = "re-created, but differs from the snapshot"
#: A re-creation the writer refused (key ``error``: its message) — e.g. the
#: library prop of a world prop was deleted in between, or the world is at
#: its world-prop cap. The element stays absent; the undo is incomplete —
#: unless an older creating entry of the same target is handled in the same
#: pass: the target was the run's own and absent is its end state, so the
#: record gets the key ``net_absent`` and counts as complete.
REASON_RECREATE_REFUSED = "re-creation refused"
#: Reason (behind the character's quoted name) of the INFORMATIONAL record of
#: a character left standing in a place (or room) the undo removed. It carries
#: the key ``occupant`` and never makes a rollback incomplete: nothing was
#: skipped, the character only has to be placed anew (nobody is moved
#: automatically, see ``delete_location``).
REASON_OCCUPANT = "stands in the removed place — place them anew"

HOME_SCHEDULE_KEYS = ("home_location", "home_room", "daily_schedule",
                      "known_locations")


class _Skip(Exception):
    """One skip of an entry (or of a part of it)."""

    def __init__(self, reason: str, **extra: Any):
        super().__init__(reason)
        self.reason = reason
        self.extra = extra


# ── Helpers shared with the write tools ─────────────────────────────────

def _norm(value: Any) -> Any:
    """The JSON round-trip of a value — what the journal gives back."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def is_absent(value: Any) -> bool:
    return isinstance(value, dict) and value == ABSENT


def absent_as_none(values: Dict[str, Any]) -> Dict[str, Any]:
    """A key map with ABSENT shown as None — the shape a sync push compares."""
    return {k: (None if is_absent(v) else v) for k, v in values.items()}


def diff_keys(before: Optional[Dict[str, Any]],
              after: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Top-level keys whose stored value differs between two storage reads:
    ``(before_map, written_map)``; a missing key is :data:`ABSENT`."""
    before = _norm(before or {})
    after = _norm(after or {})
    b_map: Dict[str, Any] = {}
    w_map: Dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        bv = before[key] if key in before else ABSENT
        av = after[key] if key in after else ABSENT
        if bv != av:
            b_map[key] = bv
            w_map[key] = av
    return b_map, w_map


def position_of(location: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``{x, z, yaw}`` of a stored location record (x/z None = not placed).
    The stored rotation is a column that reads back 0.0 when unset, so an
    absent yaw IS 0.0 here — never None."""
    loc = location or {}

    def num(key: str) -> Optional[float]:
        val = loc.get(key)
        return None if val is None else float(val)
    return {"x": num("pos_x"), "z": num("pos_z"),
            "yaw": float(loc.get("yaw_deg") or 0.0)}


def home_schedule_state(name: str) -> Dict[str, Any]:
    """Home, daily schedule and known places of a character as stored —
    the before/written shape of ``restore_home_schedule``. A character
    without a schedule row reads as ``get_character_daily_schedule`` answers
    (``{"enabled": False, "slots": []}``); ``known_locations`` is None when
    the config has no such key (that is not the same as an empty list);
    ``home_location`` / ``home_room`` are :data:`ABSENT` when the config has
    no such key."""
    from app.models.character import (get_character_config,
                                      get_character_daily_schedule)
    cfg = get_character_config(name) or {}
    sched = get_character_daily_schedule(name) or {}
    known = cfg.get("known_locations")

    def home_key(key: str) -> Any:
        # A missing key is ABSENT (restoring it removes the key again), not
        # the empty string: the two are different stored states.
        return str(cfg.get(key) or "") if key in cfg else ABSENT
    return _norm({
        "home_location": home_key("home_location"),
        "home_room": home_key("home_room"),
        "daily_schedule": {"enabled": bool(sched.get("enabled")),
                           "slots": list(sched.get("slots") or [])},
        "known_locations": list(known) if isinstance(known, list) else None,
    })


def body_slot_state(values: Dict[str, Any],
                    keys: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The stored values of the body-slot attributes named by ``keys``
    (``{slot: {attribute: ...}}``) in a profile's ``body_slots`` map —
    the before/written shape of ``restore_body_slots``; an unset attribute
    is :data:`ABSENT`."""
    out: Dict[str, Dict[str, Any]] = {}
    for slot, attrs in (keys or {}).items():
        cur = values.get(slot) if isinstance(values, dict) else None
        cur = cur if isinstance(cur, dict) else {}
        out[slot] = {a: (copy.deepcopy(cur[a]) if a in cur else ABSENT)
                     for a in attrs}
    return _norm(out)


def body_slot_diff(before: Dict[str, Dict[str, Any]],
                   after: Dict[str, Dict[str, Any]]
                   ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """The attributes whose value differs between two :func:`body_slot_state`
    reads: ``(before_map, written_map)``, slots without a change left out."""
    b_map: Dict[str, Dict[str, Any]] = {}
    w_map: Dict[str, Dict[str, Any]] = {}
    for slot in sorted(set(before or {}) | set(after or {})):
        b_slot = (before or {}).get(slot) or {}
        a_slot = (after or {}).get(slot) or {}
        for attr in sorted(set(b_slot) | set(a_slot)):
            bv = b_slot.get(attr, ABSENT)
            av = a_slot.get(attr, ABSENT)
            if _norm(bv) != _norm(av):
                b_map.setdefault(slot, {})[attr] = bv
                w_map.setdefault(slot, {})[attr] = av
    return b_map, w_map


def outfit_rows(name: str) -> Dict[str, Dict[str, Any]]:
    """The stored outfit sets of a character by id (the written shape of
    ``remove_outfits``)."""
    from app.models.character import get_character_outfits
    return _norm({str(o.get("id")): o for o in get_character_outfits(name)
                  if o.get("id")})


def inventory_entries(name: str) -> Dict[str, Dict[str, Any]]:
    """The stored inventory entries of a character by item id. A read error
    raises (never "holds nothing")."""
    from app.models.inventory import _load_inventory
    data = _load_inventory(name, strict=True)
    return _norm({str(e.get("item_id")): e for e in data.get("inventory") or []
                  if e.get("item_id")})


def _split_keys(before: Dict[str, Any], written: Any,
                current: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Which keys of ``before`` may be restored (current == written) and
    which changed since. ``written`` None (pending entry) restores all."""
    restore: Dict[str, Any] = {}
    changed: List[str] = []
    cur = _norm(current)
    for key, bval in (before or {}).items():
        if isinstance(written, dict) and key in written:
            now = cur[key] if key in cur else ABSENT
            if now != _norm(written[key]):
                changed.append(key)
                continue
        restore[key] = bval
    return restore, changed


def _apply_keys(record: Dict[str, Any], restore: Dict[str, Any]) -> None:
    for key, value in restore.items():
        if is_absent(value):
            record.pop(key, None)
        else:
            record[key] = copy.deepcopy(value)


# ── Locations ────────────────────────────────────────────────────────────

def standing_in(loc_id: str, rooms: Optional[set] = None) -> List[Tuple[str, str]]:
    """``(name, room)`` of every character standing in the place (in one of
    ``rooms`` only, when given), sorted by name."""
    from app.models.character import list_character_places
    return sorted((name, str(room or ""))
                  for name, (lid, room) in list_character_places().items()
                  if lid == loc_id and (rooms is None or room in rooms))


def _occupant_notes(loc_id: str, occupants: List[Tuple[str, str]]) -> List["_Skip"]:
    # The name leads the reason: every reader of the skip list (the panel,
    # the run note) shows reason and line, not the extra keys.
    return [_Skip(f'"{name}" {REASON_OCCUPANT}', occupant=name, location=loc_id,
                  **({"room": room} if room else {}))
            for name, room in occupants]


def _undo_delete_location(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.world import (delete_location, get_location_by_id,
                                  world_write_lock)
    lid = str(inv.get("id") or "")
    with world_write_lock:  # re-entrant; delete_location takes it again
        if not lid or get_location_by_id(lid) is None:
            raise _Skip(REASON_GONE)
        occupants = standing_in(lid)
        if not delete_location(lid) and get_location_by_id(lid) is not None:
            raise _Skip(REASON_REFUSED)
    return _occupant_notes(lid, occupants)


def _undo_restore_location(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Put the journalled keys of a location back (keys changed since by
    someone else are skipped). The restore is READER-equal, not raw-row
    equal: a place last written outside the tool writers (e.g. the create
    editor path) is canonicalised by the first tool write (image_prompt_night
    "" on every room, yaw_deg 0.0), and the undo keeps that canonical form —
    get_location_by_id reads the same before and after."""
    from app.models.world import (get_location_by_id, upsert_location,
                                  world_write_lock)
    lid = str(inv.get("id") or "")
    with world_write_lock:
        cur = get_location_by_id(lid) if lid else None
        if cur is None:
            raise _Skip(REASON_GONE)
        cur = copy.deepcopy(cur)
        rooms_before = {str(r.get("id") or "") for r in cur.get("rooms") or []
                        if isinstance(r, dict)}
        restore, changed = _split_keys(inv.get("before") or {},
                                       entry.get("written"), cur)
        occupants: List[Tuple[str, str]] = []
        if restore:
            _apply_keys(cur, restore)
            if not upsert_location(cur, sync_world=True):
                raise RuntimeError(f"restoring location {lid} was not stored")
            # The seat inventory caches the room layouts (as every layout
            # writer does, the restore drops it): a removed piece must not
            # stay offered as a seat until the cache TTL runs out.
            from app.core import places
            places.invalidate()
            # The rooms the restore took away, read back from storage (the
            # writer's corridor sync has a say too). Whoever stands in one
            # stays there and is reported: the forward tool refuses this
            # case, the undo cannot.
            after = get_location_by_id(lid) or {}
            gone = rooms_before - {str(r.get("id") or "")
                                   for r in after.get("rooms") or []
                                   if isinstance(r, dict)}
            if gone:
                occupants = standing_in(lid, gone)
    notes = _occupant_notes(lid, occupants)
    if changed:
        notes.insert(0, _Skip(REASON_CHANGED, keys=changed))
    return notes


def _undo_restore_position(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """The position is ONE unit (x, z and yaw move together): any of them
    changed since -> the whole entry is skipped. Restored through
    ``update_location_position`` so the occupants ride back with the place.
    An absent yaw is 0.0 (see :func:`position_of`) — there is no "no yaw"
    state to restore, and never an unplace + re-place (that would drop every
    occupant on the centre)."""
    from app.models.world import (get_location_by_id, update_location_position,
                                  world_write_lock)
    lid = str(inv.get("id") or "")
    before = inv.get("before") or {}
    written = entry.get("written")
    with world_write_lock:
        cur = get_location_by_id(lid) if lid else None
        if cur is None:
            raise _Skip(REASON_GONE)
        if isinstance(written, dict) and position_of(cur) != _norm(
                {"x": written.get("x"), "z": written.get("z"),
                 "yaw": float(written.get("yaw") or 0.0)}):
            raise _Skip(REASON_CHANGED, keys=["position"])
        bx, bz = before.get("x"), before.get("z")
        if bx is None or bz is None:
            update_location_position(lid, None, None)
        else:
            update_location_position(lid, bx, bz,
                                     float(before.get("yaw") or 0.0))
    return []


# ── Terrain and height areas ─────────────────────────────────────────────

def _undo_delete_terrain_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.terrain import delete_area, get_area
    aid = str(inv.get("id") or "")
    if not aid or get_area(aid) is None:
        raise _Skip(REASON_GONE)
    if not delete_area(aid) and get_area(aid) is not None:
        raise _Skip(REASON_REFUSED)
    return []


# Terrain and height restores compare the stored row with ``written`` and then
# save with must_exist=True. The terrain/height writers have no writer lock to
# share (only their generation counters are locked), so compare and save are
# not one atomic span; in a frozen world the window is negligible.

def _undo_restore_terrain_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.core.bulk_edit import GoneError
    from app.models.terrain import get_area, save_area
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    cur = get_area(aid) if aid else None
    if cur is None:
        raise _Skip(REASON_GONE)
    written = entry.get("written")
    if written is not None and _norm(cur) != _norm(written):
        raise _Skip(REASON_CHANGED)
    try:
        save_area(copy.deepcopy(row), must_exist=True)
    except GoneError:
        raise _Skip(REASON_GONE)
    return []


def _height_area(area_id: str) -> Optional[Dict[str, Any]]:
    from app.models.heightfield import list_height_areas
    return next((a for a in list_height_areas() if a.get("id") == area_id), None)


def _undo_delete_height_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.heightfield import delete_height_area
    aid = str(inv.get("id") or "")
    if not aid or _height_area(aid) is None:
        raise _Skip(REASON_GONE)
    if not delete_height_area(aid) and _height_area(aid) is not None:
        raise _Skip(REASON_REFUSED)
    return []


def _undo_restore_height_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.core.bulk_edit import GoneError
    from app.models.heightfield import save_height_area
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    cur = _height_area(aid) if aid else None
    if cur is None:
        raise _Skip(REASON_GONE)
    written = entry.get("written")
    if written is not None and _norm(cur) != _norm(written):
        raise _Skip(REASON_CHANGED)
    try:
        save_height_area(copy.deepcopy(row), must_exist=True)
    except GoneError:
        raise _Skip(REASON_GONE)
    return []


# ── Characters ───────────────────────────────────────────────────────────

def _knowledge_holders(iid: str, locations: Optional[List[Dict[str, Any]]] = None
                       ) -> List[Dict[str, Any]]:
    """The places whose ``knowledge_item_id`` names the item (the stored
    ones, or ``locations`` when the discard preview passes its simulation)."""
    if locations is None:
        from app.models.world import list_locations
        locations = list_locations() or []
    return [loc for loc in locations
            if isinstance(loc, dict) and str(loc.get("knowledge_item_id") or "") == iid]


def _cleanup_items(item_ids: List[str]) -> List["_Skip"]:
    """Delete the catalog items a created character brought — only when the
    item exists, is not shared and is held nowhere (inventory, room, or a
    place's knowledge_item_id)."""
    from app.models.inventory import (delete_item, find_item_location,
                                      get_item, is_shared_item)
    skips: List[_Skip] = []
    for iid in item_ids or []:
        iid = str(iid or "")
        if not iid or get_item(iid) is None:
            continue
        if (is_shared_item(iid) or find_item_location(iid) is not None
                or _knowledge_holders(iid)):
            # A place naming it as its knowledge item holds it too: deleting
            # it would leave that place naming a missing id.
            skips.append(_Skip(REASON_ITEM_IN_USE, item=iid))
            continue
        if not delete_item(iid) and get_item(iid) is not None:
            skips.append(_Skip(REASON_REFUSED, item=iid))
    return skips


def _undo_delete_character(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    # No profile lock held around delete_character: it detaches party and
    # interaction first and takes the profile lock itself, in its own order.
    from app.models.character import character_row_exists, delete_character
    name = str(inv.get("name") or "")
    if (entry.get("state") == "pending" and entry.get("written") is None
            and not inv.get("claimed")):
        # The process ended inside the create before the name was claimed.
        # The claim is stored in the journal BEFORE the profile save (under
        # the profile lock that also covered the absence check), so nothing
        # of this create was written; a row under that name is a foreign one
        # and is never touched.
        raise _Skip(REASON_NOT_WRITTEN)
    if not name or not character_row_exists(name):
        return [_Skip(REASON_GONE)] + _cleanup_items(inv.get("items") or [])
    # Done, or pending WITH a claim: the profile lock was held from the
    # absence check to the save, so a row with that name is this create's.
    if not delete_character(name) and character_row_exists(name):
        raise _Skip(REASON_REFUSED)
    return _cleanup_items(inv.get("items") or [])


def _undo_restore_character(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.character import (character_row_exists,
                                      get_character_config,
                                      get_character_profile,
                                      save_character_config,
                                      save_character_profile)
    name = str(inv.get("name") or "")
    written = entry.get("written")
    w_prof = written.get("profile") if isinstance(written, dict) else None
    w_cfg = written.get("config") if isinstance(written, dict) else None
    changed: List[str] = []
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        if inv.get("profile"):
            prof = copy.deepcopy(get_character_profile(name) or {})
            restore, ch = _split_keys(inv["profile"], w_prof, prof)
            changed += [f"profile.{k}" for k in ch]
            if restore:
                was = {k: (copy.deepcopy(prof[k]) if k in prof else ABSENT)
                       for k in restore}
                _apply_keys(prof, restore)
                if not save_character_profile(name, prof):
                    raise RuntimeError(f"profile of {name} was not stored")
                # Inside the profile lock, right after the save (D12): a
                # later config failure or the changed-since skip cannot drop
                # it. Only the restored profile keys; never config (D9).
                # A value that differs only as absent vs None is no change
                # for the push: skip it instead of a bare avatars signal.
                was_n, restore_n = absent_as_none(was), absent_as_none(restore)
                if was_n != restore_n:
                    from app.core import sync_topics
                    sync_topics.profile_patched(name, was_n, restore_n)
        if inv.get("config"):
            cfg = copy.deepcopy(get_character_config(name) or {})
            restore, ch = _split_keys(inv["config"], w_cfg, cfg)
            changed += [f"config.{k}" for k in ch]
            if restore:
                _apply_keys(cfg, restore)
                if not save_character_config(name, cfg):
                    raise RuntimeError(f"config of {name} was not stored")
    if changed:
        raise _Skip(REASON_CHANGED, keys=changed)
    return []


def _undo_restore_body_slots(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Per attribute: restored when it still holds what the agent wrote
    (a pending entry restores all), ``changed since`` otherwise. A slot
    that did not exist before and is empty again goes; the profile's
    ``body_slots`` key goes when it did not exist before and is empty."""
    from app.models.character import (character_row_exists, get_character_profile,
                                      save_character_profile)
    name = str(inv.get("name") or "")
    before = inv.get("before") or {}
    written = entry.get("written")
    w_slots = written.get("slots") if isinstance(written, dict) else None
    present = set(inv.get("slots_present") or [])
    changed: List[str] = []
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        if not before:
            return []
        prof = copy.deepcopy(get_character_profile(name) or {})
        vals = prof.get("body_slots") if isinstance(prof.get("body_slots"), dict) else {}
        vals = copy.deepcopy(vals)
        touched = False
        for slot, attrs in before.items():
            cur = dict(vals.get(slot) or {}) if isinstance(vals.get(slot), dict) else {}
            for attr, bval in (attrs or {}).items():
                if isinstance(w_slots, dict) and attr in (w_slots.get(slot) or {}):
                    now = cur[attr] if attr in cur else ABSENT
                    if _norm(now) != _norm(w_slots[slot][attr]):
                        changed.append(f"body_slots.{slot}.{attr}")
                        continue
                if is_absent(bval):
                    cur.pop(attr, None)
                else:
                    cur[attr] = copy.deepcopy(bval)
                touched = True
            if cur or slot in present:
                vals[slot] = cur
            else:
                vals.pop(slot, None)
        if touched:
            if vals or inv.get("had_key"):
                prof["body_slots"] = vals
            else:
                prof.pop("body_slots", None)
            if not save_character_profile(name, prof):
                raise RuntimeError(f"profile of {name} was not stored")
    if changed:
        raise _Skip(REASON_CHANGED, keys=changed)
    return []


def _undo_restore_status_effects(entry: Dict[str, Any],
                                 inv: Dict[str, Any]) -> List["_Skip"]:
    """Per stat of ``before``: restored when it still holds what the agent
    wrote (a pending entry restores every stat of its before map — never any
    other stat), ``changed since`` (key ``status_effects.<stat>``)
    otherwise. Restoring ABSENT removes the stat; the profile's
    ``status_effects`` key goes only when it did not exist before
    (``had_key`` False) and is empty again."""
    from app.core.world_dev_tools import _template_fields
    from app.models.character import (character_row_exists, get_character_profile,
                                      remove_state_meta_key, save_character_profile)
    name = str(inv.get("name") or "")
    before = inv.get("before") or {}
    written = entry.get("written")
    w_stats = written.get("stats") if isinstance(written, dict) else None
    changed: List[str] = []
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        if not before:
            return []
        prof = copy.deepcopy(get_character_profile(name) or {})
        vals = prof.get("status_effects")
        vals = copy.deepcopy(vals) if isinstance(vals, dict) else {}
        touched = False
        for stat, bval in before.items():
            if isinstance(w_stats, dict) and stat in w_stats:
                now = vals[stat] if stat in vals else ABSENT
                if _norm(now) != _norm(w_stats[stat]):
                    changed.append(f"status_effects.{stat}")
                    continue
            if is_absent(bval):
                vals.pop(stat, None)
            else:
                vals[stat] = copy.deepcopy(bval)
            touched = True
        if touched:
            drop_key = not vals and not inv.get("had_key")
            if drop_key:
                prof.pop("status_effects", None)
            else:
                prof["status_effects"] = vals
            # Soul values are injected on read; they never go back through a
            # profile save.
            for key, field in _template_fields(str(prof.get("template") or "")).items():
                if field.get("source_file"):
                    prof.pop(key, None)
            if not save_character_profile(name, prof):
                raise RuntimeError(f"profile of {name} was not stored")
            # status_effects lives in character_state.meta, which a profile
            # save merges: leaving the key out does not remove it.
            if drop_key and not remove_state_meta_key(name, "status_effects"):
                raise RuntimeError(f"status_effects of {name} was not removed")
    if touched:
        from app.core import sync_topics
        sync_topics.changed_at(name, topics=("presence", "self"))
    if changed:
        raise _Skip(REASON_CHANGED, keys=changed)
    return []


def _undo_remove_outfits(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Remove the outfit sets an update_character added, take back the
    inventory entries it added and delete the catalog pieces it created
    (only those held nowhere — :func:`_cleanup_items`). A done entry names
    the exact ids and compares each with what was written (``changed
    since`` when it differs: kept). A pending one (the process ended inside
    the write) is resolved from what the inverse recorded before it: the
    sets of the given names that did not exist before, and the inventory
    entries of the named / created pieces that were not held before."""
    from app.models.character import character_row_exists, delete_character_outfit
    from app.models.inventory import remove_from_inventory
    name = str(inv.get("name") or "")
    written = entry.get("written")
    w_outs = (written.get("outfits") or {}) if isinstance(written, dict) else None
    w_inv = (written.get("inventory") or {}) if isinstance(written, dict) else None
    items = [str(i) for i in inv.get("items") or [] if i]
    changed: List[str] = []
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            return [_Skip(REASON_GONE)] + _cleanup_items(items)
        outs = outfit_rows(name)
        held = inventory_entries(name)
        if "outfits" in inv:
            out_ids = [str(o) for o in inv.get("outfits") or []]
            inv_ids = [str(i) for i in inv.get("inventory") or []]
        else:
            names = {str(n).strip().casefold() for n in inv.get("names") or []}
            before_o = set(inv.get("outfits_before") or [])
            before_i = set(inv.get("inventory_before") or [])
            out_ids = [oid for oid, o in outs.items() if oid not in before_o
                       and str(o.get("name") or "").strip().casefold() in names]
            inv_ids = [iid for iid in list(inv.get("refs") or []) + items
                       if iid in held and iid not in before_i]
        # The pieces of a set that is KEPT (changed since) stay with the
        # character: taking them back would leave the kept set without them.
        kept_pieces: set = set()
        for oid in out_ids:
            if oid not in outs:
                continue
            if isinstance(w_outs, dict) and oid in w_outs and outs[oid] != _norm(w_outs[oid]):
                changed.append(f"outfit {outs[oid].get('name') or oid}")
                kept_pieces.update(str(p) for p in outs[oid].get("pieces") or [])
                continue
            if not delete_character_outfit(name, oid) and oid in outfit_rows(name):
                raise RuntimeError(f"outfit {oid} of {name} was not deleted")
        for iid in inv_ids:
            if iid not in held or iid in kept_pieces:
                continue
            if isinstance(w_inv, dict) and iid in w_inv and held[iid] != _norm(w_inv[iid]):
                changed.append(f"inventory {iid}")
                continue
            qty = int(held[iid].get("quantity") or 1)
            if (not remove_from_inventory(name, iid, quantity=qty, force=True)
                    and iid in inventory_entries(name)):
                raise RuntimeError(f"inventory entry {iid} of {name} was not removed")
    skips = _cleanup_items(items)
    if changed:
        return [_Skip(REASON_CHANGED, keys=changed)] + skips
    return skips


def _undo_restore_soul(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.core import soul_writer
    from app.models.character import character_row_exists
    name = str(inv.get("name") or "")
    rel = str(inv.get("file_id") or "")
    written = entry.get("written")
    # Lock order: character_profile -> soul_file (both re-entrant).
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        path = soul_writer.soul_text_path(name, rel)
        with keyed_lock("soul_file", str(path)):
            # A done entry compares even when the agent's write removed the
            # file (written None); a pending one has nothing to compare.
            if entry.get("state") == "done":
                if soul_writer.read_text(name, rel) != written:
                    raise _Skip(REASON_CHANGED, keys=[rel])
            soul_writer.write_text(name, rel, inv.get("before_text"))
    return []


def _undo_restore_home_schedule(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Same saver chain as ``world_dev_apply._apply_home_and_schedule``:
    home, room and known places through ``save_character_config``, the
    schedule through ``save_character_daily_schedule`` + the scheduler
    marker sync. A known_locations of None removes the key again."""
    from app.models.character import (character_row_exists,
                                      get_character_config,
                                      save_character_config,
                                      save_character_daily_schedule)
    name = str(inv.get("name") or "")
    before = {k: v for k, v in (inv.get("before") or {}).items()
              if k in HOME_SCHEDULE_KEYS}
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        restore, changed = _split_keys(before, entry.get("written"),
                                       home_schedule_state(name))
        cfg_keys = {k: v for k, v in restore.items()
                    if k in ("home_location", "home_room", "known_locations")}
        if cfg_keys:
            cfg = copy.deepcopy(get_character_config(name) or {})
            for key, value in cfg_keys.items():
                if value is None or is_absent(value):
                    cfg.pop(key, None)
                else:
                    cfg[key] = copy.deepcopy(value)
            if not save_character_config(name, cfg):
                raise RuntimeError(f"config of {name} was not stored")
        if "daily_schedule" in restore:
            sched = restore["daily_schedule"]
            if is_absent(sched) or not isinstance(sched, dict):
                sched = {"enabled": False, "slots": []}
            sched = {"enabled": bool(sched.get("enabled")),
                     "slots": list(sched.get("slots") or [])}
            if not save_character_daily_schedule(name, sched):
                raise RuntimeError(f"schedule of {name} was not stored")
            try:
                from app.scheduler.scheduler_manager import get_scheduler_manager
                get_scheduler_manager().sync_daily_schedule(name, sched)
            except Exception as e:  # noqa: BLE001 — the row is stored; the marker is cosmetic
                logger.warning("undo: schedule marker for %s failed: %s", name, e)
    if changed:
        raise _Skip(REASON_CHANGED, keys=changed)
    return []

def _undo_remove_known_places(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Removes exactly the places of ``ids`` from the character's known
    places — none of them was known before the call (a pending entry names
    every place the call was about to add, so removing them is exact too).
    A place already gone is fine (it is unknown again either way); places
    added by anybody else (in-game discovery) stay, so a foreign change never
    makes this undo incomplete. A later discovery of one of the SAME places
    was a no-op (the place was already known), so the undo still removes it
    — an add-only list carries no provenance. The ``known_locations`` key
    goes only when it did not exist before (``had_key`` False) and the list
    is empty again. Only that key is written (``character.write_known_locations``):
    the rest of the stored config and ``updated_at`` are left as they are."""
    from app.models.character import (character_row_exists, stored_known_locations,
                                      write_known_locations)
    name = str(inv.get("name") or "")
    ids = {str(i) for i in inv.get("ids") or [] if i}
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        if not ids:
            return []
        # Only the stored key, never the defaulting config reader (it would
        # write a whole default config for an empty one).
        raw = stored_known_locations(name)[1]
        if not isinstance(raw, list):
            return []
        keep = [v for v in raw if str(v) not in ids]
        if len(keep) == len(raw):
            return []
        if not write_known_locations(name, keep if (keep or inv.get("had_key")) else None):
            raise RuntimeError(f"config of {name} was not stored")
    return []

# ── Cross-turn deletes: exact snapshots and their re-creation ──────────
#
# delete_created of something the run created in an EARLIER turn journals a
# write of its own whose inverse re-creates the element exactly as it was
# stored right before the delete (the snapshot is taken under the writer's
# lock, in the same span as the delete). A discard then re-creates it and the
# creating step's inverse deletes it again — net absent, complete; a rollback
# of the deleting turn alone re-creates it.

#: Most bytes of a character's directory a cross-turn delete carries in its
#: journal row (base64 in the inverse). A larger directory (generated images,
#: models) is refused up front instead of being restored in part.
MAX_SNAPSHOT_FILE_BYTES = 512 * 1024
#: Most bytes of the database rows of a character snapshot.
MAX_SNAPSHOT_ROW_BYTES = 2 * 1024 * 1024

#: delete_character's sweep of the references that are NOT a
#: `character_name` column, copied literally from
#: `app.models.character.delete_character` (table, WHERE clause). Every table
#: with a `character_name` column is swept as well — read off the schema, the
#: same way delete_character finds them. scripts/smoke_world_dev_undo.py
#: compares this list with the DELETE statements in delete_character's source,
#: so a new sweep there cannot silently fall out of the snapshot.
CHARACTER_SWEEP_SPECIAL: Tuple[Tuple[str, str], ...] = (
    ("characters", "name=?"),
    ("relationships", "from_char=? OR to_char=?"),
    ("llm_call_stats", "agent_name=?"),
    ("chat_messages", "partner=?"),
    ("chat_stat_evaluations", "recipient=?"),
    ("parties", "leader=?"),
    ("party_invites", "inviter=? OR invitee=?"),
    ("interaction_invites", "inviter=? OR invitee=?"),
    ("intents", "owner=?"),
    ("quest_facts", "mind=? OR subject=?"),
    ("notifications", "title=? AND kind<>'room_furnish'"),
)

_ROWID = "$rowid"


def _cell_out(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        import base64
        return {"$b64": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _cell_in(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$b64"}:
        import base64
        return base64.b64decode(value["$b64"])
    return value


def character_rows(name: str) -> Dict[str, List[Dict[str, Any]]]:
    """Every database row `delete_character(name)` removes, per table, in
    rowid order: the rows of each table with a `character_name` column plus
    :data:`CHARACTER_SWEEP_SPECIAL`. A row carries its rowid (key
    `"$rowid"`) so the re-creation stores it under the same key; BLOB cells
    are `{"$b64": ...}`. Tables without such a row are left out."""
    import sqlite3
    from app.core.db import get_connection
    conn = get_connection()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    sweeps: Dict[str, List[str]] = {}
    for tbl in tables:
        cols = {c[1] for c in conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()}
        if "character_name" in cols:
            sweeps.setdefault(tbl, []).append("character_name=?")
    present = set(tables)
    for tbl, where in CHARACTER_SWEEP_SPECIAL:
        if tbl in present:
            sweeps.setdefault(tbl, []).append(where)
    found: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def grab(tbl: str, where: str, params: tuple) -> List[Dict[str, Any]]:
        try:
            cur = conn.execute(f'SELECT rowid AS "{_ROWID}", * FROM "{tbl}" '
                               f'WHERE {where}', params)
        except sqlite3.OperationalError:  # a WITHOUT ROWID table
            cur = conn.execute(f'SELECT * FROM "{tbl}" WHERE {where}', params)
        names = [d[0] for d in cur.description]
        new = []
        for r in cur.fetchall():
            row = {k: _cell_out(v) for k, v in zip(names, r)}
            key = json.dumps(row.get(_ROWID, row), sort_keys=True, default=str)
            if key not in found.setdefault(tbl, {}):
                found[tbl][key] = row
                new.append(row)
        return new

    for tbl in sorted(sweeps):
        where = " OR ".join(f"({w})" for w in sweeps[tbl])
        grab(tbl, where, (name,) * where.count("?"))
    # The rows an ON DELETE CASCADE takes along with a swept row (memory
    # embeddings with their memory, ...), transitively.
    cascades = []
    for tbl in tables:
        for fk in conn.execute(f'PRAGMA foreign_key_list("{tbl}")').fetchall():
            # (id, seq, parent table, child column, parent column, on_update, on_delete, match)
            if str(fk[6]).upper() == "CASCADE":
                cascades.append((tbl, fk[3], fk[2], fk[4]))
    pending = {t: list(rows.values()) for t, rows in found.items()}
    while pending:
        parents, pending = pending, {}
        for child, ccol, parent, pcol in cascades:
            values = sorted({json.dumps(r.get(pcol)) for r in parents.get(parent, [])
                             if r.get(pcol) is not None})
            for i in range(0, len(values), 500):
                chunk = [json.loads(v) for v in values[i:i + 500]]
                new = grab(child, f'"{ccol}" IN ({", ".join("?" for _ in chunk)})',
                           tuple(chunk))
                if new:
                    pending.setdefault(child, []).extend(new)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for tbl in sorted(found):
        rows = list(found[tbl].values())
        if rows:
            out[tbl] = sorted(rows, key=lambda r: (
                (0, int(r[_ROWID]), "") if _ROWID in r
                else (1, 0, json.dumps(r, sort_keys=True, default=str))))
    return out


def _character_dir(name: str):
    from app.models.character import get_user_characters_dir
    base = get_user_characters_dir()
    path = base / name
    if path.resolve().parent != base.resolve():
        raise ValueError(f"character directory of {name!r} is outside the storage")
    return path


def character_files(name: str) -> Tuple[Dict[str, str], List[str], int]:
    """The character's directory as `({relative path: base64 bytes},
    [relative directories], total bytes)`; a symlink raises ValueError (it
    could not be restored as what it was)."""
    import base64
    root = _character_dir(name)
    files: Dict[str, str] = {}
    dirs: List[str] = []
    total = 0
    if not root.exists():
        return files, dirs, 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"{rel} is a symlink")
        if path.is_dir():
            dirs.append(rel)
        elif path.is_file():
            data = path.read_bytes()
            total += len(data)
            files[rel] = base64.b64encode(data).decode("ascii")
    return files, dirs, total


def character_snapshot(name: str) -> Dict[str, Any]:
    """Everything `delete_character(name)` removes that belongs to the
    character itself: `{"rows": character_rows, "files", "dirs", "has_dir",
    "file_bytes"}`. Call under `keyed_lock("character_profile", name)`."""
    files, dirs, total = character_files(name)
    return {"rows": character_rows(name), "files": files, "dirs": dirs,
            "has_dir": _character_dir(name).is_dir(), "file_bytes": total}


def _restore_character(name: str, snap: Dict[str, Any]) -> None:
    """Store a :func:`character_rows` + :func:`character_files` snapshot
    again: every row under its rowid in ONE transaction, then the files."""
    import base64
    from app.core.db import transaction
    from app.models.character_template import invalidate_source_file
    rows = snap.get("rows") or {}
    with transaction() as conn:
        # Parents before children: a row's foreign key is checked on insert.
        parents = {tbl: {fk[2] for fk in conn.execute(
            f'PRAGMA foreign_key_list("{tbl}")').fetchall()} & set(rows) - {tbl}
            for tbl in rows}
        order: List[str] = []
        while len(order) < len(rows):
            ready = sorted(t for t in rows if t not in order
                           and parents[t] <= set(order))
            if not ready:  # a cycle: the rest in name order
                ready = sorted(t for t in rows if t not in order)
            order.extend(ready)
        for tbl in order:
            for row in rows[tbl]:
                cols = list(row)
                if _ROWID in row:
                    cur = conn.execute(f'SELECT rowid AS "{_ROWID}", * FROM "{tbl}" '
                                       'WHERE rowid=?', (int(row[_ROWID]),))
                    have = cur.fetchone()
                    if have is not None:
                        names = [d[0] for d in cur.description]
                        if _norm({k: _cell_out(v) for k, v in zip(names, have)}) == _norm(row):
                            # A cascade row still there (foreign keys off on
                            # the deleting connection) is the same row.
                            continue
                        # The key went to another row since: nothing is
                        # stored (the transaction rolls back).
                        raise _Skip(REASON_CHANGED,
                                    keys=[f"{tbl} row {row[_ROWID]} is taken"])
                col_sql = ", ".join("rowid" if c == _ROWID else f'"{c}"' for c in cols)
                conn.execute(f'INSERT INTO "{tbl}" ({col_sql}) VALUES '
                             f'({", ".join("?" for _ in cols)})',
                             tuple(_cell_in(row[c]) for c in cols))
    if not snap.get("has_dir"):
        return
    root = _character_dir(name)
    root.mkdir(parents=True, exist_ok=True)
    root_res = root.resolve()

    def inside(rel: str):
        target = root / rel
        if root_res not in target.resolve().parents:
            raise ValueError(f"snapshot path {rel!r} leaves the character directory")
        return target
    for rel in snap.get("dirs") or []:
        inside(rel).mkdir(parents=True, exist_ok=True)
    for rel, b64 in (snap.get("files") or {}).items():
        target = inside(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".wdundo")
        tmp.write_bytes(base64.b64decode(b64))
        tmp.replace(target)
        invalidate_source_file(target)


def _recreate_exists(entry: Dict[str, Any]) -> List["_Skip"]:
    """The element of a re-creation exists. Pending (the process ended
    between journal begin and complete): the delete never ran — nothing to
    do. Done: somebody else stored an element under that key since; it is
    not this run's and is left alone."""
    if entry.get("state") == "pending":
        return []
    raise _Skip(REASON_CHANGED, keys=["exists again"])


def _check_recreated(now: Optional[Dict[str, Any]], want: Dict[str, Any]) -> None:
    if _norm(now) != _norm(want):
        b, _w = diff_keys(want, now if isinstance(now, dict) else {})
        raise _Skip(REASON_INEXACT, keys=sorted(b))


def _undo_recreate_location(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.world import (get_location_by_id, upsert_location,
                                  world_write_lock)
    row = inv.get("row") or {}
    lid = str(row.get("id") or "")
    if not lid:
        raise RuntimeError("recreate_location without an id")
    with world_write_lock:
        if get_location_by_id(lid) is not None:
            return _recreate_exists(entry)
        if not upsert_location(copy.deepcopy(row), sync_world=True):
            raise RuntimeError(f"re-creating location {lid} was not stored")
        _check_recreated(get_location_by_id(lid), row)
    return []


def _check_order(exact_order: bool) -> None:
    """A re-created area whose old rowid was taken while another area shares
    its paint-order stamp: the content is exact, its place in the order may
    not be (terrain.restore_area)."""
    if not exact_order:
        raise _Skip(REASON_INEXACT, keys=["paint order"])


# A deleted area comes back with its ORDER identity (inverse key `order`:
# created_at, updated_at, rowid — terrain.area_order_identity): the paint
# order decides which overlapping area answers a point, and the height-area
# order feeds height_sig, so re-inserting it "now" would move it to the top.
# An entry journalled without `order` (before the key existed) is re-created
# through the same writer with an empty identity (stamped now, a fresh rowid)
# and reported as an inexact paint order — the content is exact, its place
# in the order is not known.

def _undo_recreate_terrain_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.terrain import get_area, restore_area
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    if not aid:
        raise RuntimeError("recreate_terrain_area without an id")
    if get_area(aid) is not None:
        return _recreate_exists(entry)
    order = inv.get("order")
    _area, exact = restore_area(copy.deepcopy(row),
                                order if isinstance(order, dict) else {})
    _check_recreated(get_area(aid), row)
    exact = exact and isinstance(order, dict)
    _check_order(exact)
    return []


def _undo_recreate_height_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.heightfield import restore_height_area
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    if not aid:
        raise RuntimeError("recreate_height_area without an id")
    if _height_area(aid) is not None:
        return _recreate_exists(entry)
    order = inv.get("order")
    _area, exact = restore_height_area(copy.deepcopy(row),
                                       order if isinstance(order, dict) else {})
    _check_recreated(_height_area(aid), row)
    exact = exact and isinstance(order, dict)
    _check_order(exact)
    return []


# ── World props (free-standing props, E10) ───────────────────────────────

def world_prop_row(placement_id: str) -> Optional[Dict[str, Any]]:
    """One stored world prop as the reader gives it (``list_world_props``
    rows: id, prop_id, x, z, yaw_deg, offset_y, variant), or None."""
    from app.models.world_props import list_world_props
    pid = str(placement_id or "")
    return next((r for r in list_world_props() if r.get("id") == pid), None) if pid else None


# Like the areas, the world-prop writer has no writer lock to share: compare
# and delete are not one atomic span; in a frozen world the window is
# negligible.

def _undo_delete_world_prop(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.world_props import delete_world_prop
    wid = str(inv.get("id") or "")
    cur = world_prop_row(wid)
    if cur is None:
        raise _Skip(REASON_GONE)
    written = entry.get("written")
    if written is not None and _norm(cur) != _norm(written):
        b, _w = diff_keys(written, cur)
        raise _Skip(REASON_CHANGED, keys=sorted(b))
    if not delete_world_prop(wid) and world_prop_row(wid) is not None:
        raise _Skip(REASON_REFUSED)
    return []


def _undo_recreate_world_prop(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Bring a deleted world prop back with its exact row values. The
    authoring ORDER is not restored: the writer stamps a new ``created_at``,
    so the prop moves to the end of ``list_world_props()``. Accepted — world
    props are decoration-only draw calls, nothing reads their order but the
    listing itself."""
    from app.models.world_props import save_world_prop
    row = inv.get("row") or {}
    wid = str(row.get("id") or "")
    if not wid:
        raise RuntimeError("recreate_world_prop without an id")
    if world_prop_row(wid) is not None:
        return _recreate_exists(entry)
    try:
        save_world_prop(copy.deepcopy(row))
    except ValueError as exc:  # unknown library prop, world-prop cap
        raise _Skip(REASON_RECREATE_REFUSED, error=str(exc)) from None
    _check_recreated(world_prop_row(wid), row)
    return []


def _undo_recreate_character(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.character import (character_row_exists,
                                      get_character_current_location)
    name = str(inv.get("name") or "")
    snap = inv.get("snapshot") or {}
    if not name or not (snap.get("rows") or {}).get("characters"):
        raise RuntimeError("recreate_character without a snapshot")
    with keyed_lock("character_profile", name):
        if character_row_exists(name):
            # The DB sweep is one transaction and runs before the files go:
            # a row still there means the delete removed nothing.
            return _recreate_exists(entry)
        _restore_character(name, snap)
        # Read back through the same reader the snapshot used.
        if _norm(character_rows(name)) != _norm(snap.get("rows") or {}):
            raise _Skip(REASON_INEXACT, keys=["database rows"])
    try:
        from app.core import linked_characters, sync_topics
        linked_characters.invalidate()
        sync_topics.moved(name, "", get_character_current_location(name) or "")
    except Exception as e:  # noqa: BLE001 — the rows are stored; the signal is cosmetic
        logger.warning("undo: re-created %s, presence signal failed: %s", name, e)
    return []


# ── Terrain kinds (custom kinds of the world catalog, E12) ──────────────

def terrain_type_row(kind: str) -> Optional[Dict[str, Any]]:
    """The WORLD row of one terrain kind as the catalog reads it, or None
    when the world holds no row of that kind (a shared-only kind is not the
    world's to delete)."""
    from app.core import terrain_types as tt
    k = str(kind or "").strip()
    if not k or tt.sources().get(k) != "world":
        return None
    return tt.get_type(k)


def terrain_type_changed(row: Optional[Dict[str, Any]], written: Any) -> bool:
    """Does the stored world row of a kind differ from what the creating
    step wrote (its journal ``written``)? False when nothing was journalled."""
    return written is not None and _norm(row) != _norm(written)


def terrain_kind_users(kind: str) -> List[Tuple[str, str, str]]:
    """Everything that names a terrain kind: ``(target kind, id, text)`` per
    terrain area whose ``kind`` OR ``meta.bed_kind`` (the ground under a
    water) it is, per place whose ``terrain`` field it is, and the world
    setting ``game.default_terrain_kind`` (the ground no area covers) when
    it names the kind. The one in-use check of the kind's undo, of
    ``delete_created`` and of the discard preview."""
    from app.core import config
    from app.models.terrain import list_areas
    from app.models.world import list_locations
    k = str(kind or "").strip()
    out: List[Tuple[str, str, str]] = []
    if not k:
        return out
    for area in list_areas():
        meta = area.get("meta") if isinstance(area.get("meta"), dict) else {}
        aid = str(area.get("id") or "")
        if str(area.get("kind") or "").strip() == k:
            out.append(("terrain", aid, f"terrain area {aid}"))
        elif str(meta.get("bed_kind") or "").strip() == k:
            out.append(("terrain", aid, f"terrain area {aid} (its water bed)"))
    for loc in list_locations():
        if str(loc.get("terrain") or "").strip() == k:
            lid = str(loc.get("id") or "")
            out.append(("location", lid, f'location {lid} "{loc.get("name") or ""}"'))
    if str(config.get("game.default_terrain_kind", "") or "").strip() == k:
        out.append(("setting", "game.default_terrain_kind",
                    "the world's default ground (setting game.default_terrain_kind)"))
    return out


# Like the areas, the catalog writer has no writer lock to share: compare,
# use check and delete are not one atomic span; in a frozen world the window
# is negligible.

def _undo_delete_terrain_type(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Remove a kind the run created. Its own uses were undone first (they
    are newer entries, the undo walks newest-first); a use that remains is
    somebody else's — the kind stays (changed since, in use)."""
    from app.core.terrain_types import delete_world_type
    kind = str(inv.get("kind") or "")
    cur = terrain_type_row(kind)
    if cur is None:
        raise _Skip(REASON_GONE)
    written = entry.get("written")
    if terrain_type_changed(cur, written):
        b, _w = diff_keys(written, cur)
        raise _Skip(REASON_CHANGED, keys=sorted(b))
    if terrain_kind_users(kind):
        raise _Skip(REASON_CHANGED, keys=["in use"])
    if not delete_world_type(kind) and terrain_type_row(kind) is not None:
        raise _Skip(REASON_REFUSED)
    return []


def _undo_recreate_terrain_type(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.core.terrain_types import effective_catalog, save_world_type
    row = inv.get("row") or {}
    kind = str(row.get("kind") or "")
    if not kind:
        raise RuntimeError("recreate_terrain_type without a kind")
    if kind in effective_catalog():
        return _recreate_exists(entry)
    try:
        save_world_type(copy.deepcopy(row))
    except ValueError as exc:
        raise _Skip(REASON_RECREATE_REFUSED, error=str(exc)) from None
    _check_recreated(terrain_type_row(kind), row)
    return []


# ── Items: catalog, inventories, room items (E14) ────────────────────────

def item_row(item_id: str) -> Optional[Dict[str, Any]]:
    """One WORLD catalog item as the reader gives it (``get_item``), or None
    (a shared library item is never the run's own)."""
    from app.models.inventory import get_item, is_shared_item
    iid = str(item_id or "")
    if not iid or is_shared_item(iid):
        return None
    row = get_item(iid)
    return _norm(row) if row else None


def _undo_delete_items(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Remove the catalog items a create_item made — only those held nowhere
    (an inventory or a room) and never a shared one (:func:`_cleanup_items`).
    An item already gone is ``already gone`` for the entry."""
    ids = [str(i) for i in inv.get("ids") or [] if i]
    if not any(item_row(i) is not None for i in ids):
        raise _Skip(REASON_GONE)
    return _cleanup_items(ids)


def _undo_restore_inventory(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Take a give_items back per item: an entry that differs from what the
    give wrote is somebody else's change (``changed since``, keys = item ids);
    an entry the give created (before ABSENT) is removed whole, a stack the
    give increased is set back to its quantity (the give touched no other
    field of it, so the entry then equals its pre-run state)."""
    from app.models.character import character_row_exists
    from app.models.inventory import remove_from_inventory, update_inventory_entry
    name = str(inv.get("name") or "")
    before = inv.get("before") or {}
    written = entry.get("written")
    changed: List[str] = []
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        for iid, bval in before.items():
            now = inventory_entries(name).get(iid, ABSENT)
            if isinstance(written, dict) and iid in written:
                if _norm(now) != _norm(written[iid]):
                    changed.append(iid)
                    continue
            if is_absent(now):
                continue
            if is_absent(bval):
                qty = int(now.get("quantity") or 1)
                if (not remove_from_inventory(name, iid, quantity=qty, force=True)
                        or iid in inventory_entries(name)):
                    raise RuntimeError(f"inventory entry {iid} of {name} was not removed")
            elif (not update_inventory_entry(name, iid, {"quantity": bval})
                  or (inventory_entries(name).get(iid) or {}).get("quantity") != bval):
                raise RuntimeError(f"inventory entry {iid} of {name} was not set "
                                   f"back to {bval}")
    if changed:
        raise _Skip(REASON_CHANGED, keys=changed)
    return []


def room_items_value(room: Dict[str, Any]) -> Any:
    """A room's whole ``items`` value (a deep copy), :data:`ABSENT` when the
    room has no such key — the before/written shape of restore_room_items."""
    return copy.deepcopy(room["items"]) if "items" in room else ABSENT


def _item_ids(value: Any) -> set:
    if is_absent(value) or not isinstance(value, list):
        return set()
    return {str(e.get("item_id") or "") for e in value if isinstance(e, dict)} - {""}


def _undo_restore_room_items(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Set a room's whole ``items`` value back (or pop the key when it had
    none) under ``world_write_lock`` — never through remove_item_from_room,
    so the row is equal to before and an OLDER restore_location of the same
    place still finds its rooms as written. The discovery rows of every item
    the restore takes out of the room go too (the statement
    remove_item_from_room runs; inventory has no public helper for it)."""
    from app.core import sync_topics
    from app.core.db import transaction
    from app.models.world import (get_location_by_id, upsert_location,
                                  world_write_lock)
    lid = str(inv.get("location_id") or "")
    rid = str(inv.get("room_id") or "")
    before = inv.get("before", ABSENT)
    written = entry.get("written")
    with world_write_lock:
        cur = get_location_by_id(lid) if lid else None
        if cur is None:
            raise _Skip(REASON_GONE)
        cur = copy.deepcopy(cur)
        room = next((r for r in cur.get("rooms") or []
                     if isinstance(r, dict) and r.get("id") == rid), None)
        if room is None:
            raise _Skip(REASON_GONE)
        now = room_items_value(room)
        if written is not None and _norm(now) != _norm(written):
            raise _Skip(REASON_CHANGED, keys=["items"])
        if is_absent(before):
            room.pop("items", None)
        else:
            room["items"] = copy.deepcopy(before)
        if not upsert_location(cur, sync_world=False):
            raise RuntimeError(f"restoring the items of room {rid} of {lid} was not stored")
        gone = _item_ids(now) - _item_ids(before)
        if gone:
            with transaction() as conn:
                for iid in sorted(gone):
                    conn.execute("DELETE FROM item_discoveries WHERE location_id=? "
                                 "AND room_id=? AND item_id=?", (lid, rid, iid))

    def visible(value: Any) -> bool:
        return (isinstance(value, list)
                and any(isinstance(e, dict) and not e.get("hidden") for e in value))
    sync_topics.room_items_changed(lid, rid, visible(now), visible(before))
    return []


def _undo_restore_address(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Reverse set_address. The pair row gone -> already gone; the key's
    value differs from what the step wrote -> changed since [key]. A row the
    step CREATED is deleted when, apart from the key, it still is the row the
    step wrote; when somebody changed the rest of it since, only the key is
    cleared and the row stays (changed since ["row"] — it is theirs now).
    Otherwise, when the row is still the one the step wrote apart from the
    key (a pending step: the key still holds the ``text`` it sent), its
    journaled raw columns (``raw``) are written back byte-for-byte (the
    writer filled the reader's defaults into a sparse row); when the rest
    changed since, only the key's meta entry gets its before value back
    (ABSENT pops it) through ``relationship.set_pair_row_meta_key`` — every
    other stored column stays as it is, no reader defaults are added — and
    the meta keys the step itself added (:func:`_address_added_keys`) are
    popped while they still hold what it wrote; one that cannot go (a
    content column, a foreign value) -> changed since ["row"]. The
    cleared key of a created row that changed goes the same way. :func:`discard_preview` simulates the same
    branches (:func:`_address_preview_lines`). The writer has no lock to
    share (world frozen during a run — accepted residual)."""
    from app.models import relationship as rel
    speaker = str(inv.get("speaker") or "")
    addressee = str(inv.get("addressee") or "")
    key = str(inv.get("key") or "")
    if not speaker or not addressee or not key:
        raise RuntimeError("restore_address without its pair or key")
    row = rel.pair_row(speaker, addressee)
    if row is None:
        raise _Skip(REASON_GONE)
    written = entry.get("written")
    if isinstance(written, dict) and (_norm(row.get(key, ABSENT))
                                      != _norm(written.get("value", ABSENT))):
        raise _Skip(REASON_CHANGED, keys=[key])
    wrow = written.get("row") if isinstance(written, dict) else None

    def rest(r: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in r.items() if k != key}
    if inv.get("row_created"):
        if wrow is None or _norm(rest(row)) == _norm(rest(wrow)):
            # A pending step (no written) is the run's own unreported write.
            if not rel.delete_pair_row(int(row["_db_id"])) and \
                    rel.pair_row(speaker, addressee) is not None:
                raise _Skip(REASON_REFUSED)
            return []
        if not rel.set_pair_row_meta_key(int(row["_db_id"]), key, remove=True):
            rel.set_address(speaker, addressee, "")
        raise _Skip(REASON_CHANGED, keys=["row"])
    raw = inv.get("raw")
    if isinstance(written, dict):
        own = wrow is not None and _norm(rest(row)) == _norm(rest(wrow))
    else:
        # A pending step (crash between the write and complete): the row is
        # still the one it wrote when the key holds the text it sent (world
        # frozen during a run, like the created-row branch above).
        own = ("text" in inv and _norm(row.get(key, ABSENT))
               == _norm(inv.get("text") or ABSENT))
    if (own and isinstance(raw, dict)
            and row.get("_db_id") == inv.get("row_id")
            and rel.restore_pair_row(int(row["_db_id"]), raw)):
        return []
    # The rest of the row changed since: only the key's meta entry goes back,
    # every other stored column stays as it is (the merging writer only when
    # the meta is not a JSON object).
    before = inv.get("before", ABSENT)
    if not rel.set_pair_row_meta_key(int(row["_db_id"]), key,
                                     None if is_absent(before) else before,
                                     remove=is_absent(before)):
        rel.set_address(speaker, addressee, "" if is_absent(before) else before)
    # The reader defaults the step's own write put into a sparse row (meta
    # ``id``, ``history``, ...) go too while they still hold what it wrote;
    # one that cannot go (a content column, a foreign value, an unreadable
    # journal) leaves the row not as before -> changed since ["row"].
    added = _address_added_keys(raw, wrow, key) if isinstance(written, dict) else {}
    if added is None:
        raise _Skip(REASON_CHANGED, keys=["row"])
    for k, v in added.items():
        if _norm(row.get(k, ABSENT)) != _norm(v):
            continue
        try:
            rel.set_pair_row_meta_key(int(row["_db_id"]), k, remove=True)
        except ValueError:
            pass  # a content column key: not popped, counted below
    if added:
        now = rel.pair_row(speaker, addressee)
        if now is not None and any(k in now for k in added):
            raise _Skip(REASON_CHANGED, keys=["row"])
    return []


def _address_added_keys(raw: Any, wrow: Any, key: str) -> Optional[Dict[str, Any]]:
    """The keys set_address added to a row that existed, with the value it
    wrote: present in the written row (``written["row"]``, a
    :func:`relationship.pair_row` view), absent from the journaled raw
    columns (content and meta), apart from the address *key* itself, the
    column names and the ``_``-prefixed bookkeeping. {} without a written
    row; None when the raw columns cannot be read (the undo cannot tell)."""
    if not isinstance(wrow, dict):
        return {}
    if not isinstance(raw, dict):
        return None
    try:
        content = json.loads(raw.get("content") or "{}")
        meta = json.loads(raw.get("meta") or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(content, dict) or not isinstance(meta, dict):
        return None
    had = set(content) | set(meta)
    return {k: v for k, v in wrow.items()
            if k != key and not k.startswith("_")
            and k not in ("character_a", "character_b") and k not in had}


def secret_row(owner: str, secret_id: str) -> Optional[Dict[str, Any]]:
    """The stored secret *secret_id* of *owner*'s mind, or None. A read
    error propagates (never read as "absent")."""
    from app.models.secrets import list_secrets
    return next((s for s in list_secrets(owner, strict=True)
                 if str(s.get("id")) == secret_id), None)


def _undo_delete_secret(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Reverse add_secret: under the writer's own lock (re-entrant) the
    secret gone -> already gone; differing from what the step wrote ->
    changed since (the keys that differ); else it is deleted. A pending
    step (no written) is the run's own unreported write (world frozen).
    Accepted residual (like the rules layer's
    ``save_rules``): the writer (``secrets._save_secrets``) re-serialises
    every secret of the mind on each add and delete, so a FOREIGN legacy or
    sparse secret row of the same mind may come back with the reader's
    defaults filled in (meta ``id``, ``category``, ``severity``,
    ``known_by``/``discovered_by``, ...; ``visibility`` rewritten) — same
    meaning; byte-for-byte (gone again) holds for the run's own row. The admin's own add
    and delete do the same today."""
    from app.models.secrets import delete_secret
    owner = str(inv.get("owner") or "")
    sid = str(inv.get("id") or "")
    if not owner or not sid:
        raise RuntimeError("delete_secret without its owner or id")
    with keyed_lock("secrets", owner):
        cur = secret_row(owner, sid)
        if cur is None:
            raise _Skip(REASON_GONE)
        written = entry.get("written")
        if written is not None and _norm(cur) != _norm(written):
            b, _w = diff_keys(written, cur)
            raise _Skip(REASON_CHANGED, keys=sorted(b))
        delete_secret(owner, sid)
        # The writer returns True even when its save logged and swallowed a
        # DB error: read the row back whatever it returned.
        if secret_row(owner, sid) is not None:
            raise _Skip(REASON_REFUSED)
    return []


def _undo_delete_rule(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Reverse add_block_rule: under ``rules.layer_lock()`` (re-entrant; the
    writers take it too) the world-layer row gone -> already gone; differing
    from what the step wrote -> changed since (the keys that differ); else
    it is deleted from the world layer and read back. Accepted residual
    (plan p3 Review focus 1): ``save_rules`` re-serialises every world rule
    on the delete, so a FOREIGN legacy row may come back normalised with the
    same meaning; rows written by ``add_rule`` stay byte-for-byte."""
    from app.models import rules
    rid = str(inv.get("id") or "")
    if not rid:
        raise RuntimeError("delete_rule without its id")
    with rules.layer_lock():
        cur = rules.world_rule(rid)
        if cur is None:
            raise _Skip(REASON_GONE)
        written = entry.get("written")
        if written is not None and _norm(cur) != _norm(written):
            b, _w = diff_keys(written, cur)
            raise _Skip(REASON_CHANGED, keys=sorted(b))
        rules.delete_rule(rid, target_dir="world")
        if rules.world_rule(rid) is not None:
            raise _Skip(REASON_REFUSED)
    return []


def _event_row_strict(eid: str) -> Optional[Dict[str, Any]]:
    """The event's row, None only when it is really gone. ``get_event``
    alone reads a failed table read as "gone"; ``event_exists`` asks first
    and a read error raises instead (as in ``_exists``)."""
    from app.models import events
    found = events.event_exists(eid)
    if found is None:
        raise RuntimeError(f"event {eid}: the events table could not be read")
    if not found:
        return None
    row = events.get_event(eid)
    if row is None:
        raise RuntimeError(f"event {eid}: the event row could not be read")
    return row


def _undo_delete_event(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Reverse add_event: under ``keyed_lock("world_event", id)`` (the lock
    the event writers take around their read-modify-write) the event gone ->
    already gone; differing from what the step wrote -> changed since (an
    attempt, a stat hit, a resolution or an image all change the row); else
    it is deleted and read back strictly (a failed table read raises instead
    of counting as deleted). The writer's cascade also removes rules bound to
    the event (``delete_rules_by_event``) and its image files
    (``remove_event_images``) unchecked against the journal; a run's own
    event has neither — only ``random_events`` binds rules, to its own
    events, and a rendered image sets ``image_path`` on the row, which is a
    changed-since skip before the delete."""
    from app.models import events
    eid = str(inv.get("id") or "")
    if not eid:
        raise RuntimeError("delete_event without its id")
    with keyed_lock("world_event", eid):
        cur = _event_row_strict(eid)
        if cur is None:
            raise _Skip(REASON_GONE)
        written = entry.get("written")
        if written is not None and _norm(cur) != _norm(written):
            b, _w = diff_keys(written, cur)
            raise _Skip(REASON_CHANGED, keys=sorted(b))
        events.delete_event(eid)
        if _event_row_strict(eid) is not None:
            raise _Skip(REASON_REFUSED)
    return []


def _quest_template_changed(cur: Dict[str, Any], written: Optional[Dict[str, Any]]
                            ) -> Optional[List[str]]:
    """Why a quest template the run created may not go any more, as the skip
    keys, or None: its revision moved on (an admin edit — every editable key
    goes through ``update_template``, which raises the revision) -> ["revision"];
    a run of it exists (open or ended — the run's snapshot names the template
    id) -> ["runs"]. Shared by the undo and :func:`discard_preview`."""
    from app.models import quests
    if written is not None and int(cur.get("revision") or 0) != int(written.get("revision") or 0):
        return ["revision"]
    if quests.count_runs(quests.RUN_OPEN_STATES + quests.RUN_ENDED_STATES,
                         template_id=str(cur.get("id") or "")) > 0:
        return ["runs"]
    return None


def _undo_delete_quest_template(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Reverse create_quest_template: under ``keyed_lock("quest_template", id)``
    (the template writers' own lock, re-entrant for ``delete_template``) the
    template gone -> already gone; edited since or run -> changed since
    (:func:`_quest_template_changed`); else the one row is deleted by id."""
    from app.models import quests
    qid = str(inv.get("id") or "")
    if not qid:
        raise RuntimeError("delete_quest_template without its id")
    with keyed_lock("quest_template", qid):
        cur = quests.get_template(qid)
        if cur is None:
            raise _Skip(REASON_GONE)
        keys = _quest_template_changed(cur, entry.get("written"))
        if keys:
            raise _Skip(REASON_CHANGED, keys=keys)
        quests.delete_template(qid)
        if quests.get_template(qid) is not None:
            raise _Skip(REASON_REFUSED)
    return []


def _undo_restore_placement(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """place_character: the placement is ONE unit. Under the profile lock the
    stored placement (the five profile keys and the position as one key
    ``pos``) is compared with what the step wrote; all equal -> the ``before``
    placement is written back through ``character.write_placement``; any key
    differs -> nothing of it is written (restoring some keys could leave a
    room that is not in the location), skipped ``changed since`` with the
    differing keys. A pending entry (no ``written``) is restored
    unconditionally. The known place the step added goes with an applied
    restore; with a skipped one it goes only when the character no longer
    stands in the placed location — whoever stands there must know it (the
    rule of save_character_current_location), so it is KEPT and named in the
    same skip (key ``known_places``).

    A character place_character would refuse outright now
    (``world_dev_tools._placeable_refusal``: a player took it over, it left
    the world …) is skipped ``changed since`` with the key ``state`` even
    when the six match. When the step INSERTed the ``character_state`` row
    (``before.row`` False), an applied restore removes it again through
    ``character.drop_bare_placement_row`` — kept only when someone else has
    written into it meanwhile.

    Accepted residual: the applied path does not ask the runtime states of
    ``_placement_state_refusal`` (asleep, seated, a journey, a party …). A
    state that began after the placement and left all six untouched does not
    stop the restore — the run keeps the world frozen, so nothing but a
    player or an admin can start one meanwhile."""
    from app.core.world_dev_tools import _placeable_refusal
    from app.models.character import (PLACEMENT_KEYS, character_row_exists,
                                      drop_bare_placement_row, read_placement,
                                      write_placement)
    name = str(inv.get("name") or "")
    before = inv.get("before") or {}
    written = entry.get("written")
    added = [str(i) for i in inv.get("known_added") or [] if i]
    remove = {"op": "remove_known_places", "name": name, "ids": added,
              "had_key": bool(inv.get("had_known_key"))}
    with keyed_lock("character_profile", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        if written is None:
            changed: List[str] = []
        else:
            cur = _norm(read_placement(name))
            want = _norm(written.get("placement") or {})
            changed = [k for k in PLACEMENT_KEYS
                       if (cur.get("profile") or {}).get(k)
                       != (want.get("profile") or {}).get(k)]
            if cur.get("pos") != want.get("pos"):
                changed.append("pos")
        if not changed and _placeable_refusal(name):
            changed = ["state"]
        if not changed:
            if not write_placement(name, dict(before.get("profile") or {}),
                                   before.get("pos")):
                raise RuntimeError(f"restoring the placement of {name} was not stored")
            if before.get("row") is False:
                drop_bare_placement_row(name)
            _undo_remove_known_places(entry, remove)
            return []
        placed = ((written or {}).get("placement") or {}).get("profile") or {}
        now = (read_placement(name).get("profile") or {}).get("current_location")
        if added and now == placed.get("current_location"):
            raise _Skip(REASON_CHANGED, keys=changed + ["known_places"])
        _undo_remove_known_places(entry, remove)
    raise _Skip(REASON_CHANGED, keys=changed)


def _undo_restore_skill_config(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """set_skill: under ``keyed_lock("skill_config", name)`` the file's current
    raw text is compared with the text the step wrote; a difference is
    ``changed since`` (keys [skill]) and nothing is written. Otherwise the
    ``before`` text is written back VERBATIM
    (``character.write_character_skill_config_text``), or — before ABSENT —
    the file is removed, and with it the ``skills/`` directory when it did
    not exist before the step (``had_dir`` False) and is empty now. A
    pending entry (no ``written``) is restored unconditionally. Character
    gone -> already gone."""
    from app.models.character import (character_row_exists,
                                      read_character_skill_config_text,
                                      remove_character_skill_config,
                                      write_character_skill_config_text)
    name = str(inv.get("name") or "")
    skill = str(inv.get("skill") or "")
    before = inv.get("before", ABSENT)
    written = entry.get("written")
    with keyed_lock("skill_config", name):
        if not name or not character_row_exists(name):
            raise _Skip(REASON_GONE)
        if not skill:
            raise RuntimeError("restore_skill_config without its skill")
        if written is not None:
            try:
                now = read_character_skill_config_text(name, skill)
            except UnicodeDecodeError:
                now = None
            if now != written:
                raise _Skip(REASON_CHANGED, keys=[skill])
        if before is None or is_absent(before):
            if not remove_character_skill_config(name, skill,
                                                 drop_empty_dir=not inv.get("had_dir")):
                raise RuntimeError(f"the skill config {skill} of {name} was not removed")
        elif not write_character_skill_config_text(name, skill, str(before)):
            raise RuntimeError(f"the skill config {skill} of {name} was not restored")
    return []


def simulated_places(entries: List[Dict[str, Any]], foreign: set
                     ) -> Dict[str, Tuple[str, str]]:
    """For :func:`discard_preview`: ``{name: (location, room)}`` of the roster
    as the undo leaves it — ``list_character_places()``, then the run's
    not-undone ``restore_placement`` entries walked newest-first the way
    :func:`_undo_restore_placement` decides: an entry whose written placement
    equals the SIMULATED placement of that character (all five keys and the
    position — not the stored one, so two chained placements unwind step by
    step) moves it to its ``before`` placement; a pending entry does so
    unconditionally; one that does not match, or whose character
    ``world_dev_tools._placeable_refusal`` refuses now, leaves it (changed
    since)."""
    from app.core.world_dev_tools import _placeable_refusal
    from app.models.character import list_character_places, read_placement
    places = dict(list_character_places())
    sims: Dict[str, Dict[str, Any]] = {}
    for entry in entries:  # newest-first, as undo() walks them
        inv = entry.get("inverse") or {}
        if inv.get("op") != "restore_placement":
            continue
        name = str(inv.get("name") or "")
        if not name or ("character", name) in foreign or name not in places:
            continue
        if name not in sims:
            sims[name] = _norm(read_placement(name))
        written = entry.get("written")
        want = _norm(written.get("placement") or {}) if written is not None else None
        if want is not None and (want.get("profile"), want.get("pos")) != (
                sims[name].get("profile"), sims[name].get("pos")):
            continue
        if _placeable_refusal(name):
            continue
        sims[name] = _norm(inv.get("before") or {})
        prof = sims[name].get("profile") or {}
        loc, room = prof.get("current_location"), prof.get("current_room")
        places[name] = (loc if isinstance(loc, str) else "",
                        room if isinstance(room, str) else "")
    return places



# ── The lane's hairstyle (world_dev_media.make_hairstyle) ────────────────

def _hairstyle_key_names() -> Tuple[str, str]:
    from app.core.garment_hair import BASE_HAIRSTYLE_KEY
    return (BASE_HAIRSTYLE_KEY, "equipped_mesh_pieces")


def _references(value: Any, item_id: str) -> bool:
    """Whether a hairstyle key's value names the item (the plain body's id,
    or a slot of ``equipped_mesh_pieces``)."""
    if isinstance(value, dict) and not is_absent(value):
        return any(v == item_id for v in value.values())
    return value == item_id


def _hairstyle_pending_value(key: str, before: Dict[str, Any], item_id: str) -> Any:
    """What ``garment_hair._claim_first`` writes into ``key`` for a first
    hairstyle ``item_id`` when the profile held ``before``: the plain body's
    id = the item; ``equipped_mesh_pieces`` = the previous dict (or {}) with
    "hair" = the item. Used for a pending row, which recorded no written keys."""
    from app.core.garment_hair import BASE_HAIRSTYLE_KEY, HAIR_KIND
    if key == BASE_HAIRSTYLE_KEY:
        return item_id
    prev = before.get(key, ABSENT)
    worn = dict(prev) if isinstance(prev, dict) and not is_absent(prev) else {}
    worn[HAIR_KIND] = item_id
    return worn


def _hairstyle_decision(entry: Dict[str, Any], inv: Dict[str, Any],
                        now: Optional[Dict[str, Any]],
                        item_now: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the undo of a ``remove_hairstyle`` row does — ONE decision for
    :func:`_undo_remove_hairstyle` and the discard preview. ``now`` = the two
    keys as stored (value or ABSENT), None when the character is gone;
    ``item_now`` = :func:`item_row` of the hairstyle. Returns ``{"restore": {key:
    before}, "changed": [keys], "item": "delete" | "gone" | "kept", "item_keys":
    [keys]}``: a key equal to what the step wrote goes back to ``before``, a
    differing one is left alone (changed); the item is
    deleted when its row still equals what the step wrote (a pending row: when
    it exists) AND no key left unrestored still names it — else kept, with the
    naming keys (or ["item"] for an edited row).

    A PENDING row (``ensure_hairstyle`` minted the item, then raised; the id
    was attached, nothing was recorded as written) does not restore blindly:
    the step may have stopped before or after its profile write, so a key
    goes back to ``before`` only while it equals ``before`` itself or the
    value the step would have written (:func:`_hairstyle_pending_value` —
    ``_claim_first``'s write: base = the item, worn = before plus "hair" =
    the item); anything else is a hand edit since and is left alone
    (changed), exactly like a written row."""
    iid = str(inv.get("item_id") or "")
    written = entry.get("written") if isinstance(entry.get("written"), dict) else None
    wkeys = written.get("keys") if written is not None else None
    before = inv.get("before") or {}
    restore: Dict[str, Any] = {}
    changed: List[str] = []
    for key in _hairstyle_key_names() if now is not None else ():
        cur = now.get(key, ABSENT)
        if isinstance(wkeys, dict):
            ours = [wkeys.get(key, ABSENT)]
        else:
            ours = [before.get(key, ABSENT), _hairstyle_pending_value(key, before, iid)]
        if any(_norm(cur) == _norm(v) for v in ours):
            restore[key] = before.get(key, ABSENT)
        else:
            changed.append(key)
    if item_now is None:
        return {"restore": restore, "changed": changed, "item": "gone", "item_keys": []}
    if written is not None and _norm(item_now) != _norm(written.get("item")):
        return {"restore": restore, "changed": changed, "item": "kept", "item_keys": ["item"]}
    naming = [k for k in changed if _references((now or {}).get(k, ABSENT), iid)]
    return {"restore": restore, "changed": changed,
            "item": "kept" if naming else "delete", "item_keys": naming}


def _undo_remove_hairstyle(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    """Reverse the lane's hairstyle (``make_hairstyle``) under ``garment_item`` ->
    ``character_profile`` (the order every hairstyle writer takes): the two keys
    still equal to what the step wrote go back to ``before`` (ABSENT removes),
    differing ones are skipped ``changed since`` (those keys); then the item is
    deleted through the public deleter ``hairstyle_delete.delete_hairstyle`` when
    :func:`_hairstyle_decision` says so (``HairstyleBusy`` -> ``changed since``
    keys ["busy"], an item no longer the character's -> ``already gone``), else
    ``changed since`` with the keys still naming it (it would otherwise clear
    values the handler just left alone). Item gone -> ``already gone``. A
    pending row without an item id -> ``not written``.

    Side effect, documented: a restored key that named the item (the hair was
    worn / the plain body's) is an outfit change of the character —
    ``garment_assembly.schedule`` and ``figure_build.request(name,
    "outfit_change")`` are called after the locks, the same calls
    ``delete_hairstyle`` makes when it unclaims a worn hairstyle (it finds the
    keys restored already). During a Discard both are still deferred
    (``release_all`` runs after the undo) and recorded as suppressed; they are
    replayed for characters that still exist, so a pre-existing character's
    figure is rebuilt to its restored, hair-less state through the ordinary
    path, and a character the same undo deletes has nothing to replay."""
    from app.core import hairstyle_delete
    from app.core.world_dev_tools import _template_fields
    from app.models.character import (_STATE_META_KEYS, character_row_exists,
                                      get_character_profile, remove_state_meta_key,
                                      save_character_profile)
    name = str(inv.get("name") or "")
    iid = str(inv.get("item_id") or "")
    if not iid:
        raise _Skip(REASON_NOT_WRITTEN)
    skips: List[_Skip] = []
    released = False
    with keyed_lock("garment_item", name), keyed_lock("character_profile", name):
        exists = bool(name) and character_row_exists(name)
        prof = (get_character_profile(name) or {}) if exists else {}
        now = ({k: (copy.deepcopy(prof[k]) if k in prof else ABSENT)
                for k in _hairstyle_key_names()} if exists else None)
        plan = _hairstyle_decision(entry, inv, now, item_row(iid))
        apply = {k: v for k, v in plan["restore"].items() if _norm(now[k]) != _norm(v)}
        if apply:
            for key, value in apply.items():
                if is_absent(value):
                    prof.pop(key, None)
                else:
                    prof[key] = copy.deepcopy(value)
            # Soul values are injected on read; they never go back through a
            # profile save.
            for key, field in _template_fields(str(prof.get("template") or "")).items():
                if field.get("source_file"):
                    prof.pop(key, None)
            if not save_character_profile(name, prof):
                raise RuntimeError(f"could not save the profile of {name}")
            # equipped_mesh_pieces lives in character_state.meta, which a
            # profile save merges: leaving the key out does not remove it.
            for key, value in apply.items():
                if (is_absent(value) and key in _STATE_META_KEYS
                        and not remove_state_meta_key(name, key)):
                    raise RuntimeError(f"{key} of {name} was not removed")
            released = any(_references(now[k], iid) for k in apply)
        if plan["changed"]:
            skips.append(_Skip(REASON_CHANGED, keys=list(plan["changed"])))
        if plan["item"] == "gone":
            skips.append(_Skip(REASON_GONE, hairstyle=iid))
        elif plan["item"] == "kept":
            skips.append(_Skip(REASON_CHANGED, keys=list(plan["item_keys"]), hairstyle=iid))
        else:
            try:
                hairstyle_delete.delete_hairstyle(name, iid)
            except hairstyle_delete.HairstyleBusy as e:
                skips.append(_Skip(REASON_CHANGED, keys=["busy"], hairstyle=iid, error=str(e)))
            except LookupError:
                skips.append(_Skip(REASON_GONE, hairstyle=iid))
    if released:
        try:
            from app.core import garment_assembly
            garment_assembly.schedule(name)
        except Exception as e:  # noqa: BLE001 — the restored profile stands
            logger.warning("world-dev undo: garment assembly schedule for %s failed: %s", name, e)
        try:
            from app.core import figure_build
            figure_build.request(name, "outfit_change")
        except Exception as e:  # noqa: BLE001 — the restored profile stands
            logger.warning("world-dev undo: Build request for %s failed: %s", name, e)
    return skips


def _hairstyle_preview_lines(entries: List[Dict[str, Any]], deleted: set) -> List[str]:
    """The discard lines of the run's ``remove_hairstyle`` rows, decided by
    :func:`_hairstyle_decision` (the handler's own decision): a hairstyle the
    undo deletes is ``hairstyle <id> of "<name>"`` — no line when the character
    itself goes (DELETED; the handler, reached first, deletes the item); keys
    left alone are one "<keys> was changed since — the discard leaves it
    alone" line; an item kept is one "was changed since — the discard leaves it
    alone" line. A pending row without an item id, or an item already gone,
    gets no line. Oldest line first."""
    from app.models.character import character_row_exists, get_character_profile
    lines: List[str] = []
    for entry in entries:  # newest-first
        inv = entry.get("inverse") or {}
        if inv.get("op") != "remove_hairstyle" or not inv.get("item_id"):
            continue
        name = str(inv.get("name") or "")
        iid = str(inv["item_id"])
        now = None
        if name and character_row_exists(name):
            prof = get_character_profile(name) or {}
            now = {k: (prof[k] if k in prof else ABSENT) for k in _hairstyle_key_names()}
        plan = _hairstyle_decision(entry, inv, now, item_row(iid))
        head = f'hairstyle {iid} of "{name}"'
        out: List[str] = []
        if plan["changed"]:
            out.append(f"{head}: {', '.join(plan['changed'])} was changed since — the discard "
                       "leaves it alone")
        if plan["item"] == "kept":
            out.append(f"{head} was changed since — the discard leaves it alone")
        elif plan["item"] == "delete" and name not in deleted:
            out.append(head)
        lines.extend(reversed(out))
    lines.reverse()
    return lines


_HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], List[_Skip]]] = {
    "delete_location": _undo_delete_location,
    "restore_location": _undo_restore_location,
    "restore_position": _undo_restore_position,
    "delete_terrain_area": _undo_delete_terrain_area,
    "restore_terrain_area": _undo_restore_terrain_area,
    "delete_height_area": _undo_delete_height_area,
    "restore_height_area": _undo_restore_height_area,
    "delete_character": _undo_delete_character,
    "restore_character": _undo_restore_character,
    "restore_soul": _undo_restore_soul,
    "restore_home_schedule": _undo_restore_home_schedule,
    "restore_body_slots": _undo_restore_body_slots,
    "restore_status_effects": _undo_restore_status_effects,
    "remove_known_places": _undo_remove_known_places,
    "remove_outfits": _undo_remove_outfits,
    "recreate_location": _undo_recreate_location,
    "recreate_terrain_area": _undo_recreate_terrain_area,
    "recreate_height_area": _undo_recreate_height_area,
    "recreate_character": _undo_recreate_character,
    "delete_world_prop": _undo_delete_world_prop,
    "recreate_world_prop": _undo_recreate_world_prop,
    "delete_terrain_type": _undo_delete_terrain_type,
    "recreate_terrain_type": _undo_recreate_terrain_type,
    "delete_items": _undo_delete_items,
    "restore_inventory": _undo_restore_inventory,
    "restore_room_items": _undo_restore_room_items,
    "restore_address": _undo_restore_address,
    "delete_secret": _undo_delete_secret,
    "delete_rule": _undo_delete_rule,
    "delete_event": _undo_delete_event,
    "delete_quest_template": _undo_delete_quest_template,
    "restore_placement": _undo_restore_placement,
    "restore_skill_config": _undo_restore_skill_config,
    "remove_hairstyle": _undo_remove_hairstyle,
}


def _skip_dict(entry: Dict[str, Any], skip: _Skip) -> Dict[str, Any]:
    line = entry.get("line") or (
        f"{entry.get('tool') or ''} {entry.get('target_id') or ''}".strip())
    out = {"seq": int(entry["seq"]), "line": line, "reason": skip.reason}
    out.update(skip.extra)
    return out


def apply_inverse(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute ONE journal entry's inverse, without journal bookkeeping.
    Returns the skip records (empty = fully reversed); raises on a real
    failure."""
    inv = entry.get("inverse") or {}
    handler = _HANDLERS.get(str(inv.get("op") or ""))
    if handler is None:
        return [_skip_dict(entry, _Skip(f"unknown inverse op {inv.get('op')!r}"))]
    try:
        return [_skip_dict(entry, s) for s in handler(entry, inv)]
    except _Skip as s:
        return [_skip_dict(entry, s)]


#: Inverse ops whose undo can fail on a read error while their row stays
#: standing (the discard preview's "cannot be read" kinds). A step of these
#: whose undo RAISED is not marked undone: the row still exists, so it stays
#: in later previews and the next undo (the final discard after a turn
#: rollback) tries it again — their handlers compare with ``written`` and are
#: safe to repeat. While it stands it HOLDS the places and characters its
#: written row names (:func:`held_names`): their creating delete in the same
#: pass is skipped with :data:`REASON_HELD` and stays in the journal too,
#: never leaving the row naming a missing place or character.
_HOLDING_OPS = frozenset({"delete_secret", "delete_rule", "delete_event"})

#: Reason (behind it: the steps that hold it) of a delete_location /
#: delete_character skipped because a rule, secret or event whose undo failed
#: in the same pass still names the place or character.
REASON_HELD = "still named by a step whose undo failed"


def held_names(entry: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The places and characters the row of a holding step (:data:`_HOLDING_OPS`)
    names, from the row as the step WROTE it (the stored one could not be
    read): ``("location", id)`` and ``("character", casefolded name)``. The
    same references the forward delete paths check (``rules.rules_naming``,
    ``secrets.secrets_naming`` without the owner, ``_event_refs``). A step
    without a written row (pending) names nothing."""
    inv = entry.get("inverse") or {}
    op = str(inv.get("op") or "")
    row = entry.get("written")
    if op not in _HOLDING_OPS or not isinstance(row, dict):
        return []
    out: List[Tuple[str, str]] = []

    def place(value: Any) -> None:
        if str(value or "").strip():
            out.append(("location", str(value).strip()))

    def person(value: Any) -> None:
        if str(value or "").strip():
            out.append(("character", str(value).strip().casefold()))

    if op == "delete_rule":
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        place(target.get("location_id") or target.get("location"))
        person(row.get("character"))
        try:
            from app.core.activity_engine import condition_references
            refs = condition_references(str(row.get("condition") or ""))
        except Exception:  # noqa: BLE001 — a condition the parser rejects names nobody
            refs = []
        for fam, tok in refs:
            if fam in ("present", "relationship", "romantic"):
                person(tok)
    elif op == "delete_secret":
        place(row.get("related_location"))
        owner = str(inv.get("owner") or "").strip().casefold()
        for name in list(row.get("known_by") or []) + list(row.get("related_characters") or []):
            if str(name or "").strip().casefold() != owner:
                person(name)
    elif op == "delete_event":
        place(row.get("location_id"))
    return out


def _held_key(inv: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """The key :func:`held_names` would use for the target of a creating
    delete_location / delete_character inverse, or None."""
    op = str(inv.get("op") or "")
    if op == "delete_location" and inv.get("id"):
        return ("location", str(inv.get("id")))
    if op == "delete_character" and str(inv.get("name") or "").strip():
        return ("character", str(inv.get("name")).strip().casefold())
    return None


def _holder_label(inv: Dict[str, Any]) -> str:
    kind = {"delete_rule": "rule", "delete_secret": "secret",
            "delete_event": "event"}.get(str(inv.get("op") or ""), "step")
    return f"{kind} {inv.get('id') or ''}".strip()


# ── Public entry points ──────────────────────────────────────────────────

def undo(run_id: str, turn: Optional[int] = None) -> Dict[str, Any]:
    """Reverse every not-yet-undone WRITE entry of the run (or of one turn)
    newest-first: ``{"reversed": [seq], "skipped": [{"seq", "line",
    "reason", ...}], "complete": bool}``. ``complete`` is True when no
    skip other than ``already gone``, ``not written`` or an occupant record
    happened — the
    target being absent is the desired end state, so it never makes a
    rollback incomplete. An entry counts as reversed when its own target was
    restored or removed; item skips of a deleted character (key ``item``)
    are reported beside it. ``already gone`` is a skip, not an error; an
    exception in one step becomes a skip (``undo failed: ...``) and the rest
    still runs. Every handled entry is marked undone — except a secret,
    rule or event step whose undo raised (its row still stands, it stays in
    later previews and the next undo retries it) and the delete_location /
    delete_character of a place or character that such a step still names
    (skipped with ``still named by a step whose undo failed (...)``, key
    ``held_by``; see :data:`_HOLDING_OPS`). Occupant records of
    characters this undo deleted are dropped at the end, and so are the
    ``item still in use`` records of items a final cleanup pass deletes
    (held only by an older element of the run that the walk removed later).

    A ``re-creation refused`` (e.g. a world prop placed in turn 1, deleted
    by ``delete_created`` in turn 2, its library prop gone since) stays
    incomplete on its own — but when an OLDER creating entry of the same
    target (``delete_*`` inverse) is handled in the same pass, the world
    ends exactly as before the run (absent): the record gets
    ``net_absent: True`` and no longer makes the rollback incomplete."""
    reversed_seqs: List[int] = []
    skipped: List[Dict[str, Any]] = []
    # Targets whose re-creation found a FOREIGN element under the same key:
    # every older entry of that target is skipped too — above all the
    # creating step's delete, which would otherwise remove the foreign one.
    foreign: set = set()
    # Targets whose re-creation the writer refused -> those skip records;
    # an older creating entry of the target in this pass marks them net_absent.
    refused: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    # Places/characters (held_names keys) still named by a holding step whose
    # undo failed in this pass -> labels of those steps.
    held: Dict[Tuple[str, str], List[str]] = {}
    for entry in wr.entries(run_id, turn=turn):
        seq = int(entry["seq"])
        target = _target_of(entry.get("inverse") or {})
        if target is not None and target in foreign:
            skipped.append(_skip_dict(entry, _Skip(REASON_CHANGED,
                                                   keys=["exists again"])))
            wr.mark_undone(run_id, seq)
            continue
        if not entry.get("inverse"):
            if entry.get("state") == "pending":
                skipped.append(_skip_dict(entry, _Skip(REASON_NO_INVERSE)))
            # A done write without inverse (delete_created) has nothing of
            # its own to reverse.
            wr.mark_undone(run_id, seq)
            continue
        inv_now = entry.get("inverse") or {}
        hkey = _held_key(inv_now)
        if hkey is not None and hkey in held:
            # Deleting it would leave the failed step's row naming a missing
            # place/character: skipped, and kept in the journal for a later
            # discard (not marked undone, like the holder).
            skipped.append(_skip_dict(entry, _Skip(
                f"{REASON_HELD} ({', '.join(held[hkey])}) — kept for a later discard",
                held_by=list(held[hkey]))))
            continue
        try:
            skips = apply_inverse(entry)
        except Exception as e:  # noqa: BLE001 — one failed step must not stop the rest
            logger.error("world-dev undo %s#%s failed: %s", run_id, seq, e,
                         exc_info=True)
            skips = [_skip_dict(entry, _Skip(f"undo failed: {e}"))]
            if str(inv_now.get("op") or "") in _HOLDING_OPS:
                # Its row still stands: not marked undone (see _HOLDING_OPS).
                for key in held_names(entry):
                    held.setdefault(key, []).append(_holder_label(inv_now))
                skipped.extend(skips)
                continue
        if not any("item" not in s and "occupant" not in s for s in skips):
            reversed_seqs.append(seq)
        elif (target is not None
              and str((entry.get("inverse") or {}).get("op") or "").startswith("recreate_")
              and any(s.get("reason") == REASON_CHANGED for s in skips)):
            foreign.add(target)
        op = str((entry.get("inverse") or {}).get("op") or "")
        if target is not None:
            if op.startswith("recreate_"):
                refused.setdefault(target, []).extend(
                    s for s in skips if s.get("reason") == REASON_RECREATE_REFUSED)
            elif op.startswith("delete_") and all(
                    s.get("reason") == REASON_GONE for s in skips):
                for s in refused.pop(target, []):
                    s["net_absent"] = True
        skipped.extend(skips)
        wr.mark_undone(run_id, seq)
    # An item the walk reached while an OLDER holder of the run still had it
    # (a place or character created before the item, holding it through a
    # foreign placement or a give changed since) is skipped as in use; the
    # older entry has removed that holder by now. One more cleanup pass
    # deletes what is held nowhere any more and drops its skip record — the
    # end state discard_preview describes (_item_kept_by is order-free).
    retry = sorted({str(s.get("item")) for s in skipped
                    if s.get("reason") == REASON_ITEM_IN_USE and s.get("item")})
    if retry:
        try:
            _cleanup_items(retry)
        except Exception as e:  # noqa: BLE001 — the skip records stay as they are
            logger.error("world-dev undo %s: item cleanup failed: %s", run_id, e,
                         exc_info=True)
        from app.models.inventory import get_item
        gone = {iid for iid in retry if get_item(iid) is None}
        skipped = [s for s in skipped
                   if not (s.get("reason") == REASON_ITEM_IN_USE
                           and str(s.get("item") or "") in gone)]
    if any("occupant" in s for s in skipped):
        # An occupant recorded before an older entry deleted that very
        # character (created before the place) has nobody left to place.
        from app.models.character import character_row_exists
        skipped = [s for s in skipped if "occupant" not in s
                   or character_row_exists(str(s.get("occupant") or ""))]
    logger.info("world-dev undo %s (turn %s): %d reversed, %d skipped",
                run_id, turn, len(reversed_seqs), len(skipped))
    return {"reversed": reversed_seqs, "skipped": skipped,
            "complete": is_complete(skipped)}


#: inverse op -> (target kind, key of the inverse naming the target; a
#: tuple path for a key inside ``row``).
_TARGET_KEYS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "delete_location": ("location", ("id",)),
    "restore_location": ("location", ("id",)),
    "restore_position": ("location", ("id",)),
    "recreate_location": ("location", ("row", "id")),
    "delete_terrain_area": ("terrain", ("id",)),
    "restore_terrain_area": ("terrain", ("row", "id")),
    "recreate_terrain_area": ("terrain", ("row", "id")),
    "delete_height_area": ("height", ("id",)),
    "restore_height_area": ("height", ("row", "id")),
    "recreate_height_area": ("height", ("row", "id")),
    "delete_character": ("character", ("name",)),
    "restore_character": ("character", ("name",)),
    "restore_soul": ("character", ("name",)),
    "restore_home_schedule": ("character", ("name",)),
    "restore_body_slots": ("character", ("name",)),
    "restore_status_effects": ("character", ("name",)),
    "remove_known_places": ("character", ("name",)),
    "remove_outfits": ("character", ("name",)),
    "recreate_character": ("character", ("name",)),
    "delete_world_prop": ("world_prop", ("id",)),
    "recreate_world_prop": ("world_prop", ("row", "id")),
    "delete_terrain_type": ("terrain_type", ("kind",)),
    "recreate_terrain_type": ("terrain_type", ("row", "kind")),
    # A LIST of ids: the target is its first id (create_item journals one).
    "delete_items": ("item", ("ids",)),
    "restore_inventory": ("character", ("name",)),
    "restore_room_items": ("location", ("location_id",)),
    "restore_address": ("relationship", ("pair",)),
    "delete_secret": ("secret", ("id",)),
    "delete_rule": ("rule", ("id",)),
    "delete_event": ("event", ("id",)),
    "delete_quest_template": ("quest_template", ("id",)),
    "restore_placement": ("character", ("name",)),
    "restore_skill_config": ("character", ("name",)),
    "remove_hairstyle": ("character", ("name",)),
}


def _target_of(inv: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    spec = _TARGET_KEYS.get(str(inv.get("op") or ""))
    if spec is None:
        return None
    value: Any = inv
    for key in spec[1]:
        value = value.get(key) if isinstance(value, dict) else None
    if isinstance(value, list):
        value = value[0] if value else None
    return (spec[0], str(value)) if value else None


def is_complete(skipped: List[Dict[str, Any]]) -> bool:
    """True when every skip is ``already gone`` / ``not written``, an
    informational occupant record (key ``occupant``) or a refused
    re-creation of the run's own element (key ``net_absent``), or there is
    none."""
    return all(s.get("reason") in (REASON_GONE, REASON_NOT_WRITTEN)
               or "occupant" in s or s.get("net_absent") for s in skipped or [])


def _exists(target: Tuple[str, str]) -> bool:
    kind, ident = target
    if kind == "location":
        from app.models.world import get_location_by_id
        return get_location_by_id(ident) is not None
    if kind == "terrain":
        from app.models.terrain import get_area
        return get_area(ident) is not None
    if kind == "height":
        return _height_area(ident) is not None
    if kind == "world_prop":
        return world_prop_row(ident) is not None
    if kind == "terrain_type":
        return terrain_type_row(ident) is not None
    if kind == "item":
        return item_row(ident) is not None
    if kind == "relationship":
        from app.models.relationship import pair_row
        return pair_row(*ident.split("|", 1)) is not None
    if kind == "secret":
        from app.models.secrets import secret_exists
        return secret_exists(ident)
    if kind == "rule":
        from app.models.rules import world_rule
        return world_rule(ident) is not None
    if kind == "event":
        from app.models.events import event_exists
        found = event_exists(ident)
        if found is None:
            # A read error is never "absent".
            raise RuntimeError(f"event {ident}: the events table could not be read")
        return found
    if kind == "quest_template":
        from app.models.quests import get_template
        return get_template(ident) is not None
    from app.models.character import character_row_exists
    return character_row_exists(ident)


def _run_cleared_uses(entries: List[Dict[str, Any]], foreign: set
                      ) -> Callable[[Tuple[str, str, str], str], bool]:
    """For :func:`discard_preview`: does the undo itself take a use of a
    terrain kind away before it reaches the kind? The undo walks newest-first
    and first reaches the kind at its NEWEST creating entry
    (``delete_terrain_type``), so only entries NEWER than that one count.
    True for an area or place a newer entry created (it goes), and for one
    whose value, after the newer restore entries are walked back newest-first
    the way the handlers decide (a restore whose written value no longer
    equals the simulated one is skipped as changed since, the next older one
    compares against what is left — so a foreign edit between two run edits
    of one area stops the chain there), no longer names the kind. An
    area or place created BEFORE the kind still exists when the undo reaches
    the kind; only a newer restore can clear its use. Everything else is a
    foreign use."""
    from app.models.terrain import get_area
    from app.models.world import get_location_by_id
    kind_at: Dict[str, int] = {}
    # Per target, newest-first: (index, op, value written, pre-value).
    steps: Dict[Tuple[str, str], List[Tuple[int, str, Any, Any]]] = {}
    for idx, entry in enumerate(entries):  # newest-first
        inv = entry.get("inverse") or {}
        op = str(inv.get("op") or "")
        target = _target_of(inv)
        if target is None or target in foreign:
            continue
        if op == "delete_terrain_type":
            kind_at.setdefault(str(inv.get("kind") or ""), idx)
        elif op in ("delete_terrain_area", "delete_location"):
            steps.setdefault(target, []).append((idx, "created", None, None))
        elif op == "restore_terrain_area":
            steps.setdefault(target, []).append(
                (idx, "restore", entry.get("written"), inv.get("row") or {}))
        elif op == "restore_location" and "terrain" in (inv.get("before") or {}):
            steps.setdefault(target, []).append(
                (idx, "restore", (entry.get("written") or {}).get("terrain"),
                 (inv.get("before") or {}).get("terrain")))

    def uses(row: Any, kind: str) -> bool:
        row = row if isinstance(row, dict) else {}
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        return kind in (str(row.get("kind") or "").strip(),
                        str(meta.get("bed_kind") or "").strip())

    def clears(user: Tuple[str, str, str], kind: str) -> bool:
        target = (user[0], user[1])
        limit = kind_at.get(kind, len(entries))
        newer = [s for s in steps.get(target, ()) if s[0] < limit]
        if any(s[1] == "created" for s in newer):
            return True
        restores = [s for s in newer if s[1] == "restore"]
        if not restores:
            return False
        if user[0] == "terrain":
            value: Any = get_area(user[1])
        else:
            value = (get_location_by_id(user[1]) or {}).get("terrain", ABSENT)
        for _idx, _op, written, before in restores:  # newest-first
            if written is not None and _norm(value) != _norm(written):
                continue  # changed since: the handler skips it
            value = before
        if user[0] == "terrain":
            return not uses(value, kind)
        return is_absent(value) or str(value or "").strip() != kind
    return clears


def _recreated_kind_users(entries: List[Dict[str, Any]], foreign: set,
                          kind: str) -> List[Tuple[str, str, str]]:
    """For :func:`discard_preview`: the uses of a terrain kind that are NOT
    stored now but that the undo brings back before it reaches the kind — a
    foreign area this run deleted (``recreate_terrain_area``, delete_area) in
    an entry NEWER than the kind's newest creating entry. The undo walks
    newest-first: it re-creates the area (absent now, so the re-creation runs),
    walks the area's older restore entries back (one whose ``written`` no
    longer equals the simulated row is skipped: changed since), and then
    reaches the kind, which it skips as in use — unless an older creating
    entry of this run (``delete_terrain_area``) deletes the area again before
    the kind. Same triples as :func:`terrain_kind_users`."""
    limit = next((i for i, e in enumerate(entries)
                  if (e.get("inverse") or {}).get("op") == "delete_terrain_type"
                  and str((e.get("inverse") or {}).get("kind") or "") == kind),
                 len(entries))
    out: List[Tuple[str, str, str]] = []
    seen: set = set()
    for i in range(limit):
        inv = entries[i].get("inverse") or {}
        if inv.get("op") != "recreate_terrain_area":
            continue
        target = _target_of(inv)
        if target is None or target in foreign or target in seen:
            continue
        seen.add(target)
        if _exists(target):
            continue  # stored: counted by terrain_kind_users (or never deleted)
        value: Any = inv.get("row") or {}
        gone = False
        for j in range(i + 1, limit):
            older = entries[j]
            oinv = older.get("inverse") or {}
            if _target_of(oinv) != target:
                continue
            if oinv.get("op") == "delete_terrain_area":
                gone = True
                break
            if oinv.get("op") == "restore_terrain_area":
                written = older.get("written")
                if written is None or _norm(value) == _norm(written):
                    value = oinv.get("row") or {}
        if gone:
            continue
        meta = value.get("meta") if isinstance(value.get("meta"), dict) else {}
        if str(value.get("kind") or "").strip() == kind:
            out.append(("terrain", target[1], f"terrain area {target[1]}"))
        elif str(meta.get("bed_kind") or "").strip() == kind:
            out.append(("terrain", target[1], f"terrain area {target[1]} (its water bed)"))
    return out


def _item_kept_by(iid: str, entries: List[Dict[str, Any]], foreign: set,
                  deleted_names: set, created: Dict[str, str],
                  removed_rooms: Dict[str, Dict[str, str]],
                  sim_places: Optional[Dict[str, Optional[Dict[str, Any]]]] = None
                  ) -> List[str]:
    """Who still holds a created item once the undo has taken back what it
    takes back — simulated the way the handlers decide, newest-first over
    the run's not-undone entries: a character the discard deletes and a
    room of a created place (or one a restore_location removes) let go of
    it; an inventory entry walks back through the run's restore_inventory
    rows of it (one whose entry no longer equals what it wrote is skipped:
    changed since), a room's items through its restore_room_items rows the
    same way. Order does not matter: an item the walk reaches while an OLDER
    holder of the run still has it is deleted by undo()'s final cleanup pass. A target the discard leaves alone (foreign) keeps its holding.
    What remains is the holder list :func:`_cleanup_items` will find."""
    from app.core.db import get_connection
    from app.models.world import list_locations
    kept: List[str] = []
    rows = get_connection().execute(
        "SELECT DISTINCT character_name FROM inventory_items WHERE item_id=?",
        (iid,)).fetchall()
    for holder in sorted(str(r[0] or "").strip() for r in rows):
        if not holder or holder in deleted_names:
            continue
        cur: Any = inventory_entries(holder).get(iid, ABSENT)
        if ("character", holder) not in foreign:
            for entry in entries:
                inv = entry.get("inverse") or {}
                before = inv.get("before") or {}
                if (inv.get("op") != "restore_inventory"
                        or str(inv.get("name") or "") != holder or iid not in before):
                    continue
                written = entry.get("written")
                if (isinstance(written, dict) and iid in written
                        and _norm(cur) != _norm(written[iid])):
                    continue
                if is_absent(cur):
                    continue
                cur = (ABSENT if is_absent(before[iid])
                       else dict(cur, quantity=before[iid]))
        if not is_absent(cur):
            kept.append(f'character "{holder}"')
    for loc in list_locations() or []:
        lid = str(loc.get("id") or "")
        for room in loc.get("rooms") or []:
            if not isinstance(room, dict):
                continue
            rid = str(room.get("id") or "")
            cur = room_items_value(room)
            if iid not in _item_ids(cur) or lid in created or rid in removed_rooms.get(lid, {}):
                continue
            if ("location", lid) not in foreign:
                for entry in entries:
                    inv = entry.get("inverse") or {}
                    if (inv.get("op") != "restore_room_items"
                            or str(inv.get("location_id") or "") != lid
                            or str(inv.get("room_id") or "") != rid):
                        continue
                    written = entry.get("written")
                    if written is not None and _norm(cur) != _norm(written):
                        continue
                    cur = inv.get("before", ABSENT)
            if iid in _item_ids(cur):
                kept.append(f'room {rid} "{room.get("name") or rid}" of location {lid}')
    # A place naming it as its knowledge item (as the undo leaves the place:
    # sim_places holds the run's restore_location rows walked back) — a
    # created place goes with the discard.
    sims = sim_places or {}
    places = [sims[str(loc.get("id") or "")] if str(loc.get("id") or "") in sims else loc
              for loc in list_locations() or []]
    for loc in _knowledge_holders(iid, [p for p in places if p]):
        lid = str(loc.get("id") or "")
        if lid not in created:
            kept.append(f'location {lid} "{loc.get("name") or lid}" (its knowledge item)')
    return kept


def _run_removed_rooms(entries: List[Dict[str, Any]], foreign: set
                       ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Optional[Dict[str, Any]]]]:
    """For :func:`discard_preview`: ``({location id: {room id: name}},
    {location id: simulated row})`` — the rooms the undo's restore_location
    rows really take away, and each touched place as the undo leaves it. Simulated
    the way the handlers decide, newest-first over the run's not-undone
    entries on a copy of each place: a restore_room_items row puts its
    room's items back when they still equal what it wrote
    (:func:`_undo_restore_room_items`), and a restore_location restores only
    the keys whose current value equals what it wrote (:func:`_split_keys`,
    as :func:`_undo_restore_location` does) — a rooms / map3d key changed
    since (a foreign edit, e.g. an item laid into a room the run added)
    removes nothing. The removal itself is simulated with the writer's
    corridor sync (``world_dev_tools._rooms_removed_by``)."""
    from app.core.world_dev_tools import _rooms_removed_by
    from app.models.world import get_location_by_id
    sims: Dict[str, Optional[Dict[str, Any]]] = {}
    removed: Dict[str, Dict[str, str]] = {}
    for entry in entries:  # newest-first, as undo() walks them
        inv = entry.get("inverse") or {}
        op = inv.get("op")
        if op == "restore_location":
            lid = str(inv.get("id") or "")
        elif op == "restore_room_items":
            lid = str(inv.get("location_id") or "")
        else:
            continue
        if not lid or ("location", lid) in foreign:
            continue
        if lid not in sims:
            sims[lid] = copy.deepcopy(get_location_by_id(lid))
        cur = sims[lid]
        if not cur:
            continue
        written = entry.get("written")
        if op == "restore_room_items":
            rid = str(inv.get("room_id") or "")
            room = next((r for r in cur.get("rooms") or []
                         if isinstance(r, dict) and r.get("id") == rid), None)
            if room is None or (written is not None
                                and _norm(room_items_value(room)) != _norm(written)):
                continue
            before = inv.get("before", ABSENT)
            if is_absent(before):
                room.pop("items", None)
            else:
                room["items"] = copy.deepcopy(before)
            continue
        restore, _changed = _split_keys(inv.get("before") or {}, written, cur)
        if "rooms" in restore or "map3d" in restore:
            b_rooms = restore.get("rooms", ABSENT)
            b_map3d = restore.get("map3d", ABSENT)
            new_rooms = (None if "rooms" not in restore
                         else [] if is_absent(b_rooms) else list(b_rooms or []))
            new_map3d = (None if "map3d" not in restore or is_absent(b_map3d)
                         else b_map3d)
            for room in _rooms_removed_by(cur, new_rooms, new_map3d):
                rid = str(room.get("id") or "")
                removed.setdefault(lid, {})[rid] = str(room.get("name") or rid)
        _apply_keys(cur, restore)
    return removed, sims


class _OrderSim:
    """The discard preview's model of the area rowids, so it can say up front
    which re-created area _check_order will report as an inexact paint order.
    It applies terrain.order_tie_rule (and sqlite's: an insert without a
    rowid takes the largest one + 1) to the rows as the undo, walking
    newest-first, will find them — areas the undo deleted or re-created
    before included."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Tuple[int, str, Optional[int]]]] = {}

    def _table(self, kind: str) -> Dict[str, Tuple[int, str, Optional[int]]]:
        if kind not in self.rows:
            if kind == "terrain":
                from app.models.terrain import area_order_rows
                self.rows[kind] = {r["id"]: (r["rowid"], r["created_at"], r["z_order"])
                                   for r in area_order_rows()}
            else:
                from app.models.heightfield import height_area_order_rows
                self.rows[kind] = {r["id"]: (r["rowid"], r["created_at"], None)
                                   for r in height_area_order_rows()}
        return self.rows[kind]

    def delete(self, kind: str, aid: str) -> None:
        self._table(kind).pop(aid, None)

    def recreate(self, kind: str, aid: str, order: Any, z: Optional[int]) -> bool:
        """Re-insert ``aid`` the way restore_area would; True = exact order."""
        rows = self._table(kind)
        known = isinstance(order, dict)
        old = order.get("rowid") if known else None
        # An entry without `order` is stamped "now": it ties with nothing.
        created = str(order.get("created_at") or "") if known else "\uffff"
        from app.models.terrain import order_tie_rule
        used = {v[0] for k, v in rows.items() if k != aid}
        if known and isinstance(old, int) and old not in used:
            new = old
        else:
            new = max(used, default=0) + 1
        sibs = [(k, v[0]) for k, v in rows.items()
                if k != aid and v[1] == created and (z is None or v[2] == z)]
        tie = order_tie_rule(sibs, order if known else {}, new)
        rows[aid] = (new, created, z)
        return known and not tie


def _order_preview_line(sim: _OrderSim, op: str, inv: Dict[str, Any]) -> Optional[str]:
    """The line for a deleted area the discard re-creates but cannot put back
    at its old place in the paint order — what _check_order will report."""
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    if op == "recreate_terrain_area":
        try:
            z = int(row.get("z_order") or 0)
        except (TypeError, ValueError):
            z = 0
        exact, label = sim.recreate("terrain", aid, inv.get("order"), z), "terrain area"
    elif op == "recreate_height_area":
        exact, label = sim.recreate("height", aid, inv.get("order"), None), "height area"
    else:
        return None
    if exact:
        return None
    return f"{label} {aid} comes back, but not at its old place in the paint order"


def _address_preview_lines(entries: List[Dict[str, Any]]) -> List[str]:
    """The discard lines of the run's ``restore_address`` entries, decided
    the way :func:`_undo_restore_address` decides them: newest-first over a
    SIMULATED pair row per pair (the real one first). Row gone -> nothing.
    The key differs from what the step wrote -> "was changed since" (the
    undo skips it). A row the step created that is, apart from the key, the
    row it wrote -> it goes (one line); the rest changed -> "was changed
    since", the key is cleared and the row stays. Otherwise the key gets its
    before value back (a raw restore writes back the before row exactly; the
    key alone stands in for it here — no other key of a row is compared
    except by a creating entry, whose row the later steps' raw restores
    bring back to what it wrote). When the undo takes its key-only branch
    (the rest of a row that existed changed since), the meta keys the step
    added go from the simulated row as the undo pops them; one left -> one
    "was changed since" line. Oldest line first."""
    from app.models import relationship as rel
    lines: List[str] = []
    sim: Dict[str, Optional[Dict[str, Any]]] = {}
    for entry in entries:  # newest-first
        inv = entry.get("inverse") or {}
        if inv.get("op") != "restore_address":
            continue
        speaker = str(inv.get("speaker") or "")
        addressee = str(inv.get("addressee") or "")
        key = str(inv.get("key") or "")
        if not speaker or not addressee or not key:
            continue
        pair = rel.pair_key(speaker, addressee)
        if pair not in sim:
            sim[pair] = rel.pair_row(speaker, addressee)
        row = sim[pair]
        if row is None:
            continue
        written = entry.get("written")
        if isinstance(written, dict) and (_norm(row.get(key, ABSENT))
                                          != _norm(written.get("value", ABSENT))):
            lines.append(f"form of address {speaker} → {addressee} was changed "
                         "since — the discard leaves it alone")
            continue
        wrow = written.get("row") if isinstance(written, dict) else None

        def rest(r: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in r.items() if k != key}
        if inv.get("row_created"):
            if wrow is None or _norm(rest(row)) == _norm(rest(wrow)):
                lines.append(f"form of address {pair} (created by the run)")
                sim[pair] = None
            else:
                lines.append(f"form of address {pair}: the relationship row was "
                             "changed since — the discard clears "
                             f"{speaker} → {addressee} and leaves the row")
                sim[pair] = rest(row)
            continue
        before = inv.get("before", ABSENT)
        new = rest(row) if is_absent(before) else {**row, key: before}
        if isinstance(written, dict):
            own = wrow is not None and _norm(rest(row)) == _norm(rest(wrow))
        else:
            own = ("text" in inv and _norm(row.get(key, ABSENT))
                   == _norm(inv.get("text") or ABSENT))
        raw = inv.get("raw")
        if not (own and isinstance(raw, dict) and row.get("_db_id") == inv.get("row_id")):
            # The undo's key-only branch: the step's own added meta keys go
            # while they hold what it wrote; any left -> changed since.
            added = _address_added_keys(raw, wrow, key) if isinstance(written, dict) else {}
            left = added is None
            for k, v in (added or {}).items():
                if (k not in rel._CONTENT_KEYS and k in new
                        and _norm(new[k]) == _norm(v)):
                    new.pop(k)
                if k in new:
                    left = True
            if left:
                lines.append(f"form of address {speaker} → {addressee}: the relationship "
                             "row was changed since — the discard puts the form of address "
                             "back and leaves the rest of the row")
        sim[pair] = new
    lines.reverse()
    return lines


def _skill_preview_lines(entries: List[Dict[str, Any]], deleted: set) -> List[str]:
    """The discard lines of the run's ``restore_skill_config`` entries,
    decided the way :func:`_undo_restore_skill_config` decides them:
    newest-first over a SIMULATED file text per (character, skill), the real
    one first. A text that differs from what the step wrote -> one "was
    changed since — the discard leaves it alone" line (the undo skips it);
    otherwise the simulated text becomes the entry's ``before``. A switch put
    back is no line (nothing goes). A character that is gone, or that the
    discard deletes itself (DELETED), gets no line. Oldest line first."""
    from app.models.character import (character_row_exists,
                                      read_character_skill_config_text)
    lines: List[str] = []
    sim: Dict[Tuple[str, str], Optional[str]] = {}
    for entry in entries:  # newest-first
        inv = entry.get("inverse") or {}
        if inv.get("op") != "restore_skill_config":
            continue
        name = str(inv.get("name") or "")
        skill = str(inv.get("skill") or "")
        if not name or not skill or name in deleted or not character_row_exists(name):
            continue
        key = (name, skill)
        if key not in sim:
            try:
                sim[key] = read_character_skill_config_text(name, skill)
            except UnicodeDecodeError:
                sim[key] = None
        written = entry.get("written")
        if written is not None and sim[key] != written:
            lines.append(f"{name}: skill {skill} was changed since — the discard "
                         "leaves it alone")
            continue
        before = inv.get("before", ABSENT)
        sim[key] = None if before is None or is_absent(before) else str(before)
    lines.reverse()
    return lines


#: Kinds whose discard_preview branch turns a read error into a line
#: ("... cannot be read; the discard will report it") instead of raising —
#: the same error the undo handler reports as "undo failed".
_READ_ERROR_LINE_KINDS = frozenset({"secret", "rule", "event"})


def _preview_held(entries: List[Dict[str, Any]], foreign: set
                  ) -> Dict[Tuple[str, str], List[str]]:
    """What undo() will hold back (:data:`_HOLDING_OPS`): per
    :func:`held_names` key, the labels of the run's secret / rule / event
    steps whose row cannot be read now — the read the undo handler makes
    first, so its undo will fail the same way."""
    from app.models import rules
    held: Dict[Tuple[str, str], List[str]] = {}
    for entry in entries:
        inv = entry.get("inverse") or {}
        op = str(inv.get("op") or "")
        if op not in _HOLDING_OPS or _target_of(inv) in foreign:
            continue
        ident = str(inv.get("id") or "")
        try:
            if op == "delete_secret":
                owner = str(inv.get("owner") or "")
                if owner and ident:
                    secret_row(owner, ident)
            elif op == "delete_rule":
                if ident:
                    rules.world_rule(ident)
            elif ident:
                _event_row_strict(ident)
        except Exception:  # noqa: BLE001 — the undo reports it as "undo failed"
            for key in held_names(entry):
                held.setdefault(key, []).append(_holder_label(inv))
    return held


def discard_preview(run_id: str) -> List[str]:
    """One line per element the run created that still exists (oldest
    first); a created character also names its chat rows and the other
    characters' memory rows that mention it — they go with it. Then one line
    per character standing in a created place, or in a room a
    ``restore_location`` would take away (simulated with the writer's
    corridor sync): it stays there and has to be placed anew. A character the
    discard deletes itself (one the run created) gets no such line. An
    element the run deleted in a later turn (cross-turn ``delete_created``)
    is re-created and deleted again — net absent, no line; one that exists
    AGAIN is somebody else's: one line, and nothing of that target is
    listed as going — unless a NEWER not-undone creating entry of this run
    owns it (deleted and created again by the run): then it goes, decided
    by the same newest-first walk as :func:`undo`. A created character's
    line also counts the outfit pieces it brought that are still in the
    catalog (", N outfit pieces it brought" — "piece" for 1 — left out at 0).
    A world prop placed by the run and edited by somebody else since (its
    row differs from what the creating step wrote) is left alone by the
    undo (``changed since``): one "was changed since" line, not a going
    line. A terrain kind the run created is listed as
    ``terrain kind <kind> "<name>"``; when an area or place the undo does
    not take away still uses it (see :func:`_run_cleared_uses`) — or a
    deleted area the undo brings back first (:func:`_recreated_kind_users`) —, the line
    says so and that it stays — the undo skips it (changed since, in use).
    A kind changed since is one "was changed since" line, like a world prop.
    An item the run created is listed as ``item <id> "<name>"``; when a
    holder the undo does not take back still has it (:func:`_item_kept_by`),
    the line names the holders and that it stays — the undo skips it (item
    still in use). A deleted area the discard re-creates whose old rowid was
    taken meanwhile by a sibling of the same paint-order stamp gets one
    "comes back, but not at its old place in the paint order" line — the undo
    reports it as inexact (paint order). Forms of address
    (``restore_address``) follow :func:`_address_preview_lines`: a pair row
    the run created and the undo deletes is one going line, a direction or
    row changed since is one "was changed since" line; a key put back on a
    row that existed is no line (nothing goes). A skill switch
    (``restore_skill_config``) whose file changed since is one "was changed
    since" line (:func:`_skill_preview_lines`); one put back is no line. The
    media lane's hairstyle (``remove_hairstyle``) follows
    :func:`_hairstyle_preview_lines`: ``hairstyle <id> of "<name>"`` when the
    undo deletes it (no line when the character itself goes), "was changed
    since — the discard leaves it alone" exactly where the handler skips. A
    secret the run added
    (``delete_secret``) is ``secret <id> of "<owner>" (<category>)``, or one
    "was changed since — the discard leaves it alone" line when it differs
    from what the step wrote (the undo skips it, changed since). A foreign
    sparse secret row of the same mind that the undo's re-save normalises
    (accepted residual, see ``_undo_delete_secret``) is no line — its
    meaning stays. A world block rule the run added (``delete_rule``) is
    ``rule <id> "<name>"``, or one "was changed since — the discard leaves it
    alone" line when its stored row differs from what the step wrote (the
    undo skips it, changed since). An event the run added (``delete_event``) is
    ``event <id> "<text, 60 characters>"``, or one "was changed since — the
    discard leaves it alone" line when its stored row differs from what the
    step wrote; the event writer's cascade (event-bound rules, image files)
    gets no line — a run's own event has neither (only ``random_events``
    binds rules, and an image changes the row, so it is left alone). When the
    rule or the event cannot be read, the line is ``rule <id> — the world
    rules cannot be read; the discard will report it`` / ``event <id> — the
    events cannot be read; the discard will report it`` (the undo handler
    reports the same error as "undo failed"), never an exception; a place
    or character the run created that such an unreadable row names (by the
    row the step wrote, :func:`held_names`) is ``location <id> "<name>" is
    still named by rule <id>, which cannot be read — the discard leaves it``
    (``character "<name>" ...`` likewise): undo() skips it
    (:data:`REASON_HELD`), and both stay in the journal, so a later preview
    still lists them. A quest
    template the run created (``delete_quest_template``) is
    ``quest template <id> "<title>"``, or one "was changed since — the discard
    leaves it alone" line when its revision moved on or a run of it exists
    (:func:`_quest_template_changed`, the undo's own test). The occupant
    lines read where everybody stands once the undo has put the run's
    placements back (:func:`simulated_places`, ``restore_placement``) — a
    character the run placed into a created place or added room gets no line
    unless that placement was changed since (then the undo leaves it there).
    Accepted residual: a run-created location or character
    that ANOTHER session's secret or rule came to name meanwhile
    (``related_location``, ``known_by``, ``related_characters``, a rule's
    target place or ``character``) still goes
    with the discard without a line, and that row keeps a dangling name
    (the tool's own ``delete_created`` refuses in that case; during a run
    the world is frozen, so a foreign secret write is unlikely). Last, the
    run's media (``world_dev_media.media_preview_lines``, Task 9 of plan
    2026-11-25-world-dev-free-media): per element what the discard removes,
    a render still running, and every artefact it keeps (changed since,
    modified and not restored) — the same decision ``remove_run_media``
    takes. The discard removes them BEFORE the journal undo."""
    from app.core.world_dev_tools import _kind_label, _short
    from app.models.character import character_row_exists
    from app.models.chat import count_messages_involving
    from app.models.memory import count_other_memories_naming
    from app.models.terrain import get_area
    from app.models.world import get_location_by_id
    lines: List[str] = []
    created: Dict[str, str] = {}
    removed_rooms: Dict[str, Dict[str, str]] = {}
    deleted_names: set = set()
    entries = wr.entries(run_id)  # newest-first, as undo() walks them
    # `foreign` is decided the way undo() decides it: newest-first over a
    # SIMULATED existence per target, starting from the real one. A creating
    # step (delete_*) the undo reaches first makes the target absent; a done
    # re-creation (recreate_*) that then still finds the target present is
    # somebody else's element (undo: ``changed since``) — the discard
    # leaves it and every older entry of it alone. One that finds it absent
    # re-creates it (and an older creating step deletes it again: net
    # absent). So a character deleted in turn 2 and created AGAIN by this run
    # (a newer creating entry owns the name) is not foreign: it goes.
    foreign: set = set()
    alive: Dict[Tuple[str, str], bool] = {}
    # World props only: the row the simulation holds per target (the real
    # one, or the snapshot a simulated re-creation brings back) — the undo of
    # a creating step compares it with what the step wrote (changed since).
    prop_rows: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
    items_of: Dict[str, set] = {}
    order_sim = _OrderSim()
    for entry in entries:
        inv = entry.get("inverse") or {}
        op = str(inv.get("op") or "")
        target = _target_of(inv)
        if target is None or target in foreign:
            continue
        if target not in alive:
            try:
                alive[target] = _exists(target)
            except Exception:
                if target[0] not in _READ_ERROR_LINE_KINDS:
                    raise
                # No re-creation exists for these kinds, so the simulation
                # needs no real answer: the op branch below reads the row
                # again and turns the error into its "cannot be read" line.
                alive[target] = True
            if target[0] == "world_prop":
                prop_rows[target] = world_prop_row(target[1])
            elif target[0] == "terrain_type":
                prop_rows[target] = terrain_type_row(target[1])
        if op.startswith("recreate_"):
            if not alive[target]:
                alive[target] = True
                line = _order_preview_line(order_sim, op, inv)
                if line:
                    lines.append(line)
                if op in ("recreate_world_prop", "recreate_terrain_type"):
                    prop_rows[target] = inv.get("row")
            elif entry.get("state") == "done":
                foreign.add(target)
                lines.append(f"{_kind_label(target[0])} {target[1]} was deleted by this run and "
                             "exists again — the discard leaves it alone")
            # pending and present: the delete never ran — nothing to do.
        elif op.startswith("delete_"):
            if op == "delete_world_prop" and alive[target]:
                # _undo_delete_world_prop leaves a row edited since alone.
                written = entry.get("written")
                now = prop_rows.get(target)
                if written is not None and _norm(now) != _norm(written):
                    foreign.add(target)
                    lines.append(f"world prop {target[1]} "
                                 f"({(now or {}).get('prop_id')}) was changed since "
                                 "— the discard leaves it alone")
                    continue
            if op == "delete_terrain_type" and alive[target]:
                # _undo_delete_terrain_type leaves a row edited since alone.
                written = entry.get("written")
                now = prop_rows.get(target)
                if written is not None and _norm(now) != _norm(written):
                    foreign.add(target)
                    lines.append(f"terrain kind {target[1]} was changed since "
                                 "— the discard leaves it alone")
                    continue
            if op == "delete_character":
                if (entry.get("state") == "pending" and entry.get("written") is None
                        and not inv.get("claimed")):
                    continue  # nothing written (see _undo_delete_character)
                items_of.setdefault(target[1], set()).update(
                    str(i) for i in inv.get("items") or [] if i)
            if op in ("delete_terrain_area", "delete_height_area") and alive[target]:
                order_sim.delete("terrain" if op == "delete_terrain_area" else "height",
                                 target[1])
            alive[target] = False
    from app.models.inventory import get_item
    clears = _run_cleared_uses(entries, foreign)
    held = _preview_held(entries, foreign)
    listed: set = set()
    item_lines: List[Tuple[int, str, str]] = []
    for entry in reversed(entries):
        inv = entry.get("inverse") or {}
        op = inv.get("op")
        target = _target_of(inv)
        if target in foreign:
            continue
        if op in ("delete_location", "delete_terrain_area", "delete_height_area",
                  "delete_character", "delete_world_prop", "delete_terrain_type",
                  "delete_items", "delete_secret", "delete_rule", "delete_event",
                  "delete_quest_template"):
            # A target created, deleted and created again by this run has
            # several creating entries: one line.
            if target in listed:
                continue
            listed.add(target)
        if op == "delete_location":
            loc = get_location_by_id(str(inv.get("id") or ""))
            hkey = _held_key(inv)
            if loc and hkey in held:
                # undo() skips it (REASON_HELD): it stays, nobody is stranded.
                lines.append(f'location {loc.get("id")} "{loc.get("name") or ""}" is '
                             f"still named by {', '.join(held[hkey])}, which cannot be "
                             "read — the discard leaves it")
            elif loc:
                created[str(loc.get("id"))] = str(loc.get("name") or "")
                lines.append(f'location {loc.get("id")} "{loc.get("name") or ""}"')
        elif op == "delete_terrain_area":
            area = get_area(str(inv.get("id") or ""))
            if area:
                lines.append(f"terrain area {area['id']} ({area.get('kind')})")
        elif op == "delete_height_area":
            area = _height_area(str(inv.get("id") or ""))
            if area:
                lines.append(f"height area {area['id']} ({area.get('height_m')} m)")
        elif op == "delete_world_prop":
            prop = world_prop_row(str(inv.get("id") or ""))
            if prop:
                lines.append(f"world prop {prop['id']} ({prop.get('prop_id')})")
        elif op == "delete_secret":
            sid = str(inv.get("id") or "")
            owner = str(inv.get("owner") or "")
            try:
                srow = secret_row(owner, sid) if owner and sid else None
            except Exception:
                # _undo_delete_secret reports the same read error as
                # "undo failed" and leaves the secret alone.
                lines.append(f'secret {sid} of "{owner}" — its keeper\'s secrets cannot '
                             "be read; the discard will report it")
                srow = None
            if srow:
                written = entry.get("written")
                if written is not None and _norm(srow) != _norm(written):
                    # _undo_delete_secret leaves a secret changed since alone.
                    lines.append(f"secret {sid} was changed since — the discard "
                                 "leaves it alone")
                else:
                    lines.append(f'secret {sid} of "{owner}" ({srow.get("category")})')
        elif op == "delete_rule":
            from app.models import rules
            rid = str(inv.get("id") or "")
            try:
                rrow = rules.world_rule(rid) if rid else None
            except Exception:
                # _undo_delete_rule reports the same read error as
                # "undo failed" and leaves the rule alone.
                lines.append(f"rule {rid} — the world rules cannot be read; "
                             "the discard will report it")
                rrow = None
            if rrow is not None:
                written = entry.get("written")
                if written is not None and _norm(rrow) != _norm(written):
                    # _undo_delete_rule leaves a rule changed since alone.
                    lines.append(f"rule {rid} was changed since — the discard leaves it alone")
                else:
                    lines.append(f'rule {rid} "{rrow.get("name") or ""}"')
        elif op == "delete_event":
            eid = str(inv.get("id") or "")
            try:
                erow = _event_row_strict(eid) if eid else None
            except Exception:
                # _undo_delete_event reports the same read error as
                # "undo failed" and leaves the event alone.
                lines.append(f"event {eid} — the events cannot be read; "
                             "the discard will report it")
                erow = None
            if erow is not None:
                written = entry.get("written")
                if written is not None and _norm(erow) != _norm(written):
                    # _undo_delete_event leaves an event changed since alone.
                    lines.append(f"event {eid} was changed since — the discard leaves it alone")
                else:
                    lines.append(f'event {eid} "{_short(erow.get("text"), 60)}"')
        elif op == "delete_quest_template":
            from app.models.quests import get_template
            qid = str(inv.get("id") or "")
            qrow = get_template(qid) if qid else None
            if qrow is not None:
                if _quest_template_changed(qrow, entry.get("written")):
                    # _undo_delete_quest_template leaves it alone (changed since).
                    lines.append(f"quest template {qid} was changed since — the discard "
                                 "leaves it alone")
                else:
                    lines.append(f'quest template {qid} "{_short(qrow.get("title"), 80)}"')
        elif op == "delete_items":
            for iid in inv.get("ids") or []:
                irow = item_row(str(iid or ""))
                if irow:
                    # Decided after the walk: who still holds it depends on
                    # the created places/characters collected here.
                    item_lines.append((len(lines), str(irow.get("id")),
                                       str(irow.get("name") or "")))
                    lines.append("")
        elif op == "delete_terrain_type":
            kind = str(inv.get("kind") or "")
            trow = terrain_type_row(kind)
            if trow:
                head = f'terrain kind {kind} "{trow.get("name") or kind}"'
                users = ([u for u in terrain_kind_users(kind) if not clears(u, kind)]
                         + _recreated_kind_users(entries, foreign, kind))
                if users:
                    # _undo_delete_terrain_type skips it (changed since, in use).
                    from app.core.world_dev_tools import _kind_users_text
                    head += (" is still used by " + _kind_users_text(users)
                             + " — the discard leaves it")
                lines.append(head)
        elif op == "delete_character":
            name = str(inv.get("name") or "")
            if (entry.get("state") == "pending" and entry.get("written") is None
                    and not inv.get("claimed")):
                continue  # nothing written (see _undo_delete_character)
            hkey = _held_key(inv)
            if name and hkey in held and character_row_exists(name):
                # undo() skips it (REASON_HELD): it stays with everything it has.
                lines.append(f'character "{name}" is still named by '
                             f"{', '.join(held[hkey])}, which cannot be read — "
                             "the discard leaves it")
            elif name and character_row_exists(name):
                deleted_names.add(name)
                chats = count_messages_involving(name)
                mems = count_other_memories_naming(name)
                pieces = sum(1 for iid in sorted(items_of.get(name) or ())
                             if get_item(iid) is not None)
                lines.append(f'character "{name}" — {chats} chat messages, '
                             f"{mems} memory rows of other characters name it"
                             + (f", {pieces} outfit piece{'' if pieces == 1 else 's'} it brought"
                                if pieces else ""))
    # The rooms a restore_location really takes away (one whose rooms /
    # map3d changed since is skipped by the handler and removes nothing).
    sim_removed, sim_places = _run_removed_rooms(entries, foreign)
    removed_rooms.update(sim_removed)
    for at, iid, iname in item_lines:
        holders = _item_kept_by(iid, entries, foreign, deleted_names, created,
                                removed_rooms, sim_places)
        # _undo_delete_items skips an item still held (item still in use).
        lines[at] = (f'item {iid} "{iname}"'
                     + (" is still held by " + ", ".join(holders) + " — stays"
                        if holders else ""))
    lines.extend(_address_preview_lines(entries))
    lines.extend(_skill_preview_lines(entries, deleted_names))
    lines.extend(_hairstyle_preview_lines(entries, deleted_names))
    if created or removed_rooms:
        # Where everybody stands once the undo has put the run's placements
        # back (it reaches them before the older location/room writes).
        for name, (lid, room) in sorted(simulated_places(entries, foreign).items()):
            if name in deleted_names:
                continue
            if lid in created:
                lines.append(f'character "{name}" stands in location {lid} '
                             f'"{created[lid]}" — stays there, place them anew')
            elif room in removed_rooms.get(lid, {}):
                lines.append(f'character "{name}" stands in room '
                             f'"{removed_rooms[lid][room]}" ({room}) of location '
                             f"{lid}, which the undo removes — stays there, "
                             "place them anew")
    # The run's media (plan 2026-11-25-world-dev-free-media Task 9): exactly
    # what the discard's remove_run_media removes / keeps / leaves pending.
    from app.core import world_dev_media
    try:
        lines.extend(world_dev_media.media_preview_lines(run_id))
    except Exception as e:  # noqa: BLE001 — the preview never raises for the media
        lines.append(f"media — could not be read ({e}); the discard will report it")
    return lines
