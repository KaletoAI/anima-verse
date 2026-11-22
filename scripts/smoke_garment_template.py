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
    * kind "trousers" (A233: built) gives the fitted spec of trousers (``fitted.kind`` "trousers", no panels).
[4] tsig: the same inputs give the same 12-hex key; each of params / base sha / texture sha / lower layers
    changes it; the order of the lower layers does not.
[5] drape_state in a temp folder: no parameters → blocked with NEEDS_PARAMS; kind "trousers" (A233: built) →
    missing (NOT_DRAPED), no longer KIND_NOT_BUILT; parameters + picture → missing (NOT_DRAPED); a failure record of that key → failed with
    DRAPE_FAILED; a GLB + accepted record → ready.
    A record that failed ONLY on ``build_wall_s`` (written while the wall still gated; its stretch row passed) is no
    refusal any more → missing (NOT_DRAPED, due again); one that failed ``build_wall_s`` AND ``stretch_max`` →
    failed, its ``failure`` (no ``outcome`` in the record, a failed gate row → "rejected") ONE line, the stretch
    sentence with value 4.768 → "4.77" and limit 1.3 → "1.3" (the wall row is no gate in the sentences: its gate
    flag was True in the old record, but only ``FAILURE_SENTENCES`` checks speak). ``estimate_s``: no judged record → CPU_ESTIMATE_S 45; the failure record of the user's case (wall_total_s
    77.34, slot_wait_s 25.0, no renders, rows present) → round(77.34 - 25.0) = round(52.34) = 52.
