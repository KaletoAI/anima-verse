"""Smoke check (A214): the two leather fabrics of a template piece — cloth preset, drape key, surface, due, UI.

Usage: ./.venv/bin/python scripts/smoke_leather_fabric_a214.py   (no server, no world DB: a temp storage dir)

Expected values, by hand:
  [A] cloth: Blender 5.2's shipped preset ``scripts/presets/cloth/Leather.py`` sets quality 15, mass 0.4,
      tension / compression / shear stiffness 80, bending 150, tension / compression / shear damping 25, air 1.
      Both ``leather_glossy`` and ``leather_rough`` carry exactly those (``cloth_mass`` 0.4, ``air_damping`` 1.0,
      ``structural_damping`` 25). ``build_args``: a skirt runs quality 15; a top (bodice x1.5) round(22.5) = 22.
      ``spring_kwargs``: leather -> {tension 80, compression 80, shear 80, structural_damping 25}; medium -> {}
      (``drape``'s defaults 15 / 15 / 5, Blender's default damping, as before A214).
  [B] drape key: glossy and rough share one ``tsig`` (``DRAPE_FABRIC`` -> "leather"); medium -> leather changes it;
      the key of stiff / medium / flowing / sheer equals the pre-A214 module's (commit 2a23beb00) — nothing re-drapes.
  [C] surface: glossy = roughness 0.38, metallic 0, generator map dropped, clear coat 0.35 / roughness 0.30 (round
      2026-11-25: was 0.2 under 1.0 / 0.08, a mirror coat), sheen removed (None); rough = roughness 0.85, metallic 0,
      sheen [0.25]*3 / 0.7, clear coat removed. Both ``explicit_metallic`` False. ``material_key``
      "leather_glossy.v2" / "leather_rough.v2" (``LEATHER_SURFACE_VERSION`` 2); medium "" (unchanged).
      Merged over the cotton preset (roughness 0.95 + sheen): roughness 0.38 wins, sheen None, so the graft drops it.
      A real ``glb_mesh.graft`` of the glossy keys writes KHR_materials_clearcoat into the material and extensionsUsed,
      no sheen.
  [D] due: the assembly state's ``material`` entry differs for medium / glossy / rough (a finish switch
      re-assembles); ``_is_sheer`` is False for both leathers (they hide the body under them).
  [E] UI: ``PARAM_SPEC["fabric"]`` choices (what the dialog's select lists) hold both; figureModel.ts labels
      "Leather (glossy)" / "Leather (rough)" with a note each; de.json "Leder glänzend" / "Leder rau".
  [F] wall: ``LEATHER_WALL`` 1.5 (measured 64.8 s / 46.3 s = 1.40 on Gelina's skirt, rounded up) -> 90 s for both;
      medium stays 60.
  [G] renderers: scene-render exports ``prepareGlossyPieces`` (glossy fabric list = ["leather_glossy"]).
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="smoke_a214_")
paths.init(TMP)

from app.core import garment_assembly, garment_template as gt  # noqa: E402

PRE = "2a23beb00"
failures = []


def check(label, ok, detail=""):
    print(f"  {'ok ' if ok else 'FAIL'} {label}{(' — ' + str(detail)) if detail else ''}")
    if not ok:
        failures.append(label)


LEATHERS = ("leather_glossy", "leather_rough")
print("[A] cloth")
want = {"bending": 150.0, "mass": 0.4, "quality": 15, "shrink": 0.0, "cloth_mass": 0.4, "air_damping": 1.0,
        "tension": 80.0, "compression": 80.0, "shear": 80.0, "structural_damping": 25.0}
for f in LEATHERS:
    check(f"{f}: Blender Leather preset", gt.FABRICS[f] == want, gt.FABRICS[f])
spec = {"measure": {}, "row_y": [0.0], "outline": []}
skirt = gt.build_args(gt.validate_params({"kind": "skirt", "fabric": "leather_rough"})[0], spec, item_id="i",
                      corrective=False)
check("skirt quality 15", skirt["fabric"]["quality"] == 15 and skirt["drape_quality"] == 15, skirt["drape_quality"])
top = gt.build_args(gt.validate_params({"kind": "top", "fabric": "leather_glossy"})[0], spec, item_id="i",
                    corrective=False)
check("top drape quality round(15 x 1.5) = 22", top["drape_quality"] == 22, top["drape_quality"])
src_drape = (ROOT / "app/blender/scripts/garment_template_drape.py").read_text()
ns: dict = {}
start = src_drape.index("def spring_kwargs(")
exec(src_drape[start:src_drape.index("\ndef drape(", start)], ns)
check("spring_kwargs leather", ns["spring_kwargs"](want) == {"tension": 80.0, "compression": 80.0, "shear": 80.0,
                                                             "structural_damping": 25.0})
check("spring_kwargs medium = {}", ns["spring_kwargs"](gt.FABRICS["medium"]) == {})
check("drape() defaults 15 / 15 / 5, damping untouched",
      "tension=15.0, compression=15.0, shear=5.0, structural_damping=None" in src_drape)
build_src = (ROOT / "app/blender/scripts/garment_template_build.py").read_text()
check("both build calls pass the springs", build_src.count("**gd.spring_kwargs(fab)") == 2)

print("[B] drape key")
key = lambda prm: gt.tsig(gt.validate_params(prm)[0], base_sha="b", texture_sha="t", lower=[])  # noqa: E731
g, r, m = (key({"kind": "skirt", "fabric": f}) for f in ("leather_glossy", "leather_rough", "medium"))
check("glossy and rough share one drape", g == r)
check("medium -> leather re-drapes", g != m)
old_src = subprocess.run(["git", "show", f"{PRE}:app/core/garment_template.py"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
old_path = Path(TMP) / "garment_template_pre_a214.py"
old_path.write_text(old_src)
old_spec = importlib.util.spec_from_file_location("garment_template_pre_a214", old_path)
old = importlib.util.module_from_spec(old_spec)
old_spec.loader.exec_module(old)
check("the pre-A214 module has no leather", not any(f.startswith("leather") for f in old.FABRICS))
for f in ("stiff", "medium", "flowing", "sheer"):
    prm = {"kind": "skirt", "fabric": f}
    check(f"{f}: key as before A214", key(prm) == old.tsig(old.validate_params(prm)[0], base_sha="b",
                                                           texture_sha="t", lower=[]))

print("[C] surface")
gl = gt.validate_params({"fabric": "leather_glossy"})[0]
ro = gt.validate_params({"fabric": "leather_rough"})[0]
ov_g, ov_r = gt.material_overrides(gl), gt.material_overrides(ro)
check("glossy overrides", ov_g == {
    "pbrMetallicRoughness": {"metallicRoughnessTexture": None, "roughnessFactor": 0.38, "metallicFactor": 0.0},
    "extensions": {"KHR_materials_clearcoat": {"clearcoatFactor": 0.35, "clearcoatRoughnessFactor": 0.3},
                   "KHR_materials_sheen": None},
    "extras": {"anima_material": "leather_glossy", "explicit_metallic": False}}, ov_g)
check("rough overrides", ov_r == {
    "pbrMetallicRoughness": {"metallicRoughnessTexture": None, "roughnessFactor": 0.85, "metallicFactor": 0.0},
    "extensions": {"KHR_materials_clearcoat": None,
                   "KHR_materials_sheen": {"sheenColorFactor": [0.25, 0.25, 0.25], "sheenRoughnessFactor": 0.7}},
    "extras": {"anima_material": "leather_rough", "explicit_metallic": False}}, ov_r)
check("material keys", gt.material_key(gl) == "leather_glossy.v2" and gt.material_key(ro) == "leather_rough.v2"
      and gt.material_key(gt.validate_params({"fabric": "medium"})[0]) == "")
from app.core import piece_material  # noqa: E402
merged = garment_assembly._merge_overrides(piece_material.overrides("cotton"), ov_g)
check("over cotton: roughness 0.38, sheen None, clear coat set",
      merged["pbrMetallicRoughness"]["roughnessFactor"] == 0.38 and merged["extensions"]["KHR_materials_sheen"] is None
      and merged["extensions"]["KHR_materials_clearcoat"]["clearcoatFactor"] == 0.35, merged)
from app.core import glb_mesh  # noqa: E402
material = {"pbrMetallicRoughness": {}, "extensions": {"KHR_materials_sheen": {"sheenRoughnessFactor": 0.9}}}
for k, v in merged.items():      # the graft's merge rule (``glb_mesh.graft``): a None sub value removes that key
    if k in glb_mesh._MERGED_MATERIAL_KEYS and isinstance(v, dict):
        cur = dict(material.get(k) or {})
        for sk, sv in v.items():
            cur.pop(sk, None) if sv is None else cur.__setitem__(sk, sv)
        material[k] = cur
check("graft rule: glossy material keeps the clear coat only",
      set(material["extensions"]) == {"KHR_materials_clearcoat"}, material["extensions"])

print("[D] due")
item = lambda f: {"outfit_piece": {"template": {"params": {"kind": "skirt", "fabric": f}}}}  # noqa: E731
keys = {f: garment_assembly._fabric_key({"template": True, "item": item(f)}) for f in ("medium", *LEATHERS)}
check("fabric part of the assembly state: '', glossy, rough", keys == {
    "medium": "", "leather_glossy": "leather_glossy.v2", "leather_rough": "leather_rough.v2"}, keys)
asm = (ROOT / "app/core/garment_assembly.py").read_text()
check("the state's material entry carries the fabric key", 'entry["material"] += "+" + fabric' in asm)
check("leather is not sheer", not any(garment_assembly._is_sheer({"template": True, "item": item(f)})
                                      for f in LEATHERS))

print("[E] UI")
check("dialog choices hold both", all(f in gt.PARAM_SPEC["fabric"][1] for f in LEATHERS), gt.PARAM_SPEC["fabric"][1])
fm = (ROOT / "frontend/src/tabs/characters/figureModel.ts").read_text()
check("labels", "leather_glossy: 'Leather (glossy)'" in fm and "leather_rough: 'Leather (rough)'" in fm)
check("notes", fm.count("Heavy and stiff: barely stretches") == 2)
de = json.loads((ROOT / "shared/languages/de.json").read_text())["translations"]
check("de.json", de.get("Leather (glossy)") == "Leder glänzend" and de.get("Leather (rough)") == "Leder rau")

print("[F] wall")
for f in LEATHERS:
    check(f"{f}: 90 s", gt.wall_limit({"fabric": f}) == 90.0, gt.wall_limit({"fabric": f}))
check("medium stays 60", gt.wall_limit({"fabric": "medium"}) == 60.0)

print("[G] renderers")
fig = (ROOT / "packages/scene-render/src/figure.ts").read_text()
check("scene-render: glossy list", "export const GLOSSY_FABRICS = ['leather_glossy']" in fig
      and "export function prepareGlossyPieces(" in fig)
check("scene-render index exports it", "prepareGlossyPieces" in (ROOT / "packages/scene-render/src/index.ts").read_text())

if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
