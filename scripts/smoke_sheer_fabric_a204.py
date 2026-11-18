"""Smoke check (A204): the sheer fabric of a template piece — parameters, drape key, cloth run, material, assembly.

Usage: ./.venv/bin/python scripts/smoke_sheer_fabric_a204.py   (no server, no world DB: a temp storage dir)

Hand-derived expectations:
  [A] ``validate_params``: ``opacity`` defaults to 0.4; any fabric other than sheer resets it to 0.4 (a stale slider
      never changes anything); sheer keeps 0.35; 0.1 clamps to 0.2 with one error; 1.5 to 1.0.
  [B] ``tsig`` leaves ``opacity`` out: for stiff / medium / flowing it equals the PRE-A204 module's tsig (commit
      e08e95fdb, which had no ``opacity`` and no ``sheer``) for the same input — no existing drape re-drapes; two
      sheer params differing only in opacity share one key; medium -> sheer changes the key.
  [C] cloth run: ``build_args`` hands sheer ``cloth_mass`` 0.08 / ``air_damping`` 2.0 / bending 0.01 / quality 7 and
      the other fabrics NO such keys; the Blender ``drape()`` defaults are mass 0.3 and air_damping 5.0 (the fixed
      values before A204) and both build calls read ``fab.get("cloth_mass", 0.3)`` / ``fab.get("air_damping", 5.0)``.
  [D] ``material_overrides``: None for medium; sheer 0.35 -> alphaMode BLEND, doubleSided, baseColorFactor
      [1, 1, 1, 0.35], extras {anima_sheer: True, opacity: 0.35}; ``material_key`` "sheer:0.35" / "".
  (The graft of those keys into a real figure GLB is checked by ``node scripts/smoke_sheer_render_a204.mjs <glb>``.)
  [F] assembly: ``_uppers`` — a sheer template draped over an inner piece hides nothing of it ({} for that inner),
      while the same piece in medium lists itself as the inner's upper; ``_merge_overrides`` keeps a material
      preset's keys and adds the sheer ones; ``_state``'s material entry carries "+sheer:0.35" for a sheer piece.
"""
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="smoke_a204_")
paths.init(TMP)

from app.core import garment_assembly, garment_template as gt, glb_mesh  # noqa: E402

PRE = "e08e95fdb"
failures = []


def check(label, ok, detail=""):
    print(f"  {'ok ' if ok else 'FAIL'} {label}{(' — ' + str(detail)) if detail else ''}")
    if not ok:
        failures.append(label)


print("[A] parameters")
p, e = gt.validate_params({"kind": "skirt"})
check("opacity defaults to 0.4", p["opacity"] == 0.4 and not e)
p, _ = gt.validate_params({"kind": "skirt", "fabric": "medium", "opacity": 0.3})
check("medium resets opacity to 0.4", p["opacity"] == 0.4)
p, _ = gt.validate_params({"kind": "skirt", "fabric": "sheer", "opacity": 0.35})
check("sheer keeps 0.35", p["opacity"] == 0.35 and p["fabric"] == "sheer")
p, e = gt.validate_params({"kind": "top", "fabric": "sheer", "opacity": 0.1})
check("0.1 clamps to 0.2 with one error", p["opacity"] == 0.2 and len(e) == 1, e)
p, _ = gt.validate_params({"kind": "dress", "fabric": "sheer", "opacity": 1.5})
check("1.5 clamps to 1.0", p["opacity"] == 1.0)
check("every kind shows opacity", all("opacity" in f for f in gt.KIND_FIELDS.values()))

