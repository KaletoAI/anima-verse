"""Smoke (real Blender, CPU, 0 hub jobs): a top's collar, neckband and placket line (plan group B, phases E + F).

Usage:
    ./.venv/bin/python scripts/smoke_template_cut_tops.py --body <plain base body .glb> [--only NAME ...] \
        [--base-repo <checkout of the commit before phases E + F>] [--instance <instance dir, default <repo>/instance>]

Work on a COPY of a character's base body (``model3d/base*.glb``), never on a live world folder: everything this writes
goes into a temp folder. Each case is a cut-only run (``build_args`` + ``cut_only``) of ``validate_params`` of its
params, no lower layers.

What the rules of ``garment_template_build.build_bodice`` give a ``top`` since phases E + F (B8 / B9 / B10 now for
every kind with a bodice), derived from them:

[1] covered, elbow sleeves, crew, ``collar`` stand (B9): a collar is the binding, so no ``band``; the collar is a strip
    cut at the back centre and relaxed like the waistband: islands exactly {front, back, sleeve_l, sleeve_r, collar},
    the collar's area 0.97-1.03 and stretch p95 <= 1.10 (B24); ``marks.json`` holds exactly one line,
    ``centre_front`` on ``front`` (a closed front's centre meridian), at least 5 points, top first (the last point
    lower than the first by at least 10 cm: the line runs from the neck to the hem of a 0.29 m top).
[2] covered, V 5 cm deep, no collar (B8: a V never keeps the band): islands {front, back, sleeve_l, sleeve_r};
    ``centre_front`` on ``front``.
[3] covered, crew cut 15 cm deep (B8, phase F: a crew / boat neck keeps its band only while the cut is at most
    ``BAND_SCOOP_MAX_M`` = 8 cm deep, like a scoop — a 15 cm crew band measured area 1.31, p95 2.99): no ``band``.
[4] covered, crew at its usual depth (``NECK_DEPTH`` crew 1 cm <= 8 cm), no collar: ONE ``band`` island, relaxed from its
    strip (before phase F the bare one-row strip read p95 2.65 / 3.69 in two pieces on Tilda's body): area 0.97-1.03,
    p95 <= 1.10.
Every case [1]-[4]: panels area 0.97-1.03, stretch p95 <= 1.30 (B24, bodice panels), px/cm >= 11.0.

[5] with ``--base-repo``: an off-shoulder top and a top with straps have no neck ring, so phases E + F change nothing for
    them — the ``islands.json`` bytes of this checkout equal the base checkout's (the same body, the same args; the base
    is run with its own ``garment_template`` and builder in a subprocess).

[6] with ``--corset-body``: phase G — a strapless corset top (sweetheart 10 cm, fit 0, 0.42 m) cut by ``wrap`` with
    the darts of ``corset_darts`` (centre cut + two bust darts, UV only): islands exactly {front, back}, both panels area
    0.97-1.03 and stretch p95 <= 1.25 (the plan's acceptance for this piece; without the darts Rosi's front read 1.28 /
    0.969), ``marks.json`` holds exactly ``centre_back`` on ``back``, at least 10 points, top first (the last at least
    20 cm under the first: the 0.42 m panel's centre column).

Measured 2026-11-22 (copies of the world's base bodies): Dario's body passes [1]-[5] (the stand collar p95 1.09 since
the collar's rings are laid out of the neck as a smooth ring; built inside it and pushed out vertex by vertex it read
1.24). Tilda's body fails [1]-[4]: hair is part of her body mesh at the nape, the neck rim zig-zags 3 cm round it —
the collar p95 1.61, the back panel 1.30-1.36, the crew band split in two by a merged rim vertex. A known miss of the
body, reported, not hidden here.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


_TOP = {"kind": "top", "fabric": "medium", "shoulders": "covered", "sleeves": "elbow", "sleeve_fit": 0.5, "fit": 0.4,
        "length_m": 0.29}
CASES = {
    "1_stand_collar": dict(_TOP, neckline="crew", collar="stand"),
    "2_v": dict(_TOP, neckline="v", neck_depth_m=0.05),
    "3_deep_crew": dict(_TOP, neckline="crew", neck_depth_m=0.15),
    "4_crew": dict(_TOP, neckline="crew"),
}
ISLANDS = {
    "1_stand_collar": {"front", "back", "sleeve_l", "sleeve_r", "collar"},
    "2_v": {"front", "back", "sleeve_l", "sleeve_r"},
    "3_deep_crew": {"front", "back", "sleeve_l", "sleeve_r"},
    "4_crew": {"front", "back", "sleeve_l", "sleeve_r", "band"},
}
SAME = {
    "5_off_shoulder": {"kind": "top", "fabric": "medium", "shoulders": "off_shoulder", "sleeves": "elbow",
                       "sleeve_fit": 0.77, "length_m": 0.35},
    "5_straps": {"kind": "top", "fabric": "medium", "shoulders": "straps", "neckline": "straight", "length_m": 0.4,
                 "fit": 0.0},
}

_SUB = r'''
import json, sys
from pathlib import Path
repo, body, out, raw, inst = sys.argv[1:6]
sys.path.insert(0, repo)
from app.core import paths
paths.init(str(Path(out) / "storage"))
from app.blender import runner
runner.use_instance_config(Path(inst))
from app.core import garment_template as gt
params = gt.validate_params(json.loads(raw))[0]
spec = gt.panel_spec(params, gt.measure_body(Path(body).read_bytes()))
args = gt.build_args(params, spec, item_id="same")
args["cut_only"] = True
res = runner.run(gt.SCRIPT, inputs={"body": Path(body)}, params=args, out_dir=Path(out), timeout_s=600)
print("RESULT", json.dumps({"ok": bool(res.get("ok")), "error": str(res.get("error") or "")[:300]}))
'''


def run_in(repo: Path, body: Path, out: Path, raw: dict, inst: str) -> bool:
    out.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, "-c", _SUB, str(repo), str(body), str(out), json.dumps(raw), inst],
                       capture_output=True, text=True, cwd=str(repo))
    line = [x for x in p.stdout.splitlines() if x.startswith("RESULT ")]
    return bool(line) and json.loads(line[-1][7:])["ok"] and (out / "islands.json").is_file()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--base-repo")
    ap.add_argument("--corset-body")
    ap.add_argument("--instance", default=str(ROOT / "instance"), help="the instance dir (Blender's settings), read")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="smoke-cut-tops-"))
    from app.core import paths
    paths.init(str(tmp / "storage"))
    from app.blender import runner
    runner.use_instance_config(Path(a.instance))
    from app.core import garment_template as gt
    body = Path(a.body)
    meas = gt.measure_body(body.read_bytes())
    for name, raw in CASES.items():
        if a.only and name not in a.only:
            continue
        params = gt.validate_params(raw)[0]
        spec = gt.panel_spec(params, meas)
        args = gt.build_args(params, spec, item_id=name)
        args["cut_only"] = True
        out = tmp / name
        out.mkdir(parents=True)
        res = runner.run(gt.SCRIPT, inputs={"body": body}, params=args, out_dir=out, timeout_s=600)
        check(f"[{name}] runs", bool(res.get("ok")) and (out / "islands.json").is_file(),
              str(res.get("error") or "")[:300])
        if not (out / "islands.json").is_file():
            continue
        pay = json.loads((out / "islands.json").read_text())
        isl = {i["name"]: i for i in pay["islands"]}
        check(f"[{name}] islands {sorted(ISLANDS[name])}", set(isl) == ISLANDS[name], sorted(isl))
        panels = [i for i in pay["islands"] if i["name"] not in ("band", "collar")]
        bad = [(i["name"], i["distortion"]) for i in panels
               if not (0.97 <= i["distortion"]["area_ratio"] <= 1.03 and i["distortion"]["stretch_p95"] <= 1.30)]
        check(f"[{name}] panels area 0.97-1.03, p95 <= 1.30", not bad, bad)
        check(f"[{name}] px/cm >= 11.0", pay["px_per_cm"] >= 11.0, pay["px_per_cm"])
        for strip in ("band", "collar"):
            if strip in isl:
                d = isl[strip]["distortion"]
                check(f"[{name}] {strip} strip area 0.97-1.03, p95 <= 1.10",
                      0.97 <= d["area_ratio"] <= 1.03 and d["stretch_p95"] <= 1.10, d)
        marks = json.loads((out / "marks.json").read_text()) if (out / "marks.json").is_file() else {}
        lines = marks.get("lines") or {}
        cf = lines.get("centre_front") or {}
        px = cf.get("px") or []
        check(f"[{name}] marks: one centre_front line on front, top first",
              set(lines) == {"centre_front"} and cf.get("island") == "front" and len(px) >= 5
              and px[-1][1] - px[0][1] >= 10 * pay["px_per_cm"],
              {k: (v["island"], len(v["px"])) for k, v in lines.items()})
    if a.corset_body and not (a.only and "6_corset" not in a.only):
        params = gt.validate_params({"kind": "top", "shoulders": "strapless", "neckline": "sweetheart",
                                     "neck_depth_m": 0.1, "fit": 0.0, "length_m": 0.42, "fabric": "medium"})[0]
        cbody = Path(a.corset_body)
        spec = gt.panel_spec(params, gt.measure_body(cbody.read_bytes()))
        args = gt.build_args(params, spec, item_id="corset")
        args["cut_only"] = True
        out = tmp / "6_corset"
        out.mkdir(parents=True)
        res = runner.run(gt.SCRIPT, inputs={"body": cbody}, params=args, out_dir=out, timeout_s=600)
        check("[6_corset] runs", bool(res.get("ok")) and (out / "islands.json").is_file(), str(res.get("error"))[:300])
        if (out / "islands.json").is_file():
            pay = json.loads((out / "islands.json").read_text())
            isl = {i["name"]: i["distortion"] for i in pay["islands"]}
            check("[6_corset] islands {back, front}", set(isl) == {"front", "back"}, sorted(isl))
            check("[6_corset] panels area 0.97-1.03, p95 <= 1.25", all(
                0.97 <= d["area_ratio"] <= 1.03 and d["stretch_p95"] <= 1.25 for d in isl.values()), isl)
            lines = (json.loads((out / "marks.json").read_text()) if (out / "marks.json").is_file() else {}).get(
                "lines") or {}
            cb = (lines.get("centre_back") or {}).get("px") or []
            check("[6_corset] marks: one centre_back line on back, top first", set(lines) == {"centre_back"}
                  and lines["centre_back"]["island"] == "back" and len(cb) >= 10
                  and cb[-1][1] - cb[0][1] >= 20 * pay["px_per_cm"], {k: len(v["px"]) for k, v in lines.items()})
    if a.base_repo:
        for name, raw in SAME.items():
            if a.only and name not in a.only:
                continue
            mine, base = tmp / f"{name}_this", tmp / f"{name}_base"
            ok = run_in(ROOT, body, mine, raw, a.instance) and run_in(Path(a.base_repo), body, base, raw, a.instance)
            check(f"[{name}] runs in both checkouts", ok)
            if ok:
                check(f"[{name}] islands.json byte-identical to the base checkout",
                      (mine / "islands.json").read_bytes() == (base / "islands.json").read_bytes())
    print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
    print("work dir", tmp)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
