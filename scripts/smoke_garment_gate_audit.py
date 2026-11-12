#!/usr/bin/env python3
"""The verdicts of the clothing gate audit (2026-11-12,
``~/claude-out/gate-audit/report.md``): a gate refuses only what would put
something WRONG into the figure (app/core/garment_gates.py ``GARMENT_MIN``,
``OUTSIDE_DRIFT_PX``, ``ghost_clothing_gate`` / ``CLOTH_FAR`` / ``_hem_row``,
``WORN_GATE_VERSION`` 3, ``GHOST_GATE_VERSION`` 3; app/core/garment_images.py
``raw_path`` / ``_register`` / ``run_edit_step``'s re-gate; garment_store.py
``parse_name``).

Usage:
    ./.venv/bin/python scripts/smoke_garment_gate_audit.py

Throwaway storage + instance, a copy of the ``human`` package; no world, no
hub, no GPU, no server. REAL: the gates, the registration, run_edit_step.
Stubbed: the renderer (records every call), ``character.run_rembg`` (every
pixel more than 2 away from grey 128 is figure), ``get_image_service``
(raises). Needs git for [6] (the pinned old code).

Frame W 600 x H 1000 on grey 128, skin (200, 160, 140), black (20, 20, 20).
Margin at H 1000: round(8 x 1000 / 1536) = 5 iterations (an L1 diamond of
radius 5); the region's opening round(2 x 1000 / 1536) = 1 iteration (it
cuts the 4 corner pixels of a rectangle), closing 3.

  BASE  skin cols [120, 480) rows [100, 900): area 360 x 800 = 288000,
        y0 100, Hb 799; no neck -> head zone = rows < int(100 + 0.13 x 799)
        = 203 (rule "chin").

[1] Worn GARMENT_MIN 0.01 -> 0.002 (= GARMENT_MIN_COMPONENT: share >= 0.002
    means "one kept part"). Audit: Kira's choker 0.0049 / 0.0068 refused,
    the image right; nothing worn 0.0.
    CHOKER = BASE + black cols [259, 342) rows [300, 317) = 83 x 17 = 1411
    px, minus the 4 cut corners = 1407 -> share 1407 / 288000 = 0.0049 (the
    choker's), >= 576 px (0.002 x 288000) so the part is kept; outline
    unchanged (XOR 0), head zone untouched -> ok. Old: "nothing put on:
    garment 0.0049 < 0.01". NOTHING = BASE: share 0.0 -> refused. SPECK =
    BASE + black 20 x 20 = 400 - 4 = 396 px < 576 -> dropped -> 0.0 ->
    refused.
[2] Worn drift of an EDIT 1.5 -> 2.0 px. Audit: Glut's boots front 1.84
    (a uniform seam) refused, the boots right; Kira's skirt front 2.40 (the
    legs moved) refused.
    THIN = skin cols [250, 350) rows [100, 900): area 80000; its outline
    (mask minus its cross erosion) = 2 x 100 + 2 x 798 = 1796 px, all
    outside the grown garment. TOP = THIN + black cols [260, 340) rows
    [300, 500) (region 15996, grown to cols 255..344: never the outline).
    SEAM = TOP + skin cols [248, 250) rows [100, 900) and col 350 rows
    [100, 500): 2 x 800 + 400 = 2000 XOR px (2 px and 1 px wide outside the
    base mask: the region's opening drops them). xor 2000 / 80000 = 0.025,
    drift 2000 / 1796 x 1536 / 1000 = 1.71 px. Limit = max(0.015, d x
    1000 / 1536 x 1796 / 80000): old d 1.5 -> 0.0219 (0.025 >= -> refused),
    new d 2.0 -> 0.0292 -> ok. MOVED = TOP + 2 cols each side full height:
    3200 px, xor 0.04, drift 3200 / 1796 x 1.536 = 2.74 -> refused
    "(drift 2.74 px >= 2.0 px)".
[3] Ghost ``outside`` = the largest part beyond CLOTH_FAR (0.02 x 799 =
    15.98 px Euclidean) from the region; the near area is a warning.
    WORN_J = BASE + JACKET black cols [140, 460) rows [200, 600): region G_J
    = 128000 - 4 = 127996.
    RIM = the jacket 10 px larger all round, cols [130, 470) rows [190, 610)
    = 340 x 420 = 142800 px (the piece's own rim, Rosi's corset). Inside the
    margin: the region's L1-5 dilation = 128000 + 2 x 5 x 320 + 2 x 5 x 400
    + 4 x 10 (full-rectangle corner triangles) - 4 x 6 (the cut corner: a
    point at outward offset (dx, dy) is dx + dy + 1 from the region, one
    pixel lost on each axis line and 4 in the triangle) = 135216 ->
    beyond 142800 - 135216 = 7584 -> outside_near 7584 / 127996 = 0.05925
    (> 0.05: old refused). Farthest pixel: the ghost corner (130, 190) to
    the region pixel (141, 200) = sqrt(11² + 10²) = 14.87 < 15.98 ->
    outside 0.0 -> ok with the warning "garment rim beyond the worn piece".
    w_ratio 339 / 319 = 1.063, top_dy -10 / 799 = -0.01252 (warning).
    DRESS = the jacket + cols [140, 460) rows [600, 700) (a skirt drawn as a
    dress, the other way round): beyond rows 605..699 x 320 + 2 (row 604 at
    the cut corners) = 30402 -> outside_near 0.23752; far: a row r below
    the hem is r - 599 from row 599 (at cols 140 / 459 sqrt((r - 599)² + 1),
    the same rows), > 15.98 from r = 615: 85 x 320 = 27200 px, one part ->
    outside 27200 / 127996 = 0.21251 -> refused "more than the garment".
[4] ``length_free`` hem (``_hem_row``). Audit: Kira's skirt back, a slit and
    a re-shaded leg-edge strand in the worn region from the hem to row 1042;
    the correct attempt 2 counted its own slit tips.
    WORN_S = BASE + SKIRT black cols [200, 400) rows [450, 650) + STRAND
    (120, 90, 80) cols [380, 383) rows [650, 800) (|ΔRGB| to skin 70 > 20,
    3 px: survives the region's 1-iteration opening, which cuts the strand's
    2 bottom corners and the skirt's 4). The region's 3-iteration closing
    rounds the junction into a fillet: row 650 cols 377..385, 651 cols
    378..384, 652 cols 379..383 (12 px beside the strand). One part, area
    39996 + 448 + 12 = 40456, bbox bottom 799.
    ``_hem_row``: opened by 5 (L1 radius 5) the skirt's own diamonds reach
    row 649; a diamond centred at (649, 381) needs widths 9, 7, 5, 3, 1 on
    rows 650..654 around col 381 — the fillet and the strand, it fits; one
    at (650, 381) needs cols 379..383 on row 653 where the strand is 3 wide
    — no. The opened region ends at row 654 = hem_row (the bbox: 799).
    LONG = SKIRT 60 rows longer, rows [450, 710) (the edit's length).
    New: rows >= 654 + 1 + 5 = 660 are free; beyond the margin above that:
    rows 655..659 x (200 - 13 cols within 5 of the strand, cols 375..387)
    = 935 + row 654 at the cut corners cols 200 / 399 = 2 -> 937 px ->
    outside_near 937 / 40456 = 0.02316; nothing 15.98 away (row 659 is 10
    below the hem) -> outside 0.0, ok. With the bbox hem (799, the old
    ``a[3]``): the far rows r - 649 >= 16, rows 665..709 = 45, cols whose
    distance to the strand's cols 380..382 is >= 16: 200..364 (165) and
    398..399 (2, their own part) -> 165 x 45 = 7425 px -> outside 7425 /
    40456 = 0.18353 -> refused: the far rule alone does not free the slit.
[5] The raw sibling. Kai's "Jeans" back was rewritten as a 20 px jeans by a
    failed estimate and could never pass again. A character Demo with the
    accepted worn back WORN_J (base = BASE as its back), a JACKET piece
    (slot "outer": the outline registration).
    a) Stored ghost back try1 = SQUASHED (the jacket 20 px wide, cols [290,
       310), as an old overwrite left it), its version-2 record refused for
       the width with an APPLIED registration, raw sibling = SHIFTED (the
       jacket alone 12 rows low, rows [212, 612)). run_edit_step re-gates:
       the raw is copied back and registered again (|shift| 12 / 799 =
       0.015 <= 0.04, scale 1.0) -> the try file is the jacket in place,
       accepted, published, no render; the raw stays = SHIFTED.
    b) The same without the raw sibling: gated as stored -> w_ratio 19 /
       319 = 0.06 -> refused, then the step renders (stub: no image ->
       GateRefused).
    c) A fresh render of SHIFTED: the raw sibling is written with the
       rendered bytes before the registration rewrites the try file.
    d) A stale raw sibling and a render already in place (JACKET, a
       negligible correction): the raw goes.
    e) ``parse_name`` keeps a raw sibling in its (item, fsig) group (the
       sweeps delete it with the group).
[6] Fails on the old code (garment_gates.py PINNED at bc07100f, read with
    ``git show`` into a temp module): [1] CHOKER refused; [2] SEAM refused;
    [3] RIM refused; [4] LONG refused.
[7] Versions: WORN_GATE_VERSION 3, GHOST_GATE_VERSION 3,
    garment_clothing.GATE_VERSIONS = both -> a stored record of version 2 is
    stale (re-gated from its files by the next run, no image job), one of
    version 3 is not.
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

PINNED = "bc07100f"
FAILS = []
W, H = 600, 1000
HB = 799
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
BLACK = (20, 20, 20)
STRAND = (120, 90, 80)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
    if not ok:
        FAILS.append(label)


def has(record, key, text):
    return any(text in x for x in record.get(key) or [])


def canvas():
    return np.full((H, W, 3), GREY, dtype=np.uint8)


def mask_of(rgb):
    return np.abs(rgb.astype(np.int16) - 128).max(2) > 2


def png(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


BASE = canvas()
BASE[100:900, 120:480] = SKIN
CHOKER = BASE.copy()
CHOKER[300:317, 259:342] = BLACK
SPECK = BASE.copy()
SPECK[400:420, 290:310] = BLACK

THIN = canvas()
THIN[100:900, 250:350] = SKIN
TOP = THIN.copy()
TOP[300:500, 260:340] = BLACK
SEAM = TOP.copy()
SEAM[100:900, 248:250] = SKIN
SEAM[100:500, 350] = SKIN
MOVED = TOP.copy()
MOVED[100:900, 248:250] = SKIN
MOVED[100:900, 350:352] = SKIN

WORN_J = BASE.copy()
WORN_J[200:600, 140:460] = BLACK


def piece(rows, cols):
    img = canvas()
    img[rows[0]:rows[1], cols[0]:cols[1]] = BLACK
    return img


JACKET = piece((200, 600), (140, 460))
RIM = piece((190, 610), (130, 470))
DRESS = piece((200, 700), (140, 460))
SHIFTED = piece((212, 612), (140, 460))
SQUASHED = piece((200, 600), (290, 310))

WORN_S = BASE.copy()
WORN_S[450:650, 200:400] = BLACK
WORN_S[650:800, 380:383] = STRAND
LONG = piece((450, 710), (200, 400))


def pinned(commit, name, tmp):
    """app/core/<name>.py at ``commit`` as a throwaway module."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:app/core/{name}.py"],
                         check=True, capture_output=True, text=True).stdout
    path = Path(tmp) / f"{name}_{commit}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(f"{name}_{commit}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB"))
    mask = (mask_of(rgb) * 255).astype(np.uint8)
    return png(mask) if kwargs.get("only_mask") else png(np.dstack([rgb, mask]))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-gate-audit-") as tmp:
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

        from app.core import base_body, expression_regen, garment_clothing, garment_images
        from app.core import garment_gates as gg
        from app.core import garment_store as gs
        from app.imagegen import service as imgservice
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        charmod.run_rembg = rembg_stub
        jobs = []

        def no_image_job(*a, **k):
            jobs.append(a)
            raise AssertionError("no image job in this smoke")
        imgservice.get_image_service = no_image_job
        old = pinned(PINNED, "garment_gates", tmp)

        def worn(module, base, arr, **kw):
            return module.worn_gate(base, mask_of(base), arr, mask_of(arr), view="front", **kw)

        def ghost(module, base, worn_arr, arr, length_free=False):
            region = module.garment_region(base, mask_of(base), worn_arr, mask_of(worn_arr))
            return module.ghost_clothing_gate(base, mask_of(base), region, arr, mask_of(arr), view="back",
                                              length_free=length_free)

        print("[1] worn GARMENT_MIN")
        check("GARMENT_MIN = GARMENT_MIN_COMPONENT", (gg.GARMENT_MIN, gg.GARMENT_MIN_COMPONENT), (0.002, 0.002))
        choker = worn(gg, BASE, CHOKER)
        check("choker 0.0049: ok", (choker["ok"], choker["garment_share"], choker["outside_xor"],
                                    choker["head_garment"], choker["reasons"]), (True, 0.0049, 0.0, 0.0, []))
        check("choker region px", int(gg.garment_region(BASE, mask_of(BASE), CHOKER, mask_of(CHOKER)).sum()), 1407)
        nothing = worn(gg, BASE, BASE)
        check("nothing worn: refused", (nothing["ok"], nothing["garment_share"], nothing["reasons"]),
              (False, 0.0, ["nothing put on: garment 0.0 < 0.002"]))
        speck = worn(gg, BASE, SPECK)
        check("speck below the kept-part size: refused", (speck["ok"], speck["garment_share"]), (False, 0.0))

        print("[2] worn drift of an edit")
        check("drift limit", gg.OUTSIDE_DRIFT_PX, 2.0)
        seam = worn(gg, THIN, SEAM)
        check("seam 1.71 px: ok", (seam["ok"], seam["outside_outline"], seam["outside_xor"], seam["outside_drift_px"],
                                   seam["outside_xor_limit"]), (True, 1796, 0.025, 1.71, 0.0292))
        moved = worn(gg, THIN, MOVED)
        check("moved 2.74 px: refused", (moved["ok"], moved["outside_drift_px"],
                                         has(moved, "reasons", "(drift 2.74 px >= 2.0 px)")), (False, 2.74, True))

        print("[3] ghost outside: the far part")
        rim = ghost(gg, BASE, WORN_J, RIM)
        check("rim: ok, near recorded", (rim["ok"], rim["outside"], rim["outside_near"], rim["w_ratio"], rim["top_dy"],
                                         has(rim, "warnings", "garment rim beyond the worn piece"), rim["reasons"]),
              (True, 0.0, 0.05925, 1.063, -0.01252, True, []))
        dress = ghost(gg, BASE, WORN_J, DRESS)
        check("dress: refused", (dress["ok"], dress["outside"], dress["outside_near"],
                                 has(dress, "reasons", "more than the garment in the image")),
              (False, 0.21251, 0.23752, True))
        check("limit chip gates the far part", gg.limits("clothing")["ghost"]["outside"], {"op": "le", "value": 0.05})

        print("[4] length_free hem")
        region_s = gg.garment_region(BASE, mask_of(BASE), WORN_S, mask_of(WORN_S))
        check("region bbox bottom (the strand)", gg._bbox(region_s)[3], 799)
        check("region area", int(region_s.sum()), 40456)
        check("hem row", gg._hem_row(region_s, H), 654)
        long = ghost(gg, BASE, WORN_S, LONG, length_free=True)
        check("long skirt: ok", (long["ok"], long["outside"], long["hem_row"]), (True, 0.0, 654))
        check("long skirt: near", long["outside_near"], 0.02316)
        keep_hem = gg._hem_row
        gg._hem_row = lambda region, height: gg._bbox(region)[3]
        try:
            bbox_hem = ghost(gg, BASE, WORN_S, LONG, length_free=True)
        finally:
            gg._hem_row = keep_hem
        check("bbox hem: far part, refused", (bbox_hem["outside"], bbox_hem["ok"]), (0.18353, False))

        print("[5] the raw sibling")
        human = {"template": "human-roleplay", "gender": "male", "age": 30, "height": 180,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        jid = inventory.add_item(name="Black Jacket", category="outfit_piece",
                                 prompt_fragment="a black jacket",
                                 outfit_piece={"slots": ["outer"], "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
        check("inventory", inventory.add_to_inventory("Demo", jid), True)
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png(BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
        fsig = gs.garment_fsig("Demo", jid)

        def image(step, view, attempt=0):
            return gs.garment_path("Demo", jid, fsig, "image", step=step, view=view, attempt=attempt)

        worn_back = image("worn", "back")
        worn_back.parent.mkdir(parents=True, exist_ok=True)
        worn_back.write_bytes(png(WORN_J))
        gs.write_record(worn_back.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": {"ok": True}}})
        renders = []
        rendered = {"ghost": None}

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            renders.append(f"{g['step']} {g['view'][0]}{g.get('attempt', 'd')}")
            arr = rendered.get(g["step"])
            if arr is None:
                return None
            out = np.full((kw["override_height"], kw["override_width"], 3), 128, dtype=np.uint8)
            dy, dx = (out.shape[0] - arr.shape[0]) // 2, (out.shape[1] - arr.shape[1]) // 2
            out[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            path = Path(str(output_stem) + ".png")
            path.write_bytes(png(out))
            path.with_suffix(".json").write_text(json.dumps(kw["sidecar_extra"]))
            return path
        expression_regen.render_character_image = recorder

        ghost_final, try1, try2 = image("ghost", "back"), image("ghost", "back", 1), image("ghost", "back", 2)
        raw1 = garment_images.raw_path(try1)
        check("raw name", raw1.name, f"{jid}_{fsig}_ghost_back.try1.raw.png")

        def read(path):
            from PIL import Image
            with Image.open(path) as im:
                return np.asarray(im.convert("RGB"))

        def stage(with_raw):
            for p in (ghost_final, ghost_final.with_suffix(".json"), try1, try1.with_suffix(".json"), try2,
                      try2.with_suffix(".json"), raw1):
                p.unlink(missing_ok=True)
            try1.write_bytes(png(SQUASHED))
            if with_raw:
                raw1.write_bytes(png(SHIFTED))
            stored = ghost(gg, BASE, WORN_J, SQUASHED)
            stored.update(gate_version=2, attempt=1, registration={"applied": True, "scale": 0.06},
                          reg_shift=0.0, reg_scale=0.06)
            gs.write_record(try1.with_suffix(".json"), {"garment": {"item_id": jid, "fsig": fsig, "step": "ghost",
                                                                    "view": "back", "attempt": 1}, "gate": stored})

        stage(True)
        got = garment_images.run_edit_step("Demo", jid, fsig, "ghost", "back")
        record = gs.read_record(ghost_final.with_suffix(".json"))
        first = (record.get("gates") or {}).get("first") or {}
        reg = first.get("registration") or {}
        check("a) re-registered from the raw: accepted, no render",
              (got == ghost_final, renders, jobs, record.get("accepted"), first.get("ok"), first.get("regated_from"),
               first.get("gate_version"), reg.get("applied")), (True, [], [], True, True, 2, 3, True))
        near("a) shift rows", (reg.get("shift_px") or [0])[0], -12.0, 0.5)
        check("a) the try file is the jacket in place, the raw as rendered",
              (int((mask_of(read(try1)) ^ mask_of(JACKET)).sum()) <= 2 * 320, bool((read(raw1) == SHIFTED).all()),
               read(ghost_final).tobytes() == read(try1).tobytes()), (True, True, True))

        stage(False)
        del renders[:]
        try:
            garment_images.run_edit_step("Demo", jid, fsig, "ghost", "back")
            refused = None
        except garment_images.GateRefused as exc:
            refused = exc
        sidecar = gs.read_record(try1.with_suffix(".json")).get("gate") or {}
        check("b) without the raw: gated as stored, refused, rendered",
              (refused is not None, sidecar.get("w_ratio"), sidecar.get("regated_from"), renders),
              (True, 0.06, 2, ["ghost b1", "ghost b2"]))

        for p in (ghost_final, ghost_final.with_suffix(".json"), try1, try1.with_suffix(".json"), raw1):
            p.unlink(missing_ok=True)
        del renders[:]
        rendered["ghost"] = SHIFTED
        garment_images.run_edit_step("Demo", jid, fsig, "ghost", "back", force=True)
        rec = (gs.read_record(ghost_final.with_suffix(".json")).get("gates") or {}).get("first") or {}
        check("c) fresh render: raw kept as rendered, try file moved",
              (renders, rec.get("ok"), (rec.get("registration") or {}).get("applied"), raw1.is_file(),
               raw1.is_file() and bool((read(raw1) == SHIFTED).all()), bool((read(try1) == SHIFTED).all())),
              (["ghost b1"], True, True, True, True, False))

        del renders[:]
        rendered["ghost"] = JACKET
        raw1.write_bytes(png(SHIFTED))
        garment_images.run_edit_step("Demo", jid, fsig, "ghost", "back", force=True)
        rec = (gs.read_record(ghost_final.with_suffix(".json")).get("gates") or {}).get("first") or {}
        check("d) in place: no correction, the stale raw goes",
              (renders, rec.get("ok"), (rec.get("registration") or {}).get("applied"), raw1.exists()),
              (["ghost b1"], True, False, False))
        check("e) raw in the group", gs.parse_name(raw1), (jid, fsig))

        print(f"[6] fails on the old code ({PINNED})")
        check("old [1]: choker refused", worn(old, BASE, CHOKER)["reasons"], ["nothing put on: garment 0.0049 < 0.01"])
        old_seam = worn(old, THIN, SEAM)
        check("old [2]: seam refused", (old_seam["ok"], has(old_seam, "reasons", "(drift 1.71 px >= 1.5 px)")),
              (False, True))
        old_rim = ghost(old, BASE, WORN_J, RIM)
        check("old [3]: rim refused", (old_rim["ok"], old_rim["outside"]), (False, 0.05925))
        check("old [4]: long skirt refused", ghost(old, BASE, WORN_S, LONG, length_free=True)["ok"], False)

        print("[7] versions")
        check("versions", (gg.WORN_GATE_VERSION, gg.GHOST_GATE_VERSION, garment_clothing.GATE_VERSIONS),
              (3, 3, {"worn": 3, "ghost": 3}))
        check("version 2 stale", (garment_images._stale_gate(garment_clothing, "ghost", {"gate_version": 2}),
                                  garment_images._stale_gate(garment_clothing, "worn", {"gate_version": 2})),
              (True, True))
        check("version 3 not stale", garment_images._stale_gate(garment_clothing, "ghost", {"gate_version": 3}), False)

    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
