"""The character's 3D model for the current outfit — cached per combination.

There is ONE model per outfit combination, produced in one of two ways:

* GENERATED: the T-pose reference render (``app/core/model_refs.py``) is sent
  to an img2mesh backend; its unrigged GLB is retained before a
  separate mesh2rig job produces the rigged model.
* UPLOADED: the user drops a GLB (or FBX+PNG) in the Game-Admin 3D tab.

Both write ``characters/<name>/model3d/<signature>.<ext>`` (+ a ``.png``
texture for FBX, + a ``.json`` sidecar recording ``source``/``rig``/…), so an
upload and a generation are interchangeable and either one is "the current
model". Switching back to a known outfit reuses whatever is stored.
"""

import json
import hashlib
import functools
import os
import inspect
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.imagegen.routing import ROUTE_META_KEYS
from app.core.log import get_logger
from app.core.model_refs import current_outfit_state, find_ref_image
from app.core.timeutils import utc_now_iso
from app.imagegen.occasions import mesh_occasion_for_rig

logger = get_logger(__name__)

# Formats a mesh backend may return (the gateway picks; Trellis2 -> .fbx).
MODEL_EXTS = (".fbx", ".glb", ".gltf", ".obj", ".ply", ".vrm")

_lock = threading.Lock()
_generating: set = set()
_rerig_results: Dict[str, Dict[str, Any]] = {}
_face_retexture_results: Dict[str, Dict[str, Any]] = {}
# The last "Re-apply face cleanup" run per character (``trigger_face_cleanup``).
_face_cleanup_results: Dict[str, Dict[str, Any]] = {}
# Distance meshes currently being built in the background, keyed by file path
# — one build per file, however many clients ask for it at once.
_lod_building: set = set()
_char_locks: Dict[str, threading.Lock] = {}


# A worker-local transaction redirects existing processing paths to a private
# same-filesystem directory. Nested full/low operations share that transaction.
_staging = threading.local()
_publication_epochs: Dict[tuple, int] = {}


# The garment assembly's delivery files (``garment_assembly``): the bare
# model + grafted garments, derived, never a publication input of its own.
ASSEMBLED_DIR = "assembled"
# The base body's second model without its ``exposed_only`` extension groups
# (``_auto_covered_variant``): what an outfit that hides them is built from.
COVERED_DIR = "covered"


def _signature_files(directory: Path, signature: str) -> Dict[Path, Path]:
    """Only one signature's public files and private backups, never stages."""
    folders = (Path('.'), Path('low'), Path('raw'), Path('prerig'), Path('unrigged'),
               Path('low/raw'), Path('low/prerig'), Path('facefix'), Path(COVERED_DIR),
               Path(ASSEMBLED_DIR), Path(ASSEMBLED_DIR) / 'low')
    return {relative / p.name: p for relative in folders
            for p in (directory / relative).glob(f"{signature}.*") if p.is_file()}


def _is_assembled(relative: Path) -> bool:
    """Whether a ``_signature_files`` key is a garment-assembly delivery file."""
    return bool(relative.parts) and relative.parts[0] == ASSEMBLED_DIR


def _fresh_staged_assemblies(stage: Path, signature: str) -> Dict[str, tuple]:
    """tier -> (bytes, sidecar) of every assembly built INSIDE the stage on
    the stage's own bare file (its ``bare_revision`` matches that file)."""
    from app.core import garment_assembly
    fresh = {}
    for tier in garment_assembly.TIERS:
        target = garment_assembly.assembled_path(stage, signature, tier)
        bare = garment_assembly.bare_path(stage, signature, tier)
        if not (target.is_file() and bare.is_file()):
            continue
        meta = _read_sidecar(target)
        if meta.get("bare_revision") == garment_assembly.bare_revision(bare):
            fresh[tier] = (target.read_bytes(), meta)
    return fresh


def _settle_assemblies(directory: Path, signature: str, changed, fresh: Dict[str, tuple]) -> bool:
    """Called under the publication lock after a signature's files moved:
    the assembly of every tier whose bare model or sidecar changed is
    dropped, or replaced by the stage's fresh one (restamped to the
    published bare file). True when an assembly file changed."""
    from app.core import garment_assembly
    touched = False
    for tier in garment_assembly.TIERS:
        bare = garment_assembly.bare_path(directory, signature, tier)
        bare_rel = bare.relative_to(directory)
        if not any(r.parent == bare_rel.parent and r.stem == signature and r.suffix in (".glb", ".json")
                   for r in changed):
            continue  # this tier's bare file is unchanged: its assembly stays as it is
        target = garment_assembly.assembled_path(directory, signature, tier)
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Assembly path escapes the model directory")
        for old in (target, target.with_suffix(".json")):
            if old.exists():
                old.unlink()
                touched = True
        if tier in fresh and bare.is_file():
            blob, meta = fresh[tier]
            target.parent.mkdir(parents=True, exist_ok=True)
            _publish_model_bytes(target, blob)
            _publish_sidecar(target, {**meta, "bare_revision": garment_assembly.bare_revision(bare)})
            touched = True
    return touched


