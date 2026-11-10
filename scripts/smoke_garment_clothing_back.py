#!/usr/bin/env python3
"""The worn BACK of an own-mesh outfit piece is drafted from the worn FRONT
and fitted onto the base back (app/core/garment_images.py ``_drafted_back``,
garment_clothing.py ``draft_prompt`` / ``back_reasons``, garment_gates.py
``back_follows_front``, base_body.py ``render_draft`` / ``render_fit`` /
``fit_references``, garments.py per-step view order).

Why: one edit of the base back ("they now wear only …") turned the body
toward the camera — live "Black Blazer" (Kira, 2026-11-09): the back view
showed lapels, buttons, flap pockets and the open V of the FRONT under a
back-of-head, and the worn gate accepted it (head unchanged, outline kept).

Usage:
    ./.venv/bin/python scripts/smoke_garment_clothing_back.py

Throwaway storage + instance, a copy of the ``human`` package; no world, no
hub, no GPU, no server. REAL: run_edit_step, the gates, fit_references /
fit_canvas, garments.run_garment. Stubbed: the renderer (writes the planned
image, records every call), ``character.run_rembg`` (every pixel more than 2
away from grey 128 is figure; RGBA cut-out unless ``only_mask``), and for
the chain runs ``cut_out`` / ``garment_mesh.generate`` / ``garments._fit``.

Fixture (the canvas of smoke_garment_clothing_images.py), W 1024 x H 1200 on
grey 128: BASE = head disc centre (512, 200) r 100 + torso cols [392, 632)
rows [300, 1100) in skin (200, 160, 140) -> figure rows 100 .. 1099, y0 100,
Hb 999; morphology at H 1200: open 2, close 3, margin 6 iterations.
Item J = "Black Blazer", outfit piece, slots [top], own_mesh, fragment
"a black tailored blazer with silver buttons".

JACKET(bottom, v) = green (40, 90, 50) cols [380, 644) rows [320, bottom],
skin again in the opening cols [472, 552) rows [320, 320 + v) (unchanged
base skin -> not garment). Garment region bbox [380, 320, 643, bottom];
neckline: centre int((380 + 643) / 2) = 511, band round(0.03 x 263) = 8 ->
columns 503 .. 519 all inside the opening -> first garment row 320 + v ->
depth v px = v / 999 Hb.
  FRONT      = JACKET(759, 100): neckline 100 / 999 = 0.1001 Hb, hem_t
               (759 - 100) / 999 = 0.65966.
  BACK_OK    = JACKET(759, 10):  neckline 0.01 Hb (< 0.04: no opening), hem
               0.65966 -> follows the front, accepted.
  BACK_FRONT = FRONT on the back view (the live failure): 0.1001 >= 0.04 and
               >= 0.5 x 0.1001 -> refused "back shows the front opening".
  BACK_SHORT = JACKET(700, 10): hem_t 600 / 999 = 0.6006 — NOT refused here:
               the worn region of a real fit runs past the cloth (the hems
               are compared on the ghosts, ``hems_agree``).
  BACK_LEGS  = BACK_OK with the torso rows [850, 1100) cols [392, 402) and
               [622, 632) grey (a fit re-rendering the legs): 250 x 20 = 5000
               base pixels gone, all below the jacket + 6 px margin (765) ->
               XOR 5000 / base area. Base area = the r-100 disc (Gauss circle
               N(100) = 31417) + torso 800 x 240 = 192000 - 1 (the disc's
               bottom pixel (512, 300) is torso too) = 223416 -> 0.02238 ->
               0.0224: refused at the edit limit 0.015, accepted at the
               fitted back's 0.04 (record outside_xor_max 0.04).
  BACK_EXTRA = BACK_OK + green cols [392, 632) rows [800, 900) (the fit put
               on something the front does not wear — live 2026-11-10: bodysuits
               and underwear on footwear backs). Front garment rows (320 - 100)
               / 999 = 0.22022 .. (759 - 100) / 999 = 0.65966, ± 0.02 -> row t
               <= 0.67966 -> rows <= 778: the jacket lies inside, the added
               part (rows 800..899, 40 rows below the jacket: its own part)
               outside: 100 x 240 = 24000 minus the opening's 4 x 3 cut
               corners = 23988 / 223416 = 0.10737 -> extra_part 0.1074 > 0.02
               -> refused "back puts on more than the front"; it lies inside
               the figure, so the outline is unchanged (XOR 0, worn gate ok).
               BACK_OK with the front: extra_part 0.0 -> follows.
The other backs change nothing outside the jacket -> worn gate ok (outside 0).

Fit canvas (fit_references(base, draft, size (1, 1), grey)): base 1024 x
1200 -> height 1200, width max(1024, 1200 x 1 / 1, draft figure) = 1200,
base pasted at left (1200 - 1024) // 2 = 88. The stub renders the planned
image centred in the canvas (dx 88) -> cropped back at offset (88, 0) it is
the planned image again.

[1] prompts: draft = base_body.draft_prompt(back, outfit_text = "wearing only
    a black tailored blazer with silver buttons, the same garment as on the
    person in the reference image, with the same length, cut and colour") —
    not the outfit's DRAFT_OUTFIT_TEXT; its negative ends with the worn
    negative "loose clothing, baggy, skirt, dress, shoes, socks, hair" —
    "jacket" is dropped: its pattern (base_body.DRESS_GARMENT_NEGATIVE,
    r"jackets?|coats?|blazers?") names the fragment's "blazer". Fit prompt = "edit the first image with the clothes from the
    second image". edit_prompt(worn, back) -> ValueError. EDIT_STEPS worn
    views (front, back), back "draft"; ghost keeps the default order.
[2] gate numbers (worn_gate + back_follows_front) as derived above.
[3] chain run from scratch, fits [BACK_FRONT, BACK_OK]: render order worn f1,
    worn bd (draft), worn b1, worn b2, ghost b1, ghost f1 — the draft once,
    BEFORE the fits, the front before both. Draft call: occasion
    "outfit_back_draft", use case "base_back", reference = the worn front's
    file name, character_loras True. Fit calls: occasion "outfit_back", use
    case "outfit_fit", postprocess False, 1200 x 1200, image 1 = the base
    back, image 2 = the draft. Back attempt 1 refused with the opening
    reason, attempt 2 accepted; the accepted back records front_sha256 = the
    worn front's sha, draft = the draft's file name.
[4] both fits front-facing -> run refused at worn back with the opening
    reason twice; no ghost rendered.
[5] a new accepted front drops the worn back (+ its ghost); a back whose
    front_sha256 is not the current front is not served from the cache.
[6] fsig: version 2 differs from the same inputs under version 1.
"""
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
GREEN = (40, 90, 50)
W, H = 1024, 1200
FRAGMENT = "a black tailored blazer with silver buttons"
DRAFT_TEXT = ("wearing only a black tailored blazer with silver buttons, the same garment as on the person in "
              "the reference image, with the same length, cut and colour")
