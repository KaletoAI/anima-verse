"""Minimal hook bus (F5-light) — the core emits, packages listen.

Core code fires domain events generically via ``emit(event, **kwargs)``;
skill packages register callbacks at load time via ``register``. The
direction rule R1 stays intact: the core never imports package code — it
only names an EVENT, and nobody may be listening.

Registration is keyed by ``(event, tag)`` (tag defaults to the callback's
module+qualname), so a skill reload replaces its callback instead of
stacking duplicates. Callback errors are logged and never propagate into
the emitting core path.
"""
from typing import Any, Callable, Dict, Tuple

from app.core.log import get_logger

logger = get_logger("hooks")

_hooks: Dict[Tuple[str, str], Callable] = {}


def register(event: str, fn: Callable, tag: str = "") -> None:
    """Register a callback for an event (idempotent per (event, tag))."""
    key = (event, tag or f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}")
    _hooks[key] = fn


def unregister(event: str, tag: str) -> None:
    _hooks.pop((event, tag), None)


def emit(event: str, **kwargs: Any) -> int:
    """Fire an event. Returns the number of callbacks invoked."""
    count = 0
    for (ev, tag), fn in list(_hooks.items()):
        if ev != event:
            continue
        try:
            fn(**kwargs)
            count += 1
        except Exception as e:
            logger.error("hook %s (%s) failed: %s", event, tag, e, exc_info=True)
    return count
