"""Smoke: Ruling A118 / A216 — the accessory build's identity, state and gap (``app/core/accessory_build.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_build.py   (no server; a temp storage dir, monkeypatched base)

Expected values, derived by hand:

[1] ``asig`` = md5[:12] of the geometry inputs {version, kind, chain}: the metal is not one of them, so gold →
    silver keeps the asig (a re-assembly, never a rebuild — ``material_key`` changes instead: "accessory:gold:
    #d4af37:0.25" → "accessory:silver:#c0c0c0:0.2:1.0"); drop 4 → 10 changes it; thickness 1.5 → 2.0 changes it.
[2] The state rule (``accessory_state``), base sha "B1":
    no jewellery → blocked "Choose the accessory kind in the Wardrobe"; a kind outside ``BUILT_KINDS`` (A238: every kind
    is built, so the smoke takes ring out of it for the check) → blocked "Ring: not built yet…";
    no plain body → blocked "No plain body yet"; nothing stored → due "Not built yet…"; a record of THIS asig on
    B1 → current; the same record when the body is B2 → due "Body changed…"; only a record of another asig (the
    drop changed) → due "Chain settings changed…"; a failure record on B1 → failed "Build failed — boom".
[3] ``gap_metrics`` on a tube around the cylinder of smoke_accessory_curve: centre line radius 0.06 + 0.0017 +
    0.00075, tube radius 0.00075 (1.5 mm chain), 48 rings × 8 sides: the innermost vertex of each ring lies at
    0.06 + 0.0017 from the axis → min gap = 1.7 mm minus the facet sag (≤ 0.0045 mm) → every ring 1.70 mm
    (rounded to 0.01 mm), inside_share 0.0.
[4] A216 review H2 — the plausibility gate (``plausible``), neck ellipse 0.36 m, drop 0.04 m: the length bound is
    1.35 · 0.36 + 2.6 · 0.04 = 0.59 m and the floor 0.9 · 0.36 = 0.324 m. Length 0.46, segment ratio 1.3, joints
    Neck/Spine2/LeftShoulder, inside 0 → passes; length 0.62 → refused ("long"); 0.30 → refused ("shorter");
    segment ratio 3.5 → refused ("jumps"); Head at 0.6 (> HEAD_WEIGHT_MAX 0.5) or LeftArm at 0.3 (> 0.2) → refused
    ("move with"), Head at 0.4 → passes; inside 0.01 →
    refused ("inside").
[5] A216 review L1 — ``drop_other_builds(folder, "item_x", A)`` with the files item_x_<A>.json, item_x_<B>.npz,
    item_x_<B>.failed.json, item_xy_<B>.json and item_x_notes.txt (A, B 12 hex digits) deletes exactly
    item_x_<B>.failed.json and item_x_<B>.npz (another item "item_xy" and a non-build name stay).
[6] A216 review L3 — ``failure_text``: KeyError('neck') → "The plain body has no neck bone"; ValueError("x") → "x".
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="smoke_accessory_build_")
os.environ["STORAGE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
import json  # noqa: E402
import numpy as np  # noqa: E402
from app.core import accessory_build as ab, accessory_mesh as am, model_geometry  # noqa: E402
from app.core.accessory_spec import normalize  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def item(**jew):
    return {"id": "item_x", "category": "outfit_piece", "outfit_piece": {"slots": ["neck"], "mesh_mode": "accessory",
                                             **({"jewellery": jew} if jew else {})}}


gold = normalize({"kind": "necklace"})
check("[1] metal keeps asig", ab.asig(gold), ab.asig(normalize({"kind": "necklace", "metal": "silver"})))
check("[1] drop changes asig", ab.asig(gold) != ab.asig(normalize({"kind": "necklace", "chain": {"drop_cm": 10}})), True)
check("[1] thickness changes asig",
      ab.asig(gold) != ab.asig(normalize({"kind": "necklace", "chain": {"thickness_mm": 2.0}})), True)
check("[1] material gold", ab.material_key(item(kind="necklace")), "accessory:gold:#d4af37:0.25:1.0")
check("[1] material silver", ab.material_key(item(kind="necklace", metal="silver")), "accessory:silver:#c0c0c0:0.2:1.0")

store = Path(TMP) / "jewellery"
store.mkdir()
ab.store_dir = lambda _c: store
BASE = {"sha": "B1"}
ab._current_base = lambda _c, _p: (("base1", BASE["sha"]) if BASE["sha"] else None)
model_geometry.record_matches = lambda rec, sha, **_k: rec.get("base_model_sha256") == sha


def state(it):
    s = ab.accessory_state("C", "item_x", profile={}, item=it)
    return s["state"], s["reason"]


neck = item(kind="necklace")
sig = ab.asig(gold)
check("[2] no kind", state(item()), ("blocked", ab.REASON_NO_KIND))
from app.core import accessory_spec as _spec  # noqa: E402
_built = _spec.BUILT_KINDS
_spec.BUILT_KINDS = tuple(k for k in _built if k != "ring")
check("[2] kind not built", state(item(kind="ring"))[0], "blocked")
check("[2] kind not built reason", state(item(kind="ring"))[1].startswith("Ring: not built yet"), True)
_spec.BUILT_KINDS = _built
BASE["sha"] = ""
check("[2] no body", state(neck), ("blocked", ab.REASON_NO_BODY))
BASE["sha"] = "B1"
check("[2] nothing stored", state(neck), ("due", ab.REASON_NOT_BUILT))
(store / f"item_x_{sig}.json").write_text(json.dumps({"asig": sig, "base_model_sha256": "B1"}))
np.savez(store / f"item_x_{sig}.npz", V=np.zeros((1, 3)))
check("[2] built on B1", state(neck), ("current", ""))
BASE["sha"] = "B2"
check("[2] body changed", state(neck), ("due", ab.REASON_BODY))
BASE["sha"] = "B1"
check("[2] drop changed", state(item(kind="necklace", chain={"drop_cm": 10})), ("due", ab.REASON_SETTINGS))
other = ab.asig(normalize({"kind": "necklace", "chain": {"drop_cm": 12}}))
(store / f"item_x_{other}.failed.json").write_text(json.dumps({"base_model_sha256": "B1", "error": "boom"}))
check("[2] failed", state(item(kind="necklace", chain={"drop_cm": 12})), ("failed", "Build failed — boom"))

sides = 256
a = 2 * np.pi * np.arange(sides) / sides
ring = np.stack([0.06 * np.cos(a), np.zeros(sides), 0.06 * np.sin(a)], 1)
P = np.concatenate([ring, ring + [0, 0.2, 0], [[0, 0, 0], [0, 0.2, 0]]])
F = []
for i in range(sides):
    j = (i + 1) % sides
    F += [[i, sides + i, j], [j, sides + i, sides + j], [2 * sides, i, j], [2 * sides + 1, sides + j, sides + i]]
F = np.array(F, np.int64)
r = 0.00075
b = 2 * np.pi * np.arange(48) / 48
c = (0.06 + 0.0017 + r) * np.stack([np.cos(b), np.zeros(48), np.sin(b)], 1) + [0, 0.1, 0]
V, _F, _N = am.tube(c, r, sides=8, outward=c - [0, 0.1, 0])
m = ab.gap_metrics(V, 48, P, F)
print(f"       {m}")
check("[3] every ring 1.70 mm", (m["gap_mm"]["min"], m["gap_mm"]["p95"]), (1.7, 1.7))
check("[3] inside share", m["inside_share"], 0.0)

def gate(**kw):
    m = {"neck_ellipse_m": 0.36, "length_m": 0.46, "max_segment_ratio": 1.3, "inside_share": 0.0,
         "joints": {"mixamorig:Neck": 0.9, "mixamorig:Spine2": 0.7, "mixamorig:LeftShoulder": 0.3}, **kw}
    try:
        ab.plausible(m, 0.04)
        return "ok"
    except ValueError as e:
        return str(e)

check("[4] plausible", gate(), "ok")
check("[4] too long", "long" in gate(length_m=0.62), True)
check("[4] too short", "shorter" in gate(length_m=0.30), True)
check("[4] jumps", "jumps" in gate(max_segment_ratio=3.5), True)
check("[4] head 0.6", "move with head" in gate(joints={"mixamorig:Neck": 0.9, "mixamorig:Head": 0.6}), True)
check("[4] head 0.4", gate(joints={"mixamorig:Neck": 0.9, "mixamorig:Head": 0.4}), "ok")
check("[4] arm", "move with leftarm" in gate(joints={"mixamorig:LeftArm": 0.3}), True)
check("[4] inside", "inside" in gate(inside_share=0.01), True)

A, B = "a" * 12, "b" * 12
d5 = Path(TMP) / "l1"
d5.mkdir()
for n in (f"item_x_{A}.json", f"item_x_{B}.npz", f"item_x_{B}.failed.json", f"item_xy_{B}.json", "item_x_notes.txt"):
    (d5 / n).write_text("x")
check("[5] deleted", ab.drop_other_builds(d5, "item_x", A), [f"item_x_{B}.failed.json", f"item_x_{B}.npz"])
check("[5] kept", sorted(p.name for p in d5.iterdir()), sorted([f"item_x_{A}.json", f"item_xy_{B}.json",
                                                               "item_x_notes.txt"]))
check("[6] KeyError", ab.failure_text(KeyError("neck")), "The plain body has no neck bone")
check("[6] ValueError", ab.failure_text(ValueError("x")), "x")

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
