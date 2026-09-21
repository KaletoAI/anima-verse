"""ChatTaskManager — decouples LLM generation from the HTTP request lifecycle.

When a chat message is sent, generate() runs as an asyncio background task that
writes SSE chunks into an in-memory buffer.  The browser subscribes via a separate
GET /chat/{user_id}/stream/{task_id} endpoint that replays buffered chunks and then
tails live output — making the stream reconnect-safe across page refreshes.

Task lifecycle:  pending → running → done | error
Cleanup: finished tasks are purged after TASK_TTL_S seconds; an entry that
never leaves pending/running is dropped after STUCK_TTL_S so the dict cannot
grow for the lifetime of the process.
"""

import asyncio
import time
import uuid
from typing import AsyncGenerator, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("chat_task_manager")

TASK_TTL_S = 600       # 10 minutes — enough for any LLM + reconnect window
# Hard cap for an entry that is still pending/running. A generator that hangs
# (or a feed task that never started) keeps its status forever, so the TTL
# above would never touch it. Generous on purpose: this is a technical leak
# stop, not a timeout — a real turn is long over after half an hour.
STUCK_TTL_S = TASK_TTL_S * 3
CLEANUP_INTERVAL_S = 60


class ChatTask:
    __slots__ = ("task_id", "user_id", "status", "buffer", "created_at",
                 "runner")

    def __init__(self, task_id: str, user_id: str = "") -> None:
        self.task_id = task_id
        self.user_id = user_id
        self.status = "pending"   # pending | running | done | error
        self.buffer: List[str] = []
        self.created_at = time.monotonic()
        # The asyncio task that fills `buffer` (see start_feed). The event
        # loop only keeps a WEAK reference to a running task, so without this
        # one the feed can be garbage-collected mid-turn: the stream would
        # stop silently and the browser would poll `subscribe` forever.
        self.runner: Optional["asyncio.Task"] = None


class ChatTaskManager:
    """Singleton — manages background chat tasks and SSE buffer delivery."""

    def __init__(self) -> None:
        self._tasks: Dict[str, ChatTask] = {}
        # Same reason as ChatTask.runner: the periodic cleanup must not be
        # collected while it sleeps.
        self._cleanup_task: Optional["asyncio.Task"] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_task(self, user_id: str = "") -> str:
        """Creates a task entry and returns the task_id."""
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = ChatTask(task_id=task_id, user_id=user_id)
        logger.info("[ChatTask] Created %s user=%s", task_id, user_id or "-")
        return task_id

    def get_task_owner(self, task_id: str) -> str:
        """Liefert die user_id des Task-Erstellers (leer wenn unbekannt)."""
        task = self._tasks.get(task_id)
        return task.user_id if task else ""

    def start_feed(
        self, task_id: str, generator: AsyncGenerator[str, None]
    ) -> Optional["asyncio.Task"]:
        """Starts ``feed_from_generator`` as a background task AND keeps it.

        This is the only way the routes may start a feed: a bare
        ``asyncio.create_task(...)`` whose result is thrown away may be
        collected while it runs (the loop holds no strong reference), and the
        turn would then die silently with the subscriber waiting for a status
        that never changes.
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.error("[ChatTask] start_feed: unknown task_id %s", task_id)
            return None
        runner = asyncio.create_task(self.feed_from_generator(task_id, generator))
        task.runner = runner
        return runner

    async def feed_from_generator(
        self, task_id: str, generator: AsyncGenerator[str, None]
    ) -> None:
        """Drains an async generator into the task buffer.
        Started via start_feed() so it outlives the HTTP request.
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.error("[ChatTask] feed_from_generator: unknown task_id %s", task_id)
            return

        task.status = "running"
        try:
            async for chunk in generator:
                task.buffer.append(chunk)
            task.status = "done"
            logger.info("[ChatTask] Done  %s  chunks=%d", task_id, len(task.buffer))
        except asyncio.CancelledError:
            task.status = "error"
            task.buffer.append('data: {"error": "Task abgebrochen"}\n\n')
            logger.warning("[ChatTask] Cancelled %s", task_id)
            raise
        except Exception as exc:
            task.status = "error"
            import json as _json
            task.buffer.append(f"data: {_json.dumps({'error': str(exc)})}\n\n")
            logger.error("[ChatTask] Error %s: %s", task_id, exc, exc_info=True)

    async def subscribe(
        self, task_id: str, from_offset: int = 0
    ) -> AsyncGenerator[str, None]:
        """Yields SSE frames for a task.

        Replays buffer from from_offset, then tails live output until the task
        finishes.  Sends a heartbeat comment every ~15 s while waiting for new data.
        """
        task = self._tasks.get(task_id)
        if task is None:
            yield 'data: {"error": "Task nicht gefunden oder abgelaufen"}\n\n'
            return

        pos = from_offset
        heartbeat_ticks = 0

        while True:
            # Drain any buffered chunks
            while pos < len(task.buffer):
                yield task.buffer[pos]
                pos += 1

            if task.status in ("done", "error"):
                break

            # Poll every 100 ms; send heartbeat every ~15 s
            await asyncio.sleep(0.1)
            heartbeat_ticks += 1
            if heartbeat_ticks >= 150:   # 150 * 100ms = 15s
                yield ": heartbeat\n\n"
                heartbeat_ticks = 0

    def get_task(self, task_id: str) -> Optional[ChatTask]:
        return self._tasks.get(task_id)

    def cleanup_old_tasks(self) -> int:
        """Removes expired tasks. Returns count removed.

        Finished entries go after TASK_TTL_S. Entries still pending/running
        go after STUCK_TTL_S, whatever their status — without that cap a
        hanging generator (or a feed that never started) keeps its ChatTask
        and its whole buffer for the lifetime of the process. A runner that
        is still alive at that point is cancelled, so it stops feeding a
        buffer nobody can reach any more.
        """
        now = time.monotonic()
        to_delete = []
        for tid, t in self._tasks.items():
            age = now - t.created_at
            if t.status in ("done", "error"):
                if age > TASK_TTL_S:
                    to_delete.append(tid)
            elif age > STUCK_TTL_S:
                to_delete.append(tid)
        for tid in to_delete:
            task = self._tasks.pop(tid, None)
            if task is None:
                continue
            runner = task.runner
            task.runner = None
            if runner is not None and not runner.done():
                logger.warning("[ChatTask] Stuck task %s (%s) cancelled after %ds",
                               tid, task.status, int(now - task.created_at))
                runner.cancel()
        if to_delete:
            logger.debug("[ChatTask] Cleaned up %d expired tasks", len(to_delete))
        return len(to_delete)

    def start_cleanup_loop(self) -> None:
        """Starts the periodic cleanup coroutine. Call once from server lifespan."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_S)
            try:
                self.cleanup_old_tasks()
            except Exception as exc:
                logger.error("[ChatTask] Cleanup error: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_manager: Optional[ChatTaskManager] = None


def get_chat_task_manager() -> ChatTaskManager:
    global _manager
    if _manager is None:
        _manager = ChatTaskManager()
    return _manager
