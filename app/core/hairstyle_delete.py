"""Deleting a hairstyle again, with its files (Ruling A59; the user: "Haare wieder löschen gibt es nicht.").

A hairstyle is a garment item of kind hair that ONE character owns (``garment_hair``; minted by
``create_hairstyle`` into the world item store with ``owner`` = the character, carried by nobody). Deleting it:

1. **The character's references**, under ``keyed_lock("garment_item", name)`` → ``keyed_lock("character_profile",
   name)`` (the order ``create_hairstyle`` takes): the hair slot of ``equipped_mesh_pieces`` when it is worn (the
   character then wears no hairstyle — bald, the hair slot empty) and ``garment_hair.BASE_HAIRSTYLE_KEY`` when the
   plain body is its body; every saved outfit set that names it gets ``hairstyle`` "" ("the set leaves the hair as
   it is" — the set editor's own value). Deleting the worn one, and the last one, is allowed.
2. **The item**: ``inventory.delete_item`` — the path the item delete route (``DELETE /inventory/items/{id}``,
   the outfit-piece delete) takes: its row, every inventory row of it and its media folder ``items/<id>/``. A
   hairstyle is never a shared library item; one that is (hand-made) is refused, never deleted from one
   character's tab.
3. **Its generated files** under ``characters/<name>/garments/``: every file and folder whose name is the item id
   followed by a 12-hex signature (``fsig`` / ``hsig`` / ``ssig``, ``garment_store``'s layout) — HairDeck jobs
   ``raw/{item}_{hsig}/`` (record, every result file, the beard-free input), HAAR strand jobs ``raw/{item}_{ssig}/``
   (record, ``s{seed}/`` strand jobs and their variant tiles), the fits ``{item}_{fsig}.glb/.json`` with their
   strand records ``.strands.json/.npz``, ``low/``, ``failed/``, ``layers/``, ``limbs/``, ``images/``,
   ``prepared/``, the refused attempts ``attempts/…`` and the fits on every body shape ``bodies/<ob…>/…``. Only
   names of THIS item: a file of another item never starts with this id plus a signature (an item whose id is
   this id plus ``_`` plus more is checked and skipped). Every path is checked to resolve inside ``garments/``,
   symlinks are never followed or removed. A body fit whose body is being fitted
   (``keyed_lock("garment_body_fit", …)``) is skipped and named.
4. **The assembled delivery models** (``model3d/assembled/``) whose sidecar grafts it — the served one is
   re-assembled without hair on the CPU (``garment_assembly.schedule``, no hub job).
5. **Body shapes with its hair** (a ``body`` hairstyle other than the plain body's is worn as a body SHAPE whose
   ``shape_inputs.hair`` is its text, ``figure.shape_inputs``): deleted through the Figure tab's own Delete
   (``figure.delete_stored``) when no other hairstyle of the character has that text and the figure would not be
   built on it now (``figure.stored`` ``deletable``). A shape the worn figure stands on stays until the Build has
   rebuilt the figure; the Figure tab's "Stored bodies" offers it then. The plain body is never deleted.

Then the figure is told: ``figure.invalidate``, the assembly is scheduled and — when the worn or the plain body's
hairstyle went — the Build is requested (``figure_build.request(name, "outfit_change")``, like a Wear: "Build
automatically" decides; else it stays a pending change). ``delete_estimate`` says before the click what that Build
costs (``figure_build.plan`` of the profile without the hairstyle — like ``garment_hair.wear_estimate``).

Refused (``HairstyleBusy``, a 409) while a run of the hairstyle works or waits (``artefact_graph.running_state``,
``garment_store.run_item_lock``), while what is running cannot be read at all (``running_state``'s unknown — its
``artefact_graph.RUNNING_UNKNOWN`` text is the refusal), or while a Build of the character runs
(``figure_build.build_lock``): nothing is deleted then.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("hairstyle_delete")

#: 409 while a hair run of the hairstyle works or waits.
HAIR_RUNNING = "Not deleted: a run of this hairstyle works or waits now — delete it after the run."
#: 409 while a Build of the character runs.
BUILD_RUNNING = "Not deleted: a Build runs now — delete it after the Build."
#: The signature after the item id in every hair file / folder name (``fsig`` / ``hsig`` / ``ssig``: md5[:12]).
_SIG_TAIL = r"_[0-9a-f]{12}(?:[._]|$)"
_SEED_DIR = re.compile(r"s[1-9][0-9]{0,8}")
#: The labels of the file groups the confirmation lists (``delete_preview``), in their order.
LABELS: Tuple[str, ...] = ("HairDeck jobs", "HAAR strand jobs", "Fits and strand records", "Fits on body shapes",
                           "Refused attempts", "Failure records", "Layered fits", "Other generated files")


class HairstyleBusy(RuntimeError):
    """A run or a Build works now — nothing deleted (the route answers 409)."""


def _checked(character_name: str, item_id: str) -> Dict[str, Any]:
    """The character's hairstyle ``item_id``. ValueError for an id that is no safe item id or names a shared
    library item; LookupError when it is no hairstyle of the character."""
    from app.core import garment_hair
    from app.models import inventory
    iid = inventory.safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid item id {str(item_id)[:80]!r}")
    item = inventory.get_item(iid)
    if not garment_hair.is_hairstyle(item, character_name):
        raise LookupError(f"{iid} is no hairstyle of {character_name}")
    if inventory.is_shared_item(iid):
        raise ValueError(f"{iid} is a shared library item — it is not deleted from one character's hairstyles")
    return item


def _name_matcher(item_id: str):
    """A predicate over a file / folder name: it belongs to ``item_id`` — the id, then a 12-hex signature, then a
    dot, an underscore or the end — and to no other item whose id starts with this id plus ``_``."""
    from app.models import inventory
    named = re.compile(re.escape(item_id) + _SIG_TAIL)
    longer = sorted(str(i.get("id")) for i in inventory.list_items()
                    if str(i.get("id") or "").startswith(item_id + "_"))

    def match(name: str) -> bool:
        if not named.match(name):
            return False
        return not any(name == other or name.startswith((other + "_", other + ".")) for other in longer)
    return match


def item_paths(character_name: str, item_id: str) -> List[Path]:
    """Every file and top-most folder under the character's ``garments/`` named after the hairstyle (module
    docstring, step 3) — a matching folder is listed whole and not descended. Symlinks are never followed nor
    listed. Read-only; [] without a ``garments/`` folder."""
    from app.core import garment_store
    root = garment_store._root(character_name)
    if not root.is_dir() or root.is_symlink():
        return []
    match = _name_matcher(item_id)
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            path = here / d
            if path.is_symlink():
                continue
            if match(d):
                out.append(path)
            else:
                keep.append(d)
        dirnames[:] = keep
        out.extend(here / f for f in sorted(filenames) if match(f) and not (here / f).is_symlink())
    return out


def _files_of(path: Path) -> List[Path]:
    if path.is_dir() and not path.is_symlink():
        return [p for p in path.rglob("*") if p.is_file() and not p.is_symlink()]
    return [path] if path.is_file() and not path.is_symlink() else []


def _size(paths: List[Path]) -> int:
    total = 0
    for p in paths:
        try:
            total += p.lstat().st_size
        except OSError:
            pass
    return total


def _label(path: Path, root: Path) -> str:
    """The group of one stored path (``LABELS``)."""
    parts = path.relative_to(root).parts
    head = parts[0] if len(parts) > 1 else ""
    if head == "raw" and path.is_dir():
        return ("HAAR strand jobs" if any(_SEED_DIR.fullmatch(p.name) for p in path.iterdir() if p.is_dir())
                else "HairDeck jobs")
    if head == "bodies":
        return "Fits on body shapes"
    if head == "attempts":
        return "Refused attempts"
    if head == "failed":
        return "Failure records"
    if head == "layers":
        return "Layered fits"
    if head in ("", "low"):
        return "Fits and strand records"
    return "Other generated files"


def _assemblies(character_name: str, item_id: str) -> List[Tuple[str, Path]]:
    """``(tier, sidecar)`` of every assembled delivery model whose sidecar grafts the item."""
    from app.core import garment_assembly, media_cleanup
    from app.core.model3d import ASSEMBLED_DIR
    from app.models.character import get_character_dir
    char_dir = get_character_dir(character_name)
    assembled = char_dir / "model3d" / ASSEMBLED_DIR
    out: List[Tuple[str, Path]] = []
    for tier, folder in ((garment_assembly.FULL, assembled), (garment_assembly.LOW, assembled / "low")):
        if not folder.is_dir() or folder.is_symlink() or not media_cleanup.contained(char_dir, folder):
            continue
        for sidecar in sorted(folder.glob("*.json")):
            grafted = garment_assembly.read_sidecar(sidecar).get("garments")
            if isinstance(grafted, dict) and item_id in grafted:
                out.append((tier, sidecar))
    return out


def _shape_keys_with_hair(character_name: str, text: str) -> List[str]:
    """The stored body shapes (``ob…``) whose parent record names ``text`` as its hair
    (``shape_inputs.hair``, ``figure.shape_inputs``) — read from the shape's sidecars, no analysis."""
    if not text:
        return []
    from app.core import artefact_graph
    from app.models.character import get_character_dir
    root = get_character_dir(character_name)
    keys: Set[str] = set()
    for folder, pattern in ((root / "model3d", "ob*.json"), (root / "model_refs", "tpose*ob*.json")):
        if not folder.is_dir():
            continue
        for sidecar in folder.glob(pattern):
            record = artefact_graph._json(sidecar).get("outfit_body")
            inputs = record.get("shape_inputs") if isinstance(record, dict) else None
            body = record.get("body_id") if isinstance(record, dict) else None
            if isinstance(inputs, dict) and inputs.get("hair") == text and isinstance(body, str):
                keys.add(body)
    return sorted(keys)


def _other_texts(character_name: str, item_id: str) -> Set[str]:
    """The texts of the character's OTHER hairstyles (a shape with one of them stays: that hairstyle may stand on it)."""
    from app.core import garment_hair
    return {garment_hair.hairstyle_description(i) for i in garment_hair.hairstyles(character_name)
            if str(i.get("id") or "") != item_id}


def _shapes(character_name: str, item_id: str, text: str) -> List[Dict[str, Any]]:
    """``[{key, deletable, why}]``: the body shapes with this hairstyle's hair (module docstring, step 5)."""
    keys = _shape_keys_with_hair(character_name, text)
    if not keys:
        return []
    if text in _other_texts(character_name, item_id):
        return [{"key": k, "deletable": False, "why": "another hairstyle has the same text"} for k in keys]
    from app.core import figure
    try:
        stored = {e["key"]: e for e in figure.stored(character_name) if e.get("kind") == "shape"}
    except Exception:  # noqa: BLE001 — never deleted on a guess
        logger.exception("Hairstyle delete %s: stored bodies unreadable — body shapes kept", character_name)
        stored = {}
    out = []
    for key in keys:
        entry = stored.get(key)
        if entry is None:
            out.append({"key": key, "deletable": False, "why": "not judged"})
        elif entry.get("running"):
            out.append({"key": key, "deletable": False, "why": "a run works on it"})
        elif not entry.get("deletable"):
            out.append({"key": key, "deletable": False,
                        "why": "the figure stands on it — the Figure tab offers it once the figure is rebuilt"})
        else:
            out.append({"key": key, "deletable": True, "why": ""})
    return out


