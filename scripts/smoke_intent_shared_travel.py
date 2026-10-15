#!/usr/bin/env python3
"""Behavioral checks for consent-bound intent travel in throwaway storage.

The contract, not current output, supplies these expectations: proposal alone
never moves anyone; yes forms exactly the agreed group and starts one real
journey (or changes both rooms); no/expiry/withdrawal ends the intent. A freeze,
queue pause or sleep may record consent but cannot start movement. A follower's
entry/leave restriction blocks everyone. Pair scope cannot silently absorb an
existing follower. A claimed startup survives re-registration without a second
journey. Completion requires consent plus every member's actual destination.
Cancel/deletion/pooling cancels only the journey stamped with this trip's claim.

Usage: ./.venv/bin/python scripts/smoke_intent_shared_travel.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="intent-trip-smoke-")
ROOT = Path(TMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import config, db, hooks, prompt_templates, travel_engine
config.load(ROOT / "world" / "config.json")
db.init_schema()
from app.core.game_time import GameDuration, GameTime
from app.core.keyed_lock import keyed_lock
from app.core.timeutils import game_time, set_game_factor, set_game_time
from app.core.task_queue import get_task_queue
from app.core import party_engine as P
from app.models import character as C, intents as I, world as W
from plugins.party import trip_intents as T

prompt_templates.register_package_template_dirs([
    Path(__file__).resolve().parents[1] / "plugins/party/templates/llm"])
T.register()
set_game_factor(0)
set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
HOME = W.add_location("Smoke Inn", "A consent test inn.",
                     rooms=[{"id": "taproom", "name": "Taproom"},
                            {"id": "kitchen", "name": "Kitchen"}])["id"]
AWAY = W.add_location("Smoke Market", "A destination on the road.",
                     rooms=[{"id": "hall", "name": "Hall"}])["id"]
for lid, x, edge in [(HOME, 0, 1), (AWAY, 100, 3)]:
    loc = W.get_location_by_id(lid)
    loc.update(pos_x=x, pos_z=0, map3d={"plan_width_m": 10,
               "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
               "boundary_openings": [{"edge": edge, "at": 0.5,
                                      "width_m": 4, "type": "passage"}]})
    W.upsert_location(loc, sync_world=True)

serial = 0

def pair():
    global serial
    serial += 1
    names = (f"demo_lead_{serial}", f"demo_guest_{serial}")
    for name in names:
        assert C.save_character_profile(name, {"character_name": name,
                    "template": "npc-temporary"}, create_new=True)
        C.save_character_current_location(name, HOME)
        C.save_character_current_room(name, "taproom")
        C.set_character_pos(name, 0, 0)
        C.set_known_locations(name, [HOME, AWAY])
    return names


def propose(names, location=HOME, room="kitchen", scope="pair"):
    a, b = names
    action = {"type": "travel_together", "destination": {
        "location_id": location, "room_id": room}, "scope": scope}
    parts = {a: {"role": "leader"}, b: {"role": "follower"}}
    action = T.intent_action_validate(a, parts, action)
    intent = I.create_intent(owner=a, title="Shared trip", participants=parts,
                             action=action, target_count=0)
    assert intent, "intent persisted"
    return I.get_intent(intent["id"])


def invite(intent):
    return P.get_invite(intent["meta"]["travel"]["invite_id"])


def phase(intent):
    return I.get_intent(intent["id"])["meta"]["travel"]["phase"]


# Missing continuation after membership acceptance is caught by both room writes.
a, b = pair()
it = propose((a, b))
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "taproom"
assert invite(it)["intent_id"] == it["id"]
assert it["id"] in T.trip_context(a, "invite")
assert it["id"] in T.trip_context(b, "join")
assert not T.trip_context(a, "join")
assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "kitchen"
assert I.get_intent(it["id"])["status"] == "done"
assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
assert P.get_party_of(a)["members"] == [b]

a, b = pair()
it = propose((a, b))
assert P.resolve_pending_invite(invite(it)["invite_id"], False)["status"] == "declined"
assert I.get_intent(it["id"])["status"] == "cancelled"
assert not P.get_party_of(a) and C.get_character_current_room(b) == "taproom"
assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] != "accepted"

for gate in ["freeze", "pause", "sleep"]:
    a, b = pair()
    it = propose((a, b))
    if gate == "freeze": W.set_world_frozen(True)
    if gate == "pause": get_task_queue().pause_queue("default")
    if gate == "sleep": W.set_world_sleeping(True)
    assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
    assert C.get_character_current_room(a) == C.get_character_current_room(b) == "taproom"
    assert I.get_intent(it["id"])["status"] == "active"
    if gate == "freeze": W.set_world_frozen(False)
    if gate == "pause": get_task_queue().resume_queue("default")
    if gate == "sleep": W.set_world_sleeping(False)
    hooks.emit("world_tick")
    assert I.get_intent(it["id"])["status"] == "done"

# Explicit party scope includes known followers; pair scope leaves them intact.
a, b = pair()
_, extra = pair()
assert P.add_to_party(a, extra)
try:
    propose((a, b))
    raise AssertionError("pair must reject an existing extra companion")
except ValueError:
    pass
it = propose((a, b), scope="party")
assert set(it["meta"]["travel"]["expected_members"]) == {a, b, extra}
assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
assert all(C.get_character_current_room(n) == "kitchen" for n in [a, b, extra])

# Real accessible_when evaluation, not a stubbed movement/permission result.
a, b = pair()
loc = W.get_location_by_id(AWAY)
loc["accessible_when"] = ["NOT always"]
W.upsert_location(loc, sync_world=True)
it = propose((a, b), AWAY, "hall")
assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
assert phase(it) == "blocked" and not travel_engine.get_journey(a)
loc["accessible_when"] = []
W.upsert_location(loc, sync_world=True)
hooks.emit("world_tick")
assert travel_engine.get_journey(a) and phase(it) == "travelling"
assert I.get_intent(it["id"])["status"] == "active"
assert not I.complete_intent(it["id"])
try:
    T.intent_action_change_validate(I.get_intent(it["id"]), {"status": "done"})
    raise AssertionError("manual premature done must fail")
except ValueError:
    pass
first = travel_engine.get_journey(a)
T.register()  # registration/recovery is idempotent, no process-local claim cache
hooks.emit("world_tick")
assert travel_engine.get_journey(a) == first
assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
assert travel_engine.get_journey(a) == first
set_game_time(game_time() + GameDuration.of(hours=1))
travel_engine.advance_all_journeys()
hooks.emit("world_tick")
assert all(C.get_character_current_location(n) == AWAY for n in [a, b])
assert all(C.get_character_current_room(n) == "hall" for n in [a, b])
assert I.get_intent(it["id"])["status"] == "done"

# Claim saved but no movement yet: re-register then recover exactly once.
a, b = pair()
W.set_world_frozen(True)
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
state = dict(I.get_intent(it["id"])["meta"]["travel"])
state.update(phase="starting", claim_id="smoke_claim_before_start")
I.update_intent(it["id"], meta={"travel": state})
T.register()
W.set_world_frozen(False)
hooks.emit("world_tick")
j = travel_engine.get_journey(a)
assert j and j["journey_id"] == "smoke_claim_before_start"
hooks.emit("world_tick")
assert travel_engine.get_journey(a) == j
assert I.cancel_intent(it["id"])
assert not travel_engine.get_journey(a) and phase(it) == "cancelled"
assert P.get_party_of(a), "cancel never silently dissolves an existing party"

# A stale ticker snapshot must not revive the journey cancelled above.
from unittest.mock import patch
snapshot = [{"name": a, "journey": j, "movement_target": AWAY,
             "current_location": HOME}]
positions = {name: C.get_character_pos(name) for name in [a, b]}
set_game_time(game_time() + GameDuration.of(hours=1))
with patch.object(C, "list_active_journeys", return_value=snapshot):
    travel_engine.advance_all_journeys()
assert {name: C.get_character_pos(name) for name in [a, b]} == positions
assert all(C.get_character_current_location(name) == HOME for name in [a, b])

# Ending a pending plan cannot cancel a later, unrelated real journey.
a, b = pair()
it = propose((a, b), AWAY, "hall")
other, reason = travel_engine.start_journey(a, AWAY, target_room="hall")
assert other and not reason
assert I.cancel_intent(it["id"])
assert travel_engine.get_journey(a) == other
travel_engine.cancel_journey(a)

# Every member's entry AND room-leave rules gate an otherwise valid trip.
from app.models import rules as R
for rule_action, target_room in [("enter", "kitchen"), ("leave", "taproom")]:
    a, b = pair()
    rule_id = f"smoke_trip_{rule_action}_{serial}"
    R.add_rule({"id": rule_id, "type": "block", "action": rule_action,
                "character": b, "condition": "always", "message": "This companion cannot pass.",
                "target": {"scope": "room", "location_id": HOME,
                           "room_ids": [target_room]}})
    it = propose((a, b))
    assert P.resolve_pending_invite(invite(it)["invite_id"], True)["status"] == "accepted"
    assert phase(it) == "blocked"
    assert all(C.get_character_current_room(name) == "taproom" for name in [a, b])
    R.delete_rule(rule_id)
    hooks.emit("world_tick")
    assert I.get_intent(it["id"])["status"] == "done"

# A follower's changed access on the road must deny the leader's arrival too.
a, b = pair()
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
R.add_rule({"id": "smoke_trip_arrival", "type": "block", "action": "enter",
            "character": b, "condition": "always", "message": "The destination is closed to the companion.",
            "target": {"scope": "room", "location_id": AWAY, "room_ids": ["hall"]}})
set_game_time(game_time() + GameDuration.of(hours=1))
travel_engine.advance_all_journeys()
assert all(C.get_character_current_location(name) != AWAY for name in [a, b])
assert I.get_intent(it["id"])["status"] == "cancelled"
R.delete_rule("smoke_trip_arrival")

# Gaining a companion after consent cancels the scope, never drags the extra.
a, b = pair()
c, _ = pair()
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
assert P.add_to_party(a, c)
set_game_time(game_time() + GameDuration.of(minutes=1))
travel_engine.advance_all_journeys()
assert not travel_engine.get_journey(a)
assert I.get_intent(it["id"])["status"] == "cancelled"
assert C.get_character_current_location(c) == HOME
assert C.get_character_current_room(c) == "taproom"
assert P.get_party_of(a)["members"] == [b, c]

# An independently moved follower is never dragged back by a managed ticker.
a, b = pair()
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
C.save_character_current_room(b, "kitchen")
set_game_time(game_time() + GameDuration.of(minutes=1))
travel_engine.advance_all_journeys()
assert C.get_character_current_room(b) == "kitchen"
assert I.get_intent(it["id"])["status"] == "cancelled"

# Default-queue pause gates a new continuation, not an existing physical walk.
a, b = pair()
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
get_task_queue().pause_queue("default")
set_game_time(game_time() + GameDuration.of(hours=1))
travel_engine.advance_all_journeys()
assert I.get_intent(it["id"])["status"] == "done"
assert C.get_character_current_location(a) == C.get_character_current_location(b) == AWAY
get_task_queue().resume_queue("default")

# Sleep after departure is visible termination, never a separate trip clock.
for sleeping in ["world", "participant"]:
    a, b = pair()
    it = propose((a, b), AWAY, "hall")
    P.resolve_pending_invite(invite(it)["invite_id"], True)
    assert travel_engine.get_journey(a)
    if sleeping == "world":
        W.set_world_sleeping(True)
    else:
        C.set_is_sleeping(b, True)
    travel_engine.advance_all_journeys()
    assert not travel_engine.get_journey(a)
    assert I.get_intent(it["id"])["status"] == "cancelled"
    assert P.get_party_of(a)["members"] == [b]
    W.set_world_sleeping(False)

# Removing the owning package aborts its journey, not ordinary travel.
a, b = pair()
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
ordinary, _ = pair()
unmanaged, reason = travel_engine.start_journey(ordinary, AWAY, target_room="hall")
assert unmanaged and not reason
owned_positions = {name: C.get_character_pos(name) for name in [a, b]}
execution = hooks.get_provider("journey_execution_context")
hooks.register_provider("journey_execution_context", None)
set_game_time(game_time() + GameDuration.of(hours=1))
travel_engine.advance_all_journeys()
assert not travel_engine.get_journey(a)
assert {name: C.get_character_pos(name) for name in [a, b]} == owned_positions
assert C.get_character_current_location(ordinary) == AWAY
hooks.register_provider("journey_execution_context", execution)
hooks.emit("world_tick")
assert I.get_intent(it["id"])["status"] == "cancelled"

# A cached owned row cannot clear a replacement ordinary journey.
a, b = pair()
it = propose((a, b), AWAY, "hall")
P.resolve_pending_invite(invite(it)["invite_id"], True)
cached = {"name": a, "journey": travel_engine.get_journey(a),
          "movement_target": AWAY, "current_location": HOME}
replacement, reason = travel_engine.start_journey(a, AWAY, target_room="hall")
assert replacement and not reason and not replacement.get("execution_ref")
hooks.register_provider("journey_execution_context", None)
with patch.object(C, "list_active_journeys", return_value=[cached]):
    travel_engine.advance_all_journeys()
assert travel_engine.get_journey(a) == replacement
hooks.register_provider("journey_execution_context", execution)
I.cancel_intent(it["id"])
assert travel_engine.get_journey(a) == replacement

# An NPC's actual lifetime sweep detaches the still-waiting linked proposal.
a, b = pair()
it = propose((a, b))
with keyed_lock("character_profile", b):
    profile = C.get_character_profile(b)
    profile["expires_at"] = "Y0001-D001T00:00:00"
    assert C.save_character_profile(b, profile)
from app.core.npc_ops import sweep_expired_npcs
assert sweep_expired_npcs() >= 1
assert I.get_intent(it["id"])["status"] == "cancelled"
assert P.get_invite(invite(it)["invite_id"])["status"] != "pending"

# Administrative removal and pool detach use the existing core detach path.
from app.core.npc_pool import pool_npc

for end in ["withdraw", "pool", "delete", "pool_owner", "delete_owner",
            "disappeared", "intent_delete", "expire"]:
    a, b = pair()
    it = propose((a, b), AWAY, "hall")
    if end == "expire":
        I.update_intent(it["id"], expires_at="Y0001-D001T00:00:00")
    else:
        P.resolve_pending_invite(invite(it)["invite_id"], True)
        assert travel_engine.get_journey(a)
    if end == "withdraw": P.leave_party(b)
    if end == "pool": assert pool_npc(b)
    if end == "delete": assert C.delete_character(b)
    if end == "pool_owner": assert pool_npc(a)
    if end == "delete_owner": assert C.delete_character(a)
    if end == "disappeared":
        with db.transaction() as conn:
            # Simulate an external removal that bypassed the detach callbacks.
            conn.execute("UPDATE characters SET status='pooled' WHERE name=?", (b,))
    if end == "intent_delete": assert I.delete_intent(it["id"])
    hooks.emit("world_tick")
    assert not travel_engine.get_journey(a), end
    current = I.get_intent(it["id"])
    assert current is None or current["status"] in {"cancelled", "expired"}, end

# Expiry closes invitation, so stale consent cannot start anything later.
a, b = pair()
it = propose((a, b))
iid = invite(it)["invite_id"]
with db.transaction() as conn:
    conn.execute("UPDATE party_invites SET created_at=? WHERE invite_id=?",
                 ("2000-01-01T00:00:00+00:00", iid))
hooks.emit("world_tick")
assert I.get_intent(it["id"])["status"] == "expired"
assert P.resolve_pending_invite(iid, True)["status"] != "accepted"
print("PASS: consent, duplicate, gates, scope, timed arrival, recovery and termination")
