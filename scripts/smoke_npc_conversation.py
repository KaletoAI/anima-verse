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
      because the sentence was meant for the room it just left. A ``pair`` in
      such a turn is dropped for the same reason — the partner would be in
      the room the NPC has just left, so the invitation could never bind.
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
      raising. Without a pair clip installed there are no pair keys, and then
      the prompt must not propose a pair the application would only reject.

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


# NOT "Player": that name is in `_RESERVED_NAMES` and `save_character_profile`
# silently skips it — the avatar would never exist and every place would be empty.
AVATAR = "Runa"
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
    """The SPOKEN lines of a room. The storyteller's movement traces
    (``source="movement"``, written by every placement and room change) are
    not speech and are left out — the checks count what somebody said."""
    rows = perception_store.get_room_utterances(location_id, room_id, limit=50)
    return [r for r in rows if (r.get("meta") or {}).get("source") != "movement"]


# ── (j) the chat task of a temporary NPC ────────────────────────────────────
print("(j) temporary NPCs answer through npc_talk, everyone else through chat_stream")
A = make_npc("Gudrun")
check("temporary NPC -> npc_talk", chat_llm_task(A), "npc_talk")
check("ordinary character -> chat_stream", chat_llm_task(FULL), "chat_stream")
check("unknown name -> chat_stream", chat_llm_task("nobody"), "chat_stream")

# ── (a) the tick opens a conversation ───────────────────────────────────────
print("(a) a say to a present NPC becomes one utterance and one cascade")
B = make_npc("Halvard", task="chops wood", role="woodcutter")
isolate(A)
LLM = FakeLLM('{"room": "taproom", "activity": "Sie poliert Glaeser.", "pose": "",'
              ' "say": {"to": "Halvard", "line": "Halvard, das letzte Fass muss weg."}}')
res = npc_actions.run_action_for(A, llm=LLM)
check("the turn reports whom it spoke to", res.get("said_to") if res else None, B)
rows = utterances()
check("exactly one utterance in the taproom", len(rows), 1)
check("spoken by A", rows[0]["speaker"], A)
check("addressed to B", list(rows[0].get("addressees") or []), [B])
check("marked as the tick's line", (rows[0].get("meta") or {}).get("source"),
      "npc_action")
check("the room energy was reset once", LOOP.resets, [(LOC_ID, "taproom", A)])
check("and the cascade was called once with B addressed",
      [(d["speaker"], d["addressees"], d["is_avatar"]) for d in LOOP.dispatches],
      [(A, [B], False)])
_user = LLM.calls[0]["user"]
check("the prompt lists B with role", ("Halvard" in _user, "woodcutter" in _user),
      (True, True))
check("and carries A's goals, reason and style",
      ("sell the last barrel" in _user, "has run this place" in _user,
       "short, dry sentences" in _user), (True, True, True))
check("the answer budget grew for the line", LLM.calls[0]["kwargs"].get("max_tokens"), 320)
check("the activity was still written", get_effective_activity(A), "Poliert Glaeser.")

# ── (b) an absent addressee is discarded ────────────────────────────────────
print("(b) a say to someone not in the room writes nothing")
LOOP.resets.clear(); LOOP.dispatches.clear()
isolate(A)
LLM = FakeLLM('{"room": "taproom", "activity": "Sie wischt den Tresen.",'
              ' "say": {"to": "Ingrid", "line": "Ingrid!"}}')
res = npc_actions.run_action_for(A, llm=LLM)
check("no addressee reported", res.get("said_to") if res else None, "")
check("still one utterance (the old one)", len(utterances()), 1)
check("no cascade", LOOP.dispatches, [])
check("but the activity was written", get_effective_activity(A), "Wischt den Tresen.")

# ── (c) no avatar at the place → no talk block ─────────────────────────────
print("(c) without an avatar at the place there is no conversation")
C = make_npc("Sigrun", location_id=MILL_ID, room_id="floor", task="grinds flour")
D = make_npc("Ragnar", location_id=MILL_ID, room_id="floor", task="hauls sacks")
isolate(C)
LLM = FakeLLM('{"room": "floor", "activity": "Sie mahlt.", "say": {"to": "Ragnar", "line": "He!"}}')
npc_actions.run_action_for(C, llm=LLM)
check("the prompt has no partner list", "Ragnar" in LLM.calls[0]["user"], False)
check("no utterance at the mill", len(utterances(MILL_ID, "floor")), 0)
check("no cascade", LOOP.dispatches, [])
check("talk_allowed says no", npc_actions.talk_allowed(C, {}), False)
check("but present_partners alone would list Ragnar",
      [p["name"] for p in npc_actions.present_partners(C)], [D])

# ── (d) no talking while walking out ───────────────────────────────────────
print("(d) a say in the same turn as a room change is dropped")
isolate(A)
LLM = FakeLLM('{"room": "kitchen", "activity": "Sie holt Rueben.",'
              ' "say": {"to": "Halvard", "line": "Bis gleich."}}')
res = npc_actions.run_action_for(A, llm=LLM)
check("the move happened", get_character_current_room(A), "kitchen")
check("nothing was said", (res.get("said_to") if res else None, len(utterances())),
      ("", 1))
force_set_status(A, room="taproom")

# … and a pair proposal in such a turn binds nothing either. No pair clip
# lives in the throwaway ANIMATION_CLIPS_DIR, so the catalog offers no pair
# pose of its own: "shaking hands" is a real catalog key (``solo: false``)
# and ``handshake`` is the clip it names.
_real_partner_poses = interaction_engine.partner_poses
interaction_engine.partner_poses = lambda: [("shaking hands", "handshake")]
PAIR_KEY = "shaking hands"
isolate(A)
LLM = FakeLLM('{"room": "kitchen", "activity": "Sie holt Rueben.",'
              ' "pair": {"with": "Halvard", "pose": "%s"}}' % PAIR_KEY)
