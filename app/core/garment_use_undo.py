"""Undo of a "Use this" on a stored image attempt (Ruling A79).

WHY. "Use this" (Ruling A37, ``garments.use_attempt``) publishes a stored attempt of an edit step (``worn`` /
``ghost``) as the view's accepted image — a refused one accepted by the user — and drops what was made from the
image it replaces: the later images of the view (for a new drafted front its back too), the raw and prepared mesh
and the kept mesh attempts (``garments._drop_mesh``), and the recorded refusal of the chain. A refused fit's
acceptance has its Undo (``fit_attempts.undo``); an image taken by hand had none, so a wrong click could only be
answered by another attempt or a new render. Ylva's laced linen blouse (2026-11-15): both ghost fronts refused by
a mis-measured hem — the user wants to take attempt 1 by hand, and to be able to take that back.

WHAT IS KEPT. Before the click publishes anything, ``snapshot`` copies every file the click replaces or drops into
``garments/attempts/use/{item}_{fsig}/`` (paths relative to ``garments/``) and writes ``manifest.json``::

    {version, at, step, view, attempt, passing, published_sha256,
     files: {<relative path>: <sha256 of the copy> | null},    # null: the file was not there before
     mesh_attempts: [<relative path>, ...]}                     # the kept mesh attempts there were

``published_sha256`` is the image the click published. The copies are made into ``….pending`` and become the
group's snapshot only when the click published (``commit``; ``discard`` otherwise). ONE snapshot per (item,
fsig): the next "Use this" of the group replaces it, so Undo takes back the last click.

UNDO (``undo``) holds while the view's accepted image is still the one the click published (``state``): every
file of ``files`` is put back as it was — a copy back, or removed when it was not there before (an image, a mesh
or a refusal made since from the image taken by hand) — and the kept mesh attempts are those of before. The fits
stay (a fit is never dropped by new images either, R11): a fit made since reads outdated against the mesh put
back and is fitted again on the CPU. Nothing is rendered; the figure is due again (the Build's estimate names
what). ``UndoUnavailable`` when there is nothing to undo or the image was replaced since.

The folder is in the garment group of its (item, fsig) for the artefact GC (``artefact_graph``) and goes with an
undo or the next snapshot.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("garment_use_undo")

#: The snapshot folder of a group under ``garments/``.
UNDO_DIR = "attempts/use"
MANIFEST = "manifest.json"
VERSION = 1
#: Why Undo is not offered (``state``) — plain words the Wardrobe shows.
NOTHING_TO_UNDO = "Nothing to undo"
REPLACED_SINCE = "The image was replaced since — use another attempt instead"


class UndoUnavailable(ValueError):
    """``undo``: no click to take back, or the image it published was replaced since (409)."""


def undo_dir(character_name: str, item_id: str, fsig: str) -> Path:
    """``garments/attempts/use/{item}_{fsig}`` (ValueError like ``garment_store.garment_path``); creates nothing."""
    from app.core import garment_store as gs
    failed = gs.garment_path(character_name, item_id, fsig, "failed")   # validates item id and fsig
    return gs._root(character_name) / UNDO_DIR / failed.stem


def _later_views(kind_module, order, step: str, view: str) -> Dict[str, List[str]]:
    """The image steps per view a "Use this" on ``view`` of ``step`` replaces or drops (``garment_images._publish``):
    the step and its later steps of the view, and for a new front of a drafted step the back's too."""
    out = {view: list(order[order.index(step):])}
    if view == "front" and (getattr(kind_module, "EDIT_STEPS", {}).get(step) or {}).get("back") == "draft":
        out["back"] = list(order[order.index(step):])
    return out


