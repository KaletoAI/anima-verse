"""Hoerweite-Aufloesung + Verteilung fuer den Wahrnehmungs-Stream.

plan-room-conversation Phase 1.

``compute_earshot`` ist REIN (keine DB) — pro Sprechakt liefert sie, wer ihn wie
wahrnimmt. ``record_utterance`` loest die Praesenz JETZT auf (Hoerweite beim
Schreiben), ruft ``compute_earshot`` und schreibt ueber ``perception_store``.

Lautstaerke = Reichweite:
  whisper  — 1 Ziel (Inhalt) + restlicher Raum (nur Meta-Tatsache, kein Inhalt)
  normal   — der ganze Raum (Inhalt)
  shout    — der Raum (Inhalt) + alle anderen Raeume der Location (Inhalt, fern)

Der Sprecher bekommt immer eine Selbst-Wahrnehmung, damit sein eigener Stream
enthaelt, was er gesagt hat.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("perception")

VOLUME_WHISPER = "whisper"
VOLUME_NORMAL = "normal"
VOLUME_SHOUT = "shout"
_VALID_VOLUMES = {VOLUME_WHISPER, VOLUME_NORMAL, VOLUME_SHOUT}

KIND_SPOKEN_SELF = "spoken_self"
KIND_IN_ROOM = "in_room"
KIND_WHISPER_META = "whisper_meta"
KIND_DISTANT_SHOUT = "distant_shout"


@dataclass(frozen=True)
class EarshotTarget:
    """Ein Wahrnehmender eines Sprechakts.

    ``gets_content`` = False bedeutet: nur die Meta-Tatsache wahrnehmbar
    (Fluestern an Dritte) — kein Inhalt.
    """
    perceiver: str
    kind: str
    gets_content: bool


def compute_earshot(*, speaker: str, volume: str,
                    addressees: Sequence[str],
                    room_members: Sequence[str],
                    location_others: Sequence[str]) -> List[EarshotTarget]:
    """Wer nimmt einen Sprechakt wie wahr? REIN — keine DB.

    Args:
        speaker:          Name des Sprechers.
        volume:           whisper | normal | shout (Unbekanntes -> normal).
        addressees:       direkt Angesprochene (nur fuer whisper relevant).
        room_members:     Namen im selben Raum (Sprecher darf drin sein).
        location_others:  Namen in ANDEREN Raeumen derselben Location.
    """
    vol = volume if volume in _VALID_VOLUMES else VOLUME_NORMAL
    addr = {a for a in (addressees or [])}

    targets: List[EarshotTarget] = [EarshotTarget(speaker, KIND_SPOKEN_SELF, True)]
    seen = {speaker}

    def add(name: str, kind: str, gets_content: bool) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        targets.append(EarshotTarget(name, kind, gets_content))

    for m in room_members:
        if vol == VOLUME_WHISPER:
            if m in addr:
                add(m, KIND_IN_ROOM, True)
            else:
                add(m, KIND_WHISPER_META, False)
        else:  # normal + shout: der Raum hoert den vollen Inhalt
            add(m, KIND_IN_ROOM, True)

    if vol == VOLUME_SHOUT:
        for m in location_others:
            add(m, KIND_DISTANT_SHOUT, True)
    # whisper/normal: andere Raeume hoeren nichts

    return targets


def _resolve_presence(location_id: str, room_id: str) -> Tuple[List[str], List[str]]:
    """Raum-Mitglieder + Mitglieder anderer Raeume derselben Location.

    Delegiert an die bestehende Hoerweite-Primitive aus ``room_entry``.
    """
    from app.core.room_entry import _list_characters_in_room
    if not location_id:
        return [], []
    if room_id:
        room_members = _list_characters_in_room(location_id, room_id)
    else:
        room_members = _list_characters_in_room(location_id, "")
    all_in_loc = _list_characters_in_room(location_id, "")
    rm = set(room_members)
    location_others = [c for c in all_in_loc if c not in rm]
    return room_members, location_others


def announce_action(character_name: str, text: str,
                    source: str = "direct_action",
                    perception_meta: Optional[Dict[str, Any]] = None,
                    react: bool = True) -> None:
    """UNIFIED flow for DIRECT (UI-triggered) actions — outfit change, scene
    photo, and whatever comes next. Same pattern the spell path uses in
    /play/say (user directive 2026-07-07: one mechanism, not per-feature
    rebuilds):

    1. Narrator line into the room stream (world-visible perception).
    2. Room reactions via the agent loop (present characters get a chime
       opportunity and may react — or SKIP).

    Location/room come from the acting character ("Erzähler" has no own
    position). Best-effort — never raises into the calling route."""
    try:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        loc = get_character_current_location(character_name) or ""
        room = get_character_current_room(character_name) or ""
        if not loc:
            return
        record_utterance(speaker="Erzähler", content=text,
                         volume=VOLUME_NORMAL, location_id=loc,
                         room_id=room, source=source,
                         perception_meta=perception_meta)
        if not react:
            return
        try:
            from app.core.agent_loop import get_agent_loop
            from app.models.account import is_player_controlled
            get_agent_loop().dispatch_room_reactions(
                speaker=character_name, content=text,
                volume=VOLUME_NORMAL, location_id=loc, room_id=room,
                addressees=[],
                is_avatar=bool(is_player_controlled(character_name)))
        except Exception as e:
            logger.debug("announce_action reactions failed for %s: %s",
                         character_name, e)
    except Exception as e:
        logger.debug("announce_action failed for %s: %s", character_name, e)


def record_utterance(*, speaker: str, content: str,
                     volume: str = VOLUME_NORMAL,
                     addressees: Optional[Sequence[str]] = None,
                     location_id: Optional[str] = None,
                     room_id: Optional[str] = None,
                     source: str = "",
                     ts: Optional[str] = None,
                     dedupe: bool = False,
                     perception_meta: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Zeichnet einen Sprechakt auf + verteilt die Wahrnehmungen (Fan-Out).

    Praesenz wird JETZT aufgeloest. Gibt die utterance-id zurueck — oder None bei
    Fehler. Aufrufer (z.B. Shadow-Write) duerfen dadurch nie brechen.

    location_id/room_id default = aktueller State des Sprechers.
    dedupe=True ueberspringt, wenn (speaker, ts, content) schon existiert
    (Shadow: dieselbe Nachricht kann in mehreren Historien landen).
    """
    from app.core.timeutils import utc_now_iso
    from app.models import perception_store

    if not speaker:
        return None

    stamp = ts or utc_now_iso()
    addr = list(addressees or [])
    vol = volume if volume in _VALID_VOLUMES else VOLUME_NORMAL

    if dedupe:
        try:
            if perception_store.utterance_exists(speaker, stamp, content):
                return None
        except Exception:
            pass  # Dedup ist best-effort, nie blockierend

    loc = location_id
    room = room_id
    if loc is None or room is None:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        if loc is None:
            loc = get_character_current_location(speaker) or ""
        if room is None:
            room = get_character_current_room(speaker) or ""

    try:
        room_members, location_others = _resolve_presence(loc, room)
        targets = compute_earshot(speaker=speaker, volume=vol, addressees=addr,
                                  room_members=room_members,
                                  location_others=location_others)

        # Utterance-Meta: source + optionale Marker (z.B. event_verdict/reason),
        # damit auch die objektive Beobachter-Sicht (liest utterances) sie sieht.
        _umeta: Dict[str, Any] = {}
        if source:
            _umeta["source"] = source
        if perception_meta:
            _umeta.update(perception_meta)
        uid = perception_store.insert_utterance(
            ts=stamp, speaker=speaker, location_id=loc, room_id=room,
            volume=vol, addressees=addr, content=content, meta=_umeta)

        rows = []
        for t in targets:
            # Sprecher + Adressaten sind NICHT geheim (man hoert/sieht, wer
            # spricht und wen er anspricht). Geheim ist nur der Inhalt — der
            # ist bei whisper_meta leer. So kann die subjektive Sicht "X sagt:
            # …" rendern, ohne dass je Fluester-Inhalt durchsickert.
            pmeta = {"speaker": speaker}
            if addr:
                pmeta["addressees"] = addr
            if perception_meta:
                pmeta.update(perception_meta)
            rows.append({
                "perceiver": t.perceiver,
                "ts": stamp,
                "kind": t.kind,
                "content": content if t.gets_content else "",
                "meta": pmeta,
            })
        perception_store.insert_perceptions(uid, rows)
        # Szene des Raums öffnen/touchen (§7) — best-effort, nie blockierend.
        try:
            from app.core import scene_manager
            scene_manager.touch(loc, room, speaker, stamp)
        except Exception as _se:
            logger.debug("scene touch failed: %s", _se)
        return uid
    except Exception as e:
        logger.error("record_utterance failed (speaker=%s, loc=%s, room=%s): %s",
                     speaker, loc, room, e)
        return None
