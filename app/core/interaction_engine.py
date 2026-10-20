"""Interactions — two characters play a PAIR animation clip together.

A pair clip (``app/core/animation_clips.py``: ``<kind>__a`` + ``<kind>__b``)
is recorded with both actors in one capture volume, so the two halves only
make sense played at ONE anchor, in lockstep. This module owns that state:

    profile["interaction"] = {
        "id": "…",                    # shared by both participants
        "invite_id": "…",             # optional question that consented to this pair
        "kind": "handshake",          # the pair clip kind
        "role": "a" | "b",            # which half this character plays
        "partner": "<character>",
        "pose_key": "shaking hands",  # the catalog key that named the clip
        "anchor": {"x": 12.3, "z": -4.5, "yaw": 1.57,    # world metres / rad
                   "place_id": "sofa/s"},                # the PLACE it sits on, or None
        "started_at_game": "Y0002-D109T14:23:45",        # canonical GAME stamp
        "clip_duration_s": 2.533,     # the clip's own length, from the sidecar
        "loop": True,                 # repeat the clip, or hold its last frame
    }

Like a journey its POSITION in time is a pure function of the GAME clock:
``interaction_state`` derives the elapsed time from ``started_at_game`` and
the clock, so a world freeze freezes the handshake mid-air and every client
shows the same frame (``docs/schnittstellen-3d.md`` § A8a).

An interaction has NO clock end (plan-animationen-echtzeit-stehplatz.md E4):
it runs until a SIGNAL ends it, and there is no safety cap. Nothing here ticks
on its own; everything that moves a character out of the scene calls
``end_interaction`` — a new pose or activity (``set_pose_intent`` /
``clear_pose_intent``), a position change, a journey, a room or location
change, falling asleep, NPC pooling, the avatar's ``POST /play/interact/end``,
and the partner doing any of those.

Anchor convention (shared with the clips and both renderers): the clip's
frame has its origin at the anchor and its +X pointing from A to B. A client
places a figure at ``anchor + R_y(yaw) · clip_root`` with three.js's Y
rotation (``x' = x·cos + z·sin``, ``z' = −x·sin + z·cos``), so ``yaw`` is
chosen here such that clip +X lands on the world direction from A to B.

Where the anchor IS (plan-posen-plaetze.md § 4): a pair sits on ONE place
of its pose's group when the room has one with ``places`` free slots
(``places.assign_pair`` — the sofa for a cuddle, a standing spot for a
hug): the anchor is that place's centre, ``yaw`` follows the marker's
facing (+ the pose's ``yaw_offset``) and ``place_id`` names it, so a client
draws the pair at the seat's height. Without such a place — none free, or
the free one beyond ``MAX_START_DISTANCE_M`` from a partner — a STANDING
pair meets halfway between the two figures (``place_id`` None); a seated
pair without a reachable seat is refused.
"""
import math
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

logger = get_logger(__name__)


def _narrate(anchor: str, key: str, **fmt) -> None:
    """Record a pair event in the anchor's language and room. Never raises."""
    try:
        from app.core.i18n import t
        from app.core.perception import (STORYTELLER_SPEAKER, VOLUME_NORMAL,
                                         record_utterance)
        from app.core.pose_catalog import pose_label
        from app.models.character import (get_character_current_location,
                                          get_character_current_room,
                                          get_character_language)
        lang = get_character_language(anchor)
        pose_key = fmt.pop("pose_key")
        record_utterance(
            speaker=STORYTELLER_SPEAKER,
            content=t(key, lang).format(**fmt, pose=pose_label(pose_key, lang)),
            volume=VOLUME_NORMAL,
            location_id=get_character_current_location(anchor) or "",
            room_id=get_character_current_room(anchor) or "",
            source="interaction", anchor=anchor)
    except Exception as e:
        logger.debug("interaction narration failed: %s", e)


class TooFarApart(ValueError):
    """The pair failed on METRES alone — everything else about it is fine.

    Told apart from the other refusals because it is the one that walking
    fixes: an accepted invitation answers it by sending the one who said yes
    over, instead of handing the player a refusal they have no way to act on.
    """


# Farther apart than this and the pair is not "together" — the clip's own
# approach (the handshake take starts 2 m apart) covers the rest visually.
MAX_START_DISTANCE_M = 4.5
# Out in the open there are no rooms to share, so "present" is a distance.
# Wide enough that an invitation survives the walk over, far short of "two
# dots on the same map" — the start still insists on MAX_START_DISTANCE_M.
OPEN_FIELD_REACH_M = 40.0


# ------------------------------------------------------------- the pair lock

@contextmanager
def pair_profile_locks(a: str, b: str):
    """Both partners' profile locks, ALWAYS in sorted-name order.

    A pair write touches TWO ``profile_json`` blobs, and each save rewrites
    the whole blob — so both halves have to be read and written under their
    own ``keyed_lock("character_profile", …)`` or the partner's concurrent
    equip/seat write is lost (DATA-3). Two locks at once is the one place a
    deadlock can be built here, so the order is FIXED by name: whoever wants
    both takes ``min(a, b)`` first. Two threads ending the same pair from
    opposite ends then queue up instead of each holding what the other wants.

    ``keyed_lock`` is re-entrant, so a caller that already holds ONE of the
    two names may pass through — as long as it holds the alphabetically
    EARLIER one. Holding the later name and then entering here is the
    inversion this order exists to forbid, which is why
    ``save_character_current_location`` / ``save_character_current_room`` /
    ``set_is_sleeping`` call ``end_interaction`` outside their own lock.

    Same name twice (never a real pair) is harmless: the re-entrant lock is
    simply taken twice.
    """
    from app.core.keyed_lock import keyed_lock
    first, second = sorted((str(a or ""), str(b or "")))
    with keyed_lock("character_profile", first):
        with keyed_lock("character_profile", second):
            yield


