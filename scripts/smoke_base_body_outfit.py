#!/usr/bin/env python3
"""Base body: outfit = dressed edits + retextured base (Task 6).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_outfit.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no image backend, no Blender, no server process.

Stubs:
  * ``expression_regen.render_character_image`` — a recorder that writes an
    8x8 PNG whose colour is ``colour_of(<output stem name>)`` (md5 of the
    stem, first three bytes) plus the sidecar render_character_image would
    write (equipped pieces/items, ``mesh_variant`` of the mesh-input
    profile, ``sidecar_extra``);
  * ``refine.apply_script`` (recorder, bytes unchanged),
    ``model3d._auto_retexture`` / ``_attach_measurement`` (no-ops),
    ``model3d.request_lod`` (recorder), the extension declarations
    (``rig_groups_for`` / ``resolved_extension_groups``: by default ONE group
    ``jiggle`` op jiggle — the base's own state; scenario [8] adds an
    ``attached_part`` group ``part``).
  * The worker is a REAL subprocess run by ``body_retexture.retexture``: a
    fake repo ``<tmp>/worker`` (``.venv/bin/python`` -> this interpreter,
    ``body_core/__main__.py``). Per call it records argv and copies of the
    ``--glb`` input and every ``--view`` file into ``<tmp>/calls/<n>/``;
    mode file ``<tmp>/worker_mode``: ``ok`` (default) paints a 16x16 atlas of
    the dressed FRONT image's pixel (4, 4) into the input GLB
    (``base_body.replace_base_color``) as ``--out``, writes ``--atlas`` and
    the proof ``{"garment_share_visible": 0.42, "filled_share": 0.07,
    "rgb": [r, g, b]}``; ``refuse`` prints "front view does not match the
    registration (shift 9.1 % > 6 %)" on stderr, exits 3; ``slow`` waits
    for ``<tmp>/release`` (and writes ``<tmp>/started``) before ``ok``.

Fixture GLBs (``make_glb``): one triangle (POSITION accessor in bufferView
0, 36 bytes = 9 floats seed..seed+8) + one embedded 8x8 PNG base colour
(bufferView 1). The delivery validator rejects textures under 8 px
(``model_validate.MIN_TEXTURE_DIM``), so the fixture images are 8x8 and the
atlas 16x16 rather than the 2x2/4x4 the brief sketched.
  rigged base  model3d/<bsig>.glb: seed 1.0, image RIG (8x8 (10,20,30)),
               52 Mixamo joints + skin; sidecar {base: true, rig: mixamo,
               signature: bsig, blender {steps [normalize, limb_weights]},
               extension_rig = the applied state of [jiggle]};
  prerig       model3d/prerig/<bsig>.glb = the rigged bytes;
  unrigged     model3d/unrigged/<bsig>.glb: seed 5.0, image UNRIG (8x8
               (90,90,90)), no rig.
Base images: tpose[_back|_left|_right]_<bsig>.png, RGBA 8x8 transparent
with pixel (4, 4) = BASE_PX[view], sidecar base_signature = bsig.

Characters (template human-roleplay — it has the outfit system):
``Demo`` (human, profile image, on the pipeline), ``DemoOld``
(human, NOT on the pipeline), ``DemoNoModel`` (on the pipeline, base images,
no base model). Outfit piece ``dress`` (slot top, prompt_fragment
"a fitted red cotton dress with white sneakers"), piece ``scarf`` (slot neck,
"a green wool scarf").

Expected, derived by hand from the brief:

[1] replace_base_color / base_color_image on the fixture: the result's
    nodes, skins, meshes, accessors, materials, textures JSON equal the
    input's; the accessor bytes equal the input's; the image bytes are the
    new PNG; replacing with JPEG bytes sets mimeType image/jpeg; an
    EXT_texture_webp texture gets WebP bytes (RIFF....WEBP) in its WebP
    source AND the new image in its PNG fallback; two materials with two
    different images -> ValueError.
[2] dress_prompt(Demo, "front", pieces {top: dress}):
    prompt = DRESS_KEEP + " Only change their clothing: they now wear a
    fitted red cotton dress with white sneakers."; negative = style words +
    "loose clothing, baggy, skirt, jacket, socks, hair" (dress and shoes are
    named by the outfit: "dress", "sneakers"). Undressed -> ValueError.
    back/left/right: the same text opened by the view sentence VIEW[v]
    (wording of the e2e fix F1, written out in VIEW below) and a blank:
    back "This is a back view seen directly from behind, the figure faces
    away from the camera; keep it a back view, do not turn the figure toward
    the camera. Keep the image exactly as it is: …"; left/right "This is a
    strict left|right side profile view, the whole body in profile facing
    the left|right edge of the frame; keep it a side profile view, do not
    turn the figure toward the camera. Keep …". Same negative.
[3] Chain (Demo on the pipeline, wearing dress): _run_generation(Demo,
    "tpose") (the debounce timer body) -> four render calls, one per view
    in BASE_VIEWS order: reference_image name = tpose[_<v>]_<bsig>.png (the
    base view, on grey: pixel (0,0) = (128,128,128), pixel (4,4) =
    BASE_PX[v]); bare_prompt starts with VIEW[v] + " " (front: nothing) +
    "Keep the image exactly as it is" and contains the dress fragment; occasion "tpose_view"; use case tpose /
    tpose_back / tpose_side / tpose_side; character_loras True; sidecar_extra
    {base_signature: bsig, dressed: true, base_image_sha256: sha256 of that
    base view file}; extra_negative = [2]'s negative;
    back_view only for back. Then the auto hook (auto_generate is OFF)
    starts the model: one worker call whose --glb has the UNRIGGED accessor
    bytes and the RIGGED image; four --view pairs whose dressed files equal
    the dressed refs and registration files equal the base images. The
    published model3d/<osig>.glb: nodes/skins/accessors JSON = the rigged
    base's, accessor bytes = the rigged base's (seed 1.0), image = the 16x16
    atlas of colour_of("tpose_<osig>"); sidecar base_signature bsig,
    base_model_sha256 = sha256(rigged), retexture_proof = the fake proof, source "base_body", pieces {top:
    dress}; prerig/<osig>.glb image = the atlas; apply_script never called
    (the copied [jiggle] state is current -> no-op); request_lod once for
    <osig>.glb. base_info(Demo)["outfit"]: signature osig, status "ready",
    proof the fake proof.
[4] Base changes (new profile image -> bsig2 != bsig): find_model3d(Demo,
    osig) None, with include_stale the path; find_model3d_serving ->
    (path, "stale"); outfit status "stale", error "Built on an older base
    body", stale_reason "older_base" (the sidecar names a base signature). A tpose pass now finds no base images for bsig2: no render, the
    outfit status "failed" with BASE_IMAGES_MISSING, no model run. Profile
    image back -> bsig again, a pass (all cached) clears it -> "ready".
[4b] The base model regenerated under the SAME signature (other bytes in
    model3d/<bsig>.glb): find_model3d(Demo, osig) None, status "stale"; the
    original bytes back -> current again. A base view re-rendered (other
    bytes in tpose_<bsig>.png): dressed_image(front) None; restored -> the
    dressed front again.
[5] Worker refuses (mode refuse), forced rebuild: result ok False, error
    contains "does not match the registration"; <osig>.glb bytes unchanged;
    outfit status "failed" with that text. worker_dir "" -> error "Body
    retexture worker not configured", file unchanged.
[6] Outfit changes while a run is running (mode slow): a forced run for
    osig starts and waits in the worker; Demo then puts on the scarf (sig2),
    its tpose pass renders four new edits and the hook finds the run busy
    (follow-up marked). Released: osig's model carries colour_of(
    "tpose_<osig>"), the follow-up builds <sig2>.glb with colour_of(
    "tpose_<sig2>") — two models, each with its own atlas.
[7] Undressed (nothing worn, osig0): the tpose pass copies the four base
    images (no render call; bytes equal; sidecar dressed false,
    base_signature bsig); the model run calls NO worker; <osig0>.glb image =
    the RIGGED image, retexture_proof null, base_signature bsig.
[8] Parts for this outfit (declarations [part attached_part, jiggle]):
    forced osig rebuild -> apply_script batches attached_part [part] then
    extension_bones [jiggle] (rebuilt once from the prerig copy, never on top
    of the base's bones), and the published image is still osig's atlas.
[9] DemoNoModel: model run -> ok False, error BASE_MODEL_MISSING, outfit
    status failed.
[10] Not on the pipeline (DemoOld): its tpose pass renders with
    prompt_prefix = get_tpose_prompt(), occasion "tpose", no bare_prompt,
    no reference_image; the hook with auto_generate off starts nothing; with
    auto_generate on it calls trigger_generation(prefer_cheapest=True); a
    stored model without base_signature is found by find_model3d (no stale
    rule off the pipeline). Switched ONTO the pipeline, that model is
    "stale" with error "Built before the base body pipeline" and
    stale_reason "before_pipeline" (its sidecar has no base_signature).
[11] View guard in the model run (Demo wearing dress, forced rebuilds;
    ``base_body.view_guard`` replaced by a script — the measurement itself
    is scripts/smoke_base_body_view_guard.py). The stub renders are opaque,
    so in [3]..[10] the real guard skips every view (no matte).
    (a) back fails once, left fails twice: two re-renders, in BASE_VIEWS
        order tpose_back_<osig> then tpose_left_<osig> (each once); the
        worker gets views front, back, right; result ok; sidecar view_guard:
        back ok + rerendered + first.ok False, left ok False + rerendered,
        front/right ok without "rerendered"; view_warnings = ["left view:
        the dressed image does not keep its view (its head looks most like
        the front base view); left out of the outfit model"]; outfit_info
        status ready, warnings = that list.
    (b) front fails twice: one re-render (tpose_<osig>); result ok False,
        error starts "front view: the dressed image does not keep its view";
        no worker call; model bytes unchanged; status failed.
"""
import hashlib
import io
import json
import os
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
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {repr(got)[:160]}" + ("" if ok else f" — expected {repr(want)[:400]}"))
    if not ok:
        FAILS.append(label)


