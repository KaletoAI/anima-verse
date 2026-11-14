#!/usr/bin/env python3
"""Ruling A71: the cut of HAAR hair cards has ONE rule — ``app/core/hair_cut.py`` (``cut_cards``, the fit) — and one
port for the Hairstyles tab's live Cut preview (``frontend/src/tabs/characters/hairCut.ts``: ``cutCards``). This
smoke holds the two together on synthetic cards with the cuts derived by hand, and proves the tip defect on the
code before the ruling.

Usage:
    ./.venv/bin/python scripts/smoke_hair_cut_parity.py

No server, no world, no storage: pure functions only. The TypeScript module is bundled by esbuild (root
``node_modules``, else ``frontend/``) and run by ``node`` on the same rails. [6] reads the pre-A71
``app/core/hair_cards.py`` with ``git show`` at the pinned commit (skipped with a note outside a git checkout).

THE CARDS (R = 5 rows: 3 body segments + the soft tip; rails ±5 mm in x, z 0; "straight" = root (0, 1.6, 0), rows
every L/4 straight down)
-------------------------------------------------------------------------------------------------------------------
k0, k2..k8 straight, L 0.40 (rows y 1.6, 1.5, 1.4, 1.3, 1.2); k1 bent: (0, 1.6), (0, 1.5), (0, 1.4), (0.1, 1.4),
(0.2, 1.4) — L 0.40; k9 straight from y 1.30, L 0.40; k10 straight, L 1.00 (the outlier).
Lengths: ten 0.40 and one 1.00 -> p90: h = 0.9 · 10 = 9 -> the 10th sorted value = 0.40; clamp = 1.5 · 0.40 = 0.60.
The rule: keep = min(L, clamp, max_cm, a(at)) ≥ min(L, 0.03); E = min(ends (Auto 0.03), keep / 4); rows 0..3 at
arc (keep − E)·r/3, row 4 at keep; v = 1 − 0.75·r/3 = (1, 0.75, 0.5, 0.25), row 4: 1 − 0.95 = 0.05.

[1] Auto (no cut) — the outlier clamp: k0 keep 0.40, E 0.03, arcs (0, 0.123333, 0.246667, 0.37, 0.40) -> y (1.6,
    1.476667, 1.353333, 1.23, 1.2); v (1, 0.75, 0.5, 0.25, 0.05). k10 keep 0.60 (clamped), arcs (0, 0.19, 0.38,
    0.57, 0.60) -> y (1.6, 1.41, 1.22, 1.03, 1.0). clamped 1, shortened 1.
[2] Length cut max_cm 30: k0 arcs (0, 0.09, 0.18, 0.27, 0.30) -> y (1.6, 1.51, 1.42, 1.33, 1.30). k1 bent: arc
    0.27 lies on its third segment (arc 0.2 .. 0.3, horizontal) at f 0.7 -> centre (0.07, 1.4), arc 0.30 = its
    row 3 (0.1, 1.4). k10 keep 0.30: the user's length binds, not the clamp (clamped 0); all 11 shortened.
[3] Height cut at "shoulder" = 1.35: k0 first drops below 1.35 at row 3 (1.3), between row 2 (1.4, arc 0.2) and it
    at t = (1.4 − 1.35) / 0.1 = 0.5 -> keep 0.25, arcs (0, 0.073333, 0.146667, 0.22, 0.25). k1 never drops below
    1.35 (lowest 1.4): uncut, keep 0.40. k9's root (1.30) lies below: keep = min(0.40, 0.03) = 0.03, E =
    min(0.03, 0.0075) = 0.0075, arcs (0, 0.0075, 0.015, 0.0225, 0.03). k10 (rows 1.6, 1.35, 1.1, …): row 1 = 1.35
    is not below, row 2 is: t = 0 -> keep 0.25 (not clamped). shortened 10 (all but k1), clamped 0.
[4] Tail removal / the soft tip: ends_cm 8 -> k0 E = min(0.08, 0.10) = 0.08, arcs (0, 0.106667, 0.213333, 0.32,
    0.40); ends_cm 0.5 -> E 0.005, row 3 at 0.395. The v of every row is the same in every case: nothing past
    S_END = 0.95 of the strip (where no strand line passes the cutoff) and never v = 0 reaches a card.
[5] TypeScript = Python on [1]–[4] and on 40 random wavy cards of 17 rows (lengths 0.05–0.8 m, a few long
    outliers) under 6 cuts: every position and v within 1e-9 (both float64 on the same float32 rails).
[6] Fails on the old code (commit b2f9f2f068df54e20a27109514c2878bb51779d9, before A71): its ``haar_cards`` maps the
    tip row to v = 1 − 16/16 = 0 — under the glTF default REPEAT wrap the tip texel is half the strip's ROOT row
    (the dashes under every card's end, A71 diagnosis) — and the whole strip over the card, so the strip's thin
    tail (s 0.75 … 1.0) spans the last 25 % of the card. The cut maps the tip row to v 0.05 and the tail into the
    last 3 cm.
"""
import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLD_COMMIT = "b2f9f2f068df54e20a27109514c2878bb51779d9"

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
for (const cand of ['esbuild', join(root, 'node_modules/esbuild'), join(root, 'frontend/node_modules/esbuild')]) {
  try { esbuild = require_(cand); break } catch { /* next */ }
}
if (!esbuild) { console.error('esbuild not found'); process.exit(2) }
const dir = mkdtempSync(join(tmpdir(), 'smoke-hair-cut-'));
const file = join(dir, 'm.mjs');
await esbuild.build({ entryPoints: [join(root, 'frontend/src/tabs/characters/hairCut.ts')], outfile: file,
  bundle: true, format: 'esm', platform: 'neutral', logLevel: 'silent', absWorkingDir: root });