# ------------------------------------------------------------------ reading

def get_interaction(character_name: str,
                    profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The character's running interaction, or None."""
    from app.models.character import get_character_profile
    prof = profile if profile is not None else (get_character_profile(character_name) or {})
    inter = prof.get("interaction")
    if not isinstance(inter, dict):
        return None
    if not all(inter.get(k) for k in ("id", "kind", "role", "partner",
                                      "started_at_game")):
        return None
    return inter


def interaction_state(inter: Dict[str, Any], now_game: GameTime) -> Dict[str, Any]:
    """Where the clip stands at ``now_game``: elapsed GAME seconds. Pure — no
    I/O. There is nothing to be "over": the scene ends on a signal, never on
    the clock (E4), so this only ever grows."""
    started = GameTime.parse(inter["started_at_game"])
    elapsed = max(0.0, (now_game - started).seconds)
    return {"elapsed_s": round(elapsed, 3)}


def payload_for(character_name: str, profile: Dict[str, Any],
                now_game: GameTime, rate: float = 0.0) -> Optional[Dict[str, Any]]:
    """The per-character ``interaction`` block of the worldmap payload.
    ``rate`` is the game-speed factor (GAME seconds per REAL second) so a
    client can advance the clip between polls; 0 = frozen."""
    inter = get_interaction(character_name, profile)
    if not inter:
        return None
    st = interaction_state(inter, now_game)
    return {
        "id": inter["id"],
        "kind": inter["kind"],
        "role": inter["role"],
        "partner": inter["partner"],
        "anchor": dict(inter.get("anchor") or {}),
        "started_at_game": inter["started_at_game"],
        "elapsed_s": st["elapsed_s"],
        # the clip's own length and whether it cycles — a looping clip is
        # replayed (phase mod clip length), a one-shot holds its last frame
        "clip_duration_s": float(inter.get("clip_duration_s") or 0.0),
        "loop": bool(inter.get("loop")),
        "rate": round(float(rate or 0.0), 4),
    }


# ------------------------------------------------------------------ kinds

def pair_kind_for_pose(pose_key: str,
                       complete_pairs: Optional[Iterable[str]] = None) -> str:
    """The pair clip kind a catalog pose names — "" when the pose is a solo
    one or its clip is not a complete pair. ``complete_pairs`` lets a caller
    that asks for many poses pass ``pair_kinds()`` once instead of having it
    recomputed per pose."""
    from app.core.animation_clips import pair_kinds
    from app.core.expression_pose_maps import is_partner_activity, resolve_pose_animation
    if not pose_key or not is_partner_activity(pose_key):
        return ""
    kind = resolve_pose_animation(pose_key)
    pairs = pair_kinds() if complete_pairs is None else complete_pairs
    return kind if kind in pairs else ""


def partner_poses() -> List[Tuple[str, str]]:
    """``(pose_key, pair_kind)`` for every catalog pose that has a complete
    pair clip — what the interact verb offers."""
    from app.core.animation_clips import pair_kinds
    from app.core.pose_catalog import get_catalog
    complete = set(pair_kinds())
    out = []
    for key in get_catalog("pose"):
        kind = pair_kind_for_pose(key, complete)
        if kind:
            out.append((key, kind))
    return out


# ------------------------------------------------------------------ pairing

def check_can_pair(actor: str, partner: str) -> str:
    """Why ``actor`` and ``partner`` cannot pair up right now — "" when they
    can. The checks that do NOT depend on a pose or on the exact metres:
    two different, awake, present, unoccupied characters in one room.

    Shared by the invitation (asked before anyone is troubled with a
    question) and by ``start_interaction`` (asked again on acceptance,
    because minutes may have passed). The distance and the seat stay with
    the start alone — an invitation is meant to survive the walk over.
    """
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_profile,
                                      is_character_sleeping)
    from app.core.travel_engine import get_journey
    if not actor or not partner or actor == partner:
        return "an interaction needs two different characters"
    for name in (actor, partner):
        prof = get_character_profile(name)
        if prof is None:
            return f"{name} does not exist"
        if get_journey(name, profile=prof):
            return f"{name} is travelling"
        if get_interaction(name, prof):
            return f"{name} is already busy with someone"
        if is_character_sleeping(name):
            return f"{name} is asleep"
    loc_a = get_character_current_location(actor) or ""
    loc_b = get_character_current_location(partner) or ""
    if loc_a != loc_b:
        return f"{partner} is not here"
    if loc_a:
        if (get_character_current_room(actor) or "") != (get_character_current_room(partner) or ""):
            return f"{partner} is in another room"
        return ""
    # Both stand in the OPEN, where "" == "" would otherwise make two figures
    # a kilometre apart count as being in one room. Out there the only
    # measure is the metre: a rough reach, generous enough that the question
    # survives the last few steps towards each other.
    from app.models.character import get_character_pos
    pa, pb = get_character_pos(actor), get_character_pos(partner)
    if not pa or not pb:
        return f"{partner} is not here"
    if math.dist((pa["x"], pa["z"]), (pb["x"], pb["z"])) > OPEN_FIELD_REACH_M:
        return f"{partner} is too far away"
    return ""


# ------------------------------------------------------------------ writing

def _yaw_from_to(ax: float, az: float, bx: float, bz: float) -> float:
    """Y rotation that maps clip +X onto the world direction A→B."""
    ux, uz = bx - ax, bz - az
    return math.atan2(-uz, ux)


def _rotate(x: float, z: float, yaw: float) -> Tuple[float, float]:
    c, s = math.cos(yaw), math.sin(yaw)
    return (x * c + z * s, -x * s + z * c)


