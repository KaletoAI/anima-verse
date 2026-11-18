"""How often AUTOMATIC work may come back after a retryable end (``app.blender.outcome.is_retryable``).

A timeout, an interruption or Blender being unavailable judges nothing, so the work stays due. Without a bound a
piece that ALWAYS times out would be tried again on every trigger — every payload, every scene compose, every
improvements tick — for good. So an automatic caller asks ``may_try(key)`` before it starts, and reports how the
run ended with ``note(key, outcome)``:

- a retryable end defers the key — ``DELAYS_S[0]`` (5 min) after the first in a row, ``DELAYS_S[1]`` (20 min) after
  the second — and the ``HOLD_AFTER``-th (3rd) in a row holds it until the process restarts, with ONE warning that
  names the key;
- ok, a verdict or a crash clears the key; ``None`` (no run decided anything: load, a pause, a held run) and
  ``cancelled`` (someone stopped it) change nothing.

User-triggered work (a Build click, an explicit route, a garment run the user started) never asks: the user is
the bound. Its outcome is still noted, so a success clicked by hand frees an automatic key again.

In-memory on purpose (one server process; a restart forgetting the count costs one more try). A plain dict with a
lock and the monotonic clock — no class hierarchy.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

from app.blender import outcome as oc

logger = logging.getLogger(__name__)

#: The wait after the 1st and the 2nd retryable end in a row.
DELAYS_S: Tuple[float, ...] = (300.0, 1200.0)
#: The retryable end in a row that holds the key until restart.
HOLD_AFTER = 3

#: key -> (retryable ends in a row, monotonic time before which it may not run; ``inf`` = held).
_state: Dict[str, Tuple[int, float]] = {}
_lock = threading.Lock()


def may_try(key: str) -> bool:
    """Whether an automatic caller may run ``key`` now."""
    with _lock:
        entry = _state.get(key)
    return entry is None or time.monotonic() >= entry[1]


def held(key: str) -> bool:
    """Whether ``key`` is held until restart (``HOLD_AFTER`` retryable ends in a row)."""
    with _lock:
        entry = _state.get(key)
    return entry is not None and entry[0] >= HOLD_AFTER


def note(key: str, outcome: Optional[str]) -> None:
    """Record how a run of ``key`` ended (module docstring)."""
    if outcome is None or outcome == oc.CANCELLED:
        return
    if not oc.is_retryable(outcome):
        with _lock:
            _state.pop(key, None)
        return
    with _lock:
        count = _state.get(key, (0, 0.0))[0] + 1
        until = (float("inf") if count >= HOLD_AFTER
                 else time.monotonic() + DELAYS_S[min(count, len(DELAYS_S)) - 1])
        _state[key] = (count, until)
    if count == HOLD_AFTER:
        logger.warning("Blender work %s kept timing out / being interrupted (%d times in a row, last: %s) — held "
                       "until restart; a user action still runs it", key, count, outcome)
    else:
        logger.info("Blender work %s left due (%s, %d in a row) — automatic retry in %ds", key, outcome, count,
                    int(DELAYS_S[min(count, len(DELAYS_S)) - 1]))


def reset() -> None:
    """Forget every key (tests)."""
    with _lock:
        _state.clear()
