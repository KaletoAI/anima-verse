#!/usr/bin/env python3
"""Per-turn tool availability without changing the character tool inventory.

Usage: ./.venv/bin/python scripts/smoke_tool_turn_availability.py

Hand-derived expectations: alone hides speech/pair/party verbs, but not travel,
clothes or sleep. Pose is hidden only in rp_first. A respond partner alone
needs no TalkTo; a third person does. Incoming pair, furniture and party
questions remain answerable after the sender leaves. Cooldown 9.7 hides a
post, zero allows it. An inactive end-state verb is hidden, active is offered.
Explicit brief metadata wins; fallback is the first description sentence.
Furniture needs a requestable offer or an owned live run. Storage is temporary.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="turn-tools-") as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        from app.skills.base import BaseSkill, TurnFacts, ToolSpec
        from app.core.streaming import turn_tools, decision_tools
        from app.plugins.context import PluginContext
        from app.plugins.loader import _apply_skill_meta, _parse_skill_entries, load_plugin
        from plugins.talk_to.skill import TalkToSkill
        from plugins.interact.skill import InteractSkill
        from plugins.party.skill import PartySkill
        from plugins.instagram.skill_post import InstagramSkill
        from plugins.set_pose.skill_prop_action import PropActionSkill

        class Plain(BaseSkill):
            def execute(self, raw):
                return "ok"

        ctx = PluginContext("demo")
        skills = {"TalkTo": TalkToSkill({}, ctx), "InteractWith": InteractSkill({}, ctx),
                  "InviteToParty": PartySkill({}, ctx, "invite"),
                  "JoinParty": PartySkill({}, ctx, "join"),
                  "Instagram": InstagramSkill({}, ctx), "PropAction": PropActionSkill({}, ctx)}
        for name in ("SetLocation", "ChangeOutfit", "Sleep", "SetActivity", "EndIntimate"):
            skills[name] = Plain({})
        for name, skill in skills.items():
            skill.name = name
        skills["SetActivity"].POSE_SETTER = True
        tools = list(skills.values())
        manager = SimpleNamespace(get_skill_by_name=skills.get)
        flags = [SimpleNamespace(cleared_by="end_demo", flag="demo_active")]
        alone = TurnFacts("demo", "thought", ())
        with patch("app.core.dependencies.get_skill_manager", return_value=manager), \
             patch("app.core.flag_lifecycle._specs", return_value=flags), \
             patch("app.core.flag_lifecycle._clear_tool_name", return_value="EndIntimate"), \
             patch("app.models.character.get_character_profile", return_value={}) as profile, \
             patch("app.core.interaction_engine.pending_invites_for", return_value=[]) as pair, \
             patch("app.core.party_engine.get_pending_invites_for", return_value=[]) as party, \
             patch("app.core.prop_action_store.live_runs", return_value=[]) as runs, \
             patch("app.core.prop_actions.offers", return_value=[]) as offers, \
             patch.object(skills["Instagram"], "cooldown_left_hours", return_value=0) as cooldown:
            def offered(facts=alone, rp_first=True):
                result, hidden = turn_tools(tools, facts, rp_first=rp_first)
                return {s.name for s in result}, hidden

            names, hidden = offered()
            assert {"TalkTo", "InteractWith", "InviteToParty", "JoinParty"} <= hidden.keys()
            assert {"SetLocation", "ChangeOutfit", "Sleep"} <= names
            assert len(tools) == len(skills)
            print("PASS [1] alone filters social tools; general tools remain")
            specs = [ToolSpec(name, "", lambda raw: "") for name in skills]
            selected, _ = turn_tools(specs, alone, rp_first=True)
            assert {tool.name for tool in selected} == names
            selected, _ = turn_tools({name: skill.execute for name, skill in skills.items()},
                                     alone, rp_first=True)
            assert set(selected) == names

            assert hidden["SetActivity"] == "pose comes from the state extraction"
            assert "SetActivity" in offered(rp_first=False)[0]
            assert isinstance(decision_tools(tools, suppress_in_person=False), list)
            print("PASS [2] pose setter only hidden in rp_first; decision_tools list preserved")
            assert "TalkTo" not in offered(TurnFacts("demo", "respond", ("Mira",), "Mira"))[0]
            assert "TalkTo" in offered(TurnFacts("demo", "respond", ("Mira", "Pixel"), "Mira"))[0]
            print("PASS [3] respond partner alone versus third person")
            pair.return_value = [{"inviter": "Mira", "invitee": "demo"}]
            assert "InteractWith" in offered()[0]
            pair.return_value = []
            runs.return_value = [{"actor": "Mira", "partner": "demo", "status": "awaiting_consent"}]
            assert "InteractWith" in offered()[0]
            assert "PropAction" in offered()[1]
            runs.return_value = []
            party.return_value = [{"inviter": "Mira", "invitee": "demo"}]
            assert {"JoinParty", "InviteToParty"} <= offered()[0]
            party.return_value = []
            print("PASS [4] departed senders leave pair/furniture/party answers offered")
            cooldown.return_value = 9.7
            assert "Instagram" in offered()[1]
            cooldown.return_value = 0
            assert "Instagram" in offered()[0]
            print("PASS [5] post cooldown filters availability")
            assert hidden["EndIntimate"] == "state not active"
            profile.return_value = {"demo_active": True}
            assert "EndIntimate" in offered()[0]
            print("PASS [6] end-state availability follows flag")
            assert "PropAction" in offered()[1]
            offers.return_value = [{"required_partner": False, "enabled": True}]
            assert "PropAction" in offered()[0]
            offers.return_value = [{"required_partner": False, "enabled": False}]
            assert "PropAction" in offered()[1]
            offers.return_value = [{"required_partner": True, "available_targets": [{"enabled": False}]}]
            assert "PropAction" in offered()[1]
            offers.return_value[0]["available_targets"][0]["enabled"] = True
            assert "PropAction" in offered()[0]
            offers.return_value = []
            runs.return_value = [{"actor": "demo", "partner": "", "status": "running"}]
            assert "PropAction" in offered()[0]
            runs.return_value = [{"actor": "Mira", "partner": "Pixel", "status": "running"}]
            assert "PropAction" in offered()[1]
            print("PASS [8] furniture requires requestable offers or own live run")

        plain = Plain({})
        plain.description = "First sentence. Second sentence."
        assert plain.brief == "First sentence."
        entry = _parse_skill_entries({"skill_id": "demo"})[0]
        with patch("app.core.prompt_templates.template_exists", return_value=True), \
             patch("app.core.prompt_templates.load_skill_meta", return_value={
                 "description": "Long description.", "brief": "Use for a demo; input: {}"}):
            _apply_skill_meta(plain, entry)
        assert plain.brief == "Use for a demo; input: {}"
        import yaml
        root = Path(__file__).resolve().parents[1]
        wanted = {"TalkTo", "SetLocation", "StartIntimate", "EndIntimate", "ChangeOutfit", "Act",
                  "InteractWith", "SendMessage", "Sleep", "WakeUp", "Instagram", "PropAction",
                  "GoToCharacter", "JoinParty", "InviteToParty"}
        found = set()
        missing_briefs = []
        files = list((root / "shared/templates/llm/skills").glob("*.md"))
        files += list((root / "plugins").glob("*/templates/llm/skills/*.md"))
        for path in files:
            raw = path.read_text()
            meta = dict(line.split(":", 1) for line in raw.split("---", 2)[1].splitlines() if ":" in line)
            meta = {key.strip(): value.strip() for key, value in meta.items()}
            if meta.get("name") in wanted:
                brief = meta.get("brief", "")
                if not brief:
                    missing_briefs.append(str(path.relative_to(root)))
                else:
                    assert len(brief) <= 200 and "\n" not in brief, path
                found.add(meta["name"])
        assert found == wanted, wanted - found
        from app.skills.outfit_change_skill import OutfitChangeSkill
        assert OutfitChangeSkill({}).brief
        from app.plugins.registry import Package
        manifest = yaml.safe_load((root / "plugins/set_pose/plugin.yaml").read_text())
        pkg = Package("set_pose", root / "plugins/set_pose", manifest,
                      skills=_parse_skill_entries(manifest))
        loaded = dict(load_plugin(pkg))
        assert loaded["set_pose"].POSE_SETTER and not loaded["prop_action"].POSE_SETTER
        if missing_briefs:
            print("FAIL [7] missing brief: " + ", ".join(missing_briefs))
            return 1
        print("PASS [7] explicit/fallback briefs, all short forms, manifest pose flag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
