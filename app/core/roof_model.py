"""THE ROOF — a parametric building part from a declarative build description.

Stage 4b of ``plan-assets-im-szenenkontext.md``: simple assets are not meshed
from a picture any more, they are BUILT from numbers. The first one is the
roof, because the far view already shows a location's walls
(``client3d sceneRecipe.buildFarShell``) and those walls are open at the top —
the outline and the eaves height are known, so the only thing left to decide
is the roof's FORM, and that is a taste question an LLM may answer.

THE DIVISION OF LABOUR: this module
decides, ``app/blender/scripts/roof_build.py`` executes. The script receives
finished vertex lists and a material, builds, exports — it computes no
geometry, so every number in the GLB can be traced back to a function in here
and the smoke (``scripts/smoke_roof_model.py``) can check the mesh by hand
WITHOUT a Blender binary.

WHY A DESCRIPTION AND NOT CODE. The WorldClaw paper (analysed in
``development_instructions/analyse-worldclaw.md``) names generated Blender
CODE as its main failure source. So the LLM emits a small JSON object with
clamped fields — junk becomes a default, never an exception and never an
`exec`:

    {form, pitch_deg, overhang_m, ridge_axis, material: {tone, kind},
     gable_tone?}

THE FRAME is the location's own SCENE frame (``scene_recipe``): origin at the
anchor pin, x east, y up, z south, metres. Blender is Z-up, so the job
converts ONCE, here::

    (x, y, z)_scene  ->  (x, -z, y)_blender

and the glTF exporter turns that back into the scene frame on the way out
(Blender (x, y, z) -> glTF (x, z, -y)), so the stored GLB speaks the same
coordinates as every other building model.

WHERE THE RESULT LANDS: in the location's building-model gallery
(``location_model3d``), as an unrigged GLB with ``roof_only: true`` in its
sidecar. That flag is the whole display contract of this feature — see
``docs/llm-blender-models.md`` and the § B addendum in
``docs/schnittstellen-3d.md``: a roof-only building model does NOT replace the
recipe shell, the client shows both.
"""
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

Vec2 = Tuple[float, float]

# ── Schema v1 — roof only ───────────────────────────────────────────────

#: The roof forms v1 can build. Every one of them is a closed body over the
#: footprint's oriented bounding box; nothing here needs a solver.
FORMS = ("gable", "hip", "shed", "flat")
#: Material kinds — a word for the LOOK, not a texture: v1 paints one
#: principled material with a tone and the roughness the kind implies.
KINDS = ("shingle", "thatch", "metal", "tile")
#: Ridge orientation: "auto" = along the LONGER side of the oriented bbox
#: (what a builder does), "x"/"z" = force the world axis.
RIDGE_AXES = ("auto", "x", "z")

PITCH_MIN_DEG = 5.0
PITCH_MAX_DEG = 60.0
OVERHANG_MIN_M = 0.0
OVERHANG_MAX_M = 1.0

DEFAULT_FORM = "gable"
DEFAULT_PITCH_DEG = 35.0
DEFAULT_OVERHANG_M = 0.4
DEFAULT_KIND = "shingle"
#: Fallback tone per kind — used when the LLM sends no/an unreadable colour.
DEFAULT_TONE = {"shingle": "#6b5f57", "thatch": "#b79a63",
                "metal": "#8f959b", "tile": "#9c5540"}
#: Surface roughness per kind. Metal is the only one that reflects.
ROUGHNESS = {"shingle": 0.80, "thatch": 0.95, "metal": 0.35, "tile": 0.60}

