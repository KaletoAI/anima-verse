"""One-time boot migration: the hair a character no longer uses goes
(spec ``docs/superpowers/specs/2026-11-11-hair-from-body-design.md`` § Design 6,
plan ``2026-11-11-hair-from-body`` Task 3).

Only two hair methods are left — ``body`` (the hair is part of the body mesh,
no hair item) and HairDeck. ``delete_all_hair_once`` runs once per world
(world_kv flag ``HAIR_FLAG``) and, per character (every row: dormant and pooled
ones too):

1. under ``keyed_lock("character_profile", name)``: drops the profile keys of the
   removed methods (``hair_subtract_shape``, ``hair_shell_mm``, a ``hair_method``
   that names no method any more, the per-character ``outfit_imagegen`` chains of
   the removed occasions) and decides the EFFECTIVE method on what is left
   (``legacy_hair_method``: the character's stored value, else the world's
   default). ``body``: every own hair item goes and every hair slot is emptied.
   HairDeck: the character keeps its hair item (the worn own hair, else the
   first owned) with its HairDeck job folders and fits; any other own hair item
   goes;
2. outside the lock: ``inventory.delete_item`` per hair item that goes;
3. ``artefact_graph.collect(explicit=True)`` without a budget, limited to the
   hair nodes (``keys``) — every group, layered fit, body fit and HairDeck job
   folder of a deleted item, and of the KEPT item only the groups of the removed
   methods (edit chain / subtract: a fit record without ``method: hairdeck``, or
   files HairDeck never writes — images, prepared, a raw GLB). Those are taken out
   of the computed garment roots first: the GC keeps the newest fit of every
   method a record names, and nothing serves these any more;
4. the files the collector does not know: the subtract method's
   ``garments/source/<item>_<ssig>/`` folders, a file under ``garments/`` still
   named after a deleted hair item, and the assembled delivery models
   (``model3d/assembled/``) whose sidecar grafts a deleted hair item. Every path
   is checked to resolve inside the character directory before it is removed.

A failure is logged as a WARNING with the path and the migration goes on; the
flag is set anyway (a half-run retry at every start would be worse) — the log
names what stayed. Only a character list that cannot be read leaves the flag
unset. No hub job, no generation: a HairDeck character's next run builds
fresh from what it kept, a ``body`` character has no hair item to build.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("hair_migration")

#: world_kv key of the done flag.
HAIR_FLAG = "migrated_hair_from_body"
#: Why the collector deletes (its log line and report).
REASON = "hair method body: old hair removed"
#: Profile keys of the removed subtract method.
REMOVED_PROFILE_KEYS: Tuple[str, ...] = ("hair_subtract_shape", "hair_shell_mm")
#: ``outfit_imagegen`` keys of the removed occasions ``hair_views_mesh`` / ``hair_source_mesh``.
REMOVED_IMAGEGEN_KEYS: Tuple[str, ...] = ("hair_views_mesh_workflow", "hair_source_mesh_workflow")
#: Steps of the removed methods a ``failed/`` record can name (edit chain + subtract).
REMOVED_STEPS = frozenset({"haired", "ghost", "cutout", "mesh", "mesh_source", "cut"})
#: The subtract method's source mesh folders under ``garments/``.
SOURCE_DIR = "source"
_DIR_NAME_RE = re.compile(r"(?P<item>[A-Za-z0-9][A-Za-z0-9_-]*)_(?P<sig>[0-9a-f]{12})")


def _contained(root: Path, path: Path) -> bool:
    from app.core.media_cleanup import contained
    return contained(root, path)


#: The per-character hair methods before hairstyles (plan 2026-11-12-unified-worn-pieces Task 13 moved the
#: mode onto the hairstyle item and dropped the profile key ``hair_method``).
LEGACY_HAIR_METHODS: Tuple[str, ...] = ("body", "hairdeck")
#: The profile key the method was stored under.
LEGACY_METHOD_KEY = "hair_method"


def legacy_hair_method(profile: Dict[str, Any]) -> str:
    """The hair method a profile from before hairstyles stood for: its stored
    ``hair_method`` when it names one of ``LEGACY_HAIR_METHODS``, else the
    world's default (``garment_hair.default_mode`` — the world setting the old
    ``base_body.hair_method`` was renamed to). Read by the boot migrations
    only."""
    from app.core import garment_hair
    own = (profile or {}).get(LEGACY_METHOD_KEY)
    return own if own in LEGACY_HAIR_METHODS else garment_hair.default_mode()


def _is_hair(item: Optional[Dict[str, Any]]) -> bool:
    from app.core.garment_hair import HAIR_KIND
    return bool(item and item.get("category") == "garment"
                and isinstance(item.get("garment"), dict) and item["garment"].get("kind") == HAIR_KIND)


def _profile_step(name: str, hair_items: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Step 1 under the profile lock: drop the removed keys, decide the method,
    empty the hair slots that lose their item. ``{method, kept, delete,
    dropped, unequipped, saved}``."""
    from app.core import garment_hair
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        dropped: List[str] = []
        for key in REMOVED_PROFILE_KEYS:
            if key in profile:
                profile.pop(key)
                dropped.append(key)
        own = profile.get(LEGACY_METHOD_KEY)
        if own not in (None, "", *LEGACY_HAIR_METHODS):
            profile.pop(LEGACY_METHOD_KEY)
            dropped.append(f"hair_method={own}")
        imagegen = profile.get("outfit_imagegen")
        if isinstance(imagegen, dict):
            for key in REMOVED_IMAGEGEN_KEYS:
                if key in imagegen:
                    imagegen.pop(key)
                    dropped.append(f"outfit_imagegen.{key}")
        method = legacy_hair_method(profile)
        owned = sorted(iid for iid, item in hair_items.items() if (item.get("owner") or "").strip() == name)
        worn = profile.get("equipped_mesh_pieces")
        worn = dict(worn) if isinstance(worn, dict) else {}
        kept = ""
        if method != garment_hair.BODY_MODE:
            worn_hair = worn.get(garment_hair.HAIR_KIND)
            kept = worn_hair if worn_hair in owned else (owned[0] if owned else "")
        unequipped = [slot for slot, iid in worn.items() if iid in hair_items and iid != kept]
        for slot in unequipped:
            worn.pop(slot)
        if unequipped:
            profile["equipped_mesh_pieces"] = worn
        saved = True
        if dropped or unequipped:
            saved = bool(save_character_profile(name, profile))
    return {"method": method, "kept": kept, "delete": [iid for iid in owned if iid != kept],
            "dropped": dropped if saved else [], "unequipped": unequipped if saved else [], "saved": saved}