def assign_roles(actor: str, partner: str, actor_gender: str,
                 partner_gender: str,
                 role_gender: Dict[str, str]) -> Tuple[str, str]:
    """``(plays A, plays B)`` — who takes which half of the pair clip.

    A clip whose sidecar assigns the halves to genders (``role_gender``,
    ``animation_clips.clip_role_gender``) is matched by gender, not by who
    asked: a character FITS a half when its gender is that half's gender.
    The two swap when the actor fits B or the partner fits A — unless the
    actor fits A or the partner fits B as well, which is the case with two
    characters of the same gender. So a man and a woman always play their
    own halves, a woman beside a non-binary partner still takes hers, and
    whenever nothing decides (same gender, no gender, no assignment) the
    initiator plays A — the pair is never refused over it.
    """
    if not role_gender:
        return actor, partner
    ga = str(actor_gender or "").strip().lower()
    gp = str(partner_gender or "").strip().lower()

    def fits(gender: str, role: str) -> bool:
        return bool(gender) and gender == role_gender.get(role)

    swap = ((fits(ga, "b") or fits(gp, "a"))
            and not (fits(ga, "a") or fits(gp, "b")))
    return (partner, actor) if swap else (actor, partner)


def start_interaction(actor: str, partner: str, pose_key: str, *,
                      invite_id: str = "") -> Dict[str, Any]:
    """Binds ``actor`` (the initiator) and ``partner`` to the pair clip the
    pose names. Who plays which half follows the clip's gender assignment
    (``assign_roles``); without one the actor plays A. Raises ``ValueError``
    with a reason a tool result can relay. A supplied ``invite_id`` is stored
    with both halves before the pair locks are released."""
    from app.core.animation_clips import clip_loops, clip_meta, clip_role_gender
    from app.core.state_events import publish
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_pos, get_character_profile,
                                      save_character_profile, set_character_pos,
                                      set_pose_intent)

    if not actor or not partner or actor == partner:
        raise ValueError("an interaction needs two different characters")
    kind = pair_kind_for_pose(pose_key)
    if not kind:
        raise ValueError(f"'{pose_key}' has no pair animation")
    meta = clip_meta(kind) or {}
    clip_duration = float(meta.get("duration_s") or 0.0)
    if clip_duration <= 0:
        raise ValueError(f"pair clip '{kind}' has no sidecar duration")
    # The clip's own length is all there is: a cycle repeats for as long as
    # the scene lasts, a one-shot holds its last frame. How long the SCENE
    # lasts is not a number here — a signal ends it (E4).
    loop = clip_loops(meta)

    # The pose-independent side of "can these two pair up" — one definition,
    # asked here and by the invitation. Checked AFTER the clip: a pose with no
    # pair animation is the more useful answer than "he is asleep".
    blocked = check_can_pair(actor, partner)
    if blocked:
        raise ValueError(blocked)

    profiles = {n: get_character_profile(n) or {} for n in (actor, partner)}
    # Who plays which half: by gender when the clip assigns its halves, else
    # the initiator plays A. The geometry below orients on the HALVES (clip
    # +X runs from A to B), never on who asked.
    who_a, who_b = assign_roles(actor, partner,
                                str(profiles[actor].get("gender") or ""),
                                str(profiles[partner].get("gender") or ""),
                                clip_role_gender(meta))
    loc_a = get_character_current_location(actor) or ""
    pa = get_character_pos(actor)
    pb = get_character_pos(partner)
    if not pa or not pb:
        raise ValueError("both characters need a map position")
    dist = math.dist((pa["x"], pa["z"]), (pb["x"], pb["z"]))
    if dist > MAX_START_DISTANCE_M:
        raise TooFarApart(f"{partner} is too far away ({dist:.1f} m)")

    # Anchor: a free place of the pose's group when the room has one — its
    # centre, the clip turned to the marker's facing; else (pairs whose
    # group needs no marker only) the midpoint, clip +X towards the
    # partner. A degenerate zero distance keeps the actor's facing
    # irrelevant — any yaw will do.
    from app.core import places
    try:
        seated = places.assign_pair(actor, partner, pose_key)
    except places.PlaceUnavailable as e:
        raise ValueError(str(e))
    if seated:
        place, yaw = seated
        ax, az = places.centre_of(place)
        # The "together" rule runs against the ANCHOR here: a place out of
        # reach for one of them is no place for this pair — a standing pair
        # meets halfway instead, a seated pair is refused.
        who, pos = max(((actor, pa), (partner, pb)),
                       key=lambda wp: math.dist((wp[1]["x"], wp[1]["z"]), (ax, az)))
        far = math.dist((pos["x"], pos["z"]), (ax, az))
        if far > MAX_START_DISTANCE_M:
            from app.core.pose_catalog import needs_place
            places.release_pair(actor, partner)
            if needs_place(place["group"]):
                raise TooFarApart(
                    f"{who} is too far from the {place['label']} ({far:.1f} m)")
            seated = None
    if seated:
        anchor = {"x": round(ax, 3), "z": round(az, 3), "yaw": round(yaw, 4),
                  "place_id": place["id"]}
    else:
        p_a, p_b = (pa, pb) if who_a == actor else (pb, pa)
        yaw = _yaw_from_to(p_a["x"], p_a["z"], p_b["x"], p_b["z"]) if dist > 1e-6 else 0.0
        anchor = {"x": round((pa["x"] + pb["x"]) / 2, 3),
                  "z": round((pa["z"] + pb["z"]) / 2, 3), "yaw": round(yaw, 4),
                  "place_id": None}
    inter_id = uuid.uuid4().hex[:12]
    started = game_time().canonical()
    roles = (meta.get("geometry") or {}).get("roles") or {}
    halves = ((who_a, "a", who_b), (who_b, "b", who_a))
    # BOTH interaction blobs in ONE locked span, in sorted-name order
    # (DATA-3): each save rewrites a whole profile_json, so a concurrent
    # equip on either partner would otherwise be dropped — and the pair must
    # not be half-written, or the other half sees a partner that is not bound.
    stored = True
    with pair_profile_locks(who_a, who_b):
        for name, role, other in halves:
            # Re-read: assign_pair just wrote the place into both profiles.
            prof = profiles[name] = get_character_profile(name) or {}
            prof["interaction"] = {
                "id": inter_id, "kind": kind, "role": role, "partner": other,
                "pose_key": pose_key, "anchor": anchor,
                "started_at_game": started,
                "clip_duration_s": round(clip_duration, 3), "loop": loop,
            }
            if invite_id:
                prof["interaction"]["invite_id"] = invite_id
            if not save_character_profile(name, prof):
                stored = False
    # OUTSIDE the locks: both of these write the profile themselves and reach
    # the places-lock (``set_pose_intent`` -> ``places.assign``), which by the
    # documented order comes BEFORE ``character_profile``. Neither reads the
    # other partner, so running them after both blobs are stored changes
    # nothing but the order in which two independent figures are placed.
    for name, role, other in halves:
        # The game-state position is where the clip holds the figure at the
        # anchor moment — perception, rules and the map all see them there.
        # Unless that point lies outside the location (a marker authored
        # past the footprint): the write would evict, so the figure stays
        # where it is and only the seat is bookkept (`places.inside`).
        off = (roles.get(role) or {}).get("anchor_xz_m")
        if off:
            dx, dz = _rotate(float(off[0]), float(off[1]), yaw)
            px, pz = anchor["x"] + dx, anchor["z"] + dz
            if not anchor.get("place_id") or places.inside(loc_a, px, pz):
                set_character_pos(name, px, pz, preserve_movement_target=True)
        set_pose_intent(name, pose_key)
    publish("interaction_started", actor, partner=partner, kind=kind,
            interaction_id=inter_id, clip_duration_s=clip_duration)
    from app.core import sync_topics
    if stored:
        sync_topics.changed_at(actor, loc_a)
    # The room has to SEE it. Without a line in the perception stream the
    # pair is a 3D animation nobody in the fiction ever noticed — including
    # the two doing it, who read the stream as their own memory of the scene.
    _narrate(actor, "{actor} and {partner} start {pose}.",
             actor=actor, partner=partner, pose_key=pose_key)
    logger.info("interaction %s: %s (a) + %s (b) play '%s' (%.1fs %s)",
                inter_id, who_a, who_b, kind, clip_duration,
                "cycle" if loop else "one-shot")
    return profiles[actor]["interaction"]