#: A flat roof is a SLAB, not a plane — a zero-thickness lid has no silhouette
#: and no underside. Metres.
FLAT_THICKNESS_M = 0.12
#: How far the roof's base plane sits BELOW the nominal eaves height
#: (storeys x storey height). The contour walls of the top storey end at
#: ``storeys * storey - 0.07`` (plate top 0.08 + wall height storey - 0.15),
#: so sinking the roof by 0.10 makes it OVERLAP the wall head by 0.03 m
#: instead of leaving a slit the far view would look straight through.
EAVES_SINK_M = 0.10


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _r(v: float, nd: int = 4) -> float:
    return round(float(v) + 0.0, nd)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _tone(value: Any, fallback: str) -> str:
    """``#rrggbb`` or the fallback — the one place a colour is parsed.

    Accepts ``#rgb`` too (an LLM writes it often enough) and expands it;
    anything else is not a colour and does not become one.
    """
    s = str(value or "").strip().lower()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3 and all(c in "0123456789abcdef" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) == 6 and all(c in "0123456789abcdef" for c in s):
        return f"#{s}"
    return fallback


def tone_to_linear(tone: str) -> List[float]:
    """``#rrggbb`` -> linear RGB, the space Blender's Base Color lives in.

    sRGB is what a person (and an LLM) names; a principled BSDF is fed linear
    values, so a tone handed over raw comes out washed out. The transfer
    function is the standard sRGB EOTF.
    """
    s = tone.lstrip("#")
    out: List[float] = []
    for i in (0, 2, 4):
        c = int(s[i:i + 2], 16) / 255.0
        out.append(round(c / 12.92 if c <= 0.04045
                         else ((c + 0.055) / 1.055) ** 2.4, 6))
    return out


def validate_description(raw: Any) -> Dict[str, Any]:
    """The LLM's answer -> a build description this module can build.

    NEVER raises and never rejects: an unknown form becomes the default form,
    a pitch outside the range is clamped to it, a missing material is the
    default material. The worst an answer can do is produce a plain gable —
    which is a roof, and a roof is what was asked for.
    """
    src = raw if isinstance(raw, dict) else {}
    material = src.get("material") if isinstance(src.get("material"), dict) else {}

    form = str(src.get("form") or "").strip().lower()
    if form not in FORMS:
        form = DEFAULT_FORM
    kind = str(material.get("kind") or "").strip().lower()
    if kind not in KINDS:
        kind = DEFAULT_KIND
    axis = str(src.get("ridge_axis") or "").strip().lower()
    if axis not in RIDGE_AXES:
        axis = "auto"

    # A flat roof HAS no pitch — carrying one would only invite a renderer to
    # use it. It is stated as 0 and the geometry ignores it either way.
    pitch = (0.0 if form == "flat"
             else _clamp(_num(src.get("pitch_deg"), DEFAULT_PITCH_DEG),
                         PITCH_MIN_DEG, PITCH_MAX_DEG))
    overhang = _clamp(_num(src.get("overhang_m"), DEFAULT_OVERHANG_M),
                      OVERHANG_MIN_M, OVERHANG_MAX_M)

    out: Dict[str, Any] = {
        "form": form,
        "pitch_deg": _r(pitch, 2),
        "overhang_m": _r(overhang, 3),
        "ridge_axis": axis,
        "material": {"tone": _tone(material.get("tone"), DEFAULT_TONE[kind]),
                     "kind": kind},
    }
    # The gable ends are the one part that is NOT roof surface — they are the
    # wall triangle under it, so a separate tone is allowed and only there.
    if form == "gable" and src.get("gable_tone"):
        out["gable_tone"] = _tone(src.get("gable_tone"), DEFAULT_TONE[kind])
    return out


# ── Footprint: which polygon the roof sits on ───────────────────────────

def _polygon(points: Any) -> List[Vec2]:
    """A list of [x, z] pairs, or [] — the same tolerance the recipe has."""
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        return []
    out: List[Vec2] = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return []
        out.append((_num(p[0]), _num(p[1])))
    return out


def _room_union_points(location: Dict[str, Any]) -> List[Vec2]:
    """Every room shell of the location as one point cloud (local metres).

    The LAST source of a footprint: a location that has neither a drawn
    building contour nor a boundary still has rooms, and their union is the
    shape the far-view shell shows. Composed through ``room_recipe`` rather
    than read off ``layout``, because that is where the outline of a room is
    decided (§ B1) — a second reading of the same rectangle is how two
    renderers drift apart.
    """
    from app.core.room_recipe import compose_recipe
    rooms = [r for r in (location.get("rooms") or []) if isinstance(r, dict)]
    map3d = location.get("map3d") or {}
    seed = int(_num(location.get("variant_seed")))
    pts: List[Vec2] = []
    for room in rooms:
        if not room.get("layout"):
            continue
        recipe = compose_recipe(room, [r for r in rooms if r is not room],
                                variant_seed=seed, map3d=map3d)
        if not recipe:
            continue
        for p in recipe.get("outline") or []:
            if isinstance(p, (list, tuple)) and len(p) == 2:
                pts.append((_num(p[0]), _num(p[1])))
    return pts


def footprint(location: Dict[str, Any]) -> Dict[str, Any]:
    """The polygon the roof is built over, with its precedence stated.

    THREE sources, in this order — the same order the scene recipe uses for
    its level plates (``scene_recipe._plates``), plus one fallback it does not
    need because a location without any of them has no walls either:

    1. ``map3d.outline`` — the DRAWN building contour. The author said where
       the building is; nothing may outvote that.
    2. ``map3d.boundary`` — the drawn plot boundary. Coarser, but authored.
    3. the union of the room shells — derived, and marked as such.

    Returns ``{source, points, ok}``; ``ok`` False means there is nothing to
    roof (no contour, no boundary, no room with a layout).
    """
    map3d = location.get("map3d") or {}
    pts = _polygon(map3d.get("outline"))
    if pts:
        return {"source": "outline", "points": pts, "ok": True}
    from app.core.world_geometry import polygon_points
    drawn = polygon_points(map3d.get("boundary"))
    if drawn:
        return {"source": "boundary", "points": [(float(x), float(z))
                                                 for x, z in drawn], "ok": True}
    cloud = _room_union_points(location)
    if len(cloud) >= 3:
        return {"source": "rooms", "points": cloud, "ok": True}
    return {"source": "none", "points": [], "ok": False}


# ── The oriented bounding box ───────────────────────────────────────────

def convex_hull(points: Sequence[Vec2]) -> List[Vec2]:
    """Monotone-chain hull in the XZ plane, counter-clockwise in (x, z)."""
    pts = sorted(set((round(x, 6), round(z, 6)) for x, z in points))
    if len(pts) < 3:
        return list(pts)

    def cross(o: Vec2, a: Vec2, b: Vec2) -> float:
        return ((a[0] - o[0]) * (b[1] - o[1])
                - (a[1] - o[1]) * (b[0] - o[0]))

    lower: List[Vec2] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Vec2] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def oriented_bbox(points: Sequence[Vec2]) -> Dict[str, Any]:
    """The minimum-area rectangle around a point set (rotating calipers).

    V1 RECTANGULARIZES, and says so: an L-shaped or curved contour is roofed
    by the rectangle that hugs it. A real roof over a concave outline needs a
    straight-skeleton solver, which is a stage of its own — a rectangle is
    honest, deterministic and right for the huts and houses this exists for.

    Returns ``{center, angle_deg, length, depth, u, v}`` where ``u`` is the
    rectangle's long-side direction in the XZ plane, ``length`` its extent
    along ``u`` and ``depth`` along ``v`` (so ``length >= depth`` always).
    """
    hull = convex_hull(points)
    if len(hull) < 3:
        xs = [p[0] for p in points] or [0.0]
        zs = [p[1] for p in points] or [0.0]
        length, depth = max(xs) - min(xs), max(zs) - min(zs)
        return {"center": ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2),
                "angle_deg": 0.0, "length": max(length, depth),
                "depth": min(length, depth),
                "u": (1.0, 0.0) if length >= depth else (0.0, 1.0),
                "v": (0.0, 1.0) if length >= depth else (-1.0, 0.0)}

    best: Optional[Tuple[float, Dict[str, Any]]] = None
    n = len(hull)
    for i in range(n):
        ax, az = hull[i]
        bx, bz = hull[(i + 1) % n]
        edge = math.hypot(bx - ax, bz - az)
        if edge < 1e-9:
            continue
        ux, uz = (bx - ax) / edge, (bz - az) / edge
        vx, vz = -uz, ux
        su = [p[0] * ux + p[1] * uz for p in hull]
        sv = [p[0] * vx + p[1] * vz for p in hull]
        du, dv = max(su) - min(su), max(sv) - min(sv)
        area = du * dv
        cu, cv = (max(su) + min(su)) / 2, (max(sv) + min(sv)) / 2
        rect = {"center": (cu * ux + cv * vx, cu * uz + cv * vz),
                "u": (ux, uz), "v": (vx, vz), "length": du, "depth": dv}
        # The long side names the rectangle: swapping here means every caller
        # can rely on length >= depth instead of checking.
        if dv > du:
            rect = {"center": rect["center"], "u": (vx, vz), "v": (-ux, -uz),
                    "length": dv, "depth": du}
        if best is None or area < best[0] - 1e-9:
            best = (area, rect)

    rect = best[1] if best else {}
    ux, uz = rect["u"]
    rect["angle_deg"] = _r(math.degrees(math.atan2(uz, ux)), 3)
    rect["center"] = (_r(rect["center"][0]), _r(rect["center"][1]))
    rect["length"] = _r(rect["length"])
    rect["depth"] = _r(rect["depth"])
    return rect


