#!/usr/bin/env python3
"""Smoke run: whoever is addressed through TalkTo owes an answer.

Throwaway storage, throwaway world DB — no server, no LLM. TalkTo only QUEUES
the answer (the respond lane of the AgentLoop); what is measured here is the
queue entry, not a reply.

THE RULE, by hand:

    TalkTo(sender → target, message) puts ``target`` into the respond lane
    with a MANDATORY answer: ``_respond_queue`` holds the name at the front,
    ``_respond_to[target]`` carries speaker = sender, content = message,
    obligatory = True and the line's volume ("normal" when none was given).

    Before 2026-10-20 TalkTo asked for a THOUGHT turn (``bump``) instead.
    ``bump`` is refused for every character without ``thoughts_enabled`` —
    and the ``npc-temporary`` template ships ``thoughts_enabled: false`` — so
    an autonomous character could talk at a temporary NPC for as long as it
    liked and the NPC never said a word (Kira → Lukas, Rosi → Hannibal Krumb
    in the observer).

Seed: one location "Bathhouse" with the room "pool".
  Kira   human-roleplay   (thoughts on)    in pool
  Lukas  npc-temporary    (thoughts off)   in pool, created through apply_npc
  Mara   human-roleplay, the active character of user "demo"  in pool

Hand-derived expectations:

[0] The precondition that made the old route dead-end: the thought gate
    ``_is_agent_eligible`` answers False for Lukas (template thoughts off),
    True for Kira. Lukas's reply runs on ``npc_talk`` (chat_engine.chat_llm_task).
[1] Kira → Lukas "Hallo Lukas." → "Spoke to Lukas…"; respond queue == ["Lukas"],
    entry {speaker "Kira", content "Hallo Lukas.", obligatory True, volume
    "normal"}; the thought queue stays EMPTY (no bump() any more).
[2] Kira → Lukas three times in one turn (what rp_first does): still ONE queue
    entry for Lukas, and it carries the LAST line — bump_respond replaces the
    entry of a name already waiting.
[3] Lukas → Kira whispered "Psst." → Kira is put IN FRONT of Lukas (a
    mandatory answer is inserted at index 0): queue == ["Kira", "Lukas"], and
    Kira's entry carries volume "whisper", so her reply mirrors it.
[4] Kira → Mara: TalkTo still succeeds ("Spoke to Mara…"), but nobody
    answers for the player — the avatar is not respond-eligible, so the queue
    is unchanged from [3].

Usage:  ./.venv/bin/python scripts/smoke_talk_to_answer.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="talkto-answer-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="talkto-answer-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import agent_loop as _agent_loop_mod  # noqa: E402
from app.core.agent_loop import AgentLoop, _is_agent_eligible  # noqa: E402
from app.core.chat_engine import chat_llm_task  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.users import create_user, update_user  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (is_temporary_npc,  # noqa: E402
                                  save_character_current_location,
                                  save_character_current_room,
                                  save_character_profile)
from app.plugins.context import PluginContext  # noqa: E402
from plugins.talk_to.skill import TalkToSkill  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the world ───────────────────────────────────────────────────────────────
LOC_ID = world.add_location(
    "Bathhouse", "Steam and tiles.",
    rooms=[{"id": "pool", "name": "Pool", "description": "Warm water."}])["id"]


def place(name: str) -> None:
    save_character_current_location(name, LOC_ID)
    save_character_current_room(name, "pool")


# A fresh NPC is held back (not listed) until its T-pose/mesh exist; the
# smoke renders nothing, so the gate is opened the way smoke_npc_actions does.
_cfg = config.get_all()
_cfg.setdefault("npc", {})["require_assets"] = False
config.save(_cfg, STORAGE / "config.json")

for _name in ("Kira", "Mara"):
    save_character_profile(_name, {"character_name": _name,
                                   "template": "human-roleplay"},
                           create_new=True)
    place(_name)
apply_npc({"character_name": "Lukas",
           "character_appearance": "a young man with short brown hair",
           "outfit_description": "a bath towel",
           "standing_task": "waits at the pool"},
          LOC_ID, "pool", template="npc-temporary",
          created_by="smoke_talk_to_answer")
place("Lukas")
_uid = create_user("demo", "smoke-password", allowed_characters=["Mara"])
update_user(_uid, settings={"active_character": "Mara"})

LOOP = AgentLoop()
_agent_loop_mod._agent_loop = LOOP  # TalkTo reaches it through get_agent_loop()
TALK = TalkToSkill({"enabled": True}, PluginContext("talk_to"))


def talk_to(sender, target, message, volume=""):
    payload = {"agent_name": sender, "name": target, "message": message}
    if volume:
        payload["volume"] = volume
    return TALK.execute(json.dumps(payload))


def entry(name):
    e = LOOP._respond_to.get(name) or {}
    return {k: e.get(k) for k in ("speaker", "content", "obligatory", "volume")}


# ── [0] the precondition ────────────────────────────────────────────────────
print("[0] Lukas is a temporary NPC without thoughts; Kira thinks")
check("Lukas is a temporary NPC", is_temporary_npc("Lukas"), True)
check("thought gate refuses Lukas", _is_agent_eligible("Lukas"), False)
check("thought gate admits Kira", _is_agent_eligible("Kira"), True)
check("Lukas answers through npc_talk", chat_llm_task("Lukas"), "npc_talk")

# ── [1] one line queues one mandatory answer ───────────────────────────────
print("[1] Kira → Lukas queues Lukas's answer in the respond lane")
res = talk_to("Kira", "Lukas", "Hallo Lukas.")
check("TalkTo reports the line as spoken", res.startswith("Spoke to Lukas"), True)
check("respond queue", list(LOOP._respond_queue), ["Lukas"])
check("respond entry", entry("Lukas"),
      {"speaker": "Kira", "content": "Hallo Lukas.", "obligatory": True,
       "volume": "normal"})
check("no thought bump", list(LOOP._bump_queue), [])

# ── [2] several lines in one turn → one answer to the last ─────────────────
print("[2] three lines in a row leave ONE entry carrying the last line")
for _line in ("Komm her.", "Na?", "Willst du das hier?"):
    talk_to("Kira", "Lukas", _line)
check("respond queue", list(LOOP._respond_queue), ["Lukas"])
check("entry content", entry("Lukas")["content"], "Willst du das hier?")

# ── [3] the other way round, whispered ─────────────────────────────────────
print("[3] Lukas whispers to Kira → Kira answers first, in a whisper")
res = talk_to("Lukas", "Kira", "Psst.", volume="whisper")
check("TalkTo reports the line as spoken", res.startswith("Spoke to Kira"), True)
check("respond queue", list(LOOP._respond_queue), ["Kira", "Lukas"])
check("Kira's entry", entry("Kira"),
      {"speaker": "Lukas", "content": "Psst.", "obligatory": True,
       "volume": "whisper"})

# ── [4] the avatar is spoken to, but nobody answers for it ─────────────────
print("[4] Kira → Mara: delivered, no answer queued for the avatar")
res = talk_to("Kira", "Mara", "Und du?")
check("TalkTo reports the line as spoken", res.startswith("Spoke to Mara"), True)
check("respond queue unchanged", list(LOOP._respond_queue), ["Kira", "Lukas"])
check("no entry for the avatar", "Mara" in LOOP._respond_to, False)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)} of {CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"all {CHECKED} checks passed")