def _group_is_removed_method(files: List[Path], garments_root: Path) -> Optional[bool]:
    """Whether a stored hair group of the KEPT item was made by a removed
    method: True (edit chain / subtract), False (HairDeck), None (cannot
    tell — kept, never deleted on a guess)."""
    from app.core import garment_store
    fit_methods = set()
    for path in files:
        if path.suffix != ".json" or garment_store.is_strands_sidecar(path):
            continue
        body = garment_store.body_of(path)
        if path.parent == garments_root or (body and path.parent.name == body):
            fit_methods.add(garment_store.fit_method(garment_store.read_record(path)))
    if fit_methods:
        return garment_store.HAIRDECK not in fit_methods
    # HairDeck writes no images, no prepared mesh and no raw GLB (its job is a folder).
    for path in files:
        folder = path.parent.name
        if folder in (garment_store.PART_DIRS["image"], garment_store.PART_DIRS["prepared"],
                      garment_store.PART_DIRS["limbs"]):
            return True
        if folder == garment_store.PART_DIRS["raw"] and path.suffix == ".glb":
            return True
    for path in files:
        if path.parent.name == garment_store.PART_DIRS["failed"]:
            step = str(garment_store.read_record(path).get("step") or "")
            if step in REMOVED_STEPS:
                return True
            if step == garment_store.HAIRDECK:
                return False
    return None


def _collect_keys(name: str, deleted: Set[str], kept: str) -> Tuple[Set[str], Set[str], List[str]]:
    """``(keys, leftover garment keys of the kept item, undecided groups)``."""
    from app.core import garment_store
    from app.core.outfit_cache_gc import _garment_key
    keys: Set[str] = set()
    leftover: Set[str] = set()
    undecided: List[str] = []
    root = garment_store._root(name)
    current = ""
    if kept:
        try:
            current = garment_store.garment_fsig(name, kept)
        except ValueError:
            current = ""
    for (item_id, fsig), files in garment_store.stored_groups(name).items():
        if item_id in deleted:
            keys.add(_garment_key(item_id, fsig))
        elif item_id == kept and fsig != current:
            verdict = _group_is_removed_method(files, root)
            if verdict:
                keys.add(_garment_key(item_id, fsig))
                leftover.add(_garment_key(item_id, fsig))
            elif verdict is None:
                undecided.append(f"{item_id}_{fsig}")
    raw = root / garment_store.PART_DIRS["raw"]
    if raw.is_dir():
        for folder in raw.iterdir():
            match = _DIR_NAME_RE.fullmatch(folder.name)
            if match and folder.is_dir() and match.group("item") in deleted:
                keys.add(f"hairdeck:{folder.name}")
    return keys, leftover, undecided


