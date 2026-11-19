"""Smoke: A229 — the off-shoulder (Carmen / Bardot) top and dress: a covered bodice with sleeves cut below the
shoulders along a pinned elastic band, optional front lacing.

Usage:
    ./.venv/bin/python scripts/smoke_off_shoulder_a229.py

No server, no world DB, no LLM, no Blender (``paths.init`` into a temp dir first). Every expected number is derived
here by hand from the constants of ``app/core/garment_template.py`` (SHOULDER_TOP_M 0.045, OFF_SHOULDER_ARM_M 0.07,
LACE_GAP_M 0.03, the PARAM_SPEC defaults band_m 0.025, band_drop_m 0.05, lace_depth_m 0.15).

[1] validate_params:
    * top + off_shoulder, no sleeves given -> sleeves "short" (none / cap would be cut away with the shoulder);
      sleeves "cap" -> "short"; "long" kept; neckline "v" + depth 0.2 -> "crew", 0.0 (the band is the neckline).
    * lacing "none" + lace_depth_m 0.3 -> lace_depth_m back to 0.15; lacing "front" keeps 0.3.
    * band_m 0.2 -> clamped to 0.05 (one error).
    * a covered top given band_m 0.04 / lacing "front" -> band_m 0.025, lacing "none" (the defaults).
    * dress + off_shoulder + sleeves "elbow" -> kept (a dress's sleeves are no longer reset off the shoulders).
[2] has_bodice / has_sleeves True, corset_top False, off_shoulder True; a covered top: off_shoulder False.
[3] off_shoulder_spec on a body with shoulder joints at 1.40: line_y = 1.40 + 0.045 - 0.05 = 1.395;
    band_drop_m 0.08 -> 1.365; arm_out_m 0.07; lace {depth_m 0.2, gap_m 0.03} with lacing front, None without;
    bodice_spec carries it, a covered top's bodice_spec has off_shoulder None.
[4] tsig: a covered top keys the same with and without the off-shoulder fields in its params (the A229 fields
    never re-key an existing drape); two off-shoulder tops differing only in band_m key differently.
[5] the preview (garment_preview.shapes) on the A188 synthetic picture (200 px/m, feet row 380, centre column 100,
    x0 = 0): the body fill's top row = 380 - 1.395 x 200 = 101.0; the band edge runs from column
    100 - (0.18 + 0.07) x 200 = 50 to 150 on row 101; the dashed band 0.025 lower = row 106; with lacing 0.2 the
    lacing cut's bottom row = 380 - 1.195 x 200 = 141, its top half width 0.015 x 200 = 3 px (columns 97 / 103).
[6] the LLM template names "off_shoulder", "Carmen", "Bardot", "lacing"; de.json and figureModel.ts carry the labels.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="a229-smoke-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
import numpy as np  # noqa: E402

from app.core import garment_preview as gp  # noqa: E402
from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def v(**kw):
    return gt.validate_params(kw)[0]


def close(a, b, tol=1e-3):
    return abs(a - b) <= tol


OFF = {"kind": "top", "shoulders": "off_shoulder"}
check("[1] sleeves none -> short", v(**OFF)["sleeves"] == "short")
check("[1] cap -> short", v(**OFF, sleeves="cap")["sleeves"] == "short")
check("[1] long kept", v(**OFF, sleeves="long")["sleeves"] == "long")
p = v(**OFF, neckline="v", neck_depth_m=0.2)
check("[1] neckline crew 0", (p["neckline"], p["neck_depth_m"]) == ("crew", 0.0), str((p["neckline"], p["neck_depth_m"])))
check("[1] no lacing -> depth default", v(**OFF, lacing="none", lace_depth_m=0.3)["lace_depth_m"] == 0.15)
check("[1] lacing keeps depth", v(**OFF, lacing="front", lace_depth_m=0.3)["lace_depth_m"] == 0.3)
p, err = gt.validate_params({**OFF, "band_m": 0.2})
check("[1] band clamp", p["band_m"] == 0.05 and len(err) == 1, str(err))
p = v(kind="top", shoulders="covered", band_m=0.04, lacing="front")
check("[1] covered resets", (p["band_m"], p["lacing"]) == (0.025, "none"), str((p["band_m"], p["lacing"])))
check("[1] dress keeps sleeves", v(kind="dress", shoulders="off_shoulder", sleeves="elbow")["sleeves"] == "elbow")

p = v(**OFF, sleeves="long")
check("[2] predicates", gt.has_bodice(p) and gt.has_sleeves(p) and not gt.corset_top(p) and gt.off_shoulder(p)
      and not gt.off_shoulder(v(kind="top")))

meas = {"band_y": 1.30, "shoulder_y": 1.40, "floor_y": 0.0, "waist_y": 1.05, "hip_y": 0.90, "waist_c": 0.7,
        "hip_c": 0.9, "band_c": 0.8, "torso": [[0.6, 0.8], [1.6, 0.8]], "neck_c": 0.34, "neck_y": 1.45,
        "shoulder_w": 0.36, "arm_len": 0.5, "arm_c": [[0, 0.3], [1, 0.2]], "height": 1.70,
        "joints": {"hips": [0.0, 0.95, 0.0], "neck": [0.0, 1.45, 0.0]}}
o = gt.off_shoulder_spec(v(**OFF, lacing="front", lace_depth_m=0.2), meas)
check("[3] line 1.395", close(o["line_y"], 1.395, 1e-6) and o["arm_out_m"] == 0.07 and o["band_m"] == 0.025, str(o))
check("[3] lace", o["lace"] == {"depth_m": 0.2, "gap_m": 0.03}, str(o["lace"]))
check("[3] drop 0.08", close(gt.off_shoulder_spec(v(**OFF, band_drop_m=0.08), meas)["line_y"], 1.365, 1e-6))
check("[3] no lacing", gt.off_shoulder_spec(v(**OFF), meas)["lace"] is None)
check("[3] bodice_spec", gt.bodice_spec(v(**OFF), meas)["off_shoulder"] is not None
      and gt.bodice_spec(v(kind="top"), meas)["off_shoulder"] is None)

cov = v(kind="top")
bare = {k: x for k, x in cov.items() if k not in gt.OFF_SHOULDER_FIELDS}
sig = dict(base_sha="b", texture_sha="t", lower=[])
check("[4] covered key unchanged", gt.tsig(cov, **sig) == gt.tsig(bare, **sig))
check("[4] off-shoulder keyed", gt.tsig(v(**OFF), **sig) != gt.tsig(v(**OFF, band_m=0.03), **sig))

mask = np.zeros((400, 200), bool)
mask[40:240, 80:120] = True
mask[240:380, 70:90] = True
mask[240:380, 110:130] = True
reg = gp.register(gp.frame_of_mask(mask), meas)
out = gp.shapes(v(**OFF, lacing="front", lace_depth_m=0.2, length_m=0.55), meas, reg)
by = {}
for s in out["shapes"]:
    by.setdefault(s["role"], []).append(s)
body_top = min(q[1] for q in by["body"][0]["points"])
check("[5] body top row 101", close(body_top, 101.0, 0.11), str(body_top))
edge = by["band_edge"][0]["points"]
check("[5] band edge 50..150 row 101", close(edge[0][0], 50, 0.11) and close(edge[1][0], 150, 0.11)
      and close(edge[0][1], 101, 0.11), str(edge))
check("[5] band dash row 106", close(by["band"][0]["points"][0][1], 106, 0.11), str(by["band"][0]["points"]))
lace = by["lacing"][0]["points"]
check("[5] lacing", close(max(q[1] for q in lace), 141, 0.11) and close(lace[0][0], 97, 0.11)
      and close(lace[1][0], 103, 0.11), str(lace))

md = (ROOT / "shared/templates/llm/tasks/garment_template_params.md").read_text()
check("[6] LLM template", all(w in md for w in ('"off_shoulder"', "Carmen", "Bardot", '"lacing"', '"band_m"')))
de = (ROOT / "shared/languages/de.json").read_text()
check("[6] de.json", all(f'"{k}":' in de for k in ("Off the shoulders (Carmen)", "Elastic band height",
                                                    "Band below the shoulder line", "Lacing", "Lacing depth")))
fm = (ROOT / "frontend/src/tabs/characters/figureModel.ts").read_text()
check("[6] labels", "off_shoulder: 'Off the shoulders (Carmen)'" in fm and "OFF_SHOULDER_SLEEVES" in fm)

print("\nall checks passed" if not FAILS else f"\nFAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
