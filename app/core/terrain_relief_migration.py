"""Boot migration: hand the micro-relief from the terrain KIND to the AREA.

Why this exists
---------------
From 2026-08-13 to 2026-08-23 the micro-relief (``relief_amplitude_m`` /
``relief_wave_m``, § A16.2) was a property of the terrain TYPE: painting a kind
that carried hills made the world heightfield bumpy wherever that kind lay. It
is a property of the painted AREA now — "how bumpy is this ground" is a
statement about one shape somebody drew, and a kind-level number made every
meadow in a world exactly as bumpy as every other one.

The kind lost the two keys without a fallback reader (``terrain_types``
whitelists them no more, ``heightfield.relief_inputs`` reads the area). Dropping
them without moving them would FLATTEN every existing world in one boot. So
the value the old rule would have used is written out once, per world:

* every painted area whose KIND carries an amplitude gets that kind's two
  numbers copied into its own ``meta``;
* an area that already authors relief of its own is left alone — its keys are
  the author's, and a repair must never overwrite an explicit answer (there
  cannot be one yet on the first run, and there can be on a re-run of a world
  restored from a backup);
* the kind rows then LOSE the two keys, so nothing is left that looks like it
  still decides something.

The picture is preserved exactly: the seed is still hashed from the kind name
(``heightfield.relief_seed``), so an area that inherits its kind's amplitude and
wave gets the very same lattice at the very same heights it had before.

The SEED (``shared/terrain/types.json``) is READ but never written: it is a file
in the repo, and this reads it RAW rather than through ``effective_catalog`` —
the catalog sanitizer drops the two keys now, so the live catalog can no longer
tell what a seed entry used to say. (The seed shipped in this repo carries no
relief at all; a world that pulled a bumpier seed from elsewhere still gets its
areas filled.)

Idempotent through a ``world_kv`` marker, like every other one-time repair (the
``terrain_surface_migration`` pattern), and per world: the areas live in
``world.db``, so the world that boots is the one that gets repaired.

NO SIGNATURE IS BUMPED BY HAND. ``height_sig`` hashes the areas AND
``HEIGHT_BAKE_VERSION``, which went to 2 with this change, so every client
refetches and the stored raster is rebuilt on the next read either way.
"""

import json
from typing import Any, Dict, Optional

from app.core.log import get_logger

logger = get_logger("terrain_relief_migration")

_GUARD_KEY = "migrated_area_relief_v1"

_KEYS = ("relief_amplitude_m", "relief_wave_m")


def _relief_of(meta: Any) -> Dict[str, Any]:
    """The relief keys of one raw ``meta``, or ``{}``.

    Nothing is validated here beyond "there is an amplitude": the values go
    through the AREA sanitizer on the way in, which is the same clamp the kind
    sanitizer applied on the way out.
    """
    if not isinstance(meta, dict):
        return {}
    amp = meta.get("relief_amplitude_m")
    if amp is None:
        return {}
    return {k: meta[k] for k in _KEYS if k in meta}


def _seed_relief() -> Dict[str, Dict[str, Any]]:
    """``kind -> {relief keys}`` of the SHARED seed, read RAW from the file."""
    from app.core.terrain_types import _shared_path
    try:
        raw = json.loads(_shared_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for entry in (raw.get("types") or []):
        if not isinstance(entry, dict):
            continue
        relief = _relief_of(entry.get("meta"))
        if relief:
            out[str(entry.get("kind") or "").strip()] = relief
    return out


def move_relief_to_areas() -> Dict[str, int]:
    """Copy every kind's relief onto its painted areas, then strip the kinds.

    Returns ``{"kinds": <kinds that carried relief>, "areas": <areas filled>,
    "kept": <areas that already authored their own>}``.
    """
    from app.core.db import transaction
    from app.models.terrain import _sanitize_relief
    stats = {"kinds": 0, "areas": 0, "kept": 0}
    seed = _seed_relief()
    with transaction() as conn:
        # The WORLD rows win over the seed, whole (override-replace per kind):
        # a world row without relief means this kind has none, even where the
        # seed entry of the same name carries some.
        by_kind: Dict[str, Dict[str, Any]] = dict(seed)
        rows = conn.execute("SELECT kind, meta FROM terrain_types").fetchall()
        world_rows: Dict[str, Any] = {}
        for kind, meta_json in rows:
            key = str(kind or "").strip()
            try:
                meta = json.loads(meta_json or "{}")
            except ValueError:
                meta = {}
            world_rows[key] = meta if isinstance(meta, dict) else {}
            relief = _relief_of(world_rows[key])
            if relief:
                by_kind[key] = relief
            else:
                by_kind.pop(key, None)
        stats["kinds"] = len(by_kind)
        if not by_kind:
            return stats
        areas = conn.execute(
            "SELECT id, kind, meta FROM terrain_areas").fetchall()
        for area_id, kind, meta_json in areas:
            relief = by_kind.get(str(kind or "").strip())
            if not relief:
                continue
            try:
                meta = json.loads(meta_json or "{}")
            except ValueError:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            if any(k in meta for k in _KEYS):
                stats["kept"] += 1
                continue
            meta.update(relief)
            # The same clamp an editor save would apply, so the migration can
            # never store a number the sanitizer would refuse.
            _sanitize_relief(meta)
            conn.execute("UPDATE terrain_areas SET meta=? WHERE id=?",
                         (json.dumps(meta, ensure_ascii=False), area_id))
            stats["areas"] += 1
        # …and the kinds let go. A key nothing reads is worse than no key: it
        # reads like a setting that still does something.
        for kind in by_kind:
            meta = world_rows.get(kind)
            if not isinstance(meta, dict):
                continue
            if not any(k in meta for k in _KEYS):
                continue
            for key in _KEYS:
                meta.pop(key, None)
            conn.execute("UPDATE terrain_types SET meta=? WHERE kind=?",
                         (json.dumps(meta, ensure_ascii=False), kind))
    return stats


def migrate_area_relief_once() -> Optional[Dict[str, int]]:
    """Run :func:`move_relief_to_areas` once per world, guarded by ``world_kv``.

    Returns None when the migration had already run (or could not run) — the
    caller only logs.
    """
    try:
        from app.models.world import get_world_setting, set_world_setting
        if get_world_setting(_GUARD_KEY):
            return None
        stats = move_relief_to_areas()
        set_world_setting(_GUARD_KEY, "1")
        if stats["areas"] or stats["kept"]:
            logger.info(
                "Micro-relief is a property of the painted AREA now, not of "
                "the terrain kind: %s area(s) took over the relief of %s "
                "kind(s), %s already authored their own; the kind rows lost "
                "the two keys.",
                stats["areas"], stats["kinds"], stats["kept"])
        return stats
    except Exception as e:
        logger.warning("Terrain relief migration failed: %s", e)
        return None
