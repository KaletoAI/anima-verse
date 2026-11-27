"""Idle-time engine: feeds ONE improvement_step task into the TaskQueue whenever
the user has been idle long enough; keeps candidate steps materialised for the
admin queue view.

The engine never names an improvement type — it asks the registry.  It never
runs work itself either: it submits one task, the queue worker calls
``handle_step`` back, and the type does the work synchronously in that call.
"""
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.core import user_activity
from app.core.improvements import registry, store
from app.core.improvements.base import Candidate, CandidateBusy, CandidateRefused
from app.core.hub_ops import HubOpBusy
from app.core.log import get_logger
from app.core.task_queue import get_task_queue
from app.core.timeutils import parse_iso, utc_now, utc_now_iso
from app.imagegen.base import (BackendBusyError, HubJobLost, MediaGenerationDisabled,
                               media_generation_enabled)
from app.models.world import is_world_frozen

logger = get_logger("improvements.engine")

TASK_TYPE = "improvement_step"
STEP_PRIORITY = 90            # far behind anything the player is waiting for
QUEUE_NAME = "improvements"
SCAN_INTERVAL_S = 600         # how often a standing entry re-asks its type
MAX_ATTEMPTS = 2              # a defect gets one retry, then the step is skipped
BUSY_DEFER_S = 300            # a step that came back busy sits out this long

#: The gates a FORCED entry (the admin's "Run now", ``improvements.forced``)
#: passes: it is the admin asking for this entry, so neither the idle window
#: nor the engine switch nor a world freeze or task-queue pause (which stop
#: autonomous work, not on-demand work) holds it back. The media switch and an
#: in-flight step do. The flag is persisted, so it survives a restart, and the
#: tick clears it once the entry has nothing left to run.
RUN_NOW_OVERRIDES = ("active", "disabled", "frozen", "paused")

#: Step statuses a validity pass judges (``remove_invalid``): work still owed
#: or given up. A running step belongs to its worker; a done or fulfilled one
#: is history.
VALIDATE_STATUSES = ("pending", "skipped", "failed")

# improvement_id -> ``time.monotonic()`` of its last validity pass. In memory
# on purpose: a restart forgets it, so the first tick after a start judges
# every entry once.
_validated_at: Dict[str, float] = {}
_validated_lock = threading.Lock()

# Steps that came back BUSY (BackendBusyError / CandidateBusy), keyed
# (improvement_id, candidate_key) -> SYSTEM time until which ``tick`` passes
# them over. Without it the first pending step is submitted on every tick, and
# one candidate whose backend is down for hours blocks every later step of
# every entry. In-memory on purpose: the engine runs in ONE process (the
# periodic tick and the TaskQueue worker that calls ``handle_step`` are both
# threads of the server), and a restart forgetting a deferral only means that
# step is tried once more right away — it then defers itself again.
_busy_until: Dict[Tuple[str, str], datetime] = {}
_busy_lock = threading.Lock()


def _defer(improvement_id: str, key: str) -> None:
    with _busy_lock:
        _busy_until[(improvement_id, key)] = utc_now() + timedelta(seconds=BUSY_DEFER_S)


def _undefer(improvement_id: str, key: str) -> None:
    with _busy_lock:
        _busy_until.pop((improvement_id, key), None)


def _deferred(improvement_id: str, key: str, now: datetime) -> bool:
    with _busy_lock:
        until = _busy_until.get((improvement_id, key))
        if until is None:
            return False
        if until <= now:
            del _busy_until[(improvement_id, key)]
            return False
        return True


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
    # Wrong steps go BEFORE the diff: a step the type no longer lists would
    # otherwise be closed as "fulfilled", which it is not, and its own files
    # would stay behind.
    remove_invalid(improvement_id)
    listing = improvement_type.list_candidates(improvement["params"])
    result = store.replace_steps_scan(
        improvement_id,
        [(c.key, c.label, c.hub_jobs, c.note) for c in listing.candidates],
        withheld=listing.withheld)
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
# Validity
# ---------------------------------------------------------------------------

