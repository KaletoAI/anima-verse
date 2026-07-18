"""Global surface-texture library (AV3D-13).

Seamless tileable top-down ground textures for terrain tiles (road, water,
grass, …), delivered world-globally via ``GET /assets/surface-textures`` —
analogous to the animation-clip library. ``kind`` is an OPEN vocabulary
matching the location ``terrain`` field; the client gets ONE texture per
kind — the ACTIVE one. Like the image galleries and the building models,
SEVERAL versions per kind may be stored: every generation/upload adds a
timestamped file, one of them is selected. ``size_m`` = physical edge
length (default 3 m); an empty list is the normal state — the client
falls back to its built-in procedural materials.

Storage: ``worlds/<world>/surface_textures/``:

    <kind>_<ts>.jpg          — one file per version (uploads may be PNG/WebP)
    <kind>_<ts>.json         — sidecar: created_at, source, backend, prompt,
                               negative, size_m
    <kind>.jpg / <kind>.json — the legacy single-version store, stays valid
    selection.json           — {"<kind>": "<active filename>"}

Without a selection entry the NEWEST version is active. Generation runs
through the normal image pipeline — use case ``surface_texture``,
serialized on the backend GPU channel like every other render — and the
result is converted to JPEG ≤ 1024²; the sidecar records HOW the texture
was made (backend + final prompt).
"""

import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

DEFAULT_SIZE_M = 3.0
TEXTURE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# Version-timestamp suffix: unix seconds (≥ 9 digits) — kinds themselves may
# contain digits/underscores, the length keeps the split unambiguous.
_TS_RE = re.compile(r"^(.+)_(\d{9,})$")
_SEL_FILE = "selection.json"

_lock = threading.Lock()
# Running job keys "<kind>|<backend glob>" — generations of the SAME kind on
# DIFFERENT backends may run/queue concurrently (each serializes on its own
# GPU channel); only a double-click of the same kind+backend is rejected.
_generating: set = set()


def _dir(*, create: bool = False) -> Path:
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "surface_textures"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def safe_kind(kind: str) -> str:
    """Normalized kind ('' = invalid) — lowercase, url/file-safe."""
    kind = (kind or "").strip().lower()
    return kind if _KIND_RE.match(kind) else ""


def _stem_kind(stem: str) -> str:
    """Kind of a file stem: ``<kind>_<ts>`` (versioned) or ``<kind>``
    (legacy). '' when the stem is no valid kind."""
    m = _TS_RE.match(stem)
    return safe_kind(m.group(1) if m else stem)


def _sidecar_path(p: Path) -> Path:
    return p.with_suffix(".json")


def _read_meta(p: Path) -> Dict[str, Any]:
    sp = _sidecar_path(p)
    if sp.exists():
        try:
            meta = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                return meta
        except (OSError, ValueError):
            pass
    return {}


def _write_meta(p: Path, meta: Dict[str, Any]) -> None:
    _sidecar_path(p).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _created_key(p: Path) -> float:
    meta = _read_meta(p)
    ts = meta.get("created_at") or ""
    if ts:
        from app.core.timeutils import parse_iso
        try:
            return parse_iso(ts).timestamp()
        except (TypeError, ValueError):
            pass
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _files_by_kind() -> Dict[str, List[Path]]:
    """All stored texture files grouped by kind, newest first per kind."""
    d = _dir()
    if not d.is_dir():
        return {}
    out: Dict[str, List[Path]] = {}
    for p in d.iterdir():
        if not p.is_file() or p.suffix.lower() not in TEXTURE_EXTS:
            continue
        kind = _stem_kind(p.stem)
        if kind:
            out.setdefault(kind, []).append(p)
    for kind in out:
        out[kind].sort(key=_created_key, reverse=True)
    return out


def _read_selection() -> Dict[str, str]:
    sp = _dir() / _SEL_FILE
    if sp.exists():
        try:
            sel = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(sel, dict):
                return sel
        except (OSError, ValueError):
            pass
    return {}


def _write_selection(sel: Dict[str, str]) -> None:
    (_dir(create=True) / _SEL_FILE).write_text(
        json.dumps(sel, indent=2, ensure_ascii=False), encoding="utf-8")


def texture_file(kind: str) -> Optional[Path]:
    """The ACTIVE version of a kind: the selection entry when it points at an
    existing file, else the newest stored version (legacy files need no
    migration this way)."""
    kind = safe_kind(kind)
    if not kind:
        return None
    sel = _read_selection().get(kind, "")
    if sel and "/" not in sel and "\\" not in sel and ".." not in sel:
        p = _dir() / sel
        if p.exists() and _stem_kind(p.stem) == kind:
            return p
    files = _files_by_kind().get(kind) or []
    return files[0] if files else None


