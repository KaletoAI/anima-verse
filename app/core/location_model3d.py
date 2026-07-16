"""Location building models + room models — the 3D models of a location.

Counterpart of ``app/core/model3d.py`` for locations, deliberately simpler:
ONE unrigged GLB per location (buildings have no outfit analogue → no signature
cache; regenerating overwrites), keyed by the GALLERY OWNER id so clones share
their template's model. Stored parallel to the gallery images under
``locations/<owner_id>/model3d/building.glb`` + a ``building.json`` sidecar.

Rooms (AV3D-2) reuse the exact same store with a per-room stem:
``room_<room_id>.glb`` + ``room_<room_id>.json`` in the same directory. Clone
records store ``rooms: []`` and inherit the template's room list on merge, so
room ids are template-identical — a room model automatically serves every
placed clone. Every function takes an optional ``room_id``; empty = the
building model.

The source image is a gallery image of the location (an ``image_type="building"``
render — for rooms one assigned to the room, picked by the caller); generation
goes through ``service.generate_mesh(rig="none")`` on the backend queue
channel, as a background job with a pending flag — the same busy/serialization
contract as the character mesh.
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
_generating: set = set()  # "<owner id>:<stem>" keys with a running generation


def _stem(room_id: str = "") -> str:
    """File stem in the model dir: ``building`` or ``room_<room_id>``."""
    return f"room_{room_id}" if room_id else _STEM


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


def find_building_model(location_id: str, room_id: str = "") -> Optional[Path]:
    """The stored building/room model file of a location (via the gallery
    owner), or None. Globs the mesh extensions — normally ``.glb``, but a test
    run with a generic alias may have left an ``.fbx``."""
    owner = _owner_id(location_id)
    if not owner:
        return None
    d = _model_dir(owner)
    for ext in MODEL_EXTS:
        p = d / f"{_stem(room_id)}{ext}"
        if p.exists():
            return p
    return None


def _read_meta(owner_id: str, room_id: str = "") -> Dict[str, Any]:
    mp = _model_dir(owner_id) / f"{_stem(room_id)}.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _gen_key(owner_id: str, room_id: str = "") -> str:
    return f"{owner_id}:{_stem(room_id)}"


def is_pending(location_id: str, room_id: str = "") -> bool:
    owner = _owner_id(location_id)
    with _lock:
        return bool(owner) and _gen_key(owner, room_id) in _generating


def get_building_info(location_id: str, room_id: str = "") -> Dict[str, Any]:
    """Status for the admin UI: ``{exists, pending, meta, backends, default}``.
    ``backends`` = all available rig-'none' mesh backends (with face_num),
    ``default`` = the admin default only when its rig is 'none' (else empty)."""
    from app.core.model3d import list_mesh_backends
    owner = _owner_id(location_id)
    path = find_building_model(location_id, room_id)
    out: Dict[str, Any] = {
        "exists": bool(path),
        "pending": is_pending(location_id, room_id),
        "meta": _read_meta(owner, room_id) if (owner and path) else {},
    }
    out.update(list_mesh_backends("none"))  # {"backends": [...], "default": ""}
    return out


def get_client_meta(location_id: str, room_id: str = "") -> Optional[Dict[str, Any]]:
    """Lean meta for the 3D client (``{format, rig, rotation}``), or None when
    there is no model — no backend enumeration (that is the admin status's
    job). ``rotation`` is the admin's persisted 90°-step orientation fix; the
    client applies it to the model root on load. Map placement (yaw + tile
    size) is NOT here — that is ``map3d.rotation``/``map3d.size`` on the
    location (rooms: ``room.layout``), delivered via the worldmap/locations
    (see schnittstellen-3d.md)."""
    p = find_building_model(location_id, room_id)
    if not p:
        return None
    meta = _read_meta(_owner_id(location_id), room_id)
    return {"format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "rig": meta.get("rig", "none"),
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0}}


def set_rotation(location_id: str, rotation: Dict[str, Any],
                 room_id: str = "") -> Dict[str, Any]:
    """Persist the admin's orientation fix ({x,y,z} in degrees, each snapped
    to 0/90/180/270). Generated meshes come out arbitrarily oriented and
    nobody can compute which way is up — the admin dials it in the viewer,
    every client applies it on load. Returns the updated sidecar meta."""
    owner = _owner_id(location_id)
    if not owner or not find_building_model(location_id, room_id):
        raise ValueError("no model")
    meta = _read_meta(owner, room_id)
    cur = meta.get("rotation") or {}
    rot: Dict[str, int] = {}
    for axis in ("x", "y", "z"):
        try:
            v = int(rotation.get(axis, cur.get(axis, 0)) or 0)
        except (TypeError, ValueError):
            v = int(cur.get(axis, 0) or 0)
        rot[axis] = (v // 90 * 90) % 360
    meta["rotation"] = rot
    (_model_dir(owner) / f"{_stem(room_id)}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def _purge(dir_: Path, stem: str, keep: Optional[Path] = None) -> None:
    """Remove every ``<stem>.*`` file (model/texture/sidecar) except ``keep``
    — regenerating overwrites, and a format switch (glb<->fbx) must not leave
    the old model behind."""
    for old in dir_.glob(f"{stem}.*"):
        if old.is_file() and old != keep:
            old.unlink()


def save_uploaded_building(location_id: str, contents: bytes, *,
                           source_image: str = "",
                           backend: str = "",
                           room_id: str = "") -> Dict[str, Any]:
    """Store an uploaded GLB as the location's building/room model (overwrites
    any existing one). Validation is the caller's job (validate_static_glb)."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("location not found")
    d = _model_dir(owner, create=True)
    target = d / f"{_stem(room_id)}.glb"
    _purge(d, _stem(room_id), keep=target)
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
    if room_id:
        meta["room"] = room_id
    (d / f"{_stem(room_id)}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Location model %s%s: uploaded (%d bytes)", owner,
                f"/{room_id}" if room_id else "", len(contents))
    return meta


