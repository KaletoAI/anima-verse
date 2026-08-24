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
    """All temporary NPCs with the fields the admin list shows."""
    from app.core.npc_ops import list_npcs
    return {"npcs": list_npcs()}


@router.post("/sweep")
async def sweep_route() -> Dict[str, Any]:
    """Run the TTL sweep now (the periodic job does the same hourly)."""
    import asyncio
    from app.core.npc_ops import sweep_expired_npcs
    removed = await asyncio.to_thread(sweep_expired_npcs)
    return {"removed": removed}


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
