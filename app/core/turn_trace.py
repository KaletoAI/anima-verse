"""Turn trace — correlates every LLM call of one action (a respond turn,
a thought turn, a user chat message) under one short trace id, so the
LLM log can group them. Propagates via contextvars: through await,
asyncio.create_task and asyncio.to_thread automatically; plain
threading.Thread spawns must capture the context explicitly
(contextvars.copy_context().run) or pass the trace by value.
"""
import contextvars, uuid
from typing import Optional, Dict

_trace: contextvars.ContextVar[Optional[Dict[str, str]]] = \
    contextvars.ContextVar("turn_trace", default=None)


def begin_trace(kind: str, who: str = "") -> Dict[str, str]:
    """Start a new trace at an action root. Overwrites any inherited
    trace (a worker coroutine inherits the dispatcher's context)."""
    t = {"id": uuid.uuid4().hex[:10], "kind": kind, "who": who}
    _trace.set(t)
    return t


def current_trace() -> Optional[Dict[str, str]]:
    return _trace.get()
