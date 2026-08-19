"""Map layouts an LLM drew — normalize, warn, apply, snapshot (E10 task 1).

The world-dev chat can emit a whole MAP: painted terrain areas, optional
height areas and where the existing locations stand, all in world metres.
This module is the one place that turns such a draft into the exact rows the
map editor writes, so nothing downstream has to know the map came from a
model rather than from a mouse.

Three layers, deliberately separated:

* **Pure geometry** — :func:`simplify_polygon`, :func:`stroke_to_polygon` and
  :func:`decorate_stroke`. No DB, no config. The last two are the SERVER TWIN
  of ``frontend/src/tabs/map/mapMath.ts``: the LLM describes a river as a
  centre LINE plus a width, and the ribbon it becomes must be the very
  polygon the editor would have produced from the same recipe — otherwise the
  drawn shape jumps the first time somebody drags one of its handles. Ported
  constant for constant, including the seeded PRNG
  (``@anima/scene-render.seededRandom``), and pinned to the TS docstring's
  hand-derived numbers in ``scripts/smoke_map_layout.py``.
* **Validation** — :func:`sanitize_map_layout`, a pure function: the catalog
  and the world's locations are handed IN, so the whole rule set is testable
  without a world. It returns the normalized draft plus WARNINGS, never
  exceptions, for everything a person can still want (a hut on impassable
  rock is a legitimate authoring choice); only junk is dropped, and dropping
  is itself a warning.
* **Writing** — :func:`apply_map_layout`, :func:`map_snapshot`,
  :func:`list_snapshots`, :func:`restore_snapshot`. These touch the DB, and
  they validate EVERYTHING before the first write: a layout with one broken
  polygon must leave the world exactly as it was, not half-painted.

The snapshot is the undo the map editor does not have. It is a full copy of
the painted world (areas, height areas, every location's placement) under
``<storage>/.cache/map_snapshots/`` — gitignored, capped at
:data:`MAX_SNAPSHOTS`, and restored WITH the original row ids, so a restore
puts back the very areas that were there rather than look-alikes.
"""

import json
import math
import re
import secrets
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("map_layout")

# ── Ported from frontend/src/tabs/map/mapMath.ts ────────────────────────────
#: A join is bevelled once the miter would stick out further than this many
#: stroke widths (``STROKE_MITER_LIMIT_WIDTHS``).
STROKE_MITER_LIMIT_WIDTHS = 2
#: Two stroke points closer than this are the same click, not a segment.
STROKE_EPS = 1e-9
#: Points a DECORATED centre line may end up with — the budget of the
#: server's 256-point polygon limit counted where it is spent (a mitred
#: ribbon is 2n points wide).
MAX_DECORATED_POINTS = 120
#: The smallest deflection, as a fraction of the amplitude.
DEFLECTION_MIN_FACTOR = 0.4
#: Deflections per full wave of the ``wavy`` style.
WAVE_SPACINGS_PER_PERIOD = 4
#: The three styles a centre line may be bent with (``mapMath.STROKE_STYLES``).
STROKE_STYLES = ("straight", "jagged", "wavy")

#: How many snapshots are kept per world. Twenty apply runs is far more
#: history than anybody scrolls back through, and each file is the whole
#: painted world.
MAX_SNAPSHOTS = 20

#: Points a polygon in the ``{existing_map}`` prompt injection is boiled down
#: to. Twelve is enough to recognise a shape and small enough that a whole map
#: fits in a prompt.
SIMPLIFY_MAX_POINTS = 12

#: What ``meta.source`` every row this module writes carries, so the editor
#: (and a later cleanup) can tell machine-drawn ground from hand-drawn.
SOURCE = "world_dev"


# ── Pure geometry ───────────────────────────────────────────────────────────

def _finite(value: Any) -> Optional[float]:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _round2(value: float) -> float:
    """JavaScript's ``Math.round(v * 100) / 100``, to the digit.

    Python's :func:`round` is banker's rounding and would disagree with the
    editor on every exact half — 2.345 rounds to 2.34 here and 2.35 there,
    which is a different polygon. ``floor(x + 0.5)`` is what JS does, and the
    ``+ 0.0`` normalizes ``-0.0`` to ``0.0`` (the same reason ``mapMath``
    does it: JSON writes the sign out).
    """
    out = math.floor(value * 100 + 0.5) / 100.0
    return out + 0.0 if out else 0.0


def _js_number(value: float) -> str:
    """A number the way JS stringifies it — needed for the STROKE SEED.

    The seed of a decoration is the clicked line rendered into a string
    (:func:`stroke_seed`), so ``10`` must not become ``"10.0"`` here while it
    is ``"10"`` in the editor: one differing character and the two sides draw
    different rivers from the same recipe.
    """
    if value == int(value) and abs(value) < 1e21:
        return str(int(value))
    return repr(float(value))


