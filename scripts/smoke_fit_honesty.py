#!/usr/bin/env python3
"""Honest refusal of a clothing fit: the rigged clearance pass is gated by its deep push share
(``garment_fit.CLOTHING_GATES`` ``rigged_deep_push_share``; ``rigged_push_max_m`` / ``rigged_push_p95_m`` reported,
not gated — plan 2026-11-12 fit-sdf-speed-drape, Task 7, Ruling R7a), and a shoe whose refit is refused or not yet
made keeps its older fit on an outfit body (Ruling R7b), expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_fit_honesty.py

No world, no server, no external assets: every mesh is built below; [H3] / [H5] write records under a temp storage
(``paths.init(<tmp>)`` before any other app import).

Fixture — the [F1] construction of ``smoke_body_field.py``, VERTICAL: a double-walled "leg" around the y axis,
outer cylinder r 0.05 and inner cylinder r 0.04 with REVERSED winding, y 0.00 .. 0.40 (41 rings, 64 around),
their ends joined by annular caps; the core (r < 0.04) is open at both ends. Skinned to LeftUpLeg 1 (a second
joint Hips with no vertex). Unrigged = rigged (same positions and UVs), k = 1: the transfer moves nothing, the
rigged clearance pass (``transfer_skinned`` step 4, ``push_kept`` against ``body_sdf`` of the rigged body) is
the only motion. The garment is an open tube around the y axis, y 0.10 .. 0.30 (21 rings 1 cm apart, 48 around),
radius r_g; it is >= 0.10 from both open ends, farther than from the outer wall (<= 0.05), so its nearest exit is
the outer wall, radially. Gate numbers by ``clothing_metrics`` with the unrigged push at zero (Q_post = Q0_pre:
the leaky placement pushed nothing) and the transfer's report, judged by ``clothing_gates`` as ``fit_clothing``
does.

[H1] r_g 0.01: 4 cm inside the leg (0.05 - 0.01), 3 cm inside the inner wall.
     - New field (every y-slice is two rings, the core disc is enclosed): every garment vertex lies 0.04 deep. Any
       path out of the solid is at least that long (the nearest outside is the outer wall 0.04 away radially), so
       every vertex that ends outside was pushed >= 0.04 > DEEP_PUSH_M 0.03 -> rigged_deep_push_share = the share
       that ends outside; every vertex ends outside (rigged_inside_share 0) -> rigged_deep_push_share 1.0 > 0.12 ->
       ``ok False``, and the reasons name ``rigged_deep_push_share`` with its value and the limit 0.12 in the text.
       Torso-mapped (``clothing_gates(torso_mapped=True)``): the same refusal (the rigged keys are never skipped).
       (Which way a vertex leaves is not asserted: 0.04 deep > SIDE_DEEP_M and its unrigged side — from the inner
       wall towards the axis — points against the gradient, so ``_transfer_sides`` marches it across the axis and
       out of the far wall; measured 0.075 .. 0.272 m, the far end past the field's crop, which ``Sdf.sample``
       clamps — which is why ``rigged_push_max_m`` is reported, not gated: the gate keys hold
       ``rigged_deep_push_share`` and ``rigged_inside_share``, not the max.)
     - BASE f55e4b2c (the plan's BASE, its own ``garment_fit`` loaded as a module): its field fills in 3-D and seals
       only, the core reaches the outside through the open ends -> outside, 0.03 from the inner wall > CLEAR_M
       0.0119 -> nothing is pushed (rigged push max < 1 mm, inside share 0) and its gates (no rigged-push key)
       pass -> ``ok True``: the leaky field reads the core as outside.
     - Task BASE c49be850 (the correct field, before this gate): the push runs (rigged deep push share 1.0) and its
       gates pass -> ``ok True``: the refusal comes from the new gate, not the field.
[H2] r_g 0.055: 5 mm outside the outer wall. The push takes each vertex to the clearance CLEAR_M 0.0119 ->
     0.0119 - 0.005 = 6.9 mm (+- 2 mm: the exact band's sampling and the smoothing) -> rigged_push_max_m in
     0.0049 .. 0.0089, rigged_deep_push_share 0, both present and finite; every other gate number of a clean tube
     (one component: largest share 1.0, inside 0) passes -> ``ok True``.
[H3] The refused fit's failure record, built the way ``garments._fit`` + ``garments._note_outcome`` do: error
     ``"fit refused — " + "; ".join(reasons)`` written by ``garment_store.record_failure(step "fit")`` under
     ``paths.init(<tmp>)``, read back: it carries the reason with the key ``rigged_deep_push_share``, the value
     (``1`` as ``gate`` formats it, ``{value:g}``) and the limit ``0.12``, plus ``scale_retry`` (a fit refusal).
[H4] The version bumps: ``FIT_VERSION`` hair 16 / clothing 17 (8 in phase A, 9 with Task 7 fix 1's side
     projection, 10 with Ruling A35's joint frames, sleeves and openings, 11 with Ruling A47's sleeves laid onto the
     arm, width allowance and arm light, 12 with Ruling A50's trunk bridge on body shapes,
     13 with Ruling A51's openings the worn view shows, 14 with Ruling A72's repaired UV-mismatched donors,
     15 with Ruling A76's kept sheet order and openings' inside, 16 with Ruling A83's trunk laid onto the body,
     17 with Ruling A84's armpit seam;
     hair 14: user test T-U1/T-U2, 15: Ruling A80, the cap above the brow, 16: A80b, the natural hairline) / footwear 18 (= ``FOOTWEAR_FIT_VERSION``;
     18: an outfit body's shoe is derived from the plain body's fit, Ruling A35), ``garment_layers.LAYER_VERSION`` 2.
[H5] Ruling R7b on an outfit body (``garment_footwear.body_fit``; stubs: the shoe's current fsig
     ``fedcba987654``, its source ready, the stored body bytes ``"b" * 64``, the fit refuses). Stored: the shoe's
     fit of the OLD fsig ``0123456789ab`` on ``ob0000000a`` — accepted, fit_version 16, ``body_sha256`` "b" * 64,
     with ``cut.sides`` and ``foot_pose`` (graftable).
     (a) serving (build False): the current fsig has no fit, the source is ready, the body bytes match, no failure
         -> pending True, fit None (the assembly is not current, a build is asked; nothing to fall back to yet).
     (b) the build (build True): the fit refuses -> a body failure for the current fsig (fit_version 18, no base
         fit: ``base_fit_sha`` ""), and the
         old fit is served: fit = the old GLB, fsig ``0123456789ab``, pending False, error the refusal's text.
     (c) the old record without ``cut.sides`` -> nothing graftable: fit None.
     (d) graftable again but made on other body bytes (``body_sha256`` "c" * 64) -> fit None (never another body's).
     (e) the current fsig's fit accepted on the body (fit_version 18, "b" * 64), derived from the base fit of
         that fsig (``base_fit_sha256`` = the sha256 of the stored base fit, Ruling A35) -> served itself, fsig
         ``fedcba987654``.
"""
import math
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BASE = "f55e4b2c"          # plan BASE: the leaky field
TASK_BASE = "c49be850"     # this task's BASE: the correct field, no rigged gate
FAILS = []
JOINTS = ["mixamorig:Hips", "mixamorig:LeftUpLeg"]


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- meshes ---------------------------------------------------------------------------------------------------

