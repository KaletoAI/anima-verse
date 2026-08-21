"""The LAYER CUT of the ground (Ein Boden, E3 — plan-ein-boden.md § G3).

Until E2 the painted terrain was drawn as a STACK: one transparent drape mesh
per painted shape, lying a fraction of a millimetre over the terrain and over
each other, held apart by a `renderOrder` ladder, a `polygonOffset` ladder and
a hairline y ladder — three depth crutches at once — and blended into each
other by an alpha fringe. This module ends that. The ground is ONE surface, and
the material is **cut per texel**: at every point exactly one layer wins, the
one below it is named as the runner-up, and the transition between the two is a
width in METRES that the author sets per ground kind.

WHAT IS BAKED, per 256 m tile of the very lattice the heightfield already keys
its tiles by (`heightfield.TILE_M`, `heightfield.tile_key`):

* an **id mask** at :data:`ID_STEP_M` (1 m) — per texel the PAIR (A, B) of layer
  indices: A the layer that is painted on top at the nearest boundary, B the one
  under it. Two bytes per texel, read with NEAREST.
* an **sd mask** at :data:`SD_STEP_M` (0.5 m) — per texel the SIGNED distance in
  metres to that boundary, positive on A's side, clamped to ±:data:`SD_BAND_M`
  and quantised to one byte. Read with LINEAR filtering.

THE PAIR IS CANONICAL, AND THAT IS THE WHOLE TRICK. Both sides of a boundary
carry the SAME (A, B) — A is always the higher-painted of the two, never "the
one I am standing on". Only the SIGN of `sd` says which side a texel is on. So a
NEAREST fetch of the pair and a LINEAR fetch of the distance compose into a
continuous edge: the id may snap to either side of the boundary without ever
changing which two materials are being mixed, and the sub-texel position of the
cut comes entirely out of the interpolated distance. Ordering the pair by "the
layer here" instead would flip A and B across the line, flip the sign with them,
and tear the edge apart at every texel seam.

…AND THE PAIR IS ONLY CANONICAL PER BOUNDARY, which is the whole reason for the
three rules below (finding round 2026-08-21). A world with more than two grounds
in one neighbourhood has SEVERAL boundaries competing, and a texel that reads
its pair off one of them and its distance off another composes a material that
is at neither: a wooden floor showed the meadow outside the house in metre-wide
chevrons, the beach showed the forest in staircase cracks, and the kitchen's
rubber bled into the living room. Measured, not guessed — the id texel and the
sd texel under it carried the pairs of two DIFFERENT boundaries at exactly the
same distance, i.e. on their medial axis. So:

1. **A BOUNDARY IS A CHANGE OF LAYER, not of paint rank.** Two shapes of the
   same material (three sand zones drawn in three strokes) touch without a
   boundary between them; a seam there used to seed the distance field and pull
   every texel around it off the real edge.
2. **A TEXEL ONLY EVER TAKES A BOUNDARY ITS OWN LAYER IS PART OF.** The sign
   "am I on A's side" is meaningless for a third ground standing near somebody
   else's edge — it used to read as "B", which is how a floor came to show the
   grass of a boundary it is not on either side of.
3. **THE ID TEXEL AND THE FOUR SD TEXELS UNDER IT SPEAK OF ONE BOUNDARY.** The
   id takes the NEAREST of its four, and all four are then signed against THAT
   pair. Beyond the width where the transition is still being drawn
   (:func:`collapse_band_m`) the pair collapses to (own, own) — a texel that is
   far inside one ground needs no runner-up, and not naming one is what keeps a
   medial axis from becoming a hairline of the wrong material.

THE PRIORITY IS THE DATA LAW AND NOTHING NEW: the LAST containing area wins,
in `models.terrain.list_areas` order (z_order, then paint order) — the very rule
`core.terrain_query.kind_at` answers point queries with. The bake fills a raster
of PAINT RANKS (0 = the unpainted world, r = the r-th area of that list) by
painting the areas in that order, so "who is on top" is a comparison of two
integers and the picture and the rules cannot disagree about it. Asserted at 500
lattice probes in `scripts/smoke_terrain_layers.py`.

A LOCATION'S LEVEL-0 FLOORS ARE LAYERS TOO ("Ein Boden" E5, § G3/§ G5). Since
E5a the plate era is over on storey 0: an open zone's sand and a closed room's
parquet are not geometry laid over the ground, they are the ground's TOPMOST
LAYER — the same mask, the same cut, the same width dial. Priority, from the
bottom up: painted terrain areas, then a location's open zones, then its closed
rooms; between two overlapping locations the SMALLER one wins (the containment
law ``location_at_point`` already resolves nesting by). The yard (``is_ground``,
§ A13a) contributes nothing at all — it IS the plateau ground under everything
else. The transition width of a floor is the ROOM's own ``layout.edge_blend_m``
and its default is **0**, the hard cut: a floor ends on the metre it was drawn
on, which is the user's rule for floors and the opposite of a painted meadow's
1.5 m fringe.

WATER IS A LAYER HERE. A kind flagged `meta.water` gets its own layer index like
any other, because the mask is the truth about "which ground is at this point"
for the undergrowth gate and for the priority. What the water SURFACE looks like
is not this module's business — the index answers it with the ``waters`` list
(polygon + mirror height), the same shape a painted lake carries, so a client
renders a room's pond with the machinery it renders a lake with.

PURE AND DETERMINISTIC. Everything below is a function of (areas, catalog,
default kind); the model and the tiles are cached per :func:`layers_sig`, the
same way the height model is cached per generation, and a smoke can build a
world out of literals without a DB.
"""

import base64
import hashlib
import json
import math
from array import array
from collections import OrderedDict
from typing import (Any, Dict, List, NamedTuple, Optional, Sequence,
                    Tuple)

from app.core.log import get_logger

logger = get_logger(__name__)

# ── The lattices ────────────────────────────────────────────────────────────

#: Metres per texel of the ID mask. One metre is the scale of the thing the
#: mask decides — WHICH two materials meet here — and it is deliberately not
#: finer: the id is read with NEAREST and carries the same pair on both sides of
#: a boundary, so a coarser lattice cannot move an edge. What places the edge is
#: the sd mask below.
ID_STEP_M = 1.0

#: Metres per texel of the SD mask — half the id step, so an id texel holds
#: exactly 2 × 2 sd texels. This is the lattice the sub-texel sharpness comes
#: out of: read LINEARLY, a distance field between two samples 0.5 m apart
#: places the zero crossing to within the quantisation step below, which is
#: 6 cm — an edge that stays sharp at any zoom without a single extra triangle.
SD_STEP_M = 0.5

#: How far the signed distance is carried, in metres, before it is clamped.
#: Eight metres is the widest transition an author may ask for
#: (:data:`EDGE_BLEND_MAX_M`), so the band always covers the whole blend; past
#: it the answer is "far inside" or "far outside" and one byte would not be able
#: to say anything finer anyway.
SD_BAND_M = 8.0

