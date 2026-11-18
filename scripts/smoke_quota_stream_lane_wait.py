#!/usr/bin/env python3
"""A streaming call keeps its provider-quota reservation while it waits for a lane.

Usage:
    ./.venv/bin/python scripts/smoke_quota_stream_lane_wait.py

Follow-up of review 11#4. Streaming callers (thoughts, act engine, story
player, world-dev) resolve their instance with ``resolve_llm`` — which books
a quota slot (``_quota_reservation``) — and then wait in
``ProviderManager.register_chat_active`` for a cache lane before they stream.
The send (``llm_client._quota_attempt`` -> ``quota.send(reservation)``) comes
only after that wait. A reservation used to expire one window after booking
whatever its call was doing, so a lane wait longer than the window gave the
slot to the next fresh ``resolve_llm`` and the stream then found the window
full at its send (``QuotaUnavailable``). ``register_chat_active`` now HOLDS
the reservation while it waits; a granted lane re-books it at the grant
(``unhold(renew=True)``) because the send follows only after the return, any
other exit lets it expire by its original age.

Runs without the server, a world, a DB or a network. The quota runs on a fake
SYSTEM clock (``now``); a lane manager with one lane per pool and no
affinity/hold rules stands in for the configured one. Thread waits use a
deadline that only bounds how long the check waits for a thread; the deadline
decides no expectation.

EXPECTATIONS, DERIVED BY HAND (capacity 1, window 60 s, one lane per pool)

[1] Wait longer than the window, then send. The lane of pool P/m is taken
    by a blocker. The instance books R at t=0 and registers (task "thought",
    no overflow); it waits for the lane, R is held. At t=61 R is older than
    the window but held: used=1, a later arrival's reserve() is None. The
    blocker leaves, the registration is granted at t=61: R is re-booked at
    61 and no longer held. The stream's send(R) at t=61 succeeds; afterwards
    used=1 (that send) and the next slot frees at 61+60=121 (reserve() None
    at 120.9, a token at 121).
    Old code: R expired at t=60, so the later arrival's reserve() at t=61
    got the slot, and send(R) raised QuotaUnavailable (window full, R no
    longer booked). Old code also fails [2] (used=0 at 329.9: R expired at
    260) and the "held" checks of [3]/[4].

[2] Granted, but the send never comes (leak bound). R booked at t=200,
    lane wait until t=270, grant. R is re-booked at 270 and expires one
    window later: used=1 at 329.9, used=0 at 330.

[3] Cancelled while waiting. R booked at t=400, the caller cancels at t=430
    while the lane is still taken: LaneWaitCancelled, R not held. R keeps
    its ORIGINAL age: used=1 at 459.9, used=0 at 460 (400+60).
    Same with an old booking: R2 booked at t=500, cancelled at t=600 (100 s
    of waiting) -> no renewal, so R2 is already past its window: used=0
    right after the cancel.

[4] Overflow hop. Instance on provider A (reservation RA at t=1000), the
    first lane round on A expires (LaneWaitExpired) and overflow_target
    hands an alternative on provider C with reservation RC (booked t=1000).
    During the A round RA is held. During the C round RA is gone from A's
    quota (released on the hop: used on A = 0) and RC is held; the clock
    moves to t=1100 in that round (100 s of waiting on C) and the round is
    granted. After the return used on C is 1 (RC, re-booked at the grant:
    stamp 1100) and nothing is held on either quota.
    Old code: RC was never held and its booking at t=1000 had expired at
    t=1060, so after the return used on C was 0.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import atexit
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def scratch(prefix):
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


os.environ["ANIMATION_CLIPS_DIR"] = scratch("quota-stream-clips-")
from app.core import paths  # noqa: E402

paths.init(scratch("quota-stream-storage-"))

from app.core import llm_lanes as lanes  # noqa: E402
from app.core import llm_router as router  # noqa: E402
from app.core import provider_manager as pm_mod  # noqa: E402
from app.core import provider_queue as pq_mod  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_quota import ProviderQuota, QuotaUnavailable  # noqa: E402
from app.utils import llm_stats  # noqa: E402

pq_mod._attach_duration_estimate = lambda task: None
llm_stats.record_call = lambda *a, **kw: None

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


now = [0.0]


def clock():
    return now[0]


RULES = lambda: lanes.LaneRules(affinity_wait=0, conversation_hold=0,  # noqa: E731
                                overflow_after=0)
MANAGER = lanes.LaneManager(lane_count=lambda key: 1, rules=RULES)
patch.object(lanes, "_manager", MANAGER).start()
patch.object(lanes, "configured_lane_rules", RULES).start()

PM = pm_mod.ProviderManager()


def add_provider(name):
    provider = Provider(name=name, type="openai", api_base="http://stub",
                        api_key="", max_concurrent=1, timeout=30)
    provider.available = True
    provider.quota = ProviderQuota(1, 60, clock=clock)
    queue = pq_mod.ProviderQueue(provider, queue_name=name, max_concurrent=1,
                                 chat_pause_enabled=False, serialize_group="")
    PM.providers[name] = provider
    PM.channels[name] = PM._queues[name] = queue
    return provider


P = add_provider("P")
QUOTA = P.quota


def instance_on(provider, model, at):
    now[0] = at
    inst = router.LLMInstance(provider.name, model, tasks=["thought"])
    inst._provider = provider
    inst._quota_reservation = provider.quota.reserve()
    return inst


def register_in_thread(inst, cancel=None):
    box = {}

    def run():
        try:
            box["task_id"] = PM.register_chat_active(inst, "demo", task_type="thought",
                                                     cancel=cancel)
        except Exception as exc:  # inspected below
            box["error"] = exc
        box["done"] = True

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def block_lane():
    return MANAGER.acquire_lane("P/m", "chat:blocker", lanes.Priority.CHAT, timeout=0)


# ── [1] wait longer than the window, then send ──────────────────────────────
print("[1] a lane wait longer than the window keeps the slot for the send")
blocker = block_lane()
inst = instance_on(P, "m", 0.0)
r = inst._quota_reservation
check("R booked at t=0", r is not None, True)
thread, box = register_in_thread(inst)
check("R is held while the call waits for its lane",
      wait_until(lambda: r in QUOTA._held), True)
now[0] = 61.0
check("used at t=61", QUOTA.used, 1)
late = QUOTA.reserve()
check("later arrival at t=61 gets no slot", late, None)
blocker.release()
thread.join(timeout=10)
check("registration granted", "task_id" in box, True)
check("R no longer held after the grant", r in QUOTA._held, False)
try:
    QUOTA.send(r)
    sent = True
except QuotaUnavailable:
    sent = False
check("stream's send(R) at t=61 succeeds", sent, True)
if late is not None:
    QUOTA.release(late)
check("used after the send", QUOTA.used, 1)
if "task_id" in box:
    PM.register_chat_done(box["task_id"])
now[0] = 120.9
check("fresh reserve at t=120.9", QUOTA.reserve(), None)
now[0] = 121.0
fresh = QUOTA.reserve()
check("fresh reserve at t=121", fresh is not None, True)
QUOTA.release(fresh)

# ── [2] granted, never sent: one window from the grant ─────────────────────
print("\n[2] a granted reservation that never sends expires a window after the grant")
blocker = block_lane()
inst = instance_on(P, "m", 200.0)
r = inst._quota_reservation
thread, box = register_in_thread(inst)
check("R held while waiting", wait_until(lambda: r in QUOTA._held), True)
now[0] = 270.0
blocker.release()
thread.join(timeout=10)
check("registration granted", "task_id" in box, True)
if "task_id" in box:
    PM.register_chat_done(box["task_id"])
now[0] = 329.9
check("used at t=329.9", QUOTA.used, 1)
now[0] = 330.0
check("used at t=330", QUOTA.used, 0)

# ── [3] cancelled while waiting: original age ─────────────────────────────
print("\n[3] a cancelled wait gives the hold back without renewal")
blocker = block_lane()
inst = instance_on(P, "m", 400.0)
r = inst._quota_reservation
cancel = threading.Event()
thread, box = register_in_thread(inst, cancel)
check("R held while waiting", wait_until(lambda: r in QUOTA._held), True)
now[0] = 430.0
cancel.set()
thread.join(timeout=10)
check("registration cancelled",
      type(box.get("error")).__name__, "LaneWaitCancelled")
check("R not held after the cancel", r in QUOTA._held, False)
now[0] = 459.9
check("used at t=459.9", QUOTA.used, 1)
now[0] = 460.0
check("used at t=460", QUOTA.used, 0)

inst = instance_on(P, "m", 500.0)
r2 = inst._quota_reservation
cancel = threading.Event()
thread, box = register_in_thread(inst, cancel)
check("R2 held while waiting", wait_until(lambda: r2 in QUOTA._held), True)
now[0] = 600.0
check("used at t=600 while still held", QUOTA.used, 1)
cancel.set()
thread.join(timeout=10)
check("registration cancelled",
      type(box.get("error")).__name__, "LaneWaitCancelled")
check("used right after the cancel at t=600", QUOTA.used, 0)
blocker.release()

# ── [4] overflow hop holds the new reservation ─────────────────────────────
print("\n[4] an overflow hop releases the old slot and holds the new one")
A = add_provider("A")
C = add_provider("C")
inst = instance_on(A, "a", 1000.0)
alt = instance_on(C, "c", 1000.0)
ra, rc = inst._quota_reservation, alt._quota_reservation
seen = {}


def round_on_a(*args, **kwargs):
    seen["ra_held_on_a"] = ra in A.quota._held
    raise lanes.LaneWaitExpired(kwargs["arrived"])


def round_on_c(*args, **kwargs):
    seen["a_used_on_c_round"] = A.quota.used
    seen["rc_held_on_c"] = rc in C.quota._held
    now[0] = 1100.0
    return "moved-id"


hop_rules = lambda: lanes.LaneRules(affinity_wait=0, conversation_hold=0,  # noqa: E731
                                    overflow_after=1)
with patch.object(lanes, "configured_lane_rules", hop_rules), \
        patch.object(PM._queues["A"], "register_chat_active", side_effect=round_on_a), \
        patch.object(PM._queues["C"], "register_chat_active", side_effect=round_on_c), \
        patch.object(router, "overflow_target", return_value=alt):
    result = PM.register_chat_active(inst, "demo", task_type="thought", overflow=True)
check("registered on the alternative", result, ("moved-id", alt))
check("RA held during the A round", seen.get("ra_held_on_a"), True)
check("A's quota empty during the C round (RA released)", seen.get("a_used_on_c_round"), 0)
check("RC held during the C round", seen.get("rc_held_on_c"), True)
check("C used at t=1100 (RC still booked)", C.quota.used, 1)
check("RC booked at the grant (t=1100)", C.quota._reservations.get(rc), 1100.0)
check("nothing held on A", len(A.quota._held), 0)
check("nothing held on C", len(C.quota._held), 0)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("PASS: a streaming call keeps its reservation while it waits for a lane")
