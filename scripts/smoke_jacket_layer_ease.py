#!/usr/bin/env python3
"""A jacket over a sleeved layer gets a layer allowance on its sleeve and room at the armhole (bug round 2026-11-20).

Usage: ./.venv/bin/python scripts/smoke_jacket_layer_ease.py
No server, no world DB (throwaway ``paths.init``), no Blender: the pattern is ``panel_spec`` / ``bodice_spec`` /
``outline`` on hand-built measures, the layer test runs on stubbed items, the plumbing on a stubbed runner.

The bug: Kai's template jacket (sleeves long, sleeve_fit 0.3, fit 0) drapes over a template T-shirt (sleeves short,
sleeve_fit 0.3). Both sleeves had the same ease 1 + SLEEVE_EASE[0] 0.05 + SLEEVE_EASE[1] 0.40 x 0.3 = 1.17, so at
every distance along the arm the jacket sleeve had exactly the rest girth of the shirt sleeve under it, and one edge
over the shirt's hem stretched to 1.329 (limit 1.3).

Expected values, by hand. Measure K = Kai's arm (failure record ``item_black_lederjacket_copy_80150fe776cd``):
arm_len 0.5618, arm_c [[0.05, 0.4523], [0.15, 0.4244], [0.25, 0.3922], [0.35, 0.3501], [0.5, 0.3254],
[0.65, 0.3109], [0.8, 0.2492], [0.97, 0.1996]], shoulder_y 1.4787 (top_y 1.5237), band_y 1.395; a FLAT torso of
girth 1.0 (no underbust fold: the girth never climbs) so the bodice knots read straight off the ease.

[1] The allowance (``JACKET_SLEEVE_EASE``) is one cloth layer round the arm: the drape's collision distance is
    ``thickness`` 0.004 m for the cloth AND the collider's ``thickness_outer`` (garment_template_drape), so the
    jacket stands 0.004 + 0.004 = 0.008 m off the shirt sleeve's cloth: 2 x pi x 0.008 = 0.050265 m more girth.
    Over the shirt sleeve (shares 0 .. 0.3 of the arm; under 0.05 the table holds 0.4523) the mean arm girth is
    (0.05 x 0.4523 + 0.1 x (0.4523 + 0.4244) / 2 + 0.1 x (0.4244 + 0.3922) / 2 + 0.05 x (0.3922 + 0.37115) / 2)
    / 0.3 = (0.022615 + 0.043835 + 0.04083 + 0.019084) / 0.3 = 0.126364 / 0.3 = 0.42121 m (0.37115 = the girth at
    share 0.3, half-way 0.25 -> 0.35). 0.050265 / 0.42121 = 0.1193 -> JACKET_SLEEVE_EASE = 0.12 (within 0.005).
    ``layer_ease``: a jacket with sleeves over sleeves 0.12; the same jacket not over sleeves 0; a top over sleeves
    0 (only a jacket is the outer layer); a sleeveless jacket over sleeves 0.
[2] Sleeve rings on K (ring 0 at d 0 clamps to share 0.05's 0.4523):
    without:  0.4523 x 1.17 + 0.02 = 0.549191 -> 0.5492;  over sleeves: 0.4523 x 1.29 + 0.02 = 0.603467 -> 0.6035.
    d 0.15 (share 0.267): girth 0.3922 - 0.17 x 0.0421 = 0.385043 -> without 0.4705, over 0.5167.
    The shirt (top, sleeves short, sleeve_fit 0.3) on K: length 0.3 x 0.5618 = 0.1685; its last ring 0.37115 x 1.17
    + 0.02 = 0.454246 -> 0.4542, and at d 0.15 the same 0.4705 as the jacket without the allowance — THE BUG: the
    jacket's ring minus the shirt's ring at the same d is 0 at every ring of the shirt's span. Over sleeves it is
    0.12 x girth: 0.603467 - 0.549191 = 0.0543 at d 0, 0.5167 - 0.4705 = 0.0462 at d 0.15 (rounded rings: within
    0.0002) — each between 0.044 and 0.055, i.e. one layer's 0.050 within the arm's taper.
    The jacket over sleeves has the same ring distances and count as without (only the girths change).
[3] Armhole room (``_bodice_outline``): jacket fit 0, length 0.47 -> hem 1.5237 - 0.47 = 1.0537, knots every 2 cm
    from it. Ease 1 + BODICE_EASE[0] 0.03 + 0.17 x 0 + JACKET_EASE 0.05 = 1.08 -> knot 1.0 x 1.08 + 0.02 = 1.10
    without. Over sleeves the room w = clamp(1 - (band_y - y) / ARMHOLE_BLEND_M 0.06, 0, 1) adds 0.12 x w:
    knot 14 (y 1.3337, 0.0613 under the band): w 0 -> 1.10;  knot 15 (y 1.3537, 0.0413 under): w 0.31167 ->
    1.08 + 0.0374 + 0.02 = 1.1374;  knot 17 (y 1.3937, 0.0013 under): w 0.97833 -> 1.08 + 0.1174 + 0.02 = 1.2174;
    knot 18 (y 1.4137, over the band): w 1 -> 1.20 + 0.02 = 1.22; the top knot (1.5237): 1.22. Every knot 0..14
    equals the knot without (the hem stays). The same jacket NOT over sleeves: all knots 1.10 (unchanged).
    ``panel_spec`` over sleeves carries ``layer_ease`` 0.12; without, no ``layer_ease`` key, and its spec equals the
    spec built with the keyword left out (the old call).
[4] Which layers count (``over_sleeved_layer``, stubbed items, ``inner_pieces`` by layer slots): jacket JT (outer)
    over a template T-shirt TS (top, sleeves short) -> True; over a template tank top TN (top, sleeves none) ->
    False; over an own-mesh top OT -> False (an own-mesh piece says nothing about sleeves; A200's shrink / drop
    fallback stays its answer); the T-shirt TS itself over nothing -> False.
    The key (``key_for``): JT over TS carries the token ``ease:over_sleeves`` — its key differs from the same key
    with ``layer_ease`` forced to 0 (a jacket cut wider re-drapes); JT over TN has the same key either way (nothing
    re-drapes there, and TEMPLATE_VERSION is not bumped: still 9).
[5] Plumbing: ``run_drape(..., over_sleeves=True)`` hands the spec with ``layer_ease`` 0.12 to the Blender runner
    (stubbed: it records ``params["spec"]``); ``over_sleeves`` left out -> no ``layer_ease``. ``_build_drape``
    computes ``over_sleeved_layer`` once and passes it to every ``run_drape`` of ``drape_with_fallback`` and writes
    ``layer_ease`` into the record (source).

Measured on copies (not re-run here; Blender, ~2 min each, ``~/claude-out/bugrunde-1120/fix-c3/``): Kai's jacket
over underwear + T-shirt + jeans (the 08:51 set, shaped body), first drape: before 1.329 (1 edge over, x 0.369 z
1.371, refused); sleeve-only +0.05 / +0.08 1.406 / 1.384 at the armpit (x 0.25 z 1.32); +0.08 with the armhole room
1.372; +0.12 sleeve-only 1.243 (= sleeve_fit 0.6); with the armhole room +0.10 / +0.12 / +0.14 drape at 1.181 /
1.184 / 1.221, no edge over 1.3 (0.12, the derived value, sits on that plateau). Without the T-shirt (nothing
sleeved under it) the jacket drapes at 1.254 at the armpit, the same number and edge as before the change.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-jacket-layer-ease-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import body_slots, garment_template as gt  # noqa: E402
from app.models import inventory  # noqa: E402

FAILS = []


def check(label, ok, got=None):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got: {got!r}"))
    if not ok:
        FAILS.append(label)


def close(a, b, tol=1e-4):
    return a is not None and abs(float(a) - float(b)) <= tol


ARM_C = [[0.05, 0.4523], [0.15, 0.4244], [0.25, 0.3922], [0.35, 0.3501], [0.5, 0.3254], [0.65, 0.3109],
         [0.8, 0.2492], [0.97, 0.1996]]
K = {"height": 1.86, "floor_y": 0.0, "waist_y": 1.183, "waist_c": 1.0, "hip_y": 0.927, "hip_c": 1.0,
     "band_y": 1.395, "band_c": 1.0, "shoulder_y": 1.4787, "shoulder_w": 0.4934, "neck_y": 1.5377, "neck_c": 0.6215,
     "arm_len": 0.5618, "arm_c": ARM_C, "upper_arm_c": 0.3922, "wrist_c": 0.1996, "joints": {},
     "torso": [[0.90, 1.0], [1.10, 1.0], [1.30, 1.0], [1.55, 1.0]]}


def v(**p):
    return gt.validate_params(p)[0]


JACKET = v(kind="jacket", sleeves="long", sleeve_fit=0.3, fit=0.0, length_m=0.47, front="open")
SHIRT = v(kind="top", sleeves="short", sleeve_fit=0.3, fit=0.0)

# [1]
seg = [(0.0, 0.05, 0.4523, 0.4523), (0.05, 0.15, 0.4523, 0.4244), (0.15, 0.25, 0.4244, 0.3922),
       (0.25, 0.30, 0.3922, 0.37115)]
mean = sum((b - a) * (ga + gb) / 2 for a, b, ga, gb in seg) / 0.3
check("[1] mean arm girth over the shirt sleeve 0.42121", close(mean, 0.42121, 1e-5), mean)
layer = 2 * 3.141592653589793 * (0.004 + 0.004)
check("[1] one layer 0.050265 m / mean girth = 0.1193 ~ JACKET_SLEEVE_EASE 0.12",
      close(layer / mean, 0.1193, 1e-4) and abs(gt.JACKET_SLEEVE_EASE - layer / mean) <= 0.005
      and gt.JACKET_SLEEVE_EASE == 0.12, (layer / mean, gt.JACKET_SLEEVE_EASE))
check("[1] layer_ease jacket over sleeves 0.12", gt.layer_ease(JACKET, True) == 0.12)
check("[1] layer_ease jacket not over sleeves 0", gt.layer_ease(JACKET, False) == 0.0)
check("[1] layer_ease top over sleeves 0", gt.layer_ease(SHIRT, True) == 0.0)
check("[1] layer_ease sleeveless jacket 0", gt.layer_ease(v(kind="jacket", sleeves="none"), True) == 0.0)

# [2]
plain = gt.bodice_spec(JACKET, K)["sleeve"]["rings"]
over = gt.bodice_spec(JACKET, K, over_sleeves=True)["sleeve"]["rings"]
shirt = gt.bodice_spec(SHIRT, K)["sleeve"]
check("[2] ring 0 without 0.5492", close(plain[0][1], 0.5492), plain[0])
check("[2] ring 0 over sleeves 0.6035", close(over[0][1], 0.6035), over[0])
at15 = [r for r in plain if close(r[0], 0.15)]
at15o = [r for r in over if close(r[0], 0.15)]
check("[2] d 0.15 without 0.4705 / over 0.5167", at15 and at15o and close(at15[0][1], 0.4705)
      and close(at15o[0][1], 0.5167), (at15, at15o))
check("[2] the shirt: length 0.1685, last ring 0.4542", close(shirt["len_m"], 0.1685)
      and close(shirt["rings"][-1][1], 0.4542), shirt["rings"][-1])
sh = {round(d, 4): c for d, c in shirt["rings"]}
pl = {round(d, 4): c for d, c in plain}
ov = {round(d, 4): c for d, c in over}
common = [d for d in sh if d in pl]
check("[2] the bug: without the allowance the jacket ring = the shirt ring over the shirt's span",
      len(common) >= 6 and all(close(pl[d], sh[d], 1e-9) for d in common), [(d, pl[d], sh[d]) for d in common])
gaps = [ov[d] - sh[d] for d in common]
check("[2] over sleeves: 0.0543 at d 0, 0.0462 at d 0.15, every gap 0.044..0.055",
      close(gaps[0], 0.0543, 2e-4) and close(ov[0.15] - sh[0.15], 0.0462, 2e-4)
      and all(0.044 <= g <= 0.055 for g in gaps), gaps)
check("[2] same ring distances and count", [d for d, _c in plain] == [d for d, _c in over])

# [3]
kp = gt.outline(JACKET, K)["knots"]
ko = gt.outline(JACKET, K, over_sleeves=True)["knots"]
check("[3] knots 2 cm from the hem 1.0537 (knot 18 at 1.4137)", close(1.5237 - kp[-1][0] + kp[18][0], 1.4137), kp[18])
check("[3] without: every knot 1.10", all(close(c, 1.10) for _h, c in kp), kp)
check("[3] knots 0..14 unchanged", [c for _h, c in ko[:15]] == [c for _h, c in kp[:15]], ko[:15])
check("[3] knot 15 1.1374", close(ko[15][1], 1.1374), ko[15])
check("[3] knot 17 1.2174", close(ko[17][1], 1.2174), ko[17])
check("[3] knot 18 1.22 and the top 1.22", close(ko[18][1], 1.22) and close(ko[-1][1], 1.22), (ko[18], ko[-1]))
check("[3] same knot heights", [h for h, _c in kp] == [h for h, _c in ko])
sp_old = gt.panel_spec(JACKET, K)
sp_no = gt.panel_spec(JACKET, K, over_sleeves=False)
sp_over = gt.panel_spec(JACKET, K, over_sleeves=True)
check("[3] panel_spec over sleeves carries layer_ease 0.12", sp_over.get("layer_ease") == 0.12)
check("[3] panel_spec not over sleeves = the old call, no layer_ease", sp_no == sp_old and "layer_ease" not in sp_no)


# [4]
def piece(name, slots, mode, params=None):
    p = {"slots": list(slots), "covers": [], "partially_covers": [], "mesh_mode": mode}
    if params:
        p["template"] = {"params": params}
    return {"id": name, "name": name, "category": "outfit_piece", "outfit_piece": p}


ITEMS = {"JT": piece("JT", ["outer"], "template", dict(JACKET)),
         "TS": piece("TS", ["top"], "template", dict(SHIRT)),
         "TN": piece("TN", ["top"], "template", dict(v(kind="top", sleeves="none"))),
         "OT": piece("OT", ["top"], "own_mesh")}
inventory.get_item = lambda item_id, *a, **k: ITEMS.get(str(item_id))
body_slots.piece_slots_for_character = lambda *a, **k: list(inventory.VALID_PIECE_SLOTS)
check("[4] JT over TS -> True", gt.over_sleeved_layer("JT", "jacket", ["JT", "TS"]) is True)
check("[4] JT over TN -> False", gt.over_sleeved_layer("JT", "jacket", ["JT", "TN"]) is False)
check("[4] JT over OT -> False", gt.over_sleeved_layer("JT", "jacket", ["JT", "OT"]) is False)
check("[4] TS over nothing -> False", gt.over_sleeved_layer("TS", "top", ["TS"]) is False)
pic = _SCRATCH / "pic.png"
pic.write_bytes(b"picture")
gt.texture_sources = lambda c, i: {"front": str(pic), "back": str(pic), "source": "cutout"}
gt.own_colliders = lambda *a, **k: []
from app.core import bust_shaping  # noqa: E402
bust_shaping.key_tokens = lambda *a, **k: []


def key(lower):
    return gt.key_for("c", "JT", base_sha="base", lower=lower)[0]


k_ts, k_tn = key(["TS"]), key(["TN"])
saved = gt.layer_ease
gt.layer_ease = lambda params, over: 0.0
k_ts0, k_tn0 = key(["TS"]), key(["TN"])
gt.layer_ease = saved
check("[4] JT over TS: the key re-drapes (token)", k_ts and k_ts != k_ts0, (k_ts, k_ts0))
check("[4] JT over TN: the key is unchanged", k_tn and k_tn == k_tn0, (k_tn, k_tn0))
check("[4] TEMPLATE_VERSION not bumped (9)", gt.TEMPLATE_VERSION == 9, gt.TEMPLATE_VERSION)

# [5]
from app.blender import runner as _runner  # noqa: E402


def spec_sent(**kw):
    sent = []

    def fake(script, **k):
        sent.append(k["params"]["spec"])
        return {"ok": True, "outcome": "ok", "error": "", "log_tail": "", "outputs": {"glb": "/x.glb"},
                "data": {"script_wall_s": 5.0, "render_wall_s": 0.0,
                         "drape": {"cpu_s": 1.0, "pin_drift_mm": 0.0, "stretch_max": 1.1,
                                   "stretch_at": {"over_1_3": 0}},
                         "draped": {"rest": {"poke_share": 0.0}}}}
    saved_ = (_runner.run, gt.measure_body, gt.prepare_view)
    _runner.run = fake
    gt.measure_body = lambda glb: dict(K)
    gt.prepare_view = lambda src, dst, garment_only=True: {}
    tmp = Path(tempfile.mkdtemp(prefix="smoke-jacket-run-"))
    try:
        (tmp / "b.glb").write_bytes(b"glb")
        gt.run_drape(tmp / "b.glb", dict(JACKET), {"front": "f", "back": "b"}, item_id="JT", out_dir=tmp / "o", **kw)
    finally:
        _runner.run, gt.measure_body, gt.prepare_view = saved_
        shutil.rmtree(tmp, ignore_errors=True)
    return sent


s_over, s_plain = spec_sent(over_sleeves=True), spec_sent()
check("[5] run_drape over sleeves -> spec layer_ease 0.12", s_over and s_over[0].get("layer_ease") == 0.12)
check("[5] run_drape plain -> no layer_ease", s_plain and "layer_ease" not in s_plain[0])
src = (ROOT / "app/core/garment_template.py").read_text()
body = src[src.index("def _build_drape("):src.index("def ", src.index("def _build_drape(") + 10)]
check("[5] _build_drape passes over_sleeves and records layer_ease",
      "over = over_sleeved_layer(item_id, params[\"kind\"], lower)" in body and "over_sleeves=over" in body
      and '"layer_ease": JACKET_SLEEVE_EASE' in body)

shutil.rmtree(_SCRATCH, ignore_errors=True)
print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
