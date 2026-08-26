#!/usr/bin/env python3
"""Smoke run for the temporary-NPC action tick (plan-npc-leben, task 2).

Throwaway storage, throwaway world DB — no server, no real world is touched
and no LLM is called: every turn is a fake that hands back a canned string, so
what is measured here is the VALIDATION and the APPLICATION, not a model.

Two stubs beyond the LLM, both so the run stays offline:
  * ``app.core.embedding.embed`` returns None — ``set_pose_intent`` then
    resolves its catalog key by plain alias equality instead of downloading
    the built-in embedding model (same rule the pose catalog states for a
    missing backend).
  * nothing else. ``force_set_status``, ``check_access``, the room list and
    the cooldown clock all run for real.

THE RULE, by hand — the action contract of the brief's § 0 B:

    Once per check the tick takes at most ``npc.action_batch`` living
    temporary NPCs whose per-NPC GAME cooldown (``npc.action_interval_game_
    minutes``) has run out, asks ONE small JSON turn where they go and what
    they do, and applies the answer through ``force_set_status``.

Hand-derived expectations, case by case:

  (a) A VALID ANSWER MOVES AND ACTS. `{"room": "kitchen", "activity": "…"}`
      for an NPC standing in `taproom` of a place that has both rooms:
      `current_room` is `kitchen` afterwards and the activity is the
      answer's sentence (`set_pose_intent` stores the first sentence, ≤120
      chars, as the flavor — the test sentence is one short sentence and
      carries no character name, so it survives verbatim). Exactly ONE LLM
      call. The user prompt really carries the assembled room list: both
      room ids, both activity hints and the standing task are in it. The
      call carries `max_tokens=200`: the answer is two short fields, and an
      uncapped budget is what lets a chatty model write an essay per NPC per
      interval (feedback_validate_llm_guards).

  (b) A FOREIGN ROOM ID IS DISCARDED WHOLE. `"cellar"` is not a room of the
      NPC's location, so the answer is thrown away — return None, the room
      stays `taproom` AND the activity stays what it was. The activity is
      not salvaged: it was written for a room that does not exist, so it
      describes nothing.

  (c) `room` == THE CURRENT ROOM IS A VALID ANSWER. Standing still is the
      normal case: no move (`moved` False, `current_room` unchanged) but the
      activity is written. Whitespace and casing around the id are tolerated
      — `"  KITCHEN "` addresses `kitchen`; a model that shouts is not a
      model that hallucinated.

  (d) BROKEN JSON GETS EXACTLY ONE REPAIR. Prose instead of an object → a
      second call asking for valid JSON. Repaired on that second try, the
      answer applies as usual (2 calls, NPC moved). Broken twice → None, no
      third call, nothing written — but the COOLDOWN IS STAMPED ALL THE SAME.
      That is the module's cost guarantee: the stamp is written before the
      call, so a model that babbles buys one interval of quiet instead of a
      fresh pair of calls on every 60 s check.

  (e) THE COOLDOWN IS GAME TIME. One tick acts; a second tick right after it
      calls no LLM at all, because the per-NPC cooldown has not elapsed in
      GAME time. Advancing the game clock past
      `action_interval_game_minutes` makes the same NPC a candidate again and
      the next tick acts. (The world's real seconds are irrelevant — the
      clock is moved with `set_game_time`, exactly as a freeze or a jump
      would move it.)

  (f) POOLED, SLEEPING, BUSY, TRAVELLING, IN-CHAT AND PLACELESS NPCs ARE
      NEVER CANDIDATES. Pooled (`status` 'pooled') is already out of
      `list_temporary_npcs`; sleeping (`is_sleeping`), holding a running
      `interaction`, carrying a `journey`, talking to an avatar right now,
      and standing in no location at all are the five the filter adds. The
      journey one matters most: mid-walk `current_location` is whatever
      transit cell the travel ticker last wrote, so this NPC would be asked
      to pick a room of a place it is only passing through. A plain living,
      placed NPC IS a candidate, and both the released and the arrived one
      become candidates again — without those contrasts the five above prove
      nothing.

      The IN-CHAT one is the same rule the AgentLoop gates its own turns on
      (`agent_loop._minutes_since_last_chat_with_avatar` against its HOT
      window `_IN_CHAT_HOT_MIN` = 10 minutes), not a second definition:
      every temporary NPC carries `talk_to`, so without it the tick could
      send the innkeeper down to the cellar and overwrite her activity
      mid-sentence while the player is writing to her. Hand-derived: a
      `chat_messages` row between the NPC and an AVATAR stamped NOW makes it
      no candidate; the same row stamped 20 minutes back (outside the HOT
      window) leaves it a candidate; and a row whose partner is an ordinary
      character, not an avatar, never counted in the first place (TalkTo
      NPC↔NPC is not "in chat" — the agent-loop helper's own rule).

  (g) THE BLOCK RULES STILL RULE. A `block`/`enter` rule on the target room
      with condition `always` denies the move: None, nothing written. Only
      MOVES are gated — the rule is about entering.

  (h) THE PLACE MUST STILL BE THE PLACE. The room list is taken from ONE
      location before the turn; if the character is somewhere else by the
      time the answer arrives, the answer is discarded whole. Otherwise a
      room id valid in the old place is written into the new one, where it
      does not exist — an invalid `room_id` for perception and the 3D
      client. Simulated by an injected LLM that relocates the NPC while it
      "thinks": None, and no Roadhouse room ends up on an NPC now at the Mill.

  (i) THE BATCH CAPS THE COST. Three eligible NPCs, `action_batch` 2 → one
      tick makes exactly two LLM calls.

  (j) THE TICK IS SWITCHABLE. `npc.action_tick_enabled` false → no
      candidates at all, whatever else is true.

  (k) THE TEMPLATE RENDERS. `render_task("npc_action", …)` under
      StrictUndefined returns a non-empty system AND user part for the very
      variable set the module passes — a placeholder the module forgets is a
      crash in production, not a warning.

Usage:  ./.venv/bin/python scripts/smoke_npc_actions.py
"""
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcactions-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcactions-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding, llm_router, npc_actions  # noqa: E402
from app.core.game_time import GameDuration  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.npc_pool import pool_npc  # noqa: E402
from app.core.prompt_templates import render_task  # noqa: E402
from app.core.timeutils import game_time, set_game_time, utc_now  # noqa: E402
from app.core.users import create_user, update_user  # noqa: E402
from app.models import rules as rules_model, world  # noqa: E402
from app.models.character import (force_set_status,  # noqa: E402
                                  get_character_current_location,
                                  get_character_current_room,
                                  get_character_profile,
                                  get_effective_activity,
                                  list_temporary_npcs,
                                  save_character_profile,
                                  save_character_current_location,
                                  set_is_sleeping)

