"""Deterministic furnishing solver (plan-room-furnish.md, stage 3).

Turns the RELATIONAL placement plan of the ``furnish_place`` LLM task into
concrete ``layout.props`` entries. Pure geometry, no I/O, no randomness —
identical input yields identical output (the repair loop depends on that).

Coordinate frame: metres, origin at the room bounding-box's north-west
corner, x → east, y → south (plan view). Compass follows the room-marker
vocabulary (0 = S, 90 = E, 180 = N, 270 = W — counter-clockwise on screen);
placement ``yaw`` turns CLOCKWISE in the top view, a prop's front points
south at yaw 0, so front compass = (−yaw) mod 360 (mirrors
``room_recipe.compose_prop_marker``).

v1 simplifications (documented in the plan): walkways are modelled as
keep-out rectangles in front of doors/passages (0.6 m deep) plus a clear
zone around ``layout.exit`` — no path finding; wall anchors snap the yaw to
the wall's compass class (hulls are drawn axis-snapped in practice); in
front of windows only pieces taller than the sill are rejected.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

Vec = Tuple[float, float]

# Hard share of the floor area the summed footprints may occupy.
BUDGET_FRACTION = 0.45
WALL_GAP_M = 0.05          # breathing room between prop back and wall
DOOR_CLEAR_M = 0.6         # keep-out depth in front of doors/passages
WINDOW_CLEAR_M = 0.6       # sill-limited zone depth in front of windows
EXIT_CLEAR_M = 0.5         # half edge of the square kept free around exit
SAMPLE_STEP_M = 0.25       # deterministic candidate stepping
REF_GAPS_M = (0.15, 0.35, 0.6)

_COMPASS_VEC: Dict[str, Vec] = {
    "n": (0.0, -1.0), "s": (0.0, 1.0), "e": (1.0, 0.0), "w": (-1.0, 0.0)}
# Wall class → yaw with the front towards the room (front = south at yaw 0).
_WALL_YAW_ROOM = {"n": 0.0, "s": 180.0, "e": 90.0, "w": 270.0}


def _compass_vec(deg: float) -> Vec:
    r = math.radians(deg % 360)
    return (math.sin(r), math.cos(r))


def _rect_corners(cx: float, cy: float, w: float, d: float,
                  yaw_deg: float) -> List[Vec]:
    """Corners of a w×d rectangle centred at (cx, cy), yaw clockwise on
    screen (y down ⇒ the standard rotation matrix already turns clockwise)."""
    r = math.radians(yaw_deg % 360)
    c, s = math.cos(r), math.sin(r)
    out = []
    for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2),
                   (w / 2, d / 2), (-w / 2, d / 2)):
        out.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return out


def _poly_area(pts: List[Vec]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _point_in_poly(pt: Vec, poly: List[Vec]) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xi:
                inside = not inside
    return inside


def _rect_in_poly(corners: List[Vec], poly: List[Vec]) -> bool:
    """Corners plus edge midpoints inside — a cheap, adequate containment
    test for convex-ish furniture rectangles in drawn hulls."""
    for i, c in enumerate(corners):
        if not _point_in_poly(c, poly):
            return False
        nxt = corners[(i + 1) % 4]
        if not _point_in_poly(((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2), poly):
            return False
    return True


def _project(corners: List[Vec], axis: Vec) -> Tuple[float, float]:
    dots = [c[0] * axis[0] + c[1] * axis[1] for c in corners]
    return min(dots), max(dots)


def _rects_overlap(a: List[Vec], b: List[Vec]) -> bool:
    """Separating-axis test for two convex quads (touching ≠ overlap)."""
    for quad in (a, b):
        for i in range(4):
            ex = quad[(i + 1) % 4][0] - quad[i][0]
            ey = quad[(i + 1) % 4][1] - quad[i][1]
            axis = (-ey, ex)
            a_lo, a_hi = _project(a, axis)
            b_lo, b_hi = _project(b, axis)
            if a_hi <= b_lo + 1e-9 or b_hi <= a_lo + 1e-9:
                return False
    return True


class _Zone:
    """Keep-out rectangle. ``max_height`` None = blocks everything (door /
    exit), a number = blocks only pieces taller than it (window sill)."""

    def __init__(self, corners: List[Vec], max_height: Optional[float]):
        self.corners = corners
        self.max_height = max_height


def _normalize_outline(outline_m: List[List[float]]) -> Tuple[List[Vec], float, float]:
    xs = [float(p[0]) for p in outline_m]
    ys = [float(p[1]) for p in outline_m]
    x0, y0 = min(xs), min(ys)
    poly = [(float(p[0]) - x0, float(p[1]) - y0) for p in outline_m]
    return poly, max(xs) - x0, max(ys) - y0


def _edge_geometry(poly: List[Vec], centroid: Vec,
                   idx: int) -> Tuple[Vec, Vec, Vec, float]:
    """Edge start, unit direction, INWARD unit normal and length."""
    a = poly[idx % len(poly)]
    b = poly[(idx + 1) % len(poly)]
    ex, ey = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ey) or 1.0
    d = (ex / length, ey / length)
    n = (d[1], -d[0])
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    to_c = (centroid[0] - mid[0], centroid[1] - mid[1])
    if n[0] * to_c[0] + n[1] * to_c[1] < 0:
        n = (-n[0], -n[1])
    return a, d, n, length


def _opening_zones(poly: List[Vec], centroid: Vec,
                   openings: List[Dict[str, Any]]) -> List[_Zone]:
    zones: List[_Zone] = []
    for op in openings or []:
        try:
            edge = int(op.get("edge") or 0)
            at = float(op.get("at") or 0.5)
            width = float(op.get("width_m") or 1.0)
        except (TypeError, ValueError):
            continue
        typ = str(op.get("type") or "door")
        a, d, n, length = _edge_geometry(poly, centroid, edge)
        p = (a[0] + d[0] * at * length, a[1] + d[1] * at * length)
        depth = DOOR_CLEAR_M if typ in ("door", "passage") else WINDOW_CLEAR_M
        hw = (width + 0.4) / 2
        centre = (p[0] + n[0] * depth / 2, p[1] + n[1] * depth / 2)
        yaw = math.degrees(math.atan2(d[1], d[0]))
        corners = _rect_corners(centre[0], centre[1], hw * 2, depth, yaw)
        if typ in ("door", "passage"):
            zones.append(_Zone(corners, None))
        elif typ == "window":
            try:
                sill = float(op.get("sill_m") or 0.9)
            except (TypeError, ValueError):
                sill = 0.9
            zones.append(_Zone(corners, sill))
    return zones


def _wall_edges(poly: List[Vec], centroid: Vec, wall: str) -> List[int]:
    """Indices of the polygon edges whose OUTWARD normal points mostly in
    the wall's compass direction."""
    want = _COMPASS_VEC[wall]
    out = []
    for i in range(len(poly)):
        _, _, inward, _ = _edge_geometry(poly, centroid, i)
        if -inward[0] * want[0] - inward[1] * want[1] > 0.5:
            out.append(i)
    return out


