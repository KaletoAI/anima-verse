#!/usr/bin/env python3
"""Cache-lane check: assignment order (R1), no self-block (R6), task classes.

Usage:
    ./.venv/bin/python scripts/smoke_llm_lanes.py

Runs WITHOUT the server, without a world DB and without a config: the lane
manager takes its clock AND its lane count as arguments, so every expected
value below is a hand calculation from the rules, not a recording of current
output. The clock is stepped by the check; nothing sleeps.

Covers checks 1, 5 and 6 of development_instructions/plan-cache-lanes.md § 7.

THE RULES UNDER TEST

R1 assignment, in this order: a free lane whose key is already hot → a lane
that was never used → the free lane whose key has been idle the longest (LRU)
→ queue up. R6: a call may give its lane back and take one again from the
same call path without blocking itself (that is what the tool executor in
routes/chat.py does around every tool).

[1] R1 with a pool of TWO lanes, clock in whole seconds. Lane ids are handed
    out 0, 1; a release stamps the lane with the time it became free.

      t=0  acquire chat:Kira       -> lane 0   both lanes never used, lowest id
      t=1  acquire chat:Vallerie   -> lane 1   lane 0 is busy, lane 1 is fresh
                                               (two keys, two lanes)
      t=2  release chat:Kira                   lane 0: hot=chat:Kira,  idle@2
      t=3  release chat:Vallerie               lane 1: hot=chat:Vall., idle@3
      t=4  acquire chat:Vallerie   -> lane 1   its key is hot there; lane 0 is
                                               the older one and still loses
      t=5  release                             lane 1 idle@5
      t=6  acquire thought:Ida     -> lane 0   third key: no hot lane, no
                                               unused lane, so LRU — lane 0
                                               (idle@2) over lane 1 (idle@5)
      t=7  release                             lane 0 idle@7
      t=8  acquire chat:Kira       -> lane 1   Kira's key was displaced at
                                               t=6, so this is LRU again:
                                               lane 1 (idle@5) < lane 0 (@7)

    With both lanes busy a third key cannot be served: an acquire with
    timeout=0 raises LaneTimeout (that is the "queue up" branch, measured
    without blocking).

[2] R1 step 2 — a NEVER USED lane beats the least recently used one. Two
    lanes cannot show this: with two lanes the free lane the rule picks is
    the only one there is. With THREE the three steps really compete, and
    every line below fails if two of them are swapped:

      t=0  acquire chat:Kira      -> lane 0   all three never used, lowest id
      t=1  release                            lane 0: hot=chat:Kira, idle@1
      t=2  acquire chat:Kira      -> lane 0   STEP 1 beats step 2: its key is
                                              hot on lane 0, although lanes 1
                                              and 2 have never been used
      t=3  release                            lane 0 idle@3
      t=4  acquire chat:Vallerie  -> lane 1   STEP 2 beats step 3: lane 0 is
                                              free and, as the only used lane,
                                              also the LRU — a fresh lane is
                                              still taken first, because
                                              displacing Kira's key would cost
                                              a cache that costs nothing to keep
      t=5  release                            lane 1 idle@5
      t=6  acquire thought:Ida    -> lane 2   the last fresh lane, again over
                                              the LRU lane 0 (idle@3)
      t=7  release                            lane 2 idle@7
      t=8  acquire bg:            -> lane 0   no fresh lane left, so STEP 3:
                                              lane 0 (idle@3) is older than
                                              lane 1 (@5) and lane 2 (@7)

    One honest limit: under a clock that only moves forward, steps 2 and 3
    cannot disagree on the RESULT — a lane that was never used carries
    last_used = 0, the beginning of time, so it is the least recently used one
    as well. What the lines above pin is therefore: a hot key beats a fresh
    lane (t=2 picks lane 0, not lane 1), a fresh lane is never passed over for
    a used one (t=4/t=6 fail at once if a new lane were stamped with the
    current time at creation, or if the free lanes were ordered the other way
    round), and the oldest wins once nothing is fresh (t=8).

[3] Queueing up really hands the lane over: with both lanes busy, a call
    waiting in a second thread is parked on the pool (snapshot: waiting = 1)
    and is served the moment a lane is released. Exactly ONE lane is released
    here — lane 0, whose hot key is thought:Ida — so the waiter for chat:Kira
    must land on lane 0 although lane 1 holds its key: R1 chooses among the
    lanes that are FREE, and there is only one.

[4] R6 with a pool of ONE lane:
      a) acquire, release, acquire again with timeout=0 -> the same lane 0,
         no block. A release that did nothing would raise LaneTimeout here.
      b) while that second handle is held, a third acquire with timeout=0
         DOES raise LaneTimeout — the pool is genuinely occupied, so (a) is
         not passing for lack of accounting.
      c) release is idempotent: releasing the first handle a second time,
         after someone else has taken the lane, must not free that lane.
      d) the context-manager form survives an early release inside the body
         (the tool-executor shape); after the block the lane is free exactly
         once.

[5] cache_key_for(task, character) = "<class>:<character>". THE CLASS FOLLOWS
    THE PROMPT FAMILY, not the routing. It is declared once per task, as
    `cache_class` in the catalog (app/core/llm_tasks.py); the few surface ids
    that are not catalog tasks (user_chat, group_chat, story, ...) are mapped
    in llm_lanes by the same measure. llm_router.fallback_parent() is read for
    ONE thing only: the "<parent>_<sub>" shape, where the sub-task really does
    produce its parent's prompt. Its other entries are routing — which model
    answers — and a routing rule must never decide a prompt family, or an NPC
    action tick would land on the very lane that holds that character's live
    conversation and evict the cache this whole mechanism protects.

      chat_stream/Kira            -> chat:Kira      cache_class "chat"
      npc_talk/Bo                 -> chat:Bo        cache_class "chat": it IS
                                                    the chat prompt, under its
                                                    own name
      npc_action/Bo               -> bg:Bo          no cache_class: borrows the
                                                    chat MODEL, writes its own
                                                    one-sentence prompt
      group_chat/Kira             -> chat:Kira      surface, chat prompt
      user_chat/Kira              -> chat:Kira      surface, chat prompt
      character_talk/Kira         -> chat:Kira      surface, chat prompt
      story/Nox                   -> bg:Nox         surface of the storyteller:
                                                    world prose, a beginning
                                                    nobody else shares
      thought/Vallerie            -> thought:V.     cache_class "thought"
      thought_reflect/Vallerie    -> thought:V.     "<parent>_<sub>" rule
      intent/""                   -> tool:          cache_class "tool"
      intent_move/Kira            -> tool:Kira      "<parent>_<sub>" rule
      furnish/""                  -> tool:          cache_class "tool"
      prop_mount_classify/""      -> tool:          cache_class "tool"
      room_description_sync/""    -> bg:            the fourth furnish step,
                                                    but cache_class "bg": it
                                                    answers prose from its own
                                                    template and shares no
                                                    beginning with the tool
                                                    prompt it is ROUTED to
      spell_detect/Kira           -> tool:Kira      cache_class "tool"
      extraction_chat_state/Kira  -> bg:Kira        an extraction, no class
      consolidation/""            -> bg:            no class, world-wide: all
                                                    such calls share one key
      image_prompt/Kira           -> bg:Kira        no class
      storyteller/Nox             -> bg:Nox         catalog category "chat",
                                                    but its own prompt

[6] reconfigure: growing adds a lane at once, shrinking waits for the running
    call and drops the surplus lane when it is released.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Storage and clip library are redirected BEFORE the first app import: without
# it the default world is worlds/demo, which is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="llm-lanes-clips-")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="llm-lanes-storage-"))

from app.core.llm_lanes import (  # noqa: E402
    LaneManager, LaneTimeout, cache_key_for,
)

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


class Clock:
    """A clock the check steps by hand — no test ever sleeps for a rule."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = float(t)


