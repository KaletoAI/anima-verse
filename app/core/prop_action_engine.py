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
import uuid

from app.core import prop_action_store as store, places, props, travel_engine as travel
from app.core.game_time import GameTime, GameDuration
from app.core.timeutils import game_time, game_speed_factor, utc_now
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
    return [("actor", run["actor"])] + ([("partner", run["partner"])] if run["partner"] else [])


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
                    names = [run["actor"], run["partner"]] if effect["target"] == "both" else [run[effect["target"]]]
                    for name in names:
                        reason = effects.validate_profile_effects(profiles[name], [effect], catalogs)
                        if reason and phase != "active":
                            raise ValueError(reason)
                result = effects.apply_execution_effects(run["execution_id"], phase, now,
                                                        conn=conn, run=run, profiles=profiles, catalogs=catalogs)
                if result["effects"]:
                    run["data"].setdefault("effect_results", {})[phase] = result["effects"]
                for name, update in result["changed"].items():
                    aggregate = changed.setdefault(name, dict(changes={}, results={}))
                    aggregate["changes"].update(update["changes"])
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


def _validate(run, *, conn=None, require_claims=False, presence=True, _query=None):
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
        if held and held != run["execution_id"]:
            return "participant_claimed"
        if require_claims and held != run["execution_id"]:
            return "participant_claim_lost"
        profile = profiles[name] = C.get_character_profile(name)
        if places.where(name, profile=profile) != (run["target"]["location_id"], run["target"]["room_id"]):
            return "target_not_in_actor_room"
        owned_sleep_transition = (run["status"] == "active" and definition["ability"] == "sleep"
                                  and (profile.get("place") or {}).get("execution_id") == run["execution_id"])
        if profile.get("is_sleeping") and run["status"] != "sleeping" and not owned_sleep_transition:
            return "participant_asleep"
        journey = profile.get("journey")
        if journey and not _own_journey(run, name, journey):
            return "journey_already_active"
        if profile.get("interaction") and profile["interaction"].get("execution_ref") != run["execution_id"]:
            return "interaction_active"
        targeted = [effect for effect in definition["effects"]
                    if effect["target"] in (role, "both")]
        reason = validate_profile_effects(profile, targeted, catalogs)
        if reason:
            return reason
    if presence:
        present = {n for n, _ in places._present(run["target"]["location_id"], run["target"]["room_id"])}
        members = set(profiles)
        rule = definition["presence"]
        if ((rule == "alone" and present != {run["actor"]}) or
                (rule == "others" and not present - {run["actor"]}) or
                (rule == "participants_only" and present != members)):
            return "presence_not_met"
    reason = _requirements(run, profiles) if presence else ""
    if reason:
        return reason
    if require_claims:
        for role, plan in run["data"]["plans"].items():
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
            if anchor["slot"] not in places.free_slots(place, [(n, s) for n, s in taken
                    if n not in profiles and n != "@prop:" + run["execution_id"]]):
                return "slot_occupied"
            binding = next((b for b in place.get("action_bindings", [])
                            if b["action_id"] == run["action_id"]), None)
            if not binding or not binding.get("supported") or binding.get("validation") != "local_valid":
                return "binding_not_supported"
            current_access = binding.get("access_points", {}).get(run["data"]["access_roles"][role])
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