def png(rgb, size=8, mode="RGB") -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new(mode, (size, size), rgb).save(out, "PNG")
    return out.getvalue()


def colour_of(stem: str):
    digest = hashlib.md5(stem.encode()).digest()
    return (digest[0], digest[1], digest[2])


def pixel(data: bytes, xy=(4, 4)):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGB").getpixel(xy)


def make_glb(seed: float, image: bytes, *, rig: bool = False, mime: str = "image/png") -> bytes:
    from app.core.rig_contract import BASE_JOINT_NAMES
    positions = struct.pack("<9f", *[seed + i for i in range(9)])
    doc = {"asset": {"version": "2.0"},
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                          "min": [seed, seed + 1, seed + 2], "max": [seed + 6, seed + 7, seed + 8]}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                           {"buffer": 0, "byteOffset": 36, "byteLength": len(image)}],
           "images": [{"bufferView": 1, "mimeType": mime}], "textures": [{"source": 0}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    if rig:
        doc["nodes"] = [{"name": n} for n in BASE_JOINT_NAMES]
        doc["skins"] = [{"joints": list(range(len(BASE_JOINT_NAMES)))}]
    return pack(doc, positions + image)


def pack(doc, binary: bytes) -> bytes:
    binary = binary + b"\0" * (-len(binary) % 4)
    doc["buffers"] = [{"byteLength": len(binary)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = (struct.pack("<II", len(raw), 0x4e4f534a) + raw
            + struct.pack("<II", len(binary), 0x004e4942) + binary)
    return b"glTF" + struct.pack("<II", 2, len(body) + 12) + body


def parts(glb: bytes):
    """(gltf json, accessor bytes, base-colour image bytes)."""
    from app.core.base_body import base_color_image
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf, binary = parsed["gltf"], parsed["bin"]
    view = gltf["bufferViews"][gltf["accessors"][0]["bufferView"]]
    start = view.get("byteOffset", 0)
    return gltf, bytes(binary[start:start + view["byteLength"]]), base_color_image(glb)[0]


WORKER = r'''
import json, os, shutil, sys, time
from pathlib import Path
ROOT, TMP = {root!r}, Path({tmp!r})
sys.path[:0] = [ROOT, *{site!r}]
a = sys.argv[1:]
calls = TMP / "calls"
calls.mkdir(exist_ok=True)
call = calls / str(len(list(calls.iterdir())))
call.mkdir()
glb = a[a.index("--glb") + 1]
shutil.copyfile(glb, call / "in.glb")
views = {{}}
for i, arg in enumerate(a):
    if arg == "--view":
        name, files = a[i + 1].split("=", 1)
        dressed, registration = files.split(",")
        shutil.copyfile(dressed, call / f"{{name}}_dressed.png")
        shutil.copyfile(registration, call / f"{{name}}_registration.png")
        views[name] = [os.path.basename(dressed), os.path.basename(registration)]
(call / "argv.json").write_text(json.dumps({{"argv": a, "views": views}}))
mode = (TMP / "worker_mode").read_text().strip() if (TMP / "worker_mode").exists() else "ok"
if mode == "refuse":
    sys.stderr.write("loading views\nfront view does not match the registration (shift 9.1 % > 6 %)\n")
    sys.exit(3)
if mode == "slow":
    (TMP / "started").write_text("1")
    deadline = time.time() + 30
    while not (TMP / "release").exists() and time.time() < deadline:
        time.sleep(0.05)
import io
from PIL import Image
with Image.open(call / "front_dressed.png") as im:
    rgb = im.convert("RGB").getpixel((4, 4))
buf = io.BytesIO()
Image.new("RGB", (16, 16), rgb).save(buf, "PNG")
from app.core.base_body import replace_base_color
out = replace_base_color(Path(glb).read_bytes(), buf.getvalue(), "image/png")
Path(a[a.index("--out") + 1]).write_bytes(out)
Path(a[a.index("--atlas") + 1]).write_bytes(buf.getvalue())
Path(a[a.index("--proof") + 1]).write_text(json.dumps(
    {{"garment_share_visible": 0.42, "filled_share": 0.07, "rgb": list(rgb)}}))
'''

PROOF_KEYS = {"garment_share_visible": 0.42, "filled_share": 0.07}
RENDERS, SCRIPT_CALLS, LOD_CALLS, TRIGGERS = [], [], [], []
GROUPS = {"default": [{"id": "jiggle", "op": "jiggle", "params": {}, "chains": [], "depends_on": ""}]}
VIEW = {
    "back": ("This is a back view seen directly from behind, the figure faces away from the camera; keep it a "
             "back view, do not turn the figure toward the camera."),
    "left": ("This is a strict left side profile view, the whole body in profile facing the left edge of the "
             "frame; keep it a side profile view, do not turn the figure toward the camera."),
    "right": ("This is a strict right side profile view, the whole body in profile facing the right edge of the "
              "frame; keep it a side profile view, do not turn the figure toward the camera."),
}
BASE_PX = {"front": (200, 10, 10), "back": (10, 200, 10), "left": (10, 10, 200), "right": (200, 200, 10)}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-outfit-") as tmp:
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

        from app.core import base_body, expression_regen, extension_rig, glb_delivery, model3d, model_refs
        from app.blender import refine
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)

        # --- fake worker ------------------------------------------------------
        worker = root / "worker"
        (worker / ".venv" / "bin").mkdir(parents=True)
        (worker / ".venv" / "bin" / "python").symlink_to(Path(sys.executable).resolve())
        (worker / "body_core").mkdir()
        (worker / "body_core" / "__init__.py").write_text("")
        import site
        # The symlinked interpreter starts outside this venv: hand the fake
        # this venv's site-packages (PIL) explicitly.
        (worker / "body_core" / "__main__.py").write_text(
            WORKER.format(root=str(ROOT), tmp=str(root), site=site.getsitepackages()))
        config._CONFIG["body_retexture"] = {"worker_dir": str(worker), "timeout_seconds": 60}
        mode = root / "worker_mode"

        def calls():
            d = root / "calls"
            return sorted((p for p in d.iterdir()), key=lambda p: int(p.name)) if d.is_dir() else []

        # --- [1] GLB helpers ----------------------------------------------------
        print("[1] replace_base_color")
        RIG = png((10, 20, 30))
        UNRIG = png((90, 90, 90))
        rigged = make_glb(1.0, RIG, rig=True)
        new = png((1, 2, 3), 16)
        out = base_body.replace_base_color(rigged, new, "image/png")
        g_in, acc_in, img_in = parts(rigged)
        g_out, acc_out, img_out = parts(out)
        check("structure unchanged", {k: g_out.get(k) for k in ("nodes", "skins", "meshes", "accessors",
                                                                 "materials", "textures")},
              {k: g_in.get(k) for k in ("nodes", "skins", "meshes", "accessors", "materials", "textures")})
        check("geometry bytes unchanged", acc_out, acc_in)
        check("image replaced", (img_in == RIG, img_out == new), (True, True))
        jpeg = io.BytesIO()
        from PIL import Image
        Image.new("RGB", (16, 16), (5, 6, 7)).save(jpeg, "JPEG")
        out_j = base_body.replace_base_color(rigged, jpeg.getvalue(), "image/jpeg")
        check("jpeg mime", base_body.base_color_image(out_j)[1], "image/jpeg")
        webp_img = io.BytesIO()
        Image.new("RGB", (16, 16), (9, 9, 9)).save(webp_img, "WEBP", lossless=True)
        positions = struct.pack("<9f", *range(9))
        webp_doc = {"asset": {"version": "2.0"}, "extensionsUsed": ["EXT_texture_webp"],
                    "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
                    "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                                    {"buffer": 0, "byteOffset": 36, "byteLength": len(webp_img.getvalue())},
                                    {"buffer": 0, "byteOffset": 36 + len(webp_img.getvalue()),
                                     "byteLength": len(RIG)}],
                    "images": [{"bufferView": 1, "mimeType": "image/webp"},
                               {"bufferView": 2, "mimeType": "image/png"}],
                    "textures": [{"source": 1, "extensions": {"EXT_texture_webp": {"source": 0}}}],
                    "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
        webp_glb = pack(webp_doc, positions + webp_img.getvalue() + RIG)
        out_w = base_body.replace_base_color(webp_glb, new, "image/png")
        from app.core.model_validate import parse_glb
        pw = parse_glb(out_w)
        vw = pw["gltf"]["bufferViews"]
        webp_bytes = pw["bin"][vw[1]["byteOffset"]:vw[1]["byteOffset"] + vw[1]["byteLength"]]
        png_bytes = pw["bin"][vw[2]["byteOffset"]:vw[2]["byteOffset"] + vw[2]["byteLength"]]
        check("webp source re-encoded", (webp_bytes[:4], webp_bytes[8:12], pixel(webp_bytes)),
              (b"RIFF", b"WEBP", (1, 2, 3)))
        check("png fallback replaced", png_bytes, new)
        two = json.loads(json.dumps(webp_doc))
        two.pop("extensionsUsed")
        two["textures"] = [{"source": 1}, {"source": 1}]
        two["images"][0] = {"bufferView": 1, "mimeType": "image/png"}
        two["textures"][0] = {"source": 0}
        two["materials"].append({"pbrMetallicRoughness": {"baseColorTexture": {"index": 1}}})
        try:
            base_body.replace_base_color(pack(two, positions + RIG + RIG), new, "image/png")
            check("two base-colour images refused", "no error", "ValueError")
        except ValueError:
            check("two base-colour images refused", "ValueError", "ValueError")

        # --- world fixtures -------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name in ("Demo", "DemoOld", "DemoNoModel"):
            check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
            images = get_character_images_dir(name)
            images.mkdir(parents=True, exist_ok=True)
            (images / f"{name}_1.png").write_bytes(png((50, 60, 70)))
            (images / f"{name}_2.png").write_bytes(png((50, 60, 71), 9))
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"profile image {name}", save_character_profile(name, stored), True)
        for name in ("Demo", "DemoNoModel"):
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)
        dress = inventory.add_item(name="dress", category="outfit_piece",
                                   prompt_fragment="a fitted red cotton dress with white sneakers",
                                   outfit_piece={"slots": ["top"], "covers": [], "outfit_types": ["casual"]})["id"]
        scarf = inventory.add_item(name="scarf", category="outfit_piece", prompt_fragment="a green wool scarf",
                                   outfit_piece={"slots": ["neck"], "covers": [], "outfit_types": ["casual"]})["id"]
        for name in ("Demo", "DemoOld"):
            for item in (dress, scarf):
                check(f"inventory {name} {item}", inventory.add_to_inventory(name, item), True)

        def base_images(name, bsig):
            refs = get_character_dir(name) / "model_refs"
            refs.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            for v in base_body.BASE_VIEWS:
                stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
                im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
                im.putpixel((4, 4), BASE_PX[v] + (255,))
                im.save(refs / f"{stem}.png")
                (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))

        jiggle_fp = extension_rig.extension_rig_fingerprint(GROUPS["default"], {})
        bsig = base_body.base_signature("Demo")
        base_images("Demo", bsig)
        base_images("DemoNoModel", base_body.base_signature("DemoNoModel"))
        model_dir = get_character_dir("Demo") / "model3d"
        for sub in ("unrigged", "prerig"):
            (model_dir / sub).mkdir(parents=True, exist_ok=True)
        (model_dir / f"{bsig}.glb").write_bytes(rigged)
        (model_dir / f"{bsig}.json").write_text(json.dumps({
            "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated",
            "blender": {"steps": ["normalize", "limb_weights"]},
            "extension_rig": {"fingerprint": jiggle_fp, "groups": ["jiggle"], "group_ops": {"jiggle": "jiggle"},
                              "status": "applied", "attempted": True, "has_applied": True, "metrics": {}}}))
        (model_dir / "prerig" / f"{bsig}.glb").write_bytes(rigged)
        (model_dir / "prerig" / f"{bsig}.json").write_text(json.dumps({
            "rig": "mixamo", "blender": {"steps": ["normalize", "limb_weights"]}}))
        unrigged = make_glb(5.0, UNRIG)
        (model_dir / "unrigged" / f"{bsig}.glb").write_bytes(unrigged)
        refs = get_character_dir("Demo") / "model_refs"

        # --- stubs ----------------------------------------------------------------
        originals = {
            (expression_regen, "render_character_image"): expression_regen.render_character_image,
            (refine, "apply_script"): refine.apply_script,
            (model3d, "_auto_retexture"): model3d._auto_retexture,
            (model3d, "_attach_measurement"): model3d._attach_measurement,
            (model3d, "request_lod"): model3d.request_lod,
            (extension_rig, "rig_groups_for"): extension_rig.rig_groups_for,
            (extension_rig, "resolved_extension_groups"): extension_rig.resolved_extension_groups,
            (glb_delivery, "delivery_path"): glb_delivery.delivery_path,
        }

        def render(character_name, *, output_stem, equipped_pieces, equipped_items, **kw):
            from PIL import Image
            ref = kw.get("reference_image")
            entry = {"character": character_name, "stem": Path(output_stem).name, **kw,
                     "reference_name": ref.name if ref else None,
                     "reference_px": (pixel(Path(ref).read_bytes(), (0, 0)), pixel(Path(ref).read_bytes()))
                     if ref else None}
            RENDERS.append(entry)
            target = Path(str(output_stem) + ".png")
            Image.new("RGB", (8, 8), colour_of(target.stem)).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            meta = {"equipped_pieces": equipped_pieces or {}, "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        def apply_script(path, operation, params, **kw):
            SCRIPT_CALLS.append((operation, [g["id"] for g in params.get("groups", [])]))
            return {"applied": True, "data": {}}

        expression_regen.render_character_image = render
        refine.apply_script = apply_script
        model3d._auto_retexture = lambda *a, **k: None
        model3d._attach_measurement = lambda *a, **k: None
        model3d.request_lod = lambda name, path: LOD_CALLS.append(path.name) or False
        extension_rig.rig_groups_for = lambda *a, **k: [dict(g) for g in GROUPS["default"]]
        extension_rig.resolved_extension_groups = lambda *a, **k: [
            {**g, "enabled": True, "flip": False} for g in GROUPS["default"]]
        glb_delivery.delivery_path = lambda path, **kw: path

        def wait_idle(name, timeout=30.0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and (name in model3d._generating
                                                   or name in model3d._outfit_followups):
                time.sleep(0.05)
            check(f"{name} generation finished", name in model3d._generating, False)

        def equip(name, item):
            check(f"equip {item}", inventory.equip_piece(name, item, source="smoke")["status"], "ok")
            model_refs._cancel_timers(name, model_refs.REF_KINDS)

        try:
            # --- [2] dress prompt ---------------------------------------------------
            print("[2] dress_prompt")
            prompt, negative = base_body.dress_prompt("Demo", "front", pieces={"top": dress}, items=[])
            check("prompt", prompt, base_body.DRESS_KEEP + " Only change their clothing: they now wear a "
                  "fitted red cotton dress with white sneakers.")
            check("negative", negative, base_body.DRESS_STYLE_NEGATIVE
                  + ", loose clothing, baggy, skirt, jacket, socks, hair")
            for v in ("back", "left", "right"):
                vp, vn = base_body.dress_prompt("Demo", v, pieces={"top": dress}, items=[])
                check(f"{v} prompt", vp, VIEW[v] + " " + prompt)
                check(f"{v} negative", vn, negative)
            try:
                base_body.dress_prompt("Demo", "front", pieces={}, items=[])
                check("undressed refused", "no error", "ValueError")
            except ValueError:
                check("undressed refused", "ValueError", "ValueError")

            # --- [3] the chain ------------------------------------------------------
            print("[3] outfit change -> dressed edits -> outfit model")
            check("auto_generate off", model3d.get_model3d_options("Demo")["auto_generate"], False)
            equip("Demo", dress)
            osig = model_refs.current_outfit_state("Demo")[2]
            model_refs._run_generation("Demo", "tpose")
            wait_idle("Demo")
            dressed_renders = [r for r in RENDERS if r["character"] == "Demo"]
            check("four edits", [r["stem"] for r in dressed_renders],
                  [f"tpose_{osig}", f"tpose_back_{osig}", f"tpose_left_{osig}", f"tpose_right_{osig}"])
            want_refs = [f"tpose_{bsig}.png", f"tpose_back_{bsig}.png", f"tpose_left_{bsig}.png",
                         f"tpose_right_{bsig}.png"]
            check("references = base views", [r["reference_name"] for r in dressed_renders], want_refs)
            check("references on grey", [r["reference_px"] for r in dressed_renders],
                  [((128, 128, 128), BASE_PX[v]) for v in base_body.BASE_VIEWS])
            check("prompts", [(r["bare_prompt"].startswith(
                (VIEW[v] + " " if v in VIEW else "") + "Keep the image exactly as it is"),
                               "a fitted red cotton dress with white sneakers" in r["bare_prompt"])
                              for v, r in zip(base_body.BASE_VIEWS, dressed_renders)], [(True, True)] * 4)
            check("occasions", [r["occasion"] for r in dressed_renders], ["tpose_view"] * 4)
            check("use cases", [r["image_use_case"] for r in dressed_renders],
                  ["tpose", "tpose_back", "tpose_side", "tpose_side"])
            check("character loras", [r["character_loras"] for r in dressed_renders], [True] * 4)
            check("sidecar extra", [r["sidecar_extra"] for r in dressed_renders],
                  [{"base_signature": bsig, "dressed": True,
                    "base_image_sha256": hashlib.sha256((refs / name).read_bytes()).hexdigest()}
                   for name in want_refs])
            check("extra negative", {r["extra_negative"] for r in dressed_renders}, {negative})
            check("back view flag", [r["back_view"] for r in dressed_renders], [False, True, False, False])
            runs = calls()
            check("one worker call", len(runs), 1)
            first = runs[0] if runs else None
            if first:
                _g, acc, img = parts((first / "in.glb").read_bytes())
                check("worker geometry = unrigged", acc, parts(unrigged)[1])
                check("worker image = rigged image", img, RIG)
                argv = json.loads((first / "argv.json").read_text())
                check("worker views", sorted(argv["views"]), sorted(base_body.BASE_VIEWS))
                for v in base_body.BASE_VIEWS:
                    kind = "tpose" if v == "front" else f"tpose_{v}"
                    check(f"{v} dressed input", (first / f"{v}_dressed.png").read_bytes(),
                          (refs / f"{kind}_{osig}.png").read_bytes())
                    check(f"{v} registration input", (first / f"{v}_registration.png").read_bytes(),
                          (refs / f"{kind}_{bsig}.png").read_bytes())
            model = model_dir / f"{osig}.glb"
            check("outfit model published", model.is_file(), True)
            if model.is_file():
                g_m, acc_m, img_m = parts(model.read_bytes())
                g_r = parts(rigged)[0]
                check("rig JSON unchanged", {k: g_m.get(k) for k in ("nodes", "skins", "accessors", "meshes")},
                      {k: g_r.get(k) for k in ("nodes", "skins", "accessors", "meshes")})
                check("rigged geometry", acc_m, parts(rigged)[1])
                check("atlas image", (pixel(img_m), len(img_m) > 0), (colour_of(f"tpose_{osig}"), True))
                meta = model3d._read_sidecar(model)
                check("sidecar", {k: meta.get(k) for k in ("base_signature", "base_model_sha256", "source",
                                                           "pieces", "base")},
                      {"base_signature": bsig, "base_model_sha256": hashlib.sha256(rigged).hexdigest(),
                       "source": "base_body", "pieces": {"top": dress}, "base": None})
                check("proof", {k: (meta.get("retexture_proof") or {}).get(k) for k in PROOF_KEYS}, PROOF_KEYS)
                check("prerig carries the atlas",
                      pixel(base_body.base_color_image((model_dir / "prerig" / f"{osig}.glb").read_bytes())[0]),
                      colour_of(f"tpose_{osig}"))
            check("extension rig no-op", SCRIPT_CALLS, [])
            check("lod requested", LOD_CALLS, [f"{osig}.glb"])
            info = base_body.base_info("Demo")["outfit"]
            check("outfit info", {k: info.get(k) for k in ("signature", "status", "error")},
                  {"signature": osig, "status": "ready", "error": ""})
            check("outfit proof", {k: (info.get("proof") or {}).get(k) for k in PROOF_KEYS}, PROOF_KEYS)
            check("find_model3d", model3d.find_model3d("Demo", osig), model)
            check("serving exact", model3d.find_model3d_serving("Demo"), (model, "exact"))

            # --- [4] the base changes ------------------------------------------------
            print("[4] base changes -> outfit model stale")
            stored = get_character_profile("Demo")
            stored["profile_image"] = "Demo_2.png"
            check("new profile image", save_character_profile("Demo", stored), True)
            bsig2 = base_body.base_signature("Demo")
            check("base signature changed", bsig2 != bsig, True)
            check("stale counts as missing", model3d.find_model3d("Demo", osig), None)
            check("include_stale", model3d.find_model3d("Demo", osig, include_stale=True), model)
            check("serving stale", model3d.find_model3d_serving("Demo"), (model, "stale"))
            info = base_body.outfit_info("Demo")
            check("status stale", (info["status"], info["error"], info["stale_reason"]),
                  ("stale", "Built on an older base body", "older_base"))
            n_renders, n_calls = len(RENDERS), len(calls())
            model_refs._run_generation("Demo", "tpose")
            wait_idle("Demo")
            check("no render without base images", len(RENDERS), n_renders)
            check("no worker run", len(calls()), n_calls)
            info = base_body.outfit_info("Demo")
            check("status base images missing", (info["status"], info["error"]),
                  ("failed", base_body.BASE_IMAGES_MISSING))
            stored = get_character_profile("Demo")
            stored["profile_image"] = "Demo_1.png"
            check("profile image back", save_character_profile("Demo", stored), True)
            check("base signature back", base_body.base_signature("Demo"), bsig)
            model_refs._run_generation("Demo", "tpose")
            wait_idle("Demo")
            check("cached pass renders nothing", len(RENDERS), n_renders)
            check("status ready again", base_body.outfit_info("Demo")["status"], "ready")

            # --- [4b] base regenerated under the same signature -------------------
            print("[4b] base regenerated under the same signature")
            base_glb = model_dir / f"{bsig}.glb"
            base_glb.write_bytes(make_glb(1.0, png((11, 20, 30)), rig=True))
            check("regenerated base model: outfit stale", model3d.find_model3d("Demo", osig), None)
            check("regenerated base model: status", base_body.outfit_info("Demo")["status"], "stale")
            base_glb.write_bytes(rigged)
            check("same base content again: current", model3d.find_model3d("Demo", osig), model)
            front_base = refs / f"tpose_{bsig}.png"
            saved = front_base.read_bytes()
            front_base.write_bytes(png((1, 1, 1)))
            check("re-rendered base view: dressed front not current",
                  base_body.dressed_image("Demo", "front", osig, bsig), None)
            front_base.write_bytes(saved)
            check("base view restored: dressed front current",
                  base_body.dressed_image("Demo", "front", osig, bsig), refs / f"tpose_{osig}.png")

            # --- [5] worker refuses / not configured -------------------------------
            print("[5] worker refuses")
            before = model.read_bytes()
            mode.write_text("refuse")
            result = model3d.generate_for_current_outfit("Demo", force=True)
            check("refused result", (result.get("ok"), "does not match the registration" in (result.get("error") or "")),
                  (False, True))
            check("model untouched", model.read_bytes() == before, True)
            info = base_body.outfit_info("Demo")
            check("status refused", (info["status"], "does not match the registration" in info["error"]),
                  ("failed", True))
            config._CONFIG["body_retexture"]["worker_dir"] = ""
            n_calls = len(calls())
            result = model3d.generate_for_current_outfit("Demo", force=True)
            check("not configured", (result.get("ok"), result.get("error")),
                  (False, "Body retexture worker not configured"))
            check("not configured: no run, untouched", (len(calls()), model.read_bytes() == before),
                  (n_calls, True))
            config._CONFIG["body_retexture"]["worker_dir"] = str(worker)
            mode.write_text("ok")

            # --- [6] outfit changes during a run ------------------------------------
            print("[6] outfit changes while the retexture runs")
            mode.write_text("slow")
            (root / "started").unlink(missing_ok=True)
            (root / "release").unlink(missing_ok=True)
            check("forced run started", model3d.trigger_generation("Demo", force=True), True)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (root / "started").exists():
                time.sleep(0.05)
            check("worker waiting", (root / "started").exists(), True)
            mode.write_text("ok")
            equip("Demo", scarf)
            sig2 = model_refs.current_outfit_state("Demo")[2]
            check("new signature", sig2 != osig, True)
            model_refs._run_generation("Demo", "tpose")
            check("follow-up marked", "Demo" in model3d._outfit_followups, True)
            (root / "release").write_text("1")
            wait_idle("Demo")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (model_dir / f"{sig2}.glb").is_file():
                time.sleep(0.05)
            wait_idle("Demo")
            check("osig atlas", pixel(parts(model.read_bytes())[2]), colour_of(f"tpose_{osig}"))
            model2 = model_dir / f"{sig2}.glb"
            check("sig2 model built", model2.is_file(), True)
            if model2.is_file():
                check("sig2 atlas", pixel(parts(model2.read_bytes())[2]), colour_of(f"tpose_{sig2}"))
                check("sig2 sidecar", model3d._read_sidecar(model2).get("base_signature"), bsig)

            # --- [7] undressed -------------------------------------------------------
            print("[7] undressed combination")
            for item in (dress, scarf):
                check(f"unequip {item}", inventory.unequip_piece("Demo", item_id=item, source="smoke")["status"], "ok")
            model_refs._cancel_timers("Demo", model_refs.REF_KINDS)
            osig0 = model_refs.current_outfit_state("Demo")[2]
            n_renders, n_calls = len(RENDERS), len(calls())
            model_refs._run_generation("Demo", "tpose")
            wait_idle("Demo")
            check("no render for undressed", len(RENDERS), n_renders)
            for v in base_body.BASE_VIEWS:
                kind = "tpose" if v == "front" else f"tpose_{v}"
                copy = refs / f"{kind}_{osig0}.png"
                check(f"{v} copied", copy.is_file() and copy.read_bytes() == (refs / f"{kind}_{bsig}.png").read_bytes(),
                      True)
                side = json.loads(copy.with_suffix(".json").read_text()) if copy.is_file() else {}
                check(f"{v} copy sidecar", (side.get("dressed"), side.get("base_signature")), (False, bsig))
            check("no worker for undressed", len(calls()), n_calls)
            model0 = model_dir / f"{osig0}.glb"
            check("undressed model", model0.is_file(), True)
            if model0.is_file():
                meta0 = model3d._read_sidecar(model0)
                check("undressed image = rigged image", parts(model0.read_bytes())[2], RIG)
                check("undressed sidecar", (meta0.get("retexture_proof"), meta0.get("base_signature"),
                                            meta0.get("dressed")), (None, bsig, False))

            # --- [8] parts for this outfit ---------------------------------------
            print("[8] anatomy part declared for this outfit")
            equip("Demo", dress)
            GROUPS["default"] = [{"id": "part", "op": "attached_part", "params": {}, "chains": [], "depends_on": ""},
                                 {"id": "jiggle", "op": "jiggle", "params": {}, "chains": [], "depends_on": ""}]
            SCRIPT_CALLS.clear()
            result = model3d.generate_for_current_outfit("Demo", force=True)
            check("parts run ok", result.get("ok"), True)
            check("part batches", SCRIPT_CALLS, [("attached_part", ["part"]), ("extension_bones", ["jiggle"])])
            check("atlas kept through the rebuild", pixel(parts(model.read_bytes())[2]), colour_of(f"tpose_{osig}"))
            GROUPS["default"] = GROUPS["default"][1:]

            # --- [9] no base model ---------------------------------------------------
            print("[9] base model missing")
            equip_ok = inventory.add_to_inventory("DemoNoModel", dress)
            check("inventory DemoNoModel", equip_ok, True)
            equip("DemoNoModel", dress)
            model_refs._run_generation("DemoNoModel", "tpose")
            wait_idle("DemoNoModel")
            result = model3d.generate_for_current_outfit("DemoNoModel", force=True)
            check("no base model", (result.get("ok"), result.get("error")), (False, base_body.BASE_MODEL_MISSING))
            info = base_body.outfit_info("DemoNoModel")
            check("status no base model", (info["status"], info["error"]), ("failed", base_body.BASE_MODEL_MISSING))

            # --- [10] not on the pipeline --------------------------------------------
            print("[10] character off the pipeline keeps today's path")
            equip("DemoOld", dress)
            n_renders = len(RENDERS)
            real_trigger = model3d.trigger_generation
            model3d.trigger_generation = lambda name, **kw: TRIGGERS.append((name, kw)) or True
            try:
                model_refs.generate_model_ref_images("DemoOld", kinds=("tpose",))
                old = [r for r in RENDERS[n_renders:] if r["character"] == "DemoOld"]
                check("old path main render", [(r.get("prompt_prefix"), r.get("occasion"), r.get("bare_prompt"),
                                                r.get("reference_image")) for r in old[:1]],
                      [(model_refs.get_tpose_prompt(), "tpose", None, None)])
                check("auto off: nothing started", (model3d.maybe_auto_generate_for_outfit("DemoOld"), TRIGGERS),
                      (False, []))
                model3d.set_model3d_options("DemoOld", {"auto_generate": True})
                model3d.maybe_auto_generate_for_outfit("DemoOld")
                check("auto on: cheapest trigger", TRIGGERS, [("DemoOld", {"prefer_cheapest": True})])
            finally:
                model3d.trigger_generation = real_trigger
            old_dir = get_character_dir("DemoOld") / "model3d"
            old_sig = model_refs.current_outfit_state("DemoOld")[2]
            (old_dir / f"{old_sig}.glb").write_bytes(rigged)
            (old_dir / f"{old_sig}.json").write_text(json.dumps({"rig": "mixamo"}))
            check("no stale rule off the pipeline", model3d.find_model3d("DemoOld", old_sig),
                  old_dir / f"{old_sig}.glb")
            check("DemoOld onto the pipeline", base_body.set_pipeline("DemoOld", True), True)
            info = base_body.outfit_info("DemoOld")
            check("built before the pipeline", (info["status"], info["error"], info["stale_reason"]),
                  ("stale", "Built before the base body pipeline", "before_pipeline"))
            check("DemoOld off the pipeline", base_body.set_pipeline("DemoOld", False), True)

            # --- [11] view guard ------------------------------------------------------
            print("[11] view guard: re-render once, leave out, front fails the build")
            real_guard = base_body.view_guard
            fails = {}

            def scripted(view, dressed, bases):
                if fails.get(view, 0) > 0:
                    fails[view] -= 1
                    return {"ok": False, "scores": {"front": 0.9, view: 0.5}, "best": "front"}
                return {"ok": True, "scores": {view: 0.9}, "best": view}

            base_body.view_guard = scripted
            try:
                fails.update({"back": 1, "left": 2})
                n_renders, n_calls = len(RENDERS), len(calls())
                result = model3d.generate_for_current_outfit("Demo", force=True)
                check("guarded run ok", result.get("ok"), True)
                check("re-rendered once each", [r["stem"] for r in RENDERS[n_renders:]],
                      [f"tpose_back_{osig}", f"tpose_left_{osig}"])
                runs = calls()[n_calls:]
                check("one worker call", len(runs), 1)
                if runs:
                    views = json.loads((runs[0] / "argv.json").read_text())["views"]
                    check("left left out", sorted(views), ["back", "front", "right"])
                meta = model3d._read_sidecar(model)
                guard = meta.get("view_guard") or {}
                check("guard back", (guard.get("back", {}).get("ok"), guard.get("back", {}).get("rerendered"),
                                     (guard.get("back", {}).get("first") or {}).get("ok")), (True, True, False))
                check("guard left", (guard.get("left", {}).get("ok"), guard.get("left", {}).get("rerendered")),
                      (False, True))
                check("guard front/right", [(guard.get(v, {}).get("ok"), "rerendered" in guard.get(v, {}))
                                            for v in ("front", "right")], [(True, False)] * 2)
                warning = ("left view: the dressed image does not keep its view (its head looks most like the "
                           "front base view); left out of the outfit model")
                check("sidecar warnings", meta.get("view_warnings"), [warning])
                info = base_body.base_info("Demo")["outfit"]
                check("outfit info warnings", (info["status"], info["warnings"]), ("ready", [warning]))

                fails.clear()
                fails.update({"front": 2})
                before = model.read_bytes()
                n_renders, n_calls = len(RENDERS), len(calls())
                result = model3d.generate_for_current_outfit("Demo", force=True)
                check("front fails the build", (result.get("ok"), (result.get("error") or "").startswith(
                    "front view: the dressed image does not keep its view")), (False, True))
                check("front re-rendered once", [r["stem"] for r in RENDERS[n_renders:]], [f"tpose_{osig}"])
                check("no worker call", len(calls()), n_calls)
                check("model untouched", model.read_bytes() == before, True)
                check("status failed", base_body.outfit_info("Demo")["status"], "failed")
            finally:
                base_body.view_guard = real_guard
        finally:
            for (module, attr), value in originals.items():
                setattr(module, attr, value)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
