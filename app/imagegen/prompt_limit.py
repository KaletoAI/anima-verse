"""Prompt character limit — shorten a prompt that a backend would reject.

Some engines refuse a prompt above a fixed number of characters (HTTP 400
"prompt is outside the model's text length bounds"). This module knows the
limit of a backend and fits the final prompt to it before it is sent. It is
GENERAL: every media generation (image, video, mesh) and every backend type
passes the same two places, nothing here names a backend, model, occasion or
use case.

Where the limit comes from (ruling PL1):
  1. the backend entry's ``prompt_char_limit`` (instance config, 0/empty =
     none) — always wins;
  2. otherwise the AI hub's alias schema of the backend's ``model``
     (:func:`hub_prompt_limit`), cached per (url, model) for ``HUB_TTL_S``.
     A backend that never talks to the hub (a direct engine, a cloud API)
     simply gets "no limit" back from that read.
  No limit known → nothing changes, the prompt goes out byte-identical.

Where the shortening runs (ruling PL2): never inside a channel worker, never
under a GPU slot — an LLM wait must not hold a backend slot (and an LLM that
shares a serialize group with the backend would deadlock). The two places:

  * ``ImageBackend.generate()`` (``app/imagegen/base.py``) — the one place
    every prompt passes on its way to an engine — builds the final prompt and
    calls :func:`fit_prompt`. Inside a channel worker that is only a length
    check: an over-limit prompt without a decision raises
    :class:`PromptOverLimit` at once, before anything is sent.
  * ``ImageService.run_on_backend_channel()`` (``app/imagegen/service.py``) —
    the one handoff every generation is submitted through — resolves the
    limit BEFORE the submission, catches that bounce in its own wrapper, runs
    :func:`shorten` on the caller's thread (no slot held) and submits again
    with the decision attached; the second pass sends the shortened prompt.

Shortening: the LLM task ``image_prompt_shorten`` (template
``tasks/image_prompt_shorten.md``, unrouted → ``image_prompt``) condenses the
prompt; its answer must keep every reference token of the prompt. A failed,
empty, refused or token-dropping answer falls back to the cut; an answer
still over the limit is cut too. The cut ends at the last comma or sentence
boundary at or under the limit (else the last word boundary, else a hard
cut), and never inside a reference token such as ``<Picture 1>``.
"""
from __future__ import annotations

import contextvars
import hashlib
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("prompt_limit")

#: The LLM task (app/core/llm_tasks.py); unrouted it borrows "image_prompt".
TASK = "image_prompt_shorten"

#: The hub's alias schema (contract from the ai-hub session, 2026-11-12):
#: ``GET <api_url>/v1/generations/<model>/schema`` → ``prompt_limit``
#: ``{"max_chars": int|null, "unit": "characters",
#: "status": "known"|"partial"|"unknown", "candidates": [...]}``.
#: ``max_chars`` is already the strictest limit across the alias' candidates
#: and counts Unicode codepoints (Python ``len``). The same number is also on
#: ``GET <api_url>/v1/models/<model>`` as ``prompt_max_chars``; the schema is
#: the one read here.
HUB_SCHEMA_PATH = "/v1/generations/{model}/schema"
HUB_LIMIT_FIELD = "prompt_limit"

#: How long one hub answer (a limit OR "no limit") is reused, seconds.
HUB_TTL_S = 600.0
#: Request timeout of the hub read — short: it runs before every submission
#: whose cache entry has expired.
HUB_TIMEOUT_S = 4.0

#: Shortened prompts kept in memory (LLM results only).
CACHE_SIZE = 256

#: A boundary cut that keeps less than this share of the limit throws away
#: too much — the word-boundary cut is used instead.
_MIN_BOUNDARY_SHARE = 0.5
#: An LLM answer shorter than this share of the target is a refusal or lost
#: content — the cut of the original is the safer prompt.
_MIN_ANSWER_SHARE = 0.3

#: Reference wording an edit prompt addresses its images with (see
#: ``prompt_adapters.reference_wording``). The LLM must keep each one, and the
#: cut never ends inside one.
REFERENCE_TOKEN = re.compile(
    r"<Picture\s*\d+>|\bthe (?:first|second|third|fourth|fifth|reference) image\b",
    re.IGNORECASE)
#: Spans the cut must not split: reference wording and any ``<…>`` token.
_PROTECTED = re.compile(REFERENCE_TOKEN.pattern + r"|<[^<>\n]{1,40}>", re.IGNORECASE)
#: Cut boundaries: a comma/semicolon/line break (dropped), a sentence end
#: (kept).
_BOUNDARY = re.compile(r"[,;\n]|[.!?](?=\s|$)")


# ── limit sources ────────────────────────────────────────────────────────

_hub_cache: Dict[Tuple[str, str], Tuple[float, Optional[int]]] = {}
_hub_lock = threading.Lock()


