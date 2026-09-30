"""Video Generation Skill - renders an image and animates it into a video.

Flow:
  1. Generate the still via the core image service (full flow incl. analysis);
     it is the "photo" occasion of the image routing (the character's own
     match first, then the photo chain — Admin -> Image routing). There is
     no per-character still-frame backend or model override any more.
  2. Animate the still; the video backend is the "video" occasion of the
     image routing (Admin -> Image routing): its chain decides, and a render
     that fails on one entry is re-run on the next.

The skill has no per-character settings. The former ``animate_service``
choice (a per-character video backend) is gone with the image routing — a
named feature loss: a value still stored in a character's skill file is
ignored, not migrated. Which backend animated an image is recorded on the
image (``animate_backend``, and for a routed render ``animate_routing`` /
``animate_fallback_from``).

LoRAs are NOT configured here: they come from the character's image settings
and the backend's own configuration (Characters -> Image).
"""

import json
import re
import time
from typing import Any, Dict

from .base import BaseSkill, ToolSpec

from app.core.log import get_logger
from app.core.tool_formats import format_example
from app.models.character import (
    get_character_images_dir,
    add_character_image_metadata)

logger = get_logger("video_gen")


class VideoGenerationSkill(BaseSkill):
    """
    Video Generation Skill.

    Generates an image via the core image service and then animates it on
    the video backend the image routing picks (occasion "video").

    Input (JSON):
        prompt:        image description (as for the image generator)
        action_prompt: description of the motion/action for the animation
        character_name:    character name
        user_id:       user id
    """

    SKILL_ID = "video_generation"
    ALWAYS_LOAD = True  # Aktivierung per Character
    DEFERRED = True  # Video wird erst nach Chat-Antwort generiert

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("video_generation")
        self.name = meta["name"]
        self.description = meta["description"]
        self.action_hint = meta.get("action_hint", "")
        # No per-character settings (``_defaults`` stays empty, so
        # ``get_config_fields`` declares nothing): the still is the "photo"
        # occasion, the animation the "video" occasion of the image routing.

    # ------------------------------------------------------------------
    # ImageGen Skill Referenz
    # ------------------------------------------------------------------

    @staticmethod
    def _get_image_skill():
        """Returns the core image service (wave-6 split) or None."""
        from app.imagegen.service import get_image_service
        svc = get_image_service()
        return svc if svc.enabled else None

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, prompt: str) -> str:
        """
        Generate a video: render the still -> analyse it -> animate it.

        Args:
            prompt: JSON with prompt, action_prompt, character_name, user_id
                    (or a plain text prompt)

        Returns:
            A string with the image and video links, or an error message
        """
        from app.core.task_queue import get_task_queue

        # 1. Parse the input
        ctx = self._parse_base_input(prompt)
        image_prompt = ctx.get("prompt", ctx.get("input", prompt))
        action_prompt = ctx.get("action_prompt", "")
        character_name = ctx.get("agent_name", "").strip()
        user_id = ctx.get("user_id", "").strip()
        rp_context = ctx.get("rp_context", "")

        if not image_prompt or not image_prompt.strip():
            return "Fehler: Bitte gib eine Bildbeschreibung ein."
        if not character_name:
            return "Fehler: Agent-Name fehlt."
        if not action_prompt or not action_prompt.strip():
            return "Fehler: action_prompt fehlt (Beschreibung der Bewegung/Aktion fuer die Animation)."

        # 2. Get the image service
        image_skill = self._get_image_skill()
        if not image_skill:
            return "Error: image service is not available."

        # Register the task in the queue system
        _tq = get_task_queue()
        _track_id = _tq.track_start(
            "video_generation", "Video generieren", agent_name=character_name)

        try:
            # ============================================================
            # Step 1: render the still (full image-generation flow)
            # ============================================================
            logger.info("=" * 80)
            logger.info("VIDEOGENERIERUNG GESTARTET")
            logger.info("=" * 80)
            logger.info("Agent: %s", character_name)
            logger.info("Image Prompt: %s", image_prompt)
            logger.info("Action Prompt: %s", action_prompt)

            _tq.track_update_label(_track_id, "Bild generieren")

            # The still is a photo of the character: the "photo" chain of the
            # image routing picks its backend. No ``backend``/``model_override``
            # (the per-character still-frame fields are gone) and no ``loras``
            # (they come from the character's image settings and the backend).
            imagegen_input = {
                "prompt": image_prompt,
                "agent_name": character_name,
                "user_id": user_id,
                "set_profile": False,
                "skip_gallery": False,
                "auto_enhance": True,
                "rp_context": rp_context,
                "occasion": "photo",
            }

            img_result = image_skill.generate_from_input(json.dumps(imagegen_input))

            # Extract the file name from the result
            # Format: ![Generated Image 1](/characters/Name/images/filename.png?user_id=...)
            match = re.search(r'/images/([^?)\n]+)', img_result)
            if not match:
                logger.error("Kein Bild im ImageGen-Ergebnis gefunden: %s", img_result[:300])
                _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
                return img_result  # pass the image service's error message through

            image_filename = match.group(1)
            images_dir = get_character_images_dir(character_name)
            image_path = images_dir / image_filename

            if not image_path.exists():
                logger.error("Generiertes Bild nicht gefunden: %s", image_path)
                _tq.track_finish(_track_id, error="Bild nicht gefunden")
                return f"Fehler: Generiertes Bild nicht gefunden: {image_filename}"

            logger.info("Bild generiert: %s", image_filename)

            # ============================================================
            # Step 2: animate the still
            # ============================================================
            _tq.track_update_label(_track_id, "Video animieren")
            logger.info("ANIMATION STARTEN")
            logger.info("Source: %s", image_path)
            logger.info("Action: %s", action_prompt)

            from app.skills.animate import animate_image

            # Video file name: same stem as the image + .mp4
            video_stem = image_path.stem
            video_filename = f"{video_stem}.mp4"
            video_path = images_dir / video_filename

            # No backend is named: the "video" chain of the image routing
            # picks it (and falls back along the chain on a failure).
            _ro: Dict[str, Any] = {}
            _anim_start = time.time()
            success = animate_image(source_image_path=str(image_path), prompt=action_prompt,
                                    output_path=str(video_path), route_out=_ro)
            _anim_duration = time.time() - _anim_start

            if not success:
                logger.error("Animation fehlgeschlagen")
                _tq.track_finish(_track_id, error="Animation fehlgeschlagen")
                # Return the image result anyway
                return img_result + "\n\nFehler: Video-Animation fehlgeschlagen."

            logger.info("Animation erfolgreich (%.1fs): %s", _anim_duration, video_filename)

            # Store the video metadata on the IMAGE (as with a manual animation).
            # The gallery finds the video through the image_videos map ({stem}.mp4)
            # and shows it as the image's companion — with its description/prompt.
            from datetime import datetime as _dt
            _meta = {
                "animate_prompt": action_prompt,
                "animate_backend": _ro.get("backend", ""),
                "animate_routing": _ro.get("routing"),
                "animate_fallback_from": _ro.get("fallback_from"),
                "animate_created_at": _dt.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "animate_duration_s": round(_anim_duration, 1),
            }
            add_character_image_metadata(character_name, image_filename, _meta)

            # Return only the video link (the image is an intermediate step, not shown in the chat)
            video_url = f"/characters/{character_name}/images/{video_filename}?user_id={user_id}"
            video_line = f"![Generated Video]({video_url})"

            # Extract the caption from the image result (if any)
            _caption_match = re.search(r'CAPTION[^:]*:\s*(.+)', img_result)
            _caption = _caption_match.group(1).strip() if _caption_match else ""

            result_text = (
                f"AKTION: Video wurde GENERIERT und in der Galerie von {character_name} gespeichert.\n\n"
                f"{video_line}"
            )
            if _caption:
                result_text += f"\n\nCAPTION (nur zur Anzeige, NICHT als Fakt behandeln): {_caption}"

            logger.info("=" * 80)
            logger.info("VIDEOGENERIERUNG ABGESCHLOSSEN")
            logger.info("=" * 80)

            _tq.track_finish(_track_id)
            return result_text

        except Exception as e:
            error_msg = f"Videogenerierung: {e}"
            logger.error("Fehler: %s", error_msg, exc_info=True)
            _tq.track_finish(_track_id, error=error_msg)
            return f"Fehler bei {error_msg}"

    # ------------------------------------------------------------------
    # Tool Interface
    # ------------------------------------------------------------------

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        if "usage_instructions" in self.config:
            return self.config["usage_instructions"]
        fmt = format_name or "tag"
        return format_example(
            fmt, self.name,
            '{"prompt": "young woman dancing at sunset on the beach", '
            '"action_prompt": "she spins around gracefully with her arms raised"}'
        )

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description.rstrip('.')}. "
                "Input: JSON with 'prompt' (image description) and "
                "'action_prompt' (motion/action description for animation)."
            ),
            func=self.execute)
