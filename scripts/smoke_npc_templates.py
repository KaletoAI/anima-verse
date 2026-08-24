#!/usr/bin/env python3
"""Checks the temporary-NPC prompt templates against their production call sites.

Usage:
    ./.venv/bin/python scripts/smoke_npc_templates.py

Needs neither the server nor a world DB — `prompt_templates` resolves
`shared/templates/llm/` relative to the repo root and nothing else. The schema
markdown is read straight off disk (no placeholder filling; that half needs a
world and lives in scripts/smoke_temporary_npc.py).

WHY these expectations (derived by hand from the call sites, not recorded from
current output):

1. StrictUndefined. Each template is rendered with EXACTLY the kwargs its
   production call site passes — `npc_ops.generate_npc` calls
   `render_task("npc_generate", schema_text=…, briefing=…)`,
   `render_task("world_dev_validate", schema_text=…, draft_json=…)` and
   `render_task("npc_repair", schema_text=…, draft_json=…, gaps=…)`. A missing
   placeholder raises here, so a template that renders here cannot raise in
   production for the same call site.

2. Both sections non-empty. `render_task` splits on `## system` / `## user` and
   either half may legally come back empty — which is exactly how two summary
   templates once shipped with no system prompt at all (see
   scripts/test_a2_templates.py §3). For a one-shot generator an empty system
   turn would mean the model never sees the schema, so empty is a regression.

3. The schema reaches the SYSTEM turn, in full. The generator has no human in
   the loop; the spec is the only thing keeping the output in shape. The check
   asserts the schema text is inside the system prompt and NOT inside the user
   prompt (duplicating it would double the token cost of every turn).

4. The split survives a schema full of `##` headings. `render_task` renders
   FIRST and splits AFTERWARDS, so a raw `## system` / `## user` line inside
   the injected schema tears the prompt in half: the real user turn replaces
   the schema's tail (the last marker wins) and everything before the stray
   heading is dropped. That is why `build_npc_schema_text` runs every schema
   through `sanitize_injected_markdown` — the check feeds a schema containing
   both literal headings through that same function, exactly as production
   does, and asserts both halves come out whole. Without the sanitizer this
   check fails, which is how the hazard was found.

5. The fence marker survives rendering. `_extract_json_block(text, "npc")`
   looks for exactly ```json:npc; if the instruction that produces it were
   reworded away, every run would end in "no ```json:npc block".

6. The repair turn demands the COMPLETE object and carries the gaps verbatim.
   Apply takes ONE flat dict, so a partial answer silently drops every field it
   omits — the instruction against that is load-bearing, not decoration.

7. The npc-temporary template switches OFF every feature the decision list
   names, and `is_feature_enabled` is fail-open (a key the template omits is
   GRANTED). So each flag is asserted present AND false by reading the merged
   template — an omission is the failure mode this catches.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.npc_ops import sanitize_injected_markdown  # noqa: E402
from app.core.prompt_templates import render_task  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: A schema stand-in that deliberately contains the two headings the splitter
#: reacts to — see WHY §4. Passed through the SAME sanitizer the production
#: `build_npc_schema_text` applies, so this is the real call site.
TRAP_SCHEMA_RAW = (
    "# Schema: Temporary NPC\n\n"
    "## system\nthis line must not split the prompt\n\n"
    "## user\nneither must this one\n\n"
    "## Output\nAnswer with exactly one ```json:npc block.\n"
)
TRAP_SCHEMA = sanitize_injected_markdown(TRAP_SCHEMA_RAW)

BRIEFING = "a weary barkeeper who has run this place for thirty years"
DRAFT_JSON = '{\n  "character_name": "Maren Kolb",\n  "standing_task": ""\n}'
GAPS = "- standing_task — missing, Standing task is required"

# task -> kwargs exactly as npc_ops.generate_npc passes them
CALL_SITES = {
    "npc_generate": dict(schema_text=TRAP_SCHEMA, briefing=BRIEFING),
    "npc_repair": dict(schema_text=TRAP_SCHEMA, draft_json=DRAFT_JSON, gaps=GAPS),
    "world_dev_validate": dict(schema_text=TRAP_SCHEMA, draft_json=DRAFT_JSON),
}

#: Every flag the "radically reduced features" decision turns off, plus the
#: three that must stay on (an NPC still stands somewhere, still does its one
#: task, still stays in character) and the marker itself.
EXPECTED_FEATURES = {
    "temporary_npc": True,
    "humanoid": True,
    "locations_enabled": True,
    "activities_enabled": True,
    "roleplay_rules_enabled": True,
    "memory_enabled": False,
    "relationships_enabled": False,
    "relationship_summary_enabled": False,
    "thoughts_enabled": False,
    "intents_enabled": False,
    "story_enabled": False,
    "storydev_enabled": False,
    "secrets_enabled": False,
    "inventory_enabled": False,
    "mood_tracking_enabled": False,
    "social_dialog_enabled": False,
    "random_events_enabled": False,
    "expression_variants_enabled": False,
    "playable_avatar": False,
    "assignments_enabled": False,
    "beliefs_enabled": False,
    "lessons_enabled": False,
    "goals_enabled": False,
    "soul_enabled": False,
    "retrospect_enabled": False,
    "status_effects_enabled": False,
    "outfit_system_enabled": False,
}

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


print("[1] StrictUndefined render with the exact production kwargs")
rendered = {}
for task, kwargs in CALL_SITES.items():
    try:
        rendered[task] = render_task(task, **kwargs)
        check(f"{task} renders", True, True)
    except Exception as e:  # noqa: BLE001
        check(f"{task} renders", f"{type(e).__name__}: {e}", True)

print("\n[2] Both sections non-empty")
for task in CALL_SITES:
    if task not in rendered:
        continue
    system, user = rendered[task]
    check(f"{task} system non-empty", bool(system.strip()), True)
    check(f"{task} user non-empty", bool(user.strip()), True)

print("\n[3]+[4] Schema lands in system only, split survives ## headings")
check("sanitizer demotes '## system'", "### system" in TRAP_SCHEMA, True)
check("sanitizer demotes '## user'", "### user" in TRAP_SCHEMA, True)
check("sanitizer leaves other headings alone", "## Output" in TRAP_SCHEMA, True)
for task in CALL_SITES:
    if task not in rendered:
        continue
    system, user = rendered[task]
    # The trap lines live in the schema; both must be on the system side and
    # neither may have torn the prompt apart.
    check(f"{task} keeps trap line 1 in system",
          "this line must not split the prompt" in system, True)
    check(f"{task} keeps trap line 2 in system",
          "neither must this one" in system, True)
    check(f"{task} does not duplicate the schema into user",
          "this line must not split the prompt" in user, False)

print("\n[5] The ```json:npc fence marker survives rendering")
for task in ("npc_generate", "npc_repair"):
    if task not in rendered:
        continue
    system, user = rendered[task]
    check(f"{task} names json:npc", "```json:npc" in (system + user), True)

print("\n[6] Repair turn: gaps verbatim + the COMPLETE-object instruction")
if "npc_repair" in rendered:
    _, user = rendered["npc_repair"]
    check("gaps text present", GAPS in user, True)
    check("draft json present", '"character_name": "Maren Kolb"' in user, True)
    check("demands the complete object", "COMPLETE" in user, True)
    check("warns about partial answers", "partial" in user.lower(), True)

if "npc_generate" in rendered:
    _, user = rendered["npc_generate"]
    check("briefing verbatim in the user turn", BRIEFING in user, True)
    # One-shot: the model must be told not to ask, or the pipeline stalls on a
    # clarifying question nobody will answer.
    check("forbids clarifying questions",
          "not ask questions" in user or "do not ask" in user.lower(), True)

print("\n[7] npc-temporary feature flags — present AND at the expected value")
import json  # noqa: E402
tmpl_path = REPO / "shared" / "templates" / "character" / "npc-temporary.json"
tmpl = json.loads(tmpl_path.read_text(encoding="utf-8"))
features = tmpl.get("features") or {}
for flag, expected in sorted(EXPECTED_FEATURES.items()):
    # `.get(flag, "<absent>")` on purpose: is_feature_enabled treats an absent
    # key as True, so "absent" must fail loudly rather than read as False.
    check(f"features.{flag}", features.get(flag, "<absent>"), expected)
check("base template", tmpl.get("base"), "base-character")
check("selectable", tmpl.get("selectable"), True)

print("\n[8] The schema file exists and asks for the json:npc fence")
schema_path = REPO / "shared" / "world_dev_schemas" / "npc_character.md"
check("npc_character.md exists", schema_path.exists(), True)
if schema_path.exists():
    text = schema_path.read_text(encoding="utf-8")
    check("schema names the fence", "```json:npc" in text, True)
    # The splitter would tear the prompt at these; the trap test above proves
    # the templates survive it, this proves the real schema never triggers it.
    lines = [ln.strip().lower() for ln in text.splitlines()]
    check("schema has no '## system' line", "## system" in lines, False)
    check("schema has no '## user' line", "## user" in lines, False)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
