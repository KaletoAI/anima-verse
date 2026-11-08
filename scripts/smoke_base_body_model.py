#!/usr/bin/env python3
"""Base body: the rigged base model (base_body.generate_base_model, model3d).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_model.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no hub, no Blender, no server process. Stubs: the
image service (``generate_mesh`` writes an unrigged fixture GLB,
``generate_rig`` a 52-joint Mixamo fixture GLB), ``refine.apply_script``
(recorder: applied, bytes unchanged), ``model3d._auto_retexture`` /
``_auto_normalize`` / ``_attach_measurement`` / ``request_lod`` (recorders),
the extension declarations (``rig_groups_for`` / ``resolved_extension_groups``
return four enabled groups: ``part`` op attached_part, ``part_bone`` op
attached_part_bone, ``inset`` op inset_part, ``jiggle`` op jiggle) and the
GLB delivery copy (identity).

Fixtures: ``Demo`` (template human-default, profile image), ``DemoFox``
(animal-default, profile image), ``DemoBare`` (human-default, profile image,
no base images). ``bsig`` = base_signature(Demo); ``osig`` = Demo's current
outfit signature (nothing worn). Stored in Demo's model_refs/: the four base
images tpose[_back|_left|_right]_<bsig>.png, each sidecar
{base_signature: bsig, equipped_pieces: {}, equipped_items: [],
mesh_variant: model_refs.mesh_variant(Demo, {})} — the same piece state the
nothing-worn outfit has, so WITHOUT the base exclusion the base model would
be the outfit's nearest stand-in; and the outfit front tpose_<osig>.png.
Demo's per-character view toggles are left at their default.

Expected, derived by hand from the brief (Task 4) and the code rules:

[1] generate_base_model(Demo):
    - result ok; ONE generate_mesh call with occasion "mesh_humanoid"
      (mesh_occasion_for_rig("mixamo")), view_images keys exactly
      {back, left, right} (all base views, whatever the toggles say), the
      source image a frozen copy named tpose_<bsig>.png;
    - the frozen hub-op inputs carry base True, signature bsig, manifest {};
    - model3d/<bsig>.glb exists, its sidecar has base True, rig "mixamo",
      signature bsig and NO "pieces" key; model3d/unrigged/<bsig>.glb
      exists and its sidecar has base True;
    - apply_script was called exactly once, with operation
      "extension_bones" and groups [jiggle] — no attached_part/inset_part
      batch; the extension state's group_ops lists only jiggle;
    - request_lod was never called.
    base_info(Demo)["model"]: signature bsig, status "ready", created_at the
    sidecar's, url "/characters/Demo/model3d/file?signature=<bsig>&v=<16 hex>".
    find_model3d_serving(Demo) is (None, "") — the base is never the
    outfit's model, nor its nearest; get_model3d_info(Demo)["model"] None
    and its signature osig.
[2] Resume: a fresh hub-op record with the SAME frozen inputs (base True),
    run through the registered resume entry ``_op_thread_resume(
    _generate_for_current_outfit)`` (which passes no base argument):
    ok; again apply_script once with extension_bones [jiggle] only, no
    request_lod; the sidecar still has base True.
[3] Outfit run (no flag): generate_for_current_outfit(Demo, force=True):
    ok; occasion "mesh_humanoid", no view_images (the toggles are off by
    default); apply_script batches in order: attached_part [part, part_bone],
    inset_part [inset], extension_bones [jiggle]; request_lod called once
    for model3d/<osig>.glb; the outfit sidecar has no "base" key; the hub-op
    inputs have no "base" key.
[4] Refusals: generate_base_model(DemoFox) and (DemoBare) raise ValueError
    (animal; no base images = MissingInput); nothing is generated.
[5] Routes (characters router on a bare FastAPI app, real sessions), GLB
    delivery is the stored file:
    admin GET /characters/Demo/model3d/file?signature=<bsig> -> 200, the
    stored base bytes; ?signature=<osig> -> 200, the outfit bytes;
    ?signature=deadbeef0000 -> 404; ?signature=base00000000 -> 404;
    player with ?signature=<bsig> -> 403; the url of base_info -> 200.
    POST /characters/Demo/base-body/model {} -> 202 {started: true}, the
    worker finishes cached (no new generate_mesh call); player -> 403;
    DemoFox -> 400; DemoBare -> 409.
"""
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def tiny_png(path: Path) -> None:
    from PIL import Image
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((4, 4), (200, 100, 50, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def color_png() -> bytes:
    import io
    from PIL import Image
    image = Image.new("RGB", (16, 16), "red")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def fixture_glb(rig: bool = False) -> bytes:
    from app.core.rig_contract import BASE_JOINT_NAMES
    color = color_png()
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


MESH_CALLS, RIG_CALLS, SCRIPT_CALLS, LOD_CALLS, CREATED = [], [], [], [], []

GROUPS = [{"id": "part", "op": "attached_part", "params": {}, "chains": []},
          {"id": "part_bone", "op": "attached_part_bone", "params": {}, "chains": []},
          {"id": "inset", "op": "inset_part", "params": {}, "chains": []},
          {"id": "jiggle", "op": "jiggle", "params": {}, "chains": []}]


class FakeService:
    def generate_mesh(self, *, source_image_path, output_path, view_images=None, occasion="", **kw):
        MESH_CALLS.append({"source": Path(source_image_path).name, "views": dict(view_images or {}),
                           "occasion": occasion})
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fixture_glb())
        return {"ok": True, "path": output_path, "backend": "fake-mesh"}

    def generate_rig(self, *, mesh_path, output_path, rig, **kw):
        RIG_CALLS.append({"mesh": Path(mesh_path).name, "rig": rig})
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fixture_glb(True))
        return {"ok": True, "path": output_path, "backend": "fake-rig", "rig": rig}


