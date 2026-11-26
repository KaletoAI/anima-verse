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
import re
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
MANUAL_SECTIONS = ("locations", "layout", "map", "characters", "homes", "naming", "systems")


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
        # Deferred before wr.begin: should begin raise or the step refuse
        # without writing, the character simply stays deferred until the turn
        # ends — harmless, the release replays whatever was suppressed.
        self._defer_media(target_kind, target_id)
        # The element's media baseline at the run's first touch — before the
        # write (create-inverse = created by the run, plan Task 4).
        self._note_media_touch(target_kind, target_id, inverse)
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
        self._defer_media(self.target_kind, target_id)
        self._note_media_touch(self.target_kind, target_id, inverse)

    def _note_media_touch(self, target_kind: Optional[str], target_id: Optional[str],
                          inverse: Optional[dict]) -> None:
        """``world_dev_media.note_touch`` for a location / character target,
        and for an item target the touch of every character wearing it
        (``note_item_touch`` — an edited shared piece re-plans its wearers'
        media). Never raises: a fingerprint error must not refuse the tool."""
        if target_kind in ("location", "character") and target_id:
            from app.core import world_dev_media
            world_dev_media.note_touch(self.ctx.run_id, str(target_kind), str(target_id), inverse)
        elif target_kind == "item" and target_id:
            from app.core import world_dev_media
            world_dev_media.note_item_touch(self.ctx.run_id, str(target_id), inverse)

    def _defer_media(self, target_kind: Optional[str], target_id: Optional[str]) -> None:
        """A character the step writes gets no automatic render until the turn
        ends (``world_dev_media.defer``, plan 2026-11-25-world-dev-free-media
        Task 2) — set BEFORE the write, so no trigger it reaches arms one."""
        if target_kind == "character" and target_id:
            from app.core import world_dev_media
            world_dev_media.defer(str(target_id), self.ctx.run_id)

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
               "character": ("character", "update_character"),
               "world_prop": ("world prop", ""),
               "terrain_type": ("terrain kind", ""),
               "item": ("item", ""),
               "relationship": ("form of address", "set_address"),
               "secret": ("secret", ""),
               "rule": ("rule", ""),
               "event": ("event", ""),
               "quest_template": ("quest template", "")}


def _kind_label(kind: str) -> str:
    """How a result line names a target kind (``world_prop`` -> "world prop")."""
    return _KEPT_HINTS.get(kind, (kind, ""))[0]


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


# The deepest nesting a tool's arguments may have. The deepest legitimate
# argument (a quest condition tree, a room list with openings) stays far
# below it; the cap keeps the journal's json.dumps and the tools' deepcopy
# from hitting Python's recursion limit (about 1000 frames) on hostile input.
MAX_ARG_DEPTH = 64


def _arg_depth_exceeds(value: Any, limit: int = MAX_ARG_DEPTH) -> bool:
    """True when VALUE nests dicts/lists deeper than LIMIT levels (the
    top-level object is level 1). Iterative, so it never recurses."""
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children = node.values()
        elif isinstance(node, (list, tuple)):
            children = node
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def run_tool(ctx: ToolCtx, name: str, args: Any) -> ToolResult:
    """Run ONE tool call as one journal step; see the module docstring."""
    spec = TOOLS.get(name)
    too_deep = _arg_depth_exceeds(args)
    if too_deep:
        # The journal row must not carry the arguments: dumping them is what
        # would overflow the stack.
        step = _Step(ctx, name, {"_raw": f"<arguments nested deeper than "
                                         f"{MAX_ARG_DEPTH} levels>"})
    else:
        step = _Step(ctx, name, args if isinstance(args, dict) else {"_raw": args})
    try:
        if too_deep:
            raise ToolRefusal(f"the arguments are nested too deeply (more than "
                              f"{MAX_ARG_DEPTH} levels of objects/lists)")
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


def _ring(value: Any, key: str) -> List[List[float]]:
    """A closed outline: at least 3 points that enclose ground. A ring whose
    points all lie on one line (zero area) is refused — the map would show
    it as a line and no placement check could ever see it."""
    pts = _points(value, key, 3)
    twice_area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                     - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))
    if abs(twice_area) < 1e-6:
        raise ToolRefusal(f"'{key}' encloses no area — its points lie on one line")
    return pts


def _only_keys(args: Dict[str, Any], allowed, what: str) -> None:
    extra = sorted(k for k in args if k not in allowed)
    if extra:
        raise ToolRefusal(f"unknown {what} key(s) {', '.join(extra)} — allowed: "
                          + (", ".join(sorted(allowed)) or "none"))


# The location fields the core writers take, including the location
# editor's extra fields.
_LOC_STR = ("name", "description", "image_prompt_day", "image_prompt_night",
            "image_prompt_building", "indoor", "decency", "style_hint",
            "activity_hint", "terrain", "entry_room",
            "default_door_style", "default_window_style")
_LOC_INT = ("danger_level",)
_LOC_BOOL = ("swim_allowed",)
#: The location editor's extra fields (gap 16): each is checked by
#: _check_location_extras and read back after the write (_verify_extras).
_LOC_EXTRA = ("event_settings", "stat_rates", "chattiness", "knowledge_item_id",
              "default_door_prop_id", "npc_slots")
_LOC_KEYS = (set(_LOC_STR) | set(_LOC_INT) | set(_LOC_BOOL) | set(_LOC_EXTRA)
             | {"rooms", "map3d"})
#: What a get_location fields read knows as a field even when the place
#: does not store it: the writable keys plus the id and the map position.
_LOC_READ_KEYS = _LOC_KEYS | {"id", "pos_x", "pos_z", "yaw_deg"}
# A room's image_prompt_building has a reader of the ROOM key
# (world_ops.resolve_gallery_subject, the room-model source image).
_ROOM_STR = ("id", "name", "description", "indoor", "decency", "style_hint",
             "image_prompt", "image_prompt_day", "image_prompt_night",
             "image_prompt_building", "activity_hint", "room_type")
_ROOM_BOOL = ("swim_allowed",)
_ROOM_KEYS = set(_ROOM_STR) | set(_ROOM_BOOL) | {"ambience", "stat_rates"}
#: The map3d keys create_location / update_location take (E3; plan_width_m
#: is derived from the boundary, never an input — an echo of the derived
#: value is dropped by _drop_derived_plan_width). The other keys
#: world_ops._sanitize_map3d keeps are refused there with a pointer, unless
#: update_location gets them back unchanged (_drop_map3d_echo); their stored
#: values survive the map3d merge of update_location.
_MAP3D_KEYS = {"floors", "footprint", "style", "color", "ground_corridor",
               "boundary", "storey_height_m"}
#: map3d keys that belong to the floor plan: written by set_room_layout.
_MAP3D_PLAN_KEYS = ("stairs", "outline", "level_outlines", "boundary_openings")
#: map3d keys with no reader-safe agent shape: the floor-plan editor sets them.
_MAP3D_EDITOR_KEYS = ("elevator", "elevator_kind", "level_floors", "wall_kind",
                      "level_walls", "area_model", "area_detail", "hull_openings")
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


_ABSENT = object()


def _rewrite_text(value: Any) -> str:
    if value is _ABSENT:
        return '"dropped"'
    return json.dumps(value, ensure_ascii=False)


def _same_leaf(sent: Any, stored: Any, tol: float = 0.0) -> bool:
    """Leaf compare of _refuse_rewritten: numbers equal after float() (within
    tol, for a writer that only rounds), a bool only equals a bool,
    everything else (strings: exact) by ==."""
    if isinstance(sent, bool) or isinstance(stored, bool):
        return type(sent) is type(stored) and sent == stored
    if _is_num(sent) and _is_num(stored):
        try:
            return abs(float(sent) - float(stored)) <= tol
        except OverflowError:
            return False
    return type(sent) is type(stored) and sent == stored


def _first_rewrite(path: str, sent: Any, stored: Any,
                   tol: float = 0.0) -> Optional[Tuple[str, Any]]:
    if stored is _ABSENT:
        return path, _ABSENT
    if isinstance(sent, dict):
        if not isinstance(stored, dict):
            return path, stored
        for key, value in sent.items():
            hit = _first_rewrite(f"{path}.{key}", value, stored.get(key, _ABSENT), tol)
            if hit:
                return hit
        return None
    if isinstance(sent, list):
        if not isinstance(stored, list):
            return path, stored
        for i, value in enumerate(sent):
            hit = _first_rewrite(f"{path}[{i}]", value,
                                 stored[i] if i < len(stored) else _ABSENT, tol)
            if hit:
                return hit
        return None
    return None if _same_leaf(sent, stored, tol) else (path, stored)


def _refuse_rewritten(what: str, sent: Any, stored: Any, tol: float = 0.0) -> None:
    """Refuse a value a core sanitizer would rewrite (clamp, drop, default
    away). Walks the SENT value — dicts by key, lists by index — and refuses
    at the first sent leaf that is missing or different in the sanitized
    value. Keys the sanitizer ADDS (defaults) are no rewrite. ``stored`` None
    for a sent dict/list means the sanitizer drops it as a whole. tol lets
    numbers through that differ by no more than a writer's rounding."""
    if stored is None and isinstance(sent, (dict, list)):
        stored = _ABSENT
    hit = _first_rewrite(what, sent, stored, tol)
    if hit:
        raise ToolRefusal(f"'{hit[0]}' would be stored as {_rewrite_text(hit[1])} "
                          f"— send that value or leave it out")


# ── Catalog sources (list_catalog and every refusal that lists values) ──

def _stat_keys() -> List[str]:
    from app.core.stat_hints import get_all_stat_keys
    return list(get_all_stat_keys())


def _event_categories() -> List[str]:
    from app.core.random_events import CATEGORIES
    return sorted(CATEGORIES)


def _room_type_ids() -> List[str]:
    from app.core.furniture_kits import load_room_types
    return list(load_room_types())


def _door_prop_ids() -> List[str]:
    from app.core.props import is_door_prop, list_props
    return sorted(str(p.get("id")) for p in list_props() if is_door_prop(p))


def _item_categories() -> List[str]:
    from app.models.inventory import VALID_ITEM_CATEGORIES
    # outfit_piece comes with outfits; garment is a mesh-only item kind
    # (equipped_mesh_pieces) that makes no sense as a free catalog item.
    return [c for c in VALID_ITEM_CATEGORIES if c not in ("outfit_piece", "garment")]


def _whole_in(value: Any, lo: int, hi: int) -> bool:
    return _is_num(value) and lo <= value <= hi and float(value) == int(value)


def _check_stat_rates(value: Any, what: str) -> None:
    """A stat_rates list (place or room): at most ten {stat, per_hour}, stat
    one of the world's stat keys, per_hour a whole number -50…50, each stat
    at most once (the sanitizer would keep a second entry and the hourly
    tick would apply both) — then nothing the editor's sanitizer would
    rewrite."""
    from app.core.world_ops import _sanitize_stat_rates
    if not isinstance(value, list):
        raise ToolRefusal(f"'{what}' must be a list of {{stat, per_hour}}")
    if len(value) > 10:
        raise ToolRefusal(f"'{what}' has {len(value)} entries — at most 10")
    keys = _stat_keys()
    for i, rate in enumerate(value):
        if not isinstance(rate, dict):
            raise ToolRefusal(f"'{what}[{i}]' must be an object {{stat, per_hour}}")
        _only_keys(rate, {"stat", "per_hour"}, f"{what}[{i}]")
        if rate.get("stat") not in keys:
            raise ToolRefusal(f"'{what}[{i}].stat' must be one of: "
                              + (", ".join(keys) or "none — this world has no stats")
                              + " (list_catalog stats)")
        if not _whole_in(rate.get("per_hour"), -50, 50):
            raise ToolRefusal(f"'{what}[{i}].per_hour' must be a whole number -50…50")
    first: Dict[str, int] = {}
    for i, rate in enumerate(value):
        stat = rate["stat"]
        if stat in first:
            raise ToolRefusal(f"'{what}[{i}].stat' {stat!r} is already rated in "
                              f"{what}[{first[stat]}] — one entry per stat")
        first[stat] = i
    _refuse_rewritten(what, value, _sanitize_stat_rates(value))


#: max_concurrent_events and event_cooldown_hours ranges of the place
#: editor (RandomEventsEditor.tsx inputs).
_EVENT_MAX_CONCURRENT = (1, 10)
_EVENT_COOLDOWN_H = (0, 48)


def _check_event_settings(value: Any) -> None:
    """A SENT event_settings object (a patch carries only the keys it
    changes; _update_location lays it over the stored object)."""
    from app.core.random_events import default_event_settings
    from app.core.world_ops import _sanitize_event_settings
    if not isinstance(value, dict):
        raise ToolRefusal("'event_settings' must be an object (list_catalog event_settings)")
    _only_keys(value, set(default_event_settings()) | {"stat_effects"}, "event_settings")
    cats = _event_categories()
    if "allowed_categories" in value:
        allowed = value["allowed_categories"]
        if not isinstance(allowed, list) or any(c not in cats for c in allowed):
            raise ToolRefusal("'event_settings.allowed_categories' must be a list of: "
                              + ", ".join(cats))
        if len(set(allowed)) != len(allowed):
            raise ToolRefusal("'event_settings.allowed_categories' names a category twice")
    if "event_blacklist" in value:
        bl = value["event_blacklist"]
        if not isinstance(bl, list) or not all(isinstance(t, str) for t in bl):
            raise ToolRefusal("'event_settings.event_blacklist' must be a list of strings")
        if any(not t.strip() or t != t.strip() for t in bl):
            raise ToolRefusal("'event_settings.event_blacklist' words must be non-empty "
                              "and without leading or trailing spaces")
        if len(set(bl)) != len(bl):
            raise ToolRefusal("'event_settings.event_blacklist' names a word twice")
    if "event_probability" in value:
        p = value["event_probability"]
        if not _is_num(p) or not 0 <= p <= 1:
            raise ToolRefusal("'event_settings.event_probability' must be a number 0…1")
    # The bounds of the place editor's own inputs (frontend
    # tabs/world/RandomEventsEditor.tsx: "Max" 1…10, "Cooldown h" 0…48).
    if "max_concurrent_events" in value:
        if not _whole_in(value["max_concurrent_events"], *_EVENT_MAX_CONCURRENT):
            raise ToolRefusal("'event_settings.max_concurrent_events' must be a whole "
                              "number %d…%d" % _EVENT_MAX_CONCURRENT)
        # Stored as the editor stores it (an int, never 2.0); the callers
        # check before they copy the sent value into the write body.
        value["max_concurrent_events"] = int(value["max_concurrent_events"])
    if "event_cooldown_hours" in value:
        # The editor input is parseInt: whole game hours only.
        if not _whole_in(value["event_cooldown_hours"], *_EVENT_COOLDOWN_H):
            raise ToolRefusal("'event_settings.event_cooldown_hours' must be a whole "
                              "number %d…%d (game hours)" % _EVENT_COOLDOWN_H)
        value["event_cooldown_hours"] = int(value["event_cooldown_hours"])
    if "stat_effects" in value:
        effects = value["stat_effects"]
        if not isinstance(effects, dict):
            raise ToolRefusal("'event_settings.stat_effects' must be an object "
                              "{category: {stat: amount}}")
        keys = _stat_keys()
        for cat, eff in effects.items():
            if cat not in cats:
                raise ToolRefusal(f"'event_settings.stat_effects' category {cat!r} must be "
                                  f"one of: " + ", ".join(cats))
            if not isinstance(eff, dict):
                raise ToolRefusal(f"'event_settings.stat_effects.{cat}' must be an object "
                                  f"{{stat: amount}}")
            for stat, amount in eff.items():
                if stat not in keys:
                    raise ToolRefusal(f"'event_settings.stat_effects.{cat}': stat {stat!r} "
                                      f"must be one of: " + (", ".join(keys) or "none"))
                if not _whole_in(amount, -100, 100):
                    raise ToolRefusal(f"'event_settings.stat_effects.{cat}.{stat}' must be "
                                      f"a whole number -100…100")
    _refuse_rewritten("event_settings", value, _sanitize_event_settings(value))


#: The keys npc_spawn.normalize_slot stores.
_SLOT_KEYS = {"role", "template", "count_min", "count_max", "briefing", "room",
              "when", "radius_m", "character"}


def _check_npc_slots(value: Any, room_ids: Optional[Dict[str, str]]) -> None:
    """npc_slots of a place: nothing normalize_slots would rewrite (duplicate
    role, counts out of range, unusable when / radius_m); a slot's room is a
    STORED room id of the place (``room_ids`` id -> name; None on create — the
    ids are minted by the create writer); a bound character is an existing
    temporary NPC. An unusable when / count / radius_m is refused here with
    its own wording, BEFORE normalize_slots runs (which would log a warning
    for it and rewrite it)."""
    from app.core.npc_spawn import SLOT_COUNT_MAX, normalize_slots
    from app.core.npc_windows import normalize_when
    from app.models.character import character_row_exists, is_temporary_npc
    if not isinstance(value, list):
        raise ToolRefusal("'npc_slots' must be a list of slot objects")
    for i, slot in enumerate(value):
        if not isinstance(slot, dict):
            raise ToolRefusal(f"'npc_slots[{i}]' must be an object")
        _only_keys(slot, _SLOT_KEYS, f"npc_slots[{i}]")
        if not isinstance(slot.get("role"), str) or not slot["role"].strip():
            raise ToolRefusal(f"'npc_slots[{i}]' needs a non-empty 'role'")
        _check_slot_values(slot, f"npc_slots[{i}]", SLOT_COUNT_MAX, normalize_when)
    _refuse_rewritten("npc_slots", value, normalize_slots(value))
    for i, slot in enumerate(value):
        room = str(slot.get("room") or "")
        if room:
            if room_ids is None:
                raise ToolRefusal(f"'npc_slots[{i}].room': room ids exist only after the "
                                  f"place is created — add the slot's room with "
                                  f"update_location")
            if room not in room_ids:
                raise ToolRefusal(f"'npc_slots[{i}].room' must be a room id of this place: "
                                  + (", ".join(f'{rid} "{n}"' for rid, n in room_ids.items())
                                     or "none"))
        tpl = slot.get("template")
        if tpl not in (None, ""):
            names = _npc_template_names()
            if not isinstance(tpl, str) or tpl not in names:
                raise ToolRefusal(f"'npc_slots[{i}].template' must be a character "
                                  f"template: " + (", ".join(names) or "none")
                                  + ' ("" = the NPC pipeline\'s default)')
        who = str(slot.get("character") or "")
        if who and not (character_row_exists(who) and is_temporary_npc(who)):
            raise ToolRefusal(f"'npc_slots[{i}].character' {who!r} is no existing "
                              f"temporary NPC")


def _slot_number(value: Any) -> Optional[float]:
    """A finite JSON number (never a bool or a numeric string), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _check_slot_values(slot: Dict[str, Any], where: str, count_max_bound: int,
                       normalize_when: Any) -> None:
    """when / count_min / count_max / radius_m of one slot, each refused with
    its own wording (an absent or null value is the slot default)."""
    when = slot.get("when")
    if when not in (None, "") and not (isinstance(when, str) and normalize_when(when)):
        raise ToolRefusal(f"'{where}.when' must be \"\" (always), \"day\", \"night\" or a "
                          f"game-time span \"HH:MM-HH:MM\" — got {when!r}")
    counts: Dict[str, float] = {}
    for key in ("count_min", "count_max"):
        if slot.get(key) is None:
            continue
        num = _slot_number(slot[key])
        if num is None or num != int(num) or not 0 <= num <= count_max_bound:
            raise ToolRefusal(f"'{where}.{key}' must be a whole number 0…{count_max_bound} "
                              f"— got {slot[key]!r}")
        counts[key] = num
    # normalize_slot's defaults: count_min 1, count_max max(1, count_min).
    low = counts.get("count_min", 1)
    if "count_max" in counts and counts["count_max"] < low:
        raise ToolRefusal(f"'{where}.count_max' must not be below count_min ({_g(low)}"
                          + ("" if "count_min" in counts else ", its default")
                          + f") — got {_g(counts['count_max'])}")
    if slot.get("radius_m") is not None:
        radius = _slot_number(slot["radius_m"])
        if radius is None or radius < 0:
            raise ToolRefusal(f"'{where}.radius_m' must be a number ≥ 0 (metres; 0 = the "
                              f"rooms) — got {slot['radius_m']!r}")


def _npc_template_names() -> List[str]:
    """The character templates a slot may name (the selectable ones)."""
    from app.models.character_template import list_templates
    return sorted(t["name"] for t in list_templates("character"))


def _slot_room_ids(rooms: List[Dict[str, Any]]) -> Dict[str, str]:
    """The room ids a slot may name: every room with an id except the
    reserved ones (the ground and the storey corridors, ids "__…" — the
    corridor sync may drop a corridor on its own)."""
    return {str(r.get("id")): str(r.get("name") or r.get("id"))
            for r in rooms if isinstance(r, dict) and r.get("id")
            and not str(r.get("id")).startswith("__")}


def _check_location_extras(data: Dict[str, Any]) -> None:
    """Value checks of the editor's extra fields that need no stored place
    (npc_slots is checked by the tools, which know the room ids)."""
    for key in ("knowledge_item_id", "default_door_prop_id"):
        _str(data, key)
    if "stat_rates" in data:
        _check_stat_rates(data["stat_rates"], "stat_rates")
    if "event_settings" in data:
        _check_event_settings(data["event_settings"])
    if "chattiness" in data:
        c = data["chattiness"]
        if not (c == "" or (_is_num(c) and 0 <= c <= 1)):
            raise ToolRefusal("'chattiness' must be a number 0…1 (\"\" = the world value)")
    if "knowledge_item_id" in data:
        from app.models.inventory import get_item
        v = data["knowledge_item_id"]
        if v != "" and (v != v.strip() or not get_item(v)):
            raise ToolRefusal(f"'knowledge_item_id': no item {v!r} (\"\" = none)")
    if "default_door_prop_id" in data:
        from app.core.props import is_door_prop, read_sidecar, safe_prop_id
        v = data["default_door_prop_id"]
        if v != "" and (safe_prop_id(v) != v
                        or not is_door_prop(read_sidecar(v, read_only=True))):
            doors = _door_prop_ids()
            raise ToolRefusal("'default_door_prop_id' must be a door prop: "
                              + (", ".join(doors[:20]) or "none")
                              + (" …" if len(doors) > 20 else "")
                              + ' ("" = none; list_catalog door_props)')


def _check_room_extras(room: Dict[str, Any], what: str) -> None:
    from app.core.world_ops import sanitize_ambience
    if "room_type" in room and room["room_type"] != "":
        types = _room_type_ids()
        if room["room_type"] not in types:
            raise ToolRefusal("'room_type' must be one of: " + ", ".join(types)
                              + ' ("" = none) — see list_catalog room_types')
    if "stat_rates" in room:
        _check_stat_rates(room["stat_rates"], f"{what}.stat_rates")
    if "ambience" in room:
        amb = room["ambience"]
        if not isinstance(amb, dict):
            raise ToolRefusal(f"'{what}.ambience' must be an object {{daylight, tint?}}")
        _only_keys(amb, {"daylight", "tint"}, f"{what}.ambience")
        # {} clears the ambience: sanitize_ambience drops it (= the default
        # light), and a kept room's merge carries the {} to the writer.
        if amb:
            _refuse_rewritten(f"{what}.ambience", amb, sanitize_ambience(amb))


def _expected_extra(key: str, value: Any) -> Any:
    """What the location writers store for an accepted extra value (None =
    the key is absent) — the read-back of _verify_extras."""
    if key == "chattiness":
        return None if value == "" else float(value)
    if key == "npc_slots":
        from app.core.npc_spawn import normalize_slots
        return normalize_slots(value) or None
    if key == "stat_rates":
        from app.core.world_ops import _sanitize_stat_rates
        return _sanitize_stat_rates(value)
    if key == "event_settings":
        from app.core.world_ops import _sanitize_event_settings
        return _sanitize_event_settings(value)
    return value


def _verify_extras(lid: str, body: Dict[str, Any]) -> None:
    """Raise (inside step.writing) when an accepted extra field was not
    stored as the writer's sanitizer would keep it."""
    from app.models.world import get_location_by_id
    loc = get_location_by_id(lid) or {}
    for key in _LOC_EXTRA:
        if key in body and loc.get(key) != _expected_extra(key, body[key]):
            raise RuntimeError(f"{key} was not stored as sent (got {loc.get(key)!r})")


#: The room keys of the location editor read back by _verify_room_extras.
_ROOM_EXTRA = ("room_type", "ambience", "stat_rates", "image_prompt_building")


def _verify_room_extras(lid: str, sent_rooms: List[Dict[str, Any]],
                        old_ids: set) -> None:
    """Raise (inside step.writing) when a SENT room extra was not stored as
    the writer's sanitizer keeps it. A sent room with an id is matched by id,
    a new one by name among the rooms the write added (ids not in old_ids)."""
    from app.core.world_ops import _sanitize_stat_rates, sanitize_ambience
    from app.models.world import get_location_by_id
    stored = [r for r in (get_location_by_id(lid) or {}).get("rooms") or []
              if isinstance(r, dict)]
    used: set = set()
    for sent in sent_rooms:
        rid = str(sent.get("id") or "")
        # Two new rooms may share a name: each takes the next unused one.
        room = next((r for r in stored if id(r) not in used and (
            str(r.get("id") or "") == rid if rid else
            (r.get("name") == sent.get("name")
             and str(r.get("id") or "") not in old_ids))), None)
        if room is not None:
            used.add(id(room))
        keys = [k for k in _ROOM_EXTRA if k in sent]
        if not keys:
            continue
        if room is None:
            raise RuntimeError(f'room {rid or sent.get("name")!r} was not stored')
        for key in keys:
            value = sent[key]
            if key == "ambience":
                want = sanitize_ambience(value)
            elif key == "stat_rates":
                want = _sanitize_stat_rates(value)
            else:
                want = value
            if room.get(key) != want:
                raise RuntimeError(f"room {room.get('id')} {key} was not stored as "
                                   f"sent (got {room.get(key)!r})")


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


def _drop_derived_plan_width(data: Dict[str, Any], derived: float) -> Dict[str, Any]:
    """``map3d.plan_width_m`` is computed by the writer from the boundary
    (world_geometry.polygon_plan_width_m), never an input. A value sent back
    unchanged — the stored map3d echoed — is dropped; any other value is
    refused with the derived width, so the agent learns where the size comes
    from. ``derived`` is the width the write would store (0 = no outline).
    Returns ``data`` itself or a copy without the key."""
    m3 = data.get("map3d")
    if not isinstance(m3, dict) or "plan_width_m" not in m3:
        return data
    sent = m3["plan_width_m"]
    ok = (sent is None or (isinstance(sent, (int, float)) and not isinstance(sent, bool)
                           and derived > 0 and abs(float(sent) - derived) <= 0.01))
    if not ok:
        raise ToolRefusal(
            "map3d.plan_width_m is derived by the writer from map3d.boundary "
            + (f"(here {_g(derived)} m)" if derived > 0 else "(this place has no outline)")
            + " — omit it; change the size through the boundary")
    out = dict(data)
    out["map3d"] = {k: v for k, v in m3.items() if k != "plan_width_m"}
    return out


def _stored_map3d(lid: str) -> Dict[str, Any]:
    """The stored map3d of a place ({} when the place or its map3d is missing).
    Read without the write lock: callers use it for pre-checks of keys that
    are dropped, never written."""
    from app.models.world import get_location_by_id
    m3 = (get_location_by_id(lid) or {}).get("map3d")
    return m3 if isinstance(m3, dict) else {}


def _stored_plan_width(stored_m3: Dict[str, Any]) -> float:
    """The plan width the stored outline yields (0.0 without one)."""
    from app.core.world_geometry import polygon_plan_width_m
    boundary = stored_m3.get("boundary")
    if boundary is None:
        return 0.0
    return float(polygon_plan_width_m(boundary) or 0.0)