def _generate(location_id: str, source_image: str, backend_glob: str,
              room_id: str = "") -> Dict[str, Any]:
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

    # Header visibility, like the character mesh ("model3d_generation"): this
    # wrapper is the ONE tracked header task — the queue-channel entry of the
    # actual GPU job lives in the queue panel, not the header task list.
    from app.core.task_queue import get_task_queue
    label = owner
    try:
        from app.models.world import get_location_by_id, get_room_by_id
        loc = get_location_by_id(location_id) or {}
        label = loc.get("name") or owner
        if room_id:
            room = get_room_by_id(loc, room_id) or {}
            label = f"{label} / {room.get('name') or room_id}"
    except Exception:
        pass
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation",
            f"{'Room' if room_id else 'Building'} model: {label}",
            start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        d = _model_dir(owner, create=True)
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(d / f"{_stem(room_id)}.glb"),
            backend_glob=backend_glob,
            mesh_name=_stem(room_id) if room_id else owner,
            rig="none")
        if not res.get("ok"):
            error = str(res.get("error") or "generation failed")
            logger.error("Location model %s failed: %s", owner, error)
            return {"ok": False, "error": error}

        path = Path(res["path"])
        _purge(d, _stem(room_id), keep=path)  # drop a previous model of another format
        meta = {
            "created_at": utc_now_iso(),
            "source": "generated",
            "format": res.get("format", path.suffix.lstrip(".").lower() or "glb"),
            "rig": res.get("rig", "none"),
            "source_image": source_image,
            "backend": res.get("backend", ""),
            "location": owner,
        }
        if room_id:
            meta["room"] = room_id
        (d / f"{_stem(room_id)}.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Location model %s: %s (%d bytes, from %s)", owner, path.name,
                    path.stat().st_size, source_image)
        return {"ok": True, "path": str(path), "meta": meta}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def _run(location_id: str, source_image: str, backend_glob: str,
         room_id: str = "") -> None:
    owner = _owner_id(location_id)
    try:
        _generate(location_id, source_image, backend_glob, room_id)
    except Exception as e:
        logger.error("Location model generation for %s failed: %s", owner, e)
    finally:
        with _lock:
            _generating.discard(_gen_key(owner, room_id))


def trigger_generation(location_id: str, *, source_image: str,
                       backend_glob: str = "", room_id: str = "") -> bool:
    """Start the building/room-model generation in the background. False when
    one is already running for this location (owner) + stem."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    with _lock:
        if _gen_key(owner, room_id) in _generating:
            return False
        _generating.add(_gen_key(owner, room_id))
    threading.Thread(target=_run,
                     args=[location_id, source_image, backend_glob, room_id],
                     daemon=True).start()
    return True


def delete_building_model(location_id: str, room_id: str = "") -> bool:
    """Remove the location's building/room model + sidecar; True if it existed."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    removed = False
    for f in _model_dir(owner).glob(f"{_stem(room_id)}.*"):
        if f.is_file():
            f.unlink()
            removed = True
    return removed
