#!/usr/bin/env python3
"""A queued call keeps its provider-quota reservation until it leaves the queue.

Usage:
    ./.venv/bin/python scripts/smoke_quota_queued_reservation.py

Review 11#4: ``resolve_llm`` books a quota slot for the call it picks, and the
call then waits in the provider queue for a cache lane. A reservation used to
expire after one quota window whatever its holder was doing, so a call that
waited longer than the window lost its slot while still queued. The next
fresh ``resolve_llm`` took the freed slot, and the old call found the window
full at dequeue (``_acquire_lane`` -> ``wait_for_send``). Every slot that came
free went to a newer arrival first. A reservation is now HELD while its call
sits in ``ProviderQueue.submit`` and expires by age only once the call is out
of the queue without sending.

Runs without the server, a world, a DB or a network. The quota runs on a
fake SYSTEM clock (``now``), so nothing waits for a real window. The queue
part uses a real ``ProviderQueue`` with a stub LLM whose ``invoke`` does what
``llm_client._quota_attempt`` does: ``quota.send(reservation)`` before the
"HTTP request". Thread waits use a deadline that only bounds how long the
check waits for a thread. The deadline decides no expectation.

EXPECTATIONS, DERIVED BY HAND (capacity C, window 60 s)

[1] Pure quota, C=1. Reservation R at t=0, held. At t=61 R is older than the
    window, but held reservations do not expire by age. So used=1 and a fresh
    reserve() gets None. wait_seconds() is one whole window (60): a held slot
    turns into a send no earlier than now, and that send frees 60 s later.
    send(R) at t=61 consumes R and books one send. used=1, held set empty.
    The next slot frees at 61+60=121, so reserve() is None at 120 and a
    token at 121.
    Old code: R expired at t=60, so at t=61 used=0 and the fresh reserve()
    succeeded. The held call then found the window full.

[2] Pure quota, C=2. Held R from t=0, plain send at t=100. used=2 and
    wait_seconds()=60 (the send at 100 frees at 160; the held slot frees no
    earlier than 100+60=160). reserve() is None at 159.9 and a token at 160.

[3] Leak bound. Reservation S at t=200, held, then unhold (the call left the
    queue without sending). S is an ordinary reservation again: used=1 at
    259.9 and 0 at 260 (200+60).

[4] Through the queue. C=1, one lane on pool P/model-a, held by scaffolding
    under A's own cache key (bg:Kira). Task A (consolidation, Kira) reserves
    at t=0 and is submitted. It cannot get a lane, so it waits in the queue.
    The clock jumps to t=61. A later arrival's reserve() must get None
    (A still holds the only slot). Then the scaffolding lane is released. A
    runs, and its send(R) succeeds at t=61. The caller gets "ok". Afterwards
    used=1 (A's send), nothing is held, and a fresh reserve() is None until
    121.
    Old code: the later arrival's reserve() succeeded at t=61. A's dequeue
    check then saw a full window, so A was deferred for the rest of the
    frozen clock and never returned within the deadline.

[5] Through the queue, failure without a send. C=1. Task F reserves at t=300
    and its invoke raises before sending. submit() re-raises. F's token is
    not held any more: used=1 at 359.9 (an ordinary reservation still in its
    window) and 0 at 360.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def scratch(prefix):
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


os.environ["ANIMATION_CLIPS_DIR"] = scratch("quota-hold-clips-")
from app.core import paths  # noqa: E402

paths.init(scratch("quota-hold-storage-"))

from app.core import provider_queue as pq_mod  # noqa: E402
from app.core.llm_lanes import (cache_key_for, get_lane_manager,  # noqa: E402
                                pool_key_for)
from app.core.llm_queue import Priority  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.core.provider_quota import ProviderQuota, QuotaUnavailable  # noqa: E402
from app.utils import llm_logger, llm_stats  # noqa: E402

llm_logger.LOG_DIR = Path(scratch("quota-hold-logs-"))
llm_logger.LOG_FILE = llm_logger.LOG_DIR / "llm_calls.jsonl"
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


# ── [1] held reservation does not expire by age (C=1) ──────────────────────
print("[1] a held reservation survives the window")
q = ProviderQuota(1, 60, clock=clock)
now[0] = 0.0
r = q.reserve()
check("R booked at t=0", r is not None, True)
check("hold(R) accepted", q.hold(r), True)
now[0] = 61.0
check("used at t=61", q.used, 1)
check("fresh reserve at t=61", q.reserve(), None)
check("wait_seconds at t=61", q.wait_seconds(), 60.0)
check("held call may still send (wait_for_send)", q.wait_for_send(r), 0.0)
q.send(r)
check("used after send(R)", q.used, 1)
check("nothing held after send", len(q._held), 0)
now[0] = 120.0
check("fresh reserve at t=120", q.reserve(), None)
now[0] = 121.0
check("fresh reserve at t=121", q.reserve() is not None, True)

# ── [2] the free time counts the held slot as 'not before now + window' ─────
print("\n[2] wait_seconds with a held slot and a send (C=2)")
q = ProviderQuota(2, 60, clock=clock)
now[0] = 0.0
r = q.reserve()
q.hold(r)
now[0] = 100.0
q.send()
check("used at t=100", q.used, 2)
check("wait_seconds at t=100", q.wait_seconds(), 60.0)
now[0] = 159.9
check("reserve at t=159.9", q.reserve(), None)
now[0] = 160.0
check("reserve at t=160", q.reserve() is not None, True)

# ── [3] unhold turns it back into an expiring reservation ──────────────────
print("\n[3] unhold restores the age limit")
q = ProviderQuota(1, 60, clock=clock)
now[0] = 200.0
s = q.reserve()
q.hold(s)
q.unhold(s)
now[0] = 259.9
check("used at t=259.9", q.used, 1)
now[0] = 260.0
check("used at t=260", q.used, 0)


# ── [4]/[5] through a real provider queue ──────────────────────────────────
class StubResponse:
    content = "ok"
    finish_reason = "stop"


class QuotaStubLLM:
    """Sends like llm_client._quota_attempt: one quota.send(reservation)."""

    def __init__(self, quota, reservation, fail=False):
        self.model = "model-a"
        self.model_name = "model-a"
        self.max_tokens = 0
        self.openai_api_base = "http://stub"
        self.provider_quota = quota
        self.quota_reservation = reservation
        self.fail = fail
        self.sent = None

    def invoke(self, messages):
        if self.fail:
            raise RuntimeError("broken before the request")
        try:
            self.provider_quota.send(self.quota_reservation)
            self.sent = True
        except QuotaUnavailable:
            self.sent = False
            raise
        return StubResponse()


quota = ProviderQuota(1, 60, clock=clock)
provider = Provider(name="P", type="openai", api_base="http://stub",
                    api_key="", max_concurrent=1, timeout=30)
provider.available = True
provider.quota = quota
QUEUE = ProviderQueue(provider, queue_name="P", max_concurrent=1,
                      chat_pause_enabled=False, serialize_group="")
LANES = get_lane_manager()
POOL = pool_key_for("P", "model-a")
MESSAGES = [{"role": "user", "content": "u"}]

print("\n[4] a call that waits longer than the window keeps its slot")
blocker = LANES.acquire_lane(POOL, cache_key_for("consolidation", "Kira"),
                             Priority.CHAT, timeout=0)
now[0] = 0.0
token_a = quota.reserve()
llm_a = QuotaStubLLM(quota, token_a)
box = {}


def run_a():
    try:
        box["result"] = QUEUE.submit("consolidation", Priority.LOW, llm_a,
                                     MESSAGES, agent_name="Kira")
    except Exception as e:  # a failed check, reported below
        box["error"] = repr(e)
    box["done"] = True


thread_a = threading.Thread(target=run_a, daemon=True)
thread_a.start()
check("A is queued and holds its reservation",
      wait_until(lambda: token_a in quota._held), True)
now[0] = 61.0
late = quota.reserve()
check("later arrival at t=61 gets no slot", late, None)
if late is not None:
    quota.release(late)
blocker.release()
thread_a.join(timeout=10)
check("A finished", box.get("done"), True)
check("A's answer", getattr(box.get("result"), "content", box.get("error")), "ok")
check("A sent on its own reservation", llm_a.sent, True)
check("used after A (one send)", quota.used, 1)
check("nothing held after A", len(quota._held), 0)
now[0] = 120.0
check("fresh reserve at t=120", quota.reserve(), None)
now[0] = 121.0
fresh = quota.reserve()
check("fresh reserve at t=121", fresh is not None, True)
quota.release(fresh)

print("\n[5] a call that fails before sending gives its hold back")
now[0] = 300.0
token_f = quota.reserve()
llm_f = QuotaStubLLM(quota, token_f, fail=True)
try:
    QUEUE.submit("consolidation", Priority.LOW, llm_f, MESSAGES, agent_name="Kira")
    raised = False
except Exception:
    raised = True
check("submit re-raised the failure", raised, True)
check("F is not held any more", token_f in quota._held, False)
now[0] = 359.9
check("used at t=359.9", quota.used, 1)
now[0] = 360.0
check("used at t=360", quota.used, 0)
check("pool lane free at the end",
      wait_until(lambda: LANES.free_lanes(POOL) == 1), True)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("PASS: queued reservations are held until the call leaves the queue")
