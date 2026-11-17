"""The explicit mesh backend of one garment / shoe run (A187, item 5).

A click on a piece's mesh "Regenerate" may name a concrete img2mesh backend instead of "Auto (routing)". The pick
rides on the queued run (``garments._Job.backend``); the character's garment worker sets it here for the duration of
that run, and the two mesh steps (``garment_mesh._attempt``, ``footwear_source._mesh_attempt``) hand it to
``generate_mesh(backend_glob=…)`` — an explicit pick, never routed elsewhere, no fallback. "" = the occasion's
routing chain. A ``ContextVar``: one worker thread's run never sees another's pick.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_PICK: ContextVar[str] = ContextVar("explicit_mesh_backend", default="")


def current() -> str:
    """The explicit mesh backend of the run in this thread, "" = Auto (routing)."""
    return _PICK.get()


@contextmanager
def use(name: str) -> Iterator[None]:
    """Set the explicit mesh backend for the body of the ``with`` ("" = Auto)."""
    token = _PICK.set(str(name or "").strip())
    try:
        yield
    finally:
        _PICK.reset(token)
