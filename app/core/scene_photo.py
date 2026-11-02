"""Scene photo — the 📷 button in the player UI (plan-chat-photos.md).

Renders ONE image of the current moment from the avatar's point of view:
the prompt is distilled from the recent room conversation (scene_photo
template), references come from the regenerate pipeline (room background +
present characters), and the result lands in the AVATAR's gallery.

Public photos announce a narrator line in the room stream. Secret photos
stay silent unless an observer notices; showing them later can reveal them.
"""
from pathlib import Path
import random
import re
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.log import get_logger
from app.core.lora_library import LoraNotAllowedError
from app.imagegen.base import MediaGenerationDisabled

logger = get_logger("scene_photo")

# Cap for the transcript lines fed into the prompt distillation.
_TRANSCRIPT_LINES = 12


class PhotoVisible(BaseModel):
    name: str = Field(max_length=200)
    screen_x: float = Field(ge=0, le=1, allow_inf_nan=False)
    screen_y: float = Field(ge=0, le=1, allow_inf_nan=False)
    depth_m: float = Field(ge=0, allow_inf_nan=False)


class PhotoCamera(BaseModel):
    pitch_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    height_m: float = Field(ge=0, allow_inf_nan=False)
    fov_deg: float = Field(gt=0, lt=180, allow_inf_nan=False)


class PhotoView(BaseModel):
    visible: List[PhotoVisible] = Field(max_length=128)
    camera: PhotoCamera


_SCREENSHOT_SENTENCE = (
    "The reference image gives only composition, camera angle and poses; "
    "its 3D/CGI look must not be copied.")
_SCREENSHOT_NEGATIVE = "3d render, cgi, video game screenshot, low poly, plastic skin, game engine"
_CAMERA_HOLDER = re.compile(r"\bselfie\b|\btaken\s+by\b", re.IGNORECASE)


def _view_framing(view: PhotoView, visible: List[PhotoVisible]) -> str:
    """Translate client geometry into framing, never into world facts."""
    camera = view.camera
    angle = ("from above" if camera.pitch_deg < -20 else
             "from below" if camera.pitch_deg > 15 else "at eye level")
    shot = "wide view" if camera.fov_deg >= 60 else "close view"
    parts = ["Photograph from an unseen photographer at the given angle.",
             f"Camera {angle}, {shot}, {camera.height_m:g} m above ground."]
    depths = [person.depth_m for person in visible]
    nearest, farthest = (min(depths), max(depths)) if depths else (0, 0)
    midpoint = (nearest + farthest) / 2
    for person in visible:
        side = ("left" if person.screen_x < 1 / 3 else
                "right" if person.screen_x >= 2 / 3 else "centre")
        layer = ""
        if nearest != farthest:
            layer = ", front" if person.depth_m < midpoint else ", back" if person.depth_m > midpoint else ""
        parts.append(f"{person.name}: {side}{layer}.")
    if not visible:
        parts.append("No people in the frame.")
    return " ".join(parts)


def _room_transcript(avatar: str, loc: str, room: str) -> str:
    from app.models import perception_store
    lines: List[str] = []
    for r in perception_store.get_character_room_stream(avatar, loc, room, 20):
        sp = ((r.get("meta") or {}).get("speaker") or "").strip()
        txt = (r.get("content") or "").strip()
        if not sp or not txt:
            continue
        lines.append(f"{sp}: {txt}")
    return "\n".join(lines[-_TRANSCRIPT_LINES:])


def _person_descriptions(subjects: List[str]) -> str:
    """Text block with appearance + worn outfit per person in the frame.

    The reference image alone is often not enough (identity only) — the
    prompt must carry the description too, same semantics as everywhere
    else: reference = appearance aid, outfit/pose live in the text."""
    from app.core.scene_render import _appearance_text
    from app.core.outfit_renderer import render_outfit
    parts = []
    for n in subjects:
        bits = []
        try:
            a = _appearance_text(n)
            if a:
                bits.append(a)
        except Exception:
            pass
        try:
            outfit = (render_outfit(character_name=n) or {}).get("full") or ""
            if outfit:
                bits.append(outfit)
        except Exception:
            pass
        parts.append(f"{n}" + (f" ({'; '.join(bits)})" if bits else ""))
    return "People in the frame: " + "; ".join(parts)