#: The byte code of sd = 0, and how many codes one metre is worth.
#:
#: THE QUANTISATION, written out: ``code = clamp(round(sd · SD_CODES_PER_M)
#: + SD_ZERO, 1, 255)`` and back ``sd = (code − SD_ZERO) / SD_CODES_PER_M``.
#: 127 codes per side of a zero that is EXACTLY representable (128), so a texel
#: sitting on the boundary quantises to the boundary rather than to 6 cm beside
#: it; the step is 8/127 = 0.063 m, an order finer than the narrowest sensible
#: blend width. Code 0 is never written — it would decode to −8.06 m, outside
#: the band the contract states.
SD_ZERO = 128
SD_CODES_PER_M = 127.0 / SD_BAND_M


def encode_sd(metres: float) -> int:
    """One signed distance as the byte the mask carries — the quantisation,
    written once so the bake and the check cannot spell it differently."""
    code = int(round(float(metres) * SD_CODES_PER_M)) + SD_ZERO
    return 1 if code < 1 else (255 if code > 255 else code)


def decode_sd(code: int) -> float:
    """…and back to metres. The TypeScript twin is
    ``@anima/scene-render`` ``decodeSd``, which reads the same two numbers out
    of the payload rather than out of a constant — a client must never hold a
    second opinion about how the bytes it was sent were made."""
    return (int(code) - SD_ZERO) / SD_CODES_PER_M

#: Layer indices one world may have. The id mask is two BYTES per texel, one per
#: half of the pair, so 256 is the ceiling the format itself sets — and it is
#: also more ground kinds than a world has ever painted. Past it the extra kinds
#: fall back to bare ground rather than aliasing onto somebody else's material.
MAX_LAYERS = 256

# ── The transition width ────────────────────────────────────────────────────

#: HOW WIDE THE TRANSITION OF A GROUND KIND IS, in metres — `meta.edge_blend_m`
#: on the terrain type (§ G3). It replaces the client's fixed 1.5 m alpha fringe
#: (`NG_EDGE_BAND_M`), which was a property of the RENDERER and the same for
#: every ground in the world; this is a property of the MATERIAL and the author
#: sets it per kind.
#:
#: The default IS that old fringe, so nothing looks different until somebody
#: turns a dial. 0 is the hard cut — the ground of a room, a paved path, a kerb
#: — and it is a real value rather than "off": the shader then draws an
#: analytically anti-aliased step instead of a blend, which is a sharp edge and
#: not a jagged one. The ceiling is the sd band: a blend wider than the baked
#: distance could not be evaluated.
EDGE_BLEND_DEFAULT_M = 1.5
EDGE_BLEND_MIN_M = 0.0
EDGE_BLEND_MAX_M = 8.0
EDGE_BLEND_KEY = "edge_blend_m"

#: How far the edge NOISE may push a transition, in metres — the Python twin of
#: ``@anima/scene-render`` ``LC_EDGE_NOISE_M``, and the reason it is spelled
#: here at all is :func:`collapse_band_m`: the bake has to know how far out the
#: shader is still drawing something before it may stop naming a runner-up. The
#: push is itself capped at half the blend width (``lcPushedSd``), so a hard cut
#: is not widened by it.
EDGE_NOISE_M = 0.5

#: The slack on top of the drawn transition, in metres, before a texel's pair
#: collapses to (own, own).
#:
#: TWO SD TEXELS, and both of them are paid for: one because the shader's LINEAR
#: fetch of the distance reaches into the neighbouring texel, so a texel whose
#: own pair has already collapsed must not be read by a neighbour that is still
#: blending; one because a HARD cut is anti-aliased over a PIXEL, and a pixel a
#: hundred metres out is about a metre of ground. Wider than that and the
#: collapse stops doing its job — the whole point of it is that two id texels
#: deep inside one ground name the SAME thing, so the interpolated distance
#: between them cannot cross zero and paint a hairline of somebody else.
COLLAPSE_SLACK_M = 1.0


def collapse_band_m(blend_m: float) -> float:
    """How far from a boundary the pair still has to name a runner-up, metres.

    Everything the shader still draws of the transition, plus
    :data:`COLLAPSE_SLACK_M`: half the blend width lies on each side of the line
    (``layerWeight``), the noise may push the line by up to
    :data:`EDGE_NOISE_M` — itself capped at half the width — and past the sum of
    those the weight is saturated, i.e. the runner-up contributes nothing to the
    picture. A hard cut (0) therefore keeps its pair for exactly the slack.
    """
    blend = max(float(blend_m), 0.0)
    return 0.5 * blend + min(EDGE_NOISE_M, 0.5 * blend) + COLLAPSE_SLACK_M


def sanitize_edge_blend(raw: Any) -> Optional[float]:
    """One authored ``edge_blend_m`` as a stored value, or None to drop the key.

    The shape rule of :func:`app.core.terrain_types._clamped_meta_number` with
    ONE difference, and it is the reason this lives here rather than reusing
    that helper: **0 is a value**. Everywhere else in the catalog a number that
    rounds to zero says nothing and leaves no key; here it says "hard cut", the
    room-floor case § G3 names explicitly, and it has to survive a save. Junk
    (absent, NaN, a string) still leaves no key, and that is what
    :func:`edge_blend_of` reads as "the default width".
    """
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return round(min(max(value, EDGE_BLEND_MIN_M), EDGE_BLEND_MAX_M), 2)


def edge_blend_of(entry: Optional[Dict[str, Any]]) -> float:
    """The transition width of one catalog entry, in metres — the READER.

    A kind that says nothing gets :data:`EDGE_BLEND_DEFAULT_M`, today's look. A
    stored value is clamped a second time on the way out, because the catalog is
    editable by hand and a payload number nobody clamped is a shader that draws
    a hundred-metre gradient.
    """
    meta = (entry or {}).get("meta")
    if not isinstance(meta, dict):
        return EDGE_BLEND_DEFAULT_M
    value = sanitize_edge_blend(meta.get(EDGE_BLEND_KEY))
    return EDGE_BLEND_DEFAULT_M if value is None else value


# ── Location floors: the topmost layers ─────────────────────────────────────

#: THE TRANSITION WIDTH OF A FLOOR, in metres, when the room does not name one
#: — and it is **0**, the hard cut, where a painted ground kind defaults to a
#: 1.5 m fringe. A floor is drawn, not grown: parquet ends at the wall, a paved
#: yard ends at its kerb, and a room whose sand should run out into the beach
#: says so by dialling ``layout.edge_blend_m`` up.
FLOOR_EDGE_BLEND_DEFAULT_M = 0.0

#: The floor kind of a CLOSED room that names none. The twin of
#: ``scene_recipe.DEFAULT_FLOOR_KIND``: a room with walls has a floor, and if
#: nobody said which one it is still not the meadow outside. An open ZONE that
#: names no kind contributes no layer at all — there the terrain is the answer.
FLOOR_KIND_DEFAULT = "floor"


class Floor(NamedTuple):
    """ONE level-0 floor polygon of ONE location, in WORLD metres.

    The unit the bake, the zone-water carve and the scene payload's
    ``floor_plan`` all speak: the room's own hull (``room_recipe``'s, never a
    second derivation), the kind it wears, whether it is a closed room or an
    open zone, its transition width and — for a water floor — the mirror the
    author asked for (``None`` = derive it).
    """
    location_id: str
    room_id: str
    polygon: List[List[float]]
    kind: str
    closed: bool
    edge_blend_m: float
    water: bool
    water_level: Optional[float]
    water_depth_m: float
    shore_ramp_m: float


