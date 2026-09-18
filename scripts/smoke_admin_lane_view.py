#!/usr/bin/env python3
"""Admin lane view: what /admin/agent-loop shows about the cache lanes.

Usage:
    ./.venv/bin/python scripts/smoke_admin_lane_view.py

Runs WITHOUT the server, without a world DB and without touching any world:
``paths.init()`` points at a fresh temp directory before the first app import,
the routing config is set in memory (``config._CONFIG``, never written), and
the lane manager is built by hand with a STEPPED clock — so every expected
number below is a calculation from the rules and the clock, not a recording of
what the code currently prints.

Covers phase 4, item 10 of development_instructions/plan-cache-lanes.md: the
payload behind the table (``llm_lanes.admin_lane_view``) and the cache ring
that feeds its ⚡ column (``lane_cache_stats``). Item 11 — the lane count on
LLM Routing › LLMs — is checked in scripts/smoke_admin_pages.py, where the
rest of the admin page structure lives.

WHAT THE TABLE CLAIMS, AND WHERE EACH NUMBER COMES FROM

    column            source                        checked in
    lane / hot key    Lane.lane_id / Lane.hot_key   [2]
    running / for     Lane.label, clock - stamp     [2] [3]
    lanes / free      len(pool.lanes), not busy     [2] [3]
    lanes configured  llm_routing.max_concurrent    [1]
    ⚡ cache share    lane_cache_stats ring         [5]
    waiting + reason  pool.waiting + the rule that  [4]
                      said no

None of them is a constant in the view: every section changes the state and
demands the changed number back.

[1] THE CONFIG SIDE, before a single call ran. Two enabled entries name the
    same provider+model (one per sampling profile) — they share ONE pool and
    the HIGHEST lane count wins, so 2 and 3 make 3, the same fold
    ``configured_lane_count`` does. A third entry is its own pool with the
    default of 1 lane. Nothing has run, so the view says so
    (``started: false``) instead of printing zeros that read like a
    measurement, and the ⚡ column says "no calls yet". A DISABLED entry
    routes nothing and therefore has no lanes: it is not a pool.

[2] THE LIVE SIDE. A manager with 3 lanes and a clock the check steps:

      t=10  acquire chat:Kira    (label chat_stream) -> lane 0
      t=12  acquire thought:Ida  (label thought)     -> lane 1
      t=15  snapshot

    Expected at t=15: lane_count 3, busy 2, free 1. Lane 0 runs chat_stream
    for 15-10 = 5 s, lane 1 runs thought for 15-12 = 3 s, lane 2 has never
    been used (no hot key, no age at all). A busy lane reports ``running_s``
    and no ``idle_s`` — the stamp is the same field, but "running for 5 s" and
    "idle for 5 s" are opposite readings and the view must not confuse them.

[3] THE SAME NUMBERS AFTER A CHANGE. Releasing lane 0 at t=16 and reading at
    t=20: busy 1, free 2, lane 0 now idle for 20-16 = 4 s with ``running_s``
    None and its hot key kept (chat:Kira — that is what makes it the lane
    Kira's next turn prefers). A view that printed constants would still say
    5 s and 2 busy here.

[4] THE WAITING QUEUE AND ITS REASON. Every reason is the answer of the code
    that decides (``_assignable_lane_reason`` / ``_next_in_line``); the view
    derives none of them a second time.

      a) all_busy          1 lane, busy; a parked call has nowhere to go.
      b) affinity_wait     2 lanes, lane 0 busy, lane 1 free with the foreign
                           key bg:other. R3 holds a LOW call off a foreign
                           lane for affinity_wait_seconds = 5: at 2 s after
                           its arrival it still waits, and the view names R3.
      c) conversation_hold 2 lanes, lane 0 busy, lane 1 free and last used by
                           chat:Kira 1 s ago. R4 keeps a LOW call off a fresh
                           conversation lane while a busy lane could still
                           come free — which is exactly this state.
      d) outranked/starting are read on a hand-built waiting list, because a
                           pass that CAN be won is won in the same instant: a
                           waiter that has a lane assigned leaves the list
                           before any HTTP request could see it. Two waiters,
                           one free lane: CHAT is the winner of the pass
                           ("starting"), LOW is "outranked" — and the
                           R2 ageing is visible as LOW → NORMAL once it has
                           waited longer than wait_upgrade_seconds.

[5] THE ⚡ COLUMN. "Not reported" is not 0 %:

      no call at all                      -> pct None, "no calls yet"
      2 calls, provider reported nothing  -> pct None, "cache not reported (2 calls)"
      1 call, prompt 1000, cached 0       -> pct 0.0, "0 % cached (last 1 of 1 calls)"
      + 1 call, prompt 1000, cached 800   -> pct 40.0 (800 of 2000 reported tokens)
      + 1 call with no figure             -> pct 40.0 still: an unreported call
                                             is left OUT of both sums instead
                                             of counted as zero, and only the
                                             sample count grows.

    The three texts must differ from each other — that is what the admin reads.
    A failed call and a call without prompt tokens are not samples at all.

[6] A POOL THE CONFIG DOES NOT KNOW (a renamed entry, or the unresolved
    ``?/model`` pool) is still listed, marked ``configured: false`` and sorted
    behind the configured ones — hiding it would hide exactly the lanes nobody
    expects to exist.
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
    """A temp directory that lives exactly as long as this run."""
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


# Storage and clip library are redirected BEFORE the first app import: without
# it the default world is worlds/demo, which is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = scratch("lane-view-clips-")

from app.core import paths  # noqa: E402

paths.init(scratch("lane-view-storage-"))

from app.core import config, lane_cache_stats  # noqa: E402
from app.core.llm_lanes import (  # noqa: E402
    LaneManager, LaneRules, LaneTimeout, _Waiter, admin_lane_view,
)
from app.core.llm_queue import Priority  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


class Clock:
    """A clock the check steps by hand — nothing here ever sleeps for a rule."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = float(t)