[6] judge_build: wall 60.0 is within the budget, 60.01 is over it — reported (ok False), NEVER a gate since
    2026-11-18; drape CPU 126 s is reported and NOT a gate; poke at rest is a gate, at sit not. The user's case
    (wall_total_s 77.34 of which slot_wait_s 25.0 was the wait for a free Blender slot, quality rows passing) →
    build_wall_s 52.34, within the budget, and no gate row fails. ``run_drape`` with a stubbed runner whose two runs
    (stretch 1.6 > RETRY_STRETCH 1.5 starts the retry; script_wall_s 10 ≤ 30 leaves room) waited 3.0 s and 4.5 s for
    a slot → ``data["slot_wait_s"]`` 7.5; the second run's stretch 1.2 and rest poke 0 pass → ok True, outcome "ok".
    ``failure_info`` (the plain sentences, owner 2026-11-18): a failed rest poke 0.0123 (limit 0.005) → the poke
    sentence with "1.23" / "0.5" (×100, per cent); a failed pin drift 7.5 (limit 5.0) → "7.5" / "5"; a run left due
    (outcome "timeout", log_tail "tail") → the LEFT_DUE["timeout"] sentence, outcome and log_tail passed through;
    rows that all pass with outcome "crashed" → NO_GLB_SENTENCE; "crashed" without rows → CRASHED_SENTENCE;
    "rejected" without rows → REJECTED_SENTENCE. Before this change none of these existed (no ``failure_info``).
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
[14] The skirt profile is never narrower than the body (``_skirt_knots``): inside the torso profile every height
     gets max(cone, body girth + EASE_M 0.02), a knot at each torso sample; the legs below keep the cone. Body T:
     waist_y 1.00, waist_c 0.70, hip_y 0.80, hip_c 0.90, band_y 1.275, band_c 0.90, torso [[0.92, 0.76],
     [0.94, 0.74], [0.96, 0.70], [0.98, 0.68], [1.00, 0.71]]. Skirt natural, flare 0, length 0.5: line 1.00, frac 1
     -> old top 0.70 + 0.02 = 0.72; hem max(0.90 * 1.04, 0.72) = 0.936 at y 0.50 (below the profile: the cone);
     cone(h) = 0.936 - 0.432 h.
     * h 0.42 (y 0.92): cone 0.75456, body 0.78 -> 0.78 (body); h 0.44: cone 0.74592, body 0.76 -> 0.76 (body);
       h 0.46: cone 0.73728, body 0.72 -> 0.73728 (cone); h 0.48: cone 0.72864, body 0.70 -> 0.72864 (cone); the
       sample at 1.00 IS the top: no knot of its own; top h 0.50: cone 0.72, body 0.71 + 0.02 = 0.73 -> 0.73.
       Six knots: (0, 0.936), (0.42, 0.78), (0.44, 0.76), (0.46, 0.73728), (0.48, 0.72864), (0.50, 0.73).
     * every knot inside the torso range (y 0.92 .. 1.00) >= _torso_girth + 0.02 (- 1e-9), and so is every panel
       row there (2 x row width at the row's own grid height; the body is linear between its samples, so is the
       cone).
     * below the lowest sample (legs) no body floor: the profile runs straight from the hem knot (0, 0.936) to
       (0.42, 0.78) — 0.936 - 0.156 h / 0.42, at h 0.20: 0.936 - 0.074286 = 0.861714 — never under the cone
       (0.936 - 0.432 * 0.20 = 0.8496); every panel row below y 0.92 >= the cone at its height.
     * panel_spec on it: rows round(0.5 / 0.015) + 1 = 34, top row width 0.73 / 2 = 0.365, hem row 0.936 / 2 =
       0.468; the pygarment front panel has 2 x 6 = 12 edges (hem, 5 right, top, 5 left).
     * a strapless dress on T: the same six skirt knots + the band knot (0.5 + 0.275 = 0.775, 0.92).
     * a covered dress on T (+ the [12] upper body): its 2 cm grid from the hem 0.50 reads the skirt profile —
       y 0.92 (h 0.42) 0.78, y 0.96 (h 0.46) round(0.73728, 4) = 0.7373, y 0.70 (h 0.20) round(0.861714, 4) = 0.8617;
       every knot up to the waist >= body + 0.02 less the 4-decimal rounding (5e-5).
     * body T0 = T with torso [[0.92, 0.70], [0.96, 0.68], [1.00, 0.68]]: body + 0.02 = 0.72 / 0.70 / 0.70 against
       the cone 0.75456 / 0.73728 / 0.72 -> cleared everywhere: exactly the two old knots [(0, 0.936), (0.5, 0.72)],
       the outline identical (==) to T0 without a torso profile, and ``_skirt_knots`` hands the covered dress the
       very same two-knot list it interpolated before.
     * Gelina regression (the user's failed low-waist skirt, numbers typed from its failure record): waist_y 1.0475,
       waist_c 0.578, hip_y 0.7925, hip_c 0.9279, torso 0.66 .. 0.92 + the 0.94 sample (0.7937); kind skirt,
       length 0.76, flare 0.68, waist low, slit left 0.6, fabric flowing. Line 1.0475 - 0.5 * 0.255 = 0.92,
       frac 0.5 -> old top 0.9279 - 0.17495 + 0.02 = 0.77295; hem max(0.965016, 0.77295) * 2.02 = 1.94933 (y 0.16,
       legs: unchanged). Top knot max(0.77295, 0.8217 + 0.02) = 0.8417. y 0.82 (h 0.66): cone 1.94933 -
       1.17638 * 0.66 / 0.76 = 0.92774 < 0.9178 + 0.02 = 0.9378 -> 0.9378; y 0.80 (h 0.64): cone 1.94933 -
       0.99063 = 0.95870 > 0.9459 -> 0.9587. Knots: hem + the 13 samples 0.66 .. 0.90 + top = 15.
[15] Pattern-piece UVs (plan 2026-11-20-template-cut-uv-texture, Task 3): ``build_args`` sends ``uv_mode`` "pattern"
     for a top, and since plan group B phases C / D for a jacket and a covered dress with sleeves too (a skirt is a
     pattern kind since step 3b, [17]). A stubbed ``_build_drape`` whose run hands back ``outputs.islands`` moves that file next to the GLB as
     ``{item}_{tsig}.islands.json`` (``islands_path``), byte-equal, and the record carries ``islands`` = {file: that
     name, sha256: the sha-256 of its bytes, px_per_cm: the payload's 19.59}; a run without an islands output (a
     grid piece) writes no file and no ``islands`` key. ``TEMPLATE_VERSION`` is 10 (the one bump of that plan).
[16] Step 3a (the fitted kinds' pattern pieces): ``build_args`` sends ``uv_mode`` "pattern" for briefs, bra, gloves,
     tights and trousers too (``PATTERN_KINDS``). ``FITTED_VERSION`` is 1 since the fitted kinds' texture choice was
     released (group A, one re-drape of every fitted drape): a fitted kind's ``tsig`` is md5 of the payload
     ``{params: keyed_params, version: TEMPLATE_VERSION, base, texture, lower: sorted(lower)}`` PLUS ``"fitted": 1`` —
     it differs from the pre-release key (the same payload without ``fitted``) in exactly that one component, for
     briefs, bra, gloves, tights and trousers alike. A top carries no ``fitted`` component: its ``tsig`` still equals
     the one ``garment_template.py`` of the base commit c926b67f0 gives (read with ``git show``; skipped with a note
     without git) — no top re-drapes.
[17] Step 3b (plan group B, Phase A — skirts and strapless tops cut into pattern pieces):
     [17.1] ``build_args`` sends ``uv_mode`` "pattern" for a skirt and a strapless top, and a skirt's
            ``waistband_m`` = ``WAISTBAND_M[waistband]`` (wide 0.03, thin 0.012); a top with a bodice gets no
            ``waistband_m`` key.
     [17.2] ``PANEL_VERSION`` is 1: a skirt's / a strapless top's ``tsig`` is md5 of the [16] payload PLUS
            ``"panels": 1`` (and differs from it); a top with sleeves carries none (its key is the base commit's,
            [16]); a fitted kind none either.
     [17.3] ``validate_params({"kind": "skirt"})`` keeps the PARAM_SPEC waistband "thin" (a saved skirt is unchanged);
            ``kind_defaults("skirt")["waistband"]`` is "wide" (a new skirt, B2); "waistband" and "texture" are skirt
            fields; ``slit`` "front_left" / "front_right" are valid (not reset to "none").
     [17.4] The builder's ``SLIT_ANGLE`` (read from the source, evaluated with ``math``): front_left - 1.5 pi =
            6 * pi / 40 = 0.471239 (+-1e-6) = 6 columns of ``split_slit``'s pi / 40 step; front_right = 1.5 pi - the same.
[18] Phases E + F (plan group B — a top's collar, placket and neckband):
     [18.1] "collar", "placket", "buttons" are top fields; a top's "lapel" becomes "stand" (B9: a lapel is a jacket's);
            a stand collar on an off-shoulder or strapped top becomes "none" (no neck ring to stand on).
     [18.2] ``placket`` / ``buttons`` are ``TEXTURE_ONLY``: a top's ``tsig`` with placket "buttons", 7 buttons equals the
            one without; ``collar`` "stand" changes it (a new geometry).
     [18.3] ``NECK_VERSION`` is 1: the cut key of a covered top cut by the neck rules (``neck_rules``: a collar or a
            placket — the B8 neckband rule, the stand-collar strip, the placket line) is md5 of the payload
            ``{params: cut_params, version, uv_pattern, base, lower}`` PLUS ``"neck": 1``; a covered top with neither
            is cut as before and carries none (``smoke_template_cut_tops_main.py``: byte-identical to 84feba712); an
            off-shoulder top and a top with straps (no neck ring: their islands are byte-identical,
            ``smoke_template_cut_tops.py`` [5]) carry none, with a placket too — their cuts and atlases stay.
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
                                                  "front": "closed", "collar": "none", "placket": "none",
                                                  "buttons": 0, "fabric": "medium",
                                                  "opacity": 0.4,
                                                  # A223: the fitted kinds' fields (at their defaults on a skirt)
                                                  "rise": "mid", "leg_cut": 0.5, "back_coverage": 1.0,
                                                  "side_width_m": 0.05, "gusset_m": 0.06, "waistband": "thin", "leg_length_m": 0.0, "sides": "fabric", "string_width_m": 0.008, "cup_style": "molded",
                                                  "cup_coverage": 0.7, "push_up": 0.0, "underband_m": 0.02,
                                                  "center_gore": "narrow", "closure": "back_hook", "straps": "thin",
                                                  "fingers": "full", "length": "wrist", "cuff": "none",
                                                  "tights_style": "tights", "feet": "closed", "garters": "none",
                                                  # A229: the off-shoulder fields (at their defaults on a skirt)
                                                  "band_m": 0.025, "band_drop_m": 0.05, "lacing": "none",
                                                  "lace_depth_m": 0.15,
                                                  # A233: the trouser fields (at their defaults on a skirt)
                                                  "trouser_length": "full", "leg_shape": "straight", "seat": "regular",
                                                  "trouser_waist": "belt", "fly": "zip", "hem": "plain",
                                                  # plan 2026-11-20-template-cut-uv-texture: the texture source
                                                  "texture": "projection",
                                                  # user test 2026-11-21: the sleeves of the texture from cut
                                                  "sleeve_print": "plain"},
      str((p, e)))
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
# A223: a strapless dress's top edge is STRAPLESS_UNDERARM_M (0.02) under the band: 0.775 - 0.02 = 0.755, 1.255
check("[3] dress top knot (0.755, 0.92), top_y 1.255",
      close(o["knots"][-1][0], 0.755) and close(o["knots"][-1][1], 0.92) and close(o["top_y"], 1.255), o)
