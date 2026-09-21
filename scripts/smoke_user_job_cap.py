#!/usr/bin/env python3
"""Smoke run: one user may only have N generation jobs owed at a time (SEC-7).

Usage:
    ./.venv/bin/python scripts/smoke_user_job_cap.py

Runs WITHOUT the server, without a world DB and without a network: the storage
root is a throwaway temp dir set through ``paths.init`` BEFORE the first import
of an app module, so the TaskQueue's DB (``<storage>/task_queue.db``) can never
be the real one. The "GPU job" is a callable that waits on an Event.

The finding under test (review 2026-09-20, security.md SEC-7, part 2)
---------------------------------------------------------------------------
Nothing bounded how much work ONE user could ask for: a script in a loop
enqueued image/video/mesh jobs until the GPU was busy with nothing else, and
with a cloud provider every one of them cost money. The gate sits where that
work is really handed over:

``ProviderQueue.submit_gpu_task`` blocks for the whole life of the job, so
holding a slot for the duration of the call IS the in-flight count.
``TaskQueue.submit`` (the persistent queue) deliberately does NOT admit: it
only RECORDS the submitter in the ``user_id`` column that existed but was
never filled, so a row in the queue view is attributable.

Who a job belongs to comes from ``auth_dependency.current_user_ctx``. No user
in the context = the server's own work (agent loop, scheduler, tickers) and an
admin are never limited.

Expected values, derived by hand from the source — not recorded from a run
---------------------------------------------------------------------------
[1] ``max_inflight_jobs_per_user()`` with no config loaded must be the SCHEMA
    default of ``server.max_inflight_jobs_per_user`` = 4: ``config.get``
    returns None for a plain scalar until the settings page has been saved
    once, and the fallback is the schema, not 0 (0 would mean "unlimited" and
    silently disable the gate).

[2] ``user_job_slot`` bookkeeping with a hand-set cap of 2:
    a) no user in the context -> no bookkeeping at all: 5 nested slots, the
       snapshot stays empty.
    b) an admin -> the same.
    c) user "u1": slot 1 and 2 enter (snapshot {"u1": 2}); the THIRD raises
       TooManyJobsError with status_code 429, and the counter stays 2 —
       a refusal must not consume a slot.
    d) leaving one slot puts the count back to 1 and the next slot is granted
       again; leaving the last one removes the user from the snapshot
       entirely (no leak per user).
    e) cap 0 = unlimited: 5 nested slots for the same user, snapshot empty.

[3] ``submit_gpu_task`` on a real queue (3 permits, cap 2), each job blocking
    on an Event:
    a) two jobs submitted from two threads that CARRY the user context
       (``contextvars.copy_context().run`` — a bare ``threading.Thread``
       would arrive here with no user at all) are accepted: 2 in flight.
    b) the third submit raises TooManyJobsError AND queues nothing: the
       queue's ``_seq_counter`` is the same before and after, so no task
       object was ever created.
    c) the same submit with an ADMIN in the context goes through while the
       two user jobs are still running (admins are never limited).
    d) after the two jobs finish, the user's counter is back to 0 and a
       submit is accepted again.

[4] ``TaskQueue.submit`` against a throwaway DB — it records, it never
    refuses. The persistent queue carries ENGINE work (intents, memory
    consolidation, NPC assets) that merely runs on whichever thread triggered
    it, so a quota there would drop exactly that work while the GPU stays as
    reachable as before. With the cap at 2:
    a) FIVE submits for "u1" (cap+3) all return a task id, all five rows are
       pending, and every one of them carries ``user_id`` "u1".
    b) work with no user in the context lands with an EMPTY user_id — the
       server's own rows (agent loop, scheduler, tickers).
    c) an admin's submit does the same: not attributed to a player.
    d) a second user is recorded under his own id.
"""
from __future__ import annotations

import atexit
import contextvars
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def scratch(prefix: str) -> str:
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


# Throwaway storage and clip library BEFORE the first app import: without it
# the default world is worlds/demo, which is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = scratch("job-cap-clips-")

from app.core import paths  # noqa: E402

paths.init(scratch("job-cap-storage-"))

from app.core import provider_queue as pq_mod  # noqa: E402
from app.core.auth_dependency import current_user_ctx  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_queue import (ProviderQueue, TooManyJobsError,  # noqa: E402
                                     inflight_jobs_snapshot, user_job_slot)
