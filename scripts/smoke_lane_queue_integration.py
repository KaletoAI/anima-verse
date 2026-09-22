#!/usr/bin/env python3
"""Integration check: cache lanes THROUGH the provider queue — no leaks.

Usage:
    ./.venv/bin/python scripts/smoke_lane_queue_integration.py

scripts/smoke_llm_lanes.py checks the lane manager on its own. This one checks
the two places that take a lane and have to give it back: the queue worker
(``ProviderQueue._worker_loop``) and the streaming registration
(``register_chat_active`` / ``register_chat_done``). Every leak this file
covers was a real finding of the phase-1 review — a lane that is never
released takes a model out of service for the lifetime of the process, and
nothing in the running system says so.

No config is loaded, so the three global lane timings are their defaults
(affinity wait 3 s, conversation hold 120 s, wait upgrade 60 s) and the clock
is the real one — this file measures the plumbing, not the assignment rules
(those are hand-derived on a stepped clock in smoke_llm_lanes.py). Where the
check itself takes a lane away to force a wait, it does so with CHAT priority:
the blocker is scaffolding and must not be held up by the affinity wait of R3.

Runs WITHOUT the server, without a world, without a DB and without a network:
the storage root is a temp dir, the LLM client is a stub whose ``invoke``
waits on an Event the check sets, the JSONL logger writes into a temp dir and
the two functions that would touch world.db (the duration estimate and the
stats recorder) are replaced by no-ops. Nothing sleeps for a rule: every wait
is a poll on a condition with a deadline, and the deadline only decides how
long the check is willing to wait for a thread, never what the right answer is.

THE RULES UNDER TEST (plan-cache-lanes.md § 3/§ 4, § 6 P1)

  * One pool per provider/model, ``max_concurrent`` lanes per pool. No config
    is loaded here, so every pool has exactly ONE lane — which is what makes
    "busy" and "free" below countable by hand.
  * A queued LLM task occupies a lane while it runs and releases it
    afterwards. It never runs unlaned.
  * Workers belong to the PROVIDER, lanes to the MODEL. A task whose pool is
    full therefore goes back into the queue instead of parking the worker —
    otherwise one busy model would stop every other model of the same provider.
  * A streaming registration takes a lane of the same pool and holds it until
    register_chat_done, whatever happens to its entry in between.

THE EXPECTATIONS, DERIVED BY HAND

[1] One queued task on model-a. The stub blocks inside invoke(), so while it
    runs the pool must show busy=1, free=0, and the lane's hot key must be
    the key of that call: task ``consolidation`` has no cache_class, so its
    class is ``bg``, the agent is Kira -> ``bg:Kira``. When the call returns,
    the lane goes back: busy=0, free=1.

[2] The channel has TWO worker threads (max_concurrent=2) and every pool
    still has ONE lane: workers belong to the provider, lanes to the model,
    and that difference is the whole point of this check. Three tasks in this
    order:
      T1  model-a, agent Kira      — blocks, holds the only lane of pool A
      T2  model-a, agent Vallerie  — a second key on the SAME pool, no lane
      T3  model-b, agent Ida       — a third pool, its lane is free
    Worker 1 is executing T1. Worker 2 pops T2, finds pool A full, and the
    question this check asks is what it does then. Expected: it puts T2 back
    and runs T3, which finishes WHILE T1 still holds its lane. A worker that
    waited for T2's lane instead would leave T3 sitting in the queue until T1
    is done — model-b stopped by a model it shares nothing with but the
    provider. T2 must not have started (pool A has one lane and T1 has it),
    and pool A must still show exactly one busy lane — putting T2 back must
    not have handed it a lane on the side. When T1 finishes, T2 runs.
    Chat pause is OFF on this queue, so the only thing that can hold T2 back
    is the lane.

[3] A streaming registration: register_chat_active takes a lane of its pool
    (task chat_stream, agent Kira -> key ``chat:Kira``), register_chat_done
    gives it back. busy=1 while registered, free=1 afterwards.

[4] Finding 1 — a CANCELLED register_chat_active_async must not lose a lane.
    The lane of pool A is held by the check, so the registration blocks in the
    thread pool. The caller is cancelled (this is what thoughts.py's
    wait_for(..., 600) does). The thread cannot be cancelled: it keeps
    waiting, and the moment the lane is free it registers. Nobody will ever
    call register_chat_done for that task_id — so the async wrapper has to do
    it itself. Expected: the caller sees CancelledError, and afterwards the
    pool is free again and no chat registration is left behind.

[5] Finding 3 — the stale check must not orphan a lane. Two halves:
    a) while a registration is still WAITING for its lane, there is nothing
       to clean up: the entry is only made once the lane is in hand, so a
       stale check that runs meanwhile (timeout set to 0 here, so everything
       it can see is stale) finds no entry, the waiting call is untouched,
       and when the lane is handed over the registration is IN THE BOOKS —
       the third part is what tells "there was nothing to clean up" apart
       from "it was cleaned up while it waited", which is the finding.
    b) once registered, a stale check DOES pop the entry — and the lane must
       still come back, because it is released by task_id and not through the
       entry that has just been thrown away.

[6] Finding F1 (second review) — a registration whose register_chat_done
    NEVER comes must not hold its lane forever, and not only where a
    serialize group is configured. The stale cleanup used to run in ONE
    place: the worker's chat-pause wait, which is entered only when
    _chat_pause_enabled is on (= the channel has a serialize group). This
    channel has NONE (chat_pause_enabled=False, serialize_group=""), which is
    the normal case and exactly where the bug lived: a registration whose SSE
    generator never ran its finally (browser reload during streaming) kept
    the model's only lane, so every later chat waited here forever and every
    queued task of that pool was deferred for good.
    The setup: one registration is made and then abandoned — no done call —
    and the stale timeout is set to 0, so it IS stale. A second registration
    (a new chat on the same model) is started in a thread; the pool has one
    lane, so it has to wait. Expected: it comes through by itself, because
    the waiting path runs the stale check between its wait slices; the
    abandoned entry is gone from the books and the second registration holds
    the lane with ITS key. Without the fix nothing ever runs the cleanup on
    this channel and the second registration never returns.
    The slice length is shortened for the check (_LANE_WAIT_WARN), which only
    decides how long the check runs — not what the right answer is. That the
    wait says so in the log is checked too: at least one ERROR line per slice.

[7] Finding F2 (second review) — the boot migration of the lane counts runs
    EXACTLY ONCE per world. The provider's max_concurrent stays where it is
    (it sizes the worker pool and is the GPU limit), so a migration that only
    asks "has this entry a value?" would copy the provider number onto every
    entry again on every boot — and an entry created later in the admin UI
    writes no max_concurrent, so a `tool` entry would come up with the
    provider's 4 lanes although § 10 of the plan keeps tool/vision at 1.
    Two boots over the same dict, no disk, no server:
      boot 1: provider P has max_concurrent=4. The enabled entry without a
              value gets 4, an entry with its own 2 keeps 2, a DISABLED entry
              is left alone (it describes no running pool), and an entry of
              another provider is not touched. The marker is set.
      boot 2: the admin has added a `tool` entry — enabled, no max_concurrent.
              The migration must do NOTHING: return False and leave the new
              entry without a value, which means one lane.
    A fresh world (no providers/llm_routing at all) still gets the marker, so
    the step is over for good there too.

[8] Item 7a — the rp_first TOOL CALL takes a lane of its own, and doing so on
    a ONE-LANE pool must not block the turn that is already holding that lane.
    The tool decision in streaming.py calls its LLM directly (to_thread +
    invoke), past the queue and, until now, past the lanes: on a one-model
    host that is a second prompt beginning on exactly the pool whose cache the
    running turn just filled. Giving it a lane is only half of it — the order
    is the other half (R6), and the order is what this section measures.
      a) A chat registration on model-a holds the ONE lane of pool A, with the
         key chat:Kira. Inside ``nested_call_lane`` the pool must still show
         exactly one busy lane, but its hot key must now be tool:Kira: the
         registration's lane was handed back first and the nested call took
         one for itself. The registration stays in the books (the queue panel
         keeps showing the turn) while holding no lane.
      b) The whole thing has to COMPLETE. It runs in a thread that is joined
         with a deadline; without the release-first order this is precisely
         where a one-lane pool waits for itself, forever. The deadline only
         bounds how long the check waits, it decides no expectation: a
         self-block never finishes, however long one waits.
      c) Afterwards the registration holds a lane again, with its own key
         back on it, and register_chat_done gives it back.
      d) A body that RAISES must not lose the chat lane either: the nested
         lane goes back and the registration gets one again, then the error
         reaches the caller.
      e) The REAL call site, not just the helper: StreamingAgent's tool
         decision is driven once with a stub that reports what the pool looks
         like from inside its invoke(). Expected there: one busy lane, hot key
         tool:Kira — the turn's own chat:Kira lane is suspended at that
         moment — and the chat key back on the lane when the decision returns.
      f) Round 3, finding 5 — the same call site with an EMPTY
         `chat_task_id`. No such caller exists today, and the guard is there
         so a new one is loud instead of stuck: with no registration id there
         is no owner to suspend, and asking for a second lane on this one-lane
         pool would be the turn waiting for itself. Expected: no lane is taken
         (inside the call the pool still shows the turn's own chat:Kira), the
         decision answers, and a WARNING names the character.

[9] Review of phase 2, blocker 1 — A NESTED CALL ON ANOTHER POOL COSTS THE
    CONVERSATION NOTHING. This is the normal topology, not a corner case: the
    chat model is one alias, the tool alias is another, and they are different
    hosts. The first version suspended the chat lane before it knew which pool
    the tool LLM was on, so the conversation's lane went to whoever was
    waiting — its prompt cache evicted, and the turn then waiting for that
    stranger to finish. Nothing was won, because the two calls never contend.
    Setup: a chat registration holds the one lane of pool A (key chat:Kira), a
    background call (thought:Ida, LOW) is parked on pool A, and the nested
    call runs with an LLM of model-b. Expected, read from INSIDE the nested
    call: pool B busy=1 with hot key tool:Kira, pool A busy=1 with hot key
    chat:Kira and its handle still in the books, and the parked background
    call still parked. Only after register_chat_done does it get the lane.

[10] Review of phase 2, blocker 2 — TWO LANES, THE OTHER ONE BUSY. Same pool
    this time, so R6 applies and the turn hands its lane back. The lane it
    gave back is a FREE lane whose hot key is a fresh chat — exactly what R4
    protects — while the second lane is busy with a foreign call. Protecting
    a conversation against its own tool call is the one case R4 must not
    cover: the nested call would wait for the stranger's lane and the turn
    would stall behind it. Expected: the nested call gets back the very lane
    the registration held (its id is read off the registration beforehand, so
    the check does not depend on which id the pool hands out), both lanes are
    busy while it runs, and afterwards the turn holds a lane again with
    chat:Kira on it while the foreign call keeps its own.
    The same section pins the arrival stamp (review finding 3): the turn's
    ``_lane_arrived`` is read before the nested call and must be UNCHANGED
    afterwards. Both the nested acquire and the resume hand that stamp back
    in, so the turn goes on ageing from when it first asked; stamping either
    of them fresh would make a turn the youngest waiter on its pool at every
    single suspend, and two turns on one pool would leapfrog each other.

[11] Review of phase 2, finding 4 — THE LANE PRIORITY FOLLOWS THE PROMPT
    CLASS. Every streaming registration is Priority.CHAT: the queue panel and
    the queue pause want that, the lanes must not have it, or the AgentLoop's
    thoughts would ignore R3 and rank level with a user's conversation in R2.
    The pool's one lane is made used, free and foreign for both calls
    (hot key chat:Bo); the affinity wait is set to 1000 s and the
    conversation hold to 0, so the ONLY thing that can hold a call off that
    lane is its own class. Expected: a registration of task `thought` parks
    (class thought -> LOW, R3 applies), a registration of `chat_stream` takes
    the same lane at once (class chat -> CHAT, R3 exempt), and the thought
    follows once the wait is set to 0. With the registration's panel priority
    the thought would take the lane straight away.
    b) Round 2, finding 4 — THE NESTED CALL INHERITS THE OWNER'S CLASS. The
    thought turn's tool call runs on pool B (another pool, so R6 does not
    apply and no own_lane is carried), whose one lane is used, free and
    foreign for the tool key. With the turn's LOW the affinity wait holds the
    call off it and it parks; with a hard-coded Priority.CHAT it would take
    the lane at once and, in R2, outrank a parked user conversation — the one
    thing the lane priority exists to prevent. It is served as soon as the
    wait is 0, so nothing is lost by inheriting.

[13] Review of phase 2, round 2, blocker 1 — THE NESTED CALL RESOLVES ITS
    POOL FROM THE LLM IT REALLY USES, not from the first channel.
    `StreamingAgent.tool_llm` is a client, not an `LLMInstance`; a resolution
    that reads an attribute the client does not have falls through to the
    FIRST channel — invisible in a one-channel world, wrong in the plan's own
    topology (AI-Hub + DX10-01).
    So this section adds a SECOND channel Q (its own api_base) while P stays
    the first one, and the turn runs on Q:
      a) same provider AND model as the turn (Q/model-q, one lane): the call
         must land on Q/model-q and the turn's lane must be suspended for it
         (pool Q busy=1 with hot key tool:Kira, the registration holding no
         handle). Resolved against P the pool key would read "P/model-q", the
         same-pool test would say "different" and nothing would be suspended
         — on this one-lane pool the call would then wait for the very lane
         its own turn holds.
      b) same provider, DIFFERENT model (Q/model-tool): another pool, so
         nothing is suspended and the conversation keeps its lane. That is
         the normal topology, and it is the half that must NOT change.
      c) an endpoint no provider serves: the lane is still taken, but under
         the explicitly unknown key "?/model-nowhere". Nothing is suspended,
         because an unknown pool can never equal the turn's.
    And afterwards: the pools this section created are exactly Q/model-q,
    Q/model-tool and ?/model-nowhere. No "P/..." key may appear — a pool for a
    provider/model pair that no channel serves is a phantom in the admin view.
      d) Round 3, finding 2 — WHAT THE ROUTER BUILDS SAYS WHICH PROVIDER IT
         IS. The endpoint match of (a)-(c) is the fallback for an object that
         did not come from the router, and its limit is in its nature: it
         returns the FIRST provider on that URL, and several providers on one
         AI-Hub URL (one per alias or key) cannot be told apart by endpoint at
         all. So `LLMInstance.create_llm()` stamps its provider name on the
         client and `provider_name_for` reads that first. Measured with a
         second provider Q2 on Q's endpoint: a client the router built from Q2
         answers "Q2", while the same probe without a stamp answers "Q" — the
         first one on that URL.

[14] Review of phase 2, round 2, finding 3 — TWO CONVERSATIONS ON TWO LANES
    DO NOT EVICT EACH OTHER. Two lanes is the user's start value, so this is
    the normal case, not a corner one. Both conversations have had a turn, so
    each has a lane with its key on it; then four turns alternate, each one
    an rp_first turn that gives its lane back for its tool call and takes one
    again (R6). Counted over those four turns: 8 acquisitions of the
    speaker's key (the registration and the resume after the nested call),
    and every one of them must land on the lane that already carries that
    key — 8 hits, 0 evictions, where an eviction is the neighbour's key
    disappearing from the pool. Without R1's own-lane step the LRU step
    decides both the nested call and the resume, and the LRU lane is the
    neighbour's: every turn evicts the other conversation and the whole
    mechanism is worse than no lanes at all.

[15] After all of it: both pools fully free, nothing waiting. A lane that is
    busy here is a leak, and [1]-[6] and [8]-[11], [13]-[14] are exactly the
    paths that can leak one.

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
# a storage root every world access raises StorageNotInitialised — there is no
# default world any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = scratch("lane-queue-clips-")

from app.core import paths  # noqa: E402

paths.init(scratch("lane-queue-storage-"))

from app.core import provider_manager as pm_mod  # noqa: E402
from app.core import provider_queue as pq_mod  # noqa: E402
from app.core.llm_lanes import get_lane_manager, pool_key_for  # noqa: E402
from app.core.llm_queue import Priority, get_llm_queue  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_manager import ProviderManager  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.utils import llm_logger, llm_stats  # noqa: E402

# Keep the JSONL log out of the repo's logs/ directory ...
llm_logger.LOG_DIR = Path(scratch("lane-queue-logs-"))
llm_logger.LOG_FILE = llm_logger.LOG_DIR / "llm_calls.jsonl"
# ... and both DB users out of the run entirely. Neither has anything to do
# with lanes; both would open a SQLite file.
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
    """True as soon as ``predicate()`` holds. The timeout only bounds how long
    the check waits for a thread — it never decides an expectation."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class StubResponse:
    """What the stub LLM answers. Short on purpose: an answer of 0 estimated
    tokens keeps even the stats recorder out of the picture."""

    def __init__(self, content="ok"):
        self.content = content
        self.finish_reason = "stop"


