#!/usr/bin/env python3
"""Ruling A23 a/b/c (T15-F1 of plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``): a wanted
own-mesh piece whose fit on the wanted body shape is refused never leads to a published outfit model lacking it,
the refusal is a cached failure an automatic Build does not re-plan, a manual Build re-fits it once, and the
resolver never puts the (mesh-ready) piece into an interim body while a figure is shown.

Usage:
    ./.venv/bin/python scripts/smoke_figure_fit_refused.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no GPU, no server. The resolver
(``figure._delivered``), the plan (``figure_build.plan``), ``_run_fits`` / ``_run_assemble`` / ``_worn_rows`` /
``refit`` are real; the rest are tables (the stubs of ``scripts/smoke_figure_a11.py``, narrowed):
``inventory.get_item`` / ``motion_item_cache.item_snapshot`` serve ITEMS; ``base_body.is_base_pipeline`` True,
``base_signature`` BSIG, ``base_model_sha256`` "basesha", ``dress_text`` "wear:" + the visible ids,
``dressed_views`` (front, back), ``shape_view*`` none, ``stored_base_haired`` True, ``prompts_current`` True,
``base_refresh_plan`` {}, ``dressed_image`` a view for every figure (nothing to render),
``dressed_view_estimate`` 3; ``figure.stored_shape`` -> a sidecar for the keys in STORED;
``garment_store.accepted_fit`` -> the jacket's closed base fit ``jacket_0123456789ab.glb`` (its mesh is ready:
no chain, no interim for want of a mesh); ``garments.body_fit`` -> a fit for the (item, shape) pairs in
BODY_FITS, else the error "refused — stub"; ``garments.cached_failure`` None; ``garments.run_estimate`` 0 jobs,
no step; ``garment_refit.work_count`` 0, ``tracked`` records; ``garment_store.clear_failure_on_body`` and
``figure_build.start`` record; ``model3d.find_model3d`` -> MODEL["path"] for MODEL["sig"] only,
``find_model3d_serving`` -> (SERVED, "nearest"), ``_read_sidecar`` -> MODEL["meta"];
``model_refs.current_outfit_state`` -> the worn outfit's signature.

Fixture: "Demo", hair in the body (the worn hairstyle "hair_body"), items blouse [top] IN THE BODY, jacket
[outer] own mesh, closable. Worn W = {top: blouse, outer: jacket}. The wanted figure: shape SB = the shape of
{blouse} (stored, meshed), own (jacket,).

Expected, derived by hand from rulings A23 a/b/c:

[1] Nothing shown (no model of W, nothing served): the jacket's fit on SB refused -> it joins the body as before
    A23 (rule 1 of ``_delivered``, ruling A11): the delivered shape is not SB, in_body (blouse, jacket),
    in_body_own (jacket,), fit_refused {} — there is nothing to keep.
[2] The model of W stored, built as F = the figure on SB with the jacket grafted (the fit accepted then): its fit
    on SB refused now -> delivered = F (``as_dict`` equal), kept True, fit_refused {jacket: "refused — stub"};
    never an interim (interim {}). The AUTOMATIC plan has no "fits" and no "assemble" step (a cached failure is
    not re-planned); the MANUAL plan has Step("fits", "Re-fit on the body shape (refused before): Jacket", 0)
    then Step("assemble", …). ``_run_assemble`` -> "Not assembled: the fit of Jacket on the body shape is
    refused — the figure built before stays served" (nothing published). The worn row of the jacket: state
    "fit_refused", fit_refused "refused — stub". ``refit(blouse)`` -> ValueError (its fit is not refused);
    ``refit(jacket)`` clears the refusal of (jacket, "0123456789ab") on SB and starts an AUTOMATIC Build with
    reason "refit". The manual Build's fits step, refused again -> "Fit refused — Jacket: refused — stub; the
    figure built before stays served", no CPU refit run (assemble depends on fits: ``DEPENDS["assemble"]`` ∋
    "fits"); accepted (BODY_FITS ∋ (jacket, SB)) -> "", the CPU refits run once, and the figure is no longer
    refused (delivered own (jacket,), fit_refused {}).
[3] A model served for ANOTHER outfit only (no model of W, the nearest stand-in): delivered on SB, own (),
    left_out {jacket: "Fit refused — refused — stub"}, fit_refused {jacket: "refused — stub"}, kept False, no
    interim — the refused jacket never goes into an interim body while a figure is shown (A23 c); the worn row
    "fit_refused".
[4] Fails on the old code (explicit hash 21ca534b, the base of T15-F1): ``figure.py`` had no ``FIT_REFUSED``
    (the refused piece always joined an interim body) and ``DEPENDS["assemble"]`` was {"plain_body"}.
"""
import copy
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASELINE = "21ca534b"
FAILS = []
BSIG = "base0123abcd"
FSIG = "0123456789ab"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def _item(item_id, slots, mode, **extra):
    return {"id": item_id, "name": item_id.title(), "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode, **extra}}


ITEMS = {"blouse": _item("blouse", ["top"], "in_body"),
         "jacket": _item("jacket", ["outer"], "own_mesh", closable=True),
         "hair_body": {"id": "hair_body", "name": "Short hair", "category": "garment", "owner": "Demo",
                       "garment": {"kind": "hair", "mesh_mode": "body", "description": "short hair"}}}
W = {"top": "blouse", "outer": "jacket"}
STORED, BODY_FITS = set(), set()
MODEL = {"sig": None, "path": None, "meta": None}
SERVED = {"path": None}
CLEARED, STARTS, REFITS = [], [], []


def profile():
    return {"model_pipeline": "base_body", "base_hairstyle": "hair_body", "equipped_pieces": dict(W),
            "equipped_mesh_pieces": {"hair": "hair_body"}, "equipped_items": []}


def stub_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=(), **_kw):
    meshed = {str(i) for i in mesh_items or ()}
    visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
    return ("wear:" + "+".join(visible)) if visible else ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-fit-refused-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")

        from app.core import (base_body, figure, figure_build, garment_refit, garment_store, garments, model3d,
                              model_refs, motion_item_cache)
        from app.models import inventory
        inventory.get_item = lambda item_id, **_kw: copy.deepcopy(ITEMS.get(str(item_id)))
        motion_item_cache.item_snapshot = lambda **_kw: copy.deepcopy(ITEMS)
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.base_signature = lambda *_a, **_kw: BSIG
        base_body.base_model_sha256 = lambda *_a, **_kw: "basesha"
        base_body.dress_text = stub_dress_text
        base_body.side_views_dressed = lambda: False
        base_body.dressed_views = lambda: ("front", "back")
        base_body.shape_view_shas = lambda *_a, **_kw: {}
        base_body.shape_view = lambda *_a, **_kw: None
        base_body.stored_base_haired = lambda *_a, **_kw: True
        base_body.prompts_current = lambda *_a, **_kw: True
        base_body.base_refresh_plan = lambda *_a, **_kw: {}
        base_body.dressed_image = lambda *_a, **_kw: root / "view.png"
        base_body.dressed_view_estimate = lambda *_a, **_kw: 3
        figure.stored_shape = lambda _c, key, **_kw: {"outfit_body": {"body_id": key}} if key in STORED else None
        base_fit = (root / "garments" / f"jacket_{FSIG}.glb", {"accepted": True})
        garment_store.accepted_fit = (lambda _c, item_id, *, state=None, **_kw:
                                      base_fit if (item_id, state) == ("jacket", "closed") else None)
        garment_store.clear_failure_on_body = lambda c, item_id, fsig, body: CLEARED.append((item_id, fsig, body))
        garments.body_sha256 = lambda *_a, **_kw: "bodysha"
        garments.cached_failure = lambda *_a, **_kw: None
        garments.run_estimate = lambda *_a, **_kw: {"hub_jobs": 0, "steps": [], "note": ""}

        def body_fit(_c, item_id, *, body_id, **_kw):
            if (item_id, body_id) in BODY_FITS:
                return {"fit": root / f"{item_id}_{body_id}.glb", "pending": False, "error": ""}
            return {"fit": None, "pending": False, "error": "refused — stub"}

        garments.body_fit = body_fit
        garment_refit.work_count = lambda *_a, **_kw: 0
        garment_refit.tracked = lambda c, fn: REFITS.append(c) or {}
        model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "rig"]
        model3d.find_model3d = (lambda _c, sig=None, **_kw:
                                MODEL["path"] if sig is not None and sig == MODEL["sig"] else None)
        model3d.find_model3d_serving = lambda *_a, **_kw: (SERVED["path"], "nearest" if SERVED["path"] else "")
        model3d._read_sidecar = lambda _p: copy.deepcopy(MODEL["meta"] or {})
        figure_build._read_profile = lambda _c: profile()
        figure_build.start = lambda c, **kw: STARTS.append((c, kw)) or {"status": "started"}

        def delivered():
            figure.invalidate()
            return figure._delivered("Demo", profile=profile())

        wanted, _ = delivered()
        sb = wanted.shape
        model_refs.current_outfit_state = lambda _c: (dict(W), [], wanted.signature)
        STORED.add(sb)
        check("wanted: shape of {blouse} (meshed), the jacket own", (figure.is_plain(sb), wanted.in_body, wanted.own),
              (False, ("blouse",), ("jacket",)))

        print("[1] nothing shown: the refused jacket joins the body (as before A23)")
        _w, got = delivered()
        check("interim body with the jacket", (got.shape != sb, got.in_body, got.in_body_own, got.fit_refused),
              (True, ("blouse", "jacket"), ("jacket",), {}))

        print("[2] the model of W shown: it stays the delivered figure")
        BODY_FITS.add(("jacket", sb))
        _w, built = delivered()
        check("F: on SB, the jacket grafted", (built.shape, built.own, built.in_body), (sb, ("jacket",), ("blouse",)))
        BODY_FITS.discard(("jacket", sb))
        MODEL.update(sig=wanted.signature, path=root / "model.glb", meta={"figure": built.as_dict()})
        SERVED["path"] = root / "model.glb"
        _w, got = delivered()
        check("delivered = F, kept, the refusal named", (got.as_dict() == built.as_dict(), got.kept,
                                                         got.fit_refused, got.interim),
              (True, True, {"jacket": "refused — stub"}, {}))
        auto = [s.name for s in figure_build._runnable(figure_build.plan("Demo", profile=profile(), explicit=False),
                                                       False)]
        check("automatic plan: no fits, no assemble", ("fits" in auto, "assemble" in auto), (False, False))
        manual = [(s.name, s.label, s.jobs) for s in figure_build.plan("Demo", profile=profile(), explicit=True)]
        check("manual plan: the re-fit, then the assembly",
              [m for m in manual if m[0] in ("fits", "assemble")],
              [("fits", "Re-fit on the body shape (refused before): Jacket", 0),
               ("assemble", "Assemble the figure", 0)])
        check("assemble refuses to publish", figure_build._run_assemble("Demo", None),
              "Not assembled: the fit of Jacket on the body shape is refused — the figure built before stays served")
        wanted_now, got = delivered()
        rows = figure_build._worn_rows("Demo", wanted_now, got, {}, False, profile())
        check("worn row", [(r["item_id"], r["state"], r.get("fit_refused")) for r in rows if r["item_id"] == "jacket"],
              [("jacket", "fit_refused", "refused — stub")])
        try:
            figure_build.refit("Demo", "blouse")
            check("refit(blouse) refused", "no error", "ValueError")
        except ValueError:
            check("refit(blouse) refused", "ValueError", "ValueError")
        CLEARED.clear()
        STARTS.clear()
        figure_build.refit("Demo", "jacket")
        check("refit(jacket): refusal cleared, automatic Build started",
              (CLEARED, STARTS), ([("jacket", FSIG, sb)], [("Demo", {"reason": "refit", "automatic": True})]))
        check("DEPENDS: assemble needs the fits", "fits" in figure_build.DEPENDS["assemble"], True)
        CLEARED.clear()
        REFITS.clear()
        check("manual fits, refused again", figure_build._run_fits("Demo", None, True),
              "Fit refused — Jacket: refused — stub; the figure built before stays served")
        check("refused again: cleared once, no CPU refits", (CLEARED, REFITS), ([("jacket", FSIG, sb)], []))
        BODY_FITS.add(("jacket", sb))
        check("manual fits, accepted", figure_build._run_fits("Demo", None, True), "")
        _w, got = delivered()
        check("accepted: the CPU refits ran, nothing refused", (REFITS, got.own, got.fit_refused),
              (["Demo"], ("jacket",), {}))
        BODY_FITS.discard(("jacket", sb))

        print("[3] another outfit's model shown: the jacket left out, never an interim")
        MODEL.update(sig="another", path=root / "other.glb", meta={})
        SERVED["path"] = root / "other.glb"
        wanted_now, got = delivered()
        check("left out on SB", (got.shape, got.own, got.left_out, got.fit_refused, got.kept, got.interim),
              (sb, (), {"jacket": "Fit refused — refused — stub"}, {"jacket": "refused — stub"}, False, {}))
        rows = figure_build._worn_rows("Demo", wanted_now, got, {}, False, profile())
        check("worn row", [r["state"] for r in rows if r["item_id"] == "jacket"], ["fit_refused"])

        print(f"[4] fails on the old code ({BASELINE})")
        old_fig = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/figure.py"],
                                 capture_output=True, text=True).stdout
        old_build = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/figure_build.py"],
                                   capture_output=True, text=True).stdout
        check(f"{BASELINE}: no FIT_REFUSED", (bool(old_fig), "FIT_REFUSED" in old_fig), (True, False))
        check(f"{BASELINE}: assemble needed only the plain body", '"assemble": {"plain_body"}}' in old_build, True)

    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
