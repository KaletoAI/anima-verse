#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_clip_cache_headers.py

Free walk and licensed wave contain abc (ba7816bf8f01cfea); licensed walk
contains xyz (3608bca1e44ea6c4) and shadows free walk. Library prefixes must
survive versioning. Matching v is immutable, absent/stale v revalidates;
atomic replacement changes the next listing and stale URLs serve new bytes.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
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
    free, licensed = root / "free", root / "licensed"
    free.mkdir(); licensed.mkdir()
    os.environ["ANIMATION_CLIPS_DIR"] = str(free)
    os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(licensed)
    (free / "walk.fbx").write_bytes(b"abc")
    (licensed / "wave.fbx").write_bytes(b"abc")
    from app.routes.assets import get_animation_clip, list_animation_clips
    def request(version=""):
        return Request({"type": "http", "headers": [], "query_string": version.encode()})
    def listing():
        return {c["kind"]: c for c in list_animation_clips()["clips"]}
    clips = listing()
    assert clips["walk"]["url"] == "/assets/animation-clips/walk.fbx?v=ba7816bf8f01cfea", clips["walk"]["url"]
    assert clips["wave"]["url"] == "/assets/animation-clips/licensed/wave.fbx?v=ba7816bf8f01cfea"
    for rel in ["walk.fbx", "licensed/wave.fbx"]:
        r = get_animation_clip(rel, request("v=ba7816bf8f01cfea"))
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert run_async(body(r)) == b"abc"
        r = get_animation_clip(rel, request())
        assert r.headers["cache-control"] == "no-cache"
        run_async(body(r))
    from app.core.http_files import atomic_replace
    staged = free / "walk.tmp"
    staged.write_bytes(b"xyz"); atomic_replace(staged, free / "walk.fbx")
    r = get_animation_clip("walk.fbx", request("v=ba7816bf8f01cfea"))
    assert r.headers["cache-control"] == "no-cache"
    assert run_async(body(r)) == b"xyz"
    assert listing()["walk"]["url"].endswith("?v=3608bca1e44ea6c4")
    (licensed / "walk.fbx").write_bytes(b"xyz")
    assert listing()["walk"]["url"] == "/assets/animation-clips/licensed/walk.fbx?v=3608bca1e44ea6c4"
    print("OK: free/licensed URLs, clip headers and replacement")

from unittest.mock import patch
from app.core import fbx_import
import threading
with tempfile.TemporaryDirectory() as tmp:
    destination = Path(tmp)
    barrier = threading.Barrier(2)
    published = threading.Event()
    stages, errors = [], []
    def copying(source, stage):
        with open(stage, "wb") as writer:
            writer.write(b"abc")
            writer.flush()
            stages.append(Path(stage))
            barrier.wait(timeout=5)
            if Path(source).read_bytes() == b"second":
                assert published.wait(5)
                assert destination.joinpath("walk.fbx").stat().st_ino != os.fstat(writer.fileno()).st_ino, "published inode still held by another writer"
                writer.write(b"xyz")
        return stage
    def conversion(script, *, out_dir, **kwargs):
        source = out_dir / "walk.fbx"
        source.write_bytes(threading.current_thread().name.encode())
        return {"ok": True, "outputs": {"clip": str(source)}}
    def write():
        try:
            fbx_import._run_source({}, {}, destination, 5)
        except BaseException as exc:
            errors.append(exc)
        finally:
            if threading.current_thread().name == "first": published.set()
    with patch.object(fbx_import.runner, "run", side_effect=conversion), patch("shutil.copy2", side_effect=copying):
        threads = [threading.Thread(target=write, name=name) for name in ("first", "second")]
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
    assert not errors, errors
    assert len(set(stages)) == 2, stages
    assert not any(stage.exists() for stage in stages)
print("OK: concurrent clip staging uses distinct closed inodes")

# A failed copy leaves the published generation intact and cleans its stage.
with tempfile.TemporaryDirectory() as tmp:
    destination = Path(tmp)
    live = destination / "walk.fbx"
    live.write_bytes(b"old")
    def failed_copy(source, stage):
        Path(stage).write_bytes(b"partial")
        raise OSError("copy interrupted")
    with patch.object(fbx_import.runner, "run", side_effect=conversion), patch("shutil.copy2", side_effect=failed_copy):
        try:
            fbx_import._run_source({}, {}, destination, 5)
        except OSError:
            pass
        else:
            raise AssertionError("copy failure was swallowed")
    assert live.read_bytes() == b"old"
    assert list(destination.iterdir()) == [live]
print("OK: failed clip publication cleans staging and preserves live bytes")