def _targets(character_name: str, item_id: str, fsig: str, step: str, view: str) -> List[Path]:
    """Every file a "Use this" on ``view`` of ``step`` replaces or drops, except the kept mesh attempts."""
    from app.core import garment_images
    from app.core import garment_store as gs
    kind = garment_images._item_kind(item_id)
    module = garment_images.kind_module(kind)
    paths: List[Path] = []
    for v, steps in _later_views(module, gs.image_steps(kind), step, view).items():
        for s in steps:
            image = gs.garment_path(character_name, item_id, fsig, "image", step=s, view=v)
            paths += [image, image.with_suffix(".json")]
    for part in ("raw", "prepared"):
        mesh = gs.garment_path(character_name, item_id, fsig, part)
        paths += [mesh, mesh.with_suffix(".json")]
    paths.append(gs.garment_path(character_name, item_id, fsig, "failed"))
    return paths


def _mesh_attempts(character_name: str, item_id: str, fsig: str) -> List[Path]:
    """The kept mesh attempt files of the group (``garment_mesh.clear_attempts``' glob)."""
    from app.core import garment_store as gs
    folder = gs.garment_path(character_name, item_id, fsig, "mesh_attempt", attempt=1).parent
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob(f"{item_id}_{fsig}.try*.glb") if gs.parse_name(p) == (item_id, fsig))


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.undo.tmp")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def _read_manifest(folder: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((folder / MANIFEST).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == VERSION else None


def _pending(folder: Path) -> Path:
    return folder.with_name(f"{folder.name}.pending")


def snapshot(character_name: str, item_id: str, fsig: str, step: str, view: str, attempt: int,
             passing: bool) -> Path:
    """Copy every file a "Use this" on ``attempt`` of ``view`` of ``step`` replaces or drops (module docstring)
    into the group's PENDING snapshot and write its manifest — ``commit`` makes it the group's snapshot once the
    click published, ``discard`` drops it when it did not. The caller holds the item's run lock and calls it
    BEFORE the click publishes anything. Returns the pending folder."""
    from app.core import garment_store as gs
    from app.core.base_body import file_sha256
    from app.core.timeutils import utc_now_iso
    root = gs._root(character_name)
    folder = _pending(undo_dir(character_name, item_id, fsig))
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    files: Dict[str, Optional[str]] = {}
    for path in _targets(character_name, item_id, fsig, step, view):
        rel = path.relative_to(root).as_posix()
        if path.is_file():
            _copy(path, folder / rel)
            files[rel] = file_sha256(folder / rel)
        else:
            files[rel] = None
    kept = []
    for path in _mesh_attempts(character_name, item_id, fsig):
        rel = path.relative_to(root).as_posix()
        _copy(path, folder / rel)
        kept.append(rel)
    manifest = {"version": VERSION, "at": utc_now_iso(), "step": step, "view": view, "attempt": int(attempt),
                "passing": bool(passing), "published_sha256": None, "files": files, "mesh_attempts": kept}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return folder


