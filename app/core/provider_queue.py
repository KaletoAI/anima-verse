"""Per-Provider LLM Queue.

Each Provider gets its own ProviderQueue. Tasks are processed in priority
order.

How many LLM calls run at once is NOT decided here: every LLM task takes a
CACHE LANE of the pool of its own provider/model (app/core/llm_lanes.py,
plan-cache-lanes.md), so the limit belongs to the LLM entry and a call prefers
the lane that already holds its prompt beginning. The queue's own slot
bookkeeping (``_Permits``) is left for GPU tasks — image/video/mesh jobs on a
backend channel, where the limit really is the backend.

Chat/Story streaming bypasses the queue (direct invoke) but registers for
tracking AND takes a lane of the same pool, so a streaming turn and a queued
call never race for the same prompt cache. While chat is active on a provider,
that provider's background tasks pause.
"""
import queue
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from app.core.timeutils import utc_now_iso
from typing import Any, Dict, List, Optional, Tuple

from .provider import Provider
from .llm_queue import LLMTask, Priority
from .turn_trace import current_trace
from app.utils.llm_logger import get_model_name

from app.core.log import get_logger
logger = get_logger("provider_queue")


class _CancelledByUser(Exception):
    """Internal signal: task was cancelled by user."""


def _trace_fields() -> Tuple[str, str]:
    """Reads the ambient turn trace as ``(trace_id, trace_kind)``.

    Must be called at SUBMIT time: submit runs in the caller's context where
    the trace of the running action still exists, while the worker thread
    that later executes the task does not inherit it.
    """
    t = current_trace()
    if not t:
        return "", ""
    return t.get("id", ""), t.get("kind", "")


# A caller that retries the same logical call over its own fallback chain
# (llm_router.llm_call) reports the outcome itself. While this is set, a
# failed LLM task of the upstream class is logged here as a WARNING without a
# traceback — the ERROR with the full traceback belongs to the caller, and
# only once its chain is exhausted. Read at SUBMIT time and stamped onto the
# task, because the worker THREAD does not inherit the caller's context (same
# reason as LLMTask.trace_id).
_caller_handles_failure: ContextVar[bool] = ContextVar(
    "llm_caller_handles_failure", default=False)


@contextmanager
def caller_handles_failure():
    """Marks LLM submits inside this block as reported by the caller."""
    token = _caller_handles_failure.set(True)
    try:
        yield
    finally:
        _caller_handles_failure.reset(token)


def _is_upstream_failure_safe(err: BaseException) -> bool:
    """``llm_router._is_upstream_failure`` without an import-time dependency —
    the router imports this module, so the import stays local and a failure to
    resolve it means "not recoverable" (full traceback)."""
    try:
        from app.core.llm_router import _is_upstream_failure
        return _is_upstream_failure(err)
    except Exception:
        return False


def log_task_failure(queue_name: str, task: LLMTask, err: BaseException) -> None:
    """Logs a failed LLM task at the level its outcome deserves.

    An upstream failure (5xx, connection drop, "no servable backend") whose
    caller retries it over a fallback chain is NOT final: it becomes a WARNING
    without a traceback, and the caller writes the ERROR once the chain is
    exhausted. Everything else — a user/payload error, or any failure nobody
    else reports — keeps the ERROR and the full traceback.
    """
    if task._caller_handles_failure and _is_upstream_failure_safe(err):
        logger.warning("[%s] Upstream failure: %s: %s — the caller falls back",
                       queue_name, task.task_id, err)
    else:
        logger.error("[%s] Error: %s: %s", queue_name, task.task_id, err, exc_info=True)


def cooldown_after_failure(provider: Provider, model_name: str,
                           task_type: str, err: BaseException) -> None:
    """Puts the provider (or just one of its models) into cooldown after a
    backend-side crash (5xx, process exit, connection drop), so resolve_llm
    skips it and the routing chain falls through. Streaming consumers that do
    not go through llm_call benefit too.

    EXCEPTION: a 503 "No healthy backend for model X" is model-specific — cool
    down only that (provider, model) pair, NOT the whole provider, which keeps
    serving its other models.

    Both cooldown setters are idempotent and log only the FIRST time per
    outage, so this call and llm_router.llm_call's own one leave a single line.
    """
    try:
        from app.core.llm_router import (
            _is_upstream_failure, _UPSTREAM_COOLDOWN_SECONDS,
            mark_model_unhealthy,
        )
        from app.core.llm_client import _is_no_backend_error
        if _is_no_backend_error(err):
            mark_model_unhealthy(provider.name, model_name)
        elif _is_upstream_failure(err):
            provider.mark_unhealthy(
                f"upstream-fail [{task_type}]: {str(err)[:120]}",
                _UPSTREAM_COOLDOWN_SECONDS)
    except Exception:
        pass


