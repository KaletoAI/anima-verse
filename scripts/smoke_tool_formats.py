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

  (f) Copied placeholders before JSON are stripped in both parsers; plain
      JSON is unchanged. Bare angle placeholders are returned unchanged by both parsers,
      as before.
  (g) Bare ``ToolName: {json}`` lines (gemma-4 tool decisions, 2026-11-01:
      58 of 266 answers, all calls dropped — fails on 2d33fa51), format
      natural_en, offered tools ChangeOutfit/TalkTo/Act:
      - Rosi's real answer ``ChangeOutfit: {"equip":["Red lace bra"],
        "unequip_slots":["top"]}`` + an [INTENT:] line -> exactly that one
        call, input the JSON object verbatim;
      - two TalkTo lines with different messages -> two calls, in order;
      - ``- TalkTo: {...}`` (list bullet) -> one call;
      - ``GoToCharacter: {"partner": "Kai"}`` with GoToCharacter NOT offered,
        ``Act: she smiles`` (no JSON), ``Act: {broken`` (no object that
        parses), ``Act: ["x"]`` (not an object) and a mid-line
        ``I think Act: {"text": "x"}`` -> no call;
      - ``Use Act for: {"text": "wave"}`` still goes through the taught
        format -> one call, unchanged.

Usage:  ./.venv/bin/python scripts/smoke_tool_formats.py
  (h) The same without the colon (2026-11-03: Melanie's consent answer
      ``InteractWith {"partner": "Kai", "answer": "yes"}``, logged three
      times, never executed — fails on 988d0107), format tag, offered
      InteractWith/PropAction/Act: that answer -> one InteractWith call with
      the JSON verbatim; the contract's ``PropAction {"stop": true}`` -> one
      call; ``Act {broken``, ``Act ["x"]``, a call inside a sentence and a
      tool not offered (TalkTo) -> no call. strip_bare_json_calls leaves ""
      for the call alone, "Ja, gern." for speech plus a call line, and
      ``Act {broken`` unchanged.
  (i) ``ToolName for: {json}`` without the ``Use`` verb (2026-11-08: the
      temporary NPC Hannibal's rp_first tool step answered the logged text
      below, format natural_en; neither the taught format nor the
      ``Use X for:`` fallback nor (h) matched it, the party join was dropped
      silently — fails on 4dd5c7b0). Offered JoinParty/TalkTo/Act:
      - the logged answer (call line, blank line, [INTENT:] marker line) ->
        exactly ONE call ``("JoinParty", <the JSON object verbatim>)``;
      - ``JoinParty für: {...}`` and ``JoinParty fuer: {...}`` -> one call each;
      - ``JoinParty for: she agrees`` (no JSON), ``GoToCharacter for: {...}``
        (not offered) and ``JoinParty for {...}`` (no colon after "for") ->
        no call.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import tool_formats  # noqa: E402
from app.core.tool_formats import (_is_placeholder_input,  # noqa: E402
                                   build_tool_instruction, find_tool_calls,
                                   find_stream_tool_call)

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

print("(f) copied placeholder before JSON")
placeholder = "<JSON input exactly as the tool description specifies>"
for raw, want in (
    (placeholder + '{"name": "Ben", "message": "Hallo"}',
     '{"name": "Ben", "message": "Hallo"}'),
    (placeholder + ' \n []', '[]'),
    ('{"message": "Hallo"}', '{"message": "Hallo"}'),
    ("<only a placeholder>", "<only a placeholder>"),
):
    text = '<tool name="TalkTo">' + raw + '</tool>'
    check("full input " + raw, find_tool_calls("tag", text),
          [("TalkTo", want)])
    match = find_stream_tool_call("tag", text)
    check("stream input " + raw, match.group(2).strip() if match else None, want)
    check("stream span " + raw, match.span() if match else None, (0, len(text)))

print("(g) bare ToolName: {json} lines, offered tools only")
offered = {"ChangeOutfit": None, "TalkTo": None, "Act": None}
outfit = '{"equip":["Red lace bra"],"unequip_slots":["top"]}'
check("Rosi's answer", find_tool_calls(
    "natural_en", "ChangeOutfit: " + outfit
    + "\n[INTENT: 998d3b40 | Go to the inn | when=now | prio=3 | by=self]", offered),
    [("ChangeOutfit", outfit)])
check("two TalkTo lines", find_tool_calls(
    "natural_en", 'TalkTo: {"name": "Luisa", "message": "Komm!"}\n'
    'TalkTo: {"name": "Renate", "message": "Du auch!"}', offered),
    [("TalkTo", '{"name": "Luisa", "message": "Komm!"}'),
     ("TalkTo", '{"name": "Renate", "message": "Du auch!"}')])
check("bullet", find_tool_calls("natural_en", '- TalkTo: {"name": "Ben", "message": "Hi"}', offered),
      [("TalkTo", '{"name": "Ben", "message": "Hi"}')])
for text in ('GoToCharacter: {"partner": "Kai"}\n[INTENT_DONE: 7fd96d4d]',
             "Act: she smiles", "Act: {broken", 'Act: ["x"]', 'I think Act: {"text": "x"}'):
    check("no call: " + text.splitlines()[0], find_tool_calls("natural_en", text, offered), [])
check("taught format unchanged", find_tool_calls("natural_en", 'Use Act for: {"text": "wave"}', offered),
      [("Act", '{"text": "wave"}')])

print("(h) bare ToolName {json} without the colon, and the spoken rest")
offered_h = {"InteractWith": None, "PropAction": None, "Act": None}
consent = '{"partner": "Kai", "answer": "yes"}'
check("Melanie's consent", find_tool_calls("tag", "InteractWith " + consent, offered_h),
      [("InteractWith", consent)])
check("contract shape", find_tool_calls("tag", 'PropAction {"stop": true}', offered_h),
      [("PropAction", '{"stop": true}')])
for text in ("Act {broken", 'Act ["x"]', 'Gern, InteractWith {"partner": "Kai"}', 'TalkTo {"name": "Ben"}'):
    check("no call: " + text, find_tool_calls("tag", text, offered_h), [])
from app.core.tool_formats import strip_bare_json_calls
check("call only -> nothing said", strip_bare_json_calls("InteractWith " + consent, offered_h), "")
check("speech kept", strip_bare_json_calls("Ja, gern.\nInteractWith " + consent, offered_h).strip(),
      "Ja, gern.")
check("prose untouched", strip_bare_json_calls("Act {broken", offered_h), "Act {broken")

print("(i) ToolName for: {json} without the Use verb")
offered_i = {"JoinParty": None, "TalkTo": None, "Act": None}
join = ('{"target":"Lirien Edwinsdottir","destination":'
        '{"location_id":"e73591d5","room_id":"933ecd23"}}')
LOGGED_JOIN = ("JoinParty for: " + join + "\n\n[INTENT: Kellerbesuch | Wir gehen mit Lirien in den "
               "Keller des Gasthauses. | when=now | prio=3 | by=self]")
check("Hannibal's join", find_tool_calls("natural_en", LOGGED_JOIN, offered_i), [("JoinParty", join)])
for verb in ("für", "fuer"):
    check("JoinParty " + verb + ":", find_tool_calls(
        "natural_en", "JoinParty " + verb + ': {"target": "Kai"}', offered_i),
        [("JoinParty", '{"target": "Kai"}')])
for text in ("JoinParty for: she agrees", 'GoToCharacter for: {"partner": "Kai"}',
             'JoinParty for {"target": "Kai"}'):
    check("no call: " + text, find_tool_calls("natural_en", text, offered_i), [])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed"
      + (": " + ", ".join(FAILURES) if FAILURES else ""))
sys.exit(1 if FAILURES else 0)
