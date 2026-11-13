#!/usr/bin/env python3
"""Hair from the body mesh — the hair method ``body`` (spec
docs/superpowers/specs/2026-11-11-hair-from-body-design.md, plan Task 1).

Usage:
    ./.venv/bin/python scripts/smoke_hair_in_body.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no server; the
image service is a stub without a pool (nothing is loaded or probed). The world
config names no ``base_body.hair_method``, so the schema default applies.
The "unchanged bytes" proofs execute ``app/core/base_body.py`` (and read the
face-view prompt and ``resolve_negative_prompt``) as they were at ``START``
(019a995a, the task's start) and compare their output with today's for a
character on another method.

Fixtures (template human-default, female, 30, height 168, skin olive, eyes
green, build athletic, character_appearance "wears a red scarf", profile
image Demo_1.png, on the base-body pipeline, a ready base model
``model3d/<bsig>.glb`` + sidecar rig mixamo):
  ``Long``  hair {length long, color brunette}   -> hair text "long brunette hair";
  ``Short`` hair {length short, color black}     -> "short black hair";
  ``Bald``  no hair slot values                  -> no hair text;
  ``Deck``  as Long + profile hair_method "hairdeck".

EXPECTED VALUES, DERIVED BY HAND FROM THE SPEC AND THE CONSTANTS

[H0] Schema default ``base_body.hair_method`` = "body", choices ["body",
     "hairdeck"] (edit_chain and subtract removed by Task 2), label "From the
     body mesh"; ``world_hair_method()`` "body"; ``hair_method`` Long "body",
     Deck "hairdeck"; an unknown world value ("nonsense") resolves to "body",
     and so do the removed "edit_chain" / "subtract";
     ``hair_in_body`` Long True, Deck False.
[H1] Base views of Long (method body). APPEARANCE = "female, 30 years old,
     green eyes, olive skin, average height, athletic build" (the human build
     slot carries the height; smoke_base_body_prompt [1]).
     front block = "sfw, long brunette hair, " + BODY_TEXT (the natural-skin
       body text of 2026-11-13) + ", " + APPEARANCE
       (the hair text where BALD_HEAD stood);
     front prompt = BASE_FRONT_POSE_PROMPT + ", no hair on the chest or in
       front of the shoulders, chest, collarbones and front of the shoulders
       fully uncovered, the hair falls behind the shoulders" (long hair falls
       behind them: the hair slot has a mesh-input line for "long");
     back = "The same person turned around, seen directly from behind, back
       view, same A-pose, same framing, long brunette hair, the same
       hairstyle, hair length and hair volume as the reference, the hair falls
       behind the shoulders, the whole figure from head to feet in the frame."
       — left / right the same head clause in their sentences;
     negative (all views) = "hat, hood, headscarf, wig, clothing, underwear,
       jewellery, detailed anatomy, hands touching body, fists, curled fingers,
       fused fingers, mitten hands, cropped feet, feet cut off, cropped legs,
       close-up, portrait crop" (human declares no base_body_negative).
     Every view: "completely bald" / BALD_HEAD absent, "long brunette hair"
     present; the chest clause only in the front.
     Short: the same shapes with "short black hair" and WITHOUT "the hair falls
     behind the shoulders" (no mesh-input line for "short").
     Deck and Bald: every block / prompt / negative of the four views equals
     the start hash's output byte for byte (Bald: no hair text under body ->
     the bald wording; Deck: another method).
     Back draft of Long: DRAFT_PROMPTS["back"] with the outfit text and the
     same head clause as the back view, negative "hat, hood, headscarf, wig,
     detailed anatomy, " + POSE_NEGATIVE; Deck's draft = the start hash's.
     Dressed front edit (dress_text stubbed "they now wear a blue shirt"):
     Long opens with "Keep the image exactly as it is: the same person, same
     hair, same body shape, ..." and its negative has no "hair" term; Deck =
     the start hash's (DRESS_KEEP, "..., socks, hair").
     The clothing worn negative: "a blue shirt" -> the garment terms with
     "hair" last; with keep_hair no "hair".
     Face view: Long's prompt has "the same hairstyle, hair length and hair
     colour as the reference" in place of "completely bald with a smooth bare
     scalp", and the drop list is (hair, bangs, fringe, hair strands,
     ponytail); Deck's prompt = the start hash's FACE_VIEW_PROMPT_DEFAULT,
     drop list (). resolve_negative_prompt with the drop list on "hair,
     bangs, fringe, hair strands, ponytail, hat, cap" -> "hat, cap"; an
     explicit negative_prompt is kept as it is; without a drop list the output
     equals the start hash's function.
[H2] base_identity(Long) == base_identity(Long as hairdeck) (the method is no
     identity input); prompt_fingerprint differs. base_prompts_freshness(Long):
     no stored front -> missing "Base body images missing — render them in
     the Figure tab"; a front sidecar with the hairdeck fingerprint ->
     stale OLDER_PROMPTS; with Long's own fingerprint -> current.
[H3] garments.after_base_model(Long) asks the Build ("body_change",
     ``figure_build.request`` recorded — Task 8 of plan
     2026-11-12-unified-worn-pieces), and the Build of Long has no chain step
     (``build_chains`` False; was: after_base_model -> False; enqueue_garment =
     recorder): no hair item (find_hair_item None), nothing queued;
     ensure_hair_item(Long) -> ValueError starting "Hair comes from the body
     mesh". Contrast: the Build's hair step of Deck (was: after_base_model)
     creates Deck's hair item and queues it once.
[H4] hair_fill.find_candidates({}) lists Deck only (Long and Short are body,
     Bald has no hair text); world method "hairdeck" -> Long, Short and Deck.
[H5] garment_store.steps_for("hair", "body") == () (never a ValueError);
     HUB_JOBS["hair:body"] == {}. With Deck's item and Deck switched to
     "body": check_run -> ValueError "Hair comes from the body mesh";
     run_estimate -> {steps [], hub_jobs 0, note "Hair comes from the body
     mesh", refit False}; hair_summary None; accepted_fit None (a fit record
     of the current fsig is written first: served under hairdeck, not under
     body); the bald edit of the wanted figure's shape (the profile wears a
     coat in mode in_body, so the shape is meshed — Task 6 of plan
     2026-11-12-unified-worn-pieces replaced outfit_body_bald in mesh mode by
     ``base_body._bald_edit`` of the wanted shape): True under hairdeck
     (wears its own hair item), False under body. The hair payload (the Wardrobe hair row's; route function
     called directly): hair_in_body True, garment None, others [],
     base_prompts = H2's freshness; under hairdeck hair_in_body False,
     base_prompts None.

Fails on 019a995a: [H0] schema default "edit_chain", choices without "body",
then KeyError 'body' on the choice labels (and garment_hair has no
``hair_in_body``; Long's base front would be bald).
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

START = "019a995a"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def old_source(path: str) -> str:
    return subprocess.run(["git", "show", f"{START}:{path}"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout


def old_names(path: str, names) -> dict:
    """The top-level assignments / functions ``names`` of ``path`` at START."""
    tree = ast.parse(old_source(path))
    ns: dict = {}
    exec("from typing import Any, Dict, Iterable, List, Optional, Tuple", ns)  # annotations of the old code
    for node in tree.body:
        target = (node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                  else getattr(node, "name", None))
        if target in names:
            exec(compile(ast.Module([node], []), f"{path}@{START}", "exec"), ns)
    return ns


APPEARANCE = "female, 30 years old, green eyes, olive skin, average height, athletic build"
BODY_TEXT = "an unclothed body with realistic natural skin, visible pores, subtle skin tone variation, matte skin, a plain smooth chest and groin like a store mannequin"
CHEST = ("no hair on the chest or in front of the shoulders, chest, collarbones and front of the shoulders "
         "fully uncovered")
REF = "the same hairstyle, hair length and hair volume as the reference"
BEHIND = "the hair falls behind the shoulders"
POSE_NEG = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, "
            "feet cut off, cropped legs, close-up, portrait crop")
HAIRED_NEG = "hat, hood, headscarf, wig, clothing, underwear, jewellery, detailed anatomy, " + POSE_NEG
VIEW_TAIL = {
    "back": "The same person turned around, seen directly from behind, back view, same A-pose, same framing, ",
    "left": "The same person turned to a strict left side profile view, same A-pose, same framing, ",
    "right": "The same person turned to a strict right side profile view, same A-pose, same framing, ",
}
END = "the whole figure from head to feet in the frame."
OUTFIT = ("wearing exactly the same outfit as the person in the reference image, the same garments, lengths, cut, "
          "colours and shoes")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-in-body-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import (base_body, config_scope, garment_assembly, garment_clothing, garment_hair, garments,
                              glb_delivery, model_refs)
        from app.core import garment_store as gs
        from app.core import figure_build
        from app.core.improvements.types.hair_fill import HairFill
        from _figure_build_fixtures import build_chains
        from app.imagegen import service
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        # No image service: HairDeck's fsig asks the pool for its backend params — a stub without a
        # pool answers "none" instead of loading (and probing) any configured backend.
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda *a, **k: True
        glb_delivery.delivery_path = lambda path, **kw: path

        old_bb = types.ModuleType("base_body_" + START)
        old_bb.__file__ = "base_body_" + START + ".py"
        exec(compile(old_source("app/core/base_body.py"), old_bb.__file__, "exec"), old_bb.__dict__)
        # The body text changed on its own (2026-11-13, natural skin — not part of
        # the hair method): the START module gets today's text, so these proofs
        # still compare only what the hair method touches.
        old_bb.BODY_TEXT = base_body.BODY_TEXT

        base = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                "character_appearance": "wears a red scarf",
                "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                               "build": {"type": "athletic"}}}
        fixtures = {"Long": {"hair": {"length": "long", "color": "brunette"}},
                    "Short": {"hair": {"length": "short", "color": "black"}},
                    "Bald": {},
                    "Deck": {"hair": {"length": "long", "color": "brunette"}}}
        for name, slots in fixtures.items():
            profile = json.loads(json.dumps(base))
            profile["body_slots"].update(slots)
            if name == "Deck":
                profile["hair_method"] = "hairdeck"
            check(f"create {name}", save_character_profile(name, profile, create_new=True), True)
            images = get_character_images_dir(name)
            images.mkdir(parents=True, exist_ok=True)
            (images / f"{name}_1.png").write_bytes(b"\x89PNG" + b"a" * 100)
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"image {name}", save_character_profile(name, stored), True)
            bsig = base_body.base_signature(name)
            mdir = get_character_dir(name) / "model3d"
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / f"{bsig}.glb").write_bytes(f"glb-{name}".encode())
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            check(f"{name} base ready", (base_body.base_model_info(name) or {}).get("status"), "ready")
        P = {name: get_character_profile(name) for name in fixtures}

        # --- [H0] -----------------------------------------------------------------
        print("[H0] the method and its default")
        field = config_scope.schema_for(config_scope.WORLD)["base_body"]["fields"]["hair_method"]
        check("schema default", field["default"], "body")
        check("schema choices", field["choices"], ["body", "hairdeck"])
        check("schema label", field["choice_labels"]["body"], "From the body mesh")
        check("world default", garment_hair.world_hair_method(), "body")
        check("methods", (garment_hair.hair_method("Long"), garment_hair.hair_method("Deck")), ("body", "hairdeck"))
        config._CONFIG.setdefault("base_body", {})["hair_method"] = "nonsense"
        check("unknown world value -> body", garment_hair.world_hair_method(), "body")
        for gone in ("edit_chain", "subtract"):
            config._CONFIG["base_body"]["hair_method"] = gone
            check(f"removed world value {gone} -> body", garment_hair.world_hair_method(), "body")
        config._CONFIG.pop("base_body", None)
        check("hair_in_body", (garment_hair.hair_in_body("Long"), garment_hair.hair_in_body("Deck")), (True, False))

        # --- [H1] -----------------------------------------------------------------
        print("[H1] base view prompts")
        from app.core.model_refs import BASE_FRONT_POSE_PROMPT
        front_block = base_body.base_character("Long", "front", profile=P["Long"])
        check("Long front block", front_block, f"sfw, long brunette hair, {BODY_TEXT}, {APPEARANCE}")
        front, negative = base_body.base_prompt("Long", "front", profile=P["Long"])
        check("Long front prompt", front, f"{BASE_FRONT_POSE_PROMPT}, {CHEST}, {BEHIND}")
        check("Long front negative", negative, HAIRED_NEG)
        for view in ("back", "left", "right"):
            prompt, negative = base_body.base_prompt("Long", view, profile=P["Long"])
            check(f"Long {view}", prompt, f"{VIEW_TAIL[view]}long brunette hair, {REF}, {BEHIND}, {END}")
            check(f"Long {view} negative", negative, HAIRED_NEG)
            check(f"Long {view}: no chest clause", CHEST in prompt, False)
        texts = [front_block, front] + [base_body.base_prompt("Long", v, profile=P["Long"])[0]
                                        for v in ("back", "left", "right")]
        check("Long: no bald words", [("completely bald" in t, base_body.BALD_HEAD in t) for t in texts],
              [(False, False)] * 5)
        # The front carries the hair in its block (the style slot), the edit views in their prompt.
        check("Long: haired text in every view", ["long brunette hair" in texts[i] for i in (0, 2, 3, 4)],
              [True] * 4)
        check("Short front", base_body.base_prompt("Short", "front", profile=P["Short"])[0],
              f"{BASE_FRONT_POSE_PROMPT}, {CHEST}")
        check("Short back", base_body.base_prompt("Short", "back", profile=P["Short"])[0],
              f"{VIEW_TAIL['back']}short black hair, {REF}, {END}")

        def views(module, name):
            return {v: (module.base_character(name, v, profile=P[name]), module.base_prompt(name, v, profile=P[name]))
                    for v in base_body.BASE_VIEWS}

        for name in ("Deck", "Bald"):
            check(f"{name} views == {START}", views(base_body, name), views(old_bb, name))
        check("Deck front still bald", base_body.BALD_HEAD in base_body.base_character("Deck", "front",
                                                                                        profile=P["Deck"]), True)

        draft, negative = base_body.draft_prompt("Long", "back", profile=P["Long"])
        check("Long back draft", draft, f"{VIEW_TAIL['back']}long brunette hair, {REF}, {BEHIND}, {OUTFIT}, {END}")
        check("Long draft negative", negative, "hat, hood, headscarf, wig, detailed anatomy, " + POSE_NEG)
        check(f"Deck draft == {START}", base_body.draft_prompt("Deck", "back", profile=P["Deck"]),
              old_bb.draft_prompt("Deck", "back", profile=P["Deck"]))

        stub = lambda *a, **k: "they now wear a blue shirt"  # noqa: E731
        with patch.object(base_body, "dress_text", stub), patch.object(old_bb, "dress_text", stub):
            prompt, negative = base_body.dress_prompt("Long", "front", pieces={}, items=[], profile=P["Long"])
            check("Long dressed edit", prompt.startswith("Keep the image exactly as it is: the same person, same "
                                                         "hair, same body shape,"), True)
            check("Long dressed negative: no hair", "hair" in negative.split(", "), False)
            check(f"Deck dressed == {START}",
                  base_body.dress_prompt("Deck", "front", pieces={}, items=[], profile=P["Deck"]),
                  old_bb.dress_prompt("Deck", "front", pieces={}, items=[], profile=P["Deck"]))
        check("worn negative", garment_clothing._worn_negative("a blue shirt"),
              "loose clothing, baggy, skirt, dress, jacket, shoes, socks, hair")
        check("worn negative keep_hair", garment_clothing._worn_negative("a blue shirt", keep_hair=True),
              "loose clothing, baggy, skirt, dress, jacket, shoes, socks")

        old_face = old_names("app/core/model_refs.py", {"FACE_VIEW_PROMPT_DEFAULT"})["FACE_VIEW_PROMPT_DEFAULT"]
        check("Long face prompt", model_refs.get_face_view_prompt("Long"),
              old_face.replace("completely bald with a smooth bare scalp",
                               "the same hairstyle, hair length and hair colour as the reference"))
        check("Long face drop", model_refs.face_view_drop_negative("Long"),
              ("hair", "bangs", "fringe", "hair strands", "ponytail"))
        check(f"Deck face == {START}", (model_refs.get_face_view_prompt("Deck"),
                                        model_refs.face_view_drop_negative("Deck")), (old_face, ()))
        drop = list(model_refs.FACE_VIEW_HAIR_NEGATIVE)
        uc_neg = "hair, bangs, fringe, hair strands, ponytail, hat, cap"
        check("drop on the use case", service.resolve_negative_prompt({"negative_prompt_drop": drop}, uc_neg),
              "hat, cap")
        check("explicit negative kept", service.resolve_negative_prompt(
            {"negative_prompt": "hair, x", "negative_prompt_drop": drop}, uc_neg), "hair, x")
        old_resolve = old_names("app/imagegen/service.py", {"resolve_negative_prompt"})["resolve_negative_prompt"]
        for data in ({}, {"negative_prompt": "a, b"}, {"negative_prompt_extra": "z"},
                     {"negative_prompt": "a", "negative_prompt_extra": "z"}):
            check(f"resolve {data} == {START}", service.resolve_negative_prompt(data, uc_neg),
                  old_resolve(data, uc_neg))

        # --- [H2] -----------------------------------------------------------------
        print("[H2] identity and fingerprint")
        as_deck = dict(P["Long"], hair_method="hairdeck")
        check("identity unchanged", base_body.base_identity("Long", profile=P["Long"]),
              base_body.base_identity("Long", profile=as_deck))
        fp_body = base_body.prompt_fingerprint("Long", profile=P["Long"])
        fp_deck = base_body.prompt_fingerprint("Long", profile=as_deck)
        check("fingerprint differs", fp_body != fp_deck, True)
        check("freshness without a front", base_body.base_prompts_freshness("Long"),
              {"state": "missing", "reason": "Base body images missing — render them in the Base body tab"})
        refs = model_refs.get_model_refs_dir("Long")
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Long")
        (refs / f"tpose_{bsig}.png").write_bytes(b"\x89PNG front")
        sidecar = refs / f"tpose_{bsig}.json"
        sidecar.write_text(json.dumps({"base_signature": bsig, "prompt_fingerprint": fp_deck}))
        check("freshness bald front", base_body.base_prompts_freshness("Long"),
              {"state": "stale", "reason": base_body.OLDER_PROMPTS})
        sidecar.write_text(json.dumps({"base_signature": bsig, "prompt_fingerprint": fp_body}))
        check("freshness haired front", base_body.base_prompts_freshness("Long"), {"state": "current", "reason": ""})
        sidecar.write_text(json.dumps({"base_signature": bsig, "prompt_fingerprint": fp_deck}))

        # --- [H3] -----------------------------------------------------------------
        print("[H3] no hair item after the base model")
        QUEUED = []
        REQUESTS = []

        def enqueue(name, item_id, automatic=True):
            QUEUED.append((name, item_id))
            job = garments._Job(item_id, None, None, False)
            job.result = {"ok": True, "ran": []}
            job.done.set()
            return job
        with patch.object(garments, "enqueue_garment", enqueue), \
                patch.object(figure_build, "request", lambda name, trigger: REQUESTS.append((name, trigger)) or True):
            check("after_base_model Long asks the Build", (garments.after_base_model("Long"), REQUESTS),
                  (True, [("Long", "body_change")]))
            check("the Build of Long has no chain step", build_chains("Long"), False)
            check("Long has no hair item", garment_hair.find_hair_item("Long", get_character_profile("Long")), None)
            check("nothing queued", QUEUED, [])
            try:
                garment_hair.ensure_hair_item("Long")
                check("ensure_hair_item refused", "no error", "ValueError")
            except ValueError as e:
                check("ensure_hair_item refused", str(e).startswith("Hair comes from the body mesh"), True)
            check("the Build of Deck runs its hair step", build_chains("Deck"), True)
            deck_item = (garment_hair.find_hair_item("Deck", get_character_profile("Deck")) or {}).get("id")
            check("Deck item queued", QUEUED, [("Deck", deck_item)])

        # --- [H4] -----------------------------------------------------------------
        print("[H4] hair_fill candidates")
        typ = HairFill()
        # Deck now wears an item without a fit: its candidate is the worn item ("missing").
        check("body characters are no candidates",
              [c.key for c in typ.find_candidates(typ.validate({}))], ["character:Deck"])
        config._CONFIG.setdefault("base_body", {})["hair_method"] = "hairdeck"
        check("world hairdeck lists them",
              [c.key for c in typ.find_candidates(typ.validate({}))],
              ["character:Deck", "character:Long", "character:Short"])
        config._CONFIG.pop("base_body", None)

        # --- [H5] -----------------------------------------------------------------
        print("[H5] no steps, nothing served")
        check("steps_for body", gs.steps_for("hair", "body"), ())
        check("HUB_JOBS body", garments.HUB_JOBS["hair:body"], {})
        deck = get_character_profile("Deck")
        fsig = gs.garment_fsig("Deck", deck_item, profile=deck)
        fit = gs.garment_path("Deck", deck_item, fsig, "fit")
        fit.parent.mkdir(parents=True, exist_ok=True)
        fit.write_bytes(b"fit")
        base_sha = base_body.current_base("Deck")[1]
        gs.write_record(fit.with_suffix(".json"), {"accepted": True, "kind": "hair", "item_id": deck_item,
                                                    "method": "hairdeck", "base_model_sha256": base_sha})
        check("hairdeck serves its fit", (gs.accepted_fit("Deck", deck_item, base_model_sha=base_sha) or (None,))[0],
              fit)
        # A worn piece in the body: the wanted figure stands on a meshed shape (Task 6 of plan
        # 2026-11-12-unified-worn-pieces; the per-character mode and outfit_body_bald are gone).
        from app.core import figure
        from app.models import inventory

        def bald_edit(profile):
            """Whether the dressed edit of the wanted figure's shape closes with the bald head."""
            shape = figure.wanted_figure("Deck", profile=profile).shape
            return base_body._bald_edit("Deck", profile, meshed=not figure.is_plain(shape))
        coat = inventory.add_item(name="Coat", category="outfit_piece", prompt_fragment="a coat",
                                  outfit_piece={"slots": ["outer"], "mesh_mode": "in_body"})["id"]
        mesh = dict(deck, equipped_pieces={"outer": coat})
        check("a shape", figure.is_plain(figure.wanted_figure("Deck", profile=mesh).shape), False)
        check("bald edit hairdeck", bald_edit(mesh), True)
        hair_route = __import__("app.routes.characters", fromlist=["x"]).get_character_hair
        tab = hair_route("Deck", _={})
        check("tab hairdeck", (tab["hair_in_body"], tab["base_prompts"]), (False, None))

        deck["hair_method"] = "body"
        check("save Deck body", save_character_profile("Deck", deck), True)
        try:
            garments.check_run("Deck", deck_item)
            check("check_run refused", "no error", "ValueError")
        except ValueError as e:
            check("check_run refused", str(e), "Hair comes from the body mesh")
        check("run_estimate", garments.run_estimate("Deck", deck_item),
              {"steps": [], "hub_jobs": 0, "note": "Hair comes from the body mesh", "refit": False})
        check("hair_summary", garments.hair_summary("Deck"), None)
        check("accepted_fit body", gs.accepted_fit("Deck", deck_item, base_model_sha=base_sha), None)
        check("bald edit body", bald_edit(dict(get_character_profile("Deck"), equipped_pieces={"outer": coat})),
              False)
        tab = hair_route("Deck", _={})
        check("tab body", (tab["hair_in_body"], tab["method"], tab["garment"], tab["others"],
                           tab["base_prompts"]["state"]),
              (True, "body", None, [], "missing"))
        check("tab Long", hair_route("Long", _={})["base_prompts"],
              {"state": "stale", "reason": base_body.OLDER_PROMPTS})

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("PASS hair in body: haired base prompts, other methods byte-identical, no hair item / run / fit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
