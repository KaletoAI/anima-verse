#!/usr/bin/env python3
"""A refit the refit pool ENDS is no refusal, a server stop ends refit work promptly, a cancelled tracked refit
stays cancelled (review 2026-11-18 unit 01, findings #1-#6; app/core/refit_pool.py, garment_refit.py,
garments.py, fit_attempts.py, improvements/types/fit_refit.py).

Usage:
    ./.venv/bin/python scripts/smoke_refit_interruption.py

Runs against THROWAWAY storage + instance directories (``paths.init`` before any world module) and stand-in
processes it starts and ends itself — no real world, no server, no hub, no GPU, no Blender. The worker-side
helpers below sit at module level (a spawned worker imports this file as ``__mp_main__``; everything with a side
effect is in ``main()``).

Expected, derived by hand:

[1] Stop during a parallel sweep (stand-in server, a subprocess): ``server.refit_workers`` = 2, the pool enabled.
    First a pool of 3 runs ``time.sleep(SLEEP)`` (SLEEP = 30 s) — then the sweep's own ``_get_pool(2)`` replaces
    it (a resize): its worker keeps computing. The real ``garment_refit._sweep_parallel`` runs six characters on
    2 orchestrator threads on a daemon thread (``start_sweep``'s shape); each character's ``refit_character`` is
    one ``refit_pool.run(time.sleep, SLEEP)``. 3 s later ``refit_pool.shutdown()`` (the lifespan exit), then the
    stand-in's main returns. Two characters are in flight, four wait. Expected: the two in-flight calls raise
    ``RefitInterrupted`` (none runs again — no "runs once more" warning, no worker process alive 1 s after
    the shutdown, the resized-away pool's worker included); every one of the six tracked rows ends with
    ``garment_refit.STOPPED`` (two from ``_attempt``, four never started); no ``refit_character`` returned. The
    process ends within TERMINATE_GRACE_S + 2 = 5 s of the stop. Before this fix the two calls re-ran in fresh
    worker processes (SLEEP s), the four waiting characters ran in-process after the stop (the thread pool's exit
    hook drains its queue: 2 × SLEEP) and the old pool's worker kept the process (its manager is joined at exit)
    — at least SLEEP = 30 s.
[2] The same stop on ONE call, ``refit_pool.run(time.sleep, 12)`` in a thread and ``shutdown()`` 3 s later:
    this tree → the call raises ``RefitInterrupted``, the stand-in ends within 5 s of the stop; the pinned code
    before the fix (``git show 3f2ce338e…:app/core/refit_pool.py``) → the call runs once more in a fresh worker
    (12 s), so the stand-in ends ≥ 8 s after the stop. Skipped when that commit is not in the repository.
[3] Pool semantics in this process (2 workers):
    a) five concurrent ``run(nap, 30)``, terminating ``shutdown()`` 2.5 s later → all five raise
       ``RefitInterrupted`` (two computing, three queued; before: two re-ran 30 s, three raised
       ``CancelledError('')`` — an ``Exception`` the callers recorded as the fit's refusal), within 5 s of the
       stop. Afterwards ``closing()`` True, ``run(len, [1, 2])`` raises ``RefitInterrupted`` (before: 2,
       computed in-process), ``_get_pool(2)`` raises it too; ``enable()`` → ``closing()`` False and
       ``run(os.getpid)`` answers a worker pid again (≠ this pid).
    b) ``_drop`` of a pool that is no longer the current one (a resize replaced it) cancels nothing: six
       ``nap(0.5)`` submitted to P1, ``_get_pool(3)`` replaces P1, ``_drop(P1)`` → all six results None, none
       cancelled (before: ``cancel_futures`` cancelled the queued ones).
    c) A crash re-runs one call at a time: ``crash_soon`` (``os._exit`` after 0.3 s) and, 0.2 s later, three
       ``timed(1.5)`` from four threads on 2 workers — the crash breaks the pool while all three timed calls are
       computing or queued, so all four run once more on their own: ``crash_soon`` → ``WorkerCrashed``, the
       three timed calls return ``(pid, t0, t1)`` with pid ≠ this pid and pairwise disjoint intervals
       (``_ALONE_LOCK``; before: four re-runs at once — the intervals overlap).
[4] No refusal for an interruption (#2), stubbed garment state, in-process:
    a) ``refit_character`` whose ``garments._fit`` raises ``RefitInterrupted`` → the exception propagates,
       ``garments._note_outcome`` is never called (no failure record, no stamp), the item's run status is
       not ``fit`` any more and holds no failure. Control (the path a ``CancelledError`` took before): the same
       with ``RuntimeError("boom")`` → ``_note_outcome`` once, ``ok`` False, error "boom", ``refusal_stamp``
       set.
    b) ``_retry_refused`` and ``_refit_bodies`` the same: ``RefitInterrupted`` propagates, neither
       ``_note_outcome`` nor ``garment_store.record_body_failure`` is called.
    c) ``garments._is_load``: ``RefitInterrupted`` → True, a ``ValueError`` raised ``from`` one → True,
       ``RuntimeError`` → False (``run_garment`` then persists nothing: ``_retry_later``). The body before the
       fix (``footwear_source.failure_of(e)[0] == LOAD``, run inline here) → False for ``RefitInterrupted``.
    d) ``fit_attempts.store`` re-raises ``RefitInterrupted`` from ``_store``; a ``ValueError`` there still
       returns False ("never raises" for every other failure).
[5] A cancelled tracked refit (#3), real task queue:
    a) ``refit_pool.finish`` on a row cancelled in the TaskPanel → it stays ``cancelled`` (before:
       ``track_finish`` overwrote it with ``completed``).
    b) The FIFO: item A runs (held on an event), a fit-only click of B waits (pending row); B's row cancelled;
       A released → ``run_garment`` is never called for B, B's job result is ``{ok False, cancelled True}``, B's
       row stays ``cancelled`` (before: B ran and its row ended ``completed``).
    c) The parallel sweep's retry attempt (``first`` False) of a character whose row was cancelled while it
       waited → ``("done", [])``, ``refit_character`` not called, the row stays cancelled (before: only the
       first attempt looked).
[6] An explicit click takes over a waiting automatic run (#4): A runs (held), ``enqueue_garment(C,
    automatic=True)`` waits; ``cached_failure`` reports a refusal for C; ``start_garment(C, steps="mesh")`` → the
    waiting job is that same job, now ``automatic`` False, and once A is released ``run_garment`` runs C with
    steps "mesh" (before: ``automatic`` stayed True and the cached refusal skipped the run).
[7] The tracked row is ``running`` only while work is done (#6):
    a) ``_attempt`` with no posture work and ``refit_character`` finding the chain busy (None, ``on_hold``
       never called) → ``(BUSY, [])``, the row stays ``pending`` (before: ``running`` while it waited).
    b) With posture work done and then busy → ``(BUSY, ["posture@b1"])``; that row ends ``completed`` (its
       posture work), ``tracks[name]`` names a NEW row, ``pending``.
    c) The next attempt holds the lock (``on_hold`` called) and refits ``["x"]`` → ``("done", ["x"])``, the
       new row ``completed``.
    d) The ``fit_refit`` improvement: postures matched, then busy → ``CandidateBusy``, and its row is
       ``completed`` (before: discarded — no trace of the posture work); ``refit_character`` raising
       ``RefitInterrupted`` → ``CandidateBusy`` (deferred, not a failed attempt).
[8] The footwear chain (``garment_footwear.run_chain`` → ``_failure``, matched by the exception's type NAME): a
    failure of type ``RefitInterrupted`` → ``retry_later`` True, so ``garments._note_outcome`` persists nothing;
    control: ``RuntimeError`` → no ``retry_later``. Before: ``RETRY_LATER_ERRORS`` held only
    ``BackendBusyError`` / ``MediaGenerationDisabled`` → the interruption was persisted as the fit's refusal.
[9] ``body_fit`` with ``build`` (the assembly, a Build's re-fit, the per-body Re-fit), the body state stubbed as
    "missing", no failure, the body bytes current: a) ``garments.body_fit`` whose ``fit_on_body`` raises
    ``RefitInterrupted`` → it propagates, ``record_body_failure`` is not called; control ``RuntimeError`` →
    recorded once. b) ``garment_footwear.body_fit`` whose ``fit`` raises it → the same; control → recorded once.
    Before: both caught every exception and recorded it as the body's refusal.
[10] ``app.routes.queue.cancel_task`` (DELETE /queue/tasks/{id}, the TaskPanel's Cancel), called as a function:
    a) a ``cpu_refit`` row that is running (``refit_pool.track(pending=False)``) → HTTPException 409 with
       ``CPU_REFIT_RUNNING``, the row stays ``running`` (its compute cannot be stopped and publishes anyway);
    b) a waiting ``cpu_refit`` row → ``{"status": "cancelled"}``, the row ``cancelled`` (it does not run);
    c) control: a running tracked ``image_generation`` row → cancelled as before;
    d) the TaskPanel keeps a 409's message (``ApiError.message`` = the server's ``detail``) and renders it through
       ``t()`` — before, its ``catch {}`` dropped it silently. Before the fix a) answered ``cancelled`` and marked
       the row cancelled while the refit went on.
[11] ``TaskQueue.track_finish_if_open``. Old body (inline, verbatim from 101d1f505) with a cancel landing between
    its SELECT and its ``track_finish`` → returns True and the row reads ``completed``: the cancel is lost. New:
    a) a cancel landing before the write (hooked into the method's first step) → False, the row stays
       ``cancelled`` / "Manuell abgebrochen"; b) open running row → True, ``completed`` / ""; a later cancel finds
       it closed → False; c) pending row with ``error="boom"`` → True, ``failed`` / "boom"; d) again with
       another error → False, ``failed`` / "boom" kept; e) unknown id → False; f) a queued (not tracked) row →
       False, still ``pending``.
"""
import os
import sys
import time

