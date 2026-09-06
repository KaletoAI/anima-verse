"""Deterministic furnishing solver v2 (plan-furnish-v2.md § 2 B1/B2/B4/B5,
§ 2b B10/B11/B16/B17).

Turns the RELATIONAL placement plan of the ``furnish_place`` LLM task into
concrete ``layout.props`` entries. Pure geometry, no I/O, no randomness —
identical input yields identical output (the repair loop depends on that).
The plan-view primitives live in :mod:`app.core.furnish_geometry`; this module
is the three passes, the anchors and the budgets.

THREE PASSES (the Holodeck order — floor objects, then wall/ceiling objects on
top of them, then the small stuff on their surfaces). Each pass may reference
what the earlier ones placed:

* **A — floor** (``mount floor``): ``wall_n|e|s|w``, ``corner_*``, ``center``
  (as a walkway GRID, not a ring around the middle), ``in_front_of``,
  ``beside``, ``around`` (seats by side capacity), ``under`` (underlays).
* **B — wall + ceiling**: ``wall_n|e|s|w``, ``wall_above <ref>``,
  ``at_opening <window>``; ceiling ``above <ref>`` and ``center``. Wall pieces
  always look into the room and carry a base height (``base_m``, clamped).
* **C — surface** (``mount surface``): ``on <ref>`` only. Output is a CHILD
  FRAME entry (``on`` + relative ``at``), composed by
  ``room_recipe.compose_on_chain``; the height comes from
  ``props.stack_on_support`` — imported, never re-typed.

OCCUPANCY IS 3D. Every occupied thing is ``(quad, y0, y1)``; two things collide
only when their quads overlap AND their height intervals overlap (touching is
not overlapping in either test). That is what lets a picture hang over a sofa
and a pendant lamp hover over a table. ``y0`` is the piece's true base,
``ground_offset_m + offset_y`` — which for the usual ``ground_offset_m 0`` is
the plan's ``y0 = offset_y``.

FRAME AND TURN — see :mod:`app.core.furnish_geometry`. In one line: yaw turns
like the renderer (``R_y(+yaw)``) and a placed prop's front compass is
``(0 + yaw) mod 360``, so a yaw-90 desk faces EAST. v1 used the transpose and
is corrected here, wall-yaw table included.

Still simplified on purpose: walkways are keep-out rectangles in front of the
openings, not a path search; a room's outline is its only boundary. The openings
ARE the doorways (plan-betreten-und-tueren.md § 4.1).
"""

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core import furnish_geometry as fg
from app.core.props import stack_on_support

Vec = Tuple[float, float]

# ── Budgets and clearances ──────────────────────────────────────────────
BUDGET_FRACTION = 0.45          # share of the floor area furniture may cover
WALL_BUDGET_FRACTION = 0.6      # share of a wall's free length wall pieces may use
SURFACE_BUDGET_FRACTION = 0.4   # share of a support's top its children may cover
FLOOR_GAP_M = 0.05              # breathing room between a floor piece and the wall
WALL_GAP_M = 0.02               # a wall piece hangs closer than a cupboard stands
WALL_SERIES_GAP_M = 0.3         # minimum gap between two pieces on the same wall
DOOR_CLEAR_M = 0.6              # minimum keep-out depth in front of a doorway
SAMPLE_STEP_M = 0.25            # deterministic candidate stepping along a wall
SURFACE_STEP_M = 0.15           # raster step on a support's top
WALKWAY_M = 0.9                 # gangway added to a ``center`` grid cell
REF_GAPS_M = (0.15, 0.35, 0.6)  # gaps tried next to a reference piece
SEAT_GAP_M = 0.05               # gap between a seat and the table it belongs to
SEAT_PITCH_M = 0.1              # gap between two neighbouring seats
ROW_PITCH_M = 0.1               # gap between two pieces of an ``in_front_of`` row
UNDERLAY_MAX_H = 0.05           # a floor piece this flat is a rug, not an obstacle
SUPPORT_MIN_H = 0.2             # nothing is placed on top of something this low
MAX_CHAIN_DEPTH = 3             # a child of a child of a child, no deeper
CEILING_MIN_BASE_M = 1.9        # a hanging piece never reaches into head height
WALL_BASE_MIN_M = 0.3           # lowest base a wall piece may be clamped to
WALL_BASE_CENTRE_M = 1.5        # default: a wall piece is centred at eye height
WALL_ABOVE_GAP_M = 0.2          # a picture hangs this far above its sofa
WALL_ABOVE_TOL_M = 0.15         # how close a support's back must be to a wall
OPENING_PIECE_GAP_M = 0.15      # a curtain rail rides this far above the window
MAX_COUNT = 64                  # a plan may ask for dozens of mugs, not hundreds

_MOUNTS = ("floor", "wall", "ceiling", "surface")
_PASS_OF_MOUNT = {"floor": "floor", "wall": "wall", "ceiling": "ceiling",
                  "surface": "surface"}
_WALL_ANCHORS = ("wall_n", "wall_e", "wall_s", "wall_w")
_CORNER_ANCHORS = ("corner_ne", "corner_nw", "corner_se", "corner_sw")
_FLOOR_ANCHORS = set(_WALL_ANCHORS) | set(_CORNER_ANCHORS) | {
    "center", "in_front_of", "beside", "around", "under"}
_WALL_PASS_ANCHORS = set(_WALL_ANCHORS) | {"wall_above", "at_opening"}
_CEILING_PASS_ANCHORS = {"above", "center"}
_SURFACE_PASS_ANCHORS = {"on"}

# Within a pass the anchors run in this order, so an anchor that needs a
# reference always finds it. Ties keep the plan's own order (stable sort).
_FLOOR_RANK = {a: 0 for a in _WALL_ANCHORS}
_FLOOR_RANK.update({a: 0 for a in _CORNER_ANCHORS})
_FLOOR_RANK.update({"center": 1, "in_front_of": 2, "beside": 2, "around": 2,
                    "under": 3})
_WALL_RANK = {"at_opening": 0, "wall_above": 1}
_WALL_RANK.update({a: 2 for a in _WALL_ANCHORS})

_NEXT_WALL = {"n": "e", "e": "s", "s": "w", "w": "n"}


def _other_wall(wall: str) -> str:
    """A concrete alternative to name in a repair text (constraint 5)."""
    return _NEXT_WALL.get(wall, "n")


class _Piece:
    """One occupied thing: a quad, a height interval and who it belongs to."""

    __slots__ = ("prop_id", "place_id", "at", "yaw", "w", "d", "h", "mount",
                 "corners", "y0", "y1", "on", "depth", "order",
                 "ground_offset_m")

    def __init__(self, *, prop_id: str, place_id: str, at: Vec, yaw: float,
                 w: float, d: float, h: float, mount: str, y0: float,
                 ground_offset_m: float, on: str, depth: int,
                 order: int) -> None:
        self.prop_id = prop_id
        self.place_id = place_id
        self.at = at
        self.yaw = yaw % 360.0
        self.w = w
        self.d = d
        self.h = h
        self.mount = mount
        self.y0 = y0
        self.y1 = y0 + h
        self.on = on
        self.depth = depth
        self.order = order
        self.ground_offset_m = ground_offset_m
        self.corners = fg.rect_corners(at[0], at[1], w, d, self.yaw)

    @property
    def top(self) -> float:
        return self.y1

    def box(self) -> Dict[str, Any]:
        """The vertical facts ``props.stack_on_support`` reads."""
        return {"ground_offset_m": self.ground_offset_m,
                "offset_y": self.y0 - self.ground_offset_m,
                "height_m": self.h}


