"""Boot migration: hand size, subject, ground offset and markers from the PROP
to its MODEL VARIANTS.

Why this exists
---------------
Until 2026-08-25 a prop carried ONE size (``width_m`` / ``depth_m`` /
``height_m`` + ``dims_estimated``), ONE generation subject (``description``),
ONE ground offset (``ground_offset_m``) and ONE marker list (``markers``), and
a model variant could override the first two. A variant is a whole VERSION of
the object, though — a sapling beside the grown pine, a broken chair beside the
whole one — and all four of those differ per version: the seat marker of a
chair is a fraction of THAT mesh's bounding box, and a trunk without a root
ball is buried by an amount that belongs to that bake.

So the five fields live on the variant now, and on nothing else. The prop
record lost them without a fallback reader (``props._variant_list`` no longer
looks at the master record for any of them), which means dropping them without
moving them would reset every prop in every world to a 1 m cube with no
markers on the first boot. The value the old rule would have used is therefore
written out once, per world:

* every variant that does NOT author a field of its own inherits the prop's
  value for it — that is exactly what the old resolution rule answered, so
  nothing moves on screen;
* a variant that DOES author one keeps it: its key is the author's, and a
  repair must never overwrite an explicit answer (there can be one on the first
  run — the per-variant dim and description overrides shipped 2026-08-24);
* a variant that inherited its dims keeps the prop's ``dims_estimated``, one
  that authored its own is marked NOT estimated: a number an admin typed is
  never redistributed from the mesh proportions again;
* the legacy single ``size_m`` is folded into three dims on the way (the job
  ``props._materialize_dims`` used to do on the next write, which is gone with
  the prop-level dims);
* the master record then LOSES all six keys, so nothing is left that looks like
  it still decides something.

Idempotent through a ``world_kv`` marker, like every other one-time repair (the
``terrain_relief_migration`` pattern), and per world: props are FILES under
``worlds/<world>/props/``, so the world that boots is the one that gets
repaired.

RUNS AFTER ``props.migrate_marker_surface_once``, which reads the pre-move
shape (prop-level markers measured against prop-level dims). Both are one-time
repairs; a world that still needs that one still has its props in the shape it
expects, and once this migration has run there is nothing left there to find.

The same per-prop transform is also the INGEST normaliser: a content pack
authored before this change installs a whole ``props/<id>/`` directory, sidecar
included, long after the boot migration ran. ``normalize_prop_sidecar`` puts
one such sidecar into the current shape at import time — not a fallback reader,
a write.
"""

from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("prop_field_migration")

_GUARD_KEY = "world.migration.prop_fields_to_variants_v1"


def _prop_dims(meta: Dict[str, Any]) -> Dict[str, float]:
    """The three metres the OLD rule would have reported for this prop.

    The stored trio when it is complete and usable; otherwise the legacy single
    ``size_m`` spread over the mesh proportions — the very arithmetic
    ``props._materialize_dims`` ran on the next write of such a record.
    """
    from app.core.props import (DEFAULT_DIM_M, DIM_KEYS, _coerce_dim_m,
                                _dims_from_size)
    complete = True
    for key in DIM_KEYS:
        try:
            if float(meta.get(key)) <= 0:
                complete = False
                break
        except (TypeError, ValueError):
            complete = False
            break
    if complete:
        return {key: _coerce_dim_m(meta.get(key)) for key in DIM_KEYS}
    return _dims_from_size(meta.get("size_m", DEFAULT_DIM_M), meta.get("bbox"),
                           meta.get("rotation"))


