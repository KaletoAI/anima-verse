#!/usr/bin/env python3
"""The template drape's stretch gate, its narrow-miss retry and the hem off the underbust fold (bug round 2026-11-20).

Usage: ./.venv/bin/python scripts/smoke_stretch_gate.py
No server, no world DB (throwaway ``paths.init``), no Blender: the gate is ``app/blender/scripts/stretch_gate.py``
(numpy only), the retry runs ``run_drape`` on a stubbed runner, the hem is ``outline`` on a hand-built measure.

Expected values, by hand:

[1] ``stretch_gate.stretch`` (rest -> draped, mm; ratio = draped / rest; gate drops rest < 3 mm or growth < 1 mm,
    ``all`` drops only rest < 1 mm):
    a  Kira's blazer, the V's bottom: 1.33 -> 2.43: ratio 2.43 / 1.33 = 1.82707; rest under 3 mm -> gate 1.0,
       all 1.82707 (the stored failure read 1.823 on the same edge).
    b  its twin 1.24 -> 2.2: ratio 1.77419; gate 1.0, all 1.77419.
    c  a degenerate 0.5 -> 0.9 edge (A144): 1.8; gate 1.0 AND all 1.0.
    d  a real tear, 4.0 -> 5.3: ratio 1.325, growth 1.3 mm >= 1 -> gate 1.325 (fails: >= 1.3), all 1.325.
    e  Kira's skirt at the back waist, 10.4 -> 14.2: ratio 1.36538, growth 3.8 -> gate 1.36538.
    f  a 3.0 -> 3.95 edge: ratio 1.31667 but growth 0.95 mm < 1 -> gate 1.0, all 1.31667. (The boundary: an edge
       counts at ratio 1.3 only from 1 / 0.3 = 3.33 mm on; under that the gate needs growth >= 1 mm.)
    g  an ordinary 15 -> 15.3 edge: ratio 1.02, growth 0.3 mm < 1 -> gate 1.0, all 1.02 (below 1.3 it never
       mattered to the gate).
    The gated maximum of a..g = max(1.325, 1.36538) = 1.36538 (e); the ``all`` maximum = 1.82707 (a).
[2] ``retry_due`` (``THRESHOLDS["stretch_max"]`` 1.3 fails at >= 1.3, ``RETRY_STRETCH`` 1.5, ``NARROW_MISS_EDGES``
    4): 1.29 -> None; 1.3 with 1 edge -> "narrow"; Kai's jacket 1.329 with 1 edge -> "narrow"; 1.5 with 4 edges ->
    "narrow"; 1.5 with 5 edges -> None; 1.4 without ``over_1_3`` -> None; 1.51 with 412 edges -> "stretch"; an empty
    drape -> None. 1.6 without ``over_1_3`` -> "stretch" (the existing [6] stub of smoke_garment_template).
[3] ``run_drape`` on a stubbed runner (fabric "flowing", wall limit 60, half 30): first run stretch 1.329 with 1
    edge, script_wall_s 10 -> a second run at doubled quality; it returns 1.2 -> ok, ``data.retry`` = {reason
    "narrow", first_stretch_max 1.329}, qualities [q, 2q]. The same first run with script_wall_s 31 > 30 -> ONE run,
    ``retry_skipped`` set, refused ("stretch_max 1.329 (limit 1.3)"). A first run 1.329 with 6 edges -> one run, no
    ``retry_skipped`` (not due at all), refused. A first run at 1.25 -> one run, ok, no ``data.retry``.
[4] The hem off the underbust fold. Measure L (Lirien's numbers): shoulder_y 1.4027 (top_y = 1.4027 + 0.045 =
    1.4477), waist_y 1.0, band_y 1.30, torso [[1.0, .70], [1.10, .68], [1.168, .66], [1.20, .72], [1.25, .90],
    [1.288, .98], [1.30, .95], [1.36, 1.0]]. ``_bust_lines``: the widest sample in [1.05, 1.30] is 1.288 (.98) = the
    bust; the narrowest in [1.148, 1.248] is 1.168 (.66) = the fold. UNDERBUST_HEM_M 0.03.
    a  top, length 0.27: hem 1.4477 - 0.27 = 1.1777, |1.1777 - 1.168| = 0.0097 < 0.03 -> hem 1.168 - 0.03 = 1.138,
       knots from 1.138: the outline's length round(1.4477 - 1.138, 4) = 0.3097; ``hem_moved`` = {under_y 1.168,
       from_y 1.1777, hem_y 1.138, length_m 0.27, draped_length_m 0.3097}.
    b  top, length 0.24: hem 1.2077, 0.0397 above the fold -> stays, length 0.24, no ``hem_moved``.
    c  top, length 0.36: hem 1.0877, 0.0803 under -> stays (0.36).
    d  top, length 0.3087: hem 1.139, 0.029 under the fold -> moved to 1.138 (one mm longer: 0.3097).
    e  jacket, length 0.27 -> moved like a (0.3097).
    f  dress, length 0.27 (from the waist): no move (a dress hem is not a cropped top's).
    g  strapless top, length 0.27 (counted from the shoulder line 1.4477): its top edge is band 1.30 -
       STRAPLESS_UNDERARM_M 0.02 = 1.28, the hem min(1.28 - STRAPLESS_MIN_M 0.08 = 1.20, 1.4477 - 0.27 = 1.1777) =
       1.1777 -> on the fold, moved to 1.138: the outline's length round(1.28 - 1.138, 4) = 0.142, ``hem_moved``
       counted from the shoulder line like ``length_m``: draped_length_m 0.3097. Length 0.24: hem min(1.20, 1.2077) =
       1.20, 0.032 over the fold -> stays (length 1.28 - 1.20 = 0.08).
    Never shorter: in every moved case the new hem is under the old one (a, d, e).
    h  No fold, no move (review): ``UNDERBUST_STEP_M`` 0.10. Measure L's step: girth at the bust 0.98 - at the fold
       0.66 = 0.32 >= 0.10 -> a fold. Probe F (L with torso [[1.0, .80], [1.05, .82], [1.10, .85], [1.15, .88],
       [1.20, .92], [1.25, .96], [1.30, 1.0], [1.36, 1.02]], widening evenly): bust = widest in [1.05, 1.30] = 1.30
       (1.0), under = narrowest in [1.16, 1.26] = 1.20 (.92); step 1.0 - 0.92 = 0.08 < 0.10 -> no fold: a jacket
       0.27 (hem 1.1777, 2.23 cm under that line) stays at 0.27, no ``hem_moved``. Probe G (torso [[1.05, .82],
       [1.10, .84], [1.15, .86], [1.20, .89], [1.25, .92], [1.30, .96], [1.36, 1.0]], shoulder_y 1.48, band_y 1.36):
       bust 1.36 (1.0), under = narrowest in [1.22, 1.32] = 1.25 (.92), step 0.08 -> no fold: a top 0.28 (top_y
       1.48 + 0.045 = 1.525, hem 1.245) stays at 0.28. L without a torso profile (``_bust_lines`` falls back to
       band - 0.15 = 1.15, and 1.1777 is 2.77 cm over it): no measured fold -> top 0.27 stays at 0.27.
[5] The failure sentence of a top whose hem ends between the fold and the bust: a record with params top 0.27,
    outline top_y 1.4477 / length 0.27 (hem 1.1777), measure L, worst edge z 1.203 -> ``stretch_max_underbust`` and
    ``underbust_length`` = ceil((0.27 + 1.1777 - 1.138) x 100) / 100 = ceil(30.97) / 100 = 0.31; ``failure_info``
    fills value "1.48", limit "1.3", length "0.31". The same record with worst z 1.36 (>= 1.4027 - 0.05 = 1.3527)
    -> ``stretch_max_neck``; with z 1.40 on a skirt -> plain ``stretch_max``; with length 0.36 (hem 1.0877, under
    the fold) -> plain ``stretch_max``; worst z 1.33 (> bust 1.288 + 0.03 = 1.318) -> plain. No sentence says
    "shorter".
    Strapless (review): params strapless top, length 0.15; its outline top_y 1.28, length 0.08 (hem = min(1.20,
    1.4477 - 0.15 = 1.2977) = 1.20, the STRAPLESS_MIN_M floor), worst z 1.203. The hem 1.20 lies in [1.168, 1.288],
    z <= 1.318 -> ``stretch_max_underbust``; the length is counted from the shoulder line 1.4477 that ``length_m``
    counts from: ceil((1.4477 - 1.138) x 100) / 100 = ceil(30.97) / 100 = 0.31 (the old asked-based sum
    0.15 + 1.20 - 1.138 = 0.212 -> 0.22 left the hem at min(1.20, 1.2277) = 1.20: the same failure again). Check:
    the outline at 0.31 has hem min(1.20, 1.1377) = 1.1377, 3.03 cm under the fold -> not moved, length round(1.28 -
    1.1377, 4) = 0.1423, hem <= 1.138. The flat probe F with a top 0.20 (hem 1.2477, between its lines 1.20 / 1.30,
    worst z 1.203): no fold -> plain ``stretch_max``, ``underbust_length`` None.
[6] Source: the Blender script reads ``stretch_gate.stretch`` for its gate and its p99 from the ``all`` ratios;
    ``piece_progress`` hands the outline's ``hem_moved`` to the dialog; the dialog shows it; de.json has both new
    strings.
[7] The preview (``garment_preview.shapes``, a 100 px wide box mask 480 px tall, no camera): top 0.27 on L draws the
    moved hem, so its dimension reads the length draped 0.3097 -> "31 cm (asked 27)" and the hem mark "hem 1.14 m ·
    moved below the underbust fold" (1.138 -> 1.14); top 0.24 keeps "24 cm" / "hem 1.21 m" (1.2077).
"""
import math
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-stretch-gate-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

