"""How much of a pool's prompt the backend served from its cache, lately.

A ring of the last :data:`RING_SIZE` calls per pool (``provider/model``), fed
from ``app/utils/llm_logger.log_llm_call`` — the one place that already knows
the lane, the cache key and what the provider reported as cached prompt
tokens. In memory only: the lane view of ``/admin/agent-loop`` asks it once
per poll, and reading ``logs/llm_calls.jsonl`` inside a request would mean
parsing a growing file every five seconds for a number that is only ever
looked at while somebody watches the page.

NOT REPORTED IS NOT ZERO. A backend that says nothing about its prompt cache
(``tokens_cached=None``) is a different finding from one that reports a cold
cache (0): the first means we cannot see whether the lanes work, the second
means they did not. The sample keeps ``cached=None`` and the summary counts
those samples separately, exactly as ``tokens.cached`` is left out of the
JSONL and as the ⚡ line of the player UI distinguishes the two
(``packages/player-ui/src/SceneView.tsx``).

The ring is process-local and starts empty after a restart — it describes what
is happening right now, not a history. Time is SYSTEM time
(``time.monotonic``): these are technical stamps, never game logic.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional

# How many calls per pool are kept. Twenty is about two minutes of a busy
# conversation — long enough that a single cold call does not dominate the
# share, short enough that the number still describes the present.
RING_SIZE = 20


@dataclass(frozen=True)
class CallSample:
    """One finished LLM call on a pool.

    ``cached`` is ``None`` when the provider reported no cache figure at all.
    ``lane`` is ``None`` for a call that ran without a lane (an unlaned
    fallback path) — it still belongs to this model's cache, which is why it
    is recorded, but the view can tell the two apart.
    """
    prompt_tokens: int
    cached: Optional[int]
    cache_key: str
    lane: Optional[int]
    at: float


_lock = threading.Lock()
_rings: Dict[str, Deque[CallSample]] = {}


def record_call(provider: str, model: str, prompt_tokens: int,
                cached: Optional[int], *, lane: Optional[int] = None,
                cache_key: str = "", error: str = "") -> None:
    """Remembers one call for the pool ``provider/model``.

    The key is built with ``pool_key_for``, the same function the lanes use —
    a call whose provider could not be resolved is laned under ``?/<model>``
    and has to be counted there, or that pool shows busy lanes next to "no
    calls yet".

    Skipped without a model (the call cannot be attributed to a pool), for a
    failed call and for a call that reports no prompt tokens at all: neither
    says anything about a prompt cache, and both would only dilute the
    "reported" count that decides between "not reported" and a real share.
    """
    if error or not model:
        return
    try:
        prompt = int(prompt_tokens)
    except (TypeError, ValueError):
        return
    if prompt <= 0:
        return
    from app.core.llm_lanes import pool_key_for
    key = pool_key_for(provider, model)
    sample = CallSample(prompt_tokens=prompt,
                        cached=(None if cached is None else int(cached)),
                        cache_key=cache_key or "",
                        lane=(None if lane is None else int(lane)),
                        at=time.monotonic())
    with _lock:
        ring = _rings.get(key)
        if ring is None:
            ring = deque(maxlen=RING_SIZE)
            _rings[key] = ring
        ring.append(sample)


def pool_stats(pool_key: str) -> Dict[str, Any]:
    """The cache share of the last calls on this pool.

    ``pct`` is ``None`` when NOT ONE of the samples carried a figure — the
    honest answer "the backend does not report it", which the view must not
    print as 0 %. With at least one report, ``pct`` is the share of the
    reported calls' prompt tokens that came from the cache; samples without a
    figure are left out of both sums rather than counted as zero, or a single
    silent provider would drag a working cache towards 0 %.

    ``samples`` counts every call in the ring, ``reported`` only those with a
    figure — the difference is what makes a 0 % readable.
    """
    with _lock:
        ring = list(_rings.get(pool_key) or ())
    reported = [s for s in ring if s.cached is not None]
    prompt_sum = sum(s.prompt_tokens for s in reported)
    cached_sum = sum(int(s.cached or 0) for s in reported)
    pct: Optional[float]
    if not reported:
        pct = None
    elif prompt_sum <= 0:
        pct = 0.0
    else:
        pct = round(100.0 * cached_sum / prompt_sum, 1)
    return {
        "samples": len(ring),
        "reported": len(reported),
        "prompt_tokens": prompt_sum,
        "cached_tokens": cached_sum,
        "pct": pct,
        "text": stats_text(len(ring), len(reported), pct),
    }


def stats_text(samples: int, reported: int, pct: Optional[float]) -> str:
    """The one-line form the admin view prints.

    Built here, not in the browser, so the three states — nothing seen yet,
    seen but not reported, a real share — are one decision in one place and a
    check can read them. English source strings, like every admin string.
    """
    if not samples:
        return "no calls yet"
    if pct is None:
        return f"cache not reported ({samples} calls)"
    return f"{pct:g} % cached (last {reported} of {samples} calls)"


def snapshot() -> Dict[str, Dict[str, Any]]:
    """``pool_stats`` for every pool the ring has seen."""
    with _lock:
        keys = list(_rings)
    return {key: pool_stats(key) for key in keys}


def reset() -> None:
    """Drops every ring — for checks only."""
    with _lock:
        _rings.clear()
