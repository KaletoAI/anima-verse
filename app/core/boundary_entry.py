"""Entry/exit decisions at authored boundary openings (contract § B1 Nr. 13).

A ``boundary_opening`` on ``map3d`` is an authored pass-through at the
LOCATION edge (a road crossing the cell). Since Etappe 3 of
``plan-3d-lod-und-betreten.md`` it is not only geometry any more: a location
change accepts an opening as a legitimate crossing point —

- ENTERING a location that HAS authored openings is only possible across one
  of them (strictness decision 2026-08-04) — its own openings ARE its ways in,
  and anything else is a wall. A location that draws NO opening at all is the
  other case and has a FREE boundary (decision E4 task 5, ``POST /play/pos``):
  it never said where its way in is, the mirror of ``may_leave``'s "no entry
  room = leave anywhere", and a painted square or a passable transit place
  cannot author an opening for every direction a walker may arrive from. The
  rule gates (``accessible_when``, access rules) apply either way — the free
  boundary drops the GEOMETRIC half of the gate, never the rules. The
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

AN EDGE IS AN INDEX (contract v6 Nr. 5). A location is a drawn polygon, so an
opening names the 0-based index of the boundary edge it sits on (edge i =
point i → point i+1) and ``at ∈ [0, 1]`` runs along that edge. The letters
N/E/S/W are gone, and so is the ``tile_rotation`` turn that used to rotate
them: a location faces the way its pin says (§ A1.1), and the boundary is
authored in that same local frame. The index is what identifies an opening
everywhere it travels — the journey remembers it as ``entry_edge``, the
walking gate matches it, and none of them re-derives a point of their own:
``world_geometry.polygon_edge_frame`` computes it once, for the scene payload
and for this module alike.

The worldmap row is the third consumer and reads the same function:
:func:`opening_world_frames` is what ``world_ops.build_worldmap_payload``
hands out as ``locations[].openings`` (§ A1.3), so the 3D client renders the
very pass-throughs the entry gate judges — it computes nothing about an
opening itself.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.models.world import GROUND_ROOM_ID


def _openings(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The authored openings of a location as ``{edge, at, room}`` entries.

    ``edge`` is the boundary EDGE INDEX, ``at`` the position along that edge
    as a fraction; a missing or unusable ``at`` degrades to the edge midpoint
    0.5 (the one degradation rule, applied in ``polygon_edge_frame``). An
    entry whose edge is not a plain index is dropped — the sanitizer already
    refuses those, so what is left here is a hand-posted blob.
    """
    map3d = location.get("map3d") if isinstance(location, dict) else None
    if not isinstance(map3d, dict):
        return []
    out: List[Dict[str, Any]] = []
    for op in map3d.get("boundary_openings") or []:
        if not isinstance(op, dict):
            continue
        edge = op.get("edge")
        if isinstance(edge, bool) or not isinstance(edge, int) or edge < 0:
            continue
        out.append({"edge": edge, "at": op.get("at"),
                    "room": str(op.get("room") or "").strip()})
    return out


def _r(value: float, digits: int = 2) -> float:
    """Round for the payload — and never emit ``-0.0``.

    ``+ 0.0`` is what normalizes it: IEEE-754 says ``-0.0 + 0.0 == +0.0``,
    while ``round()`` alone keeps the sign a normal of a west-running edge
    picks up.
    """
    return round(value, digits) + 0.0