import numpy as np  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import stretch_gate as sg  # noqa: E402
sys.path.pop(0)

FAILS = []


def check(label, ok, got=None):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got: {got!r}"))
    if not ok:
        FAILS.append(label)


def close(a, b, tol=1e-4):
    return a is not None and abs(float(a) - float(b)) <= tol


# [1] the gate
rest = np.array([1.33, 1.24, 0.5, 4.0, 10.4, 3.0, 15.0]) / 1000
draped = np.array([2.43, 2.2, 0.9, 5.3, 14.2, 3.95, 15.3]) / 1000
gate, every = sg.stretch(rest, draped)
check("[1a] V bottom 1.33 -> 2.43: gate 1.0, all 1.82707", close(gate[0], 1.0) and close(every[0], 1.82707), (gate[0], every[0]))
check("[1b] 1.24 -> 2.2: gate 1.0, all 1.77419", close(gate[1], 1.0) and close(every[1], 1.77419), (gate[1], every[1]))
check("[1c] degenerate 0.5 mm: 1.0 in both", close(gate[2], 1.0) and close(every[2], 1.0), (gate[2], every[2]))
check("[1d] a tear 4.0 -> 5.3: gated 1.325", close(gate[3], 1.325) and close(every[3], 1.325), gate[3])
check("[1e] skirt 10.4 -> 14.2: gated 1.36538", close(gate[4], 1.36538), gate[4])
check("[1f] 3.0 -> 3.95 grew 0.95 mm: gate 1.0, all 1.31667", close(gate[5], 1.0) and close(every[5], 1.31667),
      (gate[5], every[5]))
