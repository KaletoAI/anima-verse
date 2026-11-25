"""Smoke: request_timing writes its slow-request log from a writer thread.

``_record`` runs on the event loop; it must only enqueue. One daemon writer
thread drains a bounded queue into LOG_FILE; a full queue drops the OLDEST row;
``flush()`` writes everything queued and ends the writer.

No storage, no world DB, no server: LOG_FILE points into a temp directory and
the module's ``open`` is replaced by a recorder (the writer calls the
module-global ``open``, so a name in the module's globals shadows the builtin).

Checks, expected numbers derived by hand:
  A  order: 20 slow records (ms=300 > 250) for routes /r0../r19, then flush
     -> the file holds exactly 20 lines, routes /r0../r19 in that order.
     route_stats() still counts every record: 20 routes with n=1 each, plus
     one fast record (ms=10) on /fast -> 21 rows, /fast never in the file.
  B  thread: every recorded open() ran on a thread other than the caller's
     (the main thread), and after A at least one open happened.
  C  overflow: queue maxlen 5. The writer is held inside open() while it
     writes the first row /o0. Then /o1../o8 are recorded (8 rows) into the
     5-slot queue: rows /o1,/o2,/o3 are the oldest and get dropped (8-5 = 3),
     /o4../o8 stay. After release + flush the file part for C reads
     /o0,/o4,/o5,/o6,/o7,/o8 (6 lines) and _dropped grew by exactly 3.
  D  flush twice: a second flush() returns at once, the writer is gone,
     the file is unchanged (26 lines = 20 + 6).
  E  restart: a record after flush starts a new writer; after flush the file
     has 27 lines, the last one /after.

Usage:
    ./.venv/bin/python scripts/smoke_request_timing_writer.py
Exit 0 = all checks passed.
"""
import builtins
import json
import shutil
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import request_timing as rt  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="rt_writer_"))
rt.LOG_FILE = tmp / "logs" / "request_timing.jsonl"
main_tid = threading.get_ident()
open_tids = []
gate = threading.Event()
gate.set()
entered = threading.Event()


def recording_open(path, *a, **kw):
    open_tids.append(threading.get_ident())
    entered.set()
    gate.wait(10)
    return builtins.open(path, *a, **kw)


rt.open = recording_open


def routes():
    if not rt.LOG_FILE.exists():
        return []
    return [json.loads(l)["route"] for l in rt.LOG_FILE.read_text().splitlines()]


# A
for i in range(20):
    rt._record(f"/r{i}", "GET", 200, 300.0, 10, "ok")
rt._record("/fast", "GET", 200, 10.0, 10, "ok")
rt.flush()
check(routes() == [f"/r{i}" for i in range(20)], "A: 20 lines in order /r0../r19")
stats = rt.route_stats()
check(len(stats) == 21 and all(r["n"] == 1 for r in stats), "A: route_stats 21 rows, n=1 each")
check("/fast" not in routes(), "A: fast request not logged")

# B
check(len(open_tids) >= 1 and main_tid not in open_tids, "B: every open() ran off the calling thread")

# C
rt._pending = deque(maxlen=5)
dropped_before = rt._dropped
gate.clear()
entered.clear()
rt._record("/o0", "GET", 200, 300.0, 1, "ok")
check(entered.wait(5), "C: writer entered open() for /o0")
for i in range(1, 9):
    rt._record(f"/o{i}", "GET", 200, 300.0, 1, "ok")
check([r["route"] for r in rt._pending] == ["/o4", "/o5", "/o6", "/o7", "/o8"],
      "C: queue keeps the newest 5")
gate.set()
rt.flush()
check(routes()[20:] == ["/o0", "/o4", "/o5", "/o6", "/o7", "/o8"], "C: file has /o0,/o4../o8")
check(rt._dropped - dropped_before == 3, "C: exactly 3 rows dropped")

# D
rt.flush()
rt.flush()
check(rt._writer is None or not rt._writer.is_alive(), "D: writer ended")
check(len(routes()) == 26, "D: file unchanged at 26 lines")

# E
rt._record("/after", "GET", 200, 300.0, 1, "ok")
rt.flush()
r = routes()
check(len(r) == 27 and r[-1] == "/after", "E: record after flush written (27 lines)")
check(main_tid not in open_tids, "E: still no open() on the calling thread")

shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print(f"FAILED ({len(fails)})")
    sys.exit(1)
print("OK: request_timing writer")
