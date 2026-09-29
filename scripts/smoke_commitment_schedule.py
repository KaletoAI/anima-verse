#!/usr/bin/env python3
"""Smoke run for commitments with a due time (plan-befundrunde-2026-09-29 B8).

Usage:  ./.venv/bin/python scripts/smoke_commitment_schedule.py

Runs against a THROWAWAY storage dir: ``paths.init`` → ``config.load`` →
``db.init_schema`` before anything else is imported; the shared scheduler is
a fake registered with ``set_scheduler_manager`` and the task queue a fake
patched into ``app.core.task_queue``. Nothing is executed.

THE BUG
---------------------------------------------------------------------------
``memory_service._create_intent_from_commitment`` looked the scheduler up as
``ThoughtRunner._scheduler`` — an attribute that no longer exists — so the
scheduler was always ``None`` and ``execute_intent`` ran every commitment
("tomorrow") IMMEDIATELY through the task queue. Behind that, the delayed
path built an ``execute_tool``/``remind`` action, which the scheduler
discards (``scheduler_manager._execute_job``: "execute_tool action is
deactivated").

Hand-derived expectations
---------------------------------------------------------------------------
[1] A commitment with ``delay_minutes = 1440`` for "Bob":
    * the fake scheduler gets exactly ONE ``add_job``, the task queue ZERO
      submits (no immediate execution);
    * ``agent == "Bob"``; ``trigger == {"type": "date", "run_date": R,
      "one_time": True}`` where R is a canonical GAME stamp with
      ``canonical(game_time() + 86400 s)`` taken before the call <= R <= the
      same taken after it (the game clock may tick in between);
    * ``action == {"type": "intent_bump", "intent_id": "",
      "hint": "Reminder, due now: call the baker"}`` — the scheduler's working
      action, which bumps the character into a thought turn at R;
    * ``job_id`` matches ``intent_Bob_remind_<12 hex>``.
[2] A second, identical commitment in the same second gets a DIFFERENT job
    id (the old id had second resolution and collided).
[3] ``delay_minutes = 0`` schedules nothing and submits nothing (the
    commitment path only exists for due times).
[4] When the scheduler REFUSES the job (``success: False``):
    ``execute_intent`` returns False, the task queue still gets ZERO submits
    (a failed schedule must not turn into "run it now"), and the
    "Commitment → Intent: … in …s" info line is NOT logged — a warning that
    it could not be scheduled is.
[5] ``execute_intent`` for a deferred intent returns True when the job was
    accepted (the value the log line depends on).
[6] ``execute_intent`` for a deferred intent WITHOUT any scheduler
    (``scheduler_manager=None``): returns False, the task queue gets ZERO
    submits (it used to run the intent right away), and an ERROR is logged.
"""
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="commitment-schedule-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="commitment-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import memory_service  # noqa: E402
from app.core import task_queue as tq_mod  # noqa: E402
from app.core.game_time import GameDuration  # noqa: E402
from app.core.intent_engine import Intent, execute_intent  # noqa: E402
from app.core.timeutils import game_time  # noqa: E402
from app.scheduler import scheduler_manager as sm_mod  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class FakeScheduler:
    def __init__(self, accept=True):
        self.accept = accept
        self.jobs = []

    def add_job(self, agent, trigger, action, job_id=None, enabled=True):
        self.jobs.append({"agent": agent, "trigger": trigger, "action": action,
                          "job_id": job_id})
        if not self.accept:
            return {"success": False, "error": "refused by the smoke"}
        return {"success": True, "job_id": job_id, "message": "job added"}


class FakeQueue:
    def __init__(self):
        self.submits = []

    def submit(self, **kw):
        self.submits.append(kw)
        return "task-1"


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelname, record.getMessage()))


QUEUE = FakeQueue()
tq_mod.get_task_queue = lambda: QUEUE
CAPTURE = LogCapture()
logging.getLogger("memory_service").addHandler(CAPTURE)


def due(seconds: int) -> str:
    return (game_time() + GameDuration.of(seconds=seconds)).canonical()


