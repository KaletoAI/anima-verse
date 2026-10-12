"""Prepare validated UniMate motion captions and optional catalog proposals."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from app.core.llm_json import parse_json


class MotionPromptError(ValueError):
    """A motion preparation failure suitable for display in the UI."""


@dataclass
class PreparedMotion:
    captions: List[str]
    loop: bool
    entry: Optional[Dict[str, Any]]


def _check_mode(mode: str) -> None:
    if mode not in ("entry", "candidate", "free"):
        raise MotionPromptError(f"unknown mode '{mode}'")


def parse_motion_answer(raw: str, *, mode: str, shared_groups: Set[str],
                        taken_aliases: Set[str]) -> PreparedMotion:
    """Validate an answer without accessing the catalog or an LLM."""
    _check_mode(mode)
    answer = parse_json(raw)
    if answer is None:
        raise MotionPromptError("invalid JSON")
    if answer.get("error") == "unsupported_motion":
        raise MotionPromptError(f"unsupported motion: {answer.get('reason', '')}")
    unknown = set(answer) - {"segments", "loop", "entry"}
    if unknown:
        raise MotionPromptError("unknown field(s): " + ", ".join(sorted(unknown)))
    segments = answer.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 3:
        raise MotionPromptError("expected 1..3 segments")
    for i, caption in enumerate(segments, 1):
        if not isinstance(caption, str):
            raise MotionPromptError(f"caption {i} must be a string")
        if not caption.startswith("An object "):
            raise MotionPromptError(f"caption {i} must start with 'An object '")
        if len(caption.splitlines()) != 1 or "\n" in caption or "\r" in caption:
            raise MotionPromptError(f"caption {i} must not contain a line break")
        if not caption[len("An object "):].strip():
            raise MotionPromptError(f"caption {i} must describe an action")
    loop = answer.get("loop")
    if not isinstance(loop, bool):
        raise MotionPromptError("loop must be a bool")
    proposal = None
    entry = answer.get("entry")
    if "entry" in answer or mode != "entry":
        if not isinstance(entry, dict):
            raise MotionPromptError("entry missing or not an object")
        unknown = set(entry) - {"key", "prompt", "synonyms", "group"}
        if unknown:
            raise MotionPromptError("unknown field(s): " + ", ".join(sorted(unknown)))
    if mode != "entry":
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            raise MotionPromptError("key must not be empty")
        if "/" in key:
            raise MotionPromptError("key must not contain '/'")
        key = key.strip().lower()
        taken = {alias.strip().lower() for alias in taken_aliases}
        if key in taken:
            raise MotionPromptError(f"key '{key}' already exists")
        prompt = entry.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise MotionPromptError("prompt must not be empty")
        group = entry.get("group")
        if not isinstance(group, str) or group not in shared_groups:
            raise MotionPromptError(f"unknown place type '{group}'")
        synonyms = entry.get("synonyms")
        if not isinstance(synonyms, list) or any(not isinstance(s, str) for s in synonyms):
            raise MotionPromptError("synonyms must be a list of strings")
        seen = taken | {key}
        cleaned = []
        for synonym in synonyms:
            synonym = synonym.strip().lower()
            if synonym and synonym not in seen:
                cleaned.append(synonym)
                seen.add(synonym)
        proposal = dict(key=key, prompt=prompt.strip(), synonyms=cleaned, group=group)
    return PreparedMotion(captions=list(segments), loop=loop, entry=proposal)


def prepare_motion(mode: str, *, entry: Optional[Dict] = None,
                   text: str = "", hint: str = "") -> PreparedMotion:
    """Render and route one motion request, then validate its answer."""
    from app.core import pose_catalog
    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task

    _check_mode(mode)
    if mode == "entry" and (not isinstance(entry, dict) or
                            any(field not in entry for field in ("key", "group", "prompt"))):
        raise MotionPromptError("entry missing required key, group or prompt")
    from app.core.pose_catalog_edit import read_store
    groups = set(read_store("pose", "shared").get("groups", {}))
    taken = set()
    for key, item in pose_catalog.get_catalog("pose").items():
        taken.add(key.strip().lower())
        taken.update(s.strip().lower() for s in item.get("synonyms", []) if isinstance(s, str))
    system, user = render_task("pose_animation_prompt", mode=mode, entry=entry,
        text=text, hint=hint, groups=", ".join(sorted(groups)),
        taken=", ".join(sorted(taken)), body="humanoid")
    try:
        response = llm_call("pose_animation_prompt", system, user,
                            max_tokens=600, label="Pose animation captions")
    except RuntimeError as exc:
        raise MotionPromptError(f"no LLM routed for pose_animation_prompt: {exc}") from exc
    return parse_motion_answer(response.content, mode=mode,
                               shared_groups=groups, taken_aliases=taken)
