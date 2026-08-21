"""Room layouts an LLM drew — normalize, warn, apply, snapshot.

Programme "Prop-Welt statt Dioramen", stage 3. The world-dev chat can emit a
whole FLOOR PLAN for ONE location: where each room stands inside the plot, how
big it is, which walls carry doors, and how one walks onto the plot at all.
This module turns such a draft into exactly the rows the floor-plan editor
writes, so nothing downstream has to know the plan came from a model rather
than from a mouse.

The layering mirrors :mod:`app.core.map_layout_apply` deliberately — same
three layers, same vocabulary, same undo:

* **Validation** — :func:`sanitize_layout`, a PURE function: the target
  location (its rooms, its drawn boundary, its storey height) and the surface
  library are handed IN, so the whole rule set runs without a world DB. It
  returns the normalized draft plus WARNINGS, never exceptions, for everything
  a person can still legitimately want. A room sticking out of the plot, two
  rooms sharing floor, a door into a room that is nowhere near — all of those
  are things an author may be mid-way through, and the ``problems[]`` system
  (``scene_recipe``) reports them on the finished world anyway. Only junk is
  DROPPED (a room id this location does not have, a rectangle with no extent),
  and dropping is itself a warning.
* **Writing** — :func:`apply_layout`. It validates EVERYTHING before the
  first write and then goes through the ORDINARY save path
  (``world_ops.update_location_with_extras``), so the layout sanitizer, the
  centimetre rounding and the map3d whitelist are the editor's, not a second
  implementation's.
* **Snapshots** — :func:`layout_snapshot`, :func:`list_layout_snapshots`,
  :func:`restore_layout_snapshot`. One snapshot is ONE location's whole plan
  (every room's layout, ``map3d``, ``entry_room``), stored under
  ``<storage>/.cache/layout_snapshots/`` — gitignored, capped at
  :data:`MAX_SNAPSHOTS`. That is the undo the floor-plan editor does not have.

THE SANITIZER IS THE JUDGE. Every room layout goes through
``world_ops._sanitize_room_layout`` — the very function ``PUT
/world/locations/{id}`` calls — and every boundary opening through
``world_ops._sanitize_map3d``. This module only decides what to hand them and
what to say about the result.
"""

import json
import re
import secrets
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("layout_apply")

#: How many snapshots are kept per world (across all locations). Twenty apply
#: runs is far more history than anybody scrolls back through.
MAX_SNAPSHOTS = 20

#: Two rooms count as overlapping only past this much — plans are stored to the
#: centimetre and a shared wall is a zero-width touch, not an overlap.
OVERLAP_TOL_M = 0.01

#: Default opening sizes, by type, in metres. The model is asked for
#: ``height_m``/``sill_m`` but routinely leaves them out, and a door without a
#: height would be dropped by the sanitizer — a silent loss of the one thing
#: that makes a plan walkable. These are ordinary building sizes, spelled out
#: in the schema so the number the model reads and the number it gets are one.
OPENING_DEFAULTS: Dict[str, Tuple[float, float]] = {
    # type: (height_m, sill_m)
    "door": (2.1, 0.0),
    "passage": (2.1, 0.0),
    "window": (1.4, 0.9),
}

#: The complete warning vocabulary. A warning NEVER blocks an apply.
WARNING_CODES = (
    "unknown_room",            # `id` names no room of this location — dropped
    "duplicate_room",          # the same room twice — the later one dropped
    "nameless_room",           # neither `id` nor `name` — dropped
    "invalid_layout",          # x/y/w/d unusable — dropped
    "unknown_surface",         # surface kind not in the library — dropped
    "opening_dropped",         # an opening the sanitizer refused — dropped
    "unknown_opening_target",  # `to` names no room here — opening KEPT
    "boundary_opening_dropped",  # bad edge index / no boundary — dropped
    "room_outside_boundary",   # plan reaches over the plot outline — KEPT
    "room_overlap",            # two rooms share floor on one level — KEPT
    "unknown_entry_room",      # entry_room proposal names nothing — dropped
    "no_boundary",             # the location has no drawn plot outline
)


