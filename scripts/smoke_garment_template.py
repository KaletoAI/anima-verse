"""Smoke: garment templates P1 + P2 (Rulings A138, A142) — parameters, panels, cache key, figure mode, judge.

Usage:
    ./.venv/bin/python scripts/smoke_garment_template.py

No server, no world DB (throwaway ``paths.init``), no Blender, no LLM: every item lookup, the LLM call and the storage folder are
replaced in-process (the LLM answer is a fixed JSON string). The Blender drape itself is proven by the A138
run sheet (``~/claude-out/a138/``), not here.

Expected numbers, derived by hand from ``app/core/garment_template.py``:

[1] validate_params: an empty dict gives the PARAM_SPEC defaults (skirt, 0.5 m, flare 0.3, natural, no slit,
    0 m, strapless, no sleeves, sleeve fit 0.3, fit 0.3, crew, depth 0, closed, no collar, medium) and NO error. ``length_m`` 2.0 is clamped to the range top 1.2 and reported;
    ``kind`` "cape" is reported and becomes the default "skirt"; ``slit`` "left" with ``slit_m`` 0 takes
    min(0.25, 0.4 * length) — for length 0.5: min(0.25, 0.2) = 0.2; ``slit_m`` 0.6 on a 0.5 m piece is capped at
    0.8 * 0.5 = 0.4. ``slit`` "none" forces ``slit_m`` 0.
[2] parse_answer: a ```json fenced object, a bare object after prose, and a <think> block before it all parse;
    text without braces raises ValueError.
[3] outline / panel_spec with a hand-made body: waist_y 1.00, waist_c 0.70, hip_y 0.85, hip_c 0.95,
    band_y 1.275, band_c 0.90 (EASE_M 0.02):
    * skirt natural, flare 0, length 0.5: waist circumference 0.70 + 0.02 = 0.72; hem = max(0.95 * 1.04, 0.72)
      * (1 + 1.5 * 0) = 0.988. Panel grids are HALF the circumference: top row width 0.36, hem row 0.494.
      rows = round(0.5 / 0.015) + 1 = round(33.33) + 1 = 34; row_y[0] = 1.00, row_y[-1] = 0.50.
    * flare 0.4: hem 0.988 * 1.6 = 1.5808.
    * waist "high": line 1.03, frac (1.03-0.85)/(0.15) = 1.2 clamped to 1 → 0.72; "low": line 0.925,
      frac 0.5 → 0.95 + (0.70-0.95) * 0.5 + 0.02 = 0.845.
    * dress, length 0.5: bodice 1.275 - 1.00 = 0.275, top knot (0.775, 0.90 + 0.02 = 0.92), top_y 1.275,
      rows = round(0.775 / 0.015) + 1 = round(51.67) + 1 = 53.
    * kind "trousers" raises ValueError (not built).
[4] tsig: the same inputs give the same 12-hex key; each of params / base sha / texture sha / lower layers
    changes it; the order of the lower layers does not.
[5] drape_state in a temp folder: no parameters → blocked with NEEDS_PARAMS; kind "trousers" → blocked with
    KIND_NOT_BUILT; parameters + picture → missing (NOT_DRAPED); a failure record of that key → failed with
    DRAPE_FAILED; a GLB + accepted record → ready.
[6] judge_build: wall 60.0 passes (gate is <= 60 s, Ruling A138), 60.01 fails; drape CPU 126 s is reported and
    NOT a gate; poke at rest is a gate, at sit not.
[7] prepare_view: a 40 x 40 picture, white background, a blue 20 x 20 block (rows 5-24, cols 10-29), under it a
    4 x 20 skin strip (rows 25-26 lit (224, 172, 140), rows 27-28 shaded (70, 40, 30)) and a blue 2 x 2 island at
    rows 35-36, cols 2-3: the white border is cut (alpha 0), blue kept; the skin strip is 80 / 484 = 16.5 % of the
    opaque pixels (< 50 %) and is cut — the shaded rows too: Y 0.299·70 + 0.587·40 + 0.114·30 = 47.1 ≥ 25,
    Cr 128 + 35 − 16.75 − 2.44 = 143.8 in [133, 180], Cb 128 − 11.81 − 13.25 + 15 = 117.9 in [77, 127] (the A138 RGB rule
    needed r > 95); a yellow pixel (230, 200, 60): Cb 128 − 38.8 − 66.3 + 30 = 52.9 < 77 is NOT skin. Skin grown by 2
    px takes block rows 23-24; the island is not the largest region and goes; the rim loses one pixel: (5, 10) cut,
    (6, 11) kept. With garment_only False (a cut-out view) nothing of the strip is cut and skin_dropped is 0.
[8] suggest_params with the stub LLM: ONE call, task "garment_template_params", the item picture attached,
    the fenced JSON parsed and validated.
[9] figure: worn_sets puts a template piece into ``template`` AND ``own`` (kind clothing), never into
    in_body/painted; Figure.state_of answers "template"; as_dict carries "template" only when one is worn and
    from_dict reads it back.
[11] texture_sources (Ruling A141): no cut-out → the item picture for both sides; only a front cut-out → it serves
    both sides; front + back → each its own; source "cutout" whenever one exists.
[10] the vendored pygarment imports from app.third_party and builds a 4-edge panel (no PyPI package).
[12] Ruling A142 tops / jackets / dresses with a bodice, on a hand-made body: shoulder_y 1.37, shoulder_w 0.39,
     neck_c 0.33, arm_len 0.50, arm_c [[0.05, 0.34], [0.25, 0.26], [0.5, 0.24], [0.97, 0.17]], torso
     [[0.8, 0.92], [1.0, 0.70], [1.2, 0.80], [1.36, 1.0]] (+ the [3] body):
    * validate_params: kind "top" forces shoulders "covered" and resets the skirt fields (flare back to 0.3, slit
      "none"); a strapless dress drops its sleeves to "none"; a skirt resets sleeves / neckline to their defaults.
    * top, length 0.55, fit 0.3: top_y = 1.37 + 0.045 = 1.415, hem_y 0.865; ease 1 + 0.03 + 0.17 * 0.3 = 1.081;
      the hem knot: torso girth at 0.865 = 0.92 - 0.22 * 0.065 / 0.2 = 0.8485 -> 0.8485 * 1.081 + 0.02 = 0.93723;
      the top knot (0.55, 1.0 * 1.081 + 0.02 = 1.101). A jacket adds 0.05 ease: top knot 1.0 * 1.131 + 0.02 = 1.151.
    * bodice_spec, short sleeves, sleeve fit 0.3: length 0.3 * 0.50 = 0.15; ease 1 + 0.05 + 0.4 * 0.3 = 1.17; ring 0
      (share 0, left of the samples -> 0.34) 0.34 * 1.17 + 0.02 = 0.4178; rings every 2.5 cm 0 .. 0.15 = 7; the last
      (share 0.3: 0.26 - 0.02 * 0.05 / 0.25 = 0.256) 0.256 * 1.17 + 0.02 = 0.31952. neck_r = 0.33 / 2pi + 0.012 =
      0.06452; pin_half_x 0.75 * 0.195 = 0.14625; crew depth 0.01 below front_y = shoulder_y 1.37 (NECK_DEPTH, Ruling
      A144). Boat: neck_r = 0.62 * 0.195 = 0.1209. Lapel: neckline "v", depth below the notch max(0.12, 1.37 - 1.275 +
      0.04 = 0.135) = 0.135, front open. No sleeves -> sleeve None.
    * shape_groups: a top with hem 0.865 above hip_y 0.85 -> the two arm groups (arms_down, arms_forward, arms_up),
      no leg group; length 0.6 (hem 0.815 < 0.85) adds the leg group with "sit" only; a strapless dress -> legs
      (sit, kneel) only; a covered dress with sleeves -> legs + both arms with "arms_down" only.
    * shape_targets folds sides: ["sit", "arms_down_l", "arms_down_r"] -> ["sit", "arms_down"].
    * judge_build takes the sheet renders out of the wall: wall 63 with render 4 -> 59 passes.
[13] Ruling A142 layering: a jacket worn with a template top lists the top as its collider (collider_pieces), the
     top lists nothing (rank 1 < 2 only one way); an own-mesh piece is no collider. The jacket's key changes when
     the TOP's parameters change; the top's key does not change with the jacket's.
"""
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Throwaway storage + instance before any world import (nothing here opens them; the store is redirected).
_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-template-paths-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402
TEXTURE_SOURCES = gt.texture_sources   # [5] stubs it; [11] checks the real one

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def close(a, b, tol=1e-4):
    return abs(float(a) - float(b)) <= tol


