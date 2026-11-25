#!/usr/bin/env python3
"""Event-loop watchdog: the reported block length comes from the heartbeat,
and idle pool threads take one dump line each.

Usage: ./.venv/bin/python scripts/smoke_event_loop_watchdog.py
No server, no world DB.

Setup: watchdog started with tick 0.05 s, threshold 300 ms and a check
interval of 1.0 s. ``loop_guard.report_if_due`` (called once per check)
is wrapped to signal each check, and the loop thread starts a 1.2 s blocking
sleep right after a check at time c0. Then:
  - the next check at c0 + 1.0 s sees a lag of about 1.0 s >= 300 ms and
    dumps;
  - the block ends at c0 + 1.2 s; the first heartbeat after it lands there;
  - the check at c0 + 2.0 s finds the loop free again.
Expected, by hand: the heartbeat before the block is at most one tick
(0.05 s) older than c0, the first one after it is the block's end, so the
reported length lies in [1.2 s, 1.5 s] (1.2 + 0.05 + scheduling slack).
The old measurement took "now" at the c0 + 2.0 s check: about 2.0 s.

Dump format, by hand:
  - a ThreadPoolExecutor worker waiting for work (innermost frame
    concurrent/futures/thread.py _worker, no app frame) -> exactly 1 line;
  - a thread blocked in queue.Queue.get (innermost frame threading.py
    wait, no app frame) -> exactly 1 line;
  - the watchdog thread itself (app/core/event_loop_watchdog.py frames) ->
    its full stack, more than 1 line, naming event_loop_watchdog.py.
  - the log lines are English: "Event loop blocked for", "free again after".
"""
import asyncio
import logging
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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

checked = threading.Event()
_real_report = loop_guard.report_if_due


def _signal_check():
    checked.set()
    return _real_report()


loop_guard.report_if_due = _signal_check

pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smokepool")
pool.submit(lambda: None).result()
q = queue.Queue()
waiter = threading.Thread(target=q.get, name="smokequeue", daemon=True)
waiter.start()


async def main():
    wd.start(tick=0.05, threshold_ms=300.0, check_interval=1.0)
    await asyncio.sleep(0.3)
    checked.clear()
    while not checked.is_set():
        await asyncio.sleep(0.002)
    time.sleep(1.2)            # the artificial block, on the loop thread
    await asyncio.sleep(1.6)   # past the next check after the block
    wd.stop()
    await asyncio.sleep(0.05)


asyncio.run(main())
q.put(None)
pool.shutdown()

dump = next((r for r in records if "Event loop blocked for" in r), "")
free = [r for r in records if "free again after" in r]
ok("English dump line logged", bool(dump), repr([r[:60] for r in records]))
m = re.search(r"free again after (\d+)ms", free[0]) if free else None
ms = int(m.group(1)) if m else -1
ok(f"reported block length in [1200, 1500] ms ({ms})", 1200 <= ms <= 1500, repr(free))


def section(name):
    lines = dump.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("--- Thread ") and name in line:
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith("--- Thread "):
                    break
                if nxt.strip():
                    out.append(nxt)
            return out
    return []


p = section("smokepool")
ok("idle pool worker -> 1 line", len(p) == 1, repr(p))
s = section("smokequeue")
ok("queue waiter -> 1 line", len(s) == 1, repr(s))
w = section("EventLoopWatchdog")
ok("watchdog thread -> full stack",
   len(w) > 1 and any("event_loop_watchdog.py" in ln for ln in w), repr(w[:3]))

print("PASSED" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
