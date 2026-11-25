#!/usr/bin/env python3
"""Event-loop watchdog: the block start is the heartbeat the lag was measured
from, even when the loop beats between two reads.

Usage: ./.venv/bin/python scripts/smoke_watchdog_heartbeat_once.py
No server, no world DB, no real sleeping block: the watchdog thread function
runs against a scripted clock.

Script, by hand (threshold 1000 ms):
  heartbeat = 100.0 s before the first check.
  check 1: monotonic() returns 102.0 -> lag 102.0 - 100.0 = 2.0 s >= 1 s.
    Right after the lag is measured (inside loop_guard.report_if_due, which
    the check calls before it dumps) the loop comes back and beats:
    heartbeat -> 101.9, recorded gap (100.0, 101.9). Dump "blocked for
    2000ms"; the block started at the beat the lag was read from: 100.0.
  check 2: monotonic() returns 102.0 -> lag 0.1 s -> "free again"; the
    recorded gap starts at the block start 100.0, so the end is its 101.9
    -> reported block 101.9 - 100.0 = 1900 ms.
  A second read of the heartbeat for the block start would take 101.9, the
  gap would not match it and the end would fall back to the latest beat
  101.9 -> "0ms".
"""
import logging
import re
import sys
import threading
import time as _real_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import event_loop_watchdog as wd, loop_guard  # noqa: E402

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


records = []


class _H(logging.Handler):
    def emit(self, rec):
        records.append(rec.getMessage())


logging.getLogger(wd.logger.name).addHandler(_H())
reports = {"n": 0}


def _report():
    reports["n"] += 1
    if reports["n"] == 1:
        # the loop beats between the lag measurement and the dump
        wd._heartbeat = 101.9
        wd._last_gap = (100.0, 101.9)


loop_guard.report_if_due = _report
loop_guard.server_loop_tid = lambda: None

calls = {"n": 0}


class _Clock:
    @staticmethod
    def sleep(_s):
        _real_time.sleep(0.001)

    @staticmethod
    def monotonic():
        calls["n"] += 1
        if calls["n"] >= 2:
            wd._stop_event.set()
        return 102.0


wd._heartbeat = 100.0
wd._last_gap = (0.0, 0.0)
wd._stop_event.clear()
wd.time = _Clock
t = threading.Thread(target=wd._watchdog_thread, args=(1000.0, 0.0), daemon=True)
t.start()
t.join(5.0)
wd.time = _real_time

ok("watchdog thread ended", not t.is_alive())
ok("dump logged", any("Event loop blocked for 2000ms" in r for r in records),
   repr([r[:50] for r in records]))
free = [r for r in records if "free again after" in r]
m = re.search(r"free again after (\d+)ms", free[0]) if free else None
ms = int(m.group(1)) if m else -1
ok(f"block length 1900 ms ({ms})", ms == 1900, repr(free))

print("PASSED" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