# Offline: no embedding model is downloaded for the pose catalog.
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

LOC2 = world.add_location("Mill", "A watermill downstream.",
                          rooms=[{"id": "floor", "name": "Grinding floor",
                                  "description": "Dust."}])
LOC2_ID = LOC2["id"]


def set_npc_config(**values) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


set_npc_config(require_assets=False, action_tick_enabled=True,
               action_interval_game_minutes=30, action_batch=2, max_alive=50)


def make_npc(name: str, *, location_id: str = LOC_ID, room_id: str = "taproom",
             task: str = "tends the bar", role: str = "") -> str:
    """Create a temporary NPC through the real apply path and place it."""
    apply_npc({"character_name": name,
               "character_appearance": "a weathered innkeeper",
               "outfit_description": "a grey linen apron",
               "standing_task": task},
              location_id, room_id, template="npc-temporary",
              slot_role=role, created_by="smoke_npc_actions")
    return name


def silence(*keep: str) -> None:
    """Stamp every living temporary NPC EXCEPT ``keep`` as having just acted —
    so a section only ever sees the NPCs it is about. The kept ones keep their
    OWN stamp, which is what makes the cooldown check in (e) mean something."""
    now = game_time()
    for name in list_temporary_npcs():
        if name not in keep:
            npc_actions._last_action[name] = now


