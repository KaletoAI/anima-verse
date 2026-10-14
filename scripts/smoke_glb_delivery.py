#!/usr/bin/env python3
"""Check delivery caching, worker isolation, retries and retention.

Usage: .venv/bin/python scripts/smoke_glb_delivery.py

Hand-derived expectations: concurrent requests for identical bytes at two
paths queue one build;
the first returns the source, completion yields one sha256-named cache GLB.
Changed bytes yield a second digest/build; an atomic same-size replacement
with preserved mtime still yields a new digest/build because inode/ctime
change. Replacement during hashing must serve the source without memoizing
or scheduling the unstable digest; the next request builds the new bytes.
A skip marker, disabled switch or
missing Blender queues zero builds. Failures without deterministic skipped
reasons queue again. At a fixed time T, only recognized entries with mtime
strictly below T - 30*86400 are removed; the boundary itself survives.
Touching a sibling .used marker updates retention without changing served stat or ETag.
With delivery disabled, an atomic same-size replacement with preserved
mtime returns 200 and the new bytes when revalidated with the old ETag.
Eight inline route sites select delivery; an explicit character Download
keeps source bytes even after the cache is warm. FBX remains uncompressed.
"""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def run_async(coroutine):
    """Poll completions when the sandbox prevents selector socket wakeups."""
    import selectors
    class SmokeSelector(selectors.DefaultSelector):
        def select(self, timeout=None):
            return super().select(.05 if timeout is None else min(timeout, .05))
    with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(SmokeSelector())) as runner:
        return runner.run(coroutine)


