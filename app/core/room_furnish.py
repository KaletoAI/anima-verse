"""Room furnishing job (plan-room-furnish.md) — the "✨ Furnish" workflow.

The LLM delivers SEMANTICS, never coordinates: it picks library props
(``furnish_select``), proposes the missing pieces (``furnish_new``) and
arranges them RELATIONALLY (``furnish_place``); the deterministic
``furnish_solver`` turns that plan into ``layout.props`` geometry.

Because generation takes minutes, the whole thing is a PERSISTED job — one
row per room, one in-process orchestrator thread (pattern:
``props.trigger_generation``). The dialog is only a view on that row and may
be closed at any time; a server restart kills the thread but not the state,
which is why every phase re-enters idempotently (``resume``/``retry``).

States and their transitions::

    selecting ──▶ proposal_ready ──confirm──▶ generating ──▶ placing
                                                                │
                        error ◀── any phase failing             ▼
                                                          review_ready
                                                       (accept | discard)

``accept``/``discard``/``reset`` DELETE the row — there is no history; the
provenance of a run lives in the job log / queue panel (the layout sanitizer
strips foreign fields, so per-placement provenance is impossible anyway).

Everything the job writes outside its own row is normal world data: new
props are ordinary library entries (they survive a discarded proposal) and
accepted placements are appended to ``layout.props`` via
``world.append_room_props``.
"""

import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
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
_ACTIVE_STATES = (STATE_SELECTING, STATE_GENERATING, STATE_PLACING)

# Share of the floor area the summed footprints may occupy — the same hard
# limit the solver enforces; here it only sizes the prompt's budget.
BUDGET_FRACTION = 0.45
MAX_ITEMS = 20            # cap on the total pieces furnish_select may pick
MAX_NEW_KINDS = 8         # cap on the piece KINDS furnish_new may invent
MAX_COUNT = 12            # per entry
MIN_DIM_M = 0.05
MAX_DIM_M = 5.0
MODEL_POLL_SECONDS = 5
MODEL_TIMEOUT_SECONDS = 30 * 60

_UNIT_SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

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


def _progress(proposal: Any) -> Dict[str, int]:
    """Generation progress n/m over the NEW pieces — derived, not stored:
    a piece counts as done when its prop exists and has a model."""
    new = (proposal or {}).get("new") if isinstance(proposal, dict) else None
    new = new if isinstance(new, list) else []
    return {"done": sum(1 for n in new if _prop_ready((n or {}).get("prop_id"))),
            "total": len(new)}


def get_status(room_id: str) -> Optional[Dict[str, Any]]:
    """The job's full status payload, or None when there is no job."""
    row = _get_row(room_id)
    if not row:
        return None
    with _lock:
        running = room_id in _running
    row["running"] = running
    # After a restart the state survives but the thread does not — the dialog
    # offers "Continue" exactly for this.
    row["stalled"] = row["state"] in _ACTIVE_STATES and not running
    row["progress"] = _progress(row.get("proposal"))
    return row


# ── World lookups / geometry ────────────────────────────────────────────

