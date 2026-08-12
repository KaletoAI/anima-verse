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
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


import app.core.dependencies as deps  # noqa: E402
deps.get_skill_manager = lambda: _StubManager()

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
for name, text in ALL_PROMPTS.items():
    has = "At most ONE **I am at ...** marker" in text
    want = name != "streaming/constrained"
    check(f"{name}: single-**I am at**-marker rule {'present' if want else 'absent'}",
          has == want)

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
      "always include your appearance: red hair, green eyes" in _with_photo)
check("appearance hint stays away without an image tool",
      "always include your appearance" not in _without)
_photog = build_tool_instruction("tag", [_T("TakePhoto")], photographer_mode=True,
                                 user_appearance="tall, blond")
check("photographer hint fires for the declared image tool",
      "You are a PHOTOGRAPHER" in _photog and "tall, blond" in _photog)

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

print(f"\n{len(RESULTS)} checks run.")
print("\n" + ("ALL CHECKS PASSED" if not FAILS
              else f"{len(FAILS)} FAILED: " + "; ".join(FAILS)))
sys.exit(1 if FAILS else 0)
