#!/usr/bin/env python3
"""Destination-bound pair activities use real intents, consent and interaction state.

Usage: ./.venv/bin/python scripts/smoke_intent_undertaking.py

Expected from the contract, not a snapshot: arrival alone cannot complete an
undertaking. Consent leaves both actors in the destination with one real pair
interaction; ending that exact interaction completes the intent. Reconciliation
must not start it twice. Cancellation must stop only the owned interaction.
All storage/catalog/clip paths come from the disposable review fixture. Clip
metadata is sufficient for backend state; this does not claim visual playback.
"""
import sys
import os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import smoke_trip_review_edges as F
os.environ["STORAGE_DIR"] = str(F.ROOT / "world")
from app.core import interaction_engine as IE
from app.core import hooks


def undertaking(temporary=True):
    a, b = F.character(), F.character("npc-temporary" if temporary else "human-roleplay")
    intent = F._create_route_sync({
        "owner": a, "title": "Go downstairs and embrace", "source": "human",
        "participants": {a: {"role": "leader"}, b: {"role": "follower"}},
        "action": {"type": "travel_together", "scope": "pair",
                   "destination": {"location_id": F.HOME, "room_id": "cellar"},
                   "after_arrival": {"type": "pair", "pose_key": "embracing"}}})
    assert intent["action"].get("after_arrival") == {"type": "pair", "pose_key": "embracing"}, \
        "structured followup was silently discarded"
    projection = F.T.invite_projection({"intent_id": intent["id"]})
    assert projection.get("after_arrival_label") == "embracing", "consent hides the followup"
    assert IE.get_interaction(a) is None and IE.get_interaction(b) is None
    assert all(F.C.get_character_current_room(n) == "taproom" for n in (a, b))
    return a, b, intent


def accept_activity(intent):
    """Legacy temporary Together still starts immediately; normal NPCs answer."""
    request_id = "iinv_intent_" + intent["id"]
    row = IE.get_invite(request_id)
    if F.C.is_temporary_npc(row["invitee"]):
        assert row["status"] == "accepted"
        interaction = IE.get_interaction(row["inviter"])
        assert interaction and interaction["invite_id"] == request_id
    else:
        assert row["status"] == "pending"
        assert IE.resolve_invite(request_id, True)["status"] == "started"


def complete_after_real_end():
    a, b, intent = undertaking()
    assert F.P.resolve_pending_invite(F.invite_id(intent), True)["status"] == "accepted"
    assert IE.get_interaction(a)["partner"] == b, "legacy temporary Together did not start"
    accept_activity(intent)
    row = F.I.get_intent(intent["id"])
    assert row["status"] == "active", "arrival prematurely completed the undertaking"
    assert all(F.C.get_character_current_room(n) == "cellar" for n in (a, b))
    inter = IE.get_interaction(a)
    assert inter and inter["partner"] == b and inter["pose_key"] == "embracing"
    for _ in range(3):
        F.T.reconcile(intent["id"], request=False)
    assert IE.get_interaction(a)["id"] == inter["id"], "reconciliation restarted the pair"
    assert F.I.get_intent(intent["id"])["status"] == "active"
    assert IE.end_interaction(b, reason="ended")
    row = F.I.get_intent(intent["id"])
    assert row["status"] == "done" and row["meta"]["travel"]["phase"] == "completed"
    F.T.reconcile(intent["id"])
    assert IE.get_interaction(a) is None, "completed undertaking restarted"


def cancellation_stops_owned_pair():
    a, b, intent = undertaking()
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    accept_activity(intent)
    assert IE.get_interaction(a)
    assert F.I.cancel_intent(intent["id"])
    assert IE.get_interaction(a) is None and IE.get_interaction(b) is None
    assert F.I.get_intent(intent["id"])["status"] == "cancelled"


def declined_trip_starts_nothing():
    a, b, intent = undertaking()
    assert F.P.resolve_pending_invite(F.invite_id(intent), False)["status"] == "declined"
    assert F.I.get_intent(intent["id"])["status"] == "cancelled"
    assert all(F.C.get_character_current_room(n) == "taproom" for n in (a, b))
    assert IE.get_interaction(a) is None and IE.get_interaction(b) is None


