#!/usr/bin/env python3
"""Ruling A46 — a piece-only view from the worn view minus the body, the "Piece-only views from" setting
and the ghost gate's added parts (app/core/garment_from_worn.py, garment_gates.added_parts,
garments.run_estimate / piece_views_info); Ruling A46b — an accepted ghost gated under an older version is
re-gated when the piece is shown (garments.regate_shown, garment_images.regate_due).

Usage:
    ./.venv/bin/python scripts/smoke_piece_from_worn.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no
world, no hub, no GPU, no server. Every image is synthetic (numpy), every number below derived by hand:

Frame: 400 x 1536 px (1536 = the gates' reference height, so every px constant is used as written). The
base view: the neutral grey (128) background, the figure the rectangle x 100..299, y 100..1499 (200 x 1400
= 280 000 px; y0 = 100, Hb = 1499 - 100 = 1399) in a skin gradient R = 170 + (x - 100) // 10,
G = 120 + (y - 100) // 100, B = 90. The worn view = the base with a BAND x 120..279, y 600..679 in blue
(40, 90, 160): 160 x 80 = 12 800 px.

[1] Exact mask. The band's distance to anything in the reference (skin: (80..100, 30..44, 70)/3 ≥ 60;
    grey: (88 + 38 + 32) / 3 = 52.7) is above GARMENT_DRGB 20 at every shift of the 5 px disc, every other
    pixel is 0 at its own place -> raw 12 800 px, nothing rim-filled (the closing of a rectangle is the
    rectangle; outside it nothing differs in place). Alignment: shift [0, 0] at cost 0.0 (no shift on a tie),
    gain 1.0. The opening by the 4-neighbour cross (``OPEN_PX`` 1) takes each pixel whose 4 neighbours are
    not all in and gives back each one with a neighbour left — not the 4 corners, which have none; the
    closing (2 iterations, a diamond of radius 2) does not reach a corner either: the mask = the band
    without its 4 corner pixels, 12 796 px, bbox [120, 600, 279, 679], 1 part. The alpha is 0 outside the
    mask (the feather starts 1 px inside), 1.0 at the band's centre (240, 640).
[2] Shading is no piece. The worn view's figure is the base times (0.96, 0.92, 0.88) plus Gaussian noise
    (sigma 2, seed 46), the band blue as in [1], and a re-shaded SKIN PATCH x 140..219, y 900..979
    (80 x 80) the shaded skin times 1.3. The gain is measured on the agreeing pixels (|Δ| ≈ 9 < 25). A patch
    pixel differs from the normalised skin by about (50 + 35 + 24) / 3 = 36 > 20 — the reference is the
    base, unpatched everywhere, so the disc finds no match for any of them: raw = 12 800 + 6 400 = 19 200 px.
    The patch has the skin's hue (shade distance 0 <= SKIN_SHADE 12) and brightness: an area, taken out ->
    skin_removed_px 6 400 (6 400 >= 0.2 x 12 796: kept as a part without the skin rule). The mask is that of
    [1] exactly (12 796 px).
[3] Auto (``garment_from_worn.resolve``, items in the throwaway world): a LOOSE piece (slot "top") ->
    generated, why "loose", no fallback; a close-fitting one (slot "underwear_top") without files ->
    generated, "passes", auto True; the same with two stored ghost back attempts both refused (no final)
    -> worn, "refused", detail = the newest attempt's first reason; with an accepted GENERATED final whose
    current gate record says ``added_refused`` (reach 0.0428) -> worn, "added", detail "0.0428". A set
    choice wins: "worn" on the loose piece -> worn "set_worn"; "generated" on the added one -> generated
    "set_generated". ``set_choice`` stores ``outfit_piece.piece_views`` = {"back": "worn"}; an update
    that does not name it keeps it; Auto drops the key.
[4] Gate: a thin added strap is refused. Region = the band; the ghost = the band plus a STRAP x 196..199
    (4 px), y 500..599 up from the band's top. The margin (8 iterations of the cross: L1 distance 8) leaves
    the strap's rows 500..591 = 92 x 4 = 368 px beyond it, one part of 368 / 12 800 = 0.02875 of the region
    (>= ADDED_MIN_PART 0.001); its farthest pixel (y 500) lies 100 px above the box: reach 100 / 1399 =
    0.0715 > ADDED_REACH_MAX 0.03, thickness 368 / 100 / 1399 = 0.0026 <= ADDED_THIN_MAX 0.02 -> refused
    (``added_refused``). ``outside`` (the part farther than CLOTH_FAR 0.02 Hb = 27.98 px: rows 500..572,
    73 x 4 = 292 px) = 292 / 12 800 = 0.02281 < 0.05: the old gate passed it. A NUB (rows 570..599, 30 px)
    reaches 30 / 1399 = 0.0214 <= 0.03 -> passes. A longer HEM (the band continued to y 739) reaches 60 /
    1399 = 0.0429 but is the piece's width thick (52 x 160 = 8 320 px / 60 / 1399 = 0.099 > 0.02) -> no
    added part (added_reach 0.0; the hem is the hem gate's).
[5] The setting makes the cut-out, the mesh and the fit due (``run_estimate``, ``piece_views_info``): a
    close-fitting piece with worn + ghost (generated) + cut-out accepted on both views and the prepared mesh
    accepted, the fit missing -> steps [fit], 0 jobs. Back -> "worn": the ghost back is due (made from the
    generated edit, the setting names the worn view) -> steps [ghost, cutout, mesh, fit]; jobs: ghost 2 - 1
    kept front - 1 back from the worn view = 0, cutout 2 - 1 kept front (its ghost and cut-out stay done) = 1,
    mesh 1 -> 2, note "cutout 1 + mesh 1". ``piece_views_info`` back: source worn, made_from generated,
    due [ghost back 0, cutout back 1, mesh 1, fit 0]; front unchanged (due []), its "worn" option names
    [ghost front 0, cutout front 1, mesh 1, fit 0] and its "generated" option []. Back -> "generated"
    or back to Auto -> steps [fit], 0 again (made from the edit, which they name).
[6] Fails on the old code (efcb9e4a9793dc23a5693528959e957a56abaeb0): ``app/core/garment_from_worn.py``
    does not exist there, and its ``ghost_clothing_gate`` passes the strap of [4] (ok True, no
    ``added_reach``).
[7] Ruling A46b — an accepted ghost gated under an OLDER version is re-gated when the piece is shown
    (``garments.regate_shown``, asked by ``garment_info`` / ``piece_views_info``). The character's base views
    (front and back) are the base of [1]; a close-fitting "Strap top" (slot underwear_top) has its worn front
    (the base with the band, accepted) and as its accepted ghost front the band plus the strap of [4] on grey
    (``garment_images.run_rembg`` stubbed: every pixel more than 2 away from the grey is the figure), stamped
    ``gate_version`` 6, ok — as stored before A46. The masks are the base's skin rectangle, the worn view's the
    same, the ghost's band + strap; the garment region of base and worn view is the band (every band pixel is
    more than 20 from the skin). So the current gate measures what [4] measured: the strap reaches
    100 / 1399 = 0.0715 Hb past it, thickness 0.0026 -> refused, ``added_refused``.
    - Before: ``regate_due`` True; Auto reads the stored v6 record -> ("generated", "passes"), nothing due.
    - Shown while the background worker is busy (a blocker queued first): ``regate_shown`` names
      [ghost front] and queues ONE task (a second call while it is pending queues none); ``piece_views_info``
      front ``checking`` True, the back (no accepted ghost) False.
    - After the worker: the sidecar's record is version 7, ``regated_from`` 6, ok False, ``added_refused``,
      reach 0.0715; the gate ran once (1 call); the file is unchanged (same bytes) and still accepted.
    - Auto now: ("worn", "added", "0.0715"), made from generated -> due [ghost front 0, cutout front 1, mesh 1,
      fit 0]; ``checking`` False.
    - A second read: ``regate_due`` False, ``regate_shown`` [], no task, the gate still called once; the
      garment payload (``garment_info``) has ``regate_checking`` [], the front from the worn view, its ghost
      front's record ``added_refused``.
    - Fails on the old code (ff9cbd7aea2e2b94b4a0f35e6c87ae13afa82d7a, A46): its ``garments.py`` has no
      ``regate_shown`` and its ``garment_info`` / ``piece_views_info`` re-gate nothing, its ``garment_images.py`` no
      ``regate_due`` — the payload kept the stored v6 verdict, which Auto reads as ("generated", "passes")
      (the "Before" check above) until a run.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "efcb9e4a9793dc23a5693528959e957a56abaeb0"
OLD_A46 = "ff9cbd7aea2e2b94b4a0f35e6c87ae13afa82d7a"
FAILS = []
W, H = 400, 1536
GREY = 128
BLUE = (40, 90, 160)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def base_view():
    rgb = np.full((H, W, 3), GREY, dtype=np.uint8)
    ys, xs = np.mgrid[100:1500, 100:300]
    rgb[100:1500, 100:300, 0] = 170 + (xs - 100) // 10
    rgb[100:1500, 100:300, 1] = 120 + (ys - 100) // 100
    rgb[100:1500, 100:300, 2] = 90
    figure = np.zeros((H, W), dtype=bool)
    figure[100:1500, 100:300] = True
    return rgb, figure


def band_mask():
    m = np.zeros((H, W), dtype=bool)
    m[600:680, 120:280] = True
    return m


def without_corners(m):
    out = m.copy()
    for y, x in ((600, 120), (600, 279), (679, 120), (679, 279)):
        out[y, x] = False
    return out


def part_mask():
    from app.core import garment_from_worn as fw
    print("[1] exact mask")
    base, figure = base_view()
    worn = base.copy()
    band = band_mask()
    worn[band] = BLUE
    mask, alpha, n = fw.piece_mask(base, figure, worn)
    check("alignment", (n["alignment"]["shift"], n["alignment"]["cost"]), ([0, 0], 0.0))
    check("gain", n["gain"], [1.0, 1.0, 1.0])
    check("raw / rim-filled / skin removed", (n["raw_px"], n["rim_filled_px"], n["skin_removed_px"]), (12800, 0, 0))
    want = without_corners(band)
    check("mask = the band without its 4 corners", (bool((mask == want).all()), n["piece_px"], n["bbox"], n["parts"]),
          (True, 12796, [120, 600, 279, 679], 1))
    check("alpha: 0 outside, 1 at the centre", (float(alpha[~mask].max()), round(float(alpha[640, 240]), 4)),
          (0.0, 1.0))

    print("[2] shading is no piece")
    rng = np.random.default_rng(46)
    shaded = base.astype(np.float32)
    shaded[figure] = shaded[figure] * np.array([0.96, 0.92, 0.88], dtype=np.float32)
    shaded[figure] += rng.normal(0.0, 2.0, size=(int(figure.sum()), 3)).astype(np.float32)
    shaded[900:980, 140:220] *= 1.3
    shaded[band] = BLUE
    worn2 = np.clip(np.round(shaded), 0, 255).astype(np.uint8)
    mask2, _alpha2, n2 = fw.piece_mask(base, figure, worn2)
    check("raw: the band + the patch", n2["raw_px"], 19200)
    check("the patch taken out as skin", n2["skin_removed_px"], 6400)
    check("mask = the band without its 4 corners", (bool((mask2 == want).all()), n2["piece_px"]), (True, 12796))


def gate_inputs(ghost_extra=None, hem_to=None):
    base, figure = base_view()
    region = band_mask()
    worn = base.copy()
    worn[region] = BLUE
    ghost_m = region.copy()
    if ghost_extra is not None:
        ghost_m |= ghost_extra
    if hem_to is not None:
        ghost_m[600:hem_to + 1, 120:280] = True
    ghost = np.full((H, W, 3), GREY, dtype=np.uint8)
    ghost[ghost_m] = BLUE
    return base, figure, region, ghost, ghost_m, worn


def strap(y_from):
    m = np.zeros((H, W), dtype=bool)
    m[y_from:600, 196:200] = True
    return m


def gate(gg, **kw):
    base, figure, region, ghost, ghost_m, worn = gate_inputs(**kw)
    return gg.ghost_clothing_gate(base, figure, region, ghost, ghost_m, view="front", worn_rgb=worn)


def part_gate():
    from app.core import garment_gates as gg
    print("[4] the gate: a thin added strap")
    rec = gate(gg, ghost_extra=strap(500))
    check("strap: reach, part, thick", (rec["added_reach"], rec["added_part"], rec["added_thick"]),
          (round(100 / 1399, 4), round(368 / 12800, 5), round(368 / 100 / 1399, 4)))
    check("strap: refused for it alone", (rec["ok"], rec["added_refused"], len(rec["reasons"]),
                                          rec["reasons"][0].startswith("a part the worn piece does not have")),
          (False, True, 1, True))
    check("strap: outside (the old measure)", rec["outside"], round(292 / 12800, 5))
    nub = gate(gg, ghost_extra=strap(570))
    check("nub: within the reach", (nub["added_reach"], nub["added_refused"], nub["ok"]),
          (round(30 / 1399, 4), False, True))
    hem = gate(gg, hem_to=739)
    check("a longer hem: no added part", (hem["added_reach"], hem["added_refused"]), (0.0, False))
    return rec


def part_old_code():
    print("[6] fails on the old code (" + OLD[:9] + ")")
    exists = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{OLD}:app/core/garment_from_worn.py"],
                            capture_output=True).returncode == 0
    check("garment_from_worn.py at the old commit", exists, False)
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/garment_gates.py"],
                            capture_output=True, text=True, check=True).stdout
    path = Path(tempfile.mkdtemp(prefix="a46-old-gates-")) / "old_garment_gates.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("old_garment_gates", path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    rec = gate(old, ghost_extra=strap(500))
    check("old gate: the strap passes", (rec["ok"], "added_reach" in rec, old.GHOST_GATE_VERSION), (True, False, 6))
    shutil.rmtree(path.parent, ignore_errors=True)


def setup() -> Path:
    """The throwaway storage + instance — first, before any app module is imported. Its root (the caller
    removes it)."""
    root = Path(tempfile.mkdtemp(prefix="piece-from-worn-"))
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
    shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
    from app.plugins.loader import discover_packages
    discover_packages(root / "plugins", force=True)
    return root


def world_parts():
    from app.core import garment_assembly, garment_from_worn as fw, garments
    from app.core import garment_store as gs
    from app.models import inventory
    from app.models.character import save_character_profile
    garment_assembly.schedule = lambda *a, **k: False
    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
             "character_appearance": "slender",
             "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"}, "build": {"type": "athletic"},
                            "hair": {"length": "medium", "color": "blonde"}}}
    check("create Demo", save_character_profile("Demo", human, create_new=True), True)

    def piece(name, slots, equip=True):
        iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a red {name.lower()}",
                                 outfit_piece={"slots": slots, "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
        check(f"inventory {name}", inventory.add_to_inventory("Demo", iid), True)
        if equip:
            check(f"equip {name}", inventory.equip_piece("Demo", iid, source="smoke")["status"], "ok")
        return iid

    def png(path: Path):
        from PIL import Image
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), (20, 20, 20)).save(path)

    def brief(r):
        return (r["source"], r["why"], r["detail"], r["auto"])

    print("[3] Auto")
    loose = piece("Shirt", ["top"])
    close = piece("Scale top", ["underwear_top"])
    fsig = gs.garment_fsig("Demo", close)
    check("loose", brief(fw.resolve("Demo", loose, gs.garment_fsig("Demo", loose), "front")),
          ("generated", "loose", "", False))
    check("close-fitting, no files", brief(fw.resolve("Demo", close, fsig, "back")), ("generated", "passes", "", True))
    for n, at in ((1, "2026-11-14T10:00:00"), (2, "2026-11-14T10:05:00")):
        path = gs.garment_path("Demo", close, fsig, "image", step="ghost", view="back", attempt=n)
        png(path)
        gs.write_record(path.with_suffix(".json"), {"created_at": at, "gate": {
            "ok": False, "reasons": [f"reason of attempt {n}"], "gate_version": 7}})
    check("both attempts refused", brief(fw.resolve("Demo", close, fsig, "back")),
          ("worn", "refused", "reason of attempt 2", True))
    final = gs.garment_path("Demo", close, fsig, "image", step="ghost", view="front")
    png(final)
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": {
        "ok": False, "added_refused": True, "added_reach": 0.0428, "gate_version": 7}}})
    check("accepted generated, added part", brief(fw.resolve("Demo", close, fsig, "front")),
          ("worn", "added", "0.0428", True))
    fw.set_choice("Demo", loose, "front", "worn")
    check("set worn on the loose piece", brief(fw.resolve("Demo", loose, gs.garment_fsig("Demo", loose), "front")),
          ("worn", "set_worn", "", False))
    fw.set_choice("Demo", close, "front", "generated")
    check("set generated on the added one", brief(fw.resolve("Demo", close, fsig, "front")),
          ("generated", "set_generated", "", False))
    fw.set_choice("Demo", close, "front", "auto")
    fw.set_choice("Demo", close, "back", "worn")
    check("stored", (inventory.get_item(close)["outfit_piece"].get("piece_views")), {"back": "worn"})
    inventory.update_item(close, {"outfit_piece": {"slots": ["underwear_top"], "mesh_mode": "own_mesh"}})
    check("an update that does not name it keeps it", inventory.get_item(close)["outfit_piece"].get("piece_views"),
          {"back": "worn"})
    fw.set_choice("Demo", close, "back", "auto")
    check("Auto drops the key", "piece_views" in inventory.get_item(close)["outfit_piece"], False)
    for path in final.parent.glob(f"{close}_*"):
        path.unlink()

    print("[5] the setting makes the cut-out, the mesh and the fit due")
    did = piece("Band top", ["underwear_top"])
    dsig = gs.garment_fsig("Demo", did)
    for step in ("worn", "ghost", "cutout"):
        for view in gs.GARMENT_VIEWS:
            path = gs.garment_path("Demo", did, dsig, "image", step=step, view=view)
            png(path)
            record = {"accepted": True, "attempt": 1, "gates": {"first": {"ok": True, "hem_t": 0.65,
                                                                          "gate_version": 7}}}
            if step == "worn" and view == "back":
                record["fit"] = "composite"
            gs.write_record(path.with_suffix(".json"), record)
    prepared = gs.garment_path("Demo", did, dsig, "prepared")
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_bytes(b"glb")
    gs.write_record(prepared.with_suffix(".json"), {"accepted": True})

    def est():
        r = garments.run_estimate("Demo", did)
        return (r["steps"], r["hub_jobs"], r["note"])

    check("everything done but the fit", est(), (["fit"], 0, "no hub job"))
    fw.set_choice("Demo", did, "back", "worn")
    check("back from the worn view", est(), (["ghost", "cutout", "mesh", "fit"], 2, "cutout 1 + mesh 1"))
    info = garments.piece_views_info("Demo", did, dsig)
    back, front = info["back"], info["front"]
    check("back: source, made from, due", (back["source"], back["made_from"], back["due"]),
          ("worn", "generated", [{"step": "ghost", "view": "back", "jobs": 0},
                                 {"step": "cutout", "view": "back", "jobs": 1},
                                 {"step": "mesh", "jobs": 1}, {"step": "fit", "jobs": 0}]))
    check("front: nothing due, its options", (front["due"], front["options"]["worn"]["due"],
                                              front["options"]["generated"]["due"]),
          ([], [{"step": "ghost", "view": "front", "jobs": 0}, {"step": "cutout", "view": "front", "jobs": 1},
                {"step": "mesh", "jobs": 1}, {"step": "fit", "jobs": 0}], []))
    fw.set_choice("Demo", did, "back", "generated")
    check("back generated: nothing due", est(), (["fit"], 0, "no hub job"))
    fw.set_choice("Demo", did, "back", "auto")
    check("back Auto: nothing due", est(), (["fit"], 0, "no hub job"))


def png_bytes(arr) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


def rembg_stub(data, model="u2net", **kwargs):
    """Every pixel more than 2 away from the grey is the figure (no model)."""
    import io
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB")).astype(np.int16)
    mask = ((np.abs(rgb - GREY) > 2).any(2) * 255).astype(np.uint8)
    return png_bytes(mask) if kwargs.get("only_mask") else png_bytes(np.dstack([rgb.astype(np.uint8), mask]))


def regate_part():
    import ast
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.core import base_body, garment_clothing, garment_from_worn as fw, garment_images, garments
    from app.core import garment_store as gs
    from app.models import character as charmod
    from app.models import inventory
    from app.models.character import get_character_dir
    print("[7] an accepted ghost gated under an older version is re-gated when shown (A46b)")
    charmod.run_rembg = rembg_stub
    base, _figure = base_view()
    refs = get_character_dir("Demo") / "model_refs"
    refs.mkdir(parents=True, exist_ok=True)
    bsig = base_body.base_signature("Demo")
    for v in base_body.BASE_VIEWS:
        stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
        (refs / f"{stem}.png").write_bytes(png_bytes(base))
        (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
    iid = inventory.add_item(name="Strap top", category="outfit_piece", prompt_fragment="a blue band top",
                             outfit_piece={"slots": ["underwear_top"], "outfit_types": ["casual"],
                                           "mesh_mode": "own_mesh"})["id"]
    check("inventory Strap top", inventory.add_to_inventory("Demo", iid), True)
    check("equip Strap top", inventory.equip_piece("Demo", iid, source="smoke")["status"], "ok")
    fsig = gs.garment_fsig("Demo", iid)
    _b, _f, _region, ghost, _ghost_m, worn = gate_inputs(ghost_extra=strap(500))
    for step, arr in (("worn", worn), ("ghost", ghost)):
        path = gs.garment_path("Demo", iid, fsig, "image", step=step, view="front")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(arr))
        gs.write_record(path.with_suffix(".json"), {
            "accepted": True, "attempt": 1, "created_at": "2026-11-14T10:00:00+00:00",
            "gates": {"first": {"view": "front", "ok": True, "reasons": [], "gate_version": 6, "attempt": 1}}})
    final = gs.garment_path("Demo", iid, fsig, "image", step="ghost", view="front")
    stored = final.read_bytes()

    calls = []
    real_gate = garment_clothing.gate

    def counted(*a, **k):
        calls.append(a[:2])
        return real_gate(*a, **k)

    garment_clothing.gate = counted

    def brief(view="front"):
        r = fw.resolve("Demo", iid, fsig, view)
        return (r["source"], r["why"], r["detail"])

    check("before: due, Auto reads the stored v6 record",
          (garment_images.regate_due("Demo", iid, fsig, "ghost", "front"), brief(),
           garments.piece_views_info("Demo", iid, fsig, checking=[])["front"]["due"]),
          (True, ("generated", "passes", ""), []))

    gate_open = threading.Event()
    garments._regate_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smoke-regate")
    garments._regate_worker.submit(gate_open.wait, 30)
    first = garments.regate_shown("Demo", iid, "clothing", fsig)
    again = garments.regate_shown("Demo", iid, "clothing", fsig)
    info = garments.piece_views_info("Demo", iid, fsig)
    check("shown: [ghost front] named, one task queued, front checking",
          (first, again, garments._regate_worker._work_queue.qsize(), info["front"]["checking"],
           info["back"].get("checking")),
          ([{"step": "ghost", "view": "front"}], [{"step": "ghost", "view": "front"}], 1, True, False))
    gate_open.set()
    garments._regate_worker.submit(lambda: None).result(timeout=60)
    record = gs.read_record(final.with_suffix(".json"))
    g = record["gates"]["first"]
    check("re-gated: version 7 from 6, refused for the strap",
          (g.get("gate_version"), g.get("regated_from"), g.get("ok"), g.get("added_refused"), g.get("added_reach")),
          (7, 6, False, True, round(100 / 1399, 4)))
    check("the gate ran once; the file unchanged and still accepted",
          (len(calls), final.read_bytes() == stored, record.get("accepted")), (1, True, True))
    info = garments.piece_views_info("Demo", iid, fsig)
    front = info["front"]
    check("Auto now: from the worn view, the added part",
          (front["source"], front["why"], front["detail"], front["made_from"], front["checking"]),
          ("worn", "added", str(round(100 / 1399, 4)), "generated", False))
    check("due: the view from the worn view, its cut-out, the mesh, the fit",
          front["due"], [{"step": "ghost", "view": "front", "jobs": 0}, {"step": "cutout", "view": "front", "jobs": 1},
                         {"step": "mesh", "jobs": 1}, {"step": "fit", "jobs": 0}])
    check("a second read re-gates nothing",
          (garment_images.regate_due("Demo", iid, fsig, "ghost", "front"),
           garments.regate_shown("Demo", iid, "clothing", fsig), garments._regate_worker._work_queue.qsize(),
           len(calls)), (False, [], 0, 1))
    payload = garments.garment_info("Demo", iid)
    check("the garment payload: nothing checking, Auto from the worn view, the ghost front refused",
          (payload["regate_checking"], payload["piece_views"]["front"]["source"],
           (payload["steps"]["ghost"]["front"].get("gates") or {}).get("first", {}).get("added_refused"), len(calls)),
          ([], "worn", True, 1))
    garment_clothing.gate = real_gate

    print("  fails on the old code (" + OLD_A46[:9] + ")")
    old_garments = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_A46}:app/core/garments.py"],
                                  capture_output=True, text=True, check=True).stdout
    old_images = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_A46}:app/core/garment_images.py"],
                                capture_output=True, text=True, check=True).stdout
    tree = ast.parse(old_garments)
    bodies = {n.name: ast.get_source_segment(old_garments, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    check("old: no regate_shown / regate_due; garment_info and piece_views_info re-gate nothing",
          ("regate_shown" in bodies, "def regate_due" in old_images,
           "regate" in bodies["garment_info"], "regate" in bodies["piece_views_info"]),
          (False, False, False, False))


def main() -> int:
    scratch = setup()
    try:
        part_mask()
        part_gate()
        part_old_code()
        world_parts()
        regate_part()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
