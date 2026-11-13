#!/usr/bin/env python3
"""HairDeck fit: the XPBD drape below the ear line (``garment_hairdeck.drape_below_ear``, keyword ``drape``, off by
default — ``HAIR_DRAPE_ON``). Plan 2026-11-12 fit-sdf-speed-drape, Task 10.

Usage: ./.venv/bin/python scripts/smoke_hairdeck_drape_xpbd.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first), every GLB is built in this file (the
head-and-neck geometry of ``smoke_hairdeck_drape_width.py``, the GLB packing of ``smoke_garment_hairdeck_fit.py``,
both loaded from their files).

Fixture (metres, +y up, +z front). Body, skin joints [mixamorig:Hips, mixamorig:Spine2, mixamorig:Head]:
- head = UV sphere R 0.1 at (0, 1.6, 0), 61 bands x 120 segments, Head 1;
- neck = closed cylinder radius 0.05 about the y axis, 1.30 .. 1.55, 48 segments x 51 rings + 10 cap rings; its
  vertices at y >= 1.45 Head 1, the rest Spine2 1.
  -> chin (lowest Head > 0.5 vertex) 1.45, top 1.7, cranium threshold 1.45 + 0.6 * 0.25 = 1.60 (the head's upper
  half, as the proxy's), ear line 1.45 + 0.25 * 0.25 = 1.5125, neck back plane z = -0.05.
- proxy = UV sphere r 0.05 at (0, 0.4, 0) in HairDeck's space -> placement scale 2, translation (0, 0.8, 0); every
  fit passes forward_m 0, tilt_deg 0. The hair is built in body space and stored as (p - (0, 0.8, 0)) / 2.
- Cards: ribbons 4 mm wide (two columns), rows every 5 mm along a path. Five hanging cards at azimuths 90, 135,
  180, 225, 270 deg (0 = +z): over the head on a sphere of radius 0.108 from polar angle 20 deg to the equator,
  then straight down at horizontal radius 0.108 to y = ear - 0.10 = 1.4125 (outside the body all the way). One
  NECK card at azimuth 180: radius 0.108 from 20 to 70 deg, then a straight line THROUGH the head's lower back to
  (0, 1.50, -0.02), then down inside the neck to (0, 1.4125, -0.02).
- Short hair (for [D4]): the five hanging cards' head part only, down to polar angle 45 deg (y >= 1.676): every
  vertex above the ear line.

[D1] drape=True: every vertex of the drape=False result with y >= ear (1.5125) is array_equal (they are pinned:
     ``drape_pins``, and the drape returns the pinned bits unchanged).
[D2] drape=True: every hair vertex below the ear line has body_sdf >= CARD_CLEAR_M - 0.001 = 0.003 (the drape keeps
     CARD_CLEAR_M; 1 mm for the voxel field's trilinear slack, VOX_M 3.4 mm).
[D3] drape=True: the neck card's vertices below the head (y < 1.50) end behind the neck's back plane:
     z < -0.05 + CARD_CLEAR_M = -0.046 (the start of each free vertex is its PLACED position, inside the neck at
     z -0.02: 0.03 from the back surface, 0.05 from the sides, 0.07 from the front, so the growing body pushes it
     out backward).
[D4] Short hair, drape=True: ``report.push.drape_xpbd`` == {"skipped": "no_free_vertex"}; garment, metrics and the
     rest of the report equal to drape=False.
[D5] drape=False (and the default, ``HAIR_DRAPE_ON`` False) is byte-equal to commit 71306d21's ``fit_hairdeck`` on
     both fixtures: every garment array's bytes, the metrics, the verdict and the report (no ``drape_xpbd`` key).
Timings of the drape (``t_jit_s``, ``t_run_s``) are printed.
"""
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BASE_COMMIT = "71306d21"
FAILS = []
EAR = 1.5125
LOW = EAR - 0.10
R_HAIR = 0.108
T = np.array([0.0, 0.8, 0.0])
S = 2.0


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def body_glb(width, fit):
    Ps, Fs = width.uv_sphere(0.1, np.array([0.0, 1.6, 0.0]), 61, 120)
    Pc, Fc = width.cylinder(0.05, 1.30, 1.55, 48, 51)
    P = np.vstack([Ps, Pc])
    F = np.vstack([Fs, Fc + len(Ps)])
    head = np.r_[np.ones(len(Ps), bool), Pc[:, 1] >= 1.45 - 1e-9]
    J = np.zeros((len(P), 4), "<u2")
    J[:, 0] = np.where(head, 2, 1)
    W = np.zeros((len(P), 4), "<f4")
    W[:, 0] = 1
    b = fit.Builder()
    attrs = {"POSITION": b.add(P.astype("<f4"), 5126, "VEC3", minmax=True),
             "JOINTS_0": b.add(J, 5123, "VEC4"), "WEIGHTS_0": b.add(W, 5126, "VEC4")}
    ind = b.add(F.astype("<u4").ravel(), 5125, "SCALAR")
    nodes = [{"name": "Armature", "children": [1, 2]},
             {"name": "Body", "mesh": 0, "skin": 0},
             {"name": "mixamorig:Hips", "children": [3]},
             {"name": "mixamorig:Spine2", "children": [4], "translation": [0, 1.3, 0]},
             {"name": "mixamorig:Head", "translation": [0, 0.2, 0]}]
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [2, 3, 4]}], "materials": [{"name": "Skin"}]}
    return b.glb(doc)


