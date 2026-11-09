#!/usr/bin/env python3
"""Base body phase 5, task 2: the clothing image chain — an outfit piece
flagged ``outfit_piece.own_mesh`` runs ``worn -> ghost -> cutout`` with its
own gates (app/core/garment_clothing.py, garment_gates.py worn_gate /
ghost_clothing_gate / hems_agree, garment_store.py, garment_images.py,
garments.py — plan docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md).

Usage:
    ./.venv/bin/python scripts/smoke_garment_clothing_images.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no server. The image
gates and ``run_edit_step`` are REAL; stubbed: the renderer (writes the planned
image, records the prompt), ``character.run_rembg`` (every pixel more than 2
away from grey 128), and for the chain run [6] ``garment_images.cut_out`` /
``garment_mesh.generate`` / ``garments._fit`` (the steps after ``ghost`` are
not under test). The gate limits are the calibrated constants of
``garment_gates`` (spike numbers in its "Clothing" block).

Fixture ``Demo`` (female, base-body pipeline). Item D = "Green Dress",
outfit piece, slots [top, bottom], covers [legs], own_mesh True, prompt
fragment "a knee-length green linen dress with short sleeves." — worn by Demo.

Geometry (the canvas of smoke_garment_ghost_pair.py), W 1024 x H 1200 on grey:
  BASE  head disc centre (512, 200) r 100 + torso cols [392, 632) rows
        [300, 1100) in skin (200, 160, 140) -> base mask rows 100 .. 1099:
        y0 100, Hb 999. Head zone rows < int(100 + 0.13 x 999) = 229.
        Skin sample rows int(100 + 0.04 x 999) = 139 .. int(100 + 0.10 x 999)
        = 199, middle row 169: head chord half-width sqrt(100² - 31²) = 95
        -> columns 464 .. 560, all skin -> sample (200, 160, 140).
        Morphology at H 1200: open round(2 x 1200/1536) = 2, close
        round(4 x 1200/1536) = 3, margin round(8 x 1200/1536) = 6 iterations.
  DRESS(top, bottom, x0, x1) = green (40, 90, 50), |ΔRGB| to skin
        (160 + 70 + 90) / 3 = 106.7 > 20, cols [x0, x1) rows [top, bottom].
        The standard dress: cols [380, 644) (12 px wider than the torso on
        each side), rows [320, 759], NECKLINE: rows [320, 350) cols [472, 552)
        not dress (the base neck shows in the worn view).
  WORN      = BASE + DRESS with the neckline open (skin there).
        garment region G = the dress minus the neckline: bbox [380, 320,
        643, 759]; nothing of the figure outside G changes -> outside_dRGB
        0.0, outside_xor 0.0, head_garment 0.0 -> ok.
        Neckline of G: centre column int((380 + 643) / 2) = 511, band
        round(0.03 x 263) = 8 -> columns 503 .. 519, first G row 350 ->
        depth 30 px = 0.03 Hb >= 0.012 -> a neckline.
  WORN_SHIFT = WORN with the whole picture moved 6 px right: the head and the
        legs move, so their outline changes outside G: XOR >= 0.015 -> refused
        ("body outline outside the garment changed").
  WORN_FACE  = WORN with the head (rows < 300) in (150, 120, 100):
        |ΔRGB| 43.3 > 20 -> the head joins G -> head_garment 1.0 > 0.05 ->
        refused ("head changed").
  WORN_NONE  = BASE: G empty -> garment_share 0.0 < 0.01 -> refused
        ("nothing put on").
  GHOST(bottom) = grey + the dress cols [380, 644) rows [320, bottom],
        neckline rows [320, 340) grey (open), rows [340, 350) cols [472, 552)
        the inside of the back (25, 60, 35): bbox [380, 320, 643, bottom] ->
        top_dy 0, centre_dx 0, w_ratio 1.0, skin_left 0, outside 0 (for
        bottom <= 759 + 6), neck_fill <= 10 / 30 rows ~ 0.33 <= 0.70 -> ok.
        hem_t = (bottom - 100) / 999.
  GHOST_CLOSED = GHOST(759) with the neckline filled in dress green: neck_fill
        1.0 > 0.70 -> refused ("neckline closed").
  GHOST_LEGS   = GHOST(759) + the torso rows [780, 1100) in skin: skin far
        outside G -> skin_left > 0.005 -> refused ("skin left in the image").
  GHOST_WIDE   = GHOST(759) with cols [356, 668): w_ratio 311 / 263 = 1.183
        > 1.05 -> refused ("garment width changed").
  GHOST_RAISED = GHOST(759) moved up 10 rows: top_dy -10 / 999 = -0.01001,
        |..| > 0.0055 -> refused ("garment top moved").
  HATTED = BASE with the head (rows < 300, figure pixels) in hat brown
        (90, 60, 40): |ΔRGB| 103.3 > 20 -> G = the head, everything else
        unchanged -> outside 0, head_garment 1.0.

[1] Store: GARMENT_VERSION["clothing"] 1; steps_for("clothing", "edit_chain")
    = (worn, ghost, cutout, mesh, fit); image_steps("clothing") = (worn,
    ghost, cutout), image_steps("hair") = (haired, ghost, cutout); a "worn"
    image path is images/D_F_worn_front.png. fsig_inputs of D =
    {prompt_fragment "a knee-length green linen dress with short sleeves",
    noun "green dress", slots [bottom, top], covers [legs], partially_covers
    [], pronouns [her, she]}; the fsig changes with the fragment AND with the
    item's name (fix round 1: the noun is a prompt input — a rename re-renders
    the ghost).
[2] Prompts (exact):
    worn front = "Keep the image exactly as it is. Only change their clothing:
      they now wear only a knee-length green linen dress with short sleeves."
    worn back  = base_body.DRESS_VIEW["back"] + " " + worn front
    ghost (both views) = "The same green dress alone, as if worn by an
      invisible person (ghost mannequin): no head, no arms, no hands, no legs,
      no feet, no skin; where the neck opening, sleeves and hem are, the
      inside of the garment is visible. Same position, size and framing,
      plain grey background."
    negatives: worn = DRESS_GARMENT_NEGATIVE minus "dress" -> "loose
      clothing, baggy, skirt, jacket, shoes, socks, hair"; ghost = that +
      ", person, skin, head, arms, hands, legs, feet, mannequin, hanger".
    An item without a fragment -> ValueError "has no prompt fragment".
[3] Gates as derived above (ok flags, the named reasons, the numbers of the
    good records); limits("clothing") names worn + ghost keys, limits() is
    still the hair table (keys fit/ghost/haired… untouched: [haired, ghost]).
    Fix round 1 (slot zones, garment_gates.SLOT_ZONES = {head: (head,)}):
    the clothing module's worn gate with item_id — Hat (slots [head]) on
    HATTED -> ok True, head_gated False, head_garment 1.0; the dress
    (slots [top, bottom]) on WORN_FACE -> refused "head changed", head_gated
    True; occupied_zones([neck]) = () (the neck is below the head zone),
    occupied_zones([head, neck]) = (head,).
[4] hems: front GHOST(759) hem_t (759 - 100) / 999 = 0.65966; back
    GHOST(733) hem_t 0.63363 -> |Δ| 0.02603 > 0.02 -> disagree, reason
    "garment ends at another height than in the back view: |Δ| 0.026 Hb >
    0.02 Hb (front 0.65966, back 0.63363)"; back GHOST(769) hem_t 0.66967
    -> |Δ| 0.01001 -> agree.
[5] run_edit_step worn front on D: render 1 = WORN_SHIFT (refused), render 2
    = WORN (accepted): final images/D_F_worn_front.png, gates.first.ok False,
    gates.second.ok True; the render call has occasion "garment_view", use
    case "garment_edit", character_loras False, postprocess False, the worn
    front prompt. A ghost + cutout front of the same fsig placed beforehand
    are gone after the forced re-render (``_drop_later`` follows the clothing
    order). cut_out on an all-grey accepted ghost -> ValueError "No garment
    found in the ghost front image".
[6] Chain run (garments.run_garment, back first):
    A: back ghost GHOST(733), every front ghost GHOST(759) -> renders worn b1,
       worn f1, ghost b1, ghost f1, ghost f2 (both fronts refused with the
       hems reason against the back) -> {ok False, step ghost, gates.view
       front}; the item's prompt_fragment is untouched (no description
       refresh for clothing).
    B: run again, the front GHOST(733) -> one render ghost f1, ok True, ran
       starts [ghost, cutout].
    garment_info(D): kind clothing, description = the fragment, steps keys
    [worn, ghost, cutout, mesh, fit].
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
INSIDE = (25, 60, 35)
W, H = 1024, 1200
FRAGMENT = "a knee-length green linen dress with short sleeves."
WORN_FRONT = ("Keep the image exactly as it is. Only change their clothing: they now wear only a knee-length "
              "green linen dress with short sleeves.")
GHOST_PROMPT = ("The same green dress alone, as if worn by an invisible person (ghost mannequin): no head, no "
                "arms, no hands, no legs, no feet, no skin; where the neck opening, sleeves and hem are, the "
                "inside of the garment is visible. Same position, size and framing, plain grey background.")
WORN_NEG = "loose clothing, baggy, skirt, jacket, shoes, socks, hair"
GHOST_NEG = WORN_NEG + ", person, skin, head, arms, hands, legs, feet, mannequin, hanger"
HEM_REASON = ("garment ends at another height than in the back view: |Δ| 0.026 Hb > 0.02 Hb "
              "(front 0.65966, back 0.63363)")


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


def dress(rgb, bottom=759, x0=380, x1=644, top=320, neckline="skin"):
    rgb[top:bottom + 1, x0:x1] = GREEN
    if neckline == "skin":
        rgb[top:top + 30, 472:552] = SKIN
    elif neckline == "ghost":
        rgb[top:top + 20, 472:552] = GREY
        rgb[top + 20:top + 30, 472:552] = INSIDE
    return rgb


def mask_of(rgb):
    return (np.abs(rgb.astype(np.int16) - 128) > 2).any(2)


BASE = figure(canvas())
WORN = dress(figure(canvas()))
WORN_SHIFT = np.roll(WORN, 6, axis=1)
WORN_FACE = WORN.copy()
WORN_FACE[:300][mask_of(WORN)[:300]] = (150, 120, 100)


def ghost(bottom=759, **kw):
    return dress(canvas(), bottom=bottom, neckline="ghost", **kw)


GHOST = ghost()
GHOST_CLOSED = dress(canvas(), neckline="none")
GHOST_LEGS = ghost()
GHOST_LEGS[780:1100, 392:632] = SKIN
GHOST_WIDE = ghost(x0=356, x1=668)
GHOST_RAISED = ghost(top=310, bottom=749)
HATTED = BASE.copy()
HATTED[:300][mask_of(BASE)[:300]] = (90, 60, 40)
SHORT, MATCHING = ghost(733), ghost(769)


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        arr = np.asarray(im.convert("RGB")).astype(np.int16)
    return png((mask_of(arr) * 255).astype(np.uint8))


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


def gates_part(gg, kept):
    print("[3] gates")
    worn = gg.worn_gate(BASE, mask_of(BASE), WORN, mask_of(WORN), view="front")
    check("worn ok", (worn["ok"], worn["outside_dRGB"], worn["outside_xor"], worn["head_garment"],
                      worn["garment_bbox"]), (True, 0.0, 0.0, 0.0, [380, 320, 643, 759]))
    check("worn share >= 0.01", worn["garment_share"] >= 0.01, True)

    def reason(record, text):
        return (record["ok"], any(text in r for r in record["reasons"]))

    shifted = gg.worn_gate(BASE, mask_of(BASE), WORN_SHIFT, mask_of(WORN_SHIFT), view="front")
    check("worn shifted refused", reason(shifted, "body outline outside the garment changed"), (False, True))
    face = gg.worn_gate(BASE, mask_of(BASE), WORN_FACE, mask_of(WORN_FACE), view="front")
    check("worn face refused", (reason(face, "head changed"), face["head_garment"]), ((False, True), 1.0))
    none = gg.worn_gate(BASE, mask_of(BASE), BASE, mask_of(BASE), view="front")
    check("worn nothing refused", (reason(none, "nothing put on"), none["garment_share"]), ((False, True), 0.0))

    region = gg.garment_region(BASE, mask_of(BASE), WORN, mask_of(WORN))
    neck = gg.neckline(region)
    check("neckline depth", neck["depth"], 30)
    check("skin sample", [float(v) for v in gg.skin_colour(BASE, mask_of(BASE))], [200.0, 160.0, 140.0])

    def ghost_gate(arr):
        return gg.ghost_clothing_gate(BASE, mask_of(BASE), region, arr, mask_of(arr), view="front")

    good = ghost_gate(GHOST)
    check("ghost ok", (good["ok"], good["top_dy"], good["centre_dx"], good["w_ratio"], good["skin_left"],
                       good["outside"], good["neckline_depth"], good["bottom"], good["hem_t"]),
          (True, 0.0, 0.0, 1.0, 0.0, 0.0, 0.03, 759, 0.65966))
    check("ghost neck_fill <= 0.4", good["neck_fill"] is not None and good["neck_fill"] <= 0.4, True)
    check("closed refused", reason(ghost_gate(GHOST_CLOSED), "neckline closed"), (False, True))
    check("legs refused", reason(ghost_gate(GHOST_LEGS), "skin left in the image"), (False, True))
    check("wide refused", reason(ghost_gate(GHOST_WIDE), "garment width changed"), (False, True))
    raised = ghost_gate(GHOST_RAISED)
    check("raised refused", (reason(raised, "garment top moved"), raised["top_dy"]), ((False, True), -0.01001))
    check("limits clothing", {k: sorted(v) for k, v in gg.limits("clothing").items()},
          {"worn": ["garment_share", "head_garment", "outside_dRGB", "outside_xor"],
           "ghost": ["centre_dx", "neck_fill", "outside", "skin_left", "top_dy", "w_ratio"]})
    check("limits hair unchanged", sorted(gg.limits()), ["ghost", "haired"])

    print("[4] hems")
    short, matching = ghost_gate(SHORT), ghost_gate(MATCHING)
    check("short/matching pass their gate", (short["ok"], matching["ok"]), (True, True))
    check("hem_t", (short["hem_t"], matching["hem_t"]), (0.63363, 0.66967))
    check("disagree", gg.hems_agree(good, short), False)
    check("reason", gg.hems_reason(good, short), HEM_REASON)
    check("agree", (gg.hems_agree(good, matching), gg.hems_reason(good, matching)), (True, None))
    check("unmeasured", (gg.hems_agree({}, good), gg.hems_reason({"reasons": ["x"]}, good)), (False, None))
    kept["good"] = good


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-clothing-") as tmp:
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

        from app.core import base_body, expression_regen, garment_assembly, garment_images, garment_mesh, garments
        from app.core import garment_gates as gg
        from app.core import garment_store as gs
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        charmod.run_rembg = rembg_stub

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        did = inventory.add_item(name="Green Dress", category="outfit_piece", prompt_fragment=FRAGMENT,
                                 outfit_piece={"slots": ["top", "bottom"], "covers": ["legs"],
                                               "outfit_types": ["casual"], "own_mesh": True})["id"]
        bare = inventory.add_item(name="Plain Shirt", category="outfit_piece", prompt_fragment="",
                                  outfit_piece={"slots": ["top"], "own_mesh": True})["id"]
        check("inventory dress", inventory.add_to_inventory("Demo", did), True)
        check("equip dress", inventory.equip_piece("Demo", did, source="smoke")["status"], "ok")
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png(BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))

        try:
            from app.core import garment_clothing
        except ImportError as e:
            check("garment_clothing importable", str(e), "importable")
            print("FAILED: " + ", ".join(FAILS))
            return 1

        print("[1] store")
        check("version", gs.GARMENT_VERSION.get("clothing"), 1)
        check("steps", gs.steps_for("clothing", gs.EDIT_CHAIN), ("worn", "ghost", "cutout", "mesh", "fit"))
        check("image steps", (gs.image_steps("clothing"), gs.image_steps("hair")),
              (("worn", "ghost", "cutout"), ("haired", "ghost", "cutout")))
        fsig = gs.garment_fsig("Demo", did)
        check("worn path", gs.garment_path("Demo", did, fsig, "image", step="worn", view="front").name,
              f"{did}_{fsig}_worn_front.png")
        check("fsig inputs", garment_clothing.fsig_inputs("Demo", inventory.get_item(did)),
              {"prompt_fragment": "a knee-length green linen dress with short sleeves",
               "noun": "green dress", "slots": ["bottom", "top"], "covers": ["legs"], "partially_covers": [],
               "pronouns": ["her", "she"]})
        inventory.update_item(did, {"name": "Summer Dress"})
        check("rename changes the fsig", gs.garment_fsig("Demo", did) != fsig, True)
        inventory.update_item(did, {"prompt_fragment": "a short green linen dress"})
        check("fsig follows the fragment", gs.garment_fsig("Demo", did) != fsig, True)
        inventory.update_item(did, {"name": "Green Dress", "prompt_fragment": FRAGMENT})
        check("fsig back", gs.garment_fsig("Demo", did), fsig)

        print("[2] prompts")
        from app.core.base_body import DRESS_VIEW
        check("worn front", garment_clothing.edit_prompt("Demo", "worn", "front", item_id=did),
              (WORN_FRONT, WORN_NEG))
        check("worn back", garment_clothing.edit_prompt("Demo", "worn", "back", item_id=did),
              (f"{DRESS_VIEW['back']} {WORN_FRONT}", WORN_NEG))
        check("ghost front", garment_clothing.edit_prompt("Demo", "ghost", "front", item_id=did),
              (GHOST_PROMPT, GHOST_NEG))
        check("ghost back", garment_clothing.edit_prompt("Demo", "ghost", "back", item_id=did)[0], GHOST_PROMPT)
        raises("no fragment", lambda: garment_clothing.edit_prompt("Demo", "worn", "front", item_id=bare),
               ValueError, "has no prompt fragment")

        kept = {}
        gates_part(gg, kept)
        print("[3b] slot zones")
        hat = inventory.add_item(name="Straw Hat", category="outfit_piece", prompt_fragment="a straw hat",
                                 outfit_piece={"slots": ["head"], "own_mesh": True})["id"]

        def module_worn(arr, item_id):
            return garment_clothing.gate("worn", "front", base_rgb=BASE, base_mask=mask_of(BASE),
                                         source_rgb=None, source_mask=None, edit_rgb=arr,
                                         edit_mask=mask_of(arr), item_id=item_id)

        hat_rec = module_worn(HATTED, hat)
        check("hat passes worn", (hat_rec["ok"], hat_rec["head_gated"], hat_rec["head_garment"],
                                  hat_rec["outside_dRGB"], hat_rec["outside_xor"]), (True, False, 1.0, 0.0, 0.0))
        face = module_worn(WORN_FACE, did)
        check("dress changing the head refused", (face["ok"], face["head_gated"],
                                                  any("head changed" in r for r in face["reasons"])),
              (False, True, True))
        check("occupied zones", (gg.occupied_zones(["neck"]), gg.occupied_zones(["head", "neck"]),
                                 gg.occupied_zones(["top", "bottom"])), ((), ("head",), ()))

        print("[5] run_edit_step worn front")
        renders, prompts = [], {}
        plan = {}

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            key = f"{g['step']} {g['view'][0]}{g['attempt']}"
            renders.append(key)
            prompts[key] = kw
            queue = plan.get((g["step"], g["view"])) or []
            arr = queue.pop(0) if queue else (WORN if g["step"] == "worn" else GHOST)
            side = kw["override_width"]
            out_canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
            dy, dx = (out_canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
            out_canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(out_canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g["attempt"], **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder
        later = [gs.garment_path("Demo", did, fsig, "image", step=s, view="front") for s in ("ghost", "cutout")]
        for path in later:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png(GHOST))
            gs.write_record(path.with_suffix(".json"), {"accepted": True})
        plan[("worn", "front")] = [WORN_SHIFT, WORN]
        final = garment_images.run_edit_step("Demo", did, fsig, "worn", "front", force=True)
        check("final", final.name, f"{did}_{fsig}_worn_front.png")
        record = gs.read_record(final.with_suffix(".json"))
        check("accepted at attempt 2", (record.get("accepted"), record.get("attempt"),
                                        record["gates"]["first"]["ok"], record["gates"]["second"]["ok"]),
              (True, 2, False, True))
        kw = prompts["worn f1"]
        check("render call", (kw["occasion"], kw["image_use_case"], kw["character_loras"], kw["postprocess"],
                              kw["bare_prompt"], kw["extra_negative"]),
              ("garment_view", "garment_edit", False, False, WORN_FRONT, WORN_NEG))
        check("later steps dropped", [p.exists() for p in later], [False, False])
        ghost_final = gs.garment_path("Demo", did, fsig, "image", step="ghost", view="front")
        ghost_final.write_bytes(png(canvas()))
        gs.write_record(ghost_final.with_suffix(".json"), {"accepted": True})
        raises("cut_out empty", lambda: garment_images.cut_out("Demo", did, fsig, "front"), ValueError,
               "No garment found in the ghost front image")
        for step in ("worn", "ghost"):
            for v in ("front", "back"):
                p = gs.garment_path("Demo", did, fsig, "image", step=step, view=v)
                p.unlink(missing_ok=True)
                p.with_suffix(".json").unlink(missing_ok=True)

        print("[6] chain run, back first")

        def cut_out(character_name, item_id, fsig_, view, *, force=False):
            path = gs.garment_path(character_name, item_id, fsig_, "image", step="cutout", view=view)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"cutout")
            gs.write_record(path.with_suffix(".json"), {"accepted": True})
            return path

        garment_images.cut_out = cut_out
        garment_mesh.generate = lambda *a, **k: None
        garments._fit = lambda *a, **k: None
        del renders[:]
        plan.clear()
        plan[("ghost", "back")] = [SHORT]
        plan[("ghost", "front")] = [GHOST, GHOST, GHOST]
        res = garments.run_garment("Demo", did)
        check("A renders", renders, ["worn b1", "worn f1", "ghost b1", "ghost f1", "ghost f2"])
        gates = res.get("gates") or {}
        check("A refused at ghost front", (res.get("ok"), res.get("step"), gates.get("view")),
              (False, "ghost", "front"))
        check("A reasons", [a.get("reasons") for a in gates.get("attempts") or []], [[HEM_REASON], [HEM_REASON]])
        check("A back prompt", prompts["worn b1"]["bare_prompt"], f"{DRESS_VIEW['back']} {WORN_FRONT}")
        check("A ghost prompt", prompts["ghost f1"]["bare_prompt"], GHOST_PROMPT)
        check("A fragment untouched", inventory.get_item(did).get("prompt_fragment"), FRAGMENT)
        del renders[:]
        plan[("ghost", "front")] = [SHORT]
        res = garments.run_garment("Demo", did)
        check("B renders", renders, ["ghost f1"])
        check("B ok", (res.get("ok"), (res.get("ran") or [])[:2]), (True, ["ghost", "cutout"]))
        info = garments.garment_info("Demo", did)
        check("info", (info["kind"], info["description"], list(info["steps"])),
              ("clothing", "a knee-length green linen dress with short sleeves",
               ["worn", "ghost", "cutout", "mesh", "fit"]))

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
