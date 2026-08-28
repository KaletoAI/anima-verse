"""Room recipe (plan-room-props.md) — ONE endpoint for a furnished room.

The raw data already flows to the client through the location payload
(``rooms[].layout`` with outline/surfaces/openings/props); the recipe adds
the COMPOSED conveniences so the client renders without re-deriving them:

- ``outline`` in ABSOLUTE LOCAL METRES (the drawn hull or the implicit
  rectangle — no room-local mechanics on the client side),
- ``openings`` normalized to polygon edge INDICES (legacy letters converted,
  S/W flip their ``at`` against the clockwise edge direction) — INCLUDING the
  neighbours' openings that sit on a shared wall: one physical door is edited
  only in the room that owns it but has to be a hole in BOTH rooms' walls, so
  the recipe mirrors it geometrically (see ``_mirrored_openings``),
- ``placements`` joined with each prop's real dims + its mesh tiers (REAL-SIZE
  rule: a placement never scales a prop — its own dims × the plan factor k
  do), and
- ``prop_markers`` as fully composed transforms RELATIVE to their placement
  anchor: the object-local marker ran through orientation fix → real-size
  scale → placement yaw, anchored exactly like the mesh (oriented-box
  bottom centre on the placement point). The client adds
  ``placement world position + offset_m × k`` — one multiply, no marker
  math.

The GROUND room is the one carrier without geometry (§ A13a): it composes
through :func:`compose_ground_recipe` into the same payload shape minus hull
and openings — placements and markers whose ``at`` is a location-local metre
already, scattered inside the drawn boundary instead of a room hull.

Coordinate frames (contract v6 Nr. 2 — the metric wave): XZ positions are
LOCAL METRES around the location's anchor pin, the same frame ``layout.x/y``,
``map3d.outline`` and ``map3d.boundary`` are stored in. There is no fraction
anywhere in this module any more; a length ending in ``_m`` is the same metre,
and since E4 that is already a world metre too (k = 1).

THE ROOM MAY BE TURNED (contract v6 addendum "Der Raum dreht sich ganz"):
``layout.rotation`` turns the WHOLE room about its rect centre
``(x + w/2, y + d/2)`` on the way from the room's own frame into the
location's. :func:`room_transform` is that step, and it is the only place it
happens — storage stays straight, so drawing stays a straight-on gesture.

Yaw/facing are degrees; the compass vocabulary of the room markers applies
(0 = south, 90 = east, …), composed prop facing = ``facing − placement.yaw``
(the plan yaw turns clockwise in the top view, the compass counts the other
way around).
"""

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.scatter_curves import scatter as _scatter_props
from app.core.scatter_curves import tessellate
from app.core.scatter_curves import variant_mix

logger = get_logger(__name__)


def _rect_outline(w: float, d: float) -> List[List[float]]:
    """The implicit rectangle hull in the room's OWN metres, clockwise on
    screen (y down) — edge 0 = N, 1 = E, 2 = S, 3 = W, exactly the indexing
    the letter openings map onto."""
    return [[0.0, 0.0], [w, 0.0], [w, d], [0.0, d]]


def _r(v: float, nd: int = 4) -> float:
    out = round(float(v), nd)
    return out if out != 0 else 0.0  # never -0.0 in payloads


def _rot_matrix(rotation: Any) -> List[List[float]]:
    """Ry·Rx·Rz (three.js **'YXZ'** Euler, degrees) — the order the payload
    declares the orientation fix in (``scene_recipe._fix_euler``, § A1) and the
    one every renderer applies it in (``place()`` sets ``rotation.order =
    'YXZ'``). With a single non-zero axis — what a 90°-step fix normally is —
    'XYZ' and 'YXZ' are identical; with two, they are not, and this matrix has
    to be the renderers'."""
    rot = rotation if isinstance(rotation, dict) else {}
    try:
        rx = math.radians(float(rot.get("x") or 0))
        ry = math.radians(float(rot.get("y") or 0))
        rz = math.radians(float(rot.get("z") or 0))
    except (TypeError, ValueError):
        rx = ry = rz = 0.0
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cy * cz + sy * sx * sz, sy * sx * cz - cy * sz, sy * cx],
        [cx * sz, cx * cz, -sx],
        [cy * sx * sz - sy * cz, sy * sz + cy * sx * cz, cy * cx],
    ]


def _snap90(rotation: Any) -> Dict[str, float]:
    """The orientation fix rounded to whole 90° steps (§ B2 step 1, v5.1 Nr. 4).

    How BIG an object is must not depend on how finely it is tilted: the
    axis-aligned hull of a diagonally turned box is larger than the box, so a
    fine fix angle would shrink the object. ``place()`` therefore MEASURES with
    the rounded fix and DRAWS with the real one — and the marker composition
    has to measure with the very same number, or the seat sits on a prop of a
    different size than the mesh next to it."""
    rot = rotation if isinstance(rotation, dict) else {}
    out: Dict[str, float] = {}
    for axis in ("x", "y", "z"):
        try:
            out[axis] = round(float(rot.get(axis) or 0) / 90.0) * 90.0
        except (TypeError, ValueError):
            out[axis] = 0.0
    return out


def _apply(m: List[List[float]], p: List[float]) -> List[float]:
    return [m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] for r in range(3)]


