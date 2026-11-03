"""Persistent exact-target prop actions shared by authenticated HTTP and tools.

Run locks are reentrant (travel cancellation can call back inside its guard).
Claims use SQLite, never actor-global locks. No owner callback runs under a
profile lock. Offline intervals pause execution; receipts recover actual Core
arrival writes, not inferred animation completion. Effects and lifecycle
progress share one transaction, with notifications strictly after commit.
"""
from contextlib import contextmanager, ExitStack, nullcontext
from contextvars import ContextVar
from threading import Lock, RLock
from weakref import WeakValueDictionary
import math
import operator
import time
import uuid

from app.core import prop_action_store as store, places, props, travel_engine as travel
from app.core.game_time import GameTime, GameDuration
from app.core.timeutils import game_time, game_speed_factor, parse_iso, utc_now
from app.core.keyed_lock import keyed_lock, _DeferredRLock
from app.core.log import get_logger
from app.models import character as C
from app.models.world import is_world_frozen

_PROCESS = uuid.uuid4().hex
_locks = WeakValueDictionary()
_locks_mutex = Lock()
_OPS = dict(lt=operator.lt, le=operator.le, eq=operator.eq, ge=operator.ge, gt=operator.gt)
_TARGET = ("location_id", "room_id", "placement_id", "variant_uid")
_INTERNAL_MUTATION = ContextVar("prop_action_owned_mutation", default=False)
logger = get_logger("prop_action_engine")

#: A pair run requested with ``consent="react"`` waits at the furniture this long (SYSTEM
#: seconds: it waits for a model, not for the world) for the partner's
#: reaction; without one it goes on as accepted.
REACTION_WAIT_S = 60.0
#: Relationship change per ``feeling`` step (-2..2) of a reaction: the
#: partner's sentiment toward the actor, romantic tension for a romantic
#: action; a resisted actor's own sentiment drops by the fixed amount.
_REACTION_SENTIMENT_STEP = 0.05
_REACTION_ROMANTIC_STEP = 0.02
_RESISTED_ACTOR_SENTIMENT = -0.03


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


def request_guard(actor: str, request_id: str):
    """Serialize one actor/nonce's admission and adapter charge, not all actions.

    Weak lifetime bounds the caller-supplied key space. The existing deferred
    RLock keeps invitation/model callbacks outside the adapter's outer guard.
    """
    if not isinstance(actor, str) or not isinstance(request_id, str) or not request_id:
        return nullcontext()
    key = "request:" + store.encode([actor, request_id])
    with _locks_mutex:
        guard = _locks.get(key)
        if guard is None:
            guard = _DeferredRLock()
            _locks[key] = guard
        return guard


def _result(run):
    result = {"execution_id": run["execution_id"], "status": run["status"], "reason": run["reason"]}
    if run["data"].get("effect_results"):
        result["effects"] = run["data"]["effect_results"]
    return result


def _refused(reason):
    return dict(execution_id="", status="refused", reason=reason)


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

@contextmanager
def _claim_transaction(run):
    # Existing seating uses location-place -> profile. Keep that order and
    # never call profile writers/callbacks in the SQLite acquisition span.
    with keyed_lock("places", run["target"]["location_id"]):
        with store.transaction() as conn:
            yield conn


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
        need = pose_places(definition["pose_key"]) if definition["ability"] == "pair" else len(_members(run))
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
                if not places.inside(target["location_id"], anchor["x"], anchor["z"]):
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