def sphere_path(az, th0, th1):
    """Points every ~5 mm on the sphere of radius R_HAIR round the head centre, polar angle th0 -> th1 (deg)."""
    n = max(2, int(math.ceil(R_HAIR * math.radians(th1 - th0) / 0.005)) + 1)
    th = np.radians(np.linspace(th0, th1, n))
    a = math.radians(az)
    return np.stack([R_HAIR * np.sin(th) * math.sin(a), 1.6 + R_HAIR * np.cos(th), R_HAIR * np.sin(th) * math.cos(a)],
                    1)


def line(p, q):
    n = max(2, int(math.ceil(np.linalg.norm(q - p) / 0.005)) + 1)
    return p + (q - p) * np.linspace(0, 1, n)[:, None]


def join(*parts):
    out = [parts[0]]
    for p in parts[1:]:
        out.append(p[1:])
    return np.vstack(out)


def ribbon(path, P, F):
    """Append a 4 mm ribbon along ``path`` (two columns, offset sideways in the horizontal plane) -> vertex ids."""
    tang = np.gradient(path, axis=0)
    side = np.cross(tang, [0.0, 1.0, 0.0])
    bad = np.linalg.norm(side, axis=1) < 1e-9
    side[bad] = np.cross(tang[bad], [0.0, 0.0, 1.0])
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    start = len(P)
    for p, s in zip(path, side):
        P.extend([p - 0.002 * s, p + 0.002 * s])
    for i in range(len(path) - 1):
        a0, a1, b0, b1 = start + 2 * i, start + 2 * i + 1, start + 2 * i + 2, start + 2 * i + 3
        F.extend([[a0, b0, b1], [a0, b1, a1]])
    return np.arange(start, len(P))


def hair(short=False):
    """``(P body space, F, neck card ids or None)``."""
    P, F = [], []
    for az in (90, 135, 180, 225, 270):
        if short:
            ribbon(sphere_path(az, 20, 45), P, F)
            continue
        top = sphere_path(az, 20, 90)
        ribbon(join(top, line(top[-1], np.array([top[-1, 0], LOW, top[-1, 2]]))), P, F)
    neck = None
    if not short:
        top = sphere_path(180, 20, 70)
        mid = np.array([0.0, 1.50, -0.02])
        neck = ribbon(join(top, line(top[-1], mid), line(mid, np.array([0.0, LOW, -0.02]))), P, F)
    return np.array(P, np.float64), np.array(F, np.int64), neck


def hair_glbs(fit, P, F):
    Pl = (P - T) / S
    C = np.tile(np.array([0.25, 0.25, 0.25, 1.0], "<f4"), (len(P), 1))
    U = np.zeros((len(P), 2), "<f4")
    out = []
    for with_proxy in (False, True):
        b = fit.Builder()
        attrs = {"POSITION": b.add(Pl.astype("<f4"), 5126, "VEC3", minmax=True),
                 "COLOR_0": b.add(C, 5126, "VEC4"), "TEXCOORD_0": b.add(U, 5126, "VEC2")}
        ind = b.add(F.astype("<u4").ravel(), 5125, "SCALAR")
        nodes = [{"name": "hair_cards", "mesh": 0}]
        meshes = [{"name": "hair_cards", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}]
        mats = [{"name": "hair", "doubleSided": True}]
        if with_proxy:
            Pp, Fp = fit.uv_sphere(0.05, (0, 0.4, 0), 45, 96)
            pa = b.add(Pp.astype("<f4"), 5126, "VEC3", minmax=True)
            pi = b.add(Fp.astype("<u4").ravel(), 5125, "SCALAR")
            nodes.append({"name": "head_proxy", "mesh": 1})
            meshes.append({"name": "head_proxy", "primitives": [{"attributes": {"POSITION": pa}, "indices": pi,
                                                                 "material": 1}]})
            mats.append({"name": "head", "doubleSided": False})
        doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
               "nodes": nodes, "meshes": meshes, "materials": mats}
        out.append(b.glb(doc))
    return out[0], out[1]


GARMENT_KEYS = ("positions", "normals", "uvs", "indices", "joints", "weights", "colors")


def blob(res, drop_xpbd=False):
    """Everything a fit returns, as comparable bytes / JSON."""
    rep = json.loads(json.dumps(res.report, default=str, sort_keys=True))
    if drop_xpbd:
        rep["push"].pop("drape_xpbd", None)
    g = res.garment
    arrays = {k: (np.asarray(getattr(g, k)).dtype.str, np.asarray(getattr(g, k)).shape,
                  np.asarray(getattr(g, k)).tobytes()) for k in GARMENT_KEYS}
    rest = json.dumps({"names": list(g.joint_names), "parents": g.joint_parents, "material": g.material,
                       "binds": {k: np.asarray(v).tobytes().hex() for k, v in (g.joint_binds or {}).items()}},
                      default=str, sort_keys=True)
    return arrays, rest, json.dumps(res.metrics, sort_keys=True, default=str), res.ok, list(res.reasons), \
        json.dumps(rep, sort_keys=True)


