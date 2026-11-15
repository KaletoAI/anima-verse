#!/usr/bin/env python3
"""HairDeck up/down correction and the forward tilt to 30 deg (Ruling A85, ``app/core/garment_hairdeck.py``).

Usage: ./.venv/bin/python scripts/smoke_hairdeck_up_tilt.py

No world, no server, no hub, no network: a throwaway storage dir (``paths.init`` first); the meshes are the synthetic
fixtures of scripts/smoke_hairdeck_placement.py (imported) or built here. [2] runs ``node`` on the Game-Admin's
``hairstylesModel.ts`` (bundled with the workspace's esbuild) for the live-preview parity. The fails-on-old
proof reads ``app/core/garment_hairdeck.py`` at ``bed1e13a1`` (before A85) with ``git show``.

User request 2026-11-15 (Vallerie, HairDeck): "Korrektur hoch / runter, Neigung nach vorn muss bis 30 gehen".

[1] Limits: forward tilt -15 .. +30 deg (``TILT_BACK_LIMIT_DEG`` 15, ``TILT_FORWARD_LIMIT_DEG`` 30), up/down +-0.03 m
    (``UP_LIMIT_M``), the auto tilt still 0 .. ``AUTO_TILT_MAX_DEG`` 15. ``_check_manual``: tilt 30 / -15 / up +-0.03
    pass; tilt 30.5 / -15.5, up +-0.031, up nan -> ValueError. ``garment_hair.placement_limits()`` =
    {forward_m 0.03, tilt_deg [-15, 30], up_m 0.03, width_scale [0.5, 1.5]}.
    bed1e13a1 refuses tilt 30 (its limit was +-15) -> the old code FAILS "tilt 30 passes".
[2] ``adjust_placement`` with up: pivot p = (0, 1.56, 0.03), Q = p + (0, 0.1, 0) = (0, 1.66, 0.03), forward 0.006,
    tilt 30, up 0.01: R(30)(0, 0.1, 0) = (0, 0.1 cos 30, 0.1 sin 30) = (0, 0.0866025, 0.05) ->
    (0, 1.56 + 0.0866025 + 0.01, 0.03 + 0.05 + 0.006) = (0, 1.6566025, 0.086) (+- 1e-7) — the same case
    scripts/check_hairstyles_ui.mjs [5] maps through the preview's ``placementMap``.
    up 0 is bit for bit the call without it, and bit for bit bed1e13a1's ``adjust_placement`` (seeded random points,
    tilt 6.25, forward 0.004). bed1e13a1 has no ``up_m`` -> TypeError: the old code FAILS "up moves the hair".
    Preview parity: 200 seeded points Q around the head, fitted (f0 0.004, a0 3.7, u0 0.012), dragged
    (f1 0.011, a1 27.5, u1 -0.018), width 1: ``placementMap(adjust(Q; fitted))`` = ``adjust(Q; dragged)``
    (max |diff| <= 1e-12: both are the same rigid map, the preview undoes u0 / f0, turns by a1 - a0, adds f1 / u1).
[3] Rule for up with the auto tilt (rule B): the tilt aims at target + up. The arc of smoke_hairdeck_placement [4]
    (pivot (-0.00336, 1.6054, 0.06191), radius 0.095, elevation 20..90 deg; the phi = 20 point is the hairline:
    hairline(t, up) = 1.6054 + 0.095 sin(20 - t) + up) on the profile body (target 1.63325), with ``_push`` replaced
    by a lift of every point by 0.006 (as there):
    up 0: two rounds, tilt 6.7029, pushed 1.63325 (smoke_hairdeck_placement [5]).
    up +0.01: goal 1.64325. Round 1 aims at 1.64325: sin(20 - t) = (1.64325 - 0.01 - 1.6054) / 0.095 = 0.293158
      -> t = 2.9525; pushed 1.64925, miss 0.006; round 2 aims at 1.63725: sin = 0.23 -> t = 6.7029, pushed 1.64325
      = goal. So the same tilt 6.703 (+- 0.02), the hairline exactly 0.01 higher: 1.64325 (+- 0.0002); report up_m
      0.01 "manual", hairline_image_y = the hairline placed without tilt and up, not pushed = 1.6054 + 0.095 sin 20 =
      1.6378919 (r5: 1.63789).
    up -0.01: goal 1.62325, the same tilt 6.703, pushed 1.62325 (+- 0.0002).
    Automatic (up None): up_m 0.0 "none", no hairline_image_y.
    Manual tilt 30 (forward 0.006), up None: one round, tilt 30 "manual", pushed = 1.6054 + 0.095 sin(-10) + 0.006
      = 1.6054 - 0.0164966 + 0.006 = 1.5949034 (the strip test z > 0.11775: the phi 20 point after 30 deg has
      z = 0.06191 + 0.095 cos(-10) + 0.006 = 0.16147, in it; phi 21 .. 50 points lie higher); hairline_image_y 1.63789.
    Manual tilt 0, no up: no hairline_image_y — the pushed hairline decides as before, so a fit with a stored manual
    tilt 0 is rebuilt bit for bit (scripts/smoke_hairdeck_drape_xpbd [D5]).
[4] The face clearing decides "fringe" on the image's hairline: with a manual tilt (not 0) or up the fit hands
    ``hairline_image_y`` to both ``_clear_face`` calls, without them ``hairline_pushed_y`` (as before). Checked on the
    sphere fixture of smoke_garment_hairdeck_fit with ``_place_and_push`` wrapped to put a marker 1.234 into the
    report and ``_clear_face`` wrapped to record its ``hairline_y``. ``_clear_face`` itself (unchanged): a hairline at
    or below the brow is skipped "fringe".
[5] The cap at the back under a manual forward tilt (``tilt_back_drop``, ``back_weight``, ``cap_floor``).
    Fixture: body points on a cylinder radius 0.1 about (cx, cz) = (0, 0), azimuth +-150 .. 180 deg every 2 deg,
    y 1.400 .. 1.700 every 1 mm; hair points radius 0.106, the same azimuths, y from 1.555 up every 2 mm. A body
    point is covered when a hair point lies within 0.012: the nearest one is at the same azimuth, 0.006 out, so up
    to sqrt(0.012^2 - 0.006^2) = 0.0103923 below 1.555 -> covered iff y >= 1.5446077. Hairline 1.60, depth 0.2:
    bands [1.59, 1.60) .. [1.55, 1.56) fully covered; [1.54, 1.55) has 1.545 .. 1.549 covered, 5 of 10 rows = 0.5
    < 0.9 -> stop at 1.55: drop 0.05 (+- 1e-9) when the cap allows it: tilt 30 -> at most 0.2 sin 30 = 0.1 -> 0.05;
    tilt 15 -> at most 0.2 sin 15 = 0.0517638 -> 0.05; tilt 5 -> at most 0.0174311 -> 0.0174311; tilt 0 / -5 -> 0.
    Hair from 1.605 up (none below the hairline band's top): band [1.59, 1.60) has 1.595 .. 1.599 covered (5/10)
    -> 0. ``back_weight``: azimuth 85 -> 0, 132.5 -> 0.5, 180 -> 1. ``cap_floor(1.60, None, (0, 0), 0.05)`` at
    azimuth 180 -> 1.55, 132.5 -> 1.575, 60 / 0 -> 1.60; with a face lift (face 1.64) the face part stays 1.64 at
    azimuth 0. Drop 0 -> bit for bit bed1e13a1's ``cap_floor`` (points all round, with and without a face lift).
    In the fit only a MANUAL tilt lowers the cap (an automatic tilt <= 15 never: every fit stored today has
    ``tilt_deg`` None — automatic — and is rebuilt bit for bit).
"""
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

