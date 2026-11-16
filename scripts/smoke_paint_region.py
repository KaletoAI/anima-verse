#!/usr/bin/env python3
"""Smoke: the paint region of a painted body (Ruling A127, app/core/paint_region.py).

Usage:  ./.venv/bin/python scripts/smoke_paint_region.py

No server, no world DB, no worker run. The storage root is a throwaway temp dir (set before any
app import).

Expected values, derived by hand from the rule "only the body regions of the worn PAINTED pieces'
slots may change; head, hands, feet, toes locked unless a slot names them":

[1] Slip only, {underwear_bottom: slip}, painted [slip] -> SLOT_REGIONS[underwear_bottom] = (hips,)
    -> {"version": 1, "regions": ["hips"], "margin_mm": 40}.
[2] Slip painted, blouse own mesh ({underwear_bottom: slip, top: blouse}, painted [slip]) -> the
    blouse's slot is not painted -> regions ["hips"], same as [1].
[3] One dress in two slots {top: dress, bottom: dress}, painted [dress] -> top (spine, shoulder,
    upper_arm, forearm) + bottom (hips, upper_leg, lower_leg), sorted: ["forearm", "hips",
    "lower_leg", "shoulder", "spine", "upper_arm", "upper_leg"] — no head, hand, foot, toe.
[4] Boots {feet: boots} -> ["foot", "lower_leg", "toe"]: the feet slot unlocks foot and toe.
[5] A species slot the table does not know {tail_sleeve: x} -> every region but head, hand,
    foot, toe: ["forearm", "hips", "lower_leg", "neck", "shoulder", "spine", "upper_arm",
    "upper_leg"].
[6] Nothing painted (painted []) -> None; empty pieces -> None.
[7] worker_arguments([1]) -> {"paint_region": ("hips",), "paint_region_margin_mm": 40.0};
    worker_arguments(None) -> {}.
[8] build_argv (python /py, glb /w/in.glb, front + back, rig /w/rig.glb, region ("hips",), margin
    40, body height 1620): the base argv, then "--paint-region", "hips", "--paint-region-margin-mm",
    "40.0", "--body-height-mm", "1620.0", "--arm-rig-glb", "/w/rig.glb". Without a region and
    without a side view: no "--arm-rig-glb". A region without a rig: ValueError.
[9] The region lists of paint_region and the core's locked set agree: LOCKED_REGIONS ⊂ BODY_REGIONS
    and every SLOT_REGIONS value ⊂ BODY_REGIONS.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TMP = Path(tempfile.mkdtemp(prefix="smoke-paint-region-"))
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["INSTANCE_DIR"] = str(_TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(str(_TMP / "storage"))

from app.core import body_retexture, paint_region as pr  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def region(regions):
    return {"version": 1, "regions": regions, "margin_mm": 40}


print("[1-6] regions of the painted slots")
check("[1] slip only", pr.paint_region({"underwear_bottom": "slip"}, ["slip"]), region(["hips"]))
check("[2] blouse own mesh", pr.paint_region({"underwear_bottom": "slip", "top": "blouse"}, ["slip"]),
      region(["hips"]))
check("[3] dress in two slots", pr.paint_region({"top": "dress", "bottom": "dress"}, ["dress"]),
      region(["forearm", "hips", "lower_leg", "shoulder", "spine", "upper_arm", "upper_leg"]))
check("[4] boots", pr.paint_region({"feet": "boots"}, ["boots"]), region(["foot", "lower_leg", "toe"]))
check("[5] unknown slot", pr.paint_region({"tail_sleeve": "x"}, ["x"]),
      region(["forearm", "hips", "lower_leg", "neck", "shoulder", "spine", "upper_arm", "upper_leg"]))
check("[6] nothing painted", pr.paint_region({"underwear_bottom": "slip"}, []), None)
check("[6] no pieces", pr.paint_region({}, ["slip"]), None)

print("[7] worker keywords")
check("[7] slip", pr.worker_arguments(region(["hips"])), {"paint_region": ("hips",), "paint_region_margin_mm": 40.0})
check("[7] none", pr.worker_arguments(None), {})

print("[8] worker argv")
w = Path("/w")
two = {"front": (w / "f.png", w / "rf.png"), "back": (w / "b.png", w / "rb.png")}
base = ["/py", "-m", "body_core", "--glb", "/w/in.glb", "--view", "front=/w/f.png,/w/rf.png",
        "--view", "back=/w/b.png,/w/rb.png", "--out", "/w/o.glb", "--proof", "/w/p.json", "--atlas", "/w/a.png"]
argv = body_retexture.build_argv(Path("/py"), w / "in.glb", two, w / "o.glb", w / "p.json", w / "a.png",
                                 arm_rig_glb=w / "rig.glb", paint_region=("hips",), paint_region_margin_mm=40,
                                 body_height_mm=1620)
check("[8] region flags", argv, base + ["--paint-region", "hips", "--paint-region-margin-mm", "40.0",
                                        "--body-height-mm", "1620.0", "--arm-rig-glb", "/w/rig.glb"])
check("[8] no region, no side view: no rig", body_retexture.build_argv(
    Path("/py"), w / "in.glb", two, w / "o.glb", w / "p.json", w / "a.png", arm_rig_glb=w / "rig.glb"), base)
try:
    body_retexture.build_argv(Path("/py"), w / "in.glb", two, w / "o.glb", w / "p.json", w / "a.png",
                              paint_region=("hips",))
    check("[8] region without rig refused", False, True)
except ValueError:
    check("[8] region without rig refused", True, True)

print("[9] tables")
check("[9] locked within regions", set(pr.LOCKED_REGIONS) <= set(pr.BODY_REGIONS), True)
check("[9] slot regions known", all(set(v) <= set(pr.BODY_REGIONS) for v in pr.SLOT_REGIONS.values()), True)

shutil.rmtree(_TMP, ignore_errors=True)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
