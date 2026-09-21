#!/usr/bin/env python3
"""Smoke run: what the provider queue HOLDS must always come back — and a
GPU job must be measured against the budget it really has.

Usage:
    ./.venv/bin/python scripts/smoke_provider_queue_release.py

Runs WITHOUT the server, without a world DB and without a network: the storage
root is a temp dir, the "backends" are fake callables, and the two functions
that would open world.db (the duration estimate and the stats recorder) are
replaced by no-ops. Nothing here sleeps for a rule; the one place that sleeps
(the watchdog section) sleeps 2 s and says why.

The four findings under test (review 2026-09-20)
---------------------------------------------------------------------------
LLM-1  A provider that fails its health probe during a reload loses its
       CHANNEL (``check_all_availability`` pops it) while its queue keeps
       running. Every handle lookup in the ProviderManager searched
       ``self.channels`` only, so the ``register_chat_done`` of a turn that
       was already streaming found nothing: its cache lane stayed busy for
       the lifetime of the process, the queue stayed paused, and every later
       chat on that model waited forever. The lookups belong on
       ``self._queues`` — the lifecycle view, which holds every queue ever
       built — and ``is_busy()`` has to count an open chat registration so
       ``_prune_queues`` cannot throw such a queue away either.
LLM-2  ``POST /queue/force-resume`` cleared ``_chat_tasks`` from outside,
       without releasing the cache lanes and without releasing a held
       serialize gate. The emergency exit left the system worse than the
       hang it was called for. It must use the queue's own release path.
IMG-2  The queue watchdog for a GPU task came from the backend's HTTP
       ``timeout`` (+30 s). A POLLING backend (mesh/video/civitai) sends its
       request in seconds and then polls: its budget is
       ``max_queue_wait + max_wait``. A 600-s video was declared dead after
       90 s, the finished MP4 was thrown away, and the healthy backend got a
       300-s cooldown because the watchdog failure carried no typed
       exception.
IMG-5b ``submit_gpu_task`` fell back to ``find_channel(api_type)`` when
       ``backend:<name>`` had no channel — so a globally disabled backend's
       job took ANOTHER backend's GPU slot while running against its own URL.

The expectations, derived by hand
---------------------------------------------------------------------------
[1] No config is loaded, so every lane pool has exactly ONE lane (that is
    what makes busy/free countable here).
    a) A chat registration on channel "P" takes that lane: busy=1.
    b) The provider's health probe says False and ``check_all_availability``
       runs, exactly as it does on every admin save: "P" is gone from
       ``channels`` and the queue object is still in the lifecycle view.
    c) ``is_busy()`` must be True — an open registration is a reason to keep
       the queue, so ``_prune_queues`` leaves it alone (before: False, the
       queue was forgettable although it held a lane).
    d) ``chat_lane_info`` still finds the registration (lane id is the one it
       holds, key ``chat:Kira``), and ``register_chat_done`` releases it:
       busy=0, no entry, no handle left. Before the fix this call only logged
       "chat task ... not found in any channel".

[2] force-resume. A channel with a serialize group holds the group's
    Semaphore(1) while a chat is registered.
    a) After the registration: lane busy=1, gate held (a non-blocking acquire
       fails), queue paused (``_chat_active`` cleared).
    b) ``force_resume_all_chats()`` reports exactly that one registration and
       afterwards: no entry, no handle, lane free, gate released (a
       non-blocking acquire succeeds) and the queue resumed. Before the fix
       the lane stayed busy and the gate stayed closed for good.

[3] The watchdog budget, computed by hand from the backend classes:
    a) ``together_video`` with TIMEOUT=60, MAX_WAIT=600 (the pair from a real
       world config): no ``max_queue_wait`` on that class, so the budget is
       600 -> watchdog max(60, 600) + 60 = 660. The old formula gave 90 —
       less than the job's own budget, which is the whole finding.
    b) ``openai_video`` with TIMEOUT=120 and no MAX_WAIT: class defaults
       max_wait=900 and max_queue_wait = 900*4 = 3600 -> budget 4500 ->
       max(120, 4500) + 60 = 4560.
    c) ``civitai`` with TIMEOUT=1, MAX_WAIT=5 (the scaled-down polling case):
       budget 5 -> max(1, 5) + 60 = 65.
    d) ``a1111`` has no polling budget at all: the plain HTTP rule stays,
       TIMEOUT=60 -> 90, and no TIMEOUT -> None (queue default 300).

[4] The watchdog branch itself, on a queue whose provider.timeout is 1 s:
    a) A callable that needs 2 s is not finished when the watchdog fires. The
       caller must hear about it after ~1 s, NOT after 2 s: the worker may
       not sit in the executor's shutdown waiting for the very callable it
       just declared dead (measured: < 1.6 s; the reviewer measured the old
       code returning only when the callable ended).
    b) What it raises is ``BackendBusyError`` — busy is not broken: the
       watchdog measures the backend's own budget, so overrunning it is load.
       Typed, it survives the queue boundary and ``run_on_backend`` retries
       without a cooldown (that classification is checked in
       scripts/smoke_backend_runner.py [3]). Before: a bare ``Exception``,
       which the runner answered with a 300-s cooldown.
    c) A result that arrives in the same breath as the timeout is NOT thrown
       away: with a ``_wait_for_future`` that raises the timeout AFTER the
       future is done (the race, made deterministic), the task completes and
       the caller gets the bytes.

[4b] The other half of that: freeing the SUBMITTER must not free the BACKEND.
    The abandoned callable is still rendering on that GPU, and "never two
    image generations in parallel on the same backend" is a hard rule here —
    the old ``with`` block enforced it by accident (it blocked in shutdown).
    So the callable keeps the execution SLOT of its task until it really
    ends; a daemon reaper gives the slot back, bounded by one more watchdog
    budget. Two runs on a one-slot channel with the watchdog at 0.5 s:
    a) callable A needs 0.8 s. It is abandoned at ~0.5 s (the submitter hears
       BackendBusyError then, measured < 0.7 s), and task B, submitted
       immediately, must NOT start before A's callable has RETURNED: recorded
       enter/exit stamps, B.enter >= A.exit. The remaining 0.3 s of A are
       inside the reaper's 0.5-s bound, so nothing is written off.
    b) callable C needs 3.0 s — far past the bound. Abandoned at ~0.5 s, the
       reaper gives up at ~1.0 s ("hung, channel continues") and the slot is
       released although C runs on. Task D then runs and finishes while C has
       not even recorded its exit yet, ~1 budget after C started instead of
       3 s later. That overlap is the deliberate escape hatch
       — a channel that never works again is worse than one parallel run —
       and the ERROR line is what says so.

[4c] Exactly ONE slot, not the whole channel. A channel with
    ``max_concurrent=2`` is an operator saying two generations at once are
    fine here, so an abandoned callable may only take one of the two slots:
    the next task runs on the other one WHILE the abandoned callable is still
    going (no exit recorded for it yet), and the task after that has to wait
    for that one slot instead of becoming a third parallel job
    (F.enter >= E.exit).

[5] Routing of a named backend. Two backends of the same api_type, one of
    them disabled:
    a) A job for the disabled one raises ``NoBackendChannelError`` and the
       callable never runs — before, it ran on the ENABLED backend's channel.
    b) The enabled backend's channel is untouched by that attempt (no task in
       its history).
    c) The legitimate fallback stays: a caller that passes no provider_name
       and only a gpu_type still lands on the enabled backend's channel and
       its callable runs.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import atexit
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def scratch(prefix):
    """A temp directory that lives exactly as long as this run."""
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


# Storage and clip library are redirected BEFORE the first app import:
# without it the default world is worlds/demo, which is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = scratch("pq-release-clips-")

from app.core import paths  # noqa: E402

paths.init(scratch("pq-release-storage-"))

from app.core import provider_manager as pm_mod  # noqa: E402
from app.core import provider_queue as pq_mod  # noqa: E402
from app.core.llm_lanes import get_lane_manager, pool_key_for  # noqa: E402
from app.core.llm_queue import Priority  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_manager import (  # noqa: E402
    NoBackendChannelError, ProviderManager,
)
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.imagegen.base import BackendBusyError  # noqa: E402
from app.utils import llm_logger, llm_stats  # noqa: E402

# Keep the JSONL log out of the repo's logs/ directory and both DB users out
# of the run entirely — neither has anything to do with what is measured here.
llm_logger.LOG_DIR = Path(scratch("pq-release-logs-"))
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


LANES = get_lane_manager()


def pool(pool_key):
    return LANES.snapshot()["pools"].get(
        pool_key, {"busy": 0, "free": 0, "waiting": 0, "lanes": []})


def stub_provider(name, ptype="openai", timeout=30):
    p = Provider(name=name, type=ptype, api_base=f"http://stub/{name}",
                 api_key="", max_concurrent=1, timeout=timeout)
    p.available = True
    return p


# ── [1] LLM-1: a registration on a queue whose channel was dropped ─────────
print("\n[1] the channel is gone, the registration is still released")

PROVIDER = stub_provider("P")
QUEUE = ProviderQueue(PROVIDER, queue_name="P", max_concurrent=1,
                      chat_pause_enabled=False, serialize_group="")
MANAGER = ProviderManager()
MANAGER.providers["P"] = PROVIDER
MANAGER.channels["P"] = QUEUE
MANAGER._queues["P"] = QUEUE
pm_mod._provider_manager = MANAGER

POOL_A = pool_key_for("P", "model-a")

chat_id = QUEUE.register_chat_active("Kira", model="model-a",
                                     task_type="chat_stream")
check("a) the registration holds the pool's only lane", pool(POOL_A)["busy"], 1)

# The health probe says "not reachable" right now — check_all_availability
# then drops the channel, which is what every admin save runs into.
PROVIDER.check_availability = lambda: False
PROVIDER.available = False
MANAGER.check_all_availability()
check("b) the channel is gone from the routing view", "P" in MANAGER.channels, False)
check("b) the queue object is still in the lifecycle view",
      MANAGER._queues.get("P") is QUEUE, True)
check("c) a queue with an open registration counts as busy",
      QUEUE.is_busy(), True)

lane_id, cache_key = MANAGER.chat_lane_info(chat_id)
check("d) chat_lane_info finds the registration",
      (lane_id is not None, cache_key), (True, "chat:Kira"))

MANAGER.register_chat_done(chat_id)
check("d) the registration is closed", QUEUE._chat_tasks, {})
check("d) its lane came back", pool(POOL_A)["busy"], 0)
check("d) no handle left behind", QUEUE._chat_lanes, {})
check("c) and the queue is forgettable again", QUEUE.is_busy(), False)

# ── [2] LLM-2: force-resume releases lane AND serialize gate ───────────────
print("\n[2] force-resume gives back everything a registration holds")

GATE = threading.Semaphore(1)
GATED_PROVIDER = stub_provider("G")
GATED = ProviderQueue(GATED_PROVIDER, queue_name="G", max_concurrent=1,
                      chat_pause_enabled=True, serialize_group="gpu0")
GATED._serialize_gate = GATE
MANAGER.providers["G"] = GATED_PROVIDER
MANAGER.channels["G"] = GATED
MANAGER._queues["G"] = GATED

POOL_G = pool_key_for("G", "model-g")
gated_id = GATED.register_chat_active("Ida", model="model-g",
                                      task_type="chat_stream")
check("a) the registration holds a lane", pool(POOL_G)["busy"], 1)
check("a) and the serialize gate", GATE.acquire(blocking=False), False)
check("a) the queue is paused", GATED._chat_active.is_set(), False)

released = MANAGER.force_resume_all_chats()
check("b) force-resume reports the registration",
      [(r["provider"], r["chat_task"], r["agent"]) for r in released],
      [("G", gated_id, "Ida")])
check("b) the entry is gone", GATED._chat_tasks, {})
check("b) no handle left behind", GATED._chat_lanes, {})
check("b) the lane is free", pool(POOL_G)["busy"], 0)
check("b) the serialize gate is released", GATE.acquire(blocking=False), True)
GATE.release()
check("b) the queue is resumed", GATED._chat_active.is_set(), True)

# ── [3] IMG-2: the watchdog comes from the job budget ──────────────────────
print("\n[3] the watchdog budget of a polling backend")

_budget = ProviderManager._watchdog_timeout


def budget(api_type, prefix, timeout, **envs):
    for key, value in envs.items():
        os.environ[f"{prefix}{key}"] = str(value)
    try:
        return _budget(api_type, prefix, timeout)
    finally:
        for key in envs:
            os.environ.pop(f"{prefix}{key}", None)


check("a) together_video timeout=60, max_wait=600 -> 660",
      budget("together_video", "SMOKE_BE_1_", 60, MAX_WAIT=600), 660)
check("b) openai_video timeout=120, defaults 900 + 3600 -> 4560",
      budget("openai_video", "SMOKE_BE_2_", 120), 4560)
check("c) civitai timeout=1, max_wait=5 -> 65",
      budget("civitai", "SMOKE_BE_3_", 1, MAX_WAIT=5), 65)
check("d) a1111 has no polling budget: timeout=60 -> 90",
      budget("a1111", "SMOKE_BE_4_", 60), 90)
check("d) a1111 without a timeout stays on the queue default",
      budget("a1111", "SMOKE_BE_4_", None), None)

# ── [4] IMG-2: the timeout branch frees the worker and keeps a result ──────
print("\n[4] a watchdog timeout: fast, typed, and no result thrown away")

SLOW_PROVIDER = stub_provider("S", timeout=1)   # watchdog fires after 1 s
SLOW = ProviderQueue(SLOW_PROVIDER, queue_name="S", max_concurrent=1,
                     chat_pause_enabled=False, serialize_group="")


def slow_render():
    # Longer than the watchdog: the job is NOT done when it fires.
    time.sleep(2.0)
    return [b"late-mp4"]


t0 = time.monotonic()
raised = None
try:
    SLOW.submit_gpu_task("image_gen", Priority.IMAGE_GEN, slow_render,
                         agent_name="system", label="S")
except Exception as e:  # noqa: BLE001 — the type is the expectation
    raised = e
elapsed = time.monotonic() - t0
check("a) the caller hears about it at the watchdog, not at the callable's end",
      elapsed < 1.6, True)
check("b) and hears it as load, not as a defect",
      type(raised).__name__, BackendBusyError.__name__)

# The race, made deterministic: the future IS done when the timeout is raised.
_real_wait = pq_mod._wait_for_future


def wait_then_timeout(future, task, timeout, poll_interval=2.0):
    future.result()          # the work finished during the wait
    raise FuturesTimeoutError()


pq_mod._wait_for_future = wait_then_timeout
try:
    late = SLOW.submit_gpu_task("image_gen", Priority.IMAGE_GEN,
                                lambda: [b"mp4"], agent_name="system", label="S")
except Exception as e:  # noqa: BLE001 — would be a failed check
    late = f"raised {type(e).__name__}"
finally:
    pq_mod._wait_for_future = _real_wait
check("c) a result that arrived with the timeout is delivered", late, [b"mp4"])

# ── [4b] the abandoned callable keeps the backend's slot ──────────────────
print("\n[4b] a timed-out callable keeps its slot until it really ends")

STAMPS = []
STAMP_LOCK = threading.Lock()


def stamped(name, seconds, result=None):
    """A fake render that records when it enters and when it returns."""

    def run():
        with STAMP_LOCK:
            STAMPS.append((f"{name}.enter", time.monotonic()))
        time.sleep(seconds)
        with STAMP_LOCK:
            STAMPS.append((f"{name}.exit", time.monotonic()))
        return result if result is not None else [b"img"]

    return run


def stamp(name):
    """When the event was recorded, or None when it has not happened (yet).

    None is an answer here, not an error: "the callable has not returned"
    is exactly what half of these checks are about."""
    with STAMP_LOCK:
        return dict(STAMPS).get(name)


def run_in_thread(queue_obj, callable_fn, label):
    box = {}

    def go():
        try:
            box["result"] = queue_obj.submit_gpu_task(
                "image_gen", Priority.IMAGE_GEN, callable_fn,
                agent_name="system", label=label)
        except Exception as e:  # noqa: BLE001 — the type is an expectation
            box["error"] = type(e).__name__
    t = threading.Thread(target=go, daemon=True, name=f"submit-{label}")
    t.start()
    return t, box


# One slot, watchdog at 0.5 s — fast enough for a check, and the ONLY thing
# the small numbers decide is how long the check runs.
ABANDON_PROVIDER = stub_provider("A", timeout=30)
ABANDON_PROVIDER.timeout = 0.5
ABANDON = ProviderQueue(ABANDON_PROVIDER, queue_name="A", max_concurrent=1,
                        chat_pause_enabled=False, serialize_group="")

t_a0 = time.monotonic()
t_a, box_a = run_in_thread(ABANDON, stamped("A", 0.8), "A")
t_a.join(timeout=5)
a_elapsed = time.monotonic() - t_a0
check("a) the submitter is freed at the watchdog",
      (box_a.get("error"), a_elapsed < 0.7), (BackendBusyError.__name__, True))

t_b, box_b = run_in_thread(ABANDON, stamped("B", 0.05), "B")
t_b.join(timeout=10)
check("a) the second task ran", box_b.get("result"), [b"img"])
_a_exit, _b_enter = stamp("A.exit"), stamp("B.enter")
check("a) and it did NOT start before the abandoned callable returned",
      _a_exit is not None and _b_enter is not None and _b_enter >= _a_exit, True)

# b) the hung variant: the callable outruns the reaper's bound.
t_c, box_c = run_in_thread(ABANDON, stamped("C", 3.0), "C")
t_c.join(timeout=5)
check("b) the submitter is freed at the watchdog again",
      box_c.get("error"), BackendBusyError.__name__)

t_d, box_d = run_in_thread(ABANDON, stamped("D", 0.05), "D")
t_d.join(timeout=10)
check("b) the channel carries on after the bound", box_d.get("result"), [b"img"])
with STAMP_LOCK:
    _seen = {name for name, _ in STAMPS}
check("b) while the hung callable is still running (no exit recorded yet)",
      "C.exit" in _seen, False)
_c_enter, _d_enter = stamp("C.enter"), stamp("D.enter")
check("b) and that took about one more budget, not the callable's 3 s",
      _c_enter is not None and _d_enter is not None
      and _d_enter - _c_enter < 2.0, True)

# ── [4c] the slot is per SLOT, not per channel ─────────────────────────────
print("\n[4c] on a two-slot channel exactly ONE slot is held")

# A channel with max_concurrent=2 is an operator saying "two generations at
# once are fine here". An abandoned callable must take exactly ONE of those
# slots away: the other one keeps working (E below), and a third task has to
# wait for it (F below) instead of running as a third parallel job.
TWO_PROVIDER = stub_provider("T", timeout=30)
TWO_PROVIDER.timeout = 0.5
TWO = ProviderQueue(TWO_PROVIDER, queue_name="T", max_concurrent=2,
                    chat_pause_enabled=False, serialize_group="")

t_e0, box_e0 = run_in_thread(TWO, stamped("E0", 1.6), "E0")
t_e0.join(timeout=5)
check("the long callable was abandoned", box_e0.get("error"),
      BackendBusyError.__name__)

t_e, box_e = run_in_thread(TWO, stamped("E", 0.2), "E")
t_f, box_f = run_in_thread(TWO, stamped("F", 0.05), "F")
t_e.join(timeout=10)
t_f.join(timeout=10)
check("the free slot kept working", box_e.get("result"), [b"img"])
check("and so did the task behind it", box_f.get("result"), [b"img"])
_e_enter, _e_exit, _f_enter = stamp("E.enter"), stamp("E.exit"), stamp("F.enter")
check("it started while the abandoned callable was still running",
      _e_enter is not None and stamp("E0.exit") is None, True)
check("but the third task waited — only ONE slot was taken away",
      _f_enter is not None and _e_exit is not None and _f_enter >= _e_exit, True)

# ── [5] IMG-5b: a named backend never runs on a foreign channel ────────────
print("\n[5] a backend without a channel fails instead of taking a foreign one")

for key in list(os.environ):
    if key.startswith("SKILL_IMAGEGEN_") or key.startswith("PROVIDER_"):
        os.environ.pop(key)
os.environ.update({
    "SKILL_IMAGEGEN_1_NAME": "Alpha",
    "SKILL_IMAGEGEN_1_API_TYPE": "a1111",
    "SKILL_IMAGEGEN_1_API_URL": "http://stub/alpha",
    "SKILL_IMAGEGEN_1_ENABLED": "true",
    "SKILL_IMAGEGEN_2_NAME": "Beta",
    "SKILL_IMAGEGEN_2_API_TYPE": "a1111",
    "SKILL_IMAGEGEN_2_API_URL": "http://stub/beta",
    "SKILL_IMAGEGEN_2_ENABLED": "false",
})

BACKENDS = ProviderManager()
BACKENDS.load_providers()
check("the enabled backend has a channel",
      "backend:Alpha" in BACKENDS.channels, True)
check("the disabled one has none",
      "backend:Beta" in BACKENDS.channels, False)

ran = []
routed = None
try:
    BACKENDS.submit_gpu_task("Beta", "image_gen", Priority.IMAGE_GEN,
                             lambda: ran.append("Beta") or [b"img"],
                             agent_name="system", label="Beta",
                             gpu_type="a1111")
except Exception as e:  # noqa: BLE001 — the type is the expectation
    routed = e
check("a) the disabled backend's job fails with the typed error",
      type(routed).__name__, NoBackendChannelError.__name__)
check("a) and its callable never ran", ran, [])
check("b) the other backend's channel stayed untouched",
      BACKENDS.channels["backend:Alpha"].get_status()["recent"], [])

result = BACKENDS.submit_gpu_task("", "image_gen", Priority.IMAGE_GEN,
                                  lambda: ran.append("Alpha") or [b"img"],
                                  agent_name="system", label="Alpha",
                                  gpu_type="a1111")
check("c) a gpu_type-only caller still routes by type", ran, ["Alpha"])
check("c) and gets its result", result, [b"img"])

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
