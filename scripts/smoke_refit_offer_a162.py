"""Ruling A162 — a refused refit is an offer, a refused shoe can be accepted, the base-to-base frame may scale.

Usage: ./.venv/bin/python scripts/smoke_refit_offer_a162.py   (no server, no world DB, no backend, no job)

Hand-derived numbers.

[1] ``garment_source.register_frames`` with its own scale caps (``FRAME_SCALE_MIN`` 0.80 .. ``_MAX`` 1.25).
    A figure of height H on a 1536 x 800 canvas, centred (top at row 768 - 0.55 H, so the scale about the mask
    centre moves nothing), centre column 400: a head disc of radius 0.06 H centred 0.06 H below the top, a torso
    block 0.30 H wide from 0.12 H down to H. The target has H = 1000; the
    source draws the SAME figure with H = 1000 / 0.92 = 1087 px (a base front framed 8 % larger, Ylva's case:
    1446 -> 1332 px = 0.921). The registration lays source onto target: scale 1000 / 1087 = 0.920 (± 0.01), the
    residual small -> accepted (the ghost caps 0.93 .. 1.07 used to refuse it). Source H = 1000 / 0.75 = 1333:
    scale 0.75 < 0.80 -> FrameRefused. Same H, 60 px lower (0.06 Hb > 0.04): FrameRefused by the shift cap.
[2] ``garment_footwear._fit_attempt`` on a fit refused by its OWN gates (lift_asymmetry_mm 15.74 > 10, Vallerie's
    Woman shoes): with the insole the fit is cut (cut stubbed: description {"v": 1}, the cut keeps each primitive,
    the cut gates pass) -> ok False, reasons [the lift reason] only, ``replaced`` present (an attempt GLB can be
    kept and accepted), the result stays refused (ok False) and carries the cut. Cut gates refusing too
    (visible_poke 0.0086 > 0.005) -> both reasons, lift first. Without the insole (the old call) or when the cut
    cannot be described -> no ``replaced``, as before.
    Measured on copies 2026-11-16 (fit_compute on Vallerie's prepared shoe + base128a6534, Auto allowance): before
    A162 ``attempt.glb_sha256`` null (nothing to accept); now an attempt of 240368 tris, reasons lift_asymmetry_mm
    15.74 > 10; visible_poke 0.008591 > 0.005. The allowance (width / length) never enters the lift difference of
    the two sides (15.74 at Auto, 15.78 at the user's setting) — so it could not help; Accept anyway is the way.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_a162_")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402
paths.init(_tmp)

import numpy as np  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else f": {got!r} — expected {want!r}"))
    if not ok:
        failures.append(name)


def figure(h: float, down: int = 0, canvas=(1536, 800), col: int = 400) -> np.ndarray:
    top = 768 - 0.55 * h + down
    rows, cols = np.mgrid[0:canvas[0], 0:canvas[1]]
    head = (rows - (top + 0.06 * h)) ** 2 + (cols - col) ** 2 <= (0.06 * h) ** 2
    torso = (rows >= top + 0.12 * h) & (rows <= top + h) & (np.abs(cols - col) <= 0.15 * h)
    return head | torso


print("[1] the base-to-base frame registration")
from app.core import garment_source  # noqa: E402
target = figure(1000)
reg = garment_source.register_frames(figure(1000 / 0.92), target)
check("scale 0.92 accepted", abs(reg["scale"] - 0.92) <= 0.01, True)
check("within the frame caps", reg["within_caps"], True)
for name, mask in (("scale 0.75 refused", figure(1000 / 0.75)), ("shift 0.06 Hb refused", figure(1000, down=60))):
    try:
        garment_source.register_frames(mask, target)
        check(name, "accepted", "FrameRefused")
    except garment_source.FrameRefused:
        check(name, "FrameRefused", "FrameRefused")

print("[2] a shoe refused by its own gates is cut, so it can be accepted")
from app.core import footwear_cut, garment_footwear  # noqa: E402
LIFT = "lift_asymmetry_mm 15.74 > 10 (difference of the two sides' lifts)"
POKE = "visible_poke 0.008591 > 0.005 (share of the remaining foot vertices still below the upper's rim, worse side)"


def refused():
    record = {"sides": {"left": {}, "right": {}}, "gates": {"lift_asymmetry_mm": {"value": 15.74, "ok": False}},
              "diagnostics": {"left": {}, "right": {}}}
    return SimpleNamespace(ok=False, reasons=[LIFT], record=record, parts={"left": {}, "right": {}})


real = (footwear_cut.cut_description, footwear_cut.apply_cut, footwear_cut.cut_gates)
zero = {"removed_faces": 0, "bisected_faces": 0, "new_vertices": 0, "slim_share": {}, "slim_needed": {},
        "throat_moved": {}, "toe_conform": {}, "toe_pull": {}}
prim = SimpleNamespace(positions=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]), joints=np.zeros((3, 4)),
                       weights=np.zeros((3, 4)), joint_names=[])
try:
    footwear_cut.cut_description = lambda fit, insole: {"v": 1}
    footwear_cut.apply_cut = lambda p, cut, joints: (p, dict(zero))
    footwear_cut.cut_gates = lambda *a, **k: {"ok": True, "gates": {}, "sides": {}}
    r = refused()
    att = garment_footwear._fit_attempt(r, [prim], {}, {"insole": True})
    check("refused, the lift reason only", (att["ok"], att["reasons"]), (False, [LIFT]))
    check("cut: an attempt mesh can be kept", ("replaced" in att, r.ok, r.record.get("cut")), (True, False, {"v": 1}))
    footwear_cut.cut_gates = lambda *a, **k: {"ok": False, "reasons": [POKE], "gates": {}, "sides": {}, "marks": {}}
    att = garment_footwear._fit_attempt(refused(), [prim], {}, {"insole": True})
    check("cut gates refuse too: both, lift first", (att["reasons"], "replaced" in att), ([LIFT, POKE], True))
    att = garment_footwear._fit_attempt(refused(), [prim], {})
    check("without the insole: as before", ("replaced" in att, att["reasons"]), (False, [LIFT]))

    def boom(fit, insole):
        raise ValueError("The fit has no sides to cut for")
    footwear_cut.cut_description = boom
    r = refused()
    att = garment_footwear._fit_attempt(r, [prim], {}, {"insole": True})
    check("not cuttable: as before", ("replaced" in att, att["reasons"], "cut" in r.record), (False, [LIFT], False))
finally:
    footwear_cut.cut_description, footwear_cut.apply_cut, footwear_cut.cut_gates = real

print("FAILED (%d): %s" % (len(failures), ", ".join(failures)) if failures else "ALL OK")
sys.exit(1 if failures else 0)