def _pairs_among(names: List[str]) -> List[tuple]:
    """The running pair interactions INSIDE this set of names, each once, as
    ``(a, b, pose_key)`` in the order the names come in.

    A pair pose describes ONE event between two people. Listed per person it
    turns into two people striking the same pose side by side — the very
    thing the image pipeline gets wrong when it only ever sees one character
    (``expression_regen`` skips partner poses for exactly that reason). Here
    both are in the frame on purpose, so the event is named once.
    """
    from app.core.interaction_engine import get_interaction
    seen = set()
    out: List[tuple] = []
    for name in names:
        inter = get_interaction(name)
        if not inter:
            continue
        partner = str(inter.get("partner") or "")
        if partner not in names:
            continue
        pair = tuple(sorted((name, partner)))
        if pair in seen:
            continue
        seen.add(pair)
        out.append((name, partner, str(inter.get("pose_key") or "")))
    return out


def prepare_scene_photo(avatar: str, view: Optional[dict] = None) -> Dict[str, Any]:
    """Builds the photo prompt (chat-context distillation + person
    descriptions) WITHOUT generating — feeds the image-gen dialog."""
    from app.models.character import (get_character_current_location,
                                      get_character_current_room)
    from app.core.room_entry import characters_in_room

    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    if not loc:
        return {"ok": False, "error": "Avatar has no location."}

    present = [c for c in (characters_in_room(loc, room) or [])
               if c != avatar]
    # The photographer stays behind the camera — unless they are part of
    # what there is to photograph. In a running pair the avatar is a
    # participant, and a photo of the moment that leaves out one half of it
    # is the wrong photo. The template flips to its selfie wording on its
    # own once the photographer is among the subjects.
    from app.core.interaction_engine import get_interaction
    if present and get_interaction(avatar):
        subjects = present + [avatar]
    else:
        # Alone in the room -> selfie.
        subjects = present or [avatar]
    framing = ""
    if view is not None:
        parsed_view = PhotoView.model_validate(view)
        # The server owns presence; the client only owns framing.
        allowed = set(present + [avatar])
        seen = set()
        visible = []
        for person in parsed_view.visible:
            if person.name in allowed and person.name not in seen:
                seen.add(person.name)
                visible.append(person)
        subjects = [person.name for person in visible]
        present = list(subjects)
        framing = _view_framing(parsed_view, visible)
    pairs = _pairs_among(subjects)

    transcript = _room_transcript(avatar, loc, room)

    # Prompt distillation via LLM; deterministic fallback from state poses.
    prompt = ""
    if transcript:
        try:
            from app.core.prompt_templates import render_task
            from app.core.llm_router import llm_call
            sys_p, user_p = render_task(
                "scene_photo",
                photographer=avatar,
                subjects=", ".join(subjects),
                pairs="; ".join(f"{a} and {b} are {pose} together"
                                for a, b, pose in pairs),
                transcript=transcript, framing=framing)
            resp = llm_call(task="image_prompt", system_prompt=sys_p,
                            user_prompt=user_p, agent_name=avatar)
            prompt = (getattr(resp, "content", "") or "").strip().strip('"')
            from app.imagegen.prompt_guard import is_prompt_refusal
            # Distillation intentionally compresses conversation. Reject only
            # extreme truncation (at most 40 chars), not a valid short summary.
            if is_prompt_refusal(prompt, transcript[:400], min_length_ratio=0.1):
                logger.warning("Scene photo prompt is a refusal or too short — using deterministic poses")
                prompt = ""
            elif framing and _CAMERA_HOLDER.search(prompt):
                logger.warning("Scene photo prompt contradicts the free camera — using deterministic poses")
                prompt = ""
        except Exception as e:
            logger.warning("scene photo prompt distillation failed: %s", e)
    if not prompt:
        from app.core.scene_render import _pose_hint
        parts = []
        paired = {n for a, b, _ in pairs for n in (a, b)}
        for a, b, pose in pairs:
            parts.append(f"{a} and {b} ({pose} together)")
        for n in subjects:
            if n in paired:
                continue
            hint = _pose_hint(n)
            if framing and _CAMERA_HOLDER.search(hint or ""):
                hint = ""
            parts.append(f"{n} ({hint})" if hint else n)
        prompt = ("Candid photograph of the current moment: "
                  + "; ".join(parts))

    if framing:
        prompt = f"{prompt}\n{framing}"

    desc = _person_descriptions(subjects) if subjects else ""
    if desc:
        prompt = f"{prompt}\n{desc}"

    # The dialog's preselection: the backend the "photo" occasion resolves
    # to for this avatar right now (never probes, never rotates).
    from app.imagegen.routing import explain_occasion
    try:
        default_backend = explain_occasion("photo", character=avatar).get("resolved") or ""
    except Exception as e:
        logger.debug("scene photo: photo routing lookup failed: %s", e)
        default_backend = ""
    return {"ok": True, "prompt": prompt, "subjects": subjects,
            "present": present, "location": loc, "room": room,
            "default_backend": default_backend}


