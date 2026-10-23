#!/usr/bin/env python3
"""Chat absolute movement cap and template checks.

Usage: ./.venv/bin/python scripts/smoke_stat_chat_cap.py

Hand-derived Task 4: cap 15: -10 -> -10, -10 -> -5, -10 -> {};
+5 -> {} because |-10|+|-5|=15. -40 passes without consuming budget.
Next game hour -10 -> -10. Cap 0 returns unchanged deltas.
Per-stat and per-character budgets are independent. Exact turning-point
boundary +/-30 bypasses the cap, while +/-29 consumes ordinary budget.
Both stats_enabled branches must render under StrictUndefined. Rest
values come from resolved rules; None omits the rest-value phrase.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORAGE_DIR"] = os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.core import stat_rules as rules
        from app.core.game_time import GameTime
        clock = [3600]
        with patch("app.core.timeutils.game_time", side_effect=lambda: GameTime(clock[0])), patch(
                "app.core.stat_rules.get_setting", return_value=15):
            cap = rules.cap_chat_deltas
            for delta, expected in [(-10, -10), (-10, -5), (-10, 0), (5, 0), (-40, -40)]:
                assert cap("A", {"stamina": delta}) == ({"stamina": expected} if expected else {})
            assert cap("A", {"attention": 29}) == {"attention": 15}
            assert cap("B", {"stamina": -30}) == {"stamina": -30}
            assert cap("B", {"stamina": 30}) == {"stamina": 30}
            assert cap("B", {"stamina": 5}) == {"stamina": 5}
            assert cap("B", {"stamina": -29}) == {"stamina": -10}
            clock[0] = 7199
            assert cap("A", {"stamina": 5}) == {}
            clock[0] = 7200
            assert cap("A", {"stamina": -10}) == {"stamina": -10}
        with patch("app.core.stat_rules.get_setting", return_value=0):
            assert cap("A", {"stamina": -20}) == {"stamina": -20}
        from app.core.stat_effects import build_stat_list
        template = {"sections": [{"fields": [{"key": "stamina", "store": "status_effects", "hint": "A hint"}]}]}
        with patch("app.models.character_template.is_feature_enabled", return_value=True), patch(
                "app.models.character_template.get_template", return_value=template), patch(
                "app.models.character.get_character_profile", return_value={"template": "test", "status_effects": {"stamina": 42}}), patch(
                "app.core.stat_rules.rules_for_character", return_value={"stamina": {"baseline": 65}}) as resolved:
            assert build_stat_list("A") == (True, "- stamina, currently 42/100, rests at 65 — A hint")
            resolved.return_value = {"stamina": {"baseline": None}}
            assert build_stat_list("A") == (True, "- stamina, currently 42/100 — A hint")
        # Exercise the route consumer with the real cap and profile writer.
        from app.core.db import transaction
        from app.routes.chat import _extract_context_from_last_chat
        from app.models.character import get_character_profile
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                         ("Route", "test", json.dumps({"status_effects": {"stamina": 50}}), "{}", "", ""))
        response = SimpleNamespace(content=json.dumps({"stats": {"stamina": -10}}))
        with patch("app.core.timeutils.game_time", return_value=GameTime(10800)), patch(
                "app.core.stat_rules.get_setting", return_value=15), patch(
                "app.core.llm_router.llm_call", return_value=response), patch(
                "app.core.chat_engine.run_follow_up", side_effect=lambda callback, **kwargs: callback()), patch(
                "app.models.character.is_outfit_locked", return_value=True), patch(
                "app.models.account.get_active_character", return_value=""), patch(
                "app.models.account.is_player_controlled", return_value=False), patch(
                "app.core.stat_effects.build_stat_list", return_value=(True, "values")):
            for expected in (40, 35, 35):
                _extract_context_from_last_chat("Route", [{"role": "assistant", "content": "A tiring beat"}])
                assert get_character_profile("Route")["status_effects"]["stamina"] == expected
        from app.core.prompt_templates import render_task
        for enabled in (False, True):
            render_task("extraction_chat_state", target_name="A", is_avatar=False,
                        stats_enabled=enabled, stat_list="values", pose_keys=[], current_pose="",
                        source_label="reply", source_text="hello", context_text="",
                        outfit_locked=True, piece_list=[])
        for per_hour in (False, True):
            render_task("stat_effects", target_name="A", stat_list="values", per_hour=per_hour, situation_text="a pause")
        print("PASS chat absolute cap, turning points, isolation, reset, baseline and strict templates")


if __name__ == "__main__":
    main()
