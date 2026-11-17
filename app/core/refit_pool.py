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
  at nice 10 with one BLAS thread (set before numpy is imported there).
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
  own — the call that crashes again fails alone (``WorkerCrashed``), the other
  characters' calls that were in flight complete.

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

logger = logging.getLogger(__name__)

#: The provider name of a CPU refit task (the TaskPanel / indicator show it).
CPU_PROVIDER = "CPU"
#: The task type of a tracked CPU refit.
TASK_TYPE = "cpu_refit"
#: The queue name of the tracked rows.
QUEUE_NAME = "cpu"
#: Upper bound of the auto worker count.
AUTO_MAX = 8

_lock = threading.Lock()
_pool: Any = None
_pool_size = 0
_enabled = False
#: True inside a worker process (``_initializer``): a nested ``run`` computes in place.
_IN_WORKER = False


class WorkerDatabaseAccess(RuntimeError):
    """A refit worker process tried to open a database."""


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


def enable(on: bool = True) -> None:
    """Allow the pool (the server lifespan; smokes that test it)."""
    global _enabled
    _enabled = bool(on)


#: Seconds a worker waits between two looks at its parent (``_watch_parent``).
PARENT_POLL_S = 1.0
#: Seconds ``shutdown`` gives a terminated worker before it is killed.
TERMINATE_GRACE_S = 3.0


def _worker_processes(pool: Any) -> list:
    """The worker processes of ``pool`` (a ``ProcessPoolExecutor``) that are still alive."""
    procs = getattr(pool, "_processes", None) or {}
    out = []
    for proc in list(procs.values()):
        try:
            if proc.is_alive():
                out.append(proc)
        except (OSError, ValueError, AssertionError):
            continue
    return out


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
    its refit is lost and runs again on the next trigger — so none of them
    outlives the server; ``wait`` True instead waits for the running calls."""
    global _pool, _pool_size, _enabled
    with _lock:
        pool, _pool, _pool_size = _pool, None, 0
        _enabled = False
    if pool is None:
        return
    procs = _worker_processes(pool) if terminate and not wait else []
    try:
        pool.shutdown(wait=wait, cancel_futures=True)
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


def _initializer(blender_slots: Optional[tuple] = None, fit_threads: Optional[int] = None,
                 parent_pid: Optional[int] = None) -> None:
    """Runs first in every worker: no database, low priority, one BLAS thread;
    ``blender_slots`` (``runner.spawn_slots()`` of the server) pins the Blender
    limit's slot folder and count — a worker has no instance and no config;
    ``fit_threads`` is the worker's share of the cores for the fit kernels and
    KD-tree queries (``fit_kernels.set_threads``; None keeps its default);
    ``parent_pid`` (the server's pid) starts ``_watch_parent``, so the worker
    ends with the server (Ruling A64)."""
    global _IN_WORKER
    _IN_WORKER = True
    if parent_pid:
        _watch_parent(int(parent_pid))
    if blender_slots:
        from app.blender import runner
        runner.pin_slots(*blender_slots)
    # numpy is not imported yet in a fresh spawned worker: these take effect.
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"
    if fit_threads:
        # after the BLAS variables: this import brings numpy in
        from app.core import fit_kernels
        fit_kernels.set_threads(fit_threads)
    import sqlite3
    sqlite3.connect = _no_database  # type: ignore[assignment]
    sqlite3.dbapi2.connect = _no_database  # type: ignore[attr-defined]
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass


def _new_pool(size: int) -> Any:
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from app.blender import runner
    # the cores less two, shared evenly by the workers
    fit_threads = max(1, ((os.cpu_count() or 1) - 2) // size)
    return ProcessPoolExecutor(max_workers=size, mp_context=multiprocessing.get_context("spawn"),
                               initializer=_initializer, initargs=(runner.spawn_slots(), fit_threads, os.getpid()))


def _get_pool(size: int) -> Any:
    """The pool of ``size`` workers, created on first use (or after a resize /
    a break)."""
    global _pool, _pool_size
    with _lock:
        if _pool is not None and _pool_size == size:
            return _pool
        old, _pool, _pool_size = _pool, _new_pool(size), size
        logger.info("Refit pool: %d worker process(es)", size)
    if old is not None:
        old.shutdown(wait=False)
    return _pool


def _drop(pool: Any) -> None:
    """Forget a broken pool (the next call creates a new one)."""
    global _pool, _pool_size
    with _lock:
        if _pool is pool:
            _pool, _pool_size = None, 0
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass


class WorkerCrashed(RuntimeError):
    """A refit worker process died while computing this call (twice: in the pool and alone)."""


def _run_alone(fn: Callable[..., Any], args: Any, kwargs: Any) -> Any:
    """``fn`` in a worker process of its own (after a pool break): a crash here is this call's alone."""
    from concurrent.futures.process import BrokenProcessPool
    ex = _new_pool(1)
    try:
        return ex.submit(fn, *args, **kwargs).result()
    except BrokenProcessPool as e:
        raise WorkerCrashed(f"the refit worker process crashed in {getattr(fn, '__name__', fn)}") from e
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``_run`` reporting live progress (A194): with a ``cpu_progress`` scope open, the call is named
    ``cpu:<function>`` and its inner ``cpu_progress.sub`` reports reach the scope — through a progress file when it
    runs in a worker process. Without a scope it is ``_run`` as is."""
    from app.core import cpu_progress
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
    again fails alone (``WorkerCrashed``) and the others complete."""
    size = workers()
    if size <= 1:
        return fn(*args, **kwargs)
    from concurrent.futures.process import BrokenProcessPool
    pool = _get_pool(size)
    try:
        future = pool.submit(fn, *args, **kwargs)
    except (BrokenProcessPool, RuntimeError):
        # Broken or shut down meanwhile (a break / resize by another thread): a fresh pool.
        _drop(pool)
        pool = _get_pool(size)
        future = pool.submit(fn, *args, **kwargs)
    try:
        return future.result()
    except BrokenProcessPool:
        _drop(pool)
        logger.warning("Refit pool broke during %s — recreated; the call runs once more on its own",
                       getattr(fn, "__name__", fn))
        return _run_alone(fn, args, kwargs)


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


def finish(task_id: str, error: str = "") -> None:
    """The tracked refit ended (done, or failed with ``error``)."""
    if not task_id:
        return
    try:
        from app.core.task_queue import get_task_queue
        get_task_queue().track_finish(task_id, error=error)
    except Exception:  # noqa: BLE001
        logger.exception("Refit task %s: finish failed", task_id)


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