def _load_room(room_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from app.models.world import find_location_by_room, get_room_by_id
    loc = find_location_by_room(room_id)
    room = get_room_by_id(loc, room_id) if loc else None
    if not loc or not room:
        raise FurnishError("Room not found", 404)
    return loc, room


def _poly_area(pts: List[List[float]]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _geometry(loc: Dict[str, Any], room: Dict[str, Any]) -> Dict[str, Any]:
    """The room's floor plan in REAL METRES. Raises when the room has no
    layout or the location has no scale anchor (the metre polygon is
    undefined without one)."""
    lay = room.get("layout")
    if not isinstance(lay, dict) or not all(k in lay for k in ("x", "y", "w", "d")):
        raise FurnishError(
            "This room has no floor plan yet — draw its layout first.", 409)
    from app.core.location_model3d import derive_plan_width_m
    plan_w = derive_plan_width_m(str(loc.get("id") or ""), loc.get("map3d"))
    if plan_w <= 0:
        raise FurnishError(
            "This location has no scale anchor: set the plan width (m) or give "
            "the building model a declared height.", 409)
    w_m = round(float(lay["w"]) * plan_w, 3)
    d_m = round(float(lay["d"]) * plan_w, 3)
    pts = lay.get("outline") or _UNIT_SQUARE
    outline_m = [[round(float(p[0]) * w_m, 3), round(float(p[1]) * d_m, 3)]
                 for p in pts]
    return {"layout": lay, "plan_width_m": plan_w, "w_m": w_m, "d_m": d_m,
            "outline_m": outline_m, "area_m2": round(_poly_area(outline_m), 2),
            "is_rect": not lay.get("outline")}


def _library() -> Dict[str, Dict[str, Any]]:
    """The prop library keyed by id."""
    from app.core.props import list_props
    return {p["id"]: p for p in list_props()}


def _placements(lay: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in (lay.get("props") or []) if isinstance(p, dict)]


def _aggregate(placements: List[Dict[str, Any]],
               library: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Placed props as ``{prop_id, name, count, width_m, depth_m}`` — one
    entry per prop id, unknown ids skipped (they render as placeholders in
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
                    "count": count, "width_m": prop.get("width_m"),
                    "depth_m": prop.get("depth_m")})
    return sorted(out, key=lambda e: e["name"].lower())


def _used_area(placements: List[Dict[str, Any]],
               library: Dict[str, Dict[str, Any]]) -> float:
    total = 0.0
    for p in placements:
        prop = library.get(str(p.get("prop_id") or ""))
        if prop:
            total += float(prop.get("width_m") or 0) * float(prop.get("depth_m") or 0)
    return total


# ── LLM plumbing ────────────────────────────────────────────────────────

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)
_JSON_ARR_RE = re.compile(r"\[.*\]", re.S)


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """Strict-ish JSON extraction: the answer must contain ONE object; code
    fences and stray prose around it are tolerated, everything else is a
    parse failure (the caller retries once). A bare top-level ARRAY — the
    common "forgot the wrapper" slip — is accepted as ``{"_list": [...]}``."""
    text = (raw or "").strip()
    if not text:
        return None
    match = _JSON_OBJ_RE.search(text)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    match = _JSON_ARR_RE.search(text)
    if match:
        try:
            arr = json.loads(match.group(0))
            if isinstance(arr, list):
                return {"_list": arr}
        except ValueError:
            pass
    return None


def _list_field(obj: Dict[str, Any], key: str) -> List[Any]:
    """The expected list under ``key`` — falling back to an unwrapped array."""
    val = obj.get(key)
    if isinstance(val, list):
        return val
    val = obj.get("_list")
    return val if isinstance(val, list) else []


def _llm_json(task: str, system_prompt: str, user_prompt: str,
              label: str) -> Dict[str, Any]:
    """One LLM task expecting a JSON object, with EXACTLY one repair attempt
    (the model gets its own broken answer back and is asked for valid JSON)."""
    from app.core.llm_router import llm_call
    response = llm_call(task=task, system_prompt=system_prompt,
                        user_prompt=user_prompt, agent_name="system", label=label)
    raw = str(getattr(response, "content", "") or "")
    obj = _parse_json(raw)
    if obj is not None:
        return obj
    logger.info("room_furnish %s: unparsable answer, one repair attempt", task)
    repair = (f"{raw[:4000]}\n\n"
              "That was not valid JSON. Return the SAME content as a single "
              "valid JSON object — no markdown, no code fence, no explanation.")
    response = llm_call(task=task, system_prompt=system_prompt,
                        user_prompt=repair, agent_name="system",
                        label=f"{label} (repair)")
    obj = _parse_json(str(getattr(response, "content", "") or ""))
    if obj is None:
        raise FurnishError(f"The {task} answer was not valid JSON.")
    return obj


def _num(value: Any, lo: float, hi: float) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, 3) if lo <= v <= hi else None


def _count(value: Any) -> int:
    try:
        return max(1, min(MAX_COUNT, int(float(value))))
    except (TypeError, ValueError):
        return 1