# [1]
p, e = gt.validate_params({})
check("[1] defaults, no error", e == [] and p == {"kind": "skirt", "length_m": 0.5, "flare": 0.3,
                                                  "waist_height": "natural", "slit": "none", "slit_m": 0.0,
                                                  "shoulders": "strapless", "sleeves": "none", "sleeve_fit": 0.3,
                                                  "fit": 0.3, "neckline": "crew", "neck_depth_m": 0.0,
                                                  "front": "closed", "collar": "none", "fabric": "medium"}, str((p, e)))
p, e = gt.validate_params({"length_m": 2.0, "kind": "cape"})
check("[1] length clamped to 1.2 and reported", p["length_m"] == 1.2 and any("length_m" in x for x in e))
check("[1] unknown kind reported, default skirt", p["kind"] == "skirt" and any("kind" in x for x in e))
p, _ = gt.validate_params({"slit": "left", "length_m": 0.5})
check("[1] slit default depth 0.2", close(p["slit_m"], 0.2), p["slit_m"])
p, _ = gt.validate_params({"slit": "left", "slit_m": 0.6, "length_m": 0.5})
check("[1] slit depth capped at 0.4", close(p["slit_m"], 0.4), p["slit_m"])
p, _ = gt.validate_params({"slit": "none", "slit_m": 0.3})
check("[1] no slit -> 0", p["slit_m"] == 0.0)
check("[1] non-dict is an error", gt.validate_params("x")[1] != [])

