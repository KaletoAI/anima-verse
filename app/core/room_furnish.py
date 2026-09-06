"""Room furnishing job (plan-room-furnish.md) — the "✨ Furnish" workflow.

The LLM delivers SEMANTICS, never coordinates: it writes what the room NEEDS
without ever seeing the library (``furnish_needs``), maps the library onto
that need list (``furnish_match``) and arranges the result RELATIONALLY
(``furnish_place``); the deterministic ``furnish_solver`` turns that plan into
``layout.props`` geometry. The need list is the ONE list the whole job carries
— a need either names the library piece that serves it or is built
(plan-furnish-v2.md § 4).

Because generation takes minutes, the whole thing is a PERSISTED job — one
row per room, one in-process orchestrator thread (pattern:
``props.trigger_generation``). The dialog is only a view on that row and may
be closed at any time; a server restart kills the thread but not the state,
which is why every phase re-enters idempotently (``resume``/``retry``).

PLACING COMES BEFORE GENERATING (decision E6, B12). Waiting for every mesh
before the first placement meant hours of an empty dialog; now the plan is
made from the need list's own dimensions, so the admin sees the finished room
as ghosts within minutes and the meshes arrive afterwards — the recipe already
renders a prop without a model as a placeholder box, so an accepted room is
usable while it fills itself in.

States and their transitions::

    selecting ──▶ proposal_ready ──confirm──▶ placing ──▶ review_ready
                                                               │
                        error ◀── any phase failing          accept
                                                               ▼
                                        (row deleted) ◀── generating

``accept`` hands the placements to ``layout.props`` and keeps the row only as
long as meshes are still missing; ``discard``/``reset`` delete it outright.
There is no history: the provenance of a run lives in the job log / queue
panel (the layout sanitizer strips foreign fields, so per-placement provenance
is impossible anyway).

Everything the job writes outside its own row is normal world data: the props
``accept`` creates are ordinary library entries (they survive the job) and the
accepted placements are appended to ``layout.props`` via
``world.append_room_props``.

THE YARD IS A TARGET LIKE A ROOM (§ A13a). A location's ground can be
furnished too; it has no floor plan, so its surface is the drawn boundary and
its placements are location-local metres. Two things follow: the job is
addressed by the COMPOSITE id ``__ground__@<location_id>`` (see
``ground_job_id`` — the reserved room id is the one that is not unique), and
the solver's frame is shifted by the boundary's min corner and back
(``_geometry``/``_phase_place``).
"""

import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core import furnish_needs
from app.core.db import get_connection, transaction
from app.core.llm_json import llm_json
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

# Job states (plan-room-furnish.md). ACTIVE = a thread should be working on
# it; without one the job is "stalled" and the dialog offers Continue.
STATE_SELECTING = "selecting"
STATE_PROPOSAL_READY = "proposal_ready"
STATE_GENERATING = "generating"
STATE_PLACING = "placing"
STATE_REVIEW_READY = "review_ready"
STATE_ERROR = "error"
_ACTIVE_STATES = (STATE_SELECTING, STATE_PLACING, STATE_GENERATING)

# Share of the FLOOR area the summed footprints of floor pieces may occupy —
# the same hard limit the solver enforces; here it only sizes the prompt's
# budget. Wall, ceiling and surface pieces have budgets of their own (in the
# solver) and never touch this one.
BUDGET_FRACTION = 0.45
# What a need may say, how many of them there may be and how far a library
# piece may differ from one lives with the validators that enforce it
# (``app.core.furnish_needs``); this module only spends those numbers.
MODEL_POLL_SECONDS = 5
MODEL_TIMEOUT_SECONDS = 30 * 60


_lock = threading.Lock()
# room_ids with a running orchestrator thread (double-start guard, pattern
# props._generating). NOT persisted — after a restart every job is stalled.
_running: set = set()


class FurnishError(Exception):
    """Job error carrying the HTTP status the routes should map it to."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ── Row access ──────────────────────────────────────────────────────────

def _loads(raw: Any) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _get_row(room_id: str) -> Optional[Dict[str, Any]]:
    if not room_id:
        return None
    try:
        row = get_connection().execute(
            "SELECT room_id, location_id, state, proposal, placements, error, "
            "created_at, updated_at FROM room_furnish WHERE room_id=?",
            (room_id,)).fetchone()
    except Exception as e:
        logger.error("room_furnish read failed for %s: %s", room_id, e)
        return None
    if not row:
        return None
    return {"room_id": row[0], "location_id": row[1], "state": row[2],
            "proposal": _loads(row[3]), "placements": _loads(row[4]),
            "error": row[5] or "", "created_at": row[6], "updated_at": row[7]}


def _insert_row(room_id: str, location_id: str) -> None:
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO room_furnish (room_id, location_id, state, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?)",
            (room_id, location_id, STATE_SELECTING, now, now))


def _update_row(room_id: str, **fields: Any) -> bool:
    """UPDATE only — never re-creates a row a discard/reset removed, so a
    still-running thread cannot resurrect a cancelled job."""
    sets = ["updated_at=?"]
    vals: List[Any] = [utc_now_iso()]
    for key in ("state", "error"):
        if key in fields:
            sets.append(f"{key}=?")
            vals.append(fields[key] if fields[key] is not None else "")
    for key in ("proposal", "placements"):
        if key in fields:
            sets.append(f"{key}=?")
            vals.append(json.dumps(fields[key], ensure_ascii=False)
                        if fields[key] is not None else None)
    vals.append(room_id)
    with transaction() as conn:
        cur = conn.execute(
            f"UPDATE room_furnish SET {', '.join(sets)} WHERE room_id=?", vals)
        return cur.rowcount > 0


def _delete_row(room_id: str) -> bool:
    with transaction() as conn:
        return conn.execute("DELETE FROM room_furnish WHERE room_id=?",
                            (room_id,)).rowcount > 0


def _fail(room_id: str, message: str) -> None:
    logger.warning("room_furnish %s failed: %s", room_id, message)
    _update_row(room_id, state=STATE_ERROR, error=message[:500])


# ── Status ──────────────────────────────────────────────────────────────

def _prop_ready(prop_id: Any) -> bool:
    """True when the prop exists AND already carries a model."""
    pid = str(prop_id or "")
    if not pid:
        return False
    from app.core.props import get_prop
    prop = get_prop(pid)
    return bool(prop and prop.get("has_model"))


def _needs(proposal: Any) -> List[Dict[str, Any]]:
    """The job's need list — the only list a proposal carries (§ 4)."""
    raw = (proposal or {}).get("needs") if isinstance(proposal, dict) else None
    return [n for n in (raw or []) if isinstance(n, dict)]


def _ordered_builds(proposal: Any) -> List[Dict[str, Any]]:
    """The needs a mesh was actually ORDERED for: built AND carrying a prop id.

    A need that stayed unplaced never gets a prop (controller ruling: build
    only what was placed), so it is not part of any n/m — counting it would
    leave the progress bar one short forever and make the job unclosable.
    """
    return [n for n in _needs(proposal)
            if n.get("build") and n.get("prop_id")]