# ── Proposal validation ─────────────────────────────────────────────────

def _valid_existing(raw: Any, library: Dict[str, Dict[str, Any]],
                    limit: int = MAX_ITEMS) -> List[Dict[str, Any]]:
    """Library picks: only ids the library really has, counts 1..12, total
    pieces capped. Unknown entries are dropped silently."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    total = 0
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("prop_id") or "").strip()
        if pid not in library or pid in seen:
            continue
        count = _count(entry.get("count"))
        if total + count > limit:
            count = limit - total
            if count <= 0:
                break
        seen.add(pid)
        total += count
        out.append({"prop_id": pid, "count": count})
    return out


def _valid_marker(raw: Any, kinds: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    anim = str(raw.get("animation") or "").strip()
    if not anim or (kinds and anim not in kinds):
        return None
    at = raw.get("at")
    if not isinstance(at, (list, tuple)) or len(at) != 3:
        at = [0.5, 0.5, 0.5]
    try:
        at3 = [round(min(max(float(at[i]), 0.0), 1.0), 4) for i in range(3)]
    except (TypeError, ValueError):
        at3 = [0.5, 0.5, 0.5]
    return {"animation": anim, "at": at3}


def _valid_new(raw: Any, kinds: List[str],
               limit: int = MAX_NEW_KINDS) -> List[Dict[str, Any]]:
    """New pieces: name/description non-empty, dims 0.05..5 m, counts 1..12,
    marker optional. ``prop_id`` is carried over when present (idempotent
    re-entry after a restart)."""
    out: List[Dict[str, Any]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or len(out) >= limit:
            continue
        name = str(entry.get("name") or "").strip()
        description = str(entry.get("description") or "").strip()
        if not name or not description:
            continue
        dims = {}
        for key in ("width_m", "depth_m", "height_m"):
            v = _num(entry.get(key), MIN_DIM_M, MAX_DIM_M)
            if v is None:
                break
            dims[key] = v
        if len(dims) != 3:
            continue
        item: Dict[str, Any] = {
            "name": name[:80],
            "description": description[:600],
            "category": str(entry.get("category") or "").strip()[:40],
            "count": _count(entry.get("count")),
            "marker": _valid_marker(entry.get("marker"), kinds),
            "prop_id": str(entry.get("prop_id") or "").strip() or None,
            **dims,
        }
        out.append(item)
    return out


def _validate_proposal(raw: Any, library: Dict[str, Dict[str, Any]],
                       kinds: List[str]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {"existing": _valid_existing(raw.get("existing"), library),
            "new": _valid_new(raw.get("new"), kinds)}


# ── Phase 1: selecting ──────────────────────────────────────────────────

def _phase_select(room_id: str) -> None:
    from app.core.expression_pose_maps import available_animation_kinds
    from app.core.prompt_templates import render_task
    from app.models.world import get_room_activity_hint

    loc, room = _load_room(room_id)
    geom = _geometry(loc, room)
    library = _library()
    placed = _placements(geom["layout"])
    existing = _aggregate(placed, library)
    budget = max(0.0, geom["area_m2"] * BUDGET_FRACTION
                 - _used_area(placed, library))
    room_name = str(room.get("name") or "Room")
    style_hint = str(room.get("style_hint") or loc.get("style_hint") or "")
    common = {
        "room_name": room_name,
        "room_description": str(room.get("description") or ""),
        "activity_hint": get_room_activity_hint(str(loc.get("id") or ""), room_id),
        "style_hint": style_hint,
        "room_w_m": geom["w_m"],
        "room_d_m": geom["d_m"],
        "area_m2": geom["area_m2"],
    }

    sys_p, user_p = render_task(
        "furnish_select", budget_m2=round(budget, 2), max_items=MAX_ITEMS,
        existing=[{"name": e["name"], "count": e["count"],
                   "width_m": e["width_m"], "depth_m": e["depth_m"]}
                  for e in existing],
        catalog=[{"id": p["id"], "name": p.get("name") or p["id"],
                  "category": p.get("category") or "",
                  "width_m": p.get("width_m"), "depth_m": p.get("depth_m"),
                  "height_m": p.get("height_m"), "tags": p.get("tags") or []}
                 for p in library.values()],
        **common)
    picks = _valid_existing(_list_field(
        _llm_json("furnish_select", sys_p, user_p, f"Furnish select: {room_name}"),
        "existing"), library)
    if not _get_row(room_id):
        return  # discarded while the LLM was busy
    picks_area = sum(float(library[p["prop_id"]].get("width_m") or 0)
                     * float(library[p["prop_id"]].get("depth_m") or 0)
                     * p["count"] for p in picks)

    covered = [{"name": e["name"], "count": e["count"]} for e in existing]
    covered += [{"name": library[p["prop_id"]].get("name") or p["prop_id"],
                 "count": p["count"]} for p in picks]
    kinds = available_animation_kinds()
    sys_p, user_p = render_task(
        "furnish_new", budget_m2=round(max(0.0, budget - picks_area), 2),
        max_new=MAX_NEW_KINDS, existing=covered,
        catalog_names=sorted(p.get("name") or p["id"] for p in library.values()),
        marker_kinds=kinds, **common)
    new_items = _valid_new(_list_field(
        _llm_json("furnish_new", sys_p, user_p, f"Furnish new: {room_name}"),
        "new"), kinds)

    if not _get_row(room_id):
        return
    _update_row(room_id, state=STATE_PROPOSAL_READY, error="",
                proposal={"existing": picks, "new": new_items})
    logger.info("room_furnish %s: proposal ready (%d library picks, %d new)",
                room_id, len(picks), len(new_items))


# ── Phase 2: generating ─────────────────────────────────────────────────

def _phase_generate(room_id: str) -> None:
    from app.core.props import create_prop, set_markers, trigger_generation

    row = _get_row(room_id)
    proposal = (row or {}).get("proposal") or {}
    new_items = proposal.get("new") or []
    for item in new_items:
        if _prop_ready(item.get("prop_id")):
            continue
        if not item.get("prop_id"):
            prop = create_prop(
                name=item["name"], category=item.get("category") or "",
                width_m=item.get("width_m"), depth_m=item.get("depth_m"),
                height_m=item.get("height_m"),
                description=item.get("description") or "", source="generated")
            item["prop_id"] = prop["id"]
            if item.get("marker"):
                set_markers(prop["id"], [item["marker"]])
            # Persist the id BEFORE the long generation — a restart must not
            # create the same prop twice.
            if not _update_row(room_id, proposal=proposal):
                return
        pid = str(item["prop_id"])
        from app.core.props import is_pending
        trigger_generation(pid)
        deadline = time.monotonic() + MODEL_TIMEOUT_SECONDS
        while not _prop_ready(pid):
            if not _get_row(room_id):
                return  # job discarded mid-generation
            if not is_pending(pid):
                # The chain ended WITHOUT a model (source render or mesh
                # failed) — fail fast instead of burning the full timeout.
                raise FurnishError(
                    f"Model generation for '{item['name']}' failed — see the "
                    "queue panel / server log, then Retry.")
            if time.monotonic() > deadline:
                raise FurnishError(
                    f"Model generation for '{item['name']}' timed out.")
            time.sleep(MODEL_POLL_SECONDS)
        _update_row(room_id, state=STATE_GENERATING)  # bump updated_at (n/m)
        logger.info("room_furnish %s: prop %s ready", room_id, pid)


# ── Phase 3: placing ────────────────────────────────────────────────────

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


def _place_items(proposal: Dict[str, Any],
                 library: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The confirmed furnishing as ``{id, name, count, dims}`` — library picks
    plus the generated new pieces (a piece without a prop id never made it
    through generation and is skipped)."""
    items: List[Dict[str, Any]] = []
    for pick in proposal.get("existing") or []:
        prop = library.get(str(pick.get("prop_id") or ""))
        if prop:
            items.append({"id": prop["id"], "name": prop.get("name") or prop["id"],
                          "count": _count(pick.get("count")),
                          "width_m": prop.get("width_m"),
                          "depth_m": prop.get("depth_m"),
                          "height_m": prop.get("height_m")})
    for item in proposal.get("new") or []:
        pid = str(item.get("prop_id") or "")
        if not pid:
            continue
        prop = library.get(pid) or {}
        items.append({"id": pid, "name": item.get("name") or pid,
                      "count": _count(item.get("count")),
                      "width_m": prop.get("width_m") or item.get("width_m"),
                      "depth_m": prop.get("depth_m") or item.get("depth_m"),
                      "height_m": prop.get("height_m") or item.get("height_m")})
    return items


