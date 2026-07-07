"""Rendered-scene pipeline — renders the environment view (room + present
characters) as ONE generated image, shown by the player UI's "Rendered"
toggle in the environment panel (plan-scene-live-rendering.md).

Two independent render modes (config ``image_generation.scene_render_mode``),
so any generate backend (Qwen, Flux, Krea2, …) can be used flexibly:

- ``multi_ref``: room background as reference slot 1 + the present
  characters' PROFILE images (canonical identity source, same semantics as
  the main pipeline's reference slots) on the remaining slots. Persons
  beyond the slot budget are described in text instead.
- ``only_background``: only the room background as reference — every
  person is described in text (appearance from the profile + pose).

Backend selection follows the event-image pattern: config glob
``image_generation.scene_imagegen_default`` (fallback: location default,
then cheapest available). The prompt per mode is a config template
(``scene_prompt_multi_ref`` / ``scene_prompt_only_background``).

Results are cached per scene signature — (mode, backend, location, room,
background file, present characters + reference images) — under
``worlds/<w>/scene_render/``. Rendering is manual-only (player button);
``force=True`` bypasses the cache with a fresh seed.
"""
import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import config
from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.core.timeutils import utc_now

logger = get_logger("scene_render")

# Built-in prompt templates per render mode. Overridable via config so each
# workflow can get its own tuned wording without code changes. Placeholders:
# {label} = room/location name, {count} = "exactly two people" etc.,
# {people} = person list. KEEP IN SYNC with the schema defaults in
# config_schema.py.
PROMPT_MULTI_REF_DEFAULT = (
    "The exact {setting} from the first reference image, keeping its "
    "layout, lighting and perspective. Compose {count} into the scene "
    "and NO ONE else — each person appears exactly once, no additional "
    "people, no duplicates. A person's reference image provides their "
    "IDENTITY ONLY (face, hair, body, outfit) — IGNORE the pose and "
    "background it shows; every person's pose follows the text. "
    "People: {people}")
PROMPT_ONLY_BG_DEFAULT = (
    "The exact {setting} from the reference image, keeping its layout, "
    "lighting and perspective. Compose {count} into the scene and NO ONE "
    "else — each person appears exactly once, no additional people, no "
    "duplicates. People: {people}")


def _setting_word(loc_obj: Dict[str, Any]) -> str:
    """'room'/'outdoor location'/'place' from the location's indoor flag —
    'room' on an outdoor location makes the model build an interior."""
    flag = str((loc_obj or {}).get("indoor") or "").strip().lower()
    if flag == "indoor":
        return "room"
    if flag == "outdoor":
        return "outdoor location"
    return "place"


def get_scene_dir() -> Path:
    d = get_storage_dir() / "scene_render"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_scene_image_path(sig: str) -> Path:
    return get_scene_dir() / f"{sig}.png"


def get_scene_render_mode() -> str:
    """'multi_ref' (default): background + profile images as references.
    'only_background': background reference only, persons as text."""
    m = str(config.get("image_generation.scene_render_mode", "") or "").strip().lower()
    return m if m in ("multi_ref", "only_background") else "multi_ref"


# Unix ts of the last fresh generation — basis for the render cooldown.
_last_gen_ts = 0.0


def _scene_cooldown_s() -> int:
    try:
        v = config.get("image_generation.scene_render_cooldown_s", "")
        return int(v) if str(v).strip() != "" else 120
    except (TypeError, ValueError):
        return 120


def _newest_scene_image() -> Optional[Path]:
    """Most recent rendered scene image (16-hex signature files only)."""
    newest = None
    try:
        for p in get_scene_dir().iterdir():
            if p.suffix != ".png" or not re.fullmatch(r"[0-9a-f]{16}", p.stem):
                continue
            if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
                newest = p
    except Exception as e:
        logger.debug("scene: newest lookup failed: %s", e)
    return newest


def _prompt_template(config_key: str, default: str) -> str:
    txt = str(config.get(f"image_generation.{config_key}", "") or "").strip()
    if not txt:
        return default
    # Old shipped defaults persisted by the former settings prefill count as
    # "not customized" — keep built-in template updates flowing.
    from app.core.config_schema import SCENE_PROMPT_LEGACY_DEFAULTS
    if txt in SCENE_PROMPT_LEGACY_DEFAULTS:
        return default
    return txt


def _fill_template(tpl: str, **vars_: str) -> str:
    # Plain token replace — str.format would choke on braces in user text.
    for k, v in vars_.items():
        tpl = tpl.replace("{" + k + "}", v)
    return tpl


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


