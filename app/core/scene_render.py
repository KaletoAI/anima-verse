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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import config
from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.core.timeutils import utc_now

logger = get_logger("scene_render")


# Figure height in % of the stage at scale = 1 — mirrors the environment
# panel's FIG_BASE_H so the collage matches what the live view shows.
FIG_BASE_H = 70

# Built-in prompt templates per render mode. Overridable via config
# (image_generation.scene_prompt_collage / scene_prompt_multi_ref) so each
# workflow (e.g. Krea edit vs. Qwen edit) can get its own tuned wording
# without code changes. Placeholders: {label} = room/location name,
# {count} = "exactly two people" etc., {people} = person list (multi_ref
# only). KEEP IN SYNC with the schema defaults in config_schema.py.
PROMPT_COLLAGE_DEFAULT = (
    "{label}: the people were pasted onto this room photo — seamlessly "
    "integrate them into the scene. Keep the room and keep every person "
    "exactly where and as they are: same position, same size, same pose, "
    "{count} and NO ONE else — no additional people, no duplicates. Blend "
    "lighting, shadows, color grading, reflections and edges so it looks "
    "like one natural photograph")
PROMPT_MULTI_REF_DEFAULT = (
    "{label}: the exact room from the first reference image, keeping the "
    "room layout, lighting and perspective. Compose {count} into the scene "
    "and NO ONE else — each person appears exactly once, no additional "
    "people, no duplicates. The person reference images provide IDENTITY "
    "ONLY (face, hair, body, outfit) — IGNORE the pose and background they "
    "show; each person's pose follows the text. People: {people}")


def _prompt_template(config_key: str, default: str) -> str:
    txt = str(config.get(f"image_generation.{config_key}", "") or "").strip()
    return txt or default


def _fill_template(tpl: str, **vars_: str) -> str:
    # Plain token replace — str.format would choke on braces in user text.
    for k, v in vars_.items():
        tpl = tpl.replace("{" + k + "}", v)
    return tpl


def get_scene_dir() -> Path:
    d = get_storage_dir() / "scene_render"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_scene_render_mode() -> str:
    """'collage' (default): paste the figures onto the background at their
    live panel positions and send ONE image — the edit model only
    harmonizes. 'multi_ref': background + persons as separate reference
    images, pose from text (for backends with true identity conditioning)."""
    m = str(config.get("image_generation.scene_render_mode", "") or "").strip().lower()
    return m if m in ("collage", "multi_ref") else "collage"


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
    """Identity reference image of a character.

    Preference: the variant matching the CURRENT state (mood + effective
    activity + real equipped state — same lookup as /outfit-expression);
    else the newest cached variant of any state (matches the current outfit
    era better than the often-old profile portrait); else the profile image.
    The reference is used for identity only — pose comes from the prompt.
    """
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
        from app.core.expression_regen import _get_expressions_dir
        expr_dir = _get_expressions_dir(name)
        newest = None
        if expr_dir.exists():
            for p in expr_dir.iterdir():
                if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                    continue
                if p.name.startswith(".tmp_"):
                    continue
                if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
                    newest = p
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


def build_scene_state(avatar: str,
                      layout: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Collects everything the render needs + the cache signature.

    ``layout`` is the panel's measured on-screen geometry (stage aspect +
    per-figure anchor/height fractions) — it feeds the collage signature.
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

    names = [avatar] + [n for n in (_list_characters_in_room(loc, room) or [])
                        if n != avatar]
    from app.models.character import get_last_scene_position
    chars: List[Dict[str, Any]] = []
    for n in names:
        img = _expr_image_path(n)
        if not img:
            continue  # no visual — the figure also has no panel presence
        pos = get_last_scene_position(n, room, bg_path.name) or {}
        chars.append({
            "name": n,
            "image": img,
            "activity": _pose_hint(n),
            "x": pos.get("x"), "y": pos.get("y"), "scale": pos.get("scale"),
        })

    mode = get_scene_render_mode()
    # Positions only matter for the collage draft — in multi_ref mode they
    # must not invalidate the cache (they don't influence the render there).
    pos_sig = None
    if mode == "collage":
        lay = layout if isinstance(layout, dict) else {}
        figs = lay.get("figures") if isinstance(lay.get("figures"), dict) else {}
        entries = []
        for c in chars:
            f = figs.get(c["name"]) if isinstance(figs.get(c["name"]), dict) else {}
            entries.append((
                round(float(f.get("x", c["x"] or 0.0) or 0.0), 2),
                round(float(f.get("y", c["y"] or 0.0) or 0.0), 2),
                round(float(f.get("h", 0.0) or 0.0), 2),
                round(float(c["scale"] or 1.0), 2)))
        pos_sig = [round(float(lay.get("aspect") or 0.0), 2), entries]
    sig_src = json.dumps([
        mode, loc, room, bg_path.name,
        [(c["name"], str(c["image"]), int(c["image"].stat().st_mtime))
         for c in chars],
        pos_sig,
    ], ensure_ascii=False, sort_keys=True)
    sig = hashlib.sha1(sig_src.encode("utf-8")).hexdigest()[:16]

    return {"location": loc, "room": room, "label": label, "mode": mode,
            "bg_path": bg_path, "chars": chars, "sig": sig}


