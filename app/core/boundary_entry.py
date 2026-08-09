"""Entry/exit decisions at authored boundary openings (contract § B1 Nr. 13).

A ``boundary_opening`` on ``map3d`` is an authored pass-through at the
LOCATION edge (a road crossing the cell). Since Etappe 3 of
``plan-3d-lod-und-betreten.md`` it is not only geometry any more: the avatar
step (``world_ops.move_avatar_step``) accepts an opening as a legitimate
crossing point —

- ENTERING is only possible across an edge that carries an authored opening
  (decision 2026-08-04: a location without one cannot be entered at all). The
  opening's room link routes the avatar; WITHOUT one the opening says nothing
  about the room and the arrival rule decides (``world.get_arrival_room_id``:
  the declared entry room, otherwise the ground);
- LEAVING across such an edge is allowed WITHOUT standing in the entry room,
  provided the avatar stands in the opening's linked room (the round trip of
  an opening entry — otherwise the avatar that walked in on the road could
  never walk back out on it). A roomless opening leads onto the GROUND, and
  since plan-grundflaeche.md the ground is a room like any other, so that is
  the room it lets out of — nobody is roomless any more.

The ``entry_room`` gate stays the gameplay authority for every other edge.

Pure functions over location dicts on purpose: no DB, no config (the one
import from ``app.models.world`` is the ground room's constant id, nothing
that reads) — the smoke ``scripts/smoke_boundary_entry.py`` derives its
expectations by hand and runs without a server or a world.

Tile rotation (contract v5.2 Nr. 15): ``map3d`` stores the openings in the
TEMPLATE orientation while ``tile_rotation`` turns the composed payload — and
with it the physical edges of the location. The step direction is such an
edge, so the stored edge letters are rotated here with the same N→E→S→W rule
the composer uses (``scene_recipe._TILE_EDGE_CW``), and ``at`` travels along
with them (``at → 1 − at`` on the E/W steps, the composer's rule verbatim) —
it is what gives an opening a POINT, which the travel engine needs to walk to
(``opening_world_point``). ``room`` is unaffected: the link names the same
room in every orientation.

An opening's world point takes one more turn: ``tile_rotation`` puts it into
the LOCATION's own frame, ``yaw_deg`` (§ A1.1) maps that frame into the world.
The two are different fields and both are applied, in that order.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

from app.models.world import GROUND_ROOM_ID

# World edge the avatar EXITS through for a step direction, and the target's
# edge it ENTERS through (the shared edge, seen from the other side).
EDGE_OF_DIRECTION = {"north": "N", "south": "S", "east": "E", "west": "W"}
OPPOSITE_EDGE = {"N": "S", "S": "N", "E": "W", "W": "E"}

# One clockwise 90° step — identical to scene_recipe._TILE_EDGE_CW/_FLIP.
_EDGE_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}
_EDGE_FLIP = {"N": False, "E": True, "S": False, "W": True}


def _rotated_openings(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The authored openings of a location as ``{edge, at, room}`` entries,
    rotated into the location's own orientation (``map3d.tile_rotation``).

    ``at`` is the position ALONG that edge as a fraction (left→right on N/S,
    top→bottom on E/W, the room-opening convention); a missing or unusable
    value degrades to the edge midpoint 0.5.
    """
    map3d = location.get("map3d") if isinstance(location, dict) else None
    if not isinstance(map3d, dict):
        return []
    try:
        steps = int(map3d.get("tile_rotation") or 0) // 90 % 4
    except (TypeError, ValueError):
        steps = 0
    out: List[Dict[str, Any]] = []
    for op in map3d.get("boundary_openings") or []:
        if not isinstance(op, dict):
            continue
        edge = str(op.get("edge") or "").upper()
        if edge not in _EDGE_CW:
            continue
        try:
            at = float(op.get("at"))
        except (TypeError, ValueError):
            at = 0.5
        if not math.isfinite(at):
            at = 0.5
        at = min(max(at, 0.0), 1.0)
        for _ in range(steps):
            if _EDGE_FLIP[edge]:
                at = 1.0 - at
            edge = _EDGE_CW[edge]
        out.append({"edge": edge, "at": at,
                    "room": str(op.get("room") or "").strip()})
    return out


