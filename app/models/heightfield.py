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
#: every renderer parses. The number itself is set over there, by what the
#: LINE TOOL generates; a height area is only ever clicked by hand and stays
#: far below it.
MAX_POINTS = 2050
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
    """The outline, 3..:data:`MAX_POINTS` finite ``[x, z]`` points on the
    2-decimal metre grid. Identical rules to a terrain area's polygon — same
    reasons, listed in ``app/models/terrain._sanitize_polygon``."""
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_POINTS:
        raise ValueError(f"polygon needs 3..{MAX_POINTS} points")
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


def save_height_area(raw: Any, must_exist: bool = False) -> Dict[str, Any]:
    """Create (no ``id``) or replace (with ``id``) one height area; returns the
    sanitized entry. Raises ValueError when it is not usable.

    ``must_exist`` is the singular PUT's rule, spelled exactly as its terrain
    twin (:func:`app.models.terrain.save_area`): the WRITE itself refuses —
    an ``UPDATE`` matching no row raises ``core.bulk_edit.GoneError`` — so a
    stale PUT racing a DELETE cannot raise a deleted hill from the dead.
    """
    area = sanitize_height_area(raw)
    # Microsecond resolution, because this stamp is the batch save's version
    # token (:func:`height_area_stamps`) — see ``terrain._edit_stamp``.
    now = utc_now_iso("microseconds")
    with transaction() as conn:
        if must_exist:
            cur = conn.execute(
                "UPDATE height_areas SET polygon=?, height_m=?, falloff_m=?, "
                "meta=?, updated_at=? WHERE id=?",
                (json.dumps(area["polygon"], ensure_ascii=False),
                 area["height_m"], area["falloff_m"],
                 json.dumps(area["meta"], ensure_ascii=False), now,
                 area["id"]))
            if not cur.rowcount:
                from app.core.bulk_edit import GoneError
                raise GoneError("height area")
        else:
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


def height_area_stamps() -> Dict[str, str]:
    """``{id: updated_at}`` of every stored height area — the version tokens
    the batch save checks against (``core.bulk_edit``).

    Kept out of :func:`list_height_areas` for the reason its terrain twin is
    (``terrain.area_stamps``): the list is what :func:`height_sig` hashes, and a
    re-save that changes no ground must not move the signature.
    """
    conn = get_connection()
    return {r[0]: str(r[1] or "")
            for r in conn.execute(
                "SELECT id, updated_at FROM height_areas").fetchall()}


def save_height_areas_bulk(upserts: Any, deletes: Any) -> Dict[str, Any]:
    """Write a whole relief edit — many areas, one transaction, ONE re-raster.

    The batch half of :func:`save_height_area` / :func:`delete_height_area`.
    :func:`_invalidate` is what makes it worth having: every singular write
    re-rasters the entire world grid synchronously (hundreds of milliseconds
    for a full-budget area), so drawing five hills used to pay for five
    rasters of the same world. Here it runs once, after the last write.

    Refusals are per object and never fail the request (``core.bulk_edit``).
    Returns ``{"saved": [{"temp_id", "area"}], "deleted": [id],
    "rejected": [...]}``.
    """
    from app.core.bulk_edit import plan_batch
    prepared, delete_ids, rejected = plan_batch(
        upserts, deletes, height_area_stamps(), sanitize_height_area)
    now = utc_now_iso("microseconds")
    saved: List[Dict[str, Any]] = []
    changed = 0
    with transaction() as conn:
        for area_id in delete_ids:
            cur = conn.execute("DELETE FROM height_areas WHERE id=?",
                               (area_id,))
            changed += int(cur.rowcount or 0)
        for entry in prepared:
            area = entry["obj"]
            conn.execute(
                "INSERT INTO height_areas (id, polygon, height_m, falloff_m, "
                "meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET polygon=excluded.polygon, "
                "height_m=excluded.height_m, falloff_m=excluded.falloff_m, "
                "meta=excluded.meta, updated_at=excluded.updated_at",
                (area["id"], json.dumps(area["polygon"], ensure_ascii=False),
                 area["height_m"], area["falloff_m"],
                 json.dumps(area["meta"], ensure_ascii=False), now, now))
            changed += 1
            saved.append({"temp_id": entry["temp_id"], "area": area})
    if changed:
        _invalidate()
    return {"saved": saved, "deleted": delete_ids, "rejected": rejected}


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

    THE ONE SPELLING OF THE LAW (§ A16.4). The scene builder used to carry a
    twin of it (``scene_recipe.is_natural_location``, asked of the COMPOSED
    room recipes); since E5a that twin decided nothing in the payload, so E6
    deleted it. This one asks the STORED location, which keeps the whole scene
    builder out of the walking gate's import path. The two questions are the
    contract, and they are:

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


