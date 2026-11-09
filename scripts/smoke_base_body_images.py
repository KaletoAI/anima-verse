#!/usr/bin/env python3
"""Base body: the four A-pose images, the pipeline switch and the routes (app/core/base_body.py).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_images.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no image backend, no server process, no GPU. The
expected values below are derived by hand from the brief and the code rules:

Fixtures: ``Demo`` (template human-default, profile image Demo_1.png,
``outfit_imagegen`` {loras: [char-lora 0.8], tpose_loras: [pose-lora 0.6]},
body slot ``marking.look`` = "slot-lora-x" — a ``lora_select`` attribute of
the fixture package ``fixture_lora`` (apply_to human-default, always
exposed: no covering), so the normal outfit path WOULD add it),
``DemoBare`` (human-default, NO profile image), ``DemoFail`` (human-default,
profile image; its front render fails), ``DemoFox`` (template animal-default,
feature ``humanoid: false``, profile image). ``bsig`` = base_signature(Demo).

[1] Recorder in place of ``expression_regen.render_character_image`` (writes an
    8x8 RGBA PNG, transparent but for one opaque pixel, to ``<stem>.png``).
    generate_base_images("Demo") makes 4 calls, in BASE_VIEWS order:
      front: occasion "base_front", image_use_case "base_front", reference_image None
             (the profile image is slotted by render_character_image's
             profile_only payload, as for every tpose render), stem
             model_refs/.handgate_<random>/attempt1/tpose_<bsig> (the hand
             gate's staging dir; the recorder's 8x8 image has no figure to
             measure, so attempt 1 passes and lands on model_refs/tpose_<bsig>);
      back:  occasion "base_view", use case "base_back"
             (base_body.BASE_USE_CASES — the base views' own use cases, the
             whole-body T-pose path keeps tpose*), back_view True, stem
             tpose_back_<bsig>,
             reference_image NAMED tpose_<bsig>.png (neutral_view_reference
             keeps the file name) but NOT the front file itself: a grey
             copy, whose transparent corner pixel reads (128, 128, 128);
      left/right: use case "base_side", stems tpose_left_<bsig> /
             tpose_right_<bsig>.
    Every call: bare_prompt/extra_negative = base_prompt(view) (prompt,
    negative), style_character = base_character(view) (the block for the
    style's {character} slot), NO negative_prompt (it would REPLACE the use-case negative),
    equipped {} / [], apply_state_modifiers False, size _tpose_size() =
    (1024, 1024) (no config override), sidecar_extra {"base_signature": bsig}.
    While the front renders, base_info status front.running is True.
    Afterwards find_ref_image(Demo, "tpose", bsig) is model_refs/tpose_<bsig>.png
    and find_ref_image(Demo, "tpose_left", bsig) the left file; the return
    value maps all 4 views to their paths; status: nothing running or failed.
    A second call without force renders nothing and returns {}.
    view="left", force=True renders ONLY left (1 call, reference = front name).
    view="back" without force (cached) renders nothing.
[2] Refusals: an unknown view, DemoFox (animal) and DemoBare (no profile
    image) raise ValueError without a render. DemoFail: front returns None ->
    result {"front": None}, no view render (they need the front), status
    front.failed True and back/left/right failed with error "front render
    failed"; a view of DemoFail then raises ValueError (no front).
[3] base_info(Demo): pipeline False, signature bsig, images = 4 URLs
    "/characters/Demo/base-body/images/<view>?v=<mtime_ns>", model None.
    set_pipeline(Demo, True) -> True, stored model_pipeline "base_body",
    base_info pipeline True; set_pipeline(Demo, False) -> True, the field is
    gone. set_pipeline(DemoFox, True) -> ValueError, profile unchanged.
[4] The real render_character_image with a FAKE image service (records the
    JSON payload, writes the "generated" file into the images dir) and a
    recording postprocess_outfit_image:
      front payload: prompt == base_prompt(front)[0] (bare), image_use_case
      "base_front", occasion "base_front", style_character ==
      base_character(front), negative_prompt_extra == BASE_NEGATIVE, no
      "negative_prompt" key, profile_only True, no reference_image_override,
      clothed False (no fabric clause in the use-case style);
      back payload: use case "base_back", occasion "base_view",
      style_character == base_character(back),
      reference_image_override ends with "/tpose_<bsig>.png";
      postprocess called with mesh_input=True for both (BiRefNet matte path —
      base_front/base_view are mesh-input occasions like tpose/tpose_view);
      the sidecar tpose_<bsig>.json records base_signature bsig, the bare
      prompt, mesh_variant (a mesh-input key) and equipped_pieces {}.
      LoRAs: the fixture is live (exposed_slot_loras(Demo) names
      slot-lora-x), yet every base payload carries exactly
      [{"name": "pose-lora", "strength": 0.6}] — tpose_loras replaces loras
      on the mesh-input occasions, as on today's tpose render; no slot LoRA;
      no "loras_explicit" (stored LoRAs go through the library gate's
      filter, not its hard assert). A bare_prompt render WITHOUT
      character_loras (occasion tpose, like the face view) carries no
      "loras" key and no "style_character" key — unchanged behaviour for
      other callers.
[5] Service: resolve_negative_prompt({"negative_prompt_extra": X}, UC) is
    "UC, X"; with an explicit negative N it is "N, X"; without extra it is UC.
    _parse_input keeps "negative_prompt_extra" and "style_character" (the
    whitelist; a payload without the key parses to None). For the base_front
    use case the merged negative starts with config._NEG_TPOSE (the same
    shipped negative as tpose) and ends with BASE_NEGATIVE.
[6] Routes (characters router on a bare FastAPI app, real sessions):
    player GET /characters/Demo/base-body -> 403; admin -> 200 with signature
    bsig; POST .../pipeline {enabled: true} for DemoFox -> 400 and the profile
    is unchanged; for Demo -> 200 {pipeline: true}; POST .../images
    {view: "left", force: true} -> 202 {started: true} and, once the worker
    is done, exactly one render (left); {view: "sideways"} -> 422; DemoFox
    images -> 400; DemoBare images -> 409; GET .../images/front -> 200 with
    the PNG; unknown character -> 404.
"""
import json
import os
import shutil
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