def end_interaction(character_name: str, reason: str = "ended", *,
                    interaction_id: str = "") -> bool:
    """Clears the interaction on the character AND the partner. True when
    there was one.

    Both partners STAND UP from the pair seat, and where they stand then is the
    server's word (T4): with the pair pose still on, ``clear_pose_intent``
    carries the standing point; where the pose has already moved on, the place
    is dropped here and ``room_stand.stand_up`` is asked here — the two must
    not end up on top of each other, which is why the first one placed counts
    as the second one's neighbour.

    ``interaction_id`` restricts an owned cancellation to that exact running
    pair; its identity is checked again under the removal locks.
    """
    from app.core.room_stand import stand_up
    from app.core.state_events import publish
    from app.models.character import (clear_pose_intent, get_character_profile,
                                      save_character_profile)
    inter = get_interaction(character_name)
    if not inter or (interaction_id and inter["id"] != interaction_id):
        return False
    partner = inter["partner"]
    # BOTH profiles under BOTH locks, in sorted-name order (DATA-3). The
    # standing-up that follows is collected here and run AFTERWARDS:
    # ``clear_pose_intent`` and ``room_stand.stand_up`` write the profile
    # themselves and reach the places-lock, which comes BEFORE
    # ``character_profile`` in the documented order — doing them inside would
    # invert it.
    stand: list = []
    cleared = True
    saved_names: list[str] = []
    ended_invite_id = ""
    with pair_profile_locks(character_name, partner):
        for name in (character_name, partner):
            p = get_character_profile(name) or {}
            cur = p.get("interaction")
            if interaction_id and name == character_name and not (
                    isinstance(cur, dict) and cur.get("id") == interaction_id
                    and cur.get("partner") == partner):
                return False
            if not (isinstance(cur, dict) and cur.get("id") == inter["id"]):
                continue
            if not ended_invite_id:
                ended_invite_id = str(cur.get("invite_id") or "")
            p.pop("interaction", None)
            same_pose = (p.get("pose_key") or "") == inter.get("pose_key")
            if not same_pose:
                # The pair seat goes with the interaction; with the pair pose
                # still on, clear_pose_intent below stands the character up.
                p["place"] = None
            if save_character_profile(name, p):
                saved_names.append(name)
            else:
                cleared = False
            stand.append((name, same_pose))
    for name, same_pose in stand:
        if same_pose:
            clear_pose_intent(name)
        else:
            stand_up(name)
    publish("interaction_ended", character_name, partner=partner,
            kind=inter["kind"], interaction_id=inter["id"], reason=reason)
    from app.core import sync_topics
    for name in saved_names:
        sync_topics.changed_at(name)
    if stand and cleared:
        actor, other = ((character_name, partner) if inter.get("role") == "a"
                        else (partner, character_name))
        _narrate(character_name, "{actor} and {partner} stop {pose}.",
                 actor=actor, partner=other, pose_key=inter["pose_key"])
        from app.core.hooks import emit
        emit("interaction.ended", character=character_name, partner=partner,
             interaction_id=inter["id"], invite_id=ended_invite_id, reason=reason)
    logger.info("interaction %s ended (%s)", inter["id"], reason)
    return True


