#!/usr/bin/env python3
"""Smoke: copied placeholders never run a tool; DescribeRoom gets its ids in
the rp_first tool step; GoToCharacter reads the name out of a JSON object.

Usage:  ./.venv/bin/python scripts/smoke_tool_placeholder_inputs.py

Throwaway storage and world DB (paths.init on a temp dir BEFORE any world-DB
import); no server, no LLM, no image render (the room-image trigger is
stubbed). Expectations derived by hand:

[1] Placeholder guard (skill_gate.placeholder_refusal). A value counts only
    when the WHOLE value is one "<...>":
    '{"location_id": "<allowed id>", "room": "Hall"}' -> refused (field);
    '<allowed id>' -> refused (whole text); '{"equip": ["<inventory item
    name>"]}' -> refused (list item); '{"prompt": "A photo of <ref 1> at the
    beach"}', '{"text": "<b>bold</b> words"}', 'Kai, <hello>' and
    '{"room": "Hall"}' -> '' (free text, HTML, plain text with a tag, real
    value). A refusal starts with "Error:".
[2] At the execution boundary: run_gated with DescribeRoom and
    '{"location_id": "<allowed id>", ...}' returns the refusal, the skill
    call never runs (0 calls), the tool log row has status "error".
[3] DescribeRoom.decision_menu for Merle, allowed = [N, M] (N = location
    "Nordstraße" with room "Hall", M = "Markt" without rooms):
    ["<N> = Nordstraße (rooms: Hall)", "<M> = Markt"]. The rendered tool-step
    user part holds the block "DescribeRoom takes these location ids …:" with
    both lines; the brief holds no "<".
[4] Name -> id: location_id "nordstraße" (exact name, other case) resolves
    to N and the room Hall is updated ("Raum aktualisiert: Hall (Nordstraße)").
    "Nord" (a part of the name) is refused ("nicht erlaubt"). With a second
    allowed location ALSO named "Nordstraße" the name is ambiguous -> refused.
[5] GoToCharacter, actor "Ada Berg" and target "Tom Lind" in the same room,
    so every resolved call answers "You are already in the same room as Tom
    Lind." The executor envelope is {"input": <raw>, "agent_name": ...} plus
    the parsed JSON fields (thoughts/act wrappers):
      {"character": "Tom Lind"}, {"name": "Tom Lind"}, {"target": "Tom Lind"},
      plain "Tom Lind" and plain "Tom Lind, hurry" -> same room;
      {"person": "Tom Lind"} (none of the keys) -> "Error: no person given…"
      (the raw JSON is NOT looked up as a name);
      {"name": "Ada Berg"} -> "That is you…".
    The brief names the "character" key and holds no "<".
[6] act_engine.perform_act while the same actor's act still runs: busy,
    the summary keeps its exact wording ("Action not performed: Ada Berg's
    previous action is still being narrated — an action cannot trigger
    another action.", no "Error:" — callers treat it as before), but
    tool_call_log.classify says "refused" and the row run_gated writes for
    the Act call has status "refused" (it read "ok").
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="tool-placeholders-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402
paths.init(TMP / "world")
from app.core import config, db  # noqa: E402
config.load(paths.get_config_path())
db.init_schema()

from app.core import tool_call_log  # noqa: E402
from app.core.skill_gate import placeholder_refusal, run_gated  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (save_character_current_location,  # noqa: E402
                                  save_character_current_room,
                                  save_character_profile,
                                  save_character_skill_config)
from app.skills.describe_room_skill import DescribeRoomSkill  # noqa: E402

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


print("[1] the guard hits whole placeholder values only")
for raw, refused in (
        ('{"location_id": "<allowed id>", "room": "Hall"}', True),
        ("<allowed id>", True),
        ('{"equip": ["<inventory item name>"]}', True),
        ('{"prompt": "A photo of <ref 1> at the beach"}', False),
        ('{"text": "<b>bold</b> words"}', False),
        ("Kai, <hello>", False),
        ('{"room": "Hall"}', False)):
    got = placeholder_refusal(raw)
    check(f"[1] {raw}", bool(got) and got.startswith("Error:"), refused)
    if not refused:
        check(f"[1] {raw} -> ''", got, "")

N = world.add_location("Nordstraße", "A street.",
                       rooms=[{"id": "hall", "name": "Hall", "description": "Old."}])["id"]
M = world.add_location("Markt", "A square.")["id"]
for name in ("Merle", "Ada Berg", "Tom Lind"):
    save_character_profile(name, {"character_name": name, "template": "human-roleplay"},
                           create_new=True)
save_character_skill_config("Merle", "describe_room", {"design_locations": [N, M]})
skill = DescribeRoomSkill({"enabled": True})

print("[2] the boundary refuses a placeholder without running the skill")
tool_call_log.configure(TMP / "tool_calls.jsonl")
calls = []
manager = Mock(get_skill=lambda sid: skill if sid == "describe_room" else None,
               get_skill_by_name=lambda n: skill if n == skill.name else None,
               tool_names_with_flag=lambda flag: frozenset())
raw = '{"location_id": "<allowed id>", "room": "Hall", "description": "Bright."}'
with patch("app.core.dependencies.get_skill_manager", return_value=manager):
    result = run_gated("Merle", "describe_room", lambda: calls.append(1) or "done",
                       tool_input=raw, tool_name=skill.name)
check("[2] refusal returned", result.startswith("Error: <allowed id> is a placeholder"), True)
check("[2] the skill never ran", calls, [])
rows = [json.loads(line) for line in (TMP / "tool_calls.jsonl").read_text().splitlines()]
check("[2] logged as error", [r["status"] for r in rows], ["error"])

print("[3] DescribeRoom lists its ids in the tool step")
menu = skill.decision_menu("Merle")
check("[3] menu lines", menu, [f"{N} = Nordstraße (rooms: Hall)", f"{M} = Markt"])
check("[3] no angle brackets in the brief", "<" in skill.brief, False)
from app.core.tool_step_prompt import build_tool_step_prompt  # noqa: E402
from app.skills.base import TurnFacts  # noqa: E402
with patch("app.core.dependencies.get_skill_manager", return_value=manager), \
        patch("app.core.streaming.open_questions_note", return_value=""), \
        patch("app.routes.chat._marker_travel_refusal", return_value="unavailable"), \
        patch("app.models.intents.build_open_intents_brief", return_value=""):
    rendered = build_tool_step_prompt(
        "Merle", mode="thought", rp_response="I look around the hall.", user_input="",
        tools=[skill], facts=TurnFacts("Merle", "thought", ()), tool_format="tag")
block = (f"DescribeRoom {skill.decision_menu_heading}:\n"
         f"- {N} = Nordstraße (rooms: Hall)\n- {M} = Markt\n")
check("[3] the menu block is in the rendered user part", block.rstrip() in rendered.user, True)

print("[4] an exact place name resolves to its id")


def describe(location_id):
    return skill.execute(json.dumps({"agent_name": "Merle", "location_id": location_id,
                                     "room": "Hall", "description": "Bright and tidy."}))


with patch.object(DescribeRoomSkill, "_trigger_room_image", lambda *a, **k: None):
    check("[4] 'nordstraße' -> N", describe("nordstraße").split("\n")[0],
          "Raum aktualisiert: Hall (Nordstraße)")
    check("[4] a partial name is refused", "nicht erlaubt" in describe("Nord"), True)
    N2 = world.add_location("Nordstraße", "Another street.")["id"]
    save_character_skill_config("Merle", "describe_room", {"design_locations": [N, M, N2]})
    check("[4] an ambiguous name is refused", "nicht erlaubt" in describe("Nordstraße"), True)

print("[5] GoToCharacter reads character|name|target")
from app.plugins.context import PluginContext  # noqa: E402
from plugins.movement.skill_go_to_character import GoToCharacterSkill  # noqa: E402
for name in ("Ada Berg", "Tom Lind"):
    save_character_current_location(name, M)
    save_character_current_room(name, "")
go = GoToCharacterSkill({"enabled": True}, PluginContext("movement"))


def go_to(raw):
    ctx = {"input": raw, "agent_name": "Ada Berg", "user_id": ""}
    if raw.startswith("{"):
        ctx.update(json.loads(raw))
    return go.execute(json.dumps(ctx))


SAME = "You are already in the same room as Tom Lind."
for raw in ('{"character": "Tom Lind"}', '{"name": "Tom Lind"}', '{"target": "Tom Lind"}',
            "Tom Lind", "Tom Lind, hurry"):
    check(f"[5] {raw}", go_to(raw), SAME)
check("[5] a JSON object without a name key is no name",
      go_to('{"person": "Tom Lind"}').startswith("Error: no person given"), True)
check("[5] oneself", go_to('{"name": "Ada Berg"}').startswith("That is you"), True)
meta = Path("plugins/movement/templates/llm/skills/go_to_character.md").read_text()
brief = next(line for line in meta.splitlines() if line.startswith("brief:"))
check("[5] the brief names the character key", '"character"' in brief, True)
check("[5] no angle brackets in the brief", "<" in brief, False)

print("[6] the act refusal is logged as refused, its text unchanged")
import asyncio  # noqa: E402
from app.core import act_engine  # noqa: E402
from app.core.tool_call_log import classify  # noqa: E402
act_engine._ACTING.add("Ada Berg")
try:
    refused = asyncio.run(act_engine.perform_act("Ada Berg", "waves", "room"))
finally:
    act_engine._ACTING.discard("Ada Berg")
summary = refused["summary"]
check("[6] busy", refused["busy"], True)
check("[6] the text is the old wording",
      str(summary), "Action not performed: Ada Berg's previous action is still being "
                    "narrated — an action cannot trigger another action.")
check("[6] classified as refused", classify(summary), "refused")
(TMP / "tool_calls.jsonl").write_text("")
run_tool_result = run_gated("Ada Berg", "act", lambda: summary, tool_input="waves",
                            tool_name="Act")
rows = [json.loads(line) for line in (TMP / "tool_calls.jsonl").read_text().splitlines()]
check("[6] the tool log row says refused", [r["status"] for r in rows], ["refused"])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("ALL CHECKS PASSED")