def decline_after_arrival():
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    assert F.I.get_intent(intent["id"])["status"] == "active"
    row = IE.get_invite("iinv_intent_" + intent["id"])
    assert row and row["status"] == "pending", "arrival bypassed renewed activity consent"
    assert IE.get_interaction(a) is None
    assert IE.resolve_invite(row["invite_id"], False)["status"] == "declined"
    F.T.reconcile(intent["id"])
    assert F.I.get_intent(intent["id"])["status"] == "cancelled"
    assert all(F.C.get_character_current_room(n) == "cellar" for n in (a, b))
    assert IE.get_interaction(a) is None


def submitted_receipt_cannot_replay():
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    request_id = "iinv_intent_" + intent["id"]
    assert IE.get_invite(request_id)["status"] == "pending"
    assert F.I.get_intent(intent["id"])["meta"]["travel"]["activity"]["submitted"]
    with F.db.transaction() as conn:
        conn.execute("DELETE FROM interaction_invites WHERE invite_id=?", (request_id,))
    F.T.reconcile(intent["id"])
    row = F.I.get_intent(intent["id"])
    assert row["status"] == "active" and row["meta"]["travel"]["phase"] == "blocked"
    assert row["meta"]["travel"]["reason"]
    assert IE.get_invite(request_id) is None and IE.get_interaction(a) is None


def interruption_is_not_success():
    for reason in ("sleep", "pose", "position"):
        a, b, intent = undertaking()
        F.P.resolve_pending_invite(F.invite_id(intent), True)
        accept_activity(intent)
        assert IE.end_interaction(a, reason=reason)
        assert F.I.get_intent(intent["id"])["status"] == "cancelled"


def invalid_activity_is_rejected():
    a, b = F.character(), F.character()
    for followup in ({}, {"type": "tool", "pose_key": "embracing"},
                     {"type": "pair", "pose_key": "missing"}, "embracing"):
        try:
            F._create_route_sync({"owner": a, "title": "Invalid undertaking",
                "participants": {a: {"role": "leader"}, b: {"role": "follower"}},
                "action": {"type": "travel_together", "destination": {"location_id": F.HOME},
                           "after_arrival": followup}})
        except F.HTTPException as error:
            assert error.status_code == 400
        else:
            raise AssertionError("invalid activity accepted")
    assert not F.P.find_pending_invite(a, b)
    assert not F.I.list_intents(owner=a)


def extra_party_member_is_not_silently_included():
    a, b, other = F.character(), F.character(), F.character()
    iid = F.P.create_pending_invite(a, other)
    assert F.P.resolve_pending_invite(iid, True)["status"] == "accepted"
    try:
        F._create_route_sync({"owner": a, "title": "Three cannot form one pair",
            "participants": {a: {"role": "leader"}, b: {"role": "follower"}},
            "action": {"type": "travel_together", "scope": "party",
                "destination": {"location_id": F.HOME, "room_id": "cellar"},
                "after_arrival": {"type": "pair", "pose_key": "embracing"}}})
    except F.HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("three-person paired undertaking accepted")
    assert F.P.get_party_of(other)["leader"] == a
    assert not F.P.find_pending_invite(a, b)
    assert all(F.C.get_character_current_room(n) == "taproom" for n in (a, b, other))


def pause_holds_activity_and_resume_starts_once():
    a, b, intent = undertaking()
    queue = F.get_task_queue()
    queue.pause_queue("default")
    try:
        F.P.resolve_pending_invite(F.invite_id(intent), True)
        assert F.I.get_intent(intent["id"])["status"] == "active"
        assert IE.get_interaction(a) is None
        assert IE.get_invite("iinv_intent_" + intent["id"]) is None
    finally:
        queue.resume_queue("default")
    F.T.reconcile(intent["id"], request=False)
    assert IE.get_invite("iinv_intent_" + intent["id"]) is None, "lock-held reconciliation requested external consent"
    F.T.reconcile(intent["id"])
    accept_activity(intent)
    inter = IE.get_interaction(a)
    assert inter
    F.T.reconcile(intent["id"])
    assert IE.get_interaction(a)["id"] == inter["id"]
    IE.end_interaction(a)