print("\n[1] a commitment due in 1440 game minutes")
sched = FakeScheduler()
sm_mod.set_scheduler_manager(sched)
lo = due(86400)
memory_service._create_intent_from_commitment("Bob", "call the baker", 1440)
hi = due(86400)
check("one scheduler job", len(sched.jobs) == 1, str(sched.jobs))
check("no task-queue submit (not run now)", QUEUE.submits == [], str(QUEUE.submits))
job = sched.jobs[0] if sched.jobs else {}
trig = job.get("trigger") or {}
check("agent is Bob", job.get("agent") == "Bob", str(job.get("agent")))
check("date trigger, one-time",
      trig.get("type") == "date" and trig.get("one_time") is True, str(trig))
check("run_date is a game stamp one game day ahead",
      lo <= str(trig.get("run_date")) <= hi, f"{lo} <= {trig.get('run_date')} <= {hi}")
check("action is intent_bump with the reminder hint",
      job.get("action") == {"type": "intent_bump", "intent_id": "",
                            "hint": "Reminder, due now: call the baker"},
      str(job.get("action")))
check("job id intent_Bob_remind_<12 hex>",
      bool(re.fullmatch(r"intent_Bob_remind_[0-9a-f]{12}", job.get("job_id") or "")),
      str(job.get("job_id")))
check("the 'in …s' info line was logged",
      any(lvl == "INFO" and "in 86400s" in msg for lvl, msg in CAPTURE.records),
      str(CAPTURE.records))

print("\n[2] a second identical commitment right away")
memory_service._create_intent_from_commitment("Bob", "call the baker", 1440)
check("second job", len(sched.jobs) == 2, str(len(sched.jobs)))
check("distinct job ids",
      len(sched.jobs) == 2 and sched.jobs[0]["job_id"] != sched.jobs[1]["job_id"],
      str([j["job_id"] for j in sched.jobs]))

print("\n[3] no due time")
sched = FakeScheduler()
sm_mod.set_scheduler_manager(sched)
memory_service._create_intent_from_commitment("Bob", "call the baker", 0)
check("nothing scheduled, nothing submitted",
      sched.jobs == [] and QUEUE.submits == [], f"{sched.jobs} {QUEUE.submits}")

print("\n[4] the scheduler refuses")
sched = FakeScheduler(accept=False)
sm_mod.set_scheduler_manager(sched)
CAPTURE.records.clear()
memory_service._create_intent_from_commitment("Bob", "call the baker", 60)
check("the job was offered", len(sched.jobs) == 1, str(sched.jobs))
check("still no task-queue submit", QUEUE.submits == [], str(QUEUE.submits))
check("no 'in …s' info line",
      not any(lvl == "INFO" and "Commitment → Intent" in msg
              for lvl, msg in CAPTURE.records), str(CAPTURE.records))
check("a warning says it could not be scheduled",
      any(lvl == "WARNING" and "could not be scheduled" in msg
          for lvl, msg in CAPTURE.records), str(CAPTURE.records))
check("execute_intent returns False",
      execute_intent(Intent(type="remind", delay_seconds=60,
                            params={"note": "x"}), "Bob", sched) is False)

print("\n[5] execute_intent reports an accepted job")
sched = FakeScheduler()
check("execute_intent returns True",
      execute_intent(Intent(type="remind", delay_seconds=60, params={"note": "x"}),
                     "Bob", sched) is True)
check("still no task-queue submit", QUEUE.submits == [], str(QUEUE.submits))

print("\n[6] no scheduler at all")
ENGINE_LOG = LogCapture()
logging.getLogger("intent_engine").addHandler(ENGINE_LOG)
ok = execute_intent(Intent(type="remind", delay_seconds=60, params={"note": "x"}),
                    "Bob", None)
check("returns False", ok is False, repr(ok))
check("no task-queue submit (not run now)", QUEUE.submits == [], str(QUEUE.submits))
check("an ERROR is logged",
      any(lvl == "ERROR" and "No SchedulerManager" in msg
          for lvl, msg in ENGINE_LOG.records), str(ENGINE_LOG.records))

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
