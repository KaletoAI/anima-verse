"""World Dev free mode — the tool registry the agent works through.

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 5 (read
tools, locations, terrain, height areas) and Task 6 (create_character,
update_character — one journal step per group: soul section, profile+config,
home+schedule). Spec docs/superpowers/specs/2026-11-22-world-dev-free-mode-design.md
("Tools").

ONE ENTRY POINT. run_tool() runs one tool call and journals it as one step
(world_dev_runs): kind "read" for a read tool, "write" for a write that may
have stored something, "refused" for a call the tool turned down. The ONE
refusal mapping lives in run_tool(): ValueError (incl. CharacterNameError),
bulk_edit.GoneError, a 4xx HTTPException and ToolRefusal become ok=False with
a one-line "error: ..."; every other exception propagates — that is a hard
failure for the run manager.

WRITE PROTOCOL (every write tool). Under the writer's lock: read "before"
from storage -> _Step.begin (with the inverse when the target is known) ->
write inside _Step.writing -> attach the target id and the exact inverse as
soon as they exist -> re-read -> complete(written). before/written are
always STORAGE reads, in the shapes world_dev_undo documents (diff_keys maps
for a location update, position_of for a placement, the full re-read row for
an area). When the writer raises, _Step.writing reconciles against storage
INSIDE the same lock span: what was stored keeps its kind "write" and gets
its inverse attached (undo only sees writes); nothing stored means kind
"refused". A reconcile that itself fails leaves the row pending, which the
undo reports as "may have written".

Before the run's first write the safety backup is taken once
(world_dev_backup.take_backup + world_dev_runs.set_backup) — lazily, a run
that only reads makes none; a backup that fails is a hard failure (a run
never writes without one).

Every input is type-checked BEFORE the first write: a core writer such as
world_ops.create_location_with_extras calls .strip() on fields AFTER
add_location has stored the row, so a wrong type would otherwise leave a
half-written place behind.

Never call run_tool() inside an open db.transaction() — the journal helpers
open their own connections.
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.core import world_dev_completeness as completeness
from app.core import world_dev_runs as wr
from app.core import world_dev_undo as wu
from app.core.log import get_logger

logger = get_logger("world_dev_tools")

#: Longest result a READ tool returns (the model's context is the budget).
MAX_RESULT_CHARS = 1500
#: Longest list a read tool returns before "… N more — narrow the query".
MAX_LIST_LINES = 30

#: Manual sections read_manual offers (templates
#: shared/templates/llm/world_dev_free/manual_<section>.md, Task 7).
MANUAL_SECTIONS = ("locations", "map", "characters", "homes", "naming")


class ToolRefusal(Exception):
    """A tool turned its input down — returned to the model, not a failure."""


@dataclass
class ToolCtx:
    run_id: str
    turn: int


@dataclass
class ToolSpec:
    name: str
    write: bool
    signature: str
    summary: str
    fn: Callable[["_Step", Dict[str, Any]], str]
    #: A reference read (manual section, template schema): the agent history
    #: keeps its result whole instead of shrinking it.
    pinned: bool = False


@dataclass
class ToolResult:
    ok: bool
    line: str
    wrote: bool
    #: The journal row of this call (the UI merges live step events into the
    #: journal list by it).
    seq: Optional[int] = None


TOOLS: Dict[str, ToolSpec] = {}


def _tool(name: str, write: bool, signature: str, summary: str, pinned: bool = False):
    def deco(fn):
        TOOLS[name] = ToolSpec(name, write, signature, summary, fn, pinned)
        return fn
    return deco


# ── Journal step ─────────────────────────────────────────────────────────

_BACKED_UP: set = set()


def _ensure_backup(run_id: str) -> None:
    """Take the run's safety backup once, before its first write."""
    if run_id in _BACKED_UP:
        return
    run = wr.get_run(run_id)
    if run is None:
        raise KeyError(f"unknown world-dev run: {run_id}")
    if not run.get("backup_path"):
        from app.core.world_dev_backup import take_backup
        wr.set_backup(run_id, take_backup(run_id))
    _BACKED_UP.add(run_id)


class _Step:
    """The journal row of one tool call (created lazily by the tool)."""

    def __init__(self, ctx: ToolCtx, tool: str, args: Dict[str, Any]):
        self.ctx = ctx
        self.tool = tool
        self.args = args
        self.seq: Optional[int] = None
        self.kind: Optional[str] = None
        self.done = False
        self.writing_started = False
        self.target_kind: Optional[str] = None
        self.target_id: Optional[str] = None
        self.inverse_op: Optional[str] = None

    def prepare(self) -> None:
        """The backup before the first write — called OUTSIDE the writer's
        lock, so a large copy never blocks other world writes."""
        _ensure_backup(self.ctx.run_id)

    def begin(self, target_kind: str, target_id: Optional[str] = None,
              inverse: Optional[dict] = None) -> int:
        _ensure_backup(self.ctx.run_id)
        self.seq = wr.begin(self.ctx.run_id, self.ctx.turn, "write", self.tool,
                            self.args, target_kind, target_id, inverse)
        self.kind = "write"
        self.target_kind = target_kind
        self._note_target(target_id, inverse)
        return self.seq

    def _note_target(self, target_id: Optional[str], inverse: Optional[dict]) -> None:
        if target_id:
            self.target_id = str(target_id)
        if isinstance(inverse, dict) and inverse.get("op"):
            self.inverse_op = str(inverse["op"])

    def attach(self, target_id: Optional[str], inverse: Optional[dict],
               before: Any = None) -> None:
        wr.attach(self.ctx.run_id, self.seq, target_id, inverse, before)
        self._note_target(target_id, inverse)

    def complete(self, written: Any, line: str, kind: Optional[str] = None) -> None:
        wr.complete(self.ctx.run_id, self.seq, written, line, kind)
        if kind:
            self.kind = kind
        self.done = True

    @contextlib.contextmanager
    def writing(self, reconcile: Callable[[], Optional[Tuple[str, dict, Any]]]):
        """Run the writer; on ANY exception reconcile against storage. Used
        INSIDE the writer's lock span, so nothing foreign can land between
        the failed write and the reconcile. reconcile() returns
        (target_id, inverse, written) when something was stored, else None."""
        self.writing_started = True
        try:
            yield
        except BaseException as exc:
            try:
                found = reconcile()
            except Exception as rec_exc:  # noqa: BLE001 — the row stays pending
                logger.error("world-dev %s#%s: reconcile after a failed write "
                             "failed: %s", self.ctx.run_id, self.seq, rec_exc,
                             exc_info=True)
                raise exc
            text = _error_text(exc)
            if found is not None:
                target_id, inverse, written = found
                self.attach(target_id, inverse)
                self.complete(written, f"failed: {text}")
            else:
                self.complete(None, f"error: {text}", kind="refused")
            raise

    @property
    def wrote(self) -> bool:
        return self.seq is not None and self.kind == "write"

    def kept_note(self) -> str:
        """What a refused call left stored — told to the model so it neither
        retries into a duplicate nor forgets the half-written target."""
        kind = str(self.target_kind or "")
        what, fixer = _KEPT_HINTS.get(kind, (kind or "target", ""))
        ident = self.target_id or "?"
        if (self.inverse_op or "").startswith("delete_"):
            return (f"; partly written: {what} {ident} exists — "
                    + (f"fix it with {fixer} or " if fixer else "")
                    + f"remove it with delete_created{{kind: {kind}, id: {ident}}}")
        return (f"; partly written: {what} {ident} was changed in part — "
                f"read it again before the next change")


#: target kind -> (how the result line names it, the tool that fixes it)
_KEPT_HINTS = {"location": ("location", "update_location"),
               "terrain": ("terrain area", "update_terrain_area"),
               "height": ("height area", "update_height_area"),
               "character": ("character", "update_character")}


def _is_refusal(exc: BaseException) -> bool:
    from app.core.bulk_edit import GoneError
    if isinstance(exc, (ToolRefusal, ValueError, GoneError)):
        return True
    try:
        from fastapi import HTTPException
    except Exception:  # noqa: BLE001
        return False
    return isinstance(exc, HTTPException) and 400 <= int(exc.status_code) < 500


