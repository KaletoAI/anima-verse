#!/usr/bin/env python3
"""The delivered figure with the interim rule (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 6; spec
``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md``,
builder-check rulings 2 and 7): ``figure.wanted_figure``,
``figure.delivered_figure``, ``figure.pending_changes``,
``figure.built_figure`` and the refusal branch behind ``PAINT_ON_SHAPE``.

Usage:
    ./.venv/bin/python scripts/smoke_figure_delivered.py

Runs against a THROWAWAY storage + instance directory — no real world, no
hub, no GPU, no server. Nothing is written to a world DB.

Stubs (tables; the resolver itself is real): ``inventory.get_item`` /
``motion_item_cache.item_snapshot`` serve the items below;
``base_body.is_base_pipeline`` -> True; ``base_body.base_signature`` ->
BSIG; ``base_body.base_model_sha256`` -> "basesha"; ``base_body.dress_text``
-> ``"wear:" + "+".join(sorted visible ids)`` (visible = worn ids minus
``mesh_items``, "" when none is left); ``side_views_dressed`` False,
``dressed_views`` ("front", "back"); ``figure.stored_shape`` -> a sidecar for
the keys in STORED, else None; ``garment_store.accepted_fit`` -> a fit for the
items in BASE_FITS; ``garments.body_fit`` -> ``{"fit": <path>}`` for the
(item, shape) pairs in BODY_FITS, else ``{"fit": None, "pending": False,
"error": "refused — stub"}``; ``garments.cached_failure`` -> None;
``base_body.stored_base_haired`` -> HAIRED; ``base_body.prompts_current`` ->
CURRENT; ``model_refs.find_ref_image`` -> a path for the base front of BSIG.

Fixture: "Demo", BSIG = "base0123abcd", variant "rigged". Items
(outfit_piece): coat [outer] in_body, blouse [top] painted, trousers
[bottom] own_mesh (clothing), boots [feet] own_mesh (footwear); the hair item
"hair_demo" (garment kind hair, owner Demo). Worn W = {outer: coat, top:
blouse, bottom: trousers}; W+ = W + {feet: boots}.

Keys by hand (canonical JSON = sort_keys, separators ",", ":"; h8 / h12 =
first 8 / 12 hex of sha256 — the rules of ``scripts/smoke_figure_keys.py``):
  S  = shape of {coat}            = "ob" + h8({version 2, base_signature
       BSIG, base_variant rigged, hair_in_body True, side_views False,
       dress_text {front/back: "wear:coat"}})             = "ob82e8f156"
  S2 = shape of {blouse, coat}    = same with "wear:blouse+coat" = "oba82e1f92"
  T(S, blouse)            = "tex" + h12({version 1, shape S, base_variant
       rigged, dress_text {front/back: "wear:blouse"}})   = "texe57feda37703"
  T(S, blouse+trousers)   = same with "wear:blouse+trousers" = "tex72b75ed8d6e3"
  T(plain, blouse+coat)   = today's tsig: "tex" + h12({version 1,
       base_signature BSIG, base_variant rigged, side_views False,
       dress_text {front/back: "wear:blouse+coat"}})     = "tex06c6eeeaa12a"

Expected, derived by hand from the brief's delivered rule:

[1] All built: S stored, trousers fit on S (base fit + body fit), hair body,
    base haired -> delivered == wanted: shape S, texture T(S, blouse) =
    "texe57feda37703", in_body (coat,), painted (blouse,), own (trousers,),
    no interim, no left_out, hair "body".
[2] S not stored -> shape BSIG, painted (blouse, coat), interim {coat:
    "Shown painted until its body shape is built"}, own (trousers,) (its base
    fit is the fit on the plain body), texture T(plain, blouse+coat) =
    "tex06c6eeeaa12a".
[3] S stored, trousers WITHOUT a fit on S (base fit yes, body fit refused):
    branch True -> painted (blouse, trousers), interim {trousers: "Shown
    painted until its own mesh is built"}, own (), texture "tex72b75ed8d6e3".
    Branch False (S2 stored too) -> wanted and delivered shape S2 =
    shape_key(in_body (blouse, coat)) = "oba82e1f92", in_body (blouse, coat),
    notes {blouse: "In the body here: painting needs the plain body"},
    trousers in left_out (reason "refused — stub"), painted (), texture "".
[4] Review Focus 3: W+, boots own_mesh with NO fit at all (no base fit), S
    and S2 stored, trousers fitted on both -> boots in left_out {boots: "no accepted
    fit on the current base model"} and in neither painted nor in_body, in
    both branches; branch True texture stays T(S, blouse) (boots left out of
    the dress text as before).
[5] Review Focus 2: worn {top: blouse}, hair_method hairdeck, hair_demo worn,
    no HairDeck fit; base haired -> hair "body"; base bald -> "bald".
    With the plain body's prompts older (CURRENT False) pending_changes ==
    [{key body, name "Plain body", wanted "built", delivered OLDER_PROMPTS},
     {key hair, name "Hair", wanted "hairdeck", delivered "body"}].
[6] [1]'s state: a model sidecar {"figure": delivered.as_dict()} ->
    built_figure == delivered; pending_changes == []; built_figure({}) is
    None. Blouse switched painted -> own_mesh (no fit, nothing built) ->
    pending_changes == [{key "blouse", name "Blouse", wanted "own_mesh",
    delivered "painted"}].
[7] Fails on the old code: the per-character outfit body mode is gone —
    ``git show bcba4ce3:app/core/base_body.py`` (BASE of the task) holds
    exactly one ``def outfit_body_mode``; the file now holds none, and
    ``base_body`` has no ``outfit_body_mode`` / ``MESH_MODE`` /
    ``RETEXTURE_MODE`` / ``mesh_items_off_rule`` any more.
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
S, S2 = "ob82e8f156", "oba82e1f92"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def _item(item_id, slots, mode):
    return {"id": item_id, "name": item_id.title(), "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode}}


ITEMS = {"coat": _item("coat", ["outer"], "in_body"),
         "blouse": _item("blouse", ["top"], "painted"),
         "trousers": _item("trousers", ["bottom"], "own_mesh"),
         "boots": _item("boots", ["feet"], "own_mesh"),
         "hair_demo": {"id": "hair_demo", "name": "Hair", "category": "garment", "owner": "Demo",
                       "garment": {"kind": "hair"}}}
W = {"outer": "coat", "top": "blouse", "bottom": "trousers"}
STORED = set()
BASE_FITS = set()
BODY_FITS = set()
HAIRED = {"value": True}
CURRENT = {"value": True}


def set_mode(item_id, mode):
    ITEMS[item_id]["outfit_piece"]["mesh_mode"] = mode


def profile(pieces=None, method="body", hair=None):
    return {"model_pipeline": "base_body", "hair_method": method,
            "equipped_pieces": dict(W if pieces is None else pieces),
            "equipped_mesh_pieces": {"hair": hair} if hair else {}, "equipped_items": []}


def stub_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=()):
    meshed = {str(i) for i in mesh_items or ()}
    visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
    return ("wear:" + "+".join(visible)) if visible else ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-delivered-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")

        from app.core import base_body, figure, garment_store, garments, model_refs, motion_item_cache
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
        base_body.stored_base_haired = lambda *_a, **_kw: HAIRED["value"]
        base_body.prompts_current = lambda *_a, **_kw: CURRENT["value"]
        figure.stored_shape = lambda _c, key, **_kw: {"outfit_body": {"body_id": key}} if key in STORED else None
        garment_store.accepted_fit = (lambda _c, item_id, **_kw:
                                      (root / f"{item_id}.glb", {"accepted": True}) if item_id in BASE_FITS else None)
        garments.body_sha256 = lambda *_a, **_kw: "bodysha"
        garments.cached_failure = lambda *_a, **_kw: None

        def body_fit(_c, item_id, *, body_id, **_kw):
            if (item_id, body_id) in BODY_FITS:
                return {"fit": root / f"{item_id}_{body_id}.glb", "pending": False, "error": ""}
            return {"fit": None, "pending": False, "error": "refused — stub"}

        garments.body_fit = body_fit
        real_find = model_refs.find_ref_image
        model_refs.find_ref_image = (lambda c, kind, signature=None:
                                     root / "front.png" if (kind, signature) == ("tpose", BSIG)
                                     else real_find(c, kind, signature))

        def both(p):
            return figure.wanted_figure("Demo", profile=p), figure.delivered_figure("Demo", profile=p)

        print("[1] all built: delivered == wanted")
        STORED.update({S})
        BASE_FITS.update({"trousers"})
        BODY_FITS.update({("trousers", S)})
        wanted, got = both(profile())
        check("delivered == wanted", got, wanted)
        check("shape", got.shape, S)
        check("texture", got.texture, "texe57feda37703")
        check("in_body / painted / own", (got.in_body, got.painted, got.own), (("coat",), ("blouse",), ("trousers",)))
        check("no interim / left_out / notes", (got.interim, got.left_out, got.notes), ({}, {}, {}))
        check("hair", got.hair, "body")
        check("bsig", got.bsig, BSIG)
        check("signature is the mesh-input signature", got.signature, model_refs.mesh_signature(
            W, [], "Demo", model_refs.mesh_variant("Demo", W, profile()),
            model_refs.mesh_items_token("Demo", W, profile())))

        print("[2] the shape is not stored: painted meanwhile")
        STORED.clear()
        got = figure.delivered_figure("Demo", profile=profile())
        check("shape = plain body", got.shape, BSIG)
        check("painted", got.painted, ("blouse", "coat"))
        check("in_body", got.in_body, ())
        check("interim", got.interim, {"coat": "Shown painted until its body shape is built"})
        check("own (base fit on the plain body)", got.own, ("trousers",))
        check("texture = today's tsig", got.texture, "tex06c6eeeaa12a")
        check("the wanted shape is still S", figure.wanted_figure("Demo", profile=profile()).shape, S)

        print("[3] trousers without a fit on S")
        STORED.update({S, S2})
        BODY_FITS.discard(("trousers", S))
        got = figure.delivered_figure("Demo", profile=profile())
        check("True: shape", got.shape, S)
        check("True: painted", got.painted, ("blouse", "trousers"))
        check("True: interim", got.interim, {"trousers": "Shown painted until its own mesh is built"})
        check("True: own", got.own, ())
        check("True: left_out", got.left_out, {})
        check("True: texture", got.texture, "tex72b75ed8d6e3")
        figure.PAINT_ON_SHAPE = False
        try:
            wanted, got = both(profile())
            check("False: wanted shape", wanted.shape, S2)
            check("False: delivered shape", got.shape, S2)
            check("False: shape_key(in_body (blouse, coat))", got.shape, figure.shape_key(
                "Demo", figure.WornSets(in_body=("blouse", "coat"), painted=(), own={"trousers": "clothing"},
                                        hair_in_body=True, hair_item="", pieces=dict(W)),
                bsig=BSIG, variant="rigged", profile=profile()))
            check("False: in_body", got.in_body, ("blouse", "coat"))
            check("False: notes", got.notes, {"blouse": "In the body here: painting needs the plain body"})
            check("False: trousers left out", got.left_out, {"trousers": "refused — stub"})
            check("False: painted", got.painted, ())
            check("False: texture", got.texture, "")
        finally:
            figure.PAINT_ON_SHAPE = True

        print("[4] footwear pending on a meshed shape (Review Focus 3)")
        BODY_FITS.update({("trousers", S), ("trousers", S2)})
        plus = {**W, "feet": "boots"}
        for flag in (True, False):
            figure.PAINT_ON_SHAPE = flag
            try:
                got = figure.delivered_figure("Demo", profile=profile(plus))
            finally:
                figure.PAINT_ON_SHAPE = True
            check(f"{flag}: boots left out", got.left_out, {"boots": "no accepted fit on the current base model"})
            check(f"{flag}: boots not painted", "boots" in got.painted, False)
            check(f"{flag}: boots not in the body", "boots" in got.in_body, False)
            check(f"{flag}: boots not grafted", "boots" in got.own, False)
            if flag:
                check("True: shape", got.shape, S)
                check("True: texture unchanged", got.texture, "texe57feda37703")
            else:
                check("False: shape", got.shape, S2)

        print("[5] HairDeck without a fit (Review Focus 2)")
        hairdeck = profile({"top": "blouse"}, method="hairdeck", hair="hair_demo")
        wanted, got = both(hairdeck)
        check("wanted hair", wanted.hair, "hairdeck")
        check("haired plain body -> body", got.hair, "body")
        HAIRED["value"] = False
        check("bald plain body -> bald", figure.delivered_figure("Demo", profile=hairdeck).hair, "bald")
        HAIRED["value"] = True
        CURRENT["value"] = False
        check("pending_changes", figure.pending_changes("Demo", profile=hairdeck),
              [{"key": "body", "name": "Plain body", "wanted": "built", "delivered": base_body.OLDER_PROMPTS},
               {"key": "hair", "name": "Hair", "wanted": "hairdeck", "delivered": "body"}])
        CURRENT["value"] = True

        print("[6] pending_changes")
        got = figure.delivered_figure("Demo", profile=profile())
        meta = {"figure": got.as_dict()}
        check("built_figure round trip", figure.built_figure(meta), got)
        check("built_figure without a record", figure.built_figure({}), None)
        check("every mode delivered -> []", figure.pending_changes("Demo", profile=profile()), [])
        set_mode("blouse", "own_mesh")
        check("blouse painted -> own_mesh", figure.pending_changes("Demo", profile=profile()),
              [{"key": "blouse", "name": "Blouse", "wanted": "own_mesh", "delivered": "painted"}])
        check("the model's figure is not the delivered one now",
              figure.built_figure(meta) == figure.delivered_figure("Demo", profile=profile()), False)
        set_mode("blouse", "painted")

        print("[7] the outfit body mode is gone")
        import subprocess
        old = subprocess.run(["git", "show", "bcba4ce3:app/core/base_body.py"], cwd=ROOT, capture_output=True,
                             text=True).stdout
        check("BASE has outfit_body_mode", old.count("def outfit_body_mode"), 1)
        check("now none", (ROOT / "app/core/base_body.py").read_text(encoding="utf-8").count("def outfit_body_mode"),
              0)
        check("no mode names left", [n for n in ("outfit_body_mode", "MESH_MODE", "RETEXTURE_MODE",
                                                 "mesh_items_off_rule") if hasattr(base_body, n)], [])

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
