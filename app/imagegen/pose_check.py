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
import json
import re
from typing import Any, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("pose_check")

# The LLM task (app/core/llm_tasks.py); unrouted it borrows "image_prompt".
TASK = "image_pose_check"

# An answer this much shorter than the prompt dropped content (or is a
# refusal) — the original is the safer render.
_MIN_LENGTH_RATIO = 0.5

# The template asks for "CHECK: <limb list>" first and "PROMPT: <prompt>"
# after it — listing every limb's task makes the model actually find the
# conflicts instead of returning the prompt untouched.
_PROMPT_MARKER = re.compile(r"^[ \t]*PROMPT:[ \t]*", re.MULTILINE)
_CHECK_MARKER = re.compile(r"^[ \t]*CHECK:", re.MULTILINE)


def _extract_prompt(answer: str) -> Tuple[str, str]:
    """``(prompt, check)`` from an answer in the template's form. An answer
    without the PROMPT marker counts as the bare prompt — unless it is only a
    CHECK part, which is no prompt at all (empty)."""
    match = _PROMPT_MARKER.search(answer)
    if match:
        check = answer[:match.start()]
        return answer[match.end():].strip(), _CHECK_MARKER.sub("", check, count=1).strip()
    if _CHECK_MARKER.match(answer):
        return "", answer.strip()
    return answer.strip(), ""


_SCENE_DECODER = json.JSONDecoder()


def _image_text(prompt: str) -> str:
    """The part of ``prompt`` that describes the picture — what the length
    guard measures. A scene object embedded by the photo tool
    (``{"image_prompt": …, "rp_context": …, "user_input": …}``) counts only
    with its ``image_prompt``: the role-play context and the turn's
    instructions are no image content, and a repair that leaves them out
    dropped nothing (2026-11-01: a 2546-character prompt, most of it that
    context, rejected a complete 686-character repair as "too short")."""
    out, pos = [], 0
    while True:
        start = prompt.find("{", pos)
        if start < 0:
            out.append(prompt[pos:])
            return "".join(out)
        try:
            obj, end = _SCENE_DECODER.raw_decode(prompt, start)
        except ValueError:
            out.append(prompt[pos:start + 1])
            pos = start + 1
            continue
        out.append(prompt[pos:start])
        if isinstance(obj, dict):
            out.append(str(obj.get("image_prompt") or ""))
        else:
            out.append(prompt[start:end])
        pos = end


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
        answer = (getattr(response, "content", "") or "").strip()
    except Exception as e:  # noqa: BLE001 — a failed check never blocks a render
        logger.warning("Pose check failed, rendering the original prompt: %s", e)
        return prompt
    checked, findings = _extract_prompt(answer)
    if findings:
        logger.info("Pose check findings: %s", " | ".join(findings.split("\n"))[:400])
    if not checked:
        logger.warning("Pose check returned nothing, rendering the original prompt")
        return prompt
    measured = len(_image_text(original).strip())
    if len(checked) < measured * _MIN_LENGTH_RATIO:
        logger.warning("Pose check answer is too short (%d < %d chars of image text) — "
                       "looks like dropped content or a refusal; rendering the original prompt",
                       len(checked), measured)
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
