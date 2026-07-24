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
(§ A2/A3/A6). When code and contract disagree, the CONTRACT wins.

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
# The reference square is 8 × 8 world metres, the map tile 10 × 10.
PLATE_M = 8.0
TILE_M = 10.0
# Storey height when neither the building meta nor map3d.level_height says.
DEFAULT_STOREY_M = 3.0
# Level plate: extruded downward, top at level × storey + 0.08, 0.14 thick.
LEVEL_PLATE_TOP = 0.08
LEVEL_PLATE_THICKNESS = 0.14
# Room floor plate: sits ABOVE the level plate (it overrides only its own
# area). The top offset is the preview's value; the body is deliberately
# thin — thickness 0 is RESERVED for "texture only, no geometry" (§ A5).
ROOM_PLATE_TOP = 0.04
ROOM_PLATE_THICKNESS = 0.02
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
# Buildings: tile fit leaves a 0.92 margin, the shell stands at 0.06.
TILE_FILL = 0.92
BUILDING_BOTTOM_Y = 0.06
# Figures (§ A3): 1.70 m at the plan scale; the clearance is a world-metre
# CONSTANT (never × k).
FIGURE_HEIGHT_M = 1.70
STAND_CLEARANCE = 0.12
# Room dioramas stand a clearance above their storey floor (§ A2).
DIORAMA_CLEARANCE = 0.12
# The floor kind of a level plate without its own entry in map3d.level_floors.
DEFAULT_FLOOR_KIND = "floor"

# The renderers' colour vocabulary — ONE place for both of them (§ B1 style).
STYLE: Dict[str, Any] = {
    "wall_color": "#cfc4b2",
    "floor_color": "#d8d0c2",
    "glass_color": "#9fc2d8",
    "glass_opacity": 0.25,
    "upper_wall_opacity": 0.45,
    "upper_floor_opacity": 0.4,
    "room_palette": ["#58a6ff", "#3fb950", "#d29922", "#f778ba",
                     "#a371f7", "#f85149", "#79c0ff", "#56d364"],
}


def _r(v: float, nd: int = 4) -> float:
    out = round(float(v), nd)
    return out if out != 0 else 0.0  # never -0.0 in payloads


def _w(frac: Any) -> float:
    """Reference-square fraction → world metre (origin = tile centre)."""
    try:
        return (float(frac) - 0.5) * PLATE_M
    except (TypeError, ValueError):
        return 0.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opacity_role(level: int) -> str:
    """Ground floor is opaque, every other storey is ghosted (§ A6)."""
    return "ground" if level == 0 else "upper"


def derive_scalars(map3d: Dict[str, Any], plan_width_m: float,
                   building_meta: Dict[str, Any]) -> Tuple[float, float]:
    """(k, storey_m) — the two scalars everything else derives from (§ A1).

    ``k`` = world metres per real metre = 8 / plan_width_m; without a scale
    anchor the location runs in LEGACY mode (k = 1, storey from
    ``map3d.level_height``). ``storey_m`` = height_m / floors × k when the
    building model declares both, else level_height, else 3.
    """
    k = PLATE_M / plan_width_m if plan_width_m > 0 else 1.0
    floors = _num((building_meta or {}).get("floors"))
    height = _num((building_meta or {}).get("height_m"))
    if floors > 0 and height > 0:
        storey = height / floors * k
    else:
        storey = _num((map3d or {}).get("level_height")) or DEFAULT_STOREY_M
    return k, storey


def _used_levels(recipes: List[Dict[str, Any]]) -> List[int]:
    """The levels the layout rooms occupy, ascending; [0] when there are
    none (a location may be nothing but a contour)."""
    levels = sorted({int(r.get("level") or 0) for r in recipes})
    return levels or [0]


def _outline_world(map3d: Dict[str, Any]) -> List[List[float]]:
    """``map3d.outline`` in world metres, or [] when there is no polygon."""
    pts = (map3d or {}).get("outline")
    if not isinstance(pts, list) or len(pts) < 3:
        return []
    out: List[List[float]] = []
    for pt in pts:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return []
        out.append([_r(_w(pt[0])), _r(_w(pt[1]))])
    return out


