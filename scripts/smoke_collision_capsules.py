#!/usr/bin/env python3
"""Smoke: collision capsules — fitting, the stored record, inheritance and the model overview step
(app/core/collision.py, model3d._auto_collision, model_overview).

Usage:
    ./.venv/bin/python scripts/smoke_collision_capsules.py

Runs without the server, against a temp storage dir; no world DB, no Blender.

FIXTURE — a synthetic skinned GLB (``make_body``): Mixamo joints (``mixamorig:`` prefix, flat hierarchy, node
translation = bind position, inverse bind matrix = translation by its negative), one body mesh whose every
vertex is weighted 1.0 to ONE joint:
  legs   LeftUpLeg (0.1, 0.95, 0) → LeftLeg (0.1, 0.5, 0) → LeftFoot (0.1, 0.08, 0), right mirrored in x;
         LeftToeBase (0.1, 0.02, 0.12), RightToeBase (−0.1, 0.02, 0.12) (no vertices; with the feet they give the
         outer rule's front);
         rings of radius 0.06 around UpLeg→Leg (weighted UpLeg) and Leg→Foot (weighted Leg);
  arms   LeftArm (0.2, 1.45, 0) → LeftForeArm (0.5, 1.45, 0) → LeftHand (0.75, 1.45, 0), right mirrored;
         rings of radius 0.04 around Arm→ForeArm (weighted Arm) and ForeArm→Hand (weighted ForeArm);
  shoulders LeftShoulder (0.05, 1.45, 0) → LeftArm, right mirrored; a ring of radius 0.05 (weighted Shoulder);
  torso  Hips (0, 1.0, 0) → Spine1 (0, 1.2, 0) → Spine2 (0, 1.35, 0) → Neck (0, 1.5, 0); ELLIPSE rings
         x = 0.12 cos θ, z = 0.10 sin θ around each segment, weighted to its start bone (``torso_shift``
         moves the rings' centres by that much along z, the joints stay);
  head   Head (0, 1.6, 0), HeadTop_End (0, 1.8, 0); a capsule SURFACE of radius 0.09 around 1.6..1.8 (rings
         + two hemispheres of 10 rows × 72, polar angle φ = 0.1..π/2), weighted Head ("head sphere 0.09").
Each ring: 720 evenly spaced θ at 9 stations t = 0.1..0.9 of the segment (all strictly inside, so the distance
to the segment is the distance to the axis); the torso's ellipse rings at a station every 5 mm instead, from 2.5 mm
in (s = 0.0025, 0.0075, … < L — two in every 1-cm slice of the outer rule's profile; the distances are the same).

Expected, derived by hand:
[1] fit_capsules on the full body: 18 capsules (14 + the 4 outer; the current ``collision.VERSION``), nothing
    skipped.
    A uniform ring has ONE distance, so every quantile = its radius:
      legs  0.060 + 6 mm = 0.066 (left/right thigh, left/right shin)
      arms  0.040 + 6 mm = 0.046 (left/right upper arm, left/right forearm)
      shoulders (hair only) 0.050 + 6 mm = 0.056 (left/right_shoulder_hair, a LeftShoulder, b LeftArm, region
            shoulder_hair)
      head  crown rule (a = b = Head, b_pos): body axis u = Hips→Head = +y; crown = the highest Head vertex =
            the top row φ = 0.1 of the upper hemisphere: 1.8 + 0.09·cos 0.1 = 1.889550; distances to
            Head→crown: rings (6480) and the lower hemisphere (720, all below Head → distance to Head) are 0.09,
            the upper hemisphere (720) is 0.09·sin φ ≤ 0.09 → p50 = 0.090; b_pos = crown − r·u =
            (0, 1.889550 − 0.09, 0) = (0, 1.7996, 0) — the synthetic capsule's own end, recovered.
    The ellipse ring: d(θ)² = b² + (a² − b²)·cos²θ, a = 0.12, b = 0.10. For θ uniform, P(cos²θ ≤ c) =
    1 − (2/π)·arccos(√c), so the q-quantile is d_q = sqrt(b² + (a² − b²)·sin²(qπ/2)):
      hips  q = 0.02: sin²(0.01π) = 0.000987 → sqrt(0.0100 + 0.0044·0.000987) = 0.10002 → 0.1000
      spine q = 0.10: sin²(0.05π) = 0.024472 → sqrt(0.0100 + 0.0044·0.024472) = 0.10054 → 0.1005
      chest q = 0.10: same → 0.1005
    (p95 would give sqrt(0.0100 + 0.0044·0.99384) = 0.1199 — the table's torso quantile is what is checked.)
    OUTER (end rules "outer" / "outer_capped", region outer_trunk, q 0.25, margin 0): axis e = +y; the two
      (toe − foot) = (±0, −0.06, 0.12) sum to (0, −0.12, 0.24), across e (0, 0, 0.24) → front f = +z, lateral = x.
      Only the torso rings lie in the trunk's slices with |x| < 10 cm (legs below Hips, arms beyond |x| 0.2, the
      shoulder rings at |x| ≥ 0.065 only above y 1.40 with |z| ≤ 0.05 — never the extreme); the midline (|x| < 2 cm)
      of every 1-cm slice holds the ellipse's θ within 9.6° of ±90° (about 76 per station ≥ 4), whose z reaches
      ±0.10 exactly (θ = 90° and 270° are on the grid). So every centre is 0 and every need n = 0.10 (z ± 0.10
      around 0); a ring has one need, so the quantile is 0.10 → r = 0.10 on all four:
        outer_hips  a Hips, b Spine1, part [0, 0.5]: a_pos (0, 1.0, 0), b_pos (0, 1.1, 0);
        outer_waist a Hips, b Spine1, part [0.5, 1]: a_pos (0, 1.1, 0), b_pos (0, 1.2, 0);
        outer_spine Spine1 → Spine2: a_pos (0, 1.2, 0), b_pos (0, 1.35, 0);
        outer_chest Spine2 → Neck, capped: L = 0.15, slices s = 0.005 … 0.145 (15), t = 0.15 − s; for s ≤ 0.045
          t ≥ 0.105 ≥ n → 0.10 (five slices); s = 0.055 → (0.01 + 0.095²)/0.19 = 0.100132, rising to 1.0025 at
          s = 0.145; the 0.25-quantile sits at index 3.5 of the 15 sorted → between two 0.10 → r = 0.10;
          b_pos moves back to r below Neck: (0, 1.35 + 0.15·(1 − 0.10/0.15), 0) = (0, 1.40, 0) — the top cap ends
          at Neck (1.50).
    Tolerance 0.3 mm (discrete θ, 0.1-mm rounding). Joint names come back as in the model ("mixamorig:…").
[2] Without HeadTop_End: still 18 capsules, the head identical (the crown rule needs no crown joint). Without
    Head: head skipped "joint Head missing". Without LeftFoot: left_shin and the four outer capsules skipped
    "joint LeftFoot missing" (the outer rule's front needs it), everything else unchanged — no crash.
[3] Region scale 1.2 everywhere → every radius × 1.2 (thigh 0.0792, upper arm 0.0552, hips 0.1200, spine
    0.1206, shoulder 0.0672, head 0.1080 with b_pos y = 1.889550 − 0.108 = 1.7816, outer 0.10·1.2 = 0.12,
    ±0.4 mm); {"leg": 1.2} alone → legs 0.0792, arms stay 0.046; {"outer_trunk": 1.2} alone → the four outer
    radii 0.12, their a_pos and the hips/waist/spine b_pos unchanged (the centre is not scaled), outer_chest b_pos
    keeps its cap at Neck: y = 1.35 + 0.15·(1 − 0.12/0.15) = 1.38; every other radius unchanged. validate_scales refuses
    0.4, 1.6, "x", an unknown region; fills missing regions with 1.0.
[4] A grafted garment node (``garment_dress_x``, a ring of radius 0.30 weighted LeftUpLeg) changes nothing:
    left_thigh stays 0.066 (body_arrays skips garment nodes).
[5] The stored record (``collision.ensure_path`` on <tmp>/model3d/<sig>.glb + sidecar, scales passed in):
    own model → record {current version, source own, sha256 = sha of the file, scales = defaults, 18 capsules},
    written into the
    sidecar; a second call fits nothing (fit counter unchanged); new file bytes (no LeftFoot: 18 − left_shin −
    4 outer = 13 capsules) → refitted (counter +1).
    Outfit (sidecar source "base_body", base_signature B, base_model_sha256 S) carrying the base record
    (source own, sha256 S) → current, relabelled {source base, base_signature B}, NOT refitted.
    The same outfit with base_model_sha256 S2 (built on another base) → refitted on its own file, record
    sha256 S2 / source base (Review Focus 1: the set follows the base it was built on, never a stale copy).
    Changed scales → refitted. rig "generic" → None, nothing written. A file that is not a GLB body →
    record with ``error`` and no capsules, stored (not refitted on the next call).
[6] model3d._auto_collision(…) = the post-rig step: called by _auto_extension_rig; a base model's meta gets
    the record (source own); the result's ``noop`` stays the extension rig's answer (True here — a no-op
    rebuild publishes no sidecar; the next ensure_path stores the set).
[7] model_overview: base_model_steps / outfit_model_steps carry a "collision" row after extension_rig:
      record with 18 capsules → done "18 capsules · leg 6.6 cm · arm 4.6 cm · torso 10.0–10.1 cm · head
      9.0 cm · shoulder_hair 5.6 cm · outer_trunk 10.0 cm", numbers count 18; on the outfit "… · from the base
      model"; none → missing "Not computed"; error → failed with the error; skipped capsules → warning "13 capsules
      · … · skipped left_shin (joint LeftFoot missing), outer_hips (joint LeftFoot missing), outer_waist …, …".
[8] Extension capsules (collision v2, ``EXTENSION_CAPSULES``; generic joint names, no package needed):
    BUMP — op ``pair_protrusion`` (p50, margin 0, region chest), one-link chain [TestBump], joint H = (0, 1.30,
      0.05); its own vertices = a Fibonacci sphere of N = 4000 points, radius R = 0.05 around c = (0, 1.30, 0.10)
      (z_i = 1 − (2i+1)/N: the axial coordinate is uniform). Axis u = H → centroid = +z. Tip = the mean of the top
      1 % along u = the cap z ≥ 0.98 R, mean 0.99 R → tip = (0, 1.30, 0.1495), height |tip − H| = 0.0995. A point at
      z = R·ζ lies R·sqrt(1 − ζ²) from the axis (ζ ≤ 0.99, inside the segment; the 0.5 % beyond it are nearer
      still), and sqrt(1 − ζ²) ≤ sqrt(0.75) ⇔ |ζ| ≥ 0.5 — half the points → p50 = R·sqrt(0.75) = 0.043301.
      a = b = TestBump, b_pos = H + u·(0.0995 − 0.043301) = (0, 1.30, 0.106199), region chest.
    PART — op ``attached_part`` (p75, margin 0, region attached_part), chain [TestPart1, TestPart2] in a SECOND
      node marked ``extras.attached_part`` (an attached part's own mesh — ``body_arrays`` leaves it out, the fit
      must not): TestPart1 (0, 0.9, 0.12) → TestPart2 (0, 0.9, 0.22), a ring r 0.03 around it weighted TestPart1
      → capsule a TestPart1, b TestPart2 (the next link's joint), r = 0.030 (a ring has one distance); TestPart2
      = the last link: a ring r 0.025 around (0, 0.9, 0.22) → (0, 0.9, 0.30) weighted TestPart2; axis = the
      previous joint → TestPart2 = +z; the top 1 % are ties of the top station z = 0.292 → tip (0, 0.9, 0.292),
      height 0.072, r = 0.025, b_pos = (0, 0.9, 0.22 + 0.072 − 0.025) = (0, 0.9, 0.267).
    BUMP HAIR — the same op's second entry (``chest_hair``, p95, margin HAIR_CLEARANCE_M = 0.006): the share of
      the points with distance > R·x is the share with |ζ| < sqrt(1 − x²) = 0.05 → x = sqrt(1 − 0.05²) = 0.998749,
      p95 = 0.049937; r = 0.049937 + 0.006 = 0.055937; the cap ends at the tip pushed out by the margin:
      b_pos = H + u·(0.0995 + 0.006 − 0.055937) = (0, 1.30, 0.099563); id "bump:testbump:chest_hair".
    The table's capsules are unchanged but ``outer_spine``: the outer rule reads EVERY body vertex, and the bump is
    body mesh inside the Spine1 → Spine2 slices reaching z 0.15 > 0.10, so outer_spine grows (only checked as
    larger — the sphere's slices move the end centre as well).
    Payload order: the 18 table capsules, then BUMP, BUMP HAIR, PART1, PART2 (ids "<group>:<normalised bone>").
    No group (``extension`` None / only an op outside the table, e.g. ``pair_tip``) → the 18 capsules only.
    Scale chest 1.2 → BUMP r = 0.051962, b_pos z = 0.05 + 0.0995 − 0.051962 = 0.097538; BUMP HAIR and PART
    unchanged. Scale chest_hair 1.2 → BUMP HAIR r = 0.067125, b_pos z = 0.05 + 0.0995 + 0.0072 − 0.067125
    = 0.089575; BUMP unchanged. HAIR_CLEARANCE_M = garment_fit.HAIR_CLEAR_M.
    A chain joint the model lacks → skipped "joint … missing".
    ``extension_chains(meta)``: status "applied", groups [bump, tip], ops {bump: pair_protrusion, tip: pair_tip}
    → [{group bump, op pair_protrusion, chains from the declaration}]; status "failed" → []; no record → [].
[9] APPENDAGE (collision v5): op ``appendage_chain`` (region appendage, margin 0), chain [TestApp1, TestApp2] IN
    THE BODY NODE (a part the generator drew itself is body mesh, weighted to the chain): TestApp1 (0, 0.9, 0.12) →
    TestApp2 (0, 0.9, 0.22), a ring r 0.03 around it weighted TestApp1; a ring r 0.025 around (0, 0.9, 0.22) →
    (0, 0.9, 0.30) weighted TestApp2. A ring has ONE distance, so every quantile equals its radius:
      app:testapp1 — a TestApp1, b TestApp2 (the next link's joint), no b_pos, r 0.030, region appendage;
      app:testapp2 — the tip rule as PART2 of [8]: axis TestApp1 → TestApp2 = +z, the top 1 % are ties of the top
        station z = 0.292 → tip (0, 0.9, 0.292), height 0.072, r 0.025, b_pos (0, 0.9, 0.22 + 0.072 − 0.025) =
        (0, 0.9, 0.267), a = b = TestApp2.
    Scale appendage 1.2 → r 0.036 and 0.030; b_pos z = 0.22 + 0.072 − 0.030 = 0.262. Scale attached_part 1.2 → both
    unchanged (the region is the op's own). The payload version is ``collision.VERSION`` ≥ 5 (v5 brought the
    region; a later bump keeps it). ``validate_scales`` knows ``appendage``. ``extension_chains`` keeps a group of
    op appendage_chain.
[10] OUTER RULE (collision v6), ``torso_shift`` 0.03: the rings' centres at z = +0.03, the joints unchanged. Every
    slice's front/back is 0.03 ± 0.10 → every centre c = 0.03, every need 0.10 → r = 0.10 (the chest as in [1]);
    the axis runs through the centres: outer_hips a_pos (0, 1.0, 0.03), outer_waist a_pos (0, 1.1, 0.03),
    outer_spine a_pos = Spine1 + c·f = (0, 1.2, 0.03), b_pos (0, 1.35, 0.03), outer_chest b_pos (0, 1.40, 0.03).
    The table's inside-skin torso capsules keep their joints (no positions). Without LeftToeBase: the four outer
    capsules skipped "joint LeftToeBase missing", the 14 others fitted. Front follows the feet: both toes moved to
    z = −0.12 → f = −z, z = −(0.03 + …) → c = −0.03 along −z, so a_pos is again (0, 1.2, 0.03) (the same physical
    point). Toe-out cancels: LeftToeBase (0.15, 0.02, 0.12), RightToeBase (−0.15, 0.02, 0.12) → the sum (0, −0.12,
    0.24), f = +z exactly → r 0.10, outer_spine a_pos (0, 1.2, 0.03) unchanged. Both feet count: only LeftToeBase at
    z = −0.12 → the sum (0, −0.12, 0) lies along e → the four outer capsules skipped "no front direction".
[11] BIND POSE (the admin viewer's partner probe, cross-person Task 8): ``bind_pose_capsules(body, fit)`` on the full
    fixture gives the 18 table capsules in payload order, each {id, region, a, b, r}. An endpoint without a position is
    its joint's bind position = the negated translation of its inverse bind matrix = the node translation:
    left_thigh a = LeftUpLeg (0.1, 0.95, 0), b = LeftLeg (0.1, 0.5, 0), r = the fit's 0.066; head a = Head
    (0, 1.6, 0), b = its b_pos (0, 1.7996, 0) as given ([1]); outer_spine a / b = its a_pos / b_pos (0, 1.2, 0) /
    (0, 1.35, 0). A capsule whose joint the file lacks is left out: the same record on the body without LeftFoot →
    17 (left_shin gone, the outer four keep their joints Hips … Neck — only the FIT's front rule needed that joint).
    The route ``GET /characters/{c}/model3d/collision/bind-pose`` (the real characters router, the gate and the
    stubbed session of ``smoke_auth_gate.py``; the served model is <tmp>/characters/Mara/model3d/sig1.glb with the fit
    in its sidecar — ``find_model3d_serving`` stubbed to it, there is no world DB): a player → 403 (its
    require_admin; ``model3d`` is a public character segment, so the gate lets it through), an admin → 200
    {signature "sig1", capsules = bind_pose_capsules}, the sidecar unchanged byte for byte (no write); a sidecar
    without ``collision`` → 404.
"""
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
#: The table's capsules on the full fixture: 14 (leg, arm, torso, head, shoulder_hair) + 4 outer_trunk.
TABLE = 18
OUTER = ["outer_hips", "outer_waist", "outer_spine", "outer_chest"]


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(f"  {'ok ' if ok else 'FAIL'} {label}: {got} ≈ {want} (±{tol})")
    if not ok:
        FAILS.append(label)


