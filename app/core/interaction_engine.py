"""Interactions — two characters play a PAIR animation clip together.

A pair clip (``app/core/animation_clips.py``: ``<kind>__a`` + ``<kind>__b``)
is recorded with both actors in one capture volume, so the two halves only
make sense played at ONE anchor, in lockstep. This module owns that state:

    profile["interaction"] = {
        "id": "…",                    # shared by both participants
        "invite_id": "…",             # optional question that consented to this pair
        "kind": "greeting-handshake", # the pair clip kind
        "role": "a" | "b",            # which half this character plays
        "members": {"a": "<character>", "b": "<character>"},  # every role -> its
                                      # character, this one included (a..e)
        "pose_key": "greeting handshake",  # the catalog key that named the clip
        "anchor": {"x": 12.3, "z": -4.5, "yaw": 1.57,    # world metres / rad
                   "place_id": "sofa/s"},                # the PLACE it sits on, or None
        "started_at_game": "Y0002-D109T14:23:45",        # canonical GAME stamp
        "started_at_sys": "2026-10-30T20:00:00.000000+00:00",  # SYSTEM stamp, ordering only
        "clip_duration_s": 2.533,     # the clip's own length, from the sidecar
        "loop": True,                 # repeat the clip, or hold its last frame
        "loop_count": 3,              # cycles of a loop before it holds; None = endless
        "alt": "wave",                # optional: this one plays the ALT half
                                      # <kind>__<role>~<alt> (``set_alt``)
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

General Together actions never select a furniture marker. Only an exact
consented prop execution may supply a shared reserved anchor; free pair
capabilities meet at the participants' midpoint.
"""
import math
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

logger = get_logger(__name__)


def _narrate(anchor: str, key: str, *, literal: bool = False, **fmt) -> None:
    """Record a pair event in the anchor's language and room. Never raises.
    ``literal``: ``key`` is told as it is (a reaction line already written in
    the room's language), not translated or formatted."""
    try:
        from app.core.i18n import t
        from app.core.perception import (STORYTELLER_SPEAKER, VOLUME_NORMAL,
                                         record_utterance)
        from app.core.pose_catalog import pose_label
        from app.models.character import (get_character_current_location,
                                          get_character_current_room,
                                          get_character_language)
        if literal:
            content = key
        else:
            lang = get_character_language(anchor)
            pose_key = fmt.pop("pose_key")
            content = t(key, lang).format(**fmt, pose=pose_label(pose_key, lang))
        record_utterance(
            speaker=STORYTELLER_SPEAKER,
            content=content,
            volume=VOLUME_NORMAL,
            location_id=get_character_current_location(anchor) or "",
            room_id=get_character_current_room(anchor) or "",
            source="interaction", anchor=anchor)
    except Exception as e:
        logger.debug("interaction narration failed: %s", e)


class StaleDecision(ValueError):
    """A character turn that began BEFORE the pair started tried to end it.

    The turn's prompt showed the character alone; its pose or journey answers
    a world that no longer exists, and ending the pair for it is what cut
    pairs off half a minute in. A turn that began after the start saw the
    pair and may end it.
    """


def stale_against_pair(character_name: str,
                       profile: Optional[Dict[str, Any]] = None) -> str:
    """The refusal sentence when the running character turn predates the
    pair ``character_name`` is in, else "".

    Only a character turn has a decision start
    (``turn_trace.decision_started_at``); a player request or a ticker never
    is stale. An interaction without a system start stamp is not protected.
    """
    from app.core.turn_trace import decision_started_at
    decided = decision_started_at()
    if not decided:
        return ""
    inter = get_interaction(character_name, profile)
    started = str((inter or {}).get("started_at_sys") or "")
    if not started or started <= decided:
        return ""
    from app.core.pose_catalog import pose_label
    return (f"{character_name} began {pose_label(inter['pose_key'], 'en')} with "
            f"{join_names(others_of(inter, character_name))} after this decision was made; "
            f"that keeps going. "
            f"Do not change {character_name}'s activity or leave in this turn.")


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
    """Both partners' profile locks — :func:`profile_locks` for two names."""
    with profile_locks(a, b):
        yield


