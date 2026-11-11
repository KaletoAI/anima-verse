#!/usr/bin/env python3
"""Bald dressed views under an own hair mesh (controller ruling 2026-11-10; app/core/base_body.py block "Bald
dressed views under an own hair mesh": ``outfit_body_bald``, ``dress_prompt(bald=…)``). A prompt detail only — the
texture key, the body id and every stale judgement stay what they were.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_bald.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package; the outfit_bodies router on a
bare FastAPI app with a TestClient (session lookup stubbed, header ``x-role: admin``). No hub, no GPU:
``expression_regen.render_character_image`` is a recorder that writes a PNG + sidecar (one call = one image job).

Fixture (character Demo: humanoid, pipeline on, outfit_body_mode mesh, side views off = the default; appearance
with hair, so ``garment_hair.ensure_hair_item`` creates and WEARS its own hair item H). Items top / skirt, painted.
Base views front/back of bsig, base model. Outfit O1 {top, skirt} WORN with a dressed front + back made BEFORE the
rule, texture T0 = its tsig, its body B0 = outfit_body_id(T0) (refs + rigged GLB) and the outfit model of O1 on B0.

Expected, by hand:
[1] Rule: outfit_body_bald(Demo) True (mesh mode + worn own hair item); hair taken off (equipped_mesh_pieces {})
    -> False; a hair item owned by another character worn in the slot -> False; retexture mode -> False.
[2] Prompt: dress_prompt(front, bald=True) =
      "Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand position,
       same framing and background. Only change their clothing: <text>. Completely bald with a smooth bare scalp."
    (the base front's BALD_HEAD words, capitalised, one sentence), negative = the bald=False negative + ", " +
    HAIR_NEGATIVE. bald=False = the same text WITHOUT that last sentence. The back draft's prompt carries
    "completely bald" (base view prompt, unchanged).
[3] Key unchanged: T0 = "tex" + sha256(canonical JSON of texture_inputs)[:12] with the own hair worn, and the
    SAME with it taken off (the rule is not an input); texture_inputs has no "bald" key.
[4] Nothing stale: O1's old front counts (dressed_image = the file), outfit_body_of_outfit(O1) = B0,
    outfit_body_stale(O1 model) "", outfit_info not stale; the tab's B0: freshness not stale, can_regenerate True.
    (After a re-render of its views B0 says only DRESSED_VIEWS_CHANGED, as after any re-render.)
[5] A new front render: POST views/front/regenerate on B0 -> ONE image job (tpose_<O1>, occasion outfit_front)
    whose bare prompt is [2]'s bald prompt and whose negative ends with HAIR_NEGATIVE; its sidecar names
    texture_signature T0 and no "bald"; outfit_body_of_outfit(O1) still B0; the tab's B0 still not stale.
[6] No own hair -> unchanged: hair taken off -> the next front render's prompt is [2]'s plain prompt, its
    negative the plain negative; texture T0, body B0.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
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


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


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
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import (artefact_graph, auth_dependency, base_body, expression_regen, garment_assembly,
                              garment_hair, garment_store, garments, outfit_bodies)
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_images_dir, get_character_profile, \
            save_character_profile
        from app.routes import outfit_bodies as outfit_bodies_routes
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, **kw: path

        auth_dependency._get_session_user = lambda request: (
            {"id": "a", "username": "admin", "role": "admin"} if request.headers.get("x-role") == "admin" else None)
        app = FastAPI()
        app.include_router(outfit_bodies_routes.router)
        client = TestClient(app)
        ADMIN = {"x-role": "admin"}

        char = "Demo"
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair with a side parting", "outfit_body_mode": "mesh",
                 "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}
        assert save_character_profile(char, human, create_new=True)
        png(get_character_images_dir(char) / f"{char}_1.png", (200, 180, 160))
        prof = get_character_profile(char)
        prof["profile_image"] = f"{char}_1.png"
        assert save_character_profile(char, prof)
        assert base_body.set_pipeline(char, True)
        hair_id = garment_hair.ensure_hair_item(char)
        check("fixture: hair worn", inventory.get_equipped_mesh_pieces(char), {"hair": hair_id})
        for key, slots in (("top", ["top"]), ("skirt", ["bottom"])):
            op = {"slots": slots, "covers": [], "outfit_types": ["casual"]}
            inventory.add_item(name=key.title(), category="outfit_piece", item_id=key,
                               prompt_fragment=f"a plain {key}", outfit_piece=op)
            inventory.add_to_inventory(char, key)
        pieces = {"top": "top", "bottom": "skirt"}
        prof = get_character_profile(char)
        prof["equipped_pieces"] = dict(pieces)
        assert save_character_profile(char, prof)

        def profile():
            return get_character_profile(char)

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
        check("[1] mesh mode + own hair", base_body.outfit_body_bald(char), True)
        set_profile(equipped_mesh_pieces={})
        check("[1] hair taken off", base_body.outfit_body_bald(char), False)
        foreign = inventory.add_item(name="Other hair", category="garment", owner="Someone",
                                     garment={"kind": "hair", "slot": "hair", "body_slot": "hair"})["id"]
        set_profile(equipped_mesh_pieces={"hair": foreign})
        check("[1] foreign hair item", base_body.outfit_body_bald(char), False)
        set_profile(equipped_mesh_pieces={"hair": hair_id}, outfit_body_mode="retexture")
        check("[1] retexture mode", base_body.outfit_body_bald(char), False)
        set_profile(outfit_body_mode="mesh")
        check("[1] back on", base_body.outfit_body_bald(char), True)

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
        B0 = base_body.outfit_body_id(T0)

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
        rec0 = {"body_id": B0, "mode": "mesh", "version": base_body.OUTFIT_BODY_VERSION, "texture_signature": T0,
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
                    "texture_signature": T0, "outfit_body_mode": "mesh", "body_id": B0,
                    "body_sha256": sha(M / f"{B0}.glb"), "rig": "mixamo", "source": "base_body", "dressed": True,
                    "character": char}
        write_json(M / f"{O1}.json", o1_model)
        (M / f"{O1}.glb").write_bytes(b"OUTFIT-ON-B0")
        outfit_bodies.stale_posture = lambda c, meta: ""

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

        def tab_body(body_id):
            data = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
            return next((b for b in data["bodies"] if b["body_id"] == body_id), None)

        def not_stale(label, rerendered=False):
            """Not stale for the rule; after a re-render the body says only what any re-render makes it say
            (``outfit_bodies.DRESSED_VIEWS_CHANGED``: its mesher inputs differ from the outfit's views now)."""
            b = tab_body(B0)
            f = b["freshness"] or {}
            want = ("stale", outfit_bodies.DRESSED_VIEWS_CHANGED) if rerendered else (None, None)
            got = (f.get("state"), f.get("reason")) if f.get("state") == "stale" else (None, None)
            check(f"{label}: tab B0 freshness", (got, b["can_regenerate"]), (want, True))
            check(f"{label}: outfit model not stale", base_body.outfit_body_stale(char, o1_model), "")
            check(f"{label}: outfit_info not stale", base_body.outfit_info(char, signature=O1)["status"] != "stale",
                  True)
            check(f"{label}: O1 stands on B0", base_body.outfit_body_of_outfit(char, O1), B0)

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] nothing becomes stale")
        check("[4] old front counts", base_body.dressed_image(char, "front", O1, bsig), o1_front)
        not_stale("[4]")

        def front_run():
            n = len(renders)
            r = client.post(f"/characters/{char}/outfit-bodies/{B0}/views/front/regenerate", headers=ADMIN)
            check("front run accepted", r.status_code, 202)
            check("front run ended", wait_for(lambda: not outfit_bodies._active), True)
            return renders[n:]

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] a new front render carries the bald rule")
        jobs = front_run()
        check("[5] one image job", [(x["stem"], x["occasion"]) for x in jobs], [(f"tpose_{O1}", "outfit_front")])
        check("[5] its prompt is the bald prompt", jobs[0]["prompt"], bald_prompt)
        check("[5] its negative ends with the hair negative",
              (jobs[0]["negative"] or "").endswith(base_body.HAIR_NEGATIVE), True)
        meta = json.loads(o1_front.with_suffix(".json").read_text())
        check("[5] sidecar: T0, no bald key", (meta.get("texture_signature"), "bald" in meta), (T0, False))
        not_stale("[5]", rerendered=True)

        # --- [6] ---------------------------------------------------------------------------------------------
        print("[6] no own hair -> unchanged")
        set_profile(equipped_mesh_pieces={})
        jobs = front_run()
        check("[6] plain prompt", jobs[0]["prompt"] if jobs else None, plain_prompt)
        check("[6] plain negative", jobs[0]["negative"] if jobs else None, plain_neg)
        meta = json.loads(o1_front.with_suffix(".json").read_text())
        check("[6] sidecar T0", meta.get("texture_signature"), T0)
        not_stale("[6]", rerendered=True)

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nOK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
