#!/usr/bin/env python3
"""Ruling A96: both side views facing the same edge are resolved (the one against the convention is mirrored), and a
Run all / Build stops before the base model while a side view faces the wrong way, both face the same edge, or one
holds an arm clearly away from the body.

Usage:
    ./.venv/bin/python scripts/smoke_side_view_holds.py

No world, no server, no hub: synthetic mattes in a temp dir; the Build's model step is patched to a recorder.

Fixture (a 200 x 400 RGBA canvas, opaque = the figure): a body column x 80..120 (41 px) on rows 20..339, a leg
x 90..110 on rows 340..372 and a sole x 85..140 on rows 373..380 — figure height h = 361 (rows 20..380), the sole
reaching forward to image-RIGHT. An "arm" adds x 121..160 on rows 100..110.

Expected, by hand:
[1] facing (FOOT_BAND 0.12 -> int(43.32) = 43 rows, region rows 337..380 = 44 rows, one part): leg rows = the
    part's top 30 % (rows 337..350: 3 rows of the body 80..120 + 11 of the leg 90..110, mean x 100); sole rows = the
    bottom 30 % (rows 367..380: 85 .. 140) -> score ((140 - 100) - (100 - 85)) / 55 = 25 / 55 = 0.455 -> "right",
    confidence min(1, 0.455 / 0.4) = 1.0. The mirrored image reads "left" at the same confidence.
[2] arm reach: ARM_BAND rows 20 + int(0.12 h) = 63 .. 20 + int(0.45 h) = 182 (exclusive); HIP_BAND rows 182 .. 218,
    every row 80..120, so the hip line is back 80 / front 120. Without the arm nothing passes it: 0.0. With it the
    rows 100..110 reach x 160: (160 - 120) / 361 = 0.111 >= ARM_REACH_LIMIT 0.06 -> arms_out.
[3] resolve_pair: left.png and right.png both face right -> pair_state same (facing "right"); the LEFT view's
    convention is the left edge, so left.png is mirrored (auto, sidecar record, original kept) and reads "left";
    the pair is no longer the same; right.png is untouched (same bytes). A second call does nothing (None).
[4] side_view_holds: before the resolve (both facing right) left.png is SURE wrong (confidence 1.0 >= AUTO 0.75)
    -> [HOLD_WRONG left] (a sure-wrong line replaces the same-edge line); the resolved pair -> []; the right view
    with the arm -> [HOLD_ARMS right].
[5] _run_plain_body with no views due and the model due: holds present -> returns HOLD_PREFIX + the holds joined,
    generate_base_model NOT called; no holds -> generate_base_model called once (force=True), "" returned.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def figure(path: Path, *, arm: bool = False, mirrored: bool = False) -> None:
    from PIL import Image, ImageOps
    import numpy as np
    a = np.zeros((400, 200), dtype=np.uint8)
    a[20:340, 80:121] = 255
    a[340:373, 90:111] = 255
    a[373:381, 85:141] = 255
    if arm:
        a[100:111, 121:161] = 255
    rgba = np.zeros((400, 200, 4), dtype=np.uint8)
    rgba[..., :3] = 128
    rgba[..., 3] = a
    image = Image.fromarray(rgba, "RGBA")
    if mirrored:
        image = ImageOps.mirror(image)
    image.save(path)
    path.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T20:00:00Z"}), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="side-holds-"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    try:
        from app.core import paths
        paths.init(str(tmp / "world"))
        from app.core import view_facing as vf
        refs = tmp / "refs"
        refs.mkdir()

        print("[1] facing of the fixture")
        figure(refs / "f.png")
        figure(refs / "fm.png", mirrored=True)
        got = vf.measure(refs / "f.png")
        check("fixture", (got["facing"], got["score"], got["confidence"]), ("right", 0.455, 1.0))
        got = vf.measure(refs / "fm.png")
        check("mirrored fixture", (got["facing"], got["confidence"]), ("left", 1.0))

        print("[2] arm reach")
        figure(refs / "arm.png", arm=True)
        check("no arm", (vf.arm_reach(refs / "f.png"), vf.arms_out(refs / "f.png")), (0.0, False))
        check("arm out", (vf.arm_reach(refs / "arm.png"), vf.arms_out(refs / "arm.png")), (0.111, True))

        print("[3] resolve_pair")
        left, right = refs / "left.png", refs / "right.png"
        figure(left)
        figure(right)
        right_bytes = right.read_bytes()
        check("same before", vf.pair_state(left, right), {"same": True, "facing": "right"})
        check("holds before", vf.side_view_holds(left, right), [vf.HOLD_WRONG.format(view="left")])
        check("resolved view", vf.resolve_pair(left, right), "left")
        check("left now", vf.measure(left)["facing"], "left")
        check("left record", bool((vf.mirror_record(left) or {}).get("auto")), True)
        check("original kept", vf.restorable(left), True)
        check("right untouched", right.read_bytes() == right_bytes, True)
        check("pair after", vf.pair_state(left, right)["same"], False)
        check("second call", vf.resolve_pair(left, right), None)

        print("[4] side_view_holds")
        check("resolved pair", vf.side_view_holds(left, right), [])
        figure(right, arm=True)
        check("right arm out", vf.side_view_holds(left, right), [vf.HOLD_ARMS.format(view="right")])
        # Both unsure-but-same: confidence between SAME (0.5) and AUTO (0.75) is only reachable on real views;
        # the same-edge line is pinned by pair_state above.

        print("[5] the Build stops before the model")
        from app.core import base_body, figure_build
        calls = []

        def model(name, **kw):
            calls.append(kw)
            return {"ok": True}

        step = figure_build.Step("plain_body", "Plain body", 3)
        with patch.object(base_body, "base_refresh_plan", lambda *a, **k: {"views": [], "model": True}), \
                patch.object(base_body, "generate_base_model", model), \
                patch.object(figure_build, "_side_view_holds", lambda name: ["x", "y"]):
            check("held", figure_build._run_plain_body("Demo", step), vf.HOLD_PREFIX + "x; y")
            check("no model job", calls, [])
        with patch.object(base_body, "base_refresh_plan", lambda *a, **k: {"views": [], "model": True}), \
                patch.object(base_body, "generate_base_model", model), \
                patch.object(figure_build, "_side_view_holds", lambda name: []):
            check("not held", figure_build._run_plain_body("Demo", step), "")
            check("model job", calls, [{"force": True}])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("All checks passed." if not FAILS else f"FAILED: {len(FAILS)} — {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
