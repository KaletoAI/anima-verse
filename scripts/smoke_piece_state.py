#!/usr/bin/env python3
"""Open / closed pieces (plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 11a; spec
``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md`` Addendum A; rulings A1–A8): the item flag
``outfit_piece.closable``, the worn state ``equipped_options.piece_state``, the state words in the texts, the
outfit signature, the figure keys, the cache GC, the piece-state route, (Task 11b, ruling A8) the coverage of
an open piece and (ruling A9) the closed words in the text an LLM reads.

Usage:
    ./.venv/bin/python scripts/smoke_piece_state.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real
world, no hub, no GPU, no server. Stubs: ``base_body.is_base_pipeline`` -> True, ``base_body.side_views_dressed``
-> False, ``base_body.dressed_views`` -> ("front",) (only in [5]/[7]), ``model_refs.schedule_outfit_render`` and
``sync_topics.changed_at`` -> no-ops, ``figure.served_figure`` (in [7]) -> a built figure of the fixture.

Fixture (real ``add_item``; ids below are the generated ids, written as names): jacket ``{slots: [outer], covers:
[top]}`` fragment "black jacket"; blouse ``{slots: [top]}`` "white blouse"; boots ``{slots: [feet]}`` "brown
boots"; tee ``{slots: [top]}`` "grey tee" (held, not worn). Character "Demo" holds all four and wears
``{outer: jacket, top: blouse}``.

Expected, derived by hand from the brief and rulings A1 (closed changes no key), A6 (neutral words) and A7 (Task
11b: closed says NOTHING — no ", worn closed" anywhere; a closed or untoggled piece reads byte for byte as before
the option; was: "black jacket, worn closed" in 2D / chat text):

[0] Fails on the old code: ``git show 1b60c54b:app/core/garment_set.py`` has no ``def default_closable`` (BASE of
    this task), so step [1] fails there.
[1] Item flag. default_closable(["outer"]) True, (["top"]) False, (["feet"]) False. add_item jacket -> stored
    closable True (kind default, outer); blouse with closable True -> True; boots with closable True -> False
    (D-A3: footwear never). update_item(blouse, {outfit_piece: {slots: [top]}}) keeps True (not named = kept).
    A stored item without the key reads its kind default: closable_of({category outfit_piece, slots [outer]})
    True, slots [top] False; a non-outfit item False. update_item(blouse, closable False) calls neither
    _notify_outfit_changed nor _invalidate_renders_for_item (an item property spends nothing).
[2] State. piece_states({equipped_pieces: {outer: jacket, top: blouse}, equipped_options: {piece_state: {jacket:
    open, boots: open, tee: open}}}) == {jacket: open} (boots not closable, tee not worn). set_piece_state(Demo,
    jacket, open) -> stored {jacket: open}, piece_state_of open; (jacket, closed) -> stored map without jacket;
    (boots, open) -> ValueError "not closable"; (tee, open) -> ValueError "not worn now" (tee made closable for
    that case); (jacket, "ajar") -> ValueError. equip_piece(Demo, jacket) after an open state -> entry gone.
[3] Texts (A7). piece_text(jacket, open) == "black jacket, worn open"; (closed) == "black jacket" (the fragment
    alone); the blouse (closable False) is "white blouse" in both states. render_outfit(pieces={outer: jacket,
    top: blouse})["pieces"]: closed -> "black jacket" with mesh_input and without (the blouse is covered; the
    BASE renderer, which had no state at all, gave the same); open -> "white blouse underneath black jacket, worn
    open" with mesh_input and without (D-A4: the open jacket's covers count as partially_covers, the outer slot's
    own fragment is suppressed).
[4] Signature (D-A1). _equipped_signature({outer: jacket, top: blouse}, []) closed == "outer=jacket" == the BASE
    function's output (its source from ``git show 1b60c54b:app/core/expression_regen.py`` run in a namespace);
    open == "outer=jacket|top=blouse|open:jacket"; outfit_signature = md5[:12] of those strings.
[5] Keys (real dress_text). Jacket in_body, blouse painted, worn {outer: jacket, top: blouse}: closed shape_key ==
    the shape_key with piece_state={} passed AND with the base_body.dress_text of BASE — i.e. shape_inputs
    dress_text front "they now wear black jacket" (nothing new); open -> "they now wear black jacket, worn open"
    (the painted blouse is left out before covers resolve) and another key. Jacket painted: open and closed ->
    the same shape_key (plain = bsig), different texture_key; closed texture_key ==
    base_body.texture_signature(texture_inputs(...)) over the closed profile (Task 4's tsig).
[6] Saved sets. add_character_outfit(Demo, {pieces: [jacket, blouse], options: {boot_hem: tucked, piece_state:
    {jacket: open}}}) stores options {boot_hem: tucked, piece_state: {jacket: open}}; applying it -> profile
    piece_state {jacket: open}, boot_hem tucked. A set saved without options while the jacket is open stores
    piece_state {jacket: open}. A set whose options lack piece_state applies {} (all closed).
[7] Figure. worn_sets(...).open == (jacket,) when open, () when closed. pending_changes with the jacket open and a
    served figure wearing the jacket with open == () names {key: "jacket:state", name: "Jacket", wanted: "open",
    delivered: "closed"}; closed -> no state entry.
[8] GC. A manifest {pieces {outer: jacket, top: blouse}, items [], piece_state {jacket: open}} re-signs to the open
    signature -> _entry_valid True; with the jacket's closable False -> False; a sidecar without piece_state
    (closed render) -> read_manifest piece_state {} and _entry_valid True for the closed signature
    (md5 of the BASE string "outer=jacket").
[9] Route. Admin POST /characters/Demo/outfit-options/piece-state {item_id: jacket, state: open} -> 200, body
    piece_state {jacket: open}, closable [{jacket, Jacket, open, names_state False}],
    _notify_outfit_changed called once with (Demo, "piece_state", action "open", item_ids [jacket]); boots -> 400
    "not closable"; a player of another character -> 403. The chat line render_outfit(character_name=Demo)["full"]
    contains "worn open". GET adds piece_state + closable.
[10] Coverage (ruling A8, ``outfit_renderer.covering_pieces``). Character "Bare" wears {outer: jacket, bottom:
    trousers} (trousers {slots: [bottom]} "blue trousers", not closable), nothing on top or feet.
    Jacket closed: covering_pieces == both pieces; the bare-slot summary (thought_context) is "barefoot" — the
    jacket's covers [top] count, so the upper body is covered; a body slot covered_by [top, outer] is NOT
    exposed. Jacket open: covering_pieces == {bottom: trousers}; the summary is "topless under an open layer,
    barefoot" (the open jacket covers neither outer nor top); the [top, outer] body slot IS exposed; a slot
    covered_by [bottom] stays covered either way. The decency hint reads the same summary ("You are currently
    topless under an open layer, barefoot. …" — checked through _bare_slots_summary, its only coverage input).
[11] LLM text (ruling A9: every worn closable piece names its state where an LLM reads the outfit; image and mesh
    texts keep A7). Demo wears {outer: jacket, top: blouse}, jacket CLOSED (set explicitly; the blouse is not
    closable since [1], the jacket is by kind default).
    piece_text(jacket, closed, for_llm) == "black jacket, worn closed"; (closed) == "black jacket"; (open,
    for_llm) == "black jacket, worn open" == (open). Blouse, both states, for_llm: "white blouse".
    state_words: jacket closed for_llm "worn closed", closed "" ; blouse closed for_llm "".
    render_outfit(pieces={outer: jacket, top: blouse}, piece_state {})["pieces"]: for_llm "black jacket, worn
    closed" (blouse covered), image "black jacket"; jacket open: both "white blouse underneath black jacket, worn
    open". A coat {slots: [outer], partially_covers: [top]} "long coat" (closable by kind) over the blouse, closed:
    for_llm "white blouse underneath long coat, worn closed", image "white blouse underneath long coat".
    LLM call sites, real functions (Demo dressed, nothing in hand, no equipped_items):
      thought_context._build_outfit_block(Demo, "Your outfit") starts "Your outfit: black jacket, worn closed";
      act_engine._subject_outfit_text(Demo) == "wearing: black jacket, worn closed" (the "full" text: no fallback
      parts, no items); act_engine._build_present_people_block([Demo]) == "- Demo — wearing: black jacket, worn
      closed"; person_description(Demo, include_outfit, include_exposed False, no state modifiers, for_llm) ends
      "wearing: black jacket, worn closed", the same call without for_llm ends "wearing: black jacket";
      thought_context.present_people_details([(Demo, Demo)]) contains "black jacket, worn closed".
      OutfitChangeSkill.decision_menu(Demo) == ["Blouse (top, worn)", "Boots (feet)", "Jacket (outer, worn
      closed)", "Tee (top)"] (sorted by name; the blouse is worn but not closable); jacket open -> "Jacket (outer,
      worn open)".
      OutfitCreationSkill existing_block (render_task stubbed to capture it) holds "- [outer] [EQUIPPED, worn
      closed] Jacket: black jacket" and "- [top] [EQUIPPED] Blouse: white blouse" — the state in the marker, the
      fragment untouched.
    Call-site scan (AST): every render_outfit call in app/routes/chat.py, app/routes/story.py,
    app/core/act_engine.py and app/core/thought_context.py passes for_llm=True; no render_outfit /
    person_description call in the image / mesh files (prompt_builder, scene_render, scene_photo,
    imagegen/service, model_refs, expression_regen, base_body, character_ops, routes/play) passes for_llm=True.
"""
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "1b60c54b"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def raises(label, fn, needle):
    try:
        fn()
    except ValueError as e:
        check(label, needle in str(e), True)
        return
    check(label, "no ValueError", f"ValueError containing {needle!r}")