from app.core.task_queue import TaskQueue  # noqa: E402
from app.utils import llm_logger, llm_stats  # noqa: E402

# Keep the JSONL log out of the repo and the stats DB out of the run — neither
# has anything to do with the admission gate.
llm_logger.LOG_DIR = Path(scratch("job-cap-logs-"))
llm_logger.LOG_FILE = llm_logger.LOG_DIR / "llm_calls.jsonl"
pq_mod._attach_duration_estimate = lambda task: None
llm_stats.record_call = lambda *a, **kw: None

FAILED: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


def set_cap(value: int) -> None:
    """Hand-set the configured cap (no config file is loaded here)."""
    pq_mod.max_inflight_jobs_per_user = lambda: value


_REAL_CAP = pq_mod.max_inflight_jobs_per_user


def as_user(user, fn, *args, **kwargs):
    """Run ``fn`` with ``user`` in the request context."""
    token = current_user_ctx.set(user)
    try:
        return fn(*args, **kwargs)
    finally:
        current_user_ctx.reset(token)


USER = {"id": "u1", "username": "player", "role": "user"}
OTHER = {"id": "u2", "username": "player2", "role": "user"}
ADMIN = {"id": "a1", "username": "boss", "role": "admin"}


# ── [1] the configured default ────────────────────────────────────────────
print("\n[1] the cap falls back to the schema default")
check("max_inflight_jobs_per_user() with no config", _REAL_CAP(), 4)


# ── [2] the slot bookkeeping ──────────────────────────────────────────────
print("\n[2] user_job_slot: who is counted, who is not")
set_cap(2)


def nest(depth: int):
    """Enter ``depth`` slots, return the snapshot, then leave them all."""
    if depth == 0:
        return dict(inflight_jobs_snapshot())
    with user_job_slot("test job"):
        return nest(depth - 1)


check("a) no user in the context -> nothing counted",
      nest(5), {})
check("b) an admin -> nothing counted",
      as_user(ADMIN, nest, 5), {})


def user_over_cap():
    """Two slots, then a third that must be refused."""
    out = {}
    with user_job_slot("test job"):
        with user_job_slot("test job"):
            out["at_cap"] = dict(inflight_jobs_snapshot())
            try:
                with user_job_slot("test job"):
                    out["third"] = "entered"
            except TooManyJobsError as exc:
                out["third"] = f"{exc.status_code}"
            out["after_refusal"] = dict(inflight_jobs_snapshot())
        out["after_one_left"] = dict(inflight_jobs_snapshot())
        with user_job_slot("test job"):
            out["granted_again"] = dict(inflight_jobs_snapshot())
    out["after_all_left"] = dict(inflight_jobs_snapshot())
    return out


RES = as_user(USER, user_over_cap)
check("c) two slots are held", RES["at_cap"], {"u1": 2})
check("c) the third is refused with 429", RES["third"], "429")
check("c) a refusal consumes no slot", RES["after_refusal"], {"u1": 2})
check("d) leaving one frees a slot", RES["after_one_left"], {"u1": 1})
check("d) the freed slot is granted again", RES["granted_again"], {"u1": 2})
check("d) leaving the last one drops the user", RES["after_all_left"], {})

set_cap(0)
check("e) cap 0 = unlimited", as_user(USER, nest, 5), {})


# ── [3] the GPU funnel ────────────────────────────────────────────────────
print("\n[3] submit_gpu_task admits before it queues")
set_cap(2)

# THREE permits, so the admin's job in c) can really start while the two
# user jobs are still running — the cap under test is the user's, not the
# channel's.
PROVIDER = Provider(name="G", type="openai", api_base="http://stub/G",
                    api_key="", max_concurrent=3, timeout=30)
PROVIDER.available = True
QUEUE = ProviderQueue(PROVIDER, queue_name="G", max_concurrent=3,
                      chat_pause_enabled=False, serialize_group="")

RELEASE = threading.Event()
RUNNING = threading.Semaphore(0)


def blocking_job():
    RUNNING.release()
    # The wait has a ceiling so a broken run ends instead of hanging; the
    # checks below release it long before that.
    RELEASE.wait(120)
    return "done"


