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
from typing import Any, Dict, Optional

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
    # Monotonically increasing timestamp — used for stale detection so that
    # server clock changes/drift cannot distort it.
    _monotonic_created: float = field(default=0.0, repr=False)

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
        """Async wrapper: runs the blocking _tasks_idle.wait() in the threadpool
        so the event loop does not stall while we wait for the provider to idle.

        Async code MUST use this variant. Sync code (worker threads) keeps
        using register_chat_active().
        """
        import asyncio
        return await asyncio.to_thread(
            self.register_chat_active,
            agent_name, llm_instance=llm_instance,
            task_type=task_type, label=label,
        )

    def register_chat_done(self, task_id: str) -> None:
        """Chat/story finished. The queue resumes."""
        from .provider_manager import get_provider_manager
        pm = get_provider_manager()
        pm.register_chat_done(task_id)

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
        """Resolves provider name from a LLMClient's api_base.

        Matches the LLMClient's api_base against all known providers.
        Returns provider name if found, None otherwise.
        """
        try:
            from .provider_manager import get_provider_manager

            api_base = (getattr(llm, "openai_api_base", "")
                        or getattr(llm, "base_url", "")
                        or "")
            api_base = api_base.rstrip("/")
            if not api_base:
                return None

            pm = get_provider_manager()
            for name, provider in pm.providers.items():
                if provider.api_base.rstrip("/") == api_base:
                    return name

        except Exception:
            pass

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
