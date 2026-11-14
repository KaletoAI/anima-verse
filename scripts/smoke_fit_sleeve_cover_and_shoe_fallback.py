#!/usr/bin/env python3
"""Ruling A40: a piece's own sleeve covers its armhole; a refused derived shoe falls back to a fresh fit.

Usage:
    ./.venv/bin/python scripts/smoke_fit_sleeve_cover_and_shoe_fallback.py

Runs against a THROWAWAY storage directory (``paths.init`` first) on synthetic bodies built here (``BodyMesh``
arrays) and stubbed footwear computes — no world, no hub, no GPU, no Blender, no server. Every expected number is
derived by hand below. The "fails on the old code" proof loads ``app/core/garment_source.py`` of commit
``ccb4f7502`` (Ruling A35, the last code without the sleeve rule) through ``git show``.

Geometry ([1] - [4]). Trunk: a closed cylinder r 0.10 around the y axis, y 0.79 .. 1.45, 360 segments, rings every
2 mm, skinned like ``smoke_garment_refit_source.py`` [11] (Hips / Spine / Spine1 / Spine2 / Neck by height, the
weight rings put the hip joint at y 0.85 and the neck at 1.40: v = (y - 0.85) / 0.55). Arm: a closed cylinder
r 0.06 around the vertical line x 0.17, z 0, y 1.05 .. 1.40 (120 segments, rings every 5 mm), every vertex on
LeftArm: it spans x 0.11 .. 0.23 on the +x side, 1 cm off the trunk. Jacket: a tube r 0.115 around the trunk, y
0.80 .. 1.40, 360 segments, rings every 2 mm, with an ARMHOLE: the faces whose centre lies within 15 deg of +x
(the trunk angle 90 deg) between y 1.15 and 1.30 are cut out. Sleeve: a tube of radius R around the arm's axis,
y 1.05 .. 1.40 (180 segments, rings every 5 mm), its faces within 0.13 of the trunk axis cut away (the part that
would lie inside the trunk) — the sleeve hangs from the armhole, over the arm. The base fit's openings: none
(``torso_open`` all closed: the whole seen area counts).

The straight pass (``_trunk_seen``) looks along each skin vertex's outward normal (radial) for a jacket sample
within ``TORSO_SEE_LATERAL_M`` 0.012 of the ray points 0.002, 0.010, ... 0.074 from the skin. In the armhole the
nearest ray point to the jacket tube is r 0.118 (3 mm off it): the cut edge is reached within sqrt(0.012^2 -
0.003^2) = 0.01162 m, i.e. 0.01162 / 0.115 = 5.79 deg from the side edges and 0.0116 m from the top and bottom
edges. Seen: |angle - 90| < 15 - 5.79 = 9.21 deg (0.1608 rad), y 1.1616 .. 1.2884 (0.1268 m): at r 0.10 that is
2 x 0.1608 x 0.10 x 0.1268 = 40.8 cm2 (+- 3.5: the 1 deg x 2 mm grid's half cell along the 0.32 m border), centred
at angle 90 deg, height (1.225 - 0.85) / 0.55 = 0.68. The sleeve never comes within 0.012 of those rays: the
sleeve circle (centre 0.17, radius R) crosses r 0.13 from the trunk axis at cos(phi) = (0.13^2 + 0.17^2 - R^2) /
(2 x 0.13 x 0.17) — R 0.075: 24.6 deg off +x (0.13 x sin(24.6 - 9.21 deg) = 0.034 > 0.012 from the outermost seen
ray); its far side lies at x 0.17 + R cos ... >= 0.2377 (R 0.075, ray at 9.21 deg: 0.17 cos a + sqrt(R^2 -
(0.17 sin a)^2)), beyond the straight pass's last point 0.174 + 0.012.

[1] A sleeve R 0.075 (1.5 cm over the arm). A seen ray at angle a (|a| <= 9.21 deg) crosses the arm (its distance
    to the arm's axis 0.17 sin a <= 0.0272 < 0.06): it enters at s = 0.17 cos a - sqrt(0.06^2 - (0.17 sin a)^2)
    (0.110 at a 0, 0.1143 at 9.21 deg; s = distance from the trunk axis), leaves at + sqrt(...) (0.230 / 0.2213)
    and meets the sleeve at 0.17 cos a + sqrt(0.075^2 - (0.17 sin a)^2) (0.245 / 0.2377): outside the arm the ray
    runs 0.010 + 0.015 = 0.025 (a 0) to 0.0143 + 0.0164 = 0.031 m (9.21 deg) — at most 5 steps of 0.008, within
    the straight pass's 10 (``_sleeve_over``). Every seen vertex is covered: largest hole 0.0, the gate passes.
    The old code (ccb4f7502): 40.8 cm2, refused (> ``TORSO_HOLE_CM2`` 15).
[2] Sleeveless (no sleeve, the same armhole): the rays cross the arm and find nothing after it — 40.8 cm2, refused,
    the same number as the old code's (a real armhole gap stays a hole).
[3] A loose sleeve R 0.10 (4 cm over the arm): outside the arm 0.010 + (0.27 - 0.23) = 0.05 m at a 0 (6.25 steps;
    9.21 deg: 0.0143 + 0.0365 = 0.051) <= 0.08: covered, largest hole 0.0. A loose sleeve R 0.16 (10 cm over the
    arm): 0.010 + (0.33 - 0.23) = 0.11 m > 0.08 (9.21 deg: 0.0143 + 0.104): beyond the gap tolerance, 40.8 cm2,
    refused — no new limit, the existing depth decides.
[4] Only the armhole changes: the same jacket without the armhole (the window kept) covers everything, with and
    without the rule (largest hole 0.0, seen area 0); and the old and new code agree on [2] and on R 0.16 exactly.

Footwear ([5] - [7]; ``garment_footwear.fit`` with stubbed computes, the attempt store and the preview REAL).
Demo, item ``shoes``, fsig F = "a40a40a40a40", body shapes A / B / C (``ob`` ids). The stubs: ``derive_compute``
and ``fit_compute`` write their GLB bytes ("DERIVED-<body>" / "FRESH-<body>") to the compute's temp path and
answer as scripted; ``refit_pool.run`` calls in-process; ``refine.decimate_to`` copies.
[5] A: the derived shoe refused (deep_outside 0.02798 > 0.02 and visible_poke 0.03685 > 0.005 — Kira's legacy body
    22354 on the real data), the fresh fit accepted: calls [derive, fresh]; the fit at bodies/A/shoes_F.glb holds
    the FRESH bytes, its record ``fit_method`` "fresh_fallback", ``base_fit_sha256`` = sha256(the base fit);
    the derived attempt kept (attempts/derived/shoes_F.glb = the DERIVED bytes, record ``fit_method`` "derived",
    attempt error "fit refused — deep_outside 0.02798 > 0.02 …"), no attempt in the main slot.
[6] B: both refused: ``_Refused`` with the fresh fit's error; BOTH attempts kept — main slot ``fit_method``
    "fresh_fallback" (FRESH bytes), the derived slot (DERIVED bytes); no fit published. C: the derived shoe
    accepted: calls [derive] only, ``fit_method`` "derived"; a derived attempt kept there before is dropped.
[7] The Details preview (``fit_attempts.bodies`` with ``fit_status`` stubbed per body; ``_current`` real). Ruling
    A67: the dialog lists the base body and the CURRENT body (``dialog_shape``, stubbed to A, then B, then C) — so
    with A current the keys are exactly plain, A, A-derived (role base / current / current); A -> entry "A"
    accepted, ``method_note`` = FIT_METHOD_NOTES["fresh_fallback"], then entry "A-derived" (variant "derived",
    refused, cannot be accepted: "This body already has an accepted fit"); B current -> "B" refused with the
    fresh_fallback note and "B-derived" refused, can_accept. ``parse_key``: "plain" -> ("", ""), "B-derived" ->
    (B, "derived"), "plain-derived" -> ValueError. Accepting "B-derived" publishes the DERIVED bytes as B's fit
    (``user_accepted.slot`` "derived"); a new FRESH attempt of the main slot on B (other bytes) does NOT void it.
    The three notes and the button word are de.json keys.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

#: The last code without the sleeve rule (Ruling A35).
OLD_COMMIT = "ccb4f7502"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def within(label, value, lo, hi):
    ok = value is not None and lo <= value <= hi
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {value!r} in [{lo}, {hi}]")
    if not ok:
        FAILS.append(label)


JOINTS = ["Hips", "LeftUpLeg", "RightUpLeg", "Spine", "Spine1", "Spine2", "Neck", "LeftArm"]


def tube(r, cx, y0, y1, nseg, step):
    """An open tube of radius ``r`` around the vertical line x ``cx``, z 0 -> ``(positions, faces)``."""
    ys = np.arange(int(round((y1 - y0) / step)) + 1) * step + y0
    ang = np.arange(nseg) * 2 * np.pi / nseg
    G = np.array([(cx + r * np.cos(a), y, r * np.sin(a)) for y in ys for a in ang])
    faces = []
    for row in range(len(ys) - 1):
        for j in range(nseg):
            a, b = row * nseg + j, row * nseg + (j + 1) % nseg
            c, d = (row + 1) * nseg + (j + 1) % nseg, (row + 1) * nseg + j
            faces += [(a, b, c), (a, c, d)]
    return G, np.asarray(faces, np.int64)


def trunk_with_arm():
    """The trunk + arm body (docstring)."""
    import smoke_garment_fit as fx
    from app.core.glb_mesh import BodyMesh
    idx = {n: i for i, n in enumerate(JOINTS)}
    P, F = fx.cylinder(0.10, 0.79, 1.45, nseg=360, nrings=331)
    J = np.zeros((len(P), 4), np.int64)
    W = np.zeros((len(P), 4))
    rings = {0.95: ("Hips", "Spine"), 1.10: ("Spine", "Spine1"), 1.25: ("Spine1", "Spine2"), 1.40: ("Spine2", "Neck")}
    for i, (x, y, _z) in enumerate(P):
        y = round(float(y), 4)
        if y == 0.85:
            pair = ("Hips", "LeftUpLeg" if x >= 0 else "RightUpLeg")
        elif y in rings:
            pair = rings[y]
        else:
            bone = "Hips" if y < 0.95 else "Spine" if y < 1.10 else "Spine1" if y < 1.25 else "Spine2" if y < 1.40 \
                else "Neck"
            J[i, 0], W[i, 0] = idx[bone], 1.0
            continue
        J[i, :2], W[i, :2] = [idx[pair[0]], idx[pair[1]]], [0.5, 0.5]
    Pa, Fa = fx.cylinder(0.06, 1.05, 1.40, nseg=120, nrings=71)
    Pa = Pa + np.array([0.17, 0.0, 0.0])
    Ja = np.zeros((len(Pa), 4), np.int64)
    Ja[:, 0] = idx["LeftArm"]
    Wa = np.zeros((len(Pa), 4))
    Wa[:, 0] = 1.0
    return BodyMesh(positions=np.vstack([P, Pa]), faces=np.vstack([F, Fa + len(P)]).astype(np.int64),
                    uvs=np.zeros((len(P) + len(Pa), 2)), joints=np.vstack([J, Ja]), weights=np.vstack([W, Wa]),
                    joint_names=["mixamorig:" + n for n in JOINTS])


def jacket(sleeve_r=None, armhole=True):
    """The jacket tube with its armhole (docstring), plus a sleeve of radius ``sleeve_r`` when given."""
    G, Fg = tube(0.115, 0.0, 0.80, 1.40, 360, 0.002)
    centre = G[Fg].mean(1)
    window = (np.abs(np.degrees(np.arctan2(centre[:, 2], centre[:, 0]))) < 15) & (centre[:, 1] > 1.15) \
        & (centre[:, 1] < 1.30)
    faces = Fg[~window] if armhole else Fg
    if sleeve_r is None:
        return G, faces
    S, Fs = tube(sleeve_r, 0.17, 1.05, 1.40, 180, 0.005)
    cs = S[Fs].mean(1)
    Fs = Fs[np.hypot(cs[:, 0], cs[:, 2]) > 0.13]
    return np.vstack([G, S]), np.vstack([faces, Fs + len(G)])


def old_garment_source():
    """``app/core/garment_source.py`` as it was at ``OLD_COMMIT``, imported under its own name."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/garment_source.py"],
                            capture_output=True, text=True, check=True).stdout
    path = Path(tempfile.mkdtemp(prefix="a40old")) / "old_garment_source.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("old_garment_source", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_a40_"))
    try:
        from app.core import paths
        paths.init(tmp / "world")
        from app.core import garment_source
        lo, hi = garment_source.TORSO_V_RANGE
        closed = [[False] * garment_source.TORSO_OPEN_SECTORS
                  for _ in range(int(round((hi - lo) / garment_source.TORSO_OPEN_V)))]
        body = trunk_with_arm()
        old = old_garment_source()

        def holes(module, garment):
            h = module.torso_holes(garment[0], garment[1], body, closed)
            return h, module.torso_hole_gate(h)

        # --- [1] ---------------------------------------------------------------------------------------------------
        print("[1] a sleeve over the arm covers the armhole")
        sleeved = jacket(0.075)
        h, gate = holes(garment_source, sleeved)
        check("sleeve 0.075: no hole, passes", (h["largest_cm2"], h["patches"], gate["ok"]), (0.0, [], True))
        h_old, gate_old = holes(old, sleeved)
        print(f"  old code: {h_old['patches'][:1]}")
        within("old code (ccb4f7502): the armhole is a hole", h_old["largest_cm2"], 37.3, 44.3)
        check("old code refused, at the armhole",
              (gate_old["ok"], h_old["patches"][0]["theta_deg"], h_old["patches"][0]["v"]), (False, 90, 0.68))

        # --- [2] ---------------------------------------------------------------------------------------------------
        print("[2] sleeveless: a real armhole gap stays a hole")
        bare = jacket(None)
        h2, gate2 = holes(garment_source, bare)
        within("sleeveless hole", h2["largest_cm2"], 37.3, 44.3)
        check("sleeveless refused, at the armhole", (gate2["ok"], h2["patches"][0]["theta_deg"],
                                                     h2["patches"][0]["v"]), (False, 90, 0.68))
        h2_old, _ = holes(old, bare)
        check("sleeveless: old and new agree", h2["largest_cm2"], h2_old["largest_cm2"])
        check("sleeve 0.075 on the new code = the old code's sleeveless hole gone",
              h_old["largest_cm2"], h2["largest_cm2"])

        # --- [3] ---------------------------------------------------------------------------------------------------
        print("[3] the gap tolerance decides: 4 cm over the arm covers, 10 cm does not")
        h3, gate3 = holes(garment_source, jacket(0.10))
        check("sleeve 0.10 covers", (h3["largest_cm2"], gate3["ok"]), (0.0, True))
        h4, gate4 = holes(garment_source, jacket(0.16))
        within("sleeve 0.16: hole", h4["largest_cm2"], 37.3, 44.3)
        check("sleeve 0.16 refused", gate4["ok"], False)
        check("sleeve 0.16: old and new agree", h4["largest_cm2"], holes(old, jacket(0.16))[0]["largest_cm2"])

        # --- [4] ---------------------------------------------------------------------------------------------------
        print("[4] without an armhole nothing changes")
        closed_jacket = jacket(0.075, armhole=False)
        h5, _ = holes(garment_source, closed_jacket)
        h5_old, _ = holes(old, closed_jacket)
        check("closed jacket: no hole, new and old", (h5["largest_cm2"], h5_old["largest_cm2"]), (0.0, 0.0))
        seen = garment_source._trunk_seen(closed_jacket[0], closed_jacket[1], body)
        check("closed jacket: nothing seen", int(seen["seen"].sum()), 0)

        # --- [5] - [7] ---------------------------------------------------------------------------------------------
        footwear(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("smoke_fit_sleeve_cover_and_shoe_fallback: all checks passed")
    return 0


def footwear(tmp: Path) -> None:
    from app.blender import refine
    from app.core import fit_attempts, garment_fit, garment_footwear as gfw, garment_store as gs, garments
    from app.core import footwear_source, refit_pool
    from app.core import db
    from app.models.character import get_character_dir

    db.init_schema()
    get_character_dir("Demo").mkdir(parents=True, exist_ok=True)
    item, F = "shoes", "a40a40a40a40"
    A, B, C = "ob0000000a", "ob0000000b", "ob0000000c"
    version = garment_fit.FIT_VERSION["footwear"]
    source = tmp / "source"
    source.mkdir()
    (source / "prepared.glb").write_bytes(b"PREPARED")
    (source / "insole.json").write_text("{}")
    base_fit = (b"BASE-FIT", {"sides": {}}, b"BASE-RIGGED")
    parents_source = {"ssig": "s0", "empty_sha256": "e", "mesh_sha256": "m", "insole_version": 8}
    script = {}
    calls = []

    def compute(kind_):
        def run(*args):
            out = Path(args[-1])
            body = script["body"]
            calls.append(kind_)
            ok = script[kind_]
            data = f"{'DERIVED' if kind_ == 'derive' else 'FRESH'}-{body}-{script.get('round', 0)}".encode()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            part = {"record": {"scale": {"width_factor": 1.0}, "root_lift_m": 0.01, "sides": {}},
                    "foot_pose": {"bones": {}}, "cut_stats": {"removed_faces": 1, "bisected_faces": 0},
                    "rest": {}, "glb_sha256": sha(data), "tris": 12}
            if ok:
                return {"ok": True, **part}
            reasons = (["deep_outside 0.02798 > 0.02 (share of the slimmed foot's should-be-enclosed vertices > 3 mm "
                        "outside the shoe, worse side)", "visible_poke 0.03685 > 0.005 (share of the remaining foot "
                        "vertices still below the upper's rim, worse side)"] if kind_ == "derive" else
                       ["throat_ledge_p95_mm 11.8 > 4 (p95 height of the remaining vertices just behind the throat "
                        "front above the vamp edge)"])
            key = reasons[0].split()[0]
            return {"ok": False, "reasons": reasons,
                    "gates": {"ok": False, "reasons": reasons, key: {"value": 1.0, "ok": False, "gating": True}},
                    "attempt": part, "marks": None}
        return run

    saved = {}

    def patch(obj, name, value):
        saved[(obj, name)] = getattr(obj, name)
        setattr(obj, name, value)

    patch(gfw, "derive_compute", compute("derive"))
    patch(gfw, "fit_compute", compute("fresh"))
    patch(gfw, "_item_kind", lambda c, i: ({"id": i}, "footwear"))
    patch(gfw, "_fsig", lambda c, i, p: F)
    patch(gfw, "source_ready", lambda i: True)
    patch(gfw, "_accepted_base_fit", lambda c, i, f, p: base_fit)
    patch(gfw, "_source_parents", lambda i, s: dict(parents_source))
    patch(footwear_source, "current_ssig", lambda i: "s0")
    patch(footwear_source, "source_dir", lambda i, s: source)
    patch(garments, "_snapshot_body", lambda c, b: {"rigged": f"RIGGED-{b}".encode(), "sha": f"sha-{b}",
                                                    "meta": {"outfit_body": {"base_signature": "base00000000"}}})
    patch(refit_pool, "run", lambda fn, *a, **k: fn(*a, **k))

    def decimate(src, target, dst, **_kw):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return {"ok": True, "tris": target, "ratio": 1.0}
    patch(refine, "decimate_to", decimate)
    patch(fit_attempts, "follow_up", lambda c: {"hub_jobs": 0, "steps": []})
    patch(gs, "_garment_kind", lambda i: "footwear")
    try:
        def run_fit(body, derive_ok, fresh_ok, round_=0):
            script.update(body=body, derive=derive_ok, fresh=fresh_ok, round=round_)
            calls.clear()
            try:
                gfw.fit("Demo", item, F, body=body, profile={})
                return None
            except garments._Refused as e:
                return e.error

        def attempt(body, slot=""):
            found = fit_attempts.attempt_of("Demo", item, body, slot)
            if found is None:
                return None
            glb, record, _marks = found
            return (glb.read_bytes() if glb else None, record.get("fit_method"),
                    (record.get("attempt") or {}).get("error", "")[:40])

        fit_path = {b: gs.garment_path("Demo", item, F, "fit", body=b) for b in (A, B, C)}

        # --- [5] ---------------------------------------------------------------------------------------------------
        print("[5] a refused derived shoe falls back to a fresh fit")
        check("A: accepted", run_fit(A, False, True), None)
        check("A: derive, then fresh", list(calls), ["derive", "fresh"])
        rec = gs.read_record(fit_path[A].with_suffix(".json"))
        check("A: the fresh fit published", (fit_path[A].read_bytes(), rec.get("fit_method"), rec.get("accepted"),
                                             rec.get("base_fit_sha256"), rec.get("fit_version")),
              (f"FRESH-{A}-0".encode(), "fresh_fallback", True, sha(base_fit[0]), version))
        check("A: the derived shoe kept as an attempt", attempt(A, fit_attempts.DERIVED),
              (f"DERIVED-{A}-0".encode(), "derived", "fit refused — deep_outside 0.02798 > 0.0"))
        check("A: no attempt in the main slot", attempt(A), None)
        check("A: the derived attempt's folder", fit_attempts._attempt_files("Demo", item, A, "derived")[F]["glb"],
              gs.body_root("Demo", A) / "attempts" / "derived" / f"{item}_{F}.glb")

        # --- [6] ---------------------------------------------------------------------------------------------------
        print("[6] both refused: both attempts kept; a derived shoe that fits needs no fresh fit")
        err = run_fit(B, False, False)
        check("B: refused with the fresh fit's error", err, "fit refused — throat_ledge_p95_mm 11.8 > 4 (p95 height "
              "of the remaining vertices just behind the throat front above the vamp edge)")
        check("B: derive, then fresh", list(calls), ["derive", "fresh"])
        check("B: no fit", fit_path[B].is_file(), False)
        check("B: main attempt = the fresh fit", attempt(B), (f"FRESH-{B}-0".encode(), "fresh_fallback",
                                                              "fit refused — throat_ledge_p95_mm 11.8 >"))
        check("B: derived attempt kept", attempt(B, "derived"), (f"DERIVED-{B}-0".encode(), "derived",
                                                                 "fit refused — deep_outside 0.02798 > 0.0"))
        run_fit(C, False, False)
        check("C: refused first", (attempt(C) is not None, attempt(C, "derived") is not None), (True, True))
        check("C: accepted, derived", run_fit(C, True, False, 1), None)
        check("C: derive only", list(calls), ["derive"])
        rec_c = gs.read_record(fit_path[C].with_suffix(".json"))
        check("C: fit_method derived", (rec_c.get("fit_method"), fit_path[C].read_bytes()),
              ("derived", f"DERIVED-{C}-1".encode()))
        check("C: every attempt dropped", (attempt(C), attempt(C, "derived")), (None, None))

        # --- [7] ---------------------------------------------------------------------------------------------------
        print("[7] the Details preview names the method; the derived shoe is an entry of its own")
        states = {A: "accepted", B: "missing", C: "accepted"}

        def status(c, i, body, profile=None):
            if not body:
                return {"fsig": F, "state": "accepted", "failure": None, "body_sha": "sha-plain", "base_fit_sha": ""}
            failure = None if states[body] == "accepted" else {"error": err}
            return {"fsig": F, "state": states[body], "failure": failure, "body_sha": f"sha-{body}",
                    "base_fit_sha": ""}
        patch(fit_attempts, "fit_status", status)
        current = {"body": A}
        patch(fit_attempts, "dialog_shape", lambda c, i, profile=None: (current["body"], True))

        def bodies_on(body):
            current["body"] = body
            return {e["key"]: e for e in fit_attempts.bodies("Demo", item, profile={})}
        entries = bodies_on(A)
        check("A current: base + current only", [(k, e["role"]) for k, e in entries.items()],
              [("plain", "base"), (A, "current"), (A + "-derived", "current")])
        entries.update(bodies_on(B))
        check("B current: base + current only", sorted(bodies_on(B)), sorted(["plain", B, B + "-derived"]))
        entries.update(bodies_on(C))
        check("C current: base + current only", sorted(bodies_on(C)), sorted(["plain", C]))
        check("A: accepted, fresh fit named", (entries[A]["status"], entries[A]["method_note"], entries[A]["variant"]),
              ("accepted", fit_attempts.FIT_METHOD_NOTES["fresh_fallback"], ""))
        e = entries[A + "-derived"]
        check("A-derived: refused, kept, not acceptable",
              (e["status"], e["variant"], e["method_note"], e["can_accept"], e["accept_block"], e["url"] is not None),
              ("refused", "derived", fit_attempts.FIT_METHOD_NOTES["derived"], False,
               "This body already has an accepted fit", True))
        check("B: refused, fresh fit named", (entries[B]["status"], entries[B]["method_note"]),
              ("refused", fit_attempts.FIT_METHOD_NOTES["fresh_fallback"]))
        check("B-derived: refused, acceptable", (entries[B + "-derived"]["status"], entries[B + "-derived"]["can_accept"],
                                                 entries[B + "-derived"]["reason"]),
              ("refused", True, "the foot pokes out through the shoe; the foot shows above the shoe's rim"))
        check("C: accepted, derived named", entries[C]["method_note"], fit_attempts.FIT_METHOD_NOTES["derived"])
        check("plain: no note", entries["plain"]["method_note"], "")
        check("parse_key", (fit_attempts.parse_key("plain"), fit_attempts.parse_key(B + "-derived"),
                            fit_attempts.parse_key(A)), (("", ""), (B, "derived"), (A, "")))
        for bad in ("plain-derived", "-derived", "base12345678-derived"):
            try:
                fit_attempts.parse_key(bad)
                check(f"parse_key {bad!r} refused", False, True)
            except ValueError:
                check(f"parse_key {bad!r} refused", True, True)
        shown = fit_attempts.shown_file("Demo", item, B + "-derived")
        check("B-derived model = the derived attempt", shown[0].read_bytes(), f"DERIVED-{B}-0".encode())

        fit_attempts.accept("Demo", item, B, profile={}, slot="derived")
        rec_b = gs.read_record(fit_path[B].with_suffix(".json"))
        check("B: the derived shoe accepted by the user",
              (fit_path[B].read_bytes(), rec_b.get("fit_method"), (rec_b.get("user_accepted") or {}).get("slot")),
              (f"DERIVED-{B}-0".encode(), "derived", "derived"))
        states[B] = "accepted"
        e = bodies_on(B)
        check("B-derived now user_accepted", (e[B]["status"], e[B + "-derived"]["status"]),
              ("user_accepted", "user_accepted"))
        # a new attempt of the MAIN slot (the fresh fit, other bytes) does not void the derived acceptance
        fit_attempts.store("Demo", item, F, body=B, kind="footwear",
                           record={"kind": "footwear", "item_id": item, "fsig": F, "fit_method": "fresh_fallback"},
                           error="fit refused — x", gates=None, glb=None)
        check("B: the acceptance holds", (gs.read_record(fit_path[B].with_suffix(".json")).get("user_accepted")
                                          or {}).get("slot"), "derived")

        de = json.loads((ROOT / "shared" / "languages" / "de.json").read_text())["translations"]
        for key in (*fit_attempts.FIT_METHOD_NOTES.values(), "the plain body's shoe"):
            check(f"de.json key {key[:40]!r}", key in de, True)
    finally:
        for (obj, name), value in saved.items():
            setattr(obj, name, value)


if __name__ == "__main__":
    sys.exit(main())
