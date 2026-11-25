"""Persistent exact-target prop actions shared by authenticated HTTP and tools.

Run locks are reentrant (travel cancellation can call back inside its guard).
Claims use SQLite, never actor-global locks. No owner callback runs under a
profile lock. Offline intervals pause execution; receipts recover actual Core
arrival writes, not inferred animation completion. Effects and lifecycle
progress share one transaction, with notifications strictly after commit.
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from threading import Lock, RLock
from weakref import WeakValueDictionary
import math
import threading
import operator
import time
import uuid

from app.core import prop_action_store as store, places, props, travel_engine as travel
from app.core.game_time import GameTime, GameDuration
from app.core import timeutils
from app.core.timeutils import game_time, game_speed_factor, utc_now
from app.core.keyed_lock import keyed_lock, _DeferredRLock
from app.core.log import get_logger
from app.core import pair_reaction, pose_scene
from app.core.pair_reaction import REACTION_WAIT_S
from app.models import character as C
from app.models.world import is_world_frozen

_PROCESS = uuid.uuid4().hex
_locks = WeakValueDictionary()
_locks_mutex = Lock()
_OPS = dict(lt=operator.lt, le=operator.le, eq=operator.eq, ge=operator.ge, gt=operator.gt)
_TARGET = ("location_id", "room_id", "placement_id", "variant_uid")
_INTERNAL_MUTATION = ContextVar("prop_action_owned_mutation", default=False)
logger = get_logger("prop_action_engine")



@contextmanager
def _internal_mutation():
    token = _INTERNAL_MUTATION.set(True)
    try:
        yield
    finally:
        _INTERNAL_MUTATION.reset(token)


def _lock(ref):
    with _locks_mutex:
        return _locks.setdefault(ref, RLock())


class RequestInProgress(Exception):
    """Another request of the same actor is still being admitted
    (``request_guard``); adapters answer it as the refusal
    ``request_in_progress``."""
    reason = "request_in_progress"


#: actor -> [owning thread ident, depth]: the actor's request in flight.
_actors_busy: dict = {}


@contextmanager
def _actor_slot(actor: str):
    """One request per actor at a time. A second one — another nonce, a second
    click while the first is still validating/planning — is refused at once
    (``RequestInProgress``) instead of running beside it and replacing its
    run; the thread already inside may nest."""
    me = threading.get_ident()
    with _locks_mutex:
        owner = _actors_busy.get(actor)
        if owner is not None and owner[0] != me:
            raise RequestInProgress(actor)
        if owner is None:
            owner = _actors_busy[actor] = [me, 0]
        owner[1] += 1
    try:
        yield
    finally:
        with _locks_mutex:
            owner[1] -= 1
            if owner[1] <= 0:
                _actors_busy.pop(actor, None)


@contextmanager
def request_guard(actor: str, request_id: str):
    """Serialize one actor/nonce's admission and adapter charge, and admit one
    request per actor at a time.

    The same nonce waits for its first use (a replay returns that result);
    another nonce of an actor with a request in flight raises
    ``RequestInProgress`` at once (the HTTP adapter's 409, like every other
    refusal). Weak lifetime bounds the caller-supplied key space. The existing
    deferred RLock keeps invitation/model callbacks outside the adapter's
    outer guard: the actor slot is released before the nonce guard, whose
    release runs them.
    """
    if not isinstance(actor, str) or not actor or not isinstance(request_id, str):
        yield
        return
    if not request_id:
        with _actor_slot(actor):
            yield
        return
    key = "request:" + store.encode([actor, request_id])
    with _locks_mutex:
        guard = _locks.get(key)
        if guard is None:
            guard = _DeferredRLock()
            _locks[key] = guard
    with guard:
        with _actor_slot(actor):
            yield


def _result(run):
    result = {"execution_id": run["execution_id"], "status": run["status"], "reason": run["reason"]}
    if run["data"].get("effect_results"):
        result["effects"] = run["data"]["effect_results"]
    return result


def _refused(reason, run=None):
    """A refusal; one for the clothes in the way of a contact clip (``contact_clothing.REASON``) also names who
    still wears what (``message`` for an LLM, ``blockers`` for a route to word for its player)."""
    out = dict(execution_id="", status="refused", reason=reason)
    if run is not None:
        out.update(_clothing_details(run, reason))
    return out


def _clothing_details(run, reason) -> dict:
    """``{message, blockers}`` of a run refused for the clothes in the way of its contact clip, else {}."""
    from app.core import contact_clothing
    if reason != contact_clothing.REASON or run["definition"].get("ability") != "pair":
        return {}
    refused = contact_clothing.refusal(run["definition"].get("pose_key") or "", store.people(run),
                                       roles=run["data"].get("clip_roles") or None)
    return {key: refused[key] for key in ("message", "blockers")} if refused else {}


def _members(run):
    """``[(semantic role, name)]``: the initiator ``actor``, then every
    invitee as ``partner`` (invitation order). The semantic role is what an
    effect, requirement or access override targets; who plays which clip
    role (a..e) is ``data.clip_roles``."""
    return [("actor", run["actor"])] + [("partner", name) for name in run["members"]]


def _targets(run, target):
    """The names an effect or requirement ``target`` reaches: ``actor``, every
    invitee (``partner``) or everyone (``both``)."""
    if target == "both":
        return store.people(run)
    return [run["actor"]] if target == "actor" else list(run["members"])


def _join(names):
    from app.core.interaction_engine import join_names
    return join_names(list(names))


#: How a run with others begins — chosen by whoever requests it: "ask"
#: (every invitee consents first) or "react" (a pair only: it starts at once,
#: the partner reacts and may resist).
CONSENTS = ("ask", "react")

#: How long an invitation waits for its answers: REAL seconds on the motion
#: clock (``timeutils.motion_time`` — the seconds the world has run unfrozen),
#: so the game-speed factor never shortens it and a frozen world (or a server
#: downtime) pauses it, as the game-time count before it did. The answers come
#: from models that take real time, not game time. A group gets
#: ``CONSENT_WINDOW_PER_EXTRA_INVITEE_S`` more for every invitee beyond the
#: first: the questions are answered one after another.
CONSENT_WINDOW_S = 300.0
CONSENT_WINDOW_PER_EXTRA_INVITEE_S = 120.0

#: A "yes" that arrives this many motion-clock seconds after its invitation
#: expired still reaches the inviter ("would have agreed"); later, nothing.
LATE_ANSWER_WINDOW_S = 600.0


def consent_window_s(run) -> float:
    """The motion-clock seconds ``run``'s invitation waits for its answers."""
    return CONSENT_WINDOW_S + CONSENT_WINDOW_PER_EXTRA_INVITEE_S * max(0, len(run["members"]) - 1)

#: The fewest people a GROUP action (``participants`` > 2) runs with, the
#: actor included. Its ``participants`` — the role count of its clip — is the
#: most; the roles nobody takes stay empty (``interaction_engine.group_roles``).
GROUP_MIN_PEOPLE = 3


def head_count_fits(participants: int, invitees: int) -> bool:
    """Whether the actor plus ``invitees`` others fit an action for
    ``participants``: a solo or pair action takes exactly that many, a group
    action any count from ``GROUP_MIN_PEOPLE`` up to ``participants``."""
    people = invitees + 1
    if participants > 2:
        return GROUP_MIN_PEOPLE <= people <= participants
    return people == participants


def _reacts(run):
    """A pair run that starts without consent: the partner REACTS instead."""
    return len(run.get("members") or ()) == 1 and run["data"].get("consent") == "react"


def _same_run(actor, target, action_id, members):
    """The live run ``actor`` already takes part in that this request names
    again — the same action on the same piece with the same people,
    whichever of them requested it. None otherwise."""
    people = {actor, *members}
    held = store.held(store.person_key(actor))
    run = store.get(held) if held else None
    if (run and run["status"] not in store.TERMINAL and run["action_id"] == action_id
            and run["target"] == target and set(store.people(run)) == people):
        return run
    # An invitation holds no claims yet: the same question asked again is the
    # one already waiting for its answer.
    return next((r for r in store.live_runs() if r["status"] == "awaiting_consent"
                 and r["action_id"] == action_id and r["target"] == target
                 and set(store.people(r)) == people), None)


def _save(run):
    """Plain progress write; active effect progress must use _commit instead."""
    with store.transaction() as conn:
        previous = store.get(run["execution_id"], conn=conn)
        saved = store.save(conn, run)
    if saved:
        _activity_boundary(run, previous["status"], game_time())
        _notify(run)


def _activity_boundary(run, previous_status, now):
    owned = ("active", "sleeping")
    if ((previous_status in owned) == (run["status"] in owned)
            or not any(effect["type"] == "stat_delta" for effect in run["definition"]["effects"])):
        return
    from app.core.keyed_lock import _after_locks
    from app.core.stat_effects import reanchor_activity_accounting
    names = [name for role, name in _members(run) if any(
        effect["type"] == "stat_delta" and effect["target"] in (role, "both")
        for effect in run["definition"]["effects"])]
    _after_locks(lambda: reanchor_activity_accounting(names, now))


def _commit(run, phases=(), *, runtime=None, now=None, catalogs=None):
    """Profiles -> dedicated DB write, never DB write -> profile locks.

    Run/phase/clock, bounded runtime state, effects and receipts either all
    commit or all roll back. No separately committing save helper is used.
    """
    from app.core import effect_application as effects
    if not runtime and not any(effect["when"] in phases for effect in run["definition"]["effects"]):
        _save(run)
        return run["data"].get("effect_results", {})
    catalogs = catalogs if catalogs is not None else effects.effect_catalogs()
    now = now if now is not None else game_time()
    changed = {}
    with ExitStack() as locks:
        for name in sorted(n for _, n in _members(run)):
            locks.enter_context(keyed_lock("character_profile", name))
        with store.transaction() as conn:
            current = store.get(run["execution_id"], conn=conn)
            if not current or current["status"] in store.TERMINAL:
                return {}
            profiles = {name: C.read_effect_profile(conn, name) for _, name in _members(run)}
            for phase in phases:
                for effect in run["definition"]["effects"]:
                    if effect["when"] != phase:
                        continue
                    for name in _targets(run, effect["target"]):
                        reason = effects.validate_profile_effects(profiles[name], [effect], catalogs)
                        if reason and phase != "active":
                            raise ValueError(reason)
                result = effects.apply_execution_effects(run["execution_id"], phase, now,
                                                        conn=conn, run=run, profiles=profiles, catalogs=catalogs)
                if result["effects"]:
                    run["data"].setdefault("effect_results", {})[phase] = result["effects"]
                for name, update in result["changed"].items():
                    aggregate = changed.setdefault(name, dict(changes={}, results={}))
                    effects.merge_changes(aggregate["changes"], update["changes"])
                    aggregate["results"].update(update["results"])
            for name in profiles:
                if name in changed or (runtime and name in runtime):
                    C.write_effect_profile(conn, name, profiles[name], runtime=(runtime or {}).get(name))
            if not store.save(conn, run):
                raise RuntimeError("execution_progress_write_failed")
    effects.notify_effects(changed, "prop_action:" + run["execution_id"])
    _activity_boundary(run, current["status"], now)
    _notify(run)
    return run["data"].get("effect_results", {})


def apply_execution_effects(execution_id: str, phase: str, now: GameTime) -> dict:
    """Replay only durable real lifecycle evidence, never a caller's wish."""
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run:
            return dict(effects={}, reason="execution_not_found")
        recorded = run["data"].get("effect_results", {}).get(phase)
        if run["status"] in store.TERMINAL:
            return dict(effects=recorded or {})
        allowed = ((phase == "start" and run["status"] in ("active", "sleeping"))
                   or (phase == "active" and run["status"] == "active" and run["definition"]["ability"] != "sleep")
                   or (phase == "success" and run["status"] == "sleeping" and C.is_character_sleeping(run["actor"])))
        if not allowed:
            return dict(effects=recorded or {}, reason="effect_phase_not_reached")
        result = _commit(run, (phase,), now=now)
        return dict(effects=result.get(phase, {}))

def _place_lock(run):
    """The seat-allocation lock of the run's location. Existing seating uses
    location-place -> profile: keep that order, and never call profile
    writers/callbacks in the SQLite acquisition span (``store.transaction``),
    which this lock encloses."""
    return keyed_lock("places", run["target"]["location_id"])


def _definition(target, action_id, revision, *, _query=None):
    query = _query if _query is not None else places._GeometryQuery()
    candidates = [p for p in query.room_places(target["location_id"], target["room_id"])
                  if p.get("placement_id") == target["placement_id"]]
    if not candidates:
        return None, "placement_not_found"
    candidates = [p for p in candidates if p.get("variant_uid") == target["variant_uid"]]
    if not candidates:
        return None, "stale_variant"
    # Author snapshot, not the rendering getter (which can demand media work).
    prop = query.prop_document(candidates[0]["prop_id"])
    if props._document_revision(prop) != revision:
        return None, "stale_definition"
    action = next((a for a in prop.get("actions", []) if a["id"] == action_id), None)
    if not action:
        return None, "action_not_found"
    if not action.get("enabled"):
        return None, "action_disabled"
    from app.core.prop_actions import validate_document
    issues = validate_document(prop)
    if any(i["severity"] == "error" for i in issues):
        reason = next((i["code"] for i in issues if i["code"] == "unknown_requirement_reference"),
                      "invalid_action_definition")
        return None, reason
    from app.core.pose_catalog import get_catalog
    catalog = get_catalog("pose")
    keys = [p["pose_key"] for p in action["phases"]] if action["ability"] == "combined" else [action["pose_key"]]
    if any(key not in catalog for key in keys):
        return None, "unknown_pose"
    if any(catalog[key].get("participants", 1) != action["participants"] for key in keys):
        return None, "unsupported_pose_capability"
    if action["ability"] == "sleep" and catalog[action["pose_key"]].get("group") != "lie":
        return None, "sleep_requires_lying_place"
    if action["ability"] == "pair":
        from app.core.interaction_engine import pair_kind_for_pose
        if not pair_kind_for_pose(action["pose_key"]):
            return None, "missing_pair_animation"
    return action, ""


def _conditions(profile, now):
    result = set()
    for entry in profile.get("active_conditions") or []:
        duration = entry.get("duration_hours", 0)
        if duration:
            try:
                if (now - GameTime.parse(entry["started_at"])).total_seconds > float(duration) * 3600:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
        result.add(entry.get("name"))
    return result


def _requirements(run, profiles):
    from app.core.stat_boosts import effective_stat
    from app.core.prompt_filters import load_filters
    from app.core.stat_rules import template_rules
    from app.models.character_template import get_template
    conditions = {f["id"] for f in load_filters() if f.get("enabled", True)}
    now = game_time()
    for req in run["definition"].get("requirements", []):
        for name in _targets(run, req["target"]):
            profile = profiles[name]
            if req["type"] == "stat":
                key = req["stat"]
                if key not in template_rules(get_template(profile.get("template", "")) or {}):
                    return "unknown_requirement_reference"
                try:
                    value = effective_stat(profile, key)
                    if value is None or not math.isfinite(float(value)):
                        return "missing_character_stat"
                except (TypeError, ValueError, OverflowError):
                    return "missing_character_stat"
                if not _OPS[req["op"]](value, req["value"]):
                    return "requirement_not_met"
            else:
                if req["condition_id"] not in conditions:
                    return "unknown_requirement_reference"
                if (req["condition_id"] in _conditions(profile, now)) != req["present"]:
                    return "requirement_not_met"
    return ""


def animated_for(name, definition, *, profile=None) -> bool:
    """Whether ``name``'s figure has a clip for every pose of a solo action:
    along its set chain (explicit -> derived female/male/animal), then the
    neutral set — the very lookup its client plays from. A pose whose clip
    exists only for another figure (a ``female``-only take for a male
    character) is not meant for this one, and the action is not offered
    instead of playing as the group's fallback. A pose without a configured
    clip kind claims nothing and passes."""
    from app.core.animation_sets import resolve_sets
    from app.core.movement import clip_file_for, played_pose_kind
    keys = ([p.get("pose_key") for p in definition.get("phases") or []]
            if definition.get("ability") == "combined" else [definition.get("pose_key")])
    chain = resolve_sets(name, profile)
    for key in keys:
        kind = played_pose_kind(key) if isinstance(key, str) else ""
        if kind and clip_file_for(kind, chain, free_only=False) is None:
            return False
    return True


