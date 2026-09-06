"""The strict-JSON LLM hop: one call, one repair attempt, one dict back.

Every task whose answer IS a JSON object — not prose that happens to contain
one — needs the same three things: tolerate a code fence around the object,
tolerate the "forgot the wrapper" bare array, and give the model exactly ONE
chance to repair an unparsable answer before the caller fails. That was
written once for the room-furnish job and moved here (2026-09-06,
plan-furnish-v2.md § 2) when the prop-mount classifier needed the same hop;
the classifier must not import the furnish job to get it.

What is deliberately NOT here: what to do with the parsed object. Which keys
are expected, which entries are dropped and what a caller does with a refused
answer is the caller's business — this module ends at "a dict".
"""

import json
import re
from typing import Any, Callable, Dict, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)
_JSON_ARR_RE = re.compile(r"\[.*\]", re.S)


class LlmJsonError(RuntimeError):
    """An answer that was not JSON, twice — the default failure of
    :func:`llm_json`. A caller with an error type of its own (the furnish job
    carries an HTTP status on its) passes that one in instead."""


def parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """Strict-ish JSON extraction: the answer must contain ONE object; code
    fences and stray prose around it are tolerated, everything else is a
    parse failure (the caller retries once). A bare top-level ARRAY — the
    common "forgot the wrapper" slip — is accepted as ``{"_list": [...]}``."""
    text = (raw or "").strip()
    if not text:
        return None
    match = _JSON_OBJ_RE.search(text)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    match = _JSON_ARR_RE.search(text)
    if match:
        try:
            arr = json.loads(match.group(0))
            if isinstance(arr, list):
                return {"_list": arr}
        except ValueError:
            pass
    return None


def llm_json(task: str, system_prompt: str, user_prompt: str, label: str,
             error: Callable[[str], BaseException] = LlmJsonError
             ) -> Dict[str, Any]:
    """One LLM task expecting a JSON object, with EXACTLY one repair attempt
    (the model gets its own broken answer back and is asked for valid JSON).

    ``error`` builds the exception a twice-broken answer raises, so a caller
    can keep its own failure type (and with it its own error message in the
    UI) without wrapping this function.
    """
    from app.core import llm_router
    response = llm_router.llm_call(task=task, system_prompt=system_prompt,
                                   user_prompt=user_prompt,
                                   agent_name="system", label=label)
    raw = str(getattr(response, "content", "") or "")
    obj = parse_json(raw)
    if obj is not None:
        return obj
    logger.info("llm_json %s: unparsable answer, one repair attempt", task)
    repair = (f"{raw[:4000]}\n\n"
              "That was not valid JSON. Return the SAME content as a single "
              "valid JSON object — no markdown, no code fence, no explanation.")
    response = llm_router.llm_call(task=task, system_prompt=system_prompt,
                                   user_prompt=repair, agent_name="system",
                                   label=f"{label} (repair)")
    obj = parse_json(str(getattr(response, "content", "") or ""))
    if obj is None:
        raise error(f"The {task} answer was not valid JSON.")
    return obj