def _warn(out: List[Dict[str, str]], code: str, ref: str, message: str) -> None:
    out.append({"code": code, "ref": ref, "message": message})


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


# ── Geometry helpers (pure) ─────────────────────────────────────────────────

def room_outline_local(layout: Dict[str, Any]) -> List[List[float]]:
    """One room's shell in LOCATION-LOCAL metres.

    A stored layout carries ``x``/``y`` (the room's minimum corner in the
    location frame) and, optionally, an ``outline`` whose points are metres
    relative to THAT corner (contract v6 Nr. 2); ``layout.rotation`` turns the
    whole room about its rect centre on the way out (v6 addendum). Both steps
    live in ``room_recipe.room_transform`` — the ONE place a room-local metre
    becomes a location-local one — so the draft is measured with exactly the
    geometry the composed world gets. Without an outline the shell is the
    rectangle's four corners, clockwise in map view.
    """
    from app.core.room_recipe import room_transform
    w = float(layout.get("w") or 0.0)
    d = float(layout.get("d") or 0.0)
    place = room_transform(layout)
    outline = layout.get("outline")
    pts = (outline if isinstance(outline, list) and len(outline) >= 3
           else [[0.0, 0.0], [w, 0.0], [w, d], [0.0, d]])
    return [list(place(float(p[0]), float(p[1]))) for p in pts]


def _boxes_overlap(a: Dict[str, Any], b: Dict[str, Any],
                   tol: float = OVERLAP_TOL_M) -> bool:
    """Do two room shells share floor by more than ``tol`` in BOTH axes?

    Hand-derived: A at x −2 … 2, B at x 1 … 4 overlap by 1 m; A at x −2 … 2 and
    B at x 2 … 4 overlap by 0 — a shared wall, which is what neighbouring rooms
    are made of and must never warn.

    Measured on the PLACED shell, not on ``x/y/w/d``: a turned room's stored
    rectangle is its straight frame, and its bounding box in the location is
    the box of the turned hull. For an unturned room the two are the same box
    (the sanitizer folds a drawn hull's bbox into the rect), so nothing moves
    for the ordinary plan.
    """
    def _box(lay: Dict[str, Any]) -> tuple:
        pts = room_outline_local(lay)
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        return (min(xs), min(zs), max(xs), max(zs))

    ax0, ay0, ax1, ay1 = _box(a)
    bx0, by0, bx1, by1 = _box(b)
    return (min(ax1, bx1) - max(ax0, bx0) > tol
            and min(ay1, by1) - max(ay0, by0) > tol)


