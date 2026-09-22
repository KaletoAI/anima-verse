#!/usr/bin/env python3
"""AgentLoop against the cache lanes — the respond budget (item 8) and R5.

Usage:
    ./.venv/bin/python scripts/smoke_agent_loop_lanes.py

Covers phase 3 of development_instructions/plan-cache-lanes.md § 6:

  item 8  ``thoughts.max_parallel_responds`` is gone. The respond dispatcher
          starts as many turns as the RESPONDER'S LLM ENTRY has free lanes.
  item 9  R5: among the candidates that are due anyway, the loop prefers the
          one whose prompt is still sitting on a free lane of its entry.
          Tickets, cooldowns and eligibility keep deciding WHO is due — R5
          decides only the ORDER.

Runs WITHOUT the server, without a world DB and without a network: the
storage root is a throwaway temp world (removed at exit), the turn itself is
a stub that waits on an asyncio.Event, and the module gates of the loop
(_is_paused, _chat_llm_available, _is_respond_eligible, _is_agent_eligible,
_build_round_tickets) are monkeypatched. Everything the plan is about runs
for real: the dispatcher, ``_pop_next_respond``, ``_respond_lane_free``,
``_take_from_tickets``, ``_has_hot_lane`` and the real ``LaneManager``.

THE ENTRY EVERY TURN RUNS ON. No routing config is loaded here, so
``_respond_pool_of`` and ``_pool_for`` both resolve to the pool of the
unknown entry, ``?/?`` — that is the entry of this check, and its lane count
is set by hand (``reconfigure``). Section [0] pins it: if that fallback ever
changes, the sections below would be counting lanes of a pool nobody uses,
and this line says so instead.

Nothing here sleeps for a rule. A stub turn ends when the check sets its
event; every "wait" is a poll with a deadline, and the deadline only bounds
how long the check waits for the event loop, never what the right answer is.

THE EXPECTATIONS, DERIVED BY HAND

[1] THE BUDGET IS THE FREE LANES. An entry with TWO lanes, three obligatory
    bumps in three different rooms (so the per-room lock serializes nothing),
    and a stub turn that never returns on its own. A MANDATORY bump goes to
    the FRONT of the queue (``bump_respond``), so bumping A, B, C leaves the
    queue reading C, B, A. Expected: exactly TWO turns run and they are C and
    B, while A stays QUEUED — queued, not dropped (``_respond_queue`` still
    holds its name). C's stub is then released: expected, exactly one more
    turn starts, so all three run in the end. Both lists are read — the turns
    the dispatcher STARTED and the turns that ran — because they are not the
    same thing (see [3]).

    The stub never reaches an LLM and therefore never takes a lane — what
    holds the third turn back is the dispatcher's own count of the turns it
    has started (``_respond_pools``). That is the part that has to be right
    for a real turn too: a turn that was started a moment ago is still
    building its prompt and has not acquired its lane yet. Without that count
    the free-lane number would still read 2 on the next tick and the
    dispatcher would start a turn per tick until the first one acquires.

[2] NONE WHEN THERE IS NO LANE. Same shape, ONE lane, and the check itself
    holds it (an ordinary acquire, the shape a user's chat turn has). With
    the lane busy the dispatcher must start NOTHING, however long it ticks —
    the bump stays in the queue. The moment the lane is released, one turn
    starts. Without the lane check this is where an answer would be sent into
    a model that is already answering somebody else, evicting the prompt
    cache both turns need.

[3] NEVER TWICE FOR THE SAME CHARACTER. Two lanes, so the budget is not what
    decides here: one character, its turn running, and a second bump for the
    SAME character. Expected: the dispatcher hands exactly ONE turn to a
    worker while the first one runs (``_respond_active`` holds one task), the
    bump keeps its place in the queue, and after the first turn ends it runs
    — exactly twice in total, and never more than ONE of them at a time,
    although the entry would have had a lane for a second one. [1] is the
    counter-sample for the same measurement: there it reads 2.

    What is counted is what the DISPATCHER started, not what ran: the second
    worker would park on the per-room lock before reaching the turn, so a
    turn that must never have been started is invisible in the list of turns
    that ran. Without the guard the queue is emptied and a second worker
    exists — measured, with the guard removed, in a copy of the tree.

[4] R5 PREFERS THE HOT CANDIDATE AMONG EQUALS. Three eligible characters, in
    the ticket order [Kira, Vallerie, Ida], nobody on cooldown, one entry
    with two lanes.

    a) Nothing hot: the pick is Kira — the order the round already had. R5
       changes nothing when there is nothing to prefer.
    b) A lane is made hot for ``thought:Ida`` (a call with that key ran on it
       and gave it back). Expected pick: Ida, out of order, because that is
       the turn whose prompt beginning the backend still has.
    c) The ticket of the character that was passed over is NOT spent: after
       (b) the tickets still hold Vallerie, and the next pick is Vallerie —
       one hot candidate does not cost the others their turn.

[5] R5 NEVER MAKES ANYBODY DUE. The same setup, with Ida hot in all three
    shapes, and the expected pick is Kira every time — R5 is asked about the
    candidates that survived the existing filters, so it cannot reach Ida:
      a) Ida is not eligible (asleep, disabled, avatar) — the pick is Kira.
         Her ticket is NOT spent by this pick, and the tickets read
         ["Vallerie", "Ida"] afterwards: Ida's ticket sits BEHIND the first
         due name, and a ticket behind the first due name is only skipped,
         never taken away ([7] is about nothing else). The old serial walk
         stopped at Kira and never looked at Ida's ticket either, so this is
         the list it left behind too. Only a ticket in FRONT of the first due
         name is spent — measured in [7] as well.
      b) Ida is on the per-character cooldown (last real turn just now).
      c) Ida is running a respond turn (a character is never in two turns).
    d) is the other half of the same rule: the lane that carries Ida's key is
       BUSY. A key on a busy lane is not a lane anybody can have, so R5 has
       no preference and the order stands — pick Kira.

[6] NO STARVATION. Ida's lane stays hot for good, the round is refilled from
    the same three characters, and six picks are taken in a row. Expected:
    each character exactly TWICE — Ida first in each round, then Kira, then
    Vallerie. R5 reorders a round, it does not hand out extra turns, and the
    cold characters come up in their normal turn.

[7] A TICKET BEHIND THE FIRST DUE NAME IS NOT SPENT. The round
    [A, B, C, C, C] — C with three tickets, which is what importance 3 looks
    like — with C not due at the first pick and due from the second pick on,
    and no refill. Five picks. Expected: A, B, C, C, C. At the first pick the
    walk finds A due and C's tickets are behind it, so they are skipped and
    stay; from the second pick C is due and takes all three.

    That is the behaviour of the loop before R5, which returned at the first
    due name and judged later tickets only when it reached them. Spending
    every not-due ticket of the round instead reads A, B and then nothing:
    one instant of cooldown costs an importance-3 character its whole round.

    The counter-sample is in the same section and pins the other half of the
    rule: with C in FRONT, [C, C, C, A, B], its three tickets ARE spent at
    the first pick and it gets no turn even though it is due from the second
    pick on — that is what makes a character on cooldown come up less often
    instead of blocking the round, and it is what the loop always did.

[8] A REPLY THAT REALLY HOLDS ITS LANE STILL LEAVES ROOM FOR THE NEXT. Two
    lanes, and here the stub turn ACQUIRES the lane its real counterpart
    would acquire (``chat:<name>``, class CHAT) and holds it until the check
    releases it. A first reply is started and waits until it holds its lane;
    only THEN does the second bump arrive, in another room. Expected: the
    second reply starts and runs while the first one still holds its lane —
    two lanes, two replies.

    This is the case [1] cannot see. There the stub never takes a lane, so
    ``free_lanes`` is the full capacity on every tick and the two terms of
    ``_respond_lane_free`` cannot be told apart: ``min(free, capacity -
    starting)`` and ``free - starting`` give the same answer for every
    scenario in which nothing is ever held. Here they do not — with one lane
    held and one turn started, the first says min(1, 2-1) = 1 (start) and the
    second 1-1 = 0 (block) — and blocking is the production bug: on a
    two-lane entry the second reply of a scene would wait for the whole first
    one and a lane would stand empty.

[9] A QUEUED REPLY RESERVES ITS POOL (plan § 6 P5, item 13: "a reply always
    takes precedence"). A reply that waits for a lane is a POLLER — the
    dispatcher asks ``free_lanes`` twice a second and starts a turn when one
    is free, so it is never in ``pool.waiting`` and R2 cannot rank it against
    a thought that IS parked there. While it waits, the dispatcher therefore
    holds a RESERVATION on its pool: no lane, only the rule that a freed lane
    does not go to a lower class.

    What the MANAGER does with a reservation — the parked LOW that gets
    nothing, the same and the higher class that are untouched, the TTL, the
    refresh — is measured on a stepped clock in scripts/smoke_llm_lanes.py
    [14]. This section measures the DISPATCHER's half: that the claim exists
    while, and only while, a reply is waiting for a lane.

    One lane, held by a foreign chat (the shape of a user's turn), one
    obligatory bump:

      a) the dispatcher records ``no_lane`` and reserves the pool for
         ``chat:A`` with the class the reply carries (CHAT) and a holder the
         admin can read.
      b) IT IS REFRESHED. After 3.5 s of ticking — longer than
         RESERVATION_TTL_SECONDS — the claim is still there and still has
         nearly its full TTL left. A claim that was only made once would have
         run out in the meantime; that is what bounds a dispatcher that dies.
      c) THE REPLY REALLY TAKES THE LANE — that is the statement, and it is
         not the same as "a worker was started". The held lane is released
         while a LOW thought is parked on the pool, the dispatcher starts the
         turn, and the turn then spends 200 ms on its PROMPT BUILD before it
         asks for its lane (Stub.build_seconds). In the server that gap is the
         room lock, the perception stream, the prompt build and the queue
         worker — seconds of it. A check that ends at "the dispatcher launched
         a worker" reads green even when the reply loses its lane inside that
         gap, which is what a review measured: the claim was released when the
         turn STARTED, the release woke the parked thought, and the thought
         won in microseconds. So this section reads the outcome instead: the
         reply HOLDS the lane and the thought is still parked.
      d) THE CLAIM IS NOT RELEASED AT THE START — it is HANDED OVER to the
         turn (holder "respond turn"), read here inside the prompt build, and
         it ends by being CONSUMED by the reply's own call when that call
         takes the lane. The turn's finally drops whatever is left, for a turn
         that never reaches its call at all.
      e) THE OTHER TWO WAYS OUT: a queue entry that vanishes (the character
         became ineligible — an avatar takeover) and a dispatcher that stops
         ticking (pause switch, ``stop()``). Neither may leave a pool claimed.
      f) ONE REPLY'S CLAIM GOES WITHOUT TOUCHING THE OTHER'S. Everything in
         (d) and (e) empties the queue, and an empty queue drops every claim
         at once — so none of those lines can tell the per-name release
         apart from the blanket one. Here two replies wait on a one-lane
         entry, the first one starts and REALLY holds the lane, and the
         second one is still waiting: exactly one claim may be left, and it
         must be the second reply's.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import asyncio
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
# a storage root every world access raises StorageNotInitialised — there is no
# default world any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = scratch("agent-loop-lanes-clips-")

from app.core import paths  # noqa: E402

paths.init(scratch("agent-loop-lanes-storage-"))

from app.core import agent_loop as al  # noqa: E402
from app.core.llm_lanes import (  # noqa: E402
    LaneTimeout, cache_key_for, get_lane_manager,
)
from app.core.llm_queue import Priority  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402

FAILED = []
LANES = get_lane_manager()


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


# ── [0] the entry every turn of this check runs on ─────────────────────────
print("[0] both loops resolve the same LLM entry")
POOL = al._respond_pool_of("Kira")
check("the respond lane's entry is the unknown one (no routing config)",
      POOL, "?/?")
check("the thought loop resolves the same entry",
      al._pool_for(al._THOUGHT_TASK_TYPE, "Kira"), POOL)


# ── scaffolding ────────────────────────────────────────────────────────────

def set_lanes(count):
    """One entry with a known number of lanes, nothing hot, nothing held."""
    LANES.reset()
    LANES.reconfigure(POOL, count)


def hold_lane(cache_key, priority=Priority.CHAT):
    """Occupies a lane of the entry — the shape a running chat turn has."""
    return LANES.acquire_lane(POOL, cache_key, priority, timeout=0)


def make_hot(cache_key):
    """Runs a call with this key on a lane and gives the lane back: the key
    is now hot on a FREE lane, which is what R5 looks for."""
    hold_lane(cache_key).release()


class Stub:
    """One stubbed AgentLoop and everything this check measures on it.

    ``runs``     the names of the stub turns that really RAN, in order.
    ``started``  the names of the turns the DISPATCHER handed to a worker —
                 which is not the same list: a worker parks on the per-room
                 lock before it runs, so a turn that must never have been
                 started at all is invisible in ``runs`` and visible here.
    ``together`` per running turn, how many turns were running at that moment
                 (``_respond_active``, which the dispatcher fills before the
                 worker's coroutine gets to run). Its maximum is the
                 concurrency this check really observed — measured, not
                 inferred from timings.
    ``gate``     one asyncio.Event per character: its stub turn ends when the
                 check sets the event, so nothing here depends on a timer.
    ``holding``  one asyncio.Event per character, set once its stub turn
                 really holds its lane (only with ``take_lane``).

    ``lost``     the names whose stub turn asked for its lane and did NOT get
                 it — the outcome [9c] measures, and the one a check that only
                 counts started workers cannot see.

    ``take_lane`` makes the stub turn do the one thing a real reply does to
    the pool: acquire the lane of its own chat key and hold it for as long as
    the turn runs. Without it the pool is never occupied by a turn of this
    check, and a dispatcher that counted free lanes wrongly would still pass
    every scenario — see [8].

    ``build_seconds`` is the gap between the START of the turn and its LLM
    call: in the server that is the room lock, the perception stream and the
    prompt build, seconds of it. Nothing in this file needed it until [9],
    where the whole rule is decided inside exactly that gap — with a turn that
    takes its lane in the same instant it starts, a claim released at the
    start still looks fine.
    """

    def __init__(self, room_map, take_lane=False, build_seconds=0.0):
        self.loop = al.AgentLoop()
        self.runs = []
        self.started = []
        self.together = []
        self.gate = {}
        self.holding = {}
        self.held = {}
        self.lost = []
        self.take_lane = take_lane
        self.build_seconds = build_seconds
        self.loop._run_respond_turn = self._fake_turn
        self.loop._char_room_key = lambda name: room_map.get(name, "")
        self.loop._respond_worker = self._counting_worker
        self._worker = al.AgentLoop._respond_worker.__get__(self.loop)
        al._is_paused = lambda: False
        al._is_respond_eligible = lambda name: True
        al._chat_llm_available = lambda: True
        al._BOOT_GRACE_SECONDS = 0

    async def _counting_worker(self, name, payload):
        """The REAL worker, with a note of every start. Only the note is the
        check's; the room lock, the timeout and the bookkeeping below it are
        the production ones."""
        self.started.append(name)
        return await self._worker(name, payload)

    async def _fake_turn(self, name, respond):
        if self.take_lane:
            if self.build_seconds:
                await asyncio.sleep(self.build_seconds)
            try:
                # timeout=0: ONE attempt, exactly like the queue worker's. A
                # reply that does not get the lane its turn was started for is
                # recorded instead of raising, so the check reads the outcome
                # rather than a traceback.
                self.held[name] = LANES.acquire_lane(
                    POOL, cache_key_for(al._RESPOND_TASK_TYPE, name),
                    Priority.CHAT, timeout=0)
                self.holding.setdefault(name, asyncio.Event()).set()
            except LaneTimeout:
                self.lost.append(name)
        self.runs.append(name)
        self.together.append(len(self.loop._respond_active))
        self.gate.setdefault(name, asyncio.Event())
        try:
            await self.gate[name].wait()
        finally:
            handle = self.held.pop(name, None)
            if handle is not None:
                handle.release()
        return {"preview": f"stub {name}", "tools": [], "intents": [],
                "rp_response": ""}

    def holds(self, name):
        """True once this character's stub turn really holds its lane."""
        event = self.holding.setdefault(name, asyncio.Event())
        return event.is_set()

    def bump(self, *names):
        for name in names:
            self.loop.bump_respond(name, speaker="S", content="hi",
                                   obligatory=True)

    def run(self):
        return asyncio.create_task(self.loop._respond_dispatcher())


async def settle(ticks=20):
    """Lets the dispatcher run several of its own ticks — 2.4 s.

    That is deliberately longer than its longest nap: the dispatcher sleeps
    up to 1 s when its queue is EMPTY (which it is right after it started the
    turns) and 0.5 s when nothing may start. A shorter settle would let a
    "nothing was started" line pass because the dispatcher had not looked
    yet, which is no statement about any rule — and it really did: [3] read
    green with the double-start guard removed until this was 2.4 s.
    """
    for _ in range(ticks):
        await asyncio.sleep(0.12)


async def wait_for(predicate, timeout=5.0):
    """Polls until the predicate holds. Bounds only how long the check waits
    for the event loop — it decides no expectation."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


async def stop(stub, task):
    """Ends the dispatcher and every stub turn it started."""
    task.cancel()
    for event in stub.gate.values():
        event.set()
    for t in list(stub.loop._respond_active.values()):
        t.cancel()
    await asyncio.gather(task, *stub.loop._respond_active.values(),
                         return_exceptions=True)


# ── [1] the budget is the free lanes ───────────────────────────────────────
async def section_budget():
    print("\n[1] two lanes, three bumps: two turns run, the third waits")
    set_lanes(2)
    stub = Stub({"A": "loc/r1", "B": "loc/r2", "C": "loc/r3"})
    stub.bump("A", "B", "C")
    task = stub.run()
    await wait_for(lambda: len(stub.runs) >= 2)
    await settle()
    check("the dispatcher started exactly two turns",
          sorted(stub.started), ["B", "C"])
    check("and both of them run", sorted(stub.runs), ["B", "C"])
    check("the third bump is still queued, not dropped",
          stub.loop._respond_queue, ["A"])
    check("the dispatcher knows both running turns' entry",
          sorted(stub.loop._respond_pools.values()), [POOL, POOL])

    stub.gate["C"].set()                 # one turn ends -> one lane free
    await wait_for(lambda: len(stub.runs) >= 3)
    check("the freed lane starts the third turn", sorted(stub.runs),
          ["A", "B", "C"])
    check("the queue is empty", stub.loop._respond_queue, [])
    check("the finished turn released its entry",
          sorted(stub.loop._respond_pools), ["A", "B"])
    check("two turns really ran at the same time", max(stub.together), 2)
    await stop(stub, task)


# ── [2] no lane, no turn ───────────────────────────────────────────────────
async def section_no_lane():
    print("\n[2] one lane, held by somebody else: no turn starts at all")
    set_lanes(1)
    held = hold_lane("chat:Somebody")
    stub = Stub({"A": "loc/r1"})
    stub.bump("A")
    task = stub.run()
    await settle()
    check("the dispatcher started nothing", stub.started, [])
    check("no turn ran", stub.runs, [])
    check("the bump is still queued", stub.loop._respond_queue, ["A"])
    check("free_lanes says so too",
          LANES.free_lanes(POOL, cache_key_for(al._RESPOND_TASK_TYPE, "A"),
                           priority=Priority.CHAT), 0)
    check("and the status says WHY it waits",
          stub.loop.status()["respond_waiting"], {"A": "no_lane"})

    held.release()
    await wait_for(lambda: len(stub.runs) >= 1)
    check("the released lane starts the turn", stub.runs, ["A"])
    await stop(stub, task)


# ── [3] never two turns for one character ──────────────────────────────────
async def section_never_twice():
    print("\n[3] a character in a respond turn is never started twice")
    set_lanes(2)
    stub = Stub({"A": "loc/r1"})
    stub.bump("A")
    task = stub.run()
    await wait_for(lambda: len(stub.runs) >= 1)
    stub.bump("A")                       # a second utterance, same character
    await settle()
    check("the dispatcher started only the first turn", stub.started, ["A"])
    check("one running turn", list(stub.loop._respond_active), ["A"])
    check("the second bump waits in the queue",
          stub.loop._respond_queue, ["A"])
    check("and the status names the other reason",
          stub.loop.status()["respond_waiting"], {"A": "active"})

    stub.gate["A"].set()
    await wait_for(lambda: len(stub.runs) >= 2)
    check("it runs after the first turn ended", stub.runs, ["A", "A"])
    check("and never two at a time", max(stub.together), 1)
    check("the started turn left no reason behind",
          stub.loop.status()["respond_waiting"], {})
    await stop(stub, task)


# ── R5 scaffolding ─────────────────────────────────────────────────────────

ROUND = ["Kira", "Vallerie", "Ida"]


def thought_loop(eligible=None, tickets=None):
    """An AgentLoop whose round is exactly ``tickets``.

    ``_is_agent_eligible`` and the round refill are the two module functions
    the pick reads besides the lanes; everything else (cooldown, in-chat skip,
    respond-active) is loop STATE and is set through the instance, the way
    the running loop sets it.
    """
    loop = al.AgentLoop()
    names = list(ROUND if eligible is None else eligible)
    al._is_agent_eligible = lambda name: name in names
    al._build_round_tickets = lambda: list(ROUND)
    loop._tickets = list(ROUND if tickets is None else tickets)
    return loop


# ── [4] R5 prefers the hot candidate ───────────────────────────────────────
def section_r5_prefers():
    print("\n[4] R5 prefers the candidate whose prompt is on a free lane")
    set_lanes(2)
    loop = thought_loop()
    check("a) nothing hot: the round's own order decides",
          loop._pick_next_agent(), "Kira")

    set_lanes(2)
    loop = thought_loop()
    make_hot(cache_key_for(al._THOUGHT_TASK_TYPE, "Ida"))
    check("b) the hot candidate is picked out of order",
          loop._pick_next_agent(), "Ida")
    check("c) the candidate that was passed over kept its ticket",
          loop._tickets, ["Kira", "Vallerie"])
    check("c) and it is picked next", loop._pick_next_agent(), "Kira")


# ── [5] R5 never makes anybody due ─────────────────────────────────────────
def section_r5_never_due():
    print("\n[5] R5 picks only among the candidates that are due anyway")
    hot = cache_key_for(al._THOUGHT_TASK_TYPE, "Ida")

    set_lanes(2)
    loop = thought_loop(eligible=["Kira", "Vallerie"])
    make_hot(hot)
    check("a) an ineligible hot character is not picked",
          loop._pick_next_agent(), "Kira")
    check("a) and its ticket is only SKIPPED — it sits behind the first "
          "due name, exactly as before R5", loop._tickets,
          ["Vallerie", "Ida"])

    set_lanes(2)
    loop = thought_loop()
    make_hot(hot)
    loop._last_real_turn_at["Ida"] = utc_now()
    check("b) a hot character on cooldown is not picked",
          loop._pick_next_agent(), "Kira")

    set_lanes(2)
    loop = thought_loop()
    make_hot(hot)
    loop._respond_active["Ida"] = "a running respond turn"
    check("c) a hot character mid-respond is not picked",
          loop._pick_next_agent(), "Kira")

    set_lanes(2)
    loop = thought_loop()
    busy = hold_lane(hot, Priority.LOW)     # hot key, but the lane is BUSY
    check("d) a key on a BUSY lane is no preference",
          loop._pick_next_agent(), "Kira")
    busy.release()


# ── [6] no starvation ──────────────────────────────────────────────────────
def section_r5_no_starvation():
    print("\n[6] a cold character still gets its turn")
    set_lanes(2)
    loop = thought_loop()
    hot = cache_key_for(al._THOUGHT_TASK_TYPE, "Ida")
    picks = []
    for _ in range(6):
        make_hot(hot)          # Ida's lane stays hot for good
        picks.append(loop._pick_next_agent())
    check("two full rounds, in R5's order", picks,
          ["Ida", "Kira", "Vallerie", "Ida", "Kira", "Vallerie"])
    check("every character ran exactly twice",
          sorted(picks), sorted(ROUND * 2))


# ── [7] which tickets a pick spends ────────────────────────────────────────
def section_ticket_spend():
    print("\n[7] a ticket behind the first due name survives the pick")
    set_lanes(2)
    al._is_agent_eligible = lambda name: True
    al._build_round_tickets = lambda: []      # no refill: one round, five picks

    loop = al.AgentLoop()
    loop._tickets = ["A", "B", "C", "C", "C"]
    loop._last_real_turn_at["C"] = utc_now()  # C is not due at the first pick
    picks = []
    for step in range(5):
        picks.append(loop._pick_next_agent())
        if step == 0:
            loop._last_real_turn_at.pop("C", None)   # due from here on
    check("the importance-3 character keeps all three turns", picks,
          ["A", "B", "C", "C", "C"])

    loop = al.AgentLoop()
    loop._tickets = ["C", "C", "C", "A", "B"]
    loop._last_real_turn_at["C"] = utc_now()
    picks = []
    for step in range(5):
        picks.append(loop._pick_next_agent())
        if step == 0:
            loop._last_real_turn_at.pop("C", None)
    check("counter-sample: tickets IN FRONT of the first due name are spent",
          picks, ["A", "B", None, None, None])


# ── [8] a reply that really holds its lane ─────────────────────────────────
async def section_real_lane():
    print("\n[8] a held lane still leaves the second reply its own")
    set_lanes(2)
    stub = Stub({"A": "loc/r1", "B": "loc/r2"}, take_lane=True)
    stub.bump("A")
    task = stub.run()
    got_lane = await wait_for(lambda: stub.holds("A"))
    check("the first reply really holds a lane", got_lane, True)
    check("one of the two lanes is gone",
          LANES.free_lanes(POOL, cache_key_for(al._RESPOND_TASK_TYPE, "B"),
                           priority=Priority.CHAT), 1)

    stub.bump("B")                        # arrives AFTER the lane is held
    await wait_for(lambda: len(stub.runs) >= 2)
    # Every line below asks whether something HAPPENED, and the wait ends the
    # moment it has: both turns hold their lane. Nothing here says "and
    # nothing else started", so there is no negative that would need a wait
    # longer than the dispatcher's naps.
    await wait_for(lambda: LANES.free_lanes(
        POOL, cache_key_for(al._RESPOND_TASK_TYPE, "A"),
        priority=Priority.CHAT) == 0)
    check("the second reply runs on the other lane", sorted(stub.runs),
          ["A", "B"])
    check("both of them at the same time", max(stub.together), 2)
    check("and both really hold a lane",
          LANES.free_lanes(POOL, cache_key_for(al._RESPOND_TASK_TYPE, "A"),
                           priority=Priority.CHAT), 0)
    await stop(stub, task)


# ── [9] a queued reply reserves its pool ───────────────────────────────────

def park_thought(name="Ida"):
    """A LOW thought really parked in ``acquire_lane`` on the same pool — the
    caller the reservation exists for. Returns a box like the lane check's:
    ``handle`` fills the moment it is served.

    Its arrival is stamped a minute BACK on purpose. This check runs against
    the real config, where R3 holds a background call off a foreign lane for
    the first three seconds after it arrived — a fresh stamp would keep the
    thought off the freed lane all by itself, and the section below would read
    green without a reservation existing at all. An old arrival puts the
    thought where the rule is really decided: it may take that lane, and only
    the reply's claim stops it.
    """
    box = {}

    def run():
        try:
            box["handle"] = LANES.acquire_lane(
                POOL, cache_key_for(al._THOUGHT_TASK_TYPE, name),
                Priority.LOW, arrived=LANES.now() - 60, timeout=30)
        except Exception as e:  # pragma: no cover - a failed check
            box["error"] = str(e)

    box["thread"] = threading.Thread(target=run, daemon=True, name="park")
    box["thread"].start()
    return box


def claims():
    """The pool's reservations, as the admin payload carries them."""
    pool = LANES.snapshot()["pools"].get(POOL) or {}
    return pool.get("reservations", [])


async def gone(predicate, what):
    """A bounded wait for something to DISAPPEAR, and the answer.

    The states below are reached by a release, which is immediate: the claim
    is gone within a dispatcher tick or it is not going at all. The
    alternative — it merely EXPIRED — is seconds away (RESERVATION_TTL_SECONDS
    is 3 s, a turn's claim ten minutes), so a wait of well under a second
    cannot confuse the two. A fixed settle can: on a loaded machine its 2.4 s
    are longer than the TTL, and the check reads green for a claim nobody ever
    released.
    """
    ok = await wait_for(predicate, timeout=1.0)
    if not ok:
        print(f"    (waited 1.0 s in vain for: {what})")
    return ok


async def section_reservation():
    print("\n[9] a reply waiting for a lane reserves its pool")
    # The paused dispatcher naps _IDLE_SLEEP_SECONDS (30 s in the server).
    # Shortened here so the pause sub-check below measures the CLAIM and not
    # that nap; nothing else in this file pauses.
    al._IDLE_SLEEP_SECONDS = 0.2
    set_lanes(1)
    held = hold_lane("chat:Somebody")          # a user's turn holds the lane
    # THE TURN REALLY TAKES ITS LANE, and not before it has built its prompt:
    # that gap is where this whole rule is decided (see Stub.build_seconds).
    stub = Stub({"A": "loc/r1", "B": "loc/r2"}, take_lane=True,
                build_seconds=0.2)
    stub.bump("A")
    task = stub.run()
    await wait_for(lambda: bool(claims()))
    check("a) the reply is queued for want of a lane",
          stub.loop.status()["respond_waiting"], {"A": "no_lane"})
    check("a) and its pool is reserved for it",
          [(c["cache_key"], c["priority"], c["holder"]) for c in claims()],
          [(cache_key_for(al._RESPOND_TASK_TYPE, "A"), int(Priority.CHAT),
            "respond dispatcher")])

    # b) refreshed: after longer than the TTL the claim is still young. This
    # one really has to spend the time — the statement IS that the claim
    # outlives its own TTL.
    await asyncio.sleep(al_reservation_ttl() + 0.5)
    left = [c["expires_in_s"] for c in claims()]
    check("b) the claim survives longer than its own TTL", len(left), 1)
    check("b) because it is refreshed every tick — nearly the full TTL left",
          bool(left and left[0] > al_reservation_ttl() - 1.0), True)

    # c) the reply REALLY TAKES the freed lane, with a thought parked on it
    thought = park_thought()
    await wait_for(lambda: LANES.snapshot()["pools"][POOL]["waiting"] == 1)
    check("c) a LOW thought is really parked on the pool",
          LANES.snapshot()["pools"][POOL]["waiting"], 1)
    held.release()
    await wait_for(lambda: bool(stub.started))
    # The claim did NOT go when the turn started — it passed to the turn. The
    # window this is read in is the 200 ms of the prompt build.
    check("c) the claim passes to the turn, it is not released at the start",
          [(c["cache_key"], c["holder"]) for c in claims()],
          [(cache_key_for(al._RESPOND_TASK_TYPE, "A"), "respond turn")])
    got = await wait_for(lambda: stub.holds("A") or bool(stub.lost))
    check("c) the reply GETS the lane after its prompt build",
          (got, stub.holds("A"), stub.lost), (True, True, []))
    check("c) and the parked thought did not — it was there the whole time",
          (thought.get("handle"), LANES.snapshot()["pools"][POOL]["waiting"]),
          (None, 1))
    check("c) the reply's own call consumed the claim — nobody released it",
          claims(), [])
    check("d) nothing is left waiting in the AgentLoop either",
          (stub.loop._respond_queue, stub.loop.status()["respond_waiting"]),
          ([], {}))

    # e) a queue entry that vanishes
    stub.bump("B")
    await wait_for(lambda: bool(claims()))
    check("e) the second reply, with no lane, reserves the pool too",
          [c["cache_key"] for c in claims()],
          [cache_key_for(al._RESPOND_TASK_TYPE, "B")])
    al._is_respond_eligible = lambda name: name != "B"   # avatar takeover
    await gone(lambda: not claims(), "the dropped entry's claim")
    check("e) the entry is dropped", stub.loop._respond_queue, [])
    check("e) and its claim with it", claims(), [])
    al._is_respond_eligible = lambda name: True

    # e) a dispatcher that stops ticking: the pause switch ...
    stub.bump("B")
    await wait_for(lambda: bool(claims()))
    check("e) reserved again", len(claims()), 1)
    al._is_paused = lambda: True
    await gone(lambda: not claims(), "the paused dispatcher's claim")
    check("e) the pause switch lets the claim go", claims(), [])
    al._is_paused = lambda: False
    await wait_for(lambda: bool(claims()))
    check("e) and resuming takes it back", len(claims()), 1)

    # ... and stop()
    stub.loop._respond_task = task
    await stub.loop.stop()
    check("e) stop() leaves no claim behind", claims(), [])

    for handle in (thought.get("handle"),):
        if handle is not None:
            handle.release()
    await stop(stub, task)


async def section_reservation_release():
    print("\n[9f] the claim of the reply that starts goes, the other stays")
    set_lanes(1)
    held = hold_lane("chat:Somebody")
    # take_lane: the first reply really occupies the lane, so the second one
    # stays blocked and its claim has to survive the first one's start.
    stub = Stub({"A": "loc/r1", "B": "loc/r2"}, take_lane=True)
    stub.bump("B")
    stub.bump("A")                  # obligatory bumps go to the front: [A, B]
    task = stub.run()
    await wait_for(lambda: len(claims()) == 2)     # a POSITIVE: both claims
    check("f) both replies wait and each holds a claim",
          sorted(c["cache_key"] for c in claims()),
          ["chat:A", "chat:B"])

    held.release()
    await wait_for(lambda: stub.holds("A"))
    await settle()
    check("f) the first reply runs and holds the lane",
          (stub.runs, stub.holds("A")), (["A"], True))
    check("f) the second one still waits for a lane",
          stub.loop.status()["respond_waiting"], {"B": "no_lane"})
    check("f) and exactly its claim is left — the starter's is gone",
          [c["cache_key"] for c in claims()], ["chat:B"])
    await stop(stub, task)


def al_reservation_ttl():
    from app.core.llm_lanes import RESERVATION_TTL_SECONDS
    return RESERVATION_TTL_SECONDS


async def main():
    await section_budget()
    await section_no_lane()
    await section_never_twice()
    section_r5_prefers()
    section_r5_never_due()
    section_r5_no_starvation()
    section_ticket_spend()
    await section_real_lane()
    await section_reservation()
    await section_reservation_release()
    print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
