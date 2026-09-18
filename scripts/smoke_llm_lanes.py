#!/usr/bin/env python3
"""Cache-lane check: the assignment rules R1-R4 and R6, and the task classes.

Usage:
    ./.venv/bin/python scripts/smoke_llm_lanes.py

Runs WITHOUT the server, without a world DB and without a config: the lane
manager takes its clock, its lane count AND the three global timings as
arguments, so every expected value below is a hand calculation from the rules,
not a recording of current output. The clock is stepped by the check; nothing
sleeps.

Covers checks 1-6 of development_instructions/plan-cache-lanes.md § 7.

Every acquire below goes through `try_lane`/`lane_of`: a rule that wrongly
holds a call off then prints a FAIL line instead of raising a LaneTimeout out
of the middle of the run and hiding every section after it.

THE RULES UNDER TEST

R1 assignment, in this order: the caller's OWN lane when it passed one and it
is still free → a free lane whose key is already hot → a lane that was never
used → the free lane whose key has been idle the longest (LRU) → queue up.
R2: when a lane frees up, only the highest waiting priority class
is eligible; within it the key that matches the lane wins, otherwise the
oldest — and a call that has waited longer than `wait_upgrade_seconds` counts
one class higher. R3: a call below the chat class takes a FOREIGN lane only
`affinity_wait_seconds` after it arrived. R4: a lane that last served a chat
younger than `conversation_hold_seconds` counts as occupied for a different
key, unless waiting would be a blockade rather than a wait. R6: a call may
give its lane back and take one again from the same call path without blocking
itself (that is what the tool executor in routes/chat.py does around every
tool).

THE THREE TIMINGS ARE ZERO unless a section sets them. Sections [1]-[6] and
[12] are about R1/R6 and switch R2's ageing, R3 and R4 off, so that each of
them can be read on its own; [7]-[9] switch on exactly the one they measure.

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

[7] R2 — who gets the lane that just freed up. One lane, held by a call the
    check releases on a stepped clock; the contenders are already parked on
    the pool when it frees, so the answer does not depend on which thread
    wakes first. `wait_upgrade_seconds` = 60, the other two timings 0.

    a) CLASS BEATS AGE. The holder runs with key bg:holder (so the freed lane
       matches nobody). LOW arrives at t=1, CHAT at t=2, the lane frees at
       t=3. Expected: CHAT, although LOW waited a second longer. Then CHAT
       releases and LOW gets it — the loser is served, not dropped.
    b) KEY BEATS AGE INSIDE A CLASS. The holder runs with key chat:Kira, so
       the lane is hot for chat:Kira when it frees. Both waiters are LOW:
       thought:Ida arrived t=1, chat:Kira arrived t=2. Expected: chat:Kira —
       the younger one — because its prompt beginning is still on that lane.
    c) AGEING, the pair that only differs in the clock. Waiters: LOW at t=0
       and NORMAL at t=10, one lane, hot key bg:holder.
         c1) the lane frees at t=30. LOW has waited 30 s < 60, so it is still
             LOW(30) and NORMAL(20) wins.
         c2) same setup, the lane frees at t=61. LOW has waited 61 s >= 60 and
             counts one rung higher — NORMAL(20). NORMAL itself waited 51 s,
             not enough, so it stays NORMAL. Tie, and the tie goes to the
             older arrival: LOW wins. Ageing is computed at selection time
             from the clock; nothing promotes anyone in the background.
         c3) THE BOUNDARY ITSELF, t = 60 exactly. c1 and c2 are 30 and 61, so
             they hold whether the rule reads ">= 60" or "> 60"; only the
             exact second tells the two apart. The plan says "who waits
             LONGER than wait_upgrade_seconds rises" and the code reads
             ">=" — 60 s of waiting is the first second that counts. Same
             setup, the lane frees at t=60: LOW(30) has waited exactly 60 s
             and rises to NORMAL(20), NORMAL waited 50 s and stays, tie to
             the older arrival, so LOW wins. Under ">" the NORMAL call would
             win here, and nothing else in this file would notice.
    d) A PARKED CALL DOES NOT OUT-RANK A LATER CHAT. The two shapes are not
       the same: a queued task is NOT a persistent waiter (the worker asks
       with timeout=0 and re-queues), only a streaming registration really
       parks. Here the parked one is a LOW held back by R3 (affinity wait set
       to 1000 s, so it cannot take the one foreign lane no matter what) while
       a CHAT call arrives later and asks with timeout=0, the queue-worker
       shape. Expected: the CHAT gets the lane at once — a call parked in the
       list blocks nobody it out-ranks, and the chat class ignores R3. It
       takes lane 0 (idle@1) over lane 1 (idle@3), plain LRU. After the CHAT
       releases at t=1005 and the clock has passed the affinity wait, the LOW
       is served on lane 1 — the least recently used of the two by then.

[8] R3 — the affinity wait, on two lanes with `affinity_wait_seconds` = 3 and
    the other two timings 0. Both lanes are made hot first: chat:Kira on lane
    0 (idle@1), chat:Bo on lane 1 (idle@3). Nothing is fresh any more, so
    every lane is FOREIGN for a third key.

      t=4  thought:Ida (LOW), arrived 4   -> LaneTimeout   waited 0 s < 3
      t=6  thought:Ida (LOW), arrived 4   -> LaneTimeout   waited 2 s < 3
           (the SAME arrival stamp: a queued task asks again on every pass of
           the worker and ages from when it first asked, not from this try)
      t=7  thought:Ida (LOW), arrived 4   -> lane 0        waited 3 s >= 3,
                                                           then plain LRU:
                                                           lane 0 (idle@1)
      t=9  thought:Ida (LOW), arrived 9   -> lane 0        its OWN key is hot
                                                           there — no wait
      t=11 chat:Vallerie (CHAT), arr. 11  -> lane 1        the chat class is
                                                           not subject to R3
                                                           (lane 1 is the LRU
                                                           of the two now)

    And on a pool of three lanes: after chat:Kira has used lane 0, a LOW call
    with a third key takes the never-used lane 1 at once — a fresh lane is not
    a foreign one, it costs no cache.

[9] R4 — the conversation hold, `conversation_hold_seconds` = 120, the other
    two timings 0.

    a) TWO LANES, ONE OF THEM A FRESH CONVERSATION. chat:Kira runs on lane 0
       and frees it at t=1; bg:x runs on lane 1 and frees it at t=3. At t=4 a
       thought asks: lane 0 is the LRU (idle@1 < idle@3), but its hot key is a
       chat that ran 3 s ago, so it is held — expected lane 1. Without R4 this
       lands on lane 0 and the conversation's cache is gone.
       free_lanes for that key is 1 here, not 2.
    b) THE HOLD EXPIRES. At t=200 a fourth key asks: lane 0's chat is 199 s
       old, past the 120 s hold, so it is an ordinary LRU lane again —
       expected lane 0.
    c) A BUSY LANE IS WORTH WAITING FOR. Two lanes: lane 0 free with a fresh
       chat key, lane 1 BUSY. A thought with timeout=0 gets LaneTimeout — it
       waits for the running call to free lane 1 instead of evicting the
       conversation. free_lanes for its key is 0.
    d) BUT NEVER A BLOCKADE. Same pool, lane 1 released, both lanes now free
       and both hot with a fresh chat key. Nothing is running that could free
       anything else, so waiting would mean waiting for the hold itself —
       expected: the thought takes the LRU lane 0 after all. Same on a pool of
       ONE lane, which is the case the plan names: the single lane is a fresh
       chat lane and is taken anyway.
       free_lanes says ONE here, not two: the moment the first caller takes a
       held lane it is a running call, and the remaining held lane is worth
       waiting for again. Two would tell the phase-3 dispatcher to start two
       turns where the rules hand out one lane.

    e) THE HOLD IS AGAINST BACKGROUND WORK, NOT AGAINST THE CHAT CLASS
       (review of phase 2, plan § 4 R4). Same pool as (c): lane 0 free with a
       fresh chat:Kira on it, lane 1 BUSY. A thought gets nothing there — that
       is (c). A CHAT call with a third key gets lane 0 at once: a
       conversation must never wait behind a thought while a lane sits idle,
       which is the same reason R3 exempts the class. What it costs is
       measured right after: on a pool whose free lanes are a fresh
       chat:Kira (idle@3) and an older bg:x (idle@1), the chat call takes the
       OLDER one — R1 picks the least recently used lane among those allowed,
       so a lane a conversation just left is the last one anybody reaches for.
       The exemption only decides what happens when there is nothing else.
       AND ``free_lanes`` HAS TO SAY THE SAME THING. It answers "what could
       this caller take right now", so it needs the caller's class, exactly
       as the assignment does: on that pool the thought is told 0 and the
       chat call 1 — and the chat call then really gets a lane, which is what
       makes the 1 the truth and not an opinion. Asked without a class it
       answers for background work, which is the safe default for everyone
       who is. The respond dispatcher of phase 3 asks with the chat class
       (`agent_loop._respond_lane_free`); told 0 here it would leave a free
       lane unused whenever the NEIGHBOURING conversation had been on it
       within the hold — with one lane per entry, that is every second turn
       of a two-person scene.
    f) AND NOT AGAINST THE CALLER'S OWN LANE. The nested tool call of a turn
       hands its lane back first (R6) and asks again a moment later; the lane
       is then a free, fresh chat lane belonging to that very turn. R4 would
       protect the conversation against its own tool call and — with the
       second lane busy with someone else's call — the turn would wait for a
       stranger to finish. What prevents it is R1's first step, which hands
       out `own_lane` before R3 and R4 are consulted at all (section [12] is
       where that step is read on its own). Lane 0 free (fresh chat:Kira),
       lane 1 busy: `tool:Kira` at LOW gets LaneTimeout, the same call with
       `own_lane=0` gets lane 0.

[10] The three timings come from the CONFIG, and they are read live. The
    defaults in app/core/config_schema.py (section "Cache Lanes") and the
    defaults in the code are the same two numbers in two places, so they are
    compared against each other here: 3 s affinity wait, 120 s conversation
    hold, 60 s wait upgrade. Then a manager that reads the config the way the
    server does is shown changing its answer between two identical calls —
    the same clock, the same pool, only the config edited in between: with a
    1000 s affinity wait the background call gets nothing, with 0 it gets a
    lane. Nothing is cached at import, so an admin save lands without a
    restart.

[11] R2 again, the part that is easy to get backwards: A WAITER HELD BACK BY
    R3/R4 BLOCKS NOBODY — IN ITS OWN CLASS, AND WITHOUT A KEY MATCH. [7d]
    shows it across classes, where the class filter alone would produce the
    same answer; and a younger call whose KEY is hot on the lane wins by the
    key rule anyway. Only this shape isolates `_next_in_line`'s "count only
    the waiters that could take a lane at this moment": same class, no key
    match, and the younger call is assignable for one reason only — it is the
    turn taking back the lane it gave up for its own tool call (R6, own_lane).
    Two lanes, hold = 120 s, affinity wait 0. Lane 0 last served chat:Kira
    (idle@1), lane 1 is BUSY with a foreign call, so nothing can come free but
    the held lane.
      t=3  thought:Ida (LOW) parks — R4 holds it off lane 0, lane 1 is busy
      t=4  tool:Kira (LOW, own_lane=0) asks with timeout=0 -> lane 0 at once.
           Same class, one second younger, no key match — and it wins because
           the older call cannot take that lane at all. A selection that
           counted the parked call as a contender would hand it the pass on
           age and NEITHER would run: the parked one may not take the lane,
           and the one that may is not the winner.
      t=5  the tool call gives lane 0 back, hot key tool:Kira. It is not a
           conversation any more, so R4 no longer holds anybody off it and the
           parked call is served there — the loser is not dropped.

[12] R1 STEP 1 — A FREE `own_lane` WINS BEFORE EVERYTHING ELSE, IN EVERY
    PRIORITY CLASS (review of phase 2, round 2, plan § 4 R1). `own_lane` is
    literally the lane this call released a moment ago so that its own nested
    tool call could run (R6): its prompt is cached there. All three timings
    are 0 here, so R3 and R4 cannot be the reason for anything — R1 alone
    decides. Two lanes, two conversations, the clock at t=4:

      lane 0  hot chat:Vallerie, idle@1   the other conversation, between
                                          turns — and the LRU lane
      lane 1  hot chat:Kira,     idle@3   the turn's own, just handed back

    Without `own_lane` the LRU step sends `tool:Kira` onto lane 0 and evicts
    the neighbour's prompt cache — that is the finding, and it is measured
    first so the fix is not passing for lack of a difference. With
    `own_lane=1` the tool call gets lane 1, and so does the RESUME right after
    it (by then lane 1 is hot for `tool:Kira`, so no other step of R1 would
    bring it back either), while lane 0 still carries `chat:Vallerie`. The
    three classes CHAT/NORMAL/LOW are run through the same shape: the step may
    not depend on the class, or a thought's tool call — which now inherits its
    turn's LOW priority — would still evict the neighbour.

[13] R1 STEP 1 WHEN IT IS CONTESTED — the same step, against a HIGHER class
    that is already parked on the pool (review of phase 2, round 3). [12] has
    no contest: nobody else wants the lane, so it only shows that
    `_assignable_lane` honours `own_lane`. This section is the case that goes
    wrong without R2 knowing about the step as well: R2 picks the winner of a
    pass BEFORE the lane is assigned, so a parked CHAT would win the pass on
    its class and take the lane a LOW thought turn released one instant
    earlier for its own tool call. One lane, all three timings 0, so neither
    R3 nor R4 nor the ageing can be the reason for anything.

      t=0  thought:Ida (LOW)   takes lane 0        the running turn
      t=1  chat:Kira  (CHAT)   parks               one lane, and it is busy
      t=2  the turn hands lane 0 back (R6) and its tool decision asks for it
           with own_lane=0: expected lane 0, the CHAT keeps waiting
      t=3  the tool call gives it back, the turn RESUMES with own_lane=0:
           expected lane 0 again, the CHAT still waiting
      t=4  the turn ends: the CHAT is served at once — it waited one turn,
           which is the normal wait on a pool with one lane

    Negative control, run first and on the identical setup: the same suspend
    WITHOUT own_lane. There the parked CHAT takes the lane and the tool call
    gets a LaneTimeout — the measured bug, in which the turn's tool call and
    then its resume wait behind a whole foreign chat turn, on a busy one-lane
    pool until the 660 s stale sweep frees the registration.

    The two halves of a suspend (release, then ask again) run under the
    manager's lock here — see `frozen`. Otherwise the parked thread, which the
    release wakes, could take the lane before the nested call has asked at
    all: that is a race between two threads, not a rule, and it would make the
    check report whichever thread happened to win. Under the lock both calls
    are in the same selection pass, which is what the rule decides.

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
    """A temp directory that lives exactly as long as this run.

    Registered for removal at exit, whatever the run does — a check that is
    started a few dozen times in a review round otherwise fills /tmp with
    empty world directories nobody ever looks at again.
    """
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


# Storage and clip library are redirected BEFORE the first app import: without
# it the default world is worlds/demo, which is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = scratch("llm-lanes-clips-")

from app.core import paths  # noqa: E402

paths.init(scratch("llm-lanes-storage-"))

from app.core.llm_lanes import (  # noqa: E402
    LaneManager, LaneRules, LaneTimeout, cache_key_for, configured_lane_rules,
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
    """A clock the check steps by hand — no test ever sleeps for a rule."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = float(t)