def floor_edge_blend_of(layout: Any) -> float:
    """One room's transition width, in metres — ``layout.edge_blend_m``.

    Same clamp as a ground kind's (:func:`sanitize_edge_blend`, 0…8 m, 0 is a
    VALUE), only the default differs: a floor's is the hard cut.
    """
    if not isinstance(layout, dict):
        return FLOOR_EDGE_BLEND_DEFAULT_M
    value = sanitize_edge_blend(layout.get(EDGE_BLEND_KEY))
    return FLOOR_EDGE_BLEND_DEFAULT_M if value is None else value


def floor_water_meta(layout: Any) -> Tuple[Optional[float], float, float]:
    """``(water_level | None, depth_m, shore_ramp_m)`` of a water FLOOR.

    THE SAME READER THE PAINTED LAKES USE (``heightfield.water_meta``), fed the
    room's ``layout`` instead of an area's ``meta`` — the three numbers have the
    same names, the same defaults and the same clamps in both places, and a
    second spelling of them is a second lake physics nobody asked for. A missing
    ``water_level`` answers None and the bake derives one (§ G4).
    """
    from app.core.heightfield import water_meta
    return water_meta({"meta": layout if isinstance(layout, dict) else {}})


def floor_kind_of(source: Any, closed: bool) -> str:
    """WHAT THE GROUND WEARS in one room — the kind rule, spelled once.

    ``source`` is the room's ``layout`` or the composed recipe; both carry the
    same ``surfaces.floor``. Two answers where the author named nothing:

    * a CLOSED room gets :data:`FLOOR_KIND_DEFAULT`. A room with walls has a
      floor whether or not anybody named it, and it is not the meadow outside —
      that is the whole point of the stage ("parquet under the furniture");
    * an open ZONE gets the empty string, i.e. NO layer at all. A zone without
      a kind is a place to stand, not a material, and the terrain under it is
      the honest picture.

    Read by the bake (:func:`location_floors`) and by the scene payload's
    ``floor_plan`` (``scene_recipe._floor_plan``) — one rule, so the material of
    the ground and the material a consumer is told about cannot differ.
    """
    kind = str((((source or {}).get("surfaces") or {}).get("floor")) or "").strip()
    if kind:
        return kind
    return FLOOR_KIND_DEFAULT if closed else ""


def is_water_floor(kind: str, catalog: Optional[Dict[str, Dict[str, Any]]],
                   surface_classes: Optional[Dict[str, str]] = None) -> bool:
    """Is this FLOOR kind a water surface? Two catalogs, never the name.

    A floor kind is a SURFACE-library id (``surfaces.floor``), which a terrain
    kind only sometimes is. So the question is asked of both books, in the order
    of specificity:

    1. the terrain catalog's ``meta.water`` (``terrain_types.is_water_kind``) —
       the flag § G4 gave painted lakes;
    2. the surface library's material CLASS (``water``/``ice``), which is the
       very predicate the renderers decide a rippling surface by
       (``@anima/scene-render`` ``isWaterClass``).

    ``surface_classes`` maps a surface id to its declared material class and is
    handed in so this module stays pure; absent, only the terrain catalog is
    asked.
    """
    from app.core.terrain_types import is_water_kind
    kind = (kind or "").strip()
    if not kind:
        return False
    if catalog is not None and is_water_kind(kind, catalog):
        return True
    cls = str((surface_classes or {}).get(kind) or "").strip().lower()
    return cls in ("water", "ice")


def location_floors(loc: Dict[str, Any],
                    catalog: Optional[Dict[str, Dict[str, Any]]] = None,
                    surface_classes: Optional[Dict[str, str]] = None,
                    ) -> List[Floor]:
    """The level-0 floor polygons of ONE placed location, in PRIORITY ORDER.

    Zones first, closed rooms after — that is the § G3 order ("terrain areas <
    zone floors < closed-room floors"), and within each group the rooms keep the
    order the location stores them in, which is the order the 2D plan paints
    them in. The last one containing a point wins, exactly as with painted
    areas.

    THREE KINDS OF ROOM, THREE ANSWERS:

    * an open ZONE (``always_visible``) contributes its ``surfaces.floor`` — and
      NOTHING when it declares none: a zone without a kind is a place to stand,
      not a material, and the terrain under it is the honest picture (that is
      what the renderers already did with a kindless zone plate);
    * a CLOSED room contributes its ``surfaces.floor`` or
      :data:`FLOOR_KIND_DEFAULT` — a room with walls has a floor, whether or not
      anybody named it. This is the whole point of the stage: parquet under the
      furniture instead of grass;
    * the YARD (``is_ground``, § A13a) contributes nothing. It is not a floor
      laid on the ground, it IS the ground of the plot — and on a built location
      that ground is the plateau the bake already stamped.

    Only storey 0 is asked. Storeys above and below stay scene geometry (§ G5);
    they have plates and this module has no third dimension to put them in.

    An UNPLACED location (no pin, no drawn boundary) yields nothing: it owns no
    square metre of world, so it can colour none.
    """
    from app.core.world_geometry import (effective_boundary,
                                         polygon_local_to_world)
    from app.core.room_recipe import room_outline_local
    from app.models.world import GROUND_ROOM_ID
    eff = effective_boundary(loc)
    if eff is None:
        return []
    cx, cz, yaw, _pts = eff
    loc_id = str(loc.get("id") or "")
    zones: List[Floor] = []
    rooms: List[Floor] = []
    for room in (loc.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("id") or "")
        if room_id == GROUND_ROOM_ID:
            continue                      # the yard IS the ground (§ A13a)
        lay = room.get("layout")
        if not isinstance(lay, dict):
            continue
        try:
            if int(lay.get("level") or 0) != 0:
                continue                  # a storey keeps its plate (§ G5)
        except (TypeError, ValueError):
            continue
        outline = room_outline_local(lay)
        if len(outline) < 3:
            continue
        world = polygon_local_to_world(outline, cx, cz, yaw)
        if world is None or len(world) < 3:
            continue
        closed = not bool(lay.get("always_visible"))
        kind = floor_kind_of(lay, closed)
        if not kind:
            continue                      # a kindless zone paints nothing
        water = is_water_floor(kind, catalog, surface_classes)
        level, depth, ramp = floor_water_meta(lay)
        entry = Floor(location_id=loc_id, room_id=room_id,
                      polygon=[[float(x), float(z)] for x, z in world],
                      kind=kind, closed=closed,
                      edge_blend_m=floor_edge_blend_of(lay),
                      water=water,
                      water_level=(level if water else None),
                      water_depth_m=depth, shore_ramp_m=ramp)
        (rooms if closed else zones).append(entry)
    return zones + rooms


def world_floors(locations: Sequence[Dict[str, Any]],
                 catalog: Optional[Dict[str, Dict[str, Any]]] = None,
                 surface_classes: Optional[Dict[str, str]] = None,
                 ) -> List[Floor]:
    """Every location's level-0 floors, in ONE priority order.

    LARGEST PLOT FIRST, so the SMALLEST writes last and wins — the containment
    law of ``world_geometry.location_at_point`` and of the plateau stamps
    (``heightfield._build_plateaus``), spelled here for the material of the
    ground. A hut inside a village square paints its floor over the square's,
    never the other way round, and neither of them needs a z-order.

    ``sorted`` is stable, so two plots of equal area keep the order the world
    handed them out in.
    """
    ranked: List[Tuple[float, int, Dict[str, Any]]] = []
    from app.core.world_geometry import boundary_area_m2
    for pos, loc in enumerate(locations or []):
        if not isinstance(loc, dict):
            continue
        ranked.append((-boundary_area_m2(loc), pos, loc))
    out: List[Floor] = []
    for _neg_area, _pos, loc in sorted(ranked, key=lambda e: (e[0], e[1])):
        out.extend(location_floors(loc, catalog, surface_classes))
    return out


