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

_DECODER = json.JSONDecoder()
_CLOSER = {"{": "}", "[": "]"}
#: How many candidate start positions are tried before giving up — prose in
#: front of the answer may contain a stray bracket or two, never dozens.
_MAX_STARTS = 8


class LlmJsonError(RuntimeError):
    """An answer that was not JSON, twice — the default failure of
    :func:`llm_json`. A caller with an error type of its own (the furnish job
    carries an HTTP status on its) passes that one in instead."""


def _walk(text: str, start: int):
    """Follow the bracket run that starts at ``start`` (outside strings).

    Returns ``("ended", i)`` when the run ends at index ``i`` before the
    text does — the stack emptied, or a closer did not match (prose with a
    stray bracket). Returns ``("open", end, stack, in_string)`` when the run
    reaches the end of the text, or a code fence OUTSIDE a string, with
    brackets still open — a truncated answer or a forgotten closer.
    """
    stack = []
    in_string = escaped = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "`" and text.startswith("```", i):
            break
        elif ch in _CLOSER:
            stack.append(ch)
        elif ch in "}]":
            if not stack or _CLOSER[stack.pop()] != ch:
                return ("ended", i)
            if not stack:
                return ("ended", i)
        i += 1
    return ("open", i, stack, in_string)


#: A body ending on these characters may have been cut inside a number
#: ("mood": 1 of a meant 15) — closing it would invent a value.
_NUMBER_TAIL = re.compile(r"[-+.\deE]+$")


def _close_open(text: str, end: int, stack: list) -> Optional[str]:
    """``text`` up to ``end`` with the closers of ``stack`` appended.

    A model that forgets the outermost brace or stops after a complete list
    element leaves exactly that stack behind; the closers are appended in
    stack order. Refused (``None``): a body that ends on a number (it may
    be cut in half — "1" of a meant "15"; a number followed by a comma is
    complete and stays).
    """
    body = text[:end].rstrip()
    if body.endswith(","):
        body = body[:-1].rstrip()
    else:
        tail = _NUMBER_TAIL.search(body)
        if tail and re.search(r"[\d.-]", tail.group()):
            return None
    return body + "".join(_CLOSER[ch] for ch in reversed(stack))


def _decode_at(text: str, start: int):
    """(hit, resume) for the JSON value at ``start``.

    ``hit`` is (value, end) — read as it stands (anything behind it
    ignored), else with its open brackets closed — or ``None``.
    ``resume`` is where the search for a later start may continue: behind
    the end of a failed bracket run, never inside it. ``None`` means stop:
    the failed value runs to the end of the text (a truncated answer), so
    every later start lies INSIDE it and would hand back a fragment as the
    answer.
    """
    try:
        value, end = _DECODER.raw_decode(text, start)
        return (value, end), end
    except ValueError:
        pass
    walk = _walk(text, start)
    if walk[0] == "ended":
        return None, walk[1] + 1
    _, end, stack, in_string = walk
    if in_string:
        return None, None
    closed = _close_open(text[start:], end - start, stack)
    if closed is None:
        return None, None
    try:
        return (json.loads(closed), len(text)), None
    except ValueError:
        return None, None


def _values(text: str, openers: str, descend_lists: bool = False):
    """Yield (value, start, end) for each value that starts with one of
    ``openers``, in text order. A start is only tried outside every value
    or failed bracket run before it — except inside a complete list when
    ``descend_lists`` is set — and the walk stops at a truncated value."""
    pos = 0
    tries = 0
    while tries < _MAX_STARTS:
        starts = [p for p in (text.find(o, pos) for o in openers) if p >= 0]
        if not starts:
            return
        start = min(starts)
        tries += 1
        hit, resume = _decode_at(text, start)
        if hit is not None:
            yield hit[0], start, hit[1]
            resume = start + 1 if descend_lists and isinstance(hit[0], list) else hit[1]
        if resume is None:
            return
        pos = max(resume, start + 1)


def loads_object(raw: Any) -> Optional[Dict[str, Any]]:
    """The one tolerant JSON-OBJECT decoder for model answers.

    From the first ``{`` on: the first complete object is taken as it
    stands (code fences, prose before it and anything behind it — including
    one brace too many — are ignored); failing that, the brackets the model
    left open are closed in stack order and the text is loaded again (the
    "forgot the outermost brace" and "stopped after a list element" slips).
    A later ``{`` is tried only BEHIND an earlier one that ended without
    being an object (prose with a stray brace); the objects inside a complete
    leading array are read as before. A value cut off by the end
    of the text (an open string, a body cut inside a number, a closed text
    that still does not load) is ``None`` — never one of the complete
    objects nested inside it. ``None`` when nothing decodes to a dict.

    The FIRST complete object wins: an example object in prose before the
    real answer is returned instead of it (callers then see a contract
    error or an empty result).
    """
    text = str(raw or "")
    for value, _start, _end in _values(text, "{[", descend_lists=True):
        if isinstance(value, dict):
            return value
    return None


def parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """Strict-ish JSON extraction: the answer must contain ONE object, read
    like :func:`loads_object` (fences, stray prose and missing closers
    tolerated); everything else is a parse failure (the caller retries once).
    A bare top-level ARRAY — the common "forgot the wrapper" slip — is
    accepted as ``{"_list": [...]}``: an array that encloses an object wins
    over it, an array is also taken when no object follows. A value cut off
    by the end of the text is a failure, never a fragment nested in it."""
    text = (raw or "").strip()
    if not text:
        return None
    fallback = None
    for value, start, end in _values(text, "{["):
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            if "{" in text[start:end]:
                return {"_list": value}
            if fallback is None:
                fallback = value
    return {"_list": fallback} if fallback is not None else None


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
