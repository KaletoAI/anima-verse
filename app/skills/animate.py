"""Image-to-video animation — thin adapter over the image-generation pool.

Video generation was folded into ``app/imagegen`` (a backend media-type:
``localai_video`` / ``together_video`` with ``MEDIA_TYPE == "video"``), so it
runs through the same BackendPool / matching / fallback / per-backend queue as
image generation. This module keeps the small "animate this still" seam its
callers use (``video_generation_skill``, ``instagram``, ``character_ops``) and
delegates to ``ImageService.generate_video()`` + the pool's video-backend list.

The former standalone ``AnimateService`` / ``TogetherAnimateService`` classes
and the ``TOGETHER_ANIMATE_*`` config were retired — see
``development_instructions/plan-video-generation.md``.
"""
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.imagegen.base import MediaGenerationDisabled

logger = get_logger("animate")


def _image_service():
    from app.imagegen.service import get_image_service
    return get_image_service()


def get_animate_services() -> List[Dict[str, Any]]:
    """Configured video backends as ``{id, label, enabled}`` for the frontend.

    ``id`` is the backend name (used as the animate service / backend glob);
    ``enabled`` reflects the globally-enabled + currently-available state.
    """
    try:
        from app.core.config import get_lora_options
        svc = _image_service()
        return [
            {"id": b.name, "label": b.name,
             "enabled": bool(getattr(b, "instance_enabled", False) and b.available),
             # LoRAs of the video alias from the LoRA library ([{name,
             # missing}], backend-scoped) — the animate dialog offers them
             # as optional slots.
             "loras": get_lora_options(
                 b.name, lora_filter=getattr(b, "lora_filter", "") or "")}
            for b in svc.backends
            if getattr(b, "MEDIA_TYPE", "image") == "video"
        ]
    except Exception as e:
        logger.debug("get_animate_services: %s", e)
        return []


def animate_image(source_image_path: str, prompt: str, output_path: str,
                  service: str = "", loras=None, seconds=None,
                  route_out: Optional[Dict[str, Any]] = None) -> bool:
    """Renders a video from a still via a video backend (image-to-video).

    Args:
        source_image_path: still to animate (first frame).
        prompt: motion/action description.
        output_path: where the ``.mp4`` is written.
        service: video-backend name/glob — an explicit pick, never replaced
            by another backend. Empty = the "video" chain of the image
            routing (with its fallback along the chain).
        route_out: optional dict, filled by ``generate_video`` with
            ``{"backend", "routing"?, "fallback_from"?}`` for the caller's
            meta (``animate_backend`` / ``animate_routing`` /
            ``animate_fallback_from`` on the image).

    Returns True on success, False on error — except when the world has media
    generation switched off: that is a refusal, not a failed render, so
    ``MediaGenerationDisabled`` travels on to the caller (the route maps it to
    409, a queue job records its message).
    """
    try:
        return _image_service().generate_video(
            source_image_path=source_image_path,
            action_prompt=prompt,
            output_path=output_path,
            backend_glob=service,
            loras=loras,
            seconds=seconds,
            route_out=route_out)
    except MediaGenerationDisabled:
        raise
    except Exception as e:
        logger.error("animate_image failed: %s", e)
        return False