# [2]
check("[2] fenced", gt.parse_answer('Here:\n```json\n{"kind": "dress"}\n```')["kind"] == "dress")
check("[2] bare after prose", gt.parse_answer('sure {"kind": "skirt", "flare": 0.2} done')["flare"] == 0.2)
check("[2] think block", gt.parse_answer('<think>{"kind":"top"}</think>{"kind": "skirt"}')["kind"] == "skirt")
try:
    gt.parse_answer("no json here")
    check("[2] no JSON raises", False)
except ValueError:
    check("[2] no JSON raises", True)

# [3]
M = {"height": 1.7, "floor_y": 0.0, "waist_y": 1.0, "waist_c": 0.70, "hip_y": 0.85, "hip_c": 0.95,
     "band_y": 1.275, "band_c": 0.90}
skirt, _ = gt.validate_params({"kind": "skirt", "length_m": 0.5, "flare": 0.0})
o = gt.outline(skirt, M)
check("[3] skirt waist 0.72 / hem 0.988", close(o["knots"][1][1], 0.72) and close(o["knots"][0][1], 0.988), o)
spec = gt.panel_spec(skirt, M)
g = spec["panels"][0]["grid_m"]
check("[3] rows 34", spec["rows"] == 34, spec["rows"])
check("[3] top row width 0.36", close(g[0][-1][0] - g[0][0][0], 0.36), g[0][-1][0] - g[0][0][0])
check("[3] hem row width 0.494", close(g[-1][-1][0] - g[-1][0][0], 0.494), g[-1][-1][0] - g[-1][0][0])
check("[3] row_y 1.00 .. 0.50", close(spec["row_y"][0], 1.0) and close(spec["row_y"][-1], 0.5))
check("[3] pygarment spec of both panels", set(spec["pygarment"]["panels"]) == {"front", "back"})
o = gt.outline(gt.validate_params({"flare": 0.4, "length_m": 0.5})[0], M)
check("[3] flare 0.4 hem 1.5808", close(o["knots"][0][1], 1.5808), o["knots"][0][1])
o = gt.outline(gt.validate_params({"waist_height": "high"})[0], M)
check("[3] high waist 0.72", close(o["knots"][1][1], 0.72))
o = gt.outline(gt.validate_params({"waist_height": "low"})[0], M)
check("[3] low waist 0.845", close(o["knots"][1][1], 0.845), o["knots"][1][1])
dress, _ = gt.validate_params({"kind": "dress", "length_m": 0.5})
o = gt.outline(dress, M)
check("[3] dress top knot (0.775, 0.92), top_y 1.275",
      close(o["knots"][-1][0], 0.775) and close(o["knots"][-1][1], 0.92) and close(o["top_y"], 1.275), o)