def opening_world_frames(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every authored opening as ``{edge, at_world, inward, room}`` in WORLD
    metres — the finished pass-through, ready to be delivered.

    Empty for a location without an effective boundary (unplaced, or without
    a DRAWN outline — since 2026-08-19 a legacy ``plan_width_m`` is no shape
    any more): such a location has no area, so its openings have no point
    either.

    ONE geometry source: ``polygon_edge_frame`` puts the point AND the
    measured unit inward normal on the local boundary edge, ``local_to_world``
    maps the local frame into the world (§ A1.1). The normal is a DIRECTION,
    so it takes the same rotation about the ORIGIN instead of the full
    mapping. An index the boundary does not have is skipped, exactly like an
    unusable edge letter used to be. ``room`` is the authored link, '' when
    there is none — existence of that room is the entry gate's question
    (:func:`opening_entry_room`), not the geometry's.

    Hand-derived: a location at (50, 50) whose drawn boundary is the centred
    10 m square (−5,−5) (5,−5) (5,5) (−5,5) — edge 0 at 0.5 is local (0, −5)
    with inward (0, 1) → world (50, 45) / (0, 1), and the same location at
    yaw 90 → (45, 50) / (1, 0).
    """
    from app.core.world_geometry import (effective_boundary, local_to_world,
                                         polygon_edge_frame)
    if not isinstance(location, dict):
        return []
    eff = effective_boundary(location)
    if eff is None:
        return []
    cx, cz, yaw, pts = eff
    out: List[Dict[str, Any]] = []
    for op in _openings(location):
        frame = polygon_edge_frame(pts, op["edge"], op["at"])
        if frame is None:
            continue
        (lx, lz), (nx, nz) = frame
        x, z = local_to_world(lx, lz, cx, cz, yaw)
        wnx, wnz = local_to_world(nx, nz, 0.0, 0.0, yaw)
        out.append({"edge": int(op["edge"]),
                    "at_world": [_r(x), _r(z)],
                    "inward": [_r(wnx, 4), _r(wnz, 4)],
                    "room": op["room"]})
    return out


def opening_world_points(location: Dict[str, Any]
                         ) -> List[Tuple[int, Tuple[float, float]]]:
    """Every authored opening as ``(edge index, (x, z))`` in WORLD metres.

    The point half of :func:`opening_world_frames`, for the callers that
    measure a distance and care about nothing else (the entry/exit gate of
    ``POST /play/pos``). Same numbers, one derivation.
    """
    return [(f["edge"], (f["at_world"][0], f["at_world"][1]))
            for f in opening_world_frames(location)]


def opening_world_point(location: Dict[str, Any],
                        edge: Any) -> Optional[Tuple[float, float]]:
    """World point of the opening on boundary edge ``edge``, or None.

    Several openings on the same edge (a road in and a gate) are legal; the
    FIRST authored one wins — a deterministic answer, and the caller that
    needs a specific one iterates :func:`opening_world_points` itself.
    """
    for op_edge, point in opening_world_points(location):
        if op_edge == edge:
            return point
    return None


def _room_exists(location: Dict[str, Any], room_id: str) -> bool:
    return any(isinstance(r, dict) and r.get("id") == room_id
               for r in (location.get("rooms") or []))


def opening_entry_room(target: Dict[str, Any], entry_edge: Any) -> str:
    """Room an authored opening on boundary edge ``entry_edge`` routes into.

    '' when the edge carries no opening with a valid room link — the opening
    then makes no statement and the caller falls back to
    ``world.get_arrival_room_id``. A room link that names no existing room is
    ignored (the sanitizer checks format, never existence).
    """
    for op in _openings(target):
        if op["edge"] == entry_edge and op["room"] \
                and _room_exists(target, op["room"]):
            return op["room"]
    return ""


def opening_on_edge(location: Dict[str, Any], edge: Any) -> bool:
    """True when ``location`` carries an authored opening on boundary ``edge``.

    The room link answers "which room does it route into"; this answers "is
    this edge a way in at all". Since the strictness decision of 2026-08-04
    the second question stands on its own: an opening WITHOUT a room link is
    an entrance too, it just leaves the room to the arrival rule.
    """
    return any(op["edge"] == edge for op in _openings(location))


def has_entrance(location: Dict[str, Any]) -> bool:
    """True when the location carries at least one authored opening.

    NOT a reachability verdict — it has not been one since the free-boundary
    rule (E4 task 5): a location WITHOUT any opening is entered anywhere along
    its edge, one WITH openings only across them. The old step gate this
    function once served is gone with the grid, so the two consumers left are
    an editor hint (the boundary-openings section says which of the two modes
    the location is in) and the payload flag ``Location.has_entrance`` that
    carries it there. Nothing decides a crossing by it — that is
    ``POST /play/pos`` with ``opening_world_points`` / ``may_leave``.
    """
    return bool(_openings(location))


def may_leave(current: Dict[str, Any], current_room: str, entry_room: str,
              exit_edge: Any) -> bool:
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
    for op in _openings(current):
        if op["edge"] != exit_edge:
            continue
        if (op["room"] or GROUND_ROOM_ID) == current_room:
            return True
    if not entry_room:
        return True
    return current_room == entry_room
