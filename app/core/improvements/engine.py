"""Idle-time engine: feeds ONE improvement_step task into the TaskQueue whenever
the user has been idle long enough; keeps candidate steps materialised for the
admin queue view.

The engine never names an improvement type — it asks the registry.  It never
runs work itself either: it submits one task, the queue worker calls
``handle_step`` back, and the type does the work synchronously in that call.
"""
from typing import Any, Dict, List, Set, Tuple

from app.core import user_activity
from app.core.improvements import registry, store
from app.core.improvements.base import Candidate, CandidateBusy
from app.core.log import get_logger
from app.core.task_queue import get_task_queue
from app.core.timeutils import parse_iso, utc_now, utc_now_iso
from app.imagegen.base import BackendBusyError
from app.models.world import is_world_frozen

logger = get_logger("improvements.engine")

TASK_TYPE = "improvement_step"
STEP_PRIORITY = 90            # far behind anything the player is waiting for
QUEUE_NAME = "improvements"
SCAN_INTERVAL_S = 600         # how often a standing entry re-asks its type
MAX_ATTEMPTS = 2              # a defect gets one retry, then the step is skipped

# Improvement ids whose next step ignores the idle rule exactly once — the
# admin's "run now" button. In-memory on purpose: a restart forgets it.
_run_now: Set[str] = set()


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan(improvement_id: str) -> Dict[str, int]:
    """Ask the type for its candidates and diff them onto the steps."""
    improvement = store.get(improvement_id)
    if improvement is None:
        return {"added": 0, "closed": 0}
    improvement_type = registry.get(improvement["type_id"])
    if improvement_type is None:
        return {"added": 0, "closed": 0}
    candidates = improvement_type.find_candidates(improvement["params"])
    result = store.replace_steps_scan(
        improvement_id, [(c.key, c.label) for c in candidates])
    store.update(improvement_id, last_scan_at=utc_now_iso())
    # A one_shot whose scan finds nothing has nothing to do — ever. Without
    # this it would sit 'open' with 0/0 steps forever, because the only other
    # close happens after a step FINISHES and there is no step to finish.
    _close_if_finished(improvement_id)
    return result


def _scan_due(improvement: Dict[str, Any]) -> bool:
    """Only a standing entry rescans, and only on the interval.  A one_shot
    was scanned when it was created; its candidate list is its whole job."""
    if improvement["mode"] != "standing":
        return False
    if improvement["status"] not in ("open", "paused"):
        return False
    last = improvement.get("last_scan_at")
    if not last:
        return True
    try:
        age = (utc_now() - parse_iso(last)).total_seconds()
    except (ValueError, TypeError):
        return True
    return age >= SCAN_INTERVAL_S


# ---------------------------------------------------------------------------
# The queue view
# ---------------------------------------------------------------------------

def ordered_queue() -> List[Dict[str, Any]]:
    """Every runnable step of every OPEN entry, in the order they will run:
    whatever is in flight first, then the entry order (``position``) and
    within an entry the label order ``list_steps`` gives."""
    rows: List[Dict[str, Any]] = []
    for improvement in store.list_all():          # ORDER BY position
        if improvement["status"] != "open":
            continue
        for step in store.list_steps(improvement["id"]):
            if step["status"] not in ("running", "pending"):
                continue
            rows.append({**step,
                         "improvement_id": improvement["id"],
                         "label": improvement["label"],
                         "type_id": improvement["type_id"],
                         "mode": improvement["mode"]})
    # Stable sort: running to the front, everything else keeps its entry order.
    rows.sort(key=lambda r: r["status"] != "running")
    for position, row in enumerate(rows, 1):
        row["pos"] = position
    return rows


# ---------------------------------------------------------------------------
# The gates
# ---------------------------------------------------------------------------

def submit_allowed() -> Tuple[bool, str]:
    """(may a step be submitted right now, why not) — the reason is what the
    admin panel shows: disabled | frozen | busy | active | ok."""
    settings = store.get_settings()
    if not settings["enabled"]:
        return False, "disabled"
    if is_world_frozen():
        return False, "frozen"
    if get_task_queue().has_pending_task(TASK_TYPE):
        return False, "busy"
    if user_activity.seconds_since() < settings["idle_minutes"] * 60:
        return False, "active"
    return True, "ok"


def request_run_now(improvement_id: str) -> None:
    """The next tick runs ONE step of this entry even while the user is here."""
    _run_now.add(improvement_id)


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------

def tick() -> Dict[str, Any]:
    """One pass: recover, rescan, submit at most one step."""
    task_queue = get_task_queue()

    # 1. A restart (or a crash) leaves 'running' steps behind whose task row
    #    is gone. Nothing is owed any more, so they are runnable again.
    if store.running_steps() and not task_queue.has_pending_task(TASK_TYPE):
        rescued = store.reset_running_to_pending()
        if rescued:
            logger.info("improvements: %d orphaned step(s) made runnable again",
                        rescued)

    # 2. Scans — independent of idleness, they only read.
    scanned = 0
    for improvement in store.list_all():
        if not _scan_due(improvement):
            continue
        try:
            scan(improvement["id"])
            scanned += 1
        except Exception as e:  # noqa: BLE001 — one broken type must not stop the tick
            logger.warning("improvements: scan of %s failed: %s",
                           improvement["id"], e, exc_info=True)

    # 3. One step.
    allowed, reason = submit_allowed()
    if not allowed and not (reason == "active" and _run_now):
        return {"scanned": scanned, "submitted": "", "reason": reason}

    for row in ordered_queue():
        if row["status"] != "pending":
            continue
        if reason == "active" and row["improvement_id"] not in _run_now:
            continue
        _run_now.discard(row["improvement_id"])
        # Mark FIRST, submit second. A worker can pick the task up — and even
        # finish it — before ``submit`` has returned here; a mark_running after
        # that would overwrite the handler's 'done' back to 'running'.
        store.mark_running(row["improvement_id"], row["candidate_key"])
        task_id = task_queue.submit(
            TASK_TYPE,
            {"improvement_id": row["improvement_id"],
             "candidate_key": row["candidate_key"]},
            queue_name=QUEUE_NAME, priority=STEP_PRIORITY, max_retries=0,
            deduplicate=True)
        if not task_id:
            # Deduplicated: nothing is owed after all, so give the step back.
            store.mark_result(row["improvement_id"], row["candidate_key"],
                              status="pending", count_attempt=False)
            return {"scanned": scanned, "submitted": "", "reason": "dedup"}
        return {"scanned": scanned, "submitted": task_id, "reason": "ok"}

    # Nothing runnable. A run-now flag that got this far names an entry with no
    # pending step (its last one finished between the click and this tick) —
    # it can never fire, so it is spent here instead of sticking forever.
    _run_now.clear()
    return {"scanned": scanned, "submitted": "", "reason": "empty"}


