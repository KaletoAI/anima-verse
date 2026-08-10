"""Room recipe (plan-room-props.md) — ONE endpoint for a furnished room.

The raw data already flows to the client through the location payload
(``rooms[].layout`` with outline/surfaces/openings/props); the recipe adds
the COMPOSED conveniences so the client renders without re-deriving them:

- ``outline`` in ABSOLUTE plate fractions (the drawn hull or the implicit
  rectangle — no bbox-local mechanics on the client side),
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

Coordinate frames: XZ positions are fractions of the location's reference
square (like ``layout.x/y`` and ``map3d.outline``); every length that ends
in ``_m`` is REAL metres — and since E4 that is already a world metre, because
the reference square IS the location's footprint (``extent_m = plan_width_m``,
k = 1).
Yaw/facing are degrees; the compass vocabulary of the room markers applies
(0 = south, 90 = east, …), composed prop facing = ``facing − placement.yaw``
(the plan yaw turns clockwise in the top view, the compass counts the other
way around).
"""

import hashlib
import json
import math
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.scatter_curves import scatter as _scatter_props
from app.core.scatter_curves import tessellate
from app.core.scatter_curves import variant_mix

logger = get_logger(__name__)

_UNIT_SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def _r(v: float, nd: int = 4) -> float:
    out = round(float(v), nd)
    return out if out != 0 else 0.0  # never -0.0 in payloads


def _rot_matrix(rotation: Any) -> List[List[float]]:
    """Rx·Ry·Rz (three.js 'XYZ' Euler, degrees) — the SAME convention as
    ``props.oriented_dims`` / the client viewers; keep them in lockstep."""
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
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]


def _apply(m: List[List[float]], p: List[float]) -> List[float]:
    return [m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] for r in range(3)]


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
# Change both or neither. All coordinates are absolute plate fractions; the
# thresholds are metres, converted with the location's plan width. Without a
# plan width (unanchored legacy data) there is no real size at all — assume
# a location 8 real metres across so the tolerances stay sane.
SHARE_TOL_M = 0.15
MIN_SHARE_M = 0.8
_UNANCHORED_PLAN_WIDTH_M = 8.0
# Scatter keep-outs (plan-area-detail-scenes.md): clearance in REAL metres in
# front of an opening (beyond its half width) and around markers /
# model-less manual props. Axis-aligned squares on purpose — § B5a wants the
# arithmetic hand-checkable.
SCATTER_OPENING_CLEAR_M = 0.6
SCATTER_POINT_CLEAR_M = 0.5
# Opening types a character can walk through (a window is not a way out).
_WALKABLE_TYPES = ("door", "passage")


def _layout_rect(lay: Any) -> Optional[tuple]:
    """(x, y, w, d) of a layout, or None when it is not a usable rectangle."""
    if not isinstance(lay, dict):
        return None
    try:
        return (float(lay["x"]), float(lay["y"]),
                float(lay["w"]), float(lay["d"]))
    except (KeyError, TypeError, ValueError):
        return None


def _abs_outline(lay: Dict[str, Any]) -> List[List[float]]:
    """A layout's hull in ABSOLUTE plate fractions (mirrors
    ``planGeometry.absOutline``); [] when the layout has no usable rect."""
    rect = _layout_rect(lay)
    if not rect:
        return []
    x, y, w, d = rect
    pts = lay.get("outline") or _UNIT_SQUARE
    if not isinstance(pts, list) or len(pts) < 3:
        pts = _UNIT_SQUARE
    try:
        return [[x + float(u) * w, y + float(v) * d] for u, v in pts]
    except (TypeError, ValueError):
        return []


def _abs_shape(lay: Dict[str, Any]) -> List[List[float]]:
    """Like ``_abs_outline`` but with curved edges TESSELLATED — the shape a
    renderer actually sees. Beziers are affine-invariant, so tessellating in
    the bbox-local frame and mapping to plate fractions afterwards is exact."""
    rect = _layout_rect(lay)
    if not rect:
        return []
    x, y, w, d = rect
    pts = lay.get("outline") or _UNIT_SQUARE
    if not isinstance(pts, list) or len(pts) < 3:
        pts = _UNIT_SQUARE
    tess, _ = tessellate(pts, lay.get("outline_curves"))
    try:
        return [[x + float(u) * w, y + float(v) * d] for u, v in tess]
    except (TypeError, ValueError):
        return []


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


