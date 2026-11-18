#!/usr/bin/env python3
"""Smoke: the image routing at RUN time (``routing.run_routed``) — the re-run after a failure, the gate retry on the
next chain entry, and the overflow to a later backend with room.

Usage:  ./.venv/bin/python scripts/smoke_image_routing_runtime.py

No server, no network, no world DB: fake backends (``_smoke_image_routing.Fake``) in a real BackendPool, the render
is a local function (0 outbound requests, no hub jobs). Chain resolution itself is smoke_image_routing_resolve.py,
the service façade smoke_image_service_facade.py. Three sections, one per former smoke; each installs its own
routing stubs; a failing section does not stop the next, the run exits non-zero and names every failed section.

[1] RE-RUN (formerly smoke_image_routing_reentry).
Spec: development_instructions/plan-image-routing.md § 4 + review notes
("Neuanlauf — typisiertes Signal"). No server, no network, no world DB: fake
backends in a real BackendPool; `render(backend)` is the caller's function —
here it goes through the REAL `BackendPool.run_on_backend`, so the failure
classes are the real ones.

Every case builds FRESH fakes (cooldowns do not leak between cases).
Behaviour per backend name prefix of the op:
  ok*     -> returns [b"img"]
  dead*   -> RuntimeError("HTTP 500: gone")      (cooldown -> BackendFailedError)
  empty*  -> []                                   (cooldown -> BackendFailedError)
  busy*   -> BackendBusyError                     (no cooldown)
  bad*    -> RuntimeError("HTTP 400: bad input")  (payload error, no cooldown)
  cancel* -> GpuTaskCancelled
  late*   -> GpuTaskTimeout
  off*    -> MediaGenerationDisabled
  quota*  -> TooManyJobsError
  nochan* -> NoBackendChannelError
Every fake costs 1 except "cloud" (cost 9, ok) which is in NO chain.

EXPECTED (by hand):
 1. rules ["dead1", "ok1", "ok2"] -> render calls [dead1, ok1]; result from
    ok1; route.position 2; route_meta has fallback_from
    {"occasion": "photo", "intended_spec": "dead1", "position": 1}.
 2. ["empty1", "ok1"] -> calls [empty1, ok1] (empty result is a failure too).
 3. ["busy1", "ok1"] -> BackendBusyError out, calls [busy1] (load: no re-run).
 4. ["bad1", "ok1"] -> RuntimeError (not BackendFailedError) out, calls [bad1].
 5. ["cancel1", "ok1"] -> GpuTaskCancelled out, calls [cancel1].
 6. ["late1", "ok1"] -> GpuTaskTimeout out, calls [late1].
 7. ["off1", "ok1"] -> MediaGenerationDisabled, calls [off1].
 8. ["quota1", "ok1"] -> TooManyJobsError, calls [quota1].
 9. ["nochan1", "ok1"] -> NoBackendChannelError, calls [nochan1].
10. ["dead1", "dead2", "dead3", "ok1"] -> at most 2 re-runs = 3 backends:
    calls [dead1, dead2, dead3], BackendFailedError out; ok1 never asked.
11. ["dead1"] -> dead1 fails, the re-resolve finds nothing -> NoRouteError
    out; calls [dead1]; "cloud" (cheapest-of-kind fallback) NEVER asked.
12. no rules at all (empty chain) and the only live backends are dead1
    (cost 1) and cloud (9): cheapest = dead1 -> BackendFailedError out, NO
    re-run (position None), calls [dead1].
13. a NESTED failure: rules ["ok1", "ok2"]; render on ok1 runs a helper step
    that fails with BackendFailedError for backend "helper" (not in the
    chain). The failure is not the routed backend's (e.backend_name "helper"
    != route.backend.name "ok1") -> no re-run: calls ["ok1"], the
    BackendFailedError (backend_name "helper") propagates, ok1 and ok2 are
    not cooled down (nothing ran through run_on_backend's failure branch)
    and ok2 is never asked. (The code at 58672d18 trusted e.backend: it
    excluded "helper" and re-rendered ok1 -> calls ["ok1", "ok1", "ok1"].)
14. is_character_match("photo", "someone", "Flux Big") with the character's
    own spec "Flux*" -> True; "Qwen A" -> False; no character spec -> False.

[2] RETRY ATTEMPT (formerly smoke_image_routing_attempt): gate retries run on the NEXT chain entry
(routing.retry_attempt).
A quality-gated step (garment edit/draft, base-body hand gate, dressed draft,
view-guard re-render, beard edit) renders attempt N inside
``routing.retry_attempt(N)``; ``run_routed`` then aims at the N-th
configuration-passing entry of the occasion's chain, clamped to the last one.
No server, no network, no world DB: fake backends in a real BackendPool, the
render is a local function (0 outbound requests, no hub jobs).

EXPECTED (by hand):
 1. chain ["a1", "b2", "c3"], no attempt context -> render on a1, position 1,
    route_meta has no attempt_entry and no fallback_from.
 2. same chain, retry_attempt(2) -> b2, position 2; route_meta attempt_entry
    {"attempt": 2, "aimed_position": 2, "position": 2}; NO fallback_from (the
    aimed entry is the intended one for a retry, the Improvements queue must
    not re-render it).
 3. retry_attempt(3) -> c3, position 3.
 4. retry_attempt(5) on the 3-entry chain -> clamped to the last: c3.
 5. single-entry chain ["a1"], retry_attempt(2) -> a1 (same as today).
 6. chain ["typo*", "a1", "b2"] ("typo*" matches nothing = configuration
    skip) and retry_attempt(2) -> b2 (the typo is no backend of the chain).
 7. chain ["a1", "dead2", "c3"], retry_attempt(2): dead2 fails (HTTP 500 ->
    cooldown -> BackendFailedError) -> the re-run continues FORWARD from the
    aimed entry: calls [dead2, c3]; route_meta has fallback_from (it ran
    behind the aimed entry).
 8. chain ["a1", "b2"] with b2 unavailable, retry_attempt(2) -> walks
    forward (nothing), then back -> a1 (availability honoured like attempt 1).
 9. explicit pick: resolve_spec("photo", "a1") inside retry_attempt(2) ->
    a1 (the attempt context never touches an explicit pick).
10. the context is restored: after the with-block current_attempt() == 1.
11. explain_occasion: chain ["a1", "b2", "c3"] -> retry_entry
    {"position": 2, "spec": "b2"}; chain ["a1"] -> {"position": 1, "spec": "a1"}.
12. "cloud" (cost 9, in no chain) is never asked in any case above.

[3] OVERFLOW (formerly smoke_image_overflow_routing, Task 3).
EXPECTED by hand (base without overflow: 5e03967c):
R1 local1/cloud1 calls, overflow local1/5s, no fallback.
R2 not accepting, R3 no room, R4 cooldown: local1 only, no overflow.
R5 zero threshold and R6 empty chain: local1 only, watch None.
R7 dead1/local1/cloud1 calls: fallback photo/dead1/position 1 and local1/5s.
R8 local* -> local1/local2: overflow local1/5s, no fallback.
R9 local1/local2/local3: last watch None, overflow local1/10s.
R10 local1/cloud1: cloud cannot go back, final pick None.
R11 helper overflow propagates unchanged, one call, watch reset.
R12 video vid1/vid2: vid1 only, watch None.
R13 explain local1 [], cloud1 [cloud1] as overflow_targets.
R14 local1/deadcloud (deadcloud accepts): local1 overflows to deadcloud, which
    fails (HTTP 500 -> cooldown -> BackendFailedError); the re-run excludes only
    the FAILED backend, lands back on local1 (full, not broken) and renders there:
    calls [local1, deadcloud, local1], picks [deadcloud, None], no overflow_from,
    no fallback_from.
Fakes cost 1; each queue simulation waits exactly 5 seconds.
"""
import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _smoke_image_routing import scratch  # noqa: E402

os.environ["ANIMATION_CLIPS_DIR"] = scratch("routing-runtime-clips-")
from app.core import paths  # noqa: E402
paths.init(scratch("routing-runtime-storage-"))

from _smoke_image_routing import FAILS, Fake, check  # noqa: E402
from app.core.provider_manager import NoBackendChannelError  # noqa: E402
from app.core.provider_queue import TooManyJobsError  # noqa: E402
from app.imagegen import routing  # noqa: E402
import app.imagegen.base as _base  # noqa: E402
from app.imagegen.base import (BackendBusyError, BackendFailedError,  # noqa: E402
                               ChannelOverflow, GpuTaskCancelled, GpuTaskTimeout,
                               MediaGenerationDisabled, OVERFLOW_WATCH)
from app.imagegen.selection import BackendPool  # noqa: E402

FAILED_SECTIONS = []
_REAL_RULES = routing._rules
_REAL_CHARACTER_SPEC = routing._character_spec
_REAL_OVERFLOW_AFTER = _base.image_overflow_after_seconds


def section(name, fn):
    """Run one section with the real routing hooks back in place; a crash or a failed check names the section."""
    print(f"\n=== {name}")
    before = len(FAILS)
    try:
        fn()
    except Exception:  # noqa: BLE001 — a crashed section is a failed section, the others still run
        traceback.print_exc()
        FAILS.append(f"{name}: crashed")
    finally:
        routing._rules = _REAL_RULES
        routing._character_spec = _REAL_CHARACTER_SPEC
        _base.image_overflow_after_seconds = _REAL_OVERFLOW_AFTER
    if len(FAILS) > before:
        FAILED_SECTIONS.append(name)


def section_rerun():
    def behaviour(name):
        if name.startswith("ok") or name == "cloud":
            return [b"img"]
        if name.startswith("dead"):
            raise RuntimeError("HTTP 500: gone")
        if name.startswith("empty"):
            return []
        if name.startswith("busy"):
            raise BackendBusyError("busy")
        if name.startswith("bad"):
            raise RuntimeError("HTTP 400: bad input")
        if name.startswith("cancel"):
            raise GpuTaskCancelled("GPU task cancelled: t")
        if name.startswith("late"):
            raise GpuTaskTimeout("no result within 1s")
        if name.startswith("off"):
            raise MediaGenerationDisabled("off")
        if name.startswith("quota"):
            raise TooManyJobsError(1, 1, "generation job")
        if name.startswith("nochan"):
            raise NoBackendChannelError("no channel")
        raise AssertionError(name)


    RULES = {}
    routing._rules = lambda occasion: list(RULES.get(occasion, []))
    CHAR_SPEC = {"value": ""}
    routing._character_spec = lambda occ_def, character, overrides=None: (  # spec_overrides: 998a19d86
        CHAR_SPEC["value"] if character and occ_def.get("character_scoped") else "")


    POOLS = []


    def run(rules, names=None, nested_failure=None):
        """``nested_failure``: a backend name — render raises a BackendFailedError
        for THAT backend (a failing helper step) instead of rendering."""
        names = names or sorted({n for n in rules} | {"cloud"})
        backends = [Fake(n, cost=9 if n == "cloud" else 1, env_prefix="FAKE_REENTRY_")
                    for n in names]
        pool = BackendPool(backends)
        POOLS.append(pool)
        RULES.clear()
        if rules:
            RULES["photo"] = list(rules)
        calls = []

        def render(backend):
            calls.append(backend.name)
            if nested_failure:
                raise BackendFailedError(Fake(nested_failure),
                                         RuntimeError("HTTP 500: helper gone"))
            result, _used = pool.run_on_backend(backend, op=lambda b: behaviour(b.name))
            return result

        out = err = route = None
        try:
            out, route = routing.run_routed("photo", render, pool=pool)
        except BaseException as e:  # noqa: BLE001 — the type is the expectation
            err = e
        return out, route, err, calls


    out, route, err, calls = run(["dead1", "ok1", "ok2"])
    check("1 calls", calls, ["dead1", "ok1"])
    check("1 result", out, [b"img"])
    check("1 position", route.position if route else None, 2)
    check("1 meta", routing.route_meta(route).get("fallback_from"),
          {"occasion": "photo", "intended_spec": "dead1", "position": 1})

    _o, _r, err, calls = run(["empty1", "ok1"])
    check("2 empty result re-runs", (calls, err), (["empty1", "ok1"], None))

    for num, first, exc in (("3", "busy1", "BackendBusyError"), ("4", "bad1", "RuntimeError"),
                            ("5", "cancel1", "GpuTaskCancelled"), ("6", "late1", "GpuTaskTimeout"),
                            ("7", "off1", "MediaGenerationDisabled"),
                            ("8", "quota1", "TooManyJobsError"),
                            ("9", "nochan1", "NoBackendChannelError")):
        _o, _r, err, calls = run([first, "ok1"])
        check(f"{num} {first} no re-run", (type(err).__name__, calls), (exc, [first]))

    _o, _r, err, calls = run(["dead1", "dead2", "dead3", "ok1"])
    check("10 at most 2 re-runs", (type(err).__name__, calls),
          ("BackendFailedError", ["dead1", "dead2", "dead3"]))

    _o, _r, err, calls = run(["dead1"])
    check("11 chain exhausted", (type(err).__name__, calls), ("NoRouteError", ["dead1"]))

    _o, _r, err, calls = run([], names=["dead1", "cloud"])
    check("12 empty chain: no re-run", (type(err).__name__, calls),
          ("BackendFailedError", ["dead1"]))

    _o, _r, err, calls = run(["ok1", "ok2"], nested_failure="helper")
    check("13 nested failure: no re-run", (type(err).__name__, getattr(err, "backend_name", None), calls),
          ("BackendFailedError", "helper", ["ok1"]))
    check("13 nothing cooled", sorted(b.name for b in POOLS[-1].backends if b.in_cooldown()), [])

    CHAR_SPEC["value"] = "Flux*"
    check("14 character match", routing.is_character_match("photo", "someone", "Flux Big"), True)
    check("14 other backend", routing.is_character_match("photo", "someone", "Qwen A"), False)
    CHAR_SPEC["value"] = ""
    check("14 no character spec", routing.is_character_match("photo", "someone", "Flux Big"), False)



def section_attempt():
    ALL_CALLS = []

    RULES = {}
    routing._rules = lambda occasion: list(RULES.get(occasion, []))
    routing._character_spec = lambda occ_def, character, overrides=None: ""
    # Overflow off: no provider manager, no channel lookups.
    import app.imagegen.base as _base  # noqa: E402
    _base.image_overflow_after_seconds = lambda: 0


    def make_pool(rules, unavailable=()):
        names = sorted({r for r in rules if "*" not in r} | {"cloud"})
        pool = BackendPool([Fake(n, cost=9 if n == "cloud" else 1,
                                 available=n not in unavailable, result=None,
                                 env_prefix="FAKE_ATTEMPT_") for n in names])
        RULES.clear()
        RULES["photo"] = list(rules)
        return pool


    def run(rules, attempt=None, unavailable=()):
        pool = make_pool(rules, unavailable)
        calls = []

        def render(backend):
            calls.append(backend.name)
            ALL_CALLS.append(backend.name)

            def op(b):
                if b.name.startswith("dead"):
                    raise RuntimeError("HTTP 500: gone")
                return [b"img"]
            result, _used = pool.run_on_backend(backend, op=op)
            return result

        if attempt is None:
            _out, route = routing.run_routed("photo", render, pool=pool)
        else:
            with routing.retry_attempt(attempt):
                _out, route = routing.run_routed("photo", render, pool=pool)
        return route, calls


    route, calls = run(["a1", "b2", "c3"])
    meta = routing.route_meta(route)
    check("1 first attempt", (calls, route.position), (["a1"], 1))
    check("1 meta", ("attempt_entry" in meta, "fallback_from" in meta), (False, False))

    route, calls = run(["a1", "b2", "c3"], attempt=2)
    meta = routing.route_meta(route)
    check("2 attempt 2 -> entry 2", (calls, route.position), (["b2"], 2))
    check("2 attempt_entry", meta.get("attempt_entry"),
          {"attempt": 2, "aimed_position": 2, "position": 2})
    check("2 no fallback_from", "fallback_from" in meta, False)

    route, calls = run(["a1", "b2", "c3"], attempt=3)
    check("3 attempt 3 -> entry 3", (calls, route.position), (["c3"], 3))

    route, calls = run(["a1", "b2", "c3"], attempt=5)
    check("4 clamped to last", (calls, route.position), (["c3"], 3))

    route, calls = run(["a1"], attempt=2)
    check("5 single entry unchanged", (calls, route.position), (["a1"], 1))
    check("5 no fallback_from", "fallback_from" in routing.route_meta(route), False)

    route, calls = run(["typo*", "a1", "b2"], attempt=2)
    check("6 config skip not counted", (calls, route.position), (["b2"], 3))

    route, calls = run(["a1", "dead2", "c3"], attempt=2)
    check("7 failure continues forward", (calls, route.position), (["dead2", "c3"], 3))
    check("7 fallback_from", "fallback_from" in routing.route_meta(route), True)

    route, calls = run(["a1", "b2"], attempt=2, unavailable={"b2"})
    check("8 aimed unavailable -> back to a1", (calls, route.position), (["a1"], 1))

    pool = make_pool(["a1", "b2"])
    with routing.retry_attempt(2):
        status, b = routing.resolve_spec("photo", "a1", pool=pool)
    check("9 explicit pick unaffected", (status, b.name if b else None), ("ok", "a1"))
    check("10 context restored", routing.current_attempt(), 1)

    pool = make_pool(["a1", "b2", "c3"])
    check("11 overview retry entry", routing.explain_occasion("photo", pool=pool).get("retry_entry"),
          {"position": 2, "spec": "b2"})
    pool = make_pool(["a1"])
    check("11 overview single", routing.explain_occasion("photo", pool=pool).get("retry_entry"),
          {"position": 1, "spec": "a1"})

    check("12 cloud never asked", "cloud" in ALL_CALLS, False)



def section_overflow():
    RULES = []
    routing._rules = lambda _: list(RULES)
    routing._character_spec = lambda *_: ""
    POOLS = []
    LAST_CALLS = []

    def run(rules, *, names=None, accepts=("cloud1",), room=True, cool=False,
            threshold=90, helper=None, video=False):
        RULES[:] = rules
        backends = [Fake(n, env_prefix="FAKE_OVERFLOW_") for n in (names or rules or ["local1"])]
        for b in backends:
            b.accepts_overflow = b.name in accepts
            if video:
                b.MEDIA_TYPE = "video"
            if cool and b.name == "cloud1":
                b.mark_unhealthy("offline")
        pool = BackendPool(backends)
        POOLS.append(pool)
        calls, watches, picks = [], [], []
        LAST_CALLS.clear()
        def render(b):
            calls.append(b.name)
            LAST_CALLS.append(b.name)
            w = OVERFLOW_WATCH.get()
            watches.append(w.backend_name if w else None)
            if helper:
                raise helper
            if b.name.startswith("dead"):
                def fail(_):
                    raise RuntimeError("HTTP 500")
                return pool.run_on_backend(b, op=fail)[0]
            if w and w.backend_name == b.name:
                target = w.pick()
                picks.append(target.backend.name if target else None)
                if target:
                    raise ChannelOverflow(b.name, 5.0, target)
            return [b"img"]
        with patch("app.imagegen.base.image_overflow_after_seconds", return_value=threshold):
            out, route = routing.run_routed("video" if video else "photo", render,
                                           pool=pool, channel_room=lambda _: room)
        check("watch reset", OVERFLOW_WATCH.get(), None)
        check("result", out, [b"img"])
        return calls, watches, picks, routing.route_meta(route), pool

    assert callable(routing.overflow_target)
    c, w, p, m, pool = run(["local1", "cloud1"])
    check("R1 calls", c, ["local1", "cloud1"])
    check("R1 overflow", m.get("overflow_from"), {"backend": "local1", "waited_s": 5})
    check("R1 fallback", "fallback_from" in m, False)
    rows = routing.explain_occasion("photo", pool=pool)["chain"]
    check("R13", [r["overflow_targets"] for r in rows], [[], ["cloud1"]])
    for label, kw in [("R2", {"accepts": ()}), ("R3", {"room": False}), ("R4", {"cool": True})]:
        c, w, p, m, _ = run(["local1", "cloud1"], **kw)
        check(label, (c, "overflow_from" in m), (["local1"], False))
    for label, rules, kw in [("R5", ["local1", "cloud1"], {"threshold": 0}), ("R6", [], {})]:
        c, w, *_ = run(rules, **kw)
        check(label, (c, w), (["local1"], [None]))
    c, w, p, m, _ = run(["dead1", "local1", "cloud1"])
    check("R7 calls", c, ["dead1", "local1", "cloud1"])
    check("R7 fallback", m.get("fallback_from"), {"occasion": "photo", "intended_spec": "dead1", "position": 1})
    check("R7 overflow", m.get("overflow_from"), {"backend": "local1", "waited_s": 5})
    c, w, p, m, _ = run(["local*"], names=["local1", "local2"], accepts=("local2",))
    check("R8", (c, "fallback_from" in m, m.get("overflow_from")),
          (["local1", "local2"], False, {"backend": "local1", "waited_s": 5}))
    c, w, p, m, _ = run(["local1", "local2", "local3"], accepts=("local1", "local2", "local3"))
    check("R9", (c, w[-1], m.get("overflow_from")),
          (["local1", "local2", "local3"], None, {"backend": "local1", "waited_s": 10}))
    c, w, p, m, _ = run(["local1", "cloud1"], accepts=("local1", "cloud1"))
    check("R10", (c, p), (["local1", "cloud1"], ["cloud1", None]))
    e = ChannelOverflow("helper", 5.0, "x")
    try:
        run(["local1", "cloud1"], helper=e)
    except ChannelOverflow as got:
        check("R11 identity", got is e, True)
    else:
        check("R11 propagated", False, True)
    check("R11 calls", LAST_CALLS, ["local1"])
    check("R11 reset", OVERFLOW_WATCH.get(), None)
    c, w, *_ = run(["vid1", "vid2"], accepts=("vid2",), video=True)
    check("R12", (c, w), (["vid1"], [None]))
    c, w, p, m, _ = run(["local1", "deadcloud"], accepts=("deadcloud",))
    check("R14", (c, p, "overflow_from" in m, "fallback_from" in m),
          (["local1", "deadcloud", "local1"], ["deadcloud", None], False, False))


section("[1] re-run", section_rerun)
section("[2] retry attempt", section_attempt)
section("[3] overflow", section_overflow)

print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed in section(s) {', '.join(FAILED_SECTIONS)}: {FAILS}")
    sys.exit(1)
print("all checks passed")