# ── The layer table ─────────────────────────────────────────────────────────

def layer_table(areas: Sequence[Dict[str, Any]],
                catalog: Dict[str, Dict[str, Any]],
                default_kind: str,
                floors: Sequence[Floor] = ()) -> List[Dict[str, Any]]:
    """The layers of this world, index 0 first — INDEX 0 IS BARE GROUND.

    Index 0 is the world's default kind (`game.default_terrain_kind`), i.e. the
    ground of everything nobody painted; the painted kinds follow, sorted by
    kind so the table of one world is the same list on every request and a
    payload diff means the world moved. A shape painted in the DEFAULT kind maps
    back onto index 0 rather than getting a twin of it: there is no boundary
    between the default ground and itself, and a second slice of the same
    texture would be VRAM for a cut nobody can see.

    THEN THE FLOOR KINDS (E5a), and the table stops being a list of terrain
    kinds: a room's ``surfaces.floor`` is a surface-library id and may be a
    material no painted area of this world uses. It is sorted the same way, and
    it appears exactly once per (kind, WIDTH) pair — the width is what the
    shader reads out of the table, so two rooms that wear the same parquet with
    two different transitions really are two layers. A floor whose kind AND
    width already exist as a terrain layer maps back onto it, for the same
    reason a default-kind shape maps back onto 0.

    Each entry carries what a renderer needs and nothing else: the ``kind`` (for
    logs and for the undergrowth gate), the ``surface`` the type wears (the
    library id, `terrain_types` — NEVER the kind's spelling; a floor kind IS its
    own surface id), the transition width and whether the kind is water.
    """
    from app.core.terrain_types import is_water_kind
    default_kind = (default_kind or "").strip()
    out: List[Dict[str, Any]] = []
    seen: Dict[Tuple[str, float], int] = {}
    overflow = 0

    def add(kind: str, surface: str, blend: float, water: bool) -> None:
        nonlocal overflow
        key = (kind, round(float(blend), 2))
        if key in seen:
            return
        if len(out) >= MAX_LAYERS:
            overflow += 1
            return
        seen[key] = len(out)
        out.append({"index": len(out), "kind": kind, "surface": surface,
                    "edge_blend_m": key[1], "water": water})

    entry = catalog.get(default_kind)
    add(default_kind, str((entry or {}).get("surface") or "").strip(),
        edge_blend_of(entry), bool(is_water_kind(default_kind, catalog)))
    for kind in sorted({str(a.get("kind") or "").strip()
                        for a in (areas or [])}):
        if not kind:
            continue
        entry = catalog.get(kind)
        add(kind, str((entry or {}).get("surface") or "").strip(),
            edge_blend_of(entry), bool(is_water_kind(kind, catalog)))
    for kind, blend, water in sorted({(f.kind, round(f.edge_blend_m, 2),
                                       f.water) for f in (floors or [])}):
        # A FLOOR IS ITS OWN SURFACE. ``surfaces.floor`` names a library entry
        # directly, where a terrain type points at one through its ``surface``
        # field — so a floor kind that the terrain catalog does not know wears
        # itself, and one it does know keeps the terrain type's own surface.
        entry = catalog.get(kind)
        surface = str((entry or {}).get("surface") or "").strip() or kind
        add(kind, surface, blend, water)
    if overflow:
        logger.warning("terrain layers: %d layer(s) past the ceiling of %d "
                       "render as bare ground", overflow, MAX_LAYERS)
    return out


# ── The model ───────────────────────────────────────────────────────────────

def _ring(points: Any) -> Optional[List[Tuple[float, float]]]:
    """A polygon parsed ONCE into float pairs, or None when it is not one —
    the twin of ``heightfield._ring``, and for the same reason: the scanline
    below walks a ring per raster row and must not re-parse it every time."""
    out: List[Tuple[float, float]] = []
    for pt in (points or []):
        try:
            out.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError, IndexError):
            return None
    return out if len(out) >= 3 else None


def _ring_box(ring: Sequence[Tuple[float, float]]
              ) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    zs = [p[1] for p in ring]
    return (min(xs), min(zs), max(xs), max(zs))


