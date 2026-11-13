#!/usr/bin/env python3
"""Ruling A17 (2026-11-13): the ghost hems are measured against the WORN
views, a stale ghost back is rendered again, and a closable piece's ghost
front keeps the worn view's open / closed look (app/core/garment_gates.py
``centre_hem`` / ``gap_rows`` / ``centre_gap`` / ``ghost_clothing_gate`` /
``worn_hems_reason`` / ``hem_deviation`` / ``hems_agree``,
app/core/garment_clothing.py ``gate`` / ``pair_reason`` / ``pair_redo`` /
``REGATE_ACCEPTED_STEPS``, app/core/garment_images.py ``regate_accepted`` /
``stale_accepted``, app/core/garments.py ``_regate_accepted`` / the pair
repair of ``_run_locked``).

The case (Kai's leather jacket, item_555a7a01): the ghost BACK was accepted
hanging below the worn back's hem with a dark underside bulge (its area,
0.006 of the piece beyond 0.02 Hb, passed the 0.05 limit), every ghost
front was then measured against that back and refused, and a restart
reused the stored back — refused forever.

Usage:
    ./.venv/bin/python scripts/smoke_ghost_hem_reference.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server. The gates,
``run_edit_step`` and the chain are REAL; stubbed: the renderer (writes the
planned image), ``character.run_rembg`` (every pixel more than 2 away from
grey 128), ``garment_images.cut_out`` / ``garment_mesh.generate`` /
``garments._fit`` (after the ghost, not under test). Needs git for [6].

Geometry, W 1024 x H 1200 on grey 128 (the canvas of
smoke_garment_clothing_images.py):
  BASE  head disc centre (512, 200) r 100 + torso cols [392, 632) rows
        [300, 1100) in skin (200, 160, 140): y0 100, Hb 999. Shoulder row
        int(100 + 0.19 x 999) = 289: the disc there spans |x - 512| <= 45
        (45² = 2025 <= 100² - 89² = 2079 < 46²) -> cols 467..557, centre
        512. Hem band ± round(0.04 x 999) = 40 -> cols 472..552; gap band
        ± round(0.05 x 999) = 50 -> cols 462..562, panels 51..149 px off
        the centre (0.15 x 999 = 149.85).
  JACKET(bottom) brown (60, 45, 35) (luminance 46.667; |ΔRGB| to skin 120),
        cols [380, 644) rows [320, bottom]. WORN = BASE + JACKET(759): the
        region's band columns run rows 320..759 -> worn_hem_c (759 - 100) /
        999 = 0.65966. The worn back is the CPU composite of the stub draft
        (= WORN) onto the base back (= BASE): the same rows -> 0.65966.
  Ghosts (grey canvas, every band column one run from row 320):
        GOOD        JACKET(759)  hem_c 0.65966   Δ worn 0
        FRONT_EARLY JACKET(752)  hem_c 0.65265   Δ 7 / 999 = 0.00701
        BACK_LATE   JACKET(775)  hem_c 0.67568   Δ 16 / 999 = 0.01602
        FRONT_LATE  JACKET(778)  hem_c 0.67868   Δ 0.01902
        BACK_EARLY  JACKET(745)  hem_c 0.64565   Δ 0.01401
        BULGE       GOOD + the dark underside (15, 12, 10) cols [452, 572)
                    rows [760, 790] (Kai's bulge): hem_c (790 - 100) / 999 =
                    0.69069, Δ 31 / 999 = 0.03103.
        NARROW      the jacket cols [380, 560): 179 px wide against a worn
                    region of about 250..263 -> w_ratio < 0.72 < 0.80 (refused
                    for its width, the rule of gate version 2), hem 0.65966.
  WORN_BELLY = WORN + a re-shaded belly (225, 185, 165) cols [452, 572) rows
        [760, 840): |ΔRGB| 25 to the base skin -> garment region (> 20), but
        within SKIN_DRGB 30 of the skin sample (the thighs, (200, 160, 140))
        -> left out of the worn hem: 0.65966; with it the band columns run
        to row 839 -> (839 - 100) / 999 = 0.73974.
  WORN_OPEN_WIDE = WORN with cols [432, 592) rows [340, 760) in skin (worn
        open): every band column holds only the collar rows 320..339 (20 rows
        < 0.25 x 440, the region's height) -> no worn hem (None).

[1] Hem against the worn piece (a): BULGE as the BACK -> refused, its only
    reason "garment ends at another height than the worn piece: |Δ| 0.031
    Hb > 0.02 Hb (ghost 0.69069, worn 0.65966)". Its area does not catch it:
    beyond the 6 px margin rows 766..790 x 120 = 3000 px (outside_near
    3000 / ~116160 = 0.0258), farther than 0.02 x 999 = 19.98 px rows
    779..790 x 120 = 1440 px -> outside 0.0124 (± 0.0005) <= 0.05.
    BACK_LATE (0.01602) passes; a waistband piece (``length_free``) is never
    held to the worn hem (BULGE with length_free -> ok). GOOD against
    WORN_BELLY (worn pixels given) -> ok, worn_hem_c 0.65966; without the
    worn pixels it would read 0.73974. WORN_OPEN_WIDE -> centre_hem None.
[2] Front against the worn hems (b): GOOD as the front passes its gate and
    ``pair_reason`` against the BULGE back's record is None (front 0.65966,
    worn back 0.65966) — the ghost pair rule (``hems_reason``) refuses that
    same pair: "garment ends at another height than in the back view: |Δ|
    0.031 Hb > 0.02 Hb (front 0.65966, back 0.69069)". FRONT_LATE as a front
    against a BACK_EARLY back: pair_reason None (0.01902 from the worn back).
    A front 0.026 off the worn back: GOOD front record with hem_c 0.63363 ->
    "… |Δ| 0.026 Hb > 0.02 Hb (front 0.63363, worn back 0.65966)".
[3] The view rendered again (c): ``pair_redo`` (front, back) — GOOD /
    BULGE -> "back" (0.03103 > 0); FRONT_EARLY / BACK_LATE (pair gap 23 /
    999 = 0.02302 > 0.02) -> "back" (0.01602 > 0.00701); FRONT_LATE /
    BACK_EARLY (gap 33 / 999) -> "front" (0.01401 < 0.01902); unmeasured
    ({} / {}) -> "front".
[4] Open / closed: gap rows from the region's top 320 (no neckline) + 0.02
    x 999 -> int(max(100 + 0.24 x 999 = 339.76, 339.98)) = 339 to
    int(min(100 + 0.40 x 999 = 499.6, 100 + (659 / 999 - 0.02) x 999 =
    739.02)) = 499 (499 without a worn hem too: int(499.6)). Panels: the
    jacket, median luminance 46.667 -> dark <=
    18.667.
    OPEN = GOOD with cols [497, 527) in the dark inside (12, 10, 8)
    (luminance 10): 30 open columns -> centre_gap 30 / 999 = 0.03003; worn
    0.0 -> refused "garment open where the worn piece is closed: a centre
    gap of 0.03 Hb (worn 0.0 Hb, open from 0.015 Hb)" — its hem is the
    jacket's (the inside is part of the ghost), so that is its only reason.
    WORN_OPEN = WORN with those columns in skin (worn open: the body shows,
    not garment): worn gap 0.03003; GOOD against it -> refused "garment
    closed where the worn piece is open: a centre gap of 0.0 Hb (worn 0.03
    Hb, open from 0.015 Hb)"; OPEN against it -> ok.
    PLACKET: worn and ghost both with the dark stripe -> both 0.03003 -> ok.
    Not closable, or the back view: no gap measured, OPEN ok.
[5] The chain (the jacket "Black Jacket", slots [outer] -> closable):
    garment_clothing.gate refuses OPEN for the jacket and passes it for a
    "Plain Shirt" (slots [top], not closable).
    Run 0: ghost back GOOD, front GOOD -> renders worn f1, worn bd1, ghost
    b1, ghost f1; ok; the back's record worn_hem_c 0.65966.
    Run B (b + c): the back := BACK_LATE (a version 3 record, re-gated by
    ``regate_accepted`` -> version 4, ok, hem_c 0.67568), the front
    removed; plan front FRONT_EARLY, back GOOD -> renders ghost f1 (accepted:
    0.00701 from both worn hems — the ghost pair rule would have refused it
    against BACK_LATE, 0.02302), then the pair disagrees and the BACK renders
    again: ghost b1 -> ok, the back's record hem_c 0.65966.
    Run D (d): first the back := NARROW with a version 3 record: re-gated
    -> refused for its width (an older rule), hem_refused False -> kept,
    not stale, the ghost step done. Then the back := BULGE with a version
    3 record (ok, as stored
    before A17). Not stale until re-gated; ``regate_accepted`` -> refused
    for its hem (the [1] reason), ``stale_accepted`` True, ``_done(ghost)``
    False. The run renders ONLY the back (ghost b1, GOOD) — never the front
    against the stored back — and ends ok; the back's final is GOOD.
[6] Fails on the old code (garment_gates.py PINNED at 16423b6b, read with
    ``git show`` into a temp module): BULGE as the back is ACCEPTED there
    (outside 0.0124), and its ``hems_reason`` refuses GOOD as the front
    against it (the lock of the case).
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
PINNED = "16423b6b"
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
BROWN = (60, 45, 35)
INSIDE = (12, 10, 8)
UNDERSIDE = (15, 12, 10)
W, H = 1024, 1200
HB = 999
BULGE_REASON = ("garment ends at another height than the worn piece: |Δ| 0.031 Hb > 0.02 Hb "
                "(ghost 0.69069, worn 0.65966)")
PAIR_GHOST_REASON = ("garment ends at another height than in the back view: |Δ| 0.031 Hb > 0.02 Hb "
                     "(front 0.65966, back 0.69069)")
WORN_BACK_REASON = ("garment ends at another height than in the back view: |Δ| 0.026 Hb > 0.02 Hb "
                    "(front 0.63363, worn back 0.65966)")
OPEN_REASON = "garment open where the worn piece is closed: a centre gap of 0.03 Hb (worn 0.0 Hb, open from 0.015 Hb)"
CLOSED_REASON = ("garment closed where the worn piece is open: a centre gap of 0.0 Hb (worn 0.03 Hb, "
                 "open from 0.015 Hb)")


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
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


def jacket(rgb, bottom=759):
    rgb[320:bottom + 1, 380:644] = BROWN
    return rgb


def mask_of(rgb):
    return (np.abs(rgb.astype(np.int16) - 128) > 2).any(2)


BASE = figure(canvas())
WORN = jacket(figure(canvas()))
GOOD = jacket(canvas())
FRONT_EARLY, BACK_LATE = jacket(canvas(), 752), jacket(canvas(), 775)
FRONT_LATE, BACK_EARLY = jacket(canvas(), 778), jacket(canvas(), 745)
BULGE = jacket(canvas())
BULGE[760:791, 452:572] = UNDERSIDE
OPEN = GOOD.copy()
OPEN[320:760, 497:527] = INSIDE
WORN_OPEN = WORN.copy()
WORN_OPEN[320:760, 497:527] = SKIN
WORN_PLACKET = WORN.copy()
WORN_PLACKET[320:760, 497:527] = INSIDE
WORN_BELLY = WORN.copy()
WORN_BELLY[760:840, 452:572] = (225, 185, 165)
WORN_OPEN_WIDE = WORN.copy()
WORN_OPEN_WIDE[340:760, 432:592] = SKIN
NARROW = canvas()
NARROW[320:760, 380:560] = BROWN


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB"))
    mask = (mask_of(rgb.astype(np.int16)) * 255).astype(np.uint8)
    if kwargs.get("only_mask"):
        return png(mask)
    return png(np.dstack([rgb, mask]))


def pinned(commit, name, tmp: Path):
    """app/core/<name>.py at ``commit`` as a throwaway module."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:app/core/{name}.py"],
                         check=True, capture_output=True, text=True).stdout
    path = tmp / f"{name}_{commit}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(f"{name}_{commit}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate(gg, ghost, *, worn=WORN, view="back", **kw):
    region = gg.garment_region(BASE, mask_of(BASE), worn, mask_of(worn))
    return gg.ghost_clothing_gate(BASE, mask_of(BASE), region, ghost, mask_of(ghost), view=view, **kw)