@contextmanager
def profile_locks(*names: str):
    """Every named character's profile lock, ALWAYS in sorted-name order.

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
    from contextlib import ExitStack
    from app.core.keyed_lock import keyed_lock
    with ExitStack() as stack:
        for name in sorted(str(n or "") for n in names):
            stack.enter_context(keyed_lock("character_profile", name))
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
    if not all(inter.get(k) for k in ("id", "kind", "role", "started_at_game")):
        return None
    members = inter.get("members")
    if not isinstance(members, dict) or members.get(inter["role"]) != character_name \
            or len(members) < 2:
        return None
    return inter


def members_of(inter: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """``{role: name}`` of an interaction blob, in role order (a..e)."""
    members = (inter or {}).get("members")
    if not isinstance(members, dict):
        return {}
    return {role: str(members[role]) for role in sorted(members) if members.get(role)}


def others_of(inter: Optional[Dict[str, Any]], name: str) -> List[str]:
    """Everyone in the interaction but ``name``, in role order."""
    return [n for n in members_of(inter).values() if n != name]


def partner_of(inter: Optional[Dict[str, Any]], name: str) -> str:
    """The other one of a PAIR ("" when there is none). Group-aware callers
    use :func:`others_of`."""
    others = others_of(inter, name)
    return others[0] if others else ""


def join_names(names: List[str]) -> str:
    """"A", "A and B", "A, B and C" — the English list a prompt reads."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def migrate_members_once() -> int:
    """Boot migration (2026-11-03, plan-gruppen-animationen.md G2b): the
    profile's ``interaction.partner`` becomes ``interaction.members`` ``{role:
    name}`` — the own role plus the partner on the other half of the pair.
    A ``last_interaction_result`` still naming a ``partner`` carries no role
    to rebuild it from; it is bookkeeping of an end already past and is
    dropped. Only profiles still in the old shape are written, so it runs
    once in effect. Returns the profiles rewritten."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (get_character_profile, list_available_characters,
                                      save_character_profile)
    changed = 0
    for name in list_available_characters(include_pooled=True):
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            inter = profile.get("interaction")
            result = profile.get("last_interaction_result")
            touched = False
            if isinstance(inter, dict) and "partner" in inter:
                role = inter.get("role")
                other = "b" if role == "a" else "a"
                partner = inter.pop("partner")
                if role in ("a", "b") and partner:
                    inter["members"] = dict(sorted({role: name, other: str(partner)}.items()))
                touched = True
            if isinstance(result, dict) and "partner" in result:
                profile.pop("last_interaction_result", None)
                touched = True
            if touched:
                if save_character_profile(name, profile):
                    changed += 1
                else:
                    logger.warning("interaction members migration: %s not saved", name)
    return changed


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
        "members": members_of(inter),
        "anchor": dict(inter.get("anchor") or {}),
        "started_at_game": inter["started_at_game"],
        "elapsed_s": st["elapsed_s"],
        # the clip's own length and whether it cycles — a looping clip is
        # replayed (phase mod clip length), a one-shot holds its last frame
        "clip_duration_s": float(inter.get("clip_duration_s") or 0.0),
        "loop": bool(inter.get("loop")),
        # how many cycles the loop plays before it holds its last frame;
        # None = endless (always None for a one-shot)
        "loop_count": inter.get("loop_count") if inter.get("loop") else None,
        "rate": round(float(rate or 0.0), 4),
        # the ALT half this one plays instead of its role's own ("" = none):
        # the clip is <kind>__<role>~<alt>, same anchor, same phase (§ A8a)
        "alt": str(inter.get("alt") or ""),
    }


def alt_choices(character_name: str,
                profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """What ``character_name`` may play instead of its role's own half in
    its running interaction: ``{current, options: [{id, label}]}``, the
    first option ``""`` = the role's own half. None without an interaction
    or without an alt for its role."""
    from app.core.animation_clips import alt_label, clip_alts
    inter = get_interaction(character_name, profile)
    if not inter:
        return None
    alts = clip_alts(inter["kind"]).get(inter["role"]) or []
    if not alts:
        return None
    return {"current": str(inter.get("alt") or ""),
            "options": [{"id": "", "label": "Default"}]
                       + [{"id": a, "label": alt_label(a)} for a in alts]}


def alt_point(meta: Dict[str, Any], role: str, alt: str = "") -> Optional[Tuple[float, float]]:
    """The clip-frame root (metres) of ``role`` at the anchor frame — of its
    ALT half when ``alt`` names one the sidecar measured, else of the role's
    own half. None without geometry."""
    geometry = meta.get("geometry") or {}
    off = None
    if alt:
        off = ((geometry.get("alts") or {}).get(f"{role}~{alt}") or {}).get("anchor_xz_m")
    if not off:
        off = ((geometry.get("roles") or {}).get(role) or {}).get("anchor_xz_m")
    return (float(off[0]), float(off[1])) if off else None


def set_alt(character_name: str, alt: str) -> Dict[str, Any]:
    """``character_name`` plays the ALT half ``alt`` of its role from now on
    (``""`` = back to the role's own half) — ``{ok, reason}``. Its game-state
    position moves to the alt's root at the anchor, so perception, rules and
    the map see it where the clip shows it. Everyone else in the
    interaction is untouched. Refused: no interaction (``not_interacting``),
    an alt the role does not have as a file (``unknown_alt``)."""
    from app.core.animation_clips import clip_alts, clip_meta
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (_write_character_pos, get_character_current_location,
                                      get_character_profile, save_character_profile)
    alt = str(alt or "").strip().lower()
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        inter = get_interaction(character_name, profile)
        if not inter:
            return {"ok": False, "reason": "not_interacting"}
        if alt and alt not in (clip_alts(inter["kind"]).get(inter["role"]) or []):
            return {"ok": False, "reason": "unknown_alt"}
        if str(inter.get("alt") or "") == alt:
            return {"ok": True, "reason": ""}
        if alt:
            inter["alt"] = alt
        else:
            inter.pop("alt", None)
        if not save_character_profile(character_name, profile):
            return {"ok": False, "reason": "not_saved"}
        anchor = inter.get("anchor") or {}
        point = alt_point(clip_meta(inter["kind"]) or {}, inter["role"], alt)
        if point and anchor.get("x") is not None:
            dx, dz = _rotate(point[0], point[1], float(anchor.get("yaw") or 0.0))
            _write_character_pos(character_name, round(float(anchor["x"]) + dx, 3),
                                 round(float(anchor["z"]) + dz, 3))
    from app.core import sync_topics
    sync_topics.changed_at(character_name, get_character_current_location(character_name) or "")
    logger.info("interaction %s: %s plays %s", inter["id"], character_name,
                f"the alt '{alt}' of role {inter['role']}" if alt else f"role {inter['role']} again")
    return {"ok": True, "reason": ""}


# ------------------------------------------------------------------ kinds

def pair_kind_for_pose(pose_key: str,
                       complete_pairs: Optional[Iterable[str]] = None) -> str:
    """The pair or group clip kind a catalog pose names — "" when the pose is
    a solo one or its clip is not complete with one role per participant of
    the pose (a pair a/b, a group of three a/b/c). ``complete_pairs`` lets a
    caller that asks for many poses pass ``pair_kinds()`` once instead of
    having it recomputed per pose — that answer knows pairs only."""
    from app.core.animation_clips import role_counts
    from app.core.expression_pose_maps import is_partner_activity, resolve_pose_animation
    from app.core.pose_catalog import get_catalog
    if not pose_key or not is_partner_activity(pose_key):
        return ""
    kind = resolve_pose_animation(pose_key)
    if complete_pairs is not None:
        return kind if kind in complete_pairs else ""
    people = get_catalog("pose")[pose_key.strip().lower()].get("participants", 1)
    return kind if role_counts().get(kind) == people else ""


def partner_poses() -> List[Tuple[str, str]]:
    """Free ``(pose_key, pair_kind)`` capabilities; props own bound actions."""
    from app.core.animation_clips import pair_kinds
    from app.core.pose_catalog import get_catalog, group_of, needs_place
    complete = set(pair_kinds())
    out = []
    for key in get_catalog("pose"):
        kind = pair_kind_for_pose(key, complete)
        if kind and not needs_place(group_of(key)):
            out.append((key, kind))
    return out


# ------------------------------------------------------------------ pairing

def check_can_pair(actor: str, partner: str, pose_key: str = "") -> str:
    """Why ``actor`` and ``partner`` cannot pair up right now — "" when they
    can. The checks that do NOT depend on a pose or on the exact metres:
    two different, awake, present, unoccupied characters in one room.
    With ``pose_key`` the packages are asked as well whether THIS pose may
    happen here and now (``participation.check``, kind ``"pose"`` — e.g.
    not in front of others); their English message is the reason.

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
        room = get_character_current_room(actor) or ""
        if room != (get_character_current_room(partner) or ""):
            return f"{partner} is in another room"
        return _pose_participation(actor, partner, pose_key, loc_a, room)
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
    return _pose_participation(actor, partner, pose_key, "", "")


def _pose_participation(actor: str, partner: str, pose_key: str,
                        location_id: str, room_id: str) -> str:
    """The package verdict on one free pair pose ("" = allowed, or no pose)."""
    if not pose_key:
        return ""
    from app.core import participation
    refused = participation.check("pose", pose_key.strip().lower(), [actor, partner],
                                  location_id, room_id)
    return refused.get("message", "")


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


#: A partner this close to its point in the clip steps in at once; farther
#: and it walks over first (a pair beside a player's avatar).
_STEP_IN_M = 0.3


def held_participant(a: str, b: str) -> str:
    """The one of the two who stays where it stands: a player's avatar beside
    a character that is not one — the NPC comes to the player. "" for two
    NPCs or two avatars (then they meet halfway)."""
    from app.models.account import is_player_controlled
    av_a, av_b = is_player_controlled(a), is_player_controlled(b)
    return a if av_a and not av_b else b if av_b and not av_a else ""


def walker_of(invitation: Dict[str, Any]) -> str:
    """Who walks over for an accepted invitation: the one who said yes —
    unless that is the held avatar (``held_participant``), then the other."""
    inviter, invitee = invitation["inviter"], invitation["invitee"]
    return inviter if held_participant(inviter, invitee) == invitee else invitee


def _role_start(meta: Dict[str, Any], role: str) -> Optional[Tuple[float, float]]:
    """Where the clip half stands in its FIRST frame (clip metres), falling
    back to its anchor-moment point for a sidecar without ``start_xz_m``."""
    r = ((meta.get("geometry") or {}).get("roles") or {}).get(role) or {}
    point = r.get("start_xz_m") or r.get("anchor_xz_m")
    return (float(point[0]), float(point[1])) if point else None


def _held_frame(held: str, who_a: str, who_b: str, meta: Dict[str, Any],
                pos: Dict[str, Dict[str, float]]):
    """``(anchor {x, z, yaw}, first-frame points {name: (x, z)})`` of a pair
    laid around ``held``: +X still runs from the A figure towards the B
    figure, and the clip frame is shifted so that ``held``'s first frame
    lands exactly on its own point — it does not move, the other one comes.
    None without role geometry."""
    starts = {who_a: _role_start(meta, "a"), who_b: _role_start(meta, "b")}
    if None in starts.values():
        return None
    pa, pb = pos[who_a], pos[who_b]
    span = math.dist((pa["x"], pa["z"]), (pb["x"], pb["z"]))
    yaw = _yaw_from_to(pa["x"], pa["z"], pb["x"], pb["z"]) if span > 1e-6 else 0.0
    hx, hz = _rotate(*starts[held], yaw)
    ax, az = pos[held]["x"] - hx, pos[held]["z"] - hz
    points = {}
    for name, start in starts.items():
        dx, dz = _rotate(*start, yaw)
        points[name] = (ax + dx, az + dz)
    return {"x": ax, "z": az, "yaw": yaw}, points


def role_point(place: dict, pose_key: str, clip_role: str) -> Tuple[float, float]:
    """Where clip role ``a``..``e`` of the pose's pair or group clip stands on
    ``place``: the place centre plus the role's sidecar ``anchor_xz_m`` turned
    by ``places.pair_yaw`` — the point both renderers draw it at
    (``pairPoints``). Raises ``ValueError("pair_geometry_missing")``."""
    from app.core.animation_clips import clip_meta
    from app.core import places
    meta = clip_meta(pair_kind_for_pose(pose_key)) or {}
    offset = ((((meta.get("geometry") or {}).get("roles") or {}).get(clip_role) or {})
              .get("anchor_xz_m"))
    if not offset:
        raise ValueError("pair_geometry_missing")
    cx, cz = places.centre_of(place)
    dx, dz = _rotate(float(offset[0]), float(offset[1]), places.pair_yaw(place, pose_key))
    return cx + dx, cz + dz


def group_roles(names: List[str], profiles: Dict[str, Dict[str, Any]],
                meta: Dict[str, Any]) -> Dict[str, str]:
    """``{clip role: name}`` — who plays which role of a pair or group clip.
    ``names``: the initiator first, then the invitees in invitation order.

    A pair keeps :func:`assign_roles`, which never refuses. A group follows
    the clip's ``role_gender``: each person of a gender the clip names takes
    the first free role of that gender, in invitation order (a tie goes to
    whoever was asked first); everyone else (no gender, or one the clip does
    not name) then takes the first free role. Without a gender assignment the
    roles go in invitation order, the initiator plays A. A group may be
    smaller than its clip (``prop_action_engine.GROUP_MIN_PEOPLE`` up to the
    role count): the roles nobody takes stay EMPTY and are left out of the
    result, which lists the taken roles in clip order. Raises
    ``ValueError("roles_unfit")`` when the clip has fewer roles than people,
    or a person finds no free role of their gender (three women for two
    female roles)."""
    from app.core.animation_clips import _meta_roles, clip_role_gender
    gender = clip_role_gender(meta)

    def sex(name):
        return str((profiles.get(name) or {}).get("gender") or "").strip().lower()
    if len(names) == 2:
        a, b = assign_roles(names[0], names[1], sex(names[0]), sex(names[1]), gender)
        return {"a": a, "b": b}
    roles = _meta_roles(meta)
    if len(roles) < len(names):
        raise ValueError("roles_unfit")
    if not gender:
        return dict(zip(roles, names))
    taken: Dict[str, str] = {}
    for name in names:
        if sex(name) in gender.values():
            role = next((r for r in roles if r not in taken and gender[r] == sex(name)), None)
            if role is None:
                raise ValueError("roles_unfit")
            taken[role] = name
    rest = [n for n in names if n not in taken.values()]
    for role in roles:
        if not rest:
            break
        if role not in taken:
            taken[role] = rest.pop(0)
    return {role: taken[role] for role in roles if role in taken}


def shared_slot(place: dict) -> int:
    """The ONE slot a pair whose pose shares a place (catalog ``places`` 1)
    holds: the slot nearest the place centre — the marker itself on a single
    seat, the middle of a row; a tie takes the lower index."""
    from app.core import places
    centre = places.centre_of(place)
    return min(range(len(place["slots"])),
               key=lambda i: (math.dist(place["slots"][i], centre), i))


def plan_interaction_at(names: List[str], pose_key: str, place: dict, *, profiles=None) -> dict:
    """Shared clip-role allocation BEFORE a prop owner claims access/slots.

    ``names``: the initiator first, then the invitees in invitation order;
    roles by :func:`group_roles` — only the TAKEN roles of a group smaller
    than its clip get a slot or point. Everything is keyed by NAME: ``slots``,
    ``points`` and ``access_roles`` — the marker access of clip role A is
    ``actor``, of every other role ``partner``. Semantic initiator/invitee
    identities stay with the run, including effect targets.

    A pose with ``places`` > 1 needs one slot per role, each within 5 cm of
    its role point. A pose with ``places`` 1 shares a place: every role holds
    :func:`shared_slot` and enters at its own role point, returned under
    ``points`` (location metres) — the slot position would put them all on
    one spot.
    """
    from app.core.animation_clips import clip_meta
    from app.core.pose_catalog import pose_places
    from app.models.character import get_character_profile
    meta = clip_meta(pair_kind_for_pose(pose_key)) or {}
    profiles = profiles if profiles is not None else {n: get_character_profile(n) for n in names}
    clip_roles = group_roles(list(names), profiles, meta)
    shared = pose_places(pose_key) == 1
    slots, access_roles, points = {}, {}, {}
    for clip_role, name in clip_roles.items():
        point = role_point(place, pose_key, clip_role)
        access_roles[name] = "actor" if clip_role == "a" else "partner"
        if shared:
            points[name] = [point[0], point[1]]
            continue
        matches = [i for i, p in enumerate(place["slots"]) if math.dist(p, point) <= .05]
        if len(matches) != 1:
            raise ValueError("pair_geometry_marker_mismatch")
        slots[name] = matches[0]
    if shared:
        slot = shared_slot(place)
        return dict(clip_roles=clip_roles, access_roles=access_roles,
                    slots={name: slot for name in names}, points=points)
    if len(set(slots.values())) != len(names):
        raise ValueError("pair_geometry_marker_mismatch")
    return dict(clip_roles=clip_roles, access_roles=access_roles, slots=slots)


def start_interaction_at(names: List[str], pose_key: str, *, execution_id: str,
                         plans: dict, commit_profiles) -> Dict[str, Any]:
    """Real shared pair or group entry at an executor's exact jointly
    claimed marker; ``names`` the initiator first, then the invitees.

    No invitation/automatic seat search: the prop run already owns consent,
    every approach and the measured entry. Re-read its durable authority
    here, check each role point against its plan, then write every member's
    profile through ``commit_profiles`` under the sorted profile locks.
    """
    from app.core import places, prop_action_store as runs
    from app.core.animation_clips import clip_loop_count, clip_loops, clip_meta
    from app.core.pose_catalog import pose_places
    from app.core.state_events import publish
    from app.models.character import (get_character_current_location,
                                      get_character_pos, get_character_profile)
    names = list(names)
    run = runs.get(execution_id)
    if (not run or run["status"] != "approaching" or run["phase"] != "entry"
            or runs.people(run) != names or run["definition"]["pose_key"] != pose_key
            or run["data"]["plans"] != plans or not run["data"].get("consented")):
        raise ValueError("pair_execution_mismatch")
    for name in names:
        anchor = plans[name]["entry_anchor"]
        if (runs.held(runs.person_key(name)) != execution_id or
                runs.held(runs.slot_key(run["target"], anchor["marker_id"], anchor["slot"])) != execution_id):
            raise ValueError("pair_claim_lost")
    kind = pair_kind_for_pose(pose_key)
    if not kind:
        raise ValueError(f"'{pose_key}' has no pair animation")
    meta = clip_meta(kind) or {}
    clip_duration = float(meta.get("duration_s") or 0.0)
    if clip_duration <= 0:
        raise ValueError(f"pair clip '{kind}' has no sidecar duration")
    loop = clip_loops(meta)
    loop_count = clip_loop_count(meta)
    # The pose-independent side of "can they pair up"; the run asked its
    # furniture presence rule itself, so no pose goes to the packages here.
    for other in names[1:]:
        blocked = check_can_pair(names[0], other, "")
        if blocked:
            raise ValueError(blocked)
    profiles = {n: get_character_profile(n) or {} for n in names}
    clip_roles = run["data"]["clip_roles"]
    try:
        roles_now = group_roles(names, profiles, meta)
    except ValueError:
        roles_now = {}
    if roles_now != clip_roles:
        raise ValueError("pair_roles_changed")
    anchors = [plans[n]["entry_anchor"] for n in names]
    first = anchors[0]
    # Distinct seats for a pose over several places; ONE shared seat otherwise.
    if (any(a["place_id"] != first["place_id"] for a in anchors)
            or len({a["slot"] for a in anchors}) != (1 if pose_places(pose_key) == 1 else len(names))):
        raise ValueError("pair_marker_mismatch")
    loc = get_character_current_location(names[0]) or ""
    place = next((p for p in places._compose(loc).get(first["room_id"], [])
                  if p["id"] == first["place_id"] and p.get("variant_uid") == first["variant_uid"]), None)
    if place is None:
        raise ValueError("pair_marker_lost")
    yaw = places.pair_yaw(place, pose_key)
    ax, az = places.centre_of(place)
    anchor = {"x": round(ax, 3), "z": round(az, 3), "yaw": round(yaw, 4), "place_id": place["id"]}
    roles_geometry = (meta.get("geometry") or {}).get("roles") or {}
    for role, name in clip_roles.items():
        plan = plans[name]
        point = plan["entry_anchor"]
        off = (roles_geometry.get(role) or {}).get("anchor_xz_m")
        if not off:
            raise ValueError("pair_geometry_missing")
        dx, dz = _rotate(float(off[0]), float(off[1]), yaw)
        if math.dist((ax + dx, az + dz), (point["x"], point["z"])) > .05:
            raise ValueError("pair_geometry_marker_mismatch")
        current = get_character_pos(name)
        access = plan["access"]
        if not current or math.dist((current["x"], current["z"]), (access["x"], access["z"])) > .05:
            raise ValueError("pair_access_lost")
    inter_id = uuid.uuid4().hex[:12]
    started = game_time().canonical()
    from app.core.timeutils import utc_now_iso
    started_sys = utc_now_iso("microseconds")
    runtime = {}
    # EVERY member's blob in ONE locked span, in sorted-name order (DATA-3).
    with profile_locks(*names):
        for role, name in clip_roles.items():
            point = plans[name]["entry_anchor"]
            interaction = {
                "id": inter_id, "kind": kind, "role": role, "members": dict(clip_roles),
                "pose_key": pose_key, "anchor": anchor,
                "started_at_game": started, "started_at_sys": started_sys,
                "clip_duration_s": round(clip_duration, 3), "loop": loop,
                "loop_count": loop_count,
                "execution_ref": execution_id, "execution_kind": "prop_action",
            }
            runtime[name] = dict(interaction=interaction,
                                 place=dict(id=point["place_id"], slot=point["slot"],
                                            room_id=point["room_id"], execution_id=execution_id),
                                 pose_key=pose_key, pose_flavor="", prop_action_entry=None,
                                 pos_x=point["x"], pos_z=point["z"], pos_session=None, pos_seq=None)
        commit_profiles(runtime)
    publish("interaction_started", names[0], members=dict(clip_roles), kind=kind,
            interaction_id=inter_id, clip_duration_s=clip_duration)
    from app.core import sync_topics
    sync_topics.changed_at(names[0], loc)
    # "A and B start …"; a group reads "A, B and C start …" off the same line.
    _narrate(names[0], "{actor} and {partner} start {pose}.",
             actor=", ".join(names[:-1]), partner=names[-1], pose_key=pose_key)
    logger.info("interaction %s: %s play '%s' (%.1fs %s)", inter_id,
                ", ".join(f"{n} ({r})" for r, n in clip_roles.items()), kind, clip_duration,
                "cycle" if loop else "one-shot")
    return runtime[names[0]]["interaction"]


def start_interaction(actor: str, partner: str, pose_key: str, *,
                      invite_id: str = "", arrived: bool = False) -> Dict[str, Any]:
    """Binds ``actor`` (the initiator) and ``partner`` to the pair clip the
    pose names. Who plays which half follows the clip's gender assignment
    (``assign_roles``); without one the actor plays A. Raises ``ValueError``
    with a reason a tool result can relay. A supplied ``invite_id`` is stored
    with both halves before the pair locks are released.

    Beside a player's avatar (``held_participant``) the pair is laid around
    the avatar, which is neither moved nor written; the other one must stand
    within ``_STEP_IN_M`` of its first-frame point, else ``TooFarApart`` sends
    it over. ``arrived`` (the approach just ended) binds without that check:
    the walker steps the last bit in."""
    from app.core.animation_clips import (clip_loop_count, clip_loops, clip_meta,
                                          clip_role_gender)
    from app.core.state_events import publish
    from app.models.character import (get_character_current_location,
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
    loop_count = clip_loop_count(meta)

    # The pose-independent side of "can these two pair up" — one definition,
    # asked here and by the invitation. Checked AFTER the clip: a pose with no
    # pair animation is the more useful answer than "he is asleep".
    blocked = check_can_pair(actor, partner, pose_key)
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

    # Furniture is exclusively an exact prop action capability
    # (``start_interaction_at``). General invitations cannot choose a marker
    # or bypass its action requirements.
    from app.core.pose_catalog import group_of, needs_place
    if needs_place(group_of(pose_key)):
        raise ValueError("This pair action requires an explicit prop action.")
    held = held_participant(actor, partner)
    frame = _held_frame(held, who_a, who_b, meta, {actor: pa, partner: pb}) if held else None
    if frame:
        laid, points = frame
        other = partner if held == actor else actor
        here = pa if other == actor else pb
        gap = math.dist((here["x"], here["z"]), points[other])
        if gap > _STEP_IN_M and not arrived:
            raise TooFarApart(f"{other} has to come over to {held} first ({gap:.1f} m)")
        yaw = laid["yaw"]
        anchor = {"x": round(laid["x"], 3), "z": round(laid["z"], 3),
                  "yaw": round(yaw, 4), "place_id": None}
    else:
        held = ""
        p_a, p_b = (pa, pb) if who_a == actor else (pb, pa)
        yaw = _yaw_from_to(p_a["x"], p_a["z"], p_b["x"], p_b["z"]) if dist > 1e-6 else 0.0
        anchor = {"x": round((pa["x"] + pb["x"]) / 2, 3),
                  "z": round((pa["z"] + pb["z"]) / 2, 3), "yaw": round(yaw, 4),
                  "place_id": None}
    inter_id = uuid.uuid4().hex[:12]
    started = game_time().canonical()
    from app.core.timeutils import utc_now_iso
    started_sys = utc_now_iso("microseconds")
    roles = (meta.get("geometry") or {}).get("roles") or {}
    halves = ((who_a, "a", who_b), (who_b, "b", who_a))
    # BOTH interaction blobs in ONE locked span, in sorted-name order
    # (DATA-3): each save rewrites a whole profile_json, so a concurrent
    # equip on either partner would otherwise be dropped — and the pair must
    # not be half-written, or the other half sees a partner that is not bound.
    stored = True
    with pair_profile_locks(who_a, who_b):
        for name, role, other in halves:
            prof = profiles[name] = get_character_profile(name) or {}
            prof["interaction"] = {
                "id": inter_id, "kind": kind, "role": role, "members": {"a": who_a, "b": who_b},
                "pose_key": pose_key, "anchor": anchor,
                "started_at_game": started, "started_at_sys": started_sys,
                "clip_duration_s": round(clip_duration, 3), "loop": loop,
                "loop_count": loop_count,
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
        off = (roles.get(role) or {}).get("anchor_xz_m")
        if off and name != held:
            # The held avatar stays exactly where its player put it.
            dx, dz = _rotate(float(off[0]), float(off[1]), yaw)
            set_character_pos(name, anchor["x"] + dx, anchor["z"] + dz,
                              preserve_movement_target=True)
        set_pose_intent(name, pose_key)
    publish("interaction_started", actor, members={"a": who_a, "b": who_b}, kind=kind,
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
    if not stored:
        raise ValueError("pair_profile_write_failed")
    return profiles[actor]["interaction"]


def end_interaction(character_name: str, reason: str = "ended", *,
                    interaction_id: str = "", keep_places: Iterable[str] = ()) -> bool:
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
    ``keep_places`` (furniture pairs): names whose place the ending run keeps
    for their follow pose (``prop_action_engine._follow_up``) — not released.
    """
    from app.core.pose_catalog import follow_pose_for
    from app.core.room_stand import stand_up
    from app.core.state_events import publish
    from app.models.character import (clear_pose_intent, get_character_profile,
                                      save_character_profile)
    inter = get_interaction(character_name)
    if not inter or (interaction_id and inter["id"] != interaction_id):
        return False
    members = members_of(inter)
    # Everyone in clip-role order (a first): the narration and the hook list.
    names = list(dict.fromkeys(members[role] for role in sorted(members)))
    # EVERY profile under its lock, in sorted-name order (DATA-3). The
    # standing-up that follows is collected here and run AFTERWARDS:
    # ``clear_pose_intent`` and ``room_stand.stand_up`` write the profile
    # themselves and reach the places-lock, which comes BEFORE
    # ``character_profile`` in the documented order — doing them inside would
    # invert it.
    stand: list = []
    cleared = True
    saved_names: list[str] = []
    ended_invite_id = ""
    location_id = room_id = ""
    with profile_locks(*names):
        for name in names:
            p = get_character_profile(name) or {}
            if name == character_name:
                location_id = p.get("current_location") or ""
                room_id = p.get("current_room") or ""
            cur = p.get("interaction")
            if interaction_id and name == character_name and not (
                    isinstance(cur, dict) and cur.get("id") == interaction_id
                    and members_of(cur) == members):
                return False
            if not (isinstance(cur, dict) and cur.get("id") == inter["id"]):
                continue
            if not ended_invite_id:
                ended_invite_id = str(cur.get("invite_id") or "")
            p.pop("interaction", None)
            p["last_interaction_result"] = dict(
                interaction_id=cur["id"], invite_id=cur.get("invite_id", ""),
                members=members_of(cur), pose_key=cur["pose_key"], reason=reason,
                started_at_game=cur["started_at_game"], ended_at_game=game_time().canonical())
            same_pose = (p.get("pose_key") or "") == inter.get("pose_key")
            follow = (follow_pose_for(cur["pose_key"], cur.get("role", ""))
                      if reason in FOLLOW_REASONS and same_pose and cur.get("execution_kind") != "prop_action"
                      else "")
            seat = p.get("place") if isinstance(p.get("place"), dict) else None
            if not same_pose or follow:
                # The pair seat goes with the interaction; with the pair pose
                # still on, clear_pose_intent below stands the character up —
                # unless it takes its follow pose (_take_follow) from here.
                p["place"] = None
            if save_character_profile(name, p):
                saved_names.append(name)
            else:
                cleared = False
            stand.append((name, same_pose, follow, seat))
    if inter.get("execution_kind") == "prop_action":
        keep = set(keep_places)
        from app.core.keyed_lock import _after_locks
        def owned_ended():
            from app.models.character import release_prop_action_state
            for name, *_rest in stand:
                if name not in keep:
                    release_prop_action_state(name, inter["execution_ref"])
            from app.core.prop_action_engine import interrupt_after_locks
            interrupt_after_locks(character_name, "interaction_" + reason, execution_id=inter["execution_ref"])
        _after_locks(owned_ended)
    else:
        # Who stands up goes first: a seat it still holds is free then for
        # the other's follow pose.
        for name, same_pose, follow, seat in sorted(stand, key=lambda row: bool(row[2])):
            if follow and _take_follow(name, follow, seat, inter["pose_key"]):
                continue
            if same_pose and not follow:
                clear_pose_intent(name)
            elif follow:
                clear_pose_intent(name)
                stand_up(name, from_place=seat, from_pose_key=inter["pose_key"])
            else:
                stand_up(name)
    publish("interaction_ended", character_name, members=members,
            kind=inter["kind"], interaction_id=inter["id"], reason=reason)
    from app.core import sync_topics
    for name in saved_names:
        sync_topics.changed_at(name)
    if stand and cleared and len(names) >= 2:
        _narrate(character_name, "{actor} and {partner} stop {pose}.",
                 actor=", ".join(names[:-1]), partner=names[-1], pose_key=inter["pose_key"])
        _remember_together(names, character_name, inter, ended_invite_id, location_id, room_id, reason)
        from app.core.hooks import emit
        emit("interaction.ended", character=character_name, members=names,
             interaction_id=inter["id"], invite_id=ended_invite_id, reason=reason)
    logger.info("interaction %s ended (%s)", inter["id"], reason)
    return True


#: Endings after which a partner takes its follow pose (plan-folge-pose.md):
#: the avatar's "end" in the HUD, an NPC's own cancel, the default "ended".
#: A move, a new pose, sleep, a journey or a deletion is no normal end.
FOLLOW_REASONS = frozenset(("avatar", "cancelled", "ended"))


def _take_follow(name: str, follow: str, seat: Optional[Dict[str, Any]], pair_pose: str) -> bool:
    """Put ``name`` into its follow pose after a free pair: on the room place
    the pair held when the follow's place type matches (``prefer``), else on
    any free place of that type in the room. False = it got none (the pose
    needs a place and the room has no free one) — the caller stands it up."""
    from app.core import places
    from app.core.pose_catalog import group_of
    from app.models.character import set_pose_intent
    prefer = ""
    if seat:
        loc, room = places.where(name)
        held = next((p for p in places.room_places(loc, room) if p["id"] == seat.get("id")), None)
        if held and held.get("group") == group_of(follow) and held.get("source") != "prop":
            prefer = held["id"]
    try:
        taken = False
        if prefer:
            try:
                taken = bool(set_pose_intent(name, follow, prefer=prefer))
            except places.PlaceUnavailable:
                pass
        taken = taken or bool(set_pose_intent(name, follow))
    except Exception:
        logger.exception("follow pose %r for %s after %s failed", follow, name, pair_pose)
        return False
    if taken:
        _limit_follow(name, follow)
    return taken


def _limit_follow(name: str, follow: str) -> None:
    """An NPC gets up from its follow pose by itself after
    ``prop_action_engine.FOLLOW_NPC_LIMIT_S`` game seconds
    (:func:`expire_follow_poses`); the player's avatar stays until stopped."""
    from app.core.keyed_lock import keyed_lock
    from app.core.prop_action_engine import FOLLOW_NPC_LIMIT_S
    from app.models.account import get_all_avatars
    from app.models.character import get_character_profile, save_character_profile
    if name in set(get_all_avatars()):
        return
    until = (game_time() + GameDuration.of(seconds=FOLLOW_NPC_LIMIT_S)).canonical()
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        profile["follow_pose_until"] = dict(pose_key=follow, until_game=until)
        save_character_profile(name, profile)


def expire_follow_poses() -> int:
    """Periodic: clear the follow pose of every NPC whose time in it is up
    (:func:`_limit_follow`). A pose that changed meanwhile only drops the
    stale mark. Returns how many got up."""
    from app.core.db import get_connection
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (clear_pose_intent, get_character_profile,
                                      save_character_profile)
    now = game_time()
    ended = 0
    # One query for the whole cast — almost always nobody carries the mark.
    names = [row[0] for row in get_connection().execute(
        "SELECT name FROM characters WHERE json_extract(profile_json,'$.follow_pose_until') IS NOT NULL")]
    for name in names:
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            mark = profile.get("follow_pose_until")
            if not isinstance(mark, dict):
                continue
            current = (profile.get("pose_key") or "") == mark.get("pose_key")
            try:
                due = now >= GameTime.parse(str(mark.get("until_game") or ""))
            except ValueError:
                due = True
            if current and not due:
                continue
            profile.pop("follow_pose_until", None)
            save_character_profile(name, profile)
        if current:
            clear_pose_intent(name)
            ended += 1
    return ended


def _remember_together(names: List[str], character_name: str, inter: Dict[str, Any],
                       invite_id: str, location_id: str, room_id: str,
                       reason: str) -> None:
    """Everyone remembers the pair or group (``names``, clip-role order); each
    two of them count one relationship event, led by the inviter — without an
    invitation by ``character_name``, whose end it was.

    Runs once per really-ended interaction, outside every profile lock and
    BEFORE the ``interaction.ended`` hook. Never raises: a failed write must
    not keep the hook (party, packages) from hearing that it is over.
    """
    try:
        from app.core.i18n import t
        from app.core.pose_catalog import pose_label
        from app.models.character import get_character_language
        from app.models.memory import add_memory
        from app.models.relationship import record_interaction

        ended_at_game = game_time().canonical()
        extra_meta = {
            "interaction_id": inter["id"], "pose_key": inter["pose_key"],
            "location_id": location_id, "room_id": room_id,
            "started_at_game": inter.get("started_at_game", ""),
            "ended_at_game": ended_at_game, "reason": reason,
        }
        for name in names:
            others = [n for n in names if n != name]
            lang = get_character_language(name)
            add_memory(
                name, t("{pose} with {partner}.", lang).format(
                    pose=pose_label(inter["pose_key"], lang), partner=join_names(others)),
                memory_type="episodic", importance=3 if inter.get("loop") else 2,
                tags=["interaction"], related_character=others[0] if len(others) == 1 else "",
                game_ts=ended_at_game, extra_meta=extra_meta)
        invite = get_invite(invite_id) if invite_id else None
        first = invite["inviter"] if invite else character_name
        order = sorted(names, key=lambda n: n != first)
        for i, char_a in enumerate(order):
            for char_b in order[i + 1:]:
                record_interaction(
                    char_a=char_a, char_b=char_b, interaction_type="together",
                    summary=f"{char_a} and {char_b}: {inter['pose_key']}",
                    sentiment_delta_a=0.05, sentiment_delta_b=0.05, strength_delta=3)
    except Exception as e:
        logger.warning("remembering pair %s failed: %s", inter.get("id"), e)


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
            "pose_key": r[3], "created_at": r[4], "status": r[5], "reason": r[6],
            "consent": r[7] or "ask"}


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
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
                    and members_of(actor) == members_of(partner)
                    and set(members_of(actor).values()) == {inv["inviter"], inv["invitee"]}
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
        from app.core.keyed_lock import _after_locks
        _after_locks(lambda: emit("interaction.invited", invite_id=invite_id, inviter=inviter,
                                 invitee=invitee, pose_key=pose_key))
    except Exception as e:
        logger.debug("interaction.invited emit failed: %s", e)
    return invite_id


def get_invite(invite_id: str) -> Optional[Dict[str, Any]]:
    from app.core.db import get_connection
    if not invite_id:
        return None
    try:
        r = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
    """The open, fresh invitation ``inviter`` is waiting on — a question, or
    a pair started without asking whose reaction is still out
    (``reacting``) — so the UI can show "waiting for X…" with a way to take
    it back."""
    from app.core.db import get_connection
    inviter = (inviter or "").strip()
    if not inviter:
        return None
    try:
        r = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
            "FROM interaction_invites WHERE inviter=? AND status IN ('pending', 'reacting') "
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
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
    sql = ("SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
    if inv.get("consent") == "react":
        # Nobody was asked: the actor's own start fell through, not a yes.
        _narrate(inv["inviter"],
                 "{inviter} wanted to start {pose} with {invitee}, but it is not possible ({reason}).",
                 inviter=inv["inviter"], invitee=inv["invitee"],
                 pose_key=inv["pose_key"], reason=reason)
    else:
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
        "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
    return _accept_claimed(inv)


def _accept_claimed(inv: Dict[str, Any]) -> Dict[str, Any]:
    """A yes for the invitation this call has claimed (``answering``): start
    the pair, walk over when only the metres are missing, or fail it with its
    reason. The answer to an invitation and an unanswered or accepted react
    pair (:func:`react`) end here alike."""
    invite_id = inv["invite_id"]
    out = {k: v for k, v in inv.items() if k != "status"}
    blocked = check_can_pair(inv["inviter"], inv["invitee"], inv["pose_key"])
    if blocked:
        _fail_invite(inv, blocked)
        return {**out, "status": "cannot", "reason": blocked}
    try:
        inter = start_interaction(inv["inviter"], inv["invitee"], inv["pose_key"],
                                  invite_id=invite_id)
    except TooFarApart as e:
        # Yes was said; only the metres are missing. ``walker_of`` walks over
        # (the one who agreed, or the NPC beside a player's avatar), and the
        # ticker binds the pair when they get there. Saying "too far away" to
        # a player who has no way to close the gap would be a dead end.
        if _walk_to_partner(inv):
            if _set_invite_status(invite_id, "approaching"):
                return {**out, "status": "approaching", "reason": str(e)}
            from app.core.travel_engine import cancel_journey
            cancel_journey(walker_of(inv))
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


def _walk_to_partner(invitation: Dict[str, Any]) -> bool:
    """Send ``walker_of(invitation)`` over to the other one on the nav grid.
    True when a route was found and the journey is running.

    Beside a held avatar the goal is the walker's own first-frame point in
    the pair laid around the avatar (``_held_frame``), so the pair binds
    where the walk ends and the avatar never moves. Otherwise, or when that
    point has no route, it is a metre SHORT of the other one, on the
    walker's own side — the pair snaps to its anchor on arrival anyway.
    """
    from app.core.travel_engine import cancel_journey, start_journey_to_point
    from app.models.character import get_character_pos
    walker = walker_of(invitation)
    target = invitation["inviter"] if walker == invitation["invitee"] else invitation["invitee"]
    pw, pt = get_character_pos(walker), get_character_pos(target)
    if not pw or not pt:
        return False
    dx, dz = pw["x"] - pt["x"], pw["z"] - pt["z"]
    span = math.hypot(dx, dz)
    goals = []
    if held_participant(walker, target) == target:
        point = _held_goal(invitation, walker, target, pw, pt)
        if point and math.dist(point, (pw["x"], pw["z"])) > _STEP_IN_M:
            goals.append(point)
    if span > _APPROACH_GAP_M:
        goals.append((pt["x"] + dx / span * _APPROACH_GAP_M,
                      pt["z"] + dz / span * _APPROACH_GAP_M))
    if not goals:
        return False            # already there — the refusal was not distance
    # A trip already running is the one this replaces: the walker just agreed
    # to be somewhere else.
    cancel_journey(walker)
    reason = ""
    for gx, gz in goals:
        journey, reason = start_journey_to_point(walker, gx, gz)
        if journey:
            logger.info("%s walks over to %s for a pair interaction", walker, target)
            return True
    logger.info("%s cannot walk to %s (%s)", walker, target, reason)
    return False


def _held_goal(invitation, walker, target, pw, pt) -> Optional[Tuple[float, float]]:
    """The walker's first-frame point in the pair laid around ``target``."""
    from app.core.animation_clips import clip_meta, clip_role_gender
    from app.models.character import get_character_profile
    kind = pair_kind_for_pose(invitation["pose_key"])
    meta = (clip_meta(kind) or {}) if kind else {}
    if not meta:
        return None
    actor, partner = invitation["inviter"], invitation["invitee"]
    who_a, who_b = assign_roles(
        actor, partner, str((get_character_profile(actor) or {}).get("gender") or ""),
        str((get_character_profile(partner) or {}).get("gender") or ""), clip_role_gender(meta))
    frame = _held_frame(target, who_a, who_b, meta, {walker: pw, target: pt})
    return frame[1][walker] if frame else None


def settle_approaches() -> int:
    """Bind every pair whose walker has arrived; drop the ones that will not
    happen as failed with a saved reason, narration and hook. Called on the
    travel ticker's beat, right after the journeys.

    A row stays ``approaching`` while the journey runs — the consent is
    given, only the metres are still being covered. When the walking stops
    the pair is attempted once: it either starts, or the invitation is over
    (the other one moved on, fell asleep, sat down elsewhere). Retrying
    forever would leave a character walking after someone across the world.
    The same beat lets a react pair whose reaction never came go on
    (:func:`_settle_reactions`).
    """
    from app.core.db import get_connection
    from app.core.travel_engine import get_journey
    _settle_reactions()
    try:
        rows = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
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
            if get_journey(walker_of(inv)):
                continue                      # still on the way
            if not _claim_invite(inv["invite_id"], "approaching"):
                continue
            claimed = True
            inter = start_interaction(inv["inviter"], inv["invitee"], inv["pose_key"],
                                      invite_id=inv["invite_id"], arrived=True)
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


# ------------------------------------------------------ without asking

#: How a free pair begins — chosen by whoever proposes it, the same two ways
#: as a furniture pair run (``prop_action_engine.CONSENTS``): "ask" (an
#: invitation the partner answers) or "react" (:func:`start_without_asking`).
CONSENTS = ("ask", "react")


def start_without_asking(actor: str, partner: str, pose_key: str) -> Dict[str, Any]:
    """``actor`` starts the free pair pose ``pose_key`` with ``partner``
    WITHOUT asking — the free-pose twin of a furniture pair run requested
    with consent "react".

    No question is put: the row is recorded as ``reacting`` (no
    ``interaction.invited``, so nobody is woken to answer it) and the room
    hears "{actor} approaches {partner}: {pose}.". What happens next depends
    on the partner's reaction (``pair_reaction.request_state``):

    * ``player`` (a player-controlled partner) or ``none`` (no package
      answers ``pair_reaction``) — nothing waits, the pair is accepted at once
      (:func:`_accept_claimed`: it starts, or ``walker_of`` walks over); a
      player partner ends it with the ordinary Stop.
    * ``pending`` — the ``pair_reaction`` provider is asked and the pair
      WAITS for the answer before it binds, as a furniture run waits at the
      furniture: :func:`react` accepts (the same start or walk) or resists
      (the row ends ``declined`` / ``partner_resisted``, nothing ever ran).
      Unlike a furniture run the walk over starts only after the answer — a
      free pair has no place to walk to beforehand, its meeting point is laid
      when it binds. Without an answer after ``REACTION_WAIT_S`` (counted from
      the row's ``created_at``) :func:`settle_approaches` goes on as accepted.

    Returns resolve_invite's shape — ``started`` / ``approaching`` /
    ``cannot`` with its ``reason`` — or ``reacting`` while the reaction is
    out. The same pair asked again while its reaction is out is that row
    (a double click starts nothing twice).
    """
    from app.core import pair_reaction, sync_topics
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    actor, partner, pose_key = ((actor or "").strip(), (partner or "").strip(),
                                (pose_key or "").strip())
    if not actor or not partner or actor == partner or not pose_key:
        return {"status": "cannot", "reason": "an interaction needs two different characters"}
    blocked = check_can_pair(actor, partner, pose_key)
    if blocked:
        return {"status": "cannot", "reason": blocked}
    invite_id, waiting = "iinv_" + uuid.uuid4().hex[:10], ""
    try:
        with transaction() as conn:
            row = conn.execute(
                "SELECT invite_id, created_at FROM interaction_invites WHERE inviter=? "
                "AND invitee=? AND pose_key=? AND status='reacting' "
                "ORDER BY created_at DESC LIMIT 1", (actor, partner, pose_key)).fetchone()
            if row and pair_reaction.waited_s(row[1]) < pair_reaction.REACTION_WAIT_S:
                waiting = row[0]
            else:
                # Starting it takes the place of the actor's own open question.
                conn.execute(
                    "UPDATE interaction_invites SET status='cancelled' "
                    "WHERE inviter=? AND invitee=? AND status='pending'", (actor, partner))
                conn.execute(
                    "INSERT INTO interaction_invites (invite_id, inviter, invitee, "
                    "pose_key, created_at, status, consent) "
                    "VALUES (?, ?, ?, ?, ?, 'reacting', 'react')",
                    (invite_id, actor, partner, pose_key, utc_now_iso()))
    except Exception as e:
        logger.debug("start_without_asking failed: %s", e)
        return {"status": "cannot", "reason": "the action could not be started"}
    if waiting:
        return {"status": "reacting", "invite_id": waiting, "inviter": actor,
                "invitee": partner, "pose_key": pose_key}
    sync_topics.avatars([actor, partner], "presence")
    _narrate(actor, "{actor} approaches {partner}: {pose}.",
             actor=actor, partner=partner, pose_key=pose_key)
    state = pair_reaction.request_state(partner)["state"]
    logger.info("interaction %s: %s starts '%s' with %s without asking (reaction %s)",
                invite_id, actor, pose_key, partner, state)
    if state == "pending":
        pair_reaction.ask("interaction", invite_id, actor, partner)
        return {"status": "reacting", "invite_id": invite_id, "inviter": actor,
                "invitee": partner, "pose_key": pose_key}
    inv = get_invite(invite_id)
    if not inv or not _claim_invite(invite_id, "reacting"):
        # Taken back (or swept) in between: nothing starts.
        return {"status": "cannot", "invite_id": invite_id, "reason": "the action was called off"}
    return _accept_claimed(inv)


def react(partner: str, invite_id: str, accept: bool, *, line: str = "",
          feeling: int = 0, romantic: bool = False) -> Dict[str, Any]:
    """The partner's reaction to a free pair started without asking
    (:func:`start_without_asking`) — the same answer as
    ``prop_action_engine.react`` gives a furniture run.

    ``accept`` True starts the pair (or the walk over, :func:`_accept_claimed`);
    False ends it before it began: the row becomes ``declined`` with reason
    ``partner_resisted`` and the answer is ``resisted``. ``line`` is told to
    the room as it is; ``feeling`` (-2..2) and ``romantic`` are booked on the
    relationship (``pair_reaction.book``). A reaction for a row that no longer
    waits (taken back, timed out, already answered) changes nothing and
    answers ``not_waiting``; one by anybody but the partner is refused.
    """
    from app.core import pair_reaction, sync_topics
    from app.core.db import transaction
    from app.core.pose_catalog import pose_label
    if type(accept) is not bool:
        return {"status": "refused", "reason": "invalid_response"}
    feeling = pair_reaction.clamp_feeling(feeling)
    inv = get_invite(invite_id)
    if not inv or inv["invitee"] != partner:
        return {"status": "refused", "reason": "not_partner"}
    out = {k: v for k, v in inv.items() if k != "status"}
    if inv["status"] != "reacting" or not _claim_invite(invite_id, "reacting"):
        return {**out, "status": "not_waiting"}
    line = line.strip() if isinstance(line, str) else ""
    if line:
        _narrate(partner, line, literal=True)
    pair_reaction.book(inv["inviter"], partner, pose_label(inv["pose_key"], "en"),
                       accept, feeling, bool(romantic))
    logger.info("interaction %s: %s %s %s's '%s' (feeling %d)", invite_id, partner,
                "accepts" if accept else "resists", inv["inviter"], inv["pose_key"], feeling)
    if accept:
        return _accept_claimed(inv)
    with transaction() as conn:
        conn.execute(
            "UPDATE interaction_invites SET status='declined', reason='partner_resisted' "
            "WHERE invite_id=? AND status='answering'", (invite_id,))
    sync_topics.avatars([inv["inviter"], partner], "presence")
    return {**out, "status": "resisted", "reason": "partner_resisted"}


def _settle_reactions() -> int:
    """Go on as accepted with every react pair whose reaction has not come
    within ``REACTION_WAIT_S`` — a model that is down must not block every
    pair started without asking. Returns how many went on."""
    from app.core import pair_reaction
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT invite_id, inviter, invitee, pose_key, created_at, status, reason, consent "
            "FROM interaction_invites WHERE status='reacting'").fetchall()
    except Exception:
        return 0
    moved = 0
    for r in rows:
        inv = _invite_row(r)
        if pair_reaction.waited_s(inv["created_at"]) < pair_reaction.REACTION_WAIT_S:
            continue
        try:
            if not _claim_invite(inv["invite_id"], "reacting"):
                continue
            logger.info("interaction %s: no reaction from %s within %.0f s — goes on",
                        inv["invite_id"], inv["invitee"], pair_reaction.REACTION_WAIT_S)
            _accept_claimed(inv)
            moved += 1
        except Exception as e:          # one bad row must not stop the beat
            logger.debug("settling the reaction of %s failed: %s", inv.get("invite_id"), e)
    return moved


def cancel_invite(invite_id: str) -> bool:
    """Take back an invitation — before it is answered (a react pair: before
    the reaction came), or while the one who agreed is still walking over.
    True when there was one to take back.

    Calling off an approach also calls off the WALK: the trip existed only to
    make that pair possible, and leaving it running would march the character
    to a spot it has no reason to be at.
    """
    inv = get_invite(invite_id)
    if not inv or inv["status"] not in ("pending", "reacting", "approaching"):
        return False
    if not _set_invite_status(invite_id, "cancelled", expected_status=inv["status"]):
        return False
    if inv["status"] == "approaching":
        try:
            from app.core.travel_engine import cancel_journey
            cancel_journey(walker_of(inv))
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
                "WHERE status IN ('pending', 'reacting', 'approaching') AND (inviter=? OR invitee=?)",
                (c, c)).fetchall()
            conn.execute("UPDATE interaction_invites SET status='stale' "
                         "WHERE status IN ('pending', 'reacting', 'approaching') "
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
    others = join_names(others_of(inter, character_name))
    if not pose:
        return ""
    return f"{pose} with {others}" if others else pose
