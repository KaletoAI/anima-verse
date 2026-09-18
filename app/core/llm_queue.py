"""Central LLM queue — facade over the ProviderManager.

Keeps LLMTask and Priority as the canonical definitions. LLMQueue itself
delegates every call to the ProviderManager, which routes it to the right
provider queue.

Existing consumers (social_reactions, instagram_skill, talkto_skill, etc.)
can keep using get_llm_queue().submit() unchanged.

Usage:
    from app.core.llm_queue import get_llm_queue, Priority

    queue = get_llm_queue()
    response = queue.submit("image_prompt", Priority.NORMAL, llm, messages, agent_name="Pixel")
"""
import threading  # noqa: F401  (still used for LLMTask._done_event)
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable, Dict, Optional

from app.core.log import get_logger

logger = get_logger("llm_queue")


class Priority(IntEnum):
    """Task priorities. Lower value = higher priority."""
    CHAT = 0        # tracking only (not queued)
    HIGH = 10       # story_stream
    NORMAL = 20     # image_prompt, extraction, history_summary, instagram_caption, image_comment
    IMAGE_GEN = 25  # image_generation via GPU slot (between NORMAL and LOW)
    LOW = 30        # talk_to, random_event, consolidation


@dataclass
class LLMTask:
    """One LLM task in the queue."""
    task_id: str
    task_type: str
    priority: int
    agent_name: str
    created_at: str
    status: str = "pending"       # pending, running, completed, failed, cancelled, chat_active
    result: Any = None
    error: str = ""
    duration_s: float = 0.0
    provider_name: str = ""
    model: str = ""
    started_at: str = ""        # when the task actually starts processing (not the queue submit)
    label: str = ""             # optional user-friendly label for the task panel
    # Iteration tracking for chat_active tasks (a StreamingAgent can make
    # several LLM calls per turn: initial → tool call → follow-up). Updated
    # by the agent via register_chat_iteration(). 0 = not started yet.
    current_iteration: int = 0
    max_iterations: int = 1
    # Duration estimate — set when processing starts (not at submit time), so
    # only calls that really run on a provider get a display value.
    estimated_duration_s: float = 0.0
    estimated_p90_s: float = 0.0
    estimated_in_tokens: int = 0
    estimated_samples: int = 0
    # Turn trace — captured at SUBMIT time from the caller's context
    # (app/core/turn_trace.py). The worker THREAD that executes the task
    # does not inherit that context, so the correlation has to ride on the
    # task object to reach the JSONL logger. Empty = call outside any
    # action root, stays ungrouped.
    trace_id: str = ""
    trace_kind: str = ""
    # Internal fields (not part of the status output)
    _llm: Any = field(default=None, repr=False)
    _messages: Any = field(default=None, repr=False)
    _done_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _cancelled: bool = field(default=False, repr=False)
    _retry_count: int = field(default=0, repr=False)
    # Who reports a failure of this task — stamped at SUBMIT time from the
    # caller's context (provider_queue.caller_handles_failure), because the
    # worker THREAD does not inherit it (same reason as trace_id). True = a
    # caller retries this call over its own fallback chain and writes the
    # ERROR itself once the chain is exhausted.
    _caller_handles_failure: bool = field(default=False, repr=False)
    # The original exception of a failed task, kept by the worker so the
    # caller thread can chain it as __cause__ (LLM path) or re-raise it
    # typed (GPU path, e.g. BackendBusyError). repr=False keeps the whole
    # traceback out of the task representation in logs.
    _exception: Optional[BaseException] = field(default=None, repr=False)
    # The work of a GPU-slot task (e.g. image generation), stamped at submit
    # time by ProviderQueue.submit_gpu_task. Its presence is what makes the
    # worker take the GPU branch instead of the LLM branch — None means a
    # plain LLM task. repr=False keeps the callable out of the task
    # representation in logs.
    _gpu_callable: Optional[Callable[[], Any]] = field(default=None, repr=False)
    # Monotonically increasing timestamp — used for stale detection so that
    # server clock changes/drift cannot distort it.
    _monotonic_created: float = field(default=0.0, repr=False)
    # Cache lane this task occupies while it runs (app/core/llm_lanes.py) and
    # the prompt-prefix key it was assigned for. The handle rides on the task
    # because the streaming path takes the lane in register_chat_active and
    # gives it back in register_chat_done; both fields also reach the JSONL
    # logger, which runs in the worker thread.
    _lane_handle: Any = field(default=None, repr=False)
    _cache_key: str = field(default="", repr=False)
    # The priority this call carries IN THE LANES. Not the same thing as
    # `priority`: that one pauses the provider queue and is what the admin
    # panel shows, and every streaming registration sets it to CHAT — thought
    # turns included. For the lanes a thought is background work, so the lane
    # priority follows the prompt class instead (llm_lanes.lane_priority_for).
    # Set in ProviderQueue._acquire_chat_lane; queued tasks use `priority`.
    _lane_priority: int = field(default=int(Priority.NORMAL), repr=False)
    # When this call FIRST asked for a lane, on the lane manager's clock. A
    # queued task asks again on every pass of the worker; the stamp stays at
    # the first attempt so the call really ages while it waits (what the lane
    # rules R2/R3 read).
    _lane_arrived: float = field(default=0.0, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes for the REST endpoint (without internal fields)."""
        d = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "priority": self.priority,
            "agent_name": self.agent_name,
            "created_at": self.created_at,
            "status": self.status,
            "error": self.error,
            "duration_s": self.duration_s,
        }
        if self.started_at:
            d["started_at"] = self.started_at
        if self.provider_name:
            d["provider_name"] = self.provider_name
        if self.model:
            d["model"] = self.model
        if self.label:
            d["label"] = self.label
        if self.current_iteration > 0:
            d["iteration"] = self.current_iteration
            d["max_iterations"] = self.max_iterations
        if self._retry_count > 0:
            d["retry_count"] = self._retry_count
        if self.estimated_duration_s > 0:
            d["estimated_duration_s"] = round(self.estimated_duration_s, 1)
            d["estimated_p90_s"] = round(self.estimated_p90_s, 1)
            d["estimated_samples"] = self.estimated_samples
        return d


class LLMQueue:
    """Facade over the ProviderManager — routes tasks to the right provider queue.

    The global pause was removed — disabling a task now runs through the
    router (app/core/llm_task_state.py). A disabled task gets no LLM from the
    router and the caller falls back on its own path.
    """

    def submit(
        self,
        task_type: str,
        priority: int,
        llm: Any,
        messages_or_prompt: Any,
        agent_name: str = "", label: str = "") -> Any:
        """Hands an LLM call to the right provider queue.

        Determines the provider from the LLMClient's api_base and delegates
        to the matching ProviderQueue.
        """
        from .provider_manager import get_provider_manager

        pm = get_provider_manager()
        provider_name = self._resolve_provider_name(llm)

        if provider_name:
            pq = pm.get_queue_for_provider(provider_name)
            if pq:
                return pq.submit(task_type, priority, llm, messages_or_prompt,
                                 agent_name, label=label)

        # Fallback: first available queue
        pq = pm.get_first_queue()
        if pq:
            return pq.submit(task_type, priority, llm, messages_or_prompt,
                             agent_name, label=label)

        raise Exception("No provider queue available for LLM call")

    def submit_gpu_task(
        self,
        provider_name: str = "",
        task_type: str = "",
        priority: int = 20,
        callable_fn=None,
        agent_name: str = "", label: str = "",
        gpu_type: str = "") -> Any:
        """Hands a GPU-slot task to the provider queue.

        Routing: gpu_type for dynamic routing (preferred), provider_name as fallback.
        """
        from .provider_manager import get_provider_manager
        pm = get_provider_manager()
        return pm.submit_gpu_task(provider_name, task_type, priority, callable_fn,
                                  agent_name, label,
                                  gpu_type=gpu_type)

    def register_chat_active(self, agent_name: str, llm_instance: Any = None,
                             task_type: str = "chat_stream",
                             label: str = "") -> str:
        """Registers an active chat/story. Pauses the provider queue.

        Args:
            agent_name: Character name
            user_id: User ID
            llm_instance: Optional LLMInstance for provider-aware routing.
                          If not given, uses first available queue.
            task_type: differentiates entries in panel
                ("chat_stream", "thought", "talk_to", "send_message", ...)
            label: short user-friendly label

        Returns:
            task_id for register_chat_done()
        """
        from .provider_manager import get_provider_manager

        pm = get_provider_manager()

        if llm_instance:
            return pm.register_chat_active(llm_instance, agent_name, task_type=task_type, label=label)

        # Fallback: first available queue
        pq = pm.get_first_queue()
        if pq:
            return pq.register_chat_active(agent_name, task_type=task_type, label=label)

        raise Exception("No provider queue available for chat registration")

    async def register_chat_active_async(self, agent_name: str, llm_instance: Any = None,
                                          task_type: str = "chat_stream",
                                          label: str = "") -> str:
        """Async wrapper: runs the blocking registration in the threadpool so
        the event loop does not stall while we wait for a cache lane of this
        model's pool (app/core/llm_lanes.py).

        Async code MUST use this variant. Sync code (worker threads) keeps
        using register_chat_active().

        CANCELLATION-SAFE. Cancelling the caller (thoughts.py wraps the whole
        turn in a wait_for) does not stop the thread — it registers, takes a
        lane and hands back a task_id that nobody would ever be able to close
        again: the lane would be lost for the lifetime of the process. The
        registration is therefore shielded and, if the caller is gone by the
        time it finishes, closed right here. The caller still sees the
        CancelledError it asked for.
        """
        import asyncio

        pending = asyncio.ensure_future(asyncio.to_thread(
            self.register_chat_active,
            agent_name, llm_instance=llm_instance,
            task_type=task_type, label=label,
        ))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            pending.add_done_callback(self._close_orphaned_registration)
            raise

    def _close_orphaned_registration(self, done) -> None:
        """Closes a registration whose caller was cancelled while it waited.

        Runs as the done-callback of the shielded task above, so it also
        consumes an exception the abandoned registration may carry. It must
        never raise: it runs on the event loop, with nobody left to handle
        anything.
        """
        try:
            if done.cancelled():
                return
            if done.exception() is not None:
                return
            task_id = done.result()
            if not task_id:
                return
            self.register_chat_done(task_id)
            logger.info("chat registration %s closed — its caller was cancelled "
                        "before it was handed over", task_id)
        except Exception as e:
            logger.error("could not close the orphaned chat registration: %s", e)

    def register_chat_done(self, task_id: str) -> None:
        """Chat/story finished. The queue resumes."""
        from .provider_manager import get_provider_manager
        pm = get_provider_manager()
        pm.register_chat_done(task_id)

    def nested_call_lane(self, chat_task_id: str, llm_instance: Any,
                         cache_key: str, label: str = ""):
        """Context manager for an LLM call made from inside a running chat
        turn — the rp_first tool decision (plan-cache-lanes.md item 7a).

        Blocks: call it from a worker thread (``asyncio.to_thread``), never on
        the event loop. It yields the lane handle, or None when there is no
        channel at all to take one from — then the call runs as it did before
        lanes existed, which is still better than dropping the turn.
        """
        from .provider_manager import get_provider_manager

        return get_provider_manager().nested_call_lane(
            chat_task_id, llm_instance, cache_key, label=label)

    def register_chat_iteration(self, task_id: str,
                                 iteration: int, max_iterations: int) -> None:
        """Update iteration count on a chat_active task.

        Called by StreamingAgent at the start of each iteration so the
        admin queue panel can show "iter 2/3" while the turn runs.
        """
        from .provider_manager import get_provider_manager
        pm = get_provider_manager()
        pm.register_chat_iteration(task_id, iteration, max_iterations)

    def has_pending_tasks(self) -> bool:
        """Returns True if any provider queue has pending tasks."""
        from .provider_manager import get_provider_manager
        pm = get_provider_manager()
        return pm.has_pending_tasks()

    def get_status(self) -> Dict[str, Any]:
        """Queue status aggregated over all providers."""
        from .provider_manager import get_provider_manager
        pm = get_provider_manager()
        return pm.get_combined_status()

    def _resolve_provider_name(self, llm: Any) -> Optional[str]:
        """The provider of a bare ``LLMClient``, by its endpoint.

        The matching itself lives in ``ProviderManager.provider_name_for`` —
        one place, because the lane pool a call lands on is derived from this
        name and two answers would mean two pools for one backend.
        """
        try:
            from .provider_manager import get_provider_manager

            return get_provider_manager().provider_name_for(llm) or None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------
_llm_queue: Optional[LLMQueue] = None


def get_llm_queue() -> LLMQueue:
    """Returns the global LLMQueue facade."""
    global _llm_queue
    if _llm_queue is None:
        _llm_queue = LLMQueue()
        logger.info("Facade initialized (delegates to ProviderManager)")
    return _llm_queue
