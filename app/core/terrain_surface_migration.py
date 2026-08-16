"""Boot migration: write the surface assignment a terrain kind used to imply.

Why this exists
---------------
A terrain kind was skinned by the surface-texture library entry that happened
to carry the SAME NAME (``surface_textures`` id == ``terrain_types`` kind).
That match is gone: a kind now names its material explicitly in
``terrain_types.surface``, and there is no name fallback behind it — a type
without the field renders the default ground.

Dropping the fallback without filling the field would undress every existing
world at once: a painted meadow whose kind is ``grass`` would lose the
``grass`` texture it has been wearing. So the assignment the old rule DERIVED
is written out once, per world, for exactly the rows where the old rule fired:
a world row whose kind is an id the library holds gets ``surface = <kind>``.
A row whose kind the library never held gets nothing — that ground rendered
the default before and renders it after.

The SEED (``shared/terrain/types.json``) is not touched here: it is a file in
the repo and carries its assignments directly.

Idempotent through a ``world_kv`` marker, like every other one-time repair
(the ``workflow_spec_migration`` pattern). The library is passed IN rather
than read here, so the decision stays a pure set membership test and a check
can hand it a library of its own.
"""

from typing import Dict, Iterable, Optional

from app.core.log import get_logger

logger = get_logger("terrain_surface_migration")

_GUARD_KEY = "migrated_terrain_surface_v1"


def assign_surfaces(known_kinds: Iterable[str]) -> Dict[str, int]:
    """Fill ``surface`` on every world terrain row the old name match served.

    Returns ``{"rows": <seen>, "assigned": <written>}``. Rows that already
    carry a surface are left alone — the field is the author's, and a repair
    must never overwrite an explicit answer.
    """
    from app.core.db import transaction
    library = {str(k).strip().lower() for k in (known_kinds or ()) if str(k).strip()}
    stats = {"rows": 0, "assigned": 0}
    with transaction() as conn:
        rows = conn.execute(
            "SELECT kind, surface FROM terrain_types").fetchall()
        for kind, surface in rows:
            stats["rows"] += 1
            if str(surface or "").strip():
                continue
            key = str(kind or "").strip().lower()
            if key not in library:
                continue
            conn.execute("UPDATE terrain_types SET surface=? WHERE kind=?",
                         (key, kind))
            stats["assigned"] += 1
            logger.info("Terrain kind %r keeps its ground: surface=%r",
                        kind, key)
    return stats


def migrate_terrain_surfaces_once(
        known_kinds: Optional[Iterable[str]] = None) -> Dict[str, int]:
    """Run :func:`assign_surfaces` once per world, guarded by ``world_kv``.

    ``known_kinds`` defaults to the live surface library. Returns {} when the
    migration had already run (or could not run) — the caller only logs.
    """
    try:
        from app.models.world import get_world_setting, set_world_setting
        if get_world_setting(_GUARD_KEY):
            return {}
        if known_kinds is None:
            from app.core.surface_textures import library_kinds
            known_kinds = library_kinds()
        stats = assign_surfaces(known_kinds)
        set_world_setting(_GUARD_KEY, "1")
        # No signature has to be bumped by hand: ``terrain_sig`` is hashed over
        # the effective catalog on every read, so the changed rows reach a
        # polling client with the next worldmap answer by themselves.
        return stats
    except Exception as e:
        logger.warning("Terrain surface migration failed: %s", e)
        return {}
