#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_item_reading.py

Hand-derived expectations (provider order p1..p4; p2 has no secret):
[a] Opening page 0 returns p1, total 4, teaches s1 and writes one read memory.
    Providers/memory run without locks or transactions; route has no-avatar 409.
[b] Pages 1,2,3 teach s3,s4, but only s1,s3 produce memories (cap 2).
[c] 99 clamps to 3; -5 clamps to 0, with no repeated learning.
[d] Owner O receives a page but gains neither knowledge nor memory.
[e] Raising provider returns None/False/error, without escaping exceptions.
    Missing source is unreadable; empty provider list returns total 0/page None.
[f] NPC R first learns p4,p3 (two memories); next day only p1 is unknown;
    third day all secrets are known, so returns p4. p2 is never unknown.
[g] Nonportable notebook pickup fails with That cannot be taken.
[h] Room payload is readable=True, portable=False; absent provider -> False.
[i] Hidden difficulty 999 exceeds A with no discovery stat: unreadable/error.
[j] name_de supplied through extra_fields localizes to Notizbuch.
    German reader G remembers In Notizbuch gelesen: Note 1.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="item-reading-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.item_reading import pages_of, readable_here, read_page, npc_read, npc_read_today
        from app.core import hooks, item_reading
        from app.core.db import init_schema, transaction, get_connection
        from app.core.game_time import GameTime, GameDuration
        from app.core.timeutils import set_game_time, set_game_factor
        from app.models.inventory import add_item, add_item_to_room, pick_up_item, update_item
        from app.models.world import add_location, add_room
        from app.models.secrets import add_secret, get_secret
        from app.core.i18n import localized
        from app.routes.play import _items_here, _play_read_sync
        from fastapi import HTTPException
        init_schema()
        set_game_factor(0)
        now = GameTime.parse("Y0002-D109T12:00:00")
        set_game_time(now)
        with transaction() as conn:
            for name in ("O", "A", "R", "G"):
                conn.execute("INSERT INTO characters (name, created_at, updated_at) VALUES (?, ?, ?)", (name, "", ""))
        loc = add_location(name="Study", description="A quiet study")["id"]
        room = add_room(loc, "Desk", sync_world=True)["id"]
        secrets = [add_secret("O", f"Note {i}")["id"] for i in range(1, 5)]
        pages = [{"ref": f"p{i}", "heading": f"Page {i}", "text": f"Text {i}",
                  "secret_id": secrets[i-1] if i != 2 else ""} for i in range(1, 5)]
        def assert_unlocked():
            from app.core.keyed_lock import _LOCKS
            from app.models.world import world_write_lock
            assert not world_write_lock._is_owned()
            assert not any(lock._is_owned() for bucket in _LOCKS.values() for lock in bucket.values())
            assert not get_connection().in_transaction
        def provider(item, reader):
            assert_unlocked()
            return pages
        hooks.register_provider("item_pages.test_pages", provider)
        real_add_memory = item_reading.add_memory
        def checked_memory(*args, **kwargs):
            assert_unlocked()
            return real_add_memory(*args, **kwargs)
        item = add_item("Notebook", category="document", owner="O", pages_source="test_pages", portable=False)
        iid = item["id"]
        add_item_to_room(loc, room, iid)
        def known(i, reader):
            return reader in get_secret("O", secrets[i-1])["known_by"]
        def memories(reader):
            return get_connection().execute("SELECT content, meta FROM memories WHERE character_name=?", (reader,)).fetchall()
        with patch("app.core.item_reading.add_memory", side_effect=checked_memory), patch("app.models.character.get_character_current_location", return_value=loc), patch("app.models.character.get_character_current_room", return_value=room), patch("app.models.character.get_character_language", return_value="en"):
            out = read_page("A", iid, 0, opening=True)
            assert out["total"] == 4 and out["page"]["heading"] == "Page 1"
            assert known(1, "A") and len(memories("A")) == 1
            assert memories("A")[0][0] == "Read in Notebook: Note 1"
            assert json.loads(memories("A")[0][1])["secret_id"] == secrets[0]
            with patch("app.models.account.get_active_character", return_value=""):
                try:
                    _play_read_sync({"item_id": iid})
                except HTTPException as exc:
                    assert exc.status_code == 409
                else:
                    raise AssertionError("missing avatar must be 409")
            with patch("app.models.account.get_active_character", return_value="A"):
                assert _play_read_sync({"item_id": iid, "index": 0, "opening": True}) == out
            print("PASS [a]")
            for i in (1, 2, 3):
                read_page("A", iid, i)
            assert known(3, "A") and known(4, "A") and not known(2, "A")
            assert len(memories("A")) == 2
            assert [json.loads(m[1])["secret_id"] for m in memories("A")] == [secrets[0], secrets[2]]
            print("PASS [b]")
            assert read_page("A", iid, 99)["index"] == 3
            assert read_page("A", iid, -5)["index"] == 0
            print("PASS [c]")
            before = [get_secret("O", s) for s in secrets]
            assert read_page("O", iid, 0)["page"]
            assert [get_secret("O", s) for s in secrets] == before and not memories("O")
            print("PASS [d]")
            def broken(item, reader):
                raise ValueError("test provider failure")
            hooks.register_provider("item_pages.broken", broken)
            bad = add_item("Letter", pages_source="broken")
            add_item_to_room(loc, room, bad["id"])
            assert pages_of(bad, "A") is None and not readable_here("A", bad["id"])
            assert "error" in read_page("A", bad["id"], 0)
            assert pages_of({}, "A") is None
            with patch("app.core.hooks.get_provider", return_value=lambda item, reader: []):
                empty = read_page("A", iid, 99)
                assert empty["total"] == 0 and empty["page"] is None and empty["index"] == 0
            print("PASS [e]")
            out = npc_read("R", iid)
            assert [p["heading"] for p in out["pages"]] == ["Page 4", "Page 3"]
            assert known(4, "R") and known(3, "R") and len(memories("R")) == 2
            assert npc_read_today("R", iid)
            assert "error" in npc_read("R", iid)
            assert get_connection().execute("SELECT game_day FROM item_reads WHERE reader='R'").fetchone()[0] == "Y0002-D109"
            set_game_time(now + GameDuration.of(days=1))
            assert not npc_read_today("R", iid)
            assert [p["heading"] for p in npc_read("R", iid)["pages"]] == ["Page 1"]
            set_game_time(now + GameDuration.of(days=2))
            assert [p["heading"] for p in npc_read("R", iid)["pages"]] == ["Page 4"]
            print("PASS [f]")
            assert pick_up_item("A", loc, room, iid) == {"success": False, "error": "That cannot be taken"}
            with patch("app.models.character.get_character_language", return_value="de"):
                assert pick_up_item("A", loc, room, iid)["error"] == "Das lässt sich nicht mitnehmen"
            print("PASS [g]")
            row = next(p for p in _items_here("A") if p["item_id"] == iid)
            assert row["readable"] is True and row["portable"] is False
            with patch("app.core.hooks.get_provider", return_value=None):
                assert next(p for p in _items_here("A") if p["item_id"] == iid)["readable"] is False
            print("PASS [h]")
            add_item_to_room(loc, room, iid, hidden=True, discovery_difficulty=999)
            assert not readable_here("A", iid) and "error" in read_page("A", iid, 0)
            print("PASS [i]")
            translated = add_item("Other notebook", owner="O", pages_source="test_pages", extra_fields={"name_de": "Notizbuch"})
            assert localized(translated, "name", "de") == "Notizbuch"
            assert update_item(translated["id"], {"description_de": "Notizen"})["description_de"] == "Notizen"
            add_item_to_room(loc, room, translated["id"])
            with patch("app.models.character.get_character_language", return_value="de"):
                assert read_page("G", translated["id"], 0)["item_name"] == "Notizbuch"
            assert memories("G")[0][0] == "In Notizbuch gelesen: Note 1"
            print("PASS [j]")
    print("PASS smoke_item_reading")


if __name__ == "__main__":
    main()
