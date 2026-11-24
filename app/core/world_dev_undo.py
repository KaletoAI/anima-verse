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
reported back.

Inverse ops (``inverse["op"]``):
  delete_location{id} · restore_location{id, before:{key: value}} ·
  restore_position{id, before:{x, z, yaw}} · delete_terrain_area{id} ·
  restore_terrain_area{row} · delete_height_area{id} · restore_height_area{row}
  · delete_character{name, items:[ids]} · restore_character{name,
  profile:{k: before}, config:{k: before}} · restore_soul{name, file_id,
  before_text} (file_id = path relative to the character directory, as
  ``soul_writer.read_text/write_text`` take it) · restore_home_schedule{name,
  before:{home_location, home_room, daily_schedule, known_locations}}

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
    the config has no such key (that is not the same as an empty list)."""
    from app.models.character import (get_character_config,
                                      get_character_daily_schedule)
    cfg = get_character_config(name) or {}
    sched = get_character_daily_schedule(name) or {}
    known = cfg.get("known_locations")
    return _norm({
        "home_location": str(cfg.get("home_location") or ""),
        "home_room": str(cfg.get("home_room") or ""),
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

def _undo_delete_location(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.world import delete_location, get_location_by_id
    lid = str(inv.get("id") or "")
    if not lid or get_location_by_id(lid) is None:
        raise _Skip(REASON_GONE)
    if not delete_location(lid) and get_location_by_id(lid) is not None:
        raise _Skip(REASON_REFUSED)
    return []


def _undo_restore_location(entry: Dict[str, Any], inv: Dict[str, Any]) -> List["_Skip"]:
    from app.models.world import (get_location_by_id, upsert_location,
                                  world_write_lock)
    lid = str(inv.get("id") or "")
    with world_write_lock:
        cur = get_location_by_id(lid) if lid else None
        if cur is None:
            raise _Skip(REASON_GONE)
        cur = copy.deepcopy(cur)
        restore, changed = _split_keys(inv.get("before") or {},
                                       entry.get("written"), cur)
        if restore:
            _apply_keys(cur, restore)
            if not upsert_location(cur, sync_world=True):
                raise RuntimeError(f"restoring location {lid} was not stored")
    if changed:
        raise _Skip(REASON_CHANGED, keys=changed)
    return []


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
    if not name or not character_row_exists(name):
        return [_Skip(REASON_GONE)] + _cleanup_items(inv.get("items") or [])
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
    skip other than ``already gone`` happened — the target being absent is
    the desired end state, so it never makes a rollback incomplete. An entry counts as reversed when its own target was
    restored or removed; item skips of a deleted character (key ``item``)
    are reported beside it. ``already gone`` is a skip, not an error; an
    exception in one step becomes a skip (``undo failed: ...``) and the rest
    still runs. Every handled entry is marked undone."""
    reversed_seqs: List[int] = []
    skipped: List[Dict[str, Any]] = []
    for entry in wr.entries(run_id, turn=turn):
        seq = int(entry["seq"])
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
        if not any("item" not in s for s in skips):
            reversed_seqs.append(seq)
        skipped.extend(skips)
        wr.mark_undone(run_id, seq)
    logger.info("world-dev undo %s (turn %s): %d reversed, %d skipped",
                run_id, turn, len(reversed_seqs), len(skipped))
    return {"reversed": reversed_seqs, "skipped": skipped,
            "complete": is_complete(skipped)}


def is_complete(skipped: List[Dict[str, Any]]) -> bool:
    """True when every skip is ``already gone`` (or there is none)."""
    return all(s.get("reason") == REASON_GONE for s in skipped or [])


def discard_preview(run_id: str) -> List[str]:
    """One line per element the run created that still exists (oldest
    first); a created character also names its chat rows and the other
    characters' memory rows that mention it — they go with it."""
    from app.models.character import character_row_exists
    from app.models.chat import count_messages_involving
    from app.models.memory import count_other_memories_naming
    from app.models.terrain import get_area
    from app.models.world import get_location_by_id
    lines: List[str] = []
    for entry in reversed(wr.entries(run_id)):
        inv = entry.get("inverse") or {}
        op = inv.get("op")
        if op == "delete_location":
            loc = get_location_by_id(str(inv.get("id") or ""))
            if loc:
                lines.append(f'location {loc.get("id")} "{loc.get("name") or ""}"')
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
            if name and character_row_exists(name):
                chats = count_messages_involving(name)
                mems = count_other_memories_naming(name)
                lines.append(f'character "{name}" — {chats} chat messages, '
                             f"{mems} memory rows of other characters name it")
    return lines