class Rules:
    """The three global lane timings, under the check's control."""

    def __init__(self, affinity_wait=0.0, conversation_hold=0.0,
                 wait_upgrade=0.0):
        self.value = LaneRules(affinity_wait=affinity_wait,
                               conversation_hold=conversation_hold,
                               wait_upgrade=wait_upgrade)

    def __call__(self):
        return self.value


POOL = "AI-Hub/for-her-darkside-12b"
POOL2 = "DX10-01/tool"


def manager(lanes, rules=None):
    clock = Clock()
    return (LaneManager(now=clock, lane_count=lambda _key: lanes,
                        rules=rules or Rules()),
            clock)


def pool_of(view, key):
    for row in view["pools"]:
        if row["pool_key"] == key:
            return row
    return {}


def parked(m, cache_key, priority, arrived, pool=POOL):
    """Starts a call that really WAITS for a lane (the streaming shape)."""
    box = {}

    def run():
        try:
            box["handle"] = m.acquire_lane(pool, cache_key, priority,
                                           arrived=arrived, timeout=10 ** 9)
        except LaneTimeout as e:  # pragma: no cover - a failed check
            box["error"] = str(e)

    box["thread"] = threading.Thread(target=run, daemon=True,
                                     name=f"park-{cache_key}")
    box["thread"].start()
    return box


