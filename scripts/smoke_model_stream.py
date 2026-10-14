#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_model_stream.py

Hand-derived expectations: demo.fbx contains 2 * 1,048,576 OLD bytes plus
four tail bytes, so its 2,097,156-byte body spans several chunks. demo.png
contains exactly b"texture bytes". All four asset routes and the explicit
/model3d/file?download=1 call must return 200 and those fixture bytes even
when Path.read_bytes is forbidden for either asset. Sending the returned
ETag unchanged or prefixed with W/ must return 304 with zero body bytes.
After consuming the first (nonempty, incomplete) chunk, replacing demo.fbx
with equally sized NEW bytes must still yield the entire OLD body. While
that stream remains suspended, another thread must acquire the publication
lock within 0.050 seconds. These catch eager read_bytes, strict ETag matching,
path reopening mid-stream, and holding the publication lock during delivery.
Version URL construction and replacement before iteration are covered by
smoke_model_version.py instead.
"""
import asyncio
import os
import selectors
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from starlette.requests import Request


def smoke_loop():
    """Observe worker completions even when a sandbox blocks selector wakeups."""
    class SmokeSelector(selectors.DefaultSelector):
        def select(self, timeout=None):
            return super().select(.05 if timeout is None else min(timeout, .05))
    return asyncio.SelectorEventLoop(SmokeSelector())


async def bounded(awaitable, operation):
    try:
        return await asyncio.wait_for(awaitable, timeout=5)
    except asyncio.TimeoutError as exc:
        raise AssertionError(f"{operation} timed out after 5 seconds") from exc


async def collect(iterator):
    chunks = []
    while True:
        try:
            chunks.append(await bounded(anext(iterator), "response body chunk"))
        except StopAsyncIteration:
            return chunks


async def body(response):
    if hasattr(response, "body_iterator"):
        return b"".join(await bounded(collect(response.body_iterator), "response body collection"))
    return response.body


def request(url, etag=None):
    path, _, query = url.partition("?")
    headers = [] if etag is None else [(b"if-none-match", etag.encode())]
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": headers, "query_string": query.encode()})


async def check_routes(characters, model3d, directory, source, texture):
    old = b"OLD!" * 524288 + b"tail"
    new = b"NEW!" * 524288 + b"tail"
    texture_bytes = b"texture bytes"
    source.write_bytes(old)
    texture.write_bytes(texture_bytes)
    original_read_bytes = Path.read_bytes

    def forbid_asset_read_bytes(path):
        if path in (source, texture):
            raise AssertionError("model assets must stream without Path.read_bytes")
        return original_read_bytes(path)

    # Isolate outfit selection as in smoke_model_version; keep tier selection,
    # texture lookup, route functions and snapshot delivery real.
    with (patch.object(model3d, "find_model3d_serving", return_value=(source, "exact")),
          patch.object(Path, "read_bytes", forbid_asset_read_bytes)):
        cases = [
            ("/characters/demo/model", characters.get_character_model_file, {}, old),
            ("/characters/demo/model/texture", characters.get_character_model_texture_file,
             {}, texture_bytes),
            ("/characters/demo/model3d/file", characters.get_character_model3d_file, {}, old),
            ("/characters/demo/model3d/texture", characters.get_character_model3d_texture,
             {}, texture_bytes),
            ("/characters/demo/model3d/file?download=1", characters.get_character_model3d_file,
             {"download": True}, old),
        ]
        for url, route, kwargs, expected in cases:
            response = route("demo", request(url), **kwargs)
            assert response.status_code == 200, url
            assert await body(response) == expected, url
            etag = response.headers["etag"]
            assert etag.startswith("\"") and etag.endswith("\""), url
            for conditional in (etag, "W/" + etag):
                response = route("demo", request(url, conditional), **kwargs)
                assert response.status_code == 304, (url, conditional)
                assert await body(response) == b"", (url, conditional)

        from app.core.keyed_lock import keyed_lock
        response = characters.get_character_model_file("demo", request("/characters/demo/model"))
        assert response.status_code == 200
        iterator = response.body_iterator
        ready = threading.Event()
        attempt = threading.Event()
        acquired = threading.Event()

        def contender():
            ready.set()
            if attempt.wait(5):
                with keyed_lock("model3d_publication", str(directory)):
                    acquired.set()

        thread = threading.Thread(target=contender, daemon=True)
        try:
            first = await bounded(anext(iterator), "first response body chunk")
            chunks = [first]
            assert 0 < len(first) < len(old), "stream must have pending bytes"
            assert first == old[:len(first)]
            thread.start()
            assert ready.wait(5), "lock contender did not start"
            attempt.set()
            assert acquired.wait(.050), "publication lock unavailable within 50 ms during stream"
            staged = directory / "replacement.tmp"
            staged.write_bytes(new)
            os.replace(staged, source)
            chunks.extend(await bounded(collect(iterator), "remaining response body collection"))
            assert len(chunks) > 1, "replacement must happen between chunks"
            assert b"".join(chunks) == old, "stream mixed or reopened model generations"
            with source.open("rb") as current:
                assert current.read() == new, "replacement fixture was not published"
        finally:
            try:
                await bounded(iterator.aclose(), "response body iterator close")
            finally:
                attempt.set()
                if thread.ident is not None:
                    thread.join(5)
                    assert not thread.is_alive(), "lock contender did not finish within 5 seconds"


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
    from app.core import db, model3d
    from app.routes import characters
    db.init_schema()
    from app.models.character import get_character_dir
    get_character_dir("demo").mkdir(parents=True, exist_ok=True)
    directory = model3d.get_model3d_dir("demo")
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "demo.fbx"
    texture = directory / "demo.png"
    with asyncio.Runner(loop_factory=smoke_loop) as runner:
        runner.run(check_routes(characters, model3d, directory, source, texture))
    print("OK: model/texture/download streaming without read_bytes, strong/weak ETag 304, "
          "replacement after first chunk, publication lock free within 50 ms")
