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
from typing import Any, Callable, Dict, List, Optional, Tuple

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


@dataclass
class ToolResult:
    ok: bool
    line: str
    wrote: bool
    #: The journal row of this call (the UI merges live step events into the
    #: journal list by it).
    seq: Optional[int] = None


TOOLS: Dict[str, ToolSpec] = {}


def _tool(name: str, write: bool, signature: str, summary: str):
    def deco(fn):
        TOOLS[name] = ToolSpec(name, write, signature, summary, fn)
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
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _num(args: Dict[str, Any], key: str, required: bool = False) -> Optional[float]:
    if key not in args or args[key] is None:
        if required:
            raise ToolRefusal(f"'{key}' is required (a number)")
        return None
    if not _is_num(args[key]):
        raise ToolRefusal(f"'{key}' must be a number")
    return float(args[key])


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
            "activity_hint", "outfit_type", "terrain", "entry_room",
            "default_door_style", "default_window_style")
_LOC_INT = ("danger_level",)
_LOC_BOOL = ("swim_allowed",)
_LOC_KEYS = set(_LOC_STR) | set(_LOC_INT) | set(_LOC_BOOL) | {"rooms", "map3d"}
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


def _cap_lines(lines: List[str], hint: str = "narrow the query",
               budget: int = MAX_RESULT_CHARS, used: int = 0) -> List[str]:
    """At most MAX_LIST_LINES lines and "budget" characters ("used" already
    spent by a header), with "… N more — <hint>" for the rest."""
    out: List[str] = []
    total = used
    reserve = 60
    for i, line in enumerate(lines):
        if len(out) >= MAX_LIST_LINES or total + len(line) + 1 + reserve > budget:
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


def _fmt_poly(polygon: Any) -> str:
    return "[" + ",".join(f"[{_g(p[0])},{_g(p[1])}]" for p in polygon or []) + "]"


def _fields_arg(args: Dict[str, Any]) -> Optional[List[str]]:
    fields = args.get("fields")
    if fields is not None and (not isinstance(fields, list)
                               or not all(isinstance(f, str) for f in fields)):
        raise ToolRefusal("'fields' must be a list of field names")
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
       "one place; rooms as names unless 'rooms' is asked for")
def _get_location(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"id", "fields"}, "get_location")
    loc = _resolve_location(_str(args, "id", required=True))
    fields = _fields_arg(args)
    if fields:
        out = [f'{loc.get("id")} "{loc.get("name")}"']
        for key in fields:
            if key not in loc:
                out.append(f"{key}: (not set)")
            else:
                out.append(f"{key}: {_short(json.dumps(loc[key], ensure_ascii=False), 600)}")
        return _cut("\n".join(out))
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
       "terrain/height areas and places in a box (bboxes; polygons on request)")
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
    for a in list_areas():
        box = _bbox(a.get("polygon"))
        if not hits(box):
            continue
        label = (a.get("meta") or {}).get("label")
        line = (f'terrain {a["id"]} {a.get("kind")}'
                + (f' "{_short(label, 40)}"' if label else "")
                + f" {_fmt_box(box)} z_order {a.get('z_order') or 0}")
        if polys:
            line += " polygon " + _fmt_poly(a.get("polygon"))
        lines.append(line)
    for h in list_height_areas():
        box = _bbox(h.get("polygon"))
        if not hits(box):
            continue
        label = (h.get("meta") or {}).get("label")
        line = (f'height {h["id"]}' + (f' "{_short(label, 40)}"' if label else "")
                + f" {_g(h.get('height_m'))} m falloff {_g(h.get('falloff_m'))} m "
                + _fmt_box(box))
        if polys:
            line += " polygon " + _fmt_poly(h.get("polygon"))
        lines.append(line)
    for loc in list_locations():
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            continue
        px, pz = float(loc["pos_x"]), float(loc["pos_z"])
        if x0 <= px <= x1 and z0 <= pz <= z1:
            lines.append("place " + _loc_line(loc))
    if not lines:
        return "nothing in this box"
    return "\n".join(_cap_lines(lines, "use a smaller box"))


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
       "one character; field names unless fields are asked for")
