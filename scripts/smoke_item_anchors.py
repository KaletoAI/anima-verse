#!/usr/bin/env python3
"""Smoke: stored anchor write paths for world-placeable room items (Task 6).

Usage:
    ./.venv/bin/python scripts/smoke_item_anchors.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp
directory and paths.init(tmp) is called before importing any world-DB module.

Fixture (hand-derived):
- Location at world pos_x=100.0, pos_z=50.0, yaw_deg=0.0.
- Room "study" with layout x=0, y=0, w=4, d=3 -> outline [[0,0],[4,0],[4,3],[0,3]].
- Table prop (1.2 x 0.8 x 0.8 m) with flagged storage surface height_m=0.75,
  placed as placement id "T" at local [1.0, 1.0], yaw 0.
- room_geometry(loc, "study") yields 1 prop with id == "T" and surface_y == 0.75.

Hand-derived expectations:
[a] add_item_to_room of a world_placeable item (size 0.1 m) -> stored entry has
    anchor with on == "T" and y == 0.75. A non-placeable item -> no "anchor" key.
[b] Drop by an avatar with snapshot pos world (102.0, 51.5), yaw 45.0 ->
    world_to_local(102.0, 51.5, 100.0, 50.0, 0.0) = (2.0, 1.5), inside [0,4]x[0,3],
    so anchor is {"at": [2.0, 1.5], "y": 0.0, "yaw": 45.0, "on": ""}.
    Second drop of the same item at world (103.0, 50.5) -> local [3.0, 0.5],
    quantity becomes 2 and anchor moves to at == [3.0, 0.5], y == 0.0, on == "".
[c] Drop with snapshot pos None -> falls back to automatic compute_anchor for
    that room (matches compute_anchor(...) and never stores [0, 0]).
[d0] Move T to [3.0, 2.0]: the key (size 0.1, r 0.05) lay inside T's old
    inner top |x-1| <= 0.6-0.1 = 0.5, |z-1| <= 0.4-0.1 = 0.3 (x 0.5..1.5),
    which lies outside the new table (x 2.4..3.6, z 1.6..2.4), so the repair
    re-anchors it: on == "T", |x-3| <= 0.5, |z-2| <= 0.3.
[d] Remove table placement "T" from the room layout and persist with
    upsert_location -> repair_anchors re-anchors the item that lay on T to the
    floor (on == "", y == 0.0); the item lying at [3.0, 0.5] keeps its anchor.
[e] A non-placeable item lying in the room has no anchor; calling
    update_item(id, {"world_placeable": True}) backfills its anchor; calling
    update_item(id, {"world_placeable": False}) keeps the stored anchor.
[f] Partial pick_up_item (quantity 2 -> 1) leaves the stored anchor unchanged.
[g] backfill_anchors() run twice: first run anchors any unanchored placeable
    entry (returns >= 1 when one exists), second run returns 0.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    status = "OK  " if ok else "FAIL"
    suffix = f": {detail}" if detail else ""
    print(f"  {status} {label}{suffix}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="item-anchors-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import init_schema, transaction
        init_schema()

        from app.core import props
        from app.core.item_placement import (
            backfill_anchors,
            compute_anchor,
            occupied_by_items,
            room_geometry,
        )
        from app.core.keyed_lock import keyed_lock
        from app.models import character as char_model
        from app.models.inventory import (
            add_item,
            add_item_to_room,
            add_to_inventory,
            drop_item,
            get_item,
            get_room_items,
            item_world_size,
            pick_up_item,
            update_item,
        )
        from app.models.world import get_location_by_id, upsert_location

        # Create a table prop with storage surface at 0.75 m.
        table_prop = props.create_prop(
            name="Oak Table",
            category="table",
            width_m=1.2,
            depth_m=0.8,
            height_m=0.8,
        )
        table_prop_id = table_prop["id"]
        props.update_prop(table_prop_id, {"surface": {"height_m": 0.75}})

        loc_id = "loc_anchors"
        room_id = "study"
        loc = {
            "id": loc_id,
            "name": "Study House",
            "pos_x": 100.0,
            "pos_z": 50.0,
            "yaw_deg": 0.0,
            "rooms": [
                {
                    "id": room_id,
                    "name": "Study",
                    "items": [],
                    "layout": {
                        "x": 0.0,
                        "y": 0.0,
                        "w": 4.0,
                        "d": 3.0,
                        "props": [
                            {
                                "id": "T",
                                "prop_id": table_prop_id,
                                "at": [1.0, 1.0],
                                "yaw": 0.0,
                            }
                        ],
                    },
                }
            ],
        }
        assert upsert_location(loc, sync_world=False), "initial upsert_location failed"

        # Verify setup: room_geometry returns 1 prop with surface_y == 0.75
        print("[setup] Verify room_geometry sees table T with surface_y 0.75")
        geo = room_geometry(get_location_by_id(loc_id), room_id)
        check("[setup] room_geometry not None", geo is not None, repr(geo))
        if geo is not None:
            check("[setup] 1 prop in room_geometry", len(geo["props"]) == 1, repr(geo["props"]))
            if geo["props"]:
                check("[setup] prop id == 'T'", geo["props"][0]["id"] == "T", repr(geo["props"][0]["id"]))
                check("[setup] surface_y == 0.75", geo["props"][0]["surface_y"] == 0.75,
                      repr(geo["props"][0]["surface_y"]))

        # Create character for drop/pickup checks
        avatar_name = "Alice"
        with transaction() as conn:
            conn.execute(
                "INSERT INTO characters (name, created_at, updated_at) VALUES (?, '', '')",
                (avatar_name,),
            )
        with keyed_lock("character_profile", avatar_name):
            char_model.save_character_profile(avatar_name, {"language": "en", "status_effects": {}})

        def find_entry(iid: str):
            return next((e for e in get_room_items(loc_id, room_id) if e.get("item_id") == iid), None)

        # [a] add_item_to_room: placeable vs non-placeable
        print("[a] add_item_to_room: placeable lands on table T, non-placeable has no anchor")
        key_id = add_item(
            name="Brass Key",
            description="A small key",
            world_placeable=True,
            world_size_m=0.1,
        )["id"]
        note_id = add_item(
            name="Invisible Note",
            description="Not placeable",
            world_placeable=False,
        )["id"]

        check("[a] add placeable ok", add_item_to_room(loc_id, room_id, key_id))
        check("[a] add non-placeable ok", add_item_to_room(loc_id, room_id, note_id))

        key_entry = find_entry(key_id)
        note_entry = find_entry(note_id)
        check("[a] placeable has anchor", isinstance(key_entry.get("anchor"), dict), repr(key_entry))
        if isinstance(key_entry.get("anchor"), dict):
            check("[a] placeable anchor on == 'T'", key_entry["anchor"]["on"] == "T", repr(key_entry["anchor"]))
            check("[a] placeable anchor y == 0.75", key_entry["anchor"]["y"] == 0.75, repr(key_entry["anchor"]))
        check("[a] non-placeable has no 'anchor' key", "anchor" not in note_entry, repr(note_entry))

        # [b] drop_item with avatar snapshot pos, then second drop moves stack
        print("[b] drop_item at world (102.0, 51.5) -> local [2.0, 1.5], second drop -> [3.0, 0.5]")
        coin_id = add_item(
            name="Silver Coin",
            description="A shiny coin",
            stackable=True,
            world_placeable=True,
            world_size_m=0.1,
        )["id"]
        assert add_to_inventory(avatar_name, coin_id, quantity=2)

        snap_1 = {"pos": {"x": 102.0, "z": 51.5}, "yaw": 45.0}
        with patch.object(char_model, "get_avatar_sync_snapshot", return_value=snap_1):
            res1 = drop_item(avatar_name, loc_id, room_id, coin_id, quantity=1)
        check("[b] first drop ok", res1.get("success") is True, repr(res1))
        coin_entry1 = find_entry(coin_id)
        check("[b] first drop at == [2.0, 1.5]", coin_entry1.get("anchor", {}).get("at") == [2.0, 1.5],
              repr(coin_entry1.get("anchor")))
        check("[b] first drop y == 0.0", coin_entry1.get("anchor", {}).get("y") == 0.0,
              repr(coin_entry1.get("anchor")))
        check("[b] first drop on == ''", coin_entry1.get("anchor", {}).get("on") == "",
              repr(coin_entry1.get("anchor")))

        snap_2 = {"pos": {"x": 103.0, "z": 50.5}, "yaw": 90.0}
        with patch.object(char_model, "get_avatar_sync_snapshot", return_value=snap_2):
            res2 = drop_item(avatar_name, loc_id, room_id, coin_id, quantity=1)
        check("[b] second drop ok", res2.get("success") is True, repr(res2))
        coin_entry2 = find_entry(coin_id)
        check("[b] second drop quantity == 2", coin_entry2.get("quantity") == 2, repr(coin_entry2))
        check("[b] second drop anchor moved to [3.0, 0.5]",
              coin_entry2.get("anchor", {}).get("at") == [3.0, 0.5], repr(coin_entry2.get("anchor")))

        # [c] drop_item with pos None -> compute_anchor fallback, never [0, 0]
        print("[c] drop_item with pos None uses compute_anchor (never [0, 0])")
        cup_id = add_item(
            name="Tin Cup",
            description="A tin cup",
            world_placeable=True,
            world_size_m=0.12,
        )["id"]
        assert add_to_inventory(avatar_name, cup_id, quantity=1)

        loc_before_c = get_location_by_id(loc_id)
        room_before_c = next(r for r in loc_before_c["rooms"] if r["id"] == room_id)
        geo_c = room_geometry(loc_before_c, room_id)
        expected_cup_anchor = compute_anchor(
            cup_id, item_world_size(get_item(cup_id)), geo_c, occupied_by_items(room_before_c, cup_id)
        )

        snap_none = {"pos": None, "yaw": None}
        with patch.object(char_model, "get_avatar_sync_snapshot", return_value=snap_none):
            res_c = drop_item(avatar_name, loc_id, room_id, cup_id, quantity=1)
        check("[c] drop with pos None ok", res_c.get("success") is True, repr(res_c))
        cup_entry = find_entry(cup_id)
        check("[c] anchor matches compute_anchor", cup_entry.get("anchor") == expected_cup_anchor,
              f"got={cup_entry.get('anchor')!r} expected={expected_cup_anchor!r}")
        check("[c] anchor is not [0, 0]", cup_entry.get("anchor", {}).get("at") != [0.0, 0.0],
              repr(cup_entry.get("anchor")))

        # [d0] Move table T to [3.0, 2.0] -> the key on T follows it (Opus, review)
        print("[d0] Moving table T re-anchors the key onto T's new top")
        loc_m = get_location_by_id(loc_id)
        room_m = next(r for r in loc_m["rooms"] if r["id"] == room_id)
        room_m["layout"]["props"][0]["at"] = [3.0, 2.0]
        assert upsert_location(loc_m, sync_world=False)
        key_m = find_entry(key_id).get("anchor") or {}
        km_at = key_m.get("at") or [0.0, 0.0]
        check("[d0] key still on T", key_m.get("on") == "T", repr(key_m))
        check("[d0] key inside T's new inner top", abs(km_at[0] - 3.0) <= 0.5 + 1e-9
              and abs(km_at[1] - 2.0) <= 0.3 + 1e-9, repr(key_m))

        # [d] Remove table T from layout and upsert_location -> repair_anchors
        print("[d] Removing table T repairs item on T to floor; floor item keeps its anchor")
        coin_anchor_before_d = dict(find_entry(coin_id)["anchor"])
        loc_d = get_location_by_id(loc_id)
        room_d = next(r for r in loc_d["rooms"] if r["id"] == room_id)
        room_d["layout"]["props"] = []
        assert upsert_location(loc_d, sync_world=False)

        key_after_d = find_entry(key_id)
        coin_after_d = find_entry(coin_id)
        check("[d] key on T repaired to on == ''", key_after_d.get("anchor", {}).get("on") == "",
              repr(key_after_d.get("anchor")))
        check("[d] key on T repaired to y == 0.0", key_after_d.get("anchor", {}).get("y") == 0.0,
              repr(key_after_d.get("anchor")))
        check("[d] coin at [3.0, 0.5] kept its anchor", coin_after_d.get("anchor") == coin_anchor_before_d,
              f"got={coin_after_d.get('anchor')!r} expected={coin_anchor_before_d!r}")

        # [e] update_item world_placeable False -> True -> False
        print("[e] update_item world_placeable False -> True adds anchor; True -> False keeps it")
        check("[e] note still has no anchor before toggle", "anchor" not in find_entry(note_id),
              repr(find_entry(note_id)))
        update_item(note_id, {"world_placeable": True})
        note_on = find_entry(note_id)
        check("[e] note gained an anchor", isinstance(note_on.get("anchor"), dict), repr(note_on))
        saved_note_anchor = dict(note_on["anchor"]) if isinstance(note_on.get("anchor"), dict) else None

        update_item(note_id, {"world_placeable": False})
        note_off = find_entry(note_id)
        check("[e] note kept stored anchor after turning off",
              note_off.get("anchor") == saved_note_anchor, repr(note_off.get("anchor")))

        # [f] Partial pickup (2 -> 1) leaves anchor unchanged
        print("[f] Partial pick_up_item (2 -> 1) leaves anchor unchanged")
        coin_anchor_before_f = dict(find_entry(coin_id)["anchor"])
        pu = pick_up_item(avatar_name, loc_id, room_id, coin_id, quantity=1)
        check("[f] partial pickup ok", pu.get("success") is True, repr(pu))
        coin_after_f = find_entry(coin_id)
        check("[f] quantity is now 1", coin_after_f.get("quantity") == 1, repr(coin_after_f))
        check("[f] anchor unchanged", coin_after_f.get("anchor") == coin_anchor_before_f,
              f"got={coin_after_f.get('anchor')!r} expected={coin_anchor_before_f!r}")

        # [g] backfill_anchors() run twice -> second run returns 0
        print("[g] backfill_anchors() idempotent: second run returns 0")
        # Create an unanchored placeable room entry directly in storage to verify backfill works too.
        gem_id = add_item(
            name="Ruby",
            description="A red gem",
            world_placeable=True,
            world_size_m=0.08,
        )["id"]
        loc_g = get_location_by_id(loc_id)
        room_g = next(r for r in loc_g["rooms"] if r["id"] == room_id)
        room_g["items"].append({
            "item_id": gem_id,
            "quantity": 1,
            "hidden": False,
            "discovery_difficulty": 0,
            "note": "",
        })
        assert upsert_location(loc_g, sync_world=False)
        check("[g] gem initially has no anchor", "anchor" not in find_entry(gem_id), repr(find_entry(gem_id)))

        n1 = backfill_anchors()
        n2 = backfill_anchors()
        check("[g] first backfill anchored 1 entry", n1 == 1, repr(n1))
        check("[g] gem now has anchor", isinstance(find_entry(gem_id).get("anchor"), dict),
              repr(find_entry(gem_id)))
        check("[g] second backfill returns 0", n2 == 0, repr(n2))

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
