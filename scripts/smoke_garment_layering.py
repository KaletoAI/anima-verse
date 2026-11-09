#!/usr/bin/env python3
"""Texture-body reuse + garment layering, Task 2: own-mesh pieces worn over each other
(plan docs/superpowers/plans/2026-11-10-texture-body-reuse-and-layering.md, Review Focus 5;
app/core/garment_fit_layers.py, app/core/garment_layers.py, app/core/garment_set.py layer order,
app/core/garment_assembly.py).

Usage:
    ./.venv/bin/python scripts/smoke_garment_layering.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no Blender, no server process. Synthetic GLBs only. Stubs: every generation entry point of
the garment chain (``garment_images.run_edit_step`` / ``cut_out``, ``garment_mesh.generate``,
``garments._fit``, ``service.get_image_service``) raises and counts — a layered fit must reach none of them;
``garment_assembly.schedule`` records; ``model3d.request_lod`` no-op.

Geometry (rigged metres, the bind space every fit lives in). Body: a closed cylinder R = 0.100 around the y axis,
y 0.60 .. 1.60, 64 segments, weighted to Spine2. Tubes: open cylinders of 64 segments at the body's angles (the
body vertex is the nearest body point of a tube vertex, so a tube vertex's body distance is exactly r - R), rings
every 1 cm, plus a seam column duplicating the first one (UV u = 1, same position). A fit GLB = the rigged body
with one tube grafted on. Clearances: CLEAR_M = LAYER_CLEAR_M = 0.0119, reach 0.015.

Expected, derived by hand:

[1] layer_over (pure math). Inner "slip" r 0.1125, y 1.00 .. 1.40; outer "coat" r 0.1080, y 0.80 .. 1.40 (fitted
    to the body alone: 8 mm clearance, INSIDE the slip). Over the slip the coat must stand LAYER_CLEAR_M above the
    slip's height 0.0125: r >= 0.1125 + 0.0119 = 0.1244. The push follows the body gradient (radial), and the
    body field beyond its exact band (6 voxels = 20.4 mm) is the voxel EDT, which reads up to 0.6 voxel SHORT on
    diagonals -> pushes up to ~2 mm further, never less: every coat vertex with y in [1.10, 1.30] has r in
    [0.1239, 0.1270] (0.5 mm below for the polygon / float tolerance). y <= 0.85 (15 rings below the slip's rim:
    beyond the reach and the displacement smoothing) is not moved (|dr| < 0.1 mm). Seam duplicates stay
    identical; UVs, joints, weights, image unchanged; normals unit length and outward (dot with the radial
    direction > 0.9 over the slip band). Report: covered_share = the coat rings whose foot is within the reach
    (0.015) of a slip foot: y 0.99 .. 1.40 = 42 of 61 rings = 0.6885; gap_p1_m >= 0.0119 - 0.0005.
    No inner -> the coat unchanged (same object), covered 0.
[2] Layer order (garment_set.layer_order; slot order inventory.VALID_PIECE_SLOTS: underwear_top 0, top 3,
    bottom 4, outer 5, feet 6). Items: slip {underwear_top}, dress {top, covers [underwear_top]}, coat {outer,
    covers [top, underwear_top]}, shoes {feet}, blouse {top, partially_covers [bottom]}, skirt {bottom, covers
    [top]}, all own_mesh; plain {top} WITHOUT the flag.
    - {coat, dress, slip, shoes} in any input order: order [slip, dress, coat, shoes]; under slip [], dress
      [slip], coat [dress, slip], shoes []; cycles []. mesh_overlaps({underwear_top: slip, top: dress, outer:
      coat}) == [] (layered: no warning any more).
    - {blouse, skirt} (over each other): rank blouse 3 < skirt 4 -> order [blouse, skirt], under skirt
      [blouse], blouse []; cycles [{items [blouse, skirt], slots [top, bottom]}] (blouse.covers ∩ skirt.worn =
      bottom, skirt.covers ∩ blouse.worn = top, sorted by rank). Input order reversed -> the same.
      mesh_overlaps({top: blouse, bottom: skirt}) == that cycle list.
    - {plain, coat}: plain is no own mesh -> order [coat], under coat [].
[3] Assembly with layers (Review Focus 5). Demo on the pipeline, base model B (the body above), body fits
    slip (r 0.1125) and coat (r 0.1080, its low tier 32 segments) accepted on sha(B). Outfit model A: bare =
    the body, sidecar mesh_items {intended [coat, slip], effective [coat, slip]}, bare low tier too.
    lsig1 = md5[:12] of {"inner": {"slip": sha(slip fit)}, "version": 1} (sorted JSON).
    - served(A, full) before a build: the bare file + schedule(Demo, A); _wanted_for: coat over {lsig lsig1,
      items [slip], pending True}, coat fit = its body fit; slip without ``over``.
    - assemble(A) -> {full: assembled, low: assembled}; layers/coat_<F>_<lsig1>.glb + .json and
      layers/low/coat_<F>_<lsig1>.glb exist; the record: accepted, lsig1, base_model_sha256 sha(B),
      base_fit_sha256 sha(coat body fit), inner {slip: {fsig, sha256 sha(slip fit), lsig None}}; the assembled
      sidecar garments.coat = {kind clothing, fsig F, sha256 sha(layer file), over lsig1}; garments.slip has no
      ``over``; the assembled coat node: r in [0.1239, 0.1270] over y [1.10, 1.30], extras.garment.over [slip];
      the low tier's coat node too (32 segments). served(A, full) = the assembled file. Hub counters 0, the
      coat's body fit bytes unchanged.
    - Inner refit (slip fit rewritten at r 0.1175 — a new mesh / fit, new sha): served(A) = bare + schedule;
      plan: coat pending with lsig2 != lsig1; assemble -> coat r in [0.1289, 0.1320] over the slip band
      (0.1175 + 0.0119 = 0.1294); hub counters still 0, no fit step, coat body fit unchanged; both lsig1 and
      lsig2 files kept (the cache).
    - Worn WITHOUT the slip: outfit model C, mesh_items effective [coat] -> _wanted_for coat has no ``over``,
      its source is the body fit; assemble(C) builds no layer (build counter 0); garments.coat.sha256 = sha(coat
      body fit). Back to A: plan coat lsig2 valid (pending False) -> assemble(A) is ``current``, 0 builds.
    - Stale inner never used: base model rewritten (B2, new sha) with only the COAT refitted on B2 -> plan over
      [coat, slip] with base sha(B2): slip has no fit there -> coat lsig "" (body fit), no build.
      Slip refitted on B2 (r 0.1125) -> ensure builds coat over it: record base_model_sha256 sha(B2), inner
      slip sha256 = sha(the new slip fit); coat r over the slip band in [0.1239, 0.1270]; the layered fits made
      from the old coat body fit are pruned (base_fit_sha256 differs).
    - Cache bound: 5 more slip variants (r 0.1130 .. 0.1150) built one after the other -> 4 layered coat fits
      remain (LAYER_KEEP), the newest kept.
    - GC grouping: parse_name(layer file) == parse_name(layer low) == (coat, F); stored_groups[(coat, F)]
      contains them.
[4] Wardrobe (Demo wears {underwear_top: slip, outer: coat}, both fits on B2): worn_layers -> {coat: {over
    [Slip], without []}}; wardrobe items coat over [Slip], slip without the keys (nothing under it); overlaps []. Slip's fit file moved away
    -> coat {over [], without [Slip]} (the outfit paints the slip on; the coat is fitted against the body
    there). Demo wears {top: blouse, bottom: skirt}: overlaps == the [2] cycle.
[5] Cycle warning: ensure over [blouse, skirt] logs one warning naming both and "slot order".

"Fails on the old code": against 47902741 garment_fit_layers / garment_layers / layer_order do not exist
(ImportError at [1]).
"""
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
R_BODY = 0.100
NSEG = 64


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


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(Path(path).read_bytes())