def grid_faces(rows, cols, start=0):
    F = []
    for i in range(rows - 1):
        for j in range(cols):
            a, b = start + i * cols + j, start + i * cols + (j + 1) % cols
            c, d = start + (i + 1) * cols + (j + 1) % cols, start + (i + 1) * cols + j
            F += [(a, b, c), (a, c, d)]
    return np.array(F, np.int64)


def ring_stack(radius, ys, nseg):
    ang = np.arange(nseg) * 2 * np.pi / nseg
    return np.array([(radius * math.cos(a), y, radius * math.sin(a)) for y in ys for a in ang])


def leg(r_out=0.05, r_in=0.04, y0=0.0, y1=0.40, nseg=64, nrings=41):
    """[F1] turned vertical: outer side, inner side (reversed winding), annular caps at both ends."""
    ys = np.linspace(y0, y1, nrings)
    parts = [(ring_stack(r_out, ys, nseg), grid_faces(nrings, nseg)),
             (ring_stack(r_in, ys, nseg), grid_faces(nrings, nseg)[:, ::-1])]
    ang = np.arange(nseg) * 2 * np.pi / nseg
    for y in (y0, y1):
        P = np.array([(r * math.cos(a), y, r * math.sin(a)) for r in np.linspace(r_out, r_in, 4) for a in ang])
        parts.append((P, grid_faces(4, nseg)))
    Ps, Fs, n = [], [], 0
    for P, F in parts:
        Ps.append(P)
        Fs.append(F + n)
        n += len(P)
    return np.concatenate(Ps), np.concatenate(Fs)


