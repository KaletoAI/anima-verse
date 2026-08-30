"""Turning one CMU mocap take into a shared animation clip (core, route-free).

The CMU Graphics Lab database is free to copy, modify and redistribute (also
commercially; only reselling the data itself is excluded) and asks for the
credit the sidecar carries. That makes it the one mocap source whose clips may
travel WITH the repository, unlike the Mixamo library.

One import is: locate the take's ASF/AMC originals, hand them to Blender
(``app/blender/scripts/cmu_clip.py``) together with the project's reference
skeleton (``shared/models/rig/reference.fbx``, ``default_rig()`` — every clip
sits on that one rig), and drop the resulting ``<kind>.fbx`` (or ``<kind>__a.fbx``
+ ``<kind>__b.fbx`` for a pair) plus the ``<kind>.json`` sidecar into the
target library.

Both callers live on top of this module: the CLI ``scripts/clip_import_cmu.py``
and the catalog browser's import route. Nothing here knows about HTTP, and
nothing in ``app/`` imports from ``scripts/``.
"""
import importlib.util
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.blender import runner
from app.core import paths
from app.core.log import get_logger

logger = get_logger(__name__)

CMU_BASE = "https://mocap.cs.cmu.edu/subjects"

#: Capture rate assumed when the catalog does not know the take. 326 of the
#: 2 435 takes were recorded at 60 Hz, the rest at 120 Hz.
DEFAULT_SOURCE_FPS = 120.0


class ClipImportError(Exception):
    """A refusable import — a bad kind, a missing original, a Blender failure.

    Carries a message meant for the user; the route turns it into a 4xx.
    """


def default_cache_dir() -> Path:
    """Where downloaded ASF/AMC files are kept — storage-independent, so a
    world switch does not re-download the database."""
    return Path.home() / ".cache" / "anima-verse" / "cmu"


def fetch(url: str, dest: Path) -> Path:
    """Downloads once; the CMU server ships an incomplete certificate chain,
    so a failed verification falls back to an unverified fetch — the data is
    public and its integrity is checked by the parser, not by TLS."""
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            dest.write_bytes(r.read())
    except (urllib.error.URLError, ssl.SSLError) as e:
        logger.info("verified fetch failed (%s); retrying without verification", e)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, timeout=60, context=ctx) as r:
            dest.write_bytes(r.read())
    if dest.stat().st_size < 100:
        raise ClipImportError(f"download of {url} looks empty — wrong take id?")
    return dest


def split_take(take: str) -> Tuple[str, str]:
    """``"18_01"`` → ``("18", "01")``; raises on anything else."""
    subject, _, trial = str(take or "").strip().partition("_")
    if not (subject.isdigit() and trial.isdigit()):
        raise ClipImportError(f"take must look like 18_01, got {take!r}")
    return subject, trial


def take_files(take: str, cache: Optional[Path] = None) -> Tuple[Path, Path]:
    """``(asf, amc)`` of one take.

    The bulk-downloaded originals under ``shared/models/mocap-src/cmu`` win —
    they are already on disk and are what the catalog measured. Only a take
    missing there is fetched from CMU into the cache.
    """
    subject, _trial = split_take(take)
    local = paths.get_mocap_source_dir() / "cmu" / subject
    asf, amc = local / f"{subject}.asf", local / f"{take}.amc"
    if asf.is_file() and amc.is_file():
        return asf, amc
    cache = cache or default_cache_dir()
    return (fetch(f"{CMU_BASE}/{subject}/{subject}.asf", cache / f"{subject}.asf"),
            fetch(f"{CMU_BASE}/{subject}/{take}.amc", cache / f"{take}.amc"))


def catalog_framerate(take: str) -> float:
    """The take's capture rate from the scraped catalog (60 or 120 Hz);
    ``DEFAULT_SOURCE_FPS`` when the catalog is missing or does not know it."""
    cat = paths.get_shared_dir() / "models" / "cmu_catalog.json"
    try:
        data = json.loads(cat.read_text(encoding="utf-8"))
        subject, trial = split_take(take)
        key = f"{int(subject):02d}_{int(trial):02d}"
        for t in data.get("takes", []):
            if t.get("id") == key:
                return float(t.get("framerate") or DEFAULT_SOURCE_FPS)
    except (OSError, ValueError, ClipImportError):
        pass
    return DEFAULT_SOURCE_FPS