def seeded_random(seed: str) -> Callable[[], float]:
    """Deterministic PRNG over a string seed — the twin of
    ``@anima/scene-render.seededRandom`` (FNV-1a state, xorshift stream).

    Kept unsigned 32-bit throughout: ``Math.imul`` returns a SIGNED int32,
    but every operation downstream is a bitwise one, so the unsigned
    representation of the same 32 bits produces the identical stream.
    """
    h = 2166136261
    for ch in seed:
        h = (h ^ ord(ch)) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    state = [h]

    def rnd() -> float:
        v = state[0]
        v = ((v ^ (v >> 15)) * 2246822519) & 0xFFFFFFFF
        v = ((v ^ (v >> 13)) * 3266489917) & 0xFFFFFFFF
        v = (v ^ (v >> 16)) & 0xFFFFFFFF
        state[0] = v
        return v / 4294967296.0

    return rnd


def stroke_seed(points: Sequence[Sequence[float]]) -> str:
    """The seed of ONE decoration — the clicked line itself, so the same
    stroke gives the same spikes on the server and in the editor."""
    parts = ["terrain:stroke"]
    for p in points:
        try:
            parts.append(f"{_js_number(float(p[0]))},{_js_number(float(p[1]))}")
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            parts.append("undefined,undefined")
    return ":".join(parts)


def _clean_line(points: Any) -> Optional[List[List[float]]]:
    """The centre line as both ribbon builders read it: finite coordinates,
    no repeated click. None when it is not a line at all."""
    if not isinstance(points, (list, tuple)):
        return None
    line: List[List[float]] = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        x, z = _finite(p[0]), _finite(p[1])
        if x is None or z is None:
            return None
        if line and abs(line[-1][0] - x) < STROKE_EPS \
                and abs(line[-1][1] - z) < STROKE_EPS:
            continue
        line.append([x, z])
    return line


def decorate_stroke(points: Any, style: str, spacing_m: float,
                    amplitude_m: float, seed: str = "") -> Dict[str, Any]:
    """Bend a clicked centre line — the step BEFORE :func:`stroke_to_polygon`.

    The port of ``mapMath.decorateStroke``. Returns
    ``{"points": [...], "spacing_m": float, "capped": bool}``; the input list
    comes back unchanged for the ``straight`` style, an unknown style, a
    non-positive spacing or amplitude, a line with fewer than two distinct
    points and a line of zero length — a decoration that cannot be computed
    is no decoration, never half of one.

    Hand-derived (the TS docstring's cases, pinned in the smoke):
    ``[(0,0),(100,0)]``, jagged, spacing 10, amplitude 2 → deflections at
    5, 15, …, 95, so 10 of them and 12 points in all, alternating sides of the
    normal ``(0,-1)`` with heights in ``[0.8, 2]``.
    """
    plain = {"points": points, "spacing_m": spacing_m, "capped": False}
    if style not in ("jagged", "wavy"):
        return plain
    sp = _finite(spacing_m)
    am = _finite(amplitude_m)
    if sp is None or sp <= 0 or am is None or am <= 0:
        return plain
    line = _clean_line(points)
    if line is None or len(line) < 2:
        return plain

    cum = [0.0]
    for i in range(1, len(line)):
        cum.append(cum[i - 1] + math.hypot(line[i][0] - line[i - 1][0],
                                           line[i][1] - line[i - 1][1]))
    total = cum[-1]
    if not total > 0:
        return plain

    room = MAX_DECORATED_POINTS - len(line)
    if room <= 0:
        return {"points": line, "spacing_m": sp, "capped": True}
    spacing = sp
    capped = False
    if spacing < total / room:
        spacing = total / room
        capped = True

    rnd = seeded_random(seed or stroke_seed(line))
    phase = rnd() * math.pi * 2
    out: List[List[float]] = [line[0]]
    seg = 1
    i = 0
    d = spacing / 2
    while d < total - STROKE_EPS:
        while seg < len(line) - 1 and cum[seg] <= d:
            out.append(line[seg])
            seg += 1
        ax, az = line[seg - 1]
        bx, bz = line[seg]
        seg_len = cum[seg] - cum[seg - 1]
        f = (d - cum[seg - 1]) / seg_len
        nx = (bz - az) / seg_len
        nz = -(bx - ax) / seg_len
        height = am * (DEFLECTION_MIN_FACTOR
                       + (1 - DEFLECTION_MIN_FACTOR) * rnd())
        if style == "jagged":
            side = 1.0 if i % 2 == 0 else -1.0
        else:
            side = math.sin(phase + (i * 2 * math.pi) / WAVE_SPACINGS_PER_PERIOD)
        off = height * side
        out.append([_round2(ax + f * (bx - ax) + off * nx),
                    _round2(az + f * (bz - az) + off * nz)])
        d += spacing
        i += 1
    while seg < len(line):
        out.append(line[seg])
        seg += 1
    return {"points": out, "spacing_m": spacing, "capped": capped}


