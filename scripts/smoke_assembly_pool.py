#!/usr/bin/env python3
"""Garment assembly builds run on a bounded worker pool (app/core/garment_assembly.py ``schedule`` ->
``_submit`` / ``_worker``, ``MAX_WORKERS``), queued and never dropped (review finding 06B#4).

Usage:
    ./.venv/bin/python scripts/smoke_assembly_pool.py

No world, no server, no Blender: a throwaway storage + instance root (``paths.init`` first), and ``assemble`` /
``_input_key`` / ``_wanted_for`` / ``_model3d`` replaced by stubs. The ``assemble`` stub blocks on an event and
counts how many run at once.

EXPECTED, hand-derived from the rule (MAX_WORKERS = 2, one build per key, a request while queued/running only
marks it again):
[P1] 6 characters scheduled at once -> ``schedule`` returns True 6 times; while the gate is closed exactly 2
     builds run (peak concurrency 2), the other 4 wait in the queue — c5 is in ``_building`` (in flight, not
     dropped) and in ``_queued``.
     FAILS on the old code (commit 8fa2d763f, one thread per request): peak concurrency 6.
[P2] gate opened -> ``wait_idle`` True, every one of the 6 characters built exactly once (6 calls).
[P3] no more than 2 live threads named ``garment-assembly-*`` at any time.
[P4] a key scheduled twice while still queued -> ``schedule`` returns False the second time and it builds ONCE:
     ``_run`` clears the ``_again`` mark before it reads its inputs, so a request that came before the build
     started is served by that build (1 call for that key, none lost).
[P5] gate closed, 4 keys scheduled (2 run, q2 and q3 queued); ``wait_for("q3", timeout=0.3)`` while the gate opens
     only after 1.0 s -> True: the 0.3 s count only from when a worker takes q3 (its build is instant once open).
[P6] the worker thread names ever seen are unique (no two live workers share a name).
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_assembly_pool_")).resolve()
os.environ["STORAGE_DIR"] = str(TMP / "storage")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
from app.core import paths  # noqa: E402
paths.init(str(TMP / "storage"))
paths.init_instance(str(TMP / "instance"))

from app.core import garment_assembly as ga  # noqa: E402

fails = []


def check(tag, ok, msg=""):
    print(f"[{tag}] {'PASS' if ok else 'FAIL'} {msg}")
    if not ok:
        fails.append(tag)


class _M3:
    class _staging:  # noqa: N801
        directories = {}

    @staticmethod
    def get_model3d_dir(name):
        return TMP / name


gate = threading.Event()
lk = threading.Lock()
running = 0
peak = 0
calls = []
max_threads = 0


def fake_assemble(name, sig):
    global running, peak, max_threads
    with lk:
        running += 1
        peak = max(peak, running)
        calls.append(name)
        n = sum(1 for t in threading.enumerate() if t.name.startswith("garment-assembly"))
        max_threads = max(max_threads, n)
    gate.wait(10)
    with lk:
        running -= 1
    return {"ok": True}


ga._model3d = lambda: _M3
ga._wanted_for = lambda *a, **k: [{"x": 1}]
ga._input_key = lambda *a, **k: "k"
ga.assemble = fake_assemble

names = [f"c{i}" for i in range(6)]
res = [ga.schedule(n, "sig") for n in names]
time.sleep(0.5)
with lk:
    p_running = running
with ga._lock:
    queued_done = not (("c5", "sig") in ga._building and ("c5", "sig") in ga._queued)
check("P1", res == [True] * 6 and peak == 2 and p_running == 2 and not queued_done,
      f"returns {res} peak {peak} running {p_running} c5 done {queued_done}")
gate.set()
idle = ga.wait_idle(10)
check("P2", idle and sorted(calls) == sorted(names), f"idle {idle} calls {sorted(calls)}")
check("P3", max_threads <= 2, f"max live assembly threads {max_threads}")

gate.clear()
calls.clear()
peak = 0
a = [ga.schedule(n, "sig") for n in ("b0", "b1", "dup")]
b = ga.schedule("dup", "sig")
gate.set()
ga.wait_idle(10)
check("P4", a == [True] * 3 and b is False and calls.count("dup") == 1, f"{a} {b} {calls}")

gate.clear()
calls.clear()
for n in ("q0", "q1", "q2", "q3"):
    ga.schedule(n, "sig")
threading.Timer(1.0, gate.set).start()
t0 = time.monotonic()
ok5 = ga.wait_for("q3", "sig", timeout=0.3)
check("P5", ok5 and time.monotonic() - t0 >= 0.9, f"done {ok5} after {time.monotonic() - t0:.2f}s")
ga.wait_idle(10)
names = [w.name for w in ga._workers]
check("P6", len(names) == len(set(names)) and len(names) <= 2, str(names))

print("FAIL" if fails else "ALL PASS", fails)
sys.exit(1 if fails else 0)
