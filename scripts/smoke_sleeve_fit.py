#!/usr/bin/env python3
"""Ruling A47 — sleeves laid onto the arm, the Auto choice, the stretched-strip gate, the arm light, the width
allowance and the fit settings (app/core/garment_fit.py: ``fit_sleeve``, ``measure_sleeve``, ``auto_sleeve``,
``sleeve_shards``, ``arm_light``, ``scale_retry``; app/core/garment_fit_settings.py) on synthetic geometry — no
world, no hub, no GLB.

Usage:
    ./.venv/bin/python scripts/smoke_sleeve_fit.py

Expected numbers, derived by hand:

Arm: a straight chain shoulder (0.20, 1.40, 0) -> elbow (0.48, 1.40, 0) -> wrist (0.74, 1.40, 0), reference (0, 1, 0)
-> u = +x, v = +y, w = u x v = +z; arc length s = x - 0.20, cross coordinates a = y - 1.40, b = z. The arm is a
cylinder of radius R = 0.04 about the chain (``_ArmSections`` built by hand: every station centre (0, 0), every
sector radius 0.04; 28 stations of SLEEVE_STATION_M 0.02 cover s 0 .. 0.56).

[1] "Fitted to the arm" (``fit_sleeve``). The sleeve: rings every 1 cm, s = 0 .. 0.52, 24 vertices each at angle
    t_j = 2 pi j / 24, radius rho(t) = 0.035 + 0.004 cos(6 t) about its own axis, which is OFFSET and TILTED: its
    centre at s is (a, b) = (-0.06 s / 0.54, 0) — 0 at the shoulder, 6 cm lower at the wrist (the generator's steeper
    sleeve, as thin as the arm). Transfer weight on the arm 1 everywhere.
    The ring median radius is 0.035 (the median of cos(6 t) over 24 equal steps is 0), so a vertex's detail is
    0.004 cos(6 t) and its fitted radius about the ARM's centre is R + SLEEVE_FIT_CLEAR_M + SLEEVE_FIT_DETAIL x detail
    = 0.04 + 0.012 + 0.3 x 0.004 cos(6 t) = 0.052 + 0.0012 cos(6 t), at its own angle t (cos 6t from the ring's own
    centre: the angle is kept). The blend along the arm is clip((s - 0.03) / 0.07, 0, 1) -> full from s = 0.10.
    Expected for every vertex with 0.10 <= s <= 0.50 after X + D:
      * its distance from the arm axis minus (0.052 + 0.0012 cos(6 t)) within 0.5 mm;
      * its angle about the arm axis = t within 0.02 rad (1 mm of arc at 5.2 cm: the sleeve's own centre is
        ESTIMATED from its ring — the mid-range of the 2nd / 98th percentiles of 24 vertices with 4 mm folds —, so
        it carries a fraction of a millimetre, which turns the angle by up to ~0.3 mm / 3.5 cm);
      * per ring, the mid-range centre within 0.5 mm of the arm axis (was up to 5.6 cm off);
      * the ring's radius amplitude (max - min) / 2 = 1.2 mm +- 0.2 mm — SLEEVE_FIT_DETAIL of the 4 mm folds kept
        (with detail share 0 it would be 0, with 1 it would be 4 mm);
      * s unchanged (within 0.1 mm): the sleeve is not pulled along the arm.
    At s = 0.0 (inside the armhole blend) nothing moves (beta 0); at s = 0.065 (half way) the vertex moves half way:
    |D| = 0.5 x |T - X| within 0.1 mm.
[2] ``measure_sleeve`` + ``auto_sleeve`` on that sleeve (inside = the vertex lies within R of the arm axis, an
    input): stations 5 (ceil(0.10 / 0.02)) .. 25 (the last closed station 26 left out); the worst station 25 holds the
    rings at s 0.50 / 0.51 (offsets 5.56 / 5.67 cm, mid-range of both about 5.6 cm) -> offset_max_m 0.055 .. 0.058,
    where "forearm" (0.51 lies between the elbow 0.28 and the wrist 0.54); room p50 = 0.035 - 0.04 = -0.5 cm. Auto ->
    "fitted" with the rules offset and room both holding (inside may hold too: that share is the input's); the reason
    text reads "Auto -> Fitted to the arm: the sleeve sits 5.6 (or 5.7, rounding) cm off the forearm and it is as
    thin as the arm ...".
    A GOOD sleeve — straight, on the arm axis, radius 0.06 (2 cm of room), nothing inside — : offset 0 (< 2 cm), room
    p50 2 cm (>= 1.2 cm), inside 0 (<= 20 %) -> "generated", why [{rule: fits}], and ``fit_sleeve`` is not run
    (``sleeve_choices`` of an empty setting is auto/auto, ``place_sleeves`` decides from ``auto_sleeve``).
[3] ``sleeve_shards``: a triangle (0,0,0) (0.01,0,0) (0,0.01,0) — longest edge 0.01414 — stretched to (0,0,0)
    (0.045,0,0) (0,0.01,0): longest edge 0.0461 > SLEEVE_SHARD_M 0.03 and > 3 x 0.01414 = 0.0424 -> a shard; to
    (0.035,0,0): 0.0364 > 0.03 but < 0.0424 -> no shard; outside the region -> no shard. The gate
    ``sleeve_shards`` is in CLOTHING_GATES with the limit SLEEVE_SHARDS_MAX 6 (7 refuses, 6 passes).
[4] ``arm_light``: {left 0.2, right 12} -> left green (rounds to 0), right yellow (< 30) -> state yellow, worst 12;
    {left 30} -> red; {} -> none.
[5] Width allowance (``scale_retry`` with stub push/finish: the scale is read off a probe vertex at x 1.0 widened
    about centre 0 with half width 10 — widen scales it whole; every step passes the gates):
    (a) torso_tight_share by scale 1.00 0.30, 1.02 0.25, 1.04 0.20, 1.06 0.17, 1.08 0.12, deep push 0.05: the trigger
        is the tight share (0.30 > 0.18); 1.06 is the SMALLEST step that passes and clears it (0.17 <= 0.18) ->
        factor 1.06, attempts 1.02 / 1.04 / 1.06 (1.08 never tried), finish calls [1.0, 1.02, 1.04, 1.06];
    (b) the same with 1.02 refused and nothing clearing (tight 0.30, 0.25 refused, 0.22, 0.21, 0.20): the smallest
        passing step that improves (neither number worse, one lower) -> 1.04;
    (c) no trigger (tight 0.10, deep 0.05) -> factor 1.0, one finish call;
    (d) a fixed allowance 6 -> one finish call at 1.06, factor 1.06, no walk; fixed 0 -> 1.0;
    never beyond 1.08: max(SCALE_RETRY_STEPS) == 1.08 and every tried scale <= 1.08.
    Width only: ``widen`` keeps y — (0.3, 1.2, 0.1) widened 1.08 about (0, 0) with half width 10 -> (0.324, 1.2,
    0.108).
[6] Fit settings: ``normalise`` fills every key with its default ("auto"; Ruling A68's ``depth`` 0) and drops
    unknown values (depth 5 -> 0); a record made with the defaults
    and a profile asking sleeves_left "fitted" -> ``changed`` True (the fit is due), the same settings -> False, a
    record WITHOUT ``inputs.fit_settings`` reads as the defaults; ``validate`` refuses an unknown key, a bad sleeve
    choice, allowance 5 / 25 and depth 5 / 25 / "auto" and keeps allowance 20 / depth 20 (Ruling A76: both reach
    +20 %); ``garments._settings_changed`` judges a clothing record so and never a
    footwear one. Ruling A68: a record made before the depth setting (no ``depth`` key) under a profile without one
    is NOT due (missing = 0), the same record under depth 6 is.
[7] Fails on the old code: at commit 8e6d8c65a (before Ruling A47) app/core/garment_fit.py has no ``fit_sleeve``,
    no ``sleeve_shards`` gate and FIT_VERSION clothing 10; garment_fit_settings.py does not exist.
"""
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f" ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


