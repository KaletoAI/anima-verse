#!/usr/bin/env python3
"""Smoke run for the CLIENT-EXECUTION COUNTERS (plan E0/E1, tasks 1 and 2).

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

Ticker counters (task 2): name "client_exec_ticker", keys beat / advance /
advance_run / advance_validate. Each case replaces hps.count with a recorder
``lambda name, key, **kw: calls.append((name, key))`` and stubs every
collaborator, so no world DB is read.

[T1] travel_engine._next_beat_s() with list_active_journeys -> [],
     motion_rate -> 1.0 (plus motion_time -> 0.0, no prop-action engine,
     pose_scene.next_end_in_s -> None): the count sits at the very start of
     the function, every planning is one beat -> exactly
     [("client_exec_ticker", "beat")]. With motion_rate -> 0 (frozen world,
     early return of _TICK_SECONDS) still exactly one beat.
[T2] prop_action_engine.advance(now) with pending_cleanup -> [], live_runs
     -> [{"execution_id": "r1"}, {"execution_id": "r2"}], _advance_run -> 0,
     end_finales and register_owner no-ops: one "advance" (first statement),
     one "advance_run" right before each of the two _advance_run calls ->
     advance x1, advance_run x2, advance_validate x0.
[T3] _advance_run("r1", now, []) on an "approaching" run (not active, not
     sleeping -> straight to _validate), _clock -> (0, 0.0), world not
     frozen, _validate -> "stop", _finish no-op: _validate is reached once
     -> exactly one advance_validate; the failed run returns 0.
[T4] same run, is_world_frozen -> True: _advance_run saves and returns 0
     before _validate -> no advance_validate (no ticker count at all).

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


class Patch:
    """Set attributes for one case and restore them afterwards."""

    def __init__(self):
        self.saved = []

    def set(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)


def _ticker_calls(calls):
    return [c for c in calls if c[0] == "client_exec_ticker"]


def _run_patched(setup, body):
    """Patch hps.count with a recorder plus whatever setup(p) sets, run body,
    restore; returns (body result, recorded calls)."""
    calls = []
    p = Patch()
    try:
        p.set(hps, "count", lambda name, key, **kw: calls.append((name, key)))
        setup(p)
        result = body()
    finally:
        p.undo()
    return result, calls


def t1():
    print("\n[T1] every _next_beat_s planning counts one beat")
    from app.core import travel_engine, timeutils, pose_scene
    from app.models import character as C

    for rate, label in ((1.0, "T1 running world"), (0, "T1 frozen world")):
        def setup(p, rate=rate):
            p.set(C, "list_active_journeys", lambda: [])
            p.set(timeutils, "motion_rate", lambda: rate)
            p.set(timeutils, "motion_time", lambda: 0.0)
            p.set(travel_engine, "_prop_action_engine", lambda: None)
            p.set(pose_scene, "next_end_in_s", lambda: None)
        _, calls = _run_patched(setup, travel_engine._next_beat_s)
        check(label, _ticker_calls(calls), [("client_exec_ticker", "beat")])


def t2():
    print("\n[T2] advance counts itself and each run step")
    from app.core import prop_action_engine as pae, pose_scene

    def setup(p):
        p.set(pae, "register_owner", lambda: None)
        p.set(pae.store, "pending_cleanup", lambda: [])
        p.set(pae.store, "live_runs",
              lambda: [{"execution_id": "r1"}, {"execution_id": "r2"}])
        p.set(pae, "_advance_run", lambda execution_id, now, beats: 0)
        p.set(pose_scene, "end_finales", lambda **kw: None)
    result, calls = _run_patched(setup, lambda: pae.advance(None))
    keys = [k for _, k in _ticker_calls(calls)]
    check("T2 advance x1", keys.count("advance"), 1)
    check("T2 advance_run x2", keys.count("advance_run"), 2)
    check("T2 advance_validate x0", keys.count("advance_validate"), 0)
    check("T2 nothing advanced", result, 0)


def _approaching_run():
    return {"status": "approaching",
            "definition": {"ability": "sit", "interrupt_on_presence_change": False},
            "data": {}, "actor": "a", "members": [], "target": {},
            "action_id": "x", "phase": "walk"}


def _advance_run_case(frozen):
    import contextlib
    from app.core import prop_action_engine as pae

    def setup(p):
        p.set(pae.store, "get", lambda execution_id: _approaching_run())
        p.set(pae, "_lock", lambda ref: contextlib.nullcontext())
        p.set(pae, "_clock", lambda run, now: (0, 0.0))
        p.set(pae, "is_world_frozen", lambda: frozen)
        p.set(pae, "_validate", lambda run, **kw: "stop")
        p.set(pae, "_finish", lambda run, status, reason, **kw: None)
        p.set(pae, "_save", lambda run: None)
    return _run_patched(setup, lambda: pae._advance_run("r1", None, []))


def t3():
    print("\n[T3] _advance_run counts the validation it reaches")
    result, calls = _advance_run_case(frozen=False)
    check("T3 one advance_validate", _ticker_calls(calls),
          [("client_exec_ticker", "advance_validate")])
    check("T3 returns 0", result, 0)


def t4():
    print("\n[T4] a frozen world never reaches the validation")
    result, calls = _advance_run_case(frozen=True)
    check("T4 no ticker count", _ticker_calls(calls), [])
    check("T4 returns 0", result, 0)


def main() -> int:
    for case in (c1, c2, c3, c4, t1, t2, t3, t4):
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
