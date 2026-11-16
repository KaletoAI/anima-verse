"""Smoke: the generic reference-view post-process (Ruling A146, ``app/core/view_postprocess.py``).

Usage:
    ./.venv/bin/python scripts/smoke_view_postprocess.py

No server, no world DB: a temp storage dir, a stand-in operation registered as a contributor of the
capability, PNG files written by hand.

Expected values, derived by hand:

* The view: 40 x 20 RGBA, alpha 255 in columns 4..33 (else 0; mirrored 6..35, so a processed view is not its own mirror), colour (180, 140, 120) everywhere except a
  4 x 4 dark disc stand-in at rows 8..11, columns 10..13 = (90, 50, 50).
* The stand-in operation turns every opaque pixel with R < 100 into (180, 140, 120): after ``process`` the
  view has 0 pixels with R < 100 and its alpha is unchanged; ``found`` = 16 (the 4 x 4 pixels it changed).
* ``restore`` gives the input bytes back byte for byte (the kept original is the input file).
* Process, then mirror the file (``view_facing.toggle_mirror``), then restore: the file is the MIRROR of the
  original — the dark block now at columns 40-1-13 .. 40-1-10 = 26..29, rows 8..11 — and turning the mirror
  back gives the original bytes again (the mirror record followed the restore).
* An operation that changes the matte is refused: ``ValueError``, file unchanged, no record.
* Choices: world default ["stand_in"], character {"stand_in": False} -> on = []; character {} -> ["stand_in"].
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="smoke_vpp_"))
os.environ.setdefault("STORAGE_DIR", str(TMP))
from app.core import paths  # noqa: E402
paths.init(str(TMP))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import hooks, view_facing, view_postprocess as vp  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def make_view(path: Path) -> bytes:
    a = np.zeros((20, 40, 4), np.uint8)
    a[..., :3] = (180, 140, 120)
    a[:, 4:34, 3] = 255  # not symmetric: a mirror changes the bytes
    a[8:12, 10:14, :3] = (90, 50, 50)
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, format="PNG")
    path.write_bytes(buf.getvalue())
    path.with_suffix(".json").write_text("{}", encoding="utf-8")
    return buf.getvalue()


def stand_in(image, *, view, params):
    a = np.asarray(image).copy()
    hit = (a[..., 0] < 100) & (a[..., 3] > 0)
    a[hit, :3] = (180, 140, 120)
    return {"image": Image.fromarray(a, "RGBA") if hit.any() else None, "found": int(hit.sum()),
            "regions": [], "seconds": 0.0}


def bad(image, *, view, params):
    a = np.asarray(image).copy()
    a[0, 0, 3] = 255 - a[0, 0, 3]
    return {"image": Image.fromarray(a, "RGBA"), "found": 1}


hooks.register_provider(vp.CAPABILITY, lambda: {"id": "stand_in", "label": "x", "views": ["front"],
                                                "params": {}, "apply": stand_in}, owner="smoke_a", multiple=True)
hooks.register_provider(vp.CAPABILITY, lambda: {"id": "bad", "label": "y", "views": ["front"],
                                                "params": {}, "apply": bad}, owner="smoke_b", multiple=True)

d = TMP / "model_refs"
d.mkdir()
view = d / "tpose_base0.png"
orig = make_view(view)


def pixels(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGBA"))


rec = vp.process(view, "front", "stand_in")
px = pixels(view)
check(int((px[..., 0] < 100).sum()) == 0, "processed: no dark pixel left")
check(rec["found"] == 16, f"processed: found 16 (got {rec['found']})")
check(np.array_equal(px[..., 3], np.asarray(Image.open(io.BytesIO(orig)))[..., 3]), "processed: alpha unchanged")
check(vp.original_path(view).read_bytes() == orig, "processed: original kept byte for byte")
check(vp.tile_state(view)["restorable"] is True, "processed: restorable")

check(vp.restore(view) is True and view.read_bytes() == orig, "restore: input bytes back")
check(not vp.original_path(view).exists() and vp.record_of(view) is None, "restore: kept file and record gone")

vp.process(view, "front", "stand_in")
view_facing.toggle_mirror(view)
vp.restore(view)
px = pixels(view)
dark_cols = sorted(set(np.where(px[..., 0] < 100)[1].tolist()))
dark_rows = sorted(set(np.where(px[..., 0] < 100)[0].tolist()))
check(dark_cols == [26, 27, 28, 29] and dark_rows == [8, 9, 10, 11], f"mirrored restore: block at 26..29 (got {dark_cols})")
view_facing.toggle_mirror(view)
check(view.read_bytes() == orig, "mirror turned back after restore: original bytes")

before = view.read_bytes()
try:
    vp.process(view, "front", "bad")
    check(False, "matte change refused")
except ValueError:
    check(view.read_bytes() == before and vp.record_of(view) is None, "matte change refused, file unchanged")

vp.world_default_ids = lambda: ["stand_in"]
avail = vp.operations()
check(vp.enabled_ids({"reference_postprocess": {"stand_in": False}}, avail) == [], "own off beats world default")
check(vp.enabled_ids({}, avail) == ["stand_in"], "world default applies without own choice")

print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