def gates_part(gg, gc):
    print("[1] hem against the worn piece (a)")
    region = gg.garment_region(BASE, mask_of(BASE), WORN, mask_of(WORN))
    check("centre column", gg._centre_column(mask_of(BASE)), (512, 100, 999))
    check("worn hem", round(gg.centre_hem(region, mask_of(BASE)), 5), 0.65966)
    bulge = gate(gg, BULGE)
    check("bulge back: refused for its hem alone", (bulge["ok"], bulge["reasons"], bulge["hem_c"],
                                                    bulge["worn_hem_c"]), (False, [BULGE_REASON], 0.69069, 0.65966))
    near("bulge back: its area passes (outside)", bulge["outside"], 1440 / 116160, 0.0005)
    late = gate(gg, BACK_LATE)
    check("BACK_LATE passes", (late["ok"], late["hem_c"]), (True, 0.67568))
    check("a waistband piece's length is free", gate(gg, BULGE, length_free=True)["ok"], True)
    belly = gate(gg, GOOD, worn=WORN_BELLY, worn_rgb=WORN_BELLY)
    check("a re-shaded belly is no hem (skin left out)", (belly["ok"], belly["worn_hem_c"]), (True, 0.65966))
    check("... it would be without the worn pixels", gate(gg, GOOD, worn=WORN_BELLY)["worn_hem_c"], 0.73974)
    wide = gg.garment_region(BASE, mask_of(BASE), WORN_OPEN_WIDE, mask_of(WORN_OPEN_WIDE))
    check("an open front: the collar is no hem", gg.centre_hem(wide, mask_of(BASE)), None)

    print("[2] the front against the worn hems (b)")
    good = gate(gg, GOOD, view="front")
    check("GOOD front passes its gate", (good["ok"], good["hem_c"], good["worn_hem_c"]), (True, 0.65966, 0.65966))
    check("against the bulge back: accepted by the worn back", gc.pair_reason(good, bulge), None)
    check("the ghost pair rule refuses it", gg.hems_reason(good, bulge), PAIR_GHOST_REASON)
    check("FRONT_LATE against BACK_EARLY", gc.pair_reason(gate(gg, FRONT_LATE, view="front"),
                                                         gate(gg, BACK_EARLY)), None)
    check("0.026 off the worn back", gc.pair_reason({**good, "hem_c": 0.63363}, bulge), WORN_BACK_REASON)
    check("a waistband front is free", gc.pair_reason({**good, "hem_c": 0.63363, "length_free": True}, bulge), None)

    print("[3] the view rendered again (c)")
    early, back_late = gate(gg, FRONT_EARLY, view="front"), late
    check("GOOD / BULGE -> back", gc.pair_redo(good, bulge), "back")
    check("FRONT_EARLY / BACK_LATE disagree, -> back",
          (gg.hems_agree(early, back_late), gc.pair_agree(early, back_late), gc.pair_redo(early, back_late)),
          (False, False, "back"))
    front_late, back_early = gate(gg, FRONT_LATE, view="front"), gate(gg, BACK_EARLY)
    check("FRONT_LATE / BACK_EARLY disagree, -> front",
          (gg.hems_agree(front_late, back_early), gc.pair_redo(front_late, back_early)), (False, "front"))
    check("unmeasured -> front", gc.pair_redo({}, {}), "front")

    print("[4] open / closed")
    check("gap rows", (gg.gap_rows(region, mask_of(BASE), 659 / 999), gg.gap_rows(region, mask_of(BASE), None)),
          ((339, 499), (339, 499)))
    opened = gate(gg, OPEN, view="front", worn_rgb=WORN, closable=True)
    check("OPEN against the closed worn front: refused for its gap alone",
          (opened["ok"], opened["reasons"], opened["centre_gap"], opened["worn_centre_gap"]),
          (False, [OPEN_REASON], 0.03, 0.0))
    shut = gate(gg, GOOD, worn=WORN_OPEN, view="front", worn_rgb=WORN_OPEN, closable=True)
    check("GOOD against the open worn front: refused", (shut["ok"], shut["reasons"], shut["worn_centre_gap"]),
          (False, [CLOSED_REASON], 0.03))
    check("OPEN against the open worn front: ok",
          gate(gg, OPEN, worn=WORN_OPEN, view="front", worn_rgb=WORN_OPEN, closable=True)["ok"], True)
    placket = gate(gg, OPEN, worn=WORN_PLACKET, view="front", worn_rgb=WORN_PLACKET, closable=True)
    check("a dark placket in both: ok", (placket["ok"], placket["centre_gap"], placket["worn_centre_gap"]),
          (True, 0.03, 0.03))
    plain = gate(gg, OPEN, view="front", worn_rgb=WORN, closable=False)
    check("not closable: no gap measured, ok", (plain["ok"], "centre_gap" in plain), (True, False))
    check("the back view: no gap measured",
          "centre_gap" in gate(gg, OPEN, view="back", worn_rgb=WORN, closable=True), False)


