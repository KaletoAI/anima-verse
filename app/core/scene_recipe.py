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

What the composer emits (world coordinates throughout, ORIGIN = the
location's ANCHOR PIN — the consumer places the scene at the location's map
point; since v6 Nr. 2 that is also the frame every plan coordinate is STORED
in, so nothing is denormalized here):

- ``boundary`` — the location's footprint as a polygon in the scene frame
                (contract v6: the drawn outline, or the synthesized square of
                edge ``extent_m`` as its four corners),
- ``plates``  — the floors of the storeys ABOVE AND BELOW the ground: one
                contour plate per such level plus one floor plate per room on
                it. **Storey 0 has none** since "Ein Boden" E5a — the terrain
                IS the floor there, its material is the layer bake
                (``core.terrain_layers``) and its height is ``h_final``,
- ``floor_plan`` — the storey-0 rooms as polygons + floor kinds, so a consumer
                can place room spots and NPC stands without a plate to raycast
                against (E5a),
- ``walls``   — the building contour with its door gaps and the room shell
                walls already split around every opening. EVERY opening is
                cut the same way: a piece below it (a window's sill band), a
                LINTEL above it up to the top of the wall, and a PANE in the
                hole itself — glass for a window, a dark DOOR LEAF for a door.
                A door is a hole, not a slot up to the ceiling,
- ``extras``  — the elevator primitives,
- ``style``   — the colours/opacities both renderers used to keep as copies,
- ``models``  — ONE spec form for building, room diorama and prop; the client
                runs the single ``place()`` routine of § B2 over it,
- ``figures``/``markers`` — the figure scale and every anchor point already
                resolved into world coordinates.

Numbers are NOT free here: every constant below is quoted from the contract
(``docs/schnittstellen-3d.md``, § A2/A3/A6 for the values, part B for the
payload shape) — that document, not this file, is where a value is changed.
When code and contract disagree, the CONTRACT wins.

The composer is pure: location dict + rooms in, primitives out. Loading
(world DB, model sidecars, scale anchor) is the route's job; the prop library
is read through ``room_recipe`` exactly as the room recipe does it.
"""

import math
from typing import (Any, Dict, Iterator, List, Optional, Sequence, Set,
                    Tuple)

from app.core.log import get_logger
from app.core.model_store import DEFAULT_TIER, variant_urls
from app.core.room_recipe import (SHARE_TOL_M, _WALKABLE_TYPES,
                                  compose_recipe, layout_rotation,
                                  room_transform)

logger = get_logger(__name__)

#: Code version of the scene geometry, mixed into :func:`_signature`.
#: Bump whenever the code that derives this payload changes its output for
#: unchanged data — otherwise the signature stays put after a pure code change
#: and every client keeps serving the old geometry until someone happens to
#: save the location.
#: 2 (2026-08-25): every opening keeps a LINTEL over it — a door no longer
#: reaches the top of the wall, and the hole it projects into the building
#: contour ends at the door's own height too.
#: 3 (2026-08-25): a door hole is filled by a DOOR LEAF — a thin dark plate
#: over its clear opening, the door's answer to a window's glass pane, so an
#: exterior door is visible as a door from outside.
#: 4 (2026-08-25): STAIRS — ``map3d.stairs`` becomes a flight of solid
#: ``stair_step`` boxes plus a ``stair_pad`` at each end, so a storey can be
#: reached on foot and the elevator is only the fallback.
#: 5 (2026-08-27): DOOR PROPS — a door opening may be filled by a PROP
#: instead of the flat leaf: a ``models[]`` spec with ``measure "fit"``,
#: hung on its HINGE edge so a renderer can swing it. The leaf wall stays in
#: ``walls[]`` (the Blender exterior render reads that list) and merely says
#: ``door_prop`` so the renderers skip drawing it.
#: 6 (2026-08-27): BAKED MODEL SURFACES (spec-surface-height) — a diorama and
#: a prop tagged ``walkable`` carry the height lattice their mesh was baked
#: into (``surface``, plus ``walkable`` on the prop), so a figure stands on
#: the rock the model shows instead of on the land under it.
SCENE_RECIPE_VERSION = 7

# ── Contract constants (§ A2/A3/A6) ─────────────────────────────────────
# THERE IS NO REFERENCE SQUARE ANY MORE (contract v6 Nr. 2, the metric wave):
# every plan coordinate is stored in local metres, so nothing is denormalized
# on the way into this payload. What survives of the square is ``extent_m`` —
# the width of the location's bounding box (``map3d.plan_width_m``, derived
# from the drawn boundary) — as the box the location model fills, the edge of
# the terrain frame and the loading/viewport number the consumer contracts
# quote. One world metre IS one real metre everywhere (k = 1).
# The fallback edge for a location without a boundary of its own.
DEFAULT_EXTENT_M = 10.0
# Storey height in metres when the location does not declare one.
DEFAULT_STOREY_REAL_M = 3.0
# Level plate of a DECLARED STOREY (level != 0): extruded downward, top at
# level × storey + 0.08, 0.14 thick.
#
# STOREY 0 HAS NO PLATE SINCE "Ein Boden" E5a. Its floor is the world terrain:
# the height is ``h_final`` (stamped flat under a built location, § G5) and the
# material is the layer bake (§ G3). These two numbers are therefore the datum
# of an UPPER STOREY and of a BASEMENT, nowhere else — every L0 occurrence of
# 0.08/0.09/0.10 is gone, and ``scripts/smoke_scene_recipe.py`` keeps red
# counter-probes that say so.
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
# How far BELOW a marked surface a figure's root goes is a property of the
# PLACE TYPE the marker names — ``pose_catalog.get_groups()[group]["root_drop"]``
# × figure height (the measured numbers and their derivation sit at ``groups``
# in the catalog file). ONE source for the payload's ``root_offset`` and for
# every renderer alike; no viewer measures a pose to decide the height
# (finding 2026-08-21). A group without a drop touches at its root.
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
# THE SKIRT OF A STOREY-0 WALL (§ A16.9, finding round 2026-08-21).
#
# A wall foot is a straight HORIZONTAL line at the storey floor; the ground
# under it is not straight. Until E5a that never showed, because storey 0 had
# a plate and the foot was EMBEDDED in its body: a room wall based at
# ``ROOM_PLATE_TOP`` 0.10 and a contour wall at ``LEVEL_PLATE_TOP`` 0.08, both
# over a level plate whose body reached down to 0.08 − 0.14 = −0.06. The plate
# is gone, the foot now meets the bare terrain, and every millimetre the ground
# drops away under the wall opens a lit gap.
#
# So the wall keeps the skirt the plate used to give it: it starts
# ``WALL_SINK_M`` BELOW the floor line and its top stays put (the height grows
# by the same amount), which makes this change invisible from above and a
# no-op for every consumer that reads ``base_y + height``.
#
# THE NUMBER, derived from the contract rather than picked:
#   * it must beat the plateau ramp. A built plot is stamped flat (§ A16.4),
#     but a wall's OUTER FACE lies WALL_THICKNESS/2 = 0.035 m outside the hull
#     the stamp follows, and just outside the plot the ground may fall at the
#     full ``max_slope_deg`` = 40°: 0.035 · tan 40° = 0.029 m. That is the
#     floor of the requirement.
#   * it must not be visible from the storey BELOW a declared one. There the
#     wall still stands on a plate, and the deepest foot is the contour wall's
#     ``LEVEL_PLATE_TOP`` 0.08 over a plate body that ends at −0.06 — 0.14 m
#     of solid material under it. That is the ceiling of the requirement.
# 0.14 is that ceiling exactly: the skirt is the LEVEL PLATE'S BODY, i.e. the
# precise depth of material a wall foot stood in before E5a. A declared storey
# therefore does not move by a millimetre in appearance (the skirt hides in the
# plate it was always inside), and storey 0 gets the same solidity from the
# terrain. Against the 0.029 m ramp case it carries a 4.8× margin.
WALL_SINK_M = LEVEL_PLATE_THICKNESS
WALL_MIN_HEIGHT = 0.6
WALL_HEAD_ROOM = 0.15
# A PANE — the thing that fills a hole rather than framing it — is this
# fraction of the wall's thickness. Two of them exist: a window's glass band
# and a door's LEAF (2026-08-25). Both sit in the hole the splitter left, so
# both are thinner than the reveal around them and neither is a wall.
PANE_THICKNESS_FACTOR = 0.6
# Two wall faces count as ONE wall line when their directions are (anti)parallel
# within ~1° — the same slack ``room_recipe._mirrored_openings`` uses.
_WALL_PARALLEL = 0.98
# Contour wall pieces below 0.06 m are dropped (the gap a door leaves is the
# door's own clear width — there is no constant for it any more, § 4.2).
MIN_WALL_PIECE_M = 0.06
# Anything shorter/lower than this is not worth a primitive.
MIN_SEGMENT_M = 0.02
# Two openings whose CLAMPED spans agree this closely on the same wall edge are
# the same hole (a mirrored party-wall door beside the room's own, the same
# opening entered twice). A centimetre is orders of magnitude above the 4
# decimals a mirrored ``at`` is rounded to and orders of magnitude below any
# gap an author can mean.
_SAME_SPAN_M = 0.01
# Elevator (§ A6) — metres.
ELEVATOR_SHAFT_M = 1.8
ELEVATOR_COLUMN_M = 0.14
ELEVATOR_PAD_M = 1.6
ELEVATOR_CABIN_M = 1.4
ELEVATOR_CABIN_STOREY_FRAC = 0.6
ELEVATOR_ROOF_THICKNESS = 0.05
ELEVATOR_PAD_THICKNESS = 0.05
ELEVATOR_GLASS_THICKNESS = 0.03
# Stairs (§ A6) — metres. A flight connects ONE storey to the one above it;
# where a flight exists it wins over the elevator, which stays the fallback.
STAIR_WIDTH_M = 1.2      # step width across the climb direction
STAIR_TREAD_M = 0.26     # run per step along the climb direction
STAIR_RISE_M = 0.20      # nominal rise; the real rise divides the climb evenly
STAIR_PAD_M = 0.9        # trigger pad edge (marker only, like ELEVATOR_PAD_M)
STAIR_PAD_THICKNESS = 0.05
# Clearance between a pad's edge and the first/last tread, so the marker never
# overlaps the flight it belongs to.
STAIR_PAD_GAP_M = 0.05
# How many flights one location may carry. Beyond this an author is drawing
# something other than a building; the sanitizer caps the stored list at the
# same number.
STAIR_MAX = 8
# The four legal climb directions as (x, z) unit vectors — an author names the
# ANGLE, the vector is fixed here so no consumer trigonometries it back out.
_STAIR_DIRS: Dict[int, Tuple[float, float]] = {
    0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0), 270: (-1.0, 0.0),
}
#: The legal angles as data, for whoever validates an author's entry — the
#: sanitizer reads THIS instead of writing the four numbers down a second time.
STAIR_DIRS_DEG: Tuple[int, ...] = tuple(sorted(_STAIR_DIRS))
# A building SHELL is anchored at its WALKABLE SURFACE, exactly like a GROUND
# model — the surface lands on the storey-0 floor (``LEVEL_PLATE_TOP``) and the
# mesh hangs below it. The old free-standing socle clearance (0.06 over the
# tile floor, ``BUILDING_BOTTOM_Y``) is gone with it: it pinned the mesh's
# LOWER EDGE, which is the model's floor only for a mesh without a ground pad —
# see ``_building_model`` and the § B2 addendum of 2026-08-20.
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
# An outdoor zone ON A DECLARED STOREY (a roof terrace) lies this far above
# that storey's level plate — coplanar with it they would z-fight. On storey 0
# it has no consumer any more: a zone there is a LAYER of the ground bake, not
# a surface laid over a slab (E5a).
OVERLAY_SURFACE_LIFT = 0.01
# The floor kind of a level plate without its own entry in map3d.level_floors —
# and of a CLOSED room that names none (``core.terrain_layers``' twin
# constant, which is what puts parquet rather than grass under the furniture).
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
    # The DOOR LEAF (2026-08-25): opaque, dark, neutral wood — a door has to
    # read as a door against ``wall_color`` from a hundred metres away, and it
    # is the ONE colour both renderers take for a ``leaf`` piece.
    "door_color": "#4a3a2e",
    "upper_wall_opacity": 0.45,
    "upper_floor_opacity": 0.4,
    "room_palette": ["#58a6ff", "#3fb950", "#d29922", "#f778ba",
                     "#a371f7", "#f85149", "#79c0ff", "#56d364"],
    "elevator_frame_color": "#6d7681",
    "elevator_pad_color": "#aab4be",
    "elevator_cabin_color": "#3d4650",
    "elevator_cabin_opacity": 0.85,
    "elevator_glass_opacity": 0.22,
    # A staircase is masonry, not machinery: warm stone rather than the
    # elevator's cold grey, so the two vertical connections read apart at a
    # glance.
    "stair_color": "#8a7a66",
}


def _r(v: float, nd: int = 4) -> float:
    out = round(float(v), nd)
    return out if out != 0 else 0.0  # never -0.0 in payloads


def _room_outline_world(recipe: Dict[str, Any]) -> List[List[float]]:
    """The room shell in world metres — the ONE source for the room's floor
    plate and for a diorama's ``clip_outline`` (§ B1); [] when degenerate.

    Since v6 (Nr. 2) this is a PARSE, not a transform: ``compose_recipe``
    already delivers absolute local metres, and the scene frame IS the
    location's local frame."""
    pts = [[_r(_num(p[0])), _r(_num(p[1]))]
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
    """(extent_m, k, storey_m) — the three scalars the payload quotes.

    **k = 1 since E4** (2026-08-09) and since v6 (Nr. 2) nothing is derived
    from ``extent_m`` at all: it IS ``plan_width_m``, the width of the
    location's bounding box, and it is carried rather than applied. One world
    metre is one real metre — inside the scene exactly as on the map
    (§ A1.1). ``map3d.extent_m``, the world-metre dial of the tile era, is not
    read any more (the field may still sit in old blobs; nothing
    reads it, and the sanitizer drops it on the next save).

    Without a boundary (no ``plan_width_m``) the location has no width of its
    own; it falls back to ``DEFAULT_EXTENT_M`` so a plan still composes.

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


def _outline_world(map3d: Dict[str, Any]) -> List[List[float]]:
    """``map3d.outline`` — the drawn BUILDING contour — in world metres, or []
    when there is no polygon. Stored in local metres since v6 (Nr. 2), so
    nothing is scaled here."""
    pts = (map3d or {}).get("outline")
    if not isinstance(pts, list) or len(pts) < 3:
        return []
    out: List[List[float]] = []
    for pt in pts:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return []
        out.append([_r(_num(pt[0])), _r(_num(pt[1]))])
    return out


def _drawn_boundary(map3d: Dict[str, Any]) -> List[List[float]]:
    """``map3d.boundary`` as local metres, or [] when none is DRAWN.

    The scene frame IS the location's local frame (origin = the anchor pin),
    which is the frame the boundary is authored in — so this is a parse, not
    a transform. The winding and the point cap are the sanitizer's job
    (``world_ops._sanitize_map3d``); here a malformed outline simply is not
    one.
    """
    from app.core.world_geometry import polygon_points
    pts = polygon_points((map3d or {}).get("boundary"))
    return [] if pts is None else [[_r(x), _r(z)] for x, z in pts]


def _boundary_local(map3d: Dict[str, Any], extent: float) -> List[List[float]]:
    """The location's EFFECTIVE boundary in local metres — polygon always
    (contract v6 Nr. 1: "a square is only the special case of the polygon").

    The drawn ``map3d.boundary`` where there is one, otherwise the reference
    square as its four corners, clockwise in map view. It mirrors
    ``world_geometry.effective_boundary`` — deliberately WITHOUT its
    placement requirement, because a scene composes for an unplaced template
    too (draft preview, § B3): the square there has no pin to sit on and the
    scene frame is the pin.
    """
    drawn = _drawn_boundary(map3d)
    if drawn:
        return drawn
    half = _r(extent / 2.0)
    return [[-half, -half], [half, -half], [half, half], [-half, half]]


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


def storey_floor_y(level: int, storey: float) -> float:
    """The FLOOR DATUM of one storey, in scene metres — where one stands on it.

    THE WHOLE HEIGHT LADDER OF A SCENE, in one line and two cases (§ G5):

    * storey 0 is the TERRAIN. Its datum is 0 in the scene frame, because the
      scene frame's zero IS the ground under the pin — there is no plate, no
      slab and no 0.08 to clear;
    * every DECLARED storey above or below keeps its level plate, so its datum
      is that plate's top, ``level·storey + LEVEL_PLATE_TOP``.

    Before E5a this was a hard ``level·storey + 0.08`` everywhere plus a
    ``slab`` parameter that was 0 on a natural location and 0.08 elsewhere —
    two grounds, one of which the world relief knew nothing about.

    THE BASEMENT IS NOT STOREY 0 EITHER. § G5 speaks of "upper storeys", but the
    property that decides is being a DECLARED storey rather than the terrain: a
    cellar at level −1 lies a storey under the ground and would otherwise lose
    its floor to a terrain it is nowhere near.
    """
    level = int(level)
    return level * storey + (0.0 if level == 0 else LEVEL_PLATE_TOP)


def _room_floor_y(recipe: Dict[str, Any], storey: float) -> float:
    """The room's STOREY datum plus its own offset (``layout.floor_offset_y``).

    The bare storey level, not the floor one stands on: what a room's floor
    lifts over it is :func:`_plate_top`, and the two are added wherever
    something rests on that floor.

    The offset is a per-room fine adjustment and nothing else since E5a. It used
    to carry two other jobs and has lost both: it compensated for a room cutting
    a hole into a LOCATION model on a slope (there is one ground now, and it is
    the same one the mesh stands on), and the author used it as a WATERLINE for
    a zone whose floor kind was water (since W1 a room has no water at all — the
    painted AREA carries the mirror, and the room only names it via
    ``floor_plan[].map_water``).
    Everything in the room still derives from here, so plate, walls, props,
    markers and diorama move as one.
    """
    return (int(recipe.get("level") or 0) * storey
            + _num(recipe.get("floor_offset_y")))


def _room_rect(recipe: Dict[str, Any], room: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """The room's placed rectangle (x, y, w, d) in LOCAL METRES — min corner
    plus size, exactly as stored (contract v6 Nr. 2)."""
    lay = room.get("layout") or {}
    return (_num(lay.get("x")), _num(lay.get("y")),
            _num(lay.get("w"), 1.0), _num(lay.get("d"), 1.0))


def room_size_m(location: Dict[str, Any],
                room: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """A room's rectangle in REAL METRES ``(w_m, d_m)``, or None when it has
    no layout.

    Since v6 (Nr. 2) a layout side IS its real size — there is no scale rule
    left to apply and no anchor that could be missing. The function stays
    because consumers outside the 3D path (the image-prompt composer wants
    the footprint in metres) ask this module for geometry rather than
    reading the layout themselves. ``location`` is unused and kept only so
    the call sites read as "the room OF this location".
    """
    lay = (room or {}).get("layout") or {}
    w, d = _num(lay.get("w")), _num(lay.get("d"))
    if w <= 0 or d <= 0:
        return None
    return (round(w, 2), round(d, 2))


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

    RULE 2 IS UNREACHABLE FROM ``_plates`` SINCE E5a, and deliberately kept:
    storey 0 draws no level plate at all any more (the terrain is its floor and
    the layer bake its material), so no plate ever asks this function about
    level 0. The rule stays written down because it is the CONTRACT of the
    location's ``terrain`` field — the ground OUTSIDE — and it is the one place
    that says storey 0 is the terrain storey by definition.
    """
    if isinstance(level_floors, dict):
        declared = str(level_floors.get(str(level)) or "").strip()
        if declared:
            return declared
    if level == 0 and ground_kind:
        return ground_kind
    return DEFAULT_FLOOR_KIND


def _plates(map3d: Dict[str, Any], recipes: List[Dict[str, Any]],
            levels: List[int], storey: float,
            ground_kind: str = "") -> List[Dict[str, Any]]:
    """The floors of every DECLARED storey — one contour plate per level plus
    one floor plate per room on it. **Storey 0 gets nothing** (E5a).

    THE PLATE ERA IS OVER ON THE GROUND. Until E5a this function drew, on
    storey 0, a level plate 0.14 m thick with its top at 0.08, a room plate per
    room at 0.10 and a texture-only surface per outdoor zone at 0.09 — a second
    ground stacked on the world's own, held apart from it by constants, and the
    root of every "house sinks in the distance / grass over the parquet" finding
    the plan was written for. On storey 0 the floor is now the TERRAIN: its
    height is ``h_final`` (planed flat under a built location by the plateau
    stamp, § G5) and its material is the LAYER BAKE, where the same room
    polygons appear as the topmost layers of the ground (§ G3,
    ``core.terrain_layers.location_floors``). What is left here is
    ``floor_plan`` in the payload — the polygons, so a consumer still knows
    where the rooms are.

    A DECLARED STOREY IS UNTOUCHED, and that includes a basement: level ±1 and
    beyond are scene geometry (§ G5, "Obergeschosse bleiben Szenen-Geometrie"),
    at exactly the datums they always had — the level plate's top at
    ``level·storey + 0.08``, the room plates at 0.10 on it, an outdoor zone as a
    texture surface at 0.09. Nothing about an upper floor moved.

    The level plate carries the storey's floor kind (``level_plate_kind``);
    the rooms lay their own plates ON TOP, so a room floor overrides only its
    own area. Outdoor rooms (§ A5) get NO body — they appear as a plate of
    thickness 0, i.e. a pure texture surface on the level plate below.

    WHAT THE LEVEL PLATE IS SHAPED LIKE (contract v6 Nr. 4): the drawn
    location boundary — the plate is the triangulated boundary polygon, not a
    square any more. A drawn BUILDING contour (``map3d.outline``) still wins
    where there is one: it is the more specific shape, the floor plan of the
    house inside the plot, and the walls are built along it. A location with
    neither gets no level plate at all, exactly as before — the synthesized
    square is a transition crutch for the payload's ``boundary``
    field, never a floor somebody drew.
    """
    plates: List[Dict[str, Any]] = []
    contour = _outline_world(map3d) or _drawn_boundary(map3d)
    level_floors = (map3d or {}).get("level_floors") or {}
    ground = min(levels)
    if contour:
        for level in levels:
            if level == 0:
                continue                    # the terrain is the floor here
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
        if level == 0:
            continue                        # …and here (``floor_plan``)
        outdoor = bool(recipe.get("always_visible"))
        outline = _room_outline_world(recipe)
        if not outline:
            continue
        entry: Dict[str, Any] = {
            "level": level,
            "outline": outline,
            "top_y": _r(_room_floor_y(recipe, storey) + _plate_top(recipe)),
            "thickness": 0.0 if outdoor else ROOM_PLATE_THICKNESS,
            "opacity_role": _opacity_role(level, ground),
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
                   doors: List[Dict[str, Any]],
                   room_hulls: Optional[Dict[int, List[List[List[float]]]]] = None,
                   ) -> List[Dict[str, Any]]:
    """The building contour as walls, per used level (§ A6).

    THE HULL TAKES ITS HOLE FROM THE DOOR (plan-betreten-und-tueren.md § 4.2):
    every outside doorway is projected forward onto the contour and opens it
    there, in the DOOR's clear width. ``doors`` carries one dict per outside
    doorway — ``level``, ``at`` (middle of the clear opening), ``normal`` (the
    door's outward unit normal), ``width`` and ``top_y`` (the world height the
    door's head reaches) — all of it derived from the ``doorways`` block the
    payload itself ships, never a second time from the openings. The hole
    lands on the door's OWN storey: a hull opens where a door is, and a
    building without one stays shut and is reported instead (``_problems``).
    The old fallback — one 0.8 m door mid in the southernmost piece whenever
    no door projected close enough — is gone.

    The hole is the door's CLEAR width measured along the contour edge: a door
    meeting the hull at an angle keeps its own width there instead of being
    stretched, and one clamped against a corner loses the part that runs past
    the edge rather than wrapping onto the next one.

    AND IT IS THE DOOR'S CLEAR HEIGHT (finding 2026-08-25): above ``top_y``
    the contour carries on as a LINTEL piece over the opening, exactly like
    the head a window has always had on a room wall. The projected hole used
    to run from the foot to the top of the shell, so a door in an outer wall
    read as a missing wall segment rather than as a door — from outside and in
    the Blender exterior render alike. Where the contour has already yielded
    to a room hull the lintel yields with it: no wall there, no lintel there,
    and the room's own wall carries both.

    AND THE HOLE ITSELF CARRIES A DOOR LEAF (user decision 2026-08-25): a thin
    dark plate from the wall's foot to ``top_y``, flagged ``leaf`` — the door's
    counterpart to a window's glass pane, and the reason an exterior door is
    visible AS a door instead of as a dark rectangle of interior. It follows
    the lintel in everything: same span, clipped against the stretches that
    yielded to a room hull (there the ROOM wall's own leaf is the only one),
    and it is emitted only for a ``door``. A ``passage`` is an authored opening
    WITHOUT a door — a leaf there would state a door nobody drew — so its
    entry arrives with ``leaf`` False and the hole stays empty.

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
    pts = _outline_world(map3d)
    if len(pts) < 3:
        return []
    # Winding decides which side is outside (shoelace in the XZ plane).
    area2 = 0.0
    for i, (x1, z1) in enumerate(pts):
        x2, z2 = pts[(i + 1) % len(pts)]
        area2 += x1 * z2 - x2 * z1
    ccw = area2 > 0

    # (level, edge index) → the (span, head height, has a leaf, the leaf is a
    # PROP) the doors of that storey cut out of it.
    cuts: Dict[Tuple[int, int],
               List[Tuple[float, float, float, bool, bool]]] = {}
    for door in doors:
        hit = _contour_hit(pts, door["at"], door["normal"])
        if not hit:
            continue
        i, t = hit
        half = _num(door.get("width")) / 2
        cuts.setdefault((int(door.get("level") or 0), i), []).append(
            (t - half, t + half, _num(door.get("top_y")),
             bool(door.get("leaf")), bool(door.get("door_prop"))))

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
            door_cuts = list(cuts.get((level, i), []))
            # Room-hull spans on this contour edge: colinear within roughly
            # a wall thickness → the room wall owns that stretch.
            yielded: List[Tuple[float, float]] = []
            for hull in (room_hulls or {}).get(level, []):
                for j, ha in enumerate(hull):
                    hb = hull[(j + 1) % len(hull)]
                    span = _colinear_span(a, ux, uz, length, ha, hb)
                    if span:
                        yielded.append(span)
            holes = sorted(yielded + [(c[0], c[1]) for c in door_cuts])
            sink = WALL_SINK_M if level == 0 else 0.0
            foot = storey_floor_y(level, storey)
            # (span, foot, height, kind) of every piece of this edge on this
            # storey: the full-height runs between the holes first, then one
            # LINTEL over each door hole and one LEAF in it — both clipped
            # against the stretches that yielded to a room hull, because there
            # is no contour wall there to carry either. A door as tall as the
            # wall leaves no lintel and drops out; a passage carries no leaf.
            pieces: List[Tuple[float, float, float, float, str, bool]] = [
                (s0, s1, foot - sink, height + sink, "", False)
                for s0, s1 in _subtract([(0.0, length)], holes,
                                        MIN_WALL_PIECE_M)]
            for t0, t1, top_y, has_leaf, has_prop in door_cuts:
                span = (max(t0, 0.0), min(t1, length))
                if span[1] - span[0] < MIN_WALL_PIECE_M:
                    continue
                clipped = _subtract([span], sorted(yielded), MIN_WALL_PIECE_M)
                lintel = foot + height - top_y
                if MIN_WALL_PIECE_M <= lintel <= height:
                    pieces.extend((s0, s1, top_y, lintel, "lintel", False)
                                  for s0, s1 in clipped)
                # THE LEAF fills the CLEAR opening: from the wall's own foot
                # (never skirted — it is the door, not a wall standing in the
                # terrain) up to the door's head.
                if has_leaf and top_y - foot >= MIN_WALL_PIECE_M:
                    pieces.extend((s0, s1, foot, top_y - foot, "leaf",
                                   has_prop) for s0, s1 in clipped)
            for s0, s1, base_y, piece_h, kind, has_prop in pieces:
                start, end = _segment_points(a, ux, uz, s0, s1)
                entry: Dict[str, Any] = {
                    "level": level,
                    "from": start,
                    "to": end,
                    # The foot of the shell is the floor of its storey
                    # (:func:`storey_floor_y`) — the terrain on storey 0 since
                    # E5a, the level plate's top on every declared one. On
                    # storey 0 it goes ``WALL_SINK_M`` further down, into the
                    # ground, and the height grows by the same amount: the TOP
                    # edge is untouched and no relief under the wall can open a
                    # gap between it and the terrain (§ A16.9). A LINTEL over a
                    # door and the LEAF in it hang in the wall instead: they
                    # start at the door's head / at the floor line and are
                    # never skirted.
                    "base_y": _r(base_y),
                    "height": _r(piece_h),
                    "thickness": _r(WALL_THICKNESS * PANE_THICKNESS_FACTOR, 3)
                    if kind == "leaf" else WALL_THICKNESS,
                    "opacity_role": _opacity_role(level, min(levels)),
                    "outward_normal": [_r(nx), _r(nz)],
                }
                if kind == "leaf":
                    # The door itself (§ B1 ``leaf``): drawn dark and opaque,
                    # excluded from the facade culling like a glass pane, and
                    # no barrier — one walks THROUGH a door.
                    entry["leaf"] = True
                    if has_prop:
                        # A PROP fills this hole (v5) — same rule as on a room
                        # wall: the renderers skip the plate, the entry stays
                        # for the exterior render.
                        entry["door_prop"] = True
                elif wall_kind:
                    entry["texture_kind"] = wall_kind
                if kind == "lintel":
                    # Over the door one WALKS — the piece is drawn, it does not
                    # block (§ B1 ``lintel``).
                    entry["lintel"] = True
                walls.append(entry)
    return walls


def _room_wall_edges(recipe: Dict[str, Any]
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
    outline = [[_num(p[0]), _num(p[1])]
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


def _opening_height(op: Dict[str, Any], wall_height: float) -> float:
    """CLEAR height of one opening in metres — its authored ``height_m``.

    Every stored opening carries the field (``world_ops._sanitize_opening``
    demands 0.4…10 m and drops the entry otherwise). A dict that does not — a
    hand-written fixture, a draft coming out of a generator — keeps the
    behaviour a missing number always had: the hole reaches the top of the
    wall, so no lintel is built over it. A height taller than the wall is
    clamped by the caller, which is the only place that knows the wall.
    """
    height = _num(op.get("height_m"))
    return height if height > 0 else wall_height


def door_prop_id(opening: Dict[str, Any], default_prop_id: str = "") -> str:
    """WHICH prop stands in this opening — ``""`` when none does.

    THREE-VALUED, and the same rule everywhere this file asks (user decision
    2026-08-27, plan-door-props-texture-slots.md):

    * the opening's own ``prop_id`` wins,
    * ``door_prop: "none"`` is the explicit "no prop here" and blocks the
      location default (an EMPTY ``prop_id`` is "nothing chosen", which is
      what the default is for),
    * otherwise the location's ``default_door_prop_id``,
    * and otherwise the open hole with the flat leaf, exactly as before.

    Only a ``door`` takes one: a window's hole is glass, and a ``passage`` is
    an authored opening WITHOUT a door — putting a leaf, let alone a prop, in
    either would state something nobody drew.

    A pure function of the two records on purpose: the wall splitter, the
    doorway list and the model spec all have to agree about which openings
    have a door prop, and they do because they all ask THIS.
    """
    if str(opening.get("type") or "door").lower() != "door":
        return ""
    own = str(opening.get("prop_id") or "").strip()
    if own:
        return own
    if str(opening.get("door_prop") or "").strip().lower() == "none":
        return ""
    return str(default_prop_id or "").strip()


def _room_walls(recipe: Dict[str, Any], storey: float,
                ground_level: int,
                default_door_prop_id: str = "") -> List[Dict[str, Any]]:
    """One room's shell walls, split around its openings (§ A4).

    EVERY opening is cut the same way (finding 2026-08-25): the wall below it
    (a window's sill band, nothing under a door — one walks THROUGH a door,
    so its sill is ignored), the LINTEL above it up to the top of the wall,
    and a PANE filling the hole. A door used to be the exception — a gap all
    the way to the ceiling, its authored ``height_m`` unused — which is what
    left doorways open to the ceiling and made an outer wall look as if it had
    lost a whole segment.
    Mirrored openings (the neighbour's door in the shared wall) arrive
    pre-translated in the recipe and are treated exactly like own ones.
    Outdoor rooms have no shell at all (§ A5).

    THE PANE IN THE HOLE has two forms (user decision 2026-08-25): a window's
    translucent GLASS band, and a door's opaque dark LEAF from the floor to its
    head. Same mechanism, same thinness, one flag each — which is why the
    renderers needed almost no new code for the leaf. A ``passage`` gets
    neither: it is an authored opening WITHOUT a door, so its hole stays empty.

    ``no_walls`` is the per-room opt-out (open zone, pavilion, an area inside
    an area model): NOTHING is emitted — no segments, no window sill or head,
    no glass, no leaf. Everything else about the room stays: its plate, its
    openings in the ``rooms`` block (the 2D editor keeps drawing them), its
    markers and its diorama. The BUILDING's contour walls are untouched.
    """
    level = int(recipe.get("level") or 0)
    # Room shell walls stand on the ROOM's own floor (``_plate_top``): the
    # room plate (0.10) on a declared storey, the TERRAIN (0.0) on storey 0.
    base = _room_floor_y(recipe, storey) + _plate_top(recipe)
    height = _wall_height(storey)
    kind = str(((recipe.get("surfaces") or {}).get("wall")) or "").strip()
    room_id = recipe.get("room_id") or ""
    role = _opacity_role(level, ground_level)
    walls: List[Dict[str, Any]] = []

    for _i, a, ux, uz, length, spans in _room_wall_edges(recipe):
        # Clockwise hull → the outward normal of (ux, uz) is (uz, −ux).
        normal = [_r(uz), _r(-ux)]

        def _emit(s0: float, s1: float, y: float, h: float,
                  thickness: float, glass: bool = False,
                  lintel: bool = False, leaf: bool = False,
                  door_prop: bool = False) -> None:
            if s1 - s0 < MIN_SEGMENT_M or h < MIN_SEGMENT_M:
                return
            # Only a piece that STANDS ON THE FLOOR gets the skirt (§ A16.9):
            # the full-height segments and a window's sill, never its head and
            # never its glass band — those start further up the wall. On a
            # declared storey the plate under the foot is still there and the
            # skirt is 0. A DOOR LEAF stands on the floor line and is NOT
            # skirted for it: it fills the CLEAR opening exactly, the threshold
            # primitive lies at its foot, and the jambs either side carry the
            # skirt that keeps the light out under the wall.
            sink = (WALL_SINK_M if (level == 0 and y <= 0.0 and not leaf)
                    else 0.0)
            start, end = _segment_points(a, ux, uz, s0, s1)
            entry: Dict[str, Any] = {
                "level": level,
                "from": start,
                "to": end,
                "base_y": _r(base + y - sink),
                "height": _r(h + sink),
                "thickness": _r(thickness, 3),
                "opacity_role": role,
                "room_id": room_id,
                "outward_normal": normal,
            }
            if glass:
                entry["glass"] = True
            elif leaf:
                # The door itself (§ B1 ``leaf``): opaque and dark, drawn like
                # a pane, out of the facade culling like a pane, and no
                # barrier — one walks THROUGH a door.
                entry["leaf"] = True
                if door_prop:
                    # …and a PROP fills this hole (v5): the renderers skip the
                    # plate, the prop is the door. The entry itself STAYS —
                    # the Blender exterior render builds its facade from
                    # ``walls`` and would lose the door's prism with it
                    # (user decision 2026-08-27).
                    entry["door_prop"] = True
            elif kind:
                entry["texture_kind"] = kind
            if lintel:
                # It hangs over a WALKABLE gap: drawn like any wall, but it
                # bars nothing in a floor plan (§ B1 ``lintel``).
                entry["lintel"] = True
            walls.append(entry)

        for s0, s1 in _subtract([(0.0, length)],
                                [(sp[0], sp[1]) for sp in spans],
                                MIN_SEGMENT_M):
            _emit(s0, s1, 0.0, height, WALL_THICKNESS)
        # ONE HOLE, ONE SET OF PIECES. Two entries can describe the same hole:
        # the neighbour's MIRRORED copy of a party-wall door next to the door
        # this room authored itself, or the same opening entered twice. The
        # solid runs never showed it (``_subtract`` merges overlapping holes),
        # but every band did — two lintels, two panes, two leaves in one gap,
        # z-fighting each other. ``_doorways`` collapses exactly these cases
        # for the threshold (``_same_gap``); this is the same rule on the wall
        # itself, and the FIRST entry wins, as it does there.
        seen: List[Tuple[float, float]] = []
        for s0, s1, op in spans:
            if any(abs(s0 - p0) <= _SAME_SPAN_M
                   and abs(s1 - p1) <= _SAME_SPAN_M for p0, p1 in seen):
                continue
            seen.append((s0, s1))
            op_type = str(op.get("type") or "door").lower()
            window = op_type == "window"
            # A door/passage starts on the floor whatever a sill says: it is
            # walked through, and the threshold primitive lies at its foot.
            sill = min(_num(op.get("sill_m")), height) if window else 0.0
            top = min(sill + _opening_height(op, height), height)
            _emit(s0, s1, 0.0, sill, WALL_THICKNESS)
            # The head. Over a WALKABLE opening it is flagged: one walks under
            # it, so it must not become a barrier in anyone's floor plan. A
            # window's head needs no flag — its own sill blocks that span.
            _emit(s0, s1, top, height - top, WALL_THICKNESS,
                  lintel=op_type in _WALKABLE_TYPES)
            # The pane in the hole: glass for a window, the LEAF for a door.
            if window:
                _emit(s0, s1, sill, top - sill,
                      WALL_THICKNESS * PANE_THICKNESS_FACTOR, glass=True)
            elif op_type == "door":
                _emit(s0, s1, 0.0, top,
                      WALL_THICKNESS * PANE_THICKNESS_FACTOR, leaf=True,
                      door_prop=bool(door_prop_id(op, default_door_prop_id)))
    return walls


# ── Doorways ────────────────────────────────────────────────────────────

def _doorways(recipes: List[Dict[str, Any]], storey: float,
              default_door_prop_id: str = "") -> List[Dict[str, Any]]:
    """Every walkable threshold of the location as a finished primitive
    (plan-betreten-und-tueren.md § 4.1).

    A doorway is EXACTLY the gap an opening cuts out of a wall — same source,
    same clamp (``_room_wall_edges``), no second derivation. Hence ``width_m``
    is the CLEAR width after the edge clamp, not the authored width for
    anyone to re-clamp, and ``height_m`` is the clear height after the same
    clamp against the wall — the number the lintel above the gap starts at.
    The consumer rule is: nothing is recalculated.

    ``base_y`` LEAVES this function as the foot of the wall the gap belongs to
    and is the finished number only after :func:`compose_scene` has run
    :func:`threshold_base_y` over it — the payload's ``base_y`` is the STANDING
    height of the adjoining rooms (§ B doorways), and where a room diorama
    declares one, that is not knowable here: it lives on the model spec, which
    is composed later.

    ONE gap in the wall = ONE entry. Two candidates are the same hole when all
    three of ``_same_gap`` hold: same wall DIRECTION, the two wall faces no
    further apart than the mirror's own ``SHARE_TOL_M`` (plus the rounding a
    mirrored ``at`` carries — 4 decimals of a world metre), and clamped
    spans that actually meet on that line. Three cases run through it:

    * the neighbour's mirrored copy (``room_recipe._mirrored_openings``) — it
      contributes only its room id;
    * BOTH rooms of a party wall authoring their own door at the same spot;
    * the same door authored twice in one room.

    The widest span wins the GEOMETRY (the gap is the union of the overlapping
    spans — ``at_world`` and ``width_m``), never the ORIENTATION: ``along``,
    the order of ``rooms`` and the door prop stay with the entry that was kept
    first, so ``rooms[0]`` is always the room whose wall this entry was cut out
    of. A mirrored copy runs backwards along the same line and names the
    neighbour first — letting it win those would put an authored hinge on the
    other jamb and open the door into the author's room.

    ``outside`` is GEOMETRY, not authored text — see below. The GROUND room
    never appears in ``rooms``: it has no walls, and ``outside`` already says
    the door leads onto it.

    A window is no way out (``_WALKABLE_TYPES``), a room without a shell has
    no threshold, and the order is deterministic (level, position, rooms):
    consumers diff whole payloads.

    THE DOOR PROP rides along in the INTERNAL key ``_door_prop`` (v5): which
    prop fills this hole (:func:`door_prop_id`) and which side its hinge is
    on. It is resolved here because this is where an opening becomes a hole —
    :func:`_door_prop_models` is its only reader and :func:`compose_scene`
    strips the key before the payload leaves. ``hinge`` is read against THIS
    entry's ``along``, i.e. against the wall of ``rooms[0]`` — which is why
    the dedup above never lets a mirrored copy replace either of the two.
    """
    from app.models.world import GROUND_ROOM_ID

    def _rooms_of(room_id: str, to: str) -> List[str]:
        out = [room_id]
        if to and to.lower() != "outside" and to != GROUND_ROOM_ID \
                and to != room_id:
            out.append(to)
        return out

    tol = SHARE_TOL_M + 1e-4
    wall_h = _wall_height(storey)
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
        base = _r(_room_floor_y(recipe, storey) + _plate_top(recipe))
        for _i, a, ux, uz, length, spans in _room_wall_edges(recipe):
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
                    # WHICH KIND of walkable opening this is. A ``door`` has a
                    # leaf in its hole, a ``passage`` is an open gap (§ B1
                    # ``leaf``) — the contour reads it from here instead of
                    # looking the opening up a second time.
                    "type": str(op.get("type") or "door").lower(),
                    "width_m": _r(s1 - s0),
                    # CLEAR height of the gap, clamped to the wall exactly as
                    # the splitter clamps it: the wall over the door is a
                    # lintel, and this is where that lintel begins. Consumers
                    # do not re-derive it either — same rule as ``width_m``.
                    "height_m": _r(min(_opening_height(op, wall_h), wall_h)),
                    "base_y": base,
                    "rooms": _rooms_of(room_id, to),
                    # INTERNAL, stripped in compose_scene — see the docstring.
                    "_door_prop": {
                        "id": door_prop_id(op, default_door_prop_id),
                        "hinge": ("right"
                                  if str(op.get("hinge") or "").strip().lower()
                                  == "right" else "left"),
                    },
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
            # entry describes the GEOMETRY — and only that. Both candidates
            # lie on the same line, so the direction, the room order and the
            # door prop stay with the base: a mirrored copy runs backwards and
            # would move an authored hinge onto the other jamb.
            keep = {k: base_entry[k] for k in ("along", "rooms", "_door_prop")}
            keep["rooms"] = keep["rooms"] + [r for r in entry["rooms"]
                                             if r not in keep["rooms"]]
            base_entry.update(entry)
            base_entry.update(keep)
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

# A room corner is "out" only past this much — the boundary is stored to the
# centimetre, so a plan drawn flush against an edge must not be flagged.
_BOUNDARY_TOL_M = 0.01


def rooms_outside_boundary(recipes: List[Dict[str, Any]],
                           boundary: Any) -> List[str]:
    """The ids of rooms whose floor plan sticks out of the location boundary.

    Both sides are LOCAL METRES around the pin and, since v6 (Nr. 2), stored
    that way — there is no conversion left on either side, so "outside" means
    here exactly what it means in the composed scene. The room rectangle needs
    no special case: ``compose_recipe`` already resolved it into an outline.

    Measured with ``polygon_distance``, which is 0 anywhere INSIDE the
    polygon including its edges — a plan drawn flush against the boundary is
    legal, only a point further than ``_BOUNDARY_TOL_M`` out counts. Tested
    are the outline corners AND each edge's midpoint: with a concave
    boundary (a U), a room edge can cross the opening while both corners
    stand inside the arms, and the midpoint is the cheap witness for that.
    Ids come back in recipe order; an empty list means everything fits.
    """
    from app.core.world_geometry import polygon_area, polygon_distance
    if polygon_area(boundary) <= 0:
        return []
    out: List[str] = []
    for recipe in recipes:
        outline = _room_outline_world(recipe)
        if not outline:
            continue
        probes = list(outline)
        n = len(outline)
        probes.extend(((outline[i][0] + outline[(i + 1) % n][0]) / 2.0,
                       (outline[i][1] + outline[(i + 1) % n][1]) / 2.0)
                      for i in range(n))
        if any(polygon_distance(px, pz, boundary) > _BOUNDARY_TOL_M
               for px, pz in probes):
            out.append(str(recipe.get("room_id") or ""))
    return out


def _problems(location: Dict[str, Any], map3d: Dict[str, Any],
              shell_levels: Set[int], doorways: List[Dict[str, Any]],
              recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Findings instead of silent repairs (plan-betreten-und-tueren.md § 4.3).

    ``rooms_without_layout`` — the location has a contour, it has rooms, and
    not ONE of them composed a recipe (every layout is missing or degenerate).
    That is the quiet version of the sealed hull: without a recipe there is no
    shell either, so ``shell_levels`` stays empty and ``no_building_entrance``
    below can never speak up. The contour then stands over nothing at all.
    The GROUND room never counts — its layout is props and markers, not a
    floor plan somebody can enter (§ A13a). The room
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
    so door, window, glass, door leaf and threshold all silently cease to
    exist in 3D —
    while the 2D floor plan keeps drawing the very openings the author
    authored. A wall-less room WITHOUT openings is perfectly legal (open
    zone, pavilion) and stays quiet; only the combination is the trap. Fires
    once per location, with the number of affected rooms as its own field.

    ``boundary_self_intersection`` — the drawn location boundary crosses
    itself (contract v6 Nr. 1). Concave is fine, a bow tie is not: the
    triangulated level plate, the ramp ring and every point-in-location test
    become ambiguous there. Still only a warning — the outline is stored as
    drawn and nothing is repaired behind the author's back.

    ``room_outside_boundary`` — a room's floor plan reaches out of that
    boundary (contract v6 Nr. 9), so it would stand on ground the location
    does not own. Only checked when a valid boundary exists; the affected
    room ids ride along as their own field, since ``message`` is translated
    as a whole sentence.
    """
    out: List[Dict[str, Any]] = []
    from app.models.world import GROUND_ROOM_ID
    has_contour = len(_outline_world(map3d)) >= 3
    # The GROUND room is out: it is the location's open surface and NEVER
    # carries a layout (the sanitizer strips one), so counting it would blame
    # the author for a room that cannot be drawn.
    rooms = [r for r in (location.get("rooms") or [])
             if isinstance(r, dict) and str(r.get("id") or "") != GROUND_ROOM_ID]
    # …and its RECIPE is out of the count for the same reason: a yard full of
    # props (§ A13a) composes a recipe, but it is not a room somebody can
    # enter, so it must not silence this finding.
    room_recipes = [r for r in recipes if not r.get("is_ground")]
    if has_contour and rooms and not room_recipes:
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
    # The drawn location boundary (v6): its own two findings. Both are pure
    # geometry over the stored local-metre points, so they read the same for
    # the floor-plan editor and the 3D client.
    from app.core.world_geometry import polygon_self_intersects
    boundary = (map3d or {}).get("boundary")
    if polygon_self_intersects(boundary):
        out.append({
            "kind": "boundary_self_intersection",
            "location_id": str(location.get("id") or ""),
            "message": "The drawn location boundary crosses itself: what is "
                       "inside and what is outside is ambiguous there. "
                       "Redraw the outline without crossing edges.",
        })
    stray = rooms_outside_boundary(recipes, boundary)
    if stray:
        out.append({
            "kind": "room_outside_boundary",
            "location_id": str(location.get("id") or ""),
            "room_ids": stray,
            "room_count": len(stray),
            "message": "Rooms reach out of the location boundary: their "
                       "floor plan stands on ground this location does not "
                       "cover. Move them inside or widen the boundary.",
        })
    return out


# ── Extras (elevator, stairs) ───────────────────────────────────────────

def _box(kind: str, cx: float, cy: float, cz: float,
         w: float, h: float, d: float, **extra: Any) -> Dict[str, Any]:
    """ONE primitive form for the extras: an axis-aligned box by centre+size."""
    entry = {"kind": kind,
             "center": [_r(cx), _r(cy), _r(cz)],
             "size": [_r(w), _r(h), _r(d)]}
    entry.update(extra)
    return entry


def _elevator(map3d: Dict[str, Any], levels: List[int],
              storey: float) -> List[Dict[str, Any]]:
    """The elevator of a building: shaft columns + roof, glass on three sides
    (the side facing the building centre stays open), a pad per level and a
    static cabin on the ground floor (§ A6). ``map3d.elevator`` is a POINT IN
    LOCAL METRES since v6 (Nr. 2), like every other plan coordinate — the
    [0,1]² domain is gone. All sizes are metres — the
    legacy figure scale the caller used to hand in as k (storey / 3, the
    preview's kEl) is gone with E4: one metre is one metre.
    """
    pos = (map3d or {}).get("elevator")
    if not isinstance(pos, (list, tuple)) or len(pos) != 2:
        return []
    ex, ez = _num(pos[0]), _num(pos[1])
    top_level = max([0] + list(levels))
    # The shaft reaches the floor of the storey ABOVE the topmost one, which is
    # always a declared storey (``top_level`` ≥ 0) and therefore unchanged by
    # E5a. Every other height here comes off :func:`storey_floor_y`.
    shaft_top = storey_floor_y(top_level + 1, storey)
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
        # THE PAD HANGS UNDER THE FLOOR OF ITS STOREY — the same law as before,
        # only the floor is now :func:`storey_floor_y` instead of a hard 0.08:
        # on storey 0 the pad's top is the terrain (0.0) and one steps onto it
        # level with the ground, on every declared storey it is the level
        # plate's top exactly as it always was.
        out.append(_box("elevator_pad", ex,
                        storey_floor_y(level, storey)
                        - ELEVATOR_PAD_THICKNESS / 2,
                        ez, pad, ELEVATOR_PAD_THICKNESS, pad, level=level))
    cabin = ELEVATOR_CABIN_M
    cabin_h = max(ELEVATOR_CABIN_STOREY_FRAC * storey, 0.3)
    out.append(_box("elevator_cabin", ex,
                    storey_floor_y(0, storey) + cabin_h / 2, ez,
                    cabin, cabin_h, cabin, level=0))
    return out


def _stairs(map3d: Dict[str, Any], levels: List[int],
            storey: float) -> List[Dict[str, Any]]:
    """The staircases of a location: a flight of solid steps per entry, with a
    trigger pad at each end (§ A6, Nachtrag "Treppen (v4)").

    ``map3d.stairs`` is a list of ``{"at": [x, z], "from_level": int,
    "dir_deg": 0|90|180|270}`` in LOCAL METRES, like ``map3d.elevator``. ``at``
    is the FOOT — where the first tread begins — and a flight ALWAYS ends one
    storey up, at ``from_level + 1``; that is what makes a multi-storey climb a
    CHAIN of flights rather than one authored ramp.

    Every number falls out of :func:`storey_floor_y`, so a basement flight
    (``from_level`` −1) is the same formula and not a special case:

    * ``climb`` = the two floor datums apart; ``steps`` = the climb divided by
      the NOMINAL rise and rounded, at least two — the real ``rise`` then
      divides the climb evenly, so the last tread lands EXACTLY on the upper
      floor instead of a hand's breadth under or over it;
    * step *i* is a SOLID box from the lower floor up to its own tread — a
      staircase one can stand on anywhere, not a set of floating slabs;
    * a pad's TOP is its storey's floor, the same law ``elevator_pad`` follows,
      and it sits one pad-half plus a gap clear of the flight.

    ``levels`` is the storey census of the layout and deliberately NOT read: a
    flight is anchored by its own ``from_level``, whereas the elevator needs
    the census because it puts a pad on every storey that exists.
    """
    raw = (map3d or {}).get("stairs")
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(list(raw)[:STAIR_MAX]):
        if not isinstance(item, dict):
            continue
        at = item.get("at")
        if not isinstance(at, (list, tuple)) or len(at) != 2:
            continue
        # STRICTLY parsed, never repaired: a flight whose direction or foot
        # nobody wrote down is not silently turned north or dropped onto the
        # anchor pin — it does not exist.
        try:
            deg = int(float(item.get("dir_deg"))) % 360
            from_level = int(float(item.get("from_level")))
            ax, az = float(at[0]), float(at[1])
        except (TypeError, ValueError, OverflowError):
            continue
        if not (math.isfinite(ax) and math.isfinite(az)):
            continue
        step_dir = _STAIR_DIRS.get(deg)
        if step_dir is None:
            continue
        dx, dz = step_dir
        base = storey_floor_y(from_level, storey)
        target = storey_floor_y(from_level + 1, storey)
        climb = target - base
        if climb <= 0:
            continue
        steps = max(2, int(round(climb / STAIR_RISE_M)))
        rise = climb / steps
        run = steps * STAIR_TREAD_M
        # The tread runs ALONG the climb, the width ACROSS it — which of the
        # two is the x size therefore depends on the direction, and nothing
        # else does.
        size_x = STAIR_TREAD_M if dx else STAIR_WIDTH_M
        size_z = STAIR_TREAD_M if dz else STAIR_WIDTH_M
        for i in range(steps):
            along = (i + 0.5) * STAIR_TREAD_M
            height = (i + 1) * rise
            out.append(_box("stair_step", ax + dx * along, base + height / 2,
                            az + dz * along, size_x, height, size_z,
                            level=from_level, stair=idx))
        gap = STAIR_PAD_M / 2 + STAIR_PAD_GAP_M
        out.append(_box("stair_pad", ax - dx * gap,
                        base - STAIR_PAD_THICKNESS / 2, az - dz * gap,
                        STAIR_PAD_M, STAIR_PAD_THICKNESS, STAIR_PAD_M,
                        level=from_level, stair=idx, end="foot"))
        head = run + gap
        out.append(_box("stair_pad", ax + dx * head,
                        target - STAIR_PAD_THICKNESS / 2, az + dz * head,
                        STAIR_PAD_M, STAIR_PAD_THICKNESS, STAIR_PAD_M,
                        level=from_level + 1, stair=idx, end="head"))
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
    squashed in a single dimension any more), and since contract v6 Nr. 3 ONE
    scale LAW for every model in this file: the model's largest YAWED XZ side
    becomes its DECLARED REAL WIDTH in metres (sidecar ``width_m``, the same
    dial the diorama uses, § B2a). The height follows its own proportions. A
    mesh with wrong proportions is not repaired here; that is a modelling
    problem the metre ruler makes visible.

    Undeclared width = the effective boundary's bounding-box width
    (``extent_m``), flagged as ``width_estimated`` so the UI can ask for a
    calibration. That is exactly the number the retired ``map3d.size``
    produced at its default 1 (``extent_m × 1``), so a world that never
    declared a width renders identically to before the law changed.
    ``measure`` stays ``yawed_xz``: a building has to fit its plot AFTER the
    yaw, and the fix goes into that measurement rounded to 90° (v5.1 Nr. 4).

    ONE anchor rule since 2026-08-20 (§ B2 addendum), because both kinds of
    model answer the same question — WHERE IS THE FLOOR:

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
    - ``display "shell"`` — a building is pinned by the SAME law, to the same
      storey-0 floor: its walkable surface lands there, ``offset_y`` trims from
      there, and the mesh hangs below.

      It used to pin the mesh's LOWER EDGE (a fixed 0.06 socle clearance +
      ``offset_y``), which is the model's floor only for a mesh that has no
      ground pad under the house. "Haus von Kai" has one 0.240 m thick:
      pinned by the lower edge its floor came out at 0.000 while the room
      plates lay at 0.100 and the socle grass at 0.045 — the figure walked
      9 cm under the floor its own furniture stood on, and the tile's grass
      covered the model's floor (user finding 2026-08-20, measured). The
      dial that describes exactly this is ``walk_y``, and now it is the dial
      that places the model.

    WHAT E5a MOVES: the storey-0 floor IS the terrain now
    (:func:`storey_floor_y`), so both anchors measure from 0 instead of from the
    0.08 slab a drawn boundary used to produce. A building whose ``walk_y`` is 0
    (undeclared — the mesh's lower edge IS its floor) therefore sits 8 cm lower
    in the scene frame and exactly ON the ground, which under a built location
    is the plateau the bake stamped. No model is measured automatically to fill
    ``walk_y`` in — that law stands (below).

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
    # The declared real width wins for BOTH kinds — a plot-share fraction
    # (`map3d.size`) is gone with v6 Nr. 3. Undeclared falls back to the
    # boundary's bounding-box width, which is what the old default produced.
    width_m = _num(meta.get("width_m"))
    max_m = width_m if width_m > 0 else extent
    offset_y = _num(meta.get("offset_y"))
    walk = _num(meta.get("walk_y"))
    # Centre of the plot the model fills: the boundary's bbox centre in local
    # metres. For a pin-centred plot this is (0, 0) — the square-era numbers
    # are untouched; only an off-centre boundary moves the default stand.
    _bnd = _boundary_local(map3d or {}, extent)
    _xs = [p[0] for p in _bnd]
    _zs = [p[1] for p in _bnd]
    _bbox_cx = (min(_xs) + max(_xs)) / 2.0 if _bnd else 0.0
    _bbox_cz = (min(_zs) + max(_zs)) / 2.0 if _bnd else 0.0

    # THE STOREY-0 FLOOR, and since E5a there is only one of it: the terrain,
    # i.e. 0 in the scene frame (:func:`storey_floor_y`). Both kinds of model
    # measure from it, and so does everything standing in the yard and in the
    # zones on it (``_plate_top`` answers 0 there too) — which is what makes
    # "one ground" true for a mesh as well as for a figure.
    floor = storey_floor_y(0, 0.0)
    if ground:
        # An area model IS the ground of storey 0, so its walkable surface
        # lands on that floor and ``offset_y`` does not apply.
        walk_world = floor
        bottom = walk_world - walk
    else:
        # The SAME law for a building shell: the declared walkable surface
        # lands on the storey-0 floor, the mesh hangs below it, and
        # ``offset_y`` trims from there.
        walk_world = floor + offset_y
        bottom = walk_world - walk
    spec: Dict[str, Any] = {
        "role": "building",
        "display": "shell_area" if detail else ("ground" if ground else "shell"),
        "id": loc_id,
        "variants": _variants(f"/play/locations/{quote(loc_id)}/model",
                              meta.get("tiers")),
        "level": 0,
        "fix_euler": _fix_euler(meta.get("rotation")),
        # A building has NO yaw dial of its own any more (v6 Nr. 10): the
        # sidecar's orientation fix (``fix_euler`` y) turns the mesh, and the
        # location itself is turned by its anchor pin (§ A1.1). The old
        # ``map3d.rotation`` → ``map_rotation_2d`` chain was a second turn on
        # the SAME axis and only ever a source of arithmetic error.
        "yaw_deg": 0.0,
        # The width is met AFTER the yaw — a model turned 325° must still fit
        # its location, so the rotated footprint is what gets measured.
        "max_m": _r(max_m),
        "measure": "yawed_xz",
        # The DEFAULT stand of a building is the centre of the plot it fills —
        # since v6 that is the boundary's bbox CENTRE, not the pin: a boundary
        # enlarged to one side moves the plot while the pin stays, and a model
        # anchored at the pin then overflows the plate on that side (user
        # finding 2026-08-20: the roof view showed only part of the house —
        # snapshot camera and plate sit on the bbox centre, the mesh sat on
        # the pin). Offsets shift from that centre, exactly as they used to
        # shift from the pin when both were the same point (square era).
        "anchor": [_r(_bbox_cx + _num(meta.get("offset_x"))),
                   _r(_bbox_cz + _num(meta.get("offset_z")))],
        "bottom_y": _r(bottom),
        "walk_y_world": _r(walk_world),
    }
    if width_m <= 0:
        # Not calibrated yet: the location's own width stands in, and the spec
        # says so — same signal the diorama gives (§ B2a).
        spec["width_estimated"] = True
    if meta.get("roof_only"):
        # A GENERATED ROOF (docs/llm-blender-models.md, § B addendum
        # 2026-08-20): the model is the roof and nothing else, so it does NOT
        # replace the far-view recipe shell — the renderer keeps the walls and
        # puts this on top. Everything else about the spec stays a building's:
        # it fades on zoom-in exactly like a roof should.
        spec["roof_only"] = True
    return spec


def _diorama_model(recipe: Dict[str, Any], room: Dict[str, Any],
                   meta: Dict[str, Any], storey: float,
                   ) -> Optional[Dict[str, Any]]:
    """A room's diorama model as a placement spec (§ B2a).

    It rests on the SAME floor the room's props do (``_plate_top``): the
    terrain on storey 0, the room plate on a declared storey. ``model_offset_y``
    survives unchanged (user decision 4 of the plan) — it now measures from the
    one ground instead of from a slab, so it means the same thing everywhere.

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
        at = [w / 2, d / 2]          # absent = centred, in the room's metres
    # The anchor rides the room's own turn (contract v6 addendum): rotating a
    # rigid body about the rect centre IS "move the anchor + spin the mesh
    # about it by the same angle", and the spin is ``yaw_deg`` below. Without
    # the moved anchor the model spun in place inside a straight shell — the
    # gap the addendum closes.
    place = room_transform(room.get("layout"))
    anchor_u, anchor_v = place(_num(at[0], w / 2), _num(at[1], d / 2))
    spec: Dict[str, Any] = {
        "role": "room",
        "id": room_id,
        "variants": _variants(f"/play/rooms/{quote(room_id)}/model",
                              meta.get("tiers")),
        "room_id": room_id,
        "level": level,
        "fix_euler": _fix_euler(meta.get("rotation")),
        "yaw_deg": _r(_num(lay.get("rotation")), 1),
        "anchor": [_r(anchor_u), _r(anchor_v)],
        # Same floor the room's PROPS stand on — ONE source for all of them
        # (`_plate_top`): the terrain on storey 0, the room plate on a
        # declared storey. Plus the diorama clearance and the plan's dial.
        "bottom_y": _r(_room_floor_y(recipe, storey)
                       + _plate_top(recipe)
                       + DIORAMA_CLEARANCE
                       + _num(recipe.get("model_offset_y"))),
        "measure": "xz",
    }
    width_m = _num(meta.get("width_m"))
    max_m = width_m
    if max_m <= 0:
        # Not calibrated yet: the room rectangle's own world width is the
        # honest stand-in — same number the old rectangle fit produced, but
        # now as a real size the admin can dial at the reference figure.
        max_m = max(w, d)
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
    # The BAKED surface (v6, spec-surface-height): rung 0 of the walking height
    # in both renderers and the server's walk gate. Shipped verbatim from the
    # sidecar file — the recipe states no geometry of its own here.
    if isinstance(meta.get("surface"), dict):
        spec["surface"] = meta["surface"]
    # Opt-in shell clip (§ B1): a diorama may stick out over its floor plan —
    # with the flag the renderer discards everything outside the room shell.
    # The polygon is the room's floor plate, not a second derivation. An
    # outdoor room has no shell to clip against (§ A5).
    if recipe.get("clip_model") and not recipe.get("always_visible"):
        clip = _room_outline_world(recipe)
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


def _plate_top(recipe: Dict[str, Any]) -> float:
    """How far a room's floor lifts what stands on it, over its storey datum.

    THE ONE PLACE THIS IS DECIDED — the room's own plate reads it
    (``_plates``), and so does everything that stands on that plate: props,
    markers and the room diorama.

    **ON STOREY 0 THE ANSWER IS ZERO, for every kind of room** (E5a): the
    terrain IS the floor, there is no plate to stand on, and a prop measures
    from the ground under its own anchor. That single line replaces the whole
    ``slab`` apparatus — 0.08 where a location drew a floor, 0.00 where it did
    not, plus a 1 cm anti-z-fight hair on every zone — which existed only to
    keep two grounds apart.

    On a DECLARED storey (an upper floor, a basement) nothing has moved:

    * a BUILT room has a floor plate with a body — its top (0.10);
    * an OUTDOOR room is a pure texture surface (§ A5), laid on the level plate
      plus the hair that keeps the two from z-fighting (0.08 + 0.01);
    * the GROUND (§ A13a) draws no surface of its own — it IS the yard — so its
      placements stand DIRECTLY on the level plate (0.08). It only ever exists
      on storey 0, so in practice it takes the 0 above.
    """
    if int(recipe.get("level") or 0) == 0:
        return 0.0
    if recipe.get("is_ground"):
        return LEVEL_PLATE_TOP
    if recipe.get("always_visible"):
        return LEVEL_PLATE_TOP + OVERLAY_SURFACE_LIFT
    return ROOM_PLATE_TOP


def _prop_models(recipe: Dict[str, Any], storey: float,
                 ) -> List[Dict[str, Any]]:
    """The room's prop placements as specs (REAL-SIZE rule, § A2).

    A placement never scales its prop: the size comes from the prop's own
    dims. Dangling ids and props without a mesh keep their placement and
    carry ``placeholder_dims`` so the consumer can draw a box.
    Furniture stands ON the room's floor (plate top + clearance). On storey 0
    that floor is the TERRAIN and ``_plate_top`` answers 0, so a prop's base is
    the clearance alone — the client puts it on the ground under its own anchor
    and the height ladder has exactly one rung there (E5a).

    GROUND OFFSET (§ B2 addendum 2026-08-20): the PROP may declare how deep it
    stands in the ground (the VARIANT's ``ground_offset_m``, ± 5 m, carried
    onto the recipe placement by ``room_recipe._carry_ground_offset``). It is added to
    the automatic base HERE and nowhere else on this path, and the placement's
    own ``offset_y`` stays what it always was — the per-instance trim on top.

    MODEL VARIANTS (E2.3, § B2 addendum): a prop may carry several meshes of
    the same object. ``model_variants`` is one tier-map per ACTIVE variant, in
    the prop's own order, and ``variant`` says which of them THIS placement
    shows. ``variants`` stays what it always was — the PRIMARY variant's tier
    map, i.e. ``model_variants[0]`` — so a consumer that never heard of
    variants renders exactly what it rendered before. The index is resolved
    here, not in the renderers: the same copy must show the same mesh in the
    3D client, in the admin preview and in the smoke.

    PICTURE AREAS (spec-picture-props.md § 5): ``slots`` says what is IN the
    prop's fillable surfaces — the prop's ``area_defaults`` overlaid with the
    resolved variant's ``slot_values`` (:func:`_slot_spec`). Absent when there
    is nothing to say.
    """
    from app.core import props as prop_store
    level = int(recipe.get("level") or 0)
    room_id = recipe.get("room_id") or ""
    plate_top = _plate_top(recipe)
    floor_y = _room_floor_y(recipe, storey) + plate_top + PROP_CLEARANCE
    out: List[Dict[str, Any]] = []
    for placement in recipe.get("placements") or []:
        pid = str(placement.get("prop_id") or "")
        dims_raw = placement.get("dims") or {}
        dims = [_num(dims_raw.get("width_m"), 1.0), _num(dims_raw.get("depth_m"), 1.0),
                _num(dims_raw.get("height_m"), 1.0)]
        at = placement.get("at") or [0.0, 0.0]
        anchor_u = _num(at[0])
        anchor_v = _num(at[1])
        has_model = bool(placement.get("has_model"))
        prop = prop_store.get_prop(pid) if pid else None
        model_variants = (_prop_variant_urls(pid, placement)
                          if has_model else [])
        spec: Dict[str, Any] = {
            "role": "prop",
            "id": pid,
            # The PRIMARY variant's tier map — unchanged for every prop that
            # has one variant, which is every prop until an admin adds a
            # second one.
            "variants": model_variants[0] if model_variants else {},
            "room_id": room_id,
            "level": level,
            "fix_euler": _fix_euler((prop or {}).get("rotation")),
            "yaw_deg": _r(_num(placement.get("yaw")), 1),
            "max_m": _r(max(dims)),
            "measure": "xyz",
            "anchor": [_r(anchor_u), _r(anchor_v)],
            # THE EFFECTIVE BASE (§ B2 addendum 2026-08-20): the automatic
            # floor, the PROP's own ground offset (a sunk trunk sinks in every
            # room alike) and the PLACEMENT's trim, in that order. Both are
            # added in exactly one place per path — the offset never rides on
            # `floor_y`, which is shared by every placement of the room.
            "bottom_y": _r(floor_y + _num(placement.get("ground_offset_m"))
                           + _num(placement.get("offset_y"))),
        }
        # Only a prop that really HAS more than one variant says so: a
        # one-element list beside an identical `variants` map would be the
        # same fact twice in every payload of every world.
        if len(model_variants) > 1:
            spec["model_variants"] = model_variants
            spec["variant"] = _variant_index(placement, len(model_variants))
        # WHAT IS IN THE PICTURE AREAS (spec-picture-props.md § 5).
        slots = _slot_spec(prop, placement, model_variants)
        if slots:
            spec["slots"] = slots
        # WALKABLE (v6): only a prop that carries the tag ships its surface —
        # a table's lattice would be dead weight in every payload.
        tags = [str(t).lower() for t in ((prop or {}).get("tags") or [])]
        if "walkable" in tags:
            spec["walkable"] = True
            store_variant = _store_variant_index(placement, model_variants)
            surface = prop_store.surface_for(pid, store_variant) if has_model else None
            if surface:
                spec["surface"] = surface
        # The DEPTH CUT, already turned into a plane in world metres — the
        # renderers only hand it to a material (§ B2 addendum 2026-08-23).
        cut = depth_cut_plane(anchor_u, anchor_v, _num(placement.get("yaw")),
                              dims[1], _num(placement.get("cut_keep"), 1.0),
                              str(placement.get("cut_side") or "back"))
        if cut:
            spec["cut_plane"] = cut
        if not has_model:
            spec["placeholder_dims"] = {"w": _r(dims[0]), "d": _r(dims[1]),
                                        "h": _r(dims[2])}
        out.append(spec)
    return out


def _slot_spec(prop: Optional[Dict[str, Any]], placement: Dict[str, Any],
               model_variants: List[Dict[str, str]]) -> Dict[str, Any]:
    """WHAT one placement shows in its prop's picture areas: the prop's
    ``area_defaults``, overlaid with the ``slot_values`` of the VARIANT this
    placement resolves to (spec-picture-props.md § 5).

    Two sources, one merge, in that order: the defaults are the prop-wide
    statement (a door's pane), the variant's values are the picture somebody
    hung on THIS version of the frame. A placement whose variant shows nothing
    of its own — every placement of every ordinary prop — therefore gets the
    defaults alone, and a prop with neither gets nothing at all: an EMPTY
    result is an ABSENT key, because a renderer reads "no slots" as "render
    the mesh as it was modelled" and an empty object would say the same thing
    in every payload of every world.

    NO SECOND GATE: the values were checked against the prop's real areas when
    the variant was saved (``props.set_variant_slot_values``), so the recipe
    copies them verbatim. The variant is resolved with the ONE rule
    (:func:`_variant_index` → position in the published list → that entry), so
    the picture a copy shows and the mesh it shows come from the same entry.
    """
    if not prop:
        return {}
    out: Dict[str, Any] = dict(prop.get("area_defaults") or {})
    entries = placement.get("variant_tiers")
    if isinstance(entries, list) and entries:
        pos = _variant_index(placement, len(model_variants) or len(entries))
        if 0 <= pos < len(entries) and isinstance(entries[pos], dict):
            out.update(entries[pos].get("slot_values") or {})
    return out


def _door_prop_models(doorways: List[Dict[str, Any]],
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """The door props of a location as ``models[]`` specs (§ B2 v5), plus the
    ``{prop_id: model_signature}`` of the props they name.

    The second half is for the scene signature and nothing else: a door prop's
    URL never changes when its mesh is regenerated, so without the signature a
    running client would keep the old leaf forever — the same reason a room
    placement carries ``model_sig`` (``room_recipe._join_placements``).

    ONE spec per threshold that :func:`door_prop_id` gave a prop — a door two
    rooms share is one hole, so it is one door, and the dedup in
    :func:`_doorways` has already made it one entry. Call this AFTER
    :func:`threshold_base_y` has settled ``base_y``: a door prop stands on the
    threshold, not in it.

    NOT REAL-SIZE, and the only such spec in this file: a door prop is FITTED
    to the hole it fills (``measure "fit"``, ``size_m`` = the clear width and
    height of the doorway). A frame that is 5 cm too narrow is a lit gap in a
    wall, so the opening wins over the mesh's own metres — the renderer scales
    x to the width, y to the height and z with the width factor, keeping the
    leaf's depth in proportion.

    THE ANCHOR IS THE HINGE EDGE, not the middle, because that is the point a
    renderer swings the leaf about (the client's own view state, never the
    server's). Looking ALONG ``along``, hinge ``left`` is the end the
    direction comes from::

        left :  at_world − along · width/2
        right:  at_world + along · width/2

    and ``yaw_deg`` turns the model's local +x onto the direction the leaf
    RUNS, away from its hinge: three's ``Ry(+θ)`` (= the server's
    ``local_to_world``, § A1.1) puts local +x on ``(cos θ, −sin θ)``, so
    ``θ = atan2(−uz, ux)`` for a left hinge and 180° more for a right one.
    The shared ``place()`` hangs a ``fit`` model on its own local −x edge, so
    those two numbers together put the mesh exactly in the hole.

    ``door.swing`` is the sign of "a POSITIVE rotation about y opens the leaf
    outward". Turning the placed group by φ moves a world offset (vx, vz) with
    ``d/dφ|₀ = (vz, −vx)``, and the free end of the leaf sits at ``v = +along``
    (left hinge) or ``v = −along`` (right hinge); ``(uz, −ux)`` IS
    :func:`_door_outward`, the normal away from the room the hole was cut out
    of. Hence +1 for a left hinge, −1 for a right one.

    ``door.leaf_bbox`` (spec-picture-props.md § 6) rides along when the prop
    sidecar carries one — the ``leaf`` node's box in raw model metres — and
    is absent otherwise; nothing here measures a mesh.

    A prop id that names nothing (or a prop without a mesh) keeps its spec
    with an EMPTY ``variants`` map — the same rule dangling room-prop
    placements follow. It carries no ``placeholder_dims``: a stand-in box is
    drawn centred on its anchor, and this anchor is an edge, so the box would
    stand half a door beside the hole.
    """
    from urllib.parse import quote

    from app.core import props as prop_store
    out: List[Dict[str, Any]] = []
    sigs: Dict[str, str] = {}
    for index, door in enumerate(doorways):
        info = door.get("_door_prop") or {}
        pid = str(info.get("id") or "")
        if not pid:
            continue
        hinge = "right" if info.get("hinge") == "right" else "left"
        along = door.get("along") or [1.0, 0.0]
        ux, uz = _num(along[0]), _num(along[1])
        width = _num(door.get("width_m"))
        edge = (width / 2) * (1.0 if hinge == "right" else -1.0)
        yaw = math.degrees(math.atan2(-uz, ux)) + (180.0 if hinge == "right"
                                                   else 0.0)
        prop = prop_store.get_prop(pid) or {}
        has_model = bool(prop.get("has_model"))
        sigs[pid] = str(prop.get("model_signature") or "")
        out.append({
            "role": "prop",
            "id": pid,
            "variants": (_variants(f"/assets/props/{quote(pid)}/model",
                                   prop.get("model_tiers"))
                         if has_model else {}),
            # The room the hole was cut out of — a threshold names it first,
            # and that is the parent a renderer hangs the leaf in.
            "room_id": (door.get("rooms") or [""])[0],
            "level": int(door.get("level") or 0),
            "fix_euler": _fix_euler(prop.get("rotation")),
            "yaw_deg": _r(yaw % 360, 1),
            "measure": "fit",
            "size_m": [_r(width), _r(_num(door.get("height_m")))],
            "anchor": [_r(_num(door["at_world"][0]) + ux * edge),
                       _r(_num(door["at_world"][1]) + uz * edge)],
            "bottom_y": _r(_num(door.get("base_y"))),
            # `leaf_bbox` (spec-picture-props.md § 6): the box of the prop's
            # `leaf` NODE in raw y-up model metres, copied off the prop
            # sidecar so a renderer hangs the leaf's pivot without measuring
            # (§ B5a). Absent when the mesh has no leaf node — then the
            # whole group swings, as before. Ruling R13: WHERE the pivot goes
            # is the shared package's `leafPivot`, which states the rule in
            # the FIXED frame (x = min, y = min, z = centre of the box turned
            # by `fix_euler` above) and maps it back — the yaw already turns a
            # right-hinged door 180° onto the same jamb, so `hinge` only feeds
            # the swing sign. With `fix_euler` 0 that is (min.x, min.y,
            # centre z), the earlier R12 wording.
            "door": {"opening": index, "hinge": hinge,
                     "swing": 1 if hinge == "left" else -1,
                     **({"leaf_bbox": prop["leaf_bbox"]}
                        if isinstance(prop.get("leaf_bbox"), dict) else {})},
            # A door prop has no variants (see the note below), so its panes
            # come from the PROP's own defaults and from nothing else
            # (spec-picture-props.md § 5) — absent when it declares none.
            **({"slots": dict(prop.get("area_defaults") or {})}
               if prop.get("area_defaults") else {}),
        })
    return out, sigs


def depth_cut_plane(anchor_u: float, anchor_v: float, yaw_deg: float,
                    depth_m: float, keep: float, side: str,
                    ) -> Optional[Dict[str, Any]]:
    """THE DEPTH CUT as a FINISHED PLANE (§ B2 addendum 2026-08-23) — half a
    table against a wall, without a second prop in the library.

    Returns ``{"normal": [nx, 0, nz], "constant": c}`` in the payload's own
    world metres, with the renderer's rule: a fragment is KEPT where
    ``n·p + c >= 0``. That is exactly ``THREE.Plane``'s convention, so the
    consumer builds one object and hands it to the material — no renderer
    decides where the cut runs (the finding of § B5: geometry exists once).
    ``None`` for a prop that is not cut at all.

    The cut always runs across the prop's DEPTH, i.e. its LOCAL z axis, and it
    turns with the placement yaw. ``side`` names the half that REMAINS:
    ``"front"`` is the side the floor plan draws at the TOP of an unturned
    footprint (local −z), ``"back"`` the bottom (local +z). The prop hangs on
    its own centre (§ B2 step 3), so local z runs −d/2 … +d/2 and the plane
    sits at

        back:   z_cut = +d/2 − keep·d,  n_local = (0, 0, +1)
        front:  z_cut = −d/2 + keep·d,  n_local = (0, 0, −1)

    turned into the world by the SAME rotation the mesh gets
    (``R_y(+yaw)``, § A1.1): ``n = σ·(sin θ, 0, cos θ)`` and, with the plane
    point ``P = anchor + z_cut·(sin θ, 0, cos θ)``, ``c = −n·P``.

    The cut face stays OPEN — this is a clipping plane, not CSG. Consumers draw
    the cut mesh double-sided so the hollow does not show through.
    """
    if not (0 < keep < 1) or depth_m <= 0:
        return None
    sigma = -1.0 if side == "front" else 1.0
    z_cut = sigma * (depth_m / 2.0) - sigma * keep * depth_m
    th = math.radians(yaw_deg)
    dir_x, dir_z = math.sin(th), math.cos(th)
    nx, nz = sigma * dir_x, sigma * dir_z
    px = anchor_u + z_cut * dir_x
    pz = anchor_v + z_cut * dir_z
    return {"normal": [_r(nx, 4), 0.0, _r(nz, 4)],
            "constant": _r(-(nx * px + nz * pz), 4)}


def _prop_variant_urls(prop_id: str,
                       placement: Dict[str, Any]) -> List[Dict[str, str]]:
    """One tier-map per ACTIVE model variant of a prop, in the prop's own
    order (§ B2 addendum) — element 0 is the PRIMARY variant.

    Each map is built exactly like the single ``variants`` map has always
    been (:func:`_variants`), plus the ``variant`` query the serving route
    reads (``…/model?variant=2&tier=low``); the primary one keeps the bare URL
    it always had, so nothing already cached by a client is invalidated by the
    feature existing.

    A recipe that carries no ``variant_tiers`` (a prop with one variant)
    yields the single primary map — the same list ``[variants]``, so the
    caller has one shape to reason about.

    The URL index is the entry's OWN ``variant`` number, never its position in
    the list: switching variant 1 off leaves the payload with 0 and 2, and a
    position would serve the very mesh the admin just switched off.
    """
    from urllib.parse import quote
    base = f"/assets/props/{quote(prop_id)}/model"
    entries = placement.get("variant_tiers")
    if not isinstance(entries, list) or not entries:
        return [_variants(base, placement.get("model_tiers"))]
    out: List[Dict[str, str]] = []
    for pos, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        idx = int(entry.get("variant") or 0)
        # The PRIMARY variant (list position 0) keeps the bare URL it has
        # always had, whatever its store index — that identity is what keeps
        # existing client caches valid.
        out.append(_variants(base if pos == 0 else f"{base}?variant={idx}",
                             entry.get("tiers")))
    return out


def _variant_index(placement: Dict[str, Any], count: int) -> int:
    """WHICH variant this placement shows — the resolved index into
    ``model_variants``.

    Scattered copies carry the number the recipe already computed with the
    one formula ``(scatter_seed + instance) mod count``
    (``props.scatter_variant_index``); a manually placed prop carries whatever
    the editor set, and 0 — the primary variant — until it sets anything. Out
    of range wraps rather than 404s: the variant count moves when an admin
    adds or deletes a mesh, and a stored index must not make a placement
    disappear."""
    try:
        i = int(placement.get("variant") or 0)
    except (TypeError, ValueError):
        return 0
    return i % count if count > 0 else 0


def _store_variant_index(placement: Dict[str, Any],
                         model_variants: List[Dict[str, str]]) -> Optional[int]:
    """The STORE index of the variant this placement shows (None = primary).

    Two numbers meet here and they are not the same one:
    :func:`_variant_index` answers with a POSITION in ``model_variants`` (the
    list of variants that are effectively active AND have a mesh), while the
    prop library addresses a variant by its position in the FULL variant list
    — the number ``props._published_entry`` writes into each entry as
    ``variant``, and the very number the serving URL names. Switching variant
    1 off leaves positions 0, 1 over store indices 0, 2. So the position is
    resolved through the entry's own number, exactly as
    :func:`_prop_variant_urls` builds its URLs."""
    entries = placement.get("variant_tiers")
    if not isinstance(entries, list) or len(model_variants) <= 1:
        return None
    pos = _variant_index(placement, len(model_variants))
    try:
        return int(entries[pos].get("variant") or 0)
    except (IndexError, AttributeError, TypeError, ValueError):
        return None


# ── Markers, figures ────────────────────────────────────────────────────

def marker_slots(at: Tuple[float, float], facing_deg: Optional[float],
                 capacity: int, spacing_m: float) -> List[List[float]]:
    """The seats of one marker, world metres, centred on the marker along the
    axis ACROSS the facing (a bench runs sideways). Facing 0 = south (+z),
    90 = east (+x); the lateral unit vector is the facing turned by +90°:
    (cos f, −sin f). Capacity 1 is the marker itself."""
    n = max(1, int(capacity))
    if n == 1:
        return [[_r(at[0]), _r(at[1])]]
    f = math.radians(float(facing_deg or 0.0))
    lx, lz = math.cos(f), -math.sin(f)
    return [[_r(at[0] + (i - (n - 1) / 2.0) * spacing_m * lx),
             _r(at[1] + (i - (n - 1) / 2.0) * spacing_m * lz)] for i in range(n)]


def _markers(recipe: Dict[str, Any], room: Dict[str, Any], storey: float,
             ) -> List[Dict[str, Any]]:
    """Every marker of one room, finished in world coordinates — as PLACES
    (plan-posen-plaetze.md § 3.3/3.4): a stable ``id``, the place type
    ``group``, a ``label`` for the chip, and the finished ``slots`` a figure
    can take (``capacity`` of them, ``spacing_m`` apart across the facing;
    capacity 1 ⇒ ``slots == [at_world]``). Nothing downstream computes a slot.

    Room markers are METRES from the room's min corner (v6 Nr. 2) with an
    offset additive to the sampled floor. On the GROUND that corner is the
    location's own origin (§ A13a) — the layout's absent ``x``/``y`` already
    read as 0/0, so the anchor is the stored metre verbatim. Their id is the
    marker's own; a prop marker is ``"<placement.id>/<marker.id>"`` and its
    label the placement's, else the prop's name, else the group label.

    Prop markers arrive from the recipe as placement-relative transforms
    (fix → real size → yaw already applied) and only need ``placement point +
    [dx, dz]`` — resolved here, so the consumer adds nothing.

    ``y_world`` is the SURFACE the marker names. How far below it a figure's
    root belongs travels with the marker as ``root_offset`` (world metres:
    the group's ``root_drop`` × figure height, read from the pose catalog) —
    a seated body touches at the buttocks, not at the feet. That number used
    to live in the 3D client alone and only for ROOM markers, so prop markers
    had no drop at all and every author baked one into the marker by hand.
    One source, both renderers, both marker sources.

    A marker whose group the catalog does not know is no place and is skipped.

    ``y_world`` measures from the room's STOREY DATUM, which on storey 0 is the
    terrain itself (E5a) — so a marker on the ground says "this far over the
    ground under it" and the consumer samples ``h_final`` there.
    """
    from app.core.pose_catalog import get_groups
    room_id = recipe.get("room_id") or ""
    floor_y = _room_floor_y(recipe, storey)
    x, y, w, d = _room_rect(recipe, room)
    # A room marker is a spot IN the room, so it rides the room's own turn —
    # position through the room transform, facing by the same angle (compass
    # facing grows in the same sense as a placement yaw, § A1.8).
    place = room_transform(room.get("layout"))
    room_yaw = layout_rotation(room.get("layout"))
    figure_h = FIGURE_HEIGHT_M
    groups = get_groups()

    def _root_drop(group: str) -> float:
        """World metres a figure's root sinks below the marked surface
        (millimetres — a drop is a body measure, not a survey point)."""
        return _r(float(groups[group].get("root_drop") or 0.0) * figure_h, 3)

    out: List[Dict[str, Any]] = []
    for marker in recipe.get("markers") or []:
        group = str(marker.get("group") or "").strip().lower()
        if group not in groups:
            continue
        at = marker.get("at") or [w / 2, d / 2]
        anchor_u, anchor_v = place(_num(at[0], w / 2), _num(at[1], d / 2))
        facing: Optional[float] = None
        if marker.get("rotation") is not None:
            facing = _r((_num(marker.get("rotation")) + room_yaw) % 360, 1)
        cap = max(1, int(_num(marker.get("capacity"), 1)))
        entry: Dict[str, Any] = {
            "room_id": room_id,
            "id": str(marker.get("id") or ""),
            "group": group,
            "label": str(groups[group].get("label") or group),
            "capacity": cap,
            "at_world": [_r(anchor_u), _r(anchor_v)],
            "slots": marker_slots((anchor_u, anchor_v), facing, cap,
                                  _num(marker.get("spacing_m"), 0.6)),
            "y_world": _r(floor_y + _num(marker.get("offset_y"))),
            "root_offset": _root_drop(group),
            "source": "room",
        }
        if facing is not None:
            entry["facing"] = facing
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
    prop_lift = _plate_top(recipe) + PROP_CLEARANCE
    for marker in recipe.get("prop_markers") or []:
        group = str(marker.get("group") or "").strip().lower()
        if group not in groups:
            continue
        try:
            placement = placements[int(marker.get("placement"))]
        except (TypeError, ValueError, IndexError):
            continue
        at = placement.get("at") or [0.0, 0.0]
        offset = marker.get("offset_m") or [0.0, 0.0]
        au = _num(at[0]) + _num(offset[0])
        av = _num(at[1]) + _num(offset[1])
        # A prop marker ALWAYS carries a composed facing (§ B, facing default).
        facing = (_r(_num(marker.get("facing")), 1)
                  if marker.get("facing") is not None else None)
        cap = max(1, int(_num(marker.get("capacity"), 1)))
        # The marker belongs to its PLACEMENT: it is sampled at the prop's
        # anchor, not at its own offset point, so a bench and every seat on
        # it rise by exactly the same amount and the mesh stays level.
        entry = {
            "room_id": room_id,
            "id": f"{placement.get('id') or ''}/{marker.get('id') or ''}",
            "group": group,
            "label": str(placement.get("label") or placement.get("prop_name")
                         or groups[group].get("label") or group),
            "capacity": cap,
            "at_world": [_r(au), _r(av)],
            "slots": marker_slots((au, av), facing, cap,
                                  _num(marker.get("spacing_m"), 0.6)),
            # THE MARKER RIDES THE MESH (§ B2 addendum 2026-08-20): a sunk
            # trunk sinks its seat with it, so the placement's ground offset is
            # added here as well — the same term the prop spec adds to its
            # `bottom_y`, which keeps `y_world - bottom_y` the marker's own
            # composed height. (The placement's `offset_y` is already inside
            # `height_m`, composed by `room_recipe.compose_prop_marker`.)
            "y_world": _r(floor_y + prop_lift + _num(marker.get("height_m"))
                          + _num(placement.get("ground_offset_m"))),
            "root_offset": _root_drop(group),
            "source": "prop",
        }
        if facing is not None:
            entry["facing"] = facing
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
               ground_kind: str = "",
               door_prop_sigs: Optional[Dict[str, str]] = None,
               surface_sigs: Optional[Dict[str, str]] = None) -> str:
    """Change detection for the whole scene — a SUPERSET of the room recipe's
    signature: the room signatures already cover layouts, neighbour openings
    and prop sidecars, and the model metas add every anchor dial (floors,
    height_m, width_m, walk_y, rotation, offsets). Polling it is enough.

    ``ground_kind`` is in here as the RESOLVED kind, not as the raw
    ``terrain`` text: it is what the payload carries, and it also moves when
    the library gains or loses the entry a terrain names.

    THE SEASON is in here as a token (E2c, 2026-08-20), and it is the one
    input that is not a stored value: a season change swaps prop variants
    (``props._effective_indices``) and surface textures
    (``surface_textures.texture_file``) without touching a single sidecar. The
    room signatures DO move with the variant lists they carry, so props alone
    would be covered — the textures would not, and a running client would keep
    a summer ground under a winter sky until it reloaded. One token settles
    both, and a world without seasons contributes the empty string, i.e. the
    signature it always had.

    :data:`SCENE_RECIPE_VERSION` is in here as ``code_version`` because the
    payload is a function of the CODE as much as of the data: a changed
    geometry rule used to leave every signature exactly where it was, so
    clients and caches kept the old scene until someone saved the location by
    hand. Bumping the constant moves every scene signature at once.

    THE DOOR PROPS are in here twice over (v5): the location's
    ``default_door_prop_id``, which no room signature covers because it is a
    field of the LOCATION, and ``door_prop_sigs`` — the mesh signature of
    every prop a door actually resolved to, for the same reason a room
    placement carries one (a regenerated mesh keeps its URL).

    THE SURFACES are in here for that same reason once more (v6): a lattice
    that was just baked — or has just gone stale — changes no dial, no URL and
    no sidecar the room signature reads, so without ``surface_sigs`` a running
    client would keep walking the old floor. ``surface_sigs`` is the ONLY
    place a lattice enters this hash — the room metas hand theirs over to it
    and travel here without it."""
    import hashlib
    import json
    from app.core.game_time import get_calendar
    from app.core.timeutils import game_time
    try:
        cal = get_calendar()
        season = (cal.seasons[game_time().parts(cal).season_index].key
                  if cal.seasons else "")
    except Exception:
        season = ""
    payload = {
        "code_version": SCENE_RECIPE_VERSION,
        "map3d": location.get("map3d") or {},
        "plan_width_m": round(float(plan_width_m or 0), 3),
        "ground_kind": ground_kind,
        "season": season,
        "rooms": {str(r.get("room_id") or ""): r.get("signature") or ""
                  for r in recipes},
        "building_meta": building_meta or {},
        # The room metas MINUS their lattices: a baked surface is hundreds of
        # kilobytes of integers, and json-dumping it into every signature to
        # md5 it once more would hash the very numbers ``surface_sigs`` has
        # already reduced to eight characters. Dropped, not summarized — the
        # sigs below cover the rooms too.
        "room_metas": {rid: ({k: v for k, v in meta.items() if k != "surface"}
                             if isinstance(meta, dict) else meta)
                       for rid, meta in (room_metas or {}).items()},
        "default_door_prop_id": str(location.get("default_door_prop_id")
                                    or "").strip(),
        "door_props": door_prop_sigs or {},
        "surfaces": surface_sigs or {},
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True,
                                  default=str).encode()).hexdigest()


# ── Composer ────────────────────────────────────────────────────────────

def _boundary_openings(map3d: Dict[str, Any],
                       extent: float) -> List[Dict[str, Any]]:
    """Location-edge pass-throughs (plan-area-detail-scenes.md) in world
    metres — where a road enters and leaves the cell.

    Geometry plus the room link, and both are read: the 3D client offers
    "enter" at an opening and walks the figure in through it (``main.ts``),
    while the server decides entry and departure on the same data
    (``boundary_entry``). Still open is the journey walk-through — an opening
    pair plus the linked room's hull is a path across the cell.

    SINCE v6 (Nr. 5) an opening sits on a POLYGON EDGE: ``edge`` is the
    0-based index of the boundary edge (edge i = point i → i+1) and ``at``
    runs along that edge. The letters N/E/S/W are gone with the square, and
    with them the only place a consumer could have re-derived a point: the
    payload carries the finished ``at_world`` and the ``inward`` normal,
    computed by ``world_geometry.polygon_edge_frame`` — the same function the
    entry gate reads, so picture and rule cannot drift.
    """
    from app.core.world_geometry import polygon_edge_frame
    boundary = _boundary_local(map3d, extent)
    out: List[Dict[str, Any]] = []
    for op in (map3d or {}).get("boundary_openings") or []:
        if not isinstance(op, dict):
            continue
        try:
            width_m = float(op.get("width_m") or 0)
        except (TypeError, ValueError):
            continue
        # ``at`` degrades to the edge MIDPOINT inside ``polygon_edge_frame``
        # — ONE degradation rule for both consumers (E3 ledger: they used to
        # disagree, 0 here and 0.5 in the entry gate, so an opening without a
        # position sat in the corner for the renderers and in the middle for
        # the gate).
        frame = polygon_edge_frame(boundary, op.get("edge"), op.get("at"))
        if frame is None:
            continue
        (px, pz), (nx, nz) = frame
        entry: Dict[str, Any] = {
            "edge": int(op["edge"]),
            "at_world": [_r(px), _r(pz)],
            "width_m": _r(width_m, 3),
            "type": str(op.get("type") or "passage"),
            "inward": [_r(nx), _r(nz)],
        }
        room = op.get("room")
        if isinstance(room, str) and room.strip():
            entry["room_id"] = room.strip()
        out.append(entry)
    return out


# ── The floor plan (E5a) ────────────────────────────────────────────────

def _floor_plan(loc: Dict[str, Any], recipes: List[Dict[str, Any]],
                ) -> List[Dict[str, Any]]:
    """The STOREY-0 rooms as polygons + floor kinds — what replaces the plates.

    Until E5a a consumer found out where a room is by looking at its PLATE:
    the 3D client shot 6 × 6 rays at the plate meshes to find NPC stands, the
    admin preview measured room centres off them. Storey 0 has no plates any
    more (``_plates``), so the polygons travel as data instead — which is what
    they always were.

    ONE ENTRY PER LEVEL-0 ROOM, in recipe order, and every part of it is the
    SAME derivation the ground bake uses: the hull is the recipe's ``outline``,
    which is ``room_recipe.room_outline_local`` — the very polygon
    ``terrain_layers.location_floors`` transforms into world metres — and the
    kind is ``terrain_layers.floor_kind_of``. That identity is the point: the
    material of the ground and the shape a consumer places NPCs on cannot
    disagree, and it is measured in ``scripts/smoke_terrain_layers.py``, which
    puts this list beside the baked mask to the centimetre.

    * ``polygon_world`` — the room hull in the SCENE FRAME (local metres around
      the anchor pin), like every other coordinate in this payload.
    * ``floor_kind`` — what the ground WEARS there; the empty string for a zone
      that declares none (the terrain shows through, and the layer bake paints
      nothing there either).
    * ``closed`` — a room with a shell, as opposed to an open zone (§ A5).
    * ``map_water`` — ``{area_id, kind}`` when this room's hull lies on PAINTED
      water (W1). A REFERENCE and nothing more: the room owns no mirror, no
      depth and no bed, it merely stands where the map says water is, and saying
      so is what lets the plan editor show "Map ground: water — <area>" instead
      of offering per-room water sliders that shape nothing.

    THE REFERENCE IS DERIVED, NEVER STORED, which is why it cannot dangle: it is
    a MAJORITY-AREA containment test (:func:`_map_water_ref`) against the painted
    areas of a water kind, run at compose time. Delete the lake and the line is
    gone with it; move the room off the water and it is gone too.

    The yard (``is_ground``, § A13a) is not in it: it has no hull, it IS the
    plot. An unplaced location yields an empty list — it owns no world metre, so
    no containment could be decided for it either.
    """
    from app.core.terrain_layers import floor_kind_of
    from app.core.world_geometry import (effective_boundary,
                                         polygon_local_to_world)
    eff = effective_boundary(loc)
    waters = _painted_waters() if eff is not None else []
    out: List[Dict[str, Any]] = []
    for recipe in recipes:
        if recipe.get("is_ground"):
            continue
        if int(recipe.get("level") or 0) != 0:
            continue
        outline = _room_outline_world(recipe)
        if not outline:
            continue
        room_id = str(recipe.get("room_id") or "")
        closed = not bool(recipe.get("always_visible"))
        kind = floor_kind_of(recipe, closed)
        entry: Dict[str, Any] = {
            "room_id": room_id,
            "polygon_world": outline,
            "floor_kind": kind,
            "closed": closed,
        }
        if waters:
            # The hull travels to WORLD metres through the ONE transform
            # (§ A1.1) — the scene frame IS the location's local frame, so this
            # is the same polygon ``terrain_layers.location_floors`` builds.
            world = polygon_local_to_world(outline, eff[0], eff[1], eff[2])
            ref = _map_water_ref(world, waters)
            if ref is not None:
                entry["map_water"] = ref
        out.append(entry)
    return out


def _painted_waters() -> List[Dict[str, Any]]:
    """Every painted area of a WATER kind, in priority order (W1).

    ``models.terrain.list_areas`` order, i.e. z_order then paint order — the
    same list ``terrain_query.kind_at`` answers point queries from, so "which
    water is this room on" and "which ground is at this point" cannot name two
    different lakes. A world that flags no kind as water answers an empty list
    and every floor plan below costs nothing.
    """
    from app.core.heightfield import water_areas
    from app.core.terrain_types import effective_catalog
    from app.models.terrain import list_areas
    try:
        return [area for area, _box
                in water_areas(list_areas(), effective_catalog())]
    except Exception:                    # noqa: BLE001 — no world, no water
        logger.warning("floor plan: painted water unreadable — no map "
                       "reference", exc_info=True)
        return []


#: Samples per axis of the majority-area test below. 32 x 32 over the room's
#: bounding box is 1024 probes — fine enough that a room half on the water
#: answers within a percent of its true share, cheap enough to run per room of a
#: scene, and a FIXED number, so the answer is a pure function of the two
#: polygons rather than of how large somebody drew them.
MAP_WATER_SAMPLES = 32


def _map_water_ref(polygon: Optional[List[List[float]]],
                   waters: Sequence[Dict[str, Any]]
                   ) -> Optional[Dict[str, str]]:
    """``{area_id, kind}`` of the painted water a room's hull LIES ON — or None.

    MAJORITY AREA, not "the centre is inside": a room whose middle happens to
    poke out of a bay is still on the lake, and a room that merely touches one
    at a corner is not. The share is measured by sampling the hull's bounding
    box on a fixed :data:`MAP_WATER_SAMPLES` lattice at CELL CENTRES, counting
    the probes inside the hull and, of those, the ones inside the water — the
    ratio of two areas, approximated the one way that needs no polygon clipper.

    LAST CONTAINING AREA WINS on a tie, which is the priority law of the whole
    ground (§ A16.7): ``waters`` arrives in paint order, so a later lake painted
    over an earlier one is the one a room on both is said to lie on.
    """
    from app.core.world_geometry import point_in_polygon
    if not polygon or len(polygon) < 3 or not waters:
        return None
    xs = [float(p[0]) for p in polygon]
    zs = [float(p[1]) for p in polygon]
    min_x, max_x, min_z, max_z = min(xs), max(xs), min(zs), max(zs)
    if max_x <= min_x or max_z <= min_z:
        return None
    step_x = (max_x - min_x) / MAP_WATER_SAMPLES
    step_z = (max_z - min_z) / MAP_WATER_SAMPLES
    probes: List[Tuple[float, float]] = []
    for j in range(MAP_WATER_SAMPLES):
        pz = min_z + (j + 0.5) * step_z
        for i in range(MAP_WATER_SAMPLES):
            px = min_x + (i + 0.5) * step_x
            if point_in_polygon(px, pz, polygon):
                probes.append((px, pz))
    if not probes:
        return None
    best: Optional[Dict[str, str]] = None
    best_share = 0.5
    for area in waters:
        ring = area.get("polygon")
        inside = sum(1 for px, pz in probes if point_in_polygon(px, pz, ring))
        share = inside / len(probes)
        # A MAJORITY, so STRICTLY more than half — a room lying exactly half on
        # the water is not on it, and a tie between two lakes is won by the
        # LATER one (``>= best_share`` once the half is cleared).
        if share > 0.5 and share >= best_share:
            best_share = share
            best = {"area_id": str(area.get("id") or ""),
                    "kind": str(area.get("kind") or "")}
    return best



def layout_signature(map3d: Dict[str, Any],
                     rooms: List[Dict[str, Any]]) -> str:
    """Hash over everything that SHAPES a location's scene: its ``map3d``
    (the drawn boundary, boundary openings, rotation, size, ``plan_width_m``,
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


def scene_inputs(location: Dict[str, Any], location_id: str,
                 building_model_file: str = "", *,
                 with_surface: bool = True,
                 ) -> Tuple[float, Dict[str, Any], Dict[str, Any]]:
    """What :func:`compose_scene` needs beside the location: plan width, the
    building model's meta and one meta per laid-out room (each a
    ``get_client_meta`` dict, surfaces included).

    ``with_surface=False`` leaves the baked lattices out of the room metas —
    for a consumer that DRAWS the scene and never walks it (the admin's
    floor-plan preview, Minor 10). A lattice is a few hundred kilobytes per
    room and reading it costs a JSON parse per model; the preview would ship
    all of that on every keystroke of the plan editor and use none of it.

    Clones need no special handling: the model store redirects them to their
    template (gallery owner) and room ids are template-identical, so the same
    call works for template and clone.

    Lived in ``routes/play.py`` until the server's own walk gate needed it
    (spec-surface-height § 7) — a route may not be the only way to the
    composer's inputs."""
    from app.core.location_model3d import derive_plan_width_m, get_client_meta
    map3d = location.get("map3d") or {}
    if not location_id:
        try:
            plan_width_m = float(map3d.get("plan_width_m") or 0)
        except (TypeError, ValueError):
            plan_width_m = 0.0
        return plan_width_m, {}, {}
    room_metas: Dict[str, Any] = {}
    for room in location.get("rooms") or []:
        if not isinstance(room, dict) or not room.get("layout"):
            continue
        rid = str(room.get("id") or "")
        meta = get_client_meta(location_id, room_id=rid,
                               with_surface=with_surface) if rid else None
        if meta:
            room_metas[rid] = meta
    return (derive_plan_width_m(location_id, map3d),
            get_client_meta(location_id, filename=building_model_file) or {},
            room_metas)


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
                                variant_seed=variant, map3d=map3d)
        if not recipe:
            continue
        recipes.append(recipe)
        by_room[str(room.get("id") or "")] = room
    levels = _used_levels(recipes)

    # The location's own fallback door prop (v5, user decision 2026-08-27):
    # an opening that names none takes this one, and ``door_prop: "none"``
    # opts out of it. Resolved in :func:`door_prop_id`, nowhere else.
    default_door_prop_id = str(location.get("default_door_prop_id")
                               or "").strip()

    # Thresholds as finished primitives (plan-betreten-und-tueren.md § 4.1) —
    # composed BEFORE the shell, because the shell takes its holes from them
    # (§ 4.2). One derivation, two consumers: this block and the payload.
    doorways = _doorways(recipes, storey, default_door_prop_id)

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
        hull = _room_outline_world(recipe)
        if hull:
            level = int(recipe.get("level") or 0)
            room_hulls.setdefault(level, []).append(hull)
            shell_levels.add(level)

    # Every OUTSIDE door as a hole for the hull: middle, outward normal, clear
    # width and the world height of its head, straight off the doorway — the
    # contour projects them, it does not measure a door of its own (§ 4.2).
    # ``top_y`` is read HERE, before :func:`threshold_base_y` lifts ``base_y``
    # onto a declared walking surface: the door's head stands over the wall's
    # own foot, which is what the wall it pierces is built from.
    outside_doors = [{"level": d["level"], "at": d["at_world"],
                      "width": d["width_m"], "normal": _door_outward(d),
                      "top_y": _num(d["base_y"]) + _num(d["height_m"]),
                      # …and whether the hull's hole gets a LEAF: a door has
                      # one, an open passage has not.
                      "leaf": str(d.get("type") or "door") == "door",
                      # …and whether a PROP fills that leaf's place (v5).
                      "door_prop": bool((d.get("_door_prop") or {}).get("id"))}
                     for d in doorways if d.get("outside")]

    walls: List[Dict[str, Any]] = _contour_walls(map3d, levels, storey,
                                                 outside_doors, room_hulls)
    # WHICH SHAPE COUNTS AS "the floor plan" — the SAME fallback the level
    # plate is built on (``_plates``): the drawn building outline, else the
    # drawn boundary. Without the second half a boundary-only location had no
    # contour at all, so every room counted as lying OUTSIDE it (a bbox can
    # never be inside nothing) and became a zone on a model that may not even
    # exist. It only became visible with the metric wave (8672c756), which
    # gave those locations a level plate to be buried under.
    contour_world = _outline_world(map3d) or _drawn_boundary(map3d)
    # THE ``slab`` IS GONE (E5a). It was the top of the storey-0 plate — 0.08
    # where a location drew a floor, 0.0 where it did not — and every anchor in
    # this composer measured from it. On storey 0 the floor is the terrain, so
    # the datum is 0 for every location alike (:func:`storey_floor_y`) and the
    # question "does this place draw a floor" only survives where it decides
    # whether the BAKE stamps a plateau — ONE spelling of it, and it lives on
    # the stored location: ``models.heightfield.draws_built_floor``.
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
    overlay_rooms: Dict[str, Dict[str, Any]] = {}
    if area_model:
        outside_indoor: List[Tuple[str, List[List[float]]]] = []
        outside_outdoor: List[Dict[str, Any]] = []
        for recipe in recipes:
            outline = _room_outline_world(recipe)
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
            outline = _room_outline_world(recipe)
            xs = [p[0] for p in outline]
            zs = [p[1] for p in outline]
            cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
            if building:
                y = _num(building.get("walk_y_world"),
                         _num(building.get("bottom_y")))
            else:
                # No model: the zone lies on the floor of its storey, which on
                # storey 0 is the TERRAIN itself (:func:`storey_floor_y`).
                y = storey_floor_y(int(recipe.get("level") or 0), storey)
            # The room's own height offset applies here exactly as it does to a
            # built room's plate.
            y += _num(recipe.get("floor_offset_y"))
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
        walls.extend(_room_walls(recipe, storey, min(levels),
                                 default_door_prop_id))
        diorama = _diorama_model(recipe, room, room_metas.get(room_id) or {},
                                 storey)
        if diorama:
            models.append(diorama)
        models.extend(_prop_models(recipe, storey))
        markers.extend(_markers(recipe, room, storey))

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

    # DOOR PROPS (v5) — after the thresholds have found their standing height,
    # because a door prop stands ON its threshold. The resolution rode in on
    # the doorway (``_door_prop``) and leaves the payload again right here:
    # the model spec is its only consumer, and the same fact twice in one
    # payload is exactly what § B5 forbids.
    door_props, door_prop_sigs = _door_prop_models(doorways)
    models.extend(door_props)
    for door in doorways:
        door.pop("_door_prop", None)

    # Per-room recipe vocabulary in LOCAL METRES — the 2D editor's ghost
    # openings draw from here instead of re-deriving the mirroring locally
    # (v4: no geometry twice). Pure pass-through of the room recipe: the
    # openings are already normalized AND mirrored in.
    room_blocks = []
    for r in recipes:
        # The GROUND never appears as a room block (§ A13/A13a): it has no
        # hull, no openings and no plate — it contributes props and markers
        # and nothing else.
        if r.get("is_ground"):
            continue
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

    # One short hash per placement that ships a lattice — the only form in
    # which a lattice enters the scene signature (``_signature`` drops it from
    # the room metas). A room's lattice reaches the hash through no other
    # input, and a PROP's through none at all, so without this a freshly baked
    # crate would never reach a running client.
    #
    # THE VARIANT IS PART OF THE KEY: two copies of the same crate in the same
    # room may show DIFFERENT meshes with different lattices, and role + id +
    # room alone would let the second one overwrite the first in this dict —
    # a bake of the swallowed variant would then move nothing. Two copies of
    # the SAME variant do collide, and that is right: their block is the same
    # block, so one entry says everything two would.
    from app.core.model_surface import block_sig
    surface_sigs = {
        f"{m.get('role')}:{m.get('id')}:{m.get('room_id', '')}:{m.get('variant', 0)}":
            block_sig(m["surface"])
        for m in models if isinstance(m, dict) and m.get("surface")}

    out = {
        "signature": _signature(location, plan_width_m, recipes,
                                building_meta, room_metas, ground_kind,
                                door_prop_sigs, surface_sigs),
        "rooms": room_blocks,
        # The location's FOOTPRINT as a polygon in the scene frame (contract
        # v6 Nr. 1 + Nr. 4): the drawn ``map3d.boundary`` where there is one,
        # the synthesized square as its four corners otherwise. The scene frame
        # IS the local frame around the anchor pin, so these are the very
        # points the world map draws — no consumer transforms them a second
        # time, and none of them synthesizes a square of its own any more.
        "boundary": _boundary_local(map3d, extent),
        # extent_m = the width of the location's bounding box in metres.
        # Since v6 (Nr. 2) it converts NOTHING any more — every coordinate in
        # this payload is already a metre — but it stays, because consumer
        # contracts are built on it (loading radius, viewport, backdrop) and
        # because it is the edge of the terrain frame. Consumers must read it
        # instead of assuming a constant (they used to assume 8).
        "extent_m": _r(extent),
        # k = world metres per real metre. CONSTANT 1 since E4 — the field
        # stays because consumers multiply by it (× 1 is right for them),
        # not because it can be anything else.
        "k": _r(k, 6),
        "storey_m": _r(storey),
        "levels": [{"level": lv, "floor_y": _r(lv * storey)} for lv in levels],
        "style": STYLE,
        # THE FLOORS OF THE DECLARED STOREYS ONLY (E5a). Storey 0 has none —
        # its floor is the terrain and its material is the layer bake — so what
        # is left here is upper floors and basements. An overlay zone still
        # gets no plate from the normal path: it lies ON an area model.
        "plates": _plates(map3d,
                          [r for r in recipes
                           if str(r.get("room_id") or "") not in overlay_rooms],
                          levels, storey, ground_kind),
        # THE STOREY-0 ROOMS AS DATA, which is what replaces those plates: the
        # polygons a consumer needs for room spots, NPC stands and labels
        # (``_floor_plan``). Heights are not in it on purpose — they come from
        # the height sampler, at the point the consumer actually asks about.
        "floor_plan": _floor_plan(location, recipes),
        "walls": walls,
        # The vertical connections of the building, one flat list: the
        # elevator's shaft primitives and every staircase's steps and pads.
        "extras": (_elevator(map3d, levels, storey)
                   + _stairs(map3d, levels, storey)),
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
        "problems": _problems(location, map3d, shell_levels, doorways,
                              recipes),
    }
    if boundary:
        out["boundary_openings"] = boundary
    # Detail mode is a property of the LOCATION, not of its model: a forest
    # may have no location model at all (the whole point of the detail
    # scenes), and the renderers still need to know — fade gate and zone
    # handling key off this flag; `display: shell_area` on the building spec is
    # merely its per-model consequence.
    if map3d.get("area_model") and map3d.get("area_detail"):
        out["area_detail"] = True
    # ``natural_floor`` IS GONE (E5a). It told a consumer that this location's
    # floor was the terrain rather than a storey slab — a distinction that
    # existed only while there were two grounds. On storey 0 EVERY location's
    # floor is the terrain now, so the flag would be true everywhere and say
    # nothing. The classification survives ONCE, on the stored location, where
    # the PLATEAU STAMP reads it (``models.heightfield.draws_built_floor``) —
    # never as a payload field, and never as a second spelling here (E6).
    return out
