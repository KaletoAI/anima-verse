#!/usr/bin/env python3
"""Smoke: final review fixes for quest stage 2 (items 1, 2, 3, 4, 6, 7, 9, Minor B).

Usage:
    ./.venv/bin/python scripts/smoke_quest_review_fixes.py

Throwaway storage (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR in temp dirs,
paths.init + paths.init_instance BEFORE importing any world-DB module).
No server, no LLM, no network, no media (prop generation and LLM calls stubbed).
Registers quest types with quest_types.register() and drives quest_effects.pass_once()
directly.

HAND-DERIVED EXPECTATIONS
  [1] Non-permanent create_prop in last step's on_done (probe_loop scenario) + reverted unit check:
      - Pass 1: step:0 creates 2 pending rows (world_prop, prop), 1 trigger; cleanup skips
        because run still has pending payout step:0.
      - Pass 2: still 1 trigger, still 2 pending rows, payout step:0 still pending.
      - Mark prop modeled & not pending -> Pass 3: step (2) applies step:0 (rows promoted live,
        payout step:0 applied), then step (3) sees no remaining pending payouts and cleans up
        both non-permanent rows (world_prop reverted, prop reverted); trigger count stays 1.
      - Pass 4: trigger count stays 1, rows stay [reverted, reverted].
      - Direct unit check: an ended run whose only row of key "k" is "reverted" ->
        quest_effects._apply_entry(...) returns ("done", None, "") and adds no row.
      Fails on d026dc0fb: cleanup marks pending rows gone/revert_pending while step:0 is pending,
      and _apply_entry ignores non-pending/live rows so every pass_once creates a new prop.

  [2] validate_template rejects a reward targeting a non-permanent setup effect key:
      - probe_reward template (setup create_item "box" without permanent; reward give_item "box")
        -> issues include ("rewards.0.params.item", "not_permanent") with exact message
        "A reward can only use a permanent object: this one is removed when the quest ends".
      - Same template with setup_effects[0]["permanent"] = True -> no "not_permanent" issue.
      Fails on d026dc0fb: validate_template returns [] for probe_reward template.

  [3] _step_setup withdraws announcement if run is cancelled between finish_preparing and _announce:
      - Monkeypatch quest_engine._announce to cancel the run FIRST (while news_event_id is still
        empty, so cancel_run's own withdraw finds nothing) and THEN call the original _announce
        with the stale run dict.
      - After pass_once(), the run state is "cancelled", news_event_id is recorded on the run,
        and that event no longer exists in events.get_all_events().
      Fails on d026dc0fb: _step_setup does not re-read the run after _announce, so the event
      created after the cancel stays.

  [4] build_tool_step_prompt puts quest_block in prompt.user ONLY (never prompt.system):
      - With app.core.quest_prompt.block_for patched to "- QUEST-SENTINEL":
        "QUEST-SENTINEL" in prompt.user and "QUEST-SENTINEL" not in prompt.system.
      - With block_for patched to "": "Quests you are part of" not in prompt.user.
      Fails on d026dc0fb: build_tool_step_prompt does not pass quest_block and tool_step_turn.md
      does not render it.

  [6] random_events._try_generate_secret_hint_event skips quest-source secrets:
      - Two characters in one location, target owns only a source="quest" secret ->
        returns False and app.core.llm_router.llm_call is never called.
      Fails on d026dc0fb: candidate filter does not skip source=="quest", so llm_call is called.

  [7] npc_actions._with_action_context uses quest_block variable (not extension_prompt):
      - With app.core.quest_prompt.block_for patched to "- QUEST-SENTINEL" (no extension provider):
        _with_action_context(name, vars) sets extension_prompt == "" and
        quest_block == "- QUEST-SENTINEL".
      - render_task("npc_action", **vars) puts "QUEST-SENTINEL" in user part and does NOT include
        "or the optional `action` described below" in system part.
      Fails on d026dc0fb: quest block is appended to extension_prompt, activating the action
      contract text in the system prompt and putting the sentinel in system instead of user.

  [9] secrets.known_about_others_block skips quest-source secrets:
      - Knower knows only a quest secret of another character -> known_about_others_block == "".
      - After also learning a normal secret of that character -> block contains the normal secret
        content and does NOT contain the quest secret content.
      Fails on d026dc0fb: known_about_others_block includes the quest secret.

  [Minor B] quests.permanent_props_of_ended_runs marks missing-sidecar rows "gone":
      - Done run with a permanent prop row whose props/<id> directory was deleted ->
        permanent_props_of_ended_runs() excludes it and its status in list_objects is "gone".
      Fails on d026dc0fb: permanent_props_of_ended_runs returns the row and leaves status "live".
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quest-review-fixes-"))
STORAGE = TMP / "world"
INSTANCE = TMP / "instance"
STORAGE.mkdir()
INSTANCE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")

import app  # noqa: E402
assert Path(app.__file__).resolve().is_relative_to(ROOT), f"wrong tree: {app.__file__}"

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(INSTANCE)

from app.core import (  # noqa: E402
    db,
    npc_actions,
    prompt_templates,
    props,
    quest_effects as qfx,
    quest_engine as qe,
    quest_prompt,
    quest_types as qt,
    random_events,
)
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_time  # noqa: E402
from app.core.tool_step_prompt import build_tool_step_prompt  # noqa: E402
from app.models import character as chars, events, quests, secrets, world  # noqa: E402
from app.skills.base import TurnFacts  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}: got={got!r} want={want!r}")
        FAILURES.append(label)


def main() -> int:
    db.init_schema()
    qt.register()
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))

    world.upsert_location(
        {
            "id": "L1",
            "name": "Wood",
            "pos_x": 100.0,
            "pos_z": -50.0,
            "entry_room": "glade",
            "rooms": [{"id": "glade", "name": "Glade", "layout": {"x": 0, "y": 0, "w": 6, "d": 4}}],
        },
        sync_world=False,
    )
    chars.save_character_profile(
        "Alice",
        {"name": "Alice", "current_location": "L1", "current_room": "glade", "status_effects": {}},
        create_new=True,
    )
    chars.save_character_profile(
        "Bob",
        {"name": "Bob", "current_location": "L1", "current_room": "glade", "status_effects": {}},
        create_new=True,
    )

    # ── [1] non-permanent create_prop in step on_done + reverted unit check ──
    print("[1] non-permanent create_prop in step on_done")
    triggers: list[str] = []
    pending_pids: set[str] = set()
    modeled_pids: set[str] = set()

    orig_trigger = props.trigger_generation
    orig_is_pending = props.is_pending
    orig_has_model = qfx._prop_has_model
    orig_media_problem = qfx._prop_media_problem
    try:
        def fake_trigger(pid, **kw):
            triggers.append(pid)
            pending_pids.add(pid)
            return True

        props.trigger_generation = fake_trigger
        props.is_pending = lambda pid="": ([pid] if pid in pending_pids else []) if pid else sorted(pending_pids)
        qfx._prop_has_model = lambda pid: pid in modeled_pids
        qfx._prop_media_problem = lambda: ""

        tpl1 = {
            "id": "t_loop",
            "title": "Loop Test",
            "roles": [{"key": "wood", "kind": "location"}],
            "steps": [
                {
                    "id": "s1",
                    "text": "x",
                    "condition": {"type": "at_place", "params": {"place": "wood"}},
                    "on_done": [
                        {
                            "key": "rock",
                            "type": "create_prop",
                            "params": {"name": "Rock", "prompt": "rock", "near": "wood"},
                        }
                    ],
                }
            ],
        }
        run1 = quests.create_run(template=tpl1, bindings={"wood": {"location_id": "L1"}}, state="open")
        r1 = quests.record_step_done(run1["id"], 0, avatar="Alice", mind="Alice")
        check("[1] run state done", r1["state"], "done")

        # Pass 1
        qfx.pass_once()
        check("[1] pass 1 triggers == 1", len(triggers), 1)
        check(
            "[1] pass 1 rows pending",
            [(o["effect_key"], o["kind"], o["status"]) for o in quests.list_objects(run1["id"])],
            [("rock", "world_prop", "pending"), ("rock", "prop", "pending")],
        )
        check(
            "[1] pass 1 payout pending",
            [(p["position"], p["state"]) for p in quests.list_payouts(states=(), run_id=run1["id"])],
            [("step:0", "pending")],
        )

        # Pass 2
        qfx.pass_once()
        check("[1] pass 2 still 1 trigger", len(triggers), 1)
        check(
            "[1] pass 2 still 2 pending rows",
            [(o["effect_key"], o["kind"], o["status"]) for o in quests.list_objects(run1["id"])],
            [("rock", "world_prop", "pending"), ("rock", "prop", "pending")],
        )

        # Mark prop modeled and not pending -> Pass 3 applies payout and cleans up
        pid1 = triggers[0]
        pending_pids.discard(pid1)
        modeled_pids.add(pid1)
        qfx.pass_once()
        check(
            "[1] pass 3 payout applied",
            [(p["position"], p["state"]) for p in quests.list_payouts(states=(), run_id=run1["id"])],
            [("step:0", "applied")],
        )
        check(
            "[1] pass 3 rows reverted",
            [(o["effect_key"], o["kind"], o["status"]) for o in quests.list_objects(run1["id"])],
            [("rock", "world_prop", "reverted"), ("rock", "prop", "reverted")],
        )
        check("[1] pass 3 trigger count stays 1", len(triggers), 1)

        # Pass 4: stays quiet
        qfx.pass_once()
        check("[1] pass 4 trigger count stays 1", len(triggers), 1)
        check(
            "[1] pass 4 rows stay reverted",
            [(o["effect_key"], o["kind"], o["status"]) for o in quests.list_objects(run1["id"])],
            [("rock", "world_prop", "reverted"), ("rock", "prop", "reverted")],
        )

        # Direct unit check: ended run whose only row of key "k" is "reverted"
        run1b = quests.create_run(template=tpl1, bindings={"wood": {"location_id": "L1"}}, state="open")
        quests.set_run_state(run1b["id"], "done")
        oid = quests.add_object(
            run1b["id"],
            effect_key="k",
            position="step:0",
            kind="prop",
            ref={"prop_id": "gone_prop"},
            label="k",
            permanent=False,
            status="reverted",
        )
        assert oid > 0
        entries = [{"key": "k", "type": "narrate", "params": {"text": "hi"}}]
        outcome = qfx._apply_entry(quests.get_run(run1b["id"]), entries, 0, "step:0", "Alice")
        check("[1] reverted-row _apply_entry returns done", outcome, ("done", None, ""))
        check("[1] reverted-row adds no row", len(quests.list_objects(run1b["id"])), 1)
    finally:
        props.trigger_generation = orig_trigger
        props.is_pending = orig_is_pending
        qfx._prop_has_model = orig_has_model
        qfx._prop_media_problem = orig_media_problem

    # ── [2] reward targeting non-permanent effect key ──
    print("[2] validate_template non_permanent reward target")
    tpl2 = {
        "id": "t_rew",
        "title": "Reward Test",
        "roles": [{"key": "wood", "kind": "location"}],
        "setup_effects": [{"key": "box", "type": "create_item", "params": {"name": "Box", "category": "tool"}}],
        "steps": [{"id": "s1", "text": "Go", "condition": {"type": "at_place", "params": {"place": "wood"}}}],
        "rewards": [{"key": "gift", "type": "give_item", "permanent": True, "params": {"item": "box"}}],
    }
    issues2 = qe.validate_template(tpl2)
    check(
        "[2] non-permanent setup item in reward flagged",
        [(i["path"], i["code"], i["message"]) for i in issues2],
        [(
            "rewards.0.params.item",
            "not_permanent",
            "A reward can only use a permanent object: this one is removed when the quest ends",
        )],
    )
    tpl2_perm = {
        **tpl2,
        "setup_effects": [
            {"key": "box", "type": "create_item", "permanent": True, "params": {"name": "Box", "category": "tool"}}
        ],
    }
    issues2_perm = qe.validate_template(tpl2_perm)
    check("[2] permanent setup item in reward clean", issues2_perm, [])

    # ── [3] _step_setup race with cancel during _announce ──
    print("[3] _step_setup withdraws announcement on cancel race")
    tpl3 = quests.create_template(
        title="Announce Race",
        summary="A race test.",
        roles=[{"key": "wood", "kind": "location"}],
        setup_effects=[{"key": "news1", "type": "post_news", "params": {"text": "Setup news."}}],
        steps=[{"id": "s1", "text": "Go", "condition": {"type": "at_place", "params": {"place": "wood"}}}],
        state="ready",
    )
    run3 = qe.start_run(tpl3["id"], {"wood": {"location_id": "L1"}})
    check("[3] starts preparing", run3["state"], "preparing")
    orig_announce = qe._announce

    def _cancel_then_announce(run_dict):
        qe.cancel_run(run_dict["id"])
        orig_announce(run_dict)

    qe._announce = _cancel_then_announce
    try:
        qfx.pass_once()
    finally:
        qe._announce = orig_announce
    run3_after = quests.get_run(run3["id"])
    news_eid = (run3_after or {}).get("news_event_id") or ""
    check("[3] run ended cancelled with news_event_id recorded", (run3_after["state"], bool(news_eid)), ("cancelled", True))
    all_eids = {e.get("id") for e in events.get_all_events()}
    check("[3] announcement event withdrawn", news_eid in all_eids, False)

    # ── [4] build_tool_step_prompt quest_block ──
    print("[4] build_tool_step_prompt per-turn quest_block")
    class _Skill:
        POSE_SETTER = False
        name = "DummySkill"
        brief = "Do a thing."
        def available_now(self, facts):
            return None
        def decision_menu(self, character):
            return []

    dummy = _Skill()
    mgr = Mock(get_skill_by_name=lambda n: dummy if n == "DummySkill" else None,
               tool_names_with_flag=lambda flag: frozenset())
    with patch("app.core.dependencies.get_skill_manager", return_value=mgr), \
         patch("app.models.character.get_character_language_instruction", return_value="Always respond in English."), \
         patch("app.core.flag_lifecycle.inactive_clearing_tools", return_value=set()), \
         patch("app.routes.chat._marker_travel_refusal", return_value="has_movement_verb"), \
         patch("app.models.intents.build_open_intents_brief", return_value=""), \
         patch.object(quest_prompt, "block_for", return_value="- QUEST-SENTINEL"):
        p_with = build_tool_step_prompt(
            "Alice", mode="respond", rp_response="Hello.", user_input="Hi.",
            tools=[dummy], facts=TurnFacts("Alice", "respond", ("Bob",)),
            tool_format="tag",
        )
    check("[4] sentinel in prompt.user", "QUEST-SENTINEL" in p_with.user, True)
    check("[4] sentinel not in prompt.system", "QUEST-SENTINEL" in p_with.system, False)
    with patch("app.core.dependencies.get_skill_manager", return_value=mgr), \
         patch("app.models.character.get_character_language_instruction", return_value="Always respond in English."), \
         patch("app.core.flag_lifecycle.inactive_clearing_tools", return_value=set()), \
         patch("app.routes.chat._marker_travel_refusal", return_value="has_movement_verb"), \
         patch("app.models.intents.build_open_intents_brief", return_value=""), \
         patch.object(quest_prompt, "block_for", return_value=""):
        p_empty = build_tool_step_prompt(
            "Alice", mode="respond", rp_response="Hello.", user_input="Hi.",
            tools=[dummy], facts=TurnFacts("Alice", "respond", ("Bob",)),
            tool_format="tag",
        )
    check("[4] header absent when block_for empty", "Quests you are part of" in p_empty.user, False)

    # ── [6] random_events skips quest secrets ──
    print("[6] random_events skips quest-source secrets")
    qsec = secrets.add_secret(
        "Alice",
        "The secret quest hint under the mossy stone.",
        category="personal",
        severity=3,
        source="quest",
        source_ref="quest_run:qr_fake",
    )
    llm_calls = []
    with patch("app.core.llm_router.llm_call", side_effect=lambda *a, **k: llm_calls.append((a, k))):
        res6 = random_events._try_generate_secret_hint_event(
            "L1", {"id": "L1", "name": "Wood"}, ["Alice", "Bob"], {}
        )
    check("[6] returns False for quest-only secret", res6, False)
    check("[6] llm_call never invoked", len(llm_calls), 0)

    # ── [7] npc_actions quest_block variable ──
    print("[7] npc_actions own quest_block variable")
    base_vars = {
        "location_id": "L1",
        "npc_name": "Alice",
        "npc_role": "Woodcutter",
        "standing_task": "Chop wood.",
        "location_name": "Wood",
        "current_room_id": "glade",
        "current_room_name": "Glade",
        "current_activity": "",
        "game_time_label": "Day 10, 12:00",
        "rooms": [{"id": "glade", "name": "Glade", "hint": "", "places": ""}],
        "home": "",
        "pose_keys": ["standing"],
        "npc_goals": "",
        "arrival_reason": "",
        "dialogue_style": "",
        "talk_allowed": False,
        "present": [],
        "pair_keys": [],
        "recent": [],
    }
    with patch.object(quest_prompt, "block_for", return_value="- QUEST-SENTINEL"):
        ctx7 = npc_actions._with_action_context("Alice", dict(base_vars))
    check("[7] extension_prompt stays empty", ctx7.get("extension_prompt"), "")
    check("[7] quest_block set", ctx7.get("quest_block"), "- QUEST-SENTINEL")
    sys7, user7 = prompt_templates.render_task("npc_action", **ctx7)
    check("[7] sentinel in user part", "QUEST-SENTINEL" in user7, True)
    check("[7] sentinel not in system part", "QUEST-SENTINEL" in sys7, False)
    check(
        "[7] optional action contract absent from system part",
        "or the optional `action` described below" in sys7,
        False,
    )

    # ── [9] secrets.known_about_others_block skips quest secrets ──
    print("[9] secrets.known_about_others_block skips quest secrets")
    check("[9] add_known_by quest secret", secrets.add_known_by("Alice", qsec["id"], "Bob"), True)
    check("[9] Bob gets empty block for quest-only known secret", secrets.known_about_others_block("Bob"), "")
    nsec = secrets.add_secret("Alice", "Alice broke the lantern last winter.", category="personal", severity=2, source="manual")
    check("[9] add_known_by normal secret", secrets.add_known_by("Alice", nsec["id"], "Bob"), True)
    block9 = secrets.known_about_others_block("Bob")
    check("[9] normal secret shown", "Alice broke the lantern last winter." in block9, True)
    check("[9] quest secret excluded", "mossy stone" in block9, False)

    # ── [Minor B] permanent_props_of_ended_runs marks missing sidecar gone ──
    print("[Minor B] permanent_props_of_ended_runs missing sidecar -> gone")
    p_del = props.create_prop(name="Vanished Statue", description="stone", source="generated", quest_run="qr_minb")
    pid_del = p_del["id"]
    run_b = quests.create_run(template=tpl2_perm, bindings={"wood": {"location_id": "L1"}}, state="open")
    quests.set_run_state(run_b["id"], "done")
    oid_b = quests.add_object(
        run_b["id"],
        effect_key="statue",
        position="setup",
        kind="prop",
        ref={"prop_id": pid_del},
        label="Vanished Statue",
        permanent=True,
        status="live",
    )
    shutil.rmtree(props._prop_dir(pid_del))
    remaining_ids = [o["id"] for o in quests.permanent_props_of_ended_runs()]
    check("[Minor B] deleted prop excluded", oid_b in remaining_ids, False)
    row_b = next(o for o in quests.list_objects(run_b["id"]) if o["id"] == oid_b)
    check("[Minor B] row status marked gone", row_b["status"], "gone")

    shutil.rmtree(TMP, ignore_errors=True)
    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