class StubLLM:
    """An LLM client that does not call anything. ``invoke`` reports that it
    started and then waits for the Event the check controls, so the check
    decides exactly how long a call occupies its lane."""

    def __init__(self, model, gate=None):
        self.model = model
        self.model_name = model
        self.max_tokens = 0
        self.openai_api_base = "http://stub"
        self.started = threading.Event()
        self._gate = gate if gate is not None else threading.Event()
        if gate is None:
            self._gate.set()

    def release(self):
        self._gate.set()

    def invoke(self, messages):
        self.started.set()
        self._gate.wait(timeout=20)
        return StubResponse()


def stub_provider(name="P"):
    p = Provider(name=name, type="openai", api_base="http://stub",
                 api_key="", max_concurrent=1, timeout=30)
    p.available = True
    return p


PROVIDER = stub_provider()
# Two workers, one lane per pool: a worker that parks on a full pool takes
# half the channel out of service, which is what [2] measures.
QUEUE = ProviderQueue(PROVIDER, queue_name="P", max_concurrent=2,
                      chat_pause_enabled=False, serialize_group="")

# A real ProviderManager carrying exactly this one channel: the streaming
# registration path goes through it (llm_queue -> provider_manager -> queue),
# so stubbing it away would skip half of what is under test.
MANAGER = ProviderManager()
MANAGER.providers["P"] = PROVIDER
MANAGER.channels["P"] = QUEUE
MANAGER._queues["P"] = QUEUE
pm_mod._provider_manager = MANAGER

