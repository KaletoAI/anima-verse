#!/usr/bin/env python3
"""NPC action proposals resume an existing intent through real party consent.

Usage: ./.venv/bin/python scripts/smoke_npc_trip_dispatch.py

Hand-derived expectations: two temporary NPCs start in the taproom. A proposal
names the cellar but changes neither room before consent. The actual respond
worker executes JoinParty from a scripted external chat answer. Yes during
freeze joins the party without moving; thaw moves both to the cellar and marks
the existing intent done. No leaves both in the taproom and cancels the intent.
A proposal coupled with a room change is invalid and writes neither movement
nor an invitation. A pending managed plan also prevents a stale background
LLM answer from moving a participant. No ordinary thought turn is enabled.
Only external model/provider availability is controlled; DB, prompt, NPC action,
plugin hooks, respond dispatcher/worker, consent and movement run for real.
Storage, instance and animation paths are disposable.
"""
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TEMP = tempfile.TemporaryDirectory(prefix="npc-trip-dispatch-")
ROOT = Path(_TEMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig" / "reference.fbx")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
(ROOT / "instance" / "config.json").write_text(json.dumps({
    "providers": [], "embedding": {"backend": "external"}}))
from app.core import config, db
config.load(ROOT / "world" / "config.json")
db.init_schema()
settings = config.get_all()
settings.setdefault("npc", {}).update(conversation_mode="turns", action_tick_enabled=True)
settings.setdefault("image_generation", {})["enabled"] = False
# Packages load only when the world enables them explicitly (ba172904).
settings["packages"] = {"enabled": "party"}
config.save(settings, ROOT / "world" / "config.json")
from app.core import agent_loop as al, chat_engine, decision, npc_actions, party_engine as party
from app.core.dependencies import get_skill_manager
from app.core.llm_lanes import get_lane_manager
from app.core.periodic_jobs import _sub_plugin_tick
from app.core.users import create_user, update_user
from app.models import character as chars, intents, world
from app.plugins.context import PluginContext
from plugins.party.skill import PartySkill

get_skill_manager()
LOCATION = world.add_location("Demo inn", "Two real rooms.", rooms=[
    {"id": "taproom", "name": "Taproom"}, {"id": "cellar", "name": "Cellar"}])["id"]
OWNER, COMPANION, AVATAR = "Demo Host", "Demo Traveler", "Demo Avatar"
for name in (OWNER, COMPANION, AVATAR):
    assert chars.save_character_profile(name, {
        "character_name": name, "template": "human-roleplay" if name == AVATAR else "npc-temporary",
        "standing_task": "tends the inn", "npc_goals": "find a quiet place for a conversation",
        "language": "en", "current_location": LOCATION, "current_room": "taproom"}, create_new=True)
    chars.set_known_locations(name, [LOCATION])
user = create_user("demo", "smoke-password", allowed_characters=[AVATAR])
assert update_user(user, settings={"active_character": AVATAR})
JOIN = PartySkill({}, PluginContext("party"), "join")
al._BOOT_GRACE_SECONDS = 0
al._IDLE_SLEEP_SECONDS = 0.01
al._chat_llm_available = lambda: True
decision.is_active = lambda point: False
ACCEPT = True
FAIL_RESPONSES = 0
REPLY_COUNT = 0


def reply(owner, responder, speaker, content, *args, **kwargs):
    global FAIL_RESPONSES, REPLY_COUNT
    REPLY_COUNT += 1
    if FAIL_RESPONSES:
        FAIL_RESPONSES -= 1
        raise ConnectionError("scripted external provider failure")
    reference = re.search(r"invite_id=(pinv_[a-z0-9]+)", content)
    assert reference, "the actual response content must identify its proposal"
    return JOIN.execute(json.dumps({"agent_name": responder, "leader": speaker,
                                    "invite_id": reference.group(1), "answer": "yes" if ACCEPT else "no"}))


chat_engine.run_chat_turn = reply


def proposal(room="taproom"):
    return {"room": room, "activity": "Invites a companion downstairs.", "pose": "standing",
            "action": {"type": "travel_together", "target": COMPANION,
                       "destination": {"location_id": LOCATION, "room_id": "cellar"},
                       "scope": "pair", "line": "Come downstairs with me; the cellar is quieter."}}


def reset():
    party.leave_party(OWNER)
    for intention in intents.list_intents():
        intents.delete_intent(intention["id"])
    party.clear_invites_for(OWNER)
    party.clear_invites_for(COMPANION)
    world.set_world_setting("world_frozen", "0")
    for name in (OWNER, COMPANION):
        chars.save_character_current_room(name, "taproom")
    get_lane_manager().reset()
    get_lane_manager().reconfigure("?/?", 2)
    loop = al.AgentLoop()
    al._agent_loop = loop
    return loop


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


async def consent(accept):
    global ACCEPT
    ACCEPT = accept
    loop = reset()
    result = npc_actions.run_action_for(OWNER, llm=lambda *args, **kwargs: SimpleNamespace(content=json.dumps(proposal())))
    assert result and result.get("intent_id"), result
    intention = intents.get_intent(result["intent_id"])
    assert intention and intention["status"] == "active"
    assert all(chars.get_character_current_room(name) == "taproom" for name in (OWNER, COMPANION))
    pending = party.find_pending_invite(OWNER, COMPANION)
    assert pending
    world.set_world_setting("world_frozen", "1")
    dispatcher = asyncio.create_task(loop._respond_dispatcher())
    try:
        await until(lambda: party.get_invite(pending["invite_id"])["status"] != "pending")
        await until(lambda: COMPANION not in loop._respond_active)
        assert all(chars.get_character_current_room(name) == "taproom" for name in (OWNER, COMPANION))
        if accept:
            assert party.party_followers(OWNER) == [COMPANION]
            assert intents.get_intent(intention["id"])["status"] == "active"
            world.set_world_setting("world_frozen", "0")
            _sub_plugin_tick()
            assert all(chars.get_character_current_room(name) == "cellar" for name in (OWNER, COMPANION))
            assert intents.get_intent(intention["id"])["status"] == "done"
            print("OK: NPC proposal -> real consent while frozen -> both arrive after thaw -> done")
        else:
            assert party.get_party_of(OWNER) is None
            assert intents.get_intent(intention["id"])["status"] == "cancelled"
            print("OK: NPC refusal cancels the proposed intent without moving anyone")
    finally:
        loop._stop.set()
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)
        await asyncio.gather(*loop._respond_active.values(), return_exceptions=True)