def _publish_signature(character_name: str, directory: Path, stage: Path,
                       signature: str, token, *, retain_stage: bool = False,
                       rollback_on_error: bool = False, invalidate: bool = False) -> Optional[tuple]:
    """Commit one signature under the reader lock, rejecting stale work."""
    import os
    from app.core.keyed_lock import keyed_lock
    # Garment assemblies are derived from the bare files: they are never
    # replaced or dropped by absence like the rest, but settled per tier
    # after the move (``_settle_assemblies``).
    staged_files = {r: p for r, p in _signature_files(stage, signature).items() if not _is_assembled(r)}
    current_files = {r: p for r, p in _signature_files(directory, signature).items() if not _is_assembled(r)}
    replacements = []
    prepared = stage / ".publication" if retain_stage else stage
    rollback = stage / ".rollback" if rollback_on_error else None
    try:
        for relative, source in staged_files.items():
            current = current_files.get(relative)
            if current is None or source.read_bytes() != current.read_bytes():
                replacements.append(relative)
                if retain_stage:
                    target = prepared / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        if rollback is not None:
            for relative in set(replacements) | (current_files.keys() - staged_files.keys()):
                source = current_files.get(relative)
                if source is not None:
                    target = rollback / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        fresh_assemblies = _fresh_staged_assemblies(stage, signature)
    except FileNotFoundError:
        return None
    with keyed_lock("model3d", f"{character_name}:{signature}"), \
            keyed_lock("model3d_publication", str(directory)):
        if not directory.is_dir() or _publication_token(directory, signature) != token:
            return None
        changed = []
        snapshot_removed = False
        try:
            for relative in current_files.keys() - staged_files.keys():
                current_files[relative].unlink(missing_ok=True)
                changed.append(relative)
            # Full sidecar last: the commit marker for lock-aware readers.
            order = lambda r: (r.suffix == ".json", r.parent == Path('.'), str(r))
            for relative in sorted(replacements, key=order):
                target = directory / relative
                if not target.resolve().is_relative_to(directory.resolve()):
                    raise ValueError("Model publication path escapes its directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(prepared / relative, target)
                changed.append(relative)
            if changed:
                # Rides on this publication's epoch bump and changed_at.
                _settle_assemblies(directory, signature, changed, fresh_assemblies)
            snapshot = directory / "rollback" / signature
            if not snapshot.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Rollback path escapes the model directory")
            removed_snapshot = stage / ".removed-snapshot"
            if (stage / ".replace-source").exists() or (stage / ".face-revert").exists():
                if snapshot.exists():
                    os.replace(snapshot, removed_snapshot)
                    snapshot_removed = True
            # facefix-ref/ (the upscaled reference photo) is deliberately NOT
            # purged here: it depends on the photo, not on the mesh, and its
            # sidecar hash turns a re-rendered photo into a cache miss anyway.
            prepared_snapshot = stage / ".face-snapshot"
            if prepared_snapshot.exists() and not snapshot.exists():
                snapshot.parent.mkdir(exist_ok=True)
                os.replace(prepared_snapshot, snapshot)
        except Exception:
            if snapshot_removed:
                os.replace(stage / ".removed-snapshot", directory / "rollback" / signature)
            if rollback is not None:
                for relative in reversed(changed):
                    target = directory / relative
                    if relative in current_files:
                        os.replace(rollback / relative, target)
                    else:
                        target.unlink(missing_ok=True)
            raise
        if snapshot_removed:
            shutil.rmtree(removed_snapshot)
        if changed or invalidate:
            key = (str(directory), signature)
            _publication_epochs[key] = _publication_epochs.get(key, 0) + 1
        published = _publication_token(directory, signature)
    if changed or invalidate:
        from app.core import sync_topics
        sync_topics.changed_at(character_name)
    return published


def _checkpoint_mesh(character_name: str, signature: str) -> None:
    """Publish the validated static model and source before submitting its rig."""
    publication = getattr(_staging, "source_publications", {}).get(character_name)
    if not publication:
        return
    directory = publication["directory"]
    stage = get_model3d_dir(character_name)
    token = _publish_signature(character_name, directory, stage, signature,
                               publication["token"], retain_stage=True,
                               rollback_on_error=True)
    if token is None:
        raise RuntimeError("Model changed before mesh publication")
    publication["token"] = token
    publication["mesh_published"] = True


def _publication_token(directory: Path, signature: str):
    records = []
    for relative, path in sorted(_signature_files(directory, signature).items()):
        if _is_assembled(relative):
            # A background assembly must not void a staged operation; the
            # publication settles the assemblies itself.
            continue
        stat = path.stat()
        records.append((str(relative), stat.st_size, stat.st_mtime_ns, stat.st_ino))
    return (_publication_epochs.get((str(directory), signature), 0), records)


def _serial_model(function):
    """Stage expensive processing; lock only snapshot checks and publication.

    Readers take model3d_publication on the real directory. Meshes/textures/
    backups replace first, tier sidecars next, full sidecar last. Unchanged
    files retain their inode/mtime, so a no-op never changes model_rev.
    """
    # The staged twin of a public entry carries a leading underscore (the
    # hub-operation entries ``_generate_for_current_outfit`` & co., see
    # app/core/hub_ops.py): it is the same operation and takes the same
    # branches below.
    name = function.__name__.lstrip("_")

    @functools.wraps(function)
    def wrapped(character_name, *args, **kwargs):
        import tempfile
        from app.core.keyed_lock import keyed_lock
        bound = inspect.signature(function).bind_partial(character_name, *args, **kwargs)
        signature = bound.arguments.get("signature")
        if not signature:
            if name in ("set_model3d_rig", "delete_model3d"):
                exact = find_model3d(character_name, include_stale=name == "delete_model3d")
                signature = exact.stem if exact else None
            elif name in ("build_lod", "rebuild_extension_rig", "measure_model", "diagnose_model", "retexture_model", "rerig_model", "face_retexture_model", "revert_face_retexture"):
                served = find_model3d_serving(character_name)[0]
                signature = served.stem if served else None
            signature = signature or current_outfit_state(character_name)[2]
        if not isinstance(signature, str) or any(c in signature for c in ("/", "\\", "\0")) or signature in (".", ".."):
            raise ValueError("Invalid model signature")
        if "signature" in inspect.signature(function).parameters:
            bound.arguments["signature"] = signature
        def stale(reason):
            if name == "delete_model3d":
                return False
            return {"ok": False, "status": "stale", "error": reason}
        active = getattr(_staging, "directories", {})
        if character_name in active:
            return function(*bound.args, **bound.kwargs)
        directory = get_model3d_dir(character_name)
        if not directory.is_dir():
            return function(*bound.args, **bound.kwargs)
        with keyed_lock("model3d_publication", str(directory)):
            token = _publication_token(directory, signature)
        with tempfile.TemporaryDirectory(prefix=".process-", dir=directory) as tmp:
            stage = Path(tmp)
            # Copy outside the lock. A racing mutation invalidates the token;
            # it can never be overwritten with a stale snapshot.
            try:
                for relative, source in _signature_files(directory, signature).items():
                    if _is_assembled(relative):
                        continue  # derived; the publication drops or keeps it
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            except FileNotFoundError:
                return stale("Model changed while staging")
            if name == "face_retexture_model" and not (directory / "rollback" / signature).exists():
                from app.core.face_retexture import prepare_snapshot
                prepare_snapshot(stage, signature)
            _staging.directories = {**active, character_name: stage}
            publications = getattr(_staging, "source_publications", {})
            publication = {"directory": directory, "signature": signature, "token": token}
            _staging.source_publications = {**publications, character_name: publication}
            # Garment-assembly builds asked for inside the stage wait for its
            # publication (garment_assembly.schedule): built earlier, they
            # would read the old bare file.
            assembly_requests = getattr(_staging, "assembly_requests", {})
            requested: set = set()
            _staging.assembly_requests = {**assembly_requests, character_name: requested}
            generation_error = None
            try:
                result = function(*bound.args, **bound.kwargs)
            except Exception as exc:
                if name != "generate_for_current_outfit":
                    raise
                generation_error = exc
                result = {"ok": False, "error": str(exc)}
            finally:
                _staging.directories = active
                _staging.source_publications = publications
                _staging.assembly_requests = assembly_requests
            token = publication["token"]
            # A rig failure never rolls back the already published new mesh,
            # nor publishes partially processed rig/LOD bytes from the stage.
            if name == "generate_for_current_outfit" and not result.get("ok"):
                rig_error_published = False
                if publication.get("mesh_published"):
                    with keyed_lock("model3d", f"{character_name}:{signature}"), \
                            keyed_lock("model3d_publication", str(directory)):
                        if directory.is_dir() and _publication_token(directory, signature) == token:
                            path = directory / f"{signature}.glb"
                            meta = _read_sidecar(path)
                            meta["rig_error"] = result.get("error") or "Rig generation failed"
                            _publish_sidecar(path, meta)
                            rig_error_published = True
                            key = (str(directory), signature)
                            _publication_epochs[key] = _publication_epochs.get(key, 0) + 1
                if rig_error_published:
                    from app.core import sync_topics
                    sync_topics.changed_at(character_name)
                if generation_error is not None:
                    raise generation_error
                return result
            if name in ("rerig_model", "face_retexture_model", "revert_face_retexture", "repair_model_weights") and not result.get("ok"):
                return result
            if not _publish_signature(character_name, directory, stage, signature, token,
                                      rollback_on_error=name in (
                                          "generate_for_current_outfit", "rerig_model", "face_retexture_model", "revert_face_retexture", "repair_model_weights"),
                                      invalidate=name == "delete_model3d"):
                return stale("Model changed during processing; result discarded")
            if requested:
                from app.core import garment_assembly
                for requested_signature in sorted(requested):
                    garment_assembly.schedule(character_name, requested_signature)
            if isinstance(result, dict):
                if "path" in result:
                    result["path"] = str(directory / Path(result["path"]).name)
                if "model_rev" in result:
                    result["model_rev"] = model_revision(find_model3d(character_name, signature))
            if generation_error is not None:
                raise generation_error
            return result
    return wrapped


def _model_reader(function):
    """Return one coherent publication snapshot, including tier metadata."""
    @functools.wraps(function)
    def wrapped(character_name, *args, **kwargs):
        from app.core.keyed_lock import keyed_lock
        url_base = kwargs.pop("_url_base", None) or f"/characters/{quote(character_name)}/model3d/file"
        publication = keyed_lock("model3d_publication", str(get_model3d_dir(character_name)))
        with publication:
            out = function(character_name, *args, **kwargs)
            captured = _capture_model_urls(character_name, url_base) if out.get("model") else []
        urls = _finish_model_urls(captured, publication)
        if out.get("model"):
            out["model"].update(urls)
        return out
    return wrapped


def get_model3d_options(character_name: str) -> Dict[str, Any]:
    """Read supported per-character model options from ``model3d_opts``."""
    from app.models.character import get_character_profile
    try:
        raw = (get_character_profile(character_name) or {}).get("model3d_opts") or {}
    except Exception:
        raw = {}
    return {
            # Auto-generate the mesh on the CHEAPEST backend as soon as a
            # fresh T-pose render of a new outfit combination succeeds.
            "auto_generate": bool(raw.get("auto_generate")),
            "face_before_rig": bool(raw.get("face_before_rig")),
            # The face cleanup before the face retexture (app/core/face_cleanup.py): OFF by default until its
            # result passes the visual gate (review 2026-11-09, torn shards at the eye); only True is stored.
            "face_cleanup": bool(raw.get("face_cleanup")),
            "face_photo": dict(raw.get("face_photo") or {}),
            "extension_rig_models": dict(raw.get("extension_rig_models") or {}),
            "extension_motion": dict(raw.get("extension_motion") or {}),
            # Collision-capsule radius scale per region (collision.py), all
            # four regions; an invalid stored map counts as the defaults.
            "collision_scales": _collision_scales_option(raw.get("collision_scales"))}


def _collision_scales_option(raw: Any) -> Dict[str, float]:
    from app.core.collision import default_scales, validate_scales
    try:
        return validate_scales(raw)
    except ValueError:
        return default_scales()


def set_model3d_options(character_name: str,
                        updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge supported model options into the character profile."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    # Read AND write under the per-character profile lock (DATA-3). The
    # read-back that forms the answer stays inside, so the caller is told what
    # this write stored and not what a later one did. Leaf span.
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        opts = dict(profile.get("model3d_opts") or {})
        if "face_photo" in updates:
            from app.core.face_photo_adjust import validated_params as photo_params
            photo = photo_params(updates["face_photo"])
            from app.core.face_photo_adjust import DEFAULTS as photo_defaults
            cleaned = {k: v for k, v in photo.items() if v != photo_defaults[k]}
            if cleaned:
                opts["face_photo"] = cleaned
            else:
                opts.pop("face_photo", None)
        if "face_before_rig" in updates:
            if type(updates["face_before_rig"]) is not bool:
                raise ValueError("face_before_rig must be a boolean")
            if updates["face_before_rig"]:
                opts["face_before_rig"] = True
            else:
                opts.pop("face_before_rig", None)
        if "auto_generate" in updates:
            if updates["auto_generate"]:
                opts["auto_generate"] = True
            else:
                opts.pop("auto_generate", None)
        if "face_cleanup" in updates:
            if type(updates["face_cleanup"]) is not bool:
                raise ValueError("face_cleanup must be a boolean")
            if updates["face_cleanup"]:
                opts["face_cleanup"] = True
            else:
                opts.pop("face_cleanup", None)
        if "extension_rig" in updates:
            from app.core.face_retexture import safe_signature
            signature = safe_signature(updates.get("signature"))
            if find_model3d(character_name, signature) is None:
                raise ValueError("Stored full model not found for signature")
            overrides = updates["extension_rig"]
            if not isinstance(overrides, dict):
                raise ValueError("extension_rig must be a group override map")
            cleaned = {}
            for group_id, values in overrides.items():
                if not isinstance(group_id, str) or not group_id or not isinstance(values, dict):
                    raise ValueError("invalid extension group override")
                if set(values) - {"enabled", "flip"} or any(type(v) is not bool for v in values.values()):
                    raise ValueError("extension overrides accept enabled and flip booleans only")
                cleaned[group_id] = dict(values)
            models = dict(opts.get("extension_rig_models") or {})
            if cleaned:
                models[signature] = cleaned
            else:
                models.pop(signature, None)
            opts["extension_rig_models"] = models
        if "collision_scales" in updates:
            # Stored as deviations from 1.0 only; the capsule sets follow
            # through collision.recompute_character (the caller runs it).
            from app.core.collision import validate_scales
            scales = {region: value for region, value in validate_scales(updates["collision_scales"]).items()
                      if value != 1.0}
            if scales:
                opts["collision_scales"] = scales
            else:
                opts.pop("collision_scales", None)
        if "extension_motion" in updates:
            from app.core.extension_rig import validate_motion_overrides
            overrides = updates["extension_motion"]
            validate_motion_overrides({"groups": overrides}, character=True)
            opts["extension_motion"] = {key: dict(value) for key, value in overrides.items() if value}
        profile["model3d_opts"] = opts
        if not save_character_profile(character_name, profile):
            raise RuntimeError("Character profile could not be saved")
        return get_model3d_options(character_name)


def get_model3d_dir(character_name: str) -> Path:
    """Directory of the generated meshes (see get_character_images_dir for the
    base-dir existence gate that avoids ghost dirs on read paths)."""
    staged = getattr(_staging, "directories", {}).get(character_name)
    if staged is not None:
        return staged
    from app.models.character import get_character_dir
    base = get_character_dir(character_name)
    d = base / "model3d"
    if base.exists():
        d.mkdir(parents=True, exist_ok=True)
    return d


# Resolution tiers of a character mesh. Unlike props and locations there is
# nothing to SELECT here — the outfit signature already determines the model —
# so a tier is not a gallery entry but the SAME signature at another
# resolution, stored in a subdirectory of that name. A subdirectory rather
# than a "<signature>.low.glb" sibling for the same reason the raw backups
# live in one: the store walks the model directory to find the nearest
# matching outfit, and a coarse stand-in must never be a candidate for that.
FULL_TIER = "full"
LOW_TIER = "low"
MODEL_TIERS = (FULL_TIER, LOW_TIER)


def tier_dir(character_name: str, tier: str) -> Path:
    """Directory holding the meshes of ``tier`` (full = the model root)."""
    base = get_model3d_dir(character_name)
    return base if tier in ("", FULL_TIER) else base / tier


def tier_variant(model_path: Path, tier: str) -> Optional[Path]:
    """The ``tier`` file belonging to a stored mesh, or None if not built.

    Same file name, one directory down — the signature is what ties the two
    together, so a tier can never drift onto another outfit's model.
    """
    from app.core.model_refs import is_state_fork
    if is_state_fork(model_path.stem) or "-p" in model_path.stem:
        return None
    if tier in ("", FULL_TIER):
        return model_path if model_path.exists() else None
    candidate = model_path.parent / tier / model_path.name
    return candidate if candidate.exists() else None


def available_tiers(model_path: Optional[Path]) -> List[str]:
    """Which tiers exist for a stored mesh, in fallback order."""
    if not model_path:
        return []
    return [t for t in MODEL_TIERS if tier_variant(model_path, t)]


def find_model3d(character_name: str,
                 signature: Optional[str] = None, *,
                 include_stale: bool = False) -> Optional[Path]:
    """Path of the cached mesh for the given outfit combination (default: the
    currently worn one), or None.

    States do not enter mesh identity. Explicit signatures are matched exactly;
    retired state forks are rejected.

    Base-body pipeline: an outfit model not built on the CURRENT base body
    (sidecar ``base_signature`` / ``base_model_sha256`` differ or are
    absent — an older or regenerated base, or a whole-body model from
    before the switch) counts as missing, so the next
    trigger rebuilds it (``_on_older_base``). ``include_stale`` finds it
    anyway (deletion, status display)."""
    from app.core.model_refs import is_state_fork
    if is_state_fork(signature) or "-p" in (signature or ""):
        return None
    candidates = [signature]
    if signature is None:
        try:
            _, _, sig = current_outfit_state(character_name)
        except Exception:
            return None
        candidates = [sig]
    d = get_model3d_dir(character_name)
    for sig in candidates:
        for ext in MODEL_EXTS:
            p = d / f"{sig}{ext}"
            if p.exists():
                if not include_stale and _on_older_base(p, _current_base(character_name)):
                    return None
                return p
    return None


def _current_base(character_name: str) -> Optional[tuple]:
    """``(base signature, base model sha256)`` when the character is on the
    base-body pipeline (``base_body.current_base``), else None (no stale
    rule applies). An unreadable profile counts as off the pipeline — the
    stored model keeps being found."""
    try:
        from app.core.base_body import current_base
        from app.models.character import get_character_profile
        return current_base(character_name, profile=get_character_profile(character_name) or {})
    except Exception as e:  # noqa: BLE001
        logger.debug("Model3D %s: base body unreadable: %s", character_name, e)
        return None


def _on_older_base(path: Path, base: Optional[tuple]) -> bool:
    """Whether a stored outfit model is not built on the current base body
    (``base`` from ``_current_base``; None = off the pipeline, never stale):
    another base signature, another base model under the same signature,
    or none recorded (a whole-body model from before the switch) — or built
    from the other base model than its pieces call for now
    (``base_body.variant_current``: a piece's ``exposed_detail`` changed),
    or left an own-mesh piece painted on that has its garment mesh now
    (``base_body.mesh_items_ready``). The base model itself is never stale
    here."""
    if not base:
        return False
    from app.core.base_body import built_on_current_base, is_base_signature, mesh_items_ready, variant_current
    if is_base_signature(path.stem):
        return False
    meta = _read_sidecar(path)
    if not built_on_current_base(meta, base):
        return True
    if not meta.get("character"):
        return False
    return (not variant_current(meta["character"], meta)
            or bool(mesh_items_ready(meta["character"], meta, base_sha=base[1])))


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


def _auto_lod_enabled() -> bool:
    from app.core import config
    return bool(config.get("image_generation.blender_auto_lod", True))


def _auto_lod_ratio() -> float:
    from app.blender.refine import lod_ratio
    return lod_ratio("character")


def request_lod(character_name: str, model_path: Path) -> bool:
    """Builds the missing distance mesh in the BACKGROUND. True if started.

    A client asking for a resolution that does not exist yet still gets the
    full mesh (the tier fallback); this makes sure the next request has the
    real thing. Serving must never wait on a build, and the same file must
    never be built twice at once — hence the thread and the in-flight set.

    The admin stays in charge: the generated mesh is a floor, not a ceiling.
    A better low-poly version made elsewhere can replace it at any time.
    """
    meta = _read_sidecar(model_path)
    # A base body is copied per outfit, never shown at range: no low tier.
    if (not _auto_lod_enabled() or model_path.suffix.lower() != ".glb"
            or meta.get("rig") == "none" or meta.get("base")):
        return False
    if character_name in getattr(_staging, "directories", {}):
        result = build_lod(character_name, model_path.stem, ratio=_auto_lod_ratio())
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Low tier preparation failed")
        return True
    key = str(model_path)
    with _lock:
        if key in _lod_building:
            return False
        _lod_building.add(key)

    def _run_build() -> None:
        try:
            res = build_lod(character_name, model_path.stem,
                            ratio=_auto_lod_ratio())
            if not res.get("ok"):
                logger.debug("Model3D %s: LOD not built (%s)",
                             character_name, res.get("error"))
        except Exception as e:                              # noqa: BLE001
            logger.warning("Model3D %s: LOD build failed: %s",
                           character_name, e)
        finally:
            with _lock:
                _lod_building.discard(key)

    threading.Thread(target=_run_build, daemon=True,
                     name=f"lod-{character_name}").start()
    return True


def find_model3d_serving_tier(character_name: str, tier: str = FULL_TIER) -> tuple:
    """(path, match, tier) of the mesh to serve at ``tier``.

    The outfit combination is resolved FIRST, exactly as always, and only the
    winner is then looked up at the requested resolution. Doing it the other
    way round would let a coarse stand-in of some other outfit beat the right
    model. A tier that was never built falls back to ``full`` — a consumer
    asking for a resolution gets the best available one, never nothing.
    """
    path, match = find_model3d_serving(character_name)
    if not path:
        return None, "", ""
    tier = (tier or FULL_TIER).strip().lower()
    variant = tier_variant(path, tier) if tier in MODEL_TIERS else None
    if variant:
        return variant, match, tier
    # Asked for a resolution that does not exist yet: serve the full mesh now
    # and build the missing one in the background, so the next request has it.
    if tier == LOW_TIER:
        request_lod(character_name, path)
    return path, match, FULL_TIER


def find_model3d_serving(character_name: str) -> tuple:
    """(path, match) of the mesh to SERVE for the worn outfit — the serving
    chain behind the byte/meta routes. ``match`` is how it was found:
    ``"exact"`` / ``"stale"`` (this combination's model, built on an
    older base body — base-body pipeline only) / ``"nearest"``
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
    d = get_model3d_dir(character_name)
    for ext in MODEL_EXTS:
        p = d / f"{sig}{ext}"
        if p.exists():
            base = _current_base(character_name)
            # Base-body pipeline: a model built on an older base body is
            # still this outfit, so it stays on screen until its rebuild is
            # published — but never as the current one ("stale").
            return p, ("stale" if _on_older_base(p, base) else "exact")
    best = None
    if d.is_dir():
        from app.core.model_refs import is_state_fork
        from app.core.outfit_match import outfit_similarity
        from app.core.base_body import is_base_signature
        base = _current_base(character_name)
        for p in d.iterdir():
            if p.suffix.lower() not in MODEL_EXTS or is_state_fork(p.stem) or "-p" in p.stem:
                continue
            # The base body is never an outfit's model (nor its stand-in).
            if is_base_signature(p.stem):
                continue
            manifest = _stored_manifest(character_name, p.stem)
            if manifest is None:
                continue
            from app.core.model_refs import mesh_variant
            if manifest.get("mesh_variant", "") != mesh_variant(character_name, pieces):
                continue
            score = outfit_similarity(pieces, items,
                                      manifest["pieces"], manifest["items"])
            # Ties: prefer the newest neutral outfit entry; a model on the
            # current base body beats one built on an older base.
            key = (not _on_older_base(p, base), score, p.stat().st_mtime)
            if best is None or key > best[0]:
                best = (key, p)
    if best is not None:
        logger.debug("Model3D %s: nearest %s for combination %s (score %.2f)",
                     character_name, best[1].stem, sig, best[0][1])
        return best[1], "nearest"
    return None, ""


def required_rig(character_name: str) -> str:
    """Which rig this character needs: humanoids get the Mixamo 52-bone rig
    (one GLB, animation clips apply), everything else a generic rig (FBX +
    separate texture, no clips)."""
    from app.core.model_refs import is_humanoid
    return "mixamo" if is_humanoid(character_name) else "generic"


def list_mesh_backends(occasion: str = "", character: str = "") -> Dict[str, Any]:
    """Available img2mesh choices and the supplied occasion's routed default.

    All img2mesh backends produce unrigged sources. With no occasion supplied,
    no default is preselected. ``character`` puts that character's own mesh
    match (Characters → Image) in front of the chain, so the dialog preselects
    what an Auto run for this character would use.
    """
    from app.imagegen.service import get_image_service
    out = []
    try:
        svc = get_image_service()
        for b in svc.list_mesh_backends():
            out.append({
                "name": b.name,
                "model": getattr(b, "model", ""),
                "cost": getattr(b, "cost", 0),
                "face_num": getattr(b, "face_num", None),
                # 0 = no cap. A backend that HANGS above a face count (rather
                # than failing) needs the dialog to stop the value, not the job.
                "face_num_max": getattr(b, "face_num_max", 0),
                # Can this alias bake reduced LOD stages in the SAME job
                # (input_lod_faces)? Read from the alias schema, never from its
                # name — the dialog offers the stage control only where it
                # actually reaches something.
                "lod_stages": bool(getattr(b, "supports_lod_stages", False)),
            })
    except Exception as e:
        logger.debug("Listing mesh backends failed: %s", e)
    # The dialogs preselect what the occasion's chain resolves to right now
    # (image routing); a call without an occasion has no default.
    default = ""
    try:
        occ = occasion
        if occ:
            from app.imagegen.routing import explain_occasion
            default = str(explain_occasion(occ, character).get("resolved") or "")
    except Exception as e:
        logger.debug("Mesh default for occasion=%r not resolved: %s", occasion, e)
        default = ""
    if default and not any(b["name"] == default for b in out):
        default = ""
    return {"backends": out, "default": default}


def list_rig_backends() -> List[Dict[str, Any]]:
    """Offer all enabled mesh2rig backends for an explicit pick."""
    from app.imagegen.service import get_image_service
    return [{"name": b.name, "model": getattr(b, "model", "")}
            for b in get_image_service().pool.backends
            if getattr(b, "MEDIA_TYPE", "image") == "mesh"
            and getattr(b, "category", "") == "mesh2rig"
            and b.instance_enabled]


def list_shrink_backends() -> Dict[str, Any]:
    """Available mesh→mesh backends (``category`` mesh2mesh) for the "Create
    low variant" dialog: ``{"backends": [...]}`` in the same entry shape as
    ``list_mesh_backends``. No default — the reduction is one explicit admin
    action, not a routed job; with a single backend the dialog preselects it.
    """
    from app.imagegen.service import get_image_service
    out = []
    try:
        for b in get_image_service().list_shrink_backends():
            out.append({
                "name": b.name,
                "model": getattr(b, "model", ""),
                "cost": getattr(b, "cost", 0),
                "face_num": getattr(b, "face_num", None),
                "face_num_max": getattr(b, "face_num_max", 0),
                # Same field as in list_mesh_backends so the dialog reads ONE
                # shape; a reduction alias never bakes stages of its own.
                "lod_stages": bool(getattr(b, "supports_lod_stages", False)),
            })
    except Exception as e:
        logger.debug("Listing shrink backends failed: %s", e)
    return {"backends": out}


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


def _capture_model_urls(character_name: str, enc_base: str):
    """Select/open/fstat source snapshots under the caller's publication lock."""
    captured = []
    def capture(key, base, path, delivery=False):
        f = open(path, "rb")
        try:
            captured.append((key, base, path, f, os.fstat(f.fileno()), delivery))
        except BaseException:
            f.close()
            raise
    try:
        from app.core import garment_assembly
        full, _, _ = find_model3d_serving_tier(character_name, "")
        if full is None:
            return captured
        # The delivered bytes: the garment assembly when it is current.
        capture("url", enc_base + "?v=", garment_assembly.served(character_name, full, FULL_TIER), True)
        if tier_variant(full, LOW_TIER) is not None:
            low, _, low_tier = find_model3d_serving_tier(character_name, LOW_TIER)
            capture("low_url", enc_base + f"?tier={LOW_TIER}&v=",
                    garment_assembly.served(character_name, low, low_tier), True)
        if full.suffix.lower() == ".fbx":
            texture = find_texture(character_name, full.stem)
            if texture is not None:
                base = enc_base[:-4] + "texture" if enc_base.endswith("/file") else enc_base + "/texture"
                capture("texture_url", base + "?v=", texture)
        return captured
    except BaseException:
        for _, _, _, f, _, _ in captured:
            f.close()
        raise


def _finish_model_urls(captured, publication=None):
    from app.core.http_files import opened_content_version, select_opened_delivery
    urls = {}
    try:
        for key, base, path, f, st, delivery in captured:
            try:
                if delivery and path.suffix.lower() == ".glb":
                    path, f, st = select_opened_delivery(path, f, st, publication)
                urls[key] = base + opened_content_version(f, st)
            finally:
                f.close()
        return urls
    finally:
        for _, _, _, f, _, _ in captured:
            f.close()


def versioned_model_urls(character_name: str, enc_base: str) -> Dict[str, str]:
    """Capture model descriptors under the lock, hash their bytes after release."""
    from app.core.keyed_lock import keyed_lock
    publication = keyed_lock("model3d_publication", str(get_model3d_dir(character_name)))
    with publication:
        captured = _capture_model_urls(character_name, enc_base)
    return _finish_model_urls(captured, publication)


def signature_model_url(character_name: str, signature: str) -> Optional[str]:
    """Versioned URL of the stored full model of ONE explicit signature
    (``/characters/<name>/model3d/file?signature=<sig>&v=<content>``), or
    None. The file route accepts only the current outfit or the current base
    signature there; the version is the delivered file's, like ``url``."""
    from app.core.keyed_lock import keyed_lock
    base = (f"/characters/{quote(character_name, safe='')}/model3d/file"
            f"?signature={quote(signature, safe='')}&v=")
    publication = keyed_lock("model3d_publication", str(get_model3d_dir(character_name)))
    with publication:
        path = find_model3d(character_name, signature)
        if path is None:
            return None
        f = open(path, "rb")
        try:
            captured = [("url", base, path, f, os.fstat(f.fileno()), True)]
        except BaseException:
            f.close()
            raise
    return _finish_model_urls(captured, publication).get("url")


def attached_part_info(extension):
    """Read stored part metrics; declarations describe the served model, not today's switch."""
    groups = extension.get("group_ops") or {}
    part_ids = [key for key, op in groups.items() if op in ("attached_part", "inset_part")]
    if not part_ids:
        return None
    metrics = extension.get("metrics") or {}
    rows = [{"protrusion_warn_mm": ((extension.get("group_params") or {}).get(key) or {}).get("protrusion_warn_mm", 12),
             **(metrics.get(key) or {}), "op": groups[key]} for key in part_ids]
    failed = next((row for row in rows if row.get("status") == "failed"), None)
    row = failed or max(rows, key=lambda r: r.get("protrusion_mm") or 0)
    protrusion = row.get("protrusion_mm")
    status = row.get("status", extension.get("status", "not_found"))
    return {"status": status, "reason": row.get("reason") or extension.get("reason", ""),
            "protrusion_mm": protrusion,
            "warning": bool(row["op"] == "attached_part" and protrusion is not None and protrusion > row.get("protrusion_warn_mm", 12))}


@_model_reader
def get_model3d_info(character_name: str, *, preview_states=None) -> Dict[str, Any]:
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
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    out: Dict[str, Any] = {
        "signature": signature,
        "rig": rig,
        "has_input": bool(find_ref_image(character_name, "tpose", signature)
                          if signature else None),
        "model": None,
    }
    # Serving semantics (like the file route): exact outfit first,
    # then the nearest stored neutral combination — meta and
    # served file must agree.
    path, match = find_model3d_serving(character_name) if signature else (None, "")
    if path:
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
                                "limb_weights": {"checked": False, "vertices": 0,
                                                 "fully_foreign": 0, "error": ""}}
        # Base-body pipeline: the served file may be an outfit model built on
        # an older base body ("stale" for its own combination, or a nearest
        # stand-in). It is still THE file on screen, so its details stay; the
        # flag tells the tab to ask for a rebuild. ``stale_reason``:
        # ``older_base`` / ``before_pipeline`` (no base recorded) /
        # ``detail_changed`` / ``mesh_item_ready``.
        current_base = _current_base(character_name)
        info["stale_base"] = _on_older_base(path, current_base)
        if info["stale_base"]:
            from app.core.base_body import built_on_current_base, variant_current
            stale_meta = _read_sidecar(path)
            info["stale_reason"] = ("before_pipeline" if not stale_meta.get("base_signature")
                                    else "older_base" if not built_on_current_base(stale_meta, current_base)
                                    else "detail_changed" if not variant_current(character_name, stale_meta)
                                    else "mesh_item_ready")
        info["has_unrigged_source"] = (path.parent / "unrigged" / f"{path.stem}.glb").is_file()
        info["unrigged_source_reason"] = "" if info["has_unrigged_source"] else "No retained unrigged mesh source. Generate a new model to enable re-rigging."
        info["source"] = "generated"  # default for legacy sidecars
        meta_path = path.with_suffix(".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                info["source"] = meta.get("source", "generated")
                info["created_at"] = meta.get("created_at", "")
                info["backend"] = meta.get("backend", "")
                for key in ("mesh_backend", "rig_backend", "mesh_route_meta", "rig_route_meta"):
                    info[key] = meta.get(key, "" if key.endswith("backend") else {})
                for key in ("clips", "rig_metrics"):
                    if key in meta:
                        info[key] = meta[key]
                info["lod_error"] = meta.get("lod_error", "")
                if isinstance(meta.get("refined"), dict):
                    info["refined"] = meta["refined"]
                info["source_filename"] = meta.get("source_filename", "")
                info["job_id"] = meta.get("job_id", "")
                info["rig_error"] = meta.get("rig_error", "")
                info["face_num"] = meta.get("face_num")
                # The base body the served file was built on (base-body
                # pipeline; None for a whole-body model).
                info["base_signature"] = meta.get("base_signature")
                info["base_model_sha256"] = meta.get("base_model_sha256")
                # Measured geometry, if this model has been through Blender.
                # Read from the sidecar only — the info route is polled, and
                # measuring costs a subprocess.
                if meta.get("measured"):
                    info["measured"] = meta["measured"]
                # Cached defect indicators (diagnose_model) — display only.
                if isinstance(meta.get("extension_rig"), dict):
                    info["extension_rig"] = meta["extension_rig"]
                if meta.get("diagnosis"):
                    info["diagnosis"] = meta["diagnosis"]
                # Normalised = the file already stands its real height on the
                # ground; a client must NOT rescale it by the bounding box
                # (hair above the crown would shrink the body again).
                if "normalize" in ((meta.get("blender") or {}).get("steps")
                                   or []):
                    info["normalized"] = True
                weights = (meta.get("blender") or {}).get("limb_weights") or {}
                info["limb_weights"] = {
                    "checked": "limb_weights" in ((meta.get("blender") or {}).get("steps") or []),
                    "vertices": weights.get("vertices", 0),
                    "fully_foreign": weights.get("fully_foreign", 0),
                    "error": weights.get("error", ""),
                }
                if meta.get("rig"):
                    info["rig"] = meta["rig"]  # what it was ACTUALLY made with
            except (OSError, ValueError):
                pass
        # Which resolutions exist for THIS file. "full" is always there (it is
        # the file itself); "low" only once it has been built.
        from app.core.extension_rig import extension_metadata
        info.setdefault("extension_rig", extension_metadata(character_name, profile=profile, signature=path.stem))
        part = attached_part_info(info["extension_rig"])
        if part is not None:
            info["attached_part"] = part
        # Collision capsules of the served body (spec 2026-11-08): fitted and
        # stored once per file, None for a non-humanoid model.
        try:
            from app.core.collision import character_scales, ensure_path
            info["collision"] = ensure_path(character_name, path,
                                            scales=character_scales(character_name, profile=profile))
        except Exception as exc:  # noqa: BLE001 — the info route never fails on it
            logger.warning("Model3D %s: collision capsules unavailable: %s", character_name, exc)
            info["collision"] = None
        info["model_rev"] = model_revision(path)
        info["tiers"] = available_tiers(path)
        low = tier_variant(path, LOW_TIER)
        if low:
            info["low_size"] = low.stat().st_size
            try:
                low_meta = json.loads(low.with_suffix(".json").read_text(encoding="utf-8"))
                info["low_tris"] = low_meta.get("tris")
                info["low_ratio"] = low_meta.get("lod_ratio")
                if low_meta.get("extension_rig"):
                    info["extension_rig"].setdefault("per_tier", {}).setdefault(LOW_TIER, low_meta["extension_rig"])
            except (OSError, ValueError):
                pass
        # FBX case only — a GLB embeds its textures; a stray image next to a
        # GLB is an auxiliary material map, never the basecolor.
        if info["format"] == "fbx":
            tex = find_texture(character_name, path.stem)
            if tex:
                info["texture_size"] = tex.stat().st_size
        from app.core.head_twist import read_head_twist, tpose_status
        from app.core.face_retexture import photo_path
        source_meta = _read_sidecar(path.parent / "unrigged" / f"{path.stem}.glb")
        try:
            photo = photo_path(character_name, path.stem, source_meta)
        except ValueError:
            photo = None
        info["tpose_status"] = tpose_status(match, source_meta, photo)
        twist = read_head_twist(path)
        correction = (_read_sidecar(path).get("blender") or {}).get("head_twist") or {}
        fixed = None
        if correction.get("corrected"):
            before_twist = correction.get("before") or {}
            after_twist = correction.get("after") or {}
            changes = [before_twist[n] - after_twist[n] for n in ("head", "neck")
                       if n in before_twist and n in after_twist]
            if changes:
                fixed = max(changes, key=abs)
        info["head_twist"] = {"current": round(max(twist.values(), key=abs), 1) if twist else None,
                              "corrected": fixed}
        out["model"] = info
    from app.core.extension_rig import motion_payload
    out["motion"] = motion_payload(character_name, profile=profile, preview_states=preview_states)
    draft_profile = {**profile, "model3d_opts": {**(profile.get("model3d_opts") or {}), "extension_motion": {}}}
    out["motion_defaults"] = motion_payload(character_name, profile=draft_profile, apply_clothing=False, apply_states=False)["groups"]
    from app.core.extension_rig import rig_groups_for
    # The served model's own mesh variant decides its part groups.
    out["extension_groups"] = rig_groups_for(
        character_name, profile=profile,
        mesh_variant=(_read_sidecar(path).get("mesh_variant") or "") if path else None)
    out["options"] = get_model3d_options(character_name)
    from app.blender import runner
    out["blender"] = runner.status()
    out.update(list_mesh_backends(occasion=mesh_occasion_for_rig(rig),
                                  character=character_name))
    out["rig_backends"] = list_rig_backends()
    from app.imagegen.service import get_image_service
    out["upscale_backends"] = [{"name": b.name, "model": b.model}
                               for b in get_image_service().list_upscale_backends()]
    from app.imagegen.routing import explain_occasion
    out["upscale_runnable"] = bool(explain_occasion("upscale").get("resolved"))
    out["face_retexture_backends"] = [{"name": b.name, "model": b.model}
                                     for b in get_image_service().list_face_retexture_backends()]
    if path:
        # On the base-body pipeline the face is the base body's (the face
        # routes act on the base signature): status, revert and comparison
        # come from the base model, not from the outfit painted onto it.
        face_path = path
        if _current_base(character_name):
            from app.core.base_body import base_signature
            base_path = path.parent / f"{base_signature(character_name, profile=profile)}.glb"
            if base_path.is_file():
                face_path = base_path
                out["model"]["face_signature"] = base_path.stem
        out["model"].update(face_info(character_name, face_path))
    with _lock:
        out["pending"] = character_name in _generating
        out["rerig_result"] = _rerig_results.get(character_name)
        out["face_retexture_result"] = _face_retexture_results.get(character_name)
    return out


def face_info(character_name: str, face_path: Path) -> Dict[str, Any]:
    """The face-retexture fields of the stored model ``face_path``:
    ``{face_retexture, face_retexture_snapshot, face_retexture_revert,
    face_retexture_compare_url?}`` — the 3D tab's model (the base model's on
    the pipeline) and the Base body tab's base model."""
    from app.core.face_retexture import snapshot_info
    out: Dict[str, Any] = {"face_retexture": _read_sidecar(face_path).get("face_retexture")}
    snapshot = snapshot_info(face_path.parent, face_path.stem)
    out["face_retexture_snapshot"] = snapshot
    out["face_retexture_revert"] = (
        "snapshot" if snapshot["ok"] else "rerig" if (
            not (face_path.parent / "rollback" / face_path.stem).exists()
            and (out["face_retexture"] or {}).get("status") == "applied"
            and (face_path.parent / "unrigged" / f"{face_path.stem}.glb").is_file()) else None)
    if (face_path.parent / "facefix" / f"{face_path.stem}.png").is_file():
        out["face_retexture_compare_url"] = (f"/characters/{quote(character_name)}/model3d/face-retexture/compare"
                                             f"?signature={face_path.stem}")
    return out


def _purge_combination(out_dir: Path, signature: str, *,
                       keep_model: Optional[Path] = None, preserve_unrigged: bool = False,
                       preserve_sources: bool = False,
                       drop_reference_cache: bool = False) -> None:
    """Remove any stored model of this outfit combination (model + texture +
    sidecar), whatever its format/source — the caller writes a fresh one.
    ``keep_model`` preserves the publication target until atomic replacement.
    ``drop_reference_cache`` also removes facefix-ref/ (the upscaled photo);
    only callers that drop the whole combination or its photo set it."""
    from app.core.face_retexture import safe_signature
    safe_signature(signature)
    keep = MODEL_EXTS + (".png", ".jpg", ".jpeg", ".json")
    for old in out_dir.glob(f"{signature}.*"):
        if old.suffix.lower() in keep and old not in (keep_model, keep_model.with_suffix(".json") if keep_model else None):
            old.unlink()
    # The reduced tiers of the same combination go with it — they are derived
    # from the file being replaced and would otherwise be served alongside a
    # model they no longer belong to.
    for tier in MODEL_TIERS:
        if tier == FULL_TIER:
            continue
        for old in (out_dir / tier).glob(f"{signature}.*"):
            if old.suffix.lower() in keep:
                old.unlink()
    # And the raw/ backup: it is the untouched ORIGINAL of the file being
    # replaced. Left behind, it would block the backup of the NEW original
    # (refine.apply_script backs up only the first time) — the incident of
    # 2026-08-06: a fresh bake's pristine copy was silently never kept.
    from app.blender.refine import RAW_DIR_NAME
    # facefix-ref/ is not listed: the upscaled photo outlives a mesh swap
    # (see _publish_signature); see drop_reference_cache below.
    # The garment assemblies are derived from the files being replaced too.
    for directory in (out_dir / "unrigged", out_dir / "facefix", out_dir / RAW_DIR_NAME, out_dir / "prerig", out_dir / LOW_TIER / "prerig", out_dir / LOW_TIER / RAW_DIR_NAME,
                      out_dir / COVERED_DIR, out_dir / ASSEMBLED_DIR, out_dir / ASSEMBLED_DIR / LOW_TIER):
        if (preserve_unrigged and directory.name == "unrigged") or (preserve_sources and directory.name in ("unrigged", "facefix")):
            continue
        for old in directory.glob(f"{signature}.*"):
            old.unlink()
    if drop_reference_cache:
        for old in (out_dir / "facefix-ref").glob(f"{signature}.*"):
            old.unlink()

    if not preserve_sources and not preserve_unrigged:
        if out_dir in getattr(_staging, "directories", {}).values():
            (out_dir / ".replace-source").touch()
        else:
            snapshot = out_dir / "rollback" / signature
            if snapshot.resolve().is_relative_to(out_dir.resolve()) and snapshot.is_dir():
                shutil.rmtree(snapshot)


def invalidate_models_for_item(character_name: str, item_id: str) -> set:
    """Drops every cached mesh whose manifest contains this item.

    Counterpart of ``model_refs.invalidate_refs_for_item`` for the mesh
    store: the outfit signature keys on item IDs, so a changed
    ``prompt_fragment`` renders a different picture under the SAME signature
    and the stored mesh would stay stale forever (the cache GC calls it
    valid). Purges the model, its texture, sidecar, reduced tiers and raw
    backup — the same set a re-generation of that combination replaces.

    Returns the signatures purged.
    """
    out: set = set()
    if not item_id:
        return out
    from app.core.outfit_cache_gc import read_manifest
    d = get_model3d_dir(character_name)
    if not d.exists():
        return out
    for sidecar in sorted(d.glob("*.json")):
        manifest = read_manifest(sidecar)
        if manifest is None:
            continue  # nothing recorded — never delete on a guess
        if item_id not in (set(manifest["pieces"].values())
                           | set(manifest["items"])):
            continue
        try:
            # The item changed the outfit picture, so the photo is re-rendered:
            # its upscaled copy is stale too.
            _purge_combination(d, sidecar.stem, drop_reference_cache=True)
        except OSError as e:
            logger.warning("Model3D invalidation %s: %s not removed: %s",
                           character_name, sidecar.stem, e)
            continue
        out.add(sidecar.stem)
    if out:
        logger.info("Model3D invalidation %s: item %s -> %d combination(s) "
                    "dropped", character_name, item_id, len(out))
    return out


def _publish_model_bytes(target: Path, contents: bytes) -> None:
    """Publish a complete file by replacing from a unique same-directory stage."""
    import os
    import tempfile
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".mesh-", suffix=".tmp",
                                         delete=False) as stream:
            staged = Path(stream.name)
            stream.write(contents)
        os.replace(staged, target)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _publish_sidecar(path: Path, meta: Dict[str, Any]) -> None:
    """Sidecars use the same atomic publication as model bytes."""
    _publish_model_bytes(path.with_suffix(".json"),
                         json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8"))


def _read_sidecar(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# Extension-group operations that build an anatomy part (and its bone).
PART_OPS = ("attached_part", "attached_part_bone", "inset_part")


def _auto_extension_rig(character_name: str, path: Path,
                        meta: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """Build declared extensions from a clean source; failed gates preserve bytes.

    A base body (``meta["base"]``) then also refreshes its covered variant
    (``_auto_covered_variant``) — a failure there is recorded in
    ``meta["covered_variant"]`` and never fails the base."""
    result = _extension_rig_once(character_name, path, meta, force=force)
    if meta.get("base") and not meta.get("base_variant") and path.parent.name != LOW_TIER:
        try:
            if _auto_covered_variant(character_name, path, meta, force=force) and result.get("noop"):
                # The base sidecar must record the new variant state.
                result = {**result, "noop": False}
        except Exception as exc:  # noqa: BLE001 — the base stays published
            logger.warning("Model3D %s: covered variant failed: %s", character_name, exc)
            meta["covered_variant"] = {"status": "failed", "reason": str(exc), "at": utc_now_iso()}
            result = {**result, "noop": False}
    # ``noop`` stays the extension rig's answer: a no-op rebuild publishes no
    # sidecar, and the next ``collision.ensure_path`` stores the set then.
    _auto_collision(character_name, path, meta)
    return result


def _auto_collision(character_name: str, path: Path, meta: Dict[str, Any]) -> bool:
    """The post-rig step after the extension rig: the collision capsules of
    the full-tier model ``path`` into ``meta["collision"]``
    (``collision.refresh``; the caller publishes the sidecar). An outfit on
    the base body keeps the set of the base it was built on. Never fails the
    model. Returns True when the record changed."""
    if path.parent.name == LOW_TIER:
        return False
    from app.core import collision
    try:
        return collision.refresh(character_name, path, meta)
    except Exception as exc:  # noqa: BLE001 — capsules never block a model
        logger.warning("Model3D %s: collision capsules failed: %s", character_name, exc)
        return False


def _extension_groups_for(meta: Dict[str, Any], groups):
    """The extension groups a model of ``meta`` carries: a base body never
    the anatomy parts (``PART_OPS``, they belong to the outfit models), the
    covered variant of a base body — and an outfit built from it
    (``base_variant: "covered"``) — never the ``exposed_only`` groups."""
    if meta.get("base"):
        groups = [g for g in groups if g["op"] not in PART_OPS]
    if meta.get("base_variant") == "covered":
        groups = [g for g in groups if not g.get("exposed_only")]
    return groups


def _auto_covered_variant(character_name: str, path: Path, meta: Dict[str, Any], *,
                          force: bool = False) -> bool:
    """Keep ``covered/<bsig>.glb``: the base body ``path`` built once more
    from the SAME clean prerig source with every ``exposed_only`` extension
    group left out. Every other group runs on the same source bytes with the
    same declarations and overrides as the base, so its bones (a colour
    apex included) are those of the base. Its sidecar: ``source_sha256``
    (the prerig it was built from), ``extension_rig`` (its own state, which
    an outfit built from it copies), ``blender``, ``rig``, ``groups_removed``.

    Without any applicable ``exposed_only`` group (or for a non-humanoid
    model) the variant is removed and ``meta["covered_variant"]`` dropped.
    A current variant (same source bytes, same fingerprint) is kept unless
    ``force``. Records ``meta["covered_variant"]`` ``{status: built|failed,
    groups_removed, at, reason}``. Returns True when the variant or its
    record changed."""
    from app.core.extension_rig import (extension_rig_fingerprint, model_extension_overrides,
                                       rig_groups_for)
    from app.models.character import get_character_profile
    target = path.parent / COVERED_DIR / path.name
    profile = get_character_profile(character_name) or {}
    declarations = _extension_groups_for(meta, rig_groups_for(
        character_name, profile=profile, mesh_variant=meta.get("mesh_variant") or ""))
    removed = sorted(g["id"] for g in declarations if g.get("exposed_only"))
    before = meta.get("covered_variant")
    if not removed or path.suffix.lower() != ".glb" or meta.get("rig") != "mixamo":
        changed = target.exists() or before is not None
        for old in (target, target.with_suffix(".json")):
            old.unlink(missing_ok=True)
        meta.pop("covered_variant", None)
        return changed
    source = path.parent / "prerig" / path.name
    if not source.is_file():
        for old in (target, target.with_suffix(".json")):
            old.unlink(missing_ok=True)
        meta["covered_variant"] = {"status": "failed", "groups_removed": removed,
                                   "reason": "Clean prerig source is missing", "at": utc_now_iso()}
        return True
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    kept = [g for g in declarations if not g.get("exposed_only")]
    fingerprint = extension_rig_fingerprint(kept, model_extension_overrides(profile, path.stem))
    previous = _read_sidecar(target) if target.is_file() else {}
    if (not force and previous.get("source_sha256") == source_sha
            and (previous.get("extension_rig") or {}).get("fingerprint") == fingerprint
            and (previous.get("extension_rig") or {}).get("status") != "failed"
            and (before or {}).get("status") == "built"):
        return False
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".covered-", dir=path.parent) as tmp:
        work = Path(tmp) / path.name
        (Path(tmp) / "prerig").mkdir()
        work.write_bytes(source_bytes)
        (Path(tmp) / "prerig" / path.name).write_bytes(source_bytes)
        source_meta = _read_sidecar(source)
        _publish_sidecar(Path(tmp) / "prerig" / path.name, source_meta)
        covered_meta: Dict[str, Any] = {"rig": "mixamo", "base": True, "base_variant": "covered",
                                        "blender": source_meta.get("blender") or {},
                                        "mesh_variant": meta.get("mesh_variant") or ""}
        result = _extension_rig_once(character_name, work, covered_meta, force=True)
        state = covered_meta.get("extension_rig") or {}
        if not result.get("ok") or state.get("status") == "failed":
            for old in (target, target.with_suffix(".json")):
                old.unlink(missing_ok=True)
            meta["covered_variant"] = {"status": "failed", "groups_removed": removed,
                                       "reason": result.get("error") or state.get("reason") or "Extension rig failed",
                                       "at": utc_now_iso()}
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        _publish_model_bytes(target, work.read_bytes())
        _publish_sidecar(target, {"rig": "mixamo", "source_sha256": source_sha,
                                  "groups_removed": removed, "extension_rig": state,
                                  "blender": covered_meta.get("blender") or {},
                                  "created_at": utc_now_iso()})
    meta["covered_variant"] = {"status": "built", "groups_removed": removed, "at": utc_now_iso()}
    logger.info("Model3D %s: covered variant of %s without %s", character_name, path.stem, ", ".join(removed))
    return True


def _extension_rig_once(character_name: str, path: Path,
                        meta: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """The extension rig of ONE model file (``_auto_extension_rig``)."""
    import tempfile
    from app.blender import refine
    from app.core.extension_rig import (rig_groups_for, resolved_extension_groups,
                                       extension_rig_fingerprint, model_extension_overrides)
    from app.core.model_validate import parse_glb, validate_glb
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    # The part follows how THIS mesh was rendered: a source drawn with
    # clothing (or anatomy) over the slot never gets a procedural part.
    mesh_variant = meta.get("mesh_variant") or ""
    declarations = rig_groups_for(character_name, profile=profile, mesh_variant=mesh_variant)
    # A base body gets every extension group BUT the anatomy parts: those
    # belong to the outfit models painted onto it (spec B.4), which inherit
    # this rig with its jiggle/secondary bones. A covered variant (and an
    # outfit built from it) leaves the exposed-only groups out as well.
    declarations = _extension_groups_for(meta, declarations)
    overrides = model_extension_overrides(profile, path.stem)
    fingerprint = extension_rig_fingerprint(declarations, overrides)
    previous = meta.get("extension_rig") or {}
    source_blender = _read_sidecar(path.parent / "prerig" / path.name).get("blender") or {}
    # A forced rebuild is only a no-op when the source is already as clean as
    # it gets: a humanoid source still lacking the weight repair is rebuilt.
    source_current = (source_blender == (meta.get("blender") or {})
                      and (meta.get("rig") != "mixamo"
                           or "limb_weights" in (source_blender.get("steps") or [])))
    # A failed part publishes the body without it while the aggregate stays
    # "applied"; a forced rebuild must still retry the part.
    part_failed = any(op in ("attached_part", "inset_part") and ((previous.get("metrics") or {}).get(gid) or {}).get("status") == "failed"
                      for gid, op in (previous.get("group_ops") or {}).items())
    if previous.get("attempted") and previous.get("status") in ("applied", "not_found", "none_applicable") and previous.get("fingerprint") == fingerprint and (not force or (previous.get("status") == "applied"
            and source_current and not part_failed)):
        return {"ok": previous.get("status") != "failed", "applied": False, "noop": True, "extension_rig": previous}
    groups = [g for g in _extension_groups_for(meta, resolved_extension_groups(
                  character_name, profile=profile, signature=path.stem, mesh_variant=mesh_variant))
              if g["enabled"]]
    state = {"fingerprint": fingerprint, "groups": [g["id"] for g in declarations],
             "group_ops": {g["id"]: g["op"] for g in declarations},
             "group_params": {g["id"]: g["params"] for g in declarations if g["op"] in ("attached_part", "inset_part")},
             "status": "not_found" if groups else "none_applicable",
             "reason": "", "has_applied": previous.get("has_applied", previous.get("status") == "applied"), "attempted": True, "attempted_at": utc_now_iso(), "metrics": {}, "per_tier": {}}
    meta["extension_rig"] = state
    if path.suffix.lower() != ".glb" or meta.get("rig") != "mixamo":
        state.update(status="none_applicable", reason="Extension bones require a humanoid GLB")
        return {"ok": True, "applied": False, "extension_rig": state}
    source = path.parent / "prerig" / path.name
    if not groups and not state["has_applied"]:
        # A failed later attempt can still leave a previously rigged mesh;
        # its existing prerig source drives the removal path below.
        return {"ok": True, "applied": False, "extension_rig": state}
    if not source.exists():
        # Never mistake a rigged asset for an unattenuated source.
        try:
            gltf = parse_glb(path.read_bytes())["gltf"]
            nodes = gltf.get("nodes") or []
            extra = any(norm_bone_name(nodes[j].get("name", "")) not in BASE_JOINT_KEYS
                        for skin in gltf.get("skins", []) for j in skin.get("joints", []))
        except (ValueError, KeyError, IndexError, TypeError):
            extra = True
        if extra:
            state.update(status="failed", reason="Clean prerig source is missing for an extended or unreadable model")
            return {"ok": False, "applied": False, "extension_rig": state, "error": state["reason"]}
        source.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=path.parent) as tmp:
            prepared = Path(tmp) / path.name
            shutil.copy2(path, prepared)
            prepared_meta = dict(meta)
            try:
                _auto_normalize(character_name, prepared, prepared_meta, required=True)
                verdict = validate_glb(prepared.read_bytes())
                if not verdict.get("ok"):
                    raise ValueError("; ".join(verdict.get("errors") or []))
            except (ValueError, RuntimeError) as e:
                state.update(status="failed", reason="Clean source preparation failed: " + str(e))
                return {"ok": False, "applied": False, "extension_rig": state, "error": state["reason"]}
            _publish_model_bytes(source, prepared.read_bytes())
            _publish_sidecar(source, {"blender": prepared_meta.get("blender") or {}, "rig": "mixamo"})
    source_meta = _read_sidecar(source)
    source_meta.setdefault("rig", "mixamo")
    try:
        _auto_normalize(character_name, source, source_meta, required=True)
        verdict = validate_glb(source.read_bytes())
        if not verdict.get("ok"):
            raise ValueError("; ".join(verdict.get("errors") or []))
    except (ValueError, RuntimeError) as e:
        state.update(status="failed", reason="Clean source preparation failed: " + str(e))
        return {"ok": False, "applied": False, "extension_rig": state, "error": state["reason"]}
    _publish_sidecar(source, source_meta)
    if not groups:
        changed = path.read_bytes() != source.read_bytes()
        if changed:
            _publish_model_bytes(path, source.read_bytes())
        if changed:
            meta["blender"] = source_meta.get("blender") or {}
        state["has_applied"] = False
        return {"ok": True, "applied": changed, "extension_rig": state}
    with tempfile.TemporaryDirectory(prefix=".extension-", dir=path.parent) as tmp:
        staged = Path(tmp) / path.name
        shutil.copy2(source, staged)
        attached = [g for g in groups if g["op"] == "attached_part"]
        companions = [g for g in groups if g["op"] == "attached_part_bone"]
        remaining = [g for g in groups if g["op"] not in ("attached_part", "attached_part_bone", "inset_part")]
        validator = _validator_for("mixamo", character_name)
        inset = [g for g in groups if g["op"] == "inset_part"]
        part_applied = False
        # Each operation is isolated so a failed later part preserves earlier work.
        batches = [("attached_part", attached + companions)] if attached else []
        batches.extend(("inset_part", [group]) for group in inset)
        for operation, batch in batches:
            before_part = staged.read_bytes()
            try:
                part_result = refine.apply_script(
                    staged, operation, {"groups": batch},
                    validator=validator, require_smaller=False,
                    keep_original=False, base_joints_only=True, timeout_s=600)
            except Exception as exc:
                part_result = {"applied": False, "error": str(exc)}
            part_data = part_result.get("data") or {}
            part_metrics = part_data.get("metrics") or part_data.get("groups") or {}
            applied = bool(part_result.get("applied"))
            part_applied = part_applied or applied
            reason = part_data.get("reason") or part_result.get("error") or "Part build produced no model"
            for group in batch:
                state["metrics"][group["id"]] = {
                    **part_metrics.get(group["id"], {}),
                    "status": "applied" if applied else "failed",
                    "reason": "" if applied else reason}
            if not applied:
                staged.write_bytes(before_part)
        if remaining:
            result = refine.apply_script(staged, "extension_bones", {"groups": remaining},
                                         validator=validator,
                                         require_smaller=False, keep_original=False,
                                         base_joints_only=True)
            data = result.get("data") or {}
            state["metrics"].update(data.get("metrics") or data.get("groups") or {})
            if not result.get("applied"):
                for group in remaining:
                    state["metrics"].setdefault(group["id"], {
                        "status": data.get("status") or "failed",
                        "reason": data.get("reason") or result.get("error") or "No extension model produced"})
        else:
            result = {"applied": part_applied, "data": {}}
            data = {}
        state["reason"] = data.get("reason") or result.get("error") or ""
        # A failed part publishes a validated clean body (with other extensions
        # when available), replacing any stale part from a previous build.
        publish = bool(result.get("applied")) or bool(batches)
        if publish:
            verdict = validator(staged.read_bytes())
            if not verdict.get("ok"):
                publish = False
                state["reason"] = "; ".join(verdict.get("errors") or [])
        if publish:
            _publish_model_bytes(path, staged.read_bytes())
            meta["blender"] = source_meta.get("blender") or {}
            state.update(status="applied", has_applied=part_applied or bool(remaining and result.get("applied")))
        else:
            state["status"] = data.get("status") if data.get("status") in ("not_found", "failed") else "failed"
        state["per_tier"][LOW_TIER if path.parent.name == LOW_TIER else FULL_TIER] = {
            key: state[key] for key in ("fingerprint", "groups", "status", "reason", "metrics", "attempted", "attempted_at")}
        return {"ok": state["status"] != "failed", "applied": publish,
                "extension_rig": state, "error": state["reason"]}


def _extension_state_current(character_name: str, path: Path, meta: Dict[str, Any]) -> bool:
    """Whether the stored extension state of ``path`` matches what
    ``_extension_rig_once`` would build now (its no-op condition without a
    force): attempted, not failed, same fingerprint."""
    from app.core.extension_rig import (extension_rig_fingerprint, model_extension_overrides,
                                       rig_groups_for)
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    declarations = _extension_groups_for(meta, rig_groups_for(
        character_name, profile=profile, mesh_variant=meta.get("mesh_variant") or ""))
    previous = meta.get("extension_rig") or {}
    return bool(previous.get("attempted")
                and previous.get("status") in ("applied", "not_found", "none_applicable")
                and previous.get("fingerprint") == extension_rig_fingerprint(
                    declarations, model_extension_overrides(profile, path.stem)))


@_serial_model
def rebuild_extension_rig(character_name: str, signature: Optional[str] = None, *,
                          tier: str = FULL_TIER, force: bool = False) -> Dict[str, Any]:
    """Rebuild a stored model from prerig and derive its distance tier anew."""
    if tier not in MODEL_TIERS:
        raise ValueError("Unknown model tier")
    path = (find_model3d(character_name, signature) if signature
            else find_model3d_serving(character_name)[0])
    if path is None:
        return {"ok": False, "error": "no_model"}
    if tier == LOW_TIER:
        low = tier_variant(path, LOW_TIER)
        if low is None:
            result = rebuild_extension_rig(character_name, path.stem, force=force)
            return result
        if _read_sidecar(low).get("source") == "lod":
            return rebuild_extension_rig(character_name, path.stem, force=force)
        path = low
    meta = _read_sidecar(path)
    meta.setdefault("rig", required_rig(character_name))
    if tier == FULL_TIER and meta.get("source") == "base_body" and not meta.get("base"):
        # An outfit on the base body is never rebuilt from its own geometry
        # (a painted outfit hides the colour markers; the bones would move):
        # a forced or outdated extension rig builds the outfit model anew.
        from app.core import base_body
        if base_body.is_base_pipeline(character_name) and (
                force or not _extension_state_current(character_name, path, meta)):
            result = base_body.build_outfit_model(character_name, path.stem)
            result["noop"] = False
            result["extension_rig"] = _read_sidecar(path).get("extension_rig") or {}
            if result.get("ok"):
                result["model_rev"] = model_revision(path)
            return result
    original_bytes = path.read_bytes()
    original_meta = json.loads(json.dumps(meta))
    result = _auto_extension_rig(character_name, path, meta, force=force)
    if not result.get("noop"):
        _publish_sidecar(path, meta)
    if (result.get("ok") and tier == FULL_TIER and not meta.get("base")
            and (meta.get("extension_rig") or {}).get("status") in ("applied", "none_applicable")):
        low = tier_variant(path, LOW_TIER)
        low_meta = _read_sidecar(low) if low else {}
        state = meta.get("extension_rig") or {}
        low_state = low_meta.get("extension_rig") or {}
        current_low = (low is not None and low_state.get("fingerprint") == state.get("fingerprint")
                       and low_state.get("status") != "failed"
                       and (state.get("per_tier", {}).get(LOW_TIER) or {}).get("status") != "failed")
        if not current_low or result.get("applied"):
            if low and low_meta.get("source") != "lod":
                low_result = rebuild_extension_rig(character_name, path.stem, tier=LOW_TIER, force=force)
            else:
                low_result = build_lod(character_name, path.stem, ratio=_auto_lod_ratio())
            result["low"] = low_result
            if not low_result.get("ok"):
                result["ok"] = False
                result["error"] = low_result.get("error") or "Low tier rebuild failed"
                # Keep the previous complete tier if the replacement fails.
                _publish_model_bytes(path, original_bytes)
                meta = original_meta
                meta.setdefault("extension_rig", {}).setdefault("per_tier", {})[LOW_TIER] = {
                    **low_state, "status": "failed", "reason": result["error"]}
                _publish_sidecar(path, meta)
                result["applied"] = False
                result["extension_rig"] = meta.get("extension_rig") or {}
            result["noop"] = False
    result["model_rev"] = model_revision(path if tier == FULL_TIER else path.parent.parent / path.name)
    return result


def extension_rebuild_targets(character_name: str) -> tuple[List[Path], List[Path]]:
    """``(targets, skipped)``: the stored full models (``*.glb``, no state
    forks) that "Rebuild extension bones for all models" rebuilds, in that
    order, and the ones it leaves alone. Off the pipeline every model is a
    target, sorted by name. Base-body pipeline: the CURRENT base model goes
    first — every outfit model is built from it, so an outfit rebuilt before
    it would be stale the moment the base changes; a base model of an older
    base signature and an outfit model that is stale anyway (``find_model3d``
    does not find it; rebuilt on its next trigger) are skipped. The
    Improvements type ``extension_rig_rebuild`` checks completion on the
    same targets."""
    from app.core.base_body import is_base_signature
    from app.core.model_refs import is_state_fork
    current = _current_base(character_name)
    paths = sorted((path for path in get_model3d_dir(character_name).glob("*.glb")
                    if not is_state_fork(path.stem)),
                   key=lambda path: (not current or path.stem != current[0], path.stem))
    targets: List[Path] = []
    skipped: List[Path] = []
    for path in paths:
        stale = bool(current) and (is_base_signature(path.stem) and path.stem != current[0]
                                   or find_model3d(character_name, path.stem) is None)
        (skipped if stale else targets).append(path)
    return targets, skipped


def extension_state_current(character_name: str, path: Path, meta: Dict[str, Any]) -> bool:
    """Public form of ``_extension_state_current`` (the Improvements type's
    completion check): the stored extension state of ``path`` matches what a
    rebuild would produce now — with the groups THIS model carries (a base
    body without the anatomy parts, a covered variant without the
    exposed-only groups)."""
    return _extension_state_current(character_name, path, meta)


def rebuild_character_extension_rigs(character_name: str) -> Dict[str, Any]:
    """Rebuild every stored full model of one character for the Improvements
    queue — the targets of ``extension_rebuild_targets``; skipped models
    report ``{"ok": True, "skipped": "stale"}``, never a failure."""
    targets, skipped = extension_rebuild_targets(character_name)
    results: Dict[str, Any] = {path.stem: {"ok": True, "skipped": "stale"} for path in skipped}
    for path in targets:
        results[path.stem] = rebuild_extension_rig(character_name, path.stem, force=True)
    return {"ok": all(result.get("ok") for result in results.values()), "models": results}


def save_uploaded_model(character_name: str, original_filename: str,
                        contents: bytes, *, rig: str,
                        texture: Optional[bytes] = None,
                        signature: Optional[str] = None) -> Dict[str, Any]:
    """Process an upload in a worker, then publish one final signature."""
    from app.core.model_refs import is_state_fork
    if is_state_fork(signature) or "-p" in (signature or ""):
        raise ValueError("State fork mesh signatures are retired")
    pieces, items, current = current_outfit_state(character_name)
    return _save_uploaded_model(character_name, original_filename, contents,
                                rig=rig, texture=texture,
                                outfit=(pieces, items, signature or current),
                                signature=signature or current)


@_serial_model
def _save_uploaded_model(character_name: str, original_filename: str,
                         contents: bytes, *, rig: str,
                         texture: Optional[bytes], outfit: tuple,
                         signature: str) -> Dict[str, Any]:
    """Stores an uploaded model as the current outfit's model (replacing any
    generated or previously uploaded one). ``texture`` is the basecolor PNG
    that belongs to an FBX; a GLB embeds its textures. Validation is the
    caller's job (app/core/model_validate.py)."""
    from app.core.model_refs import is_state_fork
    if is_state_fork(signature) or "-p" in signature:
        raise ValueError("State fork mesh signatures are retired")
    ext = Path(original_filename.lower()).suffix
    pieces, items, _ = outfit
    out_dir = get_model3d_dir(character_name)
    target = out_dir / f"{signature}{ext}"
    _purge_combination(out_dir, signature, keep_model=target)
    _publish_model_bytes(target, contents)
    if texture is not None:
        _publish_model_bytes(target.with_suffix(".png"), texture)
    from app.core.model_refs import mesh_items_token, mesh_variant
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
        "mesh_variant": mesh_variant(character_name, pieces),
        "pieces": dict(pieces or {}),
        "items": list(items or []),
    }
    token = mesh_items_token(character_name, pieces)
    if token:
        meta["mesh_token"] = token
    # An upload takes the same route as a generated model: re-encode and
    # normalise first, then measure, so the numbers describe what will be
    # served.
    _auto_retexture(character_name, target, meta)
    _auto_normalize(character_name, target, meta)
    _auto_extension_rig(character_name, target, meta)
    _attach_measurement(meta, target)
    from app.core.extension_rig import extension_metadata
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=target.stem))
    _publish_sidecar(target, meta)
    request_lod(character_name, target)
    logger.info("Model3D %s: upload %s (%d bytes, combination %s)",
                character_name, target.name, len(contents), signature)
    return meta


