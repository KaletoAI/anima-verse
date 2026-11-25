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
  recreate_location{row} · recreate_terrain_area{row} ·
  recreate_height_area{row} (row = the reader's full record) ·
  recreate_character{name, snapshot:{rows, files, dirs, has_dir,
  file_bytes}} (:func:`character_snapshot`)

Written shapes: restore_location / restore_home_schedule — the written map of
:func:`diff_keys`; restore_position — ``{x, z, yaw}`` (:func:`position_of`);
restore_*_area — the full re-read row; restore_character —
``{"profile": {...}, "config": {...}}``; restore_soul — the stored text as a
plain string (or None when the write removed the file). A key that did not exist is recorded as :data:`ABSENT` (restoring it
removes the key again).

A step that RAISES is reported as ``undo failed: ...`` and still marked
undone (it is not retried by a second ``undo``). Read errors propagate into
that path; they are never read as "absent".

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

def _cleanup_items(item_ids: List[str]) -> List["_Skip"]:
    """Delete the catalog items a created character brought — only when the
    item exists, is not shared and is held nowhere (inventory or room)."""
    from app.models.inventory import (delete_item, find_item_location,
                                      get_item, is_shared_item)
    skips: List[_Skip] = []
    for iid in item_ids or []:
        iid = str(iid or "")
        if not iid or get_item(iid) is None:
            continue
        if is_shared_item(iid) or find_item_location(iid) is not None:
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
                _apply_keys(prof, restore)
                if not save_character_profile(name, prof):
                    raise RuntimeError(f"profile of {name} was not stored")
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


def _undo_recreate_terrain_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.terrain import get_area, save_area
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    if not aid:
        raise RuntimeError("recreate_terrain_area without an id")
    if get_area(aid) is not None:
        return _recreate_exists(entry)
    save_area(copy.deepcopy(row))
    _check_recreated(get_area(aid), row)
    return []


def _undo_recreate_height_area(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.heightfield import save_height_area
    row = inv.get("row") or {}
    aid = str(row.get("id") or "")
    if not aid:
        raise RuntimeError("recreate_height_area without an id")
    if _height_area(aid) is not None:
        return _recreate_exists(entry)
    save_height_area(copy.deepcopy(row))
    _check_recreated(_height_area(aid), row)
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
    "recreate_location": _undo_recreate_location,
    "recreate_terrain_area": _undo_recreate_terrain_area,
    "recreate_height_area": _undo_recreate_height_area,
    "recreate_character": _undo_recreate_character,
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
    still runs. Every handled entry is marked undone. Occupant records of
    characters this undo deleted are dropped at the end."""
    reversed_seqs: List[int] = []
    skipped: List[Dict[str, Any]] = []
    # Targets whose re-creation found a FOREIGN element under the same key:
    # every older entry of that target is skipped too — above all the
    # creating step's delete, which would otherwise remove the foreign one.
    foreign: set = set()
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
        try:
            skips = apply_inverse(entry)
        except Exception as e:  # noqa: BLE001 — one failed step must not stop the rest
            logger.error("world-dev undo %s#%s failed: %s", run_id, seq, e,
                         exc_info=True)
            skips = [_skip_dict(entry, _Skip(f"undo failed: {e}"))]
        if not any("item" not in s and "occupant" not in s for s in skips):
            reversed_seqs.append(seq)
        elif (target is not None
              and str((entry.get("inverse") or {}).get("op") or "").startswith("recreate_")
              and any(s.get("reason") == REASON_CHANGED for s in skips)):
            foreign.add(target)
        skipped.extend(skips)
        wr.mark_undone(run_id, seq)
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
    "recreate_character": ("character", ("name",)),
}


def _target_of(inv: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    spec = _TARGET_KEYS.get(str(inv.get("op") or ""))
    if spec is None:
        return None
    value: Any = inv
    for key in spec[1]:
        value = value.get(key) if isinstance(value, dict) else None
    return (spec[0], str(value)) if value else None


def is_complete(skipped: List[Dict[str, Any]]) -> bool:
    """True when every skip is ``already gone`` / ``not written`` or an
    informational occupant record (key ``occupant``), or there is none."""
    return all(s.get("reason") in (REASON_GONE, REASON_NOT_WRITTEN)
               or "occupant" in s for s in skipped or [])


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
    from app.models.character import character_row_exists
    return character_row_exists(ident)


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
    catalog (", N outfit pieces it brought", left out at 0)."""
    from app.core.world_dev_tools import _rooms_removed_by
    from app.models.character import character_row_exists, list_character_places
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
    items_of: Dict[str, set] = {}
    for entry in entries:
        inv = entry.get("inverse") or {}
        op = str(inv.get("op") or "")
        target = _target_of(inv)
        if target is None or target in foreign:
            continue
        if target not in alive:
            alive[target] = _exists(target)
        if op.startswith("recreate_"):
            if not alive[target]:
                alive[target] = True
            elif entry.get("state") == "done":
                foreign.add(target)
                lines.append(f"{target[0]} {target[1]} was deleted by this run and "
                             "exists again — the discard leaves it alone")
            # pending and present: the delete never ran — nothing to do.
        elif op.startswith("delete_"):
            if op == "delete_character":
                if (entry.get("state") == "pending" and entry.get("written") is None
                        and not inv.get("claimed")):
                    continue  # nothing written (see _undo_delete_character)
                items_of.setdefault(target[1], set()).update(
                    str(i) for i in inv.get("items") or [] if i)
            alive[target] = False
    from app.models.inventory import get_item
    listed: set = set()
    for entry in reversed(entries):
        inv = entry.get("inverse") or {}
        op = inv.get("op")
        target = _target_of(inv)
        if target in foreign:
            continue
        if op in ("delete_location", "delete_terrain_area", "delete_height_area",
                  "delete_character"):
            # A target created, deleted and created again by this run has
            # several creating entries: one line.
            if target in listed:
                continue
            listed.add(target)
        if op == "delete_location":
            loc = get_location_by_id(str(inv.get("id") or ""))
            if loc:
                created[str(loc.get("id"))] = str(loc.get("name") or "")
                lines.append(f'location {loc.get("id")} "{loc.get("name") or ""}"')
        elif op == "restore_location":
            before = inv.get("before") or {}
            if "rooms" not in before and "map3d" not in before:
                continue
            lid = str(inv.get("id") or "")
            cur = get_location_by_id(lid) if lid else None
            if not cur:
                continue
            b_rooms = before.get("rooms", ABSENT)
            b_map3d = before.get("map3d", ABSENT)
            new_rooms = (None if "rooms" not in before
                         else [] if is_absent(b_rooms) else list(b_rooms or []))
            new_map3d = (None if "map3d" not in before or is_absent(b_map3d)
                         else b_map3d)
            for room in _rooms_removed_by(cur, new_rooms, new_map3d):
                rid = str(room.get("id") or "")
                removed_rooms.setdefault(lid, {})[rid] = str(room.get("name") or rid)
        elif op == "delete_terrain_area":
            area = get_area(str(inv.get("id") or ""))
            if area:
                lines.append(f"terrain area {area['id']} ({area.get('kind')})")
        elif op == "delete_height_area":
            area = _height_area(str(inv.get("id") or ""))
            if area:
                lines.append(f"height area {area['id']} ({area.get('height_m')} m)")
        elif op == "delete_character":
            name = str(inv.get("name") or "")
            if (entry.get("state") == "pending" and entry.get("written") is None
                    and not inv.get("claimed")):
                continue  # nothing written (see _undo_delete_character)
            if name and character_row_exists(name):
                deleted_names.add(name)
                chats = count_messages_involving(name)
                mems = count_other_memories_naming(name)
                pieces = sum(1 for iid in sorted(items_of.get(name) or ())
                             if get_item(iid) is not None)
                lines.append(f'character "{name}" — {chats} chat messages, '
                             f"{mems} memory rows of other characters name it"
                             + (f", {pieces} outfit pieces it brought" if pieces else ""))
    if created or removed_rooms:
        for name, (lid, room) in sorted(list_character_places().items()):
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
    return lines