_rows = gt.panel_spec(dress, M)["rows"]
check("[3] dress rows 51 = round(0.755 / GRID_M 0.015 = 50.3) + 1 (was 0.775 -> 52 + 1 = 53)", _rows == 51, _rows)
_tspec = gt.panel_spec(gt.validate_params({"kind": "trousers"})[0], M)
check("[3] trousers (A233) -> the fitted spec", _tspec["fitted"]["kind"] == "trousers" and _tspec["panels"] == [],
      _tspec.get("fitted"))

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
    check("[5] trousers (A233: built) -> NOT_DRAPED", st["state"] == "missing" and st["reason"] == gt.NOT_DRAPED, st)
    piece["outfit_piece"]["template"] = {"params": {"kind": "skirt", "length_m": 0.45}}
    st = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] missing -> NOT_DRAPED", st["state"] == "missing" and st["reason"] == gt.NOT_DRAPED)
    from app.core import garment_store
    garment_store.write_record = lambda path, rec: (Path(path).parent.mkdir(parents=True, exist_ok=True),
                                                    Path(path).write_text(json.dumps(rec)))
    garment_store.write_record(gt.failed_path("K", "i1", st["tsig"]), {"error": "stretch_max 2.1"})
    st2 = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] failed -> DRAPE_FAILED", st2["state"] == "failed" and "stretch_max 2.1" in st2["reason"])
    check("[5] estimate without a judged record -> 45", gt.estimate_s("K", "i1") == gt.CPU_ESTIMATE_S == 45)
    wall_row = {"check": "build_wall_s", "value": 77.34, "limit": 60.0, "ok": False, "gate": True}
    stretch_ok = {"check": "stretch_max", "value": 1.1, "limit": 1.3, "ok": True, "gate": True}
    garment_store.write_record(gt.failed_path("K", "i1", st["tsig"]), {
        "error": "build_wall_s 77.34 (limit 60.0)", "outcome": "rejected", "rows": [wall_row, stretch_ok],
        "metrics": {"wall_total_s": 77.34, "slot_wait_s": 25.0, "render_wall_s": 0.0}})
    st3 = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] failed only on the wall -> due again", st3["state"] == "missing" and st3["reason"] == gt.NOT_DRAPED,
          st3["state"])
    check("[5] estimate from the judged record -> 52", gt.estimate_s("K", "i1") == 52, gt.estimate_s("K", "i1"))
    garment_store.write_record(gt.failed_path("K", "i1", st["tsig"]), {
        "error": "x", "rows": [wall_row, {**stretch_ok, "value": 4.768, "ok": False}]})
    st4 = gt.drape_state("K", "i1", base_sha="s", lower=[], item=piece)
    check("[5] wall + stretch -> still failed", st4["state"] == "failed")
    fl = st4.get("failure") or {}
    check("[5] its failure: rejected, one stretch sentence 4.77 / 1.3",
          fl.get("outcome") == "rejected" and len(fl.get("lines") or []) == 1
          and fl["lines"][0] == {"text": gt.FAILURE_SENTENCES["stretch_max"],
                                 "values": {"value": "4.77", "limit": "1.3"}} and len(fl.get("rows") or []) == 2, fl)
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
    info = gt.prepare_view(str(src), dst, matte=None)
    a = np.asarray(Image.open(dst))[..., 3]
    check("[7] border cut, blue kept", a[0, 0] == 0 and a[15, 20] == 255)
    # A230: the 2 x 2 island (4 px < 5 % of the 480 px piece) goes with the stray components before the skin
    # count: 80 skin px / 480 (was 80 / 484)
    check("[7] skin strip cut (16.7 %)", a[26, 20] == 0 and close(info["skin_dropped"], 80 / 480, 1e-3), info)
    check("[7] yellow kept", a[6, 11] == 255)
    check("[7] shaded skin cut", a[28, 20] == 0)
    check("[7] stray island cut", a[35, 2] == 0)
    check("[7] rim eroded", a[5, 10] == 0 and a[6, 11] == 255)
    info_cut = gt.prepare_view(str(src), dst, garment_only=False, matte=None)
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
    check("[9] not in body", "sk" not in sets.in_body and "tp" in sets.in_body)
    fig = figure.Figure(signature="s", bsig="b", shape="b", texture="", in_body=(), own=("sk",),
                        template=("sk",))
    check("[9] state_of template", fig.state_of("sk") == garment_set.TEMPLATE)
    check("[9] as_dict roundtrip", figure.Figure.from_dict(fig.as_dict()).template == ("sk",))
    plain = figure.Figure(signature="s", bsig="b", shape="b", texture="", in_body=(), own=())
    check("[9] no template key without one", "template" not in plain.as_dict())
    check("[9] MESH_MODES has template", garment_set.TEMPLATE in garment_set.MESH_MODES)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(_SCRATCH, ignore_errors=True)