def garment(radius):
    ys = np.round(np.linspace(0.10, 0.30, 21), 4)
    return ring_stack(radius, ys, 48), grid_faces(21, 48)


def bodies():
    from app.core.glb_mesh import BodyMesh
    P, F = leg()
    n = len(P)
    J = np.zeros((n, 4), np.int64)
    W = np.zeros((n, 4))
    J[:, 0], W[:, 0] = 1, 1.0
    uv = np.stack([(np.arange(n) + 0.5) / n, np.full(n, 0.5)], 1)
    rig = BodyMesh(positions=P, faces=F, uvs=uv, joints=J, weights=W, joint_names=list(JOINTS))
    unrig = BodyMesh(positions=P.copy(), faces=F, uvs=uv, joints=np.zeros((n, 4), np.int64),
                     weights=np.zeros((n, 4)), joint_names=[])
    return unrig, rig


def module_at(rev):
    """``app/core/garment_fit.py`` of commit ``rev``, loaded as its own module."""
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:app/core/garment_fit.py"])
    mod = types.ModuleType(f"garment_fit_{rev}")
    mod.__file__ = f"<{rev}:app/core/garment_fit.py>"
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def fit(gf, radius, *, torso_mapped=False):
    """The rigged pass of a clothing fit on the leg -> ``(ok, reasons, metrics, report)``."""
    unrig, rig = bodies()
    Q, F = garment(radius)
    X, report = gf.transfer_skinned(Q, unrig, rig, faces=F, k=1.0, split_y=float(Q[:, 1].min()) - 1.0)
    m = gf.clothing_metrics(X, F, Q, Q, report)
    if hasattr(gf, "clothing_gates"):
        gates = gf.clothing_gates(torso_mapped=torso_mapped)
    else:
        gates = {key: spec for key, spec in gf.CLOTHING_GATES.items()
                 if not (torso_mapped and key in getattr(gf, "PLACEMENT_GATE_KEYS", ()))}
    ok, reasons = gf.gate(m, gates)
    return ok, reasons, m, report


# --- cases --------------------------------------------------------------------------------------------------------

