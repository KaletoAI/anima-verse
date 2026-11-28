"""Per-item 3D mesh storage, generation, copying and deletion.

World-placeable items store a single unrigged GLB and its JSON metadata
sidecar (``model.glb`` + ``model.json``) inside the item's own media
directory (or the shared item directory for shared-library items).
Generation runs in a background daemon thread through the ``mesh_item``
occasion on ``get_image_service().generate_mesh(...)``.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core import glb_mesh, http_files
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso
from app.models.inventory import (
    _get_item_dir,
    _get_shared_item_dir,
    get_item,
    get_item_image_path,
)

logger = get_logger("item_mesh")

MESH_OCCASION = "mesh_item"
MODEL_FILENAME = "model.glb"
META_FILENAME = "model.json"

DEFAULT_FACE_NUM = 20000
MIN_FACE_NUM = 500
MAX_FACE_NUM = 200000
REDUCE_TOLERANCE = 1.05


def normalize_face_num(raw: Any) -> int:
    """Validate and normalize ``face_num`` into ``[MIN_FACE_NUM, MAX_FACE_NUM]``."""
    msg = f"face_num must be an integer between {MIN_FACE_NUM} and {MAX_FACE_NUM}"
    if raw is None:
        return DEFAULT_FACE_NUM
    if isinstance(raw, bool):
        raise ValueError(msg)
    if isinstance(raw, int):
        val = raw
    elif isinstance(raw, float):
        if not math.isfinite(raw) or not raw.is_integer():
            raise ValueError(msg)
        val = int(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            raise ValueError(msg)
        try:
            val = int(s, 10)
        except ValueError as exc:
            raise ValueError(msg) from exc
    else:
        raise ValueError(msg)
    if val < MIN_FACE_NUM or val > MAX_FACE_NUM:
        raise ValueError(msg)
    return val


def triangle_count(glb_bytes: bytes) -> int:
    """Return the triangle count of ``glb_bytes`` via ``glb_mesh.static_arrays``."""
    return int(len(glb_mesh.static_arrays(glb_bytes)[1]))


def _reduce_glb(src: Path, face_num: int, tris: int, out_dir: Path) -> Tuple[Path, int]:
    """Reduce ``src`` toward ``face_num`` triangles via Blender's ``lod`` script."""
    from app.blender import runner
    from app.blender.refine import unavailable_reason

    ratio = face_num / tris
    res = runner.run(
        "lod",
        inputs={"model": Path(src)},
        params={"ratios": [ratio], "merge_vertices": True},
        out_dir=Path(out_dir),
        timeout_s=600,
    )
    outputs = (res or {}).get("outputs") if isinstance(res, dict) else None
    if not isinstance(res, dict) or not res.get("ok") or not outputs:
        err = (
            (res.get("error") if isinstance(res, dict) else None)
            or unavailable_reason()
            or "no stage produced"
        )
        raise RuntimeError(str(err))
    out_path = Path(next(iter(outputs.values())))
    if not out_path.is_file():
        raise RuntimeError(unavailable_reason() or "reduced mesh output missing")
    stages = (res.get("data") or {}).get("stages") or []
    stage_tris = stages[0].get("tris") if stages and isinstance(stages[0], dict) else None
    achieved = int(stage_tris) if stage_tris is not None else triangle_count(out_path.read_bytes())
    return out_path, achieved


def _item_media_dir(item_id: str, *, create: bool = False) -> Path:
    """Return the item's media directory (shared for shared items); never create on read."""
    item = get_item(item_id)
    if item and item.get("_shared"):
        return _get_shared_item_dir(item_id, create=create)
    return _get_item_dir(item_id, create=create)


def mesh_paths(item_id: str) -> Tuple[Path, Path]:
    """Return ``(model.glb, model.json)`` for ``item_id`` without creating directories."""
    item_dir = _item_media_dir(item_id, create=False)
    return item_dir / MODEL_FILENAME, item_dir / META_FILENAME