def file_by_name(filename: str) -> Optional[Path]:
    """Resolve a served filename (path-escape safe, known extensions only)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    p = _dir() / filename
    if not p.exists() or p.suffix.lower() not in TEXTURE_EXTS:
        return None
    return p if _stem_kind(p.stem) else None


def _size_m_of(p: Path) -> float:
    try:
        v = float(_read_meta(p).get("size_m"))
        return v if v > 0 else DEFAULT_SIZE_M
    except (TypeError, ValueError):
        return DEFAULT_SIZE_M


def set_size_m(kind: str, size_m: float, filename: str = "") -> bool:
    """Persist the physical edge length on ONE version's sidecar (default:
    the active one) — a property of the image (what area it depicts)."""
    kind = safe_kind(kind)
    if not kind:
        return False
    p = (file_by_name(filename) if filename else texture_file(kind))
    if not p or _stem_kind(p.stem) != kind:
        return False
    try:
        size_m = float(size_m)
    except (TypeError, ValueError):
        return False
    if size_m <= 0 or size_m > 100:
        return False
    meta = _read_meta(p)
    if abs(size_m - DEFAULT_SIZE_M) < 1e-9:
        meta.pop("size_m", None)
    else:
        meta["size_m"] = round(size_m, 2)
    if meta:
        _write_meta(p, meta)
    else:
        _sidecar_path(p).unlink(missing_ok=True)
    return True


def select_texture(kind: str, filename: str) -> bool:
    """Make ``filename`` the active version of its kind."""
    kind = safe_kind(kind)
    p = file_by_name(filename) if kind else None
    if not p or _stem_kind(p.stem) != kind:
        return False
    sel = _read_selection()
    sel[kind] = p.name
    _write_selection(sel)
    return True


def list_textures() -> List[Dict[str, Any]]:
    """CLIENT list — one entry per kind, the ACTIVE version:
    {kind, filename, url, size_m, size}."""
    out = []
    for kind in sorted(_files_by_kind()):
        p = texture_file(kind)
        if not p:
            continue
        out.append({
            "kind": kind,
            "filename": p.name,
            "url": f"/assets/surface-textures/{p.name}",
            "size_m": _size_m_of(p),
            "size": p.stat().st_size,
        })
    return out


def admin_list() -> List[Dict[str, Any]]:
    """Admin listing — ALL versions per kind (newest first) incl. HOW each
    was made: [{kind, versions: [{filename, url, size_m, created_at,
    source, backend, prompt, negative, active}]}]."""
    out = []
    by_kind = _files_by_kind()
    for kind in sorted(by_kind):
        active = texture_file(kind)
        versions = []
        for p in by_kind[kind]:
            meta = _read_meta(p)
            versions.append({
                "filename": p.name,
                "url": f"/assets/surface-textures/{p.name}",
                "size_m": _size_m_of(p),
                "created_at": meta.get("created_at", ""),
                "source": meta.get("source", ""),
                "backend": meta.get("backend", ""),
                "prompt": meta.get("prompt", ""),
                "negative": meta.get("negative", ""),
                "active": bool(active and p.name == active.name),
            })
        out.append({"kind": kind, "versions": versions})
    return out


def delete_texture(kind: str, filename: str = "") -> bool:
    """Remove ONE version (+ sidecar) by filename, or ALL versions of the
    kind when ``filename`` is empty. Deleting the active version moves the
    selection to the newest remaining one."""
    kind = safe_kind(kind)
    if not kind:
        return False
    if filename:
        p = file_by_name(filename)
        if not p or _stem_kind(p.stem) != kind:
            return False
        p.unlink()
        _sidecar_path(p).unlink(missing_ok=True)
    else:
        files = _files_by_kind().get(kind) or []
        if not files:
            return False
        for p in files:
            p.unlink()
            _sidecar_path(p).unlink(missing_ok=True)
    sel = _read_selection()
    if kind in sel and not (_dir() / sel[kind]).exists():
        sel.pop(kind)
        _write_selection(sel)
    return True


def _new_path(kind: str, ext: str) -> Path:
    """Fresh timestamped target file; bumps the timestamp on a collision."""
    d = _dir(create=True)
    ts = int(time.time())
    while True:
        p = d / f"{kind}_{ts}{ext}"
        if not p.exists():
            return p
        ts += 1


def save_uploaded(kind: str, contents: bytes) -> Dict[str, Any]:
    """Store an uploaded texture as a NEW version (magic-byte sniffed) and
    select it — existing versions stay."""
    kind = safe_kind(kind)
    if not kind:
        return {"ok": False, "error": "bad_kind"}
    if len(contents) > 10 * 1024 * 1024:
        return {"ok": False, "error": "too_large"}
    if contents[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif contents[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        ext = ".webp"
    else:
        return {"ok": False, "error": "not_an_image"}
    p = _new_path(kind, ext)
    p.write_bytes(contents)
    _write_meta(p, {"created_at": utc_now_iso(), "source": "uploaded"})
    select_texture(kind, p.name)
    return {"ok": True, "kind": kind, "filename": p.name}


# Subject phrases per kind — the visual character of the material, which the
# generic "<kind> ground material" wording completely failed to convey (gray
# swatches on every backend). The vocabulary stays OPEN: unknown kinds get
# the generic fallback and the phrase is editable in the tab anyway.
SURFACE_SUBJECTS: Dict[str, str] = {
    "water": "calm water surface with gentle ripples and small waves, natural blue-green tones",
    "road": "worn gray asphalt with fine grain, subtle cracks and faint tire marks",
    "grass": "dense short lawn grass, natural fresh green blades",
    "sand": "fine beach sand with slight wind ripples, warm beige tones",
    "rock": "rough natural stone with fissures and mineral speckles",
    "gravel": "small mixed gravel pebbles densely packed, varied gray-brown tones",
    "dirt": "dry brown earth with small stones, cracks and fine soil texture",
    "snow": "fresh untouched snow with fine sparkling crystals",
    "forest": "forest floor of brown leaf litter, moss patches and small twigs",
}


def surface_subject(kind: str) -> str:
    """The subject phrase for a kind (curated wording or generic fallback)."""
    kind = (kind or "").strip().lower()
    if not kind:
        return "a natural ground surface"
    return SURFACE_SUBJECTS.get(kind, f"the surface of {kind} seen straight from above")


def compose_prompt(kind: str, backend) -> Dict[str, str]:
    """Final prompt + negative for a kind on a backend — use-case style
    (``surface_texture``, per image family) plus the per-kind subject
    phrase. The dialog shows exactly this and may edit it (final-prompt
    rule); ``style`` is returned separately so the UI can recompose per
    kind."""
    from app.core import config as _cfg
    ucp = _cfg.resolve_use_case_style(
        "surface_texture",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    subject = surface_subject(kind)
    style = (ucp.get("prompt_style") or "").strip()
    return {
        "style": style,
        "prompt": f"{style}, {subject}" if style else subject,
        "negative": ucp.get("prompt_negative", ""),
    }


def _gen_key(kind: str, backend_glob: str) -> str:
    return f"{kind}|{(backend_glob or '').strip().lower()}"


def is_pending(kind: str = "") -> List[str]:
    """KINDS with at least one running generation (any backend)."""
    with _lock:
        kinds = sorted({k.split("|", 1)[0] for k in _generating})
    return kinds if not kind else ([kind] if kind in kinds else [])


def _generate(kind: str, backend_glob: str, prompt: str, negative: str) -> Dict[str, Any]:
    """Blocking generation on a worker thread — the GPU job itself runs on
    the backend queue channel like every image render. Adds a NEW version
    and selects it; the sidecar records backend + final prompt."""
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    backend = None
    if backend_glob.strip():
        backend = svc.resolve_imagegen_target(backend_glob)
    if not backend:
        backend = svc._select_backend()
    if not backend:
        logger.warning("Surface texture %s: no image backend available", kind)
        return {"ok": False, "error": "no backend available"}

    if not prompt.strip():
        composed = compose_prompt(kind, backend)
        prompt = composed["prompt"]
        if not negative.strip():
            negative = composed["negative"]

    from app.core.task_queue import get_task_queue
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "surface_texture", f"Surface texture: {kind}", start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        params: Dict[str, Any] = {
            "width": 1024, "height": 1024,
            "seed": random.randint(1, 2**31 - 1),
        }
        from app.core.llm_queue import get_llm_queue, Priority
        images = get_llm_queue().submit_gpu_task(
            provider_name=backend.name,
            task_type="surface_texture",
            priority=Priority.IMAGE_GEN,
            callable_fn=lambda: backend.generate(prompt, negative, params),
            agent_name="system",
            label=f"Surface texture: {kind}",
            gpu_type=backend.api_type)
        if not images:
            error = "empty backend result"
            return {"ok": False, "error": error}

        # Contract: JPEG preferred, ≤ 1024² — convert whatever came back.
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(images[0])).convert("RGB")
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024))
        out = _new_path(kind, ".jpg")
        img.save(out, "JPEG", quality=90)
        _write_meta(out, {
            "created_at": utc_now_iso(),
            "source": "generated",
            "backend": backend.name,
            "prompt": prompt,
            "negative": negative,
        })
        select_texture(kind, out.name)
        logger.info("Surface texture %s: %s (%d bytes, backend %s)",
                    kind, out.name, out.stat().st_size, backend.name)
        return {"ok": True, "filename": out.name}
    except Exception as e:
        error = str(e)
        logger.error("Surface texture %s failed: %s", kind, e)
        return {"ok": False, "error": error}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def trigger_generation(kind: str, *, backend_glob: str = "",
                       prompt: str = "", negative: str = "") -> bool:
    """Start a texture generation in the background. Different backends for
    the same kind run concurrently (each queues on its own GPU channel);
    False only while THIS kind+backend combination is already generating
    (double-click guard)."""
    kind = safe_kind(kind)
    if not kind:
        return False
    key = _gen_key(kind, backend_glob)
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _run() -> None:
        try:
            _generate(kind, backend_glob, prompt, negative)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return True