def _validate(run, *, conn=None, require_claims=False, presence=True, _query=None, replaces=(),
              offer=False):
    """``replaces``: the live runs of the two people this request ends first
    (``_replaced_runs``) — their claims, journeys and interactions do not
    count as busy. ``offer``: a menu asks, not a start (``participation``)."""
    replaces = _refs(replaces)
    query = _query if _query is not None else places._GeometryQuery()
    definition, reason = _definition(run["target"], run["action_id"], run["definition_revision"], _query=query)
    if reason:
        return reason
    if definition != run["definition"]:
        return "stale_definition"
    from app.core.effect_application import effect_catalogs, validate_profile_effects
    catalogs = effect_catalogs()
    profiles = {}
    for role, name in _members(run):
        row = (conn or store.db.get_connection()).execute("SELECT status FROM characters WHERE name=?", (name,)).fetchone()
        if row is None or row[0]:
            return "participant_unavailable"
        held = store.held(store.person_key(name), conn=conn)
        if held and held not in (run["execution_id"], *replaces):
            return "participant_claimed"
        if require_claims and held != run["execution_id"]:
            return "participant_claim_lost"
        profile = profiles[name] = query.profile(name)
        if places.where(name, profile=profile) != (run["target"]["location_id"], run["target"]["room_id"]):
            return "target_not_in_actor_room"
        if definition["ability"] != "pair" and not animated_for(name, definition, profile=profile):
            return "pose_not_for_actor"
        owned_sleep_transition = (run["status"] == "active" and definition["ability"] == "sleep"
                                  and (profile.get("place") or {}).get("execution_id") == run["execution_id"])
        if profile.get("is_sleeping") and run["status"] != "sleeping" and not owned_sleep_transition:
            return "participant_asleep"
        journey = profile.get("journey")
        if journey and not _own_journey(run, name, journey) and journey.get("execution_ref") not in replaces:
            return "journey_already_active"
        ref = (profile.get("interaction") or {}).get("execution_ref")
        if profile.get("interaction") and ref != run["execution_id"] and ref not in replaces:
            return "interaction_active"
        targeted = [effect for effect in definition["effects"]
                    if effect["target"] in (role, "both")]
        reason = validate_profile_effects(profile, targeted, catalogs)
        if reason:
            return reason
    if presence:
        from app.core.model_refs import is_humanoid
        members = set(profiles)
        # Who is in the room means people: a pet lying there is nobody.
        present = {n for n, _ in places._present(run["target"]["location_id"], run["target"]["room_id"])
                   if n in members or is_humanoid(n, profile=query.profile(n))}
        rule = definition["presence"]
        if rule == "policy":
            # The characters decide, not the furniture: packages answer
            # (``participation.check``); none registered = allowed. Their
            # reason code reaches start, accept and the offer menu as it is.
            from app.core import participation
            refused = participation.check(
                "prop_action", str(definition.get("pose_key") or ""),
                store.people(run),
                run["target"]["location_id"], run["target"]["room_id"], offer=offer)
            if refused:
                return refused["reason"]
        elif ((rule == "alone" and present != {run["actor"]}) or
                (rule == "others" and not present - {run["actor"]}) or
                (rule == "participants_only" and present != members)):
            return "presence_not_met"
    if definition["ability"] == "pair" and run["status"] in ("awaiting_consent", "approaching"):
        # The clothes in the way of the clip's contact (owner decision 2026-11-25): asked for every offer, request,
        # answer, walk and entry — never once the run is active (a piece put back on does not stop a running clip).
        from app.core import contact_clothing
        if contact_clothing.refusal(definition["pose_key"], store.people(run),
                                    roles=run["data"].get("clip_roles") or None, profiles=profiles):
            return contact_clothing.REASON
    reason = _requirements(run, profiles) if presence else ""
    if reason:
        return reason
    if require_claims:
        for name, plan in run["data"]["plans"].items():
            anchor = plan["entry_anchor"]
            key = store.slot_key(run["target"], anchor["marker_id"], anchor["slot"])
            if store.held(key, conn=conn) != run["execution_id"]:
                return "slot_claim_lost"
            inventory = query.room_places(run["target"]["location_id"], run["target"]["room_id"])
            place = next((p for p in inventory
                          if p["id"] == anchor["place_id"]), None)
            if not place:
                return "placement_not_found"
            taken = places.occupancy(run["target"]["location_id"], run["target"]["room_id"],
                                     _places=inventory).get(place["id"], [])
            others = [(n, s) for n, s in taken if n not in profiles and n != "@prop:" + run["execution_id"]]
            if anchor["slot"] not in places.free_slots(place, others):
                stale = _left_behind(run)
                if not stale or anchor["slot"] not in places.free_slots(
                        place, [t for t in others if t[0] not in stale]):
                    return "slot_occupied"
            binding = next((b for b in place.get("action_bindings", [])
                            if b["action_id"] == run["action_id"]), None)
            if not binding or not binding.get("supported") or binding.get("validation") != "local_valid":
                return "binding_not_supported"
            from app.core.prop_action_access import slot_access
            try:
                point = _entry_point(run, name, place)
            except ValueError:
                return "approach_target_changed"
            current_access, access_reason = slot_access(
                place, anchor["slot"], run["data"]["access_roles"][name],
                definition, profiles[name], point=point)
            if access_reason:
                return access_reason
            expected = point if point is not None else list(place["slots"][anchor["slot"]])
            if current_access != plan.get("bridge_access", plan["access"]) or expected != [anchor["x"], anchor["z"]] or place["y_world"] != anchor["y"]:
                return "approach_target_changed"
            if run["status"] == "approaching" and (run["phase"] == "entry" or name in run["data"]["arrived"]):
                pos = C.get_character_pos(name)
                if not pos or math.dist((pos["x"], pos["z"]), (plan["access"]["x"], plan["access"]["z"])) > .05:
                    return "access_position_lost"
            if run["status"] in ("active", "sleeping"):
                profile = profiles[name]
                field = profile.get("place") or {}
                if field.get("execution_id") != run["execution_id"] or field.get("id") != anchor["place_id"] or field.get("slot") != anchor["slot"]:
                    return "owned_place_lost"
                pos = C.get_character_pos(name)
                if not pos or math.dist((pos["x"], pos["z"]), (anchor["x"], anchor["z"])) > .05:
                    return "owned_position_lost"
    return ""


def _shares_place(run) -> bool:
    """A pair or group whose pose shares one place (catalog ``places`` 1)."""
    from app.core.pose_catalog import pose_places
    definition = run["definition"]
    return definition["ability"] == "pair" and pose_places(definition["pose_key"]) == 1


def _entry_point(run, name, place):
    """The entry target of ``name`` on ``place`` when it is NOT its slot
    position: a pair or group sharing one place (``_shares_place``) enters
    at its clip role point (``interaction_engine.role_point``), else None.
    Recomputed, never read back from a plan, so a revalidation compares the
    plan against today's place and catalog."""
    if not _shares_place(run):
        return None
    definition = run["definition"]
    from app.core.interaction_engine import role_point
    clip_role = next(r for r, member in run["data"]["clip_roles"].items() if member == name)
    return list(role_point(place, definition["pose_key"], clip_role))


def _plan(run, *, conn, _query=None, replaces=()):
    from app.core.prop_action_paths import plan_approach
    query = _query if _query is not None else places._GeometryQuery()
    target = dict(run["target"], action_id=run["action_id"], definition_revision=run["definition_revision"])
    candidates = query.room_places(target["location_id"], target["room_id"])
    choices = []
    last_reason = "no_free_slot"
    occupancy = places.occupancy(target["location_id"], target["room_id"], _places=candidates)
    # Both people leave their own seats as part of the departure, and the runs
    # this request replaces give up their slots: none of it blocks the new plan.
    replaces = _refs(replaces)
    own = _freed(run, replaces)
    for place in candidates:
        if place.get("placement_id") != target["placement_id"] or place.get("variant_uid") != target["variant_uid"]:
            continue
        from app.core.pose_catalog import group_of
        definition = run["definition"]
        keys = [p["pose_key"] for p in definition["phases"]] if definition["ability"] == "combined" else [definition["pose_key"]]
        if any(group_of(key) != place["group"] for key in keys):
            if last_reason == "no_free_slot":
                last_reason = "incompatible_pose_marker"
            continue
        free = [s for s in places.free_slots(place, [t for t in occupancy.get(place["id"], []) if t[0] not in own])
                if store.held(store.slot_key(target, place["marker_id"], s), conn=conn) in (None, "", *replaces)]
        from app.core.pose_catalog import pose_places
        # A group with fewer people than roles holds a slot per person at
        # most: the roles nobody takes need no place.
        need = (min(pose_places(definition["pose_key"]), len(_members(run)))
                if definition["ability"] == "pair" else len(_members(run)))
        if len(free) < need:
            continue
        if definition["ability"] == "pair":
            from app.core.interaction_engine import plan_interaction_at
            try:
                allocation = plan_interaction_at(store.people(run), definition["pose_key"], place,
                                                 profiles={name: query.profile(name) for _, name in _members(run)})
            except ValueError as exc:
                last_reason = str(exc)
                continue
            if any(s not in free for s in allocation["slots"].values()):
                continue
        else:
            allocation = dict(clip_roles={}, access_roles={run["actor"]: "actor"}, slots={run["actor"]: free[0]})
        pose = (definition["phases"][0]["pose_key"] if definition["ability"] == "combined"
                else definition["pose_key"])
        _, entry_reason = _entry_capability(pose)
        if entry_reason:
            last_reason = entry_reason
            continue
        allocations = ([allocation] if definition["ability"] == "pair" else
                       [dict(clip_roles={}, access_roles={run["actor"]: "actor"},
                             slots={run["actor"]: slot}) for slot in free])
        for allocation in allocations:
            plans = {}
            for _role, name in _members(run):
                slot = allocation["slots"][name]
                point = (allocation.get("points") or {}).get(name)
                plan = plan_approach(name, dict(target, marker_id=place["marker_id"], slot=slot,
                                                **({"point": point} if point else {})),
                                     allocation["access_roles"][name], _query=query)
                if plan["status"] != "ok":
                    last_reason = plan["reason"]
                    break
                anchor = plan["entry_anchor"]
                if not places.inside(target["location_id"], anchor["x"], anchor["z"],
                                     _locations=query.locations()):
                    last_reason = "entry_anchor_outside_location"
                    break
                plans[name] = plan
            if len(plans) == len(_members(run)):
                for _role, name in _members(run):
                    _, last_reason = _entry_spec(name, plans[name], pose, _query=query)
                    if last_reason:
                        break
                if last_reason:
                    continue
                distance = sum(sum(math.dist(a, b) for a, b in zip(p["waypoints"], p["waypoints"][1:])) for p in plans.values())
                choices.append((sum(p.get("entry_mode") == "direct" for p in plans.values()), distance, place["id"], plans, allocation))
    if not choices:
        return {}, last_reason
    _, _, _, plans, allocation = min(choices, key=lambda p: p[:3])
    run["data"].update(clip_roles=allocation["clip_roles"], access_roles=allocation["access_roles"])
    return plans, ""


def _planning_state(run, query):
    """Inputs whose change invalidates an already calculated admission plan."""
    target = run["target"]
    inventory = query.room_places(target["location_id"], target["room_id"])
    return dict(profiles={name: query.profile(name) for _, name in _members(run)},
                positions={name: C.get_character_pos(name) for _, name in _members(run)},
                inventory=inventory, geometry=query.room_geometry(target["location_id"], target["room_id"]),
                documents={p["prop_id"]: query.prop_document(p["prop_id"])
                           for p in inventory if p.get("prop_id")})


# The claim of an admission (_admit_timed, _respond) comes in two parts, both
# under the place lock of the run's location (_place_lock):
#   a) _admission_check — the expensive re-check, read only, BEFORE the write
#      transaction: validation, the planning inputs, the chosen slots' occupancy;
#   b) _admission_claims — inside BEGIN IMMEDIATE, SQL on ``conn`` only: the
#      person and slot claims and the characters' status, then insert/acquire.
# The write lock on world.db is held for b alone (milliseconds), never for the
# re-check: every other writer (sessions, chat, profiles) gives up after its
# busy_timeout of 5 s, and the re-check once took more than a minute under load.
#
# Nothing that a) decided can change before b) commits:
# - seat occupancy (a profile's ``place``) is written only under this same
#   place lock (places.assign / assign_pair, character.py's owned-place release,
#   this engine's seat entry), and so are slot claims: store.acquire runs only
#   in b of an admission at this location, while a release only frees slots;
# - a person claim may come from an admission at ANOTHER location (another
#   place lock), and a character's status from anywhere: b re-reads both in
#   the transaction, so a race ends as "participant_claimed" /
#   "participant_unavailable", never as an IntegrityError on the claim key;
# - other profile state (a journey, sleep) is re-checked by every tick of
#   ``advance`` (``require_claims``), as it was between plan and claim before;
# - a) reuses the admission's composed room, room geometry and prop documents
#   (``with_fresh_profiles``): an admin's layout or prop edit landing inside
#   the admission itself is caught by that same tick (a fresh query), not here.
# Lock order: _lock(execution) -> places -> SQLite; a) reads profiles without
# taking a character_profile lock, b) takes none.


def _admission_check(run, planned_state, query, replaces=()):
    """Part a of the claim (see above), under the place lock and outside the
    write transaction. ``query`` is the admission's own (validate/plan)
    geometry with fresh profiles (``with_fresh_profiles``), so the profile
    comparison is meaningful and no room is composed a second time."""
    reason = "world_frozen" if is_world_frozen() else _validate(run, _query=query, replaces=replaces)
    if reason:
        return reason
    if _planning_state(run, query) != planned_state:
        return "approach_target_changed"
    target = run["target"]
    inventory = query.room_places(target["location_id"], target["room_id"])
    taken = places.occupancy(target["location_id"], target["room_id"], _places=inventory)
    own = _freed(run, _refs(replaces))
    for plan in run["data"]["plans"].values():
        anchor = plan["entry_anchor"]
        place = next((p for p in inventory if p["id"] == anchor["place_id"]), None)
        if not place or anchor["slot"] not in places.free_slots(
                place, [t for t in taken.get(place["id"], []) if t[0] not in own]):
            return "no_free_slot"
    return ""


def _admission_claims(run, conn, replaces=()):
    """Part b of the claim (see above): inside BEGIN IMMEDIATE, SQL on ``conn``
    only — each participant's status and person claim, each chosen slot's
    claim."""
    replaces = _refs(replaces)
    for _role, name in _members(run):
        row = conn.execute("SELECT status FROM characters WHERE name=?", (name,)).fetchone()
        if row is None or row[0]:
            return "participant_unavailable"
        held = store.held(store.person_key(name), conn=conn)
        if held and held not in (run["execution_id"], *replaces):
            return "participant_claimed"
    for plan in run["data"]["plans"].values():
        anchor = plan["entry_anchor"]
        if store.held(store.slot_key(run["target"], anchor["marker_id"], anchor["slot"]), conn=conn) \
                not in (None, "", *replaces):
            return "no_free_slot"
    return ""


def request(actor: str, target: dict, action_id: str, revision: str, members=(), request_id: str = "",
            consent: str = "ask") -> dict:
    """Public Core result remains unchanged; admission metadata stays internal."""
    return request_with_creation(actor, target, action_id, revision, members, request_id, consent)[0]


def _valid_members(actor, members):
    """``members`` as a list when it names distinct people other than
    ``actor`` (each a non-empty string), else None."""
    if not isinstance(members, (list, tuple)):
        return None
    out = list(members)
    if (any(not isinstance(m, str) or not m for m in out)
            or len(set(out)) != len(out) or actor in out):
        return None
    return out


def request_with_creation(actor: str, target: dict, action_id: str, revision: str,
                          members=(), request_id: str = "", consent: str = "ask") -> tuple[dict, bool]:
    """Return (result, created), with creation decided at the SQLite insert.

    ``members``: the invitees, in invitation order — one for a pair action,
    ``GROUP_MIN_PEOPLE`` - 1 up to ``participants`` - 1 for a group action
    (``head_count_fits``), none for a solo action.
    ``consent`` (requests with others): "ask" — every invitee consents
    first — or "react", a pair only (``CONSENTS``). Naming the run one
    already takes part in again — the partner's tool repeating the action it
    just agreed to — answers that run, marked ``already``, instead of
    refusing it as a busy participant. An "ask" for another action on the
    piece the same people already use together, with their consent, asks
    nobody again (_consent_carries): it switches in place at once, its
    ``consents`` all "yes" and ``consent_carried`` set.

    Adapters must not infer creation from a successful status: a replay has the
    same result. The second nonce lookup under BEGIN IMMEDIATE also handles a
    competing Core caller/process that does not hold the adapter's nonce guard.
    """
    if (not isinstance(actor, str) or not actor or not isinstance(target, dict) or set(target) != set(_TARGET)
            or any(not isinstance(target[k], str) or not target[k] for k in _TARGET)
            or not all(isinstance(v, str) for v in (action_id, revision, request_id))
            or consent not in CONSENTS):
        return _refused("invalid_request"), False
    invitees = _valid_members(actor, members)
    if invitees is None:
        return _refused("invalid_partner"), False
    fingerprint = store.encode([target, action_id, revision, invitees] + ([consent] if consent != "ask" else []))
    previous = store.by_request(actor, request_id)
    if previous:
        return (_result(previous) if previous["request_fingerprint"] == fingerprint
                else _refused("request_id_conflict")), False
    same = _same_run(actor, target, action_id, invitees)
    if same:
        return dict(_result(same), already=True), False
    if places.where(actor) != (target["location_id"], target["room_id"]):
        return _refused("target_not_in_actor_room"), False
    if is_world_frozen():
        return _refused("world_frozen"), False
    definition, reason = _definition(target, action_id, revision)
    if reason:
        return _refused(reason), False
    if not head_count_fits(definition["participants"], len(invitees)):
        return _refused("invalid_partner"), False
    if consent == "react" and len(invitees) != 1:
        return _refused("invalid_consent"), False
    now = game_time().canonical()
    asks = bool(invitees) and consent != "react"
    run = dict(execution_id=uuid.uuid4().hex, actor=actor, members=invitees, request_id=request_id or None,
               request_fingerprint=fingerprint, action_id=action_id, definition_revision=revision,
               status="awaiting_consent" if asks else "approaching", phase="", reason="", target=target,
               definition=definition, data=dict(plans={}, journey_ids={}, arrived=[], process=_PROCESS,
                                                last_game=now, last_motion=_motion_now(),
                                                **({"consent": consent} if invitees else {}),
                                                **({"consents": {m: "pending" for m in invitees},
                                                    "consent_wait_s": 0.0} if asks else {})))
    replaces = _replaced_runs(actor, invitees, target, action_id)
    if not replaces:
        return _admit(run, fingerprint)
    if asks and _consent_carries(run, replaces):
        # They agreed to being here together already: another action on the
        # same piece asks nobody again and switches in place below.
        asks = False
        run["status"] = "approaching"
        run["data"].pop("consent_wait_s", None)
        run["data"].update(consents={m: "yes" for m in invitees}, consented=True, consent_carried=True)
    if asks:
        # An invitation ends nothing yet: what they are doing goes on until
        # the last invitee agrees (respond), and on after a "no".
        return _admit(run, fingerprint, replaces=replaces)
    # Another action while seated: stand up and go there. Refusals that need
    # no route keep the current actions; a failed plan after that has ended
    # them, and the seated stand up instead (a no-op once the new approach
    # has taken the place over).
    reason = _validate(run, replaces=replaces)
    if reason:
        return _refused(reason, run), False
    direct = _switches_in_place(run, replaces)
    with _replacing(run, replaces, direct):
        return _admit(run, fingerprint, direct=direct)


