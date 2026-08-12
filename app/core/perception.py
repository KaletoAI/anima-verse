"""Earshot resolution + fan-out for the perception stream.

plan-room-conversation phase 1.

``compute_earshot`` is PURE (no DB) — per speech act it says who perceives it
how. ``record_utterance`` resolves the presence NOW (earshot at write time),
calls ``compute_earshot`` and writes through ``perception_store``.

Volume = range, inside a location:
  whisper  — 1 target (content) + the rest of the room (the bare fact, no content)
  normal   — the whole room (content)
  shout    — the room (content) + every other room of the location (content, distant)

Outside every location the walls are gone, so the room rules have nothing to
work on: the wilderness is an invisible room around the speaker with the radius
``game.hearing_radius_m`` (see ``get_hearing_radius_m``). Everyone location-less
inside that circle hears the line (kind ``nearby``); a whisper reaches its
addressee alone — with no room to carry it, there is no bystander line.

The speaker always gets a self-perception so its own stream contains what it
said.
"""
from __future__ import annotations

import math
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
# Heard in the open: no room, no walls — just close enough (E6).
KIND_NEARBY = "nearby"

DEFAULT_HEARING_RADIUS_M = 20.0
_MIN_HEARING_RADIUS_M = 1.0
_MAX_HEARING_RADIUS_M = 500.0

# Canonical speaker value for narrator/storyteller lines (act narration, spell
# results, movement traces, party joins). Persisted AND player-visible, so it is
# one constant referenced everywhere (write + presence filters) — never a bare
# string literal (previously a bare narrator literal). Localised for display via
# t("Storyteller", lang); the stored value stays this canonical English token.
STORYTELLER_SPEAKER = "Storyteller"

# What the PROMPTS call the place of a location-less character. Before E6 the
# prompt builders rendered a bare "Unknown" here, which reads as "we do not
# know where you are" — the opposite of the truth: we know exactly where the
# character stands, it is simply out in the open. English like every other
# prompt string; the character's own language comes from its language
# instruction, not from this label.
WILDERNESS_LOCATION_LABEL = "Wilderness (in the open, no building, no room)"


def get_hearing_radius_m() -> float:
    """How far a spoken line carries in the WILDERNESS, in world metres, from
    the world setting `game.hearing_radius_m`.

    Only the open world uses it — inside a location the walls decide, not a
    distance.

    The boundary between "garbage" and "extreme but meant":
      * missing, non-numeric, bool, NaN/inf, **zero or negative** -> the
        default. Zero counts as garbage on purpose: an emptied admin field
        arrives as 0, and reading that as "nobody ever hears anybody outdoors"
        would silence the wilderness without anyone asking for it.
      * 0 < value < 1 is an absurdly short range but positive and deliberate
        -> clamped up to 1 m; anything above 500 m is clamped down.
    """
    from app.core import config
    raw = config.get("game.hearing_radius_m", DEFAULT_HEARING_RADIUS_M)
    if raw is None:
        return DEFAULT_HEARING_RADIUS_M
    if isinstance(raw, bool):
        return _reject_radius(raw)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _reject_radius(raw)
    if not math.isfinite(value) or value <= 0:
        return _reject_radius(raw)
    return min(max(value, _MIN_HEARING_RADIUS_M), _MAX_HEARING_RADIUS_M)


_radius_warned = False


def _reject_radius(raw: Any) -> float:
    """Log the discarded setting ONCE and return the default — the fallback
    sits on the write path of every spoken line, a warning per line would spam."""
    global _radius_warned
    if not _radius_warned:
        _radius_warned = True
        logger.warning("Unusable game.hearing_radius_m (%r) — using the "
                       "default %.1f m", raw, DEFAULT_HEARING_RADIUS_M)
    return DEFAULT_HEARING_RADIUS_M


@dataclass(frozen=True)
class EarshotTarget:
    """One perceiver of a speech act.

    ``gets_content`` = False means: only the bare fact is perceivable
    (whispering to someone else) — no content.
    """
    perceiver: str
    kind: str
    gets_content: bool


