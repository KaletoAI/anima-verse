"""Hot-path statistics: one log line per measured name and minute.

``record(name, values)`` takes one measurement (several values, e.g. the
phases of one ``GET /play/worldmap``), ``count(name, key)`` counts one event.
``flush`` turns everything collected into finished lines and writes them
through ``get_logger("hot_path")`` at INFO — at most once per 60 s of
monotonic time. There is no thread of its own: ``record``/``count`` call
``flush`` after collecting.

Line formats::

    hot_path <name> n=<n> <key>_p50=<x> <key>_p95=<y> ...   (keys sorted)
    hot_path <name> <key>=<n> ...                            (by n desc, ties
                                                              alphabetical,
                                                              at most 40 keys,
                                                              rest as other=)

p95 is the nearest-rank percentile, like ``request_timing.route_stats``;
values are rounded to 0.1.

Statistics must never disturb the measured path: every entry point swallows
its own errors, the lock only guards swapping data, and formatting and
logging run after the lock is released.
"""
import math
import threading
import time
from statistics import median
from typing import Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("hot_path")

FLUSH_S = 60.0
MAX_COUNT_KEYS = 40
MAX_SAMPLES = 10_000   # per name and key and minute; bounds memory, not accuracy

_lock = threading.Lock()
_samples: Dict[str, Dict[str, List[float]]] = {}
_n: Dict[str, int] = {}
_counts: Dict[str, Dict[str, int]] = {}
_last_flush = time.monotonic()


def record(name: str, values: Dict[str, float]) -> None:
    """Take one measurement of ``name`` (one value per key). Thread-safe,
    never raises."""
    try:
        with _lock:
            _n[name] = _n.get(name, 0) + 1
            per = _samples.setdefault(name, {})
            for key, value in values.items():
                lst = per.setdefault(key, [])
                if len(lst) < MAX_SAMPLES:
                    lst.append(float(value))
        flush()
    except Exception:
        pass


def count(name: str, key: str) -> None:
    """Count one event ``key`` under ``name``. Thread-safe, never raises."""
    try:
        with _lock:
            per = _counts.setdefault(name, {})
            per[key] = per.get(key, 0) + 1
        flush()
    except Exception:
        pass


def _fmt(x: float) -> str:
    return f"{round(x, 1):.1f}"


def _measure_line(name: str, n: int, per: Dict[str, List[float]]) -> str:
    parts = [f"hot_path {name} n={n}"]
    for key in sorted(per):
        vals = sorted(per[key])
        if not vals:
            continue
        p95 = vals[math.ceil(.95 * len(vals)) - 1]
        parts.append(f"{key}_p50={_fmt(median(vals))} {key}_p95={_fmt(p95)}")
    return " ".join(parts)


def _count_line(name: str, per: Dict[str, int]) -> str:
    ranked = sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = [f"hot_path {name}"]
    parts += [f"{k}={n}" for k, n in ranked[:MAX_COUNT_KEYS]]
    rest = sum(n for _, n in ranked[MAX_COUNT_KEYS:])
    if rest:
        parts.append(f"other={rest}")
    return " ".join(parts)


def flush(now: Optional[float] = None) -> List[str]:
    """Return the finished lines and empty the collector — but only once
    ``FLUSH_S`` have passed since the last flush (``[]`` before that, the
    data stays). The lines are logged at INFO as well. Never raises."""
    global _samples, _n, _counts, _last_flush
    try:
        now = time.monotonic() if now is None else now
        with _lock:
            if now - _last_flush < FLUSH_S:
                return []
            _last_flush = now
            samples, ns, counts = _samples, _n, _counts
            _samples, _n, _counts = {}, {}, {}
        lines = [_measure_line(name, ns.get(name, 0), samples[name])
                 for name in sorted(samples)]
        lines += [_count_line(name, counts[name]) for name in sorted(counts)
                  if counts[name]]
        for line in lines:
            try:
                logger.info(line)
            except Exception:
                pass
        return lines
    except Exception:
        return []