def wait_for_waiters(m, count, pool=POOL):
    """Blocks until ``count`` calls are parked. Only bounds how long the check
    waits for threads — it decides no expectation."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if m.snapshot()["pools"].get(pool, {}).get("waiting") == count:
            return True
        time.sleep(0.005)
    return False


# ── [1] the config side ────────────────────────────────────────────────────
print("\n[1] pools from the routing config, before anything ran")

_saved_routing = config._CONFIG.get("llm_routing")
config._CONFIG["llm_routing"] = [
    {"name": "Darkside (chat)", "provider": "AI-Hub",
     "model": "for-her-darkside-12b", "max_concurrent": 2, "enabled": True},
    {"name": "Darkside (hot)", "provider": "AI-Hub",
     "model": "for-her-darkside-12b", "max_concurrent": 3, "enabled": True},
    {"name": "Tool", "provider": "DX10-01", "model": "tool", "enabled": True},
    {"name": "Off", "provider": "DX10-01", "model": "disabled-model",
     "max_concurrent": 8, "enabled": False},
]

_empty, _ = manager(3)
view = admin_lane_view(_empty, stats={})
check("the two entries of one model make ONE pool",
      [row["pool_key"] for row in view["pools"]], [POOL, POOL2])
check("the highest lane count of the shared pool wins",
      pool_of(view, POOL)["configured_lanes"], 3)
check("an entry without a value gets one lane",
      pool_of(view, POOL2)["configured_lanes"], 1)
check("both entries are named on the shared pool",
      pool_of(view, POOL)["entries"], ["Darkside (chat)", "Darkside (hot)"])
check("a disabled entry is no pool",
      [row["pool_key"] for row in view["pools"] if "disabled-model" in row["pool_key"]],
      [])
check("an unused pool says so instead of printing zeros",
      (pool_of(view, POOL)["started"], pool_of(view, POOL)["lane_count"],
       pool_of(view, POOL)["busy"]),
      (False, None, None))
check("an unused pool has no cache figure",
      (pool_of(view, POOL)["cache"]["pct"], pool_of(view, POOL)["cache"]["text"]),
      (None, "no calls yet"))

# ── [2] the live side ──────────────────────────────────────────────────────
print("\n[2] the lane rows come from the running manager")

m, clock = manager(3)
clock.set(10)
h_kira = m.acquire_lane(POOL, "chat:Kira", Priority.CHAT, timeout=0,
                        label="chat_stream")
clock.set(12)
h_ida = m.acquire_lane(POOL, "thought:Ida", Priority.LOW, timeout=0,
                       label="thought")
clock.set(15)

view = admin_lane_view(m, stats={})
row = pool_of(view, POOL)
check("the pool is started now", row["started"], True)
check("lane count / busy / free at t=15",
      (row["lane_count"], row["busy"], row["free"]), (3, 2, 1))
check("the configured count is still shown next to it",
      row["configured_lanes"], 3)
lanes = row["lanes"]
check("one row per lane", [x["lane_id"] for x in lanes], [0, 1, 2])
check("hot keys per lane",
      [x["hot_key"] for x in lanes], ["chat:Kira", "thought:Ida", ""])
check("what is running on each lane",
      [x["label"] for x in lanes], ["chat_stream", "thought", ""])
check("lane 0 has been running for 15-10 s",
      (lanes[0]["busy"], lanes[0]["running_s"], lanes[0]["idle_s"]),
      (True, 5.0, None))
check("lane 1 has been running for 15-12 s",
      (lanes[1]["busy"], lanes[1]["running_s"], lanes[1]["idle_s"]),
      (True, 3.0, None))
check("the never-used lane reports no age at all",
      (lanes[2]["used"], lanes[2]["running_s"], lanes[2]["idle_s"],
       lanes[2]["age_s"]),
      (False, None, None, None))
check("nobody is waiting", (row["waiting"], row["waiting_calls"]), (0, []))

# ── [3] the same numbers after a change ────────────────────────────────────
print("\n[3] the numbers follow the state, they are not constants")

clock.set(16)
h_kira.release()
clock.set(20)
view = admin_lane_view(m, stats={})
row = pool_of(view, POOL)
check("busy/free after the release",
      (row["busy"], row["free"]), (1, 2))
lane0 = row["lanes"][0]
check("lane 0 is idle for 20-16 s and runs nothing",
      (lane0["busy"], lane0["idle_s"], lane0["running_s"], lane0["label"]),
      (False, 4.0, None, ""))
check("the released lane keeps its hot key", lane0["hot_key"], "chat:Kira")
check("lane 1 is still running, now for 20-12 s",
      row["lanes"][1]["running_s"], 8.0)
h_ida.release()

# ── [4] the waiting queue and its reason ───────────────────────────────────
print("\n[4a] all lanes busy")

m4, clock4 = manager(1)
clock4.set(0)
h_hold = m4.acquire_lane(POOL, "bg:holder", Priority.NORMAL, timeout=0,
                         label="consolidation")
w = parked(m4, "chat:Kira", Priority.CHAT, arrived=0)
check("the call is parked", wait_for_waiters(m4, 1), True)
clock4.set(4)
row = pool_of(admin_lane_view(m4, stats={}), POOL)
check("one waiting call", row["waiting"], 1)
call = row["waiting_calls"][0]
check("its key, class and age",
      (call["cache_key"], call["priority_label"], call["waiting_s"]),
      ("chat:Kira", "CHAT", 4.0))
check("the reason is that every lane is busy", call["reason"], "all_busy")
check("R2 has not aged it (wait_upgrade is off here)", call["aged"], False)
h_hold.release()
w["thread"].join(timeout=5)
check("and it runs the moment the lane frees", "handle" in w, True)
w["handle"].release()

print("\n[4b] R3 — a short wait for one's own lane")

m5, clock5 = manager(2, Rules(affinity_wait=5))
clock5.set(0)
h_a = m5.acquire_lane(POOL, "bg:other", Priority.NORMAL, timeout=0, label="x")
h_a.release()                       # lane 0 now carries the foreign key
clock5.set(1)
h_b = m5.acquire_lane(POOL, "bg:busy", Priority.NORMAL, timeout=0, label="y")
check("lane 1 is the busy one", h_b.lane_id, 1)
w5 = parked(m5, "thought:Ida", Priority.LOW, arrived=2)
check("the call is parked", wait_for_waiters(m5, 1), True)
clock5.set(4)                       # 2 s after arrival, affinity wait is 5 s
row = pool_of(admin_lane_view(m5, stats={}), POOL)
check("a free lane exists and it still waits",
      (row["free"], row["waiting"]), (1, 1))
check("the reason is R3", row["waiting_calls"][0]["reason"], "affinity_wait")
clock5.set(8)                       # 6 s after arrival — R3 is over
w5["thread"].join(timeout=5)
check("after the wait it takes the foreign lane",
      w5["handle"].lane_id if "handle" in w5 else w5.get("error"), 0)
w5["handle"].release()
h_b.release()

print("\n[4c] R4 — a fresh conversation lane is protected")

m6, clock6 = manager(2, Rules(conversation_hold=120))
clock6.set(0)
h_c = m6.acquire_lane(POOL, "chat:Kira", Priority.CHAT, timeout=0, label="chat_stream")
h_c.release()                       # lane 0: chat key, last used at t=0
clock6.set(1)
h_d = m6.acquire_lane(POOL, "bg:busy", Priority.NORMAL, timeout=0, label="y")
w6 = parked(m6, "thought:Ida", Priority.LOW, arrived=1)
check("the call is parked", wait_for_waiters(m6, 1), True)
row = pool_of(admin_lane_view(m6, stats={}), POOL)
check("a free lane exists and the thought still waits",
      (row["free"], row["waiting"]), (1, 1))
check("the reason is R4",
      row["waiting_calls"][0]["reason"], "conversation_hold")
clock6.set(130)                     # the hold has expired
w6["thread"].join(timeout=5)
check("after the hold it takes the lane",
      w6["handle"].lane_id if "handle" in w6 else w6.get("error"), 0)
w6["handle"].release()
h_d.release()

print("\n[4d] R2 — who is starting and who is outranked")

m7, clock7 = manager(1, Rules(wait_upgrade=60))
clock7.set(0)
h_e = m7.acquire_lane(POOL, "bg:holder", Priority.NORMAL, timeout=0, label="z")
h_e.release()                       # the pool exists, its one lane is free
pool7 = m7._pools[POOL]
pool7.waiting.append(_Waiter(cache_key="thought:Ida", priority=int(Priority.LOW),
                             arrived=0, ticket=1))
pool7.waiting.append(_Waiter(cache_key="chat:Kira", priority=int(Priority.CHAT),
                             arrived=10, ticket=2))
clock7.set(30)
row = pool_of(admin_lane_view(m7, stats={}), POOL)
by_key = {c["cache_key"]: c for c in row["waiting_calls"]}
check("the chat is the winner of this pass",
      by_key["chat:Kira"]["reason"], "starting")
check("the thought is outranked, although it is older",
      by_key["thought:Ida"]["reason"], "outranked")
check("the thought has not aged yet at 30 s",
      (by_key["thought:Ida"]["aged"], by_key["thought:Ida"]["effective_label"]),
      (False, "LOW"))
clock7.set(70)                      # 70 s > wait_upgrade 60
row = pool_of(admin_lane_view(m7, stats={}), POOL)
by_key = {c["cache_key"]: c for c in row["waiting_calls"]}
check("after the upgrade time it counts one class higher",
      (by_key["thought:Ida"]["aged"], by_key["thought:Ida"]["priority_label"],
       by_key["thought:Ida"]["effective_label"]),
      (True, "LOW", "NORMAL"))
pool7.waiting.clear()

# ── [5] the cache share ────────────────────────────────────────────────────
print("\n[5] ⚡ cache share — 'not reported' is not 0 %")

lane_cache_stats.reset()
RING = "AI-Hub/ring-model"
check("no call yet",
      (lane_cache_stats.pool_stats(RING)["pct"],
       lane_cache_stats.pool_stats(RING)["text"]),
      (None, "no calls yet"))

lane_cache_stats.record_call("AI-Hub", "ring-model", 900, None, lane=0,
                             cache_key="chat:Kira")
lane_cache_stats.record_call("AI-Hub", "ring-model", 900, None, lane=0,
                             cache_key="chat:Kira")
silent = lane_cache_stats.pool_stats(RING)
check("two calls, no figure from the backend",
      (silent["samples"], silent["reported"], silent["pct"]), (2, 0, None))
check("and the line says so", silent["text"], "cache not reported (2 calls)")

lane_cache_stats.reset()
lane_cache_stats.record_call("AI-Hub", "ring-model", 1000, 0, lane=0,
                             cache_key="chat:Kira")
cold = lane_cache_stats.pool_stats(RING)
check("a reported cold cache is a real 0",
      (cold["samples"], cold["reported"], cold["pct"]), (1, 1, 0.0))
check("and it reads differently from 'not reported'",
      cold["text"], "0 % cached (last 1 of 1 calls)")
check("the two states are not the same line",
      cold["text"] != silent["text"], True)

lane_cache_stats.record_call("AI-Hub", "ring-model", 1000, 800, lane=0,
                             cache_key="chat:Kira")
warm = lane_cache_stats.pool_stats(RING)
check("800 of 2000 reported prompt tokens = 40 %",
      (warm["reported"], warm["prompt_tokens"], warm["cached_tokens"],
       warm["pct"]),
      (2, 2000, 800, 40.0))
lane_cache_stats.record_call("AI-Hub", "ring-model", 5000, None, lane=1,
                             cache_key="thought:Ida")
mixed = lane_cache_stats.pool_stats(RING)
check("an unreported call does not drag the share down",
      (mixed["samples"], mixed["reported"], mixed["pct"]), (3, 2, 40.0))
check("but it is counted as a call",
      mixed["text"], "40 % cached (last 2 of 3 calls)")

lane_cache_stats.record_call("AI-Hub", "ring-model", 1000, 500,
                             error="boom")
lane_cache_stats.record_call("AI-Hub", "ring-model", 0, 500)
lane_cache_stats.record_call("", "ring-model", 1000, 500)
check("a failed call, a call without prompt tokens and a call without a "
      "provider are no samples",
      lane_cache_stats.pool_stats(RING)["samples"], 3)

# the ring is bounded, or the "last N calls" would be "all calls since boot"
for _ in range(lane_cache_stats.RING_SIZE + 5):
    lane_cache_stats.record_call("AI-Hub", "ring-model", 100, 10)
check("the ring keeps the last N calls",
      lane_cache_stats.pool_stats(RING)["samples"], lane_cache_stats.RING_SIZE)

print("\n[5b] the view shows the ring of the pool, per pool")
lane_cache_stats.reset()
lane_cache_stats.record_call("AI-Hub", "for-her-darkside-12b", 1000, 250)
view = admin_lane_view(_empty)
check("the shared pool carries its own share",
      pool_of(view, POOL)["cache"]["pct"], 25.0)
check("the other pool has seen nothing",
      pool_of(view, POOL2)["cache"]["text"], "no calls yet")
lane_cache_stats.reset()

# ── [6] a pool the config does not know ────────────────────────────────────
print("\n[6] a pool nobody configured is shown, not hidden")

m8, clock8 = manager(1)
clock8.set(0)
h_f = m8.acquire_lane("?/mystery-model", "bg:", Priority.NORMAL, timeout=0,
                      label="consolidation")
view = admin_lane_view(m8, stats={})
keys = [row["pool_key"] for row in view["pools"]]
check("it is listed", "?/mystery-model" in keys, True)
check("and sorted behind the configured pools", keys[-1], "?/mystery-model")
stray = pool_of(view, "?/mystery-model")
check("marked as not configured",
      (stray["configured"], stray["configured_lanes"]), (False, None))
check("its live numbers are still real",
      (stray["lane_count"], stray["busy"]), (1, 1))
h_f.release()

if _saved_routing is None:
    config._CONFIG.pop("llm_routing", None)
else:
    config._CONFIG["llm_routing"] = _saved_routing

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s)")
    for name in FAILED:
        print(f"  - {name}")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
