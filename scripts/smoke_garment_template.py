"""Smoke: garment templates P1 (Ruling A138) — parameters, panels, cache key, figure mode, judge.

Usage:
    ./.venv/bin/python scripts/smoke_garment_template.py

No server, no world DB (throwaway ``paths.init``), no Blender, no LLM: every item lookup, the LLM call and the storage folder are
replaced in-process (the LLM answer is a fixed JSON string). The Blender drape itself is proven by the A138
run sheet (``~/claude-out/a138/``), not here.

Expected numbers, derived by hand from ``app/core/garment_template.py``:

[1] validate_params: an empty dict gives the PARAM_SPEC defaults (skirt, 0.5 m, flare 0.3, natural, no slit,
    0 m, no sleeves, medium) and NO error. ``length_m`` 2.0 is clamped to the range top 1.2 and reported;
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
    * kind "top" raises ValueError (not built in P1).
[4] tsig: the same inputs give the same 12-hex key; each of params / base sha / texture sha / lower layers
    changes it; the order of the lower layers does not.
[5] drape_state in a temp folder: no parameters → blocked with NEEDS_PARAMS; kind "trousers" → blocked with
    KIND_NOT_BUILT; parameters + picture → missing (NOT_DRAPED); a failure record of that key → failed with
    DRAPE_FAILED; a GLB + accepted record → ready.
[6] judge_build: wall 60.0 passes (gate is <= 60 s, Ruling A138), 60.01 fails; drape CPU 126 s is reported and
    NOT a gate; poke at rest is a gate, at sit not.
[7] prepare_view: a 40 x 40 picture, white background, a blue 20 x 20 block and a skin-coloured 4 x 20 strip
    under it: the white border is cut (alpha 0), blue kept; the skin strip is 80 / 480 = 16.7 % of the opaque
    pixels (< 50 %) and is cut; a yellow pixel (230, 200, 60: b * 10 = 600 < r * 3 = 690) is NOT skin.
[8] suggest_params with the stub LLM: ONE call, task "garment_template_params", the item picture attached,
    the fenced JSON parsed and validated.
[9] figure: worn_sets puts a template piece into ``template`` AND ``own`` (kind clothing), never into
    in_body/painted; Figure.state_of answers "template"; as_dict carries "template" only when one is worn and
    from_dict reads it back.
[10] the vendored pygarment imports from app.third_party and builds a 4-edge panel (no PyPI package).
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
                                                  "sleeves": "none", "fabric": "medium"}, str((p, e)))
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
    gt.panel_spec(gt.validate_params({"kind": "top"})[0], M)
    check("[3] top not built raises", False)
except ValueError:
    check("[3] top not built raises", True)

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
    img[25:29, 10:30] = (224, 172, 140)
    img[6, 11] = (230, 200, 60)
    src, dst = tmp / "v.png", tmp / "v_out.png"
    Image.fromarray(img).save(src)
    info = gt.prepare_view(str(src), dst)
    a = np.asarray(Image.open(dst))[..., 3]
    check("[7] border cut, blue kept", a[0, 0] == 0 and a[15, 20] == 255)
    check("[7] skin strip cut (16.7 %)", a[26, 20] == 0 and close(info["skin_dropped"], 80 / 480, 1e-3), info)
    check("[7] yellow kept", a[6, 11] == 255)

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

# [10]
from app.third_party.pygarment.garmentcode.edge import Edge  # noqa: E402
from app.third_party.pygarment.garmentcode.panel import Panel  # noqa: E402
pn = Panel("p")
for a, b in (([0, 0], [10, 0]), ([10, 0], [10, 10]), ([10, 10], [0, 10]), ([0, 10], [0, 0])):
    pn.edges.append(Edge(a, b))
check("[10] vendored pygarment panel assembles", "p" in pn.assembly().pattern["panels"])

print("\n" + ("all checks passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
