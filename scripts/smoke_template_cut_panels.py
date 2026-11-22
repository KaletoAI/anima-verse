"""Smoke (real Blender, CPU, 0 hub jobs): the jacket's and the dress's pattern pieces (plan group B, phases C / D).

Usage:
    ./.venv/bin/python scripts/smoke_template_cut_panels.py --body <plain base body .glb> [--dress-body <.glb>] \
        [--only NAME ...] \
        [--instance <instance dir, default <repo>/instance>]

Work on a COPY of a character's base body (``model3d/base*.glb``), never on a live world folder: everything this writes
goes into a temp folder; ``--dress-body`` (default ``--body``) is the body the dress cases [5] / [6] are cut on. Each case
is a cut-only run (``garment_template_cut.run_blender`` args: ``build_args`` +
``cut_only``) of ``validate_params`` of the case's params, no lower layers.

What the rules of ``garment_template_build.build_bodice`` (``kind`` jacket / dress) give, derived from them:

[1] an open jacket, V neck, no collar (B7, B8): the fronts are ``left_front`` / ``right_front`` (columns c < N/4 and
    c >= 3N/4 of an open front: two parts, never ``front`` / ``front_2``), no ``band`` (an open front has no neckband);
    islands exactly {left_front, right_front, back, sleeve_l, sleeve_r}; ``marks.json`` holds ``edge_left`` on the
    island ``left_front`` and ``edge_right`` on ``right_front``, each at least 10 points, top first: the last point
    at least 20 cm under the first (a 0.6 m jacket's edge runs from the neck to the hem), no step up by more than 1 cm
    (the neck rim's own curve may lift the second point a few pixels).
[2] a closed jacket, crew neck, stand collar (B8, B9): no ``band`` (a collar is the binding), a ``collar`` island whose
    strip (cut at the back centre, relaxed like the waistband) keeps area 0.97-1.03 and stretch p95 <= 1.10 (B24); one
    ``centre_front`` line on ``front``.
[3] a closed jacket, V 0.26 m deep, no collar: no ``band`` (a V is no crew / boat / shallow scoop, B8).
[4] a closed jacket, crew, no collar: a ``band`` (B8 keeps it), relaxed: p95 <= 1.10 (B24).
[5] a covered dress with long sleeves, crew: the torso at and under the row nearest the outline's waist is the skirt
    part (B6): islands {front, back, skirt_front, skirt_back, band, sleeve_l, sleeve_r}; the ``centre_front`` line ends
    at the waist seam — its last point lies ON the front island's outline (<= 0.5 px from a loop point: the waist
    row's centre vertex is a border vertex of the bodice front) in its lower half, never in the skirt part.
[6] a dress with straps and a slit on the left side seam (B23: no marked cut at all): it runs; islands {front, back,
    skirt_front, skirt_back} (straps: no band, no sleeves).
Every case: the panels' area ratio 0.97-1.03 and stretch p95 <= 1.30 (B24: bodice / jacket panels; a skirt part's own
limit 1.25 is checked too), px/cm >= 11.0.

Measured 2026-11-22 (copies of the world's base bodies): Kai's body passes the jacket cases [1]-[4], Vallerie's the
dress cases [5] / [6] (a long-sleeved dress cut on Kai's body packs at 10.96 px/cm: its 66 cm neckband widens the
sleeve row — a dress on a body that tall is no case of the world). Vallerie's body fails [2]: her
crew neckline is cut 7.3 cm deep at the front, the collar keeps its faces where the cut is up to ``COLLAR_CUT_MAX_M``
(3 cm), and its ends follow the cut down — a strip of 30.5 cm with folded ends, stretch p95 1.14 > 1.10. A known miss
of B24 for a stand collar on a deep crew neck (reported, not hidden here).
"""
import argparse
import json
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


