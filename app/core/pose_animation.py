"""Generate, validate and publish one UniMate pose animation."""
import hashlib
import json
import math
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional

from app.blender import runner
from app.core import animation_clips, paths, pose_catalog, pose_catalog_edit
from app.core.fbx_import import BONE_NAMES, import_source
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.pose_animation_prompt import PreparedMotion, prepare_motion
from app.core.pose_catalog_edit import apply_generated_entry, read_store
from app.core.task_queue import get_task_queue
from app.imagegen.backends._gateway_job import _cancel_lost_job
from app.imagegen.service import get_image_service

logger = get_logger(__name__)

TASK_TYPE = "pose_animation"
MODEL_REVISION = "174fc755ec248d0c98f27759b7a95648e7f05905"
CREDIT = "UniMate: Linzhan Mou, Jiahui Lei, Zhiyang Dou, Chenyue Cai, Chaoyue Song, Adam Finkelstein, Szymon Rusinkiewicz. Checkpoints © 2026 Linzhan Mou."
CHECK_LIMITS = {"seam_distance": 4.1, "min_foot_y": -0.035,
                "hips_y": {"stand": (0.95, 1.20), "seat": (0.55, 0.75),
                           "ground": (0.05, 0.45), "lie": (0.05, 0.30)}}


# Finger and toe rotations are optional: rigs without those joints are legitimate.
REQUIRED_ROTATION_BONES = frozenset({
    "Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
})


def _allowed_group(group: str) -> bool:
    return group in pose_catalog.get_groups() and group in CHECK_LIMITS["hips_y"]


def submit(mode: str, *, key: str = "", raw_text: str = "", text: str = "",
           hint: str = "", seed: Optional[int] = None) -> str:
    """Validate an entry before enqueueing a non-retryable generation."""
    if mode not in ("entry", "candidate", "free"):
        raise ValueError(f"unknown mode {mode}")
    if mode == "entry":
        entry = pose_catalog.get_catalog("pose").get(key)
        if entry is None:
            raise ValueError("Entry not found")
        if not entry.get("solo", True):
            raise ValueError("pair poses cannot get a generated animation")
        if not _allowed_group(entry.get("group", "")):
            raise ValueError("unsupported place type")
    return get_task_queue().submit(TASK_TYPE,
        {"mode": mode, "key": key, "raw_text": raw_text, "text": text, "hint": hint, "seed": seed},
        queue_name=TASK_TYPE, max_retries=0)


def recent_jobs(limit: int = 20) -> List[Dict]:
    """Expose the queue history without leaking internal payload fields."""
    jobs = []
    for task in get_task_queue().list_recent_tasks(TASK_TYPE, limit=limit):
        payload, progress = task.get("payload") or {}, task.get("progress") or {}
        jobs.append({"task_id": task["task_id"], "status": task["status"],
            "mode": payload.get("mode", ""), "key": progress.get("key", payload.get("key", "")),
            **{field: progress.get(field) for field in ("phase", "captions", "kind", "hub_job")},
            **{field: task.get(field) for field in ("error", "created_at", "completed_at")}})
    return jobs


