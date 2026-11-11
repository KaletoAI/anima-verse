#!/usr/bin/env python3
"""The garment image chain's mechanics (app/core/garment_images.py and the
``postprocess`` switch of expression_regen.render_character_image), run on
an own-mesh dress. Written for the hair image chain (task 4 of plan
2026-11-09-base-body-phase4-hair); that chain is gone since the
hair-from-body spec 2026-11-11 (Task 2), so its hair prompts and hair gates
went with it and the mechanics are checked on the clothing chain (its
prompts and gates: smoke_garment_clothing_images.py).

Usage:
    ./.venv/bin/python scripts/smoke_garment_images.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no GPU, no server. The image service, the
renderer, rembg and the upscaler are stubs; every image is synthetic.
Controller rulings kept: ``postprocess=False``, no character LoRAs.

Fixture ``Demo`` (female, base-body pipeline, hair slot medium blonde,
appearance "slender") wears the own-mesh dress D = "dress" (slots [top,
bottom], "a green dress"). The base views model_refs/tpose_BSIG.png and
tpose_back_BSIG.png are RGBA 160x160: transparent background, opaque figure
in skin (200, 160, 140) = head disc centre (80, 26) radius 10 + torso
x [64, 96) y [36, 152). rembg stub = "every pixel with a channel more than 2
away from 128".

Prepared renders (all opaque RGB 160x160 on grey 128):
  GOOD_WORN  = the figure + the dress block x [64, 96) y [40, 110) in
               (40, 90, 50) -> pass (the outline outside the garment is the
               base's)
  SHIFTED    = GOOD_WORN with the torso moved 1 px right: the outline
               outside the garment region (the dress rows +- the 1 px
               margin, i.e. rows 39..110) changes at two columns over the
               torso rows 36..38 and 111..151 = 2 x 44 = 88 px of a base
               body of ~3.9-4.0k px -> XOR ~0.022 >= 0.015 -> fail
  GOOD_GHOST = grey + the dress block only -> pass
The recorder writes them by (step, view, attempt):
  worn/front : SHIFTED, then GOOD_WORN  -> accepted at attempt 2
  ghost/front: GOOD_GHOST               -> accepted at attempt 1

[1] worn/front: final = images/D_F_worn_front.png with the bytes of
    attempt 2; sidecar accepted True, gates.first = the fail record (ok
    False, ONE reason "body outline outside the garment changed ...",
    outside_xor in [0.020, 0.025]), gates.second ok True; two render calls.
    Each call: bare_prompt, extra_negative, image_use_case "garment_edit",
    occasion "garment_view", apply_state_modifiers False, pieces {} items [],
    character_loras False, postprocess False, override 160x160 (the square
    canvas: max(160, 160) = 160, already a multiple of 16),
    sidecar_extra.garment = {item_id D, fsig F, step worn, view front,
    attempt n}; the reference is the base front flattened on grey (same
    file name, inside model_refs). A second run without force renders
    nothing (cached).
[3] ghost/front: reference = a grey-square copy of the accepted worn front
    file (same name; square already, so the pixels are the worn image's),
    override 160x160; accepted.
[5] Sizes: a 100x90 source asks for 112x96 (rounded up to 16).
[6] cut_out (canvas 1200x1200 grey, a block in the dress colour (40, 90, 50)):
    - block 331x331 -> bbox width 331 -> side int(1.15*331) = 380 < 1024:
      the upscale stub (2x) is called once -> 760, Lanczos top-up -> 1024x1024
      RGBA; sidecar side 380, upscale.status "applied", backend "stub-up".
    - block 957x957 -> side int(1.15*957) = 1100 >= 1024: no upscale call,
      result 1100x1100, upscale.status "not_needed".
    - upscale stub raising -> Lanczos alone: 1024x1024, upscale.status
      "lanczos" with the reason.
    - the alpha of the result is opaque at the centre, transparent at a
      corner (the square pads the block by 7.5 % per side).
[8] Square canvas (bug A of the 2026-11-09 end-to-end run: a narrow source
    sent at its own size is re-framed by the edit model). NARROW base views =
    the 160x160 base cropped to columns [32, 128) -> 96x160 RGBA (the whole
    figure lies in x 64..96 and the head in 70..90, all inside). Square
    frame: side = max(96, 160) = 160 (a multiple of 16), offset
    ((160 - 96) // 2, (160 - 160) // 2) = (32, 0); a 100x90 source gives
    side 112 (100 rounded up to 16) at offset (6, 11). fsig Q = "0000000000f8".
    - worn/front: ONE render with override 160x160; the reference is
      160x160 and pixel-equal to the full undressed 160x160 image (grey
      padding 32 px each side, transparent pixels grey 128). The recorder
      returns GOOD_WORN (160x160, the figure at canvas x 64..96) -> cropped
      at (32, 0) to 96x160 = GOOD_WORN[:, 32:128]: body unchanged -> accepted
      at attempt 1; the final is 96x160 and pixel-equal to that crop;
      sidecar edit_canvas {side 160, offset [32, 0], crop [96, 160]}.
      Old code: override 96x160 and the 160x160 render squeezed to 96 wide
      -> the body gate refuses.
    - ghost/front: the source is the accepted 96x160 worn final -> the
      reference is GOOD_WORN again (pixel-equal), override 160x160. The
      recorder returns GOOD_GHOST scaled 2x (320x320): scaled back to
      160x160 (Lanczos), cropped at (32, 0) -> the attempt-1 file is
      96x160. (Whether the gate takes it is not the point here: the Lanczos
      ringing at the block edge moves the stub mask by a pixel.)
[7] render_character_image default path unchanged: with a stub image service
    a default call runs postprocess_outfit_image once and publishes its
    output; postprocess=False skips it and publishes the backend bytes
    unchanged.
"""
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
DRESS = (40, 90, 50)
SIZE = 160


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def png(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


def grey(size=SIZE):
    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    rgb[:] = GREY
    return rgb


def figure(rgb, torso_x0=64):
    yy, xx = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]]
    rgb[(xx - 80) ** 2 + (yy - 26) ** 2 <= 100] = SKIN
    rgb[36:152, torso_x0:torso_x0 + 32] = SKIN
    return rgb


