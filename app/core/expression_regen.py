"""Outfit-bound expression images and the explicit character reference renderer."""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from types import MappingProxyType
from typing import Any, Dict, Optional, Set
import uuid

from app.core.config_schema import field_default
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.imagegen.base import media_generation_enabled

logger = get_logger(__name__)
TPOSE_USE_CASES = ("tpose", "tpose_animal", "tpose_back", "tpose_side", "tpose_animal_view")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_state_lock = threading.RLock()
_attempts = OrderedDict()
_active = {}
_pending = {}
_epochs = {}
_last_expression_time = {}
_EXPRESSION_COOLDOWN = 300
_COALESCE_WINDOW = 10.0


def _safe_name(name):
    return name.replace(" ", "_")


def _get_expressions_dir(name):
    """Read-only path: polling a deleted character cannot recreate it."""
    from app.core.paths import get_storage_dir
    base = get_storage_dir() / "characters"
    folder = base / name / "outfits"
    if Path(name).name != name or base.is_symlink() or folder.parent.is_symlink() or folder.is_symlink():
        raise ValueError("Unsafe expression directory")
    if folder.resolve().parent != (base / name).resolve():
        raise ValueError("Expression directory escapes character storage")
    return folder


def publication_lock(name):
    return keyed_lock("expression_publication", name)


def render_lock(name):
    return keyed_lock("expression_render", name)


def mutation_epoch(name):
    with publication_lock(name):
        return _epochs.get(name, 0)


def invalidate_publication(name):
    """Caller holds publication lock; preserve tombstones across name reuse."""
    with publication_lock(name):
        _epochs[name] = _epochs.get(name, 0) + 1
        with _state_lock:
            for aid, attempt in list(_attempts.items()):
                if attempt.character == name and attempt.state in ("pending", "running"):
                    _finish(aid, "invalidated", error="Expression assets changed")


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ExpressionSnapshot:
    character: str
    set_id: str
    expression_key: str
    outfit_raw: str
    contract: str
    stem: str
    pose_prompt: str
    expression_prompt: str
    pieces: tuple
    items: tuple
    profile: object
    mood: str
    epoch: int


def expression_snapshot(character: str, mood: str = "", *, equipped_pieces=None, equipped_items=None):
    from app.models.character import get_character_profile
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    from app.core.expression_sets import catalog_snapshot, set_for_character, ExpressionSetError
    from app.core.expression_pose_maps import resolve_expression_key
    from app.core.model_refs import outfit_signature_raw
    from app.core.prompt_builder import person_description
    while True:
        with keyed_lock("character_profile", character):
            profile = deepcopy(get_character_profile(character) or {})
            if not profile:
                raise ExpressionSetError("Character not found", 404)
            cat = catalog_snapshot()
            spec = set_for_character(character, profile=profile, catalog=cat)
            pieces = dict(get_equipped_pieces(character) if equipped_pieces is None else equipped_pieces)
            items = list(get_equipped_items(character) if equipped_items is None else equipped_items)
            profile["equipped_pieces"] = pieces
            profile["equipped_items"] = items
            outfit = outfit_signature_raw(pieces, items, character, profile=profile)
            appearance = person_description(character, body_profile=profile, apply_state_modifiers=False, neutral_state=True)
            epoch = mutation_epoch(character)
        expression = resolve_expression_key(mood, set_id=spec.id)
        with keyed_lock("character_profile", character):
            current = dict(get_character_profile(character) or {})
            if not current:
                raise ExpressionSetError("Character was removed during matching", 404)
            latest = catalog_snapshot()
            current_pieces = dict(get_equipped_pieces(character) if equipped_pieces is None else equipped_pieces)
            current_items = list(get_equipped_items(character) if equipped_items is None else equipped_items)
            current["equipped_pieces"], current["equipped_items"] = current_pieces, current_items
            current_set = set_for_character(character, profile=current, catalog=latest)
            current_outfit = outfit_signature_raw(current_pieces, current_items, character, profile=current)
            current_appearance = person_description(character, body_profile=current, apply_state_modifiers=False, neutral_state=True)
            if (latest.revision != cat.revision or current_set.id != spec.id
                    or current_outfit != outfit or current_appearance != appearance
                    or mutation_epoch(character) != epoch):
                continue
        if expression not in spec.members:
            continue
        prompt = cat.entries[expression]["prompt"]
        contract = _digest({"version": 2, "pose_prompt": spec.pose_prompt, "expression_prompt": prompt})
        identity = _digest({"version": 2, "set_id": spec.id, "expression_key": expression, "outfit_raw": outfit, "contract": contract})
        return ExpressionSnapshot(character, spec.id, expression, outfit, contract,
            f"{_safe_name(character)}_{identity[:24]}", spec.pose_prompt, prompt,
            tuple(sorted(pieces.items())), tuple(sorted(set(items))), _freeze(profile), mood, epoch)


