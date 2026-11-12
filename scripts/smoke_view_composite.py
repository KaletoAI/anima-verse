#!/usr/bin/env python3
"""Smoke: the CPU composite of a two-step view (plan
2026-11-12-unified-worn-pieces, Task 11g, Ruling C1 — ``app/core/view_composite.py``)
and what replaced the model fit around it.

Usage:
    ./.venv/bin/python scripts/smoke_view_composite.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first,
STORAGE_DIR / INSTANCE_DIR temp dirs), synthetic RGBA figures, the draft
render stubbed where a caller is driven.

Fixture (built by hand, 400 rows x 300 columns, transparent background,
skin (224, 172, 140) opaque; rows / columns half-open):
    head  rows 40..100,  cols 125..175   60 x 50  =  3000
    neck  rows 100..110, cols 140..160   10 x 20  =   200
    torso rows 110..230, cols 100..200  120 x 100 = 12000
    arms  rows 115..230, cols 80..100 and 200..220   2 x 115 x 20 = 4600
    legs  rows 230..360, cols 105..145 and 155..195  2 x 130 x 40 = 10400
    base figure = 30200 px, bbox rows 40..360 (height 320), cols 80..220
    (centre 150). The DRAFT D = the base plus a blue (40, 70, 200) rectangle
    R rows 130..210, cols 110..190 (80 x 80 = 6400 px) on the torso.

Expected values, derived by hand:

[1] compose(base, D, rule "outfit"): the same figure height and top/centre
    -> alignment {scale 1.0, dx 0.0, dy 0.0}; identical silhouettes -> the
    flow is zero (warp mean / p95 / max 0.0), iou 1.0, composite_iou 1.0,
    drift_px 0.0. The mask is R plus at most its 4 px blur/closing halo:
    6400 / 30200 = 0.2119 <= mask_share <= 88 x 88 / 30200 = 0.2564. Every
    put-on cell either is R (composite = draft) or is skin on both (composite
    = base = draft) -> draft_de 0.0, score 1.0. Skin on both sides of the
    seam -> seam_de 0.0. Outside R dilated by 4 px the composite equals the
    base, inside R eroded by 4 px it equals the draft (max |diff| <= 1 RGB:
    the ring offset is 0, so nothing is shifted). ok, no reasons.
[2] D drawn 1.1x (every coordinate y -> 20 + 1.1 (y - 40), x -> 150 +
    1.1 (x - 150), 420 rows): height 1.1 x 320 = 352, top 20, centre 150
    -> scale 320 / 352 = 0.9091, dx 0.0, dy 40 - 20 = 20.0; iou >= 0.99
    (the same figure resampled), ok.
[3] draft = base: no draft cell differs -> region 0, "nothing to put on"
    with the rule's minimum ("< 0.03" outfit, "< 0.002" piece), coverage
    0.0, ok False, and the composite is the base exactly.
[4] ALIGNMENT refused: the arms raised above the head (arms rows 20..175,
    head rows 100..160, torso 170..280, legs 280..360) -> bbox rows
    20..360 = 340, scale 320 / 340 = 0.9412, dy 40 - 20 = 20.0, dx 0.0;
    the raised arms land 25..45 px beside the base head, beyond what the
    smoothed flow moves -> iou < IOU_MIN 0.93, reason starts with
    NOT_ALIGNED. Pure ``check``: iou 0.92 + coverage 0.9 -> exactly
    ["the draft does not line up with the base (IoU 0.920 < 0.93)"];
    iou 0.95 + coverage 0.4 -> exactly ["the composite did not put on what
    the draft wears (coverage 0.400 < 0.5)"]. A draft without a figure
    (alpha 0) -> [NO_FIGURE], ok False; a base without one -> CompositeError.
[5] Caller ``base_body._dress_view`` (back, render_draft + compose stubbed;
    view_guard / noise / framing stubbed ok):
    (a) both composites fail (iou 0.9) -> two drafts, then OutfitError =
        view_composite.refusal("Dressed back", [rec, rec]) = "Dressed back
        refused — the composite of the draft failed (IoU >= 0.93, coverage
        >= 0.5): draft 1: IoU 0.900, coverage 0.900 (region 0.200), mask
        0.300: <reason> | draft 2: …"; the stored back (bytes "OLD") stays,
        no draft published under drafts/.
    (b) composite 1 fails, 2 passes -> two drafts, the second published:
        sidecar fit "composite", composite = record 2, fit_gate chosen 2
        with both attempts; drafts/tpose_back_<sig>.png = draft 2's bytes.
    The garment chain's own refusal (worn back, rule "piece") is
    smoke_garment_clothing_back.py [4].
[6] Job counts: dressed_view_jobs() = 1 + (views - 1): front + back -> 2,
    with left + right -> 4 (was 3 / 7 with the fit). garments.HUB_JOBS
    clothing:edit_chain worn 2 (front edit + back draft; was 3),
    BACK_JOBS worn 1 (was 2), ghost unchanged 1.
[7] Catalog: outfit_back / outfit_side are no occasion (OCCASIONS,
    MESH_INPUT_OCCASIONS), outfit_back_draft / outfit_side_draft are;
    config.DEAD_USE_CASES holds outfit_fit. _migrate_removed_fit_occasions
    on routing {tpose, outfit_back, outfit_side} -> True, both dropped, tpose
    kept, ONE info line naming "outfit_back, outfit_side"; a second run ->
    False, no line; no routing -> False.
[8] compose refuses the event loop (inside asyncio.run) and a thread named
    "ProviderQueue-x" with CompositeError, nothing written; a plain worker
    thread composes.
[9] Determinism: compose(base, D) twice -> the same PNG bytes, the same
    record except runtime_s.
[10] Old-code proof: ``git show eaa0fd58:app/imagegen/occasions.py`` holds
    '"outfit_back": _image(' — on eaa0fd58 the back's second step was a
    routed model fit (a hub job), the occasion this task removes.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []
SKIN = (224, 172, 140)
BLUE = (40, 70, 200)
BODY = [(40, 100, 125, 175), (100, 110, 140, 160), (110, 230, 100, 200), (115, 230, 80, 100),
        (115, 230, 200, 220), (230, 360, 105, 145), (230, 360, 155, 195)]
RECT = (130, 210, 110, 190)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def figure(parts, rows=400, cols=300, scale=1.0, top=40):
    """RGBA float array: each (y0, y1, x0, x1[, colour]) box mapped y -> top + scale (y - 40), x -> 150 + scale (x - 150)."""
    a = np.zeros((rows, cols, 4))
    for part in parts:
        y0, y1, x0, x1 = part[:4]
        colour = part[4] if len(part) > 4 else SKIN
        Y0, Y1 = (int(round(top + (y - 40) * scale)) for y in (y0, y1))
        X0, X1 = (int(round(150 + (x - 150) * scale)) for x in (x0, x1))
        a[Y0:Y1, X0:X1, :3] = colour
        a[Y0:Y1, X0:X1, 3] = 255
    return a


def save(arr, path: Path) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA").save(path)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="view-composite-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        from scipy import ndimage as ndi

        from app.core import base_body, config, garments, view_composite as vc
        from app.imagegen import occasions

        base = figure(BODY)
        draft = figure(BODY + [(*RECT, BLUE)])

        print("[1] a rectangle put on")
        out, rec = vc.composite_arrays(base, draft, rule="outfit")
        check("alignment", rec["alignment"], {"scale": 1.0, "dx": 0.0, "dy": 0.0})
        check("no warp", rec["warp"], {"mean_px": 0.0, "p95_px": 0.0, "max_px": 0.0})
        check("iou / composite iou / drift", (rec["iou"], rec["composite_iou"], rec["drift_px"]), (1.0, 1.0, 0.0))
        check("mask share between R and R + 4 px", 6400 / 30200 <= rec["mask_share"] <= 88 * 88 / 30200, True)
        check("coverage", (rec["coverage"]["score"], rec["coverage"]["draft_de"]), (1.0, 0.0))
        check("seam", rec["seam_de"], 0.0)
        r = np.zeros(base.shape[:2], bool)
        r[RECT[0]:RECT[1], RECT[2]:RECT[3]] = True
        outside, inside = ~ndi.binary_dilation(r, iterations=4), ndi.binary_erosion(r, iterations=4)
        check("outside the halo = the base", float(np.abs(out - base)[outside].max()) <= 1.0, True)
        check("inside = the draft", float(np.abs(out - draft)[inside].max()) <= 1.0, True)
        check("ok", (rec["ok"], rec["reasons"]), (True, []))

        print("[2] a 1.1x draft")
        big = figure(BODY + [(*RECT, BLUE)], rows=420, scale=1.1, top=20)
        _o, rec = vc.composite_arrays(base, big)
        check("alignment", rec["alignment"], {"scale": 0.9091, "dx": 0.0, "dy": 20.0})
        check("iou >= 0.99, ok", (rec["iou"] >= 0.99, rec["ok"]), (True, True))

        print("[3] nothing to put on")
        out, rec = vc.composite_arrays(base, base.copy(), rule="outfit")
        check("outfit", (rec["ok"], rec["reasons"], rec["coverage"]["score"]),
              (False, ["nothing to put on (garment region 0.0000 < 0.03)"], 0.0))
        check("composite = base", bool(np.array_equal(out, base)), True)
        _o, rec = vc.composite_arrays(base, base.copy(), rule="piece")
        check("piece", rec["reasons"], ["nothing to put on (garment region 0.0000 < 0.002)"])

        print("[4] alignment refused")
        up = figure([(100, 160, 125, 175), (160, 170, 140, 160), (170, 280, 100, 200), (280, 360, 105, 145),
                     (280, 360, 155, 195), (20, 175, 80, 100), (20, 175, 200, 220), (190, 260, 110, 190, BLUE)])
        _o, rec = vc.composite_arrays(base, up)
        check("arms up: alignment", rec["alignment"], {"scale": 0.9412, "dx": 0.0, "dy": 20.0})
        check("arms up: iou below IOU_MIN", rec["iou"] < vc.IOU_MIN, True)
        check("arms up: refused as not aligned", (rec["ok"], [x.split(" (")[0] for x in rec["reasons"]]),
              (False, [vc.NOT_ALIGNED]))
        check("check: iou 0.92", vc.check({"iou": 0.92, "coverage": {"score": 0.9, "region": 0.2}}),
              ["the draft does not line up with the base (IoU 0.920 < 0.93)"])
        check("check: coverage 0.4", vc.check({"iou": 0.95, "coverage": {"score": 0.4, "region": 0.2}}),
              ["the composite did not put on what the draft wears (coverage 0.400 < 0.5)"])
        _o, rec = vc.composite_arrays(base, np.zeros_like(base))
        check("draft without a figure", (rec["ok"], rec["reasons"]), (False, [vc.NO_FIGURE]))
        try:
            vc.composite_arrays(np.zeros_like(base), draft)
            check("base without a figure", "no exception", "CompositeError")
        except vc.CompositeError:
            check("base without a figure", "CompositeError", "CompositeError")

        print("[5] the dressed view's caller")
        refs = root / "refs"
        refs.mkdir()
        base_back = save(base, refs / "tpose_back_bsig.png")
        front = save(draft, refs / "tpose_sig.png")
        stored = refs / "tpose_back_sig.png"
        stored.write_bytes(b"OLD")
        renders, plan = [], []

        def render_draft(character_name, view, *, stem, **kw):
            renders.append(view)
            path = save(draft if len(renders) % 2 else big, Path(str(stem) + ".png"))
            path.with_suffix(".json").write_text(json.dumps({"n": len(renders)}))
            return path

        def compose(base_view, draft_file, target, *, rule="outfit", background=None):
            ok = plan.pop(0)
            Path(target).write_bytes(Path(draft_file).read_bytes())
            rec = {"version": 1, "rule": rule, "ok": ok, "iou": 0.97 if ok else 0.9,
                   "coverage": {"score": 0.9, "region": 0.2}, "mask_share": 0.3}
            rec["reasons"] = vc.check(rec)
            return rec

        real = (base_body.render_draft, base_body.draft_prompt, vc.compose, base_body.view_guard)
        from app.core import base_body_gates
        real_gates = (base_body_gates.noise_gate, base_body_gates.framing_gate)
        base_body.render_draft = render_draft
        base_body.draft_prompt = lambda *a, **k: ("p", "n")
        vc.compose = compose
        base_body.view_guard = lambda view, path, views: {"ok": True, "best": view}
        base_body_gates.noise_gate = lambda *a, **k: {"ok": True, "score": 1.0}
        base_body_gates.framing_gate = lambda *a, **k: {"ok": True}
        kw = dict(signature="sig", bsig="bsig", pieces={}, items=[], profile={}, front=front,
                  base_views={"back": base_back}, refs_dir=refs, size=(300, 400))
        try:
            plan[:] = [False, False]
            try:
                base_body._dress_view("Demo", "back", **kw)
                check("(a) refused", "no exception", "OutfitError")
            except base_body.OutfitError as e:
                failed = {"version": 1, "rule": "outfit", "ok": False, "iou": 0.9,
                          "coverage": {"score": 0.9, "region": 0.2}, "mask_share": 0.3,
                          "reasons": ["the draft does not line up with the base (IoU 0.900 < 0.93)"]}
                check("(a) the refusal names both drafts' numbers", str(e), vc.refusal("Dressed back", [failed, failed]))
                check("(a) its text", str(e).startswith(
                    "Dressed back refused — the composite of the draft failed (IoU >= 0.93, coverage >= 0.5): "
                    "draft 1: IoU 0.900, coverage 0.900 (region 0.200), mask 0.300: the draft does not line up"), True)
            check("(a) two drafts", renders, ["back", "back"])
            check("(a) the stored back stays", stored.read_bytes(), b"OLD")
            check("(a) no draft published", sorted(p.name for p in (refs / base_body.DRAFT_DIR).glob("*")), [])
            renders.clear()
            plan[:] = [False, True]
            path, warning = base_body._dress_view("Demo", "back", **kw)
            meta = json.loads(path.with_suffix(".json").read_text())
            check("(b) two drafts, the second published", (renders, path.name, warning), (["back", "back"],
                                                                                          stored.name, None))
            check("(b) sidecar", (meta.get("fit"), meta["composite"]["iou"], meta["fit_gate"]["chosen"],
                                  len(meta["fit_gate"]["attempts"])), ("composite", 0.97, 2, 2))
            published = refs / base_body.DRAFT_DIR / "tpose_back_sig.png"
            check("(b) draft 2 published", published.is_file() and published.read_bytes() == path.read_bytes(), True)
        finally:
            base_body.render_draft, base_body.draft_prompt, vc.compose, base_body.view_guard = real
            base_body_gates.noise_gate, base_body_gates.framing_gate = real_gates

        print("[6] job counts")
        real_views = base_body.dressed_views
        try:
            base_body.dressed_views = lambda: ["front", "back"]
            two = base_body.dressed_view_jobs()
            base_body.dressed_views = lambda: ["front", "back", "left", "right"]
            four = base_body.dressed_view_jobs()
        finally:
            base_body.dressed_views = real_views
        check("dressed_view_jobs", (two, four), (2, 4))
        check("garment worn", (garments.HUB_JOBS["clothing:edit_chain"]["worn"], garments.BACK_JOBS["worn"],
                               garments.BACK_JOBS["ghost"]), (2, 1, 1))

        print("[7] catalog and migration")
        check("no fit occasions", [o in occasions.OCCASIONS or o in occasions.MESH_INPUT_OCCASIONS
                                   for o in ("outfit_back", "outfit_side")], [False, False])
        check("draft occasions stay", [o in occasions.OCCASIONS for o in ("outfit_back_draft", "outfit_side_draft")],
              [True, True])
        check("outfit_fit dead", "outfit_fit" in config.DEAD_USE_CASES, True)
        lines = []

        class Rec:
            def info(self, msg, *args):
                lines.append(msg % args)

            def __getattr__(self, name):
                return lambda *a, **k: None

        real_logger = config.logger
        config.logger = Rec()
        try:
            union = {"image_generation": {"routing": {"tpose": ["a*"], "outfit_back": ["x"], "outfit_side": ["y"]}}}
            first = config._migrate_removed_fit_occasions(union)
            check("dropped", (first, union["image_generation"]["routing"]), (True, {"tpose": ["a*"]}))
            check("one info line", [("outfit_back, outfit_side" in line) for line in lines], [True])
            check("idempotent", (config._migrate_removed_fit_occasions(union), len(lines)), (False, 1))
            check("no routing", config._migrate_removed_fit_occasions({}), False)
        finally:
            config.logger = real_logger

        print("[8] never on the event loop or a GPU-queue worker")
        target = root / "out" / "c.png"
        draft_file = save(draft, root / "in" / "draft.png")

        async def on_loop():
            return vc.compose(base_back, draft_file, target)

        try:
            asyncio.run(on_loop())
            check("event loop", "no exception", "CompositeError")
        except vc.CompositeError:
            check("event loop", "CompositeError", "CompositeError")
        result = {}

        def run():
            try:
                result["rec"] = vc.compose(base_back, draft_file, target)
            except vc.CompositeError as e:
                result["error"] = str(e)

        for name in ("ProviderQueue-x", "worker"):
            result.clear()
            t = threading.Thread(target=run, name=name)
            t.start()
            t.join()
            check(f"thread {name}", ("error" in result, bool((result.get("rec") or {}).get("ok"))),
                  (True, False) if name.startswith("ProviderQueue-") else (False, True))
            if name.startswith("ProviderQueue-"):
                check("nothing written", target.exists(), False)

        print("[9] determinism")
        first = vc.compose(base_back, draft_file, root / "out" / "a.png")
        second = vc.compose(base_back, draft_file, root / "out" / "b.png")
        check("same bytes", (root / "out" / "a.png").read_bytes() == (root / "out" / "b.png").read_bytes(), True)
        check("same record", {k: v for k, v in first.items() if k != "runtime_s"},
              {k: v for k, v in second.items() if k != "runtime_s"})

        print("[10] old code")
        old = subprocess.run(["git", "-C", str(ROOT), "show", "eaa0fd58:app/imagegen/occasions.py"],
                             capture_output=True, text=True)
        if old.returncode == 0:
            check("eaa0fd58 routed the back fit", '"outfit_back": _image(' in old.stdout, True)
        else:
            print("  SKIP eaa0fd58 not in this clone")

    print("ALL OK" if not FAILS else f"FAILED: {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
