#!/usr/bin/env python3
"""Smoke: app/core/route_limits.py — the shared cap for the three figure polls.

Usage:
    ./.venv/bin/python scripts/smoke_route_limits.py

No world, no server, no HTTP. STORAGE_DIR / INSTANCE_DIR point at temp dirs and
paths.init(<tmp>) runs before any app.routes module is imported (the route
modules are only imported for [5]); "app.server" must not be imported.
Counters are read by patching app.core.hot_path_stats.count.

Expected numbers, derived by hand:

[1] Pool limit 2, five threads call a decorated body that records the number
    of bodies running at once and then blocks on one Event. Two get a slot at
    once, the other three block on the semaphore. While the Event is clear:
    running = 2, max observed = 2, "waited" counted 3 times (5 - 2). After the
    Event is set every body returns: 5 finished, max observed still exactly 2,
    no "overdue" (nobody waits 30 s).
[2] Pool limit 1, the body raises ValueError. The caller gets ValueError, and
    the slot is free again: a second call runs at once (0 "waited"), and the
    semaphore value is back to 1.
[3] Pool limit 2, MAX_WAIT_S patched to 0.05. Two threads hold both slots on an
    Event. A third call waits 0.05 s, then runs anyway without a slot:
    elapsed >= 0.05 s (and < 2 s), it returns its value, counts "waited" 1 and
    "overdue" 1. After all three end the semaphore value is 2 — the overdue
    call took no slot, so it releases none (3 would mean the cap grew).
[4] Pool limit 1, MAX_WAIT_S at its 30 s default. outer() holds the only slot
    and calls inner() of the same pool in the same thread. Re-entrant: inner
    runs at once — the thread finishes within 2 s (a non-re-entrant cap would
    hang 30 s), "waited" 0, and the semaphore value is 1 afterwards.
[5] The decorated real handlers — figure.get_open_steps, figure.get_figure,
    characters.get_character_model3d — carry __wrapped__, their
    inspect.signature equals the undecorated function's, and the FastAPI
    route's dependant lists the same parameter names (path, query, header,
    cookie, body, dependency calls, request param) as a dependant built from
    the undecorated function. Each route is registered exactly once with the
    decorated endpoint.
[6] An async function is refused (TypeError); registering a name twice with
    different limits is refused (ValueError).
"""
import inspect
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="smoke_route_limits_")
os.environ["STORAGE_DIR"] = os.path.join(_tmp, "world")
os.environ["INSTANCE_DIR"] = os.path.join(_tmp, "instance")
os.makedirs(os.environ["STORAGE_DIR"], exist_ok=True)
os.makedirs(os.environ["INSTANCE_DIR"], exist_ok=True)

from app.core import paths  # noqa: E402
paths.init(os.environ["STORAGE_DIR"])

from app.core import hot_path_stats, route_limits  # noqa: E402
from app.core.route_limits import limited  # noqa: E402

failures = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        failures.append(label)


counted = []
_lock = threading.Lock()


def _fake_count(name, key):
    with _lock:
        counted.append((name, key))


hot_path_stats.count = _fake_count


def n(key):
    with _lock:
        return sum(1 for name, k in counted if name == "route_limit" and k == key)


def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


# [1] ------------------------------------------------------------------
print("[1] limit 2, five callers")
state = {"now": 0, "max": 0, "done": 0}
gate = threading.Event()


@limited("t1", 2)
def body1():
    with _lock:
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
    gate.wait(10)
    with _lock:
        state["now"] -= 1
        state["done"] += 1


threads = [threading.Thread(target=body1) for _ in range(5)]
for t in threads:
    t.start()
wait_until(lambda: n("t1:waited") == 3 and state["now"] == 2)
time.sleep(0.1)   # give a wrongly admitted third caller time to show up
check("[1] running while held", state["now"], 2)
check("[1] waited", n("t1:waited"), 3)
gate.set()
for t in threads:
    t.join(10)
check("[1] finished", state["done"], 5)
check("[1] max concurrency", state["max"], 2)
check("[1] overdue", n("t1:overdue"), 0)

# [2] ------------------------------------------------------------------
print("[2] an exception frees the slot")


@limited("t2", 1)
def body2(fail):
    if fail:
        raise ValueError("boom")
    return "ran"


try:
    body2(True)
    check("[2] raised", None, "ValueError")