def _room_rect(recipe: Dict[str, Any], room: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """The room's placed rectangle (x, y, w, d) in plate fractions."""
    lay = room.get("layout") or {}
    return (_num(lay.get("x")), _num(lay.get("y")),
            _num(lay.get("w"), 1.0), _num(lay.get("d"), 1.0))


def room_exit_world(recipe: Dict[str, Any],
                    room: Dict[str, Any]) -> Optional[List[float]]:
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
        return [_r(_w(ex)), _r(_w(ey))]
    x, y, w, d = _room_rect(recipe, room)
    return [_r(_w(x + ex * w)), _r(_w(y + ey * d))]


# ── Plates ──────────────────────────────────────────────────────────────

def _plates(map3d: Dict[str, Any], recipes: List[Dict[str, Any]],
            levels: List[int], storey: float) -> List[Dict[str, Any]]:
    """One contour plate per used level + one floor plate per room.

    The level plate carries the storey's floor kind (``map3d.level_floors``,
    else the global ``floor`` kind); the rooms lay their own plates ON TOP,
    so a room floor overrides only its own area. Outdoor rooms (§ A5) get NO
    body — they appear as a plate of thickness 0, i.e. a pure texture surface
    on the ground below.
    """
    plates: List[Dict[str, Any]] = []
    contour = _outline_world(map3d)
    level_floors = (map3d or {}).get("level_floors") or {}
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
                "opacity_role": _opacity_role(level),
            })
    for recipe in recipes:
        level = int(recipe.get("level") or 0)
        outdoor = bool(recipe.get("always_visible"))
        outline = [[_r(_w(p[0])), _r(_w(p[1]))] for p in recipe.get("outline") or []]
        if len(outline) < 3:
            continue
        entry: Dict[str, Any] = {
            "level": level,
            "outline": outline,
            "top_y": _r(level * storey + (0.0 if outdoor else ROOM_PLATE_TOP)),
            "thickness": 0.0 if outdoor else ROOM_PLATE_THICKNESS,
            "opacity_role": _opacity_role(level),
            "room_id": recipe.get("room_id") or "",
        }
        kind = str(((recipe.get("surfaces") or {}).get("floor")) or "").strip()
        if kind:
            entry["texture_kind"] = kind
        plates.append(entry)
    return plates


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


def _contour_walls(map3d: Dict[str, Any], levels: List[int], storey: float,
                   exits: List[List[float]]) -> List[Dict[str, Any]]:
    """The building contour as walls, per used level (§ A6).

    The ground floor gets a door gap wherever a room exit projects onto the
    contour closer than 0.45 m; without a single such exit ONE central door
    is punched into the southernmost wall piece, so a building is never
    sealed shut.
    """
    pts = _outline_world(map3d)
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
            segs = _subtract([(0.0, length)],
                             holes if level == 0 else [], MIN_WALL_PIECE_M)
            for s0, s1 in segs:
                start, end = _segment_points(a, ux, uz, s0, s1)
                walls.append({
                    "level": level,
                    "from": start,
                    "to": end,
                    "base_y": _r(level * storey + LEVEL_PLATE_TOP),
                    "height": _r(height),
                    "thickness": WALL_THICKNESS,
                    "opacity_role": _opacity_role(level),
                    "outward_normal": [_r(nx), _r(nz)],
                })
    return walls


def _room_walls(recipe: Dict[str, Any], storey: float,
                k: float) -> List[Dict[str, Any]]:
    """One room's shell walls, split around its openings (§ A4).

    Doors and passages leave a full-height gap; a window keeps a sill segment
    below and a head segment above and fills the hole with a glass segment.
    Mirrored openings (the neighbour's door in the shared wall) arrive
    pre-translated in the recipe and are treated exactly like own ones.
    Outdoor rooms have no shell at all (§ A5).
    """
    if recipe.get("always_visible"):
        return []
    outline = [[_w(p[0]), _w(p[1])] for p in recipe.get("outline") or []]
    if len(outline) < 3:
        return []
    level = int(recipe.get("level") or 0)
    base = level * storey + LEVEL_PLATE_TOP
    height = _wall_height(storey)
    kind = str(((recipe.get("surfaces") or {}).get("wall")) or "").strip()
    room_id = recipe.get("room_id") or ""
    role = _opacity_role(level)
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
              k: float) -> List[Dict[str, Any]]:
    """The elevator of a building: shaft columns + roof, glass on three sides
    (the side facing the building centre stays open), a pad per level and a
    static cabin on the ground floor (§ A6). All sizes are real metres × k.
    """
    pos = (map3d or {}).get("elevator")
    if not isinstance(pos, (list, tuple)) or len(pos) != 2:
        return []
    ex, ez = _w(pos[0]), _w(pos[1])
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
    """The orientation fix as an 'XYZ' Euler in degrees (§ A1)."""
    rot = rotation if isinstance(rotation, dict) else {}
    return {axis: _r(_num(rot.get(axis)), 3) for axis in ("x", "y", "z")}


