#!/usr/bin/env python3
"""The garment chain orchestration, its triggers and the outfit-model hook
(app/core/garments.py + the base_body hooks), run on an own-mesh dress (the
clothing edit chain). Written for hair as its own mesh (task 8 of plan
2026-11-09-base-body-phase4-hair); the hair edit chain is gone since the
hair-from-body spec 2026-11-11 (Task 2), so the same orchestration is now
checked on the one kind that still runs it.

Usage:
    ./.venv/bin/python scripts/smoke_garment_chain.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process. Every image and mesh is synthetic; the expectations are
derived by hand below.

Stubs: ``expression_regen.render_character_image`` (recorder writing the
planned image per (step, view, attempt); the drafted worn back is recorded
with attempt "d"), ``character.run_rembg`` ("every pixel with a channel
more than 2 away from grey 128"), the image service (``generate_mesh`` =
recorder writing the dress GLB; ``upscale_image`` raises, so the cut-out
takes its documented Lanczos path), ``refine.decimate_to`` (recorder; copies
the input), ``garment_assembly.schedule`` (recorder), ``model_refs.
trigger_now`` / ``schedule_outfit_render`` no-ops (wearing the dress asks
for outfit renders), and for the outfit model the stubs of
``smoke_base_body_outfit.py`` (``_auto_retexture`` / ``_attach_measurement``
/ ``_auto_extension_rig`` no-ops, ``request_lod`` recorder, no extension
groups, identity delivery path). The gates, the cut-out, the fit and the
graft/assembly are REAL.

Geometry, 1000 px per unit (the framing of smoke_garment_fit.py (f)):
  unrigged base = double-walled head sphere R 0.100 (inner 0.098) at
                  (0, 0.9, 0) + closed torso cylinder r 0.12, y 0.0 .. 0.8;
                  bbox x [-0.12, 0.12], y [0, 1.0];
  rigged base   = 1.7 x unrigged + (0, 0.05, 0), same UVs/topology, the
                  52 Mixamo joints, head vertices weighted Head, torso
                  vertices below y 0.4 Hips (``base_bodies(hips=True)`` —
                  the clothing fit needs a Hips-weighted vertex), the rest
                  Spine2, a 16x16 base colour (validator: >= 8 px);
  dress (mesh stub) = closed cylinder r 0.125, y 0.34 .. 0.78, generated in
                  its own frame (x4, shifted by (3, -2, 1)), UVs + a PNG.
Images W 1024 x H 1200 on grey 128 (RGB); column 512 = x 0, row 100 = y 1.0,
so y = 0 is row 1100:
  BASE   head disc centre (512, 200) radius 100 + torso cols [392, 632) rows
         [300, 1100) in skin (200, 160, 140);
  WORN   = BASE + the dress rect cols [392, 632) rows [320, 760) in
         (40, 90, 50) (= y 0.78 .. 0.34, the dress's height) — it changes
         only the zones of the dress's slots (top, bottom);
  GHOST  = grey + the dress rect only; the "bad" ghost back = plain grey
         (no garment at all).
Dress Demo item "dress": slots [top, bottom], own_mesh, prompt_fragment
FRAGMENT. Demo has hair text, the world's hair method is the default
"body": no hair item exists or is made.

[1] Full run run_garment(Demo, D): 5 renders in chain order — worn front,
    the drafted worn back ("d") and its fit, ghost back, ghost front (back
    first, garments.EDIT_VIEW_ORDER), each accepted at attempt 1 —
    cut-outs f/b, ONE generate_mesh (occasion mesh_garment), decimate_to
    raw -> prepared (target 60000, garment_mesh.TARGET_TRIS_BY_KIND) and
    fit -> low (target round(lod_ratio("character") x tris of the fit GLB));
    the fit garments/D_F1.glb has a node "garment_clothing_D" with
    extras.garment {kind clothing, item_id D, fsig F1}; record accepted
    True, base_signature B1, base_model_sha256 = sha(model3d/B1.glb),
    metrics.tris > 0, gates.ok True, inputs.prepared_sha256 =
    sha(prepared); low exists; schedule(Demo) recorded; result ok, ran =
    all five steps; status idle.
[2] A second run: ok, ran [], no render / mesh / decimate call.
[3] Forced worn front (steps "worn", view "front", force): a new front of
    the drafted step drops the back drafted from it, and every later image
    step of both views goes (``garment_images._drop_later``): the same 5
    renders as [1]; the old prepared mesh is deleted and rebuilt (1 mesh
    call), the fit is re-fitted (2 decimations).
[4] Forced mesh refused (stub adds a cylinder r 0.03, y 0.1 .. 0.2 at
    x 0.5: area share of the largest = (2 pi 0.125 x 0.44 + 2 pi 0.125^2) /
    (that + 2 pi 0.03 x 0.1 + 2 pi 0.03^2) = 0.4438 / 0.4683 = 0.948 <
    0.98): 2 mesh calls, result {ok False, step "mesh"}, gates.attempts 2,
    status failed.step "mesh", NO prepared GLB — but the accepted fit of F1
    is still the served one (accepted_fit). Then a plain run (good stub):
    starts at mesh (1 call), re-fits; failure cleared.
[4b] Forced mesh, attempt 1 refused (the two-part stub) and attempt 2
    raising "no backend available ..." (bug C1 of the 2026-11-09 end-to-end
    run): result {ok False, step "mesh"}, 2 calls, gates.attempts =
    [attempt 1 ok False with its share < 0.98, attempt 2 ok False with the
    error]; the status failure carries both and its error names the backend
    error AND "attempt 1 refused"; the step record (accepted False) keeps
    both.
[4c] Bug C2: start_garment while the failure of [4b] is recorded (run lock
    held by the smoke): status running_step "queued" and failed None at
    once. Released, the run rebuilds the mesh: failure None, prepared back.
[5] Base model rewritten under the same B1 (other texture colour ->
    new sha): after_base_model starts fit only: renders 0, mesh calls 0,
    the fit record's base_model_sha256 = the new sha. Then, with the run
    lock held by the smoke: start_garment -> started (status "queued" at
    once); a second start_garment (the item is IN FLIGHT, waiting on the
    lock) is queued behind it: {started False, queued True, position 1,
    behind D}; a third identical one reuses that waiting run (same
    payload, queue still [D]); released, both runs find nothing to do and
    the "queued" mark ends without a failure.
[5b] The fit record of [5] carries fit_version =
    garment_fit.FIT_VERSION["clothing"]. Rewritten without it: _fit_state
    "stale", garment_info stale_reasons ["fit_algorithm_updated"] (inputs,
    base and base model unchanged); after_base_model queues the item and
    the run re-fits ONLY: 0 renders, 0 mesh calls, 1 decimation (the low
    tier of the new fit; the prepared mesh stays cached); the new record
    accepted, fit_version current, base sha unchanged; "accepted" again. A
    record with fit_version one lower is "stale" as well.
[6] New profile image -> B2 (base images + base model for B2 written):
    refit before re-render (garment_source, 2026-11-10): F2's group has no
    images, F1's accepted source names the current dress inputs on B1, so
    after_base_model copies it into F2 and fits it on the CPU: 0 renders,
    0 mesh calls; fit record base_signature B2, source.fsig F1, refitted
    False (B2's views are byte-identical to B1's, so no registration
    either: frame.registered False); the worn front of F2 is a copy
    (copied_from F1).
[7] Dress text changed (FRAGMENT2; B2 unchanged, F3 != F2) and the bad
    ghost back for both attempts: run_garment -> {ok False, step "ghost"},
    3 (worn f, worn bd, worn b) + 2 (ghost back) renders — the back renders
    first, so the ghost front never starts — NO mesh call; status
    failed.step "ghost"; the item's text untouched (no description refresh
    for clothing); garment_info: fsig F3, ghost back accepted False with 2
    attempts, no ghost front url, served_fsig F2 (the fallback),
    stale_reasons ["description_changed"], preview_url names the F2 fit's
    content version.
[8] Outfit model (the worn outfit OSIG, its dressed images from
    generate_dressed_images): generate_for_current_outfit publishes
    model3d/OSIG.glb WITHOUT a garment node and model3d/assembled/OSIG.glb
    WITH "garment_clothing_D" (fsig F2); no garment_warnings.
[9] The F2 fit file broken (garbage bytes, record still accepted): a forced
    outfit build still publishes the bare model (no garment node), records
    garment_warnings (one entry naming the full tier), and leaves no
    assembled file.
[10] generate_base_model: a successful (stubbed) run calls after_base_model
    once; a failed one does not.
[11] Hair in the body mesh (the world default "body"): Neo, pipeline human,
    hair slot {short, black} (hair text), base images + model written ->
    after_base_model False, no hair item, worn {}, 0 renders, 0 mesh calls.
[12] The base views change during a run (moved here from the removed
    smoke_garment_ghost_pair.py [4]): a forced worn front whose FIRST render
    rewrites the base front view (one torso pixel: same base signature,
    other bytes, mtime +2 s for the stat-keyed hash cache -> another fsig)
    -> {ok False, step "worn", error INPUTS_CHANGED_ERROR} after that one
    render; the current fsig is no longer the run's.
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
DRESS = (40, 90, 50)
DRESS_ROWS = (320, 760)
FRAGMENT = "a knee-length green linen dress"
FRAGMENT2 = "a knee-length green cotton dress"
#: [3]: a forced worn front drops the back drafted from it (``garments``: "a new front of a drafted step drops
#: the back it was drafted from") and the later steps of both views (``garment_images._drop_later``).
FORCED_FRONT = [("worn", "front", 1), ("worn", "back", "d"), ("worn", "back", 1), ("ghost", "back", 1),
                ("ghost", "front", 1)]
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


def dressed(rgb):
    rgb[DRESS_ROWS[0]:DRESS_ROWS[1], 392:632] = DRESS
    return rgb


BASE = figure(canvas())
WORN = dressed(figure(canvas()))
GHOST = dressed(canvas())


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


def base_bodies(colour=(200, 160, 140), hips=False):
    """(unrigged GLB, rigged GLB) of the fixture body. ``hips``: the torso
    vertices below y 0.4 (unrigged frame) weighted Hips instead of Spine2 —
    the clothing fit needs a Hips-weighted vertex."""
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
    torso = names.index("Hips") if hips else names.index("Spine2")
    J[:, 0] = np.where(head, names.index("Head"),
                       np.where(P[:, 1] < 0.4, torso, names.index("Spine2")))
    Wt = np.zeros((n, 4))
    Wt[:, 0] = 1.0
    unrigged = fx.make_glb(P, F, U, image=solid_png((90, 90, 90)))
    rigged = rigged_glb(1.7 * P + np.array([0, 0.05, 0]), F, U, J, Wt, solid_png(colour))
    return unrigged, rigged


def dress_glb(bad=False) -> bytes:
    """The mesh stub's dress: a closed cylinder r 0.125, y 0.34 .. 0.78
    (unrigged frame), generated in its own frame (x4, shifted by (3, -2, 1));
    ``bad`` adds a separate cylinder r 0.03, y 0.1 .. 0.2 at x 0.5."""
    import smoke_garment_fit as fx
    P, F = fx.cylinder(0.125, 0.34, 0.78)
    if bad:
        P2, F2 = fx.cylinder(0.03, 0.1, 0.2)
        P, F = fx.merge((P, F), (P2 + np.array([0.5, 0, 0]), F2))
    c = np.array([0, 0.5, 0])
    U = np.stack([np.linspace(0, 1, len(P)), np.linspace(1, 0, len(P))], 1)
    return fx.make_glb(4 * (P - c) + np.array([3, -2, 1]), F, U, image=solid_png(DRESS))


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
        # The world's hair method stays the default "body": the hair is in the body mesh, no hair item.
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
        from app.core import (base_body, expression_regen, extension_rig, garment_assembly, garment_fit,
                              garment_hair, glb_delivery, model3d, model_refs, sync_topics)
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
        mode = {"ghost_back_bad": False, "mesh_bad": False, "mesh_raise_at": 0, "on_render": None}
        charmod.run_rembg = rembg_stub

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            draft = g.get("stage") == "draft"
            RENDERS.append((g["step"], g["view"], "d" if draft else g["attempt"], g["fsig"]))
            hook, mode["on_render"] = mode["on_render"], None
            if hook:
                hook()
            if g["step"] == "worn":
                arr = WORN
            elif g["view"] == "back" and mode["ghost_back_bad"]:
                arr = canvas()  # no garment at all
            else:
                arr = GHOST
            # The edit renders on the square canvas (side max(W, H) = 1200,
            # the source centred at x offset (1200 - 1024) // 2 = 88): the
            # stub answers with the planned image placed the same way. The
            # drafted worn back is a fresh render in its own frame.
            side = kw["override_width"]
            if draft:
                out_canvas = arr
            else:
                out_canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
                dy, dx = (out_canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
                out_canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(out_canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g.get("attempt", 0),
                                                            **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder

        class FakeService:
            def generate_mesh(self, **kw):
                MESHES.append(kw)
                if mode["mesh_raise_at"] and len(MESHES) == mode["mesh_raise_at"]:
                    raise RuntimeError("no backend available for mesh_garment: FakeMesh (cooling down)")
                Path(kw["output_path"]).write_bytes(dress_glb(bad=mode["mesh_bad"]))
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
        # Wearing the own-mesh dress asks for the outfit renders (pose / tpose): not part of this smoke.
        model_refs.trigger_now = lambda name, kinds=None, **kw: None
        model_refs.schedule_outfit_render = lambda name: None

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
        hid = inventory.add_item(name="Dress", category="outfit_piece", owner="Demo", item_id="dress",
                                 prompt_fragment=FRAGMENT,
                                 outfit_piece={"slots": ["top", "bottom"], "outfit_types": ["casual"],
                                               "mesh_mode": "own_mesh"})["id"]
        inventory.add_to_inventory("Demo", hid)
        check("dress worn", inventory.equip_piece("Demo", hid, source="smoke").get("status"), "ok")
        check("no hair item (method body)", garment_hair.find_hair_item("Demo", get_character_profile("Demo")),
              None)
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
            unrigged, rigged = base_bodies(colour, hips=True)
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
        check("ran", res.get("ran"), ["worn", "ghost", "cutout", "mesh", "fit"])
        check("renders", [(s, v, a) for s, v, a, _f in RENDERS],
              [("worn", "front", 1), ("worn", "back", "d"), ("worn", "back", 1), ("ghost", "back", 1),
               ("ghost", "front", 1)])
        for step in ("worn", "ghost", "cutout"):
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
        node = f"garment_clothing_{hid}"
        if fit.is_file():
            check("fit node", node in node_names(fit.read_bytes()), True)
            check("fit extras", garment_extras(fit.read_bytes(), node), {"kind": "clothing", "item_id": hid, "fsig": f1})
            from app.core import glb_mesh
            fit_tris = len(glb_mesh.static_arrays(fit.read_bytes())[1])
            want_low = max(1, int(round(refine.lod_ratio("character") * fit_tris)))
            check("decimations", [(d[1], d[2]) for d in DECIMATES], [("prepared", 60000), ("low", want_low)])
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

        # --- [3] forced worn front ------------------------------------------------
        print("[3] forced worn front re-runs it and every later step")
        RENDERS.clear(), MESHES.clear(), DECIMATES.clear()
        res = garments.run_garment("Demo", hid, steps="worn", view="front", force=True)
        check("ok", res.get("ok"), True)
        check("renders", [(s, v, a) for s, v, a, _f in RENDERS], FORCED_FRONT)
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

        print("[4b] mesh attempt 2 fails at the backend after a refused attempt 1")
        MESHES.clear()
        mode["mesh_bad"], mode["mesh_raise_at"] = True, 2
        res = garments.run_garment("Demo", hid, steps="mesh", force=True)
        mode["mesh_bad"], mode["mesh_raise_at"] = False, 0
        attempts = (res.get("gates") or {}).get("attempts") or []
        check("failed at mesh", (res.get("ok"), res.get("step"), len(MESHES)), (False, "mesh", 2))
        check("both attempts kept", [a.get("attempt") for a in attempts], [1, 2])
        check("attempt 1 = gate numbers",
              (attempts[0].get("ok"), (attempts[0].get("largest_component_share") or 1) < 0.98) if attempts else None,
              (False, True))
        check("attempt 2 = the error",
              (attempts[1].get("ok"), "no backend available" in (attempts[1].get("error") or ""))
              if len(attempts) > 1 else None, (False, True))
        failed = gs.status("Demo", hid)["failed"] or {}
        check("status carries both attempts",
              (failed.get("step"), len((failed.get("gates") or {}).get("attempts") or [])), ("mesh", 2))
        check("error names both", ("no backend available" in (failed.get("error") or ""),
                                   "attempt 1 refused" in (failed.get("error") or "")), (True, True))
        mrec = gs.read_record(prepared.with_suffix(".json"))
        check("step record keeps both", (mrec.get("accepted"), len(mrec.get("attempts") or [])), (False, 2))
        print("[4c] a new run clears the previous failure")
        lock = gs.char_lock("Demo")
        lock.acquire()
        try:
            check("start", garments.start_garment("Demo", hid)["started"], True)
            st = gs.status("Demo", hid)
            check("queued without the old failure", (st["running_step"], st["failed"]), ("queued", None))
        finally:
            lock.release()
        check("idle", garments.wait_idle(120), True)
        check("repaired", (gs.status("Demo", hid)["failed"], prepared.is_file()), (None, True))

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
            check("start (waits on the run lock)", garments.start_garment("Demo", hid)["started"], True)
            queued = {"started": False, "queued": True, "position": 1, "behind": hid}
            check("second start queued behind the running one", garments.start_garment("Demo", hid), queued)
            check("third identical start reuses it", garments.start_garment("Demo", hid), queued)
            check("one waiting run", garments.queue_state("Demo")["queue"], [hid])
            check("queued from the start", gs.status("Demo", hid)["running_step"], "queued")
        finally:
            lock.release()
        check("idle", garments.wait_idle(60), True)
        check("queued mark ended", (gs.status("Demo", hid)["running_step"], gs.status("Demo", hid)["failed"]),
              (None, None))

        # --- [5b] fit by an older fit algorithm ---------------------------------------------
        print("[5b] fit record without fit_version -> stale -> fit only")
        check("record carries the version", rec5.get("fit_version"), garment_fit.FIT_VERSION["clothing"])
        old = {k: v for k, v in rec5.items() if k != "fit_version"}
        gs.write_record(gs.garment_path("Demo", hid, f1, "fit").with_suffix(".json"), old)
        check("stale", garments._fit_state("Demo", hid, f1, new_sha), "stale")
        check("stale reason", garments.garment_info("Demo", hid)["stale_reasons"], ["fit_algorithm_updated"])
        before = counts()
        check("after_base_model starts", garments.after_base_model("Demo"), True)
        check("idle", garments.wait_idle(120), True)
        after = counts()
        check("no render, no mesh, refit (prepared kept, low rebuilt)",
              (after[0] - before[0], after[1] - before[1], after[2] - before[2]), (0, 0, 1))
        rec5b = fit_record(f1)
        check("refit record", (rec5b.get("accepted"), rec5b.get("fit_version"), rec5b.get("base_model_sha256")),
              (True, garment_fit.FIT_VERSION["clothing"], new_sha))
        check("accepted again", garments._fit_state("Demo", hid, f1, new_sha), "accepted")
        older = {**rec5b, "fit_version": garment_fit.FIT_VERSION["clothing"] - 1}
        gs.write_record(gs.garment_path("Demo", hid, f1, "fit").with_suffix(".json"), older)
        check("older version stale", garments._fit_state("Demo", hid, f1, new_sha), "stale")
        gs.write_record(gs.garment_path("Demo", hid, f1, "fit").with_suffix(".json"), rec5b)

        # --- [6] new bsig ---------------------------------------------------------------
        print("[6] new profile image -> new base signature -> refit from the B1 source")
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
        check("0 renders, 0 mesh", (after[0] - before[0], after[1] - before[1]), (0, 0))
        rec6 = fit_record(f2)
        check("fit on B2", (rec6.get("accepted"), rec6.get("base_signature")), (True, b2))
        check("source F1, not refitted (same views), no registration",
              ((rec6.get("source") or {}).get("fsig"), rec6.get("refitted"), (rec6.get("frame") or {}).get("registered")),
              (f1, False, False))
        copied = gs.garment_path("Demo", hid, f2, "image", step="worn", view="front")
        check("worn front copied", gs.read_record(copied.with_suffix(".json")).get("copied_from"), f1)

        # --- [7] description change + ghost refusal --------------------------------------
        print("[7] ghost refusal")
        check("dress text changed", bool(inventory.update_item(hid, {"prompt_fragment": FRAGMENT2})), True)
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
        check("item text untouched", inventory.get_item(hid).get("prompt_fragment"), FRAGMENT2)
        info = garments.garment_info("Demo", hid)
        check("info fsig", info.get("fsig"), f3)
        gb = ((info.get("steps") or {}).get("ghost") or {}).get("back") or {}
        check("ghost back refused, 2 attempts", (gb.get("accepted"), len(gb.get("attempts") or [])), (False, 2))
        check("no ghost front url", bool(((info["steps"]["ghost"]).get("front") or {}).get("url")), False)
        check("served fsig", info.get("served_fsig"), f2)
        check("stale reasons", info.get("stale_reasons"), ["description_changed"])
        from app.core.http_files import content_version
        f2fit = gs.garment_path("Demo", hid, f2, "fit")
        check("preview url", (info.get("preview_url") or "").endswith(f"?v={content_version(f2fit)}"), True)
        check("info failed", (info.get("failed") or {}).get("step"), "ghost")
        check("mesh/fit steps", (info["steps"]["mesh"].get("status"), info["steps"]["fit"].get("status")),
              ("missing", "missing"))

        # --- [8] outfit model + assembly ---------------------------------------------------
        print("[8] outfit model: bare + assembled")
        opieces, _oitems, osig = model_refs.current_outfit_state("Demo")
        base_body.generate_dressed_images("Demo", pieces=opieces, items=[], signature=osig)
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
                  {"kind": "clothing", "item_id": hid, "fsig": f2})

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
        # --- [11] hair in the body mesh: no hair item, no run ----------------------------
        print("[11] method body: after_base_model makes no hair item")

        def write_base_for(name):
            bsig = base_body.base_signature(name)
            r = get_character_dir(name) / "model_refs"
            m = get_character_dir(name) / "model3d"
            r.mkdir(parents=True, exist_ok=True)
            for v in base_body.BASE_VIEWS:
                stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
                (r / f"{stem}.png").write_bytes(png(BASE))
                (r / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
            unrigged, rigged = base_bodies(hips=True)
            (m / "unrigged").mkdir(parents=True, exist_ok=True)
            (m / "unrigged" / f"{bsig}.glb").write_bytes(unrigged)
            (m / f"{bsig}.glb").write_bytes(rigged)
            (m / f"{bsig}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated"}))
            return bsig

        neo = json.loads(json.dumps(human))
        neo["body_slots"]["hair"] = {"length": "short", "color": "black"}
        check("create Neo", save_character_profile("Neo", neo, create_new=True), True)
        check("pipeline Neo", base_body.set_pipeline("Neo", True), True)
        check("Neo has hair text", bool(garment_hair.hair_description("Neo")), True)
        write_base_for("Neo")
        garments.wait_idle(30)
        before = counts()
        check("Neo not started", garments.after_base_model("Neo"), False)
        check("idle", garments.wait_idle(30), True)
        check("Neo no item", (inventory.get_equipped_mesh_pieces("Neo"),
                              garment_hair.find_hair_item("Neo", get_character_profile("Neo"))), ({}, None))
        check("no GPU work", counts()[:2], before[:2])

        # --- [12] the base views change during a run ----------------------------------------
        print("[12] base front view rewritten during the run -> refused, fsig moved on")
        from app.core.garments import INPUTS_CHANGED_ERROR
        b_now = base_body.base_signature("Demo")
        f_before = gs.garment_fsig("Demo", hid)

        def rewrite_front():
            front = refs / f"tpose_{b_now}.png"
            arr = BASE.copy()
            arr[1000, 400] = (201, 160, 140)  # one torso pixel: same signature, other bytes
            front.write_bytes(png(arr))
            st = front.stat()
            os.utime(front, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

        mode["on_render"] = rewrite_front
        RENDERS.clear()
        res = garments.run_garment("Demo", hid, steps="worn", view="front", force=True)
        check("refused at worn", (res.get("ok"), res.get("step"), res.get("error")),
              (False, "worn", INPUTS_CHANGED_ERROR))
        check("one render", [(s_, v, a) for s_, v, a, _f in RENDERS], [("worn", "front", 1)])
        check("fsig moved on", gs.garment_fsig("Demo", hid) != f_before, True)

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
