#!/usr/bin/env python3
"""A3.2b — checks the rp_first tool-decision prompt.

Usage:
    ./.venv/bin/python scripts/test_a32b_tool_prompt.py

Runs WITHOUT the server and with a temporary world DB: the skill manager and
the world's location list are replaced by synthetic stubs, so every expected
value below is derived by hand from the fixture, not from live data.

Fixture (hand-built): a character with the tools
    ChangeOutfit (SINGLETON), TakePhoto, SetLocation (SINGLETON),
    JoinParty, TalkTo (DELIVERS_SPEECH), SendMessage (DELIVERS_SPEECH +
    REMOTE_COMM)
and the same character as a PARTY FOLLOWER, i.e. without SetLocation
(party_engine: only the leader moves).

Expectations, derived by hand:
  The new shared template lists only offered tools with their brief, keeps
  singleton and speech guardrails, suppresses in-person movement and omits
  pose/mood markers. A free character gets the place marker; followers and
  movement owners do not. Respond uses the same builder.
  Both paths retain inventory-derived tool names, image-name guidance and
  no dead tool names. Six locations with three distinct names deduplicate
  to three legacy catalogue entries.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Throwaway storage BEFORE any app import: every world read below is stubbed,
# but a stub that is missed must hit an empty temp world, never a real one.
from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="a32b_"))
from app.core import db
db.init_schema()

FAILS = []
RESULTS = []


def check(label, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("  OK   " if cond else "  FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(label)


# ----------------------------------------------------------------------
# Stub skill manager (no DB, no plugin loading)
# ----------------------------------------------------------------------

class _Skill:
    def __init__(self, name, hint, singleton=False, speech=False, remote=False,
                 suppress_in_person=False, progress_type=""):
        self.name = name
        self.action_hint = hint
        self.SINGLETON = singleton
        self.DELIVERS_SPEECH = speech
        self.REMOTE_COMM = remote
        self.SUPPRESS_IN_PERSON = suppress_in_person
        self.PROGRESS_TYPE = progress_type
        self.brief = hint
        self.description = f"{name} does something"

    def available_now(self, facts):
        return None

    def get_usage_instructions(self, format_name="", **kwargs):
        return f"USAGE {self.name}: <tool name=\"{self.name}\">x</tool>"


_SKILLS = [
    _Skill("ChangeOutfit", "Character changes/puts on/takes off clothes, outfit, dress, shirt etc.",
           singleton=True),
    _Skill("TakePhoto", "Character takes a photo / makes an image / shows a picture",
           progress_type="image"),
    _Skill("SetLocation", "Character moves to a different room/location ON THEIR OWN",
           singleton=True, suppress_in_person=True),
    _Skill("JoinParty", "Character agrees to go somewhere TOGETHER with whoever invited them"),
    _Skill("TalkTo", "Character speaks to someone present in the room", speech=True),
    _Skill("SendMessage", "Character writes a remote text message to another character",
           speech=True, remote=True),
    _Skill("GoToCharacter", "Character walks over to another character",
           suppress_in_person=True),
]


class _StubManager:
    skills = _SKILLS

    def get_skill_by_name(self, name):
        return next((s for s in _SKILLS if s.name.lower() == name.lower()), None)

    def get_action_hint(self, name):
        s = self.get_skill_by_name(name)
        return getattr(s, "action_hint", "") if s else ""

    def tool_names_with_flag(self, flag):
        return frozenset(s.name for s in _SKILLS if getattr(s, flag, False))

    # The REAL filter of the skill manager, run over the fixture skills. The
    # fixture list is handed to it through a separate holder: a
    # _get_agent_skills on THIS stub would change what
    # routes/chat._marker_travel_refusal answers in section 4.
    def get_agent_usage_instructions(self, character_name, format_name="",
                                     check_limits=True, exclude=frozenset(), turn=None):
        from app.skills.skill_manager import SkillManager

        class _Holder:
            def _get_agent_skills(self, name, check_limits=True, turn=None):
                return list(_SKILLS)

        return SkillManager.get_agent_usage_instructions(
            _Holder(), character_name, format_name, check_limits=check_limits,
            exclude=exclude, turn=turn)


import app.core.dependencies as deps  # noqa: E402
deps.get_skill_manager = lambda: _StubManager()

# The current pose is a world read — stubbed to a fixed value so both
# decision prompts can be checked for it (B7).
import app.core.streaming as _streaming_mod  # noqa: E402
_streaming_mod.current_pose_text = lambda name: "sitting: reads a letter"

from app.core.streaming import (StreamingAgent, action_mapping_lines)  # noqa: E402

LEADER = {n: (lambda x: "") for n in
          ["ChangeOutfit", "TakePhoto", "SetLocation", "JoinParty", "TalkTo", "SendMessage"]}
FOLLOWER = {k: v for k, v in LEADER.items() if k != "SetLocation"}
MUTE = {"ChangeOutfit": (lambda x: ""), "TakePhoto": (lambda x: "")}


def streaming_prompt(tools, *, thought=False, constrained=False, in_person=False,
                     marker_refusal="has_movement_verb"):
    from app.core.tool_step_prompt import build_tool_step_prompt
    from app.skills.base import TurnFacts
    from unittest.mock import patch
    mode = 'thought' if thought else 'respond'
    offered = [n for n in tools if not (in_person and
               getattr(_StubManager().get_skill_by_name(n), 'SUPPRESS_IN_PERSON', False))]
    with patch('app.routes.chat._marker_travel_refusal', return_value=marker_refusal):
        prompt = build_tool_step_prompt('demo', mode=mode, rp_response='She walks to the kitchen.',
            user_input='Hi', tools=offered, facts=TurnFacts('demo', mode, ('Ben Example',), 'Ben Example' if in_person else ''),
            constrained=constrained, tool_format='tag')
    return prompt.system + prompt.user


print("\n1) Party follower loses the SetLocation mapping line")
for label, thought, constrained in [("thought", True, False),
                                    ("chat", False, False),
                                    ("constrained", False, True)]:
    lead = streaming_prompt(LEADER, thought=thought, constrained=constrained)
    foll = streaming_prompt(FOLLOWER, thought=thought, constrained=constrained)
    check(f"streaming/{label}: leader HAS '→ SetLocation'", "- SetLocation:" in lead)
    check(f"streaming/{label}: follower has NO '→ SetLocation'", "- SetLocation:" not in foll)
ce_lead = streaming_prompt(LEADER)
ce_foll = streaming_prompt(FOLLOWER)
check("respond: leader offers movement", "- SetLocation:" in ce_lead)
check("respond: follower has no movement", "- SetLocation:" not in ce_foll)

print("\n2) Dead tool names are gone from both paths")
ALL_PROMPTS = {
    "streaming/thought": streaming_prompt(LEADER, thought=True),
    "streaming/chat": streaming_prompt(LEADER),
    "streaming/constrained": streaming_prompt(LEADER, constrained=True),
    "chat_engine": ce_lead,
}
for name, text in ALL_PROMPTS.items():
    for dead in ("ImageGenerator", "SetPose"):
        check(f"{name}: no '{dead}'", dead not in text)

print("\n3) Inventory-derived declarations and legacy mapping")
lines = action_mapping_lines(LEADER)
check("shared template declares every offered tool", all(f"- {n}:" in ALL_PROMPTS["streaming/chat"] for n in LEADER))
check("respond contains short inventory declarations", all(f"- {n}:" in ce_lead for n in LEADER))
check("6 tools → 6 mapping lines", len(lines.splitlines()) == 6,
      f"{len(lines.splitlines())}")
check("follower mapping has 5 lines", len(action_mapping_lines(FOLLOWER).splitlines()) == 5)

print("\n4) Anti-hallucination rules present")
for name, text in ALL_PROMPTS.items():
    check(f"{name}: speech-verbatim rule", "SPEAKS THEMSELVES" in text)
    check(f"{name}: never another figure's reply",
          "never turn another figure's reply into" in text.lower()
          or "Never turn another figure's reply into" in text)
    check(f"{name}: at-most-one singleton rule", "At most ONE call per answer" in text)
    check(f"{name}: singleton list names SetLocation",
          "ChangeOutfit, SetLocation" in text)
# Since 2026-09-18 the place marker is named only where it may still travel
# (routes/chat._marker_travel_refusal). The fixture owns SetLocation, and the
# chat_engine call below passes no character — without a name the builder
# promises nothing either. So NO prompt here carries the line.
for name, text in ALL_PROMPTS.items():
    check(f"{name}: single-**I am at**-marker rule absent",
          "At most ONE **I am at ...** marker" not in text)

print("\n5) Speech note uses the room verb only")
th = ALL_PROMPTS["streaming/thought"]
check("thought note names TalkTo", "ONLY through TalkTo" in th)
check("thought note does not route speech through SendMessage",
      "through TalkTo / SendMessage" not in th and "ONLY through SendMessage" not in th)
check("chat note limits TalkTo to a third person",
      "ONLY to pass something on to a THIRD person" in ALL_PROMPTS["streaming/chat"])
mute = streaming_prompt(MUTE, thought=True)
check("no room-speech verb → no speech note", "SPEECH IN THIS" not in mute)
check("no room-speech verb → no speech rule", "SPEAKS THEMSELVES" not in mute)

print("\n6) Location catalogue is deduplicated")
import plugins.movement.skill_set_location as sl  # noqa: E402

_LOCS = [
    {"id": "l1", "name": "Wald", "rooms": [{"id": "r1", "name": "Lichtung"}]},
    {"id": "l2", "name": "Wald", "rooms": [{"id": "r2", "name": "Dickicht"}]},
    {"id": "l3", "name": "Stadt", "rooms": [{"id": "r3", "name": "Markt"}]},
    {"id": "l4", "name": "Stadt", "rooms": []},
    {"id": "l5", "name": "Wald", "rooms": []},
    {"id": "l6", "name": "Küste", "rooms": []},
]
sl.list_locations = lambda: _LOCS
sl.get_location_rooms = lambda loc: loc.get("rooms", [])
hint = sl.SetLocationSkill._build_locations_hint(None, "")
body = hint.split("Available locations: ", 1)[1].split(".", 1)[0]
entries = [e.strip() for e in body.split(";")]
check("6 locations, 3 distinct names → 3 entries", len(entries) == 3, str(entries))
check("first 'Wald' wins (its rooms are kept)", entries[0] == "Wald (rooms: Lichtung)", entries[0])
check("'Stadt' listed once", sum(e.startswith("Stadt") for e in entries) == 1)
check("'Küste' still offered", "Küste" in entries)
check("explicit warning against copying the parenthesis",
      "never copy the '(rooms: ...)' listing" in hint)

print("\n7) Tool-instruction system prompt carries no tool names of its own")
from app.core.tool_formats import build_tool_instruction, _DEFAULT_TOOL_INSTRUCTION  # noqa: E402


class _T:
    def __init__(self, name):
        self.name = name
        self.description = f"{name} does something."


for dead in ("ImageGenerator", "SetPose"):
    check(f"_DEFAULT_TOOL_INSTRUCTION: no '{dead}'", dead not in _DEFAULT_TOOL_INSTRUCTION)
for named in ("WebSearch", "SearchKnowledge"):
    check(f"_DEFAULT_TOOL_INSTRUCTION: no hard '{named}'", named not in _DEFAULT_TOOL_INSTRUCTION)
check("_DEFAULT_TOOL_INSTRUCTION: points at the AVAILABLE TOOLS list",
      "AVAILABLE TOOLS" in _DEFAULT_TOOL_INSTRUCTION)
from app.core.tool_formats import TOOL_FORMATS  # noqa: E402
for _fmt_name, _fmt in TOOL_FORMATS.items():
    check(f"format '{_fmt_name}' syntax example uses no real tool name",
          "ImageGenerator" not in _fmt["instruction"])
_full = build_tool_instruction("tag", [_T("TakePhoto"), _T("TalkTo")])
check("assembled instruction block is free of 'ImageGenerator'",
      "ImageGenerator" not in _full)

_with_photo = build_tool_instruction("tag", [_T("TakePhoto"), _T("TalkTo")],
                                     appearance="red hair, green eyes")
_without = build_tool_instruction("tag", [_T("TalkTo")], appearance="red hair, green eyes")
check("appearance hint fires for the declared image tool (PROGRESS_TYPE 'image')",
      "your appearance for reference: red hair, green eyes" in _with_photo)
check("appearance hint stays away without an image tool",
      "your appearance for reference" not in _without)
_photog = build_tool_instruction("tag", [_T("TakePhoto")], photographer_mode=True,
                                 user_appearance="tall, blond")
check("photographer hint fires for the declared image tool",
      "You are a PHOTOGRAPHER" in _photog and "tall, blond" in _photog)

print("\n7b) Image hints ask for NAMES, never role words")
check("image hint: name yourself and every other person",
      "name yourself and every other person in it by name" in _with_photo)
check("photographer hint: subjects named", "by their NAME" in _photog)

print("\n8) In-person turn drops the suppressed movement verb from the mapping")
_ip_stream = streaming_prompt(LEADER, in_person=True)
_ip_thought = streaming_prompt(LEADER, thought=True, in_person=True)
_ip_chat_engine = streaming_prompt(LEADER, in_person=True)
check("streaming/in-person: no '→ SetLocation'", "- SetLocation:" not in _ip_stream)
check("streaming/in-person thought: no '→ SetLocation'", "- SetLocation:" not in _ip_thought)
check("chat_engine/in-person: no '→ SetLocation'", "→ SetLocation" not in _ip_chat_engine)
check("streaming/in-person: singleton rule no longer lists SetLocation",
      "SetLocation" not in _ip_stream)
check("chat_engine/in-person: singleton rule no longer lists SetLocation",
      "SetLocation" not in _ip_chat_engine)
check("streaming/in-person keeps the other 5 tools",
      all(f"- {n}:" in _ip_stream for n in
          ["ChangeOutfit", "TakePhoto", "JoinParty", "TalkTo", "SendMessage"]))
check("not-in-person is unchanged", "- SetLocation:" in streaming_prompt(LEADER))

# The respond mode uses the same short declarations, not long usage examples.
for name in LEADER:
    check(f"respond short declaration: {name}", f"- {name}:" in ce_lead)
check("respond omits long usage examples", "USAGE " not in ce_lead)

# B4: the guard and the missing "user asks" bullet.
_GUARD = "Act only on the character’s text, not on a request alone"
check("respond decision carries the guard", _GUARD in _ip_chat_engine)
check("respond decision scopes the guard to TOOLS",
      "You translate what demo did in the text into tool calls" in _ip_chat_engine)
check("streaming decision keeps its guard", "Act only on the character’s text" in _ip_stream)
_USER_ASKS = "Whenever the user asks for something"
check("tool-decision system part has no 'user asks' bullet",
      _USER_ASKS not in _ip_chat_engine and _USER_ASKS not in ce_lead)
check("build_tool_instruction(for_tool_decision=True) drops the bullet",
      _USER_ASKS not in build_tool_instruction("tag", [_T("TakePhoto")],
                                               for_tool_decision=True))
check("the chat-model default keeps the bullet",
      _USER_ASKS in build_tool_instruction("tag", [_T("TakePhoto")]))
check("tool-decision instruction keeps the rest of the default",
      "Only the tools listed under AVAILABLE TOOLS above exist" in
      build_tool_instruction("tag", [_T("TakePhoto")], for_tool_decision=True))

# Pose and mood are owned by state extraction in rp_first.
check("respond does not request pose or mood", "**I do" not in ce_lead and "**I feel" not in ce_lead)

# ---------------------------------------------------------------------------
# 9) The place rule follows the SERVER's rule, not the tool list alone
# ---------------------------------------------------------------------------
# Derived by hand from routes/chat._marker_travel_refusal (2026-09-18): the
# **I am at ...** marker travels only for a character that has no movement
# verb, is no party follower and is no avatar. So the tool LLM must be told
#   - "call SetLocation, never the marker"  when the character owns the verb,
#   - the marker rule                        when it owns nothing else,
#   - nothing about moving at all            when neither way is open.
# The three cases are driven by the refusal, because that is what the server
# will answer — the tool list alone cannot tell a follower from a character
# that simply owns nothing (both have no SetLocation).
print("\n9) Place rule: tool call vs. marker")
import app.routes.chat as _chat_mod  # noqa: E402

_real_refusal = _chat_mod._marker_travel_refusal
try:
    _chat_mod._marker_travel_refusal = lambda name: "has_movement_verb"
    _lead = streaming_prompt(LEADER)
    _chat_mod._marker_travel_refusal = lambda name: ""
    _free = streaming_prompt(MUTE, marker_refusal="")
    _chat_mod._marker_travel_refusal = lambda name: "party_follower"
    _foll = streaming_prompt(MUTE, marker_refusal="party_follower")
finally:
    _chat_mod._marker_travel_refusal = _real_refusal

check("free character keeps the place marker", "**I am at <place>**" in _free)
check("follower has no place marker", "**I am at" not in _foll)
check("movement owner has no place marker", "**I am at" not in _lead)
check("new builder offers the movement verb", "- SetLocation:" in _lead)
check("new builder does not request pose/mood markers",
      "**I feel" not in _lead and "**I do" not in _lead)

for refusal, offered, marker in [('', MUTE, True), ('has_movement_verb', LEADER, False),
                                  ('party_follower', MUTE, False)]:
    text = streaming_prompt(offered, marker_refusal=refusal)
    check(f"respond travel marker gate: {refusal or 'free'}", ('**I am at' in text) == marker)

print(f"\n{len(RESULTS)} checks run.")
print("\n" + ("ALL CHECKS PASSED" if not FAILS
              else f"{len(FAILS)} FAILED: " + "; ".join(FAILS)))
sys.exit(1 if FAILS else 0)
