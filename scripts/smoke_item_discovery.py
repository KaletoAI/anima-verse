#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_item_discovery.py

Hand-derived expectations:
[a] Insert 1500 clamps to 999; overwrite -5 clamps to 0.
[b] Hidden 70: A=50 fails, B=80 finds, C=missing=0 fails.
[c] A+30=80 finds; after expiry 50 still sees the remembered placement.
[d] Visible coin: all see, no discovery rows.
[e] Before [c], A lacks notebook; B sees notebook discovered=True, coin False.
[f] Full removal clears rows; in another room A=50 fails until +30=80.
[g] A before discovery gets "You cannot see that here"; boosted pickup succeeds.
    A refused full pickup restores all discoveries, including their game stamps.
[h] Before [c], B sees notebook with "(hidden — you noticed it)"; A does not.
[i] courage absent in B: 0 fails 70, meets 0.
[j] Legacy hidden 3 becomes 101, marker stat; rerun preserves an edit to 72.
[k] Unmarked location pack converts hidden items to 101; export marks stat,
    and a marked round trip preserves 72. Unrelated locations survive.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="item-discovery-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.models.inventory import (placement_visible_to, discovery_value,
            discovered_by, add_item, add_item_to_room, remove_item_from_room,
            get_room_items, pick_up_item)
        from app.core.db import init_schema, transaction, get_connection
        from app.core import config
        from app.core.game_time import GameTime, GameDuration
        from app.core.timeutils import set_game_time, set_game_factor
        from app.core.keyed_lock import keyed_lock
        from app.models.character import save_character_profile
        from app.models.world import (add_location, add_room, get_location, get_world_setting, world_generation)
        from app.routes.play import _items_here
        from app.core.thought_context import _build_room_items_block
        init_schema()
        set_game_factor(0)
        t = GameTime.parse("Y0001-D002T12:00:00")
        set_game_time(t)
        profiles = {"A": {"status_effects": {"attention": 50}},
                    "B": {"status_effects": {"attention": 80}},
                    "C": {"status_effects": {}}}
        with transaction() as conn:
            for name in profiles:
                conn.execute("INSERT INTO characters (name, created_at, updated_at) VALUES (?, '', '')", (name,))
            conn.execute("INSERT INTO prompt_filters (id, condition, meta) VALUES (?, '', ?)",
                         ("focused", json.dumps({"stat_boosts": {"attention": 30}})))
        def store(name):
            with keyed_lock("character_profile", name):
                assert save_character_profile(name, profiles[name])
        for name in profiles:
            store(name)
        loc = add_location(name="Study", description="A quiet study")["id"]
        room = add_room(loc, "Desk", sync_world=True)["id"]
        other = add_room(loc, "Shelf", sync_world=True)["id"]
        notebook = add_item(name="notebook", description="A plain notebook")["id"]
        coin = add_item(name="coin", description="A plain coin")["id"]
        def placement(iid=notebook, rid=room):
            return next(p for p in get_room_items(loc, rid) if p["item_id"] == iid)
        def sees(name, iid=notebook, rid=room):
            return placement_visible_to(name, loc, rid, placement(iid, rid))
        def boost(expired=False):
            profiles["A"]["active_conditions"] = [{"name": "focused",
                "started_at": (t-GameDuration.of(hours=3 if expired else 1)).canonical(),
                "duration_hours": 2}]
            store("A")
        def here(name):
            with patch("app.models.character.get_character_current_location", return_value=loc), patch("app.models.character.get_character_current_room", return_value=room):
                return {p["item_id"]: p for p in _items_here(name)}
        add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=1500)
        assert placement()["discovery_difficulty"] == 999
        add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=-5)
        assert placement()["discovery_difficulty"] == 0
        remove_item_from_room(loc, room, notebook, quantity=2)
        print("PASS [a]")
        add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=70)
        generation = world_generation()
        assert not sees("A") and sees("B") and not sees("C")
        assert world_generation() == generation
        assert discovered_by(loc, room, notebook) == ["B"]
        assert get_connection().execute("SELECT game_ts FROM item_discoveries").fetchone()[0] == t.canonical()
        print("PASS [b]")
        add_item_to_room(loc, room, coin)
        assert all(sees(n, coin) for n in profiles)
        assert discovered_by(loc, room, coin) == []
        print("PASS [d]")
        assert notebook not in here("A")
        assert here("B")[notebook]["discovered"] is True
        assert here("B")[coin]["discovered"] is False
        print("PASS [e]")
        block = _build_room_items_block(loc, room, "B", profile=profiles["B"])
        assert "notebook" in block and "(hidden — you noticed it)" in block
        assert "notebook" not in _build_room_items_block(loc, room, "A", profile=profiles["A"])
        print("PASS [h]")
        assert pick_up_item("A", loc, room, notebook)["error"] == "You cannot see that here"
        boost()
        assert discovery_value("A") == 80 and sees("A")
        assert discovered_by(loc, room, notebook) == ["A", "B"]
        boost(expired=True)
        assert discovery_value("A") == 50 and sees("A")
        before = [tuple(row) for row in get_connection().execute(
            "SELECT * FROM item_discoveries ORDER BY character_name")]
        with patch("app.models.inventory.add_to_inventory", return_value=False):
            assert pick_up_item("A", loc, room, notebook)["error"] == "Your hands are full"
        assert [tuple(row) for row in get_connection().execute(
            "SELECT * FROM item_discoveries ORDER BY character_name")] == before
        assert sees("A")
        print("PASS [c]")
        assert remove_item_from_room(loc, room, notebook)
        assert discovered_by(loc, room, notebook) == []
        add_item_to_room(loc, other, notebook, hidden=True, discovery_difficulty=70)
        assert not sees("A", rid=other)
        boost()
        assert sees("A", rid=other)
        print("PASS [f]")
        assert pick_up_item("A", loc, other, notebook)["success"]
        assert discovered_by(loc, other, notebook) == []
        print("PASS [g]")
        add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=70)
        original_get = config.get
        with patch.object(config, "get", side_effect=lambda key, default=None: "courage" if key == "inventory.discovery_stat" else original_get(key, default)):
            assert discovery_value("B") == 0 and not sees("B")
            add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=0)
            assert sees("B")
        print("PASS [i]")
        from app.core.discovery_scale_migration import migrate_discovery_scale_once
        add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=3)
        untouched = add_location(name="Unrelated", description="A separate place")["id"]
        migrate_discovery_scale_once()
        assert placement()["discovery_difficulty"] == 101
        assert get_world_setting("discovery_scale") == "stat"
        add_item_to_room(loc, room, notebook, hidden=True, discovery_difficulty=72)
        migrate_discovery_scale_once()
        assert placement()["discovery_difficulty"] == 72 and get_location(untouched)
        print("PASS [j]")
        from app.core.content_io import export_location_to_zip, import_location_from_zip
        content = export_location_to_zip(loc)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["discovery_scale"] == "stat"
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as legacy:
                for member in zf.namelist():
                    data = zf.read(member)
                    if member == "manifest.json":
                        manifest.pop("discovery_scale")
                        data = json.dumps(manifest).encode()
                    legacy.writestr(member, data)
        def imported_difficulties(data):
            result = import_location_from_zip(data)
            imported = get_location(result["location_id"])
            return [p["discovery_difficulty"] for r in imported["rooms"] for p in r.get("items", []) if p.get("hidden")]
        assert imported_difficulties(buf.getvalue()) == [101]
        assert imported_difficulties(content) == [72]
        assert get_location(untouched)
        print("PASS [k]")
        print("All item discovery checks passed (11/11).")


if __name__ == "__main__":
    main()