def _oriented_box(m: List[List[float]], size: List[float],
                  ) -> Tuple[List[float], List[float]]:
    """AABB ``(lo, hi)`` of the raw box ``[0, size]`` turned by ``m``."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                q = _apply(m, [i * size[0], j * size[1], k * size[2]])
                for a in range(3):
                    lo[a] = min(lo[a], q[a])
                    hi[a] = max(hi[a], q[a])
    return lo, hi


_EDGE_INDEX = {"N": 0, "E": 1, "S": 2, "W": 3}


def _normalize_opening(op: Dict[str, Any]) -> Dict[str, Any]:
    """Letters map onto the implicit unit square's clockwise edges
    (0=N TL→TR, 1=E TR→BR, 2=S BR→BL, 3=W BL→TL); letter ``at`` runs
    left→right / top→bottom, so S and W flip. Mirrors
    ``planGeometry.normalizeOpeningEdge`` — change both or neither."""
    out = dict(op)
    edge = op.get("edge")
    if isinstance(edge, str):
        out["edge"] = _EDGE_INDEX.get(edge, 0)
        if edge in ("S", "W"):
            out["at"] = _r(1.0 - float(op.get("at") or 0))
    return out


# ── Shared-wall geometry ────────────────────────────────────────────────
# Mirror image of ``planGeometry.sharedEdges`` (frontend) — SAME tolerances,
# SAME antiparallel test, so server and editor agree on what "one wall" is.
# Change both or neither. Every coordinate here is a LOCAL METRE (v6 Nr. 2),
# so the two thresholds ARE the numbers below — the conversion through a plan
# width, and with it the 8 m stand-in for unanchored data, is gone.
SHARE_TOL_M = 0.15
MIN_SHARE_M = 0.8
# Scatter keep-outs (plan-area-detail-scenes.md): clearance in REAL metres in
# front of an opening (beyond its half width) and around markers /
# model-less manual props. Axis-aligned squares on purpose — § B5a wants the
# arithmetic hand-checkable.
SCATTER_OPENING_CLEAR_M = 0.6
SCATTER_POINT_CLEAR_M = 0.5
# Opening types a character can walk through (a window is not a way out).
_WALKABLE_TYPES = ("door", "passage")


def _layout_rect(lay: Any) -> Optional[tuple]:
    """(x, y, w, d) of a layout, or None when it is not a usable rectangle.

    This is the room's UNROTATED rectangle — the frame everything inside the
    room is stored in. ``layout.rotation`` never touches it (see
    :func:`room_transform`)."""
    if not isinstance(lay, dict):
        return None
    try:
        return (float(lay["x"]), float(lay["y"]),
                float(lay["w"]), float(lay["d"]))
    except (KeyError, TypeError, ValueError):
        return None


def layout_rotation(lay: Any) -> float:
    """``layout.rotation`` in degrees, 0 when absent or unusable.

    Contract v6 addendum "Der Raum dreht sich ganz": the angle turns the
    WHOLE room about its rect centre, not just its model."""
    if not isinstance(lay, dict):
        return 0.0
    try:
        return float(lay.get("rotation") or 0) % 360.0
    except (TypeError, ValueError):
        return 0.0


def room_transform(lay: Any) -> Any:
    """``f(u, v) -> (x, y)``: ROOM-local metres → LOCATION-local metres.

    Two steps, in this order and nowhere else in the codebase:

    1. translate by the room's min corner (``layout.x``/``y``),
    2. turn the whole room about its rect CENTRE ``(x + w/2, y + d/2)`` by
       ``layout.rotation``, with the ONE rotation of § A1.1
       (``world_geometry.local_to_world``) — the same matrix the map uses for
       a location pin and the same sense both renderers apply to a placement
       yaw (``rotation.y = +rad(yaw)``).

    Everything a room owns goes through here: its hull, its curve control
    points, its prop placements, its markers and its diorama anchor. Storage
    stays in the room's own straight frame — the turn is applied on the way
    out, so drawing stays a straight-on gesture.

    A layout without a usable rectangle (the GROUND room, § A13a) or without
    a rotation gets the plain translation; the identity path costs nothing.
    """
    rect = _layout_rect(lay)
    if not rect:
        return lambda u, v: (float(u), float(v))
    x, y, w, d = rect
    rot = layout_rotation(lay)
    if not rot:
        return lambda u, v: (x + float(u), y + float(v))
    from app.core.world_geometry import local_to_world
    cx, cy = x + w / 2.0, y + d / 2.0
    return lambda u, v: local_to_world(x + float(u) - cx, y + float(v) - cy,
                                       cx, cy, rot)


def _abs_outline(lay: Dict[str, Any]) -> List[List[float]]:
    """A layout's hull in ABSOLUTE LOCAL METRES (mirrors
    ``planGeometry.absOutline``); [] when the layout has no usable rect.

    The stored points are metres from the room's own min corner, so placing
    the hull is the room transform: translation plus the room's own turn
    about its rect centre. Nothing is scaled here."""
    rect = _layout_rect(lay)
    if not rect:
        return []
    _x, _y, w, d = rect
    pts = lay.get("outline")
    if not isinstance(pts, list) or len(pts) < 3:
        pts = _rect_outline(w, d)
    place = room_transform(lay)
    try:
        return [list(place(float(u), float(v))) for u, v in pts]
    except (TypeError, ValueError):
        return []


def _abs_shape(lay: Dict[str, Any]) -> List[List[float]]:
    """Like ``_abs_outline`` but with curved edges TESSELLATED — the shape a
    renderer actually sees. Beziers are affine-invariant and a rotation is
    affine, so tessellating in the room-local frame and placing afterwards is
    exact."""
    rect = _layout_rect(lay)
    if not rect:
        return []
    _x, _y, w, d = rect
    pts = lay.get("outline")
    if not isinstance(pts, list) or len(pts) < 3:
        pts = _rect_outline(w, d)
    tess, _ = tessellate(pts, lay.get("outline_curves"))
    place = room_transform(lay)
    try:
        return [list(place(float(u), float(v))) for u, v in tess]
    except (TypeError, ValueError):
        return []


def room_outline_local(lay: Any) -> List[List[float]]:
    """A room's HULL in the location's local metres — the public name of
    :func:`_abs_shape` ("Ein Boden" E5a).

    It is byte for byte the polygon ``compose_recipe`` puts into its
    ``outline`` (same tessellation, same room transform), and that identity is
    the point: the LAYER BAKE of the ground (``core.terrain_layers``) and the
    ZONE-WATER carve of the heightfield need a room's floor polygon without
    paying for a whole recipe — props, scatter, mirrored openings and a
    signature — and a second derivation of the hull would put the material of
    the ground on a different rectangle than the scene payload draws its walls
    on. Pinned in ``scripts/smoke_terrain_layers.py`` against
    ``scene_recipe.compose_scene``.

    [] when the layout has no usable rectangle.
    """
    return _abs_shape(lay if isinstance(lay, dict) else {})


def _unit_edge(outline: List[List[float]], i: int) -> Optional[tuple]:
    """Directed edge i as (ax, ay, ux, uy, length); None for a degenerate one."""
    a = outline[i]
    b = outline[(i + 1) % len(outline)]
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return (a[0], a[1], dx / length, dy / length, length)


def _point_on_edge(outline: List[List[float]], i: int,
                   at: float) -> List[float]:
    a = outline[i]
    b = outline[(i + 1) % len(outline)]
    return [a[0] + (b[0] - a[0]) * at, a[1] + (b[1] - a[1]) * at]


def _mirrored_openings(lay: Dict[str, Any],
                       siblings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The neighbours' openings that physically pierce THIS room's wall.

    An opening is one hole in one wall. It is defined and edited in the room
    that owns it, but a wall between two rooms belongs to both — so every
    sibling opening whose centre falls on a shared edge of this room is
    reported here as a normal opening entry, translated onto this room's own
    edge index and ``at``.

    The translation is a projection, not a formula: the two hulls are wound
    clockwise, so a shared wall is traversed in OPPOSITE directions by the two
    rooms — projecting the opening's world point onto this room's directed
    edge flips ``at`` by itself. ``to`` becomes the owning room (that is where
    the door leads from here) and ``mirrored`` marks the entry as
    not-editable-here; everything else (type/width/height/sill) is carried
    over unchanged.
    """
    outline = _abs_outline(lay)
    if len(outline) < 3:
        return []
    tol = SHARE_TOL_M
    min_overlap = MIN_SHARE_M
    level = int(lay.get("level") or 0)

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for sibling in siblings:
        slay = sibling.get("layout")
        if not isinstance(slay, dict) or int(slay.get("level") or 0) != level:
            continue
        sib_id = str(sibling.get("id") or "")
        sib_outline = _abs_outline(slay)
        if len(sib_outline) < 3:
            continue
        sib_openings = [_normalize_opening(op)
                        for op in (slay.get("openings") or [])
                        if isinstance(op, dict)]
        if not sib_openings:
            continue

        for i in range(len(outline)):
            mine = _unit_edge(outline, i)
            if not mine:
                continue
            ax, ay, ux, uy, alen = mine
            for j in range(len(sib_outline)):
                theirs = _unit_edge(sib_outline, j)
                if not theirs:
                    continue
                bx, by, vx, vy, _ = theirs
                # Antiparallel within ~1°: two rooms meeting at a wall face
                # each other (both hulls wound clockwise).
                if abs(ux * vy - uy * vx) > 0.02 or ux * vx + uy * vy > -0.98:
                    continue
                if abs((bx - ax) * uy - (by - ay) * ux) > tol:
                    continue
                t0 = (bx - ax) * ux + (by - ay) * uy
                b_end = sib_outline[(j + 1) % len(sib_outline)]
                t1 = ((b_end[0] - ax) * ux + (b_end[1] - ay) * uy)
                start = max(0.0, min(t0, t1))
                end = min(alen, max(t0, t1))
                if end - start < min_overlap:
                    continue

                for op in sib_openings:
                    try:
                        if int(op.get("edge") or 0) != j:
                            continue
                        at = float(op.get("at") or 0)
                    except (TypeError, ValueError):
                        continue
                    px, py = _point_on_edge(sib_outline, j, at)
                    t = (px - ax) * ux + (py - ay) * uy
                    if t < start - 1e-9 or t > end + 1e-9:
                        continue  # the opening sits outside the shared stretch
                    key = (sib_id, j, round(at, 6))
                    if key in seen:
                        continue
                    seen.add(key)
                    entry = dict(op)
                    entry["edge"] = i
                    entry["at"] = _r(max(0.0, min(1.0, t / alen)))
                    entry["to"] = sib_id
                    entry["mirrored"] = True
                    out.append(entry)
    return out


