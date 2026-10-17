#!/usr/bin/env python3
"""Intent limits against temporary storage.

Usage: ./.venv/bin/python scripts/smoke_intent_limits.py

Hand-derived expectations: eight plans at cap six evict the two oldest
priority-five plans, preserving the new priority-five plan. At D001 09:00,
player now expires D002 09:00; standing D008 09:00. 10:00 is today before
ten, tomorrow at/after ten; +2d is D003 08:30; a one-digit
hour (at:9:30) is D001 09:30. A bump for an ended intent still completes the
run so its one-time job is removed. Goal TTLs are 2/7/30 days;
replacement retains three goals and expires only discarded package goals.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="intent-limits-") as tmp:
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
        from app.core import paths
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp) / "instance")
        from app.core import config, db
        config.load(Path(tmp) / "config.json")
        db.init_schema()
        from app.models import intents
        assert callable(getattr(intents, "enforce_active_caps", None)), "active caps missing"
        rows = []
        for n, priority in enumerate([5, 5, 4, 3, 3, 2, 1, 5]):
            with patch.object(intents, "utc_now_iso", return_value=f"2026-01-01T00:00:{n:02d}+00:00"):
                rows.append(intents.create_intent(owner="demo", title=f"Plan {n}", priority=priority))
        assert intents.enforce_active_caps("demo", keep_ids=(rows[-1]["id"],)) == 2
        assert [intents.get_intent(r["id"])["status"] for r in rows] == [
            "expired", "expired", "active", "active", "active", "active", "active", "active"]
        assert all(intents.get_intent(r["id"])["meta"]["expired_reason"] == "cap" for r in rows[:2])
        print("PASS caps and eviction order")
        exempt = [intents.create_intent(owner="demo", title=f"Exempt {n}", source=source, meta=meta)
                  for n, (source, meta) in enumerate([
                      ("character", {"origin": "admin"}),
                      ("character", {"origin": "package_goal"}),
                      ("character", {"managed": True})])]
        guest = intents.create_intent(owner="", title="Participant only", participants={"demo": {}})
        players = [intents.create_intent(owner="demo", title=f"Player {n}", source="human") for n in range(6)]
        with patch.object(intents, "is_managed_intent", side_effect=lambda it: bool(it["meta"].get("managed"))):
            assert intents.enforce_active_caps("demo") == 2
        assert all(intents.get_intent(it["id"])["status"] == "active" for it in exempt + [guest])
        assert sum(intents.get_intent(it["id"])["status"] == "active" for it in players) == 4
        for it in intents.list_intents():
            intents.delete_intent(it["id"])
        for n in range(8):
            intents.create_intent(owner="demo", title=f"Legacy {n}")
        from app.core.periodic_jobs import _sub_assignment_expiry
        _sub_assignment_expiry()
        assert len(intents.list_intents(owner="demo", status="active")) == 6
        for it in intents.list_intents():
            intents.delete_intent(it["id"])
        for n in range(13):
            intents.create_intent(owner="demo", title=f"Prompt plan {n}", meta={"origin": "admin"})
        assert intents.build_intents_prompt_section("demo").count("(id ") == 12
        assert "(+1 more)" in intents.build_intents_prompt_section("demo")
        assert intents.build_intents_prompt_section("demo", 0).count("(id ") == 13
        with patch.dict(config._CONFIG, {"intents": {"max_active_self": 0, "max_active_player": 0}}):
            assert intents.enforce_active_caps("demo") == 0
        from app.routes.intents import _create_route_sync
        admin = _create_route_sync({"owner": "demo", "title": "Admin plan"})
        assert admin["meta"]["origin"] == "admin" and admin["expires_at"] == ""
        with patch.dict(config._CONFIG, {"intents": {"max_active_self": 1}}):
            previous = intents.create_intent(owner="demo", title="Previous marker plan", priority=1)
            new = intents.parse_and_apply_intent_markers("demo", "[INTENT: New protected plan | prio=5]")[0]
            assert new["meta"]["origin"] == "marker"
            assert intents.get_intent(new["id"])["status"] == "active"
            assert intents.get_intent(previous["id"])["meta"]["expired_reason"] == "cap"
        print("PASS exemptions, player cap, periodic legacy trim, marker integration and prompt cap")

        from app.core.game_time import GameTime
        fixed = GameTime.parse("Y0001-D001T09:00:00")
        with patch.object(intents, "game_time", return_value=fixed):
            assert intents.default_intent_expiry({"kind": "now"}, "human") == "Y0001-D002T09:00:00"
            assert intents.default_intent_expiry({"kind": "standing"}, "human") == "Y0001-D008T09:00:00"
            for token, expected in [("at:10:00", "Y0001-D001T10:00:00"),
                                    ("at:tomorrow 10:00", "Y0001-D002T10:00:00"),
                                    ("AT:+2D 08:30", "Y0001-D003T08:30:00"),
                                    ("at:9:30", "Y0001-D001T09:30:00")]:
                assert intents._when_to_trigger(token) == {"kind": "at_time", "run_date": expected}
            for token in ("at:garbage", "at:25:00", "at:+31d 08:00", "at:tomorrow 10:60"):
                assert intents._when_to_trigger(token) == {"kind": "standing"}
        with patch.object(intents, "game_time", return_value=GameTime.parse("Y0001-D001T10:00:00")):
            assert intents._when_to_trigger("at:10:00")["run_date"] == "Y0001-D002T10:00:00"
        with patch.object(intents, "game_time", return_value=fixed):
            assert intents.default_intent_expiry({"kind": "at_location"}, "human") == "Y0001-D008T09:00:00"
            for source in ("human", "character"):
                assert intents.default_intent_expiry({"kind": "at_time", "run_date": "Y0001-D002T10:00:00"}, source) == "Y0001-D002T11:00:00"
            with patch.dict(config._CONFIG, {"intents": {"player_task_now_ttl_days": 0, "player_task_ttl_days": 0}}):
                assert intents.default_intent_expiry({"kind": "now"}, "human") == ""
                assert intents.default_intent_expiry({"kind": "standing"}, "human") == ""
            deadline = intents.create_intent(owner="demo", title="Deadline plan", expires_at=fixed.canonical(), meta={"preserved": True})
            assert intents.expire_overdue() == 1
            assert intents.get_intent(deadline["id"])["meta"] == {"preserved": True, "expired_reason": "deadline"}
            assert not intents.expire_intent(deadline["id"], "cap")
            assert not intents.expire_intent("missing", "cap")
            assert intents._when_to_trigger("at:+0d 08:30")["run_date"] == "Y0001-D001T08:30:00"
        print("PASS player TTLs, unlimited lifetimes, deadline metadata and absolute times")

        from plugins.retrospect.skill import RetrospectSkill
        from app.plugins.context import PluginContext
        skill = RetrospectSkill({}, PluginContext("retrospect"))
        old = intents.create_intent(owner="demo", title="Discarded reflection goal", meta={"origin": "retrospect_goal"})
        kept = intents.create_intent(owner="demo", title="Confirmed reflection goal", meta={"origin": "retrospect_goal"}, expires_at="Y0001-D001T00:00:00")
        goals = [{"text": "Confirmed reflection goal", "category": "short_term"},
                 {"text": "Second reflection goal", "category": "mid_term"},
                 {"text": "Third reflection goal", "category": "long_term"},
                 {"text": "Fourth reflection goal", "category": "mid_term"}]
        with patch("app.core.soul_writer.rewrite_file", return_value=4), patch("app.core.timeutils.game_time", return_value=fixed):
            skill._replace_entries("demo", "goals", goals, "en")
        assert intents.get_intent(old["id"])["meta"]["expired_reason"] == "replaced"
        assert intents.get_intent(kept["id"])["expires_at"] == "Y0001-D003T09:00:00"
        own = [it for it in intents.list_intents(status="active") if it["meta"].get("origin") == "retrospect_goal"]
        assert len(own) == 3
        assert {it["expires_at"] for it in own} == {"Y0001-D003T09:00:00", "Y0001-D008T09:00:00", "Y0001-D031T09:00:00"}
        before = intents.list_intents()
        skill._replace_entries("demo", "goals", [], "en")
        skill._replace_entries("demo", "goals", [{"text": "Invalid goal", "category": "invalid"}], "en")
        assert intents.list_intents() == before
        print("PASS reflection replacement, TTL refresh, cap and empty buckets")
        from app.scheduler.scheduler_manager import SchedulerManager
        from unittest.mock import Mock
        manager = SchedulerManager.__new__(SchedulerManager)
        manager._log_execution = Mock()
        manager._save_jobs_for_character = Mock()
        loop = Mock()
        job = {"id": "demo-job", "character": "demo", "action": {"type": "intent_bump", "intent_id": kept["id"]}}
        with patch("app.core.agent_loop.get_agent_loop", return_value=loop), patch("app.models.character.is_character_sleeping", return_value=False):
            assert manager._execute_job(job)["status"] == "success"
            loop.bump.assert_called_once()
            intents.complete_intent(kept["id"])
            loop.reset_mock()
            # A done intent bumps nobody, but the run still completes so a
            # one-time job is removed instead of being retried every tick.
            manager.jobs_data = {"jobs": [{"id": "demo-once"}]}
            manager._game_jobs = {"demo-once": object()}
            once = {"id": "demo-once", "character": "demo",
                    "trigger": {"type": "date", "one_time": True},
                    "action": {"type": "intent_bump", "intent_id": kept["id"]}}
            out = manager._execute_job(once)
            assert out["status"] == "success" and out["result"]["skipped"] == "intent_not_active", out
            assert manager.jobs_data["jobs"] == [] and "demo-once" not in manager._game_jobs
            loop.bump.assert_not_called()
            job["action"]["intent_id"] = "missing"
            assert manager._execute_job(job)["result"]["skipped"] == "intent_not_active"
            loop.bump.assert_not_called()
            job["action"]["intent_id"] = ""
            assert manager._execute_job(job)["status"] == "success"
            loop.bump.assert_called_once()
        print("PASS scheduler active/done/missing/commitment guards")


if __name__ == "__main__":
    main()
