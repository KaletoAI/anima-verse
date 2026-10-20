"""Continue an agreed trip through an optional package-provided paired activity.

Only the existing intent metadata stores execution receipts. An invitation is
not execution, and a running pair is not completion: its exact end signal is
required. External consent requests happen outside intent/membership locks.
"""
from app.core import hooks
from app.core.keyed_lock import keyed_lock
from app.models import intents as I


def _runtime():
    from plugins.party import trip_intents
    return trip_intents


def validate(owner, target, action):
    provider = hooks.get_provider("shared_activity_validate")
    if not provider:
        raise ValueError("No shared activity capability is installed.")
    return provider(owner, target, action)


def arrive(intent):
    """Persist arrival or observe the exact invitation; return whether to request."""
    T = _runtime()
    followup = intent["action"].get("after_arrival")
    if not followup:
        T._save(intent, {**T._state(intent), "phase": "arrived", "reason": ""})
        if not I.complete_intent(intent["id"]):
            raise RuntimeError("Arrival completion could not be persisted.")
        return False
    state = T._state(intent)
    activity = state.get("activity") or {}
    if activity.get("ended"):
        T._save(intent, {**state, "phase": "completed", "reason": ""})
        if not I.complete_intent(intent["id"]):
            raise RuntimeError("Activity completion could not be persisted.")
        return False
    if any(T._position(name) != intent["action"]["destination"] for name in state["expected_members"]):
        T._terminate(intent, "A participant left before the agreed activity finished.")
        return False
    gated = T._gated()
    if gated:
        T._save(intent, {**state, "reason": gated})
        return False
    status = hooks.get_provider("shared_activity_status")
    if not status:
        T._save(intent, {**state, "phase": "blocked", "reason": "The shared activity package is unavailable."})
        return False
    request_id = activity.get("request_id")
    if not request_id:
        T._save(intent, {**state, "phase": "waiting_activity", "reason": "Waiting to propose the agreed activity.",
                         "activity": {"request_id": "iinv_intent_" + intent["id"]}})
        return True
    result = status(intent["owner"], state["invitee"], followup, request_id)
    if result.get("status") == "not_found":
        # Persisted before submission: deterministic request identity recovers
        # a crash here without replacing or replaying another invitation.
        return True
    _observe(intent, result)
    return False


def _observe(intent, result):
    T = _runtime()
    state = T._state(intent)
    if (state.get("activity") or {}).get("ended") or intent["status"] != "active":
        return
    status = result.get("status")
    if status in {"pending", "approaching", "running", "declined"}:
        state = {**state, "activity": {**(state.get("activity") or {}), "submitted": True}}
    if result.get("terminal"):
        T._terminate(intent, result.get("reason") or "The activity invitation ended without execution.")
        return
    if status == "declined":
        T._terminate(intent, "The companion declined the activity after arrival.")
    elif status == "running":
        activity = {**(state.get("activity") or {}), "interaction_id": result["interaction_id"]}
        T._save(intent, {**state, "activity": activity, "phase": "activity", "reason": ""})
    elif status in {"pending", "approaching"}:
        T._save(intent, {**state, "phase": "waiting_activity", "reason": result.get("reason") or
                         "Waiting for the companion's activity answer."})
    else:
        T._save(intent, {**state, "phase": "blocked", "reason": result.get("reason") or
                         "The agreed activity cannot start."})


def request(intent_id):
    """Request consent outside locks, then reconcile the actual result."""
    T = _runtime()
    with keyed_lock("intent_execution", intent_id):
        intent = I.get_intent(intent_id)
        if not intent or intent["status"] != "active" or T._gated():
            return
        state = T._state(intent)
        activity = state.get("activity") or {}
        if not activity.get("request_id") or activity.get("interaction_id"):
            return
        if not T._group_matches(intent, True) or not T._arrived(intent):
            return
        provider = hooks.get_provider("shared_activity_request")
        if not provider:
            T._save(intent, {**state, "phase": "blocked", "reason": "The shared activity package is unavailable."})
            return
        owner, target = intent["owner"], state["invitee"]
        action, request_id = intent["action"]["after_arrival"], activity["request_id"]
    result = provider(owner, target, action, request_id)
    with keyed_lock("intent_execution", intent_id):
        current = I.get_intent(intent_id)
        if not current or current["status"] != "active":
            cancel = hooks.get_provider("shared_activity_cancel")
            if cancel:
                cancel(owner, target, action, request_id,
                       interaction_id=result.get("interaction_id", ""))
            return
        if (T._state(current).get("activity") or {}).get("interaction_id"):
            # A start hook persisted ownership while the provider was outside
            # this lock. Its request result is stale; arrive() still observes
            # authoritative status and exposes missing submitted ownership.
            return
        _observe(current, result)


