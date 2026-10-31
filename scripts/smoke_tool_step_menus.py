#!/usr/bin/env python3
"""Exact per-turn furniture and pair menus, without a live world.

Usage: ./.venv/bin/python scripts/smoke_tool_step_menus.py

Hand-derived expectations: the fake room has Bench/Rest (solo), Bench/Read
(pair with Sam), blocked Chair/Sit and blocked Bed/Nap. Two Bench placements
must yield only two lines. Both listed requests pass the real named-request
validator; only the execution boundary is stubbed. A running Bench/Rest
adds the stop line FIRST. Free pair keys wave and greet are valid with Sam;
a busy or absent Sam yields no keys. The thought prompt must contain both
exact menu blocks. Twenty-five distinct offers/keys yield twenty lines,
including the running line in the furniture cap. Pending questions are not
menu entries. No pose keys or internal offer fields belong in the furniture menu.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import ExitStack
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="tool-menus-") as tmp:
        root = Path(tmp)
        os.environ.update(STORAGE_DIR=str(root / "world"), INSTANCE_DIR=str(root / "instance"),
                          ANIMATION_CLIPS_DIR=str(root / "clips"), ANIMATION_RIG_FILE=str(root / "rig.fbx"))
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config, db
        paths.get_config_path().write_text("{}")
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        db.init_schema()
        from app.plugins.context import PluginContext
        from plugins.set_pose.skill_prop_action import PropActionSkill
        from plugins.interact.skill import InteractSkill
        from app.core import prop_actions as PA, prop_action_engine as PE, interaction_engine as IE
        from app.skills.base import TurnFacts
        from app.core.tool_step_prompt import build_tool_step_prompt
        from app.models import character as C

        for name in ("Alex", "Sam"):
            C.save_character_profile(name, dict(template="human-roleplay", current_location="test-house",
                                                current_room="lounge"), create_new=True)

        prop = PropActionSkill({}, PluginContext("set_pose"))
        pair = InteractSkill({}, PluginContext("interact"))
        # Template metadata normally installed by the package loader.
        import yaml
        template = Path("plugins/set_pose/templates/llm/skills/prop_action.md").read_text()
        meta = yaml.safe_load(template.split("---")[1])
        prop.name, prop.brief = meta["name"], meta["brief"]
        pair.name, pair.brief = "InteractWith", "Propose a pair action with a present partner."

        def offer(piece, action, enabled=True, partners=None):
            return dict(prop_label=piece, label=action, enabled=enabled, reason="" if enabled else "blocked",
                        required_partner=partners is not None, available_targets=partners or [],
                        distance_m=1, action_id=action, definition_revision="v1", target={})

        rows = [offer("Bench", "Rest"), offer("Bench", "Read", partners=[dict(partner="Sam", enabled=True, reason="")]),
                offer("Chair", "Sit", False), offer("Bed", "Nap", False, [dict(partner="Sam", enabled=False, reason="blocked")]),
                offer("Bench", "Rest")]
        state = dict(current=[], outgoing=[], incoming=[], recent_results=[])
        with ExitStack() as stack:
            stack.enter_context(patch.object(PA, "offers", return_value=rows))
            stack.enter_context(patch.object(PE, "state_for", return_value=state))
            stack.enter_context(patch.object(PA, "piece_label", return_value="Bench"))
            poses = stack.enter_context(patch.object(IE, "partner_poses", return_value=[("wave", "wave_pair"), ("greet", "greet_pair")]))
            expected = ["Bench | Rest", "Bench | Read | with partner"]
            assert prop.decision_menu("Alex") == expected, prop.decision_menu("Alex")
            # Run the actual skill and named validation, stubbing only execution.
            with patch.object(PE, "request_with_creation", return_value=(dict(status="walking", execution_id="test", reason=""), False)):
                for line in expected:
                    piece, action, *_ = line.split(" | ")
                    data = dict(agent_name="Alex", furniture=piece, action=action)
                    if "with partner" in line:
                        data["partner"] = "Sam"
                    result = json.loads(prop.execute(json.dumps(data)))
                    assert result["status"] != "refused", result
            print("[1] PASS: exact requestable furniture menu; real skill validation accepts every entry")
            state["current"] = [dict(actor="Alex", partner="", target={}, label="Rest")]
            running = 'running: Bench | Rest - to get up or leave it: {"stop": true}'
            assert prop.decision_menu("Alex") == [running, *expected]
            assert "get" in prop.brief and '{"stop":true}' in prop.brief
            assert "get" in meta["action_hint"] and '{"stop":true}' in meta["action_hint"]
            print("[2] PASS: running action first; brief and hint explain getting up")
            assert pair.decision_menu("Alex") == ["wave", "greet"]
            with patch.object(IE, "check_can_pair", return_value="busy"):
                assert pair.decision_menu("Alex") == []
            sam = C.get_character_profile("Sam")
            sam["current_room"] = "other-room"
            C.save_character_profile("Sam", sam)
            assert pair.decision_menu("Alex") == []
            sam["current_room"] = "lounge"
            C.save_character_profile("Sam", sam)
            print("[3] PASS: only valid free pair keys; empty with nobody eligible")
            manager = Mock(tool_names_with_flag=lambda flag: frozenset(), get_skill_by_name=lambda name: {prop.name: prop, pair.name: pair}.get(name))
            with ExitStack() as prompt_stack:
                prompt_stack.enter_context(patch("app.core.dependencies.get_skill_manager", return_value=manager))
                prompt_stack.enter_context(patch.object(prop, "available_now", return_value=None))
                prompt_stack.enter_context(patch("app.core.streaming.open_questions_note", return_value=""))
                prompt_stack.enter_context(patch("app.routes.chat._marker_travel_refusal", return_value="unavailable"))
                prompt_stack.enter_context(patch("app.models.intents.build_open_intents_brief", return_value=""))
                rendered = build_tool_step_prompt("Alex", mode="thought", rp_response="I get up from the bench and wave to Sam.",
                    user_input="", tools=[prop, pair], facts=TurnFacts("Alex", "thought", ("Sam",)), tool_format="json")
            for skill in (prop, pair):
                block = f"{skill.name} takes these names — copy one exactly:\n" + "".join(f"- {line}\n" for line in skill.decision_menu("Alex"))
                assert block.rstrip() in rendered.user, rendered.user
            print("[4] PASS: thought user part includes both exact menu blocks")
            print("RENDERED USER PART\n" + rendered.user + "\nEND USER PART")
            rows[:] = [offer(f"Bench {n}", "Rest") for n in range(25)]
            assert len(prop.decision_menu("Alex")) == 20
            assert prop.decision_menu("Alex")[0] == running
            state["current"] = []
            assert len(prop.decision_menu("Alex")) == 20
            poses.return_value = [(f"wave_{n}", "wave_pair") for n in range(25)]
            assert pair.decision_menu("Alex") == [f"wave_{n}" for n in range(20)]
            print("[5] PASS: both menus capped at 20, running line included")
    print("ALL OK")


if __name__ == "__main__":
    main()