def _read_meta(meta_path: Path) -> Dict[str, Any]:
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_meta(meta_path: Path, data: Dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    with http_files.sibling_stage(meta_path) as stage:
        stage.write_bytes(payload)
        http_files.atomic_replace(stage, meta_path)


def mesh_meta(item_id: str) -> Optional[Dict[str, Any]]:
    """Return parsed ``model.json`` plus ``version`` when ``model.glb`` exists, or ``None``.

    While a generation is running before any GLB exists, returns the JSON with
    ``status == "running"`` and no ``version`` key.
    """
    glb_path, meta_path = mesh_paths(item_id)
    has_glb = glb_path.is_file()
    has_meta = meta_path.is_file()
    if not has_glb and not has_meta:
        return None
    meta = _read_meta(meta_path) if has_meta else {}
    meta.pop("version", None)
    if has_glb:
        meta["version"] = http_files.content_version(glb_path)
        if "tris" not in meta:
            with contextlib.suppress(Exception):
                meta["tris"] = triangle_count(glb_path.read_bytes())
    return meta


def _compute_bbox(glb_bytes: bytes) -> list[float]:
    """Parse ``glb_bytes`` via ``glb_mesh.static_arrays`` and return ``[minx, miny, minz, maxx, maxy, maxz]``."""
    positions = glb_mesh.static_arrays(glb_bytes)[0]
    if len(positions) == 0:
        raise ValueError("The delivered GLB contains no vertices")
    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    return [
        round(float(lo[0]), 6),
        round(float(lo[1]), 6),
        round(float(lo[2]), 6),
        round(float(hi[0]), 6),
        round(float(hi[1]), 6),
        round(float(hi[2]), 6),
    ]


def _generate_worker(item_id: str, image_path: str, face_num: int = DEFAULT_FACE_NUM) -> None:
    """Background worker: run ``mesh_item`` generation, validate GLB and atomically publish."""
    from app.core.task_queue import get_task_queue
    from app.imagegen.service import get_image_service

    item = get_item(item_id)
    name = str((item or {}).get("name") or item_id)
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation",
            f"Item mesh: {name}",
            agent_name=name,
            start_running=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Item mesh %s: track_start failed: %s", item_id, exc)
        task_id = ""

    track_error = ""
    try:
        with keyed_lock("item_mesh", item_id):
            glb_path, meta_path = mesh_paths(item_id)
            glb_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_glb = glb_path.parent / f".model.{uuid.uuid4().hex[:8]}.glb"
            try:
                source_bytes = Path(image_path).read_bytes()
                source_sha = hashlib.sha256(source_bytes).hexdigest()

                res = get_image_service().generate_mesh(
                    source_image_path=str(image_path),
                    output_path=str(tmp_glb),
                    occasion=MESH_OCCASION,
                    mesh_name=f"item-{item_id}",
                    face_num=face_num,
                )
                if not isinstance(res, dict) or not res.get("ok"):
                    err = (res or {}).get("error") if isinstance(res, dict) else None
                    raise RuntimeError(str(err or "mesh generation failed"))

                delivered = Path(str(res.get("path") or ""))
                if not delivered.is_file():
                    raise RuntimeError("mesh generation delivered no file")

                glb_bytes = delivered.read_bytes()
                tris_delivered = triangle_count(glb_bytes)
                tris = tris_delivered
                reduce_error: Optional[str] = None
                reduced = False

                if tris_delivered > face_num * REDUCE_TOLERANCE:
                    try:
                        with tempfile.TemporaryDirectory(prefix="av-item-lod-") as lod_tmp:
                            reduced_path, reduced_tris = _reduce_glb(
                                delivered, face_num, tris_delivered, Path(lod_tmp)
                            )
                            reduced_bytes = reduced_path.read_bytes()
                            bbox = _compute_bbox(reduced_bytes)
                            glb_bytes = reduced_bytes
                            tris = reduced_tris
                            reduced = True
                    except Exception as red_exc:  # noqa: BLE001 — post-steps never discard the delivered mesh
                        reduce_error = (str(red_exc) or type(red_exc).__name__)[:300]
                        logger.warning(
                            "Item mesh %s reduction failed, keeping delivered mesh: %s",
                            item_id,
                            reduce_error,
                        )
                        bbox = _compute_bbox(glb_bytes)
                else:
                    bbox = _compute_bbox(glb_bytes)

                if not reduced and delivered.parent.resolve() == glb_path.parent.resolve():
                    http_files.atomic_replace(delivered, glb_path)
                else:
                    tmp_glb.write_bytes(glb_bytes)
                    http_files.atomic_replace(tmp_glb, glb_path)
                    if delivered != tmp_glb and delivered.parent.resolve() == glb_path.parent.resolve():
                        delivered.unlink(missing_ok=True)

                record: Dict[str, Any] = {
                    "status": "done",
                    "created_at": utc_now_iso(),
                    "source_sha": source_sha,
                    "backend": str(res.get("backend") or ""),
                    "routing": res.get("routing") or {},
                    "bbox": bbox,
                    "face_num": face_num,
                    "tris": tris,
                    "tris_delivered": tris_delivered,
                }
                if res.get("fallback_from"):
                    record["fallback_from"] = res["fallback_from"]
                if reduce_error:
                    record["reduce_error"] = reduce_error
                _write_meta(meta_path, record)
                logger.info("Item mesh %s generated via %s", item_id, record["backend"])
            except Exception as e:  # noqa: BLE001 — recorded in model.json; any previous model.glb stays
                err = (str(e) or type(e).__name__)[:300]
                track_error = err
                logger.warning("Item mesh %s failed: %s", item_id, err)
                # A failed job leaves the previous model.glb in place, so its record
                # facts stay too; only the status and the error are new.
                prior = {k: v for k, v in _read_meta(meta_path).items()
                         if k not in ("status", "error", "started_at")}
                _write_meta(meta_path, {**prior, "status": "failed", "error": err})
            finally:
                tmp_glb.unlink(missing_ok=True)
    except BaseException as exc:
        if not track_error:
            track_error = (str(exc) or type(exc).__name__)[:300]
        raise
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=track_error)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Item mesh %s: track_finish failed: %s", item_id, exc)


