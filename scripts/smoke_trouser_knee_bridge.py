#!/usr/bin/env python3
"""Smoke: round 2026-11-25 — the knee bridge of a widened trouser leg (Kai's jeans: an outward dome over the upper
calf under a pinch ring in the knee hollow).

Usage:
    ./.venv/bin/python scripts/smoke_trouser_knee_bridge.py

No server, no hub, no network, no Blender: the builder module ``app/blender/scripts/garment_template_fitted.py`` is
imported with stub ``bpy`` / ``bmesh`` / ``mathutils`` modules and only its numpy functions run; the keys come from
``garment_template`` / ``garment_template_cut`` directly, the keys of main ``ac232ef4d`` from that commit's
``garment_template.py`` loaded under another name.

Expected by hand:

[H] ``upper_hull`` / ``hull_at`` on the knee profile of the plan: (s, r) = (-0.06, 0.094), (0, 0.090), (0.10, 0.105)
    and (0.05, 0.095). The chord from the first to the third point runs at 0.094 + 0.011 x (s + 0.06) / 0.16; at
    s = 0.05 it is 0.1015625 > 0.095 and at s = 0 it is 0.098125 > 0.090, so both middle points lie under it: the hull
    is that chord. H(0) = 0.098125 (the 98.1 mm of the plan), H(-0.06) = 0.094, H(0.10) = 0.105, H(0.05) = 0.1015625;
    outside [-0.06, 0.10] NaN. With a point (0.12, 0.100) added the hull is (-0.06, 0.094) -> (0.10, 0.105) ->
    (0.12, 0.100): H(0.11) = 0.1025, H(0) unchanged. Two points at the same s: only the larger counts.
[T] ``sector_hulls`` with 4 sectors, flat profiles: sector 0 at 0.08, sector 1 at 0.10, sectors 2 and 3 at 0.08 (a
    point every 0.01 from s 0 to 0.1, one angle per sector at its centre). The (1, 2, 1) / 4 mean: sector 0
    (0.08 + 0.16 + 0.10) / 4 = 0.085 > 0.08 -> 0.085; sector 1 (0.08 + 0.20 + 0.08) / 4 = 0.09 < 0.10 -> 0.10 (never
    lowered); sector 2 (0.10 + 0.16 + 0.08) / 4 = 0.085; sector 3 (0.08 + 0.16 + 0.08) / 4 = 0.08.
[K] ``knee_bridge`` on a synthetic leg: side +1, axis hip (0.2, 0, 0.9) -> knee (0.2, 0, 0.5) -> ankle (0.2, 0, 0.1),
    cx 0, crotch 0.85, ramp 0.23 (the zone's top at z 0.62: s = -0.12), hem 0.12 (plain), centre gap 0.006, a
    straight leg (``shape_r`` set). Rings every 0.01 from
    z 0.12 to 0.80 (s = 0.5 - z: -0.30 .. 0.38), 36 angles each, round the axis; the radius by s: 0.094 down to
    s = -0.06, then straight to 0.090 at s = 0, to 0.105 at s = 0.10, to 0.085 at the hem s = 0.38. The bridge reads
    s from -0.12: its hull's corners are (-0.12, 0.094), (0.10, 0.105), (0.38, 0.085) (the points from -0.12 to -0.06
    at 0.094 and the hollow lie under the chord of slope 0.011 / 0.22 = 0.05; under the calf the profile is a straight
    line, the hull itself). So:
    - s = 0 (z 0.50): 0.094 + 0.05 x 0.12 = 0.100 (was 0.090: 10 mm out, the hollow bridged);
    - s = -0.06 (z 0.56): 0.094 + 0.05 x 0.06 = 0.097 (was 0.094);
    - s = -0.11 (z 0.61): the fade smoothstep((0.01) / 0.03) = 1/3^2 x (3 - 2/3) = 0.259259; H = 0.0945, lift
      0.0005 x 0.259259 = 0.00012963 -> 0.09412963;
    - s = -0.12 and above: unchanged (0.094); s = 0.10 (calf): 0.105, s = 0.24: 0.085 + 0.02 x 0.14 / 0.28 = 0.095,
      unchanged (the hull is the profile there);
    - no vertex moves in, no height changes; a skinny leg (no ``shape_r``) moves nothing;
    - with ramp 0.08 the zone starts at z 0.77 (s -0.27): the hull runs (-0.27, 0.094) -> (0.10, 0.105), so z 0.66
      (s -0.16, fade full) is at 0.094 + 0.011 x 0.11 / 0.37 = 0.09727027.
[N] the keys: a straight trouser's drape key (``tsig``) differs from main ``ac232ef4d`` (``KNEE_VERSION``), a skinny
    trouser's and a skirt's are the same as there; ``knee_piece``: straight / wide / flared / cargo yes, skinny no, a
    skirt no. The CUT key of a straight trouser has no knee part (the bridge runs after the pattern UVs, so its islands
    and its cut atlas stay): ``cut_sig`` is the same with ``KNEE_VERSION`` set to 1 and to 99.
"""
import importlib.util
import math
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []
MAIN = "ac232ef4d"


