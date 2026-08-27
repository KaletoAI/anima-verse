"""Admin routes for the improvements queue.

A thin HTTP adapter: parsing, status codes, and the shape the Game-Admin tab
consumes.  Every decision lives in ``app/core/improvements`` — the engine owns
the gates and the order, the store owns the rows, the registry owns the types.
This module never names an improvement type.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth_dependency import require_admin
from app.core.improvements import engine, registry, store
from app.core.log import get_logger
from app.core.task_queue import get_task_queue

logger = get_logger("improvements.route")

router = APIRouter(prefix="/improvements", tags=["improvements"],
                   dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------

class CreateBody(BaseModel):
    type_id: str
    label: str = ""
    mode: str = "one_shot"
    params: Dict[str, Any] = {}


class PreviewBody(BaseModel):
    type_id: str
    params: Dict[str, Any] = {}


class PatchBody(BaseModel):
    label: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    mode: Optional[str] = None


class OrderBody(BaseModel):
    ids: List[str]


class SettingsBody(BaseModel):
    enabled: bool
    idle_minutes: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _improvement_or_404(improvement_id: str) -> Dict[str, Any]:
    improvement = store.get(improvement_id)
    if improvement is None:
        raise HTTPException(404, f"improvement '{improvement_id}' not found")
    return improvement


def _type_or_400(type_id: str):
    improvement_type = registry.get(type_id)
    if improvement_type is None:
        raise HTTPException(400, f"unknown improvement type '{type_id}'")
    return improvement_type


def _validated(type_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalised params, or 400 with the type's own message — that string is
    what the tab shows the user, so it is passed through unchanged."""
    try:
        return _type_or_400(type_id).validate(params or {})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _cancel_in_flight(improvement_id: str) -> None:
    """Cancel the queue task(s) of a step this entry has in flight.

    Ownership is decided by the task's own payload, never by "there is only one
    improvement_step owed": a foreign entry's task must survive this delete.
    ``list_tasks_of_type`` is used rather than ``get_status``, whose pending
    list is the admin panel's top-50 window ordered by priority — improvement
    steps run at the very back (STEP_PRIORITY 90), so under load the task to
    cancel is exactly the one that window drops.
    """
    task_queue = get_task_queue()
    for row in task_queue.list_tasks_of_type(engine.TASK_TYPE):
        if (row["payload"] or {}).get("improvement_id") != improvement_id:
            continue
        task_queue.cancel_task(row["task_id"])
        logger.info("improvements: cancelled task %s of deleted entry %s",
                    row["task_id"], improvement_id)


# ---------------------------------------------------------------------------
# Types + entries
# ---------------------------------------------------------------------------

@router.get("/types")
def list_types() -> List[Dict[str, Any]]:
    return [{"id": t.id, "label": t.label,
             "params_schema": [f.to_dict() for f in t.params_schema]}
            for t in registry.list_types()]


@router.get("")
def list_improvements() -> List[Dict[str, Any]]:
    return store.list_all()


@router.post("")
def create_improvement(body: CreateBody) -> Dict[str, Any]:
    """Create and scan in one go — an entry that showed 0/0 until the next tick
    would look broken."""
    params = _validated(body.type_id, body.params)
    improvement = store.create(body.type_id, body.label, params, body.mode)
    engine.scan(improvement["id"])
    return store.get(improvement["id"]) or improvement


@router.post("/preview")
def preview(body: PreviewBody) -> Dict[str, Any]:
    """What the type would work on with these params — asked before creating."""
    params = _validated(body.type_id, body.params)
    candidates = _type_or_400(body.type_id).find_candidates(params)
    return {"count": len(candidates),
            "sample": [c.label for c in candidates[:20]]}


@router.patch("/order")
def reorder(body: OrderBody) -> Dict[str, Any]:
    store.set_order(body.ids)
    return {"ok": True}


@router.get("/queue")
def queue() -> Dict[str, Any]:
    return {"queue": engine.ordered_queue(), "recent": store.recent_done(20)}


@router.get("/status")
def engine_status() -> Dict[str, Any]:
    return engine.status()


@router.put("/settings")
def put_settings(body: SettingsBody) -> Dict[str, Any]:
    """Answers with what was STORED — idle_minutes is clamped, and the tab must
    show the value that is really in effect."""
    store.set_settings(body.enabled, body.idle_minutes)
    return store.get_settings()


@router.patch("/{improvement_id}")
def patch_improvement(improvement_id: str, body: PatchBody) -> Dict[str, Any]:
    improvement = _improvement_or_404(improvement_id)
    fields: Dict[str, Any] = {}
    if body.label is not None:
        fields["label"] = body.label
    if body.mode is not None:
        fields["mode"] = body.mode
    rescan = body.params is not None
    if rescan:
        fields["params"] = _validated(improvement["type_id"], body.params)
    if fields:
        store.update(improvement_id, **fields)
    if rescan:
        # New parameters mean a different subject list — the steps would
        # otherwise still be the old query's.
        engine.scan(improvement_id)
    return store.get(improvement_id) or improvement


@router.delete("/{improvement_id}")
def delete_improvement(improvement_id: str) -> Dict[str, Any]:
    _improvement_or_404(improvement_id)
    _cancel_in_flight(improvement_id)
    store.delete(improvement_id)
    return {"ok": True}


@router.post("/{improvement_id}/pause")
def pause(improvement_id: str) -> Dict[str, Any]:
    _improvement_or_404(improvement_id)
    store.update(improvement_id, status="paused")
    return store.get(improvement_id) or {}


@router.post("/{improvement_id}/resume")
def resume(improvement_id: str) -> Dict[str, Any]:
    _improvement_or_404(improvement_id)
    store.update(improvement_id, status="open")
    return store.get(improvement_id) or {}


@router.post("/{improvement_id}/run-now")
def run_now(improvement_id: str) -> Dict[str, Any]:
    _improvement_or_404(improvement_id)
    engine.request_run_now(improvement_id)
    return {"ok": True}


@router.post("/{improvement_id}/rescan")
def rescan(improvement_id: str) -> Dict[str, int]:
    _improvement_or_404(improvement_id)
    return engine.scan(improvement_id)


@router.get("/{improvement_id}/steps")
def list_steps(improvement_id: str) -> List[Dict[str, Any]]:
    _improvement_or_404(improvement_id)
    return store.list_steps(improvement_id)


@router.post("/{improvement_id}/steps/{candidate_key}/retry")
def retry_step(improvement_id: str, candidate_key: str) -> Dict[str, Any]:
    _improvement_or_404(improvement_id)
    store.retry_step(improvement_id, candidate_key)
    return {"ok": True}
