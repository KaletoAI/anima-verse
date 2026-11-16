"""Ruling A128 — deleting the generated meshes of an own-mesh clothing piece (the piece dialog's Mesh row).

Two actions, both admin-only through ``routes/characters.py`` and both spending nothing:

- ``delete_mesh(n)``: one tile of the Mesh row of the piece's worn state. ``n`` > 0 is a KEPT mesh (Ruling A58: its
  slot files ``attempts/mesh/{item}_{fsig}.try{n}[.raw].glb`` and its ``kept`` entry in the step record go). ``n`` = 0
  is the mesh IN USE and needs ``in_use=True`` (the dialog's confirmation): its prepared + raw GLB go and the step
  record keeps only the kept list — the Mesh row reads ``missing``, so the mesh step is due; the fit stays served
  (like ``garments._drop_mesh``: it reads as outdated until the next fit).
- ``delete_all(include_images)``: every stored file of the piece's fingerprint groups (``garment_store.stored_groups``
  — every state, the raw/prepared meshes, kept meshes, shells, fits on every body, layers, failure records, fit
  attempts) EXCEPT the worn / piece-only / cut-out images (``images/``), which go only with ``include_images``.

Both take the piece's run lock without waiting (``garment_store.run_item_lock``: no run of the piece writes
meanwhile) and refuse a piece whose mesh job runs (``DeleteBusy``); the step record is written under
``garment_mesh.mesh_lock`` like every other writer of it. Every path comes from ``garment_store.garment_path`` /
``stored_groups`` (``safe_item_id`` + fsig pattern) and is checked again to resolve inside the character's
``garments/`` before it is unlinked. ``preview`` says before the click what rebuilding costs (``garments.run_estimate``
forced from the mesh step, or from the first image step when the images go too).
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("garment_mesh_delete")

#: Why a delete waits (409).
DELETE_BUSY = "A run of this piece is writing its files — delete after it ends"


class DeleteBusy(RuntimeError):
    """A run of the piece holds its files."""


class InUseNeedsConfirm(ValueError):
    """The mesh in use is deleted only with the confirmation (``in_use=True``)."""


def _clothing_item(character_name: str, item_id: str) -> None:
    from app.core import garments
    _item, kind = garments._item(character_name, item_id)  # noqa: SLF001 — same subsystem
    if kind != garments._clothing():  # noqa: SLF001
        raise ValueError("Only an own-mesh clothing piece has generated meshes to delete")


def _unlink(root: Path, path: Path) -> int:
    """Unlink ``path`` when it resolves inside ``root`` (the character's ``garments/``); 1 when a file went."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"garment path escapes {root}")
    if path.is_symlink() or not path.is_file():
        return 0
    path.unlink(missing_ok=True)
    return 1


def _estimate(character_name: str, item_id: str, from_step: str = "") -> Dict[str, Any]:
    from app.core import garments
    est = garments.run_estimate(character_name, item_id, from_step=from_step)
    return {"hub_jobs": est.get("hub_jobs"), "note": str(est.get("note") or ""), "steps": list(est.get("steps") or [])}


def _groups(character_name: str, item_id: str) -> Dict[str, List[Path]]:
    from app.core import garment_store as gs
    return {fsig: paths for (iid, fsig), paths in gs.stored_groups(character_name).items() if iid == item_id}


def _is_image(path: Path) -> bool:
    from app.core import garment_store as gs
    return path.parent.name == gs.PART_DIRS["image"]


def preview(character_name: str, item_id: str) -> Dict[str, Any]:
    """What the delete actions remove and what making it again costs, before the click: ``{files: {meshes,
    images}, rebuild_mesh: {hub_jobs, note, steps}, rebuild_all: {…}}`` — ``rebuild_mesh`` the run forced from the
    mesh step (the images stay), ``rebuild_all`` the run forced from the first step (the images go too). ValueError
    for an item that is no own-mesh clothing piece of the character."""
    from app.core import garment_store as gs
    _clothing_item(character_name, item_id)
    meshes = images = 0
    for paths in _groups(character_name, item_id).values():
        for path in paths:
            if _is_image(path):
                images += 1
            else:
                meshes += 1
    first = gs.GARMENT_STEPS[gs._garment_kind(item_id)][0] if gs._garment_kind(item_id) else ""  # noqa: SLF001
    return {"item_id": item_id, "files": {"meshes": meshes, "images": images},
            "rebuild_mesh": _estimate(character_name, item_id, "mesh"),
            "rebuild_all": _estimate(character_name, item_id, first)}


class _RunLock:
    """The piece's run lock taken without waiting; ``DeleteBusy`` when a run holds it or its mesh job runs."""

    def __init__(self, character_name: str, item_id: str) -> None:
        from app.core import garment_store as gs
        self.lock = gs.run_item_lock(character_name, item_id)
        self.name, self.item_id = character_name, item_id

    def __enter__(self) -> "_RunLock":
        from app.core import garment_mesh
        if not self.lock.acquire(blocking=False):
            raise DeleteBusy(DELETE_BUSY)
        if garment_mesh.running_job(self.name, self.item_id) is not None:
            self.lock.release()
            raise DeleteBusy(DELETE_BUSY)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.lock.release()


def delete_mesh(character_name: str, item_id: str, n: int, *, in_use: bool = False) -> Dict[str, Any]:
    """Delete one tile of the worn state's Mesh row: kept mesh ``n`` (1..KEPT_MAX) or, with ``n`` = 0 and
    ``in_use``, the mesh in use. ``{item_id, n, deleted (files), in_use, follow_up: {hub_jobs, note, steps}}`` —
    ``follow_up`` what a plain run costs now. ``garment_mesh.KeptUnusable`` for an empty slot, ``InUseNeedsConfirm``
    for ``n`` = 0 without ``in_use``, ``DeleteBusy`` while a run of the piece writes, ValueError for a bad slot or an
    item that is no own-mesh clothing piece."""
    from app.core import garment_mesh
    from app.core import garment_store as gs
    from app.core.timeutils import utc_now_iso
    _clothing_item(character_name, item_id)
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= garment_mesh.KEPT_MAX:
        raise ValueError(f"mesh slot must be 0..{garment_mesh.KEPT_MAX}")
    if n == 0 and not in_use:
        raise InUseNeedsConfirm("Deleting the mesh in use needs the confirmation")
    root = gs.garments_dir(character_name)
    fsig = gs.garment_fsig(character_name, item_id)
    prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
    record_path = prepared.with_suffix(".json")
    deleted = 0
    with _RunLock(character_name, item_id), garment_mesh.mesh_lock(character_name, item_id):
        record = gs.read_record(record_path)
        kept = garment_mesh.kept_entries(record)
        if n > 0:
            entry = next((e for e in kept if e["n"] == n), None)
            files = garment_mesh.attempt_files(character_name, item_id, fsig, n)
            if entry is None and files["prepared"] is None and files["raw"] is None:
                raise garment_mesh.KeptUnusable(f"No kept mesh {n} of this piece")
            for part in garment_mesh.MESH_PARTS:
                deleted += _unlink(root, gs.garment_path(character_name, item_id, fsig, part, attempt=n))
            if entry is not None:
                record["kept"] = [e for e in kept if e["n"] != n]
                gs.write_record(record_path, record)
        else:
            raw = gs.garment_path(character_name, item_id, fsig, "raw")
            if not prepared.is_file() and not raw.is_file():
                raise garment_mesh.KeptUnusable("No mesh in use for this piece")
            deleted += _unlink(root, prepared) + _unlink(root, raw)
            if kept:
                # No ``accepted`` and no ``attempts``: the Mesh row reads "missing" (the step is due); the kept
                # meshes stay usable.
                gs.write_record(record_path, {"kind": record.get("kind"), "item_id": item_id, "fsig": fsig,
                                              "kept": kept, "deleted_at": utc_now_iso()})
            else:
                deleted += _unlink(root, record_path)
    logger.info("garment mesh %s/%s: deleted %s (%d files)", character_name, item_id,
                "the mesh in use" if n == 0 else f"kept mesh {n}", deleted)
    return {"item_id": item_id, "n": n, "deleted": deleted, "in_use": n == 0,
            "follow_up": _estimate(character_name, item_id)}


def delete_all(character_name: str, item_id: str, *, include_images: bool = False) -> Dict[str, Any]:
    """Delete every mesh, kept mesh, shell, fit (every body), layer and failure record of the piece in every state;
    its images too with ``include_images``. ``{item_id, deleted: {meshes, images}, follow_up}``. ``DeleteBusy``
    while a run of the piece writes, ValueError for an item that is no own-mesh clothing piece."""
    from app.core import garment_mesh
    from app.core import garment_store as gs
    _clothing_item(character_name, item_id)
    root = gs.garments_dir(character_name)
    meshes = images = 0
    with _RunLock(character_name, item_id), garment_mesh.mesh_lock(character_name, item_id):
        for fsig, paths in _groups(character_name, item_id).items():
            for path in paths:
                if _is_image(path):
                    if include_images:
                        images += _unlink(root, path)
                else:
                    meshes += _unlink(root, path)
    logger.info("garment %s/%s: deleted all meshes (%d files)%s", character_name, item_id, meshes,
                f" and {images} images" if include_images else "")
    return {"item_id": item_id, "deleted": {"meshes": meshes, "images": images},
            "follow_up": _estimate(character_name, item_id)}
