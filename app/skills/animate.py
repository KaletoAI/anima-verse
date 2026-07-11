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
from typing import Any, Dict, List

from app.core.log import get_logger

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
        svc = _image_service()
        return [
            {"id": b.name, "label": b.name,
             "enabled": bool(getattr(b, "instance_enabled", False) and b.available),
             # LoRAs of the video alias (gateway discovery) — the animate
             # dialog offers them as optional slots.
             "loras": list(getattr(b, "available_loras", []) or [])}
            for b in svc.backends
            if getattr(b, "MEDIA_TYPE", "image") == "video"
        ]
    except Exception as e:
        logger.debug("get_animate_services: %s", e)
        return []


def reload_animate_services() -> None:
    """No-op kept for existing callers: video backends live in the image
    service, which is rebuilt on an ``image_generation`` config change."""
    return None


def animate_image(source_image_path: str, prompt: str, output_path: str,
                  service: str = "", loras=None, seconds=None) -> bool:
    """Renders a video from a still via a video backend (image-to-video).

    Args:
        source_image_path: still to animate (first frame).
        prompt: motion/action description.
        output_path: where the ``.mp4`` is written.
        service: video-backend name/glob (empty = cheapest available).

    Returns True on success, False on error.
    """
    try:
        return _image_service().generate_video(
            source_image_path=source_image_path,
            action_prompt=prompt,
            output_path=output_path,
            backend_glob=service,
            loras=loras,
            seconds=seconds)
    except Exception as e:
        logger.error("animate_image fehlgeschlagen: %s", e)
        return False