class LayerModel:
    """The painted world as ONE cut — the layer table plus the ranked rings.

    A **paint rank** is the position of a shape in `list_areas` order, offset by
    one: rank 0 is the unpainted world, rank r the r-th painted shape. The rank
    IS the priority (a higher rank was painted later, so it wins), and the layer
    index of a rank is a lookup — which is what lets the bake decide "who is on
    top" with an integer comparison while the payload still speaks in layers.

    THE LOCATION FLOORS TAKE THE RANKS ABOVE THE AREAS (E5a). They are appended
    after the painted shapes in the order :func:`world_floors` puts them in, so
    "the last containing entry wins" is the WHOLE priority rule — there is no
    second mechanism, no z-order and no special case for a room. What makes a
    floor beat a meadow is that it comes later in one list.
    """

    def __init__(self, areas: Sequence[Dict[str, Any]],
                 catalog: Optional[Dict[str, Dict[str, Any]]],
                 default_kind: str,
                 floors: Sequence[Floor] = ()):
        catalog = catalog or {}
        floors = list(floors or [])
        self.layers = layer_table(areas, catalog, default_kind, floors)
        by_kind: Dict[Tuple[str, float], int] = {
            (entry["kind"], round(float(entry["edge_blend_m"]), 2)):
            entry["index"] for entry in self.layers}
        #: rank -> layer index. Rank 0 is bare ground, i.e. layer 0.
        self.rank_layer: List[int] = [0]
        #: rank -> (parsed ring, world box). Index 0 is a placeholder for the
        #: unpainted world, which has no outline.
        self.rings: List[Optional[List[Tuple[float, float]]]] = [None]
        self.boxes: List[Tuple[float, float, float, float]] = [
            (math.inf, math.inf, -math.inf, -math.inf)]
        #: rank -> the floor it came from, for the ranks that are floors. The
        #: painted areas are absent from it, which is what "is this rank a
        #: room's floor" is asked with.
        self.floor_by_rank: Dict[int, Floor] = {}
        for area in (areas or []):
            ring = _ring(area.get("polygon"))
            if ring is None:
                # A shape that encloses nothing paints nothing — and it must not
                # take a rank either, or the ranks would stop being the order the
                # DB handed out.
                continue
            kind = str(area.get("kind") or "").strip()
            entry = catalog.get(kind)
            self.rank_layer.append(
                by_kind.get((kind, round(edge_blend_of(entry), 2)), 0))
            self.rings.append(ring)
            self.boxes.append(_ring_box(ring))
        self.floors: List[Floor] = []
        for floor in floors:
            ring = _ring(floor.polygon)
            if ring is None:
                continue
            self.floor_by_rank[len(self.rings)] = floor
            self.rank_layer.append(
                by_kind.get((floor.kind, round(floor.edge_blend_m, 2)), 0))
            self.rings.append(ring)
            self.boxes.append(_ring_box(ring))
            self.floors.append(floor)

    # ── point queries (the scalar twin of the raster) ───────────────────────

    def rank_at(self, x: float, z: float) -> int:
        """The paint rank at a world point — the LAST containing shape wins.

        The scalar twin of the scanline fill, and the reason both exist: the
        smoke asserts them against each other and against
        ``terrain_query.kind_at`` at 500 lattice probes, which is what makes
        "the picture and the rules read the same ground" a measured fact.
        """
        hit = 0
        for rank in range(1, len(self.rings)):
            box = self.boxes[rank]
            if x < box[0] or x > box[2] or z < box[1] or z > box[3]:
                continue
            if _inside_ring(x, z, self.rings[rank]):
                hit = rank
        return hit

    def layer_at(self, x: float, z: float) -> int:
        """The layer index at a world point — :meth:`rank_at` through the
        rank/layer map. THE UNDERGROWTH GATE READS THIS (decision 5.2)."""
        return self.rank_layer[self.rank_at(x, z)]

    # ── the raster ──────────────────────────────────────────────────────────

    def rank_grid(self, origin_x: float, origin_z: float, step: float,
                  n: int) -> array:
        """The paint rank at ``n × n`` lattice CENTRES, painted bottom to top.

        Sample (i, j) sits at ``origin + (i + 0.5) · step`` — a TEXEL CENTRE,
        the convention a mask is read with, not the support-point convention of
        the heightfield.

        SCANLINE FILL, NOT POINT QUERIES. A per-point `rank_at` over a tile is
        n² ray casts against every ring, which for the 544² lattice of one tile
        is tens of millions of edge tests; a scanline computes the crossings
        once per ROW and then writes whole spans at C speed. The rule it fills
        by is exactly the ray cast's: a point is inside when the number of
        crossings to its right is odd, which for a sorted crossing list is the
        half-open span ``[xs[2m], xs[2m+1])``. That identity is not argued, it
        is measured — `smoke_terrain_layers.py` puts the raster and
        :meth:`rank_at` side by side on a lattice of probes.
        """
        grid = array("H", bytes(2 * n * n))
        for rank in range(1, len(self.rings)):
            ring = self.rings[rank]
            box = self.boxes[rank]
            if box[0] > origin_x + n * step or box[2] < origin_x:
                continue
            if box[1] > origin_z + n * step or box[3] < origin_z:
                continue
            filler = array("H", [rank])
            j0 = max(0, int(math.ceil((box[1] - origin_z) / step - 0.5)))
            j1 = min(n, int(math.floor((box[3] - origin_z) / step - 0.5)) + 1)
            count = len(ring)
            for j in range(j0, j1):
                z = origin_z + (j + 0.5) * step
                xs: List[float] = []
                px, pz = ring[count - 1]
                for k in range(count):
                    qx, qz = ring[k]
                    if (pz > z) != (qz > z):
                        xs.append(px + (qx - px) * (z - pz) / (qz - pz))
                    px, pz = qx, qz
                if not xs:
                    continue
                xs.sort()
                base = j * n
                for m in range(0, len(xs) - 1, 2):
                    i0 = int(math.ceil((xs[m] - origin_x) / step - 0.5))
                    i1 = int(math.ceil((xs[m + 1] - origin_x) / step - 0.5))
                    if i0 < 0:
                        i0 = 0
                    if i1 > n:
                        i1 = n
                    if i1 > i0:
                        grid[base + i0:base + i1] = filler * (i1 - i0)
        return grid