def test_h1(gf):
    ok, reasons, m, report = fit(gf, 0.01)
    deep = m.get("rigged_deep_push_share")
    check(isinstance(deep, float) and deep > 0.12,
          f"[H1] 4 cm inside the leg: rigged deep push share > 0.12 (got {deep}; max push "
          f"{m.get('rigged_push_max_m')}, p95 {m.get('rigged_push_p95_m')}, inside {m.get('rigged_inside_share')})")
    check(abs(report["rigged_deep_push_share"] - 1.0) < 1e-9,
          f"[H1] every vertex pushed out more than 3 cm (report share {report['rigged_deep_push_share']:.4f})")
    check(report["rigged_inside_share"] == 0.0, f"[H1] every vertex ends outside ({report['rigged_inside_share']})")
    hit = [r for r in reasons if r.startswith("rigged_deep_push_share ")]
    check(not ok and len(hit) == 1 and f"{deep:g}" in hit[0] and "> 0.12" in hit[0],
          f"[H1] refused, the reason names rigged_deep_push_share, its value and 0.12 ({ok}, {reasons})")
    ok_t, reasons_t, _m, _r = fit(gf, 0.01, torso_mapped=True)
    check(not ok_t and any(r.startswith("rigged_deep_push_share ") for r in reasons_t),
          f"[H1] torso-mapped: the rigged gate still refuses ({reasons_t})")
    check(not any(r.startswith("rigged_push_max_m ") for r in reasons),
          f"[H1] the rigged max push is reported, never a reason (R7a; {reasons})")
    keys = gf.clothing_gates(torso_mapped=True)
    check({"rigged_deep_push_share", "rigged_inside_share"} <= set(keys)
          and not set(gf.PLACEMENT_GATE_KEYS) & set(keys),
          f"[H1] clothing_gates(torso_mapped=True) keeps the rigged gates, drops the placement keys ({sorted(keys)})")
    check("rigged_push_max_m" not in gf.CLOTHING_GATES and "rigged_push_p95_m" not in gf.CLOTHING_GATES
          and gf.CLOTHING_GATES["rigged_deep_push_share"]
          == ("max", 0.12, "share of vertices pushed out more than 3 cm on the rigged body"),
          "[H1] the rigged deep push gate carries the existing limit 0.12; max / p95 not gated (R7a)")
    return reasons


def test_h1_old():
    old = module_at(BASE)
    ok, reasons, m, report = fit(old, 0.01)
    check(ok and report["rigged_push_max_m"] < 0.001 and report["rigged_inside_share"] == 0.0,
          f"[H1] BASE {BASE}: the leaky field reads the core as outside — nothing pushed, the fit passes "
          f"(ok {ok}, push max {report['rigged_push_max_m']:.4f}, {reasons})")
    task = module_at(TASK_BASE)
    ok, reasons, m, report = fit(task, 0.01)
    check(ok and report["rigged_push_max_m"] >= 0.04 and report["rigged_inside_share"] == 0.0,
          f"[H1] task BASE {TASK_BASE}: the push runs ({report['rigged_push_max_m']:.4f} m) yet the fit passes "
          f"(ok {ok}, {reasons})")


def test_h2(gf):
    ok, reasons, m, _report = fit(gf, 0.055)
    keys = ("rigged_push_max_m", "rigged_push_p95_m", "rigged_deep_push_share")
    finite = all(isinstance(m.get(k), float) and math.isfinite(m[k]) for k in keys)
    check(finite, f"[H2] the rigged push numbers are present and finite ({ {k: m.get(k) for k in keys} })")
    check(finite and 0.0049 <= m["rigged_push_max_m"] <= 0.0089 and m["rigged_deep_push_share"] == 0.0,
          f"[H2] 5 mm outside: pushed 6.9 mm +- 2 mm, nothing deep ({m.get('rigged_push_max_m')}, "
          f"{m.get('rigged_deep_push_share')})")
    check(ok, f"[H2] 5 mm outside: the fit passes ({reasons}; {m})")


def test_h3(gf, reasons):
    from app.core import garment_store as gs
    from app.models.character import get_character_dir
    get_character_dir("Demo", create=True)
    gs._root("Demo").mkdir(parents=True, exist_ok=True)
    error = "fit refused — " + "; ".join(reasons)
    gs.record_failure("Demo", "item_demo", "a" * 12, step="fit", error=error, base_model_sha="b" * 64)
    record = gs.read_record(gs.garment_path("Demo", "item_demo", "a" * 12, "failed"))
    hit = [r for r in str(record.get("error") or "").split("; ") if "rigged_deep_push_share" in r]
    check(record.get("step") == "fit" and len(hit) == 1 and " 1 > 0.12 " in hit[0] + " ",
          f"[H3] the failure record carries the key, its value 1 and the limit 0.12 ({record.get('error')!r})")
    check(record.get("scale_retry") == gf.SCALE_RETRY_VERSION, f"[H3] stamped as a fit refusal ({record})")