def rooms_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Do two room layouts on the same level share floor?

    The bounding boxes decide first (cheap, and the only test a plain
    rectangular room needs). When BOTH rooms carry a drawn outline the answer
    is refined with the exact polygon test — two interlocking L-shaped rooms
    can have fully overlapping boxes and not share a single square metre, and a
    warning nobody can act on is noise. The refinement can only REMOVE a
    finding: a mere shared edge is already excluded by the box test's
    tolerance, so ``polygons_overlap``'s "a shared edge counts" never fires
    here.
    """
    if not _boxes_overlap(a, b):
        return False
    if not (a.get("outline") and b.get("outline")):
        return True
    from app.core.world_geometry import polygons_overlap
    return polygons_overlap(room_outline_local(a), room_outline_local(b))


def rooms_outside_boundary(layouts: Sequence[Tuple[str, Dict[str, Any]]],
                           boundary: Any) -> List[str]:
    """The keys of the rooms whose plan reaches out of the plot outline.

    Delegates to ``scene_recipe.rooms_outside_boundary`` — the ONE routine the
    finished world is measured with (``problems[] room_outside_boundary``,
    contract v6 Nr. 9), including its tolerance and its corner+midpoint probe
    set. Feeding it the world-frame outlines is exactly the shape it reads
    (``{room_id, outline}``), so the draft and the applied world can never
    disagree about what "outside" means.
    """
    from app.core.scene_recipe import rooms_outside_boundary as _stray
    recipes = [{"room_id": key, "outline": room_outline_local(lay)}
               for key, lay in layouts]
    return _stray(recipes, boundary)


# ── Validation ──────────────────────────────────────────────────────────────

def _coerce_opening(raw: Any) -> Optional[Dict[str, Any]]:
    """Fill in what the schema lets the model leave out, then hand it on.

    ``type`` defaults to ``door`` and ``height_m``/``sill_m`` to the ordinary
    building sizes of that type (:data:`OPENING_DEFAULTS`). Everything else —
    the edge index, the clamps, the vocabulary — is the sanitizer's call.
    """
    if not isinstance(raw, dict):
        return None
    out = dict(raw)
    typ = str(out.get("type") or "door").strip().lower()
    if typ not in OPENING_DEFAULTS:
        typ = "door"
    out["type"] = typ
    height, sill = OPENING_DEFAULTS[typ]
    if _num(out.get("height_m")) is None:
        out["height_m"] = height
    if _num(out.get("sill_m")) is None:
        out["sill_m"] = sill
    if _num(out.get("at")) is None:
        out["at"] = 0.5
    return out


def _room_key(entry: Dict[str, Any]) -> str:
    """What a warning points at: the room's id.

    A room the plan CREATES gets its id up front (so ``entry_room`` can point
    at it in the same write), which means every finding carries the very key
    the preview draws the room under — a warning is a pointer, and one that
    named a room by title would not resolve to a shape.
    """
    return str(entry.get("room_id") or entry.get("name") or "?")


def sanitize_layout(data: Any, *,
                    location: Dict[str, Any],
                    surface_kinds: Optional[Sequence[str]] = None
                    ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Turn one LLM layout draft into the rows :func:`apply_layout` writes.

    PURE: ``location`` (the full location dict — ``id``, ``rooms``, ``map3d``)
    and the surface library are handed in, so the rule set runs without a world
    DB. ``surface_kinds`` empty/None disables the surface check entirely; a
    world without a texture library must not lose every floor the model picked.

    Returns ``(normalized, warnings)``:

    ``normalized`` = ``{summary, location_id, entry_room, rooms[],
    boundary_openings}``. Each ``rooms[]`` entry is
    ``{room_id, name, description, is_new, layout}`` — ``room_id`` is set for
    every entry (new rooms get theirs up front, so ``entry_room`` can point at
    a room this very plan creates; that id is minted PER PASS, so the preview
    and the apply give a new room different ids — which is harmless, since a
    room that does not exist yet has nothing to reference it), and ``layout``
    is already through
    ``world_ops._sanitize_room_layout``. ``boundary_openings`` is ``None`` when
    the draft did not mention them at all, which means "leave what is there".

    Raises ValueError only when the draft is not an object or names no room at
    all; everything else is a warning, because a plan in progress is a normal
    state and not a defect.
    """
    from app.models.world import GROUND_ROOM_ID, _generate_room_id
    from app.core.world_ops import _sanitize_map3d, _sanitize_room_layout

    if not isinstance(data, dict):
        raise ValueError("layout must be an object")

    warnings: List[Dict[str, str]] = []
    map3d = location.get("map3d") if isinstance(location.get("map3d"), dict) else {}
    boundary = map3d.get("boundary")
    known_rooms = {str(r.get("id")): r for r in (location.get("rooms") or [])
                   if isinstance(r, dict) and r.get("id")}
    known_names = {str(r.get("name") or "").strip().lower(): str(r.get("id"))
                   for r in (location.get("rooms") or [])
                   if isinstance(r, dict) and r.get("id")}
    library = {str(k) for k in (surface_kinds or [])}

    raw_rooms = data.get("rooms")
    if not isinstance(raw_rooms, list) or not raw_rooms:
        raise ValueError("layout carries no rooms")

    entries: List[Dict[str, Any]] = []
    seen: set = set()
    for index, raw in enumerate(raw_rooms):
        ref = f"rooms[{index}]"
        if not isinstance(raw, dict):
            _warn(warnings, "invalid_layout", ref, "Not a room object.")
            continue
        room_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if room_id and room_id not in known_rooms:
            # A model that guesses an id would silently overwrite the wrong
            # room, so this is a DROP and never a "create it anyway".
            _warn(warnings, "unknown_room", room_id,
                  f"This location has no room with id '{room_id}'. "
                  f"The entry was dropped.")
            continue
        if room_id == GROUND_ROOM_ID:
            # The ground is the location's open surface and carries no
            # geometry of its own (§ A13a) — the room sanitizer would strip
            # everything anyway.
            _warn(warnings, "unknown_room", room_id,
                  "The ground is not a room with a floor plan. "
                  "The entry was dropped.")
            continue
        if not room_id and name and name.lower() in known_names:
            # A name that already exists is an EDIT, not a second room —
            # matching it is the only reading that does not duplicate rooms.
            room_id = known_names[name.lower()]
        if not room_id and not name:
            _warn(warnings, "nameless_room", ref,
                  "Neither an existing room `id` nor a `name` for a new room.")
            continue
        is_new = not room_id
        if is_new:
            room_id = _generate_room_id()
        key = room_id if not is_new else f"new:{name.lower()}"
        if key in seen:
            _warn(warnings, "duplicate_room", _room_key({"room_id": room_id,
                                                         "name": name}),
                  "The plan names this room twice; the later entry was dropped.")
            continue

        raw_layout = {k: v for k, v in raw.items()
                      if k not in ("id", "name", "description", "open", "flat")}
        # The flag trio behind the operating language "open / closed
        # sub-area" (contract v6 Nr. 9). The FIELDS stay what they were; only
        # the way an author says it changed.
        if raw.get("open"):
            raw_layout["always_visible"] = True
            raw_layout["no_walls"] = True
        # ``flat`` HAS NO EFFECT ANY MORE ("Ein Boden" E5a, user decision 1): a
        # location carries no relief of its own for a sub-area to opt out of.
        # The word stays legal in the world-dev schema so an old prompt answer
        # still applies; it simply produces no field.
        surfaces = raw_layout.get("surfaces")
        if library and isinstance(surfaces, dict):
            kept = {}
            for slot in ("floor", "wall"):
                val = str(surfaces.get(slot) or "").strip()
                if not val:
                    continue
                if val in library:
                    kept[slot] = val
                else:
                    _warn(warnings, "unknown_surface",
                          _room_key({"room_id": room_id, "name": name}),
                          f"The surface library has no kind '{val}' "
                          f"({slot}); it was dropped.")
            raw_layout["surfaces"] = kept
        raw_ops = raw_layout.get("openings")
        if isinstance(raw_ops, list):
            raw_layout["openings"] = [op for op in
                                      (_coerce_opening(o) for o in raw_ops)
                                      if op is not None]

        layout = _sanitize_room_layout(raw_layout)
        if not layout:
            _warn(warnings, "invalid_layout",
                  _room_key({"room_id": room_id, "name": name}),
                  "The rectangle is unusable (x/y/w/d must be finite metres, "
                  "w and d greater than 0). The entry was dropped.")
            continue
        dropped = len(raw_layout.get("openings") or []) - len(layout.get("openings") or [])
        if dropped > 0:
            _warn(warnings, "opening_dropped",
                  _room_key({"room_id": room_id, "name": name}),
                  f"{dropped} opening(s) were refused — an edge the room does "
                  f"not have, a curved edge, or a size outside 0.4…10 m.")

        seen.add(key)
        entries.append({
            "room_id": room_id,
            "name": name or str(known_rooms.get(room_id, {}).get("name") or room_id),
            "description": str(raw.get("description") or "").strip(),
            "is_new": is_new,
            "layout": layout,
        })

    # ── the findings that never drop anything ──────────────────────────────
    draft_ids = {e["room_id"] for e in entries}
    for entry in entries:
        for op in entry["layout"].get("openings") or []:
            to = str(op.get("to") or "").strip()
            if not to or to == "outside":
                continue
            if to not in draft_ids and to not in known_rooms:
                _warn(warnings, "unknown_opening_target", _room_key(entry),
                      f"A door leads to '{to}', which is no room of this "
                      f"location. The opening is kept as a plain hole.")

    if boundary:
        stray = rooms_outside_boundary(
            [(e["room_id"], e["layout"]) for e in entries], boundary)
        for room_id in stray:
            entry = next(e for e in entries if e["room_id"] == room_id)
            _warn(warnings, "room_outside_boundary", _room_key(entry),
                  f"'{entry['name']}' reaches out of the plot outline — it "
                  f"would stand on ground this location does not own.")
    elif entries:
        _warn(warnings, "no_boundary", str(location.get("id") or ""),
              "This location has no drawn plot outline, so nothing could be "
              "checked against it — and boundary openings have no edge to sit "
              "on.")

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            if a["layout"].get("level", 0) != b["layout"].get("level", 0):
                continue
            if rooms_overlap(a["layout"], b["layout"]):
                _warn(warnings, "room_overlap",
                      f"{_room_key(a)}|{_room_key(b)}",
                      f"'{a['name']}' and '{b['name']}' share floor on level "
                      f"{a['layout'].get('level', 0)}.")

    # ── entry room ─────────────────────────────────────────────────────────
    entry_room = str(data.get("entry_room") or "").strip()
    if entry_room:
        if entry_room in draft_ids or entry_room in known_rooms:
            pass
        else:
            by_name = next((e["room_id"] for e in entries
                            if e["name"].lower() == entry_room.lower()), "")
            if not by_name:
                by_name = known_names.get(entry_room.lower(), "")
            if by_name:
                entry_room = by_name
            else:
                _warn(warnings, "unknown_entry_room", entry_room,
                      f"'{entry_room}' is no room of this location; the entry "
                      f"room was left as it is.")
                entry_room = ""

    # ── boundary openings ──────────────────────────────────────────────────
    raw_bo = data.get("boundary_openings")
    boundary_openings: Optional[List[Dict[str, Any]]] = None
    if isinstance(raw_bo, list):
        # Run them through the map3d whitelist WITH this location's real
        # boundary, so the edge-index range and the width clamp are the ones
        # the editor enforces — not a second reading of the same rule.
        probe = _sanitize_map3d({**map3d, "boundary_openings": raw_bo})
        boundary_openings = list(probe.get("boundary_openings") or [])
        lost = len(raw_bo) - len(boundary_openings)
        if lost > 0:
            _warn(warnings, "boundary_opening_dropped",
                  str(location.get("id") or ""),
                  f"{lost} boundary opening(s) were refused — an edge index "
                  f"the plot outline does not have, or an unreadable entry.")

    normalized = {
        "summary": str(data.get("summary") or "").strip(),
        "location_id": str(location.get("id") or ""),
        "location_name": str(location.get("name") or ""),
        "boundary": list(boundary) if boundary else [],
        "entry_room": entry_room,
        "rooms": entries,
        "boundary_openings": boundary_openings,
    }
    return normalized, warnings


