"""One-time move of markers from clip KINDS to PLACE TYPES (plan-posen-plaetze.md § 9).

A marker used to say "clip `sit` plays here"; it now says "here is a seat" —
a group of the pose catalog (``pose_catalog.get_groups()``) — and carries a
stable id, so a deleted neighbour no longer renumbers it and a character can
hold it by name. Placements (``layout.props[]``) get the same stable id, since
a prop marker is addressed as ``"<placement.id>/<marker.id>"``.

Three marker homes are rewritten: ``layout.markers[]`` of every room (ground
layout included), ``layout.props[]`` (ids only) and the prop sidecars — the
record-level ``markers`` list AND each entry of ``VARIANTS_KEY``. Idempotent
via the world_kv flag; no reader keeps a fallback for ``animation``.

Kind → group follows the numbers the deleted ``FIGURE_ROOT_DROP`` table held:
``sit`` 0.314 = seat, ``sleep`` 0.631 = bed, ``lie``/``laying`` 0.051 = floor
(the catalog's own ``lying`` pose sits in ``floor`` too); every other kind
touched at its root and is a standing spot.
"""
import secrets
from typing import Any, Dict

from app.core.log import get_logger

logger = get_logger("places_migration")

_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_FLAG = "migration.places_v1"


def new_place_id() -> str:
    """8 chars of base32 — short enough for a chip, random enough per world."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def group_for_kind(kind: str) -> str:
    """The place type a legacy clip kind implies — the same drop the old
    root-drop table gave that kind."""
    k = (kind or "").strip().lower()
    if k.startswith("sit-ground"):
        return "floor"
    if k.startswith("sit"):
        return "seat"
    if k.startswith("sleep"):
        return "bed"
    if k.startswith(("lie", "lay")):
        return "floor"
    return "stand"


def _migrate_marker_list(markers: Any) -> int:
    changed = 0
    for m in (markers or []):
        if not isinstance(m, dict):
            continue
        if "animation" in m:
            m["group"] = group_for_kind(m.pop("animation"))
            changed += 1
        if not m.get("id"):
            m["id"] = new_place_id()
            changed += 1
    return changed


def migrate_places_once() -> Dict[str, int]:
    """Room markers, placements and prop-variant markers: kind → group, ids.
    Idempotent via world_kv. Returns counts for the boot log."""
    from app.core import props as prop_store
    from app.models.world import (_load_world_data, _save_world_data,
                                  get_world_setting, set_world_setting)
    if get_world_setting(_FLAG):
        return {}
    stats = {"room_markers": 0, "placements": 0, "prop_markers": 0}
    data = _load_world_data()
    for loc in data.get("locations", []):
        for room in loc.get("rooms", []) or []:
            lay = room.get("layout")
            if not isinstance(lay, dict):
                continue
            stats["room_markers"] += _migrate_marker_list(lay.get("markers"))
            for p in lay.get("props") or []:
                if isinstance(p, dict) and not p.get("id"):
                    p["id"] = new_place_id()
                    stats["placements"] += 1
    _save_world_data(data)
    for pid in prop_store._all_prop_ids():
        meta = prop_store.read_sidecar(pid)
        if not isinstance(meta, dict):
            continue
        n = _migrate_marker_list(meta.get("markers"))
        for v in meta.get(prop_store.VARIANTS_KEY) or []:
            if isinstance(v, dict):
                n += _migrate_marker_list(v.get("markers"))
        if n:
            prop_store._write_sidecar(pid, meta)
            stats["prop_markers"] += n
    set_world_setting(_FLAG, "1")
    logger.info("places migration: %s", stats)
    return stats