def commit(character_name: str, item_id: str, fsig: str) -> None:
    """The click published: the pending snapshot becomes the group's (the earlier one goes) and records the image
    published (the view's accepted final now) — Undo holds while it stays."""
    from app.core import garment_store as gs
    from app.core.base_body import file_sha256
    folder = undo_dir(character_name, item_id, fsig)
    pending = _pending(folder)
    manifest = _read_manifest(pending)
    if manifest is None:
        return
    final = gs.garment_path(character_name, item_id, fsig, "image", step=manifest["step"], view=manifest["view"])
    manifest["published_sha256"] = file_sha256(final) if final.is_file() else None
    (pending / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    shutil.rmtree(folder, ignore_errors=True)
    os.replace(pending, folder)


def discard(character_name: str, item_id: str, fsig: str) -> None:
    """The click published nothing: its pending snapshot goes; the group's snapshot stays."""
    shutil.rmtree(_pending(undo_dir(character_name, item_id, fsig)), ignore_errors=True)


def state(character_name: str, item_id: str, fsig: str) -> Optional[Dict[str, Any]]:
    """What Undo would take back, for the Wardrobe: ``{step, view, attempt, at, passing, available, why_not,
    images: [{step, view, before}], mesh_before, refusal_before}`` — ``before`` / ``mesh_before`` /
    ``refusal_before`` whether that file was there before the click (Undo puts it back; otherwise Undo removes
    what was made since). None without a snapshot. Reads files only."""
    from app.core import garment_store as gs
    from app.core.base_body import file_sha256
    try:
        folder = undo_dir(character_name, item_id, fsig)
    except ValueError:
        return None
    manifest = _read_manifest(folder)
    if manifest is None or not manifest.get("published_sha256"):
        return None
    step, view = str(manifest.get("step")), str(manifest.get("view"))
    try:
        final = gs.garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    except ValueError:
        return None
    holds = final.is_file() and file_sha256(final) == manifest["published_sha256"]
    files = manifest.get("files") or {}
    images = []
    for rel, sha in files.items():
        name = Path(rel).name
        if rel.startswith("images/") and name.endswith(".png"):
            stem = name[len(f"{item_id}_{fsig}_"):-len(".png")]
            s, _, v = stem.rpartition("_")
            images.append({"step": s, "view": v, "before": sha is not None})
    prepared = gs.garment_path(character_name, item_id, fsig, "prepared").relative_to(gs._root(character_name))
    failed = gs.garment_path(character_name, item_id, fsig, "failed").relative_to(gs._root(character_name))
    return {"step": step, "view": view, "attempt": manifest.get("attempt"), "at": manifest.get("at"),
            "passing": bool(manifest.get("passing")), "available": bool(holds),
            "why_not": "" if holds else REPLACED_SINCE, "images": images,
            "mesh_before": files.get(prepared.as_posix()) is not None,
            "refusal_before": files.get(failed.as_posix()) is not None}


def undo(character_name: str, item_id: str, fsig: str) -> Dict[str, Any]:
    """Put back what the group's last "Use this" replaced or dropped (module docstring). The caller holds the
    item's run lock. ``{step, view, attempt, restored, removed}`` (relative paths). ``UndoUnavailable`` without
    a snapshot or when the published image was replaced since."""
    from app.core import garment_mesh
    from app.core import garment_store as gs
    from app.core.base_body import file_sha256
    info = state(character_name, item_id, fsig)
    if info is None:
        raise UndoUnavailable(NOTHING_TO_UNDO)
    if not info["available"]:
        raise UndoUnavailable(info["why_not"])
    folder = undo_dir(character_name, item_id, fsig)
    manifest = _read_manifest(folder) or {}
    root = gs._root(character_name)
    restored: List[str] = []
    removed: List[str] = []
    for rel, sha in (manifest.get("files") or {}).items():
        target = root / rel
        if not (root / rel).resolve().is_relative_to(root.resolve()):
            continue
        if sha is None:
            if target.is_file():
                target.unlink()
                removed.append(rel)
            continue
        copy = folder / rel
        if not copy.is_file() or file_sha256(copy) != sha:
            raise UndoUnavailable("The kept copy is damaged — use another attempt instead")
        if not target.is_file() or file_sha256(target) != sha:
            _copy(copy, target)
            restored.append(rel)
    with garment_mesh.mesh_lock(character_name, item_id):
        for path in _mesh_attempts(character_name, item_id, fsig):
            path.unlink(missing_ok=True)
        for rel in manifest.get("mesh_attempts") or []:
            if (folder / rel).is_file() and (root / rel).resolve().is_relative_to(root.resolve()):
                _copy(folder / rel, root / rel)
    shutil.rmtree(folder, ignore_errors=True)
    from app.core import figure
    figure.invalidate()
    logger.info("Garment %s %s %s of %s: the use of attempt %s undone (restored %d, removed %d)", character_name,
                info["step"], info["view"], item_id, info["attempt"], len(restored), len(removed))
    return {"step": info["step"], "view": info["view"], "attempt": info["attempt"], "restored": restored,
            "removed": removed}