def move_fields_to_variants(meta: Dict[str, Any]) -> bool:
    """Move the five prop-level fields onto the variant entries, IN PLACE.

    Returns True when the record changed — i.e. when something prop-level was
    still there to move. Pure dict work: no file is read or written here, which
    is what lets the boot pass, the import path and the smoke share it.
    """
    from app.core.props import (DESCRIPTION_KEY, DIM_KEYS, DIMS_ESTIMATED_KEY,
                                GROUND_OFFSET_KEY, MARKERS_KEY, MODEL_STEM,
                                VARIANTS_KEY, _coerce_description,
                                _coerce_ground_offset_m, _coerce_dim_m,
                                sanitize_markers)
    if not isinstance(meta, dict):
        return False
    stale = [k for k in (*DIM_KEYS, DIMS_ESTIMATED_KEY, DESCRIPTION_KEY,
                         GROUND_OFFSET_KEY, MARKERS_KEY, "size_m")
             if k in meta]
    if not stale:
        return False

    dims = _prop_dims(meta)
    estimated = bool(meta.get(DIMS_ESTIMATED_KEY))
    description = _coerce_description(meta.get(DESCRIPTION_KEY))
    offset = _coerce_ground_offset_m(meta.get(GROUND_OFFSET_KEY))
    markers = sanitize_markers(meta.get(MARKERS_KEY))

    raw = meta.get(VARIANTS_KEY)
    entries: List[Dict[str, Any]] = [e for e in raw if isinstance(e, dict)] \
        if isinstance(raw, list) else []
    if not entries:
        # A prop that predates the variant list has exactly one variant, on the
        # historic stem — the same answer `props._variant_list` gives.
        entries = [{"stem": MODEL_STEM, "active": True}]

    for entry in entries:
        # DIMS: an entry that authored ANY of the three authored its size, so
        # it is not an estimate; the keys it did not author are filled from the
        # prop, which is exactly what the old override rule resolved to.
        authored = any(_coerce_dim_m(entry.get(k), 0.0) > 0 for k in DIM_KEYS)
        for key in DIM_KEYS:
            if _coerce_dim_m(entry.get(key), 0.0) <= 0:
                entry[key] = dims[key]
        entry[DIMS_ESTIMATED_KEY] = False if authored else estimated
        # The other three follow the "absence is the statement" law: only a
        # value that says something is written, and an entry that already says
        # something keeps its own.
        if description and not _coerce_description(entry.get(DESCRIPTION_KEY)):
            entry[DESCRIPTION_KEY] = description
        if offset is not None \
                and _coerce_ground_offset_m(entry.get(GROUND_OFFSET_KEY)) is None:
            entry[GROUND_OFFSET_KEY] = offset
        if markers and not sanitize_markers(entry.get(MARKERS_KEY)):
            entry[MARKERS_KEY] = [dict(m) for m in markers]

    meta[VARIANTS_KEY] = entries
    for key in stale:
        meta.pop(key, None)
    return True


def normalize_prop_sidecar(prop_id: str) -> bool:
    """Read ONE prop's sidecar, move the fields and write it back. True when
    the file changed. Used by the boot pass and by the content-pack import,
    which installs whole prop directories long after boot."""
    from app.core.props import _write_sidecar, read_sidecar
    meta = read_sidecar(prop_id)
    if not meta or not move_fields_to_variants(meta):
        return False
    try:
        _write_sidecar(prop_id, meta)
    except (OSError, ValueError) as e:
        logger.warning("Prop %s: field migration could not be written: %s",
                       prop_id, e)
        return False
    return True


def move_prop_fields() -> Dict[str, int]:
    """Walk every prop of THIS world and move the five fields. Returns
    ``{"props": <seen>, "moved": <changed>}``."""
    from app.core.props import _all_prop_ids
    seen = moved = 0
    for pid in _all_prop_ids():
        seen += 1
        if normalize_prop_sidecar(pid):
            moved += 1
    return {"props": seen, "moved": moved}


def migrate_prop_fields_once() -> Optional[Dict[str, int]]:
    """Run :func:`move_prop_fields` once per world, guarded by ``world_kv``.

    Returns None when the migration had already run (or could not run) — the
    caller only logs.
    """
    try:
        from app.models.world import get_world_setting, set_world_setting
        if get_world_setting(_GUARD_KEY):
            return None
        stats = move_prop_fields()
        set_world_setting(_GUARD_KEY, "1")
        if stats["moved"]:
            logger.info(
                "Size, description, ground offset and markers belong to the "
                "MODEL VARIANT now, not to the prop: %s of %s prop(s) handed "
                "their values to every variant that authored none; the master "
                "records lost the keys.",
                stats["moved"], stats["props"])
        return stats
    except Exception as e:
        logger.warning("Prop field migration failed: %s", e)
        return None
