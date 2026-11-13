#!/usr/bin/env python3
"""Task 11g-fix3 of the unified worn pieces (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``; ledger ruling
A15): an interim body shape (A11) only for an own-mesh piece whose mesh
needs HUB work, and none at all while the character has a figure to show.

Why: Kai's base body was refreshed (new bsig). The automatic Build that
followed meshed an INTERIM shape with all five worn pieces in the body
(t-shirt and underwear in_body, jacket / jeans / sneakers own_mesh without a
fit on the new base) — front + back renders, a mesh and a rig on the hub —
although the three garment meshes existed and their fits were CPU refits
accepted seconds later.

Usage:
    ./.venv/bin/python scripts/smoke_interim_refit_only.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no
GPU, no server. The resolver (``figure._delivered``, ``predicted_keys``) and
the Build's plan / runners (``figure_build``) are real; the rest are tables.

Stubs: ``inventory.get_item`` / ``motion_item_cache.item_snapshot`` serve the
items below; ``base_body.is_base_pipeline`` True, ``base_signature`` BSIG,
``base_model_sha256`` "newsha" (the refreshed base model), ``dress_text`` ->
``"wear:" + "+".join(sorted visible ids)`` (visible = worn minus
``mesh_items``; "" when none is left), ``side_views_dressed`` False,
``dressed_views`` ("front", "back") (``dressed_view_jobs()`` = 2),
``shape_view_jobs`` 2, ``shape_view_shas`` {}, ``stored_base_haired`` True,
``prompts_current`` True, ``base_refresh_plan`` {} (the refreshed plain body
is current), ``dressed_image`` -> a view only for the (shape, grafted
pieces) keys in VIEWS, ``dressed_view_estimate`` 3; ``figure.stored_shape``
-> a sidecar for the keys in STORED; ``garment_store.accepted_fit`` -> a
fit for the (item, state) pairs in FITS (none: no fit on the new base);
``garments.body_fit`` -> a fit for the (item, shape) pairs in BODY_FITS, else
refused; ``garments.cached_failure`` None; ``garments.run_estimate`` -> EST[item];
``garment_refit.work_count`` 0; ``model3d.mesh_hub_stages`` ["mesh",
"rig"]; ``model3d.find_model3d`` None (no outfit model on the NEW base —
Kai's model was built on the old one); ``model3d.find_model3d_serving`` ->
the old outfit model ("stale") while SERVED, else (None, "").

Fixture "Demo" (hair in the body): t-shirt [top] and underwear [underwear]
in_body; jacket [outer] and jeans [legs] own_mesh (clothing); sneakers
[feet] own_mesh (footwear). Estimates as the real ``run_estimate`` gives
them after a base refresh: a clothing piece whose last accepted source
exists -> ``{hub_jobs 0, steps [worn, ghost, cutout, mesh, fit], refit
True}`` (refit from the previous base, CPU); footwear (item steps cached
under its ssig) -> ``{hub_jobs 0, steps [fit]}``; a piece WITHOUT a garment
mesh -> ``{hub_jobs 6, steps [worn, ghost, cutout, mesh, fit]}`` (worn 2 +
ghost 2 + mesh 1 + … as ``garments.HUB_JOBS``, here the stub's 6).

Expected, derived by hand from ruling A15:

[1] Rebased (no fit on "newsha"), every garment mesh present, the old
    figure served. A15 a: no own-mesh piece needs hub work, so none is in
    the body: delivered own = (jacket, jeans, sneakers), in_body_own (),
    no ``INTERIM_IN_BODY`` anywhere. The wanted shape of {t-shirt,
    underwear} is not stored, so the delivered figure paints them meanwhile
    (rule 1) — never built (Ruling C4). The plan: NO interim step; the
    wanted shape "Body shape: views 2 + mesh + rig" = 2 + 2 = 4, not manual
    (no interim shape holds a piece: nothing to take out); "Own mesh ·
    Jacket" 0, "Own mesh · Jeans" 0, "Own mesh · Sneakers" 0 (the refits /
    the fit step); "Fits on the CPU" 0; "Assemble the figure" 0 — total 4
    (before A15: an interim shape of all five, 2 + 2 = 4 more jobs, plus its
    outfit model). The automatic plan is the same (nothing manual). Without
    a served figure the plan is the same too (A15 a alone decides).
    ``predicted_keys`` = the wanted shape (no interim key).
[1b] The same with the wanted shape STORED (and the delivered figure's views
    in VIEWS): delivered = the wanted shape with all three grafted — a
    piece waiting for its CPU fit is not refused on the stored shape (it has
    no base fit to judge there yet). Plan: the three pieces (0), fits (0),
    assemble (0) — total 0.
[2] As [1], but the jacket has NO garment mesh (6 hub jobs), the old figure
    served. A15 b: no interim shape. The delivered figure names the jacket
    ``INTERIM_IN_BODY`` (what it is waiting for), but the plan has NO
    interim step and no views for it; the wanted shape 4, not manual (the
    jacket is in no built shape); pieces Jacket 6, Jeans 0, Sneakers 0;
    fits 0; assemble 0 — total 10, automatic the same 10. Run now (the
    jacket's chain failed or still out): ``_run_texture`` renders nothing,
    ``_run_assemble`` = ``INTERIM_WAITS`` and builds no outfit model — the
    old figure stays served. Once the jacket's fit lands (FITS (jacket,
    closed), BODY_FITS (jacket, wanted shape)) and the wanted shape is
    stored, the assembly runs (ensure views, outfit model, the assembly; "").
[3] No figure served at all, the jacket without a mesh: the interim is
    planned as before (A11 / A14): "Interim body shape (own mesh in the body
    until ready): views 2 + mesh + rig" = 4 (nothing painted: no texture
    views); the wanted shape 4 with manual TAKE_OUT; Jacket 6; Jeans 0;
    Sneakers 0; fits; assemble — explicit 14, automatic 4 + 6 = 10. The
    interim's in-body set = (jacket, t-shirt, underwear): the jeans and the
    sneakers (CPU only) stay own meshes (A15 a).
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
BSIG = "base0123abcd"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def _item(item_id, slots, mode, **extra):
    return {"id": item_id, "name": item_id.title(), "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode, **extra}}


ITEMS = {"tshirt": _item("tshirt", ["top"], "in_body"),
         "underwear": _item("underwear", ["underwear"], "in_body"),
         "jacket": _item("jacket", ["outer"], "own_mesh", closable=True),
         "jeans": _item("jeans", ["legs"], "own_mesh"),
         "sneakers": _item("sneakers", ["feet"], "own_mesh")}
W = {"top": "tshirt", "underwear": "underwear", "outer": "jacket", "legs": "jeans", "feet": "sneakers"}
REFIT = {"hub_jobs": 0, "steps": ["worn", "ghost", "cutout", "mesh", "fit"], "refit": True,
         "note": "refit from the previous base; up to 5 if the refit is refused"}
FIT_ONLY = {"hub_jobs": 0, "steps": ["fit"], "refit": False, "note": "no hub job"}
CHAIN = {"hub_jobs": 6, "steps": ["worn", "ghost", "cutout", "mesh", "fit"], "refit": False, "note": "stub"}
EST = {}
STORED, FITS, VIEWS, BODY_FITS = set(), set(), set(), set()
SERVED = {"on": True}
CALLS = []


def profile():
    return {"model_pipeline": "base_body", "hair_method": "body", "equipped_pieces": dict(W),
            "equipped_mesh_pieces": {}, "equipped_items": []}


def stub_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=(), **_kw):
    meshed = {str(i) for i in mesh_items or ()}
    visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
    return ("wear:" + "+".join(visible)) if visible else ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="interim-refit-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")

        from app.core import (base_body, figure, figure_build, garment_assembly, garment_refit, garment_store,
                              garments, model3d, model_refs, motion_item_cache)
        from app.models import inventory
        inventory.get_item = lambda item_id, **_kw: copy.deepcopy(ITEMS.get(str(item_id)))
        motion_item_cache.item_snapshot = lambda **_kw: copy.deepcopy(ITEMS)
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.base_signature = lambda *_a, **_kw: BSIG
        base_body.base_model_sha256 = lambda *_a, **_kw: "newsha"
        base_body.dress_text = stub_dress_text
        base_body.side_views_dressed = lambda: False
        base_body.dressed_views = lambda: ("front", "back")
        base_body.shape_view_jobs = lambda *_a, **_kw: 2
        base_body.shape_view_shas = lambda *_a, **_kw: {}
        base_body.shape_view = lambda *_a, **_kw: None
        base_body.stored_base_haired = lambda *_a, **_kw: True
        base_body.prompts_current = lambda *_a, **_kw: True
        base_body.base_refresh_plan = lambda *_a, **_kw: {}

        def dressed_image(_c, _view, _sig, _bsig, *, fig=None):
            key = (fig.shape, tuple(sorted({*fig.own, *fig.left_out}))) if fig is not None else None
            return root / "view.png" if key in VIEWS else None

        base_body.dressed_image = dressed_image
        base_body.dressed_view_estimate = lambda *_a, **_kw: 3
        figure.stored_shape = lambda _c, key, **_kw: {"outfit_body": {"body_id": key}} if key in STORED else None

        def accepted_fit(_c, item_id, *, state=None, **_kw):
            return (root / f"{item_id}_{state}.glb", {"accepted": True}) if (item_id, state) in FITS else None

        garment_store.accepted_fit = accepted_fit
        garments.body_sha256 = lambda *_a, **_kw: "bodysha"

        def body_fit(_c, item_id, *, body_id, **_kw):
            if (item_id, body_id) in BODY_FITS:
                return {"fit": root / f"{item_id}_{body_id}.glb", "pending": False, "error": ""}
            return {"fit": None, "pending": False, "error": "refused — stub"}

        garments.body_fit = body_fit
        garments.cached_failure = lambda *_a, **_kw: None
        garments.run_estimate = lambda _c, item_id, **_kw: copy.deepcopy(EST[item_id])
        garment_refit.work_count = lambda *_a, **_kw: 0
        model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "rig"]
        model3d.find_model3d = lambda *_a, **_kw: None
        model3d.find_model3d_serving = lambda _c: ((root / "old.glb", "stale") if SERVED["on"] else (None, ""))
        real_find = model_refs.find_ref_image
        model_refs.find_ref_image = (lambda c, kind, signature=None:
                                     root / "front.png" if (kind, signature) == ("tpose", BSIG)
                                     else real_find(c, kind, signature))
        figure_build._read_profile = lambda _c: profile()
        figure_build._dressed = lambda c, w: CALLS.append("views") or ""
        figure_build._outfit_model = lambda c, sig: CALLS.append("outfit_model") or ""
        base_body.ensure_figure_views = lambda *_a, **_kw: CALLS.append("ensure_views") or None
        garment_assembly.schedule = lambda *_a, **_kw: CALLS.append("assembly")

        def steps_of(plan):
            return [(s.name, s.label, s.jobs, s.manual) for s in plan]

        def total(plan, explicit=True):
            return sum(int(s.jobs or 0) for s in figure_build._runnable(plan, explicit))

        def interim_texts(fig):
            return sorted(i for i, text in fig.interim.items() if text == figure.INTERIM_IN_BODY)

        shape_label = "Body shape: views 2 + mesh + rig"
        tail = [("fits", "Fits on the CPU", 0, ""), ("assemble", "Assemble the figure", 0, "")]

        print("[1] rebased, garment meshes present, no fit on the new base, the old figure served")
        EST.update(jacket=REFIT, jeans=REFIT, sneakers=FIT_ONLY)
        SERVED["on"] = True
        wanted, got = figure._delivered("Demo", profile=profile())
        check("wanted: t-shirt + underwear in the body, three own", (wanted.in_body, wanted.own),
              (("tshirt", "underwear"), ("jacket", "jeans", "sneakers")))
        check("A15 a: all three stay own meshes, none in the body",
              (got.own, got.in_body_own, interim_texts(got)), (("jacket", "jeans", "sneakers"), (), []))
        check("the wanted shape is not stored: painted meanwhile, never built (C4)",
              (got.shape, figure_build._painted_interim(got)), (BSIG, True))
        plan = figure_build.plan("Demo", profile=profile())
        want_plan = [("shape", shape_label, 4, ""), ("pieces", "Own mesh · Jacket", 0, ""),
                     ("pieces", "Own mesh · Jeans", 0, ""), ("pieces", "Own mesh · Sneakers", 0, "")] + tail
        check("plan: no interim, the pieces + fits cover the refits", steps_of(plan), want_plan)
        check("explicit total 4", figure_build.cost("Demo", plan)["hub_jobs"], 4)
        auto = figure_build.plan("Demo", profile=profile(), explicit=False)
        check("automatic: the same, 4", (steps_of(figure_build._runnable(auto, False)), total(auto, False)),
              (want_plan, 4))
        SERVED["on"] = False
        check("no figure served: the same plan (A15 a alone)", steps_of(figure_build.plan("Demo", profile=profile())),
              want_plan)
        SERVED["on"] = True
        check("predicted_keys: the wanted shape, no interim key",
              figure.predicted_keys("Demo", W, [], bsig=BSIG, profile=profile())[0], wanted.shape)

        print("[1b] the same with the wanted shape stored: refit pieces are not refused on it")
        STORED.add(wanted.shape)
        VIEWS.add((wanted.shape, ("jacket", "jeans", "sneakers")))
        _w, got = figure._delivered("Demo", profile=profile())
        check("delivered = the wanted shape, all three grafted",
              (got.shape, got.in_body, got.own, got.interim), (wanted.shape, ("tshirt", "underwear"),
                                                               ("jacket", "jeans", "sneakers"), {}))
        plan = figure_build.plan("Demo", profile=profile())
        check("plan: pieces 0 + fits + assemble, total 0",
              (steps_of(plan), figure_build.cost("Demo", plan)["hub_jobs"]),
              ([("pieces", "Own mesh · Jacket", 0, ""), ("pieces", "Own mesh · Jeans", 0, ""),
                ("pieces", "Own mesh · Sneakers", 0, "")] + tail, 0))
        STORED.clear()
        VIEWS.clear()

        print("[2] the jacket without a garment mesh, the old figure served: no interim shape")
        EST["jacket"] = CHAIN
        wanted, got = figure._delivered("Demo", profile=profile())
        check("the jacket waits for hub work, the others stay own",
              (interim_texts(got), got.own), (["jacket"], ("jeans", "sneakers")))
        check("its interim shape is not stored", figure._shape_stored("Demo", got.shape, BSIG), False)
        plan = figure_build.plan("Demo", profile=profile())
        want_plan = [("shape", shape_label, 4, ""), ("pieces", "Own mesh · Jacket", 6, ""),
                     ("pieces", "Own mesh · Jeans", 0, ""), ("pieces", "Own mesh · Sneakers", 0, "")] + tail
        check("plan: no interim, no views for it, the wanted shape no take-out", steps_of(plan), want_plan)
        check("explicit total 10", figure_build.cost("Demo", plan)["hub_jobs"], 10)
        auto = figure_build.plan("Demo", profile=profile(), explicit=False)
        check("automatic: the same, 10", (steps_of(figure_build._runnable(auto, False)), total(auto, False)),
              (want_plan, 10))
        CALLS.clear()
        texture = figure_build._run_texture("Demo", figure_build.Step("texture", "Texture", 0))
        assemble = figure_build._run_assemble("Demo", figure_build.Step("assemble", "Assemble the figure", 0))
        check("while it waits: no views, not assembled, the old figure stays",
              (texture, assemble, CALLS), ("", figure_build.INTERIM_WAITS, []))
        FITS.add(("jacket", "closed"))
        STORED.add(wanted.shape)
        BODY_FITS.add(("jacket", wanted.shape))
        CALLS.clear()
        assemble = figure_build._run_assemble("Demo", figure_build.Step("assemble", "Assemble the figure", 0))
        check("the jacket's mesh landed: assembled", (assemble, CALLS),
              ("", ["ensure_views", "outfit_model", "assembly"]))
        FITS.clear()
        STORED.clear()
        BODY_FITS.clear()

        print("[3] nothing to show, the jacket without a mesh: the interim as before")
        SERVED["on"] = False
        _w, got = figure._delivered("Demo", profile=profile())
        check("interim set: jacket + the in-body pieces; jeans / sneakers own",
              (got.in_body, got.in_body_own, got.own), (("jacket", "tshirt", "underwear"), ("jacket",),
                                                        ("jeans", "sneakers")))
        plan = figure_build.plan("Demo", profile=profile())
        interim = figure_build.INTERIM_SHAPE_LABEL.format(parts="views 2 + mesh + rig")
        check("plan: interim first, the shape a take-out",
              steps_of(plan),
              [("interim", interim, 4, ""), ("shape", shape_label, 4, figure.TAKE_OUT),
               ("pieces", "Own mesh · Jacket", 6, ""), ("pieces", "Own mesh · Jeans", 0, ""),
               ("pieces", "Own mesh · Sneakers", 0, "")] + tail)
        check("explicit 14, automatic 10",
              (figure_build.cost("Demo", plan)["hub_jobs"],
               total(figure_build.plan("Demo", profile=profile(), explicit=False), False)), (14, 10))

    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