def submit_one(label: str):
    return QUEUE.submit_gpu_task("image_generation", 10, blocking_job,
                                 agent_name="Kira", label=label)


RESULTS: dict[str, object] = {}


def run_in_user_context(label: str):
    """A thread that CARRIES the user context, the way asyncio.to_thread does."""
    def body():
        try:
            RESULTS[label] = submit_one(label)
        except BaseException as exc:  # noqa: BLE001 — recorded, not handled
            RESULTS[label] = exc

    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(body,), daemon=True)
    thread.start()
    return thread


TOKEN = current_user_ctx.set(USER)
T1 = run_in_user_context("job1")
T2 = run_in_user_context("job2")
check("a) both user jobs started",
      [RUNNING.acquire(timeout=30), RUNNING.acquire(timeout=30)], [True, True])
check("a) two jobs of one user are in flight", inflight_jobs_snapshot(), {"u1": 2})

SEQ_BEFORE = QUEUE._seq_counter
try:
    submit_one("job3")
    THIRD = "entered"
except TooManyJobsError as exc:
    THIRD = f"{exc.status_code}"
check("b) the third submit is refused with 429", THIRD, "429")
check("b) and nothing was queued (seq counter unchanged)",
      QUEUE._seq_counter, SEQ_BEFORE)
current_user_ctx.reset(TOKEN)

# An admin submits while the two user jobs still run: never limited.
ADMIN_DONE = threading.Event()


def admin_body():
    try:
        RESULTS["admin"] = submit_one("admin")
    except BaseException as exc:  # noqa: BLE001
        RESULTS["admin"] = exc
    ADMIN_DONE.set()


ADMIN_TOKEN = current_user_ctx.set(ADMIN)
ADMIN_CTX = contextvars.copy_context()
threading.Thread(target=ADMIN_CTX.run, args=(admin_body,), daemon=True).start()
current_user_ctx.reset(ADMIN_TOKEN)
check("c) the admin's job started past the cap",
      RUNNING.acquire(timeout=30), True)
check("c) and it is not counted against anyone",
      inflight_jobs_snapshot(), {"u1": 2})

RELEASE.set()
T1.join(30)
T2.join(30)
ADMIN_DONE.wait(30)
check("d) both user jobs returned", [RESULTS.get("job1"), RESULTS.get("job2")],
      ["done", "done"])
check("d) the admin job returned", RESULTS.get("admin"), "done")
check("d) the user's counter is back to zero", inflight_jobs_snapshot(), {})

RELEASE.clear()


def quick_job():
    return "ok"


check("d) a submit is accepted again",
      as_user(USER, lambda: QUEUE.submit_gpu_task(
          "image_generation", 10, quick_job, agent_name="Kira", label="after")),
      "ok")


# ── [4] the persistent queue ──────────────────────────────────────────────
print("\n[4] TaskQueue.submit records the submitter and refuses NOTHING")
set_cap(2)

TQ = TaskQueue()
TQ._started = True          # no worker threads: the rows stay pending


def rows():
    conn = TQ._connect()
    try:
        return [(r["task_id"], r["user_id"], r["status"])
                for r in conn.execute(
                    "SELECT task_id, user_id, status FROM tasks "
                    "ORDER BY created_at, rowid")]
    finally:
        conn.close()


IDS = [as_user(USER, TQ.submit, "smoke_job", {"n": n}) for n in range(5)]
check("a) cap+3 submits of one user all go through",
      [bool(i) for i in IDS], [True] * 5)
check("a) and all five rows are pending",
      len([r for r in rows() if r[2] == "pending"]), 5)
check("a) every row records the submitter",
      sorted({r[1] for r in rows()}), ["u1"])

for n in range(3):
    TQ.submit("smoke_job", {"server": n})
check("b) work without a user is recorded as the server's own",
      len([r for r in rows() if r[1] == ""]), 3)

as_user(ADMIN, TQ.submit, "smoke_job", {"n": 100})
check("c) an admin's row is not attributed to a player",
      len([r for r in rows() if r[1] == ""]), 4)

as_user(OTHER, TQ.submit, "smoke_job", {"n": 200})
check("d) a second user is recorded under his own id",
      len([r for r in rows() if r[1] == "u2"]), 1)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