# ------------------------------------------------------------------ invites
#
# A pair clip cannot be done TO someone: it binds two figures to one anchor
# and plays both halves at once. So a pair is proposed, not imposed —
# ``create_invite`` records the question, the answer starts the clip. The
# avatar answers through ``/play/interact/respond``, an NPC through an
# ``InteractWith`` turn of its own (never by keyword-matching its prose).
# The row is also the DIRECTION record: an invitation answered with a
# counter-invitation of the same pose is consent, not a second proposal.

#: How long an open invitation may be answered — SYSTEM minutes, like the
#: party's. This is a conversational window, not an in-world duration: a
#: frozen world must not leave a question hanging forever, and a question
#: nobody answered must not still start a clip in a scene hours later.
INVITE_MAX_AGE_MIN = 30


#: Answered rows older than this are swept away on the next invitation,
#: except an accepted question whose exact pair is still live.
#: SYSTEM hours, like the window itself — this is bookkeeping, not world time.
_INVITE_KEEP_HOURS = 24


def _sweep_before() -> str:
    from datetime import timedelta
    from app.core.timeutils import utc_now
    return (utc_now() - timedelta(hours=_INVITE_KEEP_HOURS)).isoformat()


def _invite_row(r) -> Dict[str, Any]:
    return {"invite_id": r[0], "inviter": r[1], "invitee": r[2],
            "pose_key": r[3], "created_at": r[4], "status": r[5], "reason": r[6]}


def _fresh(created_at: str, max_age_minutes: int = INVITE_MAX_AGE_MIN) -> bool:
    from app.core.timeutils import parse_iso, utc_now
    try:
        return (utc_now() - parse_iso(created_at)).total_seconds() <= max_age_minutes * 60
    except Exception:
        return True


def _sweep_invites() -> None:
    """Remove old answered questions without losing a live pair's consent."""
    from app.core.db import transaction
    before = _sweep_before()
    stored_tx_1 = False
    with transaction() as conn:
        conn.execute(
            "DELETE FROM interaction_invites WHERE status NOT IN ('pending', 'accepted') "
            "AND created_at < ?", (before,))
        rows = conn.execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
            "FROM interaction_invites WHERE status='accepted' AND created_at < ?",
            (before,)).fetchall()
        stored_tx_1 = True
    # Release the database write transaction BEFORE taking profile locks:
    # a pair write holds those locks while saving its profiles to the DB.
    for row in rows:
        inv = _invite_row(row)
        with pair_profile_locks(inv["inviter"], inv["invitee"]):
            actor = get_interaction(inv["inviter"])
            partner = get_interaction(inv["invitee"])
            if (actor and partner
                    and actor.get("invite_id") == partner.get("invite_id") == inv["invite_id"]
                    and actor["id"] == partner["id"]
                    and actor["partner"] == inv["invitee"]
                    and partner["partner"] == inv["inviter"]
                    and actor.get("pose_key") == partner.get("pose_key") == inv["pose_key"]):
                continue
            stored_tx_2 = False
            with transaction() as conn:
                conn.execute(
                    "DELETE FROM interaction_invites WHERE invite_id=? "
                    "AND status='accepted' AND created_at < ?",
                    (inv["invite_id"], before))
                stored_tx_2 = True
        from app.core import sync_topics
        if stored_tx_2:
            sync_topics.avatars([inv["inviter"], inv["invitee"]], "presence")


def create_invite(inviter: str, invitee: str, pose_key: str, *,
                  request_id: Optional[str] = None) -> Optional[str]:
    """Record "shall we <pose>?" and return its id (None on bad input).

    Without ``request_id``, a fresh pending question with the same exact
    inviter/invitee/pose is reused, including a supplied id. Different-pose
    or stale pending questions of that direction are cancelled, not deleted.
    A supplied id atomically creates or reuses only its exact
    inviter/invitee/pose row, never replaces another question, and emits the
    offer only on creation.
    """
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    inviter = (inviter or "").strip()
    invitee = (invitee or "").strip()
    pose_key = (pose_key or "").strip()
    if not inviter or not invitee or inviter == invitee or not pose_key:
        return None
    if request_id is not None and (not isinstance(request_id, str) or not request_id):
        return None
    invite_id = request_id if request_id is not None else "iinv_" + uuid.uuid4().hex[:10]
    created = True
    try:
        if request_id is None:
            _sweep_invites()
        stored_tx_1 = False
        with transaction() as conn:
            if request_id is None:
                # This write also serializes ordinary duplicate requests
                # before they read the remaining same-pose questions.
                conn.execute(
                    "UPDATE interaction_invites SET status='cancelled' "
                    "WHERE inviter=? AND invitee=? AND status='pending' AND pose_key<>?",
                    (inviter, invitee, pose_key))
                rows = conn.execute(
                    "SELECT invite_id, created_at FROM interaction_invites "
                    "WHERE inviter=? AND invitee=? AND pose_key=? AND status='pending' "
                    "ORDER BY created_at DESC", (inviter, invitee, pose_key)).fetchall()
                for row in rows:
                    if _fresh(row[1]):
                        if created:
                            invite_id, created = row[0], False
                    else:
                        conn.execute(
                            "UPDATE interaction_invites SET status='cancelled' "
                            "WHERE invite_id=? AND status='pending'", (row[0],))
                if created:
                    conn.execute(
                        "INSERT INTO interaction_invites (invite_id, inviter, invitee, "
                        "pose_key, created_at, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                        (invite_id, inviter, invitee, pose_key, utc_now_iso()))
            else:
                inserted = conn.execute(
                    "INSERT OR IGNORE INTO interaction_invites "
                    "(invite_id, inviter, invitee, pose_key, created_at, status) "
                    "VALUES (?, ?, ?, ?, ?, 'pending')",
                    (invite_id, inviter, invitee, pose_key, utc_now_iso()))
                created = inserted.rowcount == 1
                row = conn.execute(
                    "SELECT inviter, invitee, pose_key FROM interaction_invites "
                    "WHERE invite_id=?", (invite_id,)).fetchone()
                if not row or tuple(row) != (inviter, invitee, pose_key):
                    return None
            stored_tx_1 = True
    except Exception as e:
        logger.debug("create_invite failed: %s", e)
        return None
    from app.core import sync_topics
    if stored_tx_1:
        sync_topics.avatars([inviter, invitee], "presence")
    if not created:
        return invite_id
    _narrate(inviter, "{inviter} suggests {pose} to {invitee}.",
             inviter=inviter, invitee=invitee, pose_key=pose_key)
    logger.info("interaction invite %s: %s asks %s for '%s'",
                invite_id, inviter, invitee, pose_key)
    # Somebody now has a question. WHO answers it and how is not the core's
    # business (R1): a player answers in the UI, an NPC needs a turn phrased
    # with the verb it owns — the package that owns that verb listens here.
    try:
        from app.core.hooks import emit
        emit("interaction.invited", invite_id=invite_id, inviter=inviter,
             invitee=invitee, pose_key=pose_key)
    except Exception as e:
        logger.debug("interaction.invited emit failed: %s", e)
    return invite_id


def get_invite(invite_id: str) -> Optional[Dict[str, Any]]:
    from app.core.db import get_connection
    if not invite_id:
        return None
    try:
        r = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
            "FROM interaction_invites WHERE invite_id=?", (invite_id,)).fetchone()
    except Exception:
        return None
    return _invite_row(r) if r else None