def _metadata_matches(meta, request, *, exact=True):
    from app.core.expression_sets import catalog_snapshot
    if not isinstance(meta, dict) or meta.get("schema") != 2 or meta.get("neutral_state") is not True:
        return False
    if meta.get("expression_set") != request.set_id or meta.get("outfit_raw") != request.outfit_raw:
        return False
    cat = catalog_snapshot()
    spec = cat.sets.get(request.set_id)
    key = meta.get("expression_key")
    if spec is None or key not in spec.members or (exact and key != request.expression_key):
        return False
    expected = _digest({"version": 2, "pose_prompt": spec.pose_prompt, "expression_prompt": cat.entries[key]["prompt"]})
    return meta.get("contract") == expected and (not exact or meta.get("identity") == request.stem)


def _cached_unlocked(request):
    from app.core.http_files import content_version
    directory = _get_expressions_dir(request.character)
    sidecar = directory / f"{request.stem}.json"
    if sidecar.is_symlink():
        return None
    try:
        meta = json.loads(sidecar.read_text())
        if not _metadata_matches(meta, request):
            return None
        for ext in _IMAGE_EXTS:
            image = sidecar.with_suffix(ext)
            if image.is_file() and not image.is_symlink() and content_version(image) == meta.get("content_version"):
                return image
    except (OSError, ValueError, TypeError):
        pass
    return None


def get_cached_expression(request):
    with keyed_lock("pose_catalog", "expression"):
        with publication_lock(request.character):
            return _cached_unlocked(request)


def find_compatible_expression(request):
    from app.core.expression_sets import catalog_snapshot
    from app.core.http_files import content_version
    with keyed_lock("pose_catalog", "expression"):
        with publication_lock(request.character):
            exact = _cached_unlocked(request)
            if exact is not None:
                return exact
            spec = catalog_snapshot().sets[request.set_id]
            candidates = []
            for sidecar in _get_expressions_dir(request.character).glob("*.json"):
                if sidecar.is_symlink():
                    continue
                try:
                    meta = json.loads(sidecar.read_text())
                    if not _metadata_matches(meta, request, exact=False):
                        continue
                    for ext in _IMAGE_EXTS:
                        image = sidecar.with_suffix(ext)
                        if image.is_file() and not image.is_symlink() and content_version(image) == meta.get("content_version"):
                            candidates.append(((meta["expression_key"] == spec.default, image.stat().st_mtime_ns, image.name), image))
                            break
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            return max(candidates, key=lambda row: row[0])[1] if candidates else None


@dataclass(frozen=True)
class ExpressionAttempt:
    attempt_id: str
    character: str
    identity: str
    state: str
    epoch: int = 0
    content_version: str = ""
    error: str = ""


def _finish(aid, state, *, version="", error=""):
    with _state_lock:
        attempt = _attempts[aid]
        if attempt.state not in ("pending", "running"):
            return attempt
        _attempts[aid] = replace(attempt, state=state, content_version=version, error=error)
        if state not in ("pending", "running"):
            _attempts.move_to_end(aid)
            if _active.get((attempt.character, attempt.identity)) == aid:
                _active.pop((attempt.character, attempt.identity), None)
            terminal = [key for key, value in _attempts.items() if value.state not in ("pending", "running")]
            for key in terminal[:-512]:
                _attempts.pop(key, None)
        return _attempts[aid]


def get_expression_attempt(character, attempt_id):
    with _state_lock:
        attempt = _attempts.get(attempt_id)
        return attempt if attempt and attempt.character == character else None


def _latest_attempt_unlocked(request):
    return next((a for a in reversed(_attempts.values())
                 if a.character == request.character and a.identity == request.stem
                 and a.epoch == request.epoch), None)


def expression_status(request):
    from app.core.http_files import content_version
    image = get_cached_expression(request)
    fallback = image or find_compatible_expression(request)
    with _state_lock:
        aid = _active.get((request.character, request.stem))
        attempt = _attempts.get(aid)
        failed = _latest_attempt_unlocked(request)
    state = attempt.state if attempt else "ready" if image else "failed" if failed and failed.state == "failed" else "missing"
    return {"identity": request.stem, "state": state,
            "content_version": content_version(image) if image else "",
            "fallback_version": content_version(fallback) if fallback else "",
            "error": failed.error if failed and state == "failed" else ""}


def _register(request):
    with _state_lock:
        active = _active.get((request.character, request.stem))
        if active:
            return _attempts[active], False
        attempt = ExpressionAttempt("expr_" + uuid.uuid4().hex, request.character, request.stem, "pending", epoch=request.epoch)
        _attempts[attempt.attempt_id] = attempt
        _active[(request.character, request.stem)] = attempt.attempt_id
        return attempt, True


