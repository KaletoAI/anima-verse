"""The character's 3D model for the current outfit — cached per combination.

There is ONE model per outfit combination, produced in one of two ways:

* GENERATED: the T-pose reference render (``app/core/model_refs.py``) is sent
  to a MEDIA_TYPE=="mesh" backend (gateway alias, e.g. Trellis2-Low), which
  returns a rigged model file.
* UPLOADED: the user drops a GLB (or FBX+PNG) in the Game-Admin 3D tab.

Both write ``characters/<name>/model3d/<signature>.<ext>`` (+ a ``.png``
texture for FBX, + a ``.json`` sidecar recording ``source``/``rig``/…), so an
upload and a generation are interchangeable and either one is "the current
model". Switching back to a known outfit reuses whatever is stored.
"""

import json
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from app.core.log import get_logger
from app.core.model_refs import current_outfit_state, find_ref_image
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
    return {"no_fingers": None if nf is None else bool(nf),
            # Auto-generate the mesh on the CHEAPEST backend as soon as a
            # fresh T-pose render of a new outfit combination succeeds.
            "auto_generate": bool(raw.get("auto_generate"))}


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
    if "auto_generate" in updates:
        if updates["auto_generate"]:
            opts["auto_generate"] = True
        else:
            opts.pop("auto_generate", None)
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
    currently worn one), or None.

    ``signature=None`` = serving semantics: exact (outfit + state) match
    first, then the neutral entry of the same outfit — an active state must
    not make the character's model vanish while its variant is unrendered.
    An explicit signature is matched exactly (generation paths)."""
    candidates = [signature]
    if signature is None:
        try:
            _, _, sig = current_outfit_state(character_name)
        except Exception:
            return None
        from app.core.model_refs import neutral_signature
        candidates = list(dict.fromkeys([sig, neutral_signature(sig)]))
    from app.models.character import get_character_dir
    d = get_character_dir(character_name) / "model3d"
    for sig in candidates:
        for ext in MODEL_EXTS:
            p = d / f"{sig}{ext}"
            if p.exists():
                return p
    return None


def _stored_manifest(character_name: str, signature: str) -> Optional[Dict[str, Any]]:
    """``{pieces, items}`` a stored mesh stands for: its own sidecar first,
    else the T-pose sidecar of the same signature (meshes from before the
    manifest field, 2026-07 — the render input always recorded its equipped
    state). None when neither knows."""
    from app.core.outfit_cache_gc import read_manifest
    from app.models.character import get_character_dir
    base = get_character_dir(character_name)
    manifest = read_manifest(base / "model3d" / f"{signature}.json")
    if manifest is not None:
        return manifest
    for kind in ("tpose", "tpose_animal"):
        manifest = read_manifest(base / "model_refs" / f"{kind}_{signature}.json")
        if manifest is not None:
            return manifest
    return None


def find_model3d_serving(character_name: str) -> tuple:
    """(path, match) of the mesh to SERVE for the worn outfit — the serving
    chain behind the byte/meta routes. ``match`` is how it was found:
    ``"exact"`` / ``"neutral"`` (state variant unrendered) / ``"nearest"``
    (no entry for this combination — the stored mesh whose recorded piece
    combination is closest to the worn one, so a fresh outfit never degrades
    the character to a placeholder figure). (None, "") without any match.

    Management paths (delete, rig update, generation skip-check) keep
    find_model3d's exact semantics — "the nearest neighbour" is never the
    entry to delete or overwrite."""
    try:
        pieces, items, sig = current_outfit_state(character_name)
    except Exception:
        return None, ""
    from app.core.model_refs import neutral_signature
    from app.models.character import get_character_dir
    d = get_character_dir(character_name) / "model3d"
    tried = []
    for s, match in ((sig, "exact"), (neutral_signature(sig), "neutral")):
        if s in tried:
            continue
        tried.append(s)
        for ext in MODEL_EXTS:
            p = d / f"{s}{ext}"
            if p.exists():
                return p, match
    best = None
    if d.is_dir():
        from app.core.model_refs import STATE_SIG_SEP
        from app.core.outfit_match import outfit_similarity
        for p in d.iterdir():
            if p.suffix.lower() not in MODEL_EXTS:
                continue
            manifest = _stored_manifest(character_name, p.stem)
            if manifest is None:
                continue
            score = outfit_similarity(pieces, items,
                                      manifest["pieces"], manifest["items"])
            # Ties: prefer the neutral (state-free) entry, then the newest.
            key = (score, STATE_SIG_SEP not in p.stem, p.stat().st_mtime)
            if best is None or key > best[0]:
                best = (key, p)
    if best is not None:
        logger.debug("Model3D %s: nearest %s fuer Kombination %s (score %.2f)",
                     character_name, best[1].stem, sig, best[0][0])
        return best[1], "nearest"
    return None, ""


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
                # 0 = no cap. A backend that HANGS above a face count (rather
                # than failing) needs the dialog to stop the value, not the job.
                "face_num_max": getattr(b, "face_num_max", 0),
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
    """Basecolor image belonging to the cached mesh (generic/FBX case), or
    None. Stored next to the model with the same stem — same generation run.
    PNG or JPEG (the gateway prefers JPEG since 2026-07-17)."""
    model = find_model3d(character_name, signature)
    if not model:
        return None
    for ext in (".png", ".jpg", ".jpeg"):
        tex = model.with_suffix(ext)
        if tex.exists():
            return tex
    return None


def get_model3d_info(character_name: str) -> Dict[str, Any]:
    """Status of the mesh for the CURRENTLY worn outfit: cached file + meta,
    whether a T-pose input exists, and whether a generation is running.

    The model entry is what a 3D client needs: ``format`` (glb|fbx), ``rig``
    (mixamo = animation clips apply, generic = they do not), ``url`` and — in
    the FBX case only — ``texture_url``.
    """
    try:
        _, _, signature = current_outfit_state(character_name)
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
    # Serving semantics (like the file route): exact state variant first,
    # neutral fallback, then the nearest stored combination — meta and
    # served file must agree.
    path, match = find_model3d_serving(character_name) if signature else (None, "")
    if path:
        enc = quote(character_name)
        info: Dict[str, Any] = {"filename": path.name,
                                # Identity of the SERVED file — clients key
                                # model reloads on this, so the swap from a
                                # nearest neighbour to the freshly generated
                                # exact mesh is a visible change.
                                "signature": path.stem,
                                "match": match,
                                "format": path.suffix.lstrip(".").lower(),
                                "rig": rig,
                                "size": path.stat().st_size,
                                "url": f"/characters/{enc}/model3d/file"}
        info["source"] = "generated"  # default for legacy sidecars
        meta_path = path.with_suffix(".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                info["source"] = meta.get("source", "generated")
                info["created_at"] = meta.get("created_at", "")
                info["backend"] = meta.get("backend", "")
                info["source_filename"] = meta.get("source_filename", "")
                info["face_num"] = meta.get("face_num")
                if meta.get("rig"):
                    info["rig"] = meta["rig"]  # what it was ACTUALLY made with
            except (OSError, ValueError):
                pass
        # FBX case only — a GLB embeds its textures; a stray image next to a
        # GLB is an auxiliary material map, never the basecolor.
        if info["format"] == "fbx":
            tex = find_texture(character_name, path.stem)
            if tex:
                info["texture_url"] = f"/characters/{enc}/model3d/texture"
                info["texture_size"] = tex.stat().st_size
        out["model"] = info
    out["options"] = get_model3d_options(character_name)
    out.update(list_mesh_backends(rig))
    with _lock:
        out["pending"] = character_name in _generating
    return out


def _purge_combination(out_dir: Path, signature: str) -> None:
    """Remove any stored model of this outfit combination (model + texture +
    sidecar), whatever its format/source — the caller writes a fresh one."""
    for old in out_dir.glob(f"{signature}.*"):
        if old.suffix.lower() in MODEL_EXTS + (".png", ".jpg", ".jpeg", ".json"):
            old.unlink()


def save_uploaded_model(character_name: str, original_filename: str,
                        contents: bytes, *, rig: str,
                        texture: Optional[bytes] = None) -> Dict[str, Any]:
    """Stores an uploaded model as the current outfit's model (replacing any
    generated or previously uploaded one). ``texture`` is the basecolor PNG
    that belongs to an FBX; a GLB embeds its textures. Validation is the
    caller's job (app/core/model_validate.py)."""
    ext = Path(original_filename.lower()).suffix
    pieces, items, signature = current_outfit_state(character_name)
    out_dir = get_model3d_dir(character_name)
    _purge_combination(out_dir, signature)
    target = out_dir / f"{signature}{ext}"
    target.write_bytes(contents)
    if texture is not None:
        target.with_suffix(".png").write_bytes(texture)
    meta = {
        "created_at": utc_now_iso(),
        "source": "upload",
        "format": ext.lstrip("."),
        "rig": rig,
        "has_texture": texture is not None,
        "source_filename": original_filename,
        "signature": signature,
        "character": character_name,
        # Manifest (outfit_cache_gc) — an upload is made FOR the worn
        # combination, so its pieces are exactly what this signature stands for.
        "pieces": dict(pieces or {}),
        "items": list(items or []),
    }
    target.with_suffix(".json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Model3D %s: Upload %s (%d bytes, Kombination %s)",
                character_name, target.name, len(contents), signature)
    return meta


