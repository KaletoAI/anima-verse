"""Location building models — the 3D building model of a location.

Counterpart of ``app/core/model3d.py`` for locations, deliberately simpler:
ONE unrigged GLB per location (buildings have no outfit analogue → no signature
cache; regenerating overwrites), keyed by the GALLERY OWNER id so clones share
their template's model. Stored parallel to the gallery images under
``locations/<owner_id>/model3d/building.glb`` + a ``building.json`` sidecar.

The source image is a gallery image of the location (an ``image_type="building"``
render, picked by the caller); generation goes through
``service.generate_mesh(rig="none")`` on the backend queue channel, as a
background job with a pending flag — the same busy/serialization contract as the
character mesh.
"""
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.log import get_logger
from app.core.model3d import MODEL_EXTS
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_STEM = "building"

_lock = threading.Lock()
_generating: set = set()  # gallery-owner ids with a running generation


def _owner_id(location_id: str) -> str:
    """The gallery owner id (clones redirect to their template) — the store key."""
    from app.models.world import _gallery_owner_id
    return _gallery_owner_id(location_id) or ""


def _model_dir(owner_id: str, *, create: bool = False) -> Path:
    """``locations/<owner_id>/model3d`` — created only on write paths (a read
    must not conjure a ghost directory)."""
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "locations" / owner_id / "model3d"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def find_building_model(location_id: str) -> Optional[Path]:
    """The stored building model file of a location (via the gallery owner), or
    None. Globs the mesh extensions — normally ``building.glb``, but a test run
    with a generic alias may have left ``building.fbx``."""
    owner = _owner_id(location_id)
    if not owner:
        return None
    d = _model_dir(owner)
    for ext in MODEL_EXTS:
        p = d / f"{_STEM}{ext}"
        if p.exists():
            return p
    return None


def _read_meta(owner_id: str) -> Dict[str, Any]:
    mp = _model_dir(owner_id) / f"{_STEM}.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def is_pending(location_id: str) -> bool:
    owner = _owner_id(location_id)
    with _lock:
        return bool(owner) and owner in _generating


def get_building_info(location_id: str) -> Dict[str, Any]:
    """Status for the admin UI: ``{exists, pending, meta, backends, default}``.
    ``backends`` = all available rig-'none' mesh backends (with face_num),
    ``default`` = the admin default only when its rig is 'none' (else empty)."""
    from app.core.model3d import list_mesh_backends
    owner = _owner_id(location_id)
    path = find_building_model(location_id)
    out: Dict[str, Any] = {
        "exists": bool(path),
        "pending": is_pending(location_id),
        "meta": _read_meta(owner) if (owner and path) else {},
    }
    out.update(list_mesh_backends("none"))  # {"backends": [...], "default": ""}
    return out


def get_client_meta(location_id: str) -> Optional[Dict[str, Any]]:
    """Lean meta for the 3D client (``{format, rig}``), or None when there is no
    model — no backend enumeration (that is the admin status's job)."""
    p = find_building_model(location_id)
    if not p:
        return None
    meta = _read_meta(_owner_id(location_id))
    return {"format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "rig": meta.get("rig", "none")}


def _purge(dir_: Path, keep: Optional[Path] = None) -> None:
    """Remove every ``building.*`` file (model/texture/sidecar) except ``keep``
    — regenerating overwrites, and a format switch (glb<->fbx) must not leave
    the old model behind."""
    for old in dir_.glob(f"{_STEM}.*"):
        if old.is_file() and old != keep:
            old.unlink()


def save_uploaded_building(location_id: str, contents: bytes, *,
                           source_image: str = "",
                           backend: str = "") -> Dict[str, Any]:
    """Store an uploaded GLB as the location's building model (overwrites any
    existing one). Validation is the caller's job (validate_static_glb)."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("location not found")
    d = _model_dir(owner, create=True)
    target = d / f"{_STEM}.glb"
    _purge(d, keep=target)
    target.write_bytes(contents)
    meta = {
        "created_at": utc_now_iso(),
        "source": "upload",
        "format": "glb",
        "rig": "none",
        "source_image": source_image,
        "backend": backend,
        "location": owner,
    }
    (d / f"{_STEM}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Location model %s: uploaded (%d bytes)", owner, len(contents))
    return meta


def _generate(location_id: str, source_image: str, backend_glob: str) -> Dict[str, Any]:
    """Blocking mesh generation from a gallery image of the location. Runs on a
    worker thread (see trigger_generation)."""
    from app.models.world import get_gallery_dir
    from app.imagegen.service import get_image_service
    owner = _owner_id(location_id)
    if not owner:
        return {"ok": False, "error": "location_not_found"}
    # The caller passes a gallery FILE NAME — resolve it against the location's
    # gallery dir (same owner redirect) and reject path escapes.
    if not source_image or "/" in source_image or ".." in source_image:
        return {"ok": False, "error": "bad_source_image"}
    src = get_gallery_dir(location_id) / source_image
    if not src.exists():
        logger.warning("Location model %s: source image missing (%s)", owner, source_image)
        return {"ok": False, "error": "source_image_missing"}

    d = _model_dir(owner, create=True)
    res = get_image_service().generate_mesh(
        source_image_path=str(src),
        output_path=str(d / f"{_STEM}.glb"),
        backend_glob=backend_glob,
        mesh_name=owner,
        rig="none")
    if not res.get("ok"):
        logger.error("Location model %s failed: %s", owner, res.get("error"))
        return {"ok": False, "error": str(res.get("error") or "generation failed")}

    path = Path(res["path"])
    _purge(d, keep=path)  # drop a previous model of another format
    meta = {
        "created_at": utc_now_iso(),
        "source": "generated",
        "format": res.get("format", path.suffix.lstrip(".").lower() or "glb"),
        "rig": res.get("rig", "none"),
        "source_image": source_image,
        "backend": res.get("backend", ""),
        "location": owner,
    }
    (d / f"{_STEM}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Location model %s: %s (%d bytes, from %s)", owner, path.name,
                path.stat().st_size, source_image)
    return {"ok": True, "path": str(path), "meta": meta}


def _run(location_id: str, source_image: str, backend_glob: str) -> None:
    owner = _owner_id(location_id)
    try:
        _generate(location_id, source_image, backend_glob)
    except Exception as e:
        logger.error("Location model generation for %s failed: %s", owner, e)
    finally:
        with _lock:
            _generating.discard(owner)


def trigger_generation(location_id: str, *, source_image: str,
                       backend_glob: str = "") -> bool:
    """Start the building-model generation in the background. False when one is
    already running for this location (owner)."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    with _lock:
        if owner in _generating:
            return False
        _generating.add(owner)
    threading.Thread(target=_run, args=[location_id, source_image, backend_glob],
                     daemon=True).start()
    return True


def delete_building_model(location_id: str) -> bool:
    """Remove the location's building model + sidecar; True if it existed."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    removed = False
    for f in _model_dir(owner).glob(f"{_STEM}.*"):
        if f.is_file():
            f.unlink()
            removed = True
    return removed