def _allowed(request, ignore_feature_gate):
    if not media_generation_enabled():
        return False
    if ignore_feature_gate:
        return True
    from app.models.character_template import is_feature_enabled
    return is_feature_enabled(request.character, "expression_variants_enabled")


def _execute(request, aid, force=False):
    from app.core.http_files import content_version
    with render_lock(request.character):
        attempt = get_expression_attempt(request.character, aid)
        if not attempt or attempt.state not in ("pending", "running"):
            return get_cached_expression(request)
        if mutation_epoch(request.character) != request.epoch:
            _finish(aid, "invalidated", error="Expression assets changed")
            return None
        existing = get_cached_expression(request)
        if existing and not force:
            _finish(aid, "ready", version=content_version(existing))
            return existing
        if not media_generation_enabled():
            _finish(aid, "failed", error="Media generation is disabled")
            return None
        _finish(aid, "running")
        folder = _get_expressions_dir(request.character)
        if not folder.parent.is_dir() or folder.is_symlink():
            _finish(aid, "invalidated", error="Character storage is unavailable")
            return None
        folder.mkdir(exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".expression-", dir=folder) as stage:
                stage = Path(stage)
                rendered = render_character_image(request.character, output_stem=stage / request.stem,
                    equipped_pieces=dict(request.pieces), equipped_items=list(request.items),
                    pose_prompt=request.pose_prompt, expression_prompt=request.expression_prompt,
                    appearance_profile=_thaw(request.profile), apply_state_modifiers=False, neutral_state=True)
                if rendered is None:
                    raise RuntimeError("Expression render failed")
                metadata = json.loads(rendered.with_suffix(".json").read_text())
                for obsolete in ("pose_key", "activity", "state_fingerprint"):
                    metadata.pop(obsolete, None)
                version = content_version(rendered)
                metadata.update(schema=2, expression_set=request.set_id, expression_key=request.expression_key,
                    outfit_raw=request.outfit_raw, contract=request.contract, identity=request.stem,
                    pose_prompt=request.pose_prompt, expression_prompt=request.expression_prompt,
                    neutral_state=True, mood=request.mood,
                    content_version=version, image_sha256=hashlib.sha256(rendered.read_bytes()).hexdigest())
                meta_stage = stage / "publication.json"
                meta_stage.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
                with keyed_lock("character_profile", request.character):
                    with keyed_lock("pose_catalog", "expression"):
                        with publication_lock(request.character):
                            if _epochs.get(request.character, 0) != request.epoch or not folder.is_dir():
                                _finish(aid, "invalidated", error="Expression assets changed during rendering")
                                return None
                            target = folder / rendered.name
                            sidecar = target.with_suffix(".json")
                            old_image = stage / "previous-image"
                            old_meta = stage / "previous-meta"
                            had_image, had_meta = target.exists(), sidecar.exists()
                            if had_image:
                                shutil.copy2(target, old_image)
                            if had_meta:
                                shutil.copy2(sidecar, old_meta)
                            try:
                                os.replace(rendered, target)
                                os.replace(meta_stage, sidecar)
                            except BaseException:
                                if had_image:
                                    os.replace(old_image, target)
                                else:
                                    target.unlink(missing_ok=True)
                                if had_meta:
                                    os.replace(old_meta, sidecar)
                                else:
                                    sidecar.unlink(missing_ok=True)
                                raise
                _finish(aid, "ready", version=version)
                return target
        except Exception as exc:
            logger.exception("Expression render failed for %s", request.character)
            _finish(aid, "failed", error=str(exc))
            return None


def generate_expression_image(request, *, force=False):
    attempt, created = _register(request)
    return _execute(request, attempt.attempt_id, force)


def start_expression_attempt(request, *, force=False, ignore_feature_gate=False):
    from app.core.http_files import content_version
    attempt, created = _register(request)
    if created:
        image = get_cached_expression(request)
        if image and not force:
            return _finish(attempt.attempt_id, "ready", version=content_version(image))
        if not _allowed(request, ignore_feature_gate):
            return _finish(attempt.attempt_id, "failed", error="Expression generation is disabled")
        threading.Thread(target=_execute, args=(request, attempt.attempt_id, force), daemon=True,
                         name=f"expression-{request.character}").start()
    return get_expression_attempt(request.character, attempt.attempt_id)