class _Item:
    """One normalized plan entry."""

    __slots__ = ("prop", "count", "anchor", "ref", "facing", "base_m", "mount",
                 "w", "d", "h", "ground_offset_m", "variants", "order")

    def __init__(self, **kw: Any) -> None:
        for key in self.__slots__:
            setattr(self, key, kw.get(key))

    @property
    def is_underlay(self) -> bool:
        return self.mount == "floor" and self.h <= UNDERLAY_MAX_H

    @property
    def area(self) -> float:
        return self.w * self.d


class _Solver:
    def __init__(self, *, outline_m: Sequence[Sequence[float]],
                 openings: Optional[Sequence[Dict[str, Any]]],
                 existing: Optional[Sequence[Dict[str, Any]]],
                 props: Optional[Dict[str, Dict[str, Any]]],
                 storey_height_m: float) -> None:
        self.poly, self.W, self.D = fg.normalize_outline(outline_m)
        self.area = fg.poly_area(self.poly)
        self.centroid = (sum(p[0] for p in self.poly) / len(self.poly),
                         sum(p[1] for p in self.poly) / len(self.poly))
        self.storey = max(2.0, float(storey_height_m or 3.0))
        self.props = props or {}
        self.openings = [op for op in (openings or []) if isinstance(op, dict)]
        self.zones = fg.opening_zones(self.poly, self.centroid, self.openings,
                                      DOOR_CLEAR_M, DOOR_CLEAR_M)
        self.doors = self._door_points()
        self.wall_budget = self._wall_budgets()
        self.wall_used: Dict[str, float] = {"n": 0.0, "e": 0.0, "s": 0.0,
                                            "w": 0.0}
        # Floor pieces sitting AT a wall class, stored as the quad GROWN by
        # 0.15 m to each side along the wall — candidate and neighbour each
        # bring half, so two pieces on one wall keep 0.3 m apart (B4).
        self.wall_series: Dict[str, List[List[Vec]]] = {"n": [], "e": [],
                                                        "s": [], "w": []}
        self.occupied: List[_Piece] = []
        self.instances: Dict[str, List[_Piece]] = {}
        self.by_id: Dict[str, _Piece] = {}
        self.ids: set = set()
        self.counts: Dict[str, int] = {}
        self.dependants: Dict[str, int] = {}
        self.surface_used: Dict[str, float] = {}
        self.taken_openings: set = set()
        self.used_area = 0.0
        self.budget = self.area * BUDGET_FRACTION
        self._order = 0
        self._load_existing(existing or [])

    # ── setup ───────────────────────────────────────────────────────────

    def _door_points(self) -> List[Vec]:
        out: List[Vec] = []
        for op in self.openings:
            if str(op.get("type") or "door") not in ("door", "passage"):
                continue
            found = fg.opening_point(self.poly, self.centroid, op)
            if found:
                out.append(found[0])
        return out

    def _wall_budgets(self) -> Dict[str, float]:
        """Per wall class: 60 % of (its edge length − the openings in it)."""
        out: Dict[str, float] = {}
        for wall in ("n", "e", "s", "w"):
            edges = fg.wall_edges(self.poly, self.centroid, wall)
            length = sum(fg.edge_geometry(self.poly, self.centroid, i)[3]
                         for i in edges)
            for op in self.openings:
                try:
                    idx = int(op.get("edge") or 0) % max(1, len(self.poly))
                    width = float(op.get("width_m") or 0.0)
                except (TypeError, ValueError):
                    continue
                if idx in edges:
                    length -= width
            out[wall] = max(0.0, length) * WALL_BUDGET_FRACTION
        return out

    def _load_existing(self, existing: Sequence[Dict[str, Any]]) -> None:
        """Everything already standing, ALREADY COMPOSED by the caller — the
        solver only needs their boxes and their identity as possible supports.
        A dangling prop id (not in the library handed in) is skipped: without
        dims there is no box to avoid."""
        for i, e in enumerate(existing):
            if not isinstance(e, dict):
                continue
            prop_id = str(e.get("prop_id") or "")
            facts = self._prop(prop_id)
            if not facts:
                continue
            at = e.get("at") or [self.W / 2, self.D / 2]
            try:
                pos = (float(at[0]), float(at[1]))
                yaw = float(e.get("yaw") or 0.0)
                offset_y = float(e.get("offset_y") or 0.0)
            except (TypeError, ValueError, IndexError):
                continue
            place_id = str(e.get("id") or "") or f"existing-{i}"
            on = str(e.get("on") or "")
            piece = self._add(prop_id=prop_id, place_id=place_id, at=pos,
                              yaw=yaw, facts=facts,
                              y0=float(facts["ground_offset_m"]) + offset_y,
                              on=on,
                              # A composed child names its support but not the
                              # depth it sits at; one level is the safe read.
                              depth=1 if on else 0,
                              occupy=not (facts["mount"] == "floor"
                                          and facts["height_m"] <= UNDERLAY_MAX_H))
            if piece.mount == "floor" and piece.h > UNDERLAY_MAX_H:
                self.used_area += facts["width_m"] * facts["depth_m"]
            if on:
                self.surface_used[on] = (self.surface_used.get(on, 0.0)
                                         + facts["width_m"] * facts["depth_m"])

    def _prop(self, prop_id: str) -> Optional[Dict[str, Any]]:
        """The library record the solver needs, defaults filled in: absent or
        unknown ``mount`` is ``floor``, ``ground_offset_m`` 0, ``variants`` 1."""
        raw = (self.props or {}).get(prop_id)
        if not raw:
            return None
        try:
            width = float(raw["width_m"])
            depth = float(raw["depth_m"])
            height = float(raw.get("height_m") or 1.0)
        except (KeyError, TypeError, ValueError):
            return None
        if width <= 0 or depth <= 0:
            return None
        mount = str(raw.get("mount") or "floor").strip().lower()
        if mount not in _MOUNTS:
            mount = "floor"
        try:
            ground = float(raw.get("ground_offset_m") or 0.0)
        except (TypeError, ValueError):
            ground = 0.0
        try:
            variants = max(1, int(raw.get("variants") or 1))
        except (TypeError, ValueError):
            variants = 1
        return {"width_m": width, "depth_m": depth,
                "height_m": max(0.0, height), "mount": mount,
                "ground_offset_m": ground, "variants": variants}

    # ── registry ────────────────────────────────────────────────────────

    def _add(self, *, prop_id: str, place_id: str, at: Vec, yaw: float,
             facts: Dict[str, Any], y0: float, on: str, depth: int,
             occupy: bool) -> _Piece:
        self._order += 1
        piece = _Piece(prop_id=prop_id, place_id=place_id, at=at, yaw=yaw,
                       w=facts["width_m"], d=facts["depth_m"],
                       h=facts["height_m"], mount=facts["mount"], y0=y0,
                       ground_offset_m=facts["ground_offset_m"], on=on,
                       depth=depth, order=self._order)
        self.instances.setdefault(prop_id, []).append(piece)
        self.by_id[place_id] = piece
        self.ids.add(place_id)
        if occupy:
            self.occupied.append(piece)
        return piece

    def _mint_id(self, prop_id: str) -> Tuple[str, int]:
        """``md5(prop:ordinal)[:8]``, ordinal = the running number of that prop
        id within this solve; a collision with an id already in the room bumps
        the ordinal."""
        n = self.counts.get(prop_id, 0)
        while True:
            new = hashlib.md5(f"{prop_id}:{n}".encode()).hexdigest()[:8]
            if new not in self.ids:
                self.counts[prop_id] = n + 1
                return new, n
            n += 1

    # ── tests ───────────────────────────────────────────────────────────

    def _fits(self, corners: Sequence[Vec], y0: float, y1: float, *,
              ignore_opening: Optional[int] = None) -> bool:
        if not fg.rect_in_poly(corners, self.poly):
            return False
        for piece in self.occupied:
            if (fg.spans_overlap(y0, y1, piece.y0, piece.y1)
                    and fg.rects_overlap(corners, piece.corners)):
                return False
        for zone in self.zones:
            if ignore_opening is not None and zone.opening == ignore_opening:
                continue
            if zone.blocks(corners, y0, y1):
                return False
        return True

    # ── references ──────────────────────────────────────────────────────

    def _resolve(self, ref: str) -> List[_Piece]:
        """A ``ref`` is a placement id or a prop id; a prop id stands for ALL
        its instances, in placement order (existing first, then this solve)."""
        ref = str(ref or "")
        if not ref:
            return []
        piece = self.by_id.get(ref)
        if piece is not None:
            return [piece]
        return list(self.instances.get(ref) or [])

    def _pick(self, pieces: List[_Piece]) -> _Piece:
        """The instance with the fewest dependants so far, ties → the first."""
        chosen = min(pieces, key=lambda p: (self.dependants.get(p.place_id, 0),
                                            p.order))
        self.dependants[chosen.place_id] = (
            self.dependants.get(chosen.place_id, 0) + 1)
        return chosen

    # ── facing ──────────────────────────────────────────────────────────

    def _door_yaw(self, at: Vec) -> float:
        """Front towards the nearest door/passage midpoint; no door → south."""
        if not self.doors:
            return 0.0
        best = min(self.doors,
                   key=lambda p: (math.hypot(p[0] - at[0], p[1] - at[1]),
                                  p[1], p[0]))
        vec = (best[0] - at[0], best[1] - at[1])
        if abs(vec[0]) < 1e-9 and abs(vec[1]) < 1e-9:
            return 0.0
        return fg.compass_of(vec)

    def _relative_yaw(self, facing: str, default: str, *, ref_yaw: float,
                      toward_yaw: float) -> float:
        """Yaw for a piece placed next to a reference. ``ref`` = look at the
        reference, ``room`` = the reference's own heading, ``wall`` = away from
        it, a compass letter = that direction."""
        want = (facing or default or "ref").strip().lower()
        if want in fg.COMPASS_DEG:
            return fg.COMPASS_DEG[want]
        if want == "ref":
            return toward_yaw
        if want == "room":
            return ref_yaw % 360.0
        if want == "wall":
            return (ref_yaw + 180.0) % 360.0
        return toward_yaw if default == "ref" else ref_yaw % 360.0

    # ── emitting ────────────────────────────────────────────────────────

    def _commit(self, item: _Item, *, at_world: Vec, yaw_world: float,
                y0: float, store_at: Optional[Vec] = None,
                store_yaw: Optional[float] = None,
                offset_y: Optional[float] = None, on: str = "",
                depth: int = 0, occupy: bool = True,
                wall_series: Optional[Tuple[str, List[Vec]]] = None
                ) -> Dict[str, Any]:
        place_id, ordinal = self._mint_id(item.prop)
        facts = {"width_m": item.w, "depth_m": item.d, "height_m": item.h,
                 "mount": item.mount, "ground_offset_m": item.ground_offset_m}
        # An underlay is never an obstacle, whichever anchor put it down (B10).
        piece = self._add(prop_id=item.prop, place_id=place_id, at=at_world,
                          yaw=yaw_world, facts=facts, y0=y0, on=on,
                          depth=depth,
                          occupy=occupy and not item.is_underlay)
        if item.mount == "floor" and not item.is_underlay:
            self.used_area += item.area
        if wall_series:
            self.wall_series[wall_series[0]].append(wall_series[1])
        at = store_at if store_at is not None else at_world
        entry: Dict[str, Any] = {
            "prop_id": item.prop, "id": place_id,
            "at": [round(at[0], 2), round(at[1], 2)],
            "yaw": round((store_yaw if store_yaw is not None
                          else yaw_world) % 360.0, 1)}
        if offset_y is not None:
            entry["offset_y"] = round(offset_y, 3)
        if on:
            entry["on"] = on
        if item.variants > 1:
            entry["variant"] = ordinal % item.variants
        return entry