JOINTS = {
    "Hips": (0, 1.0, 0), "Spine1": (0, 1.2, 0), "Spine2": (0, 1.35, 0), "Neck": (0, 1.5, 0),
    "Head": (0, 1.6, 0), "HeadTop_End": (0, 1.8, 0),
    "LeftUpLeg": (0.1, 0.95, 0), "LeftLeg": (0.1, 0.5, 0), "LeftFoot": (0.1, 0.08, 0), "LeftToeBase": (0.1, 0.02, 0.12),
    "RightUpLeg": (-0.1, 0.95, 0), "RightLeg": (-0.1, 0.5, 0), "RightFoot": (-0.1, 0.08, 0),
    "RightToeBase": (-0.1, 0.02, 0.12),
    "LeftShoulder": (0.05, 1.45, 0), "RightShoulder": (-0.05, 1.45, 0),
    "LeftArm": (0.2, 1.45, 0), "LeftForeArm": (0.5, 1.45, 0), "LeftHand": (0.75, 1.45, 0),
    "RightArm": (-0.2, 1.45, 0), "RightForeArm": (-0.5, 1.45, 0), "RightHand": (-0.75, 1.45, 0),
}
N_THETA, STATIONS = 720, np.linspace(0.1, 0.9, 9)


def ring(a, b, rx, rz=None, stations=None):
    """Points around segment a→b: the axis is y (vertical segments) or x (arms)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    th = np.arange(N_THETA) * 2 * np.pi / N_THETA
    rz = rx if rz is None else rz
    out = []
    for t in STATIONS if stations is None else stations:
        c = a + t * (b - a)
        if abs(b[0] - a[0]) > abs(b[1] - a[1]):   # along x: circle in y/z
            out.append(np.stack([np.full_like(th, c[0]), c[1] + rx * np.cos(th), c[2] + rz * np.sin(th)], 1))
        else:                                     # along y: circle/ellipse in x/z
            out.append(np.stack([c[0] + rx * np.cos(th), np.full_like(th, c[1]), c[2] + rz * np.sin(th)], 1))
    return np.concatenate(out)


def ring_z(a, b, r):
    """Rings of radius r around a segment along z (circle in x/y), at the usual stations."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    th = np.arange(N_THETA) * 2 * np.pi / N_THETA
    out = []
    for t in STATIONS:
        c = a + t * (b - a)
        out.append(np.stack([c[0] + r * np.cos(th), c[1] + r * np.sin(th), np.full_like(th, c[2])], 1))
    return np.concatenate(out)


