"""Character reference renders for the 3D pipeline (T-pose + default pose).

After every outfit change (equip/unequip of a piece, outfit switch) a
DEBOUNCED trigger renders two full-body reference images of the character in
the CURRENT outfit: one in T-pose (the input for image->3D/rigging chains)
and one in the default pose. Both live under characters/<name>/model_refs/,
deliberately separate from the expression-variant cache.

Debounce: getting fully dressed equips several pieces in quick succession —
each mutation resets a per-character timer (trailing edge, latest state
wins), so one render pair fires at the end instead of one per piece. The
window and the on/off switch are admin config (image_generation.*), read
fresh on every call. Rendering itself reuses generate_expression_image()
(appearance + current outfit composer, profile-image identity reference,
image queue with per-backend serialization).
"""

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

# Prompt layering: this default is PURE POSE — framing, lighting and
# background come from the "outfit" use-case style, the face from the
# expression layer (REF_EXPRESSION_PROMPT below). Keep it that way.
TPOSE_PROMPT_DEFAULT = (
    "T-pose, standing upright facing the camera, arms stretched straight "
    "out horizontally to both sides, palms down, fingers extended, legs "
    "straight and slightly apart"
)

# Expression layer of both reference renders: deliberately neutral (the
# character presets default to expressive looks, which would bake into 3D
# textures). Verbatim expression content, no style fragments.
REF_EXPRESSION_PROMPT = "neutral relaxed facial expression"

REF_KINDS = ("tpose", "pose")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

_lock = threading.Lock()
_pending_timers: Dict[str, threading.Timer] = {}
_char_locks: Dict[str, threading.Lock] = {}


def _cfg(key: str, default: Any = None) -> Any:
    from app.core import config
    return config.get(f"image_generation.{key}", default)


def get_tpose_prompt() -> str:
    """T-pose prompt: admin override (image_generation.tpose_prompt) or built-in."""
    override = str(_cfg("tpose_prompt", "") or "").strip()
    return override or TPOSE_PROMPT_DEFAULT


def _enabled() -> bool:
    val = _cfg("model_ref_renders_enabled", True)
    return bool(True if val is None else val)


def _debounce_seconds() -> float:
    try:
        val = int(_cfg("model_ref_debounce_seconds", 0) or 0)
    except (TypeError, ValueError):
        val = 0
    return float(val) if val > 0 else 60.0


def get_auto_kinds(character_name: str) -> Dict[str, bool]:
    """Per-character, per-image toggles for the automatic outfit-change
    render (profile field ``model_ref_auto``; missing key = enabled)."""
    from app.models.character import get_character_profile
    try:
        raw = (get_character_profile(character_name) or {}).get("model_ref_auto") or {}
    except Exception:
        raw = {}
    return {k: bool(raw.get(k, True)) for k in REF_KINDS}


def set_auto_kinds(character_name: str, updates: Dict[str, Any]) -> Dict[str, bool]:
    """Merges per-image auto-render toggles into the character profile."""
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile(character_name) or {}
    current = profile.get("model_ref_auto") or {}
    merged = {k: bool(current.get(k, True)) for k in REF_KINDS}
    for key, val in (updates or {}).items():
        if key in REF_KINDS:
            merged[key] = bool(val)
    profile["model_ref_auto"] = merged
    save_character_profile(character_name, profile)
    return merged


def get_model_refs_dir(character_name: str) -> Path:
    """Reference-render directory (see get_character_images_dir for the
    base-dir existence gate that avoids ghost dirs on read paths)."""
    from app.models.character import get_character_dir
    base = get_character_dir(character_name)
    refs_dir = base / "model_refs"
    if base.exists():
        refs_dir.mkdir(parents=True, exist_ok=True)
    return refs_dir


def _current_outfit_state(character_name: str) -> tuple:
    """(equipped_pieces, equipped_items, signature) of the CURRENT worn
    state. The signature reuses the expression cache's equipped-signature
    (pieces + items, stably sorted) so both caches agree on what counts as
    "the same outfit combination"."""
    import hashlib
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    from app.core.expression_regen import _equipped_signature
    pieces = get_equipped_pieces(character_name)
    items = get_equipped_items(character_name)
    sig = hashlib.md5(_equipped_signature(pieces, items).encode()).hexdigest()[:12]
    return pieces, items, sig


def find_ref_image(character_name: str, kind: str,
                   signature: Optional[str] = None) -> Optional[Path]:
    """Path of the stored render of this kind for the given outfit
    combination (default: the currently worn one), or None."""
    if kind not in REF_KINDS:
        return None
    if signature is None:
        try:
            _, _, signature = _current_outfit_state(character_name)
        except Exception:
            return None
    from app.models.character import get_character_dir
    refs_dir = get_character_dir(character_name) / "model_refs"
    for ext in _IMAGE_EXTS:
        p = refs_dir / f"{kind}_{signature}{ext}"
        if p.exists():
            return p
    return None


def _cleanup_legacy(refs_dir: Path, kind: str) -> None:
    """Drops leftovers of the retired fixed-name scheme ({kind}.ext). The
    per-combination cache itself is NOT pruned — its size is naturally
    bounded by the number of outfit combinations actually worn."""
    for ext in _IMAGE_EXTS + (".json",):
        legacy = refs_dir / f"{kind}{ext}"
        if legacy.exists():
            legacy.unlink()


