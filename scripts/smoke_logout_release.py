#!/usr/bin/env python3
"""POST /auth/logout releases only the caller's own avatar.

Usage:
    ./.venv/bin/python scripts/smoke_logout_release.py

Expected, by hand from the route's contract (/auth/logout is on the public
allowlist, so an anonymous call reaches the route):
  * the legacy account row (id=1) holds active_character "Legacy Hero";
    an ANONYMOUS POST /auth/logout answers 200 and leaves that row untouched
    -> still "Legacy Hero" (it used to fall through to the account row and
    clear it — anyone could take that avatar off the map)
  * a signed-in player whose settings hold active_character "Player Hero"
    logs out -> 200, its settings now hold "" for active_character and
    current_character, and the account row still says "Legacy Hero"
"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="logout-release-") as temporary:
        root = Path(temporary)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        from app.server import app
        from app.core import users
        from app.models import account
        from fastapi.testclient import TestClient

        profile = account.get_user_profile()
        profile["active_character"] = "Legacy Hero"
        profile["current_character"] = "Legacy Hero"
        account.save_user_profile(profile)

        anonymous = TestClient(app)
        assert anonymous.post("/auth/logout").status_code == 200
        after = account.get_user_profile()
        assert after.get("active_character") == "Legacy Hero", after.get("active_character")
        assert after.get("current_character") == "Legacy Hero", after.get("current_character")

        created = users.create_user("logout-player", "smoke-password", role="user")
        user_id = created["id"] if isinstance(created, dict) else created
        users.update_user(user_id, settings={
            "active_character": "Player Hero", "current_character": "Player Hero"})
        client = TestClient(app)
        assert client.post("/auth/login", json={
            "username": "logout-player", "password": "smoke-password"}).status_code == 200
        assert client.post("/auth/logout").status_code == 200
        settings = users.get_user_by_id(user_id)["settings"]
        assert settings.get("active_character") == "", settings
        assert settings.get("current_character") == "", settings
        assert account.get_user_profile().get("active_character") == "Legacy Hero"
        print("PASS: logout releases only the caller's own avatar; anonymous logout releases nothing")


if __name__ == "__main__":
    main()
