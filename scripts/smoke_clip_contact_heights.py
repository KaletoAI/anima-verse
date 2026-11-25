"""Owner decision 2026-11-25 (docs/schnittstellen-3d.md § A8a "Echte Körpergrößen", scene-render pairHeight.ts): a pair
clip's contact heights ``pair_contact_heights`` in its ``<kind>.json`` — validation, reading, the writer's merge, the
orientation bake's effect and the PATCH route.

Usage: ./.venv/bin/python scripts/smoke_clip_contact_heights.py   (no server; a temp storage dir and temp clip libraries)

Expected, by hand:
[1] validate_pair_contact_entry("b>a:mouth", {height_cm: 85.24, roles: {a: A, b: B}}) -> height 85.2 (0.1 cm), every
    joint rounded to 0.1 cm, floats; refused: key "a>a:mouth" (same role), "b-a:mouth", "f>a:mouth", height 301 or -1,
    a role entry missing the part (only a), an extra key, three legs, a joint of two numbers, a joint 301 cm out,
    a support of -51 cm, True as a number. `method` "anchor" / "measured" is kept as given, absent stays absent;
    "guess" is refused.
[2] clip_pair_contact_heights: None / {} / {"pair_contact_heights": []} -> None; a stored map with one valid and one
    broken relation -> only the valid one.
[3] set_clip_pair_contact_heights on hug__a/hug__b + hug.json and a solo walk: {"b>a:mouth": E} writes it and leaves
    the other keys; {"b>a:hand_left": E2} adds a second relation and keeps the first (merge); {"b>a:mouth": None}
    removes only that one; a broken value is refused and leaves the file byte-identical; None removes the key; the
    solo clip is refused and its row carries None; both pair rows carry the stored map.
[4] the orientation bake's rule, as the bake applies it (the meta dict): a yaw keeps the map; a tilt, a roll, a height
    shift or a role shift with a vertical component drops it; a horizontal role shift keeps it.
[5] PATCH {"pair_contact_heights": {...}} writes; {"pair_contact_heights": "x"} is a 400.
"""
import copy
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="smoke-contact-heights-")
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


LEG = [[10, 38.04, 0], [30, 6, 5], [-10, 10, 30]]
A = {"support_cm": 0, "hips_cm": 40.44, "legs": [LEG, LEG]}
B = {"support_cm": 0, "hips_cm": 97.2, "legs": [[[9, -7, 0], [9, 50, 6], [9, 8, 0]]]}
E = {"height_cm": 85.24, "roles": {"a": A, "b": B}}

# [1]
got = ac.validate_pair_contact_entry("b>a:mouth", E)
assert got["height_cm"] == 85.2 and isinstance(got["height_cm"], float)
assert got["roles"]["a"]["hips_cm"] == 40.4 and got["roles"]["a"]["legs"][0][0] == [10.0, 38.0, 0.0], got
for key, value in (("a>a:mouth", E), ("b-a:mouth", E), ("f>a:mouth", E),
                   ("b>a:mouth", {**E, "height_cm": 301}), ("b>a:mouth", {**E, "height_cm": -1}),
                   ("b>a:mouth", {**E, "roles": {"a": A}}), ("b>a:mouth", {**E, "extra": 1}),
                   ("b>a:mouth", {**E, "roles": {"a": {**A, "legs": [LEG, LEG, LEG]}, "b": B}}),
                   ("b>a:mouth", {**E, "roles": {"a": {**A, "legs": [[[1, 2], [3, 4, 5], [6, 7, 8]]]}, "b": B}}),
                   ("b>a:mouth", {**E, "roles": {"a": {**A, "legs": [[[1, 2, 301], [3, 4, 5], [6, 7, 8]]]}, "b": B}}),
                   ("b>a:mouth", {**E, "roles": {"a": {**A, "support_cm": -51}, "b": B}}),
                   ("b>a:mouth", {**E, "height_cm": True})):
    assert refused(ac.validate_pair_contact_entry, key, value), (key, value)
assert "method" not in got
assert ac.validate_pair_contact_entry("b>a:mouth", {**E, "method": "anchor"})["method"] == "anchor"
assert ac.validate_pair_contact_entry("b>a:mouth", {**E, "method": "measured"})["method"] == "measured"
assert refused(ac.validate_pair_contact_entry, "b>a:mouth", {**E, "method": "guess"})
ok("[1] validate_pair_contact_entry rounds to 0.1 cm and refuses the malformed")

# [2]
assert ac.clip_pair_contact_heights(None) is None
assert ac.clip_pair_contact_heights({}) is None
assert ac.clip_pair_contact_heights({"pair_contact_heights": []}) is None
mixed = ac.clip_pair_contact_heights({"pair_contact_heights": {"b>a:mouth": E, "x": {"height_cm": 1}}})
assert list(mixed) == ["b>a:mouth"], mixed
ok("[2] clip_pair_contact_heights keeps the valid relations only")

