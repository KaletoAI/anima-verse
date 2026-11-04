"""Observer / scene monitor — read-only god view of the perception stream.

plan-room-conversation phase 1. Admin-only debug tool (lives as a tab in
Game-Admin), deliberately separate from the in-world player UI:

- **objective room view** — raw ``utterances`` including whispered content
  and private lines (the god view may see everything; it never feeds a prompt).
- **subjective character view** — one character's ``perceptions``; whispered
  content meant for others is hidden here (already filtered in the DB).
- **Inject** — a manual speech act to test earshot WITHOUT an LLM.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth_dependency import require_admin
from app.core.perception import VOLUME_NORMAL, record_utterance
from app.models import perception_store

router = APIRouter(prefix="/admin/observer", tags=["observer"],
                   dependencies=[Depends(require_admin)])


@router.get("/presence")
def presence():
    """All locations/rooms with the characters currently present."""
    from app.core.room_entry import characters_in_room
    from app.models.world import list_locations

    out = []
    for loc in list_locations():
        lid = loc.get("id", "")
        all_in_loc = characters_in_room(lid, "")
        seen = set()
        rooms_out = []
        for r in (loc.get("rooms") or []):
            rid = r.get("id", "")
            present = characters_in_room(lid, rid)
            seen.update(present)
            rooms_out.append({"room_id": rid, "name": r.get("name", ""),
                              "present": present})
        no_room = [c for c in all_in_loc if c not in seen]
        out.append({"location_id": lid, "name": loc.get("name", ""),
                    "rooms": rooms_out, "present_no_room": no_room})
    return {"locations": out}


@router.get("/room")
def room_view(location_id: str, room_id: str = "", limit: int = 100):
    """Objective view: raw speech acts of a room (the whole location for an
    empty room_id), oldest first."""
    # Admin-only god view, never a prompt: private lines stay visible here.
    rows = perception_store.get_room_utterances(location_id, room_id, limit,
                                                include_private=True)
    return {"location_id": location_id, "room_id": room_id, "utterances": rows}


@router.get("/character/{name}/stream")
def character_stream(name: str, limit: int = 100, before: str = ""):
    """Subjective view: one character's perception stream."""
    rows = perception_store.get_character_stream(name, limit, before or None)
    return {"perceiver": name, "perceptions": rows}


@router.post("/inject")
async def inject(request: Request):
    """Manual speech act — tests earshot/fan-out without an LLM.

    Body: ``{speaker, content, volume?, addressees?, location_id?, room_id?}``.
    Empty location_id/room_id -> the speaker's current state.
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_inject_sync, body)


def _inject_sync(body):
    """The blocking body of ``inject`` — runs in the threadpool."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    speaker = str(body.get("speaker") or "").strip()
    content = str(body.get("content") or "")
    if not speaker or not content.strip():
        raise HTTPException(status_code=400,
                            detail="speaker and content are required")

    addressees = body.get("addressees") or []
    if not isinstance(addressees, list):
        raise HTTPException(status_code=400, detail="addressees must be a list")

    uid = record_utterance(
        speaker=speaker,
        content=content,
        volume=str(body.get("volume") or VOLUME_NORMAL).strip(),
        addressees=[str(a) for a in addressees],
        location_id=(body.get("location_id") or None),
        room_id=(body.get("room_id") or None),
        source="inject",
    )
    if uid is None:
        raise HTTPException(status_code=500, detail="record_utterance failed")
    return {"utterance_id": uid}