#: An admission slower than this logs where its time went.
_SLOW_ADMIT_MS = 150.0


def _admit(run, fingerprint, *, replaces=(), direct=False):
    """Validate, plan, claim and start one new run (request_with_creation).
    ``replaces``: runs an invitation leaves running (they end on consent);
    ``direct``: the switch on the piece both already use (_settle_in_place)."""
    actor = run["actor"]
    marks = [("begin", time.perf_counter())]
    try:
        return _admit_timed(run, fingerprint, marks, replaces, direct)
    finally:
        marks.append(("end", time.perf_counter()))
        total = (marks[-1][1] - marks[0][1]) * 1000
        if total >= _SLOW_ADMIT_MS:
            steps = " ".join(f"{name}={(at - marks[i][1]) * 1000:.0f}"
                             for i, (name, at) in enumerate(marks[1:]))
            logger.info("prop-action admission for %s took %.0f ms (%s)", actor, total, steps)


def _admit_timed(run, fingerprint, marks, replaces, direct):
    actor, members, request_id = run["actor"], run["members"], run["request_id"] or ""
    with _lock(run["execution_id"]):
        marks.append(("lock", time.perf_counter()))
        query = places._GeometryQuery(cache_profiles=True)
        reason = _validate(run, _query=query, replaces=replaces)
        marks.append(("validate", time.perf_counter()))
        planned_state = _planning_state(run, query)
        plans, plan_reason = (_plan(run, conn=store.db.get_connection(), _query=query, replaces=replaces)
                              if not reason else ({}, ""))
        marks.append(("plan", time.perf_counter()))
        reason = reason or plan_reason
        if reason:
            previous = store.by_request(actor, request_id)
            if previous:
                return (_result(previous) if previous["request_fingerprint"] == fingerprint
                        else _refused("request_id_conflict")), False
            return _refused(reason, run), False
        run["data"]["plans"] = plans
        reacts = _reacts(run)
        if reacts:
            run["data"].update(consented=True, reaction=_reaction_request(members[0]))
        # Who starts at once: alone, without asking (react), or with a
        # consent carried over from the run it replaces (_consent_carries).
        starts = not members or bool(run["data"].get("consented"))
        with _place_lock(run):
            previous = store.by_request(actor, request_id)
            if previous:
                return (_result(previous) if previous["request_fingerprint"] == fingerprint
                        else _refused("request_id_conflict")), False
            reason = _admission_check(run, planned_state, query.with_fresh_profiles(), replaces)
            if reason:
                return _refused(reason, run), False
            marks.append(("recheck", time.perf_counter()))
            with store.transaction() as conn:
                # The second nonce lookup under BEGIN IMMEDIATE: a competing
                # caller/process without this adapter's nonce guard.
                previous = store.by_request(actor, request_id, conn=conn)
                if previous:
                    return (_result(previous) if previous["request_fingerprint"] == fingerprint
                            else _refused("request_id_conflict")), False
                reason = _admission_claims(run, conn, replaces)
                if reason:
                    return _refused(reason, run), False
                store.insert(conn, run)
                if starts:
                    store.acquire(conn, run, [p["entry_anchor"] for p in plans.values()])
        marks.append(("claim", time.perf_counter()))
        if starts:
            _launch(run, direct)
        marks.append(("start", time.perf_counter()))
    _notify(run)
    if reacts:
        _narrate(run, "{actor} approaches {partner}: {pose}.", _query=query)
        if run["data"]["reaction"]["state"] == "pending":
            _ask_reaction(run)
    elif members and not starts:
        _narrate(run, "{inviter} suggests {pose} to {invitee}.", _query=query, inviter=actor,
                 invitee=_join(members))
        # A decision/model or respond-lane request must never run inside an
        # execution/profile/place lock or an SQLite transaction. One question
        # per invitee: each answers for itself.
        from app.core.hooks import emit
        from app.core.keyed_lock import _after_locks
        for member in members:
            _after_locks(lambda member=member: emit("prop_action.invited", execution_id=run["execution_id"],
                                                    inviter=actor, invitee=member))
    return _result(store.get(run["execution_id"])), True


def _last_consent(run, name) -> bool:
    """Whether ``name``'s "yes" is the one ``run`` still waits for: every
    other invitee has agreed already."""
    consents = run["data"].get("consents") or {}
    return all(answer == "yes" for member, answer in consents.items() if member != name)


def _consent_over(run) -> bool:
    """Advance ``run``'s invitation wait to now on the motion clock and tell
    whether its window (``consent_window_s``) has closed. As in the tick's
    ``_clock``, time from before this process started does not count, and a
    frozen world's motion clock stands still. A run stored before the wait
    moved to the motion clock starts its window again here."""
    data = run["data"]
    now_s = _motion_now()
    if data["process"] == _PROCESS:
        data["consent_wait_s"] = (data.get("consent_wait_s", 0.0)
                                  + max(0.0, now_s - float(data.get("last_motion", now_s))))
    data.update(last_game=game_time().canonical(), last_motion=now_s, process=_PROCESS)
    return data.get("consent_wait_s", 0.0) >= consent_window_s(run)


def _late_answer(run, name, accept):
    """``name`` answers an invitation that had already expired before it
    did. A "yes" up to ``LATE_ANSWER_WINDOW_S`` after the expiry tells the
    inviter — a line in the room and a notice for a player — once per
    invitee; a "no" (or a later "yes") changes nothing. After every lock:
    the expiry may not be committed before that."""
    if accept is not True:
        return
    from app.core.keyed_lock import _after_locks
    execution_id = run["execution_id"]

    def deliver():
        try:
            current = store.get(execution_id)
            expired_at = (current or {}).get("data", {}).get("expired_at_s")
            if expired_at is None or _motion_now() - float(expired_at) > LATE_ANSWER_WINDOW_S:
                return
            if not store.mark_late_answer(execution_id, name):
                return
            key = "{name} would have agreed — the invitation had already expired."
            _narrate(current, key, name=name)
            _tell_inviter(current, key, name=name)
        except Exception:
            logger.exception("late answer of %s to %s failed", name, execution_id)

    _after_locks(deliver)


def _respond(actor: str, execution_id: str, accept: bool, direct: bool = False) -> dict:
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or actor not in run["members"]:
            return _refused("not_invitee")
        if type(accept) is not bool:
            return _refused("invalid_response")
        pending = (run["data"].get("consents") or {}).get(actor) == "pending"
        if (run["status"], run["reason"]) == ("cancelled", "consent_expired") and pending:
            _late_answer(run, actor, accept)
            return _result(run)
        if run["status"] != "awaiting_consent" or not pending:
            return _result(run)
        if not accept:
            # One "no" ends the invitation for everyone, naming who said it.
            run["data"]["declined_by"] = actor
            return _finish(run, "cancelled", "consent_declined")
        if is_world_frozen():
            return _refused("world_frozen")
        if _consent_over(run):
            # The window closed before this "yes" and no tick has noticed yet:
            # the invitation expires now, and the answer is a late one.
            run["data"]["expired_at_s"] = run["data"]["last_motion"]
            _finish(run, "cancelled", "consent_expired")
            _late_answer(run, actor, accept)
            return _result(run)
        if not _last_consent(run, actor):
            # Agreed; the run waits for the others before anything is planned.
            run["data"]["consents"][actor] = "yes"
            _save(run)
            return _result(run)
        query = places._GeometryQuery(cache_profiles=True)
        reason = _validate(run, _query=query)
        planned_state = _planning_state(run, query)
        agreed_roles = dict(run["data"]["clip_roles"])
        agreed_access = dict(run["data"]["access_roles"])
        plans, plan_reason = _plan(run, conn=store.db.get_connection(), _query=query) if not reason else ({}, "")
        reason = reason or plan_reason
        planned_roles = dict(run["data"]["clip_roles"])
        planned_access = dict(run["data"]["access_roles"])
        if not reason and planned_roles != agreed_roles:
            reason = "pair_roles_changed"
        with _place_lock(run):
            if not reason:
                # Part a of the claim (see _admission_check), outside the
                # write transaction; the run this answer planned on.
                planned = dict(run, data=dict(run["data"], plans=plans, clip_roles=planned_roles,
                                              access_roles=planned_access))
                reason = _admission_check(planned, planned_state, query.with_fresh_profiles())
            with store.transaction() as conn:
                run = store.get(execution_id, conn=conn)
                if run["status"] != "awaiting_consent":
                    return _result(run)
                data = run["data"]
                if _consent_over(run):
                    # Expired while this answer was planned. Lines and notices go
                    # out after the commit (the place lock defers them).
                    data["expired_at_s"] = data["last_motion"]
                    run.update(status="cancelled", reason="consent_expired")
                    store.save(conn, run)
                    _narrate_finish(run, "awaiting_consent", "cancelled", "consent_expired", set())
                    _late_answer(run, actor, accept)
                    return _result(run)
                if not reason:
                    data.update(plans=plans, clip_roles=planned_roles, access_roles=planned_access)
                    reason = _admission_claims(run, conn)
                if reason == "pair_roles_changed":
                    data.update(clip_roles=agreed_roles, access_roles=agreed_access)
                if reason:
                    run.update(status="failed", reason=reason)
                    store.save(conn, run)
                    return _result(run)
                run["data"].update(plans=plans, consented=True, last_game=game_time().canonical(),
                                   last_motion=_motion_now(), process=_PROCESS)
                run["data"]["consents"][actor] = "yes"
                run["status"] = "approaching"
                store.acquire(conn, run, [p["entry_anchor"] for p in plans.values()])
                store.save(conn, run)
        _launch(run, direct)
        return _result(store.get(execution_id))


def _start_checked(run):
    try:
        _start(run)
    except Exception:
        logger.exception("Prop action approach start failed: %s", run["execution_id"])
        _finish(run, "failed", "approach_start_error")


def _start(run):
    """Start an admitted approach on the estimate timer (plan E3 decision 7a):
    no journey. Per member the checks the journey start used to make
    (``actor_moved``, ``interaction_active``, ``journey_already_active``,
    ``target_not_in_actor_room``), then ONE profile write that frees its seat
    (``place`` None, ``pose_key``/``pose_flavor``/``movement_target`` empty).
    The run stores absolute motion seconds: ``eta_s`` per member (``estimate``
    over the length of its planned polyline, its exit clip and the speed frozen
    here), ``flip_s`` (run eta + the entry's nominal seconds) and
    ``deadline_s``. An empty path is refused (``no_route``)."""
    from app.core import motion_orders as mo
    from app.core.keyed_lock import keyed_lock
    from app.models.account import is_player_controlled
    data = run["data"]
    if is_world_frozen():
        _finish(run, "failed", "world_frozen")
        return
    issued = _motion_now()
    speed = float(travel.get_travel_speed_m_s())
    lengths, origins = {}, {}
    for _role, name in _members(run):
        plan = data["plans"][name]
        points = [list(p[:2]) for p in plan.get("waypoints") or []]
        if not points:
            _finish(run, "failed", "no_route")
            return
        seat = plan.get("departure_seat")
        origins[name] = tuple((seat["seat"] if isinstance(seat, dict) else seat) or points[0])
        lengths[name] = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    for _role, name in _members(run):
        # What the order names as its exit and start, captured BEFORE the
        # write below releases the seat (afterwards places.place_of is None).
        departure = _departure(name)
        start = _figure_start(run, name)
        with keyed_lock("character_profile", name):
            profile = C.get_character_profile(name) or {}
            pos = C.get_character_pos(name)
            reason = ""
            if profile.get("journey"):
                reason = "journey_already_active"
            elif places.where(name, profile=profile) != (run["target"]["location_id"], run["target"]["room_id"]):
                reason = "target_not_in_actor_room"
            elif pos is None or math.dist((pos["x"], pos["z"]), origins[name]) > 1e-6:
                reason = "actor_moved"
            elif profile.get("interaction"):
                reason = "interaction_active"
            if not reason:
                profile.update(movement_target="", place=None, pose_key="", pose_flavor="")
                if not C.save_character_profile(name, profile):
                    reason = "write_failed"
        if reason:
            _finish(run, "failed", reason)
            return
        data["plans"][name]["departure_seat"] = departure
        data.setdefault("order_starts", {})[name] = start
    entry_s = _run_entry_nominal_s(run)
    etas = {}
    for _role, name in _members(run):
        departure = data["plans"][name]["departure_seat"]
        exit_s = float(departure["exit_s"]) if isinstance(departure, dict) else 0.0
        etas[name] = round(mo.estimate(issued, exit_s, lengths[name], speed, entry_s)[0], 3)
    eta = max(etas.values())
    data.pop("elapsed", None)
    data.update(issued_s=issued, eta_s=etas, flip_s=round(eta + entry_s, 3),
                deadline_s=round(mo.deadline(issued, eta), 3), speed_m_s=speed, arrived_s={},
                reports_arrival=[name for _role, name in _members(run) if is_player_controlled(name)],
                last_game=game_time().canonical(), last_motion=issued)
    _publish_order(run)
    _save(run)
    _wake_ticker()


def _wake_ticker():
    """The travel ticker plans its next beat now (an arrival is seconds away)."""
    try:
        travel.get_travel_ticker().wake()
    except Exception:  # noqa: BLE001 — no running ticker (scripts, tests)
        pass


def _run_entry_nominal_s(run) -> float:
    """The catalog seconds of ``run``'s entry clip (0 when every member enters
    ``direct``): what ``_order`` puts on its ``entry`` steps."""
    plans = run["data"]["plans"]
    if all(plans[name].get("entry_mode") == "direct" for _role, name in _members(run)):
        return 0.0
    definition = run["definition"]
    pose = definition["phases"][0]["pose_key"] if definition["ability"] == "combined" else definition["pose_key"]
    capability, _reason = _entry_capability(pose)
    return float(capability[1]["duration_s"]) if capability else 0.0


def _motion_snapshot(run, name, journey):
    """What the participant's OWN client plays, taken from the very journey
    and plan the server runs (B1: the server decides and plans, the owner
    plays it at once on its own clock). Stored with the run; paces are
    derived from the timed polyline when it is read."""
    plan = run["data"]["plans"][name]
    definition = run["definition"]
    pose = definition["phases"][0]["pose_key"] if definition["ability"] == "combined" else definition["pose_key"]
    spec, reason = _entry_spec(name, plan, pose)
    entry = None
    if not reason:
        from app.core.animation_clips import clip_meta
        seconds = float((clip_meta(spec["kind"]) or {}).get("duration_s") or 0) if spec["kind"] else 0.0
        entry = dict(mode=plan.get("entry_mode", "bridge"), kind=spec["kind"], pose_key=spec["pose_key"],
                     duration_s=round(seconds, 3))
    anchor = plan["entry_anchor"]
    root_offset = float(anchor.get("root_offset", 0))
    from app.core.height import height_cm
    cm = height_cm(C.get_character_profile(name) or {})
    if cm is None and entry and entry["kind"]:
        from app.core.animation_clips import clip_ref_height_m
        reference = clip_ref_height_m(entry["kind"])
        cm = reference * 100 if reference else None
    seat = journey.get("departure_seat")
    departure = None
    if seat:
        departure = dict(seat=list(seat), stand=list(journey["waypoints"][1][:2]),
                         exit_clip=journey.get("exit_clip", ""), exit_s=float(journey.get("exit_s", 0.0)))
    return dict(execution_id=run["execution_id"], journey_id=journey["journey_id"],
                room_id=run["target"]["room_id"], floor_y=journey.get("floor_y"),
                timed=[list(p) for p in journey["waypoints"]], departure=departure,
                access={k: float(plan["access"][k]) for k in ("x", "y", "z", "yaw")},
                anchor=dict(x=float(anchor["x"]), y=float(anchor["y"]) - root_offset, z=float(anchor["z"]),
                            yaw=float(anchor.get("yaw") or 0), root_offset=root_offset,
                            place_id=anchor["place_id"], slot=anchor["slot"]),
                entry=entry, height_cm=cm,
                role=next((r for r, member in run["data"].get("clip_roles", {}).items()
                           if member == name), None))