def base_function(path: str, name: str):
    """``name`` from ``path`` at BASE, executed alone in a namespace (only its own body, its imports are lazy)."""
    src = subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {}
    exec("from typing import *\n" + ast.get_source_segment(src, node), ns)
    return ns[name]


def md5_12(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def main() -> int:
    print("[0] fails on the old code")
    old = subprocess.run(["git", "show", f"{BASE}:app/core/garment_set.py"], cwd=ROOT, capture_output=True,
                         text=True).stdout
    check(f"no default_closable at {BASE}", "def default_closable" in old, False)

    with tempfile.TemporaryDirectory(prefix="piece-state-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()

        from app.core import base_body, garment_set, model_refs, outfit_options as oo, sync_topics
        from app.core import outfit_renderer
        from app.models import inventory
        from app.models.character import (add_character_outfit, get_character_outfits, get_character_profile,
                                          save_character_profile)
        model_refs.schedule_outfit_render = lambda *a, **k: None
        sync_topics.changed_at = lambda *a, **k: None

        # --- [1] the item flag -------------------------------------------------------------------------------
        print("[1] item flag")
        try:
            check("default_closable outer", garment_set.default_closable(["outer"]), True)
        except AttributeError as e:
            check("garment_set.default_closable", str(e), "exists")
            print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
            return 1
        check("default_closable top", garment_set.default_closable(["top"]), False)
        check("default_closable feet", garment_set.default_closable(["feet"]), False)

        def piece(name, slots, frag, **op):
            return inventory.add_item(name, category="outfit_piece", prompt_fragment=frag,
                                      outfit_piece={"slots": slots, **op})["id"]
        jacket = piece("Jacket", ["outer"], "black jacket", covers=["top"])
        blouse = piece("Blouse", ["top"], "white blouse", closable=True)
        boots = piece("Boots", ["feet"], "brown boots", closable=True)
        tee = piece("Tee", ["top"], "grey tee")
        stored = lambda iid: (inventory.get_item(iid).get("outfit_piece") or {}).get("closable")  # noqa: E731
        check("jacket stored closable (kind default)", stored(jacket), True)
        check("blouse stored closable True", stored(blouse), True)
        check("boots closable True -> False (footwear)", stored(boots), False)
        check("tee stored closable False", stored(tee), False)
        inventory.update_item(blouse, {"outfit_piece": {"slots": ["top"]}})
        check("update without closable keeps True", stored(blouse), True)
        check("closable_of no key, outer", garment_set.closable_of(
            {"category": "outfit_piece", "outfit_piece": {"slots": ["outer"]}}), True)
        check("closable_of no key, top", garment_set.closable_of(
            {"category": "outfit_piece", "outfit_piece": {"slots": ["top"]}}), False)
        check("closable_of a tool", garment_set.closable_of({"category": "tool"}), False)
        calls = []
        real_notify, real_inval = inventory._notify_outfit_changed, inventory._invalidate_renders_for_item
        inventory._notify_outfit_changed = lambda *a, **k: calls.append(("notify", a))
        inventory._invalidate_renders_for_item = lambda *a, **k: calls.append(("invalidate", a))
        inventory.update_item(blouse, {"outfit_piece": {"slots": ["top"], "closable": False}})
        inventory._notify_outfit_changed, inventory._invalidate_renders_for_item = real_notify, real_inval
        check("closable change spends nothing", calls, [])
        check("blouse now False", stored(blouse), False)

        # --- [2] the state -----------------------------------------------------------------------------------
        print("[2] state")
        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female"},
                                                     create_new=True), True)
        for iid in (jacket, blouse, boots, tee):
            inventory.add_to_inventory("Demo", iid)
        worn = {"outer": jacket, "top": blouse}
        prof = get_character_profile("Demo")
        prof["equipped_pieces"] = dict(worn)
        check("wear jacket + blouse", save_character_profile("Demo", prof), True)
        check("piece_states filters", oo.piece_states(
            {"equipped_pieces": worn, "equipped_options": {"piece_state": {jacket: "open", boots: "open",
                                                                           tee: "open"}}}), {jacket: "open"})
        stored_map = lambda: (get_character_profile("Demo").get("equipped_options") or {}).get("piece_state")  # noqa: E731
        check("set open", oo.set_piece_state("Demo", jacket, "open"), True)
        check("stored {jacket: open}", stored_map(), {jacket: "open"})
        check("piece_state_of open", oo.piece_state_of(get_character_profile("Demo"), jacket), "open")
        oo.set_piece_state("Demo", jacket, "closed")
        check("closed pops the key", stored_map(), {})
        raises("boots not closable", lambda: oo.set_piece_state("Demo", boots, "open"), "not closable")
        inventory.update_item(tee, {"outfit_piece": {"slots": ["top"], "closable": True}})
        raises("tee not worn now", lambda: oo.set_piece_state("Demo", tee, "open"), "not worn now")
        raises("bad state", lambda: oo.set_piece_state("Demo", jacket, "ajar"), "state must be one of")
        oo.set_piece_state("Demo", jacket, "open")
        res = inventory.equip_piece("Demo", jacket, source="smoke")
        check("re-equip ok", res.get("status"), "ok")
        check("equip_piece closes the piece", stored_map(), {})

        # --- [3] texts ---------------------------------------------------------------------------------------
        print("[3] texts")
        J, B = inventory.get_item(jacket), inventory.get_item(blouse)
        check("open", outfit_renderer.piece_text(J, "open"), "black jacket, worn open")
        check("closed says nothing (A7)", outfit_renderer.piece_text(J, "closed"), "black jacket")
        for st in ("open", "closed"):
            check(f"blouse {st}", outfit_renderer.piece_text(B, st), "white blouse")
        ro = lambda state, mi=True: outfit_renderer.render_outfit(  # noqa: E731
            profile={}, equipped_pieces=dict(worn), equipped_items=[], mesh_input=mi, piece_state=state)["pieces"]
        check("closed mesh render", ro({}), "black jacket")
        check("open mesh render", ro({jacket: "open"}), "white blouse underneath black jacket, worn open")
        check("closed 2D render (A7)", ro({}, False), "black jacket")
        check("open 2D render", ro({jacket: "open"}, False), "white blouse underneath black jacket, worn open")
        # A9 brought CLOSED_WORDS back for the LLM text only; the image / mesh texts above stay A7.
        check("closed words are LLM-only (A9)", getattr(oo, "CLOSED_WORDS", None), "worn closed")

        # --- [4] signature -----------------------------------------------------------------------------------
        print("[4] signature")
        from app.core.expression_regen import _equipped_signature
        base_sig = base_function("app/core/expression_regen.py", "_equipped_signature")
        closed_raw = _equipped_signature(dict(worn), [])
        check("closed raw", closed_raw, f"outer={jacket}")
        check("closed raw == BASE", closed_raw, base_sig(dict(worn), []))
        open_raw = _equipped_signature(dict(worn), [], {jacket: "open"})
        check("open raw", open_raw, f"outer={jacket}|top={blouse}|open:{jacket}")
        check("outfit_signature closed", model_refs.outfit_signature(dict(worn), [], "Demo"), md5_12(closed_raw))
        check("outfit_signature open", model_refs.outfit_signature(dict(worn), [], "Demo",
                                                                   piece_state={jacket: "open"}), md5_12(open_raw))

        # --- [5] keys ----------------------------------------------------------------------------------------
        print("[5] keys")
        from app.core import figure
        base_body.is_base_pipeline = lambda *a, **k: True
        base_body.side_views_dressed = lambda: False
        base_body.dressed_views = lambda: ("front",)
        BSIG = "base0123abcd"
        inventory.update_item(jacket, {"outfit_piece": {"slots": ["outer"], "covers": ["top"],
                                                        "mesh_mode": "in_body"}})
        inventory.update_item(blouse, {"outfit_piece": {"slots": ["top"], "mesh_mode": "painted"}})
        prof = get_character_profile("Demo")
        prof["hair_method"] = "body"

        def keys(state):
            p = oo.with_piece_state(prof, state)
            sets = figure.worn_sets("Demo", profile=p)
            shape = figure.shape_key("Demo", sets, bsig=BSIG, variant="rigged", profile=p)
            texts = figure.shape_inputs("Demo", sets, bsig=BSIG, variant="rigged", profile=p)["dress_text"]
            texture = figure.texture_key("Demo", sets, shape=shape, bsig=BSIG, variant="rigged", items=[],
                                         profile=p)
            return sets, shape, texts, texture
        _s, shape_c, texts_c, _t = keys({})
        check("closed shape text", texts_c, {"front": "they now wear black jacket"})
        sets_none = figure.worn_sets("Demo", profile={k: v for k, v in prof.items() if k != "equipped_options"})
        check("closed shape == no piece_state at all", shape_c,
              figure.shape_key("Demo", sets_none, bsig=BSIG, variant="rigged",
                               profile={k: v for k, v in prof.items() if k != "equipped_options"}))
        _s, shape_o, texts_o, _t = keys({jacket: "open"})
        check("open shape text", texts_o, {"front": "they now wear black jacket, worn open"})
        check("open shape key differs", shape_o != shape_c, True)
        inventory.update_item(jacket, {"outfit_piece": {"slots": ["outer"], "covers": ["top"],
                                                        "mesh_mode": "painted"}})
        sc, shape_pc, _x, tex_c = keys({})
        so, shape_po, _x, tex_o = keys({jacket: "open"})
        check("painted: same shape (plain)", (shape_pc, shape_po), (BSIG, BSIG))
        check("painted: texture differs", tex_c != tex_o, True)
        closed_prof = oo.with_piece_state(prof, {})
        check("closed texture == Task 4 tsig", tex_c, base_body.texture_signature(base_body.texture_inputs(
            "Demo", pieces=dict(worn), items=[], variant="rigged", mesh_effective=[], bsig=BSIG,
            profile=closed_prof)))
        check("painted open tsig text", base_body.texture_inputs(
            "Demo", pieces=dict(worn), items=[], variant="rigged", bsig=BSIG,
            profile=oo.with_piece_state(prof, {jacket: "open"}))["dress_text"],
            {"front": "they now wear white blouse underneath black jacket, worn open"})

        # --- [6] saved sets ----------------------------------------------------------------------------------
        print("[6] saved sets")
        from app.routes.inventory import _apply_outfit_set_route_sync
        oid = add_character_outfit("Demo", {"name": "Open", "pieces": [jacket, blouse],
                                            "options": {"boot_hem": "tucked", "piece_state": {jacket: "open"}}})
        saved = next(o for o in get_character_outfits("Demo") if o["id"] == oid)
        check("stored options", saved.get("options"), {"boot_hem": "tucked", "piece_state": {jacket: "open"}})
        oo.set_piece_state("Demo", jacket, "closed")
        _apply_outfit_set_route_sync("Demo", {"outfit_id": oid})
        opts = get_character_profile("Demo").get("equipped_options") or {}
        check("applied piece_state", opts.get("piece_state"), {jacket: "open"})
        check("applied boot_hem", opts.get("boot_hem"), "tucked")
        oid2 = add_character_outfit("Demo", {"name": "Live", "pieces": [jacket, blouse]})
        check("live state saved", next(o for o in get_character_outfits("Demo") if o["id"] == oid2)
              .get("options", {}).get("piece_state"), {jacket: "open"})
        oid3 = add_character_outfit("Demo", {"name": "Hem only", "pieces": [jacket, blouse],
                                             "options": {"boot_hem": "over"}})
        _apply_outfit_set_route_sync("Demo", {"outfit_id": oid3})
        check("set without piece_state applies {}",
              (get_character_profile("Demo").get("equipped_options") or {}).get("piece_state"), {})

        # --- [7] figure --------------------------------------------------------------------------------------
        print("[7] figure")
        oo.set_piece_state("Demo", jacket, "open")
        check("worn_sets.open", figure.worn_sets("Demo").open, (jacket,))
        check("Figure.open", figure.wanted_figure("Demo").open, (jacket,))
        check("Figure.as_dict open", figure.wanted_figure("Demo").as_dict().get("open"), [jacket])
        built = figure.Figure(signature="x", bsig=BSIG, shape=BSIG, texture="tex000000000000", in_body=(),
                              painted=tuple(sorted((jacket, blouse))), own=(), pieces=dict(worn))
        figure.served_figure = lambda name: built
        state_rows = lambda: [c for c in figure.pending_changes("Demo") if c["key"].endswith(":state")]  # noqa: E731
        check("pending state change", state_rows(),
              [{"key": f"{jacket}:state", "name": "Jacket", "wanted": "open", "delivered": "closed"}])
        oo.set_piece_state("Demo", jacket, "closed")
        check("closed: worn_sets.open", figure.worn_sets("Demo").open, ())
        check("closed: no state change", state_rows(), [])
        check("closed: as_dict has no open", "open" in figure.wanted_figure("Demo").as_dict(), False)

        # --- [8] GC ------------------------------------------------------------------------------------------
        print("[8] GC")
        from app.core import outfit_cache_gc as gc
        owned = {jacket, blouse}
        open_sig = md5_12(open_raw)
        manifest = {"pieces": dict(worn), "items": [], "mesh_variant": "", "mesh_token": "",
                    "piece_state": {jacket: "open"}}
        check("open manifest valid", gc._entry_valid(open_sig, manifest, owned, set, "Demo"), True)
        check("_sign with state", gc._sign(dict(worn), [], "Demo", {jacket: "open"}), open_sig)
        side = root / "closed.json"
        side.write_text(json.dumps({"equipped_pieces": dict(worn), "equipped_items": []}))
        closed_manifest = gc.read_manifest(side)
        check("no piece_state -> {}", closed_manifest.get("piece_state"), {})
        check("closed entry valid as at BASE", gc._entry_valid(md5_12(base_sig(dict(worn), [])), closed_manifest,
                                                               owned, set, "Demo"), True)
        inventory.update_item(jacket, {"outfit_piece": {"slots": ["outer"], "covers": ["top"], "closable": False}})
        check("jacket not closable -> invalid", gc._entry_valid(open_sig, manifest, owned, set, "Demo"), False)
        inventory.update_item(jacket, {"outfit_piece": {"slots": ["outer"], "covers": ["top"], "closable": True}})

        # --- [9] route ---------------------------------------------------------------------------------------
        print("[9] route")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes.characters import router
        users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Kira"]},
                 "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}
        auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-test-user", ""))
        app = FastAPI()
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        app.include_router(router)
        client = TestClient(app)
        notified = []
        inventory._notify_outfit_changed = lambda *a, **k: notified.append((a, k))
        url = "/characters/Demo/outfit-options/piece-state"
        r = client.post(url, json={"item_id": jacket, "state": "open"}, headers={"x-test-user": "admin"})
        body = r.json() if r.status_code == 200 else {}
        check("admin 200", r.status_code, 200)
        check("payload piece_state", body.get("piece_state"), {jacket: "open"})
        check("payload closable", body.get("closable"),
              [{"item_id": jacket, "name": "Jacket", "state": "open", "names_state": False}])
        check("notified once", notified, [(("Demo", "piece_state"), {"action": "open", "item_ids": [jacket]})])
        r = client.post(url, json={"item_id": boots, "state": "open"}, headers={"x-test-user": "admin"})
        check("boots 400", (r.status_code, "not closable" in r.text), (400, True))
        r = client.post(url, json={"item_id": jacket, "state": "closed"}, headers={"x-test-user": "user"})
        check("other character's player 403", r.status_code, 403)
        r = client.get("/characters/Demo/outfit-options", headers={"x-test-user": "admin"})
        check("GET piece_state + closable", (r.status_code, r.json().get("piece_state"),
                                             [c["item_id"] for c in r.json().get("closable") or []]),
              (200, {jacket: "open"}, [jacket]))
        check("chat line says worn open",
              "worn open" in outfit_renderer.render_outfit(character_name="Demo")["full"], True)
        check("names_state hint", oo.fragment_names_state("denim jacket, unbuttoned"), True)

        # --- [10] coverage of an open piece (A8) -------------------------------------------------------------
        print("[10] coverage")
        from types import SimpleNamespace
        from app.core import body_slots, thought_context
        trousers = piece("Trousers", ["bottom"], "blue trousers")
        check("create Bare", save_character_profile("Bare", {"template": "human-roleplay", "gender": "female"},
                                                     create_new=True), True)
        for iid in (jacket, trousers):
            inventory.add_to_inventory("Bare", iid)
        bare_worn = {"outer": jacket, "bottom": trousers}
        prof = get_character_profile("Bare")
        prof["equipped_pieces"] = dict(bare_worn)
        check("Bare wears jacket + trousers", save_character_profile("Bare", prof), True)
        upper_spec = SimpleNamespace(covered_by=["top", "outer"])
        lower_spec = SimpleNamespace(covered_by=["bottom"])
        bare = lambda: get_character_profile("Bare")  # noqa: E731
        check("closed: covering", outfit_renderer.covering_pieces(bare()), bare_worn)
        check("closed: summary", thought_context._bare_slots_summary("Bare"), "barefoot")
        check("closed: upper covered", body_slots.is_slot_exposed(upper_spec, bare()), False)
        oo.set_piece_state("Bare", jacket, "open")
        check("open: covering", outfit_renderer.covering_pieces(bare()), {"bottom": trousers})
        check("open: summary", thought_context._bare_slots_summary("Bare"), "topless under an open layer, barefoot")
        check("open: upper exposed", body_slots.is_slot_exposed(upper_spec, bare()), True)
        check("open: lower still covered", body_slots.is_slot_exposed(lower_spec, bare()), False)

        # --- [11] the LLM text names both states (A9) --------------------------------------------------------
        print("[11] LLM text (A9)")
        from app.core import act_engine
        from app.core.prompt_builder import person_description
        from app.skills.outfit_change_skill import OutfitChangeSkill
        from app.skills.outfit_creation_skill import OutfitCreationSkill
        oo.set_piece_state("Demo", jacket, "closed")
        J, B = inventory.get_item(jacket), inventory.get_item(blouse)
        check("piece closed llm", outfit_renderer.piece_text(J, "closed", for_llm=True), "black jacket, worn closed")
        check("piece closed image", outfit_renderer.piece_text(J, "closed"), "black jacket")
        check("piece open llm", outfit_renderer.piece_text(J, "open", for_llm=True), "black jacket, worn open")
        check("piece open image", outfit_renderer.piece_text(J, "open"), "black jacket, worn open")
        for st in ("open", "closed"):
            check(f"blouse {st} llm", outfit_renderer.piece_text(B, st, for_llm=True), "white blouse")
        check("words closed llm", outfit_renderer.state_words(J, "closed", for_llm=True), "worn closed")
        check("words closed image", outfit_renderer.state_words(J, "closed"), "")
        check("words blouse llm", outfit_renderer.state_words(B, "closed", for_llm=True), "")
        rl = lambda pieces, state, llm: outfit_renderer.render_outfit(  # noqa: E731
            profile={}, equipped_pieces=dict(pieces), equipped_items=[], piece_state=state, for_llm=llm)["pieces"]
        check("render closed llm", rl(worn, {}, True), "black jacket, worn closed")
        check("render closed image", rl(worn, {}, False), "black jacket")
        for llm in (True, False):
            check(f"render open llm={llm}", rl(worn, {jacket: "open"}, llm),
                  "white blouse underneath black jacket, worn open")
        coat = piece("Coat", ["outer"], "long coat", partially_covers=["top"])
        check("coat closed llm", rl({"outer": coat, "top": blouse}, {}, True),
              "white blouse underneath long coat, worn closed")
        check("coat closed image", rl({"outer": coat, "top": blouse}, {}, False), "white blouse underneath long coat")

        check("thought outfit block",
              thought_context._build_outfit_block("Demo", "Your outfit").startswith(
                  "Your outfit: black jacket, worn closed"), True)
        check("storyteller subject", act_engine._subject_outfit_text("Demo"), "wearing: black jacket, worn closed")
        check("storyteller present", act_engine._build_present_people_block(["Demo"]),
              "- Demo — wearing: black jacket, worn closed")
        pd = lambda llm: person_description("Demo", include_outfit=True, include_exposed=False,  # noqa: E731
                                            apply_state_modifiers=False, for_llm=llm)
        check("person_description llm", pd(True).endswith("wearing: black jacket, worn closed"), True)
        check("person_description image", pd(False).endswith("wearing: black jacket"), True)
        check("present_people_details", "black jacket, worn closed" in thought_context.present_people_details(
            [("Demo", "Demo")]), True)

        change = OutfitChangeSkill.__new__(OutfitChangeSkill)
        check("decision menu closed", change.decision_menu("Demo"),
              ["Blouse (top, worn)", "Boots (feet)", "Jacket (outer, worn closed)", "Tee (top)"])
        oo.set_piece_state("Demo", jacket, "open")
        check("decision menu open", "Jacket (outer, worn open)" in change.decision_menu("Demo"), True)
        oo.set_piece_state("Demo", jacket, "closed")

        from app.core import prompt_templates
        captured = {}

        class _Captured(Exception):
            pass

        def _capture(task, **kw):
            captured.update(kw)
            raise _Captured()
        real_render_task, prompt_templates.render_task = prompt_templates.render_task, _capture
        create = OutfitCreationSkill.__new__(OutfitCreationSkill)
        owned = [e for e in inventory.get_character_inventory("Demo", include_equipped=True).get("inventory", [])
                 if e.get("item_category") == "outfit_piece"]
        try:
            create._generate_pieces_via_llm("Demo", "", "", "", "", "", "", owned, "", "en", 3)
        except _Captured:
            pass
        finally:
            prompt_templates.render_task = real_render_task
        lines = (captured.get("existing_block") or "").splitlines()
        check("creation marker jacket", "- [outer] [EQUIPPED, worn closed] Jacket: black jacket" in lines, True)
        check("creation marker blouse", "- [top] [EQUIPPED] Blouse: white blouse" in lines, True)

        def calls(path, func):
            tree = ast.parse((ROOT / path).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                    if name == func:
                        kw = {k.arg: k.value for k in node.keywords}
                        v = kw.get("for_llm")
                        yield node.lineno, isinstance(v, ast.Constant) and v.value is True
        for path in ("app/routes/chat.py", "app/routes/story.py", "app/core/act_engine.py",
                     "app/core/thought_context.py"):
            found = list(calls(path, "render_outfit"))
            check(f"LLM site {path}", bool(found) and all(llm for _, llm in found), True)
        for path in ("app/core/prompt_builder.py", "app/core/scene_render.py", "app/core/scene_photo.py",
                     "app/imagegen/service.py", "app/core/model_refs.py", "app/core/expression_regen.py",
                     "app/core/base_body.py", "app/core/character_ops.py", "app/routes/play.py"):
            bad = [ln for func in ("render_outfit", "person_description")
                   for ln, llm in calls(path, func) if llm]
            check(f"image site {path}", bad, [])

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