def pending_invites_for(invitee: str) -> List[Dict[str, Any]]:
    """Open, fresh invitations addressed to ``invitee`` whose inviter is still
    in the same room — the list the player is asked.

    Filtered at read time, exactly like the party's: an invitation from
    someone who has since walked out would only fail on acceptance, so the
    question disappears on its own instead of offering a dead button.
    """
    from app.core.db import get_connection
    from app.models.character import (get_character_current_location,
                                       get_character_current_room)
    invitee = (invitee or "").strip()
    if not invitee:
        return []
    try:
        rows = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
            "FROM interaction_invites WHERE invitee=? AND status='pending' "
            "ORDER BY created_at ASC", (invitee,)).fetchall()
    except Exception:
        return []
    here = (get_character_current_location(invitee) or "",
            get_character_current_room(invitee) or "")
    out = []
    for r in rows:
        inv = _invite_row(r)
        if not _fresh(inv["created_at"]):
            continue
        there = (get_character_current_location(inv["inviter"]) or "",
                 get_character_current_room(inv["inviter"]) or "")
        if there == here:
            out.append(inv)
    return out


def outgoing_invite_of(inviter: str) -> Optional[Dict[str, Any]]:
    """The open, fresh invitation ``inviter`` is waiting on — so the UI can
    show "waiting for X…" with a way to take it back."""
    from app.core.db import get_connection
    inviter = (inviter or "").strip()
    if not inviter:
        return None
    try:
        r = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
            "FROM interaction_invites WHERE inviter=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1", (inviter,)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    inv = _invite_row(r)
    return inv if _fresh(inv["created_at"]) else None


def approach_of(character: str) -> Optional[Dict[str, Any]]:
    """The accepted invitation ``character`` is part of while the one who
    agreed is still walking over — either side, so both ends of the pair can
    be told what is happening."""
    from app.core.db import get_connection
    c = (character or "").strip()
    if not c:
        return None
    try:
        r = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
            "FROM interaction_invites WHERE status='approaching' "
            "AND (inviter=? OR invitee=?) ORDER BY created_at DESC LIMIT 1",
            (c, c)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    inv = _invite_row(r)
    return inv if _fresh(inv["created_at"]) else None


def find_pending_invite(inviter: str, invitee: str,
                        pose_key: str = "") -> Optional[Dict[str, Any]]:
    """A fresh open invitation ``inviter`` -> ``invitee``, optionally only for
    ``pose_key``. This is what turns a counter-invitation into consent."""
    from app.core.db import get_connection
    inviter = (inviter or "").strip()
    invitee = (invitee or "").strip()
    if not inviter or not invitee:
        return None
    sql = ("SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
           "FROM interaction_invites WHERE inviter=? AND invitee=? "
           "AND status='pending'")
    args: List[Any] = [inviter, invitee]
    if pose_key:
        sql += " AND pose_key=?"
        args.append(pose_key)
    try:
        r = get_connection().execute(
            sql + " ORDER BY created_at DESC LIMIT 1", tuple(args)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    inv = _invite_row(r)
    return inv if _fresh(inv["created_at"]) else None


def _set_invite_status(invite_id: str, status: str, *,
                       expected_status: str = "answering") -> bool:
    """Move only the row still owned by this answer or approach."""
    from app.core.db import transaction
    inv = get_invite(invite_id)
    try:
        stored_tx_1 = False
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE interaction_invites SET status=? WHERE invite_id=? AND status=?",
                (status, invite_id, expected_status))
            changed = cur.rowcount == 1
            stored_tx_1 = True
        if changed and inv:
            from app.core import sync_topics
            if stored_tx_1:
                sync_topics.avatars([inv["inviter"], inv["invitee"]], "presence")
        return changed
    except Exception as e:
        logger.debug("invite %s -> %s failed: %s", invite_id, status, e)
        return False


