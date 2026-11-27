"""Per-viewer world-placeable items payload and ETag computation.

Pure read path for ``GET /play/locations/{location_id}/items``: never writes
discovery rows, notifications or anchors, and never composes room recipes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.core.i18n import localized
from app.core.item_mesh import mesh_meta
from app.core.item_reading import has_pages
from app.models.inventory import (
    discovered_by,
    get_item,
    item_world_size,
    placement_seen_by,
)

# Fallback core action list used until Task 8 introduces item_actions.actions_for.
CORE_ACTIONS_FALLBACK: tuple[str, ...] = ("take", "look")


def _actions(item: Dict[str, Any]) -> List[str]:
    """Return the actions offered for a world-placeable item."""
    if has_pages(item):
        return ["take", "read", "look"]
    return list(CORE_ACTIONS_FALLBACK)


def _ready_mesh_version(item_id: str) -> Optional[str]:
    """Return the mesh version whenever a GLB exists.

    ``mesh_meta`` carries ``version`` only when ``model.glb`` is on disk; a
    regeneration in progress (or one that failed) keeps the previous GLB, which
    stays the one to draw instead of falling back to the image card.
    """
    meta = mesh_meta(item_id)
    if not meta:
        return None
    version = meta.get("version")
    return str(version) if version else None


def items_etag(location: Dict[str, Any], viewer: str, lang: str) -> str:
    """Compute a sha256 hex ETag over the location's room items and viewer visibility.

    Cheap input fingerprint: performs no recipe composition and no DB writes.
    """
    loc_id = str((location or {}).get("id") or "")
    rooms_fp: List[Dict[str, Any]] = []
    distinct_ids: set[str] = set()

    for room in (location or {}).get("rooms") or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("id") or "")
        entries_fp: List[Dict[str, Any]] = []
        for entry in room.get("items") or []:
            if not isinstance(entry, dict):
                continue
            iid = str(entry.get("item_id") or "").strip()
            if not iid:
                continue
            distinct_ids.add(iid)
            hidden = bool(entry.get("hidden", False))
            discovered = (bool(viewer) and viewer in discovered_by(loc_id, room_id, iid)) if hidden else False
            entries_fp.append({
                "item_id": iid,
                "quantity": int(entry.get("quantity", 1) or 1),
                "anchor": entry.get("anchor"),
                "hidden": hidden,
                "discovered": discovered,
            })
        rooms_fp.append({"room_id": room_id, "entries": entries_fp})

    items_fp: Dict[str, Any] = {}
    for iid in sorted(distinct_ids):
        item = get_item(iid)
        if not item:
            items_fp[iid] = None
            continue
        items_fp[iid] = {
            "name": localized(item, "name", lang) or item.get("name"),
            "world_size_m": item.get("world_size_m"),
            "world_placeable": bool(item.get("world_placeable")),
            "image": item.get("image") or None,
            "mesh_version": _ready_mesh_version(iid),
        }

    canonical = json.dumps(
        {
            "location_id": loc_id,
            "lang": lang,
            "rooms": rooms_fp,
            "items": items_fp,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_items_payload(location: Dict[str, Any], viewer: str, lang: str) -> Dict[str, Any]:
    """Build the per-viewer payload of visible, anchored, world-placeable items."""
    loc_id = str((location or {}).get("id") or "")
    item_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    mesh_cache: Dict[str, Optional[str]] = {}
    out_items: List[Dict[str, Any]] = []

    for room in (location or {}).get("rooms") or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("id") or "")
        for entry in room.get("items") or []:
            if not isinstance(entry, dict):
                continue
            anchor = entry.get("anchor")
            if not isinstance(anchor, dict):
                continue
            at = anchor.get("at")
            if not isinstance(at, (list, tuple)) or len(at) < 2:
                continue
            iid = str(entry.get("item_id") or "").strip()
            if not iid:
                continue
            if iid not in item_cache:
                item_cache[iid] = get_item(iid)
            item = item_cache[iid]
            if not item or not item.get("world_placeable"):
                continue
            if not placement_seen_by(viewer, loc_id, room_id, entry):
                continue
            if iid not in mesh_cache:
                mesh_cache[iid] = _ready_mesh_version(iid)
            version = mesh_cache[iid]
            quoted_id = quote(iid, safe="")
            out_items.append({
                "item_id": iid,
                "room_id": room_id,
                "name": localized(item, "name", lang) or iid,
                "quantity": int(entry.get("quantity", 1) or 1),
                "at": list(at),
                "y": anchor.get("y"),
                "yaw": anchor.get("yaw"),
                "size_m": item_world_size(item),
                "model_url": f"/inventory/items/{quoted_id}/model?v={version}" if version else None,
                "model_version": version,
                "image_url": f"/inventory/items/{quoted_id}/image" if item.get("image") else None,
                "actions": _actions(item),
            })

    return {"location_id": loc_id, "items": out_items}
