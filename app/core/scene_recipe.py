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
centre of the location, like the 8 × 8 m reference square — the consumer
attaches the scene to its tile):

- ``plates``  — one contour plate per used level plus one floor plate per room,
- ``walls``   — the building contour with its door gaps and the room shell
                walls already split around every opening (window = sill +
                head + glass segment),
- ``extras``  — the elevator primitives,
- ``style``   — the colours/opacities both renderers used to keep as copies,
- ``models``  — ONE spec form for building, room diorama and prop; the client
                runs the single ``place()`` routine of § B2 over it,
- ``figures``/``markers``/``exits`` — the figure scale and every anchor point
                already resolved into world coordinates.

Numbers are NOT free here: every constant below is quoted from the contract
(``docs/schnittstellen-3d.md``, § A2/A3/A6 for the values, part B for the
payload shape) — that document, not this file, is where a value is changed.
When code and contract disagree, the CONTRACT wins.

The composer is pure: location dict + rooms in, primitives out. Loading
(world DB, model sidecars, scale anchor) is the route's job; the prop library
is read through ``room_recipe`` exactly as the room recipe does it.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.room_recipe import compose_recipe

logger = get_logger(__name__)

# ── Contract constants (§ A2/A3/A6) ─────────────────────────────────────
# The map grid spaces locations 10 × 10 world metres apart. How much of that
# a location actually occupies is its own dial: ``map3d.extent_m`` is the
# REFERENCE SQUARE — the frame every plan fraction lives in AND the box the
# location model fills. ONE frame (2026-07-28): plan edge == model edge, so
# the floor plan can always reach the model. Before that there were three
# unrelated rectangles (tile 10, model 10 × 0.92 × size, plan 8) and the
# outer 0.6 m of a size-1 model was not addressable by any fraction.
TILE_M = 10.0
DEFAULT_EXTENT_M = TILE_M
# Storey height in REAL metres when the location does not declare one.
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
# = plate top + this clearance (+ offset_y × k). Outdoor rooms have no
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
# Contour doors (ground floor only): a room exit closer than 0.45 m to the
# contour punches a ±0.4 m gap; wall pieces below 0.06 m are dropped.
DOOR_SNAP_M = 0.45
DOOR_HALF_GAP_M = 0.4
MIN_WALL_PIECE_M = 0.06
# Anything shorter/lower than this is not worth a primitive.
MIN_SEGMENT_M = 0.02
# Elevator (§ A6) — all real metres × k.
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
# Figures (§ A3): 1.70 m at the plan scale; the clearance is a world-metre
# CONSTANT (never × k).
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
# Editor-only overlay colours (markers, exit dots, ruler) are deliberately
# NOT here: they are preview aids, not contract geometry. The elevator IS
# contract geometry (extras), so its colours are.
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
    """Reference-square fraction → world metre (origin = tile centre)."""
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

    ``extent_m`` = how wide the location is in WORLD metres (the reference
    square), ``k`` = world metres per REAL metre = extent_m / plan_width_m.
    Without a scale anchor the location runs in LEGACY mode (k = 1).
    ``storey_m`` = the declared storey height in REAL metres × k — one dial
    in the same unit as everything else, replacing the old pair
    ``height_m / floors`` (real) and ``level_height`` (world).
    """
    extent = _num((map3d or {}).get("extent_m")) or DEFAULT_EXTENT_M
    k = extent / plan_width_m if plan_width_m > 0 else 1.0
    storey_real = (_num((map3d or {}).get("storey_height_m"))
                   or DEFAULT_STOREY_REAL_M)
    return extent, k, storey_real * k


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


def _room_floor_y(recipe: Dict[str, Any], storey: float, k: float) -> float:
    """The height the room's FLOOR sits at: its storey plus the room's own
    offset (``layout.floor_offset_y``, real metres × k).

    Inside a building the offset is 0 and this is just the storey. It matters
    where a room cuts a hole into a LOCATION model: terrain is not flat, so a
    hut on the slope needs its floor where the ground actually is — otherwise
    it floats over or sinks into the hole it made (user finding 2026-07-28).
    Everything in the room derives from here, so plate, walls, props, markers,
    exit and diorama move as one.
    """
    return (int(recipe.get("level") or 0) * storey
            + _num(recipe.get("floor_offset_y")) * k)


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


def room_exit_world(recipe: Dict[str, Any], room: Dict[str, Any],
                    extent: float) -> Optional[List[float]]:
    """A room's entry/exit point in WORLD metres, or None.

    Two frames meet here: an EXPLICIT ``layout.exit`` is a fraction of the
    room RECTANGLE (that is how the 2D editor stores it), while the recipe's
    DERIVED exit already comes in absolute plate fractions (it is projected
    off the absolute hull). Resolving that is exactly what a world-coordinate
    payload is for — the consumer never sees the difference again.
    """
    exit_pt = recipe.get("exit")
    if not isinstance(exit_pt, (list, tuple)) or len(exit_pt) != 2:
        return None
    ex, ey = _num(exit_pt[0]), _num(exit_pt[1])
    if recipe.get("exit_derived"):
        return [_r(_w(ex, extent)), _r(_w(ey, extent))]
    x, y, w, d = _room_rect(recipe, room)
    return [_r(_w(x + ex * w, extent)), _r(_w(y + ey * d, extent))]


# ── Plates ──────────────────────────────────────────────────────────────

def _plates(map3d: Dict[str, Any], recipes: List[Dict[str, Any]],
            levels: List[int], storey: float, k: float,
            extent: float) -> List[Dict[str, Any]]:
    """One contour plate per used level + one floor plate per room.

    The level plate carries the storey's floor kind (``map3d.level_floors``,
    else the global ``floor`` kind); the rooms lay their own plates ON TOP,
    so a room floor overrides only its own area. Outdoor rooms (§ A5) get NO
    body — they appear as a plate of thickness 0, i.e. a pure texture surface
    on the ground below.
    """
    plates: List[Dict[str, Any]] = []
    contour = _outline_world(map3d, extent)
    level_floors = (map3d or {}).get("level_floors") or {}
    ground = min(levels)
    if contour:
        for level in levels:
            kind = ""
            if isinstance(level_floors, dict):
                kind = str(level_floors.get(str(level)) or "").strip()
            plates.append({
                "level": level,
                "outline": contour,
                "top_y": _r(level * storey + LEVEL_PLATE_TOP),
                "thickness": LEVEL_PLATE_THICKNESS,
                "texture_kind": kind or DEFAULT_FLOOR_KIND,
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
            "top_y": _r(_room_floor_y(recipe, storey, k)
                        + (0.0 if outdoor else ROOM_PLATE_TOP)),
            "thickness": 0.0 if outdoor else ROOM_PLATE_THICKNESS,
            "opacity_role": _opacity_role(level, ground),
            "room_id": recipe.get("room_id") or "",
        }
        kind = str(((recipe.get("surfaces") or {}).get("floor")) or "").strip()
        if kind:
            entry["texture_kind"] = kind
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


def _contour_walls(map3d: Dict[str, Any], levels: List[int], storey: float,
                   extent: float, exits: List[List[float]],
                   room_hulls: Optional[Dict[int, List[List[List[float]]]]] = None,
                   ) -> List[Dict[str, Any]]:
    """The building contour as walls, per used level (§ A6).

    The ground floor gets a door gap wherever a room exit projects onto the
    contour closer than 0.45 m; without a single such exit ONE central door
    is punched into the southernmost wall piece, so a building is never
    sealed shut.

    ONE wall, one owner (finding 2026-07-27, "Haus von Kai": 27 colinear
    pairs, 16.5 m doubled → z-fighting the moment a wall texture landed on
    the room side): wherever an INDOOR room hull runs on the contour line,
    the contour piece yields — the room wall carries texture and openings.
    ``room_hulls`` maps level → list of room outlines in world metres.

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

    doors: Dict[int, List[float]] = {}
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        frame = _edge_frame(a, b)
        if not frame:
            continue
        ux, uz, length = frame
        for ex, ez in exits:
            t = min(length, max(0.0, (ex - a[0]) * ux + (ez - a[1]) * uz))
            if math.hypot(ex - (a[0] + ux * t), ez - (a[1] + uz * t)) < DOOR_SNAP_M:
                doors.setdefault(i, []).append(t)
    if not doors:
        best, best_z = 0, -math.inf
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            mid_z = (a[1] + b[1]) / 2
            if mid_z > best_z:
                best_z, best = mid_z, i
        a = pts[best]
        b = pts[(best + 1) % len(pts)]
        doors[best] = [math.hypot(b[0] - a[0], b[1] - a[1]) / 2]

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
        holes = sorted((t - DOOR_HALF_GAP_M, t + DOOR_HALF_GAP_M)
                       for t in doors.get(i, []))
        for level in levels:
            # Door gaps stay a level-0 thing: the building entrance sits on
            # the terrain storey even when a basement exists below it.
            lvl_holes = list(holes) if level == 0 else []
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


