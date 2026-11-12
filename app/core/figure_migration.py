"""One-time boot migration: every stored outfit piece gets its mode, the
per-item ``own_mesh`` flag and the per-character ``outfit_body_mode`` leave
the data (plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``
Task 3, builder-check ruling 4).

The mode of a worn piece (``outfit_piece.mesh_mode``, ``garment_set``) used
to be split over two places: the ITEM's ``own_mesh`` flag and the WEARER's
``outfit_body_mode`` (``mesh`` / ``retexture``). ``migrate_modes_once`` runs
once per world (world_kv flag ``FLAG``) and judges every stored outfit piece
— the world's (``world.db``) and the shared library's — with ``judge_item``,
in this order:

1. an item that already carries a valid ``mesh_mode`` is untouched (a shared
   item judged in another world, an item created after Task 2);
2. ``own_mesh`` true → ``own_mesh``;
3. worn (``equipped_pieces``) by at least one character, and EVERY wearer's
   STORED profile ``outfit_body_mode`` is ``"mesh"`` → ``in_body``;
4. else → ``painted``.

The wearers are every character row (dormant and pooled ones too); their
``outfit_body_mode`` is read from the stored profile key, never from the
derived ``base_body.outfit_body_mode``. Then the ``own_mesh`` key is removed
from every item, and per character, under ``keyed_lock("character_profile",
name)``, the ``outfit_body_mode`` key is popped from the profile.

The order is items first, profiles second: a run that dies in between keeps
the profile keys the next run's judgement needs (the flag is not set yet).
A failed write is logged as a WARNING and the migration goes on; the flag is
set anyway (as ``hair_migration`` does — a half-run retry at every start
would be worse), the log names what stayed. Only an item list, the character
list or a wearer's profile that cannot be read raises before anything is
written and leaves the flag unset (the boot logs it, the next start retries).

The shared library is ``shared/items/items.json`` in the repository: the
first boot of any world rewrites that tracked file.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("figure_migration")

#: world_kv key of the done flag.
FLAG = "migrated_worn_piece_modes"
#: The removed per-item flag (``outfit_piece`` key).
OWN_MESH_KEY = "own_mesh"
#: The removed per-character profile key and its value that meant "in the body".
PROFILE_KEY = "outfit_body_mode"
PROFILE_MESH = "mesh"


def _piece(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    piece = item.get("outfit_piece")
    return piece if isinstance(piece, dict) else None


def judge_item(item: Dict[str, Any], wearers_modes: List[Optional[str]]) -> str:
    """The mode of an outfit piece by ruling 4 (module docstring).
    ``wearers_modes``: the stored ``outfit_body_mode`` of every character
    wearing it (None for a profile without the key); empty = unworn."""
    from app.core import garment_set
    piece = _piece(item) or {}
    mode = piece.get("mesh_mode")
    if mode in garment_set.MESH_MODES:
        return mode
    if piece.get(OWN_MESH_KEY) is True:
        return garment_set.OWN_MESH
    if wearers_modes and all(m == PROFILE_MESH for m in wearers_modes):
        return garment_set.IN_BODY
    return garment_set.PAINTED


def _wearers(names: Sequence[str]) -> Tuple[Dict[str, List[str]], Dict[str, Optional[str]]]:
    """``({item id: [character, ...]}, {character: stored outfit_body_mode})``
    — who wears which outfit piece (``equipped_pieces``) and the STORED
    profile key of each character (None without one). A profile that cannot
    be read raises (``strict``): its wearers' judgement would be a guess."""
    from app.models.character import get_character_profile
    worn: Dict[str, List[str]] = {}
    modes: Dict[str, Optional[str]] = {}
    for name in names:
        profile = get_character_profile(name, strict=True) or {}
        modes[name] = profile.get(PROFILE_KEY)
        pieces = profile.get("equipped_pieces")
        for item_id in sorted({str(v).strip() for v in (pieces.values() if isinstance(pieces, dict) else ())
                               if v and str(v).strip()}):
            worn.setdefault(item_id, []).append(name)
    return worn, modes


def _migrate(items: List[Dict[str, Any]], worn: Dict[str, List[str]],
             modes: Dict[str, Optional[str]], where: str) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Judge and clean ``items`` in place. ``(judged {id: mode}, changed
    items)``."""
    judged: Dict[str, str] = {}
    changed: List[Dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        piece = _piece(item)
        touched = False
        if item.get("category") == "outfit_piece":
            if piece is None:
                piece = {}
                item["outfit_piece"] = piece
            from app.core.garment_set import MESH_MODES
            if piece.get("mesh_mode") not in MESH_MODES:
                wearers = worn.get(item_id, [])
                mode = judge_item(item, [modes.get(w) for w in wearers])
                piece["mesh_mode"] = mode
                judged[item_id] = mode
                touched = True
                logger.info("Worn-piece mode migration: item %s (%s, %s) -> %s, wearers %s",
                            item_id, item.get("name") or "-", where, mode,
                            ", ".join(f"{w}={modes.get(w) or '-'}" for w in wearers) or "-")
        if piece is not None and OWN_MESH_KEY in piece:
            piece.pop(OWN_MESH_KEY)
            touched = True
        if touched:
            changed.append(item)
    return judged, changed


def _drop_profile_key(name: str) -> bool:
    """Pop ``outfit_body_mode`` under the profile lock. True when it was
    there and the profile was saved."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        if PROFILE_KEY not in profile:
            return False
        profile.pop(PROFILE_KEY)
        if save_character_profile(name, profile):
            return True
    logger.warning("Worn-piece mode migration %s: profile not saved — %s stays", name, PROFILE_KEY)
    return False


def migrate_modes_once() -> Optional[Dict[str, Any]]:
    """The migration (module docstring). None when it already ran, else
    ``{items: {item id: mode}, profiles: [names whose key was dropped]}``."""
    from app.models import inventory
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(FLAG, strict=True):
        return None
    # A list that cannot be read is no reason to call the world migrated.
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    worn, modes = _wearers(names)
    world_items = inventory._load_items(strict=True)
    shared_items = inventory._load_shared_items(strict=True)

    judged, changed = _migrate(world_items, worn, modes, "world")
    for item in changed:
        if not inventory._save_items([item]):
            logger.warning("Worn-piece mode migration: world item %s not saved", item.get("id"))
            judged.pop(str(item.get("id") or ""), None)
    shared_judged, shared_changed = _migrate(shared_items, worn, modes, "shared")
    if shared_changed:
        try:
            inventory._save_shared_items(shared_items)
            judged.update(shared_judged)
        except Exception as e:  # noqa: BLE001
            logger.warning("Worn-piece mode migration: shared items not saved (%s): %s",
                           ", ".join(str(i.get("id")) for i in shared_changed), e)

    profiles: List[str] = []
    for name in names:
        try:
            if _drop_profile_key(name):
                profiles.append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("Worn-piece mode migration %s: profile step failed: %s", name, e)

    set_world_setting(FLAG, "1")
    logger.info("Worn-piece mode migration done: %d item(s) judged, %d profile(s) without %s",
                len(judged), len(profiles), PROFILE_KEY)
    return {"items": judged, "profiles": profiles}