POOL = "AI-Hub/for-her-darkside-12b"


def manager(lanes):
    clock = Clock()
    return LaneManager(now=clock, lane_count=lambda _key: lanes), clock


# ── [1] R1: hot key, unused lane, LRU ──────────────────────────────────────
print("[1] R1 assignment order (2 lanes)")
m, clock = manager(2)

clock.set(0)
h_kira = m.acquire_lane(POOL, "chat:Kira", timeout=0)
check("t=0 first call takes lane 0", h_kira.lane_id, 0)

clock.set(1)
h_val = m.acquire_lane(POOL, "chat:Vallerie", timeout=0)
check("t=1 second key takes the other lane", h_val.lane_id, 1)

clock.set(2)
h_kira.release()
clock.set(3)
h_val.release()

clock.set(4)
h = m.acquire_lane(POOL, "chat:Vallerie", timeout=0)
check("t=4 the hot key wins over the older lane", h.lane_id, 1)
clock.set(5)
h.release()

clock.set(6)
h = m.acquire_lane(POOL, "thought:Ida", timeout=0)
check("t=6 a third key takes the least recently used lane", h.lane_id, 0)
clock.set(7)
h.release()

clock.set(8)
h = m.acquire_lane(POOL, "chat:Kira", timeout=0)
check("t=8 a displaced key is LRU again, not 'its own' lane", h.lane_id, 1)
h2 = m.acquire_lane(POOL, "thought:Ida", timeout=0)
check("the second lane is free for the second key", h2.lane_id, 0)