SHOULDER, ELBOW, WRIST = np.array([0.20, 1.40, 0.0]), np.array([0.48, 1.40, 0.0]), np.array([0.74, 1.40, 0.0])
R = 0.04


def arm(gf):
    n = 28
    return gf._ArmSections(pts=np.stack([SHOULDER, ELBOW, WRIST]), reference=[0.0, 1.0, 0.0],
                           cum=np.array([0.0, 0.28, 0.54]), centres=np.zeros((n, 2)),
                           radii=np.full((n, gf.SLEEVE_SECTORS), R))


def sleeve(offset=True, radius=0.035, fold=0.004):
    """Rings every 1 cm, s 0 .. 0.52, 24 vertices: (X, s, t)."""
    rows, ss, ts = [], [], []
    for i in range(53):
        s = i * 0.01
        ca = -0.06 * s / 0.54 if offset else 0.0
        for j in range(24):
            t = 2 * math.pi * j / 24
            r = radius + fold * math.cos(6 * t)
            rows.append([0.20 + s, 1.40 + ca + r * math.cos(t), r * math.sin(t)])
            ss.append(s)
            ts.append(t)
    return np.array(rows), np.array(ss), np.array(ts)


def test_fit(gf):
    print("[1] fitted to the arm")
    A = arm(gf)
    check("[1] SLEEVE_SECTORS is 16 (the hand-built arm table)", gf.SLEEVE_SECTORS == 16, gf.SLEEVE_SECTORS)
    X, s, t = sleeve()
    share = np.ones(len(X))
    D = gf.fit_sleeve(X, X, share, A)
    Y = X + D
    a, b = Y[:, 1] - 1.40, Y[:, 2]
    full = (s >= 0.10 - 1e-9) & (s <= 0.50 + 1e-9)
    want = 0.052 + 0.0012 * np.cos(6 * t)
    err = np.abs(np.hypot(a, b) - want)[full]
    check("[1] radius = arm 0.04 + 12 mm + 0.3 x detail within 0.5 mm", err.max() < 5e-4, f"max err {err.max()*1000:.3f} mm")
    ang = np.angle(np.exp(1j * (np.arctan2(b, a) - t)))[full]
    check("[1] angle about the arm axis kept within 0.02 rad", np.abs(ang).max() < 0.02, f"{np.abs(ang).max():.4f}")
    worst_c, amps = 0.0, []
    for k in range(10, 51):
        m = np.isclose(s, k * 0.01)
        c = np.array([0.5 * (a[m].max() + a[m].min()), 0.5 * (b[m].max() + b[m].min())])
        worst_c = max(worst_c, float(np.linalg.norm(c)))
        r = np.hypot(a[m] - c[0], b[m] - c[1])
        amps.append(0.5 * (r.max() - r.min()))
    check("[1] every ring centred on the arm axis within 0.5 mm", worst_c < 5e-4, f"{worst_c*1000:.3f} mm")
    amp = float(np.median(amps))
    check("[1] the folds kept at the detail share: amplitude 1.2 +- 0.2 mm", abs(amp - 0.0012) < 2e-4,
          f"{amp*1000:.3f} mm")
    check("[1] not pulled along the arm (s within 0.1 mm)", np.abs(Y[full, 0] - X[full, 0]).max() < 1e-4,
          f"{np.abs(Y[full, 0] - X[full, 0]).max()*1000:.3f} mm")
    check("[1] nothing moves at s = 0 (armhole)", np.abs(D[np.isclose(s, 0.0)]).max() < 1e-12)
    # half way through the blend: the ring at s 0.06 moved to s 0.065 (beta = (0.065 - 0.03) / 0.07 = 0.5)
    Xh = X.copy()
    m = np.isclose(s, 0.06)
    Xh[m, 0] = 0.20 + 0.065
    Dh = gf.fit_sleeve(Xh, Xh, share, A)
    target = Xh[m] + Dh[m] / 0.5
    rr = np.hypot(target[:, 1] - 1.40, target[:, 2])
    err = np.abs(rr - (0.052 + 0.0012 * np.cos(6 * t[m]))).max()
    check("[1] half way through the blend the vertex moves half way to the fitted radius (within 1 mm)",
          err < 1e-3, f"{err*1000:.3f} mm")


