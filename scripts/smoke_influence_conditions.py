#!/usr/bin/env python3
"""Strict conditions and directed package capabilities, without a running server.

Usage: ./.venv/bin/python scripts/smoke_influence_conditions.py

Hand-derived cases: signal 20 is below 30 and an awake character satisfies
NOT is_sleeping; signal 40 fails. Unknown syntax, missing values, unresolved
references, placeholders and failed reads never become true through NOT or
OR. Case-insensitive keywords must not lowercase a character reference.
B's interest in A is directed: A need not reciprocate and A's block is not
B's block. Package removal/clear/reload cannot retain an owned callable;
configuration changes alone retain the first runtime activation snapshot.
A fresh clock at factor 1 advances 60 game seconds after 60 system seconds;
strictly validating the same empty anchor source must not restart that clock.
All world data, profiles and package-discovery fixtures are temporary.
"""
from dataclasses import FrozenInstanceError
from datetime import timedelta
from contextlib import contextmanager
import json
import sqlite3
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="influence-conditions-") as directory:
        storage = Path(directory)
        from app.core import paths
        paths.init(storage)
        paths.init_instance(storage / "instance")
        from app.core import config, db
        config.load(storage / "config.json")
        db.init_schema()
        from app.core import activity_engine as engine, hooks
        from app.models import character
        from app.plugins import loader, registry

        strict = engine.evaluate_condition_strict
        validate = engine.validate_condition_expression
        base = {"status_effects": {"signal": 20}, "is_sleeping": False,
                "gender": "female", "current_location": "demo-location"}
        assert character.save_character_profile("demo", base, create_new=True)
        assert character.save_character_profile("MixedCase Person", {
            "gender": "male", "current_location": "demo-location",
        }, create_new=True)

        def expect(expression, available, passed, *, profile=None,
                   location_id="demo-location", room_id=""):
            result = strict(expression, "demo", location_id, room_id, profile=profile)
            assert isinstance(result, engine.ConditionResult), (expression, result)
            assert (result.available, result.passed) == (available, passed), (expression, result)
            if not available or not passed:
                assert result.reason, (expression, "missing diagnostic")
            return result

        for expression in ("", "true", "signal<30 AND NOT is_sleeping"):
            expect(expression, True, True, profile=base)
            assert not validate(expression), expression
        expect("signal<30 AND NOT is_sleeping", True, False,
               profile={**base, "status_effects": {"signal": 40}})
        expect("signal<30 AND NOT is_sleeping", True, False,
               profile={**base, "is_sleeping": True})
        for expression in ("unknown_atom", "NOT unknown_atom", "true OR unknown_atom",
                           "NOT missing_signal>10", "true OR missing_signal>10",
                           "signal>30 AND missing_signal>10", "NOT missing_field=thing",
                           "npc_present", "NOT npc_present", "event_active:demo",
                           "true OR event_active:demo", "(true)", "true AND", "NOT NOT true",
                           "signal<30trailing", "true OR present:No Such Character",
                           "true OR relationship:NoSuchCharacter>10",
                           "true OR has_item:No Such Item"):
            expect(expression, False, False, profile=base)
        for expression in ("unknown_atom", "npc_present", "event_active:demo", "(true)",
                           "true AND", "NOT NOT true", "signal<30trailing",
                           "true OR unknown_atom"):
            issues = validate(expression)
            assert issues and all(isinstance(issue, engine.ConditionIssue) for issue in issues), expression
            assert all(issue.code and issue.message for issue in issues), issues
        assert not validate("present:MixedCase Person AND signal<30"), "valid references are lexical payload"
        assert not validate("relationship:MixedCase Person>10"), "character references may contain spaces"
        expect("NOT missing_field!=thing", False, False, profile=base)
        expect("NOT gender=male", False, False, profile={**base, "gender": ""})
        expect("NOT gender=male", False, False, profile={**base, "gender": None})

        # Public records are immutable, so a caller cannot turn unavailable into a match.
        result = expect("true", True, True, profile=base)
        try:
            result.available = False
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError("ConditionResult must be immutable")
        issue = validate("unknown_atom")[0]
        try:
            issue.code = "changed"
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError("ConditionIssue must be immutable")

        # The resolver must use the exact character id, not the lowercased atom.
        from app.models import relationship
        relationship.update_relationship_manual(
            "demo", "MixedCase Person", strength=80, romantic_tension=0.6)
        expect("ReLaTiOnShIp:MixedCase Person>10", True, True, profile=base)
        expect("relationship:MixedCase Person>90", True, False, profile=base)
        expect("RoMaNtIc:MixedCase Person>50", True, True, profile=base)
        with patch("app.core.room_entry.characters_in_room", return_value=["MixedCase Person"]):
            expect("PrEsEnT:MixedCase Person", True, True, profile=base)
        engine._last_matched_partner = "untouched"
        expect("relationship:MixedCase Person>10", True, True, profile=base)
        assert character.save_character_profile("demo-other", {
            "current_location": "demo-location",
        }, create_new=True)
        expect("relationship:any>10", True, True, profile=base)
        expect("relationship:demo-other<10", True, True, profile=base)
        expect("romantic:demo-other>10", True, False, profile=base)
        with patch.object(relationship, "get_connection",
                          side_effect=sqlite3.OperationalError("relationship SQL failed")):
            expect("NOT relationship:MixedCase Person>10", False, False, profile=base)
            expect("true OR romantic:MixedCase Person>10", False, False, profile=base)
        row = db.get_connection().execute(
            "SELECT id, meta FROM relationships ORDER BY id LIMIT 1").fetchone()
        with db.transaction() as connection:
            connection.execute("UPDATE relationships SET meta='{broken' WHERE id=?", (row[0],))
        try:
            expect("NOT relationship:MixedCase Person>10", False, False, profile=base)
        finally:
            with db.transaction() as connection:
                connection.execute("UPDATE relationships SET meta=? WHERE id=?", (row[1], row[0]))
        assert engine._last_matched_partner == "untouched", "strict evaluation leaked partner state"

        # Technical failures in historically permissive resolvers stay unavailable.
        for expression, module, name in (
            ("NOT mood:happy", character, "get_character_current_feeling"),
            ("true OR alone", character, "list_available_characters"),
            ("NOT is_sleeping", character, "get_character_profile"),
        ):
            with patch.object(module, name, side_effect=OSError("simulated read failure")):
                expect(expression, False, False)
        with patch("app.core.stat_boosts.effective_stat", side_effect=OSError("simulated stat failure")):
            expect("NOT signal>10", False, False, profile=base)
        with patch("app.models.secrets.list_secrets", side_effect=OSError("simulated secret failure")):
            expect("true OR has_secret", False, False, profile=base)

        # Exercise the actual swallowing readers, not a throwing public getter.
        from app.models import secrets as secret_rows, inventory as items, world
        with patch.object(secret_rows, "get_connection",
                          side_effect=sqlite3.OperationalError("secrets read failed")):
            expect("NOT has_secret", False, False, profile=base)
            expect("true OR has_secret", False, False, profile=base)
            assert engine.evaluate_condition("NOT has_secret", "demo", "demo-location")[0] is True
        with patch.object(character, "get_connection",
                          side_effect=sqlite3.OperationalError("character read failed")):
            expect("alone", False, False, profile=base)
            expect("true OR alone", False, False, profile=base)
            expect("NOT is_sleeping", False, False)
            expect("offmap", False, False, profile={**base, "current_location": ""})
            assert engine.evaluate_condition("alone", "demo", "demo-location")[0] is True
            assert engine.evaluate_condition("NOT is_sleeping", "demo", "demo-location")[0] is True
        # Legacy calls reset their partner state; resume the strict-isolation sentinel.
        engine._last_matched_partner = "untouched"
        connection = db.get_connection()
        with patch.object(character, "get_connection", side_effect=[
                connection, sqlite3.OperationalError("character state SQL failed")]):
            expect("NOT is_sleeping", False, False)

        @contextmanager
        def corrupt_character_json(name, column, value="{broken"):
            assert column in {"profile_json", "config_json"}
            old = db.get_connection().execute(
                f"SELECT {column} FROM characters WHERE name=?", (name,)).fetchone()[0]
            with db.transaction() as connection:
                connection.execute(f"UPDATE characters SET {column}=? WHERE name=?", (value, name))
            try:
                yield
            finally:
                with db.transaction() as connection:
                    connection.execute(f"UPDATE characters SET {column}=? WHERE name=?", (old, name))

        for column in ("profile_json", "config_json"):
            with corrupt_character_json("demo", column):
                expect("NOT is_sleeping", False, False)
                expect("true OR is_sleeping", False, False)
        with corrupt_character_json("demo", "config_json", "null"):
            expect("NOT is_sleeping", False, False)
        old_state = db.get_connection().execute(
            "SELECT meta FROM character_state WHERE character_name='demo'").fetchone()[0]
        with db.transaction() as connection:
            connection.execute("UPDATE character_state SET meta='{broken' WHERE character_name='demo'")
        try:
            expect("NOT is_sleeping", False, False)
            expect("true OR is_sleeping", False, False)
        finally:
            with db.transaction() as connection:
                connection.execute(
                    "UPDATE character_state SET meta=? WHERE character_name='demo'", (old_state,))
        schedule = {"enabled": True, "slots": [
            {"hour": hour, "location": "demo-location", "sleep": False} for hour in range(24)]}
        raw_schedule = json.dumps(schedule)
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO daily_schedules (character_name, enabled, slots, meta) VALUES (?, 1, ?, ?)",
                ("demo", json.dumps(schedule["slots"]), raw_schedule))
        expect("schedule:awake", True, True, profile=base)
        schedule_fallback = character.get_character_scheduler_dir("demo") / "daily_schedule.json"
        schedule_fallback.parent.mkdir(parents=True, exist_ok=True)
        schedule_fallback.write_text(raw_schedule, encoding="utf-8")
        try:
            with patch.object(character, "get_connection",
                              side_effect=sqlite3.OperationalError("schedule SQL failed")):
                expect("true OR schedule:awake", False, False, profile=base)
            with db.transaction() as connection:
                connection.execute("UPDATE daily_schedules SET meta='{broken' WHERE character_name='demo'")
            expect("NOT schedule:awake", False, False, profile=base)
        finally:
            with db.transaction() as connection:
                connection.execute(
                    "UPDATE daily_schedules SET meta=? WHERE character_name='demo'", (raw_schedule,))
            schedule_fallback.unlink()
        token = items.add_item("Demo condition token", item_id="demo_condition_token")["id"]
        item_location = world.add_location("Demo condition rooms", "Strict room lookup fixture.", rooms=[
            {"id": "empty-room", "name": "Empty room", "items": []},
        ])["id"]
        expect(f"NOT room_has_item:{token}", True, True, profile=base,
               location_id=item_location, room_id="empty-room")
        for location_id, room_id in (("", "empty-room"), ("missing-location", "empty-room"),
                                     (item_location, ""), (item_location, "missing-room")):
            for expression in (f"NOT room_has_item:{token}", f"true OR room_has_item:{token}"):
                expect(expression, False, False, profile=base,
                       location_id=location_id, room_id=room_id)
        with patch.object(items, "get_connection",
                          side_effect=sqlite3.OperationalError("item SQL failed")):
            expect(f"NOT has_item:{token}", False, False, profile=base)
            expect(f"true OR room_has_item:{token}", False, False, profile=base,
                   location_id=item_location, room_id="empty-room")
        from app.core import motion_item_cache
        motion_item_cache.invalidate()
        with patch.object(items, "get_connection",
                          side_effect=sqlite3.OperationalError("passive bonus item SQL failed")):
            expect("true OR signal<30", False, False, profile=base)
        motion_item_cache.invalidate()
        expect("signal<30", True, True, profile=base)
        assert world.upsert_location(world.get_location_by_id(item_location), sync_world=False)
        with patch.object(world, "get_connection",
                          side_effect=sqlite3.OperationalError("world room SQL failed")):
            expect(f"true OR room_has_item:{token}", False, False, profile=base,
                   location_id=item_location, room_id="empty-room")
        from app.core import timeutils
        timeutils.invalidate_game_clock_cache()
        with patch.object(world, "get_connection",
                          side_effect=sqlite3.OperationalError("world clock SQL failed")):
            expect("true OR day", False, False, profile=base)
            expect("NOT night", False, False, profile=base)
        timeutils.invalidate_game_clock_cache()
        with db.transaction() as connection:
            connection.execute("DELETE FROM world_kv WHERE key LIKE 'game_time.%'")
        technical_start = timeutils.utc_now()
        with patch.object(timeutils, "utc_now", return_value=technical_start):
            normal_clock = timeutils.game_time()
        with patch.object(timeutils, "utc_now", return_value=technical_start + timedelta(seconds=60)):
            strict_clock = timeutils.game_time(strict=True)
        assert (strict_clock - normal_clock).total_seconds == 60, "strict read restarted the game clock"
        timeutils.invalidate_game_clock_cache()
        expect("day OR night", True, True, profile=base)
        with corrupt_character_json("MixedCase Person", "profile_json"):
            expect("NOT present:MixedCase Person", False, False, profile=base,
                   location_id=item_location, room_id="empty-room")

        # A supplied snapshot is authoritative for its own fields.
        with patch.object(character, "get_character_profile", side_effect=OSError("unexpected reload")):
            expect("signal<30 AND NOT is_sleeping AND gender=female", True, True, profile=base)
        from app.core import prompt_filters
        definitions_file = storage / "strict-filter-definitions.json"
        definitions_file.write_text(
            '{"filters":[{"id":"demo-read-state","condition":"true","enabled":true,'
            '"stat_boosts":{"signal":20}}]}', encoding="utf-8")
        boosted = {**base, "active_conditions": [{"name": "demo-read-state"}]}
        with patch.object(prompt_filters, "_SHARED_FILE", definitions_file):
            prompt_filters.invalidate_filter_snapshot()
            expect("state:demo-read-state", True, True, profile=base)
            expect("signal<30", True, False, profile=boosted)
            prompt_filters.invalidate_filter_snapshot()
            with patch.object(db, "get_connection",
                              side_effect=sqlite3.OperationalError("filter overlay SQL failed")):
                expect("true OR state:demo-read-state", False, False, profile=base)
                expect("true OR signal<30", False, False, profile=boosted)
            prompt_filters.invalidate_filter_snapshot()
            with patch.object(Path, "read_text", side_effect=OSError("shared filter read failed")):
                expect("signal<30", False, False, profile=boosted)
        prompt_filters.invalidate_filter_snapshot()
        states = [
            {"id": "demo-state", "condition": "NOT missing_signal>10", "enabled": True},
            {"id": "demo-cycle", "condition": "state:demo-cycle", "enabled": True},
            {"id": "demo-or", "condition": "true OR missing_signal>10", "enabled": True},
            {"id": "demo-good", "condition": "signal<30 AND NOT is_sleeping", "enabled": True},
        ]
        with patch.object(prompt_filters, "load_filters", return_value=states):
            expect("true OR state:demo-state", False, False, profile=base)
            expect("state:demo-or", False, False, profile=base)
            expect("state:demo-good", True, True, profile=base)
            expect("NOT state:demo-cycle", False, False, profile=base)
            expect("true OR state:no-such-state", False, False, profile=base)
        with patch.object(prompt_filters, "load_filters", return_value=[
                {"id": "demo-secret", "condition": "NOT has_secret", "enabled": True}]):
            with patch.object(secret_rows, "get_connection",
                              side_effect=sqlite3.OperationalError("nested secrets read failed")):
                expect("true OR state:demo-secret", False, False, profile=base)
        assert engine._last_matched_partner == "untouched", "nested strict state touched legacy partner"

        # Existing permissive callers retain their contract.
        for expression, passed in (("signal<30", True), ("signal>30", False),
                                   ("NOT is_sleeping", True), ("unknown_atom", True),
                                   ("missing_signal>10", True), ("npc_present", True)):
            assert engine.evaluate_condition(expression, "demo", "demo-location")[0] is passed, expression

        # Use the isolated package's real matcher/registration against temporary profiles.
        source = ROOT / "plugins" / "attraction"
        assert source.is_dir(), "isolated attraction package checkout is required"
        inventory = storage / "package-inventory"
        package = inventory / "attraction"
        package.mkdir(parents=True)
        for filename in ("matching.py", "register.py", "extraction.py"):
            shutil.copy2(source / filename, package / filename)
        manifest = package / "plugin.yaml"
        manifest.write_text("name: attraction\non_load: register.py\n", encoding="utf-8")
        namespace = types.ModuleType("plugins.attraction")
        namespace.__path__ = [str(package)]
        sys.modules["plugins.attraction"] = namespace
        assert character.save_character_config("demo", {"romantic_interests": "none"})
        assert character.save_character_config("MixedCase Person", {"romantic_interests": "demo"})
        unowned = lambda: "still present"
        hooks.register_provider("demo-unowned", unowned)

        def discover(enabled, *, restart=False):
            original_get = config.get
            def get(key, default=None):
                return enabled if key == "packages.enabled" else original_get(key, default)
            if restart:
                loader._activation_enabled_ids = None
                loader._discovered = False
            with patch.object(config, "get", side_effect=get):
                return loader.discover_packages(inventory, force=True)

        discover("attraction", restart=True)
        directed = hooks.get_provider("romantic_attraction")
        assert directed is not None, "active package did not supply directed attraction"
        assert directed("MixedCase Person", "demo") is True
        assert directed("demo", "MixedCase Person") is False
        assert hooks.get_provider("romantic_compatibility")("demo", "MixedCase Person") is False
        assert hooks.get_provider("romantic_compatibility")("MixedCase Person", "demo") is False
        with patch.object(character, "get_character_config", side_effect=OSError("preference read failure")):
            try:
                directed("MixedCase Person", "demo")
            except OSError:
                pass
            else:
                raise AssertionError("directed provider hid a technical read failure")
        for name, column in (("demo", "profile_json"), ("demo", "config_json"),
                             ("MixedCase Person", "config_json")):
            with corrupt_character_json(name, column):
                try:
                    directed("MixedCase Person", "demo")
                except (ValueError, sqlite3.Error, OSError):
                    pass
                else:
                    raise AssertionError(f"directed name interest hid broken {name}.{column}")
                stored = db.get_connection().execute(
                    f"SELECT {column} FROM characters WHERE name=?", (name,)).fetchone()[0]
                assert stored == "{broken", "strict preference read repaired data as a side effect"
        with patch.object(character, "_read_config_json_row",
                          side_effect=sqlite3.OperationalError("actual config SQL failure")):
            try:
                directed("MixedCase Person", "demo")
            except sqlite3.Error:
                pass
            else:
                raise AssertionError("directed provider hid a failing config SQL query")

        # Height aliases must respect the held subject feature configuration,
        # even if the DB becomes unavailable for a redundant second config read.
        assert character.save_character_profile("demo", {
            **base, "template": "human-default", "height": 175,
        })
        assert character.save_character_config("MixedCase Person", {"romantic_interests": "tall"})

        class ConfigSnapshotConnection:
            def __init__(self, connection):
                self.connection = connection
                self.subject_reads = 0

            def execute(self, statement, parameters=()):
                if statement.startswith("SELECT config_json FROM characters") and parameters == ("demo",):
                    self.subject_reads += 1
                    if self.subject_reads > 1:
                        raise sqlite3.OperationalError("redundant subject config read failed")
                return self.connection.execute(statement, parameters)

        for humanoid, expected in ((False, False), (True, True)):
            assert character.save_character_config("demo", {
                "romantic_interests": "none", "humanoid": humanoid,
            })
            connection = ConfigSnapshotConnection(db.get_connection())
            with patch.object(character, "get_connection", return_value=connection):
                assert directed("MixedCase Person", "demo") is expected, "height ignored held feature config"
        assert character.save_character_config("MixedCase Person", {"romantic_interests": "demo"})
        assert character.save_character_config("demo", {
            "romantic_interests": "none", "romantic_blocked_with": ["MixedCase Person"],
        })
        assert directed("MixedCase Person", "demo") is True, "subject block changed observer preference"
        assert character.save_character_config("MixedCase Person", {
            "romantic_interests": "demo", "romantic_blocked_with": ["demo"],
        })
        assert directed("MixedCase Person", "demo") is False, "observer block was ignored"
        assert character.save_character_config("MixedCase Person", {"romantic_interests": "demo"})
        assert character.save_character_config("demo", {"romantic_interests": "MixedCase Person"})
        assert hooks.get_provider("romantic_compatibility")("MixedCase Person", "demo") is True
        assert character.save_character_config("demo", {
            "romantic_interests": "MixedCase Person", "romantic_blocked_with": ["MixedCase Person"],
        })
        assert hooks.get_provider("romantic_compatibility")("MixedCase Person", "demo") is False

        # Saving a pending disable does NOT hot-deactivate a running package.
        discover("")
        reloaded = hooks.get_provider("romantic_attraction")
        assert reloaded is not None
        assert reloaded("MixedCase Person", "demo") is True
        registry.unregister_package("attraction")
        assert hooks.get_provider("romantic_attraction") is None
        assert hooks.get_provider("romantic_compatibility") is None
        assert hooks.get_provider("romantic_interests_help") is None
        assert hooks.get_provider("demo-unowned") is unowned
        discover("attraction")
        assert hooks.get_provider("romantic_attraction")("MixedCase Person", "demo") is True
        registry.clear_registry()
        assert hooks.get_provider("romantic_attraction") is None
        assert hooks.get_provider("demo-unowned") is unowned
        discover("attraction")
        manifest.unlink()
        discover("attraction")
        assert hooks.get_provider("romantic_attraction") is None, "removed package left stale provider"
        manifest.write_text("name: attraction\non_load: register.py\n", encoding="utf-8")
        discover("", restart=True)
        assert hooks.get_provider("romantic_attraction") is None, "disabled startup retained capability"
        discover("attraction", restart=True)
        assert hooks.get_provider("romantic_attraction")("MixedCase Person", "demo") is True
        hooks.unregister_owned_providers("attraction")
        assert hooks.get_provider("romantic_attraction") is None
        assert hooks.get_provider("demo-unowned") is unowned
        hooks.register_provider("demo-overwritten", lambda: False, owner="attraction")
        hooks.register_provider("demo-overwritten", unowned)
        hooks.unregister_owned_providers("attraction")
        assert hooks.get_provider("demo-overwritten")() == "still present"
        hooks.register_provider("demo-overwritten", lambda: "other owner", owner="demo-other")
        hooks.unregister_owned_providers("attraction")
        assert hooks.get_provider("demo-overwritten")() == "other owner"
        hooks.unregister_owned_providers("demo-other")
        assert hooks.get_provider("demo-overwritten") is None

        # Provider rediscovery must not reset another package's live consent session.
        (inventory / "party").symlink_to(ROOT / "plugins" / "party", target_is_directory=True)
        discover("attraction,party", restart=True)
        from app.core import agent_loop, party_engine
        from plugins.party import trip_intents
        party_location = world.add_location("Demo consent rooms", "Live consent reload fixture.", rooms=[
            {"id": "origin", "name": "Origin"}, {"id": "destination", "name": "Destination"},
        ])["id"]
        owner, companion = "demo-party-owner", "demo-party-peer"
        for name in (owner, companion):
            assert character.save_character_profile(name, {
                "template": "npc-temporary", "standing_task": "help in the next room",
            }, create_new=True)
            character.save_character_current_location(name, party_location)
            character.save_character_current_room(name, "origin")
            character.set_known_locations(name, [party_location])
        loop = agent_loop.AgentLoop()
        with patch.object(agent_loop, "_agent_loop", loop):
            trip = trip_intents.propose_trip(owner, companion, {
                "location_id": party_location, "room_id": "destination",
            })
            invite_id = trip["meta"]["travel"]["invite_id"]
            assert party_engine.get_invite(invite_id)["status"] == "pending"
            assert companion in loop.status()["respond_queue"], "consent was not requested"
            # Model the dispatcher taking that request, without starting an LLM.
            loop._respond_queue.remove(companion)
            loop._respond_to.pop(companion, None)
            discover("attraction,party")
            hooks.emit("world_tick")
            assert party_engine.get_invite(invite_id)["status"] == "pending"
            assert companion not in loop.status()["respond_queue"], "reload requested consent twice"
            assert not party_engine.get_party_of(companion), "reload bypassed pending consent"
        print("PASS: strict influence conditions, directed attraction and provider lifecycle")


if __name__ == "__main__":
    main()