try:
    m.acquire_lane(POOL, "bg:", timeout=0)
    check("a full pool makes the third key queue up", "assigned", "LaneTimeout")
except LaneTimeout:
    check("a full pool makes the third key queue up", "LaneTimeout", "LaneTimeout")

snap = m.snapshot()["pools"][POOL]
check("snapshot: both lanes busy", (snap["busy"], snap["free"]), (2, 0))
check("snapshot: hot keys per lane",
      [x["hot_key"] for x in snap["lanes"]], ["thought:Ida", "chat:Kira"])
check("free_lanes with a full pool", m.free_lanes(POOL, "chat:Kira"), 0)

# ── [2] R1 step 2: never used beats LRU ────────────────────────────────────
print("\n[2] R1 step 2: a never-used lane beats the LRU one (3 lanes)")
m3, clock3 = manager(3)

clock3.set(0)
h3 = m3.acquire_lane(POOL, "chat:Kira", timeout=0)
check("t=0 the first call takes lane 0", h3.lane_id, 0)
clock3.set(1)
h3.release()

clock3.set(2)
h3 = m3.acquire_lane(POOL, "chat:Kira", timeout=0)
check("t=2 the hot lane beats the two never-used ones", h3.lane_id, 0)
clock3.set(3)
h3.release()

clock3.set(4)
h3 = m3.acquire_lane(POOL, "chat:Vallerie", timeout=0)
check("t=4 a never-used lane beats the free LRU lane", h3.lane_id, 1)
clock3.set(5)
h3.release()

clock3.set(6)
h3 = m3.acquire_lane(POOL, "thought:Ida", timeout=0)
check("t=6 the last never-used lane still beats the LRU one", h3.lane_id, 2)
clock3.set(7)
h3.release()

clock3.set(8)
h3 = m3.acquire_lane(POOL, "bg:", timeout=0)
check("t=8 with no fresh lane left, the LRU one wins", h3.lane_id, 0)
h3.release()
check("all three lanes are free again",
      m3.snapshot()["pools"][POOL]["free"], 3)

# ── [3] queueing up hands the lane over ────────────────────────────────────
print("\n[3] a waiting call gets the lane that frees up")
got = {}


def waiter():
    handle = m.acquire_lane(POOL, "chat:Kira", timeout=10)
    got["lane"] = handle.lane_id
    handle.release()


t = threading.Thread(target=waiter, daemon=True)
t.start()
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if m.snapshot()["pools"][POOL]["waiting"] == 1:
        break
    time.sleep(0.01)
check("the call is queued on the pool",
      m.snapshot()["pools"][POOL]["waiting"], 1)