# ── Pass A — floor ──────────────────────────────────────────────────────

def _place_at_wall(s: _Solver, item: _Item, yaw: float, *, wall: str,
                   gap: float, base: Optional[float],
                   series: bool) -> Optional[Dict[str, Any]]:
    """The shared wall walk: centred on the wall, then symmetric slide outwards
    in 0.25 m steps, over every edge of that wall class."""
    for edge in fg.wall_edges(s.poly, s.centroid, wall):
        a, d, n, length = fg.edge_geometry(s.poly, s.centroid, edge)
        perp = fg.half_extent(item.w, item.d, yaw, n)
        along = fg.half_extent(item.w, item.d, yaw, d)
        usable = length - 2 * along
        for frac in fg.centred_offsets(usable, SAMPLE_STEP_M):
            t = along + frac * max(usable, 0.0)
            px = a[0] + d[0] * t + n[0] * (perp + gap)
            pz = a[1] + d[1] * t + n[1] * (perp + gap)
            y0 = base if base is not None else item.ground_offset_m
            corners = fg.rect_corners(px, pz, item.w, item.d, yaw)
            grown = _grown_along_wall(px, pz, d, n, along, perp)
            if series and not _series_free(s, wall, grown):
                continue
            if s._fits(corners, y0, y0 + item.h):
                return s._commit(item, at_world=(px, pz), yaw_world=yaw, y0=y0,
                                 offset_y=(None if base is None
                                           else y0 - item.ground_offset_m),
                                 wall_series=(wall, grown) if series else None)
    return None


def _grown_along_wall(px: float, pz: float, d: Vec, n: Vec, along: float,
                      perp: float) -> List[Vec]:
    """The candidate's quad grown by 0.15 m on each side ALONG the wall — two
    pieces on one wall keep 0.3 m between them (B4)."""
    ex = along + WALL_SERIES_GAP_M / 2
    return [(px + d[0] * ex + n[0] * perp, pz + d[1] * ex + n[1] * perp),
            (px + d[0] * ex - n[0] * perp, pz + d[1] * ex - n[1] * perp),
            (px - d[0] * ex - n[0] * perp, pz - d[1] * ex - n[1] * perp),
            (px - d[0] * ex + n[0] * perp, pz - d[1] * ex + n[1] * perp)]


