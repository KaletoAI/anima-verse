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
         rings of radius 0.06 around UpLeg→Leg (weighted UpLeg) and Leg→Foot (weighted Leg);
  arms   LeftArm (0.2, 1.45, 0) → LeftForeArm (0.5, 1.45, 0) → LeftHand (0.75, 1.45, 0), right mirrored;
         rings of radius 0.04 around Arm→ForeArm (weighted Arm) and ForeArm→Hand (weighted ForeArm);
  torso  Hips (0, 1.0, 0) → Spine1 (0, 1.2, 0) → Spine2 (0, 1.35, 0) → Neck (0, 1.5, 0); ELLIPSE rings
         x = 0.12 cos θ, z = 0.10 sin θ around each segment, weighted to its start bone;
  head   Head (0, 1.6, 0), HeadTop_End (0, 1.8, 0); a capsule SURFACE of radius 0.09 around 1.6..1.8 (rings
         + two hemispheres of 10 rows × 72, polar angle φ = 0.1..π/2), weighted Head ("head sphere 0.09").
Each ring: 720 evenly spaced θ at 9 stations t = 0.1..0.9 of the segment (all strictly inside, so the distance
to the segment is the distance to the axis).

Expected, derived by hand:
[1] fit_capsules on the full body: 12 capsules, nothing skipped.
    A uniform ring has ONE distance, so every quantile = its radius:
      legs  0.060 + 6 mm = 0.066 (left/right thigh, left/right shin)
      arms  0.040 + 6 mm = 0.046 (left/right upper arm, left/right forearm)
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
    Tolerance 0.3 mm (discrete θ, 0.1-mm rounding). Joint names come back as in the model ("mixamorig:…").
[2] Without HeadTop_End: still 12 capsules, the head identical (the crown rule needs no crown joint). Without
    Head: head skipped "joint Head missing". Without LeftFoot: left_shin skipped "joint LeftFoot missing",
    everything else unchanged — no crash.
[3] Region scale 1.2 everywhere → every radius × 1.2 (thigh 0.0792, upper arm 0.0552, hips 0.1200, spine
    0.1206, head 0.1080 with b_pos y = 1.889550 − 0.108 = 1.7816, ±0.4 mm); {"leg": 1.2} alone → legs 0.0792, arms stay 0.046. validate_scales refuses
    0.4, 1.6, "x", an unknown region; fills missing regions with 1.0.
[4] A grafted garment node (``garment_dress_x``, a ring of radius 0.30 weighted LeftUpLeg) changes nothing:
    left_thigh stays 0.066 (body_arrays skips garment nodes).
[5] The stored record (``collision.ensure_path`` on <tmp>/model3d/<sig>.glb + sidecar, scales passed in):
    own model → record {version 1, source own, sha256 = sha of the file, scales = defaults}, written into the
    sidecar; a second call fits nothing (fit counter unchanged); new file bytes → refitted (counter +1).
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
      record with 12 capsules → done "12 capsules · leg 6.6 cm · arm 4.6 cm · torso 10.0–10.1 cm · head
      9.0 cm", numbers count 12; on the outfit "… · from the base model"; none → missing "Not computed";
      error → failed with the error; a skipped capsule → warning "… · skipped left_shin (joint LeftFoot
      missing)".
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
    Payload order: the 12 table capsules, then BUMP, BUMP HAIR, PART1, PART2 (ids "<group>:<normalised bone>").
    No group (``extension`` None / only an op outside the table, e.g. ``pair_tip``) → the 12 capsules only.
    Scale chest 1.2 → BUMP r = 0.051962, b_pos z = 0.05 + 0.0995 − 0.051962 = 0.097538; BUMP HAIR and PART
    unchanged. Scale chest_hair 1.2 → BUMP HAIR r = 0.067125, b_pos z = 0.05 + 0.0995 + 0.0072 − 0.067125
    = 0.089575; BUMP unchanged. HAIR_CLEARANCE_M = garment_fit.HAIR_CLEAR_M.
    A chain joint the model lacks → skipped "joint … missing".
    ``extension_chains(meta)``: status "applied", groups [bump, tip], ops {bump: pair_protrusion, tip: pair_tip}
    → [{group bump, op pair_protrusion, chains from the declaration}]; status "failed" → []; no record → [].
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
    "LeftUpLeg": (0.1, 0.95, 0), "LeftLeg": (0.1, 0.5, 0), "LeftFoot": (0.1, 0.08, 0),
    "RightUpLeg": (-0.1, 0.95, 0), "RightLeg": (-0.1, 0.5, 0), "RightFoot": (-0.1, 0.08, 0),
    "LeftArm": (0.2, 1.45, 0), "LeftForeArm": (0.5, 1.45, 0), "LeftHand": (0.75, 1.45, 0),
    "RightArm": (-0.2, 1.45, 0), "RightForeArm": (-0.5, 1.45, 0), "RightHand": (-0.75, 1.45, 0),
}
N_THETA, STATIONS = 720, np.linspace(0.1, 0.9, 9)


