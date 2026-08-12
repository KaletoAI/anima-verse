#!/usr/bin/env python3
"""Smoke run for the free gallery-image resolution + the floor-plan
proportion hint (Block M7).

Pure helpers, no world and no image backend: the size coercion and the prompt
clause a non-square room contributes. The example from the task text (a 2 x 5
room -> "roughly 2:5") is the reference case.

Usage:  ./.venv/bin/python scripts/smoke_gallery_image_size.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.world_ops import (_clamp_image_dim,          # noqa: E402
                                room_proportions_hint)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


print("Image size coercion (64 grid, 256..2048)")
for raw, want in ((None, 0), ("", 0), (0, 0), (-5, 0), ("nope", 0),
                  (100, 256), (255, 256), (256, 256), (300, 320),
                  (700, 704), ("1024", 1024), (1025, 1024),
                  (2000, 1984), (5000, 2048)):
    got = _clamp_image_dim(raw)
    check(f"{raw!r} -> {want}", got == want, str(got))


print("\nFloor-plan proportions in the prompt")
def hint(w, d):
    return room_proportions_hint({"layout": {"w": w, "d": d}})


check("square room stays silent", hint(0.4, 0.4) == "", hint(0.4, 0.4))
check("1.12 : 1 is still square enough", hint(0.4, 0.45) == "", hint(0.4, 0.45))
check("1.25 : 1 -> elongated 3:4 + verbal",
      hint(0.4, 0.5) == "elongated rectangular floor plan, noticeably longer "
      "than it is wide (footprint about 3:4), the floor slab fills the frame "
      "edge to edge",
      hint(0.4, 0.5))
check("2 x 5 room -> long narrow 2:5 + verbal (task example)",
      hint(0.2, 0.5) == "long narrow rectangular floor plan, about 2.5 times "
      "as long as it is wide (footprint about 2:5), the floor slab fills the "
      "frame edge to edge",
      hint(0.2, 0.5))
check("orientation does not matter", hint(0.2, 0.5) == hint(0.5, 0.2))
check("5 : 1 -> 1:5", "(footprint about 1:5)" in hint(0.1, 0.5), hint(0.1, 0.5))
check("no rectangle -> no clause", room_proportions_hint({}) == ""
      and room_proportions_hint(None) == "")
check("degenerate rectangle -> no clause", hint(0, 0.5) == "")

print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
sys.exit(1 if FAILURES else 0)
