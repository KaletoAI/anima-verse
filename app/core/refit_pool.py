"""The process pool CPU refits compute on (spec
``docs/superpowers/specs/2026-11-12-parallel-cpu-refits-design.md``).

Refits (garment, footwear, HairDeck, outfit-body fits, layered builds) are pure
numpy/scipy. ``run(fn, *args)`` hands ONE pure compute call to a worker
process and waits for its result; the caller — a server thread that holds the
character's run lock, reads the records and publishes — stays exactly where it
was. Which calls go there is the seam each fit module draws between compute and
publication (``garments._fit`` / ``fit_on_body`` / ``_fit_seed`` /
``_publish_fit``, ``garment_footwear.fit``, ``garment_layers._build``): the
function handed in reads only its arguments (bytes, arrays, plain values) and
at most writes its output to the private temp path it was given. A worker
never opens ``world.db`` (``_initializer`` makes ``sqlite3.connect`` raise),
never takes a ``keyed_lock``, never writes a profile and never imports
``app.server``; it has no storage root either (``paths`` is not initialised
there).

- **Workers**: ``server.refit_workers`` (instance scope), 0 = auto =
  ``max(1, min(8, cpu_count - 2))``. 1 = no pool: every call runs in-process,
  today's behaviour. The pool exists only in the server: ``enable()`` from the
  lifespan, created lazily on the first call, ``shutdown()`` in the lifespan
  exit; scripts and smokes stay in-process unless they enable it.
- **Start method** spawn (forking a threaded server is unsafe). A worker runs
  at nice 10 with one BLAS thread (set before numpy is imported there) and
  ``OMP_NUM_THREADS`` = its share of the cores when every worker computes
  (``fit_threads_for(workers)``; for any other OpenMP user in the worker).
- **Thread budget** (``fit_kernels.threads()``: numba kernels, cKDTree
  ``workers=``, pykdtree's OpenMP threads (``fit_kernels.kdtree``), the EDT,
  the drape's CPU arch, the onnxruntime session of a BiRefNet matte
  (``character._get_rembg_session``)): one number the parent keeps
  current in a shared int every worker reads at each kernel call —
  ``fit_threads_for(n)`` with n = the calls computing in the pool right now.
  A fit that runs alone gets up to ``FIT_THREADS_MAX`` threads; n fits side by
  side share the cores less two, so they never oversubscribe them (the sum of
  the budgets is at most ``cpu_count - 2``). The kernels give the same bits
  for any thread count.
- **GPU compute** (``gpu_compute``): the worker gets the server's GPU slot
  folder, ``server.gpu_compute_parallel`` and ``server.gpu_compute_device``
  at spawn and resolves its device at its first job.
- **Lifetime** (Ruling A64): a worker never outlives the server. ``shutdown``
  (the lifespan exit) terminates the workers instead of letting them finish,
  and every worker watches its parent (``_watch_parent``): once the server
  process is gone — killed, crashed, stopped by the OOM killer, so no lifespan
  exit ran — the worker exits within ``PARENT_POLL_S``. A spawned worker holds
  the write end of its own call queue, so without the watch it would wait on
  that queue forever. ``prctl(PR_SET_PDEATHSIG)`` is not used: it fires when
  the THREAD that spawned the worker ends, and the pool spawns its workers from
  whichever server thread submits first — a refit run's thread that ends long
  before the server does.
- **Failure**: an exception raised in the worker comes back as itself (the
  caller records it as today). A crashed worker breaks the pool
  (``BrokenProcessPool``): the pool is dropped (the next call creates a new
  one) and every call it took down runs once more in a worker process of its
  own, one such re-run at a time (the worker limit holds after a break) — the
  call that crashes again fails alone (``WorkerCrashed``), the other
  characters' calls that were in flight complete.
- **Interruption** (review 01#1/#2): a call the POOL ended — the server stops
  (``shutdown``: its workers terminated, its queued calls cancelled) — raises
  ``RefitInterrupted``: no re-run, no defect of the piece. Callers record
  nothing for it (the next sweep / trigger fits the piece again). From the
  stop on (``closing``) every call raises it at once — none computes
  in-process any more, no pool is created — so the process exits promptly; the
  workers of every pool this process made (a pool replaced by a resize, a
  crash re-run's own) are ended with the current one.

The per-character runs are tracked tasks (``track`` / ``activate`` /
``finish``): ``task_type`` ``TASK_TYPE``, provider ``CPU_PROVIDER``,
``pending`` while waiting for a slot, ``running`` while computing, finished
at the end — Game-Admin's header indicator and the TaskPanel list them like
GPU jobs. Exempt from the 20-minute stale reaper (``track_hold``): a long
sweep's waiting characters never vanish from the header while they wait.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Optional

from app.blender import outcome as oc

logger = logging.getLogger(__name__)

#: The provider name of a CPU refit task (the TaskPanel / indicator show it).
CPU_PROVIDER = "CPU"
#: The task type of a tracked CPU refit.
TASK_TYPE = "cpu_refit"
#: The queue name of the tracked rows.
QUEUE_NAME = "cpu"
#: Upper bound of the auto worker count.
AUTO_MAX = 8
#: Upper bound of one fit's thread budget (``fit_threads_for``): a lone fit gains up to ~16 threads and nothing
#: past them (measured 2026-11-18, see ``fit_threads_for``).
FIT_THREADS_MAX = 16

_lock = threading.Lock()
_pool: Any = None
_pool_size = 0
_enabled = False
#: Set by the terminating ``shutdown`` (the server stops), cleared by ``enable``: every call raises
#: ``RefitInterrupted`` and no pool is created any more.
_closing = False
#: Crash re-runs' own pools while they compute (``_run_alone``): ``shutdown`` ends their workers too.
_alone: set = set()
#: Worker processes of pools replaced by a resize (shut down, their running calls still computing): a
#: shut-down ``ProcessPoolExecutor`` forgets its processes, so ``_get_pool`` keeps them for ``shutdown``.
_retired: list = []
#: One crash re-run at a time (``_run_alone``): a pool break never multiplies the worker processes.
_ALONE_LOCK = threading.Lock()
#: True inside a worker process (``_initializer``): a nested ``run`` computes in place.
_IN_WORKER = False
#: The workers' live thread budget: a shared int (``multiprocessing`` RawValue, handed to every worker at spawn),
#: written by ``_computing_changed`` whenever a pool call starts or ends. None until the first pool exists.
_BUDGET: Any = None
#: Pool calls computing right now (``_run``), under ``_lock``.
_computing = 0


class WorkerDatabaseAccess(RuntimeError):
    """A refit worker process tried to open a database."""


class RefitInterrupted(RuntimeError):
    """The refit pool ended this call — the server stops (``shutdown``), or the call was cancelled in the pool.
    No defect of the piece: callers record no refusal for it and stamp nothing, so the next sweep or trigger fits
    the piece again. Its ``outcome`` is ``INTERRUPTED`` (``app.blender.outcome.of_exception`` reads it)."""

    outcome = oc.INTERRUPTED


def closing() -> bool:
    """The server stops (the terminating ``shutdown`` ran): refit work ends instead of starting."""
    return _closing


def _interrupted(what: Any) -> RefitInterrupted:
    return RefitInterrupted(f"refit interrupted — the refit pool was shut down ({getattr(what, '__name__', what)})")


def auto_workers() -> int:
    """``max(1, min(AUTO_MAX, cpu_count - 2))``."""
    return max(1, min(AUTO_MAX, (os.cpu_count() or 1) - 2))


def configured_workers() -> int:
    """``server.refit_workers`` resolved: 0 / unset / unparsable = ``auto_workers``,
    else clamped to the schema's bounds."""
    from app.core import config
    from app.core.config_schema import SECTIONS
    field = SECTIONS["server"]["fields"]["refit_workers"]
    raw = config.get("server.refit_workers", None)
    try:
        value = int(raw) if raw not in (None, "") else int(field["default"])
    except (TypeError, ValueError):
        value = int(field["default"])
    if value <= 0:
        return auto_workers()
    return max(1, min(int(field["max"]), value))