except ValueError:
    check("[2] raised", "ValueError", "ValueError")
check("[2] next call", body2(False), "ran")
check("[2] waited", n("t2:waited"), 0)
check("[2] semaphore value", route_limits._pools["t2"]._value, 1)

# [3] ------------------------------------------------------------------
print("[3] overdue: runs anyway after MAX_WAIT_S")
route_limits.MAX_WAIT_S = 0.05
gate3 = threading.Event()
held = {"n": 0}


@limited("t3", 2)
def body3(block):
    if block:
        with _lock:
            held["n"] += 1
        gate3.wait(10)
    return "late"


holders = [threading.Thread(target=body3, args=(True,)) for _ in range(2)]
for t in holders:
    t.start()
wait_until(lambda: held["n"] == 2)
t0 = time.monotonic()
got = body3(False)
elapsed = time.monotonic() - t0
check("[3] value", got, "late")
check("[3] waited >= 0.05 s", elapsed >= 0.05, True)
check("[3] waited < 2 s", elapsed < 2.0, True)
check("[3] waited", n("t3:waited"), 1)
check("[3] overdue", n("t3:overdue"), 1)
gate3.set()
for t in holders:
    t.join(10)
check("[3] semaphore value", route_limits._pools["t3"]._value, 2)
route_limits.MAX_WAIT_S = 30.0

# [4] ------------------------------------------------------------------
print("[4] nested call in the same thread")


@limited("t4", 1)
def inner():
    return "inner"


@limited("t4", 1)
def outer():
    return "outer+" + inner()


result4 = {}
t4 = threading.Thread(target=lambda: result4.setdefault("v", outer()), daemon=True)
t0 = time.monotonic()
t4.start()
t4.join(2.0)
check("[4] finished within 2 s", not t4.is_alive(), True)
check("[4] value", result4.get("v"), "outer+inner")
check("[4] waited", n("t4:waited"), 0)
check("[4] semaphore value", route_limits._pools["t4"]._value, 1)

# [5] ------------------------------------------------------------------
print("[5] real handlers keep signature and dependant")
from fastapi.dependencies.utils import get_dependant  # noqa: E402
from app.routes import characters as characters_routes  # noqa: E402
from app.routes import figure as figure_routes  # noqa: E402
check("[5] app.server not imported", "app.server" in sys.modules, False)


def dep_names(d):
    return {
        "path": [p.name for p in d.path_params],
        "query": [p.name for p in d.query_params],
        "header": [p.name for p in d.header_params],
        "cookie": [p.name for p in d.cookie_params],
        "body": [p.name for p in d.body_params],
        "deps": [getattr(x.call, "__qualname__", repr(x.call)) for x in d.dependencies],
        "request": d.request_param_name,
    }


for module, path, fn_name in ((figure_routes, "/characters/open-steps", "get_open_steps"),
                              (figure_routes, "/characters/{character_name}/figure", "get_figure"),
                              (characters_routes, "/characters/{character_name}/model3d",
                               "get_character_model3d")):
    fn = getattr(module, fn_name)
    check(f"[5] {fn_name} decorated", hasattr(fn, "__wrapped__"), True)
    raw = fn.__wrapped__
    check(f"[5] {fn_name} signature", inspect.signature(fn), inspect.signature(raw))
    routes = [r for r in module.router.routes
              if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", set())]
    check(f"[5] {fn_name} one GET route", len(routes), 1)
    if routes:
        route = routes[0]
        check(f"[5] {fn_name} endpoint is the decorated one", route.endpoint is fn, True)
        check(f"[5] {fn_name} dependant", dep_names(route.dependant),
              dep_names(get_dependant(path=route.path_format, call=raw)))
        print(f"       {fn_name}: {dep_names(route.dependant)}")

# [6] ------------------------------------------------------------------
print("[6] refusals")
try:
    @limited("t6", 1)
    async def body6():
        return None
    check("[6] async refused", None, "TypeError")
except TypeError:
    check("[6] async refused", "TypeError", "TypeError")
try:
    limited("t6", 2)
    check("[6] second limit refused", None, "ValueError")
except ValueError:
    check("[6] second limit refused", "ValueError", "ValueError")

print()
if failures:
    print(f"FAILED — {len(failures)}: {', '.join(failures)}")
    sys.exit(1)
print("all ok")
