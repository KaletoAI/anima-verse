#!/usr/bin/env python3
"""Smoke: ``figure_build.figure_info`` runs one computation per character and key at a time (plus one follower,
``single_flight.SerialFlight``), and the Build's live step progress (``build.step.live``) is no longer part of the
memo key — the fresh ``build`` is set on every answer after the memo (plan
docs/superpowers/plans/2026-11-24-figure-poll-caches.md, Task 3).

Usage:
    ./.venv/bin/python scripts/smoke_figure_info_flight.py

Runs without a server, LLM or HTTP on a throwaway world: ``STORAGE_DIR`` / ``INSTANCE_DIR`` point at temp dirs and
``paths.init(<tmp>)`` runs BEFORE any world-DB module is imported. One character "demo" is created in that world
(the real ``_profile_of`` and ``_info_key`` run). Patched:

- ``figure_build.state`` -> ``{"running": R, "failed": {}, "step": {"name": "fit", "live": {"elapsed_s": T}}}``
  with R (default True) and T set by the test.
- ``figure_build._figure_info`` -> counts its calls (n), records the highest number running at the same time,
  runs a per-section hook, sleeps 0.2 s and returns ``{"build": build, "n": n, "big": [...]}`` (``big`` = 3000 small
  dicts, so a deepcopy takes a few milliseconds).

Precondition (checked on the REAL ``_figure_info_body`` source — the body behind the read-scope wrapper — before patching): it reads ``build`` only as
``build["failed"]``, ``build["running"]``, ``build.get("step")`` (and of the step only ``.get("name")``), never
mentions "live", and hands it on unchanged as ``"build": build``. So a key without ``step.live`` stands for the
whole answer except ``build``, which figure_info sets fresh.

Expected values, by hand:

[F1] Cold memo, 4 threads at once (same T). The first caller starts the run; the three others find a run of the
     slot "demo" with the same key and wait on its future -> _figure_info 1x, all four answers carry n == 1
     (without the flight: 4 computations, n = 1..4).
[F2] Memo emptied; two calls one after the other with T=1 and T=2. The key ignores live -> the second call is a
     memo hit -> _figure_info 1x in total, the second answer's build.step.live.elapsed_s == 2 (fresh build).
     Before Task 3: live is in the key -> 2 computations.
[F3] Memo emptied. Thread A computes; inside its _figure_info figure.invalidate() moves the generation and only
     THEN B and C start. B's key (new generation) differs from A's -> B creates the slot's one follower, C joins
     it. The follower computes only after A has ended -> _figure_info 2x in total, highest concurrency 1, B and C
     end after A, B and C both carry n == 2. A's result is not stored (the generation moved during it), so
     afterwards _info_memo["demo"] holds the follower's answer (n == 2) under a key whose generation is the
     current one.
[F4] Memo emptied; _figure_info raises ValueError (after 0.2 s); 3 threads -> all three get ValueError,
     _figure_info 1x, afterwards _INFO_FLIGHT.in_flight() == 0.
[F5] Memo emptied; 3 threads at once, the first to get its answer sets r["generation_pause"] = 1 right away. The
     other two answers and _info_memo["demo"][2] have no "generation_pause" key (every caller owns a copy).
[F5b] Memo emptied; the thread that COMPUTES (thread ident recorded inside _figure_info) writes
     "generation_pause" and "plain_body" plus 2000 extra keys into its answer right after figure_info returns
     (the hook of get_figure, routes/figure.py), while 2 waiters deepcopy theirs. Expected: nobody raises, neither
     the waiters' answers nor _info_memo["demo"][2] carry "generation_pause" or "plain_body".
[F6] After a warm memo (1 computation, R=True), R switches to False with the same live -> "running" is part of the
     key -> a new key -> _figure_info computes again: 2 computations in total.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_figure_info_flight_"))
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


_lock = threading.Lock()
S = {"running": True, "t": 1, "calls": 0, "active": 0, "max": 0, "hook": None, "raise": False, "threads": []}


def reset():
    with _lock:
        S.update(running=True, t=1, calls=0, active=0, max=0, hook=None, threads=[])
        S["raise"] = False


def precondition(src: str) -> None:
    import re
    names = set(re.findall(r'build\["(\w+)"\]', src)) | set(re.findall(r'build\.get\("(\w+)"\)', src))
    check("pre build fields read", names <= {"failed", "running", "step"}, True)
    check("pre step only .get(name)", re.findall(r'build\.get\("step"\) or \{\}\)\.(\w+\("\w+"\))', src),
          ['get("name")'])
    check("pre no live", bool(re.search(r"\blive\b", src)), False)
    check("pre build handed on unchanged", '"build": build,' in src, True)


def main() -> None:
    import inspect
    from app.core import config, db
    config.load(paths.get_config_path(), instance_path=TMP / "instance" / "config.json")
    db.init_schema()
    from app.core import figure, figure_build
    from app.models.character import save_character_profile
    check("create demo", save_character_profile("demo", {"gender": "female", "age": 30}, create_new=True), True)
    # the body behind the read-scope wrapper (read_scope, plan Task 5)
    precondition(inspect.getsource(figure_build._figure_info_body))

    def fake_state(name):
        with _lock:
            return {"running": S["running"], "failed": {}, "step": {"name": "fit", "live": {"elapsed_s": S["t"]}}}

    def fake_info(name, *, profile, build):
        with _lock:
            S["calls"] += 1
            n = S["calls"]
            S["threads"].append(threading.get_ident())
            S["active"] += 1
            S["max"] = max(S["max"], S["active"])
            hook = S["hook"]
        try:
            if hook:
                hook(n)
            time.sleep(0.2)
            if S["raise"]:
                raise ValueError("boom")
            return {"build": build, "n": n, "big": [{"i": i, "v": [i, i + 1]} for i in range(3000)]}
        finally:
            with _lock:
                S["active"] -= 1

    figure_build.state = fake_state
    figure_build._figure_info = fake_info
    info = figure_build.figure_info

    def parallel(count, fn=None):
        out, errs = [None] * count, []

        def one(i):
            try:
                r = info("demo")
                out[i] = r
                if fn:
                    fn(i, r)
            except Exception as e:  # noqa: BLE001
                errs.append(type(e).__name__)

        ts = [threading.Thread(target=one, args=(i,)) for i in range(count)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return out, errs

    # [F1]
    print("[F1] four simultaneous calls, cold memo")
    figure_build._info_memo.clear()
    reset()
    out, errs = parallel(4)
    check("F1 no error", errs, [])
    check("F1 computations", S["calls"], 1)
    check("F1 all n == 1", [r and r["n"] for r in out], [1, 1, 1, 1])

    # [F2]
    print("[F2] the live progress does not break the memo")
    figure_build._info_memo.clear()
    reset()
    S["t"] = 1
    info("demo")
    S["t"] = 2
    r2 = info("demo")
    check("F2 computations", S["calls"], 1)
    check("F2 fresh live", r2["build"]["step"]["live"]["elapsed_s"], 2)

    # [F3]
    print("[F3] invalidate during run A: B and C share one follower after A")
    figure_build._info_memo.clear()
    reset()
    ends, res3 = {}, {}

    def runner(tag):
        res3[tag] = info("demo")
        ends[tag] = time.monotonic()

    bc = [threading.Thread(target=runner, args=(t,)) for t in ("B", "C")]

    def hook3(n):
        if n == 1:
            figure.invalidate()
            for t in bc:
                t.start()

    S["hook"] = hook3
    ta = threading.Thread(target=runner, args=("A",))
    ta.start()
    ta.join()
    for t in bc:
        t.join()
    S["hook"] = None
    check("F3 computations", S["calls"], 2)
    check("F3 concurrency", S["max"], 1)
    check("F3 A n", res3["A"]["n"], 1)
    check("F3 B, C n", (res3.get("B", {}).get("n"), res3.get("C", {}).get("n")), (2, 2))
    check("F3 B and C end after A", ends.get("B", 0) > ends["A"] and ends.get("C", 0) > ends["A"], True)
    hit = figure_build._info_memo.get("demo")
    check("F3 memo holds the follower's answer", hit and hit[2]["n"], 2)
    check("F3 memo key is the current generation", hit and hit[0][0] == figure._generation[0], True)

    # [F4]
    print("[F4] an exception reaches every caller")
    figure_build._info_memo.clear()
    reset()
    S["raise"] = True
    out, errs = parallel(3)
    check("F4 all ValueError", sorted(errs), ["ValueError"] * 3)
    check("F4 computations", S["calls"], 1)
    check("F4 in_flight", figure_build._INFO_FLIGHT.in_flight(), 0)
    S["raise"] = False

    # [F5]
    print("[F5] a waiter mutates its answer")
    figure_build._info_memo.clear()
    reset()
    first = []
    flock = threading.Lock()

    def mut5(i, r):
        with flock:
            if first:
                return
            first.append(i)
        r["generation_pause"] = 1

    out, errs = parallel(3, mut5)
    check("F5 no error", errs, [])
    others = [r for i, r in enumerate(out) if i not in first]
    check("F5 others clean", [("generation_pause" in r) for r in others], [False, False])
    check("F5 memo clean", "generation_pause" in figure_build._info_memo["demo"][2], False)

    # [F5b]
    print("[F5b] the first computer mutates its answer while waiters copy")
    figure_build._info_memo.clear()
    reset()
    waiters = []

    def mut5b(i, r):
        if threading.get_ident() in S["threads"]:
            r["generation_pause"] = 1
            r["plain_body"] = {"x": 1}
            for k in range(2000):
                r[f"k{k}"] = k
        else:
            waiters.append(r)

    out, errs = parallel(3, mut5b)
    check("F5b no error", errs, [])
    check("F5b computations", S["calls"], 1)
    check("F5b two waiters", len(waiters), 2)
    check("F5b waiters clean", [("generation_pause" in r or "plain_body" in r) for r in waiters], [False, False])
    memo = figure_build._info_memo["demo"][2]
    check("F5b memo clean", "generation_pause" in memo or "plain_body" in memo, False)

    # [F6]
    print("[F6] running True -> False is a new key")
    figure_build._info_memo.clear()
    reset()
    info("demo")
    S["running"] = False
    r6 = info("demo")
    check("F6 computations", S["calls"], 2)
    check("F6 fresh running", r6["build"]["running"], False)


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