def periodic_tick() -> None:
    """Zero-argument entry point for ``periodic_jobs._SUB_TASKS``."""
    tick()


# ---------------------------------------------------------------------------
# The handler
# ---------------------------------------------------------------------------

def handle_step(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run one candidate.  Called by the queue worker, synchronous: it returns
    only once the type has persisted whatever it made."""
    improvement_id = payload["improvement_id"]
    key = payload["candidate_key"]
    task_id = payload.get("_task_id", "")

    improvement = store.get(improvement_id)
    if improvement is None:
        return {"skipped": "gone"}
    step = next((s for s in store.list_steps(improvement_id)
                 if s["candidate_key"] == key), None)
    if step is None:
        # A scan closed the candidate while the task waited — there is no row
        # left to write a result into, and nothing to run.
        return {"skipped": "gone"}

    improvement_type = registry.get(improvement["type_id"])
    if improvement_type is None:
        # A package went away (or never loaded). The step MUST leave 'running'
        # here: the next tick would otherwise rescue it, resubmit it, and —
        # since only one improvement_step may ever be owed — every other entry
        # would queue up behind a step that can never run.
        message = f"type '{improvement['type_id']}' is not registered"
        logger.warning("improvement step %s/%s: %s",
                       improvement_id, key, message)
        store.mark_result(improvement_id, key, status="skipped",
                          error=message, count_attempt=False)
        store.update(improvement_id,
                     failed_count=int(improvement["failed_count"]) + 1)
        return {"skipped": message}

    candidate = Candidate(key, step["candidate_label"])
    try:
        # The step's own generations must not end the user's idle window.
        with user_activity.suppressed():
            improvement_type.apply(candidate, improvement["params"], task_id)
    except (BackendBusyError, CandidateBusy) as e:
        # Load, not a defect — the candidate keeps both its attempts.
        store.mark_result(improvement_id, key, status="pending", error=str(e),
                          count_attempt=False)
        return {"busy": str(e)}
    except Exception as e:  # noqa: BLE001 — every defect is one attempt
        logger.warning("improvement step %s/%s failed: %s",
                       improvement_id, key, e, exc_info=True)
        attempts = int(step["attempts"]) + 1
        if attempts >= MAX_ATTEMPTS:
            store.mark_result(improvement_id, key, status="skipped",
                              error=str(e), count_attempt=True)
            store.update(improvement_id,
                         failed_count=int(improvement["failed_count"]) + 1)
        else:
            store.mark_result(improvement_id, key, status="pending",
                              error=str(e), count_attempt=True)
        return {"error": str(e)}

    store.mark_result(improvement_id, key, status="done", count_attempt=False)
    store.update(improvement_id, done_count=int(improvement["done_count"]) + 1)
    _close_if_finished(improvement_id)
    return {"ok": True}


def _close_if_finished(improvement_id: str) -> None:
    """A one_shot is done when its candidate list is worked off.  A standing
    entry never closes — it rescans instead."""
    improvement = store.get(improvement_id)
    if not improvement:
        return
    if (improvement["mode"] == "one_shot" and improvement["status"] == "open"
            and improvement["pending"] == 0 and improvement["running"] == 0):
        store.update(improvement_id, status="done")


def register_improvement_handler() -> None:
    get_task_queue().register_handler(TASK_TYPE, handle_step)


# ---------------------------------------------------------------------------
# Status for the admin panel
# ---------------------------------------------------------------------------

def status() -> Dict[str, Any]:
    """What the admin tab shows above the queue: the gate, the countdown, the
    step in flight and a rough estimate for the rest."""
    settings = store.get_settings()
    _allowed, reason = submit_allowed()
    idle_seconds = user_activity.seconds_since()
    running = store.running_steps()
    averages = store.avg_duration_by_type()
    # Only OPEN entries are waiting for anything — a paused entry's steps must
    # not show up in the panel's pending total or in its estimate.
    pending = store.pending_count_by_type(open_only=True)
    estimate = sum(averages[type_id] * count
                   for type_id, count in pending.items()
                   if type_id in averages) if averages else None
    return {
        "enabled": settings["enabled"],
        "idle_minutes": settings["idle_minutes"],
        "idle_seconds": int(idle_seconds),
        "next_allowed_in_s": max(
            0, int(settings["idle_minutes"] * 60 - idle_seconds)),
        "frozen": is_world_frozen(),
        "reason": reason,
        "running_step": running[0] if running else None,
        "pending_total": sum(pending.values()),
        "estimate_s": estimate,
    }
