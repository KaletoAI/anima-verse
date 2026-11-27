"""Pure placement solver for world-placeable items in a room.

Decides where an item lies in a room's location-local metre frame:
1. On a free spot of a prop flagged with a storage surface (e.g. a table).
2. Otherwise on a free floor spot near a wall, clear of all props.

Deterministic per ``item_id`` and overlap-free against child props and other
placed items. Only :func:`room_geometry` and :func:`occupied_by_items` touch
storage/recipes; :func:`compute_anchor` is pure math.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict

from app.core.world_geometry import point_in_polygon, point_segment_distance

_SURFACE_INSET_M = 0.05
_SURFACE_STEP_M = 0.05
_FLOOR_STEP_M = 0.10
_FLOOR_WALL_CLEAR_M = 0.05
_FLOOR_WALL_MAX_M = 1.0
_FLOOR_PROP_CLEAR_M = 0.10
_EPS = 1e-9


class Anchor(TypedDict):
    """Stored placement of an item in location-local metres."""

    at: List[float]
    y: float
    yaw: float
    on: str


class ItemSpot(TypedDict):
    """Circular footprint of an already-placed item."""

    at: List[float]
    r: float


class ChildGeo(TypedDict):
    """Footprint rectangle of a prop standing on a support."""

    at: List[float]
    yaw: float
    width_m: float
    depth_m: float


class PropGeo(TypedDict):
    """Placed prop geometry relevant to item placement."""

    id: str
    at: List[float]
    yaw: float
    width_m: float
    depth_m: float
    surface_y: Optional[float]
    children: List[ChildGeo]


class RoomGeo(TypedDict):
    """Minimal room geometry consumed by :func:`compute_anchor`."""

    outline: List[List[float]]
    props: List[PropGeo]


def _r4(value: float) -> float:
    out = round(float(value), 4)
    return out if out != 0 else 0.0


def _to_room(px: float, pz: float, yaw: float,
             dx: float, dz: float) -> Tuple[float, float]:
    """Map a local offset (dx along width, dz along depth) into room metres."""
    rad = math.radians(yaw)
    cos_y, sin_y = math.cos(rad), math.sin(rad)
    return (
        px + dx * cos_y + dz * sin_y,
        pz - dx * sin_y + dz * cos_y,
    )


def _to_local(px: float, pz: float, yaw: float,
              x: float, z: float) -> Tuple[float, float]:
    """Inverse of :func:`_to_room` (transpose rotation around (px, pz))."""
    rad = math.radians(yaw)
    cos_y, sin_y = math.cos(rad), math.sin(rad)
    ux, uz = x - px, z - pz
    return (
        ux * cos_y - uz * sin_y,
        ux * sin_y + uz * cos_y,
    )


def _circle_hits_rect(x: float, z: float, radius: float,
                      rect: Dict[str, Any], clearance: float = 0.0) -> bool:
    """Return True when a circle at (x, z) overlaps a rotated rectangle."""
    at = rect["at"]
    lx, lz = _to_local(float(at[0]), float(at[1]), float(rect.get("yaw") or 0.0), x, z)
    hw = max(0.0, float(rect.get("width_m") or 0.0)) / 2.0
    hd = max(0.0, float(rect.get("depth_m") or 0.0)) / 2.0
    cx = max(-hw, min(hw, lx))
    cz = max(-hd, min(hd, lz))
    return math.hypot(lx - cx, lz - cz) < (radius + clearance - _EPS)


def _edge_distance(x: float, z: float, outline: Sequence[Sequence[float]]) -> float:
    """Shortest distance from (x, z) to any edge of the closed outline polygon."""
    n = len(outline)
    if n < 2:
        return math.inf
    best = math.inf
    for i in range(n):
        a = outline[i]
        b = outline[(i + 1) % n]
        dist = point_segment_distance(
            x, z, float(a[0]), float(a[1]), float(b[0]), float(b[1])
        )
        if dist < best:
            best = dist
    return best


def _hits_occupied(x: float, z: float, radius: float,
                   occupied: Sequence[ItemSpot]) -> bool:
    for spot in occupied:
        at = spot["at"]
        sr = float(spot["r"])
        if math.hypot(x - float(at[0]), z - float(at[1])) < (radius + sr - _EPS):
            return True
    return False


def _grid_sort_key(item_id: str, i: int, j: int) -> str:
    return hashlib.sha256(f"{item_id}:{i},{j}".encode()).hexdigest()


def room_geometry(location: Dict[str, Any], room_id: str) -> Optional[RoomGeo]:
    """Compose a room read-only and extract its placement geometry.

    Returns ``None`` when the room does not exist, has no recipe/layout, or its
    outline has fewer than 3 points.
    """
    from app.core import props as prop_store
    from app.core.room_recipe import compose_recipe

    rooms = [r for r in (location.get("rooms") or []) if isinstance(r, dict)]
    target_id = str(room_id or "")
    room = next((r for r in rooms if str(r.get("id") or "") == target_id), None)
    if room is None:
        return None

    siblings = [r for r in rooms if r is not room]
    recipe = compose_recipe(room, siblings, map3d=location.get("map3d"), read_only=True)
    if not recipe:
        return None

    raw_outline = recipe.get("outline") or []
    if len(raw_outline) < 3:
        return None
    outline = [[float(p[0]), float(p[1])] for p in raw_outline]

    records: Dict[str, Optional[Dict[str, Any]]] = {}
    props_out: List[PropGeo] = []
    by_id: Dict[str, PropGeo] = {}
    pending_children: List[Tuple[str, ChildGeo]] = []

    for placement in (recipe.get("placements") or []):
        if not isinstance(placement, dict):
            continue
        dims = placement.get("dims")
        if not isinstance(dims, dict):
            continue
        at_raw = placement.get("at")
        if not isinstance(at_raw, (list, tuple)) or len(at_raw) < 2:
            continue

        prop_id = str(placement.get("prop_id") or "")
        if prop_id not in records:
            records[prop_id] = prop_store.get_prop(prop_id, read_only=True) if prop_id else None
        record = records[prop_id]

        variant = placement.get("variant")
        surface_h = prop_store.prop_surface(record, variant) if record else None
        if surface_h is not None:
            ground_offset = float(placement.get("ground_offset_m") or 0.0)
            offset_y = float(placement.get("offset_y") or 0.0)
            surface_y: Optional[float] = ground_offset + offset_y + surface_h
        else:
            surface_y = None

        pid = str(placement.get("id") or "")
        at = [float(at_raw[0]), float(at_raw[1])]
        yaw = float(placement.get("yaw") or 0.0)
        width_m = float(dims.get("width_m") or 0.0)
        depth_m = float(dims.get("depth_m") or 0.0)

        entry: PropGeo = {
            "id": pid,
            "at": at,
            "yaw": yaw,
            "width_m": width_m,
            "depth_m": depth_m,
            "surface_y": surface_y,
            "children": [],
        }
        props_out.append(entry)
        if pid:
            by_id.setdefault(pid, entry)

        on_id = str(placement.get("on") or "")
        if on_id:
            pending_children.append((
                on_id,
                {
                    "at": at,
                    "yaw": yaw,
                    "width_m": width_m,
                    "depth_m": depth_m,
                },
            ))

    for parent_id, child in pending_children:
        parent = by_id.get(parent_id)
        if parent is not None:
            parent["children"].append(child)

    return {"outline": outline, "props": props_out}


def occupied_by_items(room: Dict[str, Any], except_item_id: str) -> List[ItemSpot]:
    """Return circular footprints for all anchored items in ``room`` except ``except_item_id``."""
    from app.models.inventory import get_item, item_world_size

    spots: List[ItemSpot] = []
    for entry in (room.get("items") or []):
        if not isinstance(entry, dict):
            continue
        iid = str(entry.get("item_id") or "")
        if not iid or iid == except_item_id:
            continue
        anchor = entry.get("anchor")
        if not isinstance(anchor, dict):
            continue
        at = anchor.get("at")
        if not isinstance(at, (list, tuple)) or len(at) < 2:
            continue
        item = get_item(iid)
        if item is None:
            continue
        spots.append({
            "at": [float(at[0]), float(at[1])],
            "r": item_world_size(item) / 2.0,
        })
    return spots


def _axis_samples(half_extent: float, step: float) -> List[Tuple[int, float]]:
    if half_extent <= 0.0:
        return [(0, 0.0)]
    out: List[Tuple[int, float]] = []
    i = 0
    while True:
        val = -half_extent + step * i
        if val > half_extent + _EPS:
            break
        out.append((i, min(val, half_extent)))
        i += 1
    return out


def _try_surface_pass(item_id: str, radius: float, yaw_item: float,
                      start: int, props: Sequence[PropGeo],
                      occupied: Sequence[ItemSpot]) -> Optional[Anchor]:
    candidates = sorted(
        (p for p in props if p.get("surface_y") is not None),
        key=lambda p: str(p.get("id") or ""),
    )
    if not candidates:
        return None

    offset = start % len(candidates)
    ordered = candidates[offset:] + candidates[:offset]

    for support in ordered:
        hw = float(support["width_m"]) / 2.0 - (_SURFACE_INSET_M + radius)
        hd = float(support["depth_m"]) / 2.0 - (_SURFACE_INSET_M + radius)
        if hw < -_EPS or hd < -_EPS:
            continue
        hw = max(0.0, hw)
        hd = max(0.0, hd)

        xs = _axis_samples(hw, _SURFACE_STEP_M)
        zs = _axis_samples(hd, _SURFACE_STEP_M)
        grid = [
            (_grid_sort_key(item_id, i, j), dx, dz)
            for i, dx in xs
            for j, dz in zs
        ]
        grid.sort(key=lambda t: t[0])

        px, pz = float(support["at"][0]), float(support["at"][1])
        pyaw = float(support.get("yaw") or 0.0)
        children = support.get("children") or []

        for _, dx, dz in grid:
            x, z = _to_room(px, pz, pyaw, dx, dz)
            rx, rz = _r4(x), _r4(z)
            if any(_circle_hits_rect(rx, rz, radius, child, 0.0) for child in children):
                continue
            if _hits_occupied(rx, rz, radius, occupied):
                continue
            return {
                "at": [rx, rz],
                "y": _r4(float(support["surface_y"])),
                "yaw": yaw_item,
                "on": str(support["id"]),
            }
    return None


def _try_floor_pass(item_id: str, radius: float, yaw_item: float,
                    outline: Sequence[Sequence[float]],
                    props: Sequence[PropGeo],
                    occupied: Sequence[ItemSpot]) -> Optional[Anchor]:
    if len(outline) < 3:
        return None

    min_x = min(float(p[0]) for p in outline)
    max_x = max(float(p[0]) for p in outline)
    min_z = min(float(p[1]) for p in outline)
    max_z = max(float(p[1]) for p in outline)

    min_edge = radius + _FLOOR_WALL_CLEAR_M
    candidates: List[Tuple[str, float, float]] = []

    i = 0
    while True:
        gx = min_x + _FLOOR_STEP_M * i
        if gx > max_x + _EPS:
            break
        rx = _r4(min(gx, max_x))
        j = 0
        while True:
            gz = min_z + _FLOOR_STEP_M * j
            if gz > max_z + _EPS:
                break
            rz = _r4(min(gz, max_z))
            if point_in_polygon(rx, rz, outline):
                d_edge = _edge_distance(rx, rz, outline)
                if d_edge >= min_edge - _EPS and d_edge <= _FLOOR_WALL_MAX_M + _EPS:
                    candidates.append((_grid_sort_key(item_id, i, j), rx, rz))
            j += 1
        i += 1

    candidates.sort(key=lambda t: t[0])

    for _, rx, rz in candidates:
        if any(_circle_hits_rect(rx, rz, radius, prop, _FLOOR_PROP_CLEAR_M) for prop in props):
            continue
        if _hits_occupied(rx, rz, radius, occupied):
            continue
        return {
            "at": [rx, rz],
            "y": 0.0,
            "yaw": yaw_item,
            "on": "",
        }
    return None


def compute_anchor(item_id: str, size_m: float, geo: RoomGeo,
                   occupied: Sequence[ItemSpot]) -> Optional[Anchor]:
    """Compute a deterministic, overlap-free anchor for ``item_id`` in ``geo``."""
    digest = hashlib.sha256(item_id.encode()).hexdigest()
    start = int(digest[:8], 16)
    yaw_item = float(int(digest[8:12], 16) % 360)
    radius = max(0.0, float(size_m)) / 2.0

    props = geo.get("props") or []
    anchor = _try_surface_pass(item_id, radius, yaw_item, start, props, occupied)
    if anchor is not None:
        return anchor

    outline = geo.get("outline") or []
    return _try_floor_pass(item_id, radius, yaw_item, outline, props, occupied)


def repair_anchors(location: Dict[str, Any]) -> int:
    """Repair invalid item anchors inside ``location`` in place.

    Does not acquire any lock and does not persist to the DB — callers hold
    ``world_write_lock`` (e.g. ``world._upsert_locations``). Computes room
    geometry at most once per room, and only for rooms with at least one
    anchored entry of a placeable item.

    Returns the number of entries whose anchor was updated or dropped.
    """
    from app.models.inventory import get_item, item_world_size

    changed = 0
    item_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    for room in (location.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        room_items = room.get("items") or []
        if not room_items:
            continue

        candidates: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
        for entry in room_items:
            if not isinstance(entry, dict) or not isinstance(entry.get("anchor"), dict):
                continue
            iid = str(entry.get("item_id") or "")
            if not iid:
                continue
            if iid not in item_cache:
                item_cache[iid] = get_item(iid)
            item = item_cache[iid]
            if item and item.get("world_placeable"):
                candidates.append((entry, iid, item))

        if not candidates:
            continue

        geo = room_geometry(location, str(room.get("id") or ""))
        if geo is None:
            for entry, _, _ in candidates:
                entry.pop("anchor", None)
                changed += 1
            continue

        props_by_id = {
            str(p.get("id") or ""): p
            for p in (geo.get("props") or [])
            if p.get("id")
        }
        prop_ids = set(props_by_id)
        outline = geo.get("outline") or []

        for entry, iid, item in candidates:
            anchor = entry["anchor"]
            on_id = str(anchor.get("on") or "")
            on_missing = bool(on_id) and (on_id not in prop_ids)

            at = anchor.get("at")
            at_inside = False
            if isinstance(at, (list, tuple)) and len(at) >= 2:
                try:
                    at_inside = point_in_polygon(float(at[0]), float(at[1]), outline)
                except (TypeError, ValueError):
                    at_inside = False

            # The anchor also no longer holds when its support moved, changed
            # height or lost its surface flag, or when furniture now stands on a
            # floor item.
            moved = False
            if at_inside and not on_missing:
                ax, az = float(at[0]), float(at[1])
                support = props_by_id.get(on_id) if on_id else None
                if support is not None:
                    sy = support.get("surface_y")
                    moved = (sy is None
                             or abs(float(anchor.get("y") or 0.0) - float(sy)) > 1e-3
                             or not _circle_hits_rect(ax, az, 1e-6, support))
                elif not on_id:
                    r = item_world_size(item) / 2.0
                    moved = any(_circle_hits_rect(ax, az, r, p) for p in (geo.get("props") or []))

            if not (on_missing or not at_inside or moved):
                continue

            occupied = occupied_by_items(room, iid)
            new_anchor = compute_anchor(iid, item_world_size(item), geo, occupied)
            if new_anchor is not None:
                entry["anchor"] = new_anchor
            else:
                entry.pop("anchor", None)
            changed += 1

    return changed


def backfill_anchors(item_id: Optional[str] = None) -> int:
    """Compute and store anchors for placeable room entries that lack one.

    When ``item_id`` is given, only entries for that item are considered.
    Runs under ``world_write_lock``, reads the world fresh, and persists only
    changed locations via ``upsert_location(loc, sync_world=False)``.
    Returns the number of anchored entries.
    """
    from app.models.inventory import get_item, item_world_size
    from app.models.world import _load_world_data, upsert_location, world_write_lock

    target_id = str(item_id) if item_id is not None else None
    item_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    if target_id is not None:
        target_item = get_item(target_id)
        if not target_item or not target_item.get("world_placeable"):
            return 0
        item_cache[target_id] = target_item

    anchored = 0
    with world_write_lock:
        for loc in (_load_world_data().get("locations") or []):
            if not isinstance(loc, dict):
                continue
            loc_changed = False
            for room in (loc.get("rooms") or []):
                if not isinstance(room, dict):
                    continue
                room_items = room.get("items") or []
                if not room_items:
                    continue

                missing: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
                for entry in room_items:
                    if not isinstance(entry, dict) or entry.get("anchor"):
                        continue
                    iid = str(entry.get("item_id") or "")
                    if not iid:
                        continue
                    if target_id is not None and iid != target_id:
                        continue
                    if iid not in item_cache:
                        item_cache[iid] = get_item(iid)
                    item = item_cache[iid]
                    if item and item.get("world_placeable"):
                        missing.append((entry, iid, item))

                if not missing:
                    continue

                geo = room_geometry(loc, str(room.get("id") or ""))
                if geo is None:
                    continue

                for entry, iid, item in missing:
                    occupied = occupied_by_items(room, iid)
                    new_anchor = compute_anchor(iid, item_world_size(item), geo, occupied)
                    if new_anchor is not None:
                        entry["anchor"] = new_anchor
                        anchored += 1
                        loc_changed = True

            if loc_changed:
                upsert_location(loc, sync_world=False)

    return anchored