# ── Storeys and the eaves plane ─────────────────────────────────────────

def storey_height_m(location: Dict[str, Any]) -> float:
    from app.core.scene_recipe import DEFAULT_STOREY_REAL_M
    v = _num((location.get("map3d") or {}).get("storey_height_m"))
    return v if v > 0 else DEFAULT_STOREY_REAL_M


def storeys(location: Dict[str, Any]) -> int:
    """How many storeys stand ABOVE ground — the levels the rooms occupy.

    A basement does not raise a roof, so negative levels are ignored; a
    location whose rooms are all on level 0 (or which has no room at all) is
    one storey high.
    """
    levels = [int(_num((r.get("layout") or {}).get("level")))
              for r in (location.get("rooms") or [])
              if isinstance(r, dict) and r.get("layout")]
    top = max([lv for lv in levels if lv >= 0] or [0])
    return top + 1


def eaves_height_m(location: Dict[str, Any]) -> float:
    """The NOMINAL eaves height: storeys x storey height, in metres.

    Two storeys of 3 m are 6.00 m. What the walls really reach is 0.07 m less
    (level plate top 0.08 + wall height storey - 0.15), which is why the roof
    body is dropped by :data:`EAVES_SINK_M` on top — see :func:`roof_base_y`.
    """
    return _r(storeys(location) * storey_height_m(location))


def roof_base_y(location: Dict[str, Any]) -> float:
    """Where the roof's base plane sits in the scene frame (metres)."""
    return _r(eaves_height_m(location) - EAVES_SINK_M)


# ── Geometry: the roof body, in the scene frame ─────────────────────────

def _ridge_dirs(rect: Dict[str, Any], axis: str) -> Tuple[Vec2, Vec2, float, float]:
    """(ridge dir, span dir, ridge length, span width) for one ridge choice.

    ``auto`` runs the ridge along the LONG side, which is what a builder does
    — the slopes then face the two long walls. ``x``/``z`` force the world
    axis: whichever rectangle axis points more that way becomes the ridge.
    """
    u, v = tuple(rect["u"]), tuple(rect["v"])
    length, depth = float(rect["length"]), float(rect["depth"])
    if axis == "auto":
        return u, v, length, depth
    want = 0 if axis == "x" else 1
    return ((u, v, length, depth) if abs(u[want]) >= abs(v[want])
            else (v, u, depth, length))


