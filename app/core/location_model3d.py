"""Location building models + room models — the 3D models of a location.

Counterpart of ``app/core/model3d.py`` for locations. Since 2026-07-16 the
store keeps SEVERAL models per subject (like the image gallery): every
generation/upload adds a timestamped file, one of them is the ACTIVE model
the clients get. Keyed by the GALLERY OWNER id so clones share their
template's models. Stored parallel to the gallery images under
``locations/<owner_id>/model3d/``:

    building.glb / building_<ts>.glb   + matching .json sidecars
    room_<room_id>[_<ts>].glb          + matching .json sidecars
    selection.json                     — {"<stem>": "<active filename>"}

The un-timestamped names are the legacy single-model store — they stay valid
entries. Without a selection entry the NEWEST file is active; generation and
upload select their new file explicitly.

Rooms (AV3D-2) use the per-room stem in the same directory. Clone records
store ``rooms: []`` and inherit the template's room list on merge, so room
ids are template-identical — a room model automatically serves every placed
clone. Every function takes an optional ``room_id``; empty = building.

The source image is a gallery image of the location (an ``image_type="building"``
render — for rooms one assigned to the room, picked by the caller); generation
goes through ``service.generate_mesh(rig="none")`` on the backend queue
channel, as a background job with a pending flag — the same busy/serialization
contract as the character mesh.
"""
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.model3d import MODEL_EXTS
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_STEM = "building"
_SEL_FILE = "selection.json"

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


def _name_re(stem: str) -> re.Pattern:
    """Filenames of a stem: ``<stem>.<ext>`` (legacy) or ``<stem>_<ts>.<ext>``."""
    exts = "|".join(e.lstrip(".") for e in MODEL_EXTS)
    return re.compile(rf"^{re.escape(stem)}(_\d+)?\.({exts})$")


def is_model_filename(filename: str, room_id: str = "") -> bool:
    """Route-level validation: the name belongs to this stem (also blocks
    path escapes and cross-stem deletes)."""
    return bool(_name_re(_stem(room_id)).match(filename or ""))


def _created_key(p: Path) -> float:
    """Sort key: sidecar created_at, falling back to file mtime."""
    meta = _read_sidecar(p)
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


def _list_files(owner_id: str, room_id: str = "") -> List[Path]:
    """All stored model files of a stem, newest first."""
    d = _model_dir(owner_id)
    if not d.is_dir():
        return []
    pat = _name_re(_stem(room_id))
    files = [p for p in d.iterdir() if p.is_file() and pat.match(p.name)]
    return sorted(files, key=_created_key, reverse=True)


def _read_sidecar(model_path: Path) -> Dict[str, Any]:
    mp = model_path.with_suffix(".json")
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _write_sidecar(model_path: Path, meta: Dict[str, Any]) -> None:
    model_path.with_suffix(".json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_selection(owner_id: str) -> Dict[str, str]:
    sp = _model_dir(owner_id) / _SEL_FILE
    if sp.exists():
        try:
            sel = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(sel, dict):
                return sel
        except (OSError, ValueError):
            pass
    return {}


def _write_selection(owner_id: str, sel: Dict[str, str]) -> None:
    (_model_dir(owner_id, create=True) / _SEL_FILE).write_text(
        json.dumps(sel, indent=2, ensure_ascii=False), encoding="utf-8")


def find_building_model(location_id: str, room_id: str = "") -> Optional[Path]:
    """The ACTIVE model file of a location/room (via the gallery owner), or
    None. Active = the selection entry when it points at an existing file,
    else the newest stored model — so the legacy single-file store keeps
    working without a migration write."""
    owner = _owner_id(location_id)
    if not owner:
        return None
    sel = _read_selection(owner).get(_stem(room_id), "")
    if sel and is_model_filename(sel, room_id):
        p = _model_dir(owner) / sel
        if p.exists():
            return p
    files = _list_files(owner, room_id)
    return files[0] if files else None


def select_model(location_id: str, filename: str, room_id: str = "") -> bool:
    """Make ``filename`` the active model of the stem. False when the file
    does not belong to the stem or is missing."""
    owner = _owner_id(location_id)
    if not owner or not is_model_filename(filename, room_id):
        return False
    if not (_model_dir(owner) / filename).exists():
        return False
    sel = _read_selection(owner)
    sel[_stem(room_id)] = filename
    _write_selection(owner, sel)
    return True


def list_models(location_id: str, room_id: str = "") -> List[Dict[str, Any]]:
    """All stored models of a stem for the admin UI, newest first:
    ``[{filename, format, created_at, backend, source, source_image,
    rotation, active}]``."""
    owner = _owner_id(location_id)
    if not owner:
        return []
    active = find_building_model(location_id, room_id)
    out: List[Dict[str, Any]] = []
    for p in _list_files(owner, room_id):
        meta = _read_sidecar(p)
        out.append({
            "filename": p.name,
            "format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "created_at": meta.get("created_at", ""),
            "backend": meta.get("backend", ""),
            "source": meta.get("source", ""),
            "source_image": meta.get("source_image", ""),
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
            "active": bool(active and p.name == active.name),
        })
    return out


def _gen_key(owner_id: str, room_id: str = "") -> str:
    return f"{owner_id}:{_stem(room_id)}"


def is_pending(location_id: str, room_id: str = "") -> bool:
    owner = _owner_id(location_id)
    with _lock:
        return bool(owner) and _gen_key(owner, room_id) in _generating


def get_building_info(location_id: str, room_id: str = "") -> Dict[str, Any]:
    """Status for the admin UI: ``{exists, pending, meta, models, backends,
    default}``. ``meta`` is the ACTIVE model's sidecar, ``models`` the full
    list (newest first); ``backends`` = all available rig-'none' mesh
    backends, ``default`` = the admin default only when its rig is 'none'."""
    from app.core.model3d import list_mesh_backends
    owner = _owner_id(location_id)
    path = find_building_model(location_id, room_id)
    out: Dict[str, Any] = {
        "exists": bool(path),
        "pending": is_pending(location_id, room_id),
        "meta": _read_sidecar(path) if (owner and path) else {},
        "models": list_models(location_id, room_id),
    }
    out.update(list_mesh_backends("none"))  # {"backends": [...], "default": ""}
    return out


def get_client_meta(location_id: str, room_id: str = "") -> Optional[Dict[str, Any]]:
    """Lean meta for the 3D client (``{format, rig, rotation}``) of the ACTIVE
    model, or None when there is none — no backend/model enumeration (that is
    the admin status's job). ``rotation`` is the admin's persisted 90°-step
    orientation fix; the client applies it to the model root on load. Map
    placement (yaw + tile size) is NOT here — that is ``map3d.rotation``/
    ``map3d.size`` on the location (rooms: ``room.layout``), delivered via
    the worldmap/locations (see schnittstellen-3d.md)."""
    p = find_building_model(location_id, room_id)
    if not p:
        return None
    meta = _read_sidecar(p)
    return {"format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "rig": meta.get("rig", "none"),
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0}}


