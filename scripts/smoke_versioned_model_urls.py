#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_versioned_model_urls.py

Task 88, tmp storage only, no Blender/server/network. Hand-derived contract:
each tier URL ends in the first 16 SHA256 hex digits of its selected SOURCE.
The tiny full/low files contain abc/xyz (ba7816bf8f01cfea/3608bca1e44ea6c4).
Two active prop variants have two tiers each; a separate full-only prop must
advertise exactly full, and an explicit low request falls back to abc.
Building, room, door and window sources are distinct; a window URL override
must retain its query before tier and v. All composed/terrain/world-prop tier
maps obey the same rule. Source hashes are memoized, never delivery hashes.

For each serving route: absent/stale v retains 3600 seconds (props/doors) or
no-cache (building/room); matching v becomes one-year immutable ONLY with
delivery off, a completed copy, or a deterministic skip. Pending delivery and
an unusable runner keep the old policy. All cases retain conditional 304s.
Replacing a prop and then a room source moves scene ETag AND URL v, even for
equal-length replacements with restored mtime; replacing
the prop also moves terrain/world-props signatures. Old v loses immutable.
Missing, unreadable and racing sources omit v without breaking composition.
Timing compares the SAME scene with 24 placed props and cold/warm hash memo.
"""
from contextlib import ExitStack
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def request(url="", etag=""):
    from starlette.requests import Request
    return Request({"type": "http", "query_string": urlsplit(url).query.encode(),
                    "headers": [(b"if-none-match", etag.encode())] if etag else []})


def main():
    with tempfile.TemporaryDirectory(prefix="versioned-model-urls-") as tmp, ExitStack() as stack:
        root = Path(tmp)
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
        from app.core import config, db, door_models, glb_delivery, location_model3d as lm, props
        from app.core import scene_recipe as sr
        from app.core.model_store import variant_urls, write_sidecar
        from app.models import terrain, world, world_props
        from app.routes import assets, play
        from app.blender import refine, runner
        db.init_schema()
        stack.enter_context(patch.object(refine, "auto_lod_enabled", return_value=False))
        stack.enter_context(patch.object(refine, "auto_bake_vc_enabled", return_value=False))
        stack.enter_context(patch.object(runner, "is_available", return_value=False))
        stack.enter_context(patch.object(runner, "run", side_effect=AssertionError("unexpected Blender call")))

        def mesh(gallery, data, tier="full"):
            gallery.dir.mkdir(parents=True, exist_ok=True)
            target = gallery.new_path()
            target.write_bytes(data)
            write_sidecar(target, {"format": "glb", "tier": tier})
            assert gallery.select(target.name, tier)
            return target

        pid = props.create_prop(name="Tree", width_m=1, height_m=2, depth_m=1)["id"]
        sources = {}
        for idx in range(2):
            if idx:
                props.add_variant(pid)
            for tier, data in (("full", b"abc"), ("low", b"xyz")):
                sources[(idx, tier)] = mesh(props.model_gallery(pid, idx), data + (b"2" if idx else b""), tier)
        lone = props.create_prop(name="Full only", width_m=1, height_m=1, depth_m=1)["id"]
        lone_path = mesh(props.model_gallery(lone, 0), b"abc")
        loc = world.add_location(name="Warehouse", description="URL cache smoke",
                                 rooms=[{"id": "hall", "name": "Hall"}])
        lid = loc["id"]
        loc["map3d"] = {"plan_width_m": 20,
                        "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]}
        loc["rooms"][0]["layout"] = {
            "x": -8, "y": -8, "w": 16, "d": 12,
            "props": [{"id": f"p{i}", "prop_id": pid, "at": [i % 8 + 1, i // 8 + 1]}
                      for i in range(24)],
            "openings": [{"edge": "N", "at": .25, "type": "door", "door_style": "plain",
                          "width_m": 1, "height_m": 2},
                         {"edge": "N", "at": .75, "type": "window", "width_m": 1.2,
                          "height_m": 1.2, "sill_m": .9}]}
        world.upsert_location(loc, sync_world=True)
        building = mesh(lm._gallery(lid), b"building")
        building_low = mesh(lm._gallery(lid), b"building low", "low")
        room = mesh(lm._gallery(lid, "hall"), b"room")
        room_low = mesh(lm._gallery(lid, "hall"), b"room low", "low")
        door_sources = {}
        for sig, data in (("a" * 16, b"door"), ("b" * 16, b"window")):
            target = paths.get_storage_dir() / "door_models" / sig / "model.glb"
            target.parent.mkdir(parents=True)
            target.write_bytes(data)
            door_sources[sig] = target
        door = {"sig": "a" * 16, "size_m": [1, 2], "leaf_bbox": [[0, 0, 0], [1, 2, .1]]}
        window = {"sig": "b" * 16, "size_m": [1.36, 1.33],
                  "url": f'/assets/doors/{"b" * 16}/model?fixture=window'}
        stack.enter_context(patch.object(door_models, "ensure_door_model", return_value=door))
        stack.enter_context(patch.object(door_models, "ensure_window_model", return_value=window))

        def source_for(url):
            parsed = urlsplit(url)
            query = parse_qs(parsed.query)
            tier = query.get("tier", [""])[0]
            ident = parsed.path.split("/")[-2]
            if parsed.path.startswith("/assets/props/"):
                idx = query.get("variant", [None])[0]
                return props.model_path(ident, tier, variant=int(idx) if idx else None)
            if parsed.path.startswith("/assets/doors/"):
                return door_models.model_path(ident)
            return lm.find_building_model(lid, room_id=ident if "/rooms/" in parsed.path else "", tier=tier)

        def check_url(url):
            digest = hashlib.sha256(source_for(url).read_bytes()).hexdigest()[:16]
            assert parse_qs(urlsplit(url).query).get("v") == [digest], (url, digest)
            assert url.endswith("v=" + digest), url
            assert list(parse_qs(urlsplit(url).query))[-1] == "v"

        def check_maps(value):
            count = 0
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "variants":
                        for url in child.values():
                            check_url(url)
                            count += 1
                    elif key == "model_variants":
                        for tier_map in child:
                            for url in tier_map.values():
                                check_url(url)
                                count += 1
                    else:
                        count += check_maps(child)
            elif isinstance(value, list):
                count += sum(check_maps(v) for v in value)
            return count

        def compose():
            width, bmeta, rmeta = sr.scene_inputs(loc, lid)
            return sr.compose_scene(loc, plan_width_m=width, building_meta=bmeta, room_metas=rmeta)

        compose()  # Import/initialize the composer before comparing only hash memo cost.
        glb_delivery._hashes.clear()
        with patch.object(hashlib, "file_digest", wraps=hashlib.file_digest) as hashing:
            started = time.perf_counter()
            scene = compose()
            cold = time.perf_counter() - started
            assert hashing.call_count == 10, "four prop tiers + four building/room tiers + door/window hash once"
        with patch.object(hashlib, "file_digest", side_effect=AssertionError("warm memo rehashed")):
            started = time.perf_counter()
            warm = compose()
            warm_time = time.perf_counter() - started
        assert scene == warm
        print(f"TIMING: 24 props cold={cold * 1000:.3f} ms warm={warm_time * 1000:.3f} ms")
        assert check_maps(scene) >= 100
        assert {"building", "room"} <= {m["role"] for m in scene["models"]}
        assert {"door:" + door["sig"], "window:" + window["sig"]} <= {m["id"] for m in scene["models"]}
        assert any("fixture=window&tier=full&v=" in m["variants"].get("full", "") for m in scene["models"])
        single = sr._prop_variant_urls(lone, {"model_tiers": ["full"]})[0]
        assert single == {"full": f"/assets/props/{lone}/model?tier=full&v=ba7816bf8f01cfea"}
        fallback = variant_urls(f"/assets/props/{lone}/model", ["low"],
                                version_for_tier=lambda t: glb_delivery.source_version(props.model_path(lone, t)))
        assert fallback["low"].endswith("tier=low&v=ba7816bf8f01cfea")

        terrain.save_area({"kind": "grass", "polygon": [[30, 30], [40, 30], [40, 40], [30, 40]],
                           "meta": {"scatter": [{"model": f"/assets/props/{pid}/model", "density": .1}]}})
        assert check_maps(play.get_terrain_route()) >= 6
        world_props.save_world_prop({"prop_id": pid, "x": 30, "z": 30})
        assert check_maps(world_props.payload_rows()) >= 6
        for meta in (play.play_location_model_meta(lid), play.play_room_model_meta("hall")):
            check_url(meta["url"])
            for info in meta["tiers"].values():
                check_url(info["url"])

        # All route functions remain synchronous; FastAPI dispatches them to workers.
        for handler in (assets.get_prop_model, assets.get_door_model, play.play_location_model,
                        play.play_room_model, play.play_location_model_meta, play.play_room_model_meta,
                        play.play_location_scene,
                        play.get_terrain_route):
            assert not inspect.iscoroutinefunction(handler)

        routes = [(lambda req: assets.get_prop_model(pid, req), sources[(0, "full")], "public, max-age=3600"),
                  (lambda req: assets.get_door_model(door["sig"], req), door_sources[door["sig"]], "public, max-age=3600"),
                  (lambda req: play.play_location_model(lid, req), building, "no-cache"),
                  (lambda req: play.play_location_model(lid, req, tier="low"), building_low, "no-cache"),
                  (lambda req: play.play_room_model("hall", req), room, "no-cache"),
                  (lambda req: play.play_room_model("hall", req, tier="low"), room_low, "no-cache")]
        for (idx, tier), source in sources.items():
            routes.append((lambda req, idx=idx, tier=tier:
                           assets.get_prop_model(pid, req, tier=tier, variant=str(idx)),
                           source, "public, max-age=3600"))
        routes.append((lambda req: assets.get_prop_model(lone, req, tier="low"),
                       lone_path, "public, max-age=3600"))
        cache = paths.get_storage_dir() / ".cache" / "meshopt"
        cache.mkdir(parents=True, exist_ok=True)
        original_get = config.get
        delivery_on = [False]
        stack.enter_context(patch.object(config, "get", side_effect=lambda key, *a, **kw:
            delivery_on[0] if key == "image_generation.blender_meshopt_delivery" else original_get(key, *a, **kw)))
        for route, source, old_policy in routes:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            for mode in ("off", "pending", "unusable", "copy", "skip"):
                delivery_on[0] = mode != "off"
                delivery_file = cache / (digest + ".glb")
                marker = cache / (digest + ".skip")
                if mode == "copy":
                    delivery_file.write_bytes(b"final delivery bytes")
                if mode == "skip":
                    marker.write_text("no geometry", encoding="utf-8")
                with patch.object(runner, "status", return_value={"usable": mode != "unusable"}), \
                        patch.object(glb_delivery._worker, "submit"):
                    for version in ("", "0" * 16, digest[:16]):
                        query = "?v=" + version if version else ""
                        expected = ("public, max-age=31536000, immutable" if version == digest[:16]
                                    and mode in ("off", "copy", "skip") else old_policy)
                        response = route(request(query))
                        assert response.headers["cache-control"] == expected, (mode, query, response.headers)
                        assert Path(response.path) == (delivery_file if mode == "copy" else source)
                        conditional = route(request(query, response.headers["etag"]))
                        assert conditional.status_code == 304 and conditional.headers["cache-control"] == expected
                delivery_file.unlink(missing_ok=True)
                marker.unlink(missing_ok=True)
                glb_delivery._pending.clear()
        delivery_on[0] = False

        # Use the actual scene route's ETag and payload cache without manual invalidation.
        before = play.play_location_scene(lid, request())
        terrain_before = terrain.terrain_sig()
        wp_before = world_props.payload_snapshot()
        old_prop_url = sr._prop_variant_urls(pid, {"model_tiers": ["full"]})[0]["full"]
        old_room_url = play.play_room_model_meta("hall")["url"]
        for source in (sources[(0, "full")], room, building):
            old_scene = json.loads(before.body)
            old_urls = [m["variants"] for m in old_scene["models"]]
            old_stat = source.stat()
            replacement = source.with_suffix(".tmp")
            replacement.write_bytes(b"X" + source.read_bytes()[1:])
            os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            replacement.replace(source)
            # Published prop writers invalidate this existing five-second TTL.
            if source == sources[(0, "full")]:
                sr.invalidate_prop_lib_token()
            after = play.play_location_scene(lid, request(etag=before.headers["etag"]))
            assert after.status_code == 200 and after.headers["etag"] != before.headers["etag"]
            new_scene = json.loads(after.body)
            assert [m["variants"] for m in new_scene["models"]] != old_urls
            assert new_scene["signature"] != old_scene["signature"], "changed URLs must remount the scene"
            check_maps(new_scene)
            before = after
        assert terrain.terrain_sig() != terrain_before
        assert world_props.payload_snapshot()[1] != wp_before[1]
        check_maps(play.get_terrain_route())
        check_maps(world_props.payload_rows())
        assert assets.get_prop_model(pid, request(old_prop_url)).headers["cache-control"] == "public, max-age=3600"
        assert play.play_room_model("hall", request(old_room_url)).headers["cache-control"] == "no-cache"

        for error in (FileNotFoundError("missing"), PermissionError("unreadable"), OSError("hash race")):
            with patch.object(glb_delivery, "_sha", side_effect=error):
                unavailable = compose()
                assert unavailable["models"]
                for model in unavailable["models"]:
                    assert all("&v=" not in url for url in model["variants"].values())
                meta = play.play_location_model_meta(lid)
                assert meta["url"] == f"/play/locations/{lid}/model"
                assert meta["tiers"]["full"]["url"] == f"/play/locations/{lid}/model?tier=full"
        lone_path.unlink()
        assert glb_delivery.source_version(lone_path) == ""
        print("PASS: versioned scene/scatter/world-props/meta URLs, fallbacks, memo, HTTP policies/304s, invalidation and failures")


if __name__ == "__main__":
    main()
