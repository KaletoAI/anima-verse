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


def set_trace(t: Optional[Dict[str, str]]) -> None:
    """Set the active trace explicitly. ``None`` clears it — used where a
    trace was begun in a context that outlives the action (an awaited
    coroutine writes into its caller's context; await does not copy)."""
    _trace.set(t)


def bind_trace(fn, trace: Optional[Dict[str, str]] = None):
    """Wrap ``fn`` so it runs with ``trace`` active (default: the trace active
    at wrap time) and restores the previous value afterwards.

    Needed for hand-offs into plain threads and executor pools: a fresh thread
    starts trace-free, and a pooled thread keeps whatever the previous job left
    in its context. Passing the trace BY VALUE instead of copying the whole
    caller context keeps unrelated context vars (e.g. a suppressed perception
    shadow) out of the background job.
    """
    t = current_trace() if trace is None else trace

    def _wrapped(*args, **kwargs):
        token = _trace.set(t)
        try:
            return fn(*args, **kwargs)
        finally:
            _trace.reset(token)

    return _wrapped