def head_surface(a, b, r):
    a, b = np.asarray(a, float), np.asarray(b, float)
    pts = [ring(a, b, r)]
    th = np.arange(72) * 2 * np.pi / 72
    for phi in np.linspace(0.1, np.pi / 2, 10):      # hemispheres: below a, above b
        s, c = math.sin(phi), math.cos(phi)
        pts.append(np.stack([r * s * np.cos(th), a[1] - r * c + 0 * th, r * s * np.sin(th)], 1))
        pts.append(np.stack([r * s * np.cos(th), b[1] + r * c + 0 * th, r * s * np.sin(th)], 1))
    return np.concatenate(pts)


def body_parts(joints, torso_shift=0.0):
    parts = []
    for side in ("Left", "Right"):
        parts.append((f"{side}UpLeg", ring(JOINTS[f"{side}UpLeg"], JOINTS[f"{side}Leg"], 0.06)))
        parts.append((f"{side}Leg", ring(JOINTS[f"{side}Leg"], JOINTS[f"{side}Foot"], 0.06)))
        parts.append((f"{side}Arm", ring(JOINTS[f"{side}Arm"], JOINTS[f"{side}ForeArm"], 0.04)))
        parts.append((f"{side}ForeArm", ring(JOINTS[f"{side}ForeArm"], JOINTS[f"{side}Hand"], 0.04)))
        parts.append((f"{side}Shoulder", ring(JOINTS[f"{side}Shoulder"], JOINTS[f"{side}Arm"], 0.05)))
    for a, b in (("Hips", "Spine1"), ("Spine1", "Spine2"), ("Spine2", "Neck")):
        shift = np.array([0.0, 0.0, torso_shift])
        length = float(np.linalg.norm(np.subtract(JOINTS[b], JOINTS[a])))
        stations = np.arange(0.0025, length, 0.005) / length     # every 5 mm, from 2.5 mm in
        parts.append((a, ring(np.add(JOINTS[a], shift), np.add(JOINTS[b], shift), 0.12, 0.10, stations)))
    parts.append(("Head", head_surface(JOINTS["Head"], JOINTS["HeadTop_End"], 0.09)))
    return [(j, p) for j, p in parts if j in joints]