def _validate_due(improvement_id: str) -> bool:
    with _validated_lock:
        last = _validated_at.get(improvement_id)
    return last is None or time.monotonic() - last >= SCAN_INTERVAL_S


def remove_invalid(improvement_id: Optional[str] = None, *, keys: Optional[Iterable[str]] = None,
                   explicit: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Judge the stored steps against today's rules (``ImprovementType.invalid_reason``) and drop the
    WRONG ones together with the files that belong only to them (``ImprovementType.release_invalid``).

    ``improvement_id`` None = every entry; ``keys`` narrows the pass to these steps (the check before a
    step runs). Only steps in ``VALIDATE_STATUSES`` are judged — never a running one. ``explicit`` = a
    person asked (the "Remove invalid" click: no grace window for the files); ``dry_run`` lists what would
    go and changes nothing. An entry whose type cannot judge right now (it raised — a roster read failed)
    is left untouched and reported with ``error``. Returns ``{"dry_run", "removed", "files", "bytes",
    "entries": [{"id", "label", "type_id", "steps": [{"key", "label", "status", "reason"}], "files",
    "bytes", "kept", "error"}]}`` — only entries with something wrong (or an error) are listed."""
    wanted = set(str(k) for k in keys) if keys is not None else None
    entries = ([store.get(improvement_id)] if improvement_id else store.list_all())
    report: Dict[str, Any] = {"dry_run": dry_run, "removed": 0, "files": 0, "bytes": 0, "entries": []}
    for improvement in entries:
        if not improvement:
            continue
        improvement_type = registry.get(improvement["type_id"])
        if improvement_type is None:
            continue
        entry: Dict[str, Any] = {"id": improvement["id"], "label": improvement["label"],
                                 "type_id": improvement["type_id"], "steps": [], "files": 0, "bytes": 0,
                                 "kept": [], "error": ""}
        if not dry_run and wanted is None:
            # Stamped also when the judgement fails below: the next try comes
            # with the next interval, not with every tick.
            with _validated_lock:
                _validated_at[improvement["id"]] = time.monotonic()
        try:
            for step in store.list_steps(improvement["id"]):
                if step["status"] not in VALIDATE_STATUSES:
                    continue
                if wanted is not None and step["candidate_key"] not in wanted:
                    continue
                reason = improvement_type.invalid_reason(step["candidate_key"], improvement["params"])
                if reason:
                    entry["steps"].append({"key": step["candidate_key"], "label": step["candidate_label"],
                                           "status": step["status"], "reason": reason})
        except Exception as e:  # noqa: BLE001 — an entry the type cannot judge now is left as it is
            logger.warning("improvements: validity of %s not judged: %s", improvement["id"], e, exc_info=True)
            entry["steps"], entry["error"] = [], str(e) or e.__class__.__name__
            report["entries"].append(entry)
            continue
        if not entry["steps"]:
            continue
        step_keys = [s["key"] for s in entry["steps"]]
        try:
            released = improvement_type.release_invalid(step_keys, improvement["params"],
                                                        explicit=explicit, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 — the rows still go; the artefact GC owns what stays behind
            logger.warning("improvements: files of the wrong steps of %s not released: %s",
                           improvement["id"], e, exc_info=True)
            released = {"files": 0, "bytes": 0, "kept": [{"key": k, "why": str(e)} for k in step_keys]}
        entry["files"] = int(released.get("files") or 0)
        entry["bytes"] = int(released.get("bytes") or 0)
        entry["kept"] = list(released.get("kept") or [])
        if not dry_run:
            removed = store.delete_steps(improvement["id"], step_keys)
            logger.info("improvements: %d wrong step(s) of %s (%s) removed, %d file(s) / %.1f MB deleted; "
                        "reasons: %s", removed, improvement["id"], improvement["type_id"], entry["files"],
                        entry["bytes"] / 1e6, sorted({s["reason"] for s in entry["steps"]}))
            for step in entry["steps"]:
                _undefer(improvement["id"], step["key"])
            _close_if_finished(improvement["id"])
        report["entries"].append(entry)
        report["removed"] += len(entry["steps"])
        report["files"] += entry["files"]
        report["bytes"] += entry["bytes"]
    return report


def validate_due_entries() -> Dict[str, Any]:
    """The automatic validity pass over every open or paused entry that was not judged within
    ``SCAN_INTERVAL_S`` (the tick and the entry list call it; after a start every entry is due once)."""
    total: Dict[str, Any] = {"removed": 0, "files": 0, "bytes": 0}
    for improvement in store.list_all():
        if improvement["status"] not in ("open", "paused") or not _validate_due(improvement["id"]):
            continue
        try:
            result = remove_invalid(improvement["id"])
        except Exception as e:  # noqa: BLE001 — one broken type must not stop the others
            logger.warning("improvements: validity pass of %s failed: %s", improvement["id"], e, exc_info=True)
            continue
        for field in total:
            total[field] += result[field]
    return total


def _dropped_as_invalid(row: Dict[str, Any]) -> Optional[bool]:
    """The check right before a step runs: True = it was wrong and is gone now, False = valid, None = its
    type could not judge it now (the caller holds it like a busy step)."""
    result = remove_invalid(row["improvement_id"], keys=[row["candidate_key"]])
    entry = next(iter(result["entries"]), None)
    if entry is None:
        return False
    return None if entry["error"] else bool(entry["steps"])


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

def submit_allowed(needs_media: bool = True) -> Tuple[bool, str]:
    """(may a step be submitted right now, why not) — the reason is what the
    admin panel shows: media_off | disabled | frozen | busy | active | ok.

    ``needs_media`` False asks for the gates BEHIND the media switch — what a
    CPU-only type (``ImprovementType.needs_media`` False) is held by."""
    # Most improvement types generate media (models, images, bakes), so the
    # world's media master switch stops them — checked first because it is
    # the cheapest read and needs no DB at all.
    if needs_media and not media_generation_enabled():
        return False, "media_off"
    settings = store.get_settings()
    if not settings["enabled"]:
        return False, "disabled"
    if is_world_frozen():
        return False, "frozen"
    # The admin tick runs this engine even while the task queue is paused (a
    # forced entry must go on); everything else stops with the pause as before.
    if get_task_queue().is_paused("default"):
        return False, "paused"
    if get_task_queue().has_pending_task(TASK_TYPE):
        return False, "busy"
    if user_activity.seconds_since() < settings["idle_minutes"] * 60:
        return False, "active"
    return True, "ok"


def request_run_now(improvement_id: str) -> None:
    """Force the entry: every tick runs its steps past the gates in
    ``RUN_NOW_OVERRIDES`` until it has nothing left to run."""
    store.update(improvement_id, forced=True)


def stop_run_now(improvement_id: str) -> None:
    """Back to the normal rules (idle window, engine switch, freeze)."""
    store.update(improvement_id, forced=False)


def _needs_media(type_id: str) -> bool:
    """Whether a step of this type is held by the media switch.  An unknown
    type is held: it cannot run anyway, and the handler skips it."""
    improvement_type = registry.get(type_id)
    return True if improvement_type is None else bool(improvement_type.needs_media)


def _held_by_pause(row: Dict[str, Any]) -> str:
    """The character whose paused automatic generation holds this step (Ruling A42), else "": a type that
    generates media (``needs_media``; the CPU-only ones run) working on one character
    (``ImprovementType.subject_character``)."""
    if not _needs_media(row["type_id"]):
        return ""
    improvement_type = registry.get(row["type_id"])
    if improvement_type is None:
        return ""
    from app.core import generation_pause
    name = improvement_type.subject_character(row["candidate_key"])
    return name if name and generation_pause.is_paused(name) else ""


def held_rows(character_name: str) -> List[Dict[str, Any]]:
    """The pending steps the character's pause holds (Ruling A42), in queue order — a forced entry ("Run now",
    a click) is not held."""
    forced = {i["id"] for i in store.list_all() if i["forced"]}
    return [r for r in ordered_queue() if r["status"] == "pending" and r["improvement_id"] not in forced
            and _held_by_pause(r) == character_name]


def cancel_held(character_name: str, improvement_id: str, key: str) -> bool:
    """The Figure tab's Cancel of a held step (Ruling A42): skipped like a step that was given up, retryable in
    the Improvements tab, no attempt counted — nothing of it ran. True when it was held."""
    from app.core import generation_pause
    if not any(r["improvement_id"] == improvement_id and r["candidate_key"] == key
               for r in held_rows(character_name)):
        return False
    store.mark_result(improvement_id, key, status="skipped", error=generation_pause.IMPROVEMENT_CANCELLED,
                      count_attempt=False)
    _close_if_finished(improvement_id)
    return True


def run_now(improvement_id: str) -> Dict[str, Any]:
    """The admin's "Run now": force the entry and submit its next pending step
    NOW — the following ones go out tick by tick, all past the idle window,
    the engine switch, a freeze and a queue pause.

    Only the media switch stops it (and only a type that ``needs_media``), and
    an improvement step already in flight makes it wait: the entry stays
    forced and the next tick submits its step as soon as that one is done
    (one step at a time is the engine's rule).
    Reasons: ``started`` | ``queued`` | ``media_off`` | ``paused`` | ``done`` |
    ``empty``."""
    improvement = store.get(improvement_id)
    if improvement is None:
        return {"ok": False, "reason": "gone"}
    if improvement["status"] != "open":
        return {"ok": False, "reason": improvement["status"]}
    if not media_generation_enabled() and _needs_media(improvement["type_id"]):
        return {"ok": False, "reason": "media_off"}
    row = None
    for candidate in ordered_queue():
        if candidate["improvement_id"] != improvement_id or candidate["status"] != "pending":
            continue
        # A wrong step is dropped here, not started (``remove_invalid``).
        if _dropped_as_invalid(candidate) is False:
            row = candidate
            break
    if row is None:
        return {"ok": False, "reason": "empty"}
    request_run_now(improvement_id)
    if get_task_queue().has_pending_task(TASK_TYPE):
        return {"ok": True, "reason": "queued"}
    # The click is an explicit "try this now" — a busy deferral does not hold it.
    _undefer(improvement_id, row["candidate_key"])
    task_id = _submit(row)
    if not task_id:
        return {"ok": False, "reason": "dedup"}
    return {"ok": True, "reason": "started", "task_id": task_id}


def _submit(row: Dict[str, Any]) -> str:
    """Mark the step running and hand it to the TaskQueue; "" when the queue
    deduplicated it (the step is given back as pending)."""
    # Mark FIRST, submit second. A worker can pick the task up — and even
    # finish it — before ``submit`` has returned here; a mark_running after
    # that would overwrite the handler's 'done' back to 'running'.
    store.mark_running(row["improvement_id"], row["candidate_key"])
    task_id = get_task_queue().submit(
        TASK_TYPE,
        {"improvement_id": row["improvement_id"],
         "candidate_key": row["candidate_key"]},
        queue_name=QUEUE_NAME, priority=STEP_PRIORITY, max_retries=0,
        deduplicate=True)
    if not task_id:
        # Deduplicated: nothing is owed after all, so give the step back.
        store.mark_result(row["improvement_id"], row["candidate_key"],
                          status="pending", count_attempt=False)
    return task_id or ""


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

    # 2. Sweep finished one-shots and rescan standing entries, independent of idleness.
    scanned = 0
    forced: Set[str] = set()
    for improvement in store.list_all():
        if (improvement["mode"] == "one_shot" and improvement["status"] == "done"
                and not improvement["skipped"] and not improvement["failed"]):
            store.delete(improvement["id"])
            logger.info("improvements: removed finished one-shot %s", improvement["id"])
            continue
        if improvement["forced"]:
            # Worked off (or no longer open): the run-now is over. A pending
            # step a later scan adds belongs to the normal rules again.
            if (improvement["status"] != "open"
                    or improvement["pending"] + improvement["running"] == 0):
                stop_run_now(improvement["id"])
            else:
                forced.add(improvement["id"])
        if not _scan_due(improvement):
            continue
        try:
            scan(improvement["id"])
            scanned += 1
        except Exception as e:  # noqa: BLE001 — one broken type must not stop the tick
            logger.warning("improvements: scan of %s failed: %s",
                           improvement["id"], e, exc_info=True)

    # 3. Every entry that did not rescan is judged for wrong steps on the scan
    #    interval (and once after a start) — a one_shot or paused entry never
    #    rescans, and a scan judges its own entry first.
    validate_due_entries()

    # 4. One step.
    allowed, reason = submit_allowed()
    # With the media switch off the CPU-only types keep running: the gates
    # BEHIND the switch decide for them, and the loop below passes over every
    # step of a type that needs media.
    media_off = not allowed and reason == "media_off"
    if media_off:
        allowed, reason = submit_allowed(needs_media=False)
    # A forced entry passes the gates it overrides — but never an in-flight
    # step, which ``submit_allowed`` does not reach when an earlier gate failed.
    override = (not allowed and reason in RUN_NOW_OVERRIDES and bool(forced)
                and not task_queue.has_pending_task(TASK_TYPE))
    if not allowed and not override:
        return {"scanned": scanned, "submitted": "", "reason": reason}

    now = utc_now()
    deferred = 0
    held = 0
    paused = 0
    # Forced entries go first even when the gates are open: the admin asked
    # for them. Stable sort, so each group keeps the queue order.
    rows = sorted(ordered_queue(), key=lambda r: r["improvement_id"] not in forced)
    for row in rows:
        if row["status"] != "pending":
            continue
        if override and row["improvement_id"] not in forced:
            continue
        if media_off and _needs_media(row["type_id"]):
            held += 1
            continue
        if row["improvement_id"] not in forced and _held_by_pause(row):
            # Ruling A42: the subject's automatic generation is paused — the step waits for the Resume.
            paused += 1
            continue
        # A step that just came back busy waits out BUSY_DEFER_S so the steps
        # behind it get their turn — forced or not, or a dead backend would be
        # hammered every tick.
        if _deferred(row["improvement_id"], row["candidate_key"], now):
            deferred += 1
            continue
        # The check before the run: a wrong step is dropped, never submitted.
        verdict = _dropped_as_invalid(row)
        if verdict is None:
            _defer(row["improvement_id"], row["candidate_key"])
            deferred += 1
            continue
        if verdict:
            continue
        _undefer(row["improvement_id"], row["candidate_key"])
        task_id = _submit(row)
        if not task_id:
            return {"scanned": scanned, "submitted": "", "reason": "dedup"}
        return {"scanned": scanned, "submitted": task_id, "reason": "ok"}

    # "media_off": the switch held back every runnable step; "deferred":
    # pending steps exist, but every one of them came back busy within the
    # last BUSY_DEFER_S — nothing is submitted this tick.
    return {"scanned": scanned, "submitted": "",
            "reason": ("media_off" if held else
                       "deferred" if deferred else
                       "character_paused" if paused else "empty")}


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
        # A skip finishes a step just as a success does: if it was the last one
        # of a one_shot, the entry is worked off and must close here — nothing
        # else will ever come back to it.
        _close_if_finished(improvement_id)
        return {"skipped": message}

    if not improvement["forced"] and _held_by_pause({"type_id": improvement["type_id"], "candidate_key": key}):
        # Ruling A42: the subject was paused while the task waited — back to pending, no attempt; the tick holds
        # it until the Resume.
        store.mark_result(improvement_id, key, status="pending", count_attempt=False)
        return {"held": key}

    # The check before the run, once more at the worker: the rules may have
    # changed while the task waited.
    try:
        invalid = improvement_type.invalid_reason(key, improvement["params"])
    except Exception as e:  # noqa: BLE001 — not judged now: held like a busy step
        store.mark_result(improvement_id, key, status="pending", error=str(e), count_attempt=False)
        _defer(improvement_id, key)
        return {"busy": f"validity not judged: {e}"}
    if invalid:
        # Given back first — a running row is never removed — then dropped
        # with its own files like in every validity pass.
        store.mark_result(improvement_id, key, status="pending", count_attempt=False)
        remove_invalid(improvement_id, keys=[key])
        return {"skipped": f"invalid: {invalid}"}

    candidate = Candidate(key, step["candidate_label"],
                          hub_jobs=step.get("hub_jobs"), note=step.get("note") or "")
    try:
        # The step's own generations must not end the user's idle window.
        with user_activity.suppressed():
            result_note = improvement_type.apply(candidate, improvement["params"], task_id)
    except (BackendBusyError, CandidateBusy, HubOpBusy, MediaGenerationDisabled) as e:
        # Load, not a defect (HubOpBusy: another hub operation holds this
        # target — it is in flight, not broken; MediaGenerationDisabled: the
        # switch flipped mid-run — it is the switch, not the subject) — the
        # candidate keeps both its attempts, and sits out BUSY_DEFER_S so it
        # does not block the steps behind it.
        store.mark_result(improvement_id, key, status="pending", error=str(e),
                          count_attempt=False)
        _defer(improvement_id, key)
        return {"busy": str(e)}
    except CandidateRefused as e:
        # The subject's own gates said no, or its chain recorded a failure
        # automatic triggers honour. Terminal after this ONE attempt: a second
        # attempt would re-spend a refused source, which is a person's
        # decision (the Wardrobe, the 3D tab), never ours — and Retry refuses
        # it too (``store.retry_step``).
        logger.info("improvement step %s/%s refused: %s", improvement_id, key, e)
        store.mark_result(improvement_id, key, status="skipped", error=str(e),
                          count_attempt=True, refused=True)
        store.update(improvement_id,
                     failed_count=int(improvement["failed_count"]) + 1)
        _close_if_finished(improvement_id)
        return {"refused": str(e)}
    except Exception as e:  # noqa: BLE001 — every defect is one attempt
        logger.warning("improvement step %s/%s failed: %s",
                       improvement_id, key, e, exc_info=True)
        attempts = int(step["attempts"]) + 1
        # A lost hub job is terminal: a second attempt would submit the same
        # work as a new hub job, which is a person's decision, never ours.
        if attempts >= MAX_ATTEMPTS or isinstance(e, HubJobLost):
            store.mark_result(improvement_id, key, status="skipped",
                              error=str(e), count_attempt=True)
            store.update(improvement_id,
                         failed_count=int(improvement["failed_count"]) + 1)
            # Giving up finishes the step. A one_shot whose LAST candidate is
            # skipped has nothing pending or running left, so it closes here —
            # without this it would stay 'open' with 0 runnable steps forever.
            _close_if_finished(improvement_id)
        else:
            store.mark_result(improvement_id, key, status="pending",
                              error=str(e), count_attempt=True)
        return {"error": str(e)}

    store.mark_result(improvement_id, key, status="done", count_attempt=False)
    if isinstance(result_note, str) and result_note:
        store.set_note(improvement_id, key, result_note)
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
        if not improvement["skipped"] and not improvement["failed"]:
            store.delete(improvement_id)
            logger.info("improvements: removed finished one-shot %s", improvement_id)
        else:
            store.update(improvement_id, status="done", forced=False)


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
        # A forced entry runs past the gates in RUN_NOW_OVERRIDES — the panel
        # says so instead of a gate that does not hold it back.
        "forced": any(i["forced"] and i["status"] == "open"
                      for i in store.list_all()),
        "running_step": running[0] if running else None,
        "pending_total": sum(pending.values()),
        # The hub jobs the open entries still owe; None when any pending step
        # could not be estimated.
        "pending_hub_jobs": store.pending_hub_jobs_total(open_only=True),
        "estimate_s": estimate,
    }