def pre_submission_block_can_resume():
    a, b, intent = undertaking()
    queue = F.get_task_queue()
    queue.pause_queue("default")
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    F.C.save_character_skill_config(b, "interact", {"enabled": False})
    queue.resume_queue("default")
    F.T.reconcile(intent["id"])
    row = F.I.get_intent(intent["id"])
    assert row["status"] == "active" and row["meta"]["travel"]["phase"] == "blocked"
    assert not row["meta"]["travel"]["activity"].get("submitted"), "failed preflight fabricated submission"
    F.C.save_character_skill_config(b, "interact", {"enabled": True})
    F.T.reconcile(intent["id"])
    accept_activity(intent)
    assert IE.get_interaction(a)
    IE.end_interaction(a)


def withdrawn_activity_cancels_undertaking():
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    assert IE.cancel_invite("iinv_intent_" + intent["id"])
    F.T.reconcile(intent["id"])
    assert F.I.get_intent(intent["id"])["status"] == "cancelled", "withdrawn question permanently reserved its actors"


def ordinary_repeat_keeps_owned_question():
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    request_id = "iinv_intent_" + intent["id"]
    assert IE.create_invite(a, b, "embracing") == request_id
    assert IE.resolve_invite(request_id, True)["status"] == "started"
    assert F.I.get_intent(intent["id"])["meta"]["travel"]["phase"] == "activity"
    IE.end_interaction(a)
    assert F.I.get_intent(intent["id"])["status"] == "done"


def stale_request_result_cannot_regress_start():
    a, b, intent = undertaking(temporary=False)
    queue = F.get_task_queue()
    queue.pause_queue("default")
    try:
        F.P.resolve_pending_invite(F.invite_id(intent), True)
    finally:
        queue.resume_queue("default")
    provider = hooks.get_provider("shared_activity_request")

    def answer_after_snapshot(owner, target, action, request_id):
        result = provider(owner, target, action, request_id)
        assert result["status"] == "pending"
        assert IE.resolve_invite(request_id, True)["status"] == "started"
        return result

    hooks.register_provider("shared_activity_request", answer_after_snapshot)
    try:
        F.T.reconcile(intent["id"])
    finally:
        hooks.register_provider("shared_activity_request", provider)
    row = F.I.get_intent(intent["id"])
    assert row["meta"]["travel"]["phase"] == "activity"
    assert row["meta"]["travel"]["activity"]["interaction_id"] == IE.get_interaction(a)["id"]
    IE.end_interaction(a)
    assert F.I.get_intent(intent["id"])["status"] == "done"


def end_before_start_receipt_is_not_lost():
    original = IE._emit_invite_started
    for reason, expected in (("ended", "done"), ("sleep", "cancelled"), ("pose", "cancelled")):
        a, b, intent = undertaking(temporary=False)
        F.P.resolve_pending_invite(F.invite_id(intent), True)

        def end_before_hook(invitation, interaction):
            assert IE.end_interaction(invitation["inviter"], reason=reason)
            original(invitation, interaction)

        with patch.object(IE, "_emit_invite_started", end_before_hook):
            assert IE.resolve_invite("iinv_intent_" + intent["id"], True)["status"] == "started"
        row = F.I.get_intent(intent["id"])
        assert row["status"] == expected, "real end was lost while start receipt was delayed"
        assert IE.get_interaction(a) is None and IE.get_interaction(b) is None
        F.T.reconcile(intent["id"])
        assert F.I.get_intent(intent["id"])["status"] == expected


def answer_claim_beats_withdrawal():
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    request_id = "iinv_intent_" + intent["id"]
    original = IE.get_invite
    answered = False

    def answer_after_read(invite_id):
        nonlocal answered
        snapshot = original(invite_id)
        if invite_id == request_id and not answered:
            answered = True
            assert IE.resolve_invite(invite_id, True)["status"] == "started"
        return snapshot

    with patch.object(IE, "get_invite", answer_after_read):
        assert not IE.cancel_invite(request_id), "withdrawal reported success after answer claimed the row"
    assert original(request_id)["status"] == "accepted"
    assert IE.get_interaction(a)["partner"] == b
    IE.end_interaction(a)
    assert F.I.get_intent(intent["id"])["status"] == "done"


