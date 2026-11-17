#!/usr/bin/env python3
"""Ruling A175: a dressed back (and side) view is TURN -> CUT OUT -> DRESS.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_back_turn_a175.py

Runs without the server and without a world (no paths.init, no DB). Every socket connect is refused for the
whole run, ``expression_regen.render_character_image`` is a recording stub (no hub job, no image generation),
``run_rembg`` is a stub (no model load), and the composite / publish / refusal helpers are stubbed — the smoke
checks only the chain in ``base_body._dress_view``.

Config (stubbed ``config.get``): image_generation.outfit_turn_lora = "angle.safetensors", strength 0.8.

Fixtures (PIL): FRONT = 100 x 200 RGB (90, 90, 90) with a figure (columns 40..59) (20, 30, 120). BASE_BACK =
100 x 200 RGB grey with a skin figure. The turn stub writes a 208 x 208 RGB image of colour TURN (5, 6, 7); the
rembg stub returns that image as RGBA with alpha 0 outside columns 80..127 (a matte: "cut out").

Expected, by hand:
[1] Exactly two renders, in this order: occasion "outfit_back_turn" then "outfit_back_draft" (the turn is step 1,
    the edit step 3; step 2 is CPU).
[2] The turn: bare_prompt == "Make the shot a full body rear view of the person." (the LoRA's trained back
    prompt, [SUBJECT] -> "person" like DRAFT_PROMPTS' "the same person"), expression_set_loras ==
    [{"name": "angle.safetensors", "strength": 0.8}], reference_image = the FRONT on its square canvas
    (side = 200 -> 208, offset (54, 4): pixel (54+50, 4+100) is the figure colour (20, 30, 120)),
    require_reference True.
[3] The cut-out: rembg was called once with the turn's bytes; the draft's extra_reference_images is one file
    whose pixels are the rembg output flattened by ``_frozen_reference`` onto
    ``model_refs.VIEW_REFERENCE_BACKGROUND``: column 0 (matted away) = that grey, column 100 = TURN (5, 6, 7).
[4] The draft prompt (bald body): DRESS_VIEW["back"] + " " + DRESS_KEEP + " " + EDIT_FROM_SECOND_PICTURE —
    no clothing words: none of "boxer", "coat", "shirt" (the pieces' texts given to _dress_view) appear;
    extra_reference_prompt == EDIT_SECOND_PICTURE with ", as it looks from behind"; draft sidecar has
    turned_second True.
[5] Job counts: dressed_view_jobs() with front + back = 1 + 2*1 = 3; with the sides 1 + 2*3 = 7.
[6] Side views: turn prompts "... side view of the person facing left." for "left", "... facing right." for
    "right" (base view "left" = profile facing the LEFT edge of the frame, DRESS_VIEW).
[7] No socket connect was attempted.
"""
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONNECTS = []


def _refuse(self, *a, **k):
    CONNECTS.append(a)
    raise OSError("outbound connection refused by the smoke")


socket.socket.connect = _refuse

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(name)


