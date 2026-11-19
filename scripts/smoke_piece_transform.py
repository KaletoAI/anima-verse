#!/usr/bin/env python3
"""A217: the placement correction of a clothing piece — ``garment_fit.piece_transform`` (the fit), its settings
(``garment_fit_settings``) and the ONE client port (``frontend/src/tabs/characters/fitWiden.ts``
``transformInPlace``, the mesh view's live preview).

Usage:
    ./.venv/bin/python scripts/smoke_piece_transform.py

No server, no world, no storage: pure functions only. The TypeScript module is bundled by esbuild (root
``node_modules``, else ``frontend/``) and run by ``node`` on the same points.

THE CASES, DERIVED BY HAND (body frame: x to the right of the front view, y up, z forward; right-hand rule;
Rz · Ry · Rx, the x turn first; the pivot is the centre of the piece's bounding box)
--------------------------------------------------------------------------------------------------------------
Six points on the unit axes, ±x, ±y, ±z -> bounding box centre (0, 0, 0), k = 2 metres per unit.
[1] rot_x +30: (0, 1, 0) -> (0, cos 30, sin 30) = (0, 0.866025, 0.5) — the top leans FORWARD;
                (0, 0, 1) -> (0, −0.5, 0.866025); (1, 0, 0) stays.
    rot_y +30: (0, 0, 1) -> (sin 30, 0, cos 30) = (0.5, 0, 0.866025) — the front turns to +x; (1, 0, 0) ->
                (0.866025, 0, −0.5).
    rot_z +30: (1, 0, 0) -> (0.866025, 0.5, 0) — the +x side goes up; (0, 1, 0) -> (−0.5, 0.866025, 0).
    off_x +2, off_y −3.5, off_z +10 cm at k 2: every point moves by (0.01, −0.0175, 0.05) units.
[2] The order (``rotation_xyz`` directly, beyond the setting's ±30): x 90 then z 90 — (1, 0, 0) -> Rx (1, 0, 0) ->
    Rz (0, 1, 0); (0, 0, 1) -> Rx (0, −1, 0) -> Rz (1, 0, 0); (0, 1, 0) -> Rx (0, 0, 1) -> Rz (0, 0, 1).
[3] Settings: ``validate`` takes −30, 30, 0.5, −10, 10 and refuses 30.5, 10.5 cm, 0.3 (no multiple of 0.5), True,
    "5", NaN and 10**400 (review: no OverflowError -> 500) with a ValueError; ``transform_values`` makes a missing / out-of-range / non-numeric value 0 and
    ``normalise({})`` carries the six keys at 0, so a fit recorded before A217 is NOT made due by them.
    All zeros: ``piece_transform`` returns the very array and no report (the fit as before, vertex for vertex).
[4] The mesh frame (the view): with a placement Q = s·P + t (s 0.25, t (0.3, 1.0, −0.1)), k 1.7, the fit's
    correction of the placed points equals s·(the client's ``transformInPlace`` of P about the mesh-frame pivot =
    the bounding-box centre of P, shift cm / 100 / (k·s)) + t, within 1e-9, on a 24 × 10 tilted cylinder at
    rot (−7, 3.5, 1), off (2, −1.5, 0.5).
"""
import json
import math
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
const dir = mkdtempSync(join(tmpdir(), 'smoke-piece-transform-'));
const file = join(dir, 'm.mjs');
await esbuild.build({ entryPoints: [join(root, 'frontend/src/tabs/characters/fitWiden.ts')], outfile: file,
  bundle: true, format: 'esm', platform: 'neutral', logLevel: 'silent', absWorkingDir: root });
