"""Smoke: A221 — the corset top: strapless or with straps, a straight or sweetheart top edge.

Usage:
    ./.venv/bin/python scripts/smoke_strapless_top_a221.py

No server, no world DB, no LLM, no Blender (``paths.init`` into a temp dir first). Every expected number is derived
here by hand from the constants of ``app/core/garment_template.py`` (BODICE_EASE (0.03, 0.17), EASE_M 0.02,
SHOULDER_TOP_M 0.045, STRAPLESS_UNDERARM_M 0.02, STRAPLESS_MIN_M 0.08, SWEETHEART_DIP_M 0.05, SWEETHEART_MAX_M 0.10,
SWEETHEART_HALF_RAD 0.5, COLS 41).

[1] validate_params:
    * {"kind": "top"} -> shoulders "covered" (a top keeps its bodice when the field is missing), neckline "crew".
    * top + strapless + neckline "v" + sleeves "long" -> neckline "straight", sleeves "none", neck_depth_m 0.
    * top + straps + sweetheart + neck_depth_m 0.3 -> kept, sleeves "none", neck_depth_m clamped to 0.10.
    * top + covered + sweetheart -> neckline "crew".  jacket + strapless -> "covered".
    * dress + strapless keeps "strapless" (unchanged behaviour).
[2] has_bodice: top/strapless False, top/straps False (round 2026-11-25: a strapped corset top is the strapless one's
    shell plus two straps, no bodice yoke), top/covered True, dress/strapless False, jacket True.
[3] the strapless outline on a box body: torso girth 0.80 at every height, band 1.30, shoulder joints 1.40,
    floor 0. fit 0: every knot 0.80 x (1 + 0.03 + 0) + 0.02 = 0.844. top_y = 1.30 - 0.02 = 1.28.
    length 0.5: hem = 1.40 + 0.045 - 0.5 = 0.945 -> length 1.28 - 0.945 = 0.335.
    length 0.15: hem 1.295 is above 1.28 - 0.08 = 1.20 -> hem 1.20, length 0.08.
    fit 1: knot 0.80 x 1.20 + 0.02 = 0.98.
[4] top_drop (sweetheart, strapless), column c at off = pi |c - 20| / 40 from the front centre:
    c 20 -> 0.05; c 22 -> off 0.15708, 0.05 x (1 - 0.31416)^2 = 0.02352; c 26 -> off 0.47124,
    0.05 x 0.05752^2 = 0.00017; c 27 -> off 0.54978 > 0.5 -> 0; c 0 -> 0. neck_depth_m 0.08 -> c 20 = 0.08.
    straight / covered -> None; round 2026-11-25: straps + sweetheart -> the same drop as strapless (c 20 0.05).
[5] bodice_spec of a top with straps + sweetheart: neckline built as "crew", top_edge {neckline "sweetheart",
    dip_m 0.05, half_rad 0.5}; straps + straight: dip_m 0.0; a covered top: top_edge None.
[6] the LLM template names the values: "strapless", "straps", "straight", "sweetheart".
[6b] the placket rule for a strapless top: its cut writes only the ``centre_back`` line (``corset_darts.back_line``),
    so the template says it laces only at the centre back and that a corset laced down the front is "none" — a
    front-laced corset must not get a code-painted lacing on its back.
[7] de.json translates "Sweetheart"; figureModel.ts labels "straight" / "sweetheart".
"""
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp())
from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def v(**kw):
    return gt.validate_params(kw)[0]


p = v(kind="top")
check("[1] top default covered/crew", p["shoulders"] == "covered" and p["neckline"] == "crew", str(p["shoulders"]))
p = v(kind="top", shoulders="strapless", neckline="v", sleeves="long")
check("[1] strapless top", (p["neckline"], p["sleeves"], p["neck_depth_m"]) == ("straight", "none", 0.0), str(p))
p = v(kind="top", shoulders="straps", neckline="sweetheart", neck_depth_m=0.3)
check("[1] straps sweetheart", (p["shoulders"], p["neckline"], p["sleeves"], p["neck_depth_m"])
      == ("straps", "sweetheart", "none", 0.1), str(p))
check("[1] covered sweetheart -> crew", v(kind="top", shoulders="covered", neckline="sweetheart")["neckline"] == "crew")
check("[1] jacket covered", v(kind="jacket", shoulders="strapless")["shoulders"] == "covered")
check("[1] dress strapless kept", v(kind="dress", shoulders="strapless")["shoulders"] == "strapless")

