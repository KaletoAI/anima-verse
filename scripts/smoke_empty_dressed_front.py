#!/usr/bin/env python3
"""Smoke: an EMPTY composite only where the dressed front may be bare (round 2026-11-25, Henrik's naked back —
``view_composite`` EMPTY, ``base_body.front_garment_region`` / ``empty_view_refused`` / ``stored_draft``).

Usage:
    ./.venv/bin/python scripts/smoke_empty_dressed_front.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first, STORAGE_DIR / INSTANCE_DIR temp dirs),
the synthetic box figure of ``_smoke_back_view.py``; the turn, the draft render and the view gates are stubbed, the
composite is the REAL one.

Fixture (smoke_view_composite.py's, by hand): base B = the skin figure (head, neck, torso, arms, legs; 30200 px);
D = B plus a blue rectangle R rows 130..210, cols 110..190 (6400 px) on the torso.

Expected values, derived by hand from the rule (module docstring of view_composite, EMPTY):

[1] EMPTY_FRONT_MAX = round(PUT_ON_MIN_REGION 0.03 / BACK_FRONT_RATIO_MIN 0.90, 4) = round(0.033333.., 4) = 0.0333.
    The ratio is the smallest back/front garment region of the published dressed backs of Anima Divide with a front
    record that kept the clothing (2026-11-25): Rurik ob5aefa093 0.8332 / 0.9174 = 0.9082 -> 0.90 (the three below —
    Henrik 0.0, Maximilian ob3b1c4c89 0.530, Arvid obf65c5d8c 0.606 — lost the shirt; [8] refuses them).
[2] ``check`` of a record that puts nothing on (coverage nothing, region 0.0) and lines up (iou 1.0):
    front_region 0.812 (Henrik's dressed front, oba9fcfdc7) -> exactly ["nothing put on although the dressed front
    wears clothing (garment region 0.0000, front 0.8120 >= 0.0333)"]; front 0.0333 -> that reason (">="); front
    0.0332 -> []; front 0.0196 (a belt alone, the piece rule's number) -> []; front 0.0055 (a necklace, the piece rule's number) -> []; no front_region -> [] (the old rule).
[3] composite_arrays(B, B): front_region 0.812 -> ok False, not empty, reasons = [2]'s text, record front_region
    0.812; front_region 0.0055 and None -> EMPTY (ok True, empty True, composite = B exactly). composite_arrays(B, D,
    front_region 0.812) -> ok True, not empty (the rule never touches a composite that puts something on).
[4] The code before the fix (``git show f70077f3c:app/core/view_composite.py``): composite_arrays(B, B) -> ok True,
    empty True — the bare back passed, whatever the front wore.
[5] ``base_body._dress_view`` (back; turn, draft render and gates stubbed; the composite real). The dressed front's
    sidecar carries ``edit_composite.coverage.region``:
    (a) region 0.812, draft 1 = B (nothing on), draft 2 = D -> attempt 1 refused, attempt 2 published: fit_gate
        chosen 2, 2 attempts, attempt 1's reasons = [2]'s text with its own numbers; the view is no EMPTY (composite
        a record, ok True); drafts/tpose_back_sig.png = draft 2; drafts/turn/tpose_back_sig.png = turn 2's cut-out
        (its bytes: the 4 x 4 marker "turn2").
    (b) region 0.812, both drafts = B -> OutfitError whose text names NOTHING_ALTHOUGH_DRESSED twice (refusal()), the
        stored back stays (bytes "OLD"), no new draft, no turn cut-out.
    (c) region 0.0055 (a front-only necklace), draft 1 = B -> one draft, published EMPTY (composite "empty").
    (d) the front has no edit record -> draft 1 = B published EMPTY (the old rule: unknown front).
[6] ``stored_draft`` / ``empty_view_refused`` (character Demo, signature obX): a front with region 0.812, the back
    view's sidecar composite "empty", the draft made from that front by the base edit with the turned second picture
    -> empty_view_refused True, stored_draft None (the draft that lost the clothing is never composited again);
    front region 0.0055 -> False, the draft; the back a real composite record -> False, the draft; the front with no
    record -> False, the draft. shape_view of the EMPTY back on a dressed front -> None (rendered anew when the shape
    is next meshed).
[7] ``outfit_cache_gc._ref_files``: drafts/turn/tpose_back_obX.png is filed under obX (it goes with its signature).
[8] The band rule (``garment_bands`` / ``clothing_lost``, live Henrik copy 2026-11-25: the regenerated back kept the
    trousers and lost the shirt and passed — region 0.471 / front 0.812 = 0.58, no EMPTY). Fixture: F = B with the
    torso (rows 110..230, cols 100..200) and both legs blue (a shirt and trousers), K = B with the legs blue only (the
    shirt lost). The measure works on cells of 0.48 px (192 of 400 rows): the figure rows 19..172 (154), the head
    0.12 x 154 = 18 more -> bands from cell row 37 to 173 in 6 of ~22.7 rows (edges 37, 59, 82, 105, …).
    Band 0 (cells 37..59 = image rows 77..123) holds head 11 x 24 = 264, neck 5 x 9.6 = 48, the torso's top
    6 x 48 = 288 and the arms 4 x 19 = 77 cells -> 288 / 677 = 0.425 < 0.5 (not a dressed band); bands 1 and 2
    (torso + arms only) torso / (torso + arms) = 100 / 140 = 0.714 (each checked within 0.03). K keeps 0 of bands
    1 and 2 ->
    clothing_lost(F, K) = [1, 2]; composite_arrays(B, K, front_bands=F) -> ok False with the CLOTHING_LOST reason;
    (B, F) -> ok True; a necklace front (rows 150..160, cols 140..160: share 200 / 6580 = 0.03 in band 1) on a bare
    back -> [] (no band dressed). Limit pairs from the derivation: front 1.0, back 0.551 (Tilda) kept; back 0.164
    (Arvid, the braces) lost. Before the fix (f70077f3c) composite_arrays(B, K) -> ok True (the shirt-less back
    passed).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _smoke_back_view import FAILS, check, save  # noqa: E402
from _smoke_back_view import box_figure as figure  # noqa: E402

BLUE = (40, 70, 200)
BODY = [(40, 100, 125, 175), (100, 110, 140, 160), (110, 230, 100, 200), (115, 230, 80, 100),
        (115, 230, 200, 220), (230, 360, 105, 145), (230, 360, 155, 195)]
RECT = (130, 210, 110, 190)
PIN = "f70077f3c"
REASON = "nothing put on although the dressed front wears clothing (garment region 0.0000, front {f} >= 0.0333)"


def _old_view_composite():
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PIN}:app/core/view_composite.py"], capture_output=True,
                         text=True, check=True).stdout
    path = Path(tempfile.mkdtemp(prefix="old-vc-")) / "old_view_composite.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("old_view_composite", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="empty-dressed-front-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        from app.core import base_body, outfit_cache_gc, view_composite as vc

        base = figure(BODY)
        dressed = figure(BODY + [(*RECT, BLUE)])

        print("[1] the limit")
        check("EMPTY_FRONT_MAX", vc.EMPTY_FRONT_MAX, 0.0333)
        check("derived", round(0.03 / 0.90, 4), vc.EMPTY_FRONT_MAX)

        print("[2] check()")
        nothing = {"iou": 1.0, "rule": "outfit", "coverage": {"score": 0.0, "region": 0.0, "nothing": True}}
        check("front 0.812", vc.check({**nothing, "front_region": 0.812}), [REASON.format(f="0.8120")])
        check("front 0.0333", vc.check({**nothing, "front_region": 0.0333}), [REASON.format(f="0.0333")])
        check("front 0.0332", vc.check({**nothing, "front_region": 0.0332}), [])
        check("front 0.0196 (belt)", vc.check({**nothing, "front_region": 0.0196}), [])
        check("front 0.0055 (necklace)", vc.check({**nothing, "front_region": 0.0055}), [])
        check("no front", vc.check(nothing), [])

        print("[3] composite_arrays")
        out, rec = vc.composite_arrays(base, base.copy(), front_region=0.812)
        check("dressed front: refused, no EMPTY", (rec["ok"], rec.get("empty"), rec["reasons"], rec["front_region"]),
              (False, None, [REASON.format(f="0.8120")], 0.812))
        for fr in (0.0055, None):
            out, rec = vc.composite_arrays(base, base.copy(), front_region=fr)
            check(f"front {fr}: EMPTY", (rec["ok"], rec.get("empty"), bool(np.array_equal(out, base))), (True, True, True))
        _o, rec = vc.composite_arrays(base, dressed, front_region=0.812)
        check("a draft that puts on: unchanged", (rec["ok"], rec.get("empty"), rec["reasons"]), (True, None, []))

        print(f"[4] before the fix ({PIN})")
        old = _old_view_composite()
        _o, rec = old.composite_arrays(base, base.copy())
        check("the bare back passed as EMPTY", (rec["ok"], rec.get("empty")), (True, True))

        print("[5] the dressed view's caller")
        refs = root / "refs"
        refs.mkdir()
        base_back = save(base, refs / "tpose_back_bsig.png")
        front = save(dressed, refs / "tpose_sig.png")
        stored = refs / "tpose_back_sig.png"
        drafts_plan: list = []
        turns: list = []

        def set_front(region):
            meta = {"dressed": True}
            if region is not None:
                meta["edit_composite"] = {"coverage": {"score": 0.97, "region": region}}
            front.with_suffix(".json").write_text(json.dumps(meta))

        def render_draft(character_name, view, *, stem, **kw):
            arr = drafts_plan.pop(0)
            path = save(arr, Path(str(stem) + ".png"))
            path.with_suffix(".json").write_text(json.dumps({"n": len(turns)}))
            return path

        def turned(character_name, view, *, stem, front, **kw):
            turns.append(view)
            out = Path(stem).parent / f"{Path(stem).name}_cut.png"
            out.write_bytes(f"turn{len(turns)}".encode())
            return out

        real = (base_body.render_view_edit, base_body.turned_cutout, base_body.view_guard)
        from app.core import base_body_gates
        real_gates = (base_body_gates.noise_gate, base_body_gates.framing_gate)
        base_body.render_view_edit = render_draft
        base_body.turned_cutout = turned
        base_body.view_guard = lambda view, path, views, front=None: {"ok": True, "best": view}
        base_body_gates.noise_gate = lambda *a, **k: {"ok": True, "score": 1.0}
        base_body_gates.framing_gate = lambda *a, **k: {"ok": True}
        real_prompt = base_body.picture_edit_prompt
        base_body.picture_edit_prompt = lambda *a, **k: ("p", "n")
        kw = dict(signature="sig", bsig="bsig", pieces={}, items=[], profile={}, front=front,
                  base_views={"back": base_back}, refs_dir=refs, size=(300, 400))
        drafts = refs / base_body.DRAFT_DIR
        try:
            set_front(0.812)
            drafts_plan[:] = [base, dressed]
            path, warning = base_body._dress_view("Demo", "back", **kw)
            meta = json.loads(path.with_suffix(".json").read_text())
            gate = meta["fit_gate"]
            first = gate["attempts"][0]["composite"]
            check("(a) attempt 1 refused, attempt 2 published",
                  (gate["chosen"], len(gate["attempts"]), first["ok"], first["reasons"]),
                  (2, 2, False, [REASON.format(f="0.8120")]))
            check("(a) the view is no EMPTY", (isinstance(meta["composite"], dict), meta["composite"].get("ok")),
                  (True, True))
            check("(a) draft 2 kept", (drafts / "tpose_back_sig.png").read_bytes() == save(
                dressed, root / "d.png").read_bytes(), True)
            check("(a) turn 2's cut-out kept", (drafts / base_body.TURN_CUT_DIR / "tpose_back_sig.png").read_bytes(),
                  b"turn2")

            for p in list(drafts.rglob("*")):
                if p.is_file():
                    p.unlink()
            stored.write_bytes(b"OLD")
            stored.with_suffix(".json").unlink()
            turns.clear()
            drafts_plan[:] = [base, base]
            try:
                base_body._dress_view("Demo", "back", **kw)
                check("(b) refused", "no exception", "OutfitError")
            except base_body.OutfitError as e:
                check("(b) the refusal names the dressed front twice", str(e).count(vc.NOTHING_ALTHOUGH_DRESSED), 2)
            check("(b) the stored back stays", stored.read_bytes(), b"OLD")
            check("(b) no draft, no turn cut-out kept",
                  sorted(p.name for p in drafts.rglob("*.png")), [])

            set_front(0.0055)
            turns.clear()
            drafts_plan[:] = [base]
            path, _w = base_body._dress_view("Demo", "back", **kw)
            check("(c) necklace front: one draft, EMPTY", (len(turns), json.loads(path.with_suffix(".json").read_text())
                                                           .get("composite")), (1, "empty"))
            set_front(None)
            turns.clear()
            drafts_plan[:] = [base]
            path, _w = base_body._dress_view("Demo", "back", **kw)
            check("(d) unknown front: the old rule", (len(turns), json.loads(path.with_suffix(".json").read_text())
                                                      .get("composite")), (1, "empty"))
        finally:
            base_body.render_view_edit, base_body.turned_cutout, base_body.view_guard = real
            base_body.picture_edit_prompt = real_prompt
            base_body_gates.noise_gate, base_body_gates.framing_gate = real_gates

        print("[6] stored_draft / empty_view_refused")
        from app.models.character import get_character_dir
        cdir = get_character_dir("Demo", create=True) / "model_refs"
        s_front = save(dressed, cdir / "tpose_obX.png")
        s_back = save(base, cdir / "tpose_back_obX.png")
        s_draft = save(base, cdir / base_body.DRAFT_DIR / "tpose_back_obX.png")
        s_draft.with_suffix(".json").write_text(json.dumps({"front_sha256": base_body.file_sha256(s_front),
                                                            "draft_method": base_body.DRAFT_BASE_EDIT,
                                                            "turned_second": True}))

        def front_meta(region):
            meta = {} if region is None else {"edit_composite": {"coverage": {"region": region}}}
            s_front.with_suffix(".json").write_text(json.dumps(meta))
            base_body._hash_cache.clear()

        def back_meta(composite):
            s_back.with_suffix(".json").write_text(json.dumps({"fit": "composite", "composite": composite}))

        back_meta("empty")
        front_meta(0.812)
        check("dressed front, EMPTY back: refused, not reused",
              (base_body.empty_view_refused("Demo", "back", "obX", s_front),
               base_body.stored_draft("Demo", "back", "obX", s_front)), (True, None))
        front_meta(0.0055)
        check("necklace front: reused", (base_body.empty_view_refused("Demo", "back", "obX", s_front),
                                         base_body.stored_draft("Demo", "back", "obX", s_front)), (False, s_draft))
        front_meta(0.812)
        back_meta({"ok": True, "coverage": {"region": 0.6}})
        check("a real composite: reused", base_body.stored_draft("Demo", "back", "obX", s_front), s_draft)
        back_meta("empty")
        front_meta(None)
        check("no front record: reused (old rule)", base_body.stored_draft("Demo", "back", "obX", s_front), s_draft)
        front_meta(0.812)
        real_shas = base_body.shape_view_shas
        base_body.shape_view_shas = lambda *a, **k: {"front": "x", "back": "y"}
        try:
            check("shape_view of the EMPTY back on a dressed front", base_body.shape_view("Demo", "back", "obX", "bsig"),
                  None)
            back_meta({"ok": True, "version": vc.VERSION, "iou": 1.0, "coverage": {"score": 0.9, "region": 0.6}})
            check("shape_view of a real composite", base_body.shape_view("Demo", "back", "obX", "bsig"), s_back)
        finally:
            base_body.shape_view_shas = real_shas

        print("[7] the kept turn cut-out goes with its signature")
        kept = cdir / base_body.DRAFT_DIR / base_body.TURN_CUT_DIR / "tpose_back_obX.png"
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_bytes(b"x")
        check("filed under obX", kept in outfit_cache_gc._ref_files("Demo").get("obX", []), True)

        print("[8] the band rule: a shirt lost on the back")
        torso, legs = (110, 230, 100, 200, BLUE), [(230, 360, 105, 145, BLUE), (230, 360, 155, 195, BLUE)]
        shirt = figure(BODY + [torso] + legs)
        no_shirt = figure(BODY + legs)
        fb = vc.garment_bands(base, shirt)
        check("front bands 0..2 by hand (0.425, 0.714, 0.714)",
              [abs(a - b) <= 0.03 for a, b in zip(fb[:3], (0.425, 0.714, 0.714))], [True, True, True])
        check("band 0 not dressed", fb[0] < vc.BAND_DRESSED_MIN, True)
        kb = vc.garment_bands(base, no_shirt)
        check("the shirt-less back keeps nothing of bands 1, 2", kb[1:3], [0.0, 0.0])
        check("clothing_lost", vc.clothing_lost(fb, kb), [1, 2])
        _o, rec = vc.composite_arrays(base, no_shirt, front_bands=fb)
        check("refused", (rec["ok"], all(r.startswith(vc.CLOTHING_LOST) for r in rec["reasons"]), len(rec["reasons"])),
              (False, True, 1))
        _o, rec = vc.composite_arrays(base, shirt, front_bands=fb)
        check("the dressed back passes", (rec["ok"], rec["reasons"]), (True, []))
        necklace = vc.garment_bands(base, figure(BODY + [(150, 160, 140, 160, BLUE)]))
        check("a necklace front dresses no band", (max(necklace) < vc.BAND_DRESSED_MIN,
                                                   vc.clothing_lost(necklace, vc.garment_bands(base, base))), (True, []))
        check("limit pairs", (vc.clothing_lost([1.0], [0.551]), vc.clothing_lost([1.0], [0.164])), ([], [0]))
        _o, rec = old.composite_arrays(base, no_shirt)
        check(f"before the fix ({PIN}) the shirt-less back passed", rec["ok"], True)

    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