def _drop_map3d_echo(lid: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """update_location: the map3d an agent read and sends back must not be
    refused for keys it cannot write. A floor-plan or editor key
    (_MAP3D_PLAN_KEYS / _MAP3D_EDITOR_KEYS) equal to the stored value is
    dropped — a changed one stays and is refused by _check_location_fields
    with its pointer; ``plan_width_m`` goes through _drop_derived_plan_width.
    A map3d left empty stays an empty merge (a no-op for the map3d).
    Returns ``patch`` itself or a copy."""
    m3 = patch.get("map3d")
    if not isinstance(m3, dict):
        return patch
    echo_keys = [k for k in (*_MAP3D_PLAN_KEYS, *_MAP3D_EDITOR_KEYS) if k in m3]
    if not echo_keys and "plan_width_m" not in m3:
        return patch
    stored = _stored_map3d(lid)
    out = dict(patch)
    if "plan_width_m" in m3:
        if m3.get("boundary") is not None:
            derived = _derived_plan_width(("map3d.boundary", m3["boundary"]))
        else:
            derived = _stored_plan_width(stored)
        out = _drop_derived_plan_width(out, derived)
    new_m3 = {k: v for k, v in out["map3d"].items()
              if not (k in echo_keys and k in stored and stored[k] == v)}
    out["map3d"] = new_m3
    return out


def _derived_plan_width(*rings: Tuple[str, Any]) -> float:
    """The plan width of the first given outline as (key, ring) — a malformed
    one is refused under its key; 0.0 when none is given."""
    from app.core.world_geometry import polygon_plan_width_m
    for key, ring in rings:
        if ring is not None:
            return float(polygon_plan_width_m(_ring(ring, key)) or 0.0)
    return 0.0


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
    _check_location_extras(data)
    if data.get("map3d") is not None:
        m3 = data["map3d"]
        if not isinstance(m3, dict):
            raise ToolRefusal("'map3d' must be an object")
        for key in sorted(m3):
            if key in _MAP3D_PLAN_KEYS:
                raise ToolRefusal(f"map3d.{key} is part of the floor plan — use "
                                  f"set_room_layout (read_manual layout)")
            if key in _MAP3D_EDITOR_KEYS:
                raise ToolRefusal(f"map3d.{key} is set in the floor-plan editor")
        _only_keys(m3, _MAP3D_KEYS, "map3d")
        if m3.get("boundary") is not None:
            _ring(m3["boundary"], "map3d.boundary")
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
                _check_room_extras(room, f"rooms[{i}]")
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
    if isinstance(out.get("npc_slots"), list):
        out["npc_slots"] = [{k: v for k, v in s.items() if v is not None}
                            if isinstance(s, dict) else s for s in out["npc_slots"]]
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


def _corners(box: Tuple[float, float, float, float]) -> str:
    return f"({_g(box[0])},{_g(box[1])})-({_g(box[2])},{_g(box[3])})"


def _fmt_box(box: Optional[Tuple[float, float, float, float]]) -> str:
    if box is None:
        return "no area"
    return "bbox " + _corners(box)


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

def _kind_text(kind: str, entry: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> str:
    """One terrain kind as the overview lists it: id, name and the flags that
    differ from the default (walkable, dry, speed ×1)."""
    from app.core.terrain_types import is_water_kind
    flags: List[str] = []
    if not bool(entry.get("passable", True)):
        flags.append("impassable")
    if is_water_kind(kind, catalog):
        flags.append("water")
    try:
        speed = float(entry.get("speed_factor", 1.0))
    except (TypeError, ValueError):
        speed = 1.0
    if speed != 1.0:
        flags.append(f"speed ×{_g(speed)}")
    return (f'{kind} "{_label(entry.get("name") or kind, 40)}"'
            + (f" ({', '.join(flags)})" if flags else ""))


#: The world_overview setup line's cut; the full text is in the system prompt.
SETUP_LINE_CHARS = 200


def _setup_line(text: str) -> str:
    """The setup line, cut at SETUP_LINE_CHARS; a cut line points at the
    system prompt, which carries the whole setup text."""
    whole = " ".join(str(text or "").split())
    if not whole:
        return "setup: (none)"
    if len(whole) <= SETUP_LINE_CHARS:
        return f"setup: {whole}"
    return (f"setup: {whole[:SETUP_LINE_CHARS - 1].rstrip()} … "
            "(full text in your instructions)")


def _calendar_line() -> str:
    """The world calendar (seasons, year label, week days) and the current
    game time — read only; the calendar is not the builder's to change."""
    from app.core.game_time import get_calendar
    from app.core.timeutils import game_time
    cal = get_calendar()
    seasons = ", ".join(f'{s.key} "{s.name}" {s.days} d' for s in cal.seasons)
    week = ", ".join(cal.week_days) or "none"
    return (f"calendar: {len(cal.seasons)} seasons — {seasons}; "
            f'year label "{cal.year_label}"; week days: {week}; '
            f'now {game_time().label("en")}')


def _content_language_line(roster: List[str]) -> str:
    """The content-language rule plus the languages characters speak — the
    RAW stored profile key (get_character_language answers a default for
    an unset key, which would invent a language nobody chose). The roster
    is every character row, out-of-world ones included — the same roster
    the counts line counts."""
    from app.models.character import get_character_profile
    counts: Dict[str, int] = {}
    for name in roster:
        lang = str((get_character_profile(name) or {}).get("language") or "").strip()
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    line = "content language: the language of your task text"
    if counts:
        line += "; characters speak " + ", ".join(
            f"{lang} ×{n}" for lang, n in sorted(counts.items(),
                                                 key=lambda kv: (-kv[1], kv[0])))
    return line


def _linked_line(name: str) -> Optional[str]:
    """One line on a linked family (one mind in several bodies), or None
    for an unlinked character."""
    from app.core.linked_characters import bodies_of, leader_of
    from app.models.character import get_character_status, is_out_of_world
    leader = leader_of(name)
    if leader:
        status = get_character_status(name)
        return (f"linked: body of {leader} "
                f"({status if is_out_of_world(status) else 'in the world'})")
    bodies = bodies_of(name)
    if not bodies:
        return None
    family = [name] + bodies
    out = {m: is_out_of_world(get_character_status(m)) for m in family}
    # ONE predicate for both: the present member is the first one NOT out of
    # the world (present_member() only means "not dormant" — a pooled member
    # would be in the world and in the outside list at once).
    present = next((m for m in family if not out[m]), None)

    def who(member: str) -> str:
        # The card is the leader's own: it is "this character", not a name.
        return "this character" if member == name else member

    outside = [who(m) for m in family if out[m]]
    if not present:
        where = "all of them stand outside the world"
    elif not outside:
        where = f"{who(present)} is in the world"
    else:
        listed = (outside[0] if len(outside) == 1
                  else ", ".join(outside[:-1]) + " and " + outside[-1])
        verb = "stands" if len(outside) == 1 else "stand"
        where = f"{listed} {verb} outside the world while {who(present)} is in it"
    return f"linked: leads {', '.join(bodies)} ({where})"


@_tool("world_overview", False, "world_overview{}",
       "world setup, compass, calendar, content language, built extent, build bounds, "
       "terrain kinds, counts, places")
def _world_overview(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.terrain_types import effective_catalog
    from app.models.character import list_available_characters
    from app.models.heightfield import list_height_areas
    from app.models.terrain import list_areas
    from app.models.world import list_locations
    from app.models.world_setup import get_world_setup_text
    _only_keys(args, set(), "world_overview")
    locs = list_locations()
    placed = [l for l in locs if l.get("pos_x") is not None and l.get("pos_z") is not None]
    # Every character row (pooled + dormant too): the language line and the
    # counts line read the same roster, the counts line names how many of
    # them stand outside the world.
    roster = list_available_characters(include_pooled=True)
    outside = len(roster) - len(list_available_characters())
    extent = _built_extent()
    build = _run_bounds(step.ctx.run_id)
    catalog = effective_catalog()
    kinds = [_kind_text(kind, entry, catalog) for kind, entry in sorted(catalog.items())]
    head = [
        _setup_line(get_world_setup_text()),
        "compass: x = east, z = south, metres",
        _calendar_line(),
        _content_language_line(roster),
        "extent: " + (_box_text(extent) if extent else "none yet"),
        "build bounds: " + (_box_text(build) if build else
                            "none — set_build_bounds{min_x, min_z, max_x, max_z} first "
                            "in an empty world"),
        "terrain kinds: " + (", ".join(kinds) or "none"),
        (f"counts: {len(locs)} locations ({len(placed)} placed), "
         f"{len(roster)} characters"
         + (f" ({outside} out of the world)" if outside else "") + ", "
         f"{len(list_areas())} terrain areas, {len(list_height_areas())} height areas"),
        "locations:",
    ]
    used = sum(len(h) + 1 for h in head)
    body = [f'{l.get("id")} "{_short(l.get("name"), 40)}" {_where(l)}' for l in locs]
    # The header is not capped by itself (a long terrain catalog), so the
    # whole result goes through the cut as well.
    return _cut("\n".join(head + (_cap_lines(body, "use find_locations", used=used)
                                  or ["(none)"])))


#: Shortest and longest side of a run's build box (E3): a smaller side is a
#: typo, a larger one a runaway number.
BUILD_BOUNDS_MIN_SIDE_M = 50.0
BUILD_BOUNDS_MAX_SIDE_M = 20000.0
_BOX_KEYS = ("min_x", "min_z", "max_x", "max_z")


def _box_text(box: Dict[str, Any]) -> str:
    return (f"x {_g(box['min_x'])}…{_g(box['max_x'])}, "
            f"z {_g(box['min_z'])}…{_g(box['max_z'])}")


def _run_bounds(run_id: str) -> Optional[Dict[str, float]]:
    """The run's build box (world_dev_runs.set_bounds), or None."""
    from app.core.map_layout_apply import valid_box
    box = (wr.get_run(run_id) or {}).get("bounds")
    return box if valid_box(box) else None


def _place_points(loc_like: Dict[str, Any], x: Any, z: Any,
                  yaw: Any) -> List[Tuple[float, float]]:
    """The pin plus the world outline of a place standing at (x, z, yaw) —
    its stored boundary; a place without one is its pin only (it has no area
    on the map, _placement_entry)."""
    from app.core.world_geometry import boundary_world_points
    entry = _placement_entry(loc_like, x, z, yaw)
    if entry["boundary"] is None:
        return [(entry["pos_x"], entry["pos_z"])]
    outline = boundary_world_points({
        "pos_x": entry["pos_x"], "pos_z": entry["pos_z"], "yaw_deg": entry["yaw_deg"],
        "map3d": {"boundary": entry["boundary"]}}) or []
    return ([(entry["pos_x"], entry["pos_z"])]
            + [(float(px), float(pz)) for px, pz in outline])


def _polygon_points(polygon: Any) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for pt in polygon or []:
        try:
            out.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _built_places() -> List[List[Tuple[float, float]]]:
    """The points (pin + outline) of every placed place."""
    from app.models.world import list_locations
    return [_place_points(l, l["pos_x"], l["pos_z"], l.get("yaw_deg"))
            for l in list_locations()
            if l.get("pos_x") is not None and l.get("pos_z") is not None]


def _built_extent() -> Optional[Dict[str, float]]:
    """The built extent: map_layout_apply.current_world_bounds (drawn place
    outlines and painted ground) plus every placed place's pin — a place
    without a stored outline is built too, as the point the map shows."""
    from app.core.map_layout_apply import box_union, current_world_bounds
    box = current_world_bounds()
    for pts in _built_places():
        box = box_union(box, {"min_x": round(min(p[0] for p in pts), 2),
                              "min_z": round(min(p[1] for p in pts), 2),
                              "max_x": round(max(p[0] for p in pts), 2),
                              "max_z": round(max(p[1] for p in pts), 2)})
    return box


def _bounds_warnings(points: List[Tuple[float, float]], what: str,
                     run_id: str) -> List[str]:
    """Out-of-box WARNINGS against the run's build box (E3 — never a
    refusal); [] without a box or when every point lies inside. One point
    reads "<what> (x,z) lies outside …", several "<what>: k of n points lie
    outside …" ("1 of n points lies outside …" when exactly one is out)."""
    from app.core.map_layout_apply import point_outside
    box = _run_bounds(run_id)
    if box is None or not points:
        return []
    outside = [p for p in points if point_outside(box, p[0], p[1])]
    if not outside:
        return []
    if len(points) == 1:
        x, z = points[0]
        return [f"{what} ({_g(x + 0.0)},{_g(z + 0.0)}) lies outside the build bounds"]
    verb = "lies" if len(outside) == 1 else "lie"
    return [f"{what}: {len(outside)} of {len(points)} points {verb} outside the build bounds"]


def _count_outside(box: Dict[str, float]) -> int:
    """How many placed places, terrain areas, height areas and world props
    have a point outside the box (a world prop is its point (x, z)).

    Cost: one pass over every placed place (pin + stored outline), terrain
    area, height area and world prop, on each set_build_bounds (like
    _built_extent). Fine at village scale; if it ever gets slow, cache by the
    world/terrain/world-props generation counters or test polygon bounding
    boxes first."""
    from app.core.map_layout_apply import point_outside
    from app.models.heightfield import list_height_areas
    from app.models.terrain import list_areas
    from app.models.world_props import list_world_props
    shapes = _built_places() + [_polygon_points(a.get("polygon"))
                                for a in list(list_areas()) + list(list_height_areas())]
    shapes += [[(float(p["x"]), float(p["z"]))] for p in list_world_props()]
    return sum(1 for pts in shapes if any(point_outside(box, x, z) for x, z in pts))


@_tool("set_build_bounds", False, "set_build_bounds{min_x, min_z, max_x, max_z}",
       "the box (world metres) this run builds in — later writes warn when they leave it")
def _set_build_bounds(step: _Step, args: Dict[str, Any]) -> str:
    """Run metadata, not world data (E3): stored on the run row, journaled as
    a read, never undone. Each side 50 … 20 000 m."""
    _only_keys(args, set(_BOX_KEYS), "set_build_bounds")
    box = {k: _coord(args, k, required=True) for k in _BOX_KEYS}
    for axis in ("x", "z"):
        lo, hi = box[f"min_{axis}"], box[f"max_{axis}"]
        if lo >= hi:
            raise ToolRefusal(f"min_{axis} {_g(lo)} must be below max_{axis} {_g(hi)}")
        side = hi - lo
        if side < BUILD_BOUNDS_MIN_SIDE_M or side > BUILD_BOUNDS_MAX_SIDE_M:
            raise ToolRefusal(f"the {axis} side is {_g(side)} m — each side must be "
                              f"{_g(BUILD_BOUNDS_MIN_SIDE_M)} … "
                              f"{_g(BUILD_BOUNDS_MAX_SIDE_M)} m (a small village: 300)")
    # Count before storing: a failing read then leaves no box behind an error.
    outside = _count_outside(box)
    wr.set_bounds(step.ctx.run_id, box)
    line = "build bounds of this run: " + _box_text(box)
    if outside:
        what = ("place / area / prop lies" if outside == 1
                else "places / areas / props lie")
        line += (f"; warning: {outside} {what} outside — they stay, "
                 f"the box only guides new writes")
    return line


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
    from app.models.rules import block_rules_at, rule_action
    block_rules = [f'{r.get("id")} "{_short(r.get("name"), 40)}" ({rule_action(r)}'
                   + (f', when {_short(r.get("condition"), 60)}' if r.get("condition") else "")
                   + ")" for r in block_rules_at(str(loc.get("id") or ""))]
    other = sorted(k for k, v in loc.items()
                   if k not in shown and v not in (None, "", [], {}))
    out = [
        f'{loc.get("id")} "{loc.get("name")}" {_where(loc)} · {_width(loc)} · '
        f'{loc.get("indoor") or "indoor unset"} · danger {loc.get("danger_level") or 0}',
        f"description: {_short(loc.get('description'), 300) or '(none)'}",
        "rooms: " + (", ".join(rooms) or "(none)"),
        "other fields: " + (", ".join(other) or "(none)"),
    ]
    if block_rules:
        out.append("rules: " + "; ".join(block_rules))
    return _cut("\n".join(out))


#: Longest furniture_kits line of list_catalog (cut at whole room types).
_KIT_LINE_CHARS = 500
#: Read budget for ``list_catalog quest_types``: the whole catalog must reach
#: the model in one call; it grows with registered types.
MAX_QUEST_TYPES_CHARS = 5000

_QUEST_TYPES_HEADER = (
    'Conditions go into steps[].condition and start_condition, prerequisite '
    'types into prerequisites.condition; an effect is an entry '
    '{"key", "type", "params", "permanent"?} of setup_effects, '
    'steps[].on_done or rewards.',
    "* = required. role[k] takes a role key of kind k. target[...] takes a "
    "role key of the listed kind or the key of an EARLIER effect that makes "
    "the listed object kind: a step condition reaches setup_effects and the "
    "on_done of earlier steps; an on_done entry also the earlier entries of "
    "its own list; a reward every effect key; a setup entry the earlier setup "
    "entries; start_condition and prerequisites setup keys only.",
)


def _quest_param_text(p: Dict[str, Any]) -> str:
    """Render one catalog parameter as ``key[*]:type-text`` for the
    ``list_catalog quest_types`` header, with the ``role[...]`` (including
    ``avatar_default``), ``target[...]`` (``role_kinds`` / ``object_kinds``),
    and ``select[...]`` forms."""
    key = f"{p.get('key')}{'*' if p.get('required') else ''}"
    ptype = str(p.get("type") or "")
    if ptype == "role":
        kinds = "|".join(str(k) for k in (p.get("role_kinds") or []))
        if kinds and p.get("avatar_default"):
            ttext = f"role[{kinds}; empty = the avatar]"
        elif kinds:
            ttext = f"role[{kinds}]"
        elif p.get("avatar_default"):
            ttext = "role[empty = the avatar]"
        else:
            ttext = "role"
    elif ptype == "target":
        parts: List[str] = []
        if p.get("role_kinds"):
            parts.append("|".join(str(k) for k in p["role_kinds"]) + " role")
        if p.get("object_kinds"):
            parts.append("|".join(str(k) for k in p["object_kinds"]) + " effect key")
        ttext = f"target[{' or '.join(parts)}]" if parts else "target"
    elif ptype == "select":
        choices = "|".join(str(c) for c in (p.get("choices") or []))
        ttext = f"select[{choices}]" if choices else "select"
    else:
        ttext = ptype
    return f"{key}:{ttext}"

#: The value lists list_catalog answers (the refusals that list values read
#: the same sources).
CATALOG_NAMES = ("stats", "event_categories", "event_settings", "room_types",
                 "furniture_kits", "surface_kinds", "door_props", "terrain_kinds",
                 "item_categories", "secret_categories", "quest_types", "quest_roles",
                 "skills")


def _catalog_lines(name: str) -> List[str]:
    if name == "stats":
        return _stat_keys()
    if name == "event_categories":
        from app.core.random_events import CATEGORIES
        return [f"{c} — {_short(CATEGORIES[c].get('description'), 120)}"
                for c in _event_categories()]
    if name == "event_settings":
        from app.core.random_events import default_event_settings
        return ([f"{k} = {json.dumps(v, ensure_ascii=False)}"
                 for k, v in default_event_settings().items()]
                + ["stat_effects = {category: {stat: whole number -100…100}} "
                   "(categories: list_catalog event_categories, stats: list_catalog stats)"])
    if name == "room_types":
        from app.core.furniture_kits import load_room_types
        out = []
        for tid, spec in load_room_types().items():
            roles = list(dict.fromkeys(e.get("role") for e in spec.get("template") or []))
            out.append(f'{tid} "{_label(spec.get("name") or tid, 40)}" roles: '
                       + (", ".join(str(r) for r in roles) or "none"))
        return out
    if name == "furniture_kits":
        from app.core.furniture_kits import catalog
        from app.core.room_furnish import _library
        cat = catalog(library=_library())
        out = []
        for kit in cat.get("kits") or []:
            missing = {t: roles for t, roles in
                       ((cat.get("missing_roles") or {}).get(kit["id"]) or {}).items() if roles}
            head = f'{kit["id"]} "{_label(kit.get("name") or kit["id"], 40)}" · '
            if not missing:
                out.append(head + "complete")
                continue
            # Cut at whole room types, never mid-word: what does not fit is
            # counted, not shown.
            parts = [f"{t}: {', '.join(r)}" for t, r in sorted(missing.items())]
            line = head + f"missing roles in {len(parts)} room type(s): "
            shown = 0
            for part in parts:
                if shown and len(line) + len(part) + 2 > _KIT_LINE_CHARS:
                    break
                line += ("; " if shown else "") + part
                shown += 1
            if shown < len(parts):
                line += f"; … +{len(parts) - shown} more"
            out.append(line)
        return out
    if name == "surface_kinds":
        from app.core.surface_textures import library_kinds
        return sorted(library_kinds())
    if name == "door_props":
        return _door_prop_ids()
    if name == "terrain_kinds":
        from app.core.terrain_types import effective_catalog
        catalog_ = effective_catalog()
        return [_kind_text(k, e, catalog_) for k, e in sorted(catalog_.items())]
    if name == "item_categories":
        return _item_categories()
    if name == "secret_categories":
        from app.models.secrets import SEVERITY_LABELS, VALID_CATEGORIES
        return ([f"category {c}" for c in VALID_CATEGORIES]
                + [f"severity {k} = {v}" for k, v in sorted(SEVERITY_LABELS.items())])
    if name == "quest_types":
        from app.core.quest_catalog import catalog_payload
        out = list(_QUEST_TYPES_HEADER)
        for group in catalog_payload().values():
            for t in group:
                obj_kind = t.get("object_kind") or ""
                makes = ""
                if obj_kind:
                    makes = f", makes {obj_kind}"
                    for param, kind2 in t.get("object_kind_when") or []:
                        makes += f" / {kind2} with {param}"
                params = ", ".join(_quest_param_text(p) for p in t.get("params") or [])
                out.append(f"{t.get('id')} ({t.get('kind')}{makes}) — {t.get('label')}: params "
                           + (params or "(none)"))
        return out
    if name == "quest_roles":
        from app.core.quest_catalog import ROLE_KINDS
        return list(ROLE_KINDS)
    if name == "skills":
        # The capability group (the Skills tab's toggle) a verb belongs to —
        # set_skill takes either id and always switches the whole group.
        from app.plugins.registry import package_of_skill

        def group_of(sid: str) -> str:
            try:
                pkg = package_of_skill(sid)
            except Exception:  # noqa: BLE001 — a listing never fails on it
                return ""
            return str(pkg.id) if pkg is not None and pkg.capability_label else ""

        out = []
        for s in _loaded_skills():
            group = group_of(s.SKILL_ID)
            out.append(f"{s.SKILL_ID} — {_label(getattr(s, 'name', '') or s.SKILL_ID, 60)}"
                       + (f" (group {group})" if group else ""))
        return out
    raise ToolRefusal(f"no catalog {name!r} — catalogs: " + ", ".join(CATALOG_NAMES))


@_tool("list_catalog", False, "list_catalog{name}",
       "value lists: " + ", ".join(CATALOG_NAMES))
def _list_catalog(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"name"}, "list_catalog")
    name = _str(args, "name", required=True)
    lines = _catalog_lines(name)
    if not lines:
        return f"{name}: (none)"
    capped = (_cap_lines(lines, budget=MAX_QUEST_TYPES_CHARS, max_lines=len(lines))
              if name == "quest_types" else _cap_lines(lines))
    return "\n".join(capped)


@_tool("map_region", False, "map_region{min_x, min_z, max_x, max_z, polygons?}",
       "terrain/height areas, places and world props in a box (bboxes; polygons on "
       "request, a polygon too long for the result points to get_area)")
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
            + f" {_fmt_box(box)} z_order {a.get('z_order') or 0}"
            + _area_extras(a), a)
    for h in list_height_areas():
        box = _bbox(h.get("polygon"))
        if not hits(box):
            continue
        label = (h.get("meta") or {}).get("label")
        add(f'height {h["id"]}' + (f' "{_label(label, 40)}"' if label else "")
            + f" {_g(h.get('height_m'))} m falloff {_g(h.get('falloff_m'))} m "
            + _fmt_box(box), h)
    ground = None
    for loc in list_locations():
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            continue
        px, pz = float(loc["pos_x"]), float(loc["pos_z"])
        if x0 <= px <= x1 and z0 <= pz <= z1:
            if ground is None:
                ground = _placement_world()
            lines.append("place " + _loc_line(loc, _place_extras(loc, ground)))
    from app.models.world_props import list_world_props
    for prop in list_world_props():
        if x0 <= prop["x"] <= x1 and z0 <= prop["z"] <= z1:
            lines.append(f'prop {prop["id"]} {prop["prop_id"]} ({_g(prop["x"])},{_g(prop["z"])})'
                         + (f' yaw {_g(prop["yaw_deg"])}' if prop.get("yaw_deg") else ""))
    if not lines:
        return "nothing in this box"
    return "\n".join(_cap_lines(lines, "use a smaller box"))


def _area_extras(area: Dict[str, Any]) -> str:
    """" · scatter <n> · along <n> · slots <n>" of a terrain area — only the
    parts it has (prop scatters, rows of props along its stroke, NPC slots)."""
    meta = area.get("meta") if isinstance(area.get("meta"), dict) else {}
    stroke = meta.get("stroke") if isinstance(meta.get("stroke"), dict) else {}
    out = ""
    for word, value in (("scatter", meta.get("scatter")), ("along", stroke.get("along")),
                        ("slots", meta.get("npc_slots"))):
        if isinstance(value, list) and value:
            out += f" · {word} {len(value)}"
    return out


def _place_extras(loc: Dict[str, Any],
                  ground: Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], str]) -> str:
    """" · outline (x0,z0)-(x1,z1) · on <kind>" of a placed place: the world
    bbox of its stored boundary (none for a place without one — a pin has no
    area) and the terrain kind under its pin."""
    from app.core.terrain_query import kind_at
    from app.core.world_geometry import boundary_world_points
    _catalog, areas, default_kind = ground
    entry = _placement_entry(loc, loc["pos_x"], loc["pos_z"], loc.get("yaw_deg"))
    box = None
    if entry["boundary"] is not None:
        box = _bbox(boundary_world_points({"pos_x": entry["pos_x"], "pos_z": entry["pos_z"],
                                           "yaw_deg": entry["yaw_deg"],
                                           "map3d": {"boundary": entry["boundary"]}}))
    kind = kind_at(entry["pos_x"], entry["pos_z"], areas=areas, default_kind=default_kind)
    return (f" · outline {_corners(box)}" if box else "") + f" · on {kind}"


#: Longest outline text one map_region line carries with polygons; a longer
#: one becomes a get_area pointer, so it cannot use up the list (D11).
MAX_REGION_POLY_CHARS = 400

#: Own budget of one get_area result: the stroke line (the recipe) first,
#: then the outline, each cut on a point boundary beyond it. A paged read
#: (points / offset / limit) has the same budget.
MAX_AREA_CHARS = 12000
#: The point lists of an area get_area can page through.
_AREA_PARTS = ("stroke", "polygon")


def _area_more_call(area_id: str, part: str, offset: int) -> str:
    """The get_area call that reads ``part`` on from ``offset``."""
    return (f'get_area{{"id": {json.dumps(area_id, ensure_ascii=False)}, '
            f'"points": "{part}", "offset": {offset}}}')


def _area_cut_line(area_id: str, cuts: List[Tuple[str, int, int]]) -> str:
    """get_area's closing line for the cut lists: per (part, shown, total)
    '<part>: <shown> of <total> points shown; more: <the call reading on
    from <shown>>', parts joined by "; "."""
    return "[cut — " + "; ".join(
        f"{part}: {shown} of {total} points shown; more: "
        + _area_more_call(area_id, part, shown)
        for part, shown, total in cuts) + "]"


def _area_cut_reserve(area_id: str, parts: List[Tuple[str, int]]) -> int:
    """Room kept for the cut line (and its newline): the line built by the
    same formatter with EVERY present part (part, total) cut at shown =
    offset = total — the most digits a real cut line can have — so the
    answer never exceeds MAX_AREA_CHARS, whatever the id length."""
    return len(_area_cut_line(area_id, [(part, total, total) for part, total in parts])) + 1


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


#: Longest slots / water / relief line of get_area. The scatter and along
#: lines are never cut: the agent resends the entries it keeps from them
#: (both lists replace whole on update), and the sanitizer caps both lists.
_AREA_INFO_LINE_MAX = 300


