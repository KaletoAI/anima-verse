"""Smoke: straight cup top tip-collider clearance and balconette cup-seam guard (``CUP_TIP_VERSION``).

Usage:
    ./.venv/bin/python scripts/smoke_cup_tip_clear.py

No server, no world DB, no Blender: ``fitted_pattern`` is numpy-only and imported through ``sys.path``; ``paths.init``
runs on a temp dir before importing ``app.core``. Every expected value below is derived by hand from the spec
(``clear_m`` = 0.012, ``seam_min_m`` = 0.003, Lirien's sidecar values: ``apex_z`` = 1.2448, ``under`` = 1.1804,
``H`` = 1.2448 - 1.1804 = 0.0644, ``push`` = 0.39, ``PUSH_LIFT_M`` = 0.02 -> ``lift`` = 0.39 * 0.02 = 0.0078;
``zc_old = apex_z + (cov - 0.5) * 2 * H``):

[1] balconette, cov 0.50:
    zc_old = 1.2448 + 0 = 1.2448; rim = 1.2448 + 0.0078 - 1.2448 = 0.0078 m (7.8 mm, in (0, 0.012)).
    -> new_zc = 1.2448 - 0.0078 + 0.012 = 1.2490; raise_m = 1.2490 - 1.2448 = 0.0042 (4.2 mm).
    new_zc - apex_z = 0.0042 >= 0.003 -> seam_z = 1.2448.
[2] balconette, cov 0.46:
    zc_old = 1.2448 + (-0.04) * 2 * 0.0644 = 1.2448 - 0.005152 = 1.239648;
    rim = 1.239648 + 0.0078 - 1.2448 = 0.002648 m (2.648 mm, in (0, 0.012)).
    -> new_zc = 1.2448 - 0.0078 + 0.012 = 1.2490; raise_m = 1.2490 - 1.239648 = 0.009352 (9.352 mm).
    new_zc - apex_z = 0.0042 >= 0.003 -> seam_z = 1.2448.
[3] balconette, cov 0.40:
    zc_old = 1.2448 + (-0.10) * 2 * 0.0644 = 1.2448 - 0.01288 = 1.23192;
    rim = 1.23192 + 0.0078 - 1.2448 = -0.00508 m (-5.08 mm <= 0).
    -> unchanged (1.23192), raise_m = 0.0; new_zc - apex_z = -0.01288 < 0.003 -> seam_z = None.
[4] balconette, cov 0.55:
    zc_old = 1.2448 + 0.05 * 2 * 0.0644 = 1.2448 + 0.00644 = 1.25124;
    rim = 1.25124 + 0.0078 - 1.2448 = 0.01424 m (14.24 mm >= 0.012).
    -> unchanged (1.25124), raise_m = 0.0; new_zc - apex_z = 0.00644 >= 0.003 -> seam_z = 1.2448.
[5] balconette, cov 0.50, push 1.0 (lift = 1.0 * 0.02 = 0.02):
    zc_old = 1.2448; rim = 0.020 m (20 mm >= 0.012).
    -> unchanged (1.2448), raise_m = 0.0; new_zc - apex_z = 0.0 < 0.003 -> seam_z = None.
[6] Style scoping at cov 0.50 (zc_old 1.2448, lift 0.0078):
    molded and triangle: never raised (1.2448, raise 0.0), seam_z = None.
    bandeau: raised as in [1] (1.2490, raise 0.0042), seam_z = None.
[7] ``seam_planes`` and ``parts`` for bra / balconette with ``cup_seam_z = {"l": None, "r": 1.2448}``:
    ``seam_planes`` produces 5 planes: centre X (1), underbust height (1), two gore X planes (2), one cup seam plane
    for the right side (side = -1, z = 1.2448) — none for the left side.
    ``parts`` on two cup centroids at (-0.09, -0.21, 1.247) (right, x < cx 0, z > 1.2448) and (0.09, -0.21, 1.247)
    (left, x > cx 0, left seam_z is None -> inf): right -> ``cup_top_r``, left -> ``cup_l``.
[8] Old-code proof pinned to commit ``e57308f80``:
    load ``e57308f80:app/blender/scripts/fitted_pattern.py`` into a temp module and call its ``seam_planes`` for
    balconette at cov 0.50 (apex z = 1.2448 = zc_old): it emits 6 planes (both sides) and its horizontal cup seam
    planes lie at z = 1.2448 == zc_old (directly on the rim).
[9] Keys (``tsig`` and ``cut_sig``):
    for both ``{"kind": "bra", "cup_style": X}`` and ``{"kind": "top", "cups": "bra", "cup_style": X}`` (validated),
    bumping ``CUP_TIP_VERSION`` changes ``tsig`` and ``cut_sig`` for X in ("balconette", "bandeau") and leaves
    "molded" and "triangle" unchanged.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_cup_tip_clear_"))
from app.core import paths  # noqa: E402

paths.init(_TMP / "world")
paths.init_instance(_TMP / "instance")

import fitted_pattern as fp  # noqa: E402
import uv_pattern as up  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


def near(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


APEX_Z = 1.2448
UNDER_Z = 1.1804
H = APEX_Z - UNDER_Z           # 0.0644
LIFT = 0.39 * 0.02             # 0.0078
CLEAR = 0.012
SEAM_MIN = 0.003


def zc_old(cov):
    return APEX_Z + (cov - 0.5) * 2.0 * H


print("smoke_cup_tip_clear")

# [1] balconette cov 0.50
z1, s1, r1 = fp.cup_top_line("balconette", APEX_Z, zc_old(0.50), LIFT, CLEAR, SEAM_MIN)
check("[1] balconette cov 0.50: zc 1.2490, raise 4.2 mm, seam 1.2448",
      near(z1, 1.2490) and near(r1, 0.0042) and s1 is not None and near(s1, 1.2448), (z1, s1, r1))

# [2] balconette cov 0.46
z2, s2, r2 = fp.cup_top_line("balconette", APEX_Z, zc_old(0.46), LIFT, CLEAR, SEAM_MIN)
check("[2] balconette cov 0.46: zc 1.2490, raise 9.352 mm, seam 1.2448",
      near(z2, 1.2490) and near(r2, 0.009352) and s2 is not None and near(s2, 1.2448), (z2, s2, r2))

# [3] balconette cov 0.40
z3, s3, r3 = fp.cup_top_line("balconette", APEX_Z, zc_old(0.40), LIFT, CLEAR, SEAM_MIN)
check("[3] balconette cov 0.40: zc 1.23192 unchanged, raise 0, seam None",
      near(z3, 1.23192) and near(r3, 0.0) and s3 is None, (z3, s3, r3))

# [4] balconette cov 0.55
z4, s4, r4 = fp.cup_top_line("balconette", APEX_Z, zc_old(0.55), LIFT, CLEAR, SEAM_MIN)
check("[4] balconette cov 0.55: zc 1.25124 unchanged, raise 0, seam 1.2448",
      near(z4, 1.25124) and near(r4, 0.0) and s4 is not None and near(s4, 1.2448), (z4, s4, r4))

# [5] balconette cov 0.50, push 1.0 (lift 0.02)
z5, s5, r5 = fp.cup_top_line("balconette", APEX_Z, zc_old(0.50), 0.02, CLEAR, SEAM_MIN)
check("[5] balconette cov 0.50 push 1.0: zc 1.2448 unchanged, raise 0, seam None",
      near(z5, 1.2448) and near(r5, 0.0) and s5 is None, (z5, s5, r5))

# [6] style scoping at cov 0.50
for st in ("molded", "triangle"):
    zs, ss, rs = fp.cup_top_line(st, APEX_Z, zc_old(0.50), LIFT, CLEAR, SEAM_MIN)
    check(f"[6] {st} cov 0.50: unchanged, raise 0, seam None",
          near(zs, 1.2448) and near(rs, 0.0) and ss is None, (zs, ss, rs))
zb, sb, rb = fp.cup_top_line("bandeau", APEX_Z, zc_old(0.50), LIFT, CLEAR, SEAM_MIN)
check("[6] bandeau cov 0.50: zc 1.2490, raise 4.2 mm, seam None",
      near(zb, 1.2490) and near(rb, 0.0042) and sb is None, (zb, sb, rb))

# [7] seam_planes and parts with one-sided cup_seam_z
f7 = {"style": "balconette", "gore_half_m": 0.012}
info7 = {
    "cx": 0.0,
    "cy": 0.0,
    "under_z": UNDER_Z,
    "apex": {"l": [0.09, -0.21, APEX_Z], "r": [-0.09, -0.21, APEX_Z]},
    "cup_seam_z": {"l": None, "r": APEX_Z},
    "pred": {
        "band": lambda c: np.zeros(len(c), bool),
        "straps": lambda c: np.zeros(len(c), bool),
        "gore": lambda c: np.zeros(len(c), bool),
        "cups": lambda c: np.ones(len(c), bool),
    },
}
planes7 = fp.seam_planes("bra", f7, {}, info7)
cup_planes7 = [(p, n, s, tag) for p, n, s, tag in planes7 if tag == "front" and near(n[2], 1.0)]
check("[7] seam_planes balconette with cup_seam_z {l: None, r: 1.2448} -> 5 planes total",
      len(planes7) == 5, len(planes7))
check("[7] seam_planes emits 1 cup seam plane on right side (side -1) at z 1.2448",
      len(cup_planes7) == 1 and cup_planes7[0][2] == -1 and near(cup_planes7[0][0][2], APEX_Z),
      [(p.tolist(), n.tolist(), s, tag) for p, n, s, tag in cup_planes7])
pts7 = np.array([[-0.09, -0.21, 1.247], [0.09, -0.21, 1.247]])
parts7 = fp.parts("bra", f7, pts7, {}, info7)
names7 = [up.PARTS[int(pid)] for pid in parts7]
check("[7] parts: right centroid -> cup_top_r, left mirror -> cup_l",
      names7 == ["cup_top_r", "cup_l"], names7)

# [8] Old-code proof pinned to e57308f80
OLD_COMMIT = "e57308f80"
old_src = subprocess.run(
    ["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/blender/scripts/fitted_pattern.py"],
    capture_output=True, text=True, check=True,
).stdout
old_file = _TMP / "fitted_pattern_old.py"
old_file.write_text(old_src, encoding="utf-8")
spec_old = importlib.util.spec_from_file_location("fitted_pattern_old", str(old_file))
fp_old = importlib.util.module_from_spec(spec_old)
spec_old.loader.exec_module(fp_old)
planes_old = fp_old.seam_planes("bra", f7, {}, info7)
cup_planes_old = [(p, n, s, tag) for p, n, s, tag in planes_old if tag == "front" and near(n[2], 1.0)]
check(f"[8] old code ({OLD_COMMIT}): balconette seam_planes emits 6 planes (both sides)",
      len(planes_old) == 6 and len(cup_planes_old) == 2, (len(planes_old), len(cup_planes_old)))
check(f"[8] old code ({OLD_COMMIT}): cup seam planes sit at z = zc_old = 1.2448 (on the rim)",
      all(near(p[2], zc_old(0.50)) for p, _n, _s, _t in cup_planes_old),
      [float(p[2]) for p, _n, _s, _t in cup_planes_old])

# [9] Keys: CUP_TIP_VERSION moves tsig and cut_sig only for balconette / bandeau
old_ver = gt.CUP_TIP_VERSION
for base_params in ({"kind": "bra"}, {"kind": "top", "cups": "bra"}):
    label_kind = "bra" if base_params["kind"] == "bra" else "top_cups"
    for style in ("balconette", "bandeau", "molded", "triangle"):
        p, errs = gt.validate_params({**base_params, "cup_style": style})
        t0 = gt.tsig(p, base_sha="b" * 64, texture_sha="t", lower=[])
        c0 = gtc.cut_sig(p, base_sha="b" * 64, lower=[])
        gt.CUP_TIP_VERSION = old_ver + 100
        try:
            t1 = gt.tsig(p, base_sha="b" * 64, texture_sha="t", lower=[])
            c1 = gtc.cut_sig(p, base_sha="b" * 64, lower=[])
        finally:
            gt.CUP_TIP_VERSION = old_ver
        want_move = style in ("balconette", "bandeau")
        check(f"[9] {label_kind} {style}: tsig {'moves' if want_move else 'stays'}",
              (t1 != t0) == want_move, (t0, t1))
        check(f"[9] {label_kind} {style}: cut_sig {'moves' if want_move else 'stays'}",
              (c1 != c0) == want_move, (c0, c1))

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
