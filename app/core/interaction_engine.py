"""Interactions — two characters play a PAIR animation clip together.

A pair clip (``app/core/animation_clips.py``: ``<kind>__a`` + ``<kind>__b``)
is recorded with both actors in one capture volume, so the two halves only
make sense played at ONE anchor, in lockstep. This module owns that state:

    profile["interaction"] = {
        "id": "…",                    # shared by both participants
        "kind": "handshake",          # the pair clip kind
        "role": "a" | "b",            # which half this character plays
        "partner": "<character>",
        "pose_key": "shaking hands",  # the catalog key that named the clip
        "anchor": {"x": 12.3, "z": -4.5, "yaw": 1.57,    # world metres / rad
                   "place_id": "sofa/s"},                # the PLACE it sits on, or None
        "started_at_game": "Y0002-D109T14:23:45",        # canonical GAME stamp
        "duration_s": 2.533,          # GAME seconds, from the clip sidecar
    }

Like a journey it is a pure function of the GAME clock: ``interaction_state``
derives the elapsed time from ``started_at_game`` and the clock, so a world
freeze freezes the handshake mid-air and every client shows the same frame
(``docs/schnittstellen-3d.md`` § A8a). Nothing here ticks on its own; the
travel ticker calls ``settle_finished`` and anything that moves a character
away (journey, teleport, a new pose) calls ``end_interaction``.

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
from typing import Any, Dict, List, Optional, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

logger = get_logger(__name__)

# Farther apart than this and the pair is not "together" — the clip's own
# approach (the handshake take starts 2 m apart) covers the rest visually.
MAX_START_DISTANCE_M = 4.5
# How long a LOOPING pair clip runs (game seconds) — the clip itself is a
# cycle of a second or two; the interaction is the scene, not the cycle.
LOOP_INTERACTION_S = 30.0


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
    """Where the clip stands at ``now_game``: elapsed GAME seconds, whether it
    is over. Pure — no I/O."""
    started = GameTime.parse(inter["started_at_game"])
    elapsed = max(0.0, (now_game - started).seconds)
    duration = float(inter.get("duration_s") or 0.0)
    done = duration > 0 and elapsed >= duration
    return {"elapsed_s": round(min(elapsed, duration) if duration > 0 else elapsed, 3),
            "duration_s": duration, "done": done}


def payload_for(character_name: str, profile: Dict[str, Any],
                now_game: GameTime, rate: float = 0.0) -> Optional[Dict[str, Any]]:
    """The per-character ``interaction`` block of the worldmap payload.
    ``rate`` is the game-speed factor (GAME seconds per REAL second) so a
    client can advance the clip between polls; 0 = frozen."""
    inter = get_interaction(character_name, profile)
    if not inter:
        return None
    st = interaction_state(inter, now_game)
    if st["done"]:
        return None
    return {
        "id": inter["id"],
        "kind": inter["kind"],
        "role": inter["role"],
        "partner": inter["partner"],
        "anchor": dict(inter.get("anchor") or {}),
        "started_at_game": inter["started_at_game"],
        "elapsed_s": st["elapsed_s"],
        "duration_s": st["duration_s"],
        # the clip's own length and whether it cycles — a looping clip is
        # replayed (elapsed mod clip length) for the whole duration
        "clip_duration_s": float(inter.get("clip_duration_s") or st["duration_s"]),
        "loop": bool(inter.get("loop")),
        "rate": round(float(rate or 0.0), 4),
    }


# ------------------------------------------------------------------ kinds

def pair_kind_for_pose(pose_key: str) -> str:
    """The pair clip kind a catalog pose names — "" when the pose is a solo
    one or its clip is not a complete pair."""
    from app.core.animation_clips import pair_kinds
    from app.core.expression_pose_maps import is_partner_activity, resolve_pose_animation
    if not pose_key or not is_partner_activity(pose_key):
        return ""
    kind = resolve_pose_animation(pose_key)
    return kind if kind in pair_kinds() else ""


def partner_poses() -> List[Tuple[str, str]]:
    """``(pose_key, pair_kind)`` for every catalog pose that has a complete
    pair clip — what the interact verb offers."""
    from app.core.pose_catalog import get_catalog
    out = []
    for key in get_catalog("pose"):
        kind = pair_kind_for_pose(key)
        if kind:
            out.append((key, kind))
    return out


# ------------------------------------------------------------------ writing

def _yaw_from_to(ax: float, az: float, bx: float, bz: float) -> float:
    """Y rotation that maps clip +X onto the world direction A→B."""
    ux, uz = bx - ax, bz - az
    return math.atan2(-uz, ux)


def _rotate(x: float, z: float, yaw: float) -> Tuple[float, float]:
    c, s = math.cos(yaw), math.sin(yaw)
    return (x * c + z * s, -x * s + z * c)


def start_interaction(actor: str, partner: str, pose_key: str) -> Dict[str, Any]:
    """Binds ``actor`` (role A) and ``partner`` (role B) to the pair clip the
    pose names. Raises ``ValueError`` with a reason a tool result can relay."""
    from app.core.animation_clips import clip_meta
    from app.core.state_events import publish
    from app.core.travel_engine import get_journey
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
    duration = float(meta.get("duration_s") or 0.0)
    if duration <= 0:
        raise ValueError(f"pair clip '{kind}' has no sidecar duration")
    # A cycle (sidecar ``loop``) is repeated for LOOP_INTERACTION_S game
    # seconds — a 0.5 s cycle played once was a blink at any game speed.
    clip_duration = duration
    loop = bool(meta.get("loop"))
    if loop:
        duration = max(duration, LOOP_INTERACTION_S)

    profiles = {n: get_character_profile(n) or {} for n in (actor, partner)}
    for name, prof in profiles.items():
        if get_journey(name, profile=prof):
            raise ValueError(f"{name} is travelling")
        if get_interaction(name, prof):
            raise ValueError(f"{name} is already busy with someone")
    loc_a = get_character_current_location(actor) or ""
    loc_b = get_character_current_location(partner) or ""
    if loc_a != loc_b:
        raise ValueError(f"{partner} is not here")
    if loc_a and (get_character_current_room(actor) or "") != (get_character_current_room(partner) or ""):
        raise ValueError(f"{partner} is in another room")
    pa = get_character_pos(actor)
    pb = get_character_pos(partner)
    if not pa or not pb:
        raise ValueError("both characters need a map position")
    dist = math.dist((pa["x"], pa["z"]), (pb["x"], pb["z"]))
    if dist > MAX_START_DISTANCE_M:
        raise ValueError(f"{partner} is too far away ({dist:.1f} m)")

    # Anchor: a free place of the pose's group when the room has one — its
    # centre, the clip turned to the marker's facing; else (standing pairs
    # only) the midpoint, clip +X towards the partner. A degenerate zero
    # distance keeps the actor's facing irrelevant — any yaw will do.
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
            places.release_pair(actor, partner)
            if place["group"] != "stand":
                raise ValueError(f"{who} is too far from the {place['label']} ({far:.1f} m)")
            seated = None
    if seated:
        anchor = {"x": round(ax, 3), "z": round(az, 3), "yaw": round(yaw, 4),
                  "place_id": place["id"]}
    else:
        yaw = _yaw_from_to(pa["x"], pa["z"], pb["x"], pb["z"]) if dist > 1e-6 else 0.0
        anchor = {"x": round((pa["x"] + pb["x"]) / 2, 3),
                  "z": round((pa["z"] + pb["z"]) / 2, 3), "yaw": round(yaw, 4),
                  "place_id": None}
    inter_id = uuid.uuid4().hex[:12]
    started = game_time().canonical()
    roles = (meta.get("geometry") or {}).get("roles") or {}
    for name, role, other in ((actor, "a", partner), (partner, "b", actor)):
        # Re-read: assign_pair just wrote the place into both profiles.
        prof = profiles[name] = get_character_profile(name) or {}
        prof["interaction"] = {
            "id": inter_id, "kind": kind, "role": role, "partner": other,
            "pose_key": pose_key, "anchor": anchor,
            "started_at_game": started, "duration_s": round(duration, 3),
            "clip_duration_s": round(clip_duration, 3), "loop": loop,
        }
        save_character_profile(name, prof)
        # The game-state position is where the clip holds the figure at the
        # anchor moment — perception, rules and the map all see them there.
        off = (roles.get(role) or {}).get("anchor_xz_m")
        if off:
            dx, dz = _rotate(float(off[0]), float(off[1]), yaw)
            set_character_pos(name, anchor["x"] + dx, anchor["z"] + dz,
                              preserve_movement_target=True)
        set_pose_intent(name, pose_key)
    publish("interaction_started", actor, partner=partner, kind=kind,
            interaction_id=inter_id, duration_s=duration)
    logger.info("interaction %s: %s (a) + %s (b) play '%s' for %.1fs",
                inter_id, actor, partner, kind, duration)
    return profiles[actor]["interaction"]


def end_interaction(character_name: str, reason: str = "ended") -> bool:
    """Clears the interaction on the character AND the partner. True when
    there was one."""
    from app.core.state_events import publish
    from app.models.character import (clear_pose_intent, get_character_profile,
                                      save_character_profile)
    prof = get_character_profile(character_name) or {}
    inter = get_interaction(character_name, prof)
    if not inter:
        return False
    partner = inter["partner"]
    for name in (character_name, partner):
        p = prof if name == character_name else (get_character_profile(name) or {})
        cur = p.get("interaction")
        if isinstance(cur, dict) and cur.get("id") == inter["id"]:
            p.pop("interaction", None)
            same_pose = (p.get("pose_key") or "") == inter.get("pose_key")
            if not same_pose:
                # The pair seat goes with the interaction; with the pair pose
                # still on, clear_pose_intent below stands the character up.
                p["place"] = None
            save_character_profile(name, p)
            if same_pose:
                clear_pose_intent(name)
    publish("interaction_ended", character_name, partner=partner,
            kind=inter["kind"], interaction_id=inter["id"], reason=reason)
    logger.info("interaction %s ended (%s)", inter["id"], reason)
    return True


def settle_finished() -> int:
    """Ends every interaction whose clip has run out (called by the travel
    ticker on its 5 s beat). Returns how many it closed."""
    from app.models.character import get_character_profile, list_available_characters
    now = game_time()
    closed = 0
    for name in list_available_characters():
        try:
            inter = get_interaction(name, get_character_profile(name) or {})
            if inter and interaction_state(inter, now)["done"]:
                if end_interaction(name, reason="finished"):
                    closed += 1
        except Exception as e:          # one bad profile must not stop the beat
            logger.debug("settle interaction failed for %s: %s", name, e)
    return closed
