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
from typing import Any, Callable, Dict, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

_DECODER = json.JSONDecoder()
_CLOSER = {"{": "}", "[": "]"}
#: How many candidate start positions are tried before giving up — prose in
#: front of the answer may contain a stray bracket or two, never dozens.
_MAX_STARTS = 8


class LlmJsonError(RuntimeError):
    """An answer that was not JSON, twice — the default failure of
    :func:`llm_json`. A caller with an error type of its own (the furnish job
    carries an HTTP status on its) passes that one in instead."""


def _close_open(text: str, start: int) -> Optional[str]:
    """The JSON value starting at ``start`` with its missing closers added.

    Walks the text outside strings with a stack of open ``{``/``[``. A
    model that forgets the outermost brace or stops after a complete list
    element leaves exactly that stack behind; the closers are appended in
    stack order. A closing code fence ends the walk. Refused (``None``):
    a string still open at the end (a value cut in half is never invented),
    a closer that does not match, or a stack that empties before the end (the
    value was complete — raw_decode already said it is not valid JSON).
    """
    stack = []
    in_string = escaped = False
    end = text.find("```", start)
    end = len(text) if end < 0 else end
    for i in range(start, end):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _CLOSER:
            stack.append(ch)
        elif ch in "}]":
            if not stack or _CLOSER[stack.pop()] != ch:
                return None
            if not stack:
                return None
    if in_string or not stack:
        return None
    body = text[start:end].rstrip().rstrip(",").rstrip()
    return body + "".join(_CLOSER[ch] for ch in reversed(stack))


def _decode_at(text: str, start: int):
    """(value, end) of the JSON value at ``start`` — read as it stands
    (anything behind it ignored), else with its open brackets closed. ``None``
    when neither works."""
    try:
        return _DECODER.raw_decode(text, start)
    except ValueError:
        pass
    closed = _close_open(text, start)
    if closed is None:
        return None
    try:
        return json.loads(closed), len(text)
    except ValueError:
        return None


def _first_value(text: str, opener: str, kind: type):
    """(value, start, end) of the first ``opener``-started value of type
    ``kind`` in ``text``, or ``None``."""
    start = text.find(opener)
    tries = 0
    while start >= 0 and tries < _MAX_STARTS:
        tries += 1
        hit = _decode_at(text, start)
        if hit is not None and isinstance(hit[0], kind):
            return hit[0], start, hit[1]
        start = text.find(opener, start + 1)
    return None


def loads_object(raw: Any) -> Optional[Dict[str, Any]]:
    """The one tolerant JSON-OBJECT decoder for model answers.

    From the first ``{`` on: the first complete object is taken as it
    stands (code fences, prose before it and anything behind it — including
    one brace too many — are ignored); failing that, the brackets the model
    left open are closed in stack order and the text is loaded again (the
    "forgot the outermost brace" and "stopped after a list element" slips).
    A later ``{`` is tried when an earlier one starts no object (prose with a
    stray brace). ``None`` when nothing decodes to a dict.
    """
    text = str(raw or "")
    hit = _first_value(text, "{", dict)
    return hit[0] if hit is not None else None


def parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """Strict-ish JSON extraction: the answer must contain ONE object, read by
    :func:`loads_object` (fences, stray prose and missing closers tolerated);
    everything else is a parse failure (the caller retries once). A bare
    top-level ARRAY — the common "forgot the wrapper" slip — is accepted as
    ``{"_list": [...]}``: an array that starts before the first object and
    encloses it wins over that object."""
    text = (raw or "").strip()
    if not text:
        return None
    obj_at = text.find("{")
    arr_at = text.find("[")
    if arr_at >= 0 and (obj_at < 0 or arr_at < obj_at):
        arr = _first_value(text, "[", list)
        if arr is not None and (obj_at < 0 or arr[1] < obj_at < arr[2]):
            return {"_list": arr[0]}
    obj = loads_object(text)
    if obj is not None:
        return obj
    arr = _first_value(text, "[", list)
    return {"_list": arr[0]} if arr is not None else None


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