def load_base(tmp: Path):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/garment_hairdeck.py"],
                         check=True, capture_output=True, text=True).stdout
    path = tmp / "garment_hairdeck_base.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("garment_hairdeck_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-xpbd-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import garment_hairdeck as gh
        from app.core.garment_fit import SDF_MARGIN_M, VOX_M, body_sdf, ear_line_height
        from app.core.glb_mesh import body_arrays

        width, fit = load_script("smoke_hairdeck_drape_width"), load_script("smoke_garment_hairdeck_fit")
        bglb = body_glb(width, fit)
        body = body_arrays(bglb)
        check(abs(ear_line_height(body) - EAR) < 1e-6, f"fixture: ear line {ear_line_height(body):.5f} ({EAR})")
        check(gh.HAIR_DRAPE_ON is False, "HAIR_DRAPE_ON is False (off until accepted)")
        P, F, neck = hair()
        nohead, proxy = hair_glbs(fit, P, F)
        kw = dict(colour_target=None, forward_m=0.0, tilt_deg=0.0)

        off = gh.fit_hairdeck(nohead, proxy, bglb, drape=False, **kw)
        on = gh.fit_hairdeck(nohead, proxy, bglb, drape=True, **kw)
        Xo = np.asarray(off.garment.positions)[:len(P)]
        Xn = np.asarray(on.garment.positions)[:len(P)]
        info = on.report["push"].get("drape_xpbd") or {}
        print("       drape_xpbd " + json.dumps({k: info.get(k) for k in ("n", "n_orig", "pinned", "free", "lra",
                                                                         "constraints", "colours", "t_jit_s",
                                                                         "t_run_s", "vmax_tail",
                                                                         "min_clear_after_m", "moved_max_m")}))
        # [D1]
        head = Xo[:, 1] >= EAR
        check(head.any() and (~head).any(), f"fixture: {int(head.sum())} vertices above, {int((~head).sum())} below")
        check(np.array_equal(Xn[head], Xo[head]), "[D1] every vertex at or above the ear line equals drape=False")
        moved = np.linalg.norm(Xn - Xo, axis=1)
        check(moved[~head].max() > 0.001, f"[D1] the drape moved the hair below the ear: max {moved.max():.4f}")
        # [D2]
        lo, hi = Xn.min(0) - SDF_MARGIN_M, Xn.max(0) + SDF_MARGIN_M
        sdf = body_sdf(body.positions, body.faces, vox=VOX_M, bounds=(lo, hi))
        d = sdf.sample(Xn[~head])
        check(d.min() >= gh.CARD_CLEAR_M - 0.001, f"[D2] body_sdf below the ear >= {gh.CARD_CLEAR_M - 0.001}: min "
                                                  f"{d.min():.5f} (drape=False: {sdf.sample(Xo[~head]).min():.5f})")
        # [D3]
        nb = neck[Xn[neck, 1] < 1.50]
        check(len(nb) > 0 and Xn[nb, 2].max() < -0.046,
              f"[D3] the neck card below the head ends behind the neck: z max {Xn[nb, 2].max():.4f} < -0.046 "
              f"(n {len(nb)}; its placed z -0.02)")

        # [D4] short hair
        Ps, Fs, _ = hair(short=True)
        check(bool(((Ps[:, 1] - 0.0) >= EAR + 0.1).all()), "fixture: the short hair lies far above the ear line")
        s_nohead, s_proxy = hair_glbs(fit, Ps, Fs)
        s_off = gh.fit_hairdeck(s_nohead, s_proxy, bglb, drape=False, **kw)
        s_on = gh.fit_hairdeck(s_nohead, s_proxy, bglb, drape=True, **kw)
        check(s_on.report["push"].get("drape_xpbd") == {"skipped": "no_free_vertex"},
              f"[D4] drape_xpbd {s_on.report['push'].get('drape_xpbd')}")
        check(blob(s_on, drop_xpbd=True) == blob(s_off), "[D4] the rest equals drape=False")

        # [D5] byte-equal to the base commit
        base = load_base(Path(tmp))
        for label, nh, px, res in (("long", nohead, proxy, off), ("short", s_nohead, s_proxy, s_off)):
            ref = base.fit_hairdeck(nh, px, bglb, **kw)
            dflt = gh.fit_hairdeck(nh, px, bglb, **kw)
            check(blob(res) == blob(ref), f"[D5] {label}: drape=False byte-equal to {BASE_COMMIT}")
            check(blob(dflt) == blob(ref), f"[D5] {label}: the default (HAIR_DRAPE_ON False) byte-equal to "
                                           f"{BASE_COMMIT}")
            check("drape_xpbd" not in res.report["push"], f"[D5] {label}: no drape_xpbd key without the drape")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
