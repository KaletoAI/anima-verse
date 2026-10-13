"""Hub operations — long AI-hub job chains that survive a restart of Anima.

A hub job (mesh, rig, face correction, upscale, motion, video) runs for
minutes on the gateway, and the gateway finishes it whether or not Anima is
still listening. This module keeps what is needed to collect it afterwards
(docs/hub-job-resume.md, spec docs/superpowers/specs/2026-10-13-hub-job-
resume-design.md):

* an OPERATION RECORD per job chain (``hub_ops`` table in world.db) with the
  FROZEN inputs of the run — signature, file names, backend pick, budgets —
  so a resume never reads the world's current state (the worn outfit, a
  re-rendered source image, a newer gallery file);
* a STAGE STATE MACHINE in the record: every hub stage goes
  ``claimed → posting → submitted → collected``, local stages are ``done``
  with their result; the stage functions of a pipeline are the same for the
  normal run and the resume, they only skip what the record says is done;
* a DURABLE directory per operation (``<world>/hub_ops/<op_id>/``) for the
  frozen input files and every intermediate result — never the staging dir
  of the run, which dies with the process.

The record lives until the result is published and is then deleted together
with its directory. A failure is stored first (``status='failed'``) and the
record deleted after it was reported. The partial unique index on
``subject`` is the atomic claim: a second operation on the same target is
refused (``HubOpBusy``) instead of submitting a second hub job.

Lost jobs (``HubJobLost``) are terminal and never resubmitted. One gap is
accepted by decision: a restart between the gateway accepting a POST and the
job id being stored leaves the stage in ``posting`` — the resume ends that
operation as lost, and the gateway job (if it exists) runs orphaned.

Owners: an operation started inside a TaskQueue handler belongs to that task
(the handler runs again after a restart and resumes it through
``find_open``); every other operation belongs to a thread and is resumed by
:func:`start_resumer`. The stamps are SYSTEM time (``utc_now_iso``) — this is
technical bookkeeping, not world time.
"""
import json
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now, utc_now_iso

logger = get_logger("hub_ops")

OP_DIRNAME = "hub_ops"
RUNNING = "running"
FAILED = "failed"
# Same number as the gateway's job retention (``_gateway_job.ATTACH_MAX_AGE_S``).
MAX_AGE_S = 24 * 3600


class HubOpBusy(RuntimeError):
    """Another operation already runs on this target (the atomic claim)."""


# ---------------------------------------------------------------------------
# Registry of operation kinds
# ---------------------------------------------------------------------------

@dataclass
class Kind:
    """What the resumer needs to know about one operation kind.

    ``resume(op)`` runs the remaining stages and publishes; it returns the
    pipeline's result (``True`` / ``{"ok": …}``). ``track_type`` is the task
    type of its display row. ``reserve(op)`` (optional) takes the in-process
    guards of a THREAD resume synchronously — before the AgentLoop and the
    queue workers start — and returns the function that releases them.
    ``agent(op)`` names the agent of the display row.

    The guards are taken on the resumer's thread and released on the resume
    thread: they must be plain sets or ``threading.Lock`` — never a
    ``keyed_lock`` (an RLock refuses a release from another thread)."""
    name: str
    resume: Callable[["Op"], Any]
    track_type: str
    reserve: Optional[Callable[["Op"], Callable[[], None]]] = None
    agent: Optional[Callable[["Op"], str]] = None


_KINDS: Dict[str, Kind] = {}


def register_kind(name: str, *, resume: Callable[["Op"], Any], track_type: str,
                  reserve: Optional[Callable[["Op"], Callable[[], None]]] = None,
                  agent: Optional[Callable[["Op"], str]] = None) -> None:
    _KINDS[name] = Kind(name, resume, track_type, reserve, agent)


def get_kind(name: str) -> Optional[Kind]:
    return _KINDS.get(name)


def register_builtin_kinds() -> None:
    """Import every module that registers a kind. Explicit, so the resumer
    never depends on which routers happened to be imported first."""
    from app.core import location_model3d, model3d, pose_animation, props  # noqa: F401
    from app.skills import animate  # noqa: F401
    from app.routes import instagram  # noqa: F401
    from app.skills import video_generation_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Owner context