def _attach_measurement(meta: Dict[str, Any], path: Path) -> None:
    """Measures the stored file and puts the numbers in ``meta`` (best-effort;
    see app/blender/refine.py). The mesh itself is never touched."""
    from app.blender.refine import attach_measurement
    attach_measurement(meta, path)


def _validator_for(rig: str, character_name: str):
    """The check a model of this rig must pass — the same one a fresh
    delivery faces, so a refinement can never lower the bar.

    Only a MIXAMO model owes the 52-joint rule. A generic rig has its own
    skeleton by definition, and a static model has none; holding either to the
    humanoid check would reject every refinement of it out of hand."""
    from app.core.model_validate import validate_glb, validate_static_glb
    from app.core.extension_rig import extension_bone_names
    if rig == "mixamo":
        context = extension_bone_names(character_name)
        return lambda data: validate_glb(data, extension_names=context)
    return validate_static_glb


def _target_height_m(character_name: str) -> float:
    """The height the stored mesh must have, in metres: the profile height,
    else the contract's base figure (schnittstellen-3d.md § A3, 1.70 m)."""
    from app.core.height import height_cm
    from app.models.character import get_character_profile
    cm = height_cm(get_character_profile(character_name) or {})
    return (cm / 100.0) if cm else 1.70


def _auto_normalize(character_name: str, path: Path,
                    meta: Dict[str, Any], *, required: bool = False,
                    fail_on_error: bool = False) -> None:
    """Scales the fresh mesh to the character's height and grounds it, if
    switched on (plan-blender-veredelung.md § 2, decided 2026-08-06).

    A Mixamo rig is measured at the crown joint — hair and hats above it no
    longer shrink the body, which the old client-side bounding-box scale did.
    ``meta["blender"].steps`` is the idempotence guard (§ 2.3): a normalised
    file is never normalised again; the gates in ``refine.apply_script`` keep
    the original whenever the export fails the delivery validation (§ 2.2).
    """
    from app.blender import refine, runner
    if (not required and not refine.auto_normalize_enabled()) or path.suffix.lower() != ".glb":
        return
    done = list((meta.get("blender") or {}).get("steps") or [])
    if "normalize" in done:
        if meta.get("rig") != "mixamo" or "limb_weights" in done:
            return
        try:
            res = refine.limb_weights(path, validator=_validator_for("mixamo", character_name))
            report = dict(res.get("data") or {})
            success = (res.get("ok") and (res.get("applied") or res.get("error") in ("", "nothing to do"))
                       and not report.get("error"))
            if not success:
                report["error"] = report.get("error") or res.get("error") or "Weight repair failed"
        except Exception as exc:
            report = {"error": str(exc)}
            success = False
        meta.setdefault("blender", {})["limb_weights"] = report
        if success:
            meta["blender"]["steps"] = done + ["limb_weights"]
        else:
            logger.warning("Model3D %s: weight repair failed (%s)", character_name, report["error"])
        return
    target = _target_height_m(character_name)
    # The unrigged mesh the rigger was given is the ground truth of the
    # posture: the rigger re-poses into its own rest and leans the trunk by a
    # noisy amount (normalize._restore_posture) — nothing without the source.
    unrigged = path.parent / "unrigged" / f"{path.stem}.glb"
    res = refine.normalize(path, target,
                           repair_limb_weights=(meta.get("rig") == "mixamo"),
                           validator=_validator_for(meta.get("rig") or "", character_name),
                           posture_source=unrigged if (meta.get("rig") == "mixamo"
                                                       and unrigged.is_file()) else None)
    data = res.get("data") or {}
    if not res.get("applied"):
        if required or fail_on_error:
            raise RuntimeError(res.get("error") or "Normalization produced no validated output")
        if res.get("error"):
            logger.info("Model3D %s: normalisation not applied (%s)",
                        character_name, res.get("error"))
        return
    meta["blender"] = {
        "version": runner.version(),
        "steps": done + ["normalize"],
        "at": utc_now_iso(),
        "height_basis": data.get("height_basis", ""),
        "scale": data.get("scale"),
        "target_height_m": data.get("target_height_m"),
        "before": data.get("before") or {},
        "after": data.get("after") or {},
    }
    if "head_twist" in data:
        meta["blender"]["head_twist"] = data["head_twist"]
    if "posture" in data:
        meta["blender"]["posture"] = data["posture"]
    if "limb_weights" in data:
        meta["blender"]["limb_weights"] = data["limb_weights"]
        if not data["limb_weights"].get("error"):
            meta["blender"]["steps"].append("limb_weights")
    logger.info("Model3D %s: normalised to %.2f m (%s basis, scale %.4f)",
                character_name, target, data.get("height_basis", "?"),
                float(data.get("scale") or 0))


