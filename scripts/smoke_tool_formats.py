#!/usr/bin/env python3
"""Smoke run for the tool-call parser (``app/core/tool_formats.py``).

No server, no world, no LLM: the parser is a pure function of the text.

Background (2026-09-12): a temporary NPC's ``Undress`` call was emitted by the
tool LLM as ``<tool name="Undress">[]</tool>`` and never executed — the
placeholder filter dropped every ``[...]`` input, and an empty ``[]`` is what
a model writes for a verb whose description says "No parameters needed" when
the prompt's own example brackets the input.

Hand-derived expectations:

  (a) ``_is_placeholder_input``: ``[]`` and ``{}`` are EMPTY inputs, not
      placeholders -> False. A bracketed phrase copied from an example
      (``[search query or question]``) and the literal instruction text
      (``your detailed input here``) stay placeholders -> True. An empty
      string is not a placeholder (there is nothing to judge) -> False.
  (b) The real tool-LLM answer from the log (trace f604deeb4e), whose last
      tag is cut off as ``</tool`` (no ``>``): the closed pattern yields
      Undress and StartIntimate; the unclosed SetActivity tag is recovered
      and its JSON trimmed to the balanced object -> exactly THREE calls in
      that order, Undress with input ``[]``.
  (c) ``<tool name="IgnoreDressCode">{}</tool>`` -> one call, input ``{}``.
  (d) A copied example ``<tool name="TakePhoto">your detailed input here</tool>``
      and ``<tool name="Search">[search query or question]</tool>`` -> no call.
  (e) ``build_tool_instruction("tag", ...)`` renders the example with the
      first tool's name and NO square bracket directly after the opening tag
      (``">[`` must not occur), and tells the model to write ``{}`` for a
      tool without input.

Usage:  ./.venv/bin/python scripts/smoke_tool_formats.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import tool_formats  # noqa: E402
from app.core.tool_formats import (_is_placeholder_input,  # noqa: E402
                                   build_tool_instruction, find_tool_calls)

# The appearance hint asks the skill manager which tools produce an image;
# that would boot the plugin tree against the real storage. Not needed here.
tool_formats._image_tool_names = lambda: frozenset()

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


print("(a) placeholder filter")
check("[] is not a placeholder", _is_placeholder_input("[]"), False)
check("{} is not a placeholder", _is_placeholder_input("{}"), False)
check("[] with whitespace", _is_placeholder_input(" [] \n"), False)
check("bracketed phrase is a placeholder",
      _is_placeholder_input("[search query or question]"), True)
check("instruction text is a placeholder",
      _is_placeholder_input("your detailed input here"), True)
check("empty string is not a placeholder", _is_placeholder_input(""), False)

print("(b) the logged answer with a cut-off last tag")
LOGGED = ('<tool name="Undress">[]</tool>\n'
          '<tool name="StartIntimate">{"partner": "Kai"}</tool>\n'
          '<tool name="SetActivity">{"pose": "standing", "detail": "nackt vor ihm stehen"}</tool')
calls = find_tool_calls("tag", LOGGED)
check("three calls", len(calls), 3)
check("order and inputs", calls, [
    ("Undress", "[]"),
    ("StartIntimate", '{"partner": "Kai"}'),
    ("SetActivity", '{"pose": "standing", "detail": "nackt vor ihm stehen"}'),
])

print("(c) empty JSON object")
check("{} call kept", find_tool_calls("tag", '<tool name="IgnoreDressCode">{}</tool>'),
      [("IgnoreDressCode", "{}")])

print("(d) copied examples stay filtered")
check("instruction text filtered",
      find_tool_calls("tag", '<tool name="TakePhoto">your detailed input here</tool>'), [])
check("bracketed phrase filtered",
      find_tool_calls("tag", '<tool name="Search">[search query or question]</tool>'), [])

print("(e) the rendered instruction teaches no brackets")
tools = [SimpleNamespace(name="ChangeOutfit", description="Change clothes."),
         SimpleNamespace(name="Undress", description="No parameters needed.")]
text = build_tool_instruction("tag", tools, model_name="")
check("example uses the first tool",
      '<tool name="ChangeOutfit">your detailed input here</tool>' in text, True)
check("no bracket right after an opening tag", '">[' in text, False)
check("empty-input rule present", '<tool name="ToolName">{}</tool>' in text, True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed"
      + (": " + ", ".join(FAILURES) if FAILURES else ""))
sys.exit(1 if FAILURES else 0)
