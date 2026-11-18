"""Smoke: A200 — a draped template over own-mesh pieces (and over templates by the slot stacks), template hosiery
taken into the shoe with its pose shapes.

Usage: ./.venv/bin/python scripts/smoke_a200_template_layers.py   (no server; a temp storage dir, no world data)

Hand-derived (``garment_set.LAYER_STACKS``: underwear_top < top < outer; underwear_bottom < legs < bottom < outer).
Items: JT template jacket (outer), TT template top (top), UT template top-kind piece worn on underwear_top,
OT own-mesh top (top), B own-mesh jeans (bottom, covers underwear_bottom), S shell stockings (legs), P own-mesh
pumps (feet = footwear, takes no part).

[1] ``garment_template.inner_pieces``:
    * JT (outer): over TT, OT, UT (outer over top / underwear_top), over B (outer over bottom) and through B over S
      (bottom over legs) -> templates [TT, UT], own [B, OT, S]; P is footwear, never a collider.
    * TT (top): over UT by the stack (top over underwear_top) -> templates [UT]. OT is worn on the same slot:
      each is over the other (worn slots count as covered), a cycle that ``layer_order`` resolves by slot rank, tie
      by item id: "OT" < "TT", so OT is inner -> own [OT]. Before A200 (commit 104171a41, ``LAYER_RANK`` only: top and top are rank 1)
      TT draped over nothing.
    * UT: under nothing -> [], [].
[2] ``garment_template.key_for`` of JT folds in the fit file of every own-mesh piece under it: the tsig changes when
    OT's fit bytes change (b"top-1" -> b"top-2") and when B gets its first fit (None -> a file); it does not change
    when the same bytes are written again. TT's tsig moves with OT's fit too (OT is under TT, [1]); UT's does
    not (nothing is under UT).
[3] ``garment_assembly._uppers`` over the grafted JT, TT, OT, B: OT -> [JT, TT], B -> [JT], TT -> [JT] (template
    over template by the stack AND by rank) — the faces of OT / B / TT under JT are hidden like A192's own-mesh layers.
[4] ``garment_layers._mesh_prim`` / ``_prim_mesh`` carry the morph targets through a cut: a strip of two quads at
    y = 0, 1, 2 (x = 0, 1), one target whose delta is (0, y, 0); ``plane_cut`` at y = 0.25 keeps y >= 0.25: the new
    vertices at y = 0.25 have delta 0.25 (the lerp of 0 and 1), the kept ones 1 and 2. Before A200 (104171a41) the
    round trip dropped the targets (``targets=[]``) and the result kept the input's longer target array.
[5] ``garment_assembly._into_shoe`` of a template piece (one target of delta (0, 0, 0.01) everywhere) on a CLOSED
    cut (``apply_cut`` stubbed to return the piece unchanged): vertex 0 has LeftFoot weight 1 -> delta 0, vertex 1
    LeftFoot 0.6 + LeftLeg 0.4 -> 0.4 x 0.01 = 0.004, vertex 2 LeftLeg 1 -> 0.01, vertex 3 RightToeBase 0.25 +
    RightLeg 0.75 -> 0.0075; ``shapes_damped`` = 3. On an OPEN cut (a sandal: the bare foot shows) nothing is
    damped. Before A200 (104171a41) a piece with targets was refused (None).
[6] ``garment_assembly._state``: a template piece worn on ``legs`` with a shoe in the set carries
    ``into_shoe`` = ``INTO_SHOE_VERSION`` (1); without a shoe, or an own-mesh legs piece, it does not.
[7] Fallback (``garment_template.drape_with_fallback``, coordinator ruling): drapes D (one template drape) and own O
    (one own-mesh fit). A fake ``run`` answers per attempt:
    * full passes -> mode "full", one call, colliders [D, O], offsets [0, 0].
    * full fails ``stretch_max`` (8.08), shrunk passes -> mode "shrunk"; the second call has offsets [0, -0.008]
      (``INNER_SHRINK_M``, own only); failed = [{mode full, stretch_max 8.08}].
    * full and shrunk fail (stretch / ``poke_share[rest]``) -> mode "dropped": third call colliders [D] alone,
      offsets None; two failed entries.
    * full fails ``build_wall_s`` only -> no fallback: mode "full", one call (the wall is load, not the colliders).
    * no own pieces -> one call with [D], offsets None, mode "full".
    ``_build_drape`` with that third answer writes ``inner_collider`` {mode dropped, failed 2} into the accepted
    record and lists only D under ``colliders``; ``piece_progress`` hands it to the dialog.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="smoke_a200_")
paths.init(TMP)

from app.core import (body_slots, footwear_cut, garment_assembly, garment_layers, garment_store,  # noqa: E402
                      garment_template)
from app.core.glb_mesh import GarmentMesh  # noqa: E402
from app.models import inventory  # noqa: E402

PRE_FIX = "104171a41"
FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got}" + ("" if ok else f" — expected {want}"))
    if not ok:
        FAILS.append(label)


def piece(name, slots, mode, covers=(), kind=None):
    p = {"slots": list(slots), "covers": list(covers), "partially_covers": [], "mesh_mode": mode}
    if kind:
        p["template"] = {"params": {**garment_template.kind_defaults(kind), "kind": kind}}
    return {"id": name, "name": name, "category": "outfit_piece", "outfit_piece": p}


ITEMS = {"JT": piece("JT", ["outer"], "template", kind="jacket"), "TT": piece("TT", ["top"], "template", kind="top"),
         "UT": piece("UT", ["underwear_top"], "template", kind="top"), "OT": piece("OT", ["top"], "own_mesh"),
         "B": piece("B", ["bottom"], "own_mesh", ["underwear_bottom"]), "S": piece("S", ["legs"], "shell"),
         "P": piece("P", ["feet"], "own_mesh")}
inventory.get_item = lambda item_id, *a, **k: ITEMS.get(str(item_id))
body_slots.piece_slots_for_character = lambda *a, **k: list(inventory.VALID_PIECE_SLOTS)
ALL = sorted(ITEMS)


def ids(pairs):
    return [i for i, _it in pairs]


# [1]
t, o = garment_template.inner_pieces("JT", "jacket", ALL)
check("[1] JT templates", ids(t), ["TT", "UT"])
check("[1] JT own", ids(o), ["B", "OT", "S"])
t, o = garment_template.inner_pieces("TT", "top", ALL)
check("[1] TT templates", ids(t), ["UT"])
check("[1] TT own", ids(o), ["OT"])
check("[1] UT", tuple(map(ids, garment_template.inner_pieces("UT", "top", ALL))), ([], []))
check("[1] collider_pieces = the templates", ids(garment_template.collider_pieces("JT", "jacket", ALL)), ["TT", "UT"])

# [2]
pic = Path(TMP) / "pic.png"
pic.write_bytes(b"picture")
garment_template.texture_sources = lambda c, i: {"front": str(pic), "back": str(pic), "source": "cutout"}
FITS = {"OT": Path(TMP) / "ot.glb", "B": None, "S": None}
FITS["OT"].write_bytes(b"top-1")
garment_store.accepted_fit = lambda c, item, **k: (FITS[item], {}) if FITS.get(item) else None
k1 = garment_template.key_for("c", "JT", base_sha="base", lower=ALL)[0]
tt1 = garment_template.key_for("c", "TT", base_sha="base", lower=ALL)[0]
ut1 = garment_template.key_for("c", "UT", base_sha="base", lower=ALL)[0]
FITS["OT"].write_bytes(b"top-2")
k2 = garment_template.key_for("c", "JT", base_sha="base", lower=ALL)[0]
tt2 = garment_template.key_for("c", "TT", base_sha="base", lower=ALL)[0]
ut2 = garment_template.key_for("c", "UT", base_sha="base", lower=ALL)[0]
check("[2] OT's fit changed -> JT re-drapes", k1 != k2, True)
check("[2] ... and TT", tt1 != tt2, True)
check("[2] ... UT does not", ut1 == ut2, True)
FITS["OT"].write_bytes(b"top-2")
check("[2] same bytes again -> same key", garment_template.key_for("c", "JT", base_sha="base", lower=ALL)[0], k2)
FITS["B"] = Path(TMP) / "b.glb"
FITS["B"].write_bytes(b"jeans")
check("[2] B fitted -> JT re-drapes", garment_template.key_for("c", "JT", base_sha="base", lower=ALL)[0] != k2, True)
check("[2] own colliders of JT", [(i, p.name if p else None) for i, p in
                                  garment_template.own_colliders("c", "JT", "jacket", ALL, base_sha="base")],
      [("B", "b.glb"), ("OT", "ot.glb"), ("S", None)])


# [3]
def g(item_id, kind_param=None):
    out = {"item_id": item_id, "kind": "clothing", "item": ITEMS[item_id], "fit": Path("x"), "record": {}}
    if kind_param:
        out.update(template=True, record={"params": {"kind": kind_param}})
    return out


ups = garment_assembly._uppers([g("JT", "jacket"), g("TT", "top"), g("OT"), g("B")])
check("[3] uppers", {k: [u["item_id"] for u in v] for k, v in ups.items() if v},
      {"OT": ["JT", "TT"], "B": ["JT"], "TT": ["JT"]})


# [4]
def strip(target_fn):
    P = np.array([[x, y, 0.0] for y in (0.0, 1.0, 2.0) for x in (0.0, 1.0)])
    F = np.array([[0, 1, 3], [0, 3, 2], [2, 3, 5], [2, 5, 4]], np.int64)
    n = len(P)
    return GarmentMesh(positions=P, normals=np.tile([0.0, 0.0, 1.0], (n, 1)), uvs=np.zeros((n, 2)),
                       indices=F.ravel(), joints=np.zeros((n, 4), np.int64), weights=np.tile([1.0, 0, 0, 0], (n, 1)),
                       joint_names=["mixamorig:Hips"], targets=[target_fn(P)], target_names=["t"])


def cut_targets(gl):
    m = strip(lambda P: np.c_[np.zeros(len(P)), P[:, 1], np.zeros(len(P))])
    prim, _st = footwear_cut.plane_cut(gl._mesh_prim(m), y_m=0.25)
    out = gl._prim_mesh(prim, m)
    return {round(float(y), 3): round(float(d[1]), 3) for y, d in zip(out.positions[:, 1], out.targets[0])} \
        if len(out.targets[0]) == len(out.positions) else f"{len(out.targets[0])} deltas for {len(out.positions)}"


check("[4] targets through plane_cut", cut_targets(garment_layers), {0.25: 0.25, 1.0: 1.0, 2.0: 2.0})


def old_module(rel, name):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PRE_FIX}:{rel}"], capture_output=True, text=True)
    if src.returncode:
        return None
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / rel)
    exec(compile(src.stdout, rel, "exec"), mod.__dict__)
    return mod


old_layers = old_module("app/core/garment_layers.py", "old_garment_layers")
if old_layers is not None:
    m = strip(lambda P: np.c_[np.zeros(len(P)), P[:, 1], np.zeros(len(P))])
    prim, _st = footwear_cut.plane_cut(old_layers._mesh_prim(m), y_m=0.25)
    check(f"[4] {PRE_FIX}: the round trip carries no target", len(prim.targets), 0)


old_template = old_module("app/core/garment_template.py", "old_garment_template")
if old_template is not None:
    check(f"[1] {PRE_FIX}: TT over nothing", ids(old_template.collider_pieces("TT", "top", ALL)), [])
    check(f"[1] {PRE_FIX}: no own-mesh collider", hasattr(old_template, "own_colliders"), False)


# [5]
def shoe_piece():
    n = 4
    P = np.array([[0, 0.05, 0], [0, 0.1, 0], [0, 0.4, 0], [0.2, 0.05, 0]], np.float64)
    names = ["mixamorig:LeftFoot", "mixamorig:LeftLeg", "mixamorig:RightToeBase", "mixamorig:RightLeg"]
    J = np.array([[0, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0], [2, 3, 0, 0]], np.int64)
    W = np.array([[1, 0, 0, 0], [0.6, 0.4, 0, 0], [1, 0, 0, 0], [0.25, 0.75, 0, 0]], np.float64)
    return GarmentMesh(positions=P, normals=np.tile([0.0, 0.0, 1.0], (n, 1)), uvs=np.zeros((n, 2)),
                       indices=np.array([0, 1, 2, 1, 3, 2], np.int64), joints=J, weights=W, joint_names=names,
                       targets=[np.tile([0.0, 0.0, 0.01], (n, 1))], target_names=["t"])


HOSE = {"item_id": "H", "item": piece("H", ["legs"], "template", kind="skirt")}
SHOE = {"item_id": "P", "record": {"cut": {"sides": {}}}}
footwear_cut.apply_cut = lambda prim, cut, joints: (prim, {"removed_faces": 0, "bisected_faces": 0,
                                                           "new_vertices": 0})
garment_assembly_glb = sys.modules["app.core.glb_mesh"]
garment_assembly_glb.joint_bind_matrices = lambda blob: {}
footwear_cut.is_open = lambda cut: False
taken = garment_assembly._into_shoe(shoe_piece(), HOSE, SHOE, b"")
check("[5] closed shoe: deltas z", None if taken is None else [round(float(z), 6) for z in taken[0].targets[0][:, 2]],
      [0.0, 0.004, 0.01, 0.0075])
check("[5] shapes_damped", None if taken is None else taken[1].get("shapes_damped"), 3)
footwear_cut.is_open = lambda cut: True
taken = garment_assembly._into_shoe(shoe_piece(), HOSE, SHOE, b"")
check("[5] open shoe: nothing damped", None if taken is None else
      ([round(float(z), 6) for z in taken[0].targets[0][:, 2]], "shapes_damped" in taken[1]), ([0.01] * 4, False))
src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PRE_FIX}:app/core/garment_assembly.py"],
                     capture_output=True, text=True).stdout
check(f"[5] {PRE_FIX} refused a piece with targets", "mesh.targets or mesh.extra_attributes" in src, True)

# [6]
fit = Path(TMP) / "f.glb"
fit.write_bytes(b"f")
garment_assembly._material = lambda gm: ("m", None)
hose = {"item_id": "H", "kind": "clothing", "fsig": "s", "fit": fit, "low": None, "template": True,
        "item": HOSE["item"]}
shoe = {"item_id": "P", "kind": "footwear", "fsig": "p", "fit": fit, "low": None, "item": ITEMS["P"]}
own = {**hose, "item_id": "S", "template": False, "item": ITEMS["S"]}
st = garment_assembly._state([hose, shoe, own], "full")
check("[6] template legs + shoe", st["H"].get("into_shoe"), garment_assembly.INTO_SHOE_VERSION)
check("[6] INTO_SHOE_VERSION", garment_assembly.INTO_SHOE_VERSION, 1)
check("[6] own-mesh legs piece", "into_shoe" in st["S"], False)
check("[6] no shoe", "into_shoe" in garment_assembly._state([hose], "full")["H"], False)

# [7]
def fake(answers):
    calls = []

    def run(cols, offsets, sub):
        calls.append((sub, [str(c[0]) for c in cols], offsets))
        bad = answers[len(calls) - 1]
        rows = [{"check": bad, "value": 8.08, "ok": False, "gate": True}] if bad else []
        return {"ok": not bad, "error": f"{bad} 8.08" if bad else "", "rows": rows,
                "data": {"drape": {"stretch_max": 8.08 if bad == "stretch_max" else 1.1}}, "glb": None}
    return run, calls


DR, OW = [(Path("D"), {})], [(Path("O"), None)]
run, calls = fake([None])
_r, inner = garment_template.drape_with_fallback(run, DR, OW)
check("[7] full passes", (inner["mode"], calls), ("full", [("full", ["D", "O"], [0.0, 0.0])]))
run, calls = fake(["stretch_max", None])
_r, inner = garment_template.drape_with_fallback(run, DR, OW)
check("[7] shrunk", (inner["mode"], calls[1][2], [(f["mode"], f["stretch_max"]) for f in inner["failed"]]),
      ("shrunk", [0.0, -0.008], [("full", 8.08)]))
run, calls = fake(["stretch_max", "poke_share[rest]", None])
_r, inner = garment_template.drape_with_fallback(run, DR, OW)
check("[7] dropped", (inner["mode"], calls[2], len(inner["failed"])), ("dropped", ("dropped", ["D"], None), 2))
run, calls = fake(["build_wall_s"])
_r, inner = garment_template.drape_with_fallback(run, DR, OW)
check("[7] wall only: no fallback", (inner["mode"], len(calls)), ("full", 1))
run, calls = fake([None])
_r, inner = garment_template.drape_with_fallback(run, DR, [])
check("[7] no own pieces", (inner["mode"], calls), ("full", [("full", ["D"], None)]))
check("[7] INNER_SHRINK_M", garment_template.INNER_SHRINK_M, -0.008)

# [7] the record
WROTE = {}
glb = Path(TMP) / "drape.glb"
answers = iter(["stretch_max", "poke_share[rest]", None])


def fake_run_drape(body, params, sources, *, out_dir, lower, lower_offsets, **k):
    bad = next(answers)
    out = Path(TMP) / "d.glb"
    out.write_bytes(b"drape")
    rows = [{"check": bad, "value": 9, "ok": False, "gate": True}] if bad else []
    return {"ok": not bad, "error": bad or "", "rows": rows, "data": {"drape": {}}, "glb": None if bad else out}


garment_template.run_drape = fake_run_drape
garment_template.collider_pieces = lambda *a, **k: [("TT", ITEMS["TT"])]
garment_template.build = lambda *a, **k: {"state": "ready", "path": Path("D.glb"), "record": {"pose_shapes": {}}}
garment_template.own_colliders = lambda *a, **k: [("OT", Path("O.glb"))]
garment_template.templates_dir = lambda c: Path(TMP) / "templates"
garment_template.drape_state = lambda *a, **k: {"state": "ready"}
import app.core.garment_store as gs  # noqa: E402
gs.write_record = lambda path, rec: WROTE.__setitem__(Path(path).name, rec)
import app.core.figure as fig  # noqa: E402
fig.invalidate = lambda *a, **k: None
garment_template._build_drape("c", "JT", key=("c", "JT"), profile={}, base=("b0", "sha"), base_sha="sha",
                              lower=ALL, item=ITEMS["JT"], sig="sig1", sources={}, body=Path("body.glb"),
                              params=garment_template.params_of(ITEMS["JT"]))
rec = WROTE.get("JT_sig1.json") or next(iter(WROTE.values()), {})
check("[7] record accepted", rec.get("accepted"), True)
check("[7] record inner_collider", ((rec.get("inner_collider") or {}).get("mode"),
                                    len((rec.get("inner_collider") or {}).get("failed") or [])), ("dropped", 2))
check("[7] record colliders", rec.get("colliders"), ["D.glb"])

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