def _auto_retexture(character_name: str, path: Path,
                    meta: Dict[str, Any]) -> None:
    """Re-encodes the stored model's textures, if that is switched on.

    Records the outcome in ``meta["refined"]`` either way: a refinement that
    was skipped or rejected is worth seeing in the panel, otherwise a model
    that quietly stayed 9 MB looks the same as one that was never eligible.
    """
    from app.blender import refine
    if not refine.auto_retexture_enabled() or path.suffix.lower() != ".glb":
        return
    res = refine.retexture(path, validator=_validator_for(meta.get("rig") or "", character_name))
    data = res.get("data") or {}
    meta["refined"] = {
        "retexture": bool(res.get("applied")),
        "reason": res.get("error", ""),
        "bytes_saved": data.get("bytes_saved", 0) if res.get("applied") else 0,
        "at": utc_now_iso(),
    }
    if not res.get("applied") and res.get("error"):
        logger.info("Model3D %s: texture re-encode not applied (%s)",
                    character_name, res["error"])


@_serial_model
def repair_model_weights(character_name: str, signature: str) -> Dict[str, Any]:
    """Repair the pelvis limb weights of a stored humanoid model, every tier.

    The clean prerig sources are repaired first; a model with applied
    extension bones is then rebuilt from its repaired source, any other model
    is repaired in place. A derived low tier is rebuilt from the full one.
    A failure publishes nothing, so the improvement can retry.
    """
    path = find_model3d(character_name, signature)
    repaired: Dict[str, Any] = {}
    if path is None:
        return {"ok": False, "repaired": repaired, "error": "no_model"}
    tiers = {FULL_TIER: path}
    low = tier_variant(path, LOW_TIER)
    if low:
        tiers[LOW_TIER] = low

    def checked(tier, target, meta, *, required=False):
        _auto_normalize(character_name, target, meta, required=required)
        _publish_sidecar(target, meta)
        block = meta.get("blender") or {}
        report = block.get("limb_weights") or {}
        repaired[tier] = report
        if "limb_weights" not in (block.get("steps") or []):
            raise RuntimeError(report.get("error") or "Weight repair did not complete")

    try:
        # Repair both independent sources before a full extension rebuild can
        # recursively rebuild the low tier.
        for tier, target in tiers.items():
            meta = _read_sidecar(target)
            if tier == LOW_TIER and meta.get("source") == "lod":
                continue
            source = target.parent / "prerig" / target.name
            if source.is_file():
                source_meta = _read_sidecar(source)
                source_meta.setdefault("rig", meta.get("rig", "mixamo"))
                checked(tier, source, source_meta, required=True)
        full_rebuilt = False
        for tier, target in tiers.items():
            meta = _read_sidecar(target)
            if tier == LOW_TIER and meta.get("source") == "lod":
                if not full_rebuilt:
                    result = build_lod(character_name, signature, ratio=_auto_lod_ratio())
                    if not result.get("ok"):
                        raise RuntimeError(result.get("error") or "Low tier rebuild failed")
                repaired[tier] = (_read_sidecar(target).get("blender") or {}).get(
                    "limb_weights", repaired.get(FULL_TIER, {}))
                continue
            source = target.parent / "prerig" / target.name
            state = meta.get("extension_rig") or {}
            if source.is_file() and (state.get("status") == "applied" or state.get("has_applied")):
                # A full rebuild already handles an independent low tier.
                if tier != LOW_TIER or not full_rebuilt:
                    result = rebuild_extension_rig(character_name, signature, tier=tier, force=True)
                    if not result.get("ok"):
                        raise RuntimeError(result.get("error") or "Extension rebuild failed")
                    full_rebuilt = tier == FULL_TIER and bool((result.get("low") or {}).get("ok"))
                block = _read_sidecar(target).get("blender") or {}
                repaired[tier] = block.get("limb_weights") or {}
                if "limb_weights" not in (block.get("steps") or []):
                    raise RuntimeError("Rebuilt model is missing repaired weights")
            else:
                checked(tier, target, meta)
        return {"ok": True, "repaired": repaired, "error": ""}
    except Exception as exc:
        logger.warning("Model3D %s: stored weight repair failed (%s)", character_name, exc)
        return {"ok": False, "repaired": repaired, "error": str(exc)}