def motion_for(name: str, run) -> dict | None:
    """The participant's own motion plan while its approach runs, else None.

    Public to the participant only (request/respond answers, its own
    ``state_for`` rows). ``waypoints`` are world-XZ metres, the first leg is
    the zero-time seat leg when ``departure`` is set; ``paces_m_s_real`` are
    per segment (null = timeless), REAL metres per second from the motion
    clock (null while the world is frozen) — the game clock's factor plays no
    part (movement runs in real time).
    """
    if not run or run["status"] != "approaching" or name not in store.people(run):
        return None
    snapshot = run["data"].get("motions", {}).get(name)
    if not snapshot:
        return None
    motion = {k: v for k, v in snapshot.items() if k != "timed"}
    motion["waypoints"] = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in snapshot["timed"]]
    motion["paces_m_s_real"] = travel.segment_paces_m_s_real(snapshot["timed"], timeutils.motion_rate())
    return motion


def _own_journey(run, name, journey):
    matches = (journey.get("execution_kind") == "prop_action" and journey.get("execution_ref") == run["execution_id"]
               and journey.get("journey_id") == run["data"]["journey_ids"].get(name))
    if not matches or "approach_target" not in journey:
        return matches  # A durable receipt has identity, not an approach body.
    plan = run["data"]["plans"][name]
    target = journey["approach_target"]
    return (journey.get("approach_role") == run["data"]["access_roles"][name]
            and journey.get("entry_anchor") == plan["entry_anchor"]
            and target.get("marker_id") == plan["entry_anchor"]["marker_id"]
            and target.get("slot") == plan["entry_anchor"]["slot"])


# --- Orders (plan E3 task 4: published beside the journey the run still walks) ---

def _departure(name):
    """The seat ``name`` leaves at the start of an approach (the order's
    ``exit`` step): ``{seat, pose_key, pose_kind, exit_s}``, or None when it
    holds no place. Read BEFORE start_approach_journey releases the place —
    afterwards places.place_of answers None (review W1)."""
    if places.place_of(name) is None:
        return None
    from app.core.pose_catalog import group_of
    pose = C.get_effective_pose_key(name) or ""
    _kind, seconds = travel.exit_bridge_for_pose(pose)
    pos = C.get_character_pos(name) or {}
    return dict(seat=[pos.get("x"), pos.get("z")], pose_key=pose, pose_kind=group_of(pose),
                exit_s=round(float(seconds), 3))


def _room_level(location_id, room_id) -> int:
    """The storey of a room (its layout ``level``, 0 when unset)."""
    try:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id) or {}
        room = next((r for r in location.get("rooms") or [] if r.get("id") == room_id), None) or {}
        return int((room.get("layout") or {}).get("level") or 0)
    except (TypeError, ValueError):
        return 0


def _yaw_deg(snapshot):
    """A stored facing (radians) as the order's compass degrees, None when unset."""
    yaw = (snapshot or {}).get("yaw")
    return None if yaw is None else round(math.degrees(float(yaw)), 3)


def _figure_start(run, name):
    """Where ``name`` stands when its order is issued: ``{x, y, z, yaw, room_id,
    level}`` on the floor of the run's room (the planned access height)."""
    target = run["target"]
    pos = C.get_character_pos(name) or {}
    plan = run["data"]["plans"].get(name) or {}
    return dict(x=float(pos.get("x") or 0.0), y=float((plan.get("access") or {}).get("y") or 0.0),
                z=float(pos.get("z") or 0.0), yaw=_yaw_deg(C.get_avatar_sync_snapshot(name)),
                room_id=target["room_id"], level=_room_level(target["location_id"], target["room_id"]))


def _order_status(run):
    if run["status"] in ("active", "sleeping"):
        return "active"
    return "entering" if run["phase"] == "entry" else "approaching"


def _order(run) -> dict:
    """The motion order of ``run`` (revision 1): one actor per member with its
    access, anchor (body root, ``y`` = support height - ``root_offset``) and
    steps — ``exit`` when ``_start`` found it seated (plan ``departure_seat``),
    ``walk`` when ``_start`` timed its approach, ``entry`` (catalog length of
    the entry clip, 0 for a ``direct`` entry) and ``loop``. The times are the
    run's own (``_start``): issued, eta = the latest member eta, the frozen
    speed; flip = eta + the longest entry; without them (a switch in place)
    issued = eta = now."""
    from app.core import motion_orders as mo
    from app.core.height import height_cm
    from app.core.pose_catalog import group_of
    from app.models.account import is_player_controlled
    data, definition, target = run["data"], run["definition"], run["target"]
    pose = definition["phases"][0]["pose_key"] if definition["ability"] == "combined" else definition["pose_key"]
    kind = group_of(pose)
    capability, _reason = _entry_capability(pose)
    catalog_s = float(capability[1]["duration_s"]) if capability else 0.0
    starts = data.get("order_starts") or {}
    roles = data.get("clip_roles") or {}
    actors, entry_s = [], 0.0
    for role, name in _members(run):
        plan = data["plans"][name]
        direct = plan.get("entry_mode") == "direct"
        entry = 0.0 if direct else catalog_s
        entry_s = max(entry_s, entry)
        sequence = []
        seat = plan.get("departure_seat")
        if isinstance(seat, dict):
            sequence.append(mo.step("exit", seat.get("pose_kind") or "", seat.get("pose_key") or "",
                                    float(seat.get("exit_s") or 0.0)))
        if name in (data.get("eta_s") or {}):
            sequence.append(mo.step("walk"))
        sequence += [mo.step("entry", kind, pose, entry), mo.step("loop", kind, pose)]
        anchor = plan["entry_anchor"]
        root = float(anchor.get("root_offset") or 0.0)
        actors.append(mo.actor_row(
            name, role, next((r for r, member in roles.items() if member == name), ""),
            height_cm(C.get_character_profile(name) or {}),
            starts.get(name) or _figure_start(run, name),
            access={k: float(plan["access"][k]) for k in ("x", "y", "z", "yaw")},
            anchor=dict(x=float(anchor["x"]), y=float(anchor["y"]) - root, z=float(anchor["z"]),
                        yaw=float(anchor.get("yaw") or 0.0), root_offset=root),
            entry_mode=plan.get("entry_mode", "bridge"), sequence=sequence,
            reports_arrival=is_player_controlled(name)))
    now = _motion_now()
    issued_s = float(data.get("issued_s", now))
    eta_s = max((data.get("eta_s") or {}).values(), default=issued_s)
    speed = float(data.get("speed_m_s") or travel.get_travel_speed_m_s())
    awaits = "reaction" if (data.get("reaction") or {}).get("state") == "pending" else ""
    first = data["plans"][run["actor"]]["entry_anchor"]
    order = mo.new_order(
        "prop_action", issued_s=issued_s, eta_s=eta_s, flip_s=None if awaits else eta_s + entry_s,
        deadline_s=mo.deadline(issued_s, eta_s), actors=actors, speed_m_s=speed, gait="walk",
        status=_order_status(run), awaits=awaits,
        target=dict(location_id=target["location_id"], room_id=target["room_id"],
                    level=_room_level(target["location_id"], target["room_id"]),
                    floor_y=float(data["plans"][run["actor"]]["access"]["y"]),
                    placement_id=target["placement_id"], marker_id=first["marker_id"],
                    place_id=first["place_id"], slot=first["slot"], execution_id=run["execution_id"]))
    if definition["ability"] == "combined":
        ids = [p["id"] for p in definition["phases"]]
        order["phase"] = run["phase"] if run["phase"] in ids else ids[0]
    return order


def _entry_nominal_s(order) -> float:
    """The longest ``entry`` step of an order (its flip after the arrival)."""
    return max((float(s.get("nominal_s") or 0.0) for actor in order.get("actors") or []
                for s in actor.get("sequence") or [] if s.get("step") == "entry"), default=0.0)


def _publish_order(run):
    """Publish ``run``'s first order and keep it on the run (``data.order``);
    the caller persists the run. A failure costs the order, never the run."""
    from app.core import motion_orders as mo
    try:
        run["data"]["order"] = mo.publish(_order(run), names=store.people(run),
                                          locations=[run["target"]["location_id"]])
    except Exception:
        logger.exception("Prop action order failed: %s", run["execution_id"])


def _revise(run, **changes) -> None:
    """A change of ``run``'s order in place (spec 5b case 2): the fields in
    ``changes``, revision + 1, published, and the run saved. A set
    ``awaits`` drops ``flip_motion_s``. A run without an order (older than
    its publication) is only saved."""
    from app.core import motion_orders as mo
    order = run["data"].get("order")
    if order:
        try:
            revised = dict(order, **{k: round(v, 3) if isinstance(v, float) else v
                                     for k, v in changes.items()})
            if revised.get("awaits"):
                revised.pop("flip_motion_s", None)
            revised["revision"] = int(order.get("revision", 1)) + 1
            run["data"]["order"] = mo.publish(revised, names=store.people(run),
                                              locations=[run["target"]["location_id"]])
        except Exception:
            logger.exception("Prop action order revision failed: %s", run["execution_id"])
    _save(run)


def _enter_or_wait(run) -> bool:
    """Everyone has arrived: into the entry (True), or — a react run whose
    partner has not reacted yet — wait at the furniture (False), revising the
    order once to ``status waiting``, ``awaits reaction``, without flip.
    After such a wait (the reaction ran out, decision 8) the entry starts now;
    otherwise at the last logical arrival (``_begin_entry``)."""
    if not _awaits_reaction(run):
        waited = (run["data"].get("order") or {}).get("awaits") == "reaction"
        _begin_entry(run, at_s=_motion_now() if waited else None)
        return True
    order = run["data"].get("order") or {}
    if order and order.get("status") != "waiting":
        _revise(run, status="waiting", awaits="reaction")
    return False


def _order_ended(run, stood, walking=None):
    """The run is over (decision 19): its order stays published for the tail
    (decision 6) and is never revised to ``ended``; whoever really got up
    (``stood``, from _stand_up) gets ONE cancel order with a new id, each
    actor with its own ``stand``. ``walking`` (``{name: pos}``): members of an
    approaching run that held no place any more — they get a row without
    steps whose ``stand`` is where they stand. Members kept seated
    (keep_seated, a follow pose) are not in it. A failure costs the order,
    never the end."""
    from app.core import motion_orders as mo
    try:
        order = run["data"].get("order")
        if order:
            mo.retire(order["order_id"])
        stood = {name: d for name, d in stood.items() if name not in _SWITCH_HELD.get()}
        walking = {name: pos for name, pos in (walking or {}).items()
                   if pos and name not in stood and name not in _SWITCH_HELD.get()}
        if not stood and not walking:
            return
        from app.core.height import height_cm
        from app.core.pose_catalog import group_of
        from app.models.account import is_player_controlled
        target = run["target"]
        level = _room_level(target["location_id"], target["room_id"])
        roles = run["data"].get("clip_roles") or {}
        now = _motion_now()
        flip, actors, floor_y = now, [], 0.0
        for role, name in _members(run):
            if name in walking:
                pos = walking[name]
                floor_y = float(((run["data"]["plans"].get(name) or {}).get("access") or {}).get("y") or 0.0)
                point = dict(x=float(pos["x"]), y=floor_y, z=float(pos["z"]))
                row = mo.actor_row(
                    name, role, next((r for r, member in roles.items() if member == name), ""),
                    height_cm(C.get_character_profile(name) or {}),
                    dict(point, yaw=None, room_id=target["room_id"], level=level),
                    reports_arrival=is_player_controlled(name))
                row["stand"] = dict(x=round(point["x"], 3), y=round(floor_y, 3), z=round(point["z"], 3),
                                    yaw=_yaw_deg(C.get_avatar_sync_snapshot(name)))
                actors.append(row)
                continue
            if name not in stood:
                continue
            pose, before, after = stood[name]["pose"], stood[name]["before"], stood[name]["after"]
            _kind, exit_s = travel.exit_bridge_for_pose(pose)
            floor_y = float(((run["data"]["plans"].get(name) or {}).get("access") or {}).get("y") or 0.0)
            row = mo.actor_row(
                name, role, next((r for r, member in roles.items() if member == name), ""),
                height_cm(C.get_character_profile(name) or {}),
                dict(x=float(before["x"]), y=floor_y, z=float(before["z"]), yaw=None,
                     room_id=target["room_id"], level=level),
                sequence=[mo.step("exit", group_of(pose), pose, float(exit_s))],
                reports_arrival=is_player_controlled(name))
            row["stand"] = dict(x=round(float(after["x"]), 3), y=round(floor_y, 3),
                                z=round(float(after["z"]), 3), yaw=_yaw_deg(after))
            actors.append(row)
            flip = max(flip, now + float(exit_s))
        cancel = mo.new_order(
            "cancel", issued_s=now, eta_s=now, flip_s=flip, deadline_s=mo.deadline(now, now),
            actors=actors, speed_m_s=0.0, gait="walk", status="ended",
            target=dict(location_id=target["location_id"], room_id=target["room_id"],
                        level=level, floor_y=floor_y))
        mo.publish(cancel, names=[a["name"] for a in actors], locations=[target["location_id"]])
    except Exception:
        logger.exception("Prop action cancel order failed: %s", run["execution_id"])


#: Narrator lines per pose group of the place: taking it, and leaving it.
_SETTLE_LINES = {"seat": "{actor} sits down on the {prop}.",
                 "lie": "{actor} lies down on the {prop}.",
                 "ground": "{actor} settles down by the {prop}.",
                 "stand": "{actor} steps up to the {prop}."}
_LEAVE_LINES = {"seat": "{actor} gets up from the {prop}.",
                "lie": "{actor} gets up from the {prop}.",
                "ground": "{actor} gets up from the {prop}.",
                "stand": "{actor} steps away from the {prop}."}


def _held_pose(run):
    """The pose the run holds its actor in right now."""
    definition = run["definition"]
    if definition["ability"] == "combined":
        phase = next((p for p in definition["phases"] if p["id"] == run.get("phase")),
                     definition["phases"][0])
        return phase["pose_key"]
    return definition["pose_key"]


def _emit_lifecycle(event, run, **extra):
    """``prop_action.started`` (a run turned active) / ``prop_action.ended``
    (an active run finished): ``execution_id``, ``members``, ``pose_key``
    plus ``extra`` — after every lock, so a package may start or end its own
    state (a solo action has no pair hook of its own)."""
    from app.core.hooks import emit
    from app.core.keyed_lock import _after_locks
    payload = dict(execution_id=run["execution_id"], members=[n for _, n in _members(run)],
                   pose_key=_held_pose(run), **extra)
    _after_locks(lambda: emit(event, **payload))


def _narrate(run, key, *, literal=False, quiet=False, _query=None, **fmt):
    """One storyteller line in the run's room, in the actor's language, after
    every lock is released. The room has to SEE a figure sit down or get up —
    the perception stream is what the characters remember of the scene, and
    the player's chat shows it. ``literal``: ``key`` is the finished line
    (a partner's reaction), neither translated nor formatted. ``quiet``: the
    line stays out of the players' chat transcript (``pose_scene.quiet``).
    ``_query``: the caller's geometry (the admission's), which already holds
    the room's places and the prop document — the line needs only the
    piece's name; without one a fresh query is read. Delivered on the same
    thread (after its locks), the query's owner. Never raises."""
    from app.core.keyed_lock import _after_locks

    def deliver():
        try:
            from app.core.i18n import localized, t
            from app.core.perception import STORYTELLER_SPEAKER, VOLUME_NORMAL, record_utterance
            from app.core.pose_catalog import pose_label
            actor, target = run["actor"], run["target"]
            lang = C.get_character_language(actor)
            query = _query if _query is not None else places._GeometryQuery()
            place = next((p for p in query.room_places(target["location_id"], target["room_id"])
                          if p.get("placement_id") == target["placement_id"]), None) or {}
            document = query.prop_document(place["prop_id"]) if place.get("prop_id") else {}
            prop = localized(document or {}, "name", lang) or place.get("prop_id") or ""
            pose = pose_label(_held_pose(run), lang)
            record_utterance(
                speaker=STORYTELLER_SPEAKER,
                content=key if literal else t(key, lang).format(
                    actor=actor, partner=_join(run["members"]), prop=prop, pose=pose, **fmt),
                volume=VOLUME_NORMAL, location_id=target["location_id"], room_id=target["room_id"],
                source="prop_action", anchor=actor, quiet=quiet)
        except Exception as e:
            logger.debug("prop-action narration failed: %s", e)

    _after_locks(deliver)


def _quiet(run) -> bool:
    """Whether the start / end line of ``run``'s held pose leaves the
    players' chat (``pose_scene.quiet``). Never raises."""
    try:
        return pose_scene.quiet(_held_pose(run))
    except Exception as e:
        logger.debug("quiet narration check failed: %s", e)
        return False


def _tell_inviter(run, key, **fmt):
    """``key`` (formatted with ``fmt``) as a notice for the run's inviter when
    a player steers it: the HUD's notice banner shows unread notifications
    (``/play/notices``), and ``create_notification`` pushes the inviter's
    ``notices`` topic. An NPC inviter has the room line. After every lock;
    never raises."""
    from app.core.keyed_lock import _after_locks
    inviter, execution_id = run["actor"], run["execution_id"]

    def deliver():
        try:
            from app.models.account import is_player_controlled
            if not is_player_controlled(inviter):
                return
            from app.core.i18n import t
            from app.models.notifications import create_notification
            create_notification(inviter, t(key, C.get_character_language(inviter)).format(**fmt),
                                notification_type="prop_action", metadata={"execution_id": execution_id})
        except Exception as e:
            logger.debug("prop-action notice for %s failed: %s", inviter, e)

    _after_locks(deliver)


def _group_line(lines, run):
    from app.core.pose_catalog import get_catalog
    return lines.get((get_catalog("pose").get(_held_pose(run)) or {}).get("group"), "")