const m = await import('file://' + file);
rmSync(dir, { recursive: true, force: true });
const jobs = JSON.parse(readFileSync(input, 'utf8'));
const out = jobs.map((j) => {
  const flat = Float64Array.from(j.points.flat());
  m.transformInPlace(flat, j.tr, j.pivot, j.scale, j.k);
  return { inPlace: Array.from(flat), R: m.rotationXyz(j.tr.rot_x, j.tr.rot_y, j.tr.rot_z) };
});
console.log(JSON.stringify(out));
"""


def run_js(jobs):
    with tempfile.TemporaryDirectory(prefix="smoke-piece-transform-") as d:
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
    from app.core import garment_fit_settings as gfs
    c, s30 = math.cos(math.radians(30)), 0.5
    pts = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float64)

    print("[1] the turns and the shift, by hand (garment_fit.piece_transform)")
    q, rep = gf.piece_transform(pts, {"rot_x": 30}, k=2.0)
    check("rot_x +30: top forward", np.allclose(q[2], [0, c, s30]) and np.allclose(q[4], [0, -s30, c])
          and np.allclose(q[0], [1, 0, 0]), np.round(q[[0, 2, 4]], 6).tolist())
    check("report names the pivot (0, 0, 0)", rep is not None and rep["pivot_m"] == [0.0, 0.0, 0.0], str(rep))
    q, _ = gf.piece_transform(pts, {"rot_y": 30}, k=2.0)
    check("rot_y +30: front to +x", np.allclose(q[4], [s30, 0, c]) and np.allclose(q[0], [c, 0, -s30]),
          np.round(q[[0, 4]], 6).tolist())
    q, _ = gf.piece_transform(pts, {"rot_z": 30}, k=2.0)
    check("rot_z +30: +x side up", np.allclose(q[0], [c, s30, 0]) and np.allclose(q[2], [-s30, c, 0]),
          np.round(q[[0, 2]], 6).tolist())
    q, _ = gf.piece_transform(pts, {"off_x": 2, "off_y": -3.5, "off_z": 10}, k=2.0)
    check("shift cm / 100 / k", np.allclose(q - pts, [0.01, -0.0175, 0.05], atol=1e-12),
          np.round((q - pts)[0], 6).tolist())

    print("[2] the order: x first, then y, then z")
    R = gf.rotation_xyz(90, 0, 90)
    check("x 90 then z 90", np.allclose(R @ [1, 0, 0], [0, 1, 0]) and np.allclose(R @ [0, 0, 1], [1, 0, 0])
          and np.allclose(R @ [0, 1, 0], [0, 0, 1]), np.round(R, 6).tolist())

    print("[3] settings")
    for value in (-30, 30, 0.5, 2.5):
        check(f"rot_x {value} accepted", gfs.validate({"rot_x": value}) == {"rot_x": float(value)})
    for value in (-10, 10):
        check(f"off_z {value} accepted", gfs.validate({"off_z": value}) == {"off_z": float(value)})
    for key, value in (("rot_y", 30.5), ("off_x", 10.5), ("rot_z", 0.3), ("off_y", True), ("rot_x", "5"),
                       ("off_z", float("nan")), ("rot_x", 10 ** 400)):
        try:
            gfs.validate({key: value})
            check(f"{key} {value!r} refused", False, "accepted")
        except ValueError as e:
            check(f"{key} {value!r} refused", True, str(e))
    check("transform_values: a huge int -> 0, no OverflowError", gf.transform_values({"off_x": 10 ** 400})["off_x"] == 0.0)
    v = gf.transform_values({"rot_x": 31, "off_y": "x", "rot_z": -2.5})
    check("transform_values: out of range / non-numeric -> 0", v == {"rot_x": 0.0, "rot_y": 0.0, "rot_z": -2.5,
                                                                    "off_x": 0.0, "off_y": 0.0, "off_z": 0.0}, str(v))
    n = gfs.normalise({})
    check("normalise({}) carries the six keys at 0", all(n[k] == 0.0 for k in gf.TRANSFORM_KEYS))
    check("a record before A217 = the defaults (no fit due)", gfs.recorded({"inputs": {"fit_settings": {
        "sleeves_left": "auto"}}}) == gfs.normalise({}))
    check("TRANSFORM_KEYS agree", tuple(gfs.TRANSFORM_KEYS) == tuple(gf.TRANSFORM_KEYS))
    check("not for a shell", set(gf.TRANSFORM_KEYS) <= set(gfs.NOT_FOR_SHELL))
    same, rep0 = gf.piece_transform(pts, gfs.normalise({}), k=2.0)
    check("all zeros: the same array, no report", same is pts and rep0 is None)

    print("[4] the client port in the mesh frame (fitWiden.ts transformInPlace)")
    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    P = np.array([[0.05 + 0.3 * np.cos(a) + 0.1 * y, y, -0.02 + 0.3 * np.sin(a) + 0.05 * y]
                  for y in np.linspace(0, 0.9, 10) for a in ang])
    s, t, k = 0.25, np.array([0.3, 1.0, -0.1]), 1.7
    tr = {"rot_x": -7.0, "rot_y": 3.5, "rot_z": 1.0, "off_x": 2.0, "off_y": -1.5, "off_z": 0.5}
    body, _ = gf.piece_transform(P * s + t, tr, k=k)
    pivot = [float(x) for x in gf.transform_pivot(P)]
    out = run_js([{"points": P.tolist(), "tr": tr, "pivot": pivot, "scale": s, "k": k},
                  {"points": pts.tolist(), "tr": {"rot_x": 30, "rot_y": 0, "rot_z": 0, "off_x": 0, "off_y": 0,
                                                  "off_z": 0}, "pivot": [0, 0, 0], "scale": 1, "k": 2}])
    js = np.array(out[0]["inPlace"]).reshape(-1, 3)
    diff = float(np.abs(js * s + t - body).max())
    check("s · TS(P) + t = python(s · P + t)", diff < 1e-9, f"max |diff| {diff:.2e}")
    check("TS rotation = python rotation_xyz", np.allclose(np.array(out[0]["R"]).reshape(3, 3),
                                                            gf.rotation_xyz(-7.0, 3.5, 1.0), atol=1e-12))
    js1 = np.array(out[1]["inPlace"]).reshape(-1, 3)
    check("TS rot_x +30 by hand", np.allclose(js1[2], [0, c, s30]) and np.allclose(js1[4], [0, -s30, c]))

    print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
