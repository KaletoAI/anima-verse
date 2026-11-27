#!/usr/bin/env python3
"""Smoke: per-viewer world-placeable items payload, ETag and sync (Task 7).

Usage:
    ./.venv/bin/python scripts/smoke_item_world_payload.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp
directory and paths.init(tmp) / paths.init_instance(tmp) are called before
importing any world-DB module or app.server. TestClient(app) is instantiated
without entering the lifespan context manager.

Auth / viewer setup:
- Uses the same auth_dependency._get_session_user stub as smoke_auth_gate.py /
  smoke_item_mesh.py (requests with header x-test-user=player authenticate as a
  real created player user; requests without the header have no session -> 401).
- Monkeypatches app.models.account.get_active_character to switch cleanly
  between viewers A and B without heavy session/user-settings plumbing.

Fixture (hand-derived):
- Location "loc_world_items" at world (100, 50), yaw 0.
- Room "study": 4 x 3 m layout with table prop "T" (1.2 x 0.8 x 0.8 m, storage
  surface height_m=0.75) at [1.0, 1.0].
- Room "porch": no layout -> room_geometry returns None -> entries have no anchor.
- Viewer A ("Alice"): language "en", attention=95 (exceeds difficulty 70).
- Viewer B ("Bob"): language "de", attention=20 (below difficulty 70, but gets
  a direct item_discoveries row for the hidden item).

Hand-derived expectations:
[a] Visible placeable item ("Brass Key", size 0.1) placed in "study" gets a
    stored anchor on table T (y=0.75); GET /play/locations/{id}/items returns
    200 with that item carrying the exact stored at/y/yaw, size_m=0.1,
    actions=[{"id": "look", "label": "Look", "source": "core"},
             {"id": "take", "label": "Take", "source": "core"}],
    image_url=None, model_url=None, model_version=None.
[b] Hidden placeable item ("Secret Diary", difficulty 70) in "study":
    - viewer A (no item_discoveries row) -> absent from payload;
    - viewer B (with a direct row in item_discoveries) -> present in payload.
[c] GET is a pure read: item_discoveries and notifications row counts are
    unchanged before and after GET for viewer A even though A's attention (95)
    exceeds the hidden item's difficulty (70).
[d] Second GET with If-None-Match=<etag> -> 304 Not Modified with ETag and
    Cache-Control: no-cache. After add_item_to_room of another placeable item
    ("Silver Cup") -> GET with the old If-None-Match returns 200 with a new ETag
    and includes the new item.
[e] Placeable item ("Lantern") added to "porch" (no layout) has no stored
    anchor -> absent from payload, response is still 200.
[f] Non-placeable item ("Folded Note") in "study" -> absent from payload.
    Switching "Silver Cup" to world_placeable=False removes it from the payload
    at once while its stored anchor remains in room.items.
[g] sync_topics.room_items_changed(loc, "study", True, True, item_id=<placeable>)
    when avatar "Bob" stands in room "porch" (R2) of the same location ->
    notifies "Bob" (topic "self"), and sync_topics.notify never receives Everyone.
[h] GET /play/locations/{id}/items without a session -> 401.
"""