LANES = get_lane_manager()
POOL_A = pool_key_for("P", "model-a")
POOL_B = pool_key_for("P", "model-b")

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def pool(pool_key):
    return LANES.snapshot()["pools"].get(
        pool_key, {"busy": 0, "free": 0, "waiting": 0, "lanes": []})


def submit_in_thread(task_type, priority, llm, agent):
    """Runs pq.submit() in its own thread — submit blocks until the result is
    there. Returns (thread, box) where box["done"] carries the result."""
    box = {}

    def run():
        try:
            box["result"] = QUEUE.submit(task_type, priority, llm, MESSAGES,
                                         agent_name=agent)
        except Exception as e:  # pragma: no cover - would be a failed check
            box["error"] = str(e)
        box["done"] = True

    t = threading.Thread(target=run, daemon=True, name=f"submit-{agent}")
    t.start()
    return t, box


# ── [0] the ground truth this check counts against ─────────────────────────
print("[0] one lane per pool (no config loaded)")
check("pool A has one lane", LANES.free_lanes(POOL_A), 1)
check("pool B has one lane", LANES.free_lanes(POOL_B), 1)
check("the channel runs two workers", QUEUE._worker_count(), 2)

# ── [1] a queued task takes a lane and gives it back ───────────────────────
print("\n[1] a queued task holds a lane while it runs")
llm1 = StubLLM("model-a", gate=threading.Event())
t1, box1 = submit_in_thread("consolidation", Priority.LOW, llm1, "Kira")
check("the call started", llm1.started.wait(timeout=5), True)
check("the pool is busy while it runs",
      (pool(POOL_A)["busy"], pool(POOL_A)["free"]), (1, 0))
check("the lane carries the call's key",
      [x["hot_key"] for x in pool(POOL_A)["lanes"]], ["bg:Kira"])
llm1.release()
t1.join(timeout=10)
check("the caller got its answer", box1.get("result").content, "ok")
check("the lane is free again",
      wait_until(lambda: pool(POOL_A)["busy"] == 0), True)

# ── [2] a full pool re-queues, it does not park the worker ─────────────────
print("\n[2] a full pool does not park a worker")
llm_a1 = StubLLM("model-a", gate=threading.Event())   # holds pool A
t_a1, box_a1 = submit_in_thread("consolidation", Priority.LOW, llm_a1, "Kira")
check("T1 runs on pool A", llm_a1.started.wait(timeout=5), True)

llm_a2 = StubLLM("model-a")                            # returns at once
llm_b = StubLLM("model-b")                             # third pool, free lane
t_a2, box_a2 = submit_in_thread("consolidation", Priority.LOW, llm_a2,
                                "Vallerie")
# Give T2 a head start so it really is the head of the queue when T3 arrives.
time.sleep(0.05)
t_b, box_b = submit_in_thread("consolidation", Priority.LOW, llm_b, "Ida")

check("T3 (other pool) runs to the end while T1 holds pool A",
      wait_until(lambda: box_b.get("done") is True), True)
check("T1 is still running", box_a1.get("done"), None)
check("T2 never started — pool A has no lane for it",
      llm_a2.started.is_set(), False)
check("pool A still shows exactly one busy lane",
      (pool(POOL_A)["busy"], pool(POOL_A)["free"]), (1, 0))
check("pool B is free again after T3",
      wait_until(lambda: pool(POOL_B)["busy"] == 0), True)