POOL = "AI-Hub/for-her-darkside-12b"


class Rules:
    """The three global timings, under the check's control.

    The manager reads them through this object on EVERY selection pass (in
    the server they come from the config the same way), so a section can
    change one between two steps. Everything is 0 by default: a section that
    does not name a rule is not subject to it, which is what lets R1, R3 and
    R4 be read one at a time.
    """

    def __init__(self, affinity_wait=0.0, conversation_hold=0.0,
                 wait_upgrade=0.0):
        self.value = LaneRules(affinity_wait=affinity_wait,
                               conversation_hold=conversation_hold,
                               wait_upgrade=wait_upgrade)

    def __call__(self):
        return self.value


def manager(lanes, rules=None):
    clock = Clock()
    return (LaneManager(now=clock, lane_count=lambda _key: lanes,
                        rules=rules or Rules()),
            clock)


def parked(m, cache_key, priority, arrived, *, pool=None):
    """Starts a call that really WAITS for a lane (the streaming shape).

    Returns a box that fills with ``handle`` once the call is served. The
    arrival stamp is handed in, so the order under test is the one written
    down here and not the one the thread scheduler produces.
    """
    box = {}

    def run():
        try:
            # The timeout is far beyond anything the stepped clock reaches:
            # the CLOCK decides the rules, and a parked call must not lose its
            # place just because a section jumps the clock by a minute. It is
            # only there so a broken rule ends the check instead of hanging.
            box["handle"] = m.acquire_lane(pool or POOL, cache_key, priority,
                                           arrived=arrived, timeout=10 ** 9)
        except LaneTimeout as e:  # pragma: no cover - a failed check
            box["error"] = str(e)

    box["thread"] = threading.Thread(target=run, daemon=True,
                                     name=f"park-{cache_key}")
    box["thread"].start()
    return box


