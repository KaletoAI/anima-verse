"""Read scope: count which read functions a computation calls, and memoise them for one read request, per context.

``measure()`` opens a counter dict for the current context (a ``contextvars.ContextVar``) and yields it;
``tally(name)`` adds one to ``name`` in every open measure of the current context — nested measures each get
their own dict and the outer one counts the inner calls too. Outside a measure ``tally`` is a no-op that costs
one ``ContextVar.get``. A ``threading.Thread`` starts with an empty context, so a measure never counts the work
of a thread it starts (plan ``2026-11-24-figure-poll-caches.md``, Task 0).

Counting must never disturb the measured path: ``tally`` swallows its own errors.

The memo half (plan Task 5): ``scope()`` opens a memo dict for the current context — a nested ``scope()``
reuses the outer one — and ``memo(ns, key, compute)`` serves one computation per key inside it. Every caller,
the first one too, gets ``copy.deepcopy`` of the stored result, so no caller's mutation reaches the entry;
exceptions are not stored. The inputs a memoised function reads below its arguments (profile, items, sidecars) are
taken as constant for the scope's lifetime only: every writer of them calls ``clear()``, and a scope lives one
read request. Inside a scope ``get_character_profile`` serves the remembered profile even under
``keyed_lock("character_profile")``, so NO profile read-modify-write may run inside a scope (final review M3). Outside a scope ``memo`` just calls ``compute()``. A ``threading.Thread`` starts with an empty
context, so it never inherits a scope. Scopes are opened only in the read functions the plan names
(``scripts/smoke_read_scope.py`` [S9] guards it), never on a build path.
"""
import copy
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Hashable, Iterator, Optional, Tuple, TypeVar

T = TypeVar("T")

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


class _Scope:
    """One read scope: the memo entries, the remembered object signatures and an epoch that ``clear`` moves."""
    __slots__ = ("entries", "sigs", "epoch")

    def __init__(self) -> None:
        self.entries: Dict[Tuple[str, Hashable], Any] = {}
        #: id(obj) -> (obj, sig); the object is held so its id cannot be reused while the scope lives.
        self.sigs: Dict[int, Tuple[Any, Optional[str]]] = {}
        self.epoch = 0


_memo_scope: ContextVar[Optional[_Scope]] = ContextVar("read_scope_memo", default=None)


@contextmanager
def scope() -> Iterator[None]:
    """Open a memo scope for this context; a nested scope reuses the outer one."""
    if _memo_scope.get() is not None:
        yield
        return
    token = _memo_scope.set(_Scope())
    try:
        yield
    finally:
        _memo_scope.reset(token)


def active() -> bool:
    """Whether a memo scope is open in this context (the wrappers skip building their key without one)."""
    return _memo_scope.get() is not None


def memo(ns: str, key: Hashable, compute: Callable[[], T]) -> T:
    """``compute()`` once per ``(ns, key)`` inside a scope — every caller, the first one too, gets its own deep copy;
    without a scope it simply computes. An exception is not stored. A result computed while a writer cleared the
    scope is handed out but not stored (it may have read inputs from before the write)."""
    sc = _memo_scope.get()
    if sc is None:
        return compute()
    full = (ns, key)
    try:
        hit = full in sc.entries
    except TypeError:   # an unhashable key: no memo
        return compute()
    if hit:
        return copy.deepcopy(sc.entries[full])
    epoch = sc.epoch
    result = compute()
    if sc.epoch != epoch:
        return result
    stored = copy.deepcopy(result)
    sc.entries[full] = stored
    return copy.deepcopy(stored)


def _sig(obj: Any) -> Optional[str]:
    from app.core import figure
    try:
        return hashlib.sha1(figure._canonical(obj)).hexdigest()
    except Exception:  # noqa: BLE001 — an object that cannot be canonicalised has no signature
        return None


def obj_sig(obj: Any) -> Optional[str]:
    """``sha1(figure._canonical(obj))``, or None for None (and for an object that cannot be canonicalised — the
    memoised wrappers then compute without the memo). Inside a scope remembered per object (by ``id``, the object
    held so the id is not reused); without a scope hashed on every call."""
    if obj is None:
        return None
    sc = _memo_scope.get()
    if sc is None:
        return _sig(obj)
    held = sc.sigs.get(id(obj))
    if held is not None and held[0] is obj:
        return held[1]
    sig = _sig(obj)
    sc.sigs[id(obj)] = (obj, sig)
    return sig


def clear() -> None:
    """Drop every memo entry and remembered signature of this context's scope (a no-op without a scope)."""
    try:
        sc = _memo_scope.get()
        if sc is None:
            return
        sc.entries.clear()
        sc.sigs.clear()
        sc.epoch += 1
    except Exception:  # noqa: BLE001 — clearing never breaks a writer
        pass