check("[3] dress rows 53", gt.panel_spec(dress, M)["rows"] == 53)
try:
    gt.panel_spec(gt.validate_params({"kind": "trousers"})[0], M)
    check("[3] trousers not built raises", False)
except ValueError:
    check("[3] trousers not built raises", True)

# [4]
k = dict(base_sha="a" * 64, texture_sha="t1", lower=["b", "a"])
s0 = gt.tsig(skirt, **k)
check("[4] stable 12 hex", s0 == gt.tsig(skirt, **k) and len(s0) == 12)
check("[4] lower order irrelevant", s0 == gt.tsig(skirt, base_sha="a" * 64, texture_sha="t1", lower=["a", "b"]))
check("[4] params change it", s0 != gt.tsig(dress, **k))
check("[4] base changes it", s0 != gt.tsig(skirt, base_sha="b" * 64, texture_sha="t1", lower=["a", "b"]))
check("[4] texture changes it", s0 != gt.tsig(skirt, base_sha="a" * 64, texture_sha="t2", lower=["a", "b"]))
check("[4] lower changes it", s0 != gt.tsig(skirt, base_sha="a" * 64, texture_sha="t1", lower=["a"]))

# [5] drape_state against a temp store
tmp = Path(tempfile.mkdtemp(prefix="smoke-template-"))
try:
    pic = tmp / "pic.png"
    from PIL import Image
    Image.new("RGB", (8, 8), (10, 20, 200)).save(pic)
    items = {}
    gt.templates_dir = lambda name: tmp / "templates"
    gt.texture_sources = lambda name, item_id: {"front": str(pic), "back": str(pic), "source": "item_image"}
    piece = {"category": "outfit_piece", "outfit_piece": {"slots": ["bottom"], "mesh_mode": "template"}}
    st = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] no params -> blocked NEEDS_PARAMS", st["state"] == "blocked" and st["reason"] == gt.NEEDS_PARAMS)
    trousers = json.loads(json.dumps(piece))
    trousers["outfit_piece"]["template"] = {"params": {"kind": "trousers"}}
    st = gt.drape_state("K", "i1", base_sha="s", lower=[], item=trousers)
    check("[5] trousers -> KIND_NOT_BUILT", st["state"] == "blocked" and "trousers" in st["reason"])
    piece["outfit_piece"]["template"] = {"params": {"kind": "skirt", "length_m": 0.45}}
    st = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] missing -> NOT_DRAPED", st["state"] == "missing" and st["reason"] == gt.NOT_DRAPED)
    from app.core import garment_store
    garment_store.write_record = lambda path, rec: (Path(path).parent.mkdir(parents=True, exist_ok=True),
                                                    Path(path).write_text(json.dumps(rec)))
    garment_store.write_record(gt.failed_path("K", "i1", st["tsig"]), {"error": "stretch_max 2.1"})
    st2 = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] failed -> DRAPE_FAILED", st2["state"] == "failed" and "stretch_max 2.1" in st2["reason"])
    glb = gt.drape_path("K", "i1", st["tsig"])
    glb.write_bytes(b"glb")
    garment_store.write_record(glb.with_suffix(".json"), {"accepted": True})
    check("[5] ready", gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)["state"] == "ready")
    check("[5] clear_failure removes 1", gt.clear_failure("K", "i1") == 1)

    # [7]
    import numpy as np
    img = np.full((40, 40, 3), 255, np.uint8)
    img[5:25, 10:30] = (20, 40, 200)
    img[25:27, 10:30] = (224, 172, 140)
    img[27:29, 10:30] = (70, 40, 30)
    img[6, 11] = (230, 200, 60)
    img[35:37, 2:4] = (20, 40, 200)
    src, dst = tmp / "v.png", tmp / "v_out.png"
    Image.fromarray(img).save(src)
    info = gt.prepare_view(str(src), dst)
    a = np.asarray(Image.open(dst))[..., 3]
    check("[7] border cut, blue kept", a[0, 0] == 0 and a[15, 20] == 255)
    check("[7] skin strip cut (16.5 %)", a[26, 20] == 0 and close(info["skin_dropped"], 80 / 484, 1e-3), info)
    check("[7] yellow kept", a[6, 11] == 255)
    check("[7] shaded skin cut", a[28, 20] == 0)
    check("[7] stray island cut", a[35, 2] == 0)
    check("[7] rim eroded", a[5, 10] == 0 and a[6, 11] == 255)
    info_cut = gt.prepare_view(str(src), dst, garment_only=False)
    a = np.asarray(Image.open(dst))[..., 3]
    check("[7] a cut-out keeps its pixels", a[26, 20] == 255 and a[28, 20] == 255 and info_cut["skin_dropped"] == 0.0)

    # [8] suggest_params with a stub LLM (no outbound request)
    from app.core import llm_router
    from app.models import inventory
    calls = []

    def stub(**kw):
        calls.append(kw)
        return types.SimpleNamespace(content='```json\n{"kind": "dress", "length_m": 0.55, "flare": 0.5, '
                                             '"waist_height": "natural", "fabric": "flowing"}\n```')
    llm_router.llm_call = stub
    inventory.get_item = lambda iid: {"id": iid, "name": "Sun dress", "category": "outfit_piece",
                                      "prompt_fragment": "blue sun dress", "outfit_piece": {"slots": ["top", "bottom"]}}
    inventory.get_item_image_path = lambda iid: str(pic)
    out = gt.suggest_params("i9", character_name="K")
    check("[8] one call, task + picture", len(calls) == 1 and calls[0]["task"] == gt.TASK
          and calls[0]["image_path"] == str(pic))
    check("[8] parsed + validated", out["params"]["kind"] == "dress" and out["params"]["fabric"] == "flowing"
          and out["errors"] == [])

    # [9] figure plumbing
    from app.core import base_body, figure, garment_hair, garment_set, outfit_options
    garment_set.worn_garments = lambda *a, **k: []
    base_body.is_base_pipeline = lambda *a, **k: True
    garment_hair.hair_mode = lambda *a, **k: "body"
    garment_hair.shape_hair = lambda *a, **k: ""
    garment_hair.hair_style_id = lambda *a, **k: ""
    the_items = {"sk": {"category": "outfit_piece", "outfit_piece": {"slots": ["bottom"], "mesh_mode": "template"}},
                 "tp": {"category": "outfit_piece", "outfit_piece": {"slots": ["top"]}}}
    inventory.get_item = lambda iid: the_items.get(iid)
    sets = figure.worn_sets("K", pieces={"bottom": "sk", "top": "tp"}, profile={}, piece_state={})
    check("[9] template in template + own", sets.template == ("sk",) and sets.own.get("sk") == "clothing")
    check("[9] not in body/painted", "sk" not in sets.in_body and "sk" not in sets.painted and "tp" in sets.in_body)
    fig = figure.Figure(signature="s", bsig="b", shape="b", texture="", in_body=(), painted=(), own=("sk",),
                        template=("sk",))
    check("[9] state_of template", fig.state_of("sk") == garment_set.TEMPLATE)
    check("[9] as_dict roundtrip", figure.Figure.from_dict(fig.as_dict()).template == ("sk",))
    plain = figure.Figure(signature="s", bsig="b", shape="b", texture="", in_body=(), painted=(), own=())
    check("[9] no template key without one", "template" not in plain.as_dict())
    check("[9] MESH_MODES has template", garment_set.TEMPLATE in garment_set.MESH_MODES)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(_SCRATCH, ignore_errors=True)

