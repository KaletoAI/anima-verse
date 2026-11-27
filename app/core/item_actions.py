"""World-item action registry, execution, and approach-point geometry.

Combines core world-item actions (``look``, ``take``, ``read``) with package
contributors registered under the ``item.actions`` hook capability, and
computes server-side approach points for standing next to a placed room item.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import hooks
from app.core.i18n import t
from app.core.item_placement import (
    _circle_hits_rect,
    _edge_distance,
    _to_room,
    room_geometry,
)
from app.core.item_reading import has_pages
from app.core.log import get_logger
from app.core.world_geometry import point_in_polygon

logger = get_logger("item_actions")

CORE_ACTIONS: Tuple[str, ...] = ("look", "take", "read")
_CORE_ACTION_SET = frozenset(CORE_ACTIONS)
_APPROACH_OFFSET_M = 0.45
_FIGURE_RADIUS_M = 0.25
_WALL_CLEAR_M = 0.25
_APPROACH_DIRECTIONS = 16
_EPS = 1e-9


def _r4(value: float) -> float:
    out = round(float(value), 4)
    return 0.0 if out == 0 else out


def _provider_source(fn: Callable) -> str:
    owner = getattr(fn, "__owner__", None)
    if isinstance(owner, str) and owner.strip():
        return owner.strip()
    mod = getattr(fn, "__module__", "")
    if isinstance(mod, str) and mod.strip():
        return mod.strip()
    return "package"


def _collect_actions(
    viewer: str,
    item: Dict[str, Any],
    placement: Dict[str, Any],
    lang: str = "de",
) -> List[Dict[str, Any]]:
    """Collect core and provider actions, retaining internal runner metadata."""
    actions: List[Dict[str, Any]] = [
        {"id": "look", "label": t("Look", lang), "source": "core"},
    ]
    if item.get("portable", True) is not False:
        actions.append({"id": "take", "label": t("Take", lang), "source": "core"})
    if has_pages(item):
        actions.append({"id": "read", "label": t("Read", lang), "source": "core"})

    taken: set[str] = set(_CORE_ACTION_SET)
    for fn in hooks.get_providers("item.actions"):
        try:
            raw_entries = fn(viewer, item, placement)
        except Exception as exc:  # noqa: BLE001
            logger.warning("item.actions provider %r failed: %s", fn, exc)
            continue
        if not isinstance(raw_entries, list):
            logger.warning("item.actions provider %r returned non-list: %r", fn, type(raw_entries).__name__)
            continue
        source = _provider_source(fn)
        default_runner = getattr(fn, "run", None)
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            action_id = str(entry.get("id") or "").strip()
            if not action_id:
                continue
            if action_id in taken:
                logger.warning(
                    "item.actions provider %r returned duplicate or core action id %r; dropping",
                    source,
                    action_id,
                )
                continue
            taken.add(action_id)
            label = str(entry.get("label") or action_id)
            runner = entry.get("run") if callable(entry.get("run")) else (
                default_runner if callable(default_runner) else None
            )
            actions.append({
                "id": action_id,
                "label": label,
                "source": source,
                "_runner": runner,
            })

    return actions


def actions_for(
    viewer: str,
    item: Dict[str, Any],
    placement: Dict[str, Any],
    lang: str = "de",
) -> List[Dict[str, str]]:
    """Return the public action list ``[{"id", "label", "source"}]`` for a world item."""
    return [
        {"id": a["id"], "label": a["label"], "source": a["source"]}
        for a in _collect_actions(viewer, item, placement, lang=lang)
    ]


def run_action(
    viewer: str,
    item: Dict[str, Any],
    placement: Dict[str, Any],
    action_id: str,
    location_id: str,
    room_id: str,
) -> Dict[str, Any]:
    """Execute a package-contributed world-item action.

    Raises:
        ValueError: when ``action_id`` is a core action (call the core route).
        LookupError: when no provider supplies ``action_id``.
        RuntimeError: when the provider has no runner or raises during execution.
    """
    aid = str(action_id or "").strip()
    if aid in _CORE_ACTION_SET:
        raise ValueError("use the core route")

    matched = next(
        (a for a in _collect_actions(viewer, item, placement) if a["id"] == aid),
        None,
    )
    if matched is None:
        raise LookupError(f"Unknown action: {aid}")

    runner = matched.get("_runner")
    if not callable(runner):
        raise RuntimeError(f"Action '{aid}' has no runner")

    item_id = str(item.get("id") or placement.get("item_id") or "")
    try:
        result = runner(viewer, item_id, location_id, room_id)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(str(exc) or exc.__class__.__name__) from exc

    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return {"result": result}


def _prop_edge_midpoints(prop: Dict[str, Any]) -> List[Tuple[float, float]]:
    px, pz = float(prop["at"][0]), float(prop["at"][1])
    pyaw = float(prop.get("yaw") or 0.0)
    hw = max(0.0, float(prop.get("width_m") or 0.0)) / 2.0
    hd = max(0.0, float(prop.get("depth_m") or 0.0)) / 2.0
    local_mids = ((hw, 0.0), (-hw, 0.0), (0.0, hd), (0.0, -hd))
    return [_to_room(px, pz, pyaw, dx, dz) for dx, dz in local_mids]


def approach_point(
    location: Dict[str, Any],
    room_id: str,
    item_id: str,
    anchor: Dict[str, Any],
    size_m: float,
) -> Optional[List[float]]:
    """Compute a free standing point ``[x, z]`` next to an anchored item.

    Samples 16 directions at radius ``0.45 + size_m / 2`` around the item's
    anchor (or, when the item rests ``on`` a prop, around the prop's footprint
    edge midpoint nearest the item, falling back to the next-nearest edges if
    the nearest edge is blocked). Returns ``None`` when no valid point exists.
    """
    geo = room_geometry(location, room_id)
    if geo is None:
        return None
    outline = geo.get("outline") or []
    if len(outline) < 3:
        return None
    if not isinstance(anchor, dict):
        return None
    at = anchor.get("at")
    if not isinstance(at, (list, tuple)) or len(at) < 2:
        return None

    ax, az = float(at[0]), float(at[1])
    props = geo.get("props") or []
    on_id = str(anchor.get("on") or "")

    centres: List[Tuple[float, float]] = [(ax, az)]
    if on_id:
        support = next((p for p in props if str(p.get("id") or "") == on_id), None)
        if support is not None:
            mids = _prop_edge_midpoints(support)
            mids.sort(key=lambda pt: math.hypot(pt[0] - ax, pt[1] - az))
            centres = mids

    radius = _APPROACH_OFFSET_M + max(0.0, float(size_m)) / 2.0
    order = sorted(
        range(_APPROACH_DIRECTIONS),
        key=lambda k: hashlib.sha256(f"{item_id}:{k}".encode()).hexdigest(),
    )

    for cx, cz in centres:
        for k in order:
            angle = math.radians(k * (360.0 / _APPROACH_DIRECTIONS))
            x = cx + radius * math.sin(angle)
            z = cz + radius * math.cos(angle)
            if not point_in_polygon(x, z, outline):
                continue
            if _edge_distance(x, z, outline) < _WALL_CLEAR_M - _EPS:
                continue
            if any(_circle_hits_rect(x, z, _FIGURE_RADIUS_M, prop, 0.0) for prop in props):
                continue
            return [_r4(x), _r4(z)]

    return None