def _get_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.character import (character_row_exists, get_character_config,
                                      get_character_profile)
    _only_keys(args, {"name", "fields"}, "get_character")
    name = _str(args, "name", required=True)
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    fields = _fields_arg(args)
    prof = get_character_profile(name) or {}
    cfg = get_character_config(name) or {}
    if fields:
        out = [f'"{name}"']
        for key in fields:
            src = prof if key in prof else cfg if key in cfg else None
            if src is None:
                out.append(f"{key}: (not set)")
            else:
                out.append(f"{key}: {_short(json.dumps(src[key], ensure_ascii=False), 600)}")
        return _cut("\n".join(out))

    def nonempty(d: Dict[str, Any]) -> List[str]:
        return sorted(k for k, v in d.items()
                      if v not in (None, "", [], {}) and not str(k).startswith("_"))
    out = [
        f'"{name}" at {prof.get("current_location") or "nowhere"}'
        + (f' / {prof.get("current_room")}' if prof.get("current_room") else ""),
        f'home: {cfg.get("home_location") or "(none)"}'
        + (f' / {cfg.get("home_room")}' if cfg.get("home_room") else ""),
        "profile fields: " + (", ".join(nonempty(prof)) or "(none)"),
        "config fields: " + (", ".join(nonempty(cfg)) or "(none)"),
    ]
    return _cut("\n".join(out))


@_tool("read_manual", False, "read_manual{section}",
       "one manual section: " + ", ".join(MANUAL_SECTIONS))
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
    return prompt_templates.render(path)


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
        after = get_location_by_id(lid) or {}
        line = f'created location {lid} "{after.get("name") or name}" at {_where(after)}'
        if taken:
            line += (f'; warnings: a place called "{name}" already exists — '
                     f"this is a second one")
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
            users = _room_users(lid, _rooms_removed_by(cur, body.get("rooms"),
                                                       body.get("map3d")))
            if users:
                raise ToolRefusal("the patch would remove a room in use — "
                                  + "; ".join(users))
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
        after = get_location_by_id(lid) or {}
        b, w = wu.diff_keys(before, after)
        step.attach(lid, {"op": "restore_location", "id": lid, "before": b},
                    before=b)
        line = (f'updated location {lid} "{after.get("name") or ""}": '
                + (", ".join(sorted(b)) if b else "no change"))
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
        line = f'placed location {lid} "{after.get("name") or ""}" at {_where(after)}'
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
            meta["stroke"] = norm["meta"]["stroke"]
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
                       "home_location", "home_room", "daily_schedule"}
#: update_character patch keys for home and daily schedule -> the draft key
#: world_dev_apply._apply_home_and_schedule reads.
#: Exactly one spelling each (the tool signature's); the draft spellings
#: home_location / daily_schedule are refused in a patch, so two spellings
#: of one value can never silently override each other.
_HOME_PATCH_KEYS = {"home": "home_location", "home_room": "home_room",
                    "schedule": "daily_schedule"}
#: Draft keys of the home group -> the patch / argument key to use instead.
_HOME_DRAFT_SPELLINGS = {"home_location": "home", "daily_schedule": "schedule"}
_OUTFIT_KEYS = {"name", "outfit", "pieces", "locations", "activities",
                "excluded_locations"}
_PIECE_KEYS = {"item_id", "slots", "name", "prompt_fragment", "description",
               "covers", "partially_covers"}


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


def _same_option(value: Any, option: Any) -> bool:
    """A value matches a select option only with the option's own JSON type
    (the number 2 for importance, never the string "2"; never a bool)."""
    if isinstance(option, str):
        return isinstance(value, str) and value == option
    if _is_num(option):
        return _is_num(value) and float(value) == float(option)
    return False


def _check_field_value(key: str, field: Dict[str, Any], value: Any) -> None:
    """The template field type decides what a value may be:
    text/textarea -> string; number -> number; select with fixed options (no
    ``source``, no ``allow_custom``) -> one of the option values in the
    option's JSON type, any other select -> string; season_day -> a
    "<season>:<day>" of this world's calendar ("" clears it). A field type
    this tool does not know is refused rather than stored unchecked."""
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
        options = [o["value"] for o in field.get("options") or []
                   if isinstance(o, dict) and "value" in o]
        if options and not field.get("source") and not field.get("allow_custom"):
            if not any(_same_option(value, o) for o in options):
                raise ToolRefusal(f"'{key}' must be one of: "
                                  + ", ".join(json.dumps(o, ensure_ascii=False)
                                              for o in options))
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


