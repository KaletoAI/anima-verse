#!/usr/bin/env python3
"""Smoke: ``HEAD_VERSION == 2`` head-zone polish in ``app/core/view_composite.py``
and ``app/core/base_body.py`` — feathered ``cut_row`` ramp, removed base hair
below ``cut_row``, ``removed_hair_exclude`` in ``put_on`` / ``garment_bands`` /
``front_garment_bands``, ``seam_ratio`` and ``head_likeness`` checks, and
``head_composite_outdated`` version check.

Usage:
    ./.venv/bin/python scripts/smoke_head_hair_polish.py

Runs without a server, a hub or a GPU: pure RGBA arrays and a temp dir for PNG
round-trips; outbound socket connects are refused and counted. Old-code proofs
load ``c5742f5f1:app/core/view_composite.py`` (and ``head_match`` from
``c5742f5f1:app/core/base_body.py``) directly from git.

Fixtures (800 rows x 400 columns, RGBA, transparent background; boxes half-open;
SKIN (224, 172, 140), SKIN2 (200, 150, 120), BLUE (40, 70, 200),
HAIR (90, 55, 30), BLOND (204, 154, 122)):
    Shared body (figure rows 20..780 = height 760, cols 65..335 = centre 200):
      shoulders rows 150..155, cols  65..335 SKIN (connects arms to torso)
      torso     rows 150..420, cols 112..288 SKIN
      arms      rows 155..420, cols  65..95 and 305..335 SKIN (armpit gap 95..112 / 288..305)
      legs      rows 420..780, cols 120..195 and 205..280 SKIN
    BASE [A] (haired front):
      hair block rows  20..150, cols 140..260 HAIR, with SKIN face rows 40..110, cols 170..230
      curtains   rows 150..300, cols 120..140 and 260..280 HAIR (over torso)
      strands    rows 156..260, cols 100..110 and 290..300 HAIR (in armpit gap; draft transparent)
    DRAFT [A] (bald front, bare):
      head rows 20..110, cols 160..240 SKIN; neck rows 110..150, cols 185..215 SKIN; + shared body.

Expected values, derived by hand:

[A] Long strands:
    * ``_head_zone`` on DRAFT [A]: rows 20..780 (height 760); neck band 65..187 ->
      narrowest row 110 (width 30); first row >= 60 wide = 150 -> ``cut_row`` =
      150 + round(0.04 * 760) = 180; feather ramp ``n = round(0.02 * 760) = 15``.
    * New code: ``removed`` covers both torso curtains (rows 150..300) and both
      armpit strands (rows 156..260, linked across the 6 px gap at row 150..156
      by ``round(0.0046 * 760) = 3`` px dilation to rows < 180) -> 0 pixels at
      rows >= 180 within Lab ΔE76 10 of HAIR in the grey-flattened composite.
      On the outside strands (cols 100..110, 290..300) at rows 190..255, draft
      alpha is 0: 0 figure pixels (alpha > 127) remain, and in the strand core
      cols 104..106 / 294..296 (> 3 * sigma = 4.56 px from the strand edge, where
      ``gaussian_filter(..., 1.52)`` > 0.998) uint8 alpha == 0.
    * Old code (``c5742f5f1``): outside strands below the 1.2 px zone feather
      (rows 182..260 = 78 rows x 2 x 10 cols = 1560 px, plus 24 px at row 181 =
      1584 px) keep HAIR (ΔE < 10) and alpha 255; and when the curtains are
      skin-close BLOND (204, 154, 122) (ΔE ~9.2 < ``DE_GARMENT`` 16, > ``HAIR_DE``
      6), ``c5742f5f1`` keeps all 2 * (300 - 180) * 20 = 4800 curtain pixels
      at rows >= 180 within ΔE 4 of BLOND while new code keeps 0 below the
      feather ramp (rows >= 188).

[B] Collar over former hair:
    * DRAFT [B] = DRAFT [A] + BLUE collar rows 140..178, cols 150..250.
    * At ``PUT_ON_WORK_HEIGHT = 192`` (scale 192 / 800 = 0.24, cell = 4.17 px,
      96 x 192 grid): base figure has ~7857 cells (rows 5..186, ``head`` =
      5 + round(0.12 * 182) = 27). Collar spans cell rows 34..42 (9 rows, minus
      corner rounding from 1-cell opening -> ~186 cells) x cols 36..60 (24 cols)
      all below ``head`` -> share ~186 / 7857 = 0.0237 (in 0.020..0.028, equal
      within 0.002 to the collar share on a curtain-free base). Curtains span
      cell rows 36..72 x 2 * 5 cols -> ~412 cells = 0.0524.
    * New code: ``coverage["region"]`` on [A] (no collar) == 0.0; on [B] in
      0.020..0.028 (collar kept, curtains excluded). Old code (``c5742f5f1``):
      [B] includes curtains -> ~0.0237 + 0.0524 = 0.0761 (> 0.065).

[C] Seam at ``cut_row``:
    * Base torso SKIN (224, 172, 140), draft head/neck/torso/limbs SKIN2
      (200, 150, 120), no hair below row 150. Raw 4-channel jump = (24 + 22 +
      20 + 0) / 4 = 16.5; after ``_seam_colour_match`` old code still steps by
      ~3.9 at row 180 (> ``HEAD_SEAM_MAX`` 2.0), whereas new code spreads the
      transition across ``n = 15`` rows (step ~16.5 / 15 = 1.1, softened to
      ~0.97 by seam matching; local median < ``SEAM_FLOOR`` 1.0 -> ratio <= 2.0).
    * ``check()`` on records: ``seam_ratio`` 3.0, ``draft_seam_ratio`` 1.0 ->
      ``HEAD_SEAM``; 3.0 with draft 3.5 -> []; missing -> [].

[D] Head-taken gate:
    * ``check()`` on records: ``composite_head_match`` 0.85 -> ``HEAD_NOT_TAKEN``;
      0.95 -> []; missing -> [].
    * On [A]: ``composite_head_match >= 0.9``, ``draft_head_match < 0.9``;
      ``head_likeness(base_a, base_a) == 1.0``.

[E] Byte-identity without ``head``:
    * ``compose(..., head=False, base_alpha=True)`` writes byte-identical PNGs
      and equal records (``runtime_s`` aside) under new code and ``c5742f5f1``.

[F] ``head_composite_outdated(head_changed=True)``:
    * ``{"alpha": "base", "head": {"alpha": "draft"}}`` -> True (version 1 < 2);
      with ``"version": HEAD_VERSION`` -> False.

[G] ``base_body.head_match`` unchanged vs ``c5742f5f1``:
    * Exact equality between ``c5742f5f1`` ``head_match`` and current
      ``base_body.head_match`` on saved [A] PNGs and (when present) on the
      Liv and Sigrun reference pairs.

[H] Bald back not refused as EMPTY / nothing-put-on:
    * Back fixture: haired back (hair block 20..150 cols 140..260 + back curtain
      150..300 cols 150..250 HAIR) + bald bare back draft.
    * ``_composite(..., take_head=True, base_alpha=True)`` with ``front_region=None``
      and with ``front_region`` = [A]'s new ``coverage["region"]`` (0.0 <
      ``EMPTY_FRONT_MAX`` 0.0333, whereas ``c5742f5f1`` on [A] gives ~0.0524 >
      ``EMPTY_FRONT_MAX``): both ``ok`` True, no ``NOTHING_ALTHOUGH_DRESSED`` /
      ``NOTHING_TO_PUT_ON``, ``empty`` falsy.
    * ``check({"iou": 0.95, "coverage": {"nothing": True, "region": 0.0},
      "front_region": rec_a["coverage"]["region"]})`` -> [].

[I] ``garment_bands`` and ``front_garment_bands``:
    * On [A]: ``garment_bands(base, out)`` band 0 > 0.10 (~170 curtain cells /
      ~1005 band-0 figure cells = 0.169), equal to ``c5742f5f1`` ``garment_bands``;
      with ``exclude=removed_hair_exclude(base, out, 180)`` band 0 == 0.0.
      ``front_garment_bands`` on saved [A] front with ``edit_composite.head.cut_row
      == 180`` gives band 0 == 0.0 (without ``head``: > 0.10).
    * On saved [H] back (``_ref_sidecar`` reads ``<stem>.json`` beside ``<stem>.png``):
      with ``{"composite": {"head": {"cut_row": 180}}}`` ``front_garment_bands``
      gives band 0 == 0.0 (the wide back curtain rows 150..300 cols 150..250,
      ~17 x 24 = ~408 band-0 cells / ~1005 figure cells = ~0.40 without ``head``,
      is excluded via ``composite.head.cut_row``).
    * On [B] (collar): ``garment_bands(..., exclude=...)`` keeps the collar in
      band 0 (~0.139, in 0.10..0.18) and drops the lower curtains in band 1 (0.0).

[J] Soft hair edge / no darkened chest patch:
    * With a uniform HAIR (90, 55, 30) sample in the head zone, ``cov = 0`` so
      ``icov = inv(0 + I) = I`` and ``Mahalanobis < HAIR_MAHA`` (3.0) requires
      Lab ΔE76 < 3.0 from HAIR. The midpoint SHADOW = (157, 113, 85) has
      ΔE76(SHADOW, HAIR) = 24.71 >= 3.0, so it is NOT hair-like unless either:
      (1) the band colour lies within ΔE76 < 3.0 of HAIR under a uniform head
          sample — ``HAIR_EDGE = (96, 60, 34)`` (ΔE76 ~ 2.3 < 3.0 from HAIR,
          ΔE76 ~ 52 > ``HAIR_DE`` 6.0 from SKIN), or
      (2) the head hair in the zone carries the same soft skin-shadow fringe —
          ``SHADOW_SKIN = (204, 155, 124)`` (``skin_b.like`` True, ΔE76 ~ 6.9
          from SKIN: > ``HAIR_DE`` 6.0, < ``DE_GARMENT`` 16.0) on cols 140..152
          and 248..260 of the head hair block (>= 25% of the hair-only sample ->
          2-point mixture ``Mahalanobis <= sqrt((1 - p) / p) <= 1.73 < 3.0``).
    * Both 3 px curtain-edge variants (cols 117..120 / 140..143 and 257..260 /
      280..283, rows 150..300, over SKIN torso) are tested: ``removed`` covers
      curtain + 3 px band grown by ``round(0.003 * 760) = 2`` px (cols 115..145
      and 255..285), placing ``_seam_colour_match``'s 6 px skin ring on clean
      SKIN outside ``mask_ramp | removed`` where base == draft == SKIN (offset 0).
      In the curtain cores (cols 125..135 and 265..275, rows 200..290) the
      grey-flattened composite RGB is within Lab ΔE76 3.0 of SKIN, and ``ok`` is
      True.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
from skimage import color

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLD_COMMIT = "c5742f5f1"
FAILS: list[str] = []
SKIN = (224, 172, 140)
SKIN2 = (200, 150, 120)
BLUE = (40, 70, 200)
HAIR = (90, 55, 30)
BLOND = (204, 154, 122)

LIMBS = [
    (150, 155, 65, 335, SKIN),
    (155, 420, 65, 95, SKIN),
    (155, 420, 305, 335, SKIN),
    (420, 780, 120, 195, SKIN),
    (420, 780, 205, 280, SKIN),
]


def check(label: str, got, want) -> None:
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300]
          + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def figure(parts) -> np.ndarray:
    a = np.zeros((800, 400, 4), dtype=np.float64)
    for y0, y1, x0, x1, col in parts:
        a[y0:y1, x0:x1, :3] = col
        a[y0:y1, x0:x1, 3] = 255.0
    return a


def save_png(arr: np.ndarray, path: Path) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA").save(path)
    return path


def load_old_view_composite():
    proc = subprocess.run(
        ["git", "show", f"{OLD_COMMIT}:app/core/view_composite.py"],
        cwd=str(ROOT), capture_output=True, text=True, check=True,
    )
    mod_name = "app.core._view_composite_old_c5742f5f1"
    mod = types.ModuleType(mod_name)
    mod.__file__ = f"<git:{OLD_COMMIT}:app/core/view_composite.py>"
    sys.modules[mod_name] = mod
    exec(compile(proc.stdout, mod.__file__, "exec"), mod.__dict__)
    return mod


def load_old_head_match():
    """Extract pure ``head_match`` + helpers from ``c5742f5f1:app/core/base_body.py``."""
    proc = subprocess.run(
        ["git", "show", f"{OLD_COMMIT}:app/core/base_body.py"],
        cwd=str(ROOT), capture_output=True, text=True, check=True,
    )
    tree = ast.parse(proc.stdout)
    wanted_funcs = {"_head_image", "_head_vector", "head_match"}
    wanted_assigns = {"VIEW_GUARD_HEAD_SHARE", "VIEW_GUARD_SIZE", "HEAD_MATCH_MIN"}
    kept = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            kept.append(node)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & wanted_assigns:
                kept.append(node)
    sub = ast.Module(body=kept, type_ignores=[])
    ns: dict = {"Path": Path, "Optional": object}
    exec(compile(sub, f"<git:{OLD_COMMIT}:app/core/base_body.py>", "exec"), ns)
    return ns["head_match"]


def de_to_colour(flat_rgb: np.ndarray, target_rgb: tuple[int, int, int]) -> np.ndarray:
    t_lab = color.rgb2lab(np.array([[target_rgb]], dtype=np.float64) / 255.0)[0, 0]
    return np.linalg.norm(color.rgb2lab(flat_rgb / 255.0) - t_lab, axis=-1)


def main() -> int:
    outbound: list = []

    def no_network(self, address, *_a, **_k):
        outbound.append(address)
        raise OSError("no network in this smoke")

    socket.socket.connect = no_network

    with tempfile.TemporaryDirectory(prefix="head-hair-polish-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")

        from app.core import base_body, view_composite as vc

        old_vc = load_old_view_composite()
        old_head_match = load_old_head_match()

        base_a = figure([
            (20, 150, 140, 260, HAIR),
            (40, 110, 170, 230, SKIN),
            (150, 420, 112, 288, SKIN),
            (150, 300, 120, 140, HAIR),
            (150, 300, 260, 280, HAIR),
            (156, 260, 100, 110, HAIR),
            (156, 260, 290, 300, HAIR),
        ] + LIMBS)
        draft_a = figure([
            (20, 110, 160, 240, SKIN),
            (110, 150, 185, 215, SKIN),
            (150, 420, 112, 288, SKIN),
        ] + LIMBS)

        print("[A] long hair curtains and outside strands")
        out_a, rec_a, _sup_a = vc._composite(base_a, draft_a, "outfit", take_head=True, base_alpha=True)
        old_a, old_rec_a, _ = old_vc._composite(base_a, draft_a, "outfit", take_head=True, base_alpha=True)
        check("cut_row == 180, version == 2, ok",
              (rec_a["head"]["cut_row"], rec_a["head"]["version"], rec_a["ok"]),
              (180, vc.HEAD_VERSION, True))
        flat_new = np.asarray(vc.to_image(out_a, vc.GREY), dtype=np.float64)
        flat_old = np.asarray(vc.to_image(old_a, vc.GREY), dtype=np.float64)
        check("new: 0 HAIR px (dE < 10) at rows >= 180",
              int((de_to_colour(flat_new[180:], HAIR) < 10.0).sum()), 0)
        u8_new = np.clip(np.round(out_a), 0, 255).astype(np.uint8)
        u8_old = np.clip(np.round(old_a), 0, 255).astype(np.uint8)
        check("new: outside strands rows 190..255 have 0 figure px (alpha > 127)",
              int((u8_new[190:255, 100:110, 3] > vc.FIGURE_ALPHA).sum())
              + int((u8_new[190:255, 290:300, 3] > vc.FIGURE_ALPHA).sum()),
              0)
        check("new: outside strand cores rows 190..255 have alpha == 0",
              int(u8_new[190:255, 104:106, 3].max()) + int(u8_new[190:255, 294:296, 3].max()),
              0)
        check("old (c5742f5f1): outside strands rows 190..260 keep alpha 255 (2*70*10=1400)",
              int((u8_old[190:260, 100:110, 3] == 255).sum())
              + int((u8_old[190:260, 290:300, 3] == 255).sum()),
              1400)
        check("old (c5742f5f1): 1584 HAIR px at rows >= 180",
              int((de_to_colour(flat_old[180:], HAIR) < 10.0).sum()), 1584)

        base_blond = figure([
            (20, 150, 140, 260, BLOND),
            (40, 110, 170, 230, SKIN),
            (150, 420, 112, 288, SKIN),
            (150, 300, 120, 140, BLOND),
            (150, 300, 260, 280, BLOND),
        ] + LIMBS)
        out_bl_new, _, _ = vc._composite(base_blond, draft_a, "outfit", take_head=True, base_alpha=True)
        out_bl_old, _, _ = old_vc._composite(base_blond, draft_a, "outfit", take_head=True, base_alpha=True)
        flat_bl_new = np.asarray(vc.to_image(out_bl_new, vc.GREY), dtype=np.float64)
        flat_bl_old = np.asarray(vc.to_image(out_bl_old, vc.GREY), dtype=np.float64)
        check("blond curtains old (c5742f5f1): 4800 BLOND px at rows >= 180 (2*120*20)",
              int((de_to_colour(flat_bl_old[180:], BLOND) < 4.0).sum()), 4800)
        check("blond curtains new: 0 BLOND px below feather ramp (rows >= 188)",
              int((de_to_colour(flat_bl_new[188:], BLOND) < 4.0).sum()), 0)

        print("[B] collar over former hair")
        draft_b = figure([
            (20, 110, 160, 240, SKIN),
            (110, 150, 185, 215, SKIN),
            (150, 420, 112, 288, SKIN),
            (140, 178, 150, 250, BLUE),
        ] + LIMBS)
        base_bare = figure([
            (20, 150, 140, 260, HAIR),
            (40, 110, 170, 230, SKIN),
            (150, 420, 112, 288, SKIN),
        ] + LIMBS)
        out_b, rec_b, _ = vc._composite(base_a, draft_b, "outfit", take_head=True, base_alpha=True)
        _, rec_b_bare, _ = vc._composite(base_bare, draft_b, "outfit", take_head=True, base_alpha=True)
        _, old_rec_b, _ = old_vc._composite(base_a, draft_b, "outfit", take_head=True, base_alpha=True)
        reg_b = rec_b["coverage"]["region"]
        reg_b_bare = rec_b_bare["coverage"]["region"]
        old_reg_b = old_rec_b["coverage"]["region"]
        check("new without collar: coverage.region == 0.0", rec_a["coverage"]["region"], 0.0)
        check("new with collar: region in 0.020..0.028 (~186/7857 = 0.0237)",
              0.020 <= reg_b <= 0.028, True)
        check("new with collar matches curtain-free collar share within 0.002",
              abs(reg_b - reg_b_bare) <= 0.002, True)
        check("old with collar includes curtains (~0.0761 > 0.065)",
              old_reg_b > 0.065, True)

        print("[C] seam metric and check()")
        limbs_s2 = [(y0, y1, x0, x1, SKIN2) for (y0, y1, x0, x1, _) in LIMBS]
        draft_c = figure([
            (20, 110, 160, 240, SKIN2),
            (110, 150, 185, 215, SKIN2),
            (150, 420, 112, 288, SKIN2),
        ] + limbs_s2)
        out_c_new, rec_c_new, _ = vc._composite(base_bare, draft_c, "outfit", take_head=True, base_alpha=True)
        out_c_old, _, _ = old_vc._composite(base_bare, draft_c, "outfit", take_head=True, base_alpha=True)
        old_sr = vc.seam_ratio(out_c_old, 180, 15)
        check("new seam_ratio <= HEAD_SEAM_MAX (about 16.5/15 = 1.1)",
              rec_c_new["head"]["seam_ratio"] <= vc.HEAD_SEAM_MAX, True)
        check("old seam_ratio > HEAD_SEAM_MAX (~3.9 > 2.0)",
              old_sr is not None and old_sr > vc.HEAD_SEAM_MAX, True)
        base_rec = {"iou": 0.99, "coverage": {"score": 0.9, "region": 0.2}}
        check("check seam 3.0 vs draft 1.0 -> HEAD_SEAM",
              vc.check({**base_rec, "head": {"seam_ratio": 3.0, "draft_seam_ratio": 1.0}}),
              [f"{vc.HEAD_SEAM} (ratio 3.00 > {vc.HEAD_SEAM_MAX})"])
        check("check seam 3.0 vs draft 3.5 -> []",
              vc.check({**base_rec, "head": {"seam_ratio": 3.0, "draft_seam_ratio": 3.5}}), [])
        check("check seam missing -> []",
              vc.check({**base_rec, "head": {"cut_row": 180}}), [])

        print("[D] head-taken gate and head_likeness")
        check("check composite_head_match 0.85 -> HEAD_NOT_TAKEN",
              vc.check({**base_rec, "head": {"composite_head_match": 0.85}}),
              [f"{vc.HEAD_NOT_TAKEN} (head match 0.850 < {vc.HEAD_TAKEN_MIN})"])
        check("check composite_head_match 0.95 -> []",
              vc.check({**base_rec, "head": {"composite_head_match": 0.95}}), [])
        check("check composite_head_match missing -> []",
              vc.check({**base_rec, "head": {}}), [])
        check("[A] composite_head_match >= 0.9 and draft_head_match < 0.9",
              (rec_a["head"]["composite_head_match"] >= 0.9, rec_a["head"]["draft_head_match"] < 0.9),
              (True, True))
        check("head_likeness(base_a, base_a) == 1.0", vc.head_likeness(base_a, base_a), 1.0)

        print("[E] byte-identity without head")
        base_p = save_png(base_a, root / "base_a.png")
        draft_b_p = save_png(draft_b, root / "draft_b.png")
        new_noh = root / "new_nohead.png"
        old_noh = root / "old_nohead.png"
        r_new_noh = vc.compose(base_p, draft_b_p, new_noh, head=False, base_alpha=True)
        r_old_noh = old_vc.compose(base_p, draft_b_p, old_noh, head=False, base_alpha=True)
        for r in (r_new_noh, r_old_noh):
            r.pop("runtime_s", None)
        check("head=False PNG bytes identical to c5742f5f1",
              hashlib.sha256(new_noh.read_bytes()).hexdigest(),
              hashlib.sha256(old_noh.read_bytes()).hexdigest())
        check("head=False record identical to c5742f5f1",
              json.dumps(r_new_noh, sort_keys=True),
              json.dumps(r_old_noh, sort_keys=True))

        print("[F] head_composite_outdated version check")
        check("no version -> True",
              base_body.head_composite_outdated({"alpha": "base", "head": {"alpha": "draft"}}, head_changed=True),
              True)
        check("version HEAD_VERSION -> False",
              base_body.head_composite_outdated(
                  {"alpha": "base", "head": {"alpha": "draft", "version": vc.HEAD_VERSION}}, head_changed=True),
              False)

        print("[G] base_body.head_match parity with c5742f5f1")
        out_a_p = save_png(out_a, root / "out_a.png")
        check("synthetic pair head_match == c5742f5f1",
              base_body.head_match(out_a_p, base_p),
              old_head_match(out_a_p, base_p))
        real_dir = Path("/home/dev/.claude/jobs/c956220f/tmp/hairpolish-data")
        if (real_dir / "tpose_basebb38b157.png").is_file():
            check("Liv head_match == c5742f5f1 (0.3232)",
                  base_body.head_match(real_dir / "liv_draft_bald.png", real_dir / "tpose_basebb38b157.png"),
                  old_head_match(real_dir / "liv_draft_bald.png", real_dir / "tpose_basebb38b157.png"))
            check("Sigrun head_match == c5742f5f1 (1.0)",
                  base_body.head_match(real_dir / "tpose_ob3f8fb187.png", real_dir / "tpose_base5e1afc76.png"),
                  old_head_match(real_dir / "tpose_ob3f8fb187.png", real_dir / "tpose_base5e1afc76.png"))

        print("[H] bald back not refused as EMPTY / nothing-put-on")
        base_back = figure([
            (20, 150, 140, 260, HAIR),
            (150, 420, 112, 288, SKIN),
            (150, 300, 150, 250, HAIR),
        ] + LIMBS)
        check("[A] new front region < EMPTY_FRONT_MAX",
              rec_a["coverage"]["region"] < vc.EMPTY_FRONT_MAX, True)
        check("[A] old (c5742f5f1) front region > EMPTY_FRONT_MAX (~412/7857 = 0.0524)",
              old_rec_a["coverage"]["region"] > vc.EMPTY_FRONT_MAX, True)
        out_h_back = None
        for label, f_reg in (("front_region=None", None), ("front_region=[A] new", rec_a["coverage"]["region"])):
            out_h, rec_h, _ = vc._composite(base_back, draft_a, "outfit", take_head=True, base_alpha=True,
                                            front_region=f_reg)
            if out_h_back is None:
                out_h_back = out_h
            bad = [r for r in rec_h["reasons"]
                   if r.startswith((vc.NOTHING_ALTHOUGH_DRESSED, vc.NOTHING_TO_PUT_ON))]
            check(f"bald back ({label}): ok, no nothing-reason, not empty",
                  (rec_h["ok"], bad, bool(rec_h.get("empty"))),
                  (True, [], False))
        check("check() on back record with [A] new front_region -> []",
              vc.check({"iou": 0.95, "coverage": {"nothing": True, "region": 0.0},
                        "front_region": rec_a["coverage"]["region"]}),
              [])

        print("[I] garment_bands and front_garment_bands with removed-hair exclusion")
        bands_a_raw = vc.garment_bands(base_a, out_a)
        bands_a_old = old_vc.garment_bands(base_a, out_a)
        bands_a_exc = vc.garment_bands(base_a, out_a, exclude=vc.removed_hair_exclude(base_a, out_a, 180))
        check("[A] garment_bands without exclude == c5742f5f1", bands_a_raw, bands_a_old)
        check("[A] garment_bands without exclude band 0 > 0.10 (~0.169)", bands_a_raw[0] > 0.10, True)
        check("[A] garment_bands with exclude band 0 == 0.0", bands_a_exc[0], 0.0)
        bands_b_exc = vc.garment_bands(base_a, out_b, exclude=vc.removed_hair_exclude(base_a, out_b, 180))
        check("[B] collar kept in band 0 (~0.139 in 0.10..0.18), curtains gone in band 1 (0.0)",
              (0.10 <= bands_b_exc[0] <= 0.18, bands_b_exc[1]), (True, 0.0))

        front_with_head = save_png(out_a, root / "front_head.png")
        front_with_head.with_suffix(".json").write_text(
            json.dumps({"edit_composite": {"head": {"cut_row": 180, "version": vc.HEAD_VERSION}}}),
            encoding="utf-8",
        )
        front_no_head = save_png(out_a, root / "front_nohead.png")
        front_no_head.with_suffix(".json").write_text(json.dumps({"edit_composite": {}}), encoding="utf-8")
        check("front_garment_bands with edit_composite.head.cut_row: band 0 == 0.0",
              base_body.front_garment_bands(front_with_head, base_p)[0], 0.0)
        check("front_garment_bands without head: band 0 > 0.10",
              base_body.front_garment_bands(front_no_head, base_p)[0] > 0.10, True)

        base_back_p = save_png(base_back, root / "base_back.png")
        back_with_head = save_png(out_h_back, root / "back_head.png")
        back_with_head.with_suffix(".json").write_text(
            json.dumps({"composite": {"head": {"cut_row": 180}}}),
            encoding="utf-8",
        )
        back_no_head = save_png(out_h_back, root / "back_nohead.png")
        back_no_head.with_suffix(".json").write_text(json.dumps({"composite": {}}), encoding="utf-8")
        check("front_garment_bands on back with composite.head.cut_row: band 0 == 0.0",
              base_body.front_garment_bands(back_with_head, base_back_p)[0], 0.0)
        check("front_garment_bands on back without head: band 0 > 0.10",
              base_body.front_garment_bands(back_no_head, base_back_p)[0] > 0.10, True)

        print("[J] soft hair edge on torso curtains: colour-match ring outside removed hair")
        hair_edge = (96, 60, 34)
        shadow_skin = (204, 155, 124)
        base_j_uniform = figure([
            (20, 150, 140, 260, HAIR),
            (40, 110, 170, 230, SKIN),
            (150, 420, 112, 288, SKIN),
            (150, 300, 117, 143, hair_edge),
            (150, 300, 120, 140, HAIR),
            (150, 300, 257, 283, hair_edge),
            (150, 300, 260, 280, HAIR),
            (156, 260, 100, 110, HAIR),
            (156, 260, 290, 300, HAIR),
        ] + LIMBS)
        base_j_soft = figure([
            (20, 150, 140, 260, HAIR),
            (20, 150, 140, 152, shadow_skin),
            (20, 150, 248, 260, shadow_skin),
            (40, 110, 170, 230, SKIN),
            (150, 420, 112, 288, SKIN),
            (150, 300, 117, 143, shadow_skin),
            (150, 300, 120, 140, HAIR),
            (150, 300, 257, 283, shadow_skin),
            (150, 300, 260, 280, HAIR),
            (156, 260, 100, 110, HAIR),
            (156, 260, 290, 300, HAIR),
        ] + LIMBS)
        for label, base_j in (("HAIR_EDGE (96,60,34)", base_j_uniform),
                              ("SHADOW_SKIN (204,155,124)", base_j_soft)):
            out_j, rec_j, _ = vc._composite(base_j, draft_a, "outfit", take_head=True, base_alpha=True)
            flat_j = np.asarray(vc.to_image(out_j, vc.GREY), dtype=np.float64)
            de_l = float(de_to_colour(flat_j[200:290, 125:135], SKIN).max())
            de_r = float(de_to_colour(flat_j[200:290, 265:275], SKIN).max())
            check(f"[J] {label}: ok and curtain cores within dE76 3 of SKIN",
                  (rec_j["ok"], de_l < 3.0 and de_r < 3.0),
                  (True, True))

    check("no outbound connection", outbound, [])
    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
