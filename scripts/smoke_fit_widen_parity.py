#!/usr/bin/env python3
"""Ruling A48c: the fit allowance's widening has ONE rule — ``garment_fit.widen`` (Python, the fit) — and one port
for the mesh view's live preview (``frontend/src/tabs/characters/fitWiden.ts``: ``widenPoint`` / ``widenInPlace``).
This smoke holds the two together on a synthetic mesh, with the numbers derived by hand, and checks the frame
mapping ``garment_mesh_view.widen_axis`` relies on. Ruling A68 adds the depth allowance's rule
(``garment_fit.depth_shift`` / ``depth_ease``; ported as ``depthShift`` / ``easeInPlace``) — sections [4]..[6].

Usage:
    ./.venv/bin/python scripts/smoke_fit_widen_parity.py

No server, no world, no storage: pure functions only. The TypeScript module is bundled by esbuild (root
``node_modules``, else ``frontend/`` or ``client3d/``) and run by ``node`` on the same points.

THE CASES, DERIVED BY HAND (the rule: z' = cz + (z − cz)·s; x' = x + (s − 1)·clip(x − cx, −hw, hw); y' = y)
--------------------------------------------------------------------------------------------------------------
Axis cx 0.1, cz −0.05, half width hw 0.2, scale s 1.06 (s − 1 = 0.06):
[1] p1 (0.25, 1.0, 0.05): dx 0.15 lies within hw -> x' = 0.25 + 0.06 · 0.15 = 0.259; z' = −0.05 + 0.10 · 1.06 =
    0.056; y' 1.0.
    p2 (0.6, 0.5, −0.05): dx 0.5, clipped to 0.2 -> x' = 0.6 + 0.012 = 0.612 (a sleeve beyond hw is shifted, not
    stretched); z' = −0.05 (on the axis depth).
    p3 (−0.3, 2.0, −0.25): dx −0.4, clipped to −0.2 -> x' = −0.3 − 0.012 = −0.312; z' = −0.05 + (−0.2) · 1.06 =
    −0.262.
    p4 (0.1, 0.7, −0.05) on the axis: unchanged. Scale 1.0: every point unchanged.
[2] Python and TypeScript agree on those four points (|diff| ≤ 1e-12) and on a 24 × 10 cylinder of radius 0.3
    around x 0.05, z −0.02, y 0 .. 0.9 at s 1.10 with the axis cx 0.1, cz −0.05, hw 0.204 (points on both sides of
    hw): every coordinate within 1e-12 (JS in Float64Array), y unchanged.
[3] The mesh-frame axis (``widen_axis``): with a placement Q = s·P + t (s 0.2, t (0.3, 1.0, −0.1)) widening the
    PLACED points about the body axis (cx_b, cz_b, hw_b) = (0.32, −0.11, 0.0408) equals s·(widen of P about
    ((cx_b − tx)/s, (cz_b − tz)/s, hw_b/s) = (0.1, −0.05, 0.204)) + t, at s 1.08, within 1e-12 — the identity
    the server's axis in the mesh frame stands on.

RULING A68 — THE DEPTH RULE (z' = z + e·wz·wx·wy; wz = clip((z − cz)/r, −1, 1),
wx = clip((xl − |x − cx|)/r, 0, 1), wy = clip((yl − y)/r, 0, 1); x, y unchanged). Frame cx 0, cz 0.02, xl 0.12, yl 1.3, ramp r 0.03, ease e 0.01:
[4] q1 (0, 1.0, 0.15) in front: wz 1 (0.13/0.03 clipped), wx 1 (0.12/0.03 clipped), wy 1 -> z' 0.16.
    q2 (0.05, 1.0, −0.10) behind: wz −1, wx clip(0.07/0.03) 1, wy 1 -> z' −0.11.
    q3 (0.0, 1.0, 0.035) at the side of the depth centre: wz 0.015/0.03 0.5 -> z' 0.035 + 0.005 = 0.04.
    q4 (0.105, 1.0, 0.15) toward the sleeve: wx (0.12 − 0.105)/0.03 0.5 -> z' 0.155.
    q5 (0.13, 1.0, 0.15) a sleeve, beyond xl: wx 0 -> unchanged. q6 (0.0, 1.29, 0.15) near the collar: wy
    0.01/0.03 = 1/3 -> z' 0.15 + 0.01/3. q7 (0.0, 1.35, −0.10) the neck opening, above yl: unchanged.
    Ease 0: every point unchanged. TypeScript = Python on q1..q7 (|diff| ≤ 1e-12) and on the cylinder of [2] at
    e 0.012 with the frame (0.1, −0.05, xl 0.2, yl 0.6, r 0.03) — points on both sides of every ramp.
[5] A CYLINDER body (radius R 0.10 about the y axis; the gap of a point = sqrt(x² + z²) − R) under a piece of
    radius 0.112 (12 mm of room), frame cx 0, cz 0, xl 0.2, yl 2, r 0.03, ease at +10 % of the body's half depth
    0.10 = 0.010: the front point (0, 1, 0.112) -> (0, 1, 0.122), gap 12 -> 22 mm; the back point (0, 1, −0.112)
    -> −0.122, 22 mm; the side point (0.112, 1, 0) keeps wz 0 -> 12 mm (the sides stay as they are).
[6] An ELLIPTIC TORSO, half width a 0.15 in x and half depth b 0.10 in z, its own depth centre at z c0 0.03 (the
    bone axis behind it at z 0 plays no part: the rule's centre is the torso's middle). A piece 12 mm off it on the
    minor axis: front (0, 1, c0 + b + 0.012) = (0, 1, 0.142), back (0, 1, c0 − b − 0.012) = (0, 1, −0.082). On the
    minor axis outside an ellipse the nearest point is its co-vertex, so the gap is the z distance: 12 mm each.
    Depth +6 % of b: e 0.006 -> front z' 0.148, back −0.088 -> 18 mm each, the same on both sides (about the
    torso's own centre — about the bone axis at z 0 a SCALE would have moved the front 0.142 / 0.082 = 1.73× as
    far as the back).
    The x of every point unchanged; TypeScript gives the same four z values.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + (f": {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


JS = r"""
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
const [root, input] = process.argv.slice(2);
const require_ = createRequire(join(root, 'scripts', 'x.js'));
let esbuild = null;
for (const cand of ['esbuild', join(root, 'node_modules/esbuild'), join(root, 'frontend/node_modules/esbuild'),
                    join(root, 'client3d/node_modules/esbuild')]) {
  try { esbuild = require_(cand); break } catch { /* next */ }
}
if (!esbuild) { console.error('esbuild not found'); process.exit(2) }
const dir = mkdtempSync(join(tmpdir(), 'smoke-fit-widen-'));
const file = join(dir, 'm.mjs');
await esbuild.build({ entryPoints: [join(root, 'frontend/src/tabs/characters/fitWiden.ts')], outfile: file,
  bundle: true, format: 'esm', platform: 'neutral', logLevel: 'silent', absWorkingDir: root });