def _area_info_lines(meta: Dict[str, Any]) -> List[str]:
    """get_area's lines for what a terrain area carries besides its shape:
    'scatter: <n> entries (<prop id> d=<density> s=<spacing> …; …)',
    'along: <n> rows (<prop id> spacing=<m> offset=<m> side=<side>; …)',
    'slots: <roles>', 'water: <key>=<value> …', 'relief: <key>=<value> …' —
    only the parts it has. The entries are spelled out IN FULL because
    scatter / along replace their WHOLE list on update: the agent resends
    the entries it keeps from this line, so a cut line would silently drop
    the entries past the cut. Only the slots / water / relief lines are cut
    at _AREA_INFO_LINE_MAX characters (get_area has its own budget)."""
    from app.core.props import prop_id_from_model_url

    def fmt(value: Any) -> str:
        if isinstance(value, str):
            return value
        if _is_num(value):
            return _g(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def entry(e: Any, keys: Tuple[Tuple[str, str], ...]) -> str:
        # EVERY stored key is printed (the common ones under their short
        # name first, the rest under their own name), because the agent
        # resends the entries it keeps from this line: a key left out here
        # would be lost on the next update of the list.
        if not isinstance(e, dict):
            return "?"
        parts = [prop_id_from_model_url(e.get("model")) or "tuft"]
        known = {key for key, _ in keys}
        for key, short in keys:
            if e.get(key) not in (None, ""):
                parts.append(f"{short}={fmt(e[key])}")
        for key in sorted(k for k in e if k != "model" and k not in known):
            if e[key] not in (None, ""):
                parts.append(f"{key}={fmt(e[key])}")
        return " ".join(parts)

    lines: List[str] = []  # scatter / along: never cut
    cut: List[str] = []    # slots / water / relief: at most _AREA_INFO_LINE_MAX
    scatter = meta.get("scatter")
    if isinstance(scatter, list) and scatter:
        keys = (("density_per_100m2", "d"), ("min_spacing_m", "s"), ("place", "place"),
                ("offset_m", "offset"), ("sides", "sides"), ("yaw_mode", "yaw"),
                ("yaw_deg", "yaw_deg"))
        lines.append(f"scatter: {len(scatter)} entries ("
                     + "; ".join(entry(e, keys) for e in scatter) + ")")
    stroke = meta.get("stroke") if isinstance(meta.get("stroke"), dict) else {}
    along = stroke.get("along")
    if isinstance(along, list) and along:
        keys = (("spacing_m", "spacing"), ("offset_m", "offset"), ("side", "side"))
        lines.append(f"along: {len(along)} rows ("
                     + "; ".join(entry(e, keys) for e in along) + ")")
    slots = meta.get("npc_slots")
    if isinstance(slots, list) and slots:
        cut.append("slots: " + ", ".join(str(s.get("role") or "?") if isinstance(s, dict)
                                            else "?" for s in slots))
    for word, keys in (("water", _WATER_KEYS), ("relief", _RELIEF_KEYS)):
        parts = [f"{k}={meta[k] if isinstance(meta[k], str) else _g(meta[k])}"
                 for k in keys if k in meta]
        if parts:
            cut.append(f"{word}: " + " ".join(parts))
    return lines + [_short(x, _AREA_INFO_LINE_MAX) for x in cut]


@_tool("get_area", False, "get_area{id, points?, offset?, limit?}",
       "one terrain or height area whole: its full polygon, and a stroke "
       "area's centre line and width (own budget of 12000 characters); a list "
       "cut there reads on with points \"stroke\"|\"polygon\" + offset (+ limit) "
       "— the cut line names the exact call")
def _get_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.heightfield import list_height_areas
    from app.models.terrain import get_area
    _only_keys(args, {"id", "points", "offset", "limit"}, "get_area")
    aid = _str(args, "id", required=True)
    part = _str(args, "points")
    if part is None:
        if any(args.get(k) is not None for k in ("offset", "limit")):
            raise ToolRefusal("get_area: 'offset' and 'limit' page through one point "
                              "list — send them with 'points' (\"stroke\" or \"polygon\")")
    elif part not in _AREA_PARTS:
        raise ToolRefusal("get_area: 'points' must be \"stroke\" or \"polygon\"")
    offset = _whole_arg(args, "offset", 0, 1_000_000, 0, "get_area")
    limit = _whole_arg(args, "limit", 1, 1_000_000, 0, "get_area")
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
    stroke = meta.get("stroke")
    spts = (stroke.get("points") or []) if isinstance(stroke, dict) else []
    poly = area.get("polygon") or []
    if part is not None:
        if part == "stroke" and not spts:
            raise ToolRefusal(f"area {area['id']} has no stroke")
        return _area_page(area["id"], out[0], part, spts if part == "stroke" else poly,
                          offset, limit)
    # What the area carries besides its shape (scatter, NPC slots, water,
    # relief) closes the answer; those short lines are reserved first, and
    # so is the longest cut line this area can need.
    extra = _area_info_lines(meta) if out[0].startswith("terrain ") else []
    parts = ([("stroke", len(spts))] if spts else []) + [("polygon", len(poly))]
    left = (MAX_AREA_CHARS - _area_cut_reserve(area["id"], parts) - len(out[0])
            - sum(len(x) + 1 for x in extra))
    # The stroke is the authoritative recipe (a stroke area's polygon is
    # derived from it), so it comes first and is budgeted first; the
    # polygon takes what is left. Both cut on a point boundary only.
    cuts: List[Tuple[str, int, int]] = []
    if spts:
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
        poly_min = len(f"polygon ({len(poly)} points): […]") + 1
        line, shown = _fit_points(f"{prefix} points ", spts, left - 1 - poly_min)
        out.append(line)
        left -= len(line) + 1
        if shown < len(spts):
            cuts.append(("stroke", shown, len(spts)))
    line, shown = _fit_points(f"polygon ({len(poly)} points): ", poly, left - 1)
    out.append(line)
    if shown < len(poly):
        cuts.append(("polygon", shown, len(poly)))
    out.extend(extra)
    if cuts:
        out.append(_area_cut_line(area["id"], cuts))
    return "\n".join(out)


def _area_page(area_id: str, head: str, part: str, pts: List[Any], offset: int,
               limit: int) -> str:
    """A paged get_area answer: the head line, '<part> points <a>…<b> of <n>:
    [<points>]' for the slice from ``offset`` of at most ``limit`` points
    (0 = no limit) that fits MAX_AREA_CHARS — whole points, closed by ",…]"
    when the budget cut it — then, while points follow, the call reading
    on. The extras lines of the full answer are not repeated."""
    total = len(pts)
    if not total:
        raise ToolRefusal(f"area {area_id} has no {part} points")
    if offset >= total:
        raise ToolRefusal(f"offset {offset} is past the last point "
                          f"({total} points: 0…{total - 1})")
    chunk = pts[offset:offset + limit] if limit else pts[offset:]
    # Both the line prefix and the more line are budgeted at their longest
    # (indices with the most digits), so the real ones always fit.
    more_room = len(f"[more — {_area_more_call(area_id, part, total)}]") + 1
    budget = MAX_AREA_CHARS - len(head) - 1 - more_room
    _, shown = _fit_points(f"{part} points {total - 1}…{total - 1} of {total}: ",
                           chunk, budget)
    if not shown:
        raise ToolRefusal(f"point {offset} of the {part} does not fit one get_area answer")
    last = offset + shown - 1
    body = (_fmt_points(chunk) if shown == len(chunk) else
            "[" + ",".join(f"[{_m2(p[0])},{_m2(p[1])}]" for p in chunk[:shown]) + ",…]")
    out = [head, f"{part} points {offset}…{last} of {total}: {body}"]
    if last + 1 < total:
        out.append(f"[more — {_area_more_call(area_id, part, last + 1)}]")
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
       "fields [\"body_slots\"] = its body slots with values and allowed values; "
       "[\"addresses\"] = the forms of address of its pairs, both directions; "
       "[\"secrets\"] = the secrets it keeps; "
       "[\"skills\"] = its skills, on/off and whether set or the default")
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
        addresses: List[str] = []
        secret_block: List[str] = []
        skill_block: List[str] = []
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
            if key == "addresses":
                # Both directions of every pair with a form of address set.
                lines = _address_lines(name)
                addresses = (["forms of address:"] + lines if lines
                             else ["forms of address: none set"])
                continue
            if key == "secrets":
                lines = _secret_lines(name)
                secret_block = (["secrets:"] + lines if lines else ["secrets: none"])
                continue
            if key == "skills":
                lines = _skill_lines(name)
                skill_block = (["skills (id on|off (default|set)):"] + lines if lines
                               else ["skills: none loaded"])
                continue
            if key == "body_slots":
                # The schema of the package-declared slots, not the raw blob:
                # what can be set, to what, and what is set now.
                lines = _body_schema(prof, name)
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
        if ("body_slots" in seen
                or any(k in tfields and str(tfields[k].get("lead") or "").strip()
                       for k in seen)):
            try:
                from app.core import body_slots
                full_sfx = body_slots.appearance_suffix(name, profile=prof).strip()
                face_sfx = body_slots.appearance_suffix(name, face_only=True,
                                                        profile=prof).strip()
                if full_sfx or face_sfx:
                    if full_sfx and face_sfx and face_sfx != full_sfx:
                        shown = f"{full_sfx}; portrait: {face_sfx}"
                    else:
                        shown = full_sfx or f"portrait: {face_sfx}"
                    text += ("\npackages append to the image prompts "
                             f"(do not repeat in the appearance texts): {shown}")
            except Exception as exc:  # noqa: BLE001 — a reader error must never fail get_character
                logger.warning("WorldDev: appearance_suffix for %s failed: %s", name, exc)
        if addresses:
            text += "\n" + "\n".join(_cap_lines(addresses, "too many pairs"))
        if secret_block:
            text += "\n" + "\n".join(_cap_lines(secret_block, "too many secrets"))
        if skill_block:
            text += "\n" + "\n".join(_cap_lines(skill_block, "too many skills"))
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
    ]
    linked = _linked_line(name)
    if linked:
        out.append(linked)
    out += [
        "profile fields: " + (", ".join(prof_keys) or "(none)"),
        "config fields: " + (", ".join(nonempty(cfg)) or "(none)"),
    ]
    from app.core.world_dev_apply import _template_has_wardrobe
    if _template_has_wardrobe(str(prof.get("template") or "human-default")):
        names = [str(o.get("name") or "") for o in get_character_outfits(name)]
        out.append("outfits: " + (", ".join(n for n in names if n) or "(none)"))
    else:
        out.append("outfits: (template without outfit system)")
    from app.models.secrets import list_secrets
    n_secrets = len(list_secrets(name))
    if n_secrets:
        out.append(f"secrets: {n_secrets}" + ' — get_character{"fields": ["secrets"]} lists them')
    if _body_specs(prof, name):
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
    """Characters naming loc_id as home, known place or schedule slot,
    secrets whose ``related_location`` is loc_id (``secret <id> of <owner>``),
    world rules whose target place is loc_id (``rule <id> "<name>"``) and
    active events at loc_id (``event <id>``)."""
    from app.models import rules as rules_mod, secrets as secrets_mod
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
    out += _secret_refs(_naming_refs(secrets_mod.secrets_naming, "secrets", location=loc_id))
    out += _rule_refs(_naming_refs(rules_mod.rules_naming, "world rules", location=loc_id))
    out += _event_refs(loc_id)
    return out


# ── Placement checks (E9) ────────────────────────────────────────────────

def _placement_entry(loc_like: Dict[str, Any], x: Any, z: Any, yaw: Any) -> Dict[str, Any]:
    """The placement-check entry of a place standing at (x, z, yaw): its name
    and its outline in local metres — ``map3d.boundary`` of a location body or
    row, else None: a place without a stored outline has no area on the map
    (world_geometry.effective_boundary), so every check judges it by its pin
    only. create_location stores the seed square itself when no boundary is
    given, so a run-made place always has one."""
    m3 = loc_like.get("map3d") if isinstance(loc_like.get("map3d"), dict) else {}
    return {"name": str(loc_like.get("name") or loc_like.get("id") or ""),
            "pos_x": float(x), "pos_z": float(z), "yaw_deg": float(yaw or 0.0),
            "boundary": m3.get("boundary") or None}


def _placement_world() -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], str]:
    """(terrain catalog, the world's terrain areas bottom-to-top, default
    kind) — the ground the placement checks read (only the ground: no
    location outlines, no world bounds)."""
    from app.core.terrain_types import effective_catalog
    from app.core.world_dev_apply import default_terrain_kind
    from app.models.terrain import list_areas
    # list_areas is z_order-then-paint order already; the stable sort keeps
    # the paint order inside one z_order, as the map judges it.
    return (effective_catalog(),
            sorted(list_areas(), key=lambda a: a.get("z_order") or 0),
            default_terrain_kind())


def _check_placement(entry: Dict[str, Any], exclude_id: str = "",
                     pin_kept: bool = False) -> List[str]:
    """Refuse a pin on impassable ground; return the overlap warning texts
    against every other placed place (not ``exclude_id``). Read only.

    ``pin_kept``: the pin stays where it already stands (a turn in place, a
    new outline) — its ground is not this call's doing (the area write that
    put it there already warned), so it is not judged and never refuses.

    The overlap text names the other place by its id as well: two places may
    share a name, and ``place_location`` needs the id to move one of them."""
    from app.core.map_layout_apply import placement_warnings
    from app.models.world import list_locations
    catalog, areas, default_kind = _placement_world()
    others = [dict(_placement_entry(l, l["pos_x"], l["pos_z"], l.get("yaw_deg")),
                   id=str(l.get("id") or ""))
              for l in list_locations()
              if str(l.get("id") or "") != exclude_id
              and l.get("pos_x") is not None and l.get("pos_z") is not None]
    texts: List[str] = []
    for w in placement_warnings([entry], catalog=catalog, areas=areas,
                                default_kind=default_kind, others=others):
        if w.get("code") == "on_impassable":
            if pin_kept:
                continue
            raise ToolRefusal(str(w.get("message") or "the place stands on impassable ground")
                              + " Pick a spot on walkable ground.")
        other_id = w.get("other_id")
        if w.get("code") == "footprint_overlap" and other_id:
            texts.append(f'\'{entry["name"]}\' overlaps place {other_id} '
                         f'"{w.get("other_name") or ""}" — their outlines share ground.')
            continue
        texts.append(str(w.get("message") or ""))
    return texts


#: (min x, min z, max x, max z) in world metres
_Box = Tuple[float, float, float, float]


def _union_box(*polygons: Any) -> Optional[_Box]:
    """The bbox around every given polygon (None ones skipped); None when
    none has a point."""
    boxes = [b for b in (_bbox(p) for p in polygons if p) if b is not None]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _pin_grounds(box: Optional[_Box]) -> Dict[str, Tuple[str, str]]:
    """{location id: (name, terrain kind under its pin)} of every placed
    place whose pin lies in ``box`` — an area write changes the ground only
    inside its old and new outline, so the pins outside are never tested.
    ``box`` None (no outline known) gives an empty map."""
    from app.core.terrain_query import kind_at
    from app.models.world import list_locations
    if box is None:
        return {}
    min_x, min_z, max_x, max_z = box
    pins = [loc for loc in list_locations()
            if loc.get("pos_x") is not None and loc.get("pos_z") is not None
            and min_x <= float(loc["pos_x"]) <= max_x
            and min_z <= float(loc["pos_z"]) <= max_z]
    if not pins:
        return {}
    _catalog, areas, default_kind = _placement_world()
    return {str(loc.get("id")): (str(loc.get("name") or ""),
                                 kind_at(float(loc["pos_x"]), float(loc["pos_z"]),
                                         areas=areas, default_kind=default_kind))
            for loc in pins}