def model_file_path(location_id: str, filename: str,
                    room_id: str = "") -> Optional[Path]:
    """Path of ONE stored model by filename (admin preview of non-active
    models). Validated against the stem; None when missing/foreign."""
    owner = _owner_id(location_id)
    if not owner or not is_model_filename(filename, room_id):
        return None
    p = _model_dir(owner) / filename
    return p if p.exists() else None


def set_rotation(location_id: str, rotation: Dict[str, Any],
                 room_id: str = "", filename: str = "") -> Dict[str, Any]:
    """Persist the admin's orientation fix ({x,y,z} in degrees, each snapped
    to 0/90/180/270) on ONE model's sidecar (default: the active model).
    Generated meshes come out arbitrarily oriented and nobody can compute
    which way is up — the admin dials it in the viewer, every client applies
    it on load. Returns the updated sidecar meta."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("no model")
    p = (model_file_path(location_id, filename, room_id) if filename
         else find_building_model(location_id, room_id))
    if not p:
        raise ValueError("no model")
    meta = _read_sidecar(p)
    cur = meta.get("rotation") or {}
    rot: Dict[str, int] = {}
    for axis in ("x", "y", "z"):
        try:
            v = int(rotation.get(axis, cur.get(axis, 0)) or 0)
        except (TypeError, ValueError):
            v = int(cur.get(axis, 0) or 0)
        rot[axis] = (v // 90 * 90) % 360
    meta["rotation"] = rot
    _write_sidecar(p, meta)
    return meta


def _new_model_path(d: Path, stem: str, suffix: str = ".glb") -> Path:
    """Fresh timestamped target file; bumps the timestamp on a collision."""
    ts = int(time.time())
    while True:
        p = d / f"{stem}_{ts}{suffix}"
        if not p.exists():
            return p
        ts += 1


def save_uploaded_building(location_id: str, contents: bytes, *,
                           source_image: str = "",
                           backend: str = "",
                           room_id: str = "") -> Dict[str, Any]:
    """Store an uploaded GLB as a NEW model of the location/room and make it
    the active one. Validation is the caller's job (validate_static_glb)."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("location not found")
    d = _model_dir(owner, create=True)
    target = _new_model_path(d, _stem(room_id))
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
    _write_sidecar(target, meta)
    select_model(location_id, target.name, room_id)
    logger.info("Location model %s%s: uploaded (%d bytes) -> %s", owner,
                f"/{room_id}" if room_id else "", len(contents), target.name)
    return meta


def _generate(location_id: str, source_image: str, backend_glob: str,
              room_id: str = "") -> Dict[str, Any]:
    """Blocking mesh generation from a gallery image of the location. Runs on a
    worker thread (see trigger_generation). Adds a NEW model and selects it —
    existing models stay (pick any of them in the admin panel)."""
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
            output_path=str(_new_model_path(d, _stem(room_id))),
            backend_glob=backend_glob,
            mesh_name=_stem(room_id) if room_id else owner,
            rig="none")
        if not res.get("ok"):
            error = str(res.get("error") or "generation failed")
            logger.error("Location model %s failed: %s", owner, error)
            return {"ok": False, "error": error}

        path = Path(res["path"])
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
        _write_sidecar(path, meta)
        select_model(location_id, path.name, room_id)
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


def delete_building_model(location_id: str, room_id: str = "",
                          filename: str = "") -> bool:
    """Remove ONE stored model (+ sidecar) by filename, or ALL models of the
    stem when ``filename`` is empty. Deleting the active model moves the
    selection to the newest remaining one. True if anything was removed."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    d = _model_dir(owner)
    removed = False
    if filename:
        p = model_file_path(location_id, filename, room_id)
        if not p:
            return False
        sidecar = p.with_suffix(".json")
        p.unlink()
        if sidecar.exists():
            sidecar.unlink()
        removed = True
    else:
        for p in _list_files(owner, room_id):
            sidecar = p.with_suffix(".json")
            p.unlink()
            if sidecar.exists():
                sidecar.unlink()
            removed = True
    # Re-point (or drop) the selection — never leave it dangling.
    sel = _read_selection(owner)
    cur = sel.get(_stem(room_id), "")
    if cur and not (d / cur).exists():
        remaining = _list_files(owner, room_id)
        if remaining:
            sel[_stem(room_id)] = remaining[0].name
        else:
            sel.pop(_stem(room_id), None)
        _write_selection(owner, sel)
    return removed