const m = await import('file://' + file);
rmSync(dir, { recursive: true, force: true });
const jobs = JSON.parse(readFileSync(input, 'utf8'));
const out = jobs.map((j) => {
  const flat = Float64Array.from(j.points.flat());
  if (j.ease != null) {
    m.easeInPlace(flat, j.ease, j.axis);
    const dz = j.points.map((p) => m.depthShift(p[0], p[1], p[2], j.ease, j.axis));
    return { inPlace: Array.from(flat), shift: dz, depthEase: m.depthEase(j.axis, 10) };
  }
  m.widenInPlace(flat, j.scale, j.axis);
  const pts = j.points.map((p) => m.widenPoint(p[0], p[1], p[2], j.scale, j.axis));
  return { inPlace: Array.from(flat), point: pts.flat() };
});
console.log(JSON.stringify(out));
"""


def run_js(jobs):
    with tempfile.TemporaryDirectory(prefix="smoke-fit-widen-") as d:
        script = Path(d) / "run.mjs"
        script.write_text(JS)
        data = Path(d) / "in.json"
        data.write_text(json.dumps(jobs))
        r = subprocess.run(["node", str(script), str(ROOT), str(data)], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stderr)
            raise SystemExit("node failed — nothing was checked")
        return json.loads(r.stdout)


def main() -> int:
    from app.core import garment_fit as gf
    axis = {"centre_x": 0.1, "centre_z": -0.05, "half_width": 0.2}
    pts = np.array([[0.25, 1.0, 0.05], [0.6, 0.5, -0.05], [-0.3, 2.0, -0.25], [0.1, 0.7, -0.05]])
    hand = np.array([[0.259, 1.0, 0.056], [0.612, 0.5, -0.05], [-0.312, 2.0, -0.262], [0.1, 0.7, -0.05]])

    print("[1] the rule, by hand (garment_fit.widen)")
    py = gf.widen(pts, 1.06, centre_x=0.1, centre_z=-0.05, half_width=0.2)
    check("python = hand at x1.06", np.allclose(py, hand, atol=1e-12), np.round(py, 6).tolist())
    check("python x1.0 unchanged", np.array_equal(gf.widen(pts, 1.0, centre_x=0.1, centre_z=-0.05, half_width=0.2), pts))

    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    cyl = np.array([[0.05 + 0.3 * np.cos(a), y, -0.02 + 0.3 * np.sin(a)] for y in np.linspace(0, 0.9, 10) for a in ang])
    axis2 = {"centre_x": 0.1, "centre_z": -0.05, "half_width": 0.204}
    jobs = [{"points": pts.tolist(), "scale": 1.06, "axis": axis},
            {"points": pts.tolist(), "scale": 1.0, "axis": axis},
            {"points": cyl.tolist(), "scale": 1.10, "axis": axis2}]
    out = run_js(jobs)

    print("[2] TypeScript = Python")
    for name, job, res in zip(("4 points x1.06", "4 points x1.0", "cylinder x1.10"), jobs, out):
        P = np.array(job["points"])
        want = gf.widen(P, job["scale"], centre_x=job["axis"]["centre_x"], centre_z=job["axis"]["centre_z"],
                        half_width=job["axis"]["half_width"])
        a = np.array(res["inPlace"]).reshape(-1, 3)
        b = np.array(res["point"]).reshape(-1, 3)
        check(f"widenInPlace {name}", float(np.abs(a - want).max()) <= 1e-12, f"max diff {float(np.abs(a - want).max()):.2e}")
        check(f"widenPoint {name}", float(np.abs(b - want).max()) <= 1e-12, f"max diff {float(np.abs(b - want).max()):.2e}")
    a = np.array(out[0]["inPlace"]).reshape(-1, 3)
    check("TypeScript = hand at x1.06", np.allclose(a, hand, atol=1e-12), np.round(a, 6).tolist())
    clipped = int((np.abs(cyl[:, 0] - 0.1) > 0.204).sum())
    check("the cylinder has points beyond the half width", clipped > 0, f"{clipped} of {len(cyl)}")
    check("y unchanged", np.array_equal(np.array(out[2]["inPlace"]).reshape(-1, 3)[:, 1], cyl[:, 1]))

    print("[3] the axis in the mesh frame (widen_axis' identity)")
    s, t = 0.2, np.array([0.3, 1.0, -0.1])
    body_axis = {"centre_x": 0.1 * s + t[0], "centre_z": -0.05 * s + t[2], "half_width": 0.204 * s}
    check("body axis by hand", np.allclose([body_axis["centre_x"], body_axis["centre_z"], body_axis["half_width"]],
                                           [0.32, -0.11, 0.0408], atol=1e-12), str(body_axis))
    placed = gf.widen(cyl * s + t, 1.08, **body_axis)
    mesh = gf.widen(cyl, 1.08, centre_x=0.1, centre_z=-0.05, half_width=0.204) * s + t
    check("widen(s·P + t) = s·widen_mesh(P) + t", float(np.abs(placed - mesh).max()) <= 1e-12,
          f"max diff {float(np.abs(placed - mesh).max()):.2e}")

    print("[4] the depth rule, by hand (garment_fit.depth_shift, Ruling A68)")
    frame = {"centre_x": 0.0, "centre_z": 0.02, "x_limit": 0.12, "y_limit": 1.3, "ramp": 0.03}
    q = np.array([[0.0, 1.0, 0.15], [0.05, 1.0, -0.10], [0.0, 1.0, 0.035], [0.105, 1.0, 0.15], [0.13, 1.0, 0.15],
                  [0.0, 1.29, 0.15], [0.0, 1.35, -0.10]])
    want = q.copy()
    want[:, 2] = [0.16, -0.11, 0.04, 0.155, 0.15, 0.15 + 0.01 / 3, -0.10]
    py = gf.depth_ease(q, 0.01, **frame)
    check("python = hand (q1..q7)", np.allclose(py, want, atol=1e-12), np.round(py[:, 2], 6).tolist())
    check("x and y unchanged", np.array_equal(py[:, :2], q[:, :2]))
    check("ease 0 unchanged", np.array_equal(gf.depth_ease(q, 0.0, **frame), q))
    frame2 = {"centre_x": 0.1, "centre_z": -0.05, "x_limit": 0.2, "y_limit": 0.6, "ramp": 0.03}
    jobs = [{"points": q.tolist(), "ease": 0.01, "axis": {**frame, "half_width": 0.2, "half_depth": 0.1}},
            {"points": cyl.tolist(), "ease": 0.012, "axis": {**frame2, "half_width": 0.2, "half_depth": 0.1}}]
    out = run_js(jobs)
    for name, job, res in zip(("q1..q7", "cylinder"), jobs, out):
        P = np.array(job["points"])
        fr = {k: job["axis"][k] for k in ("centre_x", "centre_z", "x_limit", "y_limit", "ramp")}
        want_js = gf.depth_ease(P, job["ease"], **fr)
        a = np.array(res["inPlace"]).reshape(-1, 3)
        check(f"easeInPlace {name}", float(np.abs(a - want_js).max()) <= 1e-12,
              f"max diff {float(np.abs(a - want_js).max()):.2e}")
        dz = np.array(res["shift"])
        check(f"depthShift {name}", float(np.abs(dz - gf.depth_shift(P, job["ease"], **fr)).max()) <= 1e-12)
        check(f"depthEase {name} (+10 % of half depth 0.1)", abs(res["depthEase"] - 0.01) <= 1e-12)
    ramps = gf.depth_shift(cyl, 0.012, **frame2) / 0.012
    check("the cylinder crosses every ramp", bool(((np.abs(ramps) > 0) & (np.abs(ramps) < 1)).any()
                                                  and (ramps == 0).any() and (np.abs(ramps) == 1).any()))

    print("[5] a cylinder body: front / back gaps by hand")
    fr5 = {"centre_x": 0.0, "centre_z": 0.0, "x_limit": 0.2, "y_limit": 2.0, "ramp": 0.03}
    pts5 = np.array([[0.0, 1.0, 0.112], [0.0, 1.0, -0.112], [0.112, 1.0, 0.0]])
    gap = lambda P: (np.hypot(P[:, 0], P[:, 2]) - 0.10) * 1000.0  # noqa: E731
    check("before: 12 mm all round", np.allclose(gap(pts5), [12.0, 12.0, 12.0], atol=1e-9),
          np.round(gap(pts5), 6).tolist())
    e5 = 10 / 100.0 * 0.10
    after = gap(gf.depth_ease(pts5, e5, **fr5))
    check("+10 %: front / back 22 mm, the side 12 mm", np.allclose(after, [22.0, 22.0, 12.0], atol=1e-9),
          np.round(after, 6).tolist())

    print("[6] an elliptic torso, its own depth centre")
    c0, b = 0.03, 0.10
    fr6 = {"centre_x": 0.0, "centre_z": c0, "x_limit": 0.2, "y_limit": 2.0, "ramp": 0.03}
    pts6 = np.array([[0.0, 1.0, c0 + b + 0.012], [0.0, 1.0, c0 - b - 0.012]])
    check("the points by hand", np.allclose(pts6[:, 2], [0.142, -0.082], atol=1e-12))
    egap = lambda P: np.where(P[:, 2] > c0, P[:, 2] - (c0 + b), (c0 - b) - P[:, 2]) * 1000.0  # noqa: E731
    check("before: 12 / 12 mm", np.allclose(egap(pts6), [12.0, 12.0], atol=1e-9))
    e6 = 6 / 100.0 * b
    moved = gf.depth_ease(pts6, e6, **fr6)
    check("+6 %: z' 0.148 / -0.088", np.allclose(moved[:, 2], [0.148, -0.088], atol=1e-12), moved[:, 2].tolist())
    check("+6 %: 18 / 18 mm", np.allclose(egap(moved), [18.0, 18.0], atol=1e-9), np.round(egap(moved), 6).tolist())
    scaled = gf.widen(pts6, 1.06, centre_x=0.0, centre_z=0.0, half_width=1.0)
    ratio = (scaled[0, 2] - pts6[0, 2]) / (pts6[1, 2] - scaled[1, 2])
    check("a scale about the bone axis would move the front 1.73x the back", abs(ratio - 0.142 / 0.082) < 1e-9
          and abs(ratio - 1.7317) < 1e-3, f"{ratio:.4f}")
    js6 = run_js([{"points": pts6.tolist(), "ease": e6, "axis": {**fr6, "half_width": 0.2, "half_depth": b}}])[0]
    check("TypeScript: the same z", np.allclose(np.array(js6["inPlace"]).reshape(-1, 3), moved, atol=1e-12))

    print("\nall checks passed" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