def _person_image_path(name: str) -> Optional[Path]:
    """Reference image of a person for multi_ref — the CURRENT expression/
    variant image (renders proved better than the profile portrait; user
    decision 2026-07-07). Preference:

    1. Variant for the exact current state (mood + effective activity +
       equipped — same key as /outfit-expression); on a miss the missing
       variant is triggered in the background (coalesced/cooldowned).
    2. Variant with the SAME activity/pose but any mood (sidecar match) —
       the exact key misses on every mood shift.
    3. Newest cached variant. 4. Profile image.
    """
    mood = activity = ""
    try:
        from app.models.character import (get_character_current_feeling,
                                          get_effective_activity)
        mood = get_character_current_feeling(name) or ""
        activity = get_effective_activity(name) or ""
    except Exception as e:
        logger.debug("scene: state lookup failed for %s: %s", name, e)
    try:
        from app.core.expression_regen import (get_cached_expression,
                                               trigger_expression_generation)
        from app.models.inventory import get_equipped_items, get_equipped_pieces
        cached = get_cached_expression(
            name, mood, activity,
            equipped_pieces=get_equipped_pieces(name),
            equipped_items=get_equipped_items(name))
        if cached and Path(cached).exists():
            return Path(cached)
        # Exact variant missing — generate it for the NEXT render (fire and
        # forget; coalesce + cooldown keep this from spamming the queue).
        trigger_expression_generation(name, mood, activity)
    except Exception as e:
        logger.debug("scene: expression lookup failed for %s: %s", name, e)
    try:
        from app.core.expression_regen import _get_expressions_dir
        expr_dir = _get_expressions_dir(name)
        want = activity.strip().lower()
        pose_match = None
        newest = None
        if expr_dir.exists():
            for p in expr_dir.iterdir():
                if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                    continue
                if p.name.startswith(".tmp_"):
                    continue
                if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
                    newest = p
                if want:
                    try:
                        meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if str(meta.get("activity") or "").strip().lower() != want:
                        continue
                    if (pose_match is None
                            or p.stat().st_mtime > pose_match.stat().st_mtime):
                        pose_match = p
        if pose_match:
            return pose_match
        if newest:
            return newest
    except Exception as e:
        logger.debug("scene: variant fallback failed for %s: %s", name, e)
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


def _appearance_text(name: str) -> str:
    """Compact appearance description for persons WITHOUT a reference slot:
    identity travels as text instead of an image. Outfit placeholders are
    resolved by the model helper."""
    try:
        from app.models.character import get_character_appearance
        desc = (get_character_appearance(name) or "").strip()
        desc = " ".join(desc.split())
        return desc[:300]
    except Exception as e:
        logger.debug("scene: appearance lookup failed for %s: %s", name, e)
        return ""


def build_scene_state(avatar: str) -> Optional[Dict[str, Any]]:
    """Collects everything the render needs + the cache signature.

    Returns None when the avatar has no location or the room has no
    background image (nothing to compose onto).
    """
    from app.core.room_entry import _list_characters_in_room
    from app.core.world_ops import resolve_background_path
    from app.models.character import (get_character_current_location,
                                      get_character_current_room)
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
    setting = _setting_word(loc_obj)

    names = [avatar] + [n for n in (_list_characters_in_room(loc, room) or [])
                        if n != avatar]
    mode = get_scene_render_mode()
    from app.models.character import get_movement_target
    chars: List[Dict[str, Any]] = []
    for n in names:
        # Characters in transit (active movement target, walking away over
        # several ticks) still count as present data-wise but are visually
        # leaving — rendering them produces "returning to X" figures that
        # don't belong in the scene. The avatar is always included.
        if n != avatar:
            try:
                if (get_movement_target(n) or "").strip():
                    continue
            except Exception:
                pass
        # Reference image (current expression/variant) — only sent in
        # multi_ref mode, but part of the signature either way (a changed
        # variant = a changed scene). A person WITHOUT any image stays in
        # the list: they become a text-described person in the prompt.
        chars.append({
            "name": n,
            "image": _person_image_path(n),
            "activity": _pose_hint(n),
        })

    sig_src = json.dumps([
        mode, loc, room, bg_path.name,
        [(c["name"],
          str(c["image"]) if c["image"] else "",
          int(c["image"].stat().st_mtime) if c["image"] else 0)
         for c in chars],
    ], ensure_ascii=False, sort_keys=True)
    sig = hashlib.sha1(sig_src.encode("utf-8")).hexdigest()[:16]

    return {"location": loc, "room": room, "label": label, "mode": mode,
            "setting": setting, "bg_path": bg_path, "chars": chars, "sig": sig}