clock.set(9)
h2.release()   # lane 0 (hot key thought:Ida) — the only lane that frees up
t.join(timeout=5)
check("the waiter is served", "lane" in got, True)
check("it takes the one free lane, not the one holding its key",
      got.get("lane"), 0)
clock.set(10)
h.release()    # lane 1

# ── [3] R6: release early, take one again, no self-block ───────────────────
print("\n[4] R6 no self-block (1 lane)")
m1, clock1 = manager(1)
clock1.set(0)
first = m1.acquire_lane(POOL, "chat:Kira", timeout=0)
check("the single lane is taken", first.lane_id, 0)
clock1.set(1)
first.release()
try:
    second = m1.acquire_lane(POOL, "tool:Kira", timeout=0)
    check("a) release + acquire from the same call path", second.lane_id, 0)
except LaneTimeout:
    second = None
    check("a) release + acquire from the same call path", "LaneTimeout", 0)

if second is not None:
    try:
        m1.acquire_lane(POOL, "bg:", timeout=0)
        check("b) the held lane is really occupied", "assigned", "LaneTimeout")
    except LaneTimeout:
        check("b) the held lane is really occupied", "LaneTimeout", "LaneTimeout")

    first.release()  # second release of an already released handle
    check("c) a double release does not free someone else's lane",
          m1.snapshot()["pools"][POOL]["busy"], 1)
    second.release()

clock1.set(2)
with m1.acquire(POOL, "chat:Kira", timeout=0) as held:
    held.release()                                   # the tool executor's move
    inner = m1.acquire_lane(POOL, "tool:Kira", timeout=0)
    check("d) the freed lane is available inside the block", inner.lane_id, 0)
    inner.release()
check("d) after the block the lane is free",
      m1.snapshot()["pools"][POOL]["free"], 1)
check("free_lanes on an idle pool", m1.free_lanes(POOL, "chat:Kira"), 1)

# ── [4] cache_key_for ──────────────────────────────────────────────────────
print("\n[5] cache_key_for: task -> class")
for task, agent, want in [
    ("chat_stream", "Kira", "chat:Kira"),
    ("npc_talk", "Bo", "chat:Bo"),
    ("npc_action", "Bo", "bg:Bo"),
    ("group_chat", "Kira", "chat:Kira"),
    ("user_chat", "Kira", "chat:Kira"),
    ("character_talk", "Kira", "chat:Kira"),
    ("story", "Nox", "bg:Nox"),
    ("thought", "Vallerie", "thought:Vallerie"),
    ("thought_reflect", "Vallerie", "thought:Vallerie"),
    ("intent", "", "tool:"),
    ("intent_move", "Kira", "tool:Kira"),
    ("furnish", "", "tool:"),
    ("prop_mount_classify", "", "tool:"),
    ("room_description_sync", "", "bg:"),
    ("spell_detect", "Kira", "tool:Kira"),
    ("extraction_chat_state", "Kira", "bg:Kira"),
    ("consolidation", "", "bg:"),
    ("image_prompt", "Kira", "bg:Kira"),
    ("storyteller", "Nox", "bg:Nox"),
]:
    check(f"{task}/{agent or '-'}", cache_key_for(task, agent), want)

# ── [5] reconfigure ────────────────────────────────────────────────────────
print("\n[6] reconfigure")
m2, clock2 = manager(1)
clock2.set(0)
a = m2.acquire_lane(POOL, "chat:Kira", timeout=0)
m2.reconfigure(POOL, 2)
b = m2.acquire_lane(POOL, "chat:Vallerie", timeout=0)
check("growing adds a lane at once", (a.lane_id, b.lane_id), (0, 1))
m2.reconfigure(POOL, 1)
check("shrinking leaves the running calls alone",
      m2.snapshot()["pools"][POOL]["lane_count"], 2)
clock2.set(1)
b.release()
check("the surplus lane goes on release",
      m2.snapshot()["pools"][POOL]["lane_count"], 1)
a.release()

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