def _error_text(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    text = str(detail if detail is not None else exc) or exc.__class__.__name__
    return " ".join(text.split())


def run_tool(ctx: ToolCtx, name: str, args: Any) -> ToolResult:
    """Run ONE tool call as one journal step; see the module docstring."""
    spec = TOOLS.get(name)
    step = _Step(ctx, name, args if isinstance(args, dict) else {"_raw": args})
    try:
        if spec is None:
            raise ToolRefusal(f"unknown tool {name!r} — tools: "
                              + ", ".join(sorted(TOOLS)))
        if not isinstance(args, dict):
            raise ToolRefusal("arguments must be a JSON object")
        line = spec.fn(step, args)
    except BaseException as exc:
        refusal = isinstance(exc, Exception) and _is_refusal(exc)
        text = f"{'error' if refusal else 'failed'}: {_error_text(exc)}"
        if step.seq is None:
            seq = wr.begin(ctx.run_id, ctx.turn, "refused", name, step.args)
            wr.complete(ctx.run_id, seq, None, text)
        else:
            seq = step.seq
        if step.seq is not None and not step.done and not step.writing_started:
            step.complete(None, text, kind="refused")
        # A row whose writer started and was not reconciled stays pending:
        # the undo then reports it instead of assuming nothing happened.
        if refusal:
            if step.wrote:
                text += step.kept_note()
            return ToolResult(False, text, step.wrote, seq)
        raise
    if step.seq is None:
        seq = wr.begin(ctx.run_id, ctx.turn, "read", name, step.args)
        wr.complete(ctx.run_id, seq, None, line)
    else:
        seq = step.seq
        if not step.done:
            step.complete(None, line)
    return ToolResult(True, line, step.wrote, seq)


def tool_list() -> List[str]:
    """One line per tool for the system prompt."""
    return [f"{s.signature} — {s.summary}" for s in TOOLS.values()]


# ── Argument checks ──────────────────────────────────────────────────────

def _is_num(value: Any) -> bool:
    # An int is always finite; isfinite is only asked of a float, because
    # float() of a huge JSON integer (10**400) raises OverflowError — _num
    # refuses such an int when it converts it.
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _num(args: Dict[str, Any], key: str, required: bool = False) -> Optional[float]:
    if key not in args or args[key] is None:
        if required:
            raise ToolRefusal(f"'{key}' is required (a number)")
        return None
    if not _is_num(args[key]):
        raise ToolRefusal(f"'{key}' must be a number")
    try:
        return float(args[key])
    except OverflowError:
        raise ToolRefusal(f"'{key}' must be a number (got an integer too "
                          f"large for one)") from None


def _str(args: Dict[str, Any], key: str, required: bool = False) -> Optional[str]:
    if key not in args or args[key] is None:
        if required:
            raise ToolRefusal(f"'{key}' is required (a string)")
        return None
    if not isinstance(args[key], str):
        raise ToolRefusal(f"'{key}' must be a string")
    value = args[key].strip()
    if required and not value:
        raise ToolRefusal(f"'{key}' must not be empty")
    return value


def _bool(args: Dict[str, Any], key: str) -> Optional[bool]:
    if key not in args or args[key] is None:
        return None
    if not isinstance(args[key], bool):
        raise ToolRefusal(f"'{key}' must be true or false")
    return args[key]


def _points(value: Any, key: str, minimum: int) -> List[List[float]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ToolRefusal(f"'{key}' needs at least {minimum} [x, z] points")
    for pt in value:
        if not (isinstance(pt, (list, tuple)) and len(pt) == 2
                and _is_num(pt[0]) and _is_num(pt[1])):
            raise ToolRefusal(f"'{key}' points must be [x, z] number pairs")
    return [[float(p[0]), float(p[1])] for p in value]


def _only_keys(args: Dict[str, Any], allowed, what: str) -> None:
    extra = sorted(k for k in args if k not in allowed)
    if extra:
        raise ToolRefusal(f"unknown {what} key(s) {', '.join(extra)} — allowed: "
                          + (", ".join(sorted(allowed)) or "none"))


# The location schema (shared/world_dev_schemas/location.md) plus the
# location editor's extra fields the core writers take.
_LOC_STR = ("name", "description", "image_prompt_day", "image_prompt_night",
            "image_prompt_building", "indoor", "decency", "style_hint",
            "activity_hint", "terrain", "entry_room",
            "default_door_style", "default_window_style")
_LOC_INT = ("danger_level",)
_LOC_BOOL = ("swim_allowed",)
_LOC_KEYS = set(_LOC_STR) | set(_LOC_INT) | set(_LOC_BOOL) | {"rooms", "map3d"}
#: What a get_location fields read knows as a field even when the place
#: does not store it: the writable keys plus the id and the map position.
_LOC_READ_KEYS = _LOC_KEYS | {"id", "pos_x", "pos_z", "yaw_deg"}
_ROOM_STR = ("id", "name", "description", "indoor", "decency", "style_hint",
             "image_prompt", "image_prompt_day", "image_prompt_night",
             "activity_hint")
_ROOM_BOOL = ("swim_allowed",)
_ROOM_KEYS = set(_ROOM_STR) | set(_ROOM_BOOL)
#: The map3d keys world_ops._sanitize_map3d keeps (plan_width_m is derived
#: from the boundary, never an input).
_MAP3D_KEYS = {"floors", "footprint", "style", "color", "ground_corridor",
               "boundary", "storey_height_m", "outline", "level_outlines",
               "elevator", "elevator_kind", "stairs", "level_floors",
               "wall_kind", "level_walls", "area_model", "area_detail",
               "boundary_openings", "hull_openings"}
#: Longest location or room name a tool stores.
MAX_NAME_CHARS = 120
#: The decency values the location writers keep ("" = inherit / public).
_DECENCY = ("", "public", "private", "nude_ok")
#: The danger levels the location writers store (they clamp to 0-5).
_DANGER_LEVELS = tuple(range(6))
#: The indoor flags the readers know (models.world.resolve_indoor_flag;
#: the location writers blank anything else, "" = unset).
_INDOOR = ("", "indoor", "outdoor")


def _shown(value: Any) -> str:
    return '""' if value == "" else str(value)


def _one_of(data: Dict[str, Any], key: str, allowed) -> None:
    """Refuse a value of ``key`` outside ``allowed`` (the refusal lists them)."""
    if key in data and data[key] not in allowed:
        raise ToolRefusal(f"'{key}' must be one of: "
                          + ", ".join(_shown(v) for v in allowed))


def _check_location_values(data: Dict[str, Any]) -> None:
    """Value checks of a location body: a value the writers would clamp,
    blank or keep without any reader is refused, never rewritten."""
    _one_of(data, "danger_level", _DANGER_LEVELS)
    _one_of(data, "decency", _DECENCY)
    _one_of(data, "indoor", _INDOOR)
    if "default_door_style" in data:
        from app.core.door_styles import load_door_styles
        _one_of(data, "default_door_style", ("",) + tuple(sorted(load_door_styles())))
    if "default_window_style" in data:
        from app.core.window_styles import load_window_styles
        _one_of(data, "default_window_style",
                ("",) + tuple(sorted(load_window_styles())))
    if "terrain" in data:
        from app.core.terrain_types import effective_catalog
        _one_of(data, "terrain", ("",) + tuple(sorted(effective_catalog())))


def _entry_room_choices(rooms: List[Dict[str, Any]],
                        map3d: Optional[Dict[str, Any]],
                        previous: Optional[List[Dict[str, Any]]] = None
                        ) -> List[Tuple[str, str]]:
    """``(id, name)`` of every room an ``entry_room`` may name once ``rooms``
    is written with ``map3d``: the rooms of the list plus the corridors the
    writer's sync adds, of the corridors only the ground floor's
    (models.world.valid_entry_room). The ground is no choice — "" already
    means "arrive on the ground". A room without an id yet has id "".
    ``previous`` = the stored room list (None on create): a corridor the
    sync brings back takes its stored name from there, as in the writer."""
    from app.core.world_ops import _sanitize_map3d
    from app.models.world import (GROUND_ROOM_ID, ensure_floor_rooms,
                                  floor_room_level)
    sim = copy.deepcopy([r for r in rooms if isinstance(r, dict)])
    ensure_floor_rooms(sim, _sanitize_map3d(map3d) if map3d else None,
                       previous=copy.deepcopy([r for r in previous or []
                                               if isinstance(r, dict)]))
    out: List[Tuple[str, str]] = []
    for r in sim:
        rid = str(r.get("id") or "")
        if rid == GROUND_ROOM_ID:
            continue
        level = floor_room_level(rid)
        if level is not None and level != 0:
            continue
        out.append((rid, str(r.get("name") or rid).strip()))
    return out


def _resolve_entry_room(value: str,
                        choices: List[Tuple[str, str]]) -> Tuple[str, Optional[str]]:
    """``(id, None)`` for a room that already has its id (``("", None)``
    clears the entry room), ``("", name)`` for a room the write is still to
    create — resolved by name after the write. Refused unless it names
    exactly one room of ``choices`` (by id or by stripped name)."""
    v = str(value or "").strip()
    if not v:
        return "", None
    for rid, _name in choices:
        if rid and rid == v:
            return rid, None
    named = [rid for rid, name in choices if name == v]
    if len(named) > 1:
        raise ToolRefusal(f"'entry_room': {len(named)} rooms are called {v!r} — "
                          f"send the room's id")
    if named:
        return (named[0], None) if named[0] else ("", v)
    raise ToolRefusal("'entry_room' must name a room of this place: "
                      + (", ".join(name for _rid, name in choices) or "none")
                      + ' ("" = arrive on the ground)')


def _write_entry_room_by_name(lid: str, name: str, old_ids) -> None:
    """Store the id of the room ``name`` (compared stripped) that a write
    just created (its id is not in ``old_ids``) as the place's entry room."""
    from app.core.world_ops import update_location_with_extras
    from app.models.world import get_location_by_id
    loc = get_location_by_id(lid) or {}
    new = [str(r.get("id")) for r in loc.get("rooms") or []
           if isinstance(r, dict) and str(r.get("name") or "").strip() == name
           and str(r.get("id") or "") not in old_ids]
    if len(new) != 1:
        raise RuntimeError(f"entry room {name!r}: {len(new)} new rooms of that name "
                           f"after the write")
    update_location_with_extras(lid, {"entry_room": new[0]})
    if str((get_location_by_id(lid) or {}).get("entry_room") or "") != new[0]:
        raise RuntimeError(f"entry room {name!r} was not stored")


def _check_name_length(value: Optional[str], what: str) -> None:
    if value is not None and len(value) > MAX_NAME_CHARS:
        raise ToolRefusal(f"{what} is {len(value)} characters long — "
                          f"at most {MAX_NAME_CHARS}")


def _check_location_fields(data: Dict[str, Any], what: str,
                           creating: bool = False) -> None:
    """Whitelist + type check of a location body (create data / update patch).
    Room ids: never twice in one list; on create never a reserved "__" id
    (ground and corridors belong to the server)."""
    _only_keys(data, _LOC_KEYS, what)
    for key in _LOC_STR:
        _str(data, key)
    _check_name_length(_str(data, "name"), "'name'")
    for key in _LOC_BOOL:
        _bool(data, key)
    for key in _LOC_INT:
        value = _num(data, key)
        if value is not None and value != int(value):
            raise ToolRefusal(f"'{key}' must be a whole number")
    _check_location_values(data)
    if data.get("map3d") is not None:
        m3 = data["map3d"]
        if not isinstance(m3, dict):
            raise ToolRefusal("'map3d' must be an object")
        _only_keys(m3, _MAP3D_KEYS, "map3d")
        if m3.get("boundary") is not None:
            _points(m3["boundary"], "map3d.boundary", 3)
    if data.get("rooms") is not None:
        rooms = data["rooms"]
        if not isinstance(rooms, list):
            raise ToolRefusal("'rooms' must be a list of room objects")
        for i, room in enumerate(rooms):
            if not isinstance(room, dict):
                raise ToolRefusal(f"rooms[{i}] must be an object")
            _only_keys(room, _ROOM_KEYS, f"rooms[{i}]")
            try:
                for key in _ROOM_STR:
                    _str(room, key)
                for key in _ROOM_BOOL:
                    _bool(room, key)
                _check_name_length(_str(room, "name"), "'name'")
                _one_of(room, "decency", _DECENCY)
                _one_of(room, "indoor", _INDOOR)
            except ToolRefusal as exc:
                raise ToolRefusal(f"rooms[{i}]: {exc}")
        seen: Dict[str, int] = {}
        for i, room in enumerate(rooms):
            rid = str(room.get("id") or "").strip()
            if not rid:
                continue
            if rid in seen:
                raise ToolRefusal(f"rooms[{i}] repeats the id {rid!r} of rooms[{seen[rid]}] "
                                  f"— every room needs its own id (omit it for a new room)")
            seen[rid] = i
            if creating and rid.startswith("__"):
                raise ToolRefusal(f"rooms[{i}]: the id {rid!r} is reserved for the "
                                  f"server — omit the id")


def _map3d_dropped(sent: Dict[str, Any], merged: Dict[str, Any]) -> List[str]:
    """The sent map3d keys whose (non-empty) value the writer's sanitizer
    would drop — refused instead of silently losing the stored value."""
    from app.core.world_ops import _sanitize_map3d
    clean = _sanitize_map3d(merged)
    return sorted(k for k, v in sent.items()
                  if k not in clean and v not in (None, False, "", [], {}))


def _refuse_map3d_dropped(sent: Dict[str, Any], merged: Dict[str, Any]) -> None:
    dropped = _map3d_dropped(sent, merged)
    if dropped:
        raise ToolRefusal("map3d value(s) not valid and would be dropped: "
                          + ", ".join(dropped) + " — check their shape "
                          "(read_manual locations)")


def _drop_none(body: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of a location body without the keys the model sent as JSON null
    (also inside each room and map3d). Models emit null for "empty"; the core
    writers call .strip() on what they get, so a kept None would crash a
    writer AFTER the row was stored. null means "not given"."""
    out = {k: copy.deepcopy(v) for k, v in body.items() if v is not None}
    if isinstance(out.get("rooms"), list):
        out["rooms"] = [{k: v for k, v in r.items() if v is not None}
                        if isinstance(r, dict) else r for r in out["rooms"]]
    if isinstance(out.get("map3d"), dict):
        out["map3d"] = {k: v for k, v in out["map3d"].items() if v is not None}
    return out


#: Farthest a place may stand from the origin (metres) — a sanity bound
#: against a model writing 1e12; far beyond any world the editor builds.
MAX_COORD_M = 100_000.0


def _coord(args: Dict[str, Any], key: str, required: bool = False) -> Optional[float]:
    value = _num(args, key, required)
    if value is not None and abs(value) > MAX_COORD_M:
        raise ToolRefusal(f"'{key}' {_g(value)} is far outside any world "
                          f"(limit ±{_g(MAX_COORD_M)} m)")
    return value


def _normalize_rooms(rooms: List[Dict[str, Any]]) -> None:
    """The image-prompt normalisation of today's World Dev location apply:
    the model writes "image_prompt", the system reads "image_prompt_day"."""
    for room in rooms:
        if "image_prompt" in room and "image_prompt_day" not in room:
            room["image_prompt_day"] = room.pop("image_prompt")
        else:
            room.pop("image_prompt", None)
        room.setdefault("image_prompt_night", "")


# ── Formatting helpers ───────────────────────────────────────────────────

def _g(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "?"


def _short(text: Any, n: int = 160) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _where(loc: Dict[str, Any]) -> str:
    if loc.get("pos_x") is None or loc.get("pos_z") is None:
        return "unplaced"
    yaw = float(loc.get("yaw_deg") or 0.0)
    return (f"({_g(loc['pos_x'])},{_g(loc['pos_z'])})"
            + (f" yaw {_g(yaw)}" if yaw else ""))


def _width(loc: Dict[str, Any]) -> str:
    from app.core.location_model3d import derive_plan_width_m
    try:
        w = derive_plan_width_m(str(loc.get("id") or ""), loc.get("map3d"))
    except Exception:  # noqa: BLE001 — a size is a hint, never a failure
        w = 0.0
    return f"{_g(w)} m" if w > 0 else "no outline"


#: Characters _cap_lines keeps free for its "… N more" line.
_CAP_RESERVE = 60


def _cap_lines(lines: List[str], hint: str = "narrow the query",
               budget: int = MAX_RESULT_CHARS, used: int = 0,
               max_lines: int = MAX_LIST_LINES) -> List[str]:
    """At most "max_lines" lines and "budget" characters ("used" already
    spent by a header), with "… N more — <hint>" for the rest."""
    out: List[str] = []
    total = used
    for i, line in enumerate(lines):
        if len(out) >= max_lines or total + len(line) + 1 + _CAP_RESERVE > budget:
            out.append(f"… {len(lines) - i} more — {hint}")
            return out
        out.append(line)
        total += len(line) + 1
    return out


def _cut(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    tail = "\n… (cut — ask for fewer fields)"
    return text[:MAX_RESULT_CHARS - len(tail)].rstrip() + tail


def _real_rooms(loc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The authored rooms — without the reserved ground and corridors."""
    return [r for r in loc.get("rooms") or [] if isinstance(r, dict)
            and not str(r.get("id") or "").startswith("__")]


def _loc_line(loc: Dict[str, Any], extra: str = "") -> str:
    """One compact list line; rooms and size only when there are any (30
    lines have to fit the result cap)."""
    n_rooms = len(_real_rooms(loc))
    width = _width(loc)
    return (f'{loc.get("id")} "{_short(loc.get("name"), 40)}" {_where(loc)}'
            + (f" · {n_rooms} rooms" if n_rooms else "")
            + (f" · {width}" if width != "no outline" else "") + extra)


def _resolve_location(ident: str) -> Dict[str, Any]:
    from app.models.world import get_location_by_id, list_locations
    loc = get_location_by_id(ident)
    if loc:
        return loc
    named = [l for l in list_locations() if l.get("name") == ident]
    if len(named) == 1:
        return named[0]
    if named:
        raise ToolRefusal(f"{len(named)} locations are named {ident!r} — use the id: "
                          + ", ".join(str(l.get("id")) for l in named))
    raise ToolRefusal(f"no location {ident!r} — use find_locations")


def _bbox(polygon: Any) -> Optional[Tuple[float, float, float, float]]:
    xs, zs = [], []
    for pt in polygon or []:
        try:
            xs.append(float(pt[0]))
            zs.append(float(pt[1]))
        except (TypeError, ValueError, IndexError):
            continue
    if not xs:
        return None
    return min(xs), min(zs), max(xs), max(zs)


def _fmt_box(box: Optional[Tuple[float, float, float, float]]) -> str:
    if box is None:
        return "no area"
    return f"bbox ({_g(box[0])},{_g(box[1])})-({_g(box[2])},{_g(box[3])})"


#: Shared budget of the requested fields of ONE get_character / get_location
#: call (decision D8): fields are returned whole up to it, so the model can
#: read a long text and send it back unchanged.
MAX_FIELD_CHARS = 12000
#: At most this many field names per fields read, each at most
#: MAX_FIELD_KEY_CHARS long: the placeholder lines ("(not set)", "(no such
#: field)", "(not shown — over budget)") are not counted against
#: MAX_FIELD_CHARS, so these two caps bound them instead.
MAX_READ_FIELDS = 30
MAX_FIELD_KEY_CHARS = 80


def _field_text(value: Any) -> str:
    """A field value as the model reads it: strings raw (not JSON-escaped),
    everything else as JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _field_blocks(items: List[Tuple[str, Optional[str], bool]],
                  missing: Optional[Dict[str, str]] = None) -> List[str]:
    """The requested fields, each "<key>:" + newline + its full text, under
    the shared MAX_FIELD_CHARS budget (counted as header + text per field).

    "items" = (key, text or None when unset, is a soul field). The field
    that does not fit is cut to what is left and gets a note; every field
    after it is named as not shown, never dropped silently. "missing" maps
    a key that names no field at all to its placeholder text, so a typo
    never reads like an empty field."""
    out: List[str] = []
    left = MAX_FIELD_CHARS
    over = False
    for key, text, soul in items:
        if missing and key in missing:
            out.append(f"{key}: {missing[key]}")
            continue
        if text is None:
            out.append(f"{key}: (not set)")
            continue
        if over:
            out.append(f"{key}: (not shown — over budget)")
            continue
        head = f"{key}:\n"
        if len(head) + len(text) <= left:
            out.append(head + text)
            left -= len(head) + len(text)
            continue
        n = max(0, left - len(head))
        note = (f"[cut at {n} of {len(text)} characters — ask for this field alone"
                + (f" — do not send it back as soul:{key}" if soul else "") + "]")
        out.append(head + text[:n] + "\n" + note)
        left, over = 0, True
    return out


def _fields_arg(args: Dict[str, Any]) -> Optional[List[str]]:
    fields = args.get("fields")
    if fields is not None and (not isinstance(fields, list)
                               or not all(isinstance(f, str) for f in fields)):
        raise ToolRefusal("'fields' must be a list of field names")
    if fields is not None and len(fields) > MAX_READ_FIELDS:
        raise ToolRefusal(f"at most {MAX_READ_FIELDS} fields per read — "
                          f"{len(fields)} were asked for; split the read")
    for key in fields or []:
        if len(key) > MAX_FIELD_KEY_CHARS:
            raise ToolRefusal(f"field name {key[:40]!r}… is longer than "
                              f"{MAX_FIELD_KEY_CHARS} characters — no field has such a name")
    return fields


# ── Read tools ───────────────────────────────────────────────────────────

@_tool("world_overview", False, "world_overview{}",
       "world setup, compass, bounds, terrain kinds, counts, places")
def _world_overview(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.map_layout_apply import current_world_bounds
    from app.core.terrain_types import effective_catalog
    from app.models.character import list_available_characters
    from app.models.heightfield import list_height_areas
    from app.models.terrain import list_areas
    from app.models.world import list_locations
    from app.models.world_setup import get_world_setup_text
    _only_keys(args, set(), "world_overview")
    locs = list_locations()
    placed = [l for l in locs if l.get("pos_x") is not None and l.get("pos_z") is not None]
    box = current_world_bounds()
    kinds = [kind if bool(entry.get("passable", True)) else f"{kind} (impassable)"
             for kind, entry in sorted(effective_catalog().items())]
    head = [
        f"setup: {_short(get_world_setup_text(), 200) or '(none)'}",
        "compass: x = east, z = south, metres",
        ("bounds: none yet" if not box else
         f"bounds: x {_g(box['min_x'])}…{_g(box['max_x'])}, "
         f"z {_g(box['min_z'])}…{_g(box['max_z'])}"),
        "terrain kinds: " + (", ".join(kinds) or "none"),
        (f"counts: {len(locs)} locations ({len(placed)} placed), "
         f"{len(list_available_characters())} characters, "
         f"{len(list_areas())} terrain areas, {len(list_height_areas())} height areas"),
        "locations:",
    ]
    used = sum(len(h) + 1 for h in head)
    body = [f'{l.get("id")} "{_short(l.get("name"), 40)}" {_where(l)}' for l in locs]
    # The header is not capped by itself (a long terrain catalog), so the
    # whole result goes through the cut as well.
    return _cut("\n".join(head + (_cap_lines(body, "use find_locations", used=used)
                                  or ["(none)"])))


@_tool("find_locations", False, "find_locations{query?, near?:[x,z], radius?}",
       "places by name/description and/or distance")
def _find_locations(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.world import list_locations
    _only_keys(args, {"query", "near", "radius"}, "find_locations")
    query = (_str(args, "query") or "").lower()
    near = _points([args["near"]], "near", 1)[0] if args.get("near") is not None else None
    radius = _num(args, "radius")
    hits: List[Tuple[float, Dict[str, Any]]] = []
    for loc in list_locations():
        if query and query not in " ".join(
                (str(loc.get("id") or ""), str(loc.get("name") or ""),
                 str(loc.get("description") or ""))).lower():
            continue
        dist = 0.0
        if near is not None:
            if loc.get("pos_x") is None or loc.get("pos_z") is None:
                continue
            dist = math.hypot(float(loc["pos_x"]) - near[0],
                              float(loc["pos_z"]) - near[1])
            if radius is not None and dist > radius:
                continue
        hits.append((dist, loc))
    if near is not None:
        hits.sort(key=lambda h: h[0])
    if not hits:
        return "no matching locations"
    lines = [_loc_line(loc, f" · {_g(round(d, 1))} m away" if near is not None else "")
             for d, loc in hits]
    return "\n".join(_cap_lines(lines))


@_tool("get_location", False, "get_location{id, fields?:[...]}",
       "one place; rooms as names unless 'rooms' is asked for; asked-for "
       "fields come whole (shared budget of 12000 characters, at most 30 fields)")
def _get_location(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"id", "fields"}, "get_location")
    loc = _resolve_location(_str(args, "id", required=True))
    fields = _fields_arg(args)
    if fields:
        out = [f'{loc.get("id")} "{loc.get("name")}"']
        items: List[Tuple[str, Optional[str], bool]] = []
        missing: Dict[str, str] = {}
        for key in dict.fromkeys(fields):  # a key asked for twice is answered once
            value = loc.get(key)
            if key not in loc and key not in _LOC_READ_KEYS:
                # Neither stored nor a location field: a typo, not an
                # empty field.
                missing[key] = ("(no such field — location fields: "
                                + ", ".join(sorted(_LOC_READ_KEYS)) + ")")
            items.append((key, None if value in (None, "") else _field_text(value),
                          False))
        out += _field_blocks(items, missing)
        return "\n".join(out)
    rooms = [f'{r.get("name") or "?"} ({r.get("id")})' for r in _real_rooms(loc)]
    shown = {"id", "name", "description", "rooms", "pos_x", "pos_z", "yaw_deg",
             "indoor", "danger_level"}
    other = sorted(k for k, v in loc.items()
                   if k not in shown and v not in (None, "", [], {}))
    out = [
        f'{loc.get("id")} "{loc.get("name")}" {_where(loc)} · {_width(loc)} · '
        f'{loc.get("indoor") or "indoor unset"} · danger {loc.get("danger_level") or 0}',
        f"description: {_short(loc.get('description'), 300) or '(none)'}",
        "rooms: " + (", ".join(rooms) or "(none)"),
        "other fields: " + (", ".join(other) or "(none)"),
    ]
    return _cut("\n".join(out))


@_tool("map_region", False, "map_region{min_x, min_z, max_x, max_z, polygons?}",
       "terrain/height areas and places in a box (bboxes; polygons on request, "
       "a polygon too long for the result points to get_area)")
def _map_region(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.heightfield import list_height_areas
    from app.models.terrain import list_areas
    from app.models.world import list_locations
    _only_keys(args, {"min_x", "min_z", "max_x", "max_z", "polygons"}, "map_region")
    x0, z0 = _num(args, "min_x", True), _num(args, "min_z", True)
    x1, z1 = _num(args, "max_x", True), _num(args, "max_z", True)
    if x1 < x0 or z1 < z0:
        raise ToolRefusal("max_x/max_z must not be below min_x/min_z")
    polys = bool(_bool(args, "polygons"))

    def hits(box) -> bool:
        return box is not None and not (box[2] < x0 or box[0] > x1
                                        or box[3] < z0 or box[1] > z1)
    lines: List[str] = []
    used = 0

    def add(line: str, area: Dict[str, Any]) -> None:
        """One area line; with polygons, an outline longer than its own
        ceiling (MAX_REGION_POLY_CHARS) or than the read budget still left
        becomes a pointer to get_area instead of ending the list (decision
        D11): one outline can never use up the list, later areas are listed
        all the same. The outline keeps every stored decimal (_fmt_points),
        so it can be sent back unchanged; only the bbox is rounded."""
        nonlocal used
        if polys:
            poly = area.get("polygon") or []
            text = _fmt_points(poly)
            full = line + " polygon " + text
            if (len(text) <= MAX_REGION_POLY_CHARS
                    and used + len(full) + 1 + _CAP_RESERVE <= MAX_RESULT_CHARS):
                line = full
            else:
                line += (f" polygon: {len(poly)} points — "
                         f'get_area{{"id": "{area["id"]}"}}')
        lines.append(line)
        used += len(line) + 1

    for a in list_areas():
        box = _bbox(a.get("polygon"))
        if not hits(box):
            continue
        label = (a.get("meta") or {}).get("label")
        add(f'terrain {a["id"]} {a.get("kind")}'
            + (f' "{_label(label, 40)}"' if label else "")
            + f" {_fmt_box(box)} z_order {a.get('z_order') or 0}", a)
    for h in list_height_areas():
        box = _bbox(h.get("polygon"))
        if not hits(box):
            continue
        label = (h.get("meta") or {}).get("label")
        add(f'height {h["id"]}' + (f' "{_label(label, 40)}"' if label else "")
            + f" {_g(h.get('height_m'))} m falloff {_g(h.get('falloff_m'))} m "
            + _fmt_box(box), h)
    for loc in list_locations():
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            continue
        px, pz = float(loc["pos_x"]), float(loc["pos_z"])
        if x0 <= px <= x1 and z0 <= pz <= z1:
            lines.append("place " + _loc_line(loc))
    if not lines:
        return "nothing in this box"
    return "\n".join(_cap_lines(lines, "use a smaller box"))


#: Longest outline text one map_region line carries with polygons; a longer
#: one becomes a get_area pointer, so it cannot use up the list (D11).
MAX_REGION_POLY_CHARS = 400

#: Own budget of one get_area result: the stroke line (the recipe) first,
#: then the outline, each cut on a point boundary beyond it.
MAX_AREA_CHARS = 12000
#: Part of MAX_AREA_CHARS kept free for the cut line.
_AREA_CUT_RESERVE = 80


def _label(label: Any, limit: int) -> str:
    """A label for a quoted head field: shortened, inner double quotes
    replaced by single ones so the quoting stays readable."""
    return _short(str(label).replace('"', "'"), limit)


def _m2(value: Any) -> str:
    """A stored coordinate (2-decimal grid) as written: 2 decimals at most,
    trailing zeros dropped — exact where :g would round a large value."""
    try:
        s = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"
    return "0" if s == "-0" else s


def _fmt_points(points: Any) -> str:
    """A point list as JSON with every stored decimal kept."""
    return "[" + ",".join(f"[{_m2(p[0])},{_m2(p[1])}]" for p in points or []) + "]"


def _fit_points(prefix: str, points: Any, budget: int) -> Tuple[str, int]:
    """``prefix`` + the point list, whole when it fits ``budget`` characters;
    otherwise as many WHOLE points as fit, closed by ",…]" (not valid JSON,
    so a shortened list cannot be sent back by mistake). Returns the line
    and the number of points shown."""
    pts = list(points or [])
    whole = prefix + _fmt_points(pts)
    if len(whole) <= budget:
        return whole, len(pts)
    parts: List[str] = []
    size = len(prefix) + 1 + 3          # "[" … ",…]" (or "…]" when none fit)
    for p in pts:
        s = f"[{_m2(p[0])},{_m2(p[1])}]"
        add = len(s) + (1 if parts else 0)
        if size + add > budget:
            break
        parts.append(s)
        size += add
    if not parts:
        return prefix + "[…]", 0
    return prefix + "[" + ",".join(parts) + ",…]", len(parts)


@_tool("get_area", False, "get_area{id}",
       "one terrain or height area whole: its full polygon, and a stroke "
       "area's centre line and width (own budget of 12000 characters)")
def _get_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.heightfield import list_height_areas
    from app.models.terrain import get_area
    _only_keys(args, {"id"}, "get_area")
    aid = _str(args, "id", required=True)
    area = get_area(aid)
    if area is not None:
        meta = area.get("meta") or {}
        label = meta.get("label")
        out = [f'terrain {area["id"]} {area.get("kind")}'
               + (f' "{_label(label, 80)}"' if label else "")
               + f" z_order {area.get('z_order') or 0}"]
    else:
        area = next((h for h in list_height_areas() if h.get("id") == aid), None)
        if area is None:
            raise ToolRefusal(f"no terrain or height area {aid!r} — use map_region")
        meta = area.get("meta") or {}
        label = meta.get("label")
        out = [f'height {area["id"]}' + (f' "{_label(label, 80)}"' if label else "")
               + f" height_m {_g(area.get('height_m'))}"
               + f" falloff_m {_g(area.get('falloff_m'))}"]
    # The stroke is the authoritative recipe (a stroke area's polygon is
    # derived from it), so it comes first and is budgeted first; the
    # polygon takes what is left. Both cut on a point boundary only.
    left = MAX_AREA_CHARS - _AREA_CUT_RESERVE - len(out[0])
    cuts: List[str] = []
    stroke = meta.get("stroke")
    if isinstance(stroke, dict) and stroke.get("points"):
        spts = stroke.get("points") or []
        prefix = f"stroke: width_m {_g(stroke.get('width_m'))}"
        for key in ("style", "spacing_m", "amplitude_m"):
            if stroke.get(key) not in (None, ""):
                value = stroke[key]
                prefix += f" {key} {value if isinstance(value, str) else _g(value)}"
        along = stroke.get("along")
        if isinstance(along, list) and along:
            # The rows of props along the line are not part of the stroke an
            # update sends; update_terrain_area carries them over.
            prefix += f" along: {len(along)} rows (kept on update)"
        # The polygon line always follows, so its shortest form (no point
        # shown) is reserved before the stroke takes the rest.
        poly_min = len(f"polygon ({len(area.get('polygon') or [])} points): […]") + 1
        line, shown = _fit_points(f"{prefix} points ", spts, left - 1 - poly_min)
        out.append(line)
        left -= len(line) + 1
        if shown < len(spts):
            cuts.append(f"stroke: {shown} of {len(spts)} points shown")
    poly = area.get("polygon") or []
    line, shown = _fit_points(f"polygon ({len(poly)} points): ", poly, left - 1)
    out.append(line)
    if shown < len(poly):
        cuts.append(f"polygon: {shown} of {len(poly)} points shown")
    if cuts:
        out.append(f"[cut — {'; '.join(cuts)}]")
    return "\n".join(out)


@_tool("find_characters", False, "find_characters{query?, location?}",
       "characters by name and/or the place they stand in")
def _find_characters(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.character import list_available_characters, list_character_places
    from app.models.world import get_location_by_id
    _only_keys(args, {"query", "location"}, "find_characters")
    query = (_str(args, "query") or "").lower()
    loc_filter = _str(args, "location")
    loc_id = _resolve_location(loc_filter)["id"] if loc_filter else ""
    places = list_character_places()
    locs: Dict[str, Dict[str, Any]] = {}
    lines: List[str] = []
    for name in list_available_characters():
        if query and query not in name.lower():
            continue
        lid, room = places.get(name, ("", ""))
        if loc_id and lid != loc_id:
            continue
        where = "nowhere"
        if lid:
            if lid not in locs:
                locs[lid] = get_location_by_id(lid) or {}
            loc = locs[lid]
            room_name = next((r.get("name") for r in loc.get("rooms") or []
                              if isinstance(r, dict) and r.get("id") == room), room)
            where = (f'{lid} "{_short(loc.get("name") or lid, 40)}"'
                     + (f" / {room_name}" if room else ""))
        lines.append(f'"{name}" at {where}')
    if not lines:
        return "no matching characters"
    return "\n".join(_cap_lines(lines))


@_tool("get_character", False, "get_character{name, fields?:[...]}",
       "one character; field names unless fields are asked for, asked-for "
       "fields come whole (shared budget of 12000 characters, at most 30 "
       "fields; soul fields as the raw text soul:<field> takes, also readable "
       "under that spelling); "
       "fields [\"body_slots\"] = its body slots with values and allowed values")
def _get_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.character import (character_row_exists, get_character_config,
                                      get_character_profile)
    _only_keys(args, {"name", "fields"}, "get_character")
    name = _str(args, "name", required=True)
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    from app.models.character import get_character_outfits
    fields = _fields_arg(args)
    prof = get_character_profile(name) or {}
    cfg = get_character_config(name) or {}
    if fields:
        from app.core import soul_writer
        from app.core.linked_characters import soul_owner
        template = str(prof.get("template") or "human-default")
        tfields = _template_fields(template)
        soul_map = {k: str(f["source_file"]) for k, f in tfields.items()
                    if f.get("source_file")}
        out = [f'"{name}"']
        items: List[Tuple[str, Optional[str], bool]] = []
        missing: Dict[str, str] = {}
        schema: List[str] = []
        seen: set = set()
        for key in fields:
            if key.startswith("soul:"):
                # The write spelling of a soul field reads the same text
                # (answered under the bare key, the one update_character's
                # "soul:<key>" names).
                bare = key[len("soul:"):]
                if bare not in soul_map:
                    missing[key] = (f"(no such soul field in template {template} — "
                                    "soul fields: "
                                    + (", ".join(sorted(soul_map)) or "none") + ")")
                    items.append((key, None, True))
                    continue
                key = bare
            if key in seen:
                # The same field asked for twice (bare and as soul:<key>)
                # is answered once, not charged to the budget twice.
                continue
            seen.add(key)
            if key == "body_slots":
                # The schema of the package-declared slots, not the raw blob:
                # what can be set, to what, and what is set now.
                lines = _body_schema(prof)
                schema = (["body slots (slot: attribute=value [allowed]; - = unset):"]
                          + lines if lines else
                          ["body slots: none — the template declares none for this "
                           "character"])
                continue
            if key in soul_map:
                # The raw file — what update_character's soul:<key> writes —
                # not the profile's prepared copy (that one drops the top
                # heading and empty sections).
                rel = soul_map[key]
                raw = soul_writer.read_text(soul_owner(name, rel), rel)
                raw = None if raw is None else raw.rstrip("\n")
                items.append((key, raw or None, True))
                continue
            stats = (prof.get("status_effects")
                     if isinstance(prof.get("status_effects"), dict) else {})
            if key in tfields and _field_store(tfields[key]) == "status":
                # A stat lives in profile.status_effects (where
                # create/update_character write it), not under its own key.
                src = stats if key in stats else None
            else:
                src = prof if key in prof else cfg if key in cfg else None
            if src is None and key not in tfields:
                # Neither a template field nor a stored key: a typo, not an
                # empty field.
                missing[key] = (f'(no such field — describe_template{{"template": '
                                f'{json.dumps(template, ensure_ascii=False)}}} lists them)')
            # A stored None or "" is "nothing there" like an absent key:
            # one spelling, "(not set)".
            value = None if src is None else src[key]
            items.append((key, None if value in (None, "") else _field_text(value),
                          False))
        text = "\n".join(out + _field_blocks(items, missing))
        if schema:
            # The body-slot schema has its own, larger budget.
            block = "\n".join(_cap_lines(schema, "too many slots",
                                          budget=MAX_BODY_SCHEMA_CHARS))
            text += "\n" + block
        return text

    def nonempty(d: Dict[str, Any]) -> List[str]:
        return sorted(k for k, v in d.items()
                      if v not in (None, "", [], {}) and not str(k).startswith("_"))
    # status_effects is no writable key: the overview names the template's
    # stats that hold a value instead (read and written under their own key).
    ov_fields = _template_fields(str(prof.get("template") or "human-default"))
    ov_stats = (prof.get("status_effects")
                if isinstance(prof.get("status_effects"), dict) else {})
    stat_keys = sorted(k for k, f in ov_fields.items()
                       if _field_store(f) == "status"
                       and ov_stats.get(k) not in (None, "", [], {}))
    prof_keys = sorted([k for k in nonempty(prof) if k != "status_effects"] + stat_keys)
    out = [
        f'"{name}" at {prof.get("current_location") or "nowhere"}'
        + (f' / {prof.get("current_room")}' if prof.get("current_room") else ""),
        f'home: {cfg.get("home_location") or "(none)"}'
        + (f' / {cfg.get("home_room")}' if cfg.get("home_room") else ""),
        _known_places_line(cfg),
        "profile fields: " + (", ".join(prof_keys) or "(none)"),
        "config fields: " + (", ".join(nonempty(cfg)) or "(none)"),
    ]
    from app.core.world_dev_apply import _template_has_wardrobe
    if _template_has_wardrobe(str(prof.get("template") or "human-default")):
        names = [str(o.get("name") or "") for o in get_character_outfits(name)]
        out.append("outfits: " + (", ".join(n for n in names if n) or "(none)"))
    else:
        out.append("outfits: (template without outfit system)")
    if _body_specs(prof):
        missing = _missing_body_attrs(name)
        out.append("body slots: " + (f"{len(missing)} attribute(s) unset" if missing
                                     else "all set")
                   + ' — get_character{"fields": ["body_slots"]} shows them')
    return _cut("\n".join(out))


@_tool("read_manual", False, "read_manual{section}",
       "one manual section: " + ", ".join(MANUAL_SECTIONS), pinned=True)
def _read_manual(step: _Step, args: Dict[str, Any]) -> str:
    from app.core import prompt_templates
    _only_keys(args, {"section"}, "read_manual")
    section = _str(args, "section", required=True)
    path = f"world_dev_free/manual_{section}.md"
    if section not in MANUAL_SECTIONS or not prompt_templates.template_exists(path):
        raise ToolRefusal(f"no manual section {section!r} — sections: "
                          + ", ".join(MANUAL_SECTIONS))
    # A manual section is reference text the model asked for by name; it is
    # the one read the 1500-character result cap does not apply to.
    # The characters section lists the offered templates and which of them
    # take outfits.
    extra = ({"character_templates": character_templates()}
             if section == "characters" else {})
    return prompt_templates.render(path, **extra)


# ── Location writes ──────────────────────────────────────────────────────

def _references_to_location(loc_id: str) -> List[str]:
    """Characters naming loc_id as home, known place or schedule slot."""
    from app.models.character import (get_character_config,
                                      get_character_daily_schedule,
                                      list_available_characters)
    out: List[str] = []
    for name in list_available_characters(include_pooled=True):
        cfg = get_character_config(name) or {}
        why = []
        if cfg.get("home_location") == loc_id:
            why.append("home")
        if loc_id in (cfg.get("known_locations") or []):
            why.append("known place")
        slots = (get_character_daily_schedule(name) or {}).get("slots") or []
        if any(isinstance(s, dict) and s.get("location") == loc_id for s in slots):
            why.append("schedule")
        if why:
            out.append(f"{name} ({', '.join(why)})")
    return out


@_tool("create_location", True,
       "create_location{data, x?, z?, yaw?, boundary?:[[x,z],...]}",
       "new place (location schema fields + rooms); boundary in local metres")
def _create_location(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.world_ops import create_location_with_extras
    from app.models.world import (get_location_by_id, list_locations,
                                  update_location_position, world_write_lock)
    _only_keys(args, {"data", "x", "z", "yaw", "boundary"}, "create_location")
    data = args.get("data")
    if not isinstance(data, dict):
        raise ToolRefusal("'data' must be an object with the location fields")
    data = _drop_none(data)
    _check_location_fields(data, "location", creating=True)
    name = _str(data, "name", required=True)
    for i, room in enumerate(data.get("rooms") or []):
        if not _str(room, "name"):
            raise ToolRefusal(f"rooms[{i}] needs a non-empty 'name'")
    x, z, yaw = _coord(args, "x"), _coord(args, "z"), _num(args, "yaw")
    if (x is None) != (z is None):
        raise ToolRefusal("give both x and z, or neither")
    if yaw is not None and x is None:
        raise ToolRefusal("yaw needs x and z")
    boundary = (_points(args["boundary"], "boundary", 3)
                if args.get("boundary") is not None else None)
    body = copy.deepcopy(data)
    body["name"] = name
    body["rooms"] = body.get("rooms") or []
    _normalize_rooms(body["rooms"])
    if boundary is not None:
        body["map3d"] = {**(body.get("map3d") or {}), "boundary": boundary}
    if body.get("map3d") is not None:
        _refuse_map3d_dropped(body["map3d"], body["map3d"])
    # The rooms get their ids from the writer: the entry room is resolved
    # against the body's rooms now and stored by id after the write.
    entry_id, entry_name = "", None
    if "entry_room" in body:
        entry_id, entry_name = _resolve_entry_room(
            body.pop("entry_room"), _entry_room_choices(body["rooms"], body.get("map3d")))
    # Names are not keys: a name the world already has is a second place.
    body["create_new"] = True

    step.prepare()
    with world_write_lock:  # re-entrant; the writers take it again
        ids_before = {str(l.get("id")) for l in list_locations()}
        taken = any(l.get("name") == name for l in list_locations())
        step.begin("location")

        def reconcile():
            new = sorted({str(l.get("id")) for l in list_locations()} - ids_before)
            if not new:
                return None
            if len(new) > 1:
                logger.error("world-dev create_location: %d new ids %s", len(new), new)
            return (new[0], {"op": "delete_location", "id": new[0]},
                    get_location_by_id(new[0]))

        with step.writing(reconcile):
            result = create_location_with_extras(body)
            lid = str(((result or {}).get("location") or {}).get("id") or "")
            if not lid or lid in ids_before:
                raise RuntimeError(f"create_location did not create a new place "
                                   f"(got {lid!r})")
            step.attach(lid, {"op": "delete_location", "id": lid})
            if x is not None:
                update_location_position(lid, x, z, yaw)
            if entry_name is not None:
                _write_entry_room_by_name(lid, entry_name, set())
            elif entry_id:
                from app.core.world_ops import update_location_with_extras
                update_location_with_extras(lid, {"entry_room": entry_id})
                if str((get_location_by_id(lid) or {}).get("entry_room") or "") != entry_id:
                    raise RuntimeError(f"entry room {entry_id!r} was not stored")
        after = get_location_by_id(lid) or {}
        line = f'created location {lid} "{after.get("name") or name}" at {_where(after)}'
        if taken:
            line += (f'; warnings: a place called "{name}" already exists — '
                     f"this is a second one")
        line += completeness.suffix(completeness.location_gaps(after))
        step.complete(after, line)
    return line


def _rooms_removed_by(cur: Dict[str, Any], new_rooms: Optional[List[Dict[str, Any]]],
                      new_map3d: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The stored rooms (and corridors) a patch would take away — simulated
    with the corridor sync the writers run (ensure_floor_rooms)."""
    from app.core.world_ops import _sanitize_map3d
    from app.models.world import GROUND_ROOM_ID, ensure_floor_rooms
    stored = [r for r in cur.get("rooms") or [] if isinstance(r, dict)]
    sim = copy.deepcopy(new_rooms if new_rooms is not None else stored)
    m3 = _sanitize_map3d(new_map3d) if new_map3d is not None else cur.get("map3d")
    ensure_floor_rooms(sim, m3, previous=copy.deepcopy(stored))
    kept = {str(r.get("id") or "") for r in sim if isinstance(r, dict)}
    # The ground comes back with every location write.
    return [r for r in stored
            if str(r.get("id") or "") not in kept and r.get("id") != GROUND_ROOM_ID]


def _room_users(loc_id: str, rooms: List[Dict[str, Any]]) -> List[str]:
    """One text per character standing in, or living in, one of the rooms."""
    from app.models.character import (get_character_config, list_available_characters,
                                      list_character_places)
    ids = {str(r.get("id")): r for r in rooms}
    out: List[str] = []
    if not ids:
        return out
    for name, (lid, room) in list_character_places().items():
        if lid == loc_id and room in ids:
            out.append(f'room "{ids[room].get("name") or room}" ({room}): '
                       f"{name} stands there")
    for name in list_available_characters(include_pooled=True):
        cfg = get_character_config(name) or {}
        room = str(cfg.get("home_room") or "")
        if cfg.get("home_location") == loc_id and room in ids:
            out.append(f'room "{ids[room].get("name") or room}" ({room}): '
                       f"home room of {name}")
    return out


def _merge_rooms(stored_rooms: List[Dict[str, Any]],
                 sent: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The room list to write for a rooms patch. The writer replaces the list
    wholesale and keeps only "items" of a stored room, while the tool lets the
    model send only the whitelisted keys — so a kept room (sent with its id)
    is the stored room with the sent keys laid over it: layout, level,
    activities, items and every other stored key survive. Stored reserved
    rooms (ground, corridors) the model did not send stay as stored; the
    writer's corridor sync still drops a corridor whose storey lost its last
    room."""
    by_id = {str(r.get("id")): r for r in stored_rooms if r.get("id")}
    for room in sent:
        if "image_prompt" in room:
            prompt = room.pop("image_prompt")
            room.setdefault("image_prompt_day", prompt)
    out: List[Dict[str, Any]] = []
    for room in sent:
        old = by_id.get(str(room.get("id") or ""))
        if old is not None:
            merged = copy.deepcopy(old)
            merged.update(copy.deepcopy(room))
            out.append(merged)
        else:
            new = copy.deepcopy(room)
            new.setdefault("image_prompt_night", "")
            out.append(new)
    sent_ids = {str(r.get("id")) for r in out if r.get("id")}
    for room in stored_rooms:
        rid = str(room.get("id") or "")
        if rid.startswith("__") and rid not in sent_ids:
            out.append(copy.deepcopy(room))
    return out


@_tool("update_location", True, "update_location{id, patch}",
       "change fields of a place; rooms = the whole list (keep ids of kept rooms)")
def _update_location(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.world_ops import update_location_with_extras
    from app.models.world import get_location_by_id, world_write_lock
    _only_keys(args, {"id", "patch"}, "update_location")
    lid = _str(args, "id", required=True)
    patch = args.get("patch")
    if not isinstance(patch, dict) or not patch:
        raise ToolRefusal("'patch' must be a non-empty object of location fields")
    patch = _drop_none(patch)
    if not patch:
        raise ToolRefusal("'patch' has only null values — nothing to change")
    _check_location_fields(patch, "patch")
    if "name" in patch and not str(patch["name"] or "").strip():
        raise ToolRefusal("'name' must not be empty")
    body = copy.deepcopy(patch)

    # Cheap pre-check before the backup (a mistyped id on the run's first
    # write must not copy the world); the read under the lock decides.
    if get_location_by_id(lid) is None:
        raise ToolRefusal(f"no location {lid!r} — use find_locations")
    step.prepare()
    with world_write_lock:
        cur = get_location_by_id(lid)
        if cur is None:
            raise ToolRefusal(f"no location {lid!r} — use find_locations")
        stored_rooms = [r for r in cur.get("rooms") or [] if isinstance(r, dict)]
        if body.get("rooms") is not None:
            by_id = {str(r.get("id")): r for r in stored_rooms}
            sent_ids = {str(r.get("id")) for r in body["rooms"] if r.get("id")}
            for room in body["rooms"]:
                rid = room.get("id")
                if rid and str(rid) not in by_id:
                    raise ToolRefusal(f"room id {rid!r} does not exist in {lid} — "
                                      f"omit the id for a new room")
                if not rid and not _str(room, "name"):
                    raise ToolRefusal("a new room needs a non-empty 'name'")
                if not rid:
                    same = [r for r in stored_rooms
                            if r.get("name") == room.get("name")
                            and str(r.get("id")) not in sent_ids]
                    if same:
                        raise ToolRefusal(
                            f'room "{room.get("name")}" exists ({same[0].get("id")}) '
                            f"— send its id to keep it")
            body["rooms"] = _merge_rooms(stored_rooms, body["rooms"])
        if body.get("map3d") is not None:
            # A patch changes the map3d keys it names; the writer replaces the
            # whole object, so the stored keys are merged back in.
            sent_m3 = body["map3d"]
            body["map3d"] = {**(cur.get("map3d") or {}), **sent_m3}
            _refuse_map3d_dropped(sent_m3, body["map3d"])
        if body.get("rooms") is not None or body.get("map3d") is not None:
            # The undo cannot put characters back into a removed room.
            removed = _rooms_removed_by(cur, body.get("rooms"), body.get("map3d"))
            users = _room_users(lid, removed)
            if users:
                raise ToolRefusal("the patch would remove a room in use — "
                                  + "; ".join(users))
            # The writer keeps a stale entry_room id; never leave it dangling.
            entry_now = str(cur.get("entry_room") or "")
            gone = next((r for r in removed if str(r.get("id") or "") == entry_now), None)
            if entry_now and gone is not None and "entry_room" not in body:
                raise ToolRefusal(
                    f'the patch removes the entry room "{gone.get("name") or entry_now}" '
                    f"({entry_now}) — send entry_room too (\"\" = arrive on the ground)")
        entry_name = None
        if "entry_room" in body:
            # An existing room is sent by its id; one this call adds has no id
            # yet and is stored by name after the write, in this same step.
            rooms_after = body["rooms"] if body.get("rooms") is not None else stored_rooms
            m3_after = body["map3d"] if body.get("map3d") is not None else cur.get("map3d")
            entry_id, entry_name = _resolve_entry_room(
                body["entry_room"],
                _entry_room_choices(rooms_after, m3_after, stored_rooms))
            if entry_name is None:
                body["entry_room"] = entry_id
            else:
                body.pop("entry_room")
        old_ids = {str(r.get("id") or "") for r in stored_rooms}
        before = copy.deepcopy(cur)
        # Until the exact diff is known the inverse restores the whole record,
        # so a crash between the write and the attach is still undone.
        step.begin("location", lid, {"op": "restore_location", "id": lid,
                                     "before": before})

        def reconcile():
            b, w = wu.diff_keys(before, get_location_by_id(lid))
            if not b:
                return None
            return lid, {"op": "restore_location", "id": lid, "before": b}, w

        with step.writing(reconcile):
            update_location_with_extras(lid, body)
            if entry_name is not None:
                _write_entry_room_by_name(lid, entry_name, old_ids)
            elif "entry_room" in body:
                stored_entry = str((get_location_by_id(lid) or {}).get("entry_room") or "")
                if stored_entry != body["entry_room"]:
                    raise RuntimeError(f"entry room {body['entry_room']!r} was not "
                                       f"stored (got {stored_entry!r})")
        after = get_location_by_id(lid) or {}
        b, w = wu.diff_keys(before, after)
        step.attach(lid, {"op": "restore_location", "id": lid, "before": b},
                    before=b)
        line = (f'updated location {lid} "{after.get("name") or ""}": '
                + (", ".join(sorted(b)) if b else "no change")
                + completeness.location_suffix(step.ctx.run_id, after))
        step.complete(w, line)
    return line


@_tool("place_location", True, "place_location{id, x, z, yaw?}",
       "move a place on the map (metres; yaw in degrees)")
def _place_location(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.world import (get_location_by_id, update_location_position,
                                  world_write_lock)
    _only_keys(args, {"id", "x", "z", "yaw"}, "place_location")
    lid = _str(args, "id", required=True)
    x, z, yaw = _coord(args, "x", True), _coord(args, "z", True), _num(args, "yaw")
    if get_location_by_id(lid) is None:  # pre-check before the backup
        raise ToolRefusal(f"no location {lid!r} — use find_locations")
    step.prepare()
    with world_write_lock:
        cur = get_location_by_id(lid)
        if cur is None:
            raise ToolRefusal(f"no location {lid!r} — use find_locations")
        before = wu.position_of(cur)
        inverse = {"op": "restore_position", "id": lid, "before": before}
        step.begin("location", lid, inverse)

        def reconcile():
            now = wu.position_of(get_location_by_id(lid))
            return None if now == before else (lid, inverse, now)

        with step.writing(reconcile):
            update_location_position(lid, x, z, yaw)
        after = get_location_by_id(lid) or {}
        # The journal row is begun above, so this call's position write is
        # already part of the location's scope.
        line = (f'placed location {lid} "{after.get("name") or ""}" at {_where(after)}'
                + completeness.location_suffix(step.ctx.run_id, after))
        step.complete(wu.position_of(after), line)
    return line


# ── Terrain and height areas ─────────────────────────────────────────────

def _sanitize_layout(key: str, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """One area through sanitize_map_layout with the real world context;
    refused (with the warning texts) when the sanitizer drops it."""
    from app.core.map_layout_apply import sanitize_map_layout
    from app.core.world_dev_apply import _map_world_context
    catalog, locations_by_id, bounds, default_kind = _map_world_context()
    normalized, warnings = sanitize_map_layout(
        {key: [raw]}, catalog=catalog, locations_by_id=locations_by_id,
        bounds=bounds, default_kind=default_kind)
    texts = [str(w.get("message") or w.get("code") or "") for w in warnings]
    if not normalized.get(key):
        raise ToolRefusal("; ".join(t for t in texts if t) or "area dropped")
    return normalized[key][0], texts


def _geometry_raw(args: Dict[str, Any], fallback_polygon: Any = None) -> Dict[str, Any]:
    if args.get("polygon") is not None and args.get("stroke") is not None:
        raise ToolRefusal("give polygon OR stroke, not both")
    if args.get("polygon") is not None:
        return {"polygon": _points(args["polygon"], "polygon", 3)}
    if args.get("stroke") is not None:
        stroke = args["stroke"]
        if not isinstance(stroke, dict):
            raise ToolRefusal("'stroke' must be an object {points, width_m, style?}")
        _only_keys(stroke, {"points", "width_m", "style", "spacing_m", "amplitude_m"},
                   "stroke")
        _points(stroke.get("points"), "stroke.points", 2)
        _num(stroke, "width_m", True)
        _str(stroke, "style")
        _num(stroke, "spacing_m")
        _num(stroke, "amplitude_m")
        return {"stroke": copy.deepcopy(stroke)}
    if fallback_polygon is not None:
        return {"polygon": fallback_polygon}
    raise ToolRefusal("give a polygon [[x,z],...] or a stroke {points, width_m}")


def _new_id(prefix: str, exists: Callable[[str], bool]) -> str:
    """An area id chosen BEFORE the write, so the inverse is known at begin."""
    for _ in range(20):
        candidate = f"{prefix}_{secrets.token_hex(4)}"
        if not exists(candidate):
            return candidate
    raise RuntimeError("no free area id")


def _warn_suffix(texts: List[str]) -> str:
    texts = [t for t in texts if t]
    return f"; warnings: {'; '.join(texts)}" if texts else ""


@_tool("add_terrain_area", True,
       "add_terrain_area{kind, polygon | stroke:{points, width_m, style?}, label?, z_order?}",
       "paint ground of a terrain kind (world metres)")
def _add_terrain_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.terrain import get_area, save_area
    _only_keys(args, {"kind", "polygon", "stroke", "label", "z_order"}, "add_terrain_area")
    raw: Dict[str, Any] = {"kind": _str(args, "kind", required=True)}
    raw.update(_geometry_raw(args))
    label = _str(args, "label")
    if label:
        raw["label"] = label
    z_order = _num(args, "z_order")
    if z_order is not None:
        raw["z_order"] = z_order
    area, warnings = _sanitize_layout("terrain_areas", raw)
    aid = _new_id("ta", lambda i: get_area(i) is not None)
    row = copy.deepcopy(area)
    row["id"] = aid
    inverse = {"op": "delete_terrain_area", "id": aid}
    step.prepare()
    step.begin("terrain", aid, inverse)

    def reconcile():
        stored = get_area(aid)
        return None if stored is None else (aid, inverse, stored)

    with step.writing(reconcile):
        save_area(row)
    written = get_area(aid)
    label_txt = f' "{label}"' if label else ""
    line = (f"added terrain area {aid} ({row['kind']}){label_txt} "
            f"{_fmt_box(_bbox((written or row).get('polygon')))}{_warn_suffix(warnings)}")
    step.complete(written, line)
    return line


@_tool("update_terrain_area", True,
       "update_terrain_area{id, kind?, polygon? | stroke?, label?, z_order?}",
       "reshape/relabel an area; everything else on it is kept")
def _update_terrain_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.terrain import get_area, save_area
    _only_keys(args, {"id", "kind", "polygon", "stroke", "label", "z_order"},
               "update_terrain_area")
    aid = _str(args, "id", required=True)
    kind = _str(args, "kind")
    label = _str(args, "label")
    z_order = _num(args, "z_order")
    new_geom = args.get("polygon") is not None or args.get("stroke") is not None
    if not new_geom and kind is None and label is None and z_order is None:
        raise ToolRefusal("nothing to change — give kind, polygon/stroke, label or z_order")
    if args.get("polygon") is not None or args.get("stroke") is not None:
        _geometry_raw(args)  # shape errors refused before the backup
    # The backup first, then ONE read that is both the merge base and
    # "before": a second read after a long backup copy would let a foreign
    # edit in between be overwritten by a row built from the older read.
    if get_area(aid) is None:  # cheap pre-check before the backup
        raise ToolRefusal(f"no terrain area {aid!r} — use map_region")
    step.prepare()
    stored = get_area(aid)
    if stored is None:
        raise ToolRefusal(f"no terrain area {aid!r} — use map_region")
    before = copy.deepcopy(stored)
    warnings: List[str] = []
    norm: Dict[str, Any] = {}
    if new_geom or kind is not None:
        # Only the NEW geometry/kind is normalised; the stored outline only
        # rides along when the kind alone changes (the sanitizer needs one).
        raw: Dict[str, Any] = {"kind": kind if kind is not None else stored.get("kind")}
        raw.update(_geometry_raw(args, fallback_polygon=stored.get("polygon")))
        norm, warnings = _sanitize_layout("terrain_areas", raw)
        if not new_geom:
            warnings = []
    # The stored row is merged, never rebuilt: id and every other meta key
    # (scatter, water, relief, slots, ...) stay as they are.
    row = copy.deepcopy(stored)
    meta = row.setdefault("meta", {})
    if kind is not None:
        row["kind"] = norm["kind"]
    if new_geom:
        row["polygon"] = norm["polygon"]
        if (norm.get("meta") or {}).get("stroke"):
            new_stroke = norm["meta"]["stroke"]
            old_stroke = meta.get("stroke")
            # The rows of props along the line (meta.stroke.along) are not
            # a key of the tool's stroke, so a reshaped stroke keeps them.
            if (isinstance(old_stroke, dict) and old_stroke.get("along")
                    and "along" not in new_stroke):
                new_stroke = {**new_stroke,
                              "along": copy.deepcopy(old_stroke["along"])}
            meta["stroke"] = new_stroke
        else:
            meta.pop("stroke", None)
    if label is not None:
        if label:
            meta["label"] = label
        else:
            meta.pop("label", None)
    if z_order is not None:
        row["z_order"] = int(z_order)
    inverse = {"op": "restore_terrain_area", "row": before}
    step.begin("terrain", aid, inverse)

    def reconcile():
        now = get_area(aid)
        return None if now == before else (aid, inverse, now)

    with step.writing(reconcile):
        save_area(row, must_exist=True)
    written = get_area(aid) or {}
    changed = [k for k in ("kind", "polygon", "z_order", "meta")
               if written.get(k) != before.get(k)]
    line = (f"updated terrain area {aid} ({written.get('kind') or row.get('kind')}): "
            + (", ".join(changed) or "no change") + _warn_suffix(warnings))
    step.complete(written, line)
    return line


def _height_area(aid: str) -> Optional[Dict[str, Any]]:
    from app.models.heightfield import list_height_areas
    return next((a for a in list_height_areas() if a.get("id") == aid), None)


@_tool("add_height_area", True,
       "add_height_area{polygon, height_m, falloff_m?, label?}",
       "raise (or lower) the ground inside a polygon (world metres)")
def _add_height_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.heightfield import save_height_area
    _only_keys(args, {"polygon", "height_m", "falloff_m", "label"}, "add_height_area")
    raw: Dict[str, Any] = {"polygon": _points(args.get("polygon"), "polygon", 3),
                           "height_m": _num(args, "height_m", True)}
    falloff = _num(args, "falloff_m")
    if falloff is not None:
        raw["falloff_m"] = falloff
    label = _str(args, "label")
    if label:
        raw["label"] = label
    area, warnings = _sanitize_layout("height_areas", raw)
    aid = _new_id("ha", lambda i: _height_area(i) is not None)
    row = copy.deepcopy(area)
    row["id"] = aid
    inverse = {"op": "delete_height_area", "id": aid}
    step.prepare()
    step.begin("height", aid, inverse)

    def reconcile():
        stored = _height_area(aid)
        return None if stored is None else (aid, inverse, stored)

    with step.writing(reconcile):
        save_height_area(row)
    written = _height_area(aid)
    line = (f"added height area {aid} {_g((written or row).get('height_m'))} m "
            f"{_fmt_box(_bbox(row.get('polygon')))}{_warn_suffix(warnings)}")
    step.complete(written, line)
    return line


@_tool("update_height_area", True,
       "update_height_area{id, polygon?, height_m?, falloff_m?, label?}",
       "reshape or change the height of a height area")
def _update_height_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.heightfield import save_height_area
    _only_keys(args, {"id", "polygon", "height_m", "falloff_m", "label"},
               "update_height_area")
    aid = _str(args, "id", required=True)
    height = _num(args, "height_m")
    falloff = _num(args, "falloff_m")
    label = _str(args, "label")
    polygon = (_points(args["polygon"], "polygon", 3)
               if args.get("polygon") is not None else None)
    if polygon is None and height is None and falloff is None and label is None:
        raise ToolRefusal("nothing to change — give polygon, height_m, falloff_m or label")
    # Backup first, then one read = merge base and "before" (see
    # update_terrain_area).
    if _height_area(aid) is None:  # cheap pre-check before the backup
        raise ToolRefusal(f"no height area {aid!r} — use map_region")
    step.prepare()
    stored = _height_area(aid)
    if stored is None:
        raise ToolRefusal(f"no height area {aid!r} — use map_region")
    before = copy.deepcopy(stored)
    raw = {"polygon": polygon if polygon is not None else stored.get("polygon"),
           "height_m": height if height is not None else stored.get("height_m"),
           "falloff_m": falloff if falloff is not None else stored.get("falloff_m")}
    norm, warnings = _sanitize_layout("height_areas", raw)
    if polygon is None:
        warnings = []
    row = copy.deepcopy(stored)
    if polygon is not None:
        row["polygon"] = norm["polygon"]
    if height is not None:
        row["height_m"] = norm["height_m"]
    if falloff is not None:
        row["falloff_m"] = norm["falloff_m"]
    if label is not None:
        meta = row.setdefault("meta", {})
        if label:
            meta["label"] = label
        else:
            meta.pop("label", None)
    inverse = {"op": "restore_height_area", "row": before}
    step.begin("height", aid, inverse)

    def reconcile():
        now = _height_area(aid)
        return None if now == before else (aid, inverse, now)

    with step.writing(reconcile):
        save_height_area(row, must_exist=True)
    written = _height_area(aid) or {}
    changed = [k for k in ("polygon", "height_m", "falloff_m", "meta")
               if written.get(k) != before.get(k)]
    line = (f"updated height area {aid}: " + (", ".join(changed) or "no change")
            + _warn_suffix(warnings))
    step.complete(written, line)
    return line


# ── Character writes ─────────────────────────────────────────────────────

#: Keys of a create_character draft besides the template fields.
_CHAR_DRAFT_SPECIAL = {"character_name", "template", "outfits", "body_slots",
                       "home_location", "home_room", "daily_schedule", "wear",
                       "known_places"}
#: update_character patch keys for home and daily schedule -> the draft key
#: world_dev_apply._apply_home_and_schedule reads.
#: Exactly one spelling each (the tool signature's); the draft spellings
#: home_location / daily_schedule are refused in a patch, so two spellings
#: of one value can never silently override each other.
_HOME_PATCH_KEYS = {"home": "home_location", "home_room": "home_room",
                    "schedule": "daily_schedule", "known_places": "known_places"}
#: Draft keys of the home group -> the patch / argument key to use instead.
_HOME_DRAFT_SPELLINGS = {"home_location": "home", "daily_schedule": "schedule"}
_OUTFIT_KEYS = {"name", "outfit", "pieces"}
#: Outfit keys of the old outfit-type model: no reader exists any more (an
#: outfit is chosen by the wardrobe and outfit compliance, never by place or
#: activity) — refused with their own text, never dropped in silence.
_DEAD_OUTFIT_KEYS = ("locations", "activities", "excluded_locations")
_PIECE_KEYS = {"item_id", "slots", "name", "prompt_fragment", "description",
               "covers", "partially_covers"}


def character_templates() -> List[Dict[str, Any]]:
    """The templates create_character offers, by name: ``[{name, label,
    outfits}]`` — the selectable character templates without the
    temporary-NPC feature (a temporary NPC comes from the NPC pipeline,
    npc_ops, which owns its slot, home and rhythm); ``outfits`` says whether
    the template has the outfit system (``features.outfit_system_enabled``
    not false), i.e. whether a character of it can be given outfits."""
    from app.core.world_dev_apply import _template_has_wardrobe
    from app.models.character_template import get_template, list_templates
    out = []
    for t in list_templates("character"):
        tmpl = get_template(t["name"]) or {}
        if (tmpl.get("features") or {}).get("temporary_npc"):
            continue
        out.append({"name": t["name"], "label": str(t.get("label") or t["name"]),
                    "outfits": _template_has_wardrobe(t["name"])})
    return sorted(out, key=lambda t: t["name"])


def _templates_line(templates: List[Dict[str, Any]]) -> str:
    return ", ".join(f"{t['name']} ({'outfits' if t['outfits'] else 'no outfits'})"
                     for t in templates)


def _refuse_outfits(template: str, templates: List[Dict[str, Any]]) -> None:
    """A template without the outfit system takes no outfits — refused before
    any write (apply_character would only drop them with a warning)."""
    with_outfits = [t["name"] for t in templates if t["outfits"]]
    raise ToolRefusal(f"template {template!r} has no outfit system — a character of "
                      f"it cannot be given outfits; templates with outfits: "
                      + (", ".join(with_outfits) or "none"))


def _template_fields(template: str) -> Dict[str, Dict[str, Any]]:
    """Every field of the (merged) character template by key; {} when the
    template does not exist."""
    from app.models.character_template import get_template
    out: Dict[str, Dict[str, Any]] = {}
    for section in (get_template(template) or {}).get("sections", []) or []:
        for field in section.get("fields", []) or []:
            key = str(field.get("key") or "")
            if key:
                out[key] = field
    return out


def _field_store(field: Dict[str, Any]) -> str:
    """Where a template field's value lives: "soul" (a soul section file),
    "config", "status" (a stat inside profile.status_effects) or
    "profile"."""
    if field.get("source_file"):
        return "soul"
    store = str(field.get("store") or "")
    if store == "config":
        return "config"
    if store == "status_effects":
        return "status"
    return "profile"


def _settable_fields(template: str) -> Dict[str, Dict[str, Any]]:
    """Every field of the template the free tools may set: all except
    readonly ones and the identity keys (character_name, template); soul
    fields included."""
    return {k: f for k, f in _template_fields(template).items()
            if not f.get("readonly") and k not in ("character_name", "template")}


def _check_stat_value(key: str, value: Any) -> None:
    """A stat is a whole number 0-100 (the range every stat reader clamps
    to)."""
    # Range first: the whole-number test converts, which a huge integer
    # (10**400) would overflow.
    if not _is_num(value) or not 0 <= value <= 100 or float(value) != int(value):
        raise ToolRefusal(f"'{key}' must be a whole number 0-100")


def _write_char_fields(name: str, prof: Dict[str, Any], cfg: Dict[str, Any],
                       stats: Dict[str, Any]) -> None:
    """One read-modify-write of a character's profile and config under the
    profile lock: profile keys set, ``status_effects`` merged with
    ``stats`` (whole numbers), config keys set — raw JSON values, numbers
    stay numbers. A save that reports False is a ValueError."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (get_character_config, get_character_profile,
                                      save_character_config, save_character_profile)
    if not (prof or cfg or stats):
        return
    with keyed_lock("character_profile", name):
        if prof or stats:
            profile = copy.deepcopy(get_character_profile(name) or {})
            profile.update(copy.deepcopy(prof))
            if stats:
                cur = profile.get("status_effects")
                merged = dict(cur) if isinstance(cur, dict) else {}
                merged.update({k: int(v) for k, v in stats.items()})
                profile["status_effects"] = merged
            # Soul values are injected on read; they never go back through a
            # profile save (the MD file is the source).
            template = str(profile.get("template") or "")
            for k, f in _template_fields(template).items():
                if f.get("source_file"):
                    profile.pop(k, None)
            if not save_character_profile(name, profile):
                raise ValueError(f"the profile of {name} was not stored")
        if cfg:
            config = copy.deepcopy(get_character_config(name) or {})
            config.update(copy.deepcopy(cfg))
            if not save_character_config(name, config):
                raise ValueError(f"the config of {name} was not stored")


def _same_option(value: Any, option: Any) -> bool:
    """A value matches a select option only with the option's own JSON type
    (the number 2 for importance, never the string "2"; never a bool)."""
    if isinstance(option, str):
        return isinstance(value, str) and value == option
    if _is_num(option):
        return _is_num(value) and float(value) == float(option)
    return False


def _expression_set_keys() -> List[str]:
    from app.core.expression_sets import sets_payload
    return sorted(sets_payload())


def _animation_set_keys() -> List[str]:
    from app.core.animation_sets import available_sets
    return list(available_sets())


# A select field's ``source`` -> the values the editor offers for it.
_SELECT_SOURCES: Dict[str, Callable[[], List[str]]] = {
    "expression_sets": _expression_set_keys,
    "animation_sets": _animation_set_keys,
}


def _select_values(field: Dict[str, Any]) -> Optional[List[Any]]:
    """The values a select field takes: its fixed option values (no
    ``source``), the resolved source list (``source`` set), None when it
    has neither or names a source this tool cannot resolve."""
    source = field.get("source")
    if source:
        resolve = _SELECT_SOURCES.get(str(source))
        return list(resolve()) if resolve else None
    options = [o["value"] for o in field.get("options") or []
               if isinstance(o, dict) and "value" in o]
    return options or None


def _check_field_value(key: str, field: Dict[str, Any], value: Any) -> None:
    """The template field type decides what a value may be:
    text/textarea -> string; number -> number; select with fixed options (no
    ``source``, no ``allow_custom``) -> one of the option values in the
    option's JSON type; fixed options + ``allow_custom`` -> any string; a
    select with a ``source`` -> "" (derived automatically) or one of the
    source's values; a select with neither -> refused (its values come from
    live backends); season_day -> a "<season>:<day>" of this world's
    calendar ("" clears it). A field type this tool does not know is refused
    rather than stored unchecked. A stat (store status_effects) is a whole
    number 0-100."""
    if _field_store(field) == "status":
        _check_stat_value(key, value)
        return
    kind = str(field.get("type") or "")
    if kind in ("text", "textarea"):
        if not isinstance(value, str):
            raise ToolRefusal(f"'{key}' must be a string")
        return
    if kind == "number":
        if not _is_num(value):
            raise ToolRefusal(f"'{key}' must be a number")
        return
    if kind == "select":
        values = _select_values(field)
        if values is None:
            raise ToolRefusal(f"'{key}' cannot be checked here — set it in the "
                              "character editor")
        if field.get("source"):
            if not isinstance(value, str) or (value and value not in values):
                raise ToolRefusal(f"'{key}' must be one of: "
                                  + ", ".join(json.dumps(v, ensure_ascii=False)
                                              for v in [""] + list(values)))
            return
        if not field.get("allow_custom"):
            if not any(_same_option(value, o) for o in values):
                raise ToolRefusal(f"'{key}' must be one of: "
                                  + ", ".join(json.dumps(o, ensure_ascii=False)
                                              for o in values))
            return
        if not isinstance(value, str):
            raise ToolRefusal(f"'{key}' must be a string")
        return
    if kind == "season_day":
        from app.core.game_time import get_calendar, parse_season_day
        if not isinstance(value, str) or (value.strip()
                                          and parse_season_day(value) is None):
            seasons = ", ".join(f"{s.key} 1-{s.days}" for s in get_calendar().seasons)
            raise ToolRefusal(f"'{key}' must be \"<season>:<day>\" of this world's "
                              f"calendar ({seasons}), e.g. \"spring:14\"")
        return
    raise ToolRefusal(f"'{key}' (field type {kind or 'unknown'}) cannot be set "
                      "with this tool")


def _check_str_list(value: Any, what: str) -> None:
    if value is not None and (not isinstance(value, list)
                              or not all(isinstance(v, str) for v in value)):
        raise ToolRefusal(f"'{what}' must be a list of strings")


def _storable_piece_slots(profile: Dict[str, Any]) -> List[str]:
    """The clothing slots a new outfit piece of this (would-be) profile may
    name: the character's slots (``body_slots.piece_slots_for_profile``: the
    species', else the core ones) that the catalog can store — it keeps only
    core slots (``inventory._clean_piece_slots``), so a species slot outside
    them could never be stored. One list for describe_template and
    _check_outfits."""
    from app.core.body_slots import piece_slots_for_profile
    from app.models.inventory import VALID_PIECE_SLOTS
    return [s for s in piece_slots_for_profile(profile) if s in VALID_PIECE_SLOTS]


_NO_STORABLE_SLOTS = ("this template has no clothing slots the catalog can store "
                      "— give existing pieces by item_id only")


def _check_outfits(outfits: Any, allowed: Sequence[str]) -> None:
    """Shape of the draft's outfits; a piece is either a NEW piece {slots,
    name, ...} or an existing catalog piece {item_id}. A new piece's slots
    come from ``allowed`` (``_storable_piece_slots`` of the character)."""
    from app.models.inventory import get_item
    if not isinstance(outfits, list):
        raise ToolRefusal("'outfits' must be a list of outfit objects")
    for i, outfit in enumerate(outfits):
        where = f"outfits[{i}]"
        if not isinstance(outfit, dict):
            raise ToolRefusal(f"{where} must be an object")
        for key in _DEAD_OUTFIT_KEYS:
            if key in outfit:
                raise ToolRefusal(f"{where}: outfits are not bound to places or "
                                  f"activities — leave out '{key}'")
        _only_keys(outfit, _OUTFIT_KEYS, where)
        try:
            _str(outfit, "name", required=True)
            _str(outfit, "outfit")
        except ToolRefusal as exc:
            raise ToolRefusal(f"{where}: {exc}")
        pieces = outfit.get("pieces")
        if pieces is None:
            continue
        if not isinstance(pieces, list):
            raise ToolRefusal(f"{where}.pieces must be a list of piece objects")
        for j, piece in enumerate(pieces):
            pw = f"{where}.pieces[{j}]"
            if not isinstance(piece, dict):
                raise ToolRefusal(f"{pw} must be an object")
            _only_keys(piece, _PIECE_KEYS, pw)
            try:
                if piece.get("item_id") is not None:
                    iid = _str(piece, "item_id", required=True)
                    item = get_item(iid)
                    if not item or item.get("category") != "outfit_piece":
                        raise ToolRefusal(f"no outfit piece with item_id {iid!r}")
                    if set(piece) - {"item_id"}:
                        raise ToolRefusal("an existing piece is given by item_id "
                                          "alone")
                    continue
                _str(piece, "name", required=True)
                for key in ("prompt_fragment", "description"):
                    _str(piece, key)
                _check_str_list(piece.get("slots"), "slots")
                slots = [s.strip().lower() for s in piece.get("slots") or []]
                if not allowed:
                    raise ToolRefusal(_NO_STORABLE_SLOTS)
                if not slots or any(s not in allowed for s in slots):
                    raise ToolRefusal("'slots' must name at least one of "
                                      + ", ".join(allowed))
                for key in ("covers", "partially_covers"):
                    _check_str_list(piece.get(key), key)
            except ToolRefusal as exc:
                raise ToolRefusal(f"{pw}: {exc}")


def _starting_outfit_name(wear: Any, outfits: Any) -> Optional[str]:
    """The stored name of the outfit a new character starts in: ``wear``
    names one of ``outfits`` (case-insensitive); without ``wear`` the
    first outfit; None without outfits. Refused: a ``wear`` that is no
    string, names no outfit, or comes without outfits."""
    names = [str(o.get("name") or "").strip() for o in outfits or []
             if isinstance(o, dict)]
    if wear is None:
        return names[0] if names else None
    if not isinstance(wear, str) or not wear.strip():
        raise ToolRefusal("'wear' must be the name of one of data.outfits")
    if not names:
        raise ToolRefusal("'wear' names an outfit of data.outfits — there are none")
    for n in names:
        if n.casefold() == wear.strip().casefold():
            return n
    raise ToolRefusal(f"'wear' {wear!r} is none of the outfits: "
                      + ", ".join(json.dumps(n, ensure_ascii=False) for n in names))


def _wear_starting_outfit(name: str, outfit_name: str) -> Tuple[str, List[str], List[str]]:
    """Dress a just-created character in its outfit set ``outfit_name``
    (inside the create step: ``delete_character`` takes the equip and its
    outfit-history rows back). Under the profile lock, like the wardrobe
    route; ``apply_equipped_pieces`` takes no places lock, so the lock
    order holds. Its answer is not trusted — it reports the pieces applied
    even when the profile save returned False — so the worn state is read
    again: a piece it applied that is not worn is a ValueError (the render
    timers its outfit-change notice armed are disarmed first). Returns
    (outfit name, worn slots in the character's slot order, warnings for
    every piece of the set that is not worn — the ones the apply skipped,
    and the ones it never saw because another piece of the set has the same
    first slot (``outfit_set_pieces_by_slot`` keeps one piece per slot))."""
    from app.core.body_slots import piece_slots_for_profile
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_outfits, get_character_profile
    from app.models.inventory import (apply_equipped_pieces, get_equipped_pieces,
                                      get_item, outfit_set_pieces_by_slot)
    with keyed_lock("character_profile", name):
        target = next((o for o in get_character_outfits(name)
                       if str(o.get("name") or "").strip() == outfit_name), None)
        if target is None:
            raise ValueError(f"the starting outfit {outfit_name!r} was not stored")
        result = apply_equipped_pieces(
            name, pieces=outfit_set_pieces_by_slot(target),
            remove_slots=list(target.get("remove_slots") or []), source="world_dev")
        worn = get_equipped_pieces(name)
        order = piece_slots_for_profile(get_character_profile(name) or {})
    if any(worn.get(a.get("slot")) != a.get("item_id")
           for a in result.get("applied") or []):
        # apply_equipped_pieces notified the outfit change although nothing
        # was stored: the render timers it armed would render a character
        # that wears nothing. Disarm them (the history row it wrote is the
        # create step's, taken back by its delete_character inverse).
        from app.core.model_refs import cancel_character_timers
        cancel_character_timers(name)
        raise ValueError("the starting outfit was not stored")
    slots = [s for s in order if s in worn] + sorted(s for s in worn if s not in order)
    warnings = [f"starting outfit {outfit_name}: piece {s.get('item_id')} not worn "
                f"({s.get('reason')})" for s in result.get("skipped") or []]
    reported = {str(s.get("item_id")) for s in result.get("skipped") or []}
    worn_ids = set(worn.values())
    for pid in target.get("pieces") or []:
        if pid in worn_ids or pid in reported:
            continue
        reported.add(pid)
        has_slot = bool(((get_item(pid) or {}).get("outfit_piece") or {}).get("slots"))
        warnings.append(f"starting outfit {outfit_name}: piece {pid} not worn ("
                        + ("another piece of the outfit takes its slot" if has_slot
                           else "it declares no slot") + ")")
    return outfit_name, slots, warnings


def _place_compliance(name: str) -> List[str]:
    """The one outfit-compliance run of a just-created character, AFTER it
    is dressed (``apply_character(place_compliance=False)`` skipped the run
    on placement, which judged the character before its starting outfit
    was on and left a wrong "missing" notification behind). Only for a
    character that stands somewhere. The auto-filled slots are the
    character's own and go with the create step's ``delete_character``
    inverse. It writes NO violation notice (``notify=False``): a notice can
    evict the oldest row of the bounded notification window, which no
    inverse brings back — a remaining violation comes back as a warning for
    the tool line instead."""
    from app.models.character import get_character_current_location
    if not get_character_current_location(name):
        return []
    from app.core.outfit_compliance import apply_outfit_compliance
    try:
        res = apply_outfit_compliance(name, notify=False)
    except Exception as e:  # noqa: BLE001 — the character is created
        logger.warning("WorldDev: outfit compliance for %s failed: %s", name, e)
        return []
    slots = sorted({str(v.get("slot")) for v in res.get("violations") or []
                    if v.get("reason") in ("no_inventory_piece",
                                           "forced_piece_not_equipped",
                                           "outfit_not_worn")})
    if not slots:
        return []
    return [f"outfit does not fit the {res.get('decency') or 'current'} place — "
            f"missing: {', '.join(slots)}"]


def _check_outfit_refs_reveal(outfits: Any) -> None:
    """An existing catalog piece that reveals a secret on pickup is refused:
    handing it over would mark the secret known (outside every undo)."""
    from app.models.inventory import get_item
    for i, outfit in enumerate(outfits or []):
        for j, piece in enumerate((outfit or {}).get("pieces") or []):
            if isinstance(piece, dict) and piece.get("item_id"):
                item = get_item(str(piece["item_id"]).strip()) or {}
                if item.get("reveals_secret"):
                    raise ToolRefusal(f"outfits[{i}].pieces[{j}]: piece "
                                      f"{piece['item_id']!r} reveals a secret when "
                                      "handed over — it cannot be given here")


# ── Body slots (declared by species packages, read through body_slots) ──

#: Longest body-slot schema get_character returns (one line per slot).
MAX_BODY_SCHEMA_CHARS = 4000


def _body_specs(profile: Dict[str, Any]) -> List[Tuple[Any, Dict[str, Dict[str, Any]]]]:
    """(spec, llm-fillable attributes) of every body slot that applies to a
    character with this profile and has at least one fillable attribute —
    the package declarations (body_slots.slots_for_character), never a
    hard-coded slot list."""
    from app.core.body_slots import llm_fillable_attributes, slots_for_character
    out = []
    for spec in slots_for_character("", profile=profile):
        attrs = llm_fillable_attributes(spec)
        if attrs:
            out.append((spec, attrs))
    return out


def _attr_applies(decl: Dict[str, Any], slot_vals: Dict[str, Any],
                  profile: Dict[str, Any]) -> bool:
    """The attribute's own ``applies_to`` (an ``attributes.<key>`` condition
    reads the sibling attribute of the same slot, any other key the profile
    field) — same comparison as body_slots._slot_applies."""
    from app.core.body_slots import normalize_condition_value as norm
    for key, allowed in (decl.get("applies_to") or {}).items():
        value = (slot_vals.get(key[len("attributes."):])
                 if key.startswith("attributes.") else profile.get(key))
        if norm(value) not in [norm(a) for a in allowed or []]:
            return False
    return True


def _check_body_slots(raw: Any, profile: Dict[str, Any], template: str) -> Dict[str, Dict[str, str]]:
    """Validate a body_slots draft/patch against the slots that apply to a
    character with ``profile``; every invalid slot, attribute or value is
    REFUSED (before any write) instead of skipped. Returns the clean
    {slot: {attribute: value}} (values stripped)."""
    if not isinstance(raw, dict):
        raise ToolRefusal("'body_slots' must be an object {slot: {attribute: value}}")
    specs = {spec.id: (spec, attrs) for spec, attrs in _body_specs(profile)}
    if raw and not specs:
        raise ToolRefusal(f"template {template!r} has no body slots for this character")
    clean: Dict[str, Dict[str, str]] = {}
    for slot_id, values in raw.items():
        if str(slot_id) not in specs:
            raise ToolRefusal(f"body slot {slot_id!r} does not apply to this character — "
                              "slots: " + ", ".join(sorted(specs)))
        spec, attrs = specs[str(slot_id)]
        if not isinstance(values, dict) or not values:
            raise ToolRefusal(f"body_slots.{slot_id} must be a non-empty object "
                              "{attribute: value}")
        out: Dict[str, str] = {}
        for key, value in values.items():
            decl = attrs.get(key)
            if decl is None:
                raise ToolRefusal(f"body_slots.{slot_id}: attribute {key!r} cannot be "
                                  "set here — attributes: " + ", ".join(sorted(attrs)))
            if not isinstance(value, str) or not value.strip():
                raise ToolRefusal(f"body_slots.{slot_id}.{key} must be a non-empty "
                                  "string (values cannot be cleared here)")
            text = value.strip()
            options = [str(o) for o in (decl.get("options") or [])]
            if options and not decl.get("allow_custom") and text not in options:
                raise ToolRefusal(f"body_slots.{slot_id}.{key} must be one of: "
                                  + ", ".join(options))
            out[key] = text
        clean[spec.id] = out
    return clean


def _missing_body_attrs(name: str) -> List[str]:
    """"slot.attribute" of every applicable, fillable attribute of a stored
    character that has no value (attribute conditions that do not hold are
    left out)."""
    from app.models.character import get_character_profile
    prof = get_character_profile(name) or {}
    vals = prof.get("body_slots") if isinstance(prof.get("body_slots"), dict) else {}
    out = []
    for spec, attrs in _body_specs(prof):
        slot_vals = vals.get(spec.id) if isinstance(vals.get(spec.id), dict) else {}
        for key, decl in attrs.items():
            if _attr_applies(decl, slot_vals, prof) and not str(slot_vals.get(key) or "").strip():
                out.append(f"{spec.id}.{key}")
    return out


def _body_schema(prof: Dict[str, Any]) -> List[str]:
    """One line per applicable slot: every fillable attribute with its
    current value ("-" = unset) and what it takes."""
    vals = prof.get("body_slots") if isinstance(prof.get("body_slots"), dict) else {}
    lines = []
    for spec, attrs in _body_specs(prof):
        slot_vals = vals.get(spec.id) if isinstance(vals.get(spec.id), dict) else {}
        parts = []
        for key, decl in attrs.items():
            if not _attr_applies(decl, slot_vals, prof):
                continue
            options = [str(o) for o in (decl.get("options") or [])]
            takes = ("|".join(options) + ("|other" if decl.get("allow_custom") else "")
                     if options else "text")
            cur = str(slot_vals.get(key) or "").strip() or "-"
            parts.append(f"{key}={cur} [{takes}]")
        if parts:
            lines.append(f"{spec.id}: " + "; ".join(parts))
    return lines


def _check_home_values(data: Dict[str, Any]) -> None:
    """home_location / home_room strings, daily_schedule a list of slot
    objects ({hour, location?, role?, sleep?}). A slot the apply would skip
    with a warning is refused here instead (gap 24): an hour that is no whole
    number 0-23, a slot with neither place, role nor sleep, a sleep slot that
    also names a place or role, and an hour given twice. A whitespace-only
    location is refused with its own message (it names no place), and so
    are a blank home / home_room and an empty schedule list: each would be
    accepted and do nothing, so the model would get no signal."""
    for key, shown in (("home_location", "home"), ("home_room", "home_room")):
        if _str(data, key) == "":
            raise ToolRefusal(f"'{shown}' must not be empty — name a place or "
                              "leave the key out")
    slots = data.get("daily_schedule")
    if slots is None:
        return
    if not isinstance(slots, list):
        raise ToolRefusal("'schedule' must be a list of {hour, location?, role?, "
                          "sleep?} objects")
    if not slots:
        raise ToolRefusal("'schedule' must not be empty — leave the key out")
    seen: Dict[int, int] = {}
    for i, slot in enumerate(slots):
        if not isinstance(slot, dict):
            raise ToolRefusal(f"schedule[{i}] must be an object")
        _only_keys(slot, {"hour", "location", "role", "sleep"}, f"schedule[{i}]")
        raw_hour = slot.get("hour")
        if not (_is_num(raw_hour) and raw_hour == int(raw_hour)
                and 0 <= int(raw_hour) <= 23):
            raise ToolRefusal(f"schedule[{i}]: 'hour' must be a whole number 0-23")
        hour = int(raw_hour)
        try:
            location = _str(slot, "location")
            role = _str(slot, "role")
            sleep = _bool(slot, "sleep")
        except ToolRefusal as exc:
            raise ToolRefusal(f"schedule[{i}]: {exc}")
        if isinstance(slot.get("location"), str) and location == "":
            raise ToolRefusal(f"schedule[{i}]: 'location' is blank — name a place "
                              "or leave the key out")
        if sleep:
            if location or role:
                raise ToolRefusal(f"schedule[{i}]: a sleep slot takes no location "
                                  "or role")
        elif not location and not role:
            raise ToolRefusal(f'schedule[{i}] needs a location, a role or '
                              '"sleep": true')
        if hour in seen:
            raise ToolRefusal(f"schedule[{i}] repeats hour {hour} of "
                              f"schedule[{seen[hour]}]")
        seen[hour] = i


def _check_home_targets(data: Dict[str, Any], current_home: Any = None) -> None:
    """Refuse a home, home room or schedule place that does not exist BEFORE
    anything is written (the apply would only skip it with a warning and
    leave an empty journal step). ``current_home``: the stored home a room
    alone refers to (update_character)."""
    from app.core.world_dev_apply import _resolve_room_id, _resolve_world_location
    home = None
    if data.get("home_location"):
        home = _resolve_world_location(data["home_location"])
        if home is None:
            raise ToolRefusal(f"home {data['home_location']!r} is no place of this "
                              "world — use find_locations")
    elif data.get("home_room"):
        home = _resolve_world_location(current_home) if current_home else None
        if home is None:
            raise ToolRefusal("'home_room' needs a home — send 'home' as well")
    if data.get("home_room") and not _resolve_room_id(home, data["home_room"]):
        rooms = [str(r.get("name")) for r in _real_rooms(home) if r.get("name")]
        raise ToolRefusal(f"room {data['home_room']!r} is not a room of "
                          f"{home.get('name')} — rooms: " + (", ".join(rooms) or "none"))
    for i, slot in enumerate(data.get("daily_schedule") or []):
        place = slot.get("location")
        if isinstance(place, str) and place.strip() \
                and _resolve_world_location(place) is None:
            raise ToolRefusal(f"schedule[{i}]: {slot['location']!r} is no place of "
                              "this world — use find_locations")


def _check_known_places(value: Any) -> List[str]:
    """known_places: a non-empty list of place ids or exact names, each a
    place of this world. Returns the location ids, deduplicated, in the order
    sent."""
    from app.core.world_dev_apply import _resolve_world_location
    if not isinstance(value, list):
        raise ToolRefusal("'known_places' must be a list of place ids or names")
    if not value:
        raise ToolRefusal("'known_places' must not be empty — known places are only "
                          "added here, never removed")
    ids: List[str] = []
    for i, raw in enumerate(value):
        if not isinstance(raw, str) or not raw.strip():
            raise ToolRefusal(f"known_places[{i}] must be a place id or name (a string)")
        loc = _resolve_world_location(raw)
        if loc is None:
            raise ToolRefusal(f"known_places[{i}]: {raw!r} is no place of this world "
                              "— use find_locations")
        if str(loc["id"]) not in ids:
            ids.append(str(loc["id"]))
    return ids


def _add_known_places(name: str, ids: List[str]) -> Tuple[List[str], List[str]]:
    """Add ids to the character's known places (add-only, stored order kept,
    the new ones appended in the order given) — the tool's own locked
    read-modify-write: models.character.add_known_location is unlocked and
    ignores the save result. A failed save, or an id missing when read back,
    is a ValueError. Returns the stored list as read back and the ids this
    call added (those not known before, in the order given)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (get_character_config, get_known_locations,
                                      save_character_config)
    with keyed_lock("character_profile", name):
        cfg = copy.deepcopy(get_character_config(name) or {})
        existing = cfg.get("known_locations")
        known = [str(v) for v in existing if v] if isinstance(existing, list) else []
        missing = [i for i in ids if i not in known]
        if missing:
            # Appended to the stored list AS IT IS (membership on the str
            # view): the undo removes exactly the added ids, so a normalised
            # copy would change entries the journal does not record.
            cfg["known_locations"] = (list(existing) if isinstance(existing, list)
                                      else []) + missing
            if not save_character_config(name, cfg):
                raise ValueError(f"the known places of {name} were not stored")
        stored = get_known_locations(name)
    if any(i not in stored for i in ids):
        raise ValueError(f"the known places of {name} were not stored")
    return stored, missing


def _place_names(ids: List[str], cap: int = 8) -> str:
    """Place names for a result line (the id of a place without a name), at
    most cap of them."""
    from app.models.world import get_location_by_id
    names = [str((get_location_by_id(loc_id) or {}).get("name") or loc_id)
             for loc_id in ids[:cap]]
    return ", ".join(names) + (" …" if len(ids) > cap else "")


def _known_places_line(cfg: Dict[str, Any]) -> str:
    """The get_character overview line of the known places."""
    known = cfg.get("known_locations")
    ids = [str(v) for v in known if v] if isinstance(known, list) else []
    return (f"known places: {len(ids)}" + (f" ({_place_names(ids)})" if ids else ""))


#: Budget of describe_template (a whole template schema is longer than an
#: ordinary read result; it is read once before creating).
MAX_TEMPLATE_SCHEMA_CHARS = 8000


def _unknown_fields_text(keys: List[str], template: str) -> str:
    """The refusal of keys no settable field of the template has; it points
    to describe_template."""
    names = ", ".join(f"'{k}'" for k in keys)
    return (f"unknown character field{'s' if len(keys) > 1 else ''} {names} — "
            f'describe_template{{"template": {json.dumps(template, ensure_ascii=False)}}} '
            "lists the fields")


def _field_takes(field: Dict[str, Any]) -> str:
    """What a template field takes, in the words describe_template uses —
    the same rules _check_field_value enforces."""
    store = _field_store(field)
    if store == "status":
        return "whole number 0-100"
    if store == "soul":
        return "soul text"
    kind = str(field.get("type") or "")
    if kind in ("text", "textarea"):
        return "text"
    if kind == "number":
        return "number"
    if kind == "season_day":
        return '"<season>:<day>"'
    if kind == "select":
        values = _select_values(field)
        if values is None:
            return "editor only"
        quoted = [json.dumps(v, ensure_ascii=False) for v in values]
        if field.get("source"):
            return "one of " + " | ".join([json.dumps("")] + quoted)
        if field.get("allow_custom"):
            return "one of " + " | ".join(quoted) + " or another string"
        return "one of " + " | ".join(quoted)
    return "editor only"


#: Longest field hint describe_template shows (its first sentence, cut).
MAX_FIELD_HINT_CHARS = 90

#: A first sentence shorter than this (a bare range such as "0-100%.") says
#: nothing on its own, so the hint runs on to the next sentence end.
MIN_FIELD_HINT_SENTENCE = 12

#: Words whose trailing dot does not end a sentence.
_HINT_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "approx.")


def _hint_sentence_end(hint: str, start: int) -> int:
    """Index just past the first real sentence end in hint at or after start
    — a ". " that is not an abbreviation's dot and leaves no parenthesis or
    double quote open; len(hint) when there is none."""
    pos = hint.find(". ", start)
    while pos >= 0:
        head = hint[:pos + 1]
        word = head.rsplit(" ", 1)[-1].lstrip("(\"'").lower()
        if (word not in _HINT_ABBREVIATIONS
                and head.count("(") <= head.count(")")
                and head.count('"') % 2 == 0):
            return pos + 1
        pos = hint.find(". ", pos + 1)
    return len(hint)


def _field_hint(field: Dict[str, Any]) -> str:
    """The first sentence of a field's editor hint (run on to the second
    when the first is shorter than MIN_FIELD_HINT_SENTENCE), at most
    MAX_FIELD_HINT_CHARS; "" without one."""
    hint = " ".join(str(field.get("hint") or "").split())
    if not hint:
        return ""
    end = _hint_sentence_end(hint, 0)
    if end < MIN_FIELD_HINT_SENTENCE:
        end = _hint_sentence_end(hint, end)
    hint = hint[:end]
    if len(hint) > MAX_FIELD_HINT_CHARS:
        hint = hint[:MAX_FIELD_HINT_CHARS - 1].rstrip() + "…"
    return hint


def _visible_when_note(field: Dict[str, Any]) -> str:
    """" (only when <field>=<v1|v2>)" for a field the editor shows only under
    a condition; "" without one."""
    cond = field.get("visible_when")
    if not isinstance(cond, dict) or not cond:
        return ""
    if cond.get("field"):
        values = "|".join(str(v) for v in cond.get("values") or [])
        return f" (only when {cond['field']}={values})"
    if cond.get("feature"):
        return f" (only when the template has the feature {cond['feature']})"
    return ""


@_tool("describe_template", False, "describe_template{template?, gender?}",
       "the fields a character template takes (key, where it is stored, allowed "
       "values, default) and its body slots for a gender — read it before "
       "create_character", pinned=True)
def _describe_template(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"template", "gender"}, "describe_template")
    template = _str(args, "template") or "human-roleplay"
    gender = _str(args, "gender")
    templates = character_templates()
    offered = {t["name"]: t for t in templates}
    if template not in offered:
        raise ToolRefusal(f"template {template!r} cannot be created here — "
                          "templates: " + _templates_line(templates))
    fields = _template_fields(template)
    if gender is not None:
        if "gender" not in fields:
            raise ToolRefusal(f"template {template!r} has no gender field")
        _check_field_value("gender", fields["gender"], gender)
    info = offered[template]
    head = (f"template {template} ({info['label']}) — "
            f"{'outfits' if info['outfits'] else 'no outfits'}; keys work in "
            "create_character data and in update_character patch (soul fields "
            'there as "soul:<key>")')
    # The body block comes right after the header: it is short, and a
    # budget cut takes the field entries from the end, never the slots.
    would_be: Dict[str, Any] = {"template": template}
    if gender is not None:
        would_be["gender"] = gender
    body = _body_schema(would_be)
    if not body:
        top = [head, "body slots: none"]
    else:
        top = [head, f"body slots for gender={gender}:" if gender is not None else
               "body slots (gender not given — slots that depend on it are left out):",
               *body]
    if info["outfits"]:
        storable = _storable_piece_slots(would_be)
        top.append("outfit slots: " + (", ".join(storable) if storable
                                       else "none the catalog can store "
                                            "(existing pieces by item_id only)"))
    top.append("fields:")
    # One entry per field: its line, plus the hint indented below it, so a
    # cut never separates the two.
    lines: List[str] = []
    for key, field in _settable_fields(template).items():
        store = _field_store(field)
        line = f"- {key} [{store}]: {_field_takes(field)}"
        default = field.get("default")
        if store != "soul" and default not in (None, "", [], {}):
            shown = json.dumps(default, ensure_ascii=False)
            if len(shown) < 60:
                line += f" — default {shown}"
        line += _visible_when_note(field)
        hint = _field_hint(field)
        lines.append(line + (f"\n    {hint}" if hint else ""))
    shown = "\n".join(top)
    return "\n".join([shown] + _cap_lines(
        lines, "the rest is cut — a key not listed is still checked when it is set",
        budget=MAX_TEMPLATE_SCHEMA_CHARS, used=len(shown) + 1, max_lines=len(lines)))


def _refuse_foreign_sweep_rows(name: str) -> None:
    """The undo of a create is delete_character, which sweeps every row
    under the name (notifications titled with it, rows of a character_name
    column, ...). Rows that already exist under a name nobody holds are not
    this create's: the undo would delete them, so the create is refused up
    front. The row list is the one the cross-turn delete snapshots
    (world_dev_undo.character_rows), so both read the same sweep."""
    rows = wu.character_rows(name)
    if rows:
        counts = ", ".join(f"{tbl}: {len(r)}" for tbl, r in sorted(rows.items()))
        raise ToolRefusal(f"rows under the name {name!r} already exist without a "
                          f"character ({counts}) — undoing this create would delete "
                          "them; choose another name")


@_tool("create_character", True,
       "create_character{data, home?, home_room?, schedule?:[{hour, location?, role?, sleep?}], "
       "known_places?:[place]}",
       "new character (character schema fields + outfits); home = a place id or name; "
       "known_places = further places it may travel to")
def _create_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.character_name import validate_character_name
    from app.core.world_dev_apply import (_get_generable_fields,
                                          _template_has_wardrobe, apply_character)
    from app.models.character import character_row_exists
    from app.models.character_template import get_template
    _only_keys(args, {"data", "home", "home_room", "schedule", "known_places"},
               "create_character")
    data = args.get("data")
    if not isinstance(data, dict):
        raise ToolRefusal("'data' must be an object with the character fields")
    draft = {k: copy.deepcopy(v) for k, v in data.items() if v is not None}
    if "name" in draft and "character_name" not in draft:
        draft["character_name"] = draft.pop("name")
    for arg, key in (("home", "home_location"), ("home_room", "home_room"),
                     ("schedule", "daily_schedule"), ("known_places", "known_places")):
        if args.get(arg) is not None:
            if draft.get(key) is not None:
                # Two spellings of one value: refuse instead of letting one
                # silently win.
                raise ToolRefusal(f"'{arg}' is given twice (as argument and as "
                                  f"data.{key}) — send it once")
            draft[key] = copy.deepcopy(args[arg])
    raw_name = _str(draft, "character_name", required=True)
    # No template given = the full NPC template; human-default is a minimal
    # template (no memory, relationships or outfits) and only on request.
    template = _str(draft, "template") or "human-roleplay"
    tmpl = get_template(template)
    if tmpl is None:
        raise ToolRefusal(f"no character template {template!r}")
    # Only the templates the World Dev character schema offers (see
    # character_templates).
    templates = character_templates()
    if (template not in {t["name"] for t in templates}
            or (tmpl.get("features") or {}).get("temporary_npc")):
        raise ToolRefusal(f"template {template!r} cannot be created here — "
                          "templates: " + _templates_line(templates))
    draft["template"] = template
    if draft.get("outfits") and not _template_has_wardrobe(template):
        _refuse_outfits(template, templates)
    fields = _template_fields(template)
    settable = _settable_fields(template)
    unknown = sorted(k for k in draft if k not in _CHAR_DRAFT_SPECIAL and k not in settable)
    if unknown:
        raise ToolRefusal(_unknown_fields_text(unknown, template))
    for key, value in draft.items():
        if key in fields and key not in _CHAR_DRAFT_SPECIAL:
            _check_field_value(key, fields[key], value)
    if draft.get("outfits") is not None:
        _check_outfits(draft["outfits"], _storable_piece_slots({"template": template}))
        _check_outfit_refs_reveal(draft["outfits"])
        seen_outfits: set = set()
        for i, outfit in enumerate(draft["outfits"]):
            key_name = str(outfit.get("name") or "").strip().casefold()
            if key_name in seen_outfits:
                raise ToolRefusal(f"outfits[{i}]: the name {outfit.get('name')!r} "
                                  "is given twice")
            seen_outfits.add(key_name)
    # The starting outfit (D6): one of data.outfits by name, default the
    # first; worn right after the apply, inside the create step.
    wear_name = _starting_outfit_name(draft.pop("wear", None), draft.get("outfits"))
    if draft.get("body_slots") is not None:
        # Checked against the profile the character will have (template,
        # gender, ... of the draft): an invalid slot, attribute or value is
        # refused here instead of being skipped by the apply.
        would_be = {k: v for k, v in draft.items() if k not in _CHAR_DRAFT_SPECIAL}
        would_be.update(template=template, body_slots=draft["body_slots"])
        draft["body_slots"] = _check_body_slots(draft["body_slots"], would_be, template)
    _check_home_values(draft)
    _check_home_targets(draft)
    # Added by this tool after the apply (the apply knows only home and
    # schedule places), inside the create step.
    known_ids = (_check_known_places(draft.pop("known_places"))
                 if "known_places" in draft else [])
    # THE name rule (CharacterNameError is a ValueError -> refused), then
    # "taken" by the name it would be stored under.
    name = validate_character_name(raw_name)
    if character_row_exists(name):
        raise ToolRefusal(f"a character {name!r} already exists — use update_character")
    draft["character_name"] = name
    _refuse_foreign_sweep_rows(name)
    # Written by this tool right after the apply, in the same journal step
    # (covered by delete_character): every config key (raw JSON — the apply
    # would store str(value)), every stat (into status_effects) and the
    # profile keys the apply does not take (not llm_generable). Soul,
    # outfit, body-slot and home keys stay with the apply.
    generable_profile, _ = _get_generable_fields(template)
    extra_prof: Dict[str, Any] = {}
    extra_cfg: Dict[str, Any] = {}
    extra_stats: Dict[str, Any] = {}
    for key in list(draft):
        if key in _CHAR_DRAFT_SPECIAL or key not in settable:
            continue
        store = _field_store(settable[key])
        if store == "config":
            extra_cfg[key] = draft.pop(key)
        elif store == "status":
            extra_stats[key] = draft.pop(key)
        elif store == "profile" and key not in generable_profile:
            extra_prof[key] = draft.pop(key)

    step.prepare()
    # The backup can take seconds: a character of that name created by
    # someone else meanwhile is refused here, before any journal row exists.
    if character_row_exists(name):
        raise ToolRefusal(f"a character {name!r} already exists — use update_character")
    _refuse_foreign_sweep_rows(name)
    inverse = {"op": "delete_character", "name": name, "items": []}
    step.begin("character", name, inverse)
    # Set by apply_character once it has confirmed, under the profile lock,
    # that the name is still free and is about to store the new row. Only
    # then is a row found after a failure THIS apply's character; without
    # it the row is a foreign one (a race after the re-check above) and must
    # never be claimed — a discard would delete it.
    # The claim is DURABLE: it is written into the journal row before the
    # profile save, and every new catalog piece the moment add_item returns
    # its id — so the undo of a row left pending by a crash knows whether
    # the character (and which pieces) are this create's
    # (world_dev_undo._undo_delete_character).
    claimed: List[bool] = []
    new_items: List[str] = []

    def claimed_inverse() -> Dict[str, Any]:
        return {**inverse, "claimed": True, "items": list(new_items)}

    def on_claim() -> None:
        step.attach(name, claimed_inverse())
        claimed.append(True)

    def on_item(item_id: str) -> None:
        new_items.append(str(item_id))
        if claimed:
            step.attach(name, claimed_inverse())

    def reconcile():
        if not claimed or not character_row_exists(name):
            return None
        # The catalog items the failed apply created (recorded as add_item
        # returned them; the undo deletes only those held nowhere).
        inv = claimed_inverse()
        return (name, inv, {"name": name, "items": inv["items"]})

    with step.writing(reconcile):
        result = apply_character(draft, created_by="world_dev", must_be_new=True,
                                 on_claim=on_claim, on_item=on_item,
                                 place_compliance=False)
        # An explicit chat_mode is written here, after the apply's
        # rp_first default, so it wins.
        _write_char_fields(name, extra_prof, extra_cfg, extra_stats)
        worn = (_wear_starting_outfit(name, wear_name) if wear_name is not None
                else None)
        compliance_warnings = _place_compliance(name)
        known = _add_known_places(name, known_ids)[0] if known_ids else None
        items = [str(i) for i in result.get("created_items") or []]
        step.attach(name, {**claimed_inverse(), "items": items})
    outfits = result.get("outfits") or []
    reused = sum(int(o.get("pieces_reused") or 0) for o in outfits)
    from app.models.character import get_character_config
    cfg = get_character_config(name) or {}
    home = str(cfg.get("home_location") or "")
    line = (f'created character "{name}" (template {template}'
            + (f", {len(outfits)} outfit(s), {len(items)} new piece(s)"
               + (f", {reused} existing" if reused else "") if outfits else "")
            + (f", wearing {worn[0]} ({', '.join(worn[1]) or 'no pieces'})"
               if worn else "")
            + ")" + (f" home {home}" + (f" / {cfg.get('home_room')}"
                                        if cfg.get("home_room") else "")
                     if home else "")
            + (f"; knows {len(known)} place(s): {_place_names(known)}" if known else "")
            + _warn_suffix([str(w) for w in result.get("warnings") or []]
                           + (worn[2] if worn else [])
                           + compliance_warnings)
            # No silent gap: what the new character still lacks (Task 9).
            + completeness.suffix(completeness.character_gaps(name)))
    step.complete({"name": name, "items": items}, line)
    return line


@_tool("update_character", True, "update_character{name, patch}",
       "change fields of a character; 'soul:<field>' = the whole new text of a "
       "soul section (trailing whitespace is normalised to one newline); home / home_room / schedule; body_slots (merged per "
       "attribute); outfits (NEW outfits added); known_places (places added to "
       "the ones it knows)")
def _update_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.core import soul_writer
    from app.core.keyed_lock import keyed_lock
    from app.core.linked_characters import LOCKED_PROFILE_FIELDS, soul_owner
    from app.core.world_dev_apply import (_apply_home_and_schedule,
                                          _apply_one_outfit, _template_has_wardrobe)
    from app.models.character import (character_row_exists, get_character_config,
                                      get_character_outfits, get_character_profile,
                                      get_known_locations, save_character_config,
                                      save_character_profile)
    _only_keys(args, {"name", "patch"}, "update_character")
    name = _str(args, "name", required=True)
    patch = args.get("patch")
    if not isinstance(patch, dict) or not patch:
        raise ToolRefusal("'patch' must be a non-empty object of character fields")
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    prof0 = get_character_profile(name) or {}
    template = str(prof0.get("template") or "human-default")
    fields = _template_fields(template)
    soul_map = {k: str(f["source_file"]) for k, f in fields.items()
                if f.get("source_file")}
    linked = bool(str(prof0.get("linked_to") or "").strip())

    prof_patch: Dict[str, Any] = {}
    cfg_patch: Dict[str, Any] = {}
    stat_patch: Dict[str, int] = {}  # stat -> whole number (status_effects)
    soul_patch: Dict[str, str] = {}  # rel path -> full new text
    home_data: Dict[str, Any] = {}
    outfits_patch: Optional[List[Dict[str, Any]]] = None
    body_raw: Any = None
    for key, value in patch.items():
        if key.startswith("soul:"):
            fk = key[len("soul:"):]
            rel = soul_map.get(fk)
            if not rel:
                raise ToolRefusal(f"no soul field {fk!r} in template {template} — "
                                  "soul fields: " + (", ".join(sorted(soul_map)) or "none"))
            if not isinstance(value, str):
                raise ToolRefusal(f"'{key}' must be the whole new text (a string)")
            owner = soul_owner(name, rel)
            if owner != name:
                raise ToolRefusal(f"{rel} of {name} is shared with {owner} — "
                                  f"change it on {owner}")
            soul_patch[rel] = value
        elif key == "wear":
            raise ToolRefusal("the worn outfit of an existing character is its own "
                              "state — change it in the wardrobe")
        elif key == "outfits":
            if not _template_has_wardrobe(template):
                _refuse_outfits(template, character_templates())
            _check_outfits(value, _storable_piece_slots(prof0))
            _check_outfit_refs_reveal(value)
            outfits_patch = copy.deepcopy(value)
        elif key == "body_slots":
            body_raw = value
        elif key in _HOME_PATCH_KEYS:
            home_data[_HOME_PATCH_KEYS[key]] = value
        elif key in _HOME_DRAFT_SPELLINGS:
            raise ToolRefusal(f"send '{key}' as '{_HOME_DRAFT_SPELLINGS[key]}'")
        elif key in fields:
            field = fields[key]
            if field.get("source_file"):
                raise ToolRefusal(f"'{key}' is a soul section — send it as "
                                  f"'soul:{key}' with the whole new text")
            if key in ("character_name", "template") or field.get("readonly"):
                raise ToolRefusal(f"'{key}' cannot be changed here")
            if linked and key in LOCKED_PROFILE_FIELDS:
                raise ToolRefusal(f"'{key}' of a linked character is its leader's "
                                  "— change it there")
            if value is None:
                raise ToolRefusal(f"'{key}' must not be null")
            _check_field_value(key, field, value)
            store = _field_store(field)
            if store == "config":
                cfg_patch[key] = copy.deepcopy(value)
            elif store == "status":
                stat_patch[key] = int(value)
            else:
                prof_patch[key] = copy.deepcopy(value)
        else:
            raise ToolRefusal(_unknown_fields_text([key], template))
    if outfits_patch is not None:
        # Outfits are only ADDED: a name the character has already (or one
        # given twice) is refused, so nothing that existed is ever replaced
        # and the undo removes exactly what this call added.
        taken = {str(o.get("name") or "").strip().casefold()
                 for o in get_character_outfits(name)}
        seen: set = set()
        for i, outfit in enumerate(outfits_patch):
            key_name = str(outfit.get("name") or "").strip().casefold()
            if key_name in taken:
                raise ToolRefusal(f"outfits[{i}]: {name} has an outfit "
                                  f"{outfit.get('name')!r} already — outfits are only "
                                  "added here, never replaced; use another name")
            if key_name in seen:
                raise ToolRefusal(f"outfits[{i}]: the name {outfit.get('name')!r} "
                                  "is given twice")
            seen.add(key_name)
        if not outfits_patch:
            raise ToolRefusal("'outfits' must not be empty")
    body_clean: Dict[str, Dict[str, str]] = {}
    if body_raw is not None:
        # Checked against the profile as it will be after this patch (a
        # gender change can make a slot apply), the stored values merged
        # with the new ones.
        would_be = copy.deepcopy(prof0)
        would_be.update(copy.deepcopy(prof_patch))
        merged = copy.deepcopy(would_be.get("body_slots")
                               if isinstance(would_be.get("body_slots"), dict) else {})
        if isinstance(body_raw, dict):
            for slot_id, values in body_raw.items():
                if isinstance(values, dict):
                    merged.setdefault(str(slot_id), {})
                    if isinstance(merged[str(slot_id)], dict):
                        merged[str(slot_id)].update(values)
        would_be["body_slots"] = merged
        body_clean = _check_body_slots(body_raw, would_be, template)
        if not body_clean:
            raise ToolRefusal("'body_slots' must not be empty")
    known_ids = (_check_known_places(home_data.pop("known_places"))
                 if "known_places" in home_data else [])
    _check_home_values(home_data)

    def refuse_non_list_known() -> None:
        # The per-place inverse (remove_known_places) restores a list, or
        # removes the key when there was none; a stored value of another type
        # — a JSON null included, although the readers take it as empty —
        # could not be restored exactly.
        if known_ids and not isinstance(
                (get_character_config(name) or {}).get("known_locations", []), list):
            raise ToolRefusal(f"the stored known places of {name!r} are no list — "
                              "they cannot be changed here")

    refuse_non_list_known()
    if home_data and not any(home_data.get(k) for k in home_data):
        raise ToolRefusal("home / home_room / schedule must not be empty — "
                          "they cannot be cleared here")
    if home_data:
        _check_home_targets(home_data,
                            (get_character_config(name) or {}).get("home_location"))

    step.prepare()
    lines: List[str] = []

    def group_step() -> _Step:
        # One journal step per group: the call's own step first, then one
        # more row per further group (same tool and arguments).
        return step if step.seq is None else _Step(step.ctx, step.tool, step.args)

    def picked(record: Dict[str, Any], keys) -> Dict[str, Any]:
        return {k: (copy.deepcopy(record[k]) if k in record else wu.ABSENT)
                for k in keys}

    # Lock order: character_profile -> soul_file (both re-entrant).
    with keyed_lock("character_profile", name):
        if not character_row_exists(name):
            raise ToolRefusal(f"no character {name!r} — use find_characters")
        # Again under the lock, before any group writes: a foreign writer may
        # have stored a non-list since the check above.
        refuse_non_list_known()
        # Soul sections first: a profile save (below) creates missing soul
        # files from their scaffold, which must not become a section's
        # "before" text.
        for rel, text in soul_patch.items():
            sstep = group_step()
            path = soul_writer.soul_text_path(name, rel)
            with keyed_lock("soul_file", str(path)):
                before_text = soul_writer.read_text(name, rel)
                inverse = {"op": "restore_soul", "name": name, "file_id": rel,
                           "before_text": before_text}
                sstep.begin("character", name, inverse)

                def reconcile_soul(rel=rel, before_text=before_text, inverse=inverse):
                    now = soul_writer.read_text(name, rel)
                    return None if now == before_text else (name, inverse, now)

                with sstep.writing(reconcile_soul):
                    soul_writer.write_text(name, rel, text)
                written = soul_writer.read_text(name, rel)
                sline = (f"soul {rel}" + ("" if before_text is not None else " (new file)")
                         if written != before_text else f"soul {rel} unchanged")
                sstep.complete(written, sline)
            lines.append(sline)

        if prof_patch or cfg_patch:
            cstep = group_step()
            prof = copy.deepcopy(get_character_profile(name) or {})
            cfg = copy.deepcopy(get_character_config(name) or {})
            b_prof, b_cfg = picked(prof, prof_patch), picked(cfg, cfg_patch)

            def diff_now():
                p = get_character_profile(name) or {}
                c = get_character_config(name) or {}
                bp, wp = wu.diff_keys(b_prof, picked(p, prof_patch))
                bc, wc = wu.diff_keys(b_cfg, picked(c, cfg_patch))
                # diff_keys compares two maps; ABSENT on both sides is equal.
                return bp, wp, bc, wc

            inverse = {"op": "restore_character", "name": name,
                       "profile": b_prof, "config": b_cfg}
            cstep.begin("character", name, inverse)

            def reconcile_char():
                bp, wp, bc, wc = diff_now()
                if not bp and not bc:
                    return None
                return (name, {"op": "restore_character", "name": name,
                               "profile": bp, "config": bc},
                        {"profile": wp, "config": wc})

            with cstep.writing(reconcile_char):
                if prof_patch:
                    new_prof = copy.deepcopy(prof)
                    new_prof.update(prof_patch)
                    # Soul values are injected on read; they never go back
                    # through a profile save (the MD file is the source).
                    for k in soul_map:
                        new_prof.pop(k, None)
                    if not save_character_profile(name, new_prof):
                        raise ValueError(f"the profile of {name} was not stored")
                if cfg_patch:
                    new_cfg = copy.deepcopy(get_character_config(name) or {})
                    new_cfg.update(cfg_patch)
                    if not save_character_config(name, new_cfg):
                        raise ValueError(f"the config of {name} was not stored")
            bp, wp, bc, wc = diff_now()
            cstep.attach(name, {"op": "restore_character", "name": name,
                                "profile": bp, "config": bc})
            changed = ([f"profile {k}" for k in sorted(bp)]
                       + [f"config {k}" for k in sorted(bc)])
            cline = ", ".join(changed) if changed else "fields unchanged"
            cstep.complete({"profile": wp, "config": wc}, cline)
            lines.append(cline)

        if stat_patch:
            # Its own step with a PER-STAT inverse: the hourly tick and
            # adjust_status_effects rewrite status_effects all the time, so
            # a whole-dict restore would make every undo "changed since" (or
            # clobber a foreign change of another stat).
            # Still inside the keyed_lock("character_profile") taken above:
            # the before values, had_key and write_stats are read under the
            # same lock as the write, so the hourly tick (which takes that
            # lock too) cannot land between the read and the write.
            tstep = group_step()
            t_prof = get_character_profile(name) or {}
            t_had_key = "status_effects" in t_prof

            def stats_now() -> Dict[str, Any]:
                p = get_character_profile(name) or {}
                cur = p.get("status_effects") if isinstance(p.get("status_effects"), dict) else {}
                return {k: (copy.deepcopy(cur[k]) if k in cur else wu.ABSENT)
                        for k in stat_patch}

            t_before = stats_now()

            def stats_diff() -> Tuple[Dict[str, Any], Dict[str, Any]]:
                now = stats_now()
                changed_keys = [k for k in stat_patch
                                if wu._norm(now[k]) != wu._norm(t_before[k])]
                return ({k: t_before[k] for k in changed_keys},
                        {k: now[k] for k in changed_keys})

            def stats_inverse(before_map: Dict[str, Any]) -> Dict[str, Any]:
                return {"op": "restore_status_effects", "name": name,
                        "before": before_map, "had_key": t_had_key}

            tstep.begin("character", name, stats_inverse(t_before))

            def reconcile_stats():
                tb, tw = stats_diff()
                return None if not tb else (name, stats_inverse(tb), {"stats": tw})

            # Only the stats whose stored value differs are written: a stat
            # that already holds the value (70.0 for 70, say) is left as it
            # is, so nothing changes outside what the journal records.
            write_stats = {k: v for k, v in stat_patch.items()
                           if wu._norm(t_before[k]) != wu._norm(v)}
            with tstep.writing(reconcile_stats):
                _write_char_fields(name, {}, {}, write_stats)
            tb, tw = stats_diff()
            tstep.attach(name, stats_inverse(tb))
            if tb:
                from app.core import sync_topics
                sync_topics.changed_at(name, topics=("presence", "self"))
            tline = ("stats " + ", ".join(sorted(tb))) if tb else "stats unchanged"
            tstep.complete({"stats": tw}, tline)
            lines.append(tline)

        if body_clean:
            bstep = group_step()
            b_prof = get_character_profile(name) or {}
            b_vals = (copy.deepcopy(b_prof["body_slots"])
                      if isinstance(b_prof.get("body_slots"), dict) else {})
            had_key = "body_slots" in b_prof
            slots_present = sorted(s for s in body_clean if s in b_vals)
            b_before = wu.body_slot_state(b_vals, body_clean)

            def body_diff():
                p = get_character_profile(name) or {}
                now = p.get("body_slots") if isinstance(p.get("body_slots"), dict) else {}
                return wu.body_slot_diff(b_before, wu.body_slot_state(now, body_clean))

            def body_inverse(before_map):
                return {"op": "restore_body_slots", "name": name, "before": before_map,
                        "had_key": had_key, "slots_present": slots_present}

            bstep.begin("character", name, body_inverse(b_before))

            def reconcile_body():
                bb, ww = body_diff()
                return None if not bb else (name, body_inverse(bb), {"slots": ww})

            with bstep.writing(reconcile_body):
                from app.core.character_ops import apply_body_slot_values
                for slot_id, values in body_clean.items():
                    apply_body_slot_values(name, slot_id, values)
            bb, ww = body_diff()
            bstep.attach(name, body_inverse(bb))
            bline = ("body slots " + ", ".join(f"{s}.{a}" for s in sorted(bb)
                                               for a in sorted(bb[s]))
                     if bb else "body slots unchanged")
            bstep.complete({"slots": ww}, bline)
            lines.append(bline)

        if outfits_patch:
            ostep = group_step()
            o_before = set(wu.outfit_rows(name))
            i_before = set(wu.inventory_entries(name))
            refs = sorted({str(p["item_id"]).strip() for o in outfits_patch
                           for p in o.get("pieces") or []
                           if isinstance(p, dict) and p.get("item_id")})
            new_items: List[str] = []
            # Until the write is done the inverse names what to look for (a
            # row left pending by a crash is resolved from it); afterwards the
            # exact ids (world_dev_undo._undo_remove_outfits).
            pending_inv = {"op": "remove_outfits", "name": name,
                           "names": [str(o["name"]).strip() for o in outfits_patch],
                           "outfits_before": sorted(o_before),
                           "inventory_before": sorted(i_before), "refs": refs,
                           "items": []}
            ostep.begin("character", name, pending_inv)

            def on_item(item_id: str) -> None:
                # Durable the moment add_item returns the id.
                new_items.append(str(item_id))
                ostep.attach(name, {**pending_inv, "items": list(new_items)})

            def added_now():
                ours = set(refs) | set(new_items)
                outs = {oid: o for oid, o in wu.outfit_rows(name).items()
                        if oid not in o_before}
                inv = {iid: e for iid, e in wu.inventory_entries(name).items()
                       if iid not in i_before and iid in ours}
                return outs, inv

            def outfit_inverse(outs, inv):
                return {"op": "remove_outfits", "name": name, "outfits": sorted(outs),
                        "inventory": sorted(inv), "items": list(new_items)}

            def reconcile_outfits():
                outs, inv = added_now()
                if not outs and not inv and not new_items:
                    return None
                return (name, outfit_inverse(outs, inv),
                        {"outfits": outs, "inventory": inv})

            applied: List[Dict[str, Any]] = []
            with ostep.writing(reconcile_outfits):
                for outfit in outfits_patch:
                    applied.append(_apply_one_outfit(name, copy.deepcopy(outfit),
                                                     on_item=on_item))
            outs, inv = added_now()
            ostep.attach(name, outfit_inverse(outs, inv))
            created = sum(int(a.get("pieces_created") or 0) for a in applied)
            reused = sum(int(a.get("pieces_reused") or 0) for a in applied)
            oline = (f"outfits added: {', '.join(str(a.get('name')) for a in applied)} "
                     f"({created} new piece(s), {reused} existing)"
                     + _warn_suffix([str(w) for a in applied
                                     for w in a.get("warnings") or []]))
            ostep.complete({"outfits": outs, "inventory": inv}, oline)
            lines.append(oline)

        if home_data:
            hstep = group_step()
            h_before = wu.home_schedule_state(name)
            hstep.begin("character", name, {"op": "restore_home_schedule",
                                             "name": name, "before": h_before})

            def reconcile_home():
                b, w = wu.diff_keys(h_before, wu.home_schedule_state(name))
                return None if not b else (
                    name, {"op": "restore_home_schedule", "name": name, "before": b}, w)

            with hstep.writing(reconcile_home):
                warnings = _apply_home_and_schedule(name, copy.deepcopy(home_data), False)
            b, w = wu.diff_keys(h_before, wu.home_schedule_state(name))
            hstep.attach(name, {"op": "restore_home_schedule", "name": name,
                                "before": b}, before=b)
            hline = (("home " + ", ".join(sorted(b))) if b else "home unchanged") \
                + _warn_suffix([str(x) for x in warnings])
            hstep.complete(w, hline)
            lines.append(hline)

        if known_ids:
            # Its own step with a PER-PLACE inverse: in-game discovery
            # (add_known_location) extends the list at any time, so a
            # whole-list restore would make the undo "changed since". The
            # inverse removes exactly the places this call added. Still under
            # the keyed_lock("character_profile") taken above.
            kstep = group_step()
            k_raw = (get_character_config(name) or {}).get("known_locations")
            k_had_key = isinstance(k_raw, list)
            k_known = [str(v) for v in k_raw if v] if k_had_key else []
            k_missing = [i for i in known_ids if i not in k_known]

            def known_inverse(added: List[str]) -> Dict[str, Any]:
                return {"op": "remove_known_places", "name": name,
                        "ids": list(added), "had_key": k_had_key}

            def added_now() -> List[str]:
                now = get_known_locations(name)
                return [i for i in k_missing if i in now]

            # Until the write is done the inverse names every place the call
            # is about to add (none of them was known before, so removing
            # them is exact); afterwards the ones read back.
            kstep.begin("character", name, known_inverse(k_missing))

            def reconcile_known():
                added = added_now()
                return None if not added else (name, known_inverse(added),
                                               {"known": added})

            with kstep.writing(reconcile_known):
                k_stored, _ = _add_known_places(name, known_ids)
            k_added = added_now()
            kstep.attach(name, known_inverse(k_added))
            kline = ((f"known places added: {_place_names(k_added)}" if k_added
                      else "known places unchanged")
                     + f"; knows {len(k_stored)} place(s)")
            kstep.complete({"known": k_added}, kline)
            lines.append(kline)

    # The gaps of the groups this run's calls touched on this character.
    return (f'updated character "{name}": ' + "; ".join(lines)
            + completeness.character_suffix(step.ctx.run_id, name))


# ── check_run ────────────────────────────────────────────────────────────

@_tool("check_run", False, "check_run{}",
       "what the elements this run created or changed still lack (call it before "
       "the summary)")
def _check_run(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, set(), "check_run")
    lines, complete, total = completeness.check_run_lines(step.ctx.run_id)
    tail = f"{complete} of {total} elements complete"
    return "\n".join(_cap_lines(lines, "fix these first, then call check_run again",
                                used=len(tail) + 1) + [tail])


# ── delete_created ───────────────────────────────────────────────────────

#: kind -> (inverse op of the creating entry, the inverse's key for the id)
_CREATE_OPS = {"location": ("delete_location", "id"),
               "terrain": ("delete_terrain_area", "id"),
               "height": ("delete_height_area", "id"),
               "character": ("delete_character", "name")}


def _creating_entry(run_id: str, kind: str, ident: str,
                    turn: Optional[int] = None) -> Optional[Dict[str, Any]]:
    op, key = _CREATE_OPS[kind]
    return next((e for e in wr.entries(run_id, turn=turn)
                 if (e.get("inverse") or {}).get("op") == op
                 and str((e.get("inverse") or {}).get(key) or "") == ident), None)


@_tool("delete_created", True, "delete_created{kind, id}",
       "remove something THIS run created, in this or an earlier turn "
       "(kind location|terrain|height|character; id = the name for a character)")
def _delete_created(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"kind", "id"}, "delete_created")
    kind = _str(args, "kind", required=True)
    ident = _str(args, "id", required=True)
    if kind not in _CREATE_OPS:
        raise ToolRefusal("kind must be one of " + ", ".join(_CREATE_OPS))
    creating = _creating_entry(step.ctx.run_id, kind, ident, turn=step.ctx.turn)
    if creating is None:
        earlier = _creating_entry(step.ctx.run_id, kind, ident)
        if earlier is None:
            raise ToolRefusal(f"{kind} {ident!r} was not created by this run (or is "
                              "already removed) — only those can be deleted")
        return _delete_earlier(step, kind, ident, earlier)
    if kind == "location":
        refs = _references_to_location(ident) + [
            f"{n} (stands there)" for n, _room in wu.standing_in(ident)]
        if refs:
            raise ToolRefusal(f"location {ident} is still named by: " + "; ".join(refs))
    step.prepare()
    # No inverse of its own: it executes the creating entry's inverse and
    # marks that entry undone, so the undo never reverses it a second time.
    step.begin(kind, ident)
    step.writing_started = True
    skips = wu.apply_inverse(creating)
    hard = [s for s in skips if "item" not in s and "occupant" not in s
            and s.get("reason") != wu.REASON_GONE]
    if hard:
        reason = "; ".join(str(s.get("reason")) for s in hard)
        step.complete(None, f"error: could not delete: {reason}", kind="refused")
        raise ToolRefusal(f"could not delete {kind} {ident}: {reason}")
    wr.mark_undone(step.ctx.run_id, int(creating["seq"]))
    kept = [str(s.get("item")) for s in skips if "item" in s]
    line = (f"deleted {kind} {ident} (created in step #{creating['seq']})"
            + (f"; items kept (still in use): {', '.join(kept)}" if kept else ""))
    step.complete(None, line)
    return line


def _location_media(loc_id: str) -> List[str]:
    """The media directories delete_location removes with a place (its
    gallery and building models) that hold anything."""
    from app.core.paths import get_storage_dir
    storage = get_storage_dir()
    out = []
    for sub in ("world_gallery", "locations"):
        d = storage / sub / loc_id
        if d.is_dir() and any(d.iterdir()):
            out.append(f"{sub}/{loc_id}")
    return out


def _character_delete_blockers(name: str) -> List[str]:
    """What an exact re-creation of a deleted character could not bring back
    — state delete_character changes OUTSIDE the character's own rows and
    directory (party, pair interaction, prop action, linked family, the
    traces of a temporary NPC) or that other characters keep after it is
    gone (chat rows with it, memories naming it)."""
    from app.core import linked_characters
    from app.core.interaction_engine import get_interaction
    from app.core.party_engine import is_in_party
    from app.models.character import get_character_profile, is_temporary_npc
    from app.models.chat import count_messages_involving
    from app.models.memory import count_other_memories_naming
    out: List[str] = []
    prof = get_character_profile(name) or {}
    refusal = linked_characters.delete_refusal(name)
    if refusal or str(prof.get("linked_to") or "").strip():
        out.append("linked to other characters")
    if is_temporary_npc(name):
        out.append("a temporary NPC")
    if is_in_party(name):
        out.append("in a party")
    if get_interaction(name, profile=prof):
        out.append("in a pair interaction")
    try:
        from app.core import prop_action_store as store
        if any(name in store.people(r) for r in store.live_runs()):
            out.append("in a furniture action")
    except ImportError:
        pass
    chats = count_messages_involving(name)
    if chats:
        out.append(f"{chats} chat messages")
    mems = count_other_memories_naming(name)
    if mems:
        out.append(f"{mems} memory rows of other characters name it")
    return out


def _delete_earlier(step: _Step, kind: str, ident: str,
                    creating: Dict[str, Any]) -> str:
    """delete_created of an element this run created in an EARLIER turn.
    The creating step stays; this call journals a write of its own whose
    inverse re-creates the element exactly from a snapshot taken under the
    writer's lock right before the delete (world_dev_undo recreate_*).
    Whatever such a snapshot could not restore exactly is refused up front."""
    seq = creating["seq"]
    line = f"deleted {kind} {ident} (created in step #{seq}, an earlier turn)"
    if kind == "location":
        from app.models.world import (delete_location, get_location_by_id,
                                      world_write_lock)
        step.prepare()
        with world_write_lock:  # re-entrant; delete_location takes it again
            row = get_location_by_id(ident)
            if row is None:
                raise ToolRefusal(f"location {ident} does not exist any more")
            refs = _references_to_location(ident) + [
                f"{n} (stands there)" for n, _room in wu.standing_in(ident)]
            if refs:
                raise ToolRefusal(f"location {ident} is still named by: " + "; ".join(refs))
            media = _location_media(ident)
            if media:
                raise ToolRefusal(f"location {ident} has images or models ("
                                  + ", ".join(media) + ") a deletion could not "
                                  "restore — it stays")
            inverse = {"op": "recreate_location", "row": copy.deepcopy(row)}
            step.begin("location", ident, inverse)

            def reconcile():
                return (None if get_location_by_id(ident) is not None
                        else (ident, inverse, None))

            with step.writing(reconcile):
                if not delete_location(ident) and get_location_by_id(ident) is not None:
                    raise RuntimeError(f"location {ident} was not deleted")
        step.complete(None, line)
        return line
    if kind in ("terrain", "height"):
        from app.models.heightfield import delete_height_area
        from app.models.terrain import delete_area, get_area
        read = get_area if kind == "terrain" else _height_area
        delete = delete_area if kind == "terrain" else delete_height_area
        op = "recreate_terrain_area" if kind == "terrain" else "recreate_height_area"
        step.prepare()
        # The area writers have no writer lock to share (see world_dev_undo):
        # read and delete follow each other directly.
        row = read(ident)
        if row is None:
            raise ToolRefusal(f"{kind} area {ident} does not exist any more")
        inverse = {"op": op, "row": copy.deepcopy(row)}
        step.begin(kind, ident, inverse)

        def reconcile_area():
            return None if read(ident) is not None else (ident, inverse, None)

        with step.writing(reconcile_area):
            if not delete(ident) and read(ident) is not None:
                raise RuntimeError(f"{kind} area {ident} was not deleted")
        step.complete(None, line)
        return line
    # character
    from app.core.keyed_lock import keyed_lock
    from app.models.character import character_row_exists, delete_character
    step.prepare()
    with keyed_lock("character_profile", ident):
        if not character_row_exists(ident):
            raise ToolRefusal(f"character {ident!r} does not exist any more")
        blockers = _character_delete_blockers(ident)
        if blockers:
            raise ToolRefusal(f"character {ident!r} cannot be deleted in a later turn "
                              "— a re-creation could not restore it exactly: "
                              + "; ".join(blockers))
        try:
            snap = wu.character_snapshot(ident)
        except ValueError as exc:
            raise ToolRefusal(f"character {ident!r} cannot be deleted: {exc}")
        if snap["file_bytes"] > wu.MAX_SNAPSHOT_FILE_BYTES:
            raise ToolRefusal(f"character {ident!r} has {snap['file_bytes'] // 1024} KB "
                              "of files (images, models) a deletion could not restore "
                              "— it stays")
        if len(json.dumps(snap["rows"], ensure_ascii=False)) > wu.MAX_SNAPSHOT_ROW_BYTES:
            raise ToolRefusal(f"character {ident!r} has too much stored state to be "
                              "restored exactly — it stays")
        inverse = {"op": "recreate_character", "name": ident, "snapshot": snap}
        step.begin("character", ident, inverse)

    def reconcile_char():
        return None if character_row_exists(ident) else (ident, inverse, None)

    # delete_character runs OUTSIDE the profile lock, as in the undo: its
    # detach steps take the party lock before it takes the profile lock
    # itself, and that order must not be inverted. The run keeps the world
    # frozen (no agent turns), and the detach steps find nothing to change
    # in the character's own rows — party, pair interaction and furniture
    # action were refused above — so the snapshot is the state it deletes.
    with step.writing(reconcile_char):
        if not delete_character(ident) and character_row_exists(ident):
            raise RuntimeError(f"character {ident!r} was not deleted")
    step.complete(None, line)
    return line
