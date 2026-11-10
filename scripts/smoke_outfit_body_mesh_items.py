#!/usr/bin/env python3
"""Own-mesh pieces in outfit body mode mesh (ruling 2026-11-10): a flagged
piece WITHOUT an accepted fit is never painted (= meshed) into the outfit
body. The body is keyed and built from the really painted pieces (the dress
text leaves out EVERY flagged piece), the piece is missing from the outfit
model with a warning until its fit is accepted, and the acceptance only
assembles it onto the existing body. Retexture mode keeps painting it.

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
groups, GLB delivery identity. ``garments._run_locked``: an accepted base fit
(+ a prepared-mesh file the record names) per piece — except the pieces in
REFUSE, whose chain fails at step "worn" with "back refused" (persisted like
a real failure). [5] builds the old-rule model with the resolver of before
the ruling (no ``unpainted`` key) and without ``mesh_items_off_rule`` (that
check did not exist), then restores both. ``garments.fit_on_body``:
writes an accepted body fit (the quad grafted onto the body bytes) and
records the call. The resolver, dress text, tsig, texture store, outfit body
chain, staleness, assembly, Wardrobe status, Outfit body tab, overview and
artefact GC are REAL.

Fixture: Demo (human-roleplay, on the pipeline, side views OFF -> dressed
views front + back, ``outfit_body_mode: "mesh"``). Items: under
{[underwear_bottom] "plain grey underwear"}, shoes {[feet] "white
sneakers"}, jacket {[top], own_mesh, "a brown leather jacket"}, vest {[top],
own_mesh, "a knitted green vest"}. Outfits: K {under, shoes, jacket};
L {under, shoes, vest}.

Expected, derived by hand from the ruling (task 2026-11-10) and the outfit
body spec:

[1] Mesh mode, K, jacket refused: the jacket chain fails ("worn — back
    refused"). The dress text leaves the jacket out: the front sidecar's
    dress_text names "plain grey underwear" and "white sneakers", NOT
    "leather jacket". 3 image jobs (front edit, back draft, back fit), ONE
    mesh + ONE rig job, both on bK = outfit_body_id(tK), 0 worker runs. The
    model's mesh_items = {intended [jacket], effective [], unpainted
    [jacket], missing {jacket: "worn — back refused — Regenerate in the
    Wardrobe"}}. outfit_info: status ready, warnings contain
    "Jacket: own mesh not ready — not shown until its mesh is accepted
    (worn — back refused — Regenerate in the Wardrobe)"; no garment_warnings
    of that kind in the sidecar (judged live). No assembly (no fit).
    Wardrobe: jacket {painted False, missing True, reason "worn — back
    refused"}. Outfit body tab: bK's outfit row K has missing_mesh_items
    [{jacket, "Jacket", <the reason above>}]. Overview row mesh_items:
    warning, detail "missing own-mesh pieces: Jacket".
[2] Retexture mode, jacket still refused (unchanged rule P1): K stale
    (body_mode); the mesh-mode front is off-rule (the jacket belongs painted
    on) -> rendered again WITH the jacket: 3 image jobs, 1 worker run, 0
    mesh/rig jobs; dress_text names "leather jacket"; mesh_items has no
    "unpainted"; warnings = ["Jacket stays painted on: worn — back refused —
    Regenerate in the Wardrobe"] (MESH_ITEM_FAILED); Wardrobe: painted True,
    no "missing" key.
[3] Mesh mode again (jacket refused): K stale (body_mode); the retexture
    front painted the jacket -> off-rule -> rendered again without it: the
    texture store of tK holds front + back -> 0 image jobs; body bK is
    current -> 0 mesh/rig jobs, 0 worker runs; K stands on bK again.
[4] The jacket's chain is run explicitly and accepted (run_garment):
    after_mesh_item_ready assembles it onto bK: 0 image jobs, 0 mesh/rig
    jobs, 0 worker runs, ONE body fit (jacket on bK), assembled/<sigK>.glb
    carries garment jacket; K's model file and bK untouched (sha); K not
    stale (find_model3d finds it), dressed front still current; outfit_info
    warnings without the not-ready line; Wardrobe: missing False, state
    fitted; Outfit body tab: missing_mesh_items [].
[5] Old rule (a model built in mesh mode before the ruling): L built with
    the old resolver (no "unpainted": the refused vest painted in) -> tsig
    tL != tK, 3 image jobs, ONE mesh + ONE rig job on bOld =
    outfit_body_id(tL). With the new resolver: L stale ("outfit_body"),
    its dressed front off-rule; the rebuild leaves the vest out -> dress text
    = K's painted set -> tsig tK: 0 image jobs (store), 0 mesh/rig jobs, L
    stands on bK. Artefact GC (explicit): bOld is an orphan and its files
    (model3d/<bOld>.glb, unrigged/<bOld>.glb) are gone; bK stays.
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
                              glb_mesh, model3d, model_overview, model_refs, outfit_bodies, sync_topics)
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

        def run_locked(character_name, item, kind, wanted, view, force):
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
        extension_rig.rig_groups_for = lambda *a, **k: []
        extension_rig.resolved_extension_groups = lambda *a, **k: []
        extension_rig.extension_bone_names = lambda *a, **k: {}
        glb_delivery.delivery_path = lambda path, **kw: path
        sync_topics.changed_at = lambda *a, **k: None
        model_refs.trigger_now = lambda *a, **k: None
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

        def set_mode(mode):
            stored = get_character_profile("Demo")
            stored["outfit_body_mode"] = mode
            save_character_profile("Demo", stored)
            return base_body.outfit_body_mode("Demo")

        check("mode mesh", set_mode("mesh"), "mesh")

        def piece(item_id, slots, *, own_mesh=False):
            op = {"slots": list(slots), "covers": [], "outfit_types": ["casual"]}
            if own_mesh:
                op["own_mesh"] = True
            return inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=FRAG[item_id], outfit_piece=op)["id"]

        check("items", [piece("under", ["underwear_bottom"]), piece("shoes", ["feet"]),
                        piece("jacket", ["top"], own_mesh=True), piece("vest", ["top"], own_mesh=True)],
              ["under", "shoes", "jacket", "vest"])
        for item in FRAG:
            inventory.add_to_inventory("Demo", item)

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
            return r1 - r0, len(WORKER) - w0, [s for s in CHAIN[c0:] if s[0] in ("mesh", "rig")], result

        def meta_of(sig):
            return model3d._read_sidecar(mdir / f"{sig}.glb")

        def front_text(sig):
            return str(base_body._ref_sidecar(refs / f"tpose_{sig}.png").get("dress_text") or "")

        def wardrobe_entry(item_id):
            return garment_set.wardrobe("Demo")["items"].get(item_id) or {}

        def tab_row(body_id, sig):
            for body in outfit_bodies.info("Demo")["bodies"]:
                if body.get("body_id") == body_id:
                    for row in body.get("outfits") or []:
                        if row.get("signature") == sig:
                            return row
            return {}

        failed_reason = "worn — back refused — Regenerate in the Wardrobe"
        not_ready = f"Jacket: own mesh not ready — not shown until its mesh is accepted ({failed_reason})"
        K = {"underwear_bottom": "under", "feet": "shoes", "top": "jacket"}

        # --- [1] mesh mode, refused piece ---------------------------------------------
        print("[1] mesh mode: a refused own-mesh piece is left out of the body")
        sig_k = wear(K)
        jobs, runs, hub, result = render_and_build()
        meta_k = meta_of(sig_k)
        t_k = meta_k.get("texture_signature")
        b_k = base_body.outfit_body_id(t_k) if base_body.is_texture_signature(t_k) else None
        text = front_text(sig_k)
        check("K: dress text without the jacket", ("plain grey underwear" in text, "white sneakers" in text,
                                                   "leather jacket" in text), (True, True, False))
        check("K: ok, 3 image jobs, ONE mesh + ONE rig job on bK, 0 worker runs",
              (result.get("ok"), jobs, hub, runs), (True, 3, [("mesh", b_k), ("rig", b_k)], 0))
        check("K: mesh_items record", meta_k.get("mesh_items"),
              {"intended": ["jacket"], "effective": [], "warnings": [not_ready], "unpainted": ["jacket"],
               "missing": {"jacket": failed_reason}})
        info = base_body.outfit_info("Demo")
        check("K: outfit_info ready + warning", (info["status"], not_ready in info["warnings"]), ("ready", True))
        check("K: no recorded not-ready garment warning", [w for w in meta_k.get("garment_warnings") or []
                                                           if "own mesh not ready" in w], [])
        check("K: no assembly", (mdir / "assembled" / f"{sig_k}.glb").exists(), False)
        entry = wardrobe_entry("jacket")
        check("K: Wardrobe jacket", {k: entry.get(k) for k in ("painted", "missing", "reason")},
              {"painted": False, "missing": True, "reason": "worn — back refused"})
        check("K: Outfit body tab row", tab_row(b_k, sig_k).get("missing_mesh_items"),
              [{"item_id": "jacket", "name": "Jacket", "reason": failed_reason}])
        rows = model_overview.outfit_model_overview("Demo", mdir / f"{sig_k}.glb")[0]
        row = next((r for r in rows if r["id"] == "mesh_items"), {})
        check("K: overview row", (row.get("status"), row.get("detail")),
              ("warning", "missing own-mesh pieces: Jacket"))

        # --- [2] retexture mode unchanged -------------------------------------------------
        print("[2] retexture mode: the refused piece is painted on (rule P1)")
        set_mode("retexture")
        check("retexture: K stale (body_mode)", base_body.outfit_info("Demo").get("stale_reason"), "body_mode")
        jobs, runs, hub, result = render_and_build()
        meta_r = meta_of(sig_k)
        check("retexture: ok, 3 image jobs, 1 worker run, 0 mesh/rig jobs", (result.get("ok"), jobs, runs, hub),
              (True, 3, 1, []))
        check("retexture: dress text paints the jacket", "leather jacket" in front_text(sig_k), True)
        check("retexture: record without unpainted", "unpainted" in (meta_r.get("mesh_items") or {}), False)
        check("retexture: warning painted on", base_body.outfit_info("Demo")["warnings"],
              [base_body.MESH_ITEM_FAILED.format(item="Jacket", reason="worn — back refused")])
        entry = wardrobe_entry("jacket")
        check("retexture: Wardrobe jacket painted", (entry.get("painted"), "missing" in entry), (True, False))

        # --- [3] mesh mode again: the body of the painted pieces is reused ---------------
        print("[3] mesh mode again: store views + the same body, no job")
        set_mode("mesh")
        check("mesh: K stale (body_mode)", base_body.outfit_info("Demo").get("stale_reason"), "body_mode")
        jobs, runs, hub, result = render_and_build()
        check("mesh: ok, 0 image jobs, 0 mesh/rig jobs, 0 worker runs", (result.get("ok"), jobs, hub, runs),
              (True, 0, [], 0))
        meta_k = meta_of(sig_k)
        check("mesh: K on bK, tsig tK", (meta_k.get("body_id"), meta_k.get("texture_signature")), (b_k, t_k))
        check("mesh: dress text without the jacket", "leather jacket" in front_text(sig_k), False)

        # --- [4] the piece is accepted later: assembly only --------------------------------
        print("[4] the jacket is accepted: assembled onto bK, no body job")
        body_k = base_body.outfit_body_path("Demo", b_k)
        body_before, model_before = sha(body_k), sha(mdir / f"{sig_k}.glb")
        front_before = base_body.dressed_image("Demo", "front", sig_k, b1)
        r0, w0, c0 = len(RENDERS), len(WORKER), len(CHAIN)
        REFUSE.discard("jacket")
        ran = garments.run_garment("Demo", "jacket", force=True)
        garments.wait_idle(30)
        garment_assembly.wait_idle(30)
        check("accept: chain ok", ran.get("ok"), True)
        check("accept: 0 image jobs, 0 mesh/rig jobs, 0 worker runs",
              (len(RENDERS) - r0, [s for s in CHAIN[c0:] if s[0] in ("mesh", "rig")], len(WORKER) - w0),
              (0, [], 0))
        check("accept: one body fit (jacket on bK)", BODY_FITS, [("jacket", b_k)])
        assembled = mdir / "assembled" / f"{sig_k}.json"
        check("accept: assembly carries the jacket",
              sorted((json.loads(assembled.read_text()).get("garments") or {}) if assembled.is_file() else []),
              ["jacket"])
        check("accept: body + bare model untouched", (sha(body_k), sha(mdir / f"{sig_k}.glb")),
              (body_before, model_before))
        check("accept: K current, front current", (model3d.find_model3d("Demo", sig_k) is not None,
                                                   base_body.dressed_image("Demo", "front", sig_k, b1)),
              (True, front_before))
        info = base_body.outfit_info("Demo")
        check("accept: status ready, no not-ready warning",
              (info["status"], [w for w in info["warnings"] if "own mesh not ready" in w]), ("ready", []))
        entry = wardrobe_entry("jacket")
        check("accept: Wardrobe jacket", (entry.get("state"), entry.get("missing"), entry.get("painted")),
              ("fitted", False, False))
        check("accept: Outfit body tab row", tab_row(b_k, sig_k).get("missing_mesh_items"), [])

        # --- [5] a model of the old rule -> unreachable body -> GC ----------------------------
        print("[5] old rule: the vest meshed into a body; the new rule rebuilds L on bK, GC removes the old body")
        real_resolve = base_body.resolve_mesh_items

        def old_resolve(*a, **k):
            out = real_resolve(*a, **k)
            for key in ("unpainted", "missing"):
                out.pop(key, None)
            return out

        real_off_rule = base_body.mesh_items_off_rule
        base_body.resolve_mesh_items = old_resolve
        base_body.mesh_items_off_rule = lambda *a, **k: []  # the old code had no such check
        sig_l = wear({"underwear_bottom": "under", "feet": "shoes", "top": "vest"})
        jobs, runs, hub, result = render_and_build()
        meta_l = meta_of(sig_l)
        t_l = meta_l.get("texture_signature")
        b_old = base_body.outfit_body_id(t_l) if base_body.is_texture_signature(t_l) else None
        check("old L: vest painted into its own body", (result.get("ok"), jobs, hub, t_l != t_k,
                                                        "knitted green vest" in front_text(sig_l)),
              (True, 3, [("mesh", b_old), ("rig", b_old)], True, True))
        base_body.resolve_mesh_items = real_resolve
        base_body.mesh_items_off_rule = real_off_rule
        check("new rule: L stale (outfit_body)", (model3d.find_model3d("Demo", sig_l),
                                                  base_body.outfit_info("Demo").get("stale_reason")),
              (None, "outfit_body"))
        check("new rule: L's front off-rule", base_body.dressed_image("Demo", "front", sig_l, b1), None)
        jobs, runs, hub, result = render_and_build()
        meta_l = meta_of(sig_l)
        check("new rule: L rebuilt on bK, 0 image jobs, 0 mesh/rig jobs",
              (result.get("ok"), jobs, hub, meta_l.get("texture_signature"), meta_l.get("body_id")),
              (True, 0, [], t_k, b_k))
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
