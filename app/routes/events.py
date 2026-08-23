"""Event routes — situational world events + the outfit/state SSE streams."""
import asyncio
import json as _json

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, Any
from app.core.log import get_logger
from app.models.events import (add_event, event_game_label, get_all_events,
                               delete_event)

logger = get_logger("events")

router = APIRouter(prefix="/events", tags=["events"])


def _game_label(stamp: Any, lang: str) -> str:
    """Readable world label of a canonical GAME stamp ("" when there is none).

    The counterpart of :func:`event_game_label` for the other game stamp an
    event carries, its ``expires_at``.
    """
    from app.core.game_time import GameTime
    try:
        return GameTime.parse(stamp or "").label(lang)
    except (ValueError, TypeError):
        return ""


@router.get("/image-stream")
async def event_image_stream(request: Request) -> StreamingResponse:
    """SSE stream announcing when an event background image is ready.

    Payload: ``{"type": "event_image_ready", "event_id": ..., "location_id": ..., "kind": "event"|"resolved"}``.
    Multi-user: filtered by allowed_characters is not relevant here — backgrounds are world-shared.
    Unauthenticated callers are rejected with 401.
    """
    from app.core.event_images import subscribe as _subscribe_images
    from app.core.auth_dependency import get_current_user_optional

    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async def gen():
        yield f"data: {_json.dumps({'type': 'connected'})}\n\n"
        try:
            async for event in _subscribe_images():
                payload = {"type": "event_image_ready", **event}
                yield f"data: {_json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/outfit-stream")
async def outfit_event_stream(request: Request) -> StreamingResponse:
    """SSE stream of outfit-change events.

    Multi-user: filtered by allowed_characters — a user only sees events for
    the characters assigned to them. An admin with allowed=[] sees none (they
    have to assign characters first). Unauthenticated: 401.
    """
    from app.core.outfit_events import subscribe
    from app.core.auth_dependency import get_current_user_optional

    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    allowed = set(user.get("allowed_characters") or [])

    async def gen():
        yield f"data: {_json.dumps({'type': 'connected'})}\n\n"
        try:
            async for event in subscribe():
                char = event.get("character", "")
                if char and char not in allowed:
                    continue
                payload = {"type": "outfit_changed", **event}
                yield f"data: {_json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/state-stream")
async def state_event_stream(request: Request) -> StreamingResponse:
    """SSE stream of typed character-state events (AV3D-3).

    Payloads: ``location_changed {character, from_id, to_id, room_id}``,
    ``room_changed {character, location_id, room_id}``,
    ``activity_changed {character, activity, animation}``. Pushes what
    polling /play/worldmap would discover — the 3D client animates NPC
    movement without the poll jumps; polling stays the baseline.

    Auth like /play/worldmap: any authenticated user, NO per-character
    filter — the worldmap shows all characters, so the stream that mirrors
    it must too (deliberate deviation from the outfit stream).
    Unauthenticated: 401.
    """
    from app.core.state_events import subscribe as _subscribe_state
    from app.core.auth_dependency import get_current_user_optional

    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async def gen():
        yield f"data: {_json.dumps({'type': 'connected'})}\n\n"
        try:
            async for event in _subscribe_state():
                yield f"data: {_json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("")
def list_events_route(lang: str = "en") -> Dict[str, Any]:
    """Lists all active events.

    Every event carries its world stamp (``game_ts``) plus the finished
    ``game_label`` for that stamp — the client renders, it never formats a
    calendar itself. An event without a game stamp gets an empty label.

    ``expires_at`` is a GAME stamp too (an event's TTL is a world duration),
    so it gets the same treatment: ``expires_label`` is the readable form, and
    an event that never expires has neither.
    """
    events = [{**evt, "game_label": event_game_label(evt, lang),
               "expires_label": _game_label(evt.get("expires_at"), lang)}
              for evt in get_all_events()]
    return {"events": events}


@router.post("")
async def create_event_route(request: Request) -> Dict[str, Any]:
    """Creates a new event."""
    body = await request.json()
    return await asyncio.to_thread(_create_event_route_sync, body)


def _create_event_route_sync(body: Any) -> Dict[str, Any]:
    """The blocking body of ``create_event_route`` — runs in the threadpool."""
    text = body.get("text", "").strip()
    location_id = body.get("location_id") or None
    # category: ambient | social | disruption | danger (empty = uncategorized).
    # danger/disruption are highlighted as "Breaking" in the player news.
    category = (body.get("category") or "").strip().lower()

    ttl_hours = body.get("ttl_hours")
    if ttl_hours is not None:
        ttl_hours = int(ttl_hours)

    if not text:
        raise HTTPException(status_code=400, detail="text required")

    event = add_event(text, location_id=location_id, ttl_hours=ttl_hours,
                      category=category)
    return {"ok": True, "event": event}


@router.delete("/{event_id}")
def delete_event_route(
    event_id: str) -> Dict[str, Any]:
    """Deletes an event."""
    deleted = delete_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"ok": True}
