#!/usr/bin/env python3
"""Ruling A48c: the fit allowance's widening has ONE rule — ``garment_fit.widen`` (Python, the fit) — and one port
for the mesh view's live preview (``frontend/src/tabs/characters/fitWiden.ts``: ``widenPoint`` / ``widenInPlace``).
This smoke holds the two together on a synthetic mesh, with the numbers derived by hand, and checks the frame
mapping ``garment_mesh_view.widen_axis`` relies on.

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

    print("\nall checks passed" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