def _narrate_finish(run, before, status, reason, kept):
    """The line for a run that has just ended, from the status it had."""
    pair = run["definition"]["ability"] == "pair"
    if reason == "consent_declined":
        _narrate(run, "{invitee} does not feel like {pose} with {inviter} right now.",
                 inviter=run["actor"], invitee=run["data"].get("declined_by") or _join(run["members"]))
    elif reason == "consent_expired":
        # Who stayed silent, and who had agreed already (a group only: a
        # pair's one "yes" starts the run). Not a refusal — the line says so.
        consents = run["data"].get("consents") or {}
        silent = [m for m in run["members"] if consents.get(m) != "yes"] or run["members"]
        agreed = [m for m in run["members"] if consents.get(m) == "yes"]
        fmt = dict(inviter=run["actor"], silent=_join(silent))
        if agreed:
            key = "The invitation from {inviter} has expired — {silent} did not answer in time ({agreed} had agreed)."
            fmt["agreed"] = _join(agreed)
        else:
            key = "The invitation from {inviter} has expired — {silent} did not answer in time."
        _narrate(run, key, **fmt)
        _tell_inviter(run, key, **fmt)
    elif before in ("active", "sleeping"):
        # A pair ends through end_interaction, which tells the room itself;
        # a seat kept for the actor's next place or follow pose is no getting up.
        if pair or run["actor"] in kept:
            return
        if run["definition"]["ability"] == "sleep" and reason == "awake":
            _narrate(run, "{actor} wakes up and gets up from the {prop}.", quiet=_quiet(run))
        else:
            line = _group_line(_LEAVE_LINES, run)
            if line:
                _narrate(run, line, quiet=_quiet(run))
    elif before == "approaching" and status == "failed":
        _narrate(run, "{actor} does not get to the {prop} after all.")


@_internal_mutation()
def _finish(run, status, reason, *, keep_seated="", follow=False):
    """``follow``: a NORMAL end (a participant stops it, its phases are
    through) — whoever has a follow pose with an action of it on the same
    piece stays and switches into that (_follow_up) instead of standing up."""
    # State readers share this lock: terminal status and departure cleanup
    # become visible together, including server-side endings.
    with _lock(run["execution_id"]):
        if run["status"] in store.TERMINAL:
            return _result(run)
        before = run["status"]
        phases = []
        if run["status"] == "active" and run["definition"]["ability"] != "sleep":
            # Include the final online partial interval before any cleanup. _clock
            # has already advanced on scheduler paths, so this never counts twice.
            delta, _motion = _clock(run, game_time())
            if run["definition"]["ability"] == "combined":
                duration = sum(p["duration_game_s"] for p in run["definition"]["phases"])
                delta = min(delta, max(0, duration - run["data"].get("active_game_s", 0)))
                run["data"]["phase_elapsed"] += delta
            run["data"]["active_game_s"] = run["data"].get("active_game_s", 0) + delta
            phases.append("active")
        if status == "completed" and reason == "phases_completed":
            phases.append("success")
        follows = (_follow_targets(run) if follow and status == "completed" and before == "active" else {})
        kept = set(follows) | ({keep_seated} if keep_seated else set())
        run.update(status=status, reason=reason)
        run["data"]["cleanup_pending"] = True
        pose_scene.end_finales(run["execution_id"])
        _commit(run, phases)  # Terminal, effects and claim release precede cleanup.
        if before == "active":
            _emit_lifecycle("prop_action.ended", run, status=status, reason=reason)
        stood = _cleanup(run, keep=kept)
        if follows:
            stood.update(_follow_up(run, follows))
        # Whoever was still on the way (plan E3 Task 7: no journey holds it)
        # gets a cancel row as well: it stands where its order put it by now
        # (_walk_point), written as its position first. Only members whose
        # seat _start already released — a member _start failed on before its
        # write still sits.
        walking = {}
        if before == "approaching":
            now_s = _motion_now()
            for _role, name in _members(run):
                if name in kept or name in stood or (C.get_character_profile(name) or {}).get("place"):
                    continue
                point = _walk_point(run, name, now_s)
                if point is not None:
                    C.set_character_pos(name, point[0], point[1])
                walking[name] = C.get_character_pos(name)
        _order_ended(run, stood, walking)
        _narrate_finish(run, before, status, reason, kept)
        return _result(run)


@_internal_mutation()
def _cleanup(run, keep=()):
    """``keep``: members whose place stays — for the departure of the run
    replacing this one (_replace) or for their follow pose (_follow_up);
    everyone else stands up here. Returns ``{name: departure}`` of whoever
    really got up (_stand_up), for the cancel order of _order_ended."""
    reason = run["reason"]
    stood = {}
    for role, name in _members(run):
        jid = run["data"]["journey_ids"].get(name)
        if jid:
            travel.cancel_journey(name, journey_id=jid, execution_kind="prop_action", execution_ref=run["execution_id"], reason=reason)
        if name not in keep:
            departure = _stand_up(run, name)
            if departure:
                stood[name] = departure
    # Pair interaction cleanup can release both members itself. Capture and
    # release every owned place first, while its original pose still exists.
    for _role, name in _members(run):
        profile = C.get_character_profile(name)
        inter = profile.get("interaction") or {}
        if inter.get("execution_ref") == run["execution_id"]:
            from app.core.interaction_engine import end_interaction
            end_interaction(name, reason=reason, interaction_id=inter["id"], keep_places=keep)
    store.cleanup_finished(run["execution_id"], run["data"].get("exit_motions", {}))
    return stood


def _stand_up(run, name):
    """Release ``name``'s place of ``run``, recording the departure the
    client plays (``exit_motions``) when it really got up from it. Returns
    that departure (``{pose, before, after}``: the pose it left, its point
    before and after) when it got up, else None."""
    pose = C.get_effective_pose_key(name)
    before = C.get_character_pos(name)
    place = (C.get_character_profile(name) or {}).get("place") or {}
    held = place.get("execution_id") == run["execution_id"]
    released = C.release_prop_action_state(name, run["execution_id"])
    after = C.get_character_pos(name)
    if released and held and before and after:
        after["yaw"] = C.get_avatar_sync_snapshot(name)["yaw"]
        run["data"].setdefault("exit_motions", {})[name] = _exit_motion(pose, before, after)
        return dict(pose=pose, before=before, after=after)
    return None


#: How long an NPC stays in its follow pose (game seconds) before it gets up
#: by itself; the player's avatar stays until it is stopped.
FOLLOW_NPC_LIMIT_S = 20 * 60


def _ended_pose(run, name):
    """``(pose, clip role)`` ``name`` held when ``run`` ended: the last phase
    of a combined action; the clip role only for a pair."""
    definition = run["definition"]
    if definition["ability"] == "combined":
        return definition["phases"][-1]["pose_key"], ""
    roles = run["data"].get("clip_roles") or {}
    role = next((r for r, n in roles.items() if n == name), "") if definition["ability"] == "pair" else ""
    return definition["pose_key"], role


def _follow_targets(run):
    """``{name: action}``: who of ``run`` goes into a follow pose
    (``pose_catalog.follow_pose_for``) and through which solo action of the
    SAME piece — one holding exactly that pose, else one of its place type
    (the furniture_for_pose order). Nobody without such an action."""
    from app.core.pose_catalog import follow_pose_for, group_of
    if run["definition"]["ability"] not in ("pose", "pair", "combined"):
        return {}
    query = places._GeometryQuery()
    target = run["target"]
    piece = next((p for p in query.room_places(target["location_id"], target["room_id"])
                  if p.get("placement_id") == target["placement_id"]
                  and p.get("variant_uid") == target["variant_uid"]), None)
    if not piece:
        return {}
    actions = [a for a in query.prop_document(piece["prop_id"]).get("actions") or []
               if a.get("enabled") and a.get("ability") == "pose" and a.get("participants") == 1]
    out = {}
    for _role, name in _members(run):
        follow = follow_pose_for(*_ended_pose(run, name))
        if not follow:
            continue
        action = (next((a for a in actions if a.get("pose_key") == follow), None)
                  or next((a for a in actions if group_of(a.get("pose_key") or "") == group_of(follow)), None))
        if action:
            out[name] = action
    return out


def _follow_order(run, follows):
    """Who chooses a place first: the one nearest to a free slot of its
    follow's place type on the piece — on a single armchair after a shared
    pair seat, the role nearer to it keeps sitting."""
    from app.core.pose_catalog import group_of
    target = run["target"]
    inventory = places.room_places(target["location_id"], target["room_id"])

    def distance(name):
        pos = C.get_character_pos(name)
        group = group_of(follows[name].get("pose_key") or "")
        slots = [s for p in inventory if p.get("placement_id") == target["placement_id"]
                 and p.get("group") == group for s in p["slots"]]
        return min((math.dist((pos["x"], pos["z"]), (s[0], s[1])) for s in slots), default=math.inf) if pos else math.inf
    return sorted(follows, key=lambda n: (distance(n), n))


def _follow_up(run, follows):
    """Switch every member of the ended ``run`` named in ``follows`` into its
    follow action on the same piece, without walking (_settle_in_place) and
    claiming the nearest free slot of its place type. Whoever gets none (the
    piece is full, the action refuses) stands up as everyone else did.
    Returns ``{name: departure}`` of those (_stand_up)."""
    from app.models.account import get_all_avatars
    avatars = set(get_all_avatars())
    revision = None
    stood = {}
    for name in _follow_order(run, follows):
        action = follows[name]
        try:
            target = run["target"]
            query = places._GeometryQuery()
            piece = next(p for p in query.room_places(target["location_id"], target["room_id"])
                         if p.get("placement_id") == target["placement_id"]
                         and p.get("variant_uid") == target["variant_uid"])
            revision = props._document_revision(query.prop_document(piece["prop_id"]))
            definition, reason = _definition(target, action["id"], revision, _query=query)
            result = _refused(reason) if reason else None
            if not reason:
                now = game_time().canonical()
                fingerprint = store.encode([target, action["id"], revision, "", "follow", run["execution_id"]])
                follow = dict(execution_id=uuid.uuid4().hex, actor=name, members=[], request_id=None,
                              request_fingerprint=fingerprint, action_id=action["id"],
                              definition_revision=revision, status="approaching", phase="", reason="",
                              target=dict(target), definition=definition,
                              data=dict(plans={}, journey_ids={}, arrived=[], process=_PROCESS,
                                        last_game=now, last_motion=_motion_now(),
                                        follow_of=run["execution_id"],
                                        **({} if name in avatars else {"follow_limit_s": FOLLOW_NPC_LIMIT_S})))
                result, _created = _admit(follow, fingerprint, replaces=(run["execution_id"],), direct=True)
        except Exception:
            logger.exception("Follow pose for %s after %s failed", name, run["execution_id"])
            result = _refused("follow_error")
        if result.get("status") in ("refused", "failed", "cancelled"):
            logger.info("%s gets no follow pose after %s: %s", name, run["execution_id"], result.get("reason"))
            departure = _stand_up(run, name)
            if departure:
                stood[name] = departure
    store.cleanup_finished(run["execution_id"], run["data"].get("exit_motions", {}))
    return stood


def _left_behind(run):
    """Members of the run ``run`` follows on whose place that run still
    holds: switching one after the other, the second sits on its old seat
    (a pair's whole place) while the first already takes its new slot."""
    ref = run["data"].get("follow_of")
    old = store.get(ref) if ref else None
    if not old:
        return set()
    return {n for _, n in _members(old)
            if ((C.get_character_profile(n) or {}).get("place") or {}).get("execution_id") == ref}


def cancel_with_motion(actor: str, execution_id: str) -> dict:
    """``cancel`` plus, for a participant who was seated or lying, the
    stand-up its own client plays at once: the exit clip of the pose it held
    and the standing point the server put it on (``motion: null`` when the
    actor did not move)."""
    result = cancel(actor, execution_id)
    if result["status"] == "refused":
        return result
    run = store.get(execution_id)
    return dict(result, motion=run["data"].get("exit_motions", {}).get(actor))


def _exit_motion(pose, before, after):
    """The released place's departure, shared by state and cancel answers."""
    kind, seconds = travel.exit_bridge_for_pose(pose)
    if not kind:
        from app.core.animation_clips import clip_meta, resolve_pose_transition, rule_kind
        rule = resolve_pose_transition(pose, "standing") or {}
        kind = rule_kind(rule)
        seconds = float((clip_meta(kind) or {}).get("duration_s") or 0) if kind else 0.0
    return dict(seat=[before["x"], before["z"]], stand=[after["x"], after["z"]],
                exit_clip=kind, exit_s=round(seconds, 3),
                stand_yaw_deg=(None if after.get("yaw") is None
                               else math.degrees(float(after["yaw"]))))


def cancel(actor: str, execution_id: str) -> dict:
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or actor not in store.people(run):
            return _refused("not_participant")
        if run["status"] in store.TERMINAL:
            if run["data"].get("cleanup_pending"):
                _cleanup(run)
            return _result(run)
        if actor in run["members"] and _reacts(run) and run["status"] == "approaching":
            # The partner of a react run pushes it away before it begins.
            run["data"].setdefault("reaction", {}).update(state="resisted", feeling=-1)
            _narrate(run, "{partner} pushes {actor} away.")
            _book_reaction(run, False, -1, False)
            return _finish(run, "cancelled", "partner_resisted")
        normal = run["status"] == "active" and run["definition"]["ability"] in ("pose", "pair")
        return _finish(run, "completed" if normal else "cancelled", "ended" if normal else "cancelled",
                       follow=normal)


def _replaceable(actor, target, action_id):
    """The actor's own live run a new request ends first ("" = none).

    Choosing another action while seated means: stand up and go there. A
    sleeping run wakes through its own path, and asking again for the very
    action already running answers that run (``_same_run``).
    """
    held = store.held(store.person_key(actor))
    old = store.get(held) if held else None
    if (not old or old["status"] in store.TERMINAL or old["status"] == "sleeping"
            or (old["target"]["placement_id"] == target["placement_id"] and old["action_id"] == action_id)):
        return ""
    return held


def _replace(actor, execution_id):
    """End the actor's own run for a new request, with cancel()'s outcome.

    A solo actor already seated keeps its place: the new approach departs
    from the seat through the pose's exit clip, and start_approach_journey
    clears the place in its own write. The request stands it up if no new
    approach starts.
    """
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or run["status"] in store.TERMINAL:
            return
        normal = run["status"] == "active" and run["definition"]["ability"] in ("pose", "pair")
        seated = run["status"] == "active" and run["definition"]["ability"] in ("pose", "combined")
        _finish(run, "completed" if normal else "cancelled", "ended" if normal else "cancelled",
                keep_seated=actor if seated else "")


def _refs(replaces):
    """``replaces`` as a tuple of execution ids (one id or several)."""
    return tuple(r for r in ((replaces,) if isinstance(replaces, str) else replaces) if r)


def _freed(run, replaces):
    """Who gives a place up for ``run``: its two people and the members of
    the runs it replaces (their seat markers ``@prop:<id>`` as well)."""
    own = {name for _, name in _members(run)}
    for ref in replaces:
        old = store.get(ref)
        if old:
            own |= {name for _, name in _members(old)}
        own.add("@prop:" + ref)
    return own


def _member_replaceable(member, people):
    """An invitee's own live run a request ends ("" = none): one that
    involves nobody but ``people`` — sitting alone, or the action they
    already share. Asleep, or together with somebody else, it is busy."""
    held = store.held(store.person_key(member))
    old = store.get(held) if held else None
    if (not old or old["status"] in store.TERMINAL or old["status"] == "sleeping"
            or set(store.people(old)) - set(people)):
        return ""
    return held


def _replaced_runs(actor, members, target, action_id):
    """Every live run a request ends before its own begins: the actor's
    (_replaceable) and each invitee's (_member_replaceable)."""
    people = [actor, *members]
    refs = [_replaceable(actor, target, action_id)]
    refs += [_member_replaceable(member, people) for member in members]
    return tuple(dict.fromkeys(r for r in refs if r))


def _switches_in_place(run, replaces):
    """Whether everyone of ``run`` already sits in an active run on this very
    piece that the request ends: then there is no way to go and no entry to
    play — the new action begins where they are (_settle_in_place)."""
    for _, name in _members(run):
        held = store.held(store.person_key(name))
        old = store.get(held) if held in replaces else None
        if not old or old["status"] != "active" or old["target"] != run["target"]:
            return False
    return True


#: Packages that may keep a consent from carrying over to another action
#: (``hooks.register_provider(..., multiple=True)``), called as
#: ``fn(old_definition, new_definition) -> bool`` with copies of the two
#: action definitions; every provider must answer True. A provider that
#: raises counts as False: asking again is the safe side.
CONSENT_CARRIES = "prop_action.consent_carries"


def _consent_carries(run, replaces) -> bool:
    """Whether ``run``'s invitees agreed to what they do with the actor
    already, so another action on the same piece asks nobody again:

    * the actor and every invitee hold ONE active run, which the request
      ends (``replaces``) — so the new people are among its people; one of
      them may stay out, but anybody new is asked, and with him everyone
      (one invitation, one rule for all its answers);
    * on this very piece, everyone in place (_switches_in_place);
    * every invitee agreed to that run — requested it, or said "yes" to its
      invitation (a carried consent counts as that "yes" again); the partner
      of a "react" run never agreed;
    * no package refuses (``CONSENT_CARRIES``)."""
    invitees = run["members"]
    if not invitees:
        return False
    held = {store.held(store.person_key(name)) for name in store.people(run)}
    ref = held.pop() if len(held) == 1 else None
    old = store.get(ref) if ref and ref in replaces else None
    if not old or old["status"] != "active" or old["target"] != run["target"]:
        return False
    if not set(store.people(run)) <= set(store.people(old)) or not _switches_in_place(run, replaces):
        return False
    consents = old["data"].get("consents") or {}
    if any(name != old["actor"] and (_reacts(old) or consents.get(name) != "yes") for name in invitees):
        return False
    from copy import deepcopy
    from app.core.hooks import get_providers
    for fn in get_providers(CONSENT_CARRIES):
        try:
            if fn(deepcopy(old["definition"]), deepcopy(run["definition"])) is not True:
                return False
        except Exception as e:
            logger.warning("consent provider %s failed: %s", getattr(fn, "__qualname__", fn), e)
            return False
    return True