def _plan(run, *, conn, _query=None):
    from app.core.prop_action_paths import plan_approach
    query = _query if _query is not None else places._GeometryQuery()
    target = dict(run["target"], action_id=run["action_id"], definition_revision=run["definition_revision"])
    candidates = query.room_places(target["location_id"], target["room_id"])
    choices = []
    last_reason = "no_free_slot"
    occupancy = places.occupancy(target["location_id"], target["room_id"], _places=candidates)
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
        if definition["ability"] == "pair":
            from app.core.interaction_engine import plan_interaction_at
            try:
                allocation = plan_interaction_at(run["actor"], run["partner"], definition["pose_key"], place)
            except ValueError as exc:
                last_reason = str(exc)
                continue
            if any(s not in free for s in allocation["slots"].values()):
                continue
        else:
            allocation = dict(clip_roles={}, access_roles={"actor": "actor"}, slots={"actor": free[0]})
        pose = (definition["phases"][0]["pose_key"] if definition["ability"] == "combined"
                else definition["pose_key"])
        _, entry_reason = _entry_capability(pose)
        if entry_reason:
            last_reason = entry_reason
            continue
        plans = {}
        for role, name in _members(run):
            slot = allocation["slots"][role]
            plan = plan_approach(name, dict(target, marker_id=place["marker_id"], slot=slot),
                                 allocation["access_roles"][role], _query=query)
            if plan["status"] != "ok":
                last_reason = plan["reason"]
                break
            anchor = plan["entry_anchor"]
            if not places.inside(target["location_id"], anchor["x"], anchor["z"]):
                last_reason = "entry_anchor_outside_location"
                break
            plans[role] = plan
        if len(plans) == len(_members(run)):
            for role, name in _members(run):
                _, last_reason = _entry_spec(name, plans[role], pose, _query=query)
                if last_reason:
                    break
            if last_reason:
                continue
            distance = sum(sum(math.dist(a, b) for a, b in zip(p["waypoints"], p["waypoints"][1:])) for p in plans.values())
            choices.append((distance, place["id"], plans, allocation))
    if not choices:
        return {}, last_reason
    _, _, plans, allocation = min(choices, key=lambda p: p[:2])
    run["data"].update(clip_roles=allocation["clip_roles"], access_roles=allocation["access_roles"])
    return plans, ""


def request(actor: str, target: dict, action_id: str, revision: str, partner: str = "", request_id: str = "") -> dict:
    """Public Core result remains unchanged; admission metadata stays internal."""
    return request_with_creation(actor, target, action_id, revision, partner, request_id)[0]


def request_with_creation(actor: str, target: dict, action_id: str, revision: str,
                          partner: str = "", request_id: str = "") -> tuple[dict, bool]:
    """Return (result, created), with creation decided at the SQLite insert.

    Adapters must not infer creation from a successful status: a replay has the
    same result. The second nonce lookup under BEGIN IMMEDIATE also handles a
    competing Core caller/process that does not hold the adapter's nonce guard.
    """
    if (not isinstance(actor, str) or not actor or not isinstance(target, dict) or set(target) != set(_TARGET)
            or any(not isinstance(target[k], str) or not target[k] for k in _TARGET)
            or not all(isinstance(v, str) for v in (action_id, revision, partner, request_id))):
        return _refused("invalid_request"), False
    fingerprint = store.encode([target, action_id, revision, partner])
    previous = store.by_request(actor, request_id)
    if previous:
        return (_result(previous) if previous["request_fingerprint"] == fingerprint
                else _refused("request_id_conflict")), False
    if places.where(actor) != (target["location_id"], target["room_id"]):
        return _refused("target_not_in_actor_room"), False
    if is_world_frozen():
        return _refused("world_frozen"), False
    definition, reason = _definition(target, action_id, revision)
    if reason:
        return _refused(reason), False
    if bool(partner) != (definition["participants"] == 2) or actor == partner:
        return _refused("invalid_partner"), False
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
                return (_result(previous) if previous["request_fingerprint"] == fingerprint
                        else _refused("request_id_conflict")), False
            reason = _validate(run, conn=conn)
            if reason:
                return _refused(reason), False
            plans, reason = _plan(run, conn=conn)
            if reason:
                return _refused(reason), False
            run["data"]["plans"] = plans
            store.insert(conn, run)
            if not partner:
                store.acquire(conn, run, [p["entry_anchor"] for p in plans.values()])
        if not partner:
            _start_checked(run)
    _notify(run)
    if partner:
        # A decision/model or respond-lane request must never run inside an
        # execution/profile/place lock or an SQLite transaction.
        from app.core.hooks import emit
        from app.core.keyed_lock import _after_locks
        _after_locks(lambda: emit("prop_action.invited", execution_id=run["execution_id"], inviter=actor, invitee=partner))
    return _result(store.get(run["execution_id"])), True


