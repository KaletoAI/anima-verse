"""Observer / Szenen-Monitor — read-only Gott-Sicht auf den Wahrnehmungs-Stream.

plan-room-conversation Phase 1. Admin-only Debug-Werkzeug (lebt als Tab im
Game-Admin), bewusst getrennt von der spaeteren in-world Player-UI:

- **objektive Raum-Sicht** — rohe ``utterances`` inkl. gefluestertem Inhalt
  (Gott-Sicht darf alles sehen).
- **subjektive Character-Sicht** — ``perceptions`` eines Characters; Fluester-
  Inhalt fuer Dritte ist hier ausgeblendet (kommt aus der DB schon gefiltert).
- **Inject** — manueller Sprechakt zum Testen der Hoerweite OHNE LLM.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth_dependency import require_admin
from app.core.perception import VOLUME_NORMAL, record_utterance
from app.models import perception_store

router = APIRouter(prefix="/admin/observer", tags=["observer"],
                   dependencies=[Depends(require_admin)])


@router.get("/presence")
async def presence():
    """Alle Locations/Raeume mit den aktuell anwesenden Characters."""
    from app.core.room_entry import _list_characters_in_room
    from app.models.world import list_locations

    out = []
    for loc in list_locations():
        lid = loc.get("id", "")
        all_in_loc = _list_characters_in_room(lid, "")
        seen = set()
        rooms_out = []
        for r in (loc.get("rooms") or []):
            rid = r.get("id", "")
            present = _list_characters_in_room(lid, rid)
            seen.update(present)
            rooms_out.append({"room_id": rid, "name": r.get("name", ""),
                              "present": present})
        no_room = [c for c in all_in_loc if c not in seen]
        out.append({"location_id": lid, "name": loc.get("name", ""),
                    "rooms": rooms_out, "present_no_room": no_room})
    return {"locations": out}


@router.get("/room")
async def room_view(location_id: str, room_id: str = "", limit: int = 100):
    """Objektive Sicht: rohe Sprechakte eines Raums (ganze Location bei leerem
    room_id), aelteste zuerst."""
    rows = perception_store.get_room_utterances(location_id, room_id, limit)
    return {"location_id": location_id, "room_id": room_id, "utterances": rows}


@router.get("/character/{name}/stream")
async def character_stream(name: str, limit: int = 100, before: str = ""):
    """Subjektive Sicht: der Wahrnehmungs-Stream eines Characters."""
    rows = perception_store.get_character_stream(name, limit, before or None)
    return {"perceiver": name, "perceptions": rows}


@router.post("/inject")
async def inject(request: Request):
    """Manueller Sprechakt — testet Hoerweite/Verteilung ohne LLM.

    Body: ``{speaker, content, volume?, addressees?, location_id?, room_id?}``.
    Leeres location_id/room_id -> aktueller State des Sprechers.
    """
    body = await request.json()
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
