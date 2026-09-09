#!/usr/bin/env python3
"""Smoke run for temporary-NPC conversations (spec-npc-conversation.md § 7).

Throwaway storage, throwaway world DB, no server, no LLM: every model turn is
a fake that hands back a canned string. What is measured is the VALIDATION and
the APPLICATION — utterances written, the cascade called, invitations answered.

Stubs: ``embedding.embed`` -> None (pose catalog resolves by alias equality);
``agent_loop.get_agent_loop`` -> a recorder (no loop thread, no real cascade);
``interaction_engine.start_interaction`` -> a recorder in (e) and (i).

Hand-derived expectations, case by case:
  (a) Mode ``turns``, the avatar is at the location, NPC B stands in the same
      room, and A answers with a ``say`` addressed to B. That must write
      exactly ONE utterance, with ``speaker=A``, ``addressees=[B]`` and
      ``source=npc_action``. ``reset_room_energy`` is called once and
      ``dispatch_room_reactions`` once, with ``addressees=[B]`` and
      ``is_avatar=False``. The prompt carries B with its role plus A's goals,
      arrival reason and dialogue style.
  (b) A ``say`` addressed to a name that does not stand in the room. Nothing
      is spoken and nothing is dispatched — an addressee who is not there
      cannot hear. The room and the activity of the same answer are still
      written, because a bad addressee never costs the rest of the turn.
  (c) No avatar at the location. ``talk_allowed`` is False and ``present`` is
      empty, so the room block never offers anybody to talk to. A ``say`` that
      the model produces anyway is ignored — no utterance is written.
  (d) A ``say`` and a room change in the SAME answer. The room change wins:
      the NPC stands in the new room afterwards and no utterance is written,
      because the sentence was meant for the room it just left.
  (e) Mode ``turns`` with a valid ``pair`` key. ``create_invite`` writes an
      invitation, and the hook ``_on_invited`` makes a temporary NPC accept
      right away, so ``resolve_invite`` is called with ``accept=True`` (the
      engine start is monkeypatched and returns ``started``). A full character
      as the invitee keeps today's ``bump`` path — that is the regression.
  (f) ``mode == "off"`` produces no conversation block at all and a ``say`` is
      ignored. ``mode == "scene"`` behaves the same way inside a house. Out in
      the open with an ``npc_home``, ``talk_allowed`` is True again.
  (g) Mode ``scene``: a room with A and B, the avatar at the location, and an
      answer of three lines, one of them from a stranger "C". Only the two
      known speakers are written, in answer order with monotonic timestamps,
      A's activity is written too, and exactly ONE dispatch goes out with
      ``exclude={A, B}``. A second run inside the cooldown calls no LLM.
  (h) Mode ``scene`` with only a single NPC in the room makes no call — a
      scene needs two voices. A room without the avatar at the location makes
      no call either, because nobody is there to watch it.
  (i) Mode ``scene`` with a valid ``pair`` key calls
      ``start_interaction(A, B, key)`` (monkeypatched). The scene binds the
      pair directly instead of going through an invitation.
  (j) ``build_chat_context`` resolves the chat model through
      ``chat_llm_task``: a temporary NPC answers through ``npc_talk``, a full
      character through ``chat_stream``. An unknown name is treated as an
      ordinary character — the routing fails open, an unreadable sheet must
      never break a chat reply.
  (k) Both templates render through ``render_task`` (StrictUndefined) for the
      variable sets ``prompt_vars`` produces — a house with and without a
      conversation, a home area — and for ``npc_scenes.prompt_vars``, without
      raising.

Usage:  ./.venv/bin/python scripts/smoke_npc_conversation.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcconv-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcconv-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import agent_loop, embedding, interaction_engine, npc_actions  # noqa: E402
from app.core.chat_engine import chat_llm_task  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.prompt_templates import render_task  # noqa: E402
from app.core.timeutils import game_time  # noqa: E402
from app.core.users import create_user, update_user  # noqa: E402
from app.models import perception_store, world  # noqa: E402
from app.models.character import (force_set_status,  # noqa: E402
                                  get_character_current_room,
                                  get_effective_activity,
                                  list_temporary_npcs,
                                  save_character_profile,
                                  save_character_current_location)

embedding.embed = lambda text: None

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
LOC = world.add_location(
    "Roadhouse", "A stone house at the fork.",
    rooms=[{"id": "taproom", "name": "Taproom", "description": "Benches.",
            "activity_hint": "serving guests at the long table"},
           {"id": "kitchen", "name": "Kitchen", "description": "Soot.",
            "activity_hint": "cooking and washing up"}])
LOC_ID = LOC["id"]
MILL = world.add_location("Mill", "A watermill downstream.",
                          rooms=[{"id": "floor", "name": "Grinding floor",
                                  "description": "Dust."}])
MILL_ID = MILL["id"]


def set_npc_config(**values) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


set_npc_config(require_assets=False, action_tick_enabled=True,
               action_interval_game_minutes=30, action_batch=5, max_alive=50,
               conversation_mode="turns", scene_interval_game_minutes=45,
               scene_batch=1, scene_max_npcs=3)


def make_npc(name: str, *, location_id: str = LOC_ID, room_id: str = "taproom",
             task: str = "tends the bar", role: str = "", extra=None) -> str:
    data = {"character_name": name,
            "character_appearance": "a weathered innkeeper",
            "outfit_description": "a grey linen apron",
            "standing_task": task, "dialogue_style": "short, dry sentences",
            "arrival_reason": "has run this place for years",
            "npc_goals": "sell the last barrel\nkeep the taproom quiet"}
    data.update(extra or {})
    apply_npc(data, location_id, room_id, template="npc-temporary",
              slot_role=role, created_by="smoke_npc_conversation")
    return name


AVATAR = "Player"
save_character_profile(AVATAR, {"character_name": AVATAR,
                                "template": "human-roleplay"}, create_new=True)
_uid = create_user("demo", "smoke-password", allowed_characters=[AVATAR])
update_user(_uid, settings={"active_character": AVATAR})
save_character_current_location(AVATAR, LOC_ID)
force_set_status(AVATAR, room="kitchen")   # same place, another room

FULL = "Ingrid"     # an ordinary character: never a partner, keeps the bump path
save_character_profile(FULL, {"character_name": FULL,
                              "template": "human-roleplay"}, create_new=True)
save_character_location = save_character_current_location


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, task, system_prompt, user_prompt, **kwargs):
        self.calls.append({"task": task, "system": system_prompt,
                           "user": user_prompt, "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self.answers) - 1)
        return FakeResponse(self.answers[idx])


class FakeLoop:
    """Records what the tick asks of the agent loop instead of running it."""

    def __init__(self):
        self.resets = []
        self.dispatches = []
        self.bumps = []

    def reset_room_energy(self, location_id, room_id, who=""):
        self.resets.append((location_id, room_id, who))

    def dispatch_room_reactions(self, **kwargs):
        self.dispatches.append(kwargs)
        return {"obligatory": list(kwargs.get("addressees") or []), "chime": []}

    def bump(self, name, **kwargs):
        self.bumps.append((name, kwargs))
        return True


LOOP = FakeLoop()
agent_loop.get_agent_loop = lambda: LOOP


def isolate(*keep: str) -> None:
    now = game_time()
    for name in list_temporary_npcs():
        if name not in keep:
            npc_actions._last_action[name] = now
    for name in keep:
        npc_actions._last_action.pop(name, None)


def utterances(location_id=LOC_ID, room_id="taproom"):
    return perception_store.get_room_utterances(location_id, room_id, limit=50)


# ── (j) the chat task of a temporary NPC ────────────────────────────────────
print("(j) temporary NPCs answer through npc_talk, everyone else through chat_stream")
A = make_npc("Gudrun")
check("temporary NPC -> npc_talk", chat_llm_task(A), "npc_talk")
check("ordinary character -> chat_stream", chat_llm_task(FULL), "chat_stream")
check("unknown name -> chat_stream", chat_llm_task("nobody"), "chat_stream")

# ── result ──────────────────────────────────────────────────────────────────
print()
print(f"{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print("  FAIL", f)
    sys.exit(1)
print("OK")
