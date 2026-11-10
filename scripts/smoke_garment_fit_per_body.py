#!/usr/bin/env python3
"""Fits per body (plan docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 2; spec
docs/superpowers/specs/2026-11-10-outfit-body-mesh-mode-design.md "Fits per body"): an own-mesh garment and the
hair are fitted per BODY — key (item, fsig, body id) — and an outfit model on an outfit body carries exactly that
body's fits.

Usage:
    ./.venv/bin/python scripts/smoke_garment_fit_per_body.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no Blender, no server process. Synthetic GLBs only.

Stubs: every generation entry point of the garment chain (``garment_images.run_edit_step`` / ``cut_out``,
``garment_mesh.generate``, ``garments._fit`` (the BASE fit), ``service.get_image_service``) raises and counts into
HUB — a fit on a body must reach none of them; ``garment_images._mask`` (rembg) returns a full mask and records the
image name; ``garment_fit.fit_clothing`` / ``fit_hair`` record (kind, item, sha256 of the rigged + unrigged body
they got) into FITS and return a tube around the body they were GIVEN — radius = that body's radius + 0.0125
(slip), + 0.0080 (coat), + 0.0150 (hair, y 1.45 .. 1.60) — or refuse ("too tight") when the rigged body's sha is in
REFUSE; ``refine.decimate_to`` copies the fit as its distance tier; ``garment_assembly.schedule`` records;
``model3d.request_lod`` no-op. Layering (``garment_fit_layers.layer_over``), the assembly, the store and the
refit sweep are REAL.

Fixture: Demo on the pipeline, hair method edit_chain, hair item H worn; own-mesh pieces slip {underwear_top} and
coat {outer, covers [top, underwear_top]} held. Base model = closed cylinder R 0.100 (y 0.60 .. 1.60, Spine2);
base fits of coat, slip, H (records accepted on sha(base), fit_version current) with an accepted prepared mesh
and ghost front each. Outfit bodies (rigged cylinder + unrigged copy + front view tpose_<id>.png): A =
outfit_body_id("tex" + "a"*12), R 0.100 but another texture colour (so sha(A) != sha(base)); B =
outfit_body_id("tex" + "b"*12), R 0.104; C = outfit_body_id("tex" + "c"*12), R 0.100, third colour. Outfit models
(bare = a copy of their body, sidecar body_id + body_sha256, outfit_body_mode mesh): OA on A {coat, slip}; OA2 on A
{coat}; OB on B {coat}; OB2 on B {coat, slip}; OC on C {coat}; OR on the base (retexture, no body_id) {}.

Expected, derived by hand from the spec ("a garment fit is keyed by (item, fsig, body id) ... a fit is never served
on another body") and the plan's Task 2 bullet:

[1] Store: garment_path(fit) with body "" and with body = base signature is garments/coat_<F>.glb (unchanged); with
    body A it is garments/bodies/<A>/coat_<F>.glb, low -> bodies/<A>/low/, failed -> bodies/<A>/failed/<..>.json,
    layer -> bodies/<A>/layers/coat_<F>_<lsig>.glb; image/prepared ignore the body (shared); body "x" -> ValueError;
    body_of(bodies/<A>/low/x.glb) = A, body_of(garments/x.glb) = "".
[2] Two bodies -> two fits. Before a build: served(OA) = the bare file + schedule (Demo, OA); _wanted_for(OA) lists
    coat, H, slip each with fit None + pending. assemble(OA) = {full assembled, low assembled}; FITS = 3 calls
    (coat, H, slip), each on (sha(A), sha(A unrigged)); every mask read for a body fit is tpose_<A>.png (+ the
    ghost fronts). bodies/<A>/{coat,H,slip}_<F>.glb exist; the coat record: accepted, body_id A, body_sha256 sha(A),
    base_signature bsig, base_fit_sha256 sha(base coat fit), fit_version 7 (clothing), no base_model_sha256. Assembled OA:
    garments.H.sha256 = sha(bodies/<A>/H fit) != sha(base H fit); garments.slip = sha(bodies/<A>/slip); garments.coat
    over lsigA = md5[:12]({"inner": {"slip": sha(A slip fit)}, "version": 1}); served(OA) = the assembled file.
    assemble(OB) -> 2 more FITS (coat, H) on (sha(B), sha(B unrigged)); the B coat node r = 0.104 + 0.008 = 0.112,
    H r = 0.119 (±1e-6); A's files byte-identical. assemble(OA2) (body A again, coat only — two outfits, one body,
    Review Focus 4) -> 0 FITS, garments.coat.sha256 = sha(A coat fit) (no ``over``). HUB 0; base fit files
    byte-identical.
[3] Never on another body: built_on_fit_base(OB meta, A coat record) False; (OA meta, A coat record) True; (OA meta,
    base coat record) False; (OR meta = base sha, A coat record) False; ({base_signature bsig} only, A coat record)
    False. A's coat fit + record copied over B's: body_fit_state(B) "stale"; _wanted_for(OB) coat pending;
    assemble(OB) -> 1 FIT on sha(B); B's coat record body_id B again.
[4] Hair per body: the H records on A and B have kind hair and their own body_id; the retexture outfit OR wants H =
    the BASE fit garments/H_<F>.glb (unchanged path).
[5] Layering per body: bodies/<A>/layers/coat_<F>_<lsigA>.glb + .json + layers/low/…; record body_id A,
    body_sha256 sha(A), base_fit_sha256 sha(A coat fit), inner.slip.sha256 sha(A slip fit), no base_model_sha256;
    the assembled OA coat node r in [0.1239, 0.1270] over y [1.10, 1.30] (slip on A at 0.1125 + LAYER_CLEAR_M
    0.0119 = 0.1244; tolerance as smoke_garment_layering). assemble(OB2) -> 1 FIT (slip on B), layer
    bodies/<B>/layers/coat_<F>_<lsigB>.glb with lsigB = md5[:12]({"inner": {"slip": sha(B slip fit)}, ...}) != lsigA,
    coat r in [0.1279, 0.1310] (0.1165 + 0.0119 = 0.1284). No garments/layers/ of the base.
[6] FIT_VERSION per body: FIT_VERSION -> {hair 8, clothing 8}, the base records rewritten with fit_version 8 (the
    base sweep's result, GLBs unchanged): body_fit_state of coat on A and on B "stale"; outdated_fits = [];
    outdated_body_fits = the 6 body fits {coat, H, slip} x {A, B}; _wanted_for(OA) coat pending. refit_character
    -> those 6 as "<item>@<body>", 6 FITS each on its own body sha; every body record fit_version 8; afterwards
    outdated_body_fits [] and _wanted_for(OA) has no pending entry. HUB 0. FIT_VERSION restored.
[7] Refusal per body. C: REFUSE = {sha(C)}: body_fit_warning(OC meta) = NOT_FITTED_ON_BODY with "Coat (fit on the
    outfit body refused — too tight), Hair (… too tight)"; failed records on C; a second call -> 0 FITS.
    _wanted_for(OC) = [] (nothing pending), assemble(OC) builds nothing, served(OC) = bare, no schedule. R11 on B:
    the base coat fit file rewritten (new base_fit_sha), REFUSE = {sha(B)}: assemble(OB) -> 1 FIT refused, the B
    coat fit served is the OLD one (sha unchanged), the failure holds (a second assemble -> 0 FITS, "current").
    An OLDER FIT_VERSION is not kept (coordinator ruling 2026-11-10): the B coat record's fit_version set to
    FIT_VERSION - 1 (the refusal of its replacement still holding) -> wanted(OB) has no coat,
    body_fit_warning(meta_ob) = NOT_FITTED_ON_BODY with "Coat (fit on the outfit body refused — too tight)",
    0 FITS; the record restored afterwards -> the coat is served again.
[8] Body rebuilt: A's file rewritten (new colour): OA's wanted coat = the A coat fit (made on OA's body_sha256);
    assemble(OA) -> 0 FITS (nothing is fitted on a body whose stored bytes are no longer the model's).
[9] Groups: stored_groups[(coat, F)] holds bodies/<A>/coat_<F>.glb, bodies/<B>/coat_<F>.glb and the layered files;
    body_of names their body.
[10] Tab status: outfit_body_mode mesh, the current outfit's model = OB's copy (body B): garment_info(coat).body =
    {body_id B, status "failed", error "fit on the outfit body refused — too tight"} (the [7] failure), body_id B;
    garment_info(H).body.status "accepted"; garment_info(slip).body None (not carried); piece_status passes body.
    Mode retexture -> garment_info(coat).body None.
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
NSEG = 64
OFFSET = {"slip": 0.0125, "coat": 0.0080, "hair": 0.0150}


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


def body_glb(radius: float, colour) -> bytes:
    import smoke_garment_chain as chain
    import smoke_garment_fit as fx
    from app.core.rig_contract import BASE_JOINT_NAMES
    P, F = fx.cylinder(radius, 0.60, 1.60, nseg=NSEG, nrings=41)
    n = len(P)
    U = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    J = np.zeros((n, 4), np.int64)
    J[:, 0] = list(BASE_JOINT_NAMES).index("Spine2")
    Wt = np.zeros((n, 4))
    Wt[:, 0] = 1.0
    return chain.rigged_glb(P, F, U, J, Wt, solid_png(colour))


def tube(radius, y0, y1, *, nseg=NSEG, colour=(40, 90, 160)):
    """Open tube (GarmentMesh), rings every 1 cm, a seam column duplicating column 0 (smoke_garment_layering)."""
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


SPAN = {"slip": (1.00, 1.40), "coat": (0.80, 1.40), "hair": (1.45, 1.60)}


def radii(P):
    P = np.asarray(P, float)
    return np.hypot(P[:, 0], P[:, 2])


def band(P, lo, hi):
    P = np.asarray(P, float)
    return (P[:, 1] >= lo - 1e-6) & (P[:, 1] <= hi + 1e-6)


def node(glb: bytes, name: str):
    from app.core import glb_mesh
    return glb_mesh.garment_arrays(glb, node_prefix=name)


def main() -> int:
    try:
        from app.core.garments import body_fit, body_fit_state, fit_on_body  # noqa: F401
        from app.core.garment_assembly import body_fit_warning  # noqa: F401
        from app.core.garment_refit import outdated_body_fits  # noqa: F401
    except ImportError as e:
        check("fits-per-body API imports", str(e), "")
        print(f"\n{len(FAILS)} failure(s)")
        return 1
    with tempfile.TemporaryDirectory(prefix="garment-fit-per-body-") as tmp:
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

        from app.blender import refine
        from app.core import (base_body, garment_assembly as ga, garment_fit, garment_hair, garment_images,
                              garment_mesh, garment_refit, garment_set, garment_store as gs, garments, glb_mesh,
                              model3d)
        from app.core.garment_fit import FitResult
        from app.core.model_refs import current_outfit_state
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        # --- stubs -----------------------------------------------------------------------
        HUB, FITS, MASKS, SCHEDULED = [], [], [], []
        REFUSE: set = set()

        def refuse(name):
            def stub(*a, **k):
                HUB.append(name)
                raise RuntimeError(f"{name} must not run for a fit on a body")
            return stub
        garment_images.run_edit_step = refuse("run_edit_step")
        garment_images.cut_out = refuse("cut_out")
        garment_mesh.generate = refuse("garment_mesh.generate")
        garments._fit = refuse("garments._fit")
        from app.imagegen import service
        service.get_image_service = refuse("image_service")
        garment_images._mask = lambda path, size: (MASKS.append(Path(path).name),
                                                   np.ones((size[1], size[0]), bool))[1]
        ga.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model3d.request_lod = lambda *a, **k: False

        def decimate(src, target, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate

        def fake_fit(kind_key, rigged: bytes, unrigged: bytes):
            body = glb_mesh.body_arrays(rigged)
            radius = float(radii(body.positions).max())
            FITS.append((kind_key, sha_bytes(rigged), sha_bytes(unrigged)))
            if sha_bytes(rigged) in REFUSE:
                return FitResult(garment=tube(0.05, 1.0, 1.1), metrics={"tris": 1}, ok=False,
                                 reasons=["too tight"], report={})
            y0, y1 = SPAN[kind_key]
            g = tube(radius + OFFSET[kind_key], y0, y1)
            return FitResult(garment=g, metrics={"tris": len(g.indices)}, ok=True, reasons=[], report={})

        def fit_clothing(prepared, unrigged, rigged, *, masks, slots, limb_source=None):
            return fake_fit(CURRENT["item"], rigged, unrigged)

        CURRENT = {"item": ""}
        real_fit_on_body = garments.fit_on_body

        def tracking_fit_on_body(character_name, item_id, **kw):
            CURRENT["item"] = "hair" if item_id == hid else item_id
            return real_fit_on_body(character_name, item_id, **kw)
        garments.fit_on_body = tracking_fit_on_body
        garment_fit.fit_clothing = fit_clothing
        HAIR_GATES = []

        def fit_hair(prepared, unrigged, rigged, bald, ghost, *, gates=None):
            HAIR_GATES.append(sorted(gates or {}))
            return fake_fit("hair", rigged, unrigged)
        garment_fit.fit_hair = fit_hair

        # --- fixture -----------------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair with a side parting", "hair_method": "edit_chain",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair worn", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hid})

        def piece(item_id, slots, *, covers=()):
            op = {"slots": list(slots), "covers": list(covers), "outfit_types": ["casual"], "own_mesh": True}
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=f"a {item_id}", outfit_piece=op)["id"]
        check("items", [piece("slip", ["underwear_top"]), piece("coat", ["outer"], covers=["top", "underwear_top"])],
              ["slip", "coat"])
        for item in ("slip", "coat"):
            inventory.add_to_inventory("Demo", item)
        cdir = get_character_dir("Demo")
        mdir = cdir / "model3d"
        refs = cdir / "model_refs"
        for d in (mdir / "unrigged", refs):
            d.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        base_bytes = body_glb(0.100, (200, 160, 140))
        (mdir / f"{bsig}.glb").write_bytes(base_bytes)
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        (refs / f"tpose_{bsig}.png").write_bytes(solid_png((210, 180, 160), 16))
        (refs / f"tpose_back_{bsig}.png").write_bytes(solid_png((205, 175, 155), 16))
        base_sha = sha_bytes(base_bytes)
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))
        items = {"coat": "coat", "slip": "slip", "hair": hid}
        fsig = {k: gs.garment_fsig("Demo", i) for k, i in items.items()}
        kinds = {"coat": "clothing", "slip": "clothing", "hair": "hair"}
        base_fit = {}
        for key, item_id in items.items():
            f = fsig[key]
            prepared = gs.garment_path("Demo", item_id, f, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(glb_mesh.graft(base_bytes, tube(0.2, 1.0, 1.1), name="g", extras={}))
            gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
            ghost = gs.garment_path("Demo", item_id, f, "image", step="ghost", view="front")
            ghost.parent.mkdir(parents=True, exist_ok=True)
            ghost.write_bytes(solid_png((90, 90, 90), 16))
            gs.write_record(ghost.with_suffix(".json"), {"accepted": True})
            fit = gs.garment_path("Demo", item_id, f, "fit")
            y0, y1 = SPAN[key]
            fit.write_bytes(glb_mesh.graft(base_bytes, tube(0.100 + OFFSET[key], y0, y1),
                                           name=f"garment_{kinds[key]}_{item_id}",
                                           extras={"kind": kinds[key], "item_id": item_id, "fsig": f}))
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": kinds[key], "item_id": item_id, "fsig": f, "base_signature": bsig,
                "base_model_sha256": base_sha, "fit_version": garment_fit.FIT_VERSION[kinds[key]],
                "inputs": {"prepared_sha256": sha(prepared)}})
            base_fit[key] = fit
        base_fit_sha = {k: sha(p) for k, p in base_fit.items()}

        def make_body(tsig_char, radius, colour):
            bid = base_body.outfit_body_id("tex" + tsig_char * 12)
            data = body_glb(radius, colour)
            (mdir / f"{bid}.glb").write_bytes(data)
            (mdir / f"{bid}.json").write_text(json.dumps({
                "rig": "mixamo", "format": "glb", "signature": bid,
                "outfit_body": {"body_id": bid, "mode": "mesh", "version": 1, "texture_signature": "tex" + tsig_char * 12,
                                "base_signature": bsig}}))
            unrigged = body_glb(radius * 0.5, colour)  # another frame: the fit must get THIS body's own source
            (mdir / "unrigged" / f"{bid}.glb").write_bytes(unrigged)
            (refs / f"tpose_{bid}.png").write_bytes(solid_png(colour, 16))
            return bid, sha_bytes(data), sha_bytes(unrigged)
        A, sha_a, unr_a = make_body("a", 0.100, (190, 150, 130))
        B, sha_b, unr_b = make_body("b", 0.104, (180, 140, 120))
        C, sha_c, unr_c = make_body("c", 0.100, (170, 130, 110))
        check("three distinct bodies", len({sha_a, sha_b, sha_c, base_sha}), 4)

        def write_outfit(signature, body_id, effective):
            src = mdir / f"{body_id or bsig}.glb"
            meta = {"rig": "mixamo", "format": "glb", "signature": signature, "source": "base_body",
                    "base_signature": bsig, "base_model_sha256": base_sha, "pieces": {}, "items": [],
                    "mesh_items": {"intended": effective, "effective": effective, "warnings": []}}
            if body_id:
                meta.update(outfit_body_mode="mesh", body_id=body_id, body_sha256=sha(src), dressed=True)
            for p in (mdir / f"{signature}.glb", mdir / "low" / f"{signature}.glb"):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(src.read_bytes())
                p.with_suffix(".json").write_text(json.dumps(meta))
            return mdir / f"{signature}.glb", meta
        OA, meta_oa = write_outfit("OA", A, ["coat", "slip"])
        OA2, _ = write_outfit("OA2", A, ["coat"])
        OB, meta_ob = write_outfit("OB", B, ["coat"])
        OB2, _ = write_outfit("OB2", B, ["coat", "slip"])
        OC, meta_oc = write_outfit("OC", C, ["coat"])
        OR, meta_or = write_outfit("OR", "", [])

        def body_file(key, body):
            return gs.garment_path("Demo", items[key], fsig[key], "fit", body=body)

        def wanted(signature):
            return {g["item_id"]: g for g in ga._wanted_for("Demo", mdir, signature)}

        def assembled_side(signature):
            return json.loads((mdir / "assembled" / f"{signature}.json").read_text())

        # --- [1] store layout -----------------------------------------------------------------
        print("[1] store layout")
        groot = cdir / "garments"
        fc = fsig["coat"]
        check("base body path unchanged", (gs.garment_path("Demo", "coat", fc, "fit"),
                                           gs.garment_path("Demo", "coat", fc, "fit", body=bsig)),
              (groot / f"coat_{fc}.glb",) * 2)
        check("body fit path", gs.garment_path("Demo", "coat", fc, "fit", body=A), groot / "bodies" / A / f"coat_{fc}.glb")
        check("body low/failed/layer", (gs.garment_path("Demo", "coat", fc, "low", body=A),
                                        gs.garment_path("Demo", "coat", fc, "failed", body=A),
                                        gs.garment_path("Demo", "coat", fc, "layer", lsig="0" * 12, body=A)),
              (groot / "bodies" / A / "low" / f"coat_{fc}.glb", groot / "bodies" / A / "failed" / f"coat_{fc}.json",
               groot / "bodies" / A / "layers" / f"coat_{fc}_{'0' * 12}.glb"))
        check("shared parts ignore the body", (gs.garment_path("Demo", "coat", fc, "prepared", body=A),
                                               gs.garment_path("Demo", "coat", fc, "image", step="ghost",
                                                               view="front", body=A)),
              (groot / "prepared" / f"coat_{fc}.glb", groot / "images" / f"coat_{fc}_ghost_front.png"))
        try:
            gs.garment_path("Demo", "coat", fc, "fit", body="x")
            bad = "no error"
        except ValueError:
            bad = "ValueError"
        check("invalid body", bad, "ValueError")
        check("body_of", (gs.body_of(groot / "bodies" / A / "low" / "x.glb"), gs.body_of(groot / "x.glb")), (A, ""))

        # --- [2] two bodies -> two fits ---------------------------------------------------------
        print("[2] a piece worn on two bodies -> two fits")
        SCHEDULED.clear()
        check("served(OA) before a build = bare", ga.served("Demo", OA, "full"), OA)
        check("scheduled OA", SCHEDULED, [("Demo", "OA")])
        w = wanted("OA")
        check("serve: all pending, no fit", {k: (g["fit"], g.get("pending")) for k, g in w.items()},
              {"coat": (None, True), hid: (None, True), "slip": (None, True)})
        FITS.clear()
        MASKS.clear()
        check("assemble OA", ga.assemble("Demo", "OA"), {"ok": True, "tiers": {"full": "assembled", "low": "assembled"}})
        check("OA: 3 fits on body A", sorted(FITS), sorted([(k, sha_a, unr_a) for k in ("coat", "hair", "slip")]))
        check("OA: body masks = A's front view", sorted({m for m in MASKS if not m.startswith(("coat_", "slip_", hid))}),
              [f"tpose_{A}.png"])
        check("A fit files", [body_file(k, A).is_file() for k in ("coat", "hair", "slip")], [True] * 3)
        rec = gs.read_record(body_file("coat", A).with_suffix(".json"))
        check("A coat record parents", {k: rec.get(k) for k in ("accepted", "body_id", "body_sha256", "base_signature",
                                                                "base_fit_sha256", "fit_version", "item_id", "fsig")},
              {"accepted": True, "body_id": A, "body_sha256": sha_a, "base_signature": bsig,
               "base_fit_sha256": base_fit_sha["coat"], "fit_version": 7, "item_id": "coat", "fsig": fc})
        check("A coat record has no base_model_sha256", "base_model_sha256" in rec, False)
        side = assembled_side("OA")
        check("OA hair = A's hair fit", side["garments"][hid]["sha256"], sha(body_file("hair", A)))
        check("OA hair != base hair", side["garments"][hid]["sha256"] != base_fit_sha["hair"], True)
        check("OA slip = A's slip fit", side["garments"]["slip"]["sha256"], sha(body_file("slip", A)))
        lsig_a = hashlib.md5(json.dumps({"version": 1, "inner": {"slip": sha(body_file("slip", A))}},
                                        sort_keys=True).encode()).hexdigest()[:12]
        check("OA coat over lsigA", side["garments"]["coat"].get("over"), lsig_a)
        check("served(OA) = assembled", ga.served("Demo", OA, "full"), mdir / "assembled" / "OA.glb")
        a_files = {k: sha(body_file(k, A)) for k in ("coat", "hair", "slip")}

        FITS.clear()
        check("assemble OB", ga.assemble("Demo", "OB")["ok"], True)
        check("OB: 2 fits on body B", sorted(FITS), sorted([(k, sha_b, unr_b) for k in ("coat", "hair")]))
        asm_b = (mdir / "assembled" / "OB.glb").read_bytes()
        rb = radii(node(asm_b, "garment_clothing_coat").positions)
        within("B coat r min", float(rb.min()), 0.112 - 1e-6, 0.112 + 1e-6)
        within("B coat r max", float(rb.max()), 0.112 - 1e-6, 0.112 + 1e-6)
        rh = radii(node(asm_b, f"garment_hair_{hid}").positions)
        within("B hair r", float(rh.max()), 0.119 - 1e-6, 0.119 + 1e-6)
        check("A's fits untouched", {k: sha(body_file(k, A)) for k in a_files}, a_files)
        FITS.clear()
        check("assemble OA2 (body A, coat only)", ga.assemble("Demo", "OA2")["ok"], True)
        check("OA2: 0 fits (one body, two assemblies)", FITS, [])
        side2 = assembled_side("OA2")
        check("OA2 coat = A's coat fit, no over", (side2["garments"]["coat"]["sha256"], "over" in side2["garments"]["coat"]),
              (a_files["coat"], False))
        check("HUB 0", HUB, [])
        check("base fits untouched", {k: sha(p) for k, p in base_fit.items()}, base_fit_sha)

        # --- [3] never on another body -------------------------------------------------------------
        print("[3] a fit of body A is never served on body B")
        rec_a = gs.read_record(body_file("coat", A).with_suffix(".json"))
        rec_base = gs.read_record(base_fit["coat"].with_suffix(".json"))
        check("B model, A record", ga.built_on_fit_base(meta_ob, rec_a), False)
        check("A model, A record", ga.built_on_fit_base(meta_oa, rec_a), True)
        check("A model, base record", ga.built_on_fit_base(meta_oa, rec_base), False)
        check("base model, A record", ga.built_on_fit_base(meta_or, rec_a), False)
        check("base signature only, A record", ga.built_on_fit_base({"base_signature": bsig}, rec_a), False)
        shutil.copyfile(body_file("coat", A), body_file("coat", B))
        shutil.copyfile(body_file("coat", A).with_suffix(".json"), body_file("coat", B).with_suffix(".json"))
        check("A's fit on B's path: stale", garments.body_fit_state("Demo", "coat", fc, B, sha_b,
                                                                    base_fit_sha["coat"]), "stale")
        check("OB serve: coat pending", (wanted("OB")["coat"]["fit"], wanted("OB")["coat"].get("pending")), (None, True))
        FITS.clear()
        ga.assemble("Demo", "OB")
        check("OB: refitted on B", FITS, [("coat", sha_b, unr_b)])
        check("B coat record body_id", gs.read_record(body_file("coat", B).with_suffix(".json")).get("body_id"), B)

        # --- [4] hair per body -------------------------------------------------------------------
        print("[4] hair per body")
        for body in (A, B):
            r = gs.read_record(body_file("hair", body).with_suffix(".json"))
            check(f"hair record on {body}", (r.get("kind"), r.get("body_id")), ("hair", body))
        check("retexture outfit wants the BASE hair fit", wanted("OR")[hid]["fit"], base_fit["hair"])

        # --- [5] layering per body ---------------------------------------------------------------
        # The hair's length class decides its gates (medium: every GATES key, moved_share included).
        check("hair on a body: the medium length class's gates", HAIR_GATES[-1] if HAIR_GATES else None,
              sorted(garment_fit.hair_gates("medium")))
        check("medium keeps moved_share", "moved_share" in (HAIR_GATES[-1] if HAIR_GATES else []), True)

        print("[5] layering per body")
        layer_a = gs.garment_path("Demo", "coat", fc, "layer", lsig=lsig_a, body=A)
        check("A layer files", (layer_a.is_file(), layer_a.with_suffix(".json").is_file(),
                                gs.garment_path("Demo", "coat", fc, "layer_low", lsig=lsig_a, body=A).is_file()),
              (True, True, True))
        lrec = gs.read_record(layer_a.with_suffix(".json"))
        check("A layer record", {k: lrec.get(k) for k in ("body_id", "body_sha256", "base_fit_sha256")},
              {"body_id": A, "body_sha256": sha_a, "base_fit_sha256": a_files["coat"]})
        check("A layer inner slip", (lrec.get("inner") or {}).get("slip", {}).get("sha256"), a_files["slip"])
        check("A layer has no base_model_sha256", "base_model_sha256" in lrec, False)
        ga.assemble("Demo", "OA")  # current: nothing changed
        g = node((mdir / "assembled" / "OA.glb").read_bytes(), "garment_clothing_coat")
        r = radii(g.positions)[band(g.positions, 1.10, 1.30)]
        within("OA coat over the slip r min", float(r.min()), 0.1239, 0.1270)
        within("OA coat over the slip r max", float(r.max()), 0.1239, 0.1270)
        FITS.clear()
        check("assemble OB2", ga.assemble("Demo", "OB2")["ok"], True)
        check("OB2: slip fitted on B", FITS, [("slip", sha_b, unr_b)])
        lsig_b = hashlib.md5(json.dumps({"version": 1, "inner": {"slip": sha(body_file("slip", B))}},
                                        sort_keys=True).encode()).hexdigest()[:12]
        layer_b = gs.garment_path("Demo", "coat", fc, "layer", lsig=lsig_b, body=B)
        check("B layer file, other lsig", (layer_b.is_file(), lsig_b != lsig_a), (True, True))
        check("OB2 coat over lsigB", assembled_side("OB2")["garments"]["coat"].get("over"), lsig_b)
        g = node((mdir / "assembled" / "OB2.glb").read_bytes(), "garment_clothing_coat")
        r = radii(g.positions)[band(g.positions, 1.10, 1.30)]
        within("OB2 coat over the slip r min", float(r.min()), 0.1279, 0.1310)
        within("OB2 coat over the slip r max", float(r.max()), 0.1279, 0.1310)
        check("no base layers folder", (groot / "layers").exists(), False)

        # --- [6] FIT_VERSION per body ------------------------------------------------------------
        print("[6] FIT_VERSION staleness per body")
        saved_versions = dict(garment_fit.FIT_VERSION)
        garment_fit.FIT_VERSION.update({"hair": 8, "clothing": 8})
        try:
            for key, path in base_fit.items():
                rec = gs.read_record(path.with_suffix(".json"))
                gs.write_record(path.with_suffix(".json"), {**rec, "fit_version": 8})
            check("coat on A / B stale", (garments.body_fit_state("Demo", "coat", fc, A, sha_a, base_fit_sha["coat"]),
                                          garments.body_fit_state("Demo", "coat", fc, B, sha_b, base_fit_sha["coat"])),
                  ("stale", "stale"))
            check("base fits current", garment_refit.outdated_fits("Demo"), [])
            want6 = sorted((items[k], kinds[k], fsig[k], b) for k in ("coat", "hair", "slip") for b in (A, B))
            check("outdated_body_fits", sorted(garment_refit.outdated_body_fits("Demo")), want6)
            check("OA serve: coat pending", wanted("OA")["coat"].get("pending"), True)
            FITS.clear()
            done = garment_refit.refit_character("Demo")
            check("refit_character", sorted(done or []), sorted(f"{i}@{b}" for i, _k, _f, b in want6))
            check("6 refits, each on its body", sorted((f[0], f[1]) for f in FITS),
                  sorted((k, s) for k in ("coat", "hair", "slip") for s in (sha_a, sha_b)))
            check("body records fit_version 8", sorted({gs.read_record(body_file(k, b).with_suffix(".json"))
                                                        .get("fit_version") for k in ("coat", "hair", "slip")
                                                        for b in (A, B)}), [8])
            check("nothing outdated after", garment_refit.outdated_body_fits("Demo"), [])
            check("OA serve: nothing pending", [k for k, g in wanted("OA").items() if g.get("pending")], [])
            check("HUB still 0", HUB, [])
        finally:
            garment_fit.FIT_VERSION.clear()
            garment_fit.FIT_VERSION.update(saved_versions)
            for key, path in base_fit.items():
                rec = gs.read_record(path.with_suffix(".json"))
                gs.write_record(path.with_suffix(".json"), {**rec, "fit_version": saved_versions[kinds[key]]})
        ga.assemble("Demo", "OA")
        ga.assemble("Demo", "OB")  # back to the current version on both bodies

        # --- [7] refusal per body ------------------------------------------------------------------
        print("[7] a refused fit is per body")
        REFUSE.clear()
        REFUSE.add(sha_c)
        FITS.clear()
        warning = ga.body_fit_warning("Demo", meta_oc)
        reason = "fit on the outfit body refused — too tight"
        check("C warning", warning, base_body.NOT_FITTED_ON_BODY.format(items=f"Coat ({reason}), Hair ({reason})"))
        check("C: 2 refused fits", sorted(f[0] for f in FITS), ["coat", "hair"])
        check("C failure records", [gs.garment_path("Demo", items[k], fsig[k], "failed", body=C).is_file()
                                    for k in ("coat", "hair")], [True, True])
        FITS.clear()
        ga.body_fit_warning("Demo", meta_oc)
        check("C: no retry", FITS, [])
        check("OC serve: nothing wanted", ga._wanted_for("Demo", mdir, "OC"), [])
        SCHEDULED.clear()
        check("assemble OC", ga.assemble("Demo", "OC")["tiers"], {"full": "none", "low": "none"})
        check("served(OC) = bare, no schedule", (ga.served("Demo", OC, "full"), SCHEDULED), (OC, []))
        old_b_coat = sha(body_file("coat", B))
        base_fit["coat"].write_bytes(glb_mesh.graft(base_bytes, tube(0.1081, 0.80, 1.40), name="garment_clothing_coat",
                                                    extras={"kind": "clothing", "item_id": "coat", "fsig": fc}))
        check("base coat fit replaced", sha(base_fit["coat"]) != base_fit_sha["coat"], True)
        REFUSE.clear()
        REFUSE.add(sha_b)
        FITS.clear()
        ga.assemble("Demo", "OB")
        check("B: 1 refused refit", FITS, [("coat", sha_b, unr_b)])
        check("B: the OLD coat fit stays served", (wanted("OB")["coat"]["fit"], sha(body_file("coat", B)),
                                                   wanted("OB")["coat"].get("pending")),
              (body_file("coat", B), old_b_coat, None))
        FITS.clear()
        check("B: second assemble current", ga.assemble("Demo", "OB")["tiers"]["full"], "current")
        check("B: no retry", FITS, [])
        rec_path = body_file("coat", B).with_suffix(".json")
        rec_b = json.loads(rec_path.read_text())
        rec_path.write_text(json.dumps({**rec_b, "fit_version": rec_b["fit_version"] - 1}))
        FITS.clear()
        check("B: an older-version fit is not served after the refusal", "coat" in wanted("OB"), False)
        check("B: left off with the reason", ga.body_fit_warning("Demo", meta_ob),
              base_body.NOT_FITTED_ON_BODY.format(items=f"Coat ({reason})"))
        check("B: still no retry", FITS, [])
        rec_path.write_text(json.dumps(rec_b))
        check("B: current-version fit served again", wanted("OB")["coat"]["fit"], body_file("coat", B))
        REFUSE.clear()

        # --- [8] body rebuilt ----------------------------------------------------------------------
        print("[8] a rebuilt body gets no fit for the old outfit copy")
        (mdir / f"{A}.glb").write_bytes(body_glb(0.100, (10, 20, 30)))
        check("OA coat = A's fit on OA's body bytes", wanted("OA2")["coat"]["fit"], body_file("coat", A))
        FITS.clear()
        ga.assemble("Demo", "OA")
        ga.assemble("Demo", "OA2")
        check("no fit on the rebuilt body for the old copy", FITS, [])

        # --- [9] groups ------------------------------------------------------------------------------
        print("[9] groups")
        files = set(gs.stored_groups("Demo")[("coat", fc)])
        check("group holds both bodies' fits + layers", {body_file("coat", A), body_file("coat", B), layer_a, layer_b}
              <= files, True)
        check("body_of", (gs.body_of(body_file("coat", B)), gs.body_of(layer_a), gs.body_of(base_fit["coat"])),
              (B, A, ""))

        # --- [10] tab status ------------------------------------------------------------------------
        print("[10] Wardrobe / Hair tab: the fit of the body worn now")
        from app.models.character import get_character_profile
        profile = get_character_profile("Demo")
        profile["outfit_body_mode"] = "mesh"
        check("mode mesh", save_character_profile("Demo", profile), True)
        osig = current_outfit_state("Demo")[2]
        shutil.copyfile(OB, mdir / f"{osig}.glb")
        shutil.copyfile(OB.with_suffix(".json"), mdir / f"{osig}.json")
        info = garments.garment_info("Demo", "coat")
        check("coat body", {k: (info["body"] or {}).get(k) for k in ("body_id", "status", "error")},
              {"body_id": B, "status": "failed", "error": reason})
        check("coat body_id", info["body_id"], B)
        check("hair body accepted", (garments.garment_info("Demo", hid)["body"] or {}).get("status"), "accepted")
        check("slip not carried", garments.garment_info("Demo", "slip")["body"], None)
        chip = garment_set.piece_status(info, worn=False, base_model_ready=True)
        check("piece_status body", chip.get("body"), {"body_id": B, "status": "failed", "error": reason})
        profile["outfit_body_mode"] = "retexture"
        save_character_profile("Demo", profile)
        check("retexture: no body", garments.garment_info("Demo", "coat")["body"], None)
        check("HUB at the end", HUB, [])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
