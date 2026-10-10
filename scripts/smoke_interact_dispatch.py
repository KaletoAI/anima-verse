#!/usr/bin/env python3
"""Pair invitations are direct answers, not autonomous thought turns.

Usage: ./.venv/bin/python scripts/smoke_interact_dispatch.py

Hand-derived expectations: Ann and Bob stand 2 m apart outdoors. The
'embracing' catalog entry names a complete hug pair with a 2-second sidecar.
A scripted LLM answers the invitation through the REAL InteractWith verb:
yes binds both profiles to one interaction; no closes the row without a pair.
Both answers must work during an active conversation and with world freeze
on. Freeze must retain ordinary room replies and autonomous thought bumps;
queue pause and world sleep must retain even requested invitation answers.

The external LLM, provider availability and autonomous scheduling inputs
are controlled. The hook, respond dispatcher/worker, tool, invitation
database, geometry and profiles run for real. Storage, instance, catalog
and clips are disposable.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TMP = tempfile.TemporaryDirectory(prefix="interact-dispatch-")
ROOT = Path(_TMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import db
db.init_schema()
from app.core import agent_loop as al, interaction_engine as ie, pose_catalog
from app.core import chat_engine, decision
from app.core.llm_lanes import get_lane_manager
from app.models import character as chars, world
from app.plugins.context import PluginContext
from plugins.interact.skill import InteractSkill
import plugins.interact.register  # registers the real invitation hook

CLIPS = ROOT / "clips"
CLIPS.mkdir()
for role in ("a", "b"):
    (CLIPS / f"hug__{role}.fbx").write_bytes(b"clip fixture")
(CLIPS / "hug.json").write_text(json.dumps({
    "kind": "hug", "pair": True, "fps": 30, "frames": 60, "duration_s": 2,
    "geometry": {"anchor_frame": 30, "root_distance_m": 0.6,
                 "roles": {"a": {"anchor_xz_m": [-0.3, 0]},
                           "b": {"anchor_xz_m": [0.3, 0]}}}}))
CATALOG = ROOT / "pose_catalog.json"
CATALOG.write_text(json.dumps({
    "groups": {"stand": {"label": "Standing", "default": "standing",
                         "needs_place": False}},
    "entries": {
        "standing": {"prompt": "standing", "group": "stand", "_default": True},
        "embracing": {"prompt": "two people hugging", "group": "stand",
                      "animation": "hug", "solo": False, "places": 2}}}))
original_catalog_path = pose_catalog.catalog_path
pose_catalog.catalog_path = lambda axis: CATALOG if axis == "pose" else original_catalog_path(axis)
pose_catalog.reload_catalogs()
for name, x in (("Ann", 10), ("Bob", 12), ("Cid", 14)):
    assert chars.save_character_profile(name, {"language": "en"}, create_new=True)
    chars.set_character_pos(name, x, 20)

SKILL = InteractSkill({}, PluginContext("interact"))
al._BOOT_GRACE_SECONDS = 0
al._IDLE_SLEEP_SECONDS = 0.01
al._chat_llm_available = lambda: True
al._thought_llm_available = lambda: True
# An active player conversation used to divert/skip invitation thoughts.
al._minutes_since_last_chat_with_avatar = lambda name: 0
al._is_agent_eligible = lambda name: name in {"Ann", "Bob", "Cid"}
decision.is_active = lambda point: False
ACCEPT = True


def scripted_reply(owner, responder, speaker, content, *args, **kwargs):
    # The package must give the answer turn its invitation context.
    if not kwargs.get("hint"):
        return ""
    return SKILL.execute(json.dumps({
        "agent_name": responder, "partner": speaker, "action": "embracing",
        "answer": "yes" if ACCEPT else "no"}))


chat_engine.run_chat_turn = scripted_reply


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.01)


async def scenario(frozen, accepted, blocked=""):
    global ACCEPT
    ACCEPT = accepted
    world.set_world_setting("world_frozen", "1" if frozen else "0")
    world.set_world_setting("world_sleeping", "1" if blocked == "sleep" else "0")
    from app.core.task_queue import get_task_queue
    queue = get_task_queue()
    queue._is_paused = lambda name: blocked == "queue"
    loop = al.AgentLoop()
    al._agent_loop = loop
    get_lane_manager().reset()
    get_lane_manager().reconfigure("?/?", 2)
    invite = ie.create_invite("Ann", "Bob", "embracing")
    assert invite
    if frozen:
        # A later ordinary addressed line must not strand the invitation
        # behind the freeze gate by replacing its explicit request.
        loop.bump_respond("Bob", "Cid", "ordinary addressed line")
    loop.bump("Ann", hint="autonomous trigger")
    loop.bump_respond("Cid", "Ann", "ordinary room reply", obligatory=False)
    dispatcher = asyncio.create_task(loop._respond_dispatcher())
    try:
        if blocked:
            # Several real dispatch ticks; admission, not LLM completion, is blocked.
            await asyncio.sleep(0.05)
            assert ie.get_invite(invite)["status"] == "pending"
            assert not ie.get_interaction("Bob")
            print(f"OK: {blocked} retains invitation")
            ie.cancel_invite(invite)
        else:
            try:
                await until(lambda: ie.get_invite(invite)["status"] in ("accepted", "declined"))
                await until(lambda: "Bob" not in loop._respond_active)
            except TimeoutError:
                raise AssertionError(f"invitation never answered: frozen={frozen}, accept={accepted}") from None
            if accepted:
                a, b = ie.get_interaction("Ann"), ie.get_interaction("Bob")
                assert a and b and a["id"] == b["id"]
                assert a["partner"] == "Bob" and b["partner"] == "Ann"
                assert ie.get_invite(invite)["status"] == "accepted"
                assert {a["role"], b["role"]} == {"a", "b"}
            else:
                assert ie.get_invite(invite)["status"] == "declined"
                assert ie.get_interaction("Ann") is None
                assert ie.get_interaction("Bob") is None
            if frozen:
                assert "Cid" in loop._respond_queue
                assert loop._bump_queue == ["Ann"]
            print(f"OK: frozen={frozen}, accept={accepted}, pair state correct")
    finally:
        loop._stop.set()
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)
        await asyncio.gather(*loop._respond_active.values(), return_exceptions=True)
        ie.end_interaction("Ann")
        chars.set_character_pos("Ann", 10, 20)
        chars.set_character_pos("Bob", 12, 20)


async def main():
    for frozen, accepted in ((False, True), (True, True), (True, False)):
        await scenario(frozen, accepted)
    await scenario(True, True, "queue")
    await scenario(True, True, "sleep")


try:
    asyncio.run(main())
finally:
    _TMP.cleanup()
