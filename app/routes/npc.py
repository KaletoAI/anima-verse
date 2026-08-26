"""Temporary-NPC endpoints for the Game-Admin Characters tab.

Thin HTTP adapter — every decision lives in ``app.core.npc_ops``. Deleting an
NPC deliberately has NO endpoint of its own: ``DELETE /characters/{name}`` runs
``delete_character``, which already sweeps the NPC's own rows AND (because its
template marks it temporary) what other characters remembered about it.
"""
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.auth_dependency import require_admin
from app.core.log import get_logger

router = APIRouter(prefix="/npc", tags=["npc"],
                   dependencies=[Depends(require_admin)])
logger = get_logger("npc_routes")


@router.get("/list")
def list_npcs_route() -> Dict[str, Any]:
    """Temporary NPCs — the living ones, plus the recycling pool.

    Pooled NPCs are out of every roster (``list_available_characters``), so
    this endpoint is the ONE place the admin can see them at all. Deleting one
    for good is the ordinary ``DELETE /characters/{name}``.
    """
    from app.core.npc_ops import list_npcs
    from app.core.npc_pool import list_pool, max_pool_size
    from app.core.npc_spawn import alive_npc_count, max_alive, wanderer_quota
    return {"npcs": list_npcs(), "pooled": list_pool(),
            "limits": {"alive": alive_npc_count(), "max_alive": max_alive(),
                       "wanderer_quota": wanderer_quota(),
                       "pool_size": max_pool_size()}}


@router.post("/sweep")
async def sweep_route() -> Dict[str, Any]:
    """Run the TTL sweep now (the periodic job does the same hourly).

    "Removed" means moved to the pool since plan-npc-auto-spawn.md § 3 — the
    NPC is out of the world, its profile is kept for the next spawn.
    """
    import asyncio
    from app.core.npc_ops import sweep_expired_npcs
    removed = await asyncio.to_thread(sweep_expired_npcs)
    return {"removed": removed}


@router.post("/{character_name}/pool")
async def pool_npc_route(character_name: str) -> Dict[str, Any]:
    """Retire a living temporary NPC into the recycling pool by hand."""
    import asyncio
    from app.core.npc_pool import pool_npc
    ok = await asyncio.to_thread(pool_npc, character_name, "admin")
    if not ok:
        raise HTTPException(status_code=404,
                            detail="not a living temporary NPC")
    return {"status": "success", "pooled": character_name}


@router.post("/slots/{location_id}/fill")
def fill_slots_route(location_id: str) -> Dict[str, Any]:
    """Queue the slot check for one location — the editor's "Fill now".

    Submits the very same job the avatar's approach submits, so the manual
    button and the automatic trigger cannot drift apart. It also clears the
    location's cooldown: an admin who presses the button means it.
    """
    from app.core.npc_spawn import reset_cooldowns, submit_spawn_job
    reset_cooldowns()
    task_id = submit_spawn_job(location_id=location_id, reason="slot",
                               triggered_by="admin")
    return {"status": "success", "task_id": task_id,
            "queued": bool(task_id)}


@router.post("/areas/{area_id}/fill")
def fill_area_slots_route(area_id: str) -> Dict[str, Any]:
    """The same "Fill now", for the slots of a painted terrain area (§ E3.2).

    One button, two surfaces: the map editor's area panel authors slots just
    as the location editor does, so it gets the same manual trigger — and the
    same job the avatar's approach submits, so neither can drift from the
    other.
    """
    from app.core.npc_spawn import reset_cooldowns, submit_spawn_job
    reset_cooldowns()
    task_id = submit_spawn_job(area_id=area_id, reason="slot",
                               triggered_by="admin")
    return {"status": "success", "task_id": task_id,
            "queued": bool(task_id)}


@router.post("/generate")
async def generate_npc_route(request: Request):
    """Run the generate → validate → repair → apply pipeline as an SSE stream.

    One ``data:`` frame per stage transition, so the modal can show live
    progress instead of a spinner over a multi-turn LLM run.
    """
    body = await request.json()
    briefing = str(body.get("briefing") or "").strip()
    location_id = str(body.get("location_id") or "").strip()
    room_id = str(body.get("room_id") or "").strip()
    model = str(body.get("model") or "").strip()
    provider = str(body.get("provider") or "").strip()
    validator_model = str(body.get("validator_model") or "").strip()
    validator_provider = str(body.get("validator_provider") or "").strip()

    if not briefing:
        raise HTTPException(status_code=400, detail="briefing required")
    if not location_id:
        raise HTTPException(status_code=400, detail="location_id required")
    if not model:
        raise HTTPException(
            status_code=400,
            detail="model required — pick a model for the NPC generator")

    ttl_hours = body.get("ttl_hours")
    try:
        ttl_hours = float(ttl_hours) if ttl_hours not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="ttl_hours must be a number")

    max_tokens = body.get("max_tokens")
    try:
        max_tokens = int(max_tokens) if max_tokens not in (None, "") else None
    except (TypeError, ValueError):
        max_tokens = None

    created_by = ""
    try:
        created_by = str(getattr(request.state, "username", "") or "")
    except Exception:
        created_by = ""

    async def stream():
        # The queue registration lives inside generate_npc — that is where the
        # provider instance exists, so the right channel gets paused.
        from app.core.npc_ops import generate_npc
        try:
            async for frame in generate_npc(
                    briefing=briefing, location_id=location_id, room_id=room_id,
                    ttl_hours=ttl_hours, model=model, provider=provider,
                    validator_model=validator_model,
                    validator_provider=validator_provider,
                    max_tokens=max_tokens, created_by=created_by):
                yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            logger.error("NPC generate stream error: %s", e)
            yield f"data: {json.dumps({'stage': 'apply', 'error': str(e)})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