# ---------------------------------------------------------------------------

def current_owner() -> str:
    """The TaskQueue task whose handler runs on this thread, or ""."""
    try:
        from app.core.task_queue import current_task_id
        return current_task_id()
    except Exception:  # noqa: BLE001 — no queue, no owner
        return ""


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

def _ops_root() -> Path:
    from app.core.paths import get_storage_dir
    return get_storage_dir() / OP_DIRNAME


_SCHEMA_READY: set = set()


class _Db:
    """A short-lived connection of its own for every hub_ops access: the
    thread-local ``db.get_connection`` may carry a caller's open transaction,
    and a commit/rollback here must never commit or drop someone else's
    writes."""

    def __enter__(self) -> sqlite3.Connection:
        from app.core.db import _configure, get_db_path
        path = get_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=10)
        _configure(self.conn)
        if str(path) not in _SCHEMA_READY:
            # The table belongs to the world schema (init_schema at boot); a
            # tool that opens a world without it must not fail on the record
            # of a generation it triggers.
            from app.core.world_db_schema import SCHEMA_STATEMENTS
            for stmt in SCHEMA_STATEMENTS:
                if "hub_ops" in stmt:
                    self.conn.execute(stmt)
            _SCHEMA_READY.add(str(path))
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def _conn() -> _Db:
    return _Db()


def _ok(result: Any) -> bool:
    return result is True or (isinstance(result, dict) and bool(result.get("ok")))


def _error_of(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("error") or "operation failed")
    return "operation failed"