# [3]
lib = os.environ["ANIMATION_CLIPS_DIR"]
os.makedirs(lib, exist_ok=True)
for name in ("hug__a.fbx", "hug__b.fbx", "walk.fbx"):
    with open(os.path.join(lib, name), "wb") as fh:
        fh.write(b"not really an fbx")
side = os.path.join(lib, "hug.json")
base = {"kind": "hug", "duration_s": 2.0, "fps": 30, "roles": ["a", "b"], "geometry": {"anchor_s": 0.5}}
with open(side, "w", encoding="utf-8") as fh:
    json.dump(base, fh)
with open(os.path.join(lib, "walk.json"), "w", encoding="utf-8") as fh:
    json.dump({"kind": "walk", "duration_s": 1.0, "fps": 30}, fh)
rows = ac.set_clip_pair_contact_heights("free", "hug__a.fbx", {"b>a:mouth": E})
data = json.load(open(side, encoding="utf-8"))
assert data["pair_contact_heights"]["b>a:mouth"]["height_cm"] == 85.2
assert {k: v for k, v in data.items() if k != "pair_contact_heights"} == base
assert all(r["pair_contact_heights"]["b>a:mouth"]["height_cm"] == 85.2 for r in rows if r["kind"] == "hug")
ac.set_clip_pair_contact_heights("free", "hug__b.fbx", {"b>a:hand_left": {**E, "height_cm": 100}})
data = json.load(open(side, encoding="utf-8"))
assert sorted(data["pair_contact_heights"]) == ["b>a:hand_left", "b>a:mouth"]
ac.set_clip_pair_contact_heights("free", "hug__a.fbx", {"b>a:mouth": None})
assert sorted(json.load(open(side, encoding="utf-8"))["pair_contact_heights"]) == ["b>a:hand_left"]
before = open(side, "rb").read()
assert refused(ac.set_clip_pair_contact_heights, "free", "hug__a.fbx", {"b>a:mouth": {"height_cm": 5}})
assert refused(ac.set_clip_pair_contact_heights, "free", "hug__a.fbx", [1])
assert open(side, "rb").read() == before
rows = ac.set_clip_pair_contact_heights("free", "hug__a.fbx", None)
assert "pair_contact_heights" not in json.load(open(side, encoding="utf-8"))
assert all(r["pair_contact_heights"] is None for r in rows if r["kind"] == "hug")
assert refused(ac.set_clip_pair_contact_heights, "free", "walk.fbx", {"b>a:mouth": E})
solo = [ac.clip_view(e) for e in ac.clip_entries() if e["kind"] == "walk"]
assert solo and solo[0]["pair_contact_heights"] is None
ok("[3] set_clip_pair_contact_heights writes, merges per relation, removes, refuses, clears")

# [4] the bake rule, read from the source: the condition guarding the drop
src = open(os.path.join(ROOT, "app/core/animation_clips.py"), encoding="utf-8").read()
cond = src[src.index('if baked and siblings and "pair_contact_heights" in meta'):]
cond = cond[:cond.index("meta.pop(\"pair_contact_heights\"")]
assert "tilt, roll, height" in cond and "abs(v[1])" in cond and "yaw" not in cond.split("#")[0], cond


def bake_drops(yaw, tilt, roll, height, per_role):
    meta = {"pair_contact_heights": {"b>a:mouth": E}}
    baked, siblings = True, True
    if baked and siblings and "pair_contact_heights" in meta and (
            any(abs(v) > 1e-9 for v in (tilt, roll, height)) or any(abs(v[1]) > 1e-9 for v in per_role.values())):
        meta.pop("pair_contact_heights", None)
    return "pair_contact_heights" not in meta


assert not bake_drops(90, 0, 0, 0, {}) and not bake_drops(0, 0, 0, 0, {"b": [4, 0, -3]})
assert bake_drops(0, 5, 0, 0, {}) and bake_drops(0, 0, -2, 0, {}) and bake_drops(0, 0, 0, 1.5, {})
assert bake_drops(0, 0, 0, 0, {"b": [0, 0.1, 0]})
ok("[4] a yaw or a horizontal role shift keeps the heights; tilt, roll, height or a vertical role shift drops them")

# [5]
from fastapi import HTTPException  # noqa: E402
from app.routes import assets  # noqa: E402
res = assets._patch_animation_clip_sync("free", "hug__a.fbx", {"pair_contact_heights": {"b>a:mouth": copy.deepcopy(E)}})
assert json.load(open(side, encoding="utf-8"))["pair_contact_heights"]["b>a:mouth"]["height_cm"] == 85.2
assert any((r.get("pair_contact_heights") or {}).get("b>a:mouth") for r in res["clips"])
try:
    assets._patch_animation_clip_sync("free", "hug__a.fbx", {"pair_contact_heights": "x"})
    raise AssertionError("accepted a string")
except HTTPException as e:
    assert e.status_code == 400, e.status_code
ok("[5] PATCH pair_contact_heights")
print(f"smoke_clip_contact_heights: {n} ok")
shutil.rmtree(tmp, ignore_errors=True)
