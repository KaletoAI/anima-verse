#!/usr/bin/env python3
"""The BiRefNet mask cache of the garment chain (app/core/garment_images.py ``_mask_image`` /
``mask_cache_dir`` / ``MASK_CACHE_MAX``): a fit must not re-matte an image the ghost gate already matted.

Usage:
    ./.venv/bin/python scripts/smoke_mask_cache.py

No world, no hub, no server, no model: a throwaway storage root (``paths.init`` before any app import that could
reach a world DB) and ``app.models.character.run_rembg`` replaced by a deterministic stub that counts its calls.

THE STUB, hand-derived: ``run_rembg(data, model, only_mask=True)`` decodes ``data``, takes the red channel and
returns the PNG of the L image ``255 where R > 100 else 0`` at the INPUT's size — what BiRefNet returns (a mask at
the source size; ``_mask_image`` resizes it). It sleeps 0.2 s per call so two threads asking at once overlap.

THE KEY: ``sha256(data)`` + ``MESH_INPUT_REMBG_MODEL`` + ``w×h`` of the requested size. So:

[M1] Image A (64×48: left half red 200, right half red 0) written to a.png; ``_mask(a.png, (64, 48))`` twice
     -> 1 stub call (the second is a hit), both arrays equal, and equal to the hand mask: True on columns 0..31,
     False on 32..63 (threshold ``MASK_THRESHOLD`` 128 of 255/0 — no resize at the same size). The hit returns an
     L image of size (64, 48). One cache file.
     FAILS on the old code (commit 20ebbd27, no cache): 2 stub calls.
[M2] The same bytes at (32, 24) -> a new key -> 2 calls in all; the mask is the 2:1 BILINEAR downscale of the
     stub mask (left 16 columns 255, right 16 0; the edge columns 15/16 straddle the step: column 15's footprint
     covers source columns ~29.5..32.5 -> mixed). Checked against the same resize done here, not a guess.
[M3] a.png overwritten with image B (red 200 on the TOP half, 0 below) — same path, other bytes -> a new key ->
     3 calls; the mask (rows 0..23 True) differs from A's.
[M4] B's cache file truncated to 10 bytes (a PNG needs 8 signature + 25 IHDR bytes at least: unreadable) ->
     ``_mask`` re-mattes (4 calls), no exception, equal to B's mask; the file is whole again (readable, L, 64×48).
[M5] Image C, new bytes; two threads call ``_mask`` at once -> 1 call (5 in all): the second waits on the
     ``keyed_lock("mask_cache", key)`` the first took before the stub, then reads the file. Both arrays equal.
[M6] Cache emptied, ``MASK_CACHE_MAX`` patched to 2; three new keys (D, E, F at 64×48, written 50 ms apart)
     -> 2 files left, D's (the oldest by mtime) gone, E's and F's there.
[M7] No storage root (``paths._storage_dir`` None for the call): ``_mask_image`` still returns the mask (a stub
     call, nothing written) — a caller outside a world keeps working, uncached.
"""
import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TMP = Path(tempfile.mkdtemp(prefix="smoke-mask-cache-"))
os.environ["STORAGE_DIR"] = str(TMP / "storage")
from app.core import paths  # noqa: E402

