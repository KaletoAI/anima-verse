"""Read scope: count which read functions a computation calls, per context.

``measure()`` opens a counter dict for the current context (a ``contextvars.ContextVar``) and yields it;
``tally(name)`` adds one to ``name`` in every open measure of the current context — nested measures each get
their own dict and the outer one counts the inner calls too. Outside a measure ``tally`` is a no-op that costs
one ``ContextVar.get``. A ``threading.Thread`` starts with an empty context, so a measure never counts the work
of a thread it starts (plan ``2026-11-24-figure-poll-caches.md``, Task 0).

Counting must never disturb the measured path: ``tally`` swallows its own errors.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Iterator, Optional, Tuple

_scopes: ContextVar[Optional[Tuple[Dict[str, int], ...]]] = ContextVar("read_scope", default=None)


@contextmanager
def measure() -> Iterator[Dict[str, int]]:
    """A counter dict for the calls of ``tally`` inside this block (and inside nested measures)."""
    counts: Dict[str, int] = {}
    token = _scopes.set((_scopes.get() or ()) + (counts,))
    try:
        yield counts
    finally:
        _scopes.reset(token)


def tally(name: str) -> None:
    """Count one call of ``name`` in every open measure of this context; never raises."""
    try:
        scopes = _scopes.get()
        if not scopes:
            return
        for counts in scopes:
            counts[name] = counts.get(name, 0) + 1
    except Exception:  # noqa: BLE001 — statistics never disturb the measured path
        pass
