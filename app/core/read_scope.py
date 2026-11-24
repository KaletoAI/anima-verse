"""Read scope: per-request counters of repeated sub-calls (plan 2026-11-24-figure-poll-caches, Task 0).

``measure()`` opens a counting scope in the current context and yields its counter dict;
``tally(name)`` adds one to ``name`` in every scope open in this context. Nested scopes each get
their own dict and the outer one counts the inner calls too. The scopes live in a ``ContextVar``:
a ``threading.Thread`` started inside a scope does not inherit it (a new thread starts with an
empty context), so a background thread never counts into a request's scope.

Without an open scope ``tally`` costs one ``ContextVar.get`` and does nothing. Statistics must
never disturb the measured path: ``tally`` never raises.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Iterator, Tuple

_scopes: ContextVar[Tuple[Dict[str, int], ...]] = ContextVar("read_scope_measure", default=())


@contextmanager
def measure() -> Iterator[Dict[str, int]]:
    """Open a counting scope; yields its counter dict (name -> count), filled by ``tally``."""
    counts: Dict[str, int] = {}
    token = _scopes.set(_scopes.get() + (counts,))
    try:
        yield counts
    finally:
        _scopes.reset(token)


def tally(name: str) -> None:
    """Count one call of ``name`` in every open scope of this context; a no-op without one."""
    try:
        for counts in _scopes.get():
            counts[name] = counts.get(name, 0) + 1
    except Exception:  # noqa: BLE001 — statistics never disturb the measured path
        pass
