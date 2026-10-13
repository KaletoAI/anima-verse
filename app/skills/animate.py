"""Image-to-video animation — thin adapter over the image-generation pool.

Video generation was folded into ``app/imagegen`` (a backend media-type:
``localai_video`` / ``together_video`` / ``openai_video`` / ``civitai_video``
with ``MEDIA_TYPE == "video"``), so it
runs through the same BackendPool / matching / fallback / per-backend queue as
image generation. This module keeps the small "animate this still" seam its
callers use (``video_generation_skill``, ``instagram``, ``character_ops``) and
delegates to ``ImageService.generate_video()`` + the pool's video-backend list.

The former standalone ``AnimateService`` / ``TogetherAnimateService`` classes
and the ``TOGETHER_ANIMATE_*`` config were retired — see
``development_instructions/plan-video-generation.md``.
"""
from typing import Any, Callable, Dict, List, Optional

from app.core.log import get_logger
from app.imagegen.base import HubJobLost, MediaGenerationDisabled

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
                  route_out: Optional[Dict[str, Any]] = None,
                  hub_stage=None) -> bool:
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
    409, a queue job records its message). A lost hub job (``HubJobLost``)
    travels on as well: it is terminal, never "try again".

    ``hub_stage``: the operation stage this render belongs to (see
    :func:`run_video_op`).
    """
    try:
        return _image_service().generate_video(
            source_image_path=source_image_path,
            action_prompt=prompt,
            output_path=output_path,
            backend_glob=service,
            loras=loras,
            seconds=seconds,
            route_out=route_out,
            hub_stage=hub_stage)
    except (MediaGenerationDisabled, HubJobLost):
        raise
    except Exception as e:
        logger.error("animate_image failed: %s", e)
        return False


# ── Hub operations (app/core/hub_ops.py) ──────────────────────────────────
# A video renders for minutes on the hub. As an operation it survives a
# restart: the record freezes the still (copied), the prompt, the pick and
# the target; the MP4 lands in the record's directory and the kind's
# PUBLISHER puts it where the caller wants it (the Instagram feed, a
# character's gallery image). Video operations always belong to a thread
# (spec D10): the video skill may run inside a queue handler that will not
# reach this call again after a restart.

_PUBLISHERS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def register_video_kind(kind: str, publish: Callable[..., Dict[str, Any]],
                        track_type: str) -> None:
    """``publish(op, video_file, route)`` puts the finished MP4 in place and
    writes the caller's metadata; it returns ``{"ok": …}``."""
    from app.core import hub_ops
    _PUBLISHERS[kind] = publish
    hub_ops.register_kind(
        kind, track_type=track_type,
        resume=lambda op: hub_ops.resume(op, lambda: _video_stages(op),
                                         agent_name=op.inputs.get("character", "")))


def run_video_op(kind: str, subject: str, inputs: Dict[str, Any], *,
                 label: str, track_id: str = "") -> Dict[str, Any]:
    """Animate ``inputs["source"]`` as a hub operation of ``kind`` and publish
    it. ``inputs``: ``source``, ``prompt``, optional ``service``, ``loras``,
    ``seconds``, ``character``, ``fail_message`` plus whatever the kind's
    publisher reads. Raises ``HubOpBusy`` when the target is in flight."""
    from pathlib import Path
    from app.core import hub_ops
    source = Path(inputs["source"])
    op = hub_ops.create(kind, subject, {**inputs, "source": f"inputs/{source.name}"},
                        label=label, track_id=track_id, thread_owned=True)

    def run():
        op.freeze_file(source, "inputs", source.name)  # inside the settled run
        return _video_stages(op)
    return hub_ops.execute(op, run)


def _video_stages(op) -> Dict[str, Any]:
    """Stage ``video`` → publish (fresh run and resume)."""
    from app.core.timeutils import parse_iso, utc_now
    inputs = op.inputs
    if not op.done("video"):
        route: Dict[str, Any] = {}
        ok = animate_image(str(op.abs(inputs["source"])), inputs.get("prompt", ""),
                           str(op.path("video", "out.mp4")),
                           service=inputs.get("service") or "", loras=inputs.get("loras"),
                           seconds=inputs.get("seconds"), route_out=route,
                           hub_stage=op.stage("video"))
        if not ok:
            return {"ok": False, "error": inputs.get("fail_message") or "Animation failed"}
        try:
            duration = (utc_now() - parse_iso(op.created_at)).total_seconds()
        except (TypeError, ValueError):
            duration = 0.0
        op.complete("video", {"route": route, "duration_s": round(duration, 1)})
    result = op.result("video")
    publish = _PUBLISHERS.get(op.kind)
    if publish is None:
        return {"ok": False, "error": "resume operation unknown"}
    return publish(op, op.abs("video/out.mp4"), dict(result.get("route") or {}),
                   duration_s=result.get("duration_s") or 0.0)
