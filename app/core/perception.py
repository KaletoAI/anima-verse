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

A speaker that is not a character has no point and therefore no circle out
there — narration would reach nobody. Such lines carry an ``anchor`` (the
acting character) and borrow ITS point; see ``record_utterance``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

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

# Grid edge for BUCKETING open-world conversations (E6). This is not a
# perception boundary — who hears what is the hearing radius around the
# speaker, full stop. It is only how the agent loop names a "scene" outside:
# the chime budget, the winddown marker and the respond lock all need SOME
# bucket, and outside there is no room to be one. The single shared bucket the
# wilderness had before meant one conversation could spend the chime budget of
# the whole open world, permanently.
#
# The edge is at least the hearing radius, so the people of one conversation
# normally land in one cell; a speaker close to a cell border can still
# straddle two, which splits a BUDGET and never changes who perceives what.
# The 50 m floor keeps the cells coarse enough that a group walking on does
# not hop buckets every few steps.
OPEN_WORLD_CELL_MIN_M = 50.0

# Canonical speaker value for narrator/storyteller lines (act narration, spell
# results, movement traces, party joins). Persisted AND player-visible, so it is
# one constant referenced everywhere (write + presence filters) — never a bare
# string literal (previously a bare narrator literal). Localised for display via
# t("Storyteller", lang); the stored value stays this canonical English token.
#
# The storyteller is not a character: it stands nowhere, so out in the open it
# has no hearing circle of its own. That is what ``anchor`` is for — see
# ``record_utterance``.
STORYTELLER_SPEAKER = "Storyteller"

# A narration anchor: either the NAME of the character the line belongs to
# (its current point is read) or an explicit metre point.
Anchor = Union[str, Mapping[str, float]]

# What the PROMPTS call the place of a location-less character. Before E6 the
# prompt builders rendered a bare "Unknown" here, which reads as "we do not
# know where you are" — the opposite of the truth: we know exactly where the
# character stands, it is simply out in the open. English like every other
# prompt string; the character's own language comes from its language
# instruction, not from this label.
WILDERNESS_LOCATION_LABEL = "Wilderness (in the open, no building, no room)"
# ...and what they call the place of a character the map does not place at all
# (off-map: auto-sleep, a reaped avatar). Unchanged from before E6 on purpose —
# see ``prompt_place``.
UNKNOWN_LOCATION_LABEL = "Unknown"


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


def anchor_pos(anchor: Optional[Anchor]) -> Optional[Dict[str, float]]:
    """Metre point of a narration anchor — ``{"x": ..., "z": ...}`` or None.

    A string is a character NAME (its current point is read), a mapping is an
    explicit point. Anything unusable (unknown name, half-filled point) is
    None, which puts the line back where it was without an anchor: spoken from
    nowhere, heard by nobody.
    """
    if not anchor:
        return None
    if isinstance(anchor, str):
        from app.models.character import get_character_pos
        return get_character_pos(anchor)
    try:
        return {"x": float(anchor["x"]), "z": float(anchor["z"])}
    except (KeyError, TypeError, ValueError):
        return None


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


def _addressable(location_id: str, room_id: str,
                 pos: Optional[Dict[str, float]], exclude: str) -> List[str]:
    """The shared body of the two addressability queries below.

    Room list FIRST (when there is a location at all), then the earshot circle
    around ``pos`` — one list, deduplicated, order preserved. Both halves are
    the EXISTING rosters: ``room_entry._list_characters_in_room`` and
    ``_nearby_in_the_open``; nothing here invents a second distance rule or a
    second room rule.

    The roster filter of the room path (``list_available_characters``, which
    drops pooled NPCs and every system row) is applied to the WHOLE result, so
    the open half cannot answer with somebody the room half would have hidden
    — a pooled NPC has no metre point at all today, but the two lists must not
    be allowed to drift apart on that.
    """
    from app.core.room_entry import _list_characters_in_room
    from app.models.character import list_available_characters

    names: List[str] = []
    if location_id:
        names.extend(_list_characters_in_room(location_id, room_id))
    names.extend(_nearby_in_the_open(exclude or "", pos))

    roster = set(list_available_characters())
    out: List[str] = []
    seen = set()
    for name in names:
        if not name or name == exclude or name in seen or name not in roster:
            continue
        seen.add(name)
        out.append(name)
    return out


def addressable_for(character_name: str) -> List[str]:
    """Everyone this character can ADDRESS right now — THE one rule.

    Three gates used to ask this question and all three answered it with the
    room alone: an avatar out on the road, or standing at a gate with somebody
    right in front of it, could hear that somebody (the wilderness branch of
    ``record_utterance`` has always worked) but could not speak to them,
    because "no location" meant "nobody present".

    The answer is the union of the two rosters that already exist:

    * the ROOM, when the character is inside a location — same rule, same
      helper, same room-id/room-name tolerance as every other room path;
    * the EARSHOT CIRCLE around the character's own metre point: everybody
      location-less within ``game.hearing_radius_m``. That half applies
      INSIDE a location too — the point is the truth, and somebody standing
      in front of the gate is within shouting distance of the taproom.

    Never contains the character itself. A character the map does not place
    anywhere and that stands in no location addresses nobody.
    """
    if not character_name:
        return []
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_pos)
    loc = get_character_current_location(character_name) or ""
    room = (get_character_current_room(character_name) or "") if loc else ""
    return _addressable(loc, room, get_character_pos(character_name),
                        character_name)