def workers() -> int:
    """How many characters refit at once: 1 (in-process) unless the pool is
    enabled (the server) and outside a worker, else ``configured_workers``."""
    if _IN_WORKER or not _enabled:
        return 1
    try:
        return configured_workers()
    except Exception:  # noqa: BLE001 — a broken config never stops a refit
        logger.exception("Refit pool: worker count unreadable, running in-process")
        return 1


def fit_threads_for(computing: int) -> int:
    """One fit's thread budget while ``computing`` fits run side by side: ``(cpu_count - 2) // computing``, at most
    ``FIT_THREADS_MAX``, at least 1. n fits never get more than the cores less two together."""
    return max(1, min(FIT_THREADS_MAX, ((os.cpu_count() or 1) - 2) // max(1, int(computing))))


def _budget() -> Any:
    """The shared budget int (created with the first pool, in the spawn context its workers start in)."""
    global _BUDGET
    if _BUDGET is None:
        import multiprocessing
        _BUDGET = multiprocessing.get_context("spawn").RawValue("i", fit_threads_for(1))
    return _BUDGET


def _computing_changed(delta: int) -> None:
    """A pool call starts (+1) or ends (-1): the workers' budget follows the number computing now (calls beyond the
    pool's size wait for a worker and do not count)."""
    global _computing
    with _lock:
        _computing = max(0, _computing + delta)
        if _BUDGET is not None:
            _BUDGET.value = fit_threads_for(min(_computing, _pool_size) if _pool_size else _computing)


def enable(on: bool = True) -> None:
    """Allow the pool (the server lifespan; smokes that test it); ``on`` also ends a previous stop's ``closing``."""
    global _enabled, _closing
    _enabled = bool(on)
    if on:
        _closing = False


#: Seconds a worker waits between two looks at its parent (``_watch_parent``).
PARENT_POLL_S = 1.0
#: Seconds ``shutdown`` gives a terminated worker before it is killed.
TERMINATE_GRACE_S = 3.0


def _alive(proc: Any) -> bool:
    try:
        return bool(proc.is_alive())
    except (OSError, ValueError, AssertionError):
        return False


def _worker_processes(pool: Any) -> list:
    """The worker processes of ``pool`` (a ``ProcessPoolExecutor``) that are still alive (none once it is shut
    down: the executor forgets them then)."""
    procs = getattr(pool, "_processes", None) or {}
    return [proc for proc in list(procs.values()) if _alive(proc)]


def _end_processes(procs: list, grace: float = TERMINATE_GRACE_S) -> None:
    """SIGTERM every process of ``procs``, wait up to ``grace`` seconds in all, SIGKILL what is left."""
    import time
    for proc in procs:
        try:
            proc.terminate()
        except (OSError, ValueError, AttributeError):
            pass
    deadline = time.monotonic() + grace
    for proc in procs:
        try:
            proc.join(max(0.0, deadline - time.monotonic()))
            if proc.is_alive():
                proc.kill()
                proc.join(1.0)
        except (OSError, ValueError, AssertionError, AttributeError):
            pass


def shutdown(wait: bool = False, terminate: bool = True) -> None:
    """Shut the pool down (the lifespan exit) and disable it. ``terminate``
    (the default, Ruling A64): the workers are ended now — a computing one too,
    its call raises ``RefitInterrupted`` and its refit runs again on the next
    trigger — so none of them outlives the server, and from now on every call
    raises ``RefitInterrupted`` (``closing``: nothing is re-run, nothing
    computes in-process, no pool is created). The workers of every pool this
    process made are ended: the current one, a crash re-run's own, one
    replaced by a resize. ``wait`` True instead waits for the running calls
    (queued ones are cancelled: ``RefitInterrupted``) and later calls run
    in-process (the smokes)."""
    global _pool, _pool_size, _enabled, _closing
    ending = terminate and not wait
    with _lock:
        if ending:
            _closing = True
        pool, _pool, _pool_size = _pool, None, 0
        _enabled = False
        pools = ([pool] if pool is not None else []) + list(_alone)
        retired = list(_retired) if ending else []
        _retired.clear()
    procs = ([p for each in pools for p in _worker_processes(each)] + [p for p in retired if _alive(p)]
             if ending else [])
    for each in pools:
        try:
            each.shutdown(wait=wait, cancel_futures=True)
        except Exception:  # noqa: BLE001
            logger.exception("Refit pool: shutdown failed")
    if procs:
        _end_processes(procs)
        logger.info("Refit pool: %d worker process(es) ended", len(procs))


def _no_database(*_args: Any, **_kwargs: Any) -> Any:
    raise WorkerDatabaseAccess("a refit worker process never opens a database")


def _watch_parent(parent_pid: int, interval: float = PARENT_POLL_S) -> None:
    """In a worker: end this process as soon as its parent (the server, ``parent_pid``) is gone. A dead parent
    leaves the worker reparented (to init or a subreaper), so ``os.getppid()`` no longer names it. Checked once
    right away (the parent may have died while this worker started), then every ``interval`` seconds on a daemon
    thread. ``os._exit``: nothing of a worker needs cleaning up, and a computing main thread must not hold it."""
    import time

    def gone() -> bool:
        return os.getppid() != parent_pid

    if gone():
        os._exit(0)

    def loop() -> None:
        while True:
            time.sleep(interval)
            if gone():
                os._exit(0)

    threading.Thread(target=loop, name="refit-parent-watch", daemon=True).start()


def _initializer(blender_slots: Optional[tuple] = None, budget: Any = None,
                 parent_pid: Optional[int] = None, gpu: Optional[tuple] = None,
                 omp_threads: Optional[int] = None) -> None:
    """Runs first in every worker: no database, low priority, one BLAS thread;
    ``blender_slots`` (``runner.spawn_slots()`` of the server) pins the Blender
    limit's slot folder and count — a worker has no instance and no config;
    ``budget`` is the parent's live thread budget (a shared int,
    ``fit_kernels.follow``; None keeps the default);
    ``parent_pid`` (the server's pid) starts ``_watch_parent``, so the worker
    ends with the server (Ruling A64); ``gpu`` (``gpu_compute.spawn_spec()``)
    pins the GPU slots and the device setting; ``omp_threads`` (default 1) is
    ``OMP_NUM_THREADS`` for OpenMP users that do not follow the budget: the
    pool's share at full load, so all workers together never oversubscribe
    the cores (pykdtree and BiRefNet follow the budget itself since
    2026-11-18 — on the old ``OMP_NUM_THREADS=1`` a matte took 21-25 s
    instead of 6-8 s)."""
    global _IN_WORKER
    _IN_WORKER = True
    if parent_pid:
        _watch_parent(int(parent_pid))
    if blender_slots:
        from app.blender import runner
        runner.pin_slots(*blender_slots)
    # numpy is not imported yet in a fresh spawned worker: these take effect.
    for var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"
    os.environ["OMP_NUM_THREADS"] = str(max(1, int(omp_threads or 1)))
    if gpu:
        from app.core import gpu_compute
        gpu_compute.pin(gpu)
    if budget is not None:
        # after the BLAS variables: this import brings numpy in
        from app.core import fit_kernels
        fit_kernels.follow(budget)
    import sqlite3
    sqlite3.connect = _no_database  # type: ignore[assignment]
    sqlite3.dbapi2.connect = _no_database  # type: ignore[attr-defined]
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass


def _new_pool(size: int, share: Optional[int] = None) -> Any:
    """A pool of ``size`` workers that follow the live thread budget (``_budget``); their fixed OpenMP pools get
    ``fit_threads_for(share)`` threads (``share`` default ``size``: the share of each worker when all compute)."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from app.blender import runner
    from app.core import gpu_compute
    return ProcessPoolExecutor(max_workers=size, mp_context=multiprocessing.get_context("spawn"),
                               initializer=_initializer,
                               initargs=(runner.spawn_slots(), _budget(), os.getpid(), gpu_compute.spawn_spec(),
                                         fit_threads_for(share or size)))


def _get_pool(size: int) -> Any:
    """The pool of ``size`` workers, created on first use (or after a resize /
    a break). ``RefitInterrupted`` once the server stops (``closing``). A pool
    replaced by a resize finishes the calls it holds; its workers are kept
    for ``shutdown``."""
    global _pool, _pool_size
    with _lock:
        if _closing:
            raise RefitInterrupted("refit interrupted — the server stops")
        if _pool is not None and _pool_size == size:
            return _pool
        old, _pool, _pool_size = _pool, _new_pool(size), size
        pool = _pool
        if old is not None:
            _retired[:] = [p for p in _retired if _alive(p)] + _worker_processes(old)
        logger.info("Refit pool: %d worker process(es)", size)
    if old is not None:
        old.shutdown(wait=False)
    return pool


def _drop(pool: Any) -> None:
    """Forget a broken pool (the next call creates a new one). Only the CURRENT pool is shut down here: one
    already replaced (a resize, another caller's drop) is not this caller's to cancel — its other callers' queued
    calls would end as cancelled (review 01#2)."""
    global _pool, _pool_size
    with _lock:
        if _pool is not pool:
            return
        _pool, _pool_size = None, 0
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass


class WorkerCrashed(RuntimeError):
    """A refit worker process died while computing this call (twice: in the pool and alone)."""


def _run_alone(fn: Callable[..., Any], args: Any, kwargs: Any) -> Any:
    """``fn`` in a worker process of its own (after a pool break): a crash here is this call's alone. One re-run
    at a time (``_ALONE_LOCK``), on the live thread budget, so the calls a break took down never run beside each
    other in fresh processes beyond the worker limit (review 01#5). ``RefitInterrupted`` when
    the server stops meanwhile."""
    from concurrent.futures import CancelledError
    from concurrent.futures.process import BrokenProcessPool
    with _ALONE_LOCK:
        with _lock:
            if _closing:
                raise _interrupted(fn)
            ex = _new_pool(1, share=max(1, _pool_size or configured_workers()))
            _alone.add(ex)
        try:
            return ex.submit(fn, *args, **kwargs).result()
        except CancelledError as e:
            raise _interrupted(fn) from e
        except BrokenProcessPool as e:
            if _closing:
                raise _interrupted(fn) from e
            raise WorkerCrashed(f"the refit worker process crashed in {getattr(fn, '__name__', fn)}") from e
        except RuntimeError as e:
            if _closing:  # shut down by ``shutdown`` before the submit
                raise _interrupted(fn) from e
            raise
        finally:
            with _lock:
                _alone.discard(ex)
            ex.shutdown(wait=False, cancel_futures=True)


def run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``_run`` reporting live progress (A194): with a ``cpu_progress`` scope open, the call is named
    ``cpu:<function>`` and its inner ``cpu_progress.sub`` reports reach the scope — through a progress file when it
    runs in a worker process. Without a scope it is ``_run`` as is."""
    from app.core import cpu_progress
    if _closing:
        raise _interrupted(fn)
    if not cpu_progress.active():
        return _run(fn, *args, **kwargs)
    head = f"cpu:{getattr(fn, '__name__', 'compute')}"
    if workers() <= 1:
        with cpu_progress.attach(head):
            return fn(*args, **kwargs)
    try:
        path: Optional[str] = cpu_progress.progress_path("refit")
    except OSError:
        path = None
    with cpu_progress.attach(head, path):
        return _run(cpu_progress.run_reporting, path, fn, *args, **kwargs)


def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``fn(*args, **kwargs)`` — in a worker process when the pool is on
    (``workers() > 1``), else right here. ``fn`` must be a module-level pure
    function (picklable, like its arguments and result). Blocks until done; an
    exception of ``fn`` is raised here. A pool broken by a crashed worker is
    dropped (the next call creates a new one) and every call it took down is
    run once more in a worker process of its own — so a call that crashes
    again fails alone (``WorkerCrashed``) and the others complete. A call the
    pool ended (the server stops: ``closing``; cancelled in the pool) raises
    ``RefitInterrupted`` and is not run again."""
    if _closing:
        raise _interrupted(fn)
    size = workers()
    if size <= 1:
        return fn(*args, **kwargs)
    _computing_changed(+1)
    try:
        return _run_pooled(size, fn, args, kwargs)
    finally:
        _computing_changed(-1)


def _run_pooled(size: int, fn: Callable[..., Any], args: Any, kwargs: Any) -> Any:
    """``_run``'s pool path (counted in ``_computing``)."""
    from concurrent.futures import CancelledError
    from concurrent.futures.process import BrokenProcessPool
    pool = _get_pool(size)
    try:
        future = pool.submit(fn, *args, **kwargs)
    except BrokenProcessPool:
        # Broken meanwhile (a crash in another thread's call): a fresh pool.
        _drop(pool)
        pool = _get_pool(size)
        future = _submit_again(pool, fn, args, kwargs)
    except RuntimeError as e:
        # Shut down meanwhile: replaced by a resize (its calls finish there; this one goes to the new pool) or
        # the server stops.
        if _closing:
            raise _interrupted(fn) from e
        pool = _get_pool(size)
        future = _submit_again(pool, fn, args, kwargs)
    try:
        return future.result()
    except CancelledError as e:
        # Only a shutdown cancels a queued call (``cancel_futures``) — never a defect of the call.
        raise _interrupted(fn) from e
    except BrokenProcessPool as e:
        if _closing:
            # The stop terminated the workers: no crash, nothing runs again.
            raise _interrupted(fn) from e
        _drop(pool)
        logger.warning("Refit pool broke during %s — recreated; the call runs once more on its own",
                       getattr(fn, "__name__", fn))
        return _run_alone(fn, args, kwargs)


def _submit_again(pool: Any, fn: Callable[..., Any], args: Any, kwargs: Any) -> Any:
    """The second submit of ``_run`` (onto a fresh pool): a pool that is shut down or broken again at once was
    ended by the pool's own lifecycle (the stop, another resize) — ``RefitInterrupted``, never the call's
    defect."""
    try:
        return pool.submit(fn, *args, **kwargs)
    except RuntimeError as e:
        raise _interrupted(fn) from e


# --- shared compute ----------------------------------------------------------------

def graft_file(target_glb: bytes, garment: Any, name: str, extras: dict, out: str,
               material_overrides: Optional[dict] = None) -> int:
    """Pure compute for a worker: ``glb_mesh.graft`` written to the private temp
    path ``out`` (its folder is created); returns the triangle count of the
    result (``glb_mesh.static_arrays``) — what the publisher decimates by."""
    from pathlib import Path
    from app.core import glb_mesh
    more = {"material_overrides": material_overrides} if material_overrides is not None else {}
    blob = glb_mesh.graft(target_glb, garment, name=name, extras=extras, **more)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return len(glb_mesh.static_arrays(blob)[1])


def temp_path(final: Any) -> Any:
    """A private temp path beside ``final`` for a worker's output (a dot file
    the publisher renames into place or removes)."""
    import uuid
    from pathlib import Path
    final = Path(final)
    return final.with_name(f".{final.name}.{uuid.uuid4().hex[:12]}.refit.tmp")


# --- tracked tasks -----------------------------------------------------------------

def track(character_name: str, label: str, *, pending: bool = True) -> str:
    """Register a CPU refit for the header / TaskPanel; "" when the task queue
    is unavailable (the refit runs anyway)."""
    try:
        from app.core.task_queue import get_task_queue
        tq = get_task_queue()
        task_id = tq.track_start(TASK_TYPE, label, agent_name=character_name, provider=CPU_PROVIDER,
                                 queue_name=QUEUE_NAME, start_running=not pending)
        tq.track_hold(task_id)
        return task_id
    except Exception:  # noqa: BLE001 — visibility only
        logger.exception("Refit %s: tracked task not registered", character_name)
        return ""


def activate(task_id: str, label: Optional[str] = None) -> None:
    """The tracked refit starts computing (``running``); ``label`` updates it."""
    if not task_id:
        return
    try:
        from app.core.task_queue import get_task_queue
        tq = get_task_queue()
        if label:
            tq.track_update_label(task_id, label)
        tq.track_activate(task_id, queue_name=QUEUE_NAME, provider=CPU_PROVIDER)
    except Exception:  # noqa: BLE001
        logger.exception("Refit task %s: activation failed", task_id)


#: The tracked row's status per outcome (``finish``): work left due ends ``interrupted`` — the status a restart gives
#: an unfinished row — never ``failed``.
_ROW_STATUS = {oc.OK: "completed", oc.REJECTED: "failed", oc.CRASHED: "failed", oc.TIMEOUT: "interrupted",
               oc.INTERRUPTED: "interrupted", oc.UNAVAILABLE: "interrupted", oc.CANCELLED: "cancelled"}


def finish(task_id: str, error: str = "", *, outcome: Optional[str] = None, log_tail: str = "") -> None:
    """The tracked refit ended — only while its row is still open: one cancelled in the TaskPanel stays cancelled
    (review 01#3). ``outcome`` (``app.blender.outcome``; default ``OK`` without ``error``, else ``CRASHED``) sets
    the row's status (``_ROW_STATUS``) and lands with ``log_tail`` (a Blender run's end) in the row's progress
    (``{"outcome", "log_tail"}``), where the TaskPanel and a later UI read it."""
    if not task_id:
        return
    outcome = outcome or (oc.CRASHED if error else oc.OK)
    try:
        from app.core.task_queue import get_task_queue
        tq = get_task_queue()
        if tq.track_finish_if_open(task_id, error=error, status=_ROW_STATUS.get(outcome)) and outcome != oc.OK:
            tq.update_task_progress(task_id, {**tq.get_task_progress(task_id), "outcome": outcome,
                                              **({"log_tail": log_tail} if log_tail else {})})
    except Exception:  # noqa: BLE001
        logger.exception("Refit task %s: finish failed", task_id)


def end_of(e: BaseException) -> tuple:
    """``(outcome, error, log_tail)`` of an exception that ended a tracked refit: the outcome its chain carries
    (``RefitInterrupted`` → ``INTERRUPTED``, a ``RunFailed`` its own), else ``CRASHED``."""
    return (oc.of_exception(e) or oc.CRASHED, str(e) or type(e).__name__,
            next((getattr(x, "log_tail", "") for x in _chain(e) if getattr(x, "log_tail", "")), ""))


def _chain(e: Optional[BaseException]) -> list:
    out, seen = [], set()
    while e is not None and id(e) not in seen:
        out.append(e)
        seen.add(id(e))
        e = e.__cause__ or e.__context__
    return out


def discard(task_id: str) -> None:
    """Remove a tracked refit that did nothing (a busy character) — no history row."""
    if not task_id:
        return
    try:
        from app.core.task_queue import get_task_queue
        get_task_queue().track_discard(task_id)
    except Exception:  # noqa: BLE001
        logger.exception("Refit task %s: discard failed", task_id)


def release(task_id: str) -> None:
    """End a tracked refit only while it is still open (one cancelled in the TaskPanel keeps its status)."""
    if not task_id:
        return
    try:
        from app.core.task_queue import get_task_queue
        get_task_queue().track_finish_if_open(task_id)
    except Exception:  # noqa: BLE001
        logger.exception("Refit task %s: release failed", task_id)


def cancelled(task_id: str) -> bool:
    """The tracked refit was cancelled in the TaskPanel while it waited."""
    if not task_id:
        return False
    try:
        from app.core.task_queue import get_task_queue
        return get_task_queue().task_status(task_id) == "cancelled"
    except Exception:  # noqa: BLE001
        return False


#: Appended to a tracked refit's label while one of its Blender runs waits for a slot.
BLENDER_WAIT_SUFFIX = " · waiting for Blender"


def blender_wait_label(task_id: str, label: str) -> Any:
    """Context manager: while a Blender run of the block (this thread) waits for a slot
    (``runner.blender_slot``), the tracked refit's label reads ``<label> · waiting for Blender``."""
    from contextlib import nullcontext
    from app.blender import runner
    if not task_id:
        return nullcontext()

    def notice(waiting: bool) -> None:
        from app.core.task_queue import get_task_queue
        get_task_queue().track_update_label(task_id, label + BLENDER_WAIT_SUFFIX if waiting else label)

    return runner.wait_notice(notice)


def fits_label(character_name: str, n: Optional[int] = None) -> str:
    """``Refit · <name>`` / ``Refit · <name> (n fits)``."""
    if n is None:
        return f"Refit · {character_name}"
    return f"Refit · {character_name} ({n} fit{'' if n == 1 else 's'})"