def _positive_int(value: Any) -> Optional[int]:
    """``value`` as a positive int, else None (0, empty, junk = no limit)."""
    if isinstance(value, bool):
        return None
    try:
        n = int(str(value).strip()) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def limit_from_schema(schema: Any) -> Optional[int]:
    """The prompt limit an alias schema states, or None.

    ``prompt_limit.max_chars`` counts when it is a positive int and the
    status is not ``unknown``; null, ``unknown`` or a missing field mean no
    limit is known."""
    if not isinstance(schema, dict):
        return None
    block = schema.get(HUB_LIMIT_FIELD)
    if not isinstance(block, dict):
        return None
    if str(block.get("status") or "").strip().lower() == "unknown":
        return None
    return _positive_int(block.get("max_chars"))


def hub_prompt_limit(api_url: str, model: str, api_key: str = "") -> Optional[int]:
    """The hub's prompt limit for ``model`` behind ``api_url``, or None.

    The ONE reader of the hub source. Cached per (url, model) for
    ``HUB_TTL_S`` — a "no limit" answer too, so a backend that is not a hub
    (404, other JSON, unreachable) costs one request and one debug line per
    TTL, never an error."""
    url = (api_url or "").strip().rstrip("/")
    alias = (model or "").strip()
    if not url or not alias:
        return None
    key = (url, alias)
    now = time.monotonic()
    with _hub_lock:
        hit = _hub_cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    limit: Optional[int] = None
    note = ""
    try:
        import requests
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = requests.get(url + HUB_SCHEMA_PATH.format(model=quote(alias, safe="/:@")),
                            headers=headers, timeout=HUB_TIMEOUT_S)
        if resp.status_code != 200:
            note = f"HTTP {resp.status_code}"
        else:
            try:
                limit = limit_from_schema(resp.json())
            except ValueError:
                note = "no JSON"
            if limit is None and not note:
                note = "no limit stated"
    except Exception as exc:  # noqa: BLE001 — an unreadable hub is "no limit"
        note = type(exc).__name__
    with _hub_lock:
        _hub_cache[key] = (now + HUB_TTL_S, limit)
    if limit is None:
        logger.debug("Hub prompt limit for %s: none (%s)", alias, note)
    else:
        logger.debug("Hub prompt limit for %s: %d chars", alias, limit)
    return limit


def resolve_limit(backend: Any) -> Optional[int]:
    """The effective prompt limit of ``backend``: its manual
    ``prompt_char_limit`` when set, else the hub's, else None."""
    manual = _positive_int(getattr(backend, "prompt_char_limit", 0))
    if manual:
        return manual
    return hub_prompt_limit(getattr(backend, "api_url", "") or "",
                            getattr(backend, "model", "") or "",
                            getattr(backend, "api_key", "") or "")


# ── the cut ──────────────────────────────────────────────────────────────

