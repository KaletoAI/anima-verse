"""A191 — the Details previews of a whole boot show the body's leg cut inside it, as the figure's assembly does.

Usage: ./.venv/bin/python scripts/smoke_fit_preview_leg_cut.py   (no server, no world DB)

Cause (A191, Glut's Aschestiefel): A182 cuts the leg off only in the figure's assembly; the piece dialog's 3D
previews (``…/garments/{item}/model`` and ``…/fits/{body}/model``) served the stored fit GLB, whose body stays
whole. So after Shaft = "Whole boot over cut leg" the dialog still showed the full leg through the boot's holes,
and as the fit was already made with it nothing was due — no Re-fit was offered. On the copy of Glut's boot fit
(71a921e3cf7c) the preview now drops 14,416 of 132,538 body faces — the same 7,036 + 7,380 the assembly drops.

Expected values derived by hand:
[L1] ``leg_cuts_of_file``: a fit record beside the GLB with report.shaft {mode "whole", sides left body_cut_y_m
     0.505, right 0.499} -> {"left": 0.505, "right": 0.499}; mode "split" -> None; no record -> None; None -> None.
[L2] ``with_leg_cut``: no cuts -> the same bytes; cuts -> body primitives through ``garment_assembly.cut_legs`` and
     ``glb_mesh.rewrite_body_primitives`` (faked here: the fake cut drops face 1 of [[0,1,2],[2,3,0]] -> [[0,1,2]]);
     a cut that removes nothing -> the same bytes; a failing cut -> the same bytes (the preview never fails).
[L3] the wiring: both preview routes call ``with_leg_cut`` and name ``LEG_CUT_TOKEN`` in their version/ETag; both
     URL builders (``fit_attempts`` body entries, ``garments`` preview_url) append ``LEG_CUT_TOKEN`` — a browser
     that cached the uncut preview as immutable must get a new URL. The FitSettings panel offers its Re-fit also
     when nothing is due (a fit exists, not opened from the Figure tab).
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_a191_legcut_"))
import numpy as np  # noqa: E402

from app.core import fit_attempts, garment_assembly, glb_mesh  # noqa: E402

failed = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: got {got!r} want {want!r}")
    if not ok:
        failed.append(name)


# [L1]
tmp = Path(tempfile.mkdtemp(prefix="a191_"))
fit = tmp / "item_x_abc.glb"
fit.write_bytes(b"glb")
whole = {"report": {"shaft": {"mode": "whole", "sides": {"left": {"body_cut_y_m": 0.505},
                                                         "right": {"body_cut_y_m": 0.499}}}}}
fit.with_suffix(".json").write_text(json.dumps(whole))
check("L1 whole", fit_attempts.leg_cuts_of_file(fit), {"left": 0.505, "right": 0.499})
split = {"report": {"shaft": {"mode": "split", "sides": {"left": {"body_cut_y_m": 0.505}}}}}
fit.with_suffix(".json").write_text(json.dumps(split))
check("L1 split", fit_attempts.leg_cuts_of_file(fit), None)
check("L1 no record", fit_attempts.leg_cuts_of_file(tmp / "other.glb"), None)
check("L1 None", fit_attempts.leg_cuts_of_file(None), None)

# [L2]
blob = b"original"
check("L2 no cuts", fit_attempts.with_leg_cut(blob, None) is blob, True)


class FakePrim:
    faces = np.array([[0, 1, 2], [2, 3, 0]])


seen = {}
orig = (glb_mesh.body_primitive_arrays, glb_mesh.rewrite_body_primitives, garment_assembly.cut_legs)
glb_mesh.body_primitive_arrays = lambda b: [FakePrim()]


def fake_cut(prims, cuts):
    seen["cuts"] = cuts
    return {0: type("P", (), {"faces": prims[0].faces[:1]})()}, {}


def fake_rewrite(b, replaced):
    seen["faces"] = replaced[0].faces.tolist()
    return b"cut"


garment_assembly.cut_legs, glb_mesh.rewrite_body_primitives = fake_cut, fake_rewrite
check("L2 cut applied", fit_attempts.with_leg_cut(blob, {"left": 0.5}), b"cut")
check("L2 cut heights passed", seen.get("cuts"), {"left": 0.5})
check("L2 faces left", seen.get("faces"), [[0, 1, 2]])
garment_assembly.cut_legs = lambda prims, cuts: ({}, {})
check("L2 nothing removed", fit_attempts.with_leg_cut(blob, {"left": 0.5}) is blob, True)


def boom(prims, cuts):
    raise RuntimeError("x")


garment_assembly.cut_legs = boom
check("L2 failure keeps bytes", fit_attempts.with_leg_cut(blob, {"left": 0.5}) is blob, True)
glb_mesh.body_primitive_arrays, glb_mesh.rewrite_body_primitives, garment_assembly.cut_legs = orig

# [L3]
routes = (ROOT / "app/routes/characters.py").read_text(encoding="utf-8")
tree = ast.parse(routes)
fns = {n.name: ast.get_source_segment(routes, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
for name in ("get_character_garment_model", "get_character_garment_fit_model"):
    src = fns.get(name) or ""
    check(f"L3 {name} cuts", "with_leg_cut" in src and "LEG_CUT_TOKEN" in src, True)
fa = (ROOT / "app/core/fit_attempts.py").read_text(encoding="utf-8")
check("L3 body entry url token", "{LEG_CUT_TOKEN if leg_cuts_of_file(shown[0]) else ''}" in fa, True)
ga = (ROOT / "app/core/garments.py").read_text(encoding="utf-8")
check("L3 preview_url token", "(LEG_CUT_TOKEN if leg_cuts_of_file(preview) else \"\")" in ga, True)
fs = (ROOT / "frontend/src/tabs/characters/FitSettings.tsx").read_text(encoding="utf-8")
check("L3 Re-fit when nothing is due", "noRunAll || !info.recorded ? null" in fs, True)

print("FAILED: " + ", ".join(failed) if failed else "all passed")
sys.exit(1 if failed else 0)
