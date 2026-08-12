#!/usr/bin/env python3
"""Checks the A2 fact-supplier templates against their production call sites.

Usage:
    ./.venv/bin/python scripts/test_a2_templates.py

Needs neither the server nor a world DB — `prompt_templates` resolves
`shared/templates/llm/` relative to the repo root and nothing else.

WHY these expectations (derived by hand from the call sites, not recorded
from current output):

1. StrictUndefined. Every template is rendered with EXACTLY the kwargs its
   production call site passes — `memory_service.py:85` (extraction_memory),
   `routes/chat.py:2007` (extraction_chat_state), `memory_service.py:697/846/937`
   (daily/weekly/monthly), `history_manager.py:447/1003` (history_summary/today).
   A missing placeholder raises; a template that renders here cannot raise in
   production for the same call site.

2. `lang_instruction` reaches the output. Weekly and monthly were the only two
   summary templates without it — 33/33 weekly and 10/10 monthly DB entries came
   out English while 165/165 daily entries of the same characters were German
   (A2.3 report). The instruction is only effective if it lands in the USER turn
   (the system turn is generic), so that is where it is asserted.

3. Non-empty `## system`. `consolidation_today` and `consolidation_history_summary`
   shipped an empty system section, i.e. the two highest-frequency summary
   branches ran with no system prompt at all. Empty is now a regression.

4. The `extraction_chat_state` reply schema stays syntactically valid JSON in
   ALL 8 flag combinations of (is_avatar, stats_enabled, outfit_locked,
   piece_list). The schema line is a JSON *shape* with placeholder tokens, so
   the check substitutes the three known tokens with valid literals and then
   parses. Comma logic is what actually breaks here: with `piece_list` empty,
   the `"removed"` key must be gone AND the comma before it must be gone too —
   `{"pose": "x", }` would parse in no JSON parser.

5. `"removed"` appears if and only if the character has equipped pieces and the
   outfit is not locked. Before the fix, 147 of 695 calls (21 %) rendered the
   outfit block with an empty catalogue plus the instruction to pick from it.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.prompt_templates import render_task  # noqa: E402

DE = "\nWrite the summary in German."

# task -> kwargs exactly as the production call site passes them
CALL_SITES = {
    "extraction_memory": dict(
        speaker_a="Alpha", speaker_b="Beta", text_a="a", text_b="b",
        existing_summary="(none yet)", commitments_block="",
        lang_instruction="\nWrite the memory contents in German."),
    "extraction_thought": dict(
        speaker_b="Beta", text_b="b", existing_summary="(none yet)",
        commitments_block="",
        lang_instruction="\nWrite the memory contents in German."),
    "consolidation_daily": dict(
        day_str="2026-08-03", character_name="Beta", existing="",
        lang_instruction=DE, contents="- x", thoughts_of_day=""),
    "consolidation_weekly": dict(
        week_key="2026-W31", character_name="Beta",
        lang_instruction=DE, entries_text="- 2026-08-03: x"),
    "consolidation_monthly": dict(
        month_key="2026-08", character_name="Beta",
        lang_instruction=DE, entries_text="- 2026-W31: x"),
    "consolidation_today": dict(
        speaker_a="Alpha", speaker_b="Beta", lang_instruction=DE,
        history_text="Alpha: hi"),
    "consolidation_history_summary": dict(
        speaker_a="Alpha", speaker_b="Beta", lang_instruction=DE,
        history_text="Alpha: hi"),
}

failures = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        failures.append(name)


print("1) every template renders with its call-site kwargs (StrictUndefined)")
rendered = {}
for task, kwargs in CALL_SITES.items():
    try:
        rendered[task] = render_task(task, **kwargs)
        check(task, True)
    except Exception as e:
        check(task, False, f"{type(e).__name__}: {e}")

print("2) lang_instruction lands in the user turn")
for task in ("consolidation_daily", "consolidation_weekly",
             "consolidation_monthly", "consolidation_today",
             "consolidation_history_summary"):
    if task in rendered:
        check(task, DE.strip() in rendered[task][1], "instruction missing")
for _t in ("extraction_memory", "extraction_thought"):
    if _t in rendered:
        check(_t,
              "Write the memory contents in German." in rendered[_t][1],
              "instruction missing")
if False:
    check("extraction_memory",
          "Write the memory contents in German." in rendered["extraction_memory"][1],
          "instruction missing")

print("3) system section is not empty")
for task in ("consolidation_today", "consolidation_history_summary",
             "consolidation_daily", "consolidation_weekly",
             "consolidation_monthly", "extraction_memory",
             "extraction_thought"):
    if task in rendered:
        check(task, len(rendered[task][0].strip()) > 40,
              f"len={len(rendered[task][0].strip())}")

print("4) name anchor present (the 'her brother' symptom)")
ANCHOR = "never only by role"
for task in ("extraction_memory", "extraction_thought",
             "consolidation_daily", "consolidation_weekly",
             "consolidation_monthly"):
    if task in rendered:
        check(task, ANCHOR in rendered[task][1], "anchor sentence missing")
for task in ("consolidation_today", "consolidation_history_summary"):
    if task in rendered:
        check(task, "never only a role" in rendered[task][1],
              "third-party anchor missing")

print("5) extraction_chat_state schema is valid JSON in all 8 flag combinations")
SUBST = [
    ('"<short phrase>"', '"standing"'),
    ('{"<value>": <delta>, ...}', '{"stamina": -5}'),
    ('["<exact piece name>", ...]', '["shirt"]'),
]
for is_avatar in (False, True):
    for stats_enabled in (False, True):
        for locked in (False, True):
            for pieces in ("", "- shirt\n- boots"):
                label = (f"avatar={int(is_avatar)} stats={int(stats_enabled)} "
                         f"locked={int(locked)} pieces={'yes' if pieces else 'no'}")
                system, user = render_task(
                    "extraction_chat_state",
                    target_name="Beta", piece_list=pieces,
                    source_label="reply", source_text="t", context_text="",
                    outfit_locked=locked, is_avatar=is_avatar,
                    stats_enabled=stats_enabled,
                    stat_list="- stamina (0-100): 50")
                # the reply schema sits in the system turn (before "## user")
                whole = system + "\n" + user
                m = re.search(r'^\{.*\}$', whole, re.M)
                if not m:
                    check(label, False, "no schema line found")
                    continue
                schema = m.group(0)
                for old, new in SUBST:
                    schema = schema.replace(old, new)
                try:
                    parsed = json.loads(schema)
                except Exception as e:
                    check(label, False, f"{e}: {schema}")
                    continue
                # "removed" exactly when there are pieces and the outfit is free
                want_removed = bool(pieces) and not locked
                ok = ("removed" in parsed) == want_removed
                # the catalogue block must follow the same rule
                ok = ok and (("clothing pieces equipped" in whole) == want_removed)
                check(label, ok,
                      f"removed={'removed' in parsed} want={want_removed} "
                      f"schema={schema}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