#: Who a switch in place (_settle_in_place) takes over while the runs it
#: replaces end: the cleanup of a replaced pair stands its members up for a
#: moment, but the new run seats them again at once — for the order they are
#: held, so the replaced run's end publishes no cancel for them (plan E3
#: decision 19; the new order begins without exit).
_SWITCH_HELD = ContextVar("prop_action_switch_held", default=frozenset())


@contextmanager
def _replacing(run, replaces, direct=False):
    """End ``replaces`` for ``run`` (_replace); afterwards whoever kept a seat
    for the departure stands up, unless the new run has taken it over.
    ``direct``: ``run`` switches in place (_SWITCH_HELD)."""
    owners = []
    held = _SWITCH_HELD.set(frozenset(store.people(run)) if direct else frozenset())
    try:
        for ref in replaces:
            old = store.get(ref)
            if not old:
                continue
            name = next((n for _, n in _members(run) if n in store.people(old)), run["actor"])
            _replace(name, ref)
            owners.append((name, ref))
    finally:
        _SWITCH_HELD.reset(held)
    try:
        yield
    finally:
        for name, ref in owners:
            C.release_prop_action_state(name, ref)


def _launch(run, direct):
    """Start an admitted run: the approach, or the switch in place."""
    if direct:
        _settle_in_place(run)
    else:
        _start_checked(run)


def _settle_in_place(run):
    """A switch on the piece both already use (_switches_in_place): nobody
    walks and no entry clip plays. The two count as arrived at their access
    points and go straight into the new action. A react run does not wait
    for the partner's reaction here: it is already under way, and a reaction
    that pushes it away ends it (react)."""
    try:
        data = run["data"]
        for plan in data["plans"].values():
            plan["entry_mode"] = "direct"
        data["arrived"] = [name for _, name in _members(run)]
        data["order_starts"] = {name: _figure_start(run, name) for _, name in _members(run)}
        _publish_order(run)   # persisted by the commit below
        _commit(run, runtime={name: dict(pos_x=data["plans"][name]["access"]["x"],
                                         pos_z=data["plans"][name]["access"]["z"],
                                         pos_session=None, pos_seq=None)
                              for _role, name in _members(run)})
        _begin_entry(run)
    except Exception:
        logger.exception("Prop action switch in place failed: %s", run["execution_id"])
        _finish(store.get(run["execution_id"]) or run, "failed", "approach_start_error")


def interrupt_after_locks(actor, reason, *, execution_id=""):
    if _INTERNAL_MUTATION.get():
        return
    from app.core.keyed_lock import _after_locks
    _after_locks(lambda: interrupt(actor, reason, execution_id=execution_id))


def presence_changed(location_id, room_id):
    """Immediate optional presence policy, including transient third arrivals."""
    if _INTERNAL_MUTATION.get():
        return
    for snapshot in store.live_runs():
        if (snapshot["status"] not in ("active", "sleeping") or
                not snapshot["definition"]["interrupt_on_presence_change"] or
                (snapshot["target"]["location_id"], snapshot["target"]["room_id"]) != (location_id, room_id)):
            continue
        with _lock(snapshot["execution_id"]):
            run = store.get(snapshot["execution_id"])
            if run["status"] in ("active", "sleeping"):
                reason = _validate(run, require_claims=True)
                if reason:
                    _finish(run, "cancelled", reason)


#: What does not end an open invitation: it holds no place and no route yet,
#: and a "yes" checks and plans everything anew (_respond) — a step, a new
#: pose or the walk to a seat in between changes nothing about the question.
_INVITATION_SURVIVES = frozenset(("position", "pose", "journey"))


def interrupt(actor, reason, *, execution_id=""):
    """Mutation boundaries call before profile locks; no broad cancellation."""
    if _INTERNAL_MUTATION.get():
        return
    for run in store.live_runs():
        if actor not in store.people(run) or (execution_id and run["execution_id"] != execution_id):
            continue
        if run["status"] == "awaiting_consent" and reason in _INVITATION_SURVIVES:
            continue
        with _lock(run["execution_id"]):
            current = store.get(run["execution_id"])
            if current["status"] not in store.TERMINAL:
                _finish(current, "completed" if reason == "awake" and current["status"] == "sleeping" else "cancelled", reason)


def _motion_now() -> float:
    """The motion clock as stored on a run (``last_motion``, milliseconds)."""
    return round(timeutils.motion_time(), 3)


def _clock(run, now):
    """Advance a run's two clocks to ``now`` and return ``(game_delta,
    motion_delta)``: GAME seconds for what is gameplay (phases, gauges, the
    invitation), MOTION-clock (real) seconds for what moves (the approach
    deadline, the entry clip). Both are 0.0 after a restart or while frozen."""
    data = run["data"]
    previous = GameTime.parse(data["last_game"])
    gap = max(0, (now - previous).total_seconds)
    now_s = _motion_now()
    motion_gap = max(0.0, now_s - float(data.get("last_motion", now_s)))
    restarted = data["process"] != _PROCESS
    if restarted:
        # Reanchor every still-owned real journey before travel may advance it.
        # Downtime is shifted out on the motion clock the journey runs on.
        from app.core.keyed_lock import keyed_lock
        for role, name in _members(run):
            with keyed_lock("character_profile", name):
                profile = C.get_character_profile(name)
                journey = profile.get("journey")
                if journey and _own_journey(run, name, journey):
                    checkpoint = float(journey.get("position_checkpoint_s",
                                                   data.get("last_motion", now_s)))
                    anchored = float(journey.get("prop_action_reanchored_at_s", checkpoint))
                    shift = max(0.0, now_s - max(checkpoint, anchored))
                    journey["started_at_s"] = round(float(journey["started_at_s"]) + shift, 3)
                    journey["prop_action_reanchored_at_s"] = now_s
                    if not C.save_character_profile(name, profile):
                        raise RuntimeError("prop_action_reanchor_write_failed")
        data["process"] = _PROCESS
    data["last_game"] = now.canonical()
    data["last_motion"] = now_s
    if restarted or is_world_frozen():
        return 0.0, 0.0
    return float(gap), float(motion_gap)


@contextmanager
def owner_guard(actor, journey):
    ref = journey.get("execution_ref", "")
    with _lock(ref):
        run = store.get(ref)
        allowed = bool(run and run["status"] == "approaching" and actor in store.people(run)
                       and _own_journey(run, actor, journey))
        if allowed:
            # On restart pause this ticker snapshot: _clock rewrites its exact
            # stored start, so Core's snapshot equality rejects the stale tick.
            restarted = run["data"]["process"] != _PROCESS
            if restarted:
                _clock(run, game_time())
                _save(run)
            reason = _validate(run, require_claims=True)
            data = run["data"]
            elapsed = data.get("elapsed", 0.0) + max(0.0, _motion_now() - float(data.get("last_motion", _motion_now())))
            if not is_world_frozen() and elapsed > run["data"].get("deadline", 60):
                reason = "approach_timeout"
            if reason:
                _finish(run, "failed", reason)
                allowed = False
            allowed = allowed and not restarted and not is_world_frozen()
        else:
            # False is only a pause for a VALID frozen/reanchored run. Missing,
            # terminal or mismatched authority must remove this exact journey.
            travel.cancel_journey(actor, journey_id=journey.get("journey_id"),
                execution_kind="prop_action", execution_ref=ref, reason="journey_owner_mismatch")
            if run and run["status"] not in store.TERMINAL:
                _finish(run, "failed", "journey_owner_mismatch")
        yield allowed


def _arrival_validate(actor, journey, room_id):
    run = store.get(journey["execution_ref"])
    if not run or run["status"] != "approaching" or not _own_journey(run, actor, journey):
        return False, "journey_owner_mismatch"
    reason = _validate(run, require_claims=True)
    if reason:
        return False, reason
    if room_id != run["target"]["room_id"]:
        return False, "room_mismatch"
    return True, ""


def _arrived(actor, journey):
    with _lock(journey["execution_ref"]):
        run = store.get(journey["execution_ref"])
        if not run or run["status"] != "approaching" or not _own_journey(run, actor, journey):
            return
        if actor not in run["data"]["arrived"]:
            run["data"]["arrived"].append(actor)
            _save(run)
        if len(run["data"]["arrived"]) == len(_members(run)):
            _enter_or_wait(run)


def _arrived_callback(actor, journey):
    _arrived(actor, journey)


def _cancelled(actor, journey, reason):
    with _lock(journey.get("execution_ref", "")):
        run = store.get(journey.get("execution_ref", ""))
        if run and run["status"] not in store.TERMINAL and _own_journey(run, actor, journey):
            _finish(run, "cancelled" if reason in ("cancelled", "pose", "position") else "failed", reason)


def register_owner():
    travel.register_execution_owner("prop_action", guard=owner_guard, validate_arrival=_arrival_validate,
                                    arrived=_arrived_callback, cancelled=_cancelled)


def _entry_capability(pose):
    """The same static clip guard used before routing and at actual entry."""
    from app.core.animation_clips import resolve_pose_transition, clip_meta, _solo_kinds, rule_kind
    # The pose's own rule, else its group's (walking → @seat), including pair
    # poses' catalog groups.
    rule = resolve_pose_transition("walking", pose)
    if not rule:
        return None, "missing_entry_transition"
    kind = rule_kind(rule)
    meta = clip_meta(kind)
    if kind not in _solo_kinds() or not meta or meta.get("pair"):
        return None, "missing_entry_transition"
    try:
        duration = float(meta.get("duration_s", 0))
    except (TypeError, ValueError, OverflowError):
        return None, "missing_entry_transition"
    if not math.isfinite(duration) or duration <= 0:
        return None, "missing_entry_transition"
    return (kind, meta), ""


def _entry_spec(name, plan, pose, *, _query=None):
    if plan.get("entry_mode") == "direct":
        return dict(kind="", duration_s=0.0, pose_key=pose), ""
    from app.core.animation_clips import clip_travel_m, clip_ref_height_m
    from app.core.room_stand import bridge_offset, bridge_scale
    from app.core.height import height_cm
    capability, reason = _entry_capability(pose)
    if reason:
        return None, reason
    kind, meta = capability
    anchor, access = plan["entry_anchor"], plan["access"]
    query = _query if _query is not None else places._GeometryQuery()
    delta = bridge_offset(clip_travel_m(kind), float(access["yaw"]),
                          bridge_scale(height_cm(query.profile(name)), clip_ref_height_m(kind)))
    if math.dist((access["x"] + delta[0], access["z"] + delta[1]), (anchor["x"], anchor["z"])) > .05:
        return None, "entry_transition_mismatch"
    from app.core.prop_action_paths import access_space
    geometry = query.room_geometry(anchor["location_id"], anchor["room_id"])
    if not geometry or not access_space(geometry, anchor["placement_id"]).visible(
            (access["x"], access["z"]), (anchor["x"], anchor["z"])):
        return None, "entry_transition_blocked"
    # The clip's own REAL length: the entry runs on the motion clock.
    return dict(kind=kind, duration_s=float(meta["duration_s"]), pose_key=pose), ""


def _begin_entry(run, at_s=None):
    """Into the entry clip: every member written exactly onto its ``access``
    (a no-op for whoever arrived there already), the order revised to
    ``entering`` with ``flip`` = ``at_s`` + the entry's nominal seconds —
    ``at_s`` defaults to the last logical arrival (an NPC's own eta, a
    player's report), so an NPC run flips exactly when its first order said.
    The profile field ``prop_action_entry`` is no longer written: the order
    tells every client what plays (plan E3 Task 7)."""
    reason = _validate(run, require_claims=True)
    if reason:
        _finish(run, "failed", reason)
        return
    definition = run["definition"]
    pose = (definition["phases"][0]["pose_key"] if definition["ability"] == "combined" else definition["pose_key"])
    entries = {}
    for _role, name in _members(run):
        spec, reason = _entry_spec(name, run["data"]["plans"][name], pose)
        if reason:
            _finish(run, "failed", reason)
            return
        entries[name] = spec
    data = run["data"]
    now_s = _motion_now()
    if at_s is None:
        at_s = max((float(s) for s in (data.get("arrived_s") or {}).values()), default=now_s)
    order = data.get("order") or {}
    entry_s = (_entry_nominal_s(order) if order
               else max(float(e["duration_s"]) for e in entries.values()))
    if not any(e["duration_s"] for e in entries.values()):
        entry_s = 0.0
    flip = round(float(at_s) + entry_s, 3)
    run["phase"] = "entry"
    data.pop("entry_elapsed", None)
    data.update(entries=entries, entry_started_s=round(float(at_s), 3), flip_s=flip,
                last_game=game_time().canonical(), last_motion=now_s)
    with _internal_mutation():
        # Display the bridge at the exact access; no place/body anchor until it ends.
        _commit(run, runtime={name: dict(pos_x=data["plans"][name]["access"]["x"],
                                         pos_z=data["plans"][name]["access"]["z"],
                                         pos_session=None, pos_seq=None, prop_action_entry=None)
                              for _role, name in _members(run)})
    _revise(run, status="entering", awaits="", flip_motion_s=flip)
    if not entry_s:
        _activate(run)
    else:
        _wake_ticker()


def _arrive(run, name, at_s):
    """One member is at its access (an NPC at its own eta, a player through
    ``arrived``): its position is written exactly onto the access FIRST — the
    run's ``_validate`` holds every member in ``arrived`` to it
    (``access_position_lost``) — and only then it is entered in ``arrived``,
    with ``at_s`` as its logical arrival second."""
    data = run["data"]
    access = data["plans"][name]["access"]
    with _internal_mutation():
        _commit(run, runtime={name: dict(pos_x=access["x"], pos_z=access["z"], pos_session=None, pos_seq=None)})
    if name not in data["arrived"]:
        data["arrived"].append(name)
    data.setdefault("arrived_s", {})[name] = round(float(at_s), 3)
    _save(run)


def _walk_point(run, name, now_s):
    """Where ``name``'s order has it at motion second ``now_s`` while it walks
    (plan E3 Task 7): the point on its planned polyline after
    ``(now_s - issued_s - exit_s) * speed_m_s`` metres (the walk the client
    plays from the published order), at the earliest the polyline's first
    point (where the exit ends), at the latest its last (the access). None
    when it has arrived (it stands on its access) or the run never started
    (no ``issued_s``: it never left its place)."""
    data = run["data"]
    if name in data.get("arrived", []) or data.get("issued_s") is None:
        return None
    plan = data["plans"].get(name) or {}
    points = [(float(p[0]), float(p[1])) for p in plan.get("waypoints") or []]
    if not points:
        return None
    departure = plan.get("departure_seat")
    exit_s = float(departure["exit_s"]) if isinstance(departure, dict) else 0.0
    left = max(0.0, (float(now_s) - float(data["issued_s"]) - exit_s) * float(data.get("speed_m_s") or 0.0))
    for a, b in zip(points, points[1:]):
        leg = math.dist(a, b)
        if leg > 0 and left <= leg:
            f = left / leg
            return (round(a[0] + (b[0] - a[0]) * f, 3), round(a[1] + (b[1] - a[1]) * f, 3))
        left -= leg
    return points[-1]


def quiet_report():
    """The context ``/play/pos`` writes a quiet report in (``pos_report_mode``
    == "quiet"): the avatar's own approaching run does not take the write
    for an interruption."""
    return _internal_mutation()


def migrate_cancel(execution_id: str) -> None:
    """Boot (a) of plan E3: an approaching run from before the orders (it
    walks a journey, carries no ``data.order``) is cancelled, its slot freed."""
    with _lock(execution_id):
        run = store.get(execution_id)
        if run and run["status"] == "approaching" and not run["data"].get("order"):
            _finish(run, "cancelled", "e3_migration")


def shift_run(execution_id: str, shift_s: float, alive_s) -> None:
    """Boot (c) of plan E3 (decision 7c/7d): shift every absolute motion
    second of a live run and of its order by the downtime ``shift_s``,
    revision + 1, republished. The order is marked ``boot_alive_s`` =
    ``alive_s`` (the stamp the downtime was measured from); an order that
    already carries that mark was shifted by a previous boot and is left."""
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or run["status"] in store.TERMINAL or shift_s <= 0:
            return
        data = run["data"]
        order = data.get("order")
        if not order or order.get("boot_alive_s") == alive_s:
            return
        def moved(value):
            return round(float(value) + shift_s, 3)
        for key in ("issued_s", "flip_s", "deadline_s", "entry_started_s", "last_motion"):
            if data.get(key) is not None:
                data[key] = moved(data[key])
        for key in ("eta_s", "arrived_s"):
            if isinstance(data.get(key), dict):
                data[key] = {name: moved(s) for name, s in data[key].items()}
        changes = {key: moved(order[key]) for key in
                   ("issued_motion_s", "eta_motion_s", "flip_motion_s", "deadline_motion_s")
                   if order.get(key) is not None}
        _revise(run, boot_alive_s=alive_s, **changes)