def _centred_offsets(usable: float, step: float) -> List[float]:
    """0.5, then symmetric pairs outward — deterministic slide order along
    a wall, expressed as fractions of the usable range."""
    if usable <= 0:
        return [0.5]
    ticks = max(1, int(usable / step))
    fracs = [0.5]
    for k in range(1, ticks + 1):
        f = k * step / usable / 2
        if 0.5 + f <= 1.0:
            fracs.append(0.5 + f)
        if 0.5 - f >= 0.0:
            fracs.append(0.5 - f)
    return fracs


def _footprint(dims: Dict[str, float], yaw: float) -> Tuple[float, float]:
    """Effective w×d of the yawed footprint (90°-class swap; diagonal yaws
    keep the conservative max on both axes)."""
    w, d = float(dims["width_m"]), float(dims["depth_m"])
    r = abs(yaw % 180)
    if 45 <= r < 135:
        return d, w
    return w, d


class _Solver:
    def __init__(self, *, outline_m, openings, existing, props,
                 exit_frac=None):
        self.poly, self.W, self.D = _normalize_outline(outline_m)
        self.area = _poly_area(self.poly)
        cx = sum(p[0] for p in self.poly) / len(self.poly)
        cy = sum(p[1] for p in self.poly) / len(self.poly)
        self.centroid = (cx, cy)
        self.zones = _opening_zones(self.poly, self.centroid, openings)
        if exit_frac:
            ex, ey = float(exit_frac[0]) * self.W, float(exit_frac[1]) * self.D
            self.zones.append(_Zone(_rect_corners(
                ex, ey, EXIT_CLEAR_M * 2, EXIT_CLEAR_M * 2, 0), None))
        self.props = props
        self.used_area = 0.0
        # Occupied footprints: (corners, prop_id, centre, yaw)
        self.occupied: List[Tuple[List[Vec], str, Vec, float]] = []
        for e in existing or []:
            dims = self._dims(str(e.get("prop_id") or ""))
            if not dims:
                continue
            at = e.get("at") or [0.5, 0.5]
            yaw = float(e.get("yaw") or 0)
            c = (float(at[0]) * self.W, float(at[1]) * self.D)
            fw, fd = _footprint(dims, yaw)
            self.occupied.append((_rect_corners(c[0], c[1], fw, fd, yaw),
                                  str(e.get("prop_id")), c, yaw))
            self.used_area += dims["width_m"] * dims["depth_m"]

    def _dims(self, prop_id: str) -> Optional[Dict[str, float]]:
        d = (self.props or {}).get(prop_id)
        if not d:
            return None
        try:
            return {"width_m": float(d["width_m"]),
                    "depth_m": float(d["depth_m"]),
                    "height_m": float(d.get("height_m") or 1.0)}
        except (KeyError, TypeError, ValueError):
            return None

    def _fits(self, corners: List[Vec], height: float) -> bool:
        if not _rect_in_poly(corners, self.poly):
            return False
        for occ, _pid, _c, _y in self.occupied:
            if _rects_overlap(corners, occ):
                return False
        for z in self.zones:
            if _rects_overlap(corners, z.corners):
                if z.max_height is None or height > z.max_height:
                    return False
        return True

    def _try(self, prop_id: str, dims: Dict[str, float], cx: float,
             cy: float, yaw: float) -> Optional[Dict[str, Any]]:
        fw, fd = _footprint(dims, yaw)
        corners = _rect_corners(cx, cy, fw, fd, yaw)
        if not self._fits(corners, dims["height_m"]):
            return None
        self.occupied.append((corners, prop_id, (cx, cy), yaw))
        self.used_area += dims["width_m"] * dims["depth_m"]
        return {"prop_id": prop_id,
                "at": [round(cx / self.W, 4), round(cy / self.D, 4)],
                "yaw": round(yaw % 360, 1)}

    # ── anchor strategies ───────────────────────────────────────────────

    def _place_wall(self, prop_id, dims, wall, facing):
        yaw = _WALL_YAW_ROOM[wall] + (180 if facing == "wall" else 0)
        for edge in _wall_edges(self.poly, self.centroid, wall):
            a, d, n, length = _edge_geometry(self.poly, self.centroid, edge)
            fw, fd = _footprint(dims, yaw)
            usable = length - fw
            for f in _centred_offsets(usable, SAMPLE_STEP_M):
                t = fw / 2 + f * max(usable, 0)
                px = a[0] + d[0] * t + n[0] * (fd / 2 + WALL_GAP_M)
                py = a[1] + d[1] * t + n[1] * (fd / 2 + WALL_GAP_M)
                hit = self._try(prop_id, dims, px, py, yaw)
                if hit:
                    return hit
        return None

    def _place_corner(self, prop_id, dims, corner, facing):
        # corner_ne → walls n + e; yaw of whichever wall lets the front
        # point closer to the room centre wins (deterministic order n/s > e/w).
        ns, ew = corner[0], corner[1]
        for wall in (ns, ew):
            yaw = _WALL_YAW_ROOM[wall] + (180 if facing == "wall" else 0)
            fw, fd = _footprint(dims, yaw)
            cx = fw / 2 + WALL_GAP_M if ew == "w" else self.W - fw / 2 - WALL_GAP_M
            cy = fd / 2 + WALL_GAP_M if ns == "n" else self.D - fd / 2 - WALL_GAP_M
            # Slide away from the corner along the anchor wall when blocked.
            along = _COMPASS_VEC["s" if wall in ("e", "w") else "e"]
            sign = 1.0 if (wall in ("n", "s") and ew == "w") or wall in ("e", "w") and ns == "n" else -1.0
            steps = int(max(self.W, self.D) / SAMPLE_STEP_M)
            for k in range(steps + 1):
                px = cx + along[0] * sign * k * SAMPLE_STEP_M
                py = cy + along[1] * sign * k * SAMPLE_STEP_M
                hit = self._try(prop_id, dims, px, py, yaw)
                if hit:
                    return hit
        return None

    def _place_center(self, prop_id, dims, facing):
        yaw = 0.0
        cx, cy = self.W / 2, self.D / 2
        rings = int(max(self.W, self.D) / (2 * SAMPLE_STEP_M)) + 1
        for ring in range(rings):
            r = ring * SAMPLE_STEP_M
            pts = [(cx, cy)] if ring == 0 else [
                (cx + r * math.cos(a), cy + r * math.sin(a))
                for a in [i * math.pi / 4 for i in range(8)]]
            for px, py in pts:
                hit = self._try(prop_id, dims, px, py, yaw)
                if hit:
                    return hit
        return None

    def _find_ref(self, ref: str):
        for corners, pid, centre, yaw in reversed(self.occupied):
            if pid == ref:
                return centre, yaw, corners
        return None

    def _place_relative(self, prop_id, dims, anchor, ref, facing):
        found = self._find_ref(ref or "")
        if not found:
            return None, f"reference '{ref}' is not placed"
        (rx, ry), ryaw, rcorners = found
        front = _compass_vec((-ryaw) % 360)
        side = (-front[1], front[0])
        ref_half = max(abs((_project(rcorners, front))[1] - (rx * front[0] + ry * front[1])),
                       abs((_project(rcorners, side))[1] - (rx * side[0] + ry * side[1])))
        my_half = max(dims["width_m"], dims["depth_m"]) / 2
        dirs = ([front, side, (-side[0], -side[1]), (-front[0], -front[1])]
                if anchor == "in_front_of"
                else [side, (-side[0], -side[1]), front, (-front[0], -front[1])])
        for d in dirs:
            for gap in REF_GAPS_M:
                px = rx + d[0] * (ref_half + my_half + gap)
                py = ry + d[1] * (ref_half + my_half + gap)
                if facing == "ref":
                    back = math.degrees(math.atan2(rx - px, ry - py))
                    yaw = (-back) % 360  # front compass = direction to ref
                else:
                    yaw = ryaw if facing == "room" else (ryaw + 180) % 360
                hit = self._try(prop_id, dims, px, py, yaw)
                if hit:
                    return hit, ""
        return None, "no free spot near the reference"