def test_h4(gf):
    from app.core import footwear_fit, garment_layers
    check(gf.FIT_VERSION == {"hair": 16, "clothing": 17, "footwear": 18} and footwear_fit.FOOTWEAR_FIT_VERSION == 18
          and garment_layers.LAYER_VERSION == 2,
          f"[H4] FIT_VERSION {gf.FIT_VERSION}, FOOTWEAR_FIT_VERSION {footwear_fit.FOOTWEAR_FIT_VERSION}, "
          f"LAYER_VERSION {garment_layers.LAYER_VERSION} (want hair 16 / clothing 17 / footwear 18, layers 2)")


def test_h5():
    from app.core import garment_footwear, garments, garment_store as gs
    old_fsig, cur_fsig, body, sha = "0123456789ab", "fedcba987654", "ob0000000a", "b" * 64
    item = "item_shoe"
    garment_footwear._fsig = lambda name, item_id, profile: cur_fsig
    garment_footwear.source_ready = lambda item_id: True
    garments.body_sha256 = lambda name, body_id: sha

    def refuse(*_a, **_k):
        raise garments._Refused("fit", "fit refused — visible_poke 0.02 > 0.005", None)
    garment_footwear.fit = refuse
    graftable = {"cut": {"version": 7, "sides": {"left": {"cap": []}}}, "foot_pose": {"version": 1}}

    def put(fsig, version, body_sha, extra):
        path = gs.garment_path("Demo", item, fsig, "fit", body=body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"FIT " + fsig.encode())
        gs.write_record(path.with_suffix(".json"),
                        {"accepted": True, "kind": "footwear", "item_id": item, "fsig": fsig, "method": "shoe",
                         "body_id": body, "body_sha256": body_sha, "fit_version": version, **extra})
        return path

    old = put(old_fsig, 16, sha, graftable)

    def served(build=False):
        return garment_footwear.body_fit("Demo", item, body_id=body, body_sha=sha, profile={}, build=build)
    a = served()
    check(a["pending"] is True and a["fit"] is None, f"[H5] (a) serving: pending, nothing grafted yet ({a})")
    b = served(build=True)
    failure = gs.body_failure("Demo", item, cur_fsig, body, body_sha=sha, base_fit_sha="", fit_version=18)
    check(failure is not None and "visible_poke" in str(failure.get("error")),
          f"[H5] (b) the refusal recorded on the body for the current fsig ({failure})")
    check(b["fit"] == old and b["fsig"] == old_fsig and b["pending"] is False and "visible_poke" in b["error"],
          f"[H5] (b) refused: the version-16 fit stays served, the error names the refusal ({b})")
    put(old_fsig, 16, sha, {"cut": {"version": 7, "sides": {}}, "foot_pose": {"version": 1}})
    c = served()
    check(c["fit"] is None, f"[H5] (c) an old fit without its cut is never grafted ({c})")
    put(old_fsig, 16, "c" * 64, graftable)
    d = served()
    check(d["fit"] is None, f"[H5] (d) an old fit on other body bytes is never grafted ({d})")
    put(old_fsig, 16, sha, graftable)
    base_fit = gs.garment_path("Demo", item, cur_fsig, "fit")
    base_fit.parent.mkdir(parents=True, exist_ok=True)
    base_fit.write_bytes(b"BASE FIT")
    import hashlib
    cur = put(cur_fsig, 18, sha, {**graftable, "base_fit_sha256": hashlib.sha256(b"BASE FIT").hexdigest()})
    e = served()
    check(e["fit"] == cur and e["fsig"] == cur_fsig, f"[H5] (e) the accepted current fit is served ({e})")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fit-honesty-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import garment_fit as gf
        reasons = test_h1(gf)
        test_h1_old()
        test_h2(gf)
        test_h3(gf, reasons)
        test_h4(gf)
        test_h5()
    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
