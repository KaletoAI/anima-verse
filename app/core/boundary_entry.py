"""Entry/exit decisions at plot gates and building outside doors.

Entry semantics:

- ``map3d.boundary_openings`` are GATES in a FENCE around a plot. A location
  with non-empty ``boundary_openings`` is FENCED (:func:`fenced`): one enters
  and leaves the plot only through its gates (within :data:`GATE_TOLERANCE_M`).
  A location without them has a freely walkable boundary.
- A building is entered and left through ANY of its level-0 OUTSIDE DOORS
  (:func:`outside_door_frames`, :func:`at_door`), into / out of the room that
  door belongs to.
- ``entry_room`` is ONLY the arrival room for travel / teleport / scheduler —
  never an exit rule.
- No-trap rule: an UNFENCED location with zero level-0 outside doors lets one
  leave from any room.
- ``boundary_openings`` carry no ``room`` field; the room always comes from the
  point (:func:`room_at_point`) or the door.

Pure functions over location dicts and composed scene dicts: no DB, no config
(the only model imports are the reserved ground/floor room id constants).
Composing the scene is the caller's job (``world_ops`` cached location block).
"""
import math
from typing import Any, Dict, List, Optional, Tuple

from app.models.world import GROUND_ROOM_ID, floor_room_id

#: Distance (metres) from a plot gate point that counts as crossing through it.
GATE_TOLERANCE_M = 1.5
#: Extra slack (metres) on each side of a door's half-width along the wall.
DOOR_ALONG_PAD_M = 0.3
#: Distance (metres) perpendicular to a door plane that counts as at the door.
DOOR_ACROSS_M = 1.5


def _openings(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The authored plot gates of a location as ``{edge, at}`` entries.

    ``edge`` is the 0-based boundary edge index, ``at`` the fraction along that
    edge (degrades to 0.5 in ``polygon_edge_frame`` when missing/unusable).
    Entries whose edge is not a non-negative int are skipped.
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
        out.append({"edge": edge, "at": op.get("at")})
    return out


def _r(value: float, digits: int = 2) -> float:
    """Round for payloads and normalize ``-0.0`` to ``0.0``."""
    return round(value, digits) + 0.0


def fenced(location: Dict[str, Any]) -> bool:
    """True when the location has at least one authored plot gate (fenced)."""
    return bool(_openings(location))


def opening_world_frames(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every authored plot gate as ``{edge, at_world, inward}`` in WORLD metres.

    Empty for a location without an effective drawn boundary. Uses
    ``world_geometry.polygon_edge_frame`` and ``local_to_world`` so the
    worldmap payload and the walking gate always agree.
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
                    "inward": [_r(wnx, 4), _r(wnz, 4)]})
    return out


def opening_world_points(location: Dict[str, Any]
                         ) -> List[Tuple[int, Tuple[float, float]]]:
    """Every authored plot gate as ``(edge index, (x, z))`` in WORLD metres."""
    return [(f["edge"], (f["at_world"][0], f["at_world"][1]))
            for f in opening_world_frames(location)]


def opening_world_point(location: Dict[str, Any],
                        edge: Any) -> Optional[Tuple[float, float]]:
    """World point of the first plot gate on boundary edge ``edge``, or None."""
    for op_edge, point in opening_world_points(location):
        if op_edge == edge:
            return point
    return None


def _location_pose(location: Any) -> Optional[Tuple[float, float, float]]:
    """``(pos_x, pos_z, yaw_deg)`` of a placed location, or None."""
    if not isinstance(location, dict):
        return None
    px, pz = location.get("pos_x"), location.get("pos_z")
    if px is None or pz is None:
        return None
    try:
        return float(px), float(pz), float(location.get("yaw_deg") or 0.0)
    except (TypeError, ValueError):
        return None