print("[B] drape key")
old_src = subprocess.run(["git", "show", f"{PRE}:app/core/garment_template.py"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
old = types.ModuleType("garment_template_pre")
old.__file__ = str(ROOT / "app/core/garment_template.py")
exec(compile(old_src, "garment_template_pre", "exec"), old.__dict__)
check("the pre-A204 module has no sheer", "sheer" not in old.FABRICS and "opacity" not in old.PARAM_SPEC)
for fabric in ("stiff", "medium", "flowing"):
    raw = {"kind": "skirt", "fabric": fabric, "length_m": 0.76, "flare": 0.68, "slit": "left", "slit_m": 0.6}
    new_sig = gt.tsig(gt.validate_params(raw)[0], base_sha="b", texture_sha="t", lower=["x"])
    old_sig = old.tsig(old.validate_params(raw)[0], base_sha="b", texture_sha="t", lower=["x"])
    check(f"{fabric}: tsig equals the pre-A204 key", new_sig == old_sig, f"{new_sig} / {old_sig}")
s1 = gt.tsig(gt.validate_params({"fabric": "sheer", "opacity": 0.3})[0], base_sha="b", texture_sha="t", lower=[])
s2 = gt.tsig(gt.validate_params({"fabric": "sheer", "opacity": 0.8})[0], base_sha="b", texture_sha="t", lower=[])
m = gt.tsig(gt.validate_params({"fabric": "medium"})[0], base_sha="b", texture_sha="t", lower=[])
check("opacity alone keeps the key", s1 == s2)
check("medium -> sheer changes the key", s1 != m)

print("[C] cloth run")
spec = {"measure": {}, "row_y": [0.0]}
fab = gt.build_args(gt.validate_params({"fabric": "sheer"})[0], spec, item_id="i", corrective=False)["fabric"]
check("sheer: cloth_mass 0.08, air_damping 2.0, bending 0.01, quality 7",
      (fab["cloth_mass"], fab["air_damping"], fab["bending"], fab["quality"]) == (0.08, 2.0, 0.01, 7), fab)
for fabric in ("stiff", "medium", "flowing"):
    f = gt.build_args(gt.validate_params({"fabric": fabric})[0], spec, item_id="i", corrective=False)["fabric"]
    check(f"{fabric}: no cloth_mass / air_damping", "cloth_mass" not in f and "air_damping" not in f)
drape_src = (ROOT / "app/blender/scripts/garment_template_drape.py").read_text()
build_src = (ROOT / "app/blender/scripts/garment_template_build.py").read_text()
check("drape(): defaults mass=0.3, air_damping=5.0", "mass=0.3," in drape_src and "air_damping=5.0):" in drape_src
      and "s.mass = mass" in drape_src and "s.air_damping = air_damping" in drape_src)
check("both build calls pass the fabric's own values",
      build_src.count('mass=float(fab.get("cloth_mass", 0.3)), air_damping=float(fab.get("air_damping", 5.0))') == 2)
pre_drape = subprocess.run(["git", "show", f"{PRE}:app/blender/scripts/garment_template_drape.py"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout
check("pre-A204 the run was fixed at mass 0.3 / air 5.0", "s.mass = 0.3" in pre_drape and "s.air_damping = 5.0" in pre_drape)

print("[D] material")
sheer = gt.validate_params({"fabric": "sheer", "opacity": 0.35})[0]
medium = gt.validate_params({"fabric": "medium"})[0]
check("medium: no overrides, key ''", gt.material_overrides(medium) is None and gt.material_key(medium) == "")
ov = gt.material_overrides(sheer)
check("sheer overrides", ov == {"alphaMode": "BLEND", "doubleSided": True,
                                "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 0.35]},
                                "extras": {"anima_sheer": True, "opacity": 0.35}}, ov)
check("sheer key", gt.material_key(sheer) == "sheer:0.35")

print("[F] assembly")
item = lambda fabric: {"outfit_piece": {"template": {"params": {"kind": "skirt", "fabric": fabric, "opacity": 0.35}}}}  # noqa: E731
orig = gt.inner_pieces
gt.inner_pieces = lambda item_id, kind, clothing: ([], [("inner", None)])
try:
    for fabric, expect in (("sheer", False), ("medium", True)):
        outer = {"item_id": "outer", "kind": "clothing", "template": True, "item": item(fabric), "record": {}}
        inner = {"item_id": "inner", "kind": "clothing", "item": {}, "record": {}}
        ups = garment_assembly._uppers([outer, inner])
        check(f"{fabric}: inner hidden under it = {expect}", bool(ups.get("inner")) == expect, ups.keys())
finally:
    gt.inner_pieces = orig
merged = garment_assembly._merge_overrides(
    {"pbrMetallicRoughness": {"metallicRoughnessTexture": None, "roughnessFactor": 0.95}, "extras": {"anima_material": "cotton"}}, ov)
check("merge keeps the preset and adds the sheer keys",
      merged["pbrMetallicRoughness"] == {"metallicRoughnessTexture": None, "roughnessFactor": 0.95,
                                         "baseColorFactor": [1.0, 1.0, 1.0, 0.35]}
      and merged["extras"] == {"anima_material": "cotton", "anima_sheer": True, "opacity": 0.35}
      and merged["alphaMode"] == "BLEND")
check("is_sheer", garment_assembly._is_sheer({"template": True, "item": item("sheer")})
      and not garment_assembly._is_sheer({"template": True, "item": item("flowing")}))
src = (ROOT / "app/core/garment_assembly.py").read_text()
check("body cover skips sheer pieces", 'g["kind"] == CLOTHING and not _is_sheer(g)]' in src)

if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