def default_rig() -> Path:
    """The skeleton a new clip is retargeted onto — the ONE reference file
    ``shared/models/rig/reference.fbx`` (``paths.get_rig_file()``).

    Every clip must sit on the SAME skeleton: the client measures each clip's
    standing hip height against the library median (``figures.ts
    adaptExternalClips``), so a clip driven onto a shorter rig would be read as
    "crouching" and sink into the ground.

    The reference deliberately does NOT come out of the clip library any more:
    the library is content — it may be emptied, replaced or deleted — while the
    converter's reference is part of the pipeline. Missing it is an error, not
    a reason to fall back onto whatever else carries a skeleton.
    """
    rig = paths.get_rig_file()
    if not rig.is_file():
        raise ClipImportError(
            f"reference skeleton missing: {rig} "
            "— see shared/models/rig/README.md")
    return rig


def validate_kind(raw: Any) -> str:
    """The clip kind as a file stem: lowercase, no path, no role separator.

    ``__`` is the pair-role separator (``hug__a.fbx``) and a slash would make
    the clip unreachable through the serving route — both are refused here,
    at the only place a kind is ever created.
    """
    kind = str(raw or "").strip().lower()
    if not kind:
        raise ClipImportError("kind must not be empty")
    if "__" in kind:
        raise ClipImportError("kind must not contain '__' (the pair role separator)")
    if "/" in kind or "\\" in kind or kind in (".", ".."):
        raise ClipImportError("kind must not contain a path separator")
    if Path(kind).suffix:
        raise ClipImportError("kind is a file stem, without an extension")
    return kind


def convert_take(kind: str, take_a: str, take_b: str = "", *,
                 out_dir: Optional[Path] = None, clip_set: str = "",
                 start_s: float = 0.0, end_s: Optional[float] = None,
                 anchor_s: Optional[float] = None, in_place: bool = False,
                 loop_s: Optional[float] = None,
                 source_fps: Optional[float] = None, fps: int = 30,
                 speed: float = 1.0,
                 rig: Optional[Path] = None, cache: Optional[Path] = None,
                 timeout_s: int = 900) -> Dict[str, Any]:
    """Retargets one take (or a pair) and writes the clip files.

    Returns ``{"kind", "set", "dir", "sidecar", "outputs", "seconds"}``;
    ``outputs`` maps the Blender slot (``<kind>``/``<kind>__a``/…/``sidecar``)
    to the written path. Every refusable problem raises ``ClipImportError``.
    """
    kind = validate_kind(kind)
    out = Path(out_dir) if out_dir else paths.get_animation_clips_dir()
    cset = str(clip_set or "").strip().lower()
    if cset:
        if "/" in cset or "\\" in cset or cset in (".", ".."):
            raise ClipImportError("set must be a plain directory name")
        out = out / cset

    rig = Path(rig) if rig else default_rig()
    if not rig.is_file():
        raise ClipImportError(f"rig not found: {rig} "
                              "— see shared/models/rig/README.md")

    inputs: Dict[str, Path] = {"rig": rig}
    takes: List[str] = [take_a]
    if take_b:
        takes.append(take_b)
        for role, take in zip("ab", takes):
            asf, amc = take_files(take, cache)
            inputs[f"asf_{role}"] = asf
            inputs[f"amc_{role}"] = amc
    else:
        inputs["asf"], inputs["amc"] = take_files(take_a, cache)

    params = {"kind": kind, "fps": int(fps), "start_s": float(start_s or 0.0),
              "end_s": end_s, "anchor_s": anchor_s,
              "source_fps": float(source_fps or catalog_framerate(take_a)),
              "in_place": bool(in_place), "loop_s": loop_s,
              "speed": float(speed or 1.0),
              "source_takes": takes}

    st = runner.status()
    if not st["executable"]:
        raise ClipImportError("no Blender executable found "
                           "(image_generation.blender_executable)")
    out.mkdir(parents=True, exist_ok=True)
    res = runner.run("cmu_clip", inputs=inputs, params=params, out_dir=out,
                     timeout_s=timeout_s)
    if not res["ok"]:
        raise ClipImportError(str(res.get("error") or "blender run failed"))
    return {"kind": kind, "set": cset, "dir": out,
            "sidecar": res.get("data") or {},
            "outputs": res.get("outputs") or {},
            "seconds": res.get("seconds") or 0.0}


# ------------------------------------------------------------------ preview

_cmu_module = None


