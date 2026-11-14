#!/usr/bin/env python3
"""The HAAR fit: register, drape, cards, gate after the drape (``app/core/garment_haar.py``,
``strand_register.py``, ``drape.py`` strand mode, ``hair_cards.haar_cards``, ``hair_strands.haar_layout``) —
strand-hair plan 2026-11-13, Task 12 (spec § 6.3.1). Expectations derived by hand below.

Usage: ./.venv/bin/python scripts/smoke_haar_fit.py

No server, no world DB of a real world, no hub: a throwaway storage dir (``paths.init``) holds the fit of the
character ``demo`` for [5]. Outbound connections are refused (``socket.connect``). Taichi runs on the CPU.

Fixture body: Task 4's (``smoke_hair_strands_record.body_fixture``): a head sphere of radius 0.09 m at
(0, 1.60, 0), a neck cylinder r 0.05 from y 1.40 to 1.52, a torso box x ±0.15, y 1.00 .. 1.40, z ±0.08; Head
weighted from y 1.52 up (chin 1.52, crown 1.69), so ``head_frame``: cx = cz = 0, no face profile (a sphere) ->
brow = 1.69 - 0.09 = 1.60, nose = 1.52 + 0.06 = 1.58; head_d = 0.18 -> face plane z0 = 0.25 * 0.18 = 0.045;
face box [-0.06, 0.06, 1.52, 1.61, 0.045]; eye box [-0.04, 0.04, 1.59, 1.605, 0.045]. ``placement_landmarks``
finds no face either -> no hairline tilt.

Template head = the body's sphere scaled 1.1x about the origin and shifted +0.02 m in y: centre
1.1 * 1.60 + 0.02 = 1.78, radius 0.099, one component, tessellated 256 x 128 (the ICP pairs each skin point with
the nearest template VERTEX; on a coarse template those pairs pull the scale down: 64 x 32 recovers 0.8994,
128 x 64 0.9034, 256 x 128 0.9061 — HAAR's FLAME head has 3931 vertices on a smaller cranium). Strands in template space, 128 points
each, 0.30 m long, root on the template sphere: 0.02 m straight out along the sphere normal, then 0.28 m straight
down. 2080 roots on the upper back cap (theta 15..75° from +y, phi 200..340° round y, i.e. behind the head) and 20
at the front hairline (theta 40°, phi 70..110°: in front, the knee at |x| <= 0.119 * sin 40° * cos 70° / 1.1 =
0.024 m and z >= 0.119 * sin 40° * sin 70° / 1.1 = 0.065 m on the body) hanging straight down through the face
region.
Deviation from the plan's "300 strands": the card count is the spike's rule K = min(n_cards, strands // 3) (spec
§ 6.3.1 step 4, ``cards.build``): 300 strands give 100 cards, never the 700 that [3] and [5] check; 2100 = 3 x 700.

Expected (by hand):
  [1] register: the template is the body sphere x 1.1 -> the recovered scale is 1 / 1.1 = 0.90909 (within 0.01;
      the radial skin map reads the sphere 0.3 % small — r 0.08975 m, the voxel field — so about 0.906);
      the registered roots lie on the body sphere, so their distance to the scalp target (the radial skin map
      above the ear line) is the map's own error: p95 < 0.004 m. 2100 strands <= N_STRANDS = 4000: all kept,
      resampled to N_POINTS = 96.
  [2] strand_constraints(2, 4, rest) = stretch (i, i+1) per strand [(0,1),(1,2),(2,3),(4,5),(5,6),(6,7)] kind 0,
      then bend (i, i+2) [(0,2),(1,3),(4,6),(5,7)] and (i, i+3) [(0,3),(4,7)] kind 1; lengths from ``rest``
      (points 0.01 m apart on a line: 0.01 / 0.02 / 0.03). chain_long_range with point 0 of each strand pinned:
      free points 1, 2, 3 -> 0 and 5, 6, 7 -> 4 with their arc 0.01, 0.02, 0.03 (strand 2 bent at a right angle
      after point 5: arc 0.02 at point 6 although the chord is 0.01 * sqrt(2) = 0.01414).
  [3] fit_haar: metrics inside_head_3mm == 0 (the drape keeps 4 mm out of the body; the front strands start
      INSIDE the head sphere — at y 1.60 the sphere's front is at z 0.09, theirs at 0.065 .. 0.070 — and leave it as
      the body grows from inside); eye_cards == 0 (the 20 front strands left the face box by the keep-out and the
      box rule). Settling (H-R13): report.settle has resampled + dropped == stretched, the metrics carry the same
      two counts, and the cards follow the spike's rule on the strands kept: K = min(700, (2100 - dropped) // 3)
      (the fixture's box shoulders stretch some strands where they hang past the box edge — the drop count is the
      drape's, the rule on it is checked); len(V) == K * 34 + cap (report.vertices.cap > 0), and every card's 17 rows
      x 2 vertices are consecutive (card k = vertices [34k, 34k + 34), haar_layout) and run root to tip (UV v 1 at
      its first row, 0 at its last).
  [4] material path: garment.image == strip_atlas(); COLOR_0 of the card vertices == colour_linear (alpha 1) and of
      the scalp layer (H-R12) == colour_linear x SCALP_SHADE 0.6 = (0.18, 0.12, 0.06), alpha 1; the layer on the
      opaque patch (UV == SOLID_UV); report.layout "haar"; no chain joints (joint_parents / joint_binds empty);
      weights Head / Neck / Spine2; report.fit_version == HAAR_FIT_VERSION == 3 (H-R14 changed the cards).
  [5] record_for_fit on the grafted HAAR fit (method "haar", report.vertices from [3]): mode "haar", params ==
      PARAMS["haar"] (root_deg 0), cards == K; the npz binds card k + 1 to vertices [34k, 34k + 34) with u = the row
      (0, 0, 1, 1, …, 16, 16) and the cap 0.
  [6] determinism: a second fit_haar gives the same garment positions, bit for bit.
  [7] the scalp layer alone (``scalp_layer`` on the fixture body, ruling H-R12). The head sphere is 64 x 32: ring i
      at theta = i * 5.625 deg, so ring 7 = 39.375 deg (y 1.60 + 0.09 cos 39.375 = 1.66956), ring 8 = 45 deg
      (y 1.66364). Hand-built roots on the sphere: theta 0 .. 40 deg (step 1), phi step 2 deg, leaving out a
      parting |x| < 8 mm along z. Then:
      - the pole (0, 1.69, 0) is 8 mm from the nearest root (< SCALP_REACH_M 12 mm): the layer bridges the parting
        and holds the pole moved SCALP_OFFSET_M out, (0, 1.6915, 0) (within 1e-5; the pole's normal is radial by
        symmetry);
      - the parting point at theta 20 deg, phi 90 deg (x 0, y 1.68457, z 0.03078) has a layer vertex within 6 mm
        (the sphere's vertex spacing there: 8.8 mm along theta, 3.0 mm round);
      - no layer vertex below the lowest root: the lowest root is at theta 40 deg (y 1.60 + 0.09 cos 40 = 1.66894),
        so a triangle reaching ring 8 (1.66364 < 1.66894 - 0.002) is left out although its centroid is within
        12 mm of the roots (ring 7 .. 8 spans 8.8 mm); the lowest layer vertices are ring 7's, at radius 0.0915:
        y = 1.60 + 0.0915 cos 39.375 = 1.67073 (within 2e-4: vertex normals of a UV sphere are radial to ~1e-3);
      - every layer vertex at radius 0.0915 from (0, 1.60, 0) (within 2e-4).
      Without roots the layer is empty.
  [8] thin cards are smoothed (ruling H-R14), ``hair_cards.haar_cards`` alone on 9 strands of 17 points, rows 20 mm
      apart in y (y_i = 1.60 - 0.02 i), so the 17-row resample keeps every point; a stub field (sample 1 m: no push;
      grad +z). K = min(3, 9 // 3) = 3 clusters, the groups 0.5 m apart:
      - A: 7 copies of a zigzag at x = -0.5 + 0.005 (-1)^i (a card of 7 strands);
      - B: 1 zigzag at x = 0.5 + 0.005 (-1)^i (a card of 1 strand);
      - C: 1 gentle wave at x = 0.001 (-1)^i (a card of 1 strand).
      A zigzag segment is (+-0.01, -0.02): the turn between two of them is acos((-1e-4 + 4e-4) / 5e-4) =
      acos 0.6 = 53.13 deg > HAAR_SHARP_TURN_DEG 45. C's segments (+-0.002, -0.02): acos(3.96e-4 / 4.04e-4) =
      11.42 deg.
      - B is thin and sharp: one pass of [1/4, 1/2, 1/4] puts every interior row on x = 0.5 + 0.005 (1/2 - 1/4 -
        1/4) (-1)^i = 0.5, root and tip stay at 0.505 (i 0 and 16 are even); then the turns are atan(0.005 /
        0.02) = 14.04 deg at rows 1 and 15 and 0 between -> stop after 1 pass. B's centreline x: 0.505, 0.5 x 15,
        0.505; max turn 14.04 deg.
      - A has 7 strands: unchanged, its centreline x = -0.5 + 0.005 (-1)^i, max turn 53.13 deg.
      - C is thin but gentle (11.42 deg <= 45): unchanged, x = 0.001 (-1)^i.
      y stays y_i on every card (the filter of a straight line is the line).
"""
import math
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
CHAR = "demo"
ITEM = "hair_haar"
FSIG = "0123456789ab"
COLOUR = (0.30, 0.20, 0.10)


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _no_net(*_a, **_k):
    raise OSError("smoke: outbound connections are refused")