check("[1g] ordinary 15 -> 15.3: gate 1.0, all 1.02", close(gate[6], 1.0) and close(every[6], 1.02), (gate[6], every[6]))
check("[1] maxima: gate 1.36538, all 1.82707", close(gate.max(), 1.36538) and close(every.max(), 1.82707))
check("[1] constants 1 / 3 / 1 mm", sg.MIN_EDGE_M == 0.001 and sg.GATE_MIN_REST_M == 0.003
      and sg.GATE_MIN_GROW_M == 0.001)

# [2] retry_due
cases = [({"stretch_max": 1.29, "stretch_at": {"over_1_3": 0}}, None),
         ({"stretch_max": 1.3, "stretch_at": {"over_1_3": 1}}, "narrow"),
         ({"stretch_max": 1.329, "stretch_at": {"over_1_3": 1}}, "narrow"),
         ({"stretch_max": 1.5, "stretch_at": {"over_1_3": 4}}, "narrow"),
         ({"stretch_max": 1.5, "stretch_at": {"over_1_3": 5}}, None),
         ({"stretch_max": 1.4}, None),
         ({"stretch_max": 1.51, "stretch_at": {"over_1_3": 412}}, "stretch"),
         ({}, None),
         ({"stretch_max": 1.6}, "stretch")]
for drape, want in cases:
    check(f"[2] retry_due {drape} -> {want}", gt.retry_due(drape) == want, gt.retry_due(drape))
check("[2] constants", gt.THRESHOLDS["stretch_max"] == 1.3 and gt.RETRY_STRETCH == 1.5 and gt.NARROW_MISS_EDGES == 4)

# [3] run_drape on a stubbed runner
from app.blender import runner as _runner  # noqa: E402