def stroke_to_polygon(points: Any, width_m: float
                      ) -> Optional[List[List[float]]]:
    """A centre LINE plus a width becomes the AREA polygon the world stores.

    The port of ``mapMath.strokeToPolygon``, conventions and all: a segment
    direction ``d = (dx, dz)`` has side normals ``A = (dz, -dx)`` and
    ``B = (-dz, dx)``; joins are mitered until the spike would exceed
    ``STROKE_MITER_LIMIT_WIDTHS × width_m`` and are bevelled from there; caps
    are flat.

    Hand-derived: ``[(0,0),(10,0)]`` at width 4 → offset 2, ``nA = (0,-1)``,
    ``nB = (0,1)`` → ``[(0,-2),(10,-2),(10,2),(0,2)]``.

    None — never half a polygon — for fewer than 2 distinct points, a width
    that is not positive, a non-finite coordinate, and a line so short that
    the 2-decimal grid collapses it.
    """
    w = _finite(width_m)
    if w is None or w <= 0:
        return None
    line = _clean_line(points)
    if line is None or len(line) < 2:
        return None

    nrm: List[Tuple[float, float]] = []
    for i in range(1, len(line)):
        dx = line[i][0] - line[i - 1][0]
        dz = line[i][1] - line[i - 1][1]
        length = math.hypot(dx, dz)
        nrm.append((dz / length, -dx / length))

    off = w / 2.0
    miter_max = STROKE_MITER_LIMIT_WIDTHS * w

    def build_side(s: float) -> List[List[float]]:
        out: List[List[float]] = []

        def push(px: float, pz: float, nx: float, nz: float) -> None:
            out.append([px + s * off * nx, pz + s * off * nz])

        push(line[0][0], line[0][1], nrm[0][0], nrm[0][1])
        for i in range(1, len(line) - 1):
            px, pz = line[i]
            n1x, n1z = nrm[i - 1]
            n2x, n2z = nrm[i]
            mx, mz = n1x + n2x, n1z + n2z
            mlen = math.hypot(mx, mz)
            mitered = False
            if mlen > STROKE_EPS:
                cos_half = (mx / mlen) * n1x + (mz / mlen) * n1z
                if cos_half > STROKE_EPS:
                    miter_len = off / cos_half
                    if miter_len <= miter_max:
                        out.append([px + s * (mx / mlen) * miter_len,
                                    pz + s * (mz / mlen) * miter_len])
                        mitered = True
            if not mitered:
                push(px, pz, n1x, n1z)
                push(px, pz, n2x, n2z)
        last = nrm[-1]
        push(line[-1][0], line[-1][1], last[0], last[1])
        return out

    ring = [[_round2(x), _round2(z)]
            for x, z in build_side(1.0) + list(reversed(build_side(-1.0)))]
    poly: List[List[float]] = []
    for pt in ring:
        if poly and poly[-1][0] == pt[0] and poly[-1][1] == pt[1]:
            continue
        poly.append(pt)
    if len(poly) > 1 and poly[0][0] == poly[-1][0] and poly[0][1] == poly[-1][1]:
        poly.pop()
    return poly if len(poly) >= 3 else None


def simplify_polygon(points: Any,
                     max_points: int = SIMPLIFY_MAX_POINTS
                     ) -> List[List[float]]:
    """Boil a ring down to at most ``max_points`` vertices, keeping its shape.

    Vertex decimation by EFFECTIVE AREA (Visvalingam-Whyatt): repeatedly drop
    the vertex whose triangle with its two neighbours is smallest, recomputing
    the neighbours each time, until the budget is met.

    NOT the epsilon form of Douglas-Peucker the plan sketched, and the reason
    is the job: the prompt has room for twelve points per shape, not for
    "whatever a tolerance leaves", and a budget is not something an epsilon
    search hits — on a smooth outline it jumps from ten points straight to
    eighteen. Running DP greedily against a budget instead does meet it, but
    it optimizes the wrong quantity: it minimizes the DEVIATION from the
    chords, and on a circle that spends the last splits subdividing arcs that
    were already fine, leaving an uneven ring that loses 5.8 % of the area.
    Visvalingam optimizes exactly what a shrunken map shape is judged on — how
    much ground it still covers — and lands at 4.8 %, within a hair of the
    4.4 % a regular 12-gon inscribed in a circle can possibly reach.

    Deterministic: equal triangles go to the EARLIER vertex. A polygon already
    inside the budget comes back cleaned but otherwise untouched; anything with
    fewer than 3 usable vertices comes back as the empty list — it was never
    an area.
    """
    pts: List[List[float]] = []
    for p in (points or []):
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return []
        x, z = _finite(p[0]), _finite(p[1])
        if x is None or z is None:
            return []
        pts.append([x, z])
    # A ring that repeats its first vertex at the end carries no extra shape.
    while len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return []
    budget = max(3, int(max_points))
    if len(pts) <= budget:
        return pts

    def triangle(a: List[float], b: List[float], c: List[float]) -> float:
        return abs((b[0] - a[0]) * (c[1] - a[1])
                   - (b[1] - a[1]) * (c[0] - a[0])) / 2.0

    ring = list(pts)
    while len(ring) > budget:
        smallest = None
        for k in range(len(ring)):
            t = triangle(ring[k - 1], ring[k], ring[(k + 1) % len(ring)])
            if smallest is None or t < smallest[0]:
                smallest = (t, k)
        ring.pop(smallest[1])
    return ring