# [6]
rows = gt.judge_build({"wall_total_s": 60.0, "drape": {"cpu_s": 126.0}, "draped": {"rest": {"poke_share": 0.0},
                                                                                 "sit": {"poke_share": 0.02}}})
by = {r["check"]: r for r in rows}
check("[6] wall 60.0 passes", by["build_wall_s"]["ok"])
check("[6] wall 60.01 fails", not {r["check"]: r for r in gt.judge_build({"wall_total_s": 60.01})}["build_wall_s"]["ok"])
check("[6] CPU reported, no gate", not by["drape_cpu_s"]["ok"] and not by["drape_cpu_s"]["gate"])
check("[6] rest poke gates, sit not", by["poke_share[rest]"]["gate"] and not by["poke_share[sit]"]["gate"])

# [11] texture_sources: cut-outs whenever any exists, the item picture only without one
from app.core import garment_store  # noqa: E402
from app.models import inventory as _inv  # noqa: E402
store = Path(tempfile.mkdtemp(prefix="smoke-template-src-"))
(store / "images").mkdir()
garment_store.garments_dir = lambda name: store
_inv.get_item_image_path = lambda iid: "/pictures/item.png"
check("[11] no cut-out → item picture", TEXTURE_SOURCES("K", "i9") == {
    "front": "/pictures/item.png", "back": "/pictures/item.png", "source": "item_image"})