def drape_with(first, *, wall=10.0):
    runs = []

    def fake(script, **kw):
        runs.append(kw["params"]["fabric"]["quality"])
        d = first if len(runs) == 1 else {"stretch_max": 1.2, "stretch_at": {"over_1_3": 0}}
        return {"ok": True, "outcome": "ok", "error": "", "log_tail": "", "outputs": {"glb": "/x.glb"},
                "data": {"script_wall_s": wall, "render_wall_s": 0.0,
                         "drape": {"cpu_s": 9.0, "pin_drift_mm": 0.5, **d},
                         "draped": {"rest": {"poke_share": 0.0}}}}

    saved = (_runner.run, gt.measure_body, gt.panel_spec, gt.prepare_view)
    _runner.run = fake
    gt.measure_body = lambda glb: {}
    gt.panel_spec = lambda params, meas, **_k: {"outline": {}, "row_y": [0.0], "measure": {}}
    gt.prepare_view = lambda src, dst, garment_only=True: {}
    tmp = Path(tempfile.mkdtemp(prefix="smoke-stretch-run-"))
    try:
        (tmp / "b.glb").write_bytes(b"glb")
        res = gt.run_drape(tmp / "b.glb", gt.validate_params({"kind": "top", "fabric": "flowing"})[0],
                           {"front": "f", "back": "b"}, item_id="i1", out_dir=tmp / "out")
    finally:
        _runner.run, gt.measure_body, gt.panel_spec, gt.prepare_view = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return runs, res


q = gt.FABRICS["flowing"]["quality"]
runs, res = drape_with({"stretch_max": 1.329, "stretch_at": {"over_1_3": 1}})
check("[3] narrow miss: two runs, quality doubled", runs == [q, 2 * q], runs)
check("[3] narrow miss: the retry's 1.2 passes", res["ok"] and res["outcome"] == "ok", res["error"])
check("[3] narrow miss: data.retry recorded", res["data"].get("retry") == {"reason": "narrow", "first_stretch_max": 1.329},
      res["data"].get("retry"))
runs, res = drape_with({"stretch_max": 1.329, "stretch_at": {"over_1_3": 1}}, wall=31.0)
check("[3] slow first run: one run, skipped, refused", runs == [q] and res["data"].get("retry_skipped")
      and not res["ok"] and res["error"] == "stretch_max 1.329 (limit 1.3)", (runs, res["error"]))
runs, res = drape_with({"stretch_max": 1.329, "stretch_at": {"over_1_3": 6}})
check("[3] six edges over: one run, not due, refused", runs == [q] and not res["data"].get("retry_skipped")
      and not res["ok"], (runs, res["data"].get("retry_skipped")))
runs, res = drape_with({"stretch_max": 1.25, "stretch_at": {"over_1_3": 0}})
check("[3] a pass: one run, ok, no retry", runs == [q] and res["ok"] and "retry" not in res["data"], runs)

# [4] the hem off the fold
L = {"height": 1.7, "floor_y": 0.0, "waist_y": 1.0, "waist_c": 0.70, "hip_y": 0.85, "hip_c": 0.95,
     "band_y": 1.30, "band_c": 0.95, "shoulder_y": 1.4027, "shoulder_w": 0.39, "neck_y": 1.45, "neck_c": 0.33,
     "arm_len": 0.50, "arm_c": [[0.05, 0.34], [0.25, 0.26], [0.5, 0.24], [0.97, 0.17]], "joints": {},
     "torso": [[1.0, .70], [1.10, .68], [1.168, .66], [1.20, .72], [1.25, .90], [1.288, .98], [1.30, .95],
               [1.36, 1.0]]}
check("[4] fold 1.168, bust 1.288", gt._bust_lines(L) == (1.168, 1.288), gt._bust_lines(L))
check("[4] UNDERBUST_HEM_M 0.03", gt.UNDERBUST_HEM_M == 0.03)


def shape(**p):
    return gt.outline(gt.validate_params(p)[0], L)


o = shape(kind="top", length_m=0.27)
check("[4a] top 0.27 -> hem 1.138, length 0.3097", close(o["length"], 0.3097) and close(o["top_y"], 1.4477), o["length"])
check("[4a] hem_moved recorded", o.get("hem_moved") == {"under_y": 1.168, "from_y": 1.1777, "hem_y": 1.138,
                                                       "length_m": 0.27, "draped_length_m": 0.3097}, o.get("hem_moved"))
