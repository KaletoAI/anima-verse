"""Smoke: glasses (bug round 2026-11-20) — the description, the outlines, the layout, the gate, the store/graft and
the ``face`` clothing slot (``app/core/accessory_glasses.py``, ``accessory_spec``, ``accessory_build``).

Usage: ./.venv/bin/python scripts/smoke_accessory_glasses.py   (no server, no world; a temp store, the tracked
       puppet rig ``shared/models/rig/puppet.glb`` for the end-to-end part)

Expected values, derived by hand from the module docstrings:

[1] ``normalize({"kind": "glasses"})``: glasses {shape rectangular, size regular, rim_mm 2.0 (metal), frame metal,
    temple hook, lens {tint clear, opacity 0.08, mirror False}}. Frame acetate without a rim → rim 3.5; rim 9 → 5.0
    (clamped to 0.8–5); a grey tint without an opacity → 0.8; opacity 1.5 → 0.9; tint "pink" → clear; a custom tint
    keeps its colour lower-cased; shape "oval" → rectangular. Another kind has no ``glasses`` block. ``BUILT_KINDS``
    holds glasses. ``shape_inputs`` = {shape, size, rim_mm, frame, temple} — the lens is not in it, so a grey lens
    keeps the asig while ``material_key`` changes; a round frame changes the asig. ``_wants_under`` False.
    ``suggest_kind``: "Sunglasses" → glasses, "Lesebrille" → glasses. ``lens_material``: clear → #ffffff at 0.08,
    metal 0, rough 0.05; green mirrored → #2e4a32 at 0.8, metal 1.0, rough 0.1. ``frame_material``: acetate without a
    colour → (#1c1c1c, 0.35, 0.0); metal silver → (#c0c0c0, 0.2, 1.0). ``lens_seen_far``: clear False, grey True,
    clear + mirror True.
[2] ``outline`` (w 0.04, h 0.024 → a 0.02, c 0.012, 64 points, t = 2πk/64; tolerance 1e-8 at k 16 because cos(π/2) is
    6e-17 in floats and u = a · (6e-17)^(2/4.5) ≈ 1.2e-9):
    round w 0.04: every point 0.02 from the centre (±1e-12). rectangular: the point t = 0 is (0.02, 0); t = π/2
    (k 16) is (0, 0.012). cat_eye: k 8 (t = π/4): the superellipse (3) point is (a, c) · (√2/2)^(2/3) = (a, c) ·
    0.793701 = (0.0158740, 0.0095244); lift = 0.4 · 0.024 · 0.793701² · 0.793701 = 0.0096 · 0.5 = 0.0048000 →
    v 0.0143244. aviator: k 48 (t = 3π/2) is (0, −c) on the superellipse; drop = 1 + 0.55 · (a − 0) / (2a) = 1.275 →
    v −0.0153; k 40 (t = 5π/4, u < 0): superellipse (2.5) (−a, −c) · (√2/2)^(0.8) = · 0.757858 → u −0.0151572, v
    −0.0090943; drop = 1 + 0.55 · (a + 0.0151572) / (2a) = 1 + 0.55 · 0.87893 = 1.483411 → v −0.0134905.
[3] ``_plane_z`` (mid 0, eye_y 1.5, b 0.01): at x 0.034, y 1.5 the wrap is −(0.034 − 0.01) · tan 5° = −0.024 ·
    0.0874887 = −0.0020997; at x 0.005 (inside the bridge) 0; at y 1.49 the tilt adds −0.01 · tan 8° = −0.0014054.
[4] ``layout`` on a hand-made face: mid 0, eye_y 1.5, pad_y 1.496, ridge_z 0.09, nose half 0.008; an empty depth
    map except a nose patch z 0.088 at |x| ≤ 0.008, y 1.493…1.499 (it asks only z0 ≥ 0.088 + 0.002 + 0.001 = 0.091 <
    0.095); head samples only at x ±0.06, y 1.505, z 0.050…0.070 (1 mm steps); no ear found; height 1.70; metal 2 mm,
    rectangular, regular. b = 0.008 + 0.002 = 0.010. The lens back's minimum z0 = ridge + PAD_DIST 0.004 + the rim's
    half depth 0.001 = 0.095; nothing in the depth map pushes it (brow 0). The side is read at y 1.505, z 0.095 −
    0.035 = 0.060: 0.06 on both sides → W = 0.06 + 0.003 = 0.063; w = 0.063 − 0.010 − 0.005 = 0.048, h = 0.048 · 0.65
    = 0.0312; the lens centre u = 0.010 + 0.024 = 0.034 → the left lens centre (0.034, 1.5, 0.095 − 0.0020997 =
    0.0929003). Round: w = min(0.048, 0.046) = 0.046. No ear: the temple runs to the depth 0.10 · 1.70 / 1.70 − 0.01
    + 0.01 = 0.10 behind z0 → its last point z −0.005, ending "no_ear"; every temple point after the first lies at
    |x| = max(W 0.063, the side 0.06 + 0.002 + 0.0007) = 0.063, at y 1.505. With an ear used (top 1.51, front z
    0.015 — 0.080 behind z0) and ``hook``: y_ear = max(1.505, 1.51 + 0.0007 + 0.002) = 1.5127; the temple runs to
    0.080 + 0.020 = 0.100 behind z0 (z −0.005) at y 1.5127 and drops 0.020 in 7 more points to y 1.4927, z −0.005 −
    0.012 = −0.017, ending "hook". A depth-map cell inside the left outline at (0.034, 1.5) with z 0.0941003 asks for
    z0 ≥ 0.0941003 − (−0.0020997) + 0.002 + 0.001 = 0.0992 → brow 4.2 mm, z0 0.0992.
[5] The gate (``build`` with the face, samples, ears and distance stubbed: every point 5 mm off the skin): brow 4.2 mm
    → built, forward_mm 4.2; the cell at z 0.1001003 (brow 10.2 mm > MAX_PUSH 8 mm) → "The brow stands 10 mm in
    front of the nose bridge — the lenses would float; choose a smaller or lower frame".
[6] ``SkinDistance`` on the closed cube [−0.1, 0.1]³: (0, 0, 0.11) → +0.01, (0, 0, 0) → −0.1, the corner point
    (0.11, 0.11, 0.11) → +0.01·√3 = +0.0173205 (closest point the corner vertex, its pseudo-normal outward).
    ``FaceDistance.outside``: a point in front of a depth-map cell is outside; behind it is not.
[7] End to end on the puppet rig (``make_glasses``): built; every vertex on the Head at weight 1.0; frame, rims,
    lenses and temples ≥ GAP_MIN 1.9 mm off the skin, the pads ≥ PAD_MIN 0.7 mm; the store (``build`` with a
    patched base) writes LV/LF/FT; the graft carries the frame node and the lens node (alphaMode BLEND, doubleSided,
    alpha 0.08, ``anima_sheer``); the distance tier keeps the frame without the temple faces (fewer triangles) and
    leaves the clear lenses off, a grey pair stays.
[8] The ``face`` slot: in ``VALID_PIECE_SLOTS`` (before head) with the label "Face", in the human topology (portrait)
    with an anchor, the play order, the outfit prompt and the keyword fallback (glasses), and every client list.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_accessory_glasses_")
os.environ["STORAGE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
import numpy as np  # noqa: E402
from app.core import accessory_build as ab, accessory_glasses as ag, accessory_spec as s, glb_mesh  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def near(name, got, want, tol=1e-6):
    ok = bool(np.all(np.abs(np.asarray(got, float) - np.asarray(want, float)) <= tol))
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {np.round(got, 7).tolist()!r}"
          + ("" if ok else f" (expected {want!r} ± {tol})"))
    if not ok:
        FAIL.append(name)


# [1] the description
g = s.normalize({"kind": "glasses"})["glasses"]
check("[1] defaults", g, {"shape": "rectangular", "size": "regular", "rim_mm": 2.0, "frame": "metal",
                          "temple": "hook", "lens": {"tint": "clear", "opacity": 0.08, "mirror": False}})
check("[1] acetate rim", s.normalize({"kind": "glasses", "glasses": {"frame": "acetate"}})["glasses"]["rim_mm"], 3.5)
check("[1] rim clamp", s.normalize({"kind": "glasses", "glasses": {"rim_mm": 9}})["glasses"]["rim_mm"], 5.0)
check("[1] grey opacity", s.normalize({"kind": "glasses", "glasses": {"lens": {"tint": "grey"}}})["glasses"]["lens"],
      {"tint": "grey", "opacity": 0.8, "mirror": False})
check("[1] opacity clamp", s.normalize({"kind": "glasses", "glasses": {"lens": {"opacity": 1.5}}})
      ["glasses"]["lens"]["opacity"], 0.9)
check("[1] unknown tint", s.normalize({"kind": "glasses", "glasses": {"lens": {"tint": "pink"}}})
      ["glasses"]["lens"]["tint"], "clear")
check("[1] custom colour", s.normalize({"kind": "glasses", "glasses": {"lens": {"tint": "custom", "color": "#AA0011"}}})
      ["glasses"]["lens"]["color"], "#aa0011")
check("[1] unknown shape", s.normalize({"kind": "glasses", "glasses": {"shape": "oval"}})["glasses"]["shape"],
      "rectangular")
check("[1] no block on other kinds", "glasses" in s.normalize({"kind": "ring"}), False)
check("[1] built", "glasses" in s.BUILT_KINDS, True)
spec = s.normalize({"kind": "glasses"})
check("[1] shape inputs", ab.shape_inputs(spec), {"shape": "rectangular", "size": "regular", "rim_mm": 2.0,
                                                  "frame": "metal", "temple": "hook"})
grey = s.normalize({"kind": "glasses", "glasses": {"lens": {"tint": "grey"}}})
check("[1] lens keeps the asig", ab.asig(grey) == ab.asig(spec), True)
mk = {k: ab.material_key({"outfit_piece": {"jewellery": v}}) for k, v in (("clear", spec), ("grey", grey))}
check("[1] lens changes the material key", mk["clear"] != mk["grey"], True)
check("[1] round changes the asig",
      ab.asig(s.normalize({"kind": "glasses", "glasses": {"shape": "round"}})) != ab.asig(spec), True)
check("[1] nothing under it", ab._wants_under(spec), False)
check("[1] suggest", [s.suggest_kind({"name": n, "outfit_piece": {"slots": ["face"]}})
                      for n in ("Sunglasses", "Lesebrille")], ["glasses", "glasses"])
check("[1] lens clear", s.lens_material(spec), {"color": "#ffffff", "opacity": 0.08, "metalness": 0.0,
                                                "roughness": 0.05, "mirror": False})
green = s.normalize({"kind": "glasses", "glasses": {"lens": {"tint": "green", "mirror": True}}})
check("[1] lens green mirrored", s.lens_material(green), {"color": "#2e4a32", "opacity": 0.8, "metalness": 1.0,
                                                          "roughness": 0.1, "mirror": True})
check("[1] acetate frame", s.frame_material(s.normalize({"kind": "glasses", "glasses": {"frame": "acetate"}})),
      ("#1c1c1c", 0.35, 0.0))
check("[1] silver frame", s.frame_material(s.normalize({"kind": "glasses", "metal": "silver"})),
      ("#c0c0c0", 0.2, 1.0))
check("[1] seen far", [s.lens_seen_far(x) for x in (spec, grey, s.normalize(
    {"kind": "glasses", "glasses": {"lens": {"mirror": True}}}))], [False, True, True])

# [2] outlines
r = ag.outline("round", 0.04, 0.04)
near("[2] round radius", np.linalg.norm(r, axis=1).max() - 0.02, 0.0, 1e-12)
near("[2] round radius min", np.linalg.norm(r, axis=1).min() - 0.02, 0.0, 1e-12)
q = ag.outline("rectangular", 0.04, 0.024)
near("[2] rectangular k0", q[0], [0.02, 0.0], 1e-12)
near("[2] rectangular k16", q[16], [0.0, 0.012], 1e-8)
c = ag.outline("cat_eye", 0.04, 0.024)
near("[2] cat-eye k8", c[8], [0.0158740, 0.0143244], 2e-7)
a = ag.outline("aviator", 0.04, 0.024)
near("[2] aviator k48", a[48], [0.0, -0.0153], 1e-9)
near("[2] aviator k40", a[40], [-0.0151572, -0.0134905], 2e-7)

# [3] tilt and wrap
LM = {"mid_x": 0.0, "eye_y": 1.5, "pad_y": 1.496, "ridge_z": 0.09, "nose_half_m": 0.008,
      "nose_tip": np.array([0.0, 1.47, 0.1]), "nasion": np.array([0.0, 1.504, 0.088]),
      "depth": {"Z": np.full((40, 120), np.nan), "x0": -0.06, "y0": 1.48}}
# the nose flanks the pads sit on: z 0.088 over |x| <= 0.008 (columns 52..68), y 1.493..1.499 (rows 13..19)
LM["depth"]["Z"][13:20, 52:69] = 0.088
near("[3] wrap", ag._plane_z(0.034, 1.5, LM, 0.01), -0.0020997, 1e-7)
near("[3] inside the bridge", ag._plane_z(0.005, 1.5, LM, 0.01), 0.0, 1e-12)
near("[3] tilt", ag._plane_z(0.005, 1.49, LM, 0.01), -0.0014054, 1e-7)

# [4] the layout
Q = np.array([[sx * 0.06, 1.505, z] for sx in (1.0, -1.0) for z in np.arange(0.05, 0.0705, 0.001)])
NO_EAR = {"left": {"found": False, "used": False}, "right": {"found": False, "used": False}}
lay = ag.layout(LM, Q, spec["glasses"], NO_EAR, 1.70)
near("[4] b, W, w, h, z0", [lay["b"], lay["W"], lay["w"], lay["h"], lay["z0"]],
     [0.010, 0.063, 0.048, 0.0312, 0.095], 1e-9)
near("[4] brow", lay["brow_m"], 0.0, 1e-12)
near("[4] left lens centre", lay["lens_centre"]["left"], [0.034, 1.5, 0.0929003], 1e-7)
near("[4] round w", ag.layout(LM, Q, s.normalize({"kind": "glasses", "glasses": {"shape": "round"}})["glasses"],
                              NO_EAR, 1.70)["w"], 0.046, 1e-12)
tl = lay["temples"]["left"]
near("[4] temple end z", tl[-1][2], -0.005, 1e-9)
near("[4] temple x", np.abs(tl[1:, 0]), np.full(len(tl) - 1, 0.063), 1e-9)
near("[4] temple y", tl[1:, 1], np.full(len(tl) - 1, 1.505), 1e-9)
check("[4] ends", lay["temple_ends"], {"left": "no_ear", "right": "no_ear"})
EAR = {"found": True, "used": True, "top_y": 1.51, "front_z": 0.015, "back_z": 0.0}
hook = ag.layout(LM, Q, spec["glasses"], {"left": EAR, "right": EAR}, 1.70)["temples"]["left"]
near("[4] hook top", hook[-8], [0.063, 1.5127, -0.005], 1e-9)
near("[4] hook end", hook[-1], [0.063, 1.4927, -0.017], 1e-9)
LMB = dict(LM, depth={"Z": LM["depth"]["Z"].copy(), "x0": -0.06, "y0": 1.48})
# the cell holding (0.034, 1.5): column (0.034 + 0.06) / 0.001 = 94, row (1.5 − 1.48) / 0.001 = 20
LMB["depth"]["Z"][20, 94] = 0.0941003
cell_x, cell_y = -0.06 + 94.5 * 0.001, 1.48 + 20.5 * 0.001
want_z0 = 0.0941003 - float(ag._plane_z(cell_x, cell_y, LMB, 0.010)) + 0.002 + 0.001
lay_b = ag.layout(LMB, Q, spec["glasses"], NO_EAR, 1.70)
near("[4] brow push z0 (cell centre)", lay_b["z0"], want_z0, 1e-9)
near("[4] brow push ~4.2 mm", lay_b["brow_m"] * 1000.0, 4.2, 0.2)


# [5] the gate with stubbed face / distance
class _Body:
    positions = np.array([[0, 0, 0], [0, 1.7, 0], [0.1, 0, 0]], float)
    faces = np.array([[0, 1, 2]])
    joint_positions = {"mixamorig:Head": [0.0, 1.45, 0.0]}
    joint_names = ["mixamorig:Head"]


class _FarDistance:
    def __init__(self, *a, **k):
        pass

    def __call__(self, X):
        X = np.asarray(X, float)
        return np.full(len(X), 0.005), X - 0.005, np.tile([0.0, 0.0, 1.0], (len(X), 1))


def gate(lm):
    saved = (ag.face_landmarks, ag.head_samples, ag.ear_info, ag.SkinDistance, ag.FaceDistance)
    ag.face_landmarks = lambda *a, **k: lm
    ag.head_samples = lambda *a, **k: Q
    ag.ear_info = lambda *a, **k: {"found": False, "used": False}
    ag.SkinDistance, ag.FaceDistance = _FarDistance, _FarDistance
    try:
        return ag.build(_Body(), np.ones((3, 1)), _Body.positions, _Body.faces, np.arange(3), spec)
    finally:
        ag.face_landmarks, ag.head_samples, ag.ear_info, ag.SkinDistance, ag.FaceDistance = saved


made = gate(LMB)
near("[5] forward_mm", made["metrics"]["forward_mm"], 4.2, 0.2)
LMF = dict(LMB, depth={"Z": LMB["depth"]["Z"].copy(), "x0": -0.06, "y0": 1.48})
LMF["depth"]["Z"][20, 94] = 0.1001003
try:
    gate(LMF)
    check("[5] brow refused", "built", "refused")
except ValueError as e:
    check("[5] brow refused", str(e), "The brow stands 10 mm in front of the nose bridge — the lenses would float; "
                                      "choose a smaller or lower frame")

# [6] the distance
cube_P = np.array([[x, y, z] for x in (-0.1, 0.1) for y in (-0.1, 0.1) for z in (-0.1, 0.1)], float)
cube_F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                   [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
sd = ag.SkinDistance(cube_P, cube_F, np.zeros(3), radius=1.0)
near("[6] cube distances", sd(np.array([[0, 0, 0.11], [0, 0, 0], [0.11, 0.11, 0.11]]))[0],
     [0.01, -0.1, 0.0173205], 1e-7)
fd = ag.FaceDistance(sd, {"depth": {"Z": np.full((1, 1), 0.05), "x0": 0.0, "y0": 0.0}, "mid_x": 0.0},
                     np.array([[0.05, 0.0, 0.0]]))
check("[6] in front of the face map", fd.outside(np.array([[0.0005, 0.0005, 0.06], [0.0005, 0.0005, 0.04]])).tolist(),
      [True, False])

# [7] end to end on the puppet rig
PUPPET = (ROOT / "shared/models/rig/puppet.glb").read_bytes()
m = ab.make_glasses(PUPPET, spec)
check("[7] rigid on the Head", (bool(np.all(m["W"][:, 0] == 1.0)), bool(np.all(m["lens"]["W"][:, 0] == 1.0)),
                                list(m["metrics"]["joints"])), (True, True, ["mixamorig:Head"]))
check("[7] gap >= 1.9 mm", m["metrics"]["gap_mm"]["min"] >= 1.9, True)
check("[7] pads >= 0.7 mm", m["metrics"]["pad_gap_mm"] >= 0.7, True)
store = Path(TMP) / "store"
store.mkdir()
cdir = Path(TMP) / "char"
(cdir / "model3d").mkdir(parents=True)
(cdir / "model3d" / "base1.glb").write_bytes(PUPPET)
import app.models.character as mc  # noqa: E402
import app.models.inventory as inv  # noqa: E402
from app.core import model_geometry  # noqa: E402
ITEM = {"id": "item_g", "category": "outfit_piece", "name": "Glasses",
        "outfit_piece": {"slots": ["face"], "mesh_mode": "accessory", "jewellery": {"kind": "glasses"}}}
ab.store_dir = lambda _c: store
ab._current_base = lambda _c, _p: ("base1", "SHA1")
mc.get_character_dir = lambda _c: cdir
inv.get_item = lambda _i: ITEM
model_geometry.record_matches = lambda rec, sha, **_k: rec.get("base_model_sha256") == sha
model_geometry.stamp_on = lambda *a, **k: {}
st = ab.build("Puppet", "item_g", profile={})
check("[7] built", st["state"], "current")
with np.load(ab.npz_path("Puppet", "item_g", st["record"])) as z:
    check("[7] stored parts", {"LV", "LF", "FT"} <= set(z.files), True)


def grafted(item, low):
    out = ab.graft_accessory(PUPPET, "Puppet", "item_g", st["record"], st["asig"], item, low=low)
    gl = glb_mesh._parse(out, "x")["gltf"]
    tris = {mm["name"]: sum(gl["accessors"][p["indices"]]["count"] // 3 for p in mm["primitives"])
            for mm in gl["meshes"] if str(mm.get("name", "")).startswith("garment_accessory_item_g")}
    mats = {mt["name"]: mt for mt in gl["materials"] if str(mt.get("name", "")).startswith("garment_accessory_item_g")}
    return tris, mats


full, mats = grafted(ITEM, False)
check("[7] nodes", sorted(full), ["garment_accessory_item_g_c", "garment_accessory_item_g_g"])
lens_mat = mats["garment_accessory_item_g_g"]
check("[7] lens material", (lens_mat.get("alphaMode"), lens_mat.get("doubleSided"),
                            lens_mat["pbrMetallicRoughness"]["baseColorFactor"][3], lens_mat.get("extras")),
      ("BLEND", True, 0.08, {"anima_sheer": True, "opacity": 0.08}))
low, _m = grafted(ITEM, True)
check("[7] far: frame only, fewer triangles", (sorted(low), low["garment_accessory_item_g_c"]
                                               < full["garment_accessory_item_g_c"]),
      (["garment_accessory_item_g_c"], True))
GREY = {**ITEM, "outfit_piece": {**ITEM["outfit_piece"], "jewellery": {"kind": "glasses",
                                                                      "glasses": {"lens": {"tint": "grey"}}}}}
low_grey, _m = grafted(GREY, True)
check("[7] far: a grey pair stays", sorted(low_grey), ["garment_accessory_item_g_c", "garment_accessory_item_g_g"])

# [8] the face slot
from app.models.inventory import VALID_PIECE_SLOTS  # noqa: E402
from app.core import body_slots  # noqa: E402
check("[8] core slot before head", VALID_PIECE_SLOTS.index("face") == VALID_PIECE_SLOTS.index("head") - 1, True)
check("[8] label", body_slots.DEFAULT_PIECE_SLOT_LABELS.get("face"), "Face")
yml = (ROOT / "plugins/human/plugin.yaml").read_text()
check("[8] human topology", "{id: face, label: Face, portrait: true}" in yml, True)
check("[8] human anchor", re.search(r"^\s+face: \[50, 11\]", yml, re.M) is not None, True)
check("[8] play order", '_SLOT_ORDER = ["head", "face", "neck"' in (ROOT / "app/routes/play.py").read_text(), True)
check("[8] outfit prompt", "- face: glasses" in (ROOT / "shared/templates/llm/tasks/outfit_generation.md").read_text(),
      True)
check("[8] keyword fallback", '"face": ["glasses"' in (ROOT / "app/skills/outfit_creation_skill.py").read_text(), True)
for f, pat in (("frontend/src/components/Silhouette.tsx", "  face: 'M "),
               ("frontend/src/components/Silhouette.tsx", "  'head',\n  'face',"),
               ("frontend/src/tabs/characters/WardrobeTab.tsx", "face: [50, 11]"),
               ("packages/player-ui/src/BelongingsPanel.tsx", "face: [50, 11]"),
               ("frontend/src/tabs/items/itemsModel.ts", "  'head',\n  'face',")):
    check(f"[8] client {f}", pat in (ROOT / f).read_text(), True)

print()
print("all checks passed" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