def _solver_props(items: List[Dict[str, Any]],
                  library: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Dims per prop id for the solver — every id it may see: the items to
    place AND the props already standing in the room."""
    props = {pid: {"width_m": p.get("width_m"), "depth_m": p.get("depth_m"),
                   "height_m": p.get("height_m")}
             for pid, p in library.items()}
    for item in items:
        props[item["id"]] = {"width_m": item["width_m"],
                             "depth_m": item["depth_m"],
                             "height_m": item["height_m"]}
    return props


def _phase_place(room_id: str) -> None:
    from app.core import furnish_solver
    from app.core.prompt_templates import render_task
    from app.models.notifications import create_notification

    row = _get_row(room_id)
    if not row:
        return
    _update_row(room_id, state=STATE_PLACING)
    loc, room = _load_room(room_id)
    geom = _geometry(loc, room)
    library = _library()
    lay = geom["layout"]
    items = _place_items(row.get("proposal") or {}, library)
    room_name = str(room.get("name") or "Room")

    if not items:
        _update_row(room_id, state=STATE_REVIEW_READY, error="",
                    placements={"placed": [], "unplaced": []})
        return

    openings = _openings(lay)
    placed_props = _placements(lay)
    existing_solver = [{"prop_id": p.get("prop_id"), "at": p.get("at"),
                        "yaw": p.get("yaw") or 0} for p in placed_props]
    solver_props = _solver_props(items, library)
    template_existing = [
        {"prop_id": p.get("prop_id"),
         "name": (library.get(str(p.get("prop_id") or "")) or {}).get("name")
         or str(p.get("prop_id") or ""),
         "x_m": round(float((p.get("at") or [0, 0])[0]) * geom["w_m"], 2),
         "y_m": round(float((p.get("at") or [0, 0])[1]) * geom["d_m"], 2)}
        for p in placed_props]
    template_openings = [
        {"type": op.get("type") or "door",
         "wall": _edge_wall(geom["outline_m"], int(op.get("edge") or 0)),
         "at_frac": round(float(op.get("at") or 0.5), 2),
         "width_m": op.get("width_m"), "sill_m": op.get("sill_m") or 0}
        for op in openings]

    def _run(errors: List[str]) -> Dict[str, Any]:
        sys_p, user_p = render_task(
            "furnish_place", room_name=room_name,
            room_description=str(room.get("description") or ""),
            room_w_m=geom["w_m"], room_d_m=geom["d_m"], is_rect=geom["is_rect"],
            openings=template_openings, existing=template_existing,
            items=items, errors=errors)
        plan = _llm_json("furnish_place", sys_p, user_p,
                         f"Furnish place: {room_name}")
        return furnish_solver.solve(
            outline_m=geom["outline_m"], openings=openings,
            existing=existing_solver, plan=_list_field(plan, "plan"),
            props=solver_props, exit_frac=lay.get("exit"))

    result = _run([])
    if result.get("unplaced"):
        # ONE repair round: the model sees why pieces did not fit and replans.
        errors = [f"{u.get('name')}: {u.get('reason')}"
                  for u in result["unplaced"]][:20]
        try:
            retry_result = _run(errors)
            if len(retry_result.get("placed") or []) > len(result.get("placed") or []):
                result = retry_result
        except FurnishError as e:
            logger.info("room_furnish %s: repair run failed (%s) — keeping the "
                        "first result", room_id, e.message)

    if not _get_row(room_id):
        return
    _update_row(room_id, state=STATE_REVIEW_READY, error="", placements=result)
    create_notification(
        room_name,
        f"Furnishing ready for review — {len(result.get('placed') or [])} of "
        f"{len(result.get('placed') or []) + len(result.get('unplaced') or [])} "
        f"pieces placed in {room_name}.",
        notification_type="room_furnish",
        metadata={"room_id": room_id, "location_id": row.get("location_id")})
    logger.info("room_furnish %s: review ready (%d placed, %d unplaced)",
                room_id, len(result.get("placed") or []),
                len(result.get("unplaced") or []))


# ── Orchestrator thread ─────────────────────────────────────────────────

def _pipeline(room_id: str, phase: str) -> None:
    if phase == "select":
        _phase_select(room_id)
        return
    if phase == "generate":
        _phase_generate(room_id)
        phase = "place"
    if phase == "place":
        _phase_place(room_id)


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
    not from the state it died in, so retry and continue share one path."""
    proposal = row.get("proposal") or {}
    if not proposal.get("existing") and not proposal.get("new"):
        return "select"
    if row.get("state") == STATE_PROPOSAL_READY:
        return ""  # waiting for the admin, nothing to resume
    if any(not _prop_ready((n or {}).get("prop_id"))
           for n in proposal.get("new") or []):
        return "generate"
    if not (row.get("placements") or {}).get("placed"):
        return "place"
    return ""


# ── Public job API ──────────────────────────────────────────────────────

def start(room_id: str) -> Dict[str, Any]:
    """Open a furnishing job for a room and kick off stage 1."""
    loc, room = _load_room(room_id)
    _geometry(loc, room)  # layout + scale anchor are start conditions
    if _get_row(room_id):
        raise FurnishError("A furnishing job for this room is already open.", 409)
    _insert_row(room_id, str(loc.get("id") or ""))
    _spawn(room_id, "select", str(room.get("name") or room_id))
    return get_status(room_id) or {}


def confirm(room_id: str, proposal: Any) -> Dict[str, Any]:
    """Persist the admin-edited proposal and start generation + placement."""
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] != STATE_PROPOSAL_READY:
        raise FurnishError(f"Cannot confirm in state '{row['state']}'.", 409)
    from app.core.expression_pose_maps import available_animation_kinds
    _, room = _load_room(room_id)
    clean = _validate_proposal(proposal if proposal is not None else row["proposal"],
                               _library(), available_animation_kinds())
    if not clean["existing"] and not clean["new"]:
        raise FurnishError("The confirmed list is empty.", 400)
    _update_row(room_id, state=STATE_GENERATING, error="", proposal=clean)
    _spawn(room_id, "generate", str(room.get("name") or room_id))
    return get_status(room_id) or {}


