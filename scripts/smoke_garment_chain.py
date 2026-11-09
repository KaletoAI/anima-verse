#!/usr/bin/env python3
"""Hair as its own mesh, task 8: the garment chain orchestration, its
triggers and the outfit-model hook (app/core/garments.py + the base_body
hooks).

Usage:
    ./.venv/bin/python scripts/smoke_garment_chain.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process. Every image and mesh is synthetic; the expectations are
derived by hand below from plan 2026-11-09-base-body-phase4-hair (R3, R5,
R8, R10, R11, R13, R14, Task 8).

Stubs: ``expression_regen.render_character_image`` (recorder writing the
planned image per (step, view, attempt)), ``character.run_rembg`` ("every
pixel with a channel more than 2 away from grey 128"), the image service
(``generate_mesh`` = recorder writing the hair cap GLB; ``upscale_image``
raises, so the cut-out takes its documented Lanczos path),
``refine.decimate_to`` (recorder; copies the input), ``garment_assembly.
schedule`` (recorder), and for the outfit model the stubs of
``smoke_base_body_outfit.py`` (``_auto_retexture`` / ``_attach_measurement``
/ ``_auto_extension_rig`` no-ops, ``request_lod`` recorder, no extension
groups, identity delivery path). The gates, the cut-out, the fit and the
graft/assembly are REAL.

Geometry, 1000 px per unit (the framing of smoke_garment_fit.py (f)):
  unrigged base = double-walled head sphere R 0.100 (inner 0.098) at
                  (0, 0.9, 0) + closed torso cylinder r 0.12, y 0.0 .. 0.8;
                  bbox x [-0.12, 0.12], y [0, 1.0];
  rigged base   = 1.7 x unrigged + (0, 0.05, 0), same UVs/topology, the
                  52 Mixamo joints, head vertices weighted Head, the rest
                  Spine2, a 16x16 base colour (validator: >= 8 px);
  hair (mesh stub) = upper half shell r 0.108 around (0, 0.9, 0) on a
                  3-degree grid, generated in its own frame (x4, shifted by
                  (3, -2, 1)), UVs + a PNG texture.
Images W 1024 x H 1200 on grey 128 (RGB, so neutral_view_reference passes
them through); column 512 = x 0, row 100 = y 1.0, so y = 0 is row 1100:
  BASE   head disc centre (512, 200) radius 100 + torso cols [392, 632) rows
         [300, 1100) in skin (200, 160, 140) -> mask bbox x [392, 632),
         y [100, 1100) = the unrigged bbox at 1000 px / unit;
  HAIRED = BASE + hair rect cols [404, 620) rows [92, 200) in (90, 60, 30)
         (= the cap's bbox: x +-0.108, y 0.9 .. 1.008);
  GHOST  = grey + the hair rect only;  BODY_GHOST = GHOST + the torso.
Gates on these (base mask y0 100, Hb 1000): body zone from row 400, chest
box rows 270 .. 400 -> HAIRED changes nothing there (XOR 0, dRGB 0): pass.
hair_ref = the hair rect (rows < 320) = the ghost box: top_dy 0, centre 0,
w_ratio 1.0, no ghost pixel below the chin row 230: pass. BODY_GHOST: the
torso below the chin in skin colour = 120 x 800 ... far above 0.05 of the
body area: fail. Front and back are the same images, so the bottoms agree.
Cut-out: hair box 216 wide -> side int(1.15 x 216) = 248 < 1024 -> upscale
(raises) -> Lanczos to 1024. Fit: the same numbers as smoke_garment_fit (f)
(nothing pushed, gate passes, all weights Head).

[1] Full run run_garment(Demo, H): 4 renders (haired f/b, ghost f/b, each
    accepted at attempt 1), cut-outs f/b, ONE generate_mesh (occasion
    mesh_garment), decimate_to raw -> prepared (target 25000) and fit -> low
    (target round(lod_ratio("character") x tris of the fit GLB)); the fit
    garments/H_F1.glb has a node "garment_hair_H" with extras.garment
    {kind hair, item_id H, fsig F1}; record accepted True, base_signature
    B1, base_model_sha256 = sha(model3d/B1.glb), metrics.tris > 0,
    gates.ok True, inputs.prepared_sha256 = sha(prepared); low exists;
    schedule(Demo) recorded; result ok, ran = all five steps; status idle.
[2] A second run: ok, ran [], no render / mesh / decimate call.
[3] Forced haired front (steps "haired", view "front", force): 2 renders
    (haired front, ghost front — the old ghost front was dropped), the back
    stays cached; the old prepared mesh is deleted and rebuilt (1 mesh
    call), the fit is re-fitted (2 decimations).
[4] Forced mesh refused (stub writes cap + a second cap r 0.03: area share
    of the largest ~ 1 / (1 + (0.03/0.108)^2) = 0.93 < 0.98): 2 mesh calls,
    result {ok False, step "mesh"}, gates.attempts 2, status failed.step
    "mesh", NO prepared GLB — but the accepted fit of F1 is still the served
    one (accepted_fit). Then a plain run (good stub): starts at mesh (1 call),
    re-fits; failure cleared.
[5] Base model rewritten under the same B1 (other texture colour ->
    new sha): after_base_model starts fit only: renders 0, mesh calls 0,
    the fit record's base_model_sha256 = the new sha. Then, with the run
    lock held by the smoke: start_garment -> True (status "queued" at once),
    a second start_garment -> False; released, the run finds nothing to do
    and the "queued" mark ends without a failure.
[6] New profile image -> B2 (base images + base model for B2 written):
    after_base_model runs the whole chain under F2: 4 renders, 1 mesh call,
    fit record base_signature B2.
[7] Hair colour changed (B2 unchanged, F3 != F2) and BODY_GHOST on the back
    for both attempts: run_garment -> {ok False, step "ghost"}, 2 (haired) +
    1 (ghost front) + 2 (ghost back) renders, NO mesh call; status
    failed.step "ghost"; garment_info: fsig F3, ghost back accepted False
    with 2 attempts, served_fsig F2 (the fallback), stale_reasons
    ["description_changed"], preview_url names the F2 fit's content version;
    base_info(Demo)["hair"] = {item_id H, status "failed"}.
[8] Outfit model (undressed outfit OSIG, base copy): generate_for_current_
    outfit publishes model3d/OSIG.glb WITHOUT a garment node and
    model3d/assembled/OSIG.glb WITH "garment_hair_H" (fsig F2); no
    garment_warnings.
[9] The F2 fit file broken (garbage bytes, record still accepted): a forced
    outfit build still publishes the bare model (no garment node), records
    garment_warnings (one entry naming the full tier), and leaves no
    assembled file.
[10] generate_base_model: a successful (stubbed) run calls after_base_model
    once; a failed one does not.
[11] after_base_model ensures the hair item first (controller ruling after
    Task 8: nothing else creates it without a click):
    Neo    pipeline human, hair slot {short, black}, NO item, base images +
           model written -> after_base_model True; item "hair_neo" (slug
           "neo") created and worn {hair: hair_neo}, prompt_fragment = its
           hair_description; the whole chain runs: 4 renders, 1 mesh call,
           fit record accepted on Neo's base signature.
    Baldy  pipeline human, no hair slot value and no hair clause -> ""
           -> after_base_model False, no item, worn {}, 0 renders, 0 mesh.
    Unworn pipeline human with hair text that OWNS a hair item it does not
           wear (taken off in the Hair tab) -> after_base_model False, the
           item stays off (worn {}), 0 renders.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
HAIR = (90, 60, 30)
W, H = 1024, 1200


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


def solid_png(rgb, size=16) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(out, "PNG")
    return out.getvalue()


def canvas():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[:] = GREY
    return rgb


def figure(rgb):
    yy, xx = np.mgrid[0:H, 0:W]
    rgb[(xx - 512) ** 2 + (yy - 200) ** 2 <= 100 ** 2] = SKIN
    rgb[300:1100, 392:632] = SKIN
    return rgb


def hair(rgb):
    rgb[92:200, 404:620] = HAIR
    return rgb


BASE = figure(canvas())
HAIRED = hair(figure(canvas()))
GHOST = hair(canvas())
BODY_GHOST = hair(canvas())
BODY_GHOST[300:1100, 392:632] = SKIN


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        arr = np.asarray(im.convert("RGB")).astype(np.int16)
    mask = (np.abs(arr - 128) > 2).any(2)
    return png((mask * 255).astype(np.uint8))


# --- GLB fixtures -------------------------------------------------------------

def rigged_glb(P, F, U, J, W_, image: bytes) -> bytes:
    """A skinned GLB the Mixamo validator accepts: Armature -> Body (skin 0) +
    every base joint (Hips parent of the rest), one PNG base colour."""
    from app.core.rig_contract import BASE_JOINT_NAMES
    names = ["mixamorig:" + n for n in BASE_JOINT_NAMES]
    nodes = [{"name": "Armature", "children": [1, 2]}, {"name": "Body", "mesh": 0, "skin": 0}]
    joints = [{"name": n} for n in names]
    joints[0]["children"] = [3 + i for i in range(len(names) - 1)]
    nodes += joints
    blob = bytearray()
    views, accs = [], []

    def add(arr, ctype, typ, target, minmax=False):
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw), "target": target})
        blob.extend(raw)
        a = {"bufferView": len(views) - 1, "componentType": ctype,
             "count": len(arr) if arr.ndim > 1 else arr.size, "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    attrs = {"POSITION": add(P.astype("<f4"), 5126, "VEC3", 34962, True),
             "TEXCOORD_0": add(U.astype("<f4"), 5126, "VEC2", 34962),
             "JOINTS_0": add(J.astype("<u2"), 5123, "VEC4", 34962),
             "WEIGHTS_0": add(W_.astype("<f4"), 5126, "VEC4", 34962)}
    ind = add(F.astype("<u4").reshape(-1), 5125, "SCALAR", 34963)
    blob.extend(b"\0" * (-len(blob) % 4))
    views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(image)})
    blob.extend(image)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [2 + i for i in range(len(names))]}],
           "accessors": accs, "bufferViews": views,
           "images": [{"bufferView": len(views) - 1, "mimeType": "image/png"}], "textures": [{"source": 0}],
           "materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    import smoke_glb_graft as gx
    return gx.pack(doc, blob)


def base_bodies(colour=(200, 160, 140)):
    """(unrigged GLB, rigged GLB) of the fixture body."""
    import smoke_garment_fit as fx
    from app.core.rig_contract import BASE_JOINT_NAMES
    hP, hF = fx.head_body()
    tP, tF = fx.cylinder(0.12, 0.0, 0.8)
    P, F = fx.merge((hP, hF), (tP, tF))
    head = np.arange(len(P)) < len(hP)
    n = len(P)
    U = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    names = list(BASE_JOINT_NAMES)
    J = np.zeros((n, 4), np.int64)
    J[:, 0] = np.where(head, names.index("Head"), names.index("Spine2"))
    Wt = np.zeros((n, 4))
    Wt[:, 0] = 1.0
    unrigged = fx.make_glb(P, F, U, image=solid_png((90, 90, 90)))
    rigged = rigged_glb(1.7 * P + np.array([0, 0.05, 0]), F, U, J, Wt, solid_png(colour))
    return unrigged, rigged


def hair_glb(bad=False) -> bytes:
    import smoke_garment_fit as fx
    c = np.array([0, 0.9, 0])
    P, F = fx.cap(0.108, c, n_el=31, nlon=120)
    if bad:
        P2, F2 = fx.cap(0.03, c + np.array([0.5, 0, 0]), n_el=31, nlon=120)
        P, F = fx.merge((P, F), (P2, F2))
    U = np.stack([np.linspace(0, 1, len(P)), np.linspace(1, 0, len(P))], 1)
    return fx.make_glb(4 * (P - c) + np.array([3, -2, 1]), F, U, image=solid_png((90, 60, 30)))


def node_names(glb: bytes):
    from app.core.model_validate import parse_glb
    return [n.get("name") for n in parse_glb(glb)["gltf"].get("nodes", [])]


def garment_extras(glb: bytes, name: str):
    from app.core.model_validate import parse_glb
    for node in parse_glb(glb)["gltf"].get("nodes", []):
        if node.get("name") == name:
            return (node.get("extras") or {}).get("garment")
    return None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-chain-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.blender import refine
        from app.core import (base_body, expression_regen, extension_rig, garment_assembly, garment_hair,
                              glb_delivery, model3d, model_refs, sync_topics)
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        try:
            from app.core import garments
        except ImportError as e:
            check("garments importable", str(e), "importable")
            print("FAILED: " + ", ".join(FAILS))
            return 1

        # --- stubs -------------------------------------------------------------
        RENDERS, MESHES, DECIMATES, SCHEDULED = [], [], [], []
        mode = {"ghost_back_bad": False, "mesh_bad": False}
        charmod.run_rembg = rembg_stub

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            RENDERS.append((g["step"], g["view"], g["attempt"], g["fsig"]))
            if g["step"] == "haired":
                arr = HAIRED
            elif g["view"] == "back" and mode["ghost_back_bad"]:
                arr = BODY_GHOST
            else:
                arr = GHOST
            # The edit renders on the square canvas (side max(W, H) = 1200,
            # the source centred at x offset (1200 - 1024) // 2 = 88): the
            # stub answers with the planned image placed the same way.
            side = kw["override_width"]
            canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
            dy, dx = (canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
            canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g["attempt"], **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder

        class FakeService:
            def generate_mesh(self, **kw):
                MESHES.append(kw)
                Path(kw["output_path"]).write_bytes(hair_glb(bad=mode["mesh_bad"]))
                return {"ok": True, "path": kw["output_path"], "backend": "FakeMesh",
                        "routing": {"occasion": kw.get("occasion")}}

            def upscale_image(self, data, **kw):
                raise RuntimeError("no upscaler in the smoke")

            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []

        service.get_image_service = lambda: FakeService()

        def decimate_to(path_in, target_tris, out, merge_vertices=False):
            from app.core import glb_mesh
            data = Path(path_in).read_bytes()
            tris = len(glb_mesh.static_arrays(data)[1])
            DECIMATES.append((Path(path_in).name, Path(out).parent.name, int(target_tris), tris))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(data)
            return {"ok": True, "path": str(out), "tris_before": tris, "tris": tris,
                    "ratio": min(0.999, target_tris / tris), "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        LOD_CALLS = []
        model3d._auto_retexture = lambda *a, **k: None
        model3d._attach_measurement = lambda *a, **k: None
        model3d._auto_extension_rig = lambda *a, **k: None
        model3d.request_lod = lambda name, path: LOD_CALLS.append(path.name) or False
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(solid_png((50, 60, 70), 8))
        (images / "Demo_2.png").write_bytes(solid_png((50, 60, 71), 9))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        check("pipeline", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair item worn", inventory.get_equipped_mesh_pieces("Demo"), {"hair": hid})
        cdir = get_character_dir("Demo")
        refs = cdir / "model_refs"
        mdir = cdir / "model3d"

        def write_base(bsig, colour=(200, 160, 140)):
            refs.mkdir(parents=True, exist_ok=True)
            for v in base_body.BASE_VIEWS:
                stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
                (refs / f"{stem}.png").write_bytes(png(BASE))
                (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
            write_model(bsig, colour)

        def write_model(bsig, colour):
            unrigged, rigged = base_bodies(colour)
            (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
            (mdir / "unrigged" / f"{bsig}.glb").write_bytes(unrigged)
            tmpf = mdir / f".{bsig}.tmp"
            tmpf.write_bytes(rigged)
            os.replace(tmpf, mdir / f"{bsig}.glb")
            (mdir / f"{bsig}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated"}))
            return rigged

        b1 = base_body.base_signature("Demo")
        write_base(b1)
        f1 = gs.garment_fsig("Demo", hid)

        def counts():
            return len(RENDERS), len(MESHES), len(DECIMATES)

        def fit_record(fsig):
            return gs.read_record(gs.garment_path("Demo", hid, fsig, "fit").with_suffix(".json"))

        # --- [1] full run --------------------------------------------------------
        print("[1] full run")
        SCHEDULED.clear()  # equipping the item in the fixture asked for one already
        res = garments.run_garment("Demo", hid)
        check("ok", (res.get("ok"), res.get("fsig")), (True, f1))
        check("ran", res.get("ran"), ["haired", "ghost", "cutout", "mesh", "fit"])
        check("renders", sorted((s, v, a) for s, v, a, _f in RENDERS),
              [("ghost", "back", 1), ("ghost", "front", 1), ("haired", "back", 1), ("haired", "front", 1)])
        for step in ("haired", "ghost", "cutout"):
            for v in ("front", "back"):
                p = gs.garment_path("Demo", hid, f1, "image", step=step, view=v)
                check(f"{step} {v} accepted", (p.is_file(), gs.read_record(p.with_suffix(".json")).get("accepted")),
                      (True, True))
        check("one mesh call", [m.get("occasion") for m in MESHES], ["mesh_garment"])
        raw = gs.garment_path("Demo", hid, f1, "raw")
        prepared = gs.garment_path("Demo", hid, f1, "prepared")
        fit = gs.garment_path("Demo", hid, f1, "fit")
        low = gs.garment_path("Demo", hid, f1, "low")
        check("raw + prepared", (raw.is_file(), prepared.is_file()), (True, True))
        check("fit + low", (fit.is_file(), low.is_file()), (True, True))
        node = f"garment_hair_{hid}"
        if fit.is_file():
            check("fit node", node in node_names(fit.read_bytes()), True)
            check("fit extras", garment_extras(fit.read_bytes(), node), {"kind": "hair", "item_id": hid, "fsig": f1})
            from app.core import glb_mesh
            fit_tris = len(glb_mesh.static_arrays(fit.read_bytes())[1])
            want_low = max(1, int(round(refine.lod_ratio("character") * fit_tris)))
            check("decimations", [(d[1], d[2]) for d in DECIMATES], [("prepared", 25000), ("low", want_low)])
        rec = fit_record(f1)
        check("record", (rec.get("accepted"), rec.get("base_signature"), rec.get("base_model_sha256"),
                         (rec.get("gates") or {}).get("ok")),
              (True, b1, sha(mdir / f"{b1}.glb"), True))
        check("record metrics tris", (rec.get("metrics") or {}).get("tris", 0) > 0, True)
        check("record inputs", (rec.get("inputs") or {}).get("prepared_sha256"), sha(prepared) if prepared.is_file() else "")
        check("assembly scheduled", SCHEDULED, [("Demo", None)])
        st = gs.status("Demo", hid)
        check("status idle", (st["running_step"], st["failed"]), (None, None))

        # --- [2] cached ------------------------------------------------------------
        print("[2] second run does nothing")
        before = counts()
        fit_mtime = fit.stat().st_mtime_ns if fit.is_file() else 0
        res = garments.run_garment("Demo", hid)
        check("ok, nothing ran", (res.get("ok"), res.get("ran")), (True, []))
        check("no calls", counts(), before)
        check("fit untouched", fit.stat().st_mtime_ns if fit.is_file() else 0, fit_mtime)

        # --- [3] forced haired front ------------------------------------------------
        print("[3] forced haired front re-runs it and every later step")
        RENDERS.clear(), MESHES.clear(), DECIMATES.clear()
        res = garments.run_garment("Demo", hid, steps="haired", view="front", force=True)
        check("ok", res.get("ok"), True)
        check("renders", [(s, v) for s, v, _a, _f in RENDERS], [("haired", "front"), ("ghost", "front")])
        check("mesh rebuilt", len(MESHES), 1)
        check("refit (prepared + low)", [d[1] for d in DECIMATES], ["prepared", "low"])

        # --- [4] forced mesh refused --------------------------------------------------
        print("[4] forced mesh refused: the accepted fit keeps serving")
        MESHES.clear()
        mode["mesh_bad"] = True
        res = garments.run_garment("Demo", hid, steps="mesh", force=True)
        mode["mesh_bad"] = False
        check("refused", (res.get("ok"), res.get("step")), (False, "mesh"))
        check("two attempts", (len(MESHES), len((res.get("gates") or {}).get("attempts") or [])), (2, 2))
        check("status failed mesh", (gs.status("Demo", hid)["failed"] or {}).get("step"), "mesh")
        check("no prepared mesh", prepared.is_file(), False)
        served = gs.accepted_fit("Demo", hid, base_model_sha=sha(mdir / f"{b1}.glb"))
        check("fit still served", served[0] if served else None, fit)
        MESHES.clear()
        res = garments.run_garment("Demo", hid)
        check("repair run", (res.get("ok"), res.get("ran"), len(MESHES)), (True, ["mesh", "fit"], 1))
        check("failure cleared", gs.status("Demo", hid)["failed"], None)

        # --- [5] base model rewritten, same bsig ----------------------------------------
        print("[5] base model regenerated under the same base signature -> fit only")
        rigged2 = write_model(b1, (201, 161, 141))
        new_sha = hashlib.sha256(rigged2).hexdigest()
        check("sha changed", new_sha != rec.get("base_model_sha256"), True)
        before = counts()
        check("after_base_model starts", garments.after_base_model("Demo"), True)
        check("idle", garments.wait_idle(120), True)
        after = counts()
        check("no render, no mesh", (after[0] - before[0], after[1] - before[1]), (0, 0))
        rec5 = fit_record(f1)
        check("new fit record sha", (rec5.get("accepted"), rec5.get("base_model_sha256")), (True, new_sha))
        check("nothing more to do", garments.after_base_model("Demo"), False)
        lock = gs.char_lock("Demo")
        lock.acquire()
        try:
            check("start (waits on the run lock)", garments.start_garment("Demo", hid), True)
            check("second start refused", garments.start_garment("Demo", hid), False)
            check("queued from the start", gs.status("Demo", hid)["running_step"], "queued")
        finally:
            lock.release()
        check("idle", garments.wait_idle(60), True)
        check("queued mark ended", (gs.status("Demo", hid)["running_step"], gs.status("Demo", hid)["failed"]),
              (None, None))

        # --- [6] new bsig ---------------------------------------------------------------
        print("[6] new profile image -> new base signature -> whole chain")
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_2.png"
        check("profile image 2", save_character_profile("Demo", stored), True)
        b2 = base_body.base_signature("Demo")
        check("bsig changed", b2 != b1, True)
        write_base(b2)
        f2 = gs.garment_fsig("Demo", hid)
        check("fsig changed", f2 != f1, True)
        before = counts()
        check("after_base_model starts", garments.after_base_model("Demo"), True)
        check("idle", garments.wait_idle(120), True)
        after = counts()
        check("4 renders, 1 mesh", (after[0] - before[0], after[1] - before[1]), (4, 1))
        rec6 = fit_record(f2)
        check("fit on B2", (rec6.get("accepted"), rec6.get("base_signature")), (True, b2))

        # --- [7] description change + ghost refusal --------------------------------------
        print("[7] ghost refusal")
        stored = get_character_profile("Demo")
        stored["body_slots"]["hair"]["color"] = "black"
        check("hair colour", save_character_profile("Demo", stored), True)
        check("bsig unchanged", base_body.base_signature("Demo"), b2)
        f3 = gs.garment_fsig("Demo", hid)
        check("fsig changed", f3 not in (f1, f2), True)
        mode["ghost_back_bad"] = True
        before = counts()
        res = garments.run_garment("Demo", hid)
        mode["ghost_back_bad"] = False
        after = counts()
        check("refused at ghost", (res.get("ok"), res.get("step")), (False, "ghost"))
        check("renders, no mesh", (after[0] - before[0], after[1] - before[1]), (5, 0))
        check("status failed ghost", (gs.status("Demo", hid)["failed"] or {}).get("step"), "ghost")
        check("item description refreshed", inventory.get_item(hid).get("prompt_fragment"),
              garment_hair.hair_description("Demo"))
        info = garments.garment_info("Demo", hid)
        check("info fsig", info.get("fsig"), f3)
        gb = ((info.get("steps") or {}).get("ghost") or {}).get("back") or {}
        check("ghost back refused, 2 attempts", (gb.get("accepted"), len(gb.get("attempts") or [])), (False, 2))
        check("ghost front url", bool(((info["steps"]["ghost"]).get("front") or {}).get("url")), True)
        check("served fsig", info.get("served_fsig"), f2)
        check("stale reasons", info.get("stale_reasons"), ["description_changed"])
        from app.core.http_files import content_version
        f2fit = gs.garment_path("Demo", hid, f2, "fit")
        check("preview url", (info.get("preview_url") or "").endswith(f"?v={content_version(f2fit)}"), True)
        check("info failed", (info.get("failed") or {}).get("step"), "ghost")
        check("mesh/fit steps", (info["steps"]["mesh"].get("status"), info["steps"]["fit"].get("status")),
              ("missing", "missing"))
        check("base_info hair", base_body.base_info("Demo").get("hair"), {"item_id": hid, "status": "failed"})

        # --- [8] outfit model + assembly ---------------------------------------------------
        print("[8] outfit model: bare + assembled")
        osig = model_refs.current_outfit_state("Demo")[2]
        base_body.generate_dressed_images("Demo", pieces={}, items=[], signature=osig)
        result = model3d.generate_for_current_outfit("Demo", force=True)
        check("outfit run ok", result.get("ok"), True)
        bare = mdir / f"{osig}.glb"
        assembled = mdir / "assembled" / f"{osig}.glb"
        check("bare published", bare.is_file(), True)
        if bare.is_file():
            check("bare has no garment node", any(str(n).startswith("garment_") for n in node_names(bare.read_bytes())),
                  False)
            check("no garment warnings", model3d._read_sidecar(bare).get("garment_warnings"), None)
        check("assembled published", assembled.is_file(), True)
        if assembled.is_file():
            check("assembled garment node", garment_extras(assembled.read_bytes(), node),
                  {"kind": "hair", "item_id": hid, "fsig": f2})

        # --- [9] assembly failure ----------------------------------------------------------
        print("[9] assembly failure -> bare model + garment_warnings")
        f2fit.write_bytes(b"not a glb")
        result = model3d.generate_for_current_outfit("Demo", force=True)
        check("outfit run ok", result.get("ok"), True)
        check("bare published", bare.is_file(), True)
        if bare.is_file():
            warnings = model3d._read_sidecar(bare).get("garment_warnings") or []
            check("one garment warning naming full", (len(warnings), "full" in (warnings[0] if warnings else "")),
                  (1, True))
            check("bare still bare", any(str(n).startswith("garment_") for n in node_names(bare.read_bytes())),
                  False)
        check("no assembled file", assembled.is_file(), False)

        # --- [10] generate_base_model hook ------------------------------------------------
        print("[10] generate_base_model -> after_base_model")
        HOOK = []
        real_after = garments.after_base_model
        real_ready = base_body.check_model_ready
        real_generate = model3d.generate_for_current_outfit
        garments.after_base_model = lambda name: HOOK.append(name) or False
        base_body.check_model_ready = lambda name, profile=None: ({}, b2)
        try:
            model3d.generate_for_current_outfit = lambda *a, **k: {"ok": True}
            base_body.generate_base_model("Demo")
            check("hook on success", HOOK, ["Demo"])
            model3d.generate_for_current_outfit = lambda *a, **k: {"ok": False, "error": "down"}
            base_body.generate_base_model("Demo")
            check("no hook on failure", HOOK, ["Demo"])
        finally:
            garments.after_base_model = real_after
            base_body.check_model_ready = real_ready
            model3d.generate_for_current_outfit = real_generate
        # --- [11] the hair item is ensured by the trigger ---------------------------------
        print("[11] after_base_model ensures the hair item")

        def write_base_for(name):
            bsig = base_body.base_signature(name)
            r = get_character_dir(name) / "model_refs"
            m = get_character_dir(name) / "model3d"
            r.mkdir(parents=True, exist_ok=True)
            for v in base_body.BASE_VIEWS:
                stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
                (r / f"{stem}.png").write_bytes(png(BASE))
                (r / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
            unrigged, rigged = base_bodies()
            (m / "unrigged").mkdir(parents=True, exist_ok=True)
            (m / "unrigged" / f"{bsig}.glb").write_bytes(unrigged)
            (m / f"{bsig}.glb").write_bytes(rigged)
            (m / f"{bsig}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated"}))
            return bsig

        neo = json.loads(json.dumps(human))
        neo["body_slots"]["hair"] = {"length": "short", "color": "black"}
        baldy = json.loads(json.dumps(human))
        baldy["body_slots"].pop("hair")
        for name, prof in (("Neo", neo), ("Baldy", baldy), ("Unworn", json.loads(json.dumps(human)))):
            check(f"create {name}", save_character_profile(name, prof, create_new=True), True)
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)
        check("Baldy has no hair text", garment_hair.hair_description("Baldy"), "")
        unworn = garment_hair.ensure_hair_item("Unworn")
        check("Unworn takes it off", inventory.unequip_mesh_piece("Unworn", "hair"), True)
        bsig_neo = write_base_for("Neo")
        for name in ("Baldy", "Unworn"):
            write_base_for(name)
        garments.wait_idle(30)
        before = counts()
        check("Neo started", garments.after_base_model("Neo"), True)
        check("idle", garments.wait_idle(120), True)
        after = counts()
        check("Neo item worn", inventory.get_equipped_mesh_pieces("Neo"), {"hair": "hair_neo"})
        neo_item = inventory.get_item("hair_neo") or {}
        check("Neo item", (neo_item.get("category"), neo_item.get("owner"), neo_item.get("prompt_fragment")),
              ("garment", "Neo", garment_hair.hair_description("Neo")))
        check("Neo whole chain", (after[0] - before[0], after[1] - before[1]), (4, 1))
        fneo = gs.garment_fsig("Neo", "hair_neo")
        rneo = gs.read_record(gs.garment_path("Neo", "hair_neo", fneo, "fit").with_suffix(".json"))
        check("Neo fit", (rneo.get("accepted"), rneo.get("base_signature")), (True, bsig_neo))
        before = counts()
        check("Baldy not started", garments.after_base_model("Baldy"), False)
        check("Unworn not started", garments.after_base_model("Unworn"), False)
        check("idle", garments.wait_idle(30), True)
        check("Baldy no item", (inventory.get_equipped_mesh_pieces("Baldy"),
                                garment_hair.find_hair_item("Baldy", get_character_profile("Baldy"))), ({}, None))
        check("Unworn stays off", (inventory.get_equipped_mesh_pieces("Unworn"),
                                   (garment_hair.find_hair_item("Unworn", get_character_profile("Unworn"))
                                    or {}).get("id")), ({}, unworn))
        check("no GPU work", counts()[:2], before[:2])

        garments.wait_idle(30)
        for t in threading.enumerate():
            if t.name.startswith("garment-") and t.is_alive():
                t.join(30)

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