llm_a1.release()
t_a1.join(timeout=10)
check("T2 runs as soon as the lane is free",
      llm_a2.started.wait(timeout=5), True)
t_a2.join(timeout=10)
check("both queued calls answered",
      (box_a1.get("result").content, box_a2.get("result").content),
      ("ok", "ok"))
check("pool A is free after both",
      wait_until(lambda: pool(POOL_A)["busy"] == 0), True)

# ── [3] a streaming registration takes and returns a lane ──────────────────
print("\n[3] register_chat_active takes a lane, register_chat_done returns it")
tid = QUEUE.register_chat_active("Kira", model="model-a",
                                 task_type="chat_stream")
check("the registration holds a lane", pool(POOL_A)["busy"], 1)
check("with the chat key",
      [x["hot_key"] for x in pool(POOL_A)["lanes"]], ["chat:Kira"])
check("the handle is reachable by task_id", tid in QUEUE._chat_lanes, True)
QUEUE.register_chat_done(tid)
check("the lane is back", pool(POOL_A)["busy"], 0)
check("and so is the bookkeeping",
      (QUEUE._chat_tasks, QUEUE._chat_lanes), ({}, {}))

# ── [4] finding 1: a cancelled registration releases its lane ──────────────
print("\n[4] a cancelled register_chat_active_async does not lose its lane")
import asyncio  # noqa: E402  (only this section needs a loop)


async def cancelled_registration():
    blocker = LANES.acquire_lane(POOL_A, "bg:blocker", Priority.CHAT, timeout=0)
    pending = asyncio.create_task(get_llm_queue().register_chat_active_async(
        "Vallerie", llm_instance=StubLLM("model-a"), task_type="chat_stream"))
    # Wait until the registration is really queued on the pool — only then is
    # cancelling it the race the finding describes.
    for _ in range(500):
        if pool(POOL_A)["waiting"] == 1:
            break
        await asyncio.sleep(0.01)
    queued = pool(POOL_A)["waiting"]
    pending.cancel()
    cancelled = False
    try:
        await pending
    except asyncio.CancelledError:
        cancelled = True
    # The thread is still waiting for the lane: hand it over.
    blocker.release()
    # The abandoned thread now takes the lane and registers. The lane keeps
    # its hot key after being released, so that is the durable proof that the
    # late registration really happened — and only then is a free pool proof
    # that the wrapper closed it again.
    registered = False
    for _ in range(1000):
        if [x["hot_key"] for x in pool(POOL_A)["lanes"]] == ["chat:Vallerie"]:
            registered = True
            break
        await asyncio.sleep(0.01)
    free_again = False
    for _ in range(1000):
        if pool(POOL_A)["busy"] == 0 and not QUEUE._chat_tasks:
            free_again = True
            break
        await asyncio.sleep(0.01)
    return queued, cancelled, registered, free_again


_queued, _cancelled, _registered, _free = asyncio.run(cancelled_registration())
check("the registration waited for the lane", _queued, 1)
check("the caller sees CancelledError", _cancelled, True)
check("the abandoned registration went through anyway", _registered, True)
check("and released its lane by itself", _free, True)
check("no chat registration is left behind", QUEUE._chat_tasks, {})

# ── [5] finding 3: the stale check does not orphan a lane ──────────────────
print("\n[5] the stale check cannot orphan a lane")
blocker = LANES.acquire_lane(POOL_A, "bg:blocker", Priority.CHAT, timeout=0)
reg = {}


def register():
    reg["id"] = QUEUE.register_chat_active("Ida", model="model-a",
                                           task_type="chat_stream")


t_reg = threading.Thread(target=register, daemon=True, name="register")
t_reg.start()
check("the registration waits for the lane",
      wait_until(lambda: pool(POOL_A)["waiting"] == 1), True)

QUEUE._STALE_CHAT_TIMEOUT = 0   # everything the check can see is stale now
QUEUE._check_stale_chat()
check("a) it sees no entry while the lane is still being handed out",
      QUEUE._chat_tasks, {})
check("a) and the waiting call is untouched", pool(POOL_A)["waiting"], 1)

blocker.release()
t_reg.join(timeout=10)
check("the registration went through", bool(reg.get("id")), True)
check("a) and is in the books, not swept away while it waited",
      reg.get("id") in QUEUE._chat_tasks, True)
check("it holds the lane", pool(POOL_A)["busy"], 1)

QUEUE._check_stale_chat()
check("b) the stale check removed the entry", QUEUE._chat_tasks, {})
check("b) and the lane came back with it", pool(POOL_A)["busy"], 0)
del QUEUE._STALE_CHAT_TIMEOUT

# ── [6] F1: a stuck registration is reclaimed without a serialize group ────
print("\n[6] a registration whose done never comes gives its lane back")
# The wait slice of _acquire_chat_lane IS the stale-check interval. 60 s is
# right in production and useless in a check, so shorten it — the length only
# bounds how long this check runs, never what the right answer is.
_REAL_WAIT_SLICE = pq_mod._LANE_WAIT_WARN
pq_mod._LANE_WAIT_WARN = 0.25

# Count the ERROR lines the wait writes: a wait that lasts must stay visible.
import logging  # noqa: E402


class _ErrorCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.count = 0

    def emit(self, record):
        self.count += 1


_errors = _ErrorCounter()
pq_mod.logger.addHandler(_errors)

stuck = QUEUE.register_chat_active("Kira", model="model-a",
                                   task_type="chat_stream")
check("the abandoned registration holds the lane", pool(POOL_A)["busy"], 1)
# Nobody will ever call register_chat_done for `stuck` — the SSE generator's
# finally did not run. Age it past the limit:
QUEUE._STALE_CHAT_TIMEOUT = 0
check("this channel has no serialize group and no chat pause",
      (QUEUE.serialize_group, QUEUE._chat_pause_enabled), ("", False))

second = {}


def register_second():
    second["id"] = QUEUE.register_chat_active("Vallerie", model="model-a",
                                              task_type="chat_stream")


t_second = threading.Thread(target=register_second, daemon=True,
                            name="second-chat")
t_second.start()
check("the next chat has to wait for the lane",
      wait_until(lambda: pool(POOL_A)["waiting"] == 1), True)
t_second.join(timeout=10)
check("it comes through anyway — the wait ran the stale check",
      bool(second.get("id")), True)
check("the stuck registration is gone from the books",
      stuck in QUEUE._chat_tasks, False)
check("and so is its lane handle", stuck in QUEUE._chat_lanes, False)
check("the lane now carries the new chat's key",
      [x["hot_key"] for x in pool(POOL_A)["lanes"]], ["chat:Vallerie"])
check("the long wait was logged", _errors.count >= 1, True)

pq_mod.logger.removeHandler(_errors)
QUEUE._STALE_CHAT_TIMEOUT = ProviderQueue._STALE_CHAT_TIMEOUT
pq_mod._LANE_WAIT_WARN = _REAL_WAIT_SLICE
if second.get("id"):
    QUEUE.register_chat_done(second["id"])
check("the pool is free again after the second chat", pool(POOL_A)["busy"], 0)

# ── [7] F2: the lane migration runs exactly once ───────────────────────────
print("\n[7] the boot migration of the lane counts runs once")
from app.core.config import _migrate_entry_lanes  # noqa: E402