def _mirrored_openings(lay: Dict[str, Any], siblings: List[Dict[str, Any]],
                       plan_width_m: float) -> List[Dict[str, Any]]:
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
    planw = plan_width_m if plan_width_m > 0 else _UNANCHORED_PLAN_WIDTH_M
    tol = SHARE_TOL_M / planw
    min_overlap = MIN_SHARE_M / planw
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
    fractions of the raw box. The chain mirrors the mesh placement:
    orientation fix (translation-invariant — the raw box is taken as
    [0, size]) → uniform real-size scale = max(dims) / largest oriented
    extent → anchor at the oriented box's bottom centre → placement yaw.
    """
    m = _rot_matrix(rotation)
    size = [abs(float(bbox[i])) for i in range(3)]
    # Oriented AABB of the fixed raw box (8 corners of [0, size]).
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                q = _apply(m, [i * size[0], j * size[1], k * size[2]])
                for a in range(3):
                    lo[a] = min(lo[a], q[a])
                    hi[a] = max(hi[a], q[a])
    extents = [hi[a] - lo[a] for a in range(3)]
    s = (max(dims) or 1.0) / (max(extents) or 1.0)
    p = _apply(m, [frac[0] * size[0], frac[1] * size[1], frac[2] * size[2]])
    # Anchor: oriented-box bottom centre = the placement point (exactly how
    # the mesh itself is seated).
    pre = [s * (p[0] - (lo[0] + hi[0]) / 2),
           s * (p[1] - lo[1]),
           s * (p[2] - (lo[2] + hi[2]) / 2)]
    yaw = math.radians(float(placement_yaw or 0))
    dx = pre[0] * math.cos(yaw) - pre[2] * math.sin(yaw)
    dz = pre[0] * math.sin(yaw) + pre[2] * math.cos(yaw)
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
    eff_facing = 0.0 if facing is None else float(facing)
    out["facing"] = _r((eff_facing - float(placement_yaw or 0)) % 360, 1)
    return out


def compose_recipe(room: Dict[str, Any],
                   siblings: Any = (),
                   plan_width_m: float = 0.0,
                   variant_seed: int = 0) -> Optional[Dict[str, Any]]:
    """The full recipe of ONE room, or None when it has no layout.

    ``siblings`` are the OTHER rooms of the same location; those on the same
    level contribute their openings on shared walls (see
    ``_mirrored_openings``).
    ``plan_width_m`` is the location's scale anchor — only the tolerances of
    the shared-wall test use it; 0 means "assume the 8 m reference plate",
    the same fallback the editor uses.
    ``variant_seed`` is the one number a copy placed on the map owns; it is
    mixed into every stored scatter seed so two copies of one template stop
    looking identical. 0 means "not a copy" and leaves every seed untouched.
    """
    lay = room.get("layout")
    rect = _layout_rect(lay)
    if not rect:
        return None
    x, y, w, d = rect

    pts = lay.get("outline") or _UNIT_SQUARE
    # Curved edges (plan-area-detail-scenes.md) are tessellated HERE — the
    # payload outline is always a plain polygon, downstream (walls, plates,
    # clips, both renderers) never learns curves existed. ``edge_map`` shifts
    # opening edge indices past the inserted points; on a curve-free outline
    # it is the identity.
    tess_pts, edge_map = tessellate(pts, lay.get("outline_curves"))
    outline = [[_r(x + float(u) * w), _r(y + float(v) * d)] for u, v in tess_pts]

    own_id = str(room.get("id") or "")
    others = [s for s in (siblings or [])
              if isinstance(s, dict) and str(s.get("id") or "") != own_id]
    openings = [_normalize_opening(op) for op in (lay.get("openings") or [])
                if isinstance(op, dict)]
    openings.extend(_mirrored_openings(lay, others, plan_width_m))
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

    from app.core import props as prop_store
    placements: List[Dict[str, Any]] = []
    prop_markers: List[Dict[str, Any]] = []
    for placement in (lay.get("props") or []):
        if not isinstance(placement, dict):
            continue
        pid = str(placement.get("prop_id") or "")
        at = placement.get("at") or [0.5, 0.5]
        yaw = float(placement.get("yaw") or 0)
        off_y = float(placement.get("offset_y") or 0)
        entry: Dict[str, Any] = {
            "prop_id": pid,
            "at": [_r(x + float(at[0]) * w), _r(y + float(at[1]) * d)],
            "yaw": _r(yaw, 1),
            "offset_y": _r(off_y, 3),
        }
        prop = prop_store.get_prop(pid)
        if not prop:
            # Dangling id — the placement stays visible as a placeholder
            # (world data is DB, props are files; no referential integrity
            # by design).
            entry["missing"] = True
            placements.append(entry)
            continue
        entry["dims"] = {"width_m": prop["width_m"],
                         "depth_m": prop["depth_m"],
                         "height_m": prop["height_m"]}
        entry["has_model"] = bool(prop.get("has_model"))
        if prop.get("has_model"):
            # Which resolution tiers the prop has, plus the change key of its
            # mesh SELECTION: the scene payload turns the tiers into
            # ``variants`` URLs, and the signature below moves when a prop
            # gets a new mesh (the URL alone never changes).
            entry["model_tiers"] = prop.get("model_tiers") or []
            entry["model_sig"] = prop.get("model_signature") or ""
        idx = len(placements)
        placements.append(entry)
        bbox = prop.get("bbox")
        if not bbox:
            continue  # no measurable mesh — markers stay object data only
        dims = [prop["width_m"], prop["depth_m"], prop["height_m"]]
        for marker in (prop.get("markers") or []):
            composed = compose_prop_marker(
                bbox=bbox, rotation=prop.get("rotation"), dims=dims,
                frac=[float(v) for v in marker.get("at") or [0.5, 0, 0.5]],
                facing=marker.get("facing"), placement_yaw=yaw,
                placement_offset_y=off_y)
            composed["animation"] = marker.get("animation") or ""
            composed["placement"] = idx
            prop_markers.append(composed)

    # Prop scatter (plan-area-detail-scenes.md, 2026-08-02 redesign): a
    # PLACEMENT property, not a room list — a placement with
    # ``scatter_count`` throws that many copies of its prop over the room
    # area from its own ``scatter_seed``, while the placement itself stays
    # as the manually positioned anchor. Positions are computed at COMPOSE
    # time and never stored, so every renderer derives the same forest and
    # the signature below moves with seed/count/spacing (the copies land in
    # the hashed payload). Scatter runs in REAL metres; plate fractions ×
    # plan width convert both ways. Copies are appended AFTER all manual
    # entries so ``prop_markers[].placement`` indices never move, and they
    # get NO prop markers (no sit spots on twenty pines). Keep-outs are the
    # GEOMETRIC zones only (sibling hulls, openings, markers) —
    # ``scatter_spacing_m`` alone rules the density (0 = copies may
    # overlap; the old footprint minimum kept every tree a crown apart).
    # The openings ARE the doorways (plan-betreten-und-tueren.md § 4.1), so
    # their keep-outs already free every threshold.
    scatter_sources = [p for p in (lay.get("props") or [])
                       if isinstance(p, dict) and p.get("scatter_count")]
    if scatter_sources:
        planw = plan_width_m if plan_width_m > 0 else _UNANCHORED_PLAN_WIDTH_M
        level = int(lay.get("level") or 0)
        outline_m = [[p[0] * planw, p[1] * planw] for p in outline]
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
                keepouts.append([[p[0] * planw, p[1] * planw] for p in shape])

        def _square(cx: float, cy: float, half: float) -> List[List[float]]:
            return [[cx - half, cy - half], [cx + half, cy - half],
                    [cx + half, cy + half], [cx - half, cy + half]]

        for op in openings:
            try:
                e = int(op.get("edge") or 0) % len(outline)
                at = float(op.get("at") or 0)
                half = float(op.get("width_m") or 0) / 2.0 \
                    + SCATTER_OPENING_CLEAR_M
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            px, py = _point_on_edge(outline, e, at)
            keepouts.append(_square(px * planw, py * planw, half))
        for marker in (lay.get("markers") or []):
            mat = marker.get("at") if isinstance(marker, dict) else None
            if isinstance(mat, (list, tuple)) and len(mat) == 2:
                keepouts.append(_square((x + float(mat[0]) * w) * planw,
                                        (y + float(mat[1]) * d) * planw,
                                        SCATTER_POINT_CLEAR_M))

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
            for placed in _scatter_props(seed, count, outline_m, keepouts,
                                         spacing):
                entry: Dict[str, Any] = {
                    "prop_id": pid,
                    "at": [_r(placed["at"][0] / planw),
                           _r(placed["at"][1] / planw)],
                    "yaw": _r(placed["yaw"], 1),
                    "offset_y": 0.0,
                    "scattered": True,
                }
                if not prop:
                    entry["missing"] = True
                else:
                    entry["dims"] = {"width_m": prop["width_m"],
                                     "depth_m": prop["depth_m"],
                                     "height_m": prop["height_m"]}
                    entry["has_model"] = bool(prop.get("has_model"))
                    if prop.get("has_model"):
                        entry["model_tiers"] = prop.get("model_tiers") or []
                        entry["model_sig"] = prop.get("model_signature") or ""
                placements.append(entry)

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
    # Relief opt-out (§ B contract v5.2 Nr. 14): the room keeps a level floor
    # even under a terrain relief. Read from the layout into the recipe for
    # the SAME reason as clip_model — only payload fields reach the signature
    # below, so ticking "keep flat" has to make the client re-fetch.
    if lay.get("relief_flat"):
        payload["relief_flat"] = True
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
    # same signature reasoning. Only meaningful where the room cuts a hole
    # into a location model: the terrain there is not at storey level.
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
