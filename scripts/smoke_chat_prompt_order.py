#!/usr/bin/env python3
"""Checks the cache order of the chat prompt: system prompt vs. scene state.

Usage:
    ./.venv/bin/python scripts/smoke_chat_prompt_order.py

Pure: no server, no world, no LLM. It reads the two templates, the render
call in routes/chat.py (by AST), and runs the two pure helpers.

THE CONTRACT (header of shared/templates/llm/chat/chat_stream.md)

A backend caches a prompt by its prefix; one changed byte makes everything
behind it expensive, the history included. So the chat prompt is split:
chat/chat_stream.md is the system prompt and holds only what stays put
between turns; chat/chat_moment.md is the scene state of this turn and goes
on the last user turn, BEHIND the history. Derived expectations:

[1] The per-turn blocks, as decided with the user on 2026-09-17 (plan
    analyse-prompt-caching-gespraeche.md § 8, relationships included):
        situation_block, self_state_lines, condition_reminder, moment_notes,
        self_wearing, partner_wearing, partner_state_lines,
        present_characters, present_details, inventory_carrying_section,
        inventory_room_section, focused_items, known_activities,
        events_section, assignment_section, recent_activity_section,
        memory_section, relationships_section, reply_shape_section,
        addressed_to_me, addressed_names, winding_down, respond_opportunity
    None of them is referenced by chat_stream.md; every one of them is
    referenced by chat_moment.md.

[2] The same list against the CODE: the keyword arguments of
    render("chat/chat_stream.md", ...) in routes/chat.py contain none of
    them — a template that ignores a variable would not catch a builder
    that still passes one "for later".

[3] Order inside the system prompt, rarest change first. With every block
    filled by a sentinel, the sentinels appear in exactly this order:
        WORLD_SETUP < CONTEXT: < === SCENE STATE === < === GROUP SCENE ===
        < === REPLY LENGTH === < Location change < Activity change
        < Plans & tasks < LANG < === YOUR IDENTITY === < TOOLS < SECRETS
        < LONGTERM < DAILY < HISTSUM < SCENES

[4] The world part is character-independent. Render twice with every
    character-bound block different (name, language, identity, tools,
    secrets, summaries) and every world block equal: the two renders share
    a common prefix that reaches at least up to the start of render A's
    language sentinel — everything before the language line is the part
    all characters of a world share in the cache.

[5] Order inside the scene state, the moment's most binding facts last:
        [SCENE STATE < SITUATION < SELFSTATE < NOTE < PRESENT < PLACES
        < MEMORY < RELATIONS < "spoke to YOU directly" < This moment:
        < SKIP < [END OF SCENE STATE]
    (winding_down on: its SKIP line is the last rule before the end marker.)

[6] attach_moment(messages, moment):
    a) last message is a user turn "Kai: Hallo", moment "M"
       -> last content "Kai: Hallo\\n\\nM"; the input dict is NOT modified
    b) last message is an assistant turn -> a new user turn "M" is appended
    c) empty list -> [{"role": "user", "content": "M"}]
    d) empty moment -> an equal copy, not the same list object

[8] The thought turn's tool prompt (app/core/thoughts.py) follows the same
    contract: its ~17 KB tool-instruction block is stable, the clock is not.
    Reading the ``_ctx_parts.append(...)`` calls in source order, the part
    naming the standing task comes first, then ``tool_instr_block``, and the
    clock ("Uhrzeit") only after it — a clock in front of the tool block cost
    123 of 297 measured pairs their whole cacheable prefix (~96 tokens left).

[7] build_prompt_section(volatile=...) with four fields in template order
        a: plain                                   -> stable
        b: prompt_volatile true                    -> volatile
        c: store status_effects                    -> volatile (default rule)
        d: store status_effects, prompt_volatile false -> stable (flag wins)
    volatile=False -> ["A: 1", "D: 4"]; volatile=True -> ["B: 2", "C: 3"];
    volatile=None  -> all four, in template order.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jinja2 import meta  # noqa: E402

from app.core.prompt_templates import _env, render  # noqa: E402

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")
        print(f"FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"ok   {name}")


PER_TURN = {
    "situation_block", "self_state_lines", "condition_reminder", "moment_notes",
    "self_wearing", "partner_wearing", "partner_state_lines",
    "present_characters", "present_details", "inventory_carrying_section",
    "inventory_room_section", "focused_items", "known_activities",
    "events_section", "assignment_section", "recent_activity_section",
    "memory_section", "relationships_section", "reply_shape_section",
    "addressed_to_me", "addressed_names", "winding_down", "respond_opportunity",
}


def _names(tpl):
    return meta.find_undeclared_variables(
        _env.parse(_env.loader.get_source(_env, tpl)[0]))


STREAM = _names("chat/chat_stream.md")
MOMENT = _names("chat/chat_moment.md")

# [1]
check("[1] system prompt references no per-turn block",
      sorted(PER_TURN & STREAM), [])
check("[1] scene state references every per-turn block",
      sorted(PER_TURN - MOMENT), [])

# [2]
tree = ast.parse((ROOT / "app/routes/chat.py").read_text())
passed = None
for node in ast.walk(tree):
    if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "render"
            and node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "chat/chat_stream.md"):
        passed = {kw.arg for kw in node.keywords}
check("[2] render call for chat_stream.md found", passed is not None, True)
check("[2] builder passes no per-turn block to the system prompt",
      sorted(PER_TURN & (passed or set())), [])


# [3] / [4]
def _stream(**over):
    ctx = dict(
        world_setup="WORLD_SETUP", medium="in_person", partner_mode="room",
        tools_enabled=False, mood_tracking_enabled=False,
        known_locations="LOCS", activity_marker_enabled=True,
        intent_tracking_enabled=True, lang_instruction="LANG_A",
        character_name="Rosi", char_lines=["IDENT_A"], partner_name="",
        partner_lines=[], tool_instructions="TOOLS_A", secrets_section="SECRETS_A",
        longterm_section="LONGTERM_A", daily_summary_section="DAILY_A",
        history_summary_block="HISTSUM_A", scenes_block="SCENES_A")
    ctx.update(over)
    return render("chat/chat_stream.md", **{k: v for k, v in ctx.items() if k in STREAM})


a = _stream()
order = ["WORLD_SETUP", "CONTEXT:", "=== SCENE STATE ===", "=== GROUP SCENE ===",
         "=== REPLY LENGTH ===", "Location change", "Activity change",
         "Plans & tasks", "LANG_A", "=== YOUR IDENTITY ===", "TOOLS_A",
         "SECRETS_A", "LONGTERM_A", "DAILY_A", "HISTSUM_A", "SCENES_A"]
pos = [a.find(s) for s in order]
check("[3] every system sentinel present", [s for s, p in zip(order, pos) if p < 0], [])
check("[3] system order", pos == sorted(pos), True)

b = _stream(character_name="Karl", lang_instruction="LANG_B", char_lines=["IDENT_B"],
            tool_instructions="TOOLS_B", secrets_section="SECRETS_B",
            longterm_section="LONGTERM_B", daily_summary_section="DAILY_B",
            history_summary_block="HISTSUM_B", scenes_block="SCENES_B")
common = 0
while common < min(len(a), len(b)) and a[common] == b[common]:
    common += 1
check("[4] world part shared up to the language line",
      common >= a.find("LANG_A"), True)


# [5]
def _moment(**over):
    ctx = dict(
        character_name="Rosi", partner_mode="room", partner_name="Kai",
        partner_state_lines=[], present_characters="Kai, Liesa",
        present_details="PRESENT", situation_block="SITUATION",
        self_state_lines=["SELFSTATE"], condition_reminder="", moment_notes=["NOTE"],
        self_wearing="", partner_wearing="", inventory_carrying_section="",
        inventory_room_section="", focused_items="", known_activities="PLACES",
        events_section="", assignment_section="", recent_activity_section="",
        memory_section="MEMORY", relationships_section="RELATIONS",
        reply_shape_section="- brief", addressed_to_me=True, addressed_names="",
        respond_opportunity=False, winding_down=True)
    ctx.update(over)
    return render("chat/chat_moment.md", **{k: v for k, v in ctx.items() if k in MOMENT})


m = _moment()
morder = ["[SCENE STATE", "SITUATION", "SELFSTATE", "NOTE", "PRESENT", "PLACES",
          "MEMORY", "RELATIONS", "spoke to YOU directly", "This moment:",
          "reply with exactly: SKIP", "[END OF SCENE STATE]"]
mpos = [m.find(s) for s in morder]
check("[5] every scene-state sentinel present", [s for s, p in zip(morder, mpos) if p < 0], [])
check("[5] scene-state order", mpos == sorted(mpos), True)

# [6]
from app.core.chat_engine import attach_moment  # noqa: E402

hist = [{"role": "assistant", "content": "Hallo"}, {"role": "user", "content": "Kai: Hallo"}]
out = attach_moment(hist, "M")
check("[6a] appended to last user turn", out[-1]["content"], "Kai: Hallo\n\nM")
check("[6a] input dict untouched", hist[-1]["content"], "Kai: Hallo")
check("[6b] after assistant -> own user turn",
      attach_moment([{"role": "assistant", "content": "x"}], "M")[-1],
      {"role": "user", "content": "M"})
check("[6c] empty list", attach_moment([], "M"), [{"role": "user", "content": "M"}])
same = attach_moment(hist, "")
check("[6d] empty moment -> equal copy", (same == hist, same is hist), (True, False))

# [7]
from app.models.character_template import build_prompt_section  # noqa: E402

tpl = {"sections": [{"fields": [
    {"key": "a", "prompt_label": "A", "in_prompt": True},
    {"key": "b", "prompt_label": "B", "in_prompt": True, "prompt_volatile": True},
    {"key": "c", "prompt_label": "C", "in_prompt": True, "store": "status_effects"},
    {"key": "d", "prompt_label": "D", "in_prompt": True, "store": "status_effects",
     "prompt_volatile": False},
]}]}
data = {"a": "1", "b": "2", "c": "3", "d": "4"}
check("[7] stable", build_prompt_section(tpl, data, volatile=False), ["A: 1", "D: 4"])
check("[7] volatile", build_prompt_section(tpl, data, volatile=True), ["B: 2", "C: 3"])
check("[7] all", build_prompt_section(tpl, data), ["A: 1", "B: 2", "C: 3", "D: 4"])

# [8]
thought_src = (ROOT / "app/core/thoughts.py").read_text()
thought_tree = ast.parse(thought_src)
# A part is often assembled in a variable first, so a bare name is resolved to
# the source of its assignment — otherwise "Uhrzeit" hides behind `_situation`.
assigned = {}
for n in ast.walk(thought_tree):
    if (isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id not in assigned):
        assigned[n.targets[0].id] = ast.get_source_segment(thought_src, n.value) or ""
appends = [ast.get_source_segment(thought_src, n.value.args[0]) or ""
           for n in ast.walk(thought_tree)
           if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
           and getattr(n.value.func, "attr", "") == "append"
           and getattr(getattr(n.value.func, "value", None), "id", "") == "_ctx_parts"
           and n.value.args]
resolved = [assigned.get(s.strip(), s) for s in appends]
task_at = next((i for i, s in enumerate(resolved) if "Aufgabe" in s), -1)
tools_at = next((i for i, s in enumerate(appends) if s.strip() == "tool_instr_block"), -1)
clock_at = next((i for i, s in enumerate(resolved) if "Uhrzeit" in s), -1)
check("[8] thought tool prompt: all three parts found",
      [x >= 0 for x in (task_at, tools_at, clock_at)], [True, True, True])
check("[8] standing task before the tool block", task_at < tools_at, True)
check("[8] clock behind the tool block", clock_at > tools_at, True)

print(f"\n{'FAILED: ' + str(len(FAILURES)) if FAILURES else 'all checks passed'}")
sys.exit(1 if FAILURES else 0)