def isolate(*keep: str) -> None:
    """``silence`` plus: the kept ones lose their stamp and are due right now."""
    silence(*keep)
    for name in keep:
        npc_actions._last_action.pop(name, None)


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """Stands in for ``llm_call``. Hands back the canned answers in order and
    repeats the last one when it runs out."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, task, system_prompt, user_prompt, **kwargs):
        self.calls.append({"task": task, "system": system_prompt,
                           "user": user_prompt, "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self.answers) - 1)
        return FakeResponse(self.answers[idx])


# ── (a) a valid answer moves and acts ───────────────────────────────────────
print("(a) a valid answer moves the NPC and sets the activity")
A = make_npc("Gudrun")
isolate(A)
LLM = FakeLLM('{"room": "kitchen", "activity": "Sie ruehrt den Eintopf um."}')
res = npc_actions.run_action_for(A, llm=LLM)
check("the answer was applied",
      {k: res.get(k) for k in ("name", "room", "activity", "moved")} if res else None,
      {"name": A, "room": "kitchen",
       "activity": "Sie ruehrt den Eintopf um.", "moved": True})
check("the NPC really stands in the kitchen", get_character_current_room(A),
      "kitchen")
check("and really does what the answer says", get_effective_activity(A),
      "Sie ruehrt den Eintopf um.")
check("exactly one LLM call", len(LLM.calls), 1)
check("on the npc_action task", LLM.calls[0]["task"], "npc_action")
_user = LLM.calls[0]["user"]
check("the prompt carries both room ids",
      ("taproom" in _user, "kitchen" in _user), (True, True))
check("and both activity hints",
      ("serving guests at the long table" in _user,
       "cooking and washing up" in _user), (True, True))
check("and the standing task", "tends the bar" in _user, True)
check("the completion budget is capped", LLM.calls[0]["kwargs"].get("max_tokens"),
      200)

# ── (b) a foreign room id is discarded whole ────────────────────────────────
print("(b) a room the location does not have is discarded whole")
force_set_status(A, room="taproom", activity="Sie wischt den Tresen.")
isolate(A)
LLM = FakeLLM('{"room": "cellar", "activity": "Sie steigt in den Keller."}')
check("nothing is returned", npc_actions.run_action_for(A, llm=LLM), None)
check("the room is unchanged", get_character_current_room(A), "taproom")
check("and the activity is not salvaged either", get_effective_activity(A),
      "Sie wischt den Tresen.")

# ── (c) the current room is a valid answer ─────────────────────────────────
print("(c) staying put is a valid answer; id casing/whitespace is tolerated")
isolate(A)
LLM = FakeLLM('{"room": "taproom", "activity": "Sie poliert die Glaeser."}')
res = npc_actions.run_action_for(A, llm=LLM)
check("applied without a move",
      {k: res.get(k) for k in ("room", "moved")} if res else None,
      {"room": "taproom", "moved": False})
check("still in the taproom", get_character_current_room(A), "taproom")
check("but doing the new thing", get_effective_activity(A),
      "Sie poliert die Glaeser.")

isolate(A)
LLM = FakeLLM('{"room": "  KITCHEN ", "activity": "Sie schaelt Rueben."}')
res = npc_actions.run_action_for(A, llm=LLM)
check("a shouted, padded id still addresses the room",
      res.get("room") if res else None, "kitchen")
check("and the move happened", get_character_current_room(A), "kitchen")

# ── (d) exactly one repair attempt ─────────────────────────────────────────
print("(d) broken JSON gets exactly one repair attempt")
force_set_status(A, room="taproom", activity="Sie wischt den Tresen.")
isolate(A)
LLM = FakeLLM("I think she goes to the kitchen.", "Still not JSON, sorry.")
check("twice broken returns nothing", npc_actions.run_action_for(A, llm=LLM),
      None)
check("and cost exactly two calls", len(LLM.calls), 2)
check("the second call is the repair turn",
      "valid JSON" in LLM.calls[1]["user"], True)
check("and it is capped just like the first",
      LLM.calls[1]["kwargs"].get("max_tokens"), 200)
check("nothing was written", (get_character_current_room(A),
                              get_effective_activity(A)),
      ("taproom", "Sie wischt den Tresen."))
# The module's central cost guarantee: an unusable answer still SPENDS the
# turn. `isolate` popped the stamp, so a stamp here can only come from this
# run — a babbling model buys one interval of quiet, not a retry per check.
check("but the turn was spent all the same", A in npc_actions._last_action,
      True)
check("so the NPC is not due again", npc_actions.candidates(), [])

isolate(A)
LLM = FakeLLM("Sure! Here you go.",
              '{"room": "kitchen", "activity": "Sie deckt den Ofen ab."}')
res = npc_actions.run_action_for(A, llm=LLM)
check("a repaired answer applies", res.get("room") if res else None, "kitchen")
check("in two calls", len(LLM.calls), 2)
check("and moved the NPC", get_character_current_room(A), "kitchen")

# ── (e) the cooldown is GAME time ──────────────────────────────────────────
print("(e) the per-NPC cooldown runs on the game clock")
B = make_npc("Halvard", room_id="taproom", task="chops wood in the yard")
isolate(B)
TICK_LLM = FakeLLM('{"room": "kitchen", "activity": "Er stapelt Holz."}')
llm_router.llm_call = TICK_LLM
check("the NPC is a candidate", npc_actions.candidates(), [B])
npc_actions._sub_npc_actions()
check("the tick acted once", len(TICK_LLM.calls), 1)
check("and moved it", get_character_current_room(B), "kitchen")
check("a second tick right after finds no candidate",
      npc_actions.candidates(), [])
npc_actions._sub_npc_actions()
check("so it calls no LLM at all", len(TICK_LLM.calls), 1)
set_game_time(game_time() + GameDuration.of(minutes=31))
silence(B)   # B KEEPS its own stamp — the clock alone makes it due again
check("31 game minutes later it is eligible again",
      npc_actions.candidates(), [B])
npc_actions._sub_npc_actions()
check("and the tick acts again", len(TICK_LLM.calls), 2)

# ── (f) who is never a candidate ───────────────────────────────────────────
print("(f) pooled, sleeping, busy, travelling and placeless NPCs are never "
      "candidates")
C = make_npc("Ingeborg", room_id="taproom")
isolate(C)
check("a plain living, placed NPC is one", npc_actions.candidates(), [C])
pool_npc(C, reason="smoke")
check("pooled is not", npc_actions.candidates(), [])

D = make_npc("Sigrun", room_id="taproom")
isolate(D)
set_is_sleeping(D, True)
check("sleeping is not", npc_actions.candidates(), [])
set_is_sleeping(D, False)
save_character_current_location(D, LOC_ID)
force_set_status(D, room="taproom")
isolate(D)
_p = get_character_profile(D)
_p["interaction"] = {"id": "i1", "kind": "handshake", "role": "actor",
                     "partner": "Halvard",
                     "started_at_game": game_time().canonical()}
save_character_profile(D, _p)
check("mid-interaction is not", npc_actions.candidates(), [])
_p = get_character_profile(D)
_p["interaction"] = None
save_character_profile(D, _p)
isolate(D)
check("released, it is one again", npc_actions.candidates(), [D])

_p = get_character_profile(D)
_p["journey"] = {"target": LOC2_ID, "path": [], "seconds_per_cell": 10,
                 "started_at_game": game_time().canonical()}
save_character_profile(D, _p)
check("on the road is not", npc_actions.candidates(), [])
_p = get_character_profile(D)
_p["journey"] = None
save_character_profile(D, _p)
isolate(D)
check("arrived, it is one again", npc_actions.candidates(), [D])

save_character_current_location(D, "")
check("standing nowhere is not", npc_actions.candidates(), [])

# The in-chat rule, borrowed whole from the AgentLoop: while an avatar is
# writing to this NPC the tick must not walk it out of the room.
AVATAR = "Player"
save_character_profile(AVATAR, {"character_name": AVATAR,
                                "template": "human-roleplay"}, create_new=True)
_uid = create_user("demo", "smoke-password", allowed_characters=[AVATAR])
update_user(_uid, settings={"active_character": AVATAR})
NPC_IN_CHAT = make_npc("Ragnhild", room_id="taproom")
isolate(NPC_IN_CHAT)
check("before a word is spoken it is a candidate",
      npc_actions.candidates(), [NPC_IN_CHAT])


def chat_row(character: str, partner: str, minutes_ago: float) -> None:
    """One chat_messages row, stamped in SYSTEM time — that is the clock the
    agent loop's own helper measures against (technical stamp, not game time).
    """
    ts = (utc_now() - timedelta(minutes=minutes_ago)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chat_messages (character_name, partner, ts, role, "
            "content, channel) VALUES (?, ?, ?, 'user', 'Hallo?', 'web')",
            (character, partner, ts))


chat_row(NPC_IN_CHAT, AVATAR, 0.0)
check("mid-conversation with an avatar it is NOT", npc_actions.candidates(), [])
with db.transaction() as _conn:
    _conn.execute("DELETE FROM chat_messages")
chat_row(NPC_IN_CHAT, AVATAR, 20.0)
isolate(NPC_IN_CHAT)
check("20 minutes later — outside the HOT window — it is one again",
      npc_actions.candidates(), [NPC_IN_CHAT])
with db.transaction() as _conn:
    _conn.execute("DELETE FROM chat_messages")
chat_row(NPC_IN_CHAT, B, 0.0)
isolate(NPC_IN_CHAT)
check("a fresh word with a NON-avatar partner is not 'in chat' at all",
      npc_actions.candidates(), [NPC_IN_CHAT])
with db.transaction() as _conn:
    _conn.execute("DELETE FROM chat_messages")
silence()

# ── (g) the block rules still rule ─────────────────────────────────────────
print("(g) a block rule on the target room denies the move")
rules_model.add_rule({"id": "smoke_block_kitchen", "type": "block",
                      "name": "Kitchen closed", "action": "enter",
                      "condition": "always",
                      "message": "The kitchen is closed.",
                      "target": {"scope": "room", "location_id": LOC_ID,
                                 "room_ids": ["kitchen"]}})
E = make_npc("Torgrim", room_id="taproom", task="waits for the coach")
force_set_status(E, room="taproom", activity="Er wartet auf die Kutsche.")
isolate(E)
LLM = FakeLLM('{"room": "kitchen", "activity": "Er sucht die Speisekammer."}')
check("the blocked move returns nothing",
      npc_actions.run_action_for(E, llm=LLM), None)
check("and nothing was written", (get_character_current_room(E),
                                  get_effective_activity(E)),
      ("taproom", "Er wartet auf die Kutsche."))
rules_model.delete_rule("smoke_block_kitchen")

# ── (h) the place must still be the place ──────────────────────────────────
print("(h) a location change during the turn discards the answer")


class MovingLLM(FakeLLM):
    """An LLM turn that relocates the NPC while it 'thinks' — the TOCTOU
    window between assembling the room list and writing the answer."""

    def __init__(self, name, target_location, *answers):
        super().__init__(*answers)
        self.name = name
        self.target_location = target_location

    def __call__(self, task, system_prompt, user_prompt, **kwargs):
        save_character_current_location(self.name, self.target_location)
        return super().__call__(task, system_prompt, user_prompt, **kwargs)


H = make_npc("Vigdis", room_id="taproom")
isolate(H)
LLM = MovingLLM(H, LOC2_ID,
                '{"room": "kitchen", "activity": "Sie holt Mehl."}')
check("the answer is discarded", npc_actions.run_action_for(H, llm=LLM), None)
check("the NPC really did leave mid-turn",
      get_character_current_location(H), LOC2_ID)
_MILL_ROOMS = [r["id"] for r in world.get_location_by_id(LOC2_ID)["rooms"]]
check("and its room is one of the Mill's, never a Roadhouse room",
      get_character_current_room(H) in _MILL_ROOMS + [""], True)

# ── (i) the batch caps the cost ────────────────────────────────────────────
print("(i) one tick acts on at most npc.action_batch NPCs")
F = make_npc("Aslaug", room_id="taproom")
G = make_npc("Bergljot", room_id="taproom")
isolate(E, F, G)
check("three are eligible", len(npc_actions.candidates()), 2)
BATCH_LLM = FakeLLM('{"room": "taproom", "activity": "Sie wartet."}')
llm_router.llm_call = BATCH_LLM
npc_actions._sub_npc_actions()
check("but only two turns are spent", len(BATCH_LLM.calls), 2)

# ── (j) the tick is switchable ─────────────────────────────────────────────
print("(j) npc.action_tick_enabled false = no candidates")
isolate(E, F, G)
set_npc_config(action_tick_enabled=False)
check("switched off, nobody is a candidate", npc_actions.candidates(), [])
set_npc_config(action_tick_enabled=True)
check("switched on again, they are", len(npc_actions.candidates()), 2)

# ── (k) the template renders under StrictUndefined ─────────────────────────
print("(k) the template renders with the variable set the module passes")
_vars = npc_actions.prompt_vars(A)
_system, _user = render_task("npc_action", **_vars)
check("system part is non-empty", bool(_system.strip()), True)
check("user part is non-empty", bool(_user.strip()), True)
check("and the answer shape is spelled out", '"room"' in _system, True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