def start_generate(item_id: str, face_num: Any = None) -> Dict[str, Any]:
    """Queue 3D mesh generation for ``item_id`` in a background daemon thread.

    Raises:
        LookupError: when ``item_id`` does not exist.
        ValueError: when ``face_num`` is invalid or the item has no image yet.
        MediaGenerationDisabled: when media generation is switched off.
    """
    target_faces = normalize_face_num(face_num)

    item = get_item(item_id)
    if not item:
        raise LookupError(f"Item not found: {item_id}")

    image_path = get_item_image_path(item_id)
    if not image_path:
        raise ValueError("Generate the item image first")

    from app.imagegen.base import MediaGenerationDisabled, media_generation_enabled
    if not media_generation_enabled():
        raise MediaGenerationDisabled("Media generation is disabled for this world")

    _glb_path, meta_path = mesh_paths(item_id)
    # Keep the previous record's facts (bbox, source) while a new job runs: the
    # model.glb they describe is still the one served until the job publishes.
    prior = {k: v for k, v in _read_meta(meta_path).items() if k not in ("status", "error")}
    _write_meta(meta_path, {**prior, "status": "running", "started_at": utc_now_iso()})

    threading.Thread(
        target=_generate_worker,
        args=(item_id, image_path, target_faces),
        daemon=True,
        name=f"item-mesh-{item_id[:8]}",
    ).start()
    return {"status": "queued"}


