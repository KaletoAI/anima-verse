#!/usr/bin/env python3
"""Real state checks for each consent entry and structured NPC proposal.

No membership, intent, movement or response dispatcher is stubbed. The only
scripted boundary is the external decision model's answer. Hand-derived
expectations: explicit yes through NPC JoinParty, avatar respond and Decision
all continue the same destination; explicit no leaves both at the origin and
cancels the plan. Temporary NPCs get a direct response, not thought autonomy.
A malformed/out-of-context proposal records no invitation or movement; a valid
proposal records its actual spoken line, and never moves before consent.
Failed membership insertion must leave an invitation pending, not accepted.

Usage: ./.venv/bin/python scripts/smoke_intent_shared_travel_consent.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="intent-trip-consent-")
ROOT = Path(TMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import config, db, hooks, prompt_templates, decision
config.load(ROOT / "world" / "config.json")
db.init_schema()
from app.core import party_engine as P
from app.core.decision import Answer, Decision
from app.core import agent_loop as al
from app.core.timeutils import game_time
from app.core.users import create_user, update_user
from app.models import character as C, intents as I, world as W, account as ACC
from app.plugins.context import PluginContext
from plugins.party.skill import PartySkill
from plugins.party import trip_intents as T
from app.routes.play import _play_party_respond_sync
from fastapi import HTTPException

prompt_templates.register_package_template_dirs([
    Path(__file__).resolve().parents[1] / "plugins/party/templates/llm"])
import plugins.party.register
LOC = W.add_location("Smoke Tavern", "A consent test location.",
    rooms=[{"id": "taproom", "name": "Taproom"}, {"id": "kitchen", "name": "Kitchen"}])["id"]
serial = 0
JOIN = PartySkill({}, PluginContext("party"), "join")
INVITE = PartySkill({}, PluginContext("party"), "invite")


def pair(template="npc-temporary"):
    global serial
    serial += 1
    names = (f"demo_host_{serial}", f"demo_companion_{serial}")
    for name in names:
        assert C.save_character_profile(name, {"character_name": name,
                    "template": template, "standing_task": "help in the kitchen"}, create_new=True)
        C.save_character_current_location(name, LOC)
        C.save_character_current_room(name, "taproom")
        C.set_known_locations(name, [LOC])
    return names


def trip(a, b):
    return T.propose_trip(a, b, {"location_id": LOC, "room_id": "kitchen"})


def invitation(it):
    return P.get_invite(it["meta"]["travel"]["invite_id"])


# A temporary NPC's original question survives a process restart.
a, b = pair()
it = trip(a, b)
assert invitation(it)["status"] == "pending"

# Re-importing the package creates a new process session, not a new proposal.
import importlib
al._agent_loop = al.AgentLoop()
old_invitation_id = invitation(it)["invite_id"]
importlib.reload(T).register()
hooks.emit("world_tick")
JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": old_invitation_id}))
assert I.get_intent(it["id"])["status"] == "done"
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "kitchen"
assert P.get_party_of(b)["leader"] == a
JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": old_invitation_id}))
assert P.get_party_of(a)["members"] == [b]

a, b = pair()
it = trip(a, b)
JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": invitation(it)["invite_id"], "answer": "no"}))
assert I.get_intent(it["id"])["status"] == "cancelled"
assert invitation(it)["status"] == "declined"
assert not P.get_party_of(a)
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "taproom"
JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": invitation(it)["invite_id"]}))
assert not P.get_party_of(a), "closed linked invitation cannot fall through to an ordinary join"

# Avatar ownership is checked before the same resolver handles the answer.
a, b = pair()
uid = create_user("demo", "smoke-password", allowed_characters=[b])
update_user(uid, settings={"active_character": b})
ACC.set_active_character(b)
it = trip(a, b)
questions = P.get_pending_invites_for(b)
assert len(questions) == 1
assert questions[0]["intent_id"] == it["id"]
assert questions[0]["destination_label"] == "Smoke Tavern / Kitchen"
assert questions[0]["participants"] == [a, b]
try:
    _play_party_respond_sync({"username": "demo"}, {"invite_id": invitation(it)["invite_id"], "accept": "yes"})
    raise AssertionError("non-boolean consent must be rejected")
except HTTPException as e:
    assert e.status_code == 400
response = _play_party_respond_sync({"username": "demo"},
    {"invite_id": invitation(it)["invite_id"], "accept": True})
assert response["ok"] and I.get_intent(it["id"])["status"] == "done"
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "kitchen"
unrelated_avatar = b
assert P.leave_party(unrelated_avatar)
C.save_character_current_room(unrelated_avatar, "taproom")

# A scoped trip never uses SetLocation's ordinary active-avatar room follow.
a, b = pair()
it = trip(a, b)
P.resolve_pending_invite(invitation(it)["invite_id"], True)
assert I.get_intent(it["id"])["status"] == "done"
assert C.get_character_current_room(unrelated_avatar) == "taproom"
ACC.set_active_character("")

# Confident positive and negative external decisions use the exact same handler.
cfg = config.get_all()
cfg.setdefault("decision", {}).update(enabled=True, points={"party_join": {"mode": "on"}})
config.save(cfg)
for answer in ["accept", "decline"]:
    a, b = pair()
    external_answer = Decision({"answer": Answer(value=answer, p_yes=None,
                                     confidence=1.0, distribution={answer: 1.0})})
    with patch.object(decision, "decide", return_value=external_answer):
        it = trip(a, b)
    assert invitation(it)["status"] == ("accepted" if answer == "accept" else "declined")
    assert I.get_intent(it["id"])["status"] == ("done" if answer == "accept" else "cancelled")
    assert C.get_character_current_room(a) == C.get_character_current_room(b) == (
        "kitchen" if answer == "accept" else "taproom")

# An unrelated ordinary invitation must not automatically recruit a temporary NPC.
a, b = pair()
with patch.object(decision, "decide", return_value=Decision({"answer": Answer(
        value="accept", p_yes=None, confidence=1.0, distribution={"accept": 1.0})})):
    INVITE.execute(json.dumps({"agent_name": a, "target": b}))
assert P.get_party_of(a) is None and P.get_party_of(b) is None
assert P.find_pending_invite(a, b) is None
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "taproom"
cfg["decision"]["enabled"] = False
config.save(cfg)

# The skill's structured destination persists a trip, ordinary invites still work.
a, b = pair()
INVITE.execute(json.dumps({"agent_name": a, "target": b,
    "destination": {"location_id": LOC, "room_id": "kitchen"}, "scope": "pair"}))
inv = P.find_pending_invite(a, b)
assert inv and inv["intent_id"]
JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": inv["invite_id"]}))
assert I.get_intent(inv["intent_id"])["status"] == "done"
a, b = pair("human-roleplay")
INVITE.execute(json.dumps({"agent_name": a, "target": b}))
inv = P.find_pending_invite(a, b)
assert inv and not inv["intent_id"]
JOIN.execute(json.dumps({"agent_name": b, "leader": a}))
assert P.get_party_of(b)["leader"] == a
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "taproom"

# Structured NPC action validates presence, room snapshot and destination first.
a, b = pair()
variables = {"talk_allowed": True, "present": [{"name": b}], "location_id": LOC,
             "current_room_id": "taproom"}
action = {"type": "travel_together", "target": b, "scope": "pair",
          "destination": {"location_id": LOC, "room_id": "kitchen"},
          "line": "Will you help me in the kitchen?"}
assert T.npc_action_execute(a, action, variables, moved=True) == {}
assert T.npc_action_execute(a, {**action, "target": "not present"}, variables) == {}
assert T.npc_action_execute(a, {**action, "destination": {"location_id": "missing"}}, variables) == {}
assert not I.list_intents(owner=a)
result = T.npc_action_execute(a, action, variables)
assert result["invited"] == result["said_to"] == b
it = I.get_intent(result["intent_id"])
assert invitation(it)["status"] == "pending"
assert C.get_character_current_room(a) == C.get_character_current_room(b) == "taproom"
row = db.get_connection().execute("SELECT content FROM utterances WHERE speaker=? ORDER BY id DESC LIMIT 1", (a,)).fetchone()
assert row and row[0] == "Will you help me in the kitchen?"
assert not T.npc_action_available(a) and not T.npc_action_available(b)
assert T.npc_action_context(a, variables) == ""
P.resolve_pending_invite(invitation(it)["invite_id"], False)
assert T.npc_action_available(a) and T.npc_action_available(b)

# Atomically failed ordinary acceptance never marks the row accepted first.
a, b = pair()
c, _ = pair()
iid = P.create_pending_invite(a, b)
assert P.add_to_party(c, b)
assert P.resolve_pending_invite(iid, True)["status"] == "join_conflict"
assert P.get_invite(iid)["status"] == "pending"
assert P.get_party_of(b)["leader"] == c
assert P.resolve_pending_invite(iid, False)["status"] == "declined"
assert P.get_party_of(b)["leader"] == c

# A failed intent write must not leave a spoken invitation with no durable question.
a, b = pair()
variables = {"talk_allowed": True, "present": [{"name": b}], "location_id": LOC,
             "current_room_id": "taproom"}
action = {"type": "travel_together", "target": b, "scope": "pair",
          "destination": {"location_id": LOC, "room_id": "kitchen"},
          "line": "Will you help me in the kitchen?"}
with db.transaction() as conn:
    conn.execute("CREATE TRIGGER reject_trip BEFORE INSERT ON intents "
                 "WHEN NEW.title='Travel together' BEGIN SELECT RAISE(FAIL, 'forced persistence failure'); END")
try:
    try:
        T.npc_action_execute(a, action, variables)
    except RuntimeError:
        pass
    assert db.get_connection().execute("SELECT COUNT(*) FROM utterances WHERE speaker=?", (a,)).fetchone()[0] == 0
    assert not I.list_intents(owner=a)
finally:
    with db.transaction() as conn:
        conn.execute("DROP TRIGGER reject_trip")

# Expiry must report only durable updates, not rows rejected by the DB.
ordinary = I.create_intent(owner=a, title="Failing expiry", expires_at=game_time().canonical())
with db.transaction() as conn:
    conn.execute("CREATE TRIGGER reject_expiry BEFORE UPDATE ON intents "
                 "WHEN NEW.title='Failing expiry' AND NEW.status='expired' "
                 "BEGIN SELECT RAISE(FAIL, 'forced expiry failure'); END")
try:
    assert I.expire_overdue() == 0
    assert I.get_intent(ordinary["id"])["status"] == "active"
finally:
    with db.transaction() as conn:
        conn.execute("DROP TRIGGER reject_expiry")
print("PASS: real NPC, avatar, decision, structured proposal and atomic consent entry")
