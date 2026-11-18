#!/usr/bin/env python3
"""Smoke: the Wardrobe mesh-view cache is swept (review 06B#5, ``garment_mesh_view.sweep_cache``).

Usage:  ./.venv/bin/python scripts/smoke_mesh_view_sweep.py

No world DB: ``paths.init(<tmp>)``; cache entries are written by hand in ``<tmp>/.cache/garment_mesh_view/``.

Setup: a source file ``src.glb``. Entries (each ``<key>.json`` + ``<key>.ghost.glb``):
  c1, c2, c3 — ``sources`` = {src.glb: its current version}; JSON mtimes now-30, now-20, now-10 s;
  stale     — ``sources`` = {src.glb: "old"} (the file changed since);
  gone      — ``sources`` = {<tmp>/missing.glb: "v"} (the file is gone);
  legacy    — no ``sources`` (written before the sweep existed);
  busy      — stale like ``stale``, but its ``keyed_lock("garment_mesh_view", "busy")`` is held by another thread;
  orphan.ghost.glb (no JSON) aged 2 h, young.ghost.glb (no JSON) aged 0 s.
Expected with keep=2, by hand: stale, gone, legacy removed (3) + c1, the least recently used of the 3 current
ones, over the cap (1) -> return 4; c2, c3, busy kept; orphan's GLB removed, young's kept.
[2] c1 is written again with an mtime 100 s old, then read through ``_cached("c1")``, which touches it: it is now
the most recently used. A sweep with keep=1, lock free: busy (stale) goes, c1 stays, c2 and c3 go -> returns 3,
only c1.json left.
On 69aeeba75 there is no ``sweep_cache`` (AttributeError).
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="smoke_mvs_")
from app.core import paths  # noqa: E402
paths.init(TMP)
from app.core import garment_mesh_view as mv  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402

src = Path(TMP) / "src.glb"
src.write_bytes(b"glb")
cur = mv._version(src)
folder = mv._cache_dir()
folder.mkdir(parents=True)
now = time.time()


def entry(key, sources, age=0.0):
    files = mv._cache_files(key)
    files["ghost"].write_bytes(b"g")
    body = {"key": key, "inside_faces": 0}
    if sources is not None:
        body["sources"] = sources
    files["json"].write_text(json.dumps(body))
    os.utime(files["json"], (now - age, now - age))


entry("c1", {str(src): cur}, 30)
entry("c2", {str(src): cur}, 20)
entry("c3", {str(src): cur}, 10)
entry("stale", {str(src): "old"})
entry("gone", {str(Path(TMP) / "missing.glb"): "v"})
entry("legacy", None)
entry("busy", {str(src): "old"})
(folder / "orphan.ghost.glb").write_bytes(b"g")
os.utime(folder / "orphan.ghost.glb", (now - 7200, now - 7200))
(folder / "young.ghost.glb").write_bytes(b"g")

held, release = threading.Event(), threading.Event()


def holder():
    with keyed_lock("garment_mesh_view", "busy"):
        held.set()
        release.wait(10)


t = threading.Thread(target=holder)
t.start()
held.wait(10)
try:
    n1 = mv.sweep_cache(keep=2, now=now)
finally:
    release.set()
    t.join()
left = sorted(p.name for p in folder.iterdir())
want = sorted(["busy.ghost.glb", "busy.json", "c2.ghost.glb", "c2.json", "c3.ghost.glb", "c3.json",
               "young.ghost.glb"])
fails = []
if n1 != 4 or left != want:
    fails.append(f"[1] removed {n1}, left {left}")
entry("c1", {str(src): cur}, 100)
mv._cached("c1")  # a hit touches it -> most recently used
n2 = mv.sweep_cache(keep=1, now=time.time())
left2 = sorted(p.name for p in folder.iterdir() if p.name.endswith(".json"))
if n2 != 3 or left2 != ["c1.json"]:  # busy (stale, now unlocked), c2, c3 go
    fails.append(f"[2] removed {n2}, left {left2}")
print("FAILED", fails if fails else "") if fails else print("all passed")
sys.exit(1 if fails else 0)