def old_live_question_survives_housekeeping():
    from datetime import timedelta
    from app.core.timeutils import utc_now
    a, b, intent = undertaking()
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    accept_activity(intent)
    request_id = "iinv_intent_" + intent["id"]
    with F.db.transaction() as conn:
        conn.execute("UPDATE interaction_invites SET created_at=? WHERE invite_id=?",
                     ((utc_now() - timedelta(hours=25)).isoformat(), request_id))
    other, target = F.character(), F.character("human-roleplay")
    assert IE.create_invite(other, target, "embracing")
    assert IE.get_invite(request_id)["status"] == "accepted", "sweep lost a live owned pair"
    F.T.reconcile(intent["id"])
    assert F.I.get_intent(intent["id"])["meta"]["travel"]["phase"] == "activity"
    IE.end_interaction(a)
    assert F.I.get_intent(intent["id"])["status"] == "done"


def temporary_failure_keeps_actual_cause():
    a, b, intent = undertaking()
    # Lose actual clip capability after preflight but before the existing
    # temporary Together hook starts it. No successful engine result is faked.
    clip = F.CLIPS / "hug__b.fbx"
    contents = clip.read_bytes()
    from app.core import animation_clips
    real_create = IE.create_invite
    def lose_clip_before_question(*args, **kwargs):
        clip.unlink()
        animation_clips._clear_entries_cache()
        return real_create(*args, **kwargs)
    try:
        with patch.object(IE, "create_invite", lose_clip_before_question):
            F.P.resolve_pending_invite(F.invite_id(intent), True)
        row = F.I.get_intent(intent["id"])
        assert row["status"] == "cancelled"
        assert "no pair animation" in row["meta"]["travel"]["reason"]
        assert IE.get_interaction(a) is None and IE.get_interaction(b) is None
        F.T.reconcile(intent["id"])
        assert F.I.get_intent(intent["id"])["status"] == "cancelled"
    finally:
        clip.write_bytes(contents)
        animation_clips._clear_entries_cache()


def deleted_trip_is_not_rendered():
    a, b, intent = undertaking(temporary=False)
    original = F.T.invite_projection

    def delete_before_projection(invitation):
        assert F.I.delete_intent(invitation["intent_id"])
        return original(invitation)

    with patch.object(F.T, "invite_projection", delete_before_projection):
        assert F.T.trip_context(a, "invite") == ""
    assert F.I.get_intent(intent["id"]) is None
    assert IE.get_interaction(a) is None


def persisted_pair_provenance_recovers_missing_hook():
    for cancel_before_reconcile in (False, True):
        a, b, intent = undertaking(temporary=False)
        F.P.resolve_pending_invite(F.invite_id(intent), True)
        request_id = "iinv_intent_" + intent["id"]
        with patch.object(IE, "_emit_invite_started", lambda *_: None):
            assert IE.resolve_invite(request_id, True)["status"] == "started"
        interaction = IE.get_interaction(a)
        assert interaction["invite_id"] == request_id
        assert not F.I.get_intent(intent["id"])["meta"]["travel"]["activity"].get("interaction_id")
        if cancel_before_reconcile:
            assert F.I.cancel_intent(intent["id"])
            assert F.I.get_intent(intent["id"])["status"] == "cancelled"
            assert IE.get_interaction(a) is None and IE.get_interaction(b) is None
        else:
            F.T.reconcile(intent["id"])
            row = F.I.get_intent(intent["id"])
            assert row["meta"]["travel"]["phase"] == "activity"
            assert row["meta"]["travel"]["activity"]["interaction_id"] == interaction["id"]
            IE.end_interaction(a)
            assert F.I.get_intent(intent["id"])["status"] == "done"


