#!/usr/bin/env python3
"""Own-mesh pieces next to a meshed shape (ruling 2026-11-10, reworked by
Task 6 of plan 2026-11-12-unified-worn-pieces — the interim rule, ruling 2):
a flagged piece is NEVER meshed into the shape — the shape is keyed and
built from the in-body pieces only — but while it has no fit it is SHOWN
PAINTED on the texture next to them ("Shown painted until its own mesh is
built"); its accepted fit then asks for the outfit's views again (the
texture changes: the piece is no longer painted) and the rebuild grafts it.
Replaced cases are marked "(was …)".

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_mesh_items.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process.

Stubs (as smoke_outfit_body_mesh, whose helpers it imports): the image
service (``generate_mesh`` / ``generate_rig`` — ONE HUB JOB each, recorded in
CHAIN; the rig writes a real rigged GLB so the assembly can graft onto it),
``expression_regen.render_character_image`` (ONE IMAGE JOB each),
``run_rembg``, ``body_retexture.retexture`` (ONE WORKER RUN each),
``model3d`` post-steps, ``collision.refresh``, ``build_lod``, no extension
groups, GLB delivery identity, ``model_refs.trigger_now`` a recorder
(TRIGGERS). ``garments._run_locked``: an accepted base fit (+ a
prepared-mesh file the record names) per piece — except the pieces in
REFUSE, whose chain fails at step "worn" with "back refused" (persisted like
a real failure). ``garments.fit_on_body``: writes an accepted body fit (the
quad grafted onto the body bytes) and records the call. The figure
resolver, dress texts, texture store, shape chain, staleness, assembly,
Wardrobe status, missing-items rule, overview and artefact GC are REAL.

Fixture: Demo (human-roleplay, on the pipeline, side views OFF -> dressed
views front + back). Items: under {[underwear_bottom] "plain grey
underwear"}, shoes {[feet] "white sneakers"}, jacket {[top], own_mesh, "a
brown leather jacket"}, vest {[top], own_mesh, "a knitted green vest"}.
Outfits: K {under, shoes, jacket}; L {under, shoes, vest}. "mesh mode" below
= under and shoes in mode in_body, "retexture mode" = both painted.

Expected, derived by hand from the rulings:

[1] K, under + shoes in the body, jacket refused (its chain fails "worn —
    back refused"). The render step comes before any shape is stored, so it
    renders for the figure delivered NOW: the plain body with under, shoes
    (interim "its body shape") and the jacket (interim "its own mesh")
    painted — 3 image jobs (front edit, back draft, back fit), texture tP.
    The build then renders the shape's own views (key bK, the in-body dress
    text: underwear + sneakers, NO jacket), meshes + rigs bK (ONE mesh + ONE
    rig job), and renders the outfit's views on bK with the jacket painted
    (texture tK) — the build's image jobs are for [bK, sigK] in that order —
    and paints tK on bK: 1 worker run (was 0: the jacket was left out).
    K's figure: shape bK, texture tK, in_body [shoes, under], painted
    [jacket], own [], interim {jacket: "Shown painted until its own mesh is
    built"}; the texture store holds tK and tP. mesh_items = {intended
    [jacket], effective [], unpainted [], missing {}, warnings ["Jacket stays
    painted on: worn — back refused — Regenerate in the Wardrobe"]} (+ the
    figure; was unpainted [jacket], missing {jacket}). outfit_info ready with
    that one warning. No assembly. Wardrobe jacket {painted True, no
    "missing", reason "worn — back refused"} (was painted False, missing).
    base_body.mesh_items_missing of K's model [] (was [jacket]; the removed outfit-body tab's row showed exactly
    that list). Overview row
    mesh_items ("warning", "painted on: Jacket").
[2] Retexture mode (both painted), jacket still refused: K stale "figure"
    (was "body_mode"); the figure now is tP on the plain body — its views are
    the ones [1]'s render step made: 0 image jobs (was 3), 1 worker run, 0
    mesh/rig jobs; dress text names the jacket; mesh_items has no "mode" and
    unpainted []; warnings = [MESH_ITEM_FAILED jacket]; Wardrobe painted True,
    no "missing" key.
[3] Mesh mode again (jacket refused): K stale "figure"; tK's views are
    stored -> 0 image jobs; bK current -> 0 mesh/rig jobs, 0 worker runs; K
    on bK with tK, the jacket painted on again (was: left out).
[4] The jacket's chain is run explicitly and accepted (run_garment): the
    figure now grafts it (a base fit, nothing refused on bK) and paints
    nothing, so K's texture changes: after_mesh_item_ready asks the Build
    ("piece_ready", recorded — Task 8 of plan 2026-11-12-unified-worn-pieces;
    the Build renders the outfit's views; was: TRIGGERS [(Demo, (tpose,))]),
    no T-pose pass of its own; during the run 0
    image jobs, 0 mesh/rig jobs, 0 worker runs, no body fit yet; K stale
    "figure", its front made for another figure (dressed_image None);
    Wardrobe {state fitted, painted False}. (Was: assembled at once, K
    current — the jacket had never been painted.) The rebuild: 0 image jobs
    (nothing painted — the outfit's views are copies of bK's), 0 worker
    runs, 0 mesh/rig jobs, ONE body fit (jacket on bK), the assembly carries
    the jacket; figure {shape bK, texture "", painted [], own [jacket],
    interim {}}; bK untouched and K's model = bK's bytes; ready, no warning;
    base_body.mesh_items_missing of K's model [].
[5] A piece moved out of the body (was: a model of the old rule that meshed
    a refused vest into its body): vest in_body -> L built: 3 image jobs,
    ONE mesh + ONE rig job on bOld (its in-body dress text has the vest, so
    another key than bK), texture "" != tK. The vest -> painted (the
    signature stays sigL): L stale "figure", its front made for another
    figure; the rebuild stands L on bK with the vest painted: 3 image jobs in
    the render step, none in the build, 1 worker run, 0 mesh/rig jobs, a
    texture of its own (!= tK). Artefact GC (explicit): bOld is an orphan,
    its files (model3d/<bOld>.glb, unrigged/<bOld>.glb) are gone; bK stays.
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
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = []
FRAG = {"under": "plain grey underwear", "shoes": "white sneakers", "jacket": "a brown leather jacket",
        "vest": "a knitted green vest"}
REFUSE = {"jacket", "vest"}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-body-mesh-items-") as tmp:
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
        import smoke_outfit_body_mesh as obm
        from app.core import (artefact_graph, base_body, body_retexture, collision, expression_regen,
                              extension_rig, garment_assembly, garment_fit, garment_set, garments, glb_delivery,
                              glb_mesh, model3d, model_overview, model_refs, sync_topics)
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        unrigged_bytes, rigged_bytes = chain.base_bodies((200, 160, 140))
        CHAIN, RENDERS, WORKER, BODY_FITS = [], [], [], []

        class FakeService:
            def generate_mesh(self, *, source_image_path, output_path, view_images=None, occasion="", **kw):
                CHAIN.append(("mesh", Path(output_path).stem))
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(unrigged_bytes)
                return {"ok": True, "path": output_path, "backend": "fake-mesh"}

            def generate_rig(self, *, mesh_path, output_path, rig, **kw):
                CHAIN.append(("rig", Path(mesh_path).stem))
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(rigged_bytes)
                return {"ok": True, "path": output_path, "backend": "fake-rig", "rig": rig}

        def run_locked(character_name, item, kind, wanted, view, force, state=None):
            item_id = item["id"]
            fsig = gs.garment_fsig(character_name, item_id)
            if item_id in REFUSE:
                return {"ok": False, "fsig": fsig, "step": "worn", "error": "back refused", "gates": {}}
            bsig = base_body.base_signature(character_name)
            rigged = (get_character_dir(character_name) / "model3d" / f"{bsig}.glb").read_bytes()
            digest = hashlib.sha256(rigged).hexdigest()
            fit = gs.garment_path(character_name, item_id, fsig, "fit")
            if gs.read_record(fit.with_suffix(".json")).get("base_model_sha256") == digest:
                return {"ok": True, "fsig": fsig, "ran": []}
            fit.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(glb_mesh.graft(rigged, obm.garment_quad(item_id), name=f"garment_{kind}_{item_id}",
                                           extras={"kind": kind, "item_id": item_id, "fsig": fsig}))
            prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"prepared " + item_id.encode())
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "base_signature": bsig,
                "base_model_sha256": digest, "fit_version": garment_fit.FIT_VERSION.get(kind),
                "inputs": {"prepared_sha256": sha(prepared)}})
            return {"ok": True, "fsig": fsig, "ran": ["worn", "ghost", "cutout", "mesh", "fit"]}

        def fit_on_body(character_name, item_id, *, body_id, base_fit, profile=None, schedule=True):
            path, record = base_fit
            fsig = gs.parse_name(Path(path))[1]
            kind = str(record.get("kind") or "clothing")
            body = base_body.outfit_body_path(character_name, body_id)
            out = gs.garment_path(character_name, item_id, fsig, "fit", body=body_id)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(glb_mesh.graft(body.read_bytes(), obm.garment_quad(item_id),
                                           name=f"garment_{kind}_{item_id}",
                                           extras={"kind": kind, "item_id": item_id, "fsig": fsig}))
            gs.write_record(out.with_suffix(".json"), {
                "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "body_id": body_id,
                "body_sha256": sha(body), "base_fit_sha256": sha(Path(path)),
                "fit_version": garment_fit.FIT_VERSION.get(kind)})
            BODY_FITS.append((item_id, body_id))
            return out

        def render(character_name, *, output_stem, equipped_pieces, equipped_items, **kw):
            from PIL import Image
            RENDERS.append(Path(output_stem).name)
            target = Path(str(output_stem) + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), obm.colour_of(f"{target.stem}{len(RENDERS)}")).save(target)
            profile = kw.get("mesh_input_profile") or get_character_profile(character_name)
            token = model_refs.mesh_items_token(character_name, equipped_pieces, profile)
            meta = {"prompt": kw.get("bare_prompt") or "", "equipped_pieces": equipped_pieces or {},
                    "equipped_items": equipped_items or [],
                    "mesh_variant": model_refs.mesh_variant(character_name, equipped_pieces, profile),
                    "created_at": f"2026-11-10T00:{len(RENDERS) // 60:02d}:{len(RENDERS) % 60:02d}+00:00",
                    **({"mesh_token": token} if token else {}), **(kw.get("sidecar_extra") or {})}
            target.with_suffix(".json").write_text(json.dumps(meta))
            return target

        def rembg(data, model="u2net", **kw):
            import io
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

        def retexture(glb_in, views, out_glb, *, proof, atlas, **kw):
            WORKER.append(sorted(views))
            Path(out_glb).write_bytes(Path(glb_in).read_bytes())
            return {}

        def recorder(name, result=None):
            def run(character_name, path, *a, **k):
                CHAIN.append((name, Path(path).stem))
                return result() if callable(result) else result
            return run

        garments._run_locked = run_locked
        garments.fit_on_body = fit_on_body
        expression_regen.render_character_image = render
        charmod.run_rembg = rembg
        body_retexture.retexture = retexture
        service.get_image_service = lambda: FakeService()
        model3d._auto_retexture = recorder("retexture")
        model3d._auto_normalize = recorder("normalize")
        model3d._extension_rig_once = recorder("extension", lambda: {"ok": True, "noop": True})
        collision.refresh = recorder("collision", False)
        model3d._attach_measurement = lambda *a, **k: None
        model3d._auto_lod_enabled = lambda: False
        model3d.maybe_auto_generate_for_outfit = lambda *a, **k: False
        # Task 8 (plan 2026-11-12-unified-worn-pieces): every hook is a Build request now — recorded, so no
        # automatic Build runs beside the measured producers.
        from _figure_build_fixtures import record_requests
        REQUESTS = record_requests()
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None
        TRIGGERS = []
        model_refs.trigger_now = lambda name, **k: TRIGGERS.append((name, tuple(k.get("kinds") or ())))
        model_refs.schedule_outfit_render = lambda name: None
        config._CONFIG.setdefault("base_body", {})["dressed_side_views"] = False

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "male", "age": 30, "height": 180,
                 "character_appearance": "lean",
                 "body_slots": {"skin": {"tone": "fair"}, "eyes": {"color": "grey"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(obm.png((50, 60, 70)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        def piece(item_id, slots, *, own_mesh=False):
            op = {"slots": list(slots), "covers": [], "outfit_types": ["casual"]}
            op["mesh_mode"] = "own_mesh" if own_mesh else "painted"
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=FRAG[item_id], outfit_piece=op)["id"]

        check("items", [piece("under", ["underwear_bottom"]), piece("shoes", ["feet"]),
                        piece("jacket", ["top"], own_mesh=True), piece("vest", ["top"], own_mesh=True)],
              ["under", "shoes", "jacket", "vest"])
        for item in FRAG:
            inventory.add_to_inventory("Demo", item)

        def set_mode(mode):
            """The fixture's painted pieces go in the body for "mesh", back to painted for "retexture"."""
            for item_id in ("under", "shoes"):
                op = dict(inventory.get_item(item_id)["outfit_piece"])
                op["mesh_mode"] = "in_body" if mode == "mesh" else "painted"
                inventory.update_item(item_id, {"outfit_piece": op})

        set_mode("mesh")

        def wear(pieces):
            stored = get_character_profile("Demo")
            stored["equipped_pieces"] = dict(pieces)
            save_character_profile("Demo", stored)
            return model_refs.current_outfit_state("Demo")[2]

        cdir = get_character_dir("Demo")
        refs = cdir / "model_refs"
        mdir = cdir / "model3d"
        refs.mkdir(parents=True, exist_ok=True)
        b1 = base_body.base_signature("Demo")
        from PIL import Image
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            im.putpixel((4, 4), obm.BASE_PX[v] + (255,))
            im.save(refs / f"{stem}.png")
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged_bytes)
        (mdir / f"{b1}.glb").write_bytes(rigged_bytes)
        (mdir / f"{b1}.json").write_text(json.dumps({
            "base": True, "rig": "mixamo", "signature": b1, "format": "glb", "source": "generated"}))

        def render_and_build():
            r0, w0, c0 = len(RENDERS), len(WORKER), len(CHAIN)
            model_refs.generate_model_ref_images("Demo", kinds=("tpose",))
            garments.wait_idle(30)
            r1 = len(RENDERS)
            result = model3d.generate_for_current_outfit("Demo")
            garment_assembly.wait_idle(30)
            BUILD_RENDERS[:] = RENDERS[r1:]
            return r1 - r0, len(WORKER) - w0, [s for s in CHAIN[c0:] if s[0] in ("mesh", "rig")], result

        BUILD_RENDERS = []

        def stems(names):
            """The keys the build's image jobs were rendered for (``tpose[_<view>]_<key>``), in order, once each."""
            out = []
            for name in names:
                key = name.rsplit("_", 1)[-1]
                if key not in out:
                    out.append(key)
            return out

        def meta_of(sig):
            return model3d._read_sidecar(mdir / f"{sig}.glb")

        def front_text(sig):
            return str(base_body._ref_sidecar(refs / f"tpose_{sig}.png").get("dress_text") or "")

        def wardrobe_entry(item_id):
            return garment_set.wardrobe("Demo")["items"].get(item_id) or {}

        def missing_items(sig):
            """What the removed outfit-body tab listed per outfit model as ``missing_mesh_items``."""
            return [item_id for item_id, _reason in base_body.mesh_items_missing("Demo", meta_of(sig))]

        painted_on = base_body.MESH_ITEM_FAILED.format(item="Jacket", reason="worn — back refused")
        K = {"underwear_bottom": "under", "feet": "shoes", "top": "jacket"}

        # --- [1] mesh mode, refused piece ---------------------------------------------
        print("[1] mesh mode: a refused own-mesh piece is left out of the body")
        sig_k = wear(K)
        from app.core import figure
        check("in the body", sorted(figure.wanted_figure("Demo").in_body), ["shoes", "under"])
        jobs, runs, hub, result = render_and_build()
        meta_k = meta_of(sig_k)
        t_k = meta_k.get("texture_signature")
        b_k = meta_k.get("body_id")
        text = front_text(b_k)
        check("K: the shape's dress text without the jacket", ("plain grey underwear" in text,
                                                               "white sneakers" in text, "leather jacket" in text),
              (True, True, False))
        check("K: the outfit's front paints the jacket (interim)", "leather jacket" in front_text(sig_k), True)
        stored_textures = sorted({p.stem.rsplit("_", 1)[-1] for p in (refs / "texture").glob("tpose_*.png")})
        t_p_plain = next((t for t in stored_textures if t != t_k), None)
        check("K: render 3 image jobs on the plain body, ONE mesh + ONE rig job on bK, 1 worker run",
              (result.get("ok"), jobs, hub, runs), (True, 3, [("mesh", b_k), ("rig", b_k)], 1))
        check("K: the build renders the shape's views, then the outfit's on it", stems(BUILD_RENDERS),
              [b_k, sig_k])
        fig_k = meta_k.get("figure") or {}
        check("K: figure", {k: fig_k.get(k) for k in ("shape", "texture", "in_body", "painted", "own", "interim")},
              {"shape": b_k, "texture": t_k, "in_body": ["shoes", "under"], "painted": ["jacket"], "own": [],
               "interim": {"jacket": figure.INTERIM_PAINTED.format(what=figure.WHAT_OWN_MESH)}})
        check("K: two textures stored, tK and the plain body's of the render step", (
            base_body.is_texture_signature(t_k), len(stored_textures), t_k in stored_textures), (True, 2, True))
        check("K: mesh_items record", {k: v for k, v in (meta_k.get("mesh_items") or {}).items() if k != "figure"},
              {"intended": ["jacket"], "effective": [], "unpainted": [], "missing": {}, "warnings": [painted_on]})
        info = base_body.outfit_info("Demo")
        check("K: outfit_info ready + warning", (info["status"], info["warnings"]), ("ready", [painted_on]))
        check("K: no assembly", (mdir / "assembled" / f"{sig_k}.glb").exists(), False)
        entry = wardrobe_entry("jacket")
        check("K: Wardrobe jacket", {k: entry.get(k) for k in ("painted", "missing", "reason")},
              {"painted": True, "missing": None, "reason": "worn — back refused"})
        check("K: missing mesh items", missing_items(sig_k), [])
        rows = model_overview.outfit_model_overview("Demo", mdir / f"{sig_k}.glb")[0]
        row = next((r for r in rows if r["id"] == "mesh_items"), {})
        check("K: overview row", (row.get("status"), row.get("detail")), ("warning", "painted on: Jacket"))

        # --- [2] retexture mode unchanged -------------------------------------------------
        print("[2] retexture mode: the refused piece is painted on (rule P1)")
        set_mode("retexture")
        check("nothing in the body", list(figure.wanted_figure("Demo").in_body), [])
        check("retexture: K stale (figure)", base_body.outfit_info("Demo").get("stale_reason"), "figure")
        jobs, runs, hub, result = render_and_build()
        meta_r = meta_of(sig_k)
        check("retexture: ok, 0 image jobs (the plain-body views of [1]), 1 worker run, 0 mesh/rig jobs",
              (result.get("ok"), jobs, BUILD_RENDERS, runs, hub), (True, 0, [], 1, []))
        check("retexture: on the plain body", ((meta_r.get("figure") or {}).get("shape"),
                                               meta_r.get("texture_signature")), (b1, t_p_plain))
        check("retexture: dress text paints the jacket", "leather jacket" in front_text(sig_k), True)
        check("retexture: nothing unpainted, no mode", ("mode" in (meta_r.get("mesh_items") or {}),
                                                        (meta_r.get("mesh_items") or {}).get("unpainted")), (False, []))
        check("retexture: warning painted on", base_body.outfit_info("Demo")["warnings"],
              [base_body.MESH_ITEM_FAILED.format(item="Jacket", reason="worn — back refused")])
        entry = wardrobe_entry("jacket")
        check("retexture: Wardrobe jacket painted", (entry.get("painted"), "missing" in entry), (True, False))

        # --- [3] mesh mode again: the body of the painted pieces is reused ---------------
        print("[3] mesh mode again: store views + the same body, no job")
        set_mode("mesh")
        check("mesh: K stale (figure)", base_body.outfit_info("Demo").get("stale_reason"), "figure")
        jobs, runs, hub, result = render_and_build()
        check("mesh: ok, 0 image jobs, 0 mesh/rig jobs, 0 worker runs", (result.get("ok"), jobs, hub, runs),
              (True, 0, [], 0))
        meta_k = meta_of(sig_k)
        check("mesh: K on bK, tsig tK", (meta_k.get("body_id"), meta_k.get("texture_signature")), (b_k, t_k))
        check("mesh: the jacket painted on bK again (interim)", "leather jacket" in front_text(sig_k), True)

        # --- [4] the piece is accepted later: assembly only --------------------------------
        print("[4] the jacket is accepted: assembled onto bK, no body job")
        body_k = base_body.outfit_body_path("Demo", b_k)
        body_before = sha(body_k)
        r0, w0, c0, t0 = len(RENDERS), len(WORKER), len(CHAIN), len(TRIGGERS)
        REQUESTS.clear()
        REFUSE.discard("jacket")
        ran = garments.run_garment("Demo", "jacket", force=True)
        garments.wait_idle(30)
        garment_assembly.wait_idle(30)
        check("accept: chain ok", ran.get("ok"), True)
        check("accept: 0 image jobs, 0 mesh/rig jobs, 0 worker runs, no body fit yet",
              (len(RENDERS) - r0, [s for s in CHAIN[c0:] if s[0] in ("mesh", "rig")], len(WORKER) - w0, BODY_FITS),
              (0, [], 0, []))
        check("accept: the Build asked (it renders the outfit's views), no T-pose pass of the hook",
              (REQUESTS, TRIGGERS[t0:]), ([("Demo", "piece_ready")], []))
        check("accept: K stale (figure), its front made for another figure",
              (model3d.find_model3d("Demo", sig_k), base_body.outfit_info("Demo").get("stale_reason"),
               base_body.dressed_image("Demo", "front", sig_k, b1)), (None, "figure", None))
        entry = wardrobe_entry("jacket")
        check("accept: Wardrobe jacket", (entry.get("state"), entry.get("missing"), entry.get("painted")),
              ("fitted", None, False))
        jobs, runs, hub, result = render_and_build()
        check("accept, rebuilt: 0 image jobs, 0 worker runs, 0 mesh/rig jobs",
              (result.get("ok"), jobs, BUILD_RENDERS, runs, hub), (True, 0, [], 0, []))
        check("accept, rebuilt: one body fit (jacket on bK)", BODY_FITS, [("jacket", b_k)])
        assembled = mdir / "assembled" / f"{sig_k}.json"
        check("accept, rebuilt: assembly carries the jacket",
              sorted((json.loads(assembled.read_text()).get("garments") or {}) if assembled.is_file() else []),
              ["jacket"])
        fig_k = meta_of(sig_k).get("figure") or {}
        check("accept, rebuilt: figure", {k: fig_k.get(k) for k in ("shape", "texture", "painted", "own", "interim")},
              {"shape": b_k, "texture": "", "painted": [], "own": ["jacket"], "interim": {}})
        check("accept, rebuilt: body untouched, the model = the body (nothing painted)",
              (sha(body_k), sha(mdir / f"{sig_k}.glb")), (body_before, body_before))
        info = base_body.outfit_info("Demo")
        check("accept, rebuilt: ready, no warning", (info["status"], info["warnings"]), ("ready", []))
        check("accept, rebuilt: missing mesh items", missing_items(sig_k), [])

        # --- [5] a model of the old rule -> unreachable body -> GC ----------------------------
        print("[5] the vest moved out of the body: L rebuilt on bK, GC removes the old body")
        def set_vest(mode):
            op = dict(inventory.get_item("vest")["outfit_piece"])
            op["mesh_mode"] = mode
            inventory.update_item("vest", {"outfit_piece": op})

        set_vest("in_body")
        sig_l = wear({"underwear_bottom": "under", "feet": "shoes", "top": "vest"})
        jobs, runs, hub, result = render_and_build()
        meta_l = meta_of(sig_l)
        t_l = meta_l.get("texture_signature")
        b_old = meta_l.get("body_id")
        check("L: the vest meshed into its own body", (result.get("ok"), jobs, hub, t_l != t_k, b_old != b_k,
                                                        "knitted green vest" in front_text(sig_l)),
              (True, 3, [("mesh", b_old), ("rig", b_old)], True, True, True))
        set_vest("painted")
        check("same signature", model_refs.current_outfit_state("Demo")[2], sig_l)
        check("vest painted: L stale (figure)", (model3d.find_model3d("Demo", sig_l),
                                             base_body.outfit_info("Demo").get("stale_reason")),
              (None, "figure"))
        check("vest painted: L's front made for another figure", base_body.dressed_image("Demo", "front", sig_l, b1),
              None)
        jobs, runs, hub, result = render_and_build()
        meta_l = meta_of(sig_l)
        t_l = meta_l.get("texture_signature")
        check("vest painted: L rebuilt on bK, 3 image jobs, 1 worker run, 0 mesh/rig jobs",
              (result.get("ok"), jobs, BUILD_RENDERS, runs, hub, meta_l.get("body_id")), (True, 3, [], 1, [], b_k))
        check("vest painted: a texture of its own", (base_body.is_texture_signature(t_l), t_l != t_k), (True, True))
        report = artefact_graph.collect("Demo", explicit=True, reason="smoke")
        orphans = {e.get("key") for e in report.get("orphans") or []}
        check("GC: bOld orphan, bK kept", (b_old in orphans, b_k in orphans), (True, False))
        check("GC: bOld files gone, bK stays",
              ((mdir / f"{b_old}.glb").exists(), (mdir / "unrigged" / f"{b_old}.glb").exists(), body_k.is_file()),
              (False, False, True))

    print()
    if FAILS:
        print(f"FAIL: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