def check(label, got, want, tol=None):
    if tol is not None:
        ok = got is not None and want is not None and abs(float(got) - float(want)) <= tol
    else:
        ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def fitted_module():
    """The builder module with stub Blender modules (only its numpy functions are called)."""
    for name in ("bpy", "bmesh", "garment_template_drape"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mu = types.ModuleType("mathutils")
    mu.Vector = tuple
    sys.modules.setdefault("mathutils", mu)
    bvh = types.ModuleType("mathutils.bvhtree")
    bvh.BVHTree = object
    sys.modules.setdefault("mathutils.bvhtree", bvh)
    sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
    import garment_template_fitted as gf
    return gf


def profile(s):
    """The synthetic leg's radius by s ([K])."""
    return float(np.interp(s, [-0.30, -0.06, 0.0, 0.10, 0.38], [0.094, 0.094, 0.090, 0.105, 0.085]))


def leg():
    angles = np.radians(np.arange(0, 360, 10))
    zs = np.round(np.arange(0.12, 0.8001, 0.01), 4)
    V = []
    for z in zs:
        r = profile(0.5 - z)
        for a in angles:
            V.append([0.2 + r * math.cos(a), r * math.sin(a), z])
    return np.array(V), zs, len(angles)


def main_tsig_module():
    """``garment_template.py`` of main ``MAIN``, loaded as its own module (its imports are absolute)."""
    src = subprocess.run(["git", "show", f"{MAIN}:app/core/garment_template.py"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    path = Path(tempfile.mkdtemp(prefix="knee-smoke-")) / "garment_template_main.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("garment_template_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    gf = fitted_module()
    print("[H] the upper concave hull")
    S = [-0.06, 0.0, 0.10, 0.05]
    R = [0.094, 0.090, 0.105, 0.095]
    hs, hr = gf.upper_hull(S, R)
    check("hull corners", [round(float(x), 6) for x in hs], [-0.06, 0.10])
    for s, want in ((0.0, 0.098125), (-0.06, 0.094), (0.10, 0.105), (0.05, 0.1015625)):
        check(f"H({s})", float(gf.hull_at(S, R, [s])[0]), want, 1e-9)
    check("H(-0.07) NaN", bool(np.isnan(gf.hull_at(S, R, [-0.07])[0])), True)
    check("H(0.11) NaN", bool(np.isnan(gf.hull_at(S, R, [0.11])[0])), True)
    S2, R2 = S + [0.12], R + [0.100]
    check("with (0.12, 0.100): H(0.11)", float(gf.hull_at(S2, R2, [0.11])[0]), 0.1025, 1e-9)
    check("with (0.12, 0.100): H(0)", float(gf.hull_at(S2, R2, [0.0])[0]), 0.098125, 1e-9)
    check("same s: the larger counts", float(gf.hull_at([0.0, 0.0, 0.1], [0.05, 0.07, 0.07], [0.05])[0]), 0.07, 1e-12)

    print("[T] the sectors")
    ss, th, rr = [], [], []
    for k, r in enumerate((0.08, 0.10, 0.08, 0.08)):
        for s in np.round(np.arange(0.0, 0.1001, 0.01), 4):
            ss.append(s)
            th.append(-math.pi + (k + 0.5) * 2 * math.pi / 4)
            rr.append(r)
    g, T = gf.sector_hulls(np.array(ss), np.array(th), np.array(rr), 0.0, 0.1, sectors=4, grid=0.01)
    for k, want in enumerate((0.085, 0.10, 0.085, 0.08)):
        check(f"sector {k} at every s", [round(float(v), 9) for v in T[k]], [want] * len(g))

    print("[K] the knee bridge on a synthetic leg")
    V, zs, n = leg()
    f = {"shape_r": [0.8, 0.75], "hem": "plain", "cuff_m": 0.04, "centre_gap_m": 0.006, "ramp_m": 0.23}
    sides = {1: {"axis": [np.array([0.2, 0.0, 0.9]), np.array([0.2, 0.0, 0.5]), np.array([0.2, 0.0, 0.1])],
                 "crotch": 0.85, "hem": 0.12}}
    W, info = gf.knee_bridge(V, f, sides, 0.0)
    r0 = np.hypot(V[:, 0] - 0.2, V[:, 1])
    r1 = np.hypot(W[:, 0] - 0.2, W[:, 1])

    def ring(z):
        i = int(np.argmin(np.abs(zs - z)))
        return r1[i * n:(i + 1) * n]
    for z, want in ((0.50, 0.100), (0.56, 0.097), (0.61, 0.09412963), (0.62, 0.094), (0.70, 0.094),
                    (0.40, 0.105), (0.26, 0.095), (0.12, 0.085)):
        rr_ = ring(z)
        check(f"z {z:.2f} (s {0.5 - z:+.2f}) every vertex", round(float(rr_.max() - rr_.min()), 9) <= 1e-9
              and abs(float(rr_.mean()) - want) <= 1e-6, True)
        check(f"z {z:.2f} radius", float(rr_.mean()), want, 1e-6)
    check("no vertex moved in", bool((r1 >= r0 - 1e-12).all()), True)
    check("no height changed", float(np.abs(W[:, 2] - V[:, 2]).max()), 0.0, 1e-12)
    check("info: lift max 10 mm", info["1"]["lift_max_mm"], 10.0, 0.05)
    Wr, _ = gf.knee_bridge(V, {**f, "ramp_m": 0.08}, sides, 0.0)
    r2 = np.hypot(Wr[:, 0] - 0.2, Wr[:, 1])
    i = int(np.argmin(np.abs(zs - 0.66)))
    check("ramp 0.08: the zone's top at z 0.77 (s -0.27), z 0.66 (s -0.16) lifted",
          float(r2[i * n:(i + 1) * n].mean()), 0.094 + (0.105 - 0.094) * (0.27 - 0.16) / 0.37, 1e-6)
    Ws, _ = gf.knee_bridge(V, {**f, "shape_r": None}, sides, 0.0)
    check("skinny: nothing moves", float(np.abs(Ws - V).max()), 0.0, 0.0)

    print("[N] the keys")
    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    old = main_tsig_module()
    base = {"kind": "trousers", "trouser_length": "full", "leg_shape": "straight", "seat": "regular",
            "trouser_waist": "belt", "fly": "zip", "hem": "plain", "rise": "mid", "fit": 0.2, "fabric": "stiff"}
    kw = dict(base_sha="b" * 64, texture_sha="t" * 12, lower=[])
    check("straight: drape key differs from main", gt.tsig(base, **kw) != old.tsig(base, **kw), True)
    skinny = {**base, "leg_shape": "skinny", "seat": "fitted"}
    check("skinny: drape key as on main", gt.tsig(skinny, **kw), old.tsig(skinny, **kw))
    skirt = {"kind": "skirt", "length_m": 0.5, "fabric": "medium"}
    check("skirt: drape key as on main", gt.tsig(skirt, **kw), old.tsig(skirt, **kw))
    check("knee_piece", [gt.knee_piece({**base, "leg_shape": s}) for s in gt.LEG_SHAPES],
          [s != "skinny" for s in gt.LEG_SHAPES])
    check("knee_piece skirt", gt.knee_piece(skirt), False)
    a = gtc.cut_sig(base, base_sha="b" * 64, lower=[])
    keep = gt.KNEE_VERSION
    try:
        gt.KNEE_VERSION = 99
        b = gtc.cut_sig(base, base_sha="b" * 64, lower=[])
        c = gt.tsig(base, **kw)
    finally:
        gt.KNEE_VERSION = keep
    check("cut key without the knee", a, b)
    check("drape key follows KNEE_VERSION", c != gt.tsig(base, **kw), True)
    print("FAIL" if FAILS else "PASS", len(FAILS), "failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
