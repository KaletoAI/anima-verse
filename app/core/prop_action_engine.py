"""Persistent exact-target prop actions, deliberately not exposed through HTTP.

Run locks are reentrant (travel cancellation can call back inside its guard).
Claims use SQLite, never actor-global locks. No owner callback runs under a
profile lock. Offline intervals pause execution; receipts recover actual Core
arrival writes, not inferred animation completion. Task5 installs effects;
until then effectful requests are explicitly unavailable, never successful.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock, RLock
from weakref import WeakValueDictionary
import math
import operator
import uuid

from app.core import prop_action_store as store, places, props, travel_engine as travel
from app.core.game_time import GameTime, GameDuration
from app.core.timeutils import game_time, game_speed_factor
from app.core.keyed_lock import keyed_lock
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


def _result(run):
    return {"execution_id": run["execution_id"], "status": run["status"], "reason": run["reason"]}


def _refused(reason):
    return dict(execution_id="", status="refused", reason=reason)


def _members(run):
    return [("actor", run["actor"])] + ([("partner", run["partner"])] if run["partner"] else [])


def _save(run):
    with store.transaction() as conn:
        store.save(conn, run)


@contextmanager
def _claim_transaction(run):
    # Existing seating uses location-place -> profile. Keep that order and
    # never call profile writers/callbacks in the SQLite acquisition span.
    with keyed_lock("places", run["target"]["location_id"]):
        with store.transaction() as conn:
            yield conn


def _definition(target, action_id, revision):
    candidates = [p for p in places._compose(target["location_id"]).get(target["room_id"], [])
                  if p.get("placement_id") == target["placement_id"]]
    if not candidates:
        return None, "placement_not_found"
    candidates = [p for p in candidates if p.get("variant_uid") == target["variant_uid"]]
    if not candidates:
        return None, "stale_variant"
    # Author snapshot, not the rendering getter (which can demand media work).
    prop = props.read_sidecar(candidates[0]["prop_id"])
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
    if any(bool(catalog[key].get("solo", True)) != (action["participants"] == 1) for key in keys):
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
        names = [run["actor"], run["partner"]] if req["target"] == "both" else [run[req["target"]]]
        for name in names:
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


def _validate(run, *, conn=None, require_claims=False, presence=True):
    definition, reason = _definition(run["target"], run["action_id"], run["definition_revision"])
    if reason:
        return reason
    if definition != run["definition"]:
        return "stale_definition"
    if definition.get("effects"):
        return "effect_application_unavailable"
    profiles = {}
    for role, name in _members(run):
        row = (conn or store.db.get_connection()).execute("SELECT status FROM characters WHERE name=?", (name,)).fetchone()
        if row is None or row[0]:
            return "participant_unavailable"
        held = store.held(store.person_key(name), conn=conn)
        if held and held != run["execution_id"]:
            return "participant_claimed"
        if require_claims and held != run["execution_id"]:
            return "participant_claim_lost"
        profile = profiles[name] = C.get_character_profile(name)
        if places.where(name, profile=profile) != (run["target"]["location_id"], run["target"]["room_id"]):
            return "target_not_in_actor_room"
        if profile.get("is_sleeping") and run["status"] != "sleeping":
            return "participant_asleep"
        journey = profile.get("journey")
        if journey and not _own_journey(run, name, journey):
            return "journey_already_active"
        if profile.get("interaction") and profile["interaction"].get("execution_ref") != run["execution_id"]:
            return "interaction_active"
    if presence:
        present = {n for n, _ in places._present(run["target"]["location_id"], run["target"]["room_id"])}
        members = set(profiles)
        rule = definition["presence"]
        if ((rule == "alone" and present != {run["actor"]}) or
                (rule == "others" and not present - {run["actor"]}) or
                (rule == "participants_only" and present != members)):
            return "presence_not_met"
    reason = _requirements(run, profiles)
    if reason:
        return reason
    if require_claims:
        for role, plan in run["data"]["plans"].items():
            anchor = plan["entry_anchor"]
            key = store.slot_key(run["target"], anchor["marker_id"], anchor["slot"])
            if store.held(key, conn=conn) != run["execution_id"]:
                return "slot_claim_lost"
            place = next((p for p in places._compose(run["target"]["location_id"]).get(run["target"]["room_id"], [])
                          if p["id"] == anchor["place_id"]), None)
            if not place:
                return "placement_not_found"
            taken = places.occupancy(run["target"]["location_id"], run["target"]["room_id"]).get(place["id"], [])
            if anchor["slot"] not in places.free_slots(place, [(n, s) for n, s in taken
                    if n not in profiles and n != "@prop:" + run["execution_id"]]):
                return "slot_occupied"
            binding = next((b for b in place.get("action_bindings", [])
                            if b["action_id"] == run["action_id"]), None)
            if not binding or not binding.get("supported") or binding.get("validation") != "local_valid":
                return "binding_not_supported"
            current_access = binding.get("access_points", {}).get(role)
            if current_access != plan["access"] or list(place["slots"][anchor["slot"]]) != [anchor["x"], anchor["z"]] or place["y_world"] != anchor["y"]:
                return "approach_target_changed"
            if run["status"] == "approaching" and (run["phase"] == "entry" or run[role] in run["data"]["arrived"]):
                pos = C.get_character_pos(run[role])
                if not pos or math.dist((pos["x"], pos["z"]), (plan["access"]["x"], plan["access"]["z"])) > .05:
                    return "access_position_lost"
            if run["status"] in ("active", "sleeping"):
                profile = profiles[run[role]]
                field = profile.get("place") or {}
                if field.get("execution_id") != run["execution_id"] or field.get("id") != anchor["place_id"] or field.get("slot") != anchor["slot"]:
                    return "owned_place_lost"
                pos = C.get_character_pos(run[role])
                if not pos or math.dist((pos["x"], pos["z"]), (anchor["x"], anchor["z"])) > .05:
                    return "owned_position_lost"
    return ""


def _plan(run, *, conn):
    from app.core.prop_action_paths import plan_approach
    target = dict(run["target"], action_id=run["action_id"], definition_revision=run["definition_revision"])
    candidates = places._compose(target["location_id"]).get(target["room_id"], [])
    choices = []
    last_reason = "no_free_slot"
    occupancy = places.occupancy(target["location_id"], target["room_id"])
    for place in candidates:
        if place.get("placement_id") != target["placement_id"] or place.get("variant_uid") != target["variant_uid"]:
            continue
        from app.core.pose_catalog import group_of
        definition = run["definition"]
        keys = [p["pose_key"] for p in definition["phases"]] if definition["ability"] == "combined" else [definition["pose_key"]]
        if any(group_of(key) != place["group"] for key in keys):
            last_reason = "incompatible_pose_marker"
            continue
        free = [s for s in places.free_slots(place, occupancy.get(place["id"], []))
                if not store.held(store.slot_key(target, place["marker_id"], s), conn=conn)]
        if len(free) < len(_members(run)):
            continue
        plans = {}
        for (role, name), slot in zip(_members(run), free):
            plan = plan_approach(name, dict(target, marker_id=place["marker_id"], slot=slot), role)
            if plan["status"] != "ok":
                last_reason = plan["reason"]
                break
            anchor = plan["entry_anchor"]
            if not places.inside(target["location_id"], anchor["x"], anchor["z"]):
                last_reason = "entry_anchor_outside_location"
                break
            plans[role] = plan
        if len(plans) == len(_members(run)):
            distance = sum(sum(math.dist(a, b) for a, b in zip(p["waypoints"], p["waypoints"][1:])) for p in plans.values())
            choices.append((distance, place["id"], plans))
    return (min(choices, key=lambda p: p[:2])[2], "") if choices else ({}, last_reason)


def request(actor: str, target: dict, action_id: str, revision: str, partner: str = "", request_id: str = "") -> dict:
    if (not isinstance(actor, str) or not actor or not isinstance(target, dict) or set(target) != set(_TARGET)
            or any(not isinstance(target[k], str) or not target[k] for k in _TARGET)
            or not all(isinstance(v, str) for v in (action_id, revision, partner, request_id))):
        return _refused("invalid_request")
    fingerprint = store.encode([target, action_id, revision, partner])
    previous = store.by_request(actor, request_id)
    if previous:
        return _result(previous) if previous["request_fingerprint"] == fingerprint else _refused("request_id_conflict")
    if is_world_frozen():
        return _refused("world_frozen")
    definition, reason = _definition(target, action_id, revision)
    if reason:
        return _refused(reason)
    if bool(partner) != (definition["participants"] == 2) or actor == partner:
        return _refused("invalid_partner")
    # Internal pre-Task5 boundary, removed by its real transactional adapter.
    if definition.get("effects"):
        return _refused("effect_application_unavailable")
    now = game_time().canonical()
    run = dict(execution_id=uuid.uuid4().hex, actor=actor, partner=partner, request_id=request_id or None,
               request_fingerprint=fingerprint, action_id=action_id, definition_revision=revision,
               status="awaiting_consent" if partner else "approaching", phase="", reason="", target=target,
               definition=definition, data=dict(plans={}, journey_ids={}, arrived=[], process=_PROCESS,
                                                last_game=now, elapsed=0.0, consent_elapsed=0.0))
    with _lock(run["execution_id"]):
        with _claim_transaction(run) as conn:
            previous = store.by_request(actor, request_id, conn=conn)
            if previous:
                return _result(previous) if previous["request_fingerprint"] == fingerprint else _refused("request_id_conflict")
            reason = _validate(run, conn=conn)
            if reason:
                return _refused(reason)
            plans, reason = _plan(run, conn=conn)
            if reason:
                return _refused(reason)
            run["data"]["plans"] = plans
            store.insert(conn, run)
            if not partner:
                store.acquire(conn, run, [p["entry_anchor"] for p in plans.values()])
        if not partner:
            _start_checked(run)
        return _result(store.get(run["execution_id"]))


def respond(actor: str, execution_id: str, accept: bool) -> dict:
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or run["partner"] != actor:
            return _refused("not_invitee")
        if type(accept) is not bool:
            return _refused("invalid_response")
        if run["status"] != "awaiting_consent":
            return _result(run)
        if not accept:
            return _finish(run, "cancelled", "consent_declined")
        if is_world_frozen():
            return _refused("world_frozen")
        with _claim_transaction(run) as conn:
            run = store.get(execution_id, conn=conn)
            if run["status"] != "awaiting_consent":
                return _result(run)
            reason = _validate(run, conn=conn)
            plans, plan_reason = _plan(run, conn=conn) if not reason else ({}, "")
            reason = reason or plan_reason
            if reason:
                run.update(status="failed", reason=reason)
                store.save(conn, run)
                return _result(run)
            run["data"].update(plans=plans, consented=True, last_game=game_time().canonical(), process=_PROCESS)
            run["status"] = "approaching"
            store.acquire(conn, run, [p["entry_anchor"] for p in plans.values()])
            store.save(conn, run)
        _start_checked(run)
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
    for role, name in _members(run):
        anchor = run["data"]["plans"][role]["entry_anchor"]
        target = dict(run["target"], action_id=run["action_id"], definition_revision=run["definition_revision"],
                      marker_id=anchor["marker_id"], slot=anchor["slot"])
        journey, reason = travel.start_approach_journey(name, target, role, execution_kind="prop_action",
                            execution_ref=run["execution_id"], journey_id=run["data"]["journey_ids"][name])
        if not journey:
            _finish(run, "failed", reason)
            return
        delay = max(0, (GameTime.parse(journey["started_at_game"]) - game_time()).total_seconds)
        deadline = max(deadline, float(journey["waypoints"][-1][2]) + delay + 60)
    run["data"].update(deadline=deadline, last_game=game_time().canonical())
    _save(run)


def _own_journey(run, name, journey):
    return (journey.get("execution_kind") == "prop_action" and journey.get("execution_ref") == run["execution_id"]
            and journey.get("journey_id") == run["data"]["journey_ids"].get(name))


@_internal_mutation()
def _finish(run, status, reason):
    if run["status"] in store.TERMINAL:
        return _result(run)
    if run["status"] == "active":
        # Preserve the final actually online interval even when cancellation
        # precedes the next periodic tick. Task5 applies its rates atomically.
        delta = _clock(run, game_time())
        run["data"]["active_game_s"] = run["data"].get("active_game_s", 0) + delta
        if run["definition"]["ability"] == "combined":
            run["data"]["phase_elapsed"] += delta
    run.update(status=status, reason=reason)
    run["data"]["cleanup_pending"] = True
    _save(run)  # Terminal and claim release precede recursive cancellation.
    _cleanup(run)
    return _result(run)


@_internal_mutation()
def _cleanup(run):
    reason = run["reason"]
    for role, name in _members(run):
        jid = run["data"]["journey_ids"].get(name)
        if jid:
            travel.cancel_journey(name, journey_id=jid, execution_kind="prop_action", execution_ref=run["execution_id"], reason=reason)
        profile = C.get_character_profile(name)
        inter = profile.get("interaction") or {}
        if inter.get("execution_ref") == run["execution_id"]:
            from app.core.interaction_engine import end_interaction
            end_interaction(name, reason=reason, interaction_id=inter["id"])
        profile = C.get_character_profile(name)
        if (profile.get("place") or {}).get("execution_id") == run["execution_id"]:
            sleeping = bool(profile.get("is_sleeping"))
            C.clear_pose_intent(name)
            if sleeping:
                C.set_is_sleeping(name, False, _prop_execution=run["execution_id"])
        with keyed_lock("character_profile", name):
            profile = C.get_character_profile(name)
            if (profile.get("prop_action_entry") or {}).get("execution_id") == run["execution_id"]:
                profile.pop("prop_action_entry", None)
                C.save_character_profile(name, profile)
    store.cleanup_finished(run["execution_id"])


def cancel(actor: str, execution_id: str) -> dict:
    with _lock(execution_id):
        run = store.get(execution_id)
        if not run or actor not in (run["actor"], run["partner"]):
            return _refused("not_participant")
        if run["status"] in store.TERMINAL:
            if run["data"].get("cleanup_pending"):
                _cleanup(run)
            return _result(run)
        normal = run["status"] == "active" and run["definition"]["ability"] in ("pose", "pair")
        return _finish(run, "completed" if normal else "cancelled", "ended" if normal else "cancelled")


def interrupt_after_locks(actor, reason):
    if _INTERNAL_MUTATION.get():
        return
    from app.core.keyed_lock import _after_locks
    _after_locks(lambda: interrupt(actor, reason))


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


def interrupt(actor, reason, *, execution_id=""):
    """Mutation boundaries call before profile locks; no broad cancellation."""
    if _INTERNAL_MUTATION.get():
        return
    for run in store.live_runs():
        if actor not in (run["actor"], run["partner"]) or (execution_id and run["execution_id"] != execution_id):
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
                    anchored = GameTime.parse(journey.get("prop_action_reanchored_at", data["last_game"]))
                    shift = max(0, (now - max(previous, anchored)).total_seconds)
                    journey["started_at_game"] = (GameTime.parse(journey["started_at_game"]) + GameDuration.of(seconds=shift)).canonical()
                    journey["prop_action_reanchored_at"] = now.canonical()
                    C.save_character_profile(name, profile)
        data["process"] = _PROCESS
    data["last_game"] = now.canonical()
    return 0.0 if restarted or is_world_frozen() else float(gap)


@contextmanager
def owner_guard(actor, journey):
    ref = journey.get("execution_ref", "")
    with _lock(ref):
        run = store.get(ref)
        allowed = bool(run and run["status"] == "approaching" and actor in dict((n, r) for r, n in _members(run))
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
    return not reason and room_id == run["target"]["room_id"], reason or "room_mismatch"


def _arrived(actor, journey):
    with _lock(journey["execution_ref"]):
        run = store.get(journey["execution_ref"])
        if not run or run["status"] != "approaching" or not _own_journey(run, actor, journey):
            return
        if actor not in run["data"]["arrived"]:
            run["data"]["arrived"].append(actor)
            _save(run)
        if len(run["data"]["arrived"]) == len(_members(run)):
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


def _entry_spec(name, plan, pose):
    from app.core.animation_clips import resolve_transition, clip_meta, clip_travel_m, clip_ref_height_m, clip_kinds
    from app.core.room_stand import bridge_offset, bridge_scale, room_geometry
    from app.core.height import height_cm
    rule = resolve_transition("walking", pose)
    if not rule:
        return None, "missing_entry_transition"
    kind = rule["kind"]
    meta = clip_meta(kind)
    if kind not in clip_kinds() or not meta or not math.isfinite(float(meta.get("duration_s", 0))) or float(meta.get("duration_s", 0)) <= 0:
        return None, "missing_entry_transition"
    anchor, access = plan["entry_anchor"], plan["access"]
    delta = bridge_offset(clip_travel_m(kind), float(access["yaw"]),
                          bridge_scale(height_cm(C.get_character_profile(name)), clip_ref_height_m(kind)))
    if math.dist((access["x"] + delta[0], access["z"] + delta[1]), (anchor["x"], anchor["z"])) > .05:
        return None, "entry_transition_mismatch"
    from app.core.prop_action_paths import _departure_walkable
    geometry = room_geometry(anchor["location_id"], anchor["room_id"])
    if not geometry or not _departure_walkable((anchor["x"], anchor["z"]), (access["x"], access["z"]),
                                               geometry, anchor["placement_id"]):
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
    for role, name in _members(run):
        spec, reason = _entry_spec(name, run["data"]["plans"][role], pose)
        if reason:
            _finish(run, "failed", reason)
            return
        entries[name] = spec
    run["phase"] = "entry"
    run["data"].update(entries=entries, entry_elapsed=0.0, last_game=game_time().canonical())
    _save(run)
    # Display actual bridge at exact access; no place/body anchor until it ends.
    from app.core.keyed_lock import keyed_lock
    for role, name in _members(run):
        with keyed_lock("character_profile", name):
            profile = C.get_character_profile(name)
            profile["prop_action_entry"] = dict(execution_id=run["execution_id"], **entries[name],
                access=run["data"]["plans"][role]["access"], anchor=run["data"]["plans"][role]["entry_anchor"])
            C.save_character_profile(name, profile)


def _activate(run):
    reason = _validate(run, require_claims=True)
    if reason:
        _finish(run, "failed", reason)
        return
    ability = run["definition"]["ability"]
    pose = next(iter(run["data"]["entries"].values()))["pose_key"]
    if ability == "pair":
        from app.core.interaction_engine import start_interaction_at
        try:
            start_interaction_at(run["actor"], run["partner"], pose, execution_id=run["execution_id"],
                                 plans=run["data"]["plans"])
        except ValueError as exc:
            _finish(run, "failed", str(exc))
            return
    else:
        # Exactly the reserved slot; generic assign/set_pose would pick another.
        from app.core.keyed_lock import keyed_lock
        name = run["actor"]
        anchor = run["data"]["plans"]["actor"]["entry_anchor"]
        with keyed_lock("places", run["target"]["location_id"]):
            with keyed_lock("character_profile", name):
                profile = C.get_character_profile(name)
                profile.update(pose_key=pose, pose_flavor="", place=dict(id=anchor["place_id"], slot=anchor["slot"],
                               room_id=run["target"]["room_id"], execution_id=run["execution_id"]))
                profile.pop("prop_action_entry", None)
                if not C.save_character_profile(name, profile):
                    raise RuntimeError("prop action entry profile write failed")
                C._write_character_pos(name, anchor["x"], anchor["z"])
        C._publish_activity_changed(name, pose, "", pose, profile["place"], None)
    run["status"] = "active"
    run["phase"] = run["definition"]["phases"][0]["id"] if ability == "combined" else "active"
    run["data"].update(phase_elapsed=0.0, active_game_s=0.0, last_game=game_time().canonical())
    _save(run)
    if ability == "sleep":
        # Canonical sleeping flag/lifecycle, no off-map skill and no bed search.
        C.set_is_sleeping(run["actor"], True, _prop_execution=run["execution_id"])
        if not C.is_character_sleeping(run["actor"]):
            _finish(run, "failed", "sleep_transition_failed")
            return
        run["status"], run["phase"] = "sleeping", "sleeping"
        _save(run)


def advance(now: GameTime) -> int:
    register_owner()
    advanced = 0
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
            if (run["status"] == "sleeping" and not C.is_character_sleeping(run["actor"])
                    and store.db.get_connection().execute("SELECT 1 FROM characters WHERE name=?", (run["actor"],)).fetchone()):
                _finish(run, "completed", "awake")
                continue
            if (run["status"] == "active" and run["definition"]["ability"] == "sleep"
                    and C.is_character_sleeping(run["actor"])
                    and (C.get_character_profile(run["actor"]).get("place") or {}).get("execution_id") == run["execution_id"]):
                # Real flag + exact owned bed recover the awake->asleep write
                # if the process died before recording its callback/state.
                run["status"], run["phase"] = "sleeping", "sleeping"
                _save(run)
            reason = _validate(run, require_claims=run["status"] != "awaiting_consent",
                               presence=run["status"] in ("awaiting_consent", "approaching") or run["definition"]["interrupt_on_presence_change"])
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
                        try:
                            _activate(run)
                        except Exception:
                            logger.exception("Prop action entry failed: %s", run["execution_id"])
                            _finish(run, "failed", "entry_error")
                        advanced += 1
                        continue
                else:
                    data["elapsed"] += delta
                    if data["elapsed"] > data.get("deadline", 60):
                        _finish(run, "failed", "approach_timeout")
                        continue
                    for role, name in _members(run):
                        if name in data["arrived"]:
                            continue
                        profile = C.get_character_profile(name)
                        if profile.get("journey") and _own_journey(run, name, profile["journey"]):
                            continue
                        receipt = profile.get("last_journey_result") or {}
                        if _own_journey(run, name, receipt) and receipt["status"] == "arrived":
                            # Actual durable arrival proof and exact floor point.
                            access = data["plans"][role]["access"]
                            pos = C.get_character_pos(name)
                            if pos and math.dist((pos["x"], pos["z"]), (access["x"], access["z"])) <= .02:
                                data["arrived"].append(name)
                                continue
                        _finish(run, "failed", "approach_journey_lost")
                        break
                    if run["status"] not in store.TERMINAL and len(data["arrived"]) == len(_members(run)):
                        _begin_entry(run)
                        advanced += 1
                        continue
            elif run["status"] == "sleeping":
                if not C.is_character_sleeping(run["actor"]):
                    _finish(run, "completed", "awake")
                    continue
            elif run["status"] == "active":
                data["active_game_s"] += delta
                if run["definition"]["ability"] == "combined":
                    phases = run["definition"]["phases"]
                    index = next(i for i, p in enumerate(phases) if p["id"] == run["phase"])
                    data["phase_elapsed"] += delta
                    while data["phase_elapsed"] >= phases[index]["duration_game_s"]:
                        data["phase_elapsed"] -= phases[index]["duration_game_s"]
                        index += 1
                        if index == len(phases):
                            _finish(run, "completed", "phases_completed")
                            break
                        run["phase"] = phases[index]["id"]
                        # Phase pose is applied to the same exact occupied slot.
                        from app.core.keyed_lock import keyed_lock
                        with keyed_lock("character_profile", run["actor"]):
                            profile = C.get_character_profile(run["actor"])
                            profile["pose_key"] = phases[index]["pose_key"]
                            C.save_character_profile(run["actor"], profile)
            if run["status"] not in store.TERMINAL:
                _save(run)
            advanced += 1
    return advanced
