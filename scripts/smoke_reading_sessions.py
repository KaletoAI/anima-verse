#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_reading_sessions.py

Hand-derived expectations, frozen clock T=Y0002-D109T12:00:00:
[a] Opening ends at 12:10, ten minutes after T, one row per reader.
[b] Page/heartbeat at 12:06 ends at 12:16 (now+10, not old until+10).
[c] At 12:30 no live session and no stored row; exactly until is live.
[d] Changing room or location removes the session from room listings.
[e] Close deletes; a close/heartbeat for another item leaves the row alone.
[f] NPC R ends at 12:40 when starting at 12:30, with profile unchanged.
[g] Config duration 3 at 12:30 gives 12:33.
Additional checks: owner catch passes through before learning, including
heartbeat/page turns; start callbacks execute outside locks/transactions.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="reading-sessions-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import hooks, item_reading as r, config
        from app.core.db import init_schema, transaction, get_connection
        from app.core.game_time import GameTime
        from app.core.timeutils import set_game_factor, set_game_time
        from app.models import character, inventory
        from app.models.world import add_location, add_room
        init_schema()
        set_game_factor(0)
        def clock(time):
            set_game_time(GameTime.parse("Y0002-D109T" + time + ":00"))
        clock("12:00")
        with transaction() as conn:
            for name in ("A", "R", "O"):
                conn.execute("INSERT INTO characters(name,created_at,updated_at) VALUES (?,?,?)", (name,"",""))
        loc = add_location(name="Study", description="Quiet")["id"]
        room = add_room(loc, "Desk", sync_world=True)["id"]
        other = add_room(loc, "Door", sync_world=True)["id"]
        for name in ("A", "R"):
            character.save_character_current_location(name, loc)
            character.save_character_current_room(name, room)
        hooks.register_provider("item_pages.session_test", lambda item, reader: [
            {"text": "First"}, {"text": "Second"}])
        iid = inventory.add_item("Notebook", owner="O", pages_source="session_test")["id"]
        inventory.add_item_to_room(loc, room, iid)
        def row():
            return get_connection().execute("SELECT * FROM item_reading_sessions WHERE reader='A'").fetchone()
        def until(reader="A"):
            return r.active_session(reader)["until_game_ts"]
        r.read_page("A", iid, 0, opening=True)
        assert hasattr(r, "active_session"), "Reading session API is missing"
        assert until() == "Y0002-D109T12:10:00"
        assert r.active_session("A")["noticed_by"] == []
        print("PASS [a]")
        clock("12:06")
        r.read_page("A", iid, 1)
        assert until() == "Y0002-D109T12:16:00"
        assert r.heartbeat("A", iid) == {"caught_by": ""}
        assert r.heartbeat("A", "other") == {"caught_by": ""}
        assert r.extend_session("A", "other") is None
        assert until() == "Y0002-D109T12:16:00"
        print("PASS [b]")
        clock("12:16")
        assert r.active_session("A")
        clock("12:30")
        assert r.active_session("A") is None and row() is None
        print("PASS [c]")
        r.read_page("A", iid, 0, opening=True)
        character.save_character_current_room("A", other)
        assert r.sessions_in_room(loc, room) == [] and row() is None
        character.save_character_current_room("A", room)
        r.start_session("A", iid, "elsewhere", room)
        assert r.active_session("A") is None
        print("PASS [d]")
        from app.routes.play import _play_read_session_sync
        with patch("app.models.account.get_active_character", return_value="A"):
            r.read_page("A", iid, 0, opening=True)
            assert _play_read_session_sync({"item_id": "other"}, close=True) == {"ok": True}
            assert r.active_session("A")
            assert _play_read_session_sync({"item_id": iid}) == {"caught_by": ""}
            assert _play_read_session_sync({"item_id": iid}, close=True) == {"ok": True}
            assert row() is None
        print("PASS [e]")
        before = character.get_character_profile("R")
        assert "pages" in r.npc_read("R", iid)
        assert character.get_character_profile("R") == before
        assert until("R") == "Y0002-D109T12:40:00"
        print("PASS [f]")
        original_get = config.get
        with patch("app.core.config.get", side_effect=lambda key, default=None: 3 if key == "inventory.reading_minutes" else original_get(key, default)):
            r.read_page("A", iid, 0, opening=True)
        assert until() == "Y0002-D109T12:33:00"
        r.end_session("A", "closed")
        assert row() is None
        replaced = r.start_session("A", "other", loc, room)
        assert replaced["item_id"] == "other" and replaced["noticed_by"] == [] and replaced["caught"] == 0
        assert get_connection().execute("SELECT count(*) FROM item_reading_sessions WHERE reader='A'").fetchone()[0] == 1
        r.end_session("A", "closed")
        print("PASS [g]")
        from app.core import reading_watch
        def caught(session):
            assert not get_connection().in_transaction
            from app.core.keyed_lock import _LOCKS
            assert not any(lock._is_owned() for bucket in _LOCKS.values() for lock in bucket.values())
            with transaction() as conn:
                conn.execute("UPDATE item_reading_sessions SET caught=1 WHERE reader=?", (session["reader"],))
            return {"caught_by": "O"}
        with patch.object(reading_watch, "on_session_started", side_effect=caught), patch.object(r, "_learn") as learn:
            assert r.read_page("A", iid, 0, opening=True) == {"caught_by": "O"}
            learn.assert_not_called()
        from app.routes.play import _play_read_sync
        with patch("app.models.account.get_active_character", return_value="A"), patch.object(reading_watch, "on_session_started", side_effect=caught):
            assert _play_read_sync({"item_id": iid, "opening": True}) == {"caught_by": "O"}
        assert r.heartbeat("A", iid) == {"caught_by": "O"}
        assert r.read_page("A", iid, 1) == {"caught_by": "O"}
        assert r.active_session("A") is None and row() is None
        with patch.object(reading_watch, "on_session_started", side_effect=caught), patch.object(r, "_learn") as learn:
            character.save_character_current_location("O", loc)
            character.save_character_current_room("O", room)
            clock("12:31")
            assert r.npc_read("O", iid) == {"caught_by": "O"}
            learn.assert_not_called()
        from fastapi import HTTPException
        for close in (False, True):
            with patch("app.models.account.get_active_character", return_value=""):
                try:
                    _play_read_session_sync({"item_id": iid}, close=close)
                except HTTPException as exc:
                    assert exc.status_code == 409
                else:
                    raise AssertionError("No avatar must return 409")
            with patch("app.models.account.get_active_character", return_value="A"):
                try:
                    _play_read_session_sync([], close=close)
                except HTTPException as exc:
                    assert exc.status_code == 400
                else:
                    raise AssertionError("Non-object body must return 400")
        print("PASS catch passthrough and callback lock boundary")
    print("PASS smoke_reading_sessions")


if __name__ == "__main__":
    main()
