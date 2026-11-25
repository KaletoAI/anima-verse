#!/usr/bin/env python3
"""Smoke run for the world-admin tick: a long sub-task runs BESIDE the loop.

Runs against a THROWAWAY storage directory; the sub-task table is replaced by
two fakes, so nothing of a world is touched.

Background (2026-11-25): ``npc_wanderers`` baked a wanderer's route inside the
tick (nav-grid A*) and held every other sub-task for 2076 s. The search is
cheaper and budgeted now, but a valid route across a large world still takes
up to a minute, so ``npc_wanderers`` runs as its own task with a "still running
-> skip" guard, and a sub-task over 30 s is a WARNING.

Hand-derived expectations:

  [1] ``_log_duration``: 31.0 s -> one WARNING naming the label; 6.0 s -> one
      INFO "done in 6.0s"; 4.0 s -> nothing (the 5 s INFO threshold is
      unchanged).
  [2] The loop with the table [(slow "npc_wanderers", 0 s), (fast
      "status_tick", 0 s)], tick interval 0 (one 20 ms pause per sweep), the
      slow fake blocked until released. During the first 0.5 s the slow fake
      must have STARTED exactly once — every later sweep finds it running and
      skips it — while the fast one ran on every sweep: at 20 ms per sweep
      that is about 25 runs, checked as >= 5 (the old sequential loop: 0,
      because the fast one waits behind the slow one). After the release the
      slow fake finishes and its ``_last_run`` stamp is set.

Usage:  ./.venv/bin/python scripts/smoke_admin_tick_detached.py
"""
import asyncio
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="admin-tick-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="admin-tick-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)

from app.core import periodic_jobs as pj  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    if actual == expected:
        print(f"  ✓ {label}: {actual!r}")
    else:
        FAILURES.append(label)
        print(f"  ✗ {label}: got {actual!r}, expected {expected!r}")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelname, record.getMessage()))


CAP = Capture()
pj.logger.addHandler(CAP)
pj.logger.setLevel(logging.INFO)

print("[1] the slow-sub-task log line")
pj._log_duration("npc_wanderers", 31.0)
check("31 s: one WARNING", [lv for lv, _ in CAP.records], ["WARNING"])
check("...naming the label", "npc_wanderers" in CAP.records[0][1], True)
CAP.records.clear()
pj._log_duration("status_tick", 6.0)
check("6 s: one INFO", CAP.records, [("INFO", "admin_tick status_tick done in 6.0s")])
CAP.records.clear()
pj._log_duration("status_tick", 4.0)
check("4 s: nothing", CAP.records, [])

print("[2] the slow sub-task runs beside the loop")
release = threading.Event()
counts = {"slow": 0, "fast": 0}


def slow():
    counts["slow"] += 1
    release.wait(10.0)


def fast():
    counts["fast"] += 1


pj._SUB_TASKS[:] = [(slow, 0, "npc_wanderers"), (fast, 0, "status_tick")]
pj._get_tick_interval = lambda: 0
pj._is_paused = lambda: False
_real_sleep = asyncio.sleep


async def quick_sleep(seconds, *a, **kw):
    # The 30 s start-up delay and the per-sweep interval: 20 ms each.
    await _real_sleep(0.02)


async def scenario():
    pj.asyncio.sleep = quick_sleep
    try:
        task = asyncio.create_task(pj._world_admin_tick_loop())
        await _real_sleep(0.5)
        during = dict(counts)
        release.set()
        await _real_sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        for t in list(pj._detached_tasks.values()):
            t.cancel()
        return during
    finally:
        pj.asyncio.sleep = _real_sleep


during = asyncio.run(scenario())
check("the slow one started once in 0.5 s", during["slow"], 1)
check("the fast one ran on (>= 5 sweeps)", during["fast"] >= 5, True)
check("the slow one's success was stamped", "npc_wanderers" in pj._last_run,
      True)

print()
if FAILURES:
    print(f"FAILED — {len(FAILURES)} of {CHECKED} checks:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
