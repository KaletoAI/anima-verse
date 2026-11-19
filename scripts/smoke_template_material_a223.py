"""A223 — a template piece's material preset survives its fabric; the template dialog shows the material select.

No server, no world DB. Usage: ./.venv/bin/python scripts/smoke_template_material_a223.py

Expected by hand (``piece_material.PRESETS["metal"]`` = roughness 0.3, metallic 1.0; ``garment_template.
material_overrides``: None for an opaque fabric, a BLEND layer for sheer, a fixed surface with metallic 0 for a
leather finish; ``garment_assembly._merge_overrides`` lays the template's keys over the preset's):
  metal + stiff / medium / flowing -> metallic 1.0, roughness 0.3 (the template adds nothing)
  metal + sheer                   -> metallic 1.0, roughness 0.3, alphaMode BLEND, base alpha 0.4 (opacity default)
  metal + leather_glossy / rough  -> metallic 0.0 (the finish wins, as the dialog's hint says)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import garment_assembly as ga, garment_template as gt, piece_material as pm  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


base = pm.overrides("metal")
for fab in ("stiff", "medium", "flowing"):
    m = ga._merge_overrides(base, gt.material_overrides(gt.validate_params({"kind": "bra", "fabric": fab})[0]))
    pbr = m["pbrMetallicRoughness"]
    check(f"metal + {fab}: metallic 1.0, roughness 0.3", (pbr["metallicFactor"], pbr["roughnessFactor"]) == (1.0, 0.3), m)
m = ga._merge_overrides(base, gt.material_overrides(gt.validate_params({"kind": "skirt", "fabric": "sheer"})[0]))
pbr = m["pbrMetallicRoughness"]
check("metal + sheer: still metal, blended at 0.4",
      pbr["metallicFactor"] == 1.0 and m["alphaMode"] == "BLEND" and pbr["baseColorFactor"][3] == 0.4, m)
for fab in ("leather_glossy", "leather_rough"):
    m = ga._merge_overrides(base, gt.material_overrides(gt.validate_params({"kind": "top", "fabric": fab})[0]))
    check(f"metal + {fab}: the finish wins (metallic 0)", m["pbrMetallicRoughness"]["metallicFactor"] == 0.0, m)

route = (ROOT / "app/routes/figure.py").read_text()
check("the dialog payload carries the material", '"material": piece_material.describe(item)' in route)
dlg = (ROOT / "frontend/src/tabs/characters/TemplateParamsDialog.tsx").read_text()
check("the dialog renders the material select beside the fabric",
      "<MaterialSelect itemId={itemId} material={data.material}" in dlg and "key === 'fabric' && data.material" in dlg)

print()
print("all checks passed" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