def _inside_ring(x: float, z: float,
                 ring: Sequence[Tuple[float, float]]) -> bool:
    """``world_geometry.point_in_polygon`` on a PARSED ring — ray casting,
    spelled exactly as ``heightfield._inside_ring`` spells it."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, zi = ring[i]
        xj, zj = ring[j]
        if (zi > z) != (zj > z):
            if x < (xj - xi) * (z - zi) / (zj - zi) + xi:
                inside = not inside
        j = i
    return inside


# ── The distance transform ──────────────────────────────────────────────────

#: Sentinel for "no site reached this texel yet", in SQUARED HALF-TEXEL units.
_FAR = 1 << 30


def bake_masks(grid: array, n: int, rank_layer: Sequence[int],
               margin: int, out_n: int,
               blend_by_layer: Sequence[float] = ()
               ) -> Optional[Tuple[bytes, bytes]]:
    """The two masks of one window, out of a rank raster — the CORE of E3.

    ``grid`` is ``n × n`` paint ranks on the sd lattice, ``margin`` texels of
    which are the apron that lets a boundary just OUTSIDE the window still
    answer distances inside it; ``out_n`` is the shipped edge (``n − 2·margin``).
    ``blend_by_layer`` is the transition width of every layer, i.e.
    ``[l["edge_blend_m"] for l in model.layers]`` — the bake needs it for the
    collapse of step 3 and for nothing else. Returns ``(id_bytes, sd_bytes)`` or
    **None when the window carries no boundary at all** — a tile that is one
    single ground needs neither mask, and saying so is worth about 400 kB per
    tile.

    THREE STEPS.

    1. **The sites.** Between two neighbouring lattice samples of different
       LAYER lies a boundary, and its position is the MIDPOINT of the two.
       Different layer, not different rank: two shapes of one material that
       touch (a beach drawn in three strokes) have no edge between them, and a
       site there would pull every texel around it away from the real one.
       Sites are recorded in half-texel units (``2·index``), which is what makes
       a midpoint an integer coordinate and the whole transform exact
       arithmetic. Each site carries the PAIR of its two LAYERS — the one whose
       rank is higher first, i.e. the layer painted later, whose own fringe this
       boundary is.

    2. **Two sweeps (dead reckoning).** A forward raster sweep propagates each
       texel's nearest site from its already-visited neighbours, a backward
       sweep does the same from the other side. Eight neighbours in total, which
       is what keeps the error of the propagated distance under a hundredth of a
       texel — and every candidate is compared as a SQUARED distance, so no
       square root is taken until the very last step.

       A TEXEL ONLY TAKES A SITE ITS OWN LAYER IS PART OF. The sign of the
       distance says "am I on A's side or on B's", and for a ground that is
       neither there is no true answer — it used to be given B's, which is how a
       parquet floor came to show the meadow of a boundary it stands on neither
       side of. Rejecting those candidates costs nothing: the chain from a
       texel to its own nearest edge runs through its own ground.

       THE BAND IS THE BUDGET. A texel whose distance passes
       :data:`SD_BAND_M` is dropped back to the sentinel and stops propagating:
       the answer out there is the clamp anyway, and cutting the chain there is
       what turns the cost from "the whole tile" into "the strip along the
       boundaries". It cannot lose anything, because the chain from a site to a
       texel within the band runs entirely through texels that are NEARER to
       that site, i.e. through the band.

    3. **The read-out — ONE BOUNDARY PER ID TEXEL.** An id texel is 1 m and an
       sd texel 0.5 m, so four sd texels lie under each id texel. The id takes
       the pair of the NEAREST site among those four, and all four are then
       signed against THAT pair: + where the texel's own layer is A, − where it
       is B. Reading the pair off one boundary and the sign off another is the
       defect this replaces — at a medial axis the two are exactly equidistant,
       and the composition of the two answers is a material that is at neither.

       AND PAST :func:`collapse_band_m` THE PAIR COLLAPSES to (own, own). Out
       there the weight is saturated, so the runner-up contributes nothing to
       the picture — but naming one is what lets the LINEAR distance between two
       id texels that named DIFFERENT ones cross zero and draw a hairline of the
       wrong ground down the middle of a room. Two texels deep inside one ground
       now say the same thing, and ``a == b`` makes the shader ignore the
       distance altogether.
    """
    band_half = SD_BAND_M / SD_STEP_M * 2.0          # the band in half-texels
    band2 = int(band_half * band_half)
    total = n * n
    d2 = [_FAR] * total
    sx = [0] * total
    sz = [0] * total
    hi = [0] * total                                  # LAYER painted on top
    lo = [0] * total                                  # …and the one under it
    # The layer of every sample, once: the sites, the own-layer test and the
    # read-out all ask for it, and `rank_layer[grid[k]]` in three loops over a
    # 544² lattice is a million list lookups nobody needs.
    lay = [rank_layer[r] for r in grid]
    any_site = False

    for j in range(n):
        base = j * n
        z2 = 2 * j
        for i in range(n - 1):
            k = base + i
            la = lay[k]
            lb = lay[k + 1]
            if la == lb:
                continue
            any_site = True
            top, under = ((la, lb) if grid[k] > grid[k + 1] else (lb, la))
            mx = 2 * i + 1
            for t in (k, k + 1):
                if d2[t] > 1:
                    d2[t] = 1
                    sx[t] = mx
                    sz[t] = z2
                    hi[t] = top
                    lo[t] = under
    for j in range(n - 1):
        base = j * n
        below = base + n
        z2 = 2 * j + 1
        for i in range(n):
            la = lay[base + i]
            lb = lay[below + i]
            if la == lb:
                continue
            any_site = True
            top, under = ((la, lb) if grid[base + i] > grid[below + i]
                          else (lb, la))
            mx = 2 * i
            for t in (base + i, below + i):
                if d2[t] > 1:
                    d2[t] = 1
                    sx[t] = mx
                    sz[t] = z2
                    hi[t] = top
                    lo[t] = under
    if not any_site:
        return None

    def relax(k: int, m: int, x2: int, z2: int) -> None:
        dm = d2[m]
        if dm >= d2[k] or dm >= _FAR:
            return
        own = lay[k]
        if own != hi[m] and own != lo[m]:
            return              # not my boundary — its sign would be a lie
        dx = x2 - sx[m]
        dz = z2 - sz[m]
        v = dx * dx + dz * dz
        if v < d2[k]:
            if v > band2:
                return
            d2[k] = v
            sx[k] = sx[m]
            sz[k] = sz[m]
            hi[k] = hi[m]
            lo[k] = lo[m]

    for j in range(n):
        base = j * n
        above = base - n
        z2 = 2 * j
        for i in range(n):
            k = base + i
            x2 = 2 * i
            if j:
                relax(k, above + i, x2, z2)
                if i:
                    relax(k, above + i - 1, x2, z2)
                if i + 1 < n:
                    relax(k, above + i + 1, x2, z2)
            if i:
                relax(k, k - 1, x2, z2)
    for j in range(n - 1, -1, -1):
        base = j * n
        below = base + n
        z2 = 2 * j
        for i in range(n - 1, -1, -1):
            k = base + i
            x2 = 2 * i
            if j + 1 < n:
                relax(k, below + i, x2, z2)
                if i:
                    relax(k, below + i - 1, x2, z2)
                if i + 1 < n:
                    relax(k, below + i + 1, x2, z2)
            if i + 1 < n:
                relax(k, k + 1, x2, z2)

    # ── read-out ────────────────────────────────────────────────────────────
    # The collapse distance of every layer, once. A layer the caller said
    # nothing about keeps the default width, which is what `edge_blend_of`
    # answers for a kind that names none.
    widths = list(blend_by_layer)
    bands = [collapse_band_m(widths[i] if i < len(widths)
                             else EDGE_BLEND_DEFAULT_M)
             for i in range(MAX_LAYERS)]
    sd = bytearray(out_n * out_n)
    id_n = out_n // 2
    ids = bytearray(id_n * id_n * 2)
    sqrt = math.sqrt
    half_m = SD_STEP_M / 2.0                     # one half-texel in metres
    for j in range(id_n):
        row0 = (2 * j + margin) * n + margin
        row1 = row0 + n
        dst_id = j * id_n * 2
        for i in range(id_n):
            quad = (row0 + 2 * i, row0 + 2 * i + 1,
                    row1 + 2 * i, row1 + 2 * i + 1)
            near = quad[0]
            for k in quad[1:]:
                if d2[k] < d2[near]:
                    near = k
            if d2[near] >= _FAR:
                # Nothing within the band anywhere under this metre: whatever
                # ground it is, it is far inside it and has no runner-up.
                a_layer = b_layer = lay[quad[0]]
            else:
                a_layer = hi[near]
                b_layer = lo[near]
                if sqrt(d2[near]) * half_m > bands[a_layer]:
                    a_layer = b_layer = lay[near]
            ids[dst_id + 2 * i] = a_layer
            ids[dst_id + 2 * i + 1] = b_layer
            paired = a_layer != b_layer
            for w in (0, 1):
                src = row0 + w * n + 2 * i
                dst = (2 * j + w) * out_n + 2 * i
                for u in (0, 1):
                    k = src + u
                    out_k = dst + u
                    v = d2[k]
                    if v >= _FAR:
                        # Nothing within the band: the texel is FAR inside
                        # whatever it is, so the clamp is the honest answer and
                        # its sign is +.
                        sd[out_k] = 255
                        continue
                    own = lay[k]
                    # THE SIGN IS AGAINST THE ID TEXEL'S PAIR, never against
                    # this texel's own site: the shader reads ONE id and
                    # interpolates these four, and two answers about two
                    # different boundaries do not compose. Only where the id
                    # texel has collapsed — or where a third ground meets
                    # inside this very metre — is there no A to measure
                    # against, and then the texel's own site decides.
                    if paired:
                        neg = (own == b_layer if own in (a_layer, b_layer)
                               else own != hi[k])
                    else:
                        neg = own != hi[k]
                    metres = sqrt(v) * half_m
                    sd[out_k] = encode_sd(-metres if neg else metres)
    return bytes(ids), bytes(sd)


# ── The tiles ───────────────────────────────────────────────────────────────

def tile_masks(model: LayerModel, tx: int, tz: int) -> Dict[str, Any]:
    """The two masks of ONE 256 m tile — pure, no DB.

    Same key and same square as a height tile (`heightfield.tile_key`), because
    the client wants both windows to follow the player as one thing. The
    computation lattice is the sd lattice plus a :data:`SD_BAND_M` apron on
    every side, so a shape that ends one metre outside the tile still bends the
    ground inside it.

    A tile of ONE ground answers ``{"uniform": <layer>}`` and carries no arrays
    at all — the common case out in the open world, and the difference between
    384 kB and forty bytes.
    """
    from app.core.heightfield import TILE_M
    margin = int(round(SD_BAND_M / SD_STEP_M))
    out_n = int(round(TILE_M / SD_STEP_M))
    n = out_n + 2 * margin
    origin_x = tx * TILE_M - margin * SD_STEP_M
    origin_z = tz * TILE_M - margin * SD_STEP_M
    grid = model.rank_grid(origin_x, origin_z, SD_STEP_M, n)
    baked = bake_masks(grid, n, model.rank_layer, margin, out_n,
                       [float(e["edge_blend_m"]) for e in model.layers])
    head = {"origin_x": tx * TILE_M, "origin_z": tz * TILE_M}
    if baked is None:
        head["uniform"] = model.rank_layer[grid[(n // 2) * n + n // 2]]
        return head
    ids, sd = baked
    head["id_size"] = out_n // 2
    head["sd_size"] = out_n
    head["id"] = base64.b64encode(ids).decode("ascii")
    head["sd"] = base64.b64encode(sd).decode("ascii")
    return head


def tile_index(model: LayerModel) -> List[Tuple[int, int]]:
    """Every tile a painted shape reaches into, sorted — the client's map.

    PURE BOX COVERAGE, the rule `heightfield.tile_index_from` follows: a shape
    that only clips a corner still indexes the whole tile, because the answer is
    "there may be something here" and the bake then says what. Outside the index
    the world is bare ground, which is exactly what a client draws for a tile it
    was never offered.
    """
    from app.core.heightfield import tiles_of_box
    keys = set()
    for rank in range(1, len(model.rings)):
        keys.update(tiles_of_box(model.boxes[rank]))
    return sorted(keys)


# ── The overview ────────────────────────────────────────────────────────────

#: The coarse world-wide id mask's finest step, in metres, and how many texels
#: it may spend. The overview is what the ground wears BEYOND the fine tiles —
#: past the haze, on a zoomed-out map — where a metre of raster is a fraction of
#: a pixel and the fine masks would be tens of megabytes for a picture nobody
#: can resolve. Eight metres over a 2 × 2 km world is 250² texels = 125 kB; the
#: step doubles until a world of any size fits the cap, exactly as
#: `heightfield._step_for` coarsens the height overview.
OVERVIEW_STEP_M = 8.0
OVERVIEW_MAX_POINTS = 250_000


def overview_step_for(box: Tuple[float, float, float, float]) -> float:
    """The overview's step for a world box — doubled until it fits the cap."""
    step = OVERVIEW_STEP_M
    while True:
        cols = int((box[2] - box[0]) / step) + 2
        rows = int((box[3] - box[1]) / step) + 2
        if cols * rows <= OVERVIEW_MAX_POINTS or step > 4096:
            return step
        step *= 2