def cut_to_limit(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` characters: at the last comma or
    sentence boundary that keeps it within the limit, else at the last word
    boundary, else hard — and never inside a reference token."""
    if limit <= 0 or len(text) <= limit:
        return text
    end = 0
    for m in _BOUNDARY.finditer(text):
        keep = m.start() + (1 if text[m.start()] in ".!?" else 0)
        if keep > limit:
            break
        end = keep
    if end < limit * _MIN_BOUNDARY_SHARE:
        space = text.rfind(" ", 0, limit + 1)
        end = space if space >= limit * _MIN_BOUNDARY_SHARE else limit
    for m in _PROTECTED.finditer(text):
        if m.start() < end < m.end():
            end = m.start()
            break
        if m.start() >= end:
            break
    out = text[:end].rstrip(" \t\n,;:-")
    return out or text[:limit]


# ── the LLM pass ─────────────────────────────────────────────────────────

_cache: "OrderedDict[str, Tuple[str, str]]" = OrderedDict()
_cache_lock = threading.Lock()


def cache_key(prompt: str, limit: int) -> str:
    return hashlib.sha256(f"{limit}\0{prompt}".encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[Tuple[str, str]]:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
        return hit


def _cache_put(key: str, text: str, method: str) -> None:
    with _cache_lock:
        _cache[key] = (text, method)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def _clean_answer(answer: str) -> str:
    """The prompt out of an LLM answer: fences, a ``PROMPT:`` label and
    wrapping quotes removed."""
    text = (answer or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    text = re.sub(r"^\s*(?:shortened\s+)?prompt\s*:\s*", "", text, flags=re.IGNORECASE)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def _missing_references(original: str, answer: str) -> list:
    """Reference tokens of ``original`` the answer no longer contains."""
    have = {re.sub(r"\s+", " ", m.group(0)).lower() for m in REFERENCE_TOKEN.finditer(answer)}
    want = []
    for m in REFERENCE_TOKEN.finditer(original):
        token = re.sub(r"\s+", " ", m.group(0)).lower()
        if token not in have and token not in want:
            want.append(token)
    return want


def _llm_shorten(prompt: str, limit: int, character: str) -> Optional[str]:
    """One LLM pass; the cleaned answer, or None when it is unusable."""
    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        target = max(1, int(limit * 0.9))
        system, user = render_task(TASK, prompt=prompt, limit=limit, target=target,
                                   length=len(prompt))
        response = llm_call(task=TASK, system_prompt=system, user_prompt=user,
                            agent_name=character, max_tokens=max(256, limit // 2))
        answer = _clean_answer(getattr(response, "content", "") or "")
    except Exception as exc:  # noqa: BLE001 — a failed pass falls back to the cut
        logger.warning("Prompt shortening: LLM failed (%s) — cutting instead", exc)
        return None
    if not answer:
        logger.warning("Prompt shortening: empty LLM answer — cutting instead")
        return None
    if len(answer) < min(limit, len(prompt)) * _MIN_ANSWER_SHARE:
        logger.warning("Prompt shortening: LLM answer too short (%d chars for a limit "
                       "of %d) — looks like a refusal; cutting instead", len(answer), limit)
        return None
    missing = _missing_references(prompt, answer)
    if missing:
        logger.warning("Prompt shortening: LLM answer dropped reference wording %s "
                       "— cutting instead", missing)
        return None
    return answer


def shorten(prompt: str, limit: int, *, character: str = "",
            use_llm: bool = True) -> Tuple[str, str]:
    """``(text, method)`` with ``len(text) <= limit``.

    method: ``none`` (fits already), ``llm`` (the LLM's condensed prompt),
    ``cut`` (the cut — of the LLM answer when it was still too long, else of
    the original). Blocking when ``use_llm``: call it where no GPU slot is
    held. LLM results are cached by sha(prompt + limit)."""
    if not limit or len(prompt) <= limit:
        return prompt, "none"
    key = cache_key(prompt, limit)
    if use_llm:
        hit = _cache_get(key)
        if hit is not None:
            return hit
        answer = _llm_shorten(prompt, limit, character)
        if answer is not None:
            if len(answer) <= limit:
                _cache_put(key, answer, "llm")
                return answer, "llm"
            logger.info("Prompt shortening: LLM answer still %d chars over a limit of %d "
                        "— cutting it", len(answer), limit)
            text = cut_to_limit(answer, limit)
            _cache_put(key, text, "cut")
            return text, "cut"
    return cut_to_limit(prompt, limit), "cut"


# ── the channel bounce ───────────────────────────────────────────────────

@dataclass
class ChannelContext:
    """Set by ``run_on_backend_channel`` around ``gen_fn`` inside the worker.

    ``limit`` was resolved before the submission (no hub read under the
    slot); ``decisions`` carries the shortenings made on the caller's thread
    for the second pass; ``may_bounce`` is False on that pass — a prompt
    still undecided then is cut in place (no LLM under the slot)."""
    limit: Optional[int]
    may_bounce: bool = True
    decisions: Dict[str, Tuple[str, str]] = field(default_factory=dict)


CHANNEL: contextvars.ContextVar[Optional[ChannelContext]] = contextvars.ContextVar(
    "prompt_limit_channel", default=None)


class PromptOverLimit(BaseException):
    """Raised by ``generate()`` inside a channel worker for an over-limit
    prompt without a decision — BEFORE anything is sent. A BaseException on
    purpose: a gen_fn's broad ``except Exception`` must not swallow it; the
    wrapper in ``run_on_backend_channel`` catches it and shortens outside the
    slot."""

    def __init__(self, prompt: str, limit: int, character: str):
        super().__init__(f"prompt of {len(prompt)} chars over a limit of {limit}")
        self.prompt = prompt
        self.limit = limit
        self.character = character
        self.key = cache_key(prompt, limit)


@dataclass
class FitResult:
    prompt: str
    limit: Optional[int]
    method: str
    unshortened: str


def fit_prompt(backend: Any, prompt: str, *, character: str = "") -> FitResult:
    """The prompt ``backend`` gets sent — called by ``generate()`` on the
    final prompt. No limit, or within it: the prompt unchanged."""
    if not prompt:
        return FitResult(prompt, None, "none", prompt)
    ctx = CHANNEL.get()
    limit = ctx.limit if ctx is not None else resolve_limit(backend)
    if not limit or len(prompt) <= limit:
        return FitResult(prompt, limit, "none", prompt)
    key = cache_key(prompt, limit)
    if ctx is not None:
        decided = ctx.decisions.get(key)
        if decided is None:
            decided = _cache_get(key)
        if decided is None:
            if ctx.may_bounce:
                raise PromptOverLimit(prompt, limit, character)
            decided = (cut_to_limit(prompt, limit), "cut")
        text, method = decided
    else:
        text, method = shorten(prompt, limit, character=character)
    logger.info("%s: prompt shortened %d -> %d chars (limit %d, %s)",
                getattr(backend, "name", "?"), len(prompt), len(text), limit, method)
    return FitResult(text, limit, method, prompt)