def _revalidate_admission(run, conn, planned_state, replaces=()):
    """No routing under the write lock: compare inputs and check chosen slots."""
    query = places._GeometryQuery()
    reason = "world_frozen" if is_world_frozen() else _validate(run, conn=conn, _query=query, replaces=replaces)
    if reason:
        return reason
    if _planning_state(run, query) != planned_state:
        return "approach_target_changed"
    target = run["target"]
    inventory = query.room_places(target["location_id"], target["room_id"])
    taken = places.occupancy(target["location_id"], target["room_id"], _places=inventory)
    replaces = _refs(replaces)
    own = _freed(run, replaces)
    for plan in run["data"]["plans"].values():
        anchor = plan["entry_anchor"]
        place = next((p for p in inventory if p["id"] == anchor["place_id"]), None)
        if (not place or anchor["slot"] not in places.free_slots(
                place, [t for t in taken.get(place["id"], []) if t[0] not in own])
                or store.held(store.slot_key(target, anchor["marker_id"], anchor["slot"]), conn=conn)
                not in (None, "", *replaces)):
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

    ``members``: the invitees, in invitation order — as many as the action
    takes beside the actor (``participants`` - 1), none for a solo action.
    ``consent`` (requests with others): "ask" — every invitee consents
    first — or "react", a pair only (``CONSENTS``). Naming the run one
    already takes part in again — the partner's tool repeating the action it
    just agreed to — answers that run, marked ``already``, instead of
    refusing it as a busy participant.

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
    if len(invitees) != definition["participants"] - 1:
        return _refused("invalid_partner"), False
    if consent == "react" and len(invitees) != 1:
        return _refused("invalid_consent"), False
    now = game_time().canonical()
    asks = bool(invitees) and consent != "react"
    run = dict(execution_id=uuid.uuid4().hex, actor=actor, members=invitees, request_id=request_id or None,
               request_fingerprint=fingerprint, action_id=action_id, definition_revision=revision,
               status="awaiting_consent" if asks else "approaching", phase="", reason="", target=target,
               definition=definition, data=dict(plans={}, journey_ids={}, arrived=[], process=_PROCESS,
                                                last_game=now, elapsed=0.0, consent_elapsed=0.0,
                                                **({"consent": consent} if invitees else {}),
                                                **({"consents": {m: "pending" for m in invitees}} if asks else {})))
    replaces = _replaced_runs(actor, invitees, target, action_id)
    if not replaces:
        return _admit(run, fingerprint)
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
        return _refused(reason), False
    direct = _switches_in_place(run, replaces)
    with _replacing(run, replaces):
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
            return _refused(reason), False
        run["data"]["plans"] = plans
        reacts = _reacts(run)
        if reacts:
            run["data"].update(consented=True, reaction=_reaction_request(members[0]))
        with _claim_transaction(run) as conn:
            previous = store.by_request(actor, request_id, conn=conn)
            if previous:
                return (_result(previous) if previous["request_fingerprint"] == fingerprint
                        else _refused("request_id_conflict")), False
            reason = _revalidate_admission(run, conn, planned_state, replaces)
            if reason:
                return _refused(reason), False
            store.insert(conn, run)
            if not members or reacts:
                store.acquire(conn, run, [p["entry_anchor"] for p in plans.values()])
        marks.append(("claim", time.perf_counter()))
        if not members or reacts:
            _launch(run, direct)
        marks.append(("start", time.perf_counter()))
    _notify(run)
    if reacts:
        _narrate(run, "{actor} approaches {partner}: {pose}.")
        if run["data"]["reaction"]["state"] == "pending":
            _ask_reaction(run)
    elif members:
        _narrate(run, "{inviter} suggests {pose} to {invitee}.", inviter=actor, invitee=_join(members))
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