def overview_mask(model: LayerModel) -> Dict[str, Any]:
    """The world-wide COARSE id mask — one pair per texel, both halves equal.

    NO SD RIDES WITH IT, and that is a decision rather than an omission: at this
    step every transition is narrower than a texel, so the only honest answer is
    a hard cut, and a constant sd texture is something the client can build
    itself out of one byte. What the far ground loses is the soft fringe; what
    it keeps is being the right COLOUR, which is the whole reason a distant lake
    has to be in the picture at all.

    An empty world answers ``cols``/``rows`` 0 — bare ground everywhere, which
    is what a client without a mask draws anyway.
    """
    boxes = [model.boxes[r] for r in range(1, len(model.rings))]
    if not boxes:
        return {"origin_x": 0.0, "origin_z": 0.0, "step_m": OVERVIEW_STEP_M,
                "cols": 0, "rows": 0, "id": ""}
    x0 = min(b[0] for b in boxes)
    z0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    z1 = max(b[3] for b in boxes)
    step = overview_step_for((x0, z0, x1, z1))
    origin_x = math.floor(x0 / step) * step
    origin_z = math.floor(z0 / step) * step
    cols = int((x1 - origin_x) / step) + 2
    rows = int((z1 - origin_z) / step) + 2
    span = max(cols, rows)
    grid = model.rank_grid(origin_x, origin_z, step, span)
    data = bytearray(cols * rows * 2)
    for j in range(rows):
        src = j * span
        dst = j * cols * 2
        for i in range(cols):
            layer = model.rank_layer[grid[src + i]]
            data[dst + 2 * i] = layer
            data[dst + 2 * i + 1] = layer
    return {"origin_x": origin_x, "origin_z": origin_z, "step_m": step,
            "cols": cols, "rows": rows,
            "id": base64.b64encode(bytes(data)).decode("ascii")}


# ── The cache ───────────────────────────────────────────────────────────────

#: (sig, model) — one model per signature, exactly the bargain
#: `heightfield.world_model` strikes with its generation counter. Building it
#: parses every ring once; every tile of that signature then costs arithmetic.
_MODEL: Optional[Tuple[str, LayerModel]] = None
#: (sig, tx, tz) -> baked tile, least-recently-used FIRST.
_TILES: "OrderedDict[Tuple[str, int, int], Dict[str, Any]]" = OrderedDict()
#: (sig, index/overview) — the two answers of the index request.
_INDEX: Optional[Tuple[str, List[Tuple[int, int]], Dict[str, Any]]] = None

#: How many baked tiles stay in the process. A tile with boundaries costs about
#: 384 kB of mask plus its base64, so 32 of them are ~25 MB — the same order the
#: height tiles hold, and twice what one batch can ask for.
TILE_CACHE_MAX = 32

#: Tiles one batch may ask for. Deliberately far below the height batch's 64:
#: one layer tile is 384 kB of raw mask (0.5 MB of base64) against a height
#: tile's 130 kB, so 16 is already 8 MB on the wire — and a tile that has to be
#: baked from cold costs about a second. A client that needs more asks twice,
#: which is what its own load policy does anyway.
BATCH_MAX = 16


def surface_classes() -> Dict[str, str]:
    """``surface id -> declared material class`` out of the surface library.

    The second book :func:`is_water_floor` reads. It is a small dict of the
    kinds an author gave a material to at all (matte kinds leave no entry), so
    building it per signature costs one file read.
    """
    from app.core.surface_textures import get_kind_meta
    out: Dict[str, str] = {}
    for kind, meta in (get_kind_meta() or {}).items():
        cls = ((meta or {}).get("material") or {}).get("class")
        if isinstance(cls, str) and cls.strip():
            out[str(kind)] = cls.strip().lower()
    return out


def floors_basis() -> List[Dict[str, Any]]:
    """What the LOCATION FLOORS of this world are made of, in hashable form.

    Deliberately the RAW inputs and not the composed polygons: composing them
    means running the room transform over every hull of every location, and this
    is asked once per request. Everything a floor is a function of rides along —
    the pin (a moved or turned location moves its floors with it) and the whole
    ``layout`` blob of every room (its rectangle, its outline, its curves, its
    rotation, its ``surfaces.floor``, its ``always_visible``, its width and its
    water level).
    """
    from app.models.world import list_locations
    out: List[Dict[str, Any]] = []
    for loc in list_locations():
        rooms = [(str(r.get("id") or ""), r.get("layout"))
                 for r in (loc.get("rooms") or [])
                 if isinstance(r, dict) and isinstance(r.get("layout"), dict)]
        if not rooms:
            continue
        out.append({"id": loc.get("id"), "x": loc.get("pos_x"),
                    "z": loc.get("pos_z"), "yaw": loc.get("yaw_deg"),
                    "boundary": (loc.get("map3d") or {}).get("boundary"),
                    "rooms": sorted(rooms)})
    return out