OLD_COMMIT = "3f2ce338e1c2d821275709a8e54424b939f1117d"
SLEEP = 30.0


# --- worker side (picklable, no side effects at import) --------------------------------------------------------

def nap(seconds):
    time.sleep(seconds)


def crash_soon():
    time.sleep(0.3)
    os._exit(3)


def timed(seconds):
    t0 = time.time()
    time.sleep(seconds)
    return os.getpid(), t0, time.time()


# --- the stand-in servers ([1], [2]) ---------------------------------------------------------------------------

CHILD_SWEEP = r'''
import json, logging, os, sys, threading, time


def main():
    sys.path.insert(0, sys.argv[1])
    sleep = float(sys.argv[2])
    warnings = []

    class Catch(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                warnings.append(record.getMessage())
    logging.getLogger().addHandler(Catch())
    logging.getLogger().setLevel(logging.INFO)
    from app.core import garment_refit, refit_pool
    refit_pool.configured_workers = lambda: 2
    refit_pool.enable()
    finished, returned = {}, []
    refit_pool.track = lambda name, label, pending=True: f"t-{name}"
    refit_pool.activate = lambda task_id, label=None: None
    refit_pool.cancelled = lambda task_id: False
    refit_pool.finish = lambda task_id, error="": finished.setdefault(task_id, error)
    refit_pool.release = lambda task_id: finished.setdefault(task_id, "")
    garment_refit._busy = lambda name: False
    garment_refit._count = lambda name: 1
    garment_refit._posture_due = lambda name: False
    garment_refit._posture = lambda name: []

    def fake_refit(name, on_hold=None):
        if on_hold:
            on_hold()
        refit_pool.run(time.sleep, sleep)
        returned.append(name)
        return [name]
    garment_refit.refit_character = fake_refit
    # A pool of 3 computing — replaced by the sweep's pool of 2 (a resize) while its call runs on.
    old = refit_pool._get_pool(3)
    old.submit(time.sleep, sleep)
    deadline = time.time() + 30
    while time.time() < deadline and not old._processes:
        time.sleep(0.05)
    old_pids = sorted(old._processes)
    names = ["A", "B", "C", "D", "E", "F"]
    tracks = {n: f"t-{n}" for n in names}
    threading.Thread(target=garment_refit._sweep_parallel, args=(names, tracks, 2),
                     kwargs={"pause": 0.0, "retries": 0, "retry_s": 0.0}, daemon=True).start()
    time.sleep(3.0)
    pool_pids = sorted((refit_pool._pool._processes or {}) if refit_pool._pool is not None else [])
    stop = time.time()
    refit_pool.shutdown()
    time.sleep(1.0)

    def alive(pid):
        try:
            state = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return False
        return state != "Z"
    import multiprocessing
    print(json.dumps({"stop": stop, "finished": finished, "returned": returned, "warnings": warnings,
                      "old_pids": old_pids, "pool_pids": pool_pids,
                      "alive": [p for p in old_pids + pool_pids if alive(p)],
                      "children": [p.pid for p in multiprocessing.active_children()]}), flush=True)


if __name__ == "__main__":
    main()
'''

