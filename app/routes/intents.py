"""Intents routes — CRUD API for unified plans & tasks.

Replaces the old /assignments routes: human-set tasks and a character's own
plans now live in one store (see
development_instructions/plan-intents-unified.md).
"""
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict, List, Optional

from app.core.game_time import GameDuration
from app.core.log import get_logger
from app.core.timeutils import game_time
from app.models.intents import (
    create_intent, get_intent, list_intents, update_intent,
    delete_intent, cancel_intent, complete_intent, add_progress,
    apply_trigger_on_create)

logger = get_logger("intents_route")

router = APIRouter(prefix="/intents", tags=["intents"])


@router.get("")
def list_route(owner: Optional[str] = None, status: Optional[str] = None,
               source: Optional[str] = None) -> List[Dict[str, Any]]:
    """List intents, optionally filtered by owner, status and/or source."""
    return list_intents(owner=owner or "", status=status or "",
                        source=source or "")


@router.get("/{intent_id}")
def get_route(intent_id: str) -> Dict[str, Any]:
    it = get_intent(intent_id)
    if not it:
        raise HTTPException(status_code=404, detail="Intent not found")
    return it


@router.post("")
async def create_route(request: Request) -> Dict[str, Any]:
    """Create an intent.

    Body: {title, description?, owner?, participants?, source?, trigger?,
           priority?, location_id?, outfit_hint?, target_count?,
           expires_at? | duration_minutes?}

    If no explicit trigger is given but a location_id is, the intent fires
    on entering that location; otherwise it is a standing intent.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_create_route_sync, data)


def _create_route_sync(data: Any) -> Dict[str, Any]:
    """The blocking body of ``create_route`` — runs in the threadpool."""
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    participants = data.get("participants") or {}
    owner = (data.get("owner") or "").strip()
    if not owner and isinstance(participants, dict) and participants:
        owner = next(iter(participants), "")
    if owner and not participants:
        participants = {owner: {"role": "", "progress": []}}

    location_id = (data.get("location_id") or "").strip()
    trigger = data.get("trigger")
    if not isinstance(trigger, dict):
        trigger = ({"kind": "at_location", "location_id": location_id}
                   if location_id else {"kind": "standing"})

    # An intent's deadline is a WORLD deadline ("finish this within two
    # hours" means two in-world hours), so it is a canonical GameTime — the
    # same shape intent_engine._schedule_intent and the migration produce.
    expires_at = (data.get("expires_at") or "").strip()
    dur = data.get("duration_minutes")
    if not expires_at and dur:
        try:
            expires_at = (game_time()
                          + GameDuration.of(minutes=int(dur))).canonical()
        except Exception:
            expires_at = ""

    it = create_intent(
        owner=owner, title=title,
        description=(data.get("description") or "").strip(),
        source=data.get("source", "human"),
        participants=participants if isinstance(participants, dict) else {},
        trigger=trigger,
        priority=data.get("priority", 3),
        location_id=location_id,
        outfit_hint=(data.get("outfit_hint") or "").strip(),
        target_count=data.get("target_count", 0),
        expires_at=expires_at)
    apply_trigger_on_create(it)
    return it


@router.patch("/{intent_id}")
async def patch_route(intent_id: str, request: Request) -> Dict[str, Any]:
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_patch_route_sync, intent_id, data)


def _patch_route_sync(intent_id: str, data: Any) -> Dict[str, Any]:
    """The blocking body of ``patch_route`` — runs in the threadpool."""
    result = update_intent(intent_id, **data)
    if not result:
        raise HTTPException(status_code=404, detail="Intent not found")
    return result


@router.delete("/{intent_id}")
def delete_route(intent_id: str) -> Dict[str, str]:
    if not delete_intent(intent_id):
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"status": "deleted"}


@router.post("/{intent_id}/cancel")
def cancel_route(intent_id: str) -> Dict[str, str]:
    if not cancel_intent(intent_id):
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"status": "cancelled"}


@router.post("/{intent_id}/complete")
def complete_route(intent_id: str) -> Dict[str, str]:
    if not complete_intent(intent_id):
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"status": "done"}


@router.post("/{intent_id}/progress")
async def progress_route(intent_id: str, request: Request) -> Dict[str, Any]:
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_progress_route_sync, intent_id, data)


def _progress_route_sync(intent_id: str, data: Any) -> Dict[str, Any]:
    """The blocking body of ``progress_route`` — runs in the threadpool."""
    character = (data.get("character") or "").strip()
    note = (data.get("note") or "").strip()
    if not character or not note:
        raise HTTPException(status_code=400,
                            detail="character and note are required")
    result = add_progress(intent_id, character, note)
    if not result:
        raise HTTPException(status_code=404,
                            detail="Intent or character not found")
    return result