def trigger_expression_generation(request, *, force=False, ignore_cooldown=False, ignore_feature_gate=False, coalesce=True):
    if not force and get_cached_expression(request):
        return False
    if not _allowed(request, ignore_feature_gate):
        return False
    with _state_lock:
        latest = _latest_attempt_unlocked(request)
        if not force and latest and latest.state == "failed":
            return False
        if not ignore_cooldown and time.monotonic() - _last_expression_time.get(request.character, 0) < _EXPRESSION_COOLDOWN:
            return False
        attempt, created = _register(request)
        if not created:
            return True
        old = _pending.pop(request.character, None)
        if old:
            old[0].cancel()
            _finish(old[1], "superseded", error="A newer expression request replaced this one")
        def fire():
            with _state_lock:
                pending = _pending.get(request.character)
                if coalesce and (not pending or pending[1] != attempt.attempt_id):
                    return
                _pending.pop(request.character, None)
                _last_expression_time[request.character] = time.monotonic()
            _execute(request, attempt.attempt_id, force)
        timer = threading.Timer(_COALESCE_WINDOW if coalesce else 0, fire)
        timer.daemon = True
        _pending[request.character] = (timer, attempt.attempt_id)
        timer.start()
    return True


def delete_expression(character_name, filename):
    folder = _get_expressions_dir(character_name)
    if not filename or Path(filename).name != filename:
        return False
    image = folder / filename
    if image.is_symlink() or image.resolve().parent != folder.resolve():
        return False
    with publication_lock(character_name):
        invalidate_publication(character_name)
        found = False
        for path in (image, image.with_suffix(".json")):
            if path.is_symlink():
                raise ValueError("Expression symlinks cannot be deleted through the image API")
            if path.is_file():
                path.unlink()
                found = True
        return found


def clear_expression_cache(character_name):
    folder = _get_expressions_dir(character_name)
    with publication_lock(character_name):
        invalidate_publication(character_name)
        if not folder.is_dir() or folder.is_symlink():
            return 0
        files = [p for p in folder.iterdir() if p.is_file() and not p.is_symlink() and p.suffix in (*_IMAGE_EXTS, ".json")]
        for path in files:
            path.unlink()
        return len(files)


def list_expressions(character_name):
    from app.core.expression_cleanup import inventory
    return inventory(character_name)


def invalidate_variants_for_item(item_id):
    from app.models.character import list_available_characters
    removed = 0
    if not item_id:
        return removed
    for name in list_available_characters():
        _invalidate_outfit_caches_for_item(name, item_id)
        with publication_lock(name):
            invalidate_publication(name)
            for sidecar in _get_expressions_dir(name).glob("*.json"):
                if sidecar.is_symlink():
                    continue
                try:
                    meta = json.loads(sidecar.read_text())
                except (OSError, ValueError):
                    continue
                if item_id not in (meta.get("equipped_pieces") or {}).values() and item_id not in (meta.get("equipped_items") or []):
                    continue
                for ext in _IMAGE_EXTS:
                    image = sidecar.with_suffix(ext)
                    if image.is_file() and not image.is_symlink():
                        image.unlink()
                        removed += 1
                sidecar.unlink()
    return removed


def _equipped_signature(equipped_pieces: Optional[Dict[str, str]] = None,
                        equipped_items: Optional[list] = None) -> str:
    """Stable signature of the worn items (pieces + other equipment).

    Slot order is sorted so the same equip set always produces the same hash;
    items alphabetically.
    """
    parts = []
    if equipped_pieces:
        # Normalise to the VISIBLE subset (user finding 2026-07-27): a slot
        # fully hidden via `covers` does not change the image, so covered
        # variants collapse onto one signature — one render, one cache entry,
        # for the batch and the live outfit-change trigger alike. Sets
        # without covered pieces hash exactly as before, existing cache
        # entries stay valid.
        try:
            from app.core.outfit_renderer import visible_equipped_pieces
            equipped_pieces = visible_equipped_pieces(equipped_pieces)
        except Exception:
            pass  # unreadable items must not break signing — hash raw then
        for slot in sorted(equipped_pieces.keys()):
            iid = (equipped_pieces[slot] or "").strip()
            if iid:
                parts.append(f"{slot}={iid}")
    if equipped_items:
        cleaned = sorted({(i or "").strip() for i in equipped_items if i})
        if cleaned:
            parts.append("items:" + ",".join(cleaned))
    return "|".join(parts)