# [6]
rows = gt.judge_build({"wall_total_s": 60.0, "drape": {"cpu_s": 126.0}, "draped": {"rest": {"poke_share": 0.0},
                                                                                 "sit": {"poke_share": 0.02}}})
by = {r["check"]: r for r in rows}
check("[6] wall 60.0 within the budget", by["build_wall_s"]["ok"])
over = {r["check"]: r for r in gt.judge_build({"wall_total_s": 60.01})}["build_wall_s"]
check("[6] wall 60.01 over it, reported, no gate", not over["ok"] and not over["gate"], over)
user = gt.judge_build({"wall_total_s": 77.34, "slot_wait_s": 25.0, "render_wall_s": 0.0,
                       "drape": {"cpu_s": 40.0, "pin_drift_mm": 1.0, "stretch_max": 1.2},
                       "draped": {"rest": {"poke_share": 0.001}}})
ub = {r["check"]: r for r in user}
check("[6] user's case: 52.34 s of work, nothing gates", close(ub["build_wall_s"]["value"], 52.34)
      and ub["build_wall_s"]["ok"] and not [r for r in user if r["gate"] and not r["ok"]], user)
from app.blender import runner as _runner  # noqa: E402
_runs = []


def _fake_run(script, **kw):
    _runs.append(kw["params"]["fabric"]["quality"])
    first = len(_runs) == 1
    return {"ok": True, "outcome": "ok", "error": "", "log_tail": "", "outputs": {"glb": "/x.glb"},
            "slot_wait_s": 3.0 if first else 4.5,
            "data": {"script_wall_s": 10.0, "render_wall_s": 0.0,
                     "drape": {"cpu_s": 9.0, "pin_drift_mm": 0.5, "stretch_max": 1.6 if first else 1.2},
                     "draped": {"rest": {"poke_share": 0.0}}}}


_saved = (_runner.run, gt.measure_body, gt.panel_spec, gt.prepare_view)
_runner.run = _fake_run
gt.measure_body = lambda glb: {}
gt.panel_spec = lambda params, meas, **_k: {"outline": {}, "row_y": [0.0], "measure": {}}
gt.prepare_view = lambda src, dst, garment_only=True, open_mask=None: {}
_body = Path(tempfile.mkdtemp(prefix="smoke-template-run-"))
try:
    (_body / "b.glb").write_bytes(b"glb")
    res = gt.run_drape(_body / "b.glb", gt.validate_params({"kind": "skirt"})[0], {"front": "f", "back": "b"},
                       item_id="i1", out_dir=_body / "out")
finally:
    _runner.run, gt.measure_body, gt.panel_spec, gt.prepare_view = _saved
    shutil.rmtree(_body, ignore_errors=True)
check("[6] run_drape: two runs, their slot waits summed (7.5)", len(_runs) == 2
      and close(res["data"]["slot_wait_s"], 7.5), (_runs, res["data"].get("slot_wait_s")))
check("[6] run_drape: retry passes -> ok", res["ok"] and res["outcome"] == "ok", res["error"])
check("[6] CPU reported, no gate", not by["drape_cpu_s"]["ok"] and not by["drape_cpu_s"]["gate"])
check("[6] rest poke gates, sit not", by["poke_share[rest]"]["gate"] and not by["poke_share[sit]"]["gate"])
_poke = gt.failure_info({"rows": [{"check": "poke_share[rest]", "value": 0.0123, "limit": 0.005, "ok": False,
                                   "gate": True}]})
check("[6] failure_info: rest poke in per cent 1.23 / 0.5", _poke["lines"] == [
    {"text": gt.FAILURE_SENTENCES["poke_share"], "values": {"value": "1.23", "limit": "0.5"}}], _poke)
_pin = gt.failure_info({"rows": [{"check": "pin_drift_mm", "value": 7.5, "limit": 5.0, "ok": False, "gate": True}]})
check("[6] failure_info: pin drift 7.5 / 5", _pin["lines"] == [
    {"text": gt.FAILURE_SENTENCES["pin_drift_mm"], "values": {"value": "7.5", "limit": "5"}}], _pin)