def compose_prop_marker(*, bbox: List[float], rotation: Any,
                        dims: List[float], frac: List[float],
                        facing: Optional[float], placement_yaw: float,
                        placement_offset_y: float) -> Dict[str, Any]:
    """One object-local marker → placement-relative world transform.

    ``bbox`` = raw AABB edge lengths (mesh units, raw axes), ``dims`` =
    [width, depth, height] real metres (post-fix), ``frac`` = [u, v, w]
    fractions of the raw box. The chain mirrors the mesh placement STEP FOR
    STEP (§ B2), because the result is added to the very anchor the mesh is
    seated on:

    1. orientation fix, 'YXZ' (translation-invariant — the raw box is taken
       as [0, size]),
    2. uniform real-size scale = max(dims) / largest extent of the box turned
       by the **90°-ROUNDED** fix (§ B2 step 2, v5.1 Nr. 4: measured rounded,
       drawn exact) — measuring the exact fix here made the marker ride a
       prop up to 21 % smaller than the mesh beside it,
    3. anchor at the bottom centre of the box turned by the EXACT fix — the
       object's own seating point, BEFORE the yaw (§ B2 step 4),
    4. placement yaw, which turns that offset about the same point.

    Step 3 is why § B2 measures its seating box before the yaw: the server has
    only the prop's ``bbox``, so the yawed hull of the real mesh is not a datum
    it can reproduce. Both ends now spin the object about its own centre and
    land on the same point.

    Residual, stated rather than hidden: for a fix that is NOT a 90° step the
    box proxy is not the mesh (turning a box around a box overestimates), so
    the seating centre of step 3 differs from the renderer's measured hull —
    measured 5 cm on the one such prop in the field (a stool at fix x 350).
    A 90°-step fix, which is what an orientation fix normally is, is exact.
    """
    m = _rot_matrix(rotation)
    size = [abs(float(bbox[i])) for i in range(3)]
    # Size: the 90°-rounded fix (§ B2 step 2) — the fine angle must not change
    # how big the object is, and the renderer measures the same rounded box.
    slo, shi = _oriented_box(_rot_matrix(_snap90(rotation)), size)
    extents = [shi[a] - slo[a] for a in range(3)]
    s = (max(dims) or 1.0) / (max(extents) or 1.0)
    # Seat: the box turned by the EXACT fix — that is where the mesh stands.
    lo, hi = _oriented_box(m, size)
    p = _apply(m, [frac[0] * size[0], frac[1] * size[1], frac[2] * size[2]])
    # Anchor: oriented-box bottom centre = the placement point (exactly how
    # the mesh itself is seated).
    pre = [s * (p[0] - (lo[0] + hi[0]) / 2),
           s * (p[1] - lo[1]),
           s * (p[2] - (lo[2] + hi[2]) / 2)]
    # The placement yaw turns the offset with the SAME matrix that turns the
    # mesh — ``rotation.y = +rad(yaw)`` = R_y(+yaw) since E4 (§ A2 step 4).
    # Until the final E4 review this was R_y(−yaw), the compensation for the
    # old ``rotation.y = −rad(yaw)``; with the flipped render sites it sent
    # every marker of a turned prop to the mirrored side.
    yaw = math.radians(float(placement_yaw or 0))
    dx = pre[0] * math.cos(yaw) + pre[2] * math.sin(yaw)
    dz = -pre[0] * math.sin(yaw) + pre[2] * math.cos(yaw)
    out: Dict[str, Any] = {
        "offset_m": [_r(dx, 3), _r(dz, 3)],
        "height_m": _r(pre[1] + float(placement_offset_y or 0), 3),
    }
    # No object facing declared (the auto-furnish default) → the sitter still
    # follows the CHAIR: assume the prop's front is south (facing 0) in
    # object space, so the composed facing rides the placement yaw. A prop
    # whose front is not south gets its marker facing set once at the object
    # (existing mechanism) — without this default every sitter on a rotated
    # chair kept the world default and looked the same way.
    # Facing grows in the SAME sense as the placement yaw since E4 (§ A1.8 —
    # both render as ``rotation.y = +rad(…)``), so the yaw is ADDED. The
    # earlier subtraction was the mirror image of the old model-yaw sign.
    eff_facing = 0.0 if facing is None else float(facing)
    out["facing"] = _r((eff_facing + float(placement_yaw or 0)) % 360, 1)
    return out