def roof_geometry(description: Dict[str, Any],
                  rect: Dict[str, Any]) -> Dict[str, Any]:
    """The roof body as finished vertices and faces, in the SCENE frame.

    Pure: same description + same rectangle -> the same numbers, to the last
    decimal. y is measured from the roof's BASE PLANE (the wall line), so a
    negative y is the overhang hanging below it; :func:`build_job` adds the
    absolute height once.

    THE PITCH IS THE SLOPE OF THE SURFACE, and the surface passes through the
    wall line at y = 0. So the ridge stands ``(span/2) * tan(pitch)`` above the
    walls — the overhang does not raise it, it extends the same plane outward
    and DOWNWARD to ``-overhang * tan(pitch)``. A 10 x 8 m box at 30° carries
    its ridge 4 * tan30 = 2.309 m over the eaves, overhang or not.

    Returns ``{vertices, faces, groups, ridge_y, eaves_y, form}``; ``groups``
    marks which faces are gable ends (the only ones that may take a second
    tone).
    """
    form = str(description.get("form") or DEFAULT_FORM)
    pitch = math.radians(_num(description.get("pitch_deg")))
    ov = _num(description.get("overhang_m"))
    ridge_dir, span_dir, ridge_len, span = _ridge_dirs(
        rect, str(description.get("ridge_axis") or "auto"))
    cx, cz = rect["center"]
    slope = math.tan(pitch)

    half_r = ridge_len / 2.0 + ov          # along the ridge, outset
    half_s = span / 2.0 + ov               # across the ridge, outset
    eaves_y = -ov * slope                  # the outer edge hangs below the wall
    ridge_y = (span / 2.0) * slope         # over the WALL line, not the eaves

    def at(s: float, r: float, y: float) -> List[float]:
        """(across, along, height) in the rectangle's frame -> scene metres."""
        return [_r(cx + span_dir[0] * s + ridge_dir[0] * r), _r(y),
                _r(cz + span_dir[1] * s + ridge_dir[1] * r)]

    verts: List[List[float]] = []
    faces: List[List[int]] = []
    gable_faces: List[int] = []

    if form == "flat":
        # A slab on the wall head: top at +thickness, bottom at the wall line.
        for s, r in ((-half_s, -half_r), (half_s, -half_r),
                     (half_s, half_r), (-half_s, half_r)):
            verts.append(at(s, r, FLAT_THICKNESS_M))
        for s, r in ((-half_s, -half_r), (half_s, -half_r),
                     (half_s, half_r), (-half_s, half_r)):
            verts.append(at(s, r, 0.0))
        faces = [[0, 1, 2, 3], [7, 6, 5, 4],
                 [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]
        ridge_y = FLAT_THICKNESS_M
        eaves_y = 0.0
    elif form == "shed":
        # One plane, rising along +span. The low side keeps the wall line, the
        # high side is span * tan above it; the body is closed downward to the
        # low plane so the roof has an underside.
        y_lo, y_hi = eaves_y, (span + ov) * slope
        verts = [at(-half_s, -half_r, y_lo), at(half_s, -half_r, y_hi),
                 at(half_s, half_r, y_hi), at(-half_s, half_r, y_lo),
                 at(half_s, -half_r, y_lo), at(half_s, half_r, y_lo)]
        faces = [[0, 1, 2, 3],           # the slope
                 [1, 4, 5, 2],           # the high side, closed down
                 [0, 3, 5, 4],           # the underside
                 [0, 4, 1], [3, 2, 5]]   # the two triangular ends
        ridge_y = y_hi
    elif form == "hip":
        # Four slopes: the ridge is shortened by the same run the hips need,
        # so all four planes carry the identical pitch. The overhang cancels
        # out of that shortening — it outsets both extents by the same amount.
        half_ridge = max(0.0, (ridge_len - span) / 2.0)
        verts = [at(-half_s, -half_r, eaves_y), at(half_s, -half_r, eaves_y),
                 at(half_s, half_r, eaves_y), at(-half_s, half_r, eaves_y)]
        if half_ridge < 1e-6:
            # A square footprint: the ridge collapses to a point — a pyramid.
            verts.append(at(0.0, 0.0, ridge_y))
            faces = [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4],
                     [3, 2, 1, 0]]
        else:
            verts.append(at(0.0, -half_ridge, ridge_y))
            verts.append(at(0.0, half_ridge, ridge_y))
            faces = [[0, 1, 4],              # hip end
                     [1, 2, 5, 4],           # long slope
                     [2, 3, 5], [3, 0, 4, 5],
                     [3, 2, 1, 0]]           # the underside
    else:  # gable
        verts = [at(-half_s, -half_r, eaves_y), at(half_s, -half_r, eaves_y),
                 at(half_s, half_r, eaves_y), at(-half_s, half_r, eaves_y),
                 at(0.0, -half_r, ridge_y), at(0.0, half_r, ridge_y)]
        faces = [[1, 2, 5, 4],       # slope towards +span
                 [3, 0, 4, 5],       # slope towards -span
                 [0, 1, 4],          # gable end at -ridge
                 [2, 3, 5],          # gable end at +ridge
                 [3, 2, 1, 0]]       # the underside
        gable_faces = [2, 3]

    return {"vertices": verts, "faces": faces,
            "groups": {"gable": gable_faces},
            "ridge_y": _r(ridge_y), "eaves_y": _r(eaves_y), "form": form}