def outside_door_frames(location: Dict[str, Any],
                        scene: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Level-0 outside doors of ``location`` in WORLD metres.

    Each entry is ``{"at_world": [x, z], "outward": [nx, nz], "width_m": w,
    "room": str, "level": 0, "hull": bool}``. Returns ``[]`` when ``scene`` is
    None or ``location`` is unplaced.
    """
    from app.core.scene_recipe import _door_outward
    from app.core.world_geometry import local_to_world
    if not isinstance(scene, dict):
        return []
    pose = _location_pose(location)
    if pose is None:
        return []
    cx, cz, yaw = pose
    out: List[Dict[str, Any]] = []
    for d in scene.get("doorways") or []:
        if not isinstance(d, dict) or not d.get("outside"):
            continue
        if int(d.get("level") or 0) != 0:
            continue
        at_local = d.get("at_world")
        if not isinstance(at_local, (list, tuple)) or len(at_local) < 2:
            continue
        hull = bool(d.get("hull"))
        raw_norm = d.get("outward_normal")
        if not (isinstance(raw_norm, (list, tuple)) and len(raw_norm) >= 2):
            if not isinstance(d.get("along"), (list, tuple)) or len(d["along"]) < 2:
                continue
            raw_norm = _door_outward(d)
        nx, nz = float(raw_norm[0]), float(raw_norm[1])
        rooms = d.get("rooms") or []
        room_id = str(rooms[0]) if rooms else ""
        wx, wz = local_to_world(float(at_local[0]), float(at_local[1]),
                                cx, cz, yaw)
        wnx, wnz = local_to_world(nx, nz, 0.0, 0.0, yaw)
        out.append({
            "at_world": [_r(wx), _r(wz)],
            "outward": [_r(wnx, 4), _r(wnz, 4)],
            "width_m": _r(float(d.get("width_m") or 0.0), 3),
            "room": room_id,
            "level": 0,
            "hull": hull,
        })
    return out


def entry_geometry(location: Dict[str, Any],
                   scene: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """World-space entry geometry of ``location`` from its composed ``scene``.

    Returns ``{"doors": [...], "rooms": [...], "contour": [...]}`` where:
    - ``doors`` are the level-0 outside doors (:func:`outside_door_frames`),
    - ``rooms`` are every level-0 room block of ``scene`` as
      ``{"room": id, "outline": [[x, z], ...], "walled": bool}`` in world metres,
    - ``contour`` is the level-0 building outline (``scene_recipe._outline_world``)
      in world metres, or ``[]``.
    """
    from app.core.scene_recipe import _outline_world
    from app.core.world_geometry import local_to_world
    pose = _location_pose(location)
    if pose is None:
        return {"doors": [], "rooms": [], "contour": []}
    cx, cz, yaw = pose
    doors = outside_door_frames(location, scene)
    rooms: List[Dict[str, Any]] = []
    if isinstance(scene, dict):
        for rb in scene.get("rooms") or []:
            if not isinstance(rb, dict):
                continue
            if int(rb.get("level") or 0) != 0:
                continue
            outline = rb.get("outline") or []
            if len(outline) < 3:
                continue
            rid = str(rb.get("room_id") or "")
            world_pts = []
            for pt in outline:
                wx, wz = local_to_world(float(pt[0]), float(pt[1]),
                                        cx, cz, yaw)
                world_pts.append([_r(wx, 4), _r(wz, 4)])
            rooms.append({
                "room": rid,
                "outline": world_pts,
                "walled": not room_is_open(location, rid),
            })
    map3d = location.get("map3d") if isinstance(location, dict) else None
    local_contour = _outline_world(map3d, 0) if isinstance(map3d, dict) else []
    contour: List[List[float]] = []
    for pt in local_contour:
        wx, wz = local_to_world(float(pt[0]), float(pt[1]), cx, cz, yaw)
        contour.append([_r(wx, 4), _r(wz, 4)])
    return {"doors": doors, "rooms": rooms, "contour": contour}


def at_door(door: Dict[str, Any], x: float, z: float) -> bool:
    """True when ``(x, z)`` lies within the crossing box of ``door``."""
    cx, cz = door["at_world"]
    out_x, out_z = door["outward"]
    dx, dz = x - cx, z - cz
    along = dx * (-out_z) + dz * out_x
    across = dx * out_x + dz * out_z
    half_w = float(door.get("width_m") or 0.0) / 2.0
    return (abs(along) <= half_w + DOOR_ALONG_PAD_M
            and abs(across) <= DOOR_ACROSS_M)


def at_gate(location: Dict[str, Any], x: float, z: float) -> bool:
    """True when ``(x, z)`` lies within :data:`GATE_TOLERANCE_M` of a plot gate."""
    for _edge, (ox, oz) in opening_world_points(location):
        if math.hypot(ox - x, oz - z) <= GATE_TOLERANCE_M:
            return True
    return False


def room_at_point(geo: Optional[Dict[str, Any]], x: float, z: float) -> str:
    """Room of ``geo`` containing ``(x, z)`` on level 0.

    First matching level-0 room outline wins; inside the building contour but
    in no room returns ``floor_room_id(0)`` (``"__floor__0"``); otherwise
    :data:`GROUND_ROOM_ID` (``"__ground__"``).
    """
    from app.core.world_geometry import point_in_polygon
    if isinstance(geo, dict):
        for r in geo.get("rooms") or []:
            if point_in_polygon(x, z, r.get("outline")):
                return str(r.get("room") or GROUND_ROOM_ID)
        contour = geo.get("contour") or []
        if len(contour) >= 3 and point_in_polygon(x, z, contour):
            return floor_room_id(0)
    return GROUND_ROOM_ID


def may_enter(location: Dict[str, Any], geo: Optional[Dict[str, Any]],
              x: float, z: float) -> Tuple[bool, str, str]:
    """Whether ``(x, z)`` may enter ``location``, returning ``(ok, reason, room)``.

    - Fenced and not at a gate -> ``(False, "no_opening", "")``.
    - Room is derived from ``(x, z)`` (:func:`room_at_point`). If that room is
      walled and no outside door of that room satisfies :func:`at_door` ->
      ``(False, "no_door", "")``.
    - Otherwise ``(True, "", room)``.
    """
    if fenced(location) and not at_gate(location, x, z):
        return False, "no_opening", ""
    room = room_at_point(geo, x, z)
    if not room_is_open(location, room):
        doors = (geo.get("doors") or []) if isinstance(geo, dict) else []
        if not any(d.get("room") == room and at_door(d, x, z) for d in doors):
            return False, "no_door", ""
    return True, "", room


def may_leave(location: Dict[str, Any], geo: Optional[Dict[str, Any]],
              current_room: str, x: float, z: float) -> Tuple[bool, str]:
    """Whether an avatar in ``current_room`` may leave ``location`` via ``(x, z)``.

    - Fenced and not at a gate -> ``(False, "leave_blocked")``.
    - Walled ``current_room`` requires being at one of its outside doors, EXCEPT
      under the no-trap rule (zero level-0 outside doors on the location — once
      any fence gate check has passed, a character cannot be trapped in a room
      with no outside door at all).
    - The walled-room rule is skipped when ``current_room`` has no drawn
      layout: it has no walls or doors to pass, so a character a teleport or
      the scheduler put into a layout-less entry room is never trapped (at a
      fenced plot it still leaves through a gate).
    - ``entry_room`` plays no role.
    """
    if fenced(location) and not at_gate(location, x, z):
        return False, "leave_blocked"
    if (current_room and not room_is_open(location, current_room)
            and _has_layout(location, current_room)):
        doors = (geo.get("doors") or []) if isinstance(geo, dict) else []
        if doors:
            if not any(d.get("room") == current_room and at_door(d, x, z)
                       for d in doors):
                return False, "leave_blocked"
    return True, ""


def _has_layout(location: Dict[str, Any], room_id: str) -> bool:
    """Whether ``room_id`` is a room of ``location`` with a drawn layout."""
    for room in (location.get("rooms") if isinstance(location, dict) else None) or []:
        if isinstance(room, dict) and str(room.get("id") or "").strip() == room_id:
            return isinstance(room.get("layout"), dict) and bool(room["layout"])
    return False


def room_is_open(location: Dict[str, Any], room_id: str) -> bool:
    """Whether nothing stands between ``room_id`` and the plot outside:
    the ground, or a room of ``location`` without walls (``no_walls`` or
    ``always_visible``). A room the location does not list counts as walled."""
    if room_id == GROUND_ROOM_ID:
        return True
    for room in (location.get("rooms") if isinstance(location, dict) else None) or []:
        if isinstance(room, dict) and str(room.get("id") or "").strip() == room_id:
            lay = room.get("layout")
            lay = lay if isinstance(lay, dict) else {}
            return bool(lay.get("no_walls") or lay.get("always_visible"))
    return False