def _series_free(s: _Solver, wall: str, grown: List[Vec]) -> bool:
    for other in s.wall_series[wall]:
        if fg.rects_overlap(grown, other):
            return False
    return True


def _floor_wall_yaw(item: _Item, wall: str) -> float:
    facing = (item.facing or "room").strip().lower()
    if facing in fg.COMPASS_DEG:
        return fg.COMPASS_DEG[facing]
    yaw = fg.WALL_YAW_ROOM[wall]
    return (yaw + 180.0) % 360.0 if facing == "wall" else yaw


def _place_floor_wall(s: _Solver, item: _Item,
                      wall: str) -> Tuple[Optional[Dict[str, Any]], str]:
    yaw = _floor_wall_yaw(item, wall)
    if not fg.wall_edges(s.poly, s.centroid, wall):
        return None, (f"there is no wall_{wall} in this room — "
                      f"try wall_{_other_wall(wall)} or center")
    hit = _place_at_wall(s, item, yaw, wall=wall, gap=FLOOR_GAP_M, base=None,
                         series=True)
    if hit:
        return hit, ""
    return None, (f"no free wall spot on wall_{wall} — "
                  f"try wall_{_other_wall(wall)} or center")


def _place_corner(s: _Solver, item: _Item,
                  corner: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """corner_ne → the walls n and e; the piece takes whichever of the two lets
    it stand, sliding away from the corner along that wall when blocked."""
    code = corner[-2:]
    ns, ew = code[0], code[1]
    for wall in (ns, ew):
        yaw = _floor_wall_yaw(item, wall)
        ex, ez = fg.aabb_extents(item.w, item.d, yaw)
        cx = (ex / 2 + FLOOR_GAP_M if ew == "w"
              else s.W - ex / 2 - FLOOR_GAP_M)
        cz = (ez / 2 + FLOOR_GAP_M if ns == "n"
              else s.D - ez / 2 - FLOOR_GAP_M)
        along = fg.COMPASS_VEC["s" if wall in ("e", "w") else "e"]
        normal = (-along[1], along[0])
        sign = 1.0 if (ew == "w" if wall in ("n", "s") else ns == "n") else -1.0
        steps = int(max(s.W, s.D) / SAMPLE_STEP_M)
        for k in range(steps + 1):
            px = cx + along[0] * sign * k * SAMPLE_STEP_M
            pz = cz + along[1] * sign * k * SAMPLE_STEP_M
            corners = fg.rect_corners(px, pz, item.w, item.d, yaw)
            y0 = item.ground_offset_m
            half_along = fg.half_extent(item.w, item.d, yaw, along)
            half_perp = fg.half_extent(item.w, item.d, yaw, normal)
            grown = _grown_along_wall(px, pz, along, normal, half_along,
                                      half_perp)
            if s._fits(corners, y0, y0 + item.h):
                return s._commit(item, at_world=(px, pz), yaw_world=yaw,
                                 y0=y0, wall_series=(wall, grown)), ""
    return None, (f"no free spot in the {code} corner — "
                  f"try wall_{code[0]} or center")


def _center_rings(s: _Solver) -> List[Vec]:
    """The centroid, then rings of eight points around it in 0.25 m steps — the
    v1 search, kept for the case the grid is not about: ONE piece in the middle
    of the room belongs in the MIDDLE of the room."""
    cx, cz = s.centroid
    out: List[Vec] = [(cx, cz)]
    rings = int(max(s.W, s.D) / (2 * SAMPLE_STEP_M)) + 1
    for ring in range(1, rings + 1):
        r = ring * SAMPLE_STEP_M
        for i in range(8):
            a = i * math.pi / 4
            out.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    return out


def _center_cells(s: _Solver, items: List[_Item]) -> List[Vec]:
    """The walkway grid of pass A's ``center`` group (B4).

    A group of ONE piece (underlays do not count — they lie under something)
    has no walkway to keep: it takes the centroid and, if that is blocked,
    searches outwards in rings (:func:`_center_rings`).

    From two pieces on, cell = the largest footprint of the group plus a 0.9 m
    gangway, per axis. The bounding box is tiled with as many whole cells as fit
    (``n = max(1, floor(extent / cell))``), the cell centres spread evenly over
    it, and the cells are visited by distance to the outline's centroid —
    equal distances north-west first. Tiling rather than stepping outwards from
    the centroid is what keeps every cell INSIDE the box: a grid of centroid ±
    k·cell puts its outer cells half a cell beyond the wall, where nothing can
    stand.
    """
    solid = [it for it in items if not it.is_underlay]
    if sum(it.count for it in solid) <= 1:
        return _center_rings(s)
    cell_w = max(it.w for it in solid) + WALKWAY_M
    cell_d = max(it.d for it in solid) + WALKWAY_M
    nx = max(1, int(s.W / cell_w + 1e-9))
    nz = max(1, int(s.D / cell_d + 1e-9))
    cells = [(s.W * (i + 0.5) / nx, s.D * (j + 0.5) / nz)
             for j in range(nz) for i in range(nx)]
    cells.sort(key=lambda c: (round(math.hypot(c[0] - s.centroid[0],
                                               c[1] - s.centroid[1]), 6),
                              c[1], c[0]))
    return cells


def _place_center_group(s: _Solver, items: List[_Item],
                        placed: List[Dict[str, Any]],
                        unplaced: List[Dict[str, str]]) -> None:
    """Every ``center`` copy of pass A at once — each takes the first free cell,
    so three tables end up spread with a gangway instead of in one heap."""
    cells = _center_cells(s, items)
    used: List[int] = []
    for item in items:
        for _ in range(item.count):
            if not item.is_underlay and s.used_area + item.area > s.budget:
                unplaced.append(_fail(item, "floor budget exhausted — drop a "
                                            "piece or use a smaller one"))
                continue
            hit = None
            for index, cell in enumerate(cells):
                # An underlay occupies nothing (B10), so it neither claims a
                # cell nor avoids one — but it may not stick out of the room.
                if index in used and not item.is_underlay:
                    continue
                facing = (item.facing or "door").strip().lower()
                yaw = (fg.COMPASS_DEG[facing] if facing in fg.COMPASS_DEG
                       else s._door_yaw(cell))
                y0 = item.ground_offset_m
                corners = fg.rect_corners(cell[0], cell[1], item.w, item.d, yaw)
                ok = (fg.rect_in_poly(corners, s.poly) if item.is_underlay
                      else s._fits(corners, y0, y0 + item.h))
                if ok:
                    if not item.is_underlay:
                        used.append(index)
                    hit = s._commit(item, at_world=cell, yaw_world=yaw, y0=y0,
                                    occupy=not item.is_underlay)
                    break
            if hit:
                placed.append(hit)
            else:
                unplaced.append(_fail(item, "no free cell in the middle of the "
                                            "room — try wall_n or beside"))


def _ref_frame(ref_piece: _Piece) -> Tuple[Vec, Vec, Vec, Vec, Vec]:
    """Front, back, left and right unit vectors of a placed piece, named from
    the piece's own point of view (it looks along its front)."""
    front = fg.compass_vec(ref_piece.yaw)
    back = (-front[0], -front[1])
    left = fg.compass_vec(ref_piece.yaw + 90.0)
    right = (-left[0], -left[1])
    return ref_piece.at, front, back, left, right


def _place_in_front_of(s: _Solver, item: _Item, ref_pieces: List[_Piece],
                       placed: List[Dict[str, Any]],
                       unplaced: List[Dict[str, str]]) -> None:
    """A row across the reference's FRONT side, spacing 0.1 m, centred on it.
    The distance uses the reference's half extent ALONG ITS FRONT AXIS — not
    the maximum extent, which pushed stools 1.33 m off a narrow table in v1."""
    ref_piece = s._pick(ref_pieces)
    centre, front, _back, left, _right = _ref_frame(ref_piece)
    ref_half = fg.half_extent(ref_piece.w, ref_piece.d, ref_piece.yaw, front)
    toward = (fg.compass_of((-front[0], -front[1])))
    yaw = s._relative_yaw(item.facing, "ref", ref_yaw=ref_piece.yaw,
                          toward_yaw=toward)
    my_half = fg.half_extent(item.w, item.d, yaw, front)
    pitch = item.w + ROW_PITCH_M
    for i in range(item.count):
        if not item.is_underlay and s.used_area + item.area > s.budget:
            unplaced.append(_fail(item, "floor budget exhausted — drop a piece "
                                        "or use a smaller one"))
            continue
        lateral = (i - (item.count - 1) / 2.0) * pitch
        hit = None
        for gap in REF_GAPS_M:
            dist = ref_half + my_half + gap
            px = centre[0] + front[0] * dist + left[0] * lateral
            pz = centre[1] + front[1] * dist + left[1] * lateral
            use_yaw = (s._door_yaw((px, pz))
                       if (item.facing or "").lower() == "door" else yaw)
            y0 = item.ground_offset_m
            corners = fg.rect_corners(px, pz, item.w, item.d, use_yaw)
            if s._fits(corners, y0, y0 + item.h):
                hit = s._commit(item, at_world=(px, pz), yaw_world=use_yaw,
                                y0=y0, occupy=not item.is_underlay)
                break
        if hit:
            placed.append(hit)
        else:
            unplaced.append(_fail(
                item, f"no free spot in front of '{item.ref}' — "
                      f"try beside or center"))


def _place_beside(s: _Solver, item: _Item, ref_pieces: List[_Piece],
                  placed: List[Dict[str, Any]],
                  unplaced: List[Dict[str, str]]) -> None:
    """ONE side of the reference (the nightstand case): left first, then right,
    with the projected half extent OF THAT SIDE. Every copy takes the next free
    gap/side — an occupied spot is simply blocked."""
    ref_piece = s._pick(ref_pieces)
    centre, _front, _back, left, right = _ref_frame(ref_piece)
    for _ in range(item.count):
        if not item.is_underlay and s.used_area + item.area > s.budget:
            unplaced.append(_fail(item, "floor budget exhausted — drop a piece "
                                        "or use a smaller one"))
            continue
        hit = None
        # Gap-major: the nearest gap on EITHER side beats the second gap on the
        # first side, so two nightstands end up left and right of the bed.
        for gap in REF_GAPS_M:
            for side in (left, right):
                ref_half = fg.half_extent(ref_piece.w, ref_piece.d,
                                          ref_piece.yaw, side)
                toward = fg.compass_of((-side[0], -side[1]))
                yaw = s._relative_yaw(item.facing, "room",
                                      ref_yaw=ref_piece.yaw,
                                      toward_yaw=toward)
                my_half = fg.half_extent(item.w, item.d, yaw, side)
                dist = ref_half + my_half + gap
                px = centre[0] + side[0] * dist
                pz = centre[1] + side[1] * dist
                use_yaw = (s._door_yaw((px, pz))
                           if (item.facing or "").lower() == "door" else yaw)
                y0 = item.ground_offset_m
                corners = fg.rect_corners(px, pz, item.w, item.d, use_yaw)
                if s._fits(corners, y0, y0 + item.h):
                    hit = s._commit(item, at_world=(px, pz),
                                    yaw_world=use_yaw, y0=y0,
                                    occupy=not item.is_underlay)
                    break
            if hit:
                break
        if hit:
            placed.append(hit)
        else:
            unplaced.append(_fail(item, f"no free side next to '{item.ref}' — "
                                        f"try around or center"))


# Sides of a rectangle in the order the seat assignment breaks ties.
_SIDES = ("front", "right", "back", "left")


def _side_geometry(ref_piece: _Piece, side: str) -> Tuple[Vec, Vec, float, float]:
    """Outward normal, the along-axis, the side's length and the reference's
    half extent towards that side."""
    _c, front, back, left, right = _ref_frame(ref_piece)
    if side == "front":
        return front, left, ref_piece.w, ref_piece.d / 2
    if side == "back":
        return back, left, ref_piece.w, ref_piece.d / 2
    if side == "left":
        return left, front, ref_piece.d, ref_piece.w / 2
    return right, front, ref_piece.d, ref_piece.w / 2


def _seat_sides(ref_piece: _Piece, item: _Item,
                count: int) -> Tuple[Dict[str, int], int, int]:
    """Distribute ``count`` seats over the four sides (B4).

    Capacity per side = ``floor((L + 0.1) / (w_child + 0.1))``; every seat goes
    to the side with the lowest ``assigned / capacity``, ties to the longer
    side, then front, right, back, left. Returns the assignment, the total
    capacity and how many seats found no side.
    """
    caps: Dict[str, int] = {}
    lengths: Dict[str, float] = {}
    for side in _SIDES:
        _n, _a, length, _h = _side_geometry(ref_piece, side)
        lengths[side] = length
        caps[side] = int((length + SEAT_PITCH_M) / (item.w + SEAT_PITCH_M)
                         + 1e-9)
    assigned = {side: 0 for side in _SIDES}
    total = sum(caps.values())
    over = 0
    for _ in range(count):
        free = [side for side in _SIDES if assigned[side] < caps[side]]
        if not free:
            over += 1
            continue
        pick = min(free, key=lambda side: (
            assigned[side] / caps[side], -lengths[side], _SIDES.index(side)))
        assigned[pick] += 1
    return assigned, total, over


def _place_around(s: _Solver, item: _Item, ref_pieces: List[_Piece],
                  placed: List[Dict[str, Any]],
                  unplaced: List[Dict[str, str]]) -> None:
    """Seats around a table or counter. Copies are spread round-robin over the
    reference's instances first, then over the sides of each instance."""
    per_instance: List[int] = [0] * len(ref_pieces)
    for i in range(item.count):
        per_instance[i % len(ref_pieces)] += 1
    for ref_piece, count in zip(ref_pieces, per_instance):
        if count <= 0:
            continue
        assigned, capacity, over = _seat_sides(ref_piece, item, count)
        for side in _SIDES:
            k = assigned[side]
            if k <= 0:
                continue
            normal, along, length, ref_half = _side_geometry(ref_piece, side)
            dist = ref_half + item.d / 2 + SEAT_GAP_M
            for i in range(k):
                if s.used_area + item.area > s.budget:
                    unplaced.append(_fail(item, "floor budget exhausted — drop "
                                                "a piece or use a smaller one"))
                    continue
                offset = (i + 1) * length / (k + 1) - length / 2
                px = ref_piece.at[0] + normal[0] * dist + along[0] * offset
                pz = ref_piece.at[1] + normal[1] * dist + along[1] * offset
                yaw = fg.compass_of((-normal[0], -normal[1]))
                y0 = item.ground_offset_m
                corners = fg.rect_corners(px, pz, item.w, item.d, yaw)
                if s._fits(corners, y0, y0 + item.h):
                    placed.append(s._commit(item, at_world=(px, pz),
                                            yaw_world=yaw, y0=y0))
                else:
                    unplaced.append(_fail(
                        item, f"the seat on the {side} side of '{item.ref}' is "
                              f"blocked — lower the count or use beside"))
        for _ in range(over):
            unplaced.append(_fail(
                item, f"no seat around '{item.ref}' (capacity {capacity}) — "
                      f"lower the count or use beside"))


def _place_under(s: _Solver, item: _Item, ref_pieces: List[_Piece],
                 placed: List[Dict[str, Any]],
                 unplaced: List[Dict[str, str]]) -> None:
    """A rug under a table (B10): centred on the reference, its yaw, no
    occupancy and no budget — it is an underlay, not an obstacle."""
    if not item.is_underlay:
        for _ in range(item.count):
            unplaced.append(_fail(
                item, "'under' is for flat underlays (height ≤ 5 cm) — "
                      "use beside or center"))
        return
    for i in range(item.count):
        ref_piece = ref_pieces[i % len(ref_pieces)]
        # It blocks nothing, but it may not hang through a wall either.
        corners = fg.rect_corners(ref_piece.at[0], ref_piece.at[1], item.w,
                                  item.d, ref_piece.yaw)
        if not fg.rect_in_poly(corners, s.poly):
            unplaced.append(_fail(
                item, f"it would stick out of the room under '{item.ref}' — "
                      f"use a smaller underlay or center"))
            continue
        placed.append(s._commit(item, at_world=ref_piece.at,
                                yaw_world=ref_piece.yaw,
                                y0=item.ground_offset_m, occupy=False))


# ── Pass B — wall and ceiling ───────────────────────────────────────────

def _wall_base(item: _Item, storey: float) -> float:
    """``base_m`` from the plan, clamped to ``[0.3, storey − height]``; absent →
    centred at 1.5 m, clamped the same way (B1/E2)."""
    top = max(WALL_BASE_MIN_M, storey - item.h)
    want = (item.base_m if item.base_m is not None
            else WALL_BASE_CENTRE_M - item.h / 2)
    return min(max(want, WALL_BASE_MIN_M), top)


def _wall_budget_left(s: _Solver, item: _Item, wall: str) -> bool:
    return s.wall_used[wall] + item.w <= s.wall_budget.get(wall, 0.0) + 1e-9


def _place_wall_piece(s: _Solver, item: _Item,
                      wall: str) -> Tuple[Optional[Dict[str, Any]], str]:
    if not fg.wall_edges(s.poly, s.centroid, wall):
        return None, (f"there is no wall_{wall} in this room — "
                      f"try wall_{_other_wall(wall)} or make the piece "
                      f"floor-standing")
    if not _wall_budget_left(s, item, wall):
        return None, (f"wall budget on wall_{wall} exhausted — "
                      f"use another wall or drop the piece")
    yaw = fg.WALL_YAW_ROOM[wall]
    base = _wall_base(item, s.storey)
    hit = _place_at_wall(s, item, yaw, wall=wall, gap=WALL_GAP_M, base=base,
                         series=False)
    if hit:
        s.wall_used[wall] += item.w
        return hit, ""
    return None, (f"no free wall spot on wall_{wall} — "
                  f"try wall_{_other_wall(wall)} or another wall")


def _support_wall(s: _Solver, ref_piece: _Piece) -> Optional[Tuple[int, str]]:
    """The wall edge the reference stands at: its BACK edge midpoint must lie
    within 0.15 m of a polygon edge."""
    _c, front, _b, _l, _r = _ref_frame(ref_piece)
    half = fg.half_extent(ref_piece.w, ref_piece.d, ref_piece.yaw, front)
    back_mid = (ref_piece.at[0] - front[0] * half,
                ref_piece.at[1] - front[1] * half)
    best: Optional[Tuple[float, int]] = None
    for i in range(len(s.poly)):
        a = s.poly[i]
        b = s.poly[(i + 1) % len(s.poly)]
        dist = fg.point_segment_distance(back_mid, a, b)
        if dist <= WALL_ABOVE_TOL_M and (best is None or dist < best[0]):
            best = (dist, i)
    if best is None:
        return None
    return best[1], fg.edge_wall_class(s.poly, s.centroid, best[1])


def _place_wall_above(s: _Solver, item: _Item,
                      ref_pieces: List[_Piece]
                      ) -> Tuple[Optional[Dict[str, Any]], str]:
    ref_piece = s._pick(ref_pieces)
    if ref_piece.mount != "floor":
        return None, (f"'{item.ref}' is not a floor piece — "
                      f"use wall_n…w instead")
    found = _support_wall(s, ref_piece)
    if not found:
        return None, (f"'{item.ref}' does not stand at a wall — "
                      f"use wall_n…w instead")
    edge, wall = found
    if not _wall_budget_left(s, item, wall):
        return None, (f"wall budget on wall_{wall} exhausted — "
                      f"use another wall or drop the piece")
    yaw = fg.WALL_YAW_ROOM[wall]
    top = max(WALL_BASE_MIN_M, s.storey - item.h)
    want = (item.base_m if item.base_m is not None
            else ref_piece.top + WALL_ABOVE_GAP_M)
    base = min(max(want, WALL_BASE_MIN_M), top)
    a, d, n, length = fg.edge_geometry(s.poly, s.centroid, edge)
    perp = fg.half_extent(item.w, item.d, yaw, n)
    along = fg.half_extent(item.w, item.d, yaw, d)
    t0 = ((ref_piece.at[0] - a[0]) * d[0] + (ref_piece.at[1] - a[1]) * d[1])
    lo, hi = along, max(along, length - along)
    steps = int(length / SAMPLE_STEP_M) + 1
    offsets = [0.0]
    for k in range(1, steps + 1):
        offsets.extend((k * SAMPLE_STEP_M, -k * SAMPLE_STEP_M))
    for off in offsets:
        t = min(max(t0 + off, lo), hi)
        px = a[0] + d[0] * t + n[0] * (perp + WALL_GAP_M)
        pz = a[1] + d[1] * t + n[1] * (perp + WALL_GAP_M)
        corners = fg.rect_corners(px, pz, item.w, item.d, yaw)
        if s._fits(corners, base, base + item.h):
            s.wall_used[wall] += item.w
            return s._commit(item, at_world=(px, pz), yaw_world=yaw, y0=base,
                             offset_y=base - item.ground_offset_m), ""
    return None, (f"no free wall spot above '{item.ref}' — "
                  f"try wall_{wall} or another wall")


def _find_opening(s: _Solver, ref: str) -> Optional[int]:
    """``ref`` is an opening index or ``"window"`` = the next window that has no
    piece yet."""
    ref = str(ref or "window").strip().lower()
    if ref not in ("window", ""):
        try:
            index = int(ref)
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < len(s.openings):
            return index
        return None
    for index, op in enumerate(s.openings):
        if str(op.get("type") or "door") != "window":
            continue
        if index in s.taken_openings:
            continue
        return index
    return None


def _place_at_opening(s: _Solver, item: _Item
                      ) -> Tuple[Optional[Dict[str, Any]], str]:
    index = _find_opening(s, item.ref or "window")
    if index is None:
        return None, ("this room has no free window — "
                      "use wall_n…w or drop the piece")
    op = s.openings[index]
    found = fg.opening_point(s.poly, s.centroid, op)
    if not found:
        return None, ("this window sits on no usable wall — "
                      "use wall_n…w or drop the piece")
    p, _d, n, edge = found
    wall = fg.edge_wall_class(s.poly, s.centroid, edge)
    if not _wall_budget_left(s, item, wall):
        return None, (f"wall budget on wall_{wall} exhausted — "
                      f"use another wall or drop the piece")
    try:
        sill = float(op.get("sill_m") or 0.0)
        height = float(op.get("height_m") or 2.1)
    except (TypeError, ValueError):
        sill, height = 0.0, 2.1
    top = max(0.05, s.storey - item.h)
    base = min(max(sill + height + OPENING_PIECE_GAP_M - item.h, 0.05), top)
    yaw = fg.WALL_YAW_ROOM[wall]
    perp = fg.half_extent(item.w, item.d, yaw, n)
    px = p[0] + n[0] * (perp + WALL_GAP_M)
    pz = p[1] + n[1] * (perp + WALL_GAP_M)
    corners = fg.rect_corners(px, pz, item.w, item.d, yaw)
    if not s._fits(corners, base, base + item.h, ignore_opening=index):
        return None, (f"the space at this window is taken — "
                      f"try wall_{_other_wall(wall)} or drop the piece")
    s.taken_openings.add(index)
    s.wall_used[wall] += item.w
    return s._commit(item, at_world=(px, pz), yaw_world=yaw, y0=base,
                     offset_y=base - item.ground_offset_m), ""


def _place_ceiling(s: _Solver, item: _Item, ref_pieces: List[_Piece]
                   ) -> Tuple[Optional[Dict[str, Any]], str]:
    """A hanging piece: its base is the storey height minus its own height (the
    prop's height includes chain or cord), never below 1.9 m."""
    base = max(CEILING_MIN_BASE_M, s.storey - item.h)
    if ref_pieces:
        ref_piece = s._pick(ref_pieces)
        at = ref_piece.at
        yaw = ref_piece.yaw
    else:
        at = s.centroid
        yaw = 0.0
    corners = fg.rect_corners(at[0], at[1], item.w, item.d, yaw)
    if not s._fits(corners, base, base + item.h):
        target = f"above '{item.ref}'" if ref_pieces else "over the room centre"
        return None, (f"the ceiling {target} is taken — "
                      f"try another reference or center")
    return s._commit(item, at_world=at, yaw_world=yaw, y0=base,
                     offset_y=base - item.ground_offset_m), ""


# ── Pass C — surface ────────────────────────────────────────────────────

def _surface_cells(support: _Piece, item: _Item) -> List[Vec]:
    """Raster over the support's top in the support's own local frame: step
    0.15 m, inset by the child's half extent, centre first then symmetric
    outwards (x runs fastest, so the second candle lands beside the first)."""
    inset = max(item.w, item.d) / 2
    xs = fg.symmetric_ticks(support.w / 2 - inset, SURFACE_STEP_M)
    zs = fg.symmetric_ticks(support.d / 2 - inset, SURFACE_STEP_M)
    return [(x, z) for z in zs for x in xs]


def _place_on(s: _Solver, item: _Item, support: _Piece
              ) -> Tuple[Optional[Dict[str, Any]], str]:
    # A floor piece or a wall shelf carries things — and so does something
    # that already stands on one (a tray on a table), up to the chain depth.
    if support.mount not in ("floor", "wall") and not support.on:
        return None, (f"support '{item.ref}' is not a floor piece — "
                      f"put it on a table or shelf")
    if support.h < SUPPORT_MIN_H:
        return None, (f"support '{item.ref}' is too low to stand on — "
                      f"put it on a table or shelf")
    if support.depth + 1 > MAX_CHAIN_DEPTH:
        return None, (f"'{item.ref}' is already stacked three deep — "
                      f"put it on a table or shelf")
    budget = support.w * support.d * SURFACE_BUDGET_FRACTION
    if s.surface_used.get(support.place_id, 0.0) + item.area > budget + 1e-9:
        return None, (f"surface of '{item.ref}' is full — "
                      f"use another support or lower the count")
    # THE STACKING FORMULA lives in props.stack_on_support — one rule, one
    # place. It answers the child's composed offset_y; its true base adds the
    # child's own ground offset back on.
    offset_y = stack_on_support(support.box(),
                                {"ground_offset_m": item.ground_offset_m})
    y0 = offset_y + item.ground_offset_m
    for dx, dz in _surface_cells(support, item):
        at = fg.local_to_world(support.at[0], support.at[1], support.yaw,
                               dx, dz)
        yaw = support.yaw
        corners = fg.rect_corners(at[0], at[1], item.w, item.d, yaw)
        if not s._fits(corners, y0, y0 + item.h):
            continue
        s.surface_used[support.place_id] = (
            s.surface_used.get(support.place_id, 0.0) + item.area)
        return s._commit(item, at_world=at, yaw_world=yaw, y0=y0,
                         store_at=(dx, dz), store_yaw=0.0,
                         on=support.place_id, depth=support.depth + 1), ""
    return None, (f"surface of '{item.ref}' is full — "
                  f"use another support or lower the count")


# ── Orchestration ───────────────────────────────────────────────────────

def _fail(item: _Item, reason: str) -> Dict[str, str]:
    return {"name": item.prop, "reason": reason,
            "pass": _PASS_OF_MOUNT.get(item.mount, "floor")}


def _normalize(plan: Optional[Sequence[Dict[str, Any]]],
               solver: _Solver) -> Tuple[List[_Item], List[Dict[str, str]]]:
    items: List[_Item] = []
    bad: List[Dict[str, str]] = []
    for order, raw in enumerate(plan or []):
        if not isinstance(raw, dict):
            continue
        prop = str(raw.get("prop") or "")
        # A stated ZERO means zero — only a missing count falls back to one.
        want = raw.get("count")
        try:
            count = 1 if want is None else int(want)
        except (TypeError, ValueError):
            count = 1
        count = max(0, min(MAX_COUNT, count))
        if count <= 0:
            continue
        facts = solver._prop(prop)
        if not facts:
            for _ in range(count):
                bad.append({"name": prop or "?", "pass": "floor",
                            "reason": "unknown prop — remove it from the plan "
                                      "or add it to the library"})
            continue
        base_m: Optional[float]
        try:
            base_m = (None if raw.get("base_m") is None
                      else float(raw.get("base_m")))
        except (TypeError, ValueError):
            base_m = None
        items.append(_Item(
            prop=prop, count=count,
            anchor=str(raw.get("anchor") or "center").strip().lower(),
            ref=None if raw.get("ref") is None else str(raw.get("ref")),
            facing=str(raw.get("facing") or "").strip().lower(),
            base_m=base_m, mount=facts["mount"], w=facts["width_m"],
            d=facts["depth_m"], h=facts["height_m"],
            ground_offset_m=facts["ground_offset_m"],
            variants=facts["variants"], order=order))
    return items, bad


def _anchor_error(item: _Item) -> str:
    """An anchor that belongs to another pass — named with one alternative."""
    if item.anchor == "on" and item.mount != "surface":
        return "anchor 'on' is for surface pieces — use wall_n… or center"
    if item.mount == "wall":
        return ("a wall piece needs a wall anchor — use wall_n…w, wall_above "
                "or at_opening")
    if item.mount == "ceiling":
        return "a ceiling piece hangs — use above <ref> or center"
    if item.mount == "surface":
        return "a surface piece needs anchor 'on' — use on <support>"
    return f"anchor '{item.anchor}' is not a floor anchor — use center or wall_n…w"


def _needs_ref(anchor: str) -> bool:
    return anchor in ("in_front_of", "beside", "around", "under", "wall_above",
                      "above", "on")


def _ref_error(item: _Item) -> str:
    return (f"reference '{item.ref}' is not placed — "
            f"place it first or use center")


def _run_floor(s: _Solver, items: List[_Item], placed: List[Dict[str, Any]],
               unplaced: List[Dict[str, str]]) -> None:
    ranked = sorted(items, key=lambda it: (_FLOOR_RANK.get(it.anchor, 4),
                                           it.order))
    center_items = [it for it in ranked if it.anchor == "center"]
    for item in ranked:
        if item.anchor not in _FLOOR_ANCHORS:
            for _ in range(item.count):
                unplaced.append(_fail(item, _anchor_error(item)))
            continue
        if item.anchor == "center":
            if center_items and item is center_items[0]:
                _place_center_group(s, center_items, placed, unplaced)
            continue
        ref_pieces: List[_Piece] = []
        if _needs_ref(item.anchor):
            ref_pieces = s._resolve(item.ref or "")
            if not ref_pieces:
                for _ in range(item.count):
                    unplaced.append(_fail(item, _ref_error(item)))
                continue
        if item.anchor == "around":
            _place_around(s, item, ref_pieces, placed, unplaced)
            continue
        if item.anchor == "in_front_of":
            _place_in_front_of(s, item, ref_pieces, placed, unplaced)
            continue
        if item.anchor == "beside":
            _place_beside(s, item, ref_pieces, placed, unplaced)
            continue
        if item.anchor == "under":
            _place_under(s, item, ref_pieces, placed, unplaced)
            continue
        for _ in range(item.count):
            if not item.is_underlay and s.used_area + item.area > s.budget:
                unplaced.append(_fail(item, "floor budget exhausted — drop a "
                                            "piece or use a smaller one"))
                continue
            if item.anchor in _WALL_ANCHORS:
                hit, reason = _place_floor_wall(s, item, item.anchor[-1])
            else:
                hit, reason = _place_corner(s, item, item.anchor)
            if hit:
                placed.append(hit)
            else:
                unplaced.append(_fail(item, reason))


def _run_wall(s: _Solver, items: List[_Item], placed: List[Dict[str, Any]],
              unplaced: List[Dict[str, str]]) -> None:
    ranked = sorted(items, key=lambda it: (_WALL_RANK.get(it.anchor, 3),
                                           it.order))
    for item in ranked:
        allowed = (_WALL_PASS_ANCHORS if item.mount == "wall"
                   else _CEILING_PASS_ANCHORS)
        if item.anchor not in allowed:
            for _ in range(item.count):
                unplaced.append(_fail(item, _anchor_error(item)))
            continue
        for _ in range(item.count):
            ref_pieces: List[_Piece] = []
            if _needs_ref(item.anchor):
                ref_pieces = s._resolve(item.ref or "")
                if not ref_pieces:
                    unplaced.append(_fail(item, _ref_error(item)))
                    continue
            if item.mount == "ceiling":
                hit, reason = _place_ceiling(s, item, ref_pieces)
            elif item.anchor == "wall_above":
                hit, reason = _place_wall_above(s, item, ref_pieces)
            elif item.anchor == "at_opening":
                hit, reason = _place_at_opening(s, item)
            else:
                hit, reason = _place_wall_piece(s, item, item.anchor[-1])
            if hit:
                placed.append(hit)
            else:
                unplaced.append(_fail(item, reason))


def _run_surface(s: _Solver, items: List[_Item], placed: List[Dict[str, Any]],
                 unplaced: List[Dict[str, str]]) -> None:
    for item in sorted(items, key=lambda it: it.order):
        if item.anchor not in _SURFACE_PASS_ANCHORS:
            for _ in range(item.count):
                unplaced.append(_fail(item, _anchor_error(item)))
            continue
        supports = s._resolve(item.ref or "")
        if not supports:
            for _ in range(item.count):
                unplaced.append(_fail(item, _ref_error(item)))
            continue
        for i in range(item.count):
            support = supports[i % len(supports)]
            hit, reason = _place_on(s, item, support)
            if hit:
                placed.append(hit)
            else:
                unplaced.append(_fail(item, reason))


def solve(*, outline_m: Sequence[Sequence[float]],
          openings: Optional[Sequence[Dict[str, Any]]],
          existing: Optional[Sequence[Dict[str, Any]]],
          plan: Optional[Sequence[Dict[str, Any]]],
          props: Optional[Dict[str, Dict[str, Any]]],
          storey_height_m: float = 3.0) -> Dict[str, Any]:
    """Solve the relational plan.

    ``props[pid]`` = ``{width_m, depth_m, height_m, mount, ground_offset_m,
    variants}`` (mount defaults to ``floor``, ground offset to 0, variants to
    1); ``existing`` = the placements already in the room, ALREADY COMPOSED by
    the caller (``room_recipe.compose_on_chain``); ``plan`` = the LLM entries
    ``{prop, count, anchor, ref, facing, base_m}``.

    Returns ``{"placed": [...], "unplaced": [{"name", "reason", "pass"}]}``.
    A placed entry is ready to store: ``{prop_id, id, at, yaw}`` plus
    ``offset_y`` for wall/ceiling pieces, ``on`` + a CHILD-FRAME ``at`` for
    surface pieces and ``variant`` for props with more than one variant.
    Reasons are short English strings that end with one concrete alternative —
    they feed the repair round and the review UI.
    """
    plan = [it for it in (plan or []) if isinstance(it, dict)]
    if not outline_m or len(outline_m) < 3:
        return {"placed": [], "unplaced": [
            {"name": str(it.get("prop") or "?"), "pass": "floor",
             "reason": "invalid room polygon — draw the room outline first"}
            for it in plan]}
    s = _Solver(outline_m=outline_m, openings=openings, existing=existing,
                props=props, storey_height_m=storey_height_m)
    if s.area <= 0.01 or s.W <= 0.01 or s.D <= 0.01:
        return {"placed": [], "unplaced": [
            {"name": str(it.get("prop") or "?"), "pass": "floor",
             "reason": "invalid room polygon — draw the room outline first"}
            for it in plan]}
    items, unplaced = _normalize(plan, s)
    placed: List[Dict[str, Any]] = []
    _run_floor(s, [it for it in items if it.mount == "floor"], placed, unplaced)
    _run_wall(s, [it for it in items if it.mount in ("wall", "ceiling")],
              placed, unplaced)
    _run_surface(s, [it for it in items if it.mount == "surface"], placed,
                 unplaced)
    return {"placed": placed, "unplaced": unplaced}
