#!/usr/bin/env python3
"""Checks that the two thought prompts agree about what a character knows.

Usage:
    ./.venv/bin/python scripts/smoke_thought_template_parity.py

Pure: no server, no world, no LLM — it reads the two templates and renders
them from one hand-built context.

THE RULE

``chat/agent_thought.md`` (the regular AgentLoop turn) and
``chat/agent_thought_in_chat.md`` (the turn while a chat is running) are fed
by the SAME context dict (``app/core/thought_context.build_thought_context``,
picked in ``app/core/agent_loop.py``). Whatever the big template renders and
the in-chat one does not is knowledge the character LOSES the moment it is in
a conversation. That is a decision, never an oversight — so every omission is
listed here with its reason, and a new one fails this check until somebody
writes down why.

That is not theory: ``skill_context_blocks`` was missing in-chat, so a
character in a conversation did not know where it could go — measured 7935
characters (regular) against ~3300 (in-chat) in the user's world. Fixed
2026-09-18; this check is what keeps it fixed.

EXPECTATIONS, derived by hand from the in-chat template's own rule ("the chat
is the focus — only act if the conversation needs continuation; no unrelated
initiatives, no Instagram, no outfit changes"):

[1] Both templates render ``skill_context_blocks`` — what the character's
    skills offer (e.g. "Places you can go") is knowledge, not an initiative.
[2] Every variable the in-chat template omits is one of DELIBERATE below.
[3] Both templates render from the same context without an undefined variable
    (the environment runs StrictUndefined, so a forgotten one would raise).
[4] The blocks in-chat renders on top (the avatar's outfit, the recent chat)
    are the conversation itself — they exist only there, and the big template
    is not expected to carry them.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jinja2 import meta  # noqa: E402

from app.core.prompt_templates import _env, render  # noqa: E402

REGULAR = "chat/agent_thought.md"
IN_CHAT = "chat/agent_thought_in_chat.md"

# Blocks the in-chat turn deliberately does without, each with its reason.
DELIBERATE = {
    "action_instruction": "the in-chat turn has its own closing instruction (default: SKIP)",
    "general_task": "same — the standing task drives initiatives, which are off here",
    "outfit_decision_block": "no outfit changes while a conversation runs",
    "daily_schedule_block": "the schedule would start something unrelated",
    "arc_block": "story-arc initiative is not a conversation step",
    "assignments_block": "assignments would pull the character out of the chat",
    "retrospective_block": "reflecting on the day is not a conversation step",
    "tracker_block": "tracker-driven initiative, same reason",
    # Not a decision yet — the place offer is knowledge, like skill_context_blocks
    # was. Tracked as T2b in development_instructions/plan-bewegung-party-prompts.md.
    "activity_hint_block": "OPEN: the room's place offer — see plan T2b",
}

# Blocks that exist only in the in-chat turn (case [4]).
IN_CHAT_ONLY = {"outfit_avatar_block", "recent_chat_block"}

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(name)
        print(f"FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"ok   {name}")


def names(template):
    return meta.find_undeclared_variables(
        _env.parse(_env.loader.get_source(_env, template)[0]))


regular, in_chat = names(REGULAR), names(IN_CHAT)

# [1]
check("[1] regular renders skill_context_blocks", "skill_context_blocks" in regular, True)
check("[1] in-chat renders skill_context_blocks", "skill_context_blocks" in in_chat, True)

# [2]
missing = regular - in_chat
check("[2] every omission is declared", sorted(missing - set(DELIBERATE)), [])
check("[2] no stale entry in the list", sorted(set(DELIBERATE) - missing), [])

# [3]
ctx = {n: f"<{n}>" for n in (regular | in_chat)}
ctx.update(character_name="Rosi", alone_here=False, birthday_today=False)
for tpl in (REGULAR, IN_CHAT):
    out = render(tpl, **{k: v for k, v in ctx.items() if k in names(tpl)})
    check(f"[3] {tpl} renders", "<skill_context_blocks>" in out, True)

# [4]
check("[4] in-chat-only blocks", sorted(in_chat - regular), sorted(IN_CHAT_ONLY))

print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
sys.exit(1 if FAILURES else 0)