def cancel(intent):
    T = _runtime()
    activity = T._state(intent).get("activity") or {}
    provider = hooks.get_provider("shared_activity_cancel")
    if provider and activity.get("request_id"):
        provider(intent["owner"], T._state(intent)["invitee"], intent["action"]["after_arrival"],
                 activity["request_id"], interaction_id=activity.get("interaction_id", ""))


def started(invite_id, interaction, inviter="", invitee=""):
    if not invite_id.startswith("iinv_intent_"):
        return
    intent_id = invite_id[len("iinv_intent_"):]
    T = _runtime()
    with keyed_lock("intent_execution", intent_id):
        intent = I.get_intent(intent_id)
        provider = hooks.get_provider("shared_activity_cancel")
        if not intent:
            if provider and inviter and invitee:
                provider(inviter, invitee, {"type": "pair", "pose_key": interaction["pose_key"]},
                         invite_id, interaction_id=interaction["id"])
            return
        if not T.intent_action_managed(intent):
            return
        state = T._state(intent)
        activity = state.get("activity") or {}
        if activity.get("request_id") != invite_id:
            return
        if intent["status"] != "active":
            if provider:
                provider(intent["owner"], state["invitee"], intent["action"]["after_arrival"], invite_id,
                         interaction_id=interaction["id"])
            return
        _observe(intent, {"status": "running", "interaction_id": interaction["id"]})


def ended(character, partner, interaction_id, reason="ended", invite_id=""):
    T = _runtime()
    if not interaction_id:
        return
    for candidate in I.list_intents(status="active", owner=""):
        if not T.intent_action_managed(candidate):
            continue
        state = T._state(candidate)
        activity = state.get("activity") or {}
        recorded_id = activity.get("interaction_id")
        if recorded_id != interaction_id and (
                recorded_id or not invite_id or activity.get("request_id") != invite_id):
            continue
        if {character, partner} != {candidate["owner"], state["invitee"]}:
            continue
        with keyed_lock("intent_execution", candidate["id"]):
            intent = I.get_intent(candidate["id"])
            if not intent or intent["status"] != "active" or not T.intent_action_managed(intent):
                continue
            state = T._state(intent)
            activity = state.get("activity") or {}
            recorded_id = activity.get("interaction_id")
            if recorded_id != interaction_id and (
                    recorded_id or not invite_id or activity.get("request_id") != invite_id):
                continue
            if {character, partner} != {intent["owner"], state["invitee"]}:
                continue
            if reason not in {"ended", "avatar", "pose"} or not T._arrived(intent):
                T._terminate(intent, f"The agreed activity was interrupted ({reason}).")
                continue
            intent = T._save(intent, {**state, "activity": {**activity,
                                                          "interaction_id": interaction_id,
                                                          "ended": True}})
            arrive(intent)


def failed(invite_id, reason="", **_kwargs):
    """Retain the real cause of every failed accepted pair invitation."""
    if not invite_id.startswith("iinv_intent_"):
        return
    intent_id = invite_id[len("iinv_intent_"):]
    T = _runtime()
    with keyed_lock("intent_execution", intent_id):
        intent = I.get_intent(intent_id)
        if not intent or intent["status"] != "active" or not T.intent_action_managed(intent):
            return
        activity = T._state(intent).get("activity") or {}
        if activity.get("request_id") != invite_id or activity.get("interaction_id"):
            return
        T._terminate(intent, "The agreed activity could not start: " +
                     (reason or "The temporary NPC could not complete its answer."))


def invited(invite_id="", **kwargs):
    if not invite_id.startswith("iinv_intent_"):
        return
    intent_id = invite_id[len("iinv_intent_"):]
    T = _runtime()
    with keyed_lock("intent_execution", intent_id):
        intent = I.get_intent(intent_id)
        if not intent or intent["status"] != "active":
            return
        state = T._state(intent)
        activity = state.get("activity") or {}
        if activity.get("request_id") == invite_id:
            T._save(intent, {**state, "activity": {**activity, "submitted": True}})