def _segments_cross(a: List[float], b: List[float],
                    c: List[float], d: List[float]) -> bool:
    """Do the OPEN segments a-b and c-d cross? Touching endpoints do not
    count — adjacent edges of a ring always share one."""
    def orient(p, q, r) -> float:
        return ((q[0] - p[0]) * (r[1] - p[1])
                - (q[1] - p[1]) * (r[0] - p[0]))
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def polygon_self_intersects(polygon: Sequence[Sequence[float]]) -> bool:
    """Does the ring cross itself? A plain O(n²) edge test — polygons here
    are capped at 256 points, and the answer is a WARNING, not a gate."""
    pts = [[float(p[0]), float(p[1])] for p in polygon]
    n = len(pts)
    if n < 4:
        return False
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            # Skip the neighbours (they share a vertex by construction).
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            if _segments_cross(a, b, pts[j], pts[(j + 1) % n]):
                return True
    return False


# ── Validation ──────────────────────────────────────────────────────────────

#: The warning vocabulary. Everything a person could still WANT is a warning
#: and the entry survives; only junk is dropped, and the drop is a warning
#: too. The frontend renders these by code, so they are a contract.
WARNING_CODES = (
    "unknown_kind",       # terrain kind not in the catalog — area dropped
    "unknown_location",   # location id not in this world — entry dropped
    "invalid_geometry",   # polygon/stroke unusable — entry dropped
    "too_many_points",    # more than the 256 the sanitizer takes — dropped
    "self_intersecting",  # ring crosses itself — kept
    "out_of_bounds",      # a point outside the agreed box — kept
    "on_impassable",      # a place standing on impassable ground — kept
    "footprint_overlap",  # two placed footprints overlap — both kept
)


def _warn(out: List[Dict[str, str]], code: str, ref: str, message: str) -> None:
    out.append({"code": code, "ref": ref, "message": message})