def wait_for_waiters(m, count, pool=None):
    """Blocks until ``count`` calls are parked on the pool. Only bounds how
    long the check waits for threads — it decides no expectation."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if m.snapshot()["pools"].get(pool or POOL, {}).get("waiting") == count:
            return True
        time.sleep(0.005)
    return m.snapshot()["pools"].get(pool or POOL, {}).get("waiting") == count


def served(box, timeout=5):
    """The lane id a parked call was given (None = it is still waiting)."""
    box["thread"].join(timeout=timeout)
    handle = box.get("handle")
    return handle.lane_id if handle is not None else None


def drop(box):
    """Releases what a parked call holds — a no-op when a failed check left it
    waiting, so one failure does not take the rest of the run with it."""
    handle = box.get("handle")
    if handle is not None:
        handle.release()


def try_lane(m, cache_key, priority=Priority.NORMAL, arrived=None, pool=None,
             own_lane=None):
    """One acquire with timeout=0 — the handle, or the string "LaneTimeout".

    Every line below expects a LANE ID. A rule that wrongly holds a call off
    would raise out of the middle of the run and hide every section after it,
    so the timeout is turned into a value here: a broken rule then prints its
    FAIL line and the rest of the check still runs.
    """
    try:
        return m.acquire_lane(pool or POOL, cache_key, priority,
                              arrived=arrived, own_lane=own_lane, timeout=0)
    except LaneTimeout:
        return "LaneTimeout"


def lane_of(result):
    """The lane id of what ``try_lane`` returned, or the string it returned."""
    return result if isinstance(result, str) else result.lane_id


def drop_lane(result):
    """Releases it, unless there is nothing to release."""
    if not isinstance(result, str):
        result.release()


# ── [1] R1: hot key, unused lane, LRU ──────────────────────────────────────
print("[1] R1 assignment order (2 lanes)")
m, clock = manager(2)

clock.set(0)
h_kira = try_lane(m, "chat:Kira")
check("t=0 first call takes lane 0", lane_of(h_kira), 0)

clock.set(1)
h_val = try_lane(m, "chat:Vallerie")
check("t=1 second key takes the other lane", lane_of(h_val), 1)

clock.set(2)
drop_lane(h_kira)
clock.set(3)
drop_lane(h_val)

clock.set(4)
h = try_lane(m, "chat:Vallerie")
check("t=4 the hot key wins over the older lane", lane_of(h), 1)
clock.set(5)
drop_lane(h)

clock.set(6)
h = try_lane(m, "thought:Ida")
check("t=6 a third key takes the least recently used lane", lane_of(h), 0)
clock.set(7)
drop_lane(h)

clock.set(8)
h = try_lane(m, "chat:Kira")
check("t=8 a displaced key is LRU again, not 'its own' lane", lane_of(h), 1)
h2 = try_lane(m, "thought:Ida")
check("the second lane is free for the second key", lane_of(h2), 0)

check("a full pool makes the third key queue up",
      lane_of(try_lane(m, "bg:")), "LaneTimeout")

snap = m.snapshot()["pools"][POOL]
check("snapshot: both lanes busy", (snap["busy"], snap["free"]), (2, 0))
check("snapshot: hot keys per lane",
      [x["hot_key"] for x in snap["lanes"]], ["thought:Ida", "chat:Kira"])
check("free_lanes with a full pool", m.free_lanes(POOL, "chat:Kira"), 0)

# ── [2] R1 step 2: never used beats LRU ────────────────────────────────────
print("\n[2] R1 step 2: a never-used lane beats the LRU one (3 lanes)")
m3, clock3 = manager(3)

clock3.set(0)
h3 = try_lane(m3, "chat:Kira")
check("t=0 the first call takes lane 0", lane_of(h3), 0)
clock3.set(1)
drop_lane(h3)

clock3.set(2)
h3 = try_lane(m3, "chat:Kira")
check("t=2 the hot lane beats the two never-used ones", lane_of(h3), 0)
clock3.set(3)
drop_lane(h3)

clock3.set(4)
h3 = try_lane(m3, "chat:Vallerie")
check("t=4 a never-used lane beats the free LRU lane", lane_of(h3), 1)
clock3.set(5)
drop_lane(h3)

clock3.set(6)
h3 = try_lane(m3, "thought:Ida")
check("t=6 the last never-used lane still beats the LRU one", lane_of(h3), 2)
clock3.set(7)
drop_lane(h3)

clock3.set(8)
h3 = try_lane(m3, "bg:")
check("t=8 with no fresh lane left, the LRU one wins", lane_of(h3), 0)
drop_lane(h3)
check("all three lanes are free again",
      m3.snapshot()["pools"][POOL]["free"], 3)

# ── [3] queueing up hands the lane over ────────────────────────────────────
print("\n[3] a waiting call gets the lane that frees up")
queued = parked(m, "chat:Kira", Priority.NORMAL, arrived=8)
check("the call is queued on the pool", wait_for_waiters(m, 1), True)
clock.set(9)
drop_lane(h2)  # lane 0 (hot key thought:Ida) — the only lane that frees up
check("it takes the one free lane, not the one holding its key",
      served(queued), 0)
drop(queued)
clock.set(10)
drop_lane(h)   # lane 1

# ── [3] R6: release early, take one again, no self-block ───────────────────
print("\n[4] R6 no self-block (1 lane)")
m1, clock1 = manager(1)
clock1.set(0)
first = try_lane(m1, "chat:Kira")
check("the single lane is taken", lane_of(first), 0)
clock1.set(1)
drop_lane(first)
second = try_lane(m1, "tool:Kira")
check("a) release + acquire from the same call path", lane_of(second), 0)

if not isinstance(second, str):
    check("b) the held lane is really occupied",
          lane_of(try_lane(m1, "bg:")), "LaneTimeout")

    drop_lane(first)  # second release of an already released handle
    check("c) a double release does not free someone else's lane",
          m1.snapshot()["pools"][POOL]["busy"], 1)
    drop_lane(second)

clock1.set(2)
with m1.acquire(POOL, "chat:Kira", timeout=0) as held:
    held.release()                                   # the tool executor's move
    inner = try_lane(m1, "tool:Kira")
    check("d) the freed lane is available inside the block", lane_of(inner), 0)
    drop_lane(inner)
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
a = try_lane(m2, "chat:Kira")
m2.reconfigure(POOL, 2)
b = try_lane(m2, "chat:Vallerie")
check("growing adds a lane at once", (lane_of(a), lane_of(b)), (0, 1))
m2.reconfigure(POOL, 1)
check("shrinking leaves the running calls alone",
      m2.snapshot()["pools"][POOL]["lane_count"], 2)
clock2.set(1)
drop_lane(b)
check("the surplus lane goes on release",
      m2.snapshot()["pools"][POOL]["lane_count"], 1)
drop_lane(a)

# ── [7] R2: class, key, ageing ─────────────────────────────────────────────
print("\n[7] R2 selection when a lane frees up (1 lane)")

# a) class beats age
m7, clock7 = manager(1, Rules(wait_upgrade=60))
clock7.set(0)
holder = try_lane(m7, "bg:holder", Priority.NORMAL, arrived=0)
clock7.set(1)
low = parked(m7, "thought:Ida", Priority.LOW, arrived=1)
clock7.set(2)
chat = parked(m7, "chat:Kira", Priority.CHAT, arrived=2)
check("a) both calls are parked on the pool", wait_for_waiters(m7, 2), True)
clock7.set(3)
drop_lane(holder)
check("a) the CHAT class wins over the older LOW call", served(chat), 0)
check("a) and the LOW call is still waiting", low.get("handle"), None)
clock7.set(4)
drop(chat)
check("a) the loser is served next, not dropped", served(low), 0)
drop(low)

# b) the key beats age inside one class
m7b, clock7b = manager(1, Rules(wait_upgrade=60))
clock7b.set(0)
holder = try_lane(m7b, "chat:Kira", Priority.CHAT, arrived=0)
clock7b.set(1)
older = parked(m7b, "thought:Ida", Priority.LOW, arrived=1)
clock7b.set(2)
matching = parked(m7b, "chat:Kira", Priority.LOW, arrived=2)
check("b) both calls are parked", wait_for_waiters(m7b, 2), True)
clock7b.set(3)
drop_lane(holder)         # lane 0 is now hot for chat:Kira
check("b) the key that matches the lane wins over the older call",
      served(matching), 0)
check("b) the older call waits", older.get("handle"), None)
drop(matching)
check("b) and is served afterwards", served(older), 0)
drop(older)

# c1) not aged yet: the higher class wins
m7c, clock7c = manager(1, Rules(wait_upgrade=60))
clock7c.set(0)
holder = try_lane(m7c, "bg:holder", Priority.NORMAL, arrived=0)
old_low = parked(m7c, "bg:old", Priority.LOW, arrived=0)
clock7c.set(10)
normal = parked(m7c, "bg:new", Priority.NORMAL, arrived=10)
check("c1) both calls are parked", wait_for_waiters(m7c, 2), True)
clock7c.set(30)
drop_lane(holder)
check("c1) after 30 s of waiting the LOW call is still LOW",
      served(normal), 0)
check("c1) so it has not been served", old_low.get("handle"), None)
drop(normal)
check("c1) it follows once the lane is free again", served(old_low), 0)
drop(old_low)

# c2) aged past the upgrade: the older call overtakes
m7d, clock7d = manager(1, Rules(wait_upgrade=60))
clock7d.set(0)
holder = try_lane(m7d, "bg:holder", Priority.NORMAL, arrived=0)
old_low = parked(m7d, "bg:old", Priority.LOW, arrived=0)
clock7d.set(10)
normal = parked(m7d, "bg:new", Priority.NORMAL, arrived=10)
check("c2) both calls are parked", wait_for_waiters(m7d, 2), True)
clock7d.set(61)
drop_lane(holder)
check("c2) after 61 s the LOW call counts one class higher and, being older, "
      "wins", served(old_low), 0)
check("c2) the NORMAL call waits", normal.get("handle"), None)
drop(old_low)
check("c2) and is served next", served(normal), 0)
drop(normal)

# c3) exactly at the boundary: 60 s of waiting already counts
m7f, clock7f = manager(1, Rules(wait_upgrade=60))
clock7f.set(0)
holder = try_lane(m7f, "bg:holder", Priority.NORMAL, arrived=0)
old_low = parked(m7f, "bg:old", Priority.LOW, arrived=0)
clock7f.set(10)
normal = parked(m7f, "bg:new", Priority.NORMAL, arrived=10)
check("c3) both calls are parked", wait_for_waiters(m7f, 2), True)
clock7f.set(60)
drop_lane(holder)
check("c3) at exactly 60 s the LOW call has risen and wins on age",
      served(old_low), 0)
check("c3) the NORMAL call waits", normal.get("handle"), None)
drop(old_low)
check("c3) and is served next", served(normal), 0)
drop(normal)

# d) a parked call does not out-rank a CHAT call that arrives later
m7e, clock7e = manager(2, Rules(affinity_wait=1000))
clock7e.set(0)
h = try_lane(m7e, "chat:Kira", Priority.CHAT, arrived=0)
clock7e.set(1)
drop_lane(h)                                 # lane 0: hot chat:Kira, idle@1
clock7e.set(2)
h = try_lane(m7e, "chat:Bo", Priority.CHAT, arrived=2)
clock7e.set(3)
drop_lane(h)                                 # lane 1: hot chat:Bo, idle@3
clock7e.set(4)
waiting_low = parked(m7e, "thought:Ida", Priority.LOW, arrived=4)
check("d) the LOW call parks (R3 keeps it off both foreign lanes)",
      wait_for_waiters(m7e, 1), True)
clock7e.set(5)
late_chat = try_lane(m7e, "chat:Vallerie", Priority.CHAT, arrived=5)
check("d) the later CHAT call takes a lane at once", lane_of(late_chat), 0)
check("d) the parked LOW call is still waiting", waiting_low.get("handle"),
      None)
clock7e.set(1005)          # the affinity wait of the parked call is over
drop_lane(late_chat)
# Both lanes are free now; the LOW call's own key is on neither, so it is
# plain LRU — lane 1 (idle@3) against lane 0, which the chat left at t=1005.
check("d) and is served once its own wait is over", served(waiting_low), 1)
drop(waiting_low)

# ── [8] R3: the affinity wait ──────────────────────────────────────────────
print("\n[8] R3 affinity wait (2 lanes, wait = 3 s)")
m8, clock8 = manager(2, Rules(affinity_wait=3))
clock8.set(0)
h = try_lane(m8, "chat:Kira", Priority.CHAT, arrived=0)
clock8.set(1)
drop_lane(h)                                 # lane 0: hot chat:Kira, idle@1
clock8.set(2)
h = try_lane(m8, "chat:Bo", Priority.CHAT, arrived=2)
clock8.set(3)
drop_lane(h)                                 # lane 1: hot chat:Bo, idle@3

for t, want in ((4, "LaneTimeout"), (6, "LaneTimeout")):
    clock8.set(t)
    h = try_lane(m8, "thought:Ida", Priority.LOW, arrived=4)
    check(f"t={t} a background call takes no foreign lane before the wait",
          lane_of(h), want)
    drop_lane(h)

clock8.set(7)
h = try_lane(m8, "thought:Ida", Priority.LOW, arrived=4)
check("t=7 after the wait it takes the least recently used lane",
      lane_of(h), 0)
clock8.set(8)
drop_lane(h)                                 # lane 0: hot thought:Ida, idle@8

clock8.set(9)
h = try_lane(m8, "thought:Ida", Priority.LOW, arrived=9)
check("t=9 its OWN key it takes at once, with no wait", lane_of(h), 0)
clock8.set(10)
drop_lane(h)

clock8.set(11)
h = try_lane(m8, "chat:Vallerie", Priority.CHAT, arrived=11)
check("t=11 the chat class is not subject to the wait", lane_of(h), 1)
drop_lane(h)

m8b, clock8b = manager(3, Rules(affinity_wait=3))
clock8b.set(0)
h = try_lane(m8b, "chat:Kira", Priority.CHAT, arrived=0)
clock8b.set(1)
drop_lane(h)
clock8b.set(2)
h = try_lane(m8b, "bg:x", Priority.LOW, arrived=2)
check("a never-used lane is taken at once, with no wait", lane_of(h), 1)
drop_lane(h)

# ── [9] R4: the conversation hold ──────────────────────────────────────────
print("\n[9] R4 conversation hold (hold = 120 s)")
m9, clock9 = manager(2, Rules(conversation_hold=120))
clock9.set(0)
h = try_lane(m9, "chat:Kira", Priority.CHAT, arrived=0)
clock9.set(1)
drop_lane(h)                                 # lane 0: hot chat:Kira, idle@1
clock9.set(2)
h = try_lane(m9, "bg:x", Priority.LOW, arrived=2)
clock9.set(3)
drop_lane(h)                                 # lane 1: hot bg:x, idle@3

clock9.set(4)
check("a) free_lanes counts the held conversation lane out",
      m9.free_lanes(POOL, "thought:Ida"), 1)
h = try_lane(m9, "thought:Ida", Priority.LOW, arrived=4)
check("a) a thought takes the other lane, not the fresh conversation",
      lane_of(h), 1)
clock9.set(5)
drop_lane(h)                                 # lane 1: hot thought:Ida, idle@5

clock9.set(200)
h = try_lane(m9, "bg:y", Priority.LOW, arrived=200)
check("b) once the hold has expired the lane is an ordinary LRU lane again",
      lane_of(h), 0)
drop_lane(h)

m9b, clock9b = manager(2, Rules(conversation_hold=120))
clock9b.set(0)
h = try_lane(m9b, "chat:Kira", Priority.CHAT, arrived=0)
clock9b.set(1)
drop_lane(h)                                 # lane 0: hot chat:Kira, idle@1
clock9b.set(2)
busy = try_lane(m9b, "chat:Bo", Priority.CHAT, arrived=2)
clock9b.set(3)
check("c) free_lanes: no lane for a different key while one is running",
      m9b.free_lanes(POOL, "thought:Ida"), 0)
check("c) a thought waits for the running call instead of evicting the chat",
      lane_of(try_lane(m9b, "thought:Ida", Priority.LOW, arrived=3)),
      "LaneTimeout")

clock9b.set(4)
drop_lane(busy)                              # lane 1: hot chat:Bo, idle@4
clock9b.set(5)
check("d) with both lanes held and nothing running, exactly ONE lane can "
      "really be taken", m9b.free_lanes(POOL, "thought:Ida"), 1)
h = try_lane(m9b, "thought:Ida", Priority.LOW, arrived=5)
check("d) so the thought takes the least recently used one after all",
      lane_of(h), 0)
drop_lane(h)

m9c, clock9c = manager(1, Rules(conversation_hold=120))
clock9c.set(0)
h = try_lane(m9c, "chat:Kira", Priority.CHAT, arrived=0)
clock9c.set(1)
drop_lane(h)
clock9c.set(2)
h = try_lane(m9c, "thought:Ida", Priority.LOW, arrived=2)
check("d) with only ONE lane the fresh chat lane is taken, never blocked",
      lane_of(h), 0)
drop_lane(h)

# e) the hold is against background work, not against the chat class
m9d, clock9d = manager(2, Rules(conversation_hold=120))
clock9d.set(0)
h = try_lane(m9d, "chat:Kira", Priority.CHAT, arrived=0)
clock9d.set(1)
drop_lane(h)                                 # lane 0: hot chat:Kira, idle@1
clock9d.set(2)
running = try_lane(m9d, "bg:runner", Priority.CHAT, arrived=2)
check("e) the runner holds lane 1", lane_of(running), 1)
clock9d.set(3)
check("e) a thought still waits for the running call",
      lane_of(try_lane(m9d, "thought:Ida", Priority.LOW, arrived=3)),
      "LaneTimeout")
check("e) free_lanes tells background work the same: no lane",
      m9d.free_lanes(POOL, "thought:Ida"), 0)
check("e) but it tells a CHAT caller the truth — one lane",
      m9d.free_lanes(POOL, "chat:Vallerie", priority=Priority.CHAT), 1)
h = try_lane(m9d, "chat:Vallerie", Priority.CHAT, arrived=3)
check("e) a CHAT call takes the held lane at once — the hold is against "
      "background work", lane_of(h), 0)
drop_lane(h)
drop_lane(running)

# ... and it costs the conversation nothing while another free lane is older
m9e, clock9e = manager(2, Rules(conversation_hold=120))
clock9e.set(0)
h = try_lane(m9e, "bg:x", Priority.LOW, arrived=0)
clock9e.set(1)
drop_lane(h)                                 # lane 0: hot bg:x, idle@1
clock9e.set(2)
h = try_lane(m9e, "chat:Kira", Priority.CHAT, arrived=2)
check("e) the conversation ran on the never-used lane", lane_of(h), 1)
clock9e.set(3)
drop_lane(h)                                 # lane 1: hot chat:Kira, idle@3
clock9e.set(4)
h = try_lane(m9e, "chat:Vallerie", Priority.CHAT, arrived=4)
check("e) and a later chat takes the OLDER foreign lane, not the fresh "
      "conversation", lane_of(h), 0)
drop_lane(h)

# f) the caller's own, just released lane comes back to it (R1 step 1)
m9f, clock9f = manager(2, Rules(conversation_hold=120))
clock9f.set(0)
own = try_lane(m9f, "chat:Kira", Priority.CHAT, arrived=0)
check("f) the turn holds lane 0", lane_of(own), 0)
clock9f.set(1)
running = try_lane(m9f, "bg:runner", Priority.CHAT, arrived=1)
check("f) a foreign call holds lane 1", lane_of(running), 1)
clock9f.set(2)
drop_lane(own)                               # R6: the turn hands lane 0 back
clock9f.set(3)
check("f) without its lane id R4 protects the turn against its own tool "
      "call", lane_of(try_lane(m9f, "tool:Kira", Priority.LOW, arrived=3)),
      "LaneTimeout")
h = try_lane(m9f, "tool:Kira", Priority.LOW, arrived=3, own_lane=0)
check("f) with its own lane id it gets exactly that lane back", lane_of(h), 0)
drop_lane(h)
drop_lane(running)

# ── [10] the timings come from the config, live ────────────────────────────
print("\n[10] the three timings are config, read live")
from app.core import config  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402

_schema = SECTIONS["lanes"]["fields"]
check("the schema default matches the code default (affinity wait)",
      _schema["affinity_wait_seconds"]["default"],
      int(configured_lane_rules().affinity_wait))
check("the schema default matches the code default (conversation hold)",
      _schema["conversation_hold_seconds"]["default"],
      int(configured_lane_rules().conversation_hold))
check("the schema default matches the code default (wait upgrade)",
      _schema["wait_upgrade_seconds"]["default"],
      int(configured_lane_rules().wait_upgrade))
check("with no config at all the documented defaults apply",
      (configured_lane_rules().affinity_wait,
       configured_lane_rules().conversation_hold,
       configured_lane_rules().wait_upgrade),
      (3.0, 120.0, 60.0))

# A manager WITHOUT an injected rules callable — it reads the config like the
# server does. The clock stays where it is; only the config changes.
m10 = LaneManager(now=Clock(), lane_count=lambda _key: 2)
config._CONFIG["lanes"] = {"affinity_wait_seconds": 1000,
                           "conversation_hold_seconds": 0,
                           "wait_upgrade_seconds": 60}
check("the config value is what the manager reads",
      configured_lane_rules().affinity_wait, 1000.0)
h = try_lane(m10, "chat:Kira", Priority.CHAT, arrived=0)
drop_lane(h)
h = try_lane(m10, "chat:Bo", Priority.CHAT, arrived=0)
drop_lane(h)                     # both lanes used, none fresh, none matching
check("a 1000 s affinity wait keeps a background call off both lanes",
      lane_of(try_lane(m10, "bg:x", Priority.LOW, arrived=0)), "LaneTimeout")
config._CONFIG["lanes"]["affinity_wait_seconds"] = 0
h = try_lane(m10, "bg:x", Priority.LOW, arrived=0)
check("the SAME call gets a lane once the config says 0 — no restart, no "
      "cached value", lane_of(h), 0)
drop_lane(h)
config._CONFIG.pop("lanes", None)

# ── [11] a waiter held back by R3/R4 blocks nobody — same class ────────────
print("\n[11] R2: a held-back waiter blocks nobody, not even its own class")
m11, clock11 = manager(2, Rules(conversation_hold=120))
clock11.set(0)
h = try_lane(m11, "chat:Kira", Priority.CHAT, arrived=0)
clock11.set(1)
drop_lane(h)                                 # lane 0: hot chat:Kira, idle@1
clock11.set(2)
running = try_lane(m11, "bg:runner", Priority.CHAT, arrived=2)
check("the foreign call holds lane 1", lane_of(running), 1)
clock11.set(3)
held_back = parked(m11, "thought:Ida", Priority.LOW, arrived=3)
check("the thought parks — R4 holds it off lane 0, lane 1 is running",
      wait_for_waiters(m11, 1), True)
clock11.set(4)
h = try_lane(m11, "tool:Kira", Priority.LOW, arrived=4, own_lane=0)
check("a younger call of the SAME class, with no key match, takes the lane "
      "the older one may not have", lane_of(h), 0)
check("the older parked call is still waiting", held_back.get("handle"), None)
clock11.set(5)
drop_lane(h)                                 # lane 0: hot tool:Kira — no chat
check("and is served once that lane is no longer a conversation",
      served(held_back), 0)
drop(held_back)
drop_lane(running)

# ── [12] R1 step 1: the caller's own lane, for every class ─────────────────
print("\n[12] R1: a free own_lane wins before everything else")


def mid_turn_pool():
    """Two conversations on two lanes, one of them in the middle of R6.

    All three timings are 0, so R1 alone decides. The clock ends at t=4:

      lane 0  hot chat:Vallerie, idle@1   the OTHER conversation, between
                                          turns — the older, LRU lane
      lane 1  hot chat:Kira,     idle@3   the turn's own lane, handed back a
                                          moment ago for its nested tool call

    Returns (manager, clock, own lane id).
    """
    mm, cc = manager(2)
    cc.set(0)
    other = try_lane(mm, "chat:Vallerie", Priority.CHAT, arrived=0)
    cc.set(1)
    drop_lane(other)
    cc.set(2)
    mine = try_lane(mm, "chat:Kira", Priority.CHAT, arrived=2)
    own_id = lane_of(mine)
    cc.set(3)
    drop_lane(mine)
    cc.set(4)
    return mm, cc, own_id


m12, clock12, own_id = mid_turn_pool()
check("the setup: the turn's own lane is lane 1", own_id, 1)
check("the setup: both lanes free, the neighbour's is the older one",
      [(x["lane_id"], x["hot_key"], x["age_s"])
       for x in m12.snapshot()["pools"][POOL]["lanes"]],
      [(0, "chat:Vallerie", 3.0), (1, "chat:Kira", 1.0)])
stray = try_lane(m12, "tool:Kira", Priority.CHAT, arrived=2)
check("WITHOUT own_lane the LRU step sends the tool call onto the other "
      "conversation's lane", lane_of(stray), 0)
drop_lane(stray)

for prio, name in ((Priority.CHAT, "CHAT"), (Priority.NORMAL, "NORMAL"),
                   (Priority.LOW, "LOW")):
    mm, cc, own_id = mid_turn_pool()
    h = try_lane(mm, "tool:Kira", prio, arrived=2, own_lane=own_id)
    check(f"{name}: the tool call gets its own lane back", lane_of(h), own_id)
    cc.set(5)
    drop_lane(h)                        # lane 1: hot tool:Kira, idle@5
    back = try_lane(mm, "chat:Kira", prio, arrived=2, own_lane=own_id)
    check(f"{name}: the resume takes it back too — its key is no longer hot "
          "there, and lane 0 is the LRU one", lane_of(back), own_id)
    check(f"{name}: the neighbour's lane was never touched",
          [x["hot_key"] for x in mm.snapshot()["pools"][POOL]["lanes"]],
          ["chat:Vallerie", "chat:Kira"])
    drop_lane(back)

# ── [13] R1 step 1 against a HIGHER class that is parked on the pool ───────
print("\n[13] R2: a parked higher class does not get the lane a running turn "
      "released for its own nested call")


def frozen(m):
    """The manager's own lock, so the two halves of a suspend are ONE step.

    ``suspend`` is a release immediately followed by an acquire. Between the
    two, a parked thread that the release woke could take the lane before the
    nested call has even asked — a race the scheduler decides, not a rule, and
    the check would report whichever thread won this time. Holding the lock
    across both halves puts the two calls into the same selection pass, which
    is the situation the rule is about: both in the waiting list, one answer.
    (The lock is re-entrant, so release/acquire inside work as usual.)
    """
    return m._cond


def suspended_turn():
    """A LOW thought turn on a ONE-lane pool, with a CHAT registration parked
    behind it, at the moment the turn hands its lane back (R6).

      t=0  thought:Ida (LOW)  takes lane 0 — the running turn
      t=1  chat:Kira  (CHAT)  parks: one lane, and it is busy
      t=2  the turn releases lane 0 for its own tool decision

    Returns (manager, clock, the parked box, the turn's lane id).
    """
    mm, cc = manager(1)
    cc.set(0)
    turn = try_lane(mm, "thought:Ida", Priority.LOW, arrived=0)
    own_id = lane_of(turn)
    cc.set(1)
    box = parked(mm, "chat:Kira", Priority.CHAT, arrived=1)
    wait_for_waiters(mm, 1)
    cc.set(2)
    return mm, cc, box, own_id, turn


# The negative control first: the very same situation WITHOUT own_lane. The
# parked CHAT outranks the LOW nested call, takes the lane the turn just gave
# back, and the turn waits for a whole foreign chat turn — with one lane and
# continuous chatting, until the 660 s stale sweep. If this line ever reads
# "0", the section below is passing for lack of a contest.
m13, clock13, box13, own13, turn13 = suspended_turn()
with frozen(m13):
    drop_lane(turn13)
    stray = try_lane(m13, "tool:Ida", Priority.LOW, arrived=0)
check("WITHOUT own_lane the parked CHAT takes the lane and the turn's tool "
      "call gets nothing", lane_of(stray), "LaneTimeout")
check("the parked CHAT really runs on it, mid-turn", served(box13), 0)
drop(box13)
drop_lane(stray)

m13, clock13, box13, own13, turn13 = suspended_turn()
with frozen(m13):
    drop_lane(turn13)
    tool = try_lane(m13, "tool:Ida", Priority.LOW, arrived=0, own_lane=own13)
check("the nested tool call gets the turn's own lane back, although a CHAT "
      "is parked on the pool", lane_of(tool), own13)
check("the parked CHAT is still waiting", box13.get("handle"), None)

clock13.set(3)
with frozen(m13):
    drop_lane(tool)                      # lane 0: hot tool:Ida
    back13 = try_lane(m13, "thought:Ida", Priority.LOW, arrived=0,
                      own_lane=own13)
check("and so does the RESUME — the turn goes on, it does not queue up behind "
      "the chat", lane_of(back13), own13)
check("the parked CHAT is still waiting", box13.get("handle"), None)

clock13.set(4)
drop_lane(back13)                        # the turn ends
check("the moment the turn ends, the parked CHAT is served — one turn's wait, "
      "which is the normal one", served(box13), 0)
drop(box13)


print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