def compute_earshot(*, speaker: str, volume: str,
                    addressees: Sequence[str],
                    room_members: Sequence[str],
                    location_others: Sequence[str],
                    nearby: Sequence[str] = ()) -> List[EarshotTarget]:
    """Who perceives a speech act how? PURE — no DB.

    Args:
        speaker:          name of the speaker.
        volume:           whisper | normal | shout (unknown -> normal).
        addressees:       those spoken to directly (only whisper cares).
        room_members:     names in the same room (the speaker may be among them).
        location_others:  names in OTHER rooms of the same location.
        nearby:           names within the hearing radius in the open — the
                          wilderness case, mutually exclusive with the two
                          room lists (a speaker is either in a location or not).
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
        else:  # normal + shout: the room hears the full content
            add(m, KIND_IN_ROOM, True)

    if vol == VOLUME_SHOUT:
        for m in location_others:
            add(m, KIND_DISTANT_SHOUT, True)
    # whisper/normal: the other rooms hear nothing

    # The open world: everyone inside the radius hears the line in full. A
    # whisper is the exception — without a room there is nobody to notice
    # "they whispered something", so it reaches its addressee alone. There is
    # deliberately no per-volume radius yet (v1): a shout carries exactly as
    # far as normal speech.
    for m in nearby:
        if vol == VOLUME_WHISPER:
            if m in addr:
                add(m, KIND_NEARBY, True)
        else:
            add(m, KIND_NEARBY, True)

    return targets


def _resolve_presence(location_id: str, room_id: str, *, speaker: str = "",
                      speaker_pos: Optional[Dict[str, float]] = None
                      ) -> Tuple[List[str], List[str], List[str]]:
    """Members of the room + members of the other rooms of the same location
    + everyone within hearing radius in the open.

    Exactly one of the two worlds answers: with a location the two room lists
    are filled and ``nearby`` stays empty; without one it is the other way
    round. Delegates to the existing earshot primitive in ``room_entry`` for
    the room case.

    ``speaker``/``speaker_pos`` are only read in the wilderness case — the
    circle needs a centre, and the speaker must not appear in its own
    ``nearby`` list.
    """
    from app.core.room_entry import _list_characters_in_room
    if not location_id:
        return [], [], _nearby_in_the_open(speaker, speaker_pos)
    # No branch on an empty room any more: the ground is a room, so the room
    # query answers for it like for any other. The second call passes ""
    # deliberately — that IS the "everyone in the location" query, and the
    # difference of the two sets is who is within shouting distance.
    room_members = _list_characters_in_room(location_id, room_id)
    all_in_loc = _list_characters_in_room(location_id, "")
    rm = set(room_members)
    location_others = [c for c in all_in_loc if c not in rm]
    return room_members, location_others, []


def _nearby_in_the_open(speaker: str,
                        speaker_pos: Optional[Dict[str, float]]) -> List[str]:
    """Location-less characters within ``get_hearing_radius_m`` of the speaker.

    A speaker without a point has no circle at all — nobody hears it, which is
    the honest answer for a character the map does not place anywhere.
    """
    if not speaker_pos:
        return []
    try:
        sx = float(speaker_pos["x"])
        sz = float(speaker_pos["z"])
    except (KeyError, TypeError, ValueError):
        return []
    radius = get_hearing_radius_m()
    from app.models.character import list_wilderness_positions
    out: List[str] = []
    for entry in list_wilderness_positions():
        name = entry.get("name") or ""
        if not name or name == speaker:
            continue
        if math.hypot(entry["x"] - sx, entry["z"] - sz) <= radius:
            out.append(name)
    return out


def nearby_in_the_open(character_name: str,
                       pos: Optional[Dict[str, float]] = None) -> List[str]:
    """Public earshot roster for a LOCATION-LESS character: everyone else
    without a location within ``get_hearing_radius_m`` metres of them.

    The ONE wilderness-presence computation — the prompt builders, the
    reaction dispatch and TalkTo all ask this instead of each inventing a
    distance rule (the room paths likewise share ``_list_characters_in_room``).
    Empty for a character the map does not place; callers that must tell
    "nobody around" from "we do not know" read the point themselves and pass
    it in, which also saves the second lookup.
    """
    if pos is None:
        from app.models.character import get_character_pos
        pos = get_character_pos(character_name)
    return _nearby_in_the_open(character_name, pos)


def location_display_name(location_id: str) -> str:
    """The place name a PROMPT shows — the location's name, or the wilderness
    label when the character stands outside every location.

    One function for both prompt builders: they used to hardcode the same
    "Unknown" fallback separately, and a wilderness wording fixed in only one
    of them would have drifted immediately."""
    if not location_id:
        return WILDERNESS_LOCATION_LABEL
    from app.models.world import get_location_name
    return get_location_name(location_id)


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

    Location/room come from the acting character (the storyteller has no own
    position). An EMPTY location is the wilderness, not a missing value: the
    action still happened and the people standing around the character still
    react to it, so the old early return here is gone (E6).

    Known v1 gap out there: the narrator speaks from nowhere — it has no
    metre point, so its hearing circle is empty and the recorded line reaches
    no perceiver even though the reaction dispatch below does find the
    neighbours. Giving narration in the open the acting character's point is a
    deliberate open decision, not an oversight.

    Best-effort — never raises into the calling route."""
    try:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        loc = get_character_current_location(character_name) or ""
        room = get_character_current_room(character_name) or ""
        record_utterance(speaker=STORYTELLER_SPEAKER, content=text,
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
    """Records a speech act + distributes the perceptions (fan-out).

    Presence is resolved NOW. Returns the utterance id — or None on error, so
    callers (e.g. the shadow write) can never break because of it.

    location_id/room_id default to the speaker's current state. An empty
    location is not "unknown" but the WILDERNESS: the speaker's metre point
    becomes the centre of its hearing radius and is written onto the utterance.
    dedupe=True skips if (speaker, ts, content) already exists (shadow: the
    same message can land in several histories).
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
            pass  # Dedup is best-effort, never blocking

    loc = location_id
    room = room_id
    if loc is None or room is None:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        if loc is None:
            loc = get_character_current_location(speaker) or ""
        if room is None:
            room = get_character_current_room(speaker) or ""

    # The speaker's point is read only in the wilderness — inside a location
    # the room columns already say where the line was spoken.
    speaker_pos: Optional[Dict[str, float]] = None
    if not loc:
        from app.models.character import get_character_pos
        speaker_pos = get_character_pos(speaker)

    try:
        room_members, location_others, nearby = _resolve_presence(
            loc, room, speaker=speaker, speaker_pos=speaker_pos)
        targets = compute_earshot(speaker=speaker, volume=vol, addressees=addr,
                                  room_members=room_members,
                                  location_others=location_others,
                                  nearby=nearby)

        # Utterance meta: source + optional markers (e.g. event_verdict/reason),
        # so the objective observer view (which reads utterances) sees them too.
        _umeta: Dict[str, Any] = {}
        if source:
            _umeta["source"] = source
        if perception_meta:
            _umeta.update(perception_meta)
        uid = perception_store.insert_utterance(
            ts=stamp, speaker=speaker, location_id=loc, room_id=room,
            volume=vol, addressees=addr, content=content, meta=_umeta,
            pos_x=(speaker_pos or {}).get("x"),
            pos_z=(speaker_pos or {}).get("z"))

        rows = []
        for t in targets:
            # Speaker + addressees are NOT secret (one hears/sees who speaks
            # and whom they address). Only the content is secret — and it is
            # empty for whisper_meta. That lets the subjective view render
            # "X says: …" without whispered content ever leaking.
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
        # Open/touch the room's scene (§7) — best-effort, never blocking.
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