def _box_union(a: Optional[Dict[str, Any]],
               b: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """The smallest box containing both, or whichever one exists."""
    boxes = [x for x in (a, b) if _valid_box(x)]
    if not boxes:
        return None
    return {"min_x": min(float(x["min_x"]) for x in boxes),
            "min_z": min(float(x["min_z"]) for x in boxes),
            "max_x": max(float(x["max_x"]) for x in boxes),
            "max_z": max(float(x["max_z"]) for x in boxes)}


def _valid_box(box: Any) -> bool:
    if not isinstance(box, dict):
        return False
    vals = [_finite(box.get(k)) for k in ("min_x", "min_z", "max_x", "max_z")]
    if any(v is None for v in vals):
        return False
    return vals[0] <= vals[2] and vals[1] <= vals[3]


def _outside(box: Dict[str, float], x: float, z: float) -> bool:
    return (x < box["min_x"] or x > box["max_x"]
            or z < box["min_z"] or z > box["max_z"])


def _entry_world_boundary(entry: Dict[str, Any]) -> Optional[List[Any]]:
    """World-metre outline of one placement entry, or None without area.

    A draft entry is not a location record — it carries the proposed pin
    (``pos_x``/``pos_z``/``yaw_deg``) next to the world's own DRAWN outline
    (``boundary``), which is exactly what
    ``world_geometry.effective_boundary`` reads out of a location dict. So the
    two halves are handed to it in the shape it expects rather than the
    transform being written a second time here. ``plan_width_m`` is NOT part
    of it: since 2026-08-19 a width is no shape, and a location without an
    outline has no area to overlap with.
    """
    from app.core.world_geometry import boundary_world_points
    return boundary_world_points({
        "pos_x": entry.get("pos_x"), "pos_z": entry.get("pos_z"),
        "yaw_deg": entry.get("yaw_deg"),
        "map3d": {"boundary": entry.get("boundary")},
    })


def boundaries_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Do two placed locations share ground? Exact polygon overlap over their
    effective boundaries (contract v6 "Gebiete").

    EXACT, not the axis-aligned approximation: a turned place beside a
    straight one would otherwise be reported as overlapping whenever its
    bounding box reaches over, and a warning nobody can act on is noise. It is
    also exact for CONCAVE outlines, where a bounding box says almost nothing:
    two Ls can interlock arm-in-notch with their boxes fully on top of each
    other and still not share a single square metre. A shared edge counts as an
    overlap — the conservative answer, matching
    ``world_geometry.boundary_contains``.

    Both dicts need ``pos_x``, ``pos_z``, ``yaw_deg`` and a DRAWN ``boundary``
    in local metres; a place without one has no area and can overlap nothing.

    Hand-derived: two 40 m squares at yaw 0, centres 30 m apart on x, span
    [-20, 20] and [10, 50] -> they share [10, 20] -> True. At 50 m apart the
    spans are [-20, 20] and [30, 70] -> a gap of 10 m -> False.
    """
    from app.core.world_geometry import polygons_overlap
    pa = _entry_world_boundary(a)
    pb = _entry_world_boundary(b)
    if pa is None or pb is None:
        return False
    return polygons_overlap(pa, pb)


def sanitize_map_layout(data: Any, *,
                        catalog: Dict[str, Dict[str, Any]],
                        locations_by_id: Dict[str, Dict[str, Any]],
                        bounds: Optional[Dict[str, Any]] = None,
                        default_kind: str = "grass"
                        ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Turn one LLM map draft into the rows :func:`apply_map_layout` writes.

    PURE: the terrain catalog and the world's locations are handed in, so the
    whole rule set runs without a world DB. ``locations_by_id`` maps a
    location id to at least
    ``{"name": str, "boundary": list | None, "plan_width_m": float}`` — the
    location's own OUTLINE in local metres (``map3d.boundary``, contract v6)
    plus its derived bounding-box width, which the preview quotes but no rule
    reads as a shape. No boundary means "no area", which simply skips the
    overlap test for that place.

    ``bounds`` is the world's CURRENT extent; the draft may propose its own,
    and a coordinate is out of bounds only when it leaves BOTH — a new map is
    allowed to be bigger than the empty world it grows into.

    Returns ``(normalized, warnings)``. Raises ValueError only when the draft
    is not an object or carries nothing at all; everything else is a warning,
    because "a hut on the rocks" is an authoring decision and not a defect.
    """
    if not isinstance(data, dict):
        raise ValueError("map layout must be an object")

    warnings: List[Dict[str, str]] = []
    proposed = data.get("bounds") if _valid_box(data.get("bounds")) else None
    box = _box_union(bounds, proposed)

    # ── terrain areas ──
    areas: List[Dict[str, Any]] = []
    raw_areas = data.get("terrain_areas")
    if raw_areas is None:
        raw_areas = []
    if not isinstance(raw_areas, list):
        raise ValueError("terrain_areas must be a list")
    for i, raw in enumerate(raw_areas):
        ref = f"terrain_areas[{i}]"
        if not isinstance(raw, dict):
            _warn(warnings, "invalid_geometry", ref, "Entry is not an object.")
            continue
        kind = str(raw.get("kind") or "").strip()
        label = str(raw.get("label") or "").strip()
        name = label or kind or ref
        if kind not in catalog:
            _warn(warnings, "unknown_kind", ref,
                  f"'{name}': terrain kind {kind!r} is not in this world's "
                  f"catalog — area dropped.")
            continue
        meta: Dict[str, Any] = {"source": SOURCE}
        if label:
            meta["label"] = label
        polygon: Optional[List[List[float]]] = None

        stroke = raw.get("stroke")
        if isinstance(stroke, dict):
            width = _finite(stroke.get("width_m"))
            line = _clean_line(stroke.get("points"))
            if width is None or width <= 0 or line is None or len(line) < 2:
                _warn(warnings, "invalid_geometry", ref,
                      f"'{name}': stroke needs at least 2 distinct points and "
                      f"a positive width_m — area dropped.")
                continue
            style = str(stroke.get("style") or "straight").strip()
            if style not in STROKE_STYLES:
                style = "straight"
            spacing = _finite(stroke.get("spacing_m")) or 12.0
            amplitude = _finite(stroke.get("amplitude_m")) or 3.0
            deco = decorate_stroke(line, style, spacing, amplitude)
            polygon = stroke_to_polygon(deco["points"], width)
            if polygon is None:
                _warn(warnings, "invalid_geometry", ref,
                      f"'{name}': the stroke collapses to no area — dropped.")
                continue
            recipe: Dict[str, Any] = {"points": [[_round2(x), _round2(z)]
                                                 for x, z in line],
                                      "width_m": _round2(width)}
            if style != "straight":
                recipe["style"] = style
                recipe["spacing_m"] = _round2(deco["spacing_m"])
                recipe["amplitude_m"] = _round2(amplitude)
            meta["stroke"] = recipe
        else:
            polygon = _clean_line(raw.get("polygon"))
            if polygon is None or len(polygon) < 3:
                _warn(warnings, "invalid_geometry", ref,
                      f"'{name}': polygon needs at least 3 distinct "
                      f"[x, z] points — area dropped.")
                continue
            polygon = [[_round2(x), _round2(z)] for x, z in polygon]

        if len(polygon) > 256:
            _warn(warnings, "too_many_points", ref,
                  f"'{name}': {len(polygon)} points, the map takes at most "
                  f"256 — area dropped.")
            continue
        if polygon_self_intersects(polygon):
            _warn(warnings, "self_intersecting", ref,
                  f"'{name}': the outline crosses itself — the painted area "
                  f"will look inverted where it does.")
        if box:
            outliers = [p for p in polygon if _outside(box, p[0], p[1])]
            if outliers:
                _warn(warnings, "out_of_bounds", ref,
                      f"'{name}': {len(outliers)} of {len(polygon)} points lie "
                      f"outside the agreed map bounds.")
        z_order = _finite(raw.get("z_order"))
        areas.append({"kind": kind, "polygon": polygon,
                      "z_order": int(z_order) if z_order is not None else 0,
                      "meta": meta})

    # ── height areas ──
    heights: List[Dict[str, Any]] = []
    raw_heights = data.get("height_areas")
    if raw_heights is None:
        raw_heights = []
    if not isinstance(raw_heights, list):
        raise ValueError("height_areas must be a list")
    for i, raw in enumerate(raw_heights):
        ref = f"height_areas[{i}]"
        if not isinstance(raw, dict):
            _warn(warnings, "invalid_geometry", ref, "Entry is not an object.")
            continue
        label = str(raw.get("label") or "").strip()
        name = label or ref
        polygon = _clean_line(raw.get("polygon"))
        if polygon is None or len(polygon) < 3:
            _warn(warnings, "invalid_geometry", ref,
                  f"'{name}': polygon needs at least 3 distinct [x, z] "
                  f"points — height area dropped.")
            continue
        polygon = [[_round2(x), _round2(z)] for x, z in polygon]
        if len(polygon) > 256:
            _warn(warnings, "too_many_points", ref,
                  f"'{name}': {len(polygon)} points, the map takes at most "
                  f"256 — height area dropped.")
            continue
        if polygon_self_intersects(polygon):
            _warn(warnings, "self_intersecting", ref,
                  f"'{name}': the outline crosses itself.")
        if box:
            outliers = [p for p in polygon if _outside(box, p[0], p[1])]
            if outliers:
                _warn(warnings, "out_of_bounds", ref,
                      f"'{name}': {len(outliers)} of {len(polygon)} points lie "
                      f"outside the agreed map bounds.")
        meta = {"source": SOURCE}
        if label:
            meta["label"] = label
        height_m = _finite(raw.get("height_m")) or 0.0
        falloff_m = _finite(raw.get("falloff_m"))
        heights.append({"polygon": polygon,
                        "height_m": round(height_m, 3),
                        "falloff_m": round(max(falloff_m or 0.0, 0.0), 3),
                        "meta": meta})

    # ── locations ──
    # The draft's own areas are the ground the placement is judged against
    # (never the DB's): the model just drew this water, and a hut it put in
    # the middle of it must be reported even though nothing is painted yet.
    from app.core.terrain_query import kind_at
    draft_areas = sorted(areas, key=lambda a: a["z_order"])
    placed: List[Dict[str, Any]] = []
    seen_ids: Dict[str, int] = {}
    raw_locs = data.get("locations")
    if raw_locs is None:
        raw_locs = []
    if not isinstance(raw_locs, list):
        raise ValueError("locations must be a list")
    for i, raw in enumerate(raw_locs):
        ref = f"locations[{i}]"
        if not isinstance(raw, dict):
            _warn(warnings, "invalid_geometry", ref, "Entry is not an object.")
            continue
        loc_id = str(raw.get("id") or "").strip()
        known = locations_by_id.get(loc_id)
        if not loc_id or known is None:
            _warn(warnings, "unknown_location", ref,
                  f"No location with id {loc_id!r} in this world — entry "
                  f"dropped. Only existing locations can be placed.")
            continue
        if loc_id in seen_ids:
            _warn(warnings, "invalid_geometry", ref,
                  f"'{known.get('name') or loc_id}' is placed twice — the "
                  f"later entry is dropped.")
            continue
        px, pz = _finite(raw.get("pos_x")), _finite(raw.get("pos_z"))
        if px is None or pz is None:
            _warn(warnings, "invalid_geometry", ref,
                  f"'{known.get('name') or loc_id}': pos_x/pos_z must be "
                  f"numbers — entry dropped.")
            continue
        yaw = _finite(raw.get("yaw_deg")) or 0.0
        entry = {"id": loc_id,
                 "pos_x": _round2(px), "pos_z": _round2(pz),
                 "yaw_deg": round(yaw, 1) % 360.0,
                 # Preview extras — apply reads none of them, but the draft
                 # map has to be drawable without a second round trip, and
                 # since v6 what is drawn is the location's OUTLINE.
                 "name": str(known.get("name") or loc_id),
                 "boundary": known.get("boundary"),
                 "plan_width_m": float(known.get("plan_width_m") or 0.0)}
        why = str(raw.get("why") or "").strip()
        if why:
            entry["why"] = why
        seen_ids[loc_id] = len(placed)
        placed.append(entry)

        if box and _outside(box, entry["pos_x"], entry["pos_z"]):
            _warn(warnings, "out_of_bounds", ref,
                  f"'{entry['name']}' stands outside the agreed map bounds.")

        ground = kind_at(entry["pos_x"], entry["pos_z"], areas=draft_areas,
                         default_kind=default_kind)
        if not bool((catalog.get(ground) or {}).get("passable", True)):
            _warn(warnings, "on_impassable", ref,
                  f"'{entry['name']}' stands on {ground!r}, which nobody can "
                  f"walk on — the place would be unreachable.")

    # Boundary overlaps, once per PAIR. Both survive: overlapping places are
    # legal (a hut on a village square), they are just rarely intended.
    for a_i in range(len(placed)):
        for b_i in range(a_i + 1, len(placed)):
            a, b = placed[a_i], placed[b_i]
            if not boundaries_overlap(a, b):
                continue
            _warn(warnings, "footprint_overlap", f"locations[{b_i}]",
                  f"'{a['name']}' and '{b['name']}' overlap — their outlines "
                  f"share ground.")

    # The ONE hard error besides a non-object: a draft that says nothing at
    # all. A draft whose entries were ALL dropped is not that — it carries a
    # warning per entry, and the user has to see them rather than a 400.
    if not raw_areas and not raw_heights and not raw_locs:
        raise ValueError("map layout is empty — no terrain areas, height "
                         "areas or placements")

    normalized = {
        "summary": str(data.get("summary") or "").strip(),
        "bounds": box,
        "terrain_areas": areas,
        "height_areas": heights,
        "locations": placed,
    }
    return normalized, warnings


def layout_counts(normalized: Dict[str, Any]) -> Dict[str, int]:
    """``{areas, heights, positions}`` of a normalized layout."""
    return {"areas": len(normalized.get("terrain_areas") or []),
            "heights": len(normalized.get("height_areas") or []),
            "positions": len(normalized.get("locations") or [])}


# ── Writing ─────────────────────────────────────────────────────────────────

def current_world_bounds() -> Optional[Dict[str, float]]:
    """The world's current extent in metres — placed BOUNDARIES AND painted
    ground, the same two inputs ``world_ops`` builds ``world_bounds`` from.

    None on an empty world: there is no box, and inventing one would tell the
    model its map has to fit inside nothing.
    """
    from app.core.world_geometry import boundary_world_points, polygon_bounds
    from app.models.terrain import list_areas
    from app.models.world import list_locations

    xs: List[float] = []
    zs: List[float] = []
    for loc in list_locations():
        box = polygon_bounds(boundary_world_points(loc))
        if box is None:
            continue
        xs.extend((box[0], box[2]))
        zs.extend((box[1], box[3]))
    for area in list_areas():
        for pt in (area.get("polygon") or []):
            x, z = _finite(pt[0] if len(pt) > 0 else None), \
                _finite(pt[1] if len(pt) > 1 else None)
            if x is None or z is None:
                continue
            xs.append(x)
            zs.append(z)
    if not xs:
        return None
    return {"min_x": round(min(xs), 2), "min_z": round(min(zs), 2),
            "max_x": round(max(xs), 2), "max_z": round(max(zs), 2)}


def apply_map_layout(normalized: Dict[str, Any],
                     mode: str = "merge") -> Dict[str, int]:
    """Write a normalized layout to the world. Returns
    ``{areas, heights, positions}``.

    ``mode``:
      * ``merge`` — the new areas are painted ON TOP of what is there.
      * ``replace_terrain`` — every painted area and every height area is
        deleted first. Placements are never wiped: only the locations the
        layout names are moved, the rest stay where they are.

    ALL-OR-NOTHING as far as SQLite allows: every area, every height area and
    every location id is validated BEFORE the first write, so a draft with
    one broken polygon leaves the world untouched. Once writing starts each
    row is its own transaction (that is what ``save_area`` is), which is why
    the snapshot exists.
    """
    from app.models import heightfield, terrain
    from app.models.world import list_locations, update_location_position

    if mode not in ("merge", "replace_terrain"):
        raise ValueError(f"unknown apply mode {mode!r}")

    # 1. validate everything, writing nothing. The sanitizers mint a FRESH id
    #    per entry (the layout describes new ground, never an edit of a
    #    specific existing row), so the writes below can pass them straight on.
    ready_areas = [terrain.sanitize_area({k: v for k, v in area.items()
                                          if k != "id"})
                   for area in (normalized.get("terrain_areas") or [])]
    ready_heights = [heightfield.sanitize_height_area(
        {k: v for k, v in h.items() if k != "id"})
        for h in (normalized.get("height_areas") or [])]
    known = {loc.get("id") for loc in list_locations()}
    ready_positions: List[Dict[str, Any]] = []
    for entry in (normalized.get("locations") or []):
        loc_id = str(entry.get("id") or "").strip()
        if loc_id not in known:
            raise ValueError(f"unknown location id: {loc_id!r}")
        px, pz = _finite(entry.get("pos_x")), _finite(entry.get("pos_z"))
        if px is None or pz is None:
            raise ValueError(f"location {loc_id!r} has no usable position")
        ready_positions.append({"id": loc_id, "pos_x": px, "pos_z": pz,
                                "yaw_deg": _finite(entry.get("yaw_deg")) or 0.0})

    # 2. write.
    if mode == "replace_terrain":
        for area in terrain.list_areas():
            terrain.delete_area(area["id"])
        for area in heightfield.list_height_areas():
            heightfield.delete_height_area(area["id"])

    for area in ready_areas:
        terrain.save_area(area)
    for h in ready_heights:
        heightfield.save_height_area(h)
    for pos in ready_positions:
        update_location_position(pos["id"], pos["pos_x"], pos["pos_z"],
                                 pos["yaw_deg"])

    counts = {"areas": len(ready_areas), "heights": len(ready_heights),
              "positions": len(ready_positions)}
    logger.info("map layout applied (%s): %s", mode, counts)
    return counts


# ── Snapshots ───────────────────────────────────────────────────────────────

def _snapshot_dir():
    from app.core.paths import get_storage_dir
    path = get_storage_dir() / ".cache" / "map_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_id() -> str:
    """A sortable id from the SYSTEM clock — this is a technical stamp on a
    cache file, not a moment in the game world, so it is UTC and not
    ``GameTime``. The random tail keeps two applies in the same second
    apart."""
    from app.core.timeutils import utc_now_iso
    digits = re.sub(r"[^0-9]", "", utc_now_iso())[:14]
    return f"{digits}-{secrets.token_hex(3)}"


def map_snapshot() -> str:
    """Freeze the whole painted world into ``.cache/map_snapshots`` and return
    the snapshot id.

    Full copies, ids included: a restore has to put the very areas back, not
    look-alikes with fresh ids, or every reference anybody kept would dangle.
    Placements cover EVERY location, unplaced ones included (``pos_x: null``),
    because "this place had no position" is a state a restore must reach.
    """
    from app.core.timeutils import utc_now_iso
    from app.models import heightfield, terrain
    from app.models.world import list_locations

    positions = []
    for loc in list_locations():
        positions.append({
            "id": loc.get("id"),
            "pos_x": loc.get("pos_x"),
            "pos_z": loc.get("pos_z"),
            "yaw_deg": loc.get("yaw_deg"),
        })
    payload = {
        "created_at": utc_now_iso(),
        "terrain_areas": terrain.list_areas(),
        "height_areas": heightfield.list_height_areas(),
        "positions": positions,
    }
    snap_id = _snapshot_id()
    path = _snapshot_dir() / f"{snap_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # Keep the newest MAX_SNAPSHOTS. The id sorts chronologically, so the
    # file name is the ordering — no read needed to prune.
    files = sorted(_snapshot_dir().glob("*.json"), key=lambda p: p.name)
    for stale in files[:-MAX_SNAPSHOTS]:
        try:
            stale.unlink()
        except OSError as exc:  # noqa: BLE001 — pruning a cache never fails a write
            logger.warning("Could not prune map snapshot %s: %s", stale.name, exc)
    logger.info("map snapshot %s: %d areas, %d height areas, %d places",
                snap_id, len(payload["terrain_areas"]),
                len(payload["height_areas"]), len(positions))
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


def list_snapshots() -> List[Dict[str, Any]]:
    """All snapshots, newest first: ``{id, created_at, counts}``.

    An unreadable file is skipped rather than raised over — the list is an
    offer of undos, and one broken file must not hide the others.
    """
    out: List[Dict[str, Any]] = []
    for path in sorted(_snapshot_dir().glob("*.json"),
                       key=lambda p: p.name, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # noqa: BLE001
            logger.warning("Skipping unreadable map snapshot %s: %s",
                           path.name, exc)
            continue
        if not isinstance(payload, dict):
            continue
        out.append({
            "id": path.stem,
            "created_at": str(payload.get("created_at") or ""),
            "counts": {
                "areas": len(payload.get("terrain_areas") or []),
                "heights": len(payload.get("height_areas") or []),
                "positions": len(payload.get("positions") or []),
            },
        })
    return out


def restore_snapshot(snapshot_id: str) -> Dict[str, int]:
    """Put a snapshot back: every painted area and height area is deleted and
    the stored ones are written again UNDER THEIR ORIGINAL IDS, then every
    stored placement is set (or cleared).

    Returns ``{areas, heights, positions}``. Validated completely before the
    first delete — a corrupt snapshot must not leave a world with no ground.
    """
    from app.models import heightfield, terrain
    from app.models.world import list_locations, update_location_position

    payload = _read_snapshot(snapshot_id)
    ready_areas = [terrain.sanitize_area(a)
                   for a in (payload.get("terrain_areas") or [])]
    ready_heights = [heightfield.sanitize_height_area(h)
                     for h in (payload.get("height_areas") or [])]
    known = {loc.get("id") for loc in list_locations()}
    ready_positions = [p for p in (payload.get("positions") or [])
                       if isinstance(p, dict) and p.get("id") in known]

    for area in terrain.list_areas():
        terrain.delete_area(area["id"])
    for area in heightfield.list_height_areas():
        heightfield.delete_height_area(area["id"])
    for area in ready_areas:
        terrain.save_area(area)
    for h in ready_heights:
        heightfield.save_height_area(h)
    for pos in ready_positions:
        px, pz = _finite(pos.get("pos_x")), _finite(pos.get("pos_z"))
        yaw = _finite(pos.get("yaw_deg"))
        update_location_position(str(pos["id"]),
                                 None if px is None or pz is None else px,
                                 None if px is None or pz is None else pz,
                                 yaw)

    counts = {"areas": len(ready_areas), "heights": len(ready_heights),
              "positions": len(ready_positions)}
    logger.info("map snapshot %s restored: %s", snapshot_id, counts)
    return counts