def layout_counts(normalized: Dict[str, Any]) -> Dict[str, int]:
    """``{rooms, new_rooms, openings, boundary_openings}`` of a normalized
    draft — the numbers the confirmation dialog states before it writes."""
    rooms = normalized.get("rooms") or []
    return {
        "rooms": len(rooms),
        "new_rooms": sum(1 for r in rooms if r.get("is_new")),
        "openings": sum(len(r.get("layout", {}).get("openings") or [])
                        for r in rooms),
        "boundary_openings": len(normalized.get("boundary_openings") or []),
    }


# ── Writing ─────────────────────────────────────────────────────────────────

def apply_layout(normalized: Dict[str, Any]) -> Dict[str, Any]:
    """Write a normalized plan to its location.

    Goes through ``world_ops.update_location_with_extras`` — the writer behind
    ``PUT /world/locations/{id}``, which is what the floor-plan editor saves
    with. The room list handed over is the location's OWN list with the
    layouts replaced: a room the plan does not mention keeps everything it had,
    and no room loses its description, its prompts or its items to a plan that
    only ever talked about geometry.

    Validated completely before the first write: a plan naming a room that
    vanished between preview and apply must leave the location exactly as it
    was, not half-planned.

    Returns ``{location_id, updated[], created[], entry_room, boundary_openings}``.
    """
    from app.core.world_ops import update_location_with_extras
    from app.models.world import get_location_by_id

    location_id = str(normalized.get("location_id") or "").strip()
    if not location_id:
        raise ValueError("layout carries no location_id")
    loc = get_location_by_id(location_id)
    if not loc:
        raise ValueError(f"no such location: {location_id}")

    rooms = [dict(r) for r in (loc.get("rooms") or []) if isinstance(r, dict)]
    by_id = {str(r.get("id")): r for r in rooms if r.get("id")}
    updated: List[str] = []
    created: List[str] = []

    plan = normalized.get("rooms") or []
    for entry in plan:
        room_id = str(entry.get("room_id") or "")
        if not entry.get("is_new") and room_id not in by_id:
            raise ValueError(f"room {room_id} no longer exists in "
                             f"{location_id}")
    for entry in plan:
        room_id = str(entry.get("room_id") or "")
        layout = entry.get("layout") or {}
        if entry.get("is_new"):
            rooms.append({
                "id": room_id,
                "name": entry.get("name") or room_id,
                "description": entry.get("description") or "",
                "activities": [],
                "layout": layout,
            })
            created.append(room_id)
        else:
            by_id[room_id]["layout"] = layout
            updated.append(room_id)

    body: Dict[str, Any] = {"rooms": rooms}
    if normalized.get("boundary_openings") is not None:
        map3d = dict(loc.get("map3d") or {})
        map3d["boundary_openings"] = normalized["boundary_openings"]
        body["map3d"] = map3d
    entry_room = str(normalized.get("entry_room") or "").strip()
    if entry_room:
        body["entry_room"] = entry_room

    update_location_with_extras(location_id, body)
    result = {
        "location_id": location_id,
        "updated": updated,
        "created": created,
        "entry_room": entry_room,
        "boundary_openings": len(normalized.get("boundary_openings") or []),
    }
    logger.info("layout applied to %s: %s", location_id, result)
    return result


