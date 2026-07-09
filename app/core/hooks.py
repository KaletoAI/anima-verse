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
from typing import Any, Callable, Dict, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Provider registry — a single implementation of a named CAPABILITY.
# ---------------------------------------------------------------------------
# Distinct from the event bus above: emit()/register() fan out to many
# listeners; a provider is exactly one function that answers a capability
# (e.g. "romantic_compatibility"). A package supplies it at load; the core
# names only the capability string, never the package (R1). Last
# registration wins; get_provider returns None when nobody supplied it, so
# the core falls back to a neutral default.

_providers: Dict[str, Callable] = {}


def register_provider(capability: str, fn: Callable) -> None:
    _providers[capability] = fn


def unregister_provider(capability: str) -> None:
    _providers.pop(capability, None)


def get_provider(capability: str) -> Optional[Callable]:
    return _providers.get(capability)