def make_body(*, drop=(), garment=False, extra_joints=None, extra_parts=(), part_parts=(), torso_shift=0.0):
    """``extra_joints`` {name: position} join the skin; ``extra_parts`` [(joint, points)] join the body mesh,
    ``part_parts`` form a second skinned node marked ``extras.attached_part`` (an attached part's own node)."""
    from app.core.glb_mesh import pack_glb
    joints = {**JOINTS, **(extra_joints or {})}
    names = [n for n in joints if n not in drop]
    blob = bytearray()
    accessors, views = [], []

    def add(array, comp, typ, target=None):
        data = np.ascontiguousarray(array).tobytes()
        while len(blob) % 4:
            blob.append(0)
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": len(array), "type": typ}
        if typ == "VEC3" and comp == 5126:
            acc["min"] = np.asarray(array).min(0).tolist()
            acc["max"] = np.asarray(array).max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    def primitive(parts):
        pos = np.concatenate([p for _, p in parts]).astype("<f4")
        jnt = np.zeros((len(pos), 4), "<u2")
        wgt = np.zeros((len(pos), 4), "<f4")
        wgt[:, 0] = 1.0
        offset = 0
        for joint, p in parts:
            jnt[offset:offset + len(p), 0] = names.index(joint)
            offset += len(p)
        idx = np.arange(len(pos), dtype="<u4")
        idx = np.concatenate([idx, np.zeros(-len(idx) % 3, "<u4")])
        return {"attributes": {"POSITION": add(pos, 5126, "VEC3", 34962), "JOINTS_0": add(jnt, 5123, "VEC4", 34962),
                               "WEIGHTS_0": add(wgt, 5126, "VEC4", 34962)},
                "indices": add(idx, 5125, "SCALAR", 34963)}

    nodes = [{"name": f"mixamorig:{n}", "translation": list(map(float, joints[n]))} for n in names]
    ibm = np.stack([np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [-x, -y, -z, 1]], "<f4")
                    for x, y, z in (joints[n] for n in names)]).reshape(-1, 16)
    skin = {"joints": list(range(len(names))), "inverseBindMatrices": add(ibm, 5126, "MAT4")}
    meshes = [{"name": "Body", "primitives": [primitive(body_parts(names, torso_shift) + list(extra_parts))]}]
    nodes.append({"name": "Body", "mesh": 0, "skin": 0})
    if part_parts:
        meshes.append({"name": "Part", "primitives": [primitive(list(part_parts))]})
        nodes.append({"name": "Part", "mesh": len(meshes) - 1, "skin": 0, "extras": {"attached_part": "g"}})
    if garment:
        meshes.append({"name": "garment_dress_x", "primitives": [primitive(
            [("LeftUpLeg", ring(JOINTS["LeftUpLeg"], JOINTS["LeftLeg"], 0.30))])]})
        nodes.append({"name": "garment_dress_x", "mesh": len(meshes) - 1, "skin": 0,
                      "extras": {"garment": {"kind": "dress"}}})
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
            "nodes": nodes, "meshes": meshes, "skins": [skin], "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(blob) + (-len(blob) % 4)}]}
    return pack_glb(gltf, bytes(blob))