def solid_png(rgb, size=8) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(out, "PNG")
    return out.getvalue()


def body_arrays():
    """Closed cylinder R_BODY, y 0.60 .. 1.60 (side rings every 2.5 cm + fan caps)."""
    import smoke_garment_fit as fx
    return fx.cylinder(R_BODY, 0.60, 1.60, nseg=NSEG, nrings=41)


def body_glb() -> bytes:
    import smoke_garment_chain as chain
    from app.core.rig_contract import BASE_JOINT_NAMES
    P, F = body_arrays()
    n = len(P)
    U = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    J = np.zeros((n, 4), np.int64)
    J[:, 0] = list(BASE_JOINT_NAMES).index("Spine2")
    Wt = np.zeros((n, 4))
    Wt[:, 0] = 1.0
    return chain.rigged_glb(P, F, U, J, Wt, solid_png((200, 160, 140)))


def tube(radius, y0, y1, *, nseg=NSEG, colour=(40, 90, 160)):
    """Open tube (GarmentMesh) at the body's angles, rings every 1 cm, a seam column duplicating column 0."""
    from app.core.glb_mesh import GarmentMesh
    nrings = int(round((y1 - y0) / 0.01)) + 1
    ys = np.linspace(y0, y1, nrings)
    cols = nseg + 1
    P, U = [], []
    for i, y in enumerate(ys):
        for j in range(cols):
            a = (j % nseg) * 2 * math.pi / nseg
            P.append((radius * math.cos(a), y, radius * math.sin(a)))
            U.append((j / nseg, i / max(nrings - 1, 1)))
    F = []
    for i in range(nrings - 1):
        for j in range(nseg):
            a, b = i * cols + j, i * cols + j + 1
            c, d = (i + 1) * cols + j + 1, (i + 1) * cols + j
            F += [(a, c, b), (a, d, c)]
    n = len(P)
    P = np.array(P, float)
    radial = P * np.array([1.0, 0.0, 1.0])
    N = radial / np.linalg.norm(radial, axis=1, keepdims=True)
    J = np.zeros((n, 4), np.int64)
    Wt = np.zeros((n, 4))
    Wt[:, 0] = 1.0
    return GarmentMesh(positions=P, normals=N, uvs=np.array(U, float), indices=np.array(F, np.int64),
                       joints=J, weights=Wt, joint_names=["mixamorig:Spine2"], image=solid_png(colour),
                       mime="image/png", material={"name": "cloth"})


