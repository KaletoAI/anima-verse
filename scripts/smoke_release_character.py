#!/usr/bin/env python3
"""Release/spectate contract, isolated storage and instance; no TestClient threads.

Expectations from task 111: release preserves login/default, clears both resolver
bindings and makes avatar-only presence offmap; ordinary characters become autonomous.
All listed player reads stay defined, avatar writes return 409/no_avatar, and
switch/login restore control. Stream subscriptions must lose private bindings.
Usage: timeout 600 .venv/bin/python scripts/smoke_release_character.py
"""
import atexit
import asyncio
import json
import shutil
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory(prefix="release-character-")
_storage = Path(tempfile.mkdtemp(prefix="release-world-"))
_instance = Path(tempfile.mkdtemp(prefix="release-instance-"))
atexit.register(shutil.rmtree, _storage, ignore_errors=True)
atexit.register(shutil.rmtree, _instance, ignore_errors=True)
os.environ["STORAGE_DIR"] = str(_storage)
os.environ["INSTANCE_DIR"] = str(_instance)
os.environ["ANIMATION_CLIPS_DIR"] = str(Path(_tmp.name) / "clips")
from app.core import paths
paths.init(_storage)
paths.init_instance(_instance)
from app.core import db, users, sessions, auth_dependency as auth, sync_topics
from app.models import account
from app.routes import account as routes, play, prop_actions, chat, auth as auth_routes, world
from fastapi import FastAPI
import httpx

# This sandbox cannot wake the HTTP worker-thread portal reliably. Execute the
# same FastAPI handlers/dependencies inline; no business logic is mocked here.
async def inline(func, *args, **kwargs):
    return func(*args, **kwargs)
import fastapi.routing
import fastapi.dependencies.utils
fastapi.routing.run_in_threadpool = inline
fastapi.dependencies.utils.run_in_threadpool = inline
asyncio.to_thread = inline

db.init_schema()
from app.models import character
from app.core.keyed_lock import keyed_lock
for name in ("Traveller", "Resident", "Other"):
    with keyed_lock("character_profile", name):
        assert character.save_character_profile(name, {"name": name, "template": "human-default"}, create_new=True)
    assert character.save_character_config(name, {"avatar_only_presence": "true" if name == "Traveller" else "false"})
    character.set_character_pos(name, 5, 6)

from app.models import world as world_model
home = world_model.add_location("Spectator Square", "A public square.", create_new=True)["id"]
world_model.update_location_position(home, 10, 20)
# A placed place the released characters have never learned: a spectator must not see it
# (the map is filtered by the released character's knowledge, never the admin view).
hidden = world_model.add_location("Hidden Grotto", "Unknown to the traveller.", create_new=True)["id"]
world_model.update_location_position(hidden, 400, 400)
for _n in ("Traveller", "Resident"):
    character.set_known_locations(_n, [home])

uid = users.create_user("spectator", "test-password", allowed_characters=["Traveller", "Resident"])
other = users.create_user("other", "test-password", allowed_characters=["Other"])
users.update_user(other, settings={"active_character": "Other"})
app = FastAPI()
for router in (routes.router, play.router, prop_actions.router, chat.router, auth_routes.router, world.router):
    app.include_router(router)