front = store / "images" / "i9_abc_cutout_front.png"
front.write_bytes(b"x")
check("[11] front only → both sides from it", TEXTURE_SOURCES("K", "i9") == {
    "front": str(front), "back": str(front), "source": "cutout"})
back = store / "images" / "i9_abc_cutout_back.png"
back.write_bytes(b"x")
check("[11] both → each side its own", TEXTURE_SOURCES("K", "i9") == {
    "front": str(front), "back": str(back), "source": "cutout"})
shutil.rmtree(store, ignore_errors=True)

# [10]
from app.third_party.pygarment.garmentcode.edge import Edge  # noqa: E402
from app.third_party.pygarment.garmentcode.panel import Panel  # noqa: E402
pn = Panel("p")
for a, b in (([0, 0], [10, 0]), ([10, 0], [10, 10]), ([10, 10], [0, 10]), ([0, 10], [0, 0])):
    pn.edges.append(Edge(a, b))
check("[10] vendored pygarment panel assembles", "p" in pn.assembly().pattern["panels"])

# [12]
MU = dict(M, shoulder_y=1.37, shoulder_w=0.39, neck_y=1.42, neck_c=0.33, arm_len=0.50,
          arm_c=[[0.05, 0.34], [0.25, 0.26], [0.5, 0.24], [0.97, 0.17]],
          torso=[[0.8, 0.92], [1.0, 0.70], [1.2, 0.80], [1.36, 1.0]], joints={})
top, e = gt.validate_params({"kind": "top", "length_m": 0.55, "flare": 0.9, "slit": "left", "sleeves": "short"})
check("[12] top: covered, skirt fields reset", e == [] and top["shoulders"] == "covered" and top["flare"] == 0.3
      and top["slit"] == "none", top)
d0, _ = gt.validate_params({"kind": "dress", "sleeves": "long"})
check("[12] strapless dress drops sleeves", d0["shoulders"] == "strapless" and d0["sleeves"] == "none")
sk, _ = gt.validate_params({"kind": "skirt", "sleeves": "long", "neckline": "v"})
check("[12] skirt resets bodice fields", sk["sleeves"] == "none" and sk["neckline"] == "crew")
o = gt.outline(top, MU)
check("[12] top_y 1.415, length 0.55", close(o["top_y"], 1.415) and close(o["knots"][-1][0], 0.55), o["top_y"])
check("[12] hem knot 0.93723", close(o["knots"][0][1], 0.93723), o["knots"][0])
check("[12] top knot 1.101", close(o["knots"][-1][1], 1.101), o["knots"][-1])
jk, _ = gt.validate_params({"kind": "jacket", "length_m": 0.55, "sleeves": "short"})
check("[12] jacket top knot 1.151", close(gt.outline(jk, MU)["knots"][-1][1], 1.151))
b = gt.bodice_spec(top, MU)
sl = b["sleeve"]
check("[12] sleeve 0.15 m, 7 rings", close(sl["len_m"], 0.15) and len(sl["rings"]) == 7, sl)
check("[12] ring 0 0.4178, last 0.31952", close(sl["rings"][0][1], 0.4178) and close(sl["rings"][-1][1], 0.3195),
      sl["rings"])
check("[12] neck_r 0.06452, pin 0.14625, crew 0.01 under front_y 1.37", close(b["neck_r"], 0.0645)
      and close(b["pin_half_x"], 0.1462) and close(b["depth_m"], 0.01) and close(b["front_y"], 1.37), b)
boat = gt.bodice_spec(gt.validate_params({"kind": "top", "neckline": "boat"})[0], MU)
check("[12] boat neck 0.1209", close(boat["neck_r"], 0.1209), boat["neck_r"])
lap = gt.bodice_spec(gt.validate_params({"kind": "jacket", "collar": "lapel"})[0], MU)
check("[12] lapel = open v 0.135", lap["neckline"] == "v" and close(lap["depth_m"], 0.135) and lap["front_open"], lap)
check("[12] no sleeves -> None", gt.bodice_spec(gt.validate_params({"kind": "top"})[0], MU)["sleeve"] is None)
spec_t = gt.panel_spec(top, MU)
check("[12] panel_spec carries bodice + sleeve panel", "bodice" in spec_t
      and set(spec_t["pygarment"]["panels"]) == {"front", "back", "sleeve"})
