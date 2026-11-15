#!/usr/bin/env python3
"""Ruling A24 (T15-F1 of plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``): a dressed back/side
view carries the composite version it was made with; one composited before the current
``view_composite.VERSION`` (or recorded as passing with numbers today's checks refuse) is re-composited from its
stored draft on the CPU at its next use — no hub job; without a stored draft that follows its front it is drafted
again (one job, counted in the estimate).

Usage:
    ./.venv/bin/python scripts/smoke_composite_version_remake.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first, STORAGE_DIR / INSTANCE_DIR temp
dirs). The synthetic figures are those of ``scripts/smoke_bald_back_check.py`` (haired plain views, a haired
dressed front, a haired dressed back as the draft — the view check passes on the head). Stubbed:
``base_body.render_draft`` (copies the draft, records the view), ``draft_prompt``, ``view_composite.compose``
(copies the draft, an ok record of ``VERSION``; counted) and ``base_body_gates.noise_gate`` (ok). The view
check, the framing gate, ``stored_draft``, ``composite_outdated`` and ``_dress_view`` are real; ``refs_dir`` is the
character's ``model_refs`` (where ``draft_path`` looks).

Expected, derived by hand from Ruling A24:

[1] ``view_composite.VERSION`` == 5 (3 + the bump for A16's face check / A21's head, + A99's skin-tone garment). ``composite_outdated``:
    {fit composite, composite {version 3, ok, iou 0.99, coverage 0.9}} True (3 < 5); the same at version 5
    False; version 5 recorded ok with iou 0.90 True (today ``check`` refuses it: IoU < IOU_MIN 0.93); version 5
    ok False False (a refused composite is never published, nothing to remake); composite "empty" False;
    a model fit {fit_gate …} (no ``fit: composite``) False; {} False; version "x" True.
[2] A first ``_dress_view`` of the back: 1 draft, 1 composite, the sidecar's composite version 5.
[3] Its sidecar's composite version set back to 3 (a view of before the bump): ``_dress_view`` again — 0 new
    drafts (the stored draft follows the front), 1 more composite (the CPU re-composite), the published sidecar
    at version 5, ``fit_gate`` with ONE attempt (no new draft after it).
[4] At version 5 a further ``_dress_view`` is the ordinary C2 path (the stored draft composited again, passes,
    no draft) — still 0 new drafts: A24 adds no job to a current view.
[5] Version 3 again but the front changed (another pixel): the stored draft follows another front -> ONE new
    draft (what the estimate counts), then its composite at version 5.
[6] ``shape_view``: a stored shape view current for the plain body (``shape_view_shas`` stubbed {back: sha}) is
    returned at version 5 and None at version 3 (re-composited before the shape is meshed from it).
[7] Fails on the old code (explicit hash 21ca534b, the base of T15-F1): ``view_composite.VERSION = 3`` there and
    ``base_body`` had no ``composite_outdated``.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_bald_back_check import BLUE, SKIN, figure, heads, save  # noqa: E402

BASELINE = "21ca534b"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="composite-version-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        from app.core import base_body, base_body_gates, view_composite as vc
        from app.models.character import get_character_dir

        print("[1] composite_outdated")
        check("VERSION", vc.VERSION, 5)
        ok_rec = {"ok": True, "iou": 0.99, "coverage": {"score": 0.9, "region": 0.2}}
        table = [
            ("version 3", {"fit": "composite", "composite": {**ok_rec, "version": 3}}, True),
            ("version 5", {"fit": "composite", "composite": {**ok_rec, "version": 5}}, False),
            ("version 5, iou 0.90 recorded ok", {"fit": "composite", "composite": {**ok_rec, "version": 5,
                                                                                   "iou": 0.90}}, True),
            ("version 5, refused", {"fit": "composite", "composite": {**ok_rec, "version": 5, "ok": False,
                                                                      "iou": 0.90}}, False),
            ("empty", {"fit": "composite", "composite": "empty"}, False),
            ("model fit", {"fit_gate": {"ok": True}}, False),
            ("nothing", {}, False),
            ("version x", {"fit": "composite", "composite": {**ok_rec, "version": "x"}}, True),
        ]
        for label, record, want in table:
            check(f"outdated: {label}", base_body.composite_outdated(record), want)

        h = heads()
        refs = get_character_dir("Demo", create=True) / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        plain = {"front": save(figure(h["plain_front"], SKIN), refs / "tpose_bsig.png"),
                 "back": save(figure(h["hair"], SKIN), refs / "tpose_back_bsig.png"),
                 "left": save(figure(h["plain_left"], SKIN), refs / "tpose_left_bsig.png"),
                 "right": save(figure(h["plain_right"], SKIN), refs / "tpose_right_bsig.png")}
        dressed_front = figure(h["plain_front"], BLUE)
        front = save(dressed_front, refs / "tpose_sig.png")
        draft_img = save(figure(h["hair"], BLUE), root / "drafts_in" / "back.png")

        renders, composes = [], []

        def render_draft(character_name, view, *, stem, front, refs_dir, prompt, profile, common, sidecar_extra):
            renders.append(view)
            path = Path(str(stem) + ".png")
            path.write_bytes(draft_img.read_bytes())
            path.with_suffix(".json").write_text(json.dumps(sidecar_extra))
            return path

        def compose(base_view, draft_file, target, *, rule="outfit", background=None, mask_target=None, head=False):
            composes.append(Path(draft_file).name)
            Path(target).write_bytes(Path(draft_file).read_bytes())
            rec = {"version": vc.VERSION, "rule": rule, "ok": True, "iou": 0.99,
                   "coverage": {"score": 0.9, "region": 0.2}, "mask_share": 0.3}
            rec["reasons"] = vc.check(rec)
            return rec

        real = (base_body.render_draft, base_body.draft_prompt, vc.compose, base_body_gates.noise_gate,
                base_body.shape_view_shas)
        base_body.render_draft = render_draft
        base_body.draft_prompt = lambda *a, **k: ("p", "n")
        vc.compose = compose
        base_body_gates.noise_gate = lambda *a, **k: {"ok": True, "score": 1.0}
        kw = dict(signature="sig", bsig="bsig", pieces={}, items=[], profile={}, front=front,
                  base_views=plain, refs_dir=refs, size=(400, 800))

        def version_of(path):
            return (json.loads(path.with_suffix(".json").read_text()).get("composite") or {}).get("version")

        def set_version(path, version):
            meta = json.loads(path.with_suffix(".json").read_text())
            meta["composite"]["version"] = version
            path.with_suffix(".json").write_text(json.dumps(meta))

        try:
            print("[2] the first dressed back")
            path, _warning = base_body._dress_view("Demo", "back", **kw)
            check("1 draft, 1 composite, version 5", (renders, len(composes), version_of(path)), (["back"], 1, 5))

            print("[3] a view of before the bump: re-composited from its stored draft")
            set_version(path, 3)
            check("outdated now", base_body.composite_outdated(json.loads(path.with_suffix(".json").read_text())),
                  True)
            path, _warning = base_body._dress_view("Demo", "back", **kw)
            meta = json.loads(path.with_suffix(".json").read_text())
            check("0 new drafts, 1 more composite, version 5, one attempt",
                  (renders, len(composes), version_of(path), len(meta["fit_gate"]["attempts"])),
                  (["back"], 2, 5, 1))

            print("[4] a current view: no job either")
            base_body._dress_view("Demo", "back", **kw)
            check("0 new drafts", renders, ["back"])

            print("[5] the front changed: one new draft")
            dressed_front[400, 200, :3] = (1, 2, 3)
            save(dressed_front, front)
            set_version(path, 3)
            path, _warning = base_body._dress_view("Demo", "back", **kw)
            check("1 new draft, version 5", (renders, version_of(path)), (["back", "back"], 5))

            print("[6] shape_view")
            shape_back = save(figure(h["hair"], BLUE), refs / "tpose_back_obshape01.png")
            shape_back.with_suffix(".json").write_text(json.dumps(
                {"fit": "composite", "composite": {**ok_rec, "version": 5}}))
            base_body.shape_view_shas = lambda *a, **k: {"back": "sha"}
            check("version 5: the stored view", base_body.shape_view("Demo", "back", "obshape01", "bsig"), shape_back)
            shape_back.with_suffix(".json").write_text(json.dumps(
                {"fit": "composite", "composite": {**ok_rec, "version": 3}}))
            check("version 3: None (re-composited first)",
                  base_body.shape_view("Demo", "back", "obshape01", "bsig"), None)
        finally:
            (base_body.render_draft, base_body.draft_prompt, vc.compose, base_body_gates.noise_gate,
             base_body.shape_view_shas) = real

        print(f"[7] fails on the old code ({BASELINE})")
        old_vc = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/view_composite.py"],
                                capture_output=True, text=True).stdout
        old_bb = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/base_body.py"],
                                capture_output=True, text=True).stdout
        check(f"{BASELINE}: VERSION 3, no composite_outdated",
              ("\nVERSION = 3\n" in old_vc, bool(old_bb), "composite_outdated" in old_bb), (True, True, False))

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