CALLS = []

FIXTURE = {
    "name": "fixture_lora",
    "apply_to": ["human-default"],
    "body_slots": [{
        "id": "marking",
        "attributes": {"look": {"type": "lora_select"}},
        "prompt": {"always": "a marking"},
    }],
}
POSE_LORA = {"name": "pose-lora", "strength": 0.6}


def recorder(character_name, *, output_stem, **kw):
    from app.core import base_body
    ref = kw.get("reference_image")
    corner = None
    if ref is not None:
        from PIL import Image
        with Image.open(ref) as im:
            corner = im.convert("RGB").getpixel((0, 0))
    view = {"tpose": "front"}.get(output_stem.name.split("_base")[0], output_stem.name.split("_")[1])
    status = base_body.base_info(character_name)["status"][view]
    CALLS.append({"name": character_name, "stem": output_stem, "ref": ref, "corner": corner,
                  "running": status["running"], **kw})
    if character_name == "DemoFail":
        return None
    path = output_stem.with_suffix(".png")
    tiny_png(path)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-images-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human,fixture_lora"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        (plugins / "fixture_lora").mkdir(parents=True)
        (plugins / "fixture_lora" / "plugin.yaml").write_text(json.dumps(FIXTURE))
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, model_refs
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)

        human = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name, template, image in (("Demo", "human-default", True), ("DemoBare", "human-default", False),
                                      ("DemoFail", "human-default", True), ("DemoFox", "animal-default", True)):
            check(f"create {name}", save_character_profile(name, dict(human, template=template), create_new=True),
                  True)
            if image:
                tiny_png(get_character_images_dir(name) / f"{name}_1.png")
                stored = get_character_profile(name)
                stored["profile_image"] = f"{name}_1.png"
                if name == "Demo":
                    stored["outfit_imagegen"] = {"loras": [{"name": "char-lora", "strength": 0.8}],
                                                 "tpose_loras": [POSE_LORA]}
                    stored.setdefault("body_slots", {})["marking"] = {"look": "slot-lora-x"}
                check(f"profile image {name}", save_character_profile(name, stored), True)

        real_render = expression_regen.render_character_image
        expression_regen.render_character_image = recorder
        refs = get_character_dir("Demo") / "model_refs"
        bsig = base_body.base_signature("Demo")
        try:
            print("[1] four views through the recorder")
            out = base_body.generate_base_images("Demo")
            check("call count", len(CALLS), 4)
            views = ["front", "back", "left", "right"]
            stems = [f"tpose_{bsig}", f"tpose_back_{bsig}", f"tpose_left_{bsig}", f"tpose_right_{bsig}"]
            check("stems", [c["stem"].name for c in CALLS], stems)
            check("front stem dir", (CALLS[0]["stem"].parent.name, CALLS[0]["stem"].parent.parent.parent,
                                     CALLS[0]["stem"].parent.parent.name.startswith(".handgate_")),
                  ("attempt1", refs, True))
            check("view stem dir", {c["stem"].parent for c in CALLS[1:]}, {refs})
            check("staging gone", [p.name for p in refs.iterdir() if p.is_dir()], [])
            check("occasions", [c["occasion"] for c in CALLS], ["base_front", "base_view", "base_view", "base_view"])
            check("use cases", [c["image_use_case"] for c in CALLS],
                  ["base_front", "base_back", "base_side", "base_side"])
            check("front reference", CALLS[0]["ref"], None)
            check("view reference names", [c["ref"].name for c in CALLS[1:]], [f"tpose_{bsig}.png"] * 3)
            check("view reference is a copy", any(c["ref"] == refs / f"tpose_{bsig}.png" for c in CALLS[1:]), False)
            check("view reference on grey", [c["corner"] for c in CALLS[1:]], [(128, 128, 128)] * 3)
            check("back_view", [bool(c.get("back_view")) for c in CALLS], [False, True, False, False])
            for call, view in zip(CALLS, views):
                prompt, negative = base_body.base_prompt("Demo", view)
                check(f"{view} bare_prompt", call["bare_prompt"], prompt)
                check(f"{view} extra_negative", call["extra_negative"], negative)
                check(f"{view} style_character", call.get("style_character"),
                      base_body.base_character("Demo", view))
                check(f"{view} no replacing negative", call.get("negative_prompt", ""), "")
                check(f"{view} equipped", (call["equipped_pieces"], call["equipped_items"]), ({}, []))
                check(f"{view} no state modifiers", call["apply_state_modifiers"], False)
                check(f"{view} size", (call["override_width"], call["override_height"]), (1024, 1024))
                check(f"{view} sidecar_extra", call["sidecar_extra"], {"base_signature": bsig})
            check("front was running during its render", CALLS[0]["running"], True)
            check("find_ref_image front", model_refs.find_ref_image("Demo", "tpose", bsig), refs / f"tpose_{bsig}.png")
            check("find_ref_image left", model_refs.find_ref_image("Demo", "tpose_left", bsig),
                  refs / f"tpose_left_{bsig}.png")
            check("result", out, {v: str(refs / f"{s}.png") for v, s in zip(views, stems)})
            status = base_body.base_info("Demo")["status"]
            check("status idle", {v: (s["running"], s["failed"]) for v, s in status.items()},
                  {v: (False, False) for v in views})
            CALLS.clear()
            check("cached call result", base_body.generate_base_images("Demo"), {})
            check("cached call renders nothing", len(CALLS), 0)
            out = base_body.generate_base_images("Demo", view="left", force=True)
            check("single view calls", [c["stem"].name for c in CALLS], [f"tpose_left_{bsig}"])
            check("single view reference", CALLS[0]["ref"].name, f"tpose_{bsig}.png")
            check("single view result", list(out), ["left"])
            CALLS.clear()
            check("cached single view", (base_body.generate_base_images("Demo", view="back"), len(CALLS)), ({}, 0))

            print("[2] refusals and a failing front")
            for label, kwargs in (("unknown view", {"character_name": "Demo", "view": "top"}),
                                  ("animal", {"character_name": "DemoFox"}),
                                  ("no profile image", {"character_name": "DemoBare"})):
                try:
                    base_body.generate_base_images(**kwargs)
                    check(label, "no error", "ValueError")
                except ValueError:
                    check(label, "ValueError", "ValueError")
            check("refusals render nothing", len(CALLS), 0)
            out = base_body.generate_base_images("DemoFail")
            check("failed front result", out, {"front": None})
            check("failed front: no view render", len(CALLS), 1)
            fail_status = base_body.base_info("DemoFail")["status"]
            check("failed front status", fail_status["front"]["failed"], True)
            check("views marked failed", {v: (fail_status[v]["failed"], fail_status[v]["error"])
                                          for v in ("back", "left", "right")},
                  {v: (True, "front render failed") for v in ("back", "left", "right")})
            try:
                base_body.generate_base_images("DemoFail", view="back")
                check("view without front", "no error", "ValueError")
            except ValueError:
                check("view without front", "ValueError", "ValueError")
            CALLS.clear()

            print("[3] base_info and the pipeline switch")
            info = base_body.base_info("Demo")
            check("pipeline off", info["pipeline"], False)
            check("signature", info["signature"], bsig)
            check("model", info["model"], None)
            want_urls = {v: f"/characters/Demo/base-body/images/{v}?v={(refs / (s + '.png')).stat().st_mtime_ns}"
                         for v, s in zip(views, stems)}
            check("image urls", info["images"], want_urls)
            check("switch on", base_body.set_pipeline("Demo", True), True)
            check("stored", get_character_profile("Demo").get("model_pipeline"), "base_body")
            check("info pipeline on", base_body.base_info("Demo")["pipeline"], True)
            check("switch off", base_body.set_pipeline("Demo", False), True)
            check("field removed", "model_pipeline" in get_character_profile("Demo"), False)
            before = get_character_profile("DemoFox")
            try:
                base_body.set_pipeline("DemoFox", True)
                check("animal switch", "no error", "ValueError")
            except ValueError:
                check("animal switch", "ValueError", "ValueError")
            check("animal profile unchanged", get_character_profile("DemoFox"), before)
        finally:
            expression_regen.render_character_image = real_render

        print("[4] the real render_character_image, fake image service")
        from app.imagegen import service as service_mod
        from app.models import character as character_mod
        payloads, mattes = [], []

        class FakeService:
            enabled = True
            last_image_meta = {"backend": "fake", "negative_prompt": "", "created_at": ""}

            def generate_from_input(self, raw):
                payload = json.loads(raw)
                payloads.append(payload)
                name = f"gen_{len(payloads)}.png"
                tiny_png(get_character_images_dir(payload["agent_name"]) / name)
                return f"![image](/images/{name})"

        def fake_postprocess(path, mesh_input=False, portrait_matte=False):
            mattes.append(mesh_input)
            return path

        real_service, real_post = service_mod.get_image_service, character_mod.postprocess_outfit_image
        service_mod.get_image_service = lambda: FakeService()
        character_mod.postprocess_outfit_image = fake_postprocess
        try:
            out = base_body.generate_base_images("Demo", force=True)
            payload_count = len(payloads)
            expression_regen.render_character_image(
                "Demo", output_stem=refs / "probe_plain", equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="", bare_prompt="probe", image_use_case="tpose",
                occasion="tpose", apply_state_modifiers=False)
            plain = payloads[payload_count]
            del payloads[payload_count:], mattes[payload_count:]
        finally:
            service_mod.get_image_service, character_mod.postprocess_outfit_image = real_service, real_post
        check("4 payloads", len(payloads), 4)
        front, back = payloads[0], payloads[1]
        check("front prompt bare", front["prompt"], base_body.base_prompt("Demo", "front")[0])
        check("front use case/occasion", (front["image_use_case"], front["occasion"]), ("base_front", "base_front"))
        check("front style_character", front.get("style_character"), base_body.base_character("Demo", "front"))
        check("front extra negative", front.get("negative_prompt_extra"), base_body.BASE_NEGATIVE)
        check("front no replacing negative", "negative_prompt" in front, False)
        check("front profile_only", front["profile_only"], True)
        check("front no reference override", "reference_image_override" in front, False)
        check("front clothed", front["clothed"], False)
        check("back use case/occasion", (back["image_use_case"], back["occasion"]), ("base_back", "base_view"))
        check("back style_character", back.get("style_character"), base_body.base_character("Demo", "back"))
        check("back reference override", back["reference_image_override"].endswith(f"/tpose_{bsig}.png"), True)
        check("matte path", mattes, [True] * 4)
        meta = json.loads((refs / f"tpose_{bsig}.json").read_text())
        check("sidecar base_signature", meta.get("base_signature"), bsig)
        check("sidecar prompt", meta.get("prompt"), base_body.base_prompt("Demo", "front")[0])
        check("sidecar mesh_variant key", "mesh_variant" in meta, True)
        check("sidecar equipped", meta.get("equipped_pieces"), {})
        check("real path result", sorted(out), sorted(views))
        from app.core.body_slots import exposed_slot_loras
        check("slot LoRA fixture live", [l["name"] for l in exposed_slot_loras("Demo")], ["slot-lora-x"])
        check("base payload LoRAs", [p.get("loras") for p in payloads], [[POSE_LORA]] * 4)
        check("no explicit LoRA flag", any("loras_explicit" in p for p in payloads), False)
        check("plain bare_prompt carries no LoRAs", "loras" in plain, False)
        check("plain bare_prompt carries no character block", "style_character" in plain, False)

        print("[5] service negative merge")
        from app.imagegen.service import ImageService, resolve_negative_prompt
        check("extra appended", resolve_negative_prompt({"negative_prompt_extra": "X"}, "UC"), "UC, X")
        check("explicit + extra", resolve_negative_prompt({"negative_prompt": "N", "negative_prompt_extra": "X"},
                                                          "UC"), "N, X")
        check("no extra", resolve_negative_prompt({}, "UC"), "UC")
        parsed = ImageService._parse_input(ImageService.__new__(ImageService), json.dumps(front))
        check("whitelist keeps extra", parsed.get("negative_prompt_extra"), base_body.BASE_NEGATIVE)
        check("whitelist keeps style_character", parsed.get("style_character"),
              base_body.base_character("Demo", "front"))
        check("no key parses to None",
              ImageService._parse_input(ImageService.__new__(ImageService), json.dumps(plain)).get(
                  "style_character", "(dropped)"), None)
        uc = config.get_use_case_prompts("base_front", "", clothed=False)["prompt_negative"]
        merged = resolve_negative_prompt(parsed, uc)
        check("tpose negative kept", merged.startswith(config._NEG_TPOSE), True)
        check("base negative appended", merged.endswith(base_body.BASE_NEGATIVE), True)

        print("[6] routes")
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
        expression_regen.render_character_image = recorder
        CALLS.clear()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
                check("player GET", client.get("/characters/Demo/base-body").status_code, 403)
                client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])
                r = client.get("/characters/Demo/base-body")
                check("admin GET", (r.status_code, r.json().get("signature")), (200, bsig))
                before = get_character_profile("DemoFox")
                r = client.post("/characters/DemoFox/base-body/pipeline", json={"enabled": True})
                check("animal pipeline", r.status_code, 400)
                check("animal profile unchanged", get_character_profile("DemoFox"), before)
                r = client.post("/characters/Demo/base-body/pipeline", json={"enabled": True})
                check("pipeline on", (r.status_code, r.json().get("pipeline")), (200, True))
                r = client.post("/characters/Demo/base-body/images", json={"view": "left", "force": True})
                check("images started", (r.status_code, r.json()), (202, {"started": True}))
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and (
                        len(CALLS) < 1 or base_body.base_info("Demo")["status"]["left"]["running"]):
                    time.sleep(0.05)
                check("worker rendered left only", [c["stem"].name for c in CALLS], [f"tpose_left_{bsig}"])
                check("bad view", client.post("/characters/Demo/base-body/images",
                                              json={"view": "sideways"}).status_code, 422)
                check("animal images", client.post("/characters/DemoFox/base-body/images", json={}).status_code, 400)
                check("no profile image", client.post("/characters/DemoBare/base-body/images",
                                                      json={}).status_code, 409)
                r = client.get("/characters/Demo/base-body/images/front")
                check("serve front", (r.status_code, r.content[:4]), (200, b"\x89PNG"))
                check("unknown character", client.get("/characters/Nobody/base-body").status_code, 404)
        finally:
            expression_regen.render_character_image = real_render

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