def accept(room_id: str, placements: Any = None) -> Dict[str, Any]:
    """Append the (possibly hand-adjusted) placements to ``layout.props`` and
    close the job."""
    row = _get_row(room_id)
    if not row:
        raise FurnishError("No furnishing job for this room.", 404)
    if row["state"] != STATE_REVIEW_READY:
        raise FurnishError(f"Cannot accept in state '{row['state']}'.", 409)
    entries = placements if isinstance(placements, list) \
        else (row.get("placements") or {}).get("placed") or []
    from app.models.world import append_room_props
    if entries and not append_room_props(row["location_id"], room_id, entries):
        raise FurnishError("The room layout could not be updated.", 409)
    _delete_row(room_id)
    logger.info("room_furnish %s: %d placements accepted", room_id, len(entries))
    return {"status": "accepted", "placed": len(entries)}


def discard(room_id: str) -> Dict[str, Any]:
    """Drop the job (the generated props stay in the library)."""
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
        raise FurnishError("This job has nothing left to do.", 409)
    _, room = _load_room(room_id)
    state = {"select": STATE_SELECTING, "generate": STATE_GENERATING,
             "place": STATE_PLACING}[phase]
    _update_row(room_id, state=state, error="")
    if not _spawn(room_id, phase, str(room.get("name") or room_id)):
        raise FurnishError("This job is already running.", 409)
    return get_status(room_id) or {}