def test_auto(gf):
    print("[2] the Auto choice")
    A = arm(gf)
    X, s, t = sleeve()
    share = np.ones(len(X))
    inside = np.hypot(X[:, 1] - 1.40, X[:, 2]) < R
    m = gf.measure_sleeve(X, share, A, inside)
    check("[2] offset_max_m 0.055 .. 0.058 at the forearm",
          m is not None and 0.055 <= m["offset_max_m"] <= 0.058 and m["offset_where"] == "forearm", m)
    check("[2] room p50 -0.5 cm (+- 0.5 mm)", m is not None and abs(m["clear_p50_m"] + 0.005) < 5e-4,
          m and m["clear_p50_m"])
    choice, why = gf.auto_sleeve(m)
    rules = [w["rule"] for w in why]
    check("[2] Auto -> fitted for offset and room", choice == "fitted" and "offset" in rules and "room" in rules,
          (choice, why))
    text = gf.sleeve_reason_text(choice, why)
    check("[2] the reason in plain words",
          any(text.startswith(f"Auto -> Fitted to the arm: the sleeve sits {cm} cm off the forearm and it is as "
                              "thin as the arm") for cm in ("5.6", "5.7")), text)
    G, _s, _t = sleeve(offset=False, radius=0.06, fold=0.0)
    g = gf.measure_sleeve(G, np.ones(len(G)), A, np.zeros(len(G), bool))
    choice, why = gf.auto_sleeve(g)
    check("[2] a good sleeve stays as generated", choice == "generated" and [w["rule"] for w in why] == ["fits"],
          (choice, why, g))
    check("[2] no setting reads auto on both sides", gf.sleeve_choices({}) == {"left": "auto", "right": "auto"},
          gf.sleeve_choices({}))


