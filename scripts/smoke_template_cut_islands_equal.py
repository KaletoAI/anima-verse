"""Smoke (real Blender, CPU, 0 hub jobs): the cut-only run writes the same ``islands.json`` as the full drape.

Usage:
    ./.venv/bin/python scripts/smoke_template_cut_islands_equal.py --body <plain base body .glb> \\
        --record <a top's drape record .json, or a JSON file of template params> \\
        [--front <view .png> --back <view .png>] [--expect-sha <sha256 of the drape's islands.json>] \\
        [--own <an own-mesh piece's fit .glb> [--mode full|shrunk|dropped]]

Work on COPIES of a character's files (e.g. the base body ``model3d/base*.glb``, a drape record
``garments/templates/<item>_<tsig>.json`` and the two piece-only views), never on a live world folder: everything
this writes goes into a temp folder. Without ``--front`` / ``--back`` the drape bakes from a plain grey picture (the
bake is after the cut and changes no island).

What it proves, derived from the code (``app/blender/scripts/garment_template_build.run``): the cut-only run
(``garment_template_cut.run_blender``, build arg ``cut_only``) and the full drape (``garment_template.run_drape``)
take the SAME build args up to ``pattern_uv_of`` — ``build_args`` of the same params and spec — and the pattern UVs
are computed there, before the cloth run, which only moves vertices. Both runs therefore write ``islands.json`` from
identical input on identical code, and the payload holds no timing data (``uv_pattern.islands_payload``), so:

[1] both runs succeed, the cut-only one writes ``islands.json`` and nothing else;
[2] the two files are byte-identical (same sha256) — the derived tolerance is ZERO: any difference would mean the
    code paths differ, not float noise (the same Blender on the same input is deterministic: the live world's three
    drapes of one shirt, made at three different times, carry one islands sha256);
[3] parsed, the same island names / parts / triangle lists and every ``verts_px`` equal (max |Δ| = 0.0 px);
[4] with ``--expect-sha``: that sha too (the drape made earlier in the world);
[5] the cut is much quicker than the drape: its wall time (slot wait excluded) under half the drape's.
Wall times of both are printed.

Measured 2026-11-21 on a copy of Dario's base body and shirt (Blender 5.2.2, this host): cut 11.8 s, drape 63.6 s
(41.0 s Blender), both sha256 387cd15f… = the live drapes' islands.

``--own`` (stage "layers", 2026-11-22): an own-mesh piece under the template piece (its accepted plain-body fit, e.g.
Kai's generated jeans under his leather jacket) and the A200 fallback ``--mode`` the drape landed in. Both runs get it
the way that mode hands it: the drape as ``garment_template.drape_with_fallback``'s attempt (full: offset 0, shrunk:
``INNER_SHRINK_M``, dropped: not at all), the cut as ``garment_template_cut.run`` does for ``own_mode`` (the same), so
[2] / [3] hold in every mode. [1] allows ``marks.json`` beside the islands (a jacket / dress writes its placket lines).
[5] is not checked with ``--own``. Measured 2026-11-22 on a copy of Kai's base body, jacket and jeans fit: "dropped"
both sha 360866fd… (13.98 px/cm) — the drape's islands of the live run.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True)
    ap.add_argument("--record", required=True)
    ap.add_argument("--front")
    ap.add_argument("--back")
    ap.add_argument("--item", default="item_cut_check")
    ap.add_argument("--expect-sha", default="")
    ap.add_argument("--own", default="", help="an own-mesh piece's fit .glb under the piece (a collider)")
    ap.add_argument("--mode", default="full", choices=("full", "shrunk", "dropped"))
    a = ap.parse_args()
    from PIL import Image

    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    raw = json.loads(Path(a.record).read_text(encoding="utf-8"))
    params = gt.validate_params(raw.get("params") if isinstance(raw.get("params"), dict) else raw)[0]
    check("[0] a pattern kind", params["kind"] in gt.PATTERN_KINDS, params["kind"])
    out = Path(tempfile.mkdtemp(prefix="cut_islands_equal_"))
    front, back = a.front, a.back
    if not front or not back:
        grey = out / "grey.png"
        Image.new("RGBA", (512, 512), (128, 128, 128, 255)).save(grey)
        front, back = front or str(grey), back or str(grey)
    t0 = time.time()
    own = [(Path(a.own), None)] if a.own and a.mode != "dropped" else []
    off = gt.INNER_SHRINK_M if a.mode == "shrunk" else 0.0
    cut = gtc.run_blender(Path(a.body), params, item_id=a.item, out_dir=out / "cut", own=own, own_offset=off)
    cut_wall = time.time() - t0
    check("[1] the cut-only run succeeds", cut["ok"], cut["error"] or cut["outcome"])
    if not cut["ok"]:
        print(cut["log_tail"][-3000:])
        return 1
    produced = sorted(p.name for p in (out / "cut").iterdir())
    check("[1] it writes islands.json (and the placket lines) only", produced in (["islands.json"],
                                                                         ["islands.json", "marks.json"]), produced)
    t1 = time.time()
    drape = gt.run_drape(Path(a.body), params, {"front": front, "back": back, "source": "piece_only"},
                         item_id=a.item, out_dir=out / "drape", lower=own or None,
                         lower_offsets=[off] if own else None)
    if a.own:
        print(f"drape mode {a.mode}: ok {drape.get('ok')} error {drape.get('error')!r}")
    drape_wall = time.time() - t1
    isl = (drape.get("outputs") or {}).get("islands")
    check("[1] the full drape succeeds and writes islands", bool(drape.get("glb")) and bool(isl),
          drape.get("error"))
    if not isl:
        return 1
    cb, db = cut["islands"].read_bytes(), Path(isl).read_bytes()
    cs, ds = hashlib.sha256(cb).hexdigest(), hashlib.sha256(db).hexdigest()
    check("[2] byte-identical islands.json", cb == db, f"cut {cs[:12]} drape {ds[:12]}")
    cp, dp = json.loads(cb), json.loads(db)
    names = [(i["name"], i["part"], i["tris"]) for i in cp["islands"]]
    check("[3] same islands, parts and triangles", names == [(i["name"], i["part"], i["tris"]) for i in dp["islands"]],
          [n for n, _p, _t in names])
    dmax = max((abs(x - y) for ci, di in zip(cp["islands"], dp["islands"])
                for cv, dv in zip(ci["verts_px"], di["verts_px"]) for x, y in zip(cv, dv)), default=0.0)
    check("[3] every verts_px equal (max |d| 0.0 px)", dmax == 0.0, dmax)
    if a.expect_sha:
        check("[4] the drape's earlier islands sha", cs == a.expect_sha, cs)
    drape_work = gt.work_wall_s(drape.get("data") or {})
    if not a.own:
        check("[5] the cut takes under half the drape's time", cut["wall_s"] < 0.5 * float(drape_work or drape_wall),
              f"cut {cut['wall_s']} s (Blender {(cut['data'] or {}).get('script_wall_s')} s) vs drape "
              f"{drape_work} s (Blender {(drape.get('data') or {}).get('script_wall_s')} s); calls {cut_wall:.1f} / "
              f"{drape_wall:.1f} s")
    print(f"islands sha256 {cs}")
    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