def _respond(actor: str, execution_id: str, accept: bool, direct: bool = False) -> dict:
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or actor not in run["members"]:
            return _refused("not_invitee")
        if type(accept) is not bool:
            return _refused("invalid_response")
        if run["status"] != "awaiting_consent" or run["data"]["consents"].get(actor) != "pending":
            return _result(run)
        if not accept:
            # One "no" ends the invitation for everyone, naming who said it.
            run["data"]["declined_by"] = actor
            return _finish(run, "cancelled", "consent_declined")
        if is_world_frozen():
            return _refused("world_frozen")
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
        with _claim_transaction(run) as conn:
            run = store.get(execution_id, conn=conn)
            if run["status"] != "awaiting_consent":
                return _result(run)
            now = game_time()
            data = run["data"]
            if data["process"] == _PROCESS:
                data["consent_elapsed"] += max(0, (now - GameTime.parse(data["last_game"])).total_seconds)
            data.update(last_game=now.canonical(), process=_PROCESS)
            if data["consent_elapsed"] >= 300:
                run.update(status="cancelled", reason="consent_expired")
                store.save(conn, run)
                return _result(run)
            if not reason:
                data.update(plans=plans, clip_roles=planned_roles, access_roles=planned_access)
                reason = _revalidate_admission(run, conn, planned_state)
            if reason == "pair_roles_changed":
                data.update(clip_roles=agreed_roles, access_roles=agreed_access)
            if reason:
                run.update(status="failed", reason=reason)
                store.save(conn, run)
                return _result(run)
            run["data"].update(plans=plans, consented=True, last_game=game_time().canonical(), process=_PROCESS)
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
    register_owner()
    for role, name in _members(run):
        run["data"]["journey_ids"][name] = uuid.uuid4().hex
    _save(run)  # Persist identity BEFORE the real journey write (crash recovery).
    deadline = 60.0
    for _role, name in _members(run):
        anchor = run["data"]["plans"][name]["entry_anchor"]
        target = dict(run["target"], action_id=run["action_id"], definition_revision=run["definition_revision"],
                      marker_id=anchor["marker_id"], slot=anchor["slot"])
        if _shares_place(run):   # the planned clip role point, not the slot position
            target["point"] = [anchor["x"], anchor["z"]]
        journey, reason = travel.start_approach_journey(name, target, run["data"]["access_roles"][name], execution_kind="prop_action",
                            execution_ref=run["execution_id"], journey_id=run["data"]["journey_ids"][name])
        if not journey:
            _finish(run, "failed", reason)
            return
        delay = max(0, (GameTime.parse(journey["started_at_game"]) - game_time()).total_seconds)
        deadline = max(deadline, float(journey["waypoints"][-1][2]) + delay + 60)
        try:
            snapshot = _motion_snapshot(run, name, journey)
        except Exception:
            # The owner's client then follows the worldmap travel block.
            logger.exception("Prop action motion snapshot failed: %s", run["execution_id"])
            snapshot = None
        run["data"].setdefault("motions", {})[name] = snapshot
    run["data"].update(deadline=deadline, last_game=game_time().canonical())
    _save(run)


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
    per segment (null = timeless), from the game clock right now.
    """
    if not run or run["status"] != "approaching" or name not in store.people(run):
        return None
    snapshot = run["data"].get("motions", {}).get(name)
    if not snapshot:
        return None
    motion = {k: v for k, v in snapshot.items() if k != "timed"}
    motion["waypoints"] = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in snapshot["timed"]]
    motion["paces_m_s_real"] = travel.segment_paces_m_s_real(snapshot["timed"], game_speed_factor())
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


# ---------------------------------------------------------------- finale
#
# A FINALE is one participant's closing clip inside a running action: the
# pose names it (catalog ``finale_animation``), a package decides WHEN
# (``begin_finale``), the person plays it once and goes back to the action's
# loop while the partner plays on untouched. It is an animation, so it runs
# on the SYSTEM clock like every clip (a frozen world still finishes it), and
# it lives in this process only: lost on a restart, it was a second long.

#: Seconds a finale stays in the payload past its clip's own length. The
#: clips last about a second, the worldmap poll of a bystander 3 s: every
#: client must see the block once to play it (once per ``id``, § A8c), and a
#: new finale of the same person is refused until it is gone.
FINALE_SHOW_S = 4.0
_finales = {}
_finales_mutex = Lock()


def finale_kind(pose_key: str, name: str = "", *, profile=None) -> str:
    """The finale clip kind of ``pose_key``: its catalog ``finale_animation``,
    else what a package derives for it (``auto_finale``). "" when there is
    none or the clip is missing in the shape the pose needs: a multi-person
    pose needs a complete clip with one role per participant, a solo pose a
    solo clip — for ``name``'s own figure when given (its set chain, as
    ``animated_for``)."""
    from app.core.animation_clips import role_counts
    from app.core.pose_catalog import get_catalog
    entry = get_catalog("pose").get(pose_key or "") or {}
    kind = entry.get("finale_animation") or auto_finale(pose_key, entry)
    if not kind:
        return ""
    people = entry.get("participants", 1)
    roles = role_counts().get(kind, 1)
    if people != 1:
        return kind if roles == people else ""
    if roles != 1:
        return ""
    return kind if _solo_finale_clip(kind, name, profile) else ""


def auto_finale(pose_key: str, entry: dict | None = None) -> str:
    """The finale kind a package derives for a pose without an explicit one
    (provider ``pose.finale_animation(pose_key, animation, participants) -> kind``,
    e.g. a naming convention on the pose's own clip); "" without a provider
    or an answer. Unchecked — ``finale_kind`` checks the clip's shape."""
    from app.core.hooks import get_provider
    provider = get_provider("pose.finale_animation")
    if provider is None:
        return ""
    if entry is None:
        from app.core.pose_catalog import get_catalog
        entry = get_catalog("pose").get(pose_key or "") or {}
    try:
        kind = provider(pose_key=pose_key or "", animation=entry.get("animation") or "",
                        participants=int(entry.get("participants") or 1))
    except Exception as e:
        logger.debug("finale provider failed for %s: %s", pose_key, e)
        return ""
    return kind.strip().lower() if isinstance(kind, str) else ""


def _solo_finale_clip(kind, name, profile):
    """``{set, ...}`` of the solo clip ``name`` would play (any set without a
    name), None when there is none."""
    from app.core.animation_clips import clip_entries
    if not name:
        return next(({"set": e["set"]} for e in clip_entries() if e["kind"] == kind and not e["role"]), None)
    from app.core.animation_sets import resolve_sets
    from app.core.movement import clip_file_for
    return clip_file_for(kind, resolve_sets(name, profile), free_only=False)


def _finale_duration_s(kind, role, name):
    """The clip's own length in seconds — the half this person plays."""
    from app.core.animation_clips import clip_entries, clip_meta
    if role:
        entry = next((e for e in clip_entries() if e["kind"] == kind and e["role"] == role), None)
        meta = clip_meta(kind, entry["set"]) if entry else None
    else:
        found = _solo_finale_clip(kind, name, None)
        meta = clip_meta(kind, found["set"]) if found else None
    try:
        duration = float((meta or {}).get("duration_s") or 0)
    except (TypeError, ValueError):
        return 0.0
    return duration if math.isfinite(duration) and duration > 0 else 0.0


def begin_finale(execution_id: str, name: str) -> dict:
    """Starts ``name``'s finale in its running action — ``{ok, reason}``.

    Refused: a run that is not active (or sleeps), a name that is no
    participant, a held pose without a usable finale clip, and a finale of
    that person still playing. Everyone in the run is told to refresh; the
    ``prop_action.finale_started`` event fires after every lock is released.
    """
    from app.core.keyed_lock import _after_locks
    from app.core.hooks import emit
    if not isinstance(execution_id, str) or not isinstance(name, str):
        return dict(ok=False, reason="invalid")
    with _lock(execution_id):
        run = store.get(execution_id)
        if run is None or run["status"] != "active" or run["definition"]["ability"] == "sleep":
            return dict(ok=False, reason="not_active")
        if name not in [member for _, member in _members(run)]:
            return dict(ok=False, reason="not_participant")
        pose = _held_pose(run)
        kind = finale_kind(pose, name)
        if not kind:
            return dict(ok=False, reason="no_finale")
        role = (next((r for r, member in run["data"].get("clip_roles", {}).items() if member == name), "")
                if run["members"] else "")
        duration = _finale_duration_s(kind, role, name)
        if duration <= 0:
            return dict(ok=False, reason="no_finale")
        # Playing an alt half: the finale closes in that alt when its clip
        # has one for the role, else in the role's own half.
        alt = ""
        if role:
            from app.core.animation_clips import clip_alts
            from app.core.interaction_engine import get_interaction
            current = str((get_interaction(name) or {}).get("alt") or "")
            if current and current in (clip_alts(kind).get(role) or []):
                alt = current
        with _finales_mutex:
            if _finale_live(_finales.get(name)):
                return dict(ok=False, reason="finale_playing")
            _finales[name] = dict(id=uuid.uuid4().hex[:12], execution_id=execution_id,
                                  kind=kind, role=role or None, alt=alt,
                                  pose_key=pose, started=utc_now(), duration_s=duration)
        _notify(run)
    _after_locks(lambda: emit("prop_action.finale_started", execution_id=execution_id,
                              name=name, kind=kind, pose_key=pose))
    return dict(ok=True, reason="")


def _finale_live(finale) -> bool:
    return bool(finale) and ((utc_now() - finale["started"]).total_seconds()
                             < finale["duration_s"] + FINALE_SHOW_S)


def finale_for(name: str) -> dict | None:
    """The worldmap row's ``finale`` block of ``name`` (§ A8c):
    ``{id, kind, role, alt, elapsed_s, duration_s}`` — the half (``role``
    a..e, None for a solo clip; ``alt`` its alt half, ``""`` none) a client
    plays ONCE per ``id``, then back to the action's own clip. Shown until
    ``FINALE_SHOW_S`` past the clip's end, so a polling bystander sees it
    too; ``elapsed_s`` in SYSTEM seconds."""
    with _finales_mutex:
        finale = _finales.get(name)
        if not _finale_live(finale):
            return None
        elapsed = (utc_now() - finale["started"]).total_seconds()
        return dict(id=finale["id"], kind=finale["kind"], role=finale["role"],
                    alt=finale.get("alt") or "",
                    elapsed_s=round(max(0.0, elapsed), 3), duration_s=round(finale["duration_s"], 3))


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


def set_alt(execution_id: str, name: str, alt: str) -> dict:
    """``name`` plays the alt half ``alt`` of its clip role in its running
    action (``""`` = the role's own half again) — ``{ok, reason}``; refused
    for a run that is not active and a non-participant, the rest is
    ``interaction_engine.set_alt``."""
    from app.core import interaction_engine
    if not isinstance(execution_id, str) or not isinstance(name, str) or not isinstance(alt, str):
        return dict(ok=False, reason="invalid")
    with _lock(execution_id):
        run = store.get(execution_id)
        if run is None or run["status"] != "active":
            return dict(ok=False, reason="not_active")
        if name not in [member for _, member in _members(run)]:
            return dict(ok=False, reason="not_participant")
        result = interaction_engine.set_alt(name, alt)
        if result["ok"]:
            _notify(run)
    return result


def hold_meter(execution_id: str, name: str, hold: bool) -> dict:
    """``name`` holds its own gauge back (or lets go) in its running action —
    ``{ok, reason}``. What holding means is the package's (provider
    ``prop_action.meter_hold``); refused for a run that is not active, a
    non-participant and when no package takes it (``unsupported``)."""
    from app.core.hooks import get_provider
    if not isinstance(execution_id, str) or not isinstance(name, str) or not isinstance(hold, bool):
        return dict(ok=False, reason="invalid")
    run = store.get(execution_id)
    if run is None or run["status"] != "active":
        return dict(ok=False, reason="not_active")
    if name not in [member for _, member in _members(run)]:
        return dict(ok=False, reason="not_participant")
    provider = get_provider("prop_action.meter_hold")
    try:
        taken = bool(provider and provider(execution_id=execution_id, name=name, hold=hold))
    except Exception as e:
        logger.debug("meter hold provider failed for %s: %s", name, e)
        taken = False
    if not taken:
        return dict(ok=False, reason="unsupported")
    _notify(run)
    return dict(ok=True, reason="")


def _end_finales(execution_id=None, *, expired_only=False):
    """Drops finales of one run (its end) or every expired one; the
    ``prop_action.finale_done`` events fire after the locks."""
    from app.core.keyed_lock import _after_locks
    from app.core.hooks import emit
    with _finales_mutex:
        done = [(name, f) for name, f in _finales.items()
                if (execution_id is None or f["execution_id"] == execution_id)
                and not (expired_only and _finale_live(f))]
        for name, _f in done:
            _finales.pop(name, None)
    for name, finale in done:
        _after_locks(lambda name=name, finale=finale: emit(
            "prop_action.finale_done", execution_id=finale["execution_id"], name=name,
            kind=finale["kind"], pose_key=finale["pose_key"]))


def _narrate(run, key, *, literal=False, **fmt):
    """One storyteller line in the run's room, in the actor's language, after
    every lock is released. The room has to SEE a figure sit down or get up —
    the perception stream is what the characters remember of the scene, and
    the player's chat shows it. ``literal``: ``key`` is the finished line
    (a partner's reaction), neither translated nor formatted. Never raises."""
    from app.core.keyed_lock import _after_locks

    def deliver():
        try:
            from app.core.i18n import localized, t
            from app.core.perception import STORYTELLER_SPEAKER, VOLUME_NORMAL, record_utterance
            from app.core.pose_catalog import pose_label
            actor, target = run["actor"], run["target"]
            lang = C.get_character_language(actor)
            query = places._GeometryQuery()
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
                source="prop_action", anchor=actor)
        except Exception as e:
            logger.debug("prop-action narration failed: %s", e)

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
        consents = run["data"].get("consents") or {}
        silent = [m for m in run["members"] if consents.get(m) != "yes"] or run["members"]
        _narrate(run, "{invitee} does not respond to the invitation from {inviter}.",
                 inviter=run["actor"], invitee=_join(silent))
    elif before in ("active", "sleeping"):
        # A pair ends through end_interaction, which tells the room itself;
        # a seat kept for the actor's next place or follow pose is no getting up.
        if pair or run["actor"] in kept:
            return
        if run["definition"]["ability"] == "sleep" and reason == "awake":
            _narrate(run, "{actor} wakes up and gets up from the {prop}.")
        else:
            line = _group_line(_LEAVE_LINES, run)
            if line:
                _narrate(run, line)
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
            delta = _clock(run, game_time())
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
        _end_finales(run["execution_id"])
        _commit(run, phases)  # Terminal, effects and claim release precede cleanup.
        if before == "active":
            _emit_lifecycle("prop_action.ended", run, status=status, reason=reason)
        _cleanup(run, keep=kept)
        if follows:
            _follow_up(run, follows)
        _narrate_finish(run, before, status, reason, kept)
        return _result(run)


