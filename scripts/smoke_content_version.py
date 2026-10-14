#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_content_version.py

SHA256(abc) starts ba7816bf8f01cfea; SHA256(xyz) starts 3608bca1e44ea6c4.
Equal size and restored mtime must still change the version via ctime.
Only an exact v gets immutable; missing/stale v revalidates. Exact, list,
and wildcard ETags give 304. Replacement after open must return abc, not xyz.
Disconnect before body iteration must close the opened descriptor too.
The smoke-only _before_stream hook replaces the pathname before iteration.
"""
import os
import asyncio
from unittest.mock import patch
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from fastapi import FastAPI, Request
from starlette.testclient import TestClient


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
    paths.init(root)
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
    from app.core.http_files import content_version, snapshot_response, atomic_replace
    p = root / "a.bin"
    p.write_bytes(b"abc")
    assert content_version(p) == "ba7816bf8f01cfea"
    st = p.stat()
    time.sleep(0.02)  # Cross a filesystem clock tick before the in-place edit.
    p.write_bytes(b"xyz")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert content_version(p) == "3608bca1e44ea6c4"
    p.write_bytes(b"abc")
    app = FastAPI()
    def replace(target):
        staged = target.with_suffix(".tmp")
        staged.write_bytes(b"xyz")
        atomic_replace(staged, target)
    @app.get("/file")
    def file(request: Request):
        return snapshot_response(p, request, media_type="application/octet-stream",
            filename="demo ü.bin", version=request.query_params.get("v"),
            _before_stream=replace if "replace" in request.query_params else None)
    with TestClient(app, backend_options={"loop_factory": smoke_loop}) as client:
        for suffix, expected in [("", "no-cache"), ("?v=old", "no-cache"),
                ("?v=ba7816bf8f01cfea", "public, max-age=31536000, immutable")]:
            r = client.get("/file" + suffix)
            assert r.content == b"abc"
            assert r.headers["cache-control"] == expected
            assert r.headers["content-length"] == "3"
            assert "filename*=utf-8''" in r.headers["content-disposition"]
        for tag in ['"ba7816bf8f01cfea"', '"other", "ba7816bf8f01cfea"', '*']:
            r = client.get("/file", headers={"If-None-Match": tag})
            assert r.status_code == 304 and not r.content
        assert client.get("/file?replace=1").content == b"abc"
        assert p.read_bytes() == b"xyz"
        p.unlink()
        assert client.get("/file").status_code == 404
    p.write_bytes(b"abc")
    opened = []
    real_open = open
    def capture(*args, **kwargs):
        f = real_open(*args, **kwargs)
        opened.append(f)
        return f
    async def disconnect():
        request = Request({"type": "http", "headers": []})
        with patch("app.core.http_files.open", side_effect=capture):
            response = snapshot_response(p, request, media_type="application/octet-stream")
        async def send(message):
            raise OSError("disconnected before response body")
        async def receive():
            return {"type": "http.disconnect"}
        from starlette.requests import ClientDisconnect
        try:
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        except ClientDisconnect:
            pass
        assert opened[-1].closed, "disconnect before iteration leaked the descriptor"
    run_async(disconnect())
    print("OK: content versions, cache headers, 304, descriptor replacement")