def layers_sig() -> str:
    """Signature over everything the cut is made of — areas, catalog, default,
    and since E5a the LOCATION FLOORS.

    It is NOT `terrain_sig`, deliberately. That one hashes the scatter
    enrichment as well (prop variants, prop heights), so a prop gaining a low
    mesh would throw away every baked mask in the process for a picture that
    cannot change. This hashes the five things a mask really depends on: the
    polygons, their order, the surface + width + water flag of every kind, which
    kind the unpainted world is, and every placed room floor
    (:func:`floors_basis`).

    The CLIENT still refetches on `terrain_sig` — that is the signature the
    worldmap poll carries, and it moves whenever this one does.
    """
    from app.core.terrain_query import default_kind
    from app.core.terrain_types import effective_catalog
    from app.models.terrain import list_areas
    catalog = effective_catalog()
    basis = json.dumps({
        "default": default_kind(),
        "areas": [{"kind": a.get("kind"), "polygon": a.get("polygon"),
                   "z_order": a.get("z_order")} for a in list_areas()],
        "types": {k: {"surface": v.get("surface", ""),
                      "blend": edge_blend_of(v),
                      "water": bool((v.get("meta") or {}).get("water"))}
                  for k, v in catalog.items()},
        "floors": floors_basis(),
        "surface_classes": surface_classes(),
    }, sort_keys=True, default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]


def world_model() -> LayerModel:
    """THE cut of this world, built once per :func:`layers_sig`."""
    global _MODEL
    sig = layers_sig()
    cached = _MODEL
    if cached is not None and cached[0] == sig:
        return cached[1]
    from app.core.terrain_query import default_kind
    from app.core.terrain_types import effective_catalog
    from app.models.terrain import list_areas
    from app.models.world import list_locations
    catalog = effective_catalog()
    model = LayerModel(list_areas(), catalog, default_kind(),
                       world_floors(list_locations(), catalog,
                                    surface_classes()))
    _MODEL = (sig, model)
    return model


def get_tile(tx: int, tz: int, sig: Optional[str] = None) -> Dict[str, Any]:
    """One baked tile, kept in an LRU keyed by signature AND position.

    **The returned dict is SHARED — treat it as read-only**, the rule
    `heightfield.get_tile` states for the same reason.

    ``sig`` may be handed in by a caller that has already read it (a batch reads
    it ONCE, before the first tile is baked) — the signature now hashes every
    placed room layout in the world, so asking for it per tile of a sixteen-tile
    batch would be sixteen passes over the location table.
    """
    sig = layers_sig() if sig is None else sig
    key = (sig, int(tx), int(tz))
    tile = _TILES.get(key)
    if tile is not None:
        try:
            _TILES.move_to_end(key)
        except KeyError:
            pass
        return tile
    tile = tile_masks(world_model(), int(tx), int(tz))
    _TILES[key] = tile
    while len(_TILES) > TILE_CACHE_MAX:
        _TILES.popitem(last=False)
    return tile


def invalidate_cache() -> None:
    """Drop everything (tests). The signature already does this in production —
    a stale entry simply stops being asked for — but a smoke that rewrites the
    world under the same literals needs the hard reset."""
    global _MODEL, _INDEX
    _MODEL = None
    _INDEX = None
    _TILES.clear()


def _format_key(tx: int, tz: int) -> str:
    """A tile key as it appears IN A PAYLOAD: ``"tx,tz"`` — the heightfield's
    own form, so a client can key both windows off one string."""
    return f"{tx},{tz}"


def waters_payload(model: LayerModel) -> List[Dict[str, Any]]:
    """Every ZONE WATER of the world as a surface a renderer can draw (E5a).

    A room whose floor kind is water is a lake with a room id: it carves its bed
    like a painted one (``heightfield``'s zone-water stamp) and it wants the same
    flat mirror over it. So it travels in the same shape a painted lake does —
    ``polygon`` in WORLD metres, ``water_level_effective`` in world y — and a
    client renders both with one routine instead of inventing a second water.

    The mirror is read off the HEIGHT model, because that is who decided it: the
    author's ``layout.water_level`` where there is one, otherwise the plateau of
    a built location or the rim median of a natural one. A room the bake never
    saw (an unplaced location, a world without a heightfield) is left out rather
    than given a guessed height — a plane at the wrong y is the drape of old.
    """
    if not model.floors:
        return []
    try:
        from app.core.heightfield import world_model as height_model
        levels = height_model().zone_water_level_by_room
    except Exception:                       # noqa: BLE001 — no field, no water
        logger.warning("terrain layers: no height model — zone waters have no "
                       "mirror and are left out", exc_info=True)
        return []
    out: List[Dict[str, Any]] = []
    for floor in model.floors:
        if not floor.water:
            continue
        level = levels.get((floor.location_id, floor.room_id))
        if level is None:
            continue
        out.append({"location_id": floor.location_id,
                    "room_id": floor.room_id,
                    "kind": floor.kind,
                    "polygon": [[round(x, 3), round(z, 3)]
                                for x, z in floor.polygon],
                    "water_level_effective": round(float(level), 3)})
    return out


def index_payload() -> Dict[str, Any]:
    """The INDEX answer of ``GET /play/terrain-layers`` (no ``keys``)."""
    global _INDEX
    sig = layers_sig()
    cached = _INDEX
    if cached is None or cached[0] != sig:
        model = world_model()
        cached = (sig, tile_index(model), overview_mask(model))
        _INDEX = cached
    model = world_model()
    return {
        **_format_block(sig),
        "layers": model.layers,
        "overview": cached[2],
        "tile_keys": [_format_key(tx, tz) for tx, tz in cached[1]],
        "waters": waters_payload(model),
    }


def batch_payload(keys: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    """The BATCH answer of ``GET /play/terrain-layers?keys=…``.

    THE SIGNATURE IS READ FIRST, before a single tile is baked — the order
    `heightfield.tiles_payload` keeps, so a write landing mid-request leaves the
    client with masks NEWER than the signature they arrived with (which the next
    poll corrects) rather than stale ones labelled current.
    """
    sig = layers_sig()
    model = world_model()
    index = set(tile_index(model))
    tiles: Dict[str, Any] = {}
    for tx, tz in keys:
        if (tx, tz) not in index:
            continue
        tiles[_format_key(tx, tz)] = get_tile(tx, tz, sig)
    return {**_format_block(sig), "layers": model.layers, "tiles": tiles}


def _format_block(sig: str) -> Dict[str, Any]:
    """The numbers a renderer needs to READ the bytes — shipped with every
    answer, because a client that guessed them would decode a different
    landscape than the one that was baked."""
    from app.core.heightfield import TILE_M
    return {
        "sig": sig,
        "tile_m": TILE_M,
        "id_step_m": ID_STEP_M,
        "sd_step_m": SD_STEP_M,
        "sd_band_m": SD_BAND_M,
        "sd_zero": SD_ZERO,
        "sd_codes_per_m": SD_CODES_PER_M,
    }


def parse_keys(raw: str, cap: int = BATCH_MAX) -> List[Tuple[int, int]]:
    """The ``keys=tx:tz,tx:tz`` query — the heightfield's own parser, reused.

    Reusing it is the point: the two windows are keyed by the same tiles, and a
    client that writes one query writes both.
    """
    from app.core.heightfield import parse_tile_keys
    return parse_tile_keys(raw, cap=cap)