@_internal_mutation()
def _cleanup(run, keep=()):
    """``keep``: members whose place stays — for the departure of the run
    replacing this one (_replace) or for their follow pose (_follow_up);
    everyone else stands up here."""
    reason = run["reason"]
    for role, name in _members(run):
        jid = run["data"]["journey_ids"].get(name)
        if jid:
            travel.cancel_journey(name, journey_id=jid, execution_kind="prop_action", execution_ref=run["execution_id"], reason=reason)
        if name not in keep:
            _stand_up(run, name)
    # Pair interaction cleanup can release both members itself. Capture and
    # release every owned place first, while its original pose still exists.
    for _role, name in _members(run):
        profile = C.get_character_profile(name)
        inter = profile.get("interaction") or {}
        if inter.get("execution_ref") == run["execution_id"]:
            from app.core.interaction_engine import end_interaction
            end_interaction(name, reason=reason, interaction_id=inter["id"], keep_places=keep)
    store.cleanup_finished(run["execution_id"], run["data"].get("exit_motions", {}))


def _stand_up(run, name):
    """Release ``name``'s place of ``run``, recording the departure the
    client plays (``exit_motions``) when it really got up from it."""
    pose = C.get_effective_pose_key(name)
    before = C.get_character_pos(name)
    place = (C.get_character_profile(name) or {}).get("place") or {}
    held = place.get("execution_id") == run["execution_id"]
    released = C.release_prop_action_state(name, run["execution_id"])
    after = C.get_character_pos(name)
    if released and held and before and after:
        after["yaw"] = C.get_avatar_sync_snapshot(name)["yaw"]
        run["data"].setdefault("exit_motions", {})[name] = _exit_motion(pose, before, after)


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
    piece is full, the action refuses) stands up as everyone else did."""
    from app.models.account import get_all_avatars
    avatars = set(get_all_avatars())
    revision = None
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
                                        last_game=now, elapsed=0.0, consent_elapsed=0.0,
                                        follow_of=run["execution_id"],
                                        **({} if name in avatars else {"follow_limit_s": FOLLOW_NPC_LIMIT_S})))
                result, _created = _admit(follow, fingerprint, replaces=(run["execution_id"],), direct=True)
        except Exception:
            logger.exception("Follow pose for %s after %s failed", name, run["execution_id"])
            result = _refused("follow_error")
        if result.get("status") in ("refused", "failed", "cancelled"):
            logger.info("%s gets no follow pose after %s: %s", name, run["execution_id"], result.get("reason"))
            _stand_up(run, name)
    store.cleanup_finished(run["execution_id"], run["data"].get("exit_motions", {}))


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


@contextmanager
def _replacing(run, replaces):
    """End ``replaces`` for ``run`` (_replace); afterwards whoever kept a seat
    for the departure stands up, unless the new run has taken it over."""
    owners = []
    for ref in replaces:
        old = store.get(ref)
        if not old:
            continue
        name = next((n for _, n in _members(run) if n in store.people(old)), run["actor"])
        _replace(name, ref)
        owners.append((name, ref))
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


def _clock(run, now):
    data = run["data"]
    previous = GameTime.parse(data["last_game"])
    gap = max(0, (now - previous).total_seconds)
    restarted = data["process"] != _PROCESS
    if restarted:
        # Reanchor every still-owned real journey before travel may advance it.
        from app.core.keyed_lock import keyed_lock
        for role, name in _members(run):
            with keyed_lock("character_profile", name):
                profile = C.get_character_profile(name)
                journey = profile.get("journey")
                if journey and _own_journey(run, name, journey):
                    checkpoint = GameTime.parse(journey.get("position_checkpoint_game", data["last_game"]))
                    anchored = GameTime.parse(journey.get("prop_action_reanchored_at", checkpoint.canonical()))
                    shift = max(0, (now - max(checkpoint, anchored)).total_seconds)
                    journey["started_at_game"] = (GameTime.parse(journey["started_at_game"]) + GameDuration.of(seconds=shift)).canonical()
                    journey["prop_action_reanchored_at"] = now.canonical()
                    if not C.save_character_profile(name, profile):
                        raise RuntimeError("prop_action_reanchor_write_failed")
        data["process"] = _PROCESS
    data["last_game"] = now.canonical()
    return 0.0 if restarted or is_world_frozen() else float(gap)


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
            elapsed = run["data"]["elapsed"] + max(0, (game_time() - GameTime.parse(run["data"]["last_game"])).total_seconds)
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
        if len(run["data"]["arrived"]) == len(_members(run)) and not _awaits_reaction(run):
            _begin_entry(run)


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
        return dict(kind="", duration_game_s=0.0, pose_key=pose), ""
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
    return dict(kind=kind, duration_game_s=float(meta["duration_s"]) * max(1, game_speed_factor()), pose_key=pose), ""


def _begin_entry(run):
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
    run["phase"] = "entry"
    now = game_time()
    run["data"].update(entries=entries, entry_elapsed=0.0, last_game=now.canonical(),
                       entry_started_game_s=now.total_seconds)
    _save(run)
    # Display actual bridge at exact access; no place/body anchor until it ends.
    from app.core.keyed_lock import keyed_lock
    for _role, name in _members(run):
        with keyed_lock("character_profile", name):
            profile = C.get_character_profile(name)
            plan = run["data"]["plans"][name]
            if plan.get("entry_mode") == "direct":
                profile.pop("prop_action_entry", None)
            else:
                profile["prop_action_entry"] = dict(execution_id=run["execution_id"], **entries[name],
                    access=plan["access"], anchor=plan["entry_anchor"])
            C.save_character_profile(name, profile)
    if not any(e["duration_game_s"] for e in entries.values()):
        _activate(run)


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
        run["data"].update(phase_elapsed=0.0, active_game_s=0.0, last_game=game_time().canonical())
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
        _emit_lifecycle("prop_action.started", run, ability=ability)
    if ability != "pair":
        C._publish_activity_changed(run["actor"], pose, "", pose, place, None)
        line = ("{actor} lies down on the {prop} to sleep." if ability == "sleep"
                else _group_line(_SETTLE_LINES, run))
        if line:
            _narrate(run, line)
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


def advance(now: GameTime) -> int:
    """One scheduler step over every live run. Besides the run lifecycle it
    drops expired finales and, after every lock, fires
    ``prop_action.active(execution_id, members, pose_key, delta_game_s)`` for
    each run that spent online game time active — the beat a package counts
    on (a frozen world and offline time give none)."""
    from app.core.keyed_lock import _after_locks
    from app.core.hooks import emit
    register_owner()
    advanced = 0
    beats = []
    for pending in store.pending_cleanup():
        with _lock(pending["execution_id"]):
            _cleanup(pending)
    for snapshot in store.live_runs():
        with _lock(snapshot["execution_id"]):
            run = store.get(snapshot["execution_id"])
            if run["status"] in store.TERMINAL:
                continue
            delta = _clock(run, now)
            if is_world_frozen():
                _save(run)
                continue
            if run["status"] == "active" and run["definition"]["ability"] != "sleep":
                if run["definition"]["ability"] == "combined":
                    duration = sum(p["duration_game_s"] for p in run["definition"]["phases"])
                    delta = min(delta, max(0, duration - run["data"].get("active_game_s", 0)))
                run["data"]["active_game_s"] += delta
            if (run["status"] == "sleeping" and not C.is_character_sleeping(run["actor"])
                    and store.db.get_connection().execute("SELECT 1 FROM characters WHERE name=?", (run["actor"],)).fetchone()):
                _finish(run, "completed", "awake")
                continue
            if run["status"] == "active" and run["definition"]["ability"] == "sleep":
                _resume_sleep(run)
                advanced += 1
                continue
            # An invitation leaves the two's current runs going until the
            # "yes" (request_with_creation): those are not a busy participant.
            invited = run["status"] == "awaiting_consent"
            reason = _validate(run, require_claims=not invited,
                               presence=run["status"] in ("awaiting_consent", "approaching") or run["definition"]["interrupt_on_presence_change"],
                               replaces=_replaced_runs(run["actor"], run["members"], run["target"], run["action_id"])
                               if invited else ())
            if reason:
                _finish(run, "failed", reason)
                continue
            data = run["data"]
            if run["status"] == "awaiting_consent":
                data["consent_elapsed"] += delta
                if data["consent_elapsed"] >= 300:
                    _finish(run, "cancelled", "consent_expired")
                    continue
            elif run["status"] == "approaching":
                if run["phase"] == "entry":
                    data["entry_elapsed"] += delta
                    if data["entry_elapsed"] >= max(e["duration_game_s"] for e in data["entries"].values()):
                        _activate(run)
                        advanced += 1
                        continue
                elif len(data["arrived"]) == len(_members(run)):
                    # Both are there: a react run waits for the partner's
                    # reaction (no approach deadline), the others go in.
                    if not _awaits_reaction(run):
                        _begin_entry(run)
                        advanced += 1
                        continue
                else:
                    data["elapsed"] += delta
                    if data["elapsed"] > data.get("deadline", 60):
                        _finish(run, "failed", "approach_timeout")
                        continue
                    for _role, name in _members(run):
                        if name in data["arrived"]:
                            continue
                        profile = C.get_character_profile(name)
                        if profile.get("journey") and _own_journey(run, name, profile["journey"]):
                            continue
                        receipt = profile.get("last_journey_result") or {}
                        if _own_journey(run, name, receipt) and receipt["status"] == "arrived":
                            # Actual durable arrival proof and exact floor point.
                            access = data["plans"][name]["access"]
                            pos = C.get_character_pos(name)
                            if pos and math.dist((pos["x"], pos["z"]), (access["x"], access["z"])) <= .02:
                                data["arrived"].append(name)
                                continue
                        _finish(run, "failed", "approach_journey_lost")
                        break
                    if (run["status"] not in store.TERMINAL and len(data["arrived"]) == len(_members(run))
                            and not _awaits_reaction(run)):
                        _begin_entry(run)
                        advanced += 1
                        continue
            elif run["status"] == "sleeping":
                if not C.is_character_sleeping(run["actor"]):
                    _finish(run, "completed", "awake")
                    continue
            elif run["status"] == "active":
                limit = data.get("follow_limit_s")
                if limit and data.get("active_game_s", 0) >= limit:
                    # An NPC's follow pose runs out; it gets up (no further step).
                    _finish(run, "completed", "follow_elapsed")
                    continue
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
                if delta > 0:
                    beats.append(dict(execution_id=run["execution_id"],
                                      members=[name for _, name in _members(run)],
                                      pose_key=_held_pose(run), delta_game_s=delta))
            elif run["status"] not in store.TERMINAL:
                _save(run)
            advanced += 1
    _end_finales(expired_only=True)
    for beat in beats:
        _after_locks(lambda beat=beat: emit("prop_action.active", **beat))
    return advanced


#: REAL seconds between two beats of a run that fills gauges (see due_in_game_s)
METER_BEAT_REAL_S = 5.0


def due_in_game_s(now: GameTime):
    """Game seconds until a live run's next timed step — an entry clip, a
    combined phase ending or the next gauge beat (METER_BEAT_REAL_S) — or
    None when no run waits on the clock.

    The travel ticker beats on it (travel_engine._next_beat_s), so a sitter
    sits when the clip ends instead of on the next world-admin tick.
    """
    soonest = None
    for run in store.live_runs():
        data = run["data"]
        if (run["status"] == "approaching" and run["phase"] != "entry"
                and len(data.get("arrived", [])) == len(_members(run))
                and (data.get("reaction") or {}).get("state") == "pending"):
            # Waiting at the furniture on the SYSTEM clock: due once it ran out.
            if _reaction_waited_s(data["reaction"]) >= REACTION_WAIT_S:
                return 0.0
            continue
        left = None
        if run["status"] == "approaching" and run["phase"] == "entry" and data.get("entries"):
            left = max(e["duration_game_s"] for e in data["entries"].values()) - data.get("entry_elapsed", 0.0)
        elif run["status"] == "active" and run["definition"]["ability"] == "combined":
            phase = next((p for p in run["definition"]["phases"] if p["id"] == run["phase"]), None)
            if phase is not None:
                left = phase["duration_game_s"] - data.get("phase_elapsed", 0.0)
        if (run["status"] == "active" and run["definition"]["ability"] != "sleep"
                and game_speed_factor() > 0 and _meters(run)):
            # A package fills gauges on the beat (``prop_action.active``): a
            # beat every METER_BEAT_REAL_S keeps the finale on time, where the
            # world-admin tick alone would let it wait up to a minute.
            beat = METER_BEAT_REAL_S * game_speed_factor()
            left = beat if left is None else min(left, beat)
        if left is None:
            continue
        left -= max(0, (now - GameTime.parse(data["last_game"])).total_seconds)
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
    if len(invitees) != definition["participants"] - 1:
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
    result = dict(enabled=not reason, reason=reason)
    if include_plans:
        result["plans"] = plans if not reason else {}
    return result


def state_for(actor: str) -> dict:
    """Only an execution's exact participants may see its question/result."""
    from datetime import datetime, timedelta
    result = dict(incoming=[], outgoing=[], current=[], recent_results=[])
    if not isinstance(actor, str) or not actor:
        return result
    cutoff = utc_now() - timedelta(minutes=30)
    rows = store.db.get_connection().execute(
        "SELECT * FROM prop_action_runs WHERE " + store.TAKES_PART + " ORDER BY created_at,execution_id",
        (actor, actor)).fetchall()
    for raw in rows:
        terminal = raw["status"] in store.TERMINAL
        if terminal:
            try:
                if datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00")) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
        # A terminal commit precedes cleanup; wait for its departure before
        # publishing the row. Re-read even a formerly live cursor snapshot.
        with _lock(raw["execution_id"]):
            run = store.get(raw["execution_id"])
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
                   # package fills toward it (``prop_action.meters`` provider:
                   # ``[{name, value 0..100, label}]`` per participant).
                   has_finale=bool(finale_kind(_held_pose(run))),
                   meters=_meters(run) if not terminal and not pending else [])
        # The viewer's own alt halves (``set_alt``): None when its role has none.
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
    """The gauges of a running action, from the package that keeps them;
    [] without one or when it fails (a gauge never breaks the HUD row)."""
    from app.core.hooks import get_provider
    provider = get_provider("prop_action.meters")
    if provider is None:
        return []
    try:
        rows = provider(execution_id=run["execution_id"], members=[name for _, name in _members(run)],
                        pose_key=_held_pose(run))
    except Exception as exc:
        logger.warning("prop_action.meters provider failed: %s", exc)
        return []
    factor = game_speed_factor()
    since = 0.0
    if factor > 0:
        try:
            since = max(0.0, (game_time() - GameTime.parse(run["data"]["last_game"])).total_seconds)
        except (KeyError, TypeError, ValueError):
            since = 0.0
    out = []
    for row in rows or []:
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(row.get("name"), str) and math.isfinite(value):
            # ``rate`` = gauge points per GAME second. The stored value is as
            # of the run's last beat: carried forward to now, and handed out
            # per REAL second so a client fills the bar between two reads
            # instead of jumping a whole beat at once (0 = frozen world).
            try:
                rate = max(0.0, float(row.get("rate") or 0.0))
            except (TypeError, ValueError):
                rate = 0.0
            if not math.isfinite(rate):
                rate = 0.0
            value = min(100.0, max(0.0, value + rate * since))
            out.append(dict(name=row["name"], value=round(value, 1),
                            rate=round(rate * factor, 4),
                            label=str(row.get("label") or ""),
                            # ``hold_meter`` applies to this gauge / it is held now
                            holdable=row.get("holdable") is True, held=row.get("held") is True))
    return out


