#!/usr/bin/env python3
"""Smoke: the dressed-view orientation check of a figure whose head differs
from the plain views (plan 2026-11-12-unified-worn-pieces, Task 11g-fix4,
Ruling A16) — ``base_body.view_guard(front=…)``, ``face_found``,
``head_match`` and the one retry budget per view of
``base_body._guard_dressed_views`` (``orientation_retried``).

Usage:
    ./.venv/bin/python scripts/smoke_bald_back_check.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first,
STORAGE_DIR / INSTANCE_DIR temp dirs), synthetic RGBA figures, the draft
render, the composite and the noise gate stubbed where ``_dress_view`` is
driven (the composite copies the draft — the check under test sees exactly
the draft). The view check and the framing gate are the real ones.

Fixture (built by hand; 800 rows x 400 columns, transparent background):
    head  rows 20..120, cols 150..250 (100 x 100), alpha = the ellipse of
          half-axes 50 (rows) x 42 (cols) inside it
    neck  rows 120..150, cols 185..215, skin (224, 172, 140)
    torso rows 150..420, cols 120..280 — skin on the plain views, blue
          (40, 70, 200) on the dressed ones
    arms  rows 155..420, cols 90..120 and 280..310; legs rows 420..780,
          cols 130..195 and 205..270 (skin)
    figure = rows 20..780 (height 760): the head share 0.12 of the view
    check is 91 rows (the head), the face share 0.16 is 122 rows (head and
    neck, the neck narrower than the head: the crop stays 100 px wide).
Heads (100 x 100):
    FACE      the face of scikit-image's bundled ``astronaut`` sample
              (rows 36..196, cols 143..303, resized) — a real frontal face
    BALD      skin shaded from 1.05 at the top to 0.80 at the bottom — the
              back of a bald head (no face)
    HAIR      dark brown with lighter 6 px vertical stripes — braids
    plain front = FACE under HAIR (rows < 46, cols < 26 and >= 74), plain
    back = HAIR, plain left / right = BALD with HAIR on the back half.
So the plain views are HAIRED and the shape is BALD: the dressed bald front
= FACE, its correct back = BALD, a back turned toward the camera = FACE.

Expected, derived by hand from Ruling A16:

[1] the cues
    head_match(haired dressed front, plain front) = 1.0 — the head pixels
    are identical (only the torso is dressed), correlation of a vector with
    itself. head_match(bald front, plain front) < HEAD_MATCH_MIN — the
    fixture's precondition: the bald head must read as another head (the
    hair covers the face's upper half and both sides). face_found: True on
    the bald front (a real face, centred), False on the bald back and on
    the plain back (no face in them).
    The head-likeness check WITHOUT ``front`` (the check as it stood) does
    not pick "back" for the bald back — the fixture reproduces the false
    positive of Ylva's shape oba9471e94 (2026-11-13).
[2] head matches -> the check unchanged: view_guard of the haired back
    with ``front`` = the haired dressed front equals view_guard without it.
[3] bald back against haired plain views: view_guard(front=bald front) ->
    ok, cue "face", face False, best "back". The bald front itself -> ok,
    cue "face" (a face is a front). ``_dress_view`` with drafts that are
    correct bald backs -> ONE draft render, published, no warning; then
    ``_guard_dressed_views`` -> back ok, 0 re-renders, no warning.
[4] a truly front-facing draft (FACE where the back should be):
    view_guard -> refused, best "front". ``_dress_view`` -> both drafts
    rendered (DRAFT_ATTEMPTS = 2) and both refused by the check; the view is
    stored with the warning "Dressed back may be turned toward the camera
    (back check failed after 2 attempts)".
[5] the guard after those two failed drafts (same orientation reason):
    ``orientation_retried`` = 2; ``_guard_dressed_views`` -> 0 re-renders,
    the view KEPT (dressed_views["back"] unchanged, record kept True,
    draft_attempts 2) and one warning "back view: the dressed image does
    not keep its view (a face is visible — it faces the camera); kept — its
    drafts were already re-tried for this (2 attempts)".
[6] the budget is per reason: the same turned view whose draft record shows
    ONE failed check (no retry yet) -> ``orientation_retried`` 0 and the
    guard re-renders it once (1 call).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []
SKIN = np.array([224.0, 172.0, 140.0])
BLUE = np.array([40.0, 70.0, 200.0])
HAIR = np.array([70.0, 45.0, 30.0])
HAIR_LIGHT = np.array([120.0, 85.0, 55.0])


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def heads():
    from PIL import Image
    from skimage import data
    yy, xx = np.mgrid[0:100, 0:100]
    face = np.asarray(Image.fromarray(data.astronaut()[36:196, 143:303]).resize((100, 100), Image.BILINEAR), float)
    hair = np.where((xx // 6) % 2 == 0, 1.0, 0.0)[..., None] * (HAIR_LIGHT - HAIR) + HAIR
    bald = np.clip(SKIN * (1.05 - 0.25 * yy / 100)[..., None], 0, 255)

    def over(base, mask):
        out = base.copy()
        out[mask] = hair[mask]
        return out
    return {"face": face, "bald": bald, "hair": hair,
            "plain_front": over(face, (yy < 46) | (xx < 26) | (xx >= 74)),
            "plain_left": over(bald, xx < 55), "plain_right": over(bald, xx >= 45)}


def figure(head, torso):
    yy, xx = np.mgrid[0:100, 0:100]
    ellipse = ((yy - 49.5) / 50) ** 2 + ((xx - 49.5) / 42) ** 2 <= 1
    a = np.zeros((800, 400, 4))
    a[20:120, 150:250, :3] = head
    a[20:120, 150:250, 3] = ellipse * 255
    for (y0, y1, x0, x1), colour in [((120, 150, 185, 215), SKIN), ((150, 420, 120, 280), torso),
                                     ((155, 420, 90, 120), SKIN), ((155, 420, 280, 310), SKIN),
                                     ((420, 780, 130, 195), SKIN), ((420, 780, 205, 270), SKIN)]:
        a[y0:y1, x0:x1, :3] = colour
        a[y0:y1, x0:x1, 3] = 255
    return a


def save(arr, path: Path) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA").save(path)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bald-back-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        from app.core import base_body, base_body_gates, view_composite as vc

        h = heads()
        refs = root / "refs"
        plain = {"front": save(figure(h["plain_front"], SKIN), refs / "tpose_bsig.png"),
                 "back": save(figure(h["hair"], SKIN), refs / "tpose_back_bsig.png"),
                 "left": save(figure(h["plain_left"], SKIN), refs / "tpose_left_bsig.png"),
                 "right": save(figure(h["plain_right"], SKIN), refs / "tpose_right_bsig.png")}
        bald_front = save(figure(h["face"], BLUE), refs / "tpose_sig.png")
        haired_front = save(figure(h["plain_front"], BLUE), root / "haired" / "tpose_hsig.png")
        haired_back = save(figure(h["hair"], BLUE), root / "haired" / "tpose_back_hsig.png")
        bald_back = save(figure(h["bald"], BLUE), root / "drafts_in" / "bald_back.png")
        turned = save(figure(h["face"], BLUE), root / "drafts_in" / "turned.png")

        print("[1] the cues")
        check("head match, haired dressed front", base_body.head_match(haired_front, plain["front"]), 1.0)
        check("head match, bald front < HEAD_MATCH_MIN (fixture precondition)",
              base_body.head_match(bald_front, plain["front"]) < base_body.HEAD_MATCH_MIN, True)
        check("face on the bald front / bald back / plain back",
              (base_body.face_found(bald_front), base_body.face_found(bald_back), base_body.face_found(plain["back"])),
              (True, False, False))
        check("head likeness alone misreads the bald back (fixture reproduces the false positive)",
              base_body.view_guard("back", bald_back, plain).get("best") != "back", True)

        print("[2] head matches: the check unchanged")
        check("haired back, with front == without",
              base_body.view_guard("back", haired_back, plain, front=haired_front),
              base_body.view_guard("back", haired_back, plain))

        print("[3] bald back against haired plain views")
        r = base_body.view_guard("back", bald_back, plain, front=bald_front)
        check("bald back accepted by the face cue", (r["ok"], r.get("cue"), r.get("face"), r.get("best")),
              (True, "face", False, "back"))
        r = base_body.view_guard("front", bald_front, plain, front=bald_front)
        check("bald front accepted", (r["ok"], r.get("cue"), r.get("best")), (True, "face", "front"))

        renders: list = []
        source = {"draft": bald_back}

        def render_draft(character_name, view, *, stem, refs_dir, prompt, common, sidecar_extra, **kw):
            renders.append(view)
            path = Path(str(stem) + ".png")
            path.write_bytes(source["draft"].read_bytes())
            path.with_suffix(".json").write_text(json.dumps({"n": len(renders), **sidecar_extra}))
            return path

        def compose(base_view, draft_file, target, *, rule="outfit", background=None, mask_target=None, head=False, base_alpha=False):
            Path(target).write_bytes(Path(draft_file).read_bytes())
            rec = {"version": vc.VERSION, "rule": rule, "ok": True, "iou": 0.99,
                   "coverage": {"score": 0.9, "region": 0.2}, "mask_share": 0.3}
            rec["reasons"] = vc.check(rec)
            return rec

        real = (base_body.render_view_edit, base_body.draft_prompt, vc.compose, base_body_gates.noise_gate)
        base_body.render_view_edit = render_draft
        base_body.draft_prompt = lambda *a, **k: ("p", "n")
        vc.compose = compose
        base_body_gates.noise_gate = lambda *a, **k: {"ok": True, "score": 1.0}
        kw = dict(signature="sig", bsig="bsig", pieces={}, items=[], profile={}, front=bald_front,
                  base_views=plain, refs_dir=refs, size=(400, 800))
        rerenders: list = []

        def rerender(view):
            rerenders.append(view)
            return None
        try:
            path, warning = base_body._dress_view("Demo", "back", **kw)
            meta = json.loads(path.with_suffix(".json").read_text())
            check("one draft, published, no warning", (renders, path.name, warning),
                  (["back"], "tpose_back_sig.png", None))
            check("its record", (meta["fit_gate"]["ok"], len(meta["fit_gate"]["attempts"]),
                                 meta["fit_gate"]["attempts"][0]["guard"].get("cue")), (True, 1, "face"))
            views = {"front": bald_front, "back": path}
            record, warnings = base_body._guard_dressed_views("Demo", "sig", "bsig", views, plain, rerender=rerender)
            check("guard: back ok, 0 re-renders, no warning",
                  (record["back"]["ok"], rerenders, warnings, views["back"]), (True, [], [], path))

            print("[4] a truly front-facing draft")
            r = base_body.view_guard("back", turned, plain, front=bald_front)
            check("refused", (r["ok"], r.get("cue"), r.get("face"), r.get("best")), (False, "face", True, "front"))
            renders.clear()
            source["draft"] = turned
            path, warning = base_body._dress_view("Demo", "back", reuse_draft=False, **kw)
            meta = json.loads(path.with_suffix(".json").read_text())
            check("two drafts, both refused by the check",
                  (renders, [a["guard"]["ok"] for a in meta["fit_gate"]["attempts"]]), (["back", "back"], [False, False]))
            check("stored with the warning", warning,
                  "Dressed back may be turned toward the camera (back check failed after 2 attempts)")

            print("[5] the guard after two failed drafts: no third render")
            views = {"front": bald_front, "back": path}
            result = base_body.dressed_view_check("back", path, plain, front=bald_front)
            check("orientation_retried", base_body.orientation_retried("back", path, result), 2)
            record, warnings = base_body._guard_dressed_views("Demo", "sig", "bsig", views, plain, rerender=rerender)
            check("0 re-renders, kept", (rerenders, views["back"], record["back"].get("kept"),
                                         record["back"].get("draft_attempts")), ([], path, True, 2))
            check("the warning", warnings,
                  ["back view: the dressed image does not keep its view (a face is visible — it faces the camera); "
                   "kept — its drafts were already re-tried for this (2 attempts)"])

            print("[6] one failed draft only: the guard re-renders once")
            meta["fit_gate"]["attempts"] = meta["fit_gate"]["attempts"][:1]
            path.with_suffix(".json").write_text(json.dumps(meta))
            check("orientation_retried", base_body.orientation_retried("back", path, result), 0)
            views = {"front": bald_front, "back": path}
            base_body._guard_dressed_views("Demo", "sig", "bsig", views, plain, rerender=rerender)
            check("one re-render", rerenders, ["back"])
        finally:
            base_body.render_view_edit, base_body.draft_prompt, vc.compose, base_body_gates.noise_gate = real

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
