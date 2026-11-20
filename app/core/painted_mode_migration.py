"""One-time boot migration (A224): the worn-piece mode ``painted`` is gone.

Until A224 an outfit piece could be painted into the body texture (mode ``painted``). That mode, its paint compose,
its colour and its region are removed (plan ``docs/superpowers/plans/2026-11-19-remove-painted-mode.md``). Every
stored piece in that mode gets a mode of today by an EXPLICIT table (the user's answers, 2026-11-19), never by a
guess:

- ``item_936518eb`` (a gold necklace) → ``accessory``, kind ``necklace``;
- ``item_0b35fb92`` (a copper belt) → ``accessory``, kind ``belt``;
- ``item_silver_anklets`` → ``in_body``;
- ``item_silver_chain_bra`` → ``in_body``;
- every other piece stored as ``painted`` → ``in_body``.

An accessory keeps a stored ``outfit_piece.jewellery`` of the same kind, else it gets
``accessory_spec.normalize({"kind": kind})``. Nothing is built: the Build stays the only action that spends jobs.

The removed per-piece colours and the removed outfit full-body reference records (profile keys
``PROFILE_KEYS`` — an outfit's reference picture only ever applied to its painted pieces) leave every profile under
``keyed_lock("character_profile", name)``; the reference pictures themselves stay where they are
(``model_refs/references`` or the gallery).

Two scopes, two markers (like ``shell_mode_migration``): the world's items and its profiles once per world
(world_kv ``FLAG``), the shared library once per installation (top-level key ``SHARED_KEY`` of the shared items file,
written in the same write as the migrated items). There is no read-side fallback: after this migration a stored
``painted`` is an unknown mode. A failed item or profile write is logged and the run goes on; a world item that was
not saved leaves the world flag unset, so the next start retries. A list or profile that cannot be read raises before
anything is written.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("painted_mode_migration")

#: world_kv key of the world's done flag.
FLAG = "migrated_painted_mode"
#: Top-level key of the shared items file: the shared library was migrated (once per installation).
SHARED_KEY = "migrated_painted_mode"
#: The removed mode's stored value.
REMOVED_MODE = "painted"
#: The profile keys of the removed features: the per-piece colours, the outfit full-body reference records.
PROFILE_KEYS = ("garment_paint_colours", "outfit_references")
#: The explicit targets (module docstring): ``{item id: (mode, accessory kind or None)}``.
MIGRATION: Dict[str, Tuple[str, Optional[str]]] = {
    "item_936518eb": ("accessory", "necklace"),
    "item_0b35fb92": ("accessory", "belt"),
    "item_silver_anklets": ("in_body", None),
    "item_silver_chain_bra": ("in_body", None),
}


def target(item: Dict[str, Any]) -> Optional[Tuple[str, Optional[str]]]:
    """``(mode, kind)`` of an outfit piece stored as ``painted`` (``MIGRATION``, else ``in_body``); None for any
    other item."""
    from app.core import garment_set
    if item.get("category") != "outfit_piece":
        return None
    piece = item.get("outfit_piece")
    if not isinstance(piece, dict) or piece.get("mesh_mode") != REMOVED_MODE:
        return None
    return MIGRATION.get(str(item.get("id") or ""), (garment_set.IN_BODY, None))


def apply(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rewrite ``item`` in place by ``target``; ``{item, from, to, kind}`` of the change, None when untouched."""
    from app.core import accessory_spec
    goal = target(item)
    if goal is None:
        return None
    mode, kind = goal
    piece = item["outfit_piece"]
    piece["mesh_mode"] = mode
    if kind:
        stored = accessory_spec.of_item(item)
        piece["jewellery"] = stored if stored and stored["kind"] == kind else accessory_spec.normalize({"kind": kind})
    return {"item": str(item.get("id") or ""), "from": REMOVED_MODE, "to": mode, "kind": kind or ""}


def _log(change: Dict[str, Any], where: str) -> None:
    logger.info("Painted mode migration (%s): %s", where, change)


def _migrate_world() -> Tuple[List[Dict[str, Any]], bool]:
    """The world's items: ``(changes, every change saved)``. Each item under its piece lock and the item write
    lock, re-read fresh there (``inventory._item_locks``)."""
    from app.models import inventory
    changes: List[Dict[str, Any]] = []
    saved_all = True
    ids = [str(i.get("id") or "") for i in inventory._load_items(strict=True) if target(i) is not None]
    for item_id in ids:
        with inventory._item_locks(item_id):
            fresh = next((i for i in inventory._load_items(strict=True) if str(i.get("id") or "") == item_id), None)
            change = apply(fresh) if fresh is not None else None
            if change is None:
                continue
            if inventory._save_items([fresh]):
                changes.append(change)
                _log(change, "world")
            else:
                saved_all = False
                logger.warning("Painted mode migration: world item %s not saved", item_id)
    return changes, saved_all


def _migrate_shared() -> List[Dict[str, Any]]:
    """The shared library, in ONE write together with its marker (``SHARED_KEY``)."""
    from app.core.timeutils import utc_now_iso
    from app.models import inventory
    changes: List[Dict[str, Any]] = []
    with inventory.item_write_lock():
        items = inventory._load_shared_items(strict=True)
        for item in items:
            change = apply(item)
            if change is not None:
                changes.append(change)
        inventory._save_shared_items(items, meta={SHARED_KEY: utc_now_iso()})
    for change in changes:
        _log(change, "shared")
    return changes


def _drop_keys(name: str) -> bool:
    """Pop ``PROFILE_KEYS`` from the profile under the profile lock. True when one was there and the profile
    saved."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        present = [k for k in PROFILE_KEYS if k in profile]
        if not present:
            return False
        for key in present:
            profile.pop(key)
        if save_character_profile(name, profile):
            return True
    logger.warning("Painted mode migration %s: profile not saved — %s stay", name, ", ".join(present))
    return False


def migrate_painted_mode_once() -> Optional[Dict[str, Any]]:
    """The migration (module docstring). None when both halves already ran, else ``{items: [{item, from, to,
    kind}], profiles: [names whose removed keys were dropped]}``."""
    from app.models import inventory
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_KEY))
    if world_done and shared_done:
        return None
    names = [] if world_done else list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    changes: List[Dict[str, Any]] = []
    saved_all = True
    if not world_done:
        changes, saved_all = _migrate_world()
    if not shared_done:
        try:
            changes.extend(_migrate_shared())
        except Exception as e:  # noqa: BLE001 — the marker stays unset: the next boot retries
            logger.warning("Painted mode migration: shared items not saved: %s", e)
    profiles: List[str] = []
    for name in names:
        try:
            if _drop_keys(name):
                profiles.append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("Painted mode migration %s: profile step failed: %s", name, e)
    if not world_done and saved_all:
        set_world_setting(FLAG, "1")
    logger.info("Painted mode migration done: %d item(s) moved, %d profile(s) without %s",
                len(changes), len(profiles), " / ".join(PROFILE_KEYS))
    return {"items": changes, "profiles": profiles}