def relief_basis() -> List[Dict[str, Any]]:
    """The MICRO-RELIEF inputs of the raster, in hashable form.

    Not "the painted terrain": exactly the areas
    ``core.heightfield.relief_inputs`` hands the raster — the ones that AUTHOR
    relief, plus the flat ones lying over them, each with the two numbers that
    shape its hills. Same function, same list, so the signature cannot describe
    a different world than the grid does.

    THE NUMBERS ARE THE AREA'S OWN since 2026-08-23, which is why nothing has
    to be added here for the move: the areas were already hashed, and the two
    numbers travel inside the very entries this walks. What DID have to move is
    the code version (``core.heightfield.HEIGHT_BAKE_VERSION``) — the RULE
    changed for data that did not.

    THE POINT OF THE FILTER is what it leaves out (decision 2026-08-13):
    painting on a world where nobody authored relief changes no height at all,
    so it must not move this signature and must not cost a re-raster. Terrain
    is painted stroke by stroke; a heightfield rebuild per stroke would be paid
    by whoever walks next.
    """
    from app.core.heightfield import relief_inputs
    from app.models.terrain import list_areas
    out: List[Dict[str, Any]] = []
    for area, params, _box in relief_inputs(list_areas()):
        out.append({"kind": area.get("kind"),
                    "polygon": area.get("polygon"),
                    # The seed is derivable from the kind, so only the two
                    # authored numbers travel; None is the flat area on top.
                    "relief": None if params is None else [params[1],
                                                           params[2]]})
    return out


def water_flow_speeds() -> Dict[str, float]:
    """Terrain kind -> the ``flow_speed`` dial of the SURFACE it wears, in m/s
    (K-A E1) — the denominator of the water raster's flow factor.

    THE CHAIN IS THE ONE THE RENDERER WALKED. A terrain type names a surface
    (``types[].surface``, § A1.5), the surface library entry carries the
    material declaration, and ``material.flow_speed`` is the kind's own speed.
    That was resolved in ``scene/ground.ts`` per painted area until the water
    raster took the flow over; it is resolved here now, once per generation, so
    exactly one place answers "how fast does this kind run".

    ONLY WATER KINDS ARE IN IT. Everything else contributes nothing to the water
    raster, and a map of the whole catalog would put every texture edit of the
    world into ``height_sig`` for nothing. A kind whose surface declares no
    ``flow_speed`` — which is every entry shipped before the dial existed —
    answers the module default, i.e. exactly the number the renderer fell back
    to.
    """
    from app.core.heightfield import WATER_FLOW_SPEED_DEFAULT_M_S
    from app.core.surface_textures import get_kind_meta
    from app.core.terrain_types import effective_catalog, is_water_kind
    catalog = effective_catalog()
    library = get_kind_meta()
    out: Dict[str, float] = {}
    for kind, entry in catalog.items():
        if not is_water_kind(kind, catalog):
            continue
        surface = str((entry or {}).get("surface") or "").strip().lower()
        material = (library.get(surface) or {}).get("material")
        speed = None
        if isinstance(material, dict):
            try:
                speed = float(material.get("flow_speed"))
            except (TypeError, ValueError):
                speed = None
        out[kind] = (WATER_FLOW_SPEED_DEFAULT_M_S
                     if speed is None or not math.isfinite(speed) else speed)
    return out


