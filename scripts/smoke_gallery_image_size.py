#!/usr/bin/env python3
"""Smoke run for the free gallery-image resolution + the room SHAPE HINT.

Two pure helpers, no world, no DB and no image backend:

* ``world_ops._clamp_image_dim`` — the caller-chosen pixel edge, snapped to
  the 64-px grid every diffusion backend wants and clamped to 256..2048;
* ``world_ops.room_shape_hint`` — the BUILDER that turns a room's layout
  rectangle into a :class:`prompt_compose.ShapeHint`, plus
  ``prompt_compose.render_hint`` — the RENDERER that words that hint per
  prompt family. (The old single-function ``room_proportions_hint`` was split
  into exactly this builder/renderer pair; the wording moved to
  prompt_compose, which is why this file now checks both halves.)

Since scene_recipe v6 a layout side IS its real size in metres, so
``room_size_m`` always answers for a valid rectangle — the "square without a
scale anchor" branch of ``room_shape_hint`` is unreachable today and is
therefore not asserted here.

Hand-derived expectations (constants: IMAGE_DIM_MIN 256, IMAGE_DIM_MAX 2048,
IMAGE_DIM_GRID 64, ROOM_SQUARE_MAX_RATIO 1.05, RATIO_MIN 1.3,
RATIO_NARROW 2.5; _metres() rounds to the nearest HALF metre):

  Size coercion — round(px/64)*64, then clamp:
      100 -> round(1.5625)=2  -> 128 -> clamped up to 256
      288 -> round(4.5)=4     -> 256   (Python rounds ties to EVEN)
      352 -> round(5.5)=6     -> 384   (…which is why 5.5 goes UP)
      700 -> round(10.9375)=11-> 704
     2000 -> round(31.25)=31  -> 1984
     5000 -> round(78.125)=78 -> 4992 -> clamped down to 2048
    anything unparseable or <= 0 -> 0 = "nothing usable was passed"

  Shape hint (layout w x d in metres, indoor unless stated):
     4 x 4    ratio 1.00 < 1.05 -> "square",      no qualifier, no clause
     4 x 4.4  ratio 1.10        -> "rectangular", no qualifier; 4.4 m prints
                                   as "4.5" (nearest half metre)
     4 x 5    ratio 1.25 < 1.30 -> "rectangular", still no length clause
     4 x 6    ratio 1.50        -> "elongated" + "noticeably longer than it
                                   is wide" (multiplier 1.5 < 2 stays verbal)
     2 x 5    ratio 2.50 >= 2.5 -> "long narrow" + "about 2.5 times as long
                                   as it is wide"  (the reference case)
     0 x 5 / no layout / no room -> None (nothing worth saying)

  Family voices for the 2 x 5 room:
     natural  -> "a long narrow rectangular floor plan roughly 2 by 5 metres,
                  about 2.5 times as long as it is wide, the floor slab fills
                  the frame edge to edge"
     keywords -> "long narrow rectangular floor plan, 2 by 5 meters
                  footprint, fills the frame edge to edge"
                 (tags only, no verbal multiplier — and the US spelling
                  "meters", which the natural voice does NOT use)
     outdoor  -> the surface word becomes "ground base"

Usage:  ./.venv/bin/python scripts/smoke_gallery_image_size.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Throwaway storage BEFORE any app import: paths.init() falls back to
# ./worlds/demo, and a check script must never touch tracked world data.
STORAGE = Path(tempfile.mkdtemp(prefix="gallery-size-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core.prompt_compose import render_hint  # noqa: E402
from app.core.world_ops import (_clamp_image_dim,  # noqa: E402
                                room_shape_hint)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def eq(label: str, actual, expected) -> None:
    check(label, actual == expected,
          f"{actual!r}" if actual == expected else f"{actual!r} != {expected!r}")


def hint(w, d, outdoor: bool = False):
    """The hint of a room whose layout rectangle is w x d METRES."""
    return room_shape_hint({}, {"layout": {"w": w, "d": d}}, outdoor)


def natural(w, d, outdoor: bool = False) -> str:
    h = hint(w, d, outdoor)
    return render_hint(h, "natural") if h else ""


print("Image size coercion (64 grid, 256..2048)")
for raw, want in ((None, 0), ("", 0), (0, 0), (-5, 0), ("nope", 0),
                  (100, 256), (255, 256), (256, 256), (288, 256), (300, 320),
                  (352, 384), (700, 704), ("1024", 1024), (1025, 1024),
                  (2000, 1984), (5000, 2048)):
    got = _clamp_image_dim(raw)
    check(f"{raw!r} -> {want}", got == want, str(got))


print("\nShape hint: what the builder reads off the rectangle")
h = hint(4, 4)
eq("4 x 4 is square", h.shape, "square")
eq("...and carries its real metres", (h.short_m, h.long_m), (4.0, 4.0))
eq("...on a floor slab", h.surface, "floor slab")
eq("4 x 4.4 is already rectangular", hint(4, 4.4).shape, "rectangular")
eq("2 x 5 keeps the long side long", (hint(2, 5).short_m, hint(2, 5).long_m),
   (2.0, 5.0))
eq("orientation does not matter",
   (hint(5, 2).short_m, hint(5, 2).long_m, hint(5, 2).shape),
   (hint(2, 5).short_m, hint(2, 5).long_m, hint(2, 5).shape))
eq("outdoor stands on the ground", hint(4, 6, True).surface, "ground base")
check("a degenerate rectangle says nothing", hint(0, 5) is None)
check("a room without layout says nothing", room_shape_hint({}, {}) is None)
check("no room at all says nothing", room_shape_hint({}, None) is None)
check("an unreadable layout says nothing",
      room_shape_hint({}, {"layout": {"w": "wide", "d": 5}}) is None)


print("\nRendered clause, natural voice")
eq("4 x 4 — square, no length clause",
   natural(4, 4),
   "a square floor plan roughly 4 by 4 metres, "
   "the floor slab fills the frame edge to edge")
eq("4 x 4.4 — rectangular, 4.4 m prints as 4.5",
   natural(4, 4.4),
   "a rectangular floor plan roughly 4 by 4.5 metres, "
   "the floor slab fills the frame edge to edge")
eq("4 x 5 — 1.25 is below RATIO_MIN, still no clause",
   natural(4, 5),
   "a rectangular floor plan roughly 4 by 5 metres, "
   "the floor slab fills the frame edge to edge")
eq("4 x 6 — elongated, multiplier stays verbal below 2x",
   natural(4, 6),
   "an elongated rectangular floor plan roughly 4 by 6 metres, "
   "noticeably longer than it is wide, "
   "the floor slab fills the frame edge to edge")
eq("2 x 5 — long narrow + 2.5x (the reference case)",
   natural(2, 5),
   "a long narrow rectangular floor plan roughly 2 by 5 metres, "
   "about 2.5 times as long as it is wide, "
   "the floor slab fills the frame edge to edge")
eq("orientation does not change the sentence", natural(5, 2), natural(2, 5))
eq("outdoor swaps the surface word",
   natural(2, 5, True),
   "a long narrow rectangular floor plan roughly 2 by 5 metres, "
   "about 2.5 times as long as it is wide, "
   "the ground base fills the frame edge to edge")


print("\nRendered clause, keywords voice")
eq("2 x 5 — tags only, no verbal multiplier",
   render_hint(hint(2, 5), "keywords"),
   "long narrow rectangular floor plan, 2 by 5 meters footprint, "
   "fills the frame edge to edge")
eq("4 x 4 — square tag with its footprint",
   render_hint(hint(4, 4), "keywords"),
   "square floor plan, 4 by 4 meters footprint, fills the frame edge to edge")
check("the two voices really differ",
      render_hint(hint(2, 5), "keywords") != natural(2, 5))


try:
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
finally:
    shutil.rmtree(STORAGE, ignore_errors=True)
sys.exit(1 if FAILURES else 0)