check("[2] has_bodice", [gt.has_bodice(v(kind=k, shoulders=s)) for k, s in
                         (("top", "strapless"), ("top", "straps"), ("top", "covered"), ("dress", "strapless"),
                          ("jacket", "strapless"))] == [False, False, True, False, True])

meas = {"band_y": 1.30, "shoulder_y": 1.40, "floor_y": 0.0, "waist_y": 1.05, "hip_y": 0.90, "waist_c": 0.7,
        "hip_c": 0.9, "band_c": 0.8, "torso": [[0.6, 0.8], [1.6, 0.8]]}


def close(a, b, tol=1e-3):
    return abs(a - b) <= tol


o = gt.outline(v(kind="top", shoulders="strapless", length_m=0.5, fit=0.0), meas)
check("[3] knots 0.844", all(close(c, 0.844) for _h, c in o["knots"]), str(o["knots"][:2]))
check("[3] top 1.28 length 0.335", close(o["top_y"], 1.28) and close(o["length"], 0.335), f'{o["top_y"]} {o["length"]}')
o = gt.outline(v(kind="top", shoulders="strapless", length_m=0.15, fit=0.0), meas)
check("[3] min length 0.08", close(o["length"], 0.08), str(o["length"]))
o = gt.outline(v(kind="top", shoulders="strapless", length_m=0.5, fit=1.0), meas)
check("[3] fit 1 -> 0.98", close(o["knots"][0][1], 0.98), str(o["knots"][0]))

d = gt.top_drop(v(kind="top", shoulders="strapless", neckline="sweetheart"), 41)
check("[4] sweetheart drop", d is not None and close(d[20], 0.05, 1e-5) and close(d[22], 0.02352, 1e-5)
      and close(d[26], 0.00017, 1e-5) and d[27] == 0.0 and d[0] == 0.0 and close(d[18], d[22], 1e-9), str(d and d[18:28]))
d = gt.top_drop(v(kind="top", shoulders="strapless", neckline="sweetheart", neck_depth_m=0.08), 41)
check("[4] depth 0.08", close(d[20], 0.08, 1e-5))
check("[4] None otherwise", all(gt.top_drop(v(kind="top", **kw), 41) is None for kw in
                                ({"shoulders": "strapless"}, {"shoulders": "covered"}, {"shoulders": "straps"})))
d = gt.top_drop(v(kind="top", shoulders="straps", neckline="sweetheart"), 41)
check("[4] straps + sweetheart: the strapless drop", d is not None and close(d[20], 0.05, 1e-5)
      and close(d[22], 0.02352, 1e-5) and d[27] == 0.0, str(d and d[18:28]))

bm = {**meas, "neck_c": 0.34, "neck_y": 1.45, "shoulder_w": 0.36, "arm_len": 0.5, "arm_c": [[0, 0.3], [1, 0.2]]}
b = gt.bodice_spec(v(kind="top", shoulders="straps", neckline="sweetheart"), bm)
check("[5] straps sweetheart edge", b["neckline"] == "crew" and b["top_edge"] == {"neckline": "sweetheart",
      "dip_m": 0.05, "half_rad": 0.5}, str(b["top_edge"]))
check("[5] straps straight dip 0", gt.bodice_spec(v(kind="top", shoulders="straps"), bm)["top_edge"]["dip_m"] == 0.0)
check("[5] covered none", gt.bodice_spec(v(kind="top"), bm)["top_edge"] is None)

md = (ROOT / "shared/templates/llm/tasks/garment_template_params.md").read_text()
check("[6] LLM template", all(f'"{w}"' in md for w in ("strapless", "straps", "straight", "sweetheart")))
check("[6b] strapless lacing", 'A "strapless" top laces only at the centre back' in md
      and '"none" for a bodice, bustier or corset laced down the front' in md and 'a corset laced down the front is "lacing"' not in md)
check("[7] de.json", '"Sweetheart":' in (ROOT / "shared/languages/de.json").read_text())
fm = (ROOT / "frontend/src/tabs/characters/figureModel.ts").read_text()
check("[7] labels", "sweetheart: 'Sweetheart'" in fm and "straight: 'Straight'" in fm)

print("\nall checks passed" if not FAILS else f"\nFAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