def _building_yaw(location: Dict[str, Any], map3d: Dict[str, Any]) -> float:
    """Yaw chain (§ A1): map3d.rotation (an explicit 0 counts) →
    map_rotation_2d → 0."""
    if (map3d or {}).get("rotation") is not None:
        return _num(map3d.get("rotation"))
    return _num(location.get("map_rotation_2d"))


def _building_model(location: Dict[str, Any], map3d: Dict[str, Any],
                    meta: Dict[str, Any], k: float) -> Optional[Dict[str, Any]]:
    """The building shell as a ``tile_fit`` spec (§ A2/B2).

    The footprint always follows the tile (largest XZ side = 10 × 0.92 ×
    map3d.size) so the floor plan lands on the shell; the height follows
    ``height_m × k`` when the model declares it — with correct proportions
    both factors coincide, a too-flat relief gets exactly the repair it needs.
    """
    if not meta:
        return None
    from urllib.parse import quote
    loc_id = str(location.get("id") or "")
    size = _num((map3d or {}).get("size")) or TILE_FILL
    height_m = _num(meta.get("height_m"))
    box: Dict[str, float] = {"xz": _r(TILE_M * TILE_FILL * size)}
    if height_m > 0:
        box["y"] = _r(height_m * k)
    return {
        "role": "building",
        "id": loc_id,
        "url": f"/play/locations/{quote(loc_id)}/model",
        "level": 0,
        "fix_euler": _fix_euler(meta.get("rotation")),
        "yaw_deg": _r(_building_yaw(location, map3d), 1),
        "scale_mode": "tile_fit",
        "box": box,
        "anchor": [_r(_num(meta.get("offset_x"))), _r(_num(meta.get("offset_z")))],
        "bottom_y": _r(BUILDING_BOTTOM_Y + _num(meta.get("offset_y"))),
    }


def _diorama_model(recipe: Dict[str, Any], room: Dict[str, Any],
                   meta: Dict[str, Any], storey: float, k: float,
                   anchored: bool) -> Optional[Dict[str, Any]]:
    """A room's diorama model as a placement spec (§ B2a).

    ONE law of scale: with a scale anchor AND a declared ``width_m`` the
    diorama scales like a prop (real size over its largest XZ side) — the
    room RECTANGLE no longer influences its size at all, it stays floor-plan
    area for plate, shell and walkability. Without either, the documented
    fallback is the old rectangle fit.

    Coexistence rule: a room whose recipe carries prop placements is
    furnished from the recipe and gets NO diorama.
    """
    if not meta or recipe.get("placements"):
        return None
    from urllib.parse import quote
    lay = room.get("layout") or {}
    room_id = str(room.get("id") or "")
    level = int(recipe.get("level") or 0)
    x, y, w, d = _room_rect(recipe, room)
    at = lay.get("model_at")
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
        "anchor": [_r(_w(x + _num(at[0], 0.5) * w)),
                   _r(_w(y + _num(at[1], 0.5) * d))],
        "bottom_y": _r(level * storey + DIORAMA_CLEARANCE
                       + _num(lay.get("model_offset_y"))),
    }
    # Modelled floors (podium, sunken lounge, a hole in the mesh) make the
    # standing height unmeasurable from outside — the admin dials walk_y once
    # per model, in world metres above the diorama's lower edge, and the
    # consumer gets the absolute height (§ B6 no. 7).
    if meta.get("walk_y") is not None:
        spec["walk_y_world"] = _r(spec["bottom_y"] + _num(meta.get("walk_y")))
    width_m = _num(meta.get("width_m"))
    if anchored and width_m > 0:
        spec["scale_mode"] = "real_size"
        spec["max_m"] = _r(width_m * k)
        spec["measure_axes"] = "xz"
    else:
        spec["scale_mode"] = "fit_box"
        spec["box"] = {"w": _r(w * PLATE_M), "d": _r(d * PLATE_M)}
    return spec


def _prop_models(recipe: Dict[str, Any], storey: float,
                 k: float) -> List[Dict[str, Any]]:
    """The room's prop placements as specs (REAL-SIZE rule, § A2).

    A placement never scales its prop: the size comes from the prop's own
    dims × k. Dangling ids and props without a mesh keep their placement and
    carry ``placeholder_dims`` (already × k) so the consumer can draw a box.
    """
    from urllib.parse import quote
    from app.core import props as prop_store
    level = int(recipe.get("level") or 0)
    room_id = recipe.get("room_id") or ""
    floor_y = level * storey
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
            "scale_mode": "real_size",
            "max_m": _r(max(dims) * k),
            "anchor": [_r(_w(at[0])), _r(_w(at[1]))],
            "bottom_y": _r(floor_y + _num(placement.get("offset_y")) * k),
        }
        if not has_model:
            spec["placeholder_dims"] = {"w": _r(dims[0] * k), "d": _r(dims[1] * k),
                                        "h": _r(dims[2] * k)}
        out.append(spec)
    return out


