#!/usr/bin/env python3
"""Smoke: the re-run of the image routing (routing.run_routed).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_reentry.py

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


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("routing-reentry-clips-")
from app.core import paths  # noqa: E402
paths.init(_scratch("routing-reentry-storage-"))

from app.core.provider_manager import NoBackendChannelError  # noqa: E402
from app.core.provider_queue import TooManyJobsError  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.imagegen.base import (BackendBusyError, BackendFailedError,  # noqa: E402
                               GpuTaskCancelled, GpuTaskTimeout, ImageBackend,
                               MediaGenerationDisabled)
from app.imagegen.selection import BackendPool  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name, cost=1):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_REENTRY_")
        self.category = "img2img"
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = True

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"img"]


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
routing._character_switches = lambda character: {}
CHAR_SPEC = {"value": ""}
routing._character_spec = lambda occ_def, character: (
    CHAR_SPEC["value"] if character and occ_def.get("character_scoped") else "")


POOLS = []


def run(rules, names=None, nested_failure=None):
    """``nested_failure``: a backend name — render raises a BackendFailedError
    for THAT backend (a failing helper step) instead of rendering."""
    names = names or sorted({n for n in rules} | {"cloud"})
    backends = [Fake(n, cost=9 if n == "cloud" else 1) for n in names]
    pool = BackendPool(backends, agent_instances_provider=lambda n: {})
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

print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("all checks passed")
