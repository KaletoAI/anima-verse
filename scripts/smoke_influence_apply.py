#!/usr/bin/env python3
"""Atomic chat-event effects and commit-aware, per-pair chat budgets.

Usage: ./.venv/bin/python scripts/smoke_influence_apply.py

Hand-derived expectations (synthetic stat names, no live world):
* A stored value 50 plus 6 is 56: one effects history row and one receipt.
  Replaying that event, including two concurrent callers, adds nothing.
  An empty evaluation still has a receipt; later +6 for it remains a no-op.
* A value 97 plus 10 clamps to 100, recording old=97/new=100, not 107.
  Unknown stats and recipients must never be materialized.
* Ordinary original +8 scaled by 5 is +40, but cap 15 admits only +15.
  The next ordinary +1 admits zero. Original -30 is a turning point even
  when its scaled -15 is small; it bypasses and consumes no ordinary budget.
  Conversely scaled +40 is NOT a turning point when its original was +8.
  Half-away rounding makes +3*.5 -> +2 and -3*.5 -> -2.
* Cap 15 counts absolute movement: +8 then -8 admits +8 then -7. An hour
  change resets the budget. Characters and stat keys remain independent.
* Ordered sources +8, +8 (DB failure), +8 admit +8, no change, then +7.
  Final 50+8+7=65, with only first/third receipts and total usage 15.
  Retrying the missing source in the next hour adds 8 -> 73; successful
  pairs stay duplicates. Each source gets its own reservation/transaction.
* Abandoning a reservation, or failing any of status/receipt/history writes,
  consumes no RAM budget and leaves all three database records unchanged.
* History is bounded at 200 rows, but deleting/trimming it cannot undo a
  receipt. Removing a recipient removes its receipts, not another's.
* Ordinary adjust_status_effects(+3) remains +3 even with chat budget spent.

These checks exercise real SQLite commits/triggers and profile readers. The
small apply_pair adapter follows the public caller lock/commit contract;
there are no fake profile saves, fake receipts or source-text assertions.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Barrier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GAME_TS = "Y0001-D001T01:00:00"
STAT = "test_signal"
OTHER = "test_other"


def main():
    with tempfile.TemporaryDirectory(prefix="anima-influence-apply-") as tmp:
        os.environ["STORAGE_DIR"] = os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import get_connection, init_schema, transaction
        init_schema()
        from app.core import stat_rules, sync_topics
        from app.core.keyed_lock import keyed_lock
        from app.models import character
        from app.models import chat_stat_evaluations as evaluations

        stat_rules.save_setting("chat_cap_per_hour", 15)

        def seed(name, value=50):
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO characters "
                    "(name, template, profile_json, config_json, created_at, updated_at) "
                    "VALUES (?, '', ?, ?, '', '')",
                    (name, json.dumps({"fixture_marker": ["keep", {"value": 7}]}),
                     json.dumps({"fixture_config": {"keep": True}})),
                )
                conn.execute(
                    "INSERT INTO character_state (character_name, current_activity, meta) "
                    "VALUES (?, 'keep activity', ?)",
                    (name, json.dumps({
                        "status_effects": {STAT: value, OTHER: 50},
                        "equipped_items": ["keep-item"],
                        "unrecognized_metadata": {"keep": [1, 2, 3]},
                    })),
                )

        def value(name, key=STAT):
            return character.get_character_profile(name)["status_effects"][key]

        def receipts(name):
            return {row[0] for row in get_connection().execute(
                "SELECT event_id FROM chat_stat_evaluations WHERE recipient=?", (name,))}

        def history(name):
            return [json.loads(row[0]) for row in get_connection().execute(
                "SELECT state_json FROM state_history WHERE character_name=? ORDER BY id", (name,))]

        def snapshot(name):
            conn = get_connection()
            return (
                tuple(tuple(row) for row in conn.execute(
                    "SELECT * FROM characters WHERE name=?", (name,))),
                tuple(tuple(row) for row in conn.execute(
                    "SELECT * FROM character_state WHERE character_name=?", (name,))),
                tuple(tuple(row) for row in conn.execute(
                    "SELECT * FROM chat_stat_evaluations WHERE recipient=? ORDER BY event_id", (name,))),
                tuple(tuple(row) for row in conn.execute(
                    "SELECT * FROM state_history WHERE character_name=? ORDER BY id", (name,))),
            )

        def apply_pair(event_id, name, deltas, *, turning_points=None, hour=1):
            # An early duplicate check avoids reserving; the locked recheck
            # handles another caller committing between these two checks.
            if evaluations.has_evaluation(event_id, name):
                return {"status": "duplicate", "changes": {}}
            with stat_rules.reserve_chat_deltas(
                    name, deltas, turning_points=turning_points or set(), game_hour=hour) as reservation:
                with keyed_lock("character_profile", name):
                    if evaluations.has_evaluation(event_id, name):
                        return {"status": "duplicate", "changes": {}}
                    result = evaluations.commit_evaluation(
                        event_id, name, reservation.deltas, game_ts=GAME_TS,
                        metadata={"source": "chat_reply", "event_id": event_id,
                                  "fixture_metadata": {"keep": "history"}},
                    )
                    if result["status"] in {"applied", "unchanged"}:
                        reservation.commit()
                    return result

        seed("Basic")
        before = snapshot("Basic")
        observed_sync = []

        def observe_committed_basic():
            with sqlite3.connect(str(Path(tmp) / "world.db")) as observer:
                row = observer.execute(
                    "SELECT meta FROM character_state WHERE character_name='Basic'").fetchone()
                observed_sync.append((
                    json.loads(row[0])["status_effects"][STAT],
                    observer.execute(
                        "SELECT COUNT(*) FROM chat_stat_evaluations WHERE recipient='Basic'").fetchone()[0],
                    observer.execute(
                        "SELECT COUNT(*) FROM state_history WHERE character_name='Basic'").fetchone()[0],
                    get_connection().in_transaction,
                ))

        basic_sync = sync_topics.register("fixture", "fixture", "Basic", "", wake=observe_committed_basic)
        basic_sync.take()
        result = apply_pair("basic", "Basic", {STAT: 6})
        assert result == {"status": "applied", "changes": {STAT: {"old": 50, "new": 56}}}, result
        assert value("Basic") == 56
        assert receipts("Basic") == {"basic"}
        entries = history("Basic")
        assert len(entries) == 1 and entries[0]["type"] == "effects", entries
        assert entries[0]["metadata"]["changes"] == {STAT: {"old": 50, "new": 56}}
        assert entries[0]["metadata"]["fixture_metadata"] == {"keep": "history"}
        assert get_connection().execute(
            "SELECT game_ts FROM state_history WHERE character_name='Basic'").fetchone()[0] == GAME_TS
        after = snapshot("Basic")
        assert all(item == (56, 1, 1, False) for item in observed_sync), observed_sync
        sync_topics.unregister(basic_sync)
        assert before[0] == after[0], "An effects commit rewrote character profile/config data"
        meta = json.loads(get_connection().execute(
            "SELECT meta FROM character_state WHERE character_name='Basic'").fetchone()[0])
        assert meta["equipped_items"] == ["keep-item"]
        assert meta["unrecognized_metadata"] == {"keep": [1, 2, 3]}
        assert character.get_character_profile("Basic")["current_activity"] == "keep activity"
        assert apply_pair("basic", "Basic", {STAT: 6})["status"] == "duplicate"
        assert snapshot("Basic") == after
        # The model transaction also checks receipts, even without the adapter's precheck.
        with keyed_lock("character_profile", "Basic"):
            duplicate = evaluations.commit_evaluation(
                "basic", "Basic", {STAT: 6}, game_ts=GAME_TS, metadata={})
        assert duplicate == {"status": "duplicate", "changes": {}}
        assert snapshot("Basic") == after

        seed("Concurrent")
        barrier = Barrier(2)

        def concurrent_apply(_):
            barrier.wait(timeout=10)
            return apply_pair("concurrent", "Concurrent", {STAT: 6})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(concurrent_apply, range(2)))
        assert sorted(result["status"] for result in results) == ["applied", "duplicate"], results
        assert value("Concurrent") == 56
        assert len(history("Concurrent")) == 1 and receipts("Concurrent") == {"concurrent"}
        assert apply_pair("concurrent-next", "Concurrent", {STAT: 10})["changes"] == {
            STAT: {"old": 56, "new": 65}}

        seed("Empty")
        assert apply_pair("zero", "Empty", {}) == {"status": "unchanged", "changes": {}}
        assert receipts("Empty") == {"zero"} and history("Empty") == []
        assert apply_pair("zero", "Empty", {STAT: 6})["status"] == "duplicate"
        assert value("Empty") == 50
        assert apply_pair("unknown-stat", "Empty", {"undeclared_signal": 6}) == {
            "status": "unchanged", "changes": {}}
        assert "undeclared_signal" not in character.get_character_profile("Empty")["status_effects"]
        missing = apply_pair("missing", "Missing", {STAT: 6})
        assert missing["status"] == "failed" and missing["changes"] == {}, missing
        assert snapshot("Missing") == ((), (), (), ())

        seed("Nested")
        before = snapshot("Nested")
        conn = get_connection()
        conn.execute("UPDATE characters SET updated_at='outer-uncommitted' WHERE name='Nested'")
        try:
            with stat_rules.reserve_chat_deltas(
                    "Nested", {STAT: 8}, turning_points=set(), game_hour=1) as reservation:
                with keyed_lock("character_profile", "Nested"):
                    nested = evaluations.commit_evaluation(
                        "nested", "Nested", reservation.deltas, game_ts=GAME_TS, metadata={})
            assert nested == {"status": "failed", "changes": {}}
            assert conn.in_transaction, "The atomic leaf ended its caller's transaction"
            assert conn.execute(
                "SELECT updated_at FROM characters WHERE name='Nested'").fetchone()[0] == "outer-uncommitted"
        finally:
            conn.rollback()
        assert snapshot("Nested") == before
        assert apply_pair("after-nested", "Nested", {STAT: 15})["changes"] == {
            STAT: {"old": 50, "new": 65}}

        seed("Clamp", 97)
        assert apply_pair("clamp", "Clamp", {STAT: 10})["changes"] == {STAT: {"old": 97, "new": 100}}
        assert history("Clamp")[0]["metadata"]["changes"] == {STAT: {"old": 97, "new": 100}}

        seed("Scaled")
        assert apply_pair("scaled-eight", "Scaled", {STAT: 40})["changes"] == {
            STAT: {"old": 50, "new": 65}}
        assert apply_pair("scaled-one", "Scaled", {STAT: 1}) == {"status": "unchanged", "changes": {}}
        assert receipts("Scaled") == {"scaled-eight", "scaled-one"}
        assert apply_pair("turning-point", "Scaled", {STAT: -15}, turning_points={STAT})["changes"] == {
            STAT: {"old": 65, "new": 50}}
        assert apply_pair("still-capped", "Scaled", {STAT: 1})["status"] == "unchanged"
        # A turning point first must leave all fifteen ordinary units available.
        seed("Turning")
        assert apply_pair("turning-first", "Turning", {STAT: -15}, turning_points={STAT})["changes"] == {
            STAT: {"old": 50, "new": 35}}
        assert apply_pair("ordinary-after-turning", "Turning", {STAT: 15})["changes"] == {
            STAT: {"old": 35, "new": 50}}
        assert stat_rules.round_half_away(3 * .5) == 2
        assert stat_rules.round_half_away(-3 * .5) == -2
        seed("Rounding")
        assert apply_pair("rounded-up", "Rounding", {STAT: stat_rules.round_half_away(3 * .5)})[
            "changes"] == {STAT: {"old": 50, "new": 52}}
        assert apply_pair("rounded-down", "Rounding", {STAT: stat_rules.round_half_away(-3 * .5)})[
            "changes"] == {STAT: {"old": 52, "new": 50}}

        seed("Absolute")
        assert apply_pair("abs-plus", "Absolute", {STAT: 8})["changes"] == {STAT: {"old": 50, "new": 58}}
        assert apply_pair("abs-minus", "Absolute", {STAT: -8})["changes"] == {STAT: {"old": 58, "new": 51}}
        assert apply_pair("abs-next-hour", "Absolute", {STAT: 8}, hour=2)["changes"] == {
            STAT: {"old": 51, "new": 59}}
        assert apply_pair("other-stat", "Absolute", {OTHER: 8}, hour=2)["changes"] == {
            OTHER: {"old": 50, "new": 58}}
        seed("Abandoned")
        with stat_rules.reserve_chat_deltas("Abandoned", {STAT: 8}, turning_points=set(), game_hour=1) as held:
            assert held.deltas == {STAT: 8}
        assert apply_pair("after-abandoned", "Abandoned", {STAT: 15})["changes"] == {
            STAT: {"old": 50, "new": 65}}

        def fail_on(table, condition):
            with transaction() as conn:
                conn.execute(
                    f"CREATE TRIGGER influence_forced_failure BEFORE "
                    f"{'UPDATE OF meta' if table == 'character_state' else 'INSERT'} ON {table} "
                    f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'intentional influence rollback'); END")

        def stop_failing():
            with transaction() as conn:
                conn.execute("DROP TRIGGER influence_forced_failure")

        rollback_sync = sync_topics.register("fixture", "fixture", "Rollback", "")
        rollback_sync.take()

        for table, condition in [
                ("character_state", "NEW.character_name='Rollback'"),
                ("chat_stat_evaluations", "NEW.recipient='Rollback'"),
                ("state_history", "NEW.character_name='Rollback'")]:
            name = "Rollback"
            if not get_connection().execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone():
                seed(name)
            before = snapshot(name)
            fail_on(table, condition)
            try:
                failed = apply_pair(f"rollback-{table}", name, {STAT: 8}, hour=3)
            finally:
                stop_failing()
            assert failed["status"] == "failed" and failed["changes"] == {}, (table, failed)
            assert snapshot(name) == before, f"Partial commit after failure in {table}"
            assert rollback_sync.take() == ([], False), "A rolled-back application published player sync"
        assert apply_pair("rollback-retry", "Rollback", {STAT: 15}, hour=3)["changes"] == {
            STAT: {"old": 50, "new": 65}}, "Failed writes consumed the RAM budget"
        sync_topics.unregister(rollback_sync)

        seed("Ordered")
        assert apply_pair("source-1", "Ordered", {STAT: 8}, hour=4)["changes"] == {
            STAT: {"old": 50, "new": 58}}
        before = snapshot("Ordered")
        fail_on("state_history", "NEW.character_name='Ordered'")
        try:
            failed = apply_pair("source-2", "Ordered", {STAT: 8}, hour=4)
        finally:
            stop_failing()
        assert failed["status"] == "failed" and snapshot("Ordered") == before
        assert apply_pair("source-3", "Ordered", {STAT: 8}, hour=4)["changes"] == {
            STAT: {"old": 58, "new": 65}}, "A failed middle pair must leave seven units for source 3"
        assert receipts("Ordered") == {"source-1", "source-3"}
        assert len(history("Ordered")) == 2
        assert apply_pair("source-4", "Ordered", {STAT: -1}, hour=4)["status"] == "unchanged"
        # Replay preserves event order, not arbitrary dictionary key order.
        # The successful pairs skip; only the previously failed source can apply.
        for event, expected in [("source-1", "duplicate"), ("source-2", "applied"), ("source-3", "duplicate")]:
            assert apply_pair(event, "Ordered", {STAT: 8}, hour=5)["status"] == expected
        assert value("Ordered") == 73 and len(history("Ordered")) == 3
        assert receipts("Ordered") == {"source-1", "source-2", "source-3", "source-4"}

        seed("History")
        assert apply_pair("survives-trim", "History", {STAT: 6})["status"] == "applied"
        with transaction() as conn:
            conn.execute("DELETE FROM state_history WHERE character_name='History'")
            conn.executemany(
                "INSERT INTO state_history (character_name, ts, game_ts, state_json) VALUES ('History', ?, ?, ?)",
                [(f"2000-01-01T00:00:{i:06d}", GAME_TS, json.dumps({"type": "activity", "value": str(i)}))
                 for i in range(205)],
            )
        assert apply_pair("survives-trim", "History", {STAT: 6})["status"] == "duplicate"
        assert value("History") == 56
        assert apply_pair("trims-old-history", "History", {STAT: 1})["status"] == "applied"
        entries = history("History")
        assert len(entries) == 200, len(entries)
        assert entries[0]["value"] == "6" and entries[-1]["type"] == "effects"
        assert receipts("History") == {"survives-trim", "trims-old-history"}

        # This writer is not part of chat influence/capping; its ordinary
        # delta must not inherit either a multiplier or a spent chat budget.
        assert character.adjust_status_effects("Scaled", {STAT: 3}, source="fixture-direct") == {
            STAT: {"old": 50, "new": 53}}
        assert value("Scaled") == 53

        seed("DeleteMe")
        assert apply_pair("delete-receipt", "DeleteMe", {})["status"] == "unchanged"
        assert character.delete_character("DeleteMe") is True
        assert receipts("DeleteMe") == set()
        assert receipts("Basic") == {"basic"}
        assert not get_connection().in_transaction
        print("PASS atomic influence application, receipts, rollback, per-pair budgets, trim and deletion")


if __name__ == "__main__":
    main()