def ring(a, b, rx, rz=None):
    """Points around segment a→b: the axis is y (vertical segments) or x (arms)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    th = np.arange(N_THETA) * 2 * np.pi / N_THETA
    rz = rx if rz is None else rz
    out = []
    for t in STATIONS:
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


def body_parts(joints):
    parts = []
    for side in ("Left", "Right"):
        parts.append((f"{side}UpLeg", ring(JOINTS[f"{side}UpLeg"], JOINTS[f"{side}Leg"], 0.06)))
        parts.append((f"{side}Leg", ring(JOINTS[f"{side}Leg"], JOINTS[f"{side}Foot"], 0.06)))
        parts.append((f"{side}Arm", ring(JOINTS[f"{side}Arm"], JOINTS[f"{side}ForeArm"], 0.04)))
        parts.append((f"{side}ForeArm", ring(JOINTS[f"{side}ForeArm"], JOINTS[f"{side}Hand"], 0.04)))
    for a, b in (("Hips", "Spine1"), ("Spine1", "Spine2"), ("Spine2", "Neck")):
        parts.append((a, ring(JOINTS[a], JOINTS[b], 0.12, 0.10)))
    parts.append(("Head", head_surface(JOINTS["Head"], JOINTS["HeadTop_End"], 0.09)))
    return [(j, p) for j, p in parts if j in joints]


def make_body(*, drop=(), garment=False, extra_joints=None, extra_parts=(), part_parts=()):
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
    meshes = [{"name": "Body", "primitives": [primitive(body_parts(names) + list(extra_parts))]}]
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
    check("12 capsules, none skipped", (len(full["capsules"]), full["skipped"]), (12, []))
    check("version", full["version"], 3)
    for cid in ("left_thigh", "right_thigh", "left_shin", "right_shin"):
        near(cid, r.get(cid), 0.066, 0.0003)
    for cid in ("left_upper_arm", "right_upper_arm", "left_forearm", "right_forearm"):
        near(cid, r.get(cid), 0.046, 0.0003)
    near("hips (ellipse q0.02)", r.get("hips"), 0.10002, 0.0003)
    near("spine (ellipse q0.10)", r.get("spine"), 0.10054, 0.0003)
    near("chest (ellipse q0.10)", r.get("chest"), 0.10054, 0.0003)
    near("head (crown rule)", r.get("head"), 0.090, 0.0003)
    head = next(c for c in full["capsules"] if c["id"] == "head")
    check("head endpoints", (head["a"], head["b"], "a_pos" in head), ("mixamorig:Head", "mixamorig:Head", False))
    check("head b_pos at the crown minus r", head.get("b_pos"), [0.0, 1.7996, 0.0])
    check("limbs carry no positions", any("a_pos" in c or "b_pos" in c for c in full["capsules"] if c["id"] != "head"),
          False)
    thigh = next(c for c in full["capsules"] if c["id"] == "left_thigh")
    check("joint names as in the model", (thigh["a"], thigh["b"], thigh["region"]),
          ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "leg"))

    print("[2] missing joints are skipped and reported")
    notop = collision.fit_capsules(make_body(drop=("HeadTop_End",)))
    check("no HeadTop_End: 12 capsules, head identical", (len(notop["capsules"]), notop["skipped"],
          next(c for c in notop["capsules"] if c["id"] == "head")), (12, [], head))
    nohead = collision.fit_capsules(make_body(drop=("Head",)))
    check("head skipped", [(s["id"], s["reason"]) for s in nohead["skipped"]], [("head", "joint Head missing")])
    nofoot = collision.fit_capsules(make_body(drop=("LeftFoot",)))
    check("left_shin skipped", [(s["id"], s["reason"]) for s in nofoot["skipped"]],
          [("left_shin", "joint LeftFoot missing")])
    check("the rest unchanged", {k: v for k, v in radii(nofoot).items()},
          {k: v for k, v in r.items() if k != "left_shin"})

    print("[3] region scales")
    scaled = radii(collision.fit_capsules(body, scales={k: 1.2 for k in collision.REGIONS}))
    for cid, want in (("left_thigh", 0.0792), ("left_upper_arm", 0.0552), ("hips", 0.12002),
                      ("spine", 0.12065), ("head", 0.108)):
        near(f"{cid} × 1.2", scaled.get(cid), want, 0.0004)
    legs = radii(collision.fit_capsules(body, scales={"leg": 1.2}))
    scaled_head = next(c for c in collision.fit_capsules(body, scales={"head": 1.2})["capsules"] if c["id"] == "head")
    near("head × 1.2: b_pos y keeps the cap at the crown", scaled_head["b_pos"][1], 1.7816, 0.0002)
    near("leg only: thigh", legs.get("left_thigh"), 0.0792, 0.0004)
    near("leg only: upper arm unchanged", legs.get("left_upper_arm"), 0.046, 0.0003)
    for bad in ({"leg": 0.4}, {"arm": 1.6}, {"torso": "x"}, {"tail": 1.0}, [1.0]):
        try:
            collision.validate_scales(bad)
            check(f"refused {bad!r}", "accepted", "ValueError")
        except ValueError:
            check(f"refused {bad!r}", "ValueError", "ValueError")
    check("defaults filled", collision.validate_scales({"head": 0.8}),
          {"leg": 1.0, "arm": 1.0, "torso": 1.0, "head": 0.8, "chest": 1.0, "chest_hair": 1.0,
           "attached_part": 1.0})

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
          (3, "own", sha, defaults, 12))
    stored = json.loads(own.with_suffix(".json").read_text())
    check("written into the sidecar, rest kept", (stored["collision"]["sha256"], stored["rig"]), (sha, "mixamo"))
    check("fitted once", len(calls), 1)
    collision.ensure_path("Demo", own, scales=defaults)
    check("current: not refitted", len(calls), 1)
    other = make_body(drop=("LeftFoot",))
    own.write_bytes(other)
    rec = collision.ensure_path("Demo", own, scales=defaults)
    check("new bytes: refitted", (len(calls), rec["sha256"], len(rec["capsules"])),
          (2, hashlib.sha256(other).hexdigest(), 11))
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
           result.get("noop")), ("own", 12, True))

    print("[7] model overview step")
    from app.core import model_overview as mo
    record = {**real_fit(body), "source": "own", "sha256": "x"}

    def row(steps):
        rows = [(s["status"], s["detail"], s["numbers"]) for s in steps if s["id"] == "collision"]
        return rows[0] if rows else None

    want = "12 capsules · leg 6.6 cm · arm 4.6 cm · torso 10.0–10.1 cm · head 9.0 cm"
    got = row(mo.base_model_steps({"rig": "mixamo", "collision": record}, front_meta=None))
    check("base: done", got and got[:2], ("done", want))
    check("base: count", got and got[2].get("count"), 12)
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
          ("warning", "11 capsules · leg 6.6 cm · arm 4.6 cm · torso 10.0–10.1 cm · head 9.0 cm · skipped "
                      "left_shin (joint LeftFoot missing)"))
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
    check("table first, then bump, bump hair, part1, part2", ids[12:],
          ["bump:testbump", "bump:testbump:chest_hair", "part:testpart1", "part:testpart2"])
    check("the table's 12 unchanged", radii({"capsules": fit["capsules"][:12]}), r)
    bump, bump_hair, part1, part2 = fit["capsules"][12:16]
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
    check("no group: 12 capsules", len(collision.fit_capsules(ext_body)["capsules"]), 12)
    check("op outside the table: 12 capsules", len(collision.fit_capsules(
        ext_body, extension=[{"group": "t", "op": "pair_tip", "chains": [["mixamorig:TestBump"]]}])["capsules"]), 12)
    scaled = collision.fit_capsules(ext_body, scales={"chest": 1.2}, extension=groups)["capsules"]
    near("chest × 1.2", scaled[12]["r"], 0.051962, 0.0002)
    near("chest × 1.2: b_pos z", scaled[12]["b_pos"][2], 0.097538, 0.0002)
    near("chest × 1.2: hair set unchanged", scaled[13]["r"], 0.055937, 0.0002)
    near("attached_part unchanged", scaled[14]["r"], 0.030, 0.0002)
    hair_scaled = collision.fit_capsules(ext_body, scales={"chest_hair": 1.2}, extension=groups)["capsules"]
    near("chest_hair × 1.2", hair_scaled[13]["r"], 0.067125, 0.0002)
    near("chest_hair × 1.2: b_pos z", hair_scaled[13]["b_pos"][2], 0.089575, 0.0002)
    near("chest_hair × 1.2: chest unchanged", hair_scaled[12]["r"], 0.043301, 0.0002)
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

    print("FAIL" if FAILS else "OK", f"({len(FAILS)} failures)" if FAILS else "")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
