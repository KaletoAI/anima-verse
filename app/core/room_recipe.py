"""Room recipe (plan-room-props.md) — ONE endpoint for a furnished room.

The raw data already flows to the client through the location payload
(``rooms[].layout`` with outline/surfaces/openings/props); the recipe adds
the COMPOSED conveniences so the client renders without re-deriving them:

- ``outline`` in ABSOLUTE plate fractions (the drawn hull or the implicit
  rectangle — no bbox-local mechanics on the client side),
- ``openings`` normalized to polygon edge INDICES (legacy letters converted,
  S/W flip their ``at`` against the clockwise edge direction),
- ``placements`` joined with each prop's real dims + model url (REAL-SIZE
  rule: a placement never scales a prop — its own dims × the plan factor k
  do), and
- ``prop_markers`` as fully composed transforms RELATIVE to their placement
  anchor: the object-local marker ran through orientation fix → real-size
  scale → placement yaw, anchored exactly like the mesh (oriented-box
  bottom centre on the placement point). The client adds
  ``placement world position + offset_m × k`` — one multiply, no marker
  math.

Coordinate frames: XZ positions are fractions of the 8 × 8 m reference
square (like ``layout.x/y`` and ``map3d.outline``); every length that ends
in ``_m`` is REAL metres — the client converts with its k = 8/plan_width_m.
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
    if facing is not None:
        out["facing"] = _r((float(facing) - float(placement_yaw or 0)) % 360, 1)
    return out


def compose_recipe(room: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The full recipe of ONE room, or None when it has no layout."""
    lay = room.get("layout")
    if not isinstance(lay, dict):
        return None
    try:
        x = float(lay["x"])
        y = float(lay["y"])
        w = float(lay["w"])
        d = float(lay["d"])
    except (KeyError, TypeError, ValueError):
        return None

    pts = lay.get("outline") or _UNIT_SQUARE
    outline = [[_r(x + float(u) * w), _r(y + float(v) * d)] for u, v in pts]

    openings = [_normalize_opening(op) for op in (lay.get("openings") or [])
                if isinstance(op, dict)]

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
            entry["model_url"] = prop.get("model_url") or ""
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
    if lay.get("exit"):
        payload["exit"] = lay["exit"]
    if lay.get("markers"):
        payload["markers"] = lay["markers"]
    if lay.get("rotation") is not None:
        payload["rotation"] = lay["rotation"]
    # Change detection without polling the whole payload chain: the client
    # re-fetches when the signature moves (layout edits AND prop sidecar
    # edits both move it).
    payload["signature"] = hashlib.md5(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload
