#!/usr/bin/env python3
"""Smoke: gate retries run on the NEXT chain entry (routing.retry_attempt).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_attempt.py

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
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scratch(prefix):
    p = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, p, ignore_errors=True)
    return p


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("routing-attempt-clips-")
from app.core import paths  # noqa: E402
paths.init(_scratch("routing-attempt-storage-"))

from app.imagegen import routing  # noqa: E402
from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402

FAILS = []
ALL_CALLS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name, cost=1, available=True):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_ATTEMPT_")
        self.category = "img2img"
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = available

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        raise AssertionError("no real generate in this smoke")


RULES = {}
routing._rules = lambda occasion: list(RULES.get(occasion, []))
routing._character_spec = lambda occ_def, character, overrides=None: ""
# Overflow off: no provider manager, no channel lookups.
import app.imagegen.base as _base  # noqa: E402
_base.image_overflow_after_seconds = lambda: 0


def make_pool(rules, unavailable=()):
    names = sorted({r for r in rules if "*" not in r} | {"cloud"})
    pool = BackendPool([Fake(n, cost=9 if n == "cloud" else 1,
                             available=n not in unavailable) for n in names])
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

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