def water_basis() -> List[Dict[str, Any]]:
    """The WATER inputs of the bake, in hashable form (E1, § A16.3).

    Every painted area of a water kind with everything that shapes its carve —
    the mirror (absent while it is still "auto"), the two optional END levels,
    the flow bearing of a river AND (W4a) the drawn line it may follow instead
    (``flow_along`` plus the centre line AND its ribbon WIDTH — the width is the
    reach of the cross section every knot level is the median of, W5b, so it
    shapes the bed as directly as the line does), and the depth and shore ramp
    AS RESOLVED against the kind's defaults. They belong in the signature for the same
    reason the height areas do: moving a lake's level moves the ground under it,
    and a client holding the old grid would draw a bed the server does not have.

    THE RESOLVED WIDTHS ARE WHY THE KIND IS IN HERE AT ALL (W1): a world that
    dials its "river" type from 2 m deep to 6 m changes every river bed in it
    without touching a single area, and the effective numbers carry that into
    the hash without a second basis function. ``bed_kind`` is NOT here — it
    paints, it does not carve, and it lives in ``terrain_layers.layers_sig``.

    A world that flags no kind as water contributes an empty list and costs
    nothing, exactly like :func:`relief_basis` on a world without hills.
    """
    from app.core.heightfield import water_areas, water_meta
    from app.core.terrain_types import effective_catalog, water_kind_defaults
    from app.models.terrain import list_areas
    catalog = effective_catalog()
    speeds = water_flow_speeds()
    out: List[Dict[str, Any]] = []
    for area, _box in water_areas(list_areas(), catalog):
        kind = str(area.get("kind") or "")
        meta = water_meta(area, water_kind_defaults(kind, catalog))
        out.append({"id": area.get("id"), "polygon": area.get("polygon"),
                    "level": meta.level, "up": meta.level_up,
                    "down": meta.level_down, "flow": meta.flow_dir_deg,
                    "along": meta.flow_along, "line": meta.stroke_points,
                    "width": meta.stroke_width_m,
                    "depth": meta.depth_m, "ramp": meta.shore_ramp_m,
                    # THE TWO SPEED NUMBERS ARE NEW WITH THE WATER RASTER
                    # (K-A E1) and they had to be: the tile now SHIPS the flow
                    # vector, whose length is the area's speed over its kind's
                    # (``heightfield.water_flow_factor``). Until the raster
                    # existed both were pure look — read straight off the meta
                    # by the renderer, hashed by nobody — and a world that
                    # re-dialled a river's speed would have kept serving the
                    # tiles it had. They are the only inputs of this signature
                    # that do not move ``h_final`` by a millimetre.
                    "speed": meta.flow_speed_m_s,
                    "kind_speed": speeds.get(kind)})
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

    AND SO DO THE WATER POLYGONS (:func:`water_basis`, E1, § A16.3): a lake's
    mirror, depth and shore ramp — and a river's flow bearing and end levels —
    shape the ground under it exactly as a height area does. Only the PAINTED
    ones: since W1 a room floor carves nothing at all, so the fifth basis is
    gone with the fifth bake stage and there is no fallback reader.

    AND SO DOES THE MICRO-RELIEF (:func:`relief_basis`, decision 2026-08-13,
    per AREA since 2026-08-23): an area that authors hills — or a change to its
    amplitude or wave — moves the ground exactly as a height area does. An area
    that authors none does not appear here at all.

    AND SO DOES THE BAKE CODE ITSELF (``HEIGHT_BAKE_VERSION``): the grid is a
    function of the code as much as of the areas, and a changed carve or ramp
    rule used to leave this signature exactly where it was — clients and stored
    rasters kept the old ground until someone saved an area by hand.
    """
    from app.core.heightfield import HEIGHT_BAKE_VERSION
    basis = json.dumps({"code_version": HEIGHT_BAKE_VERSION,
                        "areas": list_height_areas(),
                        "places": placed_footprints(),
                        "terrain": relief_basis(),
                        "water": water_basis()},
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


def load_tile_stats(sig: str) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """Every stored tile statistic of THIS signature, keyed ``(tx, tz)``.

    The tile-level twin of :func:`load_grid`, and it exists for a bigger
    reason than the grid does. A statistic is read off a FINISHED 129² raster,
    so asking for the statistics of the whole world means rastering the whole
    world — measured 2026-08-24 on a 1077-tile world: 102 seconds of pure
    Python, and every fresh process paid it again because the cache lived in
    the process. Stored, that bill is paid once per signature and a restart
    costs one SELECT.

    ROWS OF ANOTHER SIGNATURE ARE NOT READ. They describe a world that has been
    edited since and are dropped by the next writer (:func:`store_tile_stats`);
    a mismatch means "raster it again", exactly as it does for the grid.

    An unreadable row is skipped rather than failing the read — the statistics
    are a derived cache and the tile behind one is still rasterable.
    """
    if not sig:
        return {}
    conn = get_connection()
    rows = conn.execute(
        "SELECT tx, tz, stats FROM world_height_tile_stats WHERE sig=?",
        (str(sig),)).fetchall()
    out: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for tx, tz, raw in rows:
        try:
            stats = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(stats, dict):
            out[(int(tx), int(tz))] = stats
    return out


def store_tile_stats(sig: str,
                     stats_by_key: Dict[Tuple[int, int], Dict[str, Any]]
                     ) -> None:
    """Persist freshly computed tile statistics under ``sig``, in ONE write.

    Called with whatever a single request just had to compute, so the batch is
    at most a client batch (64) and usually far less.

    EVERY ROW OF ANOTHER SIGNATURE GOES IN THE SAME TRANSACTION. The table is a
    cache of the CURRENT world, and keeping the old generations would grow it
    without bound over a world's editing life for rows nobody may read. That
    also makes the invalidation trivial: there is never more than one
    signature's worth of rows in there, and a row of the current one is by
    definition current.
    """
    if not sig or not stats_by_key:
        return
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute("DELETE FROM world_height_tile_stats WHERE sig<>?",
                     (str(sig),))
        conn.executemany(
            "INSERT INTO world_height_tile_stats (sig, tx, tz, stats, "
            "updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(sig, tx, tz) DO UPDATE SET stats=excluded.stats, "
            "updated_at=excluded.updated_at",
            [(str(sig), int(tx), int(tz),
              json.dumps(stats, ensure_ascii=False), now)
             for (tx, tz), stats in stats_by_key.items()])


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