o = shape(kind="top", length_m=0.24)
check("[4b] top 0.24 stays", close(o["length"], 0.24) and "hem_moved" not in o, (o["length"], o.get("hem_moved")))
o = shape(kind="top", length_m=0.36)
check("[4c] top 0.36 stays", close(o["length"], 0.36) and "hem_moved" not in o, o["length"])
o = shape(kind="top", length_m=0.3087)
check("[4d] top 0.3087 (hem 1.139) -> 0.3097", close(o["length"], 0.3097) and o.get("hem_moved"), o["length"])
o = shape(kind="jacket", length_m=0.27)
check("[4e] jacket 0.27 -> 0.3097", close(o["length"], 0.3097) and o.get("hem_moved"), o["length"])
o = shape(kind="dress", length_m=0.27)
check("[4f] dress: no move", "hem_moved" not in o, o.get("hem_moved"))
o = shape(kind="top", length_m=0.27, shoulders="strapless")
check("[4g] strapless top 0.27: moved to 1.138, length 0.142", gt.strapless_top(gt.validate_params(
    {"kind": "top", "shoulders": "strapless"})[0]) and close(o["top_y"], 1.28) and close(o["length"], 0.142)
      and (o.get("hem_moved") or {}).get("draped_length_m") == 0.3097, (o["top_y"], o["length"], o.get("hem_moved")))
o = shape(kind="top", length_m=0.24, shoulders="strapless")
check("[4g] strapless top 0.24 stays (0.08)", close(o["length"], 0.08) and "hem_moved" not in o, o["length"])
for n in (0.27, 0.3087, 0.2801, 0.32):
    for kind in ("top", "jacket"):
        hm = shape(kind=kind, length_m=n).get("hem_moved")
        if hm:
            check(f"[4] never shorter ({kind} {n})", hm["hem_y"] < hm["from_y"] and hm["draped_length_m"] > n, hm)

F = {**L, "torso": [[1.0, .80], [1.05, .82], [1.10, .85], [1.15, .88], [1.20, .92], [1.25, .96], [1.30, 1.0],
                   [1.36, 1.02]]}
G = {**L, "shoulder_y": 1.48, "band_y": 1.36,
     "torso": [[1.05, .82], [1.10, .84], [1.15, .86], [1.20, .89], [1.25, .92], [1.30, .96], [1.36, 1.0]]}
NOPROF = {k: v for k, v in L.items() if k != "torso"}
check("[4h] UNDERBUST_STEP_M 0.10, L has a fold", gt.UNDERBUST_STEP_M == 0.10 and gt._underbust_fold(L) == (1.168, 1.288))
check("[4h] probe F: lines (1.20, 1.30), no fold", gt._bust_lines(F) == (1.2, 1.3) and gt._underbust_fold(F) is None,
      (gt._bust_lines(F), gt._underbust_fold(F)))
o = gt.outline(gt.validate_params({"kind": "jacket", "length_m": 0.27})[0], F)
check("[4h] probe F jacket 0.27 stays", close(o["length"], 0.27) and "hem_moved" not in o, (o["length"], o.get("hem_moved")))
check("[4h] probe G: lines (1.25, 1.36), no fold", gt._bust_lines(G) == (1.25, 1.36) and gt._underbust_fold(G) is None,
      gt._bust_lines(G))
o = gt.outline(gt.validate_params({"kind": "top", "length_m": 0.28})[0], G)
check("[4h] probe G top 0.28 stays", close(o["length"], 0.28) and "hem_moved" not in o, (o["length"], o.get("hem_moved")))
o = gt.outline(gt.validate_params({"kind": "top", "length_m": 0.27})[0], NOPROF)
check("[4h] no torso profile: top 0.27 stays", gt._underbust_fold(NOPROF) is None and close(o["length"], 0.27)
      and "hem_moved" not in o, (o["length"], o.get("hem_moved")))

# [5] the sentence
REC = {"params": gt.validate_params({"kind": "top", "length_m": 0.27})[0],
       "metrics": {"outline": {"top_y": 1.4477, "length": 0.27}, "measure": L,
                   "drape": {"stretch_at": {"z": 1.203}}},
       "rows": [{"check": "stretch_max", "value": 1.482, "limit": 1.3, "ok": False, "gate": True}],
       "outcome": "rejected"}


def rec(z=1.203, length=0.27, kind="top"):
    r = {**REC, "params": gt.validate_params({"kind": kind, "length_m": length})[0]}
    r["metrics"] = {**REC["metrics"], "outline": {"top_y": 1.4477, "length": length}, "drape": {"stretch_at": {"z": z}}}
    return r