def check_clip(meta: dict, dump: dict, group: str, loop: bool) -> List[str]:
    """Fail closed on missing or nonfinite measurements."""
    reasons = []
    expected = set(BONE_NAMES["mixamo-noprefix"])
    for field, required, label in (("bones", expected, "bones"),
                                   ("rot_tracks", REQUIRED_ROTATION_BONES, "rotation tracks")):
        value = dump.get(field)
        if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
            reasons.append(f"Missing or invalid {label} measurements.")
        else:
            missing = required - set(value)
            if missing:
                reasons.append(f"Missing {label}: {', '.join(sorted(missing))}.")
    for field, allowed, label in (("loc_tracks", {"Hips"}, "translation"),
                                   ("scale_tracks", set(), "scale")):
        value = dump.get(field)
        if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
            reasons.append(f"Missing or invalid {label} track measurements.")
        else:
            forbidden = set(value) - allowed
            if forbidden:
                reasons.append(f"Forbidden {label} tracks: {', '.join(sorted(forbidden))}.")
    try:
        duration = float(dump["duration_s"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        reasons.append("Clip duration must be finite and greater than zero.")
    try:
        hips = dump["hips_y"]
        if not isinstance(hips, list) or not hips or not all(math.isfinite(float(y)) for y in hips):
            raise ValueError()
        height = median(float(y) for y in hips)
        low, high = CHECK_LIMITS["hips_y"][group]
        if not low <= height <= high:
            reasons.append(f"Median hip height {height:.3f} m is outside {low:.2f}–{high:.2f} m for {group}.")
    except (KeyError, TypeError, ValueError, OverflowError):
        reasons.append("Hip height measurements or place type are missing or invalid.")
    try:
        foot = float(dump["min_foot_y"])
        if not math.isfinite(foot):
            raise ValueError()
        if foot < CHECK_LIMITS["min_foot_y"]:
            reasons.append(f"Lowest foot joint {foot:.3f} m is below -0.035 m.")
    except (KeyError, TypeError, ValueError, OverflowError):
        reasons.append("Foot measurements are missing or invalid.")
    if loop:
        try:
            seam = float(meta["geometry"]["loop"]["seam_distance"])
            if not math.isfinite(seam) or seam < 0:
                raise ValueError()
            if seam > CHECK_LIMITS["seam_distance"]:
                reasons.append(f"Loop seam distance {seam:.3f} exceeds 4.1.")
        except (KeyError, TypeError, ValueError, OverflowError):
            reasons.append("Loop seam distance is missing or invalid.")
    return reasons


def _publish(*, tid, staging, kind, key, clip, mode, entry, raw_text, checked_group):
    """Replace owned files under the catalog transaction, including rollback."""
    def install_copy(source, target):
        # Every replace stays on the target filesystem, including restoration.
        fd, name = tempfile.mkstemp(dir=target.parent, suffix=".publish.tmp")
        os.close(fd)
        temporary = Path(name)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    tq = get_task_queue()
    # Lock order: library mutation lock before the catalog transaction.
    # Hold both through reservation, installation, catalog commit and rollback.
    with keyed_lock("clip_library", "write"), pose_catalog_edit.catalog_txn("pose"):
        if animation_clips.reserve_kind(key, pose_key=key) != kind:
            raise RuntimeError("clip name taken meanwhile — retry")
        current = pose_catalog.get_catalog("pose").get(key) if mode == "entry" else entry
        current_group = (current or {}).get("group", "")
        if current_group != checked_group or not _allowed_group(current_group):
            raise RuntimeError("place type changed or is no longer supported — generate again")
        catalog_path = pose_catalog.catalog_path("pose")
        shared_before = catalog_path.read_bytes() if catalog_path.exists() else None
        shared_mode = catalog_path.stat().st_mode & 0o777 if shared_before is not None else None
        world_before = read_store("pose", "world")["entries"]
        # Recheck only after both the keyed and cross-process locks are held,
        # immediately before the first filesystem mutation.
        if tq.is_task_cancelled(tid):
            raise RuntimeError("cancelled")
        free = paths.get_animation_clips_dir()
        free.mkdir(parents=True, exist_ok=True)
        previous = staging / "previous"
        previous.mkdir()
        targets = {suffix: free / (kind + suffix) for suffix in (".json", ".fbx")}
        saved, installed = [], []
        try:
            for target in targets.values():
                if target.exists():
                    shutil.copy2(target, previous / target.name)
                    saved.append(target)
            for suffix, source in ((".json", clip["sidecar"]), (".fbx", clip["fbx"])):
                install_copy(source, targets[suffix])
                installed.append(targets[suffix])
            result = apply_generated_entry(mode=mode, animation=kind, key=key,
                                           entry=entry, raw_text=raw_text, _locked=True)
        except Exception:
            for target in installed:
                target.unlink(missing_ok=True)
            for target in saved:
                install_copy(previous / target.name, target)
            if shared_before is None:
                catalog_path.unlink(missing_ok=True)
            elif not catalog_path.exists() or catalog_path.read_bytes() != shared_before:
                fd, name = tempfile.mkstemp(dir=catalog_path.parent, suffix=".restore.tmp")
                restore = Path(name)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(shared_before)
                    os.chmod(restore, shared_mode)
                    os.replace(restore, catalog_path)
                finally:
                    restore.unlink(missing_ok=True)
            if read_store("pose", "world")["entries"] != world_before:
                pose_catalog.replace_world_entries("pose", world_before)
            pose_catalog_edit.after_write()
            raise
        animation_clips.reload_clip_caches()
        try:
            shutil.rmtree(staging)
        except Exception:
            logger.warning("Published pose %s, but staging cleanup failed: %s", key, staging, exc_info=True)
        return result


def _handle(payload):
    tq = get_task_queue()
    tid = payload["_task_id"]
    progress = tq.get_task_progress(tid)
    if progress:
        if progress.get("hub_job"):
            try:
                backend = next((b for b in get_image_service().pool.backends
                                if b.name == progress.get("backend")), None)
                if backend is not None:
                    _cancel_lost_job(backend, progress["hub_job"])
            except Exception:
                pass
        raise RuntimeError("interrupted by restart — start the generation again")

    def update(phase, **fields):
        progress.update(phase=phase, **fields)
        tq.update_task_progress(tid, progress)

    def cancelled():
        if tq.is_task_cancelled(tid):
            raise RuntimeError("cancelled")

    mode, key = payload["mode"], payload.get("key", "")
    cancelled()
    update("llm")
    existing = None
    if mode == "entry":
        existing = pose_catalog.get_catalog("pose").get(key)
        if existing is None or not existing.get("solo", True):
            raise ValueError("entry missing or not solo")
        existing = dict(existing, key=key)
    motion_text = payload.get("raw_text", "") if mode == "candidate" else payload.get("text", "")
    prepared = prepare_motion(mode, entry=existing, text=motion_text, hint=payload.get("hint", ""))
    entry = existing if mode == "entry" else prepared.entry
    key = key if mode == "entry" else entry["key"]
    if not _allowed_group(entry.get("group", "")):
        raise ValueError("unsupported place type")
    seed = payload.get("seed")
    if seed is None:
        seed = secrets.randbelow(2**31)
    update("hub", captions=prepared.captions, loop=prepared.loop, entry=entry, key=key, seed=seed)
    cancelled()
    puppet = paths.get_puppet_file()
    puppet_sha256 = hashlib.sha256(puppet.read_bytes()).hexdigest()
    # The service checks this cancellation hook after the channel wait, before submit.
    service = get_image_service()
    result = service.generate_mesh_animation(str(puppet), prepared.captions, seed,
        route=service.resolve_animation_backend(""),
        should_cancel=lambda: tq.is_task_cancelled(tid),
        on_job_id=lambda job_id, backend_name: update("hub", hub_job=job_id, backend=backend_name), label=f"Pose animation: {key}")
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "animation generation failed")
    cancelled()
    staging = paths.get_clips_inbox_dir() / ".unimate" / tid
    staging.mkdir(parents=True, exist_ok=True)
    glb = staging / "result.glb"
    glb.write_bytes(result["blobs"][0])
    update("convert", backend=result["backend"], hub_job=result.get("job_id") or progress.get("hub_job", ""))
    converted = runner.run("glb_to_ref_fbx", inputs={"src": glb}, params={"ref_hips_m": 1.13032, "format": "glb"}, out_dir=staging)
    if not converted.get("ok"):
        raise RuntimeError(converted.get("error") or "animation conversion failed")
    cancelled()
    kind = animation_clips.reserve_kind(key, pose_key=key)
    update("import", kind=kind)
    source = {"generator": "unimate", "pose_key": key, "captions": prepared.captions,
        "seed": seed, "hub_job": progress["hub_job"], "backend": result["backend"],
        "model_revision": MODEL_REVISION, "puppet_sha256": puppet_sha256}
    clip = import_source(kind, Path(converted["outputs"]["motion"]), Path(converted["outputs"]["rest"]),
        out_dir=staging / "clip", loop_s=1.333 if prepared.loop else None,
        root_motion="strip", source_extra=source)
    clip["meta"].update(license="CC-BY-NC-4.0", credit=CREDIT)
    Path(clip["sidecar"]).write_text(json.dumps(clip["meta"], ensure_ascii=False, indent=2), encoding="utf-8")
    cancelled()
    update("check")
    measured = runner.run("clip_measure", inputs={"clip": clip["fbx"]}, out_dir=staging / "measure")
    if not measured.get("ok"):
        raise RuntimeError(measured.get("error") or "clip measurement failed")
    update("check", measurements=measured["data"])
    reasons = check_clip(clip["meta"], measured["data"], entry["group"], prepared.loop)
    if reasons:
        raise RuntimeError("check failed: " + " ".join(reasons))
    update("publish")
    return _publish(tid=tid, staging=staging, kind=kind, key=key, clip=clip,
                    mode=mode, entry=prepared.entry, raw_text=payload.get("raw_text", ""),
                    checked_group=entry["group"])


def register() -> None:
    get_task_queue().register_handler(TASK_TYPE, _handle)