def _check_outfits(outfits: Any) -> None:
    """Shape of the draft's outfits; a piece is either a NEW piece {slots,
    name, ...} or an existing catalog piece {item_id}."""
    from app.models.inventory import VALID_PIECE_SLOTS, get_item
    if not isinstance(outfits, list):
        raise ToolRefusal("'outfits' must be a list of outfit objects")
    for i, outfit in enumerate(outfits):
        where = f"outfits[{i}]"
        if not isinstance(outfit, dict):
            raise ToolRefusal(f"{where} must be an object")
        _only_keys(outfit, _OUTFIT_KEYS, where)
        try:
            _str(outfit, "name", required=True)
            _str(outfit, "outfit")
            for key in ("locations", "activities", "excluded_locations"):
                _check_str_list(outfit.get(key), key)
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
                if not slots or any(s not in VALID_PIECE_SLOTS for s in slots):
                    raise ToolRefusal("'slots' must name at least one of "
                                      + ", ".join(VALID_PIECE_SLOTS))
                for key in ("covers", "partially_covers"):
                    _check_str_list(piece.get(key), key)
            except ToolRefusal as exc:
                raise ToolRefusal(f"{pw}: {exc}")


def _check_home_values(data: Dict[str, Any]) -> None:
    """home_location / home_room strings, daily_schedule a list of slot
    objects ({hour, location?, role?, sleep?})."""
    _str(data, "home_location")
    _str(data, "home_room")
    slots = data.get("daily_schedule")
    if slots is None:
        return
    if not isinstance(slots, list):
        raise ToolRefusal("'schedule' must be a list of {hour, location?, role?, "
                          "sleep?} objects")
    for i, slot in enumerate(slots):
        if not isinstance(slot, dict):
            raise ToolRefusal(f"schedule[{i}] must be an object")
        _only_keys(slot, {"hour", "location", "role", "sleep"}, f"schedule[{i}]")
        try:
            hour = _num(slot, "hour", required=True)
            if hour != int(hour):
                raise ToolRefusal("'hour' must be a whole number")
            _str(slot, "location")
            _str(slot, "role")
            _bool(slot, "sleep")
        except ToolRefusal as exc:
            raise ToolRefusal(f"schedule[{i}]: {exc}")


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
        if slot.get("location") and _resolve_world_location(slot["location"]) is None:
            raise ToolRefusal(f"schedule[{i}]: {slot['location']!r} is no place of "
                              "this world — use find_locations")


@_tool("create_character", True,
       "create_character{data, home?, home_room?, schedule?:[{hour, location?, role?, sleep?}]}",
       "new character (character schema fields + outfits); home = a place id or name")
def _create_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.character_name import validate_character_name
    from app.core.world_dev_apply import _get_generable_fields, apply_character
    from app.models.character import character_row_exists
    from app.models.character_template import get_template, list_templates
    from app.models.inventory import get_carried_item_ids, list_items
    _only_keys(args, {"data", "home", "home_room", "schedule"}, "create_character")
    data = args.get("data")
    if not isinstance(data, dict):
        raise ToolRefusal("'data' must be an object with the character fields")
    draft = {k: copy.deepcopy(v) for k, v in data.items() if v is not None}
    if "name" in draft and "character_name" not in draft:
        draft["character_name"] = draft.pop("name")
    for arg, key in (("home", "home_location"), ("home_room", "home_room"),
                     ("schedule", "daily_schedule")):
        if args.get(arg) is not None:
            if draft.get(key) is not None:
                # Two spellings of one value: refuse instead of letting one
                # silently win.
                raise ToolRefusal(f"'{arg}' is given twice (as argument and as "
                                  f"data.{key}) — send it once")
            draft[key] = copy.deepcopy(args[arg])
    raw_name = _str(draft, "character_name", required=True)
    template = _str(draft, "template") or "human-default"
    tmpl = get_template(template)
    if tmpl is None:
        raise ToolRefusal(f"no character template {template!r}")
    # Only the templates the World Dev character schema offers (the
    # selectable ones), and no temporary-NPC template: a temporary NPC comes
    # from the NPC pipeline (npc_ops), which owns its slot, home and rhythm.
    offered = sorted(t["name"] for t in list_templates("character")
                     if not ((get_template(t["name"]) or {}).get("features") or {})
                     .get("temporary_npc"))
    if template not in offered or (tmpl.get("features") or {}).get("temporary_npc"):
        raise ToolRefusal(f"template {template!r} cannot be created here — "
                          "templates: " + ", ".join(offered))
    draft["template"] = template
    fields = _template_fields(template)
    profile_keys, config_keys = _get_generable_fields(template)
    soul_keys = {k for k, f in fields.items() if f.get("source_file")}
    allowed = (_CHAR_DRAFT_SPECIAL | profile_keys | config_keys | soul_keys)
    _only_keys(draft, allowed, "character")
    for key, value in draft.items():
        if key in fields and key not in _CHAR_DRAFT_SPECIAL:
            _check_field_value(key, fields[key], value)
    if draft.get("outfits") is not None:
        _check_outfits(draft["outfits"])
    if draft.get("body_slots") is not None and not isinstance(draft["body_slots"], dict):
        raise ToolRefusal("'body_slots' must be an object")
    _check_home_values(draft)
    _check_home_targets(draft)
    # THE name rule (CharacterNameError is a ValueError -> refused), then
    # "taken" by the name it would be stored under.
    name = validate_character_name(raw_name)
    if character_row_exists(name):
        raise ToolRefusal(f"a character {name!r} already exists — use update_character")
    draft["character_name"] = name

    step.prepare()
    # The backup can take seconds: a character of that name created by
    # someone else meanwhile is refused here, before any journal row exists.
    if character_row_exists(name):
        raise ToolRefusal(f"a character {name!r} already exists — use update_character")
    items_before = {str(i.get("id")) for i in list_items()}
    inverse = {"op": "delete_character", "name": name, "items": []}
    step.begin("character", name, inverse)
    # Set by apply_character once it has confirmed, under the profile lock,
    # that the name is still free and is about to store the new row. Only
    # then is a row found after a failure THIS apply's character; without
    # it the row is a foreign one (a race after the re-check above) and must
    # never be claimed — a discard would delete it.
    claimed: List[bool] = []

    def reconcile():
        if not claimed or not character_row_exists(name):
            return None
        # The catalog items the failed apply created and already handed to
        # the character (a piece add_item stored but never handed over is
        # left to the backup).
        items = sorted(get_carried_item_ids(name) - items_before)
        return (name, {**inverse, "items": items}, {"name": name, "items": items})

    with step.writing(reconcile):
        result = apply_character(draft, created_by="world_dev", must_be_new=True,
                                 on_claim=lambda: claimed.append(True))
        items = [str(i) for i in result.get("created_items") or []]
        step.attach(name, {**inverse, "items": items})
    outfits = result.get("outfits") or []
    reused = sum(int(o.get("pieces_reused") or 0) for o in outfits)
    from app.models.character import get_character_config
    cfg = get_character_config(name) or {}
    home = str(cfg.get("home_location") or "")
    line = (f'created character "{name}" (template {template}'
            + (f", {len(outfits)} outfit(s), {len(items)} new piece(s)"
               + (f", {reused} existing" if reused else "") if outfits else "")
            + ")" + (f" home {home}" + (f" / {cfg.get('home_room')}"
                                        if cfg.get("home_room") else "")
                     if home else "")
            + _warn_suffix([str(w) for w in result.get("warnings") or []]))
    step.complete({"name": name, "items": items}, line)
    return line