world = {
    "providers": [
        {"name": "P", "max_concurrent": 4},
        {"name": "Other", "max_concurrent": 8},
    ],
    "llm_routing": [
        {"provider": "P", "model": "chat-model"},
        {"provider": "P", "model": "own-value", "max_concurrent": 2},
        {"provider": "P", "model": "off-model", "enabled": False},
        {"provider": "Other", "model": "x", "enabled": True},
    ],
}
check("boot 1 changes something", _migrate_entry_lanes(world), True)
lanes = {e["model"]: e.get("max_concurrent") for e in world["llm_routing"]}
check("the enabled entry without a value got the provider's number",
      lanes["chat-model"], 4)
check("an entry with its own value keeps it", lanes["own-value"], 2)
check("a disabled entry is left alone", lanes["off-model"], None)
check("the other provider's entry got ITS number", lanes["x"], 8)
check("the marker is set", world.get("llm_lanes_migrated"), True)

# Boot 2: the admin added a tool entry meanwhile — enabled, no lane count.
world["llm_routing"].append({"provider": "P", "model": "tool", "enabled": True})
check("boot 2 changes nothing", _migrate_entry_lanes(world), False)
lanes2 = {e["model"]: e.get("max_concurrent") for e in world["llm_routing"]}
check("the new tool entry stays at one lane (no value)", lanes2["tool"], None)
check("and nothing else moved either",
      (lanes2["chat-model"], lanes2["own-value"], lanes2["off-model"]),
      (4, 2, None))

fresh: dict = {}
check("a fresh world gets the marker too", _migrate_entry_lanes(fresh), True)
check("and nothing else", fresh, {"llm_lanes_migrated": True})
check("a second run over it does nothing", _migrate_entry_lanes(fresh), False)

# ── [8] item 7a: the nested tool call takes a lane, without self-blocking ──
print("\n[8] the rp_first tool call gets its own lane (R6 order)")
_REAL_WAIT_SLICE = pq_mod._LANE_WAIT_WARN
# A self-block would wait in 60-s slices; shorten them so this check ends in
# seconds either way. The length never decides the answer — a self-block does
# not end, it only gets slower to notice.
pq_mod._LANE_WAIT_WARN = 0.25

chat_tid = QUEUE.register_chat_active("Kira", model="model-a",
                                      task_type="chat_stream")
check("the turn holds the only lane of pool A",
      (pool(POOL_A)["busy"], [x["hot_key"] for x in pool(POOL_A)["lanes"]]),
      (1, ["chat:Kira"]))

inside = {}


def nested_call():
    try:
        with get_llm_queue().nested_call_lane(
                chat_tid, StubLLM("model-a"), "tool:Kira",
                label="tool_decision") as handle:
            inside["laned"] = handle is not None
            inside["busy"] = pool(POOL_A)["busy"]
            inside["hot"] = [x["hot_key"] for x in pool(POOL_A)["lanes"]]
            inside["registered"] = chat_tid in QUEUE._chat_tasks
            inside["chat_lane_held"] = chat_tid in QUEUE._chat_lanes
        inside["done"] = True
    except Exception as e:  # pragma: no cover - would be a failed check
        inside["error"] = str(e)


t_nested = threading.Thread(target=nested_call, daemon=True, name="tool-call")
t_nested.start()
t_nested.join(timeout=10)
check("b) the nested call thread ended — a self-block never does",
      t_nested.is_alive(), False)
check("b) the nested call completed — no self-block on a one-lane pool",
      inside.get("done"), True)
check("a) it ran ON a lane", inside.get("laned"), True)
check("a) still exactly one busy lane, not two", inside.get("busy"), 1)
check("a) and it is the tool call's lane, not the chat's",
      inside.get("hot"), ["tool:Kira"])
check("a) the registration stays in the books while suspended",
      (inside.get("registered"), inside.get("chat_lane_held")), (True, False))
check("c) afterwards the turn holds a lane again, with its own key",
      (pool(POOL_A)["busy"], [x["hot_key"] for x in pool(POOL_A)["lanes"]]),
      (1, ["chat:Kira"]))
check("c) and the handle is back in the books", chat_tid in QUEUE._chat_lanes,
      True)

raised = {}


def nested_call_that_raises():
    try:
        with get_llm_queue().nested_call_lane(
                chat_tid, StubLLM("model-a"), "tool:Kira"):
            raise RuntimeError("tool decision failed")
    except RuntimeError as e:
        raised["error"] = str(e)
    raised["done"] = True


t_raise = threading.Thread(target=nested_call_that_raises, daemon=True,
                           name="tool-call-raises")
t_raise.start()
t_raise.join(timeout=10)
check("d) the raising call's thread ended too", t_raise.is_alive(), False)
check("d) the error reaches the caller",
      (raised.get("done"), raised.get("error")),
      (True, "tool decision failed"))
check("d) and the turn has its lane back",
      (pool(POOL_A)["busy"], [x["hot_key"] for x in pool(POOL_A)["lanes"]]),
      (1, ["chat:Kira"]))

# e) the real call site: StreamingAgent._invoke_tool_decision
from app.core.streaming import StreamingAgent, _StreamState  # noqa: E402

seen = {}


class ProbeLLM(StubLLM):
    """Reports what the pool looks like from INSIDE the tool call."""

    def invoke(self, messages):
        seen["busy"] = pool(POOL_A)["busy"]
        seen["hot"] = [x["hot_key"] for x in pool(POOL_A)["lanes"]]
        return StubResponse("NONE")


probe = ProbeLLM("model-a")
agent = StreamingAgent(llm=probe, tool_format="tag", tools_dict={},
                       agent_name="Kira", tool_llm=probe, mode="rp_first",
                       chat_task_id=chat_tid)
state = _StreamState()


async def _decision():
    async for _event in agent._invoke_tool_decision(state, "sys", "user"):
        pass


async def drive_decision():
    """The real call site, with a DEADLINE.

    A self-block on this path does not fail, it hangs: the tool decision
    keeps yielding heartbeats while the acquire inside it waits for a lane
    the turn itself holds, so an unbounded run would leave the check sitting
    there with no output at all. 10 s is far past anything this file needs —
    it decides no expectation, it only turns a hang into a FAIL line.
    """
    try:
        await asyncio.wait_for(_decision(), 10)
        return True
    except asyncio.TimeoutError:
        return False


_drive = {}


def drive_in_thread():
    """...and the whole loop in a thread, with a deadline of its own.

    The timeout above is not enough on its own: the tool call runs in
    ``asyncio.to_thread``, and a cancelled wait_for does not end that thread —
    ``asyncio.run`` then blocks in its executor shutdown waiting for exactly
    the call that is stuck. Both deadlines together are what turns a
    self-block into a FAIL line; neither of them decides an expectation.
    """
    try:
        _drive["ok"] = asyncio.run(drive_decision())
    except Exception as e:  # pragma: no cover - would be a failed check
        _drive["error"] = str(e)


t_drive = threading.Thread(target=drive_in_thread, daemon=True,
                           name="tool-decision")
t_drive.start()
t_drive.join(timeout=20)
check("e) the real tool-decision path came back at all",
      (t_drive.is_alive(), _drive.get("ok")), (False, True))
if _drive.get("ok"):
    check("e) the real tool-decision path answered", state.response, "NONE")
    check("e) and it ran on a lane of its own, on the same one-lane pool",
          (seen.get("busy"), seen.get("hot")), (1, ["tool:Kira"]))
    check("e) the turn holds its lane again afterwards",
          (pool(POOL_A)["busy"], [x["hot_key"] for x in pool(POOL_A)["lanes"]]),
          (1, ["chat:Kira"]))
