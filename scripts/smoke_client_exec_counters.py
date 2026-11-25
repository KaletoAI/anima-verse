#!/usr/bin/env python3
"""Smoke run for the CLIENT-EXECUTION ROUTE COUNTERS (plan E0/E1, task 1).

``request_timing._record`` runs on the event loop. For the three routes the
client-execution redesign watches (``CLIENT_EXEC_ROUTES``: /play/pos,
/play/worldmap, /play/orders) it counts one ``<METHOD>:<route>`` event under
the hot-path name ``client_exec_routes`` -- with ``flush=False``, so the
loop never formats or logs a flush round itself; the next ordinary
``count``/``record`` (or an explicit ``flush``) writes the line.

Runs against THROWAWAY storage/instance/clips directories -- never a real
world, no server, no LLM. Every case sets the flush clock itself
(``hps._last_flush = ...``) and flushes with an explicit ``now``.

Hand-derived expectations
-------------------------

[C1] _last_flush = t0 - 120 (the minute is long over), then
     count("x", "k", flush=False): a flush=True call would log at once, a
     flush=False call must not -> the logger recorder has 0 calls.
     flush(now=t0 + 61): 181 s >= 60 s since the last flush -> exactly
     ["hot_path x k=1"] (one key, n = 1).
[C2] _last_flush = t0 - 120; count("client_exec_routes", "POST:/play/pos",
     flush=False) x3 (no logging), then count("other", "a") with the default
     flush=True -> one flush round; count lines are ordered by name
     alphabetically ("client_exec_routes" < "other"), so the recorder holds
     exactly
       ["hot_path client_exec_routes POST:/play/pos=3", "hot_path other a=1"].
[C3] fresh clock _last_flush = t0 (no automatic flush may fire);
     _record("/play/pos", "POST", 200, 3.0, 10, "ok") x2,
     _record("/play/worldmap", "GET", 200, 5.0, 10, "ok") x1,
     _record("/characters/{name}", "GET", 200, 1.0, 10, "ok") x4.
     Only the first two routes are in CLIENT_EXEC_ROUTES; _count_line sorts
     by n descending (2 before 1) -> flush(now=t0 + 61) is exactly
       ["hot_path client_exec_routes POST:/play/pos=2 GET:/play/worldmap=1"]
     and the characters route never appears (it was recorded 4 times, more
     than either counted route, so a wrong filter would show up first).
     All ms <= 250, so no slow-request row is queued.
[C4] hps.count patched to raise RuntimeError: _record("/play/pos", "POST",
     200, 1.0, 1, "ok") raises nothing, and its timing sample still lands
     (route_stats has a POST /play/pos row whose n grew by 1).

Usage:  ./.venv/bin/python scripts/smoke_client_exec_counters.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="client-exec-counters-storage-")
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp(prefix="client-exec-counters-instance-")
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="client-exec-counters-clips-")

from app.core import paths  # noqa: E402
paths.init(os.environ["STORAGE_DIR"])

from app.core import hot_path_stats as hps  # noqa: E402
from app.core import request_timing  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class Recorder:
    """Stands in for the hot_path logger and keeps every INFO line."""

    def __init__(self):
        self.lines = []

    def info(self, line, *a, **k):
        self.lines.append(line)

    def debug(self, *a, **k):
        pass

    warning = error = debug


def reset() -> float:
    """Empty the collector and pin its flush clock to now; returns t0."""
    hps.flush(now=hps._last_flush + 10_000.0)
    t0 = time.monotonic()
    hps._last_flush = t0
    return t0


def with_recorder(fn):
    real = hps.logger
    rec = Recorder()
    hps.logger = rec
    try:
        fn(rec)
    finally:
        hps.logger = real


def c1():
    print("\n[C1] count(flush=False) never logs, an explicit flush does")

    def run(rec):
        t0 = reset()
        hps._last_flush = t0 - 120.0
        hps.count("x", "k", flush=False)
        check("C1 no logger call", len(rec.lines), 0)
        check("C1 explicit flush", hps.flush(now=t0 + 61), ["hot_path x k=1"])
    with_recorder(run)


def c2():
    print("\n[C2] the next ordinary count flushes the silent counts too")

    def run(rec):
        t0 = reset()
        hps._last_flush = t0 - 120.0
        for _ in range(3):
            hps.count("client_exec_routes", "POST:/play/pos", flush=False)
        check("C2 silent so far", len(rec.lines), 0)
        hps.count("other", "a")
        check("C2 one flush round", rec.lines,
              ["hot_path client_exec_routes POST:/play/pos=3",
               "hot_path other a=1"])
    with_recorder(run)


def c3():
    print("\n[C3] _record counts exactly the client-execution routes")
    check("C3 route set", request_timing.CLIENT_EXEC_ROUTES,
          frozenset({"/play/pos", "/play/worldmap", "/play/orders"}))
    t0 = reset()
    for _ in range(2):
        request_timing._record("/play/pos", "POST", 200, 3.0, 10, "ok")
    request_timing._record("/play/worldmap", "GET", 200, 5.0, 10, "ok")
    for _ in range(4):
        request_timing._record("/characters/{name}", "GET", 200, 1.0, 10, "ok")
    check("C3 line", hps.flush(now=t0 + 61),
          ["hot_path client_exec_routes POST:/play/pos=2 GET:/play/worldmap=1"])


def _pos_n():
    for row in request_timing.route_stats():
        if row["route"] == "/play/pos" and row["method"] == "POST":
            return row["n"]
    return 0


def c4():
    print("\n[C4] a throwing counter never reaches _record's caller")
    real = hps.count

    def boom(*a, **k):
        raise RuntimeError("counter down")

    before = _pos_n()
    hps.count = boom
    raised = None
    try:
        try:
            request_timing._record("/play/pos", "POST", 200, 1.0, 1, "ok")
        except Exception as e:  # noqa: BLE001
            raised = e
    finally:
        hps.count = real
    check("C4 nothing raised", raised, None)
    check("C4 sample still recorded", _pos_n(), before + 1)
    reset()


def main() -> int:
    for case in (c1, c2, c3, c4):
        try:
            case()
        except Exception as e:  # noqa: BLE001
            global CHECKED
            CHECKED += 1
            print(f"  ✗ {case.__name__} crashed: {type(e).__name__}: {e}")
            FAILURES.append(case.__name__)
    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