def _collect(name: str, deleted: Set[str], kept: str) -> Dict[str, Any]:
    """Step 3: the artefact graph deletes the hair nodes (no budget)."""
    from app.core import artefact_graph
    keys, leftover, undecided = _collect_keys(name, deleted, kept)
    for group in undecided:
        logger.warning("Hair migration %s: kept %s — its method cannot be told from its files", name, group)
    if not keys:
        return {"deleted_files": 0, "freed_bytes": 0, "skipped": []}
    roots = artefact_graph.compute_roots(name)
    if roots.garment_keep is None:
        logger.warning("Hair migration %s: garment roots unknown — %d hair node(s) left under %s",
                       name, len(keys), artefact_graph._char_dir(name) / "garments")
        return {"deleted_files": 0, "freed_bytes": 0, "skipped": sorted(keys)}
    # The GC keeps the newest fit of every method a record names; the removed methods' fits serve nothing.
    roots.garment_keep = set(roots.garment_keep) - leftover
    return artefact_graph.collect(name, explicit=True, keys=keys, reason=REASON, roots=roots)


def _unlink(path: Path, char_dir: Path) -> Tuple[int, int]:
    if not _contained(char_dir, path) or path.is_symlink() or not path.is_file():
        if path.exists() or path.is_symlink():
            logger.warning("Hair migration: %s not removed (outside the character or no file)", path)
        return 0, 0
    try:
        size = path.stat().st_size
        path.unlink()
        return 1, size
    except FileNotFoundError:
        return 0, 0
    except OSError as e:
        logger.warning("Hair migration: %s not removed: %s", path, e)
        return 0, 0


def _rmtree(path: Path, char_dir: Path) -> Tuple[int, int]:
    import shutil
    if path.is_symlink() or not path.is_dir() or not _contained(char_dir, path):
        logger.warning("Hair migration: %s not removed (outside the character, a link or no folder)", path)
        return 0, 0
    files = [p for p in path.rglob("*") if p.is_file() and not p.is_symlink()]
    size = sum(p.stat().st_size for p in files)
    try:
        shutil.rmtree(path)
    except OSError as e:
        logger.warning("Hair migration: %s not removed: %s", path, e)
        return 0, 0
    return len(files), size


