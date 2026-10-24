#!/usr/bin/env python3
"""Smoke: the tool-decision prompt names which package-declared states run.

Usage:
    ./.venv/bin/python scripts/smoke_tool_decision_state.py

Runs without a server, without a world DB and without network. Exit 0 = all
green, exit 1 = at least one check failed.

Background (2026-10-24): over 3005 logged tool decisions the prompt of the
tool LLM never said whether a state flag was set (0 of 3005 carried the
`prompt_when_set` line). The model ended states that were never started —
the end verb of one package runs a stat round of its own — and could not tell
a start from a running state. `flag_lifecycle.decision_state_lines` now gives
every flag whose clearing verb is OFFERED one line, set or not, and both
decision builders (`streaming.build_tool_decision_input`, the chat-turn
`chat_engine._rp_tool_decision_input`) carry it.

The flags, verbs and profile below are invented for the check; the expected
lines follow from the f-strings in `decision_state_lines` by hand.
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="tool-state-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="tool-state-storage-"))

from app.core import flag_lifecycle  # noqa: E402
from app.plugins.registry import FlagSpec  # noqa: E402

FAILURES = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = ""):
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: {detail}")
        FAILURES.append(name)


SPECS = [
    FlagSpec(flag="is_training", package_id="training", cleared_by="end_training",
             prompt_when_set="You are training — end it with {clear_tool}."),
    FlagSpec(flag="is_muddy", package_id="mud", cleared_by="wash_off"),
    FlagSpec(flag="is_hidden", package_id="hide", cleared_by="come_out",
             prompt_when_set="You hide."),
]
VERB_NAMES = {"end_training": "EndTraining", "wash_off": "WashOff",
              "come_out": "ComeOut"}
PROFILE = {"is_training": True, "is_muddy": False}


def main() -> int:
    import app.models.character as character_mod
    orig = (flag_lifecycle._specs, flag_lifecycle._clear_tool_name,
            character_mod.get_character_profile)
    flag_lifecycle._specs = lambda: SPECS
    flag_lifecycle._clear_tool_name = lambda spec: VERB_NAMES[spec.cleared_by]
    character_mod.get_character_profile = lambda name: dict(PROFILE)
    try:
        print("1. lines for offered clearing verbs only")
        lines = flag_lifecycle.decision_state_lines(
            "Demo", ["EndTraining", "WashOff", "TalkTo"])
        # ComeOut is not offered → its flag stays out: 2 lines, in spec order.
        check("two lines (ComeOut not offered)", len(lines) == 2, f"got {lines}")
        expected_set = (
            '- EndTraining: the state it ends IS active for Demo right now '
            '(the character\'s own cue: "You are training — end it with '
            'EndTraining."). Call EndTraining only when the text shows that '
            'state ending. The tool that starts this state would change '
            'nothing — it is already running.')
        check("set flag → ACTIVE line with the formatted cue",
              lines and lines[0] == expected_set, f"got {lines[:1]}")
        expected_unset = (
            "- WashOff: the state it ends is NOT active for Demo — there is "
            "nothing to end, never call WashOff this turn.")
        check("unset flag → NOT active line",
              len(lines) > 1 and lines[1] == expected_unset, f"got {lines[1:]}")

        print("2. nothing to say → empty")
        check("no offered clearing verb → []",
              flag_lifecycle.decision_state_lines("Demo", ["TalkTo"]) == [])
        check("no character → []",
              flag_lifecycle.decision_state_lines("", ["EndTraining"]) == [])

        print("3. the prompt block")
        from app.core.streaming import tool_state_note
        note = tool_state_note("Demo", {"EndTraining": None, "WashOff": None})
        check("block has the heading and both lines",
              note.startswith("   CURRENT STATES") and expected_set in note
              and expected_unset in note, f"got {note!r}")
        check("no offered verb → no block",
              tool_state_note("Demo", {"TalkTo": None}) == "")
    finally:
        (flag_lifecycle._specs, flag_lifecycle._clear_tool_name,
         character_mod.get_character_profile) = orig

    print("4. both decision builders carry it")
    from app.core import chat_engine
    from app.core.streaming import StreamingAgent
    src = inspect.getsource(StreamingAgent.build_tool_decision_input)
    # Two return branches (constrained + full) → two calls.
    check("streaming builder: both branches",
          src.count("tool_state_note(self.agent_name, _tools)") == 2,
          f"found {src.count('tool_state_note(')}")
    src = inspect.getsource(chat_engine._rp_tool_decision_input)
    check("chat-turn builder", "tool_state_note(agent_name, tools_dict" in src)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} of {CHECKS} checks — {', '.join(FAILURES)}")
        return 1
    print(f"OK: {CHECKS} checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
