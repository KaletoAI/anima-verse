"""Scene photo — the 📷 button in the player UI (plan-chat-photos.md).

Renders ONE image of the current moment from the avatar's point of view:
the prompt is distilled from the recent room conversation (scene_photo
template), references come from the regenerate pipeline (room background +
present characters), and the result lands in the AVATAR's gallery.

The action is also announced as a narrator line in the room stream, so the
present NPCs perceive "X takes a photo" and can react to it on their next
loop turn.
"""
from pathlib import Path
from typing import Any, Dict, List

from app.core.log import get_logger
from app.imagegen.base import MediaGenerationDisabled

logger = get_logger("scene_photo")

# Cap for the transcript lines fed into the prompt distillation.
_TRANSCRIPT_LINES = 12


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


def prepare_scene_photo(avatar: str) -> Dict[str, Any]:
    """Builds the photo prompt (chat-context distillation + person
    descriptions) WITHOUT generating — feeds the image-gen dialog."""
    from app.models.character import (get_character_current_location,
                                      get_character_current_room)
    from app.core.room_entry import _list_characters_in_room

    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    if not loc:
        return {"ok": False, "error": "Avatar has no location."}

    present = [c for c in (_list_characters_in_room(loc, room) or [])
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
                transcript=transcript)
            resp = llm_call(task="image_prompt", system_prompt=sys_p,
                            user_prompt=user_p, agent_name=avatar)
            prompt = (getattr(resp, "content", "") or "").strip().strip('"')
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
            parts.append(f"{n} ({hint})" if hint else n)
        prompt = ("Candid photograph of the current moment: "
                  + "; ".join(parts))

    desc = _person_descriptions(subjects)
    if desc:
        prompt = f"{prompt}\n{desc}"

    from app.core.scene_render import _resolve_backend
    backend = _resolve_backend()
    return {"ok": True, "prompt": prompt, "subjects": subjects,
            "present": present, "location": loc, "room": room,
            "default_backend": getattr(backend, "name", "") or ""}


def take_scene_photo(avatar: str,
                     prompt: str = "",
                     backend_name: str = "",
                     loras: Any = None,
                     negative_prompt: str = "",
                     character_names: Any = None,
                     use_room: bool = True) -> Dict[str, Any]:
    """Synchronous — the caller (route) runs it in a worker thread.

    Without overrides it prepares everything itself (one-click path);
    the image-gen dialog passes prompt/backend/LoRAs/negative explicitly."""
    prep = prepare_scene_photo(avatar)
    if not prep.get("ok"):
        return prep
    loc, room = prep["location"], prep["room"]
    present = prep["present"]
    subjects = list(character_names) if character_names else prep["subjects"]
    if not prompt:
        prompt = prep["prompt"]

    backend_name = (backend_name or prep.get("default_backend") or "").strip()

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
            use_room=bool(use_room))
    except MediaGenerationDisabled:
        # The world's master switch: not a failed render but a refusal, and
        # the route maps it to a 409 the player sees verbatim.
        raise
    except Exception as e:
        logger.error("scene photo generation failed: %s", e)
        return {"ok": False, "error": str(e)}
    if not ok:
        return {"ok": False, "error": "Generation failed."}

    filename = Path(actual_path).name
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
    if not _others:
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
            "prompt": final_prompt}
