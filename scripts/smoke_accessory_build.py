"""Smoke: Ruling A118 / A216 — the accessory build's identity, state and gap (``app/core/accessory_build.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_build.py   (no server; a temp storage dir, monkeypatched base)

Expected values, derived by hand:

[1] ``asig`` = md5[:12] of the geometry inputs {version, kind, chain}: the metal is not one of them, so gold →
    silver keeps the asig (a re-assembly, never a rebuild — ``material_key`` changes instead: "accessory:gold:
    #d4af37:0.25" → "accessory:silver:#c0c0c0:0.2"); drop 4 → 10 changes it; thickness 1.5 → 2.0 changes it.
[2] The state rule (``accessory_state``), base sha "B1":
    no jewellery → blocked "Choose the accessory kind in the Wardrobe"; kind ring → blocked "Ring: not built yet…";
    no plain body → blocked "No plain body yet"; nothing stored → due "Not built yet…"; a record of THIS asig on
    B1 → current; the same record when the body is B2 → due "Body changed…"; only a record of another asig (the
    drop changed) → due "Chain settings changed…"; a failure record on B1 → failed "Build failed — boom".
[3] ``gap_metrics`` on a tube around the cylinder of smoke_accessory_curve: centre line radius 0.06 + 0.0017 +
    0.00075, tube radius 0.00075 (1.5 mm chain), 48 rings × 8 sides: the innermost vertex of each ring lies at
    0.06 + 0.0017 from the axis → min gap = 1.7 mm minus the facet sag (≤ 0.0045 mm) → every ring 1.70 mm
    (rounded to 0.01 mm), inside_share 0.0.
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
check("[1] material gold", ab.material_key(item(kind="necklace")), "accessory:gold:#d4af37:0.25")
check("[1] material silver", ab.material_key(item(kind="necklace", metal="silver")), "accessory:silver:#c0c0c0:0.2")

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
check("[2] ring", state(item(kind="ring"))[0], "blocked")
check("[2] ring reason", state(item(kind="ring"))[1].startswith("Ring: not built yet"), True)
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

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
