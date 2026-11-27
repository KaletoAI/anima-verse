#!/usr/bin/env python3
"""Smoke: ``view_composite.compose(head=True, base_alpha=True)`` keeps the
draft's alpha inside the head zone (Ruling A21 + Ruling A125), ``_edit_front`` /
``_composite_attempt`` forward ``head``, and ``head_composite_outdated`` /
``shape_view_shas`` / ``shape_view`` mark views made by the broken path as
outdated.

Usage:
    ./.venv/bin/python scripts/smoke_head_zone_base_alpha.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first,
STORAGE_DIR / INSTANCE_DIR temp dirs), synthetic RGBA figures; every socket
connect is refused and counted — the run asserts none happened.

Fixture (built by hand; 800 rows x 400 columns, transparent background,
boxes rows / columns half-open; SKIN (224, 172, 140), BLUE (40, 70, 200),
HAIR (90, 55, 30)):
    BASE (haired plain view):
      hair   rows 20..150,  cols 140..260  HAIR  (130 * 120 = 15600 px)
      torso  rows 150..420, cols 110..290  SKIN
      arms   rows 155..420, cols 80..110 and 290..320  SKIN
      legs   rows 420..780, cols 120..195 and 205..280 SKIN
    DRAFT (bald shape view, dressed):
      head   rows 20..110,  cols 160..240  SKIN  (90 * 80 = 7200 px)
      neck   rows 110..150, cols 185..215  SKIN  (40 * 30 = 1200 px)
      torso  rows 150..420, cols 110..290  BLUE
      arms, legs as the base (SKIN)

Expected values, derived by hand:

[1] ``_head_zone`` of the draft: figure rows 20..780, height 760. Neck band
    rows 65..187; narrowest row 110 (neck width 30); first shoulder row >= 60
    wide = 150; cut = 150 + round(0.04 * 760) = 180 ->
    ``neck_row == 110``, ``cut_row == 180``.
[2] hair-only pixels (inside base hair block rows 20..150 x cols 140..260,
    outside draft head rows 20..110 x cols 160..240 and draft neck rows
    110..150 x cols 185..215): 15600 - 7200 - 1200 = 7200 pixels.
[3] new code, ``compose(head=True, base_alpha=True)``: of the 7200 hair-only
    pixels 0 have alpha > 0 and 0 are opaque black (alpha >= 250 and RGB all
    < 10); every pixel at row >= 180 has alpha equal to the base's alpha;
    record has ``alpha == "base"``, ``head.alpha == "draft"``, ``ok == True``.
[4] old code proof (``e57308f8057a28d950b4dafbab4e8344781c656c``): with
    ``head=True, base_alpha=True`` all 7200 hair-only pixels are opaque and
    all 7200 are opaque black (draft RGB 0 made opaque by base alpha); without
    ``head`` and ``base_alpha=True`` all 7200 hair-only pixels are opaque.
[5] without ``head``: new and old ``compose(base_alpha=True)`` write
    byte-identical PNGs and equal records (``runtime_s`` excluded).
[6] trigger stubs: ``_edit_front(..., head=True/False)`` forwards ``head`` to
    ``view_composite.compose``; ``_composite_attempt(..., head=True)`` with
    ``front=None`` passes ``head=True``.
[7] ``head_composite_outdated``: ``head_changed=False`` -> False for any
    record; ``head_changed=True`` -> True for None, ``{"alpha": "base"}``,
    ``{"alpha": "base", "head": {"cut_row": 180}}``; False for
    ``{"alpha": "base", "head": {"cut_row": 180, "alpha": "draft"}}``.
[8] ``shape_view_shas`` / ``shape_view`` in temp storage for character
    ``Demo``: front with ``edit_composite`` lacking ``head`` has its sha when
    sidecar lacks ``outfit_body``, ``""`` when ``outfit_body.shape_inputs.hair
    == "bald"``; without ``outfit_body``, ``shape_view(..., head_changed=True)``
    is None and ``shape_view(..., head_changed=False)`` is not None.
[9] hair-only front (``front_wears_clothing`` / ``front_garment_region`` /
    ``_composite_attempt``): sidecar with ``dress_text: ""`` and
    ``coverage.region: 0.0349`` -> ``front_wears_clothing`` False,
    ``front_garment_region`` None, and ``_composite_attempt`` passes neither
    ``front_region`` nor ``front_bands`` to ``compose``; with
    ``dress_text: "a red dress"`` -> True, 0.0349, and ``_composite_attempt``
    passes ``front_region == 0.0349``; without ``dress_text`` key -> True,
    0.0349.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLD_COMMIT = "e57308f8057a28d950b4dafbab4e8344781c656c"
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


def load_rgba_u8(path: Path) -> np.ndarray:
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"))


def load_old_view_composite():
    proc = subprocess.run(
        ["git", "show", f"{OLD_COMMIT}:app/core/view_composite.py"],
        cwd=str(ROOT), capture_output=True, text=True, check=True,
    )
    mod_name = "app.core._view_composite_old_e57308f"
    mod = types.ModuleType(mod_name)
    mod.__file__ = f"<git:{OLD_COMMIT}:app/core/view_composite.py>"
    sys.modules[mod_name] = mod
    exec(compile(proc.stdout, mod.__file__, "exec"), mod.__dict__)
    return mod


def main() -> int:
    import socket
    outbound: list = []

    def no_network(self, address, *_a, **_k):
        outbound.append(address)
        raise OSError("no network in this smoke")
    socket.socket.connect = no_network  # any request would be counted and refused

    with tempfile.TemporaryDirectory(prefix="head-zone-base-alpha-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")

        from app.core import base_body, view_composite as vc
        from app.models.character import get_character_dir

        base_arr = figure(BASE)
        draft_arr = figure(DRAFT)
        base = save(base_arr, root / "base.png")
        draft = save(draft_arr, root / "draft.png")

        print("[1] _head_zone of the draft")
        _zone, zone_rec = vc._head_zone(vc.figure_mask(draft_arr))
        check("neck_row, cut_row", (zone_rec["neck_row"], zone_rec["cut_row"]), (110, 180))

        print("[2] hair-only pixel count")
        hair_block = np.zeros((800, 400), dtype=bool)
        hair_block[20:150, 140:260] = True
        draft_head_neck = np.zeros((800, 400), dtype=bool)
        draft_head_neck[20:110, 160:240] = True
        draft_head_neck[110:150, 185:215] = True
        hair_only = hair_block & ~draft_head_neck
        check("hair-only pixels", int(hair_only.sum()), 7200)

        print("[3] new code: compose(head=True, base_alpha=True)")
        new_path = root / "new_head_base_alpha.png"
        new_rec = vc.compose(base, draft, new_path, head=True, base_alpha=True)
        new_u8 = load_rgba_u8(new_path)
        new_ho = new_u8[hair_only]
        new_opaque = int((new_ho[:, 3] > 0).sum())
        new_black = int(((new_ho[:, 3] >= 250) & (new_ho[:, :3] < 10).all(axis=1)).sum())
        check("hair-only alpha > 0", new_opaque, 0)
        check("hair-only opaque black", new_black, 0)
        base_u8 = load_rgba_u8(base)
        check("row >= 180 alpha equals base", bool((new_u8[180:, :, 3] == base_u8[180:, :, 3]).all()), True)
        check("record ok / alpha / head.alpha",
              (new_rec["ok"], new_rec.get("alpha"), (new_rec.get("head") or {}).get("alpha")),
              (True, "base", "draft"))

        print("[4] old code proof (commit e57308f8)")
        old_vc = load_old_view_composite()
        old_head_path = root / "old_head_base_alpha.png"
        old_vc.compose(base, draft, old_head_path, head=True, base_alpha=True)
        old_head_u8 = load_rgba_u8(old_head_path)
        old_ho = old_head_u8[hair_only]
        old_head_opaque = int((old_ho[:, 3] > 0).sum())
        old_head_black = int(((old_ho[:, 3] >= 250) & (old_ho[:, :3] < 10).all(axis=1)).sum())
        check("old head=True base_alpha=True opaque", old_head_opaque, 7200)
        check("old head=True base_alpha=True black opaque", old_head_black, 7200)

        old_nohead_path = root / "old_nohead_base_alpha.png"
        old_nohead_rec = old_vc.compose(base, draft, old_nohead_path, base_alpha=True)
        old_nohead_u8 = load_rgba_u8(old_nohead_path)
        check("old head=False base_alpha=True opaque", int((old_nohead_u8[hair_only][:, 3] > 0).sum()), 7200)

        print("[5] without head: new and old compose(base_alpha=True) byte-identical")
        new_nohead_path = root / "new_nohead_base_alpha.png"
        new_nohead_rec = vc.compose(base, draft, new_nohead_path, base_alpha=True)
        for r in (old_nohead_rec, new_nohead_rec):
            r.pop("runtime_s", None)
        check("same PNG bytes",
              hashlib.sha256(new_nohead_path.read_bytes()).hexdigest(),
              hashlib.sha256(old_nohead_path.read_bytes()).hexdigest())
        check("same record",
              json.dumps(new_nohead_rec, sort_keys=True),
              json.dumps(old_nohead_rec, sort_keys=True))

        print("[6] trigger stubs: _edit_front and _composite_attempt")
        seen_edit = []
        seen_attempt = []
        real_render = base_body.render_view_edit
        real_compose = vc.compose
        real_publish = base_body._publish_staged

        def stub_render(character_name, view, *, stem, **_kw):
            out = Path(stem).with_suffix(".png")
            out.write_bytes(draft.read_bytes())
            out.with_suffix(".json").write_text("{}", encoding="utf-8")
            return out

        def stub_compose_edit(base_view, draft_file, target, **kw):
            seen_edit.append(kw.get("head", "absent"))
            Path(target).write_bytes(Path(draft_file).read_bytes())
            return {"ok": True, "version": vc.VERSION, "alpha": "base"}

        def stub_publish(staged, target_stem, record, *, key="composite"):
            out = Path(target_stem).with_suffix(".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(Path(staged).read_bytes())
            return out

        refs_stub = root / "stub_refs"
        refs_stub.mkdir(parents=True, exist_ok=True)
        try:
            base_body.render_view_edit = stub_render
            vc.compose = stub_compose_edit
            base_body._publish_staged = stub_publish
            base_body._edit_front("Demo", signature="sig1", refs_dir=refs_stub, base_front=base,
                                  prompt=("p", "n"), common={}, extra={}, head=True)
            base_body._edit_front("Demo", signature="sig2", refs_dir=refs_stub, base_front=base,
                                  prompt=("p", "n"), common={}, extra={}, head=False)
            check("_edit_front head=True / False", seen_edit, [True, False])

            def stub_compose_attempt(base_view, draft_file, target, **kw):
                seen_attempt.append(kw.get("head", "absent"))
                Path(target).write_bytes(Path(draft_file).read_bytes())
                return {"ok": False, "iou": 0.0, "coverage": {"score": 0.0, "region": 0.0}, "reasons": ["stub"]}

            vc.compose = stub_compose_attempt
            stem = root / "attempt_head_true" / "tpose_back_sig"
            stem.parent.mkdir()
            base_body._composite_attempt("Demo", "back", stem=stem, draft=draft,
                                         base_views={"front": base, "back": base}, extra={},
                                         front=None, head=True)
            check("_composite_attempt head=True front=None", seen_attempt, [True])
        finally:
            base_body.render_view_edit = real_render
            vc.compose = real_compose
            base_body._publish_staged = real_publish

        print("[7] head_composite_outdated")
        check("head_changed=False None", base_body.head_composite_outdated(None, head_changed=False), False)
        check("head_changed=False no head",
              base_body.head_composite_outdated({"alpha": "base"}, head_changed=False), False)
        check("head_changed=True None", base_body.head_composite_outdated(None, head_changed=True), True)
        check("head_changed=True no head",
              base_body.head_composite_outdated({"alpha": "base"}, head_changed=True), True)
        check("head_changed=True no draft alpha",
              base_body.head_composite_outdated({"alpha": "base", "head": {"cut_row": 180}}, head_changed=True), True)
        check("head_changed=True draft alpha present",
              base_body.head_composite_outdated({"alpha": "base", "head": {"cut_row": 180, "alpha": "draft"}},
                                                head_changed=True), False)

        print("[8] shape_view_shas / shape_view in temp storage")
        bsig = "bb12345678"
        shape = "ob12345678"
        refs_dir = get_character_dir("Demo") / "model_refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        base_front_path = refs_dir / f"tpose_{bsig}.png"
        base_front_path.write_bytes(base.read_bytes())
        base_sha = hashlib.sha256(base_front_path.read_bytes()).hexdigest()

        shape_front_path = refs_dir / f"tpose_{shape}.png"
        shape_front_path.write_bytes(draft.read_bytes())
        shape_sha = hashlib.sha256(shape_front_path.read_bytes()).hexdigest()

        sidecar_no_ob = {
            "base_signature": bsig,
            "base_image_sha256": base_sha,
            "edit_composite": {"version": 5, "ok": True, "alpha": "base"},
        }
        shape_front_path.with_suffix(".json").write_text(json.dumps(sidecar_no_ob), encoding="utf-8")
        check("shape_view_shas front without outfit_body",
              base_body.shape_view_shas("Demo", shape, bsig)["front"], shape_sha)
        check("shape_view head_changed=True without outfit_body",
              base_body.shape_view("Demo", "front", shape, bsig, head_changed=True), None)
        check("shape_view head_changed=False without outfit_body",
              base_body.shape_view("Demo", "front", shape, bsig, head_changed=False) is not None, True)

        sidecar_with_ob = {
            **sidecar_no_ob,
            "outfit_body": {"shape_inputs": {"hair": "bald"}},
        }
        shape_front_path.with_suffix(".json").write_text(json.dumps(sidecar_with_ob), encoding="utf-8")
        check("shape_view_shas front with outfit_body.shape_inputs.hair='bald'",
              base_body.shape_view_shas("Demo", shape, bsig)["front"], "")

        print("[9] hair-only front: front_wears_clothing / front_garment_region / _composite_attempt")
        front_hair_only = root / "front_hair_only.png"
        front_hair_only.write_bytes(draft.read_bytes())
        front_hair_only.with_suffix(".json").write_text(
            json.dumps({"dress_text": "", "edit_composite": {"coverage": {"region": 0.0349}}}),
            encoding="utf-8",
        )
        check("hair-only front_wears_clothing", base_body.front_wears_clothing(front_hair_only), False)
        check("hair-only front_garment_region", base_body.front_garment_region(front_hair_only), None)

        front_dressed = root / "front_dressed.png"
        front_dressed.write_bytes(draft.read_bytes())
        front_dressed.with_suffix(".json").write_text(
            json.dumps({"dress_text": "a red dress", "edit_composite": {"coverage": {"region": 0.0349}}}),
            encoding="utf-8",
        )
        check("dressed front_wears_clothing", base_body.front_wears_clothing(front_dressed), True)
        check("dressed front_garment_region", base_body.front_garment_region(front_dressed), 0.0349)

        front_legacy = root / "front_legacy.png"
        front_legacy.write_bytes(draft.read_bytes())
        front_legacy.with_suffix(".json").write_text(
            json.dumps({"edit_composite": {"coverage": {"region": 0.0349}}}),
            encoding="utf-8",
        )
        check("legacy front_wears_clothing", base_body.front_wears_clothing(front_legacy), True)
        check("legacy front_garment_region", base_body.front_garment_region(front_legacy), 0.0349)

        seen_kwargs = []
        real_compose_9 = vc.compose

        def stub_compose_9(base_view, draft_file, target, **kw):
            seen_kwargs.append(dict(kw))
            Path(target).write_bytes(Path(draft_file).read_bytes())
            return {"ok": False, "iou": 0.0, "coverage": {"score": 0.0, "region": 0.0}, "reasons": ["stub"]}

        try:
            vc.compose = stub_compose_9
            stem_ho = root / "attempt_hair_only" / "tpose_back_sig"
            stem_ho.parent.mkdir()
            base_body._composite_attempt(
                "Demo", "back", stem=stem_ho, draft=draft,
                base_views={"front": base, "back": base}, extra={},
                front=front_hair_only, front_region=0.0349, head=True,
            )
            check("hair-only compose has no front_region / front_bands",
                  ("front_region" in seen_kwargs[-1], "front_bands" in seen_kwargs[-1]), (False, False))

            stem_dr = root / "attempt_dressed" / "tpose_back_sig"
            stem_dr.parent.mkdir()
            base_body._composite_attempt(
                "Demo", "back", stem=stem_dr, draft=draft,
                base_views={"front": base, "back": base}, extra={},
                front=front_dressed, front_region=base_body.front_garment_region(front_dressed), head=True,
            )
            check("dressed compose has front_region == 0.0349", seen_kwargs[-1].get("front_region"), 0.0349)
        finally:
            vc.compose = real_compose_9

    check("no outbound connection", outbound, [])
    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