def _reduce_worker(item_id: str, face_num: int) -> None:
    """Background worker: reduce an existing item mesh via Blender LOD and atomically publish."""
    from app.core.task_queue import get_task_queue

    item = get_item(item_id)
    name = str((item or {}).get("name") or item_id)
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation",
            f"Item mesh reduce: {name}",
            agent_name=name,
            start_running=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Item mesh %s: track_start failed: %s", item_id, exc)
        task_id = ""

    track_error = ""
    try:
        with keyed_lock("item_mesh", item_id):
            glb_path, meta_path = mesh_paths(item_id)
            try:
                if not glb_path.is_file():
                    raise RuntimeError("Item mesh not found")
                old_bytes = glb_path.read_bytes()
                old_tris = triangle_count(old_bytes)
                with tempfile.TemporaryDirectory(prefix="av-item-lod-") as lod_tmp:
                    reduced_path, new_tris = _reduce_glb(glb_path, face_num, old_tris, Path(lod_tmp))
                    new_bytes = reduced_path.read_bytes()
                bbox = _compute_bbox(new_bytes)
                with http_files.sibling_stage(glb_path) as stage:
                    stage.write_bytes(new_bytes)
                    http_files.atomic_replace(stage, glb_path)

                prior = {
                    k: v
                    for k, v in _read_meta(meta_path).items()
                    if k not in ("status", "error", "started_at", "reduce_error", "version")
                }
                record: Dict[str, Any] = {
                    **prior,
                    "status": "done",
                    "face_num": face_num,
                    "tris": new_tris,
                    "reduced_from": old_tris,
                    "bbox": bbox,
                }
                if "created_at" not in record:
                    record["created_at"] = utc_now_iso()
                _write_meta(meta_path, record)
                logger.info("Item mesh %s reduced (%d -> %d tris)", item_id, old_tris, new_tris)
            except Exception as e:  # noqa: BLE001 — leaves old model.glb untouched
                err = (str(e) or type(e).__name__)[:300]
                track_error = err
                logger.warning("Item mesh %s reduce failed: %s", item_id, err)
                prior = {
                    k: v
                    for k, v in _read_meta(meta_path).items()
                    if k not in ("status", "error", "started_at")
                }
                _write_meta(meta_path, {**prior, "status": "failed", "error": err})
    except BaseException as exc:
        if not track_error:
            track_error = (str(exc) or type(exc).__name__)[:300]
        raise
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=track_error)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Item mesh %s: track_finish failed: %s", item_id, exc)


def start_reduce(item_id: str, face_num: Any = None) -> Dict[str, Any]:
    """Queue Blender LOD reduction of an existing item mesh toward ``face_num`` triangles."""
    if not get_item(item_id):
        raise LookupError(f"Item not found: {item_id}")
    glb_path, meta_path = mesh_paths(item_id)
    if not glb_path.is_file():
        raise LookupError(f"Item mesh not found: {item_id}")

    target_faces = normalize_face_num(face_num)
    current_tris = triangle_count(glb_path.read_bytes())
    if current_tris <= target_faces * REDUCE_TOLERANCE:
        return {"status": "unchanged", "tris": current_tris}

    prior = {k: v for k, v in _read_meta(meta_path).items() if k not in ("status", "error")}
    _write_meta(meta_path, {**prior, "status": "running", "started_at": utc_now_iso()})

    threading.Thread(
        target=_reduce_worker,
        args=(item_id, target_faces),
        daemon=True,
        name=f"item-mesh-reduce-{item_id[:8]}",
    ).start()
    return {"status": "queued"}


def copy_from(item_id: str, source_item_id: str) -> Dict[str, Any]:
    """Copy ``model.glb`` and ``model.json`` (with ``copied_from``) from ``source_item_id`` to ``item_id``."""
    if not get_item(item_id):
        raise LookupError(f"Item not found: {item_id}")
    if not get_item(source_item_id):
        raise LookupError(f"Source item not found: {source_item_id}")

    src_glb, src_meta_path = mesh_paths(source_item_id)
    dst_glb, dst_meta_path = mesh_paths(item_id)

    lock_keys = sorted({item_id, source_item_id})
    with contextlib.ExitStack() as stack:
        for key in lock_keys:
            stack.enter_context(keyed_lock("item_mesh", key))
        if not src_glb.is_file():
            raise LookupError(f"Source item has no mesh: {source_item_id}")

        raw_glb = src_glb.read_bytes()
        dst_glb.parent.mkdir(parents=True, exist_ok=True)
        with http_files.sibling_stage(dst_glb) as stage:
            stage.write_bytes(raw_glb)
            http_files.atomic_replace(stage, dst_glb)

        src_meta = _read_meta(src_meta_path)
        dst_meta = {k: v for k, v in src_meta.items() if k not in ("version", "error")}
        dst_meta["status"] = "done"
        dst_meta["copied_from"] = source_item_id
        if "created_at" not in dst_meta:
            dst_meta["created_at"] = utc_now_iso()
        _write_meta(dst_meta_path, dst_meta)

    return mesh_meta(item_id) or dst_meta


def delete(item_id: str) -> bool:
    """Remove ``model.glb`` and ``model.json`` for ``item_id``; return ``False`` when neither existed."""
    glb_path, meta_path = mesh_paths(item_id)
    with keyed_lock("item_mesh", item_id):
        existed = glb_path.exists() or meta_path.exists()
        glb_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return existed