def addressable_at_location(location: str, room_id: str = "") -> List[str]:
    """The same rule asked for a PLACE instead of for a character.

    ``build_characters_at_location`` answers "who is at this location" without
    an avatar to measure from, so the circle is measured from the LOCATION's
    own map anchor. A location that was never placed on the map has no anchor
    and therefore no circle — its answer is the room list alone.

    Nobody is excluded here: the caller asks about a place, not about what it
    can reach from where it stands.
    """
    from app.models.world import resolve_location
    loc = resolve_location(location) or {}
    loc_id = str(loc.get("id") or "") or str(location or "")
    pos = None
    try:
        if loc.get("pos_x") is not None and loc.get("pos_z") is not None:
            pos = {"x": float(loc["pos_x"]), "z": float(loc["pos_z"])}
    except (TypeError, ValueError):
        pos = None
    return _addressable(loc_id, room_id, pos, "")


def open_world_cell_key(x: float, z: float) -> str:
    """Bucket name of the open-world cell a metre point falls into.

    See ``OPEN_WORLD_CELL_MIN_M`` for why the cell exists and how big it is.
    Pure — the only input is the point (and the configured radius).

    Because the radius is an input, raising ``game.hearing_radius_m`` above the
    50 m floor at runtime RE-KEYS every open-world cell at once: chime budgets
    and winddown markers keyed by the old names are orphaned (they reset), and
    a respond turn already running holds the OLD key's lock while a new turn
    takes the new one — a one-time, bounded parallel window of exactly the
    same class as a speaker straddling a cell border."""
    cell = max(OPEN_WORLD_CELL_MIN_M, get_hearing_radius_m())
    return f"open:{math.floor(x / cell)}:{math.floor(z / cell)}"


def prompt_place(character_name: str, location_id: str) -> Tuple[str, bool]:
    """Where a PROMPT says this character is: ``(display name, in_the_open)``.

    THREE states, not two — that third one is the whole point of this
    function:

    * inside a location  -> the location's name, ``in_the_open`` False.
    * location-less but placed on the map -> the wilderness label, True.
      "Nobody is around" is then a fact worth telling the character.
    * no metre point at all -> ``"Unknown"``, False. Off-map is a live,
      ordinary state: auto-sleep and ``account.reap_orphaned_avatars`` park
      characters there and they stay awake and chattable. Such a character
      does not stand in open country, so it must not be told "you are alone
      out here" — the honest answer is the one the builders gave before E6.

    One function for both prompt builders: they used to hardcode the same
    "Unknown" fallback separately, and a rule fixed in only one of them would
    have drifted immediately."""
    if location_id:
        from app.models.world import get_location_name
        return get_location_name(location_id), False
    from app.models.character import get_character_pos
    if not get_character_pos(character_name):
        return UNKNOWN_LOCATION_LABEL, False
    return WILDERNESS_LOCATION_LABEL, True


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
    position), and out in the open so does the POINT — ``anchor`` below. An
    EMPTY location is the wilderness, not a missing value: the action still
    happened and the people standing around the character still react to it,
    so the old early return here is gone (E6).

    Best-effort — never raises into the calling route."""
    try:
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        loc = get_character_current_location(character_name) or ""
        room = get_character_current_room(character_name) or ""
        record_utterance(speaker=STORYTELLER_SPEAKER, content=text,
                         volume=VOLUME_NORMAL, location_id=loc,
                         room_id=room, source=source,
                         perception_meta=perception_meta,
                         anchor=character_name)
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
                     perception_meta: Optional[Dict[str, Any]] = None,
                     anchor: Optional[Anchor] = None) -> Optional[int]:
    """Records a speech act + distributes the perceptions (fan-out).

    Presence is resolved NOW. Returns the utterance id — or None on error, so
    callers (e.g. the shadow write) can never break because of it.

    location_id/room_id default to the speaker's current state. An empty
    location is not "unknown" but the WILDERNESS: the speaker's metre point
    becomes the centre of its hearing radius and is written onto the utterance.
    dedupe=True skips if (speaker, ts, content) already exists (shadow: the
    same message can land in several histories).

    ``anchor`` is for speakers WITHOUT a point of their own — the storyteller
    above all, which is not a character and stands nowhere. Out in the open a
    line without a centre has an empty hearing circle, so narration used to
    reach nobody, not even the character it was about. The anchor (a character
    name or an explicit point) supplies that centre, and the circle is then the
    same one the acting character's own words would have. It is read ONLY when
    the speaker has no point of its own, never as an override, and inside a
    location it is ignored altogether — there the room columns decide.
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
    # the room columns already say where the line was spoken. A speaker with
    # no point of its own (the storyteller) falls back to the anchor.
    speaker_pos: Optional[Dict[str, float]] = None
    if not loc:
        from app.models.character import get_character_pos
        speaker_pos = get_character_pos(speaker) or anchor_pos(anchor)

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