else:
    print("  [SKIP] e) the checks after it — the call site never returned")

# f) round 3, finding 5: an rp_first agent WITHOUT a registration id. There is
#    no owner to suspend, so asking for a second lane on this one-lane pool
#    would be the turn waiting for itself. The guard takes NO lane instead and
#    logs a WARNING; inside the call the turn's own lane is simply still
#    there, with its own key on it.
seen = {}
state = _StreamState()
agent = StreamingAgent(llm=probe, tool_format="tag", tools_dict={},
                       agent_name="Kira", tool_llm=probe, mode="rp_first",
                       chat_task_id="")
_drive = {}
t_drive = threading.Thread(target=drive_in_thread, daemon=True,
                           name="tool-decision-no-id")
t_drive.start()
t_drive.join(timeout=20)
check("f) without a registration id the decision came back — no self-block",
      (t_drive.is_alive(), _drive.get("ok")), (False, True))
if _drive.get("ok"):
    check("f) it answered", state.response, "NONE")
    check("f) it took no lane: the turn's own lane is untouched",
          (seen.get("busy"), seen.get("hot")), (1, ["chat:Kira"]))
else:
    print("  [SKIP] f) the checks after it — the call site never returned")

QUEUE.register_chat_done(chat_tid)
pq_mod._LANE_WAIT_WARN = _REAL_WAIT_SLICE
check("the pool is free after the turn", pool(POOL_A)["busy"], 0)

# ── [9] blocker 1: a nested call on ANOTHER pool costs no lane ─────────────
print("\n[9] a tool LLM on another pool does not suspend the conversation")
chat_tid = QUEUE.register_chat_active("Kira", model="model-a",
                                      task_type="chat_stream")
parked_bg = {}


def park_background():
    """A background call waiting for pool A — the one that would be handed
    the conversation's lane if it were suspended for nothing."""
    try:
        parked_bg["handle"] = LANES.acquire_lane(
            POOL_A, "thought:Ida", Priority.LOW, timeout=30)
    except Exception as e:  # pragma: no cover - would be a failed check
        parked_bg["error"] = str(e)


t_park = threading.Thread(target=park_background, daemon=True, name="bg-wait")
t_park.start()
check("a background call is waiting for pool A",
      wait_until(lambda: pool(POOL_A)["waiting"] == 1), True)

other = {}


def nested_on_other_pool():
    try:
        with get_llm_queue().nested_call_lane(
                chat_tid, StubLLM("model-b"), "tool:Kira",
                label="tool_decision") as handle:
            other["laned"] = handle is not None
            other["a_busy"] = pool(POOL_A)["busy"]
            other["a_hot"] = [x["hot_key"] for x in pool(POOL_A)["lanes"]]
            other["a_held"] = chat_tid in QUEUE._chat_lanes
            other["b_busy"] = pool(POOL_B)["busy"]
            other["b_hot"] = [x["hot_key"] for x in pool(POOL_B)["lanes"]]
            other["bg_served"] = parked_bg.get("handle") is not None
        other["done"] = True
    except Exception as e:  # pragma: no cover - would be a failed check
        other["error"] = str(e)


t_other = threading.Thread(target=nested_on_other_pool, daemon=True,
                           name="tool-call-b")
t_other.start()
t_other.join(timeout=10)
check("the nested call thread ended", t_other.is_alive(), False)
check("it completed", other.get("done"), True)
check("it ran on a lane of pool B", (other.get("laned"), other.get("b_busy"),
                                     other.get("b_hot")),
      (True, 1, ["tool:Kira"]))
check("pool A's lane still belongs to the conversation",
      (other.get("a_busy"), other.get("a_hot"), other.get("a_held")),
      (1, ["chat:Kira"], True))
check("and the waiting background call did NOT get it",
      other.get("bg_served"), False)
check("the turn still holds its lane afterwards",
      (pool(POOL_A)["busy"], chat_tid in QUEUE._chat_lanes), (1, True))

QUEUE.register_chat_done(chat_tid)
t_park.join(timeout=10)
check("the background call is served once the turn is over",
      parked_bg.get("handle") is not None, True)
if parked_bg.get("handle") is not None:
    parked_bg["handle"].release()
check("pool A is free again",
      wait_until(lambda: pool(POOL_A)["busy"] == 0), True)
check("pool B is free again",
      wait_until(lambda: pool(POOL_B)["busy"] == 0), True)

# ── [10] blocker 2: two lanes, the other one busy ──────────────────────────
print("\n[10] the nested call gets the turn's OWN lane, not the busy one")
from app.core import config  # noqa: E402

_saved_routing = config._CONFIG.get("llm_routing")
config._CONFIG["llm_routing"] = [
    {"provider": "P", "model": "model-a", "max_concurrent": 2},
]
LANES.sync_from_config(POOL_A)
check("pool A now has two lanes", pool(POOL_A)["free"], 2)

chat_tid = QUEUE.register_chat_active("Kira", model="model-a",
                                      task_type="chat_stream")
own_lane_id = QUEUE._chat_lanes[chat_tid].lane_id
foreign = LANES.acquire_lane(POOL_A, "chat:Bo", Priority.CHAT, timeout=0)
check("the turn holds one lane and a foreign call the other",
      (pool(POOL_A)["busy"], own_lane_id != foreign.lane_id), (2, True))
# When the turn first asked for a lane. It must still say the same afterwards:
# the nested call and the resume are the same call still, and a fresh stamp at
# every suspend would make a turn the youngest waiter on its pool over and
# over — two turns on one pool would leapfrog each other for good.
_arrived_before = QUEUE._chat_tasks[chat_tid]._lane_arrived

two = {}


def nested_two_lanes():
    try:
        with get_llm_queue().nested_call_lane(
                chat_tid, StubLLM("model-a"), "tool:Kira",
                label="tool_decision") as handle:
            two["lane"] = getattr(handle, "lane_id", None)
            two["busy"] = pool(POOL_A)["busy"]
        two["done"] = True
    except Exception as e:  # pragma: no cover - would be a failed check
        two["error"] = str(e)


t_two = threading.Thread(target=nested_two_lanes, daemon=True, name="tool-2")
t_two.start()
t_two.join(timeout=10)
check("the nested call thread ended — the turn did not stall",
      t_two.is_alive(), False)
check("it completed", two.get("done"), True)
check("it took the turn's OWN lane, not the busy foreign one",
      two.get("lane"), own_lane_id)
check("both lanes were busy while it ran", two.get("busy"), 2)
check("afterwards the turn holds a lane again with its own key",
      (chat_tid in QUEUE._chat_lanes,
       sorted(x["hot_key"] for x in pool(POOL_A)["lanes"])),
      (True, ["chat:Bo", "chat:Kira"]))
check("and it still ages from when it FIRST asked, not from the resume",
      QUEUE._chat_tasks[chat_tid]._lane_arrived, _arrived_before)

foreign.release()
QUEUE.register_chat_done(chat_tid)
if _saved_routing is None:
    config._CONFIG.pop("llm_routing", None)
else:
    config._CONFIG["llm_routing"] = _saved_routing
LANES.sync_from_config(POOL_A)
check("pool A is back to one free lane",
      (pool(POOL_A)["busy"], pool(POOL_A)["free"]), (0, 1))

