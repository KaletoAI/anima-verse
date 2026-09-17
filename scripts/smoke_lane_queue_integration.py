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

[8] After all of it: both pools fully free, nothing waiting. A lane that is
    busy here is a leak, and [1]-[6] are exactly the paths that can leak one.

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
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="lane-queue-clips-")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="lane-queue-storage-"))

from app.core import provider_manager as pm_mod  # noqa: E402
from app.core import provider_queue as pq_mod  # noqa: E402
from app.core.llm_lanes import get_lane_manager, pool_key_for  # noqa: E402
from app.core.llm_queue import Priority, get_llm_queue  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_manager import ProviderManager  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.utils import llm_logger, llm_stats  # noqa: E402

# Keep the JSONL log out of the repo's logs/ directory ...
llm_logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="lane-queue-logs-"))
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
    blocker = LANES.acquire_lane(POOL_A, "bg:blocker", timeout=0)
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
blocker = LANES.acquire_lane(POOL_A, "bg:blocker", timeout=0)
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

# ── [8] nothing leaked ─────────────────────────────────────────────────────
print("\n[8] no lane left behind")
for name, key in (("A", POOL_A), ("B", POOL_B)):
    snap = pool(key)
    check(f"pool {name}: every lane free",
          (snap["busy"], snap["waiting"]), (0, 0))
    check(f"pool {name}: the lane count is still one",
          snap["free"], 1)
check("no chat lane handle left", QUEUE._chat_lanes, {})

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