_ANCHOR_ORDER = {"wall_n": 0, "wall_e": 0, "wall_s": 0, "wall_w": 0,
                 "corner_ne": 0, "corner_nw": 0, "corner_se": 0,
                 "corner_sw": 0, "center": 1, "in_front_of": 2, "beside": 2}


def solve(*, outline_m: List[List[float]],
          openings: List[Dict[str, Any]],
          existing: List[Dict[str, Any]],
          plan: List[Dict[str, Any]],
          props: Dict[str, Dict[str, Any]],
          exit_frac: Optional[List[float]] = None) -> Dict[str, Any]:
    """Solve the relational plan. Returns ``{"placed": [layout.props
    entries], "unplaced": [{"name", "reason"}]}`` — reasons are short
    English strings that feed the repair template and the review UI."""
    if not outline_m or len(outline_m) < 3:
        return {"placed": [], "unplaced": [
            {"name": str(it.get("prop") or "?"), "reason": "invalid room polygon"}
            for it in plan or []]}
    s = _Solver(outline_m=outline_m, openings=openings, existing=existing,
                props=props, exit_frac=exit_frac)
    if s.area <= 0.01 or s.W <= 0.01 or s.D <= 0.01:
        return {"placed": [], "unplaced": [
            {"name": str(it.get("prop") or "?"), "reason": "invalid room polygon"}
            for it in plan or []]}

    ordered = sorted(
        [it for it in plan or [] if isinstance(it, dict)],
        key=lambda it: _ANCHOR_ORDER.get(str(it.get("anchor") or ""), 3))
    placed: List[Dict[str, Any]] = []
    unplaced: List[Dict[str, str]] = []
    budget = s.area * BUDGET_FRACTION

    for item in ordered:
        prop_id = str(item.get("prop") or "")
        anchor = str(item.get("anchor") or "center")
        facing = str(item.get("facing") or "room")
        ref = item.get("ref")
        try:
            count = max(1, min(12, int(item.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1
        dims = s._dims(prop_id)
        if not dims:
            unplaced.append({"name": prop_id, "reason": "unknown prop"})
            continue
        piece_area = dims["width_m"] * dims["depth_m"]
        for _ in range(count):
            if s.used_area + piece_area > budget:
                unplaced.append({"name": prop_id,
                                 "reason": "area budget exhausted"})
                continue
            reason = "no free spot"
            hit = None
            if anchor in ("wall_n", "wall_e", "wall_s", "wall_w"):
                hit = s._place_wall(prop_id, dims, anchor[-1], facing)
            elif anchor.startswith("corner_"):
                hit = s._place_corner(prop_id, dims, anchor[-2:], facing)
            elif anchor == "center":
                hit = s._place_center(prop_id, dims, facing)
            elif anchor in ("in_front_of", "beside"):
                hit, reason = s._place_relative(
                    prop_id, dims, anchor, str(ref or ""), facing)
                reason = reason or "no free spot"
            else:
                reason = f"unknown anchor '{anchor}'"
            if hit:
                placed.append(hit)
            else:
                unplaced.append({"name": prop_id, "reason": reason})
    return {"placed": placed, "unplaced": unplaced}