# ── [11] finding 4: a thought registers as background work ─────────────────
print("\n[11] the lane priority follows the prompt class, not the surface")
_saved_lanes = config._CONFIG.get("lanes")
# R3 with a wait nothing here reaches, R4 switched off: the only thing that
# can hold a call off the one used, foreign lane is its own priority class.
config._CONFIG["lanes"] = {"affinity_wait_seconds": 1000,
                           "conversation_hold_seconds": 0,
                           "wait_upgrade_seconds": 0}
_hot = LANES.acquire_lane(POOL_A, "chat:Bo", Priority.CHAT, timeout=0)
_hot.release()     # the one lane is now used, free and FOREIGN for both calls
check("the pool's only lane is used and free",
      (pool(POOL_A)["free"], [x["hot_key"] for x in pool(POOL_A)["lanes"]]),
      (1, ["chat:Bo"]))


def register_in_thread(agent, task_type, box):
    """register_chat_active in its own thread. It is the one call here that
    WAITS without a timeout, so no expectation may be phrased as "it comes
    back" — a join with a deadline turns a wait that never ends into a FAIL
    line instead of a check that hangs with no output."""

    def run():
        try:
            box["id"] = QUEUE.register_chat_active(agent, model="model-a",
                                                   task_type=task_type)
        except Exception as e:  # pragma: no cover - would be a failed check
            box["error"] = str(e)

    t = threading.Thread(target=run, daemon=True, name=f"reg-{agent}")
    t.start()
    return t


thought_reg = {}
t_thought = register_in_thread("Ida", "thought", thought_reg)
check("a THOUGHT registration waits for its own lane (R3, class thought=LOW)",
      wait_until(lambda: pool(POOL_A)["waiting"] == 1), True)
check("it really has not registered", thought_reg.get("id"), None)

chat_reg = {}
t_chat = register_in_thread("Kira", "chat_stream", chat_reg)
t_chat.join(timeout=10)
check("the CHAT registration came back", t_chat.is_alive(), False)
if not t_chat.is_alive():
    check("it took the same foreign lane at once (class chat=CHAT, R3 exempt)",
          (bool(chat_reg.get("id")), pool(POOL_A)["busy"]), (True, 1))
    check("the thought is still waiting behind it", thought_reg.get("id"), None)
    check("and the lane carries the chat's key",
          [x["hot_key"] for x in pool(POOL_A)["lanes"]], ["chat:Kira"])
    QUEUE.register_chat_done(chat_reg["id"])
else:
    print("  [SKIP] the checks after it — the registration never returned")

config._CONFIG["lanes"]["affinity_wait_seconds"] = 0
LANES.reconfigure(POOL_A, 1)    # wakes the waiter so it re-reads the rules
t_thought.join(timeout=10)
check("once the affinity wait is 0 the thought is served",
      bool(thought_reg.get("id")), True)

# b) ... and the NESTED call of that turn inherits the same class. Pool B is
# the tool alias here (another pool, so R6 does not apply and no own_lane is
# carried), its one lane used, free and FOREIGN for the tool key. With the
# turn's LOW the affinity wait of R3 holds the call off it; with a hard-coded
# Priority.CHAT it would take the lane at once and outrank anything parked.
if thought_reg.get("id"):
    config._CONFIG["lanes"]["affinity_wait_seconds"] = 1000
    _hot_b = LANES.acquire_lane(POOL_B, "chat:Bo", Priority.CHAT, timeout=0)
    _hot_b.release()
    check("b) pool B's only lane is used, free and foreign",
          (pool(POOL_B)["free"], [x["hot_key"] for x in pool(POOL_B)["lanes"]]),
          (1, ["chat:Bo"]))
    _inherit: dict = {}

    def nested_from_thought():
        try:
            with get_llm_queue().nested_call_lane(
                    thought_reg["id"], StubLLM("model-b", gate=None),
                    "tool:Ida", label="tool_decision") as handle:
                _inherit["lane"] = getattr(handle, "lane_id", None)
            _inherit["done"] = True
        except Exception as e:  # pragma: no cover - would be a failed check
            _inherit["error"] = str(e)

    t_inherit = threading.Thread(target=nested_from_thought, daemon=True,
                                 name="nested-thought")
    t_inherit.start()
    check("b) the thought's tool call waits for pool B (class thought=LOW)",
          wait_until(lambda: pool(POOL_B)["waiting"] == 1), True)
    check("b) it really has no lane", _inherit.get("lane"), None)
    config._CONFIG["lanes"]["affinity_wait_seconds"] = 0
    LANES.reconfigure(POOL_B, 1)   # wakes it so it re-reads the rules
    t_inherit.join(timeout=10)
    check("b) once the wait is 0 it gets the lane",
          (t_inherit.is_alive(), _inherit.get("done"), _inherit.get("lane")),
          (False, True, 0))
    check("b) and it gave it back", pool(POOL_B)["busy"], 0)
    QUEUE.register_chat_done(thought_reg["id"])
if _saved_lanes is None:
    config._CONFIG.pop("lanes", None)
else:
    config._CONFIG["lanes"] = _saved_lanes
check("pool A is free again", pool(POOL_A)["busy"], 0)

# ── [13] round 2, blocker 1: the nested LLM has NO provider_name ──────────
print("\n[13] two channels: the nested call resolves its pool by endpoint")
PROVIDER_Q = Provider(name="Q", type="openai", api_base="http://stub-q",
                      api_key="", max_concurrent=1, timeout=30)
PROVIDER_Q.available = True
QUEUE_Q = ProviderQueue(PROVIDER_Q, queue_name="Q", max_concurrent=1,
                        chat_pause_enabled=False, serialize_group="")
MANAGER.providers["Q"] = PROVIDER_Q
MANAGER.channels["Q"] = QUEUE_Q
MANAGER._queues["Q"] = QUEUE_Q
POOL_Q = pool_key_for("Q", "model-q")
POOL_Q_TOOL = pool_key_for("Q", "model-tool")
POOL_NOWHERE = pool_key_for("", "model-nowhere")   # "?/model-nowhere"

check("P is still the first channel — the old fallback target",
      MANAGER.get_first_queue() is QUEUE, True)
_pools_before = set(LANES.snapshot()["pools"])


def q_llm(model):
    """A StubLLM on provider Q's ENDPOINT — what the rp_first tool decision
    really hands over: a bare LLMClient with an api_base and no
    provider_name."""
    llm = StubLLM(model, gate=None)
    llm.openai_api_base = PROVIDER_Q.api_base
    return llm


check("the probe LLM carries no provider_name, only its endpoint",
      (getattr(q_llm("model-q"), "provider_name", None),
       q_llm("model-q").openai_api_base), (None, "http://stub-q"))


def nested_probe(box, llm, task_id=None):
    """Runs one nested_call_lane in a thread and reports from inside it."""

    def run():
        try:
            with get_llm_queue().nested_call_lane(
                    task_id, llm, "tool:Kira", label="tool_decision") as handle:
                box["pool"] = getattr(handle, "pool_key", None)
                box["lane"] = getattr(handle, "lane_id", None)
                box["q_busy"] = pool(POOL_Q)["busy"]
                box["q_hot"] = [x["hot_key"] for x in pool(POOL_Q)["lanes"]]
                box["q_held"] = (task_id in QUEUE_Q._chat_lanes)
            box["done"] = True
        except Exception as e:  # pragma: no cover - would be a failed check
            box["error"] = str(e)

    t = threading.Thread(target=run, daemon=True, name="nested-probe")
    t.start()
    t.join(timeout=10)
    box["alive"] = t.is_alive()
    return box


