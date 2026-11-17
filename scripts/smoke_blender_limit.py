#!/usr/bin/env python3
"""The cross-process limit on concurrent Blender runs (``server.blender_max_concurrent``,
``app/blender/runner.py`` → ``blender_slot``).

Usage:
    ./.venv/bin/python scripts/smoke_blender_limit.py

No Blender, no server, no world, no instance: every run happens in CHILD PROCESSES of this script
(``--child <json>``), each of which calls the REAL ``runner.run("meshopt", …)`` with ``runner.status`` stubbed
to "usable" and ``runner.subprocess`` replaced by a stand-in whose ``run`` sleeps ``hold`` seconds, notes
``start``/``end`` (time.time) in a shared log and writes the ``{"ok": true}`` result file Blender would write.
The slot folder and limit are pinned per child (``runner.pin_slots``: the refit-worker path) into a throwaway
temp folder — except in [4], where the limit is read from a file through ``runner._config`` on every try.

Expected, derived by hand (``SLOT_POLL_S`` = 0.25 s; a holder notes ``end`` before its slot is released, so a
waiter's ``start`` is strictly later than the ``end`` that freed it):

[1] limit 2, 5 processes × hold 1.0 s → at most 2 runs overlap at any instant, and exactly 2 do (the limit is
    not a serialisation); ceil(5 / 2) = 3 waves → first start to last end ≥ 3 × 1.0 = 3.0 s. Unlimited (the old
    runner) all 5 would overlap.
[2] limit 1, 3 processes × hold 0.5 s → never 2 at once; ≥ 3 × 0.5 = 1.5 s first start to last end.
[3] Killed holder: K holds the only slot (limit 1, hold 60 s); W (limit 1, hold 0.2 s) starts after K's
    ``start`` and has not started 1.0 s later (it waits). SIGKILL K → the kernel drops K's flock; W starts within
    SLOT_POLL_S + start-up slack (≤ 2.0 s after the kill) and ends ok.
[4] Live limit + wait label: the limit file says 1; H holds slot 0 (hold 4 s); W waits inside
    ``refit_pool.blender_wait_label("t1", "Refit · X")`` with a stand-in task queue. After 1.0 s W has not
    started; the limit file is set to 2 → W takes slot 1 within ≤ 1.5 s, while H still runs (W.start < H.end).
    W's tracked labels, in order: "Refit · X · waiting for Blender", "Refit · X".
[5] Spawn pinning: ``refit_pool._initializer((<dir>, 3))`` in a fresh process → ``runner.spawn_slots()`` =
    (<dir>, 3).
[6] Fails on the old code: [1] run against ``app/blender/runner.py`` of ebcd6c0b (written to the temp folder,
    same stand-in) → 5 runs overlap (> 2): the old runner had no limit.
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_COMMIT = "ebcd6c0b"

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# --- child side ---------------------------------------------------------------------

def _note(log, tag, ev):
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tag": tag, "ev": ev, "t": time.time(), "pid": os.getpid()}) + "\n")


def child(spec):
    sys.path.insert(0, str(ROOT))
    if spec.get("old_runner"):
        mod_spec = importlib.util.spec_from_file_location("old_runner", spec["old_runner"])
        runner = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(runner)
        runner.SCRIPTS_DIR = ROOT / "app" / "blender" / "scripts"
    else:
        from app.blender import runner
        if spec.get("limit_file"):
            limit_file = spec["limit_file"]
            runner._config = lambda path, default: (int(Path(limit_file).read_text())
                                                    if path == "server.blender_max_concurrent" else default)
            runner.pin_slots(spec["slots"], None)
        else:
            runner.pin_slots(spec["slots"], spec["limit"])
    runner.status = lambda: {"enabled": True, "executable": "/stub/blender", "version": "5.2",
                             "usable": True, "error": "", "rejected": [], "configured": False}
    log, tag, hold = spec["log"], spec["tag"], float(spec["hold"])

    def fake_run(cmd, **_kw):
        _note(log, tag, "start")
        time.sleep(hold)
        _note(log, tag, "end")
        args = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
        Path(args["result"]).write_text('{"ok": true}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    runner.subprocess = types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired,
                                              SubprocessError=subprocess.SubprocessError,
                                              CompletedProcess=subprocess.CompletedProcess)
    model = Path(spec["model"])

    def go():
        res = runner.run("meshopt", inputs={"model": model}, timeout_s=120)
        _note(log, tag, "ok" if res["ok"] else "fail:" + res["error"])

    if spec.get("label"):
        labels = []
        fake_tq = types.ModuleType("app.core.task_queue")
        fake_tq.get_task_queue = lambda: types.SimpleNamespace(
            track_update_label=lambda tid, label: labels.append([tid, label]))
        sys.modules["app.core.task_queue"] = fake_tq
        from app.core import refit_pool
        with refit_pool.blender_wait_label("t1", "Refit · X"):
            go()
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": tag, "ev": "labels", "labels": labels}) + "\n")
    else:
        go()


def child_pin(spec):
    sys.path.insert(0, str(ROOT))
    from app.core import refit_pool
    from app.blender import runner
    refit_pool._initializer((spec["slots"], 3))
    print(json.dumps(list(runner.spawn_slots())))


# --- parent side --------------------------------------------------------------------

def spawn(spec, mode="--child"):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), mode, json.dumps(spec)],
                            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def read_log(log):
    if not Path(log).is_file():
        return []
    return [json.loads(line) for line in Path(log).read_text(encoding="utf-8").splitlines() if line.strip()]


def intervals(rows):
    starts = {r["tag"]: r["t"] for r in rows if r["ev"] == "start"}
    ends = {r["tag"]: r["t"] for r in rows if r["ev"] == "end"}
    return {tag: (starts[tag], ends.get(tag)) for tag in starts}


def max_overlap(iv):
    events = []
    for s, e in iv.values():
        events.append((s, 1))
        events.append((e, -1))
    events.sort(key=lambda x: (x[0], x[1]))  # an end at the same instant counts first
    cur = best = 0
    for _t, d in events:
        cur += d
        best = max(best, cur)
    return best


def wait_all(procs, timeout=60):
    for p in procs:
        out, err = p.communicate(timeout=timeout)
        if p.returncode != 0:
            print(err[-2000:])


def wait_for(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def batch(tmp, name, n, limit, hold, old_runner=None):
    slots = tmp / f"slots-{name}"
    log = tmp / f"{name}.log"
    procs = [spawn({"slots": str(slots), "limit": limit, "log": str(log), "tag": f"{name}{i}", "hold": hold,
                    "model": str(tmp / "model.glb"), "old_runner": old_runner}) for i in range(n)]
    wait_all(procs)
    rows = read_log(log)
    return intervals(rows), sum(1 for r in rows if r["ev"] == "ok")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke-blender-limit-"))
    (tmp / "model.glb").write_bytes(b"glTF-stub")
    try:
        # [1]
        iv, ok = batch(tmp, "a", 5, 2, 1.0)
        span = max(e for _s, e in iv.values()) - min(s for s, _e in iv.values())
        check(len(iv) == 5 and ok == 5, f"[1] 5 runs done ok (got {len(iv)} started, {ok} ok)")
        check(max_overlap(iv) == 2, f"[1] limit 2: max overlap 2 (got {max_overlap(iv)})")
        check(span >= 3.0, f"[1] 3 waves: span >= 3.0 s (got {span:.2f})")

        # [2]
        iv, ok = batch(tmp, "b", 3, 1, 0.5)
        span = max(e for _s, e in iv.values()) - min(s for s, _e in iv.values())
        check(ok == 3 and max_overlap(iv) == 1, f"[2] limit 1 serialises (overlap {max_overlap(iv)}, {ok} ok)")
        check(span >= 1.5, f"[2] span >= 1.5 s (got {span:.2f})")

        # [3]
        slots, log = tmp / "slots-c", tmp / "c.log"
        k = spawn({"slots": str(slots), "limit": 1, "log": str(log), "tag": "K", "hold": 60,
                   "model": str(tmp / "model.glb")})
        check(wait_for(lambda: "K" in intervals(read_log(log)), 10), "[3] K holds the slot")
        w = spawn({"slots": str(slots), "limit": 1, "log": str(log), "tag": "W", "hold": 0.2,
                   "model": str(tmp / "model.glb")})
        time.sleep(1.0)
        check("W" not in intervals(read_log(log)), "[3] W waits while K holds the only slot")
        killed = time.time()
        os.kill(k.pid, signal.SIGKILL)
        k.wait(timeout=10)
        check(wait_for(lambda: "W" in intervals(read_log(log)), 2.0), "[3] W starts <= 2.0 s after K was killed")
        wait_all([w])
        rows = read_log(log)
        w_start = intervals(rows).get("W", (None,))[0]
        check(w_start is not None and w_start > killed, "[3] W started after the kill, not before")
        check(any(r["tag"] == "W" and r["ev"] == "ok" for r in rows), "[3] W ends ok")

        # [4]
        slots, log, limit_file = tmp / "slots-d", tmp / "d.log", tmp / "limit"
        limit_file.write_text("1")
        h = spawn({"slots": str(slots), "limit_file": str(limit_file), "log": str(log), "tag": "H", "hold": 4,
                   "model": str(tmp / "model.glb")})
        check(wait_for(lambda: "H" in intervals(read_log(log)), 10), "[4] H holds slot 0")
        w = spawn({"slots": str(slots), "limit_file": str(limit_file), "log": str(log), "tag": "W", "hold": 0.2,
                   "model": str(tmp / "model.glb"), "label": True})
        time.sleep(1.0)
        check("W" not in intervals(read_log(log)), "[4] W waits at limit 1")
        limit_file.write_text("2")
        check(wait_for(lambda: "W" in intervals(read_log(log)), 1.5), "[4] W starts <= 1.5 s after limit -> 2")
        wait_all([h, w])
        rows = read_log(log)
        iv = intervals(rows)
        check(iv["W"][0] < iv["H"][1], "[4] W ran while H still held slot 0")
        labels = next((r["labels"] for r in rows if r["ev"] == "labels"), None)
        check(labels == [["t1", "Refit · X · waiting for Blender"], ["t1", "Refit · X"]],
              f"[4] wait label set and restored (got {labels})")

        # [5]
        p = spawn({"slots": str(tmp / "pinned")}, mode="--child-pin")
        out, err = p.communicate(timeout=60)
        got = json.loads(out.strip().splitlines()[-1]) if p.returncode == 0 and out.strip() else err[-500:]
        check(got == [str(tmp / "pinned"), 3], f"[5] worker pinned to (dir, 3) (got {got})")

        # [6]
        old = tmp / "old_runner.py"
        src = subprocess.run(["git", "show", f"{OLD_COMMIT}:app/blender/runner.py"], cwd=str(ROOT),
                             capture_output=True, text=True)
        if src.returncode != 0:
            check(False, f"[6] {OLD_COMMIT}:app/blender/runner.py readable")
        else:
            old.write_text(src.stdout, encoding="utf-8")
            iv, ok = batch(tmp, "old", 5, 2, 1.0, old_runner=str(old))
            check(ok == 5 and max_overlap(iv) == 5,
                  f"[6] old runner ({OLD_COMMIT}): all 5 overlap (got {max_overlap(iv)}, {ok} ok)")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child(json.loads(sys.argv[2]))
    elif len(sys.argv) > 2 and sys.argv[1] == "--child-pin":
        child_pin(json.loads(sys.argv[2]))
    else:
        sys.exit(main())
