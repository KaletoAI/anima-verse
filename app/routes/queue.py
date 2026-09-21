"""Queue status endpoint — shows all running and recent tasks."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth_dependency import require_admin

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/status")
async def queue_status() -> Dict[str, Any]:
    """Gibt den kombinierten Status aller Task-Quellen zurueck.

    Zusammenfuehrung von:
    - Provider Queues (per-Provider LLM-Calls, Chat-Streaming)
    - TaskQueue (persistente Background-Tasks + tracked GPU/TTS/Image Tasks)
    """
    import asyncio
    from app.core.provider_manager import get_provider_manager
    from app.core.task_queue import get_task_queue

    pm = get_provider_manager()
    # get_combined_status() takes per-channel locks — run in the threadpool
    # so a contended lock never blocks the event loop.
    combined = await asyncio.to_thread(pm.get_combined_status)
    tq = get_task_queue()
    # Same reason: get_status() and get_tracked_recent() query task_queue.db.
    # This route is POLLED by the queue panel, so the SQLite reads were a
    # recurring loop stall (event-loop watchdog, 2026-08-23).
    tq_status = await asyncio.to_thread(tq.get_status)

    # Active tracked tasks (running ODER pending) — Image-Gen, TTS, GPU-Tasks
    # die ausserhalb der TaskQueue laufen aber im Panel sichtbar sein sollen.
    # status explizit setzen — die running/pending-Queries selektieren die
    # status-Spalte nicht, sonst kaeme im Frontend nie "running" an.
    _active = []
    for t in tq_status.get("running", []) or []:
        if t.get("task_origin") == "tracked":
            _active.append({**t, "status": "running"})
    for t in tq_status.get("pending", []) or []:
        if t.get("task_origin") == "tracked":
            _active.append({**t, "status": "pending"})

    return {
        # Per-Channel Queues (each GPU = own channel with tasks)
        "providers": combined.get("providers", {}),
        # Flat fields (still used by UI)
        "chat_active": combined["chat_active"],
        "recent": combined["recent"],
        # Tracked + background tasks (unified)
        "active_tasks": _active,
        "recent_tasks": await asyncio.to_thread(tq.get_tracked_recent),
        # Background tasks (flat, no named queues)
        "bg_tasks": tq_status,
    }


@router.delete("/tasks/{task_id}")
def cancel_task(task_id: str) -> Dict[str, Any]:
    """Bricht einen wartenden oder laufenden Task in der Queue ab."""
    from app.core.provider_manager import get_provider_manager
    from app.core.task_queue import get_task_queue

    pm = get_provider_manager()
    cancelled = pm.cancel_task(task_id)

    if not cancelled:
        # Fallback: Tracked tasks (image_generation, etc.)
        cancelled = get_task_queue().track_cancel(task_id)

    if cancelled:
        return {"status": "cancelled", "task_id": task_id}
    return {"status": "not_found", "task_id": task_id,
            "message": "Task nicht gefunden"}


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
    """Gibt Status aller persistenten Task-Queues zurück."""
    from app.core.task_queue import get_task_queue
    return get_task_queue().get_status()


@router.post("/tasks/item/{task_id}/retry")
def retry_bg_task(task_id: str) -> Dict[str, Any]:
    """Setzt einen fehlgeschlagenen Task auf 'pending' zurück."""
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
    """Triggert manuell eine Story-Arc-Generierung."""
    from app.core.task_queue import get_task_queue
    get_task_queue().submit("story_arc_generate", {"user_id": ""})
    return {"status": "submitted", "user_id": ""}


@router.delete("/story-arc/{arc_id}", dependencies=[Depends(require_admin)])
def delete_story_arc(arc_id: str) -> Dict[str, Any]:
    """Löscht einen einzelnen Story Arc."""
    from app.models.story_arcs import remove_arc
    success = remove_arc(arc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Arc nicht gefunden")
    return {"status": "deleted", "arc_id": arc_id}


@router.get("/story-arc/status", dependencies=[Depends(require_admin)])
def story_arc_status() -> Dict[str, Any]:
    """Zeigt alle Story Arcs eines Users."""
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
