"""Cached-verdict orchestration for the ``llm_judgement`` quest condition (quest stage 3).

Evaluation of ``llm_judgement`` never calls an LLM inline. Instead:
  1. The condition evaluator reads the cached row in ``quest_judgements`` for
     ``(run_id, step, criterion_key, mind)``.
  2. While no ``yes`` verdict is cached, :func:`request` checks the in-process
     per-minute rate cap and atomically claims a slot in ``quest_judgements``
     (``quests.claim_judgement``) before submitting a low-priority task-queue job.
  3. The task-queue handler :func:`handle` re-reads the run, gathers the avatar's
     subjective perception transcript since ``step_started_at``, calls the configured
     judge function, writes the verdict via ``quests.set_judgement``, and notifies
     the quest engine (``quest.judged``) so evaluation runs again on the worker.

The default judge raises ``RuntimeError("no quest judge configured")``; a later task
wires the tool-model judge and registers the task-queue handler.
"""
from __future__ import annotations

from collections import deque
import hashlib
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.task_queue import get_task_queue
from app.core.timeutils import utc_now_iso

logger = get_logger("quest_judgement")

TASK_TYPE = "quest_judgement"
MIN_INTERVAL_S = 30
MAX_PER_MINUTE = 6
TRANSCRIPT_LINES = 40
PENDING_STALE_S = 600
TASK_PRIORITY = 30

_rate_lock = threading.Lock()
_recent_submits: Deque[float] = deque()


def min_interval_s() -> float:
    """Minimum seconds between judgement attempts for the same (run, step, criterion, mind)."""
    return MIN_INTERVAL_S


def max_per_minute() -> int:
    """In-process cap on judgement task submissions per rolling 60 seconds."""
    return MAX_PER_MINUTE


def criterion_key(criterion: str) -> str:
    """Stable 16-hex key of the rendered criterion text."""
    return hashlib.sha1((criterion or "").encode("utf-8")).hexdigest()[:16]


def _rate_limited() -> bool:
    now = time.monotonic()
    cutoff = now - 60.0
    with _rate_lock:
        while _recent_submits and _recent_submits[0] <= cutoff:
            _recent_submits.popleft()
        return len(_recent_submits) >= max_per_minute()


def _record_submit() -> None:
    now = time.monotonic()
    cutoff = now - 60.0
    with _rate_lock:
        while _recent_submits and _recent_submits[0] <= cutoff:
            _recent_submits.popleft()
        _recent_submits.append(now)


def request(ctx, criterion: str) -> None:
    """Claim a judgement slot and submit a background task-queue job; never raises."""
    try:
        from app.models import perception_store, quests

        run = getattr(ctx, "run", None) or {}
        run_id = str(run.get("id") or "")
        if not run_id or run.get("state") != "open":
            return
        if _rate_limited():
            return
        step = int(run.get("current_step") or 0)
        key = criterion_key(criterion)
        newest_id = perception_store.newest_perception_id(ctx.avatar)
        now_iso = utc_now_iso(timespec="microseconds")
        claimed = quests.claim_judgement(
            run_id, step, key, ctx.mind, ctx.avatar,
            now=now_iso,
            min_interval_s=min_interval_s(),
            newest_id=newest_id,
            pending_stale_s=PENDING_STALE_S,
        )
        if not claimed:
            return
        payload = {
            "run_id": run_id,
            "step": step,
            "criterion_key": key,
            "criterion": criterion,
            "mind": ctx.mind,
            "avatar": ctx.avatar,
            "since": str(run.get("step_started_at") or ""),
            "through_id": newest_id,
        }
        try:
            task_id = get_task_queue().submit(
                TASK_TYPE,
                payload,
                queue_name="quests",
                priority=TASK_PRIORITY,
                agent_name=ctx.avatar,
                max_retries=0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("quest judgement submit failed for %s/%s: %s", run_id, key, e)
            try:
                prev = quests.get_judgement(run_id, step, key, ctx.mind) or {}
                prev_through = int(prev.get("judged_through") or 0)
                quests.set_judgement(
                    run_id, step, key, ctx.mind,
                    state="error",
                    reason=f"submit failed: {e}",
                    judged_through=prev_through,
                )
            except Exception as e2:  # noqa: BLE001
                logger.warning("quest judgement error record failed for %s/%s: %s", run_id, key, e2)
            return
        _record_submit()
        quests.note_judgement_task(run_id, step, key, ctx.mind, task_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("quest judgement request failed: %s", e)


def _judge(criterion: str, transcript: List[Dict[str, Any]], avatar: str) -> Tuple[bool, str]:
    raise RuntimeError("no quest judge configured")


def handle(payload: Dict[str, Any], *,
           judge_fn: Optional[Callable[[str, List[Dict[str, Any]], str], Tuple[bool, str]]] = None
           ) -> Dict[str, str]:
    """Task-queue handler for ``quest_judgement`` jobs."""
    from app.core import quest_engine
    from app.models import perception_store, quests

    run_id = str(payload.get("run_id") or "")
    step = int(payload.get("step", -1))
    key = str(payload.get("criterion_key") or "")
    criterion = str(payload.get("criterion") or "")
    mind = str(payload.get("mind") or "")
    avatar = str(payload.get("avatar") or "")
    since = str(payload.get("since") or "")
    through_id = int(payload.get("through_id") or 0)

    run = quests.get_run(run_id)
    if run is None or run.get("state") != "open" or int(run.get("current_step", -1)) != step:
        return {"status": "skipped"}

    transcript = perception_store.get_character_stream_since(
        avatar, since_ts=since, limit=TRANSCRIPT_LINES)
    max_line_id = max((int(line["id"]) for line in transcript), default=0)
    through = max(max_line_id, through_id)

    if not transcript:
        state = "no"
        reason = "Nothing has been said since this step began"
    else:
        fn = judge_fn or _judge
        try:
            passed, raw_reason = fn(criterion, transcript, avatar)
            state = "yes" if passed else "no"
            reason = str(raw_reason or "")
        except Exception as e:  # noqa: BLE001
            state = "error"
            reason = str(e)[:200]

    stored = quests.set_judgement(
        run_id, step, key, mind,
        state=state, reason=reason, judged_through=through)
    if not stored:
        return {"status": "stale"}
    quest_engine.notify("quest.judged", avatar)
    return {"status": state}
