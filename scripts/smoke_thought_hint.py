#!/usr/bin/env python3
"""Smoke: a bump hint reaches the thought turn — in the USER turn.

Usage:  ./.venv/bin/python scripts/smoke_thought_hint.py

Background — the bug this pins down: ``AgentLoop.bump(name, hint=...)`` wakes
a character with a hint ("Kira asks you to dance together ... call
InteractWith ...", a party invitation, a scheduled message). The agent loop
hands it to ``ThoughtRunner.run_thought_turn`` as ``context_hint`` together
with ``system_prompt_override``; the hint was only prepended to the system
prompt in the branch WITHOUT an override, so on the agent-loop path it was
merely logged — the character never learned it had been asked.

The fix puts the hint into the synthetic user turn (``thought_user_input``),
behind the history, never into the system prompt: the system prompt must stay
byte-stable for the prompt cache (CHAT_PROMPTS.md § 1).

No server, no LLM. Storage is a throwaway dir initialised before any import
that could reach a world DB.

EXPECTATIONS, DERIVED BY HAND
1  thought_user_input("") and thought_user_input("   ") are exactly
   THOUGHT_TRIGGER_DEFAULT — an empty/blank hint adds nothing.
2  thought_user_input("Kira asks you to dance together.") starts with
   "# Triggered thought\\nKira asks you to dance together.\\n\\n" and ends with
   THOUGHT_TRIGGER_DEFAULT (header line, the stripped hint, a blank line,
   then the unchanged default trigger).
3  STRUCTURAL: the literal "# Triggered thought" occurs exactly ONCE in
   app/core/thoughts.py (inside the helper); run_thought_turn's source
   contains "thought_user_input(context_hint)" and no longer contains
   'system_prompt = f"# Triggered'.
   Why structural: whether the hint lands in the user turn of the real
   thought turn could only be observed by running run_thought_turn, which
   needs a live LLM (streaming agent, tool LLM, queue). Reading the source
   pins the wiring instead — the helper is covered by 1+2, the call site and
   the removal of the system-prompt prepend by 3.
"""
import inspect
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_thought_hint_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))

import app.core.thoughts as th  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


DEFAULT = getattr(th, "THOUGHT_TRIGGER_DEFAULT", None)
helper = getattr(th, "thought_user_input", None)

print("1/2 thought_user_input")
check("THOUGHT_TRIGGER_DEFAULT exists", isinstance(DEFAULT, str) and bool(DEFAULT), True)
check("thought_user_input exists", callable(helper), True)
if callable(helper) and isinstance(DEFAULT, str):
    check("empty hint -> default", helper(""), DEFAULT)
    check("blank hint -> default", helper("   "), DEFAULT)
    out = helper("Kira asks you to dance together.")
    check("hint: header + hint + blank line first",
          out.startswith("# Triggered thought\nKira asks you to dance together.\n\n"), True)
    check("hint: ends with the default trigger", out.endswith(DEFAULT), True)

print("3 structural (source)")
src = (ROOT / "app" / "core" / "thoughts.py").read_text(encoding="utf-8")
check('"# Triggered thought" occurs exactly once', src.count("# Triggered thought"), 1)
turn_src = inspect.getsource(th.ThoughtRunner.run_thought_turn)
check("run_thought_turn calls thought_user_input(context_hint)",
      "thought_user_input(context_hint)" in turn_src, True)
check("run_thought_turn no longer prepends the hint to the system prompt",
      'system_prompt = f"# Triggered' in turn_src, False)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} — {', '.join(FAILS)}")
    sys.exit(1)
print("OK")
