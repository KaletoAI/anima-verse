"""A223 — a strapless dress's top edge lies STRAPLESS_UNDERARM_M (2 cm) under the chest band, like the A221 top.

No server, no world DB, no Blender. Usage: ./.venv/bin/python scripts/smoke_strapless_dress_a223.py

By hand on the synthetic measure (waist_y 1.05, band_y 1.275): the bodice = max(0.08, 1.275 - 0.02 - 1.05) = 0.205,
so top_y = 1.05 + 0.205 = 1.255 (was 1.275 before A223). Only strapless dresses are re-keyed: their tsig carries
``strapless_top_m`` 0.02; a dress with straps keeps exactly the key it had (md5 of the old payload), and so does
a skirt. Measured on a copy of Lirien's body (medium, fit 0.3, length 0.6): stretch 1.503 before, 1.156 after.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import garment_template as gt  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


M = {"height": 1.70, "floor_y": 0.0, "waist_y": 1.05, "waist_c": 0.70, "hip_y": 0.90, "hip_c": 0.96,
     "band_y": 1.275, "band_c": 0.86, "shoulder_y": 1.40, "shoulder_w": 0.40, "neck_y": 1.47, "neck_c": 0.33}
dress = gt.validate_params({"kind": "dress", "shoulders": "strapless", "waist_height": "natural"})[0]
o = gt.outline(dress, M)
check("strapless dress top_y 1.255", abs(o["top_y"] - 1.255) < 1e-4, o["top_y"])


def old_key(params, **kw):
    params = {k: v for k, v in params.items() if k not in gt.MATERIAL_ONLY}
    if params.get("fabric") in gt.DRAPE_FABRIC:
        params["fabric"] = gt.DRAPE_FABRIC[params["fabric"]]
    return gt._md5({"params": params, "version": gt.template_version(params), "base": kw["base_sha"],
                    "texture": kw["texture_sha"], "lower": sorted(kw["lower"])})


kw = {"base_sha": "b", "texture_sha": "t", "lower": []}
check("strapless dress re-keyed", gt.tsig(dress, **kw) != old_key(dress, **kw))
straps = gt.validate_params({"kind": "dress", "shoulders": "straps"})[0]
check("dress with straps keeps its key", gt.tsig(straps, **kw) == old_key(straps, **kw))
skirt = gt.validate_params({"kind": "skirt"})[0]
check("skirt keeps its key", gt.tsig(skirt, **kw) == old_key(skirt, **kw))

print()
print("all checks passed" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