BEFORE_A85 = "bed1e13a1"
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def old_module(tmp, commit):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:app/core/garment_hairdeck.py"],
                         check=True, capture_output=True, text=True).stdout
    name = f"garment_hairdeck_{commit}"
    path = Path(tmp) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def refuses(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


NODE_MAP = r"""
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const [, , esbuildDir, src, out, dataFile] = process.argv;
const esbuild = createRequire(import.meta.url)(esbuildDir);
await esbuild.build({ entryPoints: [src], outfile: out, bundle: true, format: 'esm', platform: 'neutral',
  logLevel: 'silent' });
const m = await import('file://' + out);
const d = JSON.parse(readFileSync(dataFile, 'utf8'));
const map = m.placementMap(d.pivot, d.fitted, d.draft, 0, 0.08);
process.stdout.write(JSON.stringify(d.points.map(map)));
"""


def preview_map(tmp, pivot, fitted, draft, points):
    esbuild = next((d for d in (ROOT / "node_modules" / "esbuild", ROOT / "frontend" / "node_modules" / "esbuild",
                                ROOT / "client3d" / "node_modules" / "esbuild") if d.is_dir()), None)
    if esbuild is None:
        print("    esbuild not found (npm install)")
        return None
    script = Path(tmp) / "map.mjs"
    script.write_text(NODE_MAP)
    data = Path(tmp) / "data.json"
    data.write_text(json.dumps({"pivot": list(pivot), "fitted": fitted, "draft": draft,
                                "points": np.asarray(points).tolist()}))
    res = subprocess.run(["node", str(script), str(esbuild), str(ROOT / "frontend/src/tabs/characters/hairstylesModel.ts"),
                          str(Path(tmp) / "model.mjs"), str(data)], capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        print(res.stderr[-800:])
        return None
    return np.array(json.loads(res.stdout), np.float64)


def back_fixture(hair_from):
    az = np.radians(np.concatenate([np.arange(150, 181, 2.0), -np.arange(150, 180, 2.0)]))
    ys = np.round(np.arange(1400, 1701) / 1000.0, 3)
    P = np.array([(0.1 * math.sin(a), y, 0.1 * math.cos(a)) for a in az for y in ys])
    hy = np.arange(hair_from, 1.7001, 0.002)
    H = np.array([(0.106 * math.sin(a), y, 0.106 * math.cos(a)) for a in az for y in hy])
    return P, H


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-up-tilt-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import garment_hairdeck as gh
        from app.core import garment_hair
        old = old_module(tmp, BEFORE_A85)

        # [1]
        print("[1] limits")
        check(gh.TILT_FORWARD_LIMIT_DEG == 30.0 and gh.TILT_BACK_LIMIT_DEG == 15.0 and gh.UP_LIMIT_M == 0.03
              and gh.AUTO_TILT_MAX_DEG == 15.0, "tilt -15 .. +30, up +-0.03, auto tilt <= 15")
        ok = [not refuses(lambda kw=kw: gh._check_manual(**kw)) for kw in (
            {"forward_m": None, "tilt_deg": 30.0}, {"forward_m": None, "tilt_deg": -15.0},
            {"forward_m": None, "tilt_deg": None, "up_m": 0.03}, {"forward_m": None, "tilt_deg": None, "up_m": -0.03})]
        check(all(ok), f"tilt 30 / -15, up +-0.03 pass ({ok})")
        bad = [refuses(lambda kw=kw: gh._check_manual(**kw)) for kw in (
            {"forward_m": None, "tilt_deg": 30.5}, {"forward_m": None, "tilt_deg": -15.5},
            {"forward_m": None, "tilt_deg": None, "up_m": 0.031}, {"forward_m": None, "tilt_deg": None, "up_m": -0.031},
            {"forward_m": None, "tilt_deg": None, "up_m": float("nan")})]
        check(all(bad), f"tilt 30.5 / -15.5, up +-0.031 / nan refused ({bad})")
        check(garment_hair.placement_limits() == {"forward_m": 0.03, "tilt_deg": [-15.0, 30.0], "up_m": 0.03,
                                                  "width_scale": [0.5, 1.5]},
              f"placement_limits {garment_hair.placement_limits()}")
        check(refuses(lambda: old._check_manual(None, 30.0)),
              f"{BEFORE_A85} refuses tilt 30: 'tilt 30 passes' fails on the old code")

        # [2]
        print("[2] adjust_placement with up, preview parity")
        p = np.array([0.0, 1.56, 0.03])
        A = gh.adjust_placement(np.array([[0.0, 1.66, 0.03]]), p, 0.006, 30.0, 0.01)
        check(np.allclose(A[0], [0, 1.6566025, 0.086], atol=1e-7), f"parity case (0, 1.6566025, 0.086): {A[0]}")
        rng = np.random.default_rng(85)
        Q = p + rng.uniform(-0.12, 0.12, (200, 3))
        new0 = gh.adjust_placement(Q, p, 0.004, 6.25, 0.0)
        check(np.array_equal(new0, gh.adjust_placement(Q, p, 0.004, 6.25)), "up 0 = the call without it, bit for bit")
        check(np.array_equal(new0, old.adjust_placement(Q, p, 0.004, 6.25)), f"up 0 = {BEFORE_A85}, bit for bit")
        try:
            old.adjust_placement(Q, p, 0.004, 6.25, 0.01)
            old_moves = True
        except TypeError:
            old_moves = False
        check(not old_moves, f"{BEFORE_A85} has no up_m (TypeError): 'up moves the hair' fails on the old code")
        up = gh.adjust_placement(Q, p, 0.004, 6.25, 0.01)
        check(np.allclose(up - new0, [0, 0.01, 0], atol=1e-15), "up 0.01 adds 0.01 to y, nothing else")
        fitted = {"forward_m": 0.004, "tilt_deg": 3.7, "width_scale": 1, "up_m": 0.012}
        draft = {"forward_m": 0.011, "tilt_deg": 27.5, "width_scale": 1, "up_m": -0.018}
        A0 = gh.adjust_placement(Q, p, 0.004, 3.7, 0.012)
        A1 = gh.adjust_placement(Q, p, 0.011, 27.5, -0.018)
        M = preview_map(tmp, p, fitted, draft, A0)
        diff = None if M is None else float(np.abs(M - A1).max())
        check(diff is not None and diff <= 1e-12, f"placementMap(adjust(fitted)) = adjust(dragged): max diff {diff}")

        # [3]
        print("[3] up with the auto tilt (rule B), the image hairline")
        import smoke_hairdeck_placement as hp
        P, head_v = hp.profile_body()
        body = SimpleNamespace(positions=P)
        F = np.zeros((0, 3), np.int64)
        H = hp.arc()
        real_push = gh._push
        gh._push = lambda Q, F, U, body: {"Qp": np.asarray(Q) + [0, 0.006, 0], "disp": np.zeros((len(Q), 3))}
        try:
            def run(**kw):
                return gh._place_and_push(H, hp.PIVOT, F, None, body, head_v, hp.CHIN, hp.CROWN,
                                          kw.pop("forward_m", None), kw.pop("tilt_deg", None), **kw)[1]
            base = run()
            check(near(base["tilt_deg"], 6.7029, 0.02) and near(base["hairline_pushed_y"], 1.63325, 2e-4)
                  and base["up_m"] == 0.0 and base["up_source"] == "none" and "hairline_image_y" not in base,
                  f"up None: tilt 6.703, pushed 1.63325, up 0 none, no image hairline ({base['tilt_deg']}, "
                  f"{base['hairline_pushed_y']})")
            for u, want in ((0.01, 1.64325), (-0.01, 1.62325)):
                pl = run(up_m=u)
                check(near(pl["tilt_deg"], 6.7029, 0.02) and near(pl["hairline_pushed_y"], want, 2e-4)
                      and pl["up_m"] == u and pl["up_source"] == "manual" and pl["rounds"] == 2,
                      f"up {u}: same tilt 6.703, pushed {want} ({pl['tilt_deg']}, {pl['hairline_pushed_y']}, "
                      f"rounds {pl['rounds']})")
                check(pl.get("hairline_image_y") == 1.63789, f"up {u}: hairline_image_y 1.63789 "
                      f"({pl.get('hairline_image_y')})")
            pl = run(forward_m=0.006, tilt_deg=30.0)
            check(pl["rounds"] == 1 and pl["tilt_deg"] == 30.0 and pl["tilt_source"] == "manual"
                  and near(pl["hairline_pushed_y"], 1.5949034, 1e-5) and pl.get("hairline_image_y") == 1.63789,
                  f"manual 30: pushed 1.5949034, image 1.63789 ({pl['hairline_pushed_y']}, {pl.get('hairline_image_y')})")
            pl = run(forward_m=0.006, tilt_deg=0.0)
            check("hairline_image_y" not in pl, "manual 0, no up: no image hairline (the pushed one decides)")
        finally:
            gh._push = real_push

        # [4]
        print("[4] the face clearing decides on the image's hairline")
        import smoke_garment_hairdeck_fit as fx
        body_glb = fx.body_glb()
        nohead, proxy = fx.hair_glbs(inner=False)
        real_pp, real_cf = gh._place_and_push, gh._clear_face
        seen = []

        def marked_pp(*a, **kw):
            push, pl = real_pp(*a, **kw)
            if "hairline_image_y" in pl:
                pl["hairline_image_y"] = 1.234
            return push, pl

        def recording_cf(Fw, Qp, sdf, body, head_w, landmarks, chin, hairline_y, **kw):
            seen.append(hairline_y)
            return real_cf(Fw, Qp, sdf, body, head_w, landmarks, chin, hairline_y, **kw)
        gh._place_and_push, gh._clear_face = marked_pp, recording_cf
        try:
            res = gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=None, tilt_deg=20.0)
            check(seen and all(v == 1.234 for v in seen), f"manual tilt: _clear_face gets hairline_image_y ({seen})")
            seen.clear()
            res = gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=None, up_m=0.01)
            check(seen and all(v == 1.234 for v in seen), f"manual up: _clear_face gets hairline_image_y ({seen})")
            seen.clear()
            res = gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=None)
            want = res.report["placement"]["hairline_pushed_y"]
            check(seen and all(v == want for v in seen), f"automatic: _clear_face gets hairline_pushed_y {want} "
                  f"({seen})")
        finally:
            gh._place_and_push, gh._clear_face = real_pp, real_cf
        th = np.radians(np.arange(0, 181, 6.0))[:, None]
        ph = np.radians(np.arange(0, 360, 6.0))[None, :]
        sph = (np.stack([np.sin(th) * np.cos(ph), np.cos(th) + 0 * ph, np.sin(th) * np.sin(ph)], -1)
               .reshape(-1, 3) * 0.1 + [0, 1.6, 0])
        sb = SimpleNamespace(positions=sph)
        _, rep = gh._clear_face(np.zeros((0, 3), np.int64), sph[:3], None, sb, np.ones(len(sph)),
                                {"brow_y": 1.62}, 1.5, 1.62)
        check(rep.get("skipped") == "fringe", f"_clear_face: hairline at the brow -> fringe kept ({rep})")

        # [5]
        print("[5] the cap at the back under a manual forward tilt")
        Pb, Hb = back_fixture(1.555)
        hv = np.ones(len(Pb), bool)
        drops = {t: gh.tilt_back_drop(t, 0.2, Pb, hv, Hb, (0.0, 0.0), 1.60) for t in (30.0, 15.0, 5.0, 0.0, -5.0)}
        print("   ", drops)
        check(near(drops[30.0], 0.05, 1e-9) and near(drops[15.0], 0.05, 1e-9), "tilt 30 / 15: down to 1.55, drop 0.05")
        check(near(drops[5.0], 0.2 * math.sin(math.radians(5)), 1e-9), "tilt 5: capped at 0.2 sin 5 = 0.0174311")
        check(drops[0.0] == 0.0 and drops[-5.0] == 0.0, "tilt 0 / back: no drop")
        Pb2, Hb2 = back_fixture(1.605)
        check(gh.tilt_back_drop(30.0, 0.2, Pb2, np.ones(len(Pb2), bool), Hb2, (0.0, 0.0), 1.60) == 0.0,
              "hair ending above the hairline: no drop")
        pts = np.array([[math.sin(math.radians(a)), 1.6, math.cos(math.radians(a))] for a in (85, 132.5, 180, 60, 0)])
        check(np.allclose(gh.back_weight(pts, (0.0, 0.0)), [0, 0.5, 1, 0, 0], atol=1e-12), "back_weight 0 / 0.5 / 1")
        fl = gh.cap_floor(1.60, None, (0.0, 0.0), 0.05)(pts)
        check(np.allclose(fl, [1.60, 1.575, 1.55, 1.60, 1.60], atol=1e-12), f"cap_floor with drop {fl}")
        fl2 = gh.cap_floor(1.60, 1.64, (0.0, 0.0), 0.05)(pts)
        check(near(float(fl2[4]), 1.64, 1e-12) and near(float(fl2[2]), 1.55, 1e-12), f"face lift kept in front {fl2}")
        ring = np.array([[0.1 * math.sin(math.radians(a)), y, 0.1 * math.cos(math.radians(a))]
                         for a in range(-180, 180, 7) for y in (1.55, 1.6, 1.65)])
        same = all(np.array_equal(gh.cap_floor(1.60, f, (0.01, -0.02))(ring), old.cap_floor(1.60, f, (0.01, -0.02))(ring))
                   and np.array_equal(gh.cap_floor(1.60, f, (0.01, -0.02), 0.0)(ring),
                                      old.cap_floor(1.60, f, (0.01, -0.02))(ring)) for f in (None, 1.64))
        check(same, f"drop 0 = {BEFORE_A85}'s cap_floor, bit for bit")

    print()
    print("FAILED: " + "; ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