def radii(payload):
    return {c["id"]: c["r"] for c in payload["capsules"]}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_collision_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(str(tmp / "world"))
    from app.core import collision

    body = make_body()
    print("[1] fit on the synthetic body")
    full = collision.fit_capsules(body, scales=None)
    r = radii(full)
    check("18 capsules, none skipped", (len(full["capsules"]), full["skipped"]), (TABLE, []))
    check("version", full["version"], collision.VERSION)
    for cid in ("left_thigh", "right_thigh", "left_shin", "right_shin"):
        near(cid, r.get(cid), 0.066, 0.0003)
    for cid in ("left_upper_arm", "right_upper_arm", "left_forearm", "right_forearm"):
        near(cid, r.get(cid), 0.046, 0.0003)
    for cid in ("left_shoulder_hair", "right_shoulder_hair"):
        near(cid, r.get(cid), 0.056, 0.0003)
    shoulder = next(c for c in full["capsules"] if c["id"] == "left_shoulder_hair")
    check("shoulder: clavicle → upper arm, hair-only region", (shoulder["a"], shoulder["b"], shoulder["region"]),
          ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "shoulder_hair"))
    near("hips (ellipse q0.02)", r.get("hips"), 0.10002, 0.0003)
    near("spine (ellipse q0.10)", r.get("spine"), 0.10054, 0.0003)
    near("chest (ellipse q0.10)", r.get("chest"), 0.10054, 0.0003)
    near("head (crown rule)", r.get("head"), 0.090, 0.0003)
    head = next(c for c in full["capsules"] if c["id"] == "head")
    check("head endpoints", (head["a"], head["b"], "a_pos" in head), ("mixamorig:Head", "mixamorig:Head", False))
    check("head b_pos at the crown minus r", head.get("b_pos"), [0.0, 1.7996, 0.0])
    check("limbs carry no positions", any("a_pos" in c or "b_pos" in c for c in full["capsules"]
                                          if c["id"] != "head" and c["region"] != "outer_trunk"), False)
    outer = {c["id"]: c for c in full["capsules"] if c["region"] == "outer_trunk"}
    check("outer ids, after the table's 14", [c["id"] for c in full["capsules"]][14:], OUTER)
    for cid, a, b, ya, yb in (("outer_hips", "Hips", "Spine1", 1.0, 1.1), ("outer_waist", "Hips", "Spine1", 1.1, 1.2),
                              ("outer_spine", "Spine1", "Spine2", 1.2, 1.35),
                              ("outer_chest", "Spine2", "Neck", 1.35, 1.4)):
        cap = outer.get(cid, {})
        near(f"{cid} r = the need 0.10", cap.get("r"), 0.10, 0.0003)
        check(f"{cid} joints / region", (cap.get("a"), cap.get("b"), cap.get("region")),
              (f"mixamorig:{a}", f"mixamorig:{b}", "outer_trunk"))
        check(f"{cid} a_pos / b_pos (centre 0)", (cap.get("a_pos"), cap.get("b_pos")), ([0.0, ya, 0.0], [0.0, yb, 0.0]))
    thigh = next(c for c in full["capsules"] if c["id"] == "left_thigh")
    check("joint names as in the model", (thigh["a"], thigh["b"], thigh["region"]),
          ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "leg"))

    print("[2] missing joints are skipped and reported")
    notop = collision.fit_capsules(make_body(drop=("HeadTop_End",)))
    check("no HeadTop_End: 18 capsules, head identical", (len(notop["capsules"]), notop["skipped"],
          next(c for c in notop["capsules"] if c["id"] == "head")), (TABLE, [], head))
    nohead = collision.fit_capsules(make_body(drop=("Head",)))
    check("head skipped", [(s["id"], s["reason"]) for s in nohead["skipped"]], [("head", "joint Head missing")])
    nofoot = collision.fit_capsules(make_body(drop=("LeftFoot",)))
    check("left_shin and the outer four skipped", [(s["id"], s["reason"]) for s in nofoot["skipped"]],
          [("left_shin", "joint LeftFoot missing")] + [(cid, "joint LeftFoot missing") for cid in OUTER])
    check("the rest unchanged", {k: v for k, v in radii(nofoot).items()},
          {k: v for k, v in r.items() if k != "left_shin" and not k.startswith("outer_")})

    print("[3] region scales")
    scaled = radii(collision.fit_capsules(body, scales={k: 1.2 for k in collision.REGIONS}))
    for cid, want in (("left_thigh", 0.0792), ("left_upper_arm", 0.0552), ("hips", 0.12002),
                      ("spine", 0.12065), ("head", 0.108), ("left_shoulder_hair", 0.0672),
                      ("outer_hips", 0.12), ("outer_waist", 0.12), ("outer_spine", 0.12), ("outer_chest", 0.12)):
        near(f"{cid} × 1.2", scaled.get(cid), want, 0.0004)
    legs = radii(collision.fit_capsules(body, scales={"leg": 1.2}))
    scaled_head = next(c for c in collision.fit_capsules(body, scales={"head": 1.2})["capsules"] if c["id"] == "head")
    near("head × 1.2: b_pos y keeps the cap at the crown", scaled_head["b_pos"][1], 1.7816, 0.0002)
    near("leg only: thigh", legs.get("left_thigh"), 0.0792, 0.0004)
    near("leg only: upper arm unchanged", legs.get("left_upper_arm"), 0.046, 0.0003)
    outer_fit = collision.fit_capsules(body, scales={"outer_trunk": 1.2})
    outer_scaled = radii(outer_fit)
    for cid in OUTER:
        near(f"outer_trunk only: {cid}", outer_scaled.get(cid), 0.12, 0.0004)
    check("outer_trunk only: every other radius unchanged",
          {k: v for k, v in outer_scaled.items() if not k.startswith("outer_")},
          {k: v for k, v in r.items() if not k.startswith("outer_")})
    check("outer_trunk only: positions unchanged but the capped chest end (the centre is not scaled)",
          [(c["a_pos"], c["b_pos"]) for c in outer_fit["capsules"] if c["region"] == "outer_trunk"],
          [(c["a_pos"], c["b_pos"] if c["id"] != "outer_chest" else [0.0, 1.38, 0.0])
           for c in full["capsules"] if c["region"] == "outer_trunk"])
    for bad in ({"leg": 0.4}, {"arm": 1.6}, {"torso": "x"}, {"tail": 1.0}, [1.0]):
        try:
            collision.validate_scales(bad)
            check(f"refused {bad!r}", "accepted", "ValueError")
        except ValueError:
            check(f"refused {bad!r}", "ValueError", "ValueError")
    check("defaults filled", collision.validate_scales({"head": 0.8}),
          {"leg": 1.0, "arm": 1.0, "torso": 1.0, "head": 0.8, "shoulder_hair": 1.0, "chest": 1.0,
           "chest_hair": 1.0, "attached_part": 1.0, "appendage": 1.0, "outer_trunk": 1.0})
    check("validate_scales knows outer_trunk", collision.validate_scales({"outer_trunk": 1.3}).get("outer_trunk"), 1.3)

    print("[4] garment nodes are not body")
    near("left_thigh with a garment", radii(collision.fit_capsules(make_body(garment=True))).get("left_thigh"),
         0.066, 0.0003)

    print("[5] the stored record")
    calls = []
    real_fit = collision.fit_capsules

    def counting_fit(data, *, scales=None, extension=None):
        calls.append(len(data))
        return real_fit(data, scales=scales, extension=extension)

    collision.fit_capsules = counting_fit
    d = tmp / "model3d"
    d.mkdir()
    own = d / "aaaaaaaaaaaa.glb"
    own.write_bytes(body)
    own.with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    defaults = collision.default_scales()
    rec = collision.ensure_path("Demo", own, scales=defaults)
    sha = hashlib.sha256(body).hexdigest()
    check("own record", (rec["version"], rec["source"], rec["sha256"], rec["scales"], len(rec["capsules"])),
          (collision.VERSION, "own", sha, defaults, TABLE))
    stored = json.loads(own.with_suffix(".json").read_text())
    check("written into the sidecar, rest kept", (stored["collision"]["sha256"], stored["rig"]), (sha, "mixamo"))
    check("fitted once", len(calls), 1)
    collision.ensure_path("Demo", own, scales=defaults)
    check("current: not refitted", len(calls), 1)
    other = make_body(drop=("LeftFoot",))
    own.write_bytes(other)
    rec = collision.ensure_path("Demo", own, scales=defaults)
    check("new bytes: refitted", (len(calls), rec["sha256"], len(rec["capsules"])),
          (2, hashlib.sha256(other).hexdigest(), 13))
    rec = collision.ensure_path("Demo", own, scales={**defaults, "leg": 1.1})
    check("changed scales: refitted", (len(calls), rec["scales"]["leg"]), (3, 1.1))

    outfit = d / "bbbbbbbbbbbb.glb"
    outfit.write_bytes(body + b"")
    base_record = {**real_fit(body), "source": "own", "sha256": "S", "computed_at": "t"}
    outfit.with_suffix(".json").write_text(json.dumps({
        "rig": "mixamo", "source": "base_body", "base_signature": "baseB0000000", "base_model_sha256": "S",
        "collision": base_record}))
    n = len(calls)
    rec = collision.ensure_path("Demo", outfit, scales=defaults)
    check("inherited: relabelled, not refitted",
          (rec["source"], rec["base_signature"], rec["sha256"], len(calls) - n), ("base", "baseB0000000", "S", 0))
    check("inherited capsules = the base's", rec["capsules"], base_record["capsules"])
    meta = json.loads(outfit.with_suffix(".json").read_text())
    meta["base_model_sha256"] = "S2"
    outfit.with_suffix(".json").write_text(json.dumps(meta))
    rec = collision.ensure_path("Demo", outfit, scales=defaults)
    check("built on another base: refitted under that base",
          (rec["source"], rec["sha256"], len(calls) - n), ("base", "S2", 1))

    generic = d / "cccccccccccc.glb"
    generic.write_bytes(body)
    generic.with_suffix(".json").write_text(json.dumps({"rig": "generic"}))
    check("generic rig: none", collision.ensure_path("Demo", generic, scales=defaults), None)
    check("generic rig: nothing written", "collision" in json.loads(generic.with_suffix(".json").read_text()), False)
    broken = d / "dddddddddddd.glb"
    broken.write_bytes(b"not a glb at all")
    broken.with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    rec = collision.ensure_path("Demo", broken, scales=defaults)
    check("broken file: error record", (bool(rec.get("error")), rec["capsules"]), (True, []))
    n = len(calls)
    collision.ensure_path("Demo", broken, scales=defaults)
    check("broken file: not refitted per poll", len(calls) - n, 0)
    collision.fit_capsules = real_fit

    print("[6] the post-rig step")
    from app.core import model3d
    called = []
    real_refresh = collision.refresh
    collision.refresh = lambda name, path, meta, **kw: called.append(path.name) or real_refresh(
        name, path, meta, scales=defaults, **kw)
    real_once = model3d._extension_rig_once
    model3d._extension_rig_once = lambda name, path, meta, force=False: {"ok": True, "noop": True}
    base_path = d / "base00000001.glb"
    base_path.write_bytes(body)
    base_meta = {"rig": "mixamo"}
    result = model3d._auto_extension_rig("Demo", base_path, base_meta)
    model3d._extension_rig_once = real_once
    collision.refresh = real_refresh
    check("_auto_extension_rig runs the collision step", called, ["base00000001.glb"])
    check("record in the meta, noop unchanged",
          ((base_meta.get("collision") or {}).get("source"), len((base_meta.get("collision") or {}).get("capsules") or []),
           result.get("noop")), ("own", TABLE, True))

    print("[7] model overview step")
    from app.core import model_overview as mo
    record = {**real_fit(body), "source": "own", "sha256": "x"}

    def row(steps):
        rows = [(s["status"], s["detail"], s["numbers"]) for s in steps if s["id"] == "collision"]
        return rows[0] if rows else None

    want = ("18 capsules · leg 6.6 cm · arm 4.6 cm · torso 10.0–10.1 cm · head 9.0 cm · shoulder_hair 5.6 cm"
            " · outer_trunk 10.0 cm")
    got = row(mo.base_model_steps({"rig": "mixamo", "collision": record}, front_meta=None))
    check("base: done", got and got[:2], ("done", want))
    check("base: count", got and got[2].get("count"), TABLE)
    ids = [s["id"] for s in mo.base_model_steps({"rig": "mixamo", "collision": record}, front_meta=None)]
    check("after the extension rig", ids.index("collision") == ids.index("extension_rig") + 1
          or ids.index("collision") == ids.index("covered_variant") + 1, True)
    got = row(mo.base_model_steps({"rig": "mixamo"}, front_meta=None))
    check("none: missing", got and got[:2], ("missing", "Not computed"))
    got = row(mo.base_model_steps({"rig": "mixamo", "collision": {**record, "capsules": [], "error": "boom"}},
                                  front_meta=None))
    check("error: failed", got and got[:2], ("failed", "boom"))
    skipped = {**real_fit(make_body(drop=("LeftFoot",))), "source": "own", "sha256": "x"}
    got = row(mo.base_model_steps({"rig": "mixamo", "collision": skipped}, front_meta=None))
    check("skipped: warning", got and got[:2],
          ("warning", "13 capsules · leg 6.6 cm · arm 4.6 cm · torso 10.0–10.1 cm · head 9.0 cm · shoulder_hair "
                      "5.6 cm · skipped left_shin (joint LeftFoot missing), outer_hips (joint LeftFoot missing), "
                      "outer_waist (joint LeftFoot missing), outer_spine (joint LeftFoot missing), outer_chest "
                      "(joint LeftFoot missing)"))
    outfit_meta = {"rig": "mixamo", "source": "base_body", "collision": {**record, "source": "base"}}
    got = row(mo.outfit_model_steps(outfit_meta, base=None, base_meta=None, wanted_variant=None, deciders=[],
                                    shown=[], dressed_records={}, garments=[], tiers=["full"]))
    check("outfit: inherited", got and got[:2], ("done", want + " · from the base model"))

    print("[8] extension capsules")
    from app.core.glb_mesh import pack_glb  # noqa: F401 — make_body's dependency, imported once
    n_sphere = 4000
    zeta = 1 - (2 * np.arange(n_sphere) + 1) / n_sphere
    phi = np.arange(n_sphere) * math.pi * (3 - math.sqrt(5))
    rho = np.sqrt(1 - zeta ** 2)
    sphere = np.stack([0.05 * rho * np.cos(phi), 1.30 + 0.05 * rho * np.sin(phi), 0.10 + 0.05 * zeta], 1)
    ext_joints = {"TestBump": (0, 1.30, 0.05), "TestPart1": (0, 0.9, 0.12), "TestPart2": (0, 0.9, 0.22)}
    part_rings = [("TestPart1", ring_z((0, 0.9, 0.12), (0, 0.9, 0.22), 0.03)),
                  ("TestPart2", ring_z((0, 0.9, 0.22), (0, 0.9, 0.30), 0.025))]
    ext_body = make_body(extra_joints=ext_joints, extra_parts=[("TestBump", sphere)], part_parts=part_rings)
    groups = [{"group": "bump", "op": "pair_protrusion", "chains": [["mixamorig:TestBump"]]},
              {"group": "part", "op": "attached_part", "chains": [["mixamorig:TestPart1", "mixamorig:TestPart2"]]}]
    fit = collision.fit_capsules(ext_body, extension=groups)
    ids = [c["id"] for c in fit["capsules"]]
    check("table first, then bump, bump hair, part1, part2", ids[TABLE:],
          ["bump:testbump", "bump:testbump:chest_hair", "part:testpart1", "part:testpart2"])
    check("the table's 18 unchanged but outer_spine", {k: v for k, v in radii({"capsules": fit["capsules"][:TABLE]}).items()
                                                      if k != "outer_spine"},
          {k: v for k, v in r.items() if k != "outer_spine"})
    check("outer_spine covers the bump (the outer rule reads every body vertex)",
          radii(fit).get("outer_spine", 0) > r["outer_spine"], True)
    bump, bump_hair, part1, part2 = fit["capsules"][TABLE:TABLE + 4]
    near("bump r = R·sqrt(0.75)", bump["r"], 0.043301, 0.0002)
    check("bump endpoints / region", (bump["a"], bump["b"], bump["region"]),
          ("mixamorig:TestBump", "mixamorig:TestBump", "chest"))
    near("bump b_pos z (cap ends at the tip)", bump["b_pos"][2], 0.106199, 0.0002)
    near("bump b_pos x", bump["b_pos"][0], 0.0, 0.0002)
    near("bump b_pos y", bump["b_pos"][1], 1.30, 0.0002)
    near("bump hair r = p95 + clearance", bump_hair["r"], 0.055937, 0.0002)
    check("bump hair endpoints / region", (bump_hair["a"], bump_hair["b"], bump_hair["region"]),
          ("mixamorig:TestBump", "mixamorig:TestBump", "chest_hair"))
    near("bump hair b_pos z (cap ends at tip + clearance)", bump_hair["b_pos"][2], 0.099563, 0.0002)
    near("part1 r (ring)", part1["r"], 0.030, 0.0002)
    check("part1 ends at the next link", (part1["a"], part1["b"], "b_pos" in part1, part1["region"]),
          ("mixamorig:TestPart1", "mixamorig:TestPart2", False, "attached_part"))
    near("part2 r (ring)", part2["r"], 0.025, 0.0002)
    check("part2 tip rule", part2.get("b_pos"), [0.0, 0.9, 0.267])
    check("no group: 18 capsules", len(collision.fit_capsules(ext_body)["capsules"]), TABLE)
    check("op outside the table: 18 capsules", len(collision.fit_capsules(
        ext_body, extension=[{"group": "t", "op": "pair_tip", "chains": [["mixamorig:TestBump"]]}])["capsules"]), TABLE)
    scaled = collision.fit_capsules(ext_body, scales={"chest": 1.2}, extension=groups)["capsules"]
    near("chest × 1.2", scaled[TABLE]["r"], 0.051962, 0.0002)
    near("chest × 1.2: b_pos z", scaled[TABLE]["b_pos"][2], 0.097538, 0.0002)
    near("chest × 1.2: hair set unchanged", scaled[TABLE + 1]["r"], 0.055937, 0.0002)
    near("attached_part unchanged", scaled[TABLE + 2]["r"], 0.030, 0.0002)
    hair_scaled = collision.fit_capsules(ext_body, scales={"chest_hair": 1.2}, extension=groups)["capsules"]
    near("chest_hair × 1.2", hair_scaled[TABLE + 1]["r"], 0.067125, 0.0002)
    near("chest_hair × 1.2: b_pos z", hair_scaled[TABLE + 1]["b_pos"][2], 0.089575, 0.0002)
    near("chest_hair × 1.2: chest unchanged", hair_scaled[TABLE]["r"], 0.043301, 0.0002)
    from app.core import garment_fit
    check("hair clearance = the hair fit's", collision.HAIR_CLEARANCE_M, garment_fit.HAIR_CLEAR_M)
    missing = collision.fit_capsules(ext_body, extension=[{"group": "x", "op": "pair_protrusion",
                                                             "chains": [["mixamorig:Absent"]]}])
    check("missing chain joint: skipped", [(x["id"], x["reason"]) for x in missing["skipped"]],
          [("x:absent", "joint mixamorig:Absent missing"), ("x:absent:chest_hair", "joint mixamorig:Absent missing")])

    from types import SimpleNamespace
    from app.plugins import loader
    fake = [SimpleNamespace(body_slots=[SimpleNamespace(rigs=[
        SimpleNamespace(id="bump", chains=[[{"bone": "mixamorig:TestBump", "parent": "Spine2"}]]),
        SimpleNamespace(id="tip", chains=[[{"bone": "mixamorig:TestTip", "parent": "mixamorig:TestBump"}]])])])]
    real_declared = loader.declared_packages
    loader.declared_packages = lambda: fake
    try:
        rig = {"status": "applied", "groups": ["bump", "tip"], "group_ops": {"bump": "pair_protrusion", "tip": "pair_tip"}}
        check("extension_chains: the table's ops only, chains from the declaration",
              collision.extension_chains({"extension_rig": rig}),
              [{"group": "bump", "op": "pair_protrusion", "chains": [["mixamorig:TestBump"]]}])
        check("extension_chains: not applied → none",
              collision.extension_chains({"extension_rig": {**rig, "status": "failed"}}), [])
        check("extension_chains: no record → none", collision.extension_chains({}), [])
    finally:
        loader.declared_packages = real_declared

    print("[9] appendage capsules")
    app_joints = {"TestApp1": (0, 0.9, 0.12), "TestApp2": (0, 0.9, 0.22)}
    app_rings = [("TestApp1", ring_z((0, 0.9, 0.12), (0, 0.9, 0.22), 0.03)),
                 ("TestApp2", ring_z((0, 0.9, 0.22), (0, 0.9, 0.30), 0.025))]
    app_body = make_body(extra_joints=app_joints, extra_parts=app_rings)
    app_groups = [{"group": "app", "op": "appendage_chain", "chains": [["mixamorig:TestApp1", "mixamorig:TestApp2"]]}]
    fit = collision.fit_capsules(app_body, extension=app_groups)
    check("payload version: v5 brought the appendage region (later bumps keep it)",
          (fit["version"] == collision.VERSION, collision.VERSION >= 5), (True, True))
    check("the table's 18, then app1, app2", [c["id"] for c in fit["capsules"]][TABLE:],
          ["app:testapp1", "app:testapp2"])
    check("nothing skipped", fit["skipped"], [])
    app1, app2 = (fit["capsules"][TABLE:TABLE + 2] + [{}, {}])[:2]
    near("app1 r (ring)", app1.get("r"), 0.030, 0.0002)
    check("app1 ends at the next link, region appendage",
          (app1.get("a"), app1.get("b"), "b_pos" in app1, app1.get("region")),
          ("mixamorig:TestApp1", "mixamorig:TestApp2", False, "appendage"))
    near("app2 r (ring)", app2.get("r"), 0.025, 0.0002)
    check("app2 tip rule", (app2.get("a"), app2.get("b"), app2.get("b_pos"), app2.get("region")),
          ("mixamorig:TestApp2", "mixamorig:TestApp2", [0.0, 0.9, 0.267], "appendage"))
    scaled = collision.fit_capsules(app_body, scales={"appendage": 1.2}, extension=app_groups)["capsules"][TABLE:TABLE + 2]
    near("appendage × 1.2: app1", scaled[0]["r"] if scaled else None, 0.036, 0.0002)
    near("appendage × 1.2: app2", scaled[1]["r"] if len(scaled) > 1 else None, 0.030, 0.0002)
    near("appendage × 1.2: app2 b_pos z", scaled[1]["b_pos"][2] if len(scaled) > 1 else None, 0.262, 0.0002)
    other = collision.fit_capsules(app_body, scales={"attached_part": 1.2}, extension=app_groups)["capsules"][TABLE:TABLE + 2]
    check("attached_part × 1.2: appendage unchanged", [c["r"] for c in other], [0.03, 0.025])
    check("validate_scales knows appendage", collision.validate_scales({"appendage": 1.3}).get("appendage"), 1.3)
    loader.declared_packages = lambda: [SimpleNamespace(body_slots=[SimpleNamespace(rigs=[
        SimpleNamespace(id="app", chains=[[{"bone": "mixamorig:TestApp1", "parent": "Hips"},
                                           {"bone": "mixamorig:TestApp2", "parent": "mixamorig:TestApp1"}]])])])]
    try:
        check("extension_chains keeps an appendage_chain group",
              collision.extension_chains({"extension_rig": {"status": "applied", "groups": ["app"],
                                                            "group_ops": {"app": "appendage_chain"}}}),
              [{"group": "app", "op": "appendage_chain", "chains": [["mixamorig:TestApp1", "mixamorig:TestApp2"]]}])
    finally:
        loader.declared_packages = real_declared

    print("[10] the outer rule (collision v6)")
    check("payload version: v6 brought the outer set (later bumps keep it)", collision.VERSION >= 6, True)
    check("payload version: v7 brought the declared channels (later bumps keep it; smoke_collision_channels.py)",
          collision.VERSION >= 7, True)
    shifted = collision.fit_capsules(make_body(torso_shift=0.03))
    by_id = {c["id"]: c for c in shifted["capsules"]}
    for cid in OUTER:
        near(f"shifted: {cid} r = the need 0.10", (by_id.get(cid) or {}).get("r"), 0.10, 0.0003)
    for cid, key, want in (("outer_hips", "a_pos", (0.0, 1.0, 0.03)), ("outer_waist", "a_pos", (0.0, 1.1, 0.03)),
                           ("outer_spine", "a_pos", (0.0, 1.2, 0.03)), ("outer_spine", "b_pos", (0.0, 1.35, 0.03)),
                           ("outer_chest", "b_pos", (0.0, 1.40, 0.03))):
        for k, w in enumerate(want):
            near(f"shifted: {cid} {key}[{k}] through the centres", ((by_id.get(cid) or {}).get(key) or [None] * 3)[k],
                 w, 0.0003)
    check("shifted: the inside-skin torso set keeps its joints",
          [("a_pos" in by_id[c]) or ("b_pos" in by_id[c]) for c in ("hips", "spine", "chest")], [False, False, False])
    back = collision.fit_capsules(make_body(torso_shift=0.03, extra_joints={"LeftToeBase": (0.1, 0.02, -0.12),
                                                                            "RightToeBase": (-0.1, 0.02, -0.12)}))
    back_spine = next((c for c in back["capsules"] if c["id"] == "outer_spine"), {})
    near("front from the feet: reversed toes, same a_pos z", (back_spine.get("a_pos") or [0, 0, None])[2], 0.03, 0.0003)
    near("front from the feet: reversed toes, same r", back_spine.get("r"), 0.10, 0.0003)
    splay = collision.fit_capsules(make_body(torso_shift=0.03, extra_joints={"LeftToeBase": (0.15, 0.02, 0.12),
                                                                             "RightToeBase": (-0.15, 0.02, 0.12)}))
    splay_spine = next((c for c in splay["capsules"] if c["id"] == "outer_spine"), {})
    check("toe-out cancels: outer_spine a_pos unchanged", splay_spine.get("a_pos"), [0.0, 1.2, 0.03])
    near("toe-out cancels: r", splay_spine.get("r"), 0.10, 0.0003)
    one = collision.fit_capsules(make_body(torso_shift=0.03, extra_joints={"LeftToeBase": (0.1, 0.02, -0.12)}))
    check("both feet count: opposite toes leave no front", [(s["id"], s["reason"]) for s in one["skipped"]],
          [(cid, "no front direction") for cid in OUTER])
    notoe = collision.fit_capsules(make_body(drop=("LeftToeBase",)))
    check("no LeftToeBase: the outer four skipped", [(s["id"], s["reason"]) for s in notoe["skipped"]],
          [(cid, "joint LeftToeBase missing") for cid in OUTER])
    check("no LeftToeBase: the 14 others fitted", [c["id"] for c in notoe["capsules"]], [c["id"] for c in full["capsules"]][:14])

    print("[11] the bind pose of a stored set (partner probe)")
    bind = collision.bind_pose_capsules(body, full)
    by_bind = {c["id"]: c for c in bind}
    check("18 capsules in payload order", [c["id"] for c in bind], [c["id"] for c in full["capsules"]])
    check("entry keys", sorted(bind[0]) if bind else None, ["a", "b", "id", "r", "region"])
    thigh_b = by_bind.get("left_thigh") or {}
    check("left_thigh a = LeftUpLeg, b = LeftLeg", (thigh_b.get("a"), thigh_b.get("b"), thigh_b.get("region")),
          ([0.1, 0.95, 0.0], [0.1, 0.5, 0.0], "leg"))
    near("left_thigh r = the fit's", thigh_b.get("r"), 0.066, 0.0003)
    head_b = by_bind.get("head") or {}
    check("head a = Head, b = its b_pos", (head_b.get("a"), head_b.get("b")), ([0.0, 1.6, 0.0], [0.0, 1.7996, 0.0]))
    spine_b = by_bind.get("outer_spine") or {}
    check("outer_spine a / b = its a_pos / b_pos", (spine_b.get("a"), spine_b.get("b")),
          ([0.0, 1.2, 0.0], [0.0, 1.35, 0.0]))
    nofoot_bind = collision.bind_pose_capsules(make_body(drop=("LeftFoot",)), full)
    check("a joint the file lacks: left out (17, no left_shin)",
          (len(nofoot_bind), "left_shin" in {c["id"] for c in nofoot_bind}), (TABLE - 1, False))

    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.core import auth_dependency, model3d
    from app.models.character import get_character_dir
    from app.routes import characters as characters_route
    users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Mara"]},
             "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}

    def stub_session_user(request: Request):
        return users.get(request.headers.get("x-test-user", ""))

    real_session, real_serving = auth_dependency._get_session_user, model3d.find_model3d_serving
    model_dir = get_character_dir("Mara", create=True) / "model3d"
    model_dir.mkdir(parents=True, exist_ok=True)
    served = model_dir / "sig1.glb"
    served.write_bytes(body)
    side = served.with_suffix(".json")
    side.write_text(json.dumps({"rig": "mixamo", "collision": {**full, "source": "own", "sha256": "x"}}))
    before = side.read_bytes()
    auth_dependency._get_session_user = stub_session_user
    model3d.find_model3d_serving = lambda name: (served, "exact") if name == "Mara" else (None, "")
    try:
        route_app = FastAPI()
        route_app.middleware("http")(auth_dependency.auth_gate_middleware)
        route_app.middleware("http")(auth_dependency.user_context_middleware)
        route_app.include_router(characters_route.router)
        route_client = TestClient(route_app)
        url = "/characters/Mara/model3d/collision/bind-pose"
        check("route: a player is refused", route_client.get(url, headers={"x-test-user": "user"}).status_code, 403)
        answer = route_client.get(url, headers={"x-test-user": "admin"})
        check("route: an admin gets it", answer.status_code, 200)
        check("route: {signature, capsules}", answer.json() if answer.status_code == 200 else None,
              {"signature": "sig1", "capsules": json.loads(json.dumps(bind))})
        check("route: nothing written", side.read_bytes(), before)
        side.write_text(json.dumps({"rig": "mixamo"}))
        check("route: no stored set → 404",
              route_client.get(url, headers={"x-test-user": "admin"}).status_code, 404)
    finally:
        auth_dependency._get_session_user, model3d.find_model3d_serving = real_session, real_serving

    print("FAIL" if FAILS else "OK", f"({len(FAILS)} failures)" if FAILS else "")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
