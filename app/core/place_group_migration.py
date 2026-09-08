"""One-time rename of the place-type groups on stored markers
(plan-platztypen.md E1).

A place type used to name a piece of FURNITURE; it names a BODY SHAPE now::

    old:  seat  bed  floor  counter  stand
    new:  seat  lie  ground stand

``bed`` and ``floor`` both become ``lie`` — one lies on a mattress, on a couch
and on the ground, and it is the same posture with the same clip; the split
only ever existed because the deleted Mixamo ``sleep`` clip was animated on a
bed and needed its own root drop. ``counter`` becomes ``stand``: its single
pose (``working``) is a sitting one and moved to ``seat``, and what the group
pretended to be — "standing at a device, facing it" — is what a marker's
position and yaw already say. ``seat`` and ``stand`` keep their names.

Why a migration and not a fallback reader: ``scene_recipe`` skips a marker
whose group the catalog does not know **silently** (``continue``). Without
this pass every ``bed`` / ``floor`` / ``counter`` marker would disappear from
the scene and from the place inventory without an error anywhere — the symptom
is an empty room, not an exception.

Two marker homes are rewritten:

* ``locations[].rooms[].layout.markers[]`` in the ``locations.meta`` blob —
  the ground layout is a room with id ``__ground__``, so it is covered by the
  same walk;
* the prop sidecars under ``worlds/<world>/props/<id>/sidecar.json``: every
  entry of ``VARIANTS_KEY``, plus the legacy record-level ``markers`` list
  defensively (a sidecar from a pack authored before the field migration can
  still carry one when it lands).

``room_furnish.proposal`` rows are deliberately NOT touched: they live only
while a furnishing job is open, and ``furnish_needs.valid_marker`` drops an
unknown group at confirm time anyway — since plan-platztypen.md E2 it also
says so, in the log and in the confirmation dialog.

Idempotent through the ``world_kv`` flag, like every other one-time repair.
"""
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("place_group_migration")

_FLAG = "migration.place_groups_v1"

#: Stored group -> its name in the new vocabulary. Groups that keep their name
#: are absent, so a lookup miss means "nothing to do".
RENAMES: Dict[str, str] = {
    "bed": "lie",
    "floor": "lie",
    "counter": "stand",
}


def rename_place_groups(markers: Any) -> int:
    """Rewrite the ``group`` of every marker in ``markers`` IN PLACE and
    return how many were changed.

    Pure: no I/O, no world state. Used by the boot migration below and by the
    content-pack import, which installs markers long after the flag is set —
    a pack exported before this rename would otherwise bring ``bed`` markers
    back into a migrated world, where they are swallowed without a word.
    """
    changed = 0
    for m in (markers or []):
        if not isinstance(m, dict):
            continue
        new = RENAMES.get(str(m.get("group") or "").strip().lower())
        if new:
            m["group"] = new
            changed += 1
    return changed


def _rename_world_markers() -> int:
    """Room and ground layouts in the ``locations.meta`` blob."""
    from app.models.world import _load_world_data, _save_world_data
    data = _load_world_data()
    changed = 0
    for loc in data.get("locations", []) or []:
        if not isinstance(loc, dict):
            continue
        for room in loc.get("rooms", []) or []:
            if not isinstance(room, dict):
                continue
            lay = room.get("layout")
            if isinstance(lay, dict):
                changed += rename_place_groups(lay.get("markers"))
    if changed:
        _save_world_data(data)
    return changed


def _rename_prop_markers() -> Tuple[int, int]:
    """Every variant's marker list in every prop sidecar of this world.

    ``(renamed, failed)`` — a sidecar that could not be written is COUNTED,
    not swallowed: the run must not be marked done while a prop still carries
    a retired group, because nothing would ever look at it again and
    ``scene_recipe`` drops such a marker without a word.
    """
    from app.core import props as prop_store
    changed = 0
    failed = 0
    for pid in prop_store._all_prop_ids():
        meta = prop_store.read_sidecar(pid)
        if not isinstance(meta, dict):
            continue
        # The record-level list has had no reader since the field migration;
        # it is renamed anyway so an old sidecar that lands here later cannot
        # carry a dead group back onto a variant.
        n = rename_place_groups(meta.get(prop_store.MARKERS_KEY))
        for v in meta.get(prop_store.VARIANTS_KEY) or []:
            if isinstance(v, dict):
                n += rename_place_groups(v.get(prop_store.MARKERS_KEY))
        if n:
            try:
                prop_store._write_sidecar(pid, meta)
            except (OSError, ValueError) as e:
                logger.warning("Prop %s: place-group rename could not be "
                               "written: %s", pid, e)
                failed += 1
                continue
            changed += n
    return changed, failed


def migrate_place_groups_once() -> Optional[Dict[str, int]]:
    """Rename ``bed``/``floor``/``counter`` on every stored marker, once per
    world. Returns the counts for the boot log, or None when the migration
    had already run.
    """
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(_FLAG):
        return None
    rooms = _rename_world_markers()
    props, failed = _rename_prop_markers()
    stats = {"room_markers": rooms, "prop_markers": props}
    if failed:
        # Not done. The room half is idempotent and the prop half only
        # rewrites what still carries a retired group, so the next boot
        # simply tries again — which is the whole point of not stamping the
        # flag over a partial run.
        stats["props_failed"] = failed
        logger.warning("place-group migration incomplete: %d prop sidecar(s) "
                       "could not be written — retrying on the next boot",
                       failed)
    else:
        set_world_setting(_FLAG, "1")
    if any(stats.values()):
        # The place inventory is cached per location; without this the old
        # groups would be served until the TTL expires.
        try:
            from app.core import places
            places.invalidate()
        except Exception as e:                        # pragma: no cover
            logger.warning("place cache could not be invalidated: %s", e)
        logger.info("place-group migration (bed/floor -> lie, counter -> "
                    "stand): %s", stats)
    return stats