def radii(P):
    P = np.asarray(P, float)
    return np.hypot(P[:, 0], P[:, 2])


def band(P, lo, hi):
    P = np.asarray(P, float)
    return (P[:, 1] >= lo - 1e-6) & (P[:, 1] <= hi + 1e-6)


def node(glb: bytes, name: str):
    from app.core import glb_mesh
    from app.core.model_validate import parse_glb
    nodes = [n for n in parse_glb(glb)["gltf"].get("nodes", []) if n.get("name") == name]
    g = glb_mesh.garment_arrays(glb, node_prefix=name)
    return (nodes[0] if nodes else {}), g


def section1():
    print("[1] layer_over (pure math)")
    from app.core import garment_fit_layers as gfl
    from app.core.glb_mesh import body_arrays as read_body
    body = read_body(body_glb())
    slip = tube(0.1125, 1.00, 1.40)
    coat = tube(0.1080, 0.80, 1.40)
    check("LAYER_CLEAR_M = CLEAR_M", gfl.LAYER_CLEAR_M, 0.0119)
    out, rep = gfl.layer_over(coat, body, [slip])
    r = radii(out.positions)
    over = band(out.positions, 1.10, 1.30)
    within("coat r min over the slip", float(r[over].min()), 0.1239, 0.1270)
    within("coat r max over the slip", float(r[over].max()), 0.1239, 0.1270)
    low = band(coat.positions, 0.80, 0.85)
    within("coat below the slip unmoved (max |dr| mm)", float(np.abs(r[low] - 0.1080).max() * 1000), 0.0, 0.1)
    seam = np.arange(0, len(coat.positions), NSEG + 1)
    check("seam duplicates identical", float(np.abs(out.positions[seam] - out.positions[seam + NSEG]).max()), 0.0)
    check("uvs/joints/weights/image unchanged",
          (np.array_equal(out.uvs, coat.uvs), np.array_equal(out.joints, coat.joints),
           np.array_equal(out.weights, coat.weights), out.image == coat.image), (True, True, True, True))
    nlen = np.linalg.norm(out.normals, axis=1)
    within("normals unit (max |len-1|)", float(np.abs(nlen - 1).max()), 0.0, 1e-6)
    radial = out.positions * np.array([1.0, 0.0, 1.0])
    radial /= np.linalg.norm(radial, axis=1, keepdims=True)
    within("normals outward over the slip (min dot)", float((out.normals[over] * radial[over]).sum(1).min()),
           0.9, 1.0)
    within("covered share", rep["covered_share"], 42 / 61 - 1e-9, 42 / 61 + 1e-9)
    within("gap p1", rep["gap_p1_m"], 0.0119 - 0.0005, 0.02)
    same, rep0 = gfl.layer_over(coat, body, [])
    check("no inner: unchanged", (same is coat, rep0["covered_share"]), (True, 0.0))


