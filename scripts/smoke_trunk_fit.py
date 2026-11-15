#!/usr/bin/env python3
"""Ruling A83 — the trunk of a clothing piece laid onto the body: the fit setting ``trunk`` (Auto / As generated /
Fitted to the body), the Auto choice, the fitted move, its band from the narrowest waist up, the version rule that
keeps an unchanged fit current (app/core/garment_fit.py: ``fit_trunk``, ``trunk_weights``, ``trunk_waist``,
``auto_trunk``, ``trunk_reason_text``, ``trunk_choice``, ``place_trunk``, ``expected_fit_version``;
app/core/garment_fit_settings.py) on synthetic geometry — no world, no hub, no GLB.

Usage:
    ./.venv/bin/python scripts/smoke_trunk_fit.py

Expected numbers, derived by hand:

Body for [1]: a vertical cylinder of radius Rb = 0.12 about the y axis, its signed distance sqrt(x^2 + z^2) - Rb
sampled on a 5 mm grid (``Sdf``; trilinear sampling of that cone-like field is exact to ~0.03 mm at 15 cm from the
axis). The torso frame by hand: points (0, 0.95, 0) and (0, 1.45, 0), hip_y 0.95, neck_y 1.45 — the axis is the y
axis.
The piece: rings every 1 cm from y 1.00 to 1.30, 72 vertices each at t_j = 2 pi (j + 0.25) / 72 (a vertex never on a
bin edge of the 36 directions), x = r sin t, z = r cos t (the frame's angle 0 is +z).

[1] ``fit_trunk`` (TRUNK_FIT_CLEAR_M 0.012, TRUNK_FIT_SHEET_M 0.006, TRUNK_FIT_DETAIL 0.5):
    (a) one sheet with 4 cm of room (r = 0.16): every cell's median room is 0.04, the detail 0 -> target 0.012; with
        weight 1 each vertex ends at r = 0.132 (within 0.3 mm), its height and its angle kept (0.1 mm, 1e-3 rad);
        with weight 0.5 half way: r = 0.16 - 0.5 x 0.028 = 0.146; with weight 0 it does not move (D exactly 0).
    (b) two sheets at the same places, 3.6 and 4.0 cm of room: each cell holds as many of both -> median 0.038,
        detail -0.002 / +0.002, inside TRUNK_FIT_SHEET_M -> kept whole: targets 0.010 / 0.014 -> r 0.130 / 0.134, the
        sheets 4 mm apart and in their order (with the detail halved they would be 2 mm apart: 0.011 / 0.013).
    (c) two sheets with 2.4 and 4.0 cm: median 0.032, detail -0.008 / +0.008 -> 6 mm kept whole and half of the
        2 mm beyond: -0.007 / +0.007; the inner one floored at -0.5 x 0.012 = -0.006 -> targets 0.006 / 0.019 ->
        r 0.126 / 0.139.
[2] ``trunk_weights`` / ``trunk_waist``: the frame of [1] with a hand-made radius table — row i (v centre
    -0.59 + 0.02 i, TORSO_V) = 0.10 + |v_i - 0.29| in every direction. The waist search runs y 0.95 .. Spine2 1.30 in
    5 mm steps; v = (y - 0.95) / 0.50, so y 1.095 is v 0.29, a bin centre, where the mean radius is 0.10 and nowhere
    lower -> waist 1.095. The body's vertices span y 0 .. 1.70 (height 1.70), LeftArm at y 1.40, RightArm 1.42 ->
    top 1.40, full 1.40 - DEPTH_RAMP 0.03 x 1.70 = 1.349; low = 1.095 - TRUNK_FIT_BLEND_M 0.06 = 1.035.
    Weights (all weight off the arms): y 1.00 -> 0 (a peplum below the band stays free), 1.035 -> 0, 1.065 -> 0.5,
    1.095 -> 1, 1.20 -> 1, 1.3745 -> (1.40 - 1.3745) / 0.051 = 0.5, 1.40 -> 0; a vertex at 1.20 with 0.3 of its
    weight on LeftArm -> 0.7. Band {waist 1.095, low 1.035, top 1.40, full 1.349}.
[3] ``auto_trunk`` (TRUNK_AUTO_ROOM_M = TRUNK_AUTO_FRONT_M = 0.03) on the numbers measured 2026-11-15:
    Ylva's blouse room 0.0254 / front 0.0382 -> "fitted", why [{front, 3.8}] (the room 2.54 cm is not over 3);
    Kai's jacket 0.023 / 0.0196 -> "generated", why [{fits, 2.3, 2.0}]; room 0.031 / front 0.010 -> "fitted",
    [{room, 3.1}]; 0.03 / 0.03 exactly -> "generated" (over, not at); no numbers -> "generated", []. Reason texts:
    "Auto -> Fitted to the body: its front stands 3.8 cm off the body", "Auto -> As generated: the trunk sits 2.3 cm
    off the body, 2 cm in front — it keeps its volume".
    ``trunk_choice``: {} -> auto, {trunk: fitted} -> fitted, {trunk: wider} -> auto.
[4] ``place_trunk`` keeps a piece as generated ITSELF: a piece whose every vertex is carried by LeftArm has no trunk
    band (``trunk_band`` empty) -> no numbers -> Auto "generated", the very array object returned, nothing marked as
    fitted; the same with the fixed "generated".
[5] Fit settings: ``normalise`` gives ``trunk`` "auto" by default, keeps "fitted" / "generated", drops "wider";
    ``validate`` keeps trunk "fitted" and refuses "wider", True and 1; a record made before the trunk setting (no
    ``trunk`` key) under a profile without one is not due, under trunk "fitted" it is.
[6] Versions: FIT_VERSION clothing 16, CLOTHING_TRUNK_UNCHANGED 15. ``expected_fit_version`` of a clothing record
    of version 15 whose own metrics keep Auto as generated (Kira's blazer torso_gap 0.0138 / front 0.0126) -> 15 (it
    stays current); the blouse's (0.0232 / 0.0381) -> 16 (due); room 0.031 / front 0.010 -> 16; no metrics -> 15
    (nothing to lay on); version 14 -> 16; version 16 -> 16; a hair record -> FIT_VERSION hair 16.
[7] Fails on the old code: at commit ea25128b1 (Ruling A76, before A83) app/core/garment_fit.py has no
    ``place_trunk`` / ``TRUNK_CHOICES`` and FIT_VERSION clothing 15; garment_fit_settings.validate refuses the key
    ``trunk``.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILED = []
OLD = "ea25128b1"


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f" ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


RB = 0.12
FRAME = {"points": [[0.0, 0.95, 0.0], [0.0, 1.45, 0.0]], "hip_y": 0.95, "neck_y": 1.45, "kind": "torso"}


def cylinder_sdf(gf):
    vox = 0.005
    lo = np.array([-0.25, 0.90, -0.25])
    xs = lo[0] + vox * np.arange(101)
    ys = lo[1] + vox * np.arange(141)
    zs = lo[2] + vox * np.arange(101)
    gx, _gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    return gf.Sdf(field=np.hypot(gx, gz) - RB, lo=lo, vox=vox)


def rings(radius):
    """Rings every 1 cm, y 1.00 .. 1.30, 72 vertices: (X, t)."""
    rows, ts = [], []
    for i in range(31):
        y = 1.00 + 0.01 * i
        for j in range(72):
            t = 2 * np.pi * (j + 0.25) / 72
            rows.append([radius * np.sin(t), y, radius * np.cos(t)])
            ts.append(t)
    return np.array(rows), np.array(ts)


def radial(Y):
    return np.hypot(Y[:, 0], Y[:, 2])


def test_fit(gf):
    print("[1] fit_trunk")
    sdf = cylinder_sdf(gf)
    X, t = rings(RB + 0.04)
    n = len(X)
    for w, want in ((1.0, 0.132), (0.5, 0.146)):
        Y = X + gf.fit_trunk(X, np.full(n, w), FRAME, sdf)
        err = np.abs(radial(Y) - want).max()
        check(f"[1a] weight {w}: r = {want} within 0.3 mm", err < 3e-4, f"max err {err * 1000:.3f} mm")
        check(f"[1a] weight {w}: height kept", np.abs(Y[:, 1] - X[:, 1]).max() < 1e-4)
        ang = np.angle(np.exp(1j * (np.arctan2(Y[:, 0], Y[:, 2]) - t)))
        check(f"[1a] weight {w}: angle kept", np.abs(ang).max() < 1e-3, f"{np.abs(ang).max():.2e}")
    check("[1a] weight 0: no move", not np.any(gf.fit_trunk(X, np.zeros(n), FRAME, sdf)))
    for room_in, want_in, want_out, tag in ((0.036, 0.130, 0.134, "b"), (0.024, 0.126, 0.139, "c")):
        Xi, _ = rings(RB + room_in)
        Xo, _ = rings(RB + 0.04)
        X2 = np.concatenate([Xi, Xo])
        Y = X2 + gf.fit_trunk(X2, np.ones(len(X2)), FRAME, sdf)
        ri, ro = radial(Y[:n]), radial(Y[n:])
        check(f"[1{tag}] inner sheet ({room_in * 100:.1f} cm of room) -> r {want_in}",
              np.abs(ri - want_in).max() < 3e-4, f"max err {np.abs(ri - want_in).max() * 1000:.3f} mm")
        check(f"[1{tag}] outer sheet (4.0 cm) -> r {want_out}", np.abs(ro - want_out).max() < 3e-4,
              f"max err {np.abs(ro - want_out).max() * 1000:.3f} mm")
        check(f"[1{tag}] the sheets keep their order", np.all(ro > ri))


class _Body:
    def __init__(self):
        self.positions = np.array([[0.0, 0.0, 0.0], [0.0, 1.70, 0.0]])
        self.joint_names = ["Hips", "LeftArm", "RightArm", "Spine2"]
        self.joint_positions = {"hips": np.array([0.0, 0.95, 0.0]), "leftarm": np.array([0.15, 1.40, 0.0]),
                                "rightarm": np.array([-0.15, 1.42, 0.0]), "spine2": np.array([0.0, 1.30, 0.0])}


def test_weights(gf):
    print("[2] trunk_weights / trunk_waist")
    lo, hi, step = gf.TORSO_V
    nv = int(round((hi - lo) / step))
    centres = lo + step * (np.arange(nv) + 0.5)
    frame = dict(FRAME, radius=np.repeat((0.10 + np.abs(centres - 0.29))[:, None], gf.TORSO_THETA, 1).tolist())
    body = _Body()
    waist = gf.trunk_waist(body, frame)
    check("[2] the narrowest waist at y 1.095", abs(waist - 1.095) < 1e-9, waist)
    ys = np.array([1.00, 1.035, 1.065, 1.095, 1.20, 1.3745, 1.40, 1.20])
    X = np.stack([np.full(len(ys), 0.15), ys, np.zeros(len(ys))], 1)
    Wg = np.zeros((len(ys), 4))
    Wg[:, 0] = 1.0
    Wg[-1] = [0.7, 0.3, 0.0, 0.0]
    beta, band = gf.trunk_weights(X, Wg, body, frame)
    want = np.array([0.0, 0.0, 0.5, 1.0, 1.0, 0.5, 0.0, 0.7])
    check("[2] weights 0 / 0 / 0.5 / 1 / 1 / 0.5 / 0 / 0.7", np.abs(beta - want).max() < 1e-6, str(np.round(beta, 4)))
    check("[2] band {waist 1.095, low 1.035, top 1.40, full 1.349}",
          band == {"waist_y_m": 1.095, "low_y_m": 1.035, "top_y_m": 1.4, "full_y_m": 1.349}, band)


def test_auto(gf):
    print("[3] auto_trunk / trunk_reason_text / trunk_choice")
    blouse = gf.auto_trunk({"room_p50_m": 0.0254, "front_m": 0.0382})
    check("[3] the blouse -> fitted by its front 3.8 cm", blouse == ("fitted", [{"rule": "front", "cm": 3.8}]), blouse)
    jacket = gf.auto_trunk({"room_p50_m": 0.023, "front_m": 0.0196})
    check("[3] the jacket -> generated, it fits",
          jacket == ("generated", [{"rule": "fits", "cm": 2.3, "front_cm": 2.0}]), jacket)
    check("[3] room 3.1 cm -> fitted by the room",
          gf.auto_trunk({"room_p50_m": 0.031, "front_m": 0.010}) == ("fitted", [{"rule": "room", "cm": 3.1}]))
    check("[3] exactly 3 cm -> generated", gf.auto_trunk({"room_p50_m": 0.03, "front_m": 0.03})[0] == "generated")
    check("[3] no numbers -> generated, no why", gf.auto_trunk(None) == ("generated", []))
    check("[3] reason text (fitted)", gf.trunk_reason_text(*blouse)
          == "Auto -> Fitted to the body: its front stands 3.8 cm off the body", gf.trunk_reason_text(*blouse))
    check("[3] reason text (generated)", gf.trunk_reason_text(*jacket)
          == "Auto -> As generated: the trunk sits 2.3 cm off the body, 2 cm in front — it keeps its volume",
          gf.trunk_reason_text(*jacket))
    choices = (gf.trunk_choice({}), gf.trunk_choice({"trunk": "fitted"}), gf.trunk_choice({"trunk": "wider"}))
    check("[3] trunk_choice", choices == ("auto", "fitted", "auto"), choices)


def test_identity(gf):
    print("[4] place_trunk keeps a piece as generated itself")
    from app.core.garment_fit import _adjacency
    X, _t = rings(RB + 0.04)
    F = np.array([[0, 1, 72], [1, 73, 72]], np.int64)
    body = _Body()
    Wg = np.zeros((len(X), 4))
    Wg[:, 1] = 1.0
    sdf = cylinder_sdf(gf)
    adjacency = _adjacency(F, len(X))
    for choice in ("auto", "generated"):
        Y, report, fitted = gf.place_trunk(X, X.copy(), Wg, body, faces=F, adjacency=adjacency, sdf=sdf,
                                           choice=choice, clear=0.012, margin=gf.SIDE_MARGIN_M)
        check(f"[4] {choice}: the very same array", Y is X)
        check(f"[4] {choice}: applied generated, nothing fitted", report["applied"] == "generated" and not fitted.any(),
              report)


def test_settings():
    print("[5] the fit setting")
    from app.core import garment_fit_settings as fs
    check("[5] default auto", fs.normalise({})["trunk"] == "auto")
    check("[5] keeps fitted / generated, drops wider",
          (fs.normalise({"trunk": "fitted"})["trunk"], fs.normalise({"trunk": "generated"})["trunk"],
           fs.normalise({"trunk": "wider"})["trunk"]) == ("fitted", "generated", "auto"))
    check("[5] validate keeps fitted", fs.validate({"trunk": "fitted"}) == {"trunk": "fitted"})
    for bad in ("wider", True, 1):
        try:
            fs.validate({"trunk": bad})
            ok = False
        except ValueError:
            ok = True
        check(f"[5] validate refuses {bad!r}", ok)
    old = {"inputs": {"fit_settings": {"sleeves_left": "auto", "sleeves_right": "auto", "allowance": "auto",
                                       "depth": 0}}}
    check("[5] a fit made before the setting is not due", not fs.changed(old, {}, "item_a"))
    check("[5] ... and due under trunk fitted",
          fs.changed(old, {fs.SETTINGS_KEY: {"item_a": {"trunk": "fitted"}}}, "item_a"))


def test_versions(gf):
    print("[6] versions")
    check("[6] FIT_VERSION clothing 16, CLOTHING_TRUNK_UNCHANGED 15",
          gf.FIT_VERSION["clothing"] == 16 and gf.CLOTHING_TRUNK_UNCHANGED == 15, gf.FIT_VERSION)

    def rec(version, room=None, front=None, kind="clothing"):
        metrics = {} if room is None else {"torso_gap_p50_m": room, "trunk_front_gap_p50_m": front}
        return {"kind": kind, "fit_version": version, "metrics": metrics}
    cases = [("v15 blazer 13.8 / 12.6 mm stays current", rec(15, 0.0138, 0.0126), 15),
             ("v15 blouse 23.2 / 38.1 mm is due", rec(15, 0.0232, 0.0381), 16),
             ("v15 room 31 mm is due", rec(15, 0.031, 0.010), 16),
             ("v15 without metrics stays current", rec(15), 15),
             ("v14 is due", rec(14, 0.0138, 0.0126), 16),
             ("v16 is current", rec(16, 0.0232, 0.0381), 16),
             ("hair keeps its own", rec(15, kind="hair"), gf.FIT_VERSION["hair"])]
    for label, record, want in cases:
        got = gf.expected_fit_version(record)
        check(f"[6] {label}", got == want, got)


def test_old_code():
    print(f"[7] fails on the old code ({OLD})")
    try:
        src = subprocess.run(["git", "show", f"{OLD}:app/core/garment_fit.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
        settings = subprocess.run(["git", "show", f"{OLD}:app/core/garment_fit_settings.py"], cwd=ROOT,
                                  capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        check("[7] old sources readable", False, e)
        return
    check("[7] no place_trunk / TRUNK_CHOICES", "def place_trunk" not in src and "TRUNK_CHOICES" not in src)
    check("[7] FIT_VERSION clothing 15", '"clothing": 15' in src)
    check("[7] validate knows no trunk", '"trunk"' not in settings and "trunk" not in settings.split("def validate")[1])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.setdefault("STORAGE_DIR", tmp)
        from app.core import paths
        paths.init(tmp)
        from app.core import garment_fit as gf
        test_fit(gf)
        test_weights(gf)
        test_auto(gf)
        test_identity(gf)
        test_settings()
        test_versions(gf)
        test_old_code()
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
