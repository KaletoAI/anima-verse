#!/usr/bin/env python3
"""Smoke: world-item actions hook, look route, and approach point (Task 8).

Usage:
    ./.venv/bin/python scripts/smoke_item_actions.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp
directory and paths.init(tmp) / paths.init_instance(tmp) are called before
importing any world-DB module or app.server. TestClient(app) is instantiated
without entering the lifespan context manager.

Fixture (hand-derived):
- Location "loc_item_actions" at world (100, 50), yaw 0.
- Room "study": 4 x 3 m rectangle [0..4] x [0..3], with table prop "T" at
  [1.0, 1.0] (width_m=1.2, depth_m=0.8, height_m=0.8, surface height_m=0.75).
  T's footprint spans x in [0.4, 1.6], z in [0.6, 1.4]; its 4 edge midpoints
  are [1.6, 1.0], [0.4, 1.0], [1.0, 1.4], [1.0, 0.6].
- Room "hall": second room in the same location for cross-room 404 check.
- Active avatar "Alice" (language "en") standing in "study".

Hand-derived expectations:
[a] actions_for on a portable book with a registered pages provider ->
    ids ["look", "take", "read"], each with source="core" and no "run" key.
    actions_for on a non-portable statue without pages -> ids ["look"].
[b] Registered test provider (owner="test_pkg", multiple=True) adds "polish"
    with a "run" key. POST /play/room-item/action {"item_id", "action_id": "polish"}
    returns 200 with ok=True and calls run exactly once with
    ("Alice", book_id, "loc_item_actions", "study").
    A second provider (owner="test_pkg_bad", multiple=True) that raises is
    isolated: actions_for still returns ["look", "take", "read", "polish"]
    (and ["look", "take", "read"] without polish).
    POST /play/room-item/action with core action_id "take" -> 400.
    All test providers are unregistered at the end.
[c] GET /play/room-item/{id}:
    - item in "hall" (another room) -> 404;
    - hidden undiscovered item in "study" -> 404;
    - visible item in "study" with image="book.png" -> 200 with
      image_url="/inventory/items/{id}/image", name, description, quantity.
[d] After remove_item_from_room removes the item, POST /play/room-item/action
    on it -> 404.
[e] POST /play/room-item/approach:
    - floor item anchored at [2.0, 1.5] (on="") with size 0.2 -> 200,
      room_id="study", distance from [2.0, 1.5] == 0.45 + 0.1 = 0.55 (+-0.01),
      point inside [0..4] x [0..3].
    - item on table T (on="T", size 0.1) -> 200, _circle_hits_rect(x, z, 0.25,
      T, 0.0) is False, and distance from the chosen edge midpoint of T ==
      0.45 + 0.05 = 0.50 (+-0.01).
[f] All three routes without a session -> 401.
"""