async def recover_failed_response():
    global ACCEPT, FAIL_RESPONSES, REPLY_COUNT
    ACCEPT, FAIL_RESPONSES, REPLY_COUNT = True, 1, 0
    loop = reset()
    result = npc_actions.run_action_for(OWNER, llm=lambda *args, **kwargs: SimpleNamespace(content=json.dumps(proposal())))
    intention = intents.get_intent(result["intent_id"])
    pending = party.find_pending_invite(OWNER, COMPANION)
    world.set_world_setting("world_frozen", "1")
    dispatcher = asyncio.create_task(loop._respond_dispatcher())
    try:
        await until(lambda: REPLY_COUNT == 1)
        await until(lambda: COMPANION not in loop._respond_active)
        assert party.get_invite(pending["invite_id"])["status"] == "pending"
        _sub_plugin_tick()
        await until(lambda: party.get_invite(pending["invite_id"])["status"] == "accepted")
        await until(lambda: COMPANION not in loop._respond_active)
        assert all(chars.get_character_current_room(name) == "taproom" for name in (OWNER, COMPANION))
        world.set_world_setting("world_frozen", "0")
        _sub_plugin_tick()
        assert intents.get_intent(intention["id"])["status"] == "done"
        assert all(chars.get_character_current_room(name) == "cellar" for name in (OWNER, COMPANION))
        print("OK: failed external reply is consumed -> next check asks again -> recovered consent completes")
    finally:
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)
        await asyncio.gather(*loop._respond_active.values(), return_exceptions=True)


async def main():
    await consent(True)
    await consent(False)
    await recover_failed_response()
    reset()
    result = npc_actions.run_action_for(OWNER, llm=lambda *args, **kwargs: SimpleNamespace(content=json.dumps(proposal("cellar"))))
    assert result is None
    assert chars.get_character_current_room(OWNER) == "taproom"
    assert not intents.list_intents(status="active")
    assert not party.find_pending_invite(OWNER, COMPANION)
    print("OK: one NPC answer cannot move away while opening a shared-trip proposal")
    reset()

    def interrupted(*args, **kwargs):
        created = intents.create_intent(owner=COMPANION, title="Shared cellar trip", participants={
            COMPANION: {"role": "leader"}, OWNER: {"role": "follower"}}, action={
                "type": "travel_together", "destination": {"location_id": LOCATION, "room_id": "cellar"}})
        assert created
        return SimpleNamespace(content=json.dumps({"room": "cellar", "activity": "Walks downstairs.", "pose": "standing"}))

    assert npc_actions.run_action_for(OWNER, llm=interrupted) is None
    assert chars.get_character_current_room(OWNER) == "taproom"
    assert party.find_pending_invite(COMPANION, OWNER)
    print("OK: a newly pending plan invalidates an in-flight background movement answer")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        _TEMP.cleanup()
