#!/usr/bin/env python3
"""Outfit body as mesh (plan docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md,
Task 1; spec docs/superpowers/specs/2026-11-10-outfit-body-mesh-mode-design.md):
with ``outfit_body_mode: "mesh"`` the body under the own-mesh garments is the
dressed views of the texture ``tsig`` meshed and rigged through the old
path's staged chain — one outfit body per tsig.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_mesh.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process.

Stubs: the image service (``generate_mesh`` writes an unrigged fixture GLB,
``generate_rig`` a 52-joint Mixamo fixture GLB; both recorded as ONE HUB JOB
each in CHAIN), ``model3d._auto_retexture`` / ``_auto_normalize`` /
``_extension_rig_once`` and ``collision.refresh`` (recorders into CHAIN, in
call order; bytes unchanged), ``_attach_measurement`` (no-op), ``build_lod``
(recorder, with the auto distance tier on); as smoke_texture_body_reuse:
``garments._run_locked`` (an accepted fit per own-mesh piece on the current
base model sha), ``expression_regen.render_character_image`` (one entry =
ONE IMAGE JOB), ``run_rembg``, ``body_retexture.retexture`` (one entry = ONE
WORKER RUN, copies its input), no extension groups, GLB delivery identity.
The staged chain, hub-op records, view guard, texture store, signature rules,
assembly, status and overview are REAL.

Fixture: Demo (human-roleplay, profile image, on the pipeline, side views OFF
-> dressed views front + back, ``outfit_body_mode: "mesh"``), base images
tpose[_<view>]_<B1>, base model of smoke_garment_chain. Items: under
{[underwear_bottom] "plain grey underwear"}, shoes {[feet] "white sneakers"},
dress {[top], covers [bottom], own_mesh, "a long red dress"}, skirt {[bottom]
"a blue pleated skirt"}. Outfits: A {under, shoes}; B = A + dress; C {dress};
G = A + skirt.

Expected, derived by hand from the spec and the plan's Global Constraints:

[1] Body id rule: outfit_body_id(t) = "ob" + sha256 of the literal
    '{"mode":"mesh","texture_signature":"<t>","version":1}' [:8]; a non-tsig
    raises ValueError; is_outfit_body_signature("ob" + 8 hex) True, a base
    signature / an outfit signature False.
[2] Mesh mode, A: 3 image jobs (front edit, back draft, back fit); the
    chain runs ONCE on the body id bA = outfit_body_id(tA), in this order:
    mesh(bA), rig(bA), retexture(bA), normalize(bA), extension(bA),
    collision(bA) — then the outfit copy: extension(sigA), collision(sigA);
    0 worker runs. The mesh job gets source tpose_<bA>.png, views {back},
    occasion "mesh_humanoid"; the hub-op manifest names outfit_body.body_id
    bA and no "pieces". model3d/<bA>.glb and unrigged/<bA>.glb exist; both
    sidecars carry the parent record {body_id bA, mode mesh, version 1,
    texture_signature tA, base_signature B1, built_for sigA, used_views
    [front, back], views {front: sha(tpose_<sigA>.png), back:
    sha(tpose_back_<sigA>.png)}}; the unrigged sidecar records the face
    cleanup step (status "skipped": off per character by default). Refs
    tpose[_back]_<bA>.png are byte copies of A's dressed views, their sidecars
    carry outfit_body and NO equipped_pieces. Outfit model A: bytes = the
    body's; sidecar outfit_body_mode "mesh", body_id bA, body_sha256 =
    sha(body), texture_signature tA, source "base_body", no "outfit_body";
    distance tier requested for sigA only (build_lod [sigA]); outfit_info
    ready; find_model3d(Demo, bA) is the body (an outfit body is never
    stale); find_model3d_serving(Demo) = (sigA, "exact").
[3] B = A + dress (own mesh): tsig tA again -> 0 image jobs, 0 chain steps
    on a body (no mesh, no rig), 0 worker runs; B's model names body bA; the
    dress has an accepted (base) fit but no prepared mesh in this fixture, so
    its fit on bA (Task 2, garments.body_fit) cannot be made: garment_warnings
    name NOT_FITTED_ON_BODY for "Dress (The garment mesh is missing — run the
    mesh step first)", the failure is recorded on bA
    (garments/bodies/<bA>/failed/dress_<F>.json), no assembled/<sigB>.glb —
    the base fit is never grafted onto the body.
[4] C {dress}: empty dress text -> the base body: 0 image jobs, no mesh/rig
    job, 0 worker runs; model dressed False, no body_id.
[5] A rebuilt with force in mesh mode: no mesh/rig job (the body is current).
[6] Mode -> retexture: A stale, stale_reason "body_mode"; build -> 0 image
    jobs, 0 mesh/rig jobs, 1 worker run; the sidecar has no outfit_body_mode
    / body_id key and names tA (the retexture path unchanged). Mode -> mesh:
    A stale "body_mode"; build -> 0 mesh/rig jobs, 0 worker runs, body file
    bytes + mtime unchanged.
[7] The body file rewritten (as a re-rig would): A stale "outfit_body";
    build -> 0 mesh/rig jobs; A's bytes = the new body bytes. A re-rig of the
    body (rerig_model(Demo, bA)): ok, ONE rig job on bA, the body sidecar
    still carries the parent record (body_id bA) and stored_outfit_body
    still calls it current (no new mesh on the next outfit build).
[8] G = A + skirt: other dress text -> tsig tG != tA -> 3 image jobs, ONE
    mesh + ONE rig job, on body outfit_body_id(tG) != bA.
[9] GC: verify_cache calls neither body stale (meshes or refs).
[10] Overview: A's steps have the row outfit_body (done) and no
    painted_body / retexture / face_texels rows; outfit_body_overview(bA)
    rows start outfit_body, mesh, face_cleanup, face_retexture, rig.
"""
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
BASE_PX = {"front": (200, 10, 10), "back": (10, 200, 10), "left": (10, 10, 200), "right": (200, 200, 10)}
FRAG = {"under": "plain grey underwear", "shoes": "white sneakers", "dress": "a long red dress",
        "skirt": "a blue pleated skirt"}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(rgb, size=8) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(out, "PNG")
    return out.getvalue()