import logging
import math
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
    with tempfile.TemporaryDirectory(prefix="item-actions-smoke-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import init_schema, transaction
        init_schema()

        from app.core import auth_dependency, hooks, item_actions, props
        from app.core.item_placement import _circle_hits_rect
        from app.core.keyed_lock import keyed_lock
        from app.core.users import create_user, get_user_by_id
        from app.core.world_geometry import point_in_polygon
        from app.models import account as account_model
        from app.models import character as char_model
        from app.models.inventory import (
            add_item,
            add_item_to_room,
            get_item,
            get_room_items,
            remove_item_from_room,
            update_item,
        )
        from app.models.world import upsert_location

        table_prop = props.create_prop(
            name="Oak Table",
            category="table",
            width_m=1.2,
            depth_m=0.8,
            height_m=0.8,
        )
        table_prop_id = table_prop["id"]
        props.update_prop(table_prop_id, {"surface": {"height_m": 0.75}})

        loc_id = "loc_item_actions"
        room_study = "study"
        room_hall = "hall"
        loc = {
            "id": loc_id,
            "name": "Action House",
            "pos_x": 100.0,
            "pos_z": 50.0,
            "yaw_deg": 0.0,
            "rooms": [
                {
                    "id": room_study,
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
                },
                {
                    "id": room_hall,
                    "name": "Hall",
                    "items": [],
                },
            ],
        }
        assert upsert_location(loc, sync_world=False), "initial upsert_location failed"

        avatar = "Alice"
        with transaction() as conn:
            conn.execute(
                "INSERT INTO characters (name, created_at, updated_at) VALUES (?, '', '')",
                (avatar,),
            )
        with keyed_lock("character_profile", avatar):
            char_model.save_character_profile(
                avatar,
                {"language": "en", "status_effects": {"attention": 10}},
            )
        char_model.save_character_current_location(avatar, loc_id)
        char_model.save_character_current_room(avatar, room_study)

        # Register a dummy page provider so the book has pages.
        hooks.register_provider(
            "item_pages.smoke_book",
            lambda item, reader: [{"ref": "p1", "heading": "Ch 1", "text": "Hello"}],
            owner="smoke_pages_pkg",
        )

        try:
            book_id = add_item(
                name="Old Ledger",
                description="A leather-bound ledger",
                pages_source="smoke_book",
                portable=True,
                world_placeable=True,
                world_size_m=0.1,
            )["id"]
            update_item(book_id, {"image": "book.png"})

            statue_id = add_item(
                name="Heavy Statue",
                description="Bolted to the floor",
                portable=False,
                world_placeable=True,
                world_size_m=0.2,
            )["id"]

            hall_item_id = add_item(
                name="Hall Lantern",
                description="In another room",
                world_placeable=True,
                world_size_m=0.2,
            )["id"]

            hidden_id = add_item(
                name="Hidden Ring",
                description="Under the rug",
                world_placeable=True,
                world_size_m=0.1,
            )["id"]

            floor_item_id = add_item(
                name="Floor Coin",
                description="Lying on the floor",
                world_placeable=True,
                world_size_m=0.2,
            )["id"]

            table_item_id = add_item(
                name="Table Cup",
                description="Resting on the table",
                world_placeable=True,
                world_size_m=0.1,
            )["id"]

            assert add_item_to_room(loc_id, room_study, book_id)
            assert add_item_to_room(loc_id, room_study, statue_id)
            assert add_item_to_room(loc_id, room_hall, hall_item_id)
            assert add_item_to_room(loc_id, room_study, hidden_id, hidden=True, discovery_difficulty=80)
            assert add_item_to_room(
                loc_id,
                room_study,
                floor_item_id,
                anchor={"at": [2.0, 1.5], "y": 0.0, "yaw": 0.0, "on": ""},
            )
            assert add_item_to_room(
                loc_id,
                room_study,
                table_item_id,
                anchor={"at": [1.4, 1.0], "y": 0.75, "yaw": 0.0, "on": "T"},
            )

            book_item = get_item(book_id)
            statue_item = get_item(statue_id)
            book_placement = next(e for e in get_room_items(loc_id, room_study) if e["item_id"] == book_id)
            statue_placement = next(e for e in get_room_items(loc_id, room_study) if e["item_id"] == statue_id)

            # [a] Core actions_for
            print("[a] Core actions_for on portable book vs non-portable statue")
            book_acts = item_actions.actions_for(avatar, book_item, book_placement, lang="en")
            check(
                "[a] portable book ids == ['look', 'take', 'read']",
                [a["id"] for a in book_acts] == ["look", "take", "read"],
                repr(book_acts),
            )
            check(
                "[a] no 'run' key exposed in actions_for",
                all("run" not in a for a in book_acts),
                repr(book_acts),
            )
            statue_acts = item_actions.actions_for(avatar, statue_item, statue_placement, lang="en")
            check(
                "[a] non-portable statue without pages ids == ['look']",
                [a["id"] for a in statue_acts] == ["look"],
                repr(statue_acts),
            )

            logging.disable(logging.INFO)
            from fastapi.testclient import TestClient
            from app.server import app as server_app

            player_uid = create_user("player_actions_smoke", "smoke-password", allowed_characters=[avatar])
            player_user = get_user_by_id(player_uid)

            def session_user(request):
                if request.headers.get("x-test-user") == "player":
                    return player_user
                return None

            player_h = {"x-test-user": "player"}

            with (
                patch.object(auth_dependency, "_get_session_user", side_effect=session_user),
                patch.object(account_model, "get_active_character", return_value=avatar),
            ):
                client = TestClient(server_app)

                # [b] Provider action + raising provider isolation + core action refusal
                print("[b] Registered test provider, raising provider isolation, core action refusal")
                run_calls = []

                def polish_run(viewer, iid, location_id, room_id):
                    run_calls.append((viewer, iid, location_id, room_id))
                    return {"polished": True, "item_id": iid}

                def polish_provider(viewer, item, placement):
                    return [{"id": "polish", "label": "Polish", "run": polish_run}]

                def bad_provider(viewer, item, placement):
                    raise RuntimeError("boom from bad provider")

                hooks.register_provider("item.actions", polish_provider, owner="test_pkg", multiple=True)
                hooks.register_provider("item.actions", bad_provider, owner="test_pkg_bad", multiple=True)

                acts_with_pkg = item_actions.actions_for(avatar, book_item, book_placement, lang="en")
                check(
                    "[b] raising provider isolated; ids == ['look', 'take', 'read', 'polish']",
                    [a["id"] for a in acts_with_pkg] == ["look", "take", "read", "polish"],
                    repr(acts_with_pkg),
                )
                check(
                    "[b] 'run' stripped from provider action",
                    all("run" not in a for a in acts_with_pkg),
                    repr(acts_with_pkg),
                )

                r_act = client.post(
                    "/play/room-item/action",
                    json={"item_id": book_id, "action_id": "polish"},
                    headers=player_h,
                )
                check("[b] POST /play/room-item/action polish -> 200", r_act.status_code == 200, repr(r_act.text))
                check(
                    "[b] polish runner called once with avatar location & room",
                    run_calls == [(avatar, book_id, loc_id, room_study)],
                    repr(run_calls),
                )
                if r_act.status_code == 200:
                    body = r_act.json()
                    check("[b] response has ok=True and runner payload", body.get("ok") is True and body.get("polished") is True, repr(body))

                r_core = client.post(
                    "/play/room-item/action",
                    json={"item_id": book_id, "action_id": "take"},
                    headers=player_h,
                )
                check("[b] core action 'take' -> 400", r_core.status_code == 400, repr(r_core.status_code))

                hooks.unregister_owned_providers("test_pkg")
                acts_only_bad = item_actions.actions_for(avatar, book_item, book_placement, lang="en")
                check(
                    "[b] raising provider alone leaves ['look', 'take', 'read']",
                    [a["id"] for a in acts_only_bad] == ["look", "take", "read"],
                    repr(acts_only_bad),
                )

                # Re-register polish for [d]
                hooks.register_provider("item.actions", polish_provider, owner="test_pkg", multiple=True)

                # [c] GET /play/room-item/{id}
                print("[c] GET /play/room-item/{id}: other room 404, hidden 404, visible 200 with image_url")
                r_hall = client.get(f"/play/room-item/{hall_item_id}", headers=player_h)
                check("[c] item in another room -> 404", r_hall.status_code == 404, repr(r_hall.status_code))

                r_hid = client.get(f"/play/room-item/{hidden_id}", headers=player_h)
                check("[c] hidden undiscovered item -> 404", r_hid.status_code == 404, repr(r_hid.status_code))

                r_vis = client.get(f"/play/room-item/{book_id}", headers=player_h)
                check("[c] visible item -> 200", r_vis.status_code == 200, repr(r_vis.status_code))
                if r_vis.status_code == 200:
                    vdata = r_vis.json()
                    check(
                        "[c] image_url matches /inventory/items/{id}/image",
                        vdata.get("image_url") == f"/inventory/items/{book_id}/image",
                        repr(vdata.get("image_url")),
                    )
                    check("[c] name matches", vdata.get("name") == "Old Ledger", repr(vdata.get("name")))
                    check(
                        "[c] description matches",
                        vdata.get("description") == "A leather-bound ledger",
                        repr(vdata.get("description")),
                    )
                    check("[c] quantity == 1", vdata.get("quantity") == 1, repr(vdata.get("quantity")))

                # [d] Action on item removed from room -> 404
                print("[d] Action on removed item -> 404")
                assert remove_item_from_room(loc_id, room_study, book_id)
                r_gone = client.post(
                    "/play/room-item/action",
                    json={"item_id": book_id, "action_id": "polish"},
                    headers=player_h,
                )
                check("[d] action on removed item -> 404", r_gone.status_code == 404, repr(r_gone.status_code))

                # [e] Approach: floor item & table item
                print("[e] Approach point for floor item and table item")
                outline = [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]]
                r_app_floor = client.post(
                    "/play/room-item/approach",
                    json={"item_id": floor_item_id},
                    headers=player_h,
                )
                check("[e] floor item approach -> 200", r_app_floor.status_code == 200, repr(r_app_floor.text))
                if r_app_floor.status_code == 200:
                    fp = r_app_floor.json()
                    pt = fp.get("point")
                    check("[e] floor room_id == study", fp.get("room_id") == room_study, repr(fp))
                    dist_floor = math.hypot(pt[0] - 2.0, pt[1] - 1.5)
                    check(
                        "[e] floor point distance == 0.55 (+-0.01)",
                        abs(dist_floor - 0.55) <= 0.01,
                        f"point={pt} dist={dist_floor:.4f}",
                    )
                    check(
                        "[e] floor point inside room outline",
                        point_in_polygon(pt[0], pt[1], outline),
                        repr(pt),
                    )

                r_app_table = client.post(
                    "/play/room-item/approach",
                    json={"item_id": table_item_id},
                    headers=player_h,
                )
                check("[e] table item approach -> 200", r_app_table.status_code == 200, repr(r_app_table.text))
                if r_app_table.status_code == 200:
                    tp = r_app_table.json()
                    pt = tp.get("point")
                    table_rect = {"at": [1.0, 1.0], "yaw": 0.0, "width_m": 1.2, "depth_m": 0.8}
                    check(
                        "[e] table approach clear of T by >= 0.25",
                        not _circle_hits_rect(pt[0], pt[1], 0.25, table_rect, 0.0),
                        repr(pt),
                    )
                    # Nearest edge midpoint of T to [1.4, 1.0] is [1.6, 1.0]; expected radius = 0.45 + 0.1/2 = 0.50.
                    dist_edge = math.hypot(pt[0] - 1.6, pt[1] - 1.0)
                    check(
                        "[e] table point distance from chosen edge midpoint [1.6, 1.0] == 0.50 (+-0.01)",
                        abs(dist_edge - 0.50) <= 0.01,
                        f"point={pt} dist={dist_edge:.4f}",
                    )

                # [f] Unauthenticated -> 401 on all three routes
                print("[f] All three routes require a session (401 without)")
                r_u1 = client.get(f"/play/room-item/{floor_item_id}")
                r_u2 = client.post("/play/room-item/action", json={"item_id": floor_item_id, "action_id": "polish"})
                r_u3 = client.post("/play/room-item/approach", json={"item_id": floor_item_id})
                check("[f] unauthenticated GET /play/room-item/{id} -> 401", r_u1.status_code == 401, repr(r_u1.status_code))
                check("[f] unauthenticated POST /play/room-item/action -> 401", r_u2.status_code == 401, repr(r_u2.status_code))
                check("[f] unauthenticated POST /play/room-item/approach -> 401", r_u3.status_code == 401, repr(r_u3.status_code))
        finally:
            hooks.unregister_owned_providers("test_pkg")
            hooks.unregister_owned_providers("test_pkg_bad")
            hooks.unregister_owned_providers("smoke_pages_pkg")

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
