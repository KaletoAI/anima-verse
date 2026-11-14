#!/usr/bin/env python3
"""The refit pool's workers never outlive the server (Ruling A64; app/core/refit_pool.py, start.sh).

Usage:
    ./.venv/bin/python scripts/smoke_refit_pool_lifetime.py

No storage, no world, no instance, no server, no hub: the refit pool needs none of them (a worker never opens a
database and has no storage root). Every process this smoke starts is its own, and it ends each one it started,
whatever the outcome.

The incident behind it: 16 ``multiprocessing.spawn`` workers (and 7 resource trackers) of seven earlier server
runs were still alive with parent pid 1, about 8.5 GB RSS — a killed server never ran its lifespan exit, and a
spawned worker holds the write end of its own call queue, so it waits on it forever.

Expected, derived by hand:

[1] Parent killed: a child process ("the server") builds the pool through the server's own factory
    (``refit_pool._get_pool(2)``), submits two calls of ``time.sleep(60)`` so both workers exist and are busy,
    names its own children (the two workers + the resource tracker, read from /proc), then kills itself with
    SIGKILL — no lifespan exit, no atexit. ``_watch_parent`` polls every PARENT_POLL_S = 1 s, so every worker
    is gone within 1 s + start-up slack; allowed: N = 6 s. The resource tracker ends once no process holds its
    pipe any more, i.e. with the workers: also gone within N.
[2] The same on the pinned old code (``git show e57fa28b6:app/core/refit_pool.py``, no parent watch): the
    workers are STILL alive 3 s after the parent died (the incident) — then this smoke ends them itself.
    Skipped when that commit is not in the repository.
[3] Lifespan exit: ``refit_pool.shutdown()`` (the call app/server.py makes) on a pool whose one worker is in a
    ``time.sleep(60)`` call returns within TERMINATE_GRACE_S + 1 s = 4 s and the worker is gone (SIGTERM ends
    it); before Ruling A64 ``shutdown`` left it running until the call ended (60 s).
[4] start.sh: ``process_tree`` / ``stop_tree`` (extracted from start.sh by their definitions) on a stand-in
    service that leads its own process group (setsid) and has a child and a grandchild, the stand-in ignoring
    nothing: every process of the tree is gone afterwards; start_main launches uvicorn through setsid, and
    stop_service / kill_port stop through stop_tree.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLD_COMMIT = "e57fa28b6cdfa819eef0e2c7643d4924620062da"
WITHIN_S = 6.0

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def alive(pid: int) -> bool:
    """Alive and not a zombie (a reaped-later zombie of ours counts as gone)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def end(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


CHILD = textwrap.dedent("""
    import json, os, signal, sys, time


    def main():
        sys.path.insert(0, sys.argv[1])
        if sys.argv[2]:
            import refit_pool_old as refit_pool   # on PYTHONPATH, so a spawned worker imports it too
        else:
            from app.core import refit_pool
        pool = refit_pool._get_pool(2)
        futures = [pool.submit(time.sleep, 60) for _ in range(2)]
        deadline = time.time() + 30
        while time.time() < deadline and len(pool._processes) < 2:
            time.sleep(0.1)
        time.sleep(1.5)   # the workers have run their initializer and picked their call
        me = str(os.getpid())
        kids = []
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    stat = open(f"/proc/{entry}/stat").read().rsplit(")", 1)[1].split()
                except OSError:
                    continue
                if stat[1] == me:
                    kids.append(int(entry))
        print(json.dumps({"workers": sorted(pool._processes), "children": sorted(kids)}), flush=True)
        os.kill(os.getpid(), signal.SIGKILL)


    if __name__ == "__main__":   # a spawned worker imports this file as __mp_main__
        main()
""")


def run_child(old_source: str = ""):
    """The stand-in server: returns (workers, children) it named before it killed itself."""
    with tempfile.TemporaryDirectory(prefix="a64-pool-") as tmp:
        script = Path(tmp) / "server_standin.py"
        script.write_text(CHILD)
        env = dict(os.environ)
        if old_source:
            (Path(tmp) / "refit_pool_old.py").write_text(old_source)
            env["PYTHONPATH"] = os.pathsep.join([tmp, str(ROOT)])
        # Files, not pipes: a worker that outlives its parent holds the pipe open and blocks the read.
        out, err = Path(tmp) / "out.txt", Path(tmp) / "err.txt"
        with out.open("w") as fo, err.open("w") as fe:
            subprocess.run([sys.executable, str(script), str(ROOT), "old" if old_source else ""],
                           stdout=fo, stderr=fe, timeout=90, cwd=tmp, env=env)
        stdout, stderr = out.read_text(), err.read_text()
    line = next((ln for ln in stdout.splitlines() if ln.startswith("{")), "")
    if not line:
        print(stderr[-2000:])
        return [], []
    data = json.loads(line)
    return data["workers"], data["children"]


def wait_gone(pids, within):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not any(alive(p) for p in pids):
            return True, time.monotonic() - (deadline - within)
        time.sleep(0.2)
    return False, within


def case_parent_killed():
    workers, children = run_child()
    check(len(workers) == 2, f"[1] the stand-in server built 2 workers through _get_pool (got {workers})")
    check(set(workers) <= set(children) and len(children) >= 3,
          f"[1] its children: the workers + the resource tracker (got {children})")
    gone, took = wait_gone(children, WITHIN_S)
    left = [p for p in children if alive(p)]
    check(gone, f"[1] parent killed with SIGKILL → every child gone within {WITHIN_S:.0f} s "
                f"(took {took:.1f} s, left {left})")
    end(left)


def case_old_code():
    try:
        source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/refit_pool.py"],
                                capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        print(f"skip [2] commit {OLD_COMMIT[:9]} not available")
        return
    workers, children = run_child(source)
    try:
        check(len(workers) == 2, f"[2] old code: 2 workers built (got {workers})")
        time.sleep(3.0)
        still = [p for p in workers if alive(p)]
        check(still == workers, f"[2] old code {OLD_COMMIT[:9]}: the workers are still alive 3 s after the parent "
                                f"died (the incident) — alive {still}")
    finally:
        end(children)


def case_shutdown():
    from concurrent.futures import wait as fwait
    from app.core import refit_pool
    refit_pool.enable()
    pool = refit_pool._get_pool(1)
    future = pool.submit(time.sleep, 60)
    deadline = time.time() + 30
    while time.time() < deadline and not pool._processes:
        time.sleep(0.1)
    time.sleep(1.5)
    pids = sorted(pool._processes)
    check(len(pids) == 1 and alive(pids[0]), f"[3] one worker computing (got {pids})")
    started = time.monotonic()
    refit_pool.shutdown()
    took = time.monotonic() - started
    check(took <= refit_pool.TERMINATE_GRACE_S + 1.0, f"[3] shutdown() returns within 4 s (took {took:.1f} s)")
    gone, _ = wait_gone(pids, 1.0)
    check(gone, f"[3] the computing worker is gone after shutdown() (left {[p for p in pids if alive(p)]})")
    fwait([future], timeout=5)
    check(refit_pool._pool is None and refit_pool.workers() == 1, "[3] the pool is dropped and disabled")
    end(pids)


def case_start_sh():
    text = (ROOT / "start.sh").read_text()
    check("launcher=(setsid)" in text and '"${launcher[@]}" "$SCRIPT_DIR/.venv/bin/python" -m uvicorn' in text,
          "[4] start_main launches uvicorn through setsid (its own process group)")
    stop_service = text.split("stop_service() {", 1)[1].split("\n}\n", 1)[0]
    kill_port = text.split("kill_port() {", 1)[1].split("\n}\n", 1)[0]
    check('stop_tree "$pid" "$name"' in stop_service and 'kill "$pid"' not in stop_service,
          "[4] stop_service (--stop / --restart) stops through stop_tree")
    check('stop_tree "$pid" "$name"' in kill_port and 'kill "$pid"' not in kill_port,
          "[4] kill_port (a fresh start) stops through stop_tree")
    test = textwrap.dedent("""
        set -euo pipefail
        eval "$(sed -n '/^wait_for_death() {/,/^}/p;/^process_tree() {/,/^}/p;/^stop_tree() {/,/^}/p' "$1")"
        setsid bash -c 'sleep 300 & (sleep 300 & wait) & trap "exit 0" TERM; while :; do sleep 1; done' &
        pid=$!
        sleep 0.7
        tree=$(process_tree "$pid" | tr '\\n' ' ')
        echo "TREE $tree"
        stop_tree "$pid" standin >/dev/null
        sleep 0.3
        echo "DONE"
    """)
    with tempfile.TemporaryDirectory(prefix="a64-sh-") as tmp:
        script = Path(tmp) / "t.sh"
        script.write_text(test)
        out = subprocess.run(["bash", str(script), str(ROOT / "start.sh")], capture_output=True, text=True,
                             timeout=60).stdout
    tree = [int(p) for p in next((ln for ln in out.splitlines() if ln.startswith("TREE")), "TREE").split()[1:]]
    check(len(tree) >= 4, f"[4] process_tree names the stand-in, its child, its grandchild and their sleeps (got {tree})")
    left = [p for p in tree if alive(p)]
    check("DONE" in out and not left, f"[4] stop_tree leaves none of them alive (left {left})")
    end(left)


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("skip: /proc is Linux only")
        return 0
    case_parent_killed()
    case_old_code()
    case_shutdown()
    case_start_sh()
    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
