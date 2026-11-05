#!/usr/bin/env python3
"""Smoke: a worn persona's behaviour overrides in its bearer's OWN prompts.

Usage:  ./.venv/bin/python scripts/smoke_identity_overrides.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world, no transformation package: fake ``identity.*``
providers registered with owner "smoke" stand in for it.

THE RULE (restated from the plan, Task 3)
    * OVERRIDABLE_FIELDS = character_personality, dialogue_style,
      character_presence, character_task, character_goals.
    * self_field(C, key) while C wears a persona: a key of OVERRIDABLE_FIELDS
      -> the persona's non-empty override; "character_appearance" -> the
      persona description when non-empty; anything else -> None. Not
      transformed / no provider -> None (= the real value).
    * routine_paused(C) = C wears a persona with pause_routine True.
    * build_prompt_section with a character_name: self_field wins BEFORE the
      source_file branch (so over the MD file). Without a character_name a
      source_file field takes data[key] (the masked partner dict).
    * The masked partner dict of a NON-KNOWER = {name: label, appearance:
      persona description} + presence ONLY when the persona overrides it —
      never the real presence.md.
    * Thought context: personality / general_task from the override; the
      retrospective block's goals lines replaced by the override lines
      (beliefs stay), no "consider using Reflect" nudge while transformed;
      pause_routine -> daily_schedule_block "" and rhythm_sleep_now False.
    * Retrospect: transformed -> skipped, no LLM call.
    * Deletion test: no provider -> every value real again.

FIXTURE
    Location "Inn" (room "taproom"); Cara (the bearer), Kim (a knower),
    Obs (knows nothing), template human-roleplay, all in the taproom.
    Cara's real values (each soul file "# Soul" + "## Core" + the text —
    load_source_file keeps only "## " sections, so a read value is
    "## Core\\n<text>"): soul/personality.md "REAL-PERS shy and careful",
    soul/presence.md "REAL-PRES quiet warmth", soul/tasks.md "REAL-TASK run
    the bakery", soul/goals.md "- REAL-GOAL open a second shop",
    soul/beliefs.md "- REAL-BELIEF bread heals", profile dialogue_style
    "REAL-SPEECH soft and slow", appearance "REAL-LOOK freckled redhead".
    Daily schedule: hours 0-5 sleep, 6-23 role "baking" (enabled).
    Game clock Y0002-D100T12:00, frozen.
    Persona answer for Cara: alias "Moonveil", description "P-LOOK a figure
    in moonlit silver", field_overrides personality "P-PERS bold and
    theatrical", dialogue_style "P-SPEECH clipped commands", presence
    "P-PRES a cold hush follows her", task "P-TASK guard the harbour",
    goals "P-GOAL unmask the smuggler\\nP-GOAL2 stay unseen", plus an
    empty-string override "" for nothing else; pause_routine True.
    knows(O, Cara) = O == "Kim".

EXPECTED, derived BY HAND from the rule above
---------------------------------------------
[A] self_field: personality -> "P-PERS bold and theatrical"; presence ->
    "P-PRES a cold hush follows her"; appearance -> "P-LOOK a figure in
    moonlit silver"; "character_soul" -> None (not overridable); Kim
    (not transformed) personality -> None. An answer whose personality
    override is "   " -> None; an answer with description "" -> appearance
    None. routine_paused(Cara) True, routine_paused(Kim) False.
    Persona sanitizing: suit_items ["a", 3, "", "a", "b"] -> ("a", "b");
    field_overrides {"bogus": "x", "character_task": 5} -> {}; imagegen a
    deep copy (mutating the source after the read leaves it unchanged);
    pause_routine "yes" -> False.
[B] build_prompt_section, template = one prompt field personality with
    source_file soul/personality.md, label "Personality": Cara transformed
    -> ["Personality: P-PERS bold and theatrical"] (file text absent); the
    same with character_name="" and data {"character_personality": "X"}
    -> ["Personality: X"].
[C] _masked_partner_data("Cara", "Moonveil", desc) -> {character_name
    "Moonveil", character_appearance desc, character_presence "P-PRES a
    cold hush follows her"}; with the presence override removed -> no
    character_presence key.
[D] Chat system prompt of Cara (partner Obs): contains P-PERS, P-SPEECH,
    P-PRES, P-TASK, P-GOAL, P-LOOK; none of REAL-PERS, REAL-SPEECH,
    REAL-PRES, REAL-TASK, REAL-GOAL, REAL-LOOK.
    Obs's system prompt (partner Cara, non-knower): contains P-PRES and
    P-LOOK, not REAL-PRES, not REAL-LOOK. Kim's (knower): P-PRES, not
    REAL-PRES. Presence override removed: Obs has neither P-PRES nor
    REAL-PRES; Kim has REAL-PRES (no override = the real value).
[E] Thought context of Cara: personality "P-PERS bold and theatrical";
    general_task "P-TASK guard the harbour"; daily_schedule_block "";
    rhythm_sleep_now False; retrospective_block has "P-GOAL unmask the
    smuggler" and "P-GOAL2 stay unseen" and "REAL-BELIEF", no "REAL-GOAL",
    no "consider using Reflect". pause_routine False -> the schedule block
    is back (contains "baking").
[F] Retrospect for Cara transformed -> "Retrospect pauses while you are
    transformed.", llm_call never called.
[G] Deletion test (unregister owner "smoke"): self_field -> None;
    routine_paused False; [B] -> ["Personality:", "## Core\\nREAL-PERS shy
    and careful"] (a multi-line value goes under its label line);
    Cara's chat prompt has REAL-PERS/REAL-SPEECH/REAL-PRES/REAL-TASK/
    REAL-GOAL/REAL-LOOK and no P-*; thought context personality
    "REAL-PERS shy and careful", task "REAL-TASK run the bakery", schedule
    block contains "baking" (both values "## Core\\n<text>"), retrospective
    block has REAL-GOAL and the
    Reflect nudge; Retrospect passes its gate ("Nothing to reflect on yet —
    no recent material.", still no LLM call).
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-overrides-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text(json.dumps({}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None

from app.core import hooks, identity_view  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.character import (get_character_dir, get_character_profile,  # noqa: E402
                                  save_character_daily_schedule, save_character_profile)
from app.models.character_template import build_prompt_section, invalidate_source_file  # noqa: E402
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

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


def has(label, text, needle, expected=True):
    global CHECKED
    CHECKED += 1
    ok = (needle in text) == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {'has' if expected else 'lacks'} {needle!r}")
    if not ok:
        FAILURES.append(label)


set_game_factor(0.0)
set_game_time(GameTime.parse("Y0002-D100T12:00:00"))

INN = add_location("Inn", "A stone house.")["id"]
ROOM = "taproom"
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": ROOM, "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = ROOM
_save_world_data(_data)

for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = ROOM
        if _name == "Cara":
            _p["character_appearance"] = "REAL-LOOK freckled redhead"
            _p["dialogue_style"] = "REAL-SPEECH soft and slow"
        assert save_character_profile(_name, _p)

# A soul file says something only under a "## " section (strip_empty_sections
# drops the prelude), so every value sits under "## Core".
SOUL = {"personality.md": "REAL-PERS shy and careful",
        "presence.md": "REAL-PRES quiet warmth",
        "tasks.md": "REAL-TASK run the bakery",
        "goals.md": "- REAL-GOAL open a second shop",
        "beliefs.md": "- REAL-BELIEF bread heals"}
_soul_dir = get_character_dir("Cara", create=True) / "soul"
_soul_dir.mkdir(parents=True, exist_ok=True)
for _fname, _text in SOUL.items():
    (_soul_dir / _fname).write_text(f"# Soul\n\n## Core\n{_text}\n", encoding="utf-8")
    invalidate_source_file(_soul_dir / _fname)

_slots = ([{"hour": h, "sleep": True} for h in range(6)]
          + [{"hour": h, "role": "baking"} for h in range(6, 24)])
assert save_character_daily_schedule("Cara", {"enabled": True, "slots": _slots})

DESC = "P-LOOK a figure in moonlit silver"
OVERRIDES = {"character_personality": "P-PERS bold and theatrical",
             "dialogue_style": "P-SPEECH clipped commands",
             "character_presence": "P-PRES a cold hush follows her",
             "character_task": "P-TASK guard the harbour",
             "character_goals": "P-GOAL unmask the smuggler\nP-GOAL2 stay unseen"}
STATE = {"answer": {"persona_id": "p1", "alias": "Moonveil", "description": DESC,
                    "portrait_url": "", "field_overrides": dict(OVERRIDES),
                    "pause_routine": True, "imagegen": {"loras": [{"name": "x"}]},
                    "suit_items": ["suit"]}}


def _active(subject):
    return copy.deepcopy(STATE["answer"]) if subject == "Cara" else None


def _knows(observer, subject):
    return observer == "Kim"


def register():
    hooks.register_provider(identity_view.PROVIDER_ACTIVE, _active, owner="smoke")
    hooks.register_provider(identity_view.PROVIDER_KNOWS, _knows, owner="smoke")


register()

from app.core import thought_context as tc  # noqa: E402
from app.routes.chat import _build_chat_prompt, _masked_partner_data  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402
from plugins.retrospect.skill import RetrospectSkill  # noqa: E402

TEMPLATE = {"sections": [{"fields": [
    {"key": "character_personality", "label": "Personality", "in_prompt": True,
     "source_file": "soul/personality.md"}]}]}


def system_of(responder, partner):
    return _build_chat_prompt(responder, "", "", partner_override=partner).system


def run_retrospect():
    calls = []

    def _fake_llm(**kw):
        calls.append(kw)
        raise RuntimeError("no LLM in a smoke")

    skill = RetrospectSkill({}, PluginContext("retrospect"))
    with patch("app.core.llm_router.llm_call", _fake_llm):
        out = skill.execute(json.dumps({"agent_name": "Cara"}))
    return out, calls


print("[A] self_field / routine_paused / Persona sanitizing")
check("personality", identity_view.self_field("Cara", "character_personality"),
      "P-PERS bold and theatrical")
check("presence", identity_view.self_field("Cara", "character_presence"),
      "P-PRES a cold hush follows her")
check("appearance", identity_view.self_field("Cara", "character_appearance"), DESC)
check("soul not overridable", identity_view.self_field("Cara", "character_soul"), None)
check("Kim not transformed", identity_view.self_field("Kim", "character_personality"), None)
check("routine_paused Cara", identity_view.routine_paused("Cara"), True)
check("routine_paused Kim", identity_view.routine_paused("Kim"), False)
check("OVERRIDABLE_FIELDS", identity_view.OVERRIDABLE_FIELDS,
      ("character_personality", "dialogue_style", "character_presence",
       "character_task", "character_goals"))
_saved = STATE["answer"]
STATE["answer"] = dict(_saved, description="",
                       field_overrides=dict(OVERRIDES, character_personality="   "),
                       suit_items=["a", 3, "", "a", "b"], pause_routine="yes")
check("blank override -> None", identity_view.self_field("Cara", "character_personality"), None)
check("empty description -> None", identity_view.self_field("Cara", "character_appearance"), None)
_p = identity_view.active_persona("Cara")
check("suit_items sanitized", _p.suit_items, ("a", "b"))
check("pause_routine 'yes' -> False", _p.pause_routine, False)
STATE["answer"] = dict(_saved, field_overrides={"bogus": "x", "character_task": 5})
check("junk overrides -> {}", dict(identity_view.active_persona("Cara").field_overrides), {})
_src = {"loras": [{"name": "x"}]}
_ans = dict(_saved, imagegen=_src)
hooks.register_provider(identity_view.PROVIDER_ACTIVE,
                        lambda s: _ans if s == "Cara" else None, owner="smoke")
_p = identity_view.active_persona("Cara")
_src["loras"].append({"name": "y"})
check("imagegen is a deep copy", _p.imagegen["loras"], [{"name": "x"}])
STATE["answer"] = _saved
register()

print("[B] build_prompt_section")
check("transformed -> override over the MD file",
      build_prompt_section(TEMPLATE, {}, character_name="Cara"),
      ["Personality: P-PERS bold and theatrical"])
check("no character_name -> data[key]",
      build_prompt_section(TEMPLATE, {"character_personality": "X"}, character_name=""),
      ["Personality: X"])

print("[C] masked partner dict")
check("with presence override", _masked_partner_data("Cara", "Moonveil", DESC),
      {"character_name": "Moonveil", "character_appearance": DESC,
       "character_presence": "P-PRES a cold hush follows her"})
STATE["answer"] = dict(_saved, field_overrides={k: v for k, v in OVERRIDES.items()
                                                if k != "character_presence"})
check("without presence override", _masked_partner_data("Cara", "Moonveil", DESC),
      {"character_name": "Moonveil", "character_appearance": DESC})
STATE["answer"] = _saved

print("[D] chat system prompts")
_sys = system_of("Cara", "Obs")
for _tag in ("P-PERS", "P-SPEECH", "P-PRES", "P-TASK", "P-GOAL", "P-LOOK"):
    has(f"Cara own {_tag}", _sys, _tag)
for _tag in ("REAL-PERS", "REAL-SPEECH", "REAL-PRES", "REAL-TASK", "REAL-GOAL", "REAL-LOOK"):
    has(f"Cara own {_tag}", _sys, _tag, False)
_obs = system_of("Obs", "Cara")
has("Obs partner P-PRES", _obs, "P-PRES")
has("Obs partner P-LOOK", _obs, "P-LOOK")
has("Obs partner REAL-PRES", _obs, "REAL-PRES", False)
has("Obs partner REAL-LOOK", _obs, "REAL-LOOK", False)
_kim = system_of("Kim", "Cara")
has("Kim partner P-PRES", _kim, "P-PRES")
has("Kim partner REAL-PRES", _kim, "REAL-PRES", False)
STATE["answer"] = dict(_saved, field_overrides={k: v for k, v in OVERRIDES.items()
                                                if k != "character_presence"})
_obs = system_of("Obs", "Cara")
has("no override: Obs P-PRES", _obs, "P-PRES", False)
has("no override: Obs REAL-PRES", _obs, "REAL-PRES", False)
has("no override: Kim REAL-PRES", system_of("Kim", "Cara"), "REAL-PRES")
STATE["answer"] = _saved

print("[E] thought context")
_ctx = tc.build_thought_context("Cara")
check("personality", _ctx["personality"], "P-PERS bold and theatrical")
check("general_task", _ctx["general_task"], "P-TASK guard the harbour")
check("daily_schedule_block", _ctx["daily_schedule_block"], "")
check("rhythm_sleep_now", _ctx["rhythm_sleep_now"], False)
_retro = _ctx["retrospective_block"]
has("retro P-GOAL", _retro, "P-GOAL unmask the smuggler")
has("retro P-GOAL2", _retro, "P-GOAL2 stay unseen")
has("retro REAL-BELIEF", _retro, "REAL-BELIEF")
has("retro REAL-GOAL", _retro, "REAL-GOAL", False)
has("retro reflect nudge", _retro, "consider using Reflect", False)
STATE["answer"] = dict(_saved, pause_routine=False)
has("pause_routine off -> schedule back",
    tc.build_thought_context("Cara")["daily_schedule_block"], "baking")
STATE["answer"] = _saved

print("[F] retrospect")
_out, _calls = run_retrospect()
check("retrospect skipped", _out, "Retrospect pauses while you are transformed.")
check("no LLM call", len(_calls), 0)

print("[G] deletion test")
hooks.unregister_owned_providers("smoke")
check("self_field gone", identity_view.self_field("Cara", "character_personality"), None)
check("routine_paused gone", identity_view.routine_paused("Cara"), False)
check("section reads the file", build_prompt_section(TEMPLATE, {}, character_name="Cara"),
      ["Personality:", "## Core\nREAL-PERS shy and careful"])
_sys = system_of("Cara", "Obs")
for _tag in ("REAL-PERS", "REAL-SPEECH", "REAL-PRES", "REAL-TASK", "REAL-GOAL", "REAL-LOOK"):
    has(f"real {_tag}", _sys, _tag)
has("no P- value", _sys, "P-PERS", False)
has("Obs sees real presence", system_of("Obs", "Cara"), "REAL-PRES")
_ctx = tc.build_thought_context("Cara")
check("real personality", _ctx["personality"], "## Core\nREAL-PERS shy and careful")
check("real task", _ctx["general_task"], "## Core\nREAL-TASK run the bakery")
has("real schedule", _ctx["daily_schedule_block"], "baking")
has("real goals", _ctx["retrospective_block"], "REAL-GOAL")
has("reflect nudge back", _ctx["retrospective_block"], "consider using Reflect")
_out, _calls = run_retrospect()
check("retrospect passes its gate", _out, "Nothing to reflect on yet — no recent material.")
check("still no LLM call", len(_calls), 0)

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("smoke_identity_overrides: OK")