def get_model_refs_info(character_name: str) -> Dict[str, Any]:
    """Per-kind info for the UI — always for the CURRENTLY worn outfit
    combination (filename + sidecar meta, or None if not rendered yet)."""
    import json
    try:
        _, _, signature = _current_outfit_state(character_name)
    except Exception:
        signature = ""
    out: Dict[str, Any] = {"signature": signature}
    for kind in REF_KINDS:
        path = find_ref_image(character_name, kind, signature) if signature else None
        if not path:
            out[kind] = None
            continue
        info: Dict[str, Any] = {"filename": path.name}
        meta_path = path.with_suffix(".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                info["created_at"] = meta.get("created_at", "")
                info["prompt"] = meta.get("prompt", "")
                info["backend"] = meta.get("service", "")
            except (OSError, ValueError):
                pass
        out[kind] = info
    out["auto"] = get_auto_kinds(character_name)
    with _lock:
        out["pending"] = character_name in _pending_timers
    return out


def generate_model_ref_images(character_name: str,
                              kinds: Optional[tuple] = None,
                              force: bool = False) -> Dict[str, Optional[str]]:
    """Render the reference images sequentially (the image queue serializes
    per backend anyway). Blocking — call from a worker thread.

    Cached per outfit combination: kinds whose render for the CURRENT
    combination already exists are skipped unless ``force`` — switching
    back to a known outfit costs no GPU run. ``kinds`` None = exactly what
    the automatic outfit-change trigger would render (per-character
    toggles)."""
    from app.core.expression_regen import generate_expression_image
    from app.core.expression_pose_maps import default_pose_prompt
    from app.core.task_queue import get_task_queue

    if kinds is None:
        auto = get_auto_kinds(character_name)
        kinds = tuple(k for k in REF_KINDS if auto.get(k))
    else:
        kinds = tuple(k for k in kinds if k in REF_KINDS)
    if not kinds:
        return {}

    pieces, items, signature = _current_outfit_state(character_name)
    if not force:
        cached = tuple(k for k in kinds
                       if find_ref_image(character_name, k, signature))
        if cached:
            logger.info("Model-Refs fuer %s: Kombination %s bereits gerendert (%s)",
                        character_name, signature, ", ".join(cached))
        kinds = tuple(k for k in kinds if k not in cached)
    if not kinds:
        return {}

    refs_dir = get_model_refs_dir(character_name)
    prompts = {"tpose": get_tpose_prompt(), "pose": default_pose_prompt()}
    results: Dict[str, Optional[str]] = {}

    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model_ref_render", f"3D refs: {character_name}",
            agent_name=character_name, start_running=True)
    except Exception:
        pass
    error = ""
    try:
        for kind in kinds:
            path = generate_expression_image(
                character_name, mood="", activity="",
                equipped_pieces=pieces, equipped_items=items,
                pose_prompt_override=prompts[kind],
                expression_prompt_override=REF_EXPRESSION_PROMPT,
                # tpose has its own style (flat shadowless light for
                # image->3D input); the default-pose ref shares "outfit".
                image_use_case="tpose" if kind == "tpose" else "outfit",
                output_stem=refs_dir / f"{kind}_{signature}")
            results[kind] = str(path) if path else None
            if path is None:
                error = f"{kind} render failed"
            else:
                _cleanup_legacy(refs_dir, kind)
        logger.info("Model-Refs fuer %s (%s): %s", character_name, signature,
                    {k: bool(v) for k, v in results.items()})
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass
    return results


def _char_lock(character_name: str) -> threading.Lock:
    with _lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def _run_generation(character_name: str, force: bool = False) -> None:
    # Serial per character; the equipped state is read at run time, so the
    # latest outfit always wins.
    with _char_lock(character_name):
        try:
            generate_model_ref_images(character_name, force=force)
        except Exception as e:
            logger.error("Model-Ref-Render fuer %s fehlgeschlagen: %s",
                         character_name, e)


def _fire(character_name: str) -> None:
    with _lock:
        _pending_timers.pop(character_name, None)
    threading.Thread(target=_run_generation, args=[character_name],
                     daemon=True).start()


def schedule_outfit_render(character_name: str) -> None:
    """Debounced trigger after an outfit mutation (trailing edge, latest
    state wins). No-op when disabled in config or when every per-image
    toggle of this character is off."""
    if not _enabled():
        return
    if not any(get_auto_kinds(character_name).values()):
        return
    delay = _debounce_seconds()
    with _lock:
        old = _pending_timers.pop(character_name, None)
        if old:
            old.cancel()
        timer = threading.Timer(delay, _fire, args=[character_name])
        timer.daemon = True
        _pending_timers[character_name] = timer
        timer.start()


def trigger_now(character_name: str) -> None:
    """Manual trigger (UI button): fires the automatic outfit-change render
    immediately — same per-image toggles, no debounce, and force=True so a
    fresh render replaces the cached one of the current combination."""
    with _lock:
        old = _pending_timers.pop(character_name, None)
        if old:
            old.cancel()
    threading.Thread(target=_run_generation, args=[character_name, True],
                     daemon=True).start()
