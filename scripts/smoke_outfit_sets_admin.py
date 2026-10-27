#!/usr/bin/env python3
"""Saved outfits: preview never equips; deletion preserves pieces and ownership.

Uses real inventory routes, users, sessions and a throwaway world database.
Usage: ./.venv/bin/python scripts/smoke_outfit_sets_admin.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths

STORAGE = tempfile.TemporaryDirectory(prefix="outfit-sets-admin-smoke-")
paths.init(STORAGE.name)
paths.init_instance(Path(STORAGE.name) / "instance")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core import db, sessions, users
from app.models.character import add_character_outfit, save_character_profile
from app.models.inventory import add_item, add_to_inventory, equip_piece, get_equipped_pieces
from app.routes.inventory import router

db.init_schema()


def preserved_state():
    conn = db.get_connection()
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("items", "inventory_items", "equipped_pieces", "characters", "character_state")
    }


def main():
    for name in ("demo", "other"):
        assert save_character_profile(name, {
            "character_name": name, "template": "human-roleplay", "language": "en",
        }, create_new=True)
    shirt = add_item(name="White shirt", category="outfit_piece", prompt_fragment="white shirt",
                     outfit_piece={"slots": ["top"]})["id"]
    trousers = add_item(name="Blue trousers", category="outfit_piece", prompt_fragment="blue trousers",
                        outfit_piece={"slots": ["bottom"]})["id"]
    jacket = add_item(name="Worn jacket", category="outfit_piece", prompt_fragment="worn jacket",
                      outfit_piece={"slots": ["top"]})["id"]
    for item_id in (shirt, trousers, jacket):
        add_to_inventory("demo", item_id)
    equip_piece("demo", jacket)
    outfit_id = add_character_outfit("demo", {
        "name": "Research", "pieces": [shirt, trousers, "missing-piece"],
    })
    other_id = add_character_outfit("demo", {"name": "Keep this set", "pieces": [jacket]})
    other_before = tuple(db.get_connection().execute(
        "SELECT * FROM outfits_sets WHERE id=?", (other_id,),
    ).fetchone())
    tokens = {}
    for role in (users.ROLE_ADMIN, users.ROLE_USER):
        user_id = users.create_user("demo-" + role, "temporary-smoke-password", role,
                                    allowed_characters=["demo", "other"])
        tokens[role] = sessions.create_session(user_id)
    app = FastAPI()
    app.include_router(router)
    url = f"/inventory/characters/demo/outfit-sets/{outfit_id}"
    with TestClient(app, raise_server_exceptions=False) as client:
        for method in ("GET", "DELETE"):
            assert client.request(method, url).status_code == 401, "anonymous outfit access"
        client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
        for method in ("GET", "DELETE"):
            assert client.request(method, url).status_code == 403, "player may not manage saved outfits"
        client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])
        before = preserved_state()
        response = client.get(url)
        assert response.status_code == 200, (response.status_code, response.text)
        preview = response.json()
        assert preview["id"] == outfit_id and preview["name"] == "Research"
        assert [(p["item_id"], p["name"], p["missing"]) for p in preview["pieces"]] == [
            (shirt, "White shirt", False), (trousers, "Blue trousers", False),
            ("missing-piece", "", True),
        ]
        assert preserved_state() == before, "preview must not equip, grant or edit pieces"
        assert get_equipped_pieces("demo") == {"top": jacket}
        assert client.delete(url.replace("/demo/", "/other/")).status_code == 404
        assert client.get(url.replace(outfit_id, "absent")).status_code == 404
        assert client.delete(url.replace(outfit_id, "absent")).status_code == 404
        assert preserved_state() == before, "wrong owner or unknown set changed inventory"
        response = client.post("/inventory/characters/demo/apply-outfit-set", json={"outfit_id": outfit_id})
        assert response.status_code == 200, response.text
        assert get_equipped_pieces("demo") == {"top": shirt, "bottom": trousers}
        before_delete = preserved_state()
        conn = db.get_connection()
        conn.execute("CREATE TRIGGER prevent_outfit_delete BEFORE DELETE ON outfits_sets "
                     "BEGIN SELECT RAISE(ABORT, 'smoke write failure'); END")
        conn.commit()
        assert client.delete(url).status_code == 500, "failed deletion reported success"
        assert client.get(url).status_code == 200, "failed write removed the set"
        conn.execute("DROP TRIGGER prevent_outfit_delete")
        conn.commit()
        assert preserved_state() == before_delete
        response = client.delete(url)
        assert response.status_code == 200, response.text
        assert client.get(url).status_code == 404
        assert client.delete(url).status_code == 404
        assert preserved_state() == before_delete, "deleting a set changed its pieces or worn outfit"
        assert tuple(conn.execute("SELECT * FROM outfits_sets WHERE id=?", (other_id,)).fetchone()) == other_before
    print("PASS: preview is read-only; apply is explicit; admin-only deletion preserves pieces, worn outfit and other sets")


if __name__ == "__main__":
    try:
        main()
    finally:
        for connection in db._connections.values():
            connection.close()
        STORAGE.cleanup()