def unfinished_pair_start():
    """Persist the real pair at the crash window before accepted/start hooks."""
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    request_id = "iinv_intent_" + intent["id"]
    assert IE._claim_invite(request_id)
    interaction = IE.start_interaction(a, b, "embracing", invite_id=request_id)
    assert IE.get_invite(request_id)["status"] == "answering"
    return a, b, intent, interaction


def live_provenance_before_accepted_is_running():
    a, b, intent, interaction = unfinished_pair_start()
    F.T.reconcile(intent["id"])
    row = F.I.get_intent(intent["id"])
    assert row["meta"]["travel"]["phase"] == "activity", "a real owned pair was reported as waiting"
    assert row["meta"]["travel"]["activity"]["interaction_id"] == interaction["id"]
    IE.end_interaction(a)
    assert F.I.get_intent(intent["id"])["status"] == "done"


def cancellation_before_accepted_stops_owned_pair():
    a, b, intent, interaction = unfinished_pair_start()
    assert F.I.cancel_intent(intent["id"])
    assert F.I.get_intent(intent["id"])["status"] == "cancelled"
    assert IE.get_interaction(a) is None and IE.get_interaction(b) is None, \
        "cancellation orphaned the pair before accepted was written"


def start_racing_cancellation_is_not_orphaned():
    a, b, intent = undertaking(temporary=False)
    F.P.resolve_pending_invite(F.invite_id(intent), True)
    request_id = "iinv_intent_" + intent["id"]
    original = IE.cancel_invite
    answered = False

    def start_after_ownership_snapshot(invite_id):
        nonlocal answered
        if invite_id == request_id and not answered:
            answered = True
            with patch.object(IE, "_emit_invite_started", lambda *_: None):
                assert IE.resolve_invite(invite_id, True)["status"] == "started"
        return original(invite_id)

    with patch.object(IE, "cancel_invite", start_after_ownership_snapshot):
        assert F.I.cancel_intent(intent["id"])
    assert F.I.get_intent(intent["id"])["status"] == "cancelled"
    assert IE.get_interaction(a) is None and IE.get_interaction(b) is None, \
        "a start between ownership read and withdrawal escaped cancellation"


def durable_real_end_recovers_lost_hook():
    original = hooks.emit
    for reason, expected in (("ended", "done"), ("pose", "cancelled")):
        a, b, intent = undertaking()
        F.P.resolve_pending_invite(F.invite_id(intent), True)
        accept_activity(intent)
        owned = IE.get_interaction(a)["id"]
        def stop_delivery(event, **kwargs):
            if event != "interaction.ended":
                return original(event, **kwargs)
        with patch.object(hooks, "emit", stop_delivery):
            assert IE.end_interaction(a, reason=reason, interaction_id=owned)
        assert F.C.get_character_profile(a)["last_interaction_result"]["interaction_id"] == owned
        F.T.reconcile(intent["id"])
        assert F.I.get_intent(intent["id"])["status"] == expected
        assert IE.get_interaction(a) is None


if __name__ == "__main__":
    try:
        for case in (complete_after_real_end, cancellation_stops_owned_pair, declined_trip_starts_nothing,
                     decline_after_arrival, submitted_receipt_cannot_replay,
                     interruption_is_not_success, invalid_activity_is_rejected,
                     extra_party_member_is_not_silently_included, pause_holds_activity_and_resume_starts_once,
                     pre_submission_block_can_resume, withdrawn_activity_cancels_undertaking,
                     ordinary_repeat_keeps_owned_question, stale_request_result_cannot_regress_start,
                     end_before_start_receipt_is_not_lost, answer_claim_beats_withdrawal,
                     old_live_question_survives_housekeeping, temporary_failure_keeps_actual_cause,
                     deleted_trip_is_not_rendered, persisted_pair_provenance_recovers_missing_hook,
                     live_provenance_before_accepted_is_running, cancellation_before_accepted_stops_owned_pair,
                     start_racing_cancellation_is_not_orphaned, durable_real_end_recovers_lost_hook):
            case()
            print(f"PASS: {case.__name__}")
    finally:
        F.TEMP.cleanup()
