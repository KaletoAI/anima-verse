#!/usr/bin/env python3
"""Bald dressed views under an own hair mesh (controller ruling 2026-11-10; app/core/base_body.py block "Bald
dressed views under an own hair mesh": ``outfit_body_bald``, ``dress_prompt(bald=…)``). A prompt detail only — the
texture key, the body id and every stale judgement stay what they were.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_bald.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package. No hub, no GPU:
``expression_regen.render_character_image`` is a recorder that writes a PNG + sidecar (one call = one image job).

Since Task 6 of plan 2026-11-12-unified-worn-pieces there is no body mode: the rule is
``base_body._bald_edit(meshed=…)``, meshed = the worn pieces want a shape (``figure.wanted_figure``), and a shape
view render (``base_body.render_shape_views`` — what the Build's shape step runs) renders the SHAPE's own view
(``tpose_<B0>``), not the outfit's. Since Task 11 the render is called directly (was: the removed outfit-body tab's
view run, POST outfit-bodies/<B0>/views/front/regenerate, which called the same producer with ``force``).

Fixture (character Demo: humanoid, pipeline on, side views off = the default; appearance with hair, so
``garment_hair.ensure_hair_item`` creates and WEARS its own hair item H). Items top / skirt, in mode in_body (both
in the shape); "retexture mode" in [1] = both switched to painted (no shape wanted).
Base views front/back of bsig, base model. Outfit O1 {top, skirt} WORN with a dressed front + back made BEFORE the
rule, texture T0 = its tsig, its body B0 = its shape key (figure.shape_key of {top, skirt} in the body — the dress
text of its shape inputs is T0's, nothing painted next to them; plan 2026-11-12-unified-worn-pieces Task 5) with a
shape record (refs + rigged GLB) and the outfit model of O1 on B0, its ``figure`` the one delivered now (shape B0,
nothing painted).

Expected, by hand:
[1] Rule: True (a shape wanted + worn own hair item); hair taken off (equipped_mesh_pieces {}) -> False; a hair
    item owned by another character worn in the slot -> False; both pieces painted (no shape) -> False.
[2] Prompt: dress_prompt(front, bald=True) =
      "Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand position,
       same framing and background. Only change their clothing: <text>. Completely bald with a smooth bare scalp."
    (the base front's BALD_HEAD words, capitalised, one sentence), negative = the bald=False negative + ", " +
    HAIR_NEGATIVE. bald=False = the same text WITHOUT that last sentence. The back draft's prompt carries
    "completely bald" (base view prompt, unchanged).
[3] Key unchanged: T0 = "tex" + sha256(canonical JSON of texture_inputs)[:12] with the own hair worn, and the
    SAME with it taken off (the rule is not an input); texture_inputs has no "bald" key.
[4] Nothing stale: outfit_body_of_outfit(O1) = B0, figure_stale(O1 model) "", outfit_info not stale. (After a
    re-render of its views B0 is no longer current for its views: the delivered figure stands on the plain body,
    so O1's model is stale "figure" and outfit_info "stale" — marked only, the view render builds nothing; was
    "not stale", judged by body_sha256. The removed tab's own B0 freshness line is no longer checked.) O1's old front
    (edited from the plain body ``bsig``) no longer counts: on the stored shape B0 the delivered figure's views
    stand on B0 (``dressed_image`` None — replaces "the old front counts", which judged it by the texture key).
[5] A new front render: render_shape_views(wanted figure of O1, ["front"], force) -> ok, ONE image job (tpose_<B0>, the shape's own front,
    occasion outfit_front — was tpose_<O1>) whose bare prompt is [2]'s bald prompt and whose negative ends with
    HAIR_NEGATIVE; its sidecar: texture_signature "" (nothing painted on a shape view; was T0), no "bald", the
    dress text of the shape's inputs; outfit_body_of_outfit(O1) still B0; O1's model stale "figure" (above).
[6] No own hair -> unchanged: hair taken off -> the next front render's prompt is [2]'s plain prompt, its
    negative the plain negative; the sidecar's texture_signature "", body B0.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []

BALD_SENTENCE = "Completely bald with a smooth bare scalp."
KEEP = ("Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand position, "
        "same framing and background.")


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(path: Path, colour, size=(64, 128)) -> Path:
    """A cut-out figure (transparent background: the fit references take the stored matte, no BiRefNet run)."""
    from PIL import Image, ImageDraw
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((24, 4, 40, 20), fill=colour)   # a "head" for the view guard
    ImageDraw.Draw(image).rectangle((20, 22, 44, 120), fill=colour)
    image.save(path)
    return path


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-body-bald-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        # A hair method with an own hair mesh (the default "body" makes no hair item; the edit chain this smoke
        # was written for is gone since the hair-from-body spec 2026-11-11).
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                        "base_body": {"hair_method": "hairdeck"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, garment_hair
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_images_dir, get_character_profile, \
            save_character_profile
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, **kw: path

        char = "Demo"
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair with a side parting",
                 "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}
        assert save_character_profile(char, human, create_new=True)
        png(get_character_images_dir(char) / f"{char}_1.png", (200, 180, 160))
        prof = get_character_profile(char)
        prof["profile_image"] = f"{char}_1.png"
        assert save_character_profile(char, prof)
        hair_id = garment_hair.ensure_hair_item(char)
        check("fixture: hair worn", inventory.get_equipped_mesh_pieces(char), {"hair": hair_id})
        for key, slots in (("top", ["top"]), ("skirt", ["bottom"])):
            op = {"slots": slots, "covers": [], "outfit_types": ["casual"], "mesh_mode": "in_body"}
            inventory.add_item(name=key.title(), category="outfit_piece", item_id=key,
                               prompt_fragment=f"a plain {key}", outfit_piece=op)
            inventory.add_to_inventory(char, key)
        pieces = {"top": "top", "bottom": "skirt"}
        prof = get_character_profile(char)
        prof["equipped_pieces"] = dict(pieces)
        assert save_character_profile(char, prof)

        def profile():
            return get_character_profile(char)

        def set_mode(mode):
            for key in ("top", "skirt"):
                op = dict(inventory.get_item(key)["outfit_piece"])
                op["mesh_mode"] = "in_body" if mode == "mesh" else "painted"
                inventory.update_item(key, {"outfit_piece": op})
            from app.core import figure as figure_mod
            check(f"mode {mode}", sorted(figure_mod.wanted_figure(char, profile=profile()).in_body),
                  ["skirt", "top"] if mode == "mesh" else [])

        def bald():
            # The rule of a meshed shape's views (``base_body._bald_edit``): meshed = the worn pieces want a shape.
            from app.core import figure as figure_mod
            p = profile()
            return base_body._bald_edit(char, p, meshed=not figure_mod.is_plain(
                figure_mod.wanted_figure(char, profile=p).shape))

        def set_profile(**changes):
            p = profile()
            for k, v in changes.items():
                if v is None:
                    p.pop(k, None)
                else:
                    p[k] = v
            assert save_character_profile(char, p)

        cdir = get_character_dir(char)
        M, R = cdir / "model3d", cdir / "model_refs"
        bsig = base_body.base_signature(char)
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
        base_views = {"front": png(R / f"tpose_{bsig}.png", (10, 10, 10)),
                      "back": png(R / f"tpose_back_{bsig}.png", (20, 20, 20))}
        for p in base_views.values():
            write_json(p.with_suffix(".json"), {"base_signature": bsig})
        M.mkdir(parents=True, exist_ok=True)
        (M / f"{bsig}.glb").write_bytes(b"BASE-GLB")
        write_json(M / f"{bsig}.json", {"base": True, "rig": "mixamo"})

        # --- [1] ---------------------------------------------------------------------------------------------
        print("[1] the rule")
        check("[1] mesh mode + own hair", bald(), True)
        set_profile(equipped_mesh_pieces={})
        check("[1] hair taken off", bald(), False)
        foreign = inventory.add_item(name="Other hair", category="garment", owner="Someone",
                                     garment={"kind": "hair", "slot": "hair", "body_slot": "hair"})["id"]
        set_profile(equipped_mesh_pieces={"hair": foreign})
        check("[1] foreign hair item", bald(), False)
        set_profile(equipped_mesh_pieces={"hair": hair_id})
        set_mode("retexture")
        check("[1] retexture mode", bald(), False)
        set_mode("mesh")
        check("[1] back on", bald(), True)

        # --- [2] ---------------------------------------------------------------------------------------------
        print("[2] the prompt")
        text = base_body.dress_text(char, "front", pieces=pieces, items=[], profile=profile())
        bald_prompt, bald_neg = base_body.dress_prompt(char, "front", pieces=pieces, items=[], profile=profile(),
                                                       bald=True)
        plain_prompt, plain_neg = base_body.dress_prompt(char, "front", pieces=pieces, items=[], profile=profile())
        check("[2] bald prompt", bald_prompt, f"{KEEP} Only change their clothing: {text}. {BALD_SENTENCE}")
        check("[2] plain prompt unchanged", plain_prompt, f"{KEEP} Only change their clothing: {text}.")
        check("[2] bald negative", bald_neg, f"{plain_neg}, {base_body.HAIR_NEGATIVE}")
        check("[2] the bald sentence is the base front's words", BALD_SENTENCE.lower().rstrip("."),
              base_body.BALD_HEAD)
        check("[2] back draft bald in both rules", "completely bald" in base_body.draft_prompt(char, "back")[0], True)

        # --- [3] ---------------------------------------------------------------------------------------------
        print("[3] the key is unchanged")
        variant = base_body.texture_variant(char, pieces, dressed=True, mesh={}, profile=profile())
        plain_in = base_body.texture_inputs(char, pieces=pieces, items=[], variant=variant, bsig=bsig,
                                            profile=profile())
        check("[3] no bald key in the inputs", "bald" in plain_in, False)

        def by_hand(inputs):
            raw = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            return "tex" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        T0 = base_body.texture_signature(plain_in)
        check("[3] T0 by hand", T0, by_hand(plain_in))
        set_profile(equipped_mesh_pieces={})
        off_in = base_body.texture_inputs(char, pieces=pieces, items=[], variant=variant, bsig=bsig,
                                          profile=profile())
        check("[3] same key without own hair", base_body.texture_signature(off_in), T0)
        set_profile(equipped_mesh_pieces={"hair": hair_id})
        from app.core import figure
        sets0 = figure.worn_sets(char, pieces=pieces, profile=profile())
        shape0 = figure.shape_inputs(char, sets0, bsig=bsig, variant=variant, profile=profile())
        check("fixture: the shape's dress text is T0's", shape0["dress_text"], plain_in["dress_text"])
        B0 = figure.shape_key(char, sets0, bsig=bsig, variant=variant, profile=profile())

        # --- fixture: O1 with views, body B0 and model from before the rule ------------------------------------
        variant_o, token = mesh_variant(char, pieces), mesh_items_token(char, pieces)
        O1 = mesh_signature(pieces, [], char, variant_o, token)
        TEXTS = plain_in["dress_text"]
        manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": variant_o,
                    "base_signature": bsig, "dressed": True}
        o1_front = png(R / f"tpose_{O1}.png", (100, 0, 0))
        write_json(o1_front.with_suffix(".json"), {**manifest, "base_image_sha256": sha(base_views["front"]),
                                                   "texture_signature": T0, "dress_text": TEXTS["front"]})
        o1_draft = png(R / "drafts" / f"tpose_back_{O1}.png", (0, 100, 0))
        write_json(o1_draft.with_suffix(".json"), {**manifest, "back_draft": True, "front_sha256": sha(o1_front),
                                                   "texture_signature": T0})
        o1_back = png(R / f"tpose_back_{O1}.png", (0, 0, 100))
        write_json(o1_back.with_suffix(".json"), {**manifest, "base_image_sha256": sha(base_views["back"]),
                                                  "back_draft": o1_draft.name, "back_draft_sha256": sha(o1_draft),
                                                  "texture_signature": T0, "dress_text": TEXTS.get("back", "")})
        base_body._store_texture_views(char, O1, T0, ["front", "back"], TEXTS)
        rec0 = {"body_id": B0, "shape_key": B0, "version": figure.SHAPE_VERSION, "shape_inputs": shape0,
                "base_signature": bsig, "built_for": O1, "used_views": ["front", "back"],
                "views": {"front": sha(o1_front), "back": sha(o1_back)}}
        for kind, view in (("tpose", o1_front), ("tpose_back", o1_back)):
            # The mesher inputs: copies of the outfit's views (base_body._write_body_refs).
            shutil.copyfile(view, R / f"{kind}_{B0}.png")
            write_json(R / f"{kind}_{B0}.json", {**json.loads(view.with_suffix(".json").read_text()),
                                                  "outfit_body": rec0})
        (M / f"{B0}.glb").write_bytes(b"BODY-0")
        write_json(M / f"{B0}.json", {"outfit_body": rec0, "rig": "mixamo", "created_at": "2026-11-10T10:00:00+00:00"})
        o1_model = {"pieces": pieces, "items": [], "base_signature": bsig, "base_model_sha256": sha(M / f"{bsig}.glb"),
                    "texture_signature": T0, "body_id": B0,
                    "body_sha256": sha(M / f"{B0}.glb"), "rig": "mixamo", "source": "base_body", "dressed": True,
                    "character": char}
        o1_model["figure"] = figure.delivered_figure(char, profile=profile(), pieces=pieces, items=[]).as_dict()
        check("fixture: O1 delivered on B0", o1_model["figure"].get("shape"), B0)
        write_json(M / f"{O1}.json", o1_model)
        (M / f"{O1}.glb").write_bytes(b"OUTFIT-ON-B0")

        renders = []

        def fake_render(character_name, *, output_stem, sidecar_extra=None, equipped_pieces=None,
                        equipped_items=None, **kw):
            renders.append({"stem": Path(output_stem).name, "occasion": kw.get("occasion"),
                            "prompt": kw.get("bare_prompt"), "negative": kw.get("extra_negative")})
            out = png(Path(f"{output_stem}.png"), (100, 50 + len(renders), 0))
            write_json(out.with_suffix(".json"), {"equipped_pieces": equipped_pieces or {},
                                                  "equipped_items": equipped_items or [],
                                                  "created_at": "2026-11-10T12:00:00+00:00",
                                                  **(sidecar_extra or {})})
            return out
        expression_regen.render_character_image = fake_render

        def not_stale(label, rerendered=False):
            """Nothing stale for the bald rule; after a re-render the outfit model says only what any re-render of
            a shape view makes it say (the model "figure")."""
            # A re-rendered view of B0 makes B0 outdated for its views: the delivered figure stands on the plain
            # body until B0 is meshed again, so O1's model is stale "figure" — marked only, nothing rebuilt.
            check(f"{label}: outfit model", base_body.figure_stale(char, o1_model), "figure" if rerendered else "")
            check(f"{label}: outfit_info stale", base_body.outfit_info(char, signature=O1)["status"] == "stale",
                  rerendered)
            check(f"{label}: O1 stands on B0", base_body.outfit_body_of_outfit(char, O1), B0)

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] nothing becomes stale")
        check("[4] the old front (edited from the plain body) is made for another figure",
              base_body.dressed_image(char, "front", O1, bsig), None)
        not_stale("[4]")

        def front_run():
            n = len(renders)
            wanted = figure.wanted_figure(char, profile=profile())
            check("front render: the wanted shape is B0", wanted.shape, B0)
            result = base_body.render_shape_views(char, wanted, ["front"], force=True)
            check("front render ok", (result.get("ok"), result.get("error") or ""), (True, ""))
            return renders[n:]

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] a new front render carries the bald rule")
        jobs = front_run()
        check("[5] one image job", [(x["stem"], x["occasion"]) for x in jobs], [(f"tpose_{B0}", "outfit_front")])
        check("[5] its prompt is the bald prompt", jobs[0]["prompt"], bald_prompt)
        check("[5] its negative ends with the hair negative",
              (jobs[0]["negative"] or "").endswith(base_body.HAIR_NEGATIVE), True)
        meta = json.loads((R / f"tpose_{B0}.json").read_text())
        check("[5] shape front sidecar: nothing painted, no bald key, the shape's dress text",
              (meta.get("texture_signature"), "bald" in meta, meta.get("dress_text")), ("", False, TEXTS["front"]))
        not_stale("[5]", rerendered=True)

        # --- [6] ---------------------------------------------------------------------------------------------
        print("[6] no own hair -> unchanged")
        set_profile(equipped_mesh_pieces={})
        jobs = front_run()
        check("[6] plain prompt", jobs[0]["prompt"] if jobs else None, plain_prompt)
        check("[6] plain negative", jobs[0]["negative"] if jobs else None, plain_neg)
        meta = json.loads((R / f"tpose_{B0}.json").read_text())
        check("[6] shape front sidecar: nothing painted", meta.get("texture_signature"), "")
        not_stale("[6]", rerendered=True)

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nOK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
