"""How a Blender run or a CPU task ended — one closed vocabulary for every caller.

``runner.run`` puts one of these under ``"outcome"``; the refit pool's tracked
rows and the garment/figure steps speak the same words. A caller decides by the
outcome, never by matching ``error`` text:

- ``OK``          — done.
- ``REJECTED``    — the script ran to its end and reported failure itself: a
                    verdict about THIS input (the same input gives the same answer).
- ``TIMEOUT``     — the run exceeded its time budget (load-dependent; says
                    nothing about the input).
- ``INTERRUPTED`` — ended from outside without a verdict: the host shuts down,
                    Blender was killed by a signal that was not our timeout,
                    the refit pool was torn down, the work was left for later.
- ``CANCELLED``   — a user cancelled it (set by the layer that knows the cancel:
                    the garment run's Cancel / the TaskPanel — never the runner).
- ``UNAVAILABLE`` — Blender disabled, not found or not startable.
- ``CRASHED``     — a defect: unknown script, no result, unreadable result,
                    declared output missing, input vanished.

Only ``REJECTED`` is a verdict about the input; ``TIMEOUT``, ``INTERRUPTED`` and
``UNAVAILABLE`` leave the work due. ``RunFailed`` carries an outcome through
code that reports failure by raising; ``of_exception`` reads it back from an
exception chain. Importable without Blender, a world or the server.
"""
from typing import Optional

OK = "ok"
REJECTED = "rejected"
TIMEOUT = "timeout"
INTERRUPTED = "interrupted"
CANCELLED = "cancelled"
UNAVAILABLE = "unavailable"
CRASHED = "crashed"

ALL = (OK, REJECTED, TIMEOUT, INTERRUPTED, CANCELLED, UNAVAILABLE, CRASHED)


def is_verdict(outcome: Optional[str]) -> bool:
    """The run judged its input (``REJECTED``): the same input fails the same way."""
    return outcome == REJECTED


def is_retryable(outcome: Optional[str]) -> bool:
    """The run says nothing about its input and the work stays due (``TIMEOUT``, ``INTERRUPTED``,
    ``UNAVAILABLE``)."""
    return outcome in (TIMEOUT, INTERRUPTED, UNAVAILABLE)


class RunFailed(RuntimeError):
    """A failed run reported by raising: ``outcome`` (one of ``ALL``) and the Blender ``log_tail`` ride along, so
    a handler further up classifies it by ``of_exception`` instead of by its text."""

    def __init__(self, message: str, outcome: str, log_tail: str = ""):
        super().__init__(message)
        self.outcome = outcome
        self.log_tail = log_tail


def of_exception(e: Optional[BaseException]) -> Optional[str]:
    """The outcome an exception chain carries: the first ``outcome`` attribute (one of ``ALL``) along
    ``__cause__`` / ``__context__`` — ``RunFailed``, ``refit_pool.RefitInterrupted`` — else None."""
    seen = set()
    cur = e
    while cur is not None and id(cur) not in seen:
        found = getattr(cur, "outcome", None)
        if found in ALL:
            return found
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return None