def bounds(vertices: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """AABB of a vertex list in the scene frame: ``{min, max, size, center}``."""
    xs = [v[0] for v in vertices] or [0.0]
    ys = [v[1] for v in vertices] or [0.0]
    zs = [v[2] for v in vertices] or [0.0]
    lo = [min(xs), min(ys), min(zs)]
    hi = [max(xs), max(ys), max(zs)]
    return {"min": [_r(v) for v in lo], "max": [_r(v) for v in hi],
            "size": [_r(hi[i] - lo[i]) for i in range(3)],
            "center": [_r((lo[i] + hi[i]) / 2) for i in range(3)]}


# ── Gathering: everything the LLM and the build need ────────────────────

def build_roof_description(location_id: str,
                           location: Optional[Dict[str, Any]] = None,
                           ) -> Dict[str, Any]:
    """What is KNOWN about this roof before anyone decides anything.

    The footprint (with its precedence), its oriented rectangle, the storey
    count and the eaves height — the facts the LLM prompt quotes and the build
    consumes. ``ok`` False means the location has nothing to roof.
    """
    if location is None:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id) or {}
    fp = footprint(location)
    if not fp["ok"]:
        return {"ok": False, "error": "no_footprint", "location_id": location_id,
                "name": str(location.get("name") or location_id)}
    rect = oriented_bbox(fp["points"])
    return {
        "ok": True,
        "location_id": location_id,
        "name": str(location.get("name") or location_id),
        "description": str(location.get("description") or ""),
        "style_hint": str(location.get("style_hint") or ""),
        "footprint": {"source": fp["source"],
                      "points": [[_r(x), _r(z)] for x, z in fp["points"]],
                      "length_m": rect["length"], "depth_m": rect["depth"],
                      "angle_deg": rect["angle_deg"],
                      "center": [rect["center"][0], rect["center"][1]]},
        "rect": rect,
        "storeys": storeys(location),
        "storey_height_m": _r(storey_height_m(location)),
        "eaves_height_m": eaves_height_m(location),
        "roof_base_y": roof_base_y(location),
    }


# ── The LLM stage ───────────────────────────────────────────────────────