def _room_walls(recipe: Dict[str, Any], storey: float, k: float,
                extent: float, ground_level: int) -> List[Dict[str, Any]]:
    """One room's shell walls, split around its openings (§ A4).

    Doors and passages leave a full-height gap; a window keeps a sill segment
    below and a head segment above and fills the hole with a glass segment.
    Mirrored openings (the neighbour's door in the shared wall) arrive
    pre-translated in the recipe and are treated exactly like own ones.
    Outdoor rooms have no shell at all (§ A5).

    ``no_walls`` is the per-room opt-out (open zone, pavilion, an area inside
    an area model): NOTHING is emitted — no segments, no window sill or head,
    no glass. Everything else about the room stays: its plate, its exit, its
    openings in the ``rooms`` block (the 2D editor keeps drawing them), its
    markers and its diorama. The BUILDING's contour walls are untouched.
    """
    if recipe.get("always_visible") or recipe.get("no_walls"):
        return []
    outline = [[_w(p[0], extent), _w(p[1], extent)]
               for p in recipe.get("outline") or []]
    if len(outline) < 3:
        return []
    level = int(recipe.get("level") or 0)
    # Room shell walls stand on the ROOM plate (0.10), the contour walls on
    # the level plate (0.08) — § A4/A6.
    base = _room_floor_y(recipe, storey, k) + ROOM_PLATE_TOP
    height = _wall_height(storey)
    kind = str(((recipe.get("surfaces") or {}).get("wall")) or "").strip()
    room_id = recipe.get("room_id") or ""
    role = _opacity_role(level, ground_level)
    walls: List[Dict[str, Any]] = []

    for i, a in enumerate(outline):
        b = outline[(i + 1) % len(outline)]
        frame = _edge_frame(a, b)
        if not frame:
            continue
        ux, uz, length = frame
        # Clockwise hull → the outward normal of (ux, uz) is (uz, −ux).
        normal = [_r(uz), _r(-ux)]

        spans: List[Tuple[float, float, Dict[str, Any]]] = []
        for op in recipe.get("openings") or []:
            try:
                if int(op.get("edge") or 0) != i:
                    continue
            except (TypeError, ValueError):
                continue
            half = min(_num(op.get("width_m")) * k / 2, length / 2)
            centre = min(max(_num(op.get("at")), 0.0), 1.0) * length
            spans.append((max(0.0, centre - half),
                          min(length, centre + half), op))
        spans.sort(key=lambda s: s[0])

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
            sill = min(_num(op.get("sill_m")) * k, height)
            top = min((_num(op.get("sill_m")) + _num(op.get("height_m"))) * k,
                      height)
            _emit(s0, s1, 0.0, sill, WALL_THICKNESS)
            _emit(s0, s1, top, height - top, WALL_THICKNESS)
            _emit(s0, s1, sill, top - sill,
                  WALL_THICKNESS * GLASS_THICKNESS_FACTOR, glass=True)
    return walls


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
              k: float, extent: float) -> List[Dict[str, Any]]:
    """The elevator of a building: shaft columns + roof, glass on three sides
    (the side facing the building centre stays open), a pad per level and a
    static cabin on the ground floor (§ A6). All sizes are real metres × k —
    the caller hands in the LEGACY figure scale (storey / 3) as k when the
    location has no anchor, exactly like the preview's kEl.
    """
    pos = (map3d or {}).get("elevator")
    if not isinstance(pos, (list, tuple)) or len(pos) != 2:
        return []
    ex, ez = _w(pos[0], extent), _w(pos[1], extent)
    top_level = max([0] + list(levels))
    shaft_top = (top_level + 1) * storey + LEVEL_PLATE_TOP
    outer = ELEVATOR_SHAFT_M * k
    column = max(ELEVATOR_COLUMN_M * k, 0.05)

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
    pad = ELEVATOR_PAD_M * k
    for level in levels:
        out.append(_box("elevator_pad", ex,
                        level * storey + LEVEL_PLATE_TOP - ELEVATOR_PAD_THICKNESS / 2,
                        ez, pad, ELEVATOR_PAD_THICKNESS, pad, level=level))
    cabin = ELEVATOR_CABIN_M * k
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


def _building_model(location: Dict[str, Any], map3d: Dict[str, Any],
                    meta: Dict[str, Any], k: float,
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
      to state is where the ground sits inside the mesh (``walk_y``).
      Otherwise the two can drift apart — Willowbrook carried offset_y −0.75
      from the measurement era, so its village square (a level-0 room) sat
      at −0.75 while level 0 is at 0 and level −1 at −0.8475: the figures
      stood at basement height on a square that has no basement (user
      finding 2026-07-28). With the ground pinned to its level that is not
      expressible any more.

    Where the walkable surface SITS inside the mesh is the admin's ``walk_y``
    dial (real metres above the lower edge, 0 = the lower edge itself) and
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
    walk = _num(meta.get("walk_y")) * k

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
        "url": f"/play/locations/{quote(loc_id)}/model",
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
                   meta: Dict[str, Any], storey: float, k: float,
                   extent: float) -> Optional[Dict[str, Any]]:
    """A room's diorama model as a placement spec (§ B2a).

    ONE law of scale, no exception left (2026-07-28): the diorama scales like
    a prop — its declared real width over its largest XZ side. The room
    RECTANGLE does not influence its size, it stays floor-plan area for
    plate, shell and walkability. The old rectangle fit (``fit_box``) is
    gone; a model without ``width_m`` falls back to the rectangle's real
    width and says so via ``width_estimated`` so the UI can ask for a
    calibration instead of silently scaling by a different law.

    Coexistence (user decision 2026-07-25): the diorama ALWAYS coexists with
    the recipe scene — it is treated like one more prop (placed via model_at,
    calibrated via width_m/walk_y), whether or not the room carries prop
    placements. A room without a diorama simply has no model.
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
    spec: Dict[str, Any] = {
        "role": "room",
        "id": room_id,
        "url": f"/play/rooms/{quote(room_id)}/model",
        "room_id": room_id,
        "level": level,
        "fix_euler": _fix_euler(meta.get("rotation")),
        "yaw_deg": _r(_num(lay.get("rotation")), 1),
        "anchor": [_r(_w(x + _num(at[0], 0.5) * w, extent)),
                   _r(_w(y + _num(at[1], 0.5) * d, extent))],
        # Same floor the room's PROPS stand on: its plate indoors, the room
        # floor outdoors — plus the diorama clearance and the plan's dial.
        "bottom_y": _r(_room_floor_y(recipe, storey, k)
                       + (0.0 if recipe.get("always_visible") else ROOM_PLATE_TOP)
                       + DIORAMA_CLEARANCE
                       + _num(recipe.get("model_offset_y"))),
        "measure": "xz",
    }
    width_m = _num(meta.get("width_m"))
    max_m = width_m * k
    if max_m <= 0:
        # Not calibrated yet: the room rectangle's own world width is the
        # honest stand-in — same number the old rectangle fit produced, but
        # now as a real size the admin can dial at the reference figure.
        max_m = max(w, d) * extent
        spec["width_estimated"] = True
    spec["max_m"] = _r(max_m)
    # Modelled floors (a podium, a sunken lounge, a hole in the mesh) make the
    # standing height unreadable from outside — so the admin states it, in
    # REAL metres above the model's lower edge, dialled against the
    # calibration figure. No measurement fills this in: guessing where a mesh
    # is walkable is an automatic repair, and the contract does not do those.
    # Absent = the room keeps whatever floor the renderer samples.
    if meta.get("walk_y") is not None:
        spec["walk_y_world"] = _r(spec["bottom_y"] + _num(meta["walk_y"]) * k)
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


def _prop_models(recipe: Dict[str, Any], storey: float, k: float,
                 extent: float) -> List[Dict[str, Any]]:
    """The room's prop placements as specs (REAL-SIZE rule, § A2).

    A placement never scales its prop: the size comes from the prop's own
    dims × k. Dangling ids and props without a mesh keep their placement and
    carry ``placeholder_dims`` (already × k) so the consumer can draw a box.
    Furniture stands ON the room plate (plate top + clearance); an outdoor
    room has no plate, so the clearance sits on the storey level directly.
    """
    from urllib.parse import quote
    from app.core import props as prop_store
    level = int(recipe.get("level") or 0)
    room_id = recipe.get("room_id") or ""
    plate_top = 0.0 if recipe.get("always_visible") else ROOM_PLATE_TOP
    floor_y = _room_floor_y(recipe, storey, k) + plate_top + PROP_CLEARANCE
    out: List[Dict[str, Any]] = []
    for placement in recipe.get("placements") or []:
        pid = str(placement.get("prop_id") or "")
        dims_raw = placement.get("dims") or {}
        dims = [_num(dims_raw.get("width_m"), 1.0), _num(dims_raw.get("depth_m"), 1.0),
                _num(dims_raw.get("height_m"), 1.0)]
        at = placement.get("at") or [0.5, 0.5]
        has_model = bool(placement.get("has_model"))
        prop = prop_store.get_prop(pid) if pid else None
        spec: Dict[str, Any] = {
            "role": "prop",
            "id": pid,
            "url": f"/assets/props/{quote(pid)}/model" if has_model else "",
            "room_id": room_id,
            "level": level,
            "fix_euler": _fix_euler((prop or {}).get("rotation")),
            "yaw_deg": _r(_num(placement.get("yaw")), 1),
            "max_m": _r(max(dims) * k),
            "measure": "xyz",
            "anchor": [_r(_w(at[0], extent)), _r(_w(at[1], extent))],
            "bottom_y": _r(floor_y + _num(placement.get("offset_y")) * k),
        }
        if not has_model:
            spec["placeholder_dims"] = {"w": _r(dims[0] * k), "d": _r(dims[1] * k),
                                        "h": _r(dims[2] * k)}
        out.append(spec)
    return out


# ── Markers, exits, figures ─────────────────────────────────────────────

def _markers(recipe: Dict[str, Any], room: Dict[str, Any], storey: float,
             k: float, extent: float) -> List[Dict[str, Any]]:
    """Every marker of one room, finished in world coordinates.

    Room markers are fractions of the room rectangle with an offset additive
    to the sampled floor; prop markers arrive from the recipe as
    placement-relative transforms (fix → real size → yaw already applied) and
    only need ``placement point + [dx, dz] × k`` — the one multiply the
    contract promises the consumer, done here.

    ``y_world`` is the SURFACE the marker names. How far below it a figure's
    root belongs travels with the marker as ``root_offset`` (world metres,
    see FIGURE_ROOT_DROP) — a seated body touches at the buttocks, not at the
    feet. That number used to live in the 3D client alone and only for ROOM
    markers, so prop markers had no drop at all and every author baked one
    into the marker by hand (all 15 in the field carry a negative height).
    One source, both renderers, both marker sources.
    """
    room_id = recipe.get("room_id") or ""
    floor_y = _room_floor_y(recipe, storey, k)
    x, y, w, d = _room_rect(recipe, room)
    figure_h = FIGURE_HEIGHT_M * k

    def _root_drop(animation: Any) -> float:
        """World metres a figure's root sinks below the marked surface."""
        return _r(FIGURE_ROOT_DROP.get(str(animation or "").strip().lower(),
                                       0.0) * figure_h)

    out: List[Dict[str, Any]] = []
    for marker in recipe.get("markers") or []:
        at = marker.get("at") or [0.5, 0.5]
        entry: Dict[str, Any] = {
            "room_id": room_id,
            "at_world": [_r(_w(x + _num(at[0], 0.5) * w, extent)),
                         _r(_w(y + _num(at[1], 0.5) * d, extent))],
            "y_world": _r(floor_y + _num(marker.get("offset_y"))),
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
        entry = {
            "room_id": room_id,
            "at_world": [_r(_w(at[0], extent) + _num(offset[0]) * k),
                         _r(_w(at[1], extent) + _num(offset[1]) * k)],
            "y_world": _r(floor_y + prop_lift + _num(marker.get("height_m")) * k),
            "animation": marker.get("animation") or "",
            "root_offset": _root_drop(marker.get("animation")),
            "source": "prop",
        }
        if marker.get("facing") is not None:
            entry["facing"] = _r(_num(marker.get("facing")), 1)
        out.append(entry)
    return out


def _figures(k: float) -> Dict[str, Any]:
    """Figure scale (§ A3): 1.70 m × k — no legacy branch left. Unanchored
    locations run at k = 1, where "real metres × k" IS world metres, so the
    old ``1.7 × storey / 3`` proxy would double-scale. The stand clearance
    stays a world-metre CONSTANT, never × k."""
    return {"base_height_m_world": _r(FIGURE_HEIGHT_M * k),
            "stand_clearance": STAND_CLEARANCE}


def _signature(location: Dict[str, Any], plan_width_m: float,
               recipes: List[Dict[str, Any]], building_meta: Dict[str, Any],
               room_metas: Dict[str, Dict[str, Any]]) -> str:
    """Change detection for the whole scene — a SUPERSET of the room recipe's
    signature: the room signatures already cover layouts, neighbour openings
    and prop sidecars, and the model metas add every anchor dial (floors,
    height_m, width_m, walk_y, rotation, offsets). Polling it is enough."""
    import hashlib
    import json
    payload = {
        "map3d": location.get("map3d") or {},
        "map_rotation_2d": location.get("map_rotation_2d") or 0,
        "plan_width_m": round(float(plan_width_m or 0), 3),
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
    metres — where a road enters and leaves the cell. Geometry + room link
    only: the entry-room gate is untouched, and no renderer consumes them
    yet (the journey walk-through is a later stage; the data is complete —
    an opening pair plus the linked room's hull is a path across the cell).
    """
    out: List[Dict[str, Any]] = []
    for op in (map3d or {}).get("boundary_openings") or []:
        if not isinstance(op, dict):
            continue
        spec = _BOUNDARY_EDGES.get(str(op.get("edge") or "").upper())
        if not spec:
            continue
        try:
            at = float(op.get("at") or 0)
            width_m = float(op.get("width_m") or 0)
        except (TypeError, ValueError):
            continue
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


def compose_scene(location: Dict[str, Any], *, plan_width_m: float = 0.0,
                  building_meta: Optional[Dict[str, Any]] = None,
                  room_metas: Optional[Dict[str, Dict[str, Any]]] = None,
                  ) -> Dict[str, Any]:
    """The whole scene of ONE location as finished primitives (§ B1).

    ``plan_width_m`` is the resolved scale anchor (see
    ``location_model3d.derive_plan_width_m``), ``building_meta`` the building
    model's client meta and ``room_metas`` the room models' client metas by
    room id — the route loads all three, the composer only computes.
    """
    map3d = location.get("map3d") or {}
    rooms = [r for r in (location.get("rooms") or []) if isinstance(r, dict)]
    building_meta = building_meta or {}
    room_metas = room_metas or {}
    extent, k, storey = derive_scalars(map3d, plan_width_m)

    recipes: List[Dict[str, Any]] = []
    by_room: Dict[str, Dict[str, Any]] = {}
    for room in rooms:
        recipe = compose_recipe(room, [r for r in rooms if r is not room],
                               plan_width_m)
        if not recipe:
            continue
        recipes.append(recipe)
        by_room[str(room.get("id") or "")] = room
    levels = _used_levels(recipes)

    exits: List[Dict[str, Any]] = []
    for recipe in recipes:
        room = by_room.get(str(recipe.get("room_id") or ""))
        point = room_exit_world(recipe, room, extent) if room else None
        if not point:
            continue
        entry = {"room_id": recipe.get("room_id") or "", "at_world": point}
        if recipe.get("exit_derived"):
            entry["derived"] = True
        exits.append(entry)

    # Ground-floor exits feed the contour's door gaps — the DERIVED exits
    # count too (a room with a door is never walled in).
    ground_exits = [e["at_world"] for e in exits
                    if int((by_room.get(e["room_id"], {}).get("layout")
                            or {}).get("level") or 0) == 0]

    # Indoor room hulls per level, world metres — where they run on the
    # contour line, the contour wall yields (one wall, one owner).
    room_hulls: Dict[int, List[List[List[float]]]] = {}
    for recipe in recipes:
        # A room that emits no walls of its own cannot own a contour stretch
        # either — letting the contour yield to it would leave a gap with no
        # wall at all instead of one wall with one owner.
        if recipe.get("always_visible") or recipe.get("no_walls"):
            continue
        hull = _room_outline_world(recipe, extent)
        if hull:
            room_hulls.setdefault(int(recipe.get("level") or 0), []).append(hull)

    walls: List[Dict[str, Any]] = _contour_walls(map3d, levels, storey, extent,
                                                 ground_exits, room_hulls)
    models: List[Dict[str, Any]] = []
    markers: List[Dict[str, Any]] = []
    building = _building_model(location, map3d, building_meta, k, extent)
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
            y += _num(recipe.get("floor_offset_y")) * k
            overlay_rooms[str(recipe.get("room_id") or "")] = {
                "centre": [_r(cx), _r(cz)],
                "rect": {"x": _r(cx), "z": _r(cz),
                         "w": _r(max(max(xs) - min(xs), 0.5)),
                         "d": _r(max(max(zs) - min(zs), 0.5))},
                "y": _r(y),
            }
    for recipe in recipes:
        room_id = str(recipe.get("room_id") or "")
        room = by_room.get(room_id) or {}
        walls.extend(_room_walls(recipe, storey, k, extent, min(levels)))
        diorama = _diorama_model(recipe, room, room_metas.get(room_id) or {},
                                 storey, k, extent)
        if diorama:
            models.append(diorama)
        models.extend(_prop_models(recipe, storey, k, extent))
        markers.extend(_markers(recipe, room, storey, k, extent))

    # Per-room recipe vocabulary in PLAN FRACTIONS — the 2D editor's ghost
    # openings and derived-exit dot draw from here instead of re-deriving
    # mirroring/exit locally (v4: no geometry twice). Pure pass-through of
    # the room recipe: openings are already normalized AND mirrored in,
    # ``exit`` keeps the recipe's dual frame (explicit = room-rect fraction,
    # derived = absolute plate fraction, flagged by ``exit_derived``).
    room_blocks = []
    for r in recipes:
        block: Dict[str, Any] = {
            "room_id": r.get("room_id") or "",
            "level": int(r.get("level") or 0),
            "always_visible": bool(r.get("always_visible")),
            "outline": r.get("outline") or [],
            "openings": r.get("openings") or [],
            "exit": r.get("exit"),
            "exit_derived": bool(r.get("exit_derived")),
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
                                building_meta, room_metas),
        "rooms": room_blocks,
        # extent_m = the world size of the reference square: the ONE number
        # that turns every fraction in this payload into metres. Consumers
        # must read it instead of assuming a constant (they used to assume 8).
        "extent_m": _r(extent),
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
                           levels, storey, k, extent)
                   + _overlay_plates(recipes, overlay_rooms, min(levels), extent)),
        "walls": walls,
        "extras": _elevator(map3d, levels, storey, k, extent),
        "models": models,
        "figures": _figures(k),
        "markers": markers,
        "exits": exits,
        "outdoor_rooms": [r.get("room_id") or "" for r in recipes
                          if r.get("always_visible")],
    }
    if boundary:
        out["boundary_openings"] = boundary
    return out
