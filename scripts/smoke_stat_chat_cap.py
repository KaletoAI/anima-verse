#!/usr/bin/env python3
"""Chat absolute movement cap and real extraction-consumer checks.

Usage: ./.venv/bin/python scripts/smoke_stat_chat_cap.py

Hand-derived Task 4: cap 15: -10 -> -10, -10 -> -5, -10 -> {};
+5 -> {} because |-10|+|-5|=15. -40 passes without consuming budget.
Next game hour -10 -> -10. Cap 0 returns unchanged deltas.
Per-stat and per-character budgets are independent. Exact turning-point
boundary +/-30 bypasses the cap, while +/-29 consumes ordinary budget.
The route consumer persists only the allowed -10/-5/0 movement from three
new self events, using canonical runtime state and structured stat results.
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
        # Exercise the route consumer with the real cap and profile writer.
        from app.core.db import transaction
        from app.routes.chat import _extract_context_from_last_chat
        from app.models.character import get_character_profile
        from app.core.stat_sources import StatExtractionContext, self_source
        template = {"features": {"status_effects_enabled": True},
                    "sections": [{"fields": [{"key": "stamina", "store": "status_effects"}]}]}
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                         ("Route", "test", "{}", "{}", "", ""))
            conn.execute("INSERT INTO character_state (character_name,meta) VALUES (?,?)",
                         ("Route", json.dumps({"status_effects": {"stamina": 50}})))
        response = SimpleNamespace(content=json.dumps({
            "stat_results": [{"event": "S0", "target": "T0", "deltas": {"stamina": -10}}]}))
        with patch("app.core.timeutils.game_time", return_value=GameTime(10800)), patch(
                "app.core.stat_rules.get_setting", return_value=15), patch(
                "app.core.llm_router.llm_call", return_value=response), patch(
                "app.core.chat_engine.run_follow_up", side_effect=lambda callback, **kwargs: callback()), patch(
                "app.models.character.is_outfit_locked", return_value=True), patch(
                "app.models.account.get_active_character", return_value=""), patch(
                "app.models.account.is_player_controlled", return_value=False), patch(
                "app.models.character_template.is_feature_enabled", return_value=True), patch(
                "app.models.character_template.get_template", return_value=template):
            for index, expected in enumerate((40, 35, 35)):
                source = self_source("Route", "A tiring beat", f"self:cap-{index}")
                context = StatExtractionContext((source,), source.event_id, "Route")
                _extract_context_from_last_chat(
                    "Route", [{"role": "assistant", "content": "A tiring beat"}],
                    stat_context=context)
                assert get_character_profile("Route")["status_effects"]["stamina"] == expected
        print("PASS chat absolute cap, turning points, isolation, reset and extraction consumer")


if __name__ == "__main__":
    main()
