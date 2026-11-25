#!/usr/bin/env python3
"""Smoke: ``GET /characters/open-steps`` runs one roster computation at a time plus one follower
(``single_flight.SerialFlight``), and stale badges are refreshed by two background workers instead of a thread
per character (plan docs/superpowers/plans/2026-11-24-figure-poll-caches.md, Task 2).

Usage:
    ./.venv/bin/python scripts/smoke_open_steps_flight.py

Runs without a server, LLM or HTTP on a throwaway world: ``STORAGE_DIR`` / ``INSTANCE_DIR`` point at temp dirs and
``paths.init(<tmp>)`` runs BEFORE any world-DB module is imported; importing ``app.routes.figure`` must not pull in
``app.server``. The roster is five characters A..E (``list_available_characters`` patched — the route's roster
read is not what is checked here). ``figure_build.plan`` is patched: it counts its calls, sleeps 0.2 s and records
the highest number of plan calls running at the same time (a counter under a lock). The memo key is patched to
``(figure generation, name)`` (as in smoke_open_steps.py) and the profile read to ``{}``, so no world reads.
Every plan returns one outfit step, so every character is listed. Expected values, by hand:

[O1] Cold memos, four threads call the route ``get_open_steps`` at once. One roster run computes the five
     characters once each -> plan calls = 1 run x 5 characters = 5 (without the flight: up to 4 x 5 = 20;
     the route cap of 3 lets three runs overlap -> 15). All four answers are equal (==) and pairwise distinct
     objects (is not): every caller gets its own copy.
[O2] ``figure.MEMO_TTL_S`` = 0: every memo entry is stale, so one route call serves the five old answers and
     queues the five characters for a background re-plan. Waiting for the workers: plan calls +5, highest plan
     concurrency <= 2 (two workers; a thread per character would give 5), and inside each plan at most two live
     threads named ``open-steps-refresh-*``.
[O3] A second route call 0.1 s after the first of [O2] (no re-plan has finished yet, each takes 0.2 s) finds all
     five names already in ``_open_refreshing`` -> none is queued twice: the total of [O2]+[O3] stays +5.
[O4] ``SerialFlight`` alone: ``compute`` sleeps 0.3 s and raises RuntimeError; three callers on one slot with one
     key (the first computes, the two others arrive 0.1 s later and wait on its future) -> all three get
     RuntimeError, compute ran once; afterwards ``in_flight() == 0`` and a new ``run`` calls ``compute`` again
     (calls 1 -> 2).
[O5] Memo emptied, TTL back to 30 s. Route call A; inside A's fifth (last) plan call ``figure.invalidate()`` moves
     the generation and the test then starts route calls B and C (key = new generation != A's key). B and C join
     the slot's ONE follower, which starts only when A has ended: B and C end after A. A computes 5 plans; the
     follower then plans all five again (chars 1-4 are stored under the old generation, char 5 was not stored
     because the generation moved during it) -> +5 after A, total 10 (two separate follower runs would give 15).
     B's and C's answers are equal; the highest plan concurrency is 1 (never two runs of the slot at once).
     The plans are attributed by thread (A's thread: 5; the follower runs in the thread of B or C: 5), since the
     follower may already plan before A's own thread has returned.
[O6] Mutation by the first computer (review B1): ``compute`` blocks until two waiters are parked on its future
     (released 0.3 s after they start), the waiters' ``share`` is a slow deepcopy (0.05 s per call), and the first
     computer writes 2001 keys into ITS answer right after ``run`` returns. Expected: no exception anywhere, both
     waiters get an answer, neither contains the key "mutated" (the first computer owns a copy, never the
     original), and ``max_concurrent() == 1``.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_open_steps_flight_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "reference.fbx")
for d in ("world", "instance", "clips"):
    (TMP / d).mkdir()

from app.core import paths  # noqa: E402
paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))

failures = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        failures.append(name)


NAMES = ["A", "B", "C", "D", "E"]
_plock = threading.Lock()
P = {"calls": 0, "active": 0, "max": 0, "workers_max": 0, "hook": None, "threads": []}


def reset_counters():
    with _plock:
        P.update(calls=0, active=0, max=0, workers_max=0, threads=[])


def refresh_threads():
    return [t for t in threading.enumerate() if t.name.startswith("open-steps-refresh-")]


def main() -> None:
    from app.core import figure, figure_build
    from app.core.figure_build import Step
    import app.models.character as character_model
    from app.routes import figure as figure_routes
    check("route import keeps app.server out", "app.server" not in sys.modules, True)

    def fake_plan(name, *, profile=None, explicit=True, resolved=None):
        with _plock:
            P["calls"] += 1
            P["threads"].append(threading.get_ident())
            n = P["calls"]
            P["active"] += 1
            P["max"] = max(P["max"], P["active"])
            P["workers_max"] = max(P["workers_max"], len(refresh_threads()))
            hook = P["hook"]
        try:
            if hook:
                hook(name, n)
            time.sleep(0.2)
            return [Step("shape", "Body shape", 4)]
        finally:
            with _plock:
                P["active"] -= 1

    figure_build.plan = fake_plan
    figure_build._info_key = lambda name, profile, build: (figure._generation[0], name)
    figure_build._profile_of = lambda name, profile: {}
    character_model.list_available_characters = lambda include_pooled=False, include_dormant=False, **_: list(NAMES)
    route = figure_routes.get_open_steps

    def call_route():
        return route({})

    def wait_workers(limit=10.0):
        end = time.monotonic() + limit
        while time.monotonic() < end:
            with figure_build._info_lock:
                busy = bool(figure_build._open_refreshing)
            if not busy and not refresh_threads():
                return True
            time.sleep(0.02)
        return False

    # [O1]
    print("[O1] four simultaneous route calls, cold memos")
    figure_build._open_memo.clear()
    reset_counters()
    answers = [None] * 4
    errors = []

    def o1(i):
        try:
            answers[i] = call_route()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=o1, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("O1 no error", errors, [])
    check("O1 plan calls", P["calls"], 5)
    check("O1 answers equal", all(a == answers[0] for a in answers), True)
    check("O1 answers distinct objects",
          all(answers[i] is not answers[j] for i in range(4) for j in range(i + 1, 4)), True)
    check("O1 roster listed", sorted((answers[0] or {}).get("characters", {})), NAMES)

    # [O2] + [O3]
    print("[O2] stale memos refreshed by two workers; [O3] a second call during the refresh")
    saved_ttl = figure.MEMO_TTL_S
    figure.MEMO_TTL_S = 0
    reset_counters()
    call_route()
    time.sleep(0.1)
    call_route()   # [O3]
    check("O2 workers finished", wait_workers(), True)
    figure.MEMO_TTL_S = saved_ttl
    check("O2/O3 plan calls +5 (nothing queued twice)", P["calls"], 5)
    check("O2 plan concurrency <= 2", P["max"] <= 2, True)
    check("O2 refresh threads <= 2", P["workers_max"] <= 2, True)
    print(f"     (max concurrency {P['max']}, refresh threads seen {P['workers_max']})")

    # [O4]
    print("[O4] SerialFlight: an exception reaches every caller")
    from app.core.single_flight import SerialFlight
    sf = SerialFlight()
    c4 = {"n": 0}

    def boom():
        c4["n"] += 1
        time.sleep(0.3)
        raise RuntimeError("boom")

    got4 = []

    def o4():
        try:
            sf.run("slot", lambda: 1, boom)
            got4.append("none")
        except RuntimeError:
            got4.append("RuntimeError")
        except Exception as e:  # noqa: BLE001
            got4.append(type(e).__name__)

    first = threading.Thread(target=o4)
    first.start()
    time.sleep(0.1)
    rest = [threading.Thread(target=o4) for _ in range(2)]
    for t in rest:
        t.start()
    for t in [first] + rest:
        t.join()
    check("O4 all raise", got4, ["RuntimeError"] * 3)
    check("O4 compute once", c4["n"], 1)
    check("O4 in_flight after", sf.in_flight(), 0)

    def again():
        c4["n"] += 1
        return 7

    check("O4 new run computes again", sf.run("slot", lambda: 1, again), 7)
    check("O4 compute calls", c4["n"], 2)

    # [O5]
    print("[O5] invalidate during run A: B and C share one follower after A")
    figure_build._open_memo.clear()
    reset_counters()
    ends = {}
    res5 = {}
    started_bc = threading.Event()

    def runner(tag):
        res5[tag] = call_route()
        ends[tag] = time.monotonic()

    bc = [threading.Thread(target=runner, args=(t,)) for t in ("B", "C")]

    def hook(name, n):
        if n == 5 and not started_bc.is_set():
            figure.invalidate()
            started_bc.set()
            for t in bc:
                t.start()

    P["hook"] = hook
    ta = threading.Thread(target=runner, args=("A",))
    ta.start()
    ta.join()
    for t in bc:
        t.join()
    P["hook"] = None
    by_a = sum(1 for i in P["threads"] if i == ta.ident)
    others = [i for i in P["threads"] if i != ta.ident]
    check("O5 A planned 5", by_a, 5)
    check("O5 follower +5", len(others), 5)
    check("O5 one follower run (one thread, B or C)", len(set(others)) == 1 and others[0] in {t.ident for t in bc},
          True)
    check("O5 total 10", P["calls"], 10)
    check("O5 B and C end after A", ends.get("B", 0) > ends["A"] and ends.get("C", 0) > ends["A"], True)
    check("O5 B == C", res5.get("B") == res5.get("C"), True)
    check("O5 plan concurrency", P["max"], 1)

    # [O6]
    print("[O6] the first computer mutates its own copy while waiters share")
    import copy
    sf6 = SerialFlight()
    release = threading.Event()

    def compute6():
        release.wait(5)
        return {"x": {"y": list(range(200))}}

    def slow_share(v):
        time.sleep(0.05)
        return copy.deepcopy(v)

    errs6 = []
    waiters6 = []

    def first6():
        try:
            mine = sf6.run("s", lambda: 1, compute6, share=slow_share)
            for i in range(2000):
                mine[f"k{i}"] = i
            mine["mutated"] = True
        except Exception as e:  # noqa: BLE001
            errs6.append(e)

    def waiter6():
        try:
            waiters6.append(sf6.run("s", lambda: 1, compute6, share=slow_share))
        except Exception as e:  # noqa: BLE001
            errs6.append(e)

    f6 = threading.Thread(target=first6)
    f6.start()
    time.sleep(0.05)
    w6 = [threading.Thread(target=waiter6) for _ in range(2)]
    for t in w6:
        t.start()
    time.sleep(0.3)
    release.set()
    for t in [f6] + w6:
        t.join()
    check("O6 no exception", errs6, [])
    check("O6 two waiter answers", len(waiters6), 2)
    check("O6 waiters do not see the mutation", any("mutated" in w for w in waiters6), False)
    check("O6 max concurrent", sf6.max_concurrent(), 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        failures.append(f"crash: {e}")
    print("FAILED: " + ", ".join(failures) if failures else "all ok")
    sys.stdout.flush()
    os._exit(1 if failures else 0)
