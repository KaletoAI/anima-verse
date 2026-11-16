#!/usr/bin/env python3
"""Own-mesh pieces next to a meshed shape under Ruling A119 (spec
docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md, replacing
the interim rule of Task 6 / rulings A11, A15 b): a flagged piece WITHOUT
its mesh (no accepted fit, or its chain refused) is LEFT OFF — never in an
interim body shape, never painted; no outfit render runs its chain first;
once its mesh is accepted the assembly grafts it onto the shape the figure
already stands on (no hub job, no render).

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

Expected, derived by hand from Ruling A119:

[1] K, under + shoes in the body, the jacket's chain refused ("worn — back
    refused"). The figure stands on bK = the shape of {shoes, under} (its
    dress text names no jacket); the render step renders nothing (bK has no
    views yet); the build renders bK's views only, ONE mesh + ONE rig job
    on bK, the outfit's views are copies (texture "", 0 worker runs, no
    texture stored). Figure: in_body [shoes, under], painted [], own [],
    left_out {jacket}. mesh_items: intended [jacket] (an own-mesh piece left
    off stays intended), effective [], unpainted [jacket], missing {jacket},
    warnings []. outfit_info ready, no assembly, Wardrobe jacket painted
    False / not in the body, mesh_items_missing [jacket].
[2] Retexture mode (under + shoes painted), the jacket still refused: K
    stale "figure"; build: 2 image jobs, 1 worker run, no mesh/rig job, on
    the plain body with a texture; the jacket left off (unpainted [jacket]).
[3] Mesh mode again: bK stored -> 0 image / mesh / rig jobs, 0 worker
    runs; K on bK, texture "".
[4] The jacket accepted (run_garment): 0 image / mesh / rig jobs, 0 worker
    runs; the Build asked ("piece_ready"), no T-pose pass; the automatic
    Build has no shape / texture step; running it: 0 jobs, ONE body fit
    (jacket on bK), the assembly grafts the jacket, bK untouched; delivered
    on bK with own [jacket], nothing left off; ready, no warning,
    mesh_items_missing []; Wardrobe jacket fitted.
[5] vest in_body -> L: render step 0 (shape bOld unbuilt, pieces left off),
    ONE mesh + ONE rig job on bOld (its dress text has the vest), texture "".
    The vest -> painted (signature stays sigL): L stale "figure"; rebuilt on
    bK (the shape of under + shoes, stored since [1]): 2 image jobs, 1 worker
    run, no mesh/rig job, a texture of its own. Artefact GC (explicit): bOld
    an orphan, its files gone; bK stays.
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
        # Ruling A104 (smoke_outfit_reference_auto.py): these checks pin the dressed views WITHOUT an outfit
        # full-body reference — no automatic generation before the front.
        from app.core import full_body_reference as _fbr
        _fbr.auto_due = lambda *_a, **_k: False
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

        def run_locked(character_name, item, kind, wanted, view, force, state=None, only=False):
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
        from app.core import view_composite

        def compose(base_view, draft, target, *, rule="outfit", background=None):
            """The composite stand-in (Task 11g; the real one: smoke_view_composite.py): the draft copied, ok."""
            Path(target).write_bytes(Path(draft).read_bytes())
            return {"version": view_composite.VERSION, "rule": rule, "ok": True, "reasons": [], "iou": 0.99,
                    "coverage": {"score": 0.9}}  # the current version (an older one is re-composited, Ruling A24)

        view_composite.compose = compose
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

        K = {"underwear_bottom": "under", "feet": "shoes", "top": "jacket"}
        refused = "worn — back refused"

        # --- [1] mesh mode, refused piece ---------------------------------------------
        print("[1] mesh mode: a refused own-mesh piece is left off (Ruling A119)")
        sig_k = wear(K)
        from app.core import figure
        check("in the body (wanted)", sorted(figure.wanted_figure("Demo").in_body), ["shoes", "under"])
        # No outfit render runs a garment chain any more (ruling A14) — the jacket's is run (and refused) here.
        check("K: the jacket's chain refused", garments.run_garment("Demo", "jacket").get("error"), "back refused")
        jobs, runs, hub, result = render_and_build()
        meta_k = meta_of(sig_k)
        t_k = meta_k.get("texture_signature")
        b_k = meta_k.get("body_id")
        text = front_text(b_k)
        check("K: the wanted shape's dress text, no jacket", ("plain grey underwear" in text,
                                                             "white sneakers" in text, "leather jacket" in text),
              (True, True, False))
        check("K: the outfit's front (a copy of the shape's) has no jacket", "leather jacket" in front_text(sig_k),
              False)
        stored_textures = sorted({p.stem.rsplit("_", 1)[-1] for p in (refs / "texture").glob("tpose_*.png")})
        check("K: render step 0 image jobs, ONE mesh + ONE rig job on bK, 0 worker runs",
              (result.get("ok"), jobs, hub, runs), (True, 0, [("mesh", b_k), ("rig", b_k)], 0))
        check("K: the build renders the shape's views only (the outfit's are copies)", stems(BUILD_RENDERS), [b_k])
        fig_k = meta_k.get("figure") or {}
        check("K: figure", {k: fig_k.get(k) for k in ("shape", "texture", "in_body", "painted", "own")},
              {"shape": b_k, "texture": "", "in_body": ["shoes", "under"], "painted": [], "own": []})
        check("K: the jacket left off", sorted((fig_k.get("left_out") or {})), ["jacket"])
        check("K: no texture (nothing painted), none stored", (t_k, stored_textures), ("", []))
        rec = {k: v for k, v in (meta_k.get("mesh_items") or {}).items() if k not in ("figure", "missing")}
        check("K: mesh_items record (A119)", rec,
              {"intended": ["jacket"], "effective": [], "unpainted": ["jacket"], "warnings": []})
        check("K: missing = left_out", sorted((meta_k.get("mesh_items") or {}).get("missing") or {}), ["jacket"])
        check("K: outfit_info ready", base_body.outfit_info("Demo")["status"], "ready")
        check("K: no assembly", (mdir / "assembled" / f"{sig_k}.glb").exists(), False)
        entry = wardrobe_entry("jacket")
        check("K: Wardrobe jacket not painted, not in the body", (entry.get("painted"), entry.get("in_body")),
              (False, None))
        check("K: missing mesh items", missing_items(sig_k), ["jacket"])

        # --- [2] retexture mode: under + shoes painted on the plain body, the jacket still left off ------
        print("[2] retexture mode: painted on the plain body, the jacket left off")
        set_mode("retexture")
        check("nothing in the body (wanted)", list(figure.wanted_figure("Demo").in_body), [])
        check("retexture: K stale (figure)", base_body.outfit_info("Demo").get("stale_reason"), "figure")
        jobs, runs, hub, result = render_and_build()
        meta_r = meta_of(sig_k)
        check("retexture: ok, 2 image jobs, 1 worker run, no mesh/rig job", (result.get("ok"), jobs, runs, hub),
              (True, 2, 1, []))
        check("retexture: on the plain body, a texture", (meta_r.get("body_id"),
                                                          base_body.is_texture_signature(
                                                              meta_r.get("texture_signature"))), (None, True))
        check("retexture: no jacket in the outfit's dress text", "leather jacket" in front_text(sig_k), False)
        check("retexture: the jacket left off", (meta_r.get("mesh_items") or {}).get("unpainted"), ["jacket"])

        # --- [3] mesh mode again: bK is stored -----------------------------------------------
        print("[3] mesh mode again: the stored shape bK, copied views, no job")
        set_mode("mesh")
        jobs, runs, hub, result = render_and_build()
        check("mesh: ok, 0 image jobs, 0 mesh/rig jobs, 0 worker runs", (result.get("ok"), jobs, BUILD_RENDERS,
                                                                       hub, runs), (True, 0, [], [], 0))
        meta_k = meta_of(sig_k)
        check("mesh: K on bK, no texture", (meta_k.get("body_id"), meta_k.get("texture_signature")), (b_k, ""))

        # --- [4] the piece is accepted later: assembly only --------------------------------
        print("[4] the jacket is accepted: bK kept, the assembly grafts it")
        body_k = base_body.outfit_body_path("Demo", b_k)
        body_before = sha(body_k)
        r0, w0, c0, t0 = len(RENDERS), len(WORKER), len(CHAIN), len(TRIGGERS)
        REQUESTS.clear()
        REFUSE.discard("jacket")
        ran = garments.run_garment("Demo", "jacket", force=True)
        garments.wait_idle(30)
        garment_assembly.wait_idle(30)
        check("accept: chain ok", ran.get("ok"), True)
        check("accept: 0 image jobs, 0 mesh/rig jobs, 0 worker runs",
              (len(RENDERS) - r0, [s for s in CHAIN[c0:] if s[0] in ("mesh", "rig")], len(WORKER) - w0),
              (0, [], 0))
        check("accept: the Build asked, no T-pose pass of the hook",
              (REQUESTS, TRIGGERS[t0:]), ([("Demo", "piece_ready")], []))
        from app.core import figure_build
        auto = figure_build._runnable(figure_build.plan("Demo", explicit=False), False)
        check("accept: the automatic Build neither renders nor meshes",
              [s.name for s in auto if s.name in ("shape", "texture")], [])
        for step in auto:
            check(f"accept: automatic step {step.name}", figure_build._RUNNERS[step.name]("Demo", step, False), "")
        garment_assembly.wait_idle(30)
        check("accept, built: 0 image jobs, 0 mesh/rig jobs, 0 worker runs",
              (len(RENDERS) - r0, [s for s in CHAIN[c0:] if s[0] in ("mesh", "rig")], len(WORKER) - w0),
              (0, [], 0))
        now = figure.delivered_figure("Demo")
        check("accept: delivered on bK, the jacket own", (now.shape, now.own, dict(now.left_out)),
              (b_k, ("jacket",), {}))
        check("accept, built: one body fit (the jacket on bK)", BODY_FITS, [("jacket", b_k)])
        assembled = mdir / "assembled" / f"{sig_k}.json"
        check("accept, built: the assembly grafts the jacket",
              sorted((json.loads(assembled.read_text()).get("garments") or {}) if assembled.is_file() else []),
              ["jacket"])
        check("accept, built: bK untouched", sha(body_k), body_before)
        info = base_body.outfit_info("Demo")
        check("accept, built: ready, no warning", (info["status"], info["warnings"]), ("ready", []))
        check("accept, built: missing mesh items", missing_items(sig_k), [])
        entry = wardrobe_entry("jacket")
        check("accept: Wardrobe jacket fitted", (entry.get("state"), entry.get("missing"), entry.get("painted")),
              ("fitted", None, False))

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
        check("L: the vest meshed into its own body", (result.get("ok"), jobs, hub, t_l, b_old != b_k,
                                                        "knitted green vest" in front_text(sig_l)),
              (True, 0, [("mesh", b_old), ("rig", b_old)], "", True, True))
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
        b_w = meta_l.get("body_id")
        check("vest painted: L rebuilt on bK (the shape of under + shoes, stored since [1]): 2 image jobs (the "
              "vest painted onto bK's views), 1 worker run, no mesh/rig job",
              (result.get("ok"), jobs, runs, hub, b_w), (True, 2, 1, [], b_k))
        check("vest painted: a texture of its own", base_body.is_texture_signature(t_l), True)
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