def _square(cx: float, cy: float, half: float) -> List[List[float]]:
    """Axis-aligned keep-out square around a point (§ B5a: hand-checkable)."""
    return [[cx - half, cy - half], [cx + half, cy - half],
            [cx + half, cy + half], [cx - half, cy + half]]


def _variant_entry(prop: Dict[str, Any], variant: Any) -> Optional[Dict[str, Any]]:
    """The published variant entry a placement DRAWS, or ``None`` when the prop
    publishes none (no mesh anywhere).

    ``variant`` is a POSITION in ``variant_tiers`` (the published list), never
    a store index — the same number ``scene_recipe._variant_index`` resolves
    against ``model_variants``, and it wraps the same way, so a placement whose
    stored index outlived a deleted mesh keeps its size instead of vanishing.

    ONE lookup for all three of the variant's facts (size, sink, markers): a
    placement that took its dims from one entry and its sink from another would
    be a bench of one version floating at another version's height.
    """
    entries = prop.get("variant_tiers") or []
    if not entries:
        return None
    try:
        pos = max(0, int(variant or 0)) % len(entries)
    except (TypeError, ValueError):
        pos = 0
    entry = entries[pos]
    return entry if isinstance(entry, dict) else None


def _carry_ground_offset(entry: Dict[str, Any], prop: Dict[str, Any],
                         variant: Any) -> None:
    """Put the ground offset of the VARIANT this placement draws onto the
    placement entry — and only when it is not zero
    (``props.GROUND_OFFSET_DEFAULT``).

    A fact about the MESH (variant-owned since 2026-08-25), carried on the
    placement because that is where every consumer of the recipe already
    stands: the scene spec adds it to the ``bottom_y`` it composes
    (``scene_recipe._prop_models``) and the prop markers of the same placement
    ride it down with the mesh.

    ABSENT = 0.0, exactly as the sidecar stores it: sending a 0.0 would make
    "stands on the ground" two payload shapes for one behaviour, and it would
    put a key on every placement in every world for nothing. The placement's
    own ``offset_y`` stays untouched — it is the per-instance trim, and folding
    the two into one number would make the editor's dial read back a value
    nobody typed there.
    """
    published = _variant_entry(prop, variant)
    source = published if published is not None else prop
    off = float(source.get("ground_offset_m") or 0.0)
    if off:
        entry["ground_offset_m"] = _r(off, 2)


