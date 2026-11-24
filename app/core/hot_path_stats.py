"""Hot-path statistics: one log line per minute and measured path.

Request handlers and writers call ``record`` (a measurement: one sample with
named values, e.g. the phases of a worldmap build in milliseconds) or ``count``
(an event counter, e.g. which caller sent which sync topic). Nothing runs on a
thread of its own: every ``record``/``count`` checks the monotonic clock and,
at most once per ``FLUSH_INTERVAL_S``, turns the collected data into lines and
writes them through ``get_logger("hot_path")`` at INFO.

Line formats (parsed by the baseline evaluation, keep them stable):

    hot_path <name> n=<n> <key>_p50=<x> <key>_p95=<y> ...
        keys sorted, values rounded to 0.1, p95 = nearest-rank percentile
        (the same rule as ``request_timing.route_stats``)
    hot_path <name> <key>=<n> ...
        descending by n, alphabetical on equal n; at most ``MAX_COUNT_KEYS``
        keys, the rest summed as ``other=<n>``

Statistics must never disturb the measured path: ``record``/``count`` never
raise, only the data swap happens under the lock, formatting and logging run
after it.
"""
import math
import threading
import time
from statistics import median
from typing import Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("hot_path")

FLUSH_INTERVAL_S = 60.0
MAX_COUNT_KEYS = 40
# Bound per key and minute: a runaway caller costs memory, never more than this.
MAX_SAMPLES = 20000

_clock = time.monotonic
_lock = threading.Lock()
_measures: Dict[str, Dict[str, object]] = {}   # name -> {"n": int, "vals": {key: [float]}}
_counts: Dict[str, Dict[str, int]] = {}        # name -> {key: n}
_last_flush = _clock()


def _maybe_flush() -> None:
    # Racy read on purpose: the lock is only taken once the minute is over.
    if _clock() - _last_flush >= FLUSH_INTERVAL_S:
        flush()


def record(name: str, values: Dict[str, float]) -> None:
    """Take one measurement of ``name`` with its named values. Thread-safe."""
    try:
        clean = {str(k): float(v) for k, v in (values or {}).items()}
        with _lock:
            slot = _measures.get(name)
            if slot is None:
                slot = _measures[name] = {"n": 0, "vals": {}}
            slot["n"] += 1
            vals = slot["vals"]
            for k, v in clean.items():
                lst = vals.get(k)
                if lst is None:
                    lst = vals[k] = []
                if len(lst) < MAX_SAMPLES:
                    lst.append(v)
        _maybe_flush()
    except Exception:
        pass


def count(name: str, key: str) -> None:
    """Count one event ``key`` under ``name``. Thread-safe."""
    try:
        with _lock:
            slot = _counts.get(name)
            if slot is None:
                slot = _counts[name] = {}
            slot[key] = slot.get(key, 0) + 1
        _maybe_flush()
    except Exception:
        pass


def _fmt(x: float) -> str:
    return f"{round(x, 1):.1f}"


def _measure_line(name: str, n: int, vals: Dict[str, List[float]]) -> str:
    parts = [f"hot_path {name} n={n}"]
    for key in sorted(vals):
        times = sorted(vals[key])
        if not times:
            continue
        p95 = times[math.ceil(.95 * len(times)) - 1]
        parts.append(f"{key}_p50={_fmt(median(times))} {key}_p95={_fmt(p95)}")
    return " ".join(parts)


def _count_line(name: str, counts: Dict[str, int]) -> str:
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown, rest = ranked[:MAX_COUNT_KEYS], ranked[MAX_COUNT_KEYS:]
    parts = [f"hot_path {name}"] + [f"{k}={n}" for k, n in shown]
    if rest:
        parts.append(f"other={sum(n for _, n in rest)}")
    return " ".join(parts)


def flush(now: Optional[float] = None) -> List[str]:
    """Return the finished lines and empty the store — at most once per
    ``FLUSH_INTERVAL_S`` of monotonic time (earlier calls return ``[]`` and
    keep the data). The lines are also logged at INFO. Never raises."""
    global _measures, _counts, _last_flush
    try:
        t = _clock() if now is None else float(now)
        with _lock:
            if t - _last_flush < FLUSH_INTERVAL_S:
                return []
            measures, counts = _measures, _counts
            _measures, _counts = {}, {}
            _last_flush = t
        lines = [_measure_line(name, int(slot["n"]), slot["vals"])
                 for name, slot in sorted(measures.items())]
        lines += [_count_line(name, c) for name, c in sorted(counts.items()) if c]
    except Exception:
        return []
    for line in lines:
        try:
            logger.info(line)
        except Exception:
            pass
    return lines
