"""World Dev routes — the free-mode agent plus the background pause/debug endpoints."""
import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.auth_dependency import require_admin
from app.core.log import get_logger

logger = get_logger("world_dev")

router = APIRouter(prefix="/world-dev", tags=["world-dev"],
                   dependencies=[Depends(require_admin)])


# ── Global Pause / Resume ──

def _get_pause_state() -> Dict[str, bool]:
    """Returns the current pause state of all subsystems.

    Uses the llm_task_state "world_dev" runtime preset (disabled tasks),
    not the removed global llm_queue pause.
    """
    from app.core.task_queue import get_task_queue
    from app.routes.scheduler import get_scheduler_manager
    from app.core.llm_task_state import runtime_disabled_tasks

    task_queue = get_task_queue()
    scheduler_mgr = get_scheduler_manager()

    queue_paused = task_queue.is_paused("default") if task_queue else False
    llm_paused = bool(runtime_disabled_tasks())
    scheduler_paused = False
    if scheduler_mgr and hasattr(scheduler_mgr, '_global_paused'):
        scheduler_paused = scheduler_mgr._global_paused

    # AgentLoop pause state mirrors task_queue 'default' pause flag, so
    # ``queue_paused`` already covers it.
    all_paused = queue_paused and scheduler_paused and llm_paused
    return {
        "paused": all_paused,
        "queue_paused": queue_paused,
        "llm_paused": llm_paused,
        "scheduler_paused": scheduler_paused,
    }


@router.post("/pause-all")
def pause_all():
    """Pauses all LLM and background activities.

    The llm_task_state "world_dev" preset disables background tasks,
    while chat/story remain active.
    """
    from app.core.task_queue import get_task_queue
    from app.routes.scheduler import get_scheduler_manager
    from app.core.llm_task_state import activate_preset_runtime

    disabled = activate_preset_runtime("world_dev")
    logger.info("LLM task disable active (world_dev): %d tasks off", len(disabled))

    # Note: ThoughtRunner.pause() removed — pausing the task_queue 'default'
    # below also halts the AgentLoop (its pause source).

    task_queue = get_task_queue()
    if task_queue:
        task_queue.pause_queue("default")

    scheduler_mgr = get_scheduler_manager()
    if scheduler_mgr:
        for job in scheduler_mgr.scheduler.get_jobs():
            job.pause()
        scheduler_mgr._global_paused = True
        logger.info("Scheduler paused (%d jobs)", len(scheduler_mgr.scheduler.get_jobs()))

    logger.info("Background activities paused (World Dev mode)")
    return _get_pause_state()


@router.post("/resume-all")
def resume_all():
    """Resumes all LLM and background activities."""
    from app.core.task_queue import get_task_queue
    from app.routes.scheduler import get_scheduler_manager
    from app.core.llm_task_state import clear_runtime

    clear_runtime()

    task_queue = get_task_queue()
    if task_queue:
        task_queue.resume_queue("default")

    scheduler_mgr = get_scheduler_manager()
    if scheduler_mgr:
        for job in scheduler_mgr.scheduler.get_jobs():
            job.resume()
        scheduler_mgr._global_paused = False
        logger.info("Scheduler resumed (%d jobs)", len(scheduler_mgr.scheduler.get_jobs()))

    logger.info("Background activities resumed")
    return _get_pause_state()


@router.get("/pause-status")
def get_pause_status():
    """Returns the current pause state."""
    return _get_pause_state()


