"""Opt-in LLM stage of the prompt composer (phase 3).

The mechanical composer (``prompt_compose.py``) weaves style, subject and
shape hints into one grammatical prompt — but it cannot make a THIN subject
dense. The café restroom showed it: three fixtures on 2 × 2.5 m, and the
model scattered them across a mostly empty slab. A dense room text like the
kitchen's works only because a human wrote it by hand.

This stage rewrites the composed prompt into one coherent English prompt
that names the concrete objects the subject implies and fills the footprint
— positively exhaustive, no negations, style frame intact. It is:

- **opt-in** per use case (``image_generation.use_cases.<uc>.llm_compose``)
  or per click in the render dialog — never implicit (cost + latency),
- **never blocking**: any failure returns the mechanical result plus a
  warning, so a render never dies on the LLM,
- **cached** per (style, subject, hint, family, template) so a regenerate
  series and a batch run cost exactly one call.

Unlike ``prompt_compose`` this module may do I/O (LLM call, cache table).
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.core import prompt_compose
from app.core.log import get_logger
from app.core.prompt_compose import Composed, split_negations

logger = get_logger("prompt_compose_llm")

TEMPLATE = "image_prompt_compose"
# Hard cap: a composed prompt is 60-150 words. Anything beyond this is the
# model rambling or looping, not a prompt (see the validation guards).
MAX_TOKENS = 400

# Strip what a chatty model wraps around the answer despite "ONLY the prompt".
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_LABEL_RE = re.compile(r"^\s*(?:final\s+)?prompt\s*:\s*", re.IGNORECASE)
# Quality checks on the LLM's answer — reported, never silently repaired
# (the dialog shows the prompt; the user decides).
_NEG_WORD_RE = re.compile(r"\b(?:no|not|without|ohne|kein(?:e|en|er|em|es)?)\b",
                          re.IGNORECASE)
_MEASURE_RE = re.compile(r"\d+(?:[.,]\d+)?\s+by\s+\d+(?:[.,]\d+)?\s+met(?:re|er)s?",
                         re.IGNORECASE)


def _template_stamp() -> str:
    """Modification time of the template — part of the cache key, so editing
    the template in /admin/templates invalidates the cached prompts."""
    from app.core.prompt_templates import template_search_dirs
    for directory in template_search_dirs():
        path = directory / "tasks" / f"{TEMPLATE}.md"
        if path.exists():
            return str(int(path.stat().st_mtime))
    return "0"


def cache_key(style: str, subject: str, hint: str, family: str,
              conditions: str = "") -> str:
    """Cache identity of one composed prompt.

    ``conditions`` (the outdoor weather clause) is part of the key on
    purpose: without it the first summer render of a place would be served
    back in the middle of a blizzard.
    """
    parts = "\x1f".join([style, subject, hint, family, conditions,
                         _template_stamp()])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[str]:
    from app.core.db import get_connection
    try:
        row = get_connection().execute(
            "SELECT prompt FROM prompt_compose_cache WHERE key = ?", (key,)
        ).fetchone()
    except Exception as e:  # a missing table must never break a render
        logger.debug("prompt compose cache read failed: %s", e)
        return None
    return row["prompt"] if row else None


def _cache_put(key: str, prompt: str) -> None:
    # No eviction in the pilot: one row per distinct (style, subject, hint,
    # family, template) — a few hundred bytes each, and a template edit
    # simply starts a new generation of keys.
    from app.core.db import transaction
    from app.core.timeutils import utc_now
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prompt_compose_cache "
                "(key, prompt, created_at) VALUES (?, ?, ?)",
                (key, prompt, utc_now().isoformat(timespec="seconds")))
    except Exception as e:
        logger.debug("prompt compose cache write failed: %s", e)


def _clean(text: str) -> str:
    out = _FENCE_RE.sub("", (text or "").strip()).strip()
    out = _LABEL_RE.sub("", out).strip()
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'":
        out = out[1:-1].strip()
    return out


# A composed prompt is 60-150 words. Beyond this the model is rambling.
MAX_WORDS = 220
# Repetition guard (the loop failure mode): a 5-word shingle that comes back
# this often means the model is enumerating itself into the token budget
# ("a small chrome toilet brush holder base gasket, a white ceramic sink
# faucet base seal, …" — observed 2026-07-26).
SHINGLE = 5
MAX_SHINGLE_REPEATS = 3


def degenerate_reason(text: str) -> str:
    """Why this answer is unusable, or "" when it looks like a prompt.

    max_tokens alone does not help against a looping model — it fills the
    budget. So the answer is checked, and a degenerate one is DISCARDED
    (mechanical prompt + warning) instead of cached.
    """
    words = (text or "").split()
    if len(words) > MAX_WORDS:
        return f"rambling ({len(words)} words)"
    counts: dict = {}
    for i in range(len(words) - SHINGLE + 1):
        key = " ".join(w.lower() for w in words[i:i + SHINGLE])
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > MAX_SHINGLE_REPEATS:
            return "repetition loop"
    return ""


def _frame_tail(style: str) -> str:
    """The last few words of the style frame — the marker for "the model kept
    the frame". Rule 5 of the template asks for exactly this ending."""
    words = (style or "").split()
    return " ".join(words[-4:]).lower() if len(words) >= 4 else ""


