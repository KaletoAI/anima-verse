#!/usr/bin/env python3
"""Bald outfit bodies under an own hair mesh (user decision 2026-11-10; app/core/base_body.py block "Bald outfit
bodies": ``outfit_body_bald``, ``hair_rule_off``, ``dress_prompt(bald=…)``, ``texture_inputs(bald=…)``;
app/core/outfit_bodies.py ``source_outfit`` / ``successor`` / ``regenerate_blocked``; artefact GC).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_bald.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package; the outfit_bodies router on a
bare FastAPI app with a TestClient (session lookup stubbed, header ``x-role: admin``). No hub, no GPU:
``expression_regen.render_character_image`` is a recorder that writes a PNG + sidecar (one call = one image job),
``base_body.prepare_outfit_body`` a recorder (one call = one mesh run), ``outfit_bodies.rebuild_worn_on`` a recorder.

Fixture (character Demo: humanoid, pipeline on, outfit_body_mode mesh, side views off = the default; appearance
with hair, so ``garment_hair.ensure_hair_item`` creates and WEARS its own hair item H). Items top / skirt, painted.
Base views front/back of bsig, base model. Outfit O1 {top, skirt} WORN with a dressed front + back made BEFORE the
rule (no ``bald`` in their sidecars), texture T0 = its tsig without the rule, its OLD body B0 = outfit_body_id(T0)
(record without ``bald``; refs + rigged GLB) and the outfit model of O1 on B0.

Expected, by hand:
[1] Rule: outfit_body_bald(Demo) True (mesh mode + worn own hair item); hair taken off (equipped_mesh_pieces {})
    -> False; a hair item owned by another character worn in the slot -> False; retexture mode -> False.
[2] Prompt: dress_prompt(front, bald=True) =
      "Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand position,
       same framing and background. Only change their clothing: <text>. Completely bald, smooth clean-shaven head
       with no hair at all, the bare scalp and the bare back of the head fully visible, natural eyebrows."
    (the base front's BALD_HEAD words, capitalised, one sentence), negative = the bald=False negative + ", " +
    HAIR_NEGATIVE. bald=False = the same text WITHOUT that last sentence (unchanged composition). The back
    draft's prompt carries "completely bald" in both rules (base view prompt, unchanged).
[3] Key: texture_inputs(bald=True) = the bald=False dict + {"bald": true}; T0 = "tex" + sha256(canonical JSON of
    the dict WITHOUT the key)[:12] (= every texture before the rule — unchanged), Tb = the same over the dict
    WITH it; Tb != T0, so outfit_body_id(Tb) = Bb != B0.
[4] Old body under the rule: O1's old front no longer counts (dressed_image None; with hair_rule=False it is the
    file); hair_rule_off(old front) "baked_hair". outfit_body_of_outfit(O1) = "" (no front under the rule), with
    bald=True = Bb (the old front's pieces), with bald=False = B0.
    outfit_body_stale(O1 model) "baked_hair"; outfit_info stale_reason "baked_hair", error BAKED_HAIR.
    Tab, body B0: freshness stale, reason contains BAKED_HAIR; hair_stale "baked_hair"; successor Bb;
    regenerate_from O1; can_regenerate False with regenerate_blocked RENDER_VIEWS_FIRST (O1 has no view under the
    rule yet); front view blocked "", freshness contains VIEW_NOT_BALD (B0's own mesher input, the Tb store is
    empty); back blocked DRESSED_FRONT_FIRST. POST regenerate -> 409 RENDER_VIEWS_FIRST. Nothing rendered.
[5] View runs: POST views/front/regenerate -> ONE image job (tpose_<O1>, occasion outfit_front) whose bare prompt
    is [2]'s bald prompt and whose sidecar names bald True and texture_signature Tb; the tab's front now serves
    the Tb store, freshness current. Back: blocked "" now; its view run writes draft + fit (two more image jobs,
    occasions outfit_back_draft / outfit_back), the draft prompt with "completely bald", sidecars bald True.
    Zero mesh runs so far.
[6] Regenerate on B0: regenerate_blocked "" -> POST regenerate -> prepare_outfit_body(Demo, O1, rebuild=True)
    once (the recorder answers body Bb) -> last_run ok, result successor Bb, rebuild_worn_on(Demo, Bb) once.
[7] GC: before the outfit model moves, B0 is reachable (O1's model names it and T0). After it moved (model
    of O1 on Bb, record bald, refs of Bb, O1's model names Bb/Tb/bald) B0 is NOT reachable, Bb is ("texture of a
    live outfit (mesh mode)"); outfit_body_stale(new O1 model) "".
[8] Hair per bald body: garment_assembly.body_fit_warning(new O1 model meta) asks garments.body_fit for the worn
    hair H on body Bb with build=True (accepted base fit stubbed) — the hair is fitted per outfit body.
[9] No own hair -> unchanged: hair taken off -> outfit_body_bald False; texture of O1 = T0 again;
    outfit_body_of_outfit(O1) uses the views made under the rule? They are bald now -> hair_rule_off "bald_body",
    dressed_image None. The OLD front sidecar (no bald) -> hair_rule_off "". Retexture mode: a bald view ->
    "body_mode", an old one -> "". A dressed=False copy is never judged ("").
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

BALD_SENTENCE = ("Completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back "
                 "of the head fully visible, natural eyebrows.")
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
        print("[3] the key")
        variant = base_body.texture_variant(char, pieces, dressed=True, mesh={}, profile=profile())
        plain_in = base_body.texture_inputs(char, pieces=pieces, items=[], variant=variant, bsig=bsig,
                                            profile=profile())
        bald_in = base_body.texture_inputs(char, pieces=pieces, items=[], variant=variant, bsig=bsig,
                                           profile=profile(), bald=True)
        check("[3] bald inputs = plain + bald", bald_in, {**plain_in, "bald": True})
        check("[3] plain inputs carry no key", "bald" in plain_in, False)

        def by_hand(inputs):
            raw = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            return "tex" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        T0, Tb = base_body.texture_signature(plain_in), base_body.texture_signature(bald_in)
        check("[3] T0 by hand", T0, by_hand({k: v for k, v in plain_in.items()}))
        check("[3] Tb by hand", Tb, by_hand({**plain_in, "bald": True}))
        B0, Bb = base_body.outfit_body_id(T0), base_body.outfit_body_id(Tb)
        check("[3] new body id", (Tb != T0, Bb != B0), (True, True))

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

        renders, meshes, rebuilt = [], [], []

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

        def fake_prepare(c, signature=None, *, force=False, rebuild=False):
            meshes.append((c, signature, rebuild))
            return {"ok": True, "cached": False, "body_id": Bb}
        base_body.prepare_outfit_body = fake_prepare
        outfit_bodies.rebuild_worn_on = lambda c, body_id: rebuilt.append((c, body_id)) or True

        def tab_body(body_id):
            data = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
            return next((b for b in data["bodies"] if b["body_id"] == body_id), None)

        def fresh(b, v):
            f = ((b["view_info"][v] or {}).get("meta") or {}).get("freshness") or {}
            return f.get("state"), f.get("reason") or ""

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] the old body under the rule")
        check("[4] old front does not count", base_body.dressed_image(char, "front", O1, bsig), None)
        check("[4] ... without the hair rule it does", base_body.dressed_image(char, "front", O1, bsig,
                                                                              hair_rule=False), o1_front)
        check("[4] hair_rule_off(old front)", base_body.hair_rule_off(char, json.loads(
            o1_front.with_suffix(".json").read_text())), "baked_hair")
        check("[4] O1 stands on no body now (no front under the rule)", base_body.outfit_body_of_outfit(char, O1), "")
        check("[4] ... under the rule with its old front's pieces on Bb",
              base_body.outfit_body_of_outfit(char, O1, bald=True), Bb)
        check("[4] ... under the old rule on B0", base_body.outfit_body_of_outfit(char, O1, bald=False), B0)
        check("[4] outfit model stale", base_body.outfit_body_stale(char, o1_model), "baked_hair")
        info = base_body.outfit_info(char, signature=O1)
        check("[4] outfit_info", (info["status"], info["stale_reason"], info["error"]),
              ("stale", "baked_hair", base_body.BAKED_HAIR))
        b = tab_body(B0)
        check("[4] B0 stale with BAKED_HAIR", (b["freshness"]["state"], base_body.BAKED_HAIR in b["freshness"]["reason"]),
              ("stale", True))
        check("[4] hair_stale / successor / source", (b["hair_stale"], b["successor"], b["regenerate_from"]),
              ("baked_hair", Bb, O1))
        check("[4] regenerate blocked", (b["can_regenerate"], b["regenerate_blocked"]),
              (False, outfit_bodies.RENDER_VIEWS_FIRST))
        check("[4] front blocked / back blocked", (b["view_info"]["front"]["blocked"], b["view_info"]["back"]["blocked"]),
              ("", base_body.DRESSED_FRONT_FIRST))
        check("[4] front freshness names the rule", base_body.VIEW_NOT_BALD in fresh(b, "front")[1], True)
        r = client.post(f"/characters/{char}/outfit-bodies/{B0}/regenerate", headers=ADMIN)
        check("[4] regenerate -> 409", (r.status_code, r.json().get("detail")), (409, outfit_bodies.RENDER_VIEWS_FIRST))
        check("[4] nothing rendered or meshed", (renders, meshes), ([], []))

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] the view runs render bald")
        r = client.post(f"/characters/{char}/outfit-bodies/{B0}/views/front/regenerate", headers=ADMIN)
        check("[5] front run accepted", r.status_code, 202)
        check("[5] front run ended", wait_for(lambda: not outfit_bodies._active), True)
        check("[5] one image job", [(x["stem"], x["occasion"]) for x in renders], [(f"tpose_{O1}", "outfit_front")])
        check("[5] its prompt is the bald prompt", renders[0]["prompt"], bald_prompt)
        check("[5] its negative carries the hair negative", (renders[0]["negative"] or "").endswith(
            base_body.HAIR_NEGATIVE), True)
        front_meta = json.loads(o1_front.with_suffix(".json").read_text())
        check("[5] sidecar bald + Tb", (front_meta.get("bald"), front_meta.get("texture_signature")), (True, Tb))
        b = tab_body(B0)
        check("[5] tab front serves the Tb store", f"/outfit-bodies/{Tb}/views/front?" in (b["view_info"]["front"]["url"]
                                                                                          or ""), True)
        check("[5] tab front current", fresh(b, "front"), ("current", ""))
        check("[5] back renderable now", b["view_info"]["back"]["blocked"], "")
        r = client.post(f"/characters/{char}/outfit-bodies/{B0}/views/back/regenerate", headers=ADMIN)
        check("[5] back run accepted", r.status_code, 202)
        check("[5] back run ended", wait_for(lambda: not outfit_bodies._active, timeout=120), True)
        b = tab_body(B0)
        check("[5] back run ok", (b["last_run"] or {}).get("ok"), True)
        check("[5] draft + fit jobs", [(x["stem"].split("_")[0], x["occasion"]) for x in renders[1:]][:2],
              [("tpose", "outfit_back_draft"), ("tpose", "outfit_back")])
        check("[5] draft prompt bald", "completely bald" in (renders[1]["prompt"] or ""), True)
        back_meta = json.loads(o1_back.with_suffix(".json").read_text())
        check("[5] back sidecar bald + Tb", (back_meta.get("bald"), back_meta.get("texture_signature")), (True, Tb))
        check("[5] no mesh run yet", meshes, [])

        # --- [6] ---------------------------------------------------------------------------------------------
        print("[6] Regenerate builds the successor")
        b = tab_body(B0)
        check("[6] regenerate possible", (b["can_regenerate"], b["regenerate_blocked"]), (True, None))
        r = client.post(f"/characters/{char}/outfit-bodies/{B0}/regenerate", headers=ADMIN)
        check("[6] regenerate accepted", r.status_code, 202)
        check("[6] run ended", wait_for(lambda: not outfit_bodies._active), True)
        check("[6] one mesh run", meshes, [(char, O1, True)])
        b = tab_body(B0)
        check("[6] last run ok", ((b["last_run"] or {}).get("kind"), (b["last_run"] or {}).get("ok")),
              ("regenerate", True))
        check("[6] worn outfit moved to Bb", rebuilt, [(char, Bb)])

        # --- [7] ---------------------------------------------------------------------------------------------
        print("[7] artefact GC")

        def verdict(key):
            nodes = [n for n in artefact_graph.analyse(char).nodes if n.kind == "body" and n.key == key]
            return (nodes[0].reachable, nodes[0].reason) if nodes else None
        check("[7] B0 kept while O1's model names it", (verdict(B0) or (None,))[0], True)
        recb = {**rec0, "body_id": Bb, "texture_signature": Tb, "bald": True,
                "views": {"front": sha(o1_front), "back": sha(o1_back)}}
        for kind in ("tpose", "tpose_back"):
            png(R / f"{kind}_{Bb}.png", (3, 3, 3))
            write_json(R / f"{kind}_{Bb}.json", {"outfit_body": recb, "base_signature": bsig, "bald": True})
        (M / f"{Bb}.glb").write_bytes(b"BODY-BALD")
        write_json(M / f"{Bb}.json", {"outfit_body": recb, "rig": "mixamo", "created_at": "2026-11-10T13:00:00+00:00"})
        new_model = {**o1_model, "texture_signature": Tb, "body_id": Bb, "body_sha256": sha(M / f"{Bb}.glb"),
                     "bald": True}
        write_json(M / f"{O1}.json", new_model)
        (M / f"{O1}.glb").write_bytes(b"OUTFIT-ON-BB")
        check("[7] new model current", base_body.outfit_body_stale(char, new_model), "")
        check("[7] B0 unreachable", (verdict(B0) or (None,))[0], False)
        check("[7] Bb reachable", verdict(Bb), (True, "texture of a live outfit (mesh mode)"))
        b = tab_body(Bb)
        check("[7] Bb not hair-stale", (b["hair_stale"], base_body.BAKED_HAIR in (b["freshness"] or {}).get("reason", "")),
              (None, False))

        # --- [8] ---------------------------------------------------------------------------------------------
        print("[8] the hair is fitted per bald body")
        hair_fit = cdir / "garments" / f"{hair_id}_aaaaaaaaaaaa.glb"
        hair_fit.parent.mkdir(parents=True, exist_ok=True)
        hair_fit.write_bytes(b"HAIR-FIT")
        asked = []
        garment_store.accepted_fit = lambda c, item_id, **kw: ((hair_fit, {"kind": "hair", "accepted": True})
                                                                if item_id == hair_id else None)

        def fake_body_fit(c, item_id, *, body_id, body_sha, base_fit, profile=None, build=False):
            asked.append((item_id, body_id, build))
            return {"fit": None, "low": None, "record": {}, "fsig": "aaaaaaaaaaaa", "pending": False,
                    "error": "stub"}
        garments.body_fit = fake_body_fit
        garment_assembly.body_fit_warning(char, new_model)
        check("[8] hair fitted on Bb", asked, [(hair_id, Bb, True)])

        # --- [9] ---------------------------------------------------------------------------------------------
        print("[9] no own hair -> unchanged")
        set_profile(equipped_mesh_pieces={})
        check("[9] rule off", base_body.outfit_body_bald(char), False)
        check("[9] O1's texture is T0 again",
              base_body._outfit_texture(char, o1_front, bsig=bsig, profile=profile())["tsig"], T0)
        check("[9] a bald view made under the rule", base_body.hair_rule_off(char, front_meta), "bald_body")
        check("[9] ... does not count", base_body.dressed_image(char, "front", O1, bsig), None)
        old_meta = {**front_meta}
        old_meta.pop("bald")
        check("[9] an old (not bald) view", base_body.hair_rule_off(char, old_meta), "")
        check("[9] old outfit model current again", base_body.hair_rule_off(char, o1_model), "")
        check("[9] undressed copy never judged", base_body.hair_rule_off(char, {**front_meta, "dressed": False}), "")
        set_profile(outfit_body_mode="retexture")
        check("[9] retexture: bald view", base_body.hair_rule_off(char, front_meta), "body_mode")
        check("[9] retexture: old view", base_body.hair_rule_off(char, old_meta), "")
        set_profile(equipped_mesh_pieces={"hair": hair_id})
        check("[9] retexture never bald even with own hair", base_body.outfit_body_bald(char), False)

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nOK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
