#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_model_version.py

A demo model has abc bytes, low has xyz: SHA256 prefixes ba7816bf8f01cfea
and 3608bca1e44ea6c4. Texture replacement changes texture_url alone.
A delivery copy arriving after meta changes only GLB v; the old URL must
return new bytes with no-cache. Downloads retain source bytes and filename.
A publisher waits on model3d_publication while a request opens its snapshot;
replacement after opening must return one complete generation, never a mix.
Both info endpoints must use the same URLs, and model_rev stays in the payload.
"""
import asyncio
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from starlette.requests import Request

async def body(response):
    if hasattr(response, "body_iterator"):
        return b"".join([chunk async for chunk in response.body_iterator])
    return response.body


def smoke_loop():
    """Observe worker completions even when a sandbox blocks selector wakeups."""
    import selectors
    class SmokeSelector(selectors.DefaultSelector):
        def select(self, timeout=None):
            return super().select(.05 if timeout is None else min(timeout, .05))
    return asyncio.SelectorEventLoop(SmokeSelector())


def run_async(coroutine):
    with asyncio.Runner(loop_factory=smoke_loop) as runner:
        return runner.run(coroutine)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
    from app.core import model3d, glb_delivery
    from app.core.http_files import atomic_replace
    from app.core.keyed_lock import keyed_lock
    from app.routes import characters
    from app.core import db
    db.init_schema()
    from app.models.character import get_character_dir
    get_character_dir("demo").mkdir(parents=True, exist_ok=True)
    directory = model3d.get_model3d_dir("demo")
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "demo.fbx"; source.write_bytes(b"abc")
    low = directory / "low" / source.name
    low.parent.mkdir(); low.write_bytes(b"xyz")
    texture = source.with_suffix(".png"); texture.write_bytes(b"abc")
    base = "/characters/demo/model3d/file"
    def request(query="", headers=()):
        return Request({"type": "http", "headers": list(headers), "query_string": query.encode()})
    # Keep selection independent of outfit/profile setup, but exercise the real
    # tier selector, URL builder and response adapters against helper-owned paths.
    with patch.object(model3d, "find_model3d_serving", return_value=(source, "exact")):
        urls = model3d.versioned_model_urls("demo", base)
        assert urls["url"] == base + "?v=ba7816bf8f01cfea"
        assert urls["low_url"] == base + "?tier=low&v=3608bca1e44ea6c4"
        assert urls["texture_url"] == "/characters/demo/model3d/texture?v=ba7816bf8f01cfea"
        staged = directory / "texture.tmp"; staged.write_bytes(b"xyz")
        atomic_replace(staged, texture)
        changed = model3d.versioned_model_urls("demo", base)
        assert changed["url"] == urls["url"] and changed["low_url"] == urls["low_url"]
        assert changed["texture_url"].endswith("v=3608bca1e44ea6c4")
        with patch.object(model3d, "current_outfit_state", return_value=(None, None, "demo")):
            info = model3d.get_model3d_info("demo")["model"]
            assert {key: info[key] for key in changed} == changed
            assert "model_rev" in info
            meta = characters.get_character_model_meta("demo")
            assert meta["url"] == "/characters/demo/model?v=ba7816bf8f01cfea"
            assert meta["low_url"] == "/characters/demo/model?tier=low&v=3608bca1e44ea6c4"
            assert meta["texture_url"] == "/characters/demo/model/texture?v=3608bca1e44ea6c4"
        r = characters._model_asset_response("demo", request("v=ba7816bf8f01cfea"))
        assert r.headers["cache-control"].endswith("immutable")
        assert run_async(body(r)) == b"abc"
        source_glb = directory / "demo.glb"; source_glb.write_bytes(b"abc")
        delivery = directory / "delivery.glb"; delivery.write_bytes(b"xyz")
        with patch.object(model3d, "find_model3d_serving", return_value=(source_glb, "exact")), patch.object(glb_delivery, "delivery_path", side_effect=lambda p, **kwargs: p):
            old = model3d.versioned_model_urls("demo", base)
            with patch.object(glb_delivery, "delivery_path", return_value=delivery):
                new = model3d.versioned_model_urls("demo", base)
                assert old["url"] != new["url"]
                r = characters._model_asset_response("demo", request("v=ba7816bf8f01cfea"))
                assert r.headers["cache-control"] == "no-cache"
                assert run_async(body(r)) == b"xyz"
                r = characters._model_asset_response("demo", request(), download=True)
                assert r.headers["content-disposition"] == 'attachment; filename="demo.glb"'
                assert run_async(body(r)) == b"abc"
            # Open before publication; fstat/hash/body must all refer to abc.
            opened = threading.Event(); release = threading.Event(); result = {}
            publication = keyed_lock("model3d_publication", str(directory))
            def publisher():
                with publication:
                    opened.set()
                    assert release.wait(5)
                    staged = directory / "model.tmp"; staged.write_bytes(b"xyz")
                    atomic_replace(staged, source_glb)
            thread = threading.Thread(target=publisher); thread.start()
            assert opened.wait(5)
            def reader():
                result["response"] = characters._model_asset_response("demo", request())
            reader_thread = threading.Thread(target=reader); reader_thread.start()
            assert reader_thread.is_alive()
            release.set(); thread.join(5); reader_thread.join(5)
            assert not thread.is_alive() and not reader_thread.is_alive()
            # Publisher finished first, so this snapshot is xyz.
            response = result["response"]
            staged = directory / "model.tmp"; staged.write_bytes(b"abc")
            atomic_replace(staged, source_glb)
            assert run_async(body(response)) == b"xyz"
    from app.core import http_files, config
    from app.blender import runner as blender_runner
    import hashlib
    cache = glb_delivery._cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / (hashlib.sha256(source_glb.read_bytes()).hexdigest() + ".glb")
    cached.write_bytes(b"real delivery")
    original_config_get = config.get
    original_hash = http_files._hash_fd
    hashes, delivery_hashes = [], []
    original_digest = hashlib.file_digest
    def assert_unlocked():
        acquired = threading.Event()
        def contender():
            with keyed_lock("model3d_publication", str(directory)):
                acquired.set()
        thread = threading.Thread(target=contender, daemon=True)
        thread.start()
        assert acquired.wait(2), "content hash ran under publication lock"
        thread.join(2)
    def checked_hash(stream, stat):
        assert_unlocked()
        hashes.append(stat.st_ino)
        return original_hash(stream, stat)
    def checked_digest(stream, algorithm):
        assert_unlocked()
        delivery_hashes.append(os.fstat(stream.fileno()).st_ino)
        return original_digest(stream, algorithm)
    def config_get(key, *args, **kwargs):
        if key == "image_generation.blender_meshopt_delivery":
            return True
        return original_config_get(key, *args, **kwargs)
    with (
        patch.object(model3d, "find_model3d_serving", return_value=(source_glb, "exact")),
        patch.object(model3d, "current_outfit_state", return_value=(None, None, "demo")),
        patch.object(config, "get", side_effect=config_get),
        patch.object(blender_runner, "status", return_value={"usable": True}),
        patch.object(http_files, "_hash_fd", side_effect=checked_hash),
        patch.object(hashlib, "file_digest", side_effect=checked_digest),
    ):
        http_files._versions.clear()
        first = characters.get_character_model_meta("demo")
        count = len(hashes)
        delivery_count = len(delivery_hashes)
        second = characters.get_character_model_meta("demo")
        assert first["url"] == second["url"]
        assert count > 0 and len(hashes) == count, "unchanged delivery bytes were reread"
        assert delivery_count > 0 and len(delivery_hashes) == delivery_count, "unchanged source was reread for delivery"
        http_files._versions.clear()
        model3d.get_model3d_info("demo")
        info_count = len(hashes)
        model3d.get_model3d_info("demo")
        assert len(hashes) == info_count, "unchanged /model3d/info bytes were reread"
        http_files._versions.clear()
        model3d.versioned_model_urls("demo", base)
        http_files._versions.clear()
        response = characters._model_asset_response("demo", request())
        assert run_async(body(response)) == b"real delivery"
    print("OK: model/low/texture versions, real delivery reuse, unlocked hashing, download and publication lock")