import logging
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
    with tempfile.TemporaryDirectory(prefix="item-world-payload-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import get_connection, init_schema, transaction
        init_schema()

        from app.core import auth_dependency, props, sync_topics
        from app.core.keyed_lock import keyed_lock
        from app.core.users import create_user, get_user_by_id
        from app.models import account as account_model
        from app.models import character as char_model
        from app.models.inventory import (
            add_item,
            add_item_to_room,
            get_room_items,
            update_item,
        )
        from app.models.world import upsert_location

        # Build table prop with storage surface at 0.75 m.
        table_prop = props.create_prop(
            name="Oak Table",
            category="table",
            width_m=1.2,
            depth_m=0.8,
            height_m=0.8,
        )
        table_prop_id = table_prop["id"]
        props.update_prop(table_prop_id, {"surface": {"height_m": 0.75}})

        loc_id = "loc_world_items"
        room_study = "study"
        room_porch = "porch"
        loc = {
            "id": loc_id,
            "name": "Study House",
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
                    "id": room_porch,
                    "name": "Porch",
                    "items": [],
                },
            ],
        }
        assert upsert_location(loc, sync_world=False), "initial upsert_location failed"

        # Create viewers A (high attention=95, en) and B (low attention=20, de).
        viewer_a = "Alice"
        viewer_b = "Bob"
        with transaction() as conn:
            for name in (viewer_a, viewer_b):
                conn.execute(
                    "INSERT INTO characters (name, created_at, updated_at) VALUES (?, '', '')",
                    (name,),
                )
        with keyed_lock("character_profile", viewer_a):
            char_model.save_character_profile(
                viewer_a,
                {"language": "en", "status_effects": {"attention": 95}},
            )
        with keyed_lock("character_profile", viewer_b):
            char_model.save_character_profile(
                viewer_b,
                {"language": "de", "status_effects": {"attention": 20}},
            )
        char_model.save_character_current_location(viewer_a, loc_id)
        char_model.save_character_current_room(viewer_a, room_study)
        char_model.save_character_current_location(viewer_b, loc_id)
        char_model.save_character_current_room(viewer_b, room_porch)

        # Create items.
        key_id = add_item(
            name="Brass Key",
            description="A small brass key",
            world_placeable=True,
            world_size_m=0.1,
            extra_fields={"name_de": "Messingschlüssel"},
        )["id"]
        hidden_id = add_item(
            name="Secret Diary",
            description="Hidden under the blotter",
            world_placeable=True,
            world_size_m=0.2,
            extra_fields={"name_de": "Geheimes Tagebuch"},
        )["id"]
        note_id = add_item(
            name="Folded Note",
            description="Not placeable",
            world_placeable=False,
        )["id"]
        lantern_id = add_item(
            name="Lantern",
            description="Placed in room without layout",
            world_placeable=True,
            world_size_m=0.3,
        )["id"]

        assert add_item_to_room(loc_id, room_study, key_id)
        assert add_item_to_room(loc_id, room_study, hidden_id, hidden=True, discovery_difficulty=70)
        assert add_item_to_room(loc_id, room_study, note_id)
        assert add_item_to_room(loc_id, room_porch, lantern_id)

        # Give viewer B a direct discovery row for the hidden item.
        with transaction() as conn:
            conn.execute(
                "INSERT INTO item_discoveries (location_id, room_id, item_id, character_name, game_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (loc_id, room_study, hidden_id, viewer_b, "Y0001-D001T00:00:00"),
            )

        def stored_entry(room_id: str, item_id: str):
            return next((e for e in get_room_items(loc_id, room_id) if e.get("item_id") == item_id), None)

        logging.disable(logging.INFO)
        from fastapi.testclient import TestClient
        from app.server import app as server_app

        player_uid = create_user("player_items_smoke", "smoke-password", allowed_characters=[viewer_a, viewer_b])
        player_user = get_user_by_id(player_uid)

        def session_user(request):
            if request.headers.get("x-test-user") == "player":
                return player_user
            return None

        active_viewer = {"name": viewer_a}
        player_h = {"x-test-user": "player"}

        with (
            patch.object(auth_dependency, "_get_session_user", side_effect=session_user),
            patch.object(account_model, "get_active_character", side_effect=lambda: active_viewer["name"]),
        ):
            # Instantiate TestClient WITHOUT entering lifespan context manager.
            client = TestClient(server_app)

            # [c] Record table row counts before viewer A's GET.
            conn = get_connection()
            disc_before = conn.execute("SELECT COUNT(*) FROM item_discoveries").fetchone()[0]
            notif_before = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

            # [a] Visible placeable item with exact stored at/y/yaw.
            print("[a] Visible placeable item has exact stored at/y/yaw")
            active_viewer["name"] = viewer_a
            r_a = client.get(f"/play/locations/{loc_id}/items", headers=player_h)
            check("[a] GET status 200", r_a.status_code == 200, repr(r_a.status_code))
            data_a = r_a.json()
            check("[a] location_id matches", data_a.get("location_id") == loc_id, repr(data_a.get("location_id")))
            items_a = {it["item_id"]: it for it in data_a.get("items", [])}
            key_stored = stored_entry(room_study, key_id)
            key_anchor = (key_stored or {}).get("anchor") or {}
            check("[a] Brass Key present", key_id in items_a, repr(list(items_a.keys())))
            if key_id in items_a:
                ka = items_a[key_id]
                check("[a] exact at", ka.get("at") == key_anchor.get("at"), f"{ka.get('at')} vs {key_anchor.get('at')}")
                check("[a] exact y", ka.get("y") == key_anchor.get("y"), f"{ka.get('y')} vs {key_anchor.get('y')}")
                check("[a] exact yaw", ka.get("yaw") == key_anchor.get("yaw"), f"{ka.get('yaw')} vs {key_anchor.get('yaw')}")
                check("[a] size_m == 0.1", ka.get("size_m") == 0.1, repr(ka.get("size_m")))
                check(
                    "[a] actions == [look, take] core dicts",
                    ka.get("actions") == [
                        {"id": "look", "label": "Look", "source": "core"},
                        {"id": "take", "label": "Take", "source": "core"},
                    ],
                    repr(ka.get("actions")),
                )
                check("[a] model_url is None", ka.get("model_url") is None, repr(ka.get("model_url")))
                check("[a] image_url is None", ka.get("image_url") is None, repr(ka.get("image_url")))

            # [b] Hidden placeable item: A absent, B present.
            print("[b] Hidden placeable item: viewer A absent, viewer B present")
            check("[b] hidden item absent for viewer A", hidden_id not in items_a, repr(list(items_a.keys())))
            active_viewer["name"] = viewer_b
            r_b = client.get(f"/play/locations/{loc_id}/items", headers=player_h)
            check("[b] viewer B GET status 200", r_b.status_code == 200, repr(r_b.status_code))
            items_b = {it["item_id"]: it for it in r_b.json().get("items", [])}
            check("[b] hidden item present for viewer B", hidden_id in items_b, repr(list(items_b.keys())))
            if hidden_id in items_b:
                check("[b] viewer B gets German name", items_b[hidden_id].get("name") == "Geheimes Tagebuch",
                      repr(items_b[hidden_id].get("name")))

            # [c] GET writes nothing (item_discoveries & notifications unchanged).
            print("[c] GET writes nothing to item_discoveries or notifications")
            disc_after = conn.execute("SELECT COUNT(*) FROM item_discoveries").fetchone()[0]
            notif_after = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
            check("[c] item_discoveries count unchanged", disc_after == disc_before,
                  f"before={disc_before} after={disc_after}")
            check("[c] notifications count unchanged", notif_after == notif_before,
                  f"before={notif_before} after={notif_after}")

            # [d] ETag / 304 and invalidation after add_item_to_room.
            print("[d] If-None-Match -> 304; add_item_to_room -> 200 with new ETag")
            active_viewer["name"] = viewer_a
            etag_1 = r_a.headers.get("etag")
            check("[d] ETag header present and quoted", bool(etag_1) and etag_1.startswith('"') and etag_1.endswith('"'),
                  repr(etag_1))
            check("[d] Cache-Control is no-cache", r_a.headers.get("cache-control") == "no-cache",
                  repr(r_a.headers.get("cache-control")))
            r_304 = client.get(f"/play/locations/{loc_id}/items", headers={**player_h, "If-None-Match": etag_1})
            check("[d] second GET with If-None-Match -> 304", r_304.status_code == 304, repr(r_304.status_code))

            cup_id = add_item(
                name="Silver Cup",
                description="A silver cup",
                world_placeable=True,
                world_size_m=0.15,
            )["id"]
            assert add_item_to_room(loc_id, room_study, cup_id)
            r_new = client.get(f"/play/locations/{loc_id}/items", headers={**player_h, "If-None-Match": etag_1})
            etag_2 = r_new.headers.get("etag")
            check("[d] GET after add_item_to_room -> 200", r_new.status_code == 200, repr(r_new.status_code))
            check("[d] new ETag differs", bool(etag_2) and etag_2 != etag_1, f"{etag_1} -> {etag_2}")
            items_new = {it["item_id"]: it for it in r_new.json().get("items", [])}
            check("[d] Silver Cup present in new payload", cup_id in items_new, repr(list(items_new.keys())))

            # [e] Entry in room without layout has no anchor -> absent, 200.
            print("[e] Entry in room without layout has no anchor -> absent, 200")
            lantern_stored = stored_entry(room_porch, lantern_id)
            check("[e] lantern has no anchor in storage", "anchor" not in (lantern_stored or {}), repr(lantern_stored))
            check("[e] lantern absent from payload", lantern_id not in items_new, repr(list(items_new.keys())))

            # [f] Non-placeable item absent; switching world_placeable False hides item while anchor stays.
            print("[f] Non-placeable item absent; toggling world_placeable False keeps anchor")
            check("[f] non-placeable note absent", note_id not in items_new, repr(list(items_new.keys())))
            cup_anchor_before = dict((stored_entry(room_study, cup_id) or {}).get("anchor") or {})
            check("[f] Silver Cup had stored anchor", bool(cup_anchor_before), repr(cup_anchor_before))
            update_item(cup_id, {"world_placeable": False})
            r_off = client.get(f"/play/locations/{loc_id}/items", headers=player_h)
            check("[f] GET after toggle status 200", r_off.status_code == 200, repr(r_off.status_code))
            items_off = {it["item_id"]: it for it in r_off.json().get("items", [])}
            check("[f] Silver Cup absent after world_placeable=False", cup_id not in items_off, repr(list(items_off.keys())))
            cup_anchor_after = (stored_entry(room_study, cup_id) or {}).get("anchor")
            check("[f] Silver Cup stored anchor stays intact", cup_anchor_after == cup_anchor_before,
                  f"{cup_anchor_after} vs {cup_anchor_before}")

            # [g] room_items_changed for a placeable item notifies avatar in another room of same location, never Everyone.
            print("[g] room_items_changed for placeable item notifies whole location, never Everyone")
            notify_calls = []

            def spy_notify(topics, *, to):
                notify_calls.append((topics, to))

            with patch.object(sync_topics, "notify", side_effect=spy_notify):
                sync_topics.room_items_changed(loc_id, room_study, True, True, item_id=key_id)

            check("[g] sync_topics.notify called once", len(notify_calls) == 1, repr(notify_calls))
            if notify_calls:
                topics_sent, recip = notify_calls[0]
                check("[g] topic is 'self'", topics_sent == "self", repr(topics_sent))
                check("[g] recipient is not Everyone", not isinstance(recip, sync_topics.Everyone), repr(recip))
                names = recip.names if isinstance(recip, sync_topics.Avatars) else ()
                check("[g] Bob (in porch / R2) is notified", viewer_b in names, repr(names))
                check("[g] Alice (in study / R1) is notified", viewer_a in names, repr(names))

            # [h] Without a session -> 401.
            print("[h] Unauthenticated request -> 401")
            r_unauth = client.get(f"/play/locations/{loc_id}/items")
            check("[h] unauthenticated GET -> 401", r_unauth.status_code == 401, repr(r_unauth.status_code))

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