CASES = {
    "1_open_jacket": {"kind": "jacket", "length_m": 0.6, "fit": 0.8, "sleeves": "long", "neckline": "v",
                      "front": "open", "collar": "none"},
    "2_stand_jacket": {"kind": "jacket", "length_m": 0.47, "fit": 0.0, "sleeves": "long", "neckline": "crew",
                       "front": "closed", "collar": "stand"},
    "3_v_jacket": {"kind": "jacket", "length_m": 0.47, "fit": 0.0, "sleeves": "long", "neckline": "v",
                   "neck_depth_m": 0.26, "front": "closed", "collar": "none"},
    "4_crew_jacket": {"kind": "jacket", "length_m": 0.47, "fit": 0.0, "sleeves": "long", "neckline": "crew",
                      "front": "closed", "collar": "none"},
    "5_dress": {"kind": "dress", "length_m": 0.5, "flare": 0.3, "shoulders": "covered", "sleeves": "long",
                "fit": 0.4, "neckline": "crew"},
    "6_strap_dress": {"kind": "dress", "length_m": 0.8, "flare": 0.4, "slit": "left", "slit_m": 0.25,
                      "shoulders": "straps", "neckline": "crew"},
}
ISLANDS = {
    "1_open_jacket": {"left_front", "right_front", "back", "sleeve_l", "sleeve_r"},
    "2_stand_jacket": {"front", "back", "sleeve_l", "sleeve_r", "collar"},
    "3_v_jacket": {"front", "back", "sleeve_l", "sleeve_r"},
    "4_crew_jacket": {"front", "back", "sleeve_l", "sleeve_r", "band"},
    "5_dress": {"front", "back", "skirt_front", "skirt_back", "band", "sleeve_l", "sleeve_r"},
    "6_strap_dress": {"front", "back", "skirt_front", "skirt_back"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True)
    ap.add_argument("--dress-body")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--instance", default=str(ROOT / "instance"), help="the instance dir (Blender's settings), read")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="smoke-cut-panels-"))
    from app.core import paths
    paths.init(str(tmp / "storage"))
    from app.blender import runner
    runner.use_instance_config(Path(a.instance))
    from app.core import garment_template as gt
    bodies = {"jacket": Path(a.body), "dress": Path(a.dress_body or a.body)}
    meas_of = {k: gt.measure_body(b.read_bytes()) for k, b in bodies.items()}
    for name, raw in CASES.items():
        if a.only and name not in a.only:
            continue
        params = gt.validate_params(raw)[0]
        body, meas = bodies[params["kind"]], meas_of[params["kind"]]
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
               if not (0.97 <= i["distortion"]["area_ratio"] <= 1.03 and i["distortion"]["stretch_p95"] <= 1.30)
               or (i["name"].startswith("skirt_") and i["distortion"]["stretch_p95"] > 1.25)]
        check(f"[{name}] panels area 0.97-1.03, p95 <= 1.30 (skirt part 1.25)", not bad, bad)
        check(f"[{name}] px/cm >= 11.0", pay["px_per_cm"] >= 11.0, pay["px_per_cm"])
        for strip in ("band", "collar"):
            if strip in isl:
                d = isl[strip]["distortion"]
                check(f"[{name}] {strip} strip area 0.97-1.03, p95 <= 1.10",
                      0.97 <= d["area_ratio"] <= 1.03 and d["stretch_p95"] <= 1.10, d)
        marks = json.loads((out / "marks.json").read_text()) if (out / "marks.json").is_file() else {}
        lines = marks.get("lines") or {}
        if name == "1_open_jacket":
            ok = (lines.get("edge_left", {}).get("island") == "left_front"
                  and lines.get("edge_right", {}).get("island") == "right_front"
                  and all(len(lines[k]["px"]) >= 10
                          and lines[k]["px"][-1][1] - lines[k]["px"][0][1] >= 20 * pay["px_per_cm"]
                          and all(b[1] > a_[1] - pay["px_per_cm"] for a_, b in zip(lines[k]["px"], lines[k]["px"][1:]))
                          for k in ("edge_left", "edge_right") if k in lines))
            check(f"[{name}] marks: the two front edges, top first", ok, {k: (v["island"], len(v["px"]))
                                                                         for k, v in lines.items()})
        else:
            cf = lines.get("centre_front") or {}
            check(f"[{name}] marks: centre_front on front", cf.get("island") == "front" and len(cf.get("px", [])) >= 5
                  and set(lines) == {"centre_front"}, {k: (v["island"], len(v["px"])) for k, v in lines.items()})
            if name == "5_dress" and cf.get("px"):
                import math
                f = isl["front"]
                last = cf["px"][-1]
                on = min(math.dist(last, q) for loop in f["loops_px"] for q in loop)
                y0, y1 = f["bbox_px"][1], f["bbox_px"][3]
                check(f"[{name}] the line ends on the front's outline in its lower half (the waist seam)",
                      on <= 0.5 and last[1] > 0.5 * (y0 + y1), (last, on, y0, y1))
    print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
    print("work dir", tmp)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