# ── Snapshots ───────────────────────────────────────────────────────────────

def _snapshot_dir():
    from app.core.paths import get_storage_dir
    path = get_storage_dir() / ".cache" / "layout_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_id() -> str:
    """A sortable id from the SYSTEM clock — a technical stamp on a cache file,
    not a moment in the game world, so UTC and not ``GameTime``. The random
    tail keeps two applies in the same second apart."""
    from app.core.timeutils import utc_now_iso
    digits = re.sub(r"[^0-9]", "", utc_now_iso())[:14]
    return f"{digits}-{secrets.token_hex(3)}"


def layout_snapshot(location_id: str) -> str:
    """Freeze ONE location's whole plan and return the snapshot id.

    Full copies of every room (not only the layouts): a restore has to be able
    to remove a room the apply created, and that is only decidable against the
    complete list. ``map3d`` and ``entry_room`` ride along — a plan writes both.
    """
    from app.core.timeutils import utc_now_iso
    from app.models.world import get_location_by_id

    loc = get_location_by_id(location_id)
    if not loc:
        raise ValueError(f"no such location: {location_id}")
    payload = {
        "created_at": utc_now_iso(),
        "location_id": str(loc.get("id") or ""),
        "location_name": str(loc.get("name") or ""),
        "rooms": loc.get("rooms") or [],
        "map3d": loc.get("map3d") or {},
        "entry_room": loc.get("entry_room") or "",
    }
    snap_id = _snapshot_id()
    (_snapshot_dir() / f"{snap_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    files = sorted(_snapshot_dir().glob("*.json"), key=lambda p: p.name)
    for stale in files[:-MAX_SNAPSHOTS]:
        try:
            stale.unlink()
        except OSError as exc:  # noqa: BLE001 — pruning a cache never fails a write
            logger.warning("Could not prune layout snapshot %s: %s",
                           stale.name, exc)
    logger.info("layout snapshot %s: %s, %d rooms", snap_id,
                payload["location_id"], len(payload["rooms"]))
    return snap_id


def _read_snapshot(snapshot_id: str) -> Dict[str, Any]:
    snap_id = (snapshot_id or "").strip()
    if not snap_id or "/" in snap_id or "\\" in snap_id or snap_id.startswith("."):
        raise ValueError(f"invalid snapshot id: {snapshot_id!r}")
    path = _snapshot_dir() / f"{snap_id}.json"
    if not path.exists():
        raise ValueError(f"no such snapshot: {snap_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"snapshot {snap_id} is unreadable")
    return payload


def list_layout_snapshots(location_id: str = "") -> List[Dict[str, Any]]:
    """Snapshots, newest first: ``{id, created_at, location_id, location_name,
    rooms}``. ``location_id`` filters to one location; empty lists all.

    An unreadable file is skipped rather than raised over — the list is an
    offer of undos, and one broken file must not hide the others.
    """
    wanted = (location_id or "").strip()
    out: List[Dict[str, Any]] = []
    for path in sorted(_snapshot_dir().glob("*.json"),
                       key=lambda p: p.name, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # noqa: BLE001
            logger.warning("Skipping unreadable layout snapshot %s: %s",
                           path.name, exc)
            continue
        if not isinstance(payload, dict):
            continue
        loc_id = str(payload.get("location_id") or "")
        if wanted and loc_id != wanted:
            continue
        out.append({
            "id": path.stem,
            "created_at": str(payload.get("created_at") or ""),
            "location_id": loc_id,
            "location_name": str(payload.get("location_name") or ""),
            "rooms": len(payload.get("rooms") or []),
        })
    return out


def restore_layout_snapshot(snapshot_id: str) -> Dict[str, Any]:
    """Put a location's plan back — the undo for an apply.

    Writes through the same ordinary save path as the apply, so a restore is
    just another save of an older room list. Returns
    ``{location_id, rooms, entry_room}``.
    """
    from app.core.world_ops import update_location_with_extras
    from app.models.world import get_location_by_id

    payload = _read_snapshot(snapshot_id)
    location_id = str(payload.get("location_id") or "")
    if not location_id or not get_location_by_id(location_id):
        raise ValueError(f"snapshot {snapshot_id} points at a location that "
                         f"no longer exists")
    rooms = payload.get("rooms")
    if not isinstance(rooms, list):
        raise ValueError(f"snapshot {snapshot_id} carries no rooms")
    update_location_with_extras(location_id, {
        "rooms": [dict(r) for r in rooms if isinstance(r, dict)],
        "map3d": payload.get("map3d") or {},
        "entry_room": payload.get("entry_room") or "",
    })
    result = {"location_id": location_id, "rooms": len(rooms),
              "entry_room": payload.get("entry_room") or ""}
    logger.info("layout snapshot %s restored: %s", snapshot_id, result)
    return result