# a) SAME provider and model as the turn -> the suspend has to happen, and on
#    pool Q. The tool LLM carries only its endpoint, so a resolution that
#    reads provider_name alone lands on the FIRST channel (P), compares
#    "P/model-q" against the turn's "Q/model-q", finds them different and
#    suspends nothing — on this one-lane pool the nested call would then wait
#    for the very lane the turn is holding.
q_tid = QUEUE_Q.register_chat_active("Kira", model="model-q",
                                     task_type="chat_stream")
check("a) the turn holds the one lane of pool Q",
      (pool(POOL_Q)["busy"], [x["hot_key"] for x in pool(POOL_Q)["lanes"]]),
      (1, ["chat:Kira"]))
same = nested_probe({}, q_llm("model-q"), q_tid)
check("a) the nested call came back at all", (same["alive"], same.get("done")),
      (False, True))
check("a) it ran on pool Q, not on the first channel's", same.get("pool"),
      POOL_Q)
check("a) the turn's lane was suspended for it",
      (same.get("q_busy"), same.get("q_hot"), same.get("q_held")),
      (1, ["tool:Kira"], False))
check("a) and the turn holds it again afterwards",
      (q_tid in QUEUE_Q._chat_lanes, pool(POOL_Q)["busy"]), (True, 1))

# b) SAME provider, DIFFERENT model -> another pool, so nothing is suspended.
diff = nested_probe({}, q_llm("model-tool"), q_tid)
check("b) the nested call came back", (diff["alive"], diff.get("done")),
      (False, True))
check("b) it ran on the tool model's own pool", diff.get("pool"), POOL_Q_TOOL)
check("b) the conversation kept its lane",
      (diff.get("q_busy"), diff.get("q_hot"), diff.get("q_held")),
      (1, ["chat:Kira"], True))

# c) an endpoint no provider serves -> an explicitly UNKNOWN pool. The lane is
#    still taken (on the fallback channel, something has to run the wait), but
#    not under a provider/model pair that no channel serves: naming the first
#    channel would invent "P/model-nowhere" and show it in the admin snapshot.
_nowhere = q_llm("model-nowhere")
_nowhere.openai_api_base = "http://nowhere"
unknown = nested_probe({}, _nowhere, q_tid)
check("c) the nested call came back", (unknown["alive"], unknown.get("done")),
      (False, True))
check("c) it ran under the unknown-pool key", unknown.get("pool"),
      POOL_NOWHERE)
check("c) an unknown pool is never 'the same pool' — nothing was suspended",
      (unknown.get("q_busy"), unknown.get("q_hot"), unknown.get("q_held")),
      (1, ["chat:Kira"], True))

QUEUE_Q.register_chat_done(q_tid)
_new_pools = set(LANES.snapshot()["pools"]) - _pools_before
check("only real pools (plus the named unknown one) were created",
      sorted(_new_pools), sorted({POOL_Q, POOL_Q_TOOL, POOL_NOWHERE}))
check("no phantom pool under the first channel's name",
      [k for k in _new_pools if k.startswith("P/")], [])
check("pool Q is free again", pool(POOL_Q)["busy"], 0)

# d) round 3, finding 2: the stamp beats the endpoint's first match. Q2 shares
#    Q's endpoint, which is the normal AI-Hub shape (one URL, several entries)
#    and the case the endpoint match cannot decide.
from app.core.llm_router import LLMInstance  # noqa: E402

PROVIDER_Q2 = Provider(name="Q2", type="openai", api_base=PROVIDER_Q.api_base,
                       api_key="stub-key", max_concurrent=1, timeout=30)
MANAGER.providers["Q2"] = PROVIDER_Q2
_stamped = LLMInstance(provider_name="Q2", model="model-q",
                       _provider=PROVIDER_Q2).create_llm()
check("d) the client the router builds carries its provider name",
      getattr(_stamped, "provider_name", None), "Q2")
check("d) provider_name_for reads the stamp",
      MANAGER.provider_name_for(_stamped), "Q2")
check("d) without a stamp only the endpoint is left, and it answers with the "
      "FIRST provider on that URL", MANAGER.provider_name_for(q_llm("model-q")),
      "Q")
del MANAGER.providers["Q2"]

# ── [14] round 2, finding 3: two conversations do not evict each other ────
print("\n[14] two conversations on two lanes, alternating rp_first turns")
_saved_routing = config._CONFIG.get("llm_routing")
config._CONFIG["llm_routing"] = [
    {"provider": "P", "model": "model-a", "max_concurrent": 2},
]
LANES.sync_from_config(POOL_A)
check("pool A has the user's start value of two lanes", pool(POOL_A)["free"], 2)


def lane_with_key(key):
    """The id of the free lane whose hot key is ``key``, or None."""
    for lane in pool(POOL_A)["lanes"]:
        if lane["hot_key"] == key and not lane["busy"]:
            return lane["lane_id"]
    return None


# Seed: both conversations have had one turn, so each has a lane of its own.
for _who in ("Vallerie", "Kira"):
    _seed = QUEUE.register_chat_active(_who, model="model-a",
                                       task_type="chat_stream")
    QUEUE.register_chat_done(_seed)
check("each conversation left a lane behind",
      sorted(x["hot_key"] for x in pool(POOL_A)["lanes"]),
      ["chat:Kira", "chat:Vallerie"])

hits = 0
evictions = 0
for speaker, neighbour in (("Kira", "Vallerie"), ("Vallerie", "Kira"),
                           ("Kira", "Vallerie"), ("Vallerie", "Kira")):
    want = lane_with_key(f"chat:{speaker}")
    tid = QUEUE.register_chat_active(speaker, model="model-a",
                                     task_type="chat_stream")
    if QUEUE._chat_lanes[tid].lane_id == want:
        hits += 1
    nested_probe({}, StubLLM("model-a", gate=None), tid)
    if QUEUE._chat_lanes.get(tid) is not None \
            and QUEUE._chat_lanes[tid].lane_id == want:
        hits += 1
    if lane_with_key(f"chat:{neighbour}") is None:
        evictions += 1
    QUEUE.register_chat_done(tid)

check("every turn and every resume landed on its own hot lane", hits, 8)
check("and no turn evicted the other conversation", evictions, 0)
check("both keys are still on the pool",
      sorted(x["hot_key"] for x in pool(POOL_A)["lanes"]),
      ["chat:Kira", "chat:Vallerie"])

if _saved_routing is None:
    config._CONFIG.pop("llm_routing", None)
else:
    config._CONFIG["llm_routing"] = _saved_routing
LANES.sync_from_config(POOL_A)
check("pool A is back to one free lane",
      (pool(POOL_A)["busy"], pool(POOL_A)["free"]), (0, 1))

# ── [15] nothing leaked ────────────────────────────────────────────────────
print("\n[15] no lane left behind")
for name, key in (("A", POOL_A), ("B", POOL_B)):
    snap = pool(key)
    check(f"pool {name}: every lane free",
          (snap["busy"], snap["waiting"]), (0, 0))
    check(f"pool {name}: the lane count is still one",
          snap["free"], 1)
check("no chat lane handle left", QUEUE._chat_lanes, {})

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