def _order_run(actor, order_id):
    """The live run whose published order is ``order_id`` and has ``actor``
    in it, or None."""
    for run in store.live_runs():
        if (actor in store.people(run)
                and (run["data"].get("order") or {}).get("order_id") == order_id):
            return run
    return None


def arrived(actor: str, order_id: str, x: float, z: float, yaw: float, room_id: str) -> dict:
    """The player's figure reports that it stands at its access (``POST
    /play/order/arrived``): ``{"ok": True}``, or a refusal — ``order_unknown``
    (no live approach of ``actor`` under that order), ``arrive_too_far``
    (``ARRIVE_TOL_M`` or more from the access), ``room_mismatch`` (another
    room reported, or the actor stands elsewhere) or the reason ``_validate``
    gives (the run then fails). A repeated report after the arrival is ok.
    Everyone there and no reaction open → the entry starts (``_begin_entry``)."""
    from app.core import motion_orders as mo
    try:
        x, z, yaw = float(x), float(z), float(yaw)
        if not (math.isfinite(x) and math.isfinite(z) and math.isfinite(yaw)):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return _refused("invalid_request")
    if not isinstance(actor, str) or not isinstance(order_id, str) or not order_id:
        return _refused("order_unknown")
    found = _order_run(actor, order_id)
    if not found:
        return _refused("order_unknown")
    with _lock(found["execution_id"]):
        run = store.get(found["execution_id"])
        if (not run or run["status"] != "approaching" or actor not in store.people(run)
                or (run["data"].get("order") or {}).get("order_id") != order_id):
            return _refused("order_unknown")
        if run["phase"] == "entry" or actor in run["data"]["arrived"]:
            return {"ok": True}
        access = run["data"]["plans"][actor]["access"]
        if math.dist((x, z), (float(access["x"]), float(access["z"]))) >= mo.ARRIVE_TOL_M:
            return _refused("arrive_too_far")
        target = run["target"]
        if room_id != target["room_id"] or places.where(actor) != (target["location_id"], target["room_id"]):
            return _refused("room_mismatch")
        reason = _validate(run, require_claims=True)
        if reason:
            _finish(run, "failed", reason)
            return _refused(reason)
        _arrive(run, actor, _motion_now())
        if len(run["data"]["arrived"]) == len(_members(run)):
            _enter_or_wait(run)
        return {"ok": True}


def pos_report_mode(avatar: str, x: float, z: float) -> str:
    """How ``/play/pos`` treats a report of ``avatar`` while one of its runs
    approaches: ``"owned"`` — it has arrived or the entry plays, the server
    holds the figure on its access and the report is dropped; ``"quiet"`` —
    still walking and the point lies in the target room, written without
    ending the run; ``""`` — no approaching run, or the point lies elsewhere
    (the write ends the run as any position change does)."""
    held = store.held(store.person_key(avatar))
    run = store.get(held) if held else None
    if not run or run["status"] != "approaching":
        return ""
    if run["phase"] == "entry" or avatar in run["data"].get("arrived", []):
        return "owned"
    from app.core.furnish_geometry import point_in_poly
    target = run.get("target") or {}
    if not target.get("location_id") or not target.get("room_id"):
        return ""
    geometry = places._GeometryQuery().room_geometry(target["location_id"], target["room_id"])
    if geometry and point_in_poly((float(x), float(z)), geometry[0]):
        return "quiet"
    return ""

def _activate(run):
    reason = _validate(run, require_claims=True)
    if reason:
        _finish(run, "failed", reason)
        return
    from app.core.effect_application import effect_catalogs
    catalogs = effect_catalogs()
    ability = run["definition"]["ability"]
    pose = next(iter(run["data"]["entries"].values()))["pose_key"]
    # Build the desired lifecycle, but do not persist it separately from the
    # real entry state and start effects. A failed commit remains at entry.
    def entered(runtime):
        run["status"] = "active"
        run["phase"] = run["definition"]["phases"][0]["id"] if ability == "combined" else "active"
        if ability == "sleep":
            run["phase"] = "sleep_pending"
        run["data"].update(phase_elapsed=0.0, active_game_s=0.0, last_game=game_time().canonical(),
                           last_motion=_motion_now())
        _commit(run, ("start",), runtime=runtime, catalogs=catalogs)
    with keyed_lock("places", run["target"]["location_id"]):
        if ability == "pair":
            from app.core.interaction_engine import start_interaction_at
            try:
                interaction = start_interaction_at(store.people(run), pose,
                                                   execution_id=run["execution_id"],
                                                   plans=run["data"]["plans"], commit_profiles=entered)
            except ValueError as exc:
                # Validation failures are refusals, not synthetic entry success.
                run = store.get(run["execution_id"])
                _finish(run, "failed", str(exc))
                return
            # The furniture counterpart of ``interaction.invite_started``: the
            # pair or group is live. Consent was the run's, not an
            # invitation's, so a package that starts a state with a pair pose
            # listens here too (``interaction.ended`` covers every ending).
            # ``members``: everyone, the initiator first.
            from app.core.hooks import emit
            from app.core.keyed_lock import _after_locks
            _after_locks(lambda: emit("prop_action.group_started", execution_id=run["execution_id"],
                                      interaction=interaction, actor=run["actor"],
                                      members=store.people(run)))
        else:
            name = run["actor"]
            anchor = run["data"]["plans"][name]["entry_anchor"]
            place = dict(id=anchor["place_id"], slot=anchor["slot"],
                         room_id=run["target"]["room_id"], execution_id=run["execution_id"])
            entered({name: dict(pose_key=pose, pose_flavor="", place=place, prop_action_entry=None,
                                pos_x=anchor["x"], pos_z=anchor["z"], pos_session=None, pos_seq=None)})
    if run["status"] == "active":
        _revise(run, status="active")
        _emit_lifecycle("prop_action.started", run, ability=ability)
    if ability != "pair":
        C._publish_activity_changed(run["actor"], pose, "", pose, place, None)
        line = ("{actor} lies down on the {prop} to sleep." if ability == "sleep"
                else _group_line(_SETTLE_LINES, run))
        if line:
            _narrate(run, line, quiet=_quiet(run))
    if ability == "sleep":
        _resume_sleep(run)


@_internal_mutation()
def _resume_sleep(run):
    """Reconcile either crash window around the actual canonical flag write."""
    reason = _validate(run, require_claims=True, presence=(
        not C.is_character_sleeping(run["actor"]) or run["definition"]["interrupt_on_presence_change"]))
    if reason:
        _finish(run, "failed", reason)
        return
    run["phase"] = "sleep_pending"
    _save(run)
    if not C.is_character_sleeping(run["actor"]):
        C.set_is_sleeping(run["actor"], True, _prop_execution=run["execution_id"])
    if not C.is_character_sleeping(run["actor"]):
        _finish(run, "failed", "sleep_transition_failed")
        return
    run["status"], run["phase"] = "sleeping", "sleeping"
    # The actual canonical flag has committed. Recovery from either side of
    # that flag write reaches this one receipt/run transaction exactly once.
    _commit(run, ("success",))


#: Runs whose scheduler step raised: execution_id -> (consecutive failures,
#: SYSTEM monotonic stamp of the last one). A step's effects and progress
#: share one transaction, so a failed step rolled back and is simply tried
#: again — a passing fault (a busy database) costs nothing. STEP_FAIL_LIMIT
#: failures in a row end the run (``_abort_failed_step``); ``due_in_s`` gives
#: a failed run no beat for STEP_RETRY_S, so the travel ticker never retries
#: it on its 0.1 s overdue beat.
_STEP_FAILED: dict = {}
STEP_FAIL_LIMIT = 3
STEP_RETRY_S = 5.0
#: Terminal runs whose pending cleanup raised, and runs whose end itself
#: failed (each logged once).
_CLEANUP_FAILED: set = set()
_END_FAILED: set = set()


def _step_failed(execution_id):
    """Book one failed step of ``execution_id`` (inside ``advance``'s except
    branch); the traceback is logged for the first failure in a row only.
    The limit reached, the run is ended."""
    count = _STEP_FAILED.get(execution_id, (0, 0.0))[0] + 1
    _STEP_FAILED[execution_id] = (count, time.monotonic())
    if count == 1:
        logger.exception("prop action %s: step failed, retried (ended after %d failures in a row)",
                         execution_id, STEP_FAIL_LIMIT)
    if count >= STEP_FAIL_LIMIT:
        _abort_failed_step(execution_id)


def _abort_failed_step(execution_id):
    """End a run whose step kept failing, so it neither keeps its claims nor
    its people.

    The regular end first (``_finish`` "failed"/"engine_error": final
    effects, claim release, cleanup). When that raises as well — its final
    effect commit reads the same state that keeps failing — the run is ended
    WITHOUT effects: the terminal save drops its claims in the same write,
    and ``_cleanup`` releases the people (a cleanup that raises stays
    pending and ``advance`` retries it). A run that cannot even be saved
    terminal keeps its failure record and is tried again by the next
    ``advance`` (``due_in_s`` still holds its beat back for STEP_RETRY_S)."""
    try:
        with _lock(execution_id):
            run = store.get(execution_id)
            if run and run["status"] not in store.TERMINAL:
                logger.warning("prop action %s: step failed %d times in a row, ending the run",
                               execution_id, STEP_FAIL_LIMIT)
                try:
                    _finish(run, "failed", "engine_error")
                except Exception:
                    logger.exception("prop action %s: regular end failed, ending it without effects",
                                     execution_id)
                run = store.get(execution_id)
                if run and run["status"] not in store.TERMINAL:
                    run.update(status="failed", reason="engine_error")
                    run["data"]["cleanup_pending"] = True
                    pose_scene.end_finales(execution_id)
                    _save(run)
                    try:
                        _cleanup(run)
                    except Exception:
                        # Saved terminal with cleanup_pending: advance retries it.
                        _CLEANUP_FAILED.add(execution_id)
                        logger.exception("prop action %s: cleanup failed, retried each tick",
                                         execution_id)
        _STEP_FAILED.pop(execution_id, None)
        _END_FAILED.discard(execution_id)
    except Exception as exc:
        _STEP_FAILED[execution_id] = (STEP_FAIL_LIMIT, time.monotonic())
        if execution_id not in _END_FAILED:
            _END_FAILED.add(execution_id)
            logger.warning("prop action %s: could not end the run (%s), tried again next tick",
                           execution_id, exc)


def _count_ticker(key: str) -> None:
    """Count one client-execution ticker event (hot-path line
    ``client_exec_ticker``); a counter never breaks the tick."""
    try:
        from app.core import hot_path_stats
        hot_path_stats.count("client_exec_ticker", key)
    except Exception:  # noqa: BLE001 — a counter, never a failure
        pass


def advance(now: GameTime, *, due_only: bool = False) -> int:
    """One scheduler step over every live run. Besides the run lifecycle it
    drops expired finales and beats each run that spent online game time
    active (``pose_scene.emit_active`` → hook ``scene.active``, kind
    "prop_action") — the beat a package counts on (a frozen world and
    offline time give none).

    Each run steps on its own: one that raises is rolled back, logged and
    retried, the others still advance; STEP_FAIL_LIMIT failures in a row end
    it (``_step_failed``).

    ``due_only`` (the travel ticker's beat): only the runs whose next timed
    step is due (``_is_due``) are stepped; the full round (``periodic_jobs``)
    steps every run."""
    _count_ticker("advance")
    register_owner()
    advanced = 0
    beats = []
    for pending in store.pending_cleanup():
        try:
            with _lock(pending["execution_id"]):
                _cleanup(pending)
            _CLEANUP_FAILED.discard(pending["execution_id"])
        except Exception:
            # Stays pending and is tried again next tick; logged once.
            if pending["execution_id"] not in _CLEANUP_FAILED:
                _CLEANUP_FAILED.add(pending["execution_id"])
                logger.exception("prop action %s: cleanup failed, retried each tick",
                                 pending["execution_id"])
    for snapshot in store.live_runs():
        execution_id = snapshot["execution_id"]
        if _STEP_FAILED.get(execution_id, (0, 0.0))[0] >= STEP_FAIL_LIMIT:
            # Its end failed last time: try ending it again, no further step.
            _abort_failed_step(execution_id)
            continue
        if due_only and not _is_due(snapshot, now):
            continue
        try:
            _count_ticker("advance_run")
            advanced += _advance_run(execution_id, now, beats)
        except Exception:
            _step_failed(execution_id)
        else:
            _STEP_FAILED.pop(execution_id, None)
    pose_scene.end_finales(expired_only=True)
    for beat in beats:
        pose_scene.emit_active(**beat)
    return advanced


def _advance_run(execution_id, now, beats) -> int:
    """One scheduler step of one live run (``advance``): 1 when it moved,
    0 when it was skipped. A due active beat is appended to ``beats``."""
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or run["status"] in store.TERMINAL:
            return 0
        delta, motion_delta = _clock(run, now)
        if is_world_frozen():
            _save(run)
            return 0
        if run["status"] == "active" and run["definition"]["ability"] != "sleep":
            if run["definition"]["ability"] == "combined":
                duration = sum(p["duration_game_s"] for p in run["definition"]["phases"])
                delta = min(delta, max(0, duration - run["data"].get("active_game_s", 0)))
            run["data"]["active_game_s"] += delta
        if (run["status"] == "sleeping" and not C.is_character_sleeping(run["actor"])
                and store.db.get_connection().execute("SELECT 1 FROM characters WHERE name=?", (run["actor"],)).fetchone()):
            _finish(run, "completed", "awake")
            return 0
        if run["status"] == "active" and run["definition"]["ability"] == "sleep":
            _resume_sleep(run)
            return 1
        # An invitation leaves the two's current runs going until the
        # "yes" (request_with_creation): those are not a busy participant.
        invited = run["status"] == "awaiting_consent"
        _count_ticker("advance_validate")
        reason = _validate(run, require_claims=not invited,
                           presence=run["status"] in ("awaiting_consent", "approaching") or run["definition"]["interrupt_on_presence_change"],
                           replaces=_replaced_runs(run["actor"], run["members"], run["target"], run["action_id"])
                           if invited else ())
        if reason:
            _finish(run, "failed", reason)
            return 0
        data = run["data"]
        phase_before = run["phase"]
        if run["status"] == "awaiting_consent":
            # The invitation waits on the motion clock (real seconds the
            # world ran), never on game time: see CONSENT_WINDOW_S.
            data["consent_wait_s"] = data.get("consent_wait_s", 0.0) + motion_delta
            if data["consent_wait_s"] >= consent_window_s(run):
                data["expired_at_s"] = data["last_motion"]
                _finish(run, "cancelled", "consent_expired")
                return 0
        elif run["status"] == "approaching":
            # Plan E3 decision 7a: the approach runs on the run's absolute
            # motion seconds. An NPC arrives at its own eta, a player only
            # through ``arrived``; the entry ends at ``flip_s``.
            now_s = _motion_now()
            if run["phase"] == "entry":
                if now_s >= float(data.get("flip_s") or 0.0):
                    _activate(run)
                    return 1
            else:
                reporters = set(data.get("reports_arrival") or ())
                for _role, name in _members(run):
                    eta = (data.get("eta_s") or {}).get(name)
                    if name in data["arrived"] or name in reporters or eta is None:
                        continue
                    if now_s >= float(eta):
                        _arrive(run, name, float(eta))
                if len(data["arrived"]) == len(_members(run)):
                    # Both are there: a react run waits for the partner's
                    # reaction (no approach deadline), the others go in.
                    if _enter_or_wait(run):
                        return 1
                elif now_s > float(data.get("deadline_s", math.inf)):
                    _finish(run, "failed", "approach_timeout")
                    return 0
        elif run["status"] == "sleeping":
            if not C.is_character_sleeping(run["actor"]):
                _finish(run, "completed", "awake")
                return 0
        elif run["status"] == "active":
            limit = data.get("follow_limit_s")
            if limit and data.get("active_game_s", 0) >= limit:
                # An NPC's follow pose runs out; it gets up (no further step).
                _finish(run, "completed", "follow_elapsed")
                return 0
            if run["definition"]["ability"] == "combined":
                phases = run["definition"]["phases"]
                index = next(i for i, p in enumerate(phases) if p["id"] == run["phase"])
                data["phase_elapsed"] += delta
                while data["phase_elapsed"] >= phases[index]["duration_game_s"]:
                    data["phase_elapsed"] -= phases[index]["duration_game_s"]
                    index += 1
                    if index == len(phases):
                        _finish(run, "completed", "phases_completed", follow=True)
                        break
                    run["phase"] = phases[index]["id"]
                    # Pose and phase/effect progress commit together below.
        if run["status"] == "active" and run["definition"]["ability"] != "sleep":
            runtime = None
            if run["definition"]["ability"] == "combined":
                phase = next(p for p in run["definition"]["phases"] if p["id"] == run["phase"])
                runtime = {run["actor"]: {"pose_key": phase["pose_key"]}}
            _commit(run, ("active",), runtime=runtime, now=now)
            if run["phase"] != phase_before and run["definition"]["ability"] == "combined":
                _revise(run, phase=run["phase"])   # decision 18: a late client shows the right phase
            if delta > 0:
                beats.append(dict(scene_id=run["execution_id"], kind="prop_action",
                                  members=[name for _, name in _members(run)],
                                  roles=(dict(sorted(run["data"].get("clip_roles", {}).items()))
                                         if run["members"] else {}),
                                  pose_key=_held_pose(run), delta_game_s=delta))
        elif run["status"] not in store.TERMINAL:
            _save(run)
        return 1


