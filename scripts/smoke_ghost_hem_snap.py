#!/usr/bin/env python3
"""Ruling A27 (2026-11-13): a ghost view whose ONLY refusal is the hem
height, |Δ| <= 0.05 Hb, is snapped to the worn hem on the CPU instead of
refused; stored attempts refused under the older gate are judged again
before any render, and the estimate and the failure cache see that
(app/core/garment_gates.py ``hem_snap_due`` / ``underarm_row`` /
``hem_snap`` / ``snap_rows``, app/core/garment_clothing.py ``hem_snap`` /
``hem_snap_due``, app/core/garment_images.py ``_snap_hem`` /
``rejudge_expected`` / ``_regate_stored``, app/core/garments.py
``cached_failure`` / ``run_estimate``).

The case (live 2026-11-13, a leather jacket): ghost back attempt 1 was a
longer jacket (a part beyond the worn piece and |Δ| 0.0758 — a true
refusal), attempt 2 the same jacket with the sleeves hanging lower, refused
ONLY for |Δ| 0.0344 Hb > 0.02 Hb.

Usage:
    ./.venv/bin/python scripts/smoke_ghost_hem_snap.py
    A27_FIXTURE_DIR=/path ./.venv/bin/python scripts/smoke_ghost_hem_snap.py   # + [5]

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server. The gates,
``run_edit_step`` and the chain are REAL; stubbed: the renderer (writes the
planned image, every call counted), ``character.run_rembg`` (every pixel
more than 2 away from grey 128), ``garment_images.cut_out`` /
``garment_mesh.generate`` / ``garments._fit`` (after the ghost, not under
test).

Geometry, W 1024 x H 1200 on grey 128:
  BASE  skin (200, 160, 140): head disc centre (512, 200) r 100, shoulders
        rows [300, 380) cols [300, 724), torso rows [380, 1100) cols
        [392, 632), arms rows [380, 800) cols [300, 352) and [672, 724):
        y0 100, Hb 1099 - 100 = 999. Shoulder row int(100 + 0.19 x 999) =
        289: the disc spans |x - 512| <= 45 there -> centre column 512; the
        hem band ± round(0.04 x 999) = 40 -> cols 472..552.
  JACKET(bottom) brown (60, 45, 35): shoulders rows [320, 380) cols
        [292, 732), body rows [320, bottom] cols [380, 644), sleeves rows
        [380, 600) cols [292, 360) and [664, 732) — 20 px clear of the body.
        WORN = BASE + JACKET(759): every band column of the worn region runs
        rows 320..759 -> worn_hem_c (759 - 100) / 999 = 0.65966.
  Underarm line: from the shoulder row 289 down, rows 289..319 hold no
        region at column 512, rows 320..379 are one run (the shoulders);
        row 380 is the first where the run through column 512 (the body,
        380..643) has region on both sides (the sleeves, 20 px apart — the
        region's closing of 3 iterations @1200 cannot bridge them) -> 380,
        (380 - 100) / 999 = 0.28028 Hb. (The bare base parts at 380 too.)
  Ghosts (the jacket alone on grey):
        LOW    JACKET(793): hem_c (793 - 100) / 999 = 0.69369, |Δ| 34 / 999
               = 0.03403 <= 0.05; beyond the region: rows 779..793 farther
               than 0.02 x 999 = 19.98 px, 15 x 264 = 3960 px over a region
               of ~156 600 px = 0.025 <= 0.05 -> refused for the hem alone.
        HIGH   JACKET(725): hem_c 0.62563, |Δ| 0.03403.
        HIGH60 JACKET(699): hem_c 0.59960, |Δ| 60 / 999 = 0.06006 > 0.05.
        GOOD   JACKET(759), EXTRA = GOOD + a brown block rows [900, 1100)
               cols [480, 544): 200 x 64 = 12 800 px far beyond the region,
               0.082 > 0.05 -> "more than the garment"; its band columns'
               longest run is still the body (440 rows > 200) -> hem 0.65966.
               LOW_EXTRA = LOW + that block: two reasons.

[1] LOW is due (hem only, 0.034 <= 0.05). The snap: from 0.69369, to
    0.65966 (the record's), line row 380; from row 100 + 0.693694 x 999 =
    793.0, to row 100 + 0.65966 x 999 = 759.0003 -> scale (759.0003 - 380)
    / (793 - 380) = 379.0003 / 413 = 0.91768 (5 digits), underarm 0.28028.
    Snapped (``snap_rows``): output row q >= 380 reads row 380 + (q - 380)
    / 0.91768: q 759 -> 793.0003 (the body's last row, kept), q 760 ->
    794.09 (grey) -> the body ends at 759, hem_c 0.65966: the full gate
    passes. Rows above 380 are untouched (byte-equal). HIGH: scale 379.0003
    / (725 - 380) = 1.09855, the snapped image passes too.
[2] HIGH60 (|Δ| 0.06006, its only reason "… |Δ| 0.0601 Hb > 0.02 Hb …"):
    not due, no snap -> stays refused.
[3] EXTRA (hem fine, an extra part): refused, not due, no snap. LOW_EXTRA
    (the hem off by 0.034 AND the extra part — the true refusal of the case):
    not due, no snap.
[4] The chain (a "Black Jacket", slots [outer]): run 0 renders everything
    GOOD. Then the ghost back is made a refused view stored under gate
    version 4: its final, its cut-out back and the attempts' raw siblings
    go; try1 = LOW_EXTRA with its two reasons, try2 = LOW refused for the
    hem alone (both records version 4). Its registration is reported beyond
    the caps from here on, as in the live case (gated as rendered; the
    outline registration alone would scale LOW by 0.968 onto the worn hem
    and pass it unsnapped);
    a chain failure is recorded at step ghost (the cache of the refusal).
    First a contrast: with try2 refused for HIGH60's hem (0.06, version 4)
    nothing is expected — ``rejudge_expected`` False, the failure holds.
    Then with the LOW record: ``rejudge_expected`` (back) True, (front)
    False; ``cached_failure`` None (released) while ``chain_failure`` still
    holds the record; ``run_estimate`` starts at ghost with ghost 2 - 2 kept
    = 0 jobs -> "cutout 2 + mesh 1", 3 hub jobs. The run: 0 stub calls; ok;
    try1 re-judged and still refused (regated_from 4), try2 accepted with
    ``hem_snap`` {from 0.69369, to 0.65966, scale 0.91768, underarm 0.28028}
    in its record, its sidecar and the final's sidecar; the final is
    attempt 2, its hem 0.65966; the raw sibling keeps the rendering (LOW).
    The failure record is cleared.
[5] Optional — copies of the live case (``A27_FIXTURE_DIR``: base_back.png,
    worn_back.png, ghost_back.try1.png, ghost_back.try2.png, each with a
    ``.mask.png`` beside it — the BiRefNet masks the gate used; never read
    from a world): try1 not due (two reasons), try2 snapped at scale
    0.85152 (block "Hem snap" in garment_gates) and passing every rule.
    Skipped when the variable is unset or the files are absent.
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
BROWN = (60, 45, 35)
W, H = 1024, 1200
HEM_LOW_REASON = ("garment ends at another height than the worn piece: |Δ| 0.034 Hb > 0.02 Hb "
                  "(ghost 0.69369, worn 0.65966)")
HEM_60_REASON = ("garment ends at another height than the worn piece: |Δ| 0.0601 Hb > 0.02 Hb "
                 "(ghost 0.5996, worn 0.65966)")
SNAP_LOW = {"from": 0.69369, "to": 0.65966, "scale": 0.91768, "underarm": 0.28028}
FIXTURE_FILES = ("base_back", "worn_back", "ghost_back.try1", "ghost_back.try2")


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
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
    rgb[300:380, 300:724] = SKIN
    rgb[380:1100, 392:632] = SKIN
    rgb[380:800, 300:352] = SKIN
    rgb[380:800, 672:724] = SKIN
    return rgb


def jacket(rgb, bottom=759):
    rgb[320:380, 292:732] = BROWN
    rgb[320:bottom + 1, 380:644] = BROWN
    rgb[380:600, 292:360] = BROWN
    rgb[380:600, 664:732] = BROWN
    return rgb


def extra(rgb):
    rgb[900:1100, 480:544] = BROWN
    return rgb


def mask_of(rgb):
    return (np.abs(rgb.astype(np.int16) - 128) > 2).any(2)


BASE = figure(canvas())
WORN = jacket(figure(canvas()))
GOOD = jacket(canvas())
LOW, HIGH, HIGH60 = jacket(canvas(), 793), jacket(canvas(), 725), jacket(canvas(), 699)
EXTRA = extra(jacket(canvas()))
LOW_EXTRA = extra(jacket(canvas(), 793))


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB"))
    mask = (mask_of(rgb.astype(np.int16)) * 255).astype(np.uint8)
    if kwargs.get("only_mask"):
        return png(mask)
    return png(np.dstack([rgb, mask]))


def region_of(gg, base=BASE, worn=WORN):
    return gg.garment_region(base, mask_of(base), worn, mask_of(worn))


def gate(gg, ghost, *, view="back"):
    return gg.ghost_clothing_gate(BASE, mask_of(BASE), region_of(gg), ghost, mask_of(ghost), view=view,
                                  worn_rgb=WORN, closable=True)


def snapped_gate(gg, ghost, snap):
    out_rgb, out_mask = gg.snap_rows(ghost, snap), gg.snap_rows(mask_of(ghost), snap)
    return out_rgb, out_mask, gg.ghost_clothing_gate(BASE, mask_of(BASE), region_of(gg), out_rgb, out_mask,
                                                     view="back", worn_rgb=WORN, closable=True)


def gates_part(gg, gc):
    region = region_of(gg)
    print("[0] the frame")
    check("centre column", gg._centre_column(mask_of(BASE)), (512, 100, 999))
    check("worn hem", round(gg.centre_hem(region, mask_of(BASE)), 5), 0.65966)
    check("underarm line on the region / on the bare base",
          (gg.underarm_row(region, mask_of(BASE)), gg.underarm_row(np.zeros_like(region), mask_of(BASE))),
          (380, 380))

    print("[1] a hem-only refusal within 0.05 Hb is snapped")
    low = gate(gg, LOW)
    check("LOW refused for its hem alone", (low["ok"], low["reasons"], low["hem_refused"]),
          (False, [HEM_LOW_REASON], True))
    check("LOW is due", (gg.hem_snap_due(low), gc.hem_snap_due("ghost", low), gc.hem_snap_due("worn", low)),
          (True, True, False))
    snap = gg.hem_snap(low, mask_of(LOW), region, mask_of(BASE))
    check("the snap (hand-derived)", {k: snap[k] for k in SNAP_LOW} if snap else None, SNAP_LOW)
    check("its line row", snap and snap["row"], 380)
    check("the kind hook gives the same",
          gc.hem_snap("ghost", "back", low, ghost_mask=mask_of(LOW), region=region, base_mask=mask_of(BASE)),
          snap)
    out_rgb, out_mask, again = snapped_gate(gg, LOW, snap)
    check("snapped: the full gate passes, hem on the worn hem",
          (again["ok"], again["reasons"], again["hem_c"], again["worn_hem_c"]), (True, [], 0.65966, 0.65966))
    check("snapped: the body's last row 759", int(np.nonzero(out_mask[:, 512])[0].max()), 759)
    check("rows above the line untouched", bool((out_rgb[:380] == LOW[:380]).all()), True)
    high = gate(gg, HIGH)
    hsnap = gg.hem_snap(high, mask_of(HIGH), region, mask_of(BASE))
    check("HIGH (0.034 short): stretched, scale 1.09855", hsnap and hsnap["scale"], 1.09855)
    check("HIGH snapped passes", snapped_gate(gg, HIGH, hsnap)[2]["ok"], True)

    print("[2] beyond 0.05 Hb: refused")
    high60 = gate(gg, HIGH60)
    check("HIGH60 refused for its hem alone", (high60["ok"], high60["reasons"]), (False, [HEM_60_REASON]))
    check("HIGH60 not due, no snap",
          (gg.hem_snap_due(high60), gg.hem_snap(high60, mask_of(HIGH60), region, mask_of(BASE))), (False, None))

    print("[3] another reason: refused")
    ext = gate(gg, EXTRA)
    check("EXTRA: hem fine, refused for the extra part",
          (ext["ok"], ext["hem_refused"], ext["hem_c"], len(ext["reasons"]),
           ext["reasons"][0].startswith("more than the garment in the image")), (False, False, 0.65966, 1, True))
    check("EXTRA not due, no snap", (gg.hem_snap_due(ext), gg.hem_snap(ext, mask_of(EXTRA), region,
                                                                        mask_of(BASE))), (False, None))
    both = gate(gg, LOW_EXTRA)
    check("LOW_EXTRA: two reasons (the true refusal)", (both["ok"], len(both["reasons"]), both["hem_refused"]),
          (False, 2, True))
    check("LOW_EXTRA not due, no snap", (gg.hem_snap_due(both), gg.hem_snap(both, mask_of(LOW_EXTRA), region,
                                                                             mask_of(BASE))), (False, None))
    return low, both, high60


def chain_part(gg, gc, root: Path, low_record, both_record, high60_record):
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
    check("inventory jacket", inventory.add_to_inventory("Demo", jid), True)
    check("equip jacket", inventory.equip_piece("Demo", jid, source="smoke")["status"], "ok")
    refs = get_character_dir("Demo") / "model_refs"
    refs.mkdir(parents=True, exist_ok=True)
    bsig = base_body.base_signature("Demo")
    for v in base_body.BASE_VIEWS:
        stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
        (refs / f"{stem}.png").write_bytes(png(BASE))
        (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))

    print("[4] the chain")
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

    def image(step, view, attempt=None):
        return gs.garment_path("Demo", jid, fsig, "image", step=step, view=view, attempt=attempt)

    plan[("ghost", "back")] = [GOOD]
    plan[("ghost", "front")] = [GOOD]
    res = garments.run_garment("Demo", jid)
    check("run 0: renders", renders, ["worn f1", "worn bd1", "ghost b1", "ghost f1"])
    check("run 0: ok", res.get("ok"), True)

    # The refused ghost back as a run under gate version 4 left it.
    for path in (image("ghost", "back"), image("cutout", "back")):
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)

    def store_attempt(n, arr, record):
        target = image("ghost", "back", n)
        target.write_bytes(png(arr))
        garment_images.raw_path(target).unlink(missing_ok=True)   # run 0's rendering of this attempt
        gs.write_record(target.with_suffix(".json"), {
            "seed": 2000 + n, "garment": {"item_id": jid, "fsig": fsig, "step": "ghost", "view": "back",
                                          "attempt": n},
            "gate": {**record, "gate_version": 4, "attempt": n}})

    store_attempt(1, LOW_EXTRA, both_record)
    store_attempt(2, HIGH60, high60_record)
    base_sha = base_body.current_base("Demo")[1]
    gs.record_failure("Demo", jid, fsig, step="ghost", error="ghost back refused (gate version 4)",
                      base_model_sha=base_sha)
    check("contrast (0.06 stored): nothing expected, the failure holds",
          (garment_images.rejudge_expected("Demo", jid, fsig, "ghost", "back"),
           (garments.cached_failure("Demo", jid) or {}).get("step")), (False, "ghost"))
    store_attempt(2, LOW, low_record)
    # The live case: its registration was beyond the caps, the ghost gated as rendered. Here every
    # estimate is reported beyond the caps (LOW alone would be registered onto the hem and pass unsnapped).
    estimate = gc.register_estimate
    gc.register_estimate = lambda *a, **k: {**(estimate(*a, **k) or {}), "within_caps": False}
    check("rejudge expected: back / front",
          (garment_images.rejudge_expected("Demo", jid, fsig, "ghost", "back"),
           garment_images.rejudge_expected("Demo", jid, fsig, "ghost", "front")), (True, False))
    check("the failure record is there, but no longer holds",
          ((gs.chain_failure("Demo", jid, fsig, base_model_sha=base_sha) or {}).get("step"),
           garments.cached_failure("Demo", jid)), ("ghost", None))
    est = garments.run_estimate("Demo", jid)
    check("estimate: from ghost, the ghost render dropped",
          (est.get("steps"), est.get("hub_jobs"), est.get("note")),
          (["ghost", "cutout", "mesh", "fit"], 3, "cutout 2 + mesh 1"))

    del renders[:]
    res = garments.run_garment("Demo", jid)
    check("run: 0 stub calls", renders, [])
    check("run: ok", (res.get("ok"), res.get("error")), (True, None))
    t1 = gs.read_record(image("ghost", "back", 1).with_suffix(".json"))
    check("try1 judged again, still refused", ((t1.get("gate") or {}).get("ok"),
                                               (t1.get("gate") or {}).get("regated_from"),
                                               "hem_snap" in t1), (False, 4, False))
    t2 = gs.read_record(image("ghost", "back", 2).with_suffix(".json"))
    gate2 = t2.get("gate") or {}
    check("try2 accepted with hem_snap", (gate2.get("ok"), gate2.get("hem_snap"), t2.get("hem_snap"),
                                          gate2.get("gate_version"), gate2.get("regated_from")),
          (True, SNAP_LOW, SNAP_LOW, gg.GHOST_GATE_VERSION, 4))
    final = gs.read_record(image("ghost", "back").with_suffix(".json"))
    first = (final.get("gates") or {}).get("second") or {}
    check("the final: accepted, attempt 2, hem_snap, its hem",
          (final.get("accepted"), final.get("attempt"), final.get("hem_snap"), first.get("hem_c")),
          (True, 2, SNAP_LOW, 0.65966))
    check("the raw sibling keeps the rendering",
          garment_images.raw_path(image("ghost", "back", 2)).read_bytes() == png(LOW), True)
    from PIL import Image
    with Image.open(image("ghost", "back")) as im:
        final_mask = mask_of(np.asarray(im.convert("RGB")))
    check("the final's hem on the worn hem", round(gg.centre_hem(final_mask, mask_of(BASE)), 5), 0.65966)
    check("the failure record is cleared", gs.chain_failure("Demo", jid, fsig, base_model_sha=base_sha), None)
    gc.register_estimate = estimate


def fixture_part(gg, gc):
    """[5] copies of the live case (module docstring)."""
    folder = os.environ.get("A27_FIXTURE_DIR")
    paths = {n: (Path(folder) / f"{n}.png", Path(folder) / f"{n}.mask.png") for n in FIXTURE_FILES} \
        if folder else {}
    if not folder or not all(p.is_file() and m.is_file() for p, m in paths.values()):
        print("[5] SKIPPED — no copies of the live case (A27_FIXTURE_DIR)")
        return
    from PIL import Image
    print("[5] copies of the live case")

    def load(name):
        p, m = paths[name]
        with Image.open(p) as im, Image.open(m) as mk:
            return np.asarray(im.convert("RGB")), np.asarray(mk.convert("L")) >= 128

    base_rgb, base_mask = load("base_back")
    worn_rgb, worn_mask = load("worn_back")
    region = gg.garment_region(base_rgb, base_mask, worn_rgb, worn_mask)
    hb = gg._zones(base_mask)[1]
    out = {}
    for name in ("ghost_back.try1", "ghost_back.try2"):
        rgb, mask = load(name)
        est = gc.register_estimate("ghost", "back", region, mask, body_h=hb)
        if est is not None and est["within_caps"] and not est["negligible"]:
            rgb, mask = gg.warp(rgb, est), gg.warp(mask, est)
        record = gg.ghost_clothing_gate(base_rgb, base_mask, region, rgb, mask, view="back", worn_rgb=worn_rgb,
                                        closable=True)
        snap = gg.hem_snap(record, mask, region, base_mask)
        after = None
        if snap is not None:
            after = gg.ghost_clothing_gate(base_rgb, base_mask, region, gg.snap_rows(rgb, snap),
                                           gg.snap_rows(mask, snap), view="back", worn_rgb=worn_rgb, closable=True)
        out[name] = (record, snap, after)
    rec1, snap1, _ = out["ghost_back.try1"]
    check("try1: refused for two reasons, not snapped", (rec1["ok"], len(rec1["reasons"]), snap1), (False, 2, None))
    rec2, snap2, after2 = out["ghost_back.try2"]
    check("try2: refused for its hem alone", (rec2["ok"], rec2["hem_c"], rec2["worn_hem_c"], len(rec2["reasons"])),
          (False, 0.50281, 0.4684, 1))
    check("try2: snapped at scale 0.85152", snap2 and snap2["scale"], 0.85152)
    check("try2 snapped: passes, on the worn hem",
          after2 and (after2["ok"], after2["hem_c"]), (True, 0.4684))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ghost-hem-snap-") as tmp:
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
        low, both, high60 = gates_part(gg, gc)
        chain_part(gg, gc, root, low, both, high60)
        fixture_part(gg, gc)
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