def colour_of(name: str):
    d = hashlib.md5(name.encode()).digest()
    return d[0], d[1], d[2]


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture_glb(rig: bool = False) -> bytes:
    from app.core.rig_contract import BASE_JOINT_NAMES
    color = png((180, 120, 90), 16)
    doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"material": 0}]}],
           "buffers": [{"byteLength": len(color)}],
           "bufferViews": [{"byteOffset": 0, "byteLength": len(color)}],
           "images": [{"bufferView": 0, "mimeType": "image/png"}],
           "textures": [{"source": 0}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    if rig:
        doc["nodes"] = [{"name": n} for n in BASE_JOINT_NAMES]
        doc["skins"] = [{"joints": list(range(len(BASE_JOINT_NAMES)))}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    color += b"\0" * (-len(color) % 4)
    body = (struct.pack("<II", len(raw), 0x4e4f534a) + raw
            + struct.pack("<II", len(color), 0x004e4942) + color)
    return b"glTF" + struct.pack("<II", 2, len(body) + 12) + body


CHAIN, MESH_CALLS, CREATED, LOD = [], [], [], []


class FakeService:
    def generate_mesh(self, *, source_image_path, output_path, view_images=None, occasion="", **kw):
        stem = Path(output_path).stem
        CHAIN.append(("mesh", stem))
        MESH_CALLS.append({"source": Path(source_image_path).name, "views": sorted(view_images or {}),
                           "occasion": occasion})
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fixture_glb())
        return {"ok": True, "path": output_path, "backend": "fake-mesh"}

    def generate_rig(self, *, mesh_path, output_path, rig, **kw):
        CHAIN.append(("rig", Path(mesh_path).stem))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fixture_glb(True))
        return {"ok": True, "path": output_path, "backend": "fake-rig", "rig": rig}