def _cmu():
    """The stdlib ASF/AMC reader the Blender script uses, loaded from the
    scripts directory (it is not a package on purpose — Blender's Python
    imports it by path too)."""
    global _cmu_module
    if _cmu_module is None:
        path = Path(__file__).resolve().parents[1] / "blender" / "scripts" / "_cmu.py"
        spec = importlib.util.spec_from_file_location("_cmu", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _cmu_module = mod
    return _cmu_module


def loop_window(take: str, *, start_s: float = 0.0, end_s: Optional[float] = None,
                min_s: float = 1.0, fps: int = 30) -> Dict[str, Any]:
    """The window the converter WOULD cut for a seamless loop of at least
    ``min_s`` seconds inside [start_s, end_s] — same sampling, same seam
    metric (``_cmu.best_loop_window``), no Blender. Lets the admin preview
    play exactly the clip an import will write. Seconds are take time."""
    cmu = _cmu()
    asf, amc = take_files(take)
    sk, frames = cmu.load_clip(asf, amc)
    src = catalog_framerate(take)
    idx = cmu.resample_indices(len(frames), src, fps, start_s, end_s)
    poses = [cmu.solve_frame(sk, frames[i]) for i in idx]
    i, j, d = _best_window_from_matrix(_pose_distance_matrix(cmu, poses), fps, min_s)
    return {"take": take, "source_fps": src, "fps": fps,
            "window_start_s": round(start_s + i / fps, 3),
            "window_end_s": round(start_s + j / fps, 3),
            "seam_distance": None if d is None else round(d, 3),
            "frames": j - i}


LOOP_SUGGEST_MIN_S = (0.8, 1.5, 3.0, 6.0)
LOOP_SUGGEST_CAP_S = 40.0


def _pose_distance_matrix(cmu, poses):
    """All-pairs ``_cmu.pose_distance`` as an n×n numpy array — the SAME
    metric (summed rotation angle of LOOP_BONES + hips height), but per bone
    as one matrix product: tr(RaᵀRb) = ⟨vec Ra, vec Rb⟩, so the n×9 flattened
    rotations against themselves give every pair's trace at once. 1 200
    frames (40 s) take well under a second instead of the pure-Python 48 s."""
    import numpy as np
    n = len(poses)
    total = np.zeros((n, n))
    for name in cmu.LOOP_BONES:
        if name not in poses[0].rot:
            continue
        flat = np.array([[v for row in p.rot[name] for v in row] for p in poses])   # n×9
        tr = flat @ flat.T
        total += np.arccos(np.clip((tr - 1.0) / 2.0, -1.0, 1.0))
    hips = np.array([p.pos["root"][1] for p in poses]) / 100.0
    total += np.abs(hips[:, None] - hips[None, :])
    return total


def _best_window_from_matrix(dist, fps: int, min_s: float):
    """``(i, j, distance)`` of the best-closing window with j − i ≥ min_s·fps,
    read off the distance matrix (upper triangle beyond the minimum length)."""
    import numpy as np
    n = dist.shape[0]
    min_len = max(2, int(round(min_s * fps)))
    if n <= min_len + 1:
        return 0, n, None
    mask = np.triu(np.ones((n, n), dtype=bool), k=min_len)
    masked = np.where(mask, dist, np.inf)
    flat = int(np.argmin(masked))
    i, j = divmod(flat, n)
    return int(i), int(j), float(masked[i, j])


def loop_suggestions(take: str, fps: int = 30) -> Dict[str, Any]:
    """Candidate loop windows of a take for the catalog's Start/End fields:
    for each minimum length in LOOP_SUGGEST_MIN_S the best-closing window
    (``_cmu.best_loop_window``), the take capped at LOOP_SUGGEST_CAP_S so
    the O(n²) search stays under a second or two. Windows that coincide
    (same cut within a frame) are reported once, sorted by seam distance —
    the first is the cleanest cycle the take has."""
    cmu = _cmu()
    asf, amc = take_files(take)
    sk, frames = cmu.load_clip(asf, amc)
    src = catalog_framerate(take)
    idx = cmu.resample_indices(len(frames), src, fps, 0.0, LOOP_SUGGEST_CAP_S)
    poses = [cmu.solve_frame(sk, frames[i]) for i in idx]
    dist = _pose_distance_matrix(cmu, poses)
    seen = {}
    for min_s in LOOP_SUGGEST_MIN_S:
        i, j, d = _best_window_from_matrix(dist, fps, min_s)
        if d is None:
            continue
        key = (i, j)
        if key not in seen:
            seen[key] = {"start_s": round(i / fps, 3), "end_s": round(j / fps, 3),
                         "length_s": round((j - i) / fps, 3), "min_s": min_s,
                         "seam_distance": round(d, 3)}
    out = sorted(seen.values(), key=lambda w: w["seam_distance"])
    return {"take": take, "fps": fps, "source_fps": src,
            "searched_s": round(len(poses) / fps, 3), "windows": out}