def main() -> int:
    try:
        section1()
    except ImportError as e:
        check("layering modules import", str(e), "")
        print(f"\n{len(FAILS)} failure(s)")
        return 1
    with tempfile.TemporaryDirectory(prefix="garment-layering-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import (base_body, garment_assembly as ga, garment_images, garment_layers as gl,
                              garment_mesh, garment_set, garment_store as gs, garments, glb_mesh, model3d)
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        # --- stubs: nothing of the chain may run ------------------------------------
        HUB = []

        def refuse(name):
            def stub(*a, **k):
                HUB.append(name)
                raise RuntimeError(f"{name} must not run for a layered fit")
            return stub
        garment_images.run_edit_step = refuse("run_edit_step")
        garment_images.cut_out = refuse("cut_out")
        garment_mesh.generate = refuse("garment_mesh.generate")
        garments._fit = refuse("garments._fit")
        from app.imagegen import service
        service.get_image_service = refuse("image_service")
        SCHEDULED = []
        ga.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model3d.request_lod = lambda *a, **k: False
        BUILDS = []
        real_build = gl._build

        def counting_build(name, item_id, entry, inner, base_sha):
            BUILDS.append((item_id, entry["lsig"]))
            return real_build(name, item_id, entry, inner, base_sha)
        gl._build = counting_build
        WARNINGS = []
        real_warning = gl.logger.warning
        gl.logger.warning = lambda msg, *a, **k: (WARNINGS.append(msg % a), real_warning(msg, *a, **k))

        # --- [2] layer order ------------------------------------------------------------
        print("[2] layer order")

        def piece(item_id, slots, *, covers=(), partially=(), own_mesh=True):
            op = {"slots": list(slots), "covers": list(covers), "outfit_types": ["casual"]}
            if partially:
                op["partially_covers"] = list(partially)
            if own_mesh:
                op["own_mesh"] = True
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=f"a {item_id}", outfit_piece=op)["id"]
        check("items", [piece("slip", ["underwear_top"]), piece("dress", ["top"], covers=["underwear_top"]),
                        piece("coat", ["outer"], covers=["top", "underwear_top"]), piece("shoes", ["feet"]),
                        piece("blouse", ["top"], partially=["bottom"]), piece("skirt", ["bottom"], covers=["top"]),
                        piece("plain", ["top"], own_mesh=False)],
              ["slip", "dress", "coat", "shoes", "blouse", "skirt", "plain"])
        for ids in (["coat", "dress", "slip", "shoes"], ["shoes", "slip", "dress", "coat"]):
            lo = garment_set.layer_order(ids)
            check(f"order {ids}", lo, {"order": ["slip", "dress", "coat", "shoes"],
                                       "under": {"coat": ["dress", "slip"], "dress": ["slip"], "shoes": [],
                                                 "slip": []},
                                       "cycles": []})
        check("layered pair: no overlap warning",
              garment_set.mesh_overlaps({"underwear_top": "slip", "top": "dress", "outer": "coat"}), [])
        cycle = [{"items": ["blouse", "skirt"], "slots": ["top", "bottom"]}]
        for ids in (["blouse", "skirt"], ["skirt", "blouse"]):
            check(f"cycle {ids}", garment_set.layer_order(ids),
                  {"order": ["blouse", "skirt"], "under": {"blouse": [], "skirt": ["blouse"]}, "cycles": cycle})
        check("cycle overlap warning", garment_set.mesh_overlaps({"top": "blouse", "bottom": "skirt"}), cycle)
        check("no flag: not layered", garment_set.layer_order(["plain", "coat"]),
              {"order": ["coat"], "under": {"coat": []}, "cycles": []})

        # --- fixture: Demo, base model, body fits ------------------------------------------
        print("[3] assembly with layers")
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        for item in ("slip", "coat", "blouse", "skirt"):
            inventory.add_to_inventory("Demo", item)
        cdir = get_character_dir("Demo")
        mdir = cdir / "model3d"
        mdir.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        rigged = body_glb()

        def write_base(data: bytes) -> str:
            (mdir / f"{bsig}.glb").write_bytes(data)
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            return sha_bytes(data)
        base_sha = write_base(rigged)
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))
        fsig = {i: gs.garment_fsig("Demo", i) for i in ("slip", "coat")}

        def write_fit(item_id, garment, base_bytes, *, low=None):
            fit = gs.garment_path("Demo", item_id, fsig[item_id], "fit")
            fit.parent.mkdir(parents=True, exist_ok=True)
            blob = glb_mesh.graft(base_bytes, garment, name=f"garment_clothing_{item_id}",
                                  extras={"kind": "clothing", "item_id": item_id, "fsig": fsig[item_id]})
            fit.write_bytes(blob)
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": "clothing", "item_id": item_id, "fsig": fsig[item_id],
                "base_signature": bsig, "base_model_sha256": sha_bytes(base_bytes)})
            lowp = gs.garment_path("Demo", item_id, fsig[item_id], "low")
            if low is not None:
                lowp.parent.mkdir(parents=True, exist_ok=True)
                lowp.write_bytes(glb_mesh.graft(base_bytes, low, name=f"garment_clothing_{item_id}",
                                                extras={"kind": "clothing", "item_id": item_id,
                                                        "fsig": fsig[item_id]}))
            else:
                lowp.unlink(missing_ok=True)
            return fit
        slip_fit = write_fit("slip", tube(0.1125, 1.00, 1.40, colour=(200, 200, 200)), rigged)
        coat_fit = write_fit("coat", tube(0.1080, 0.80, 1.40), rigged, low=tube(0.1080, 0.80, 1.40, nseg=32))
        coat_body_sha = sha(coat_fit)

        def write_outfit(signature, effective, intended, base_sha_now):
            meta = {"rig": "mixamo", "format": "glb", "signature": signature, "source": "base_body",
                    "base_signature": bsig, "base_model_sha256": base_sha_now, "pieces": {}, "items": [],
                    "mesh_items": {"intended": intended, "effective": effective, "warnings": []}}
            for p in (mdir / f"{signature}.glb", mdir / "low" / f"{signature}.glb"):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((mdir / f"{bsig}.glb").read_bytes())
                p.with_suffix(".json").write_text(json.dumps(meta))
            return mdir / f"{signature}.glb"
        bare_a = write_outfit("outfitA", ["coat", "slip"], ["coat", "slip"], base_sha)

        def lsig_of(inner):
            payload = json.dumps({"version": 1, "inner": inner}, sort_keys=True)
            return hashlib.md5(payload.encode()).hexdigest()[:12]
        lsig1 = lsig_of({"slip": sha(slip_fit)})
        check("layer_sig rule", gl.layer_sig({"slip": sha(slip_fit)}), lsig1)

        SCHEDULED.clear()
        check("served before the build = bare", ga.served("Demo", bare_a, "full"), bare_a)
        check("scheduled", SCHEDULED, [("Demo", "outfitA")])
        wanted = {g["item_id"]: g for g in ga._wanted_for("Demo", mdir, "outfitA")}
        check("coat pending over slip", (wanted["coat"].get("over"), wanted["coat"]["fit"]),
              ({"lsig": lsig1, "items": ["slip"], "pending": True, "without": []}, coat_fit))
        check("slip plain", wanted["slip"].get("over"), None)

        res = ga.assemble("Demo", "outfitA")
        check("assemble A", res, {"ok": True, "tiers": {"full": "assembled", "low": "assembled"}})
        layer = gs.garment_path("Demo", "coat", fsig["coat"], "layer", lsig=lsig1)
        layer_low = gs.garment_path("Demo", "coat", fsig["coat"], "layer_low", lsig=lsig1)
        check("layer files", (layer.is_file(), layer.with_suffix(".json").is_file(), layer_low.is_file()),
              (True, True, True))
        rec = gs.read_record(layer.with_suffix(".json"))
        check("layer record", {k: rec.get(k) for k in ("accepted", "lsig", "base_model_sha256", "base_fit_sha256",
                                                        "inner")},
              {"accepted": True, "lsig": lsig1, "base_model_sha256": base_sha, "base_fit_sha256": coat_body_sha,
               "inner": {"slip": {"fsig": fsig["slip"], "sha256": sha(slip_fit), "lsig": None}}})
        asm = mdir / "assembled" / "outfitA.glb"
        side = json.loads(asm.with_suffix(".json").read_text())
        check("assembled coat entry", side["garments"]["coat"],
              {"kind": "clothing", "fsig": fsig["coat"], "sha256": sha(layer), "over": lsig1})
        check("assembled slip entry has no over", "over" in side["garments"]["slip"], False)
        n, g = node(asm.read_bytes(), "garment_clothing_coat")
        r = radii(g.positions)[band(g.positions, 1.10, 1.30)]
        within("assembled coat r min", float(r.min()), 0.1239, 0.1270)
        within("assembled coat r max", float(r.max()), 0.1239, 0.1270)
        check("coat node extras over", (n.get("extras") or {}).get("garment", {}).get("over"), ["slip"])
        _n, gl_low = node((mdir / "assembled" / "low" / "outfitA.glb").read_bytes(), "garment_clothing_coat")
        r = radii(gl_low.positions)[band(gl_low.positions, 1.10, 1.30)]
        check("low coat 32 segments", len(gl_low.positions), 33 * 61)
        within("low coat r min", float(r.min()), 0.1239, 0.1270)
        check("served = assembled", ga.served("Demo", bare_a, "full"), asm)
        check("no chain step ran", HUB, [])
        check("coat body fit unchanged", sha(coat_fit), coat_body_sha)

        print("    inner refit")
        write_fit("slip", tube(0.1175, 1.00, 1.40, colour=(200, 200, 200)), rigged)
        lsig2 = lsig_of({"slip": sha(slip_fit)})
        SCHEDULED.clear()
        check("served after the inner refit = bare", ga.served("Demo", bare_a, "full"), bare_a)
        check("scheduled again", SCHEDULED, [("Demo", "outfitA")])
        planned = gl.plan("Demo", ["coat", "slip"], base_sha=base_sha, intended=["coat", "slip"])
        check("coat pending over the new slip", (planned["coat"]["lsig"], planned["coat"]["pending"]),
              (lsig2, True))
        check("lsig changed", lsig2 != lsig1, True)
        BUILDS.clear()
        check("assemble A again", ga.assemble("Demo", "outfitA"),
              {"ok": True, "tiers": {"full": "assembled", "low": "assembled"}})
        check("one layer build", BUILDS, [("coat", lsig2)])
        _n, g = node(asm.read_bytes(), "garment_clothing_coat")
        r = radii(g.positions)[band(g.positions, 1.10, 1.30)]
        within("refitted coat r min", float(r.min()), 0.1289, 0.1320)
        within("refitted coat r max", float(r.max()), 0.1289, 0.1320)
        check("still no chain step", HUB, [])
        check("coat body fit still unchanged", sha(coat_fit), coat_body_sha)
        check("both layered fits kept", sorted(p.name for p in layer.parent.glob("coat_*.glb")),
              sorted([f"coat_{fsig['coat']}_{lsig1}.glb", f"coat_{fsig['coat']}_{lsig2}.glb"]))

        print("    worn without the slip")
        bare_c = write_outfit("outfitC", ["coat"], ["coat"], base_sha)
        wanted = {g["item_id"]: g for g in ga._wanted_for("Demo", mdir, "outfitC")}
        check("C: coat body fit, no over", (wanted["coat"].get("over"), wanted["coat"]["fit"]), (None, coat_fit))
        BUILDS.clear()
        check("assemble C", ga.assemble("Demo", "outfitC")["ok"], True)
        side = json.loads((mdir / "assembled" / "outfitC.json").read_text())
        check("C: coat entry = body fit", side["garments"]["coat"],
              {"kind": "clothing", "fsig": fsig["coat"], "sha256": coat_body_sha})
        check("C: served", ga.served("Demo", bare_c, "full"), mdir / "assembled" / "outfitC.glb")
        planned = gl.plan("Demo", ["coat", "slip"], base_sha=base_sha, intended=["coat", "slip"])
        check("A again: stored layer valid", (planned["coat"]["lsig"], planned["coat"]["pending"]), (lsig2, False))
        check("assemble A: current", ga.assemble("Demo", "outfitA"),
              {"ok": True, "tiers": {"full": "current", "low": "current"}})
        check("toggling built nothing", BUILDS, [])

        print("    base model changed: never over a stale inner")
        P, F = body_arrays()
        import smoke_garment_chain as chain
        from app.core.rig_contract import BASE_JOINT_NAMES
        n_v = len(P)
        J = np.zeros((n_v, 4), np.int64)
        J[:, 0] = list(BASE_JOINT_NAMES).index("Spine2")
        Wt = np.zeros((n_v, 4))
        Wt[:, 0] = 1.0
        U = np.stack([(np.arange(n_v) % 1000) / 1000.0, (np.arange(n_v) // 1000) / 1000.0], 1)
        rigged2 = chain.rigged_glb(P, F, U, J, Wt, solid_png((190, 150, 130)))
        base2 = write_base(rigged2)
        check("new base sha", base2 != base_sha, True)
        coat_fit = write_fit("coat", tube(0.1080, 0.80, 1.40), rigged2, low=tube(0.1080, 0.80, 1.40, nseg=32))
        BUILDS.clear()
        planned = gl.ensure("Demo", ["coat", "slip"], base_sha=base2, intended=["coat", "slip"])
        check("slip has no fit on B2 -> coat body fit", (sorted(planned), planned["coat"]["lsig"],
                                                         planned["coat"]["source"]), (["coat"], "", coat_fit))
        check("no build against the stale slip", BUILDS, [])
        write_fit("slip", tube(0.1125, 1.00, 1.40, colour=(200, 200, 200)), rigged2)
        planned = gl.ensure("Demo", ["coat", "slip"], base_sha=base2, intended=["coat", "slip"])
        lsig3 = lsig_of({"slip": sha(slip_fit)})
        check("coat layered over the B2 slip", (planned["coat"]["lsig"], planned["coat"]["pending"], BUILDS),
              (lsig3, False, [("coat", lsig3)]))
        layer3 = gs.garment_path("Demo", "coat", fsig["coat"], "layer", lsig=lsig3)
        rec = gs.read_record(layer3.with_suffix(".json"))
        check("B2 record", (rec["base_model_sha256"], rec["base_fit_sha256"], rec["inner"]["slip"]["sha256"]),
              (base2, sha(coat_fit), sha(slip_fit)))
        g = glb_mesh.garment_arrays(layer3.read_bytes())
        r = radii(g.positions)[band(g.positions, 1.10, 1.30)]
        within("B2 coat r min", float(r.min()), 0.1239, 0.1270)
        check("old-body-fit layers pruned", sorted(p.name for p in layer.parent.glob("coat_*.glb")),
              [f"coat_{fsig['coat']}_{lsig3}.glb"])
        check("old-body-fit low layers pruned", sorted(p.name for p in layer_low.parent.glob("coat_*.glb")),
              [f"coat_{fsig['coat']}_{lsig3}.glb"])

        print("    cache bound")
        for i, radius in enumerate((0.1130, 0.1135, 0.1140, 0.1145, 0.1150)):
            write_fit("slip", tube(radius, 1.00, 1.40, colour=(200, 200, 200 - i)), rigged2)
            gl.ensure("Demo", ["coat", "slip"], base_sha=base2, intended=["coat", "slip"])
        newest = lsig_of({"slip": sha(slip_fit)})
        kept = sorted(p.stem.rsplit("_", 1)[1] for p in layer.parent.glob("coat_*.glb"))
        check("LAYER_KEEP layered fits", len(kept), gl.LAYER_KEEP)
        check("the newest kept", newest in kept, True)
        check("GC grouping", (gs.parse_name(layer3) if layer3.exists() else gs.parse_name(
            gs.garment_path("Demo", "coat", fsig["coat"], "layer", lsig=newest)),
            gs.parse_name(gs.garment_path("Demo", "coat", fsig["coat"], "layer_low", lsig=newest))),
            (("coat", fsig["coat"]), ("coat", fsig["coat"])))
        group = gs.stored_groups("Demo")[("coat", fsig["coat"])]
        check("stored group holds the layers",
              gs.garment_path("Demo", "coat", fsig["coat"], "layer", lsig=newest) in group
              and gs.garment_path("Demo", "coat", fsig["coat"], "layer_low", lsig=newest) in group, True)
        check("accepted_fit still the body fit", gs.accepted_fit("Demo", "coat", base_model_sha=base2)[0], coat_fit)
        check("no chain step at all", HUB, [])

        # --- [4] wardrobe -------------------------------------------------------------------
        print("[4] wardrobe")
        profile = get_character_profile("Demo")
        profile["equipped_pieces"] = {"underwear_top": "slip", "outer": "coat"}
        save_character_profile("Demo", profile)
        check("worn_layers", garment_set.worn_layers("Demo", base_model_sha=base2),
              {"coat": {"over": ["Slip"], "without": []}})
        wr = garment_set.wardrobe("Demo")
        check("wardrobe chips", ({k: wr["items"][k].get("over") for k in ("coat", "slip")},
                                 wr["items"]["coat"]["without"], wr["overlaps"]),
              ({"coat": ["Slip"], "slip": None}, [], []))
        moved = slip_fit.with_name("moved.glb")
        os.replace(slip_fit, moved)
        check("worn_layers without the slip fit", garment_set.worn_layers("Demo", base_model_sha=base2),
              {"coat": {"over": [], "without": ["Slip"]}})
        check("wardrobe chip without", garment_set.wardrobe("Demo")["items"]["coat"]["without"], ["Slip"])
        os.replace(moved, slip_fit)
        profile = get_character_profile("Demo")
        profile["equipped_pieces"] = {"top": "blouse", "bottom": "skirt"}
        save_character_profile("Demo", profile)
        check("wardrobe cycle warning", garment_set.wardrobe("Demo")["overlaps"], cycle)

        # --- [5] cycle warning on a build ------------------------------------------------------
        print("[5] cycle warning")
        WARNINGS.clear()
        gl.ensure("Demo", ["blouse", "skirt"], base_sha=base2, intended=["blouse", "skirt"])
        hits = [w for w in WARNINGS if "blouse" in w and "skirt" in w and "slot order" in w]
        check("one cycle warning", len(hits), 1)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
