"""Rendered-scene pipeline — composes the environment view (room background
+ present characters) into ONE generated image, shown by the player UI's
"Rendered" toggle in the environment panel (plan-scene-live-rendering.md).

Follows the event_images pattern: the backend comes from the config glob
``image_generation.scene_imagegen_default`` (fallback: location default,
then cheapest available), the prompt is styled via use case ``scene``, the
current room background goes into reference slot 1 and the present
characters' expression images fill the remaining slots (capped by the
backend's ref_slot_count). Results are cached per scene signature —
(location, room, background file, present characters + expression images,
coarse position buckets) — under ``worlds/<w>/scene_render/``.

Rendering is manual-only (player button); ``force=True`` bypasses the
cache with a fresh seed and overwrites the signature file.
"""
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import config
from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.core.timeutils import utc_now

logger = get_logger("scene_render")


def get_scene_dir() -> Path:
    d = get_storage_dir() / "scene_render"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_scene_image_path(sig: str) -> Path:
    return get_scene_dir() / f"{sig}.png"


def _resolve_backend():
    """Backend via ``scene_imagegen_default`` glob; falls back to the
    location default, then to the cheapest available backend."""
    try:
        from app.core.dependencies import get_skill_manager
    except Exception:
        return None
    sm = get_skill_manager()
    img_skill = sm.get_skill("image_generation") if sm else None
    if not img_skill:
        return None
    default = (str(config.get("image_generation.scene_imagegen_default", "") or "").strip()
               or str(config.get("image_generation.location_imagegen_default", "") or "").strip())
    backend = img_skill.resolve_imagegen_target(default)
    if not backend:
        backend = img_skill._select_backend()
    return backend


def _expr_image_path(name: str) -> Optional[Path]:
    """Current expression/variant image of a character — same lookup as the
    /outfit-expression route (mood + effective activity + real equipped
    state); falls back to the profile image."""
    try:
        from app.core.expression_regen import get_cached_expression
        from app.models.character import (get_character_current_feeling,
                                          get_effective_activity)
        from app.models.inventory import get_equipped_items, get_equipped_pieces
        mood = get_character_current_feeling(name) or ""
        activity = get_effective_activity(name) or ""
        cached = get_cached_expression(
            name, mood, activity,
            equipped_pieces=get_equipped_pieces(name),
            equipped_items=get_equipped_items(name))
        if cached and Path(cached).exists():
            return Path(cached)
    except Exception as e:
        logger.debug("scene: expression lookup failed for %s: %s", name, e)
    try:
        from app.models.character import (get_character_images_dir,
                                          get_character_profile_image)
        profile = get_character_profile_image(name)
        if profile:
            p = get_character_images_dir(name) / profile
            if p.exists():
                return p
    except Exception as e:
        logger.debug("scene: profile image lookup failed for %s: %s", name, e)
    return None


def _pose_hint(name: str) -> str:
    """Compact pose/activity hint for the scene prompt.

    The raw pose_intent is often a whole RP paragraph (the tool LLM copies
    prose into SetPose) — useless as an image hint. Preference: a short
    effective activity as-is (covers "Sleeping" etc.), else the stored pose
    variant's canonical form (normalize_pose result, short + English, no
    extra LLM call), else the first sentence hard-trimmed with quoted
    speech removed.
    """
    import re
    from app.models.character import get_character_profile, get_effective_activity
    act = (get_effective_activity(name) or "").strip()
    if act and len(act) <= 60 and "\n" not in act:
        return act
    try:
        variant_id = (get_character_profile(name) or {}).get("pose_variant_id")
        if variant_id:
            from app.core.pose_variants import get_variant
            canonical = ((get_variant(int(variant_id)) or {})
                         .get("canonical_pose") or "").strip()
            if canonical:
                return canonical
    except Exception as e:
        logger.debug("scene: pose variant lookup failed for %s: %s", name, e)
    if not act:
        return ""
    act = re.sub(r'["„“»].*?["“”«]', "", act).strip()
    act = re.split(r"(?<=[.!?])\s", act, 1)[0].strip()
    return act[:80]


def _position_bucket(x: Optional[float]) -> str:
    if x is None:
        return "center"
    if x < 0.35:
        return "left"
    if x > 0.65:
        return "right"
    return "center"


