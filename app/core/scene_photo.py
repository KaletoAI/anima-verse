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


def take_scene_photo(avatar: str) -> Dict[str, Any]:
    """Synchronous — the caller (route) runs it in a worker thread."""
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_images_dir)
    from app.core.room_entry import _list_characters_in_room

    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    if not loc:
        return {"ok": False, "error": "Avatar has no location."}

    present = [c for c in (_list_characters_in_room(loc, room) or [])
               if c != avatar]
    # Alone in the room -> selfie.
    subjects = present or [avatar]

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
                transcript=transcript)
            resp = llm_call(task="image_prompt", system_prompt=sys_p,
                            user_prompt=user_p, agent_name=avatar)
            prompt = (getattr(resp, "content", "") or "").strip().strip('"')
        except Exception as e:
            logger.warning("scene photo prompt distillation failed: %s", e)
    if not prompt:
        from app.core.scene_render import _pose_hint
        parts = []
        for n in subjects:
            hint = _pose_hint(n)
            parts.append(f"{n} ({hint})" if hint else n)
        prompt = ("Candid photograph of the current moment: "
                  + "; ".join(parts))

    # Backend: same resolution chain as the scene render.
    from app.core.scene_render import _resolve_backend
    backend = _resolve_backend()

    out_dir = get_character_images_dir(avatar)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"{avatar}_photo.png")

    from app.skills.image_regenerate import regenerate_image
    try:
        ok, final_prompt, actual_path = regenerate_image(
            character_name=avatar,
            output_path=output_path,
            original_prompt=prompt,
            backend_name=(getattr(backend, "name", "") or ""),
            character_names=subjects,
            room_id=room,
            location_id=loc,
            create_new=True,
            use_room=True)
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
    from app.core.perception import announce_action
    if present:
        _line = (f"{avatar} zückt die Kamera und macht ein Foto von "
                 f"{', '.join(present)}.")
    else:
        _line = f"{avatar} macht ein Selfie."
    announce_action(avatar, _line, source="scene_photo",
                    perception_meta={"image_url":
                                     f"/characters/{avatar}/images/{filename}"})

    return {"ok": True, "filename": filename, "character": avatar,
            "url": f"/characters/{avatar}/images/{filename}",
            "prompt": final_prompt}
