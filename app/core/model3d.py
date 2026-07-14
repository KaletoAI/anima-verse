"""Generated 3D character models (img2mesh), cached per outfit combination.

The T-pose reference render (``app/core/model_refs.py``) is the INPUT: it is
sent to a MEDIA_TYPE=="mesh" backend (gateway alias, e.g. Trellis2-Low) which
returns a rigged model file (e.g. ``<name>_mia.fbx``). Storage mirrors the
reference renders exactly — ``characters/<name>/model3d/<signature>.<ext>``
plus a sidecar — so switching back to a known outfit reuses the cached mesh
instead of burning GPU time.

Today the generation is triggered manually from the Game-Admin 3D tab; the
outfit-change trigger is the same call (see ``generate_for_current_outfit``)
and can be wired to the debounce in model_refs later.
"""

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from app.core.log import get_logger
from app.core.model_refs import _current_outfit_state, find_ref_image
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

# Formats a mesh backend may return (the gateway picks; Trellis2 -> .fbx).
MODEL_EXTS = (".fbx", ".glb", ".gltf", ".obj", ".ply", ".vrm")

_lock = threading.Lock()
_generating: set = set()
_char_locks: Dict[str, threading.Lock] = {}


def get_model3d_options(character_name: str) -> Dict[str, Any]:
    """Per-character overrides for the mesh generation (profile field
    ``model3d_opts``). A key that is absent/None means "use the backend's
    configured default" — the default is never materialized here."""
    from app.models.character import get_character_profile
    try:
        raw = (get_character_profile(character_name) or {}).get("model3d_opts") or {}
    except Exception:
        raw = {}
    nf = raw.get("no_fingers")
    return {"no_fingers": None if nf is None else bool(nf)}


