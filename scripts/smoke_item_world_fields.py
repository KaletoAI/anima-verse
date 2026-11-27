#!/usr/bin/env python3
"""Smoke: item world placement fields (world_placeable, world_size_m) and admin gate.

Usage:
    ./.venv/bin/python scripts/smoke_item_world_fields.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp directory
before importing any app module or app.server. Never touches worlds/ or instance/.

Hand-derived expectations:
[a] A new item created via add_item() has world_placeable == False and
    world_size_m is None; item_world_size(item) == DEFAULT_WORLD_SIZE_M (0.25).
    A legacy DB row whose meta JSON omits both keys still reads back with
    world_placeable == False and world_size_m is None via get_item() and list_items().
[b] update_item(id, {"world_placeable": True, "world_size_m": 0.4}) round-trips
    through get_item() as (True, 0.4), with item_world_size == 0.4.
    String "0.4" stores 0.4; 0, -1 and "abc" store None (item_world_size == 0.25);
    7 clamps to 5.0; 0.1234 rounds to 0.123.
[c] Exporting the item via content_io.export_item_to_zip(), deleting it, and
    re-importing via content_io.import_item_from_zip() preserves both
    world_placeable == True and world_size_m == 0.4.
[d] Through TestClient on app.server:
    - PUT /inventory/items/{id} as a player returns 403.
    - PUT /inventory/items/{id} as an admin returns 200 and persists the fields.
    - POST /inventory/items as an admin passes world_placeable and world_size_m through.
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


def check(label, actual, expected):
    ok = actual == expected
    status = "OK  " if ok else "FAIL"
    print(f"  {status} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="item-world-fields-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import init_schema, transaction
        init_schema()

        from app.models.inventory import (
            DEFAULT_WORLD_SIZE_M,
            add_item,
            delete_item,
            get_item,
            item_world_size,
            list_items,
            update_item,
        )
        from app.core import content_io

        # [a] Defaults on new item and legacy DB row without the keys
        print("[a] Defaults on new and legacy items")
        created = add_item(name="Brass Key", description="A small brass key")
        item_id = created["id"]
        loaded = get_item(item_id)
        check("[a] new item world_placeable", loaded["world_placeable"], False)
        check("[a] new item world_size_m", loaded["world_size_m"], None)
        check("[a] DEFAULT_WORLD_SIZE_M", DEFAULT_WORLD_SIZE_M, 0.25)
        check("[a] item_world_size default", item_world_size(loaded), 0.25)

        with transaction() as conn:
            conn.execute(
                "INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at, updated_at) "
                "VALUES (?, ?, ?, '', '{}', '[]', '{}', '', '')",
                ("item_legacy", "Legacy Coin", "tool"),
            )
        legacy = get_item("item_legacy")
        check("[a] legacy get_item world_placeable", legacy["world_placeable"], False)
        check("[a] legacy get_item world_size_m", legacy["world_size_m"], None)
        legacy_listed = next(i for i in list_items() if i["id"] == "item_legacy")
        check("[a] legacy list_items world_placeable", legacy_listed["world_placeable"], False)
        check("[a] legacy list_items world_size_m", legacy_listed["world_size_m"], None)

        # [b] update_item round-trip and cleaning rules
        print("[b] update_item round-trip and cleaning")
        update_item(item_id, {"world_placeable": True, "world_size_m": 0.4})
        loaded = get_item(item_id)
        check("[b] round-trip world_placeable", loaded["world_placeable"], True)
        check("[b] round-trip world_size_m", loaded["world_size_m"], 0.4)
        check("[b] item_world_size stored", item_world_size(loaded), 0.4)

        update_item(item_id, {"world_size_m": "0.4"})
        check("[b] string '0.4' -> 0.4", get_item(item_id)["world_size_m"], 0.4)

        for raw in (0, -1, "abc"):
            update_item(item_id, {"world_size_m": raw})
            after = get_item(item_id)
            check(f"[b] {raw!r} -> None", after["world_size_m"], None)
            check(f"[b] item_world_size after {raw!r}", item_world_size(after), 0.25)

        update_item(item_id, {"world_size_m": 7})
        check("[b] 7 clamps to 5.0", get_item(item_id)["world_size_m"], 5.0)

        update_item(item_id, {"world_size_m": 0.1234})
        check("[b] 0.1234 rounds to 0.123", get_item(item_id)["world_size_m"], 0.123)

        # [c] Export then import keeps both fields
        print("[c] Export / import round-trip")
        update_item(item_id, {"world_placeable": True, "world_size_m": 0.4})
        blob = content_io.export_item_to_zip(item_id)
        check("[c] delete before import", delete_item(item_id), True)
        check("[c] gone after delete", get_item(item_id), None)
        res = content_io.import_item_from_zip(blob)
        check("[c] import status", res["status"], "success")
        reimported = get_item(res["item_id"])
        check("[c] imported world_placeable", reimported["world_placeable"], True)
        check("[c] imported world_size_m", reimported["world_size_m"], 0.4)

        # [d] PUT /inventory/items/{id} auth gate + POST pass-through via app.server
        print("[d] HTTP routes and auth gate")
        logging.disable(logging.INFO)
        from app.server import app as server_app
        from app.core import auth_dependency
        from app.core.users import create_user, get_user_by_id
        from fastapi.testclient import TestClient

        player_id = create_user("player_smoke", "smoke-password", allowed_characters=[])

        def session_user(request):
            who = request.headers.get("x-test-user", "")
            if who == "admin":
                return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
            if who == "player":
                return get_user_by_id(player_id)
            return None

        with patch.object(auth_dependency, "_get_session_user", side_effect=session_user):
            client = TestClient(server_app)

            r_player = client.put(
                f"/inventory/items/{item_id}",
                json={"world_placeable": False, "world_size_m": 0.6},
                headers={"x-test-user": "player"},
            )
            check("[d] player PUT 403", r_player.status_code, 403)

            r_admin = client.put(
                f"/inventory/items/{item_id}",
                json={"world_placeable": True, "world_size_m": "0.65"},
                headers={"x-test-user": "admin"},
            )
            check("[d] admin PUT 200", r_admin.status_code, 200)
            after_put = get_item(item_id)
            check("[d] admin PUT persisted world_placeable", after_put["world_placeable"], True)
            check("[d] admin PUT persisted world_size_m", after_put["world_size_m"], 0.65)

            r_post = client.post(
                "/inventory/items",
                json={
                    "name": "Lantern",
                    "description": "An oil lantern",
                    "world_placeable": True,
                    "world_size_m": "0.35",
                },
                headers={"x-test-user": "admin"},
            )
            check("[d] admin POST 200", r_post.status_code, 200)
            posted = get_item(r_post.json()["item"]["id"])
            check("[d] admin POST world_placeable", posted["world_placeable"], True)
            check("[d] admin POST world_size_m", posted["world_size_m"], 0.35)

    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