def _outline_overlaps(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """After update_location: the overlap warnings of a placed place whose
    drawn outline changed (the pin stays, so its ground is not judged). A
    read after the write — a failure costs the warning, never the step."""
    old = (before.get("map3d") or {}).get("boundary") if isinstance(before.get("map3d"), dict) else None
    new = (after.get("map3d") or {}).get("boundary") if isinstance(after.get("map3d"), dict) else None
    if old == new or after.get("pos_x") is None or after.get("pos_z") is None:
        return []
    try:
        return _check_placement(
            _placement_entry(after, after["pos_x"], after["pos_z"], after.get("yaw_deg")),
            exclude_id=str(after.get("id") or ""), pin_kept=True)
    except Exception:  # noqa: BLE001 — a hint, the write is already journalled
        logger.exception("world-dev: overlap check after an outline change failed")
        return []


def _pin_grounds_before(box: Optional[_Box]) -> Optional[Dict[str, Tuple[str, str]]]:
    """:func:`_pin_grounds` before an area write, or None when the read
    fails — a hint only: the write goes ahead without its ground warnings.
    ``box`` covers the area's outline before AND after the write."""
    try:
        return _pin_grounds(box)
    except Exception:  # noqa: BLE001 — a hint, never a reason to refuse the write
        logger.exception("world-dev: pin ground check before an area write failed")
        return None


def _ground_warnings(before: Optional[Dict[str, Tuple[str, str]]],
                     box: Optional[_Box]) -> List[str]:
    """After an area write: the pins it put on impassable ground. A read
    after the write — a failure here costs the warning, never the step.
    ``before`` None (the read before the write failed) gives no warnings;
    ``box`` is the one the before read used."""
    if before is None:
        return []
    try:
        return _newly_impassable(before, _pin_grounds(box))
    except Exception:  # noqa: BLE001 — a hint, the write is already journalled
        logger.exception("world-dev: pin ground check after an area write failed")
        return []


def _newly_impassable(before: Dict[str, Tuple[str, str]],
                      after: Dict[str, Tuple[str, str]]) -> List[str]:
    """One warning per placed pin whose ground changed to an impassable kind."""
    from app.core.terrain_types import effective_catalog
    if not after:
        return []
    catalog = effective_catalog()
    out: List[str] = []
    for lid, (name, kind) in after.items():
        if kind == (before.get(lid) or ("", ""))[1]:
            continue
        if bool((catalog.get(kind) or {}).get("passable", True)):
            continue
        out.append(f'place {lid} "{name}" now stands on {kind}, which nobody can walk on')
    return out


@_tool("create_location", True,
       "create_location{data, x?, z?, yaw?, boundary?:[[x,z],...]}",
       "new place (the place fields the core writers take, plus rooms); boundary in local metres")
def _create_location(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.map_layout_apply import SEED_BOUNDARY_M, seed_boundary
    from app.core.world_ops import create_location_with_extras
    from app.models.world import (get_location_by_id, list_locations,
                                  update_location_position, world_write_lock)
    _only_keys(args, {"data", "x", "z", "yaw", "boundary"}, "create_location")
    data = args.get("data")
    if not isinstance(data, dict):
        raise ToolRefusal("'data' must be an object with the location fields")
    data = _drop_none(data)
    _m3 = data.get("map3d") if isinstance(data.get("map3d"), dict) else {}
    data = _drop_derived_plan_width(data, _derived_plan_width(
        ("boundary", args.get("boundary")), ("map3d.boundary", _m3.get("boundary")))
        or (SEED_BOUNDARY_M if args.get("boundary") is None and not _m3.get("boundary")
            else 0.0))
    _check_location_fields(data, "location", creating=True)
    if "npc_slots" in data:
        _check_npc_slots(data["npc_slots"], None)
    name = _str(data, "name", required=True)
    for i, room in enumerate(data.get("rooms") or []):
        if not _str(room, "name"):
            raise ToolRefusal(f"rooms[{i}] needs a non-empty 'name'")
    x, z, yaw = _coord(args, "x"), _coord(args, "z"), _num(args, "yaw")
    if (x is None) != (z is None):
        raise ToolRefusal("give both x and z, or neither")
    if yaw is not None and x is None:
        raise ToolRefusal("yaw needs x and z")
    boundary = (_ring(args["boundary"], "boundary")
                if args.get("boundary") is not None else None)
    body = copy.deepcopy(data)
    body["name"] = name
    body["rooms"] = body.get("rooms") or []
    _normalize_rooms(body["rooms"])
    seeded = False
    if boundary is not None:
        body["map3d"] = {**(body.get("map3d") or {}), "boundary": boundary}
    elif not (body.get("map3d") if isinstance(body.get("map3d"), dict) else {}).get("boundary"):
        # No outline given: the seed square the manual promises is STORED, so
        # the checks below, the map and the renderers all see the same area
        # (a place without a stored boundary has none). The delete_location
        # inverse removes it with the row.
        body["map3d"] = {**(body.get("map3d") or {}), "boundary": seed_boundary(),
                         "plan_width_m": SEED_BOUNDARY_M}
        seeded = True
    if body.get("map3d") is not None:
        _refuse_map3d_dropped(body["map3d"], body["map3d"])
    # The rooms get their ids from the writer: the entry room is resolved
    # against the body's rooms now and stored by id after the write.
    entry_id, entry_name = "", None
    if "entry_room" in body:
        entry_id, entry_name = _resolve_entry_room(
            body.pop("entry_room"), _entry_room_choices(body["rooms"], body.get("map3d")))
    # The create writer does not store chattiness: the update writer writes
    # it in the same step (covered by the delete_location inverse).
    chattiness = body.pop("chattiness", "")
    # Names are not keys: a name the world already has is a second place.
    body["create_new"] = True
    placement = (_check_placement(_placement_entry(body, x, z, yaw))
                 if x is not None else [])
    if x is not None:
        placement += _bounds_warnings(_place_points(body, x, z, yaw), f'place "{name}"',
                                      step.ctx.run_id)

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
            if chattiness != "":
                from app.core.world_ops import update_location_with_extras
                update_location_with_extras(lid, {"chattiness": chattiness})
            _verify_extras(lid, data)
            _verify_room_extras(lid, body["rooms"], set())
        after = get_location_by_id(lid) or {}
        line = f'created location {lid} "{after.get("name") or name}" at {_where(after)}'
        if seeded:
            line += f" · outline: {SEED_BOUNDARY_M:g} m square (no boundary given)"
        line += _warn_suffix(([f'a place called "{name}" already exists — '
                               f"this is a second one"] if taken else []) + placement)
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
    patch = _drop_map3d_echo(lid, patch)
    _check_location_fields(patch, "patch")
    if "name" in patch and not str(patch["name"] or "").strip():
        raise ToolRefusal("'name' must not be empty")
    body = copy.deepcopy(patch)

    # Cheap pre-checks before the backup (a mistyped id or slot on the run's
    # first write must not copy the world); the read under the lock decides.
    pre = get_location_by_id(lid)
    if pre is None:
        raise ToolRefusal(f"no location {lid!r} — use find_locations")
    if "npc_slots" in body:
        pre_rooms = [r for r in pre.get("rooms") or [] if isinstance(r, dict)]
        if body.get("rooms") is not None:
            # Sent rooms with a stored id stay; new rooms have no id yet. A
            # kept room may be sent as {id} alone, so its NAME (for the
            # refusal's list) is the stored one.
            stored_ids = {str(r.get("id") or "") for r in pre_rooms}
            sent_ids = {str(r.get("id") or "") for r in body["rooms"] if isinstance(r, dict)}
            for rid in sorted(sent_ids - stored_ids - {""}):
                # Same wording as the check under the lock: a mistyped room
                # id is named as such, not as a slot room outside the place.
                raise ToolRefusal(f"room id {rid!r} does not exist in {lid} — "
                                  f"omit the id for a new room")
            pre_rooms = [r for r in pre_rooms if str(r.get("id") or "") in sent_ids]
        _check_npc_slots(body["npc_slots"], _slot_room_ids(pre_rooms))
    step.prepare()
    with world_write_lock:
        cur = get_location_by_id(lid)
        if cur is None:
            raise ToolRefusal(f"no location {lid!r} — use find_locations")
        stored_rooms = [r for r in cur.get("rooms") or [] if isinstance(r, dict)]
        sent_rooms: Optional[List[Dict[str, Any]]] = None
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
            sent_rooms = copy.deepcopy(body["rooms"])
            body["rooms"] = _merge_rooms(stored_rooms, body["rooms"])
        if "event_settings" in body:
            # A patch changes the event_settings keys it names; the writer
            # stores the object whole, so the stored keys are laid under it
            # (the sent part was checked by _check_location_fields).
            body["event_settings"] = {**(cur.get("event_settings") or {}),
                                      **body["event_settings"]}
        if "npc_slots" in body:
            _check_npc_slots(body["npc_slots"], _slot_room_ids(
                body["rooms"] if body.get("rooms") is not None else stored_rooms))
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
            # A slot's room must stay a stored room of the place (the spawn
            # would put the NPC into a room that no longer exists).
            removed_ids = {str(r.get("id") or ""): r for r in removed}
            slots = (body["npc_slots"] if "npc_slots" in body
                     else cur.get("npc_slots") or [])
            for slot in slots:
                rid = str(slot.get("room") or "") if isinstance(slot, dict) else ""
                if rid and rid in removed_ids:
                    raise ToolRefusal(
                        f'the patch removes room "{removed_ids[rid].get("name") or rid}" '
                        f"({rid}) that NPC slot '{slot.get('role')}' uses — send npc_slots "
                        f'too (with another room, or room "")')
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
            _verify_extras(lid, body)
            if sent_rooms is not None:
                _verify_room_extras(lid, sent_rooms, old_ids)
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
                + _warn_suffix(_outline_overlaps(before, after))
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
    stored = get_location_by_id(lid)
    if stored is None:  # pre-check before the backup
        raise ToolRefusal(f"no location {lid!r} — use find_locations")
    # A pin that keeps its spot (a turn in place) is not refused for the
    # ground it already stands on.
    kept = (stored.get("pos_x") is not None and stored.get("pos_z") is not None
            and float(stored["pos_x"]) == x and float(stored["pos_z"]) == z)
    placement = _check_placement(
        _placement_entry(stored, x, z, yaw if yaw is not None else stored.get("yaw_deg")),
        exclude_id=lid, pin_kept=kept)
    placement += _bounds_warnings(
        _place_points(stored, x, z, yaw if yaw is not None else stored.get("yaw_deg")),
        f'place "{stored.get("name") or lid}"', step.ctx.run_id)
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
                + _warn_suffix(placement)
                + completeness.location_suffix(step.ctx.run_id, after))
        step.complete(wu.position_of(after), line)
    return line



# ── Floor plans ──────────────────────────────────────────────────────────

#: The layout_apply.sanitize_layout codes that stay WARNINGS (E2): authoring
#: states of a plan in progress that drop nothing. Every other code refuses —
#: also a code added to the sanitizer later (never silently a warning).
_LAYOUT_KEPT_CODES = frozenset({"unknown_opening_target", "room_outside_boundary",
                                "room_overlap", "no_boundary"})
#: The keys of a set_room_layout `layout` (the json:layout object; `hull`
#: is refused, E4).
_LAYOUT_KEYS = ("rooms", "entry_room", "boundary_openings", "stairs",
                "storey_height_m", "summary")


#: Room keys of a layout entry that are no part of the room's stored
#: layout (identity, text, the open/closed flag trio, the furnishing type);
#: every OTHER sent key is compared with what the sanitizer keeps.
_LAYOUT_ROOM_META = ("id", "name", "description", "open", "room_type")
#: Room-layout keys other editors own (furnishing, figure snap spots, the
#: room model's anchor): a plan refuses them, and a named existing room
#: keeps its stored ones (_carry_room_content) — moving a door never takes
#: the furniture away.
_LAYOUT_ROOM_CONTENT = ("props", "markers", "model_at", "model_offset_y")
#: The plan writers round metres to the centimetre and an opening's "at" to
#: 1e-4; a sent number within this of the stored one is that rounding, any
#: larger difference is a clamp and refuses.
_LAYOUT_TOL = 0.006
#: The opening types a room wall takes (world_ops._sanitize_opening).
_OPENING_TYPES = ("door", "window", "passage")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _layout_level(layout: Any) -> Optional[int]:
    if not isinstance(layout, dict) or not layout:
        return None
    try:
        return int(layout.get("level") or 0)
    except (TypeError, ValueError):
        return 0


def _layout_rewrites(layout: Dict[str, Any], normalized: Dict[str, Any],
                     loc: Dict[str, Any]) -> None:
    """Refuse every sent value the sanitizer would clamp, drop or rewrite —
    room geometry and openings, plot openings, stair flights — and resolve
    a plot opening's "room" (an id, or the name of a room of the place or
    of this plan; anything else refuses). Runs after the drop check, so the
    sent rooms and the normalized entries correspond one to one."""
    for i, (raw, entry) in enumerate(zip(layout.get("rooms") or [],
                                         normalized.get("rooms") or [])):
        where = f"rooms[{i}]"
        if str(raw.get("id") or "").strip() and str(raw.get("name") or "").strip():
            raise ToolRefusal(f"'{where}' gives both 'id' and 'name' — an existing "
                              f"room by its id, a new one by its name")
        if entry.get("is_new"):
            _check_name_length(str(raw.get("name") or "").strip(), f"'{where}.name'")
        if not entry.get("is_new") and "description" in raw:
            raise ToolRefusal(f"'{where}.description' is not written by a floor plan "
                              f"for an existing room — use update_location for its text")
        for j, op in enumerate(raw.get("openings") or []):
            if isinstance(op, dict) and "type" in op and op["type"] not in _OPENING_TYPES:
                raise ToolRefusal(f"'{where}.openings[{j}].type' must be one of: "
                                  + ", ".join(_OPENING_TYPES))
        if "outline" in raw and "outline" not in entry["layout"]:
            raise ToolRefusal(f"'{where}.outline' is unusable — 3…32 [x, y] points in "
                              f"metres from the room's minimum corner, enclosing an "
                              f"area; fix it or leave it out")
        geometry = {k: v for k, v in raw.items() if k not in _LAYOUT_ROOM_META}
        _refuse_rewritten(where, geometry, entry["layout"], _LAYOUT_TOL)
    if isinstance(layout.get("boundary_openings"), list):
        stored = normalized.get("boundary_openings") or []
        _refuse_rewritten("boundary_openings", layout["boundary_openings"], stored,
                          _LAYOUT_TOL)
        ids = {str(r.get("id")) for r in loc.get("rooms") or []
               if isinstance(r, dict) and r.get("id")}
        ids |= {e["room_id"] for e in normalized.get("rooms") or []}
        by_name = {str(r.get("name") or "").strip().lower(): str(r.get("id"))
                   for r in loc.get("rooms") or [] if isinstance(r, dict) and r.get("id")}
        by_name.update({str(e.get("name") or "").strip().lower(): e["room_id"]
                        for e in normalized.get("rooms") or []})
        for i, op in enumerate(stored):
            ref = op.get("room")
            if not ref or ref in ids:
                continue
            if ref.lower() in by_name:
                op["room"] = by_name[ref.lower()]
                continue
            raise ToolRefusal(f"'boundary_openings[{i}].room' {ref!r} is no room of this "
                              f"place — an id, or the name of a room this plan creates")
    if isinstance(layout.get("stairs"), list):
        _refuse_rewritten("stairs", layout["stairs"], normalized.get("stairs") or [],
                          _LAYOUT_TOL)


def _layout_reach_warnings(normalized: Dict[str, Any],
                           loc: Dict[str, Any]) -> List[str]:
    """Warnings on the plan as it will be stored (sent rooms plus the stored
    layouts of the rooms it omits): a sent room sharing floor with an
    omitted one, a flight from or onto a storey without rooms, a storey other
    than 0 that no flight reaches. Nothing is dropped for any of them."""
    from app.core.layout_apply import rooms_overlap
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    entries = normalized.get("rooms") or []
    named = {e["room_id"] for e in entries}
    omitted = [r for r in loc.get("rooms") or []
               if isinstance(r, dict) and str(r.get("id") or "") not in named
               and r.get("id") != GROUND_ROOM_ID and not is_floor_room(str(r.get("id")))
               and _layout_level(r.get("layout")) is not None]
    out: List[str] = []
    for e in entries:
        lvl = _layout_level(e["layout"])
        for r in omitted:
            if _layout_level(r["layout"]) == lvl and rooms_overlap(e["layout"], r["layout"]):
                out.append(f"'{e['name']}' shares floor on level {lvl} with "
                           f"'{r.get('name') or r.get('id')}', which this plan does not name")
    levels = {_layout_level(e["layout"]) for e in entries}
    levels |= {_layout_level(r["layout"]) for r in omitted}
    m3 = loc.get("map3d") if isinstance(loc.get("map3d"), dict) else {}
    stairs = normalized.get("stairs")
    if stairs is None:
        stairs = m3.get("stairs") or []
    starts = []
    for st in stairs:
        try:
            starts.append(int(st.get("from_level")))
        except (TypeError, ValueError, AttributeError):
            continue
    present = levels | {0}
    for lvl in starts:
        empty = [x for x in (lvl, lvl + 1) if x not in present]
        if empty:
            out.append(f"a stair flight from level {lvl} to level {lvl + 1}, but level "
                       f"{empty[0]} has no room")
    if not m3.get("elevator"):
        for lvl in sorted(x for x in levels if x):
            # A flight leads from its storey to the one above: a level above
            # 0 is reached from below, a cellar from the flight on itself.
            if (lvl - 1 if lvl > 0 else lvl) not in starts:
                out.append(f"level {lvl} has rooms but no stair flight reaches it")
    return out


def _layout_shapes(layout: Dict[str, Any]) -> None:
    """Refuse up front the value shapes the sanitizer would silently ignore
    or crash on: a non-list boundary_openings / stairs (one object instead of
    a list of one), a non-list room openings or a non-object opening, an
    'open' that is no boolean, and the room keys other editors own."""
    for key in ("boundary_openings", "stairs"):
        if key in layout and not isinstance(layout[key], list):
            raise ToolRefusal(f"'{key}' must be a list (one object goes in a list "
                              f"of one); leave it out to keep what is stored")
    rooms = layout.get("rooms")
    for i, raw in enumerate(rooms if isinstance(rooms, list) else []):
        if not isinstance(raw, dict):
            continue
        where = f"rooms[{i}]"
        for key in _LAYOUT_ROOM_CONTENT:
            if key in raw:
                raise ToolRefusal(f"'{where}.{key}' is not written by a floor plan — "
                                  f"a named room keeps its stored {key}; leave it out")
        if "openings" in raw:
            ops = raw["openings"]
            if not isinstance(ops, list):
                raise ToolRefusal(f"'{where}.openings' must be a list of opening objects")
            for j, op in enumerate(ops):
                if not isinstance(op, dict):
                    raise ToolRefusal(f"'{where}.openings[{j}]' must be an object "
                                      f"(edge, at, width_m, …)")
        if "open" in raw and not isinstance(raw["open"], bool):
            raise ToolRefusal(f"'{where}.open' must be true or false")


def _carry_room_content(normalized: Dict[str, Any], loc: Dict[str, Any]) -> None:
    """A named existing room keeps the layout keys other editors own
    (_LAYOUT_ROOM_CONTENT): its plan entry replaces the geometry only."""
    stored = {str(r.get("id")): r.get("layout") for r in loc.get("rooms") or []
              if isinstance(r, dict) and r.get("id")}
    for entry in normalized.get("rooms") or []:
        if entry.get("is_new"):
            continue
        old = stored.get(entry["room_id"])
        if not isinstance(old, dict):
            continue
        for key in _LAYOUT_ROOM_CONTENT:
            if key in old:
                entry["layout"][key] = copy.deepcopy(old[key])


def _layout_pass(layout: Dict[str, Any], loc: Dict[str, Any],
                 kinds: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """One sanitize_layout pass against loc: (normalized, kept warning
    texts). A finding outside _LAYOUT_KEPT_CODES refuses with every such
    message; any sent value the sanitizer would rewrite refuses too
    (_layout_rewrites; a storey_height_m outside the sanitizer's range
    included)."""
    from app.core.layout_apply import sanitize_layout
    _layout_shapes(layout)
    if "storey_height_m" in layout:
        height = layout["storey_height_m"]
        if not _is_num(height) or isinstance(height, bool) or not math.isfinite(height):
            raise ToolRefusal("'storey_height_m' must be a number 2.6…4.5 (metres)")
    normalized, warnings = sanitize_layout(copy.deepcopy(layout), location=loc,
                                           surface_kinds=kinds)
    dropped = [w for w in warnings if w.get("code") not in _LAYOUT_KEPT_CODES]
    if dropped:
        text = "; ".join(f"{w.get('ref') or '?'}: {w.get('message') or w.get('code')}"
                         for w in dropped)
        if any(w.get("code") == "room_type_dropped" for w in dropped):
            text += " — see list_catalog room_types"
        raise ToolRefusal("the floor plan would lose parts, nothing was written: " + text)
    if "storey_height_m" in layout:
        _refuse_rewritten("storey_height_m", layout["storey_height_m"],
                          normalized.get("storey_height_m", _ABSENT), _LAYOUT_TOL)
    _layout_rewrites(layout, normalized, loc)
    _carry_room_content(normalized, loc)
    kept = [str(w.get("message") or w.get("code")) for w in warnings]
    return normalized, kept + _layout_reach_warnings(normalized, loc)


@_tool("set_room_layout", True, "set_room_layout{location_id, layout}",
       "floor plan of a place: rooms (x, y, w, d, level, openings), entry_room, "
       "boundary_openings, stairs, storey_height_m — read_manual layout first")
def _set_room_layout(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.layout_apply import apply_layout, layout_context, layout_counts
    from app.core.world_ops import update_location_with_extras
    from app.models.world import get_location_by_id, world_write_lock
    _only_keys(args, {"location_id", "layout"}, "set_room_layout")
    lid = _str(args, "location_id", required=True)
    layout = args.get("layout")
    if not isinstance(layout, dict) or not layout:
        raise ToolRefusal("'layout' must be an object with 'rooms' (read_manual layout)")
    if "hull" in layout:
        raise ToolRefusal("'hull' is not built here — the building panel's button "
                          "generates the hull; leave it out")
    _only_keys(layout, _LAYOUT_KEYS, "layout")

    def context() -> Tuple[Dict[str, Any], List[str]]:
        try:
            return layout_context(lid)
        except ValueError:
            raise ToolRefusal(f"no location {lid!r} — use find_locations")

    # Cheap checks before the backup: a refused first write copies nothing.
    _layout_pass(layout, *context())
    step.prepare()
    with world_write_lock:
        # The ids a plan mints for new rooms are per pass, so the write uses
        # the pass taken under the lock; a room deleted meanwhile refuses.
        cur, kinds = context()
        normalized, kept = _layout_pass(layout, cur, kinds)
        before = copy.deepcopy(cur)
        step.begin("location", lid, {"op": "restore_location", "id": lid,
                                     "before": before})

        def reconcile():
            b, w = wu.diff_keys(before, get_location_by_id(lid))
            if not b:
                return None
            return lid, {"op": "restore_location", "id": lid, "before": b}, w

        with step.writing(reconcile):
            apply_layout(normalized)
            if "storey_height_m" in layout:
                # apply_layout writes the storey height only with a derived
                # contour; a sent one is written here, in the same step.
                m3 = dict((get_location_by_id(lid) or {}).get("map3d") or {})
                m3["storey_height_m"] = normalized["storey_height_m"]
                update_location_with_extras(lid, {"map3d": m3})
                got = ((get_location_by_id(lid) or {}).get("map3d") or {}).get(
                    "storey_height_m")
                if got != normalized["storey_height_m"]:
                    raise RuntimeError(f"storey_height_m {normalized['storey_height_m']} "
                                       f"was not stored (got {got!r})")
        after = get_location_by_id(lid) or {}
        b, w = wu.diff_keys(before, after)
        step.attach(lid, {"op": "restore_location", "id": lid, "before": b},
                    before=b)
        counts = layout_counts(normalized)
        stairs = len((after.get("map3d") or {}).get("stairs") or [])
        line = (f'updated layout of location {lid} "{after.get("name") or ""}": '
                f'{_plural(counts["rooms"], "room")} ({counts["new_rooms"]} new) '
                f'with {_plural(counts["openings"], "opening")}; the place has '
                f'{_plural(stairs, "stair flight")}'
                + ("" if b else " — no change")
                + _warn_suffix(kept)
                + completeness.location_suffix(step.ctx.run_id, after))
        step.complete(w, line)
    return line

# ── Kit furnishing ───────────────────────────────────────────────────────

#: furnish_kit_building skip reasons -> what the agent reads (and does next).
_FURNISH_REASONS = {
    "no_room_type": "no room_type — set room_type with update_location "
                    "(list_catalog room_types)",
    "no_layout": "no floor plan — set_room_layout first",
    "has_furniture": "already furnished",
    "job_open": "a furnishing job is open in the editor",
    "nothing_placed": "the kit placed nothing (room too small or no fitting pieces)",
}


def _furnish_skipped(skipped: List[Dict[str, Any]],
                     loc: Optional[Dict[str, Any]]) -> List[str]:
    """The skip lines in the place's room order (rooms refused during the
    locked write are appended after the up-front skips by the writer)."""
    order = {str(r.get("id") or ""): i
             for i, r in enumerate((loc or {}).get("rooms") or []) if isinstance(r, dict)}
    ordered = sorted(skipped, key=lambda s: order.get(str(s.get("room_id") or ""),
                                                      len(order)))
    return [f"{s.get('name') or s.get('room_id')}: "
            + _FURNISH_REASONS.get(str(s.get("reason")), str(s.get("reason")))
            for s in ordered]


@_tool("furnish_rooms", True, "furnish_rooms{location_id, kit}",
       "furnish the empty rooms of a place from a furniture kit (whole kits of library "
       "props; rooms need room_type and a floor plan — use place_room_prop for a single "
       "prop) — read_manual layout first")
def _furnish_rooms(step: _Step, args: Dict[str, Any]) -> str:
    from app.core import furniture_kits
    from app.core.furnish_kit_building import furnish_location
    from app.core.keyed_lock import keyed_lock
    from app.core.room_furnish import FurnishError
    from app.models.world import get_location_by_id, world_write_lock
    _only_keys(args, {"location_id", "kit"}, "furnish_rooms")
    lid = _str(args, "location_id", required=True)
    kit = _str(args, "kit", required=True)
    kits = list(furniture_kits.load_kits())
    if kit not in kits:
        raise ToolRefusal(f"unknown kit {kit!r} — one of: " + ", ".join(kits)
                          + " (list_catalog furniture_kits)")
    if get_location_by_id(lid) is None:
        raise ToolRefusal(f"no location {lid!r} — use find_locations")
    # The dry run is the same solver path as the write: a place where no
    # room would be furnished refuses before the backup, naming every room.
    try:
        preview = furnish_location(lid, kit, dry_run=True)
    except FurnishError as exc:
        if exc.status >= 500:
            raise
        raise ToolRefusal(exc.message)
    if not preview.get("rooms"):
        reasons = _furnish_skipped(preview.get("skipped") or [],
                                   get_location_by_id(lid))
        raise ToolRefusal(f"nothing to furnish in location {lid}: "
                          + ("; ".join(reasons) if reasons else "it has no rooms"))
    step.prepare()
    # The order furnish_location takes itself: furnish_kit, then the world
    # write lock (both re-entrant), so the snapshot and the write are one span.
    with keyed_lock("furnish_kit", lid), world_write_lock:
        cur = get_location_by_id(lid)
        if cur is None:
            raise ToolRefusal(f"no location {lid!r} — use find_locations")
        before = copy.deepcopy(cur)
        step.begin("location", lid, {"op": "restore_location", "id": lid,
                                     "before": before})

        def reconcile():
            b, w = wu.diff_keys(before, get_location_by_id(lid))
            if not b:
                return None
            return lid, {"op": "restore_location", "id": lid, "before": b}, w

        with step.writing(reconcile):
            result = furnish_location(lid, kit, dry_run=False)
        after = get_location_by_id(lid) or {}
        b, w = wu.diff_keys(before, after)
        skipped = _furnish_skipped(result.get("skipped") or [], before)
        if not b:
            # A foreign write between the dry run and this locked span left
            # nothing to furnish: the agent reads a refusal, not a success.
            msg = (f"nothing furnished in location {lid}"
                   + (f": {'; '.join(skipped)}" if skipped else ""))
            step.complete(None, f"error: {msg}", kind="refused")
            raise ToolRefusal(msg)
        step.attach(lid, {"op": "restore_location", "id": lid, "before": b},
                    before=b)
        # Piece counts come from what storage holds, not the solver's
        # report (the sanitizer may drop a placement).
        stored = {str(r.get("id")): len(((r.get("layout") or {}).get("props")) or [])
                  for r in after.get("rooms") or [] if isinstance(r, dict)}
        rooms = result.get("rooms") or []
        done = ", ".join(f"{r.get('name') or r.get('room_id')} "
                         f"({_plural(stored.get(str(r.get('room_id')), 0), 'piece')}"
                         + (f", {r['unplaced']} did not fit" if r.get("unplaced") else "")
                         + ")" for r in rooms)
        missing = "; ".join(f"{r.get('name') or r.get('room_id')}: "
                            + ", ".join(str(m) for m in r["missing_roles"])
                            for r in rooms if r.get("missing_roles"))
        line = (f'furnished {_plural(len(rooms), "room")} with kit {kit} in location '
                f'{lid} "{after.get("name") or ""}"'
                + (f": {done}" if done else "")
                + (f"; missing roles: {missing}" if missing else "")
                + (f"; skipped: {'; '.join(skipped)}" if skipped else ""))
        line = _cut(line)
        step.complete(w, line)
    return line


#: Maximum manual prop placements stored per room (world_ops._sanitize_props).
_MAX_ROOM_PROPS = 100


def _room_for_prop(loc: Dict[str, Any], room_arg: str) -> Dict[str, Any]:
    """Resolve a regular room of ``loc`` by id or exact name; refuse ground/corridor
    rooms and missing rooms with a hint."""
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    lid = str(loc.get("id") or "")
    if room_arg == GROUND_ROOM_ID or is_floor_room(room_arg):
        raise ToolRefusal(
            f"room {room_arg!r} is the ground or a storey corridor — place_room_prop "
            "places props in a regular room with a floor plan (use place_world_prop "
            "for open ground)")
    regular = [r for r in (loc.get("rooms") or [])
               if isinstance(r, dict)
               and str(r.get("id") or "") != GROUND_ROOM_ID
               and not is_floor_room(str(r.get("id") or ""))]
    by_id = next((r for r in regular if r.get("id") == room_arg), None)
    if by_id is not None:
        return by_id
    named = [r for r in regular if str(r.get("name") or "") == room_arg]
    if len(named) == 1:
        return named[0]
    if named:
        raise ToolRefusal(
            f"{len(named)} rooms in location {lid} are named {room_arg!r} — use the id: "
            + ", ".join(str(r.get("id")) for r in named))
    ids = ", ".join(f'{r.get("id")} "{r.get("name") or ""}"' for r in regular)
    raise ToolRefusal(f"location {lid} has no room {room_arg!r} — rooms: {ids or 'none'}")


def _check_room_prop_fit(room: Dict[str, Any], prop: Dict[str, Any],
                         x: float, z: float, yaw: float,
                         offset_y: Optional[float]) -> List[Dict[str, Any]]:
    """Verify the room has a floor plan, is below the 100-prop cap, keeps the
    prop's turned footprint inside w×d and does not collide with an existing
    non-underlay placement. Returns the room's current placements list."""
    from app.core import furnish_geometry as fg
    from app.core.furnish_solver import UNDERLAY_MAX_H
    from app.core.props import MOUNT_KEY, get_prop
    rid = str(room.get("id") or "")
    rname = str(room.get("name") or "")
    lay = room.get("layout")
    if not isinstance(lay, dict) or not all(k in lay for k in ("x", "y", "w", "d")):
        raise ToolRefusal(f'room {rid} "{rname}" has no floor plan — set_room_layout first')
    try:
        w = float(lay["w"])
        d = float(lay["d"])
    except (TypeError, ValueError):
        raise ToolRefusal(f'room {rid} "{rname}" has no usable floor plan — set_room_layout first')
    if w <= 0 or d <= 0:
        raise ToolRefusal(f'room {rid} "{rname}" has no usable floor plan — set_room_layout first')
    existing = [p for p in (lay.get("props") or []) if isinstance(p, dict)]
    if len(existing) >= _MAX_ROOM_PROPS:
        raise ToolRefusal(f'room {rid} "{rname}" already holds its limit of '
                          f"{_MAX_ROOM_PROPS} prop placements — no more can be placed")
    pid = str(prop.get("id") or "")
    pname = str(prop.get("name") or pid)
    pw = max(0.0, float(prop.get("width_m") or 0.0))
    pd = max(0.0, float(prop.get("depth_m") or 0.0))
    ph = max(0.0, float(prop.get("height_m") or 0.0))
    ex, ez = fg.aabb_extents(pw, pd, yaw)
    hx, hz = ex / 2.0, ez / 2.0
    tol = 1e-6
    if ex > w + tol or ez > d + tol:
        raise ToolRefusal(
            f'prop {pid} "{pname}" ({_g(round(ex, 2))}×{_g(round(ez, 2))} m at yaw '
            f'{_g(yaw + 0.0)}) does not fit in room {rid} "{rname}" '
            f"({_g(w)}×{_g(d)} m)")
    if x < hx - tol or x > w - hx + tol or z < hz - tol or z > d - hz + tol:
        raise ToolRefusal(
            f'prop {pid} "{pname}" at ({_g(x + 0.0)}, {_g(z + 0.0)}) reaches outside '
            f'room {rid} "{rname}" ({_g(w)}×{_g(d)} m) — allowed '
            f"x: {_g(round(hx, 2))}…{_g(round(w - hx, 2))}, "
            f"z: {_g(round(hz, 2))}…{_g(round(d - hz, 2))}")
    new_mount = str(prop.get(MOUNT_KEY) or "floor").strip().lower() or "floor"
    new_underlay = new_mount == "floor" and ph <= UNDERLAY_MAX_H
    if not new_underlay and pw > 0 and pd > 0:
        new_corners = fg.rect_corners(x, z, pw, pd, yaw)
        y0 = float(prop.get("ground_offset_m") or 0.0) + (0.0 if offset_y is None else offset_y)
        y1 = y0 + ph
        for other in existing:
            if other.get("on"):
                continue
            eat = other.get("at")
            if not isinstance(eat, (list, tuple)) or len(eat) != 2:
                continue
            opid = str(other.get("prop_id") or "")
            oprop = get_prop(opid, read_only=True) if opid else None
            if not oprop:
                continue
            ow = max(0.0, float(oprop.get("width_m") or 0.0))
            od = max(0.0, float(oprop.get("depth_m") or 0.0))
            oh = max(0.0, float(oprop.get("height_m") or 0.0))
            if ow <= 0 or od <= 0:
                continue
            omount = str(oprop.get(MOUNT_KEY) or "floor").strip().lower() or "floor"
            if omount == "floor" and oh <= UNDERLAY_MAX_H:
                continue
            try:
                ox, oz = float(eat[0]), float(eat[1])
                oyaw = float(other.get("yaw") or 0.0)
                ooff = float(other.get("offset_y") or 0.0)
            except (TypeError, ValueError):
                continue
            oy0 = float(oprop.get("ground_offset_m") or 0.0) + ooff
            oy1 = oy0 + oh
            if not fg.spans_overlap(y0, y1, oy0, oy1):
                continue
            ocorners = fg.rect_corners(ox, oz, ow, od, oyaw)
            if fg.rects_overlap(new_corners, ocorners):
                oname = str(oprop.get("name") or opid)
                oid = str(other.get("id") or "")
                raise ToolRefusal(
                    f'prop {pid} "{pname}" at ({_g(x + 0.0)}, {_g(z + 0.0)}) overlaps '
                    f'existing placement {oid} {opid} "{oname}" at '
                    f"({_g(ox + 0.0)}, {_g(oz + 0.0)})")
    return existing


@_tool("place_room_prop", True,
       "place_room_prop{location_id, room_id, prop_id, x, z, yaw?, offset_y?, label?}",
       "stand ONE library prop in a room of a place (metres from the room's min corner) "
       "— a statue, a rug, a bench; find_props lists them")
def _place_room_prop(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.places_migration import new_place_id
    from app.core.props import get_prop, read_sidecar, safe_prop_id
    from app.models.world import append_room_props, get_location_by_id, world_write_lock
    _only_keys(args, {"location_id", "room_id", "prop_id", "x", "z", "yaw",
                      "offset_y", "label"}, "place_room_prop")
    loc = _resolve_location(_str(args, "location_id", required=True))
    lid = str(loc["id"])
    room_arg = _str(args, "room_id", required=True)
    prop_id = _str(args, "prop_id", required=True)
    x = _coord(args, "x", required=True)
    z = _coord(args, "z", required=True)
    yaw_arg = _num(args, "yaw")
    offset_y = _num(args, "offset_y")
    label = _str(args, "label")
    if offset_y is not None and (offset_y < -5.0 or offset_y > 5.0):
        raise ToolRefusal("'offset_y' must be between -5 and 5 metres")
    if label is not None and len(label) > 60:
        raise ToolRefusal("'label' must be at most 60 characters")
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid, read_only=True) if pid and pid == prop_id else {}
    if not meta:
        raise ToolRefusal(f"unknown prop {_shown(prop_id)} — find_props lists the props")
    if meta.get("quest_run"):
        raise ToolRefusal(f"prop {_shown(prop_id)} belongs to a running quest — find_props lists the props")
    prop = get_prop(pid, read_only=True)
    if not prop:
        raise ToolRefusal(f"unknown prop {_shown(prop_id)} — find_props lists the props")
    yaw_val = 0.0 if yaw_arg is None else float(yaw_arg)
    # Cheap pre-checks before the backup: a refused first write copies nothing.
    room = _room_for_prop(loc, room_arg)
    _check_room_prop_fit(room, prop, x, z, yaw_val, offset_y)
    step.prepare()
    with world_write_lock:
        cur = get_location_by_id(lid)
        if cur is None:
            raise ToolRefusal(f"no location {lid!r} — use find_locations")
        room = _room_for_prop(cur, room_arg)
        rid = str(room["id"])
        rname = str(room.get("name") or "")
        existing = _check_room_prop_fit(room, prop, x, z, yaw_val, offset_y)
        existing_ids = {str(p.get("id") or "") for p in existing}
        place_id = new_place_id()
        while place_id in existing_ids:
            place_id = new_place_id()
        entry: Dict[str, Any] = {
            "id": place_id,
            "prop_id": pid,
            "at": [x, z],
            "yaw": yaw_val,
        }
        if offset_y is not None:
            entry["offset_y"] = offset_y
        if label:
            entry["label"] = label
        before = copy.deepcopy(cur)
        step.begin("location", lid, {"op": "restore_location", "id": lid,
                                     "before": before})

        def reconcile():
            b, w = wu.diff_keys(before, get_location_by_id(lid))
            if not b:
                return None
            return lid, {"op": "restore_location", "id": lid, "before": b}, w

        with step.writing(reconcile):
            if not append_room_props(lid, rid, [entry]):
                raise ValueError(f"room {rid} did not accept prop {pid}")
        after = get_location_by_id(lid) or {}
        b, w = wu.diff_keys(before, after)
        if not b:
            msg = f"prop {pid} was not stored in room {rid}"
            step.complete(None, f"error: {msg}", kind="refused")
            raise ToolRefusal(msg)
        step.attach(lid, {"op": "restore_location", "id": lid, "before": b},
                    before=b)
        stored_room = next((r for r in after.get("rooms") or []
                            if isinstance(r, dict) and r.get("id") == rid), {})
        stored_props = ((stored_room.get("layout") or {}).get("props")) or []
        stored = next((p for p in reversed(stored_props)
                       if isinstance(p, dict) and p.get("id") == place_id), None)
        sx, sz = (stored or entry)["at"]
        syaw = float((stored or entry).get("yaw") or 0.0)
        pname = str(prop.get("name") or pid)
        line = (f'placed prop {pid} "{_short(pname, 60)}" in room {rid} '
                f'"{_short(rname, 60)}" of {lid} at ({_g(sx + 0.0)}, {_g(sz + 0.0)}) '
                f"yaw {_g(syaw + 0.0)}")
        step.complete(w, line)
    return line

# ── Terrain and height areas ─────────────────────────────────────────────

def _sanitize_layout(key: str, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """One area through sanitize_map_layout with the real world context;
    refused (with the warning texts) when the sanitizer drops it.

    ``bounds=None`` on purpose (E3): in free mode an area is judged only
    against the run's build box (:func:`_bounds_warnings`), never against
    the built extent — that extent grows with every write, so judging
    against it would flag every second area in an empty world."""
    from app.core.map_layout_apply import sanitize_map_layout
    from app.core.world_dev_apply import _map_world_context
    catalog, locations_by_id, _extent, default_kind = _map_world_context()
    normalized, warnings = sanitize_map_layout(
        {key: [raw]}, catalog=catalog, locations_by_id=locations_by_id,
        bounds=None, default_kind=default_kind)
    texts = [str(w.get("message") or w.get("code") or "") for w in warnings]
    if not normalized.get(key):
        raise ToolRefusal("; ".join(t for t in texts if t) or "area dropped")
    return normalized[key][0], texts


def _geometry_raw(args: Dict[str, Any], fallback_polygon: Any = None) -> Dict[str, Any]:
    if args.get("polygon") is not None and args.get("stroke") is not None:
        raise ToolRefusal("give polygon OR stroke, not both")
    if args.get("polygon") is not None:
        return {"polygon": _ring(args["polygon"], "polygon")}
    if args.get("stroke") is not None:
        stroke = args["stroke"]
        if not isinstance(stroke, dict):
            raise ToolRefusal("'stroke' must be an object {points, width_m, style?}")
        _only_keys(stroke, {"points", "width_m", "style", "spacing_m", "amplitude_m",
                            "along"}, "stroke")
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


#: Flat water keys an area may author (terrain._sanitize_water decides each).
_WATER_KEYS = ("water_level", "water_level_up", "water_level_down", "flow_dir_deg",
               "flow_along", "flow_speed_m_s", "water_depth_m", "shore_ramp_m", "bed_kind")
#: The micro-relief numbers of an area (terrain._sanitize_relief).
_RELIEF_KEYS = ("relief_amplitude_m", "relief_wave_m")
#: Extras of a terrain area beside kind / geometry / label / z_order.
_AREA_EXTRA_KEYS = ("scatter", "npc_slots", "water") + _RELIEF_KEYS
_FLOW_DEFAULT_NOTE = ('flows forward (drawing order) — send water {"flow_along": ""} '
                      'for still water')


def _check_prop_model(entry: Dict[str, Any], what: str, required: bool) -> None:
    """The 'model' of a scatter entry / along row must be the model URL
    find_props prints (/assets/props/<id>/model) of a prop that exists — the
    stored shape is the renderer's, so it is checked, never translated (E10)."""
    from app.core.props import get_prop, prop_id_from_model_url
    model = entry.get("model")
    if model in (None, ""):
        if required:
            raise ToolRefusal(f"'{what}.model' is missing — a row without a model places "
                              f"nothing; give a prop model URL /assets/props/<id>/model")
        return
    pid = prop_id_from_model_url(model) if isinstance(model, str) else ""
    prop = get_prop(pid, read_only=True) if pid else None
    if not pid or model != f"/assets/props/{pid}/model" \
            or prop is None or prop.get("quest_run"):
        raise ToolRefusal(f"'{what}.model' must be the model URL /assets/props/<id>/model "
                          f"of an existing prop — {_shown(model)} is none")


def _check_entry_list(value: Any, what: str, required_model: bool,
                      scatter: bool = False) -> None:
    if not isinstance(value, list):
        raise ToolRefusal(f"'{what}' must be a list of objects ([] removes them all)")
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ToolRefusal(f"'{what}[{i}]' must be an object")
        _check_prop_model(entry, f"{what}[{i}]", required_model)
        # A spread entry (no place) is density-sampled: without a density
        # above 0 it is stored as 0.0 and scatters nothing. An edge row or a
        # centre instance ignores the density (scene-render scatter.ts).
        if scatter and entry.get("place") not in ("edge", "center"):
            density = entry.get("density_per_100m2")
            if not _is_num(density) or float(density) <= 0:
                raise ToolRefusal(f"'{what}[{i}].density_per_100m2' must be a number above 0 "
                                  f"— an entry without a density scatters nothing "
                                  f'(only place "edge" / "center" goes without one)')
        # An edge row is walked at min_spacing_m: without a spacing above 0
        # the renderer places no station (scene-render scatterAxis.ts
        # ringStations).
        if scatter and entry.get("place") == "edge":
            spacing = entry.get("min_spacing_m")
            if not _is_num(spacing) or float(spacing) <= 0:
                raise ToolRefusal(f"'{what}[{i}].min_spacing_m' must be a number above 0 — "
                                  f'an edge row needs min_spacing_m, the distance between '
                                  f"its props")


def _check_area_extra_args(args: Dict[str, Any]) -> None:
    """Shape checks of the area extras an add/update sends (scatter,
    npc_slots, water, relief, stroke.along) — before any read or backup."""
    from app.core.terrain_types import effective_catalog
    if args.get("scatter") is not None:
        _check_entry_list(args["scatter"], "scatter", False, scatter=True)
    stroke = args.get("stroke")
    if isinstance(stroke, dict) and stroke.get("along") is not None:
        _check_entry_list(stroke["along"], "stroke.along", True)
    slots = args.get("npc_slots")
    if slots is not None:
        if not isinstance(slots, list):
            raise ToolRefusal("'npc_slots' must be a list of slot objects ([] removes them all)")
        for i, slot in enumerate(slots):
            if isinstance(slot, dict) and any(k in slot for k in ("room", "radius_m")):
                raise ToolRefusal(f"'npc_slots[{i}]': an area slot has no room or radius_m "
                                  f"— the painted area itself is the slot's home")
        if slots:
            _check_npc_slots(slots, None)
    water = args.get("water")
    if water is not None:
        if not isinstance(water, dict):
            raise ToolRefusal("'water' must be an object {" + ", ".join(_WATER_KEYS) + "}")
        _only_keys(water, set(_WATER_KEYS), "water")
        bed = water.get("bed_kind")
        if bed not in (None, ""):
            kinds = sorted(effective_catalog())
            if not isinstance(bed, str) or bed not in kinds:
                raise ToolRefusal("'water.bed_kind' must be a terrain kind: "
                                  + ", ".join(kinds) + ' ("" = the kind\'s own bed)')
    for key in _RELIEF_KEYS:
        if args.get(key) is not None:
            _num(args, key)


def _area_meta_extras(args: Dict[str, Any], stored_meta: Dict[str, Any]) -> Dict[str, Any]:
    """The meta to write: the sent extras laid over the stored meta (an add
    passes the meta its geometry produced). scatter / npc_slots replace their
    whole list, [] removes it; water keys are flat meta keys, "" removes one;
    a relief number 0 removes it. Everything not sent stays as stored."""
    meta = copy.deepcopy(stored_meta) if isinstance(stored_meta, dict) else {}
    for key in ("scatter", "npc_slots"):
        if args.get(key) is not None:
            if args[key]:
                meta[key] = copy.deepcopy(args[key])
            else:
                meta.pop(key, None)
    for key, value in (args.get("water") or {}).items():
        if value == "" or value is None:
            meta.pop(key, None)
        else:
            meta[key] = copy.deepcopy(value)
    for key in _RELIEF_KEYS:
        value = args.get(key)
        if value is None:
            continue
        if _is_num(value) and float(value) == 0:
            meta.pop(key, None)
        else:
            meta[key] = value
    return meta


def _set_stroke_along(meta: Dict[str, Any], args: Dict[str, Any],
                      old_stroke: Any = None) -> None:
    """meta.stroke.along after a stroke was (re)drawn: the sent rows replace
    the list ([] removes it); no along sent keeps the stored rows."""
    stroke = meta.get("stroke")
    if not isinstance(stroke, dict):
        return
    sent = args.get("stroke") if isinstance(args.get("stroke"), dict) else {}
    if sent.get("along") is not None:
        along = sent["along"]
    elif isinstance(old_stroke, dict) and old_stroke.get("along"):
        along = old_stroke["along"]
    else:
        along = None
    stroke.pop("along", None)
    if along:
        stroke["along"] = copy.deepcopy(along)


def _is_water_stroke(row: Dict[str, Any]) -> bool:
    from app.core.terrain_types import is_water_kind
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return is_water_kind(str(row.get("kind") or "")) and isinstance(meta.get("stroke"), dict)


def _flow_default(row: Dict[str, Any], args: Dict[str, Any], was_water_stroke: bool) -> bool:
    """E11: a water area drawn as a stroke flows along its line unless the
    call says otherwise — set when the area BECOMES a water stroke and no
    flow key is sent or stored. True when the default was set."""
    water = args.get("water") or {}
    meta = row.setdefault("meta", {})
    if (was_water_stroke or not _is_water_stroke(row)
            or any(k in water for k in ("flow_along", "flow_dir_deg"))
            or any(k in meta for k in ("flow_along", "flow_dir_deg"))):
        return False
    meta["flow_along"] = "forward"
    return True


def _check_area_row(row: Dict[str, Any], args: Dict[str, Any]) -> None:
    """The full row through terrain.sanitize_area BEFORE anything is
    written: its ValueError (NPC slots without a label, too many entries) is
    the refusal, and every sent extra the sanitizer would rewrite is refused
    (a sent "" water key, 0 relief or [] list is a removal, not a value)."""
    from app.core.terrain_types import effective_catalog, is_water_kind
    from app.models.terrain import sanitize_area
    # A water object of removals only ("" values) is let through on any
    # kind: it is how leftover keys of a former water kind are cleared.
    if (any(v not in ("", None) for v in (args.get("water") or {}).values())
            and not is_water_kind(str(row.get("kind") or ""))):
        catalog = effective_catalog()
        raise ToolRefusal("'water' acts only on a water kind: "
                          + (", ".join(k for k in sorted(catalog)
                                       if is_water_kind(k, catalog)) or "none"))
    meta = sanitize_area(copy.deepcopy(row))["meta"]
    for key in ("scatter", "npc_slots"):
        if args.get(key):
            _refuse_rewritten(key, args[key], meta.get(key))
    water = {k: v for k, v in (args.get("water") or {}).items() if v not in ("", None)}
    if water.get("flow_along") and not isinstance((row.get("meta") or {}).get("stroke"), dict):
        # heightfield.is_flowing needs a stroke's line: on a polygon the key
        # would be stored and act on nothing.
        raise ToolRefusal("'water.flow_along' follows a stroke's line — use flow_dir_deg "
                          "on a polygon")
    if water:
        _refuse_rewritten("water", water, {k: meta[k] for k in water if k in meta})
    for key in _RELIEF_KEYS:
        value = args.get(key)
        if value is not None and not (_is_num(value) and float(value) == 0):
            _refuse_rewritten(key, value, meta.get(key, _ABSENT))
    wave = args.get("relief_wave_m")
    if (wave is not None and not (_is_num(wave) and float(wave) == 0)
            and "relief_amplitude_m" not in meta):
        raise ToolRefusal("'relief_wave_m' acts only beside a relief_amplitude_m — "
                          "send both (the area has no amplitude)")
    sent_stroke = args.get("stroke") if isinstance(args.get("stroke"), dict) else {}
    if sent_stroke.get("along"):
        _refuse_rewritten("stroke.along", sent_stroke["along"],
                          (meta.get("stroke") or {}).get("along"))


@_tool("add_terrain_area", True,
       "add_terrain_area{kind, polygon | stroke:{points, width_m, style?, along?}, label?, "
       "z_order?, scatter?, npc_slots?, water?, relief_amplitude_m?, relief_wave_m?}",
       "paint ground of a terrain kind (world metres), with what grows on it, "
       "NPC slots, water and relief")
def _add_terrain_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.terrain import get_area, save_area
    _only_keys(args, {"kind", "polygon", "stroke", "label", "z_order", *_AREA_EXTRA_KEYS},
               "add_terrain_area")
    raw: Dict[str, Any] = {"kind": _str(args, "kind", required=True)}
    raw.update(_geometry_raw(args))
    label = _str(args, "label")
    if label:
        raw["label"] = label
    z_order = _num(args, "z_order")
    if z_order is not None:
        raw["z_order"] = z_order
    _check_area_extra_args(args)
    area, warnings = _sanitize_layout("terrain_areas", raw)
    aid = _new_id("ta", lambda i: get_area(i) is not None)
    row = copy.deepcopy(area)
    row["id"] = aid
    row["meta"] = _area_meta_extras(args, row.get("meta") or {})
    _set_stroke_along(row["meta"], args)
    flows = _flow_default(row, args, was_water_stroke=False)
    _check_area_row(row, args)
    if flows:
        warnings = warnings + [_FLOW_DEFAULT_NOTE]
    warnings = warnings + _bounds_warnings(_polygon_points(row.get("polygon")),
                                           f"terrain area {aid}", step.ctx.run_id)
    inverse = {"op": "delete_terrain_area", "id": aid}
    step.prepare()
    box = _union_box(row.get("polygon"))
    grounds = _pin_grounds_before(box)
    step.begin("terrain", aid, inverse)

    def reconcile():
        stored = get_area(aid)
        return None if stored is None else (aid, inverse, stored)

    with step.writing(reconcile):
        save_area(row)
    written = get_area(aid)
    warnings = warnings + _ground_warnings(grounds, box)
    label_txt = f' "{label}"' if label else ""
    line = (f"added terrain area {aid} ({row['kind']}){label_txt} "
            f"{_fmt_box(_bbox((written or row).get('polygon')))}{_warn_suffix(warnings)}")
    step.complete(written, line)
    return line


@_tool("update_terrain_area", True,
       "update_terrain_area{id, kind?, polygon? | stroke?, label?, z_order?, scatter?, "
       "npc_slots?, water?, relief_amplitude_m?, relief_wave_m?}",
       "reshape/relabel an area or change what grows on it; everything not sent is kept")
def _update_terrain_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.terrain import get_area, save_area
    _only_keys(args, {"id", "kind", "polygon", "stroke", "label", "z_order",
                      *_AREA_EXTRA_KEYS}, "update_terrain_area")
    aid = _str(args, "id", required=True)
    kind = _str(args, "kind")
    label = _str(args, "label")
    z_order = _num(args, "z_order")
    new_geom = args.get("polygon") is not None or args.get("stroke") is not None
    # An empty water object changes nothing (unlike [] for a list, which
    # removes it), so it does not count as sent.
    extras = any((bool(args.get(k)) if k == "water" else args.get(k) is not None)
                 for k in _AREA_EXTRA_KEYS)
    if not new_geom and kind is None and label is None and z_order is None and not extras:
        raise ToolRefusal("nothing to change — give kind, polygon/stroke, label, z_order, "
                          "scatter, npc_slots, water or relief")
    if new_geom:
        _geometry_raw(args)  # shape errors refused before the backup
    _check_area_extra_args(args)
    # The backup first, then ONE read that is both the merge base and
    # "before": a second read after a long backup copy would let a foreign
    # edit in between be overwritten by a row built from the older read.
    # The row is also built and checked on the cheap pre-read, so a refusal
    # (a rewritten extra, slots without a label) comes before the backup.
    pre = get_area(aid)
    if pre is None:
        raise ToolRefusal(f"no terrain area {aid!r} — use map_region")
    pre_row, _ = _terrain_update_row(pre, args, kind, label, z_order, new_geom)
    # Only a call that sends a new outline is judged against the build box.
    out_of_box = (_bounds_warnings(_polygon_points(pre_row.get("polygon")),
                                   f"terrain area {aid}", step.ctx.run_id)
                  if new_geom else [])
    step.prepare()
    stored = get_area(aid)
    if stored is None:
        raise ToolRefusal(f"no terrain area {aid!r} — use map_region")
    before = copy.deepcopy(stored)
    row, warnings = _terrain_update_row(stored, args, kind, label, z_order, new_geom)
    warnings = warnings + out_of_box
    inverse = {"op": "restore_terrain_area", "row": before}
    box = _union_box(before.get("polygon"), row.get("polygon"))
    grounds = _pin_grounds_before(box)
    step.begin("terrain", aid, inverse)

    def reconcile():
        now = get_area(aid)
        return None if now == before else (aid, inverse, now)

    with step.writing(reconcile):
        save_area(row, must_exist=True)
    written = get_area(aid) or {}
    warnings = warnings + _ground_warnings(grounds, box)
    changed = [k for k in ("kind", "polygon", "z_order", "meta")
               if written.get(k) != before.get(k)]
    line = (f"updated terrain area {aid} ({written.get('kind') or row.get('kind')}): "
            + (", ".join(changed) or "no change") + _warn_suffix(warnings))
    step.complete(written, line)
    return line


def _terrain_update_row(stored: Dict[str, Any], args: Dict[str, Any], kind: Optional[str],
                        label: Optional[str], z_order: Optional[float],
                        new_geom: bool) -> Tuple[Dict[str, Any], List[str]]:
    """The row update_terrain_area writes: merged onto the stored row, never
    rebuilt, and checked whole (_check_area_row) — refuses before a write."""
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
    # The stored row is merged, never rebuilt: id and every meta key not
    # sent (scatter, water, relief, slots, ...) stay as they are.
    row = copy.deepcopy(stored)
    was_water_stroke = _is_water_stroke(stored)
    stroke_dropped = False
    meta = row.setdefault("meta", {})
    if kind is not None:
        row["kind"] = norm["kind"]
    if new_geom:
        row["polygon"] = norm["polygon"]
        if (norm.get("meta") or {}).get("stroke"):
            # The rows of props along the line (meta.stroke.along) are kept
            # by a reshaped stroke unless the call sends its own along.
            old_stroke = meta.get("stroke")
            meta["stroke"] = copy.deepcopy(norm["meta"]["stroke"])
            _set_stroke_along(meta, args, old_stroke)
        else:
            old_stroke = meta.pop("stroke", None)
            if old_stroke is not None:
                stroke_dropped = True
                rows = (old_stroke.get("along") if isinstance(old_stroke, dict) else None)
                if isinstance(rows, list) and rows:
                    # The rows of props along the line have no line to
                    # follow on a polygon: they go with the stroke.
                    from app.core.props import prop_id_from_model_url
                    ids = [prop_id_from_model_url(r.get("model")) or "?"
                           if isinstance(r, dict) else "?" for r in rows]
                    warnings = warnings + [
                        f"{len(rows)} along row{'' if len(rows) == 1 else 's'} "
                        f"({', '.join(ids)}) dropped with the stroke"]
                if ("flow_along" not in (args.get("water") or {})
                        and meta.pop("flow_along", None) is not None):
                    # flow_along follows the stroke's line; a polygon has
                    # none, so the key would act on nothing.
                    warnings = warnings + ["flow_along dropped with the stroke"]
    if label is not None:
        if label:
            meta["label"] = label
        else:
            meta.pop("label", None)
    if z_order is not None:
        row["z_order"] = int(z_order)
    row["meta"] = _area_meta_extras(args, meta)
    if stroke_dropped:
        # Decided on the MERGED meta, whoever cleared the flow (the stroke
        # drop above or a sent water {flow_along: ""}): without any flow the
        # polygon settles as a still lake on water_level, and the end levels
        # of the flowing stroke would be dead keys that read like a tilted
        # surface. End levels the call sends itself stay.
        merged = row["meta"]
        sent_water = args.get("water") or {}
        if (merged.get("flow_along") in (None, "")
                and merged.get("flow_dir_deg") in (None, "")):
            ends = [k for k in ("water_level_up", "water_level_down")
                    if k not in sent_water and merged.pop(k, None) is not None]
            if ends:
                warnings = warnings + [", ".join(ends) + " dropped with the stroke "
                                       "(still water)"]
    if _flow_default(row, args, was_water_stroke):
        warnings = warnings + [_FLOW_DEFAULT_NOTE]
    _check_area_row(row, args)
    return row, warnings


def _height_area(aid: str) -> Optional[Dict[str, Any]]:
    from app.models.heightfield import list_height_areas
    return next((a for a in list_height_areas() if a.get("id") == aid), None)


@_tool("add_height_area", True,
       "add_height_area{polygon, height_m, falloff_m?, label?}",
       "raise (or lower) the ground inside a polygon (world metres)")
def _add_height_area(step: _Step, args: Dict[str, Any]) -> str:
    from app.models.heightfield import save_height_area
    _only_keys(args, {"polygon", "height_m", "falloff_m", "label"}, "add_height_area")
    raw: Dict[str, Any] = {"polygon": _ring(args.get("polygon"), "polygon"),
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
    warnings = warnings + _bounds_warnings(_polygon_points(row.get("polygon")),
                                           f"height area {aid}", step.ctx.run_id)
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
    polygon = (_ring(args["polygon"], "polygon")
               if args.get("polygon") is not None else None)
    if polygon is None and height is None and falloff is None and label is None:
        raise ToolRefusal("nothing to change — give polygon, height_m, falloff_m or label")
    # Backup first, then one read = merge base and "before" (see
    # update_terrain_area).
    pre = _height_area(aid)
    if pre is None:  # cheap pre-check before the backup
        raise ToolRefusal(f"no height area {aid!r} — use map_region")
    # Only a call that sends a new outline is judged against the build box,
    # on the outline the CALLER sent — it does not depend on the stored row,
    # so no second read and no extra sanitizer pass feed the warning.
    out_of_box = (_bounds_warnings(_polygon_points(polygon), f"height area {aid}",
                                   step.ctx.run_id)
                  if polygon is not None else [])
    step.prepare()
    stored = _height_area(aid)
    if stored is None:
        raise ToolRefusal(f"no height area {aid!r} — use map_region")
    before = copy.deepcopy(stored)
    raw = {"polygon": polygon if polygon is not None else stored.get("polygon"),
           "height_m": height if height is not None else stored.get("height_m"),
           "falloff_m": falloff if falloff is not None else stored.get("falloff_m")}
    norm, warnings = _sanitize_layout("height_areas", raw)
    warnings = (warnings + out_of_box) if polygon is not None else []
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


# ── Custom terrain kinds (E12) ───────────────────────────────────────────

_TERRAIN_TYPE_KEYS = ("kind", "name", "color", "passable", "speed_factor", "water", "surface")
_TERRAIN_TYPE_WATER_KEYS = ("water_depth_m", "shore_ramp_m")


def _kind_users_text(users: List[Tuple[str, str, str]], cap: int = 6) -> str:
    texts = [text for _k, _i, text in users]
    more = len(texts) - cap
    return "; ".join(texts[:cap]) + (f"; … {more} more" if more > 0 else "")


@_tool("add_terrain_type", True,
       "add_terrain_type{kind, name, color, passable?, speed_factor?, "
       "water?:{water_depth_m?, shore_ramp_m?}, surface?}",
       "create a NEW terrain kind for this world (an existing kind is never changed)")
def _add_terrain_type(step: _Step, args: Dict[str, Any]) -> str:
    """Create one world terrain kind. The FORMAT of the kind id and every
    range are the catalog sanitizer's (terrain_types.sanitize_type): its
    ValueError is the refusal, and a value it would rewrite (clamp, round,
    trim) is refused through _refuse_rewritten. A kind the effective catalog
    already holds (shared seed or world row) is refused — editing a kind
    changes every area of it world-wide, which is the editor's job (E12)."""
    from app.core import terrain_types as tt
    _only_keys(args, set(_TERRAIN_TYPE_KEYS), "add_terrain_type")
    for key in ("kind", "name", "color"):
        _str(args, key, required=True)
    _str(args, "surface")
    _bool(args, "passable")
    _num(args, "speed_factor")
    raw: Dict[str, Any] = {k: args[k] for k in ("kind", "name", "color", "passable",
                                                "speed_factor", "surface")
                           if args.get(k) is not None}
    water = args.get("water")
    sent_water: Dict[str, Any] = {}
    if water is not None:
        if not isinstance(water, dict):
            raise ToolRefusal("'water' must be an object {"
                              + ", ".join(_TERRAIN_TYPE_WATER_KEYS) + "} ({} = water "
                              "with the default depth and shore)")
        _only_keys(water, set(_TERRAIN_TYPE_WATER_KEYS), "water")
        for key in _TERRAIN_TYPE_WATER_KEYS:
            if _num(water, key) is not None:
                sent_water[key] = water[key]
        raw["meta"] = {tt.WATER_META_KEY: True, **sent_water}
    try:
        entry = tt.sanitize_type(copy.deepcopy(raw))
    except ValueError as exc:
        raise ToolRefusal(str(exc)) from None
    sent = {k: v for k, v in raw.items() if k != "meta"}
    stored: Dict[str, Any] = dict(entry)
    if sent_water:
        sent["water"] = sent_water
        stored["water"] = entry.get("meta") or {}
    _refuse_rewritten("add_terrain_type", sent, stored)
    kind = entry["kind"]
    surface = entry.get("surface")
    if surface:
        from app.core.surface_textures import library_kinds
        library = sorted(library_kinds())
        if library and surface not in library:
            raise ToolRefusal(f"'surface' must be a kind of the surface library — "
                              f"list_catalog{{name: surface_kinds}} lists them")
    source = tt.sources().get(kind)
    if source:
        raise ToolRefusal(f"terrain kind {kind!r} already exists ({source}) — an existing "
                          "kind is changed in the terrain editor, never here; pick a new id")
    inverse = {"op": "delete_terrain_type", "kind": kind}
    step.prepare()
    step.begin("terrain_type", kind, inverse)

    def reconcile():
        now = wu.terrain_type_row(kind)
        return None if now is None else (kind, inverse, now)

    with step.writing(reconcile):
        tt.save_world_type(entry)
    written = wu.terrain_type_row(kind)
    line = "added terrain kind " + _kind_text(kind, written or entry, tt.effective_catalog())
    step.complete(written, line)
    return line


# ── Props: the library and free-standing world props (E10) ──────────────

#: Most tags one find_props line shows (a prop may carry many).
_PROP_LINE_TAGS = 6


def _prop_line(rec: Dict[str, Any]) -> str:
    """One find_props line: id, name, category, size, mount, tags and the
    model URL the scatter / along rows take (E10)."""
    from app.core.props import MOUNT_KEY
    pid = str(rec.get("id") or "")
    tags = [str(t) for t in rec.get("tags") or [] if str(t).strip()]
    shown = ", ".join(tags[:_PROP_LINE_TAGS]) + (" …" if len(tags) > _PROP_LINE_TAGS else "")
    line = (f'{pid} "{_short(rec.get("name") or pid, 60)}" {rec.get("category") or "-"} '
            f"{_g(rec.get('width_m'))}×{_g(rec.get('depth_m'))}×{_g(rec.get('height_m'))} m "
            f"mount {rec.get(MOUNT_KEY) or '-'} tags {shown or '-'} "
            f"model /assets/props/{pid}/model")
    if not rec.get("has_model"):
        line += " · no mesh yet"
    return line


@_tool("find_props", False, "find_props{query?, category?, tag?, mount?}",
       "3D props of the library (furniture, statues, rugs, wall art, lamps, plants) — "
       "id, size in metres, mount, tags and model URL for furnish_rooms, "
       "place_room_prop, place_world_prop, scatter and along rows; if a needed prop is "
       "missing, name it under left open instead of creating an item")
def _find_props(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.props import MOUNT_KEY, MOUNT_KINDS, list_props
    _only_keys(args, {"query", "category", "tag", "mount"}, "find_props")
    query = (_str(args, "query") or "").lower()
    category = (_str(args, "category") or "").lower()
    tag = (_str(args, "tag") or "").lower()
    mount = _str(args, "mount") or ""
    if mount and mount not in MOUNT_KINDS:
        raise ToolRefusal(f"mount {_shown(mount)} is none of " + ", ".join(MOUNT_KINDS))
    lines: List[str] = []
    # A read tool: the read-only listing writes no sidecar and starts no job.
    records = sorted(list_props(read_only=True),
                     key=lambda r: (str(r.get("name") or "").lower(), str(r.get("id") or "")))
    for rec in records:
        if rec.get("quest_run"):
            continue
        tags = [str(t).lower() for t in rec.get("tags") or []]
        if category and str(rec.get("category") or "").lower() != category:
            continue
        if tag and tag not in tags:
            continue
        if mount and rec.get(MOUNT_KEY) != mount:
            continue
        if query and not any(query in str(s or "").lower() for s in (
                rec.get("id"), rec.get("name"), rec.get("description"), *tags)):
            continue
        lines.append(_prop_line(rec))
    if not lines:
        return "no props match"
    return "\n".join(_cap_lines(lines, "narrow it with query, category, tag or mount"))


#: place_world_prop argument -> the stored world-prop key it becomes.
_WORLD_PROP_ARGS = {"prop_id": "prop_id", "x": "x", "z": "z", "yaw": "yaw_deg",
                    "offset_y": "offset_y", "variant": "variant"}


def _world_prop_warnings(x: float, z: float) -> List[str]:
    """Hints for a world prop at (x, z): impassable ground under it (the
    terrain kind the map reads there) and the outline of a placed place it
    stands in (its stored boundary; a place without one is a pin and has no
    outline to stand in). A read only; a failure costs the hints, never the
    step."""
    from app.core.terrain_query import kind_at
    from app.core.world_geometry import boundary_contains
    from app.models.world import list_locations
    out: List[str] = []
    try:
        catalog, areas, default_kind = _placement_world()
        kind = kind_at(x, z, areas=areas, default_kind=default_kind)
        if not bool((catalog.get(kind) or {}).get("passable", True)):
            out.append(f"it stands on {kind}, which nobody can walk on")
        for loc in list_locations():
            if loc.get("pos_x") is None or loc.get("pos_z") is None:
                continue
            entry = _placement_entry(loc, loc["pos_x"], loc["pos_z"], loc.get("yaw_deg"))
            if entry["boundary"] is None:
                continue
            shape = {"pos_x": entry["pos_x"], "pos_z": entry["pos_z"],
                     "yaw_deg": entry["yaw_deg"], "map3d": {"boundary": entry["boundary"]}}
            if boundary_contains(shape, x, z):
                out.append(f'it stands inside the outline of place {loc.get("id")} '
                           f'"{loc.get("name") or ""}" — what belongs to a place goes '
                           f"into its rooms (furnish_rooms)")
    except Exception:  # noqa: BLE001 — a hint, never a reason to refuse
        logger.exception("world-dev: ground check of a world prop failed")
    return out


@_tool("place_world_prop", True, "place_world_prop{prop_id, x, z, yaw?, offset_y?, variant?}",
       "stand ONE library prop (3D object from find_props) on open ground outside any "
       "place (world metres) — a well, a signpost, a rock; for a room use "
       "place_room_prop")
def _place_world_prop(step: _Step, args: Dict[str, Any]) -> str:
    from app.models import world_props as wp
    _only_keys(args, set(_WORLD_PROP_ARGS), "place_world_prop")
    prop_id = _str(args, "prop_id", required=True)
    x = _coord(args, "x", required=True)
    z = _coord(args, "z", required=True)
    yaw = _num(args, "yaw")
    offset = _num(args, "offset_y")
    variant = args.get("variant")
    if variant is not None and (isinstance(variant, bool) or not isinstance(variant, int)
                                or variant < 0):
        raise ToolRefusal("'variant' must be a whole number from 0 (a variant index of the "
                          "prop) — leave it out and the placement picks one")
    if wp.count_world_props() >= wp.MAX_WORLD_PROPS:
        raise ToolRefusal(f"the world already holds its limit of {wp.MAX_WORLD_PROPS} "
                          "world props — no more can be placed")
    from app.core.props import read_sidecar
    if read_sidecar(prop_id, read_only=True).get("quest_run"):
        raise ToolRefusal(f"prop {_shown(prop_id)} belongs to a running quest — find_props lists the props")
    existing = {r["id"] for r in wp.list_world_props()}
    wid = _new_id("wp", lambda i: i in existing)
    raw = {"id": wid, "prop_id": prop_id, "x": x, "z": z,
           "yaw_deg": 0.0 if yaw is None else yaw,
           "offset_y": 0.0 if offset is None else offset, "variant": variant}
    try:
        entry = wp.sanitize_world_prop(raw)
    except ValueError as exc:
        raise ToolRefusal(f"{exc} — find_props lists the props") from None
    sent = {k: (prop_id if k == "prop_id" else args[k])
            for k in _WORLD_PROP_ARGS if args.get(k) is not None}
    _refuse_rewritten("place_world_prop", sent,
                      {k: entry[key] for k, key in _WORLD_PROP_ARGS.items()})
    warnings = (_world_prop_warnings(entry["x"], entry["z"])
                + _bounds_warnings([(entry["x"], entry["z"])], f"world prop {wid}",
                                   step.ctx.run_id))
    inverse = {"op": "delete_world_prop", "id": wid}
    step.prepare()
    step.begin("world_prop", wid, inverse)

    def reconcile():
        stored = wu.world_prop_row(wid)
        return None if stored is None else (wid, inverse, stored)

    with step.writing(reconcile):
        wp.save_world_prop(entry)
    written = wu.world_prop_row(wid)
    # `+ 0.0` turns a -0.0 into 0.0 — the line shows what the row holds.
    line = (f"placed world prop {wid} ({entry['prop_id']}) at "
            f"({_g(entry['x'] + 0.0)},{_g(entry['z'] + 0.0)}) "
            f"yaw {_g(entry['yaw_deg'] + 0.0)}"
            + _warn_suffix(warnings))
    step.complete(written, line)
    return line


# ── Items: the catalog, inventories and room items (E14) ─────────────────

#: create_item arguments (add_item keywords of the same name).
_ITEM_ARGS = ("name", "category", "description", "prompt_fragment", "image_prompt",
              "stackable", "max_stack", "consumable", "transferable", "portable", "rarity")


def _item_line(item: Dict[str, Any], shared: bool = False) -> str:
    """One find_items line: id, name, category, the piece slots of an outfit
    piece, "shared" for a library item, and the prompt fragment."""
    slots = [str(s) for s in ((item.get("outfit_piece") or {}).get("slots") or [])]
    frag = str(item.get("prompt_fragment") or "").strip()
    return (f'{item.get("id")} "{_short(item.get("name") or item.get("id"), 60)}" '
            f'{item.get("category") or "-"}'
            + (f" [{', '.join(slots)}]" if slots else "")
            + (" shared" if shared else "")
            + f" — {_short(frag, 80) if frag else '-'}")


def _catalog_items() -> List[Tuple[Dict[str, Any], bool]]:
    """(item, shared) of the world catalog and the shared library (a world
    item shadows a library item of the same id, as get_item reads them); part
    items are left out — they are worn through their host only."""
    from app.core.accessory_parts import is_part
    from app.models.inventory import list_items, list_shared_items
    out: List[Tuple[Dict[str, Any], bool]] = []
    seen: set = set()
    for item in list_items():
        seen.add(str(item.get("id") or ""))
        out.append((item, False))
    for item in list_shared_items():
        if str(item.get("id") or "") not in seen:
            out.append((item, True))
    return [(i, s) for i, s in out if i.get("id") and not is_part(i)]


@_tool("find_items", False, "find_items{query?, category?, slot?}",
       "items of the catalog (world and shared library) — id, name, category, the slots "
       "of a clothing piece; reuse an id instead of creating the same item again")
def _find_items(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"query", "category", "slot"}, "find_items")
    query = (_str(args, "query") or "").lower()
    category = (_str(args, "category") or "").lower()
    slot = (_str(args, "slot") or "").lower()
    lines: List[str] = []
    for item, shared in sorted(_catalog_items(), key=lambda p: (
            str(p[0].get("name") or "").lower(), str(p[0].get("id") or ""))):
        if category and str(item.get("category") or "").lower() != category:
            continue
        slots = [str(s).lower() for s in ((item.get("outfit_piece") or {}).get("slots") or [])]
        if slot and slot not in slots:
            continue
        if query and not any(query in str(s or "").lower() for s in (
                item.get("id"), item.get("name"), item.get("description"),
                item.get("prompt_fragment"))):
            continue
        lines.append(_item_line(item, shared))
    if not lines:
        return "no items match"
    return "\n".join(_cap_lines(lines, "narrow it with query, category or slot"))


def _item_or_refuse(item_id: Any, what: str) -> Dict[str, Any]:
    """The catalog item a give / room placement names: it exists, is no part
    item (worn through its host only) and reveals no secret (handing it over
    or finding it would mark the secret known, outside every undo)."""
    from app.core.accessory_parts import is_part
    from app.models.inventory import get_item
    if not isinstance(item_id, str) or not item_id.strip():
        raise ToolRefusal(f"{what}: 'item_id' is required (an id of find_items)")
    iid = item_id.strip()
    item = get_item(iid)
    if not item:
        raise ToolRefusal(f"{what}: no item {iid!r} — find_items lists the catalog")
    if is_part(item):
        raise ToolRefusal(f"{what}: item {iid!r} is a part worn through its host — it is "
                          "never held or placed on its own")
    if item.get("reveals_secret"):
        raise ToolRefusal(f"{what}: item {iid!r} reveals a secret when handed over or "
                          "found — it cannot be given or placed here")
    return item


def _whole_arg(args: Dict[str, Any], key: str, lo: int, hi: int, default: int,
               what: str) -> int:
    if key not in args or args[key] is None:
        return default
    if not _whole_in(args[key], lo, hi):
        raise ToolRefusal(f"{what}: '{key}' must be a whole number {lo}…{hi}")
    return int(args[key])


@_tool("create_item", True,
       "create_item{name, category, description?, prompt_fragment?, image_prompt?, "
       "stackable?, max_stack?, consumable?, transferable?, portable?, rarity?}",
       "add a NEW non-clothing item: a thing characters can pick up, carry, use or own "
       "(never furniture or decoration that stands in a room — that is a prop; missing "
       "props go under left open)")
def _create_item(step: _Step, args: Dict[str, Any]) -> str:
    """One catalog item through inventory.add_item. The id is minted UP FRONT
    (as place_world_prop does), so the journal row is begun with its exact
    inverse before the write; a crash between begin and write leaves a
    pending row whose inverse finds the item already gone."""
    from app.models.inventory import (VALID_RARITIES, add_item, get_item,
                                      is_shared_item, require_item_id)
    _only_keys(args, set(_ITEM_ARGS), "create_item")
    name = _str(args, "name", required=True)
    _check_name_length(name, "'name'")
    category = _str(args, "category", required=True)
    allowed = _item_categories()
    if category not in allowed:
        raise ToolRefusal(f"category {_shown(category)} is none of " + ", ".join(allowed)
                          + " (clothing comes with outfits — update_character)")
    texts = {k: _str(args, k) or "" for k in ("description", "prompt_fragment", "image_prompt")}
    flags = {k: _bool(args, k) for k in ("stackable", "consumable", "transferable", "portable")}
    rarity = _str(args, "rarity") or "common"
    if rarity not in VALID_RARITIES:
        raise ToolRefusal(f"rarity {_shown(rarity)} is none of " + ", ".join(VALID_RARITIES))
    stackable = bool(flags["stackable"])
    max_stack = args.get("max_stack")
    if stackable:
        if max_stack is None or not _whole_in(max_stack, 2, 9999):
            raise ToolRefusal("a stackable item needs 'max_stack', a whole number 2…9999 "
                              "(the most one character can carry of it)")
    elif max_stack is not None:
        raise ToolRefusal("'max_stack' needs stackable true — leave it out for a single item")
    # Every catalog item counts here, part items included (find_items hides
    # them; a name may still not be taken twice).
    from app.models.inventory import list_items, list_shared_items
    taken = next((i for i in list(list_items()) + list(list_shared_items())
                  if str(i.get("name") or "").strip().casefold() == name.casefold()), None)
    if taken is not None:
        from app.core.accessory_parts import is_part
        if is_part(taken):
            raise ToolRefusal(f"the catalog already has the part item {taken.get('id')} "
                              f'"{taken.get("name")}" (worn through its host) — choose '
                              "another name")
        uses = "give_items, add_room_item" + (", an outfit piece {item_id}"
                                              if taken.get("category") == "outfit_piece" else "")
        raise ToolRefusal(f"the catalog already has {taken.get('id')} "
                          f'"{taken.get("name")}" — reuse it ({uses})')
    iid = require_item_id(_new_id("item", lambda i: get_item(i) is not None
                                  or is_shared_item(i)))
    inverse = {"op": "delete_items", "ids": [iid]}
    step.prepare()
    step.begin("item", iid, inverse)

    def reconcile():
        now = get_item(iid)
        return None if now is None else (iid, inverse, wu.item_row(iid))

    with step.writing(reconcile):
        stored = add_item(
            name=name, category=category, rarity=rarity, item_id=iid,
            stackable=stackable, max_stack=int(max_stack) if stackable else 1,
            consumable=bool(flags["consumable"]),
            transferable=True if flags["transferable"] is None else flags["transferable"],
            portable=True if flags["portable"] is None else flags["portable"],
            **texts)
        if stored.get("id") != iid:
            raise ValueError(f"the catalog stored the item as {stored.get('id')!r}, "
                             f"not as the minted {iid!r}")
    line = (f'created item {iid} "{name}" {category}'
            + (f" stackable up to {int(max_stack)}" if stackable else ""))
    step.complete(wu.item_row(iid), line)
    return line


def _give_plan(name: str, wanted: List[Tuple[str, int]],
               items: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The before map of a give, or a refusal: only a NEW entry (R1) or a
    stack increase within max_stack (R2) — the two cases the inverse
    restores exactly. Read under the profile lock that covers the write."""
    from app.models.inventory import get_character_inventory, get_item
    entries = wu.inventory_entries(name)
    before: Dict[str, Any] = {}
    new_slots = 0
    for iid, qty in wanted:
        item = items[iid]
        stackable = bool(item.get("stackable"))
        max_stack = int(item.get("max_stack", 99) or 1)
        cur = entries.get(iid)
        if cur is None:
            if not stackable and qty > 1:
                raise ToolRefusal(f"item {iid} is not stackable — give 1, or create a "
                                  "stackable item")
            if stackable and qty > max_stack:
                raise ToolRefusal(f"item {iid}: {qty} is more than its max_stack {max_stack}")
            if item.get("category") != "outfit_piece":
                new_slots += 1
            before[iid] = wu.ABSENT
            continue
        if not stackable:
            raise ToolRefusal(f"{name} already holds it ({iid}) — the inventory keeps one "
                              "entry per item")
        if cur.get("locked"):
            raise ToolRefusal(f"{name} holds {iid} as a locked entry — a give would add a "
                              "separate one; not possible here")
        held_qty = int(cur.get("quantity") or 1)
        if held_qty + qty > max_stack:
            raise ToolRefusal(f"item {iid}: {name} holds {held_qty}, {held_qty} + {qty} is "
                              f"more than its max_stack {max_stack}")
        before[iid] = held_qty
    if new_slots:
        max_slots = int(get_character_inventory(name, include_equipped=True)
                        .get("max_slots", 20) or 20)
        used = sum(1 for iid in entries
                   if (get_item(iid) or {}).get("category") not in (None, "outfit_piece"))
        if used + new_slots > max_slots:
            raise ToolRefusal(f"{name} carries {used} of {max_slots} items — "
                              f"{new_slots} new would not fit")
    return before


@_tool("give_items", True, "give_items{character, items:[{item_id, quantity?}]}",
       "put catalog items into a character's inventory (a new entry, or more of a "
       "stackable item up to its max_stack)")
def _give_items(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.keyed_lock import keyed_lock
    from app.models.character import character_row_exists
    from app.models.inventory import add_to_inventory
    _only_keys(args, {"character", "items"}, "give_items")
    name = _str(args, "character", required=True)
    raw = args.get("items")
    if not isinstance(raw, list) or not raw:
        raise ToolRefusal("'items' must be a non-empty list of {item_id, quantity?}")
    wanted: List[Tuple[str, int]] = []
    items: Dict[str, Dict[str, Any]] = {}
    for i, it in enumerate(raw):
        what = f"items[{i}]"
        if not isinstance(it, dict):
            raise ToolRefusal(f"{what} must be an object {{item_id, quantity?}}")
        _only_keys(it, {"item_id", "quantity"}, what)
        item = _item_or_refuse(it.get("item_id"), what)
        iid = str(item["id"])
        if iid in items:
            raise ToolRefusal(f"item {iid} is named twice — merge the quantities")
        qty = _whole_arg(it, "quantity", 1, 9999, 1, what)
        items[iid] = item
        wanted.append((iid, qty))
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    with keyed_lock("character_profile", name):
        _give_plan(name, wanted, items)
    step.prepare()
    with keyed_lock("character_profile", name):
        if not character_row_exists(name):
            raise ToolRefusal(f"no character {name!r}")
        before = _give_plan(name, wanted, items)
        pre = wu.inventory_entries(name)
        inverse = {"op": "restore_inventory", "name": name, "before": before}
        step.begin("character", name, inverse)

        def written_now() -> Dict[str, Any]:
            now = wu.inventory_entries(name)
            return {iid: now.get(iid, wu.ABSENT) for iid in before}

        def reconcile():
            now = written_now()
            changed = any(now[iid] != pre.get(iid, wu.ABSENT) for iid in before)
            return (name, inverse, now) if changed else None

        with step.writing(reconcile):
            for iid, qty in wanted:
                if not add_to_inventory(name, iid, quantity=qty, obtained_method="manual"):
                    raise ValueError(f"the inventory did not take {iid}")
        written = written_now()
    parts = []
    for iid, qty in wanted:
        now = written.get(iid) or {}
        parts.append(f'{qty}× {iid} "{_short(items[iid].get("name") or iid, 40)}"'
                     + (" (new)" if wu.is_absent(before[iid])
                        else f" (now {now.get('quantity')})"))
    line = f"gave {name}: " + ", ".join(parts)
    step.complete(written, line)
    return line


def _stored_difficulty(entry: Optional[Dict[str, Any]]) -> int:
    """A room entry's discovery_difficulty as the writer stores it (0…999)."""
    value = (entry or {}).get("discovery_difficulty")
    return max(0, min(999, int(value))) if _is_num(value) else 0


@_tool("add_room_item", True,
       "add_room_item{location_id, room_id, item_id, quantity?, hidden?, "
       "discovery_difficulty?, note?}",
       "lay a pickupable catalog item in a room (more of it when it already lies there "
       "— never for 3D props like furniture, statues or rugs; use place_room_prop)")
def _add_room_item(step: _Step, args: Dict[str, Any]) -> str:
    """inventory.add_item_to_room; the journal holds the room's WHOLE items
    value before (the list, or ABSENT when the room had no key), so the
    inverse sets the room back exactly — also the hidden / difficulty / note
    the writer overwrites on an entry that already lies there. On such an
    entry, a ``hidden`` / ``discovery_difficulty`` left out keeps the stored
    value (the writer would reset it to visible / 0); the line names a
    visibility or difficulty change."""
    from app.models.inventory import add_item_to_room
    from app.models.world import get_location_by_id, world_write_lock
    _only_keys(args, {"location_id", "room_id", "item_id", "quantity", "hidden",
                      "discovery_difficulty", "note"}, "add_room_item")
    loc = _resolve_location(_str(args, "location_id", required=True))
    lid = str(loc.get("id"))
    rid = _str(args, "room_id", required=True)
    item = _item_or_refuse(args.get("item_id"), "add_room_item")
    iid = str(item["id"])
    qty = _whole_arg(args, "quantity", 1, 9999, 1, "add_room_item")
    hidden_arg = _bool(args, "hidden")
    difficulty_arg = (None if args.get("discovery_difficulty") is None else
                      _whole_arg(args, "discovery_difficulty", 0, 999, 0, "add_room_item"))
    note = _str(args, "note") or ""

    def room_items_now() -> Tuple[Optional[Dict[str, Any]], Any]:
        cur = get_location_by_id(lid)
        room = next((r for r in (cur or {}).get("rooms") or []
                     if isinstance(r, dict) and r.get("id") == rid), None)
        if room is None:
            return None, None
        return room, wu.room_items_value(room)

    room, _items = room_items_now()
    if room is None:
        ids = ", ".join(f'{r.get("id")} "{r.get("name") or ""}"' for r in loc.get("rooms") or []
                        if isinstance(r, dict))
        raise ToolRefusal(f"location {lid} has no room {rid!r} — rooms: {ids or 'none'}")
    step.prepare()
    with world_write_lock:  # re-entrant; add_item_to_room takes it again
        room, before = room_items_now()
        if room is None:
            raise ToolRefusal(f"location {lid} has no room {rid!r} any more")
        existing = next((e for e in (before if isinstance(before, list) else [])
                         if isinstance(e, dict) and e.get("item_id") == iid), None)
        hidden = (hidden_arg if hidden_arg is not None
                  else bool((existing or {}).get("hidden")))
        difficulty = (difficulty_arg if difficulty_arg is not None
                      else _stored_difficulty(existing))
        inverse = {"op": "restore_room_items", "location_id": lid, "room_id": rid,
                   "before": before}
        step.begin("location", lid, inverse)

        def reconcile():
            _r, now = room_items_now()
            return None if wu._norm(now) == wu._norm(before) else (lid, inverse, now)

        with step.writing(reconcile):
            if not add_item_to_room(lid, rid, iid, quantity=qty, hidden=hidden,
                                    discovery_difficulty=difficulty, note=note):
                raise ValueError(f"the room did not take {iid}")
        _r, written = room_items_now()
    entry = next((e for e in written or [] if isinstance(e, dict)
                  and e.get("item_id") == iid), {}) if not wu.is_absent(written) else {}
    changes = []
    if existing is not None:
        was_hidden = bool(existing.get("hidden"))
        if was_hidden != bool(entry.get("hidden")):
            changes.append("was hidden, now visible" if was_hidden
                           else "was visible, now hidden")
        if _stored_difficulty(existing) != _stored_difficulty(entry):
            changes.append(f"discovery_difficulty {_stored_difficulty(existing)} → "
                           f"{_stored_difficulty(entry)}")
    line = (f'placed {qty}× {iid} "{_short(item.get("name") or iid, 40)}" in room {rid} '
            f'"{room.get("name") or ""}" of {lid} (now {entry.get("quantity")}'
            + (", hidden" if entry.get("hidden") else "")
            + "".join(f"; {c}" for c in changes) + ")")
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


_LEAD_TOKEN = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _appearance_lead_error(key: str, field: Dict[str, Any], value: Any) -> Optional[str]:
    """If ``field`` declares a non-empty ``lead`` prefix and ``value`` is a
    non-empty string, require ``value`` to begin with that lead (case-
    insensitive after stripping) and contain every ``{token}`` in it.
    Returns a refusal message on mismatch, else None."""
    lead = str(field.get("lead") or "")
    if not lead.strip() or not isinstance(value, str) or not value.strip():
        return None
    norm_val = value.strip().lower()
    norm_lead = lead.strip().lower()
    tokens = _LEAD_TOKEN.findall(lead)
    if norm_val.startswith(norm_lead) and all(f"{{{t}}}".lower() in norm_val for t in tokens):
        return None
    if tokens:
        names = (tokens[0] if len(tokens) == 1
                 else ", ".join(tokens[:-1]) + f" and {tokens[-1]}")
        why = (f" — the server fills them from {names}; "
               f"never write {names} as words")
    else:
        why = ""
    example = lead + ("distinctive details, ..." if lead.endswith(" ")
                      else " distinctive details, ...")
    return f'{key} must start with the placeholders "{lead}"{why}. Example: "{example}"'


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
        err = _appearance_lead_error(key, field, value)
        if err:
            raise ToolRefusal(err)
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


def _on_base_pipeline(profile: Dict[str, Any], name: str = "") -> bool:
    """Whether a character with this profile is on the base-body pipeline
    (``base_body.is_base_pipeline``). ``name`` "" = a draft that is not
    stored yet (describe_template, create_character): the check then reads
    the profile only — no per-character config exists, and a temporary-NPC
    template is refused by those tools anyway."""
    from app.core import base_body
    return bool(base_body.is_base_pipeline(name, profile=profile))


def _mesh_part_switch(spec) -> Optional[str]:
    """The attribute that switches the slot's separately built mesh part, if
    the slot declares one."""
    return spec.mesh_part.switch if getattr(spec, "mesh_part", None) else None


def _body_specs(profile: Dict[str, Any],
                name: str = "") -> List[Tuple[Any, Dict[str, Dict[str, Any]]]]:
    """(spec, settable attributes) of every body slot that applies to a
    character with this profile and has at least one settable attribute —
    the package declarations (body_slots.slots_for_character), never a
    hard-coded slot list. Settable = what the character editor shows
    (``body_slots.editable_attributes``); a slot's mesh-part switch only for
    a character on the base-body pipeline: there a switch only marks the
    figure due (the run's Build builds it), off it the switch would start a
    mesh regeneration no journal row can take back. The schema, the check
    and the completeness gaps all read this one set. ``name`` is the stored
    character, "" for a draft (see :func:`_on_base_pipeline`)."""
    from app.core.body_slots import editable_attributes, slots_for_character
    specs = slots_for_character("", profile=profile)
    on_pipeline: Optional[bool] = None
    out = []
    for spec in specs:
        attrs = editable_attributes(spec)
        switch = _mesh_part_switch(spec)
        if switch in attrs:
            if on_pipeline is None:
                on_pipeline = _on_base_pipeline(profile, name)
            if not on_pipeline:
                attrs = {k: v for k, v in attrs.items() if k != switch}
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


def _check_body_slots(raw: Any, profile: Dict[str, Any], template: str,
                      name: str = "") -> Dict[str, Dict[str, str]]:
    """Validate a body_slots draft/patch against the slots that apply to a
    character with ``profile``; every invalid slot, attribute or value is
    REFUSED (before any write) instead of skipped. Returns the clean
    {slot: {attribute: value}} (values stripped). A mesh-part switch off the
    base-body pipeline gets its own refusal (it is no settable attribute
    there, see :func:`_body_specs`). ``name``: the stored character, ""
    for a draft."""
    if not isinstance(raw, dict):
        raise ToolRefusal("'body_slots' must be an object {slot: {attribute: value}}")
    specs = {spec.id: (spec, attrs) for spec, attrs in _body_specs(profile, name)}
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
        switch = _mesh_part_switch(spec)
        for key, value in values.items():
            decl = attrs.get(key)
            if decl is None and key == switch:
                # Before the generic refusal: off the pipeline the switch is
                # not in the settable set, and "cannot be set here" would not
                # say why.
                raise ToolRefusal(f"body_slots.{slot_id}.{key} switches a separately "
                                  "built part — only for a character on the "
                                  "base-body pipeline")
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
    """"slot.attribute" of every applicable, settable attribute of a stored
    character that has no value (attribute conditions that do not hold are
    left out)."""
    from app.models.character import get_character_profile
    prof = get_character_profile(name) or {}
    vals = prof.get("body_slots") if isinstance(prof.get("body_slots"), dict) else {}
    out = []
    for spec, attrs in _body_specs(prof, name):
        slot_vals = vals.get(spec.id) if isinstance(vals.get(spec.id), dict) else {}
        for key, decl in attrs.items():
            if _attr_applies(decl, slot_vals, prof) and not str(slot_vals.get(key) or "").strip():
                out.append(f"{spec.id}.{key}")
    return out


def _body_schema(prof: Dict[str, Any], name: str = "") -> List[str]:
    """One line per applicable slot: every settable attribute with its
    current value ("-" = unset) and what it takes. ``name``: the stored
    character, "" for a draft."""
    vals = prof.get("body_slots") if isinstance(prof.get("body_slots"), dict) else {}
    lines = []
    for spec, attrs in _body_specs(prof, name):
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


def _stored_known_ids(name: str) -> List[str]:
    """The character's known place ids as STORED (the str view of
    models.character.get_known_locations) — read through
    ``stored_known_locations``, never the defaulting config reader, which
    auto-creates a whole default config for an empty one (a write no
    journal row records)."""
    from app.models.character import stored_known_locations
    raw = stored_known_locations(name)[1]
    return [str(v) for v in raw if v] if isinstance(raw, list) else []


def _add_known_places(name: str, ids: List[str]) -> Tuple[List[str], List[str]]:
    """Add ids to the character's known places (add-only, stored order kept,
    the new ones appended in the order given) — the tool's own locked
    read-modify-write rather than models.character.add_known_location,
    because the journal needs exact bytes. Reads and writes ONLY the stored
    ``known_locations`` key (``character.stored_known_locations`` /
    ``write_known_locations``): the rest of the stored config, its absent
    defaults and ``updated_at`` stay as they are, so the undo
    (remove_known_places) gives back the same bytes. A failed save, or an id
    missing when read back, is a ValueError. Returns the stored list as read
    back and the ids this call added (those not known before, in the order
    given)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import stored_known_locations, write_known_locations
    with keyed_lock("character_profile", name):
        existing = stored_known_locations(name)[1]
        known = [str(v) for v in existing if v] if isinstance(existing, list) else []
        missing = [i for i in ids if i not in known]
        if missing:
            # Appended to the stored list AS IT IS (membership on the str
            # view): the undo removes exactly the added ids, so a normalised
            # copy would change entries the journal does not record.
            if not write_known_locations(name, (list(existing) if isinstance(existing, list)
                                                else []) + missing):
                raise ValueError(f"the known places of {name} were not stored")
        stored = _stored_known_ids(name)
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
        lead = str(field.get("lead") or "")
        if lead.strip():
            return f'text, starts with "{lead}"'
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
       "new character (the fields of its character template, plus outfits); home = a place id or name; "
       "known_places = further places it may travel to")
def _create_character(step: _Step, args: Dict[str, Any]) -> str:
    from app.core.character_name import validate_character_name
    from app.core.body_slots import editable_attributes
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
    # Only the templates character_templates() offers.
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
                                 place_compliance=False,
                                 body_attributes=editable_attributes)
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


def _soul_norm(text: str) -> str:
    """A soul section's text with its line ends made one kind (CRLF / CR ->
    LF) and its trailing whitespace dropped: what update_character compares
    to tell a real change from a rewrite that would only touch line ends,
    the final newline or trailing spaces."""
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip()


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
                                      save_character_profile, stored_known_locations)
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
        body_clean = _check_body_slots(body_raw, would_be, template, name)
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
        # Before and after are the RAW file text (soul_writer.read_raw), so
        # the undo puts back the very bytes (a CRLF file stays CRLF, a file
        # without a final newline keeps none). A text that differs from the
        # stored one only in its line ends is no change the agent asked for:
        # it is neither written nor journaled.
        for rel, text in soul_patch.items():
            path = soul_writer.soul_text_path(name, rel)
            with keyed_lock("soul_file", str(path)):
                before_text = soul_writer.read_raw(name, rel)
                new_text = text.rstrip() + "\n"
                if (before_text is not None
                        and _soul_norm(before_text) == _soul_norm(new_text)):
                    lines.append(f"soul {rel} unchanged")
                    continue
                sstep = group_step()
                inverse = {"op": "restore_soul", "name": name, "file_id": rel,
                           "before_text": before_text}
                sstep.begin("character", name, inverse)

                def reconcile_soul(rel=rel, before_text=before_text, inverse=inverse):
                    now = soul_writer.read_raw(name, rel)
                    return None if now == before_text else (name, inverse, now)

                with sstep.writing(reconcile_soul):
                    soul_writer.write_raw(name, rel, new_text)
                written = soul_writer.read_raw(name, rel)
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

            def push_profile(bp, wp):
                # Inside the keyed_lock("character_profile") taken above,
                # right after the journaled write (D12): a later group's
                # refusal or exception cannot drop it. Profile keys only —
                # config is no sync topic (D9).
                if bp:
                    from app.core import sync_topics
                    sync_topics.profile_patched(name, wu.absent_as_none(bp),
                                                wu.absent_as_none(wp))

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
                    cfg_stored = False
                    try:
                        new_cfg = copy.deepcopy(get_character_config(name) or {})
                        new_cfg.update(cfg_patch)
                        cfg_stored = bool(save_character_config(name, new_cfg))
                    finally:
                        if not cfg_stored:
                            # The profile half may be stored and reconcile_char
                            # journals it: its push must not be dropped, whether
                            # the config save returned False or raised.
                            bp, wp, _bc, _wc = diff_now()
                            push_profile(bp, wp)
                    if not cfg_stored:
                        raise ValueError(f"the config of {name} was not stored")
            bp, wp, bc, wc = diff_now()
            cstep.attach(name, {"op": "restore_character", "name": name,
                                "profile": bp, "config": bc})
            changed = ([f"profile {k}" for k in sorted(bp)]
                       + [f"config {k}" for k in sorted(bc)])
            cline = ", ".join(changed) if changed else "fields unchanged"
            cstep.complete({"profile": wp, "config": wc}, cline)
            push_profile(bp, wp)
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
            # (add_known_location — locked like this step, so never between
            # its read and its write, but at any time between this turn and
            # the undo) extends the list, so a whole-list restore would make
            # the undo "changed since". The
            # inverse removes exactly the places this call added. Still under
            # the keyed_lock("character_profile") taken above.
            kstep = group_step()
            k_raw = stored_known_locations(name)[1]
            k_had_key = isinstance(k_raw, list)
            k_known = [str(v) for v in k_raw if v] if k_had_key else []
            k_missing = [i for i in known_ids if i not in k_known]

            def known_inverse(added: List[str]) -> Dict[str, Any]:
                return {"op": "remove_known_places", "name": name,
                        "ids": list(added), "had_key": k_had_key}

            def added_now() -> List[str]:
                now = _stored_known_ids(name)
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


# ── Forms of address ─────────────────────────────────────────────────────

@_tool("set_address", True, "set_address{speaker, addressee, text}",
       "how speaker addresses addressee — ONE direction, one line of at most "
       "120 characters (\"calls him Master\"); \"\" clears it")
def _set_address(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 3 (E11). The writer (``relationship.set_address``) strips
    and validates the text: every value it would rewrite is refused here, so
    the stored text is the sent one. A linked body's direction lands on its
    mind (the writer's rule; the line says "stored on <mind>"). A stored
    value the writer would refuse or rewrite is refused up front (no exact
    inverse). The writer fills the reader's defaults (id, history,
    strength, ...) into a sparse row that existed; the inverse therefore
    carries that row's raw columns (``raw``) and the undo writes them back
    (a pending step too: the inverse carries the sent ``text`` and the
    existing row's id up front).
    The writer has no lock of its own; the run freezes the world (accepted
    residual).
    Inverse ``restore_address`` (world_dev_undo)."""
    from app.core.linked_characters import family_of, mind_of
    from app.models import relationship as rel
    from app.models.character import character_row_exists
    _only_keys(args, {"speaker", "addressee", "text"}, "set_address")
    speaker = _str(args, "speaker", required=True)
    addressee = _str(args, "addressee", required=True)
    for who in (speaker, addressee):
        if not character_row_exists(who):
            raise ToolRefusal(f"no character {who!r} — use find_characters")
    if speaker.lower() == addressee.lower():
        raise ToolRefusal("speaker and addressee are the same character")
    if addressee.lower() in {m.lower() for m in family_of(speaker)}:
        raise ToolRefusal(f"{speaker} and {addressee} are one linked family (one "
                          "mind) — there is no form of address between them")
    text = args.get("text")
    if not isinstance(text, str):
        raise ToolRefusal("'text' is required (a string; \"\" clears the form of "
                          "address)")
    try:
        clean = rel.clean_address(text)
    except rel.AddressTextError as exc:
        raise ToolRefusal(str(exc)) from None
    if clean != text:
        raise ToolRefusal("the text would be stored as "
                          + json.dumps(clean, ensure_ascii=False)
                          + " — send it exactly that way")
    mind = mind_of(speaker)
    key = rel.address_key(mind, addressee)
    pair = rel.pair_key(mind, addressee)
    before_row = rel.pair_row(mind, addressee)
    stored = before_row.get(key, "") if before_row is not None else ""
    if stored not in ("", None):
        # The undo puts the key back through the same writer: a stored value
        # the writer would refuse or rewrite (a hand-edited or foreign row)
        # has no exact inverse.
        try:
            stored_ok = rel.clean_address(stored) == stored
        except rel.AddressTextError:
            stored_ok = False
        if not stored_ok:
            raise ToolRefusal(f"the stored form of address of {speaker} toward "
                              f"{addressee} ({json.dumps(stored, ensure_ascii=False)}) "
                              "is not a valid one-line text — it cannot be restored "
                              "exactly; fix it in Game-Admin → Characters → Relationships")
    if stored == text:
        raise ToolRefusal(f"already set: {speaker} addresses {addressee} "
                          + (json.dumps(text, ensure_ascii=False) if text
                             else "without a form of address"))
    step.prepare()
    before = (before_row.get(key, wu.ABSENT) if before_row is not None
              else wu.ABSENT)
    inverse = {"op": "restore_address", "speaker": mind, "addressee": addressee,
               "pair": pair, "key": key, "before": before, "text": text,
               "row_created": before_row is None,
               # A row that existed keeps its id; a created one gets it at
               # attach / reconcile.
               "row_id": (before_row.get("_db_id") if before_row is not None
                          else None),
               # The stored columns of a row that existed: the writer merges
               # the reader's defaults into a sparse row, the undo writes
               # these back.
               "raw": (rel.raw_pair_row(int(before_row["_db_id"]))
                       if before_row is not None else None)}
    step.begin("relationship", pair, inverse)

    def written_of(row: Dict[str, Any]) -> Dict[str, Any]:
        return {"value": row.get(key, wu.ABSENT), "row": row}

    def reconcile():
        row = rel.pair_row(mind, addressee)
        if row is None or (before_row is not None
                           and wu._norm(row) == wu._norm(before_row)):
            return None
        return pair, {**inverse, "row_id": row.get("_db_id")}, written_of(row)

    with step.writing(reconcile):
        # The ORIGINAL speaker: the writer marks a leader row a body
        # created as ``mind_only``.
        if not rel.set_address(speaker, addressee, text):
            raise ToolRefusal("the form of address was not stored")
    row = rel.pair_row(mind, addressee)
    if row is None:
        raise RuntimeError(f"set_address stored no row for {pair}")
    inverse["row_id"] = row.get("_db_id")
    step.attach(pair, inverse)
    line = (f"{speaker} addresses {addressee}: "
            + (json.dumps(text, ensure_ascii=False) if text
               else "form of address cleared")
            + (f" (stored on {mind})" if mind != speaker else ""))
    step.complete(written_of(row), line)
    return line


def _address_lines(name: str) -> List[str]:
    """``<a> → <b>: "<text>"`` per pair of *name* with a direction set (both
    directions, the mind's rows included for a linked body)."""
    from app.core.linked_characters import family_of, mind_of
    from app.models.relationship import get_address, get_character_relationships
    family = {m.lower() for m in family_of(name)}
    others: List[str] = []
    for who in {name, mind_of(name)}:
        for r in get_character_relationships(who):
            for other in (str(r.get("character_a") or ""), str(r.get("character_b") or "")):
                if other and other.lower() not in family and other not in others:
                    others.append(other)
    out: List[str] = []
    for other in sorted(others, key=str.lower):
        for a, b in ((name, other), (other, name)):
            text = get_address(a, b)
            if text:
                out.append(f"{a} → {b}: " + json.dumps(text, ensure_ascii=False))
    return out


# ── Secrets ──────────────────────────────────────────────────────────────

#: Longest secret text and consequence text the builder may send (E12: a
#: prompt block, not a novel).
MAX_SECRET_CHARS = 1000
MAX_SECRET_CONSEQUENCE_CHARS = 500


def _secret_names(args: Dict[str, Any], key: str, owner: str,
                  family: set) -> List[str]:
    """A list of existing character names other than the owner's family,
    no duplicates — refused otherwise (nothing is rewritten)."""
    from app.models.character import character_row_exists
    value = args.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
        raise ToolRefusal(f"'{key}' must be a list of character names")
    seen: set = set()
    for n in value:
        if not n or n != n.strip():
            raise ToolRefusal(f"'{key}': {n!r} is no character name (no empty names, no "
                              "leading or trailing blanks)")
        if n.lower() in seen:
            raise ToolRefusal(f"'{key}' names {n} twice")
        seen.add(n.lower())
        if not character_row_exists(n):
            raise ToolRefusal(f"'{key}': no character {n!r} — use find_characters")
        if n.lower() in family:
            raise ToolRefusal(f"'{key}': {n} is {owner} or one of its linked family — "
                              "the keeper of a secret is never listed there")
    return list(value)


@_tool("add_secret", True,
       "add_secret{name, content, category?, severity?, known_by?, related_characters?, "
       "related_location?, consequences?}",
       "a secret the character keeps (categories and severities: list_catalog "
       "secret_categories)")
def _add_secret(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 4 (E12). The writer (``secrets.add_secret``) clamps the
    severity, rewrites an unknown category, strips the texts and stores the
    knowers as minds: every value it would rewrite is refused here, so the
    stored secret is the sent one. The secret is stored under the owner's
    MIND (a linked body is recorded as its ``body``). Inverse
    ``delete_secret{owner (the mind), id}`` (world_dev_undo); delete_created
    removes one only in the same turn (E2). Accepted residual (like the rules layer's
    ``save_rules``): the writer (``secrets._save_secrets``) re-serialises
    every secret of the mind on each add and delete, so a FOREIGN legacy or
    sparse secret row of the same mind may come back with the reader's
    defaults filled in (meta ``id``, ``category``, ``severity``,
    ``known_by``/``discovered_by``, ...; ``visibility`` rewritten) — same
    meaning; byte-for-byte holds for the run's own row. The admin's own add
    and delete do the same today."""
    from app.core.keyed_lock import keyed_lock
    from app.core.linked_characters import family_of, mind_of
    from app.models import secrets as sec
    from app.models.character import character_row_exists
    from app.models.world import get_location_by_id
    allowed = {"name", "content", "category", "severity", "known_by",
               "related_characters", "related_location", "consequences"}
    _only_keys(args, allowed, "add_secret")
    name = _str(args, "name", required=True)
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ToolRefusal("'content' is required (the secret, a non-empty string)")
    if content != content.strip():
        raise ToolRefusal("'content' must not start or end with blanks (it would be "
                          "stored stripped)")
    if len(content) > MAX_SECRET_CHARS:
        raise ToolRefusal(f"'content' is {len(content)} characters — at most "
                          f"{MAX_SECRET_CHARS}")
    category = args.get("category", "personal")
    if category not in sec.VALID_CATEGORIES:
        raise ToolRefusal(f"'category' {category!r} is none of: "
                          + ", ".join(sec.VALID_CATEGORIES))
    severity = args.get("severity", 2)
    if (isinstance(severity, bool) or not isinstance(severity, int)
            or severity not in sec.SEVERITY_LABELS):
        raise ToolRefusal("'severity' must be a whole number "
                          + ", ".join(f"{k} ({v})" for k, v in sorted(sec.SEVERITY_LABELS.items())))
    family = {m.lower() for m in family_of(name)} | {name.lower()}
    known_by = _secret_names(args, "known_by", name, family)
    for n in known_by:
        if mind_of(n) != n:
            raise ToolRefusal(f"'known_by': name the leader {mind_of(n)} instead of {n} — "
                              "a body knows what its leader knows")
    related = _secret_names(args, "related_characters", name, family)
    related_location = args.get("related_location")
    if related_location is not None:
        if not isinstance(related_location, str) or not related_location.strip():
            raise ToolRefusal("'related_location' must be a location id")
        if get_location_by_id(related_location) is None:
            raise ToolRefusal(f"'related_location': no location {related_location!r} — "
                              "use find_locations")
    consequences = args.get("consequences", "")
    if not isinstance(consequences, str):
        raise ToolRefusal("'consequences' must be a string")
    if consequences != consequences.strip():
        raise ToolRefusal("'consequences' must not start or end with blanks (it would be "
                          "stored stripped)")
    if len(consequences) > MAX_SECRET_CONSEQUENCE_CHARS:
        raise ToolRefusal(f"'consequences' is {len(consequences)} characters — at most "
                          f"{MAX_SECRET_CONSEQUENCE_CHARS}")
    mind = mind_of(name)
    # A strict read before prepare: a broken stored row of the mind is a
    # clear refusal here, not an error after the step was prepared.
    try:
        sec.list_secrets(mind, strict=True)
    except Exception as exc:
        raise ToolRefusal(f"a stored secret of {mind} cannot be read ({exc}) — "
                          "fix or delete that row in Game-Admin first") from exc
    step.prepare()
    # The writer's own lock (re-entrant): nothing foreign lands between the
    # id read, the write and the reconcile.
    with keyed_lock("secrets", mind):
        ids_before = {str(s.get("id")) for s in sec.list_secrets(mind, strict=True)}
        step.begin("secret", None, None)

        def new_row() -> Optional[Dict[str, Any]]:
            return next((s for s in sec.list_secrets(mind, strict=True)
                         if str(s.get("id")) not in ids_before
                         and s.get("content") == content), None)

        def reconcile():
            row = new_row()
            if row is None:
                return None
            sid_ = str(row.get("id"))
            return sid_, {"op": "delete_secret", "owner": mind, "id": sid_}, row

        with step.writing(reconcile):
            made = sec.add_secret(name, content, category=category, severity=severity,
                                  related_characters=related or None,
                                  related_location=related_location,
                                  consequences_if_revealed=consequences,
                                  source="manual", known_by=known_by or None)
            sid = str(made.get("id") or "")
            # The writer logs and swallows a failed save: read it back.
            if not sid or sec.get_secret(mind, sid) is None:
                raise RuntimeError("the secret was not stored")
        inverse = {"op": "delete_secret", "owner": mind, "id": sid}
        step.attach(sid, inverse)
        row = sec.get_secret(mind, sid)
    line = (f"added secret {sid} of {name} ({category}, severity {severity} "
            f"{sec.SEVERITY_LABELS[severity]}), known by "
            + (", ".join(known_by) or "nobody")
            + (f" (stored on {mind})" if mind != name else ""))
    step.complete(row, line)
    return line


def _secret_lines(name: str) -> List[str]:
    """``<id> <category>/<severity>: <content> — known by …`` per secret of
    *name*'s mind."""
    from app.models.secrets import list_secrets
    out = []
    for s in list_secrets(name):
        out.append(f"{s.get('id')} {s.get('category')}/{s.get('severity')}: "
                   + _short(s.get("content"), 80) + " — known by "
                   + (", ".join(str(k) for k in s.get("known_by") or []) or "nobody"))
    return out


def _secret_refs(secret_rows: List[Dict[str, Any]]) -> List[str]:
    """``secret <id> of <owner>`` (+ why) per row of
    ``secrets.secrets_naming``."""
    return [f"secret {r['secret'].get('id')} of {r['owner']}"
            + (f" ({', '.join(w for w in r['why'] if w != 'location')})"
               if any(w != "location" for w in r["why"]) else "")
            for r in secret_rows]


def _references_to_character(name: str) -> List[str]:
    """What still names *name* outside its own rows (which delete_character
    removes with it and a re-creation brings back): secrets of OTHER minds
    that list it as a knower or a related character. Both delete_created
    paths refuse while any is left — never a dangling reference. Deliberately
    not in ``_character_delete_blockers`` (the same-turn path never calls
    those). World rules whose ``character`` is it or whose condition names
    it (``rule <id> "<name>"``) are listed too. A read error of either
    refuses the delete (``_naming_refs``)."""
    from app.models import rules as rules_mod, secrets as secrets_mod
    return (_secret_refs([r for r in _naming_refs(secrets_mod.secrets_naming, "secrets", name=name)
                          if r["owner"] != name])
            + _rule_refs(_naming_refs(rules_mod.rules_naming, "world rules", character=name)))


def _naming_refs(fn: Callable[..., List[Dict[str, Any]]], label: str,
                 **kw: Any) -> List[Dict[str, Any]]:
    """The rows of a strict "who names it" reader (``rules.rules_naming``,
    ``secrets.secrets_naming``), called with *kw*. Any exception — a broken
    rules layer (``RuleWriteError``), a locked table — refuses the delete,
    like ``_event_refs``: a read error is never read as "nothing names it".
    The callers run before the first write, so a refusal leaves only a
    ``refused`` journal row."""
    try:
        return fn(**kw)
    except Exception as e:
        raise ToolRefusal(f"the {label} could not be read ({e}) — nothing was deleted") from e


# ── Access rules ─────────────────────────────────────────────────────────

#: Longest rule name and block message the builder may send (plan p3 Task 5).
MAX_RULE_NAME_CHARS = 80
MAX_RULE_MESSAGE_CHARS = 200
#: The directions an access block guards (``rules.rule_action``).
RULE_ACTIONS = ("enter", "leave")


def _rule_rooms_arg(args: Dict[str, Any], loc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The ``rooms`` argument resolved to rooms of *loc* (an id, or a name
    when exactly one room carries it). Unknown, ambiguous or repeated rooms
    are refused, listing the place's rooms."""
    value = args.get("rooms")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolRefusal("'rooms' must be a list of room ids or names")
    real = _real_rooms(loc)
    listing = ", ".join(f'{r.get("name") or "?"} ({r.get("id")})' for r in real) or "none"
    out: List[Dict[str, Any]] = []
    for ident in value:
        room = next((r for r in real if r.get("id") == ident), None)
        if room is None:
            named = [r for r in real if r.get("name") == ident]
            if len(named) > 1:
                raise ToolRefusal(f"{len(named)} rooms of {loc.get('id')} are named {ident!r} — "
                                  f"use the id; rooms: {listing}")
            room = named[0] if named else None
        if room is None:
            raise ToolRefusal(f"no room {ident!r} in {loc.get('id')} — rooms: {listing}")
        if any(r.get("id") == room.get("id") for r in out):
            raise ToolRefusal(f"'rooms' names {room.get('name') or room.get('id')} twice")
        out.append(room)
    return out


def _rule_condition_arg(args: Dict[str, Any]) -> str:
    """The required condition, checked by the editor's own validators: a
    grammar issue or an unresolved reference refuses (a rule without a
    condition never blocks — check_access only blocks when it passes). It is
    stored exactly as sent; surrounding blanks refuse instead of being
    stripped."""
    from app.core.activity_engine import (validate_condition_expression,
                                          validate_condition_references)
    condition = args.get("condition")
    if not isinstance(condition, str) or not condition.strip():
        raise ToolRefusal("'condition' is required — a block without a condition never "
                          "bites (read_manual systems lists the condition grammar)")
    if condition != condition.strip():
        # Stored as sent, like the other text fields of the plan (secret
        # content, address text): nothing is rewritten.
        raise ToolRefusal("'condition' must not start or end with blanks")
    issues = validate_condition_expression(condition)
    if issues:
        raise ToolRefusal("'condition': " + "; ".join(i.message for i in issues)
                          + " — read_manual systems lists the condition grammar")
    warnings = validate_condition_references(condition)
    if warnings:
        raise ToolRefusal("'condition': " + "; ".join(warnings))
    return condition


@_tool("add_block_rule", True,
       "add_block_rule{name, message, location_id, rooms?, action?, condition, character?}",
       "an access rule: blocks entering (or leaving) a place or some of its rooms while "
       "the condition holds (read_manual systems first)")
def _add_block_rule(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 5 (E8). A world-layer block rule in the RulesTab shape
    (``target: {scope: "location", location, action, rooms?}``), written by
    ``rules.add_rule(target_dir="world")`` under ``rules.layer_lock()``
    (re-entrant; the id choice, the write and the read-back see no foreign
    rule write). Inverse ``delete_rule{id}`` (world_dev_undo); delete_created
    removes one only in the same turn (E2). Accepted residual (plan Review
    focus 1): ``save_rules`` re-serialises every world rule on each add and
    delete, so a FOREIGN legacy row may come back normalised (``id`` set,
    ``message``/``type`` filled from the columns) — same meaning;
    byte-for-byte holds for the run's own row and rows written by add_rule."""
    from app.models import rules as rules_mod
    from app.models.character import character_row_exists
    allowed = {"name", "message", "location_id", "rooms", "action", "condition", "character"}
    _only_keys(args, allowed, "add_block_rule")
    name = _str(args, "name", required=True)
    if len(name) > MAX_RULE_NAME_CHARS:
        raise ToolRefusal(f"'name' is {len(name)} characters — at most {MAX_RULE_NAME_CHARS}")
    message = _str(args, "message", required=True)
    if len(message) > MAX_RULE_MESSAGE_CHARS:
        raise ToolRefusal(f"'message' is {len(message)} characters — at most "
                          f"{MAX_RULE_MESSAGE_CHARS}")
    loc = _resolve_location(_str(args, "location_id", required=True))
    loc_id = str(loc.get("id") or "")
    rooms = _rule_rooms_arg(args, loc)
    action = _str(args, "action") or "enter"
    if action not in RULE_ACTIONS:
        raise ToolRefusal(f"'action' {action!r} is none of: " + ", ".join(RULE_ACTIONS))
    condition = _rule_condition_arg(args)
    character = _str(args, "character")
    if character is not None:
        if not character or not character_row_exists(character):
            raise ToolRefusal(f"'character': no character {character!r} — use find_characters")
    target: Dict[str, Any] = {"scope": "location", "location": loc_id, "action": action}
    if rooms:
        target["rooms"] = [str(r.get("id")) for r in rooms]
    # A strict read before prepare: a broken stored layer is a clear refusal
    # here, not an error after the step was prepared.
    try:
        rules_mod.load_rules(strict=True)
    except Exception as exc:
        raise ToolRefusal(f"the stored rules cannot be read ({exc}) — fix that in "
                          "Game-Admin → Rules first") from exc
    step.prepare()
    with rules_mod.layer_lock():
        taken = {str(r.get("id") or "") for r in rules_mod.load_rules(strict=True)}
        rid = f"wdrule_{secrets.token_hex(4)}"
        while rid in taken:
            rid = f"wdrule_{secrets.token_hex(4)}"
        rule: Dict[str, Any] = {"id": rid, "name": name, "type": "block", "target": target,
                                "condition": condition, "message": message}
        if character:
            rule["character"] = character
        inverse = {"op": "delete_rule", "id": rid}
        step.begin("rule", rid, inverse)

        def reconcile():
            row_ = rules_mod.world_rule(rid)
            return None if row_ is None else (rid, inverse, row_)

        with step.writing(reconcile):
            rules_mod.add_rule(copy.deepcopy(rule), target_dir="world")
            if rules_mod.world_rule(rid) is None:
                raise RuntimeError("the rule was not stored")
        row = rules_mod.world_rule(rid)
    place = f'"{loc.get("name") or loc_id}" ({loc_id})'
    if rooms:
        place += " / " + ", ".join(str(r.get("name") or r.get("id")) for r in rooms)
    line = (f'added rule {rid} "{name}": blocks {action} of {place} when {condition}'
            + (f" (only for {character})" if character else ""))
    if rooms and len(rooms) == len(_real_rooms(loc)):
        line += (" — note: this names every room, but corridors and grounds stay open; "
                 "omit 'rooms' to block the whole place")
    step.complete(row, line)
    return line


def _rule_refs(rule_rows: List[Dict[str, Any]]) -> List[str]:
    """``rule <id> "<name>"`` per row of ``rules.rules_naming``."""
    return [f'rule {r.get("id")} "{r.get("name") or ""}"' for r in rule_rows]


# ── World events ─────────────────────────────────────────────────────────

#: Longest event text the builder may send, and the longest lifetime in GAME
#: hours (plan p3 E10: 720 = 30 game days; 0 = never expires, the writer's rule).
MAX_EVENT_CHARS = 500
MAX_EVENT_TTL_HOURS = 720


@_tool("add_event", True, "add_event{text, location_id?, category?, ttl_hours?}",
       "a one-off happening at a place (or everywhere without location_id); lasts "
       "ttl_hours GAME hours (categories: list_catalog event_categories)")
def _add_event(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 6 (E10). One event through ``events.add_event`` (the
    writer the admin route calls). The writer strips the text and stores any
    category string: every value it would rewrite is refused here, so the
    stored event is the sent one. Inverse ``delete_event{id}``
    (world_dev_undo); delete_created removes one only in the same turn (E2) —
    the writer stamps a new id and created_at, so no exact re-creation exists."""
    from app.models import events as ev
    from app.models.world import get_location_by_id
    _only_keys(args, {"text", "location_id", "category", "ttl_hours"}, "add_event")
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ToolRefusal("'text' is required (the happening, a non-empty string)")
    if text != text.strip():
        raise ToolRefusal("'text' must not start or end with blanks (it would be stored "
                          "stripped)")
    if len(text) > MAX_EVENT_CHARS:
        raise ToolRefusal(f"'text' is {len(text)} characters — at most {MAX_EVENT_CHARS}")
    loc_id = args.get("location_id")
    loc: Optional[Dict[str, Any]] = None
    if loc_id is not None:
        if not isinstance(loc_id, str) or not loc_id.strip():
            raise ToolRefusal("'location_id' must be a location id (leave it out for an "
                              "event everywhere)")
        loc = get_location_by_id(loc_id)
        if loc is None:
            raise ToolRefusal(f"no location {loc_id!r} — use find_locations")
    category = args.get("category")
    if category is None:
        category = ""
    cats = _event_categories()
    if not isinstance(category, str) or (category and category not in cats):
        raise ToolRefusal(f"'category' {category!r} is none of: " + ", ".join(cats)
                          + " (or leave it out)")
    ttl = args.get("ttl_hours")
    if ttl is None:
        ttl = ev.DEFAULT_TTL_HOURS
    elif not _whole_in(ttl, 0, MAX_EVENT_TTL_HOURS):
        raise ToolRefusal(f"'ttl_hours' must be a whole number of GAME hours 0…"
                          f"{MAX_EVENT_TTL_HOURS} (0 = never expires)")
    ttl = int(ttl)
    step.prepare()
    ids_before = {str(e.get("id")) for e in ev.get_all_events()}
    step.begin("event", None, None)

    def new_row() -> Optional[Dict[str, Any]]:
        return next((e for e in ev.get_all_events()
                     if str(e.get("id")) not in ids_before and e.get("text") == text), None)

    def reconcile():
        row_ = new_row()
        if row_ is None:
            return None
        eid_ = str(row_.get("id"))
        return eid_, {"op": "delete_event", "id": eid_}, row_

    with step.writing(reconcile):
        made = ev.add_event(text, location_id=loc_id, ttl_hours=ttl, category=category)
        eid = str(made.get("id") or "")
        # The writer logs and swallows a failed insert: read it back.
        if not eid or ev.get_event(eid) is None:
            raise RuntimeError("the event was not stored")
    step.attach(eid, {"op": "delete_event", "id": eid})
    row = ev.get_event(eid)
    place = f'"{loc.get("name") or loc_id}" ({loc_id})' if loc else "everywhere"
    life = (f"{ttl} game hour{'s' if ttl != 1 else ''}" if ttl
            else "never expires")
    line = (f"added event {eid} at {place} ({category or 'uncategorized'}, {life}): "
            f'"{_short(text, 80)}"')
    step.complete(row, line)
    return line


def _event_refs(loc_id: str) -> List[str]:
    """``event <id>`` per active event whose place is loc_id.

    Only ACTIVE events count (``get_all_events``): an expired event the
    periodic cleanup has not removed yet no longer blocks the delete and keeps
    naming the deleted place until the cleanup runs. That is harmless — the
    event is invisible, and undo still removes the run's own event. A read
    error refuses the delete (``get_all_events_strict`` raises; never read
    as "no events")."""
    from app.models.events import get_all_events_strict
    try:
        events = get_all_events_strict()
    except Exception as e:
        raise ToolRefusal(f"the events could not be read ({e}) — the place stays") from e
    return [f"event {e.get('id')}" for e in events
            if str(e.get("location_id") or "") == loc_id]


# ── Quest templates ──────────────────────────────────────────────────────

#: The largest template the builder may send, as serialized JSON (the admin
#: route's body cap, routes/quests._MAX_BODY_BYTES: a template is copied into
#: every run's snapshot).
MAX_QUEST_TEMPLATE_BYTES = 256 * 1024
#: Authoring issue codes that refuse ``create_quest_template`` anywhere in the
#: template: target/effect-key reference errors (``unknown_target``,
#: ``wrong_kind``, ``not_yet_created``). In addition, ``_quest_issue_blocks``
#: refuses any issue inside an effect list (``setup_effects``,
#: ``steps[].on_done``, ``rewards``) or on ``giver_role``; every other issue
#: stays a warning on the stored draft.
_QUEST_BLOCKING_CODES = ("unknown_target", "wrong_kind", "not_yet_created")
#: Matches issue paths inside a step's ``on_done`` effect list.
_QUEST_ON_DONE_RE = re.compile(r"^steps\.\d+\.on_done")


def _quest_issue_blocks(issue: Dict[str, str]) -> bool:
    """Whether an authoring issue from ``validate_template`` refuses
    ``create_quest_template`` instead of staying a warning on the stored draft.

    Refuses: any issue inside an effect list (``setup_effects``,
    ``steps[].on_done``, ``rewards``), any ``giver_role`` issue, and anywhere
    in the template a target/effect-key reference error (codes
    ``unknown_target``, ``wrong_kind``, ``not_yet_created``). Every other issue
    stays a warning on the stored draft.
    """
    path = str(issue.get("path") or "")
    if (path == "giver_role"
            or path.startswith("setup_effects")
            or path.startswith("rewards")
            or _QUEST_ON_DONE_RE.match(path) is not None):
        return True
    return str(issue.get("code") or "") in _QUEST_BLOCKING_CODES


@_tool("create_quest_template", True,
       "create_quest_template{title, summary?, gm_notes?, giver_role?, roles?, steps?, "
       "start_condition?, prerequisites?, setup_effects?, rewards?, time_limit_s?}",
       "a DRAFT quest template (roles instead of fixed characters/places, steps as catalog "
       "conditions, setup_effects / steps[].on_done / rewards as effect lists — list_catalog "
       "quest_types / quest_roles); the admin readies it")
def _create_quest_template(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 7 (E9) + quest stage 2 Task 13. One draft template through
    ``quests.create_template(origin="admin", state="draft")`` (the writer the
    admin route calls). The field check is the route's own
    (``quest_engine.check_template_fields``); every value the writer would
    rewrite (a non-container roles/steps/conditions/effects) is refused, so the
    stored template is the sent one. ``_quest_issue_blocks`` refuses the call
    before anything is stored for any issue inside an effect list
    (``setup_effects``, ``steps[].on_done``, ``rewards``), any ``giver_role``
    issue, or a target/effect-key reference error (codes ``unknown_target``,
    ``wrong_kind``, ``not_yet_created``) anywhere in the template; every other
    authoring issue (``validate_template``) stays a warning on the stored draft.
    Inverse ``delete_quest_template{id}`` (world_dev_undo); delete_created
    removes one only in the same turn (E2) — the writer mints a new id and
    created_at, so no exact re-creation exists."""
    from app.core import quest_engine
    from app.models import quests
    _only_keys(args, set(quests.TEMPLATE_CONTENT_KEYS), "create_quest_template")
    msg = quest_engine.check_template_fields(args)
    if msg:
        raise ToolRefusal(msg)
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ToolRefusal("'title' is required (the quest's name, a non-empty string)")
    for key, kind in quests.TEMPLATE_CONTAINERS.items():
        if key in args and not isinstance(args[key], kind):
            raise ToolRefusal(f"'{key}' must be {'a list' if kind is list else 'an object'} "
                              "(leave it out for none)")
    size = len(json.dumps(args, ensure_ascii=False).encode("utf-8"))
    if size > MAX_QUEST_TEMPLATE_BYTES:
        raise ToolRefusal(f"the template is {size // 1024} KiB — at most "
                          f"{MAX_QUEST_TEMPLATE_BYTES // 1024} KiB")
    fields = {k: copy.deepcopy(args[k]) for k in quests.TEMPLATE_CONTENT_KEYS if k in args}
    blocking = [f"{i.get('path')}: {i.get('message')}"
                for i in quest_engine.validate_template(fields)
                if _quest_issue_blocks(i)]
    if blocking:
        prefix = "the quest template has errors to fix — nothing was stored: "
        raise ToolRefusal(prefix + "; ".join(
            _cap_lines(blocking, "fix these and send the template again", used=len(prefix))))
    step.prepare()
    ids_before = {str(t.get("id")) for t in quests.list_templates()}
    step.begin("quest_template", None, None)

    def reconcile():
        row_ = next((t for t in quests.list_templates()
                     if str(t.get("id")) not in ids_before and t.get("title") == title), None)
        if row_ is None:
            return None
        qid_ = str(row_.get("id"))
        return qid_, {"op": "delete_quest_template", "id": qid_}, row_

    with step.writing(reconcile):
        made = quests.create_template(**fields, origin="admin", state="draft")
        qid = str((made or {}).get("id") or "")
        if not qid or quests.get_template(qid) is None:
            raise RuntimeError("the quest template was not stored")
    step.attach(qid, {"op": "delete_quest_template", "id": qid})
    row = quests.get_template(qid)
    roles = fields.get("roles") or []
    steps = fields.get("steps") or []
    line = (f'created draft quest template {qid} "{_short(title, 80)}" '
            f"({_plural(len(roles), 'role')}, {_plural(len(steps), 'step')})")
    issues = [f"{i.get('path')}: {i.get('message')}"
              for i in quest_engine.validate_template(row or {})]
    if issues:
        line += "; issues: " + "; ".join(
            _cap_lines(issues, "the admin sees all of them in Game-Admin → Quests",
                       used=len(line)))
    step.complete(row, line)
    return line


# ── Placing a character (setup placement, E5) ───────────────────────────

#: What the refusals of a runtime state say the builder can do.
_PLACE_STATE_HINT = " — end it in Game-Admin first, or leave the placement open"


def _in_furniture_action(name: str) -> bool:
    """Whether a live furniture action (prop action run) holds the character."""
    try:
        from app.core import prop_action_store as store
    except ImportError:
        return False
    return any(name in store.people(r) for r in store.live_runs())


def _placement_state_refusal(name: str, prof: Dict[str, Any]) -> Optional[str]:
    """Why a runtime state of the character forbids a setup placement now, or
    None. Every state here can change while the tool runs (other code sets
    it), so place_character asks twice: up front and again under the profile
    lock right before the write. Sleep, forbidden slots and location-reset
    flags are state an arrival would clear (save_character_current_location),
    which a setup placement must not leave stale; the flags come from the
    package declarations (registry.flag_specs), no flag name is known here."""
    from app.core.interaction_engine import get_interaction
    from app.core.party_engine import is_in_party
    from app.models.character import OFFMAP_SLEEP_SENTINEL, is_character_sleeping
    from app.plugins import registry
    if str(prof.get("current_location") or "") == OFFMAP_SLEEP_SENTINEL:
        return f"{name} sleeps off the map" + _PLACE_STATE_HINT
    if is_character_sleeping(name, profile=prof):
        return f"{name} is asleep" + _PLACE_STATE_HINT
    from app.core.motion_orders import walking
    if (isinstance(prof.get("journey"), dict) or str(prof.get("movement_target") or "").strip()
            or walking(name, profile=prof)):
        # A live walk order is "on the way" too (plan E3 decision 20): its flip
        # would write the walk's target over the placement.
        return f"{name} is travelling" + _PLACE_STATE_HINT
    if prof.get("place"):
        return f"{name} is seated on a piece of furniture" + _PLACE_STATE_HINT
    if get_interaction(name, profile=prof):
        return f"{name} is in a pair interaction" + _PLACE_STATE_HINT
    if _in_furniture_action(name):
        return f"{name} is in a furniture action" + _PLACE_STATE_HINT
    if is_in_party(name):
        return (f"{name} is in a party — party members move with their leader"
                + _PLACE_STATE_HINT)
    intent = prof.get("outfit_intent")
    slots = intent.get("forbidden_slots") if isinstance(intent, dict) else None
    if slots:
        return (f"{name} has forbidden clothing slots ({', '.join(str(s) for s in slots)})"
                + _PLACE_STATE_HINT)
    flags = [s.flag for s in registry.flag_specs()
             if s.reset_on_location_change and prof.get(s.flag)]
    if flags:
        return (f"{name} has a place-bound state ({', '.join(flags)})" + _PLACE_STATE_HINT)
    return None


def _room_label(loc: Dict[str, Any], room_id: str) -> str:
    room = next((r for r in loc.get("rooms") or []
                 if isinstance(r, dict) and r.get("id") == room_id), None)
    return str((room or {}).get("name") or room_id or "-")


def _placeable_refusal(name: str) -> Optional[str]:
    """Why place_character may not place this character at all (None = it
    may): played by a player, a temporary NPC, not in the world. Asked up
    front and again under the profile lock."""
    from app.models.account import is_player_controlled
    from app.models.character import get_character_status, is_out_of_world, is_temporary_npc
    if is_player_controlled(name):
        return f"{name} is played by a player — the player moves it"
    if is_temporary_npc(name):
        return f"{name} is a temporary NPC — its slot places it"
    if is_out_of_world(get_character_status(name)):
        return (f"{name} is not in the world (pooled or a dormant linked body) "
                "— it cannot be placed")
    return None


@_tool("place_character", True, "place_character{name, location_id, room?}",
       "put an EXISTING character somewhere now (a setup placement, not a walk); "
       "room = a room name or id, default the arrival room")
def _place_character(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 8 (E5). Writes ONLY the placement (the five
    ``character.PLACEMENT_KEYS`` and the position columns, through
    ``character.write_placement``) plus the target in the known places — no
    trace, history, discovery, compliance, flag lifecycle or party drag.
    Refused up front: an unknown character, every refusal of
    :func:`_placeable_refusal` (player-controlled, temporary, out of the
    world), every runtime state of :func:`_placement_state_refusal`, stored
    known places that are no list, an unplaced target, an unknown room and
    "already there". All but the target checks are asked again under the
    profile lock inside ``step.writing``, so a state set meanwhile (a player
    taking the character over included) ends the step refused with nothing
    written. Inverse ``restore_placement`` (world_dev_undo)."""
    from app.core.keyed_lock import keyed_lock
    from app.core.room_stand import free_stand_point
    from app.core.timeutils import utc_now_iso
    from app.core.world_dev_apply import _resolve_room_id
    from app.models.character import (character_row_exists, get_character_profile,
                                      list_character_places, read_placement,
                                      stored_known_locations, write_placement)
    from app.models.world import get_arrival_room_id
    _only_keys(args, {"name", "location_id", "room"}, "place_character")
    name = _str(args, "name", required=True)
    lid_arg = _str(args, "location_id", required=True)
    room_arg = _str(args, "room")
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    refusal = _placeable_refusal(name)
    if refusal:
        raise ToolRefusal(refusal)
    loc = _resolve_location(lid_arg)
    lid = str(loc["id"])
    if loc.get("pos_x") is None or loc.get("pos_z") is None:
        raise ToolRefusal(f"location {lid} has no place on the map — place the location "
                          "first (place_location)")
    if room_arg:
        room = _resolve_room_id(loc, room_arg)
        if not room:
            names = [str(r.get("name")) for r in loc.get("rooms") or []
                     if isinstance(r, dict) and r.get("name")]
            raise ToolRefusal(f"location {lid} has no room {room_arg!r} — its rooms: "
                              + (", ".join(names) if names else "none"))
    else:
        room = get_arrival_room_id(loc)
    prof = get_character_profile(name) or {}
    refusal = _placement_state_refusal(name, prof)
    if refusal:
        raise ToolRefusal(refusal)
    had_key, raw_known = stored_known_locations(name)
    if had_key and not isinstance(raw_known, list):
        # The inverse (remove_known_places) restores a list, or removes the
        # key when there was none — a stored value of another type could not
        # be restored exactly (the update_character rule).
        raise ToolRefusal(f"the stored known places of {name!r} are no list — "
                          "it cannot be placed here")
    seen_loc = str(prof.get("current_location") or "")
    if seen_loc == lid and str(prof.get("current_room") or "") == room:
        raise ToolRefusal(f"{name} is already there ({loc.get('name') or lid} / "
                          f"{_room_label(loc, room)})")
    point = free_stand_point(lid, room, near=(float(loc["pos_x"]), float(loc["pos_z"])),
                             exclude=name)
    x, z = (point if point is not None else (float(loc["pos_x"]), float(loc["pos_z"])))
    values: Dict[str, Any] = {"current_location": lid, "current_room": room,
                              "location_changed_at": utc_now_iso()}
    if seen_loc != lid:
        # The arrival rule: the pose belonged to the old place.
        values["pose_key"] = ""
        values["pose_flavor"] = ""
    pos = {"x": float(x), "z": float(z), "yaw": None, "session": None, "seq": None}
    step.prepare()
    with keyed_lock("character_profile", name):
        before = read_placement(name)
        had_key, raw_known = stored_known_locations(name)
        cfg_known = ([str(v) for v in raw_known if v] if isinstance(raw_known, list)
                     else [])
        # A pending row names the place it was about to add (the
        # remove_known_places rule): not known before, so removing it is exact.
        planned = [] if lid in cfg_known else [lid]
        inverse = {"op": "restore_placement", "name": name, "before": before,
                   "known_added": planned, "had_known_key": had_key}
        step.begin("character", name, inverse)

        def reconcile():
            now = read_placement(name)
            added = [i for i in planned if i in _stored_known_ids(name)]
            if wu._norm(now) == wu._norm(before) and not added:
                return None
            return (name, {**inverse, "known_added": added},
                    {"placement": now, "known": added})

        with step.writing(reconcile):
            # The re-check under the lock: who controls the character, whether
            # it stands in the world, the runtime states other code can set
            # meanwhile, the stored known places and the place the up-front
            # checks read.
            now_prof = get_character_profile(name) or {}
            refusal = _placeable_refusal(name) or _placement_state_refusal(name, now_prof)
            if refusal:
                raise ToolRefusal(refusal)
            if had_key and not isinstance(raw_known, list):
                raise ToolRefusal(f"the stored known places of {name!r} are no list — "
                                  "it cannot be placed here")
            if str(now_prof.get("current_location") or "") != seen_loc:
                raise ToolRefusal(f"{name} was moved meanwhile — read it again")
            if not write_placement(name, values, pos):
                raise ValueError(f"the placement of {name} was not stored")
            _stored, added = _add_known_places(name, [lid])
        inverse["known_added"] = added
        step.attach(name, inverse)
        written = {"placement": read_placement(name), "known": added}
        others = sorted(n for n, (l, r) in list_character_places().items()
                        if l == lid and r == room and n != name)
    line = (f"placed {name} in {loc.get('name') or lid} / {_room_label(loc, room)} "
            f"at ({_g(round(x, 2))},{_g(round(z, 2))}) — now in that room: "
            + (", ".join(others[:8]) + (" …" if len(others) > 8 else "")
               if others else "nobody else")
            + (f"; {lid} is now a known place" if added else ""))
    step.complete(written, line)
    return line


# ── Skills ───────────────────────────────────────────────────────────────

def _loaded_skills() -> List[Any]:
    """The skills of the loaded skill manager (those with a SKILL_ID)."""
    from app.core.dependencies import get_skill_manager
    return [s for s in get_skill_manager().skills if getattr(s, "SKILL_ID", "")]


def _skill_config_obj(name: str, skill: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """The raw text of a character's skill config file (None = no file) and
    the object it holds (``{}`` for no file). A file that is no UTF-8 or
    does not parse as a JSON object is refused: its text could not be
    merged, and the Skills tab is where it gets fixed."""
    from app.models.character import read_character_skill_config_text
    try:
        text = read_character_skill_config_text(name, skill)
        obj = {} if text is None else json.loads(text)
    except (UnicodeDecodeError, ValueError):
        obj = None
        text = ""
    if not isinstance(obj, dict):
        raise ToolRefusal(f"the skill config of {name} for {skill} is not readable — fix it "
                          "in the Skills tab (Game-Admin → Characters)")
    return text, obj


def _skill_toggle_states(name: str) -> List[Dict[str, Any]]:
    """The loaded skills as the Skills tab lists them, in loader order — only
    the fields the tools need: ``skill_id``, ``name``, ``enabled`` (the
    tab's rule, ``character_ops.skill_effective_enabled``) and the capability
    group (``capability_id``/``capability_label``, set only for a package
    with a capability label, as in ``build_available_skills``). Cheaper than
    the tab payload: no dependency blocks, option sources or locations."""
    from app.core import character_ops
    from app.core.dependencies import get_skill_manager
    from app.models.character import get_character_skill_config
    try:
        from app.plugins.registry import package_of_skill
    except Exception:
        package_of_skill = None
    out: List[Dict[str, Any]] = []
    for skill in get_skill_manager().skills:
        sid = skill.SKILL_ID
        if not sid:
            continue
        config = get_character_skill_config(name, sid)
        cap_pkg = None
        if package_of_skill is not None:
            try:
                p = package_of_skill(sid)
                if p is not None and p.capability_label:
                    cap_pkg = p
            except Exception:
                cap_pkg = None
        out.append({"skill_id": sid, "name": skill.name,
                    "enabled": character_ops.skill_effective_enabled(skill, name, config),
                    "capability_id": cap_pkg.id if cap_pkg else "",
                    "capability_label": cap_pkg.capability_label if cap_pkg else ""})
    return out


def _skill_lines(name: str) -> List[str]:
    """``<id> on|off (default|set)`` per loaded skill (from
    :func:`_skill_toggle_states`; "set" = the config file stores ``enabled``)."""
    out: List[str] = []
    for s in _skill_toggle_states(name):
        sid = str(s.get("skill_id") or "")
        try:
            _text, obj = _skill_config_obj(name, sid)
            how = "set" if "enabled" in obj else "default"
        except ToolRefusal:
            how = "config not readable"
        out.append(f"{sid} {'on' if s.get('enabled') else 'off'} ({how})")
    return out


def _skill_groups(name: str) -> List[Dict[str, Any]]:
    """The skill toggles the Skills tab shows for a character (plan
    2026-11-25-world-dev-free-complete-characters-budget, decision 9): ONE
    group per non-empty ``capability_id`` (every verb of the package), a skill
    without one is its own group. From :func:`_skill_toggle_states`
    in loader order, a group at its first member's position:
    ``{"id": capability id or skill id, "label", "members": [skill ids],
    "on": every member effectively enabled}`` — the tab's toggle is on only
    then. Generic: no skill or package is named here."""
    groups: List[Dict[str, Any]] = []
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for s in _skill_toggle_states(name):
        sid = str(s.get("skill_id") or "")
        if not sid:
            continue
        cap = str(s.get("capability_id") or "")
        key = ("capability", cap) if cap else ("skill", sid)
        group = by_key.get(key)
        if group is None:
            label = (s.get("capability_label") if cap else s.get("name")) or cap or sid
            group = {"id": cap or sid, "label": str(label), "members": [], "on": True}
            by_key[key] = group
            groups.append(group)
        group["members"].append(sid)
        group["on"] = group["on"] and bool(s.get("enabled"))
    return groups


def _skill_group_text(group: Dict[str, Any]) -> str:
    """``id`` for a one-member group, ``id (m1+m2)`` otherwise."""
    members = group.get("members") or []
    if len(members) <= 1:
        return str(group.get("id") or "")
    return f"{group.get('id')} ({'+'.join(members)})"


def _stored_enabled(name: str, skill: str) -> Optional[bool]:
    """The ``enabled`` value a skill config file STORES (None = not stored,
    not a real bool, or the file is not readable) — the same judgement as
    set_skill, which counts a member as decided only for an exact bool."""
    try:
        _text, obj = _skill_config_obj(name, skill)
    except ToolRefusal:
        return None
    value = obj.get("enabled")
    return value if isinstance(value, bool) else None


def _open_skill_decisions(name: str) -> List[Dict[str, Any]]:
    """The skill groups of a character nobody has decided yet: a group is
    DECIDED when it is on (the Skills tab shows it on) or when every member
    stores ``enabled`` with one common value; otherwise — a default-off
    group, a mixed or partly stored one — it is open. Each entry is the
    group of :func:`_skill_groups` plus ``text`` (:func:`_skill_group_text`)."""
    out: List[Dict[str, Any]] = []
    for group in _skill_groups(name):
        if group["on"]:
            continue
        stored = [_stored_enabled(name, m) for m in group["members"]]
        if stored and None not in stored and len(set(stored)) == 1:
            continue
        out.append({**group, "text": _skill_group_text(group)})
    return out


@_tool("set_skill", True, "set_skill{name, skill, enabled}",
       "switches a skill group (the toggle the Skills tab shows) on or off for a "
       "character — also to store a deliberate off for a group that is off by "
       "default; skill = a group id or any member's skill id (list_catalog skills); "
       "the skill's settings stay in the admin's Skills tab")
def _set_skill(step: _Step, args: Dict[str, Any]) -> str:
    """Plan p3 Task 9 (E6), widened to capability groups by plan
    2026-11-25-world-dev-free-complete-characters-budget, Task 4 (decision 9).
    ``skill`` names a group (capability id) or any member's skill id; both
    switch the WHOLE group (:func:`_skill_groups`), as the Skills tab's
    toggle does. Only the ``enabled`` key of each member's
    ``skills/<skill>.json`` changes (through ``save_character_skill_config``,
    the writer the toggle route uses), the other keys are kept. Refused up
    front, before any journal row: an unknown character, an unknown skill or
    group, a non-boolean ``enabled``, a member config file that does not
    parse as a JSON object, an enable the F9 dependency check blocks for any
    member this call would WRITE (``character_ops.skill_dependency_block`` —
    the first reason refuses the call; a member that already stores true is
    not written and not asked), and a group whose every member already STORES the
    requested value. Storing the value a member has by default is allowed:
    that is how a deliberate decision is recorded.
    Under ONE ``keyed_lock("skill_config", name)`` the checks are asked
    again; then every member whose stored ``enabled`` differs (absent
    included) gets its own journal row in group order (the multi-row pattern
    of update_character) with the RAW text of its file (or ABSENT).
    Inverse ``restore_skill_config`` (world_dev_undo) per row: the text
    written back verbatim, or the file removed. ``had_dir`` is the real
    value on the FIRST written member and True on every later one (that
    first write created the directory), so the reverse-order undo drops a
    ``skills/`` directory this call created exactly once, with the first
    member."""
    from app.core import character_ops
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (character_row_exists, character_skills_dir_exists,
                                      read_character_skill_config_text,
                                      save_character_skill_config)
    _only_keys(args, {"name", "skill", "enabled"}, "set_skill")
    name = _str(args, "name", required=True)
    skill = _str(args, "skill", required=True)
    enabled = args.get("enabled")
    if not isinstance(enabled, bool):
        raise ToolRefusal("'enabled' must be true or false")
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    # Before any read (the reads are side-effect free; recorded so the undo
    # drops a skills/ directory this step created).
    had_dir = character_skills_dir_exists(name)
    word = "on" if enabled else "off"

    def resolve() -> Dict[str, Any]:
        groups = _skill_groups(name)
        group = (next((g for g in groups if skill in g["members"]), None)
                 or next((g for g in groups if g["id"] == skill), None))
        if group is None:
            raise ToolRefusal(f"no skill or skill group {skill!r} — "
                              f"list_catalog{{\"name\": \"skills\"}} lists the skill "
                              "ids and their group ids")
        return group

    def check() -> Tuple[Dict[str, Any], List[Tuple[str, Optional[str], Dict[str, Any]]]]:
        group = resolve()
        configs = [(m, *_skill_config_obj(name, m)) for m in group["members"]]
        todo = [(m, text, obj) for m, text, obj in configs if obj.get("enabled") is not enabled]
        if not todo:
            raise ToolRefusal(f"skill {group['id']} of {name} is already {word}")
        if enabled:
            # Only the members this call writes: a member that already
            # stores true is not touched, so its dependencies are not asked.
            for m, _text, _obj in todo:
                reason = character_ops.skill_dependency_block(name, m)
                if reason:
                    raise ToolRefusal(f"cannot switch {group['id']} on for {name}: {reason}")
        return group, todo

    check()
    step.prepare()
    rows: List[_Step] = []
    with keyed_lock("skill_config", name):
        group, todo = check()
        was_on = bool(group["on"])
        multi = len(group["members"]) > 1
        for member, before, obj in todo:
            # The call's own step first, then one more row per further member.
            mstep = step if not rows else _Step(step.ctx, step.tool, step.args)
            inverse = {"op": "restore_skill_config", "name": name, "skill": member,
                       "before": wu.ABSENT if before is None else before,
                       "had_dir": had_dir if not rows else True}
            rows.append(mstep)
            mstep.begin("character", name, inverse)

            def reconcile(member=member, before=before, inverse=inverse):
                try:
                    now = read_character_skill_config_text(name, member)
                except UnicodeDecodeError:
                    now = ""
                if now == before:
                    return None
                return name, inverse, now

            with mstep.writing(reconcile):
                save_character_skill_config(name, member, {**obj, "enabled": enabled})
                written = read_character_skill_config_text(name, member)
                stored = json.loads(written) if written is not None else None
                if not isinstance(stored, dict) or stored.get("enabled") is not enabled:
                    raise ValueError(f"the skill config of {name} for {member} was not stored")
            mstep.complete(written, f"skill {member} of {name}: {word}"
                           + ("" if multi or was_on is not enabled else " (decided)"))
    head = (f"skill group {_skill_group_text(group)}" if multi
            else f"skill {group['id']}")
    return f"{head} of {name}: {word}" + (" (decided)" if was_on is enabled else "")


# ── check_run / check_character ──────────────────────────────────────────

@_tool("check_character", False, "check_character{name}",
       "everything a character still lacks, in full (profile, soul, body slots, outfits, "
       "home, secrets, skills) and its pending media — use it when filling or checking "
       "existing characters")
def _check_character(step: _Step, args: Dict[str, Any]) -> str:
    """Plan 2026-11-25-world-dev-free-complete-characters-budget, Task 5
    (C1): world_dev_completeness.check_character_lines — the full gap list,
    whatever the run touched, plus the media gaps (with the run's media on
    it records the character's media baseline, run bookkeeping only)."""
    from app.models.character import character_row_exists
    _only_keys(args, {"name"}, "check_character")
    name = _str(args, "name", required=True)
    if not character_row_exists(name):
        raise ToolRefusal(f"no character {name!r} — use find_characters")
    return "\n".join(completeness.check_character_lines(step.ctx.run_id, name))


@_tool("check_run", False, "check_run{}",
       "what the elements this run created or changed still lack (call it before "
       "the summary; for an updated character only what the run changed — "
       "check_character lists everything)")
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
               "character": ("delete_character", "name"),
               "world_prop": ("delete_world_prop", "id"),
               "terrain_type": ("delete_terrain_type", "kind"),
               # The key names a LIST of ids (create_item journals one).
               "item": ("delete_items", "ids"),
               "secret": ("delete_secret", "id"),
               "rule": ("delete_rule", "id"),
               "event": ("delete_event", "id"),
               "quest_template": ("delete_quest_template", "id")}

#: Kinds delete_created removes only in the turn that created them (E2): no
#: writer of theirs can re-create a row exactly (a new created_at / row
#: order / id), so a cross-turn delete would have no exact inverse.
_SAME_TURN_ONLY = {"item", "secret", "rule", "event", "quest_template"}


def _creating_entry(run_id: str, kind: str, ident: str,
                    turn: Optional[int] = None) -> Optional[Dict[str, Any]]:
    op, key = _CREATE_OPS[kind]

    def names(value: Any) -> bool:
        if isinstance(value, list):
            return ident in [str(v or "") for v in value]
        return str(value or "") == ident
    return next((e for e in wr.entries(run_id, turn=turn)
                 if (e.get("inverse") or {}).get("op") == op
                 and names((e.get("inverse") or {}).get(key))), None)


@_tool("delete_created", True, "delete_created{kind, id}",
       "remove something THIS run created, in this or an earlier turn "
       "(kind location|terrain|height|character|world_prop|terrain_type|item|secret|rule|"
       "event|quest_template; id = the name for a character, the kind for a terrain kind; "
       "an item, a secret, a rule, an event or a quest template only in the turn that "
       "created it)")
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
            raise ToolRefusal(f"{_kind_label(kind)} {ident!r} was not created by this run (or is "
                              "already removed) — only those can be deleted")
        if kind in _SAME_TURN_ONLY:
            # No exact re-creation exists for these (the writers stamp a new
            # created_at / id / row order), so a turn rollback could not
            # bring one back: only the same turn deletes one.
            raise ToolRefusal(f"{_kind_label(kind)} {ident} was created in an earlier turn — "
                              "it cannot be deleted now (a rollback of this turn could not "
                              "re-create it exactly); the discard of the run removes it")
        return _delete_earlier(step, kind, ident, earlier)
    if kind == "item":
        from app.models.inventory import find_item_location
        where = find_item_location(ident)
        if where is not None:
            holder = (f"character {where.get('character')}" if where.get("kind") == "character"
                      else f"room {where.get('room_id')} of {where.get('location_id')}")
            raise ToolRefusal(f"item {ident} is still held ({holder}) — take it back first "
                              "(undo of that step) or keep it")
        from app.models.world import list_locations
        named = [f'{l.get("id")} "{l.get("name") or ""}"' for l in list_locations() or []
                 if str(l.get("knowledge_item_id") or "") == ident]
        if named:
            raise ToolRefusal(f"item {ident} is the knowledge item of location "
                              + ", ".join(named) + " — change that place first "
                              "(undo of that step) or keep it")
        from app.models import rules
        rule_refs = _rule_refs(_naming_refs(rules.rules_naming, "world rules", item=ident))
        if rule_refs:
            raise ToolRefusal(f"item {ident} is still named by: " + "; ".join(rule_refs)
                              + " — delete or change those first")
    if kind == "location":
        refs = _references_to_location(ident) + [
            f"{n} (stands there)" for n, _room in wu.standing_in(ident)]
        if refs:
            raise ToolRefusal(f"location {ident} is still named by: " + "; ".join(refs))
    if kind == "character":
        refs = _references_to_character(ident)
        if refs:
            raise ToolRefusal(f"character {ident!r} is still named by: " + "; ".join(refs)
                              + " — delete or change those first")
    if kind == "terrain_type":
        # The undo of the creating step would skip a kind still in use
        # (changed since, in use) — refused here for the same reason.
        users = wu.terrain_kind_users(ident)
        if users:
            raise ToolRefusal(f"terrain kind {ident} is still used by: "
                              + _kind_users_text(users) + " — change or delete those first")
    step.prepare()
    # Removing a painted area can bare impassable ground under a pin.
    box = grounds = None
    if kind == "terrain":
        from app.models.terrain import get_area
        box = _union_box((get_area(ident) or {}).get("polygon"))
        grounds = _pin_grounds_before(box)
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
        raise ToolRefusal(f"could not delete {_kind_label(kind)} {ident}: {reason}")
    wr.mark_undone(step.ctx.run_id, int(creating["seq"]))
    # The creating entry is undone and the element gone: the media lane gives
    # it its first baseline back, exactly as the undo does (F4) — the undo of
    # this turn finds that entry already undone and never reaches its hook.
    from app.core import world_dev_media
    target = world_dev_media.create_target(creating.get("inverse"))
    if target is not None:
        world_dev_media.note_create_undone(step.ctx.run_id, target[0], target[1])
    kept = [str(s.get("item")) for s in skips if "item" in s]
    line = (f"deleted {_kind_label(kind)} {ident} (created in step #{creating['seq']})"
            + (f"; items kept (still in use): {', '.join(kept)}" if kept else "")
            + _warn_suffix(_ground_warnings(grounds, box)))
    step.complete(None, line)
    return line


# ── delete_area ──────────────────────────────────────────────────────────

#: The area kinds delete_area / _delete_area_row take (journal target kinds).
_AREA_KINDS = ("terrain", "height")


def _area_reader(kind: str) -> Callable[[str], Optional[Dict[str, Any]]]:
    from app.models.terrain import get_area
    return get_area if kind == "terrain" else _height_area


def _delete_area_row(step: _Step, kind: str, ident: str, line: str) -> str:
    """Delete one terrain or height area with an exact re-creation as its
    inverse: snapshot (the reader's full row) -> recreate_* inverse ->
    delete. Used by the cross-turn delete_created and by delete_area (any
    area, also one that existed before the run)."""
    from app.models.heightfield import delete_height_area, height_area_order_identity
    from app.models.terrain import area_order_identity, delete_area
    read = _area_reader(kind)
    delete = delete_area if kind == "terrain" else delete_height_area
    identity = area_order_identity if kind == "terrain" else height_area_order_identity
    op = "recreate_terrain_area" if kind == "terrain" else "recreate_height_area"
    step.prepare()
    # The area writers have no writer lock to share (see world_dev_undo):
    # read and delete follow each other directly.
    row = read(ident)
    order = identity(ident)
    if row is None or order is None:
        raise ToolRefusal(f"{kind} area {ident} does not exist any more")
    # `order` puts it back at its old place in the paint order (created_at,
    # rowid, and the tie siblings on either side it is checked against) with
    # its old version token (updated_at) — terrain.restore_area.
    inverse = {"op": op, "row": copy.deepcopy(row), "order": order}
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    slots = len(meta.get("npc_slots") or []) if isinstance(meta.get("npc_slots"), list) else 0
    # Removing a painted area can bare impassable ground under a pin.
    box = _union_box(row.get("polygon")) if kind == "terrain" else None
    grounds = _pin_grounds_before(box) if kind == "terrain" else None
    step.begin(kind, ident, inverse)

    def reconcile_area():
        return None if read(ident) is not None else (ident, inverse, None)

    with step.writing(reconcile_area):
        if not delete(ident) and read(ident) is not None:
            raise RuntimeError(f"{kind} area {ident} was not deleted")
    warnings = _ground_warnings(grounds, box)
    if slots:
        # npc_home / npc_spawn tolerate a missing area id; say what went.
        warnings.append(f"{slots} NPC slot{'' if slots == 1 else 's'} went with it")
    line += _warn_suffix(warnings)
    step.complete(None, line)
    return line


@_tool("delete_area", True, "delete_area{kind, id}",
       "remove ANY terrain or height area (kind terrain|height), also one that existed "
       "before the run, one area at a time; the discard "
       "brings it back")
def _delete_area(step: _Step, args: Dict[str, Any]) -> str:
    _only_keys(args, {"kind", "id"}, "delete_area")
    kind = _str(args, "kind", required=True)
    ident = _str(args, "id", required=True)
    if kind not in _AREA_KINDS:
        raise ToolRefusal("kind must be one of " + ", ".join(_AREA_KINDS))
    if _area_reader(kind)(ident) is None:  # pre-check before the backup
        raise ToolRefusal(f"{_kind_label(kind)} {ident} does not exist — map_region "
                          "lists the areas")
    # An area this turn created has its creating entry's inverse: deleting it
    # here would journal a second inverse for one creation.
    if _creating_entry(step.ctx.run_id, kind, ident, turn=step.ctx.turn) is not None:
        raise ToolRefusal(f"{_kind_label(kind)} {ident} was created in this turn — use "
                          f"delete_created{{kind: {kind}, id: {ident}}}")
    earlier = _creating_entry(step.ctx.run_id, kind, ident)
    line = f"deleted {_kind_label(kind)} {ident}" + (
        f" (created in step #{earlier['seq']}, an earlier turn)" if earlier else "")
    return _delete_area_row(step, kind, ident, line)


def _location_media(loc_id: str) -> List[str]:
    """The media directories delete_location removes with a place (its
    gallery and building models) that hold a file. Empty sub dirs do not
    count, nor the gallery's meta files (``world_dev_media.GALLERY_META_FILES``)
    while no other file is left beside them: they describe images, and with
    none left (the run's own media are removed first, Task 9 of plan
    2026-11-25-world-dev-free-media) they describe nothing a re-creation
    would miss. The snapshot does not hold them, so a rollback that
    re-creates the place does not bring them back — deliberately: they can
    only describe the run's own removed images (the place was created by
    the run), which are regenerable derivatives, not world data."""
    import os
    from app.core.paths import get_storage_dir
    from app.core.world_dev_media import GALLERY_META_FILES
    storage = get_storage_dir()
    out = []
    for sub in ("world_gallery", "locations"):
        d = storage / sub / loc_id
        if not d.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(str(d)):
            top = os.path.abspath(dirpath) == os.path.abspath(str(d))
            if any(not (sub == "world_gallery" and top and f in GALLERY_META_FILES)
                   for f in files):
                out.append(f"{sub}/{loc_id}")
                break
    return out


def _remove_earlier_media(step: _Step, kind: str, ident: str) -> int:
    """Cross-turn delete_created of a location / character (Task 9 of plan
    2026-11-25-world-dev-free-media): remove the media the run's lane
    produced for the element BEFORE its snapshot — media are regenerable
    derivatives (a rollback that re-creates the element re-plans them), and
    the snapshot then holds only world data. A render of the element still
    running after the bounded wait is refused (its output would land after
    the snapshot). Returns the number of files removed."""
    from app.core import world_dev_media
    rows = wr.media_rows(step.ctx.run_id, kind=kind, target_id=ident)
    if not rows:
        return 0
    dirs = {str(a.get("path")) for r in rows for a in r.get("produced") or []
            if isinstance(a, dict) and a.get("type") in ("dir", "gallery_dir")}
    rep = world_dev_media.remove_element_media(step.ctx.run_id, kind, ident)
    if rep.get("pending"):
        raise ToolRefusal(f"{_kind_label(kind)} {ident}: a render of it is still running "
                          f"({', '.join(str(p.get('step')) for p in rep['pending'])}) — "
                          "try again when it has ended")
    return sum(1 for p in rep.get("removed") or []
               if not str(p).startswith("profile ") and str(p) not in dirs)


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
    if _in_furniture_action(name):
        out.append("in a furniture action")
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
    line = f"deleted {_kind_label(kind)} {ident} (created in step #{seq}, an earlier turn)"
    if kind == "location":
        from app.models.world import (delete_location, get_location_by_id,
                                      world_write_lock)
        # The refusals first (re-checked under the lock below), then the
        # run's media of the place go — never while holding the writer
        # lock: the removal may wait for a running render.
        if get_location_by_id(ident) is None:
            raise ToolRefusal(f"location {ident} does not exist any more")
        refs = _references_to_location(ident) + [
            f"{n} (stands there)" for n, _room in wu.standing_in(ident)]
        if refs:
            raise ToolRefusal(f"location {ident} is still named by: " + "; ".join(refs))
        step.prepare()
        n_media = _remove_earlier_media(step, "location", ident)
        if n_media:
            line += f"; its media removed ({n_media} files)"
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
    if kind in _AREA_KINDS:
        return _delete_area_row(step, kind, ident, line)
    if kind == "world_prop":
        from app.models.world_props import delete_world_prop
        step.prepare()
        # Like the areas: the world-prop writer has no writer lock to share,
        # so the snapshot and the delete follow each other directly.
        prop_row = wu.world_prop_row(ident)
        if prop_row is None:
            raise ToolRefusal(f"world prop {ident} does not exist any more")
        # Edited by somebody else since this run placed it: the undo of the
        # creating step leaves such a row alone (changed since), so deleting
        # it here would make the discard re-create a foreign edit — refused,
        # as the same-turn path refuses it.
        written = creating.get("written")
        if written is not None and wu._norm(prop_row) != wu._norm(written):
            raise ToolRefusal(f"could not delete world prop {ident}: {wu.REASON_CHANGED}")
        prop_inverse = {"op": "recreate_world_prop", "row": copy.deepcopy(prop_row)}
        step.begin("world_prop", ident, prop_inverse)

        def reconcile_prop():
            return (None if wu.world_prop_row(ident) is not None
                    else (ident, prop_inverse, None))

        with step.writing(reconcile_prop):
            if not delete_world_prop(ident) and wu.world_prop_row(ident) is not None:
                raise RuntimeError(f"world prop {ident} was not deleted")
        step.complete(None, line)
        return line
    if kind == "terrain_type":
        return _delete_earlier_terrain_type(step, ident, creating, line)
    # character
    from app.core.keyed_lock import keyed_lock
    from app.models.character import character_row_exists, delete_character
    # The refusals first (re-checked under the lock below), then the run's
    # media of the character go — outside the profile lock: the removal
    # takes it itself (profile keys) and may wait for a running render.
    if not character_row_exists(ident):
        raise ToolRefusal(f"character {ident!r} does not exist any more")
    refs = _references_to_character(ident)
    if refs:
        raise ToolRefusal(f"character {ident!r} is still named by: " + "; ".join(refs)
                          + " — delete or change those first")
    blockers = _character_delete_blockers(ident)
    if blockers:
        raise ToolRefusal(f"character {ident!r} cannot be deleted in a later turn "
                          "— a re-creation could not restore it exactly: "
                          + "; ".join(blockers))
    step.prepare()
    n_media = _remove_earlier_media(step, "character", ident)
    if n_media:
        line += f"; its media removed ({n_media} files)"
    with keyed_lock("character_profile", ident):
        if not character_row_exists(ident):
            raise ToolRefusal(f"character {ident!r} does not exist any more")
        refs = _references_to_character(ident)
        if refs:
            raise ToolRefusal(f"character {ident!r} is still named by: " + "; ".join(refs)
                              + " — delete or change those first")
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


def _delete_earlier_terrain_type(step: _Step, ident: str, creating: Dict[str, Any],
                                 line: str) -> str:
    """delete_created of a terrain kind this run created in an earlier turn:
    refused while any area (its kind or its water bed) or place uses it, or
    when it was changed since; the inverse re-creates the exact world row.
    Like the areas, the catalog writer has no writer lock to share: the
    snapshot, the use check and the delete follow each other directly."""
    from app.core.terrain_types import delete_world_type
    step.prepare()
    row = wu.terrain_type_row(ident)
    if row is None:
        raise ToolRefusal(f"terrain kind {ident} does not exist any more")
    written = creating.get("written")
    if wu.terrain_type_changed(row, written):
        raise ToolRefusal(f"could not delete terrain kind {ident}: {wu.REASON_CHANGED}")
    users = wu.terrain_kind_users(ident)
    if users:
        raise ToolRefusal(f"terrain kind {ident} is still used by: "
                          + _kind_users_text(users) + " — change or delete those first")
    inverse = {"op": "recreate_terrain_type", "row": copy.deepcopy(row)}
    step.begin("terrain_type", ident, inverse)

    def reconcile():
        return None if wu.terrain_type_row(ident) is not None else (ident, inverse, None)

    with step.writing(reconcile):
        if not delete_world_type(ident) and wu.terrain_type_row(ident) is not None:
            raise RuntimeError(f"terrain kind {ident} was not deleted")
    step.complete(None, line)
    return line
