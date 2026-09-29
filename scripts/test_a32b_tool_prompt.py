#!/usr/bin/env python3
"""A3.2b — checks the rp_first tool-decision prompt.

Usage:
    ./.venv/bin/python scripts/test_a32b_tool_prompt.py

Runs WITHOUT the server and WITHOUT touching world.db: the skill manager and
the world's location list are replaced by synthetic stubs, so every expected
value below is derived by hand from the fixture, not from live data.

Fixture (hand-built): a character with the tools
    ChangeOutfit (SINGLETON), TakePhoto, SetLocation (SINGLETON),
    JoinParty, TalkTo (DELIVERS_SPEECH), SendMessage (DELIVERS_SPEECH +
    REMOTE_COMM)
and the same character as a PARTY FOLLOWER, i.e. without SetLocation
(party_engine: only the leader moves).

Expectations, derived by hand:
  1. Follower prompt (streaming, thought + chat, and chat_engine) contains no
     "→ SetLocation" mapping line; the leader prompt does.
  2. Neither path mentions the dead names ImageGenerator / SetPose anywhere.
  3. streaming and chat_engine produce the SAME mapping lines for the same
     tools_dict (one source: action_mapping_lines).
  4. Both paths carry the two anti-hallucination rules (speech verbatim / no
     other figure's lines, at most one call per singleton tool) and the
     single-marker rule.
  5. The room-speech note names TalkTo, never the remote verb SendMessage,
     and disappears when the character has no room-speech verb.
  6. Location catalogue: 6 synthetic locations with 3 distinct display names
     produce exactly 3 entries in "Available locations:".
  7. The tool-instruction system prompt (build_tool_instruction) names no tool
     of its own any more, and its appearance hint is driven by the declared
     image tool (PROGRESS_TYPE "image") instead of the vanished name
     "ImageGenerator".
  8. In-person suppression: with suppress_move_in_conversation / medium
     "in_person" the SUPPRESS_IN_PERSON verb (SetLocation) leaves the mapping
     of BOTH paths — it would be discarded on execution anyway.
     B3 (2026-09-29): the SAME holds for the SYSTEM part of the room path
     (chat_engine._build_rp_tool_system, in_person=True): neither SetLocation
     nor GoToCharacter (both SUPPRESS_IN_PERSON in the fixture) appears — not
     in the tool list, not in "Available tools", not in a usage example line
     (the real SkillManager.get_agent_usage_instructions with ``exclude``);
     without in_person both are there.
     B4 (2026-09-29): the respond decision prompt carries the streaming twin's
     guard ("NEVER call a tool because of what the user said"), scoped to
     TOOLS; the tool-decision system part (build_tool_instruction with
     for_tool_decision=True) has no "Whenever the user asks" bullet, the
     chat-model default still has it. The **I do** placeholder is third
     person, and the current pose (stubbed "sitting: reads a letter") is
     shown with the keep rule in BOTH decision prompts.
  7b. Names instead of role words (B4): the image hint asks to name every
     person ("name yourself and every other person in it by name") and keeps
     the appearance as reference; the photographer hint names the subjects
     ("by their NAME").
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Throwaway storage BEFORE any app import: every world read below is stubbed,
# but a stub that is missed must hit an empty temp world, never a real one.
from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="a32b_"))

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
        self.description = f"{name} does something"

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
                                     check_limits=True, exclude=frozenset()):
        from app.skills.skill_manager import SkillManager

        class _Holder:
            def _get_agent_skills(self, name, check_limits=True):
                return list(_SKILLS)

        return SkillManager.get_agent_usage_instructions(
            _Holder(), character_name, format_name, check_limits=check_limits,
            exclude=exclude)


import app.core.dependencies as deps  # noqa: E402
deps.get_skill_manager = lambda: _StubManager()

# The current pose is a world read — stubbed to a fixed value so both
# decision prompts can be checked for it (B7).
import app.core.streaming as _streaming_mod  # noqa: E402
_streaming_mod.current_pose_text = lambda name: "sitting: reads a letter"

from app.core.streaming import (StreamingAgent, action_mapping_lines)  # noqa: E402
from app.core.chat_engine import _rp_tool_decision_input  # noqa: E402

LEADER = {n: (lambda x: "") for n in
          ["ChangeOutfit", "TakePhoto", "SetLocation", "JoinParty", "TalkTo", "SendMessage"]}
FOLLOWER = {k: v for k, v in LEADER.items() if k != "SetLocation"}
MUTE = {"ChangeOutfit": (lambda x: ""), "TakePhoto": (lambda x: "")}


def streaming_prompt(tools, *, thought=False, constrained=False, in_person=False):
    st = StreamingAgent(
        llm=None, tool_format="tag", tools_dict=tools, mode="rp_first",
        log_task="thought" if thought else "chat_stream",
        constrained_tools=constrained,
        suppress_move_in_conversation=in_person)
    return st.build_tool_decision_input("Hi", "She walks to the kitchen.")


print("\n1) Party follower loses the SetLocation mapping line")
for label, thought, constrained in [("thought", True, False),
                                    ("chat", False, False),
                                    ("constrained", False, True)]:
    lead = streaming_prompt(LEADER, thought=thought, constrained=constrained)
    foll = streaming_prompt(FOLLOWER, thought=thought, constrained=constrained)
    check(f"streaming/{label}: leader HAS '→ SetLocation'", "→ SetLocation" in lead)
    check(f"streaming/{label}: follower has NO '→ SetLocation'", "→ SetLocation" not in foll)
ce_lead = _rp_tool_decision_input("Hi", "She walks to the kitchen.", LEADER)
ce_foll = _rp_tool_decision_input("Hi", "She walks to the kitchen.", FOLLOWER)
check("chat_engine: leader HAS '→ SetLocation'", "→ SetLocation" in ce_lead)
check("chat_engine: follower has NO '→ SetLocation'", "→ SetLocation" not in ce_foll)

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

print("\n3) One source — identical mapping lines in both paths")
lines = action_mapping_lines(LEADER)
check("streaming/chat contains the mapping block verbatim", lines in ALL_PROMPTS["streaming/chat"])
check("chat_engine contains the mapping block verbatim", lines in ce_lead)
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
_ip_chat_engine = _rp_tool_decision_input("Hi", "She walks to the kitchen.", LEADER,
                                          in_person=True)
check("streaming/in-person: no '→ SetLocation'", "→ SetLocation" not in _ip_stream)
check("streaming/in-person thought: no '→ SetLocation'", "→ SetLocation" not in _ip_thought)
check("chat_engine/in-person: no '→ SetLocation'", "→ SetLocation" not in _ip_chat_engine)
check("streaming/in-person: singleton rule no longer lists SetLocation",
      "SetLocation" not in _ip_stream)
check("chat_engine/in-person: singleton rule no longer lists SetLocation",
      "SetLocation" not in _ip_chat_engine)
check("streaming/in-person keeps the other 5 tools",
      all(f"→ {n}" in _ip_stream for n in
          ["ChangeOutfit", "TakePhoto", "JoinParty", "TalkTo", "SendMessage"]))
check("not-in-person is unchanged", "→ SetLocation" in streaming_prompt(LEADER))

# B3: the SYSTEM part of the room path, with every world read stubbed.
import app.models.character as _mchar  # noqa: E402
import app.models.character_template as _mtpl  # noqa: E402
import app.models.world as _mworld  # noqa: E402
import app.models.account as _macc  # noqa: E402
import app.core.outfit_renderer as _outfit  # noqa: E402
_mchar.get_character_appearance = lambda name: "red hair"
_mchar.get_character_current_location = lambda name, **kw: ""
_mchar.get_character_current_room = lambda name, **kw: ""
_mchar.get_character_language_instruction = lambda name: ""
_mtpl.is_roleplay_character = lambda name: True
_mworld.list_locations_for_character = lambda name: []
_macc.get_active_character = lambda: ""
_outfit.render_outfit = lambda **kw: {"full": "a coat"}
from app.core.chat_engine import _build_rp_tool_system  # noqa: E402

_ALL_SPECS = [_T(sk.name) for sk in _SKILLS]
_sys_ip = _build_rp_tool_system("demo_one", _ALL_SPECS, "tag", "", "",
                                in_person=True)
_sys_away = _build_rp_tool_system("demo_one", _ALL_SPECS, "tag", "", "",
                                  in_person=False)
for _mv in ("SetLocation", "GoToCharacter"):
    check(f"system part in-person: no '{_mv}' anywhere", _mv not in _sys_ip)
    check(f"system part in-person: no usage line of {_mv}",
          f"USAGE {_mv}:" not in _sys_ip)
    check(f"system part not in person: '{_mv}' listed with its usage line",
          f"- {_mv}:" in _sys_away and f"USAGE {_mv}:" in _sys_away)
check("system part in-person keeps the other tools + their usage lines",
      all(f"- {n}:" in _sys_ip and f"USAGE {n}:" in _sys_ip for n in
          ["ChangeOutfit", "TakePhoto", "JoinParty", "TalkTo", "SendMessage"]))

# B4: the guard and the missing "user asks" bullet.
_GUARD = "NEVER call a tool because of what the user said or asked for"
check("respond decision carries the guard", _GUARD in _ip_chat_engine)
check("respond decision scopes the guard to TOOLS",
      "Base every TOOL call ONLY on what the CHARACTER actually did" in _ip_chat_engine)
check("streaming decision keeps its guard", _GUARD in _ip_stream)
_USER_ASKS = "Whenever the user asks for something"
check("tool-decision system part has no 'user asks' bullet",
      _USER_ASKS not in _sys_ip and _USER_ASKS not in _sys_away)
check("build_tool_instruction(for_tool_decision=True) drops the bullet",
      _USER_ASKS not in build_tool_instruction("tag", [_T("TakePhoto")],
                                               for_tool_decision=True))
check("the chat-model default keeps the bullet",
      _USER_ASKS in build_tool_instruction("tag", [_T("TakePhoto")]))
check("tool-decision instruction keeps the rest of the default",
      "Only the tools listed under AVAILABLE TOOLS above exist" in
      build_tool_instruction("tag", [_T("TakePhoto")], for_tool_decision=True))

# B7: third-person placeholder + current pose with the keep rule.
_PH = "<what a bystander sees, 2-6 words, third person — never I/my/ich/mein>"
for _nm, _txt in (("chat_engine", _ip_chat_engine), ("streaming", _ip_stream)):
    check(f"{_nm}: third-person **I do** placeholder", _PH in _txt)
    check(f"{_nm}: old first-person placeholder gone",
          "<what you do, 2-6 words>" not in _txt)
    check(f"{_nm}: current pose shown", "Current pose: sitting: reads a letter." in _txt)
    check(f"{_nm}: keep rule", "a glance, a gesture, looking at or holding "
          "something, or thinking is NOT a new pose" in _txt)

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
    _free = streaming_prompt(MUTE)
    _chat_mod._marker_travel_refusal = lambda name: "party_follower"
    _foll = streaming_prompt(MUTE)
finally:
    _chat_mod._marker_travel_refusal = _real_refusal

check("owner of the verb is sent to the tool", "CALL THAT TOOL" in _lead)
check("owner of the verb is not ASKED for the marker",
      "emit **I am at <room or place>**" not in _lead)
check("a character with no other way keeps the marker",
      "emit **I am at <room or place>**" in _free)
check("...and is told a place is a walk", "starts a walk" in _free)
check("...and is not sent to a tool it does not have", "CALL THAT TOOL" not in _free)
check("a follower is taught neither way",
      "CALL THAT TOOL" not in _foll and "**I am at" not in _foll)

# The room path (chat_engine) asks the same rule once it is given the name.
try:
    _chat_mod._marker_travel_refusal = lambda name: ""
    _ce_free = _rp_tool_decision_input("Hi", "She walks to the kitchen.", MUTE,
                                       agent_name="demo_one")
    _chat_mod._marker_travel_refusal = lambda name: "has_movement_verb"
    _ce_verb = _rp_tool_decision_input("Hi", "She walks to the kitchen.", LEADER,
                                       agent_name="demo_one")
    _chat_mod._marker_travel_refusal = lambda name: "party_follower"
    _ce_foll = _rp_tool_decision_input("Hi", "She walks to the kitchen.", MUTE,
                                       agent_name="demo_one")
finally:
    _chat_mod._marker_travel_refusal = _real_refusal
check("room path: no other way -> the marker", "**I am at <room or place>**" in _ce_free)
check("room path: owner of the verb -> the verb", "call SetLocation" in _ce_verb)
check("room path: owner of the verb is not asked for the marker",
      "**I am at <room or place>**" not in _ce_verb)
check("room path: a follower is taught neither way",
      "**I am at" not in _ce_foll and "call SetLocation" not in _ce_foll)
# No name: the builder cannot ask the rule, so it never ASKS for the marker.
# With the verb in hand it still points at the verb — that is the safe half.
_ce_anon = _rp_tool_decision_input("Hi", "x", LEADER)
check("room path without a name does not ask for the marker",
      "**I am at <room or place>**" not in _ce_anon)
check("room path without a name still points at the verb",
      "call SetLocation" in _ce_anon)
check("room path without a name and without the verb promises nothing",
      "**I am at" not in _rp_tool_decision_input("Hi", "x", MUTE))

print(f"\n{len(RESULTS)} checks run.")
print("\n" + ("ALL CHECKS PASSED" if not FAILS
              else f"{len(FAILS)} FAILED: " + "; ".join(FAILS)))
sys.exit(1 if FAILS else 0)