def main() -> int:
    from PIL import Image
    import io
    from app.core import base_body, config, expression_regen
    from app.core.garment_hair import BALD
    from app.models import character

    real_get = config.get
    config.get = lambda key, default=None: {"image_generation.outfit_turn_lora": "angle.safetensors",
                                            "image_generation.outfit_turn_lora_strength": 0.8}.get(
        key, real_get(key, default))

    calls = []

    def render(character_name, *, output_stem, **kw):
        kw["output_stem"] = output_stem
        extras = [Image.open(p).convert("RGBA").copy() for p in kw.get("extra_reference_images") or []]
        ref = Image.open(kw["reference_image"]).convert("RGB").copy() if kw.get("reference_image") else None
        calls.append({**kw, "_extras": extras, "_ref": ref})
        out = Path(f"{output_stem}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (208, 208), (5, 6, 7)).save(out)
        return out

    rembg_calls = []

    def rembg(data, model=None, **k):
        rembg_calls.append(data)
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        for x in range(im.width):
            if not 80 <= x <= 127:
                for y in range(im.height):
                    im.putpixel((x, y), (0, 0, 0, 0))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    expression_regen.render_character_image = render
    character.run_rembg = rembg
    base_body._composite_attempt = lambda *a, stem, draft, **k: (draft, {
        "ok": True, "composite": {"ok": True}, "guard": {}, "noise": {}})
    base_body._publish_staged = lambda staged, final, record, key="": final
    base_body.clear_view_refusals = lambda *a, **k: None
    base_body.record_view_refusal = lambda *a, **k: None

    with tempfile.TemporaryDirectory() as tmp:
        refs = Path(tmp)
        front = refs / "tpose_sig.png"
        im = Image.new("RGB", (100, 200), (90, 90, 90))
        for x in range(40, 60):
            for y in range(20, 180):
                im.putpixel((x, y), (20, 30, 120))
        im.save(front)
        back = refs / "tpose_back_bsig.png"
        Image.new("RGB", (100, 200), (128, 128, 128)).save(back)
        kw = dict(signature="sig", bsig="bsig", pieces={"legs": "boxer"}, items=[], profile={"name": "Demo"},
                  front=front, base_views={"front": None, "back": back, "left": None, "right": None},
                  refs_dir=refs, size=(100, 200), reuse_draft=False, hair=BALD, bald=False,
                  text="grey cotton boxer briefs, dark navy shirt, long captain's coat")
        base_body._dress_view("Demo", "back", **kw)

        print("[1] order")
        check("occasions", [c["occasion"] for c in calls], ["outfit_back_turn", "outfit_back_draft"])
        turn, draft = calls
        print("[2] the turn")
        check("turn prompt", turn["bare_prompt"], "Make the shot a full body rear view of the person.")
        check("turn LoRA", turn["expression_set_loras"], [{"name": "angle.safetensors", "strength": 0.8}])
        check("turn input = front on its canvas", turn["_ref"].getpixel((104, 104)), (20, 30, 120))
        check("turn require_reference", turn["require_reference"], True)
        print("[3] the cut-out is the second picture")
        check("rembg once", len(rembg_calls), 1)
        second = draft["_extras"]
        check("one second picture", len(second), 1)
        from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
        check("cut-out flattened on neutral grey (col 0 = background, col 100 = the figure)",
              (second[0].getpixel((0, 104))[:3], second[0].getpixel((100, 104))[:3]),
              (tuple(VIEW_REFERENCE_BACKGROUND), (5, 6, 7)))
        print("[4] the draft prompt names no clothing")
        want = f"{base_body.DRESS_VIEW['back']} {base_body.DRESS_KEEP} {base_body.EDIT_FROM_SECOND_PICTURE}"
        check("draft prompt", draft["bare_prompt"], want)
        check("no clothing words", [w for w in ("boxer", "coat", "shirt") if w in draft["bare_prompt"]], [])
        check("second picture sentence", draft["extra_reference_prompt"], base_body.edit_second_picture("back"))
        check("sidecar turned_second", draft["sidecar_extra"].get("turned_second"), True)

    print("[5] job counts")
    real_views = base_body.dressed_views
    base_body.dressed_views = lambda: ("front", "back")
    two = base_body.dressed_view_jobs()
    base_body.dressed_views = lambda: ("front", "back", "left", "right")
    four = base_body.dressed_view_jobs()
    base_body.dressed_views = real_views
    check("dressed_view_jobs", (two, four), (3, 7))
    print("[6] side prompts")
    check("left/right", (base_body.turn_prompt("left"), base_body.turn_prompt("right")),
          ("Make the shot a full body side view of the person facing left.",
           "Make the shot a full body side view of the person facing right."))
    print("[7] outbound")
    check("no outbound connection", CONNECTS, [])
    if FAILS:
        print(f"\nFAILED: {', '.join(FAILS)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