@router.post("/trigger-thought")
async def trigger_thought(character_name: str,
    context_hint: str = "",
    fast: bool = False,
    tool_whitelist: str = "",
    suppress_notification: bool = False):
    """Force a thought tick for one character.

    Bypass idle checks, cooldown and probability for immediate debugging.

    Call: POST /world-dev/trigger-thought?character_name=Demo
    Optional: context_hint, fast, tool_whitelist (comma-separated), suppress_notification
    """
    from app.core.thoughts import get_thought_runner
    tl = get_thought_runner()
    if not tl:
        raise HTTPException(status_code=503, detail="ThoughtRunner not active")

    _whitelist = [t.strip() for t in tool_whitelist.split(",") if t.strip()] or None

    try:
        await asyncio.wait_for(
            tl.run_thought_turn(character_name,
                                context_hint=context_hint, fast=fast,
                                tool_whitelist=_whitelist,
                                suppress_notification=suppress_notification),
            timeout=300)
        return {"ok": True, "character": character_name, "context_hint": context_hint[:80]}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Thought turn timed out (>300s)")
    except Exception as e:
        logger.error("Thought trigger error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Free mode (agent) ────────────────────────────────────────────────────
# Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 8. Thin
# adapters over app.core.world_dev_agent.RunManager; the state table lives
# there. Fixed paths are declared before /free/{run_id}.

def _run_conflict(run_id: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": detail, "run_id": run_id})


def _opt_int(raw: Any, field: str, positive: bool = True) -> Optional[int]:
    """An optional integer field: None/"" -> None; a bool, a non-number or
    (with `positive`, the budgets) a value < 1 -> 400 before the manager is
    called, so a bad budget never freezes the world or starts a run."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, bool):
        raise HTTPException(status_code=400, detail=f"{field} must be a number")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be a number")
    if positive and value < 1:
        raise HTTPException(status_code=400, detail=f"{field} must be at least 1")
    return value


def _opt_bool(raw: Any, field: str, default: bool) -> bool:
    """An optional boolean field: None -> default; anything but a JSON bool
    -> 400 (explicit admin input is refused, not guessed)."""
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise HTTPException(status_code=400, detail=f"{field} must be true or false")
    return raw


async def _free_body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 — an empty body is an empty object
        return {}
    return data if isinstance(data, dict) else {}


async def _free_action(run_id: str, action):
    """Run one RunManager action, mapping its errors to HTTP."""
    from app.core.world_dev_agent import RunStateError
    try:
        return await action()
    except RunStateError as e:
        return _run_conflict(e.run_id or run_id, str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/free/defaults")
def free_defaults() -> Dict[str, Any]:
    from app.core.world_dev_agent import DEFAULT_MAX_STEPS, DEFAULT_MAX_TOKENS_TOTAL
    return {"max_steps": DEFAULT_MAX_STEPS, "max_tokens_total": DEFAULT_MAX_TOKENS_TOTAL}


@router.post("/free/start")
async def free_start(request: Request, user: Dict[str, Any] = Depends(require_admin)):
    from app.core.world_dev_agent import (DEFAULT_MAX_STEPS, DEFAULT_MAX_TOKENS_TOTAL,
                                          EFFORT_LEVELS, get_run_manager)
    from app.core.world_dev_runs import RunOpenError
    data = await _free_body(request)
    model = str(data.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")
    # The per-reply cap keeps "0 / negative = the model's default".
    max_tokens = _opt_int(data.get("max_tokens"), "max_tokens", positive=False)
    max_steps = _opt_int(data.get("max_steps"), "max_steps") or DEFAULT_MAX_STEPS
    max_total = (_opt_int(data.get("max_tokens_total"), "max_tokens_total")
                 or DEFAULT_MAX_TOKENS_TOTAL)
    # Effort (Claude thinking depth): '' = the model's default; an unknown
    # level is refused, not dropped (explicit admin input).
    effort = str(data.get("effort") or "").strip().lower()
    if effort and effort not in EFFORT_LEVELS:
        raise HTTPException(status_code=400, detail=(
            f"unknown effort {effort!r} (allowed: {', '.join(EFFORT_LEVELS)})"))
    # The run's media switch (world_dev_media): default on, a non-bool refused.
    media_enabled = _opt_bool(data.get("generate_media"), "generate_media", default=True)
    try:
        run_id = await get_run_manager().start(
            str(data.get("task") or ""), model, str(data.get("provider") or ""),
            str((user or {}).get("id") or ""),
            max_tokens=max_tokens if max_tokens and max_tokens > 0 else None,
            max_steps=max_steps, max_tokens_total=max_total, effort=effort,
            media_enabled=media_enabled)
    except RunOpenError as e:
        return _run_conflict(e.run_id, str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"run_id": run_id}


@router.get("/free/runs")
async def free_runs() -> Dict[str, Any]:
    from app.core import world_dev_runs as wr
    return {"runs": await asyncio.to_thread(wr.list_runs)}


@router.get("/free/open")
async def free_open() -> Dict[str, Any]:
    from app.core import world_dev_runs as wr
    return {"run": await asyncio.to_thread(wr.open_run)}


#: The fields of a journal row the run detail ships (FreeModePanel reads
#: seq, tool, kind, line, undone_at; turn and state for orientation).
_STEP_ROW_KEYS = ("seq", "turn", "tool", "kind", "line", "state", "undone_at")


@router.get("/free/{run_id}")
async def free_run_detail(run_id: str) -> Dict[str, Any]:
    from app.core import world_dev_runs as wr
    from app.core import world_dev_undo as wu
    from app.core.world_dev_agent import get_run_manager, turn_summaries
    manager = get_run_manager()

    def _detail() -> Optional[Dict[str, Any]]:
        run = wr.get_run(run_id)
        if run is None:
            return None
        steps = wr.steps(run_id)
        # The panel shows seq/tool/kind/line/undone per row; the journal's
        # args/before/written/inverse (a recreate_character inverse carries
        # the whole character snapshot, megabytes) stay out of the detail.
        rows = [{k: s.get(k) for k in _STEP_ROW_KEYS} for s in steps]
        return {"run": run, "steps": rows,
                "skipped": run.get("skipped") or [],
                "discard_preview": wu.discard_preview(run_id),
                # Per turn: kept / cut_by_budget / rolled_back / running,
                # with its write rows and how many of them are undone.
                "turns": turn_summaries(run, steps, manager.turn_outcomes(run_id)),
                # Write rows of the run not undone: what Accept would keep.
                "remaining_writes": sum(1 for s in steps if s.get("kind") == "write"
                                        and not s.get("undone_at")),
                # This turn's counters against the per-turn budgets (None
                # when this process ran no turn of the run).
                "turn_usage": manager.turn_usage(run_id)}

    detail = await asyncio.to_thread(_detail)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    detail["busy"] = manager.is_busy(run_id)
    return detail


@router.post("/free/{run_id}/message")
async def free_message(run_id: str, request: Request):
    from app.core.world_dev_agent import get_run_manager
    data = await _free_body(request)
    max_steps = _opt_int(data.get("max_steps"), "max_steps")
    max_total = _opt_int(data.get("max_tokens_total"), "max_tokens_total")

    async def _go():
        await get_run_manager().message(run_id, str(data.get("text") or ""),
                                        max_steps=max_steps, max_tokens_total=max_total)
        return {"ok": True}
    return await _free_action(run_id, _go)


@router.post("/free/{run_id}/stop")
async def free_stop(run_id: str):
    from app.core.world_dev_agent import get_run_manager

    async def _go():
        await get_run_manager().stop(run_id)
        return {"ok": True}
    return await _free_action(run_id, _go)


@router.post("/free/{run_id}/accept")
async def free_accept(run_id: str):
    from app.core.world_dev_agent import get_run_manager

    async def _go():
        await get_run_manager().accept(run_id)
        return {"ok": True}
    return await _free_action(run_id, _go)


@router.post("/free/{run_id}/discard")
async def free_discard(run_id: str):
    from app.core.world_dev_agent import get_run_manager

    async def _go():
        report = await get_run_manager().discard(run_id)
        return {"ok": True, "report": report}
    return await _free_action(run_id, _go)


# ── Media lane (plan 2026-11-25-world-dev-free-media, Task 10) ──
# Thin adapters over app.core.world_dev_media; row state changes push
# "generation" to the admins from there.

async def _media_action(run_id: str, fn, *args):
    from app.core.world_dev_media import MediaConflict
    try:
        return await asyncio.to_thread(fn, run_id, *args)
    except MediaConflict as e:
        return _run_conflict(run_id, str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")


@router.get("/free/{run_id}/media")
async def free_media(run_id: str) -> Dict[str, Any]:
    """The run's media switch and state, and per element its newest job row."""
    from app.core import world_dev_media as wm
    status = await asyncio.to_thread(wm.media_status, run_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return status


@router.post("/free/{run_id}/media-switch")
async def free_media_switch(run_id: str, request: Request):
    """{enabled}: off on any open run (queued rows cancelled, a running one
    stops after its step); on only in review (409 while a turn runs), then
    what is due is queued. 409 on a closed run."""
    from app.core import world_dev_media as wm
    data = await _free_body(request)
    if not isinstance(data.get("enabled"), bool):
        raise HTTPException(status_code=400, detail="enabled must be true or false")
    return await _media_action(run_id, wm.set_run_switch, data["enabled"])


@router.post("/free/{run_id}/media/retry")
async def free_media_retry(run_id: str):
    """Retry the failed/skipped steps; only in review (409 otherwise)."""
    from app.core import world_dev_media as wm
    result = await _media_action(run_id, wm.retry)
    if isinstance(result, JSONResponse):
        return result
    return {"queued": result}


@router.get("/free/{run_id}/events")
async def free_events(run_id: str, after: int = 0):
    """SSE: one "data:" frame per run event with ev > after (a {"ev": 0,
    "type": "reset"} frame when after is beyond this process's buffer)."""
    from app.core import world_dev_runs as wr
    from app.core.world_dev_agent import get_run_manager
    if await asyncio.to_thread(wr.get_run, run_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")

    async def stream():
        try:
            async for ev in get_run_manager().subscribe(run_id, max(0, int(after))):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 — end the stream with the error
            logger.error("world-dev %s: event stream failed: %s", run_id, e)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
