#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_reading_watch.py

Hand-derived expectations (threshold 60, duration ten game minutes):
[a] 70 >= 60: W learns one discovered reader secret; page remains available.
[b] 50 < 60, or distraction at 90: no notice.
[c] Raising attention to 70 on tick notices exactly once.
[d] Owner at 80 catches before page/learning; two memories, owner sentiment -0.3.
[e] Finished owner reply schedules NPC reader only; superseded does not.
[f] Same-day reopening with owner is refused; absent owner permits opening;
    returning owner narrates again but daily consequences stay single.
[g] Witness then owner: one reader secret and owner scene.
[h] Departed or expired reader cannot be caught on entry.
[i] Avatar owner gets notification and NPC reader reply, never owner LLM.
[j] Later-day W2 learns the existing secret rather than creating another.
All side-effect boundaries assert no held keyed lock or DB transaction.
"""
import os
from pathlib import Path
import sys
import tempfile
from contextlib import ExitStack
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="reading-watch-") as tmp, ExitStack() as stack:
        os.environ.update(STORAGE_DIR=tmp, INSTANCE_DIR=tmp)
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import hooks, item_reading as r, reading_watch as w
        from app.core.db import init_schema, transaction, get_connection
        from app.core.game_time import GameTime
        from app.core.timeutils import set_game_factor, set_game_time
        from app.models import character, inventory, secrets, relationship
        from app.models.world import add_location, add_room
        init_schema()
        set_game_factor(0)
        set_game_time(GameTime.parse("Y0002-D109T12:00:00"))
        names = ["A", "R", "O", "W", "W2"]
        with transaction() as conn:
            for name in names:
                conn.execute("INSERT INTO characters(name,created_at,updated_at) VALUES (?,?,?)", (name,"",""))
        loc = add_location(name="Study", description="Quiet")["id"]
        room = add_room(loc, "Desk", sync_world=True)["id"]
        other = add_room(loc, "Door", sync_world=True)["id"]
        def move(name, target):
            character.save_character_current_location(name, loc)
            character.save_character_current_room(name, target)
        for name in names:
            move(name, other)
        move("A", room)
        hooks.register_provider("item_pages.watch_test", lambda item, reader: [{"text": "Page"}])
        iid = inventory.add_item("Notebook", owner="O", pages_source="watch_test")["id"]
        inventory.add_item_to_room(loc, room, iid)
        scores = {name: 0 for name in names}
        distracted = set()
        avatars = {"A"}
        events = {key: [] for key in ("memory", "speech", "reply", "notice")}
        def boundary(key):
            def call(*args, **kwargs):
                from app.core.keyed_lock import _LOCKS
                assert not get_connection().in_transaction
                assert not any(lock._is_owned() for bucket in _LOCKS.values() for lock in bucket.values())
                if key != "speech" or any(word in kwargs.get("content", "") for word in (" catches ", " ertappt ")):
                    events[key].append((args, kwargs))
            return call
        stack.enter_context(patch("app.models.inventory.discovery_value", side_effect=lambda name, **kw: scores[name]))
        stack.enter_context(patch("app.core.interaction_engine.get_interaction", side_effect=lambda name, **kw: {} if name in distracted else None))
        stack.enter_context(patch("app.models.character.is_character_sleeping", return_value=False))
        stack.enter_context(patch("app.core.conversation_pairs.conversation_partner", return_value=None))
        stack.enter_context(patch("app.models.account.is_player_controlled", side_effect=lambda name: name in avatars))
        for target, key in [("app.models.memory.add_memory", "memory"), ("app.core.perception.record_utterance", "speech"), ("app.models.notifications.create_notification", "notice")]:
            stack.enter_context(patch(target, side_effect=boundary(key)))
        for target in ("record_interaction", "add_secret"):
            module = relationship if target == "record_interaction" else secrets
            original = getattr(module, target)
            def checked(*args, _original=original, **kwargs):
                boundary("boundary")(*args, **kwargs)
                return _original(*args, **kwargs)
            events["boundary"] = []
            stack.enter_context(patch.object(module, target, side_effect=checked))
        loop = stack.enter_context(patch("app.core.agent_loop.get_agent_loop"))
        loop.return_value.bump_respond.side_effect = boundary("reply")
        languages = {}
        stack.enter_context(patch("app.models.character.get_character_language", side_effect=lambda name: languages.get(name, "en")))
        w.register()
        move("W", room)
        events["speech"].clear()
        scores["W"] = 70
        assert "page" in r.read_page("A", iid, 0, opening=True)
        ss = secrets.list_secrets("A")
        assert len(ss) == 1 and ss[0]["content"] == "A secretly read Notebook."
        assert ss[0]["source"] == "discovered" and ss[0]["known_by"] == ["W"]
        assert ss[0]["discovered_by"] == ["W"] and "W" in ss[0]["known_at"]
        assert len(events["memory"]) == 1 and not events["speech"]
        print("PASS [a]")
        scores["W"] = 50
        r.read_page("A", iid, 0, opening=True)
        assert r.active_session("A")["noticed_by"] == []
        scores["W"] = 90
        distracted.add("W")
        hooks.emit("world_tick")
        assert r.active_session("A")["noticed_by"] == []
        print("PASS [b]")
        distracted.clear()
        scores["W"] = 70
        hooks.emit("world_tick")
        count = len(events["memory"])
        hooks.emit("world_tick")
        assert len(events["memory"]) == count and r.active_session("A")["noticed_by"] == ["W"]
        print("PASS [c]")
        scores["O"] = 80
        move("O", room)
        r.end_session("A", "test")
        # The first catch occurred on entry; another opening must be refused.
        assert r.read_page("A", iid, 0, opening=True) == {"error": "O is watching."}
        assert r.heartbeat("A", iid) == {"caught_by": ""}
        # New day isolates same-request opening and daily claim.
        set_game_time(GameTime.parse("Y0002-D110T12:00:00"))
        before = len(events["memory"])
        page_secret = secrets.add_secret("O", "A quiet afternoon.")
        hooks.register_provider("item_pages.watch_test", lambda item, reader: [{"text": "Page", "secret_id": page_secret["id"]}])
        with patch.object(r, "_learn") as learn:
            assert r.read_page("A", iid, 0, opening=True) == {"caught_by": "O"}
            learn.assert_not_called()
        assert "A" not in secrets.get_secret("O", page_secret["id"])["known_by"]
        hooks.register_provider("item_pages.watch_test", lambda item, reader: [{"text": "Page"}])
        assert len(events["memory"]) == before + 2
        caught_row = r._session_row("A")
        assert w.check_session(caught_row, []) == {"caught_by": "O"}
        w.check_session(caught_row, ["W"])
        hooks.emit("world_tick")
        assert r.sessions_in_room(loc, room) == []
        assert r.heartbeat("A", iid) == {"caught_by": "O"}
        rel = relationship.get_relationship("O", "A")
        assert abs(rel["sentiment_b_to_a"] + .6) < .00001
        assert rel["sentiment_a_to_b"] == 0
        assert events["reply"][-1][0] == ("O",)
        print("PASS [d]")
        request = events["reply"][-1][1]["request_id"]
        count = len(events["reply"])
        hooks.emit("respond_finished", character_name="O", request_id=request, outcome="ok")
        assert len(events["reply"]) == count
        move("R", room)
        assert r.npc_read("R", iid) == {"caught_by": "O"}
        request = events["reply"][-1][1]["request_id"]
        hooks.emit("respond_finished", character_name="O", request_id=request, outcome="superseded")
        assert events["reply"][-1][0] == ("O",)
        hooks.emit("respond_finished", character_name="O", request_id=request, outcome="ok")
        assert events["reply"][-1][0] == ("R",)
        print("PASS [e]")
        assert r.read_page("A", iid, 0, opening=True) == {"error": "O is watching."}
        move("O", other)
        assert "page" in r.read_page("A", iid, 0, opening=True)
        before = {k: len(v) for k, v in events.items()}
        move("O", room)
        assert len(events["speech"]) == before["speech"] + 1
        assert len(events["memory"]) == before["memory"] and len(events["reply"]) == before["reply"]
        print("PASS [f]")
        assert len(secrets.list_secrets("A")) == 1
        assert secrets.list_secrets("A")[0]["known_by"] == ["W"]
        print("PASS [g]")
        move("O", other)
        r.read_page("A", iid, 0, opening=True)
        move("A", other)
        count = len(events["speech"])
        move("O", room)
        assert len(events["speech"]) == count
        move("O", other)
        move("A", room)
        r.read_page("A", iid, 0, opening=True)
        set_game_time(GameTime.parse("Y0002-D110T12:11:00"))
        move("O", room)
        assert len(events["speech"]) == count
        print("PASS [h]")
        move("O", other)
        avatars.add("O")
        set_game_time(GameTime.parse("Y0002-D111T12:00:00"))
        r.read_page("R", iid, 0, opening=True)
        move("O", room)
        assert events["notice"][-1][0][0] == "O"
        assert events["reply"][-1][0] == ("R",)
        assert "told you" not in events["reply"][-1][1]["hint"]
        print("PASS [i]")
        move("O", other)
        move("W", other)
        scores["W2"] = 70
        move("W2", room)
        r.read_page("A", iid, 0, opening=True)
        ss = secrets.list_secrets("A")
        assert len(ss) == 1 and ss[0]["known_by"] == ["W", "W2"]
        print("PASS [j]")
        # Localized recipients and avatar witnesses use the fixed German text.
        move("O", other)
        set_game_time(GameTime.parse("Y0002-D112T12:00:00"))
        languages.update(A="de", O="en", W2="de")
        inventory.update_item(iid, {"name_de": "Notizbuch"})
        avatars.add("W2")
        r.read_page("A", iid, 0, opening=True)
        assert events["notice"][-1][0] == ("W2", "Du bemerkst, wie A heimlich in Notizbuch liest.")
        move("O", room)
        assert events["memory"][-2][0] == ("O", "I caught A reading Notebook.")
        assert events["memory"][-1][0] == ("A", "O hat mich beim Lesen in Notizbuch ertappt.")
        assert events["speech"][-1][1]["content"] == "O ertappt A beim Lesen in Notizbuch."
        assert r.read_page("A", iid, 0, opening=True) == {"error": "O schaut zu."}
        print("PASS localization, avatar witness, external lock boundaries")
    print("PASS smoke_reading_watch")


if __name__ == "__main__":
    main()
