#!/usr/bin/env python3
"""Texture-body reuse (plan docs/superpowers/plans/2026-11-10-texture-body-reuse-and-layering.md,
Task 1, Review Focus 1-4): outfit models on the base-body pipeline share ONE
painted body per distinct texture content.

Usage:
    ./.venv/bin/python scripts/smoke_texture_body_reuse.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process.

Stubs (as smoke_garment_outfit): ``garments._run_locked`` writes an accepted
fit per own-mesh piece on the CURRENT base model sha (rigged base + one
grafted quad ``garment_clothing_<item>``); ``expression_regen.
render_character_image`` = a recorder (one entry = ONE IMAGE JOB) writing an
8x8 RGB PNG of ``colour_of(<stem name>)`` and the sidecar the real renderer
writes (``prompt`` = the bare prompt, equipped pieces/items, ``mesh_variant``,
``mesh_token``, ``sidecar_extra``); ``run_rembg`` = a 2 px transparent
border; ``body_retexture.retexture`` = a recorder (one entry = ONE WORKER
RUN) copying its input GLB (the unrigged base carrying the rigged base's
colour) to ``out``; post-steps no-ops (``_auto_retexture``,
``_attach_measurement``, ``_auto_extension_rig``, ``request_lod``), no
extension groups; ``base_body.outfit_variant`` = "covered" when a piece of
the set COVERED is worn, else "rigged" (the fixture declares no exposed-only
group, so the real rule would always say rigged). Assembly, signature rule,
dress text, store and GC are REAL.

Fixture: Demo (human-roleplay, profile image, on the pipeline, side views
OFF -> dressed views front + back), base images tpose[_<view>]_<B1> (8x8
RGBA), base models of smoke_garment_chain (unrigged + rigged, colour
(200, 160, 140)). Items: under {[underwear_bottom], "plain grey underwear"},
shoes {[feet], "white sneakers"}, dress {[top], covers [bottom], own_mesh,
"a long red dress"}, coat {[outer], own_mesh, "a green wool coat"}, scarf
{[neck], own_mesh, "a green wool scarf"}, skirt {[bottom], "a blue pleated
skirt"}. Outfits: A {under, shoes}; B = A + dress; C {dress}; D {} (nothing);
E = A + coat; E2 = A + coat + dress; F = A + scarf; G = A + skirt.

Expected, derived by hand from the plan's Global Constraints:

[1] The rule. texture_inputs(Demo, A, variant rigged) = {version 1,
    base_signature B1, base_variant "rigged", side_views False, dress_text
    {front, back}} — both texts name "plain grey underwear" and "white
    sneakers"; tsig = "tex" + sha256(canonical JSON: keys sorted,
    separators "," ":", UTF-8)[:12]. The bare body (C, D): texts {"front": "",
    "back": ""} -> written out below, hashed by hand. Another base signature
    or variant -> another tsig.
[2] Review Focus 1. A: generate_model_ref_images -> 3 image jobs (front edit,
    back draft, back fit); generate_for_current_outfit(Demo) -> 1 worker run,
    model3d/texture/<tA>.glb exists, the model names texture_signature tA,
    texture_reused False. B (dress own mesh, fit ok): 0 image jobs; its views
    tpose[_back]_<sigB> are byte-equal to A's, name tA, carry B's manifest
    (equipped pieces B, mesh_items effective [dress], mesh_token) and a draft
    drafts/tpose_back_<sigB>; build -> 0 worker runs, texture_reused True,
    the body file's bytes and mtime unchanged, B's base colour = A's,
    assembled/<sigB>.glb carries garment_clothing_dress, outfit_info ready.
[3] Mesh dress alone. C: 0 image jobs (base copies, dressed False, naming
    the bare tsig); build -> 0 worker runs, model dressed False, texture
    signature = the hand-hashed bare tsig. D (nothing worn) -> the SAME tsig
    and body file, 0 worker runs.
[4] Review Focus 2. dress flag OFF, B worn -> another outfit signature; 3 image
    jobs, the front prompt names "a long red dress"; tsig tBp != tA; 1 worker
    run. Flag on again. E (coat own mesh): 0 image jobs, 0 worker runs,
    texture tA — the old body stays reusable.
[5] Review Focus 3. COVERED = {coat}: E2's texture_variant is "covered", its
    tsig tE2 != tA although its dress text is A's; generate: 0 image jobs
    (views adopted by dress text); build -> 1 worker run (tA's rigged body is
    NOT reused), the body's sidecar wanted covered: base_variant "rigged" +
    covered_missing (the fixture has no covered model). COVERED = {}.
[6] Review Focus 4. Base model rewritten (colour (20, 120, 220), same B1):
    A's model is stale (outfit_info "stale"); generate -> 0 image jobs (the
    base IMAGES did not change); build -> 1 worker run, the body's
    base_model_sha256 = the new sha; B rebuilt -> 0 worker runs, B's base
    colour = the NEW colour (no outfit served a body of the old base). A new
    profile image moves the base signature: every texture group is stale in
    verify_cache (all name B1); the old image back -> B1 again.
[7] Adoption (Step 2). The store views of tA deleted and texture_signature /
    dress_text stripped from EVERY outfit view sidecar (= views rendered
    before the store): F (scarf own mesh): 0 image jobs — adopted because a
    front's recorded prompt is exactly the front edit of A's text; F's front
    and back are byte-equal to A's; the store holds tA's front + back again
    with dress_text; build -> 0 worker runs (tA's body is current). G (skirt
    painted): 3 image jobs (no false adoption).
[8] GC (a texture lives while a live outfit would paint it NOW —
    artefact_graph._current_textures). Models of A, B, E, F name tA; E2 tE2;
    C, D the bare tsig; Bp tBp; G tG. Current: tA, the bare tsig, tG, and tBp
    — B's dress fit lies on the base model from before [6] (the fixture's
    fits are not refitted), so a retexture build of B paints the dress again,
    B's own text = tBp's —, but NOT tE2: COVERED is {} again, so E2 would
    paint the "rigged" variant -> verify_cache: every texture group but one
    valid, stale exactly [texture:<tE2>]. Bp's model + views removed -> still
    exactly [texture:<tE2>] (B keeps tBp). purge_stale([tE2, tA]) removes
    exactly tE2's files, tA skipped.
[9] Overview: the outfit model of B has the row painted_body, status done,
    detail "<tA> · reused · shared with 4 outfits" (A, B, E, F).
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
BASE_PX = {"front": (200, 10, 10), "back": (10, 200, 10), "left": (10, 10, 200), "right": (200, 200, 10)}
FRAG = {"under": "plain grey underwear", "shoes": "white sneakers", "dress": "a long red dress",
        "coat": "a green wool coat", "scarf": "a green wool scarf", "skirt": "a blue pleated skirt"}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(rgb, size=8) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(out, "PNG")
    return out.getvalue()


def colour_of(name: str):
    d = hashlib.md5(name.encode()).digest()
    return d[0], d[1], d[2]


def hand_tsig(inputs) -> str:
    raw = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "tex" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def garment_quad(item_id: str):
    from app.core.glb_mesh import GarmentMesh
    P = np.array([[0.0, 1.0, 0.25], [0.1, 1.0, 0.25], [0.1, 1.1, 0.25], [0.0, 1.1, 0.25]])
    return GarmentMesh(positions=P, normals=None, uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float),
                       indices=np.array([[0, 1, 2], [0, 2, 3]]), joints=np.zeros((4, 4), np.int64),
                       weights=np.tile([1.0, 0, 0, 0], (4, 1)), joint_names=["mixamorig:Spine2"],
                       image=png(colour_of(item_id), 8), mime="image/png")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="texture-body-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
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

        import smoke_garment_chain as chain
        from app.core import (base_body, body_retexture, expression_regen, extension_rig, garments, glb_delivery,
                              glb_mesh, model3d, model_overview, model_refs, outfit_cache_gc, sync_topics)
        from app.core import garment_store as gs
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        # --- stubs -------------------------------------------------------------
        RENDERS, WORKER = [], []
        COVERED: set = set()

        def run_locked(character_name, item, kind, wanted, view, force):
            item_id = item["id"]
            fsig = gs.garment_fsig(character_name, item_id)
            bsig = base_body.base_signature(character_name)
            rigged = (get_character_dir(character_name) / "model3d" / f"{bsig}.glb").read_bytes()
            sha = hashlib.sha256(rigged).hexdigest()
            fit = gs.garment_path(character_name, item_id, fsig, "fit")
            if gs.read_record(fit.with_suffix(".json")).get("base_model_sha256") == sha:
                return {"ok": True, "fsig": fsig, "ran": []}
            fit.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(glb_mesh.graft(rigged, garment_quad(item_id), name=f"garment_{kind}_{item_id}",
                                           extras={"kind": kind, "item_id": item_id, "fsig": fsig}))
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "base_signature": bsig,
                "base_model_sha256": sha})
            return {"ok": True, "fsig": fsig, "ran": ["worn", "ghost", "cutout", "mesh", "fit"]}

        garments._run_locked = run_locked

        def rembg(data, model="u2net", **kw):
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                rgba = im.convert("RGBA")
            for x in range(8):
                for y in range(8):
                    if min(x, y) < 2 or max(x, y) > 5:
                        rgba.putpixel((x, y), (0, 0, 0, 0))
            out = io.BytesIO()
            rgba.save(out, "PNG")
            return out.getvalue()

        def render(character_name, *, output_stem, equipped_pieces, equipped_items, **kw):
            from PIL import Image
            RENDERS.append({"stem": Path(output_stem).name, "occasion": kw.get("occasion"),
                            "prompt": kw.get("bare_prompt") or ""})
            target = Path(str(output_stem) + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), colour_of(target.stem)).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            token = model_refs.mesh_items_token(character_name, equipped_pieces, profile)
            meta = {"prompt": kw.get("bare_prompt") or "", "equipped_pieces": equipped_pieces or {},
                    "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    "created_at": f"2026-11-10T00:00:{len(RENDERS):02d}+00:00",
                    **({"mesh_token": token} if token else {}), **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        def retexture(glb_in, views, out_glb, *, proof, atlas, **kw):
            WORKER.append(sorted(views))
            Path(out_glb).write_bytes(Path(glb_in).read_bytes())
            return {}

        real_variant = base_body.outfit_variant

        def variant(character_name, pieces, *, profile=None):
            if COVERED & set((pieces or {}).values()):
                return "covered"
            return real_variant(character_name, pieces, profile=profile)

        expression_regen.render_character_image = render
        charmod.run_rembg = rembg
        body_retexture.retexture = retexture
        base_body.outfit_variant = variant
        model3d._auto_retexture = lambda *a, **k: None
        model3d._attach_measurement = lambda *a, **k: None
        model3d._auto_extension_rig = lambda *a, **k: None
        model3d.request_lod = lambda name, path: False
        model3d.maybe_auto_generate_for_outfit = lambda *a, **k: False
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None
        model_refs.trigger_now = lambda *a, **k: None
        model_refs.schedule_outfit_render = lambda name: None
        config._CONFIG.setdefault("base_body", {})["dressed_side_views"] = False

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(png((50, 60, 70)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        def piece(item_id, slots, *, covers=(), own_mesh=False):
            op = {"slots": list(slots), "covers": list(covers), "outfit_types": ["casual"]}
            if own_mesh:
                op["own_mesh"] = True
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=FRAG[item_id], outfit_piece=op)["id"]

        check("items", [piece("under", ["underwear_bottom"]), piece("shoes", ["feet"]),
                        piece("dress", ["top"], covers=["bottom"], own_mesh=True),
                        piece("coat", ["outer"], own_mesh=True), piece("scarf", ["neck"], own_mesh=True),
                        piece("skirt", ["bottom"])], ["under", "shoes", "dress", "coat", "scarf", "skirt"])
        for item in FRAG:
            inventory.add_to_inventory("Demo", item)

        def flag(item_id, on):
            item = inventory.get_item(item_id)
            op = dict(item.get("outfit_piece") or {})
            op["own_mesh"] = on
            inventory.update_item(item_id, {"outfit_piece": op})

        def wear(pieces):
            stored = get_character_profile("Demo")
            stored["equipped_pieces"] = dict(pieces)
            save_character_profile("Demo", stored)
            return model_refs.current_outfit_state("Demo")[2]

        cdir = get_character_dir("Demo")
        refs = cdir / "model_refs"
        mdir = cdir / "model3d"
        store = refs / "texture"
        refs.mkdir(parents=True, exist_ok=True)
        b1 = base_body.base_signature("Demo")
        from PIL import Image
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            im.putpixel((4, 4), BASE_PX[v] + (255,))
            im.save(refs / f"{stem}.png")
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))

        def write_model(colour):
            unrigged, rigged = chain.base_bodies(colour)
            (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
            (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged)
            tmpf = mdir / f".{b1}.tmp"
            tmpf.write_bytes(rigged)
            os.replace(tmpf, mdir / f"{b1}.glb")
            (mdir / f"{b1}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": b1, "format": "glb", "source": "generated"}))

        write_model((200, 160, 140))

        def colour(path):
            from PIL import Image as _I
            data, _mime = base_body.base_color_image(Path(path).read_bytes())
            with _I.open(io.BytesIO(data)) as im:
                return im.convert("RGB").getpixel((0, 0))

        def nodes(path):
            return sorted(n for n in chain.node_names(Path(path).read_bytes()) if str(n).startswith("garment_"))

        def render_and_build(force_build=False):
            r0, w0 = len(RENDERS), len(WORKER)
            model_refs.generate_model_ref_images("Demo", kinds=("tpose",))
            garments.wait_idle(30)
            r1 = len(RENDERS)
            result = model3d.generate_for_current_outfit("Demo", force=force_build)
            return r1 - r0, len(WORKER) - w0, result

        def model_meta(sig):
            return model3d._read_sidecar(mdir / f"{sig}.glb")

        A = {"underwear_bottom": "under", "feet": "shoes"}

        # --- [1] the rule -----------------------------------------------------------
        print("[1] texture signature rule")
        inputs_a = base_body.texture_inputs("Demo", pieces=A, items=[], variant="rigged")
        texts = inputs_a.get("dress_text") or {}
        check("inputs keys", sorted(inputs_a), ["base_signature", "base_variant", "dress_text", "side_views",
                                                "version"])
        check("inputs fixed", (inputs_a["version"], inputs_a["base_signature"], inputs_a["base_variant"],
                               inputs_a["side_views"], sorted(texts)), (1, b1, "rigged", False, ["back", "front"]))
        check("texts name under + shoes", [all(f in texts.get(v, "") for f in (FRAG["under"], FRAG["shoes"]))
                                           for v in ("front", "back")], [True, True])
        t_a = base_body.texture_signature(inputs_a)
        check("tsig = hand hash", t_a, hand_tsig(inputs_a))
        bare_inputs = {"version": 1, "base_signature": b1, "base_variant": "rigged", "side_views": False,
                       "dress_text": {"front": "", "back": ""}}
        t_bare = hand_tsig(bare_inputs)
        check("bare inputs", base_body.texture_inputs("Demo", pieces={}, items=[], variant="rigged"), bare_inputs)
        check("other base -> other tsig", base_body.texture_signature({**inputs_a, "base_signature": "base00000000"})
              != t_a, True)
        check("other variant -> other tsig", base_body.texture_signature({**inputs_a, "base_variant": "covered"})
              != t_a, True)

        # --- [2] reuse -----------------------------------------------------------------
        print("[2] two outfits differing only in an own-mesh piece share one painted body")
        sig_a = wear(A)
        jobs, runs, result = render_and_build()
        check("A: 3 image jobs, 1 worker run, ok", (jobs, runs, result.get("ok")), (3, 1, True))
        body = mdir / "texture" / f"{t_a}.glb"
        check("A: body stored", body.is_file(), True)
        meta_a = model_meta(sig_a)
        check("A: model names tA, painted", (meta_a.get("texture_signature"), meta_a.get("texture_reused")),
              (t_a, False))
        body_sha, body_mtime = hashlib.sha256(body.read_bytes()).hexdigest(), body.stat().st_mtime_ns
        sig_b = wear({**A, "top": "dress"})
        check("B: another outfit signature", sig_b != sig_a, True)
        jobs, runs, result = render_and_build()
        check("B: 0 image jobs, 0 worker runs, ok", (jobs, runs, result.get("ok")), (0, 0, True))
        for kind in ("tpose", "tpose_back"):
            mine, theirs = refs / f"{kind}_{sig_b}.png", refs / f"{kind}_{sig_a}.png"
            check(f"B: {kind} = A's bytes", mine.is_file() and mine.read_bytes() == theirs.read_bytes(), True)
        front_b = json.loads((refs / f"tpose_{sig_b}.json").read_text())
        check("B: front sidecar", (front_b.get("texture_signature"), front_b.get("equipped_pieces"),
                                   (front_b.get("mesh_items") or {}).get("effective"), bool(front_b.get("mesh_token"))),
              (t_a, {**A, "top": "dress"}, ["dress"], True))
        check("B: draft copied", (refs / "drafts" / f"tpose_back_{sig_b}.png").is_file(), True)
        meta_b = model_meta(sig_b)
        check("B: model names tA, reused", (meta_b.get("texture_signature"), meta_b.get("texture_reused")),
              (t_a, True))
        check("B: body file untouched", (hashlib.sha256(body.read_bytes()).hexdigest(), body.stat().st_mtime_ns),
              (body_sha, body_mtime))
        check("B: same paint as A", colour(mdir / f"{sig_b}.glb"), colour(mdir / f"{sig_a}.glb"))
        assembled_b = mdir / "assembled" / f"{sig_b}.glb"
        check("B: assembly carries the dress", nodes(assembled_b) if assembled_b.is_file() else None,
              ["garment_clothing_dress"])
        check("B: outfit_info ready", base_body.outfit_info("Demo")["status"], "ready")

        # --- [3] mesh dress alone ------------------------------------------------------
        print("[3] mesh dress alone -> the bare base body")
        sig_c = wear({"top": "dress"})
        jobs, runs, result = render_and_build()
        front_c = json.loads((refs / f"tpose_{sig_c}.json").read_text())
        check("C: 0 jobs, 0 runs, base copy naming the bare tsig",
              (jobs, runs, result.get("ok"), front_c.get("dressed"), front_c.get("texture_signature")),
              (0, 0, True, False, t_bare))
        meta_c = model_meta(sig_c)
        check("C: model dressed False on the bare body", (meta_c.get("dressed"), meta_c.get("texture_signature")),
              (False, t_bare))
        check("C: bare body stored", (mdir / "texture" / f"{t_bare}.glb").is_file(), True)
        sig_d = wear({})
        jobs, runs, result = render_and_build()
        check("D: same bare body, 0 runs", (jobs, runs, model_meta(sig_d).get("texture_signature"),
                                            model_meta(sig_d).get("texture_reused")), (0, 0, t_bare, True))

        # --- [4] flag flip ---------------------------------------------------------------
        print("[4] own-mesh flag flipped -> new texture; the old body stays reusable")
        flag("dress", False)
        sig_bp = wear({**A, "top": "dress"})
        check("Bp: another outfit signature", sig_bp not in (sig_a, sig_b), True)
        r0 = len(RENDERS)
        jobs, runs, result = render_and_build()
        fronts = [r for r in RENDERS[r0:] if r["occasion"] == "outfit_front"]
        check("Bp: 3 jobs, 1 run", (jobs, runs, result.get("ok")), (3, 1, True))
        check("Bp: dress painted", bool(fronts) and FRAG["dress"] in fronts[0]["prompt"], True)
        t_bp = model_meta(sig_bp).get("texture_signature")
        check("Bp: new tsig", base_body.is_texture_signature(t_bp) and t_bp != t_a, True)
        flag("dress", True)
        check("flag on: B's key again", wear({**A, "top": "dress"}), sig_b)
        sig_e = wear({**A, "outer": "coat"})
        jobs, runs, result = render_and_build()
        check("E: 0 jobs, 0 runs, tA", (jobs, runs, model_meta(sig_e).get("texture_signature")), (0, 0, t_a))

        # --- [5] covered vs rigged ---------------------------------------------------------
        print("[5] same dress text, other base variant -> other body")
        COVERED.add("coat")
        e2 = {**A, "outer": "coat", "top": "dress"}
        check("E2: texture variant covered",
              base_body.texture_variant("Demo", e2, dressed=True, mesh={"intended": ["coat", "dress"]}), "covered")
        sig_e2 = wear(e2)
        jobs, runs, result = render_and_build()
        meta_e2 = model_meta(sig_e2)
        t_e2 = meta_e2.get("texture_signature")
        check("E2: 0 jobs (views adopted), 1 run, other tsig", (jobs, runs, result.get("ok"), t_e2 != t_a),
              (0, 1, True, True))
        e2_body = model3d._read_sidecar(mdir / "texture" / f"{t_e2}.glb")
        check("E2: body wanted covered, built rigged without one",
              ((e2_body.get("texture_inputs") or {}).get("base_variant"), e2_body.get("base_variant"),
               e2_body.get("covered_missing")), ("covered", "rigged", True))
        COVERED.clear()

        # --- [6] base model regenerated -----------------------------------------------------
        print("[6] base model regenerated -> no body of the old base is served")
        write_model((20, 120, 220))
        new_sha = hashlib.sha256((mdir / f"{b1}.glb").read_bytes()).hexdigest()
        wear(A)
        check("A: stale on the new base", base_body.outfit_info("Demo")["status"], "stale")
        jobs, runs, result = render_and_build()
        check("A: 0 jobs, 1 run", (jobs, runs, result.get("ok")), (0, 1, True))
        check("A: body on the new base", model3d._read_sidecar(body).get("base_model_sha256"), new_sha)
        new_colour = colour(mdir / f"{sig_a}.glb")
        wear({**A, "top": "dress"})
        jobs, runs, result = render_and_build()
        check("B: 0 jobs, 0 runs (new body reused)", (jobs, runs, result.get("ok")), (0, 0, True))
        check("B: new base colour", (colour(mdir / f"{sig_b}.glb"), model_meta(sig_b).get("base_model_sha256")),
              (new_colour, new_sha))
        check("new colour is the new base's", new_colour, (20, 120, 220))
        (images / "Demo_2.png").write_bytes(png((70, 60, 50), 16))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_2.png"
        save_character_profile("Demo", stored)
        b2 = base_body.base_signature("Demo")
        check("new profile image moves the base signature", b2 != b1, True)
        report = outfit_cache_gc.verify_cache("Demo")
        check("other base: every texture group stale", (report["textures"]["valid"],
                                                        report["textures"]["total"] > 0), (0, True))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        save_character_profile("Demo", stored)
        check("base signature restored", base_body.base_signature("Demo"), b1)

        # --- [7] adoption ---------------------------------------------------------------------
        print("[7] views recorded before the store are adopted by their dress text")
        for p in list(store.glob(f"*_{t_a}.*")) + list((store / "drafts").glob(f"*_{t_a}.*")):
            p.unlink()
        for sidecar in refs.glob("tpose*.json"):
            meta = json.loads(sidecar.read_text())
            if meta.pop("texture_signature", None) is not None or meta.pop("dress_text", None) is not None:
                meta.pop("dress_text", None)
                sidecar.write_text(json.dumps(meta))
        sig_f = wear({**A, "neck": "scarf"})
        jobs, runs, result = render_and_build()
        check("F: 0 jobs, 0 runs, tA", (jobs, runs, result.get("ok"), model_meta(sig_f).get("texture_signature")),
              (0, 0, True, t_a))
        for kind in ("tpose", "tpose_back"):
            check(f"F: {kind} = A's bytes",
                  (refs / f"{kind}_{sig_f}.png").read_bytes() == (refs / f"{kind}_{sig_a}.png").read_bytes(), True)
        check("store refilled with dress_text", [json.loads((store / f"{k}_{t_a}.json").read_text()).get("dress_text")
                                                 == texts[v] for k, v in (("tpose", "front"), ("tpose_back", "back"))
                                                 if (store / f"{k}_{t_a}.json").is_file()], [True, True])
        sig_g = wear({**A, "bottom": "skirt"})
        jobs, runs, result = render_and_build()
        check("G: 3 jobs (no false adoption)", (jobs, result.get("ok")), (3, True))

        # --- [8] GC ---------------------------------------------------------------------------
        print("[8] cache GC keeps referenced painted bodies")
        report = outfit_cache_gc.verify_cache("Demo")
        check("every texture group but tE2's valid", report["textures"]["valid"], report["textures"]["total"] - 1)
        check("only E2's texture stale (outdated)",
              [s for s in report["stale_signatures"] if s.startswith("texture:")], [f"texture:{t_e2}"])
        for p in list(mdir.glob(f"{sig_bp}.*")) + list(refs.glob(f"*_{sig_bp}.*")) \
                + list((refs / "drafts").glob(f"*_{sig_bp}.*")):
            p.unlink()
        report = outfit_cache_gc.verify_cache("Demo")
        stale = [s for s in report["stale_signatures"] if s.startswith("texture:")]
        check("Bp gone: B still paints tBp, only E2's texture stale", stale, [f"texture:{t_e2}"])
        files_e2 = [p for p in list((mdir / "texture").iterdir()) + list(store.iterdir())
                    + list((store / "drafts").iterdir()) if t_e2 in p.name]
        result = outfit_cache_gc.purge_stale("Demo", [f"texture:{t_e2}", f"texture:{t_a}"])
        check("purge removes E2's texture files only", (bool(files_e2), result["deleted_files"], result["skipped"],
                                                         any(p.exists() for p in files_e2), body.is_file()),
              (True, len(files_e2), 1, False, True))

        # --- [9] overview --------------------------------------------------------------------
        print("[9] overview row")
        overview = model_overview.outfit_model_overview("Demo", mdir / f"{sig_b}.glb")
        rows = {r["id"]: r for r in (overview[0] if overview else [])}
        row = rows.get("painted_body") or {}
        check("painted_body row", (row.get("status"), row.get("detail")),
              ("done", f"{t_a} · reused · shared with 4 outfits"))

    print()
    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("All texture-body reuse checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
