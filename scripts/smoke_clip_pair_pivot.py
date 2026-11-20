"""Owner decision 2026-11-20 (docs/schnittstellen-3d.md § A8a, scene-render pairScale.ts): a pair clip's contact pivot
``pair_pivot_cm`` in its ``<kind>.json`` — validation, reading, the orientation bake's effect, the writer and the PATCH route.

Usage: ./.venv/bin/python scripts/smoke_clip_pair_pivot.py   (no server; a temp storage dir and temp clip libraries)

Expected, by hand:
[1] validate_pair_pivot: [12, 30] -> [12.0, 30.0] (floats); (-300, 300) accepted (the bound is inclusive);
    refused: [301, 0], [0, -300.5], [True, 0], ["1", 2], [1], [1, 2, 3], [nan, 0], [inf, 0], {"x": 1}, None.
[2] clip_pair_pivot: None / {} / a junk stored value [999, 0] -> None (= the clip frame origin); {"pair_pivot_cm":
    [1.5, -2]} -> [1.5, -2.0].
[3] orient_pair_pivot (the bake turns the clip frame by R = Ry(yaw)·Rx(tilt)·Rz(roll); x' = cos·x + sin·z,
    z' = −sin·x + cos·z for a pure yaw): [10, 0] yaw 90 -> [0.0, -10.0]; [3, 4] yaw 0 -> [3.0, 4.0]; [3, 4] yaw 180 ->
    [-3.0, -4.0]; [3, 4] yaw 30 -> [3·0.866025 + 4·0.5, −3·0.5 + 4·0.866025] = [4.598076, 1.964102] -> [4.6, 2.0];
    tilt 5 -> None; roll -2 -> None; None in -> None.
[4] set_clip_pair_pivot on a temp library with hug__a.fbx, hug__b.fbx and hug.json, plus a solo walk.fbx + walk.json:
    [12, 30] -> hug.json holds pair_pivot_cm [12.0, 30.0], every other key unchanged; both halves' listing rows carry
    pair_pivot_cm [12.0, 30.0]; [400, 0] is refused and leaves the file byte-identical; None removes the key (rows
    then carry None); the solo clip is refused; a solo row carries None.
[5] the PATCH route body {"pair_pivot_cm": [5, 6]} writes [5.0, 6.0]; {"pair_pivot_cm": "x"} is a 400.
"""
import json
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="smoke-pivot-")
os.environ["ANIMATION_CLIPS_DIR"] = os.path.join(tmp, "clips")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = os.path.join(tmp, "clips-licensed")
os.environ["ANIMATION_RIG_FILE"] = os.path.join(tmp, "rig.fbx")
os.environ["STORAGE_DIR"] = tmp
os.environ["INSTANCE_DIR"] = os.path.join(tmp, "instance")
from app.core import paths  # noqa: E402
paths.init(tmp)
from app.core import animation_clips as ac  # noqa: E402

n = 0


def ok(label):
    global n
    n += 1
    print("  ok", label)


def refused(fn, *args):
    try:
        fn(*args)
    except ac.ClipLibraryError:
        return True
    return False


# [1]
assert ac.validate_pair_pivot([12, 30]) == [12.0, 30.0]
assert all(isinstance(v, float) for v in ac.validate_pair_pivot([12, 30]))
assert ac.validate_pair_pivot((-300, 300)) == [-300.0, 300.0]
for bad in ([301, 0], [0, -300.5], [True, 0], ["1", 2], [1], [1, 2, 3], [math.nan, 0], [math.inf, 0], {"x": 1}, None):
    assert refused(ac.validate_pair_pivot, bad), bad
ok("[1] validate_pair_pivot")

# [2]
assert ac.clip_pair_pivot(None) is None
assert ac.clip_pair_pivot({}) is None
assert ac.clip_pair_pivot({"pair_pivot_cm": [999, 0]}) is None
assert ac.clip_pair_pivot({"pair_pivot_cm": [1.5, -2]}) == [1.5, -2.0]
ok("[2] clip_pair_pivot")