@_tool("update_character", True, "update_character{name, patch}",
       "change fields of a character; 'soul:<field>' = the whole new text of a "
       "soul section; home / home_room / schedule")
def _update_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.core import soul_writer
    from app.core.keyed_lock import keyed_lock
    from app.core.linked_characters import LOCKED_PROFILE_FIELDS, soul_owner
    from app.core.world_dev_apply import _apply_home_and_schedule
    from app.models.character import (character_row_exists, get_character_config,
                                      get_character_profile, save_character_config,
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
    soul_patch: Dict[str, str] = {}  # rel path -> full new text
    home_data: Dict[str, Any] = {}
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
            if field.get("store") == "config":
                cfg_patch[key] = copy.deepcopy(value)
            else:
                prof_patch[key] = copy.deepcopy(value)
        else:
            raise ToolRefusal(f"unknown character field {key!r} — use get_character "
                              "for the field names")
    _check_home_values(home_data)
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

    return f'updated character "{name}": ' + "; ".join(lines)


# ── delete_created ───────────────────────────────────────────────────────

#: kind -> (inverse op of the creating entry, the inverse's key for the id)
_CREATE_OPS = {"location": ("delete_location", "id"),
               "terrain": ("delete_terrain_area", "id"),
               "height": ("delete_height_area", "id"),
               "character": ("delete_character", "name")}


@_tool("delete_created", True, "delete_created{kind, id}",
       "remove something THIS run created in this turn "
       "(kind location|terrain|height|character; id = the name for a character)")
def _delete_created(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"kind", "id"}, "delete_created")
    kind = _str(args, "kind", required=True)
    ident = _str(args, "id", required=True)
    if kind not in _CREATE_OPS:
        raise ToolRefusal("kind must be one of " + ", ".join(_CREATE_OPS))
    op, key = _CREATE_OPS[kind]
    creating = next((e for e in wr.entries(step.ctx.run_id, turn=step.ctx.turn)
                     if (e.get("inverse") or {}).get("op") == op
                     and str((e.get("inverse") or {}).get(key) or "") == ident), None)
    if creating is None:
        raise ToolRefusal(f"{kind} {ident!r} was not created by this run in this turn "
                          f"— only those can be deleted")
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