def _respond(actor: str, execution_id: str, accept: bool) -> dict:
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
            now = game_time()
            data = run["data"]
            if data["process"] == _PROCESS:
                data["consent_elapsed"] += max(0, (now - GameTime.parse(data["last_game"])).total_seconds)
            data.update(last_game=now.canonical(), process=_PROCESS)
            if data["consent_elapsed"] >= 300:
                run.update(status="cancelled", reason="consent_expired")
                store.save(conn, run)
                return _result(run)
            reason = _validate(run, conn=conn)
            agreed_roles = dict(data["clip_roles"])
            agreed_access = dict(data["access_roles"])
            plans, plan_reason = _plan(run, conn=conn) if not reason else ({}, "")
            reason = reason or plan_reason
            if not reason and data["clip_roles"] != agreed_roles:
                data.update(clip_roles=agreed_roles, access_roles=agreed_access)
                reason = "pair_roles_changed"
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
        journey, reason = travel.start_approach_journey(name, target, run["data"]["access_roles"][role], execution_kind="prop_action",
                            execution_ref=run["execution_id"], journey_id=run["data"]["journey_ids"][name])
        if not journey:
            _finish(run, "failed", reason)
            return
        delay = max(0, (GameTime.parse(journey["started_at_game"]) - game_time()).total_seconds)
        deadline = max(deadline, float(journey["waypoints"][-1][2]) + delay + 60)
    run["data"].update(deadline=deadline, last_game=game_time().canonical())
    _save(run)


def _own_journey(run, name, journey):
    matches = (journey.get("execution_kind") == "prop_action" and journey.get("execution_ref") == run["execution_id"]
               and journey.get("journey_id") == run["data"]["journey_ids"].get(name))
    if not matches or "approach_target" not in journey:
        return matches  # A durable receipt has identity, not an approach body.
    semantic_role = "actor" if name == run["actor"] else "partner"
    plan = run["data"]["plans"][semantic_role]
    target = journey["approach_target"]
    return (journey.get("approach_role") == run["data"]["access_roles"][semantic_role]
            and journey.get("entry_anchor") == plan["entry_anchor"]
            and target.get("marker_id") == plan["entry_anchor"]["marker_id"]
            and target.get("slot") == plan["entry_anchor"]["slot"])


@_internal_mutation()
def _finish(run, status, reason):
    if run["status"] in store.TERMINAL:
        return _result(run)
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
    run.update(status=status, reason=reason)
    run["data"]["cleanup_pending"] = True
    _commit(run, phases)  # Terminal, effects and claim release precede cleanup.
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
        C.release_prop_action_state(name, run["execution_id"])
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
                    checkpoint = GameTime.parse(journey.get("position_checkpoint_game", data["last_game"]))
                    anchored = GameTime.parse(journey.get("prop_action_reanchored_at", checkpoint.canonical()))
                    shift = max(0, (now - max(checkpoint, anchored)).total_seconds)
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
    from app.core.animation_clips import resolve_transition, clip_meta, _solo_kinds
    rule = resolve_transition("walking", pose)
    if not rule:
        return None, "missing_entry_transition"
    kind = rule["kind"]
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
    from app.core.animation_clips import clip_travel_m, clip_ref_height_m
    from app.core.room_stand import bridge_offset, bridge_scale
    from app.core.height import height_cm
    capability, reason = _entry_capability(pose)
    if reason:
        return None, reason
    kind, meta = capability
    anchor, access = plan["entry_anchor"], plan["access"]
    delta = bridge_offset(clip_travel_m(kind), float(access["yaw"]),
                          bridge_scale(height_cm(C.get_character_profile(name)), clip_ref_height_m(kind)))
    if math.dist((access["x"] + delta[0], access["z"] + delta[1]), (anchor["x"], anchor["z"])) > .05:
        return None, "entry_transition_mismatch"
    from app.core.prop_action_paths import _departure_walkable
    query = _query if _query is not None else places._GeometryQuery()
    geometry = query.room_geometry(anchor["location_id"], anchor["room_id"])
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
    now = game_time()
    run["data"].update(entries=entries, entry_elapsed=0.0, last_game=now.canonical(),
                       entry_started_game_s=now.total_seconds)
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
                start_interaction_at(run["actor"], run["partner"], pose, execution_id=run["execution_id"],
                                     plans=run["data"]["plans"], commit_profiles=entered)
            except ValueError as exc:
                # Validation failures are refusals, not synthetic entry success.
                run = store.get(run["execution_id"])
                _finish(run, "failed", str(exc))
                return
        else:
            name = run["actor"]
            anchor = run["data"]["plans"]["actor"]["entry_anchor"]
            place = dict(id=anchor["place_id"], slot=anchor["slot"],
                         room_id=run["target"]["room_id"], execution_id=run["execution_id"])
            entered({name: dict(pose_key=pose, pose_flavor="", place=place, prop_action_entry=None,
                                pos_x=anchor["x"], pos_z=anchor["z"], pos_session=None, pos_seq=None)})
    if ability != "pair":
        C._publish_activity_changed(run["actor"], pose, "", pose, place, None)
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
                        _activate(run)
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
                        # Pose and phase/effect progress commit together below.
            if run["status"] == "active" and run["definition"]["ability"] != "sleep":
                runtime = None
                if run["definition"]["ability"] == "combined":
                    phase = next(p for p in run["definition"]["phases"] if p["id"] == run["phase"])
                    runtime = {run["actor"]: {"pose_key": phase["pose_key"]}}
                _commit(run, ("active",), runtime=runtime, now=now)
            elif run["status"] not in store.TERMINAL:
                _save(run)
            advanced += 1
    return advanced