def _wait_for_future(future, task, timeout: float, poll_interval: float = 2.0):
    """Waits for a future with periodic cancel checks.

    Instead of blocking for the full timeout, polls in short intervals
    and checks task._cancelled between polls. This allows cancel requests
    to take effect within poll_interval seconds instead of waiting for
    the full timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        if task._cancelled:
            raise _CancelledByUser()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FuturesTimeoutError()
        try:
            return future.result(timeout=min(poll_interval, remaining))
        except FuturesTimeoutError:
            continue  # Re-check cancel flag


# Errors that indicate a retriable GPU OOM condition
_RETRIABLE_GPU_ERRORS = (
    "OutOfMemoryError",
    "CUDA out of memory",
    "torch.OutOfMemoryError")

_GPU_MAX_RETRIES = 2  # Max retry attempts for retriable GPU errors

# A worker that went once through the whole queue without finding a task
# whose pool has a free lane sleeps this long before trying again — otherwise
# it would spin on the re-queue path at full speed. Short enough that a lane
# freed meanwhile is picked up without a noticeable delay.
_LANE_RETRY_SLEEP = 0.15

# How long a streaming registration waits for its lane in ONE go. It has no
# second option — it cannot be re-queued — so it waits; but a pool that hands
# out no lane for minutes is a bug, and an ERROR line every minute is what
# makes it visible. It is also the slice length of that wait: between two
# slices the registration runs the stale-chat cleanup, which is the only thing
# that can give back a lane held by a registration whose done never came
# (see _acquire_chat_lane).
_LANE_WAIT_WARN = 60

# After how many slices a NESTED wait (the tool call of a running turn, and
# the turn taking its lane back afterwards) stops being normal. Losing one
# pass to another conversation is what the rules are for and logs WARNING;
# waiting minutes for a lane one just gave back is not, and logs ERROR.
_LANE_WAIT_ESCALATE_SLICES = 3


class _Permits:
    """The concurrency slots of ONE channel, with a limit that may change
    while tasks run.

    A plain Semaphore cannot be shrunk: taking permits back would block on the
    ones held by running tasks, and a reaper thread racing for them loses
    against a waiting worker. Here the limit is a number, and a task that
    finishes simply does not get its slot back while the channel is over its
    limit — the reduction lands deterministically, at the next release.

    The object identity matters: it is what survives a config reload, so an
    in-flight task keeps occupying its slot (see ``ProviderQueue.reconfigure``).
    """

    def __init__(self, limit: int):
        self._cond = threading.Condition()
        self._limit = max(1, int(limit))
        self._held = 0

    @property
    def limit(self) -> int:
        with self._cond:
            return self._limit

    def acquire(self, blocking: bool = True) -> bool:
        with self._cond:
            while self._held >= self._limit:
                if not blocking:
                    return False
                self._cond.wait()
            self._held += 1
            return True

    def release(self) -> None:
        with self._cond:
            self._held = max(0, self._held - 1)
            self._cond.notify()

    def set_limit(self, limit: int) -> None:
        """New limit, effective immediately for free slots. Slots held by
        running tasks stay held — a shrink lands as they finish."""
        with self._cond:
            self._limit = max(1, int(limit))
            self._cond.notify_all()

    def held(self) -> int:
        with self._cond:
            return self._held


class ProviderQueue:
    """Per-provider (or per-backend) queue with configurable concurrency and chat pause."""

    def __init__(self, provider: Provider, queue_name: str = "",
                 max_concurrent: int = 0, chat_pause_enabled: bool = True,
                 serialize_group: str = ""):
        self.provider = provider
        self._queue_name = queue_name or provider.name
        self._chat_pause_enabled = chat_pause_enabled
        # Name of the serialize group this channel belongs to ("" = none).
        # Channels with the same group share one Semaphore(1) — see below.
        self.serialize_group = serialize_group
        effective_concurrent = max_concurrent if max_concurrent > 0 else provider.max_concurrent
        self._max_concurrent = effective_concurrent
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq_counter: int = 0
        self._lock = threading.Lock()
        self._chat_active = threading.Event()
        self._chat_active.set()  # Initially free (no chat active)
        self._running = False
        self._workers: List[threading.Thread] = []
        # Slot bookkeeping for GPU tasks only — LLM tasks take a lane
        # instead (see the module docstring).
        self._semaphore = _Permits(effective_concurrent)
        # Optional serialize-group gate: one shared Semaphore across ALL
        # channels with the same serialize_group (e.g. an LLM provider and an
        # image backend sharing one GPU). Set by the ProviderManager; None =
        # no gate (default behaviour). Both the worker (per task) and
        # streaming chat (register_chat_active) acquire it, so only ONE call
        # runs at a time within the group. _holds_serialize_gate: does this
        # channel currently hold the gate because of active chats?
        self._serialize_gate: Optional[threading.Semaphore] = None
        self._holds_serialize_gate = False
        self._current_tasks: List[LLMTask] = []
        # Multiple concurrent chats supported (keyed by task_id)
        self._chat_tasks: Dict[str, LLMTask] = {}
        # The cache lane each registration holds, by the SAME key. Separate
        # from the task object on purpose — see _release_chat_lane.
        self._chat_lanes: Dict[str, Any] = {}
        self._chat_registered_at: float = 0.0  # monotonic timestamp (latest)
        self._history: List[LLMTask] = []
        self._history_limit: int = 30
        self._pending_tasks: List[LLMTask] = []
        self._futures: Dict[str, Any] = {}  # task_id -> Future (for running task cancel)

    def reconfigure(self, provider: Provider, *, max_concurrent: int = 0,
                    chat_pause_enabled: bool = True, serialize_group: str = "",
                    serialize_gate: Optional[threading.Semaphore] = None) -> None:
        """Applies new settings IN PLACE so this queue object — and with it
        every in-flight task's concurrency slot — survives a config reload.

        A freshly built queue starts with ALL its slots free: while the old
        object still runs its task, the new one admits the next one and a
        ``concurrent=1`` backend executes two jobs at once (observed
        2026-08-03: an admin save mid-mesh-job double-ran a gateway backend
        into 600-s ComfyUI timeouts). The slot bookkeeping (``_Permits``)
        therefore stays the SAME object and only its limit changes; a shrink
        lands as the running tasks finish.

        A running queue tops its workers up right here. The worker count
        follows the lane totals of the config, so a raised lane count would
        otherwise stay without effect until the queue idles — and a queue busy
        enough to need the lanes is the one that never idles. Only growth is
        applied: a surplus worker ends by itself when it finds nothing to do,
        and taking one away mid-task is the one thing that must not happen.
        """
        effective = max_concurrent if max_concurrent > 0 else provider.max_concurrent
        with self._lock:
            self.provider = provider
            self._chat_pause_enabled = chat_pause_enabled
            self.serialize_group = serialize_group
            self._serialize_gate = serialize_gate
            self._max_concurrent = effective
            running = self._running
        self._semaphore.set_limit(effective)
        if running:
            self._ensure_workers()

    def is_busy(self) -> bool:
        """A task is running or waiting on this queue — the ProviderManager
        must keep such a queue across a reload instead of replacing it."""
        with self._lock:
            return bool(self._current_tasks) or not self._queue.empty()

    def submit(
        self,
        task_type: str,
        priority: int,
        llm: Any,
        messages_or_prompt: Any,
        agent_name: str = "", label: str = "") -> Any:
        """Submits an LLM call to this provider's queue. Blocks until result ready.

        Args:
            task_type: e.g. "image_prompt", "extraction", "talk_to"
            priority: Priority.LOW / NORMAL / HIGH
            llm: LLMClient instance
            messages_or_prompt: List[Message] or str prompt
            label: Optional detail for logging (e.g. related character)
            agent_name: Character name
            user_id: User ID

        Returns:
            AIMessage (LLM response)

        Raises:
            Exception: if LLM call fails
        """
        task = LLMTask(
            task_id=f"llm_{uuid.uuid4().hex[:8]}",
            task_type=task_type,
            priority=priority,
            agent_name=agent_name,
            created_at=utc_now_iso(),
            provider_name=self.provider.name,
            model=get_model_name(llm),
            # The label rides ON the task: the task panel shows it, and the
            # JSONL logger writes it so a call can be traced to its caller.
            label=label,
            _llm=llm,
            _messages=messages_or_prompt)
        task.trace_id, task.trace_kind = _trace_fields()
        # Who reports a failure of this task — see caller_handles_failure().
        task._caller_handles_failure = _caller_handles_failure.get()

        with self._lock:
            self._seq_counter += 1
            seq = self._seq_counter
            self._pending_tasks.append(task)

        self._queue.put((priority, seq, task))
        label_suffix = f" label={label}" if label else ""
        logger.info("[%s] Eingereicht: %s (%s) prio=%d agent=%s%s",
                    self._queue_name, task.task_id, task_type, priority, agent_name, label_suffix)

        self._ensure_workers()

        # Block until worker sets the result
        task._done_event.wait()

        # Remove from pending
        with self._lock:
            if task in self._pending_tasks:
                self._pending_tasks.remove(task)

        if task.status == "cancelled":
            raise Exception(f"LLM Queue task cancelled: {task.task_id}")

        if task.status == "failed":
            # Chain the worker's original exception as __cause__. The caller
            # type stays a plain Exception (llm_router matches on the message),
            # but logging with exc_info on this error now prints the upstream
            # stack from llm_client/HTTP as well — without it the traceback
            # would end at this raise. No original (e.g. watchdog timeout)
            # means no cause.
            raise Exception(f"LLM Queue task failed: {task.error}") from task._exception

        return task.result

    def submit_gpu_task(
        self,
        task_type: str,
        priority: int,
        callable_fn,
        agent_name: str = "", label: str = "") -> Any:
        """Submits a GPU-holding task to this provider's queue.

        The callable runs while holding the GPU slot (semaphore). Used for image
        generation on backends that share a GPU with this LLM provider.
        Blocks until the callable completes and returns its result.
        """
        task = LLMTask(
            task_id=f"gpu_{uuid.uuid4().hex[:8]}",
            task_type=task_type,
            priority=priority,
            agent_name=agent_name,
            created_at=utc_now_iso(),
            provider_name=self.provider.name,
            model=label)
        task.trace_id, task.trace_kind = _trace_fields()
        task._gpu_callable = callable_fn

        with self._lock:
            self._seq_counter += 1
            seq = self._seq_counter
            self._pending_tasks.append(task)

        self._queue.put((priority, seq, task))
        logger.info("[%s] GPU-Task eingereicht: %s (%s) prio=%d agent=%s label=%s",
                    self._queue_name, task.task_id, task_type, priority, agent_name, label)

        self._ensure_workers()

        # Block until worker sets the result
        task._done_event.wait()

        # Remove from pending
        with self._lock:
            if task in self._pending_tasks:
                self._pending_tasks.remove(task)

        if task.status == "cancelled":
            raise Exception(f"GPU task cancelled: {task.task_id}")
        if task.status == "failed":
            # Re-raise the worker's original exception when we have it — the
            # type matters to callers (imagegen's fallback engine distinguishes
            # BackendBusyError = load from real defects). Queue-level failures
            # (watchdog timeout) have no original exception and stay generic:
            # a task that blows past the watchdog is treated as broken.
            _orig = task._exception
            if _orig is not None:
                raise _orig
            raise Exception(f"GPU task failed: {task.error}")

        return task.result

    def register_chat_active(self, agent_name: str, model: str = "",
                             task_type: str = "chat_stream",
                             label: str = "") -> str:
        """Registers active chat/story. Pauses this provider's queue.

        Waits for any running background task to finish before returning,
        preventing conflicts on single-model servers like llama-swap where
        a new request would kill the running one.

        Supports multiple concurrent chats (e.g. Pixel + Diego on same provider).

        Args:
            task_type: differentiates entry types in panel
                ("chat_stream", "thought", "talk_to", "send_message", ...)
            label: short user-friendly label, falls back to task_type when empty

        Returns:
            task_id for register_chat_done()
        """
        task = LLMTask(
            task_id=f"chat_{uuid.uuid4().hex[:8]}",
            task_type=task_type,
            priority=Priority.CHAT,
            agent_name=agent_name,
            created_at=utc_now_iso(),
            status="chat_active",
            provider_name=self.provider.name,
            model=model,
            label=label)
        # Monotonic timestamp for stale detection (per task, not global)
        task._monotonic_created = time.monotonic()
        # Duration estimate without input scaling — the messages do not exist
        # yet at registration time, so show the median for (model, task).
        _attach_duration_estimate(task)

        # Take a cache lane of this model's pool BEFORE the registration
        # exists. Streaming bypasses the queue, so without a lane a streaming
        # turn and a queued call would compete for the same prompt cache. The
        # order matters: while this waits, the entry is in no dict yet, so
        # neither _check_stale_chat nor a cancelled caller can throw away a
        # registration whose lane is still being handed out. The lane is held
        # until register_chat_done — the tool executor releases and
        # re-registers around its own LLM calls (R6), which is why a lane is
        # never held across a nested call.
        handle = self._acquire_chat_lane(task)

        with self._lock:
            self._chat_tasks[task.task_id] = task
            self._chat_lanes[task.task_id] = handle
            self._chat_registered_at = time.monotonic()

        # Pause queue: workers won't start NEW tasks
        self._chat_active.clear()

        # Serialize-group gate: wait until the group is free (e.g. a running
        # image generation in the same group) and hold it for the chat's
        # duration. Only the FIRST active chat registration acquires; further
        # chats share it.
        if self._serialize_gate is not None:
            _claim = False
            with self._lock:
                if not self._holds_serialize_gate:
                    self._holds_serialize_gate = True
                    _claim = True
            if _claim and not self._serialize_gate.acquire(timeout=300):
                logger.warning("[%s] Serialize-gate timeout (300s) — chat starts anyway",
                               self._queue_name)
                with self._lock:
                    self._holds_serialize_gate = False

        active_count = len(self._chat_tasks)
        logger.info("[%s] Chat aktiv: %s (%s) — Queue pausiert (%d aktive Chats)",
                    self._queue_name, agent_name, task.task_id, active_count)
        return task.task_id

    def register_chat_iteration(self, task_id: str,
                                 iteration: int, max_iterations: int) -> None:
        """Update iteration progress on a chat_active task.

        Called by StreamingAgent at each iteration boundary so the queue
        panel can show "iter 2/3" while the turn streams.
        """
        with self._lock:
            task = self._chat_tasks.get(task_id)
            if task is None:
                return
            task.current_iteration = iteration
            task.max_iterations = max_iterations

    def _acquire_chat_lane(self, task: LLMTask) -> Any:
        """Takes a cache lane for a streaming registration and returns the
        handle.

        This is the ONE path that really waits for a lane: a stream cannot be
        put back into the queue and started again later. It therefore has no
        "run without a lane" escape either — that would be unbounded
        parallelism on exactly the pool whose cache we are protecting.

        The wait runs in SLICES of _LANE_WAIT_WARN seconds, and between two
        slices this calls _check_stale_chat(). That is not a nicety: the
        stale check used to run only in the chat-pause wait of the worker
        loop, which is gated by _chat_pause_enabled (= a serialize group is
        configured). On every other provider nothing ever cleaned up a
        registration whose register_chat_done never came — the documented
        case is a browser reload during streaming, where the SSE generator's
        finally does not run. Without lanes that left a stale entry behind;
        with lanes it would hold the model's lane for the lifetime of the
        process, so every later chat would wait here forever and every queued
        task of that pool would be deferred for good. The ERROR line per
        slice (same 60-s cadence as before) keeps such a wait visible.

        A slice boundary drops the call out of the pool's waiting list for an
        instant. The arrival stamp is taken ONCE and handed back in on every
        slice, so the ordering rules of phase 2 still age it from when it
        really arrived.
        """
        from app.core.llm_lanes import (
            cache_key_for, lane_priority_for, pool_key_for,
        )

        pool_key = pool_key_for(self.provider.name, task.model)
        task._cache_key = cache_key_for(task.task_type, task.agent_name)
        # The priority for the LANES follows the prompt class, not the panel:
        # every registration here is Priority.CHAT, thought turns included, so
        # taking that value would let the AgentLoop's thoughts ignore R3 and
        # rank level with a user's conversation in R2. task.priority itself is
        # untouched — it is what pauses the queue and what the panel shows.
        task._lane_priority = lane_priority_for(task.task_type)
        handle, arrived = self._wait_for_lane(
            pool_key, task._cache_key, task._lane_priority, task.task_type,
            who=task.agent_name or "?")
        task._lane_arrived = arrived
        task._lane_handle = handle
        return handle

    def _wait_for_lane(self, pool_key: str, cache_key: str, priority: int,
                       label: str, who: str = "",
                       arrived: Optional[float] = None,
                       own_lane: Optional[int] = None,
                       nested: bool = False) -> Tuple[Any, float]:
        """Waits for a lane of ``pool_key`` in slices. Returns (handle, when
        it first asked).

        The slice loop is the same for the two paths that cannot be put back
        into the queue — a streaming registration and the nested tool call of
        an rp_first turn (R6). Between two slices the stale-chat cleanup runs,
        the one thing that can free a lane held by a registration whose
        ``register_chat_done`` never came; a log line per slice keeps a long
        wait visible.

        ``arrived`` hands in a stamp the CALLER already owns instead of taking
        a fresh one: the nested call of a turn and the turn's own resume are
        the same call still, and a fresh stamp would make each of them the
        youngest waiter on the pool — two turns on one pool would then
        leapfrog each other at every suspend. ``own_lane`` is the lane that
        call handed back a moment ago; R4 does not hold it off that one.

        ``nested`` also says that this waiter belongs to a turn ALREADY UNDER
        WAY, and it is handed to the manager as ``running_turn``: a reply that
        reserved THIS pool (R7) must not hold such a call back. It is not new
        work — the turn holds a lane on its own pool while it waits here, so
        stalling it here only keeps that other pool's lane busy and makes the
        replies waiting there wait longer. Everything a claim really has to
        hold off is a fresh arrival.

        The level of the wait line: a nested/resume wait that is merely losing
        a pass to another conversation is normal and logs WARNING; only a wait
        that survives several slices is the pathology the ERROR is for. A
        registration's own wait logs ERROR from the first slice — it has no
        second option at all.

        A slice boundary drops the call out of the pool's waiting list for an
        instant. The arrival stamp is taken ONCE and handed back in on every
        slice, so the ordering rules (R2 ageing, R3 affinity) age it from when
        it really arrived.
        """
        from app.core.llm_lanes import LaneTimeout, get_lane_manager

        manager = get_lane_manager()
        # Live config: an admin save changes the lane count without a restart.
        manager.sync_from_config(pool_key)
        if arrived is None:
            arrived = manager.now()
        waited = 0.0
        slices = 0
        while True:
            # The lower bound only keeps a misconfigured 0 from
            # spinning; a check may shorten the slice to run in seconds.
            slice_seconds = max(0.05, float(_LANE_WAIT_WARN))
            try:
                handle = manager.acquire_lane(
                    pool_key, cache_key, priority, arrived=arrived,
                    own_lane=own_lane, running_turn=nested,
                    timeout=slice_seconds, label=label)
                return handle, arrived
            except LaneTimeout:
                waited += slice_seconds
                slices += 1
                _log = (logger.warning
                        if nested and slices < _LANE_WAIT_ESCALATE_SLICES
                        else logger.error)
                _log(
                    "[%s] %s (%s) waits %.0fs for a lane on %s — looking for "
                    "stale chat registrations",
                    self._queue_name, who or "?", cache_key, waited, pool_key)
                # The one cleanup that can free this lane again. It runs here
                # because this path is reached on EVERY provider, whereas the
                # worker's chat-pause wait only runs where a serialize group
                # is configured.
                self._check_stale_chat()

    def acquire_nested_lane(self, pool_key: str, cache_key: str,
                            priority: int = Priority.NORMAL,
                            label: str = "",
                            arrived: Optional[float] = None,
                            own_lane: Optional[int] = None) -> Any:
        """A lane for a call this channel makes OUTSIDE the queue and outside
        a registration — today the rp_first tool decision (plan § 6, 7a).

        It is a second prompt beginning on a real pool, so it needs a lane
        like everything else. The POOL is handed in, not derived from this
        channel: the caller (``ProviderManager.nested_call_lane``) is the one
        that knows which pool the nested LLM belongs to, and when no channel
        serves it at all the call runs here under an explicitly unknown pool
        key rather than under this channel's name. So is the PRIORITY, which
        is the owning turn's lane priority — a thought's tool call must not
        outrank a parked conversation just because a chat turn is waiting for
        some nested call somewhere.

        When it runs on the SAME pool as the turn that triggered it, the
        caller must have given back the lane it holds (R6,
        ``suspend_chat_lane``) — on a one-lane pool this would otherwise wait
        for itself — and hands the two things that belong to the turn along:
        ``arrived``, so the call ages from when the TURN first asked instead
        of being the youngest waiter at every suspend, and ``own_lane``, the
        lane just handed back, which R1 gives it before it considers anything
        else. On a different pool there is nothing to suspend and both stay
        None.
        """
        handle, _arrived = self._wait_for_lane(
            pool_key, cache_key, priority,
            label or "nested", who=cache_key, arrived=arrived,
            own_lane=own_lane, nested=True)
        return handle

    def chat_lane_context(self, task_id: str) -> Tuple[str, int]:
        """``(lane pool, lane priority)`` of a live registration, or
        ``("", Priority.NORMAL)`` when there is no such registration.

        The nested-call path asks BEFORE it suspends anything, and it needs
        both answers from the same lookup: the POOL, because a tool LLM on
        another pool must not cost the conversation its lane (the tool alias
        and the chat model are different hosts in the normal topology), so
        only a nested call on the SAME pool is preceded by R6 — and the
        PRIORITY, because the nested call runs on the turn's behalf and must
        rank exactly as the turn does, thought turns included.
        """
        from app.core.llm_lanes import pool_key_for

        with self._lock:
            task = self._chat_tasks.get(task_id)
            if task is None:
                return ("", int(Priority.NORMAL))
            model = task.model
            priority = int(task._lane_priority)
        return (pool_key_for(self.provider.name, model), priority)

    def suspend_chat_lane(self, task_id: str) -> Optional[Tuple[int, float]]:
        """R6: gives back the lane of a LIVE registration for the duration of
        a nested call on the SAME pool.

        The registration itself stays in the books — the panel keeps showing
        the turn and ``register_chat_done`` still closes it. The return value
        is ``(lane id, arrival stamp)`` of what was handed back, and it is the
        turn's identity for the two acquires that follow: the nested call and
        the resume take that lane id along so R4 does not hold either of them
        off their own lane, and that arrival stamp so the turn goes on ageing
        from when it FIRST asked instead of arriving anew at every suspend.
        ``None`` means there was nothing to give back (unknown id, or already
        suspended), and then nothing must be re-taken either.
        """
        with self._lock:
            task = self._chat_tasks.get(task_id)
            if task is None:
                return None
            handle = self._chat_lanes.pop(task_id, None)
            arrived = task._lane_arrived
            # Nothing may report this registration as holding a lane while it
            # does not — the log line of the nested call reads it from here.
            task._lane_handle = None
        if handle is None:
            return None
        lane_id = handle.lane_id
        handle.release()
        return (lane_id, arrived)

    def resume_chat_lane(self, task_id: str, own_lane: Optional[int] = None,
                         arrived: Optional[float] = None) -> None:
        """Takes a lane again for a registration that was suspended (R6).

        Waits like the registration itself did, and with the turn's OWN
        arrival stamp and lane id (see ``suspend_chat_lane``): a resume that
        stamped itself fresh would be the youngest waiter on the pool every
        time and lose to anything parked there. A registration that was
        closed or swept away meanwhile gets nothing — and a lane handed out
        in that race is released again right here instead of being lost.
        """
        with self._lock:
            task = self._chat_tasks.get(task_id)
            if task is None or task_id in self._chat_lanes:
                return
        from app.core.llm_lanes import pool_key_for

        handle, arrived = self._wait_for_lane(
            pool_key_for(self.provider.name, task.model), task._cache_key,
            task._lane_priority, task.task_type, who=task.agent_name or "?",
            arrived=arrived, own_lane=own_lane, nested=True)
        with self._lock:
            if task_id in self._chat_tasks and task_id not in self._chat_lanes:
                task._lane_arrived = arrived
                task._lane_handle = handle
                self._chat_lanes[task_id] = handle
                return
        handle.release()

    def _release_chat_lane(self, task_id: str) -> None:
        """Gives the lane of a streaming registration back.

        Keyed by task_id, not by the task object: whatever happened to the
        _chat_tasks entry in between (popped by the stale check, never
        inserted because the caller was cancelled), the handle stays reachable
        and is released exactly once — release() itself is idempotent.
        Callers hold ``self._lock``; the lane manager never takes it back, so
        the order stays one-way.
        """
        handle = self._chat_lanes.pop(task_id, None)
        if handle is not None:
            handle.release()

    def _release_serialize_gate_if_held(self) -> None:
        """Releases the serialize-group gate if this channel holds it because of
        active chats. Idempotent (double-release safe via flag under lock)."""
        if self._serialize_gate is None:
            return
        _release = False
        with self._lock:
            if self._holds_serialize_gate:
                self._holds_serialize_gate = False
                _release = True
        if _release:
            self._serialize_gate.release()

    def register_chat_done(self, task_id: str) -> None:
        """Chat/story finished. Resumes queue only when ALL chats are done."""
        with self._lock:
            task = self._chat_tasks.pop(task_id, None)
            self._release_chat_lane(task_id)
            if task:
                task.status = "completed"
                task.duration_s = 0
                self._history.append(task)
                if len(self._history) > self._history_limit:
                    self._history = self._history[-self._history_limit:]
                agent = task.agent_name
            else:
                agent = "?"
            remaining = len(self._chat_tasks)

        # Resume queue only when NO more active chats on this provider
        if remaining == 0:
            self._chat_active.set()
            self._release_serialize_gate_if_held()  # release gate (last chat gone)
            logger.info("[%s] Chat beendet: %s (%s) — Queue fortgesetzt (keine aktiven Chats)",
                        self._queue_name, agent, task_id)
        else:
            logger.info("[%s] Chat beendet: %s (%s) — Queue bleibt pausiert (%d aktive Chats)",
                        self._queue_name, agent, task_id, remaining)

    def cancel_task(self, task_id: str) -> bool:
        """Cancels a pending or running task. Returns True if found and cancelled."""
        with self._lock:
            # 1. Pending tasks
            for task in self._pending_tasks:
                if task.task_id == task_id and task.status == "pending":
                    task._cancelled = True
                    task.status = "cancelled"
                    task.error = "Cancelled"
                    self._pending_tasks.remove(task)
                    self._history.append(task)
                    if len(self._history) > self._history_limit:
                        self._history = self._history[-self._history_limit:]
                    task._done_event.set()
                    logger.info("[%s] Abgebrochen (pending): %s (%s) agent=%s",
                                self._queue_name, task.task_id, task.task_type, task.agent_name)
                    return True

            # 2. Running tasks — set cancelled flag + cancel future
            for task in self._current_tasks:
                if task.task_id == task_id and task.status == "running":
                    task._cancelled = True
                    future = self._futures.get(task_id)
                    if future:
                        future.cancel()
                    logger.info("[%s] Abbruch angefordert (running): %s (%s) agent=%s",
                                self._queue_name, task.task_id, task.task_type, task.agent_name)
                    return True
        return False

    def has_pending_tasks(self) -> bool:
        """Returns True if there are pending tasks in the queue."""
        with self._lock:
            return len(self._pending_tasks) > 0 or not self._queue.empty()

    def get_status(self) -> Dict[str, Any]:
        """Queue status for this provider."""
        with self._lock:
            chat_list = [t.to_dict() for t in self._chat_tasks.values()]
            # Backwards-compatible: single chat_active field
            chat = chat_list[0] if len(chat_list) == 1 else (chat_list if chat_list else None)
            current = [t.to_dict() for t in self._current_tasks]
            pending = [t.to_dict() for t in self._pending_tasks
                       if t.status == "pending"]
            recent = [t.to_dict() for t in reversed(self._history[-20:])]

        return {
            "provider": self.provider.name,
            "queue_name": self._queue_name,
            "type": self.provider.type,
            "available": self.provider.available,
            "max_concurrent": self._max_concurrent,
            "serialize_group": self.serialize_group,
            "chat_active": chat,
            "current_tasks": current,
            "pending": pending,
            "recent": recent,
        }

    def _worker_count(self) -> int:
        """How many worker threads this channel runs.

        A worker holds at most one lane, so fewer threads than the channel's
        LLM entries have lanes would cap the parallelism below what the
        entries allow. An image-backend channel has no LLM entries and keeps
        its permit count.
        """
        try:
            from app.core.llm_lanes import configured_lane_total
            lanes = configured_lane_total(self.provider.name)
        except Exception:
            lanes = 0
        return max(1, self._max_concurrent, lanes)

    def _ensure_workers(self) -> None:
        """Brings the worker threads up to ``_worker_count()``.

        Tops up while the queue is already running, instead of only starting
        a fresh set when it was idle: the count follows the lane totals of the
        config, so raising the lanes of an LLM entry in the admin used to have
        no effect until the queue happened to fall idle — on a busy provider
        that is exactly when it never happens.

        Threads that ended are dropped first: a worker leaves the list itself
        when it goes idle, but one that died on an unexpected exception would
        otherwise count forever and block the top-up.
        """
        with self._lock:
            self._workers = [w for w in self._workers if w.is_alive()]
            self._running = True
            for _ in range(self._worker_count() - len(self._workers)):
                t = threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name=f"ProviderQueue-{self._queue_name}-{len(self._workers)}")
                self._workers.append(t)
                t.start()

    _STALE_CHAT_TIMEOUT = 660  # 11 minutes — emergency brake for hanging chat registrations.
    # Must be > THOUGHT_CALL_TIMEOUT (default 600s) so the regular
    # asyncio.wait_for in thoughts.py fires before this emergency brake.
    # This stale cleanup is only a backup for when the cancel does not take
    # effect either (e.g. a real browser reload during streaming, a tool crash
    # without finally).

    def _check_stale_chat(self) -> None:
        """Checks whether chat registrations went stale and cleans them up.

        Uses the per-task _monotonic_created — the global _chat_registered_at
        is overwritten by every new registration and is therefore useless for
        aging individual stuck tasks. Typical stuck case: browser reload during
        streaming, generate() never runs its finally, the chat_tasks entry
        stays behind.
        """
        now = time.monotonic()
        cleaned = []
        with self._lock:
            if not self._chat_tasks:
                return
            stale_ids = []
            for tid, task in self._chat_tasks.items():
                t_created = getattr(task, "_monotonic_created", 0.0)
                if t_created <= 0:
                    # Legacy entry without a timestamp → treat as stale at once
                    stale_ids.append(tid)
                    continue
                age = now - t_created
                if age > self._STALE_CHAT_TIMEOUT:
                    stale_ids.append(tid)

            for tid in stale_ids:
                task = self._chat_tasks.pop(tid)
                self._release_chat_lane(tid)
                task.status = "completed"
                self._history.append(task)
                cleaned.append((task.agent_name, tid))

            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]
            remaining = len(self._chat_tasks)
            if remaining == 0:
                self._chat_registered_at = 0.0

        for agent, tid in cleaned:
            logger.warning("[%s] Stale Chat bereinigt: %s (%s) nach %ds",
                          self._queue_name, agent, tid, self._STALE_CHAT_TIMEOUT)
        if cleaned and remaining == 0:
            self._chat_active.set()
            self._release_serialize_gate_if_held()  # stale chat gone -> release gate
            logger.info("[%s] Queue fortgesetzt (alle stale Chats bereinigt)", self._queue_name)

    def _acquire_lane(self, task: LLMTask) -> bool:
        """Tries ONCE to take a cache lane for a queued LLM task. Never blocks.

        The pool is provider/model of the task, the key its prompt beginning
        (task class + character). Two things must not happen here, which is
        why this does not wait:

        * A queued task must never run WITHOUT a lane — that is unbounded
          parallelism on a model whose whole point is that only N prompt
          beginnings exist at a time.
        * A worker must never park on a full pool. Workers belong to the
          PROVIDER, lanes to the MODEL: a worker waiting for one model's pool
          would starve every other model of the same provider.

        No lane free -> False, and the caller puts the task back unchanged.
        The arrival stamp is taken on the FIRST attempt and kept on the task,
        so a task that is re-queued a few times still ages from when it really
        arrived (what R2/R3 will read in phase 2).
        """
        from app.core.llm_lanes import (
            LaneTimeout, cache_key_for, get_lane_manager, pool_key_for,
        )
        pool_key = pool_key_for(task.provider_name or self.provider.name,
                                task.model)
        task._cache_key = cache_key_for(task.task_type, task.agent_name)
        manager = get_lane_manager()
        # Live config: an admin save changes the lane count without a restart.
        manager.sync_from_config(pool_key)
        if not task._lane_arrived:
            task._lane_arrived = manager.now()
        try:
            task._lane_handle = manager.acquire_lane(
                pool_key, task._cache_key, task.priority,
                timeout=0, arrived=task._lane_arrived, label=task.task_type)
            return True
        except LaneTimeout:
            task._lane_handle = None
            return False

    def _release_slot(self, task: LLMTask) -> None:
        """Gives back what _worker_loop took for this task — a permit for a
        GPU task, a lane for an LLM task. Mirrors every release path."""
        if task._gpu_callable is not None:
            self._semaphore.release()
            return
        handle = task._lane_handle
        if handle is not None:
            handle.release()
            task._lane_handle = None

    def _requeue(self, prio: int, seq: int, task: LLMTask) -> None:
        """Puts a popped task back UNCHANGED — same priority, same sequence
        number, so the queue order is exactly what it was — and balances the
        get() with a task_done()."""
        self._queue.put((prio, seq, task))
        self._queue.task_done()

    def _flush_deferred(self, deferred: List[Tuple[int, int, LLMTask]]) -> None:
        """Puts back every task of this pass that found no free lane.

        Unchanged, and each with the ``task_done()`` its ``get()`` owes the
        queue. A deferred task is invisible to the other workers while the
        list holds it, so this runs BEFORE anything long starts — a task must
        never wait out a call it has nothing to do with.
        """
        while deferred:
            prio, seq, task = deferred.pop()
            self._requeue(prio, seq, task)

    def _worker_loop(self) -> None:
        """Processes LLM tasks. Pauses when chat is active on this provider."""
        # Tasks of this pass whose pool had no free lane. They are held HERE
        # rather than put straight back: the queue orders by (priority,
        # sequence), so a task put back would be the very next one popped and
        # the worker would never get past it to a task of another pool.
        deferred: List[Tuple[int, int, LLMTask]] = []
        while True:
            # Wait until chat is not active on this provider (with stale check)
            if self._chat_pause_enabled:
                if deferred and not self._chat_active.is_set():
                    # About to park for a chat: held-back tasks belong in the
                    # queue, not in a parked worker.
                    self._flush_deferred(deferred)
                while not self._chat_active.wait(timeout=30):
                    self._check_stale_chat()

            try:
                if deferred:
                    # Holding tasks back, so never park on the queue: those
                    # tasks are invisible to the other workers while this list
                    # owns them, and a 5-s block would hide them for 5 s. An
                    # empty queue lands in the Empty branch below, which puts
                    # them back at once.
                    prio, seq, task = self._queue.get_nowait()
                else:
                    prio, seq, task = self._queue.get(timeout=5.0)
            except queue.Empty:
                if deferred:
                    # Another worker emptied the queue while we were holding
                    # tasks back. They belong to the queue, not to a worker
                    # that is about to go idle.
                    self._flush_deferred(deferred)
                    continue
                with self._lock:
                    if self._queue.empty():
                        self._running = False
                        self._workers = [
                            w for w in self._workers
                            if w is not threading.current_thread()
                        ]
                        if not self._workers:
                            logger.debug("[%s] Worker idle, beendet", self._queue_name)
                        return
                continue

            # Skip cancelled tasks
            if task._cancelled:
                self._queue.task_done()
                continue

            # Occupy the execution slot: a GPU task takes one of the
            # channel's permits (the backend is the limit there), an LLM task
            # takes a CACHE LANE of its provider/model pool — that is where
            # LLM concurrency is decided now.
            if task._gpu_callable is not None:
                # The permit wait can be long; do not hold other tasks for it.
                self._flush_deferred(deferred)
                self._semaphore.acquire()
            elif not self._acquire_lane(task):
                # The pool of THIS task is full. Hold it back and carry on
                # with the next task: lanes belong to the MODEL, workers to
                # the PROVIDER, so another model of the same provider may well
                # have a free lane — waiting here would starve it for a pool
                # that is not even its own.
                deferred.append((prio, seq, task))
                if self._queue.empty():
                    # A whole pass over the queue without a single runnable
                    # task: put everything back and wait a moment, instead of
                    # spinning on the same head over and over.
                    self._flush_deferred(deferred)
                    time.sleep(_LANE_RETRY_SLEEP)
                continue
            # A slot in hand: hand the held tasks back BEFORE anything long
            # starts (see _flush_deferred).
            self._flush_deferred(deferred)

            # A chat that registered while we were taking the slot: give the
            # slot back and re-queue UNCHANGED (same priority/seq, so the
            # order stays stable) instead of waiting with it in hand. A
            # streaming registration wants a lane of the same pool, so waiting
            # here would block exactly the chat we are waiting for. The next
            # pass parks at the top of the loop, without a slot.
            if self._chat_pause_enabled and not self._chat_active.is_set():
                self._release_slot(task)
                self._requeue(prio, seq, task)
                continue

            # Re-check cancelled after taking the slot
            if task._cancelled:
                self._release_slot(task)
                self._queue.task_done()
                continue

            # Serialize-group gate: serializes work across all channels with
            # the same serialize_group. Blocks here if another channel (e.g. a
            # streaming chat or another backend in the same group) is currently
            # busy. None = no gate (default).
            if self._serialize_gate is not None:
                self._serialize_gate.acquire()
                # The gate can hold us for minutes (an image generation on the
                # same GPU) — and we are holding a lane the whole time. A chat
                # that registered meanwhile wants a lane of this very pool, so
                # give both back and re-queue, exactly as above the gate.
                if self._chat_pause_enabled and not self._chat_active.is_set():
                    self._serialize_gate.release()
                    self._release_slot(task)
                    self._requeue(prio, seq, task)
                    continue

            with self._lock:
                self._current_tasks.append(task)
            task.status = "running"
            task.started_at = utc_now_iso()
            _attach_duration_estimate(task)
            logger.info("[%s] Verarbeite: %s (%s) agent=%s",
                        self._queue_name, task.task_id, task.task_type, task.agent_name)

            t0 = time.monotonic()
            task_timeout = self.provider.timeout or 300  # default 5 min
            gpu_callable = task._gpu_callable

            if gpu_callable:
                # GPU-slot task: run the callable (e.g. image generation)
                try:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(gpu_callable)
                        with self._lock:
                            self._futures[task.task_id] = future
                        result = _wait_for_future(future, task, task_timeout)
                    task.result = result
                    task.status = "completed"
                    task.duration_s = round(time.monotonic() - t0, 2)
                    logger.info("[%s] GPU-Task fertig: %s (%ss)",
                                self._queue_name, task.task_id, task.duration_s)
                except _CancelledByUser:
                    task.status = "cancelled"
                    task.error = "Cancelled"
                    task.duration_s = round(time.monotonic() - t0, 2)
                    logger.info("[%s] GPU-Task abgebrochen: %s (%ss)",
                                self._queue_name, task.task_id, task.duration_s)
                except FuturesTimeoutError:
                    task.status = "failed"
                    task.error = f"Task timeout nach {task_timeout}s"
                    task.duration_s = round(time.monotonic() - t0, 2)
                    logger.error("[%s] GPU-Task Timeout: %s nach %ds",
                                 self._queue_name, task.task_id, task_timeout)
                except Exception as e:
                    if task._cancelled:
                        task.status = "cancelled"
                        task.error = "Cancelled"
                        task.duration_s = round(time.monotonic() - t0, 2)
                        logger.info("[%s] GPU-Task abgebrochen: %s", self._queue_name, task.task_id)
                    else:
                        err_str = str(e)
                        is_retriable = any(pat in err_str for pat in _RETRIABLE_GPU_ERRORS)
                        if is_retriable and task._retry_count < _GPU_MAX_RETRIES:
                            # Retry: unload VRAM, re-queue task
                            task._retry_count += 1
                            task.duration_s = round(time.monotonic() - t0, 2)
                            logger.warning(
                                "[%s] GPU-Task OOM, Retry %d/%d: %s — VRAM freigeben und erneut versuchen",
                                self._queue_name, task._retry_count, _GPU_MAX_RETRIES, task.task_id)
                            self.provider._do_unload()
                            time.sleep(5)  # Wait for VRAM to be freed by llama-swap
                            # Re-queue: reset status, put back in queue
                            task.status = "pending"
                            task.error = ""
                            with self._lock:
                                if task in self._current_tasks:
                                    self._current_tasks.remove(task)
                                self._seq_counter += 1
                                seq = self._seq_counter
                                self._pending_tasks.append(task)
                                self._futures.pop(task.task_id, None)
                            self._queue.put((task.priority, seq, task))
                            if self._serialize_gate is not None:
                                self._serialize_gate.release()
                            self._release_slot(task)
                            self._queue.task_done()
                            continue  # Skip normal cleanup — task is re-queued
                        else:
                            task.status = "failed"
                            task.error = err_str
                            # Keep the original exception object: submit_gpu_task
                            # re-raises it in the caller thread so typed errors
                            # (e.g. imagegen's BackendBusyError) survive the queue.
                            task._exception = e
                            task.duration_s = round(time.monotonic() - t0, 2)
                            if is_retriable:
                                logger.error("[%s] GPU-Task OOM nach %d Retries: %s: %s",
                                             self._queue_name, task._retry_count, task.task_id, e)
                            else:
                                logger.error("[%s] GPU-Task Fehler: %s: %s",
                                             self._queue_name, task.task_id, e, exc_info=True)
                finally:
                    with self._lock:
                        self._futures.pop(task.task_id, None)
            else:
                # Standard LLM-Task
                model_name = get_model_name(task._llm)
                max_tokens = _get_max_tokens_safe(task._llm)
                api_base = getattr(task._llm, 'openai_api_base', None) or getattr(task._llm, 'base_url', '?')
                logger.debug("[%s] -> model=%s api_base=%s max_tokens=%s", self._queue_name, model_name, api_base, max_tokens)

                try:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(task._llm.invoke, task._messages)
                        with self._lock:
                            self._futures[task.task_id] = future
                        response = _wait_for_future(future, task, task_timeout)
                    # Strip thinking tags from response (Qwen3.5 etc.)
                    response = _strip_thinking(response)

                    # Retry on an empty response. Two cases: with max_tokens
                    # set, the thinking probably ate the whole budget ->
                    # double it; without max_tokens a reasoning model emitted
                    # EOS right after an empty think block (signature: usage
                    # reports few completion tokens, content empty) — that is
                    # stochastic, an unchanged retry usually heals it.
                    resp_content = getattr(response, "content", None) or ""
                    if not resp_content.strip():
                        from app.utils.llm_logger import extract_token_info
                        _hidden = extract_token_info(response).get("output_tokens", 0)
                        logger.warning(
                            "[%s] Leere Response: %s (%s) agent=%s model=%s — "
                            "%d Token(s) ohne Content (Reasoning-Kanal?), Retry %s",
                            self._queue_name, task.task_id, task.task_type,
                            task.agent_name, model_name, _hidden,
                            ("mit max_tokens=%d (vorher %d)" % (max_tokens * 2, max_tokens))
                            if max_tokens else "unveraendert")
                        orig_max = task._llm.max_tokens
                        if max_tokens:
                            task._llm.max_tokens = max_tokens * 2
                        try:
                            with self._lock:
                                self._futures.pop(task.task_id, None)
                            with ThreadPoolExecutor(max_workers=1) as executor2:
                                future2 = executor2.submit(task._llm.invoke, task._messages)
                                with self._lock:
                                    self._futures[task.task_id] = future2
                                response = _wait_for_future(future2, task, task_timeout)
                            response = _strip_thinking(response)
                        finally:
                            task._llm.max_tokens = orig_max

                    task.result = response
                    task.status = "completed"
                    task.duration_s = round(time.monotonic() - t0, 2)
                    logger.info("[%s] Fertig: %s (%ss)", self._queue_name, task.task_id, task.duration_s)

                    _log_task_result(task, model_name, max_tokens, response)
                except _CancelledByUser:
                    task.status = "cancelled"
                    task.error = "Cancelled"
                    task.duration_s = round(time.monotonic() - t0, 2)
                    logger.info("[%s] Task abgebrochen: %s (%s) (%ss)",
                                self._queue_name, task.task_id, task.task_type, task.duration_s)
                except FuturesTimeoutError:
                    task.status = "failed"
                    task.error = f"Task timeout nach {task_timeout}s"
                    task.duration_s = round(time.monotonic() - t0, 2)
                    logger.error("[%s] Task Timeout: %s (%s) nach %ds — Queue wird fortgesetzt",
                                 self._queue_name, task.task_id, task.task_type, task_timeout)
                    _log_task_result(task, model_name, max_tokens, None, error=task.error)
                except Exception as e:
                    if task._cancelled:
                        task.status = "cancelled"
                        task.error = "Cancelled"
                        task.duration_s = round(time.monotonic() - t0, 2)
                        logger.info("[%s] Task cancelled: %s (%s)",
                                    self._queue_name, task.task_id, task.task_type)
                    else:
                        task.status = "failed"
                        task.error = str(e)
                        # Keep the original exception: submit() chains it as
                        # __cause__ so the final ERROR in llm_router carries the
                        # stack from the HTTP layer, not just the wrapper.
                        task._exception = e
                        task.duration_s = round(time.monotonic() - t0, 2)
                        log_task_failure(self._queue_name, task, e)
                        _log_task_result(task, model_name, max_tokens, None, error=task.error)
                        cooldown_after_failure(self.provider, model_name, task.task_type, e)
                finally:
                    with self._lock:
                        self._futures.pop(task.task_id, None)

            # Move to history
            with self._lock:
                if task in self._current_tasks:
                    self._current_tasks.remove(task)
                self._history.append(task)
                if len(self._history) > self._history_limit:
                    self._history = self._history[-self._history_limit:]

            # Release LLM/messages (memory)
            task._llm = None
            task._messages = None

            # Unblock caller
            task._done_event.set()

            # Release the serialize gate (before the slot, reverse acquire order)
            if self._serialize_gate is not None:
                self._serialize_gate.release()

            self._release_slot(task)

            self._queue.task_done()


_THINK_RE = re.compile(r'<think>.*?</think>\s*', re.DOTALL)
_THINK_OPEN_RE = re.compile(r'<think>.*', re.DOTALL)


def _strip_thinking(response) -> Any:
    """Remove <think>...</think> blocks from LLM response content.

    Handles both complete blocks and truncated thinking (when max_tokens
    cuts off mid-think without closing </think> tag).
    """
    content = getattr(response, "content", None)
    if not content or not isinstance(content, str):
        return response
    if "<think>" not in content:
        return response
    # First remove complete <think>...</think> blocks
    cleaned = _THINK_RE.sub("", content).strip()
    # Then remove truncated <think>... (no closing tag, hit max_tokens)
    if "<think>" in cleaned:
        cleaned = _THINK_OPEN_RE.sub("", cleaned).strip()
    response.content = cleaned
    return response


def _get_max_tokens_safe(llm) -> int:
    """Extracts max_tokens from the LLM instance.

    Returns 0 when the client carries no completion limit — that is "no limit
    configured, the provider's default budget applies", NOT "could not be
    determined". Both client classes always define ``max_tokens`` (the
    Anthropic one even forces a value), so a missing attribute cannot occur;
    ``tokens.max: 0`` in llm_calls.jsonl therefore reads unambiguously as
    "unlimited from our side".
    """
    val = getattr(llm, "max_tokens", None)
    return int(val) if val else 0


def _log_task_result(task: LLMTask, model_name: str, max_tokens: int, response,
                     error: str = "") -> None:
    """Logs a completed OR FAILED LLM task to the JSONL file.

    On failure (timeout / backend error) ``response`` is None and ``error``
    carries the message — the full prompt is still logged so the exact failing
    request can be inspected afterwards.

    This is where the provider's ``finish_reason`` reaches the JSONL: the whole
    LLM path runs through the queue, so the caller never sees the raw response
    object. Providers that send no reason leave the field out of the line.
    """
    try:
        from app.utils.llm_logger import log_llm_call, extract_token_info, estimate_tokens

        token_info = extract_token_info(response) if response is not None else {}
        response_text = getattr(response, "content", None)
        if response_text is None:
            response_text = "" if (error or response is None) else str(response)

        # Separate the system prompt from the rest so the logger writes both
        # fields cleanly (otherwise system ends up in the user field).
        system_text = ""
        prompt_text = ""
        if isinstance(task._messages, list):
            user_parts = []
            for m in task._messages:
                if isinstance(m, dict):
                    role = m.get("role", "?")
                    content = m.get("content", "")
                    if isinstance(content, list):
                        # vision messages with multi-content
                        content = " ".join(
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    elif content is None:
                        content = ""
                else:
                    role = getattr(m, "type", "?")
                    content = getattr(m, "content", str(m))
                if role == "system" and not system_text:
                    system_text = content
                else:
                    user_parts.append(f"[{role}] {content}")
            prompt_text = "\n".join(user_parts)
        elif isinstance(task._messages, str):
            prompt_text = task._messages

        tokens_in = token_info.get("input_tokens", 0) or estimate_tokens(system_text + prompt_text)
        tokens_out = token_info.get("output_tokens", 0) or estimate_tokens(response_text)

        log_llm_call(
            task=task.task_type,
            model=model_name,
            agent_name=task.agent_name,
            provider=task.provider_name,
            system_prompt=system_text,
            user_input=prompt_text,
            response=response_text,
            duration_s=task.duration_s,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            max_tokens=max_tokens,
            tokens_cached=token_info.get("cached_tokens"),
            label=getattr(task, "label", "") or "",
            trace_id=getattr(task, "trace_id", "") or "",
            trace_kind=getattr(task, "trace_kind", "") or "",
            finish_reason=getattr(response, "finish_reason", None) or "",
            lane=(task._lane_handle.lane_id
                  if task._lane_handle is not None else None),
            cache_key=getattr(task, "_cache_key", "") or "",
            llm=task._llm,
            error=error)
    except Exception as e:
        logger.error("Logging error: %s", e, exc_info=True)


def _attach_duration_estimate(task: LLMTask) -> None:
    """Computes the expected duration of this call from historic stats and
    stores it on `task` (visible to the queue panel).

    Called when processing starts — not at submit time — so only calls that
    really run on a provider get an estimate. GPU-slot tasks (image
    generation) get no LLM estimate.
    """
    if task._gpu_callable is not None:
        return
    if not task.model or not task.task_type:
        return
    try:
        from app.utils.llm_logger import estimate_tokens
        from app.utils.llm_stats import estimate_duration

        # chat_active tasks have no _messages — then without input scaling,
        # estimate_duration automatically falls back to the plain median.
        in_tokens = _estimate_in_tokens(task._messages, estimate_tokens) \
            if task._messages is not None else 0
        est = estimate_duration(task.model, task.task_type,
                                provider=task.provider_name, in_tokens=in_tokens)
        if not est:
            return
        task.estimated_in_tokens = in_tokens
        task.estimated_duration_s = est["est_duration_s"]
        task.estimated_p90_s = est["p90_duration_s"]
        task.estimated_samples = est["samples"]
    except Exception as e:
        logger.debug("Dauer-Schaetzung fehlgeschlagen: %s", e)


def _estimate_in_tokens(messages, estimate_fn) -> int:
    """Collects the text from messages_or_prompt and estimates the token count."""
    if isinstance(messages, str):
        return estimate_fn(messages)
    if not isinstance(messages, list):
        return 0
    total = 0
    for m in messages:
        if isinstance(m, dict):
            content = m.get("content", "")
        else:
            content = getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        elif content is None:
            content = ""
        if content:
            total += estimate_fn(content)
    return total
