"""Authored height areas and the rastered world grid (Relief, E8 task 2).

The world relief has TWO shapes, and only one of them is authored.

* A **height area** is what a person draws: a polygon in world metres plus
  ``height_m`` (how high the ground stands inside it) and ``falloff_m`` (over
  how many metres it climbs there from the surrounding level). It is the
  source of truth and the only thing the editor writes.
* The **grid** (``world_heightfield``) is derived from those areas by
  :mod:`app.core.heightfield` and is a cache, never an authoring surface. It
  is stored rather than recomputed per process because rastering a world-sized
  field costs cell × edge work that no walk report may pay.

This module owns the DB side of both. Everything is validated ON WRITE, the
``terrain`` rule: the readers downstream fail closed on malformed vertices
without a word in the log, so junk must never reach the DB in the first place.

There is no ``kind`` and no ``z_order`` here on purpose. Heights are not
terrain: the ground under a painted meadow may rise, and which of two
overlapping height areas wins is not a layer decision but an arithmetic one
(the STRONGEST deflection from the flat world, see
``app/core/heightfield.rasterize``).
"""

import hashlib
import json
import math
import secrets
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.timeutils import utc_now_iso

#: Outline limits — the same ones a painted terrain area has
#: (``app/models/terrain.py``), because both are polygons in world metres that
#: every renderer parses.
MAX_POINTS = 256
MAX_COORD = 100_000.0

#: How far the ground may leave the flat world, in metres, in either
#: direction. It is a RENDERING limit as much as an authoring one: the 3D
#: client raycasts its tiles from a fixed height above the plate, and a
#: mountain taller than that start height would be invisible to the ray.
MAX_HEIGHT_M = 50.0

#: Longest ramp an area may declare. A falloff wider than the area itself
#: simply never reaches the full height — that is legal (a gentle dome), so
#: this is only a sanity cap against a number that would swamp the raster.
MAX_FALLOFF_M = 1_000.0


def _finite(value: Any) -> Optional[float]:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _sanitize_polygon(raw: Any) -> List[List[float]]:
    """The outline, 3..256 finite ``[x, z]`` points on the 2-decimal metre
    grid. Identical rules to a terrain area's polygon — same reasons, listed
    in ``app/models/terrain._sanitize_polygon``."""
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_POINTS:
        raise ValueError("polygon needs 3..256 points")
    pts: List[List[float]] = []
    for pt in raw:
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            raise ValueError("polygon points must be [x, z] numbers")
        # isfinite FIRST: every NaN comparison is False, so a plain range check
        # would wave NaN through and poison every later JSON response
        # (Starlette encodes with allow_nan=False -> 500).
        if not (math.isfinite(x) and math.isfinite(z)):
            raise ValueError("polygon coordinate must be a finite number")
        if abs(x) > MAX_COORD or abs(z) > MAX_COORD:
            raise ValueError("polygon coordinate out of range")
        pts.append([round(x, 2), round(z, 2)])
    return pts


def sanitize_height_area(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one height area; raises ValueError on junk.

    ``height_m`` is CLAMPED rather than refused (an authoring slip should move
    the ground to the limit, not lose the shape someone drew), negative values
    are legal — that is a hollow, not a mistake — and a missing or unreadable
    number is 0.0, a flat area that changes nothing.

    ``falloff_m`` is a WIDTH and can only be positive; 0 means "no ramp at
    all", a wall at the outline. That is allowed and the editor warns about it,
    because a wall no walker can climb is a legitimate thing to build (a
    plateau reached through an opening) and an accident otherwise.
    """
    if not isinstance(raw, dict):
        raise ValueError("height area must be an object")
    area_id = str(raw.get("id") or "").strip() or f"ha_{secrets.token_hex(4)}"
    height = _finite(raw.get("height_m")) or 0.0
    height = min(max(height, -MAX_HEIGHT_M), MAX_HEIGHT_M)
    falloff = _finite(raw.get("falloff_m")) or 0.0
    falloff = min(max(falloff, 0.0), MAX_FALLOFF_M)
    meta = dict(raw.get("meta")) if isinstance(raw.get("meta"), dict) else {}
    return {"id": area_id,
            "polygon": _sanitize_polygon(raw.get("polygon")),
            "height_m": round(height, 3),
            "falloff_m": round(falloff, 3),
            "meta": meta}


def list_height_areas() -> List[Dict[str, Any]]:
    """All height areas in a STABLE order (insert order). The order carries no
    meaning for the result — the raster resolves overlaps by value, not by
    layer — it only has to be reproducible, or the signature would flap."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, polygon, height_m, falloff_m, meta FROM height_areas "
        "ORDER BY created_at ASC, rowid ASC").fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            polygon = json.loads(r[1])
            meta = json.loads(r[4] or "{}")
        except (TypeError, ValueError):
            continue
        out.append({"id": r[0], "polygon": polygon,
                    "height_m": float(r[2] or 0.0),
                    "falloff_m": float(r[3] or 0.0),
                    "meta": meta if isinstance(meta, dict) else {}})
    return out