def test_shards(gf):
    print("[3] stretched strips")
    X0 = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0]])
    F = np.array([[0, 1, 2]])
    region = np.ones(3, bool)
    far = X0.copy()
    far[1, 0] = 0.045
    near = X0.copy()
    near[1, 0] = 0.035
    check("[3] 4.6 cm from 1.4 cm is a shard", bool(gf.sleeve_shards(far, X0, F, region)[0]))
    check("[3] 3.6 cm from 1.4 cm is none (< 3 x)", not bool(gf.sleeve_shards(near, X0, F, region)[0]))
    check("[3] outside the moved region is none", not bool(gf.sleeve_shards(far, X0, F, np.zeros(3, bool))[0]))
    spec = gf.CLOTHING_GATES.get("sleeve_shards")
    check("[3] the gate: max SLEEVE_SHARDS_MAX 6", spec is not None and spec[0] == "max" and spec[1] == 6, spec)
    base = {k: (0.0 if kind == "max" else 1.0) for k, (kind, _l, _t) in gf.CLOTHING_GATES.items()}
    check("[3] 6 strips pass, 7 refuse", gf.gate({**base, "sleeve_shards": 6}, gf.CLOTHING_GATES)[0]
          and not gf.gate({**base, "sleeve_shards": 7}, gf.CLOTHING_GATES)[0])


def test_light(gf):
    print("[4] the arm light")
    a = gf.arm_light({"left": 0.2, "right": 12.0})
    check("[4] green + yellow -> yellow, worst 12", a == {"state": "yellow", "sides": {"left": "green",
                                                                                      "right": "yellow"},
                                                          "worst_cm2": 12.0}, a)
    check("[4] 30 cm2 -> red", gf.arm_light({"left": 30.0})["state"] == "red")
    check("[4] nothing measured -> none", gf.arm_light({})["state"] == "none")


def test_allowance(gf):
    print("[5] the width allowance")

    def run(table, refuse=(), allowance="auto"):
        Q = np.array([[1.0, 0.0, 0.0]])
        calls = []

        def push(Qs):
            return Qs, np.zeros_like(Qs), {"deep_push_share": 0.0, "max_push_m": 0.0}

        def finish(Qs, Qp, disp):
            scale = round(float(Qs[0, 0]), 2)
            calls.append(scale)
            deep, tight = table[scale]
            m = {"deep_push_share": deep, "torso_tight_share": tight, "max_push_m": 0.01}
            ok = scale not in refuse
            return gf.FitResult(garment=None, metrics=m, ok=ok, reasons=[] if ok else ["rigged_inside_share 1 > 0"])

        result, info = gf.scale_retry(Q, push, finish, centre_x=0.0, centre_z=0.0, half_width=10.0,
                                      allowance=allowance)
        return result, info, calls

    tight = {1.0: (0.05, 0.30), 1.02: (0.05, 0.25), 1.04: (0.05, 0.20), 1.06: (0.05, 0.17), 1.08: (0.05, 0.12)}
    _r, info, calls = run(tight)
    check("[5a] the smallest step clearing the trigger: 1.06", info["factor"] == 1.06, info["factor"])
    check("[5a] attempts 1.02 / 1.04 / 1.06, 1.08 never tried",
          [a["scale"] for a in info["allowance"]["attempts"]] == [1.02, 1.04, 1.06], info["allowance"])
    check("[5a] finish calls", calls == [1.0, 1.02, 1.04, 1.06], calls)
    check("[5a] the trigger named", info["allowance"]["trigger"] == ["torso_tight_share"], info["allowance"])
    slow = {1.0: (0.05, 0.30), 1.02: (0.05, 0.25), 1.04: (0.05, 0.22), 1.06: (0.05, 0.21), 1.08: (0.05, 0.20)}
    _r, info, calls = run(slow, refuse=(1.02,))
    check("[5b] nothing clears: the smallest passing improving step 1.04", info["factor"] == 1.04, info)
    _r, info, calls = run({1.0: (0.05, 0.10)})
    check("[5c] no trigger: 1.0 and one finish", info["factor"] == 1.0 and calls == [1.0], (info, calls))
    _r, info, calls = run({1.06: (0.05, 0.3)}, allowance=6)
    check("[5d] fixed +6 %: one fit at 1.06", info["factor"] == 1.06 and calls == [1.06], (info, calls))
    _r, info, calls = run({1.0: (0.2, 0.9)}, allowance=0)
    check("[5d] fixed +0 %: one fit at 1.0, no walk", info["factor"] == 1.0 and calls == [1.0], (info, calls))
    check("[5] never beyond 1.08", max(gf.SCALE_RETRY_STEPS) == 1.08, gf.SCALE_RETRY_STEPS)
    W = gf.widen(np.array([[0.3, 1.2, 0.1]]), 1.08, centre_x=0.0, centre_z=0.0, half_width=10.0)
    check("[5] width only: y kept", np.allclose(W, [[0.324, 1.2, 0.108]]), W.tolist())


