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

TPOSE_PROMPT_DEFAULT = (
    "full body T-pose, standing upright facing the camera, arms stretched "
    "straight out horizontally to both sides, palms down, fingers extended, "
    "legs straight and slightly apart, neutral relaxed face, even lighting"
)

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


def find_ref_image(character_name: str, kind: str) -> Optional[Path]:
    """Path of the stored reference render of the given kind, or None."""
    if kind not in REF_KINDS:
        return None
    from app.models.character import get_character_dir
    refs_dir = get_character_dir(character_name) / "model_refs"
    for ext in _IMAGE_EXTS:
        p = refs_dir / f"{kind}{ext}"
        if p.exists():
            return p
    return None


def get_model_refs_info(character_name: str) -> Dict[str, Any]:
    """Per-kind info for the UI: filename + sidecar meta (or None)."""
    import json
    from app.models.character import get_character_dir
    refs_dir = get_character_dir(character_name) / "model_refs"
    out: Dict[str, Any] = {}
    for kind in REF_KINDS:
        path = find_ref_image(character_name, kind)
        if not path:
            out[kind] = None
            continue
        info: Dict[str, Any] = {"filename": path.name}
        meta_path = refs_dir / f"{kind}.json"
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
                              kinds: Optional[tuple] = None) -> Dict[str, Optional[str]]:
    """Render the reference images sequentially (the image queue serializes
    per backend anyway). Blocking — call from a worker thread.

    ``kinds`` None = exactly what the automatic outfit-change trigger would
    render: the kinds enabled via the per-character toggles."""
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
                pose_prompt_override=prompts[kind],
                include_expression=False,
                image_use_case="outfit",
                output_stem=refs_dir / kind)
            results[kind] = str(path) if path else None
            if path is None:
                error = f"{kind} render failed"
        logger.info("Model-Refs fuer %s: %s", character_name,
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


def _run_generation(character_name: str) -> None:
    # Serial per character; the equipped state is read at run time inside
    # generate_expression_image, so the latest outfit always wins.
    with _char_lock(character_name):
        try:
            generate_model_ref_images(character_name)
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
    immediately — same per-image toggles, just without the debounce."""
    with _lock:
        old = _pending_timers.pop(character_name, None)
        if old:
            old.cancel()
    threading.Thread(target=_run_generation, args=[character_name],
                     daemon=True).start()