def _pending_builds(proposal: Any) -> List[Dict[str, Any]]:
    """The ordered props that still have no model."""
    return [n for n in _ordered_builds(proposal)
            if not _prop_ready(n.get("prop_id"))]


def _progress(proposal: Any) -> Dict[str, int]:
    """Generation progress n/m over the props a mesh was ordered for —
    derived, not stored: one counts as done when it carries a model."""
    build = _ordered_builds(proposal)
    return {"done": sum(1 for n in build if _prop_ready(n.get("prop_id"))),
            "total": len(build)}


def _accepted(placements: Any) -> bool:
    """Whether the placements of this job are already IN the room's layout.

    Written by ``accept`` before the generation phase starts, because from
    that moment the row is only a progress bar: a restart mid-generation must
    not append the same placements a second time.
    """
    return bool(isinstance(placements, dict) and placements.get("accepted"))


def _finished_notification(room_id: str, location_id: str, built: int) -> None:
    """The one "the meshes are there" line — posted wherever a job reaches its
    end, so the normal finish and the self-healing close read alike."""
    if built <= 0:
        return
    try:
        room_name = _room_label(_load_room(room_id)[1])
    except FurnishError:
        return  # the room went away with the job; nobody to notify about
    from app.models.notifications import create_notification
    create_notification(
        room_name,
        f"Meshes ready — {built} model{'s' if built != 1 else ''} generated "
        f"for {room_name}.",
        notification_type="room_furnish",
        metadata={"room_id": room_id, "location_id": location_id})


def _skipped_notification(room_id: str, location_id: str, placed: int,
                          skipped: List[str]) -> None:
    """Say which pieces the accept did NOT build. A need the solver could not
    fit gets no prop and no mesh (controller ruling), and that is a decision
    the admin has to be able to see — otherwise a kind simply vanishes between
    the proposal and the room."""
    try:
        room_name = _room_label(_load_room(room_id)[1])
    except FurnishError:
        return
    from app.models.notifications import create_notification
    create_notification(
        room_name,
        f"Furnishing accepted — {placed} piece{'s' if placed != 1 else ''} "
        f"placed in {room_name}; not built: {', '.join(skipped)} "
        f"(nothing placed them).",
        notification_type="room_furnish",
        metadata={"room_id": room_id, "location_id": location_id})


def _close_finished(room_id: str, row: Dict[str, Any]) -> bool:
    """Close an ACCEPTED job whose meshes are all there — True when it did.

    This is the normal end of a restart during generation: the task queue is
    persistent and finishes the meshes on its own while the furnish thread is
    dead. Without this the row would sit in ``generating`` forever, and every
    verb refuses that state — the room could never be furnished again. The
    caller must know that no thread is working on the job, otherwise the
    running phase and this would both delete the row and both notify.
    """
    if not _accepted(row.get("placements")):
        return False
    proposal = row.get("proposal")
    if _pending_builds(proposal):
        return False
    if not _delete_row(room_id):
        return False
    _finished_notification(room_id, str(row.get("location_id") or ""),
                           len(_ordered_builds(proposal)))
    logger.info("room_furnish %s: every ordered mesh is there, job closed",
                room_id)
    return True


def _phase_counts(placements: Any) -> Dict[str, Dict[str, int]]:
    """``{mount: {placed, unplaced}}`` of the placement run — stored with the
    result, because the dialog polls this status and re-deriving it would read
    the whole prop library on every poll."""
    from app.core.furnish_place import MOUNTS
    stored = placements.get("phase_counts") if isinstance(placements, dict) else None
    empty = {m: {"placed": 0, "unplaced": 0} for m in MOUNTS}
    if not isinstance(stored, dict):
        return empty
    for mount in MOUNTS:
        entry = stored.get(mount)
        if isinstance(entry, dict):
            empty[mount] = {"placed": int(entry.get("placed") or 0),
                            "unplaced": int(entry.get("unplaced") or 0)}
    return empty


def get_status(room_id: str) -> Optional[Dict[str, Any]]:
    """The job's full status payload, or None when there is no job."""
    row = _get_row(room_id)
    if not row:
        return None
    with _lock:
        running = room_id in _running
    # A SELF-HEALING READ. A job whose generation thread died with the server
    # keeps waiting in ``generating`` even after the persistent task queue has
    # delivered every mesh; nothing could then close it (see _close_finished).
    # Only a job NOBODY is working on is closed here — the running phase closes
    # its own.
    if not running and row["state"] == STATE_GENERATING \
            and _close_finished(room_id, row):
        return None
    row["running"] = running
    # After a restart the state survives but the thread does not — the dialog
    # offers "Continue" exactly for this.
    row["stalled"] = row["state"] in _ACTIVE_STATES and not running
    # Mesh generation only starts at accept (E6), so before that there is
    # nothing to be n/m of — a progress bar during review would count props
    # nobody has ordered yet.
    row["progress"] = (_progress(row.get("proposal"))
                       if _accepted(row.get("placements"))
                       else {"done": 0, "total": 0})
    row["phase_counts"] = _phase_counts(row.get("placements"))
    return row


# ── World lookups / geometry ────────────────────────────────────────────

# THE YARD NEEDS A COMPOSITE JOB ID. Every room id in this world is unique —
# except the reserved ground id, which every location carries (§ A13). The job
# table is keyed by room id, and ``find_location_by_room`` answers with the
# FIRST location that has one, so a bare "__ground__" would furnish somebody
# else's yard and two yards could never be open at once. A ground job is
# therefore addressed as ``__ground__@<location_id>`` — the id clients pass to
# every furnish endpoint. Rooms keep their plain id.
GROUND_JOB_SEP = "@"


def ground_job_id(location_id: str) -> str:
    """The furnish job id of ONE location's yard (§ A13a)."""
    from app.models.world import GROUND_ROOM_ID
    return f"{GROUND_ROOM_ID}{GROUND_JOB_SEP}{location_id}"


def _target(job_id: str) -> Tuple[str, str]:
    """``(room_id, location_id)`` a job id addresses; the location is '' for
    an ordinary room, which is looked up by its own unique id."""
    from app.models.world import GROUND_ROOM_ID
    prefix = f"{GROUND_ROOM_ID}{GROUND_JOB_SEP}"
    if (job_id or "").startswith(prefix):
        return GROUND_ROOM_ID, job_id[len(prefix):]
    return job_id or "", ""


