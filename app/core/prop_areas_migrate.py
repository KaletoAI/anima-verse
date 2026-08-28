"""Boot migration: hand the picture-area facts from the PROP to its MODEL
FILES (spec-bild-props-v2.md E1, ruling V0, 2026-08-28).

Why this exists
---------------
Until 2026-08-28 a prop carried ONE area list (``areas``), ONE door-leaf box
(``leaf_bbox``), ONE orientation fix (``rotation``), ONE set of pane defaults
(``area_defaults``) and the stamps of the last detection run (``areas_error``,
``areas_run_at``) — although every model variant is its own img2mesh
generation. Measured on a real door prop: one variant had other axes and no
leaf node, so the prop-wide leaf box was geometrically meaningless for it.

Those facts belong to the MODEL FILE now (``props.file_areas`` /
``props.set_file_areas``), the defaults to the VARIANT entry, and no reader
looks at the prop-level keys any more — so the legacy value has to be moved
once or every existing frame and door prop would come back unsplit and
unturned on the first boot. The legacy value can only ever have described the
PRIMARY variant's active full mesh, and that is where it goes:

* the primary's active FULL file gets ``areas``, ``leaf_bbox``, ``rotation``
  and ``areas_run_at``; a legacy ``areas_error`` that is the no-leaf NOTE
  (``props.NO_LEAF_NOTE``) becomes ``areas_warning`` — a run that worked —
  and any other text stays ``areas_error``;
* the primary's LOW file, when this store reduced it itself (sidecar
  ``source: lod``), gets ``inherits_from`` plus copies of the three facts, so
  ``file_areas(low)`` answers with the full file's values;
* a VARIANT COPY (model sidecar ``source: variant-copy`` — a byte copy of the
  primary's mesh, hence the same axes) gets the ``rotation`` too, and its own
  ``areas`` / ``leaf_bbox`` from the ``.areas.json`` companion that travelled
  with the copy (that companion IS a reading of that very file); its low file
  inherits likewise;
* a variant that is its OWN generation gets nothing: the legacy value never
  described its mesh;
* ``area_defaults`` moves onto the PRIMARY variant's entry, checked against
  the areas its file now names — an entry that already carries defaults keeps
  them (a repair never overwrites an explicit answer);
* the prop sidecar then LOSES all six keys. ``key_areas`` stays prop-wide
  (ruling V2: it is the wish for the next generation, not a measurement).

Idempotent by CONTENT: a sidecar without a legacy key is left alone, so the
second boot moves nothing — no ``world_kv`` flag, no DB. Per world, like every
prop repair: props are FILES under ``worlds/<world>/props/``.

A legacy prop WITHOUT a model file has nowhere to put the values; its keys
are dropped and nothing else is written. Nothing here raises for one broken
prop — the boot log gets a warning and the next prop is repaired.
"""

from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("prop_areas_migrate")

#: The prop-level keys that moved (the six of spec-bild-props-v2.md E1).
LEGACY_KEYS = ("areas", "leaf_bbox", "rotation", "area_defaults",
               "areas_error", "areas_run_at")


def _inherit_low(gallery, full, fields: Dict[str, Any]) -> None:
    """The variant's store-built low file inherits from ``full``."""
    from app.core.model_store import read_sidecar, write_sidecar
    from app.core.props import (INHERITS_FROM_KEY, LOW_TIER,
                                _INHERITED_AREAS_KEYS)
    low = gallery.find(LOW_TIER, fallback=False)
    if not low or low == full:
        return
    meta = read_sidecar(low)
    if meta.get("source") != "lod":
        return
    meta[INHERITS_FROM_KEY] = full.name
    for key in _INHERITED_AREAS_KEYS:
        if fields.get(key) is not None:
            meta[key] = fields[key]
        else:
            meta.pop(key, None)
    write_sidecar(low, meta)


def _companion_reading(full) -> Dict[str, Any]:
    """``{areas, leaf_bbox}`` a copy's ``.areas.json`` states — ``{}`` when
    there is none or it is unreadable (no reading, nothing written)."""
    from app.core.props import (read_areas_sidecar, sanitize_areas,
                                sanitize_leaf_bbox)
    record = read_areas_sidecar(full)
    if not isinstance(record.get("areas"), list):
        return {}
    try:
        areas = sanitize_areas([{k: v for k, v in a.items() if k != "edges"}
                                for a in record["areas"] if isinstance(a, dict)])
        leaf = sanitize_leaf_bbox(record.get("leaf_bbox"))
    except ValueError:
        return {}
    return {"areas": areas, "leaf_bbox": leaf}