def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """The first JSON object in a model answer, fences and prose tolerated."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def propose_roof(location_id: str,
                 location: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ONE LLM call: the facts of this building -> a validated description.

    Never fails the caller: an unroutable task, a refusing model or an
    unparsable answer all end in the DEFAULT description, flagged with
    ``llm: false``, because the user is going to see and edit the numbers
    before anything is built (propose-then-build — there is no silent magic
    in this feature).
    """
    facts = build_roof_description(location_id, location)
    if not facts.get("ok"):
        return facts
    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task

    fp = facts["footprint"]
    sys_p, user_p = render_task(
        "roof_design",
        name=facts["name"], description=facts["description"],
        style_hint=facts["style_hint"],
        length_m=fp["length_m"], depth_m=fp["depth_m"],
        storeys=facts["storeys"], eaves_height_m=facts["eaves_height_m"],
        forms=list(FORMS), kinds=list(KINDS),
        pitch_min=PITCH_MIN_DEG, pitch_max=PITCH_MAX_DEG,
        overhang_max=OVERHANG_MAX_M)
    raw = ""
    used_llm = False
    try:
        response = llm_call(task="roof_design", system_prompt=sys_p,
                            user_prompt=user_p, agent_name="system",
                            label=f"Roof design: {facts['name']}")
        raw = str(getattr(response, "content", "") or "")
        used_llm = _parse_json(raw) is not None
    except Exception as e:                       # routing off, provider down
        logger.info("Roof design for %s: no LLM answer (%s) — defaults",
                    location_id, e)
    desc = validate_description(_parse_json(raw))
    facts["description_json"] = desc
    facts["llm"] = used_llm
    return facts


# ── The Blender job ─────────────────────────────────────────────────────