def garment_quad(item_id: str):
    from app.core.glb_mesh import GarmentMesh
    P = np.array([[0.0, 1.0, 0.25], [0.1, 1.0, 0.25], [0.1, 1.1, 0.25], [0.0, 1.1, 0.25]])
    return GarmentMesh(positions=P, normals=None, uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float),
                       indices=np.array([[0, 1, 2], [0, 2, 3]]), joints=np.zeros((4, 4), np.int64),
                       weights=np.tile([1.0, 0, 0, 0], (4, 1)), joint_names=["mixamorig:Spine2"],
                       image=png(colour_of(item_id), 8), mime="image/png")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-body-mesh-") as tmp:
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

        import smoke_garment_chain as chain
        from app.core import (base_body, body_retexture, collision, expression_regen, extension_rig, garments,
                              glb_delivery, glb_mesh, hub_ops, model3d, model_overview, model_refs,
                              outfit_cache_gc, sync_topics)
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        # --- stubs -------------------------------------------------------------
        RENDERS, WORKER = [], []

        def run_locked(character_name, item, kind, wanted, view, force):
            item_id = item["id"]
            fsig = gs.garment_fsig(character_name, item_id)
            bsig = base_body.base_signature(character_name)
            rigged = (get_character_dir(character_name) / "model3d" / f"{bsig}.glb").read_bytes()
            digest = hashlib.sha256(rigged).hexdigest()
            fit = gs.garment_path(character_name, item_id, fsig, "fit")
            if gs.read_record(fit.with_suffix(".json")).get("base_model_sha256") == digest:
                return {"ok": True, "fsig": fsig, "ran": []}
            fit.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(glb_mesh.graft(rigged, garment_quad(item_id), name=f"garment_{kind}_{item_id}",
                                           extras={"kind": kind, "item_id": item_id, "fsig": fsig}))
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "base_signature": bsig,
                "base_model_sha256": digest})
            return {"ok": True, "fsig": fsig, "ran": ["worn", "ghost", "cutout", "mesh", "fit"]}

        def rembg(data, model="u2net", **kw):
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                rgba = im.convert("RGBA")
            for x in range(8):
                for y in range(8):
                    if min(x, y) < 2 or max(x, y) > 5:
                        rgba.putpixel((x, y), (0, 0, 0, 0))
            out = io.BytesIO()
            rgba.save(out, "PNG")
            return out.getvalue()

        def render(character_name, *, output_stem, equipped_pieces, equipped_items, **kw):
            from PIL import Image
            RENDERS.append({"stem": Path(output_stem).name, "occasion": kw.get("occasion")})
            target = Path(str(output_stem) + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), colour_of(target.stem)).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            token = model_refs.mesh_items_token(character_name, equipped_pieces, profile)
            meta = {"prompt": kw.get("bare_prompt") or "", "equipped_pieces": equipped_pieces or {},
                    "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    "created_at": f"2026-11-10T00:00:{len(RENDERS):02d}+00:00",
                    **({"mesh_token": token} if token else {}), **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        def retexture(glb_in, views, out_glb, *, proof, atlas, **kw):
            WORKER.append(sorted(views))
            Path(out_glb).write_bytes(Path(glb_in).read_bytes())
            return {}

        def recorder(name, result=None):
            def run(character_name, path, *a, **k):
                CHAIN.append((name, Path(path).stem))
                return result() if callable(result) else result
            return run

        def recording_create(kind, subject, inputs, **kw):
            CREATED.append(json.loads(json.dumps(inputs)))
            return real_create(kind, subject, inputs, **kw)

        real_create = hub_ops.create
        garments._run_locked = run_locked
        expression_regen.render_character_image = render
        charmod.run_rembg = rembg
        body_retexture.retexture = retexture
        service.get_image_service = lambda: FakeService()
        hub_ops.create = recording_create
        model3d._auto_retexture = recorder("retexture")
        model3d._auto_normalize = recorder("normalize")
        model3d._extension_rig_once = recorder("extension", lambda: {"ok": True, "noop": True})
        collision.refresh = recorder("collision", False)
        model3d._attach_measurement = lambda *a, **k: None
        model3d._auto_lod_enabled = lambda: True
        model3d.build_lod = lambda name, signature=None, **k: LOD.append(signature) or {"ok": True}
        model3d.maybe_auto_generate_for_outfit = lambda *a, **k: False
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None
        model_refs.trigger_now = lambda *a, **k: None
        model_refs.schedule_outfit_render = lambda name: None
        config._CONFIG.setdefault("base_body", {})["dressed_side_views"] = False

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(png((50, 60, 70)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        def set_mode(mode):
            stored = get_character_profile("Demo")
            stored["outfit_body_mode"] = mode
            save_character_profile("Demo", stored)
            return base_body.outfit_body_mode("Demo")

        check("mode default retexture", base_body.outfit_body_mode("Demo"), "retexture")
        check("mode mesh", set_mode("mesh"), "mesh")

        def piece(item_id, slots, *, covers=(), own_mesh=False):
            op = {"slots": list(slots), "covers": list(covers), "outfit_types": ["casual"]}
            if own_mesh:
                op["own_mesh"] = True
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=FRAG[item_id], outfit_piece=op)["id"]

        check("items", [piece("under", ["underwear_bottom"]), piece("shoes", ["feet"]),
                        piece("dress", ["top"], covers=["bottom"], own_mesh=True), piece("skirt", ["bottom"])],
              ["under", "shoes", "dress", "skirt"])
        for item in FRAG:
            inventory.add_to_inventory("Demo", item)

        def wear(pieces):
            stored = get_character_profile("Demo")
            stored["equipped_pieces"] = dict(pieces)
            save_character_profile("Demo", stored)
            return model_refs.current_outfit_state("Demo")[2]

        cdir = get_character_dir("Demo")
        refs = cdir / "model_refs"
        mdir = cdir / "model3d"
        refs.mkdir(parents=True, exist_ok=True)
        b1 = base_body.base_signature("Demo")
        from PIL import Image
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            im.putpixel((4, 4), BASE_PX[v] + (255,))
            im.save(refs / f"{stem}.png")
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        unrigged, rigged = chain.base_bodies((200, 160, 140))
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged)
        (mdir / f"{b1}.glb").write_bytes(rigged)
        (mdir / f"{b1}.json").write_text(json.dumps({
            "base": True, "rig": "mixamo", "signature": b1, "format": "glb", "source": "generated"}))

        def render_and_build(force_build=False):
            r0, w0, c0 = len(RENDERS), len(WORKER), len(CHAIN)
            model_refs.generate_model_ref_images("Demo", kinds=("tpose",))
            garments.wait_idle(30)
            r1 = len(RENDERS)
            result = model3d.generate_for_current_outfit("Demo", force=force_build)
            return r1 - r0, len(WORKER) - w0, CHAIN[c0:], result

        def jobs_of(steps):
            return [s for s in steps if s[0] in ("mesh", "rig")]

        def model_meta(sig):
            return model3d._read_sidecar(mdir / f"{sig}.glb")

        def stale_reason():
            return base_body.outfit_info("Demo").get("stale_reason")

        A = {"underwear_bottom": "under", "feet": "shoes"}

        # --- [1] the id rule ----------------------------------------------------------
        print("[1] body id rule")
        t_x = "tex0123456789ab"
        literal = '{"mode":"mesh","texture_signature":"' + t_x + '","version":1}'
        check("id = hand hash", base_body.outfit_body_id(t_x),
              "ob" + hashlib.sha256(literal.encode("utf-8")).hexdigest()[:8])
        try:
            base_body.outfit_body_id("base01234567")
            check("non-tsig refused", False, True)
        except ValueError:
            check("non-tsig refused", True, True)
        check("shapes", (base_body.is_outfit_body_signature("ob0123abcd"), base_body.is_outfit_body_signature(b1),
                         base_body.is_outfit_body_signature("0123456789ab")), (True, False, False))

        # --- [2] the first body --------------------------------------------------------
        print("[2] mesh mode: one body per tsig through the staged chain, in order")
        sig_a = wear(A)
        jobs, runs, steps, result = render_and_build()
        t_a = model_meta(sig_a).get("texture_signature")
        b_a = base_body.outfit_body_id(t_a) if base_body.is_texture_signature(t_a) else None
        check("A: ok, 3 image jobs, 0 worker runs", (result.get("ok"), jobs, runs), (True, 3, 0))
        check("A: chain in order", steps,
              [("mesh", b_a), ("rig", b_a), ("retexture", b_a), ("normalize", b_a), ("extension", b_a),
               ("collision", b_a), ("extension", sig_a), ("collision", sig_a)])
        check("A: mesh job inputs", MESH_CALLS[-1] if MESH_CALLS else None,
              {"source": f"tpose_{b_a}.png", "views": ["back"], "occasion": "mesh_humanoid"})
        manifest = (CREATED[-1].get("manifest") or {}) if CREATED else {}
        check("A: hub-op manifest", ((manifest.get("outfit_body") or {}).get("body_id"), "pieces" in manifest,
                                     CREATED[-1].get("signature") if CREATED else None), (b_a, False, b_a))
        body = mdir / f"{b_a}.glb"
        body_meta = model3d._read_sidecar(body)
        unrigged_meta = model3d._read_sidecar(mdir / "unrigged" / f"{b_a}.glb")
        want_parent = {"body_id": b_a, "mode": "mesh", "version": 1, "texture_signature": t_a, "base_signature": b1,
                       "built_for": sig_a, "used_views": ["front", "back"],
                       "views": {"front": sha(refs / f"tpose_{sig_a}.png"),
                                 "back": sha(refs / f"tpose_back_{sig_a}.png")}}
        for label, meta in (("rigged", body_meta), ("unrigged", unrigged_meta)):
            parent = meta.get("outfit_body") or {}
            check(f"A: {label} body parent record", {k: parent.get(k) for k in want_parent}, want_parent)
        check("A: body files", (body.is_file(), (mdir / "unrigged" / f"{b_a}.glb").is_file()), (True, True))
        check("A: face cleanup step recorded", (unrigged_meta.get("face_cleanup") or {}).get("status"), "skipped")
        for kind in ("tpose", "tpose_back"):
            mine = refs / f"{kind}_{b_a}.png"
            side = json.loads(mine.with_suffix(".json").read_text()) if mine.is_file() else {}
            check(f"A: body ref {kind}", (mine.is_file() and mine.read_bytes() == (refs / f"{kind}_{sig_a}.png")
                                          .read_bytes(), (side.get("outfit_body") or {}).get("body_id"),
                                          "equipped_pieces" in side), (True, b_a, False))
        meta_a = model_meta(sig_a)
        check("A: outfit model = body bytes", sha(mdir / f"{sig_a}.glb") == sha(body), True)
        check("A: outfit sidecar", {k: meta_a.get(k) for k in ("outfit_body_mode", "body_id", "body_sha256",
                                                              "source", "dressed")},
              {"outfit_body_mode": "mesh", "body_id": b_a, "body_sha256": sha(body), "source": "base_body",
               "dressed": True})
        check("A: no parent record on the outfit", "outfit_body" in meta_a, False)
        check("A: distance tier for the outfit only", LOD, [sig_a])
        check("A: outfit_info ready", base_body.outfit_info("Demo")["status"], "ready")
        check("A: body never stale", model3d.find_model3d("Demo", b_a), body)
        served = model3d.find_model3d_serving("Demo")
        check("A: serving", (served[0].stem if served[0] else None, served[1]), (sig_a, "exact"))

        # --- [3] same tsig, other own-mesh piece ---------------------------------------
        print("[3] same painted pieces, an own-mesh piece more -> the same body, no job")
        sig_b = wear({**A, "top": "dress"})
        jobs, runs, steps, result = render_and_build()
        meta_b = model_meta(sig_b)
        check("B: ok, 0 image jobs, 0 runs, no mesh/rig job", (result.get("ok"), jobs, runs, jobs_of(steps)),
              (True, 0, 0, []))
        check("B: same tsig, same body", (meta_b.get("texture_signature"), meta_b.get("body_id")), (t_a, b_a))
        fit = gs.accepted_fit("Demo", "dress", base_model_sha=base_body.base_model_sha256("Demo", b1))
        check("B: the dress has a (base) fit", bool(fit), True)
        check("B: not fitted on this body", base_body.NOT_FITTED_ON_BODY.format(
            items="Dress (The garment mesh is missing — run the mesh step first)")
              in (meta_b.get("garment_warnings") or []), True)
        check("B: failure recorded on the body",
              gs.garment_path("Demo", "dress", gs.parse_name(fit[0])[1], "failed", body=b_a).is_file(), True)
        check("B: no assembly with a base fit", (mdir / "assembled" / f"{sig_b}.glb").exists(), False)

        # --- [4] empty dress text ---------------------------------------------------------
        print("[4] empty dress text -> the base body")
        sig_c = wear({"top": "dress"})
        jobs, runs, steps, result = render_and_build()
        meta_c = model_meta(sig_c)
        check("C: ok, 0 image jobs, no mesh/rig job, 0 runs", (result.get("ok"), jobs, jobs_of(steps), runs),
              (True, 0, [], 0))
        check("C: base copy", (meta_c.get("dressed"), "body_id" in meta_c), (False, False))

        # --- [5] forced outfit rebuild -------------------------------------------------------
        print("[5] forced outfit rebuild keeps a current body")
        wear(A)
        jobs, runs, steps, result = render_and_build(force_build=True)
        check("A forced: ok, no mesh/rig job", (result.get("ok"), jobs_of(steps)), (True, []))

        # --- [6] mode back and forth ------------------------------------------------------------
        print("[6] retexture mode unchanged; mode back -> the body is reused")
        set_mode("retexture")
        check("retexture: A stale (body_mode)", (model3d.find_model3d("Demo", sig_a), stale_reason()),
              (None, "body_mode"))
        jobs, runs, steps, result = render_and_build()
        meta_r = model_meta(sig_a)
        check("retexture: ok, 0 image jobs, 0 mesh/rig jobs, 1 worker run",
              (result.get("ok"), jobs, jobs_of(steps), runs), (True, 0, [], 1))
        check("retexture: sidecar as before", ("outfit_body_mode" in meta_r, "body_id" in meta_r,
                                                meta_r.get("texture_signature")), (False, False, t_a))
        body_stat = (sha(body), body.stat().st_mtime_ns)
        set_mode("mesh")
        check("mesh again: A stale (body_mode)", (model3d.find_model3d("Demo", sig_a), stale_reason()),
              (None, "body_mode"))
        jobs, runs, steps, result = render_and_build()
        check("mesh again: ok, no mesh/rig job, 0 runs", (result.get("ok"), jobs_of(steps), runs), (True, [], 0))
        check("mesh again: body untouched", (sha(body), body.stat().st_mtime_ns), body_stat)
        check("mesh again: on body bA", model_meta(sig_a).get("body_id"), b_a)

        # --- [7] the body rebuilt --------------------------------------------------------------
        print("[7] the body rebuilt -> the outfit model is stale and copies the new body")
        body.write_bytes(body.read_bytes() + b"\0" * 4)
        check("rebuilt body: A stale (outfit_body)", (model3d.find_model3d("Demo", sig_a), stale_reason()),
              (None, "outfit_body"))
        jobs, runs, steps, result = render_and_build()
        check("rebuilt body: ok, no mesh/rig job", (result.get("ok"), jobs_of(steps)), (True, []))
        check("rebuilt body: A = the new body", sha(mdir / f"{sig_a}.glb"), sha(body))
        views_a = (model3d._read_sidecar(body).get("outfit_body") or {}).get("views")
        c0 = len(CHAIN)
        rerig = model3d.rerig_model("Demo", b_a)
        check("re-rig of the body: ok, one rig job", (rerig.get("ok"), jobs_of(CHAIN[c0:])), (True, [("rig", b_a)]))
        check("re-rig keeps the parent record",
              (model3d._read_sidecar(body).get("outfit_body") or {}).get("body_id"), b_a)
        check("re-rigged body still current",
              base_body.stored_outfit_body("Demo", b_a, tsig=t_a, view_shas=views_a) is not None, True)

        # --- [8] another tsig ------------------------------------------------------------------
        print("[8] other painted pieces -> another body")
        sig_g = wear({**A, "bottom": "skirt"})
        jobs, runs, steps, result = render_and_build()
        t_g = model_meta(sig_g).get("texture_signature")
        b_g = base_body.outfit_body_id(t_g) if base_body.is_texture_signature(t_g) else None
        check("G: ok, 3 image jobs, one mesh + one rig job on its own body",
              (result.get("ok"), jobs, jobs_of(steps)), (True, 3, [("mesh", b_g), ("rig", b_g)]))
        check("G: other tsig, other body", (t_g != t_a, b_g != b_a), (True, True))

        # --- [9] GC ------------------------------------------------------------------------------
        print("[9] the cache GC keeps the bodies")
        report = outfit_cache_gc.verify_cache("Demo")
        check("GC: no body stale", [s for s in report["stale_signatures"] if s in (b_a, b_g)], [])

        # --- [10] overview -------------------------------------------------------------------------
        print("[10] overview rows")
        wear(A)
        overview = model_overview.outfit_model_overview("Demo", mdir / f"{sig_a}.glb")
        ids = [row["id"] for row in overview[0]] if overview else []
        check("A: outfit_body row done", [row["status"] for row in overview[0] if row["id"] == "outfit_body"]
              if overview else None, ["done"])
        check("A: no painted-body rows", [i for i in ids if i in ("painted_body", "retexture", "face_texels")], [])
        body_rows = model_overview.outfit_body_overview("Demo", b_a)
        check("body overview head", [row["id"] for row in (body_rows or {}).get("steps", [])][:5],
              ["outfit_body", "mesh", "face_cleanup", "face_retexture", "rig"])

    print()
    if FAILS:
        print(f"FAIL: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