class Op:
    """One operation record. ``inputs`` are frozen at creation; ``state``
    holds ``jobs`` (per hub stage), ``results`` and ``done`` (per stage).
    Every state write reloads the row under the operation's lock first, so
    the resumer's collection thread and a handler never overwrite each
    other's stage."""

    def __init__(self, row: sqlite3.Row):
        self.op_id = row["op_id"]
        self.kind = row["kind"]
        self.subject = row["subject"]
        self.status = row["status"]
        self.inputs: Dict[str, Any] = json.loads(row["inputs"] or "{}")
        self.state: Dict[str, Any] = json.loads(row["state"] or "{}")
        self.owner_kind = row["owner_kind"]
        self.owner = row["owner"]
        self.track_id = row["track_id"]
        self.label = row["label"]
        self.error = row["error"]
        self.created_at = row["created_at"]
        # Set for a resumed operation: the display row's cancel button.
        self.should_cancel: Optional[Callable[[], bool]] = None

    # -- files ------------------------------------------------------------
    @property
    def dir(self) -> Path:
        return _ops_root() / self.op_id

    def path(self, *parts: str) -> Path:
        """A path inside the operation's durable directory (parent created)."""
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def freeze_file(self, source: Any, *parts: str) -> Path:
        """Copy an input file into the operation (the frozen input)."""
        target = self.path(*parts)
        shutil.copy2(str(source), target)
        return target

    # -- state ------------------------------------------------------------
    def _lock(self):
        return keyed_lock("hub_op", self.op_id)

    def reload(self) -> "Op":
        with _conn() as conn:
            row = conn.execute("SELECT * FROM hub_ops WHERE op_id=?", (self.op_id,)).fetchone()
        if row is not None:
            fresh = Op(row)
            self.state, self.status, self.error = fresh.state, fresh.status, fresh.error
            self.owner_kind, self.owner, self.track_id = fresh.owner_kind, fresh.owner, fresh.track_id
        return self

    def update_state(self, change: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock():
            self.reload()
            change(self.state)
            with _conn() as conn:
                conn.execute("UPDATE hub_ops SET state=?, updated_at=? WHERE op_id=?",
                             (json.dumps(self.state, ensure_ascii=False), utc_now_iso(),
                              self.op_id))

    def set_fields(self, **fields: Any) -> None:
        allowed = {"track_id", "owner_kind", "owner", "status", "error", "label"}
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        with self._lock():
            sets = ", ".join(f"{k}=?" for k in cols)
            with _conn() as conn:
                conn.execute(f"UPDATE hub_ops SET {sets}, updated_at=? WHERE op_id=?",
                             (*cols.values(), utc_now_iso(), self.op_id))
            for k, v in cols.items():
                setattr(self, k, v)

    def done(self, stage: str) -> bool:
        return stage in (self.state.get("done") or [])

    def result(self, stage: str) -> Dict[str, Any]:
        return dict((self.state.get("results") or {}).get(stage) or {})

    def complete(self, stage: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark a stage done with its (JSON) result — the checkpoint a resume
        starts behind."""
        def change(state: Dict[str, Any]) -> None:
            state.setdefault("results", {})[stage] = dict(result or {})
            done = state.setdefault("done", [])
            if stage not in done:
                done.append(stage)
        self.update_state(change)

    def remember(self, stage: str, **values: Any) -> Dict[str, Any]:
        """Persist values of a stage BEFORE acting on them (e.g. the gallery
        path a publish is about to write) and return what is stored — on a
        repeated publish the stored values win, so no second target appears."""
        out: Dict[str, Any] = {}

        def change(state: Dict[str, Any]) -> None:
            slot = state.setdefault("results", {}).setdefault(stage, {})
            for k, v in values.items():
                slot.setdefault(k, v)
            out.update(slot)
        self.update_state(change)
        return out

    def rel(self, path: Any) -> str:
        """``path`` relative to the operation directory (what the state keeps).
        A file outside it is copied in first — a stage result must be durable
        wherever the producer happened to write it."""
        p = Path(path).resolve()
        root = self.dir.resolve()
        if not p.is_relative_to(root):
            target = self.path("kept", p.name)
            shutil.copy2(p, target)
            p = target.resolve()
        return str(p.relative_to(root))

    def abs(self, rel: str) -> Path:
        return self.dir / rel

    def stage(self, name: str) -> "HubStage":
        return HubStage(self, name)

    def jobs(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.state.get("jobs") or {})


class HubStage:
    """Handle on ONE hub stage of an operation — what the service methods
    receive as ``hub_stage`` and the backends' ``submit_job`` reports into
    (via ``params["hub_stage"]``; the GPU channel runs the backend on another
    thread, so a thread-local would never arrive there)."""

    def __init__(self, op: Op, name: str):
        self.op = op
        self.name = name
        self._route: Optional[Dict[str, Any]] = None

    @property
    def job(self) -> Dict[str, Any]:
        return dict((self.op.state.get("jobs") or {}).get(self.name) or {})

    def _set_job(self, update: Callable[[Dict[str, Any]], None]) -> None:
        def change(state: Dict[str, Any]) -> None:
            job = state.setdefault("jobs", {}).setdefault(self.name, {})
            update(job)
        self.op.update_state(change)

    def _lost(self, reason: str) -> Exception:
        """Mark the record LOST before the verdict leaves this module — a
        pipeline that turns the exception into ``{"ok": False}`` must not
        downgrade it to an ordinary failure (a task retry would then submit
        the work anew, spec D8)."""
        from app.imagegen.base import HubJobLost
        exc = HubJobLost(reason)
        self.op.update_state(lambda st: st.update(error_kind="lost"))
        return exc

    def prepare(self) -> str:
        """The atomic claim of the stage before anything is submitted.

        ``"attach"`` — a job of an EARLIER process is recorded (or its result
        was collected already): collect it, never submit.
        ``"submit"`` — nothing reached the gateway yet (fresh, a stage only
        claimed while waiting for its GPU slot, or a job of THIS process that
        the pipeline asks for again): submit normally.
        Raises ``HubJobLost`` for a stage left in ``posting`` by a restart —
        the submission gap: whether the gateway took that POST is unknown —
        and for a claimed stage whose routed backend speaks no job protocol
        (a third-party video API): it may have run without a job id we could
        collect, and submitting again would pay for it twice."""
        verdict = {"v": "submit", "backend": ""}

        def update(job: Dict[str, Any]) -> None:
            earlier = job.get("pid") != _PROCESS_ID
            if job.get("collected") or (job.get("job_id") and earlier):
                verdict["v"] = "attach"
                return
            if earlier and job.get("phase") == "posting":
                verdict["v"] = "gap"
                return
            if earlier and job.get("route_backend"):
                backend = find_backend(job["route_backend"])
                if backend is not None and not callable(getattr(backend, "attach", None)):
                    verdict["v"], verdict["backend"] = "foreign", backend.name
                    return
            job.clear()
            job.update(phase="claimed", claimed_at=utc_now_iso(), pid=_PROCESS_ID)
        self._set_job(update)
        if verdict["v"] == "gap":
            raise self._lost(f"the restart interrupted the submission of stage "
                             f"'{self.name}' — no job id was recorded, so the job "
                             f"cannot be collected (it may run orphaned on the hub)")
        if verdict["v"] == "foreign":
            raise self._lost(f"stage '{self.name}' ran on '{verdict['backend']}', which "
                             f"has no hub job to collect after a restart")
        return verdict["v"]

    # -- hooks called by _gateway_job.submit_job (GPU worker thread) -------
    def note_route(self, meta: Optional[Dict[str, Any]], backend: str = "") -> None:
        """The routing meta of the run (``routing.route_meta``), stored with
        the job so a resumed result carries the same marks — and the backend
        about to run the stage, persisted at once: a backend without a job
        protocol never reports a job id, and a resume must know it ran there."""
        self._route = dict(meta or {})
        if backend:
            self._set_job(lambda job: job.update(route_backend=backend))

    def posting(self, backend: Any) -> None:
        def update(job: Dict[str, Any]) -> None:
            job.update(phase="posting", backend=backend.name,
                       api_url=getattr(backend, "api_url", ""),
                       posting_at=utc_now_iso(), pid=_PROCESS_ID)
            job.pop("job_id", None)
        self._set_job(update)

    def not_posted(self) -> None:
        self._set_job(lambda job: job.update(phase="claimed"))

    def submitted(self, backend: Any, job_id: str, attach_params: Dict[str, Any]) -> None:
        route = dict(self._route or {})

        def update(job: Dict[str, Any]) -> None:
            job.clear()
            job.update(phase="submitted", job_id=str(job_id), backend=backend.name,
                       api_url=getattr(backend, "api_url", ""),
                       submitted_at=utc_now_iso(),
                       attach_params=dict(attach_params or {}), route=route,
                       pid=_PROCESS_ID)
        self._set_job(update)
        logger.info("hub op %s (%s): stage %s submitted as job %s on %s",
                    self.op.op_id, self.op.kind, self.name, job_id, backend.name)

    # -- collection ---------------------------------------------------------
    def _job_dir(self) -> Path:
        return self.op.dir / "jobs" / self.name

    def collected(self) -> Optional[Dict[str, Any]]:
        """The raw result fetched by an earlier collection, or None."""
        self.op.reload()
        job = self.job
        if not job.get("collected"):
            return None
        directory = self._job_dir()
        try:
            meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
            blobs = [(directory / f"{i}.bin").read_bytes() for i in range(int(meta["count"]))]
        except (OSError, ValueError, KeyError):
            return None
        return {**meta, "blobs": blobs}

    def collect(self) -> Dict[str, Any]:
        """Collect the recorded job (``backend.attach``) and keep the raw
        result in the operation directory. No GPU slot, no master switch —
        nothing is generated. Raises ``HubJobLost`` when the job cannot be
        collected (too old, backend gone or moved, gateway verdicts)."""
        from app.imagegen.base import HubJobLost
        with keyed_lock("hub_op_stage", f"{self.op.op_id}:{self.name}"):
            have = self.collected()
            if have is not None:
                return have
            if self.op.status == FAILED:
                # The collection ahead of this handler failed while it waited.
                if self.op.state.get("error_kind") == "lost":
                    raise HubJobLost(self.op.error or "collection failed")
                raise RuntimeError(self.op.error or "collection failed")
            try:
                return self._collect_locked()
            except HubJobLost:
                self.op.update_state(lambda st: st.update(error_kind="lost"))
                raise

    def _collect_locked(self) -> Dict[str, Any]:
        from app.imagegen.base import HubJobLost
        job = self.job
        job_id = str(job.get("job_id") or "")
        if not job_id:
            raise RuntimeError(f"stage '{self.name}' has no job to collect")
        try:
            since = parse_iso(job["submitted_at"]).timestamp()
        except (KeyError, TypeError, ValueError):
            raise HubJobLost(f"job {job_id}: unreadable submission stamp")
        if utc_now().timestamp() - since > MAX_AGE_S:
            raise HubJobLost(f"job {job_id} is older than 24 h (gateway retention)")
        backend = find_backend(job.get("backend") or "")
        if backend is None:
            raise HubJobLost(f"backend '{job.get('backend')}' of job {job_id} "
                             f"is no longer configured")
        if (getattr(backend, "api_url", "") or "").rstrip("/") != \
                str(job.get("api_url") or "").rstrip("/"):
            raise HubJobLost(f"backend '{backend.name}' now points to another "
                             f"gateway than job {job_id}")
        attach = getattr(backend, "attach", None)
        if not callable(attach):
            raise HubJobLost(f"backend '{backend.name}' cannot collect jobs")
        logger.info("hub op %s (%s): collecting job %s of stage %s from %s",
                    self.op.op_id, self.op.kind, job_id, self.name, backend.name)
        blobs = attach(job_id, dict(job.get("attach_params") or {}), since=since,
                       should_cancel=self.op.should_cancel)
        meta = {
            "count": len(blobs or []),
            "files": list(getattr(backend, "last_result_files", []) or []),
            "rig": getattr(backend, "last_result_rig", None),
            "results": list(getattr(backend, "last_result_meta", []) or []),
            "backend": backend.name,
            "job_id": job_id,
            "route": dict(job.get("route") or {}),
        }
        directory = self._job_dir()
        directory.mkdir(parents=True, exist_ok=True)
        for i, blob in enumerate(blobs or []):
            (directory / f"{i}.bin").write_bytes(blob)
        (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False),
                                             encoding="utf-8")
        self._set_job(lambda j: j.update(collected=True, phase="collected"))
        return {**meta, "blobs": list(blobs or [])}


# One id per process: a ``posting`` stage written by THIS process is a live
# submission (a routed re-run may post again), one written by an earlier
# process is the submission gap.
_PROCESS_ID = uuid.uuid4().hex


def find_backend(name: str) -> Any:
    """The configured backend of that name, or None. Enabled or not: a backend
    switched off for NEW work still collects what it already ran."""
    if not name:
        return None
    try:
        from app.imagegen.service import get_image_service
        for b in get_image_service().backends:
            if b.name == name:
                return b
    except Exception as e:  # noqa: BLE001
        logger.warning("hub_ops: backend lookup failed: %s", e)
    return None


def _cancel_jobs(op: Op) -> None:
    """Best-effort cancel of every recorded, uncollected job of ``op``."""
    from app.imagegen.backends._gateway_job import _cancel_lost_job
    for job in op.jobs().values():
        if not job.get("job_id") or job.get("collected"):
            continue
        backend = find_backend(job.get("backend") or "")
        if backend is not None:
            _cancel_lost_job(backend, job["job_id"])


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def create(kind: str, subject: str, inputs: Dict[str, Any], *, label: str = "",
           track_id: str = "", thread_owned: bool = False) -> Op:
    """Claim ``subject`` and record a new operation. Raises ``HubOpBusy``
    when a running operation holds the subject already.

    ``thread_owned`` forces the resumer as the owner even inside a queue
    handler — for producers a task does not reach deterministically again
    (a video asked for by an LLM turn)."""
    owner = "" if thread_owned else current_owner()
    owner = owner if isinstance(owner, str) else ""
    track_id = track_id if isinstance(track_id, str) else ""
    op_id = f"hop_{uuid.uuid4().hex[:12]}"
    now = utc_now_iso()
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO hub_ops (op_id, kind, subject, status, inputs, state, owner_kind, "
                "owner, track_id, label, error, created_at, updated_at) "
                "VALUES (?, ?, ?, 'running', ?, '{}', ?, ?, ?, ?, '', ?, ?)",
                (op_id, kind, subject, json.dumps(inputs, ensure_ascii=False),
                 "task" if owner else "thread", owner, track_id, label, now, now))
    except sqlite3.IntegrityError as exc:
        if "hub_ops.subject" not in str(exc):
            raise
        raise HubOpBusy(f"a hub job for this target is already in progress ({subject})")
    logger.info("hub op %s created: %s %s (owner %s)", op_id, kind, subject,
                owner or "thread")
    return get(op_id)


def get(op_id: str) -> Optional[Op]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM hub_ops WHERE op_id=?", (op_id,)).fetchone()
    return Op(row) if row is not None else None


def list_ops() -> List[Op]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM hub_ops ORDER BY created_at, op_id").fetchall()
    return [Op(r) for r in rows]


def find_open(kind: str, match: Callable[[Dict[str, Any]], bool]) -> Optional[Op]:
    """The operation of ``kind`` that the CURRENT task left behind and whose
    frozen inputs satisfy ``match`` — running, or failed during the early
    collection (its stored error is what the handler must report). Outside
    a task handler always None: a thread-owned operation belongs to its
    resumer, never to a new caller."""
    owner = current_owner()
    if not owner:
        return None
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM hub_ops WHERE kind=? AND owner_kind='task' AND owner=? "
            "ORDER BY created_at", (kind, owner)).fetchall()
    for row in rows:
        op = Op(row)
        try:
            if match(op.inputs):
                return op
        except Exception:  # noqa: BLE001 — a malformed record matches nothing
            continue
    return None


def delete(op: Op) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM hub_ops WHERE op_id=?", (op.op_id,))
    try:
        shutil.rmtree(op.dir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001 — the record is gone, a stray dir is not
        logger.warning("hub op %s: directory not removed: %s", op.op_id, e)


def fail(op: Op, error: str, *, lost: bool = False, keep: bool = False) -> None:
    """Store the terminal error FIRST, then delete — unless ``keep`` (a task
    still has to report it). ``lost`` marks a ``HubJobLost``."""
    op.set_fields(status=FAILED, error=str(error or "operation failed")[:1000])
    op.update_state(lambda s: s.update(error_kind="lost" if lost else "error"))
    logger.warning("hub op %s (%s) failed: %s", op.op_id, op.kind, error)
    if not keep:
        delete(op)


def raise_failed(op: Op) -> None:
    """A task re-run met a FAILED record of its own: report the stored error
    through the handler. A lost job stays as a tombstone until the task is
    over (``release_task_ops``) — the same handler may come back to this
    target again (a restart, a batch loop) and must meet the verdict again
    instead of submitting the work anew. Any other failure is dropped, a
    retry of it is ordinary queue behaviour."""
    from app.imagegen.base import HubJobLost
    error = op.error or "operation failed"
    if op.state.get("error_kind") == "lost":
        raise HubJobLost(error)
    delete(op)
    raise RuntimeError(error)


def open_task_inputs(kind: str) -> List[Dict[str, Any]]:
    """Frozen inputs of every record of ``kind`` the CURRENT task holds
    (running or tombstone) — so a batch handler can tell which of its targets
    are still in flight."""
    owner = current_owner()
    if not owner:
        return []
    with _conn() as conn:
        rows = conn.execute(
            "SELECT inputs FROM hub_ops WHERE kind=? AND owner_kind='task' AND owner=?",
            (kind, owner)).fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["inputs"] or "{}"))
        except ValueError:
            continue
    return out


def settle(op: Op, result: Any) -> None:
    """The run of ``op`` returned: deleted after a published success, failed
    (error stored, then deleted) otherwise — a LOST stage (marked by the
    stage handle even when the pipeline turned the verdict into
    ``{"ok": False}``) stays a task's tombstone."""
    if _ok(result):
        delete(op)
        return
    op.reload()
    lost = op.state.get("error_kind") == "lost"
    error = _error_of(result)
    if lost and not error.startswith("Hub job lost"):
        error = "Hub job lost: " + error
    fail(op, error, lost=lost, keep=lost and op.owner_kind == "task")


def settle_error(op: Op, exc: BaseException) -> None:
    """The run of ``op`` raised. A task's lost job stays as a tombstone (see
    ``raise_failed``); everything else is stored and deleted."""
    from app.imagegen.base import HubJobLost
    op.reload()
    lost = isinstance(exc, HubJobLost) or op.state.get("error_kind") == "lost"
    fail(op, str(exc) or type(exc).__name__, lost=lost,
         keep=lost and op.owner_kind == "task")


def execute(op: Op, run: Callable[[], Any]) -> Any:
    """Run the stages of an EXISTING ``op`` and settle the record."""
    try:
        result = run()
    except Exception as e:
        # Exception, not BaseException: a process going down must leave the
        # record behind — that is exactly the case it exists for.
        settle_error(op, e)
        raise
    settle(op, result)
    return result


def run_new(call: Callable[[Dict[str, Any]], Any]) -> Any:
    """Run a pipeline that creates its operation itself, part-way through
    (after its preprocessing): ``call(ctx)`` puts the record into
    ``ctx["op"]`` once it exists, and the record is settled AFTER ``call``
    returned — for the character pipelines that is after the ``_serial_model``
    wrapper published the stage, the moment the result really is public."""
    ctx: Dict[str, Any] = {}
    try:
        result = call(ctx)
    except Exception as e:
        if ctx.get("op") is not None:
            settle_error(ctx["op"], e)
        raise
    if ctx.get("op") is not None:
        settle(ctx["op"], result)
    return result


def resume(op: Op, run: Callable[[], Any], *, agent_name: str = "") -> Any:
    """Run a RESUMED operation with its own display row: original task type,
    label ``<label> — collecting after restart``, exempt from the stale
    reaper, cancellable (cancelling it cancels the hub job). The previous
    runtime's row (``interrupted`` by the restart) is told which row took
    over."""
    from app.core.task_queue import get_task_queue
    kind = get_kind(op.kind)
    tq = get_task_queue()
    old = op.track_id
    new = ""
    try:
        new = tq.track_start(kind.track_type if kind else "hub_resume",
                             f"{op.label or op.kind} — collecting after restart",
                             agent_name=agent_name, start_running=True)
        tq.track_hold(new)
        if old:
            tq.annotate_error(old, f" — resumed as {new}")
        op.set_fields(track_id=new)
        op.should_cancel = lambda: tq.is_task_cancelled(new)
    except Exception as e:  # noqa: BLE001 — display only
        logger.warning("hub op %s: display row not created: %s", op.op_id, e)
    error = ""
    try:
        result = execute(op, run)
        if not _ok(result):
            error = _error_of(result)
        return result
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        if new:
            try:
                tq.track_finish_if_open(new, error=error)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# The resumer
# ---------------------------------------------------------------------------

def _run_thread(op: Op, release: Optional[Callable[[], None]]) -> None:
    kind = get_kind(op.kind)
    try:
        kind.resume(op)
    except Exception as e:  # noqa: BLE001 — the record carries the verdict
        logger.warning("hub op %s (%s) resume ended: %s", op.op_id, op.kind, e)
    finally:
        if release is not None:
            try:
                release()
            except Exception:  # noqa: BLE001
                pass


def _start_thread(op: Op) -> None:
    """Take the kind's guards NOW (synchronously), then resume on a thread."""
    kind = get_kind(op.kind)
    release = None
    if kind.reserve is not None:
        try:
            release = kind.reserve(op)
        except Exception as e:  # noqa: BLE001
            logger.warning("hub op %s: guard not taken: %s", op.op_id, e)
    threading.Thread(target=_run_thread, args=(op, release), daemon=True,
                     name=f"hub-resume-{op.op_id}").start()


def _collect_ahead(op: Op) -> None:
    """The collection path for a task-owned operation: fetch its submitted
    stage now — also while the task's queue is paused — so the gateway's 24 h
    retention cannot run out under it. The handler does the rest. A failure
    is stored on the record (``keep``): the handler reports it."""
    from app.imagegen.base import HubJobLost
    from app.core.task_queue import get_task_queue
    owner = op.owner
    op.should_cancel = lambda: get_task_queue().task_status(owner) == "cancelled"
    for name, job in op.jobs().items():
        if not job.get("job_id") or job.get("collected"):
            continue
        try:
            op.stage(name).collect()
        except Exception as e:  # noqa: BLE001
            fresh = get(op.op_id)
            if fresh is not None and fresh.status == RUNNING:
                fail(fresh, str(e) or type(e).__name__,
                     lost=isinstance(e, HubJobLost), keep=True)
        return


def _drop(op: Op, reason: str) -> None:
    """End an operation nobody will continue: its hub jobs are cancelled
    (best effort, on a thread — no HTTP on the startup path) and the record
    is deleted."""
    fail(op, reason, keep=True)
    threading.Thread(target=lambda: (_cancel_jobs(op), delete(op)), daemon=True,
                     name=f"hub-drop-{op.op_id}").start()


def adopt_as_thread(op: Op) -> None:
    """D4: the owning task is over without having resumed its operation —
    the operation continues on its own thread."""
    op.set_fields(owner_kind="thread", owner="")
    logger.info("hub op %s (%s): owner task gone — continuing on a thread",
                op.op_id, op.kind)
    _start_thread(op)


def release_task_ops(task_id: str, cancelled: bool = False) -> None:
    """Called by the TaskQueue when ``task_id`` ended for good. Operations it
    left open continue on a thread (a handler may skip the producer, e.g.
    ``npc_assets`` once the static mesh is published); a cancelled task takes
    its hub jobs with it. A failed record is only dropped — its task is the
    one that should have reported it, and it is over."""
    if not task_id:
        return
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM hub_ops WHERE owner_kind='task' AND owner=?", (task_id,)).fetchall()
    for row in rows:
        op = Op(row)
        if op.status == FAILED:
            logger.warning("hub op %s (%s): failure not reported by its task: %s",
                           op.op_id, op.kind, op.error)
            delete(op)
        elif cancelled:
            _drop(op, "the owning task was cancelled")
        elif get_kind(op.kind) is None:
            _drop(op, "resume operation unknown")
        else:
            adopt_as_thread(op)


def start_resumer() -> Dict[str, int]:
    """Read every operation that survived the restart and continue it
    (spec § 3.6). Synchronous part: the bookkeeping and the guards of the
    thread-owned operations — so it has to run BEFORE the AgentLoop and the
    TaskQueue workers start. The hub traffic itself runs on daemon threads."""
    from app.core.task_queue import get_task_queue
    register_builtin_kinds()
    tq = get_task_queue()
    if list_ops():
        # Build the (lazy) image service once, here, before several resume
        # threads would race to construct it.
        from app.imagegen.service import get_image_service
        get_image_service()
    counts = {"resumed": 0, "collecting": 0, "dropped": 0, "reported": 0}
    for op in list_ops():
        task_status = tq.task_status(op.owner) if op.owner_kind == "task" else ""
        task_alive = task_status in ("pending", "running")
        if op.status == FAILED:
            if task_alive:
                continue  # the handler reports it
            logger.warning("hub op %s (%s) had failed: %s", op.op_id, op.kind, op.error)
            if op.track_id:
                tq.annotate_error(op.track_id, f" — {op.error}")
            delete(op)
            counts["reported"] += 1
            continue
        if get_kind(op.kind) is None:
            _drop(op, "resume operation unknown")
            if op.track_id:
                tq.annotate_error(op.track_id, " — resume operation unknown")
            counts["dropped"] += 1
            continue
        if op.owner_kind == "task":
            if task_alive:
                threading.Thread(target=_collect_ahead, args=(op,), daemon=True,
                                 name=f"hub-collect-{op.op_id}").start()
                counts["collecting"] += 1
                continue
            if task_status == "cancelled":
                _drop(op, "the owning task was cancelled")
                counts["dropped"] += 1
                continue
            op.set_fields(owner_kind="thread", owner="")
        _start_thread(op)
        counts["resumed"] += 1
    if any(counts.values()):
        logger.info("hub ops after restart: %s", counts)
    return counts
