#!/usr/bin/env python3
"""Verify hourly rules and history in an isolated world.

Usage: ./.venv/bin/python scripts/smoke_stat_hourly.py

Hand-derived Task 2 cases (one game hour per tick):
[a] Awake at home: stamina 50-2=48.
[b] Sleeping at home: 50-2+22=70.
[c] Sleeping elsewhere: 50-2+10=58.
[d] Offmap awake: 50-2+22=70.
[e] Offmap sleeping, home loc_h: 50-2+10=58.
[f] Attention: 0+(50-0)*.1=5; 80-3=77; 45+.5 rounds to 46.
[g] Courage 62: -.48 rounds to 0, carry -.48; next -.96 rounds
    to -1, carry .04, value 61.
[h] Courage 30, config baseline 70: (70-30)*.04=1.6 -> +2=32.
[i] Case b writes one effects/hourly row: Base -2, Sleep at home +22.
[j] Item Tea: stamina 70-10=60, one effects row with old/new and source.
[k] No hourly_sleeping readers remain in app/, plugins/rp or shared/.

Also guards the first-sight/hour gate, clamping, absent stats, additive
rates, label fallback, world overrides, and failed-save history suppression.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction, get_connection
        from app.core.game_time import GameTime, GameDuration
        from app.core.timeutils import set_game_time, set_game_factor
        from app.core.keyed_lock import keyed_lock
        from app.models import character as chars
        from app.core import activity_engine as engine
        init_schema()
        set_game_factor(0)
        start = GameTime.parse("Y0001-D002T12:00:00")
        set_game_time(start)
        template = json.loads((ROOT / "plugins/rp/templates/character/rp.json").read_text())

        def rows(name):
            return [json.loads(row[0]) for row in get_connection().execute(
                "SELECT state_json FROM state_history WHERE character_name=?", (name,))
                if json.loads(row[0])["type"] == "effects"]

        def create(name, values, sleeping=False, location="loc_h", config=None):
            with transaction() as conn:
                conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (name, "hourly-test", json.dumps({"status_effects": values, "is_sleeping": sleeping}),
                              json.dumps({"home_location": "loc_h", **(config or {})}), "", ""))
                conn.execute("INSERT INTO character_state (character_name, current_location, is_sleeping) VALUES (?, ?, ?)", (name, location, int(sleeping)))
            set_game_time(start)
            engine.apply_hourly_status_tick(name)
            assert chars.get_character_profile(name)["status_effects"] == values
            set_game_time(start + GameDuration.of(minutes=59))
            engine.apply_hourly_status_tick(name)
            assert chars.get_character_profile(name)["status_effects"] == values

        def tick(name, hour=1):
            set_game_time(start + GameDuration.of(hours=hour))
            engine.apply_hourly_status_tick(name)
            return chars.get_character_profile(name)["status_effects"]

        with patch("app.models.character_template.get_template", return_value=template), patch(
                "app.models.character_template.is_feature_enabled", return_value=True):
            for case, sleeping, location, expected in [
                ("a", False, "loc_h", 48), ("b", True, "loc_h", 70),
                ("c", True, "loc_other", 58), ("d", False, "", 70),
                ("e", True, "", 58)]:
                create(case, {"stamina": 50}, sleeping, location)
                result = tick(case)
                assert result == {"stamina": expected}, (case, result, expected)
                print(f"PASS [{case}]")
            for value, expected in [(0, 5), (80, 77), (45, 46)]:
                name = f"f{value}"
                create(name, {"attention": value})
                assert tick(name) == {"attention": expected}
            print("PASS [f]")
            create("g", {"courage": 62})
            assert tick("g") == {"courage": 62}
            assert rows("g") == []
            assert tick("g", 2) == {"courage": 61}
            print("PASS [g]")
            create("h", {"courage": 30}, config={"courage_baseline": 70})
            assert tick("h") == {"courage": 32}
            print("PASS [h]")
            history = rows("b")
            assert len(history) == 1, history
            assert history[0]["value"] == "hourly"
            meta = history[0]["metadata"]
            assert meta["source"] == "hourly"
            assert meta["changes"] == {"stamina": {"old": 50, "new": 70}}
            assert meta["parts"]["stamina"] == [
                {"label": "Base", "delta": -2}, {"label": "Sleep at home", "delta": 22}]
            print("PASS [i]")
            assert engine.apply_effects("b", {"stamina_change": -10}, source="item:Tea") == {
                "stamina": {"old": 70, "new": 60}}
            assert rows("b")[-1]["metadata"] == {
                "source": "item:Tea", "changes": {"stamina": {"old": 70, "new": 60}}}
            print("PASS [j]")
            from app.core.stat_rules import save_stat_override
            save_stat_override("stamina", {"per_hour": -3, "rates": [
                {"condition": "is_sleeping", "per_hour": 5, "label": "Nap"},
                {"condition": "at_home", "per_hour": 4}]})
            create("extra", {"stamina": 98}, True)
            assert tick("extra") == {"stamina": 100}
            assert rows("extra")[0]["metadata"]["parts"]["stamina"] == [
                {"label": "Base", "delta": -3}, {"label": "Nap", "delta": 5},
                {"label": "at_home", "delta": 4}]
            create("failed", {"stamina": 50})
            with patch("app.models.character.save_character_profile", return_value=False):
                assert engine.apply_effects("failed", {"stamina_change": -10}) == {}
                tick("failed")
            assert rows("failed") == []
            print("PASS additional gates, clamping, rates and failed saves")
        found = subprocess.run(["git", "grep", "-n", "hourly_sleeping", "--", "app/", "plugins/rp", "shared/"],
                               cwd=ROOT, capture_output=True, text=True)
        assert found.returncode == 1, found.stdout + found.stderr
        print("PASS [k]")
        print("All hourly stat checks passed.")


if __name__ == "__main__":
    main()