def _game_left_s(run, now: GameTime):
    """GAME seconds until ``run``'s next game-clock step — the end of a
    combined phase, the next gauge beat (``pose_scene.METER_BEAT_REAL_S``
    turned into game seconds by the factor) — counted from ``now``, or None."""
    if run["status"] != "active":
        return None
    data = run["data"]
    factor = game_speed_factor()
    game_left = None
    if run["definition"]["ability"] == "combined":
        phase = next((p for p in run["definition"]["phases"] if p["id"] == run["phase"]), None)
        if phase is not None:
            game_left = phase["duration_game_s"] - data.get("phase_elapsed", 0.0)
    if factor > 0 and run["definition"]["ability"] != "sleep" and _meters(run):
        # A package fills gauges on the beat (``scene.active``): a beat every
        # METER_BEAT_REAL_S keeps the finale on time, where the world-admin
        # tick alone would let it wait up to a minute.
        beat = pose_scene.METER_BEAT_REAL_S * factor
        game_left = beat if game_left is None else min(game_left, beat)
    if game_left is None:
        return None
    return game_left - max(0, (now - GameTime.parse(data["last_game"])).total_seconds)


def _due_at(run, now: GameTime | None = None):
    """The MOTION second of ``run``'s next timed step (decision 17), or None:
    while it approaches the pending NPC etas and the deadline (``eta_s``,
    ``deadline_s``), in the entry its ``flip_s``, everyone there and the
    reaction open the end of the reaction wait (SYSTEM clock, turned into a
    motion second from now), an invitation the end of its consent window, an
    active run its combined phase end or gauge beat (game clock, turned into
    real seconds by the factor)."""
    data = run["data"]
    now_s = _motion_now()
    if run["status"] == "approaching":
        if run["phase"] == "entry":
            return float(data["flip_s"]) if data.get("flip_s") is not None else now_s
        if len(data.get("arrived", [])) == len(_members(run)):
            if (data.get("reaction") or {}).get("state") == "pending":
                return now_s + max(0.0, REACTION_WAIT_S - _reaction_waited_s(data["reaction"]))
            return now_s
        reporters = set(data.get("reports_arrival") or ())
        times = [float(s) for name, s in (data.get("eta_s") or {}).items()
                 if name not in data.get("arrived", []) and name not in reporters]
        if data.get("deadline_s") is not None:
            times.append(float(data["deadline_s"]))
        return min(times) if times else None
    if run["status"] == "awaiting_consent":
        left = (consent_window_s(run) - data.get("consent_wait_s", 0.0)
                - max(0.0, now_s - float(data.get("last_motion", now_s))))
        return now_s + left
    factor = game_speed_factor()
    if factor <= 0:
        return None
    game_left = _game_left_s(run, now if now is not None else game_time())
    return None if game_left is None else now_s + game_left / factor


def _is_due(run, now: GameTime) -> bool:
    """Whether ``run``'s next timed step is due at ``now`` (motion clock, or
    for an active run's game-clock step the game clock itself — so it holds
    also when the factor is 0 and time is set by hand)."""
    at = _due_at(run, now)
    if at is not None and at <= _motion_now() + 1e-6:
        return True
    game_left = _game_left_s(run, now)
    return game_left is not None and game_left <= 0


def due_in_s(now: GameTime):
    """REAL seconds until a live run's next timed step (``_due_at``), or None
    when no run waits on a clock.

    The travel ticker beats on it (travel_engine._next_beat_s), so an NPC
    arrives at its eta and a sitter sits when the clip ends instead of on the
    next world-admin tick.
    """
    soonest = None
    now_s = _motion_now()
    for run in store.live_runs():
        failed = _STEP_FAILED.get(run.get("execution_id"))
        if failed is not None and time.monotonic() - failed[1] < STEP_RETRY_S:
            # Its last step failed (_step_failed): no early beat for it yet.
            continue
        at = _due_at(run, now)
        if at is None:
            continue
        left = at - now_s
        soonest = left if soonest is None else min(soonest, left)
    return soonest


def _notify(run):
    """Private invalidation only, never broadcast invitation/target payloads."""
    from app.core.keyed_lock import _after_locks
    from app.core.sync_topics import avatars
    names = tuple(name for _, name in _members(run))
    _after_locks(lambda: avatars(names, ("self", "scene")))


def check(actor: str, target: dict, action_id: str, revision: str, members=(), *, _query=None, include_plans: bool = False,
          offer: bool = False) -> dict:
    """Read-only preflight; optional admin diagnostics reuse the actual successful plans."""
    if (not isinstance(target, dict) or set(target) != set(_TARGET)
            or any(not isinstance(target[k], str) or not target[k] for k in _TARGET)
            or not all(isinstance(v, str) and v for v in (actor, action_id, revision))):
        return dict(enabled=False, reason="invalid_request")
    invitees = _valid_members(actor, members)
    if invitees is None:
        return dict(enabled=False, reason="invalid_partner")
    query = _query if _query is not None else places._GeometryQuery()
    if places.where(actor, profile=query.profile(actor)) != (target["location_id"], target["room_id"]):
        return dict(enabled=False, reason="target_not_in_actor_room")
    definition, reason = _definition(target, action_id, revision, _query=query)
    if reason:
        return dict(enabled=False, reason=reason)
    if not head_count_fits(definition["participants"], len(invitees)):
        return dict(enabled=False, reason="invalid_partner")
    run = dict(execution_id="", actor=actor, members=invitees, action_id=action_id,
               definition_revision=revision, target=target, definition=definition,
               status="awaiting_consent" if invitees else "approaching",
               data=dict(plans={}, journey_ids={}, access_roles={}))
    plans = {}
    # Preserve definition/partner/freeze/participant/requirement precedence.
    # Never build a route for an already refused offer.
    # Their own running actions are ended by the request, not a block.
    replaces = _replaced_runs(actor, invitees, target, action_id)
    reason = "world_frozen" if is_world_frozen() else _validate(run, _query=query, replaces=replaces,
                                                                 offer=offer)
    if not reason:
        plans, reason = _plan(run, conn=store.db.get_connection(), _query=query, replaces=replaces)
    result = dict(enabled=not reason, reason=reason, **_clothing_details(run, reason))
    if include_plans:
        result["plans"] = plans if not reason else {}
    return result


#: How long one ``state_for`` call waits for run locks in total before it
#: reads the last committed rows instead.
STATE_LOCK_WAIT_S = 0.25


def _committed_run(execution_id, deadline):
    """The run as committed: read under its lock when that is free before
    ``deadline`` (``time.monotonic``), else without it."""
    lock = _lock(execution_id)
    if not lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
        return store.get(execution_id)
    try:
        return store.get(execution_id)
    finally:
        lock.release()


def state_for(actor: str) -> dict:
    """Only an execution's exact participants may see its question/result."""
    from datetime import timedelta
    result = dict(incoming=[], outgoing=[], current=[], recent_results=[])
    if not isinstance(actor, str) or not actor:
        return result
    cutoff = utc_now() - timedelta(minutes=30)
    deadline = time.monotonic() + STATE_LOCK_WAIT_S
    rows = store.db.get_connection().execute(
        "SELECT * FROM prop_action_runs WHERE " + store.TAKES_PART + " ORDER BY created_at,execution_id",
        (actor, actor)).fetchall()
    for raw in rows:
        terminal = raw["status"] in store.TERMINAL
        if terminal:
            try:
                if timeutils.parse_iso(raw["updated_at"]) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
        # A terminal commit precedes cleanup; wait briefly for its departure
        # before publishing the row. Re-read even a formerly live cursor
        # snapshot. A lock held longer (a tick, an admission under load) is
        # not waited for: the last committed row is the answer then.
        run = _committed_run(raw["execution_id"], deadline)
        if run is None:
            continue
        terminal = run["status"] in store.TERMINAL
        pending = run["status"] == "awaiting_consent"
        invited = actor in run["members"]
        consents = run["data"].get("consents") or {}
        row = {k: run[k] for k in ("execution_id", "action_id", "definition_revision",
                                  "target", "actor", "members", "status", "phase", "reason")}
        row.update(label=run["definition"]["name"],
                   phase_label=(next((phase["label"] for phase in run["definition"]["phases"]
                                      if phase["id"] == run["phase"]), "")
                                if run["definition"]["ability"] == "combined" else ""),
                   # Physical roles by NAME: clip role (a..e) and marker access.
                   roles={"clip": run["data"].get("clip_roles", {}),
                          "access": run["data"].get("access_roles", {})},
                   # Whose view this row is (a group has several invitees).
                   viewer=actor,
                   can_respond=pending and invited and consents.get(actor) == "pending",
                   can_cancel=not terminal,
                   own_role="partner" if invited else "actor",
                   consent=("react" if _reacts(run) else "ask") if run["members"] else "",
                   # Each invitee's answer so far (pending / yes) while it waits.
                   consents=dict(consents) if pending else {},
                   declined_by=run["data"].get("declined_by", ""),
                   reaction=(run["data"].get("reaction") or {}).get("state", ""),
                   can_resist=(not terminal and invited and _reacts(run)
                               and run["status"] == "approaching"),
                   # The held pose closes with a finale clip, and the gauges a
                   # package fills toward it (``scene.meters`` provider:
                   # ``[{name, value 0..100, label}]`` per participant).
                   has_finale=bool(pose_scene.finale_kind(_held_pose(run))),
                   meters=_meters(run) if not terminal and not pending else [])
        # The viewer's own alt halves (``pose_scene.set_alt``): None when its role has none.
        if not terminal and not pending and run["status"] == "active":
            from app.core.interaction_engine import alt_choices
            row["alt"] = alt_choices(actor)
        if terminal:
            row["motion"] = run["data"].get("exit_motions", {}).get(actor)
            row["effects"] = run["data"].get("effect_results", {})
            result["recent_results"].append(row)
        elif pending:
            result["incoming" if invited else "outgoing"].append(row)
        else:
            row["motion"] = motion_for(actor, run)
            result["current"].append(row)
    return result


def _meters(run):
    """The gauges of a running action (``pose_scene.meter_rows``), carried
    forward from the run's last beat."""
    try:
        since = max(0.0, float((game_time() - GameTime.parse(run["data"]["last_game"])).total_seconds))
    except (KeyError, TypeError, ValueError):
        since = 0.0
    return pose_scene.meter_rows(run["execution_id"], [name for _, name in _members(run)],
                                 _held_pose(run), since)


def _reaction_request(partner):
    """The reaction a react run starts with (``pair_reaction.request_state``):
    ``player`` (the partner pushes it away with the HUD), ``none`` (no
    package answers) — nothing waits; ``pending`` — the run waits at the
    furniture for the model."""
    return pair_reaction.request_state(partner)


def _ask_reaction(run):
    """Ask the ``pair_reaction`` provider; the answer comes through :func:`react`."""
    pair_reaction.ask("prop_action", run["execution_id"], run["actor"], run["members"][0])


def _reaction_waited_s(reaction):
    return pair_reaction.waited_s((reaction or {}).get("asked_at"))


def _awaits_reaction(run) -> bool:
    """Whether the run must still wait for its partner's reaction. Past
    REACTION_WAIT_S the reaction counts as given (``timeout``) — a model that
    is down must not block every react action."""
    reaction = run["data"].get("reaction") or {}
    if reaction.get("state") != "pending":
        return False
    if _reaction_waited_s(reaction) < REACTION_WAIT_S:
        return True
    reaction["state"] = "timeout"
    logger.info("prop action %s: no reaction from %s within %.0f s — goes on",
                run["execution_id"], run["members"][0], REACTION_WAIT_S)
    return False


def _book_reaction(run, accepted, feeling, romantic):
    """The reaction's mark on the pair (``pair_reaction.book``)."""
    pair_reaction.book(run["actor"], run["members"][0], run["definition"]["name"],
                       accepted, feeling, romantic)


def react(partner: str, execution_id: str, accept: bool, *, line: str = "",
          feeling: int = 0, romantic: bool = False) -> dict:
    """The partner's reaction to a pair run requested with ``consent="react"``.

    ``accept`` False ends the run (``cancelled`` / ``partner_resisted``);
    True lets it go on — at once into the furniture when both already wait
    there. ``line`` is told to the room as it is (the partner's visible
    reaction, in its language); ``feeling`` (-2..2) and ``romantic`` change
    the relationship (:func:`_book_reaction`). A reaction that comes after the
    wait ran out, or for a run that is over, changes nothing.
    """
    if type(accept) is not bool:
        return _refused("invalid_response")
    feeling = pair_reaction.clamp_feeling(feeling)
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or run["members"] != [partner] or not _reacts(run):
            return _refused("not_partner")
        reaction = run["data"].get("reaction") or {}
        if run["status"] in store.TERMINAL or reaction.get("state") != "pending":
            return _result(run)
        reaction.update(state="accepted" if accept else "resisted", feeling=feeling)
        run["data"]["reaction"] = reaction
        line = line.strip() if isinstance(line, str) else ""
        if line:
            _narrate(run, line, literal=True)
        _book_reaction(run, accept, feeling, bool(romantic))
        if not accept:
            return _finish(run, "cancelled", "partner_resisted")
        if (run["status"] == "approaching" and run["phase"] != "entry"
                and len(run["data"]["arrived"]) == len(_members(run))):
            # Everyone waits at the furniture: the entry starts now (flip =
            # now + the entry's nominal seconds).
            _begin_entry(run, at_s=_motion_now())
        elif (run["data"].get("order") or {}).get("awaits"):
            # The reaction came before the arrival: the order stops waiting.
            order = run["data"]["order"]
            _revise(run, awaits="", flip_motion_s=float(order["eta_motion_s"]) + _entry_nominal_s(order))
        else:
            _save(run)
        return _result(store.get(execution_id))


def respond(actor: str, execution_id: str, accept: bool) -> dict:
    """One invitee's answer. The LAST "yes" ends what everyone was doing
    until now (the runs the invitation left running) before the new one is
    planned; an earlier "yes" is only recorded, one "no" ends the invitation."""
    run = store.get(execution_id)
    replaces = ()
    if (accept is True and run and actor in run["members"] and run["status"] == "awaiting_consent"
            and _last_consent(run, actor) and not is_world_frozen()
            and not _consent_over(run)):   # an expired invitation ends nothing
        replaces = _replaced_runs(run["actor"], run["members"], run["target"], run["action_id"])
        if replaces and _validate(run, replaces=replaces):
            replaces = ()   # refused anyway: _respond says why, nothing ends
    direct = bool(replaces) and _switches_in_place(run, replaces)
    with _replacing(run, replaces, direct):
        result = _respond(actor, execution_id, accept, direct=direct)
    if result["status"] != "refused":
        run = store.get(execution_id)
        if run:
            _notify(run)
    return result


def take_furniture_for_pose(actor: str, pose_key: str) -> dict | None:
    """A sitting/lying pose the room has no free place for, reached the
    honest way: start the nearest furniture action in ``actor``'s room that
    holds that pose (or another pose of its group —
    ``prop_actions.furniture_for_pose``). The run walks the character over
    and seats it; its pose is the action's. Returns the accepted request
    result, or None when no piece takes it (each candidate is tried once, a
    refused one — taken meanwhile, no route — passes to the next)."""
    from app.core.prop_actions import furniture_for_pose
    for offer in furniture_for_pose(actor, pose_key):
        result = request(actor, offer["target"], offer["action_id"], offer["definition_revision"])
        if result.get("status") not in ("refused", "failed", "cancelled"):
            logger.info("%s takes %s for pose %r: %s on %s", actor, offer["label"], pose_key,
                        result.get("status"), offer["prop_label"])
            return dict(result, label=offer["label"], prop_label=offer["prop_label"])
        logger.info("%s: %s on %s refused for pose %r: %s", actor, offer["label"],
                    offer["prop_label"], pose_key, result.get("reason"))
    return None


def going_to_bed(actor: str) -> bool:
    """Whether a live SLEEP action of ``actor`` has not put it to sleep yet —
    it is still asked, walking over or lying down."""
    return any(run["actor"] == actor and run["definition"].get("ability") == "sleep"
               and run["status"] != "sleeping" for run in store.live_runs())


def take_bed_to_sleep(actor: str) -> dict | None:
    """Falling asleep without a lying place of the room: start the nearest
    sleep action of a piece in ``actor``'s room (``prop_actions.beds_for_sleep``).
    The run walks the character over, lays it down and sets the sleep flag
    itself on arrival. Returns the accepted request result, or None when no
    bed takes it (each is tried once; a refused one passes to the next)."""
    from app.core.prop_actions import beds_for_sleep
    for offer in beds_for_sleep(actor):
        result = request(actor, offer["target"], offer["action_id"], offer["definition_revision"])
        if result.get("status") not in ("refused", "failed", "cancelled"):
            logger.info("%s goes to bed to sleep: %s on %s (%s)", actor, offer["label"],
                        offer["prop_label"], result.get("status"))
            return dict(result, label=offer["label"], prop_label=offer["prop_label"])
        logger.info("%s: %s on %s refused for sleep: %s", actor, offer["label"],
                    offer["prop_label"], result.get("reason"))
    return None


def has_semantic_action(actor: str) -> bool:
    """Implicit narration never overrides an explicit, still-owned action."""
    row = store.db.get_connection().execute(
        "SELECT 1 FROM prop_action_runs WHERE " + store.TAKES_PART + " "
        "AND status NOT IN ('completed','cancelled','failed') LIMIT 1", (actor, actor)).fetchone()
    return row is not None
