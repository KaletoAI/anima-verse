#!/usr/bin/env python3
"""Smoke run for the undress package: a free-text NPC takes its clothes off.

Usage:
    ./.venv/bin/python scripts/smoke_undress.py

Runs against a THROWAWAY storage directory — never touches a real world, needs
no server. ``ANIMATION_CLIPS_DIR`` is redirected before the app modules are
imported so the clip library on disk stays out of it.

Doctrine under test (plan-temp-npc-undress.md): a character whose template has
NO outfit system dresses from one free text (``outfit_description``) plus one
binary state (``outfit_worn``). The two verbs of ``plugins/undress/`` flip that
state; everything else about the character stays untouched. Nothing in the core
names either verb — the whole condition lives in the package's ``visible_for``,
which the skill manager asks generically
(``app/skills/skill_manager.py:169``).

Every expectation below is derived BY HAND from a call site, not recorded from
current output:

  [1] The verbs reach a temporary NPC at all. An `always_load` verb without a
      per-character config is OFF (`skill_manager.py:177-179`), so the package
      alone changes nothing — the template has to name it. Read off
      `shared/templates/character/npc-temporary.json`: `default_skills` must
      contain `get_dressed` and `undress`, and the list must stay sorted
      (it is maintained alphabetically). `human-default.json` deliberately
      does NOT get them (plan, Task 2), which is asserted too — otherwise the
      next person "tidying up" the two lists would widen the feature silently.

  [2] A dressed temporary NPC is offered Undress and NOT GetDressed. Measured
      at the consumer — `_get_agent_skills`, the routine that really decides a
      character's verbs — after `activate_default_skills` has written the
      template's list, so this covers Task 2 and the visibility rule in one
      go. Tool names come from the package templates
      (`templates/llm/skills/<id>.md`): "Undress" / "GetDressed".

  [3] Undress replaces the outfit line and flips the offer. `render_outfit`
      appends `"wearing: " + outfit_description` only while the character is
      dressed and puts `NO_CLOTHES_TEXT` in its place otherwise
      (`outfit_renderer.py`, free-text branch), so after the call `full` must
      be exactly "no clothes" — the SAME text the manual UI switch produces.
      Undressed is a statement, not a gap: an image prompt with no clothing
      line at all lets the model dress the figure as it pleases. And the
      offer swaps: GetDressed appears, Undress goes. That swap is the only way
      the character learns its own state, because `outfit_worn` has
      `in_prompt: false`.

  [4] GetDressed puts the description back, verbatim:
      "wearing: a patched oilskin". Same text as before the round trip — the
      description itself is never edited by either verb.

  [5] A character WITH a wardrobe is offered neither verb, even though its
      profile carries an `outfit_description` as well. `human-roleplay` has
      `outfit_system_enabled: true`, and such characters change clothes with
      ChangeOutfit; the free text is not their dressed state (the renderer
      ignores it as soon as a piece is equipped). Asserting it with the text
      PRESENT is the point: it proves the wardrobe gate hides the verbs, not
      the missing text of case [6].

  [6] A temporary NPC without an `outfit_description` is offered neither verb.
      There is nothing to take off, and `outfit_worn` would flip a state no
      prompt ever renders.

  [7] The string form is read like the bool. The template field is a `select`
      with the option values "true"/"false" (`npc-temporary.json`), while
      `npc_ops`/`npc_pool` and the verb itself write a real `True`/`False` —
      so BOTH shapes reach the profile and there must be exactly ONE reading
      of them. That reading is `outfit_renderer.is_outfit_worn`, which the
      package imports instead of copying. Checked twice: on the function
      (missing key = dressed; "false"/"0"/"no"/"nein"/"" = undressed; "true"
      and `True` = dressed) and through the whole chain — a profile carrying
      the STRING "false" must render an empty outfit line and be offered
      GetDressed, exactly like the bool.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
STORAGE = Path(tempfile.mkdtemp(prefix="undress-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="undress-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.dependencies import get_skill_manager  # noqa: E402
from app.core.npc_ops import activate_default_skills  # noqa: E402
from app.core.outfit_renderer import is_outfit_worn, render_outfit  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  save_character_profile)

NPC = "demo_npc"
NPC_BARE = "demo_npc_bare"
RP = "demo"
OUTFIT = "a patched oilskin"

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def offered(character_name):
    """The tool names the skill manager really offers this character."""
    mgr = get_skill_manager()
    skills = mgr._get_agent_skills(character_name, check_limits=False)
    return sorted(getattr(s, "name", "") for s in skills)


def run_verb(skill_id, character_name):
    """Call a verb the way the tool layer does — JSON with agent_name."""
    skill = get_skill_manager().get_skill(skill_id)
    if skill is None:
        return f"<no skill '{skill_id}' installed>"
    return skill.execute(json.dumps({"agent_name": character_name,
                                     "input": ""}))


def make_character(name, template, **extra):
    profile = {"character_name": name, "template": template}
    profile.update(extra)
    save_character_profile(name, profile, create_new=True)
    activate_default_skills(name, template)


# ---------------------------------------------------------------------------
print("[1] The temporary-NPC template offers both verbs")
from app.models.character_template import get_template  # noqa: E402

npc_defaults = list((get_template("npc-temporary") or {}).get("default_skills") or [])
check("undress is a default skill of npc-temporary", "undress" in npc_defaults, True)
check("get_dressed is a default skill of npc-temporary",
      "get_dressed" in npc_defaults, True)
check("the list stays alphabetical", npc_defaults, sorted(npc_defaults))
human_defaults = list((get_template("human-default") or {}).get("default_skills") or [])
check("human-default is deliberately left out",
      [s for s in ("undress", "get_dressed") if s in human_defaults], [])

# ---------------------------------------------------------------------------
print("\n[2] A dressed temporary NPC is offered Undress, not GetDressed")
make_character(NPC, "npc-temporary", outfit_description=OUTFIT)
tools = offered(NPC)
check("Undress is offered", "Undress" in tools, True)
check("GetDressed is not offered", "GetDressed" in tools, False)
check("the NPC starts dressed",
      render_outfit(character_name=NPC).get("full", ""), f"wearing: {OUTFIT}")

# ---------------------------------------------------------------------------
print("\n[3] Undress replaces the outfit line and flips the offer")
result = run_verb("undress", NPC)
print(f"       undress() -> {result!r}")
check("outfit_worn is falsy now",
      is_outfit_worn(get_character_profile(NPC) or {}), False)
check("the outfit line names the undressed state",
      render_outfit(character_name=NPC).get("full", ""), "no clothes")
check("the description itself survives",
      (get_character_profile(NPC) or {}).get("outfit_description"), OUTFIT)
tools = offered(NPC)
check("GetDressed is offered now", "GetDressed" in tools, True)
check("Undress is gone", "Undress" in tools, False)

# ---------------------------------------------------------------------------
print("\n[4] GetDressed puts the description back")
result = run_verb("get_dressed", NPC)
print(f"       get_dressed() -> {result!r}")
check("outfit_worn is true again",
      is_outfit_worn(get_character_profile(NPC) or {}), True)
check("the outfit line is back, verbatim",
      render_outfit(character_name=NPC).get("full", ""), f"wearing: {OUTFIT}")
tools = offered(NPC)
check("Undress is offered again", "Undress" in tools, True)
check("GetDressed is gone again", "GetDressed" in tools, False)

# ---------------------------------------------------------------------------
print("\n[5] A wardrobe character is offered neither verb")
make_character(RP, "human-roleplay", outfit_description=OUTFIT)
tools = offered(RP)
check("Undress stays away from a wardrobe character", "Undress" in tools, False)
check("GetDressed stays away too", "GetDressed" in tools, False)

# ---------------------------------------------------------------------------
print("\n[6] A temporary NPC without an outfit description is offered neither")
make_character(NPC_BARE, "npc-temporary")
tools = offered(NPC_BARE)
check("nothing to take off", "Undress" in tools, False)
check("nothing to put on either", "GetDressed" in tools, False)

# ---------------------------------------------------------------------------
print("\n[7] The string form reads like the bool — ONE interpretation")
check("missing key = dressed", is_outfit_worn({}), True)
check('"false" = undressed', is_outfit_worn({"outfit_worn": "false"}), False)
check('"0" = undressed', is_outfit_worn({"outfit_worn": "0"}), False)
check('"no" = undressed', is_outfit_worn({"outfit_worn": "no"}), False)
check('"nein" = undressed', is_outfit_worn({"outfit_worn": "nein"}), False)
check('"" = undressed', is_outfit_worn({"outfit_worn": ""}), False)
check('"true" = dressed', is_outfit_worn({"outfit_worn": "true"}), True)
check("False = undressed", is_outfit_worn({"outfit_worn": False}), False)
check("True = dressed", is_outfit_worn({"outfit_worn": True}), True)

# ...and through the whole chain, on a profile written as the UI select does.
profile = get_character_profile(NPC) or {}
profile["outfit_worn"] = "false"
save_character_profile(NPC, profile)
check('a "false" string replaces the outfit line',
      render_outfit(character_name=NPC).get("full", ""), "no clothes")
tools = offered(NPC)
check('a "false" string offers GetDressed', "GetDressed" in tools, True)
check('a "false" string hides Undress', "Undress" in tools, False)
profile["outfit_worn"] = "true"
save_character_profile(NPC, profile)
check('a "true" string dresses the NPC again',
      render_outfit(character_name=NPC).get("full", ""), f"wearing: {OUTFIT}")
tools = offered(NPC)
check('a "true" string offers Undress', "Undress" in tools, True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
