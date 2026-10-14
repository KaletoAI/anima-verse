#!/usr/bin/env python3
"""Verify the exact 3D locations view and its conditional revision contract.

One seeded location has one room: the view must project exactly eight location
fields and three room fields, including null for absent optional values.
A matching validator builds zero payloads. World writes, boot replacement and
recognised library kinds change the revision; unsupported files do not.
The full seed preserves its stored id, name, rooms order; the loader appends
decency, style_hint, swim_allowed, activity_hint, yaw_deg defaults. The
pre-Task-3 composer then appended image_count, has_entrance, surface_kind.
(No boundary_problems is appended because this seed has no drawn boundary.)
All storage and the surface library are disposable.
Usage: ./.venv/bin/python scripts/smoke_locations_rev.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

async def main():
    # Keep the event loop polling when sandboxed thread wakeups are delayed.
    async def poll():
        while True:
            await asyncio.sleep(0.01)

    polling = asyncio.create_task(poll())
    with tempfile.TemporaryDirectory(prefix="locations-rev-") as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        from app.core import db
        db.init_schema()
        from app.models import world
        from app.core import surface_textures, world_ops
        from app.routes.world import router
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        library = Path(tmp) / "library"
        library.mkdir()
        app = FastAPI()
        app.include_router(router)
        # Exercise the actual worldmap composer through a disposable HTTP adapter.
        @app.get("/play/worldmap")
        def worldmap():
            return world_ops.build_worldmap_payload(show_all=True)

        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke")
        with patch.object(surface_textures, "_dir", return_value=library):
            world.upsert_location({"id": "smoke", "name": "Smoke", "rooms": [
                {"id": "room", "name": "Room", "description": "excluded"}]})
            assert hasattr(world_ops, "locations_rev"), "locations_rev is not implemented"
            rev = (await client.get("/play/worldmap")).json().get("locations_rev")
            assert rev, "worldmap must expose locations_rev"
            with (
                patch.object(world_ops, "conditions_pass", side_effect=AssertionError("3D view checked conditions")),
                patch.object(world_ops, "list_gallery_images", side_effect=AssertionError("3D view read gallery")),
            ):
                response = await client.get("/world/locations?view=3d")
            assert response.status_code == 200
            assert response.headers["etag"] == f'"{rev}"'
            loc = response.json()["locations"][0]
            expected = {"id", "name", "description", "rooms", "entry_room",
                        "terrain", "surface_kind", "map3d"}
            assert set(loc) == expected == set(world_ops.VIEW_3D_FIELDS)
            assert set(loc["rooms"][0]) == {"id", "name", "layout"} == set(world_ops.VIEW_3D_ROOM_FIELDS)
            assert loc["map3d"] is None and loc["rooms"][0]["layout"] is None
            with (
                patch.object(world_ops, "build_locations_payload_3d", side_effect=AssertionError("304 built payload")),
                patch.object(world_ops, "build_locations_payload", side_effect=AssertionError("304 built full view")),
            ):
                for validator in (f'"{rev}"', f'W/"{rev}"', f'"other", W/"{rev}"', '*'):
                    cached = await client.get("/world/locations?view=3d", headers={"If-None-Match": validator})
                    assert cached.status_code == 304 and cached.content == b""
            assert (await client.get("/world/locations?view=3d&agent_name=x")).status_code == 400
            full = (await client.get("/world/locations")).json()["locations"][0]
            assert list(full) == ["id", "name", "rooms", "decency", "style_hint",
                                  "swim_allowed", "activity_hint", "yaw_deg",
                                  "image_count", "has_entrance", "surface_kind"], list(full)
            world.upsert_location({"id": "smoke", "name": "Changed", "rooms": []})
            assert world_ops.locations_rev() != rev
            rev = world_ops.locations_rev()
            with patch.object(world, "BOOT_EPOCH", "another-boot"):
                assert world_ops.locations_rev() != rev
            clock = surface_textures.time.monotonic()
            with patch.object(surface_textures.time, "monotonic", return_value=clock):
                (library / "smoke_kind_123456789.png").write_bytes(b"fixture")
                assert world_ops.locations_rev() == rev, "library TTL must hold for 5 seconds"
            with patch.object(surface_textures.time, "monotonic", return_value=clock + 6):
                changed = world_ops.locations_rev()
                assert changed != rev
            with patch.object(surface_textures.time, "monotonic", return_value=clock + 12):
                (library / "unsupported.txt").write_text("ignored")
                assert world_ops.locations_rev() == changed
            with patch.object(surface_textures.time, "monotonic", return_value=clock + 18):
                (library / "blends.json").write_text('{"smoke_blend": {"base": "smoke_kind"}}')
                blend_rev = world_ops.locations_rev()
                assert blend_rev != changed
            directory_stat = library.stat()
            with patch.object(surface_textures, "library_kinds",
                              wraps=surface_textures.library_kinds) as kinds:
                with patch.object(surface_textures.time, "monotonic", return_value=clock + 19):
                    surface_textures._write_blends({
                        "smoke_blend": {"base": "smoke_kind"},
                        "added_blend": {"base": "smoke_kind"},
                    })
                    assert library.stat() == directory_stat, "blend rewrite must leave directory stat unchanged"
                    assert world_ops.locations_rev() == blend_rev
                    assert kinds.call_count == 0, "within TTL must use cached kinds signature"
                with patch.object(surface_textures.time, "monotonic", return_value=clock + 24):
                    added_rev = world_ops.locations_rev()
                    assert added_rev != blend_rev, "in-place blend addition must change revision after TTL"
                    assert kinds.call_count == 1
                with patch.object(surface_textures.time, "monotonic", return_value=clock + 25):
                    surface_textures._write_blends({"smoke_blend": {"base": "smoke_kind"}})
                    assert library.stat() == directory_stat
                    assert world_ops.locations_rev() == added_rev
                    assert kinds.call_count == 1, "within TTL must not rescan library kinds"
                with patch.object(surface_textures.time, "monotonic", return_value=clock + 30):
                    assert world_ops.locations_rev() == blend_rev, "in-place blend removal must change revision after TTL"
                    assert kinds.call_count == 2
    await client.aclose()
    polling.cancel()
    print("PASS: locations revision, exact projection and conditional requests")


asyncio.run(main())
