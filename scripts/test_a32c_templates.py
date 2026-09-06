#!/usr/bin/env python3
"""Render check for the furnish_*, spell_detect and perceive_action templates.

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

# What room_furnish._phase_needs passes to the stage-1 templates.
FURNISH_COMMON = {
    "setting": "indoor room inside a building",
    "room_name": "Workshop",
    "room_description": "A cluttered workbench room at the back of the house.",
    "activity_hint": "repairing tools",
    "style_hint": "rustic",
    "room_w_m": 5.2,
    "room_d_m": 4.0,
    "area_m2": 20.8,
}
FURNISH_COMMON_EMPTY = {
    "setting": "open-air yard of the location",
    "room_name": "Room",
    "room_description": "",
    "activity_hint": "",
    "style_hint": "",
    "room_w_m": 3.0,
    "room_d_m": 3.0,
    "area_m2": 9.0,
}

# The MATCH catalog: short refs, never slugs (plan-furnish-v2.md § 2 B3).
CATALOG = [
    {"ref": "#1", "name": "Oak Table", "category": "table", "mount": "floor",
     "width_m": 1.4, "depth_m": 0.8, "height_m": 0.75,
     "style": "heavy oak, dark waxed", "size_estimated": False,
     "tags": ["wood", "sturdy"]},
    {"ref": "#2", "name": "Wooden Stool", "category": "chair",
     "mount": "unclassified", "width_m": 0.4, "depth_m": 0.4, "height_m": 0.5,
     "style": "", "size_estimated": True, "tags": []},
]
NEEDS = [
    {"key": "n1", "kind": "dining table", "category": "table", "count": 1,
     "mount": "floor", "width_m": 1.4, "depth_m": 0.8, "height_m": 0.75,
     "style": "rustic oak"},
    {"key": "n2", "kind": "wall painting", "category": "decor", "count": 2,
     "mount": "wall", "width_m": 0.5, "depth_m": 0.05, "height_m": 0.6,
     "style": "rustic oak"},
]
MARKER_GROUPS = [{"key": "seat", "label": "Seat"}, {"key": "bed", "label": "Bed"}]
KEY_AREA_KINDS = [{"key": "picture", "meaning": "a flat face showing an image"},
                  {"key": "glass", "meaning": "a transparent pane"}]
SURFACE_KINDS = [{"key": "oak_planks", "label": "Oak planks"},
                 {"key": "plaster", "label": "Plaster"}]

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
    "game_weather": "freezing, snow — often fog in the morning",
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


# ── 1. furnish_needs ────────────────────────────────────────────────────

def t_furnish_needs() -> None:
    print("furnish_needs")
    sys_p, user_p = try_render_task(
        "prod", "furnish_needs", budget_m2=7.5, max_needs=16,
        storey_height_m=3.0,
        openings=[{"type": "door", "count": 1}, {"type": "window", "count": 2}],
        existing=[{"name": "Oak Table", "count": 1, "mount": "floor"}],
        marker_groups=MARKER_GROUPS, key_area_kinds=KEY_AREA_KINDS,
        surfaces_missing=True, surface_kinds=SURFACE_KINDS, **FURNISH_COMMON)
    if user_p:
        check("prod: existing listed with its mount",
              "1× Oak Table (mount: floor)" in user_p)
        check("prod: openings summarised", "- 2× window" in user_p)
        check("prod: the library is NOT in the prompt",
              "Wooden Stool" not in user_p and "#1" not in user_p)
        check("prod: the surface kinds are offered",
              "- oak_planks — Oak planks" in user_p)
        check("prod: marker place types listed", "- seat — Seat" in user_p)

    # Degenerate: a room that already has its surfaces, nothing standing in
    # it and no opening at all — no dangling headings, no empty lists.
    sys_p, user_p = try_render_task(
        "empty", "furnish_needs", budget_m2=0.0, max_needs=16,
        storey_height_m=3.0, openings=[], existing=[],
        marker_groups=MARKER_GROUPS, key_area_kinds=KEY_AREA_KINDS,
        surfaces_missing=False, surface_kinds=[], **FURNISH_COMMON_EMPTY)
    if user_p is not None:
        check("empty: no surface list without a proposal",
              "oak_planks" not in user_p and 'answer "surfaces": null' in user_p,
              f"| got: {user_p[-200:]!r}")
        check("empty: says the room holds nothing", "- nothing" in user_p)
        check("empty: says there is no opening", "- none" in user_p)
        check("empty: a full floor is stated as such",
              "0 m²" in user_p, f"| got: {user_p[-260:]!r}")


# ── 2. furnish_match ────────────────────────────────────────────────────

def t_furnish_match() -> None:
    print("furnish_match")
    sys_p, user_p = try_render_task(
        "prod", "furnish_match", setting=FURNISH_COMMON["setting"],
        room_name=FURNISH_COMMON["room_name"],
        style_hint=FURNISH_COMMON["style_hint"], needs=NEEDS, catalog=CATALOG)
    if user_p:
        # THE trim_blocks TRAP: a loop row that ends with a block tag loses
        # its newline and the whole catalog collapses into ONE line.
        catalog_lines = [ln for ln in user_p.splitlines() if ln.startswith("#")]
        check("prod: one catalog entry per line", len(catalog_lines) == 2,
              f"| got: {catalog_lines!r}")
        check("prod: the ref is the id the answer may use",
              catalog_lines and catalog_lines[0].startswith("#1 | Oak Table"),
              f"| got: {catalog_lines[:1]!r}")
        check("prod: an estimated size is flagged",
              "size estimated" in catalog_lines[-1], f"| got: {catalog_lines[-1]!r}")
        check("prod: the tags ride along", "tags: wood, sturdy" in user_p)
        check("prod: every need is listed",
              len([ln for ln in user_p.splitlines() if ln.startswith("n")]) == 2)

    sys_p, user_p = try_render_task(
        "empty", "furnish_match", setting=FURNISH_COMMON_EMPTY["setting"],
        room_name=FURNISH_COMMON_EMPTY["room_name"], style_hint="",
        needs=NEEDS, catalog=[])
    if user_p is not None:
        check("empty: no dangling 'The library holds:' heading",
              "The library holds:" not in user_p, f"| got: {user_p[-200:]!r}")
        check("empty: asks for null everywhere",
              "null for every need" in user_p, f"| got: {user_p[-200:]!r}")


# ── 3. furnish_place ────────────────────────────────────────────────────

def t_furnish_place() -> None:
    print("furnish_place")
    # The four groups of the v2 template (furnish_place.group_items).
    floor = [{"id": "oak-table-1", "name": "Oak Table", "count": 1,
              "width_m": 1.4, "depth_m": 0.8, "height_m": 0.75}]
    wall = [{"id": "need:n2", "name": "Framed Painting", "count": 2,
             "width_m": 0.5, "depth_m": 0.05, "height_m": 0.6}]
    ceiling = [{"id": "need:n3", "name": "Pendant Lamp", "count": 1,
                "width_m": 0.3, "depth_m": 0.3, "height_m": 0.8}]
    surface = [{"id": "need:n4", "name": "Candle", "count": 3,
                "width_m": 0.08, "depth_m": 0.08, "height_m": 0.2}]
    sys_p, user_p = try_render_task(
        "prod", "furnish_place", room_name="Workshop",
        room_description="A cluttered workbench room.",
        room_w_m=5.2, room_d_m=4.0, is_rect=True, storey_height_m=3.0,
        openings=[{"index": 0, "type": "door", "wall": "N", "at_frac": 0.5,
                   "width_m": 0.9, "sill_m": 0, "height_m": 2.1}],
        existing=[{"id": "aa11bb22", "name": "Wooden Stool", "mount": "floor",
                   "x_m": 1.0, "y_m": 2.0, "yaw": 90.0, "on": ""}],
        floor_items=floor, wall_items=wall, ceiling_items=ceiling,
        surface_items=surface, errors=[], repass=None)
    if sys_p:
        check("prod: no repair block on the first attempt",
              "PREVIOUS plan failed" not in sys_p)
        check("prod: all four anchor groups are offered",
              all(word in sys_p for word in ("FLOOR pieces", "WALL pieces",
                                             "CEILING pieces",
                                             "SURFACE pieces")))
    if user_p:
        # The trim_blocks trap: a loop row ending in a block tag loses its
        # newline. Four groups of one/two lines each must stay four blocks.
        check("prod: every item group is its own line",
              len([ln for ln in user_p.splitlines()
                   if ln.startswith("- id: ")]) == 4,
              f"| got: {[ln for ln in user_p.splitlines() if ln.startswith('- id: ')]}")
        check("prod: the opening carries its index",
              "index 0: door on wall N" in user_p, f"| got: {user_p[:400]!r}")
        check("prod: the standing piece carries id, mount and yaw",
              "(id aa11bb22), mount floor" in user_p and "yaw 90.0°" in user_p,
              f"| got: {user_p[:600]!r}")

    # Repair round — furnish_place.run re-plans ONE pass with that pass's
    # errors and the other groups listed as already standing.
    sys_p, user_p = try_render_task(
        "repair", "furnish_place", room_name="Village Square",
        room_description="", room_w_m=12.38, room_d_m=11.845, is_rect=False,
        storey_height_m=3.0, openings=[],
        existing=[{"id": "cc33", "name": "Oak Table", "mount": "floor",
                   "x_m": 2.0, "y_m": 0.45, "yaw": 0.0, "on": ""},
                  {"id": "dd44", "name": "Candle", "mount": "surface",
                   "x_m": 2.0, "y_m": 0.45, "yaw": 0.0, "on": "Oak Table"}],
        floor_items=floor, wall_items=wall, ceiling_items=ceiling,
        surface_items=surface,
        errors=[{"pass": "wall", "text": "Framed Painting (need:n2): no free "
                                         "wall spot on wall_n — try wall_e"},
                {"pass": "ceiling", "text": "Pendant Lamp (need:n3): the "
                                            "ceiling above 'x' is taken"}],
        repass="wall")
    if sys_p:
        check("repair: errors rendered with their pass",
              "[wall pass]" in sys_p and "[ceiling pass]" in sys_p,
              f"| got: {sys_p[-800:]!r}")
        check("repair: every error is its own line",
              len([ln for ln in sys_p.splitlines()
                   if ln.startswith("- [")]) == 2)
        # The wall pass carries the ceiling group with it, so the sentence
        # has to name both — a model told "only the wall group" would drop the
        # pendant lamp whose error it was just shown.
        check("repair: the wall re-plan names the ceiling group with it",
              "Re-plan ONLY the wall and ceiling group" in sys_p,
              f"| got: {sys_p[-900:]!r}")
        check("repair: demands a CHANGED plan",
              "same anchor again" in sys_p,
              "| the repair round must forbid repeating the failed plan")
    if user_p:
        check("repair: non-rect hint present",
              "non-rectangular" in user_p)
        check("repair: the child names its support",
              "stands on Oak Table" in user_p, f"| got: {user_p[:600]!r}")
        check("repair: the closing instruction names the same group",
              "plan for the wall and ceiling group" in user_p,
              f"| got: {user_p[-200:]!r}")

    # A floor (or surface) re-plan keeps the plain group name — only the wall
    # pass has a second group riding along.
    sys_p, _user_p = try_render_task(
        "repair-floor", "furnish_place", room_name="Kitchen",
        room_description="", room_w_m=4.0, room_d_m=4.0, is_rect=True,
        storey_height_m=3.0, openings=[], existing=[], floor_items=floor,
        wall_items=[], ceiling_items=[], surface_items=[],
        errors=[{"pass": "floor", "text": "Oak Table (oak-table-1): no free "
                                          "spot — try center"}],
        repass="floor")
    if sys_p:
        check("repair-floor: the floor re-plan names only the floor group",
              "Re-plan ONLY the floor group" in sys_p)


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
    for fn in (t_furnish_needs, t_furnish_match, t_furnish_place,
               t_spell_detect, t_perceive_action):
        fn()
        print()
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  - {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