def _sweep(name: str, hair_ids: Set[str], deleted: Set[str]) -> Tuple[int, int, bool]:
    """Step 4: what the collector does not know. ``(files, bytes,
    assembly removed)``."""
    from app.core import garment_store
    from app.models import inventory
    from app.models.character import get_character_dir
    char_dir = get_character_dir(name)
    if not char_dir.is_dir():
        return 0, 0, False
    count = freed = 0
    garments = garment_store._root(name)
    source = garments / SOURCE_DIR
    if source.is_dir() and _contained(char_dir, source):
        for folder in sorted(source.iterdir()):
            match = _DIR_NAME_RE.fullmatch(folder.name)
            item_id = match.group("item") if match else ""
            # The folder held only the subtract method's hair sources: a hair item's, or one whose item is gone.
            if not match or not (item_id in hair_ids or inventory.get_item(item_id) is None):
                logger.warning("Hair migration %s: %s left (no hair item named)", name, folder)
                continue
            c, b = _rmtree(folder, char_dir)
            count, freed = count + c, freed + b
        try:
            source.rmdir()
        except OSError:
            pass
    if deleted and garments.is_dir() and _contained(char_dir, garments):
        named = re.compile("(?:" + "|".join(re.escape(i) for i in sorted(deleted)) + r")_[0-9a-f]{12}(?:[._]|$)")
        for path in sorted(garments.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if not named.match(path.name):
                continue
            if path.is_dir() and not path.is_symlink():
                c, b = _rmtree(path, char_dir)
            else:
                c, b = _unlink(path, char_dir)
            count, freed = count + c, freed + b
    removed_assembly = False
    if deleted:
        from app.core import garment_assembly
        from app.core.model3d import ASSEMBLED_DIR
        directory = char_dir / "model3d"
        assembled = directory / ASSEMBLED_DIR
        for tier, folder in ((garment_assembly.FULL, assembled), (garment_assembly.LOW, assembled / "low")):
            if not folder.is_dir() or not _contained(char_dir, folder):
                continue
            for sidecar in sorted(folder.glob("*.json")):
                grafted = garment_assembly.read_sidecar(sidecar).get("garments")
                if not isinstance(grafted, dict) or not deleted.intersection(grafted):
                    continue
                present = [p for p in (sidecar.with_suffix(".glb"), sidecar) if p.is_file()]
                size = sum(p.stat().st_size for p in present)
                if garment_assembly._remove(directory, sidecar.stem, tier):
                    count, freed, removed_assembly = count + len(present), freed + size, True
    return count, freed, removed_assembly


def migrate_character(name: str, hair_items: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Steps 1-4 for one character (module docstring). Never raises."""
    from app.core import garment_store
    from app.models import inventory
    out: Dict[str, Any] = {"character": name, "method": "", "kept": "", "items": [], "dropped": [],
                           "files": 0, "bytes": 0, "failed": []}
    try:
        step = _profile_step(name, hair_items)
    except Exception as e:  # noqa: BLE001 — one character never stops the migration
        logger.warning("Hair migration %s: profile step failed: %s", name, e)
        out["failed"].append(f"profile: {e}")
        return out
    out.update(method=step["method"], kept=step["kept"], dropped=step["dropped"])
    if not step["saved"]:
        logger.warning("Hair migration %s: profile not saved — hair kept", name)
        out["failed"].append("profile not saved")
        return out
    deleted: Set[str] = set()
    for item_id in step["delete"]:
        try:
            if inventory.is_shared_item(item_id):
                logger.warning("Hair migration %s: %s is a shared item — not deleted", name, item_id)
                continue
            if inventory.delete_item(item_id):
                deleted.add(item_id)
            else:
                logger.warning("Hair migration %s: item %s not deleted", name, item_id)
                out["failed"].append(f"item {item_id}")
        except Exception as e:  # noqa: BLE001
            logger.warning("Hair migration %s: item %s not deleted: %s", name, item_id, e)
            out["failed"].append(f"item {item_id}: {e}")
    out["items"] = sorted(deleted)
    report: Dict[str, Any] = {}
    try:
        report = _collect(name, deleted, step["kept"])
    except Exception as e:  # noqa: BLE001
        logger.warning("Hair migration %s: collect under %s failed: %s", name, garment_store._root(name), e)
        out["failed"].append(f"collect: {e}")
    for skip in report.get("skipped") or []:
        logger.warning("Hair migration %s: %s left (%s)", name, skip.get("key") if isinstance(skip, dict) else skip,
                       skip.get("why") if isinstance(skip, dict) else "roots unknown")
    out["files"] += int(report.get("deleted_files") or 0)
    out["bytes"] += int(report.get("freed_bytes") or 0)
    try:
        hair_ids = set(step["delete"]) | ({step["kept"]} if step["kept"] else set())
        files, size, assembly = _sweep(name, hair_ids, deleted)
        out["files"] += files
        out["bytes"] += size
        if assembly or step["unequipped"]:
            from app.core import garment_assembly
            garment_assembly.schedule(name)
    except Exception as e:  # noqa: BLE001
        logger.warning("Hair migration %s: sweep under %s failed: %s", name, garment_store._root(name), e)
        out["failed"].append(f"sweep: {e}")
    return out


def _touches(result: Dict[str, Any]) -> bool:
    return bool(result["items"] or result["dropped"] or result["files"] or result["failed"])


def delete_all_hair_once() -> Optional[Dict[str, Any]]:
    """The migration (module docstring). None when it already ran, else
    ``{characters: [per-character result], orphans: [item ids]}``."""
    from app.models import inventory
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(HAIR_FLAG):
        return None
    # A list that cannot be read is no reason to call the world migrated.
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    hair_items = {str(item.get("id")): item for item in inventory.list_items()
                  if item.get("id") and _is_hair(item)}
    results: List[Dict[str, Any]] = []
    for name in names:
        result = migrate_character(name, hair_items)
        results.append(result)
        if _touches(result):
            logger.info("Hair migration %s: method %s, kept %s, items deleted %s, %d file(s), %.1f MB%s%s",
                        name, result["method"], result["kept"] or "-", ", ".join(result["items"]) or "-",
                        result["files"], result["bytes"] / 1e6,
                        f", profile keys dropped {', '.join(result['dropped'])}" if result["dropped"] else "",
                        f", FAILED {'; '.join(result['failed'])}" if result["failed"] else "")
    # A hair item whose owner is no character any more can be nobody's hair (``garment_hair._is_own_hair``).
    orphans: List[str] = []
    known = set(names)
    for item_id, item in hair_items.items():
        if (item.get("owner") or "").strip() in known:
            continue
        try:
            if not inventory.is_shared_item(item_id) and inventory.delete_item(item_id):
                orphans.append(item_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Hair migration: orphan hair item %s not deleted: %s", item_id, e)
    if orphans:
        logger.info("Hair migration: hair items without an owning character deleted: %s", ", ".join(orphans))
    set_world_setting(HAIR_FLAG, "1")
    logger.info("Hair migration done: %d character(s) touched, %d item(s) deleted, %.1f MB freed",
                sum(1 for r in results if _touches(r)),
                sum(len(r["items"]) for r in results) + len(orphans),
                sum(r["bytes"] for r in results) / 1e6)
    return {"characters": results, "orphans": orphans}