def _full_mask_for(draft: Path, sig: str) -> Optional[Path]:
    """All-white L mask in the draft's size — 'edit everywhere' for the
    edits endpoint. The init image still anchors the composition (img2img);
    how much may change is the workflow's denoise (tunable via the
    backend's extra params)."""
    try:
        from PIL import Image
        with Image.open(draft) as im:
            mask = Image.new("L", im.size, 255)
        out = get_scene_dir() / f"{sig}_mask.png"
        mask.save(out)
        return out
    except Exception as e:
        logger.error("scene mask: %s", e)
        return None


def _build_collage(state: Dict[str, Any], sig: str,
                   layout: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """Pastes the present figures onto the room background — the draft the
    edit model then only harmonizes.

    Preferred geometry source is the panel's MEASURED layout (stage aspect
    + per-figure anchor/height fractions): the background is center-cropped
    to the panel aspect (the panel shows it object-fit:cover) and every
    figure is pasted at exactly its measured on-screen size — WYSIWYG.
    Without a layout, the panel CSS is approximated (anchor bottom center,
    height FIG_BASE_H% × scale — NOTE: this misses the panel's 200px width
    cap and tends to render figures larger than the live view).
    """
    try:
        from PIL import Image
    except Exception as e:
        logger.error("scene collage: PIL unavailable: %s", e)
        return None
    try:
        canvas = Image.open(state["bg_path"]).convert("RGB")
    except Exception as e:
        logger.error("scene collage: background unreadable: %s", e)
        return None

    lay = layout if isinstance(layout, dict) else {}
    figs = lay.get("figures") if isinstance(lay.get("figures"), dict) else {}
    aspect = 0.0
    try:
        aspect = float(lay.get("aspect") or 0.0)
    except (TypeError, ValueError):
        aspect = 0.0
    if aspect > 0:
        # Reproduce the panel's object-fit:cover center crop so the layout
        # fractions land on the same background pixels the player sees.
        W, H = canvas.size
        cur = W / H
        if cur > aspect * 1.01:
            new_w = int(H * aspect)
            x0 = (W - new_w) // 2
            canvas = canvas.crop((x0, 0, x0 + new_w, H))
        elif cur < aspect * 0.99:
            new_h = int(W / aspect)
            y0 = (H - new_h) // 2
            canvas = canvas.crop((0, y0, W, y0 + new_h))

    W, H = canvas.size
    n = len(state["chars"])
    for i, c in enumerate(state["chars"]):
        try:
            fig = Image.open(c["image"]).convert("RGBA")
        except Exception as e:
            logger.warning("scene collage: figure %s unreadable: %s", c["name"], e)
            continue
        f = figs.get(c["name"]) if isinstance(figs.get(c["name"]), dict) else None
        if f and f.get("h"):
            x = float(f.get("x") or 0.5)
            y = float(f.get("y") or 0.92)
            fh = max(1, int(H * float(f["h"])))
        else:
            x = c.get("x")
            y = c.get("y")
            if x is None:
                x = 0.5 if n <= 1 else 0.12 + (0.76 * i) / (n - 1)
            if y is None:
                y = 0.92
            x, y = float(x), float(y)
            fh = max(1, int(H * FIG_BASE_H / 100.0 * float(c.get("scale") or 1.0)))
        fw = max(1, int(fig.width * fh / fig.height))
        fig = fig.resize((fw, fh), Image.LANCZOS)
        canvas.paste(fig, (int(x * W - fw / 2), int(y * H - fh)), fig)
    out = get_scene_dir() / f"{sig}_draft.png"
    try:
        canvas.save(out)
    except Exception as e:
        logger.error("scene collage: save failed: %s", e)
        return None
    return out


def render_scene(avatar: str, force: bool = False,
                 layout: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Renders (or serves from cache) the composed scene for the avatar's
    current room. ``layout`` = the panel's measured geometry (collage mode).
    Returns {"ok", "sig", "cached"} or {"ok": False, "error"}.
    """
    state = build_scene_state(avatar, layout)
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

    from app.core.event_images import _read_image_dimensions, _safe_dims
    dims = _read_image_dimensions(state["bg_path"])
    if not dims:
        return {"ok": False, "error": "Background dimensions unknown."}
    w, h = _safe_dims(*dims)

    slots = int(getattr(backend, "ref_slot_count", 0) or 0)
    n = len(state["chars"])
    count_word = {1: "exactly one person", 2: "exactly two people"}.get(
        n, f"exactly {n} people")
    warning = ""
    refs: Dict[str, str] = {}

    if state["mode"] == "collage":
        # Collage mode: ONE pre-composed image (bg + figures at their live
        # panel positions) — the input already contains each person exactly
        # once, the model only harmonizes. Pose text deliberately omitted —
        # the pasted figure IS the pose.
        draft = _build_collage(state, sig, layout)
        if not draft:
            return {"ok": False, "error": "Collage draft failed."}
        # Generation size follows the draft — the layout crop may have
        # changed the aspect vs. the raw background.
        draft_dims = _read_image_dimensions(draft)
        if draft_dims:
            w, h = _safe_dims(*draft_dims)
        if getattr(backend, "category", "") == "inpaint":
            # Edits/inpaint alias: draft as init image + all-white mask via
            # POST /v1/images/edits — true img2img, the composition is
            # anchored by the init latent instead of loose conditioning
            # (a generate alias treats references only as inspiration and
            # freely recomposes — observed with Krea rebalance).
            mask = _full_mask_for(draft, sig)
            if not mask:
                return {"ok": False, "error": "Mask creation failed."}
            refs["input_canvas"] = str(draft)
            refs["input_mask"] = str(mask)
        elif slots < 1:
            warning = (f"Backend '{backend.name}' has no reference slot — "
                       f"the collage draft cannot be sent.")
            logger.warning("scene render: %s", warning)
        else:
            refs["input_reference_image_1"] = str(draft)
            warning = (f"Backend '{backend.name}' is a generate alias — the "
                       f"draft is only loose inspiration there. For faithful "
                       f"integration point 'Scene Render Default' at an "
                       f"edits/inpaint alias (category=inpaint).")
            logger.info("scene render: %s", warning)
        prompt = _fill_template(
            _prompt_template("scene_prompt_collage", PROMPT_COLLAGE_DEFAULT),
            label=state["label"], count=count_word)
    else:
        # multi_ref mode: background + persons as separate references.
        if getattr(backend, "category", "") == "inpaint":
            # The edits path does img2img on ONE input — extra references
            # are not composed (observed: result = the untouched room).
            warning = (f"Backend '{backend.name}' is an edits/inpaint alias — "
                       f"it cannot compose multiple references. Use collage "
                       f"mode with it, or a generate alias for multi_ref.")
            logger.warning("scene render: %s", warning)
        elif slots < 2 and state["chars"]:
            # Composing needs bg + persons — a 0/1-slot backend is bg-only.
            warning = (f"Backend '{backend.name}' has only {slots} reference "
                       f"slot(s) — persons are not composed. Set 'Scene Render "
                       f"Default' to a multi-reference backend (e.g. Krea2).")
            logger.warning("scene render: %s", warning)
        ref_slot_of: Dict[str, int] = {}
        if slots >= 1:
            refs["input_reference_image_1"] = str(state["bg_path"])
            for i, c in enumerate(state["chars"][:max(0, slots - 1)], start=2):
                refs[f"input_reference_image_{i}"] = str(c["image"])
                ref_slot_of[c["name"]] = i

        # Prompt: room label + a CLOSED person set. Models like to invent
        # extra people or duplicate a referenced person — so state the exact
        # count, forbid everyone else, and declare the person references as
        # IDENTITY sources only (ref-slot semantics: appearance from the
        # image, pose from the text — a standing reference must not spawn a
        # standing copy).
        all_names = [c["name"] for c in state["chars"]]
        lines = []
        for c in state["chars"]:
            part = c["name"]
            if c["name"] in ref_slot_of:
                part += f" (identity from reference image {ref_slot_of[c['name']]})"
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
        if lines:
            prompt = _fill_template(
                _prompt_template("scene_prompt_multi_ref", PROMPT_MULTI_REF_DEFAULT),
                label=state["label"], count=count_word,
                people="; ".join(lines))
        else:
            prompt = (f"{state['label']}: the exact room from the first "
                      f"reference image, keeping the room layout, lighting "
                      f"and perspective")
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
    logger.info("scene rendered: %s (%s, %d chars, %d refs, %dx%d)",
                out_path.name, state["label"], len(state["chars"]), len(refs), w, h)
    result = {"ok": True, "sig": sig, "cached": False}
    if warning:
        result["warning"] = warning
    return result