WORN_NEG = "loose clothing, baggy, skirt, dress, shoes, socks, hair"
FIT_PROMPT = "edit the first image with the clothes from the second image"
OPENING = "back shows the front opening: neckline 0.1001 Hb deep, front 0.1001 Hb"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
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


def jacket(bottom, v):
    rgb = figure(canvas())
    rgb[320:bottom + 1, 380:644] = GREEN
    rgb[320:320 + v, 472:552] = SKIN
    return rgb


def mask_of(rgb):
    return (np.abs(rgb.astype(np.int16) - 128) > 2).any(2)


BASE = figure(canvas())
FRONT = jacket(759, 100)
BACK_OK = jacket(759, 10)
BACK_FRONT = FRONT
BACK_SHORT = jacket(700, 10)
BACK_LEGS = BACK_OK.copy()
BACK_LEGS[850:1100, 392:402] = GREY
BACK_LEGS[850:1100, 622:632] = GREY
BACK_EXTRA = BACK_OK.copy()
BACK_EXTRA[800:900, 392:632] = GREEN


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB"))
    mask = (mask_of(rgb) * 255).astype(np.uint8)
    return png(mask) if kwargs.get("only_mask") else png(np.dstack([rgb, mask]))


def raises(label, fn, exc, text=""):
    try:
        fn()
    except exc as e:
        check(label, text in str(e), True)
        return
    except Exception as e:  # noqa: BLE001
        check(label, type(e).__name__, exc.__name__)
        return
    check(label, "no error", "raised")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-back-") as tmp:
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

        from app.core import base_body, expression_regen, garment_assembly, garment_clothing, garment_images
        from app.core import garment_mesh, garments
        from app.core import garment_gates as gg
        from app.core import garment_store as gs
        from app.imagegen import service as imgservice
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        charmod.run_rembg = rembg_stub

        def no_hub(*a, **k):
            raise AssertionError("no hub call in this smoke")
        imgservice.get_image_service = no_hub

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        jid = inventory.add_item(name="Black Blazer", category="outfit_piece", prompt_fragment=FRAGMENT,
                                 outfit_piece={"slots": ["top"], "outfit_types": ["casual"],
                                               "own_mesh": True})["id"]
        check("inventory", inventory.add_to_inventory("Demo", jid), True)
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png(BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
        fsig = gs.garment_fsig("Demo", jid)

        print("[1] prompts")
        draft = garment_clothing.draft_prompt("Demo", "worn", item_id=jid)
        outfit_prompt, outfit_negative = base_body.draft_prompt("Demo", "back", outfit_text=DRAFT_TEXT)
        check("draft prompt = the base back prompt with the piece", draft[0], outfit_prompt)
        check("draft text in it, not the outfit's", (DRAFT_TEXT in draft[0],
                                                     base_body.DRAFT_OUTFIT_TEXT in draft[0]), (True, False))
        check("draft negative", draft[1], f"{outfit_negative}, {WORN_NEG}")
        check("fit prompt", base_body.FIT_PROMPT, FIT_PROMPT)
        raises("worn back is no edit", lambda: garment_clothing.edit_prompt("Demo", "worn", "back", item_id=jid),
               ValueError, "drafted from the worn front")
        raises("ghost has no draft", lambda: garment_clothing.draft_prompt("Demo", "ghost", item_id=jid),
               ValueError, "no drafted back")
        check("worn order + draft", (garment_clothing.EDIT_STEPS["worn"]["views"],
                                     garment_clothing.EDIT_STEPS["worn"]["back"],
                                     "views" in garment_clothing.EDIT_STEPS["ghost"]),
              (("front", "back"), "draft", False))

        print("[2] gates")

        def worn(arr, view):
            return gg.worn_gate(BASE, mask_of(BASE), arr, mask_of(arr), view=view)

        front = worn(FRONT, "front")
        check("front", (front["ok"], front["neckline_depth"], front["hem_t"]), (True, 0.1001, 0.65966))
        ok, copy, short = worn(BACK_OK, "back"), worn(BACK_FRONT, "back"), worn(BACK_SHORT, "back")
        check("backs pass the worn gate alone", (ok["ok"], copy["ok"], short["ok"]), (True, True, True))
        check("back numbers", [(r["neckline_depth"], r["hem_t"]) for r in (ok, copy, short)],
              [(0.01, 0.65966), (0.1001, 0.65966), (0.01, 0.6006)])
        check("real back follows", gg.back_follows_front(front, ok), [])
        got = gg.back_follows_front(front, copy)
        check("front copy refused", (len(got), got[0].startswith(OPENING) if got else None), (1, True))
        check("no hem rule on worn images", gg.back_follows_front(front, short), [])
        legs = worn(BACK_LEGS, "back")
        check("legs: edit limit refuses", (legs["ok"], legs["outside_xor"]), (False, 0.0224))
        fitted = garment_clothing.gate("worn", "back", base_rgb=BASE, base_mask=mask_of(BASE), source_rgb=None,
                                       source_mask=None, edit_rgb=BACK_LEGS, edit_mask=mask_of(BACK_LEGS),
                                       item_id=jid, fitted=True)
        check("legs: fitted back limit accepts", (fitted["ok"], fitted["outside_xor"], fitted["outside_xor_max"]),
              (True, 0.0224, 0.04))
        check("front chip gated on the front only", gg.limits("clothing")["worn"]["outside_xor"]["views"], ["front"])
        def fitted_back(arr):
            return garment_clothing.gate("worn", "back", base_rgb=BASE, base_mask=mask_of(BASE), source_rgb=None,
                                         source_mask=None, edit_rgb=arr, edit_mask=mask_of(arr), item_id=jid,
                                         fitted=True, front_gate=front)
        extra = fitted_back(BACK_EXTRA)
        check("extra: worn gate alone passes", (extra["ok"], extra["outside_xor"], extra["extra_part"]),
              (True, 0.0, 0.1074))
        check("extra: back puts on more than the front", gg.back_follows_front(front, extra),
              ["back puts on more than the front: a part of 0.1074 of the body outside the front piece's rows > 0.02"])
        real = fitted_back(BACK_OK)
        check("real back: nothing beyond the front rows", (real["extra_part"], gg.back_follows_front(front, real)),
              (0.0, []))
        check("garment rows of the front", gg.garment_rows(front), ((320 - 100) / 999, (759 - 100) / 999))
        check("shallow front checks no opening", gg.back_follows_front({**front, "neckline_depth": 0.03}, copy), [])
        check("old record checks nothing", gg.back_follows_front({}, copy), [])

        print("[3] chain: front, draft, fits")
        calls, plan = [], {}

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            key = f"{g['step']} {g['view'][0]}{g.get('attempt', 'd')}"
            calls.append((key, kw))
            if g.get("stage") == "draft":
                arr = FRONT  # a fresh render: its own frame
            else:
                queue = plan.get((g["step"], g["view"])) or []
                arr = queue.pop(0) if queue else (FRONT if g["step"] == "worn" else canvas())
                if g["step"] == "ghost":
                    arr = arr.copy()
                    arr[mask_of(BASE) & ~(arr == GREEN).all(2)] = GREY
                out = np.full((kw["override_height"], kw["override_width"], 3), 128, dtype=np.uint8)
                dy, dx = (out.shape[0] - arr.shape[0]) // 2, (out.shape[1] - arr.shape[1]) // 2
                out[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
                arr = out
            path = Path(str(output_stem) + ".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png(arr))
            path.with_suffix(".json").write_text(json.dumps(kw["sidecar_extra"]))
            return path

        expression_regen.render_character_image = recorder

        def cut_out(character_name, item_id, fsig_, view, *, force=False):
            path = gs.garment_path(character_name, item_id, fsig_, "image", step="cutout", view=view)
            path.write_bytes(b"cutout")
            gs.write_record(path.with_suffix(".json"), {"accepted": True})
            return path

        garment_images.cut_out = cut_out
        garment_mesh.generate = lambda *a, **k: None
        garments._fit = lambda *a, **k: None
        plan[("worn", "back")] = [BACK_FRONT, BACK_LEGS]
        plan[("ghost", "back")] = [BACK_OK]
        plan[("ghost", "front")] = [FRONT]
        res = garments.run_garment("Demo", jid)
        order = [k for k, _kw in calls]
        check("run ok", (res.get("ok"), res.get("error")), (True, None))
        check("render order", order[:6], ["worn f1", "worn bd", "worn b1", "worn b2", "ghost b1", "ghost f1"])
        check("one draft", order.count("worn bd"), 1)
        kw = dict(calls)["worn bd"]
        front_final = gs.garment_path("Demo", jid, fsig, "image", step="worn", view="front")
        check("draft call", (kw["occasion"], kw["image_use_case"], kw["character_loras"], kw["bare_prompt"],
                             Path(kw["reference_image"]).name, kw.get("postprocess", True)),
              ("outfit_back_draft", "base_back", True, draft[0], front_final.name, True))
        fit = dict(calls)["worn b1"]
        draft_file = garment_images.draft_path("Demo", jid, fsig, "worn")
        check("fit call", (fit["occasion"], fit["image_use_case"], fit["bare_prompt"], fit["postprocess"],
                           fit["override_width"], fit["override_height"],
                           Path(fit["reference_image"]).name, [Path(p).name for p in fit["extra_reference_images"]]),
              ("outfit_back", "outfit_fit", FIT_PROMPT, False, 1200, 1200, f"tpose_back_{bsig}.png",
               [draft_file.name]))
        back_final = gs.garment_path("Demo", jid, fsig, "image", step="worn", view="back")
        record = gs.read_record(back_final.with_suffix(".json"))
        first = record.get("gates", {}).get("first") or {}
        check("attempt 1 refused for the opening", (first.get("ok"),
                                                    any(r.startswith(OPENING) for r in first.get("reasons") or [])),
              (False, True))
        check("attempt 2 accepted, follows the front",
              (record.get("accepted"), record.get("attempt"), record.get("front_sha256"), record.get("draft")),
              (True, 2, base_body.file_sha256(front_final), draft_file.name))
        second = record.get("gates", {}).get("second") or {}
        check("the fit was gated as fitted", (second.get("outside_xor"), second.get("outside_xor_max")), (0.0224, 0.04))
        check("draft stored as a garment file", (draft_file.is_file(), gs.parse_name(draft_file)),
              (True, (jid, fsig)))
        check("the fit is the planned back again", bool((np.asarray(
            __import__("PIL.Image", fromlist=["Image"]).open(back_final).convert("RGB")) == BACK_LEGS).all()), True)

        print("[4] a front-facing back never reaches the ghost")
        del calls[:]
        plan[("worn", "back")] = [BACK_FRONT, BACK_FRONT]
        res = garments.run_garment("Demo", jid, steps="worn", view="back", force=True)
        attempts = (res.get("gates") or {}).get("attempts") or []
        check("refused at worn back", (res.get("ok"), res.get("step"), (res.get("gates") or {}).get("view")),
              (False, "worn", "back"))
        check("both for the opening", [any(r.startswith(OPENING) for r in a.get("reasons") or []) for a in attempts],
              [True, True])
        check("no ghost rendered", [k for k, _kw in calls], ["worn bd", "worn b1", "worn b2"])

        print("[5] a new front drops its back")
        plan[("worn", "back")] = [BACK_OK]
        plan[("ghost", "back")] = [BACK_OK]
        plan[("ghost", "front")] = [FRONT]
        res = garments.run_garment("Demo", jid, steps="worn", view="back", force=True)
        check("back again", (res.get("ok"), res.get("error")), (True, None))
        ghost_back = gs.garment_path("Demo", jid, fsig, "image", step="ghost", view="back")
        ghost_back.write_bytes(png(canvas()))
        gs.write_record(ghost_back.with_suffix(".json"), {"accepted": True})
        garment_images.run_edit_step("Demo", jid, fsig, "worn", "front", force=True)
        check("worn back + ghost back dropped", (back_final.exists(), ghost_back.exists()), (False, False))
        del calls[:]
        plan[("worn", "back")] = [BACK_OK]
        garment_images.run_edit_step("Demo", jid, fsig, "worn", "back")
        check("back re-drafted", [k for k, _kw in calls], ["worn bd", "worn b1"])
        rec = gs.read_record(back_final.with_suffix(".json"))
        gs.write_record(back_final.with_suffix(".json"), {**rec, "front_sha256": "0" * 64})
        del calls[:]
        plan[("worn", "back")] = [BACK_OK]
        garment_images.run_edit_step("Demo", jid, fsig, "worn", "back")
        check("stale back not served from the cache", [k for k, _kw in calls], ["worn bd", "worn b1"])
        del calls[:]
        garment_images.run_edit_step("Demo", jid, fsig, "worn", "back")
        check("current back served from the cache", calls, [])

        print("[6] fsig version")
        check("version", gs.GARMENT_VERSION["clothing"], 2)
        gs.GARMENT_VERSION["clothing"] = 1
        try:
            check("version 1 had another fsig", gs.garment_fsig("Demo", jid) != fsig, True)
        finally:
            gs.GARMENT_VERSION["clothing"] = 2

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
