#!/usr/bin/env python3
"""Fit reuse (plan docs/superpowers/plans/2026-11-12-fit-sdf-speed-drape.md, Task 4 / A2c): the limb source of a
base fit is derived once per base fit, and a fit's distance tier starts Blender once (``lod``), not twice
(``measure`` + ``lod``).

Usage:
    ./.venv/bin/python scripts/smoke_fit_reuse.py

Runs against a THROWAWAY storage + instance directory — no real world, no hub, no GPU, no Blender (the runner is
stubbed), no server process. Synthetic GLBs only.

Fixture: the trunk of smoke_garment_refit_source.py [11] at a lower resolution — a closed cylinder R 0.10 over
y [0.79, 1.45] (fx.cylinder, 64 segments, 67 rings = one ring per cm), weighted Hips / Spine / Spine1 / Spine2 /
Neck by height with 50/50 rows at the joints (0.85 Hips+UpLeg, 0.95, 1.10, 1.25, 1.40), as a rigged GLB
(smoke_garment_fit.make_glb); a garment tube R 0.115 over y [0.80, 1.40] skinned 100 % to Spine2 is grafted on it
(``glb_mesh.graft``, node ``garment_clothing_t``). The trunk has no arm / leg chain, so ``limb_frames`` is empty.

Expected, derived by hand from the brief (``limb_source_from_fit``: an LRU keyed by sha256(blob), skirt, torso,
``LIMB_CACHE_SIZE = 8``; ``decimate_to(..., tris=None)``: with ``tris`` given ``measure_file`` is not called,
``ratio = min(0.999, target_tris / tris)``):

[R1] ``garment_source.limb_numbers`` wrapped to count its calls (it runs once per uncached derivation, first thing).
     a) limb_source_from_fit(blob) twice -> 1 call; both None (no limb chain, no torso: nothing to align) and
        equal.
     b) limb_source_from_fit(blob, torso=True) -> 2 calls (another key); a dict with frames ["torso"], kinds
        ["arm", "leg", "torso"]; the graft skins the garment against the TARGET's skin, so the fit's garment names
        all 7 trunk joints, every one a torso bone -> names0 = the 7 "mixamorig:" trunk names in skin order; x0 =
        the garment's vertices (65 cols x 61 rings = 3965 rows); w0 3965 x 7, the Spine2 column (5) all 1.0, the
        rest 0. Again with torso=True -> still 2 calls, the SAME object.
     c) skirt=True, torso=True -> 3 calls (third key). Then the uncached ``_limb_source_from_fit(blob,
        skirt=False, torso=True)`` -> equal arrays / lists / frames to b).
     d) LRU: ``LIMB_CACHE_SIZE`` == 8. With ``_limb_source_from_fit`` stubbed to count (cache cleared): keys
        b"k0".."k7" -> 8 calls, 8 entries; b"k0" again -> 8 calls (hit, now most recent); b"k8" -> 9 calls, 8
        entries, the least recently used b"k1" dropped: b"k1" -> 10 calls, b"k0" -> still 10. An exception in the
        derivation is not cached: a raising stub called twice -> 2 calls, both raise.
[R2] ``app.blender.runner.run`` stubbed: records the script names; ``measure`` answers tris 400, ``lod`` writes one
     output file into its out_dir and answers stages [{tris 100}] and records its params; ``runner.version`` ""
     (measure_file asks for it).
     a) decimate_to(p, 100, out, tris=400) -> runs ["lod"], ratio 0.25 (100 / 400), tris_before 400, tris 100, ok,
        ``out`` exists; the lod params' ratios [0.25].
     b) decimate_to(p, 100, out2) -> runs ["measure", "lod"], ratio 0.25 (measure's 400), ok.
     c) decimate_to(p, 100, out3, tris=50) -> ["lod"], ratio 0.999 (min(0.999, 2.0)).
     d) decimate_to(p, 100, out4, tris=0) -> no run at all, ok False, an error, ``out4`` absent.
[R3] The two fit publishers pass their count (AST of app/core/garments.py and app/core/garment_footwear.py): every
     ``decimate_to`` call there carries the keyword ``tris`` — 1 call each.

Fails on the old code (ee7d75b4): [R1a] 2 limb_numbers calls (no cache), [R1b] 3 / 4 calls and a new object,
[R1c] 5, then AttributeError ``_limb_source_from_fit``; [R2a] (run alone there) TypeError, no ``tris`` keyword.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


TRUNK_JOINTS = ["Hips", "LeftUpLeg", "RightUpLeg", "Spine", "Spine1", "Spine2", "Neck"]


def fit_glb() -> bytes:
    """The fixture fit GLB (docstring): trunk cylinder + Spine2 tube grafted on it."""
    import smoke_garment_fit as fx
    from app.core import glb_mesh
    P, F = fx.cylinder(0.10, 0.79, 1.45, nseg=64, nrings=67)
    P = np.asarray(P, np.float64)
    J = np.zeros((len(P), 4), np.int64)
    W = np.zeros((len(P), 4))
    idx = {n: i for i, n in enumerate(TRUNK_JOINTS)}
    joints = {0.95: ("Hips", "Spine"), 1.10: ("Spine", "Spine1"), 1.25: ("Spine1", "Spine2"), 1.40: ("Spine2", "Neck")}
    for i, (x, y, _z) in enumerate(P):
        y = round(float(y), 4)
        if y == 0.85:
            pair = ("Hips", "LeftUpLeg" if x >= 0 else "RightUpLeg")
        elif y in joints:
            pair = joints[y]
        else:
            bone = "Hips" if y < 0.95 else "Spine" if y < 1.10 else "Spine1" if y < 1.25 else "Spine2" if y < 1.40 \
                else "Neck"
            J[i, 0], W[i, 0] = idx[bone], 1.0
            continue
        J[i, :2], W[i, :2] = [idx[pair[0]], idx[pair[1]]], [0.5, 0.5]
    U = np.zeros((len(P), 2))
    body = fx.make_glb(P, np.asarray(F), U, joints=J, weights=W,
                       joint_names=["mixamorig:" + n for n in TRUNK_JOINTS])
    nseg, ys = 64, np.linspace(0.80, 1.40, 61)
    cols = nseg + 1
    G = np.array([(0.115 * np.cos(2 * np.pi * (j % nseg) / nseg), y, 0.115 * np.sin(2 * np.pi * (j % nseg) / nseg))
                  for y in ys for j in range(cols)])
    faces = []
    for r in range(len(ys) - 1):
        for j in range(nseg):
            a, b, c, d = r * cols + j, r * cols + j + 1, (r + 1) * cols + j + 1, (r + 1) * cols + j
            faces += [(a, c, b), (a, d, c)]
    radial = G * np.array([1.0, 0.0, 1.0])
    Jg = np.zeros((len(G), 4), np.int64)
    Wg = np.zeros((len(G), 4))
    Wg[:, 0] = 1.0
    uv = np.stack([np.arange(len(G)) % cols / nseg, np.arange(len(G)) // cols / (len(ys) - 1)], 1)
    garment = glb_mesh.GarmentMesh(positions=G, normals=radial / np.linalg.norm(radial, axis=1, keepdims=True),
                                   uvs=uv, indices=np.asarray(faces, np.int64), joints=Jg, weights=Wg,
                                   joint_names=["mixamorig:Spine2"], material={"name": "cloth"})
    return glb_mesh.graft(body, garment, name="garment_clothing_t", extras={})


def same_source(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return (set(a) == set(b) and np.array_equal(a["x0"], b["x0"]) and np.array_equal(a["w0"], b["w0"])
            and a["names0"] == b["names0"] and a["kinds"] == b["kinds"] and a["numbers"] == b["numbers"]
            and repr(a["frames"]) == repr(b["frames"]) and repr(a["torso_cover"]) == repr(b["torso_cover"])
            and repr(a["torso_open"]) == repr(b["torso_open"]))


def r1() -> None:
    from app.core import garment_source as gsrc
    print("[R1] limb source cached per base fit")
    blob = fit_glb()
    real = gsrc.limb_numbers
    calls = [0]

    def counting(*a, **k):
        calls[0] += 1
        return real(*a, **k)

    gsrc.limb_numbers = counting
    try:
        a1 = gsrc.limb_source_from_fit(blob)
        a2 = gsrc.limb_source_from_fit(blob)
        check("R1a limb_numbers calls after two plain calls", calls[0], 1)
        check("R1a both None", (a1, a2), (None, None))
        b1 = gsrc.limb_source_from_fit(blob, torso=True)
        check("R1b torso=True is another key: calls", calls[0], 2)
        check("R1b a dict", isinstance(b1, dict), True)
        if isinstance(b1, dict):
            check("R1b frames", list(b1["frames"]), ["torso"])
            check("R1b kinds", b1["kinds"], ["arm", "leg", "torso"])
            check("R1b names0", b1["names0"], ["mixamorig:" + n for n in TRUNK_JOINTS])
            check("R1b x0 rows", b1["x0"].shape, (3965, 3))
            w0 = b1["w0"]
            check("R1b w0: shape, Spine2 column 1, rest 0",
                  (w0.shape, bool(np.all(w0[:, 5] == 1.0)), bool(np.all(np.delete(w0, 5, axis=1) == 0.0))),
                  ((3965, 7), True, True))
        b2 = gsrc.limb_source_from_fit(blob, torso=True)
        check("R1b again: calls", calls[0], 2)
        check("R1b again: the same object", b2 is b1, True)
        gsrc.limb_source_from_fit(blob, skirt=True, torso=True)
        check("R1c skirt is another key: calls", calls[0], 3)
        fresh = gsrc._limb_source_from_fit(blob, skirt=False, torso=True)
        check("R1c b) equals the uncached derivation", same_source(b1, fresh), True)
    finally:
        gsrc.limb_numbers = real

    check("R1d LIMB_CACHE_SIZE", gsrc.LIMB_CACHE_SIZE, 8)
    real_derive = gsrc._limb_source_from_fit
    n = [0]

    def derive(blob, *, skirt, torso):
        n[0] += 1
        return {"blob": blob}

    gsrc._limb_cache.clear()
    gsrc._limb_source_from_fit = derive
    try:
        for i in range(8):
            gsrc.limb_source_from_fit(b"k%d" % i)
        check("R1d k0..k7: calls, entries", (n[0], len(gsrc._limb_cache)), (8, 8))
        gsrc.limb_source_from_fit(b"k0")
        check("R1d k0 again: a hit", n[0], 8)
        gsrc.limb_source_from_fit(b"k8")
        check("R1d k8: calls, entries", (n[0], len(gsrc._limb_cache)), (9, 8))
        gsrc.limb_source_from_fit(b"k1")
        check("R1d k1 was dropped (least recently used)", n[0], 10)
        gsrc.limb_source_from_fit(b"k0")
        check("R1d k0 kept", n[0], 10)

        def boom(blob, *, skirt, torso):
            n[0] += 1
            raise ValueError("broken fit")

        gsrc._limb_source_from_fit = boom
        raised = 0
        for _ in range(2):
            try:
                gsrc.limb_source_from_fit(b"bad")
            except ValueError:
                raised += 1
        check("R1d an exception is not cached: calls, raised", (n[0], raised), (12, 2))
    finally:
        gsrc._limb_source_from_fit = real_derive
        gsrc._limb_cache.clear()


def r2(tmp: Path) -> None:
    from app.blender import refine, runner
    print("[R2] the distance tier without a measure launch")
    runs, lod_params = [], []
    real_run, real_version = runner.run, runner.version

    def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
        runs.append(script)
        if script == "measure":
            return {"ok": True, "error": "", "data": {"tris": 400}, "outputs": {}, "seconds": 0.0}
        if script == "lod":
            lod_params.append(params)
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            f = out_dir / "model_lod1.glb"
            f.write_bytes(b"glTF-stub")
            return {"ok": True, "error": "", "data": {"stages": [{"tris": 100}]}, "outputs": {"lod1": str(f)},
                    "seconds": 0.0}
        return {"ok": False, "error": "unexpected script", "data": {}, "outputs": {}, "seconds": 0.0}

    runner.run, runner.version = fake_run, (lambda *a, **k: "")
    try:
        src = tmp / "fit.glb"
        src.write_bytes(b"glTF-source")
        out = tmp / "low" / "a.glb"
        res = refine.decimate_to(src, 100, out, tris=400)
        check("R2a runs", runs, ["lod"])
        check("R2a ratio, tris_before, tris, ok", (res["ratio"], res["tris_before"], res["tris"], res["ok"]),
              (0.25, 400, 100, True))
        check("R2a out written", out.is_file(), True)
        check("R2a lod ratios", lod_params[-1]["ratios"] if lod_params else None, [0.25])
        runs.clear()
        res = refine.decimate_to(src, 100, tmp / "low" / "b.glb")
        check("R2b runs without tris", runs, ["measure", "lod"])
        check("R2b ratio, ok", (res["ratio"], res["ok"]), (0.25, True))
        runs.clear()
        res = refine.decimate_to(src, 100, tmp / "low" / "c.glb", tris=50)
        check("R2c below the target: runs, ratio", (runs, res["ratio"]), (["lod"], 0.999))
        runs.clear()
        out4 = tmp / "low" / "d.glb"
        res = refine.decimate_to(src, 100, out4, tris=0)
        check("R2d tris 0: runs, ok, error, out", (runs, res["ok"], bool(res["error"]), out4.exists()),
              ([], False, True, False))
    finally:
        runner.run, runner.version = real_run, real_version


def r3() -> None:
    print("[R3] the fit publishers pass their count")
    for rel in ("app/core/garments.py", "app/core/garment_footwear.py"):
        tree = ast.parse((ROOT / rel).read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "decimate_to"]
        check(f"R3 {rel}: decimate_to calls, with tris=", (len(calls), sum(any(k.arg == "tris" for k in c.keywords)
                                                                          for c in calls)), (1, 1))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fit-reuse-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(str(root / "world"))
        r1()
        r2(root)
        r3()
    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
