#!/usr/bin/env python3
"""Smoke: the composite of a dressed view whose shape wears another head than
the plain views (plan 2026-11-12-unified-worn-pieces, Task 11g-fix4b,
Ruling A21) — ``view_composite.compose(head=True)`` / ``_head_zone`` and the
trigger in ``base_body._composite_attempt``.

Usage:
    ./.venv/bin/python scripts/smoke_bald_head_composite.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first,
STORAGE_DIR / INSTANCE_DIR temp dirs), synthetic RGBA figures; every socket
connect is refused and counted — the run asserts none happened.

Fixture (built by hand; 800 rows x 400 columns, transparent background,
boxes rows / columns half-open; SKIN (224, 172, 140), BLUE (40, 70, 200),
HAIR (90, 55, 30)):
    BASE (the haired plain back):
      hair   rows 20..150,  cols 140..260  HAIR — long hair hiding head and neck
      torso  rows 150..420, cols 110..290  SKIN
      arms   rows 155..420, cols 80..110 and 290..320  SKIN
      legs   rows 420..780, cols 120..195 and 205..280 SKIN
    DRAFT (the bald shape's back, dressed):
      head   rows 20..110,  cols 160..240  SKIN
      neck   rows 110..150, cols 185..215  SKIN
      torso  rows 150..420, cols 110..290  BLUE (the garment)
      arms, legs as the base (SKIN)

Expected values, derived by hand:

[1] the head zone of the draft (``_head_zone``): figure rows 20..780,
    height 760. Neck band rows 20 + int(0.06 * 760) = 65 .. 20 +
    int(0.22 * 760) = 187; widths there: head 80 (rows 65..110), neck 30
    (rows 110..150), torso 180 (rows 150..155), torso + arms 240 (155..187)
    -> the narrowest row 110 (the first of the neck). Shoulder line: the
    first row from 110 at least 2 x 30 = 60 wide = row 150. Cut = 150 +
    round(0.04 * 760) = 180 -> {"neck_row": 110, "cut_row": 180,
    "cut": (180 - 20) / 760 = 0.2105}.
[2] the alignment: both figures span rows 20..780 and cols 80..320 ->
    scale 1.0, dx 0.0, dy 0.0 (the aligned draft is the draft).
[3] compose WITHOUT the head (the composite as it stood): the flow drives
    the draft's outline onto the base's, whose top is the hair block (cols
    140..260) — the bald head is stretched into the hair's outline or the
    hair stays (Ylva 2026-11-13: both). Either way the outline above the
    cut is the base's: (60, 150) and (130, 170) (inside the hair block,
    outside the draft's head cols 160..240 and neck cols 185..215) stay
    opaque (alpha >= 250).
[4] compose WITH the head: everything above the cut is the draft —
    (60, 150) transparent (alpha 0: the base's hair went), (60, 200) SKIN
    opaque (the bald head), (130, 200) SKIN (the neck), (130, 170)
    transparent (beside the neck, where the base had hair); not one HAIR
    pixel anywhere (the hair block lies wholly above the cut, rows 20..150
    < 180). The garment below: (300, 200) BLUE. The record keeps ``ok``
    (IoU and coverage as for any composite) and ``head`` with the zone of
    [1].
[5] the neck line's seam: below the cut the only skin outside the mask is
    the arms (cols 80..110, 290..320), SKIN in base and draft alike — the
    colour match moves nothing (offset 0) and the seam ΔE along the cut is
    0.0 (``head.neck_seam_de``).
[6] a figure whose head matches: ``compose`` without ``head`` writes the
    same bytes and the same record (runtime aside) as with ``head=False``,
    and its record has no ``head`` key — the haired path is untouched.
[7] the trigger (``base_body._composite_attempt``): ``head_match`` of the
    dressed front below ``HEAD_MATCH_MIN`` -> ``compose`` gets
    ``head=True``; at or above it -> no ``head`` keyword at all; no front
    -> none either.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []
SKIN = (224, 172, 140)
BLUE = (40, 70, 200)
HAIR = (90, 55, 30)
LIMBS = [(155, 420, 80, 110, SKIN), (155, 420, 290, 320, SKIN), (420, 780, 120, 195, SKIN),
         (420, 780, 205, 280, SKIN)]
BASE = [(20, 150, 140, 260, HAIR), (150, 420, 110, 290, SKIN)] + LIMBS
DRAFT = [(20, 110, 160, 240, SKIN), (110, 150, 185, 215, SKIN), (150, 420, 110, 290, BLUE)] + LIMBS


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def figure(parts):
    a = np.zeros((800, 400, 4))
    for y0, y1, x0, x1, colour in parts:
        a[y0:y1, x0:x1, :3] = colour
        a[y0:y1, x0:x1, 3] = 255
    return a


def save(arr, path: Path) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA").save(path)
    return path


def pixel(path: Path, y: int, x: int):
    from PIL import Image
    with Image.open(path) as im:
        return tuple(int(v) for v in im.convert("RGBA").getpixel((x, y)))


def main() -> int:
    import socket
    outbound: list = []

    def no_network(self, address, *_a, **_k):
        outbound.append(address)
        raise OSError("no network in this smoke")
    socket.socket.connect = no_network  # any request would be counted and refused
    with tempfile.TemporaryDirectory(prefix="bald-head-composite-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        from PIL import Image

        from app.core import base_body, view_composite as vc

        base = save(figure(BASE), root / "base_back.png")
        draft = save(figure(DRAFT), root / "draft_back.png")

        print("[1] the head zone")
        zone, record = vc._head_zone(vc.figure_mask(figure(DRAFT)))
        check("zone record", record, {"neck_row": 110, "cut_row": 180, "cut": 0.2105})
        check("zone rows", (bool(zone[179].all()), bool(zone[180].any())), (True, False))

        print("[2]-[3] without the head: the base's hair outline stays")
        old = root / "old.png"
        rec_old = vc.compose(base, draft, old)
        check("alignment", rec_old["alignment"], {"scale": 1.0, "dx": 0.0, "dy": 0.0})
        check("(60, 150) / (130, 170) opaque", (pixel(old, 60, 150)[3] >= 250, pixel(old, 130, 170)[3] >= 250),
              (True, True))

        print("[4] with the head: the draft's head, no hair")
        new = root / "new.png"
        rec = vc.compose(base, draft, new, head=True)
        check("ok, alignment", (rec["ok"], rec["alignment"]), (True, {"scale": 1.0, "dx": 0.0, "dy": 0.0}))
        check("(60, 150) transparent", pixel(new, 60, 150)[3], 0)
        check("(60, 200) bald head", pixel(new, 60, 200), SKIN + (255,))
        check("(130, 200) neck", pixel(new, 130, 200), SKIN + (255,))
        check("(130, 170) beside the neck transparent", pixel(new, 130, 170)[3], 0)
        check("(300, 200) garment", pixel(new, 300, 200), BLUE + (255,))
        arr = np.asarray(Image.open(new).convert("RGBA")).astype(int)
        hair = (np.abs(arr[..., :3] - np.array(HAIR)).max(-1) <= 20) & (arr[..., 3] > 0)
        check("no hair pixel", int(hair.sum()), 0)
        drafted = figure(DRAFT)
        check("above the cut = the draft (max |diff| <= 1)", float(np.abs(arr[:180] - drafted[:180]).max()) <= 1.0, True)
        check("record head zone", {k: rec["head"][k] for k in ("neck_row", "cut_row", "cut")},
              {"neck_row": 110, "cut_row": 180, "cut": 0.2105})

        print("[5] the neck line's seam")
        check("neck seam ΔE", rec["head"]["neck_seam_de"], 0.0)

        print("[6] the haired path untouched")
        a, b = root / "a.png", root / "b.png"
        rec_a = vc.compose(base, draft, a)
        rec_b = vc.compose(base, draft, b, head=False)
        for r in (rec_a, rec_b):
            r.pop("runtime_s", None)
        check("same bytes", hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest())
        check("same record, no head key", (json.dumps(rec_a, sort_keys=True) == json.dumps(rec_b, sort_keys=True),
                                           "head" in rec_a), (True, False))

        print("[7] the trigger in _composite_attempt")
        seen = []

        def compose(base_view, draft_file, target, **kw):
            seen.append(kw.get("head", "absent"))
            Path(target).write_bytes(Path(draft_file).read_bytes())
            return {"ok": False, "iou": 0.0, "coverage": {"score": 0.0, "region": 0.0}, "reasons": ["stub"]}

        real = (vc.compose, base_body.head_match)
        vc.compose = compose
        front = save(figure(DRAFT), root / "front.png")
        views = {"front": save(figure(BASE), root / "base_front.png"), "back": base}
        try:
            for match, want in ((0.22, True), (base_body.HEAD_MATCH_MIN, "absent"), (0.95, "absent")):
                base_body.head_match = lambda *_a, _m=match, **_k: _m
                stem = root / f"attempt_{match}" / "tpose_back_sig"
                stem.parent.mkdir()
                base_body._composite_attempt("Demo", "back", stem=stem, draft=draft, base_views=views, extra={},
                                             front=front)
                check(f"head_match {match}", seen[-1], want)
            stem = root / "attempt_nofront" / "tpose_back_sig"
            stem.parent.mkdir()
            base_body._composite_attempt("Demo", "back", stem=stem, draft=draft, base_views=views, extra={})
            check("no front", seen[-1], "absent")
        finally:
            vc.compose, base_body.head_match = real

    check("no outbound connection", outbound, [])
    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
