"""Per-type place capacity of a prop on the props listing (Ruling A110c), pinned by hand.

Fixture prop "sofa", markers as an author stores them, sanitized by ``props.sanitize_markers``:
  m1 seat, capacity 2           → seat 2
  m2 seat, no capacity          → 1 (absent = the marker itself); seat stays max(2, 1) = 2
  m3 lie,  capacity 2           → lie 2
  m4 lie,  capacity 1           → 1 (sanitizer drops a capacity of 1); lie stays 2
  m5 stand, capacity "x"        → 1 (unparsable = 1, as the scene recipe reads it)
  → marker_capacities == {"seat": 2, "lie": 2, "stand": 1}
  and room_recipe.marker_capacity agrees with scene_recipe.marker_slots: len(slots) == capacity for 1 and 2.
A lie PAIR clip (2 roles) fits (lie 2 ≥ 2); a lie group of 3 does not.

Usage: ./.venv/bin/python scripts/smoke_prop_marker_capacities.py   (no server, no world)
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="cap-smoke-")
atexit.register(shutil.rmtree, TMP, True)
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import props  # noqa: E402
from app.core.room_recipe import marker_capacity  # noqa: E402
from app.core.scene_recipe import marker_slots  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    fails += 0 if ok else 1


raw = [
    {"id": "m1", "group": "seat", "at": [0.3, 0.4, 0.5], "capacity": 2},
    {"id": "m2", "group": "seat", "at": [0.7, 0.4, 0.5]},
    {"id": "m3", "group": "lie", "at": [0.5, 0.5, 0.5], "capacity": 2},
    {"id": "m4", "group": "lie", "at": [0.5, 0.5, 0.2], "capacity": 1},
    {"id": "m5", "group": "stand", "at": [0.5, 0.0, 0.9], "capacity": "x"},
]
markers = props.sanitize_markers(raw, known_groups={"seat", "lie", "stand", "ground"})
caps = props._marker_capacities(markers)
check("per-type max", caps, {"seat": 2, "lie": 2, "stand": 1})
check("lie pair fits", caps.get("lie", 0) >= 2, True)
check("lie group of 3 does not", caps.get("lie", 0) >= 3, False)
for m in markers:
    n = marker_capacity(m)
    check(f"{m['id']} slots == capacity {n}", len(marker_slots((0.0, 0.0), 0.0, n, 0.6)), n)
check("empty marker = 1", marker_capacity({}), 1)
check("capacity 0 = 1", marker_capacity({"capacity": 0}), 1)
if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("OK")