paths.init(str(TMP / "storage"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import app.models.character as character  # noqa: E402
from app.core import garment_images as gi  # noqa: E402

FAILS = []
CALLS = []
_CALLS_LOCK = threading.Lock()


def check(tag, cond, detail=""):
    print(f"[{tag}] {'OK  ' if cond else 'FAIL'} {detail}")
    if not cond:
        FAILS.append(tag)


def stub_rembg(data, model="u2net", **kwargs):
    with _CALLS_LOCK:
        CALLS.append((model, kwargs.get("only_mask")))
    time.sleep(0.2)
    with Image.open(io.BytesIO(data)) as im:
        red = np.asarray(im.convert("RGB"))[:, :, 0]
    out = io.BytesIO()
    Image.fromarray(np.where(red > 100, 255, 0).astype(np.uint8), "L").save(out, "PNG")
    return out.getvalue()


character.run_rembg = stub_rembg


def write_image(path, red_region):
    """64×48 RGB: red 200 where ``red_region`` (a (48, 64) bool) else 0; green/blue 50."""
    arr = np.full((48, 64, 3), 50, np.uint8)
    arr[:, :, 0] = np.where(red_region, 200, 0)
    Image.fromarray(arr, "RGB").save(path, "PNG")


def files():
    d = gi.mask_cache_dir()
    return sorted(d.glob("*.png")) if d.is_dir() else []


cols = np.arange(64)[None, :].repeat(48, 0)
rows = np.arange(48)[:, None].repeat(64, 1)
A = cols < 32
B = rows < 24
a_png = TMP / "a.png"
write_image(a_png, A)

# [M1]
m1 = gi._mask(a_png, (64, 48))
m1b = gi._mask(a_png, (64, 48))
check("M1", len(CALLS) == 1, f"stub calls {len(CALLS)} (expected 1)")
check("M1", np.array_equal(m1, m1b) and np.array_equal(m1, A), "hit equals miss equals the hand mask")
hit = gi._mask_image(a_png.read_bytes(), (64, 48))
check("M1", hit.mode == "L" and hit.size == (64, 48) and len(CALLS) == 1, f"hit image {hit.mode} {hit.size}")
check("M1", len(files()) == 1 and gi.mask_cache_dir() == TMP / "storage" / ".cache" / "masks",
      f"cache files {len(files())} in {gi.mask_cache_dir()}")
check("M1", gi.MASK_CACHE_MAX == 4000, f"MASK_CACHE_MAX {gi.MASK_CACHE_MAX}")

# [M2]
m2 = gi._mask(a_png, (32, 24))
expect2 = np.asarray(Image.fromarray(np.where(A, 255, 0).astype(np.uint8), "L").resize(
    (32, 24), Image.Resampling.BILINEAR)) >= gi.MASK_THRESHOLD
check("M2", len(CALLS) == 2, f"stub calls {len(CALLS)} (expected 2)")
check("M2", np.array_equal(m2, expect2) and m2[:, :15].all() and not m2[:, 17:].any(),
      "the 2:1 bilinear mask of the stub mask")

# [M3]
write_image(a_png, B)
m3 = gi._mask(a_png, (64, 48))
check("M3", len(CALLS) == 3, f"stub calls {len(CALLS)} (expected 3)")
check("M3", np.array_equal(m3, B) and not np.array_equal(m3, m1), "B's mask, differs from A's")

# [M4]
import hashlib  # noqa: E402
b_sha = hashlib.sha256(a_png.read_bytes()).hexdigest()
b_files = [f for f in files() if f.name.startswith(b_sha) and f.name.endswith("64x48.png")]
check("M4", len(b_files) == 1, f"B's cache file found: {[f.name for f in b_files]}")
b_files[0].write_bytes(b_files[0].read_bytes()[:10])
try:
    m4 = gi._mask(a_png, (64, 48))
    err = None
except Exception as e:  # noqa: BLE001
    m4, err = None, e
check("M4", err is None, f"no exception ({err!r})")
check("M4", len(CALLS) == 4 and m4 is not None and np.array_equal(m4, B), f"re-matted: stub calls {len(CALLS)}")
with Image.open(b_files[0]) as im:
    im.load()
    check("M4", im.mode == "L" and im.size == (64, 48), f"rewritten file {im.mode} {im.size}")

# [M5]
c_png = TMP / "c.png"
write_image(c_png, (rows + cols) % 7 < 3)
results = [None, None]


def worker(i):
    results[i] = gi._mask(c_png, (64, 48))


threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("M5", len(CALLS) == 5, f"stub calls {len(CALLS)} (expected 5)")
check("M5", results[0] is not None and np.array_equal(results[0], results[1]), "both threads got the same mask")

# [M6]
for f in files():
    f.unlink()
gi.MASK_CACHE_MAX = 2
names = []
for k, region in enumerate((cols < 10, cols < 20, cols < 40)):
    p = TMP / f"m6_{k}.png"
    write_image(p, region)
    gi._mask(p, (64, 48))
    names.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}")
    time.sleep(0.05)
left = files()
check("M6", len(left) == 2, f"{len(left)} files left (expected 2)")
check("M6", not any(f.name.startswith(names[0]) for f in left)
      and all(any(f.name.startswith(n) for f in left) for n in names[1:]), "the oldest (D) went")
gi.MASK_CACHE_MAX = 4000

# [M7]
before, n_files = len(CALLS), len(files())
saved = paths._storage_dir
paths._storage_dir = None
try:
    m7 = gi._mask_image(c_png.read_bytes(), (64, 48))
    err = None
except Exception as e:  # noqa: BLE001
    m7, err = None, e
finally:
    paths._storage_dir = saved
check("M7", err is None and m7 is not None and np.array_equal(np.asarray(m7) >= gi.MASK_THRESHOLD, results[0]),
      f"uncached mask without a storage root ({err!r})")
check("M7", len(CALLS) == before + 1 and len(files()) == n_files, "one stub call, nothing written")

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