res = npc_actions.run_action_for(A, llm=LLM)
# Back into the taproom BEFORE the count: an open invitation of an inviter
# who stands elsewhere is filtered out at read time, and that filter would
# hide the very row this asks about.
force_set_status(A, room="taproom")
check("nobody was invited while walking out",
      ((res.get("invited") if res else None),
       interaction_engine.pending_invites_for(B)), ("", []))
interaction_engine.partner_poses = _real_partner_poses

# ── (f) the mode switch ────────────────────────────────────────────────────
print("(f) mode off / scene indoors: no talk; scene outdoors with a home: talk")
set_npc_config(conversation_mode="off")
check("off -> not allowed", npc_actions.talk_allowed(A, {}), False)
set_npc_config(conversation_mode="scene")
check("scene indoors -> not allowed", npc_actions.talk_allowed(A, {}), False)
check("scene with a home area -> allowed (avatar within spawn radius)",
      npc_actions.talk_allowed(A, {"npc_home": {"kind": "circle"}}), True)
set_npc_config(conversation_mode="turns")
check("turns -> allowed", npc_actions.talk_allowed(A, {}), True)
isolate(A)
set_npc_config(conversation_mode="off")
LLM = FakeLLM('{"room": "taproom", "activity": "Sie poliert.", "say": {"to": "Halvard", "line": "Na?"}}')
res = npc_actions.run_action_for(A, llm=LLM)
check("off: the say is ignored", (res.get("said_to") if res else None, len(utterances())), ("", 1))
set_npc_config(conversation_mode="turns")

# ── (f2) outdoors the avatar has to be within the spawn radius ─────────────
print("(f2) outdoors: avatar within npc.spawn_radius_m of the NPC's point")
from app.models.character import set_character_pos  # noqa: E402
E = make_npc("Eirik", location_id="", room_id="", task="watches the road")
set_character_pos(E, 1000.0, 1000.0)          # far from every location
set_character_pos(AVATAR, 1100.0, 1000.0)     # 100 m away, radius default 150
check("100 m away -> at the place", npc_actions.avatar_at_place(E), True)
set_character_pos(AVATAR, 1200.0, 1000.0)     # 200 m away
check("200 m away -> not at the place", npc_actions.avatar_at_place(E), False)
save_character_current_location(AVATAR, LOC_ID)
force_set_status(AVATAR, room="kitchen")
check("avatar back at the Roadhouse", npc_actions.avatar_at_place(A), True)

# ── (k1) the action template renders for every variable set ───────────────
print("(k1) npc_action renders with and without the talk block")
for label, npc in (("talk", A), ("no talk", C)):
    v = npc_actions.prompt_vars(npc)
    s, u = render_task("npc_action", **v)
    check(f"{label}: system and user render", (bool(s.strip()), bool(u.strip())), (True, True))
v = npc_actions.prompt_vars(A)
s, u = render_task("npc_action", **v)
check("talk: the system part names say and pair", ('"say"' in s, '"pair"' in s), (True, True))
check("talk: the user part lists the partner", "Halvard" in u, True)
check("talk without pair keys: no pair is proposed",
      ("two-person pose" in s, "Pair pose keys" in u), (False, False))
v = npc_actions.prompt_vars(C)
s, _u = render_task("npc_action", **v)
check("no talk: the system part does not offer say", '"say"' in s, False)

# ── (e) a pair proposal: invitation created, the hook answers yes ──────────
print("(e) pair: the invite is created and a temporary NPC accepts at once")
import plugins.interact.register  # noqa: E402,F401 — registers the hook

interaction_engine.partner_poses = lambda: [("shaking hands", "handshake")]
STARTED = []
_real_start = interaction_engine.start_interaction
interaction_engine.start_interaction = lambda a, b, pose: (STARTED.append((a, b, pose)) or
                                                           {"id": "fake", "kind": "handshake"})
PAIR_KEY = npc_actions._pair_pose_keys()[0] if npc_actions._pair_pose_keys() else ""
check("the catalog offers at least one pair key", bool(PAIR_KEY), True)
v = npc_actions.prompt_vars(A)
s, u = render_task("npc_action", **v)
check("with a pair key the prompt proposes a pair",
      ("two-person pose" in s, PAIR_KEY in u), (True, True))
isolate(A)
LLM = FakeLLM('{"room": "taproom", "activity": "Sie tritt vor.",'
              ' "pair": {"with": "Halvard", "pose": "%s"}}' % PAIR_KEY)
res = npc_actions.run_action_for(A, llm=LLM)
check("the turn reports the invitation", res.get("invited") if res else None, B)
check("the interaction was started for the pair", STARTED, [(A, B, PAIR_KEY)])
check("no bump was needed", LOOP.bumps, [])
check("no open invitation is left", interaction_engine.pending_invites_for(B), [])

# an ordinary character invitee keeps the bump path
LOOP.bumps.clear(); STARTED.clear()
save_character_current_location(FULL, LOC_ID)
force_set_status(FULL, room="taproom")
interaction_engine.create_invite(A, FULL, PAIR_KEY)
check("an ordinary character is bumped, not auto-accepted",
      ([b[0] for b in LOOP.bumps], STARTED), ([FULL], []))
interaction_engine.clear_invites_for(FULL)
interaction_engine.start_interaction = _real_start
interaction_engine.partner_poses = _real_partner_poses

# ── result ──────────────────────────────────────────────────────────────────
print()
print(f"{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print("  FAIL", f)
    sys.exit(1)
print("OK")