async def disabled_delivery_http(src):
    """Revalidation must detect atomic replacement despite unchanged size/mtime."""
    from app.core import config
    from app.core.http_files import glb_file_response
    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    @app.get("/model.glb")
    async def model(request: Request):
        return glb_file_response(src, request)

    src.write_bytes(b"old geometry")
    with patch.object(config, "get", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get("/model.glb")
            assert first.status_code == 200 and first.content == b"old geometry"
            old_etag = first.headers["etag"]
            headers = {"If-None-Match": old_etag}
            assert (await client.get("/model.glb", headers=headers)).status_code == 304
            old_stat = src.stat()
            replacement = src.with_name("disabled-replacement.glb")
            replacement.write_bytes(b"new geometry")
            os.replace(replacement, src)
            os.utime(src, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            new_stat = src.stat()
            assert new_stat.st_size == old_stat.st_size
            assert new_stat.st_mtime_ns == old_stat.st_mtime_ns
            assert new_stat.st_ino != old_stat.st_ino
            updated = await client.get("/model.glb", headers=headers)
            assert updated.status_code == 200, "atomic replacement returned a stale 304"
            assert updated.content == b"new geometry"
            assert updated.headers["etag"] != old_etag


def route_guards(src, target):
    """All eight inline route sites use delivery; explicit download keeps bytes.

    Character responses stream a descriptor snapshot; consume it before checking.
    """
    async def body(response):
        return b"".join([chunk async for chunk in response.body_iterator])
    from app.core import glb_delivery, props, model3d, location_model3d
    from app.models import world as world_model
    from app.routes import assets, characters, play, prop_variants, world
    from starlette.requests import Request
    req = Request({"type": "http", "headers": [], "query_string": b""})
    with patch.object(glb_delivery, "delivery_path", return_value=target), \
            patch.object(props, "model_path", return_value=src), \
            patch.object(props, "model_file_path", return_value=src), \
            patch.object(prop_variants, "_variant", return_value=0), \
            patch.object(location_model3d, "find_building_model", return_value=src), \
            patch.object(location_model3d, "model_file_path", return_value=src), \
            patch.object(world_model, "find_location_by_room", return_value={"id": "fixture"}), \
            patch.object(play, "_test_figure_file", return_value=(src, "glb", "fixture")), \
            patch.object(model3d, "get_model3d_dir", return_value=src.parent), \
            patch.object(model3d, "find_model3d_serving_tier", return_value=(src, None, None)):
        responses = [assets.get_prop_model("fixture", req),
                     play.play_location_model("fixture", req),
                     play.play_test_figure_model(req), play.play_room_model("fixture", req),
                     prop_variants.prop_variant_model_file("fixture", 0, src.name, req),
                     world.location_model3d_file("fixture", src.name, req),
                     world.room_model3d_file("fixture", "room", src.name, req)]
        for response in responses:
            assert Path(response.path) == target
            assert src.name in response.headers["content-disposition"]
        inline = characters.get_character_model3d_file("demo", req)
        assert run_async(body(inline)) == target.read_bytes()
        download = characters.get_character_model3d_file("demo", req, download=True)
        assert run_async(body(download)) == src.read_bytes()
        assert download.headers["content-disposition"].startswith("attachment;")
        # Filename routing must retain FBX bytes without delivery lookup.
        fbx = src.with_suffix(".fbx")
        fbx.write_bytes(b"FBX source")
        with patch.object(location_model3d, "find_building_model", return_value=fbx):
            assert Path(play.play_location_model("fixture", req).path) == fbx


def main():
    with tempfile.TemporaryDirectory(prefix="smoke-delivery-") as tmp:
        paths.init(tmp)
        from app.core import glb_delivery as delivery
        from app.blender import runner
        from app.core import config
        from app.core.config_scope import scope_of
        from app.core.http_files import glb_file_response
        from starlette.requests import Request
        assert scope_of("image_generation.blender_meshopt_delivery") == "instance"
        run_async(disabled_delivery_http(Path(tmp) / "disabled.glb"))
        src = Path(tmp) / "original.glb"
        src.write_bytes(b"first source")
        cache = Path(tmp) / ".cache/meshopt"
        started, release = threading.Event(), threading.Event()
        calls = []
        outcome = ["output"]
        def fake_run(script, *, inputs, out_dir, **kwargs):
            assert threading.current_thread().name.startswith("glb-meshopt")
            assert script == "meshopt"
            calls.append(inputs["model"].read_bytes())
            started.set()
            assert release.wait(5), "worker was not released"
            if outcome[0] == "skip":
                return {"ok": True, "data": {"skipped": "no geometry"}, "outputs": {}}
            if outcome[0] == "fail":
                return {"ok": False, "error": "timeout", "data": {}, "outputs": {}}
            output = out_dir / "meshopt.glb"
            output.write_bytes(b"delivery copy")
            return {"ok": True, "data": {}, "outputs": {"model": str(output)}}
        def drain():
            release.set()
            delivery._worker.submit(lambda: None).result(timeout=5)
        with patch.object(config, "get", return_value=True), patch.object(runner, "status", return_value={"usable": True}), patch.object(runner, "run", side_effect=fake_run):
            for _ in range(10):
                assert delivery.delivery_path(src) == src
            assert started.wait(5) and len(calls) == 1
            same_bytes = Path(tmp) / "same-content.glb"
            same_bytes.write_bytes(src.read_bytes())
            with ThreadPoolExecutor(max_workers=4) as requests:
                assert all(p == same_bytes for p in requests.map(delivery.delivery_path, [same_bytes]*10))
            assert len(calls) == 1
            drain()
            target = delivery.delivery_path(src)
            assert target == cache / (hashlib.sha256(b"first source").hexdigest()+".glb")
            assert target.read_bytes() == b"delivery copy" and src.read_bytes() == b"first source"
            req = Request({"type": "http", "headers": [], "query_string": b""})
            os.utime(target, (1, 1))
            served_stat = target.stat()
            r1 = glb_file_response(src, req)
            first_etag = r1.headers["etag"]
            r2 = glb_file_response(src, req)
            assert first_etag == r2.headers["etag"]
            assert target.stat().st_mtime_ns == served_stat.st_mtime_ns
            assert target.stat().st_ctime_ns == served_stat.st_ctime_ns
            assert target.with_name(target.name + ".used").stat().st_mtime > 1
            assert "original.glb" in r2.headers["content-disposition"]
            conditional = Request({"type": "http", "headers": [(b"if-none-match", first_etag.encode())]})
            assert glb_file_response(src, conditional).status_code == 304
            assert Path(glb_file_response(src, req, disposition="attachment").path) == src
            route_guards(src, target)
            src.write_bytes(b"second source changed")
            assert delivery.delivery_path(src) == src
            drain()
            assert len(calls) == 2 and delivery.delivery_path(src) != target
            old_stat = src.stat()
            same_size = b"x" * old_stat.st_size
            replacement = Path(tmp) / "replacement.glb"
            replacement.write_bytes(same_size)
            os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            os.replace(replacement, src)
            new_stat = src.stat()
            assert new_stat.st_size == old_stat.st_size and new_stat.st_mtime_ns == old_stat.st_mtime_ns
            assert new_stat.st_ino != old_stat.st_ino and src.read_bytes() == same_size
            assert delivery.delivery_path(src) == src, "atomic replacement served a stale delivery copy"
            drain()
            assert len(calls) == 3 and calls[-1] == same_size
            assert delivery.delivery_path(src).stem == hashlib.sha256(same_size).hexdigest()
            src.write_bytes(b"skipped source")
            outcome[0] = "skip"
            assert delivery.delivery_path(src) == src
            drain()
            marker = cache / (hashlib.sha256(src.read_bytes()).hexdigest()+".skip")
            assert marker.is_file()
            os.utime(marker, (1, 1))
            assert delivery.delivery_path(src) == src and len(calls) == 4
            assert marker.stat().st_mtime == 1
            assert marker.with_name(marker.name + ".used").stat().st_mtime > 1
            src.write_bytes(b"timeout source with different size")
            outcome[0] = "fail"
            for _ in range(2):
                assert delivery.delivery_path(src) == src
                drain()
            assert len(calls) == 6 and not (cache / (hashlib.sha256(src.read_bytes()).hexdigest()+".skip")).exists(), calls
            with patch.object(config, "get", return_value=False):
                assert delivery.delivery_path(src) == src
            with patch.object(runner, "status", return_value={"usable": False}):
                assert delivery.delivery_path(src) == src
            assert len(calls) == 6
            # The worker must reject bytes changed after the request's hash.
            outcome[0] = "output"
            src.write_bytes(b"before queued change")
            old_digest = hashlib.sha256(src.read_bytes()).hexdigest()
            block = threading.Event()
            delivery._worker.submit(lambda: block.wait(5))
            assert delivery.delivery_path(src) == src
            src.write_bytes(b"after queued change")
            block.set()
            drain()
            assert not (cache / (old_digest+".glb")).exists() and len(calls) == 6
            # Replace equal-length bytes after reading, before the post-hash stat.
            race = Path(tmp) / "hash-race.glb"
            race.write_bytes(b"before hash race")
            race_stat = race.stat()
            file_digest = hashlib.file_digest
            def replace_during_hash(stream, algorithm):
                digest = file_digest(stream, algorithm)
                replacement.write_bytes(b"during hash race")
                os.utime(replacement, ns=(race_stat.st_atime_ns, race_stat.st_mtime_ns))
                os.replace(replacement, race)
                return digest
            with patch.object(hashlib, "file_digest", side_effect=replace_during_hash):
                assert delivery.delivery_path(race) == race
            drain()
            assert race.resolve() not in delivery._hashes, "unstable hash was memoized"
            assert len(calls) == 6, "unstable hash queued a build"
            assert delivery.delivery_path(race) == race
            drain()
            assert len(calls) == 7 and calls[-1] == b"during hash race"
            assert delivery.delivery_path(race).stem == hashlib.sha256(b"during hash race").hexdigest()
        now = time.time()
        cutoff = now - 30*86400
        fixtures = [("a"*64+".glb", cutoff-1), ("b"*64+".skip", cutoff-1),
                    ("c"*64+".glb", cutoff), ("d"*64+".skip", now), ("unrelated.txt", 1)]
        for name, mtime in fixtures:
            p = cache / name
            p.write_bytes(b"fixture")
            os.utime(p, (mtime, mtime))
        # Old served bytes stay when their independent usage marker is recent.
        used_old = cache / ("e"*64 + ".glb")
        used_old.write_bytes(b"recently used old copy")
        os.utime(used_old, (1, 1))
        used_marker = used_old.with_name(used_old.name + ".used")
        used_marker.touch()
        expired = cache / ("a"*64 + ".glb.used")
        expired.touch()
        os.utime(expired, (cutoff-1, cutoff-1))
        assert delivery.sweep_cache(now=now) == 2
        assert used_old.exists() and used_marker.exists()
        assert not expired.exists()
        assert all((cache/name).exists() == (mtime >= cutoff or name == "unrelated.txt") for name, mtime in fixtures)
    print("PASS: delivery deduplication, invalidation, gates, retries, HTTP and 30-day sweep")


if __name__ == "__main__":
    main()
