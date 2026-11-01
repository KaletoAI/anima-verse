"""Pose check — an optional LLM pass over an image prompt BEFORE it renders.

Scene prompts are written in one go by an LLM, and a diffusion model draws
whatever body logic they carry: three tasks for two hands, legs described in
a waist-up selfie, two people with no stated arrangement. This pass rewrites
the prompt so every person's limbs, the framing and the spatial arrangement
are physically possible and unambiguous — without changing WHAT the image
shows (people, clothing or nudity, the action). It neither censors nor tones
anything down; route its task at a model that handles the world's content.

Where it runs:
  * automatically, per image-routing occasion: ``image_generation.pose_check``
    = {occasion: true}, edited on /admin/settings → Media Generation → Routing.
    Only occasions that render people offer it (``pose_check`` in the
    occasion catalog).
  * on demand from the regenerate/photo dialogs ("Check pose" button,
    ``POST /world/imagegen-enhance-prompt`` with ``mode: "pose"``), and the
    dialogs' checkbox overrides the occasion switch per request
    (``pose_check`` in the request body).

It runs on the SUBJECT prompt before routing, never inside a GPU channel —
an LLM wait must not hold a backend slot. A failure, an empty answer or an
answer that looks like a refusal keeps the original prompt.
"""
from typing import Any, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("pose_check")

# The LLM task (app/core/llm_tasks.py); unrouted it borrows "image_prompt".
TASK = "image_pose_check"

# An answer this much shorter than the prompt dropped content (or is a
# refusal) — the original is the safer render.
_MIN_LENGTH_RATIO = 0.5


def supported(occasion: str) -> bool:
    """Whether the occasion renders people and therefore offers the check."""
    from app.imagegen.occasions import OCCASIONS
    return bool((OCCASIONS.get(str(occasion or "").strip()) or {}).get("pose_check"))


def enabled_for(occasion: str) -> bool:
    """The routing switch of this occasion (default off)."""
    if not supported(occasion):
        return False
    from app.core import config
    flags = config.get("image_generation.pose_check", {}) or {}
    return isinstance(flags, dict) and flags.get(str(occasion).strip()) is True


def check_pose(prompt: str, *, character: str = "") -> str:
    """Rewrite ``prompt`` for consistent body logic; the original on any
    failure. Blocking (one LLM call) — call it from a worker thread."""
    original = (prompt or "").strip()
    if not original:
        return prompt
    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        system, user = render_task("image_pose_check", original_prompt=original)
        response = llm_call(task=TASK, system_prompt=system, user_prompt=user,
                            agent_name=character)
        checked = (getattr(response, "content", "") or "").strip()
    except Exception as e:  # noqa: BLE001 — a failed check never blocks a render
        logger.warning("Pose check failed, rendering the original prompt: %s", e)
        return prompt
    if not checked:
        logger.warning("Pose check returned nothing, rendering the original prompt")
        return prompt
    if len(checked) < len(original) * _MIN_LENGTH_RATIO:
        logger.warning("Pose check answer is too short (%d < %d chars) — looks like "
                       "dropped content or a refusal; rendering the original prompt",
                       len(checked), len(original))
        return prompt
    logger.info("Pose check rewrote the prompt: %s", checked[:160])
    return checked


def apply(occasion: str, prompt: str, *, override: Optional[bool] = None,
          character: str = "") -> Tuple[str, bool]:
    """The automatic hook: ``(prompt, checked)``.

    ``override`` is the dialog's checkbox: True/False wins over the routing
    switch, None follows it. An occasion without people never checks."""
    if not supported(occasion):
        return prompt, False
    wanted = enabled_for(occasion) if override is None else bool(override)
    if not wanted:
        return prompt, False
    checked = check_pose(prompt, character=character)
    return checked, checked != prompt


def parse_override(value: Any) -> Optional[bool]:
    """A request's ``pose_check`` field: a bool, or None when absent/unclear."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None