def build_scene_state(avatar: str) -> Optional[Dict[str, Any]]:
    """Collects everything the render needs + the cache signature.

    Returns None when the avatar has no location or the room has no
    background image (nothing to compose onto).
    """
    from app.core.room_entry import _list_characters_in_room
    from app.core.world_ops import resolve_background_path
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_last_scene_position)
    from app.models.world import get_location_by_id, get_room_by_id

    loc = (get_character_current_location(avatar) or "").strip()
    if not loc:
        return None
    room = (get_character_current_room(avatar) or "").strip()
    # Same hour source as the event images — keeps the day/night template
    # consistent with what the /background endpoint would deliver.
    bg_path = resolve_background_path(loc, room=room, hour=utc_now().hour)
    if not bg_path or not bg_path.exists():
        return None

    loc_obj = get_location_by_id(loc) or {}
    room_obj = get_room_by_id(loc_obj, room) if (loc_obj and room) else None
    label = (room_obj or {}).get("name") or loc_obj.get("name") or loc

    names = [avatar] + [n for n in (_list_characters_in_room(loc, room) or [])
                        if n != avatar]
    chars: List[Dict[str, Any]] = []
    for n in names:
        img = _expr_image_path(n)
        if not img:
            continue  # no visual — the figure also has no panel presence
        pos = get_last_scene_position(n, room, bg_path.name) or {}
        chars.append({
            "name": n,
            "image": img,
            "bucket": _position_bucket(pos.get("x")),
            "activity": _pose_hint(n),
        })

    sig_src = json.dumps([
        loc, room, bg_path.name,
        [(c["name"], str(c["image"]), int(c["image"].stat().st_mtime),
          c["bucket"]) for c in chars],
    ], ensure_ascii=False, sort_keys=True)
    sig = hashlib.sha1(sig_src.encode("utf-8")).hexdigest()[:16]

    return {"location": loc, "room": room, "label": label,
            "bg_path": bg_path, "chars": chars, "sig": sig}


def render_scene(avatar: str, force: bool = False) -> Dict[str, Any]:
    """Renders (or serves from cache) the composed scene for the avatar's
    current room. Returns {"ok", "sig", "cached"} or {"ok": False, "error"}.
    """
    state = build_scene_state(avatar)
    if not state:
        return {"ok": False, "error": "No location or no room background."}
    sig = state["sig"]
    out_path = get_scene_image_path(sig)
    if out_path.exists() and not force:
        return {"ok": True, "sig": sig, "cached": True}

    backend = _resolve_backend()
    if not backend:
        return {"ok": False, "error": "No image backend available."}

    from app.core.event_images import _read_image_dimensions, _safe_dims
    dims = _read_image_dimensions(state["bg_path"])
    if not dims:
        return {"ok": False, "error": "Background dimensions unknown."}
    w, h = _safe_dims(*dims)

    # Prompt: room label + one line per person (position + activity). The
    # appearance itself travels via the reference images.
    lines = []
    for c in state["chars"]:
        part = f"{c['name']} ({c['bucket']})"
        if c["activity"]:
            part += f": {c['activity']}"
        lines.append(part)
    prompt = (f"{state['label']}: the exact room from the first reference "
              f"image, with the following people composed naturally into the "
              f"scene, keeping the room layout, lighting and perspective")
    if lines:
        prompt += ". People: " + "; ".join(lines)
    _ucp = config.resolve_use_case_style(
        "scene",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    if _ucp.get("prompt_style"):
        prompt = f"{_ucp['prompt_style']}, {prompt}"
    negative = _ucp.get("prompt_negative", "")

    # References: background first, then the figures (slot budget applies).
    slots = int(getattr(backend, "ref_slot_count", 0) or 0)
    warning = ""
    if slots < 2 and state["chars"]:
        # Composing needs bg + persons — a 0/1-slot backend renders bg-only.
        warning = (f"Backend '{backend.name}' has only {slots} reference "
                   f"slot(s) — persons are not composed. Set 'Scene Render "
                   f"Default' to a multi-reference backend (e.g. Krea2).")
        logger.warning("scene render: %s", warning)
    refs: Dict[str, str] = {}
    if slots >= 1:
        refs["input_reference_image_1"] = str(state["bg_path"])
        for i, c in enumerate(state["chars"][:max(0, slots - 1)], start=2):
            refs[f"input_reference_image_{i}"] = str(c["image"])
    params: Dict[str, Any] = {
        "width": w, "height": h,
        "seed": random.randint(1, 2**31 - 1),
    }
    if refs:
        params["reference_images"] = refs

    from app.core.task_queue import get_task_queue
    _tq = get_task_queue()
    _track_id = _tq.track_start("scene_render", f"Scene: {state['label']}",
                                agent_name=avatar, provider=backend.name)
    try:
        from app.core.llm_queue import get_llm_queue, Priority as _P
        if backend.api_type == "a1111":
            images = get_llm_queue().submit_gpu_task(
                provider_name=backend.name,
                task_type="scene_render",
                priority=_P.IMAGE_GEN,
                callable_fn=lambda: backend.generate(prompt, negative, params),
                agent_name=avatar,
                label=f"Scene: {state['label']}",
                gpu_type=backend.api_type)
        else:
            images = backend.generate(prompt, negative, params)
    except Exception as e:
        logger.error("scene render failed (%s): %s", backend.name, e)
        _tq.track_finish(_track_id, error=str(e))
        return {"ok": False, "error": str(e)}

    if not images:
        _tq.track_finish(_track_id, error="empty backend result")
        return {"ok": False, "error": "Backend returned no image."}

    try:
        out_path.write_bytes(images[0])
    except Exception as e:
        _tq.track_finish(_track_id, error=str(e))
        return {"ok": False, "error": str(e)}
    _tq.track_finish(_track_id)
    logger.info("scene rendered: %s (%s, %d chars, %d refs, %dx%d)",
                out_path.name, state["label"], len(state["chars"]), len(refs), w, h)
    result = {"ok": True, "sig": sig, "cached": False}
    if warning:
        result["warning"] = warning
    return result