def set_model3d_rig(character_name: str, rig: str) -> Optional[Dict[str, Any]]:
    """Updates the rig in the current outfit's model sidecar; None if none."""
    path = find_model3d(character_name)
    if not path:
        return None
    meta_path = path.with_suffix(".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    except (OSError, ValueError):
        meta = {}
    meta["rig"] = rig
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


# Formats the per-outfit v2 store can actually serve/animate (the upload route
# accepts exactly these). VRM and other exotic formats are not v2-uploadable.
_MIGRATABLE_EXTS = (".glb", ".fbx")


def migrate_legacy_model_store_once() -> None:
    """One-time import of the pre-per-outfit global model store into v2.

    The old ``characters/<name>/model/`` folder (a single global upload) lost
    all its management routes long ago; the only thing still reading it was a
    serving fallback in the model route — the kind of backward-compat reader the
    project bans (a stale model was unremovable and reappeared on every outfit
    switch). Import the legacy GLB/FBX to the CURRENT outfit's v2 slot (same path
    an upload takes) and delete the legacy folder. VRM (and any other non-v2
    format) is left in place with a warning for the admin to convert or remove.

    Idempotent without a marker: a migrated character has no legacy folder, so a
    re-scan is a no-op (this also catches a legacy folder arriving via import)."""
    from app.models.character import (MODEL_RIG_VALUES, get_character_dir,
                                      list_available_characters)
    migrated = 0
    left_behind: list = []
    for name in list_available_characters():
        try:
            legacy_dir = get_character_dir(name) / "model"
            if not legacy_dir.is_dir():
                continue
            model_file = next(iter(sorted(legacy_dir.glob("model.*"))), None)
            if model_file is None:
                continue  # empty folder (e.g. an auto-created dir) — leave it
            if model_file.suffix.lower() not in _MIGRATABLE_EXTS:
                left_behind.append(f"{name} ({model_file.name})")
                continue
            # Never overwrite a per-outfit model the character already has for
            # the currently worn outfit — the old global upload is the fallback.
            try:
                _, _, signature = current_outfit_state(name)
            except Exception:
                signature = ""
            if signature and find_model3d(name, signature):
                continue  # v2 already covers this outfit — leave the legacy folder
            rig = required_rig(name)
            orig_name = model_file.name
            meta_path = legacy_dir / "meta.json"
            if meta_path.exists():
                try:
                    lm = json.loads(meta_path.read_text(encoding="utf-8"))
                    rig = str(lm.get("rig") or rig).strip().lower()
                    orig_name = str(lm.get("original_filename") or orig_name)
                except (OSError, ValueError):
                    pass
            if rig not in MODEL_RIG_VALUES:
                rig = required_rig(name)
            tex_path = legacy_dir / "texture.png"
            texture = tex_path.read_bytes() if tex_path.exists() else None
            save_uploaded_model(name, orig_name, model_file.read_bytes(),
                                rig=rig, texture=texture)
            shutil.rmtree(legacy_dir, ignore_errors=True)
            migrated += 1
        except Exception as e:
            logger.warning("Legacy 3D-model migration for %s failed: %s", name, e)
    if migrated:
        logger.info("Legacy 3D-model migration: %d character(s) imported into "
                    "the per-outfit store", migrated)
    if left_behind:
        logger.warning(
            "Legacy 3D-model migration: %d model(s) not imported (the per-outfit "
            "store serves only GLB/FBX) — left in characters/<name>/model/ for "
            "you to convert or remove: %s", len(left_behind), ", ".join(left_behind))


def _char_lock(character_name: str) -> threading.Lock:
    with _lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def _ref_manifest(ref_image: Path) -> Dict[str, Any]:
    """``{pieces, items}`` of the T-pose render a mesh is built from, read
    from its sidecar — the reference render records the equipped state it
    was made with. ``{}`` when there is nothing to copy (a legacy render),
    which simply leaves the mesh sidecar without a manifest."""
    try:
        meta = json.loads(
            ref_image.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return {}
    pieces = meta.get("equipped_pieces")
    if not isinstance(pieces, dict):
        return {}
    items = meta.get("equipped_items")
    return {"pieces": {str(k): str(v) for k, v in pieces.items() if v},
            "items": [str(i) for i in (items or []) if i]}


def generate_for_current_outfit(character_name: str, *, force: bool = False,
                                backend_glob: str = "",
                                prefer_cheapest: bool = False,
                                signature: Optional[str] = None,
                                face_num: Any = None,
                                texture_size: Any = None) -> Dict[str, Any]:
    """Generates the mesh for the currently worn outfit — or a given
    combination — from its T-pose render.

    Backend: ``backend_glob`` → admin default (``image_generation.
    mesh_imagegen_default``) → cheapest available mesh backend.
    ``prefer_cheapest`` skips the admin default (the auto-generate hook
    always takes the cheapest matching backend). Cached per combination —
    an existing mesh is kept unless ``force``.
    ``signature`` None = the worn combination; set = that combination drives
    the cache check, the T-pose input and the target file (the outfit batch
    pre-warms combinations without dressing the character).
    Blocking (minutes); call from a worker thread.
    """
    from app.core import config
    from app.imagegen.service import get_image_service
    from app.core.task_queue import get_task_queue

    if not backend_glob and not prefer_cheapest:
        backend_glob = str(
            config.get("image_generation.mesh_imagegen_default", "") or "").strip()

    if signature is None:
        _, _, signature = current_outfit_state(character_name)
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
    # Per-character override; None = the backend's configured default. One
    # load — the meta block below reuses it (each load reads the profile).
    no_fingers = get_model3d_options(character_name).get("no_fingers")
    try:
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(out_dir / f"{signature}.fbx"),
            backend_glob=backend_glob,
            character_name=character_name,
            mesh_name=character_name,
            rig=rig,
            face_num=face_num,
            texture_size=texture_size,
            no_fingers=no_fingers)
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
            for ext in (".png", ".jpg", ".jpeg"):
                stale_tex = path.with_suffix(ext)
                if stale_tex.exists():
                    stale_tex.unlink()
        meta = {
            "created_at": utc_now_iso(),
            "source": "generated",
            "backend": res.get("backend", ""),
            "format": res.get("format", path.suffix.lstrip(".").lower()),
            "rig": res.get("rig", rig),
            "has_texture": bool(res.get("texture_path")),
            "source_filename": res.get("filename", ""),
            "source_image": src.name,
            "signature": signature,
            "character": character_name,
            "no_fingers": no_fingers,
        }
        # Manifest (outfit_cache_gc): WHICH pieces this signature stands for.
        # The md5 cannot be read back, so without this a cache entry can only
        # be judged by "could it still be produced" — with it, exactly. The
        # T-pose render this mesh comes from already recorded it, so the
        # source of truth is copied rather than derived a second time.
        meta.update(_ref_manifest(src))
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


def _run(character_name: str, force: bool, backend_glob: str = "",
         prefer_cheapest: bool = False, face_num: Any = None,
         texture_size: Any = None) -> None:
    with _char_lock(character_name):
        try:
            generate_for_current_outfit(character_name, force=force,
                                        backend_glob=backend_glob,
                                        prefer_cheapest=prefer_cheapest,
                                        face_num=face_num,
                                        texture_size=texture_size)
        except Exception as e:
            logger.error("Model3D-Generierung fuer %s fehlgeschlagen: %s",
                         character_name, e)
        finally:
            with _lock:
                _generating.discard(character_name)


def trigger_generation(character_name: str, *, force: bool = False,
                       backend_glob: str = "",
                       prefer_cheapest: bool = False,
                       face_num: Any = None,
                       texture_size: Any = None) -> bool:
    """Starts the mesh generation in the background.
    ``backend_glob`` picks the mesh backend (empty = admin default →
    cheapest; ``prefer_cheapest`` always cheapest — the auto hook).
    False when one is already running for this character."""
    with _lock:
        if character_name in _generating:
            return False
        _generating.add(character_name)
    threading.Thread(target=_run,
                     args=[character_name, force, backend_glob, prefer_cheapest,
                           face_num, texture_size],
                     daemon=True).start()
    return True


def maybe_auto_generate_for_outfit(character_name: str) -> bool:
    """Auto-mesh hook — model_refs calls it AFTER a T-pose render pass, so
    a run only ever starts once the T-pose for the CURRENT combination
    exists (freshly rendered or cached). Conditions: the character's
    ``auto_generate`` option is on, the combination has no mesh yet, no
    run is active. Uses the CHEAPEST matching mesh backend (user decision
    2026-07-18). Returns True when a generation was started."""
    try:
        if not get_model3d_options(character_name).get("auto_generate"):
            return False
        _, _, signature = current_outfit_state(character_name)
        if not signature or find_model3d(character_name, signature):
            return False
        if not find_ref_image(character_name, "tpose", signature):
            return False  # render failed / not there yet — wait for the next pass
    except Exception as e:
        logger.debug("Model3D-Auto-Check fuer %s fehlgeschlagen: %s",
                     character_name, e)
        return False
    started = trigger_generation(character_name, prefer_cheapest=True)
    if started:
        logger.info("Model3D %s: Auto-Generierung gestartet (T-Pose vorhanden, "
                    "guenstigstes Backend)", character_name)
    return started


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