_due = gt.failure_info({"outcome": "timeout", "error": "Blender timed out", "log_tail": "tail"})
check("[6] failure_info: left due -> the LEFT_DUE sentence, outcome + log_tail kept",
      _due["lines"] == [{"text": gt.LEFT_DUE["timeout"], "values": {}}] and _due["outcome"] == "timeout"
      and _due["log_tail"] == "tail" and _due["error"] == "Blender timed out", _due)
_ok_row = {"check": "stretch_max", "value": 1.1, "limit": 1.3, "ok": True, "gate": True}
check("[6] failure_info: checks passed, crashed -> NO_GLB",
      gt.failure_info({"outcome": "crashed", "rows": [_ok_row]})["lines"][0]["text"] == gt.NO_GLB_SENTENCE)
check("[6] failure_info: crashed without rows -> CRASHED",
      gt.failure_info({"outcome": "crashed"})["lines"][0]["text"] == gt.CRASHED_SENTENCE)
check("[6] failure_info: rejected without rows -> REJECTED",
      gt.failure_info({"outcome": "rejected"})["lines"][0]["text"] == gt.REJECTED_SENTENCE)

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

# [14]
import numpy as np  # noqa: E402
T = {"height": 1.7, "floor_y": 0.0, "waist_y": 1.0, "waist_c": 0.70, "hip_y": 0.80, "hip_c": 0.90,
     "band_y": 1.275, "band_c": 0.90,
     "torso": [[0.92, 0.76], [0.94, 0.74], [0.96, 0.70], [0.98, 0.68], [1.00, 0.71]]}
E = gt.EASE_M


def knots_match(got, want, tol=1e-6):
    return len(got) == len(want) and all(close(a, c, tol) and close(b, d, tol) for (a, b), (c, d) in zip(got, want))


def clears(meas, knots, hem_y, tol=1e-9):
    lo, hi = meas["torso"][0][0], meas["torso"][-1][0]
    return [(h, c) for h, c in knots if lo <= hem_y + h <= hi and c < gt._torso_girth(meas, hem_y + h) + E - tol]


sk14, _ = gt.validate_params({"kind": "skirt", "length_m": 0.5, "flare": 0.0, "waist_height": "natural"})
o = gt.outline(sk14, T)
want = [(0.0, 0.936), (0.42, 0.78), (0.44, 0.76), (0.46, 0.73728), (0.48, 0.72864), (0.50, 0.73)]
check("[14] T skirt: six knots, body-governed 0.78 / 0.76 / top 0.73, cone 0.73728 / 0.72864",
      knots_match(o["knots"], want), o["knots"])
hem14 = o["top_y"] - o["length"]
check("[14] T skirt: every knot in the torso range clears body + ease", clears(T, o["knots"], hem14) == [],
      clears(T, o["knots"], hem14))
spec14 = gt.panel_spec(sk14, T)
g = spec14["panels"][0]["grid_m"]
check("[14] panel_spec: rows 34", spec14["rows"] == 34, spec14["rows"])
check("[14] panel_spec: top row 0.365 = top knot / 2, hem row 0.468",
      close(g[0][-1][0] - g[0][0][0], o["knots"][-1][1] / 2) and close(g[0][-1][0] - g[0][0][0], 0.365)
      and close(g[-1][-1][0] - g[-1][0][0], 0.468), (g[0][-1][0] - g[0][0][0], g[-1][-1][0] - g[-1][0][0]))
rows14 = [(hem14 + row[0][1], 2 * (row[-1][0] - row[0][0])) for row in g]     # (world y, circumference)
inside = [(y, c) for y, c in rows14 if 0.92 <= y <= 1.0]
check("[14] panel_spec: every row in the torso range clears body + ease",
      inside and all(c >= gt._torso_girth(T, y) + E - 1e-9 for y, c in inside),
      [(y, c, gt._torso_girth(T, y) + E) for y, c in inside])
check("[14] legs: h 0.20 on the hem -> lowest-sample line 0.861714", close(np.interp(
    0.20, [h for h, _c in o["knots"]], [c for _h, c in o["knots"]]), 0.861714, 1e-6))
legs = [(y, c) for y, c in rows14 if y < 0.92]
check("[14] legs: every row below the profile >= the cone", legs and all(
    c >= 0.936 - 0.432 * (y - hem14) - 1e-9 for y, c in legs), legs)
fp = spec14["pygarment"]["panels"]["front"]["panels"]["front"]
check("[14] pygarment front panel: 12 edges", len(fp["edges"]) == 12, len(fp["edges"]))
dr14, _ = gt.validate_params({"kind": "dress", "length_m": 0.5, "flare": 0.0})
od = gt.outline(dr14, T)
check("[14] strapless dress: the skirt knots + band (0.755, 0.92) (A223: 2 cm under the band)",
      knots_match(od["knots"], want + [(0.755, 0.92)]), od["knots"])
TU = dict(T, shoulder_y=1.37, shoulder_w=0.39, neck_y=1.42, neck_c=0.33, arm_len=0.50,
          arm_c=[[0.05, 0.34], [0.25, 0.26], [0.5, 0.24], [0.97, 0.17]], joints={})
dc14, _ = gt.validate_params({"kind": "dress", "length_m": 0.5, "flare": 0.0, "shoulders": "covered"})
ob = gt.outline(dc14, TU)
by_h = {round(h, 2): c for h, c in ob["knots"]}
check("[14] covered dress grid: 0.78 at h 0.42, 0.7373 at h 0.46, 0.8617 at h 0.20",
      close(by_h.get(0.42, 0), 0.78) and close(by_h.get(0.46, 0), 0.7373) and close(by_h.get(0.2, 0), 0.8617),
      ob["knots"][:26])