def move_prop_areas(prop_id: str) -> bool:
    """Move ONE prop's legacy area fields onto its files. True when the
    sidecar changed (i.e. a legacy key was there to move)."""
    from app.core import props as store
    meta = store.read_sidecar(prop_id)
    if not meta or not any(k in meta for k in LEGACY_KEYS):
        return False

    # Lenient reads: a hand-edited legacy value is dropped, never a crash.
    try:
        areas = store.sanitize_areas(meta.get("areas")) \
            if isinstance(meta.get("areas"), list) else []
    except ValueError:
        areas = []
    try:
        leaf = store.sanitize_leaf_bbox(meta.get("leaf_bbox"))
    except ValueError:
        leaf = None
    rotation = store._sanitize_rotation(meta.get("rotation"))
    run_at = str(meta.get("areas_run_at") or "")
    error = str(meta.get("areas_error") or "")
    warning = error if error == store.NO_LEAF_NOTE else ""
    error = "" if warning else error
    raw_defaults = meta.get("area_defaults")

    entries = store._variant_list(meta)
    primary = store._effective_indices(entries)[0]
    gallery = store.model_gallery(prop_id, primary)
    full = gallery.find(store.DEFAULT_TIER, fallback=False) if gallery else None
    if full:
        fields: Dict[str, Any] = {
            "areas": areas, "leaf_bbox": leaf,
            "rotation": rotation if any(rotation.values()) else None,
            "areas_run_at": run_at or None,
            "areas_error": error or None,
            "areas_warning": warning or None,
        }
        store.set_file_areas(full, **fields)
        _inherit_low(gallery, full, fields)
        # The pane defaults name areas of THAT file: checked against it.
        if raw_defaults and not entries[primary].get(store.AREA_DEFAULTS_KEY):
            try:
                clean = store.sanitize_area_defaults(raw_defaults, areas)
            except ValueError as e:
                logger.warning("Prop %s: legacy area_defaults dropped (%s)",
                               prop_id, e)
                clean = {}
            if clean:
                entries[primary][store.AREA_DEFAULTS_KEY] = clean
    # Byte copies of the primary's mesh share its axes — and carry their own
    # reading beside them.
    if any(rotation.values()) or full:
        for idx, entry in enumerate(entries):
            if idx == primary:
                continue
            g = store.model_gallery(prop_id, idx)
            f = g.find(store.DEFAULT_TIER, fallback=False) if g else None
            if not f or store.read_model_sidecar(f).get("source") != "variant-copy":
                continue
            reading = _companion_reading(f)
            fields = {"rotation": rotation if any(rotation.values()) else None,
                      **reading}
            store.set_file_areas(f, **fields)
            _inherit_low(g, f, {"rotation": fields["rotation"],
                                "areas": reading.get("areas"),
                                "leaf_bbox": reading.get("leaf_bbox")})

    meta[store.VARIANTS_KEY] = entries
    for key in LEGACY_KEYS:
        meta.pop(key, None)
    store._write_sidecar(prop_id, meta)
    return True


def migrate_prop_areas_to_files() -> Dict[str, int]:
    """Walk every prop of THIS world and move the legacy fields. Returns
    ``{"props": <seen>, "moved": <changed>}``; a prop whose repair fails is
    logged and skipped, the others are still repaired."""
    from app.core.props import _all_prop_ids
    seen = moved = 0
    for pid in _all_prop_ids():
        seen += 1
        try:
            if move_prop_areas(pid):
                moved += 1
        except Exception as e:                              # noqa: BLE001
            logger.warning("Prop %s: area fields could not be moved onto its "
                           "files: %s", pid, e)
    if moved:
        logger.info("Picture areas, leaf box and orientation belong to the "
                    "MODEL FILE now, not to the prop: %s of %s prop(s) handed "
                    "their values to the primary variant's active mesh; the "
                    "master records lost the keys.", moved, seen)
    return {"props": seen, "moved": moved}