def _placement_dims(prop: Dict[str, Any], variant: Any) -> Dict[str, float]:
    """The three real metres THIS placement renders at (2026-08-24).

    The size belongs to the VARIANT the placement shows — a sapling beside the
    grown pine — and the library resolved it when it built the record
    (``props.variant_dims``); all that happens here is the index lookup. A prop
    that publishes no variant at all (no mesh anywhere) falls back to the
    record, which answers for its PRIMARY variant.
    """
    published = _variant_entry(prop, variant)
    dims = (published or {}).get("dims")
    if isinstance(dims, dict) and dims:
        return {k: float(dims.get(k) or prop[k])
                for k in ("width_m", "depth_m", "height_m")}
    return {k: float(prop[k]) for k in ("width_m", "depth_m", "height_m")}


def _placement_markers(prop: Dict[str, Any], variant: Any) -> List[Dict[str, Any]]:
    """The OBJECT-LOCAL markers of the VARIANT this placement draws
    (2026-08-25).

    The fractions are of THAT mesh's bounding box, so a seat authored on the
    grown chair has no business on the broken one. A prop that publishes no
    variant falls back to the record's list, which is its PRIMARY variant's.
    """
    published = _variant_entry(prop, variant)
    if published is not None:
        markers = published.get("markers")
        return markers if isinstance(markers, list) else []
    return prop.get("markers") or []