const m = await import('file://' + file);
rmSync(dir, { recursive: true, force: true });
const jobs = JSON.parse(readFileSync(input, 'utf8'));
const out = jobs.map((j) => {
  const rails = m.decodeRails(j.rails);
  const r = m.cutCards(rails, j.cards, j.rows, j.cut, j.heights);
  return { positions: Array.from(r.positions), v: Array.from(r.v), keep: Array.from(r.keep), clamped: r.clamped,
           shortened: r.shortened };
});
console.log(JSON.stringify(out));
"""


def run_js(jobs):
    with tempfile.TemporaryDirectory(prefix="smoke-hair-cut-") as d:
        script = Path(d) / "run.mjs"
        script.write_text(JS)
        data = Path(d) / "in.json"
        data.write_text(json.dumps(jobs))
        r = subprocess.run(["node", str(script), str(ROOT), str(data)], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stderr)
            raise SystemExit("node failed — nothing was checked")
        return json.loads(r.stdout)


def card(centres):
    c = np.asarray(centres, np.float64)
    return np.stack([c - [0.005, 0, 0], c + [0.005, 0, 0]], 1)


def straight(y0, length, rows=5):
    return card([[0.0, y0 - length * r / (rows - 1), 0.0] for r in range(rows)])


def synthetic():
    cards = [straight(1.6, 0.4)]
    cards.append(card([[0, 1.6, 0], [0, 1.5, 0], [0, 1.4, 0], [0.1, 1.4, 0], [0.2, 1.4, 0]]))
    cards += [straight(1.6, 0.4) for _ in range(7)]
    cards.append(straight(1.30, 0.4))
    cards.append(straight(1.6, 1.0))
    return np.stack(cards).astype(np.float32)


def main() -> int:
    from app.core import hair_cut as hc
    rails = synthetic()
    heights = {"shoulder": 1.35}
    V64 = rails.astype(np.float64)
    near = lambda a, b, tol=1e-9: bool(np.allclose(np.asarray(a, np.float64), np.asarray(b, np.float64), atol=tol))
    v_hand = [1.0, 0.75, 0.5, 0.25, 0.05]

    print("[1] Auto — the outlier clamp")
    V, v, info = hc.cut_cards(V64, {}, heights)
    check("p90 0.40, clamp 0.60", abs(info["clamp_m"] - 0.60) < 1e-6, round(info["clamp_m"], 6))
    check("k0 rows y", near(V[0].mean(1)[:, 1], [1.6, 1.6 - 0.37 / 3, 1.6 - 0.74 / 3, 1.23, 1.2], 1e-6),
          np.round(V[0].mean(1)[:, 1], 6).tolist())
    check("k0 v", near(v[0], v_hand, 1e-12), v[0].tolist())
    check("every card the same v", near(v, np.tile(v_hand, (len(v), 1)), 1e-12))
    check("k10 clamped to 0.60", near(V[10].mean(1)[:, 1], [1.6, 1.41, 1.22, 1.03, 1.0], 1e-6),
          np.round(V[10].mean(1)[:, 1], 6).tolist())
    check("clamped 1, shortened 1", info["clamped"] == 1 and info["shortened"] == 1, (info["clamped"], info["shortened"]))
    check("rails keep their width (10 mm)", near(np.linalg.norm(V[:, :, 1] - V[:, :, 0], axis=2), 0.01, 1e-6))

    print("[2] length cut max_cm 30")
    V, v, info = hc.cut_cards(V64, {"max_cm": 30}, heights)
    check("k0 rows y", near(V[0].mean(1)[:, 1], [1.6, 1.51, 1.42, 1.33, 1.30], 1e-6))
    c1 = V[1].mean(1)
    check("k1 bent: arc 0.27 -> (0.07, 1.4), 0.30 -> (0.1, 1.4)",
          near(c1[3, :2], [0.07, 1.4], 1e-6) and near(c1[4, :2], [0.1, 1.4], 1e-6), np.round(c1[3:, :2], 6).tolist())
    check("k10 keep 0.30, user binds (clamped 0), shortened 11",
          abs(info["keep_m"][10] - 0.30) < 1e-6 and info["clamped"] == 0 and info["shortened"] == 11,
          (round(info["keep_m"][10], 6), info["clamped"], info["shortened"]))

    print("[3] height cut at shoulder (1.35)")
    V, v, info = hc.cut_cards(V64, {"at": "shoulder"}, heights)
    check("k0 keep 0.25", near(V[0].mean(1)[:, 1], [1.6, 1.6 - 0.22 / 3, 1.6 - 0.44 / 3, 1.38, 1.35], 1e-6),
          np.round(V[0].mean(1)[:, 1], 6).tolist())
    check("k1 never below: uncut", abs(info["keep_m"][1] - 0.40) < 1e-6)
    check("k9 root below: keep 0.03, E 0.0075",
          near(V[9].mean(1)[:, 1], [1.30, 1.2925, 1.285, 1.2775, 1.27], 1e-6), np.round(V[9].mean(1)[:, 1], 6).tolist())
    check("k10 keep 0.25 at row 1 exactly", abs(info["keep_m"][10] - 0.25) < 1e-6, round(info["keep_m"][10], 6))
    check("shortened 10, clamped 0", info["shortened"] == 10 and info["clamped"] == 0, (info["shortened"], info["clamped"]))
    check("a landmark the body lacks cuts nothing", near(hc.cut_cards(V64, {"at": "waist"}, heights)[0],
                                                          hc.cut_cards(V64, {}, heights)[0], 0))

    print("[4] the soft tip (tail removal)")
    V, v, _ = hc.cut_cards(V64, {"ends_cm": 8}, heights)
    check("ends 8 cm: k0 arcs (0, .106667, .213333, .32, .40)",
          near(V[0].mean(1)[:, 1], [1.6, 1.6 - 0.32 / 3, 1.6 - 0.64 / 3, 1.28, 1.2], 1e-6))
    V, v, _ = hc.cut_cards(V64, {"ends_cm": 0.5}, heights)
    check("ends 0.5 cm: row 3 at 0.395", abs(V[0].mean(1)[3, 1] - (1.6 - 0.395)) < 1e-6)
    check("v never 0, never past S_END", float(v.min()) == 1 - hc.S_END and float(v.min()) > 0)
    try:
        hc.normalise({"max_cm": 30, "at": "chin"})
        check("max_cm and at together refused", False)
    except ValueError:
        check("max_cm and at together refused", True)
    for bad in ({"max_cm": 1}, {"ends_cm": 50}, {"at": "knee"}, {"len": 3}):
        try:
            hc.normalise(bad)
            check(f"refused {bad}", False)
        except ValueError:
            check(f"refused {bad}", True)
    check("normalise rounds and orders", hc.normalise({"ends_cm": "2.04", "max_cm": 41.26}) ==
          {"max_cm": 41.3, "ends_cm": 2.0})

    print("[5] TypeScript = Python")
    rng = np.random.default_rng(71)
    K, R = 40, 17
    wavy = []
    for k in range(K):
        L = rng.uniform(0.05, 0.8) * (2.5 if k % 13 == 0 else 1.0)
        s = np.linspace(0, 1, R)
        root = np.array([rng.uniform(-0.08, 0.08), rng.uniform(1.5, 1.7), rng.uniform(-0.1, 0.05)])
        c = root + np.stack([0.02 * np.sin(6 * s + k), -L * s, -0.03 * s + 0.01 * np.cos(5 * s)], 1)
        w = rng.uniform(0.006, 0.03) * np.linspace(1, 0.7, R)
        wavy.append(np.stack([c - np.outer(w / 2, [1, 0, 0]), c + np.outer(w / 2, [1, 0, 0])], 1))
    wavy = np.stack(wavy).astype(np.float32)
    h2 = {"chin": 1.47, "shoulder": 1.44, "shoulder_blades": 1.27, "mid_back": 1.14, "waist": 1.04}
    cuts = [{}, {"max_cm": 30}, {"at": "shoulder"}, {"ends_cm": 8}, {"at": "mid_back", "ends_cm": 0.5},
            {"max_cm": 3, "ends_cm": 12}]
    jobs = [{"rails": base64.b64encode(rails.tobytes()).decode(), "cards": len(rails), "rows": 5, "cut": c,
             "heights": heights} for c in ({}, {"max_cm": 30}, {"at": "shoulder"}, {"ends_cm": 8})]
    jobs += [{"rails": base64.b64encode(wavy.tobytes()).decode(), "cards": K, "rows": R, "cut": c, "heights": h2}
             for c in cuts]
    out = run_js(jobs)
    worst = 0.0
    for job, res in zip(jobs, out):
        src = (rails if job["rows"] == 5 else wavy).astype(np.float64)
        V, v, info = hc.cut_cards(src, job["cut"], job["heights"])
        d = max(float(np.abs(V.ravel() - np.asarray(res["positions"])).max()),
                float(np.abs(v.ravel() - np.asarray(res["v"])).max()),
                float(np.abs(info["keep_m"] - np.asarray(res["keep"])).max()))
        worst = max(worst, d)
        check(f"{job['rows']} rows, cut {job['cut']}: positions / v / keep",
              d <= 1e-9 and res["clamped"] == info["clamped"] and res["shortened"] == info["shortened"],
              f"max |diff| {d:.2e}, clamped {res['clamped']}/{info['clamped']}, shortened {res['shortened']}/{info['shortened']}")
    print(f"     worst difference {worst:.2e}")

    print(f"[6] fails on the old code ({OLD_COMMIT[:9]})")
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/hair_cards.py"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  SKIP the pinned commit is not in this checkout")
    else:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old_hair_cards.py"
            path.write_text(r.stdout)
            spec = importlib.util.spec_from_file_location("old_hair_cards", path)
            old = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(old)

        class FarSdf:   # every point 1 m outside the body, the gradient +z: the cards keep their strands' shape
            def sample(self, X):
                return np.ones(len(np.asarray(X).reshape(-1, 3)))

            def grad(self, X):
                return np.tile([0.0, 0.0, 1.0], (len(np.asarray(X).reshape(-1, 3)), 1))
        strands = np.stack([np.stack([[0.01 * i, 1.6 - 0.4 * t, 0.0] for t in np.linspace(0, 1, 30)])
                            for i in range(9)])
        Vo, _F, UVo, cardo = old.haar_cards(strands, FarSdf(), n_cards=3, n_seg=16)
        tip_old = UVo.reshape(-1, 17, 2, 2)[:, -1, :, 1]
        check("old: the tip row samples v = 0 (the wrapped root row)", bool((tip_old == 0).all()),
              f"tip v {np.unique(tip_old).tolist()}")
        Vn, _F, UVn, cardn = __import__("app.core.hair_cards", fromlist=["x"]).haar_cards(
            strands, FarSdf(), n_cards=3, n_seg=16)
        _Vc, vrow, _ = hc.cut_cards(Vn.reshape(-1, 17, 2, 3).astype(np.float32).astype(np.float64), {}, {})
        check("new: the tip row samples v = 0.05, the dense strip runs to 3 cm before the tip",
              bool(np.allclose(vrow[:, -1], 0.05)) and bool(np.allclose(vrow[:, -2], 0.25)),
              f"rows 15/16 v {np.round(vrow[0, -2:], 4).tolist()}")
        tail_old = float((UVo.reshape(-1, 17, 2, 2)[0, :, 0, 1] < 1 - hc.S_BODY).sum())
        check("old: the strip's thin tail spans 4 of 17 rows (the last 25 % of the card)", tail_old == 4, tail_old)

    print()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