CHILD_ONE = r'''
import json, os, sys, threading, time


def main():
    sys.path.insert(0, sys.argv[1])
    if sys.argv[2]:
        import refit_pool_old as refit_pool   # on PYTHONPATH, so a spawned worker imports it too
    else:
        from app.core import refit_pool
    refit_pool.configured_workers = lambda: 2
    refit_pool.enable()
    out = {}

    def call():
        try:
            refit_pool.run(time.sleep, 12.0)
            out["outcome"] = "returned"
        except BaseException as e:  # noqa: BLE001
            out["outcome"] = type(e).__name__
    threading.Thread(target=call, daemon=True).start()
    time.sleep(3.0)
    out["stop"] = time.time()
    refit_pool.shutdown()
    time.sleep(0.5)
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
'''

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def run_standin(source, args, old_source=""):
    """Run a stand-in server script; ``(its JSON line, the wall time it ended)``."""
    import json
    import subprocess
    import tempfile
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="refit-stop-") as tmp:
        script = Path(tmp) / "server_standin.py"
        script.write_text(source)
        env = dict(os.environ)
        if old_source:
            (Path(tmp) / "refit_pool_old.py").write_text(old_source)
            env["PYTHONPATH"] = os.pathsep.join([tmp, str(root)])
        # Files, not pipes: a worker that outlives its parent would hold a pipe open.
        out, err = Path(tmp) / "out.txt", Path(tmp) / "err.txt"
        with out.open("w") as fo, err.open("w") as fe:
            try:
                subprocess.run([sys.executable, str(script), str(root), *args], stdout=fo, stderr=fe, timeout=120,
                               cwd=tmp, env=env)
            except subprocess.TimeoutExpired:
                pass
        ended = time.time()
        stdout, stderr = out.read_text(), err.read_text()
    line = next((ln for ln in stdout.splitlines() if ln.startswith("{")), "")
    if not line:
        print(stderr[-3000:])
        return {}, ended
    return json.loads(line), ended


