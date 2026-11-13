#!/usr/bin/env python3
"""Base body phase 5, task 2: the clothing image chain — an outfit piece
in mode own_mesh (``outfit_piece.mesh_mode``) runs ``worn -> ghost -> cutout`` with its
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
outfit piece, slots [top, bottom], covers [legs], mode own_mesh, prompt
fragment "a knee-length green linen dress with short sleeves." — worn by Demo.

Geometry (the canvas of the former smoke_garment_ghost_pair.py), W 1024 x H 1200 on grey:
  BASE  head disc centre (512, 200) r 100 + torso cols [392, 632) rows
        [300, 1100) in skin (200, 160, 140) -> base mask rows 100 .. 1099:
        y0 100, Hb 999. Head zone rows < int(100 + 0.13 x 999) = 229 (the
        chin rule of ``head_zone``: the disc narrows down to the shoulder
        row, no neck — the neck rule: scripts/smoke_garment_worn_regate.py).
        Skin sample (the thighs, ghost gate version 2) rows int(100 + 0.60
        x 999) = 699 .. int(100 + 0.66 x 999) = 759, every figure pixel
        there is torso skin -> sample (200, 160, 140).
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
  WORN_NONE  = BASE: G empty -> garment_share 0.0 < 0.002 -> refused
        ("nothing put on").
  GHOST(bottom) = grey + the dress cols [380, 644) rows [320, bottom],
        neckline rows [320, 340) grey (open), rows [340, 350) cols [472, 552)
        the inside of the back (25, 60, 35): bbox [380, 320, 643, bottom] ->
        top_dy 0, centre_dx 0, w_ratio 1.0, skin_left 0, outside 0 (for
        bottom <= 759 + 6), neck_fill <= 10 / 30 rows ~ 0.33 (reported) -> ok.
        hem_t = (bottom - 100) / 999.
  GHOST_CLOSED = GHOST(759) with the neckline filled in dress green: neck_fill
        1.0, reported but NOT gated (the 0.70 gate was retired 2026-11-09: a
        ghost refused at 0.832 still meshed into an open neckline) -> ok,
        no reasons; outside stays 0 (the notch is left out of it).
  GHOST_LEGS   = GHOST(759) + the torso rows [780, 1100) in skin: skin far
        outside G -> skin_left > 0.005 -> refused ("skin left in the image").
  GHOST_WIDE   = GHOST(759) with cols [356, 668): w_ratio 311 / 263 = 1.183,
        inside the widened [0.80, 1.25] (ghost gate version 2), but cols
        356..373 and 650..667 lie beyond G grown by 6 (374..649): 2 x 18 x
        440 rows = 15840 px over G's area 264 x 440 - 30 x 80 = 113760 (less
        a few cut corners) -> outside_near 0.139. Ghost gate version 3
        (gate audit): ``outside`` counts only the parts more than 0.02 x
        999 = 19.98 px from G — cols 356..360 and 663..667 (380 - c >= 20,
        c - 643 >= 20), 5 x 440 = 2200 px each, two parts -> 2200 / 113760
        = 0.019 <= 0.05 -> ACCEPTED, the rim a warning ("garment rim beyond
        the worn piece"); not refused for its width either.
  GHOST_NARROW = GHOST(759) with cols [380, 560) — a cut-off piece: w_ratio
        (559 - 380) / (643 - 380) = 0.681 < 0.80 -> refused ("garment width
        changed"); its centre offset ((380 + 559) - (380 + 643)) / 2 / 999 =
        -0.04204 only recorded ("garment centre moved" in ``warnings``).
  GHOST_RAISED = GHOST(759) moved up 10 rows: top_dy -10 / 999 = -0.01001,
        |..| > 0.0055 -> RECORDED ("garment top moved" in ``warnings``),
        not refused; rows 310..313 lie beyond the 6-row margin, less its
        open neckline cols [472, 552): 4 x (264 - 80) = 736 px, plus the few
        pixels above G's cut top corners -> outside_near 0.0066; nothing
        19.98 px away -> outside 0.0 -> ok.
  HATTED = BASE with the head (rows < 300, figure pixels) in hat brown
        (90, 60, 40): |ΔRGB| 103.3 > 20 -> G = the head, everything else
        unchanged -> outside 0, head_garment 1.0.

[1] Store: GARMENT_VERSION["clothing"] 2 (the drafted worn back); steps_for("clothing", "edit_chain")
    = (worn, ghost, cutout, mesh, fit); image_steps("clothing") = (worn,
    ghost, cutout), image_steps("hair") = () (the hair edit chain is gone,
    hair-from-body spec 2026-11-11 Task 2); a "worn"
    image path is images/D_F_worn_front.png. fsig_inputs of D =
    {prompt_fragment "a knee-length green linen dress with short sleeves",
    noun "green dress", slots [bottom, top], covers [legs], partially_covers
    [], pronouns [her, she]}; the fsig changes with the fragment AND with the
    item's name (fix round 1: the noun is a prompt input — a rename re-renders
    the ghost).
[2] Prompts (exact):
    worn front = "Keep the image exactly as it is. Only change their clothing:
      they now wear only a knee-length green linen dress with short sleeves."
    worn back  = no edit prompt: ValueError "drafted from the worn front"
      (the draft + fit back: scripts/smoke_garment_clothing_back.py)
    ghost front (the dress has a top slot: no waistband piece) = GHOST:
      "The same green dress in exactly the same position, size, width and
      framing, keeping its worn three-dimensional shape as if on an
      invisible body (ghost mannequin product photo): the person is removed,
      the inside of the garment is visible at the neck opening, sleeves and
      hem, plain grey background."
    ghost back (ruling 13e: every back says GHOST_KEEP; not a waistband
      piece -> sleeves, neck opening; Task 11e: the back names its view) =
      "Keep the green dress exactly as it is, seen from behind, the back
      view stays a back view: the same position, outer outline, width and
      framing, the sleeves at exactly the same angle as in the image, the
      same background. Remove the person completely so the green dress
      keeps its worn three-dimensional shape on an invisible body (ghost
      mannequin product photo); the inside is visible at the neck opening,
      sleeves and hem."
    A waistband piece ("Grey Trousers", slots [bottom]) says GHOST_KEEP on
      both views, the legs and the waistband: front "Keep the grey trousers
      exactly as it is, seen from the front: … the legs apart at exactly the
      same angle as in the image, … the inside is visible at the waistband
      and the leg openings."; the back the same with "seen from behind, the
      back view stays a back view".
    negatives: worn = DRESS_GARMENT_NEGATIVE minus "dress" -> "loose
      clothing, baggy, skirt, jacket, shoes, socks, hair"; ghost = that +
      ", person, skin, head, arms, hands, legs, feet, mannequin, hanger".
    An item without a fragment -> ValueError "has no prompt fragment".
[3] Gates as derived above (ok flags, the named reasons, the numbers of the
    good records); limits("clothing") names worn + ghost keys (worn without
    outside_dRGB since gate version 2 — recorded, never refused; ghost incl.
    the registration caps reg_shift / reg_scale,
    scripts/smoke_garment_ghost_registration.py), limits() defaults to the
    clothing table, limits("hair") is a ValueError (no image chain);
    ghost without top_dy / centre_dx since ghost gate version 2 (recorded).
    Fix round 1 (slot zones, garment_gates.SLOT_ZONES = {head: (head,)}):
    the clothing module's worn gate with item_id — Hat (slots [head]) on
    HATTED -> ok True, head_gated False, head_garment 1.0; the dress
    (slots [top, bottom]) on WORN_FACE -> refused "head changed", head_gated
    True; occupied_zones([neck]) = () (the neck is below the head zone),
    occupied_zones([head, neck]) = (head,).
    Outline drift (2026-11-10, Black Stilettos: the outline XOR is an area
    share, a shoe leaves the whole figure's outline exposed). SHOE fixture
    on the same canvas: FIG = skin cols [452, 572) rows [100, 1100) (area
    120 x 1000 = 120000, y0 100, Hb 999), SHOE = black (20, 20, 20) cols
    [440, 584) rows [1040, 1112) (12 px wider than the leg on each side, so
    the opening's cut corners — 3 px each, cross structure, 2 iterations —
    lie off the figure). G = the shoe; grown 6 iterations: its top row 1040
    spans cols [442, 581] -> rows >= 1034 cover the figure's columns. Base
    outline (mask minus its erosion) outside the grown G: the top row 100
    (120 px) + the left and right columns rows 101..1033 (933 each) =
    outside_outline 1986. outside_xor_limit = max(0.015, 1.5 x 1200/1536 x
    1986 / 120000) = max(0.015, 0.019395) = 0.0194 — worn gate version 3
    (gate audit: an edit's drift limit 2.0 px): max(0.015, 2.0 x 1200/1536 x
    1986 / 120000) = max(0.015, 0.025859) = 0.0259.
      SHOE_ON: worn = FIG + SHOE -> outside_xor 0.0, drift 0.0, ok.
      SHOE_SHIFT1: the whole worn picture 1 px right -> XOR outside the grown
        G = rows 100..1033 x (col 452 + col 572) = 1868 px = 0.0156 — over
        the old 0.015, under 0.0259 -> ok; drift 1868 / 1986 x 1536/1200 =
        1.20 px.
      SHOE_SHIFT2: 2 px right -> 3736 px = 0.0311 >= 0.0259, drift 2.41 px
        -> refused ("body outline outside the garment changed").
      SHOE_TORSO: rows [300, 700) of the figure moved 4 px right (the shoe
        stays) -> 2 x 4 x 400 = 3200 px = 0.0267 >= 0.0259, drift 2.06 px
        -> refused (the 4 px strip outside the base is no garment: the
        opening removes it).
      The dress (WORN_SHIFT, 6 px) keeps being refused; limits("clothing")
      worn outside_xor has record_key "outside_xor_limit".
[4] hems: front GHOST(759) hem_t (759 - 100) / 999 = 0.65966; back
    GHOST(733) hem_t 0.63363 -> |Δ| 0.02603 > 0.02 -> disagree, reason
    "garment ends at another height than in the back view: |Δ| 0.026 Hb >
    0.02 Hb (front 0.65966, back 0.63363)"; back GHOST(769) hem_t 0.66967
    -> |Δ| 0.01001 -> agree.
    Ruling A17 (ghost gate version 4) changed this block: the centre hem
    ``hem_c`` (± 40 columns around the base's shoulder-row centre 512: every
    band column's longest run ends at the bottom row, the neckline rows only
    start it later) equals hem_t here, and the region's ``worn_hem_c`` is
    0.65966. So GHOST(733) is now REFUSED by its own gate — "garment ends at
    another height than the worn piece: |Δ| 0.026 Hb > 0.02 Hb (ghost
    0.63363, worn 0.65966)" — and as a front against the worn back
    (``worn_hems_reason``) "… (front 0.63363, worn back 0.65966)";
    GHOST(769) passes both (0.01001). The ghost pair rule above is unchanged.
[5] run_edit_step worn front on D: render 1 = WORN_SHIFT (refused), render 2
    = WORN (accepted): final images/D_F_worn_front.png, gates.first.ok False,
    gates.second.ok True; the render call has occasion "garment_view", use
    case "garment_edit", character_loras False, postprocess False, the worn
    front prompt. A ghost + cutout front of the same fsig placed beforehand
    are gone after the forced re-render (``_drop_later`` follows the clothing
    order). cut_out on an all-grey accepted ghost -> ValueError "No garment
    found in the ghost front image".
[6] Chain run (garments.run_garment; worn: the front first, its back drafted
    from it — "worn bd1" = the draft of attempt 1, composited onto the base
    back on the CPU (Task 11g: no fit render; the composite of WORN onto BASE
    passes); ghost: the back first):
    A (rewritten for Ruling A17 — a back like GHOST(733) is refused by its
       own gate now, so it can no longer refuse every front): back ghosts
       GHOST(733), GHOST(769), front ghosts GHOST(733) twice -> renders worn
       f1, worn bd1, ghost b1 (refused for its hem against the worn back),
       ghost b2 (accepted), ghost f1, ghost f2 (both refused for their hem
       against the worn front AND the worn back, the reasons above); the
       draft's prompt names the fragment
       ("wearing only a knee-length green linen dress with short sleeves
       exactly as on the person in the reference image"), occasion
       outfit_back_draft; the accepted worn back records fit "composite" -> {ok False, step ghost, gates.view
       front}; the item's prompt_fragment is untouched (no description
       refresh for clothing).
    B: run again, the front GHOST(759) (0 from both worn hems, 0.01001 from
       the ghost back GHOST(769)) -> one render ghost f1, ok True, ran starts
       [ghost, cutout].
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
GHOST_PROMPT = ("The same green dress in exactly the same position, size, width and framing, keeping its worn "
                "three-dimensional shape as if on an invisible body (ghost mannequin product photo): the person "
                "is removed, the inside of the garment is visible at the neck opening, sleeves and hem, plain "
                "grey background.")
GHOST_BACK_PROMPT = ("Keep the green dress exactly as it is, seen from behind, the back view stays a back view: "
                     "the same position, outer outline, "
                     "width and framing, the sleeves at exactly the same angle as in the image, the same background. "
                     "Remove the person completely so the green dress keeps its worn three-dimensional shape on an "
                     "invisible body (ghost mannequin product photo); the inside is visible at the neck opening, "
                     "sleeves and hem.")


def trousers_ghost(side):
    return ("Keep the grey trousers exactly as it is, " + side + ": the same position, outer outline, width and "
            "framing, the legs apart at exactly the same angle as in the image, the same background. Remove the "
            "person completely so the grey trousers keeps its worn three-dimensional shape on an invisible body "
            "(ghost mannequin product photo); the inside is visible at the waistband and the leg openings.")


_OLD_GHOST_PROMPT = ("The same green dress alone, as if worn by an invisible person (ghost mannequin): no head, no "
                "arms, no hands, no legs, no feet, no skin; where the neck opening, sleeves and hem are, the "
                "inside of the garment is visible. Same position, size and framing, plain grey background.")
WORN_NEG = "loose clothing, baggy, skirt, jacket, shoes, socks, hair"
GHOST_NEG = WORN_NEG + ", person, skin, head, arms, hands, legs, feet, mannequin, hanger"
HEM_REASON = ("garment ends at another height than in the back view: |Δ| 0.026 Hb > 0.02 Hb "
              "(front 0.65966, back 0.63363)")
#: Ruling A17: GHOST(733) against the worn piece (its gate) and as a front against the worn back.
SHORT_GATE_REASON = ("garment ends at another height than the worn piece: |Δ| 0.026 Hb > 0.02 Hb "
                     "(ghost 0.63363, worn 0.65966)")
SHORT_WORN_BACK_REASON = ("garment ends at another height than in the back view: |Δ| 0.026 Hb > 0.02 Hb "
                          "(front 0.63363, worn back 0.65966)")


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


SHOE_BLACK = (20, 20, 20)


def shoe_figure(shoe=True):
    rgb = canvas()
    rgb[100:1100, 452:572] = SKIN
    if shoe:
        rgb[1040:1112, 440:584] = SHOE_BLACK
    return rgb


SHOE_BASE = shoe_figure(shoe=False)
SHOE_ON = shoe_figure()
SHOE_SHIFT1 = np.roll(SHOE_ON, 1, axis=1)
SHOE_SHIFT2 = np.roll(SHOE_ON, 2, axis=1)
SHOE_TORSO = SHOE_ON.copy()
SHOE_TORSO[300:700] = GREY
SHOE_TORSO[300:700, 456:576] = SKIN


def ghost(bottom=759, **kw):
    return dress(canvas(), bottom=bottom, neckline="ghost", **kw)


GHOST = ghost()
GHOST_CLOSED = dress(canvas(), neckline="none")
GHOST_LEGS = ghost()
GHOST_LEGS[780:1100, 392:632] = SKIN
GHOST_WIDE = ghost(x0=356, x1=668)
GHOST_NARROW = ghost(x1=560)
GHOST_RAISED = ghost(top=310, bottom=749)
HATTED = BASE.copy()
HATTED[:300][mask_of(BASE)[:300]] = (90, 60, 40)
SHORT, MATCHING = ghost(733), ghost(769)


def rembg_stub(data, model="u2net", **kwargs):
    """The mask (``only_mask``) or the RGBA cut-out (the fit's ``cut_out``)."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB"))
    mask = (mask_of(rgb.astype(np.int16)) * 255).astype(np.uint8)
    if kwargs.get("only_mask"):
        return png(mask)
    return png(np.dstack([rgb, mask]))


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

    def shoe(arr):
        rec = gg.worn_gate(SHOE_BASE, mask_of(SHOE_BASE), arr, mask_of(arr), view="front")
        return (rec["ok"], rec["outside_xor"], rec["outside_outline"], rec["outside_xor_limit"],
                rec["outside_drift_px"], rec["outside_dRGB"])
    check("shoe on", shoe(SHOE_ON), (True, 0.0, 1986, 0.0259, 0.0, 0.0))
    check("shoe, figure 1 px right: under the drift limit", shoe(SHOE_SHIFT1),
          (True, 0.0156, 1986, 0.0259, 1.2, 0.0))
    check("shoe, figure 2 px right: refused", shoe(SHOE_SHIFT2), (False, 0.0311, 1986, 0.0259, 2.41, 0.0))
    check("shoe, torso 4 px right: refused", shoe(SHOE_TORSO), (False, 0.0267, 1986, 0.0259, 2.06, 0.0))
    torso = gg.worn_gate(SHOE_BASE, mask_of(SHOE_BASE), SHOE_TORSO, mask_of(SHOE_TORSO), view="front")
    check("torso reason", torso["reasons"],
          ["body outline outside the garment changed: XOR 0.0267 >= 0.0259 (drift 2.06 px >= 2.0 px)"])
    check("limits: own record limit", gg.limits("clothing")["worn"]["outside_xor"].get("record_key"),
          "outside_xor_limit")

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
    closed = ghost_gate(GHOST_CLOSED)
    check("closed neckline reported, not refused", (closed["ok"], closed["reasons"], closed["neck_fill"],
                                                     closed["outside"]), (True, [], 1.0, 0.0))
    check("legs refused", reason(ghost_gate(GHOST_LEGS), "skin left in the image"), (False, True))
    wide = ghost_gate(GHOST_WIDE)
    check("wide: accepted, its rim a warning (ghost gate version 3)",
          (wide["ok"], wide["w_ratio"], round(wide["outside_near"], 3), round(wide["outside"], 3),
           any("garment rim beyond the worn piece" in x for x in wide["warnings"])), (True, 1.183, 0.139, 0.019, True))
    narrow = ghost_gate(GHOST_NARROW)
    check("narrow (cut off) refused for width", (reason(narrow, "garment width changed"), narrow["w_ratio"],
                                                 narrow["centre_dx"],
                                                 any("garment centre moved" in x for x in narrow["warnings"])),
          ((False, True), 0.681, -0.04204, True))
    raised = ghost_gate(GHOST_RAISED)
    check("raised recorded, accepted", (raised["ok"], raised["top_dy"], round(raised["outside_near"], 4),
                                        raised["outside"], [x.split(":")[0] for x in raised["warnings"]],
                                        raised["gate_version"]),
          (True, -0.01001, 0.0066, 0.0, ["garment top moved"], gg.GHOST_GATE_VERSION))
    check("limits clothing", {k: sorted(v) for k, v in gg.limits("clothing").items()},
          {"worn": ["garment_share", "head_garment", "outside_xor"],
           "ghost": ["outside", "reg_scale", "reg_shift", "skin_left", "w_ratio"]})
    check("limits() = clothing", gg.limits(), gg.limits("clothing"))
    try:
        gg.limits("hair")
        check("limits hair refused", "no error", "ValueError")
    except ValueError:
        check("limits hair refused", "ValueError", "ValueError")

    print("[4] hems")
    short, matching = ghost_gate(SHORT), ghost_gate(MATCHING)
    check("short refused for its hem, matching passes (A17)", (short["ok"], short["reasons"], matching["ok"]),
          (False, [SHORT_GATE_REASON], True))
    check("hem_t / hem_c", (short["hem_t"], matching["hem_t"], short["hem_c"], matching["hem_c"], good["hem_c"],
                            good["worn_hem_c"]), (0.63363, 0.66967, 0.63363, 0.66967, 0.65966, 0.65966))
    check("disagree", gg.hems_agree(good, short), False)
    check("reason", gg.hems_reason(good, short), HEM_REASON)
    check("front vs the worn back (A17 b)", (gg.worn_hems_reason(short, good), gg.worn_hems_reason(matching, good)),
          (SHORT_WORN_BACK_REASON, None))
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
        # A chain's piece_ready asks the character's Build (plan 2026-11-12-unified-worn-pieces Task 8):
        # recorded, so no automatic Build writes into the world while this smoke measures or cleans up.
        sys.path.insert(0, str(ROOT / "scripts"))
        from _figure_build_fixtures import record_requests
        record_requests()
        charmod.run_rembg = rembg_stub

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        did = inventory.add_item(name="Green Dress", category="outfit_piece", prompt_fragment=FRAGMENT,
                                 outfit_piece={"slots": ["top", "bottom"], "covers": ["legs"],
                                               "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
        bare = inventory.add_item(name="Plain Shirt", category="outfit_piece", prompt_fragment="",
                                  outfit_piece={"slots": ["top"], "mesh_mode": "own_mesh"})["id"]
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
        check("version", gs.GARMENT_VERSION.get("clothing"), 2)
        check("steps", gs.steps_for("clothing", gs.EDIT_CHAIN), ("worn", "ghost", "cutout", "mesh", "fit"))
        check("image steps", (gs.image_steps("clothing"), gs.image_steps("hair")),
              (("worn", "ghost", "cutout"), ()))
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
        check("worn front", garment_clothing.edit_prompt("Demo", "worn", "front", item_id=did),
              (WORN_FRONT, WORN_NEG))
        raises("worn back is no edit", lambda: garment_clothing.edit_prompt("Demo", "worn", "back", item_id=did),
               ValueError, "drafted from the worn front")
        check("ghost front", garment_clothing.edit_prompt("Demo", "ghost", "front", item_id=did),
              (GHOST_PROMPT, GHOST_NEG))
        check("ghost back", garment_clothing.edit_prompt("Demo", "ghost", "back", item_id=did)[0], GHOST_BACK_PROMPT)
        tid = inventory.add_item(name="Grey Trousers", category="outfit_piece", prompt_fragment="grey trousers",
                                 outfit_piece={"slots": ["bottom"]})["id"]
        check("trousers ghost front", garment_clothing.edit_prompt("Demo", "ghost", "front", item_id=tid)[0],
              trousers_ghost("seen from the front"))
        check("trousers ghost back", garment_clothing.edit_prompt("Demo", "ghost", "back", item_id=tid)[0],
              trousers_ghost("seen from behind, the back view stays a back view"))
        raises("no fragment", lambda: garment_clothing.edit_prompt("Demo", "worn", "front", item_id=bare),
               ValueError, "has no prompt fragment")

        kept = {}
        gates_part(gg, kept)
        print("[3b] slot zones")
        hat = inventory.add_item(name="Straw Hat", category="outfit_piece", prompt_fragment="a straw hat",
                                 outfit_piece={"slots": ["head"], "mesh_mode": "own_mesh"})["id"]

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
            key = (f"{g['step']} {g['view'][0]}d{g.get('attempt')}" if g.get("stage") == "draft"
                   else f"{g['step']} {g['view'][0]}{g.get('attempt', 'd')}")
            renders.append(key)
            prompts[key] = kw
            queue = [] if g.get("stage") == "draft" else plan.get((g["step"], g["view"])) or []
            arr = queue.pop(0) if queue else (WORN if g["step"] == "worn" else GHOST)
            side = kw["override_width"]
            out_canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
            dy, dx = (out_canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
            if g.get("stage") == "draft":
                out_canvas = arr  # the draft: a fresh render, its own frame
            else:
                out_canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(out_canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g.get("attempt", 0),
                                                            **kw["sidecar_extra"]}))
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
        plan[("ghost", "back")] = [SHORT, MATCHING]
        plan[("ghost", "front")] = [SHORT, SHORT]
        res = garments.run_garment("Demo", did)
        check("A renders", renders, ["worn f1", "worn bd1", "ghost b1", "ghost b2", "ghost f1", "ghost f2"])
        gates = res.get("gates") or {}
        check("A refused at ghost front", (res.get("ok"), res.get("step"), gates.get("view")),
              (False, "ghost", "front"))
        check("A reasons", [a.get("reasons") for a in gates.get("attempts") or []],
              [[SHORT_GATE_REASON, SHORT_WORN_BACK_REASON]] * 2)
        back_record = gs.read_record(gs.garment_path("Demo", did, fsig, "image", step="ghost", view="back")
                                     .with_suffix(".json"))
        check("A back: attempt 1 refused for its hem, attempt 2 accepted",
              (back_record.get("attempt"), (back_record.get("gates") or {}).get("first", {}).get("reasons")),
              (2, [SHORT_GATE_REASON]))
        check("A back draft prompt names the fragment",
              ("wearing only a knee-length green linen dress with short sleeves exactly as on the person in the "
               "reference image" in prompts["worn bd1"]["bare_prompt"], prompts["worn bd1"]["occasion"]),
              (True, "outfit_back_draft"))
        worn_back = gs.read_record(gs.garment_path("Demo", did, fsig, "image", step="worn", view="back")
                                   .with_suffix(".json"))
        check("A worn back: the composite", (worn_back.get("accepted"), worn_back.get("fit"),
                                             (worn_back.get("composite") or {}).get("ok")), (True, "composite", True))
        check("A ghost prompt", prompts["ghost f1"]["bare_prompt"], GHOST_PROMPT)
        check("A fragment untouched", inventory.get_item(did).get("prompt_fragment"), FRAGMENT)
        del renders[:]
        plan[("ghost", "front")] = [GHOST]
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