skirt_part = [(h, c) for h, c in ob["knots"] if h <= 0.5 + 1e-9]
check("[14] covered dress: skirt knots clear body + ease (less the 4-decimal rounding)",
      clears(TU, skirt_part, 0.5, tol=5e-5) == [], clears(TU, skirt_part, 0.5, tol=5e-5))
T0 = dict(T, torso=[[0.92, 0.70], [0.96, 0.68], [1.00, 0.68]])
T0_bare = {k: v for k, v in T0.items() if k != "torso"}
o0 = gt.outline(sk14, T0)
check("[14] cleared body: exactly the two old knots (0, 0.936), (0.5, 0.72)",
      knots_match(o0["knots"], [(0.0, 0.936), (0.5, 0.72)]), o0["knots"])
check("[14] cleared body: outline identical to the measure without a torso", o0 == gt.outline(sk14, T0_bare),
      (o0, gt.outline(sk14, T0_bare)))
check("[14] cleared body: no knot off the cone line",
      all(close(c, 0.936 - 0.432 * h, 1e-9) for h, c in o0["knots"]), o0["knots"])
two = gt._skirt_knots(T0, 1.0, 0.5, 0.936, 0.72)
check("[14] cleared body: the covered dress interpolates the same two knots", two == [(0.0, 0.936), (0.5, 0.72)], two)
GEL = {"height": 1.65, "floor_y": 0.0, "waist_y": 1.0475, "waist_c": 0.578, "hip_y": 0.7925, "hip_c": 0.9279,
       "band_y": 1.2375, "band_c": 0.9976,
       "torso": [[0.66, 0.8568], [0.68, 0.8705], [0.70, 0.884], [0.72, 0.8957], [0.74, 0.9077], [0.76, 0.9145],
                 [0.78, 0.9264], [0.80, 0.9259], [0.82, 0.9178], [0.84, 0.9007], [0.86, 0.8775], [0.88, 0.8592],
                 [0.90, 0.8388], [0.92, 0.8217], [0.94, 0.7937]]}
gp, ge = gt.validate_params({"kind": "skirt", "length_m": 0.76, "flare": 0.68, "waist_height": "low",
                             "slit": "left", "slit_m": 0.6, "fabric": "flowing"})
og = gt.outline(gp, GEL)
gk = og["knots"]
gby = {round(og["top_y"] - og["length"] + h, 2): c for h, c in gk}
check("[14] Gelina: params valid, top_y 0.92", ge == [] and close(og["top_y"], 0.92), (ge, og["top_y"]))
check("[14] Gelina: top knot 0.8417 (was 0.77295)", close(gk[-1][1], 0.8417), gk[-1])
check("[14] Gelina: hem 1.94933 unchanged (legs)", close(gk[0][1], 1.94933), gk[0])
check("[14] Gelina: y 0.82 -> 0.9378 (body), y 0.80 -> 0.9587 (cone)",
      close(gby.get(0.82, 0), 0.9378) and close(gby.get(0.8, 0), 0.9587), gby)
check("[14] Gelina: 15 knots, all clear body + ease", len(gk) == 15 and clears(GEL, gk, og["top_y"] - og["length"]) == [],
      (len(gk), clears(GEL, gk, og["top_y"] - og["length"])))
sg = gt.panel_spec(gp, GEL)
gg = sg["panels"][1]["grid_m"]
check("[14] Gelina: panel top row = 0.8417 / 2", close(gg[0][-1][0] - gg[0][0][0], 0.42085), gg[0][-1][0] - gg[0][0][0])

# [15] pattern-piece UVs: uv_mode, the islands file beside the drape
_top15, _ = gt.validate_params({"kind": "top", "sleeves": "short"})
check("[15] top -> uv_mode pattern", gt.build_args(_top15, gt.panel_spec(_top15, MU), item_id="x").get("uv_mode") == "pattern")
for _kw in ({"kind": "jacket"}, {"kind": "dress", "shoulders": "covered", "sleeves": "short"}):
    _p15, _ = gt.validate_params(_kw)
    check(f"[15] {_kw['kind']} -> uv_mode pattern (phases C / D)",
          gt.build_args(_p15, gt.panel_spec(_p15, MU), item_id="x").get("uv_mode") == "pattern")
check("[15] TEMPLATE_VERSION 10", gt.TEMPLATE_VERSION == 10, gt.TEMPLATE_VERSION)

# [16] step 3a: the fitted kinds are cut into pattern pieces
# the arm joints of Dario's base body (from scripts/smoke_template_cut_first.py) — gloves are fitted to them
_mu16 = {**MU, "joints": {"leftarm": [0.2081, 1.508, 0.0138], "leftforearm": [0.4789, 1.5019, 0.0144],
                          "lefthand": [0.7741, 1.5103, 0.0246], "rightarm": [-0.2161, 1.5154, 0.0044],
                          "rightforearm": [-0.4825, 1.5129, 0.004], "righthand": [-0.7713, 1.5261, 0.0075]},
         "arm_len": 0.5607}
for _k16 in ("briefs", "bra", "gloves", "tights", "trousers"):
    _p16, _ = gt.validate_params({"kind": _k16})
    check(f"[16] {_k16} -> uv_mode pattern",
          gt.build_args(_p16, gt.panel_spec(_p16, _mu16), item_id="x").get("uv_mode") == "pattern")