def set_model3d_options(character_name: str,
                        updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merges mesh-generation overrides into the character profile.
    ``no_fingers=None`` clears the override (back to the backend default)."""
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile(character_name) or {}
    opts = dict(profile.get("model3d_opts") or {})
    if "no_fingers" in updates:
        nf = updates["no_fingers"]
        if nf is None:
            opts.pop("no_fingers", None)
        else:
            opts["no_fingers"] = bool(nf)
    profile["model3d_opts"] = opts
    save_character_profile(character_name, profile)
    return get_model3d_options(character_name)


def get_model3d_dir(character_name: str) -> Path:
    """Directory of the generated meshes (see get_character_images_dir for the
    base-dir existence gate that avoids ghost dirs on read paths)."""
    from app.models.character import get_character_dir
    base = get_character_dir(character_name)
    d = base / "model3d"
    if base.exists():
        d.mkdir(parents=True, exist_ok=True)
    return d


def find_model3d(character_name: str,
                 signature: Optional[str] = None) -> Optional[Path]:
    """Path of the cached mesh for the given outfit combination (default: the
    currently worn one), or None."""
    if signature is None:
        try:
            _, _, signature = _current_outfit_state(character_name)
        except Exception:
            return None
    from app.models.character import get_character_dir
    d = get_character_dir(character_name) / "model3d"
    for ext in MODEL_EXTS:
        p = d / f"{signature}{ext}"
        if p.exists():
            return p
    return None


def required_rig(character_name: str) -> str:
    """Which rig this character needs: humanoids get the Mixamo 52-bone rig
    (one GLB, animation clips apply), everything else a generic rig (FBX +
    separate texture, no clips)."""
    from app.core.model_refs import is_humanoid
    return "mixamo" if is_humanoid(character_name) else "generic"


def list_mesh_backends(rig: str = "") -> Dict[str, Any]:
    """Available mesh backends (optionally only those producing ``rig``) + the
    admin default, so the generate dialog can offer a choice (Low vs High)."""
    from app.core import config
    from app.imagegen.service import get_image_service
    out = []
    try:
        svc = get_image_service()
        for b in svc.list_mesh_backends(rig):
            out.append({
                "name": b.name,
                "model": getattr(b, "model", ""),
                "cost": getattr(b, "cost", 0),
                "face_num": getattr(b, "face_num", None),
                "rig": getattr(b, "mesh_rig", "mixamo"),
            })
    except Exception as e:
        logger.debug("Mesh-Backends listen fehlgeschlagen: %s", e)
    default = str(config.get("image_generation.mesh_imagegen_default", "") or "").strip()
    if default and not any(b["name"] == default for b in out):
        default = ""  # the admin default is for another rig — don't preselect it
    return {"backends": out, "default": default}


def find_texture(character_name: str,
                 signature: Optional[str] = None) -> Optional[Path]:
    """Basecolor PNG belonging to the cached mesh (generic/FBX case), or None.
    It is stored next to the model with the same stem — same generation run."""
    model = find_model3d(character_name, signature)
    if not model:
        return None
    tex = model.with_suffix(".png")
    return tex if tex.exists() else None


def get_model3d_info(character_name: str) -> Dict[str, Any]:
    """Status of the mesh for the CURRENTLY worn outfit: cached file + meta,
    whether a T-pose input exists, and whether a generation is running.

    The model entry is what a 3D client needs: ``format`` (glb|fbx), ``rig``
    (mixamo = animation clips apply, generic = they do not), ``url`` and — in
    the FBX case only — ``texture_url``.
    """
    try:
        _, _, signature = _current_outfit_state(character_name)
    except Exception:
        signature = ""
    rig = required_rig(character_name)
    out: Dict[str, Any] = {
        "signature": signature,
        "rig": rig,
        "has_input": bool(find_ref_image(character_name, "tpose", signature)
                          if signature else None),
        "model": None,
    }
    path = find_model3d(character_name, signature) if signature else None
    if path:
        enc = quote(character_name)
        info: Dict[str, Any] = {"filename": path.name,
                                "format": path.suffix.lstrip(".").lower(),
                                "rig": rig,
                                "size": path.stat().st_size,
                                "url": f"/characters/{enc}/model3d/file"}
        meta_path = path.with_suffix(".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                info["created_at"] = meta.get("created_at", "")
                info["backend"] = meta.get("backend", "")
                info["source_filename"] = meta.get("source_filename", "")
                info["face_num"] = meta.get("face_num")
                if meta.get("rig"):
                    info["rig"] = meta["rig"]  # what it was ACTUALLY made with
            except (OSError, ValueError):
                pass
        tex = find_texture(character_name, signature)
        if tex:
            info["texture_url"] = f"/characters/{enc}/model3d/texture"
            info["texture_size"] = tex.stat().st_size
        out["model"] = info
    out["options"] = get_model3d_options(character_name)
    out.update(list_mesh_backends(rig))
    with _lock:
        out["pending"] = character_name in _generating
    return out


def _char_lock(character_name: str) -> threading.Lock:
    with _lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def generate_for_current_outfit(character_name: str, *, force: bool = False,
                                backend_glob: str = "") -> Dict[str, Any]:
    """Generates the mesh for the currently worn outfit from its T-pose render.

    Backend: ``backend_glob`` → admin default (``image_generation.
    mesh_imagegen_default``) → cheapest available mesh backend. Cached per
    combination — an existing mesh is kept unless ``force``.
    Blocking (minutes); call from a worker thread.
    """
    from app.core import config
    from app.imagegen.service import get_image_service
    from app.core.task_queue import get_task_queue

    if not backend_glob:
        backend_glob = str(
            config.get("image_generation.mesh_imagegen_default", "") or "").strip()

    _, _, signature = _current_outfit_state(character_name)
    if not force:
        cached = find_model3d(character_name, signature)
        if cached:
            logger.info("Model3D %s: Kombination %s bereits erzeugt (%s)",
                        character_name, signature, cached.name)
            return {"ok": True, "cached": True, "path": str(cached)}

    src = find_ref_image(character_name, "tpose", signature)
    if not src:
        logger.warning("Model3D %s: kein T-Pose-Bild fuer Kombination %s",
                       character_name, signature)
        return {"ok": False, "error": "no_tpose_input"}

    out_dir = get_model3d_dir(character_name)
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation", f"3D model: {character_name}",
            agent_name=character_name, start_running=True)
    except Exception:
        pass

    error = ""
    rig = required_rig(character_name)
    try:
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(out_dir / f"{signature}.fbx"),
            backend_glob=backend_glob,
            character_name=character_name,
            mesh_name=character_name,
            rig=rig,
            # Per-character override; None = the backend's configured default.
            no_fingers=get_model3d_options(character_name).get("no_fingers"))
        if not res.get("ok"):
            error = str(res.get("error") or "generation failed")
            logger.error("Model3D %s fehlgeschlagen: %s", character_name, error)
            return {"ok": False, "error": error}

        path = Path(res["path"])
        # Drop a cached mesh of the same combination in another format (e.g. an
        # old .fbx replaced by a .glb) — and its orphaned texture.
        for old in out_dir.glob(f"{signature}.*"):
            if old != path and old.suffix.lower() in MODEL_EXTS:
                old.unlink()
        if not res.get("texture_path"):
            stale_tex = path.with_suffix(".png")
            if stale_tex.exists():
                stale_tex.unlink()
        meta = {
            "created_at": utc_now_iso(),
            "backend": res.get("backend", ""),
            "format": res.get("format", path.suffix.lstrip(".").lower()),
            "rig": res.get("rig", rig),
            "has_texture": bool(res.get("texture_path")),
            "source_filename": res.get("filename", ""),
            "source_image": src.name,
            "signature": signature,
            "character": character_name,
            "no_fingers": get_model3d_options(character_name).get("no_fingers"),
        }
        path.with_suffix(".json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Model3D %s: %s (%d bytes, Kombination %s)", character_name,
                    path.name, path.stat().st_size, signature)
        return {"ok": True, "cached": False, "path": str(path),
                "filename": path.name}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def _run(character_name: str, force: bool, backend_glob: str = "") -> None:
    with _char_lock(character_name):
        try:
            generate_for_current_outfit(character_name, force=force,
                                        backend_glob=backend_glob)
        except Exception as e:
            logger.error("Model3D-Generierung fuer %s fehlgeschlagen: %s",
                         character_name, e)
        finally:
            with _lock:
                _generating.discard(character_name)


def trigger_generation(character_name: str, *, force: bool = False,
                       backend_glob: str = "") -> bool:
    """Starts the mesh generation in the background (manual button today).
    ``backend_glob`` picks the mesh backend (empty = admin default → cheapest).
    False when one is already running for this character."""
    with _lock:
        if character_name in _generating:
            return False
        _generating.add(character_name)
    threading.Thread(target=_run, args=[character_name, force, backend_glob],
                     daemon=True).start()
    return True


def delete_model3d(character_name: str, signature: Optional[str] = None) -> bool:
    """Deletes the cached mesh (+ sidecar + texture); True if removed."""
    path = find_model3d(character_name, signature)
    if not path:
        return False
    for companion in (path.with_suffix(".json"), path.with_suffix(".png")):
        if companion.exists():
            companion.unlink()
    path.unlink()
    return True
