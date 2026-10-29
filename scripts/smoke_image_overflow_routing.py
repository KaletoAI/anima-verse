#!/usr/bin/env python3
"""Task 3 routing smoke.
Usage: ./.venv/bin/python scripts/smoke_image_overflow_routing.py

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


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("routing-overflow-clips-")
from app.core import paths  # noqa: E402
paths.init(_scratch("routing-overflow-storage-"))

from app.core.provider_manager import NoBackendChannelError  # noqa: E402
from app.core.provider_queue import TooManyJobsError  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.imagegen.base import (BackendBusyError, BackendFailedError,  # noqa: E402
                               GpuTaskCancelled, GpuTaskTimeout, ImageBackend,
                               MediaGenerationDisabled, ChannelOverflow, OVERFLOW_WATCH)
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
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_OVERFLOW_")
        self.category = "img2img"
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = True

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"img"]



from unittest.mock import patch
RULES = []
routing._rules = lambda _: list(RULES)
routing._character_spec = lambda *_: ""
POOLS = []
LAST_CALLS = []

def run(rules, *, names=None, accepts=("cloud1",), room=True, cool=False,
        threshold=90, helper=None, video=False):
    RULES[:] = rules
    backends = [Fake(n) for n in (names or rules or ["local1"])]
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

routing.overflow_target
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
if FAILS:
    sys.exit(1)
print("all checks passed")