check("[16] FITTED_VERSION is 1", gt.FITTED_VERSION == 1, gt.FITTED_VERSION)
_kw16 = dict(base_sha="a" * 64, texture_sha="t1", lower=["b", "a"])
for _k16 in ("briefs", "bra", "gloves", "tights", "trousers"):
    _pp16 = gt.validate_params({"kind": _k16})[0]
    _pre16 = {"params": gt.keyed_params(_pp16), "version": gt.TEMPLATE_VERSION, "base": "a" * 64, "texture": "t1",
              "lower": ["a", "b"]}
    _got16 = gt.tsig(_pp16, **_kw16)
    check(f"[16] a default {_k16}'s tsig = pre-release payload + fitted 1", _got16 == gt._md5({**_pre16, "fitted": 1}))
    check(f"[16] ... and differs from the pre-release key", _got16 != gt._md5(_pre16))
import importlib.util  # noqa: E402
import subprocess  # noqa: E402
_src16 = subprocess.run(["git", "show", "c926b67f0:app/core/garment_template.py"], cwd=ROOT, capture_output=True,
                        text=True)
if _src16.returncode != 0:
    print("     [16] base comparison skipped (no git / no base commit)")
else:
    _d16 = Path(tempfile.mkdtemp(prefix="smoke-template-base-"))
    try:
        (_d16 / "garment_template_base.py").write_text(_src16.stdout)
        _spec16 = importlib.util.spec_from_file_location("garment_template_base", _d16 / "garment_template_base.py")
        _gb16 = importlib.util.module_from_spec(_spec16)
        _spec16.loader.exec_module(_gb16)
        _raw16 = {"kind": "top", "sleeves": "short"}
        check("[16] a top's tsig is the base commit's", gt.tsig(gt.validate_params(_raw16)[0], **_kw16)
              == _gb16.tsig(_gb16.validate_params(_raw16)[0], **_kw16))
    finally:
        shutil.rmtree(_d16, ignore_errors=True)
# [17] step 3b: skirts and strapless tops
_sk17 = gt.validate_params({"kind": "skirt", "waistband": "wide"})[0]
_ba17 = gt.build_args(_sk17, gt.panel_spec(_sk17, MU), item_id="x")
check("[17.1] skirt -> uv_mode pattern, waistband_m 0.03", _ba17.get("uv_mode") == "pattern"
      and _ba17.get("waistband_m") == 0.03, (_ba17.get("uv_mode"), _ba17.get("waistband_m")))
_sl17 = gt.validate_params({"kind": "top", "shoulders": "strapless"})[0]
check("[17.1] strapless top -> uv_mode pattern, no waistband_m",
      gt.build_args(_sl17, gt.panel_spec(_sl17, MU), item_id="x").get("uv_mode") == "pattern"
      and "waistband_m" not in gt.build_args(_sl17, gt.panel_spec(_sl17, MU), item_id="x"))
check("[17.1] a top with a bodice: no waistband_m", "waistband_m" not in gt.build_args(
    _top15, gt.panel_spec(_top15, MU), item_id="x"))
check("[17.2] PANEL_VERSION is 1", gt.PANEL_VERSION == 1, gt.PANEL_VERSION)
for _p17 in (_sk17, _sl17):
    _pre17 = {"params": gt.keyed_params(_p17), "version": gt.TEMPLATE_VERSION, "base": "a" * 64, "texture": "t1",
              "lower": ["a", "b"]}
    _got17 = gt.tsig(_p17, **_kw16)
    check(f"[17.2] {_p17['kind']} {_p17['shoulders']}: tsig = payload + panels 1",
          _got17 == gt._md5({**_pre17, "panels": 1}) and _got17 != gt._md5(_pre17))
check("[17.2] a top with sleeves and a fitted kind are no panel piece",
      not gt.panel_piece(_top15) and not gt.panel_piece(gt.validate_params({"kind": "briefs"})[0]))
check("[17.3] a saved skirt keeps waistband thin", gt.validate_params({"kind": "skirt"})[0]["waistband"] == "thin")
check("[17.3] a new skirt: waistband wide", gt.kind_defaults("skirt")["waistband"] == "wide")
check("[17.3] waistband + texture are skirt fields", {"waistband", "texture"} <= set(gt.KIND_FIELDS["skirt"]))
for _side17 in ("front_left", "front_right"):
    check(f"[17.3] slit {_side17} is valid",
          gt.validate_params({"kind": "skirt", "slit": _side17, "slit_m": 0.2})[0]["slit"] == _side17)
import math as _m17  # noqa: E402
import re as _re17  # noqa: E402
_b17 = (ROOT / "app" / "blender" / "scripts" / "garment_template_build.py").read_text(encoding="utf-8")
_sa17 = eval(_re17.search(r"^SLIT_ANGLE = (\{.*?\})$", _b17, _re17.S | _re17.M).group(1), {"math": _m17})
check("[17.4] SLIT_ANGLE front_left - 1.5 pi = 0.471239", abs(_sa17["front_left"] - 1.5 * _m17.pi - 0.471239) < 1e-6,
      _sa17["front_left"] - 1.5 * _m17.pi)
