"""The Poses tab's "Ground (no prop)" places (Ruling A110b) through the SAME scene-preview body the tab posts —
numbers derived by hand from the game's room-marker rule, never recorded from a run.

The draft (frontend/src/tabs/poses/placePicker.ts `groundRoom`): room x=-3, y=-3, w=6, d=6, one marker
``{group, at: [3, 3], rotation: 0, capacity: n}``, NO spacing_m / slot_axis — so the server's defaults apply:
``world_ops._spacing`` 0.6 m, ``_slot_axis`` 90°.

By hand (``scene_recipe.marker_slots``, facing 0 = south, row = compass facing + slot_axis = 90° → unit (sin 90°,
cos 90°) = (1, 0), i.e. along +x; the anchor = room min corner + at = (-3 + 3, -3 + 3) = (0, 0)):
  n = 1: slots [[0, 0]] (capacity 1 is the marker itself), facing 0
  n = 2: x = (i − 0.5) · 0.6 → [[-0.3, 0], [0.3, 0]]
  n = 3: x = (i − 1) · 0.6   → [[-0.6, 0], [0, 0], [0.6, 0]]
  n = 4: x = (i − 1.5) · 0.6 → [[-0.9, 0], [-0.3, 0], [0.3, 0], [0.9, 0]]   (inside the 6 m room)
  root_offset: ground and stand have root_drop 0 → 0.0 (schnittstellen-3d.md, place-type table)
  group: as sent ("ground" / "stand").

Usage: ./.venv/bin/python scripts/smoke_place_ground_slots.py   (no server; temp storage + instance)
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="ground-slots-")
os.environ["STORAGE_DIR"] = tmp
os.environ["INSTANCE_DIR"] = os.path.join(tmp, "inst")
from app.core import paths  # noqa: E402
paths.init(tmp)

from app.routes.play import _play_scene_preview_sync  # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        fails += 1


def draft(group, n):
    marker = {"id": "floor", "group": group, "at": [3, 3], "rotation": 0}
    if n > 1:
        marker["capacity"] = n
    return {"rooms": [{"id": "place-preview", "name": "Preview",
                       "layout": {"x": -3, "y": -3, "w": 6, "d": 6, "props": [], "markers": [marker]}}]}


want_slots = {1: [[0.0, 0.0]], 2: [[-0.3, 0.0], [0.3, 0.0]], 3: [[-0.6, 0.0], [0.0, 0.0], [0.6, 0.0]],
              4: [[-0.9, 0.0], [-0.3, 0.0], [0.3, 0.0], [0.9, 0.0]]}
for group in ("ground", "stand"):
    for n, slots in want_slots.items():
        payload = _play_scene_preview_sync(None, draft(group, n))
        ms = [m for m in payload.get("markers") or [] if m.get("id") == "floor"]
        check(f"{group} ×{n}: one marker", len(ms), 1)
        if not ms:
            continue
        m = ms[0]
        check(f"{group} ×{n}: slots", [[round(a, 3) + 0.0, round(b, 3) + 0.0] for a, b in m["slots"]], slots)
        check(f"{group} ×{n}: facing", m.get("facing"), 0.0)
        check(f"{group} ×{n}: root_offset", m.get("root_offset"), 0.0)
        check(f"{group} ×{n}: group", m.get("group"), group)

if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("OK")
