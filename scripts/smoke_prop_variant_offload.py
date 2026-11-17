#!/usr/bin/env python3
"""Smoke: the prop-variant upload and model-select routes run the Blender landing chain OFF the event
loop (review 02#2, ``app/routes/prop_variants.py``).

Usage:
    ./.venv/bin/python scripts/smoke_prop_variant_offload.py

No server, no Blender, no real world: storage and instance are temp folders, ``paths.init`` runs before any
app import. The route coroutines are awaited directly on an asyncio loop. The store functions they call
(``props.save_uploaded_glb`` / ``props.select_model``, whose ``_store_bbox`` runs Blender bake, area split,
re-encode and measurement) are replaced by stand-ins that note the calling thread and then block for
HOLD = 0.4 s with ``time.sleep`` — what a Blender subprocess does to its caller. ``_variant`` (the
sidecar check) is stubbed to accept the index. A heartbeat task on the same loop ticks every 0.02 s.

Expected, derived by hand:
[1] upload (force="1", so an invalid stub GLB still lands): ``save_uploaded_glb`` runs in a thread that is
    NOT the loop's thread, and the heartbeat ticks during it — 0.4 / 0.02 = 20 ticks ideally; at least 5
    are required (scheduling slack). On the old route the call ran on the loop thread: 0 ticks, same thread.
    The answer is ``{"status": "ok", …}``.
[2] select (body ``{"file": "a.glb"}``): same for ``select_model``; the answer is
    ``{"status": "success", "active": "a.glb", "tier": <default tier>}``.
[3] A stand-in that returns False still maps to the 404s ("Prop not found" / "Model not found").
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="smoke-prop-offload-"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
(TMP / "world").mkdir()
(TMP / "instance").mkdir()

from app.core import paths  # noqa: E402

paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))

from fastapi import HTTPException, UploadFile  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app.core import props  # noqa: E402
from app.routes import prop_variants  # noqa: E402

HOLD = 0.4
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def json_request(body: dict) -> Request:
    raw = json.dumps(body).encode()
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": raw, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"",
             "headers": [(b"content-type", b"application/json"),
                         (b"content-length", str(len(raw)).encode())]}
    return Request(scope, receive)


async def measured(coro_factory, seen):
    """Run the route with a heartbeat beside it; return (result or exception, ticks during the hold)."""
    ticks = []
    stop = asyncio.Event()

    async def heartbeat():
        while not stop.is_set():
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    hb = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)
    try:
        out = await coro_factory()
    except HTTPException as e:
        out = e
    stop.set()
    await hb
    start, end = seen.get("start", 0.0), seen.get("end", 0.0)
    return out, sum(1 for t in ticks if start < t < end)


def stand_in(seen, answer):
    def fn(*_a, **_kw):
        seen["thread"] = threading.get_ident()
        seen["start"] = time.monotonic()
        time.sleep(HOLD)
        seen["end"] = time.monotonic()
        return answer
    return fn


async def main_async():
    loop_thread = threading.get_ident()
    prop_variants._variant = lambda prop_id, index: index

    # [1]
    seen = {}
    props.save_uploaded_glb = stand_in(seen, True)
    out, ticks = await measured(lambda: prop_variants.prop_variant_upload(
        "demo_prop", 0, file=UploadFile(file=io.BytesIO(b"not-a-glb"), filename="m.glb"),
        tier="", force="1"), seen)
    check(isinstance(out, dict) and out.get("status") == "ok", f"[1] upload answers ok ({out!r})")
    check(seen.get("thread") not in (None, loop_thread), "[1] save_uploaded_glb ran off the loop thread")
    check(ticks >= 5, f"[1] loop kept ticking during the landing chain (ticks {ticks}, need >= 5)")

    # [2]
    seen = {}
    props.select_model = stand_in(seen, True)
    out, ticks = await measured(lambda: prop_variants.prop_variant_model_select(
        "demo_prop", 0, json_request({"file": "a.glb"})), seen)
    check(isinstance(out, dict) and out.get("status") == "success" and out.get("active") == "a.glb"
          and out.get("tier") == props.DEFAULT_TIER, f"[2] select answers success ({out!r})")
    check(seen.get("thread") not in (None, loop_thread), "[2] select_model ran off the loop thread")
    check(ticks >= 5, f"[2] loop kept ticking during the landing chain (ticks {ticks}, need >= 5)")

    # [3]
    props.save_uploaded_glb = stand_in({}, False)
    props.select_model = stand_in({}, False)
    out, _ = await measured(lambda: prop_variants.prop_variant_upload(
        "demo_prop", 0, file=UploadFile(file=io.BytesIO(b"x"), filename="m.glb"), tier="", force="1"), {})
    check(isinstance(out, HTTPException) and out.status_code == 404 and out.detail == "Prop not found",
          f"[3] upload False -> 404 Prop not found ({out!r})")
    out, _ = await measured(lambda: prop_variants.prop_variant_model_select(
        "demo_prop", 0, json_request({"file": "a.glb"})), {})
    check(isinstance(out, HTTPException) and out.status_code == 404 and out.detail == "Model not found",
          f"[3] select False -> 404 Model not found ({out!r})")


def main() -> int:
    try:
        asyncio.run(main_async())
    finally:
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
