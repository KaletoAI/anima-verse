#!/usr/bin/env python3
"""Render check for the A3.2c templates (furnish_*, spell_detect, perceive_action).

Renders each of the five templates with EXACTLY the kwargs its production
call site passes, under the real StrictUndefined Jinja environment. A missing
variable therefore fails here instead of at runtime inside a background thread.

The fixtures are hand-built — the script never touches world.db, never starts
the server and never calls an LLM.

Cases per template:
  * "prod"  — the normal, fully populated call.
  * "empty" — the degenerate call (empty catalog / no openings / no optional
    blocks). Asserts that the guard fired: a block whose content is empty must
    not be rendered as an empty heading with an instruction attached to it.

Usage:
    ./.venv/bin/python scripts/test_a32c_templates.py
Exit code 0 = all cases rendered and all guard assertions held.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.prompt_templates import render, render_task  # noqa: E402

FAILURES: list = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILURES.append(f"{name} {detail}".strip())


def try_render_task(case: str, task: str, **kw):
    """Render a tasks/<task>.md and report a StrictUndefined miss as a failure."""
    try:
        sys_p, user_p = render_task(task, **kw)
        print(f"  ok   {case}: rendered (system {len(sys_p)} chars, user {len(user_p)} chars)")
        return sys_p, user_p
    except Exception as e:  # noqa: BLE001 — the render error IS the test result
        print(f"  FAIL {case}: {type(e).__name__}: {e}")
        FAILURES.append(f"{case}: {type(e).__name__}: {e}")
        return None, None


def try_render(case: str, path: str, **kw):
    try:
        out = render(path, **kw)
        print(f"  ok   {case}: rendered ({len(out)} chars)")
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {case}: {type(e).__name__}: {e}")
        FAILURES.append(f"{case}: {type(e).__name__}: {e}")
        return None


# ── Fixtures ────────────────────────────────────────────────────────────

# room_furnish._phase_select builds this dict once and passes it to both
# stage-1 templates (room_furnish.py:497-506).
FURNISH_COMMON = {
    "room_name": "Workshop",
    "room_description": "A cluttered workbench room at the back of the house.",
    "activity_hint": "repairing tools",
    "style_hint": "rustic",
    "room_w_m": 5.2,
    "room_d_m": 4.0,
    "area_m2": 20.8,
}
FURNISH_COMMON_EMPTY = {
    "room_name": "Room",
    "room_description": "",
    "activity_hint": "",
    "style_hint": "",
    "room_w_m": 3.0,
    "room_d_m": 3.0,
    "area_m2": 9.0,
}

CATALOG = [
    {"id": "oak-table-1", "name": "Oak Table", "category": "table",
     "width_m": 1.4, "depth_m": 0.8, "height_m": 0.75, "tags": ["wood", "sturdy"]},
    {"id": "stool-2", "name": "Wooden Stool", "category": "chair",
     "width_m": 0.4, "depth_m": 0.4, "height_m": 0.5, "tags": []},
]

# thought_context.build_thought_context() key set (app/core/thought_context.py:89-135
# plus action_instruction at :150 and _skill_block_parts at :164). Values are
# stand-ins; only the KEY set matters for the StrictUndefined check.
THOUGHT_CTX = {
    "character_name": "Mira",
    "lang_instruction": "Always respond in German.",
    "personality": "curious, blunt",
    "location_name": "Village Square",
    "activity": "sweeping the steps",
    "feeling": "Neutral",
    "time_of_day": "14:20",
    "game_date": "Summer, day 17 · Year 3",
    "inbox_block": "",
    "events_block": "- A cart lost a wheel by the well.",
    "assignments_block": "",
    "general_task": "",
    "commitments_block": "- You promised Ren to fetch water before dusk.",
    "state_flags_block": "",
    "outfit_decision_block": "",
    "arc_block": "",
    "retrospective_block": "",
    "skill_context_blocks": "",
    "effects_block": "",
    "recent_chat_block": "",
    "recent_thoughts": "",
    "outfit_self_block": "",
    "outfit_avatar_block": "",
    "room_items_block": "",
    "inventory_block": "",
    "present_people_block": "Ren (idle)",
    "elsewhere_block": "",
    "alone_here": False,
    "tracker_block": "",
    "activity_hint_block": "",
    "daily_schedule_block": "Around this hour you are usually outdoors.",
    "tools_hint": "",
    "has_assignments": False,
    "action_instruction": "Decide what you want to do next.",
    "_skill_block_parts": [],
}

# act_engine._bump_with_perception (app/core/act_engine.py:862-869).
PERCEPTION_VARS = {
    "action_actor": "Ren",
    "action_narration": "Ren hauls the broken cart out of the way and waves people past.",
    "action_scope": "here",
    "relationship_to_actor": "friendly, close",
    "action_actor_location": "Village Square",
    "action_actor_room": "Market Side",
}
PERCEPTION_VARS_EMPTY = {
    "action_actor": "Ren",
    "action_narration": "Ren lights a lantern.",
    "action_scope": "location",
    "relationship_to_actor": "",
    "action_actor_location": "",
    "action_actor_room": "",
}


# ── 1. furnish_select ───────────────────────────────────────────────────

def t_furnish_select() -> None:
    print("furnish_select")
    sys_p, user_p = try_render_task(
        "prod", "furnish_select", budget_m2=7.5, max_items=20,
        existing=[{"name": "Oak Table", "count": 1, "width_m": 1.4, "depth_m": 0.8}],
        catalog=CATALOG, **FURNISH_COMMON)
    if user_p:
        check("prod: catalog listed", "id: oak-table-1" in user_p)
        check("prod: existing listed", "1× Oak Table" in user_p)

    # Degenerate: the exclude filter can leave the catalog EMPTY — then the
    # "pick from the library" instruction has nothing to pick from.
    sys_p, user_p = try_render_task(
        "empty", "furnish_select", budget_m2=0.0, max_items=20,
        existing=[], catalog=[], **FURNISH_COMMON_EMPTY)
    if user_p is not None:
        check("empty: no dangling 'Furniture library:' heading",
              "Furniture library:" not in user_p,
              f"| got: {user_p[-200:]!r}")
        check("empty: says the library is empty",
              "no library items" in user_p.lower(),
              f"| got: {user_p[-200:]!r}")


# ── 2. furnish_new ──────────────────────────────────────────────────────

def t_furnish_new() -> None:
    print("furnish_new")
    sys_p, user_p = try_render_task(
        "prod", "furnish_new", budget_m2=5.0, max_new=8,
        existing=[{"name": "Oak Table", "count": 1}],
        catalog_names=["Oak Table", "Wooden Stool"],
        marker_kinds=["sit", "lie"], **FURNISH_COMMON)
    if user_p:
        check("prod: library names listed", "- Oak Table" in user_p)
        check("prod: marker kinds listed", "sit, lie" in user_p)

    sys_p, user_p = try_render_task(
        "empty", "furnish_new", budget_m2=0.0, max_new=8,
        existing=[], catalog_names=[], marker_kinds=[],
        **FURNISH_COMMON_EMPTY)
    if user_p is not None:
        check("empty: no dangling 'Library names' heading",
              "Library names (do not duplicate these):" not in user_p,
              f"| got: {user_p[-260:]!r}")
        check("empty: no empty marker-kind list",
              "Allowed marker animation kinds:" not in user_p,
              f"| got: {user_p[-260:]!r}")


# ── 3. furnish_place ────────────────────────────────────────────────────

def t_furnish_place() -> None:
    print("furnish_place")
    items = [{"id": "oak-table-1", "name": "Oak Table", "count": 1,
              "width_m": 1.4, "depth_m": 0.8, "height_m": 0.75}]
    sys_p, user_p = try_render_task(
        "prod", "furnish_place", room_name="Workshop",
        room_description="A cluttered workbench room.",
        room_w_m=5.2, room_d_m=4.0, is_rect=True,
        openings=[{"type": "door", "wall": "N", "at_frac": 0.5,
                   "width_m": 0.9, "sill_m": 0}],
        existing=[{"prop_id": "stool-2", "name": "Wooden Stool",
                   "x_m": 1.0, "y_m": 2.0}],
        items=items, errors=[])
    if sys_p:
        check("prod: no repair block on the first attempt",
              "previous attempt" not in sys_p)

    # Repair round — room_furnish._phase_place calls _run(errors) with the
    # solver's reasons (room_furnish.py:733-737).
    sys_p, user_p = try_render_task(
        "repair", "furnish_place", room_name="Village Square",
        room_description="", room_w_m=12.38, room_d_m=11.845, is_rect=False,
        openings=[], existing=[], items=items,
        errors=["oak-table-1: no free spot"])
    if sys_p:
        check("repair: errors rendered", "no free spot" in sys_p)
        check("repair: demands a CHANGED plan",
              "same plan" in sys_p.lower() or "change" in sys_p.lower(),
              "| the repair round must forbid repeating the failed plan")
    if user_p:
        check("repair: non-rect hint present",
              "non-rectangular" in user_p)


# ── 4. spell_detect ─────────────────────────────────────────────────────

def t_spell_detect() -> None:
    print("spell_detect")
    # spell_engine.detect_cast (app/core/spell_engine.py:155-164).
    sys_p, user_p = try_render_task(
        "prod", "spell_detect", avatar_name="Mira", target_name="Ren",
        message="Mira raises her hand and says the words.",
        spell_catalog='- id=spell_light | incantation: "lumen" | effect: makes light',
        language_name="German",
        volume_hint="The caster speaks at a normal, audible volume.")
    if sys_p:
        check("prod: language name reaches the system prompt",
              sys_p.count("German") >= 2,
              "| the observation-language instruction must be explicit")
        check("prod: loudness hint present", "normal, audible volume" in sys_p)

    # detect_cast passes "(no target)" when the chat has no partner.
    try_render_task(
        "no-target", "spell_detect", avatar_name="Mira",
        target_name="(no target)", message="lumen",
        spell_catalog="(none)", language_name="English",
        volume_hint="The caster is WHISPERING — barely audible.")


# ── 5. perceive_action ──────────────────────────────────────────────────

def t_perceive_action() -> None:
    print("perceive_action")
    # agent_loop._run_turn: ctx = build_thought_context(name); ctx.update(vars);
    # render(perception["template"], **ctx)  (app/core/agent_loop.py:1113-1121).
    # scope="here": the recipient shares the actor's room (act_engine.
    # resolve_recipients), so the "go there" block must stay out even though
    # act_engine always fills action_actor_location/-room.
    ctx = {**THOUGHT_CTX, **PERCEPTION_VARS}
    out = try_render("prod", "tasks/perceive_action.md", **ctx)
    if out:
        check("prod: narration present", PERCEPTION_VARS["action_narration"] in out)
        check("prod: language instruction present",
              THOUGHT_CTX["lang_instruction"] in out,
              "| a witness thought must be written in the character's language")
        # The task block must come after EVERY context heading, and the
        # trigger-boilerplate note must be the very last thing in the prompt.
        task_at = out.find("=== Your task ===")
        last_ctx = max(out.find(h) for h in (
            "=== Your open commitments", "=== Active events at your location ===",
            "=== Your typical rhythm right now ==="))
        check("prod: task block comes after all context blocks",
              task_at > last_ctx > 0,
              f"| task at {task_at}, last context heading at {last_ctx}")
        check("prod: trigger-boilerplate note closes the prompt",
              out.rstrip().endswith("call a tool this turn."),
              f"| ends with: {out.rstrip()[-60:]!r}")
        check("prod: scope=here suppresses the 'go there' block",
              "is currently at:" not in out,
              "| the witness stands in the actor's own room")
        check("prod: scope=here offers no SetLocation example",
              "SetLocation" not in out,
              "| SetLocation is the only whitelisted tool — do not bait it "
              "without a named target")
        check("prod: scope=here says 'witnessed'",
              "You just witnessed an action" in out)

    # scope="location": actor is in ANOTHER room of this location — the block
    # and the SetLocation example must appear, with the actor's real place.
    ctx = {**THOUGHT_CTX, **PERCEPTION_VARS, "action_scope": "location"}
    out = try_render("location", "tasks/perceive_action.md", **ctx)
    if out:
        check("location: 'go there' block present",
              "is currently at: Village Square — Market Side" in out)
        check("location: SetLocation example present",
              "using SetLocation with exactly the place named" in out)
        check("location: heard, not seen",
              "Something happened here" in out
              and "You just witnessed an action" not in out)

    ctx = {**THOUGHT_CTX, **PERCEPTION_VARS_EMPTY,
           "events_block": "", "commitments_block": "",
           "daily_schedule_block": "", "present_people_block": "",
           "lang_instruction": ""}
    out = try_render("empty", "tasks/perceive_action.md", **ctx)
    if out:
        check("empty: no dangling actor-location line",
              "is currently at:" not in out, f"| got: {out!r}"[:200])
        check("empty: no SetLocation example without a named target",
              "SetLocation" not in out,
              "| scope=location but the actor lookup came back empty")
        check("empty: no empty section headings",
              "=== Active events at your location ===" not in out
              and "=== Your open commitments" not in out)


def main() -> int:
    for fn in (t_furnish_select, t_furnish_new, t_furnish_place,
               t_spell_detect, t_perceive_action):
        fn()
        print()
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  - {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
