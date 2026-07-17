"""Global surface-texture library (AV3D-13).

Seamless tileable top-down ground textures for terrain tiles (road, water,
grass, …), delivered world-globally via ``GET /assets/surface-textures`` —
analogous to the animation-clip library. ``kind`` is an OPEN vocabulary
matching the location ``terrain`` field; ONE texture per kind. The 3D
client tiles them in world scale (``size_m`` = physical edge length,
default 3 m); an empty list is the normal state — the client falls back
to its built-in procedural materials.

Storage: ``worlds/<world>/surface_textures/<kind>.jpg`` (JPEG preferred
per contract; uploads may be PNG/WebP) plus an optional ``<kind>.json``
sidecar (``{"size_m": …}`` when it differs from the default). Generation
runs through the normal image pipeline — use case ``surface_texture``,
serialized on the backend GPU channel like every other render — and the
result is converted to JPEG ≤ 1024².
"""

import json
import random
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

DEFAULT_SIZE_M = 3.0
TEXTURE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

_lock = threading.Lock()
_generating: set = set()  # kinds with a running generation


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


def texture_file(kind: str) -> Optional[Path]:
    d = _dir()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = d / f"{kind}{ext}"
        if p.exists():
            return p
    return None


def file_by_name(filename: str) -> Optional[Path]:
    """Resolve a served filename (path-escape safe, known extensions only)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    p = _dir() / filename
    if not p.exists() or p.suffix.lower() not in TEXTURE_EXTS:
        return None
    return p


def _sidecar(kind: str) -> Path:
    return _dir() / f"{kind}.json"


def _read_size_m(kind: str) -> float:
    try:
        v = float(json.loads(_sidecar(kind).read_text()).get("size_m"))
        return v if v > 0 else DEFAULT_SIZE_M
    except Exception:
        return DEFAULT_SIZE_M


def set_size_m(kind: str, size_m: float) -> bool:
    """Persist the physical edge length; the default drops the sidecar."""
    kind = safe_kind(kind)
    if not kind or not texture_file(kind):
        return False
    try:
        size_m = float(size_m)
    except (TypeError, ValueError):
        return False
    if size_m <= 0 or size_m > 100:
        return False
    if abs(size_m - DEFAULT_SIZE_M) < 1e-9:
        _sidecar(kind).unlink(missing_ok=True)
    else:
        _dir(create=True)
        _sidecar(kind).write_text(json.dumps({"size_m": round(size_m, 2)}))
    return True


def list_textures() -> List[Dict[str, Any]]:
    """All textures, sorted by kind: {kind, filename, url, size_m, size}."""
    d = _dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if p.suffix.lower() not in TEXTURE_EXTS:
            continue
        kind = safe_kind(p.stem)
        if not kind:
            continue
        out.append({
            "kind": kind,
            "filename": p.name,
            "url": f"/assets/surface-textures/{p.name}",
            "size_m": _read_size_m(kind),
            "size": p.stat().st_size,
        })
    return out


def delete_texture(kind: str) -> bool:
    kind = safe_kind(kind)
    p = texture_file(kind) if kind else None
    if not p:
        return False
    p.unlink()
    _sidecar(kind).unlink(missing_ok=True)
    return True


def save_uploaded(kind: str, contents: bytes) -> Dict[str, Any]:
    """Store an uploaded texture (magic-byte sniffed; replaces any format)."""
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
    d = _dir(create=True)
    old = texture_file(kind)
    if old and old.suffix.lower() != ext:
        old.unlink()
    (d / f"{kind}{ext}").write_bytes(contents)
    return {"ok": True, "kind": kind, "filename": f"{kind}{ext}"}


def compose_prompt(kind: str, backend) -> Dict[str, str]:
    """Final prompt + negative for a kind on a backend — use-case style
    (``surface_texture``, per image family) plus the material subject. The
    dialog shows exactly this and may edit it (final-prompt rule); ``style``
    is returned separately so the UI can recompose per kind."""
    from app.core import config as _cfg
    ucp = _cfg.resolve_use_case_style(
        "surface_texture",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    subject = f"{kind} ground material" if kind else "ground material"
    style = (ucp.get("prompt_style") or "").strip()
    return {
        "style": style,
        "prompt": f"{style}, {subject}" if style else subject,
        "negative": ucp.get("prompt_negative", ""),
    }


def is_pending(kind: str = "") -> List[str]:
    with _lock:
        return sorted(_generating) if not kind else (
            [kind] if kind in _generating else [])


def _generate(kind: str, backend_glob: str, prompt: str, negative: str) -> Dict[str, Any]:
    """Blocking generation on a worker thread — the GPU job itself runs on
    the backend queue channel like every image render."""
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
        d = _dir(create=True)
        old = texture_file(kind)
        if old and old.suffix.lower() != ".jpg":
            old.unlink()
        out = d / f"{kind}.jpg"
        img.save(out, "JPEG", quality=90)
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
    """Start a texture generation in the background. False while THIS kind
    is already generating (double-click guard)."""
    kind = safe_kind(kind)
    if not kind:
        return False
    with _lock:
        if kind in _generating:
            return False
        _generating.add(kind)

    def _run() -> None:
        try:
            _generate(kind, backend_glob, prompt, negative)
        finally:
            with _lock:
                _generating.discard(kind)

    threading.Thread(target=_run, daemon=True).start()
    return True
