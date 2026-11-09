#!/usr/bin/env python3
"""Base body: the view guard of dressed edits (``base_body.view_guard``).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_view_guard.py

Pure image check — no world, no server; ``paths.init(<tmp>)`` runs first
anyway (the guard lives in a module that reaches world code lazily).

Fixture images (RGBA 60x120, transparent background): the figure's alpha box
is columns 10..49, rows 10..109 (100 rows). The HEAD is rows 10..21 (the top
round(100 * 0.12) = 12 rows) and only columns 20..39 (20 px); the "arms"
(rows 22..109) span columns 10..49. So the head crop is the top 12 rows of
the figure box, cropped again to its own alpha box = the 20x12 head.

Head patterns (opaque, black 0 / white 255):
  V  = left half (columns 20..29) white, right half black;
  Vm = V mirrored (right half white);
  H  = top 6 rows white, bottom 6 black;
  Hm = H mirrored vertically.
Base views: front V, back Vm, left H, right Hm.

Expected, derived by hand. After the resize to 64x64 every pattern is a
function of ONE axis only (V/Vm of the column, H/Hm of the row); zero-mean
normalized cross-correlation (ZNCC):
  * a pattern with itself: 1;
  * V with Vm (and H with Hm): the bilinear resize is symmetric about the
    centre, so Vm's vector is V's mirrored = 255 - V's; zero-mean -> exactly
    the negative -> -1;
  * V with H: f(x) * g(y) summed = (sum f) * (sum g) = 0 * 0 = 0.
[1] dressed front with head V (body painted another colour — the body is
    not part of the guard): scores {front 1.0, back -1.0, left 0.0, right
    0.0}, best front, ok.
[2] dressed BACK whose head shows V (turned toward the camera): same scores,
    best front -> ok False.
[3] dressed left with head H: {front 0.0, back 0.0, left 1.0, right -1.0},
    ok. Dressed right with head H -> best left, ok False.
[4] An opaque image (no transparent pixel = no matte): ok True, "skipped".
    The own base view missing (None): ok True, "skipped", even though the
    others score.
[5] The head share decides what is compared: the arms below row 21 carry
    pattern Hm in the dressed front only — scores unchanged from [1].
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def figure(path: Path, head: str, *, arms_value=128, arms_pattern: str = "", opaque=False):
    from PIL import Image
    im = Image.new("RGBA", (60, 120), (90, 90, 90, 255) if opaque else (0, 0, 0, 0))
    for y in range(22, 110):
        for x in range(10, 50):
            value = arms_value
            if arms_pattern == "Hm":
                value = 0 if y < 66 else 255
            im.putpixel((x, y), (value, value, value, 255))
    for y in range(10, 22):
        for x in range(20, 40):
            white = {"V": x < 30, "Vm": x >= 30, "H": y < 16, "Hm": y >= 16}[head]
            v = 255 if white else 0
            im.putpixel((x, y), (v, v, v, 255))
    im.save(path)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="view-guard-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        from app.core import base_body

        check("head share", base_body.VIEW_GUARD_HEAD_SHARE, 0.12)
        check("size", base_body.VIEW_GUARD_SIZE, 64)
        bases = {"front": figure(root / "b_front.png", "V"), "back": figure(root / "b_back.png", "Vm"),
                 "left": figure(root / "b_left.png", "H"), "right": figure(root / "b_right.png", "Hm")}
        vertical = {"front": 1.0, "back": -1.0, "left": 0.0, "right": 0.0}
        horizontal = {"front": 0.0, "back": 0.0, "left": 1.0, "right": -1.0}

        print("[1] dressed front")
        front = figure(root / "d_front.png", "V", arms_value=40)
        r = base_body.view_guard("front", front, bases)
        check("front", (r["ok"], r["best"], r["scores"]), (True, "front", vertical))

        print("[2] dressed back turned toward the camera")
        r = base_body.view_guard("back", figure(root / "d_back.png", "V"), bases)
        check("turned back", (r["ok"], r["best"], r["scores"]), (False, "front", vertical))
        r = base_body.view_guard("back", figure(root / "d_back_ok.png", "Vm"), bases)
        check("kept back", (r["ok"], r["best"]), (True, "back"))

        print("[3] sides")
        side = figure(root / "d_side.png", "H")
        r = base_body.view_guard("left", side, bases)
        check("left", (r["ok"], r["best"], r["scores"]), (True, "left", horizontal))
        r = base_body.view_guard("right", side, bases)
        check("right showing a left head", (r["ok"], r["best"]), (False, "left"))

        print("[4] cannot be measured")
        r = base_body.view_guard("front", figure(root / "opaque.png", "V", opaque=True), bases)
        check("no matte", (r["ok"], "skipped" in r), (True, True))
        r = base_body.view_guard("left", side, {**bases, "left": None})
        check("own base missing", (r["ok"], "skipped" in r), (True, True))

        print("[5] only the head counts")
        r = base_body.view_guard("front", figure(root / "d_front_arms.png", "V", arms_pattern="Hm"), bases)
        check("arms ignored", r["scores"], vertical)
        json.dumps(r)  # the record goes into a sidecar

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