@_serial_model
def measure_model(character_name: str, signature: Optional[str] = None, *,
                  force: bool = False) -> Dict[str, Any]:
    """Real geometry of a stored model — world-space size, triangles, bone
    names, whether UVs exist — measured by Blender and cached in the sidecar.

    What the GLB header claims and what the geometry IS are two different
    things; this is the second one. Cached against the file size, so a
    replaced model is re-measured on its own and ``force`` is only needed
    after a change that keeps the size identical.

    ``signature`` None = whatever is currently SERVED (which may be a nearest
    stand-in, exactly as the viewer shows it).
    """
    path = (find_model3d(character_name, signature) if signature
            else find_model3d_serving(character_name)[0])
    if not path:
        return {"ok": False, "error": "no_model"}
    meta_path = path.with_suffix(".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) \
            if meta_path.exists() else {}
    except (OSError, ValueError):
        meta = {}
    cached = meta.get("measured") or {}
    if cached and not force and cached.get("file_bytes") == path.stat().st_size:
        return {"ok": True, "cached": True, "measured": cached}
    _attach_measurement(meta, path)
    if not meta.get("measured"):
        from app.blender.refine import unavailable_reason
        return {"ok": False, "error": unavailable_reason() or "measurement failed"}
    from app.core.extension_rig import extension_metadata
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    try:
        _publish_sidecar(path, meta)
    except OSError as e:
        logger.warning("Model3D %s: measurement not stored: %s", path.name, e)
    return {"ok": True, "cached": False, "measured": meta["measured"]}


@_serial_model
def diagnose_model(character_name: str, signature: Optional[str] = None, *,
                   force: bool = False) -> Dict[str, Any]:
    """Geometry-defect indicators of a stored model, cached in the sidecar.

    Display only (plan-blender-veredelung.md § 5a.4): the one known defect —
    a bake that turned a garment into flat wings and dissolved the limbs into
    it — separates cleanly when THREE markers fire together (skin spread > 5,
    fewer than 40 of the 52 joints owning vertices, more than 100 floating
    fragments). Each marker alone is a false-alarm generator (a mermaid tail
    or a long dress looks like spread), and the rule is calibrated on exactly
    one case — so the panel SHOWS the finding and nothing acts on it.

    Cached against the file size like the measurement; reads only.
    """
    path = (find_model3d(character_name, signature) if signature
            else find_model3d_serving(character_name)[0])
    if not path:
        return {"ok": False, "error": "no_model"}
    meta_path = path.with_suffix(".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) \
            if meta_path.exists() else {}
    except (OSError, ValueError):
        meta = {}
    cached = meta.get("diagnosis") or {}
    if cached and not force and cached.get("file_bytes") == path.stat().st_size:
        return {"ok": True, "cached": True, "diagnosis": cached}
    from app.blender import runner
    from app.blender.refine import unavailable_reason
    res = runner.run("diagnose", inputs={"model": path})
    if not res.get("ok"):
        return {"ok": False,
                "error": unavailable_reason() or res.get("error")
                or "diagnosis failed"}
    data = dict(res["data"])
    flags = {
        "skin_spread": float(data.get("skin_spread_max") or 0) > 5.0,
        "bones_missing": 0 < int(data.get("bones_with_verts") or 0) < 40,
        "fragments": int(data.get("tiny_parts") or 0) > 100,
    }
    diagnosis = {
        "at": utc_now_iso(),
        "blender": runner.version(),
        "file_bytes": path.stat().st_size,
        "data": data,
        "flags": flags,
        # Suspect ONLY when all three fire together — see the docstring.
        "suspect": all(flags.values()),
    }
    meta["diagnosis"] = diagnosis
    from app.core.extension_rig import extension_metadata
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    try:
        _publish_sidecar(path, meta)
    except OSError as e:
        logger.warning("Model3D %s: diagnosis not stored: %s", path.name, e)
    return {"ok": True, "cached": False, "diagnosis": diagnosis}


@_serial_model
def retexture_model(character_name: str,
                    signature: Optional[str] = None) -> Dict[str, Any]:
    """Re-encodes a stored model's textures and updates its sidecar.

    Only meaningful for models that predate the automatic step. The gates live
    in ``app/blender/refine.py``; what happens here is the bookkeeping — the
    outcome and the fresh measurement go into the sidecar, so the panel shows
    what the file IS after the swap, not what it was.
    """
    path = (find_model3d(character_name, signature) if signature
            else find_model3d_serving(character_name)[0])
    if not path:
        return {"ok": False, "error": "no_model"}
    from app.blender import refine
    meta_path = path.with_suffix(".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) \
            if meta_path.exists() else {}
    except (OSError, ValueError):
        meta = {}
    if path.suffix.lower() != ".glb":
        return {"ok": False, "error": f"retexture handles GLB, not {path.suffix}"}
    res = refine.retexture(path, validator=_validator_for(meta.get("rig") or "", character_name))
    if not res.get("ok"):
        from app.blender.refine import unavailable_reason
        return {"ok": False,
                "error": unavailable_reason() or res.get("error") or "failed"}
    data = res.get("data") or {}
    meta["refined"] = {
        "retexture": bool(res.get("applied")),
        "reason": res.get("error", ""),
        "bytes_saved": data.get("bytes_saved", 0) if res.get("applied") else 0,
        "at": utc_now_iso(),
    }
    if res.get("applied"):
        _attach_measurement(meta, path)
    from app.core.extension_rig import extension_metadata
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    try:
        _publish_sidecar(path, meta)
    except OSError as e:
        logger.warning("Model3D %s: sidecar not written: %s", path.name, e)
    return {"ok": True, "applied": bool(res.get("applied")),
            "reason": res.get("error", ""),
            "bytes_saved": meta["refined"]["bytes_saved"],
            "size": path.stat().st_size}


@_serial_model
def build_lod(character_name: str, signature: Optional[str] = None, *,
              ratio: float = 0.25) -> Dict[str, Any]:
    """Builds the reduced (``low``) version of a stored mesh.

    The source is the model of the SERVED combination, the result lands under
    ``model3d/low/`` with the same file name. Rig and skin travel with it —
    Decimate interpolates the vertex weights onto the surviving vertices — so
    the joint count is unchanged and the shared animation clips still apply.

    Reduction changes the silhouette; that is its purpose. ``ratio`` is
    therefore the caller's decision, not a default that quietly ages.
    """
    path = (find_model3d(character_name, signature) if signature
            else find_model3d_serving(character_name)[0])
    if not path:
        return {"ok": False, "error": "no_model"}
    if path.suffix.lower() != ".glb":
        return {"ok": False, "error": f"LOD handles GLB, not {path.suffix}"}
    from app.blender import runner
    from app.blender.refine import unavailable_reason
    out_dir = tier_dir(character_name, LOW_TIER)
    try:
        # parents=False: a character deleted meanwhile must not come back as
        # a ghost directory through its LOD tier.
        out_dir.mkdir(exist_ok=True)
    except FileNotFoundError:
        return {"ok": False, "error": "no_model"}
    import tempfile
    with tempfile.TemporaryDirectory(prefix="av-lod-") as tmp:
        res = runner.run("lod", inputs={"model": path},
                         params={"ratios": [float(ratio)]}, out_dir=Path(tmp),
                         timeout_s=600)
        if not res.get("ok") or not res.get("outputs"):
            return {"ok": False,
                    "error": unavailable_reason() or res.get("error")
                    or "no stage produced"}
        stage = (res["data"].get("stages") or [{}])[0]
        blob = Path(next(iter(res["outputs"].values()))).read_bytes()
        # Same bar as everywhere: the reduced mesh must still validate as what
        # it is, or it does not get stored.
        meta_path = path.with_suffix(".json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) \
                if meta_path.exists() else {}
        except (OSError, ValueError):
            meta = {}
        verdict = _validator_for(meta.get("rig") or "", character_name)(blob)
        if not verdict.get("ok"):
            return {"ok": False,
                    "error": "reduced mesh failed validation: "
                             + "; ".join(verdict.get("errors") or [])}
        # Same fifth gate as refine.apply_script: the distance mesh must keep
        # the full mesh's joint frames, or the shared clips deform it.
        from app.core.model_validate import rig_frames_preserved
        frames = rig_frames_preserved(path.read_bytes(), blob)
        if not frames.get("ok"):
            return {"ok": False,
                    "error": "reduced mesh rewrote the rig frames: "
                             + "; ".join(frames.get("errors") or [])}
        low_metrics = {}
        # Built parts are not extension_bones groups; only captured groups are re-measured,
        # and only the enabled ones — a group switched off for this model was never built.
        from app.core.extension_rig import resolved_extension_groups
        measured_groups = [g for g in resolved_extension_groups(character_name, signature=path.stem,
                                                                mesh_variant=meta.get("mesh_variant") or "")
                           if g["enabled"] and g["op"] not in ("attached_part", "attached_part_bone", "inset_part")]
        if (meta.get("extension_rig") or {}).get("status") == "applied" and measured_groups:
            measured = runner.run("extension_bones", inputs={"model": next(iter(res["outputs"].values()))},
                                  params={"groups": measured_groups, "metrics_only": True})
            if not measured.get("ok") or (measured.get("data") or {}).get("status") != "applied":
                return {"ok": False, "error": measured.get("error") or
                        (measured.get("data") or {}).get("reason") or "Low tier metrics failed"}
            low_metrics = (measured.get("data") or {}).get("metrics") or {}
        target = out_dir / path.name
        try:
            _publish_model_bytes(target, blob)
        except FileNotFoundError:
            # Deleted during the Blender run (up to 600 s).
            return {"ok": False, "error": "no_model"}
    side = {
        "created_at": utc_now_iso(),
        "source": "lod",
        "format": "glb",
        "rig": meta.get("rig", ""),
        "tier": LOW_TIER,
        "source_file": path.name,
        "lod_ratio": float(ratio),
        "tris": stage.get("tris"),
        "tris_before": stage.get("tris_before"),
        "signature": path.stem,
        "character": character_name,
    }
    if meta.get("blender"):
        side["blender"] = dict(meta["blender"])
    from app.core.extension_rig import extension_metadata
    side["extension_rig"] = dict(meta.get("extension_rig") or extension_metadata(character_name, signature=path.stem))
    side["extension_rig"].pop("per_tier", None)
    side["extension_rig"]["inherited"] = True
    side["extension_rig"]["metrics"] = {
        group_id: {**((meta.get("extension_rig") or {}).get("metrics") or {}).get(group_id, {}), **values}
        for group_id, values in low_metrics.items()
    } if low_metrics else side["extension_rig"].get("metrics", {})
    _publish_sidecar(target, side)
    if meta.get("extension_rig"):
        meta["extension_rig"].setdefault("per_tier", {})[LOW_TIER] = side["extension_rig"]
    had_lod_error = "lod_error" in meta
    meta.pop("lod_error", None)
    if meta.get("extension_rig") or had_lod_error:
        _publish_sidecar(path, meta)
    logger.info("Model3D %s: LOD %s (%s -> %s tris, %d bytes)", character_name,
                target.name, stage.get("tris_before"), stage.get("tris"),
                target.stat().st_size)
    # A new low tier makes its garment assembly stale: rebuild it (after the
    # publication, when this runs inside a staged operation).
    from app.core import garment_assembly
    garment_assembly.schedule(character_name, path.stem)
    return {"ok": True, "tier": LOW_TIER, "ratio": float(ratio),
            "tris": stage.get("tris"), "tris_before": stage.get("tris_before"),
            "size": target.stat().st_size,
            "size_before": path.stat().st_size}


@_serial_model
def set_model3d_rig(character_name: str, rig: str, *,
                    signature: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Updates the rig of a captured outfit model; None if none."""
    path = find_model3d(character_name, signature)
    if not path:
        return None
    meta_path = path.with_suffix(".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    except (OSError, ValueError):
        meta = {}
    meta["rig"] = rig
    from app.core.extension_rig import extension_metadata
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    _publish_sidecar(path, meta)
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
    manifest = {"pieces": {str(k): str(v) for k, v in pieces.items() if v},
                "items": [str(i) for i in (items or []) if i],
                "mesh_variant": meta.get("mesh_variant", "")}
    # Own-mesh pieces (base-body pipeline, plan 2026-11-09-base-body-phase5):
    # the token re-signs the entry (``model_refs.mesh_items_token``) and the
    # intended/effective mesh set decides which garments the assembly grafts
    # onto THIS model (``garment_assembly._wanted``). Only when recorded.
    if meta.get("mesh_token"):
        manifest["mesh_token"] = str(meta["mesh_token"])
    if isinstance(meta.get("mesh_items"), dict):
        manifest["mesh_items"] = meta["mesh_items"]
    return manifest


def _store_unrigged_model(character_name: str, signature: str, result: Dict[str, Any],
                          rig: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Store a validated source as the current static model in the publication stage."""
    from app.core.mesh_source import source_basecolor, validate_source
    source = Path(result["path"])
    blob = source.read_bytes()
    check = validate_source(blob)
    if not check.get("ok"):
        return {"ok": False, "error": "; ".join(check.get("errors") or ["invalid unrigged source"]),
                "errors": check.get("errors", []), "warnings": check.get("warnings", [])}
    # The face cleanup (app/core/face_cleanup.py) runs HERE, on the validated mesher result, before it becomes
    # the retained source: the face retexture is frozen from that file, the rig reads it and every re-rig
    # starts over from it. Humanoid meshes only; a failure keeps the mesher's bytes and is recorded.
    face_cleanup: Optional[Dict[str, Any]] = None
    if rig == "mixamo":
        from app.core import face_cleanup as _face_cleanup
        if not _face_cleanup.enabled_for(character_name):
            face_cleanup = {"status": "skipped", "reason": "disabled for this character", "at": utc_now_iso()}
        else:
            try:
                blob, face_cleanup = _face_cleanup.clean_face(blob)
                if face_cleanup.get("status") == "applied":
                    verdict = validate_source(blob)
                    if not verdict.get("ok"):
                        raise ValueError("cleaned mesh fails validation: " + "; ".join(verdict.get("errors") or []))
                logger.info("Face cleanup %s/%s: %s", character_name, signature, _face_cleanup.summary(face_cleanup))
            except Exception as exc:  # noqa: BLE001 — never block a generation on the cleanup
                blob = source.read_bytes()
                face_cleanup = {"status": "failed", "error": str(exc), "at": utc_now_iso()}
                logger.warning("Face cleanup %s/%s failed, keeping the mesher's file: %s", character_name, signature, exc)
    texture = None
    rig_error = ""
    if rig == "generic":
        try:
            texture = source_basecolor(source, result.get("texture_path") or "")
        except ValueError as exc:
            # The mesh remains usable statically even if its color maps cannot
            # be represented by the generic rig's single external PNG.
            rig_error = str(exc)
    directory = get_model3d_dir(character_name)
    path = directory / f"{signature}.glb"
    _purge_combination(directory, signature, keep_model=path)
    retained = directory / "unrigged" / path.name
    retained.parent.mkdir(parents=True, exist_ok=True)
    _publish_model_bytes(retained, blob)
    if texture is not None:
        _publish_model_bytes(retained.with_suffix(".png"), texture)
    source_meta = {
        **manifest, "created_at": utc_now_iso(), "rig": "none", "signature": signature,
        "mesh_backend": result.get("backend", ""),
        "mesh_route_meta": {k: result[k] for k in ROUTE_META_KEYS if k in result},
        "source_filename": result.get("filename", ""),
    }
    if result.get("single_view"):
        source_meta["single_view"] = True
    if result.get("job_id"):
        source_meta["job_id"] = result["job_id"]
    if face_cleanup is not None:
        source_meta["face_cleanup"] = face_cleanup
    _publish_sidecar(retained, source_meta)
    _publish_model_bytes(path, blob)
    meta = {**source_meta, "source": "generated", "character": character_name,
            "backend": result.get("backend", ""), "format": "glb", "has_texture": False}
    if rig_error:
        meta["rig_error"] = rig_error
    _publish_sidecar(path, meta)
    return {"ok": True, "path": str(path), "meta": meta, "warnings": check.get("warnings", [])}


# ── Hub operations (app/core/hub_ops.py) ──────────────────────────────────
# A generation is a chain of hub jobs (mesh → rig, upscale → face → rig) that
# outlives a restart of Anima: its record holds the FROZEN inputs and the
# stage results, its directory the input files and every intermediate. The
# public entries below are NOT staged themselves: they look up an open record
# of the current queue task BEFORE the ``_serial_model`` wrapper (which would
# otherwise stage the worn signature) and settle the record only AFTER the
# wrapper published — the moment the result really is public. Normal run and
# resume execute the same staged function and the same stages.

_OP_MESH = "character_mesh"
_OP_RERIG = "character_rerig"
_OP_FACE = "face_retexture"


def _op_subject(character_name: str, signature: str) -> str:
    """One model operation per character + combination (the target key)."""
    return f"model3d:{character_name}:{signature}"


def _op_match(character_name: str, signature: Optional[str], *, base: Optional[bool] = None):
    """``base`` (mesh records only): True/False match only base-body /
    outfit records — an outfit run never resumes a base one, nor back."""
    def match(inputs: Dict[str, Any]) -> bool:
        return (inputs.get("character") == character_name
                and (signature is None or inputs.get("signature") == signature)
                and (base is None or bool(inputs.get("base")) == base))
    return match


def _op_rel(op, result: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """A service result as JSON for the record: file paths made relative to
    the operation directory, the rest copied (routing meta included)."""
    out: Dict[str, Any] = {}
    for key, value in result.items():
        if key in keys and value:
            out[key] = op.rel(value)
        elif isinstance(value, (str, int, float, bool, dict, list)) or value is None:
            out[key] = value
    return out


def _op_abs(op, result: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    out = dict(result)
    for key in keys:
        if out.get(key):
            out[key] = str(op.abs(out[key]))
    return out


def _resume_entry(op, staged_call, character_name: str):
    """Run a record of the current task again (handler re-run after a
    restart). A tombstone reports its stored verdict instead (spec D8)."""
    from app.core import hub_ops
    if op.status == hub_ops.FAILED:
        hub_ops.raise_failed(op)
    return hub_ops.resume(op, staged_call, agent_name=character_name)


def _ensure_covered_variant(character_name: str) -> None:
    """Before an outfit model on the base body is built: a base whose
    exposed-only extension groups apply gets its covered variant
    (``_auto_covered_variant``) when it has none built from its current
    prerig source — through ``rebuild_extension_rig`` on the base signature,
    which publishes it with the base (an outfit run is staged on its own
    signature and cannot write the base's files). Best effort: the outfit
    falls back to the full base with a warning."""
    if character_name in getattr(_staging, "directories", {}):
        return
    try:
        from app.core import base_body
        from app.core.extension_rig import exposed_only_slots, rig_groups_for
        if not exposed_only_slots() or not base_body.is_base_pipeline(character_name):
            return
        bsig = base_body.base_signature(character_name)
        directory = get_model3d_dir(character_name)
        rigged, prerig = directory / f"{bsig}.glb", directory / "prerig" / f"{bsig}.glb"
        covered = directory / COVERED_DIR / f"{bsig}.glb"
        if not rigged.is_file() or not prerig.is_file():
            return
        if covered.is_file() and _read_sidecar(covered).get("source_sha256") == base_body.file_sha256(prerig):
            return
        if not any(g.get("exposed_only") for g in rig_groups_for(character_name, mesh_variant="")):
            return
        rebuild_extension_rig(character_name, bsig)
    except Exception as exc:  # noqa: BLE001 — the outfit build reports the fallback
        logger.warning("Model3D %s: covered variant not prepared: %s", character_name, exc)


def generate_for_current_outfit(character_name: str, *, force: bool = False,
                                backend_glob: str = "",
                                prefer_cheapest: bool = False,
                                signature: Optional[str] = None,
                                face_num: Any = None,
                                texture_size: Any = None,
                                base: bool = False) -> Dict[str, Any]:
    """Generates the mesh for the currently worn outfit — or a given
    combination — from its T-pose render.

    ``base=True`` (with ``signature`` = the base signature,
    ``base_body.generate_base_model``) builds the base body instead: every
    stored base view goes in whatever the view toggles say, the anatomy-part
    extension batches and the distance tier are skipped, the sidecar records
    ``"base": true``. The flag is frozen into the record, so a resume behaves
    the same.

    A character on the base-body pipeline (``base_body.is_base_pipeline``)
    gets its outfit model from ``base_body.build_outfit_model`` instead of
    the img2mesh stages: the rigged base body retextured with the outfit's
    dressed images (backend arguments do not apply).

    Backend: ``backend_glob`` (explicit) → the mesh occasion's chain of the
    image routing (``mesh_occasion_for_rig`` of the character's rig);
    ``prefer_cheapest`` = cheapest available unrigged img2mesh (auto hook).
    Cached per combination — an existing mesh is kept unless ``force``.
    ``signature`` None = the worn combination; set = that combination drives
    the cache check, the T-pose input and the target file (the outfit batch
    pre-warms combinations without dressing the character).
    Blocking (minutes); call from a worker thread.

    Inside a queue handler that left a mesh operation open before a restart,
    this RESUMES it — with its frozen signature, never the one worn now — and
    neither the cache check nor the T-pose lookup run again.
    """
    from app.core import hub_ops
    if base and not signature:
        raise ValueError("A base-body model needs its base signature")
    op = hub_ops.find_open(_OP_MESH, _op_match(character_name, signature, base=base))
    if op is None and not base:
        _ensure_covered_variant(character_name)
    if op is not None:
        return _resume_entry(op, lambda: _generate_for_current_outfit(
            character_name, signature=op.inputs["signature"], _op_ctx={"op": op}),
            character_name)
    return hub_ops.run_new(lambda ctx: _generate_for_current_outfit(
        character_name, force=force, backend_glob=backend_glob,
        prefer_cheapest=prefer_cheapest, signature=signature, face_num=face_num,
        texture_size=texture_size, base=base, _op_ctx=ctx))


@_serial_model
def _generate_for_current_outfit(character_name: str, *, force: bool = False,
                                 backend_glob: str = "",
                                 prefer_cheapest: bool = False,
                                 signature: Optional[str] = None,
                                 face_num: Any = None,
                                 texture_size: Any = None,
                                 base: bool = False,
                                 _op_ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The staged half of ``generate_for_current_outfit``: preprocessing and
    the record (fresh run), then the stages — or the stages alone when
    ``_op_ctx`` already carries the record (resume; ``base`` then comes from
    the record's inputs, never from this argument)."""
    from app.core import hub_ops
    from app.imagegen.service import get_image_service
    from app.core.task_queue import get_task_queue

    op = (_op_ctx or {}).get("op")
    task_id = ""
    error = ""
    try:
        if op is None:
            rig = required_rig(character_name)

            from app.core.model_refs import is_state_fork
            if is_state_fork(signature) or "-p" in (signature or ""):
                return {"ok": False, "error": "state_fork_retired"}
            if signature is None:
                _, _, signature = current_outfit_state(character_name)
            if not force:
                cached = find_model3d(character_name, signature)
                if cached:
                    logger.info("Model3D %s: combination %s already generated (%s)",
                                character_name, signature, cached.name)
                    return {"ok": True, "cached": True, "path": str(cached)}

            if not base:
                from app.core.base_body import build_outfit_model, is_base_pipeline
                if is_base_pipeline(character_name):
                    # Base-body pipeline: the outfit model is the rigged base
                    # body with the outfit painted on (CPU worker) — no
                    # img2mesh, no rig job, no hub record.
                    if not get_model3d_dir(character_name).is_dir():
                        return {"ok": False, "error": "character_gone"}
                    return build_outfit_model(character_name, signature, force=force)

            from app.imagegen.routing import character_spec
            if (not backend_glob and prefer_cheapest
                    and not character_spec(mesh_occasion_for_rig(rig), character_name)):
                # The auto-mesh hook keeps its rule (user decision 2026-07-18): the
                # cheapest AVAILABLE unrigged img2mesh backend — explicit, no
                # chain. Every other call without a glob is routed, and so is
                # the hook for a character with its own mesh match.
                cheapest = get_image_service().list_mesh_backends()
                if not cheapest:
                    return {"ok": False, "error": "no img2mesh backend available"}
                backend_glob = cheapest[0].name

            src = find_ref_image(character_name, "tpose", signature)
            if not src:
                logger.warning("Model3D %s: no T-pose image for combination %s",
                               character_name, signature)
                return {"ok": False, "error": "no_tpose_input"}

            # Optional extra views of the SAME outfit combination (per character, off
            # by default): a multi-view mesh backend reconstructs the back and the
            # body depth from them instead of guessing. Only what actually exists is
            # passed on — a view that failed to render must not block the mesh.
            from app.core.model_refs import enabled_tpose_views, is_humanoid
            view_images = {}
            if base:
                # The base body always sends every view it has rendered,
                # independent of the outfit view toggles.
                from app.core.base_body import BASE_VIEWS
                wanted_views = [v for v in BASE_VIEWS if v != "front"]
            else:
                wanted_views = enabled_tpose_views(character_name)
            for _view in wanted_views:
                if _view == "face":
                    continue  # Close-up texture reference, never reconstruction input.
                _vp = find_ref_image(character_name, f"tpose_{_view}", signature)
                if _vp:
                    view_images[_view] = str(_vp)
            if view_images:
                logger.info("Model3D %s: extra views for %s: %s",
                            character_name, signature, ", ".join(sorted(view_images)))

            out_dir = get_model3d_dir(character_name)
            if not out_dir.is_dir():
                # The character was deleted while this job waited in the queue —
                # no GPU run for a result nobody can store.
                return {"ok": False, "error": "character_gone"}
            try:
                task_id = get_task_queue().track_start(
                    "model3d_generation",
                    f"{'Base-body 3D model' if base else '3D model'}: {character_name}",
                    agent_name=character_name, start_running=True)
            except Exception:
                task_id = ""
            source_bytes = src.read_bytes()
            view_bytes = {v: Path(p).read_bytes() for v, p in view_images.items()}
            # The record freezes what this run is made FROM: the signature, the
            # backend pick, the T-pose bytes (copied — a re-render while the
            # job runs must not change the input) and the manifest.
            # A target in flight raises HubOpBusy (improvements read it as
            # busy, the trigger threads log it).
            face_inputs = {"face_before_rig": False}
            face_photo = None
            if rig == "mixamo" and get_model3d_options(character_name)["face_before_rig"]:
                from app.core import face_retexture
                ready = face_retexture.runnable(character_name)
                face_snapshot = {}
                face_choice = face_retexture.reference_info(character_name, signature, {
                    "source_image": src.name, "source_image_sha256": hashlib.sha256(source_bytes).hexdigest()},
                    _snapshot=face_snapshot)
                face_reference = face_choice["reference"]
                from app.core.face_photo_adjust import validated_params as photo_params, PROBLEM
                photo = photo_params(get_model3d_options(character_name)['face_photo'])
                photo_mode = 'hub' if face_retexture.photo_controls_supported(character_name) else 'local'
                photo_reason = ''
                if photo_mode == 'local' and face_reference == 'front' and photo['balance']:
                    photo['balance'] = 0.
                    photo_reason = PROBLEM
                face_inputs = {"reference": face_reference, "face_before_rig": True, "controls": face_retexture.validated_params(None),
                               "face_backend_glob": "", "upscale": face_retexture.use_upscale(face_reference, None), "upscale_backend_glob": "",
                               "source_kind": "facefix", "photo": photo, "photo_mode": photo_mode, "photo_reason": photo_reason}
                if not ready["ok"]:
                    face_inputs["face_retexture"] = {"status": "skipped", "reason": "; ".join(
                        problem["message"] for problem in ready["problems"])}
                else:
                    try:
                        photo_raw = face_snapshot['rgba'] if face_reference == 'face' else source_bytes
                        try:
                            face_photo = (face_snapshot['image'] if face_reference == 'face' and (photo_mode == 'hub' or (photo['balance'] == 0 and photo['brightness'] == 1))
                                          else face_retexture.flatten_photo(photo_raw) if photo_mode == 'hub'
                                          else face_retexture.flatten_photo(photo_raw, photo))
                        except ValueError as exc:
                            # A face view without a cut-out (background removal
                            # fell back) cannot be balanced: brightness only.
                            if str(exc) != PROBLEM or not photo['balance']:
                                raise
                            photo['balance'] = 0.
                            face_inputs["photo_reason"] = PROBLEM
                            face_photo = face_retexture.flatten_photo(photo_raw, photo)
                    except Exception as exc:
                        face_inputs["face_retexture"] = {"status": "failed", "error": str(exc), "at": utc_now_iso()}
            op = hub_ops.create(_OP_MESH, _op_subject(character_name, signature), {
                "character": character_name, "signature": signature, "rig": rig,
                "backend_glob": backend_glob, "face_num": face_num,
                "texture_size": texture_size, "occasion": mesh_occasion_for_rig(rig),
                "view_body": "humanoid" if is_humanoid(character_name) else "animal",
                "rig_options": _character_rig_options(character_name),
                "source_image": src.name,
                "source_image_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "view_images": {v: Path(p).name for v, p in view_images.items()},
                "view_images_sha256": {v: hashlib.sha256(blob).hexdigest() for v, blob in view_bytes.items()},
                # A base body stands for no outfit: no piece manifest.
                "manifest": {} if base else _ref_manifest(src),
                **({"base": True} if base else {}),
                **face_inputs,
            }, label=f"{'Base-body 3D model' if base else '3D model'}: {character_name}", track_id=task_id)
            if _op_ctx is not None:
                _op_ctx["op"] = op
            op.path("inputs", src.name).write_bytes(source_bytes)
            if face_photo is not None:
                op.path("inputs", "photo.png").write_bytes(face_photo)
            views = {}
            for v, p in view_images.items():
                frozen = op.path("inputs", "views", f"{v}{Path(p).suffix}")
                frozen.write_bytes(view_bytes[v])
                views[v] = op.rel(frozen)
            op.update_state(lambda st: st.update(view_files=views))
            op.reload()
        elif not get_model3d_dir(character_name).is_dir():
            error = "character_gone"
            return {"ok": False, "error": error}
        result = _character_mesh_stages(character_name, op)
        if not result.get("ok"):
            error = str(result.get("error") or "generation failed")
        return result
    except Exception as exc:
        error = error or str(exc)
        raise
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def _character_mesh_stages(character_name: str, op) -> Dict[str, Any]:
    """Stages ``mesh`` → ``checkpoint`` → ``rig`` → publish of one record —
    shared by the fresh run and the resume. Reads only the record (frozen
    inputs, earlier stage results), never the world's current state."""
    from app.imagegen.service import get_image_service
    from app.core.model_validate import validate_glb, validate_fbx
    inputs = op.inputs
    signature, rig = inputs["signature"], inputs["rig"]
    base = bool(inputs.get("base"))
    out_dir = get_model3d_dir(character_name)

    if not op.done("mesh"):
        views = {v: str(op.abs(rel)) for v, rel in (op.state.get("view_files") or {}).items()}
        res = get_image_service().generate_mesh(
            source_image_path=str(op.abs(f"inputs/{inputs['source_image']}")),
            output_path=str(op.path("mesh", f"{signature}.glb")),
            backend_glob=inputs.get("backend_glob") or "",
            character_name=character_name,
            mesh_name=character_name,
            face_num=inputs.get("face_num"),
            texture_size=inputs.get("texture_size"),
            # Characters are never metal; predicted alpha on an OPAQUE material
            # only blackens texels in premultiplying viewers.
            material="dielectric", alpha="opaque",
            view_images=views or None,
            view_body=inputs["view_body"],
            occasion=inputs["occasion"],
            hub_stage=op.stage("mesh"))
        if not res.get("ok"):
            error = str(res.get("error") or "generation failed")
            logger.error("Model3D %s failed: %s", character_name, error)
            return {"ok": False, "error": error}
        res.pop("stages", None)
        op.complete("mesh", _op_rel(op, res, "path", "texture_path"))
    mesh_res = _op_abs(op, op.result("mesh"), "path", "texture_path")

    publication = getattr(_staging, "source_publications", {}).get(character_name)
    if not op.done("checkpoint"):
        stored = _store_unrigged_model(character_name, signature, mesh_res, rig,
                                       {"source_image": inputs["source_image"],
                                        "view_images": dict(inputs.get("view_images") or {}),
                                        "source_image_sha256": inputs["source_image_sha256"],
                                        **({"view_images_sha256": dict(inputs["view_images_sha256"])}
                                           if "view_images_sha256" in inputs else {}),
                                        **(inputs.get("manifest") or {}),
                                        **({"base": True} if base else {})})
        if not stored.get("ok"):
            return {"ok": False, "error": stored["error"]}
        _checkpoint_mesh(character_name, signature)
        # The rig input is frozen with the record: the published retained
        # source may be replaced (an upload) while the rig job runs.
        retained = out_dir / "unrigged" / f"{signature}.glb"
        op.freeze_file(retained, "source", f"{signature}.glb")
        if inputs.get("face_before_rig"):
            op.freeze_file(retained, "inputs", "unrigged", f"{signature}.glb")
            op.freeze_file(retained.with_suffix(".json"), "inputs", "unrigged", f"{signature}.json")
        if retained.with_suffix(".png").is_file():
            op.freeze_file(retained.with_suffix(".png"), "source", f"{signature}.png")
        op.complete("checkpoint", {"rig_error": stored["meta"].get("rig_error", "")})
    elif publication is not None:
        # Published by the previous runtime: a rig failure now still marks
        # the static mesh with ``rig_error`` (the wrapper reads this flag).
        publication["mesh_published"] = True
    rig_error = op.result("checkpoint").get("rig_error")
    if rig_error:
        return {"ok": False, "error": rig_error}

    face_status = inputs.get("face_retexture")
    if inputs.get("face_before_rig"):
        if op.done("face_before_rig"):
            face_status = op.result("face_before_rig")["meta"]
        if face_status is None or face_status["status"] == "applied":
            from app.imagegen.base import GenerationCancelled, GpuTaskCancelled, MediaGenerationDisabled, HubJobLost
            try:
                corrected = _face_source_stages(character_name, op)
                if not corrected.get("ok"):
                    raise ValueError(corrected.get("error") or "Face retexture failed")
                face_status = op.result("bake")["face_meta"]
            except (GenerationCancelled, GpuTaskCancelled, MediaGenerationDisabled, HubJobLost):
                raise
            except Exception as exc:
                face_status = {"status": "failed", "error": str(exc), "at": utc_now_iso()}
                logger.warning("Face correction before rig failed for %s: %s", character_name, exc)
        op.complete("face_before_rig", {"meta": face_status})
        if face_status["status"] == "applied":
            for suffix in (".glb", ".json"):
                frozen = op.abs(f"inputs/unrigged/{signature}{suffix}")
                _publish_model_bytes(out_dir / "unrigged" / f"{signature}{suffix}", frozen.read_bytes())
            result = _rig_from_source(character_name, signature, corrected["source"],
                                      replacement_mask=corrected["mask"], op=op)
            if result.get("ok"):
                result["cached"] = False
            return result
        # A partial bake must never become the fallback rig input.
        for suffix in (".glb", ".json", ".png"):
            (out_dir / "facefix" / f"{signature}{suffix}").unlink(missing_ok=True)

    source = (op.abs(f"inputs/unrigged/{signature}.glb") if inputs.get("face_before_rig")
              else op.abs(f"source/{signature}.glb"))
    if not op.done("rig"):
        from app.imagegen.base import BackendNotApplicableError
        # Sequential caller-thread submission: the mesh slot has been released.
        try:
            res = get_image_service().generate_rig(
                mesh_path=str(source), output_path=str(op.path("rig", f"{signature}-rig.glb")),
                rig=rig, character_name=character_name,
                basecolor_path=str(source.with_suffix(".png")) if rig == "generic" else "",
                rig_options=inputs["rig_options"],
                hub_stage=op.stage("rig"))
        except BackendNotApplicableError as exc:
            return {"ok": False, "error": str(exc), "reason": exc.reason}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "rig generation failed")}
        texture_blob = Path(res["texture_path"]).read_bytes() if res.get("texture_path") else None
        check = (validate_glb(Path(res["path"]).read_bytes()) if rig == "mixamo"
                 else validate_fbx(Path(res["path"]).read_bytes(), texture_blob,
                                   _rig_result_validation_meta(res)))
        if not check.get("ok"):
            return {"ok": False, "error": "; ".join(check.get("errors") or ["invalid rigged result"])}
        warnings = list(check.get("warnings", []))
        for warning in warnings:
            logger.warning("Model3D %s: %s", character_name, warning)
        res.pop("stages", None)
        res["validation_warnings"] = warnings
        op.complete("rig", _op_rel(op, res, "path", "texture_path"))
    res = _op_abs(op, op.result("rig"), "path", "texture_path")

    delivered = Path(res["path"])
    blob = delivered.read_bytes()
    texture_blob = Path(res["texture_path"]).read_bytes() if res.get("texture_path") else None
    texture_suffix = Path(res["texture_path"]).suffix if res.get("texture_path") else ".png"
    path = out_dir / f"{signature}{delivered.suffix.lower()}"
    _purge_combination(out_dir, signature, keep_model=path, preserve_unrigged=True)
    stage_meta = {**({"single_view": True} if mesh_res.get("single_view") else {}),
                  "mesh_backend": mesh_res.get("backend", ""),
                  "rig_backend": res.get("backend", ""),
                  **_rig_result_validation_meta(res),
                  "mesh_route_meta": {k: mesh_res[k] for k in ROUTE_META_KEYS if k in mesh_res},
                  "rig_route_meta": {k: res[k] for k in ROUTE_META_KEYS if k in res}}
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    _publish_model_bytes(out_dir / "raw" / path.name, blob)
    _publish_model_bytes(path, blob)
    if texture_blob is not None:
        _publish_model_bytes(path.with_suffix(texture_suffix), texture_blob)
        _publish_model_bytes((out_dir / "raw" / path.name).with_suffix(texture_suffix), texture_blob)
    meta = {
        "created_at": utc_now_iso(),
        "source": "generated",
        **stage_meta,
        "backend": res.get("backend", ""),
        "format": res.get("format", path.suffix.lstrip(".").lower()),
        "rig": res.get("rig", rig),
        "has_texture": bool(res.get("texture_path")),
        "source_filename": res.get("filename", ""),
        "source_image": inputs["source_image"],
        "signature": signature,
        "character": character_name,
    }
    for _rk in ROUTE_META_KEYS:
        if res.get(_rk):
            meta[_rk] = res[_rk]
    if inputs.get("view_images"):
        # Which extra views went into this mesh — same shape as
        # "source_image": file names, not absolute paths.
        meta["view_images"] = dict(inputs["view_images"])
    for key in ("source_image_sha256", "view_images_sha256"):
        if key in inputs:
            meta[key] = inputs[key]
    # Manifest (outfit_cache_gc): WHICH pieces this signature stands for.
    # The md5 cannot be read back, so without this a cache entry can only
    # be judged by "could it still be produced" — with it, exactly. The
    # T-pose render this mesh comes from already recorded it, so the
    # source of truth is copied rather than derived a second time (frozen
    # with the record when the run started).
    meta.update(inputs.get("manifest") or {})
    if base:
        meta["base"] = True
    if face_status is not None:
        meta["face_retexture"] = face_status
    face_cleanup = _read_sidecar(out_dir / "unrigged" / f"{signature}.glb").get("face_cleanup")
    if face_cleanup:
        meta["face_cleanup"] = face_cleanup
    _auto_retexture(character_name, path, meta)
    _auto_normalize(character_name, path, meta)
    # Reads meta["base"]: a base body skips the anatomy-part batches.
    _auto_extension_rig(character_name, path, meta)
    # AFTER the re-encode and the normalisation: the numbers have to
    # describe the file that is actually served, not the one the backend
    # handed over.
    _attach_measurement(meta, path)
    # And the distance mesh right away — waiting for someone to ask means
    # the first viewer at range gets the full mesh for nothing, and the
    # build costs under a second against the minutes this generation just
    # took.
    from app.core.extension_rig import extension_metadata
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    _publish_sidecar(path, meta)
    if not base:
        request_lod(character_name, path)
    logger.info("Model3D %s: %s (%d bytes, combination %s)", character_name,
                path.name, path.stat().st_size, signature)
    return {"ok": True, "cached": False, "path": str(path),
            "filename": path.name, "warnings": res.get("validation_warnings", [])}


def _restore_frozen_source(op, out_dir: Path, signature: str) -> Path:
    """Write the record's frozen rig source back into the stage at the place
    ``_rig_from_source`` expects it (``facefix/`` or ``unrigged/``), with its
    sidecar and texture — so a resumed rig reads the same metadata and runs
    the same face-preservation check as the first run."""
    kind = op.inputs.get("source_kind") or "unrigged"
    target = out_dir / kind / f"{signature}.glb"
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".glb", ".json", ".png"):
        frozen = op.abs(f"source/{signature}{suffix}")
        if frozen.is_file() and (not target.with_suffix(suffix).is_file()
                                 or target.with_suffix(suffix).read_bytes() != frozen.read_bytes()):
            _publish_model_bytes(target.with_suffix(suffix), frozen.read_bytes())
    return target


def rerig_model(character_name: str, signature: Optional[str] = None, *,
                backend_glob: str = "", track_id: str = "") -> Dict[str, Any]:
    """Rebuild from the corrected source when present, otherwise the original.

    ``track_id``: the caller's display row (the trigger's), recorded so a
    resume after a restart can say which row took over."""
    from app.core import hub_ops
    op = hub_ops.find_open(_OP_RERIG, _op_match(character_name, signature))
    if op is not None:
        return _resume_entry(op, lambda: _rerig_model(
            character_name, op.inputs["signature"], _op_ctx={"op": op}), character_name)
    return hub_ops.run_new(lambda ctx: _rerig_model(
        character_name, signature, backend_glob=backend_glob, track_id=track_id, _op_ctx=ctx))


@_serial_model
def _rerig_model(character_name: str, signature: Optional[str] = None, *,
                 backend_glob: str = "", track_id: str = "", _revert_face: bool = False,
                 _op_ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.core import hub_ops
    directory = get_model3d_dir(character_name)
    op = (_op_ctx or {}).get("op")
    if op is None:
        source = directory / ("unrigged" if _revert_face else "facefix") / f"{signature}.glb"
        if not source.is_file():
            source = directory / "unrigged" / f"{signature}.glb"
        if not source.is_file():
            return {"ok": False, "error": "No retained unrigged mesh source. Generate a new model to enable re-rigging."}
        op = hub_ops.create(_OP_RERIG, _op_subject(character_name, signature), {
            "character": character_name, "signature": signature,
            "rig": required_rig(character_name),
            "rig_options": _character_rig_options(character_name),
            "backend_glob": backend_glob, "source_kind": source.parent.name,
            "revert_face": _revert_face,
        }, label=f"Re-rig: {character_name}", track_id=track_id)
        if _op_ctx is not None:
            _op_ctx["op"] = op
        for suffix in (".glb", ".json", ".png"):
            if source.with_suffix(suffix).is_file():
                op.freeze_file(source.with_suffix(suffix), "source", f"{signature}{suffix}")
    if op.inputs.get("revert_face"):
        # Reapply on resume: the previous runtime's staging deletions vanished.
        for suffix in (".glb", ".json", ".png"):
            (directory / "facefix" / f"{op.inputs['signature']}{suffix}").unlink(missing_ok=True)
    source = _restore_frozen_source(op, directory, op.inputs["signature"])
    return _rig_from_source(character_name, op.inputs["signature"], source,
                            rig_backend_glob=op.inputs.get("backend_glob") or "", op=op)


def _character_rig_options(character_name: str) -> dict:
    from app.models.character import get_character_profile
    value = (get_character_profile(character_name) or {}).get("tail_motion", "")
    if value not in ("", "full", "calm", "still"):
        raise ValueError(f"unknown tail_motion: {value}")
    return {"tail_motion": value}


def _rig_result_validation_meta(result: dict) -> dict:
    """Present backend metrics and declared clips to the FBX validator."""
    metrics = result.get("meta") or {}
    meta = {"rig_metrics": metrics}
    if "clips" in result or "clips" in metrics:
        meta["clips"] = {take: {"loop": clip["loop"]}
                         for take, clip in (result.get("clips") or metrics.get("clips") or {}).items()}
    return meta


def _rig_from_source(character_name: str, signature: str, source: Path, *,
                     rig_backend_glob: str = "", replacement_mask=None,
                     op=None) -> Dict[str, Any]:
    """Rig the retained source only; publish the entire chain on success.

    ``op``: the hub operation this rig belongs to — its ``rig`` stage is
    submitted (or, after a restart, collected) through it and the validated
    rig result is kept in the record's directory before anything is
    published."""
    from app.imagegen.service import get_image_service
    from app.core.model_validate import validate_glb, validate_fbx
    path = find_model3d(character_name, signature)
    out_dir = get_model3d_dir(character_name)
    if not source.is_file():
        return {"ok": False, "error": "No retained unrigged mesh source. Generate a new model to enable re-rigging."}
    # The rig kind is frozen with the operation: a change of the character's
    # rig while a job was out must not fail the collected result.
    rig = (op.inputs.get("rig") if op is not None else None) or required_rig(character_name)
    previous_meta = _read_sidecar(path) if path else {}
    face_meta = _read_sidecar(source).get("face_retexture") if source.parent.name == "facefix" else None
    low = tier_variant(path, LOW_TIER) if path else None
    low_meta = _read_sidecar(low) if low else {}
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".rerig-", dir=out_dir) as tmp:
        from app.imagegen.base import BackendNotApplicableError
        if op is not None and op.done("rig"):
            res = _op_abs(op, op.result("rig"), "path", "texture_path")
        else:
            target = op.path("rig", f"{signature}.glb") if op is not None else Path(tmp) / f"{signature}.glb"
            rig_options = (op.inputs["rig_options"] if op is not None
                           else _character_rig_options(character_name))
            try:
                res = get_image_service().generate_rig(
                    mesh_path=str(source), output_path=str(target),
                    rig=rig, character_name=character_name, backend_glob=rig_backend_glob,
                    basecolor_path=str(source.with_suffix(".png")) if rig == "generic" else "",
                    rig_options=rig_options,
                    hub_stage=op.stage("rig") if op is not None else None)
            except BackendNotApplicableError as exc:
                return {"ok": False, "error": str(exc), "reason": exc.reason}
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error") or "Rig generation failed"}
        delivered = Path(res["path"])
        blob = delivered.read_bytes()
        texture = Path(res["texture_path"]).read_bytes() if res.get("texture_path") else None
        check = validate_glb(blob) if rig == "mixamo" else validate_fbx(blob, texture, _rig_result_validation_meta(res))
        if not check.get("ok"):
            return {"ok": False, "error": "; ".join(check.get("errors") or ["Invalid rigged result"])}
        for warning in check.get("warnings", []):
            logger.warning("Model3D %s: %s", character_name, warning)
        if op is not None and not op.done("rig"):
            res.pop("stages", None)
            op.complete("rig", _op_rel(op, res, "path", "texture_path"))
        face_texture_lost = False
        if face_meta or (out_dir / "facefix" / f"{signature}.glb").is_file():
            from app.core.face_retexture import face_texture_preserved
            original_source = out_dir / "unrigged" / f"{signature}.glb"
            face_texture_lost = not face_texture_preserved(
                source.read_bytes(), blob, replacement_mask=replacement_mask,
                bake_meta=(face_meta or {}).get("baked"),
                original_glb=original_source.read_bytes() if replacement_mask is None and original_source.is_file() else None)
        path = out_dir / f"{signature}{delivered.suffix.lower()}"
        _purge_combination(out_dir, signature, keep_model=path, preserve_sources=True)
        _publish_model_bytes(path, blob)
        (out_dir / "raw").mkdir(exist_ok=True)
        _publish_model_bytes(out_dir / "raw" / path.name, blob)
        if texture is not None:
            _publish_model_bytes(path.with_suffix(".png"), texture)
            _publish_model_bytes((out_dir / "raw" / path.name).with_suffix(".png"), texture)
        source_meta = _read_sidecar(out_dir / "unrigged" / f"{signature}.glb")
        meta = {k: v for k, v in source_meta.items() if k in (
            "mesh_backend", "mesh_route_meta", "source_image", "source_image_sha256",
            "view_images", "view_images_sha256", "pieces", "items", "mesh_variant", "job_id", "single_view",
            "base", "face_cleanup")}
        meta.update(created_at=utc_now_iso(), source="generated", signature=signature,
                    character=character_name, rig=rig, format=path.suffix.lstrip("."),
                    backend=res.get("backend", ""), rig_backend=res.get("backend", ""),
                    **_rig_result_validation_meta(res),
                    rig_route_meta={k: res[k] for k in ROUTE_META_KEYS if k in res},
                    has_texture=texture is not None,
                    source_filename=res.get("filename", ""))
        if (out_dir / "facefix" / f"{signature}.glb").is_file():
            meta["face_retexture"] = {**(face_meta or previous_meta.get("face_retexture", {})),
                                      "face_texture_lost": face_texture_lost}
        for key in ROUTE_META_KEYS:
            if key in res:
                meta[key] = res[key]
        try:
            _auto_retexture(character_name, path, meta)
        except Exception as exc:
            _publish_model_bytes(path, blob)
            meta["refined"] = {"retexture": False, "reason": str(exc),
                               "bytes_saved": 0, "at": utc_now_iso()}
        generation_face = op is not None and op.inputs.get("face_before_rig")
        before_normalize = path.read_bytes()
        try:
            _auto_normalize(character_name, path, meta, fail_on_error=not generation_face)
        except Exception as exc:
            if not generation_face:
                raise
            _publish_model_bytes(path, before_normalize)
            meta["normalization_error"] = str(exc)
        # Optional improvements must never discard a successfully validated rig.
        normalized = path.read_bytes()
        try:
            extension = _auto_extension_rig(character_name, path, meta)
        except Exception as exc:
            extension = {"ok": False, "error": str(exc)}
        if not extension.get("ok"):
            _publish_model_bytes(path, normalized)
            meta["extension_rig"] = {**(meta.get("extension_rig") or {}),
                                     "status": "failed",
                                     "reason": extension.get("error") or "Extension bones failed"}
        _attach_measurement(meta, path)
        _publish_sidecar(path, meta)
        try:
            if meta.get("base"):
                pass  # A base body has no distance tier.
            elif low or (face_meta and _auto_lod_enabled()):
                result = build_lod(character_name, signature, ratio=low_meta.get("lod_ratio") or _auto_lod_ratio())
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "Low tier rebuild failed")
            else:
                request_lod(character_name, path)
        except Exception as exc:
            for relative, low_path in _signature_files(out_dir, signature).items():
                if relative.parts[0] == LOW_TIER:
                    low_path.unlink(missing_ok=True)
            meta["lod_error"] = str(exc)
            _publish_sidecar(path, meta)
        return {"ok": True, "path": str(path), "filename": path.name,
                "warnings": {**{k: meta[k] for k in ("face_retexture", "extension_rig", "lod_error", "refined") if k in meta},
                             **({"validation": check["warnings"]} if check.get("warnings") else {})}}



def trigger_rerig(character_name: str, signature: str, *, backend_glob: str = "") -> Dict[str, Any]:
    """Track a caller-thread orchestration job, outside GPU workers."""
    from app.core.task_queue import get_task_queue
    with _lock:
        if character_name in _generating:
            return {"status": "already_running"}
        _generating.add(character_name)
    try:
        queue = get_task_queue()
        task_id = queue.track_start("model3d_rerig", f"Re-rig: {character_name}",
                                    agent_name=character_name, start_running=True)
    except Exception:
        with _lock:
            _generating.discard(character_name)
        raise
    with _lock:
        _rerig_results.pop(character_name, None)
    def run():
        result = {"ok": False, "error": "Re-rig failed"}
        try:
            with _char_lock(character_name):
                result = rerig_model(character_name, signature, backend_glob=backend_glob,
                                     track_id=task_id)
            if result.get("ok"):
                # A re-rigged BASE body (the 3D tab on the base-body pipeline)
                # makes every outfit model stale; no-op for an outfit model.
                after_base_face_change(character_name, signature)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            logger.exception("Re-rig failed for %s", character_name)
        finally:
            try:
                queue.track_finish(task_id, error="" if result.get("ok") else result.get("error") or "Re-rig failed")
            finally:
                with _lock:
                    _rerig_results[character_name] = {"ok": bool(result.get("ok")),
                                                       "error": result.get("error", ""),
                                                       "task_id": task_id}
                    _generating.discard(character_name)
    threading.Thread(target=run, daemon=True).start()
    return {"status": "generating", "task_id": task_id}


# A gateway job id as the admin may paste it — "Job 466a4e41b73d" straight out
# of the log works too. Only id characters reach the gateway URL.
_JOB_PREFIX = re.compile(r"^\s*job[\s:#]*", re.IGNORECASE)
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,127}$")


def normalize_job_id(raw: str) -> str:
    """The bare job id out of what was typed/pasted, "" when it is none."""
    job_id = _JOB_PREFIX.sub("", str(raw or "")).strip()
    return job_id if _JOB_ID.match(job_id) else ""


@_serial_model
def fetch_job_for_current_outfit(character_name: str, job_id: str, *,
                                 force: bool = False,
                                 signature: Optional[str] = None) -> Dict[str, Any]:
    """Collects a finished gateway mesh job by its id and stores it as the
    model of the currently worn combination — the way back to a mesh whose
    generation outlived our own poll (timeout, server restart) but finished
    on the gateway.

    A valid unrigged GLB becomes the current static model and its retained
    re-rig source immediately. A rigged result must match the character's rig;
    ``force`` may override its validation errors, never a wrong rig kind.
    Rigged results go through the same retexture/normalise/measure/LOD steps
    as a fresh generation.

    Returns ``{"status": "stored", "meta"}``, ``{"status": "queued"|"running",
    "progress", "elapsed_s"}`` while the job is not finished, ``{"status":
    "invalid", "errors", "warnings"}``, ``{"status": "busy"}`` while a
    generation runs for this character, or another status with ``error``.
    Blocking (downloads + Blender); call from a worker thread.
    """
    import tempfile
    from app.core.model_validate import validate_fbx
    from app.imagegen.service import get_image_service

    from app.core.model_refs import is_state_fork
    if is_state_fork(signature) or "-p" in (signature or ""):
        return {"status": "invalid", "error": "state_fork_retired"}
    with _lock:
        if character_name in _generating:
            return {"status": "busy",
                    "error": "a 3D model generation is running for this character"}
        _generating.add(character_name)
    staging: Optional[Path] = None
    try:
        with _char_lock(character_name):
            signature = signature or current_outfit_state(character_name)[2]
            rig = required_rig(character_name)
            out_dir = get_model3d_dir(character_name)
            staging = Path(tempfile.mkdtemp(prefix=".fetch-", dir=out_dir))
            res = get_image_service().fetch_mesh_job(
                job_id, str(staging / f"{signature}.fbx"))
            if res.get("status") != "stored":
                return res
            delivered_rig = res.get("rig", rig)
            if delivered_rig not in ("none", rig):
                return {"status": "rig_mismatch",
                        "error": f"job {job_id} delivered a '{delivered_rig}' mesh, '{rig}' is needed here"}
            if delivered_rig == "none":
                src = find_ref_image(character_name, "tpose", signature)
                manifest = {"source_image": src.name, **_ref_manifest(src)} if src else {}
                stored = _store_unrigged_model(character_name, signature, res, rig, manifest)
                if not stored.get("ok"):
                    return {"status": "invalid", "errors": stored["errors"], "warnings": stored["warnings"]}
                return {"status": "stored", "path": stored["path"],
                        "meta": stored["meta"], "warnings": stored["warnings"]}

            staged = Path(res["path"])
            tex_staged = Path(res["texture_path"]) if res.get("texture_path") else None
            data = staged.read_bytes()
            if staged.suffix.lower() == ".glb":
                check = _validator_for(rig, character_name)(data)
            else:
                check = validate_fbx(
                    data, tex_staged.read_bytes() if tex_staged else None,
                    _rig_result_validation_meta(res))
            if not check["ok"] and not force:
                logger.warning("Model3D %s: job %s fails the %s contract: %s",
                               character_name, job_id, rig,
                               "; ".join(check["errors"]))
                return {"status": "invalid", "errors": check["errors"],
                        "warnings": check["warnings"]}

            for warning in check.get("warnings", []):
                logger.warning("Model3D %s: job %s: %s", character_name, job_id, warning)

            path = out_dir / f"{signature}{staged.suffix.lower()}"
            _purge_combination(out_dir, signature, keep_model=path)
            _publish_model_bytes(path, data)
            staged.unlink()
            if tex_staged:
                _publish_model_bytes(path.with_suffix(tex_staged.suffix.lower()), tex_staged.read_bytes())
                tex_staged.unlink()
            meta: Dict[str, Any] = {
                "created_at": utc_now_iso(),
                "source": "generated",
                "backend": res.get("backend", ""),
                "format": res.get("format", path.suffix.lstrip(".").lower()),
                "rig": res.get("rig", rig),
                "has_texture": bool(tex_staged),
                "source_filename": res.get("filename", ""),
                "signature": signature,
                "character": character_name,
                # Collected afterwards, not awaited: the job id says which run
                # it was, since the options it was made with are unknown here.
                "job_id": res.get("job_id") or job_id,
            }
            src = find_ref_image(character_name, "tpose", signature)
            if src:
                # Most likely what the job was made from — the manifest says
                # which pieces this combination stands for either way.
                meta["source_image"] = src.name
                meta.update(_ref_manifest(src))
            _auto_retexture(character_name, path, meta)
            _auto_normalize(character_name, path, meta)
            _auto_extension_rig(character_name, path, meta)
            _attach_measurement(meta, path)
            from app.core.extension_rig import extension_metadata
            meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
            _publish_sidecar(path, meta)
            request_lod(character_name, path)
            logger.info("Model3D %s: job %s fetched as %s (%d bytes, "
                        "combination %s)", character_name, meta["job_id"], path.name,
                        path.stat().st_size, signature)
            return {"status": "stored", "meta": meta,
                    "warnings": check["warnings"]}
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        with _lock:
            _generating.discard(character_name)


# Characters on the base-body pipeline whose outfit-change trigger found a
# generation running: once it ends, the auto hook runs again for the outfit
# worn THEN (a newer combination gets its own run, never a mixed one).
_outfit_followups: set = set()


def _run(character_name: str, force: bool, backend_glob: str = "",
         prefer_cheapest: bool = False, face_num: Any = None,
         texture_size: Any = None, base: bool = False) -> None:
    followup = False
    with _char_lock(character_name):
        try:
            if base:
                # Signature and readiness are read when the run starts.
                from app.core.base_body import generate_base_model
                generate_base_model(character_name, force=force)
            else:
                generate_for_current_outfit(character_name, force=force,
                                            backend_glob=backend_glob,
                                            prefer_cheapest=prefer_cheapest,
                                            face_num=face_num,
                                            texture_size=texture_size)
        except Exception as e:
            logger.error("Model3D generation for %s failed: %s",
                         character_name, e)
        finally:
            with _lock:
                _generating.discard(character_name)
                followup = character_name in _outfit_followups
                _outfit_followups.discard(character_name)
    if followup:
        maybe_auto_generate_for_outfit(character_name)


def trigger_generation(character_name: str, *, force: bool = False,
                       backend_glob: str = "",
                       prefer_cheapest: bool = False,
                       face_num: Any = None,
                       texture_size: Any = None,
                       base: bool = False, followup: bool = False) -> bool:
    """Starts the mesh generation in the background.
    ``backend_glob`` picks the mesh backend (empty = the rig's mesh occasion
    chain of the image routing; ``prefer_cheapest`` always cheapest of the
    rig — the auto hook). ``base`` builds the base body
    (``base_body.generate_base_model``) instead of the outfit's model.
    False when one is already running for this character; ``followup``
    then marks the auto hook to run again once it has ended (base-body
    outfit trigger)."""
    with _lock:
        if character_name in _generating:
            if followup:
                _outfit_followups.add(character_name)
            return False
        _generating.add(character_name)
    threading.Thread(target=_run,
                     args=[character_name, force, backend_glob, prefer_cheapest,
                           face_num, texture_size, base],
                     daemon=True).start()
    return True


def maybe_auto_generate_for_outfit(character_name: str) -> bool:
    """Auto-mesh hook — model_refs calls it AFTER a T-pose render pass, so
    a run only ever starts once the T-pose for the CURRENT combination
    exists (freshly rendered or cached). Conditions: the character's
    ``auto_generate`` option is on, the combination has no mesh yet, no
    run is active. Uses the CHEAPEST matching mesh backend (user decision
    2026-07-18). Returns True when a generation was started.

    Base-body pipeline: no ``auto_generate`` needed (the outfit model costs
    no GPU — ``base_body.build_outfit_model``); the input is the dressed
    front made from the current base body. A run already in progress marks
    a follow-up: when it ends, this hook runs again for the outfit worn
    then."""
    try:
        from app.core.base_body import base_signature, dressed_image, is_base_pipeline
        pipeline = is_base_pipeline(character_name)
        if not pipeline and not get_model3d_options(character_name).get("auto_generate"):
            return False
        _, _, signature = current_outfit_state(character_name)
        if not signature or find_model3d(character_name, signature):
            return False
        if pipeline:
            if not dressed_image(character_name, "front", signature, base_signature(character_name)):
                return False  # the dressed edits failed / are not there yet
        elif not find_ref_image(character_name, "tpose", signature):
            return False  # render failed / not there yet — wait for the next pass
    except Exception as e:
        logger.debug("Model3D auto check for %s failed: %s",
                     character_name, e)
        return False
    if pipeline:
        started = trigger_generation(character_name, followup=True)
        logger.info("Model3D %s: outfit model on the base body %s", character_name,
                    "started" if started else "queued behind the running generation")
        return started
    started = trigger_generation(character_name, prefer_cheapest=True)
    if started:
        logger.info("Model3D %s: auto generation started (T-pose present, "
                    "cheapest backend)", character_name)
    return started


@_serial_model
def delete_model3d(character_name: str, signature: Optional[str] = None) -> bool:
    """Deletes the cached mesh (+ sidecar + texture + reduced tiers); True if
    removed. A tier is derived from this file, so it never outlives it.
    A model built on an older base body can be deleted too."""
    path = find_model3d(character_name, signature, include_stale=True)
    if not path:
        return False
    _purge_combination(path.parent, path.stem)
    return True


def model_revision(path: Optional[Path]) -> str:
    """Revision of a complete publication; never of processing stages."""
    if path is None:
        return ""
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("model3d_publication", str(path.parent)):
        return _model_revision_unlocked(path)


def _model_revision_unlocked(path: Optional[Path]) -> str:
    """Revision of ordered tier stat records, with no mesh content reads.

    In-place writers change mtime; atomic replacements also change inode.
    Presence is explicit so creating/removing any tier invalidates the client.
    """
    import hashlib
    if path is None:
        return ""
    records = []
    found = False
    for tier in MODEL_TIERS:
        candidate = path if tier == FULL_TIER else path.parent / tier / path.name
        try:
            stat = candidate.stat()
            records.append((tier, True, stat.st_size, stat.st_mtime_ns, stat.st_ino))
            found = True
        except OSError:
            records.append((tier, False, 0, 0, 0))
    # The garment assembly of a top-level model is what the byte routes
    # deliver: a built, rebuilt or dropped assembly must reload the client.
    # Recorded only when present, so a model without one keeps its revision.
    if path.parent.name not in (LOW_TIER, ASSEMBLED_DIR):
        for tier in MODEL_TIERS:
            candidate = path.parent / ASSEMBLED_DIR / (path.name if tier == FULL_TIER else Path(tier) / path.name)
            try:
                stat = candidate.stat()
            except OSError:
                continue
            records.append((f"{ASSEMBLED_DIR}/{tier}", True, stat.st_size, stat.st_mtime_ns, stat.st_ino))
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest() if found else ""


def face_retexture_model(character_name: str, signature: Optional[str] = None, *,
                         backend_glob: str = "", params=None, photo=None, upscale: Optional[bool] = None, reference: str = "",
                         upscale_backend_glob: str = "", track_id: str = "") -> Dict[str, Any]:
    """Project the original photo, then rebuild every derived asset in the stage.

    A hub operation (upscale → face → bake → rig, app/core/hub_ops.py): inside
    a queue handler that left one open before a restart, this resumes it."""
    from app.core import hub_ops
    op = hub_ops.find_open(_OP_FACE, _op_match(character_name, signature))
    if op is not None:
        return _resume_entry(op, lambda: _face_retexture_model(
            character_name, op.inputs["signature"], _op_ctx={"op": op}), character_name)
    return hub_ops.run_new(lambda ctx: _face_retexture_model(
        character_name, signature, backend_glob=backend_glob, params=params, photo=photo,
        upscale=upscale, reference=reference, upscale_backend_glob=upscale_backend_glob, track_id=track_id,
        _op_ctx=ctx))


@_serial_model
def _face_retexture_model(character_name: str, signature: Optional[str] = None, *,
                          backend_glob: str = "", params=None, photo=None, upscale: Optional[bool] = None, reference: str = "",
                          upscale_backend_glob: str = "", track_id: str = "",
                          _op_ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The staged half: checks + record (fresh run), then the stages. A
    resume skips the eligibility and readiness checks — the job it collects
    was admitted when it was submitted, and a backend that is not reachable
    yet must not throw away a result the hub still holds."""
    from app.core import face_retexture, hub_ops
    root = get_model3d_dir(character_name)
    op = (_op_ctx or {}).get("op")
    if op is None:
        from app.core.face_photo_adjust import validated_params as photo_params, PROBLEM, FIX
        # No explicit values (Improvements, any non-dialog caller): the
        # character's remembered ones, exactly like face-before-rig.
        explicit_photo = photo is not None
        remembered = photo_params(get_model3d_options(character_name)['face_photo'])
        photo = photo_params(photo) if explicit_photo else dict(remembered)
        photo_mode = 'hub' if face_retexture.photo_controls_supported(character_name, backend_glob) else 'local'
        photo_reason = ''
        controls = face_retexture.validated_params(params)
        face_snapshot = {}
        eligibility = face_retexture.check(character_name, signature, reference, _snapshot=face_snapshot)
        ready = face_retexture.runnable(character_name, backend_glob)
        problems = eligibility['problems'] + ready['problems']
        if problems:
            return {'ok': False, 'problems': problems, 'error': '; '.join(p['message'] for p in problems)}
        original = root / 'unrigged' / f'{signature}.glb'
        reference = eligibility['reference']
        upscale = face_retexture.use_upscale(reference, upscale)
        if photo_mode == 'local' and reference == 'front' and photo['balance'] and not explicit_photo:
            # A remembered balance never blocks a front-view run: brightness only.
            photo['balance'] = 0.
            photo_reason = PROBLEM
        try:
            if photo_mode == 'local' and reference == 'front' and photo['balance']:
                raise ValueError(PROBLEM)
            try:
                image = (face_snapshot['image'] if photo_mode == 'hub' or (photo['balance'] == 0 and photo['brightness'] == 1)
                         else face_retexture.flatten_photo(face_snapshot['rgba'], photo))
            except ValueError as exc:
                # Remembered values never block a run on a photo without a
                # cut-out; an explicit dialog choice is refused instead.
                if explicit_photo or str(exc) != PROBLEM or not photo['balance']:
                    raise
                photo['balance'] = 0.
                photo_reason = PROBLEM
                image = face_retexture.flatten_photo(face_snapshot['rgba'], photo)
        except ValueError as exc:
            return {'ok': False, 'problems': [{'code': 'face_photo', 'message': str(exc), 'fix': FIX}], 'error': str(exc)}
        if explicit_photo:
            # A front-view run cannot express a balance (the dialog disables
            # it): keep the remembered one instead of overwriting it with 0.
            set_model3d_options(character_name, {'face_photo': {
                'balance': remembered['balance'] if photo_mode == 'local' and reference == 'front' else photo['balance'],
                'tone_match': photo['tone_match'], 'skin_recolor': photo['skin_recolor'], 'brightness': photo['brightness']}})
        if upscale and upscale_backend_glob:
            from app.core.upscale_reference import require_upscale_backend
            require_upscale_backend(upscale_backend_glob, character_name)
        op = hub_ops.create(_OP_FACE, _op_subject(character_name, signature), {
            "character": character_name, "signature": signature, "controls": controls, "photo": photo, "photo_mode": photo_mode,
            **({"photo_reason": photo_reason} if photo_reason else {}),
            "backend_glob": backend_glob, "upscale": bool(upscale), "reference": reference,
            "upscale_backend_glob": upscale_backend_glob, "source_kind": "facefix",
            "rig": required_rig(character_name),
            "rig_options": _character_rig_options(character_name),
        }, label=f"Face retexture: {character_name}", track_id=track_id)
        if _op_ctx is not None:
            _op_ctx["op"] = op
        op.path("inputs", "photo.png").write_bytes(image)
        # Same file name as the published source it is frozen from.
        op.freeze_file(original, "inputs", "unrigged", f"{signature}.glb")
    corrected = _face_source_stages(character_name, op)
    if not corrected.get("ok"):
        return corrected
    source, mask = corrected["source"], corrected["mask"]
    face_meta = op.result("bake")["face_meta"]
    rigged = _rig_from_source(character_name, signature, source, replacement_mask=mask, op=op)
    if rigged.get('ok'):
        rigged['face_retexture'] = _read_sidecar(Path(rigged['path'])).get('face_retexture', face_meta)
    return rigged


def _face_source_stages(character_name: str, op) -> Dict[str, Any]:
    """Build a durable corrected source through the shared upscale/face/bake stages.

    Both standalone correction and new-mesh generation consume only frozen
    operation inputs. Failed validation returns an error; cancellation and
    backend exceptions propagate so the caller can apply its failure policy.
    """
    from app.core import face_retexture
    from app.core.mesh_source import validate_face_source
    from app.imagegen.service import get_image_service
    root = get_model3d_dir(character_name)
    inputs = op.inputs
    signature = inputs["signature"]
    controls = inputs["controls"]
    original_file = op.abs(f"inputs/unrigged/{signature}.glb")
    original_bytes = original_file.read_bytes()
    image = op.abs("inputs/photo.png").read_bytes()

    if not op.done("upscale"):
        upscale_meta = {'status': 'off', **({'reason': 'face view'} if inputs.get('reference') == 'face' else {})}
        if inputs["upscale"]:
            from app.imagegen.base import GenerationCancelled, GpuTaskCancelled, HubJobLost, MediaGenerationDisabled, BackendBusyError
            publication = getattr(_staging, 'source_publications', {}).get(character_name)
            cache_root = publication['directory'] if publication else root
            cache_path = cache_root / 'facefix-ref' / f'{signature}.png'
            if not cache_path.resolve().is_relative_to(cache_root.resolve()):
                raise ValueError('Reference cache path escapes the model directory')
            try:
                improved = get_image_service().upscale_image(
                    image, backend_glob=inputs.get("upscale_backend_glob") or "",
                    character_name=character_name, cache_path=cache_path,
                    hub_stage=op.stage("upscale"))
                op.path("upscale", "image.png").write_bytes(improved['bytes'])
                upscale_meta = {k: v for k, v in improved.items() if k != 'bytes'}
            except (GenerationCancelled, GpuTaskCancelled, MediaGenerationDisabled, HubJobLost):
                # A lost upscale job is terminal for the whole correction — it
                # must not degrade into "upscale failed, project the raw photo".
                raise
            except Exception as exc:
                upscale_meta = {'status': 'failed', 'error': str(exc),
                                'busy': isinstance(exc, BackendBusyError)}
                logger.warning('Reference upscale failed: %s', exc)
        op.complete("upscale", {"meta": upscale_meta})
    upscale_meta = op.result("upscale").get("meta") or {'status': 'off'}
    if op.abs("upscale/image.png").is_file():
        image = op.abs("upscale/image.png").read_bytes()

    def attempt(face_stage: str, bake_stage: str, prefix: tuple, attempt_controls: Dict[str, Any]) -> Dict[str, Any]:
        """One projection (hub stage ``face_stage``) and its bake
        (``bake_stage``); the corrected source and mask go under ``prefix``
        of the record ("" = ``source/`` and ``bake/``, what the rig reads)."""
        if not op.done(face_stage):
            request = dict(attempt_controls)
            if inputs.get('photo_mode', 'local') == 'hub':
                photo = inputs['photo']
                request.update(light_balance=photo['balance'], tone_match=photo['tone_match'], brightness=photo['brightness'], skin_recolor=photo.get('skin_recolor', 0.))
            result = get_image_service().generate_face_retexture(
                str(original_file), image, str(op.path(face_stage, "x").parent),
                request, (inputs.get("face_backend_glob") if inputs.get("face_before_rig") else inputs.get("backend_glob")) or "", character_name,
                hub_stage=op.stage(face_stage))
            if not result.get('ok'):
                return {'ok': False, 'error': result.get('error') or 'Face retexture failed'}
            op.complete(face_stage, _op_rel(op, result, "path", "compare_path"))
        result = _op_abs(op, op.result(face_stage), "path", "compare_path")

        if not op.done(bake_stage):
            import numpy as np
            # No size cap on the hub result: it only donates its face texture and
            # may exceed the upload limit (skin recolour ships a second full
            # atlas). Only the baked mesh below goes to the rig upload.
            raw = Path(result['path']).read_bytes()
            verdict = validate_face_source(raw)
            before = validate_face_source(original_bytes, original=True)
            if not verdict['ok'] or verdict['triangles'] != before['triangles']:
                return {'ok': False, 'error': '; '.join(verdict['errors']) or 'Face retexture changed the triangle count'}
            try:
                replacement_masks = []
                raw, baked = face_retexture.bake_face_texture(
                    original_bytes, raw, replacement_masks=replacement_masks)
            except ValueError as exc:
                return {'ok': False, 'error': str(exc)}
            if len(raw) > face_retexture.MAX_BYTES:
                return {'ok': False, 'error': 'Baked mesh exceeds the 64 MB rig upload limit'}
            from app.core.face_photo_adjust import TONE_MATCH_UNSUPPORTED, SKIN_RECOLOR_UNSUPPORTED
            photo_meta = dict(inputs.get('photo', {'balance': 0., 'brightness': 1.}))
            # Old operations already contain locally adjusted bytes; never reapply them.
            photo_meta.setdefault('tone_match', 0.)
            if inputs.get('photo_mode', 'local') == 'hub':
                photo_meta.update(result.get('photo_application') or {
                    'applied_on': 'none', 'reason': 'The running face backend did not confirm photo controls.'})
            else:
                photo_meta['applied_on'] = 'local'
                if inputs.get('photo_reason'):
                    photo_meta['reason'] = inputs['photo_reason']
            if inputs.get('photo_mode', 'local') == 'local':
                photo_meta['skin_recolor'] = {'status': 'unsupported', 'reason': SKIN_RECOLOR_UNSUPPORTED}
            face_meta = {'status': 'applied', 'at': utc_now_iso(), 'reference': inputs.get('reference', 'front'),
                         'backend': result.get('backend', ''), 'job_id': result.get('job_id', ''),
                         'params': attempt_controls, 'photo': photo_meta,
                         **({'tone_match': {'status': 'unsupported', 'reason': TONE_MATCH_UNSUPPORTED}}
                            if inputs.get('photo_mode', 'local') == 'local' else {}),
                         **({'photo_reason': inputs['photo_reason']} if inputs.get('photo_reason') else {}), 'upscale': upscale_meta, 'baked': baked, 'result_sha256': result.get('result_sha256', ''),
                         'result_url': result.get('result_url', ''),
                         'route_meta': {k: result[k] for k in ROUTE_META_KEYS if k in result}}
            if result.get('compare_path'):
                comparison = Path(result['compare_path']).read_bytes()
                from PIL import Image
                import io
                decoded = Image.open(io.BytesIO(comparison))
                decoded.load()
                if decoded.format != 'PNG':
                    return {'ok': False, 'error': 'Comparison image is not a PNG'}
                op.path(*prefix, "source", f"{signature}.png").write_bytes(comparison)
            # The corrected source, its sidecar and the replacement mask live in
            # the record, not only in the stage: a restart during the rig job
            # must not lose the correction.
            op.path(*prefix, "source", f"{signature}.glb").write_bytes(raw)
            op.path(*prefix, "source", f"{signature}.json").write_bytes(json.dumps(
                {'face_retexture': face_meta, 'baked': baked}, indent=2, ensure_ascii=False).encode("utf-8"))
            with op.path(*prefix, "bake", "mask.npy").open("wb") as handle:
                np.save(handle, np.asarray(replacement_masks[0]) if replacement_masks else np.zeros((0, 0), dtype=bool))
            op.complete(bake_stage, {"face_meta": face_meta, "has_mask": bool(replacement_masks)})
        return {'ok': True}

    first = attempt("face", "bake", (), controls)
    if not first.get("ok"):
        return first
    if not op.done("face_gate"):
        _dark_face_gate(character_name, op, attempt, controls, image)

    source = _restore_frozen_source(op, root, signature)
    if not op.abs(f"source/{signature}.png").is_file():
        source.with_suffix('.png').unlink(missing_ok=True)
    mask = None
    if op.result("bake").get("has_mask"):
        import numpy as np
        with op.abs("bake/mask.npy").open("rb") as handle:
            mask = np.load(handle)
    return {"ok": True, "source": source, "mask": mask}


DARK_FACE_WARNING = ("The face projection left dark texels in the face (a black eye socket?) — "
                     "check the comparison image; a retry with another yaw did not fix it")


def _dark_face_retry_yaw(character_name: str, signature: str, yaw: float) -> float:
    """The one retry's yaw: ``DARK_RETRY_YAW`` degrees in the direction of
    the rigged head's measured twist (``blender.head_twist.before.head`` of
    the clean prerig source; positive without one), clamped to ±180."""
    from app.core.face_retexture import DARK_RETRY_YAW
    twist = ((_read_sidecar(get_model3d_dir(character_name) / "prerig" / f"{signature}.glb")
              .get("blender") or {}).get("head_twist") or {}).get("before") or {}
    head = twist.get("head")
    sign = -1.0 if isinstance(head, (int, float)) and head < 0 else 1.0
    return max(-180.0, min(180.0, float(yaw) + sign * DARK_RETRY_YAW))


def _dark_face_gate(character_name: str, op, attempt, controls: Dict[str, Any], image: bytes) -> None:
    """The "black eye" gate after the bake (``face_retexture.dark_face_gate``).

    A failing bake logs a warning and runs ONE retry (hub stage
    ``face_retry``, bake ``bake_retry``, files under ``retry/``) with the
    yaw turned by ``_dark_face_retry_yaw``; the retry replaces the first
    bake (``source/``, ``bake/mask.npy``, the ``bake`` result) only when it
    is less dark. The record ``dark_gate`` (``ok``, the shares, ``retried``,
    ``retry_yaw``, ``retry``, ``chosen``, ``warning`` when still failing)
    goes into the chosen bake's ``face_meta`` and its source sidecar — the
    model sidecar's ``face_retexture`` the 3D tab shows. Never fails the
    correction; cancellation of the retry job propagates."""
    from app.core import face_retexture
    from app.imagegen.base import GenerationCancelled, GpuTaskCancelled, HubJobLost, MediaGenerationDisabled
    signature = op.inputs["signature"]
    first = op.result("bake")
    gate = face_retexture.dark_face_gate((first.get("face_meta") or {}).get("baked") or {}, image)
    record: Dict[str, Any] = {**gate, "retried": False, "chosen": "first"}
    chosen = first
    if not gate.get("ok", True):
        yaw = _dark_face_retry_yaw(character_name, signature, controls.get("yaw", 0))
        logger.warning("Face retexture %s (%s): face coverage %.2f %% near-black vs photo %.2f %% — retrying with yaw %.1f",
                       character_name, signature, 100 * gate["dark_share"], 100 * gate["photo_dark_share"], yaw)
        record.update(retried=True, retry_yaw=yaw)
        try:
            retry = attempt("face_retry", "bake_retry", ("retry",), {**controls, "yaw": yaw})
        except (GenerationCancelled, GpuTaskCancelled, MediaGenerationDisabled, HubJobLost):
            raise
        except Exception as exc:  # noqa: BLE001 — the first bake stands
            retry = {"ok": False, "error": str(exc) or type(exc).__name__}
        if retry.get("ok"):
            second = op.result("bake_retry")
            retry_gate = face_retexture.dark_face_gate((second.get("face_meta") or {}).get("baked") or {}, image)
            record["retry"] = retry_gate
            if retry_gate.get("excess", 0) < gate.get("excess", 0):
                chosen = second
                record["chosen"] = "retry"
                for suffix in (".glb", ".json", ".png"):
                    target = op.path("source", f"{signature}{suffix}")
                    if op.abs(f"retry/source/{signature}{suffix}").is_file():
                        target.write_bytes(op.abs(f"retry/source/{signature}{suffix}").read_bytes())
                    else:
                        target.unlink(missing_ok=True)
                op.path("bake", "mask.npy").write_bytes(op.abs("retry/bake/mask.npy").read_bytes())
            record["ok"] = bool((retry_gate if record["chosen"] == "retry" else gate).get("ok"))
        else:
            record["retry_error"] = retry.get("error") or "Face retexture retry failed"
        if not record["ok"]:
            record["warning"] = DARK_FACE_WARNING
            logger.warning("Face retexture %s (%s): %s", character_name, signature, DARK_FACE_WARNING)
    face_meta = {**(chosen.get("face_meta") or {}), "dark_gate": record}
    sidecar = op.abs(f"source/{signature}.json")
    stored = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    sidecar.write_bytes(json.dumps({**stored, "face_retexture": face_meta}, indent=2,
                                   ensure_ascii=False).encode("utf-8"))
    op.complete("bake", {**chosen, "face_meta": face_meta})
    op.complete("face_gate", record)


def revert_face_retexture(character_name: str, signature: Optional[str] = None) -> Dict[str, Any]:
    """Settle a fallback re-rig only after the outer revert publication succeeds."""
    from app.core import hub_ops
    return hub_ops.run_new(lambda ctx: _revert_face_retexture(
        character_name, signature, _op_ctx=ctx))


@_serial_model
def _revert_face_retexture(character_name: str, signature: Optional[str] = None, *,
                           _op_ctx=None) -> Dict[str, Any]:
    """Restore the first snapshot, or re-rig an original generation-time source."""
    from app.core.face_retexture import snapshot_info
    root = get_model3d_dir(character_name)
    publication = getattr(_staging, 'source_publications', {}).get(character_name)
    real_root = publication['directory'] if publication else root
    snapshot = real_root / 'rollback' / signature
    info = snapshot_info(real_root, signature)
    if not info['ok']:
        path = find_model3d(character_name, signature)
        if (not snapshot.exists() and path
                and _read_sidecar(path).get("face_retexture", {}).get("status") == "applied"
                and (root / "unrigged" / f"{signature}.glb").is_file()):
            return _rerig_model(character_name, signature, _revert_face=True, _op_ctx=_op_ctx)
        return info
    for path in _signature_files(root, signature).values():
        path.unlink()
    for entry in info['files']:
        relative = Path(entry['path'])
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot / relative, target)
    path = find_model3d(character_name, signature)
    meta = _read_sidecar(path)
    meta['face_retexture'] = {'status': 'reverted', 'at': utc_now_iso()}
    _publish_sidecar(path, meta)
    (root / '.face-revert').touch()
    return {'ok': True, 'path': str(path), 'filename': path.name,
            'face_retexture': meta['face_retexture']}


def after_base_face_change(character_name: str, signature: str) -> None:
    """A face correction or its revert re-rigged the BASE body: its model
    bytes changed, so every outfit model is stale (``base_model_sha256``)
    and rebuilt on its next trigger; the worn garments refit onto the new
    base (``garments.after_base_model``, as after a base model run). A
    non-base signature does nothing. Never raises."""
    try:
        from app.core.base_body import is_base_signature
        if not is_base_signature(signature):
            return
        from app.core import garments
        garments.after_base_model(character_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Model3D %s: follow-up of the base face change failed: %s", character_name, exc)


def trigger_face_retexture(character_name: str, signature: str, *,
                           backend_glob: str = '', params=None, photo=None, upscale: Optional[bool] = None, reference: str = "",
                           upscale_backend_glob: str = '') -> Dict[str, Any]:
    """Track orchestration on the character's shared generation guard."""
    from app.core.task_queue import get_task_queue
    from app.core.face_retexture import safe_signature, validated_params
    safe_signature(signature)
    controls = validated_params(params)
    from app.core.face_photo_adjust import validated_params as photo_params
    photo = photo_params(photo) if photo is not None else None  # None = remembered
    with _lock:
        if character_name in _generating:
            return {'status': 'already_running'}
        _generating.add(character_name)
        _face_retexture_results.pop(character_name, None)
    try:
        queue = get_task_queue()
        task_id = queue.track_start('model3d_face_retexture', f'Face retexture: {character_name}',
                                    agent_name=character_name, start_running=True)
    except Exception:
        with _lock:
            _generating.discard(character_name)
        raise

    def run():
        result = {'ok': False, 'error': 'Face retexture failed'}
        try:
            with _char_lock(character_name):
                result = face_retexture_model(character_name, signature,
                                               backend_glob=backend_glob, params=controls, photo=photo,
                                               upscale=upscale, reference=reference, upscale_backend_glob=upscale_backend_glob,
                                               track_id=task_id)
            if result.get('ok'):
                after_base_face_change(character_name, signature)
        except Exception as exc:
            result = {'ok': False, 'error': str(exc)}
            logger.exception('Face retexture failed for %s', character_name)
        finally:
            try:
                queue.track_finish(task_id, error='' if result.get('ok') else result.get('error') or 'Face retexture failed')
            finally:
                with _lock:
                    _face_retexture_results[character_name] = {**result, 'task_id': task_id}
                    _generating.discard(character_name)
    threading.Thread(target=run, daemon=True).start()
    return {'status': 'generating', 'task_id': task_id}


# ── Face cleanup re-apply ─────────────────────────────────────────────────
# The face cleanup (app/core/face_cleanup.py) runs on the mesher's result
# before it becomes the retained source ``unrigged/<signature>.glb``. Its
# per-character switch (``model3d_opts.face_cleanup``) only decides the NEXT
# mesher run; "Re-apply face cleanup" brings it onto the STORED mesh: the
# retained source is cleaned in place (a local step, published on its own),
# then everything after it is rebuilt from it — the face retexture when the
# model carries one or "Improve face before rigging" is on (its stages: an
# upscale of a front-view reference, the face retexture, the rig), otherwise a
# re-rig. Normalize, extension bones, collision capsules and the distance tier
# follow the rig as on every rig run; on the base-body pipeline the outfit
# models turn stale (``after_base_face_change``). The mesher's own bytes are
# not retained: a source cleaned once stays cleaned (the switch off only
# affects the next mesher run), and a source cleaned at the current
# ``face_cleanup.VERSION`` is not cleaned again.

FACE_CLEANUP_JOBS = {"face_retexture": ["upscale (front-view reference only)", "face retexture", "rig"],
                     "rerig": ["rig"]}


def face_cleanup_signature(character_name: str, signature: str = "") -> str:
    """The signature whose retained source the face cleanup acts on: the
    base body's on the base-body pipeline (outfit models have no unrigged
    source of their own), else ``signature`` or the served model's."""
    base = _current_base(character_name)
    if base:
        return base[0]
    if signature:
        return signature
    served = find_model3d_serving(character_name)[0]
    return served.stem if served else ""


def face_cleanup_state(character_name: str, signature: str) -> Dict[str, Any]:
    """What the UI shows of the face cleanup of ``unrigged/<signature>.glb``
    and what a re-apply costs: ``{signature, enabled, humanoid, stored,
    status, summary, version, current_version, follow_up, jobs, can_reapply,
    blocked, running, result}``. ``status``: applied | skipped | failed |
    missing (a source made before the step) | none (no source). ``blocked``
    is the English reason a re-apply is refused ('' when it can run)."""
    from app.core import face_cleanup
    options = get_model3d_options(character_name)
    enabled = bool(options.get("face_cleanup"))
    humanoid = required_rig(character_name) == "mixamo"
    directory = get_model3d_dir(character_name)
    source = directory / "unrigged" / f"{signature}.glb" if signature else None
    stored = bool(source is not None and source.is_file())
    record = _read_sidecar(source).get("face_cleanup") if stored else None
    record = record if isinstance(record, dict) else {}
    status = str(record.get("status") or ("missing" if stored else "none"))
    summary = (str(record.get("error") or "") if status == "failed"
               else str(record.get("reason") or "") if status == "skipped" and record.get("reason")
               else face_cleanup.summary(record) if record else "")
    applied_now = status == "applied" and record.get("version") == face_cleanup.VERSION
    follow_up = "face_retexture" if humanoid and stored and (
        options.get("face_before_rig") or (directory / "facefix" / f"{signature}.glb").is_file()) else "rerig"
    with _lock:
        running = character_name in _generating
        result = _face_cleanup_results.get(character_name)
    blocked = ("Humanoid models only." if not humanoid
               else "No retained unrigged mesh — generate the model again." if not stored
               else "Switch the face cleanup on first." if not enabled
               else "Already applied to the stored mesh." if applied_now
               else "A 3D model run of this character is going." if running else "")
    return {"signature": signature, "enabled": enabled, "humanoid": humanoid, "stored": stored,
            "status": status, "summary": summary, "version": record.get("version"),
            "current_version": face_cleanup.VERSION, "follow_up": follow_up,
            "jobs": FACE_CLEANUP_JOBS[follow_up], "can_reapply": not blocked, "blocked": blocked,
            "running": running, "result": result}


@_serial_model
def _reclean_face_source(character_name: str, signature: str) -> Dict[str, Any]:
    """Clean the retained source ``unrigged/<signature>.glb`` in place (staged
    by ``_serial_model``, published on return). The rigged model is not
    touched here — the caller rebuilds it from the cleaned source."""
    from app.core import face_cleanup
    from app.core.mesh_source import validate_source
    root = get_model3d_dir(character_name)
    source = root / "unrigged" / f"{signature}.glb"
    if not source.is_file():
        return {"ok": False, "error": "No retained unrigged mesh — generate the model again."}
    blob = source.read_bytes()
    try:
        cleaned, record = face_cleanup.clean_face(blob)
        if record.get("status") == "applied":
            verdict = validate_source(cleaned)
            if not verdict.get("ok"):
                raise ValueError("cleaned mesh fails validation: " + "; ".join(verdict.get("errors") or []))
    except Exception as exc:  # noqa: BLE001 — reported, the stored source stays as it was
        return {"ok": False, "error": f"Face cleanup failed: {exc}"}
    record["reapplied"] = True
    meta = _read_sidecar(source)
    meta["face_cleanup"] = record
    if cleaned != blob:
        _publish_model_bytes(source, cleaned)
        # The face-revert snapshot shows the model before its face retexture,
        # built on the source just replaced: drop it with the publication.
        (root / ".replace-source").touch()
    _publish_sidecar(source, meta)
    logger.info("Face cleanup re-applied %s/%s: %s", character_name, signature, face_cleanup.summary(record))
    return {"ok": True, "face_cleanup": record, "changed": cleaned != blob}


def trigger_face_cleanup(character_name: str, signature: str) -> Dict[str, Any]:
    """Start "Re-apply face cleanup" for ``signature`` in a tracked thread on
    the character's shared generation guard: ``{status: "generating",
    task_id, follow_up, jobs}`` or ``{status: "already_running"}``.
    ValueError when the state refuses it (``face_cleanup_state.blocked``);
    LookupError with the problems when the follow-up cannot run (no face
    retexture backend, no rig route, a changed reference photo)."""
    from app.core.face_retexture import check as face_check, runnable as face_runnable, safe_signature
    from app.core.task_queue import get_task_queue
    safe_signature(signature)
    state = face_cleanup_state(character_name, signature)
    if state["running"]:
        return {"status": "already_running"}
    if not state["can_reapply"]:
        raise ValueError(state["blocked"])
    follow_up = state["follow_up"]
    if follow_up == "face_retexture":
        problems = face_check(character_name, signature)["problems"] + face_runnable(character_name)["problems"]
    else:
        from app.imagegen.routing import chain_candidates
        from app.imagegen.service import get_image_service
        problems = [] if chain_candidates("rig_humanoid", pool=get_image_service().pool) else [
            {"code": "no_rigger", "message": "No humanoid rig route is configured."}]
    if problems:
        raise LookupError("; ".join(p["message"] for p in problems))
    with _lock:
        if character_name in _generating:
            return {"status": "already_running"}
        _generating.add(character_name)
        _face_cleanup_results.pop(character_name, None)
    try:
        queue = get_task_queue()
        task_id = queue.track_start("model3d_face_cleanup", f"Face cleanup: {character_name}",
                                    agent_name=character_name, start_running=True)
    except Exception:
        with _lock:
            _generating.discard(character_name)
        raise

    def run():
        result: Dict[str, Any] = {"ok": False, "error": "Face cleanup failed"}
        try:
            with _char_lock(character_name):
                result = _reclean_face_source(character_name, signature)
                if result.get("ok"):
                    if follow_up == "face_retexture":
                        result = face_retexture_model(character_name, signature, track_id=task_id)
                    else:
                        result = rerig_model(character_name, signature, track_id=task_id)
            if result.get("ok"):
                after_base_face_change(character_name, signature)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            logger.exception("Face cleanup re-apply failed for %s", character_name)
        finally:
            try:
                queue.track_finish(task_id, error="" if result.get("ok") else result.get("error") or "Face cleanup failed")
            finally:
                with _lock:
                    _face_cleanup_results[character_name] = {"ok": bool(result.get("ok")),
                                                             "error": result.get("error", ""),
                                                             "task_id": task_id, "follow_up": follow_up}
                    _generating.discard(character_name)
    threading.Thread(target=run, daemon=True).start()
    return {"status": "generating", "task_id": task_id, "follow_up": follow_up, "jobs": state["jobs"]}


# ── Resume registration (app/core/hub_ops.py) ─────────────────────────────

def _op_reserve(op):
    """The character's generation guard, taken synchronously by the resumer
    before the AgentLoop and the queue workers start — an auto-mesh hook or a
    second admin action sees the character as busy. Released after the run;
    never releases a guard somebody else holds."""
    name = op.inputs.get("character") or ""
    with _lock:
        if name in _generating:
            return lambda: None
        _generating.add(name)

    def release() -> None:
        with _lock:
            _generating.discard(name)
    return release


def _op_thread_resume(staged, results: Optional[Dict[str, Dict[str, Any]]] = None):
    """Resume entry of a thread-owned character operation: the character
    lock like the trigger threads, the staged function with the frozen
    signature, and — for re-rig/face — the result the status routes show."""
    def run(op):
        from app.core import hub_ops
        name = op.inputs["character"]
        result: Dict[str, Any] = {"ok": False, "error": "resume failed"}
        try:
            with _char_lock(name):
                result = hub_ops.resume(op, lambda: staged(
                    name, signature=op.inputs["signature"], _op_ctx={"op": op}), agent_name=name)
            return result
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            raise
        finally:
            if results is not None:
                with _lock:
                    results[name] = {**result, "task_id": op.track_id}
    return run


def _register_hub_kinds() -> None:
    from app.core import hub_ops
    hub_ops.register_kind(_OP_MESH, resume=_op_thread_resume(_generate_for_current_outfit),
                          track_type="model3d_generation", reserve=_op_reserve,
                          optional_stage=lambda op, name: bool(op.inputs.get("face_before_rig"))
                          and name in ("upscale", "face", "bake", "face_retry"))
    hub_ops.register_kind(_OP_RERIG, resume=_op_thread_resume(_rerig_model, _rerig_results),
                          track_type="model3d_rerig", reserve=_op_reserve)
    # The dark-face retry is optional: its lost collection is replayed as a
    # failed retry, the first bake stands (``_dark_face_gate``).
    hub_ops.register_kind(_OP_FACE, resume=_op_thread_resume(_face_retexture_model, _face_retexture_results),
                          track_type="model3d_face_retexture", reserve=_op_reserve,
                          optional_stage=lambda op, name: name == "face_retry")


_register_hub_kinds()
