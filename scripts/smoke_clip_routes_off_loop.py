#!/usr/bin/env python3
"""Smoke: the three async clip-library edit routes do their blocking work in
the threadpool, never on the event loop (review 04#2, 02#3a).

``PATCH /assets/animation-clips/{library}/{rel}``, ``POST …/orient`` and
``PUT /assets/animation-clips/transitions`` call library writers that wait
for ``keyed_lock("clip_library", "write")`` — the lock an FBX/CMU import
holds for its whole Blender run — and orient may run Blender itself. Run on
the loop, that wait froze every request of the server.

Usage: ./.venv/bin/python scripts/smoke_clip_routes_off_loop.py

Setup (all temporary): a free library with ``walk.fbx`` + ``walk.json``,
a world for the transition table, the transition seed patched to a temp file.
A helper thread holds the clip-library lock for HOLD = 1.0 s. Meanwhile each
route coroutine runs beside a ticker that sleeps 0.05 s per tick.

Expected, by hand:
- off the loop: the ticker keeps running while the route waits for the lock
  — about HOLD / 0.05 = 20 ticks; at least 5 are demanded before the route
  returns.
- on the loop (the old handlers): the route blocks the loop thread until the
  lock is released, so at most the one tick already scheduled lands before
  it returns — fewer than 5 → FAIL.
- the route still answers what it did: PATCH {"loop": true} → the clip view
  with loop true; orient {"shift_cm": [10, 0]} (renderer-only, no Blender) →
  the clip; PUT {"transitions": []} → {"transitions": []}.
- every route returns no earlier than 0.9 · HOLD after the lock was taken
  (it really waited for the writer).
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="clip-routes-off-loop-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "free")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(TMP / "licensed")
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(TMP / "inbox")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

from app.core import animation_clips as clips  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.routes import assets  # noqa: E402

HOLD = 1.0
FAIL = []


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def hold_lock(taken: threading.Event):
    with keyed_lock("clip_library", "write"):
        taken.set()
        time.sleep(HOLD)


async def run_beside_ticker(make_coro):
    ticks = []
    done = asyncio.Event()

    async def ticker():
        while not done.is_set():
            await asyncio.sleep(0.05)
            ticks.append(time.monotonic())

    taken = threading.Event()
    holder = threading.Thread(target=hold_lock, args=(taken,))
    holder.start()
    taken.wait(5)
    started = time.monotonic()
    tick_task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    result = await make_coro()
    ended = time.monotonic()
    done.set()
    await tick_task
    holder.join()
    during = [t for t in ticks if t < ended]
    return result, len(during), ended - started


def main():
    free = TMP / "free"
    free.mkdir(parents=True)
    (free / "walk.fbx").write_bytes(b"fixture")
    (free / "walk.json").write_text(json.dumps({"kind": "walk", "fps": 30}), encoding="utf-8")
    clips.reload_clip_caches()

    with patch.object(clips, "clip_transitions_path", return_value=TMP / "transitions.json"):
        cases = [
            ("PATCH loop", lambda: assets.patch_animation_clip(
                "free", "walk.fbx", FakeRequest({"loop": True}), {})),
            ("POST orient shift_cm", lambda: assets.post_animation_clip_orient(
                "free", "walk.fbx", FakeRequest({"shift_cm": [10, 0]}), {})),
            ("PUT transitions", lambda: assets.put_clip_transitions(
                FakeRequest({"transitions": []}), {})),
        ]
        results = {}
        for label, make in cases:
            result, ticks, waited = asyncio.run(run_beside_ticker(make))
            results[label] = result
            check(f"{label}: the loop kept ticking while the route waited ({ticks} ticks)",
                  ticks >= 5, f"{ticks} ticks")
            check(f"{label}: the route waited for the writer lock ({waited:.2f} s)",
                  waited >= 0.9 * HOLD, f"{waited:.2f} s")

    patched = results["PATCH loop"]["clips"]
    check("PATCH answered the clip with loop true",
          len(patched) == 1 and patched[0].get("loop") is True, str(patched))
    check("the loop flag is in the sidecar",
          json.loads((free / "walk.json").read_text()).get("loop") is True)
    oriented = results["POST orient shift_cm"]
    check("orient answered the clip and a run time",
          len(oriented["clips"]) == 1 and "seconds" in oriented, str(oriented))
    check("PUT answered the stored (empty) list",
          results["PUT transitions"] == {"transitions": []}, str(results["PUT transitions"]))

    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