def _join_placements(lay: Dict[str, Any], place: Any, room_yaw: float,
                     default_u: float, default_v: float,
                     ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(placements, prop_markers)`` of one layout, joined with the library.

    ``place`` maps a stored ``at`` into the payload frame: the ROOM transform
    for a room layout (min corner + the room's own turn, :func:`room_transform`),
    the identity for the ground, whose ``at`` already IS a location-local
    metre (§ A13a). ``room_yaw`` is the room's rotation in degrees: a prop
    stands IN the room, so the room's turn is added to its own placement yaw —
    that is what keeps a bed against the same wall when the room turns.
    ``default_u``/``default_v`` stand in for a placement without ``at`` (a
    room's centre; the pin for the ground).

    Dangling ids keep their placement and are flagged ``missing`` — world data
    lives in the DB, props are files, so there is no referential integrity by
    design and a placeholder beats a silently lost placement.
    """
    from app.core import props as prop_store
    placements: List[Dict[str, Any]] = []
    prop_markers: List[Dict[str, Any]] = []
    for placement in (lay.get("props") or []):
        if not isinstance(placement, dict):
            continue
        pid = str(placement.get("prop_id") or "")
        at = placement.get("at") or [default_u, default_v]
        # The prop's OWN yaw plus the room's — one turn of the room turns
        # every piece of furniture in it by the same angle.
        yaw = (float(placement.get("yaw") or 0) + room_yaw) % 360
        off_y = float(placement.get("offset_y") or 0)
        px, py = place(float(at[0]), float(at[1]))
        entry: Dict[str, Any] = {
            "prop_id": pid,
            # The placement's stable id and label (plan-posen-plaetze.md): a
            # prop marker is the place "<placement.id>/<marker.id>", and the
            # label names it in a chip.
            "id": str(placement.get("id") or ""),
            "label": str(placement.get("label") or ""),
            "at": [_r(px), _r(py)],
            "yaw": _r(yaw, 1),
            "offset_y": _r(off_y, 3),
        }
        # An authored variant choice rides along (E2.3): the scene spec reads
        # it off the recipe placement (``scene_recipe._variant_index``), so
        # dropping it here would silently show variant 0 for every manual
        # placement no matter what the editor picked.
        if placement.get("variant") is not None:
            try:
                entry["variant"] = max(0, int(placement.get("variant")))
            except (TypeError, ValueError):
                pass
        # The DEPTH CUT of this placement (§ B2 addendum 2026-08-23) travels
        # as it was authored; the scene spec turns it into the finished
        # ``cut_plane``, because only there is the placement's world anchor
        # known. A scattered copy carries none — the cut is an act on ONE
        # hand-placed piece of furniture.
        if placement.get("cut_keep") is not None:
            try:
                keep = float(placement.get("cut_keep"))
            except (TypeError, ValueError):
                keep = 1.0
            if 0 < keep < 1:
                entry["cut_keep"] = _r(keep, 3)
                entry["cut_side"] = ("front"
                                     if placement.get("cut_side") == "front"
                                     else "back")
        prop = prop_store.get_prop(pid)
        if not prop:
            entry["missing"] = True
            placements.append(entry)
            continue
        # The size of the VARIANT this placement shows, not of the prop record
        # (2026-08-24) — the scene spec turns it into `max_m`, the depth cut
        # and the placeholder box, and the markers below scale with it.
        entry["dims"] = _placement_dims(prop, entry.get("variant"))
        entry["prop_name"] = str(prop.get("name") or pid)
        _carry_ground_offset(entry, prop, entry.get("variant"))
        entry["has_model"] = bool(prop.get("has_model"))
        if prop.get("has_model"):
            # Which resolution tiers the prop has, plus the change key of its
            # mesh SELECTION: the scene payload turns the tiers into
            # ``variants`` URLs, and the signature moves when a prop gets a
            # new mesh (the URL alone never changes).
            entry["model_tiers"] = prop.get("model_tiers") or []
            # …and the same per ACTIVE model variant (E2.3), element 0 being
            # the primary one. The scene spec turns this into `model_variants`
            # and keeps `variants` pointing at element 0.
            entry["variant_tiers"] = prop.get("variant_tiers") or []
            entry["model_sig"] = prop.get("model_signature") or ""
        idx = len(placements)
        placements.append(entry)
        bbox = prop.get("bbox")
        if not bbox:
            continue  # no measurable mesh — markers stay object data only
        dims = [entry["dims"]["width_m"], entry["dims"]["depth_m"],
                entry["dims"]["height_m"]]
        # The markers of the VARIANT this placement draws (2026-08-25) — the
        # same entry its dims came from, so the seat sits on the mesh that is
        # really there.
        # …under the orientation fix of that same variant's FILE (v2 E1):
        # the fix is a fact of the mesh the marker sits on.
        published = _variant_entry(prop, entry.get("variant")) or {}
        for marker in _placement_markers(prop, entry.get("variant")):
            composed = compose_prop_marker(
                bbox=bbox, rotation=published.get("rotation"), dims=dims,
                frac=[float(v) for v in marker.get("at") or [0.5, 0, 0.5]],
                facing=marker.get("facing"), placement_yaw=yaw,
                placement_offset_y=off_y)
            composed["id"] = str(marker.get("id") or "")
            composed["group"] = str(marker.get("group") or "")
            composed["capacity"] = int(marker.get("capacity") or 1)
            composed["spacing_m"] = float(marker.get("spacing_m") or 0.6)
            composed["placement"] = idx
            prop_markers.append(composed)
    return placements, prop_markers


def _scatter_into(placements: List[Dict[str, Any]],
                  scatter_sources: List[Dict[str, Any]],
                  keep_in: List[List[float]],
                  keepouts: List[List[List[float]]],
                  variant_seed: int) -> None:
    """Append the scattered copies of every scattering placement, in place.

    Prop scatter (plan-area-detail-scenes.md, 2026-08-02 redesign) is a
    PLACEMENT property, not a list of its own: a placement with
    ``scatter_count`` throws that many copies of its prop over ``keep_in``
    from its own ``scatter_seed``, while the placement itself stays as the
    manually positioned anchor. Positions are computed at COMPOSE time and
    never stored, so every renderer derives the same forest and the recipe
    signature moves with seed/count/spacing (the copies land in the hashed
    payload).

    ``keep_in`` is the area the copies may land in — a room's hull, or the
    LOCATION BOUNDARY for the ground (§ A13a); ``keepouts`` are the geometric
    exclusion zones (sibling hulls, openings, markers). ``scatter_spacing_m``
    alone rules the density (0 = copies may overlap; the old footprint
    minimum kept every tree a crown apart). Copies are appended AFTER all
    manual entries so ``prop_markers[].placement`` indices never move, and
    they get NO prop markers (no sit spots on twenty pines).
    """
    from app.core import props as prop_store
    for source in scatter_sources:
        pid = str(source.get("prop_id") or "")
        try:
            count = int(source.get("scatter_count") or 0)
            seed = variant_mix(int(source.get("scatter_seed") or 0),
                               variant_seed)
        except (TypeError, ValueError):
            continue
        try:
            spacing = float(source.get("scatter_spacing_m") or 0)
        except (TypeError, ValueError):
            spacing = 0.0
        prop = prop_store.get_prop(pid)
        # WHICH of the prop's model variants each copy shows (E2.3): the
        # copies of one scatter source walk the active variants in the fixed
        # order `(scatter_seed + instance) mod count`, so twenty pines are
        # four kinds of pine in the same arrangement for every renderer — and
        # the same arrangement again after a reload, since both inputs are
        # stored numbers.
        variant_count = len(prop.get("variant_tiers") or []) if prop else 0
        for i, placed in enumerate(_scatter_props(seed, count, keep_in,
                                                  keepouts, spacing)):
            entry: Dict[str, Any] = {
                "prop_id": pid,
                "at": [_r(placed["at"][0]), _r(placed["at"][1])],
                "yaw": _r(placed["yaw"], 1),
                "offset_y": 0.0,
                "scattered": True,
            }
            if not prop:
                entry["missing"] = True
            else:
                # WHICH variant this copy shows decides HOW BIG it is: the
                # index is resolved first, and the dims are read off that very
                # entry (2026-08-24). A wood of one prop can therefore be
                # saplings and grown trees, not one tree in two textures.
                if prop.get("has_model"):
                    entry["variant"] = prop_store.scatter_variant_index(
                        seed, i, variant_count)
                entry["dims"] = _placement_dims(prop, entry.get("variant"))
                # A scattered copy is the SAME mesh as the variant it shows, so
                # it sinks by that variant's amount — the offset belongs to the
                # object version, not to the placement.
                _carry_ground_offset(entry, prop, entry.get("variant"))
                entry["has_model"] = bool(prop.get("has_model"))
                if prop.get("has_model"):
                    entry["model_tiers"] = prop.get("model_tiers") or []
                    entry["variant_tiers"] = prop.get("variant_tiers") or []
                    entry["model_sig"] = prop.get("model_signature") or ""
            placements.append(entry)


def boundary_points(map3d: Any) -> List[List[float]]:
    """The DRAWN location boundary in local metres, or [] — the ground's
    frame and its scatter keep-in (§ A13a).

    Deliberately no synthesized square: without a drawn boundary a location
    has no area (contract v6 Nr. 1), and the yard is that area.
    """
    from app.core.world_geometry import polygon_points
    pts = polygon_points((map3d or {}).get("boundary"))
    return [] if pts is None else [[float(x), float(z)] for x, z in pts]


def compose_ground_recipe(room: Dict[str, Any], siblings: Any = (),
                          map3d: Any = None, variant_seed: int = 0,
                          ) -> Optional[Dict[str, Any]]:
    """The REDUCED recipe of the ground room (§ A13a), or None when the yard
    carries nothing.

    The ground has no geometry: no rect, no hull, no openings, no plate, no
    walls. What it has is placements and markers, and their ``at`` is a
    LOCATION-LOCAL metre already — so the payload frame and the storage frame
    are the same one and nothing is translated (``ox = oy = 0``).

    ``outline`` stays empty ON PURPOSE: it is what keeps the ground out of
    every plate, wall, room block and boundary check downstream, which all
    read the hull. ``is_ground`` is the positive marker for the two places
    that must treat it specially (the prop/marker plate offset and the relief
    membership).

    Scatter keeps INSIDE the drawn boundary and outside: the hulls of the
    rooms standing on level 0, the entry zones of the boundary openings (the
    yard's doorways) and the ground's own markers.
    """
    lay = room.get("layout")
    if not isinstance(lay, dict) or not (lay.get("props") or lay.get("markers")):
        return None
    boundary = boundary_points(map3d)
    placements, prop_markers = _join_placements(
        lay, lambda u, v: (u, v), 0.0, 0.0, 0.0)

    scatter_sources = [p for p in (lay.get("props") or [])
                       if isinstance(p, dict) and p.get("scatter_count")]
    if scatter_sources and len(boundary) >= 3:
        keepouts: List[List[List[float]]] = []
        for sibling in (siblings or []):
            slay = sibling.get("layout") if isinstance(sibling, dict) else None
            if not isinstance(slay, dict) or int(slay.get("level") or 0) != 0:
                continue
            shape = _abs_shape(slay)
            if len(shape) >= 3:
                keepouts.append(shape)
        for op in ((map3d or {}).get("boundary_openings") or []):
            if not isinstance(op, dict):
                continue
            try:
                e = int(op.get("edge") or 0) % len(boundary)
                at = float(op.get("at") or 0)
                half = float(op.get("width_m") or 0) / 2.0 \
                    + SCATTER_OPENING_CLEAR_M
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            px, py = _point_on_edge(boundary, e, at)
            keepouts.append(_square(px, py, half))
        for marker in (lay.get("markers") or []):
            mat = marker.get("at") if isinstance(marker, dict) else None
            if isinstance(mat, (list, tuple)) and len(mat) == 2:
                keepouts.append(_square(float(mat[0]), float(mat[1]),
                                        SCATTER_POINT_CLEAR_M))
        _scatter_into(placements, scatter_sources, boundary, keepouts,
                      variant_seed)

    payload: Dict[str, Any] = {
        "room_id": room.get("id") or "",
        "level": 0,
        "is_ground": True,
        "outline": [],
        "openings": [],
        "placements": placements,
        "prop_markers": prop_markers,
    }
    if lay.get("markers"):
        payload["markers"] = lay["markers"]
    payload["signature"] = hashlib.md5(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def compose_recipe(room: Dict[str, Any],
                   siblings: Any = (),
                   variant_seed: int = 0,
                   map3d: Any = None) -> Optional[Dict[str, Any]]:
    """The full recipe of ONE room, or None when it has no layout.

    ``siblings`` are the OTHER rooms of the same location; those on the same
    level contribute their openings on shared walls (see
    ``_mirrored_openings``).
    ``variant_seed`` is the one number a copy placed on the map owns; it is
    mixed into every stored scatter seed so two copies of one template stop
    looking identical. 0 means "not a copy" and leaves every seed untouched.
    ``map3d`` is the location's map data; the GROUND room needs it, because
    its frame and its scatter area are the drawn boundary (§ A13a). Every
    other room ignores it.
    """
    from app.models.world import GROUND_ROOM_ID
    if str(room.get("id") or "") == GROUND_ROOM_ID:
        return compose_ground_recipe(room, siblings, map3d, variant_seed)
    lay = room.get("layout")
    rect = _layout_rect(lay)
    if not rect:
        return None
    x, y, w, d = rect

    pts = lay.get("outline")
    if not isinstance(pts, list) or len(pts) < 3:
        pts = _rect_outline(w, d)
    # Curved edges (plan-area-detail-scenes.md) are tessellated HERE — the
    # payload outline is always a plain polygon, downstream (walls, plates,
    # clips, both renderers) never learns curves existed. ``edge_map`` shifts
    # opening edge indices past the inserted points; on a curve-free outline
    # it is the identity.
    tess_pts, edge_map = tessellate(pts, lay.get("outline_curves"))
    # ONE transform for the whole room (contract v6 addendum): min corner plus
    # the room's own turn about its rect centre. The hull leaves here already
    # turned, so plates, walls, doorways, clips and the boundary check all see
    # the same rotated shape without knowing rotation exists.
    place = room_transform(lay)
    room_yaw = layout_rotation(lay)
    outline = [[_r(px), _r(py)]
               for px, py in (place(float(u), float(v)) for u, v in tess_pts)]

    own_id = str(room.get("id") or "")
    others = [s for s in (siblings or [])
              if isinstance(s, dict) and str(s.get("id") or "") != own_id]
    openings = [_normalize_opening(op) for op in (lay.get("openings") or [])
                if isinstance(op, dict)]
    openings.extend(_mirrored_openings(lay, others))
    if len(tess_pts) != len(pts):
        # Openings live on CONTROL-polygon edges (own ones and the mirrored
        # projections alike) — remap onto the tessellated indexing. Straight
        # edges map 1:1, so ``at`` stays valid; openings ON a curved edge
        # were already rejected by the sanitizer.
        for op in openings:
            try:
                e = int(op.get("edge") or 0)
            except (TypeError, ValueError):
                continue
            if 0 <= e < len(edge_map):
                op["edge"] = edge_map[e]

    placements, prop_markers = _join_placements(lay, place, room_yaw,
                                                w / 2, d / 2)

    scatter_sources = [p for p in (lay.get("props") or [])
                       if isinstance(p, dict) and p.get("scatter_count")]
    if scatter_sources:
        level = int(lay.get("level") or 0)
        keepouts: List[List[List[float]]] = []
        # Sibling hulls on the same level — the road stays tree-free. Curved
        # siblings contribute their TESSELLATED shape (the curved road is
        # exactly the case this exists for).
        for sibling in others:
            slay = sibling.get("layout")
            if not isinstance(slay, dict) \
                    or int(slay.get("level") or 0) != level:
                continue
            shape = _abs_shape(slay)
            if len(shape) >= 3:
                keepouts.append(shape)
        for op in openings:
            try:
                e = int(op.get("edge") or 0) % len(outline)
                at = float(op.get("at") or 0)
                half = float(op.get("width_m") or 0) / 2.0 \
                    + SCATTER_OPENING_CLEAR_M
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            px, py = _point_on_edge(outline, e, at)
            keepouts.append(_square(px, py, half))
        for marker in (lay.get("markers") or []):
            mat = marker.get("at") if isinstance(marker, dict) else None
            if isinstance(mat, (list, tuple)) and len(mat) == 2:
                mx, my = place(float(mat[0]), float(mat[1]))
                keepouts.append(_square(mx, my, SCATTER_POINT_CLEAR_M))
        _scatter_into(placements, scatter_sources, outline, keepouts,
                      variant_seed)

    payload: Dict[str, Any] = {
        "room_id": room.get("id") or "",
        "level": int(lay.get("level") or 0),
        "outline": outline,
        "openings": openings,
        "placements": placements,
        "prop_markers": prop_markers,
    }
    if lay.get("surfaces"):
        payload["surfaces"] = lay["surfaces"]
    if lay.get("markers"):
        payload["markers"] = lay["markers"]
    # Outdoor rooms (terraces, gardens): the client builds NO shell walls
    # for them — floor plate only (openings act via the mirror in the
    # neighbours' walls). Same flag as the visibility rule (AV3D-12).
    if lay.get("always_visible"):
        payload["always_visible"] = True
    # Diorama clipping (§ B1): the scene composer reads the opt-in from HERE,
    # not from the layout — that keeps the flag inside the signature below, so
    # toggling the checkbox makes the client re-fetch.
    if lay.get("clip_model"):
        payload["clip_model"] = True
    # THE FLOOR AS A LAYER OF THE GROUND ("Ein Boden" E5a): how wide this
    # floor's transition to the ground under it is. Carried into the recipe for
    # the SAME reason as clip_model: only payload fields reach the signature
    # below, so dialling it has to make the client re-fetch. ``relief_flat``
    # used to sit here and is gone with the scene's own relief (user decision
    # 1); the three WATER fields are gone with the zone-water carve (W1) — a
    # room has no water of its own any more, it only stands on some.
    if lay.get("edge_blend_m") is not None:
        payload["edge_blend_m"] = lay["edge_blend_m"]
    # No recipe walls for this room (open zone, pavilion). Read from the
    # recipe like clip_model, so the flag is inside the signature below and
    # toggling the checkbox makes the client re-fetch.
    if lay.get("no_walls"):
        payload["no_walls"] = True
    # Diorama anchor + height (2026-07-24 plan placement): SAME signature
    # reasoning — the composer reads them from the payload so that dragging
    # the ⌂ handle or the height slider moves the signature and the client
    # re-fetches (found as a hole during the M8 review: layout-only fields
    # never reached the hash).
    if lay.get("model_at") is not None:
        payload["model_at"] = lay["model_at"]
    if lay.get("model_offset_y") is not None:
        payload["model_offset_y"] = lay["model_offset_y"]
    # Where the room's FLOOR sits, in real metres relative to its storey —
    # same signature reasoning. Since "Ein Boden" (§ A16.9) this is a pure
    # FINE-TRIM dial of one room: it lifts what stands IN the room, it no
    # longer compensates a second ground, and it is not a waterline (a room has
    # no water since W1 — the painted AREA carries the mirror).
    if lay.get("floor_offset_y") is not None:
        payload["floor_offset_y"] = lay["floor_offset_y"]
    if lay.get("rotation") is not None:
        payload["rotation"] = lay["rotation"]
    # Change detection without polling the whole payload chain: the client
    # re-fetches when the signature moves (layout edits AND prop sidecar
    # edits both move it).
    payload["signature"] = hashlib.md5(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload
