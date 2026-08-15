"""Scene recipe (``shared/schnittstellen-3d.md`` part B) — the COMPLETE 3D
scene of one location as finished primitives.

⚠ Not to be confused with ``scene_photo.py`` (the rendered chat-scene image)
or with ``GET /play/scene`` (the chat perception of the avatar's room). This
module is pure GEOMETRY for the 3D map client and the Game-Admin floor-plan
preview.

Until v4 the same geometry rules lived three times — here, in the admin
preview (``FloorPlanPreview.tsx``) and in the 3D client. Every drift bug of
the last weeks came from that. From v4 on, **every geometry decision exists
exactly once: in this module**. The consumers own two generic routines only —
"build a primitive" and "place a model" — and no geometry decision of their
own.

What the composer emits (world coordinates throughout, ORIGIN = the tile
centre of the location, i.e. of its reference square — the consumer places
the scene at the location's map point):

- ``plates``  — one contour plate per used level plus one floor plate per room,
- ``walls``   — the building contour with its door gaps and the room shell
                walls already split around every opening (window = sill +
                head + glass segment),
- ``extras``  — the elevator primitives,
- ``style``   — the colours/opacities both renderers used to keep as copies,
- ``models``  — ONE spec form for building, room diorama and prop; the client
                runs the single ``place()`` routine of § B2 over it,
- ``figures``/``markers`` — the figure scale and every anchor point already
                resolved into world coordinates,
- ``terrain`` — the optional height field of a detail scene; the composer has
                already lifted every object standing on it, so the renderers
                only drape their ground and sample figure heights.

Numbers are NOT free here: every constant below is quoted from the contract
(``docs/schnittstellen-3d.md``, § A2/A3/A6 for the values, part B for the
payload shape) — that document, not this file, is where a value is changed.
When code and contract disagree, the CONTRACT wins.

The composer is pure: location dict + rooms in, primitives out. Loading
(world DB, model sidecars, scale anchor) is the route's job; the prop library
is read through ``room_recipe`` exactly as the room recipe does it.
"""

import math
from typing import (Any, Callable, Dict, Iterator, List, Optional, Set,
                    Tuple)

from app.core.log import get_logger
from app.core.model_store import DEFAULT_TIER, variant_urls
from app.core.room_recipe import (SHARE_TOL_M, _WALKABLE_TYPES,
                                  compose_recipe)
from app.core.scatter_curves import (relief_cells, terrain_grid,
                                     terrain_height, variant_mix)

logger = get_logger(__name__)

# ── Contract constants (§ A2/A3/A6) ─────────────────────────────────────
# The REFERENCE SQUARE is the frame every plan fraction lives in AND the box
# the location model fills. ONE frame (2026-07-28): plan edge == model edge,
# so the floor plan can always reach the model.
# Since E4 (2026-08-09) it is the location's FOOTPRINT: its edge length IS
# ``map3d.plan_width_m``, the same square the world map places (§ A1.1), and
# one world metre IS one real metre everywhere (k = 1). ``map3d.extent_m``
# was the world-metre dial of the tile era and is not read any more.
# The fallback edge for a location without a scale anchor.
DEFAULT_EXTENT_M = 10.0
# Storey height in metres when the location does not declare one.
DEFAULT_STOREY_REAL_M = 3.0
# Level plate: extruded downward, top at level × storey + 0.08, 0.14 thick.
LEVEL_PLATE_TOP = 0.08
LEVEL_PLATE_THICKNESS = 0.14
# Room floor plate: sits ABOVE the level plate (it overrides only its own
# area) — its top must clear the level plate's 0.08 top or it is buried
# under it (the old preview's 0.04 was exactly that drift; the client's
# 0.10 was the consistent value). The body is deliberately thin —
# thickness 0 is RESERVED for "texture only, no geometry" (§ A5).
ROOM_PLATE_TOP = 0.10
ROOM_PLATE_THICKNESS = 0.02
# Props stand ON the room plate, not on the abstract storey floor: bottom
# = plate top + this clearance (+ offset_y). Outdoor rooms have no
# plate — there the clearance sits on the storey/terrain level directly.
PROP_CLEARANCE = 0.01
# How far BELOW a marked surface a figure's root goes, as a fraction of the
# figure's height. A marker says where the SURFACE is — the seat of a bench,
# the mattress. WHERE the body touches that surface is a property of the CLIP,
# not of the marker, and it is nowhere near the feet:
#
#   clip      hips     lowest bone   what touches
#   sit       0.344    0.000 (toes)  the buttocks, just under the hip joint
#   sleep     0.660    0.604         the back — this clip lies on a BED, so the
#                                    whole body sits 0.6 x H above the root
#   laying    0.081   -0.004         the back, at ground level
#
# (measured on x-bot.fbx + the clips). ONE rule for all of them: the contact
# is the hips bone minus 0.03 x H — the same rule the prop viewer applies
# live, where it reads the hips off the POSED skeleton instead of a table.
# The viewer is the authority when a clip changes; these numbers are for
# everyone who has no clip loaded. A kind that is absent touches at its root
# and drops by nothing (standing, walking, working poses).
FIGURE_ROOT_DROP = {"sit": 0.314, "sleep": 0.631, "laying": 0.051,
                    "lie": 0.051}
# Diorama clipping (§ B1): the shell polygon a room model may be cut against
# is capped — the shader test runs per fragment, more points than this are not
# worth the frame time, so the opt-in is ignored instead. Raised 32 → 64 for
# tessellated curved hulls (plan-area-detail-scenes.md): a hull with a few
# bends lands at 8 segments per curve and blew the old cap.
CLIP_OUTLINE_MAX_POINTS = 64
# Area locations (plan-area-locations.md): how many holes may be cut out of a
# location model and how many points each may have. Same per-polygon cap as
# the room clip — the shader that applies them is its inverted twin.
CUTOUT_MAX_POLYS = 16
CUTOUT_MAX_POINTS = CLIP_OUTLINE_MAX_POINTS
# Walls: height max(0.6, storey − 0.15), thickness 0.07; glass panes thinner.
WALL_THICKNESS = 0.07
WALL_MIN_HEIGHT = 0.6
WALL_HEAD_ROOM = 0.15
GLASS_THICKNESS_FACTOR = 0.6
# Two wall faces count as ONE wall line when their directions are (anti)parallel
# within ~1° — the same slack ``room_recipe._mirrored_openings`` uses.
_WALL_PARALLEL = 0.98
# Contour wall pieces below 0.06 m are dropped (the gap a door leaves is the
# door's own clear width — there is no constant for it any more, § 4.2).
MIN_WALL_PIECE_M = 0.06
# Anything shorter/lower than this is not worth a primitive.
MIN_SEGMENT_M = 0.02
# Elevator (§ A6) — metres.
ELEVATOR_SHAFT_M = 1.8
ELEVATOR_COLUMN_M = 0.14
ELEVATOR_PAD_M = 1.6
ELEVATOR_CABIN_M = 1.4
ELEVATOR_CABIN_STOREY_FRAC = 0.6
ELEVATOR_ROOF_THICKNESS = 0.05
ELEVATOR_PAD_THICKNESS = 0.05
ELEVATOR_GLASS_THICKNESS = 0.03
# A building SHELL stands on the ground at this clearance. A GROUND model
# (an area location: the model IS the terrain) is anchored at its walkable
# surface instead and has no socle — see ``_building_model``.
BUILDING_BOTTOM_Y = 0.06
# Figures (§ A3): 1.70 m in world metres; the clearance is a constant too.
FIGURE_HEIGHT_M = 1.70
STAND_CLEARANCE = 0.12
# A room diorama stands this far above the floor it rests on — the ROOM
# PLATE indoors, the bare storey floor outdoors. The contract's familiar
# 0.12 is this clearance plus the plate top (0.10 + 0.02); an outdoor room
# has no plate (§ A5), so quoting 0.12 there floated it 10 cm above the
# ground while the PROPS in the same room already sat correctly on it
# (user finding 2026-07-28, Mondscheinsee).
DIORAMA_CLEARANCE = 0.02
# An overlay zone that declares a floor kind gets its texture surface this far
# above the model — coplanar with the mesh it would z-fight.
OVERLAY_SURFACE_LIFT = 0.01
# The floor kind of a level plate without its own entry in map3d.level_floors.
DEFAULT_FLOOR_KIND = "floor"

# The renderers' colour vocabulary — ONE place for both of them (§ B1 style).
# Editor-only overlay colours (markers, ruler) are deliberately NOT here:
# they are preview aids, not contract geometry. The elevator IS contract
# geometry (extras), so its colours are.
STYLE: Dict[str, Any] = {
    "wall_color": "#cfc4b2",
    "floor_color": "#d8d0c2",
    "glass_color": "#9fc2d8",
    "glass_opacity": 0.25,
    "upper_wall_opacity": 0.45,
    "upper_floor_opacity": 0.4,
    "room_palette": ["#58a6ff", "#3fb950", "#d29922", "#f778ba",
                     "#a371f7", "#f85149", "#79c0ff", "#56d364"],
    "elevator_frame_color": "#6d7681",
    "elevator_pad_color": "#aab4be",
    "elevator_cabin_color": "#3d4650",
    "elevator_cabin_opacity": 0.85,
    "elevator_glass_opacity": 0.22,
}


def _r(v: float, nd: int = 4) -> float:
    out = round(float(v), nd)
    return out if out != 0 else 0.0  # never -0.0 in payloads


def _w(frac: Any, extent: float) -> float:
    """Reference-square fraction → world metre (origin = the square's
    centre)."""
    try:
        return (float(frac) - 0.5) * extent
    except (TypeError, ValueError):
        return 0.0


def _room_outline_world(recipe: Dict[str, Any],
                        extent: float) -> List[List[float]]:
    """The room shell in world metres — the ONE source for the room's floor
    plate and for a diorama's ``clip_outline`` (§ B1); [] when degenerate."""
    pts = [[_r(_w(p[0], extent)), _r(_w(p[1], extent))]
           for p in recipe.get("outline") or []]
    return pts if len(pts) >= 3 else []


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opacity_role(level: int, ground_level: int) -> str:
    """The LOWEST used storey is opaque, every level above is ghosted (§ A6).

    The camera looks from above, so opacity must open the view down to the
    bottom-most storey — with a basement (level -1) the terrain-level floor
    ghosts too, otherwise the basement sits invisibly under an opaque plate.
    """
    return "ground" if level == ground_level else "upper"


def derive_scalars(map3d: Dict[str, Any],
                   plan_width_m: float) -> Tuple[float, float, float]:
    """(extent_m, k, storey_m) — the three scalars everything derives from.

    **k = 1 since E4** (2026-08-09). The reference square IS the location's
    footprint, so its world edge ``extent_m`` is ``plan_width_m`` itself and
    one world metre is one real metre — inside the scene exactly as on the
    map (§ A1.1). ``map3d.extent_m``, the world-metre dial of the tile era,
    is not read any more (the field may still sit in old blobs; nothing
    reads it, and the sanitizer drops it on the next save).

    Without a scale anchor (no ``plan_width_m``) the location has no real
    size to be; it falls back to ``DEFAULT_EXTENT_M`` so a plan without an
    anchor still composes.

    ``storey_m`` = the declared storey height in metres — one dial in the
    same unit as everything else, replacing the old pair ``height_m /
    floors`` (real) and ``level_height`` (world).

    ``k`` stays in the tuple AND in the payload: consumers (floor-plan
    preview, model panels, both renderers) read it as "world metres per real
    metre" and multiplying by the constant 1 is exactly right for them.
    """
    extent = _num(plan_width_m)
    if extent <= 0:
        extent = DEFAULT_EXTENT_M
    storey = (_num((map3d or {}).get("storey_height_m"))
              or DEFAULT_STOREY_REAL_M)
    return extent, 1.0, storey


def _used_levels(recipes: List[Dict[str, Any]]) -> List[int]:
    """The levels the layout rooms occupy, ascending; [0] when there are
    none (a location may be nothing but a contour)."""
    levels = sorted({int(r.get("level") or 0) for r in recipes})
    return levels or [0]


def _outline_world(map3d: Dict[str, Any], extent: float) -> List[List[float]]:
    """``map3d.outline`` in world metres, or [] when there is no polygon."""
    pts = (map3d or {}).get("outline")
    if not isinstance(pts, list) or len(pts) < 3:
        return []
    out: List[List[float]] = []
    for pt in pts:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return []
        out.append([_r(_w(pt[0], extent)), _r(_w(pt[1], extent))])
    return out


def _point_in_polygon(x: float, z: float, poly: List[List[float]]) -> bool:
    """Parity (ray-casting) test in the XZ plane — the same rule the renderers'
    clip shader applies per fragment, so "inside" means the same thing on both
    sides."""
    inside = False
    n = len(poly)
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[(i + 1) % n]
        if (az > z) != (bz > z):
            t = (z - az) / ((bz - az) or 1e-12)
            if x < ax + t * (bx - ax):
                inside = not inside
    return inside


def _bbox_inside(outline: List[List[float]],
                 contour: List[List[float]]) -> bool:
    """Does an outline lie fully inside the building contour?

    The BBox is enough (plan decision): all four corners inside means the room
    sits within the floor plan and behaves exactly as it does today. Without a
    contour nothing can be "inside", so every placed room counts as outside.
    """
    if not outline or len(contour) < 3:
        return False
    xs = [p[0] for p in outline]
    zs = [p[1] for p in outline]
    corners = ((min(xs), min(zs)), (max(xs), min(zs)),
               (max(xs), max(zs)), (min(xs), max(zs)))
    return all(_point_in_polygon(x, z, contour) for x, z in corners)


def _room_floor_y(recipe: Dict[str, Any], storey: float) -> float:
    """The height the room's FLOOR sits at: its storey plus the room's own
    offset (``layout.floor_offset_y``, metres).

    Inside a building the offset is 0 and this is just the storey. It matters
    where a room cuts a hole into a LOCATION model: terrain is not flat, so a
    hut on the slope needs its floor where the ground actually is — otherwise
    it floats over or sinks into the hole it made (user finding 2026-07-28).
    Everything in the room derives from here, so plate, walls, props, markers
    and diorama move as one.
    """
    return (int(recipe.get("level") or 0) * storey
            + _num(recipe.get("floor_offset_y")))


def _room_rect(recipe: Dict[str, Any], room: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """The room's placed rectangle (x, y, w, d) in plate fractions."""
    lay = room.get("layout") or {}
    return (_num(lay.get("x")), _num(lay.get("y")),
            _num(lay.get("w"), 1.0), _num(lay.get("d"), 1.0))


def room_size_m(location: Dict[str, Any],
                room: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """A room's rectangle in REAL METRES ``(w_m, d_m)``, or None when it has
    no layout or the location has no scale anchor.

    The scale rule lives HERE, in the one module that owns geometry (§ A1):
    a layout side is a fraction of the reference square, so its real size is
    that fraction times the plan width. Consumers outside the 3D path (the
    image-prompt composer wants the footprint in metres) call this instead
    of re-deriving the rule.
    """
    lay = (room or {}).get("layout") or {}
    w, d = _num(lay.get("w")), _num(lay.get("d"))
    if w <= 0 or d <= 0:
        return None
    from app.core.location_model3d import derive_plan_width_m
    plan_w = derive_plan_width_m(str((location or {}).get("id") or ""),
                                 (location or {}).get("map3d"))
    if plan_w <= 0:
        return None
    return (round(w * plan_w, 2), round(d * plan_w, 2))


# ── Plates ──────────────────────────────────────────────────────────────

def level_plate_kind(level: int, level_floors: Any, ground_kind: str) -> str:
    """The texture kind ONE storey plate carries (plan-grundflaeche.md § 5).

    Three words in a fixed order:

    1. ``map3d.level_floors["<level>"]`` — the author naming this storey's
       floor outright. It always wins, on every storey.
    2. ``ground_kind`` on storey 0 — the ground OUTSIDE, resolved from the
       location's ``terrain`` against the surface library. Storey 0 is the
       terrain storey by definition, so this applies there and nowhere else:
       a first-storey plank floor is not terrain, and a cellar is none either.
    3. ``DEFAULT_FLOOR_KIND`` otherwise.

    Room plates lie ON TOP of the level plate and keep overriding their own
    area with their own ``surfaces.floor`` — untouched by this.
    """
    if isinstance(level_floors, dict):
        declared = str(level_floors.get(str(level)) or "").strip()
        if declared:
            return declared
    if level == 0 and ground_kind:
        return ground_kind
    return DEFAULT_FLOOR_KIND


def _plates(map3d: Dict[str, Any], recipes: List[Dict[str, Any]],
            levels: List[int], storey: float, extent: float,
            relief_rooms: Optional[Set[str]] = None,
            ground_kind: str = "") -> List[Dict[str, Any]]:
    """One contour plate per used level + one floor plate per room.

    The level plate carries the storey's floor kind (``level_plate_kind``);
    the rooms lay their own plates ON TOP, so a room floor overrides only its
    own area. Outdoor rooms (§ A5) get NO body — they appear as a plate of
    thickness 0, i.e. a pure texture surface on the ground below.

    ``relief_rooms`` are the room ids whose ground follows the terrain field
    (v5.2 Nr. 14): their plate gets ``relief: true``, which is the renderers'
    ONLY instruction to subdivide it and raise its vertices. Level plates and
    every other room plate stay exactly as flat as before.
    """
    plates: List[Dict[str, Any]] = []
    contour = _outline_world(map3d, extent)
    level_floors = (map3d or {}).get("level_floors") or {}
    ground = min(levels)
    if contour:
        for level in levels:
            plates.append({
                "level": level,
                "outline": contour,
                "top_y": _r(level * storey + LEVEL_PLATE_TOP),
                "thickness": LEVEL_PLATE_THICKNESS,
                "texture_kind": level_plate_kind(level, level_floors,
                                                 ground_kind),
                "opacity_role": _opacity_role(level, ground),
            })
    for recipe in recipes:
        level = int(recipe.get("level") or 0)
        outdoor = bool(recipe.get("always_visible"))
        outline = _room_outline_world(recipe, extent)
        if not outline:
            continue
        entry: Dict[str, Any] = {
            "level": level,
            "outline": outline,
            "top_y": _r(_room_floor_y(recipe, storey)
                        + (0.0 if outdoor else ROOM_PLATE_TOP)),
            "thickness": 0.0 if outdoor else ROOM_PLATE_THICKNESS,
            "opacity_role": _opacity_role(level, ground),
            "room_id": recipe.get("room_id") or "",
        }
        kind = str(((recipe.get("surfaces") or {}).get("floor")) or "").strip()
        if kind:
            entry["texture_kind"] = kind
        if relief_rooms and entry["room_id"] in relief_rooms:
            entry["relief"] = True
        plates.append(entry)
    return plates


def _overlay_plates(recipes: List[Dict[str, Any]],
                    overlay_rooms: Dict[str, Dict[str, Any]],
                    ground: int, extent: float) -> List[Dict[str, Any]]:
    """Texture surfaces for outdoor zones that DECLARE a floor kind.

    An overlay zone lies on the model and normally gets no plate — a surface
    at storey height would cut straight through the terrain. But the zone
    knows its real height (the measured model surface plus the room's own
    offset), so a declared kind can be laid exactly there. That is what turns
    a drawn area into a lake: a room over the water, floor kind ``water``, and
    the material class does the rest. Without a declared kind nothing is
    emitted — the model's own baked texture stays visible, as before.
    """
    out: List[Dict[str, Any]] = []
    for recipe in recipes:
        room_id = str(recipe.get("room_id") or "")
        overlay = overlay_rooms.get(room_id)
        if not overlay:
            continue
        kind = str(((recipe.get("surfaces") or {}).get("floor")) or "").strip()
        if not kind:
            continue
        outline = _room_outline_world(recipe, extent)
        if not outline:
            continue
        level = int(recipe.get("level") or 0)
        out.append({
            "level": level,
            "outline": outline,
            "top_y": _r(_num(overlay.get("y")) + OVERLAY_SURFACE_LIFT),
            "thickness": 0.0,
            "texture_kind": kind,
            "opacity_role": _opacity_role(level, ground),
            "room_id": room_id,
        })
    return out


# ── Walls ───────────────────────────────────────────────────────────────

def _wall_height(storey: float) -> float:
    return max(WALL_MIN_HEIGHT, storey - WALL_HEAD_ROOM)


def _edge_frame(a: List[float], b: List[float]) -> Optional[Tuple[float, float, float]]:
    """(ux, uz, length) of the directed edge a→b; None when degenerate."""
    dx = b[0] - a[0]
    dz = b[1] - a[1]
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return None
    return (dx / length, dz / length, length)


def _subtract(spans: List[Tuple[float, float]],
              holes: List[Tuple[float, float]],
              min_len: float) -> List[Tuple[float, float]]:
    """Solid stretches = spans minus every hole, pieces below ``min_len``
    dropped. The ONE splitting routine — contour doors and room openings both
    run through it (no CSG anywhere)."""
    out = list(spans)
    for h0, h1 in holes:
        nxt: List[Tuple[float, float]] = []
        for s0, s1 in out:
            if h0 > s0:
                nxt.append((s0, min(s1, h0)))
            if h1 < s1:
                nxt.append((max(s0, h1), s1))
        out = nxt
    return [(s0, s1) for s0, s1 in out if s1 - s0 >= min_len]


def _segment_points(a: List[float], ux: float, uz: float,
                    s0: float, s1: float) -> Tuple[List[float], List[float]]:
    return ([_r(a[0] + ux * s0), _r(a[1] + uz * s0)],
            [_r(a[0] + ux * s1), _r(a[1] + uz * s1)])


# A room wall counts as sitting ON the contour when its edge is colinear
# within roughly a wall thickness (0.07 m) plus slack.
COLINEAR_TOL_M = 0.09


def _colinear_span(a: List[float], ux: float, uz: float, length: float,
                   pa: List[float], pb: List[float]) -> Optional[Tuple[float, float]]:
    """Span (t0, t1) that segment ``pa→pb`` covers on the directed edge
    starting at ``a`` with unit (ux, uz) — None when it is not colinear
    with the edge or the overlap is not worth a hole."""
    def proj(p: List[float]) -> Tuple[float, float]:
        t = (p[0] - a[0]) * ux + (p[1] - a[1]) * uz
        e = abs(-(p[0] - a[0]) * uz + (p[1] - a[1]) * ux)
        return t, e
    t0, e0 = proj(pa)
    t1, e1 = proj(pb)
    if max(e0, e1) > COLINEAR_TOL_M:
        return None
    lo, hi = sorted((t0, t1))
    lo = max(lo, 0.0)
    hi = min(hi, length)
    if hi - lo < MIN_WALL_PIECE_M:
        return None
    return (lo, hi)


def _contour_hit(pts: List[List[float]], at: List[float],
                 normal: List[float]) -> Optional[Tuple[int, float]]:
    """The nearest contour spot IN FRONT of a door — index of the contour edge
    the ray ``at + s·normal`` meets first and the position ``t`` of that hit
    along the edge. ``None`` when the ray meets no edge at all (a door drawn
    outside the floor plan).

    "In front of" is the door's own outward direction, not the shortest
    distance to the polygon: a door in a set-back room opens the hull ahead of
    itself, not on whatever wall happens to be nearest (§ 4.2, "Dome
    Morgenröte"). A door whose wall sits ON the contour line hits at s = 0;
    the colinear slack keeps the rounding of such a wall in front of it.
    """
    px, pz = at
    nx, nz = normal
    best: Optional[Tuple[int, float]] = None
    best_s = math.inf
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        frame = _edge_frame(a, b)
        if not frame:
            continue
        ux, uz, length = frame
        # at + s·n = a + t·u, solved by crossing the equation with u and n.
        den = nx * uz - nz * ux
        if abs(den) < 1e-9:
            continue            # the ray runs along this edge, it never meets
        rx, rz = a[0] - px, a[1] - pz
        s = (rx * uz - rz * ux) / den
        t = (rx * nz - rz * nx) / den
        if s < -COLINEAR_TOL_M or s >= best_s:
            continue
        if t < -1e-9 or t > length + 1e-9:
            continue
        best, best_s = (i, min(max(t, 0.0), length)), s
    return best


def _door_outward(entry: Dict[str, Any]) -> List[float]:
    """Unit normal of a doorway pointing AWAY from the room it was cut out of.

    ``along`` leaves two perpendiculars, and the room hull decides which one:
    it is wound CLOCKWISE by contract (the editor's ``planGeometry``: the
    interior lies to the RIGHT of every edge), so the outward side of the edge
    direction (ux, uz) is (uz, −ux) — the very number ``_room_walls`` puts on
    each wall piece as ``outward_normal``.

    No centre is measured for it. A room centroid answers a different question
    and gets it wrong on a concave hull: the vertex average of an L-shaped room
    lies in the cut-out corner, i.e. OUTSIDE the room, and would flip the
    normal of every door on the two walls facing that corner.
    """
    ux, uz = entry["along"]
    return [uz, -ux]


def _contour_walls(map3d: Dict[str, Any], levels: List[int], storey: float,
                   extent: float, doors: List[Dict[str, Any]],
                   room_hulls: Optional[Dict[int, List[List[List[float]]]]] = None,
                   ) -> List[Dict[str, Any]]:
    """The building contour as walls, per used level (§ A6).

    THE HULL TAKES ITS HOLE FROM THE DOOR (plan-betreten-und-tueren.md § 4.2):
    every outside doorway is projected forward onto the contour and opens it
    there, in the DOOR's clear width. ``doors`` carries one dict per outside
    doorway — ``level``, ``at`` (middle of the clear opening), ``normal`` (the
    door's outward unit normal) and ``width`` — all of it derived from the
    ``doorways`` block the payload itself ships, never a second time from the
    openings. The hole lands on the door's OWN storey: a hull opens where a
    door is, and a building without one stays shut and is reported instead
    (``_problems``). The old fallback — one 0.8 m door mid in the southernmost
    piece whenever no door projected close enough — is gone.

    The hole is the door's CLEAR width measured along the contour edge: a door
    meeting the hull at an angle keeps its own width there instead of being
    stretched, and one clamped against a corner loses the part that runs past
    the edge rather than wrapping onto the next one.

    ONE wall, one owner (finding 2026-07-27, "Haus von Kai": 27 colinear
    pairs, 16.5 m doubled → z-fighting the moment a wall texture landed on
    the room side): wherever an INDOOR room hull runs on the contour line,
    the contour piece yields — the room wall carries texture and openings, and
    its own wall gap IS the entrance there. ``room_hulls`` maps level → list of
    room outlines in world metres.

    ``map3d.wall_kind`` textures the whole shell: every emitted piece carries
    it as ``texture_kind``, the same field a room wall gets from its own
    ``surfaces.wall``. Without the field the contour stays untextured and the
    renderers fall back to ``style.wall_color``.
    """
    pts = _outline_world(map3d, extent)
    if len(pts) < 3:
        return []
    # Winding decides which side is outside (shoelace in the XZ plane).
    area2 = 0.0
    for i, (x1, z1) in enumerate(pts):
        x2, z2 = pts[(i + 1) % len(pts)]
        area2 += x1 * z2 - x2 * z1
    ccw = area2 > 0

    # (level, edge index) → the spans the doors of that storey cut out of it.
    cuts: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for door in doors:
        hit = _contour_hit(pts, door["at"], door["normal"])
        if not hit:
            continue
        i, t = hit
        half = _num(door.get("width")) / 2
        cuts.setdefault((int(door.get("level") or 0), i), []).append(
            (t - half, t + half))

    height = _wall_height(storey)
    wall_kind = str((map3d or {}).get("wall_kind") or "").strip()
    walls: List[Dict[str, Any]] = []
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        frame = _edge_frame(a, b)
        if not frame:
            continue
        ux, uz, length = frame
        nx = (uz if ccw else -uz)
        nz = (-ux if ccw else ux)
        for level in levels:
            lvl_holes = list(cuts.get((level, i), []))
            # Room-hull spans on this contour edge: colinear within roughly
            # a wall thickness → the room wall owns that stretch.
            for hull in (room_hulls or {}).get(level, []):
                for j, ha in enumerate(hull):
                    hb = hull[(j + 1) % len(hull)]
                    span = _colinear_span(a, ux, uz, length, ha, hb)
                    if span:
                        lvl_holes.append(span)
            segs = _subtract([(0.0, length)], sorted(lvl_holes),
                             MIN_WALL_PIECE_M)
            for s0, s1 in segs:
                start, end = _segment_points(a, ux, uz, s0, s1)
                entry: Dict[str, Any] = {
                    "level": level,
                    "from": start,
                    "to": end,
                    "base_y": _r(level * storey + LEVEL_PLATE_TOP),
                    "height": _r(height),
                    "thickness": WALL_THICKNESS,
                    "opacity_role": _opacity_role(level, min(levels)),
                    "outward_normal": [_r(nx), _r(nz)],
                }
                if wall_kind:
                    entry["texture_kind"] = wall_kind
                walls.append(entry)
    return walls


def _room_wall_edges(recipe: Dict[str, Any], extent: float
                     ) -> Iterator[Tuple[int, List[float], float, float,
                                         float, List[Tuple[float, float,
                                                           Dict[str, Any]]]]]:
    """Every edge of a room that HAS a shell, as
    ``(index, a, ux, uz, length, spans)`` in world metres — ``spans`` are the
    ``(s0, s1, opening)`` triples the openings cut out of that edge, sorted
    along it.

    The ONE place an opening becomes geometry: the wall splitter below
    subtracts these spans, and ``_doorways`` turns the walkable ones into
    threshold primitives. Neither derives the clamp a second time. A room
    without a shell (outdoor zone, ``no_walls``, degenerate hull) yields
    nothing — no wall is cut there, so there is no doorway there either.
    """
    if recipe.get("always_visible") or recipe.get("no_walls"):
        return
    outline = [[_w(p[0], extent), _w(p[1], extent)]
               for p in recipe.get("outline") or []]
    if len(outline) < 3:
        return
    for i, a in enumerate(outline):
        b = outline[(i + 1) % len(outline)]
        frame = _edge_frame(a, b)
        if not frame:
            continue
        ux, uz, length = frame
        spans: List[Tuple[float, float, Dict[str, Any]]] = []
        for op in recipe.get("openings") or []:
            try:
                if int(op.get("edge") or 0) != i:
                    continue
            except (TypeError, ValueError):
                continue
            half = min(_num(op.get("width_m")) / 2, length / 2)
            centre = min(max(_num(op.get("at")), 0.0), 1.0) * length
            spans.append((max(0.0, centre - half),
                          min(length, centre + half), op))
        spans.sort(key=lambda s: s[0])
        yield i, a, ux, uz, length, spans


def _room_walls(recipe: Dict[str, Any], storey: float,
                extent: float, ground_level: int) -> List[Dict[str, Any]]:
    """One room's shell walls, split around its openings (§ A4).

    Doors and passages leave a full-height gap; a window keeps a sill segment
    below and a head segment above and fills the hole with a glass segment.
    Mirrored openings (the neighbour's door in the shared wall) arrive
    pre-translated in the recipe and are treated exactly like own ones.
    Outdoor rooms have no shell at all (§ A5).

    ``no_walls`` is the per-room opt-out (open zone, pavilion, an area inside
    an area model): NOTHING is emitted — no segments, no window sill or head,
    no glass. Everything else about the room stays: its plate, its openings
    in the ``rooms`` block (the 2D editor keeps drawing them), its markers
    and its diorama. The BUILDING's contour walls are untouched.
    """
    level = int(recipe.get("level") or 0)
    # Room shell walls stand on the ROOM plate (0.10), the contour walls on
    # the level plate (0.08) — § A4/A6.
    base = _room_floor_y(recipe, storey) + ROOM_PLATE_TOP
    height = _wall_height(storey)
    kind = str(((recipe.get("surfaces") or {}).get("wall")) or "").strip()
    room_id = recipe.get("room_id") or ""
    role = _opacity_role(level, ground_level)
    walls: List[Dict[str, Any]] = []

    for _i, a, ux, uz, length, spans in _room_wall_edges(recipe, extent):
        # Clockwise hull → the outward normal of (ux, uz) is (uz, −ux).
        normal = [_r(uz), _r(-ux)]

        def _emit(s0: float, s1: float, y: float, h: float,
                  thickness: float, glass: bool = False) -> None:
            if s1 - s0 < MIN_SEGMENT_M or h < MIN_SEGMENT_M:
                return
            start, end = _segment_points(a, ux, uz, s0, s1)
            entry: Dict[str, Any] = {
                "level": level,
                "from": start,
                "to": end,
                "base_y": _r(base + y),
                "height": _r(h),
                "thickness": _r(thickness, 3),
                "opacity_role": role,
                "room_id": room_id,
                "outward_normal": normal,
            }
            if glass:
                entry["glass"] = True
            elif kind:
                entry["texture_kind"] = kind
            walls.append(entry)

        for s0, s1 in _subtract([(0.0, length)],
                                [(sp[0], sp[1]) for sp in spans],
                                MIN_SEGMENT_M):
            _emit(s0, s1, 0.0, height, WALL_THICKNESS)
        for s0, s1, op in spans:
            if str(op.get("type") or "").lower() != "window":
                continue
            sill = min(_num(op.get("sill_m")), height)
            top = min(_num(op.get("sill_m")) + _num(op.get("height_m")),
                      height)
            _emit(s0, s1, 0.0, sill, WALL_THICKNESS)
            _emit(s0, s1, top, height - top, WALL_THICKNESS)
            _emit(s0, s1, sill, top - sill,
                  WALL_THICKNESS * GLASS_THICKNESS_FACTOR, glass=True)
    return walls


# ── Doorways ────────────────────────────────────────────────────────────

def _doorways(recipes: List[Dict[str, Any]], storey: float,
              extent: float) -> List[Dict[str, Any]]:
    """Every walkable threshold of the location as a finished primitive
    (plan-betreten-und-tueren.md § 4.1).

    A doorway is EXACTLY the gap an opening cuts out of a wall — same source,
    same clamp (``_room_wall_edges``), no second derivation. Hence ``width_m``
    is the CLEAR width after the edge clamp, not the authored width for
    anyone to re-clamp, and ``base_y`` is the foot of the wall the gap
    belongs to. The consumer rule is: nothing is recalculated.

    ONE gap in the wall = ONE entry. Two candidates are the same hole when all
    three of ``_same_gap`` hold: same wall DIRECTION, the two wall faces no
    further apart than the mirror's own ``SHARE_TOL_M`` (plus the rounding a
    mirrored ``at`` carries — 4 decimals of a plate fraction), and clamped
    spans that actually meet on that line. Three cases run through it:

    * the neighbour's mirrored copy (``room_recipe._mirrored_openings``) — it
      contributes only its room id;
    * BOTH rooms of a party wall authoring their own door at the same spot;
    * the same door authored twice in one room.

    The widest span wins the geometry (the gap is the union of the overlapping
    spans) and with it the first place in ``rooms``: ``rooms[0]`` is always the
    room whose wall this entry was cut out of.

    ``outside`` is GEOMETRY, not authored text — see below. The GROUND room
    never appears in ``rooms``: it has no walls, and ``outside`` already says
    the door leads onto it.

    A window is no way out (``_WALKABLE_TYPES``), a room without a shell has
    no threshold, and the order is deterministic (level, position, rooms):
    consumers diff whole payloads.
    """
    from app.models.world import GROUND_ROOM_ID

    def _rooms_of(room_id: str, to: str) -> List[str]:
        out = [room_id]
        if to and to.lower() != "outside" and to != GROUND_ROOM_ID \
                and to != room_id:
            out.append(to)
        return out

    tol = SHARE_TOL_M + 1e-4 * extent
    # (entry, unclamped centre) of the openings on their OWN room's wall, and
    # the neighbours' mirrored copies. Own ones are deduped FIRST, so an entry
    # is based on a room that owns its wall stretch wherever one exists.
    owned: List[Tuple[Dict[str, Any], List[float]]] = []
    mirrored: List[Tuple[Dict[str, Any], List[float]]] = []
    for recipe in recipes:
        room_id = str(recipe.get("room_id") or "")
        level = int(recipe.get("level") or 0)
        # The wall's own foot — the same number _room_walls stands its
        # full-height pieces on (room plate, storey and level included).
        base = _r(_room_floor_y(recipe, storey) + ROOM_PLATE_TOP)
        for _i, a, ux, uz, length, spans in _room_wall_edges(recipe, extent):
            for s0, s1, op in spans:
                if str(op.get("type") or "door").lower() not in _WALKABLE_TYPES:
                    continue
                if s1 - s0 < MIN_SEGMENT_M:
                    continue  # a hole the splitter does not open is no way out
                to = str(op.get("to") or "").strip()
                entry = {
                    "level": level,
                    "at_world": [_r(a[0] + ux * (s0 + s1) / 2),
                                 _r(a[1] + uz * (s0 + s1) / 2)],
                    "along": [_r(ux), _r(uz)],
                    "width_m": _r(s1 - s0),
                    "base_y": base,
                    "rooms": _rooms_of(room_id, to),
                }
                # The CENTRE before the edge clamp: that point is identical on
                # both faces of a shared wall (up to the wall's own offset),
                # while the clamped middle moves in a corner.
                t = min(max(_num(op.get("at")), 0.0), 1.0) * length
                centre = [a[0] + ux * t, a[1] + uz * t]
                if op.get("mirrored"):
                    mirrored.append((entry, centre))
                else:
                    owned.append((entry, centre))

    def _same_gap(kept_entry: Dict[str, Any], kept_centre: List[float],
                  entry: Dict[str, Any], centre: List[float]) -> bool:
        """Are these two candidates the same hole in the same wall?

        Three questions, all of them geometric. The DIRECTION comes first: a
        door clamped into a corner has its unclamped centre exactly ON the
        corner, so two doors meeting there are zero metres apart while lying
        on two different walls — without this test the south threshold of an
        L-corner would be swallowed by the east one.
        """
        if kept_entry["level"] != entry["level"]:
            return False
        ux, uz = kept_entry["along"]
        vx, vz = entry["along"]
        # Same wall LINE: parallel or antiparallel within the slack the mirror
        # itself uses to call two faces one wall (~1°). Perpendicular walls
        # score 0 here and never meet again.
        if abs(ux * vx + uz * vz) < _WALL_PARALLEL:
            return False
        # ...and the two lines have to be the same line: the two faces of one
        # wall lie at most SHARE_TOL_M metres apart, which is exactly the
        # offset the mirror accepted.
        dx, dz = centre[0] - kept_centre[0], centre[1] - kept_centre[1]
        if abs(dx * uz - dz * ux) > tol:
            return False
        # ...and the CLAMPED spans have to MEET on that line. Two doors pushed
        # into the same corner from the two stretches of one straight line
        # share a point, not a gap — they stay two thresholds.
        t = ((entry["at_world"][0] - kept_entry["at_world"][0]) * ux
             + (entry["at_world"][1] - kept_entry["at_world"][1]) * uz)
        return (kept_entry["width_m"] + entry["width_m"]) / 2 - abs(t) > 1e-9

    kept: List[List[Any]] = []  # [entry, unclamped centre of its opening]
    for entry, centre in owned + mirrored:
        base: Optional[List[Any]] = None
        best_d = 0.0
        for pair in kept:
            if not _same_gap(pair[0], pair[1], entry, centre):
                continue
            d = math.hypot(pair[1][0] - centre[0], pair[1][1] - centre[1])
            # Ties keep the FIRST candidate — the room order of the payload.
            if base is None or d < best_d:
                base, best_d = pair, d
        if base is None:
            kept.append([entry, centre])
            continue
        base_entry = base[0]
        if entry["width_m"] > base_entry["width_m"] + 1e-9:
            # The gap is the union of the overlapping spans, so the wider
            # entry is the one that describes it — geometry, leading room and
            # the centre later candidates are measured against all move over.
            rooms = entry["rooms"] + [r for r in base_entry["rooms"]
                                      if r not in entry["rooms"]]
            base_entry.update(entry)
            base_entry["rooms"] = rooms
            base[1] = centre
        else:
            for room_id in entry["rooms"]:
                if room_id not in base_entry["rooms"]:
                    base_entry["rooms"].append(room_id)

    out = [entry for entry, _c in kept]
    for entry in out:
        # ``outside`` is decided HERE, on the finished geometry, and never on
        # what an author typed into ``to``: after the dedup a single room means
        # no second room's wall meets this gap, i.e. it opens out of the
        # building — onto the ground. A door someone left unlabelled is
        # therefore a proper exterior door, not a doorway to nowhere.
        entry["outside"] = len(entry["rooms"]) == 1
    out.sort(key=lambda e: (e["level"], e["at_world"], e["rooms"]))
    return out


def threshold_base_y(sides: List[Tuple[float, Optional[float]]]) -> float:
    """The height a threshold LIES AT: the standing height of the rooms it
    joins (finding 2026-08-16, floating thresholds).

    ``sides`` is one ``(wall_foot_y, declared_walk_y_world)`` pair per adjoining
    room, both in scene metres. A room whose diorama DECLARES its walkable
    surface (the admin's ``walk_y``, resolved to ``walk_y_world`` on the model
    spec) says where one stands in that room; without a declaration the foot of
    the wall the gap was cut from is the floor, exactly as before.

    Two rooms → the HIGHER standing height wins: one steps OVER a threshold,
    never into it. An outside door has ONE side, the room's — the ground side
    is what the boundary marks cover.

    A pure function on purpose: this rule is the whole computation, and the
    smoke feeds it the numbers of the finding directly instead of reading them
    back out of a payload.
    """
    if not sides:
        return 0.0
    return max(foot if walk is None else float(walk) for foot, walk in sides)


# ── Problems ────────────────────────────────────────────────────────────

def _problems(location: Dict[str, Any], map3d: Dict[str, Any], extent: float,
              shell_levels: Set[int], doorways: List[Dict[str, Any]],
              recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Findings instead of silent repairs (plan-betreten-und-tueren.md § 4.3).

    ``rooms_without_layout`` — the location has a contour, it has rooms, and
    not ONE of them composed a recipe (every layout is missing or degenerate).
    That is the quiet version of the sealed hull: without a recipe there is no
    shell either, so ``shell_levels`` stays empty and ``no_building_entrance``
    below can never speak up. The contour then stands over nothing at all.
    The GROUND room never counts — it has no layout by contract. The room
    COUNT rides along as its own field: ``message`` is looked up as a whole
    sentence by the i18n layer, so it must stay free of numbers.

    ``no_building_entrance`` — ALL of:

    * the location has a floor-plan contour, so there is a hull to be sealed;
    * at least one room WITH A SHELL stands on level 0 (``shell_levels``) —
      that is what makes the hull a building. A contour holding nothing but
      outdoor zones or ``no_walls`` rooms is not one: such a room cannot carry
      a door at all, so there would be nothing for the author to fix;
    * not ONE doorway on level 0 leads outside.

    Then nobody can get in, and since the "one door mid in the south wall"
    fallback is gone (§ 4.2) nothing hides it any more. The composer only
    states it; the floor-plan editor and the 3D client display it.

    ``openings_without_walls`` — at least one room carries openings in its
    layout while its walls are switched off (``no_walls``, or the outdoor
    ``always_visible``). ``_room_wall_edges`` yields nothing for such a room,
    so door, window, glass and threshold all silently cease to exist in 3D —
    while the 2D floor plan keeps drawing the very openings the author
    authored. A wall-less room WITHOUT openings is perfectly legal (open
    zone, pavilion) and stays quiet; only the combination is the trap. Fires
    once per location, with the number of affected rooms as its own field.
    """
    out: List[Dict[str, Any]] = []
    from app.models.world import GROUND_ROOM_ID
    has_contour = len(_outline_world(map3d, extent)) >= 3
    # The GROUND room is out: it is the location's open surface and NEVER
    # carries a layout (the sanitizer strips one), so counting it would blame
    # the author for a room that cannot be drawn.
    rooms = [r for r in (location.get("rooms") or [])
             if isinstance(r, dict) and str(r.get("id") or "") != GROUND_ROOM_ID]
    if has_contour and rooms and not recipes:
        out.append({
            "kind": "rooms_without_layout",
            "location_id": str(location.get("id") or ""),
            "room_count": len(rooms),
            "message": "No room of this location has a floor plan: the drawn "
                       "contour holds nothing that can be entered. Draw a "
                       "layout for at least one of its rooms.",
        })
    if (has_contour
            and 0 in shell_levels
            and not any(d.get("outside") and int(d.get("level") or 0) == 0
                        for d in doorways)):
        out.append({
            "kind": "no_building_entrance",
            "location_id": str(location.get("id") or ""),
            # The GROUND FLOOR is what the rule is about: a door on an upper
            # storey opens the hull up there and still leaves nobody a way in
            # from outside, so the wording must not claim there is no door.
            "message": "No outside door on the ground floor: this building "
                       "cannot be entered from outside. Draw a door leading "
                       "outside on one of its ground-floor rooms.",
        })
    # Openings drawn into a room whose walls are off: the recipe carries them,
    # but no wall is ever split there, so nothing of them is built.
    wall_less = [r for r in recipes
                 if (r.get("no_walls") or r.get("always_visible"))
                 and (r.get("openings") or [])]
    if wall_less:
        out.append({
            "kind": "openings_without_walls",
            "location_id": str(location.get("id") or ""),
            "room_count": len(wall_less),
            "message": "Rooms have doors or windows drawn, but their walls "
                       "are switched off — nothing of it is built in 3D. "
                       "Check 'Render walls' in the room layout.",
        })
    return out


# ── Extras (elevator) ───────────────────────────────────────────────────

def _box(kind: str, cx: float, cy: float, cz: float,
         w: float, h: float, d: float, **extra: Any) -> Dict[str, Any]:
    """ONE primitive form for the extras: an axis-aligned box by centre+size."""
    entry = {"kind": kind,
             "center": [_r(cx), _r(cy), _r(cz)],
             "size": [_r(w), _r(h), _r(d)]}
    entry.update(extra)
    return entry


def _elevator(map3d: Dict[str, Any], levels: List[int], storey: float,
              extent: float) -> List[Dict[str, Any]]:
    """The elevator of a building: shaft columns + roof, glass on three sides
    (the side facing the building centre stays open), a pad per level and a
    static cabin on the ground floor (§ A6). All sizes are metres — the
    legacy figure scale the caller used to hand in as k (storey / 3, the
    preview's kEl) is gone with E4: one metre is one metre.
    """
    pos = (map3d or {}).get("elevator")
    if not isinstance(pos, (list, tuple)) or len(pos) != 2:
        return []
    ex, ez = _w(pos[0], extent), _w(pos[1], extent)
    top_level = max([0] + list(levels))
    shaft_top = (top_level + 1) * storey + LEVEL_PLATE_TOP
    outer = ELEVATOR_SHAFT_M
    column = max(ELEVATOR_COLUMN_M, 0.05)

    out: List[Dict[str, Any]] = []
    for sx in (-1, 1):
        for sz in (-1, 1):
            out.append(_box("elevator_shaft",
                            ex + sx * (outer - column) / 2, shaft_top / 2,
                            ez + sz * (outer - column) / 2,
                            column, shaft_top, column))
    out.append(_box("elevator_shaft", ex, shaft_top + ELEVATOR_ROOF_THICKNESS / 2,
                    ez, outer, ELEVATOR_ROOF_THICKNESS, outer))
    # Open side = the dominant axis of the elevator's offset, pointing at the
    # building centre; the other three sides are glazed.
    if abs(ex) >= abs(ez):
        open_side = "west" if ex > 0 else "east"
    else:
        open_side = "north" if ez > 0 else "south"
    sides = (
        ("north", ex, ez - outer / 2, outer, ELEVATOR_GLASS_THICKNESS),
        ("south", ex, ez + outer / 2, outer, ELEVATOR_GLASS_THICKNESS),
        ("west", ex - outer / 2, ez, ELEVATOR_GLASS_THICKNESS, outer),
        ("east", ex + outer / 2, ez, ELEVATOR_GLASS_THICKNESS, outer),
    )
    for side, gx, gz, gw, gd in sides:
        if side == open_side:
            continue
        out.append(_box("elevator_glass", gx, shaft_top / 2, gz,
                        gw, shaft_top, gd, side=side))
    pad = ELEVATOR_PAD_M
    for level in levels:
        out.append(_box("elevator_pad", ex,
                        level * storey + LEVEL_PLATE_TOP - ELEVATOR_PAD_THICKNESS / 2,
                        ez, pad, ELEVATOR_PAD_THICKNESS, pad, level=level))
    cabin = ELEVATOR_CABIN_M
    cabin_h = max(ELEVATOR_CABIN_STOREY_FRAC * storey, 0.3)
    out.append(_box("elevator_cabin", ex, LEVEL_PLATE_TOP + cabin_h / 2, ez,
                    cabin, cabin_h, cabin, level=0))
    return out


# ── Placement specs (§ B2) ──────────────────────────────────────────────

def _fix_euler(rotation: Any) -> Dict[str, float]:
    """The orientation fix as a **'YXZ'** Euler in degrees (§ A1).

    Yaw (y) outermost, then tilt (x) and roll (z) in the already-turned frame,
    so "tip forward" means the same whichever way the model faces. The old
    'XYZ' let x act in world axes, which stopped matching the model's own axes
    after any y turn (user finding 2026-07-28). With a single non-zero axis —
    which is what a 90°-step fix normally is — both orders are identical.
    """
    rot = rotation if isinstance(rotation, dict) else {}
    return {axis: _r(_num(rot.get(axis)), 3) for axis in ("x", "y", "z")}


def _building_yaw(location: Dict[str, Any], map3d: Dict[str, Any]) -> float:
    """Yaw chain (§ A1): map3d.rotation (an explicit 0 counts) →
    map_rotation_2d → 0."""
    if (map3d or {}).get("rotation") is not None:
        return _num(map3d.get("rotation"))
    return _num(location.get("map_rotation_2d"))


def _variants(base_url: str, tiers: Any) -> Dict[str, str]:
    """``models[].variants`` (§ B1): one URL per resolution tier the subject
    HAS. A model that declares no tiers is a ``full`` one — that is what every
    model made before the tiers existed is. Consumers pick the tier they want
    and fall back to the best available one; an empty object means there is no
    mesh at all (then ``placeholder_dims`` carries the placement)."""
    names = [str(t) for t in (tiers or []) if t] or [DEFAULT_TIER]
    return variant_urls(base_url, names)


def _building_model(location: Dict[str, Any], map3d: Dict[str, Any],
                    meta: Dict[str, Any],
                    extent: float) -> Optional[Dict[str, Any]]:
    """The location model as a placement spec (§ A2/B2).

    ONE scale factor on all three axes (user decision 2026-07-28 — nothing is
    squashed in a single dimension any more): the model's largest YAWED XZ
    side becomes ``size × extent_m``, and the height follows its own
    proportions. A mesh with wrong proportions is not repaired here; that is
    a modelling problem the metre ruler makes visible.

    TWO anchor rules, because there are two kinds of model:

    - ``display "shell"`` — a building STANDS on the ground: the bottom edge
      goes to the socle clearance + ``offset_y``.
    - ``display "ground"`` — an area model IS the ground, so its WALKABLE
      SURFACE is not a free parameter: it lands on the LEVEL-0 FLOOR and the
      mesh hangs below it. ``offset_y`` does not apply; the only thing left
      to state is where the ground sits inside the mesh (``walk_y``, metres
      above the mesh's lower edge).
      Otherwise the two can drift apart — Willowbrook carried offset_y −0.75
      from the measurement era, so its village square (a level-0 room) sat
      at −0.75 while level 0 is at 0 and level −1 at −0.8475: the figures
      stood at basement height on a square that has no basement (user
      finding 2026-07-28). With the ground pinned to its level that is not
      expressible any more.

    Where the walkable surface SITS inside the mesh is the admin's ``walk_y``
    dial (metres above the lower edge, 0 = the lower edge itself) and
    nothing else. A measured "dominant horizontal layer" used to fill it in;
    that was an automatic repair of the kind this contract does not do — and
    it was wrong exactly where it mattered (Bernstein Academy: the campus
    roofs carry 0.38 of projected area against the ground's 0.67, so the
    heuristic declared the ROOFS walkable and sank the model 7.7 real metres).
    The user sets the base value, everything else derives from it.
    """
    if not meta:
        return None
    from urllib.parse import quote
    loc_id = str(location.get("id") or "")
    ground = bool((map3d or {}).get("area_model"))
    # Detail scene (plan-area-detail-scenes.md): the area model becomes a
    # FADING shell ("shell_area") — but it keeps the ground ANCHOR law below.
    # Only the display word changes; every number in the spec stays put, so
    # toggling the flag never moves the model.
    detail = ground and bool((map3d or {}).get("area_detail"))
    # A GROUND model fills its location — `size` is a building-on-a-plot dial
    # and would leave a rim of plan with no ground under it (user finding
    # 2026-07-28: size 0.92 put a 0.45 m gap between the model and the
    # reference square's edge line, on a location whose model IS the place).
    size = 1.0 if ground else (_num((map3d or {}).get("size"), 1.0) or 1.0)
    max_m = extent * size
    offset_y = _num(meta.get("offset_y"))
    walk = _num(meta.get("walk_y"))

    if ground:
        # Level-0 floor, by definition — the terrain storey IS this model.
        bottom = -walk
        walk_world = 0.0
    else:
        bottom = BUILDING_BOTTOM_Y + offset_y
        walk_world = bottom + walk
    return {
        "role": "building",
        "display": "shell_area" if detail else ("ground" if ground else "shell"),
        "id": loc_id,
        "variants": _variants(f"/play/locations/{quote(loc_id)}/model",
                              meta.get("tiers")),
        "level": 0,
        "fix_euler": _fix_euler(meta.get("rotation")),
        "yaw_deg": _r(_building_yaw(location, map3d), 1),
        # The frame is filled AFTER the yaw — a model turned 325° must still
        # fit its location, so the rotated footprint is what gets measured.
        "max_m": _r(max_m),
        "measure": "yawed_xz",
        "anchor": [_r(_num(meta.get("offset_x"))), _r(_num(meta.get("offset_z")))],
        "bottom_y": _r(bottom),
        "walk_y_world": _r(walk_world),
    }


def _diorama_model(recipe: Dict[str, Any], room: Dict[str, Any],
                   meta: Dict[str, Any], storey: float,
                   extent: float,
                   lift: Optional[Callable[[float, float], float]] = None,
                   ) -> Optional[Dict[str, Any]]:
    """A room's diorama model as a placement spec (§ B2a).

    ONE law of scale, no exception left (2026-07-28): the diorama scales like
    a prop — its declared width over its largest XZ side. The room
    RECTANGLE does not influence its size, it stays floor-plan area for
    plate, shell and walkability. The old rectangle fit (``fit_box``) is
    gone; a model without ``width_m`` falls back to the rectangle's real
    width and says so via ``width_estimated`` so the UI can ask for a
    calibration instead of silently scaling by a different law.

    Coexistence (user decision 2026-07-25): the diorama ALWAYS coexists with
    the recipe scene — it is treated like one more prop (placed via model_at,
    calibrated via width_m/walk_y), whether or not the room carries prop
    placements. A room without a diorama simply has no model.

    ``lift`` is the terrain sampler for a room that follows the relief
    (v5.2 Nr. 14) — rare for a diorama, but the rule is one rule: everything
    standing in a non-flat room is raised to the ground under its anchor.
    ``walk_y_world`` derives from ``bottom_y`` and rides along by itself.
    """
    if not meta:
        return None
    from urllib.parse import quote
    lay = room.get("layout") or {}
    room_id = str(room.get("id") or "")
    level = int(recipe.get("level") or 0)
    x, y, w, d = _room_rect(recipe, room)
    # Anchor + height come from the RECIPE payload, like clip_model: only
    # payload fields move the signature, and the client must re-fetch when
    # the admin drags the ⌂ handle or dials the height (M8-review hole).
    at = recipe.get("model_at")
    if not isinstance(at, (list, tuple)) or len(at) != 2:
        at = [0.5, 0.5]
    anchor_u = x + _num(at[0], 0.5) * w
    anchor_v = y + _num(at[1], 0.5) * d
    spec: Dict[str, Any] = {
        "role": "room",
        "id": room_id,
        "variants": _variants(f"/play/rooms/{quote(room_id)}/model",
                              meta.get("tiers")),
        "room_id": room_id,
        "level": level,
        "fix_euler": _fix_euler(meta.get("rotation")),
        "yaw_deg": _r(_num(lay.get("rotation")), 1),
        "anchor": [_r(_w(anchor_u, extent)), _r(_w(anchor_v, extent))],
        # Same floor the room's PROPS stand on: its plate indoors, the room
        # floor outdoors — plus the diorama clearance and the plan's dial.
        "bottom_y": _r(_room_floor_y(recipe, storey)
                       + (0.0 if recipe.get("always_visible") else ROOM_PLATE_TOP)
                       + DIORAMA_CLEARANCE
                       + _num(recipe.get("model_offset_y"))
                       + (lift(anchor_u, anchor_v) if lift else 0.0)),
        "measure": "xz",
    }
    width_m = _num(meta.get("width_m"))
    max_m = width_m
    if max_m <= 0:
        # Not calibrated yet: the room rectangle's own world width is the
        # honest stand-in — same number the old rectangle fit produced, but
        # now as a real size the admin can dial at the reference figure.
        max_m = max(w, d) * extent
        spec["width_estimated"] = True
    spec["max_m"] = _r(max_m)
    # Modelled floors (a podium, a sunken lounge, a hole in the mesh) make the
    # standing height unreadable from outside — so the admin states it, in
    # metres above the model's lower edge, dialled against the
    # calibration figure. No measurement fills this in: guessing where a mesh
    # is walkable is an automatic repair, and the contract does not do those.
    # Absent = the room keeps whatever floor the renderer samples.
    if meta.get("walk_y") is not None:
        spec["walk_y_world"] = _r(spec["bottom_y"] + _num(meta["walk_y"]))
    # Opt-in shell clip (§ B1): a diorama may stick out over its floor plan —
    # with the flag the renderer discards everything outside the room shell.
    # The polygon is the room's floor plate, not a second derivation. An
    # outdoor room has no shell to clip against (§ A5).
    if recipe.get("clip_model") and not recipe.get("always_visible"):
        clip = _room_outline_world(recipe, extent)
        if len(clip) > CLIP_OUTLINE_MAX_POINTS:
            logger.warning(
                "Room %s: clip_model ignored — outline has %d points (max %d)",
                room_id, len(clip), CLIP_OUTLINE_MAX_POINTS)
        elif clip:
            spec["clip_outline"] = clip
    return spec


def _cutouts(contour: List[List[float]],
             outside_indoor: List[Tuple[str, List[List[float]]]],
             ) -> List[List[List[float]]]:
    """The holes to cut out of an AREA location's model (plan-area-locations).

    Two sources, both already world metres and both the SAME point source the
    plates use — nothing is re-derived here: the building contour as a whole
    (inside it stands the ordinary recipe interior: storey plate, contour
    walls, rooms), plus the outline of every placed INDOOR room that does not
    sit fully inside that contour (the hut off to the side).

    Caps mirror the shader: at most ``CUTOUT_MAX_POINTS`` per polygon and
    ``CUTOUT_MAX_POLYS`` polygons. Anything over is dropped with a warning
    rather than silently truncated — a half-cut hole is worse than none.
    """
    polys: List[List[List[float]]] = []
    if contour:
        if len(contour) > CUTOUT_MAX_POINTS:
            logger.warning("Area location: outline has %d points (max %d) — "
                           "not cut out", len(contour), CUTOUT_MAX_POINTS)
        else:
            polys.append(contour)
    for room_id, outline in outside_indoor:
        if len(polys) >= CUTOUT_MAX_POLYS:
            logger.warning("Area location: more than %d cutouts — room %s and "
                           "any further ones are not cut out",
                           CUTOUT_MAX_POLYS, room_id)
            break
        if len(outline) > CUTOUT_MAX_POINTS:
            logger.warning("Room %s: outline has %d points (max %d) — not cut "
                           "out", room_id, len(outline), CUTOUT_MAX_POINTS)
            continue
        polys.append(outline)
    return polys


def _prop_models(recipe: Dict[str, Any], storey: float,
                 extent: float,
                 lift: Optional[Callable[[float, float], float]] = None,
                 ) -> List[Dict[str, Any]]:
    """The room's prop placements as specs (REAL-SIZE rule, § A2).

    A placement never scales its prop: the size comes from the prop's own
    dims. Dangling ids and props without a mesh keep their placement and
    carry ``placeholder_dims`` so the consumer can draw a box.
    Furniture stands ON the room plate (plate top + clearance); an outdoor
    room has no plate, so the clearance sits on the storey level directly.

    ``lift`` samples the terrain relief (v5.2 Nr. 14) under each placement —
    the height of a prop on a slope is NEVER set by hand (user rule): manual
    anchor and scattered copy alike get the ground under their own anchor
    added here. A flat room passes ``None`` and keeps every existing number.
    """
    from urllib.parse import quote
    from app.core import props as prop_store
    level = int(recipe.get("level") or 0)
    room_id = recipe.get("room_id") or ""
    plate_top = 0.0 if recipe.get("always_visible") else ROOM_PLATE_TOP
    floor_y = _room_floor_y(recipe, storey) + plate_top + PROP_CLEARANCE
    out: List[Dict[str, Any]] = []
    for placement in recipe.get("placements") or []:
        pid = str(placement.get("prop_id") or "")
        dims_raw = placement.get("dims") or {}
        dims = [_num(dims_raw.get("width_m"), 1.0), _num(dims_raw.get("depth_m"), 1.0),
                _num(dims_raw.get("height_m"), 1.0)]
        at = placement.get("at") or [0.5, 0.5]
        anchor_u = _num(at[0], 0.5)
        anchor_v = _num(at[1], 0.5)
        has_model = bool(placement.get("has_model"))
        prop = prop_store.get_prop(pid) if pid else None
        spec: Dict[str, Any] = {
            "role": "prop",
            "id": pid,
            "variants": (_variants(f"/assets/props/{quote(pid)}/model",
                                   placement.get("model_tiers"))
                         if has_model else {}),
            "room_id": room_id,
            "level": level,
            "fix_euler": _fix_euler((prop or {}).get("rotation")),
            "yaw_deg": _r(_num(placement.get("yaw")), 1),
            "max_m": _r(max(dims)),
            "measure": "xyz",
            "anchor": [_r(_w(anchor_u, extent)), _r(_w(anchor_v, extent))],
            "bottom_y": _r(floor_y + _num(placement.get("offset_y"))
                           + (lift(anchor_u, anchor_v) if lift else 0.0)),
        }
        if not has_model:
            spec["placeholder_dims"] = {"w": _r(dims[0]), "d": _r(dims[1]),
                                        "h": _r(dims[2])}
        out.append(spec)
    return out


# ── Markers, figures ────────────────────────────────────────────────────

def _markers(recipe: Dict[str, Any], room: Dict[str, Any], storey: float,
             extent: float,
             lift: Optional[Callable[[float, float], float]] = None,
             ) -> List[Dict[str, Any]]:
    """Every marker of one room, finished in world coordinates.

    Room markers are fractions of the room rectangle with an offset additive
    to the sampled floor; prop markers arrive from the recipe as
    placement-relative transforms (fix → real size → yaw already applied) and
    only need ``placement point + [dx, dz]`` — resolved here, so the consumer
    adds nothing.

    ``y_world`` is the SURFACE the marker names. How far below it a figure's
    root belongs travels with the marker as ``root_offset`` (world metres,
    see FIGURE_ROOT_DROP) — a seated body touches at the buttocks, not at the
    feet. That number used to live in the 3D client alone and only for ROOM
    markers, so prop markers had no drop at all and every author baked one
    into the marker by hand (all 15 in the field carry a negative height).
    One source, both renderers, both marker sources.

    ``lift`` is the terrain sampler of a room that follows the relief (v5.2
    Nr. 14): a marker names a surface, and on a slope that surface has moved
    with the ground under it — so the sample at the marker's OWN anchor is
    added to ``y_world``, the same way it is added to a prop's ``bottom_y``.
    """
    room_id = recipe.get("room_id") or ""
    floor_y = _room_floor_y(recipe, storey)
    x, y, w, d = _room_rect(recipe, room)
    figure_h = FIGURE_HEIGHT_M

    def _root_drop(animation: Any) -> float:
        """World metres a figure's root sinks below the marked surface."""
        return _r(FIGURE_ROOT_DROP.get(str(animation or "").strip().lower(),
                                       0.0) * figure_h)

    out: List[Dict[str, Any]] = []
    for marker in recipe.get("markers") or []:
        at = marker.get("at") or [0.5, 0.5]
        anchor_u = x + _num(at[0], 0.5) * w
        anchor_v = y + _num(at[1], 0.5) * d
        entry: Dict[str, Any] = {
            "room_id": room_id,
            "at_world": [_r(_w(anchor_u, extent)), _r(_w(anchor_v, extent))],
            "y_world": _r(floor_y + _num(marker.get("offset_y"))
                          + (lift(anchor_u, anchor_v) if lift else 0.0)),
            "animation": marker.get("animation") or "",
            "root_offset": _root_drop(marker.get("animation")),
            "source": "room",
        }
        if marker.get("rotation") is not None:
            entry["facing"] = _r(_num(marker.get("rotation")), 1)
        # Tilt axes (2026-07-28): a figure on a slope is not upright, and
        # facing is only the compass. Applied AFTER the facing, in the
        # figure's own frame — tilt = head up/down, roll = leaning sideways.
        for axis in ("tilt", "roll"):
            if marker.get(axis) is not None:
                entry[axis] = _r(_num(marker.get(axis)), 1)
        out.append(entry)
    placements = recipe.get("placements") or []
    # Prop markers are composed relative to the placement point on the floor;
    # the mesh itself stands plate top + clearance higher (§ A4) — the seat
    # heights ride along.
    plate_top = 0.0 if recipe.get("always_visible") else ROOM_PLATE_TOP
    prop_lift = plate_top + PROP_CLEARANCE
    for marker in recipe.get("prop_markers") or []:
        try:
            placement = placements[int(marker.get("placement"))]
        except (TypeError, ValueError, IndexError):
            continue
        at = placement.get("at") or [0.5, 0.5]
        offset = marker.get("offset_m") or [0.0, 0.0]
        # The marker belongs to its PLACEMENT: it is sampled at the prop's
        # anchor, not at its own offset point, so a bench and every seat on
        # it rise by exactly the same amount and the mesh stays level.
        entry = {
            "room_id": room_id,
            "at_world": [_r(_w(at[0], extent) + _num(offset[0])),
                         _r(_w(at[1], extent) + _num(offset[1]))],
            "y_world": _r(floor_y + prop_lift + _num(marker.get("height_m"))
                          + (lift(_num(at[0], 0.5), _num(at[1], 0.5))
                             if lift else 0.0)),
            "animation": marker.get("animation") or "",
            "root_offset": _root_drop(marker.get("animation")),
            "source": "prop",
        }
        if marker.get("facing") is not None:
            entry["facing"] = _r(_num(marker.get("facing")), 1)
        out.append(entry)
    return out


def _figures() -> Dict[str, Any]:
    """Figure scale (§ A3): 1.70 m, everywhere and always.

    Since E4 the scene runs at k = 1, so the anchored ``1.70 × k`` and the
    legacy ``1.70 × storey / 3`` proxy are both gone — a person is 1.70 m
    tall in the scene exactly as on the map. The stand clearance was always
    a world-metre constant."""
    return {"base_height_m_world": _r(FIGURE_HEIGHT_M),
            "stand_clearance": STAND_CLEARANCE}


def _signature(location: Dict[str, Any], plan_width_m: float,
               recipes: List[Dict[str, Any]], building_meta: Dict[str, Any],
               room_metas: Dict[str, Dict[str, Any]],
               ground_kind: str = "") -> str:
    """Change detection for the whole scene — a SUPERSET of the room recipe's
    signature: the room signatures already cover layouts, neighbour openings
    and prop sidecars, and the model metas add every anchor dial (floors,
    height_m, width_m, walk_y, rotation, offsets). Polling it is enough.

    ``ground_kind`` is in here as the RESOLVED kind, not as the raw
    ``terrain`` text: it is what the payload carries, and it also moves when
    the library gains or loses the entry a terrain names."""
    import hashlib
    import json
    payload = {
        "map3d": location.get("map3d") or {},
        "map_rotation_2d": location.get("map_rotation_2d") or 0,
        "plan_width_m": round(float(plan_width_m or 0), 3),
        "ground_kind": ground_kind,
        "rooms": {str(r.get("room_id") or ""): r.get("signature") or ""
                  for r in recipes},
        "building_meta": building_meta or {},
        "room_metas": room_metas or {},
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True,
                                  default=str).encode()).hexdigest()


# ── Composer ────────────────────────────────────────────────────────────

# The four boundary edges of the reference square: fraction point on the
# edge for a given ``at`` (room-opening letter convention — left→right on
# N/S, top→bottom on E/W) and the INWARD normal in world axes (x east,
# z south).
_BOUNDARY_EDGES: Dict[str, Any] = {
    "N": (lambda at: (at, 0.0), [0, 1]),
    "E": (lambda at: (1.0, at), [-1, 0]),
    "S": (lambda at: (at, 1.0), [0, -1]),
    "W": (lambda at: (0.0, at), [1, 0]),
}


def _boundary_openings(map3d: Dict[str, Any],
                       extent: float) -> List[Dict[str, Any]]:
    """Location-edge pass-throughs (plan-area-detail-scenes.md) in world
    metres — where a road enters and leaves the cell.

    Geometry plus the room link, and both are read: the 3D client offers
    "enter" at an opening of the edge a step would cross and walks the figure
    in through it (``main.ts``), while the server decides entry and departure
    on the same data (``boundary_entry``). Still open is the journey
    walk-through — an opening pair plus the linked room's hull is a path
    across the cell.
    """
    out: List[Dict[str, Any]] = []
    for op in (map3d or {}).get("boundary_openings") or []:
        if not isinstance(op, dict):
            continue
        spec = _BOUNDARY_EDGES.get(str(op.get("edge") or "").upper())
        if not spec:
            continue
        try:
            width_m = float(op.get("width_m") or 0)
        except (TypeError, ValueError):
            continue
        # ``at`` degrades to the edge MIDPOINT, exactly like
        # ``boundary_entry._rotated_openings`` — the two used to disagree
        # (0 here, 0.5 there), so an opening without a position sat in the
        # corner for the renderers and in the middle for the entry gate
        # (E3 ledger; boundary_entry wins).
        try:
            at = float(op.get("at"))
        except (TypeError, ValueError):
            at = 0.5
        if not math.isfinite(at):
            at = 0.5
        at = min(max(at, 0.0), 1.0)
        point, inward = spec
        px, py = point(at)
        entry: Dict[str, Any] = {
            "edge": str(op["edge"]).upper(),
            "at_world": [_r(_w(px, extent)), _r(_w(py, extent))],
            "width_m": _r(width_m, 3),
            "type": str(op.get("type") or "passage"),
            "inward": inward,
        }
        room = op.get("room")
        if isinstance(room, str) and room.strip():
            entry["room_id"] = room.strip()
        out.append(entry)
    return out


# ── Tile rotation (v5.2 Nr. 15) ─────────────────────────────────────────

# One clockwise 90° step, seen in PLAN VIEW (x east, z south — screen
# top-down with y down): the letters of the four boundary edges, the side
# words of an extras box and the ``at`` flip that keeps an opening on the
# same physical spot. The ``at`` rule is the editor's ``rotateOpeningCW``
# verbatim (frontend/src/tabs/world/planGeometry.ts) and follows from the
# fraction rule alone: E at 0.3 sits at (1, 0.3) → (1 − 0.3, 1) = (0.7, 1),
# which is S at 0.7.
_TILE_EDGE_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}
_TILE_EDGE_FLIP = {"N": False, "E": True, "S": False, "W": True}
_TILE_SIDE_CW = {"north": "east", "east": "south",
                 "south": "west", "west": "north"}


def _rotate_scene(out: Dict[str, Any], quarters: int,
                  extent: float) -> Dict[str, Any]:
    """Turn the FINISHED scene payload ``quarters`` × 90° clockwise about the
    square's centre (``map3d.tile_rotation``), in place, and return it.

    Why the payload and not the plan: one template location — a road running
    east–west, a corner piece, a river bend — is cloned onto several map
    cells, and each clone only differs in which way it faces. The floor-plan
    editor keeps editing the ONE template in its base orientation; the server
    turns the composed result. Both renderers stay dumb, exactly as § B5
    demands, and nothing in the stored plan moves.

    Conventions (plan view, x east / z south, i.e. screen top-down, y down —
    so "clockwise on screen" is what the two rules below encode):

    * **World point / vector**, one step: ``(x, z) → (−z, x)``. The origin is
      the square's centre, so the same matrix serves points and directions
      (``outward_normal``, ``inward``) with no translation anywhere.
    * **Plan fraction**, one step: ``(u, v) → (1 − v, u)`` — the world rule
      carried into the unit square, whose centre is 0.5 instead of 0.

    Consequences the payload has to carry along:

    * ``models[].yaw_deg`` is a MODEL yaw around +y, rendered as
      ``rotation.y = +rad(yaw)`` since E4. One clockwise step is the matrix
      ``(x, z) → (−z, x)``, i.e. ``R_y(−90)``, and it multiplies onto the
      model's own turn: ``R_y(−90)·R_y(yaw) = R_y(yaw − 90)`` →
      ``(yaw + 270 · quarters) % 360``. (It read ``+90`` until the final E4
      review: that was the compensation for the OLD ``rotation.y = −rad(yaw)``
      and became a double turn when the four render sites were flipped.)
    * ``markers[].facing`` (and a room marker's ``rotation``) is a COMPASS in
      the figure convention 0 = south, 90 = east — and since E4 it grows in
      the SAME sense as the model yaw (§ A1.8), because both go through the
      same ``rotation.y = +rad(…)``. A clockwise scene step therefore turns a
      south-facing figure west by the very same amount:
      ``compass_new = (compass + 270 · quarters) % 360``.
    * A box in ``extras`` keeps its height and swaps its w/d extents on an odd
      number of steps; its ``side`` word rotates N→E→S→W like an edge letter.
    * ``terrain.grid`` is resampled instead of transformed —
      :func:`rotate_terrain_grid` holds that rule, because the walking gate
      has to reproduce it to sample the field the client actually got.
      ``step`` and ``amplitude_m`` are rotation-invariant.

    Untouched on purpose: ``signature`` (``map3d`` is hashed whole, so
    ``tile_rotation`` moves it by itself), ``extent_m`` / ``k`` / ``storey_m``
    / ``levels`` / ``style`` / ``figures`` / ``outdoor_rooms`` /
    ``area_detail`` — all rotation-invariant — and every height (``y``,
    ``base_y``, ``top_y``, ``bottom_y``, ``y_world``), because the axis of
    rotation IS +y.

    Every transformed coordinate goes back through ``_r`` (4 places, no
    −0.0), and every list is REBUILT rather than mutated: the composer shares
    point lists between entries (one contour list across all level plates, one
    normal across an edge's wall pieces, the module-level ``inward`` vectors),
    so in-place edits would rotate some of them repeatedly.
    """
    steps = int(quarters) % 4
    if steps == 0:
        return out

    def rot_world(x: float, z: float) -> Tuple[float, float]:
        for _ in range(steps):
            x, z = -z, x
        return x, z

    def rot_frac(u: float, v: float) -> Tuple[float, float]:
        for _ in range(steps):
            u, v = 1.0 - v, u
        return u, v

    def pt_world(p: Any) -> List[float]:
        x, z = rot_world(_num(p[0]), _num(p[1]))
        return [_r(x), _r(z)]

    def poly_world(points: Any) -> List[List[float]]:
        return [pt_world(p) for p in points or []
                if isinstance(p, (list, tuple)) and len(p) >= 2]

    def poly_frac(points: Any) -> List[List[float]]:
        out_pts: List[List[float]] = []
        for p in points or []:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            u, v = rot_frac(_num(p[0]), _num(p[1]))
            out_pts.append([_r(u), _r(v)])
        return out_pts

    for plate in out.get("plates") or []:
        if plate.get("outline"):
            plate["outline"] = poly_world(plate["outline"])

    for wall in out.get("walls") or []:
        for key in ("from", "to", "outward_normal"):
            if wall.get(key):
                wall[key] = pt_world(wall[key])

    for extra in out.get("extras") or []:
        centre = extra.get("center")
        if isinstance(centre, (list, tuple)) and len(centre) == 3:
            x, z = rot_world(_num(centre[0]), _num(centre[2]))
            extra["center"] = [_r(x), _r(_num(centre[1])), _r(z)]
        size = extra.get("size")
        if isinstance(size, (list, tuple)) and len(size) == 3 and steps % 2:
            extra["size"] = [_r(_num(size[2])), _r(_num(size[1])),
                             _r(_num(size[0]))]
        side = extra.get("side")
        if isinstance(side, str) and side in _TILE_SIDE_CW:
            for _ in range(steps):
                side = _TILE_SIDE_CW[side]
            extra["side"] = side

    for spec in out.get("models") or []:
        if spec.get("anchor"):
            spec["anchor"] = pt_world(spec["anchor"])
        if spec.get("yaw_deg") is not None:
            spec["yaw_deg"] = _r((_num(spec["yaw_deg"]) + 270 * steps) % 360, 1)
        if spec.get("clip_outline"):
            spec["clip_outline"] = poly_world(spec["clip_outline"])
        if spec.get("cutouts"):
            spec["cutouts"] = [poly_world(poly) for poly in spec["cutouts"]]

    for marker in out.get("markers") or []:
        if marker.get("at_world"):
            marker["at_world"] = pt_world(marker["at_world"])
        for key in ("facing", "rotation"):
            if marker.get(key) is not None:
                marker[key] = _r((_num(marker[key]) + 270 * steps) % 360, 1)

    for door in out.get("doorways") or []:
        # The same matrix serves both: ``at_world`` is a point around the tile
        # centre, ``along`` a direction — and the origin IS the centre, so
        # there is no translation to leave out. Width, foot and rooms are
        # rotation-invariant.
        if door.get("at_world"):
            door["at_world"] = pt_world(door["at_world"])
        if door.get("along"):
            door["along"] = pt_world(door["along"])

    for block in out.get("rooms") or []:
        if block.get("outline"):
            block["outline"] = poly_frac(block["outline"])
        overlay = block.get("overlay")
        if isinstance(overlay, dict):
            if overlay.get("centre"):
                overlay["centre"] = pt_world(overlay["centre"])
            rect = overlay.get("rect")
            if isinstance(rect, dict):
                rx, rz = rot_world(_num(rect.get("x")), _num(rect.get("z")))
                rw, rd = _num(rect.get("w")), _num(rect.get("d"))
                if steps % 2:
                    rw, rd = rd, rw
                overlay["rect"] = {"x": _r(rx), "z": _r(rz),
                                   "w": _r(rw), "d": _r(rd)}

    for opening in out.get("boundary_openings") or []:
        letter = str(opening.get("edge") or "").upper()
        at_world = opening.get("at_world")
        if letter not in _TILE_EDGE_CW or not at_world:
            continue
        # Back to the edge frame: the FREE coordinate of an edge is u on N/S
        # and v on E/W — the other one is pinned to 0 or 1 by the edge itself.
        u = _num(at_world[0]) / extent + 0.5
        v = _num(at_world[1]) / extent + 0.5
        at = u if letter in ("N", "S") else v
        for _ in range(steps):
            if _TILE_EDGE_FLIP[letter]:
                at = 1.0 - at
            letter = _TILE_EDGE_CW[letter]
        point, _inward = _BOUNDARY_EDGES[letter]
        px, pv = point(round(at, 6))
        opening["edge"] = letter
        opening["at_world"] = [_r(_w(px, extent)), _r(_w(pv, extent))]
        inward = opening.get("inward")
        if inward:
            # Rotating the stored vector and looking up the new edge's own
            # inward normal are the same thing — the vector is kept as the
            # integer pair the contract promises.
            ix, iz = rot_world(_num(inward[0]), _num(inward[1]))
            opening["inward"] = [int(round(ix)), int(round(iz))]

    terrain = out.get("terrain")
    grid = (terrain or {}).get("grid") if isinstance(terrain, dict) else None
    if grid:
        terrain["grid"] = rotate_terrain_grid(grid, steps)
    return out


def compose_terrain(map3d: Dict[str, Any], recipes: List[Dict[str, Any]],
                    extent: float, variant: int
                    ) -> Tuple[Optional[Dict[str, Any]], Set[str]]:
    """The location's height field (``terrain`` payload block) and the ids of
    the rooms that stand ON it — ``(None, set())`` when there is no relief.

    Extracted out of :func:`compose_scene` so there stays exactly ONE grid
    construction in the codebase: since E8 the WALKING GATE
    (``app/core/relief.scene_ground_lift``) samples the very same field the
    payload ships, and a second derivation of seed, wave width or flat hulls
    would let the rule and the picture drift apart by construction.

    A detail scene without a diorama is a billiard table; the relief gives it
    a deterministic height field. The composer owns the whole vertical story:
    it lifts EVERYTHING that stands in a non-flat room, and the renderers only
    drape the ground they are told to drape — no object height is ever sampled
    twice or set by hand.

    FLAT = every indoor room (walls need a level floor) plus every outdoor
    room that opted out via ``relief_flat`` (road, paved square). Their hulls
    are pinned to zero in the field, so nothing in them moves by a single
    digit. The recipe ``outline`` is already the tessellated hull in absolute
    plan fractions — the same points the plates use, not a second derivation.

    The relief only survives the sanitizer on an ``area_detail`` location; the
    gate is repeated here because a hand-posted or legacy map3d must not put a
    height field under an ordinary building either.
    """
    relief = (map3d or {}).get("relief")
    if not isinstance(relief, dict) or not (map3d or {}).get("area_detail"):
        return None, set()
    amplitude_world = _num(relief.get("amplitude_m"))
    if amplitude_world <= 0:
        return None, set()
    relief_rooms: Set[str] = set()
    flat_hulls: List[List[List[float]]] = []
    for recipe in recipes:
        hull = [[_num(p[0]), _num(p[1])]
                for p in recipe.get("outline") or []]
        if recipe.get("always_visible") and not recipe.get("relief_flat"):
            relief_rooms.add(str(recipe.get("room_id") or ""))
        elif len(hull) >= 3:
            flat_hulls.append(hull)
    # The wave width is authored in metres and divided into the edge length of
    # the reference square — the same frame since E4 (extent IS plan_width_m,
    # k = 1).
    cells = relief_cells(relief.get("wave_m"), extent)
    grid = terrain_grid(variant_mix(int(_num(relief.get("seed"))), variant),
                        amplitude_world, flat_hulls, cells)
    # ``step`` follows the grid that was actually built, never the default —
    # otherwise the renderers subdivide with a cell size that does not exist
    # in the payload they were handed.
    return ({"step": _r(extent / (len(grid) - 1)), "grid": grid,
             "amplitude_m": _r(amplitude_world)}, relief_rooms)


def layout_signature(map3d: Dict[str, Any],
                     rooms: List[Dict[str, Any]]) -> str:
    """Hash over everything that SHAPES a location's scene: its ``map3d``
    (boundary openings, rotation, size, ``tile_rotation``, ``plan_width_m``,
    ``storey_height_m``, ``floors``, the relief dials) plus every room that has
    a layout.

    Two consumers, deliberately one function: the worldmap payload ships the
    first 10 characters as ``layout_sig`` so a running client knows when to
    refetch a scene (E5 finding B11), and the walking gate keys its height-field
    cache on it (``core/relief``). Room layouts alone were never enough — a gate
    drawn into the boundary changes the scene and nothing else.
    """
    import hashlib
    import json
    rows = [(r.get("id"), r.get("layout"))
            for r in (rooms or [])
            if isinstance(r, dict) and r.get("layout")]
    return hashlib.md5(json.dumps([rows, map3d or {}], sort_keys=True,
                                  default=str).encode()).hexdigest()


def tile_rotation_steps(map3d: Dict[str, Any]) -> int:
    """How many 90° steps the FINISHED payload is turned by (0–3).

    ONE decision, two callers: :func:`compose_scene` turns the payload with it
    and the walking gate reproduces the same turn on the height field. Anything
    that is not a right angle — 0, 45, an empty field, a string — is no
    rotation at all, and ``_num`` swallows the unreadable cases rather than
    raising on a stored blob nobody sanitized.
    """
    quarters = int(_num((map3d or {}).get("tile_rotation")))
    return (quarters // 90) % 4 if quarters in (90, 180, 270) else 0


def rotate_terrain_grid(grid: List[List[float]],
                        steps: int) -> List[List[float]]:
    """Turn a height field ``steps`` × 90° clockwise about the square's centre.

    The field is indexed ``grid[j][i]`` at plan fraction ``(i/n, j/n)``, so a
    rotated field must answer ``h_new(u, v) = h_old(rot⁻¹(u, v))`` with the
    INVERSE (counter-clockwise) step ``rot⁻¹(u, v) = (v, 1 − u)``.
    Substituting ``(u, v) = (i/n, j/n)`` gives ``(j/n, 1 − i/n)``, i.e. old
    indices ``i_old = j`` and ``j_old = n − i`` — hence
    ``new[j][i] = old[n−i][j]``. It is RESAMPLED, never transformed.

    One rule, two callers: the payload rotation (:func:`_rotate_scene`) and
    the walking gate, which has to sample the field the client actually got.
    """
    n = len(grid) - 1
    for _ in range(int(steps) % 4):
        grid = [[grid[n - i][j] for i in range(n + 1)] for j in range(n + 1)]
    return grid


def compose_scene(location: Dict[str, Any], *, plan_width_m: float = 0.0,
                  building_meta: Optional[Dict[str, Any]] = None,
                  room_metas: Optional[Dict[str, Dict[str, Any]]] = None,
                  surface_kinds: Optional[Set[str]] = None,
                  ) -> Dict[str, Any]:
    """The whole scene of ONE location as finished primitives (§ B1).

    ``plan_width_m`` is the resolved scale anchor (see
    ``location_model3d.derive_plan_width_m``), ``building_meta`` the building
    model's client meta, ``room_metas`` the room models' client metas by
    room id and ``surface_kinds`` the ids the surface library holds — the
    route loads all four, the composer only computes. Without the library
    the location's ``terrain`` resolves to nothing and the ground keeps the
    default kind.
    """
    map3d = location.get("map3d") or {}
    # The ground OUTSIDE (plan-grundflaeche.md § 5): the location's terrain,
    # resolved against the library HERE so the world map and the detail
    # scene cannot disagree about it any more.
    from app.core.surface_textures import resolve_terrain_kind
    ground_kind = resolve_terrain_kind(location.get("terrain"),
                                       surface_kinds or ())
    rooms = [r for r in (location.get("rooms") or []) if isinstance(r, dict)]
    # A copy placed on the map owns ONE number; it is mixed into every seed
    # this location inherits from its template, so two copies stop looking
    # identical. 0 = not a copy, and then every seed stays untouched.
    variant = int(location.get("variant_seed") or 0)
    building_meta = building_meta or {}
    room_metas = room_metas or {}
    extent, k, storey = derive_scalars(map3d, plan_width_m)

    recipes: List[Dict[str, Any]] = []
    by_room: Dict[str, Dict[str, Any]] = {}
    for room in rooms:
        recipe = compose_recipe(room, [r for r in rooms if r is not room],
                                plan_width_m, variant_seed=variant)
        if not recipe:
            continue
        recipes.append(recipe)
        by_room[str(room.get("id") or "")] = room
    levels = _used_levels(recipes)

    # Thresholds as finished primitives (plan-betreten-und-tueren.md § 4.1) —
    # composed BEFORE the shell, because the shell takes its holes from them
    # (§ 4.2). One derivation, two consumers: this block and the payload.
    doorways = _doorways(recipes, storey, extent)

    # Indoor room hulls per level, world metres — where they run on the
    # contour line, the contour wall yields (one wall, one owner).
    room_hulls: Dict[int, List[List[List[float]]]] = {}
    shell_levels: Set[int] = set()
    for recipe in recipes:
        # A room that emits no walls of its own cannot own a contour stretch
        # either — letting the contour yield to it would leave a gap with no
        # wall at all instead of one wall with one owner.
        if recipe.get("always_visible") or recipe.get("no_walls"):
            continue
        hull = _room_outline_world(recipe, extent)
        if hull:
            level = int(recipe.get("level") or 0)
            room_hulls.setdefault(level, []).append(hull)
            shell_levels.add(level)

    # Every OUTSIDE door as a hole for the hull: middle, outward normal and
    # clear width, straight off the doorway — the contour projects them, it
    # does not measure a door of its own (§ 4.2).
    outside_doors = [{"level": d["level"], "at": d["at_world"],
                      "width": d["width_m"], "normal": _door_outward(d)}
                     for d in doorways if d.get("outside")]

    walls: List[Dict[str, Any]] = _contour_walls(map3d, levels, storey, extent,
                                                 outside_doors, room_hulls)
    models: List[Dict[str, Any]] = []
    markers: List[Dict[str, Any]] = []
    building = _building_model(location, map3d, building_meta, extent)
    if building:
        models.append(building)

    # ── Area location (plan-area-locations.md) ──────────────────────────
    # The model stays standing in the interior view, so the recipe interior
    # needs holes to stand in. Which room is CUT and which one is laid ON the
    # model follows from outdoor/indoor plus its position relative to the
    # floor plan — no per-room display field exists, deliberately.
    # With ``area_detail`` (plan-area-detail-scenes.md) the model FADES like a
    # building shell instead, so there is nothing to cut holes into or to lay
    # zones onto: the rooms compose like a normal building interior (outdoor
    # rooms keep their texture-only plates) and this whole branch is skipped.
    area_model = bool(map3d.get("area_model")) \
        and not bool(map3d.get("area_detail"))
    contour_world = _outline_world(map3d, extent)
    overlay_rooms: Dict[str, Dict[str, Any]] = {}
    if area_model:
        outside_indoor: List[Tuple[str, List[List[float]]]] = []
        outside_outdoor: List[Dict[str, Any]] = []
        for recipe in recipes:
            outline = _room_outline_world(recipe, extent)
            if not outline or _bbox_inside(outline, contour_world):
                continue
            if recipe.get("always_visible"):
                outside_outdoor.append(recipe)
            else:
                outside_indoor.append((str(recipe.get("room_id") or ""), outline))
        cutout_polys = _cutouts(contour_world, outside_indoor)
        if cutout_polys and building:
            building["cutouts"] = cutout_polys
        # Outdoor zones ON the model surface: no plate, no walls — but a
        # position, so NPCs, markers and labels have somewhere to stand. The
        # height is the model's walkable surface where it declares one,
        # otherwise its lower edge; without a model the storey floor.
        for recipe in outside_outdoor:
            outline = _room_outline_world(recipe, extent)
            xs = [p[0] for p in outline]
            zs = [p[1] for p in outline]
            cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
            if building:
                y = _num(building.get("walk_y_world"),
                         _num(building.get("bottom_y")))
            else:
                y = int(recipe.get("level") or 0) * storey
            # A zone on a SLOPE is not at the model's nominal ground either —
            # the room's own height offset applies here exactly as it does to
            # a built room's plate.
            y += _num(recipe.get("floor_offset_y"))
            overlay_rooms[str(recipe.get("room_id") or "")] = {
                "centre": [_r(cx), _r(cz)],
                "rect": {"x": _r(cx), "z": _r(cz),
                         "w": _r(max(max(xs) - min(xs), 0.5)),
                         "d": _r(max(max(zs) - min(zs), 0.5))},
                "y": _r(y),
            }
    terrain, relief_rooms = compose_terrain(map3d, recipes, extent, variant)

    def _lift_for(room_id: str) -> Optional[Callable[[float, float], float]]:
        """The terrain sampler of one room — ``None`` for a flat room, which
        is what keeps every existing number bit-identical there."""
        if terrain is None or room_id not in relief_rooms:
            return None
        return lambda u, v: terrain_height(terrain["grid"], u, v)

    for recipe in recipes:
        room_id = str(recipe.get("room_id") or "")
        room = by_room.get(room_id) or {}
        lift = _lift_for(room_id)
        walls.extend(_room_walls(recipe, storey, extent, min(levels)))
        diorama = _diorama_model(recipe, room, room_metas.get(room_id) or {},
                                 storey, extent, lift)
        if diorama:
            models.append(diorama)
        models.extend(_prop_models(recipe, storey, extent, lift))
        markers.extend(_markers(recipe, room, storey, extent, lift))

    # A threshold lies at the STANDING height of the rooms it joins, and THIS
    # is where that is decided (finding 2026-08-16: the 3D client recomputed
    # the height against its own sampled room floors — and mixed tile-local
    # metres with world metres while doing it, so every quad floated 10–15 cm
    # over the floor). The declared walkable surface is read off the diorama
    # spec that already carries it, so no room's floor is derived twice.
    stand_by_room = {str(spec.get("room_id") or ""): _num(spec["walk_y_world"])
                     for spec in models
                     if spec.get("role") == "room"
                     and spec.get("walk_y_world") is not None}
    for door in doorways:
        door["base_y"] = _r(threshold_base_y(
            [(_num(door["base_y"]), stand_by_room.get(room_id))
             for room_id in door["rooms"]]))

    # Per-room recipe vocabulary in PLAN FRACTIONS — the 2D editor's ghost
    # openings draw from here instead of re-deriving the mirroring locally
    # (v4: no geometry twice). Pure pass-through of the room recipe: the
    # openings are already normalized AND mirrored in.
    room_blocks = []
    for r in recipes:
        block: Dict[str, Any] = {
            "room_id": r.get("room_id") or "",
            "level": int(r.get("level") or 0),
            "always_visible": bool(r.get("always_visible")),
            "outline": r.get("outline") or [],
            "openings": r.get("openings") or [],
        }
        # Zone on the model surface instead of a built room — the consumer
        # takes centre/rect/y from HERE, because there is no plate to read
        # them off (area location, plan-area-locations.md).
        overlay = overlay_rooms.get(block["room_id"])
        if overlay:
            block["overlay"] = overlay
        room_blocks.append(block)

    boundary = _boundary_openings(map3d, extent)

    out = {
        "signature": _signature(location, plan_width_m, recipes,
                                building_meta, room_metas, ground_kind),
        "rooms": room_blocks,
        # extent_m = the size of the reference square: the ONE number that
        # turns every fraction in this payload into metres. Consumers must
        # read it instead of assuming a constant (they used to assume 8).
        # Since E4 it IS the location's footprint edge (map3d.plan_width_m).
        "extent_m": _r(extent),
        # k = world metres per real metre. CONSTANT 1 since E4 — the field
        # stays because consumers multiply by it (× 1 is right for them),
        # not because it can be anything else.
        "k": _r(k, 6),
        "storey_m": _r(storey),
        "levels": [{"level": lv, "floor_y": _r(lv * storey)} for lv in levels],
        "style": STYLE,
        # Overlay rooms get no plate from the normal path: they lie ON the
        # model, and a surface at storey height would cut through it. One that
        # DECLARES a floor kind gets it at the zone's own height instead —
        # that is how a drawn area becomes a lake (_overlay_plates).
        "plates": (_plates(map3d, [r for r in recipes
                                   if str(r.get("room_id") or "") not in overlay_rooms],
                           levels, storey, extent, relief_rooms,
                           ground_kind)
                   + _overlay_plates(recipes, overlay_rooms, min(levels), extent)),
        "walls": walls,
        "extras": _elevator(map3d, levels, storey, extent),
        "models": models,
        "figures": _figures(),
        "markers": markers,
        # Thresholds as finished primitives (plan-betreten-und-tueren.md
        # § 4.1) — from the same spans the walls are split by, so no consumer
        # ever measures a door back out of the geometry again.
        "doorways": doorways,
        "outdoor_rooms": [r.get("room_id") or "" for r in recipes
                          if r.get("always_visible")],
        # What the composer found wrong and did NOT repair behind the
        # author's back (§ 4.3). Always present, empty when all is well;
        # editor and 3D client only display it.
        "problems": _problems(location, map3d, extent, shell_levels, doorways,
                              recipes),
    }
    if boundary:
        out["boundary_openings"] = boundary
    if terrain:
        out["terrain"] = terrain
    # Detail mode is a property of the LOCATION, not of its model: a forest
    # may have no location model at all (the whole point of the detail
    # scenes), and the renderers still need to know — backstop plate, fade
    # gate and zone handling key off this flag; `display: shell_area` on the
    # building spec is merely its per-model consequence (user finding
    # 2026-08-02: without a model the backstop buried the zone plates).
    if map3d.get("area_model") and map3d.get("area_detail"):
        out["area_detail"] = True
    # Tile rotation (v5.2 Nr. 15) is the LAST word: the whole finished payload
    # turns about the square's centre, so one template location can be cloned
    # onto several places facing different ways. Everything above composed the
    # template in its base orientation — that is what the editor edits.
    steps = tile_rotation_steps(map3d)
    if steps:
        _rotate_scene(out, steps, extent)
    return out
