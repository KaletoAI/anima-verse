#!/usr/bin/env python3
"""Task 11c-2 of the unified worn pieces (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``; ledger rulings
A11 and A14): an own-mesh piece whose mesh is not delivered is IN THE BODY
SHAPE meanwhile — never painted, never left out — and the Build's interim
never waits for the garment chains.

Usage:
    ./.venv/bin/python scripts/smoke_figure_a11.py

Ruling A15 (Task 11g-fix3) narrows the interim: only a piece whose mesh
needs HUB work (``figure._needs_hub``), and only while no figure is served
(``figure_build._interim_waits``). Every expectation below still holds as
written: the ``run_estimate`` stub's 6 jobs ARE hub work, a refused chain is
too, and no outfit model is served here (``find_model3d_serving`` finds no
model in the throwaway storage). The refit-only and served-figure cases are
``scripts/smoke_interim_refit_only.py``.

Runs against a THROWAWAY storage + instance directory — no world, no hub, no
GPU, no server. The resolver (``figure``), the plan (``figure_build.plan``)
and ``base_body.resolve_figure`` / ``mesh_record`` are real; the rest are
tables.

Stubs: ``inventory.get_item`` / ``motion_item_cache.item_snapshot`` serve the
items below; ``base_body.is_base_pipeline`` -> True, ``base_signature`` ->
BSIG, ``base_model_sha256`` -> "basesha", ``dress_text`` -> ``"wear:" +
"+".join(sorted visible ids)`` (visible = worn ids minus ``mesh_items``, ""
when none is left), ``side_views_dressed`` False, ``dressed_views`` ("front",
"back") so ``dressed_view_jobs()`` = 1 + 1 = 2 (the back's draft; its composite is CPU since Task 11g), ``shape_view_shas`` {},
``shape_view`` None (no shape view stored), ``stored_base_haired`` True,
``prompts_current`` True, ``base_refresh_plan`` {} (the plain body is
current), ``dressed_image`` -> a view only for the (shape, grafted pieces)
pairs in VIEWS (a view made for that figure),
``dressed_view_estimate`` 3; ``figure.stored_shape`` -> a sidecar for the keys
in STORED; ``garment_store.accepted_fit`` -> a fit for the (item, state) pairs
in FITS; ``garments.body_fit`` -> a fit for the (item, shape) pairs in
BODY_FITS; ``garments.body_sha256`` "bodysha"; ``garments.cached_failure`` ->
FAILURES[item]; ``garments.run_estimate`` -> 6 hub jobs (3 steps) while the
item has no closed fit, else 0 / no step; ``garments.run_queued`` RECORDS its
calls; ``garment_refit.work_count`` 0; ``model3d.mesh_hub_stages`` ["mesh",
"rig"]; ``model3d.find_model3d`` / ``_read_sidecar`` -> the outfit model
MODEL (None = no model).

Fixture: "Demo", hair in the body (method ``body``), BSIG = "base0123abcd",
variant "rigged" (no package declares an exposed-only rig). Items
(outfit_piece): blouse [top] painted; jacket [outer] own_mesh, closable
(clothing); boots [feet] own_mesh (footwear). Worn W = {top: blouse, outer:
jacket}; W+ = W + {feet: boots}.

Keys by hand (canonical JSON = sort_keys, separators ",", ":"; h8 / h12 =
first 8 / 12 hex of sha256 — the rules of ``scripts/smoke_figure_keys.py``):
  S1 = shape of {jacket} = "ob" + h8({version 2, base_signature BSIG,
       base_variant rigged, hair_in_body True, side_views False, dress_text
       {front/back: "wear:jacket"}})                       = "ob2292185e"
  S4 = shape of {boots, jacket}, dress text "wear:boots+jacket" = "obb794dd8d"
  T1 = "tex" + h12({version 1, shape S1, base_variant rigged, dress_text
       {front/back: "wear:blouse"}}) — own + in-body pieces left out
                                                           = "texbc61d4fe0991"
  T4 = the same on S4                                      = "tex9db397339375"
  TP = the plain body's tsig: "tex" + h12({version 1, base_signature BSIG,
       base_variant rigged, side_views False, dress_text {front/back:
       "wear:blouse"}}) (the jacket grafted, left out)     = "texf4d3f232056c"

Expected, derived by hand from rulings A11 / A14:

[1] W, the jacket WITHOUT any fit (its chain not run): wanted shape BSIG (no
    in-body mode), own (jacket,). Delivered: shape S1 (the jacket in the
    shape key — not stored yet: the previously delivered figure stays served
    until it is), in_body (jacket,), in_body_own (jacket,), painted
    (blouse,), own (), left_out {}, interim {jacket: "In the body until its
    own mesh is ready"}, texture T1. ``figure_texts`` of the delivered
    figure (the interim views' dress text) = {front/back:
    "wear:blouse+jacket"} — the jacket stays in the views.
    ``resolve_figure(Demo, W)``: NO ``run_queued`` call; record ``in_body``
    [jacket], ``unpainted`` [], ``intended`` [], warning "Jacket is in the
    body until its own mesh is ready: no accepted fit on the current base
    model". ``pending_changes`` = [{key jacket, name Jacket, wanted
    own_mesh, delivered in_body, note INTERIM_IN_BODY}].
    Plan (no model stored): interim "Interim body shape (own mesh in the body
    until ready): views 2 + mesh + rig + texture views 2" = 2 + 2 + 2 = 6;
    pieces "Own mesh · Jacket" 6; texture "Texture: views 3" 3 (the stubbed
    estimate) with manual TAKE_OUT; fits 0; assemble 0 — explicit total 15;
    the automatic run leaves the texture out (12). The interim step comes before the pieces
    step and ``DEPENDS['interim']`` = {plain_body}: it never waits for the
    chain. ``_run_interim``: ``prepare_shape`` of the DELIVERED figure (shape
    S1), then the views, then the outfit model; ``run_queued`` never called.
    The worn rows (by slot: outer, top): jacket state "interim",
    in_body_until "mesh"; blouse "ready".
[2] The jacket's CLOSED fit accepted after [1]'s interim was built (S1
    stored, its views in VIEWS (S1, ()), BODY_FITS (jacket, S1), MODEL =
    {figure: [1]'s delivered, mesh_items: [1]'s record}):
    delivered KEEPS S1 — in_body (jacket,), in_body_own (jacket,), notes
    {jacket: "Own mesh ready — in the body shape until the next Build"},
    interim {}, texture T1 (unchanged: no view re-renders). The record of
    [1]'s interim views makes the assembly graft the jacket
    (``effective_mesh_items`` = [jacket]). Automatic plan: runnable steps
    [assemble 0] — 0 hub jobs; the explicit plan also lists texture (3,
    TAKE_OUT). Inside ``taking_out(Demo)`` (a manual Build): shape BSIG, own
    (jacket,), in_body (), texture TP; outside it the shape is kept again.
    The jacket's worn row: state "pending", in_body_until "build".
[3] F13 b: W with the jacket worn OPEN, only its CLOSED fit, no model: own
    (jacket,), shown_closed (jacket,), notes {jacket: SHOWN_CLOSED},
    in_body (), in_body_own (), shape BSIG, interim {}.
[4] W+, the jacket's chain REFUSED (``cached_failure`` {step mesh, error
    "refused — stub"}, no fit) and the boots without a fit: delivered shape
    S4, in_body (boots, jacket), in_body_own (boots, jacket), painted
    (blouse,), left_out {}, interim INTERIM_IN_BODY for both, texture T4;
    the jacket's record warning names "mesh — refused — stub — Regenerate in
    the Wardrobe"; the plan lists "Own mesh · Jacket — failed — Retry" (0).
[6] A manual Build taking a KEPT piece out: the blouse switched to in_body,
    the jacket without a fit -> delivered on the interim shape SBJ of
    {blouse, jacket} (in_body_own (jacket,)); SBJ stored and the outfit
    model recorded on it (MODEL = that figure + its mesh record); the
    jacket's closed fit accepted (and on SBJ) -> delivered KEEPS SBJ:
    interim {}, notes {jacket: READY_IN_BODY}; the wanted shape (the blouse
    alone) is another key, not stored. The explicit plan opens with the
    shape step marked TAKE_OUT and has no interim step. Inside
    ``taking_out(Demo)``: the delivered figure is the plain body with the
    blouse painted meanwhile (rule 1, interim non-empty) — still the plan
    has NO interim step (the stored SBJ model keeps serving until the new
    shape is built; painting the plain body first would be wasted jobs) and
    the shape step is not manual. The blouse back to painted afterwards.
[5] Fails on the old code (explicit hash 0e5a7adf, the BASE of the task):
    there ``base_body.resolve_figure`` ran ``garments.run_queued(character_name,
    grafted)`` before the dressed front, and ``figure._delivered`` painted an
    own-mesh piece without its fit (``WHAT_OWN_MESH``); no
    ``INTERIM_IN_BODY`` existed. Now neither does.
"""
import copy
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASELINE = "0e5a7adf"
FAILS = []
BSIG = "base0123abcd"
S1, S4 = "ob2292185e", "obb794dd8d"
T1, T4, TP = "texbc61d4fe0991", "tex9db397339375", "texf4d3f232056c"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def _item(item_id, slots, mode, **extra):
    return {"id": item_id, "name": item_id.title(), "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode, **extra}}


ITEMS = {"blouse": _item("blouse", ["top"], "painted"),
         "jacket": _item("jacket", ["outer"], "own_mesh", closable=True),
         "boots": _item("boots", ["feet"], "own_mesh")}
W = {"top": "blouse", "outer": "jacket"}
STORED, FITS, BODY_FITS, VIEWS = set(), set(), set(), set()
FAILURES = {}
MODEL = {"meta": None}
RUNS = []


def profile(pieces=None):
    return {"model_pipeline": "base_body", "hair_method": "body", "equipped_pieces": dict(W if pieces is None
                                                                                          else pieces),
            "equipped_mesh_pieces": {}, "equipped_items": []}


def stub_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=(), **_kw):
    meshed = {str(i) for i in mesh_items or ()}
    visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
    return ("wear:" + "+".join(visible)) if visible else ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-a11-") as tmp:
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
        base_body.base_model_sha256 = lambda *_a, **_kw: "basesha"
        base_body.dress_text = stub_dress_text
        base_body.side_views_dressed = lambda: False
        base_body.dressed_views = lambda: ("front", "back")
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
        garments.cached_failure = lambda _c, item_id, **_kw: FAILURES.get(item_id)

        def body_fit(_c, item_id, *, body_id, **_kw):
            if (item_id, body_id) in BODY_FITS:
                return {"fit": root / f"{item_id}_{body_id}.glb", "pending": False, "error": ""}
            return {"fit": None, "pending": False, "error": "refused — stub"}

        garments.body_fit = body_fit

        def run_estimate(_c, item_id, **_kw):
            if (item_id, "closed") in FITS:
                return {"hub_jobs": 0, "steps": [], "note": ""}
            return {"hub_jobs": 6, "steps": ["worn", "ghost", "mesh"], "note": ""}

        garments.run_estimate = run_estimate

        def run_queued(character_name, item_ids, **kw):
            RUNS.append(("run_queued", list(item_ids)))
            return {i: {"ok": True} for i in item_ids}

        garments.run_queued = run_queued
        garment_refit.work_count = lambda *_a, **_kw: 0
        model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "rig"]
        model3d.find_model3d = lambda *_a, **_kw: (root / "model.glb") if MODEL["meta"] is not None else None
        model3d._read_sidecar = lambda _p: copy.deepcopy(MODEL["meta"] or {})
        real_find = model_refs.find_ref_image
        model_refs.find_ref_image = (lambda c, kind, signature=None:
                                     root / "front.png" if (kind, signature) == ("tpose", BSIG)
                                     else real_find(c, kind, signature))

        def both(p, **kw):
            return figure._delivered("Demo", profile=p, **kw)

        def steps_of(plan):
            return [(s.name, s.label, s.jobs, s.manual) for s in plan]

        print("[1] the jacket without a mesh is in the body shape")
        wanted, got = both(profile())
        check("wanted: plain, jacket own", (wanted.shape, wanted.own, wanted.in_body), (BSIG, ("jacket",), ()))
        check("shape S1 (jacket in the shape key)", got.shape, S1)
        check("S1 is the shape of {jacket}", figure.shape_key_of(figure.shape_plan(
            "Demo", got, [], profile=profile())[2]), S1)
        check("in_body / in_body_own / painted / own", (got.in_body, got.in_body_own, got.painted, got.own),
              (("jacket",), ("jacket",), ("blouse",), ()))
        check("never painted, never left out", ("jacket" in got.painted, got.left_out), (False, {}))
        check("interim", got.interim, {"jacket": figure.INTERIM_IN_BODY})
        check("texture T1", got.texture, T1)
        check("interim views keep the jacket", base_body.figure_texts("Demo", got, [], profile=profile()),
              {"front": "wear:blouse+jacket", "back": "wear:blouse+jacket"})
        RUNS.clear()
        fig, record = base_body.resolve_figure("Demo", W, profile=profile())
        check("resolve_figure runs no chain", RUNS, [])
        check("record", {k: record.get(k) for k in ("in_body", "unpainted", "intended", "warnings")},
              {"in_body": ["jacket"], "unpainted": [], "intended": [],
               "warnings": ["Jacket is in the body until its own mesh is ready: "
                            "no accepted fit on the current base model"]})
        check("pending change", figure._pending("Demo", wanted, got, profile()),
              [{"key": "jacket", "name": "Jacket", "wanted": "own_mesh", "delivered": "in_body",
                "note": figure.INTERIM_IN_BODY}])
        plan = figure_build.plan("Demo", profile=profile())
        label = figure_build.INTERIM_SHAPE_LABEL.format(parts="views 2 + mesh + rig + texture views 2")
        check("plan", steps_of(plan),
              [("interim", label, 6, ""), ("pieces", "Own mesh · Jacket", 6, ""),
               ("texture", "Texture: views 3", 3, figure.TAKE_OUT), ("fits", "Fits on the CPU", 0, ""),
               ("assemble", "Assemble the figure", 0, "")])
        check("explicit cost 15", figure_build.cost("Demo", plan)["hub_jobs"], 15)
        auto = figure_build._runnable(figure_build.plan("Demo", profile=profile(), explicit=False), False)
        check("automatic: no take-out, 12", ([s.name for s in auto], sum(s.jobs for s in auto)),
              (["interim", "pieces", "fits", "assemble"], 12))
        check("interim before pieces, needs only the plain body",
              ([s.name for s in plan].index("interim") < [s.name for s in plan].index("pieces"),
               figure_build.DEPENDS["interim"]), (True, {"plain_body"}))
        calls = []
        figure_build._read_profile = lambda _c: profile()
        base_body.prepare_shape = lambda c, f, **kw: calls.append(("prepare_shape", f.shape)) or {"ok": True}
        figure_build._dressed = lambda c, w: calls.append(("views",))
        figure_build._outfit_model = lambda c, sig: calls.append(("outfit_model",)) or ""
        RUNS.clear()
        check("interim runs", figure_build._run_interim("Demo", plan[0]), "")
        check("interim order: shape S1, views, model — no chain",
              (calls, RUNS), ([("prepare_shape", S1), ("views",), ("outfit_model",)], []))
        rows = figure_build._worn_rows("Demo", wanted, got, {}, False, profile())
        check("worn row", [(r["item_id"], r["state"], r["in_body_until"]) for r in rows],
              [("jacket", "interim", "mesh"), ("blouse", "ready", None)])
        interim_record = record

        print("[2] the mesh accepted: served as its own mesh, the shape kept, nothing automatic")
        STORED.add(S1)
        VIEWS.add((S1, ()))   # the interim's views, made for S1 with nothing grafted
        FITS.add(("jacket", "closed"))
        BODY_FITS.add(("jacket", S1))
        MODEL["meta"] = {"figure": got.as_dict(), "mesh_items": interim_record}
        wanted, kept = both(profile())
        check("kept shape S1", (kept.shape, kept.in_body, kept.in_body_own, kept.own),
              (S1, ("jacket",), ("jacket",), ()))
        check("notes / interim", (kept.notes, kept.interim), ({"jacket": figure.READY_IN_BODY}, {}))
        check("texture unchanged (no re-render)", kept.texture, T1)
        check("the assembly grafts it", garment_assembly.effective_mesh_items(MODEL["meta"]), ["jacket"])
        auto = figure_build._runnable(figure_build.plan("Demo", profile=profile(), explicit=False), False)
        check("automatic: assemble only, 0 jobs", [(s.name, s.jobs) for s in auto], [("assemble", 0)])
        check("explicit lists the take-out", steps_of(figure_build.plan("Demo", profile=profile())),
              [("texture", "Texture: views 3", 3, figure.TAKE_OUT), ("assemble", "Assemble the figure", 0, "")])
        with figure.taking_out("Demo"):
            _w, out = both(profile())
        check("manual Build takes it out", (out.shape, out.own, out.in_body, out.in_body_own, out.texture),
              (BSIG, ("jacket",), (), (), TP))
        _w, again = both(profile())
        check("kept again after the Build's scope", again.shape, S1)
        rows = figure_build._worn_rows("Demo", wanted, kept, {}, False, profile())
        check("worn row", [(r["item_id"], r["state"], r["in_body_until"]) for r in rows],
              [("jacket", "pending", "build"), ("blouse", "ready", None)])

        print("[3] F13 b: worn open, only the closed mesh -> the closed mesh stands in")
        MODEL["meta"] = None
        STORED.clear()
        BODY_FITS.clear()
        _w, got = both(profile(), piece_state={"jacket": "open"})
        check("own, shown closed", (got.own, got.shown_closed, got.notes.get("jacket")),
              (("jacket",), ("jacket",), figure.SHOWN_CLOSED))
        check("not in the body", (got.shape, got.in_body, got.in_body_own, got.interim), (BSIG, (), (), {}))

        print("[4] a refused own mesh (and footwear without a fit) stays in the body")
        FITS.clear()
        FAILURES["jacket"] = {"step": "mesh", "error": "refused — stub"}
        wp = {**W, "feet": "boots"}
        wanted, got = both(profile(wp))
        check("shape S4", got.shape, S4)
        check("both in the body", (got.in_body, got.in_body_own, got.painted, got.left_out),
              (("boots", "jacket"), ("boots", "jacket"), ("blouse",), {}))
        check("interim", got.interim, {"boots": figure.INTERIM_IN_BODY, "jacket": figure.INTERIM_IN_BODY})
        check("texture T4", got.texture, T4)
        warnings = base_body.mesh_record("Demo", got)["warnings"]
        check("the refusal is named", warnings[1],
              "Jacket is in the body until its own mesh is ready: mesh — refused — stub — Regenerate in the Wardrobe")
        pieces = [(s.label, s.jobs) for s in figure_build.plan("Demo", profile=profile(wp)) if s.name == "pieces"]
        check("plan: failed — Retry", ("Own mesh · Jacket — failed — Retry", 0) in pieces, True)

        print("[6] a manual Build that takes a kept piece out: the kept shape serves, no interim figure")
        FAILURES.clear()
        FITS.clear()
        STORED.clear()
        BODY_FITS.clear()
        VIEWS.clear()
        ITEMS["blouse"]["outfit_piece"]["mesh_mode"] = "in_body"
        _w, first = both(profile())
        check("the jacket pending: interim shape SBJ of {blouse, jacket}", (first.in_body, first.in_body_own),
              (("blouse", "jacket"), ("jacket",)))
        sbj = first.shape
        STORED.add(sbj)
        MODEL["meta"] = {"figure": first.as_dict(), "mesh_items": base_body.mesh_record("Demo", first)}
        FITS.add(("jacket", "closed"))
        BODY_FITS.add(("jacket", sbj))
        wanted, kept = both(profile())
        check("kept SBJ, nothing interim", (kept.shape, kept.interim, kept.notes),
              (sbj, {}, {"jacket": figure.READY_IN_BODY}))
        check("the wanted shape (blouse alone) is another, not stored", (wanted.shape != sbj,
                                                                          figure._shape_stored("Demo", wanted.shape,
                                                                                               BSIG)), (True, False))
        names = [(s.name, s.manual) for s in figure_build.plan("Demo", profile=profile())]
        check("explicit plan: the shape takes the jacket out, no interim", (names[0], "interim" in dict(names)),
              (("shape", figure.TAKE_OUT), False))
        with figure.taking_out("Demo"):
            _w, out = both(profile())
            inside = [(s.name, s.manual) for s in figure_build.plan("Demo", profile=profile())]
        check("taking out: plain body meanwhile (blouse painted, rule 1)", (out.shape, out.interim != {}),
              (BSIG, True))
        check("taking out: the plan builds the shape, no interim of the plain body (SBJ keeps serving)",
              (inside[0], "interim" in dict(inside)), (("shape", ""), False))
        ITEMS["blouse"]["outfit_piece"]["mesh_mode"] = "painted"
        MODEL["meta"] = None

        print(f"[5] fails on the old code ({BASELINE})")
        old_body = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/base_body.py"],
                                  capture_output=True, text=True).stdout
        old_fig = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/figure.py"],
                                 capture_output=True, text=True).stdout
        check(f"{BASELINE}: the dressed front ran the chains first",
              "results = garments.run_queued(character_name, grafted)" in old_body, True)
        check(f"{BASELINE}: own mesh painted meanwhile, no in-body interim",
              ("what=WHAT_OPEN_MESH if state == OPEN else WHAT_OWN_MESH" in old_fig, "INTERIM_IN_BODY" in old_fig),
              (True, False))
        now_body = (ROOT / "app/core/base_body.py").read_text(encoding="utf-8")
        check("now: no chain in resolve_figure", "garments.run_queued" in now_body, False)

    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