def test_settings():
    print("[6] fit settings make the fit due")
    from app.core import garment_fit_settings as fs, garments
    check("[6] normalise", fs.normalise({"sleeves_left": "fitted", "sleeves_right": "bogus", "allowance": 5,
                                         "depth": 5})
          == {"sleeves_left": "fitted", "sleeves_right": "auto", "allowance": "auto", "depth": 0})
    pre_a68 = {"kind": "clothing", "inputs": {"fit_settings": {"sleeves_left": "auto", "sleeves_right": "auto",
                                                              "allowance": 10}}}
    check("[6] a fit made before the depth setting is not due",
          not fs.changed(pre_a68, {fs.SETTINGS_KEY: {"item_a": {"allowance": 10}}}, "item_a"))
    check("[6] ... and due under depth +6 %",
          fs.changed(pre_a68, {fs.SETTINGS_KEY: {"item_a": {"allowance": 10, "depth": 6}}}, "item_a"))
    record = {"kind": "clothing", "inputs": {"fit_settings": fs.defaults()}}
    profile = {fs.SETTINGS_KEY: {"item_a": {"sleeves_left": "fitted"}}}
    check("[6] another setting -> due", fs.changed(record, profile, "item_a"))
    check("[6] the same settings -> not due", not fs.changed(record, {}, "item_a"))
    check("[6] a record without settings reads as the defaults", not fs.changed({"inputs": {}}, {}, "item_a"))
    for bad in ({"colour": "red"}, {"sleeves_left": "baggy"}, {"allowance": 5}, {"allowance": 25}, {"depth": 5},
                {"depth": 25}, {"depth": "auto"}, {"depth": True}, {}):
        try:
            fs.validate(bad)
            ok = False
        except ValueError:
            ok = True
        check(f"[6] validate refuses {bad}", ok)
    check("[6] validate keeps good values", fs.validate({"allowance": 6, "sleeves_right": "wider", "depth": 10})
          == {"allowance": 6, "sleeves_right": "wider", "depth": 10})
    check("[6] validate keeps +20 % (Ruling A76)", fs.validate({"allowance": 20, "depth": 20})
          == {"allowance": 20, "depth": 20})
    check("[6] garments._settings_changed: clothing record due",
          garments._settings_changed("Demo", "item_a", record, profile))
    check("[6] ... a footwear record never", not garments._settings_changed("Demo", "item_a",
                                                                           {**record, "kind": "footwear"}, profile))


def test_old_code():
    print("[7] fails on the old code (8e6d8c65a)")
    old = subprocess.run(["git", "-C", str(ROOT), "show", "8e6d8c65a:app/core/garment_fit.py"], capture_output=True,
                         text=True)
    if old.returncode != 0:
        check("[7] commit 8e6d8c65a readable", False, old.stderr.strip()[:200])
        return
    src = old.stdout
    check("[7] no fit_sleeve there", "def fit_sleeve" not in src)
    check("[7] no sleeve_shards gate there", '"sleeve_shards"' not in src)
    check("[7] clothing fit version 10 there", '"clothing": 10' in src)
    gone = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", "8e6d8c65a:app/core/garment_fit_settings.py"],
                          capture_output=True)
    check("[7] no garment_fit_settings.py there", gone.returncode != 0)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sleeve-fit-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        paths.init_instance(Path(tmp) / "instance")
        from app.core import garment_fit as gf
        test_fit(gf)
        test_auto(gf)
        test_shards(gf)
        test_light(gf)
        test_allowance(gf)
        test_settings()
        test_old_code()
    print(f"\n{len(FAILED)} FAILED" if FAILED else "\nall OK")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