def repair(text: str, style: str, hint: str) -> tuple:
    """(prompt, notes) — put back what the model dropped.

    A small model reliably writes the dense subject but loses the style
    frame or the measurements every few runs (measured 2026-07-26). Both are
    mechanically restorable, so they are: the frameless answer is re-woven
    through the SAME slot mechanic the mechanical stage uses, and the hint
    block goes back in front. The notes say what happened — the dialog shows
    the finished prompt, nothing is repaired invisibly.
    """
    notes = []
    tail = _frame_tail(style)
    if tail and tail not in (text or "").lower():
        text = prompt_compose.weave_subject(style, text)[0]
        notes.append("The LLM prompt lost the style frame — it was re-woven "
                     "into the use-case style.")
    # Marker for "the hint survived": its measurements when it has any,
    # otherwise its opening words (a hint without a scale anchor).
    measure = _MEASURE_RE.search(hint or "")
    marker = measure.group(0) if measure else " ".join((hint or "").split()[:4])
    if marker and marker.lower() not in (text or "").lower():
        text = prompt_compose.prepend_hints(text, hint)
        notes.append(f"The LLM prompt dropped the footprint (\"{marker}\") — "
                     f"the hint was put back in front.")
    return text, notes


def quality_warnings(text: str, negative: str) -> list:
    """What the LLM let slip and nothing can mechanically fix. Deterministic,
    so a cache hit reports the same thing as the fresh call — and nothing is
    rewritten behind the user's back: the prompt is editable in the dialog.

    The second check needs no list of forbidden words: whatever the use case
    pushes away in its NEGATIVE has no business in the positive prompt. That
    catches the "wall-mounted mirror" in a wall-less diorama without this
    module ever naming a use case.
    """
    out = []
    low = (text or "").lower()
    if _NEG_WORD_RE.search(text or ""):
        out.append("The LLM prompt still contains a negation word — a "
                   "diffusion model draws what a negation names.")
    hits = []
    for tag in (negative or "").split(","):
        tag = tag.strip().lower()
        if len(tag) < 4 or tag in hits:
            continue
        pattern = (re.escape(tag) if " " in tag
                   else r"\b" + re.escape(tag) + r"\b")
        if re.search(pattern, low):
            hits.append(tag)
        if len(hits) >= 4:
            break
    if hits:
        out.append(f"The LLM prompt names what the negative prompt pushes "
                   f"away: {', '.join(hits)}.")
    return out


def llm_compose(composed: Composed, *, use_case: str, subject: str,
                family: str) -> Composed:
    """Run the LLM stage on a mechanically composed prompt.

    Returns a NEW :class:`Composed` with the rewritten prompt; the negative
    is untouched (the guard already moved the negated items there). On any
    failure the input is returned unchanged, with a warning appended.
    """
    from app.core import config as _cfg

    hint = str(composed.meta.get("hint_rendered") or "")
    # Open-air weather clause (empty indoors) — the mechanical stage already
    # wove it in; the rewrite has to be told about it or it drops out.
    conditions = str(composed.meta.get("conditions") or "")
    style = (_cfg.get_use_case_prompts(use_case, family).get("prompt_style")
             or "")
    # The guard's cleaned subject — same deterministic function the
    # mechanical stage used, so the cache key matches what was composed.
    clean_subject = split_negations(subject)[0]

    def _fail(msg: str) -> Composed:
        return Composed(
            prompt=composed.prompt, negative=composed.negative,
            warnings=list(composed.warnings) + [msg],
            meta={**composed.meta, "llm_composed": False, "cache_hit": False})

    key = cache_key(style, clean_subject, hint, family, conditions)
    cached = _cache_get(key)
    if cached:
        logger.info("LLM compose (%s): cache hit", use_case)
        # Repair runs on the cached text too — it is idempotent (a prompt
        # that carries frame and footprint passes through untouched) and an
        # entry written before a repair rule existed is fixed on read.
        text, notes = repair(cached, style, hint)
        return Composed(
            prompt=text, negative=composed.negative,
            warnings=(list(composed.warnings) + notes
                      + quality_warnings(text, composed.negative)),
            meta={**composed.meta, "llm_composed": True, "cache_hit": True})

    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        system, user = render_task(TEMPLATE, hints=hint, style=style,
                                   subject=clean_subject, family=family,
                                   conditions=conditions,
                                   is_outdoor=bool(conditions))
        response = llm_call(task="image_prompt", system_prompt=system,
                            user_prompt=user, max_tokens=MAX_TOKENS,
                            label=f"compose:{use_case}")
        text = _clean(getattr(response, "content", "") or "")
    except Exception as e:
        logger.warning("LLM compose failed (%s): %s", use_case, e)
        return _fail("LLM compose failed — using the mechanical prompt.")
    if not text:
        logger.warning("LLM compose returned nothing (%s)", use_case)
        return _fail("LLM compose failed — using the mechanical prompt.")
    bad = degenerate_reason(text)
    if bad:
        logger.warning("LLM compose discarded (%s): %s", use_case, bad)
        return _fail(f"LLM compose produced an unusable answer ({bad}) — "
                     f"using the mechanical prompt.")
    text, notes = repair(text, style, hint)
    for note in notes:
        logger.info("LLM compose repair (%s): %s", use_case, note)

    _cache_put(key, text)
    logger.info("LLM compose (%s): %d -> %d chars", use_case,
                len(composed.prompt), len(text))
    return Composed(
        prompt=text, negative=composed.negative,
        warnings=(list(composed.warnings) + notes
                  + quality_warnings(text, composed.negative)),
        meta={**composed.meta, "llm_composed": True, "cache_hit": False})
