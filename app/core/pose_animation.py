"""Generate, validate and publish a generated pose animation.

One job runs ONE motion model (Auto = the routed ``pose_animation`` chain, or
an explicit chain member) for 1..4 variants. Every variant is converted,
imported and checked into its own staging folder; the job then ends in
``awaiting_choice`` and only ``choose`` publishes (spec
plan-pose-animation-unimate.md §13 E9/E10). ``discard`` drops the
candidates, and a daily sweep removes those left undecided for 7 days.
"""
import hashlib
import json
import math
import os
import re
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
from app.core.pose_catalog_edit import CatalogEditError, apply_generated_entry, read_store
from app.core.task_queue import get_task_queue
from app.core.timeutils import parse_iso, utc_now, utc_now_iso
from app.imagegen.backends._gateway_job import _cancel_lost_job
from app.imagegen.service import get_image_service

logger = get_logger(__name__)

TASK_TYPE = "pose_animation"
STAGING_DIRNAME = ".pose_animation"
CANDIDATE_MAX_AGE_DAYS = 7
MAX_VARIANTS = 4
DEFAULT_VARIANTS = 3
_TASK_ID_RE = re.compile(r"task_[0-9a-f]+")
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


class ChoiceError(RuntimeError):
    """A choice or discard the job's state refuses; ``status`` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def submit(mode: str, *, key: str = "", raw_text: str = "", text: str = "",
           hint: str = "", seed: Optional[int] = None, backend: str = "",
           variants: int = DEFAULT_VARIANTS) -> str:
    """Validate an entry, the model and the variant count before enqueueing a
    non-retryable generation. An explicit model must be a usable chain member
    now — refused here, before any LLM or GPU step."""
    if mode not in ("entry", "candidate", "free"):
        raise ValueError(f"unknown mode {mode}")
    if isinstance(variants, bool) or not isinstance(variants, int) \
            or not 1 <= variants <= MAX_VARIANTS:
        raise ValueError(f"variants must be 1..{MAX_VARIANTS}")
    backend = (backend or "").strip()
    if backend:
        route = get_image_service().resolve_animation_backend(backend)
        limit = int(route.backend.motion_meta.get("max_variants", MAX_VARIANTS))
        if variants > limit:
            raise ValueError(f"'{backend}' allows at most {limit} variants")
    if mode == "entry":
        entry = pose_catalog.get_catalog("pose").get(key)
        if entry is None:
            raise ValueError("Entry not found")
        if not entry.get("solo", True):
            raise ValueError("pair poses cannot get a generated animation")
        if not _allowed_group(entry.get("group", "")):
            raise ValueError("unsupported place type")
    return get_task_queue().submit(TASK_TYPE,
        {"mode": mode, "key": key, "raw_text": raw_text, "text": text, "hint": hint, "seed": seed,
         "backend": backend, "variants": variants},
        queue_name=TASK_TYPE, max_retries=0)


REQUEST_FIELDS = (("mode", ""), ("key", ""), ("text", ""), ("raw_text", ""), ("hint", ""),
                  ("backend", ""), ("variants", DEFAULT_VARIANTS))


def recent_jobs(limit: int = 20) -> List[Dict]:
    """Expose the queue history without leaking internal payload fields."""
    jobs = []
    # Jobs still waiting for a choice stay listed past the history limit (they
    # expire after 7 days, so the extra scan is bounded).
    tasks = get_task_queue().list_recent_tasks(TASK_TYPE, limit=max(limit, 500))
    tasks = tasks[:limit] + [t for t in tasks[limit:]
                             if (t.get("progress") or {}).get("state") in ("awaiting_choice", "publishing")]
    for task in tasks:
        payload, progress = task.get("payload") or {}, task.get("progress") or {}
        jobs.append({"task_id": task["task_id"], "status": task["status"],
            "mode": payload.get("mode", ""), "key": progress.get("key", payload.get("key", "")),
            **{field: progress.get(field) for field in ("phase", "captions", "kind", "hub_job", "state",
                                                        "candidates", "backend", "generator", "chosen")},
            **{field: task.get(field) for field in ("error", "created_at", "completed_at")},
            # What the admin asked for, so a retry can reopen the dialog with it.
            # No seed: a retry draws a new one.
            "request": {field: payload.get(field, default) for field, default in REQUEST_FIELDS}})
    return jobs


def _staging_root() -> Path:
    return paths.get_clips_inbox_dir() / STAGING_DIRNAME


def _staging(task_id: str) -> Path:
    if not _TASK_ID_RE.fullmatch(str(task_id or "")):
        raise ChoiceError(404, "unknown job")
    root = _staging_root().resolve()
    path = (root / task_id).resolve()
    if path.parent != root:
        raise ChoiceError(404, "unknown job")
    return path


def candidate_clip(task_id: str, index: int) -> Path:
    """The FBX of one usable candidate, for the preview route."""
    data = _read_candidates(_staging(task_id))
    if data is None:
        raise ChoiceError(410, "the candidates are gone")
    cands = data.get("candidates") or []
    if not isinstance(index, int) or not 0 <= index < len(cands) or not cands[index].get("fbx"):
        raise ChoiceError(404, "no such candidate")
    path = Path(cands[index]["fbx"]).resolve()
    if _staging(task_id) not in path.parents or not path.is_file():
        raise ChoiceError(410, "the candidates are gone")
    return path


def _read_candidates(staging: Path) -> Optional[Dict]:
    try:
        data = json.loads((staging / "candidates.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


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
            from app.core.http_files import atomic_replace
            atomic_replace(temporary, target)
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
        if previous.exists():                    # left over by a rolled-back attempt
            shutil.rmtree(previous)
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
    if progress.get("state") == "awaiting_choice":
        # The variants were ready when the server stopped: that work is done.
        return {field: progress.get(field) for field in
                ("state", "candidates", "backend", "generator", "kind", "key")}
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
    service = get_image_service()
    try:
        route = service.resolve_animation_backend(payload.get("backend", ""))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    meta = dict(route.backend.motion_meta)
    variants = max(1, min(int(payload.get("variants") or DEFAULT_VARIANTS),
                          int(meta.get("max_variants", MAX_VARIANTS))))
    existing = None
    if mode == "entry":
        existing = pose_catalog.get_catalog("pose").get(key)
        if existing is None or not existing.get("solo", True):
            raise ValueError("entry missing or not solo")
        existing = dict(existing, key=key)
    motion_text = payload.get("raw_text", "") if mode == "candidate" else payload.get("text", "")
    prepared = prepare_motion(mode, entry=existing, text=motion_text, hint=payload.get("hint", ""),
                              caption_style=meta["caption_style"],
                              segment_seconds=float(meta["segment_seconds"]))
    entry = existing if mode == "entry" else prepared.entry
    key = key if mode == "entry" else entry["key"]
    if not _allowed_group(entry.get("group", "")):
        raise ValueError("unsupported place type")
    seed = payload.get("seed")
    if seed is None:
        seed = secrets.randbelow(2**31)
    update("hub", captions=prepared.captions, loop=prepared.loop, entry=entry, key=key, seed=seed,
           backend=route.backend.name, generator=meta["generator"], variants=variants)
    cancelled()
    rig_source = meta["motion_source"] == "reference_rig"
    source_file = paths.get_rig_file() if rig_source else paths.get_puppet_file()
    # The service checks this cancellation hook after the channel wait, before submit.
    result = service.generate_mesh_animation(str(source_file), prepared.captions, seed,
        route=route, variants=variants,
        should_cancel=lambda: tq.is_task_cancelled(tid),
        on_job_id=lambda job_id, backend_name: update("hub", hub_job=job_id, backend=backend_name),
        label=f"Pose animation: {key}")
    verdicts = result.get("results") or []
    if not result.get("ok"):
        failed = "; ".join(f"variant {i + 1}: {v.get('reason')}" for i, v in enumerate(verdicts)
                           if v.get("reason") != "unrequested result")
        raise RuntimeError("no variant passed the check" + (f" — {failed}" if failed else "")
                           + f" ({result.get('error') or 'animation generation failed'})")
    cancelled()
    staging = _staging_root() / tid
    staging.mkdir(parents=True, exist_ok=True)
    kind = animation_clips.reserve_kind(key, pose_key=key)
    update("convert", backend=result["backend"], hub_job=result.get("job_id") or progress.get("hub_job", ""),
           kind=kind)
    source = {"generator": meta["generator"], "generated_for_pose": key,
              "captions": prepared.captions, "seed": seed, "hub_job": progress["hub_job"],
              "backend": result["backend"], "model_revision": meta["model_revision"]}
    if not rig_source:
        source["puppet_sha256"] = hashlib.sha256(source_file.read_bytes()).hexdigest()
    blobs = iter(result["blobs"])
    candidates = []
    for verdict in verdicts:
        if verdict.get("reason") == "unrequested result":
            continue
        index = len(candidates)
        cand = {"index": index, "ok": False, "reasons": [], "frames": None,
                "duration_s": None, "fbx": "", "sidecar": ""}
        candidates.append(cand)
        if not verdict.get("ok"):
            cand["reasons"] = [str(verdict.get("reason") or "rejected by the backend")]
            continue
        update("convert", variant=index)
        try:
            cand.update(_build_candidate(staging / f"cand_{index}", next(blobs), kind,
                                         dict(source, variant_index=index), meta, prepared,
                                         entry["group"], cancelled, update, index))
        except _Cancelled:
            raise RuntimeError("cancelled")
        except Exception as exc:
            logger.warning("pose animation %s variant %d failed: %s", tid, index, exc)
            cand["reasons"] = [str(exc) or type(exc).__name__]
    usable = [c for c in candidates if c["ok"]]
    if not usable:
        raise RuntimeError("no variant passed the check — " + "; ".join(
            f"variant {c['index'] + 1}: {' '.join(c['reasons'])}" for c in candidates))
    (staging / "candidates.json").write_text(json.dumps({
        "task_id": tid, "created_at": utc_now_iso(), "mode": mode, "key": key, "entry": prepared.entry,
        "raw_text": payload.get("raw_text", ""), "group": entry["group"], "kind": kind,
        "candidates": [dict(c, fbx=str(c["fbx"]), sidecar=str(c["sidecar"])) for c in candidates]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    public = [_public(c) for c in candidates]
    update("choose", state="awaiting_choice", candidates=public, variant=None)
    return {"state": "awaiting_choice", "candidates": public, "backend": result["backend"],
            "generator": meta["generator"], "kind": kind, "key": key}


class _Cancelled(Exception):
    pass


def _public(cand: Dict) -> Dict:
    return {"index": cand["index"], "ok": cand["ok"], "reasons": list(cand["reasons"]),
            "frames": cand["frames"], "duration_s": cand["duration_s"], "preview": bool(cand["fbx"])}


def _build_candidate(cand_dir: Path, blob: bytes, kind: str, source: Dict, meta: Dict,
                     prepared: PreparedMotion, group: str, cancelled, update, index: int) -> Dict:
    """Convert, import, measure and check one variant into ``cand_dir``."""
    def check_cancel():
        try:
            cancelled()
        except RuntimeError:
            raise _Cancelled()

    cand_dir.mkdir(parents=True, exist_ok=True)
    if blob[:4] == b"glTF":
        src = cand_dir / "result.glb"
        inputs, params = {"src": src}, {"ref_hips_m": 1.13032, "format": "glb"}
    elif blob.startswith(b"Kaydara FBX Binary"):
        src = cand_dir / "result.fbx"
        inputs, params = {"src": src, "ref": paths.get_rig_file()}, {"format": "fbx"}
    else:
        raise ValueError("result is neither glTF nor FBX")
    src.write_bytes(blob)
    converted = runner.run("glb_to_ref_fbx", inputs=inputs, params=params, out_dir=cand_dir)
    if not converted.get("ok"):
        raise RuntimeError(converted.get("error") or "animation conversion failed")
    check_cancel()
    update("import", variant=index)
    clip = import_source(kind, Path(converted["outputs"]["motion"]), Path(converted["outputs"]["rest"]),
        out_dir=cand_dir / "clip", loop_s=1.333 if prepared.loop else None,
        root_motion="strip", source_extra=source)
    clip["meta"].update(license=meta["license"], credit=meta["credit"])
    Path(clip["sidecar"]).write_text(json.dumps(clip["meta"], ensure_ascii=False, indent=2), encoding="utf-8")
    check_cancel()
    update("check", variant=index)
    measured = runner.run("clip_measure", inputs={"clip": clip["fbx"]}, out_dir=cand_dir / "measure")
    if not measured.get("ok"):
        raise RuntimeError(measured.get("error") or "clip measurement failed")
    check_cancel()
    reasons = check_clip(clip["meta"], measured["data"], group, prepared.loop)
    data = measured["data"]
    return {"ok": not reasons, "reasons": reasons, "frames": data.get("frames"),
            "duration_s": data.get("duration_s"), "fbx": str(clip["fbx"]) if not reasons else "",
            "sidecar": str(clip["sidecar"]) if not reasons else ""}


def _set_state(task_id: str, progress: Dict, **fields) -> None:
    progress.update(**fields)
    get_task_queue().update_task_progress(task_id, progress)


def choose(task_id: str, index: int) -> Dict:
    """Publish candidate ``index`` of a job waiting for a choice — exactly once."""
    staging = _staging(task_id)
    with keyed_lock("pose_animation_choice", task_id):
        progress = get_task_queue().get_task_progress(task_id)
        state = progress.get("state")
        if not progress:
            raise ChoiceError(404, "unknown job")
        if state == "expired":
            raise ChoiceError(410, "the candidates expired")
        if state == "publishing" and progress.get("chosen") != index:
            # A publish of another variant was interrupted (server stop); only
            # that one may be finished, or the job discarded.
            raise ChoiceError(409, f"an interrupted choice of variant {int(progress.get('chosen', 0)) + 1} "
                                   "must be finished first")
        if state not in ("awaiting_choice", "publishing"):
            raise ChoiceError(409, f"the job is not waiting for a choice ({state or progress.get('phase')})")
        data = _read_candidates(staging)
        if data is None:
            raise ChoiceError(410, "the candidates are gone")
        if _age_s(data, staging) >= CANDIDATE_MAX_AGE_DAYS * 86400:
            shutil.rmtree(staging, ignore_errors=True)
            _set_state(task_id, progress, phase="expired", state="expired")
            raise ChoiceError(410, "the candidates expired")
        cands = data.get("candidates") or []
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(cands):
            raise ChoiceError(404, "no such candidate")
        cand = cands[index]
        if not cand.get("ok"):
            raise ChoiceError(422, "this variant did not pass the check")
        if not all(Path(cand.get(f) or "").is_file() for f in ("fbx", "sidecar")):
            raise ChoiceError(410, "the files of this variant are gone")
        # Reserved BEFORE the first file moves: a server stop inside the publish
        # leaves "publishing" behind, never a job open for a second variant.
        _set_state(task_id, progress, phase="publishing", state="publishing", chosen=index)
        try:
            result = _publish(tid=task_id, staging=staging, kind=data["kind"], key=data["key"],
                              clip={"sidecar": cand["sidecar"], "fbx": cand["fbx"]},
                              mode=data["mode"], entry=data.get("entry"),
                              raw_text=data.get("raw_text", ""), checked_group=data["group"])
        except (RuntimeError, CatalogEditError) as exc:
            # _publish rolled back every file and catalog change: open again.
            progress.pop("chosen", None)
            _set_state(task_id, progress, phase="choose", state="awaiting_choice")
            raise ChoiceError(409, str(exc)) from exc
        _set_state(task_id, progress, phase="published", state="published", chosen=index)
        return {**(result if isinstance(result, dict) else {}), "kind": data["kind"],
                "key": data["key"], "index": index}


def discard(task_id: str) -> Dict:
    """Drop every candidate of a job waiting for a choice."""
    staging = _staging(task_id)
    with keyed_lock("pose_animation_choice", task_id):
        progress = get_task_queue().get_task_progress(task_id)
        if not progress:
            raise ChoiceError(404, "unknown job")
        if progress.get("state") not in ("awaiting_choice", "publishing"):
            raise ChoiceError(409, f"the job is not waiting for a choice ({progress.get('state') or progress.get('phase')})")
        shutil.rmtree(staging, ignore_errors=True)
        _set_state(task_id, progress, phase="discarded", state="discarded")
        return {"task_id": task_id, "state": "discarded"}


def dismiss(task_id: str) -> Dict:
    """Remove a finished job from the list, with any staging it left behind.
    A job still running or waiting for a choice is refused (choose or discard)."""
    staging = _staging(task_id)
    with keyed_lock("pose_animation_choice", task_id):
        deleted = get_task_queue().delete_finished_task(task_id)
        if deleted is None:
            raise ChoiceError(404, "unknown job")
        if not deleted:
            raise ChoiceError(409, "the job is still running or waiting for a choice")
        shutil.rmtree(staging, ignore_errors=True)
    return {"task_id": task_id, "dismissed": True}


def _age_s(data: Optional[Dict], folder: Path) -> float:
    """Seconds since the candidates were ready (SYSTEM time). Without a
    readable stamp (a failed or interrupted job) the folder's own age."""
    try:
        return (utc_now() - parse_iso(data["created_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return utc_now().timestamp() - folder.stat().st_mtime


def sweep_candidates(max_age_days: int = CANDIDATE_MAX_AGE_DAYS) -> int:
    """Remove job staging older than ``max_age_days`` (SYSTEM time); a job still
    waiting becomes ``expired``. Returns how many folders went."""
    root = _staging_root()
    if not root.is_dir():
        return 0
    removed = 0
    for folder in root.iterdir():
        if not folder.is_dir() or not _TASK_ID_RE.fullmatch(folder.name):
            continue
        if _age_s(_read_candidates(folder), folder) < max_age_days * 86400:
            continue
        with keyed_lock("pose_animation_choice", folder.name):
            shutil.rmtree(folder, ignore_errors=True)
            progress = get_task_queue().get_task_progress(folder.name)
            if progress.get("state") in ("awaiting_choice", "publishing"):
                _set_state(folder.name, progress, phase="expired", state="expired")
        removed += 1
    if removed:
        logger.info("pose animation: removed %d expired candidate folder(s)", removed)
    return removed


def register() -> None:
    get_task_queue().register_handler(TASK_TYPE, _handle)