def _reaction_request(partner):
    """The reaction a react run starts with: ``player`` — a player-controlled
    partner reacts with the HUD (it can push the run away), nothing waits;
    ``none`` — no package supplies ``pair_reaction``, nothing waits;
    ``pending`` — the model is asked, the run waits at the furniture."""
    from app.core.hooks import get_provider
    from app.models.account import is_player_controlled
    if is_player_controlled(partner):
        state = "player"
    elif get_provider("pair_reaction") is None:
        state = "none"
    else:
        state = "pending"
    return dict(state=state, asked_at=utc_now().isoformat())


def _ask_reaction(run):
    """Hand the reaction to the ``pair_reaction`` provider after every lock;
    the provider returns at once and answers through :func:`react`."""
    from app.core.hooks import get_provider
    from app.core.keyed_lock import _after_locks
    provider = get_provider("pair_reaction")
    if provider is None:
        return

    def ask():
        try:
            provider(execution_id=run["execution_id"], actor=run["actor"], partner=run["members"][0])
        except Exception as e:
            logger.warning("pair_reaction provider failed for %s: %s", run["execution_id"], e)

    _after_locks(ask)


def _reaction_waited_s(reaction):
    try:
        return (utc_now() - parse_iso(reaction["asked_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return REACTION_WAIT_S


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
    """The reaction's mark on the pair, after every lock: the partner's
    sentiment toward the actor by ``feeling``, romantic tension for a romantic
    action, and a resisted actor's own sentiment."""
    from app.core.keyed_lock import _after_locks
    actor, partner, name = run["actor"], run["members"][0], run["definition"]["name"]

    def book():
        try:
            from app.models.relationship import record_interaction
            record_interaction(
                partner, actor, "pair_reaction",
                summary=f"{partner} {'accepted' if accepted else 'resisted'} {actor}'s {name}",
                sentiment_delta_a=_REACTION_SENTIMENT_STEP * feeling,
                sentiment_delta_b=0.0 if accepted else _RESISTED_ACTOR_SENTIMENT,
                strength_delta=1.0,
                romantic_delta=_REACTION_ROMANTIC_STEP * feeling if romantic else 0.0)
        except Exception as e:
            logger.warning("booking the reaction of %s failed: %s", partner, e)

    _after_locks(book)


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
    try:
        feeling = max(-2, min(2, int(feeling)))
    except (TypeError, ValueError):
        feeling = 0
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
            _begin_entry(run)
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
            and _last_consent(run, actor) and not is_world_frozen()):
        replaces = _replaced_runs(run["actor"], run["members"], run["target"], run["action_id"])
        if replaces and _validate(run, replaces=replaces):
            replaces = ()   # refused anyway: _respond says why, nothing ends
    direct = bool(replaces) and _switches_in_place(run, replaces)
    with _replacing(run, replaces):
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