def _load_room(job_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from app.models.world import (find_location_by_room, get_location_by_id,
                                  get_room_by_id)
    room_id, location_id = _target(job_id)
    loc = get_location_by_id(location_id) if location_id \
        else find_location_by_room(room_id)
    room = get_room_by_id(loc, room_id) if loc else None
    if not loc or not room:
        raise FurnishError("Room not found", 404)
    return loc, room


def _room_label(room: Dict[str, Any]) -> str:
    """What the prompts and the job log call this surface. An unnamed yard is
    not "Room": the ground is the location's open surface (§ A13), and an
    author who never named it still has to recognise the job."""
    from app.models.world import GROUND_ROOM_ID
    name = str(room.get("name") or "").strip()
    if name:
        return name
    return "Yard" if str(room.get("id") or "") == GROUND_ROOM_ID else "Room"


def _poly_area(pts: List[List[float]]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _geometry(loc: Dict[str, Any], room: Dict[str, Any]) -> Dict[str, Any]:
    """The furnishing surface in REAL METRES. Raises when there is none.

    Since contract v6 Nr. 2 a layout IS metres — origin at the room's min
    corner, which is exactly the frame ``furnish_solver`` works in — so this
    only reads what is stored. The scale-anchor precondition is gone with the
    fraction system: there is no plan width left to be missing.

    THE GROUND IS A SURFACE WITHOUT A PLAN (§ A13a). Its shape is the drawn
    location boundary and its placements are LOCATION-LOCAL metres, so the
    solver — which works from a polygon's own min corner — needs that corner
    named: ``origin`` is the offset between the two frames, ``[0, 0]`` for a
    room and the boundary's min corner for the ground. Its openings are the
    boundary pass-throughs, on the very edge indices the polygon has.
    """
    from app.models.world import GROUND_ROOM_ID
    lay = room.get("layout") if isinstance(room.get("layout"), dict) else {}
    if str(room.get("id") or "") == GROUND_ROOM_ID:
        from app.core.room_recipe import boundary_points
        boundary = boundary_points(loc.get("map3d"))
        if len(boundary) < 3:
            raise FurnishError(
                "This location has no boundary drawn yet — draw its outline "
                "first, the yard is that area.", 409)
        x0 = min(p[0] for p in boundary)
        y0 = min(p[1] for p in boundary)
        outline_m = [[round(p[0] - x0, 3), round(p[1] - y0, 3)]
                     for p in boundary]
        openings = [op for op in ((loc.get("map3d") or {}).get(
            "boundary_openings") or []) if isinstance(op, dict)]
        return {"layout": lay, "origin": [x0, y0],
                "w_m": round(max(p[0] for p in outline_m), 3),
                "d_m": round(max(p[1] for p in outline_m), 3),
                "outline_m": outline_m,
                "area_m2": round(_poly_area(outline_m), 2),
                "is_rect": False, "openings": openings}
    if not all(k in lay for k in ("x", "y", "w", "d")):
        raise FurnishError(
            "This room has no floor plan saved yet — draw its layout and "
            "save the location first.", 409)
    w_m = round(float(lay["w"]), 3)
    d_m = round(float(lay["d"]), 3)
    pts = lay.get("outline") or [[0.0, 0.0], [w_m, 0.0], [w_m, d_m], [0.0, d_m]]
    outline_m = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in pts]
    return {"layout": lay, "origin": [0.0, 0.0], "w_m": w_m, "d_m": d_m,
            "outline_m": outline_m, "area_m2": round(_poly_area(outline_m), 2),
            "is_rect": not lay.get("outline"), "openings": _openings(lay)}


def _library() -> Dict[str, Dict[str, Any]]:
    """The prop library keyed by id."""
    from app.core.props import list_props
    return {p["id"]: p for p in list_props()}


def _placements(lay: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in (lay.get("props") or []) if isinstance(p, dict)]


def _mount_of(prop: Dict[str, Any]) -> str:
    """How a library piece is mounted — an unclassified prop stands on the
    floor, which is what the solver assumes for it too."""
    return str(prop.get("mount") or "") or "floor"


def _aggregate(placements: List[Dict[str, Any]],
               library: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Placed props as ``{prop_id, name, count, mount, width_m, depth_m}`` —
    one entry per prop id, unknown ids skipped (they render as placeholders in
    the client but carry no dims to reason about)."""
    counts: Dict[str, int] = {}
    for p in placements:
        pid = str(p.get("prop_id") or "")
        if pid in library:
            counts[pid] = counts.get(pid, 0) + 1
    out = []
    for pid, count in counts.items():
        prop = library[pid]
        out.append({"prop_id": pid, "name": prop.get("name") or pid,
                    "count": count, "mount": _mount_of(prop),
                    "width_m": prop.get("width_m"),
                    "depth_m": prop.get("depth_m")})
    return sorted(out, key=lambda e: e["name"].lower())


def _floor_used_area(placements: List[Dict[str, Any]],
                     library: Dict[str, Dict[str, Any]]) -> float:
    """Footprint of what already stands ON THE FLOOR. A picture on the wall
    and a candle on the table cost no floor, so counting them would shrink
    the budget of the very pieces that need it — and a rug (an UNDERLAY,
    B10) is walked over, so it costs nothing either. The threshold for that
    is the solver's own, imported, never re-typed."""
    from app.core.furnish_solver import UNDERLAY_MAX_H
    total = 0.0
    for p in placements:
        prop = library.get(str(p.get("prop_id") or ""))
        if not prop or _mount_of(prop) != "floor":
            continue
        if float(prop.get("height_m") or 0) <= UNDERLAY_MAX_H:
            continue
        total += float(prop.get("width_m") or 0) * float(prop.get("depth_m") or 0)
    return total


# ── LLM plumbing ────────────────────────────────────────────────────────

def _list_field(obj: Dict[str, Any], key: str) -> List[Any]:
    """The expected list under ``key`` — falling back to an unwrapped array."""
    val = obj.get(key)
    if isinstance(val, list):
        return val
    val = obj.get("_list")
    return val if isinstance(val, list) else []


def _llm_json(task: str, system_prompt: str, user_prompt: str,
              label: str) -> Dict[str, Any]:
    """The shared strict-JSON hop (``llm_json``), failing as a
    :class:`FurnishError` — the job row shows that message verbatim, so the
    error type is what this job binds to the shared helper."""
    return llm_json(task, system_prompt, user_prompt, label, error=FurnishError)


# ── Proposal validation ─────────────────────────────────────────────────
#
# The need list and its match are validated in ``app.core.furnish_needs`` —
# pure functions with no DB and no world lookups. What stays here is what
# needs the JOB: the library pre-filter of a run and the admin's direct picks.

def _valid_picks(raw: Any, library: Dict[str, Dict[str, Any]]
                 ) -> List[Dict[str, Any]]:
    """The ADMIN's own picks (``start_direct``): only ids the library really
    has, counts 1..12, one entry per prop, at most as many entries as a need
    list may hold. This is a pick list, not a proposal — it becomes one."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or len(out) >= furnish_needs.MAX_NEEDS:
            continue
        pid = str(entry.get("prop_id") or "").strip()
        if pid not in library or pid in seen:
            continue
        seen.add(pid)
        out.append({"prop_id": pid, "count": furnish_needs.count(entry.get("count"))})
    return out


def _surface_kinds() -> List[Dict[str, str]]:
    """The surface-texture library as ``{key, label}`` — the very list the
    room editor's floor/wall pickers offer (``GET /assets/surface-textures``),
    so a kind the LLM may propose is a kind the admin could have picked."""
    from app.core.surface_textures import list_textures
    out: List[Dict[str, str]] = []
    seen: set = set()
    for entry in list_textures():
        kind = str(entry.get("kind") or "").strip()
        if not kind or kind in seen:
            continue
        seen.add(kind)
        out.append({"key": kind, "label": str(entry.get("name") or "") or kind})
    return out


def _valid_exclude(raw: Any) -> Dict[str, List[str]]:
    """Library pre-filter for stage 1: excluded props/categories/keywords
    are NOT offered to the LLM as available — so a room does not always get
    THE one bed the library has; the need list then asks for a fresh one.
    Kept small: exact ids, exact categories, substring keywords."""
    out: Dict[str, List[str]] = {"prop_ids": [], "categories": [], "keywords": []}
    if not isinstance(raw, dict):
        return out
    for key in out:
        vals = raw.get(key)
        if not isinstance(vals, list):
            continue
        seen: set = set()
        for v in vals[:64]:
            txt = str(v or "").strip().lower()[:60]
            if txt and txt not in seen:
                seen.add(txt)
                out[key].append(txt)
    return out


def _apply_exclude(library: Dict[str, Dict[str, Any]],
                   exclude: Any) -> Dict[str, Dict[str, Any]]:
    """The catalog the LLM may see. Matching: id exact, category exact,
    keyword as substring over name + tags. Empty filter = full library."""
    ex = _valid_exclude(exclude)
    if not (ex["prop_ids"] or ex["categories"] or ex["keywords"]):
        return library
    out: Dict[str, Dict[str, Any]] = {}
    for pid, prop in library.items():
        if pid.lower() in ex["prop_ids"]:
            continue
        if str(prop.get("category") or "").strip().lower() in ex["categories"]:
            continue
        hay = " ".join([str(prop.get("name") or "")]
                       + [str(t) for t in (prop.get("tags") or [])]).lower()
        if any(kw in hay for kw in ex["keywords"]):
            continue
        out[pid] = prop
    return out


# ── Phase 1: the room's need, then the library ──────────────────────────

def _setting(loc: Dict[str, Any], room: Dict[str, Any]) -> Tuple[str, bool, bool]:
    """``(setting sentence, is_yard, indoor)``.

    The setting is BINDING context for every stage (user finding 2026-08-20: a
    tree-only library got picked into a living room because the LLM never
    learned the room was indoors). The yard is open-air by nature — its record
    has no indoor flag, and falling back to the LOCATION's flag would call a
    house's yard "indoor".
    """
    from app.models.world import GROUND_ROOM_ID, resolve_indoor_flag
    is_yard = str(room.get("id") or "") == GROUND_ROOM_ID
    # ``resolve_indoor_flag`` answers "indoor" | "outdoor" | "" — a STRING, so
    # asking it for its truth called an explicitly OUTDOOR room indoor (v1
    # bug). Anything that is not "indoor" is open air, unset included, which
    # is the reading v1 had for the unset case.
    indoor = (not is_yard) and resolve_indoor_flag(loc, room) == "indoor"
    setting = ("open-air yard of the location" if is_yard
               else ("indoor room inside a building" if indoor
                     else "open-air area"))
    return setting, is_yard, indoor


def _opening_summary(openings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The room's openings as ``{type, count}`` — how many doors and how many
    windows, which is all the need list reasons about (one curtain per
    window). Where they sit is the placement stage's business."""
    counts: Dict[str, int] = {}
    for op in openings:
        kind = str((op or {}).get("type") or "door").strip().lower() or "door"
        counts[kind] = counts.get(kind, 0) + 1
    return [{"type": kind, "count": counts[kind]} for kind in sorted(counts)]


def _storey_height_m(loc: Dict[str, Any]) -> float:
    """The storey height the wall pass measures against (default 3 m)."""
    try:
        v = float((loc.get("map3d") or {}).get("storey_height_m") or 0)
    except (TypeError, ValueError):
        v = 0.0
    return round(v, 2) if v > 0 else 3.0


def _phase_needs(room_id: str) -> None:
    """Stage 1, inverted (plan-furnish-v2.md § 2 B3): ``furnish_needs`` writes
    the room's complete need WITHOUT the library, ``furnish_match`` then maps
    at most one library piece onto each need. Everything unmatched is built.

    The two calls are one phase: a match without a need list has nothing to
    match, and the admin is shown the joined result, not the halves.
    """
    from app.core.pose_catalog import get_groups
    from app.core.prompt_templates import render_task
    from app.models.world import get_room_activity_hint

    loc, room = _load_room(room_id)
    geom = _geometry(loc, room)
    library = _library()
    # The LLM only sees the FILTERED catalog (job's exclude filter) — full
    # library stays in use for resolving what already stands in the room.
    exclude = ((_get_row(room_id) or {}).get("proposal") or {}).get("exclude")
    catalog_lib = _apply_exclude(library, exclude)
    lay = geom["layout"]
    placed = _placements(lay)
    existing = _aggregate(placed, library)
    # The floor budget belongs to the FLOOR pieces alone (B3): what hangs on a
    # wall or stands on a table never took floor away in the first place.
    budget = max(0.0, geom["area_m2"] * BUDGET_FRACTION
                 - _floor_used_area(placed, library))
    room_name = _room_label(room)
    style_hint = str(room.get("style_hint") or loc.get("style_hint") or "")
    setting, is_yard, indoor = _setting(loc, room)
    # WHICH SURFACES ARE STILL BARE (E9/B15). Only a room whose layout names
    # neither a floor nor a wall kind gets a proposal — a room the admin has
    # dressed keeps what it has. The yard is out: its ground layout stores
    # props and nothing else (``world_ops.sanitize_ground_layout``), so a
    # surface row there would be a promise the accept path cannot keep.
    surfaces_stored = lay.get("surfaces") if isinstance(lay.get("surfaces"), dict) else {}
    surfaces_missing = (not is_yard
                        and not (surfaces_stored or {}).get("floor")
                        and not (surfaces_stored or {}).get("wall"))
    surface_kinds = _surface_kinds() if surfaces_missing else []
    # The place types a marker may name — the LLM sees key + label.
    groups = get_groups()

    sys_p, user_p = render_task(
        "furnish_needs", setting=setting, room_name=room_name,
        room_description=str(room.get("description") or ""),
        activity_hint=get_room_activity_hint(str(loc.get("id") or ""),
                                             str(room.get("id") or "")),
        style_hint=style_hint,
        room_w_m=geom["w_m"], room_d_m=geom["d_m"], area_m2=geom["area_m2"],
        budget_m2=round(budget, 2), max_needs=furnish_needs.MAX_NEEDS,
        storey_height_m=_storey_height_m(loc),
        openings=_opening_summary(geom["openings"]),
        existing=[{"name": e["name"], "count": e["count"], "mount": e["mount"]}
                  for e in existing],
        marker_groups=[{"key": k, "label": g.get("label") or k}
                       for k, g in groups.items()],
        key_area_kinds=furnish_needs.key_area_kinds(),
        surfaces_missing=surfaces_missing, surface_kinds=surface_kinds)
    answer = _llm_json("furnish_needs", sys_p, user_p,
                       f"Furnish needs: {room_name}")
    needs, dropped = furnish_needs.valid_needs(
        _list_field(answer, "needs"), list(groups), is_yard=is_yard)
    surfaces = (furnish_needs.valid_surfaces(
        answer.get("surfaces"), [k["key"] for k in surface_kinds])
        if surfaces_missing else None)
    if not _get_row(room_id):
        return  # discarded while the LLM was busy

    # ── the library, second ─────────────────────────────────────────────
    catalog, by_ref = furnish_needs.build_catalog(catalog_lib, indoor=indoor)
    matches: Dict[str, str] = {}
    if needs and catalog:
        sys_p, user_p = render_task(
            "furnish_match", setting=setting, room_name=room_name,
            style_hint=style_hint,
            needs=[{k: n[k] for k in ("key", "kind", "category", "count",
                                      "mount", "width_m", "depth_m",
                                      "height_m", "style")} for n in needs],
            catalog=catalog)
        matches = furnish_needs.valid_matches(
            _list_field(_llm_json("furnish_match", sys_p, user_p,
                                  f"Furnish match: {room_name}"), "matches"),
            needs, by_ref, catalog_lib)
    # An empty catalog needs no call: with nothing to choose from every
    # answer is null, and asking a model to say so costs a minute of GPU.
    furnish_needs.attach_matches(needs, matches)

    if not _get_row(room_id):
        return
    _update_row(room_id, state=STATE_PROPOSAL_READY, error="",
                proposal={"needs": needs, "surfaces": surfaces,
                          "dropped": dropped,
                          **({"exclude": _valid_exclude(exclude)} if exclude else {})})
    logger.info("room_furnish %s: proposal ready (%d needs, %d matched, "
                "%d dropped)", room_id, len(needs), len(matches), len(dropped))


# ── Phase 2: placing (before generating, E6) ────────────────────────────

def _edge_wall(outline_m: List[List[float]], idx: int) -> str:
    """Compass class N/E/S/W of a polygon edge — from its OUTWARD normal
    (screen coordinates, y points south)."""
    n = len(outline_m)
    a = outline_m[idx % n]
    b = outline_m[(idx + 1) % n]
    ex, ey = b[0] - a[0], b[1] - a[1]
    normal = (ey, -ex)
    cx = sum(p[0] for p in outline_m) / n
    cy = sum(p[1] for p in outline_m) / n
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if normal[0] * (cx - mid[0]) + normal[1] * (cy - mid[1]) > 0:
        normal = (-normal[0], -normal[1])  # flip to point OUT of the room
    if abs(normal[0]) > abs(normal[1]):
        return "E" if normal[0] > 0 else "W"
    return "S" if normal[1] > 0 else "N"


def _openings(lay: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Openings with polygon edge INDICES — letter edges are converted with
    the same rule the room recipe uses (one source of truth)."""
    from app.core.room_recipe import _normalize_opening
    return [_normalize_opening(op) for op in (lay.get("openings") or [])
            if isinstance(op, dict)]


def _stack_facts(library: Dict[str, Dict[str, Any]]):
    """The ``facts`` callable ``compose_on_chain`` asks for: height and sink
    of the VARIANT a placement draws, out of the library listing this phase
    already holds. The resolution rule itself is the recipe's
    (``room_recipe.placement_stack_facts``) — a second one would be a second
    answer to "how tall is this piece"."""
    from app.core.room_recipe import placement_stack_facts

    def facts(prop_id: str, variant: Any) -> Dict[str, Any]:
        return placement_stack_facts(library.get(str(prop_id or "")), variant)
    return facts


def _empty_placements() -> Dict[str, Any]:
    from app.core.furnish_place import MOUNTS
    return {"placed": [], "unplaced": [],
            "phase_counts": {m: {"placed": 0, "unplaced": 0} for m in MOUNTS}}


def _phase_place(room_id: str) -> None:
    """Plan and solve the whole room — one ``furnish_place`` call plus up to
    three per-pass repair rounds (``app.core.furnish_place``).

    Nothing here is generated: since E6 a need that has no library piece is
    placed under its temporary id with its own dimensions, and ``accept``
    turns those ids into props. What this phase owns is the WORLD side of the
    plan — the room's geometry, the library and what already stands in it.
    """
    from app.core import furnish_place
    from app.core.room_recipe import compose_on_chain
    from app.models.notifications import create_notification

    row = _get_row(room_id)
    if not row:
        return
    _update_row(room_id, state=STATE_PLACING)
    loc, room = _load_room(room_id)
    geom = _geometry(loc, room)
    library = _library()
    lay = geom["layout"]
    items = furnish_place.build_items(_needs(row.get("proposal")), library)
    room_name = _room_label(room)
    storey_height_m = _storey_height_m(loc)

    if not items:
        _update_row(room_id, state=STATE_REVIEW_READY, error="",
                    placements=_empty_placements())
        return

    placed_props = _placements(lay)
    # THE SOLVER WORKS FROM THE POLYGON'S MIN CORNER. For a room that IS the
    # stored frame; on the ground the stored frame is the location's, so
    # everything handed in is shifted by the origin and every result is
    # shifted back (see `_geometry`). For a room both shifts are 0.
    ox, oy = geom["origin"]
    # WHAT ALREADY STANDS THERE, COMPOSED. A placement may sit ON another one
    # (decision E1) and then stores its pose in the SUPPORT's frame; the
    # solver wants boxes in room metres, so the parent link is resolved by the
    # one function that resolves it (``room_recipe.compose_on_chain``) before
    # the yard's origin shift moves the whole room into the solver's frame.
    composed = compose_on_chain(placed_props, _stack_facts(library))
    existing_solver = [{"prop_id": p.get("prop_id"),
                        "id": p.get("id") or "",
                        "at": [c["at"][0] - ox, c["at"][1] - oy],
                        "yaw": c["yaw"], "offset_y": c["offset_y"],
                        "on": c["on"]}
                       for p, c in zip(placed_props, composed)]

    def _name_of(prop_id: Any) -> str:
        pid = str(prop_id or "")
        return str((library.get(pid) or {}).get("name") or pid)

    by_place_id = {str(p.get("id") or ""): p for p in placed_props}
    template_existing = [
        {"id": str(p.get("id") or ""),
         "name": _name_of(p.get("prop_id")),
         "mount": _mount_of(library.get(str(p.get("prop_id") or "")) or {}),
         # Told in the SOLVER's frame, so the model's "beside the table"
         # refers to the same numbers the solver reasons about.
         "x_m": round(c["at"][0] - ox, 2),
         "y_m": round(c["at"][1] - oy, 2),
         "yaw": round(float(c["yaw"] or 0.0), 1),
         "on": _name_of((by_place_id.get(c["on"]) or {}).get("prop_id"))
         if c["on"] else ""}
        for p, c in zip(placed_props, composed)]
    template_openings = [
        {"index": i,
         "type": op.get("type") or "door",
         "wall": _edge_wall(geom["outline_m"], int(op.get("edge") or 0)),
         "at_frac": round(float(op.get("at") or 0.5), 2),
         "width_m": op.get("width_m"), "sill_m": op.get("sill_m") or 0,
         "height_m": op.get("height_m") or 2.1}
        for i, op in enumerate(geom["openings"])]

    def _ask(system_prompt: str, user_prompt: str, suffix: str) -> Dict[str, Any]:
        # The re-plan rounds carry their own label — otherwise they are
        # indistinguishable from the first attempt in the LLM log and read
        # as duplicate submits.
        return _llm_json("furnish_place", system_prompt, user_prompt,
                         f"Furnish place: {room_name}{suffix}")

    result = furnish_place.run(
        room_name=room_name, room_description=str(room.get("description") or ""),
        geom=geom, storey_height_m=storey_height_m, items=items,
        props=furnish_place.solver_props(items, library),
        existing=existing_solver, template_existing=template_existing,
        template_openings=template_openings, ask=_ask,
        alive=lambda: _get_row(room_id) is not None)

    for entry in result.get("placed") or []:
        # A piece standing ON another one is stored in its SUPPORT's frame
        # (E1) — those metres are relative and must not be moved with the
        # yard's origin, or the candle would leave the table.
        if entry.get("on"):
            continue
        at = entry.get("at") or [0, 0]
        entry["at"] = [round(float(at[0]) + ox, 2),
                       round(float(at[1]) + oy, 2)]

    if not _get_row(room_id):
        return
    _update_row(room_id, state=STATE_REVIEW_READY, error="", placements=result)
    counts = furnish_place.pass_summary(result.get("phase_counts") or {})
    total_placed = len(result.get("placed") or [])
    total = total_placed + len(result.get("unplaced") or [])
    per_pass = ", ".join(
        f"{name} {counts[name]['placed']}/"
        f"{counts[name]['placed'] + counts[name]['unplaced']}"
        for name in furnish_place.PASSES)
    create_notification(
        room_name,
        f"Furnishing ready for review — {total_placed} of {total} pieces "
        f"placed in {room_name} ({per_pass}).",
        notification_type="room_furnish",
        metadata={"room_id": room_id, "location_id": row.get("location_id")})
    logger.info("room_furnish %s: review ready (%d placed, %d unplaced — %s)",
                room_id, total_placed, total - total_placed, per_pass)

# ── Phase 3: generating (after accept, E6) ──────────────────────────────

def _phase_generate(room_id: str) -> None:
    """Bake a mesh for every need that had to be built — the LAST phase since
    E6, entered by ``accept``.

    The props themselves already exist: ``accept`` created them so the layout
    could name them, which is also what makes this phase re-enterable. A prop
    that already carries a model is skipped, so a restart mid-generation picks
    up exactly where the thread died and never orders the same mesh twice.
    """
    from app.core.props import is_pending, trigger_generation

    row = _get_row(room_id)
    proposal = (row or {}).get("proposal") or {}
    for item in _ordered_builds(proposal):
        if _prop_ready(item.get("prop_id")):
            continue
        pid = str(item["prop_id"])
        # Automatic path = nobody clicks a dialog, so face count and texture
        # size derive from the piece's REAL size (the 3D client's asset-sizing
        # recommendation): faces ~6000 x largest edge clamped to 2k..20k,
        # texture 512 (<=0.5 m) / 1024 (<1.5 m) / 2048.
        max_dim = max(float(item.get("width_m") or 0),
                      float(item.get("depth_m") or 0),
                      float(item.get("height_m") or 0)) or 1.0
        face_num = max(2000, min(20000, int(round(6000 * max_dim))))
        texture_size = 512 if max_dim <= 0.5 else (1024 if max_dim < 1.5 else 2048)
        # A chain that is still running after a restart is waited for, not
        # ordered a second time — the queue would run the same mesh twice.
        if not is_pending(pid):
            trigger_generation(pid, face_num=face_num,
                               texture_size=texture_size)
        deadline = time.monotonic() + MODEL_TIMEOUT_SECONDS
        while not _prop_ready(pid):
            if not _get_row(room_id):
                return  # job discarded mid-generation
            if not is_pending(pid):
                # The chain ended WITHOUT a model (source render or mesh
                # failed) — fail fast instead of burning the full timeout.
                raise FurnishError(
                    f"Model generation for '{item.get('kind')}' failed — see "
                    "the queue panel / server log, then Retry.")
            if time.monotonic() > deadline:
                raise FurnishError(
                    f"Model generation for '{item.get('kind')}' timed out.")
            time.sleep(MODEL_POLL_SECONDS)
        _update_row(room_id, state=STATE_GENERATING)  # bump updated_at (n/m)
        logger.info("room_furnish %s: prop %s ready", room_id, pid)

    # Everything is baked — the placements have been in the room since accept,
    # so the job has nothing left to be and goes away. Same close as the
    # self-healing read's, so both ends post the same line once.
    row = _get_row(room_id)
    if row:
        _close_finished(room_id, row)

# ── Orchestrator thread ─────────────────────────────────────────────────

def _pipeline(room_id: str, phase: str) -> None:
    """One phase per thread. Since E6 the three phases no longer chain into
    each other: placing waits for the admin's ``accept``, and generating is
    what ``accept`` starts."""
    if phase == "needs":
        _phase_needs(room_id)
    elif phase == "place":
        _phase_place(room_id)
    elif phase == "generate":
        _phase_generate(room_id)


def _spawn(room_id: str, phase: str, label: str) -> bool:
    """Start the orchestrator thread for one phase chain. False when this room
    already has a running thread (double-start guard)."""
    with _lock:
        if room_id in _running:
            return False
        _running.add(room_id)

    def _run() -> None:
        from app.core.task_queue import get_task_queue
        task_id = ""
        try:
            task_id = get_task_queue().track_start("room_furnish", f"Furnish: {label}")
        except Exception:
            task_id = ""
        error = ""
        try:
            _pipeline(room_id, phase)
        except FurnishError as e:
            error = e.message
            _fail(room_id, e.message)
        except Exception as e:  # noqa: BLE001 — a job must never kill the thread silently
            error = str(e)
            logger.exception("room_furnish %s crashed", room_id)
            _fail(room_id, f"{type(e).__name__}: {e}"[:300])
        finally:
            with _lock:
                _running.discard(room_id)
            if task_id:
                try:
                    get_task_queue().track_finish(task_id, error=error)
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()
    return True


def _resume_phase(row: Dict[str, Any]) -> str:
    """Which phase a persisted job has to re-enter — derived from its DATA,
    not from the state it died in, so retry and continue share one path.

    The ``accepted`` flag is what makes the split unambiguous since E6: a job
    that has written its placements into the room is past placing forever and
    can only still owe meshes, whichever state its thread died in.
    """
    needs = _needs(row.get("proposal"))
    if not needs:
        return "needs"
    state = row.get("state")
    if state in (STATE_PROPOSAL_READY, STATE_REVIEW_READY):
        return ""  # waiting for the admin, nothing to resume
    placements = row.get("placements") or {}
    if _accepted(placements) or state == STATE_GENERATING:
        return "generate" if _pending_builds(row.get("proposal")) else ""
    if not placements.get("placed"):
        return "place"
    return ""


# ── One-time cleanup ────────────────────────────────────────────────────

def drop_legacy_jobs() -> int:
    """Delete every furnish job still carrying the v1 proposal (``existing`` /
    ``new`` instead of ``needs``), called once at boot.

    There is no fallback reader for that shape (plan-furnish-v2.md § 4,
    decision E4) and there is no history to preserve: a job is a proposal
    waiting for the admin, and the admin starts a new one in seconds. Deleting
    it is what keeps the dialog from showing a list nothing can confirm.
    Idempotent by construction — a row of the new shape is never touched, so
    no flag is needed.
    """
    try:
        rows = get_connection().execute(
            "SELECT room_id, proposal FROM room_furnish").fetchall()
    except Exception as e:
        logger.error("room_furnish legacy scan failed: %s", e)
        return 0
    stale = []
    for room_id, raw in rows:
        proposal = _loads(raw)
        if not isinstance(proposal, dict) or "needs" in proposal:
            continue
        if "existing" in proposal or "new" in proposal:
            stale.append(room_id)
    for room_id in stale:
        _delete_row(room_id)
    if stale:
        logger.info("room_furnish: %d legacy job(s) dropped (%s)",
                    len(stale), ", ".join(stale))
    return len(stale)


# ── Public job API ──────────────────────────────────────────────────────

def start(room_id: str, exclude: Any = None) -> Dict[str, Any]:
    """Open a furnishing job for a room and kick off stage 1. ``exclude``
    pre-filters the library the LLM gets to see (see _valid_exclude) — it is
    persisted with the job so retry/continue keep the same filter."""
    loc, room = _load_room(room_id)
    _geometry(loc, room)  # a drawn plan (yard: a drawn boundary) is the start
    if _get_row(room_id):
        raise FurnishError("A furnishing job for this room is already open.", 409)
    _insert_row(room_id, str(loc.get("id") or ""))
    ex = _valid_exclude(exclude)
    if ex["prop_ids"] or ex["categories"] or ex["keywords"]:
        _update_row(room_id, proposal={"exclude": ex})
    _spawn(room_id, "needs", _room_label(room))
    return get_status(room_id) or {}


def start_direct(room_id: str, proposal: Any) -> Dict[str, Any]:
    """Skip stage 1 entirely: place ONLY admin-picked library props (user
    requirement 2026-07-23). The picks BECOME needs — each one already served
    by its prop, so nothing is ever built — and the job enters straight at the
    placement phase; review/accept work exactly like the LLM path, and accept
    finds nothing to generate.

    ``proposal`` is the picker's ``{existing: [{prop_id, count}]}`` — a list
    of library pieces, not a proposal shape."""
    loc, room = _load_room(room_id)
    _geometry(loc, room)  # a drawn plan (yard: a drawn boundary) is the start here too
    if _get_row(room_id):
        raise FurnishError("A furnishing job for this room is already open.", 409)
    library = _library()
    picks = _valid_picks(
        proposal.get("existing") if isinstance(proposal, dict) else None,
        library)
    if not picks:
        raise FurnishError("Pick at least one library prop.", 400)
    needs = []
    for i, pick in enumerate(picks, 1):
        prop = library[pick["prop_id"]]
        needs.append({
            "key": f"n{i}",
            "kind": str(prop.get("name") or pick["prop_id"]),
            "category": str(prop.get("category") or ""),
            "count": pick["count"],
            "mount": _mount_of(prop),
            "width_m": prop.get("width_m"), "depth_m": prop.get("depth_m"),
            "height_m": prop.get("height_m"),
            "style": "", "description": str(prop.get("description") or ""),
            "marker": None, "key_areas": [], "from_description": False,
            "prop_id": pick["prop_id"], "build": False})
    _insert_row(room_id, str(loc.get("id") or ""))
    _update_row(room_id, state=STATE_PLACING,
                proposal={"needs": needs, "surfaces": None, "dropped": []})
    _spawn(room_id, "place", _room_label(room))
    return get_status(room_id) or {}


def confirm(room_id: str, proposal: Any) -> Dict[str, Any]:
    """Persist the admin-edited need list and place the room (E6).

    The EDITED list is validated exactly like the model's own: same shape,
    same limits, keys re-minted. ``build`` is never taken from the client —
    it is derived from ``prop_id``, so a dialog cannot declare a piece
    "already built" and skip the prop that has to be made for it.
    """
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] != STATE_PROPOSAL_READY:
        raise FurnishError(f"Cannot confirm in state '{row['state']}'.", 409)
    from app.core.pose_catalog import get_groups
    loc, room = _load_room(room_id)
    raw = proposal if isinstance(proposal, dict) else (row["proposal"] or {})
    stored = row["proposal"] or {}
    _setting_text, is_yard, _indoor = _setting(loc, room)
    needs, dropped = furnish_needs.valid_needs(
        raw.get("needs"), list(get_groups()), is_yard=is_yard,
        library=_library())
    if not needs:
        raise FurnishError("The confirmed list is empty.", 400)
    clean: Dict[str, Any] = {
        "needs": needs,
        "surfaces": furnish_needs.valid_surfaces(
            raw.get("surfaces"), [k["key"] for k in _surface_kinds()]),
        "dropped": dropped,
    }
    if stored.get("exclude"):
        clean["exclude"] = _valid_exclude(stored.get("exclude"))
    _update_row(room_id, state=STATE_PLACING, error="", proposal=clean)
    _spawn(room_id, "place", _room_label(room))
    return get_status(room_id) or {}


def _create_built_props(needs: List[Dict[str, Any]], placed_ids: set
                        ) -> Tuple[Dict[str, str], List[str]]:
    """Turn every PLACED need that has to be built into a real library prop.

    Answers ``({"need:<key>": "<prop id>"}, [skipped kind, ...])`` — the
    rewrite map for the accepted placements (E6) and the kinds that got no
    piece.

    BUILD ONLY WHAT WAS PLACED (controller ruling 2026-09-07). A need the
    solver could not fit, or one the admin dragged out of the review, is a
    piece nobody will ever see: making it would spend GPU minutes on a library
    entry the admin never asked for. The empty-accept case is not a special
    rule any more, it is this one with an empty set.

    This is the moment the placeholder becomes a piece: until now the plan
    named the need by a temporary id and the solver placed its bare
    dimensions. The prop is created here rather than in the generation phase
    so the layout can name it the instant it is written, and so a restart
    mid-generation finds it instead of creating it twice.
    """
    from app.core.furnish_place import NEED_ID_PREFIX
    from app.core.props import create_prop, set_variant_markers

    rewrite: Dict[str, str] = {}
    skipped: List[str] = []
    for need in needs:
        if not need.get("build") or need.get("prop_id"):
            continue
        temp_id = f"{NEED_ID_PREFIX}{need.get('key') or ''}"
        if temp_id not in placed_ids:
            skipped.append(str(need.get("kind") or temp_id))
            continue
        prop = create_prop(
            name=str(need.get("kind") or "Prop").title(),
            category=need.get("category") or "",
            width_m=need.get("width_m"), depth_m=need.get("depth_m"),
            height_m=need.get("height_m"),
            description=need.get("description") or "", source="generated",
            # What the piece IS, from the need list: how it is mounted (the
            # solver's pass) and which panels its generation has to key out —
            # a new picture frame without a `picture` area would never show a
            # picture (B13).
            mount=need.get("mount") or "",
            key_areas=need.get("key_areas") or None)
        need["prop_id"] = prop["id"]
        rewrite[temp_id] = prop["id"]
        if need.get("marker"):
            # Onto the freshly created prop's FIRST variant — the marker
            # describes the mesh this run is about to bake, and markers belong
            # to the variant since 2026-08-25.
            set_variant_markers(prop["id"], 0, [need["marker"]])
    return rewrite, skipped


def accept(room_id: str, placements: Any = None) -> Dict[str, Any]:
    """Write the (possibly hand-adjusted) placements into ``layout.props``,
    then generate what is still missing (E6).

    Four steps, in this order: the pieces that were PLACED and had to be built
    become props, those ids are persisted on the row, the placements that
    named them by their temporary id are rewritten, and the whole list is
    appended to the room. Only then does the job switch to ``generating`` —
    the room is already furnished with placeholder boxes, and the meshes drop
    in one by one.

    THE IDS ARE PERSISTED BEFORE THE LAYOUT WRITE, not after: a layout write
    that fails leaves the job in ``review_ready``, and without that row update
    a second accept would create every prop a second time.

    ``on`` is untouched by the rewrite: it names a PLACEMENT, not a prop.
    """
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] != STATE_REVIEW_READY:
        raise FurnishError(f"Cannot accept in state '{row['state']}'.", 409)
    stored = row.get("placements") or {}
    entries = [e for e in (placements if isinstance(placements, list)
                           else stored.get("placed") or [])
               if isinstance(e, dict)]
    proposal = row.get("proposal") or {}
    needs = _needs(proposal)
    placed_ids = {str(e.get("prop_id") or "") for e in entries}

    rewrite, skipped = _create_built_props(needs, placed_ids)
    if rewrite and not _update_row(room_id, proposal=proposal):
        raise FurnishError("No furnishing job for this room.", 404)
    for entry in entries:
        if entry.get("prop_id") in rewrite:
            entry["prop_id"] = rewrite[entry["prop_id"]]

    from app.models.world import append_room_props
    # The job id may be the composite yard one — what gets written is the ROOM.
    target_room, _loc_id = _target(room_id)
    if entries and not append_room_props(row["location_id"], target_room,
                                         entries):
        raise FurnishError("The room layout could not be updated.", 409)
    logger.info("room_furnish %s: %d placements accepted, %d prop(s) created, "
                "%d not built (%s)", room_id, len(entries), len(rewrite),
                len(skipped), ", ".join(skipped) or "-")
    if skipped:
        _skipped_notification(room_id, str(row.get("location_id") or ""),
                              len(entries), skipped)

    pending = _pending_builds(proposal)
    if not pending:
        _delete_row(room_id)
        return {"status": "accepted", "placed": len(entries), "generating": 0}
    # The layout write has happened — the flag says so, so a restart during
    # the generation resumes into the mesh phase instead of appending again.
    _update_row(room_id, state=STATE_GENERATING, error="", proposal=proposal,
                placements={**stored, "placed": entries, "accepted": True})
    _spawn(room_id, "generate", _room_label(_load_room(room_id)[1]))
    return {"status": "accepted", "placed": len(entries),
            "generating": len(pending)}


def discard(room_id: str) -> Dict[str, Any]:
    """Drop the job (the generated props stay in the library)."""
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] == STATE_GENERATING and _pending_builds(row.get("proposal")):
        # The placements are already in the room and the meshes are on their
        # way — dropping the row here would only orphan the progress display.
        # Once every ordered mesh has landed the row is just a leftover and
        # goes like any other.
        raise FurnishError(
            "The meshes for this room are being generated — wait for them or "
            "cancel the jobs in the queue panel.", 409)
    if not _delete_row(room_id):
        raise FurnishError("No furnishing job for this room.", 404)
    return {"status": "discarded"}


def reset(room_id: str) -> Dict[str, Any]:
    """Throw away a stage-1 proposal so a new one can be requested."""
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] not in (STATE_SELECTING, STATE_PROPOSAL_READY, STATE_ERROR):
        raise FurnishError(f"Cannot reset in state '{row['state']}'.", 409)
    _delete_row(room_id)
    return {"status": "reset"}


def retry(room_id: str) -> Dict[str, Any]:
    """Re-enter a failed job at its persisted state."""
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] != STATE_ERROR:
        raise FurnishError("Only a failed job can be retried.", 409)
    return _resume(row)


def resume(room_id: str) -> Dict[str, Any]:
    """Continue a job whose orchestrator thread died with the server."""
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] not in _ACTIVE_STATES:
        raise FurnishError(f"Nothing to continue in state '{row['state']}'.", 409)
    with _lock:
        if room_id in _running:
            raise FurnishError("This job is already running.", 409)
    return _resume(row)


def _resume(row: Dict[str, Any]) -> Dict[str, Any]:
    room_id = row["room_id"]
    phase = _resume_phase(row)
    if not phase:
        # An accepted job whose meshes all arrived while no thread was
        # watching is FINISHED, not stuck — close it instead of refusing it,
        # or the room keeps a row no verb accepts (see _close_finished).
        if _close_finished(room_id, row):
            return {"status": "finished"}
        raise FurnishError("This job has nothing left to do.", 409)
    _, room = _load_room(room_id)
    state = {"needs": STATE_SELECTING, "generate": STATE_GENERATING,
             "place": STATE_PLACING}[phase]
    _update_row(room_id, state=state, error="")
    if not _spawn(room_id, phase, _room_label(room)):
        raise FurnishError("This job is already running.", 409)
    return get_status(room_id) or {}