def opening_world_points(location: Dict[str, Any]
                         ) -> List[Tuple[str, Tuple[float, float]]]:
    """Every authored opening as ``(edge, (x, z))`` in WORLD metres.

    Empty for an unplaced location or one without a scale anchor: without a
    centre and an edge length an opening has no point (``placed_footprint``).

    The point is the ``at`` position on that edge of the footprint square:
    in the local frame N is ``z = −w/2``, S ``z = +w/2``, W ``x = −w/2``, E
    ``x = +w/2``, and the free coordinate is ``(at − 0.5)·w``; ``yaw_deg``
    then maps local→world (§ A1.1). Hand-derived: a location at (50, 50),
    ``plan_width_m`` 10, yaw 0, opening N at 0.5 → local (0, −5) → (50, 45);
    the same location at yaw 90 → (45, 50).
    """
    from app.core.world_geometry import local_to_world, placed_footprint
    if not isinstance(location, dict):
        return []
    fp = placed_footprint(location)
    if fp is None:
        return []
    cx, cz, width, yaw = fp
    half = width / 2.0
    out: List[Tuple[str, Tuple[float, float]]] = []
    for op in _rotated_openings(location):
        edge, at = op["edge"], float(op["at"])
        free = (at - 0.5) * width
        if edge == "N":
            lx, lz = free, -half
        elif edge == "S":
            lx, lz = free, half
        elif edge == "W":
            lx, lz = -half, free
        else:                                   # "E"
            lx, lz = half, free
        x, z = local_to_world(lx, lz, cx, cz, yaw)
        out.append((edge, (round(x, 2), round(z, 2))))
    return out


def opening_world_point(location: Dict[str, Any],
                        edge: str) -> Optional[Tuple[float, float]]:
    """World point of the opening on ``edge``, or None when there is none.

    Several openings on the same edge (a road in and a gate) are legal; the
    FIRST authored one wins — a deterministic answer, and the caller that
    needs a specific one iterates :func:`opening_world_points` itself.
    """
    wanted = str(edge or "").upper()
    for op_edge, point in opening_world_points(location):
        if op_edge == wanted:
            return point
    return None


def _room_exists(location: Dict[str, Any], room_id: str) -> bool:
    return any(isinstance(r, dict) and r.get("id") == room_id
               for r in (location.get("rooms") or []))


def opening_entry_room(target: Dict[str, Any], entry_edge: str) -> str:
    """Room an authored opening on ``entry_edge`` (world letter) routes into.

    '' when the edge carries no opening with a valid room link — the opening
    then makes no statement and the caller falls back to
    ``world.get_arrival_room_id``. A room link that names no existing room is
    ignored (the sanitizer checks format, never existence).
    """
    for op in _rotated_openings(target):
        if op["edge"] == entry_edge and op["room"] \
                and _room_exists(target, op["room"]):
            return op["room"]
    return ""


def opening_on_edge(location: Dict[str, Any], edge: str) -> bool:
    """True when ``location`` carries an authored opening on the WORLD ``edge``.

    The room link answers "which room does it route into"; this answers "is
    this edge a way in at all". Since the strictness decision of 2026-08-04
    the second question stands on its own: an opening WITHOUT a room link is
    an entrance too, it just leaves the room to the arrival rule.
    """
    return any(op["edge"] == edge for op in _rotated_openings(location))


def has_entrance(location: Dict[str, Any]) -> bool:
    """True when the location carries at least one authored opening.

    The ONE source for both the step gate and the editor's warning: a location
    nobody can reach is reported, never silently repaired.
    """
    return bool(_rotated_openings(location))


def may_leave(current: Dict[str, Any], current_room: str, entry_room: str,
              exit_edge: str) -> bool:
    """Whether the avatar may leave ``current`` across ``exit_edge``.

    Three ways out, in this order:

    - across an authored opening on that edge, from the room it links to — an
      opening without a link leads onto the ground, so standing on the ground
      is what that one requires (the round trip of an opening entry);
    - from the entry room, the gameplay gate for every other edge;
    - from anywhere when the location declares no entry room.

    The middle rule is what keeps someone standing on the ground out of a
    trap: in a location without openings they may not walk out over any edge,
    but they can always enter the entry room first and leave from there.
    """
    for op in _rotated_openings(current):
        if op["edge"] != exit_edge:
            continue
        if (op["room"] or GROUND_ROOM_ID) == current_room:
            return True
    if not entry_room:
        return True
    return current_room == entry_room