def section_stop():
    from app.core import garment_refit, refit_pool
    print(f"[1] stop during a parallel sweep (SLEEP {SLEEP:.0f} s)")
    data, ended = run_standin(CHILD_SWEEP, [str(SLEEP)])
    took = ended - data.get("stop", 0.0)
    check("stand-in ended within 5 s of the stop", took <= refit_pool.TERMINATE_GRACE_S + 2.0, True)
    print(f"       (took {took:.1f} s)")
    check("every tracked row STOPPED", data.get("finished"),
          {f"t-{n}": garment_refit.STOPPED for n in "ABCDEF"})
    check("no refit_character returned", data.get("returned"), [])
    check("no call ran once more", [w for w in data.get("warnings", []) if "once more" in w], [])
    check("the resized-away pool's worker existed", len(data.get("old_pids", [])), 1)
    check("the sweep's pool had 2 workers", len(data.get("pool_pids", [])), 2)
    check("no worker alive 1 s after the stop", data.get("alive"), [])
    check("no child process left", data.get("children"), [])


def section_old():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    print("[2] one call at the stop: this tree, and the code before the fix")
    data, ended = run_standin(CHILD_ONE, [""])
    check("this tree: the call raised", data.get("outcome"), "RefitInterrupted")
    took = ended - data.get("stop", 0.0)
    check("this tree: ended within 5 s of the stop", took <= 5.0, True)
    print(f"       (took {took:.1f} s)")
    try:
        source = subprocess.run(["git", "-C", str(root), "show", f"{OLD_COMMIT}:app/core/refit_pool.py"],
                                capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        print(f"  SKIP commit {OLD_COMMIT[:9]} not available")
        return
    data, ended = run_standin(CHILD_ONE, ["old"], old_source=source)
    took = ended - data.get("stop", 0.0)
    check(f"{OLD_COMMIT[:9]}: the call ran once more and held the exit ≥ 8 s", took >= 8.0, True)
    print(f"       (took {took:.1f} s, outcome {data.get('outcome')})")


def section_pool():
    import threading
    from concurrent.futures import wait
    from app.core import refit_pool
    print("[3] pool semantics")
    refit_pool.configured_workers = lambda: 2
    refit_pool.enable()
    out = {}

    def call(i):
        try:
            refit_pool.run(nap, 30.0)
            out[i] = "returned"
        except BaseException as e:  # noqa: BLE001
            out[i] = type(e).__name__
    threads = [threading.Thread(target=call, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    time.sleep(2.5)
    stop = time.monotonic()
    refit_pool.shutdown()
    for t in threads:
        t.join(15)
    check("a) all five interrupted", [out.get(i) for i in range(5)], ["RefitInterrupted"] * 5)
    check("a) within 5 s of the stop", time.monotonic() - stop <= 5.0, True)
    check("a) closing", refit_pool.closing(), True)
    try:
        got = refit_pool.run(len, [1, 2])
    except refit_pool.RefitInterrupted:
        got = "RefitInterrupted"
    check("a) a call after the stop", got, "RefitInterrupted")
    try:
        refit_pool._get_pool(2)
        got = "a pool"
    except refit_pool.RefitInterrupted:
        got = "RefitInterrupted"
    check("a) no pool after the stop", got, "RefitInterrupted")
    refit_pool.enable()
    check("a) enable reopens", (refit_pool.closing(), refit_pool.run(os.getpid) != os.getpid()), (False, True))

    p1 = refit_pool._get_pool(2)
    futures = [p1.submit(nap, 0.5) for _ in range(6)]
    p3 = refit_pool._get_pool(3)
    refit_pool._drop(p1)
    wait(futures, timeout=60)
    check("b) the replaced pool's calls all complete",
          [("cancelled" if f.cancelled() else f.result()) for f in futures], [None] * 6)
    check("b) the current pool stays", refit_pool._pool is p3, True)

    res = {}

    def call2(key, fn, *args):
        try:
            res[key] = refit_pool.run(fn, *args)
        except BaseException as e:  # noqa: BLE001
            res[key] = type(e).__name__
    refit_pool._get_pool(2)
    crash = threading.Thread(target=call2, args=("crash", crash_soon))
    crash.start()
    time.sleep(0.2)
    timers = [threading.Thread(target=call2, args=(f"t{i}", timed, 1.5)) for i in range(3)]
    for t in timers:
        t.start()
    for t in [crash] + timers:
        t.join(120)
    check("c) the crashing call fails alone", res.get("crash"), "WorkerCrashed")
    spans = [res.get(f"t{i}") for i in range(3)]
    ok = all(isinstance(s, tuple) and s[0] != os.getpid() for s in spans)
    check("c) the three timed calls ran in workers", ok, True)
    if ok:
        spans = sorted(spans, key=lambda s: s[1])
        check("c) one re-run at a time (disjoint intervals)",
              all(spans[i][2] <= spans[i + 1][1] for i in range(2)), True)
    refit_pool.shutdown(wait=True)


def main() -> int:
    import json
    import tempfile
    import threading
    from pathlib import Path
    root_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root_dir))
    if not sys.platform.startswith("linux"):
        print("skip: /proc is Linux only")
        return 0
    section_stop()
    section_old()
    section_pool()

    with tempfile.TemporaryDirectory(prefix="refit-interrupt-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        # A temp instance the storage lint can see as one (a name bound to tempfile.mkdtemp).
        inst = Path(tempfile.mkdtemp(prefix="instance-", dir=tmp))
        os.environ["INSTANCE_DIR"] = str(inst)
        (inst / "config.json").write_text(json.dumps({}))
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(inst)
        from app.core import config
        config.load(paths.get_config_path(), instance_path=inst / "config.json")
        from app.core import db
        db.init_schema()
        from app.core import (base_body, fit_attempts, footwear_source, garment_refit, garment_source, garments,
                              outfit_bodies, refit_pool)
        from app.core import garment_store as gs
        from app.core.improvements.base import Candidate, CandidateBusy
        from app.core.improvements.types.fit_refit import FitRefit
        from app.core.task_queue import get_task_queue
        from app.models import character as charmod
        tq = get_task_queue()
        refit_pool.enable(False)

        # --- [4] no refusal for an interruption -----------------------------------------------------------------
        print("[4] an interruption is no refusal")
        notes, body_failures = [], []
        garments._note_outcome = lambda name, item_id, result: notes.append((item_id, dict(result)))
        gs.record_body_failure = lambda *a, **k: body_failures.append(a)
        charmod.get_character_profile = lambda name: {}
        base_body.current_base = lambda name, profile=None: ("bsig", "basesha")
        garment_source.backfill = lambda name: 0
        garment_refit.refusal_stamp = lambda *a, **k: {"fit_version": 1, "inputs_id": "x"}
        for lister in ("outdated_fits", "refused_fits", "outdated_body_fits", "refused_body_fits",
                       "outdated_footwear_sources", "outdated_footwear_fits", "swing_default_fits"):
            setattr(garment_refit, lister, lambda name, profile=None: [])
        garment_refit.outdated_fits = lambda name, profile=None: [("coat", "clothing", "f1f1f1f1f1f1", "edit")]

        def raising(exc):
            def fit(*_a, **_k):
                raise exc
            return fit
        garments._fit = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        try:
            garment_refit.refit_character("Kim")
            got = "returned"
        except refit_pool.RefitInterrupted:
            got = "RefitInterrupted"
        check("a) refit_character propagates", got, "RefitInterrupted")
        check("a) nothing noted", notes, [])
        status = gs.status("Kim", "coat")
        check("a) run status: not running, no failure", (status.get("running_step"), status.get("failed")),
              (None, None))
        garments._fit = raising(RuntimeError("boom"))
        check("a) control: a real failure", garment_refit.refit_character("Kim"), [])
        check("a) control: noted as a stamped refusal",
              [(i, r.get("ok"), r.get("error"), bool(r.get("refusal_stamp"))) for i, r in notes],
              [("coat", False, "boom", True)])
        notes.clear()
        garment_refit.outdated_fits = lambda name, profile=None: []
        garment_refit.refused_fits = lambda name, profile=None: [("coat2", "clothing", "f2f2f2f2f2f2", "edit")]
        garments._fit = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        try:
            garment_refit.refit_character("Kim")
            got = "returned"
        except refit_pool.RefitInterrupted:
            got = "RefitInterrupted"
        check("b) _retry_refused propagates, notes nothing", (got, notes), ("RefitInterrupted", []))
        garment_refit.refused_fits = lambda name, profile=None: []
        garment_refit.outdated_body_fits = lambda name, profile=None: [("coat", "clothing", "f1f1f1f1f1f1", "ob0000beef")]
        gs.accepted_fit = lambda *a, **k: (Path("fit.glb"), {})
        garments.fit_on_body = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        try:
            garment_refit.refit_character("Kim")
            got = "returned"
        except refit_pool.RefitInterrupted:
            got = "RefitInterrupted"
        check("b) _refit_bodies propagates, records nothing", (got, body_failures), ("RefitInterrupted", []))
        garment_refit.outdated_body_fits = lambda name, profile=None: []

        interrupted = refit_pool.RefitInterrupted("refit interrupted — test")
        try:
            try:
                raise interrupted
            except refit_pool.RefitInterrupted as inner:
                raise ValueError("wrapped") from inner
        except ValueError as e:
            wrapped = e
        check("c) _is_load", [garments._is_load(interrupted), garments._is_load(wrapped),
                              garments._is_load(RuntimeError("x"))], [True, True, False])
        check("c) the body before the fix said no",
              footwear_source.failure_of(interrupted)[0] == footwear_source.LOAD, False)
        fit_attempts._store = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        try:
            fit_attempts.store("Kim", "coat", "f1f1f1f1f1f1", body="", kind="clothing", record={}, error="e", gates=None)
            got = "returned"
        except refit_pool.RefitInterrupted:
            got = "RefitInterrupted"
        check("d) fit_attempts.store re-raises", got, "RefitInterrupted")
        fit_attempts._store = raising(ValueError("disk"))
        check("d) any other failure: False", fit_attempts.store("Kim", "coat", "f1f1f1f1f1f1", body="", kind="clothing",
                                                                record={}, error="e", gates=None), False)

        # --- [5] cancelled tracked refits -----------------------------------------------------------------------
        print("[5] a cancelled tracked refit stays cancelled")
        tid = refit_pool.track("Kim", "Refit · Kim (1 fit)", pending=True)
        tq.track_cancel(tid)
        refit_pool.finish(tid)
        check("a) finish keeps cancelled", tq.task_status(tid), "cancelled")

        runs = []
        gate = threading.Event()

        def recorder(character_name, item_id, *, steps=None, view=None, force=False, state=None, only=False,
                     beside=False, prerequisites=False):
            runs.append((item_id, steps))
            if item_id == "A":
                gate.wait(30)
            return {"ok": True, "fsig": "f", "ran": [str(steps)]}
        garments.check_run = lambda *a, **k: None
        garments.check_body_run = lambda *a, **k: None
        garments.run_garment = recorder
        garments._base_in_flight = lambda name: "base step"   # the fit-only click queues (no refit beside)

        def wait_for(pred, timeout=10.0):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if pred():
                    return True
                time.sleep(0.02)
            return False
        garments.start_garment("Kim", "A")
        check("b) A runs", wait_for(lambda: ("A", None) in runs), True)
        garments.start_garment("Kim", "B", steps="fit")
        with garments._lock:
            job_b = next(j for j in garments._queues["Kim"] if j.item_id == "B")
        check("b) B waits with a pending row", tq.task_status(job_b.track), "pending")
        b_track = job_b.track
        tq.track_cancel(b_track)
        gate.set()
        check("b) B's job done", job_b.done.wait(10), True)
        check("b) run_garment never ran B", [r for r in runs if r[0] == "B"], [])
        check("b) B's result", (job_b.result.get("ok"), job_b.result.get("cancelled")), (False, True))
        check("b) B's row stays cancelled", tq.task_status(b_track), "cancelled")
        check("b) the FIFO is idle", wait_for(lambda: not garments.busy("Kim")), True)

        called = []
        garment_refit.refit_character = lambda name, on_hold=None: called.append(name) or ["x"]
        garment_refit._busy = lambda name: False
        garment_refit._count = lambda name: 1
        tracks = {"Lu": refit_pool.track("Lu", "Refit · Lu (1 fit)", pending=True)}
        tq.track_cancel(tracks["Lu"])
        check("c) a retry attempt of a cancelled row", garment_refit._attempt("Lu", tracks, False, 0.0),
              ("done", []))
        check("c) refit_character not called, row cancelled", (called, tq.task_status(tracks["Lu"])),
              ([], "cancelled"))

        # --- [6] an explicit click takes over a waiting automatic run -------------------------------------------
        print("[6] an explicit click over a waiting automatic run")
        runs.clear()
        gate.clear()
        garments.cached_failure = lambda name, item_id, **kw: {"fsig": "f", "step": "fit", "error": "old refusal"}
        garments.start_garment("Kim", "A")
        check("A runs", wait_for(lambda: ("A", None) in runs), True)
        job_c = garments.enqueue_garment("Kim", "C", automatic=True)
        check("C waits automatic", job_c.automatic, True)
        garments.start_garment("Kim", "C", steps="mesh")
        with garments._lock:
            waiting = list(garments._queues.get("Kim") or ())
        check("the click took over the same job", [j is job_c for j in waiting], [True])
        check("now explicit", job_c.automatic, False)
        gate.set()
        check("C's job done", job_c.done.wait(10), True)
        check("run_garment ran C with steps mesh", [r for r in runs if r[0] == "C"], [("C", "mesh")])
        check("C's result is the run's", job_c.result.get("cached"), None)
        wait_for(lambda: not garments.busy("Kim"))

        # --- [7] running only while work is done ----------------------------------------------------------------
        print("[7] the tracked row is running only while work is done")
        garment_refit._posture_due = lambda name: False
        garment_refit._posture = lambda name: []
        garment_refit.refit_character = lambda name, on_hold=None: None
        tracks = {"Mo": refit_pool.track("Mo", "Refit · Mo (1 fit)", pending=True)}
        first = tracks["Mo"]
        check("a) busy without posture work", garment_refit._attempt("Mo", tracks, True, 0.0),
              (garment_refit.BUSY, []))
        check("a) the row stays pending", (tracks["Mo"], tq.task_status(first)), (first, "pending"))
        garment_refit._posture_due = lambda name: True
        garment_refit._posture = lambda name: ["posture@b1"]
        check("b) posture, then busy", garment_refit._attempt("Mo", tracks, True, 0.0),
              (garment_refit.BUSY, ["posture@b1"]))
        check("b) the posture row completed", tq.task_status(first), "completed")
        second = tracks["Mo"]
        check("b) a new pending row", (second != first, tq.task_status(second)), (True, "pending"))
        held = []

        def refits(name, on_hold=None):
            on_hold()
            held.append(tq.task_status(tracks["Mo"]))
            return ["x"]
        garment_refit.refit_character = refits
        check("c) the next attempt refits", garment_refit._attempt("Mo", tracks, False, 0.0), ("done", ["x"]))
        check("c) running while it refitted, then completed", (held, tq.task_status(second)),
              (["running"], "completed"))

        outfit_bodies.match_stale_postures = lambda name: ["b1"]
        garment_refit.refit_character = lambda name, on_hold=None: None

        def rows(name):
            with tq._connect() as conn:
                return [r[0] for r in conn.execute("SELECT status FROM tasks WHERE agent_name=? AND task_type=? "
                                                   "ORDER BY created_at", (name, refit_pool.TASK_TYPE))]
        try:
            FitRefit().apply(Candidate("character:Nia", "Nia"), {}, "task")
            got = "applied"
        except CandidateBusy:
            got = "CandidateBusy"
        check("d) postures then busy: CandidateBusy, the row completed", (got, rows("Nia")),
              ("CandidateBusy", ["completed"]))
        garment_refit.refit_character = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        try:
            FitRefit().apply(Candidate("character:Ola", "Ola"), {}, "task")
            got = "applied"
        except CandidateBusy:
            got = "CandidateBusy"
        check("d) interrupted: CandidateBusy (deferred)", got, "CandidateBusy")

        # --- [8] the footwear chain: an interruption is retried later -----------------------------------------
        print("[8] the footwear chain answers retry_later for an interruption")
        from app.core import garment_footwear
        name = type(refit_pool.RefitInterrupted("x")).__name__
        check("the footwear failure of RefitInterrupted",
              garment_footwear._failure("Kim", "shoe", "f1f1f1f1f1f1", "fit", "x", None, [], name).get("retry_later"),
              True)
        check("control: a plain failure is persisted",
              garment_footwear._failure("Kim", "shoe", "f1f1f1f1f1f1", "fit", "x", None, [], "RuntimeError")
              .get("retry_later"), None)

        # --- [9] body_fit records no body refusal for an interruption ------------------------------------------
        print("[9] body_fit: an interruption is no body refusal")
        body_id = "ob0000beef"
        base_glb = root / "coat_f1f1f1f1f1f1.glb"
        base_glb.write_bytes(b"BASE FIT")
        gs._garment_kind = lambda item_id: "clothing" if item_id == "coat" else "footwear"
        garments.body_sha256 = lambda name, body: "bodysha"
        garments.body_fit_state = lambda *a, **k: "missing"
        gs.body_failure = lambda *a, **k: None

        def body_fit_outcome(call):
            body_failures.clear()
            try:
                call()
                got = "returned"
            except refit_pool.RefitInterrupted:
                got = "RefitInterrupted"
            except Exception as e:  # noqa: BLE001 — the control may stop later, on the stubbed state
                got = type(e).__name__
            return got, len(body_failures)

        def clothing():
            return garments.body_fit("Kim", "coat", body_id=body_id, body_sha="bodysha",
                                     base_fit=(base_glb, {"kind": "clothing"}), profile={}, build=True)
        garments.fit_on_body = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        check("a) garments.body_fit: propagates, nothing recorded", body_fit_outcome(clothing)[0:2],
              ("RefitInterrupted", 0))
        garments.fit_on_body = raising(RuntimeError("boom"))
        check("a) control: a real failure is recorded on the body", body_fit_outcome(clothing)[1], 1)

        garment_footwear._fsig = lambda name, item_id, profile: "f2f2f2f2f2f2"
        garment_footwear.fit_state = lambda *a, **k: "missing"
        garment_footwear.source_ready = lambda item_id: True
        garment_footwear._base_fit_sha = lambda *a, **k: "basefitsha"

        def shoe():
            return garment_footwear.body_fit("Kim", "shoe", body_id=body_id, body_sha="bodysha", profile={},
                                             build=True)
        garment_footwear.fit = raising(refit_pool.RefitInterrupted("refit interrupted — test"))
        check("b) garment_footwear.body_fit: propagates, nothing recorded", body_fit_outcome(shoe),
              ("RefitInterrupted", 0))
        garment_footwear.fit = raising(RuntimeError("boom"))
        check("b) control: a real failure is recorded on the body", body_fit_outcome(shoe)[1], 1)

        # --- [10] the TaskPanel Cancel of a CPU refit ----------------------------------------------------------
        print("[10] DELETE /queue/tasks/{id}: a computing CPU refit answers 409, a waiting one is cancelled")
        from fastapi import HTTPException
        from app.routes import queue as queue_route

        def delete(task_id):
            try:
                return queue_route.cancel_task(task_id).get("status")
            except HTTPException as e:
                return (e.status_code, e.detail)
        computing = refit_pool.track("Pia", "Refit · Pia", pending=False)
        check("a) computing: 409 with the reason", delete(computing), (409, queue_route.CPU_REFIT_RUNNING))
        check("a) its row stays running", tq.task_status(computing), "running")
        waiting = refit_pool.track("Pia", "Refit · Pia", pending=True)
        check("b) waiting: cancelled", (delete(waiting), tq.task_status(waiting)), ("cancelled", "cancelled"))
        other = tq.track_start("image_generation", "Image · Pia", agent_name="Pia", start_running=True)
        check("c) control: a running tracked task of another type is cancelled",
              (delete(other), tq.task_status(other)), ("cancelled", "cancelled"))
        tq.track_finish_if_open(computing)
        panel = (Path(__file__).resolve().parent.parent / "packages/player-ui/src/TaskPanel.tsx").read_text()
        check("d) the TaskPanel keeps a 409's message and renders it through t()",
              ("err.status === 409) setCancelRefused(err.message)" in panel, "{t(cancelRefused)}" in panel),
              (True, True))

        # --- [11] track_finish_if_open never overwrites a cancel ---------------------------------------------------
        print("[11] track_finish_if_open: one conditional write, a cancel stays cancelled")

        def row(task_id):
            with tq._connect() as conn:
                r = conn.execute("SELECT status, error FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return (r[0], r[1]) if r else None

        def old_track_finish_if_open(task_id, error=""):  # body at 101d1f505, verbatim
            with tq._write_lock, tq._connect() as conn:
                r = conn.execute("SELECT status FROM tasks WHERE task_id=? AND task_origin='tracked'",
                                 (task_id,)).fetchone()
            if not r or r[0] not in ("pending", "running"):
                tq._held_tracks.discard(task_id)
                return False
            tq.track_finish(task_id, error=error)
            return True

        class CancelFirst(set):
            """``_held_tracks`` whose ``discard`` lets a TaskPanel cancel land first (the first thing the method
            does, before it writes) — once: ``track_cancel`` discards too."""
            fired = False

            def discard(self, task_id):
                if not self.fired:
                    self.fired = True
                    tq.track_cancel(task_id)
                super().discard(task_id)

        live = tq.track_start("cpu_refit", "Refit · Ria", agent_name="Ria", start_running=True)
        real_finish = tq.track_finish
        tq.track_finish = lambda task_id, error="": (tq.track_cancel(task_id), real_finish(task_id, error))[1]
        old_ret = old_track_finish_if_open(live)
        tq.track_finish = real_finish
        check("old body: a cancel between its read and its write is overwritten", (old_ret, row(live)[0]),
              (True, "completed"))
        held = tq._held_tracks
        live = tq.track_start("cpu_refit", "Refit · Ria", agent_name="Ria", start_running=True)
        tq._held_tracks = CancelFirst(held)
        new_ret = tq.track_finish_if_open(live)
        tq._held_tracks = held
        check("a) a cancel landing before the write: False, the row stays cancelled", (new_ret, row(live)),
              (False, ("cancelled", "Manuell abgebrochen")))
        live = tq.track_start("cpu_refit", "Refit · Ria", agent_name="Ria", start_running=True)
        check("b) open, no error: True, completed", (tq.track_finish_if_open(live), row(live)),
              (True, ("completed", "")))
        check("b) a cancel after it finds the row closed", tq.track_cancel(live), False)
        live = tq.track_start("cpu_refit", "Refit · Ria", agent_name="Ria", start_running=False)
        check("c) pending, with an error: True, failed", (tq.track_finish_if_open(live, error="boom"), row(live)),
              (True, ("failed", "boom")))
        check("d) already finished: False, its own status and error kept",
              (tq.track_finish_if_open(live, error="other"), row(live)), (False, ("failed", "boom")))
        check("e) unknown id: False", tq.track_finish_if_open("track_nope"), False)
        tq.pause_queue("smoke_paused")  # no worker dequeues it meanwhile
        queued = tq.submit("smoke_noop_type", {}, queue_name="smoke_paused")
        check("f) a queued (not tracked) row: False, untouched",
              (tq.track_finish_if_open(queued), row(queued)[0]), (False, "pending"))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