def _fail_invite(inv: dict, reason: str, *, expected_status: str = "answering") -> None:
    """Publish a failed yes only after atomically owning its terminal change."""
    from app.core.db import transaction
    from app.core.hooks import emit
    from app.core import sync_topics
    with transaction() as conn:
        changed = conn.execute(
            "UPDATE interaction_invites SET status='failed', reason=? "
            "WHERE invite_id=? AND status=?",
            (reason, inv["invite_id"], expected_status)).rowcount == 1
    if not changed:
        return
    _narrate(inv["invitee"],
             "{invitee} would like to, but {pose} with {inviter} is not possible ({reason}).",
             inviter=inv["inviter"], invitee=inv["invitee"],
             pose_key=inv["pose_key"], reason=reason)
    emit("interaction.invite_failed", invite_id=inv["invite_id"],
         inviter=inv["inviter"], invitee=inv["invitee"], pose_key=inv["pose_key"], reason=reason)
    sync_topics.avatars([inv["inviter"], inv["invitee"]], "presence")


def last_answer_of(inviter: str) -> Optional[dict]:
    """Return only the newest own question if freshly declined or failed."""
    from app.core.db import get_connection
    row = get_connection().execute(
        "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
        "FROM interaction_invites WHERE inviter=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (inviter,)).fetchone()
    if not row:
        return None
    inv = _invite_row(row)
    if inv["status"] not in ("declined", "failed") or not _fresh(inv["created_at"]):
        return None
    return {k: inv[k] for k in ("invite_id", "invitee", "pose_key", "status", "reason")}


def dismiss_answer(invite_id: str, inviter: str) -> bool:
    """Dismiss only an answered invitation owned by the supplied inviter."""
    inv = get_invite(invite_id)
    if not inv or inv["inviter"] != inviter or inv["status"] not in ("declined", "failed"):
        return False
    return _set_invite_status(invite_id, "cancelled", expected_status=inv["status"])


def _claim_invite(invite_id: str, status: str = "pending") -> bool:
    """Take the pending/approaching row out of circulation for THIS answer/start.

    One conditional UPDATE, so a double click and a simultaneous counter-call
    cannot both walk into ``start_interaction``: the loser would be told "is
    already busy with someone" about the pair the winner has just started.
    """
    from app.core.db import transaction
    inv = get_invite(invite_id)
    try:
        stored_tx_1 = False
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE interaction_invites SET status='answering' "
                "WHERE invite_id=? AND status=?", (invite_id, status))
            changed = cur.rowcount == 1
            stored_tx_1 = True
        if changed and inv:
            from app.core import sync_topics
            if stored_tx_1:
                sync_topics.avatars([inv["inviter"], inv["invitee"]], "presence")
        return changed
    except Exception as e:
        logger.debug("claiming invite %s failed: %s", invite_id, e)
        return False


def resolve_invite(invite_id: str, accept: bool) -> Dict[str, Any]:
    """Answer an open invitation.

    ``{"status": "started"|"declined"|"cannot"|"not_found", ...}``. On accept
    the situation is checked for the first time — minutes may have passed —
    and a refusal carries the engine's own reason so the UI can say WHY.

    Every accepted yes that neither starts a pair nor walks ends as failed,
    with its reason saved, narrated and emitted by the core.
    """
    inv = get_invite(invite_id)
    if not inv or inv["status"] != "pending":
        return {"status": "not_found"}
    # The row's own "status" column must never leak into the answer — the
    # verdict of THIS call is what the caller acts on.
    out = {k: v for k, v in inv.items() if k != "status"}
    if not _claim_invite(invite_id):
        return {"status": "not_found"}
    if not accept:
        if not _set_invite_status(invite_id, "declined"):
            return {**out, "status": "cannot", "reason": "the answer could not be saved"}
        _narrate(inv["invitee"],
                 "{invitee} does not feel like {pose} with {inviter} right now.",
                 inviter=inv["inviter"], invitee=inv["invitee"], pose_key=inv["pose_key"])
        return {**out, "status": "declined"}
    blocked = check_can_pair(inv["inviter"], inv["invitee"])
    if blocked:
        _fail_invite(inv, blocked)
        return {**out, "status": "cannot", "reason": blocked}
    try:
        inter = start_interaction(inv["inviter"], inv["invitee"], inv["pose_key"],
                                  invite_id=invite_id)
    except TooFarApart as e:
        # Yes was said; only the metres are missing. The one who agreed walks
        # over, and the ticker binds the pair when they get there. Saying
        # "too far away" to a player who has no way to close the gap would
        # be a dead end, not an answer.
        if _walk_to_partner(inv["invitee"], inv["inviter"]):
            if _set_invite_status(invite_id, "approaching"):
                return {**out, "status": "approaching", "reason": str(e)}
            from app.core.travel_engine import cancel_journey
            cancel_journey(inv["invitee"])
            _fail_invite(inv, "the approach could not be saved")
            return {**out, "status": "cannot", "reason": "the approach could not be saved"}
        _fail_invite(inv, str(e))
        return {**out, "status": "cannot", "reason": str(e)}
    except ValueError as e:
        # A failed yes is terminal even when a later invitation might work.
        _fail_invite(inv, str(e))
        return {**out, "status": "cannot", "reason": str(e)}
    if not _set_invite_status(invite_id, "accepted"):
        end_interaction(inv["inviter"], reason="invitation_failed",
                        interaction_id=inter["id"])
        _fail_invite(inv, "the accepted answer could not be saved")
        return {**out, "status": "cannot", "reason": "the accepted answer could not be saved"}
    clear_invites_for(inv["inviter"])
    clear_invites_for(inv["invitee"])
    _emit_invite_started(inv, inter)
    return {**out, "status": "started", "interaction": inter}


def _emit_invite_started(invitation: Dict[str, Any], interaction: Dict[str, Any]) -> None:
    """Correlate a real pair start with the question whose consent caused it."""
    from app.core.hooks import emit
    emit("interaction.invite_started", invite_id=invitation["invite_id"],
         interaction=interaction, inviter=invitation["inviter"],
         invitee=invitation["invitee"])


#: How close the walker aims to stop: not ON the other one (an occupied cell
#: is no goal) but within arm's reach of them.
_APPROACH_GAP_M = 1.0