def _notify(run):
    """Private invalidation only, never broadcast invitation/target payloads."""
    from app.core.keyed_lock import _after_locks
    from app.core.sync_topics import avatars
    names = tuple(name for _, name in _members(run))
    _after_locks(lambda: avatars(names, ("self", "scene")))


def check(actor: str, target: dict, action_id: str, revision: str, partner: str = "", *, _query=None, include_plans: bool = False) -> dict:
    """Read-only preflight; optional admin diagnostics reuse the actual successful plans."""
    if (not isinstance(target, dict) or set(target) != set(_TARGET)
            or any(not isinstance(target[k], str) or not target[k] for k in _TARGET)
            or not all(isinstance(v, str) and v for v in (actor, action_id, revision))
            or not isinstance(partner, str)):
        return dict(enabled=False, reason="invalid_request")
    if places.where(actor) != (target["location_id"], target["room_id"]):
        return dict(enabled=False, reason="target_not_in_actor_room")
    query = _query if _query is not None else places._GeometryQuery()
    definition, reason = _definition(target, action_id, revision, _query=query)
    if reason:
        return dict(enabled=False, reason=reason)
    if bool(partner) != (definition["participants"] == 2) or actor == partner:
        return dict(enabled=False, reason="invalid_partner")
    run = dict(execution_id="", actor=actor, partner=partner, action_id=action_id,
               definition_revision=revision, target=target, definition=definition,
               status="awaiting_consent" if partner else "approaching",
               data=dict(plans={}, journey_ids={}, access_roles={}))
    plans = {}
    reason = "world_frozen" if is_world_frozen() else _validate(run, _query=query)
    if not reason:
        plans, reason = _plan(run, conn=store.db.get_connection(), _query=query)
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
        "SELECT * FROM prop_action_runs WHERE actor=? OR partner=? ORDER BY created_at,execution_id",
        (actor, actor))
    for raw in rows:
        run = store._decode(raw)
        terminal = run["status"] in store.TERMINAL
        if terminal:
            try:
                if datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00")) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
        pending = run["status"] == "awaiting_consent"
        row = {k: run[k] for k in ("execution_id", "action_id", "definition_revision",
                                  "target", "actor", "partner", "status", "phase", "reason")}
        row.update(label=run["definition"]["name"],
                   phase_label=(next((phase["label"] for phase in run["definition"]["phases"]
                                      if phase["id"] == run["phase"]), "")
                                if run["definition"]["ability"] == "combined" else ""),
                   roles={"actor": run["actor"], **({"partner": run["partner"]} if run["partner"] else {}),
                          "clip": run["data"].get("clip_roles", {}),
                          "access": run["data"].get("access_roles", {})},
                   can_respond=pending and actor == run["partner"], can_cancel=not terminal)
        if terminal:
            row["effects"] = run["data"].get("effect_results", {})
            result["recent_results"].append(row)
        elif pending:
            result["incoming" if actor == run["partner"] else "outgoing"].append(row)
        else:
            result["current"].append(row)
    return result


def respond(actor: str, execution_id: str, accept: bool) -> dict:
    result = _respond(actor, execution_id, accept)
    if result["status"] != "refused":
        run = store.get(execution_id)
        if run:
            _notify(run)
    return result


def has_semantic_action(actor: str) -> bool:
    """Implicit narration never overrides an explicit, still-owned action."""
    row = store.db.get_connection().execute(
        "SELECT 1 FROM prop_action_runs WHERE (actor=? OR partner=?) "
        "AND status NOT IN ('completed','cancelled','failed') LIMIT 1", (actor, actor)).fetchone()
    return row is not None