def delete_estimate(character_name: str, item_id: str, *,
                    profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """What the Build after deleting the hairstyle costs — ``{hub_jobs, automatic, note}`` of
    ``figure_build.plan`` on the profile WITHOUT it (not worn, not the plain body's), like
    ``garment_hair.wear_estimate``: ``automatic`` when "Build automatically" is on (the Build starts by itself).
    None off the figure pipeline (no figure) or when the hairstyle is neither worn nor the plain body's (the figure
    does not change); ``hub_jobs`` None ("cost unknown") when the plan cannot be made. Read-only."""
    from app.core import figure_build, garment_hair
    from app.models.character import get_character_profile
    profile = profile if profile is not None else (get_character_profile(character_name) or {})
    try:
        if not figure_build.on_pipeline(character_name, profile=profile):
            return None
        mesh = profile.get("equipped_mesh_pieces")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        worn = any(v == item_id for v in mesh.values())
        plain = str(profile.get(garment_hair.BASE_HAIRSTYLE_KEY) or "") == item_id
        if not worn and not plain:
            return None
        trial = {**profile, "equipped_mesh_pieces": {k: v for k, v in mesh.items() if v != item_id}}
        if plain:
            trial.pop(garment_hair.BASE_HAIRSTYLE_KEY, None)
        automatic = bool(figure_build.auto_build_on(character_name, profile=profile))
        steps = figure_build.plan(character_name, profile=trial, explicit=not automatic)
        cost = figure_build.cost(character_name, steps)
    except Exception as e:  # noqa: BLE001 — a label, never a failure of the preview
        logger.exception("Delete estimate of %s for %s failed", item_id, character_name)
        return {"hub_jobs": None, "automatic": False, "note": f"cost unknown — {e}", "steps": []}
    return {"hub_jobs": cost["hub_jobs"], "automatic": automatic, "note": cost["note"],
            "steps": [s.get("label") for s in cost.get("steps") or [] if isinstance(s, dict)]}


def delete_preview(character_name: str, item_id: str) -> Dict[str, Any]:
    """What deleting the hairstyle removes — the confirmation's content. ``{item_id, name, description, mode,
    worn, plain, last, files: [{label, files, bytes}] (``LABELS`` order, empty groups left out), total_files,
    total_bytes, item_files, assembled, shapes: [{key, deletable, why}], outfit_sets: [names], estimate}``.
    ValueError / LookupError like ``delete_hairstyle``. Read-only."""
    from app.core import garment_hair, garment_store
    from app.models.character import get_character_outfits, get_character_profile
    from app.core.paths import get_storage_dir
    item = _checked(character_name, item_id)
    profile = get_character_profile(character_name) or {}
    root = garment_store._root(character_name)
    groups: Dict[str, List[Path]] = {}
    for path in item_paths(character_name, item_id):
        groups.setdefault(_label(path, root), []).extend(_files_of(path))
    files = [{"label": label, "files": len(groups[label]), "bytes": _size(groups[label])}
             for label in LABELS if groups.get(label)]
    media = _files_of(get_storage_dir() / "items" / item_id) if (get_storage_dir() / "items").is_dir() else []
    assembled = _assemblies(character_name, item_id)
    text = garment_hair.hairstyle_description(item)
    return {"item_id": item_id, "name": str(item.get("name") or item_id), "description": text,
            "mode": garment_hair.hairstyle_mode(item),
            "worn": garment_hair.worn_hair_id(character_name, profile) == item_id,
            "plain": str(profile.get(garment_hair.BASE_HAIRSTYLE_KEY) or "") == item_id,
            "last": len(garment_hair.hairstyles(character_name)) == 1,
            "files": files, "total_files": sum(f["files"] for f in files),
            "total_bytes": sum(f["bytes"] for f in files), "item_files": len(media),
            "assembled": len(assembled),
            "shapes": _shapes(character_name, item_id, text),
            "outfit_sets": [str(o.get("name") or o.get("id") or "") for o in get_character_outfits(character_name)
                            if str(o.get("hairstyle") or "").strip() == item_id],
            "estimate": delete_estimate(character_name, item_id, profile=profile)}


def _unclaim(character_name: str, item_id: str) -> Tuple[bool, bool]:
    """Drop the hairstyle from the profile (one read-modify-write under the profile lock): every
    ``equipped_mesh_pieces`` slot that wears it and ``BASE_HAIRSTYLE_KEY`` when it names it. ``(worn, plain)``.
    RuntimeError when the save fails (nothing else changed then)."""
    from app.core import garment_hair
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        mesh = profile.get("equipped_mesh_pieces")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        worn = any(v == item_id for v in mesh.values())
        plain = str(profile.get(garment_hair.BASE_HAIRSTYLE_KEY) or "") == item_id
        if worn:
            profile["equipped_mesh_pieces"] = {k: v for k, v in mesh.items() if v != item_id}
        if plain:
            profile.pop(garment_hair.BASE_HAIRSTYLE_KEY, None)
        if (worn or plain) and not save_character_profile(character_name, profile):
            raise RuntimeError(f"Could not save the profile of {character_name} — the hairstyle is kept")
    return worn, plain


def _clear_outfit_sets(character_name: str, item_id: str) -> List[str]:
    """Every saved outfit set that wears the hairstyle gets ``hairstyle`` "" (the set leaves the hair as it is),
    through the set editor's own write (``add_character_outfit``). The names of the sets."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import add_character_outfit, get_character_outfits
    names: List[str] = []
    with keyed_lock("character_profile", character_name):
        for outfit in get_character_outfits(character_name):
            if str(outfit.get("hairstyle") or "").strip() == item_id and outfit.get("id"):
                add_character_outfit(character_name, {"id": outfit["id"], "hairstyle": ""})
                names.append(str(outfit.get("name") or outfit["id"]))
    return names


def _remove_path(path: Path, root: Path) -> Tuple[int, int]:
    """Unlink a file or remove a folder inside ``root`` — never a symlink, never outside. ``(files, bytes)``."""
    from app.core import media_cleanup
    if path.is_symlink() or not media_cleanup.contained(root, path):
        logger.warning("Hairstyle delete: %s not removed (a link or outside %s)", path, root)
        return 0, 0
    files = _files_of(path)
    size = _size(files)
    try:
        from app.core import thumbnails
        thumbnails.forget_sources(p for p in files if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    except Exception:  # noqa: BLE001 — a cache sweep, never a failure of the delete
        logger.debug("Hairstyle delete: thumbnail sweep of %s failed", path, exc_info=True)
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError:
        return 0, 0
    except OSError as e:
        logger.warning("Hairstyle delete: %s not removed: %s", path, e)
        return 0, 0
    return len(files), size


def _remove_files(character_name: str, item_id: str) -> Tuple[int, int, List[str]]:
    """Step 3: ``(files, bytes, kept)`` — ``kept`` the paths left (relative to ``garments/``) with why."""
    from app.core import artefact_graph, garment_store
    root = garment_store._root(character_name)
    count = freed = 0
    kept: List[str] = []
    for path in item_paths(character_name, item_id):
        body = garment_store.body_of(path)
        lock = artefact_graph._try_lock("garment_body_fit", f"{character_name}:{body}") if body else None
        if body and lock is None:
            kept.append(f"{path.relative_to(root).as_posix()} (its body is being fitted)")
            continue
        try:
            c, b = _remove_path(path, root)
        finally:
            if lock is not None:
                lock.release()
        count, freed = count + c, freed + b
    return count, freed, kept


def _remove_assemblies(character_name: str, item_id: str) -> int:
    """Step 4: the assembled models grafting the item go (re-assembled without it). The files removed."""
    from app.core import garment_assembly
    count = 0
    for tier, sidecar in _assemblies(character_name, item_id):
        present = [p for p in (sidecar.with_suffix(".glb"), sidecar) if p.is_file()]
        directory = sidecar.parent.parent if tier == garment_assembly.FULL else sidecar.parent.parent.parent
        if garment_assembly._remove(directory, sidecar.stem, tier):
            count += len(present)
    return count


def _remove_shapes(character_name: str, item_id: str, text: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Step 5 (after the item is gone): ``(deleted keys, kept [{key, why}])``."""
    from app.core import figure
    deleted: List[str] = []
    kept: List[Dict[str, Any]] = []
    for shape in _shapes(character_name, item_id, text):
        if not shape["deletable"]:
            kept.append({"key": shape["key"], "why": shape["why"]})
            continue
        try:
            figure.delete_stored(character_name, shape["key"])
            deleted.append(shape["key"])
        except Exception as e:  # noqa: BLE001 — the hairstyle is gone already; the shape stays listed
            logger.warning("Hairstyle delete %s: body shape %s kept: %s", character_name, shape["key"], e)
            kept.append({"key": shape["key"], "why": str(e)})
    return deleted, kept


def delete_hairstyle(character_name: str, item_id: str) -> Dict[str, Any]:
    """Delete the character's hairstyle ``item_id`` with its files (module docstring). ValueError for an invalid
    id or a shared item (400), LookupError for no hairstyle of the character (404), ``HairstyleBusy`` while a run
    of it or a Build of the character works, or what runs cannot be read (409), RuntimeError when the profile or the item cannot be written
    (500). Returns ``{item_id, worn, plain, outfit_sets, deleted_files, freed_bytes, assembled, shapes_deleted,
    kept, build_requested}``."""
    from app.core import artefact_graph, figure, figure_build, garment_hair, garment_store
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    item = _checked(character_name, item_id)
    text = garment_hair.hairstyle_description(item)
    build = figure_build.build_lock(character_name)
    if not build.acquire(blocking=False):
        raise HairstyleBusy(BUILD_RUNNING)
    try:
        run = garment_store.run_item_lock(character_name, item_id)
        if not run.acquire(blocking=False):
            raise HairstyleBusy(HAIR_RUNNING)
        try:
            _sigs, running_items, unknown = artefact_graph.running_state(character_name)
            if unknown:
                # A run of it may be working unseen: delete nothing (review 09#7).
                raise HairstyleBusy(unknown)
            if item_id in running_items:
                raise HairstyleBusy(HAIR_RUNNING)
            with keyed_lock("garment_item", character_name):
                _checked(character_name, item_id)
                worn, plain = _unclaim(character_name, item_id)
                sets = _clear_outfit_sets(character_name, item_id)
                try:
                    from app.core.expression_regen import invalidate_variants_for_item
                    invalidate_variants_for_item(item_id)
                except Exception as e:  # noqa: BLE001 — the delete route treats it the same way
                    logger.debug("Variant invalidation failed: %s", e)
                if not inventory.delete_item(item_id):
                    raise RuntimeError(f"Could not delete the item {item_id}")
            files, freed, kept = _remove_files(character_name, item_id)
            assembled = _remove_assemblies(character_name, item_id)
        finally:
            run.release()
    finally:
        build.release()
    with garment_store._status_lock:
        garment_store._failed.pop((character_name, item_id), None)
        garment_store._item_locks.pop((character_name, item_id), None)
    shapes_deleted, shapes_kept = _remove_shapes(character_name, item_id, text)
    figure.invalidate()
    if worn or plain or assembled:
        try:
            from app.core import garment_assembly
            garment_assembly.schedule(character_name)
        except Exception as e:  # noqa: BLE001 — a failed schedule must not undo the delete
            logger.warning("garment assembly schedule for %s failed: %s", character_name, e)
    build_requested = bool(figure_build.request(character_name, "outfit_change")) if (worn or plain) else False
    logger.info("Hairstyle %s of %s deleted%s%s: %d file(s), %.1f MB, %d assembled file(s), shapes %s%s%s",
                item_id, character_name, " (worn)" if worn else "", " (plain body's)" if plain else "",
                files, freed / 1e6, assembled, ", ".join(shapes_deleted) or "-",
                f", outfit sets cleared: {', '.join(sets)}" if sets else "",
                f", kept: {'; '.join(kept)}" if kept else "")
    return {"item_id": item_id, "worn": worn, "plain": plain, "outfit_sets": sets, "deleted_files": files,
            "freed_bytes": freed, "assembled": assembled, "shapes_deleted": shapes_deleted,
            "kept": kept + [f"{s['key']} ({s['why']})" for s in shapes_kept], "build_requested": build_requested}