def build_job(location_id: str, description: Any,
              location: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The finished job for ``app/blender/scripts/roof_build.py``.

    Deterministic by construction: every number in it comes from
    :func:`roof_geometry` and the rounding is done here, so the same
    description over the same footprint produces a byte-identical job — which
    is what the smoke checks.

    The vertices leave this function in BLENDER's frame ((x, y, z)_scene ->
    (x, -z, y)); the glTF exporter turns them back on the way out, so the
    stored GLB speaks the scene frame like every other building model.
    """
    facts = build_roof_description(location_id, location)
    if not facts.get("ok"):
        return facts
    desc = validate_description(description)
    geo = roof_geometry(desc, facts["rect"])
    box = bounds(geo["vertices"])

    kind = desc["material"]["kind"]
    materials = [{"name": "roof", "tone": desc["material"]["tone"],
                  "color": tone_to_linear(desc["material"]["tone"]),
                  "roughness": ROUGHNESS[kind]}]
    face_material = [0] * len(geo["faces"])
    if desc.get("gable_tone"):
        materials.append({"name": "gable", "tone": desc["gable_tone"],
                          "color": tone_to_linear(desc["gable_tone"]),
                          "roughness": ROUGHNESS[kind]})
        for idx in geo["groups"]["gable"]:
            face_material[idx] = 1

    job = {
        "kind": "roof",
        "location_id": location_id,
        "description": desc,
        "mesh": {
            "name": "roof",
            # Scene -> Blender, ONCE (the module header's conversion).
            "vertices": [[v[0], _r(-v[2]), v[1]] for v in geo["vertices"]],
            "faces": geo["faces"],
            "face_material": face_material,
        },
        "materials": materials,
        "export": {"glb": "roof.glb"},
    }
    # What the SIDECAR needs so the standard building-model placement puts the
    # roof exactly where these vertices are (metric law, § B2): the mesh is
    # measured by its widest XZ side, centred on its own AABB centre, and its
    # lower edge lands on ``bottom_y = LEVEL_PLATE_TOP − walk_y + offset_y``.
    # A generated roof declares no ``walk_y`` (nobody walks on it), so the
    # anchor is the storey-0 floor plate — the § B2 addendum of 2026-08-20
    # moved that pin by 0.02 m and this derivation moves WITH it, or the roof
    # would sit two centimetres off its own walls.
    from app.core.scene_recipe import LEVEL_PLATE_TOP
    base_y = facts["roof_base_y"]
    job["placement"] = {
        "width_m": _r(max(box["size"][0], box["size"][2])),
        "offset_x": box["center"][0],
        "offset_z": box["center"][2],
        "offset_y": _r(base_y + box["min"][1] - LEVEL_PLATE_TOP),
        "eaves_height_m": facts["eaves_height_m"],
        "roof_base_y": base_y,
        "ridge_y_world": _r(base_y + geo["ridge_y"]),
        "bbox_local": box,
        "vertex_count": len(geo["vertices"]),
        "face_count": len(geo["faces"]),
        "footprint_source": facts["footprint"]["source"],
    }
    return job


# ── Running it ──────────────────────────────────────────────────────────

def _timeout_s() -> int:
    """A parametric roof is seconds of work — the mesh-refinement timeout is
    the right order of magnitude here (unlike a Cycles render)."""
    try:
        from app.core import config
        return int(config.get("image_generation.blender_timeout_s", 120) or 120)
    except Exception:
        return 120


def generate_roof(location_id: str, description: Any = None) -> Dict[str, Any]:
    """Build the roof and store it as the location's building model.

    Blocking (see :func:`trigger_roof_generation` for the background call).
    Returns ``{ok, error, file, meta, job}``.
    """
    from app.blender import runner
    from app.core.location_model3d import save_roof_model

    job = build_job(location_id, description)
    if not job.get("ok", True):
        return {"ok": False, "error": str(job.get("error") or "no_footprint")}
    if not runner.is_available():
        return {"ok": False, "error": "blender_unavailable"}

    with tempfile.TemporaryDirectory(prefix="av-roof-") as tmp:
        tmp_dir = Path(tmp)
        job_file = tmp_dir / "job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False, sort_keys=True),
                            encoding="utf-8")
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        result = runner.run("roof_build", inputs={"job": job_file},
                            out_dir=out_dir, timeout_s=_timeout_s())
        if not result.get("ok"):
            logger.error("Roof build for %s failed: %s", location_id,
                         result.get("error"))
            return {"ok": False, "error": str(result.get("error") or "build failed")}
        glb = Path((result.get("outputs") or {}).get("glb") or "")
        if not glb.is_file():
            return {"ok": False, "error": "no glb produced"}
        data = result.get("data") or {}
        meta = save_roof_model(location_id, glb.read_bytes(),
                               placement=job["placement"],
                               description=job["description"])
    logger.info("Roof for %s: %s (%s, %d verts, ridge %.2f m)", location_id,
                meta.get("filename"), job["description"]["form"],
                int(data.get("vertices") or job["placement"]["vertex_count"]),
                job["placement"]["ridge_y_world"])
    return {"ok": True, "error": "", "meta": meta, "job": job,
            "data": data}


def trigger_roof_generation(location_id: str, description: Any = None) -> bool:
    """Start the build in the background; False = one is already running.

    Same shape as every other model job here: a daemon thread, a header task
    for visibility, and the pending flag the admin panel already polls
    (``location_model3d.is_pending``).
    """
    import threading
    from app.core.location_model3d import claim_job, release_job
    if not claim_job(location_id, kind="roof"):
        return False

    def _run() -> None:
        task_id = ""
        error = ""
        try:
            from app.core.task_queue import get_task_queue
            from app.models.world import get_location_by_id
            label = str((get_location_by_id(location_id) or {}).get("name")
                        or location_id)
            try:
                task_id = get_task_queue().track_start(
                    "model3d_generation", f"Roof: {label}", start_running=True)
            except Exception:
                task_id = ""
            res = generate_roof(location_id, description)
            error = "" if res.get("ok") else str(res.get("error") or "failed")
        except Exception as e:                   # last resort — a thread dies silently
            error = str(e)
            logger.error("Roof generation for %s failed: %s", location_id, e)
        finally:
            if task_id:
                try:
                    from app.core.task_queue import get_task_queue
                    get_task_queue().track_finish(task_id, error=error)
                except Exception:
                    pass
            release_job(location_id, kind="roof")

    threading.Thread(target=_run, daemon=True).start()
    return True