names = lambda gs: [(g["name"], tuple(g["poses"])) for g in gs]  # noqa: E731
check("[12] top groups: arms only", names(gt.shape_groups(top)) == [
    ("arm_l", gt.ARM_SHAPE_POSES), ("arm_r", gt.ARM_SHAPE_POSES)])
args = gt.build_args(gt.validate_params({"kind": "top", "length_m": 0.6})[0],
                     gt.panel_spec(gt.validate_params({"kind": "top", "length_m": 0.6})[0], MU), item_id="x")
check("[12] long top adds sit", [g["name"] for g in args["shape_groups"]] == ["legs", "arm_l", "arm_r"]
      and args["shape_groups"][0]["poses"] == ["sit"])
args = gt.build_args(top, spec_t, item_id="x")
check("[12] hip-length top: no legs", [g["name"] for g in args["shape_groups"]] == ["arm_l", "arm_r"])
check("[12] strapless dress: legs", names(gt.shape_groups(d0)) == [("legs", ("sit", "kneel"))])
check("[12] strapless dress: leg shapes at the builder default (no frames key)", "frames" not in gt.shape_groups(d0)[0])
dc, _ = gt.validate_params({"kind": "dress", "shoulders": "covered", "sleeves": "short"})
check("[12] covered dress: legs + arms_down", names(gt.shape_groups(dc)) == [
    ("legs", ("sit", "kneel")), ("arm_l", ("arms_down",)), ("arm_r", ("arms_down",))])
check("[12] covered dress: leg shapes 20 frames (DRESS_LEG_FRAMES)", gt.shape_groups(dc)[0]["frames"] == 20)
check("[12] shape_targets folds sides", gt.shape_targets({"targets": ["sit", "arms_down_l", "arms_down_r"]})
      == ["sit", "arms_down"])
check("[12] renders out of the wall", {r["check"]: r for r in gt.judge_build(
    {"wall_total_s": 63.0, "render_wall_s": 4.0})}["build_wall_s"]["ok"])

# [13]
from app.models import inventory as _inv2  # noqa: E402
lay = {"tp": {"category": "outfit_piece", "outfit_piece": {"slots": ["top"], "mesh_mode": "template",
                                                            "template": {"params": {"kind": "top"}}}},
       "jk": {"category": "outfit_piece", "outfit_piece": {"slots": ["outer"], "mesh_mode": "template",
                                                            "template": {"params": {"kind": "jacket"}}}},
       "bt": {"category": "outfit_piece", "outfit_piece": {"slots": ["feet"], "mesh_mode": "own_mesh"}}}
_inv2.get_item = lambda iid: lay.get(iid)
gt.texture_sources = lambda name, item_id: {"front": "/x.png", "back": "/x.png", "source": "item_image"}
check("[13] jacket over the top", [i for i, _ in gt.collider_pieces("jk", "jacket", ["tp", "bt"])] == ["tp"])
check("[13] top over nothing", gt.collider_pieces("tp", "top", ["jk", "bt"]) == [])
kj1 = gt.key_for("K", "jk", base_sha="s", lower=["bt", "tp"], item=lay["jk"])[0]
kt1 = gt.key_for("K", "tp", base_sha="s", lower=["bt", "jk"], item=lay["tp"])[0]
lay["tp"]["outfit_piece"]["template"]["params"]["sleeves"] = "long"
kj2 = gt.key_for("K", "jk", base_sha="s", lower=["bt", "tp"], item=lay["jk"])[0]
lay["jk"]["outfit_piece"]["template"]["params"]["collar"] = "lapel"
kt2 = gt.key_for("K", "tp", base_sha="s", lower=["bt", "jk"], item=lay["tp"])[0]
kt1b = kt1
lay["tp"]["outfit_piece"]["template"]["params"]["sleeves"] = "none"
kt1b = gt.key_for("K", "tp", base_sha="s", lower=["bt", "jk"], item=lay["tp"])[0]
check("[13] top change re-keys the jacket", kj1 and kj2 and kj1 != kj2)
check("[13] jacket change keeps the top's key", kt1 == kt1b, (kt1, kt1b, kt2))

print("\n" + ("all checks passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