def template_head():
    from smoke_hair_strands_record import sphere
    V, F = sphere((0, 1.60, 0), 0.09, 256, 128)
    return V * 1.1 + np.array([0.0, 0.02, 0.0]), F


def strand(theta_deg, phi_deg, n=128):
    c = np.array([0.0, 1.78, 0.0])
    th, ph = math.radians(theta_deg), math.radians(phi_deg)
    d = np.array([math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)])
    root = c + 0.099 * d
    knee = root + 0.02 * d
    s = np.linspace(0.0, 0.30, n)
    out = np.where(s[:, None] <= 0.02, root + s[:, None] * d, knee + (s[:, None] - 0.02) * np.array([0, -1.0, 0]))
    return out


def strands():
    rng = np.random.default_rng(3)
    back = [strand(rng.uniform(15, 75), rng.uniform(200, 340)) for _ in range(2080)]
    front = [strand(40.0, 70 + 40 * i / 19) for i in range(20)]
    return np.asarray(back + front, np.float32)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_haar_fit_"))
    try:
        return run_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(tmp):
    socket.socket.connect = _no_net
    socket.create_connection = _no_net
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    from app.core import db
    db.init_schema()
    from smoke_hair_strands_record import body_fixture
    from app.core import drape, garment_haar, hair_cards, hair_strands as hs, strand_register
    from app.core.glb_mesh import body_arrays
    from app.models.character import get_character_dir
    get_character_dir(CHAR, create=True)
    glb = body_fixture()
    body = body_arrays(glb)
    TV, TF = template_head()
    S = strands()

    # [1] register
    X, info = strand_register.register(S, TV, body, template_faces=TF)
    check(abs(info["scale"] - 1 / 1.1) < 0.01, f"[1] scale {info['scale']} within 0.01 of 0.90909")
    check(info["root_resid_p95_m"] < 0.004, f"[1] root residual p95 {info['root_resid_p95_m']} < 0.004 m")
    check(X.shape == (2100, 96, 3), f"[1] 2100 strands of 96 points (got {X.shape})")
    check(info["hairline_tilt_deg"] == 0.0 and info["landmarks"] == "none", f"[1] no face, no tilt ({info['landmarks']})")

    # [2] strand constraints and the chain tether
    rest = np.zeros((8, 3))
    rest[:4, 0] = [0, 0.01, 0.02, 0.03]
    rest[4:, :] = [[0, 0, 1], [0.01, 0, 1], [0.01, 0.01, 1], [0.01, 0.02, 1]]
    pairs, lengths, kind = drape.strand_constraints(2, 4, rest)
    want = [(0, 1), (1, 2), (2, 3), (4, 5), (5, 6), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 3), (4, 7)]
    check([tuple(p) for p in pairs.tolist()] == want, f"[2] pairs {pairs.tolist()}")
    check(kind.tolist() == [0] * 6 + [1] * 6, f"[2] kinds {kind.tolist()}")
    check(np.allclose(lengths[:3], 0.01) and np.allclose(lengths[6:8], 0.02) and np.isclose(lengths[10], 0.03),
          f"[2] lengths {np.round(lengths, 5).tolist()}")
    pinned = np.zeros(8, bool)
    pinned[[0, 4]] = True
    li, lp, ll = drape.chain_long_range(rest, pinned, np.repeat([0, 1], 4))
    check(li.tolist() == [1, 2, 3, 5, 6, 7] and lp.tolist() == [0, 0, 0, 4, 4, 4], f"[2] tethers {li} -> {lp}")
    check(np.allclose(ll, [0.01, 0.02, 0.03, 0.01, 0.02, 0.03]), f"[2] tether arcs {np.round(ll, 5).tolist()}")

    # [3] the fit
    t0 = time.time()
    r = garment_haar.fit_haar(S, TV, glb, colour_linear=COLOUR, length_class="medium", template_faces=TF)
    print(f"     fit_haar {time.time() - t0:.1f} s, timing {r.report['timing_s']}")
    m = r.metrics
    print(f"     metrics {m}")
    check(m["inside_head_3mm"] == 0, f"[3] inside_head_3mm == 0 (got {m['inside_head_3mm']})")
    check(m["eye_cards"] == 0, f"[3] eye_cards == 0 (got {m['eye_cards']})")
    nv = r.report["vertices"]
    g = r.garment
    st = r.report["settle"]
    check(st["resampled"] + st["dropped"] == st["stretched"] and m["stretched_resampled"] == st["resampled"]
          and m["stretched_dropped"] == st["dropped"] and m["strands"] == 2100 - st["dropped"],
          f"[3] settle {st}: resampled + dropped == stretched, metrics carry them, strands {m['strands']}")
    K = min(700, (2100 - st["dropped"]) // 3)
    check(m["cards"] == K and nv["hair"] == K * 34 and nv["cap"] > 0
          and len(g.positions) == K * 34 + nv["cap"],
          f"[3] {K} cards: {len(g.positions)} vertices == {K} * 34 + {nv['cap']}")
    F = np.asarray(g.indices).reshape(-1, 3)
    hair_f = F[(F < nv["hair"]).all(1)]
    one_card = (hair_f // 34 == (hair_f // 34)[:, :1]).all()
    v = np.asarray(g.uvs)[:nv["hair"], 1].reshape(K, 17, 2)
    check(bool(one_card) and len(hair_f) == K * 32, f"[3] every hair face within one card's 34 vertices "
          f"({len(hair_f)} faces)")
    check(np.allclose(v[:, 0], 1.0) and np.allclose(v[:, -1], 0.0) and (np.diff(v[:, :, 0], axis=1) < 0).all(),
          "[3] rows root (v 1) to tip (v 0)")
    lay = hs.haar_layout(g.positions, nv["hair"])
    check(lay.centrelines.shape == (K, 17, 3) and lay.card[nv["hair"]:].tolist() == [-1] * nv["cap"],
          f"[3] haar_layout: {K} cards of 17 rows, the cap rigid")

    # [4] material
    check(g.image == hair_cards.strip_atlas() and g.mime == "image/png", "[4] garment.image == strip_atlas()")
    C = np.asarray(g.colors)
    check(np.array_equal(C[:nv["hair"], :3], np.tile(COLOUR, (nv["hair"], 1))) and (C[:, 3] == 1).all(),
          "[4] COLOR_0 of the cards == colour_linear, alpha 1")
    check(garment_haar.SCALP_SHADE == 0.6 and np.allclose(C[nv["hair"]:, :3], [0.18, 0.12, 0.06], atol=1e-12),
          f"[4] COLOR_0 of the scalp layer == colour x 0.6 = (0.18, 0.12, 0.06) (got {C[nv['hair'], :3]})")
    check(np.allclose(np.asarray(g.uvs)[nv["hair"]:], hair_cards.SOLID_UV), "[4] the layer on the opaque patch")
    check(garment_haar.HAAR_FIT_VERSION == 3 and r.report["fit_version"] == 3, "[4] fit_version 3")
    check(r.report["layout"] == "haar" and not g.joint_parents and not g.joint_binds,
          "[4] layout haar, no chain joints")
    check([n.split(":")[-1] for n in g.joint_names] == ["Head", "Neck", "Spine2"], f"[4] joints {g.joint_names}")

    # [5] the record of the grafted fit
    from app.core import garment_store as gs, refit_pool
    fit = gs.garment_path(CHAR, ITEM, FSIG, "fit")
    fit.parent.mkdir(parents=True, exist_ok=True)
    refit_pool.graft_file(glb, g, f"garment_hair_{ITEM}", {"kind": "hair", "item_id": ITEM, "fsig": FSIG}, str(fit),
                          material_overrides=hair_cards.alpha_overrides())
    gs.write_record(fit.with_suffix(".json"), {"accepted": True, "kind": "hair", "item_id": ITEM, "fsig": FSIG,
                                               "method": "haar", "report": {"vertices": nv}})
    record = hs.record_for_fit(CHAR, fit)
    check(record is not None and record["mode"] == "haar", "[5] record_for_fit: mode haar")
    if record is not None:
        check(record["params"] == hs.PARAMS["haar"] and record["params"]["root_deg"] == 0, "[5] params PARAMS['haar']")
        check(record["cards"] == K, f"[5] cards == {K} (got {record['cards']})")
        arrays = hs.vertex_arrays(fit)
        want_card = np.r_[np.repeat(np.arange(K) + 1, 34), np.zeros(nv["cap"])]
        want_u = np.r_[np.tile(np.repeat(np.arange(17), 2), K), np.zeros(nv["cap"])]
        check(arrays is not None and np.array_equal(arrays["card"], want_card)
              and np.array_equal(arrays["u"], want_u), "[5] npz binding: card k + 1, u = row, cap 0")

    # [6] determinism
    r2 = garment_haar.fit_haar(S, TV, glb, colour_linear=COLOUR, length_class="medium", template_faces=TF)
    check(np.array_equal(np.asarray(r.garment.positions), np.asarray(r2.garment.positions)),
          "[6] a second fit gives the same positions, bit for bit")

    # [7] the scalp layer alone
    B = strand_register.body_frame(body)
    roots = []
    for th in range(0, 41):
        for ph in range(0, 360, 2):
            t, p = math.radians(th), math.radians(ph)
            q = (0.09 * math.sin(t) * math.cos(p), 1.60 + 0.09 * math.cos(t), 0.09 * math.sin(t) * math.sin(p))
            if abs(q[0]) >= 0.008:
                roots.append(q)
    roots = np.asarray(roots)
    LV, LF, _, info = garment_haar.scalp_layer(body, B["head_w_col"], roots, B["sdf"])
    print(f"     layer {info}, roots {len(roots)}")
    pole = np.linalg.norm(LV - [0.0, 1.6915, 0.0], axis=1).min()
    check(pole < 1e-5, f"[7] the pole bridged, moved 1.5 mm out: (0, 1.6915, 0) within 1e-5 (off {pole:.2e})")
    t = math.radians(20)
    q = np.array([0.0, 1.60 + 0.09 * math.cos(t), 0.09 * math.sin(t)])
    near = np.linalg.norm(LV - q, axis=1).min()
    check(near < 0.006, f"[7] the parting point at theta 20 deg has a layer vertex within 6 mm ({near * 1000:.2f} mm)")
    low = LV[:, 1].min()
    want_low = 1.60 + 0.0915 * math.cos(math.radians(39.375))
    check(abs(low - want_low) < 2e-4, f"[7] the lowest layer vertex is ring 7's: y {low:.5f} ~ {want_low:.5f}")
    rad = np.linalg.norm(LV - [0.0, 1.60, 0.0], axis=1)
    check(np.abs(rad - 0.0915).max() < 2e-4, f"[7] every layer vertex at radius 0.0915 (max off "
          f"{np.abs(rad - 0.0915).max():.2e})")
    E = garment_haar.scalp_layer(body, B["head_w_col"], np.zeros((0, 3)), B["sdf"])
    check(len(E[0]) == 0 and len(E[1]) == 0, "[7] no roots: no layer")

    # [8] thin cards smoothed (H-R14)
    check_thin_cards(hair_cards)

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


class _FlatField:
    """A stub body field for [8]: far from everything (no clearance push), the outward normal +z."""

    @staticmethod
    def sample(P):
        return np.ones(len(np.atleast_2d(P)))

    @staticmethod
    def grad(P):
        return np.tile([0.0, 0.0, 1.0], (len(np.atleast_2d(P)), 1))


def check_thin_cards(hair_cards):
    i = np.arange(17)
    alt = (-1.0) ** i

    def line(x):
        return np.stack([x, 1.60 - 0.02 * i, np.zeros(17)], 1)

    S = np.asarray([line(-0.5 + 0.005 * alt)] * 7 + [line(0.5 + 0.005 * alt), line(0.001 * alt)])
    V, _F, _UV, card = hair_cards.haar_cards(S, _FlatField(), n_cards=3, n_seg=16)
    check(int(card.max()) + 1 == 3 and len(V) == 3 * 34, f"[8] 3 cards of 34 vertices (got {int(card.max()) + 1})")
    C = {}
    for k in range(int(card.max()) + 1):
        c = V[card == k].reshape(17, 2, 3).mean(1)
        C[{-1: "A", 0: "C", 1: "B"}[int(round(c[:, 0].mean() * 2))]] = c
    if set(C) != {"A", "B", "C"}:
        check(False, f"[8] the three groups as cards (got {sorted(C)})")
        return
    want_b = np.r_[0.505, np.full(15, 0.5), 0.505]
    tb = hair_cards.turn_deg(C["B"]).max()
    check(np.allclose(C["B"][:, 0], want_b, atol=1e-9) and abs(tb - 14.036) < 0.01,
          f"[8] B (1 strand, 53.13 deg) smoothed: x {np.round(C['B'][:, 0], 4).tolist()}, max turn {tb:.2f} ~ 14.04")
    ta = hair_cards.turn_deg(C["A"]).max()
    check(np.allclose(C["A"][:, 0], -0.5 + 0.005 * alt, atol=1e-9) and abs(ta - 53.130) < 0.01,
          f"[8] A (7 strands) kept: max turn {ta:.2f} ~ 53.13")
    tc = hair_cards.turn_deg(C["C"]).max()
    check(np.allclose(C["C"][:, 0], 0.001 * alt, atol=1e-9) and abs(tc - 11.421) < 0.01,
          f"[8] C (1 strand, gentle) kept: max turn {tc:.2f} ~ 11.42")
    check(all(np.allclose(c[:, 1], 1.60 - 0.02 * i, atol=1e-9) for c in C.values()), "[8] y stays y_i on every card")
    check(hair_cards.smooth_thin(line(0.5 + 0.005 * alt), 1)[1] == 1, "[8] B took exactly 1 pass")


if __name__ == "__main__":
    sys.exit(main())