def batches():
    return [(c["operation"], c["groups"]) for c in SCRIPT_CALLS]


def clear():
    for calls in (MESH_CALLS, RIG_CALLS, SCRIPT_CALLS, LOD_CALLS, CREATED):
        calls.clear()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-model-") as tmp:
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

        from app.core import base_body, extension_rig, glb_delivery, hub_ops, model3d, model_refs
        from app.blender import refine
        from app.imagegen import service
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)

        human = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name, template in (("Demo", "human-default"), ("DemoFox", "animal-default"),
                               ("DemoBare", "human-default")):
            check(f"create {name}", save_character_profile(name, dict(human, template=template),
                                                           create_new=True), True)
            tiny_png(get_character_images_dir(name) / f"{name}_1.png")
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"profile image {name}", save_character_profile(name, stored), True)

        bsig = base_body.base_signature("Demo")
        osig = model_refs.current_outfit_state("Demo")[2]
        check("bsig shape", bool(re.fullmatch(r"base[0-9a-f]{8}", bsig)), True)
        refs = get_character_dir("Demo") / "model_refs"
        variant = model_refs.mesh_variant("Demo", {})
        for stem in (f"tpose_{bsig}", f"tpose_back_{bsig}", f"tpose_left_{bsig}", f"tpose_right_{bsig}"):
            tiny_png(refs / f"{stem}.png")
            (refs / f"{stem}.json").write_text(json.dumps({
                "base_signature": bsig, "equipped_pieces": {}, "equipped_items": [],
                "mesh_variant": variant}))
        tiny_png(refs / f"tpose_{osig}.png")
        (refs / f"tpose_{osig}.json").write_text(json.dumps({
            "equipped_pieces": {}, "equipped_items": [], "mesh_variant": variant}))

        # --- stubs -----------------------------------------------------------
        fake = FakeService()
        originals = {
            (service, "get_image_service"): service.get_image_service,
            (refine, "apply_script"): refine.apply_script,
            (model3d, "_auto_retexture"): model3d._auto_retexture,
            (model3d, "_auto_normalize"): model3d._auto_normalize,
            (model3d, "_attach_measurement"): model3d._attach_measurement,
            (model3d, "request_lod"): model3d.request_lod,
            (extension_rig, "rig_groups_for"): extension_rig.rig_groups_for,
            (extension_rig, "resolved_extension_groups"): extension_rig.resolved_extension_groups,
            (glb_delivery, "delivery_path"): glb_delivery.delivery_path,
            (hub_ops, "create"): hub_ops.create,
        }
        real_create = hub_ops.create

        def recording_create(kind, subject, inputs, **kw):
            CREATED.append(json.loads(json.dumps(inputs)))
            return real_create(kind, subject, inputs, **kw)

        def apply_script(path, operation, params, **kw):
            SCRIPT_CALLS.append({"operation": operation, "groups": [g["id"] for g in params["groups"]]})
            return {"applied": True, "data": {}}

        service.get_image_service = lambda: fake
        refine.apply_script = apply_script
        model3d._auto_retexture = lambda *a, **k: None
        model3d._auto_normalize = lambda *a, **k: None
        model3d._attach_measurement = lambda *a, **k: None
        model3d.request_lod = lambda name, path: LOD_CALLS.append(path.name) or False
        extension_rig.rig_groups_for = lambda *a, **k: [dict(g) for g in GROUPS]
        extension_rig.resolved_extension_groups = lambda *a, **k: [
            {**g, "enabled": True, "flip": False} for g in GROUPS]
        glb_delivery.delivery_path = lambda path, **kw: path
        hub_ops.create = recording_create
        model_dir = get_character_dir("Demo") / "model3d"
        try:
            print("[1] base run")
            result = base_body.generate_base_model("Demo")
            check("base ok", result.get("ok"), True)
            check("mesh calls", len(MESH_CALLS), 1)
            check("occasion", MESH_CALLS[0]["occasion"], "mesh_humanoid")
            check("views", sorted(MESH_CALLS[0]["views"]), ["back", "left", "right"])
            check("source", MESH_CALLS[0]["source"], f"tpose_{bsig}.png")
            check("frozen inputs", {k: CREATED[0].get(k) for k in ("base", "signature", "manifest")},
                  {"base": True, "signature": bsig, "manifest": {}})
            model = model_dir / f"{bsig}.glb"
            meta = model3d._read_sidecar(model)
            check("model published", model.is_file(), True)
            check("sidecar", {k: meta.get(k) for k in ("base", "rig", "signature")},
                  {"base": True, "rig": "mixamo", "signature": bsig})
            check("no piece manifest", "pieces" in meta, False)
            unrigged = model_dir / "unrigged" / f"{bsig}.glb"
            check("unrigged kept", unrigged.is_file(), True)
            check("unrigged sidecar base", model3d._read_sidecar(unrigged).get("base"), True)
            check("extension batches", batches(), [("extension_bones", ["jiggle"])])
            check("extension group_ops", (meta.get("extension_rig") or {}).get("group_ops"),
                  {"jiggle": "jiggle"})
            check("no request_lod", LOD_CALLS, [])
            info = base_body.base_info("Demo")["model"]
            check("info model", {k: info.get(k) for k in ("signature", "status", "created_at")},
                  {"signature": bsig, "status": "ready", "created_at": meta.get("created_at")})
            check("info url", bool(re.fullmatch(
                rf"/characters/Demo/model3d/file\?signature={bsig}&v=[0-9a-f]{{16}}", info.get("url") or "")),
                True)
            check("outfit serving ignores the base", model3d.find_model3d_serving("Demo"), (None, ""))
            # The info route lists the real backends — the real service.
            service.get_image_service = originals[(service, "get_image_service")]
            try:
                outfit_info = model3d.get_model3d_info("Demo")
            finally:
                service.get_image_service = lambda: fake
            check("3D tab: no outfit model", (outfit_info["signature"], outfit_info["model"]), (osig, None))

            print("[2] resume with the frozen inputs")
            inputs = CREATED[0]
            clear()
            op = real_create(model3d._OP_MESH, model3d._op_subject("Demo", bsig), inputs,
                             label="resume test", thread_owned=True)
            op.path("inputs", inputs["source_image"]).write_bytes((refs / f"tpose_{bsig}.png").read_bytes())
            views = {}
            for v, name in inputs["view_images"].items():
                frozen = op.path("inputs", "views", f"{v}.png")
                frozen.write_bytes((refs / name).read_bytes())
                views[v] = op.rel(frozen)
            op.update_state(lambda st: st.update(view_files=views))
            op.reload()
            resumed = model3d._op_thread_resume(model3d._generate_for_current_outfit)(op)
            check("resume ok", resumed.get("ok"), True)
            check("resume batches", batches(), [("extension_bones", ["jiggle"])])
            check("resume no request_lod", LOD_CALLS, [])
            check("resume sidecar base", model3d._read_sidecar(model).get("base"), True)

            print("[3] outfit run (unchanged behaviour)")
            clear()
            result = model3d.generate_for_current_outfit("Demo", force=True)
            check("outfit ok", result.get("ok"), True)
            check("outfit occasion", MESH_CALLS[0]["occasion"] if MESH_CALLS else None, "mesh_humanoid")
            check("outfit views", MESH_CALLS[0]["views"] if MESH_CALLS else None, {})
            check("outfit batches", batches(), [("attached_part", ["part", "part_bone"]),
                                                ("inset_part", ["inset"]),
                                                ("extension_bones", ["jiggle"])])
            check("outfit request_lod", LOD_CALLS, [f"{osig}.glb"])
            check("outfit sidecar no base", "base" in model3d._read_sidecar(model_dir / f"{osig}.glb"), False)
            check("outfit inputs no base", "base" in CREATED[0], False)

            print("[4] refusals")
            clear()
            for name in ("DemoFox", "DemoBare"):
                try:
                    base_body.generate_base_model(name)
                    check(f"{name} refused", "no error", "ValueError")
                except ValueError:
                    check(f"{name} refused", "ValueError", "ValueError")
            check("refusals generate nothing", (MESH_CALLS, RIG_CALLS), ([], []))

            print("[5] routes")
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from app.core import sessions, users
            from app.routes.characters import router
            tokens = {}
            for role in (users.ROLE_ADMIN, users.ROLE_USER):
                uid = users.create_user("demo-" + role, "temporary-smoke-password", role,
                                        allowed_characters=["Demo", "DemoFox", "DemoBare"])
                tokens[role] = sessions.create_session(uid)
            app = FastAPI()
            app.include_router(router)
            base_bytes = model.read_bytes()
            outfit_bytes = (model_dir / f"{osig}.glb").read_bytes()
            url = base_body.base_info("Demo")["model"]["url"]
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])
                r = client.get(f"/characters/Demo/model3d/file?signature={bsig}")
                check("serve base", (r.status_code, r.content == base_bytes), (200, True))
                r = client.get(f"/characters/Demo/model3d/file?signature={osig}")
                check("serve outfit", (r.status_code, r.content == outfit_bytes), (200, True))
                check("arbitrary signature", client.get(
                    "/characters/Demo/model3d/file?signature=deadbeef0000").status_code, 404)
                check("foreign base signature", client.get(
                    "/characters/Demo/model3d/file?signature=base00000000").status_code, 404)
                r = client.get(url)
                check("info url serves base", (r.status_code, r.content == base_bytes), (200, True))
                clear()
                r = client.post("/characters/Demo/base-body/model", json={})
                check("model started", (r.status_code, r.json()), (202, {"started": True}))
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and (
                        "Demo" in model3d._generating
                        or base_body.base_info("Demo")["model"]["status"] == "running"):
                    time.sleep(0.05)
                check("worker finished cached", (MESH_CALLS, base_body.base_info("Demo")["model"]["status"]),
                      ([], "ready"))
                check("animal model", client.post("/characters/DemoFox/base-body/model", json={}).status_code, 400)
                check("no base images", client.post("/characters/DemoBare/base-body/model",
                                                    json={}).status_code, 409)
                client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
                check("player base file", client.get(
                    f"/characters/Demo/model3d/file?signature={bsig}").status_code, 403)
                check("player model POST", client.post("/characters/Demo/base-body/model",
                                                       json={}).status_code, 403)
        finally:
            for (module, attr), value in originals.items():
                setattr(module, attr, value)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
