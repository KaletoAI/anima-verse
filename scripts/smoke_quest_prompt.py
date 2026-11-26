#!/usr/bin/env python3
"""Smoke: per-turn quest prompt block (quest stage 2, Task 10, D15).

Usage:
    ./.venv/bin/python scripts/smoke_quest_prompt.py

Throwaway storage and instance (STORAGE_DIR / INSTANCE_DIR temp dirs,
paths.init + paths.init_instance BEFORE importing any world-DB module).
No server, no LLM, no network, no media. Registers quest types with
quest_types.register() and drives quest_effects.pass_once() directly
(does NOT call quest_engine.register()).

FIXTURE
    Location: "Wood" (id "L_wood", entry_room "r_cave") with rooms
      "Cave" (id "r_cave") and "Glade" (id "r_glade").
    Characters: Giver, Sage, Other, Hero (template "human-roleplay"),
      all standing in L_wood / r_cave (so nobody is in r_glade).
    Template T1 (state "ready"):
      title: "The tin box"
      summary: "{giver} lost a box near {glade}."
      giver_role: "giver"
      roles: giver (character), glade (room)
      steps:
        s1: "Find the rock near {glade}." (condition: at_place glade)
        s2: "Bring the box." (condition: at_place glade)
      setup_effects:
        hint: give_hint(holder="giver", text="The box lies in {glade}.")
      bindings: giver=Giver, glade=L_wood/r_glade (frozen labels: "Giver", "Glade").
    Template T2 (state "ready"):
      title: "The old song"
      summary: "{giver} wants a song."
      giver_role: "giver"
      roles: giver (character), glade (room)
      start_condition: at_place glade (false while everyone is in Cave -> hidden)
      steps:
        s1: "Sing at {glade}." (condition: at_place glade)
      setup_effects:
        hint: give_hint(holder="giver", text="The song is old.")
      bindings: giver=Sage, glade=L_wood/r_glade (frozen labels: "Sage", "Glade").

HAND-DERIVED EXPECTATIONS
  (a) Before any run:
      lines_for("Giver") == [] and quest_engine.has_live_runs() is False.
  (b) Open run T1 after pass_once():
      state == "open", live secret object has ref["secret_id"] == sid.
      lines_for("Giver") == [
          "You want an adventurer to: Giver lost a box near Glade. — next: Find the rock near Glade.",
          f"You know something you may tell an adventurer who asks [secret {sid}]: The box lies in Glade.",
      ]
      block_for("Giver") == "\n".join("- " + line for line in expected_lines)
      lines_for("Other") == [].
  (c) Secrets section exclusion:
      After adding a normal secret "I fear the dark." for Giver,
      build_secrets_prompt_section("Giver") contains "I fear the dark."
      and does NOT contain "The box lies in".
  (d) Cache contract:
      P0 = _build_chat_prompt for Giver (partner Other);
      advance T1 to step index 1 with quests.record_step_done(run1_id, 0, avatar="Hero", mind="Hero");
      P1 = same _build_chat_prompt call.
      P0.system == P1.system (byte-identical), P0.moment != P1.moment,
      "— next: Bring the box." in P1.moment, "Quests you are part of:" in P1.moment,
      and none of "You want an adventurer", "[secret ", "The box lies in" in P1.system.
      Control: "I fear the dark." is in P1.system (secrets_enabled is true in
      human-roleplay, so the secrets section is rendered; the quest hint is
      absent from it while a normal secret is present).
  (e) Thought prompts:
      build_thought_context("Giver")["quest_block"] == block_for("Giver");
      render("chat/agent_thought.md", **ctx) and render("chat/agent_thought_in_chat.md", **ctx)
      both contain "=== Quests you are part of ===" and the secret line.
  (f) Hidden run T2 after pass_once():
      state == "hidden";
      lines_for("Sage") == ["You want an adventurer to: Sage wants a song."] exactly;
      no line contains "[secret" and no line contains "Sing at Glade.".
  (g) Ended runs:
      cancel_run(T1) -> lines_for("Giver") == [] immediately (before pass_once);
      after pass_once() still [].
      cancel_run(T2) -> lines_for("Sage") == [] and has_live_runs() is False.
  (h) Cap at MAX_LINES (3):
      4 open runs without setup for Giver ("Task 1." .. "Task 4.") ->
      len(lines_for("Giver")) == 3 (MAX_LINES).
  (i) Never raises:
      monkeypatching app.models.quests.list_runs to raise RuntimeError ->
      lines_for("Giver") == []; restored afterwards.
  (j) NPC action context:
      _with_action_context("Giver", {})["extension_prompt"] contains
      "Quests you are part of:" while the runs of (h) are live.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quest-prompt-smoke-"))
STORAGE = TMP / "world"
INSTANCE = TMP / "instance"
STORAGE.mkdir()
INSTANCE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(INSTANCE)

import app  # noqa: E402
assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import (  # noqa: E402
    npc_actions,
    quest_effects as qfx,
    quest_engine as qe,
    quest_prompt as qp,
    quest_types as qt,
    thought_context,
)
from app.core.game_time import GameTime  # noqa: E402
from app.core.prompt_templates import render  # noqa: E402
from app.core.timeutils import set_game_time  # noqa: E402
from app.models import character as ch, quests, secrets, world  # noqa: E402
from app.routes.chat import _build_chat_prompt  # noqa: E402

FAILURES = []
SECTION = [""]


def check(label, actual, expected):
    full = f"{SECTION[0]} {label}".strip()
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {full}: {actual!r}"
          + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(full)


def section(name, title):
    SECTION[0] = name
    print(f"{name} {title}")


def main() -> int:
    qt.register()
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))

    # Fixture: location "Wood" with rooms "Cave" and "Glade"
    world.upsert_location(
        {
            "id": "L_wood",
            "name": "Wood",
            "entry_room": "r_cave",
            "rooms": [
                {"id": "r_cave", "name": "Cave", "description": "A dry cave."},
                {"id": "r_glade", "name": "Glade", "description": "A mossy glade."},
            ],
        },
        sync_world=False,
    )
    for name in ("Giver", "Sage", "Other", "Hero"):
        assert ch.save_character_profile(
            name,
            {
                "character_name": name,
                "template": "human-roleplay",
                "current_location": "L_wood",
                "current_room": "r_cave",
                "language": "en",
            },
            create_new=True,
        ), name

    roles = [
        {"key": "giver", "kind": "character", "description": "Quest giver"},
        {"key": "glade", "kind": "room", "description": "The mossy glade"},
    ]
    cond_glade = {"type": "at_place", "params": {"place": "glade"}}

    tpl1 = quests.create_template(
        title="The tin box",
        summary="{giver} lost a box near {glade}.",
        giver_role="giver",
        roles=roles,
        steps=[
            {"id": "s1", "text": "Find the rock near {glade}.", "hint": "", "condition": cond_glade},
            {"id": "s2", "text": "Bring the box.", "hint": "", "condition": cond_glade},
        ],
        setup_effects=[
            {"key": "hint", "type": "give_hint", "params": {"holder": "giver", "text": "The box lies in {glade}."}},
        ],
        state="ready",
    )
    tpl2 = quests.create_template(
        title="The old song",
        summary="{giver} wants a song.",
        giver_role="giver",
        roles=roles,
        start_condition=cond_glade,
        steps=[
            {"id": "s1", "text": "Sing at {glade}.", "hint": "", "condition": cond_glade},
        ],
        setup_effects=[
            {"key": "hint", "type": "give_hint", "params": {"holder": "giver", "text": "The song is old."}},
        ],
        state="ready",
    )

    # (a) Before any run
    section("(a)", "before any run")
    check("lines_for Giver empty", qp.lines_for("Giver"), [])
    check("has_live_runs False", qe.has_live_runs(), False)

    # (b) Start T1, open via pass_once
    section("(b)", "open run T1")
    run1 = qe.start_run(
        tpl1["id"],
        {"giver": {"name": "Giver"}, "glade": {"location_id": "L_wood", "room_id": "r_glade"}},
    )
    qfx.pass_once()
    run1 = quests.get_run(run1["id"])
    check("T1 state open", run1["state"], "open")
    objs1 = [o for o in quests.list_objects(run1["id"], statuses=("live",)) if o.get("kind") == "secret"]
    check("T1 live secret object count", len(objs1), 1)
    sid = objs1[0]["ref"]["secret_id"]
    want_line1 = "You want an adventurer to: Giver lost a box near Glade. \u2014 next: Find the rock near Glade."
    want_line2 = f"You know something you may tell an adventurer who asks [secret {sid}]: The box lies in Glade."
    check("lines_for Giver", qp.lines_for("Giver"), [want_line1, want_line2])
    check("block_for Giver", qp.block_for("Giver"), f"- {want_line1}\n- {want_line2}")
    check("lines_for Other empty", qp.lines_for("Other"), [])

    # (c) Secrets section excludes quest hints
    section("(c)", "secrets section")
    secrets.add_secret("Giver", "I fear the dark.")
    sec_section = secrets.build_secrets_prompt_section("Giver")
    check("normal secret included", "I fear the dark." in sec_section, True)
    check("quest hint excluded", "The box lies in" in sec_section, False)

    # (d) Cache contract
    section("(d)", "cache contract")

    def _chat_prompt(speaker, partner):
        return _build_chat_prompt(
            character_name=speaker,
            lang_instruction="Respond in English.",
            history_summary="",
            tools_enabled=False,
            agent_config=ch.get_character_config(speaker),
            partner_override=partner,
            medium="in_person",
        )

    p0 = _chat_prompt("Giver", "Other")
    updated = quests.record_step_done(run1["id"], 0, avatar="Hero", mind="Hero")
    check("step 0 recorded, still open", (updated["state"], updated["current_step"]), ("open", 1))
    p1 = _chat_prompt("Giver", "Other")
    check("system prompt byte-identical", p0.system == p1.system, True)
    check("moment changed", p0.moment != p1.moment, True)
    check("step 2 in moment", "\u2014 next: Bring the box." in p1.moment, True)
    check("header in moment", "Quests you are part of:" in p1.moment, True)
    check("no giver wish in system", "You want an adventurer" in p1.system, False)
    check("no secret tag in system", "[secret " in p1.system, False)
    check("no hint content in system", "The box lies in" in p1.system, False)
    check("control: own normal secret is in the system prompt", "I fear the dark." in p1.system, True)

    # (e) Thought prompts
    section("(e)", "thought prompts")
    ctx = thought_context.build_thought_context("Giver")
    check("quest_block matches block_for", ctx["quest_block"], qp.block_for("Giver"))
    t_reg = render("chat/agent_thought.md", **ctx)
    t_chat = render("chat/agent_thought_in_chat.md", **ctx)
    check("agent_thought header", "=== Quests you are part of ===" in t_reg, True)
    check("agent_thought secret line", want_line2 in t_reg, True)
    check("agent_thought_in_chat header", "=== Quests you are part of ===" in t_chat, True)
    check("agent_thought_in_chat secret line", want_line2 in t_chat, True)

    # (f) Hidden run T2
    section("(f)", "hidden run T2")
    run2 = qe.start_run(
        tpl2["id"],
        {"giver": {"name": "Sage"}, "glade": {"location_id": "L_wood", "room_id": "r_glade"}},
    )
    qfx.pass_once()
    run2 = quests.get_run(run2["id"])
    check("T2 state hidden", run2["state"], "hidden")
    sage_lines = qp.lines_for("Sage")
    check("lines_for Sage exact", sage_lines, ["You want an adventurer to: Sage wants a song."])
    check("no secret id in hidden lines", any("[secret" in ln for ln in sage_lines), False)
    check("no step text in hidden lines", any("Sing at Glade." in ln for ln in sage_lines), False)

    # (g) Ended runs
    section("(g)", "ended runs")
    check("cancel T1", qe.cancel_run(run1["id"]), True)
    check("lines_for Giver empty before pass_once", qp.lines_for("Giver"), [])
    qfx.pass_once()
    check("lines_for Giver empty after pass_once", qp.lines_for("Giver"), [])
    check("cancel T2", qe.cancel_run(run2["id"]), True)
    check("lines_for Sage empty", qp.lines_for("Sage"), [])
    check("has_live_runs False", qe.has_live_runs(), False)

    # (h) Cap at MAX_LINES
    section("(h)", "cap at MAX_LINES")
    cap_runs = []
    for n in range(1, 5):
        t_cap = quests.create_template(
            title=f"Cap {n}",
            summary=f"Task {n}.",
            giver_role="giver",
            roles=roles,
            steps=[{"id": "s1", "text": f"Do {n}.", "hint": "", "condition": cond_glade}],
            state="ready",
        )
        r_cap = qe.start_run(
            t_cap["id"],
            {"giver": {"name": "Giver"}, "glade": {"location_id": "L_wood", "room_id": "r_glade"}},
        )
        cap_runs.append(r_cap)
    check("4 open runs capped to 3", len(qp.lines_for("Giver")), 3)
    check("MAX_LINES is 3", qp.MAX_LINES, 3)

    # (i) Never raises
    section("(i)", "never raises")
    orig_list_runs = quests.list_runs

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    quests.list_runs = _boom
    try:
        check("returns [] on RuntimeError", qp.lines_for("Giver"), [])
    finally:
        quests.list_runs = orig_list_runs

    # (j) NPC action context
    section("(j)", "NPC action context")
    out_vars = npc_actions._with_action_context("Giver", {})
    check("extension_prompt has quest header",
          "Quests you are part of:" in out_vars.get("extension_prompt", ""), True)

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("\nPASS smoke_quest_prompt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