app.middleware("http")(auth.auth_gate_middleware)
app.middleware("http")(auth.user_context_middleware)

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as c:
        assert (await c.post("/account/release-character")).status_code == 401
        c.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(uid))
        legacy = account.get_user_profile()
        legacy["active_character"] = "Traveller"
        account.save_user_profile(legacy)
        # Legacy empty-active settings still resolve allowed[0] before release.
        users.update_user(uid, settings={"default_character": "Traveller"})
        r = await c.post("/account/release-character")
        assert r.status_code == 200
        assert character.get_character_pos("Traveller") is None
        character.save_character_current_location("Traveller", home, _skip_compliance=True)
        assert character.get_character_current_location("Traveller") == home
        for name in ("Traveller", "Resident"):
            users.update_user(uid, settings={"active_character": name, "current_character": name, "default_character": name})
            stale_user = users.get_user_by_id(uid)
            conn = sync_topics.register(uid, "fixture", name, "fixture-location")
            r = await c.post("/account/release-character", json={"character_name": "Other"})
            assert r.status_code == 200, r.text
            assert conn.binding()[:2] == ("", "")
            sync_topics.unregister(conn)
            if name == "Traveller":
                assert character.get_character_current_location(name) == ""
                assert character.get_character_pos(name) is None
                assert character.get_character_profile(name)["_offmap_return_location"] == home
            else:
                assert character.get_character_current_location(name) == ""
                assert character.get_character_pos(name) == {"x": 5.0, "z": 6.0}
            # A position report authenticated before release must not resurrect it.
            token = auth.current_user_ctx.set(stale_user)
            try:
                from fastapi import HTTPException
                try:
                    play._play_pos_sync(name, {"x": 5, "z": 6})
                    raise AssertionError("stale report was accepted after release")
                except HTTPException as error:
                    assert error.status_code == 409 and error.detail["reason"] == "no_avatar"
            finally:
                auth.current_user_ctx.reset(token)
            u = users.get_user_by_id(uid)
            assert u["settings"]["avatar_released"] is True
            assert u["settings"]["default_character"] == name
            assert account._active_for_user(u) == ""
            assert account.get_active_character_for_user(uid) == ""
            assert not account.is_player_controlled(name)
            assert account.get_active_character_for_user(other) == "Other"
        # The public world still exists while the avatar-only figure is gone.
        r = await c.get("/play/worldmap")
        assert r.json()["avatar_released"] is True
        assert r.json()["avatar"] == "", r.json()["avatar"]
        assert home in {loc["id"] for loc in r.json()["locations"]}
        assert hidden not in {loc["id"] for loc in r.json()["locations"]}, "spectator saw an unknown place"
        assert "Resident" in {row["name"] for row in r.json()["characters"]}
        assert "Traveller" not in {row["name"] for row in r.json()["characters"]}
        for url in ["/world/locations?view=3d", "/play/terrain", "/play/heightfield",
                    "/play/terrain-layers", f"/play/locations/{home}/scene"]:
            r = await c.get(url)
            assert r.status_code in (200, 404), (url, r.status_code, r.text[:200])
        # An empty allowed list may never borrow the legacy account's avatar.
        assert account._active_for_user({"settings": {}, "allowed_characters": []}) == ""
        reads = ["scene", "self", "others", "notices", "places", "worldmap", "explored",
                 "belongings", "gallery", "galleries", "scenes", "schedule", "story-arcs", "news",
                 "messages", "messages/thread?partner=Other", "item/missing", "interact/options", "prop-actions", "prop-actions/state"]
        for path in reads:
            r = await c.get("/play/" + path)
            assert r.status_code in (200, 409), (path, r.status_code, r.text)
            if r.status_code == 409:
                assert r.json()["detail"]["reason"] == "no_avatar", (path, r.text)
            elif "avatar" in r.json():
                assert r.json()["avatar"] == "", (path, r.text)
            print("read", path, r.status_code)
        prop_target = {"location_id": "x", "room_id": "r", "placement_id": "p", "variant_uid": "v"}
        for path, body in [
            ("request", {"target": prop_target, "action_id": "sit", "revision": "fixture"}),
            ("check", {"target": prop_target, "action_id": "sit", "revision": "fixture"}),
            ("respond", {"execution_id": "x", "accept": True}),
            ("cancel", {"execution_id": "x"}), ("hold", {"execution_id": "x", "hold": True}),
            ("alt", {"execution_id": "x", "alt": "x"}),
        ]:
            r = await c.post("/play/prop-actions/" + path, json=body)
            assert r.status_code == 409 and r.json()["detail"]["reason"] == "no_avatar", (path, r.text)
        writes = ["pos", "say", "travel", "travel/cancel", "enter-room", "scene-photo/prepare", "scene-photo",
                  "scene-render", "self/mood", "self/activity", "self/outfit", "party/leave", "party/respond",
                  "interact", "interact/respond", "interact/cancel", "interact/end", "equip", "unequip",
                  "use-item", "give", "drop", "pickup", "cast", "read", "messages/send", "messages/read-all"]
        for path in writes:
            r = await c.post("/play/" + path, json={})
            assert r.status_code == 409 and r.json()["detail"]["reason"] == "no_avatar", (path, r.status_code, r.text)
        # Uploads stay avatar-free (admin chats use them too); the photo itself
        # is refused above (scene-photo/prepare, scene-photo), and an unused
        # screenshot upload is swept by the retention job.
        with patch.object(routes, "list_available_characters", return_value=["Resident"]), \
             patch("app.models.character_template.is_feature_enabled", return_value=True):
            r = await c.post("/account/switch-character", json={"character_name": "Resident"})
            assert r.status_code == 200, r.text
        assert users.get_user_by_id(uid)["settings"]["avatar_released"] is False
        assert account.get_active_character_for_user(uid) == "Resident"
        await c.post("/account/release-character")
        r = await c.post("/auth/login", json={"username": "spectator", "password": "test-password"})
        assert r.status_code == 200, r.text
        assert users.get_user_by_id(uid)["settings"]["avatar_released"] is False
        assert account.get_active_character_for_user(uid) == "Resident"
        # Presence release is also safe to repeat, and the session reaper does not restore it.
        await c.post("/account/release-character")
        assert account.reap_orphaned_avatars() == 0
        assert account.get_active_character_for_user(uid) == ""
        print(f"PASS release/presence/resolvers/isolation, {len(reads)} reads, {len(writes)} writes, photo, switch, login")

asyncio.run(main())
