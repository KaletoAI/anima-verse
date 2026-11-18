"""Queue status endpoint — shows all running and recent tasks."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.core import users
from app.core.auth_dependency import get_current_user, require_admin

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/status")
async def queue_status(user=Depends(get_current_user)) -> Dict[str, Any]:
    """The combined status of every task source.

    A row's ``log_tail`` (the Blender output of a run left due) goes to admins only: it quotes
    server paths, and this route is polled by every player's panel.

    Merges:
    - the provider queues (per-provider LLM calls, chat streaming)
    - the TaskQueue (persistent background tasks + tracked GPU/TTS/image tasks)
    """
    import asyncio
    from app.core.provider_manager import get_provider_manager
    from app.core.task_queue import get_task_queue
    from app.imagegen.base import media_generation_enabled

    pm = get_provider_manager()
    # get_combined_status() takes per-channel locks — run in the threadpool
    # so a contended lock never blocks the event loop.
    combined = await asyncio.to_thread(pm.get_combined_status)
    tq = get_task_queue()
    # Same reason: get_status() and get_tracked_recent() query task_queue.db.
    # This route is POLLED by the queue panel, so the SQLite reads were a
    # recurring loop stall (event-loop watchdog, 2026-08-23).
    tq_status = await asyncio.to_thread(tq.get_status)

    # Active tracked tasks (running OR pending) — image generation, TTS, GPU tasks
    # that run outside the TaskQueue but must show in the panel. The status is
    # set explicitly: the running/pending queries do not select the status
    # column, so the frontend would never see "running" otherwise.
    _active = []
    for t in tq_status.get("running", []) or []:
        if t.get("task_origin") == "tracked":
            _active.append({**t, "status": "running"})
    for t in tq_status.get("pending", []) or []:
        if t.get("task_origin") == "tracked":
            _active.append({**t, "status": "pending"})

    recent_tasks = await asyncio.to_thread(tq.get_tracked_recent)
    if not (isinstance(user, dict) and user.get("role") == users.ROLE_ADMIN):
        recent_tasks = [{k: v for k, v in t.items() if k != "log_tail"} for t in recent_tasks]

    return {
        # Per-Channel Queues (each GPU = own channel with tasks)
        "providers": combined.get("providers", {}),
        # Flat fields (still used by UI)
        "chat_active": combined["chat_active"],
        "recent": combined["recent"],
        # Tracked + background tasks (unified)
        "active_tasks": _active,
        "recent_tasks": recent_tasks,
        # Background tasks (flat, no named queues)
        "bg_tasks": tq_status,
        # World master switch (image_generation.enabled) — a plain in-memory
        # config read, so the polled panel/header can show "media off" without
        # a second request.
        "media_generation_enabled": media_generation_enabled(),
    }


#: 409 detail of a Cancel on a CPU refit that is computing (the TaskPanel shows it, through ``t()``).
CPU_REFIT_RUNNING = "A CPU re-fit is computing and cannot be stopped — it ends on its own"


@router.delete("/tasks/{task_id}")
def cancel_task(task_id: str) -> Dict[str, Any]:
    """Cancel a waiting or running task of the queue. A CPU refit (``refit_pool.TASK_TYPE``) that is computing
    cannot be stopped — its compute runs on to the end and publishes — so its Cancel is refused with 409
    (``CPU_REFIT_RUNNING``) instead of marking a row cancelled whose work goes on; a waiting one is cancelled
    (it does not run)."""
    from app.core import refit_pool
    from app.core.provider_manager import get_provider_manager
    from app.core.task_queue import get_task_queue

    tq = get_task_queue()
    if any(t["task_id"] == task_id and t["status"] == "running"
           for t in tq.list_tasks_of_type(refit_pool.TASK_TYPE)):
        raise HTTPException(status_code=409, detail=CPU_REFIT_RUNNING)

    pm = get_provider_manager()
    cancelled = pm.cancel_task(task_id)

    if not cancelled:
        # Fallback: tracked tasks (image_generation, etc.)
        cancelled = tq.track_cancel(task_id)

    if not cancelled:
        # Queued handler tasks have their own persistent cancellation state.
        cancelled = tq.cancel_task(task_id)

    if cancelled:
        return {"status": "cancelled", "task_id": task_id}
    return {"status": "not_found", "task_id": task_id,
            "message": "Task not found"}


@router.post("/force-resume")
async def force_resume_queues() -> Dict[str, Any]:
    """Forces every paused provider queue to resume.

    Clears chat registrations that keep background tasks from running. The
    bookkeeping belongs to the ProviderQueue: it hands back the cache lane
    and the serialize gate, in that order. Clearing ``_chat_tasks`` from
    here instead left both occupied for good (LLM-2).
    """
    import asyncio
    from app.core.provider_manager import get_provider_manager

    pm = get_provider_manager()
    # Releasing takes each queue's lock — keep it off the event loop.
    resumed = await asyncio.to_thread(pm.force_resume_all_chats)

    if resumed:
        return {"status": "resumed", "cleared": resumed}
    return {"status": "ok", "message": "Keine pausierten Queues gefunden"}


# ---------------------------------------------------------------------------
# Background Task Queue (persistent SQLite-backed)
# ---------------------------------------------------------------------------

@router.get("/tasks/status")
def task_queue_status() -> Dict[str, Any]:
    """The status of every persistent task queue."""
    from app.core.task_queue import get_task_queue
    return get_task_queue().get_status()


@router.post("/tasks/item/{task_id}/retry")
def retry_bg_task(task_id: str) -> Dict[str, Any]:
    """Put a failed task back to 'pending'."""
    from app.core.task_queue import get_task_queue
    ok = get_task_queue().retry_task(task_id)
    if ok:
        return {"status": "retrying", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Task nicht gefunden oder nicht failed/cancelled")


@router.delete("/tasks/clear")
def clear_bg_tasks(hours: float = 24.0, status: str = "",
                   queue_name: str = "") -> Dict[str, Any]:
    """Delete old finished tasks; ``status`` narrows it to one finished status."""
    from app.core.task_queue import get_task_queue
    deleted = get_task_queue().clear_completed(older_than_hours=hours, queue_name=queue_name,
                                                   status=status)
    return {"status": "ok", "deleted": deleted}


@router.post("/story-arc/generate", dependencies=[Depends(require_admin)])
def trigger_story_arc_generate() -> Dict[str, Any]:
    """Trigger a story arc generation by hand."""
    from app.core.task_queue import get_task_queue
    get_task_queue().submit("story_arc_generate", {"user_id": ""})
    return {"status": "submitted", "user_id": ""}


@router.delete("/story-arc/{arc_id}", dependencies=[Depends(require_admin)])
def delete_story_arc(arc_id: str) -> Dict[str, Any]:
    """Delete one story arc."""
    from app.models.story_arcs import remove_arc
    success = remove_arc(arc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Arc nicht gefunden")
    return {"status": "deleted", "arc_id": arc_id}


@router.get("/story-arc/status", dependencies=[Depends(require_admin)])
def story_arc_status() -> Dict[str, Any]:
    """All story arcs of a user."""
    from app.models.story_arcs import get_all_arcs
    arcs = get_all_arcs()
    active = [a for a in arcs if a.get("status") == "active"]
    resolved = [a for a in arcs if a.get("status") == "resolved"]
    return {
        "total": len(arcs),
        "active": len(active),
        "resolved": len(resolved),
        "arcs": arcs,
    }