def chain_part(gg, gc, root: Path):
    from app.core import paths
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
    from app.core import garment_store as gs
    from app.models import character as charmod
    from app.models import inventory
    from app.models.character import get_character_dir, save_character_profile
    garment_assembly.schedule = lambda *a, **k: False
    sys.path.insert(0, str(ROOT / "scripts"))
    from _figure_build_fixtures import record_requests
    record_requests()
    charmod.run_rembg = rembg_stub

    human = {"template": "human-roleplay", "gender": "male", "age": 30, "height": 180,
             "character_appearance": "slim",
             "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "brown"},
                            "build": {"type": "athletic"}}}
    check("create Demo", save_character_profile("Demo", human, create_new=True), True)
    jid = inventory.add_item(name="Black Jacket", category="outfit_piece",
                             prompt_fragment="a brown leather jacket, zipped",
                             outfit_piece={"slots": ["outer"], "outfit_types": ["casual"],
                                           "mesh_mode": "own_mesh"})["id"]
    sid = inventory.add_item(name="Plain Shirt", category="outfit_piece", prompt_fragment="a plain shirt",
                             outfit_piece={"slots": ["top"], "mesh_mode": "own_mesh"})["id"]
    check("inventory jacket", inventory.add_to_inventory("Demo", jid), True)
    check("equip jacket", inventory.equip_piece("Demo", jid, source="smoke")["status"], "ok")
    refs = get_character_dir("Demo") / "model_refs"
    refs.mkdir(parents=True, exist_ok=True)
    bsig = base_body.base_signature("Demo")
    for v in base_body.BASE_VIEWS:
        stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
        (refs / f"{stem}.png").write_bytes(png(BASE))
        (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))

    print("[5] the chain")
    args = {"base_rgb": BASE, "base_mask": mask_of(BASE), "source_rgb": WORN, "source_mask": mask_of(WORN)}
    check("the kind gate: the jacket is closable, OPEN refused",
          gc.gate("ghost", "front", edit_rgb=OPEN, edit_mask=mask_of(OPEN), item_id=jid, **args)["reasons"],
          [OPEN_REASON])
    check("the shirt is not: OPEN ok",
          gc.gate("ghost", "front", edit_rgb=OPEN, edit_mask=mask_of(OPEN), item_id=sid, **args)["ok"], True)

    renders, plan = [], {}

    def recorder(character_name, *, output_stem, **kw):
        g = kw["sidecar_extra"]["garment"]
        key = (f"{g['step']} {g['view'][0]}d{g.get('attempt')}" if g.get("stage") == "draft"
               else f"{g['step']} {g['view'][0]}{g.get('attempt', 'd')}")
        renders.append(key)
        queue = [] if g.get("stage") == "draft" else plan.get((g["step"], g["view"])) or []
        arr = queue.pop(0) if queue else (WORN if g["step"] == "worn" else GOOD)
        side = kw["override_width"]
        out_canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
        dy, dx = (out_canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
        if g.get("stage") == "draft":
            out_canvas = arr
        else:
            out_canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
        out = Path(str(output_stem) + ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png(out_canvas))
        out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g.get("attempt", 0),
                                                        **kw["sidecar_extra"]}))
        return out

    def cut_out(character_name, item_id, fsig_, view, *, force=False):
        path = gs.garment_path(character_name, item_id, fsig_, "image", step="cutout", view=view)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cutout")
        gs.write_record(path.with_suffix(".json"), {"accepted": True})
        return path

    expression_regen.render_character_image = recorder
    garment_images.cut_out = cut_out
    garment_mesh.generate = lambda *a, **k: None
    garments._fit = lambda *a, **k: None
    fsig = gs.garment_fsig("Demo", jid)

    def final(view):
        return gs.garment_path("Demo", jid, fsig, "image", step="ghost", view=view)

    def record(view):
        return gs.read_record(final(view).with_suffix(".json"))

    def first_gate(view):
        return (record(view).get("gates") or {}).get("first") or {}

    def store_v3(view, arr, **numbers):
        """``arr`` as the accepted final of ``view`` with a gate record as stored before A17."""
        final(view).write_bytes(png(arr))
        gs.write_record(final(view).with_suffix(".json"), {
            "accepted": True, "attempt": 1,
            "gates": {"first": {"view": view, "ok": True, "reasons": [], "gate_version": 3, "attempt": 1,
                                **numbers}}})

    plan[("ghost", "back")] = [GOOD]
    plan[("ghost", "front")] = [GOOD]
    res = garments.run_garment("Demo", jid)
    check("run 0: renders", renders, ["worn f1", "worn bd1", "ghost b1", "ghost f1"])
    check("run 0: ok, the worn back's hem", (res.get("ok"), first_gate("back").get("worn_hem_c")),
          (True, 0.65966))

    print("  run B: a front against the worn hems, then the back again (b + c)")
    store_v3("back", BACK_LATE, hem_t=0.67568)
    again = garment_images.regate_accepted("Demo", jid, fsig, "ghost", "back")
    check("BACK_LATE re-gated: the current version (A32: 6), still accepted",
          (again.get("gate_version"), again.get("ok"), again.get("hem_c"), again.get("regated_from"),
           garment_images.stale_accepted("Demo", jid, fsig, "ghost", "back")), (6, True, 0.67568, 3, False))
    late_record = first_gate("back")
    final("front").unlink()
    final("front").with_suffix(".json").unlink()
    del renders[:]
    plan[("ghost", "front")] = [FRONT_EARLY]
    plan[("ghost", "back")] = [GOOD]
    res = garments.run_garment("Demo", jid)
    check("run B: the front, then the back", renders, ["ghost f1", "ghost b1"])
    front_record = first_gate("front")
    check("run B: the front accepted against the worn back",
          (front_record.get("ok"), front_record.get("hem_c"), front_record.get("reasons")), (True, 0.65265, []))
    check("run B: the ghost pair rule would have refused it",
          gg.hems_reason(front_record, late_record) is not None, True)
    check("run B: ok, the back GOOD", (res.get("ok"), first_gate("back").get("hem_c")), (True, 0.65966))

    print("  run D: a stale stored ghost back is not reused (d)")
    store_v3("back", NARROW, hem_t=0.65966)
    again = garment_images.regate_accepted("Demo", jid, fsig, "ghost", "back")
    check("an older rule only (width): recorded, kept, not stale",
          (again.get("ok"), again.get("hem_refused"), garment_images.stale_accepted("Demo", jid, fsig, "ghost", "back"),
           garments._done("Demo", jid, "clothing", fsig, "ghost", "x")), (False, False, False, True))
    store_v3("back", BULGE, hem_t=0.69069)
    check("not stale before the re-gate", garment_images.stale_accepted("Demo", jid, fsig, "ghost", "back"),
          False)
    again = garment_images.regate_accepted("Demo", jid, fsig, "ghost", "back")
    check("re-gated: refused for its hem", (again.get("ok"), again.get("reasons")), (False, [BULGE_REASON]))
    check("stale, not done, still accepted",
          (garment_images.stale_accepted("Demo", jid, fsig, "ghost", "back"),
           garments._done("Demo", jid, "clothing", fsig, "ghost", "x"), record("back").get("accepted")),
          (True, False, True))
    del renders[:]
    plan[("ghost", "back")] = [GOOD]
    plan[("ghost", "front")] = [GOOD]
    res = garments.run_garment("Demo", jid)
    check("run D: only the back renders", renders, ["ghost b1"])
    check("run D: ok, the back is GOOD now",
          (res.get("ok"), first_gate("back").get("hem_c"), first_gate("back").get("ok"),
           final("back").read_bytes() == png(GOOD)), (True, 0.65966, True, True))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ghost-hem-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import garment_clothing as gc
        from app.core import garment_gates as gg
        gates_part(gg, gc)
        chain_part(gg, gc, root)
        print(f"[6] fails on the old code ({PINNED})")
        old = pinned(PINNED, "garment_gates", root)
        old_bulge = gate(old, BULGE)
        check("old: the bulge back accepted", (old_bulge["ok"], old_bulge["gate_version"]), (True, 3))
        old_good = gate(old, GOOD, view="front")
        check("old: GOOD front refused against it", old.hems_reason(old_good, old_bulge), PAIR_GHOST_REASON)
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