def height_area_exists(area_id: str) -> bool:
    """True when an area with this id is stored — the PUT route's ONE lookup,
    so a stale write answers 404 instead of resurrecting a deleted area."""
    area_id = (area_id or "").strip()
    if not area_id:
        return False
    conn = get_connection()
    return conn.execute("SELECT 1 FROM height_areas WHERE id=?",
                        (area_id,)).fetchone() is not None


def save_height_area(raw: Any) -> Dict[str, Any]:
    """Create (no ``id``) or replace (with ``id``) one height area; returns the
    sanitized entry. Raises ValueError when it is not usable."""
    area = sanitize_height_area(raw)
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO height_areas (id, polygon, height_m, falloff_m, "
            "meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET polygon=excluded.polygon, "
            "height_m=excluded.height_m, falloff_m=excluded.falloff_m, "
            "meta=excluded.meta, updated_at=excluded.updated_at",
            (area["id"], json.dumps(area["polygon"], ensure_ascii=False),
             area["height_m"], area["falloff_m"],
             json.dumps(area["meta"], ensure_ascii=False), now, now))
    _invalidate()
    return area


def delete_height_area(area_id: str) -> bool:
    """Remove one height area; False when there was nothing to delete."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM height_areas WHERE id=?",
                           ((area_id or "").strip(),))
        deleted = cur.rowcount > 0
    if deleted:
        _invalidate()
    return deleted


def _invalidate() -> None:
    """Every write drops the rastered field — and RE-RASTERS it right here.

    HERE and not in the routes: ``ground_y`` is asked on every walk report and
    in every routing loop, so the sampler may not re-hash the areas per call —
    which makes a forgotten invalidation a silently stale world. One writer,
    one place. The nav grid is dropped along with it: its cells carry terrain
    AND (from E8) the ground under them.

    THE RE-RASTER IS THE POINT OF DOING IT HERE. Rastering a big area costs
    hundreds of milliseconds (0.39 s for a full-budget square, measured), and
    with a lazy cache that bill lands on whoever asks NEXT — which on a live
    world is a walker's ``POST /play/pos``, i.e. a figure freezing because
    somebody else moved a hill. The editing request is already waiting for a
    round trip and is the honest place to pay it.

    A failed re-raster is not a failed write: the areas are stored, the cache
    is empty, and the next reader simply builds the grid the old way.
    """
    from app.core.heightfield import get_field, invalidate_cache
    from app.core.nav_grid import invalidate_nav_cache
    invalidate_cache()
    invalidate_nav_cache()
    try:
        get_field()
    except Exception as exc:   # noqa: BLE001 — never fail the write for a cache
        from app.core.log import get_logger
        get_logger("heightfield").warning(
            "Could not re-raster the heightfield after a write: %s", exc)


def draws_built_floor(loc: Dict[str, Any]) -> bool:
    """Does this location draw a BUILT floor — i.e. does it stamp its plot?

    THE INVERSE OF ``scene_recipe.is_natural_location``, deliberately
    replicated rather than imported: that function asks the same two questions
    of the COMPOSED room recipes, this one asks them of the STORED location,
    and importing the scene recipe here would drag the whole scene builder into
    the walking gate's import path. The two questions are the contract, and
    they are:

    1. is there a ``map3d.outline`` — a drawn BUILDING contour? The drawn
       ``boundary`` does NOT count: it is the plot, the edge of the place, and
       drawing where a lake ends is not the same as drawing a floor.
    2. is there a CLOSED room — one that is not ``always_visible`` (§ A5, an
       open zone)? The yard (``GROUND_ROOM_ID``, § A13a) is inherently open and
       never counts.

    Either one makes the location BUILT, and a built location planes the ground
    under itself (§ G5). A natural location — the lake, the clearing, the
    forest — stamps nothing: its floor IS the relief, and the landscape runs
    through it unchanged.
    """
    from app.models.world import GROUND_ROOM_ID
    map3d = loc.get("map3d")
    if isinstance(map3d, dict):
        outline = map3d.get("outline")
        if isinstance(outline, list) and len(outline) >= 3:
            return True
    for room in (loc.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        if str(room.get("id") or "") == GROUND_ROOM_ID:
            continue
        layout = room.get("layout")
        layout = layout if isinstance(layout, dict) else {}
        if not layout.get("always_visible"):
            return True
    return False


def placed_footprints() -> List[Tuple[float, float, float,
                                      List[Tuple[float, float]]]]:
    """``(cx, cz, yaw_deg, boundary points)`` of every location that STAMPS a
    plateau — the POLYGON footprint (contract v6 no. 1 and no. 7).

    The second input of the bake: the ground under such a footprint is stamped
    flat, so where those places stand is part of what the world's relief IS.
    The outline comes from ``world_geometry.effective_boundary``, the ONE place
    that answers "what ground does this location own": the DRAWN
    ``map3d.boundary`` and nothing else. A location that only carries the
    legacy ``plan_width_m`` dial is no input here — it has no area, so it
    stamps nothing until somebody draws its outline (the map editor's "Seed
    missing boundaries" writes exactly the square it used to get for free).
    A redrawn outline reshapes the plateau.

    **STAMPING IS A LAW, NOT A FLAG** (E1, plan-ein-boden.md § G5). The
    ``level_ground`` opt-in of 2026-08-13 is gone: every location that draws a
    BUILT floor (:func:`draws_built_floor`) appears here, and no natural one
    does. That is the same rule the scene builder already uses to decide
    whether a place has a storey slab at all — a house that draws a floor and a
    plot that does not plane under it were two independent grounds, which is
    the whole finding the plan was written for ("Haus versinkt fern / taucht
    nah fast auf").

    The points are LOCAL metres around the pin — the frame the plateau stamp
    tests in (one inverse pin transform per evaluated point, no per-query
    polygon rotation). Everything is rounded to the centimetre and the tenth of
    a degree — the precision the placement itself is stored at — so the
    signature over this list does not flap on float noise, while a boundary
    point moved by a centimetre does change it.

    ONE RULE, TWO CONSEQUENCES, and that is why it sits here rather than in the
    bake: this list is what :func:`height_sig` hashes AND what
    ``core.heightfield.build_model`` stamps with. So closing a room or drawing
    a building outline changes the list membership and therefore the signature
    — every client refetches, the stored raster is stale and is rebuilt —
    without a single extra field anywhere.
    """
    from app.core.world_geometry import effective_boundary
    from app.models.world import list_locations
    out: List[Tuple[float, float, float, List[Tuple[float, float]]]] = []
    for loc in list_locations():
        if not draws_built_floor(loc):
            continue
        eff = effective_boundary(loc)
        if eff is None:
            continue
        cx, cz, yaw, points = eff
        out.append((round(cx, 2), round(cz, 2), round(yaw, 1),
                    [(round(lx, 2), round(lz, 2)) for lx, lz in points]))
    return out


def placed_zone_waters() -> List[Tuple[str, str, List[List[float]],
                                       Optional[float], float, float]]:
    """Every ROOM whose level-0 floor is WATER, as a carve input (E5a, § G4).

    ``(location_id, room_id, polygon in WORLD metres, authored water_level or
    None, depth_m, shore_ramp_m)`` — the fifth input of the bake, and the reason
    a pond drawn as a room floor is a lake and not a blue rectangle painted over
    the ground it does not fit.

    THE POLYGONS COME FROM ``core.terrain_layers.world_floors``, the same
    function that decides which layer the ground WEARS there. One derivation for
    the material and for the shape of the bed: if the two ever came from two
    places, the water would end where one of them said and the bed where the
    other did, which is the two-grounds bug this whole plan exists to kill.

    A location that is not placed, a room that is not on storey 0 and a floor
    whose kind is not a water surface never appear here.
    """
    from app.core.terrain_layers import (surface_classes, world_floors)
    from app.core.terrain_types import effective_catalog
    from app.models.world import list_locations
    out: List[Tuple[str, str, List[List[float]], Optional[float],
                    float, float]] = []
    for floor in world_floors(list_locations(), effective_catalog(),
                              surface_classes()):
        if not floor.water:
            continue
        out.append((floor.location_id, floor.room_id,
                    [[round(x, 2), round(z, 2)] for x, z in floor.polygon],
                    floor.water_level, floor.water_depth_m,
                    floor.shore_ramp_m))
    return out


def zone_water_basis() -> List[Dict[str, Any]]:
    """The ZONE WATERS of the bake, in hashable form (E5a).

    The room-floor twin of :func:`water_basis`: a pond moved, resized, given a
    mirror or turned into parquet changes the ground under it, so a client
    holding the old grid would draw a bed the server does not have.

    A world without a single water room floor contributes an empty list.
    """
    out: List[Dict[str, Any]] = []
    for loc_id, room_id, polygon, level, depth, ramp in placed_zone_waters():
        out.append({"location": loc_id, "room": room_id, "polygon": polygon,
                    "level": level, "depth": depth, "ramp": ramp})
    return out


def relief_basis() -> List[Dict[str, Any]]:
    """The MICRO-RELIEF inputs of the raster, in hashable form.

    Not "the painted terrain": exactly the areas
    ``core.heightfield.relief_inputs`` hands the raster — the ones painted
    with a kind that carries relief, plus the flat ones lying over them, each
    with the two catalog numbers that shape its hills. Same function, same
    list, so the signature cannot describe a different world than the grid
    does.

    THE POINT OF THE FILTER is what it leaves out (decision 2026-08-13):
    painting on a world whose catalog carries no relief changes no height at
    all, so it must not move this signature and must not cost a re-raster.
    Terrain is painted stroke by stroke; a heightfield rebuild per stroke would
    be paid by whoever walks next.
    """
    from app.core.heightfield import relief_inputs
    from app.core.terrain_types import effective_catalog
    from app.models.terrain import list_areas
    out: List[Dict[str, Any]] = []
    for area, params, _box in relief_inputs(list_areas(), effective_catalog()):
        out.append({"kind": area.get("kind"),
                    "polygon": area.get("polygon"),
                    # The seed is derivable from the kind, so only the two
                    # authored numbers travel; None is the flat area on top.
                    "relief": None if params is None else [params[1],
                                                           params[2]]})
    return out


def water_basis() -> List[Dict[str, Any]]:
    """The WATER inputs of the bake, in hashable form (E1, § G4).

    Every painted area of a water kind with the three numbers that shape its
    carve — the mirror height (absent while it is still "auto"), the depth and
    the shore ramp. They belong in the signature for the same reason the height
    areas do: moving a lake's level moves the ground under it, and a client
    holding the old grid would draw a bed the server does not have.

    A world that flags no kind as water contributes an empty list and costs
    nothing, exactly like :func:`relief_basis` on a world without hills.
    """
    from app.core.heightfield import water_areas, water_meta
    from app.core.terrain_types import effective_catalog
    from app.models.terrain import list_areas
    out: List[Dict[str, Any]] = []
    for area, _box in water_areas(list_areas(), effective_catalog()):
        level, depth, ramp = water_meta(area)
        out.append({"id": area.get("id"), "polygon": area.get("polygon"),
                    "level": level, "depth": depth, "ramp": ramp})
    return out


def height_sig() -> str:
    """10-char signature over the authored height areas AND the placements.

    The refetch trigger of every client (worldmap ``height_sig``) AND the
    validity token of the stored raster: the grid row carries the signature it
    was built from, so "the areas changed" and "the grid is stale" are the same
    question asked once.

    THE PLACEMENTS BELONG IN IT (E8 task 4), and since v6 that means the
    POLYGON POINTS as well as the pin: a moved, turned, REDRAWN, newly placed
    or deleted location moves its PLATEAU with it, which changes the
    world's relief without a single height area being touched. A client
    holding the old grid would drape its ground around a hole where the place
    used to stand — and the server, which samples the same field, would agree
    with nobody.

    SO DOES WHETHER A PLACE IS BUILT AT ALL (E1, § G5), and it costs nothing
    extra: only the locations that draw a built floor are in
    :func:`placed_footprints`, so closing a room or drawing a building outline
    adds a whole entry to the basis while the place stands perfectly still.

    AND SO DO THE WATER POLYGONS (:func:`water_basis`, E1, § G4): a lake's
    mirror, depth and shore ramp shape the ground under it exactly as a height
    area does — the PAINTED ones and, since E5a, the ROOM FLOORS of a water
    kind (:func:`zone_water_basis`).

    AND SO DOES THE MICRO-RELIEF (:func:`relief_basis`, decision 2026-08-13):
    since a terrain KIND may carry hills, painting such a kind — or editing its
    amplitude or wave in the catalog — moves the ground exactly as a height
    area does. Painting a kind WITHOUT relief does not appear here at all.
    """
    basis = json.dumps({"areas": list_height_areas(),
                        "places": placed_footprints(),
                        "terrain": relief_basis(),
                        "water": water_basis(),
                        "zone_water": zone_water_basis()},
                       sort_keys=True, default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]


def note_world_write() -> None:
    """Something that MIGHT shape the ground was written — re-raster if it did.

    Called by the ONE writer of the world data (``world._save_world_data``),
    which is a location write of every kind: a move, a turn, a resize, a new
    place, a deletion — and equally a rename or a room edit, which change no
    plateau at all. Since the micro-relief (2026-08-13) also by the terrain
    writers, ``models.terrain.save_area``/``delete_area`` and
    ``core.terrain_types.save_world_type``/``delete_world_type``: a painted
    area of a kind with hills, or that kind's amplitude, is part of the world
    relief. So the cheap question is asked first (the signature the cached
    field was built from against the current one) and the expensive answer only
    follows a real change — a stroke of flat grass costs one comparison.

    Same reasoning as :func:`_invalidate`, one step further out: the editing
    request is already waiting for a round trip and is the honest place to pay
    the raster, rather than the ``POST /play/pos`` of whoever walks next.
    """
    from app.core.heightfield import cached_sig
    current = cached_sig()
    if current is not None and current == height_sig():
        return
    _invalidate()


# ── The derived raster ───────────────────────────────────────────────────

def load_grid() -> Optional[Dict[str, Any]]:
    """The stored raster, or None when there is none / it is unreadable.

    An unreadable row is treated exactly like a missing one: the grid is a
    derived cache, and the areas it comes from are still there.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT origin_x, origin_z, step_m, n_rows, n_cols, heights, sig "
        "FROM world_heightfield WHERE id=1").fetchone()
    if row is None:
        return None
    try:
        heights = json.loads(row[5])
    except (TypeError, ValueError):
        return None
    if not isinstance(heights, list):
        return None
    return {"origin_x": float(row[0]), "origin_z": float(row[1]),
            "step_m": float(row[2]), "rows": int(row[3]),
            "cols": int(row[4]), "heights": heights, "sig": str(row[6] or "")}


def store_grid(field: Dict[str, Any]) -> None:
    """Persist the rastered grid (one row, id = 1)."""
    with transaction() as conn:
        conn.execute(
            "INSERT INTO world_heightfield (id, origin_x, origin_z, step_m, "
            "n_rows, n_cols, heights, sig, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET origin_x=excluded.origin_x, "
            "origin_z=excluded.origin_z, step_m=excluded.step_m, "
            "n_rows=excluded.n_rows, n_cols=excluded.n_cols, "
            "heights=excluded.heights, sig=excluded.sig, "
            "updated_at=excluded.updated_at",
            (field["origin_x"], field["origin_z"], field["step_m"],
             field["rows"], field["cols"],
             json.dumps(field["heights"], ensure_ascii=False),
             field["sig"], utc_now_iso()))


def polygon_bounds(polygon: Any) -> Optional[Tuple[float, float, float, float]]:
    """(min_x, min_z, max_x, max_z) over an outline, or None when it has no
    usable points. Unreadable vertices are skipped, never counted — the same
    rule ``world_bounds`` follows."""
    xs: List[float] = []
    zs: List[float] = []
    for pt in (polygon or []):
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            continue
        if not (math.isfinite(x) and math.isfinite(z)):
            continue
        xs.append(x)
        zs.append(z)
    if not xs:
        return None
    return (min(xs), min(zs), max(xs), max(zs))
