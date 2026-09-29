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
    delete_intent, complete_intent, apply_trigger_on_create)

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


#: Upper bound for relative game-time inputs: ten game years of 365 days.
_MAX_GAME_MINUTES = 5_256_000


def _game_stamp_in(minutes: Any, field: str) -> str:
    """Canonical GAME stamp ``minutes`` in-world minutes from now.

    ``""`` when the field was not sent (None / empty). Anything else must be a
    whole number of game minutes in ``1.._MAX_GAME_MINUTES`` — a 400 otherwise,
    so a typo never silently drops the value or lands a stamp centuries away.
    """
    if minutes is None or minutes == "":
        return ""
    if isinstance(minutes, bool):
        mins = None
    elif isinstance(minutes, int):
        mins = minutes
    elif isinstance(minutes, str) and minutes.strip().isdigit():
        mins = int(minutes.strip())
    else:
        mins = None
    if mins is None or not 1 <= mins <= _MAX_GAME_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be a whole number of game minutes "
                   f"(1..{_MAX_GAME_MINUTES})")
    return (game_time() + GameDuration.of(minutes=mins)).canonical()


def _apply_game_time_fields(data: Dict[str, Any]) -> None:
    """Turn the relative inputs of the admin form into GAME-time stamps, in place.

    ``duration_minutes`` -> ``expires_at``; ``trigger.run_in_minutes`` (at_time)
    -> ``trigger.run_date``. The server computes both on the game clock — a
    client has no game clock and must never send a system timestamp for them.
    """
    stamp = _game_stamp_in(data.pop("duration_minutes", None), "duration_minutes")
    if stamp:
        data["expires_at"] = stamp
    trig = data.get("trigger")
    if isinstance(trig, dict) and "run_in_minutes" in trig:
        trig = dict(trig)
        run = _game_stamp_in(trig.pop("run_in_minutes"), "run_in_minutes")
        if run:
            trig["run_date"] = run
        data["trigger"] = trig


@router.post("")
async def create_route(request: Request) -> Dict[str, Any]:
    """Create an intent.

    Body: {title, description?, owner?, participants?, source?, trigger?,
           priority?, location_id?, outfit_hint?, target_count?,
           expires_at? | duration_minutes?}

    ``duration_minutes`` and an at_time trigger's ``run_in_minutes`` are
    in-world minutes from now; the server turns them into GAME stamps.
    If no explicit trigger is given but a location_id is, the intent fires
    on entering that location; otherwise it is a standing intent.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_create_route_sync, data)


def _create_route_sync(data: Any) -> Dict[str, Any]:
    """The blocking body of ``create_route`` — runs in the threadpool."""
    # An intent's deadline is a WORLD deadline ("finish this within two
    # hours" means two in-world hours), so it is a canonical GameTime — the
    # same shape intent_engine._schedule_intent and the migration produce.
    _apply_game_time_fields(data)
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

    if trigger.get("kind") == "at_time" and not trigger.get("run_date"):
        raise HTTPException(status_code=400, detail="an at_time trigger needs run_in_minutes")
    expires_at = (data.get("expires_at") or "").strip()

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
    """The blocking body of ``patch_route`` — runs in the threadpool.

    Accepts the same relative ``duration_minutes`` / ``trigger.run_in_minutes``
    as the create route; without them the stored stamps stay as they are.
    """
    if isinstance(data, dict):
        _apply_game_time_fields(data)
    result = update_intent(intent_id, **data)
    if not result:
        raise HTTPException(status_code=404, detail="Intent not found")
    return result


@router.delete("/{intent_id}")
def delete_route(intent_id: str) -> Dict[str, str]:
    if not delete_intent(intent_id):
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"status": "deleted"}


@router.post("/{intent_id}/complete")
def complete_route(intent_id: str) -> Dict[str, str]:
    if not complete_intent(intent_id):
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"status": "done"}