def dress(rgb):
    rgb[40:110, 64:96] = DRESS
    return rgb


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        arr = np.asarray(im.convert("RGB")).astype(np.int16)
    mask = (np.abs(arr - 128) > 2).any(2)
    return png((mask * 255).astype(np.uint8))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-images-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, garment_assembly
        from app.core import garment_store as gs
        from app.models import inventory
        from app.imagegen import service
        from app.models import character as charmod
        from app.models.character import get_character_dir, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        charmod.run_rembg = rembg_stub
        REAL_RENDER = expression_regen.render_character_image
        try:
            from app.core import garment_images as gi
        except ImportError as e:
            check("garment_images importable", str(e), "importable")
            print("FAILED: " + ", ".join(FAILS))
            return 1

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = inventory.add_item(name="Dress", category="outfit_piece", owner="Demo", item_id="dress",
                                 prompt_fragment="a green dress",
                                 outfit_piece={"slots": ["top", "bottom"], "outfit_types": ["casual"],
                                               "own_mesh": True})["id"]
        inventory.add_to_inventory("Demo", hid)
        check("dress worn", inventory.equip_piece("Demo", hid, source="smoke").get("status"), "ok")
        cdir = get_character_dir("Demo")
        bsig = base_body.base_signature("Demo")
        refs = cdir / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        base_rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
        base_rgba[..., :3] = figure(grey())
        base_rgba[..., 3] = (figure(np.zeros((SIZE, SIZE, 3), dtype=np.uint8)).any(2) * 255)
        for name in (f"tpose_{bsig}.png", f"tpose_back_{bsig}.png"):
            (refs / name).write_bytes(png(base_rgba))
        fsig = gs.garment_fsig("Demo", hid)

        good_worn = dress(figure(grey()))
        shifted = dress(figure(grey(), torso_x0=65))
        good_ghost = dress(grey())
        plan = {("worn", "front"): [shifted, good_worn], ("ghost", "front"): [good_ghost]}
        calls = []

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            from PIL import Image
            with Image.open(kw["reference_image"]) as ref_im:
                ref_rgb = np.asarray(ref_im.convert("RGB"))
            calls.append({"stem": output_stem, **kw,
                          "reference_name": Path(kw["reference_image"]).name,
                          "reference_path": Path(kw["reference_image"]),
                          "reference_exists": Path(kw["reference_image"]).is_file(),
                          "reference_rgb": ref_rgb})
            arr = plan[(g["step"], g["view"])][g["attempt"] - 1]
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(arr))
            out.with_suffix(".json").write_text(json.dumps(
                {"prompt": kw["bare_prompt"], "seed": 1000 + g["attempt"], **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder

        print("[1] worn/front")
        final = gi.run_edit_step("Demo", hid, fsig, "worn", "front")
        want = gs.garment_path("Demo", hid, fsig, "image", step="worn", view="front")
        check("final path", final, want)
        check("final = attempt 2 bytes", final.read_bytes() == png(good_worn), True)
        rec = gs.read_record(final.with_suffix(".json"))
        check("accepted", rec.get("accepted"), True)
        check("accepted attempt", rec.get("attempt"), 2)
        first = rec["gates"]["first"]
        check("gates.first failed on the outline", (first["ok"], len(first.get("reasons") or []),
                                                    str((first.get("reasons") or [""])[0]).startswith(
                                                        "body outline outside the garment changed"),
                                                    0.020 <= float(first.get("outside_xor") or 0) <= 0.025),
              (False, 1, True, True))
        check("gates.second ok", rec["gates"]["second"]["ok"], True)
        check("two renders", len(calls), 2)
        c = calls[0]
        check("render kwargs", (c["image_use_case"], c["occasion"], c["apply_state_modifiers"],
                                c["equipped_pieces"], c["equipped_items"], c["character_loras"],
                                c["postprocess"]),
              ("garment_edit", "garment_view", False, {}, [], False, False))
        check("override size", (c["override_width"], c["override_height"]), (SIZE, SIZE))
        check("sidecar_extra", c["sidecar_extra"]["garment"],
              {"item_id": hid, "fsig": fsig, "step": "worn", "view": "front", "attempt": 1})
        check("attempt stems", [x["stem"].name for x in calls],
              [f"{hid}_{fsig}_worn_front.try1", f"{hid}_{fsig}_worn_front.try2"])
        check("reference = base front on grey", (c["reference_name"], c["reference_exists"],
                                                 refs.resolve() in c["reference_path"].resolve().parents),
              (f"tpose_{bsig}.png", True, True))
        try1 = gs.read_record(gs.garment_path("Demo", hid, fsig, "image", step="worn", view="front",
                                              attempt=1).with_suffix(".json"))
        check("attempt 1 sidecar gate", (try1.get("gate") or {}).get("ok"), False)
        calls.clear()
        check("cached", gi.run_edit_step("Demo", hid, fsig, "worn", "front"), final)
        check("cached renders nothing", len(calls), 0)

        print("[3] ghost/front")
        calls.clear()
        gfinal = gi.run_edit_step("Demo", hid, fsig, "ghost", "front")
        check("ghost accepted", gs.read_record(gfinal.with_suffix(".json")).get("accepted"), True)
        check("ghost reference = worn file on the square",
              (calls[0]["reference_name"], np.array_equal(calls[0]["reference_rgb"], good_worn)),
              (final.name, True))
        check("ghost override = worn size", (calls[0]["override_width"], calls[0]["override_height"]),
              (SIZE, SIZE))

        print("[5] sizes")
        check("round up to 16", gi.render_size((100, 90)), (112, 96))
        check("multiple stays", gi.render_size((160, 1536)), (160, 1536))

        print("[6] cut_out")
        up_calls = []

        class Up:
            enabled = True
            fail = False

            def upscale_image(self, image_bytes, **kw):
                from PIL import Image
                up_calls.append(kw)
                if self.fail:
                    raise RuntimeError("upscaler down")
                with Image.open(io.BytesIO(image_bytes)) as im:
                    big = im.convert("RGB").resize((im.width * 2, im.height * 2))
                out = io.BytesIO()
                big.save(out, format="PNG")
                return {"bytes": out.getvalue(), "backend": "stub-up", "scale": 2, "in": [im.width, im.height],
                        "out": list(big.size), "cached": False, "status": "applied"}

        up = Up()
        real_service = service.get_image_service
        service.get_image_service = lambda: up
        try:
            from PIL import Image

            def ghost_file(fs, block):
                canvas = grey(1200)
                canvas[100:100 + block, 200:200 + block] = DRESS
                path = gs.garment_path("Demo", hid, fs, "image", step="ghost", view="front")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png(canvas))
                gs.write_record(path.with_suffix(".json"), {"accepted": True})

            small, large, down = "00000000000a", "00000000000b", "00000000000c"
            ghost_file(small, 331)
            ghost_file(large, 957)
            ghost_file(down, 331)
            out = gi.cut_out("Demo", hid, small, "front")
            check("cutout path", out, gs.garment_path("Demo", hid, small, "image", step="cutout", view="front"))
            with Image.open(out) as im:
                check("small result", (im.size, im.mode), ((1024, 1024), "RGBA"))
                alpha = np.asarray(im.getchannel("A"))
            check("upscale called once", len(up_calls), 1)
            rec = gs.read_record(out.with_suffix(".json"))
            check("small sidecar", (rec.get("side"), rec["upscale"].get("status"), rec["upscale"].get("backend")),
                  (380, "applied", "stub-up"))
            check("small bbox", rec.get("bbox"), [200, 100, 531, 431])
            check("alpha centre/corner", (int(alpha[512, 512]) > 200, int(alpha[2, 2]) < 16), (True, True))
            up_calls.clear()
            out = gi.cut_out("Demo", hid, large, "front")
            with Image.open(out) as im:
                check("large result", im.size, (1100, 1100))
            check("large: no upscale", len(up_calls), 0)
            check("large sidecar", gs.read_record(out.with_suffix(".json"))["upscale"].get("status"), "not_needed")
            up.fail = True
            out = gi.cut_out("Demo", hid, down, "front")
            with Image.open(out) as im:
                check("lanczos result", im.size, (1024, 1024))
            rec = gs.read_record(out.with_suffix(".json"))
            check("lanczos sidecar", (rec["upscale"].get("status"), "upscaler down" in rec["upscale"].get("reason", "")),
                  ("lanczos", True))
        finally:
            service.get_image_service = real_service

        print("[8] square canvas for a narrow source")
        for name in (f"tpose_{bsig}.png", f"tpose_back_{bsig}.png"):
            (refs / name).write_bytes(png(np.ascontiguousarray(base_rgba[:, 32:128])))
        check("square frame", gi.square_frame((96, 160)), (160, (32, 0)))
        check("square frame rounds up", gi.square_frame((100, 90)), (112, (6, 11)))
        q = "0000000000f8"
        plan[("worn", "front")] = [good_worn, good_worn]
        plan[("ghost", "front")] = [np.repeat(np.repeat(good_ghost, 2, axis=0), 2, axis=1)] * 2
        calls.clear()
        qfinal = None
        try:
            qfinal = gi.run_edit_step("Demo", hid, q, "worn", "front")
        except gi.GateRefused as e:
            check("narrow worn accepted", str(e), "accepted")
        check("narrow: one render", len(calls), 1)
        if calls:
            check("narrow override square", (calls[0]["override_width"], calls[0]["override_height"]),
                  (160, 160))
            check("narrow reference square + centred",
                  (calls[0]["reference_rgb"].shape, np.array_equal(calls[0]["reference_rgb"], figure(grey()))),
                  ((160, 160, 3), True))
        if qfinal is not None:
            from PIL import Image
            with Image.open(qfinal) as im:
                q_rgb = np.asarray(im.convert("RGB"))
            check("narrow final cropped back", (q_rgb.shape, np.array_equal(q_rgb, good_worn[:, 32:128])),
                  ((160, 96, 3), True))
            q_rec = gs.read_record(qfinal.with_suffix(".json"))
            check("narrow accepted at 1", (q_rec.get("accepted"), q_rec.get("attempt")), (True, 1))
            check("narrow edit_canvas", q_rec.get("edit_canvas"),
                  {"side": 160, "offset": [32, 0], "crop": [96, 160]})
            calls.clear()
            try:
                gi.run_edit_step("Demo", hid, q, "ghost", "front")
            except gi.GateRefused:
                pass
            if calls:
                check("narrow ghost reference", (calls[0]["override_width"], calls[0]["override_height"],
                                                 np.array_equal(calls[0]["reference_rgb"], good_worn)),
                      (160, 160, True))
            g_try = gs.garment_path("Demo", hid, q, "image", step="ghost", view="front", attempt=1)
            with Image.open(g_try) as im:
                check("narrow ghost 2x render cropped back", im.size, (96, 160))

        print("[7] render_character_image default path")
        expression_regen.render_character_image = REAL_RENDER
        images_dir = charmod.get_character_images_dir("Demo")
        images_dir.mkdir(parents=True, exist_ok=True)
        raw = png(good_worn)
        pp_calls = []

        class Gen:
            enabled = True

            def generate_from_input(self, payload):
                (images_dir / "gen_1.png").write_bytes(raw)
                return "![x](/images/gen_1.png)"

        def fake_pp(path, mesh_input=False, portrait_matte=False):
            pp_calls.append(path.name)
            out = path.with_name(path.stem + "_pp.png")
            out.write_bytes(b"post-processed")
            path.unlink()
            return out

        real_pp = charmod.postprocess_outfit_image
        charmod.postprocess_outfit_image = fake_pp
        service.get_image_service = lambda: Gen()
        try:
            stem = root / "render" / "default"
            stem.parent.mkdir()
            out = REAL_RENDER("Demo", output_stem=stem, equipped_pieces={}, equipped_items=[],
                              pose_prompt="", expression_prompt="", bare_prompt="x",
                              image_use_case="garment_edit", occasion="garment_view",
                              apply_state_modifiers=False)
            check("default runs postprocess", len(pp_calls), 1)
            check("default publishes postprocessed", out.read_bytes() if out else None, b"post-processed")
            pp_calls.clear()
            out = REAL_RENDER("Demo", output_stem=root / "render" / "raw", equipped_pieces={},
                              equipped_items=[], pose_prompt="", expression_prompt="", bare_prompt="x",
                              image_use_case="garment_edit", occasion="garment_view",
                              apply_state_modifiers=False, postprocess=False)
            check("postprocess=False skips it", len(pp_calls), 0)
            check("raw bytes published", bool(out) and out.read_bytes() == raw, True)
            check("raw name", out.name if out else None, "raw.png")
        finally:
            charmod.postprocess_outfit_image = real_pp
            service.get_image_service = real_service

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