# ── Markers, exits, figures ─────────────────────────────────────────────

def _markers(recipe: Dict[str, Any], room: Dict[str, Any], storey: float,
             k: float) -> List[Dict[str, Any]]:
    """Every marker of one room, finished in world coordinates.

    Room markers are fractions of the room rectangle with an offset additive
    to the sampled floor; prop markers arrive from the recipe as
    placement-relative transforms (fix → real size → yaw already applied) and
    only need ``placement point + [dx, dz] × k`` — the one multiply the
    contract promises the consumer, done here.
    """
    room_id = recipe.get("room_id") or ""
    level = int(recipe.get("level") or 0)
    floor_y = level * storey
    x, y, w, d = _room_rect(recipe, room)
    out: List[Dict[str, Any]] = []
    for marker in recipe.get("markers") or []:
        at = marker.get("at") or [0.5, 0.5]
        entry: Dict[str, Any] = {
            "room_id": room_id,
            "at_world": [_r(_w(x + _num(at[0], 0.5) * w)),
                         _r(_w(y + _num(at[1], 0.5) * d))],
            "y_world": _r(floor_y + _num(marker.get("offset_y"))),
            "animation": marker.get("animation") or "",
            "source": "room",
        }
        if marker.get("rotation") is not None:
            entry["facing"] = _r(_num(marker.get("rotation")), 1)
        out.append(entry)
    placements = recipe.get("placements") or []
    for marker in recipe.get("prop_markers") or []:
        try:
            placement = placements[int(marker.get("placement"))]
        except (TypeError, ValueError, IndexError):
            continue
        at = placement.get("at") or [0.5, 0.5]
        offset = marker.get("offset_m") or [0.0, 0.0]
        entry = {
            "room_id": room_id,
            "at_world": [_r(_w(at[0]) + _num(offset[0]) * k),
                         _r(_w(at[1]) + _num(offset[1]) * k)],
            "y_world": _r(floor_y + _num(marker.get("height_m")) * k),
            "animation": marker.get("animation") or "",
            "source": "prop",
        }
        if marker.get("facing") is not None:
            entry["facing"] = _r(_num(marker.get("facing")), 1)
        out.append(entry)
    return out


def _figures(storey: float, k: float, anchored: bool) -> Dict[str, Any]:
    """Figure scale (§ A3): 1.70 m × k, legacy 1.7 × storey / 3. The stand
    clearance is a world-metre CONSTANT — never × k."""
    base = FIGURE_HEIGHT_M * k if anchored else FIGURE_HEIGHT_M * storey / 3
    return {"base_height_m_world": _r(base),
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
    k, storey = derive_scalars(map3d, plan_width_m, building_meta)
    anchored = plan_width_m > 0

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
        point = room_exit_world(recipe, room) if room else None
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

    walls: List[Dict[str, Any]] = _contour_walls(map3d, levels, storey,
                                                 ground_exits)
    models: List[Dict[str, Any]] = []
    markers: List[Dict[str, Any]] = []
    building = _building_model(location, map3d, building_meta, k)
    if building:
        models.append(building)
    for recipe in recipes:
        room_id = str(recipe.get("room_id") or "")
        room = by_room.get(room_id) or {}
        walls.extend(_room_walls(recipe, storey, k))
        diorama = _diorama_model(recipe, room, room_metas.get(room_id) or {},
                                 storey, k, anchored)
        if diorama:
            models.append(diorama)
        models.extend(_prop_models(recipe, storey, k))
        markers.extend(_markers(recipe, room, storey, k))

    return {
        "signature": _signature(location, plan_width_m, recipes,
                                building_meta, room_metas),
        "k": _r(k, 6),
        "storey_m": _r(storey),
        "levels": [{"level": lv, "floor_y": _r(lv * storey)} for lv in levels],
        "style": STYLE,
        "plates": _plates(map3d, recipes, levels, storey),
        "walls": walls,
        "extras": _elevator(map3d, levels, storey, k),
        "models": models,
        "figures": _figures(storey, k, anchored),
        "markers": markers,
        "exits": exits,
        "outdoor_rooms": [r.get("room_id") or "" for r in recipes
                          if r.get("always_visible")],
    }