check("[17.4] SLIT_ANGLE front_right = 1.5 pi - 0.471239", abs(1.5 * _m17.pi - _sa17["front_right"] - 0.471239) < 1e-6)
import hashlib  # noqa: E402
_t15 = Path(tempfile.mkdtemp(prefix="smoke-template-islands-"))
_saved15 = {k: getattr(gt, k) for k in ("templates_dir", "drape_with_fallback", "texture_sources")}
from app.core import bust_shaping as _bs15  # noqa: E402
_prep15 = _bs15.prepare
try:
    gt.templates_dir = lambda name: _t15 / "templates"
    gt.texture_sources = lambda name, item_id: {"front": "f.png", "back": "b.png", "source": "item_image"}
    _bs15.prepare = lambda body, item_id, item, lower, folder: (body, None, None)

    def _fake15(with_islands):
        def run(run_one, colliders, own):
            out = _t15 / "run"
            out.mkdir(parents=True, exist_ok=True)
            (out / "template.glb").write_bytes(b"glb")
            outputs = {"glb": str(out / "template.glb")}
            if with_islands:
                (out / "islands.json").write_text(json.dumps({"version": 1, "atlas_px": 2048, "px_per_cm": 19.59,
                                                              "islands": []}))
                outputs["islands"] = str(out / "islands.json")
            return ({"ok": True, "glb": outputs["glb"], "outputs": outputs, "data": {"drape": {}}, "rows": [],
                     "outcome": "ok", "error": "", "log_tail": ""}, {"mode": "full", "failed": []})
        return run

    _item15 = {"category": "outfit_piece", "outfit_piece": {"slots": ["top"], "mesh_mode": "template",
                                                           "template": {"params": dict(_top15)}}}
    for _with, _sig in ((True, "aaaaaaaaaaaa"), (False, "bbbbbbbbbbbb")):
        gt.drape_with_fallback = _fake15(_with)
        _raw15 = (_t15 / "run" / "islands.json")
        gt._build_drape("K", "i15", key=("K", "i15"), profile={}, base=("sig", "sha"), base_sha="sha", lower=[],
                        item=_item15, sig=_sig, sources={"front": "f.png", "back": "b.png", "source": "item_image"},
                        body=_t15 / "body.glb", params=dict(_top15))
        _rec15 = json.loads(gt.drape_path("K", "i15", _sig).with_suffix(".json").read_text())
        _isl15 = gt.islands_path("K", "i15", _sig) if hasattr(gt, "islands_path") else _t15 / "none"
        if _with:
            _bytes = _isl15.read_bytes() if _isl15.is_file() else b""
            check("[15] islands.json moved beside the GLB", _isl15.name == f"i15_{_sig}.islands.json"
                  and _isl15.parent == gt.drape_path("K", "i15", _sig).parent and b'"px_per_cm": 19.59' in _bytes,
                  _isl15)
            check("[15] the record lists the islands file", _rec15.get("islands") == {
                "file": f"i15_{_sig}.islands.json", "sha256": hashlib.sha256(_bytes).hexdigest(), "px_per_cm": 19.59},
                _rec15.get("islands"))
        else:
            check("[15] a grid run: no islands file, no islands key", not _isl15.is_file() and "islands" not in _rec15,
                  _rec15.get("islands"))
finally:
    for _k, _v in _saved15.items():
        setattr(gt, _k, _v)
    _bs15.prepare = _prep15
    shutil.rmtree(_t15, ignore_errors=True)

# ---------------------------------------------------------------------------------------------------- [18] E + F
check("[18.1] collar, placket, buttons are top fields", {"collar", "placket", "buttons"} <= set(gt.KIND_FIELDS["top"]))
check("[18.1] a top's lapel -> stand", gt.validate_params({"kind": "top", "shoulders": "covered",
                                                        "collar": "lapel"})[0]["collar"] == "stand")
for _sh18 in ("off_shoulder", "straps"):
    check(f"[18.1] a {_sh18} top: collar none", gt.validate_params({"kind": "top", "shoulders": _sh18,
                                                                  "collar": "stand"})[0]["collar"] == "none")
_t18 = gt.validate_params({"kind": "top", "shoulders": "covered", "sleeves": "elbow"})[0]
_kw18 = {"base_sha": "a" * 64, "texture_sha": "t1", "lower": []}
check("[18.2] placket / buttons do not key the drape",
      gt.tsig(dict(_t18, placket="buttons", buttons=7), **_kw18) == gt.tsig(_t18, **_kw18))
check("[18.2] a stand collar keys the drape", gt.tsig(dict(_t18, collar="stand"), **_kw18) != gt.tsig(_t18, **_kw18))
from app.core import garment_template_cut as gtc  # noqa: E402
check("[18.3] NECK_VERSION is 1", getattr(gt, "NECK_VERSION", None) == 1)


def _cut18(p):
    return {"params": gtc.cut_params(p), "version": gt.TEMPLATE_VERSION, "uv_pattern": gtc.uv_pattern_key(p),
            "base": "b" * 64, "lower": ["x"]}


import hashlib as _h18  # noqa: E402


def _md18(payload):
    return _h18.md5(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


check("[18.3] a covered top without collar / placket: the key before the phases (no neck)",
      gtc.cut_sig(_t18, base_sha="b" * 64, lower=["x"]) == _md18(_cut18(_t18)))
for _extra18 in ({"placket": "buttons"}, {"collar": "stand"}):
    _n18 = dict(_t18, **_extra18)
    check(f"[18.3] a covered top with {_extra18}: payload + neck 1",
          gtc.cut_sig(_n18, base_sha="b" * 64, lower=["x"]) == _md18({**_cut18(_n18), "neck": 1}))
for _sh18 in ("off_shoulder", "straps"):
    _o18 = gt.validate_params({"kind": "top", "shoulders": _sh18, "sleeves": "elbow"})[0]
    check(f"[18.3] a {_sh18} top's cut key carries no neck, with a placket too",
          gtc.cut_sig(_o18, base_sha="b" * 64, lower=["x"]) == _md18(_cut18(_o18))
          and gtc.cut_sig(dict(_o18, placket="buttons"), base_sha="b" * 64, lower=["x"])
          == _md18(_cut18(dict(_o18, placket="buttons"))))

print("\n" + ("all checks passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