# [3]
assert ac.orient_pair_pivot([10, 0], 90, 0, 0) == [0.0, -10.0]
assert ac.orient_pair_pivot([3, 4], 0, 0, 0) == [3.0, 4.0]
assert ac.orient_pair_pivot([3, 4], 180, 0, 0) == [-3.0, -4.0]
assert ac.orient_pair_pivot([3, 4], 30, 0, 0) == [4.6, 2.0], ac.orient_pair_pivot([3, 4], 30, 0, 0)
assert ac.orient_pair_pivot([3, 4], 0, 5, 0) is None
assert ac.orient_pair_pivot([3, 4], 10, 0, -2) is None
assert ac.orient_pair_pivot(None, 90, 0, 0) is None
ok("[3] orient_pair_pivot")

# [4]
lib = os.environ["ANIMATION_CLIPS_DIR"]
os.makedirs(lib, exist_ok=True)
for name in ("hug__a.fbx", "hug__b.fbx", "walk.fbx"):
    with open(os.path.join(lib, name), "wb") as fh:
        fh.write(b"not really an fbx")
side = os.path.join(lib, "hug.json")
with open(side, "w", encoding="utf-8") as fh:
    json.dump({"kind": "hug", "duration_s": 2.0, "fps": 30, "roles": ["a", "b"], "geometry": {"anchor_s": 0.5}}, fh)
with open(os.path.join(lib, "walk.json"), "w", encoding="utf-8") as fh:
    json.dump({"kind": "walk", "duration_s": 1.0, "fps": 30}, fh)

rows = ac.set_clip_pair_pivot("free", "hug__a.fbx", [12, 30])
data = json.load(open(side, encoding="utf-8"))
assert data["pair_pivot_cm"] == [12.0, 30.0]
assert {k: v for k, v in data.items() if k != "pair_pivot_cm"} == {
    "kind": "hug", "duration_s": 2.0, "fps": 30, "roles": ["a", "b"], "geometry": {"anchor_s": 0.5}}, data
pairs = [r for r in rows if r["kind"] == "hug"]
assert {r["role"] for r in pairs} == {"a", "b"} and all(r["pair_pivot_cm"] == [12.0, 30.0] for r in pairs), rows
before = open(side, "rb").read()
assert refused(ac.set_clip_pair_pivot, "free", "hug__b.fbx", [400, 0])
assert open(side, "rb").read() == before
rows = ac.set_clip_pair_pivot("free", "hug__b.fbx", None)
assert "pair_pivot_cm" not in json.load(open(side, encoding="utf-8"))
assert all(r["pair_pivot_cm"] is None for r in rows if r["kind"] == "hug")
assert refused(ac.set_clip_pair_pivot, "free", "walk.fbx", [1, 2])
solo = [ac.clip_view(e) for e in ac.clip_entries() if e["kind"] == "walk"]
assert solo and solo[0]["pair_pivot_cm"] is None, solo
ok("[4] set_clip_pair_pivot writes, refuses, clears; the listing rows carry it")

# [5]
from fastapi import HTTPException  # noqa: E402
from app.routes import assets  # noqa: E402
res = assets._patch_animation_clip_sync("free", "hug__a.fbx", {"pair_pivot_cm": [5, 6]})
assert json.load(open(side, encoding="utf-8"))["pair_pivot_cm"] == [5.0, 6.0]
assert any(r.get("pair_pivot_cm") == [5.0, 6.0] for r in res["clips"])
try:
    assets._patch_animation_clip_sync("free", "hug__a.fbx", {"pair_pivot_cm": "x"})
    raise AssertionError("accepted a string pivot")
except HTTPException as e:
    assert e.status_code == 400, e.status_code
ok("[5] PATCH pair_pivot_cm")
print(f"smoke_clip_pair_pivot: {n} ok")
shutil.rmtree(tmp, ignore_errors=True)