def take_scene_photo(avatar: str,
                     prompt: str = "",
                     backend_name: str = "",
                     loras: Any = None,
                     negative_prompt: str = "",
                     character_names: Any = None,
                     use_room: bool = True,
                     pose_check: Optional[bool] = None,
                     reference_image_id: str = "",
                     user_id: str = "",
                     secret: bool = False,
                     rng: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    """Synchronous — the caller (route) runs it in a worker thread.

    Without overrides it prepares everything itself (one-click path);
    the image-gen dialog passes prompt/backend/LoRAs/negative explicitly."""
    source_path = ""
    if reference_image_id:
        from app.core.chat_ops import resolve_owned_chat_upload_path
        source_path = str(resolve_owned_chat_upload_path(reference_image_id, user_id))
    prep = prepare_scene_photo(avatar)
    if not prep.get("ok"):
        return prep
    loc, room = prep["location"], prep["room"]
    subjects = (list(character_names) if character_names or (source_path and character_names == [])
                else prep["subjects"])
    from app.core.room_entry import characters_in_room
    from app.core.scene_photo_watch import discovery_chance, discover_photo
    present = list(dict.fromkeys(characters_in_room(loc, room) or []))
    subjects = list(dict.fromkeys(n for n in subjects if n in present))
    # Snapshot attention at the shutter, before potentially slow generation.
    chances = [(n, discovery_chance(n, depicted=n in subjects)) for n in present
               if n != avatar] if secret and room else []
    if not prompt:
        prompt = prep["prompt"]

    if source_path:
        prompt = prompt.replace(_SCREENSHOT_SENTENCE, "").strip()
        prompt = f"{prompt}\n{_SCREENSHOT_SENTENCE}".strip()

    # Only a backend the user PICKED is explicit. The dialog's preselection
    # (prep["default_backend"]) is display only — the one-click photo runs on
    # the "photo" chain and keeps its fallback.
    backend_name = (backend_name or "").strip()

    from app.models.character import get_character_images_dir
    out_dir = get_character_images_dir(avatar)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"{avatar}_photo.png")

    from app.skills.image_regenerate import regenerate_image
    try:
        ok, final_prompt, actual_path = regenerate_image(
            character_name=avatar,
            output_path=output_path,
            original_prompt=prompt,
            backend_name=backend_name,
            loras=(list(loras) if loras else None),
            character_names=subjects,
            room_id=room,
            location_id=loc,
            negative_prompt_override=(negative_prompt or "").strip(),
            create_new=True,
            use_room=bool(use_room),
            occasion="photo",
            pose_check=pose_check,
            **({"use_source_as_reference": True, "source_image_path": source_path,
                "negative_prompt_extra": _SCREENSHOT_NEGATIVE} if source_path else {}))
    except (MediaGenerationDisabled, LoraNotAllowedError):
        # Refusals, not failed renders: the world's master switch (the route
        # maps it to a 409) and an explicitly picked LoRA the library does
        # not associate with the picked backend (400) — both verbatim.
        raise
    except Exception as e:
        logger.error("scene photo generation failed: %s", e)
        return {"ok": False, "error": str(e)}
    if not ok:
        return {"ok": False, "error": "Generation failed."}

    filename = Path(actual_path).name
    from app.models.character import add_character_image_metadata
    add_character_image_metadata(avatar, filename, {
        "scene_photo": True, "secret": secret, "photo_subjects": subjects})
    if reference_image_id:
        from app.core.chat_ops import delete_screenshot_upload
        try:
            delete_screenshot_upload(reference_image_id, user_id)
        except OSError as exc:
            # The generated gallery image is already safe; daily cleanup can retry.
            logger.warning("scene photo input cleanup failed: %s", exc)
    discovered_by = []
    if secret:
        roll = rng if rng is not None else random.random
        for watcher, chance in chances:
            if chance > 0 and roll() < chance and discover_photo(
                    avatar, filename, subjects, watcher, loc, room):
                discovered_by.append(watcher)
        return {"ok": True, "filename": filename, "character": avatar,
                "url": f"/characters/{avatar}/images/{filename}",
                "prompt": final_prompt, "discovered_by": discovered_by}
    logger.info("scene photo: %s (%d subjects, prompt: %s)",
                filename, len(subjects), final_prompt[:100])

    # Unified direct-action flow (announce_action): narrator line into the
    # room stream + chime reactions via the loop — NPCs notice the photo
    # being taken and can react. The image_url meta renders the photo
    # inline in the scene view.
    from app.core.i18n import t
    from app.core.perception import announce_action
    from app.models.character import get_character_language
    _lang = get_character_language(avatar) or "de"
    # Who is in the picture, not who is in the room: the dialog may have
    # deselected people, and in a pair the avatar photographs itself along
    # with its partner.
    _others = [n for n in subjects if n != avatar]
    if not subjects:
        _line = t("{actor} takes a photo of the surroundings.", _lang).format(actor=avatar)
    elif not _others:
        _line = t("{actor} takes a selfie.", _lang).format(actor=avatar)
    elif avatar in subjects:
        _line = t("{actor} holds up the camera and takes a photo of "
                  "themselves with {others}.", _lang).format(
            actor=avatar, others=", ".join(_others))
    else:
        _line = t("{actor} holds up the camera and takes a photo of "
                  "{others}.", _lang).format(
            actor=avatar, others=", ".join(_others))
    announce_action(avatar, _line, source="scene_photo",
                    perception_meta={"image_url":
                                     f"/characters/{avatar}/images/{filename}"})

    return {"ok": True, "filename": filename, "character": avatar,
            "url": f"/characters/{avatar}/images/{filename}",
            "prompt": final_prompt, "discovered_by": []}


def resolve_scene_photo(avatar: str, filename: str) -> str:
    """Resolve only this avatar's own generated photo, with path containment."""
    from fastapi import HTTPException
    from app.models.character import get_character_images_dir
    from app.core.upload_limits import ensure_image, max_upload_bytes
    if not filename or Path(filename).name != filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=404, detail="Photo not found")
    root = get_character_images_dir(avatar).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    limit = max_upload_bytes()
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail="Photo too large")
    ensure_image(content, filename=filename, what="photo")
    return f"/characters/{avatar}/images/{filename}"
