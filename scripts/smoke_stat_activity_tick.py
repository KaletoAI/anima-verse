#!/usr/bin/env python3
"""Activity game-clock/cache checks.

Usage: ./.venv/bin/python scripts/smoke_stat_activity_tick.py

Hand-derived Task 3 cases: [a] first call establishes a baseline, no LLM.
[b] 30 game minutes lifting weights at -12/hour gives -6, one LLM.
[c] Another 30 minutes gives -6, still one LLM. [d] -3/hour for two
half-hours gives -2 (carry +.5), then -1 (carry 0), total -3.
[e] Changing to reading asks the LLM again. [f] 400 minutes is capped
at 180: -12*3=-36. [g] Sleeping gives no change or LLM call.
The real profile and history writers run; only the external LLM and
thread dispatch are replaced to make completion deterministic.
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
        from app.core.db import init_schema, transaction, get_connection
        init_schema()
        from app.core import stat_effects as effects
        from app.core.game_time import GameTime
        from app.models.character import get_character_profile
        clock = [3600]
        activity = ["lifting weights"]
        sleeping = [False]
        rate = [-12]
        calls = []
        template = {"sections": [{"fields": [{"key": "stamina", "store": "status_effects"}]}]}
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                         ("Tick", "test", json.dumps({"status_effects": {"stamina": 100}}), "{}", "", ""))

        class InlineThread:
            def __init__(self, target, args=(), kwargs=None, **unused):
                self.run = lambda: target(*args, **(kwargs or {}))
            def start(self):
                self.run()

        def llm(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content=json.dumps({"stats": {"stamina": rate[0]}}))

        def tick(minutes, expected, count):
            clock[0] += minutes * 60
            effects.maybe_activity_tick("Tick")
            actual = get_character_profile("Tick")["status_effects"]["stamina"]
            assert actual == expected, (actual, expected)
            assert len(calls) == count, (len(calls), count)

        with patch("app.core.timeutils.game_time", side_effect=lambda: GameTime(clock[0])), patch(
                "app.models.character.get_effective_activity", side_effect=lambda name: activity[0]), patch(
                "app.models.character.is_character_sleeping", side_effect=lambda name: sleeping[0]), patch(
                "app.models.character_template.get_template", return_value=template), patch(
                "app.models.character_template.is_feature_enabled", return_value=True), patch(
                "app.core.llm_router.llm_call", side_effect=llm), patch(
                "app.core.stat_effects.threading.Thread", InlineThread):
            tick(0, 100, 0)
            tick(29, 100, 0)
            tick(1, 94, 1)
            tick(30, 88, 1)
            activity[0], rate[0] = "reading", -3
            tick(30, 86, 2)
            tick(30, 85, 2)
            activity[0], rate[0] = "lifting weights", -12
            tick(400, 49, 3)
            sleeping[0] = True
            tick(30, 49, 3)
            sleeping[0] = False
            tick(0, 49, 3)
            assert effects.evaluate_stat_rates("Tick", "exercise") == {"stamina": -12}
            assert get_character_profile("Tick")["status_effects"]["stamina"] == 49
            assert effects.evaluate_stat_effects("Tick", "event", source="event") == {"stamina": -12}
            assert get_character_profile("Tick")["status_effects"]["stamina"] == 37
            activity[0] = ""
            tick(30, 37, 5)
            activity[0] = "lifting weights"
            # A rewound clock establishes a fresh baseline.
            clock[0] = 3600
            tick(0, 37, 5)
            tick(30, 31, 5)

            # Hold dispatch so repeated loop turns cannot duplicate LLM work
            # or lose elapsed time while the first evaluation is pending.
            pending = []
            class DeferredThread(InlineThread):
                def start(self):
                    pending.append(self.run)
            activity[0], rate[0] = "walking", -12
            with patch("app.core.stat_effects.threading.Thread", DeferredThread):
                tick(30, 31, 5)
                tick(30, 31, 5)
                assert len(pending) == 1
                pending.pop()()
                assert get_character_profile("Tick")["status_effects"]["stamina"] == 25
                tick(0, 19, 6)
        history = [json.loads(row[0]) for row in get_connection().execute(
            "SELECT state_json FROM state_history WHERE character_name=?", ("Tick",))]
        sources = [row["metadata"]["source"] for row in history if row["type"] == "effects"]
        assert sources.count("activity") == 8 and sources.count("event") == 1, sources
        print("PASS activity [a-g], game-minute gate, rates-only and event contracts")


if __name__ == "__main__":
    main()