def _walk_to_partner(walker: str, target: str) -> bool:
    """Send ``walker`` over to ``target`` on the nav grid. True when a route
    was found and the journey is running.

    The goal is a metre SHORT of the other one, on the walker's own side —
    walking onto an occupied point is no journey, and the pair snaps to its
    anchor on arrival anyway.
    """
    from app.core.travel_engine import cancel_journey, start_journey_to_point
    from app.models.character import get_character_pos
    pw, pt = get_character_pos(walker), get_character_pos(target)
    if not pw or not pt:
        return False
    dx, dz = pw["x"] - pt["x"], pw["z"] - pt["z"]
    span = math.hypot(dx, dz)
    if span <= _APPROACH_GAP_M:
        return False            # already there — the refusal was not distance
    gx = pt["x"] + dx / span * _APPROACH_GAP_M
    gz = pt["z"] + dz / span * _APPROACH_GAP_M
    # A trip already running is the one this replaces: the walker just agreed
    # to be somewhere else.
    cancel_journey(walker)
    journey, reason = start_journey_to_point(walker, gx, gz)
    if not journey:
        logger.info("%s cannot walk to %s (%s)", walker, target, reason)
        return False
    logger.info("%s walks over to %s for a pair interaction", walker, target)
    return True


def settle_approaches() -> int:
    """Bind every pair whose walker has arrived; drop the ones that will not
    happen as failed with a saved reason, narration and hook. Called on the
    travel ticker's beat, right after the journeys.

    A row stays ``approaching`` while the journey runs — the consent is
    given, only the metres are still being covered. When the walking stops
    the pair is attempted once: it either starts, or the invitation is over
    (the other one moved on, fell asleep, sat down elsewhere). Retrying
    forever would leave a character walking after someone across the world.
    """
    from app.core.db import get_connection
    from app.core.travel_engine import get_journey
    try:
        rows = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason "
            "FROM interaction_invites WHERE status='approaching'").fetchall()
    except Exception:
        return 0
    bound = 0
    for r in rows:
        inv = _invite_row(r)
        claimed = False
        try:
            if not _fresh(inv["created_at"]):
                _fail_invite(inv, "the approach expired", expected_status="approaching")
                continue
            if get_journey(inv["invitee"]):
                continue                      # still on the way
            if not _claim_invite(inv["invite_id"], "approaching"):
                continue
            claimed = True
            inter = start_interaction(inv["inviter"], inv["invitee"], inv["pose_key"],
                                      invite_id=inv["invite_id"])
            if not _set_invite_status(inv["invite_id"], "accepted"):
                end_interaction(inv["inviter"], reason="invitation_failed",
                                interaction_id=inter["id"])
                _fail_invite(inv, "the accepted answer could not be saved")
                continue
            claimed = False
            clear_invites_for(inv["inviter"])
            clear_invites_for(inv["invitee"])
            bound += 1
            _emit_invite_started(inv, inter)
        except ValueError as e:
            logger.info("interaction invite %s expired on arrival: %s",
                        inv["invite_id"], e)
            if claimed:
                _fail_invite(inv, str(e))
        except Exception as e:          # one bad row must not stop the beat
            if claimed:
                _set_invite_status(inv["invite_id"], "approaching")
            logger.debug("settle_approaches(%s) failed: %s",
                         inv.get("invite_id"), e)
    return bound


def cancel_invite(invite_id: str) -> bool:
    """Take back an invitation — before it is answered, or while the one who
    agreed is still walking over. True when there was one to take back.

    Calling off an approach also calls off the WALK: the trip existed only to
    make that pair possible, and leaving it running would march the character
    to a spot it has no reason to be at.
    """
    inv = get_invite(invite_id)
    if not inv or inv["status"] not in ("pending", "approaching"):
        return False
    if not _set_invite_status(invite_id, "cancelled", expected_status=inv["status"]):
        return False
    if inv["status"] == "approaching":
        try:
            from app.core.travel_engine import cancel_journey
            cancel_journey(inv["invitee"])
        except Exception as e:
            logger.debug("cancelling the approach walk failed: %s", e)
    from app.core import sync_topics
    sync_topics.avatars([inv["inviter"], inv["invitee"]], "presence")
    return True


def clear_invites_for(character: str) -> None:
    """Drop every open invitation ``character`` is part of — used when the
    question can no longer mean anything (the pair started, the player let
    go of the avatar)."""
    from app.core.db import transaction
    c = (character or "").strip()
    if not c:
        return
    try:
        stored_tx_1 = False
        with transaction() as conn:
            affected = conn.execute(
                "SELECT inviter, invitee FROM interaction_invites "
                "WHERE status IN ('pending', 'approaching') AND (inviter=? OR invitee=?)",
                (c, c)).fetchall()
            conn.execute("UPDATE interaction_invites SET status='stale' "
                         "WHERE status IN ('pending', 'approaching') "
                         "AND (inviter=? OR invitee=?)", (c, c))
            stored_tx_1 = True
        from app.core import sync_topics
        if stored_tx_1:
            sync_topics.avatars([n for row in affected for n in row], "presence")
    except Exception as e:
        logger.debug("clear_invites_for(%s) failed: %s", c, e)


# ------------------------------------------------------------------ reading

def describe(character_name: str,
             profile: Optional[Dict[str, Any]] = None) -> str:
    """"shaking hands with Kira" — the running interaction as one phrase, or
    "" when none runs.

    What a pair pose MEANS is the pair; printed bare it reads as two people
    striking the same solo pose next to each other. Every prompt that states
    what a character is doing goes through here.
    """
    inter = get_interaction(character_name, profile)
    if not inter:
        return ""
    pose = str(inter.get("pose_key") or inter.get("kind") or "").strip()
    partner = str(inter.get("partner") or "").strip()
    if not pose:
        return ""
    return f"{pose} with {partner}" if partner else pose
