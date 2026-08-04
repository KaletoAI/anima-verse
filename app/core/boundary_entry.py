"""Entry/exit decisions at authored boundary openings (contract § B1 Nr. 13).

A ``boundary_opening`` on ``map3d`` is an authored pass-through at the
LOCATION edge (a road crossing the cell). Since Etappe 3 of
``plan-3d-lod-und-betreten.md`` it is not only geometry any more: the avatar
step (``world_ops.move_avatar_step``) accepts an opening as a legitimate
crossing point —

- ENTERING is only possible across an edge that carries an authored opening
  (decision 2026-08-04: a location without one cannot be entered at all). The
  opening's room link routes the avatar; WITHOUT one the avatar lands on the
  location's ground, in no room;
- LEAVING across such an edge is allowed WITHOUT standing in the entry room,
  provided the avatar stands in the opening's linked room (the round trip of
  an opening entry — otherwise the avatar that walked in on the road could
  never walk back out on it) — or in NO room at all, the location's ground,
  which is where a roomless opening puts the avatar (decision 2026-08-04: an
  opening without a room link is an entrance too, just to no room in
  particular).

The ``entry_room`` gate stays the gameplay authority for every other edge.

Pure functions over location dicts on purpose: no DB, no config — the smoke
``scripts/smoke_boundary_entry.py`` derives its expectations by hand and runs
without a server or a world.

Tile rotation (contract v5.2 Nr. 15): ``map3d`` stores the openings in the
TEMPLATE orientation while ``tile_rotation`` turns the composed payload — and
with it the physical world edges. The step direction is a world edge, so the
stored edge letters are rotated here with the same N→E→S→W rule the composer
uses (``scene_recipe._TILE_EDGE_CW``). ``at``/``room`` are unaffected: the
gate has no sub-cell position (a step crosses the whole edge), and the room
link names the same room in every orientation.
"""
from typing import Any, Dict, List

# World edge the avatar EXITS through for a step direction, and the target's
# edge it ENTERS through (the shared edge, seen from the other side).
EDGE_OF_DIRECTION = {"north": "N", "south": "S", "east": "E", "west": "W"}
OPPOSITE_EDGE = {"N": "S", "S": "N", "E": "W", "W": "E"}

# One clockwise 90° step — identical to scene_recipe._TILE_EDGE_CW.
_EDGE_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}


def _rotated_openings(location: Dict[str, Any]) -> List[Dict[str, str]]:
    """The authored openings of a location as ``{edge, room}`` pairs, with the
    edge letter rotated into WORLD orientation (``map3d.tile_rotation``)."""
    map3d = location.get("map3d") if isinstance(location, dict) else None
    if not isinstance(map3d, dict):
        return []
    try:
        steps = int(map3d.get("tile_rotation") or 0) // 90 % 4
    except (TypeError, ValueError):
        steps = 0
    out: List[Dict[str, str]] = []
    for op in map3d.get("boundary_openings") or []:
        if not isinstance(op, dict):
            continue
        edge = str(op.get("edge") or "").upper()
        if edge not in _EDGE_CW:
            continue
        for _ in range(steps):
            edge = _EDGE_CW[edge]
        out.append({"edge": edge, "room": str(op.get("room") or "").strip()})
    return out


def _room_exists(location: Dict[str, Any], room_id: str) -> bool:
    return any(isinstance(r, dict) and r.get("id") == room_id
               for r in (location.get("rooms") or []))


def opening_entry_room(target: Dict[str, Any], entry_edge: str) -> str:
    """Room an authored opening on ``entry_edge`` (world letter) routes into.

    '' when the edge carries no opening with a valid room link — the caller
    falls back to ``get_entry_room_id``. A room link that names no existing
    room is ignored (the sanitizer checks format, never existence).
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
    the entrance to a location whose ground is not a room.
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

    - across an authored opening on that edge — from its linked room (the
      round trip of an opening entry) or from NO room at all (the location's
      ground, which is where a roomless opening puts the avatar);
    - from the entry room, the gameplay gate for every other edge;
    - from anywhere when the location declares no entry room.

    The middle rule is what keeps a roomless avatar out of a trap: in a
    location without openings it may not walk out over any edge, but it can
    always enter the entry room first and leave from there.
    """
    for op in _rotated_openings(current):
        if op["edge"] != exit_edge:
            continue
        if not current_room or op["room"] == current_room:
            return True
    if not entry_room:
        return True
    return current_room == entry_room