check("[5] hem on the chest -> underbust sentence", gt.stretch_line(rec()) == "stretch_max_underbust", gt.stretch_line(rec()))
check("[5] its length 0.31", gt.underbust_length(rec()) == 0.31, gt.underbust_length(rec()))
lines = gt.failure_info(rec())["lines"]
check("[5] failure_info fills value / limit / length",
      lines == [{"text": gt.FAILURE_SENTENCES["stretch_max_underbust"],
                 "values": {"value": "1.48", "limit": "1.3", "length": "0.31"}}], lines)
check("[5] z 1.36 -> neck", gt.stretch_line(rec(z=1.36)) == "stretch_max_neck")
check("[5] a skirt -> plain", gt.stretch_line(rec(z=1.40, kind="skirt")) == "stretch_max")
check("[5] hem under the fold (0.36) -> plain", gt.stretch_line(rec(length=0.36)) == "stretch_max")
check("[5] worst edge over the bust (1.33) -> plain", gt.stretch_line(rec(z=1.33)) == "stretch_max")
SP = gt.validate_params({"kind": "top", "length_m": 0.15, "shoulders": "strapless"})[0]
o = gt.outline(SP, L)
check("[5] strapless 0.15: outline top 1.28, length 0.08 (hem 1.20)", close(o["top_y"], 1.28) and close(o["length"], 0.08),
      (o["top_y"], o["length"]))
srec = {**REC, "params": SP, "metrics": {**REC["metrics"], "outline": {"top_y": o["top_y"], "length": o["length"]},
                                        "drape": {"stretch_at": {"z": 1.203}}}}
check("[5] strapless 0.15 -> underbust sentence", gt.stretch_line(srec) == "stretch_max_underbust", gt.stretch_line(srec))
check("[5] strapless 0.15 -> length 0.31 (from the shoulder line)", gt.underbust_length(srec) == 0.31,
      gt.underbust_length(srec))
o = gt.outline({**SP, "length_m": 0.31}, L)
check("[5] strapless at 0.31: hem 1.1377 <= 1.138, not moved", close(o["top_y"] - o["length"], 1.1377)
      and close(o["length"], 0.1423) and "hem_moved" not in o, (o["length"], o.get("hem_moved")))
frec = {**rec(length=0.20), "metrics": {**rec(length=0.20)["metrics"], "measure": F}}
check("[5] flat probe F, top 0.20 -> plain, no length", gt.stretch_line(frec) == "stretch_max"
      and gt.underbust_length(frec) is None, gt.stretch_line(frec))
check("[5] no sentence says shorter", not [k for k, v in gt.FAILURE_SENTENCES.items() if "shorter" in v.lower()])

# [6] source
build = (ROOT / "app/blender/scripts/garment_template_build.py").read_text()
check("[6] build script gates through stretch_gate", "st, st_all = sg.stretch(rest_len" in build
      and "np.percentile(st_all, 99)" in build and '"stretch_max": round(float(st.max()), 3)' in build)
src = (ROOT / "app/core/garment_template.py").read_text()
check("[6] piece_progress hands hem_moved on", '"hem_moved": (metrics.get("outline") or {}).get("hem_moved")' in src)
dialog = (ROOT / "frontend/src/tabs/characters/TemplateParamsDialog.tsx").read_text()
key = "Hem moved below the underbust fold: draped {draped} m long instead of {asked} m"
check("[6] dialog shows it", key in dialog and "p.hem_moved" in dialog)
import json  # noqa: E402
de = json.loads((ROOT / "shared/languages/de.json").read_text())["translations"]
check("[6] de.json has both strings", key in de and gt.FAILURE_SENTENCES["stretch_max_underbust"] in de)

# [7] the preview
from app.core import garment_preview as gp  # noqa: E402
mask = np.zeros((500, 400), dtype=bool)
mask[10:490, 150:250] = True
reg = gp.Registration(gp.frame_of_mask(mask), L)
texts = [m["text"] for m in gp.shapes(gt.validate_params({"kind": "top", "length_m": 0.27})[0], L, reg)["marks"]]
check("[7] preview of a moved hem: '31 cm (asked 27)', hem mark says it moved",
      "31 cm (asked 27)" in texts and "hem 1.14 m · moved below the underbust fold" in texts, texts)
texts = [m["text"] for m in gp.shapes(gt.validate_params({"kind": "top", "length_m": 0.24})[0], L, reg)["marks"]]
check("[7] preview of a hem that stays: '24 cm', 'hem 1.21 m'", "24 cm" in texts and "hem 1.21 m" in texts, texts)

shutil.rmtree(_SCRATCH, ignore_errors=True)
print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