def _invalidate_outfit_caches_for_item(character_name: str, item_id: str) -> Set[str]:
    """Drops the reference renders and meshes of one character that were made
    with this item, and re-arms the outfit render when the WORN combination
    was among them.

    Both caches key on ``model_refs.outfit_signature`` (item IDs), so they
    cannot notice an edited ``prompt_fragment`` by themselves — see
    ``invalidate_variants_for_item``. Returns the purged signatures.
    """
    from app.core.model3d import invalidate_models_for_item
    from app.core.model_refs import (current_outfit_state,
                                     invalidate_refs_for_item,
                                     neutral_signature, schedule_outfit_render)
    purged: Set[str] = set()
    purged |= invalidate_refs_for_item(character_name, item_id)
    purged |= invalidate_models_for_item(character_name, item_id)
    if not purged:
        return purged
    try:
        worn = current_outfit_state(character_name)[2]
    except Exception:  # noqa: BLE001 — an unreadable state only costs the
        return purged  # re-arm; the entries are gone either way
    if neutral_signature(worn) in {neutral_signature(s) for s in purged}:
        schedule_outfit_render(character_name)
    return purged

def render_character_image(character_name: str, *, output_stem: Path,
                           equipped_pieces: Dict[str, str],
                           equipped_items: list, pose_prompt: str,
                           expression_prompt: str, prompt_prefix: str = "",
                           image_use_case: str = "expression",
                           override_width: Optional[int] = None,
                           override_height: Optional[int] = None,
                           apply_state_modifiers: bool = True,
                           neutral_state: bool = False,
                           appearance_profile: Optional[Dict[str, Any]] = None,
                           back_view: bool = False,
                           reference_image: Optional[Path] = None,
                           occasion: str = "", record_provenance: bool = False,
                           bare_prompt: Optional[str] = None,
                           mesh_input_profile: Optional[Dict[str, Any]] = None,
                           backend: str = "", dialog_loras: Optional[list] = None,
                           negative_prompt: str = "") -> Optional[Path]:
    """Render explicit content to a caller-owned stem, without expression policy.

    Reference callers retain their own prompts, state and provenance policy.
    Ordinary expressions pass a frozen neutral profile and publish separately.
    """
    from app.core.dependencies import get_skill_manager
    from app.models.character import (
        get_character_appearance,
        get_character_images_dir,
        postprocess_outfit_image)
    from app.core.outfit_renderer import render_outfit

    # Load the equipped state if it was not handed in
    if equipped_pieces is None or equipped_items is None:
        try:
            from app.models.inventory import get_equipped_pieces, get_equipped_items
            if equipped_pieces is None:
                equipped_pieces = get_equipped_pieces(character_name)
            if equipped_items is None:
                equipped_items = get_equipped_items(character_name)
        except Exception:
            equipped_pieces = equipped_pieces or {}
            equipped_items = equipped_items or []

    _occasion = occasion or ("tpose" if image_use_case in TPOSE_USE_CASES else "expression")
    _mesh_input = _occasion in ("tpose", "tpose_view")

    # Outfit text via the central renderer (plan §4). equipped_pieces/items
    # are passed in so set previews work (override against the profile state).
    from app.models.character import get_character_profile as _gcp_render
    _render_profile = (appearance_profile if appearance_profile is not None else
                       mesh_input_profile if _mesh_input and mesh_input_profile is not None
                       else _gcp_render(character_name) or {})
    _render_profile = dict(_render_profile)
    _render_profile["equipped_pieces"] = dict(equipped_pieces or {})
    _render_profile["equipped_items"] = list(equipped_items or [])
    _rendered = {} if bare_prompt is not None else render_outfit(
        profile=_render_profile,
        equipped_pieces=equipped_pieces,
        equipped_items=equipped_items,
        back_view=back_view,
        mesh_input=_mesh_input,
    )
    outfit_desc = _rendered.get("pieces", "")
    items_desc = _rendered.get("items", "")
    _fallback_text = _rendered.get("fallback", "")
    # Free-text wardrobe: a template without an outfit system (a temporary
    # NPC) is dressed by the profile's `outfit_description` alone, and
    # render_outfit puts that text into `full` ONLY — the three keys above
    # are empty. Without this the T-pose reference render, and therefore the
    # 3D mesh built from it, would show an undressed figure. Taken only when
    # nothing is equipped, so a real wardrobe can never be overridden; the
    # `wearing: ` prefix is stripped because the outfit layer below supplies
    # its own "is wearing".
    if not outfit_desc and not items_desc and not (equipped_pieces or equipped_items):
        _free_text = _rendered.get("full", "") or ""
        if _free_text.startswith("wearing: "):
            outfit_desc = _free_text[len("wearing: "):].strip()

    _state_fp = ""
    if apply_state_modifiers:
        from app.core.model_refs import state_fingerprint
        _state_fp = state_fingerprint(character_name)
    from app.core.prompt_builder import PromptBuilder

    if bare_prompt is not None:
        appearance, actor_label = "", character_name
    else:
        _expr_builder = PromptBuilder(character_name,
                                      apply_state_modifiers=apply_state_modifiers,
                                      back_view=back_view, mesh_input=_mesh_input,
                                      neutral_state=neutral_state,
                                      body_profile=_render_profile)
        persons = _expr_builder.detect_persons("", character_names=[character_name])
        appearance = persons[0].appearance if persons else get_character_appearance(character_name)
        actor_label = persons[0].actor_label if persons else character_name

    # Prompt prefix: only passed for an explicit preview (wardrobe); it stays
    # empty for automatic expression regens.
    _prompt_prefix = (prompt_prefix or "").strip()

    # Separate prompts: prefix, character (appearance), outfit, pose, expression
    character_prompt = f"{actor_label}, {appearance}"
    # outfit_desc / items_desc / _fallback_text come from render_outfit()
    # above — single source in app.core.outfit_renderer (plan §4).

    # "is wearing" only when at least one piece slot is filled.
    if outfit_desc:
        if _fallback_text:
            outfit_prompt = f"{_fallback_text}, {actor_label} is wearing {outfit_desc}"
        else:
            outfit_prompt = f"{actor_label} is wearing {outfit_desc}"
    else:
        outfit_prompt = _fallback_text

    # Equipped non-piece items (spells, tools, ...) get their own phrase, so
    # prompt_fragment="holding a glowing recall stone" reads as
    # "{actor} holding a glowing recall stone", not as "is wearing".
    if items_desc:
        if outfit_prompt:
            outfit_prompt = f"{outfit_prompt}. {actor_label} {items_desc}"
        else:
            outfit_prompt = f"{actor_label} {items_desc}"

    # Core image service (wave-6 split)
    from app.imagegen.service import get_image_service
    image_skill = get_image_service()
    if not image_skill.enabled:
        logger.warning("image service not available")
        return None

    # The backend is resolved inside the image service by the image routing:
    # the character's own match (tpose_workflow, else workflow, for the
    # T-pose occasion) is position 0, then the occasion chain; a failed
    # backend re-runs the render on the next entry.

    # Read the per-character override early — allows model/LoRA overrides
    # per character (configurable in the character editor). The render match
    # itself (workflow / tpose_workflow) is read by the image routing.
    model_override = ""
    loras_override = None
    try:
        from app.models.character import get_character_profile as _gcp
        _prof = _render_profile
        _char_override = _prof.get("outfit_imagegen") or {}
        if isinstance(_char_override, dict):
            m = (_char_override.get("model") or "").strip()
            l = _char_override.get("loras")
            if m:
                model_override = m
            if isinstance(l, list):
                loras_override = l
            # why: the T-pose match may route to a different backend with its
            # own LoRA ecosystem (e.g. a pose/turnaround LoRA), so this list
            # REPLACES the normal per-character one for those renders instead
            # of merging. Empty = the normal LoRAs apply. It follows the
            # OCCASION like the backend does; the default-pose wardrobe ref
            # uses "expression" and keeps the normal character LoRAs.
            _tpose_loras = _char_override.get("tpose_loras")
            if (isinstance(_tpose_loras, list) and _tpose_loras
                    and _occasion in ("tpose", "tpose_view")):
                loras_override = _tpose_loras
    except Exception as _err:
        logger.debug("Reading the outfit imagegen override failed: %s", _err)

    # Resolution from admin config (image_generation.outfit_image_width/height)
    # — expression variants use the same resolution as wardrobe outfit images.
    # An explicit override wins (the T-pose needs a wider frame than the
    # portrait format). The env bridge always sets both; the fallback is the
    # schema default, the same value the bridge uses for an absent field.
    outfit_w = override_width or int(os.environ.get(
        "OUTFIT_IMAGE_WIDTH", field_default("image_generation", "outfit_image_width")) or 0) or None
    outfit_h = override_height or int(os.environ.get(
        "OUTFIT_IMAGE_HEIGHT", field_default("image_generation", "outfit_image_height")) or 0) or None

    # Single prompt: prefix + character + outfit + pose + expression in one string
    parts = [_prompt_prefix, character_prompt]
    if outfit_prompt:
        parts.append(outfit_prompt)
    parts.append(pose_prompt)
    parts.append(expression_prompt)
    full_prompt = bare_prompt if bare_prompt is not None else ", ".join(p for p in parts if p)
    payload = {
        "prompt": full_prompt,
        "input": full_prompt,
        "agent_name": character_name,
        "user_id": "",
        "set_profile": False,
        "skip_gallery": True,
        "auto_enhance": False,
        "occasion": _occasion,
        "equipped_pieces_override": equipped_pieces or {},
        # Profile image as input_reference_image_1 (identity consistency).
        # profile_only prevents the self-reference loop via an already
        # existing variant. Backends without ref slots ignore it.
        "profile_only": True,
        "appearances": [{"name": character_name, "appearance": appearance or ""}],
    }
    if reference_image is not None:
        payload["reference_image_override"] = str(reference_image)

    if outfit_w:
        payload["override_width"] = outfit_w
    if outfit_h:
        payload["override_height"] = outfit_h

    if backend:
        payload["backend"] = backend
        # The stored model belongs to the character's OWN backend match; on
        # another explicit pick it would name a model that backend lacks.
        from app.imagegen.routing import is_character_match
        if model_override and not is_character_match(_occasion, character_name, backend):
            model_override = ""
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if model_override:
        payload["model_override"] = model_override
    # LoRAs: character override + slot-override LoRAs of ACTIVE (empty,
    # uncovered) slots from render_outfit. Character override first, dedup by name.
    _merged_loras = list(loras_override or [])
    _have = {str(l.get("name")) for l in _merged_loras if isinstance(l, dict)}
    for _sl in (_rendered.get("loras") or []):
        if str(_sl.get("name")) not in _have:
            _merged_loras.append(_sl)
            _have.add(str(_sl.get("name")))
    if _mesh_input:
        from app.core.body_slots import filter_mesh_input_loras
        _merged_loras = filter_mesh_input_loras(_merged_loras, _render_profile)
    if dialog_loras is not None:
        # Picked in the dialog for THIS render: the gate rejects an
        # unassociated LoRA on an explicit backend instead of dropping it.
        if dialog_loras:
            payload["loras"] = list(dialog_loras)
            payload["loras_explicit"] = True
    elif _merged_loras and bare_prompt is None:
        payload["loras"] = _merged_loras
    payload["image_use_case"] = image_use_case
    # Fabric only exists in the picture when something is actually worn —
    # pieces or the free-text wardrobe, both of which land in outfit_desc.
    # An undressed character would otherwise be rendered against a style
    # that asks for fabric textures, and the model duly invents cloth.
    payload["clothed"] = bool(outfit_desc)

    provenance_workspace = None
    try:
        if record_provenance:
            import tempfile
            from app.core.model_refs import checked_reference_override, get_model_refs_dir
            checked = checked_reference_override(character_name, str(reference_image or ""))
            if not checked:
                raise ValueError("Provenance requires a valid explicit reference image")
            # A private immutable copy is what every backend attempt reads.
            # Keep it inside model_refs so the service's containment gate applies.
            reference_bytes = Path(checked).read_bytes()
            reference_sha256 = hashlib.sha256(reference_bytes).hexdigest()
            provenance_workspace = tempfile.TemporaryDirectory(
                prefix=".provenance_", dir=get_model_refs_dir(character_name))
            workspace = Path(provenance_workspace.name)
            frozen_reference = workspace / ("reference" + Path(checked).suffix)
            frozen_reference.write_bytes(reference_bytes)
            payload["reference_image_override"] = str(frozen_reference)
            payload["record_provenance"] = True
        img_result = image_skill.generate_from_input(json.dumps(payload))

        # Extract filename from result
        match = re.search(r'/images/([^?)\n]+)', img_result)
        if not match:
            logger.warning("Could not extract the file name: %s", img_result[:200])
            return None

        image_filename = match.group(1)
        images_dir = get_character_images_dir(character_name)
        src_path = images_dir / image_filename

        if not src_path.exists():
            logger.warning("Generated image not found: %s", src_path)
            return None

        # Post-process (rembg + crop) in a temporary path, then move into
        # place — prevents the frontend from picking up the unprocessed
        # image via polling. With output_stem the target is the model_refs
        # location instead of the expression-variant cache.
        out_dir = output_stem.parent
        out_stem_name = output_stem.name
        if out_dir.parent.is_dir():
            out_dir.mkdir(exist_ok=True)
        if not out_dir.is_dir():
            # The character was deleted during the render: drop the result
            # instead of recreating its directory as a ghost.
            src_path.unlink(missing_ok=True)
            logger.warning("Expression render for %s discarded: %s is gone",
                           character_name, out_dir)
            return None
        # Provenance renders own their staging files; overlapping renders must
        # never postprocess, hash or clean up another publication's bytes.
        staging_dir = workspace if record_provenance else out_dir
        tmp_path = staging_dir / f".tmp_{out_stem_name}{src_path.suffix}"
        shutil.move(str(src_path), str(tmp_path))

        try:
            final_tmp = postprocess_outfit_image(tmp_path, mesh_input=_mesh_input)
        except Exception as pp_err:
            logger.warning("Post-processing failed, using the original: %s", pp_err)
            final_tmp = tmp_path

        if image_use_case == "face_view":
            # This per-character asset has a fixed PNG filename, including when
            # background removal falls back to a backend's JPEG/WebP output.
            from PIL import Image
            png_path = staging_dir / ".face_view.png"
            with Image.open(final_tmp) as image:
                image.save(png_path, "PNG")
            if final_tmp != tmp_path:
                final_tmp.unlink(missing_ok=True)
            final_tmp = png_path

        if record_provenance:
            image_sha256 = hashlib.sha256(final_tmp.read_bytes()).hexdigest()

        # Rename atomically into the target path
        final_path = out_dir / f"{out_stem_name}{final_tmp.suffix}"
        if output_stem is not None:
            # Fixed stem: drop a stale ref with a different extension
            # (e.g. old tpose.jpg being replaced by tpose.png).
            for _old in out_dir.glob(f"{out_stem_name}.*"):
                if _old.suffix.lower() != ".json" and _old != final_path:
                    _old.unlink()
        final_tmp.rename(final_path)
        # Clean up the temp file if the suffix changed (e.g. .jpg -> .png)
        if tmp_path != final_tmp and tmp_path.exists():
            tmp_path.unlink()


        # Metadata JSON next to the image. equipped_pieces/items are recorded
        # so invalidate_variants_for_item can delete exactly the variants that
        # actually contained the changed item. The generation meta is read
        # thread-locally — prevents collisions when expression regens for
        # different characters run in parallel.
        _tls = getattr(image_skill, '_meta_tls', None)
        _gen_meta = getattr(_tls, 'last_image_meta', None) if _tls is not None else None
        if _gen_meta is None:
            _gen_meta = getattr(image_skill, 'last_image_meta', {}) or {}
        from app.core.model_refs import mesh_variant
        _expr_meta = {
            **({"mesh_variant": mesh_variant(character_name, equipped_pieces, _render_profile)} if _mesh_input else {}),
            "provider": _gen_meta.get("backend_type", ""),
            "service": _gen_meta.get("backend", ""),
            "model": _gen_meta.get("model", ""),
            "loras": _gen_meta.get("loras", []),
            "prompt": full_prompt,
            "negative_prompt": _gen_meta.get("negative_prompt", ""),
            "characters": [character_name],
            "reference_images": _gen_meta.get("reference_images", {}),
            "seed": _gen_meta.get("seed", 0),
            "created_at": _gen_meta.get("created_at", ""),
            "duration_s": _gen_meta.get("duration_s", 0),
            "mood": "",
            "expression_key": "",
            "activity": "",
            "pose_key": "",
            "equipped_pieces": equipped_pieces or {},
            "equipped_items": equipped_items or [],
            "state_fingerprint": _state_fp,
        }
        # The routing record of the render — a fallback variant stays
        # recognisable (plan-image-routing.md, meta at every writer).
        for _rk in ("routing", "fallback_from"):
            if _gen_meta.get(_rk):
                _expr_meta[_rk] = _gen_meta[_rk]
        if record_provenance:
            _expr_meta.update(reference_sha256=reference_sha256,
                              image_sha256=image_sha256)
            if bare_prompt is not None:
                _expr_meta["profile_image"] = reference_image.name
        try:
            _meta_path = final_path.with_suffix(".json")
            if record_provenance:
                # Readers may see an interleaved image/sidecar pair, but its
                # image hash must fail rather than certify another render.
                staged_meta = workspace / "sidecar.json"
                staged_meta.write_text(json.dumps(_expr_meta, ensure_ascii=False, indent=2), encoding="utf-8")
                staged_meta.rename(_meta_path)
            else:
                _meta_path.write_text(json.dumps(_expr_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as _me:
            logger.warning("Writing the expression meta failed: %s", _me)

        logger.info("Expression image generated: %s", final_path.name)


        return final_path

    except Exception as e:
        logger.error("Expression generation failed: %s", e)
        return None
    finally:
        if provenance_workspace is not None:
            provenance_workspace.cleanup()


@contextmanager
def expression_import_scope(character, archive):
    """Validate selection before destructive import and isolate directory replacement."""
    from app.core.expression_sets import catalog_snapshot, ExpressionSetError
    from app.core.pose_catalog_edit import catalog_txn
    try:
        rows = json.loads(archive.read("db/characters.json"))
        row = next(row for row in rows if row.get("name") == character)
        profile = json.loads(row.get("profile_json") or "{}")
    except (KeyError, ValueError, TypeError, StopIteration) as exc:
        raise ValueError("Character archive has no valid character profile") from exc
    selected = str(profile.get("expression_set") or "")
    if selected and selected not in catalog_snapshot().sets:
        raise ExpressionSetError(f"Unknown imported expression set '{selected}'")
    with render_lock(character), keyed_lock("character_profile", character), catalog_txn("expression"), publication_lock(character):
        if selected and selected not in catalog_snapshot().sets:
            raise ExpressionSetError(f"Imported expression set '{selected}' changed")
        invalidate_publication(character)
        yield