def render_scene(avatar: str, force: bool = False) -> Dict[str, Any]:
    """Renders (or serves from cache) the composed scene for the avatar's
    current room. Returns {"ok", "sig", "cached"} or {"ok": False, "error"}.
    """
    state = build_scene_state(avatar)
    if not state:
        return {"ok": False, "error": "No location or no room background."}

    backend = _resolve_backend()
    if not backend:
        return {"ok": False, "error": "No image backend available."}
    # Backend is part of the cache key: switching the scene backend must
    # produce a fresh render instead of serving the other backend's result.
    sig = hashlib.sha1(
        f"{state['sig']}|{backend.name}".encode("utf-8")).hexdigest()[:16]
    out_path = get_scene_image_path(sig)
    if out_path.exists() and not force:
        return {"ok": True, "sig": sig, "cached": True}

    # Cooldown: a fresh GENERATION at most every N seconds — panel remounts
    # and signature churn (variant mtimes, presence changes) must not burn
    # renders back to back. The ⟳ button (force) always bypasses.
    global _last_gen_ts
    cooldown = _scene_cooldown_s()
    if not force and cooldown > 0 and (time.time() - _last_gen_ts) < cooldown:
        newest = _newest_scene_image()
        if newest:
            logger.info("scene render: cooldown active (%ds) — serving %s",
                        cooldown, newest.name)
            return {"ok": True, "sig": newest.stem, "cached": True,
                    "cooldown": True}

    from app.core.event_images import _read_image_dimensions, _safe_dims
    dims = _read_image_dimensions(state["bg_path"])
    if not dims:
        return {"ok": False, "error": "Background dimensions unknown."}
    w, h = _safe_dims(*dims)

    mode = state["mode"]
    slots = int(getattr(backend, "ref_slot_count", 0) or 0)
    n = len(state["chars"])
    count_word = {1: "exactly one person", 2: "exactly two people"}.get(
        n, f"exactly {n} people")
    warning = ""
    if getattr(backend, "category", "") == "inpaint":
        # The edits path does img2img on ONE input — it neither composes
        # references nor renders text persons reliably.
        warning = (f"Backend '{backend.name}' is an edits/inpaint alias — "
                   f"scene rendering needs a generate alias.")
        logger.warning("scene render: %s", warning)

    # References: background always in slot 1; profile images of the
    # present characters only in multi_ref mode (slot budget applies).
    refs: Dict[str, str] = {}
    ref_slot_of: Dict[str, int] = {}
    if slots >= 1:
        refs["input_reference_image_1"] = str(state["bg_path"])
        if mode == "multi_ref":
            with_img = [c for c in state["chars"] if c["image"]]
            for i, c in enumerate(with_img[:max(0, slots - 1)], start=2):
                refs[f"input_reference_image_{i}"] = str(c["image"])
                ref_slot_of[c["name"]] = i

    # People lines: slotted persons point at their reference image, all
    # others carry their appearance as text.
    all_names = [c["name"] for c in state["chars"]]
    lines = []
    for c in state["chars"]:
        part = c["name"]
        if c["name"] in ref_slot_of:
            part += f" (identity from reference image {ref_slot_of[c['name']]})"
        else:
            desc = _appearance_text(c["name"])
            if desc:
                part += f" ({desc})"
        act = c["activity"]
        if act:
            # Another present character's name inside a pose hint ("lying
            # beside Kai") makes the model instantiate that person AGAIN —
            # neutralize names of co-present characters.
            for other in all_names:
                if other != c["name"]:
                    act = re.sub(rf"\b{re.escape(other)}\b", "them", act,
                                 flags=re.IGNORECASE)
            part += f": {act}"
        lines.append(part)

    tpl_key, tpl_default = (
        ("scene_prompt_multi_ref", PROMPT_MULTI_REF_DEFAULT)
        if mode == "multi_ref"
        else ("scene_prompt_only_background", PROMPT_ONLY_BG_DEFAULT))
    if lines:
        prompt = _fill_template(
            _prompt_template(tpl_key, tpl_default),
            label=state["label"], count=count_word,
            setting=state["setting"], people="; ".join(lines))
    else:
        prompt = (f"The exact {state['setting']} from the reference image, "
                  f"keeping its layout, lighting and perspective")
    _ucp = config.resolve_use_case_style(
        "scene",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    if _ucp.get("prompt_style"):
        prompt = f"{_ucp['prompt_style']}, {prompt}"
    # Built-in anti-duplicate negative, merged with the use-case negative.
    _neg_base = ("additional people, extra person, crowd, duplicated person, "
                 "clone, twins, second copy of the same person")
    negative = ", ".join(p for p in (_ucp.get("prompt_negative", ""), _neg_base) if p)

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
    _last_gen_ts = time.time()
    logger.info("scene rendered: %s (%s, mode=%s, %d chars, %d refs, %dx%d)",
                out_path.name, state["label"], mode, len(state["chars"]),
                len(refs), w, h)
    result = {"ok": True, "sig": sig, "cached": False}
    if warning:
        result["warning"] = warning
    return result
