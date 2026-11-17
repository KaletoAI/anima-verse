"""One-time boot migration (A168): "Shell from the body" becomes its own mode.

Until A168 the shell (``garment_shell``, Ruling A48d) was the per-character mesh shape of an own-mesh clothing piece
(profile ``garment_fit_settings[item].mesh_shape``: ``auto`` / ``as_generated`` / ``shell``; Auto made a shell of a
close-fitting piece, ``garment_shell.close_fitting``). Since A168 it is the item mode ``shell``
(``garment_set.SHELL``) beside own mesh / template / painted / in the body, and the setting is gone.

``judge`` decides per stored outfit piece in mode ``own_mesh``: ``shell`` when a character of this world stored
``mesh_shape: "shell"`` for it, or when it is close-fitting and nobody stored ``"as_generated"`` for it — what its
fits made under the old rule; every other piece stays ``own_mesh``. Nothing else changes: the fit records name the
shape they made (``inputs.mesh_shape``), so a shell piece's fits, views and shells stay current (the piece
fingerprint never read the mode). Then ``mesh_shape`` leaves every profile's ``garment_fit_settings`` (an item entry
left empty goes with it), under ``keyed_lock("character_profile", name)``.

Two scopes, two markers (like ``figure_migration``): the world's items and its profiles once per world (world_kv
``FLAG``), the shared library once per installation (top-level key ``SHARED_KEY`` of the shared items file, written
in the same write as the judged items). A failed item or profile write is logged and the run goes on; the flag is
set anyway. A list or profile that cannot be read raises before anything is written (the next start retries).
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("shell_mode_migration")

#: world_kv key of the world's done flag.
FLAG = "migrated_shell_mode"
#: Top-level key of the shared items file: the shared library was judged (once per installation).
SHARED_KEY = "migrated_shell_mode"
#: The removed per-piece setting (``garment_fit_settings`` entry key).
SHAPE_KEY = "mesh_shape"


def _choices(names: Sequence[str]) -> Dict[str, List[str]]:
    """``{item id: [stored mesh_shape, ...]}`` over every character's stored ``garment_fit_settings``. A profile
    that cannot be read raises (``strict``)."""
    from app.core.garment_fit_settings import SETTINGS_KEY
    from app.models.character import get_character_profile
    out: Dict[str, List[str]] = {}
    for name in names:
        stored = (get_character_profile(name, strict=True) or {}).get(SETTINGS_KEY)
        for item_id, entry in (stored.items() if isinstance(stored, dict) else ()):
            if isinstance(entry, dict) and isinstance(entry.get(SHAPE_KEY), str):
                out.setdefault(str(item_id), []).append(entry[SHAPE_KEY])
    return out


def judge(item: Dict[str, Any], choices: Sequence[str]) -> Optional[str]:
    """The new mode of ``item`` (module docstring), None when it keeps its mode."""
    from app.core import garment_set, garment_shell
    if item.get("category") != "outfit_piece":
        return None
    piece = item.get("outfit_piece")
    if not isinstance(piece, dict) or piece.get("mesh_mode") != garment_set.OWN_MESH:
        return None
    if "shell" in choices or (garment_shell.close_fitting(item) and "as_generated" not in choices):
        return garment_set.SHELL
    return None


def _judge_all(items: List[Dict[str, Any]], choices: Dict[str, List[str]],
               where: str) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Judge ``items`` in place: ``(judged {id: mode}, changed items)``."""
    judged: Dict[str, str] = {}
    changed: List[Dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        mode = judge(item, choices.get(item_id, []))
        if mode is None:
            continue
        item["outfit_piece"]["mesh_mode"] = mode
        judged[item_id] = mode
        changed.append(item)
        logger.info("Shell mode migration: item %s (%s, %s) -> %s (stored choices %s)", item_id,
                    item.get("name") or "-", where, mode, ", ".join(choices.get(item_id, [])) or "-")
    return judged, changed


def _drop_setting(name: str) -> bool:
    """Pop ``mesh_shape`` from every entry of the profile's ``garment_fit_settings`` under the profile lock (an
    entry left empty goes too). True when something was dropped and the profile saved."""
    from app.core.garment_fit_settings import SETTINGS_KEY
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        stored = profile.get(SETTINGS_KEY)
        if not isinstance(stored, dict):
            return False
        hit = False
        for item_id in list(stored):
            entry = stored[item_id]
            if isinstance(entry, dict) and SHAPE_KEY in entry:
                entry.pop(SHAPE_KEY)
                hit = True
                if not entry:
                    stored.pop(item_id)
        if not hit:
            return False
        if save_character_profile(name, profile):
            return True
    logger.warning("Shell mode migration %s: profile not saved — %s stays", name, SHAPE_KEY)
    return False


def migrate_shell_mode_once() -> Optional[Dict[str, Any]]:
    """The migration (module docstring). None when both halves already ran, else ``{items: {id: mode}, profiles:
    [names whose setting was dropped]}``."""
    from app.models import inventory
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_KEY))
    if world_done and shared_done:
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    choices = _choices(names)
    world_items = [] if world_done else inventory._load_items(strict=True)
    shared_items = [] if shared_done else inventory._load_shared_items(strict=True)

    judged, changed = _judge_all(world_items, choices, "world")
    for item in changed:
        if not inventory._save_items([item]):
            logger.warning("Shell mode migration: world item %s not saved", item.get("id"))
            judged.pop(str(item.get("id") or ""), None)
    if not shared_done:
        from app.core.timeutils import utc_now_iso
        shared_judged, _ = _judge_all(shared_items, choices, "shared")
        try:
            inventory._save_shared_items(shared_items, meta={SHARED_KEY: utc_now_iso()})
            judged.update(shared_judged)
        except Exception as e:  # noqa: BLE001 — the marker stays unset: the next boot retries
            logger.warning("Shell mode migration: shared items not saved: %s", e)

    profiles: List[str] = []
    for name in ([] if world_done else names):
        try:
            if _drop_setting(name):
                profiles.append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("Shell mode migration %s: profile step failed: %s", name, e)
    if not world_done:
        set_world_setting(FLAG, "1")
    logger.info("Shell mode migration done: %d item(s) now shell, %d profile(s) without %s",
                len(judged), len(profiles), SHAPE_KEY)
    return {"items": judged, "profiles": profiles}
