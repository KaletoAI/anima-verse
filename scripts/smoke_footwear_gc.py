#!/usr/bin/env python3
"""GC of the world shoe sources, footwear fits and the old edit-chain leftovers of feet items — plan
2026-11-10-footwear-rigid-shoes Task 26 (P4): ``footwear_source.collect``, ``outfit_cache_gc._garment_roots``
(footwear keeps its current fsig group and the served shoe fit only), ``artefact_graph.sweep_all`` and the item
delete route.

Usage:
    ./.venv/bin/python scripts/smoke_footwear_gc.py

Throwaway storage + instance (``paths.init`` first), the ``human`` package copied in; no hub, no GPU, no server.
Fixture: character Demo on the base-body pipeline, outfit body mode mesh; item ``heels`` (own mesh, feet) with the
closed flat clog of ``_footwear_fixtures.clog`` as its finished shoe source under its current ssig S (every item
step accepted); the base model ``_footwear_fixtures.foot_body_glb()``; Demo wears the heels. Synthetic bytes
everywhere else — only names and JSON sidecars matter to the GC.

[G1] An OLD CLOTHING edit-chain group of the heels (from before they were footwear): images/heels_ac8e461a88ec_
     worn_front.png + .json, images/heels_ac8e461a88ec_ghost_front.png + .json, prepared/heels_ac8e461a88ec.glb +
     .json, garments/heels_ac8e461a88ec.glb + .json (an ACCEPTED edit-chain fit on the current base — the newest
     accepted fit of that method, which used to keep it) and failed/heels_ac8e461a88ec.json; the heels' current
     footwear fit made by the real fit (``garments.run_garment``, CPU) under the current fsig F with its low tier.
     ``artefact_graph.collect(Demo, explicit=True)`` → every file of the old group is gone (9 files), the F fit, its
     record and its low tier stay; ``_garment_roots(Demo)`` keeps ``garment:heels_F`` and not
     ``garment:heels_ac8e461a88ec``.
[G2] Two ssig folders under footwear/heels: S (current, named by the kept fit) and "000000000000" (named by no fit,
     not current) with a file each; plus ``.x.tmp`` (an aborted write) and ``.staging`` aged 2 days and a fresh
     ``.y.tmp``. ``footwear_source.collect(dry_run=True)`` lists the stale folder and the two aged dot entries and
     deletes nothing; ``collect()`` removes them (3 entries), S and current.json and the fresh ``.y.tmp`` stay.
     A folder of an item that does not exist (footwear/item_gone/…) goes whole.
[G3] ``routes.inventory.delete_item_route(heels)`` → the item is gone, ``footwear/heels/`` is gone (every
     character's holder GC ran: no garments/heels_* file of Demo remains, F's fit included).
[G4] A second character Mira on the pipeline, mode mesh, wearing ``pumps`` (own mesh, feet, a source like the
     heels') in a worn outfit whose model stands on a LIVE outfit body B1 (texture T1 of the worn outfit's refs
     and model, as ``smoke_artefact_gc`` plants it) with a footwear body fit bodies/B1/pumps_F.glb + .json
     (accepted) and NO base fit file garments/pumps_F.glb: ``artefact_graph.collect(Mira, explicit=True)`` keeps the
     body fit ("fit of a kept garment on a live body" — the current fsig group is kept for a held item even
     without a base fit file).
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
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data))
    else:
        path.write_bytes(data)
    return path


def age(paths, seconds):
    t = time.time() - seconds
    for p in paths:
        os.utime(p, (t, t))


def png_bytes(colour) -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (64, 64), colour).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-gc-") as tmp:
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

        from app.blender import refine
        from app.core import (artefact_graph as ag, base_body, footwear_insole, footwear_source as fs,
                              garment_assembly, garment_store as gs, garments, glb_mesh, model_refs,
                              outfit_cache_gc as ocg)
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.routes import inventory as inv_routes

        def no_service(*a, **k):
            raise RuntimeError("never a service call here")
        service.get_image_service = no_service
        model_refs.trigger_now = lambda *a, **k: False
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: True

        def decimate(src, target, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate

        def person(name):
            human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                     "character_appearance": "slender", "outfit_body_mode": "mesh",
                     "body_slots": {"skin": {"tone": "olive"}}}
            check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
            touch(get_character_images_dir(name) / f"{name}_1.png", b"\x89PNG" + name.encode() * 8)
            prof = get_character_profile(name)
            prof["profile_image"] = f"{name}_1.png"
            check(f"profile {name}", save_character_profile(name, prof), True)
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)

        def shoe_item(item_id, colour, holder):
            iid = inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                     prompt_fragment=f"black {item_id}",
                                     outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "own_mesh": True})["id"]
            folder = inventory._get_item_dir(iid, create=True)
            (folder / "image.png").write_bytes(png_bytes(colour))
            check(f"{iid} image", inventory.set_item_image(iid, "image.png"), True)
            inventory.add_to_inventory(holder, iid)
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True, exist_ok=True)
            for n, c in (("upscaled.png", (1, 1, 1)), ("empty.png", (2, 2, 2)), ("cutout.png", (3, 3, 3))):
                (d / n).write_bytes(png_bytes(c))
            P, F_ = fx.clog()
            prepared = glb_mesh.static_glb(P, F_, np.zeros((len(P), 2)))
            (d / "raw.glb").write_bytes(prepared)
            (d / "prepared.glb").write_bytes(prepared)
            insole = footwear_insole.analyse(prepared)
            gs.write_record(d / "insole.json", insole)
            steps = {s: {"accepted": True, "gates": {}, "backend": "", "routing": {}, "created_at": "x"}
                     for s in fs.ITEM_STEPS}
            steps["insole"]["version"] = footwear_insole.INSOLE_VERSION
            gs.write_record(d / "record.json", {"steps": steps})
            check(f"{holder} wears {iid}", inventory.equip_piece(holder, iid, source="smoke")["status"], "ok")
            return iid, ssig, d

        def write_base(name, data):
            mdir = get_character_dir(name) / "model3d"
            (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
            bsig = base_body.base_signature(name)
            (mdir / f"{bsig}.glb").write_bytes(data)
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            (mdir / "unrigged" / f"{bsig}.glb").write_bytes(data)
            R = get_character_dir(name) / "model_refs"
            touch(R / f"tpose_{bsig}.png"); touch(R / f"tpose_{bsig}.json", {"base_signature": bsig})
            touch(R / f"tpose_back_{bsig}.png"); touch(R / f"tpose_back_{bsig}.json", {"base_signature": bsig})
            return bsig, hashlib.sha256(data).hexdigest()

        person("Demo")
        heels, S, src = shoe_item("heels", (20, 20, 20), "Demo")
        bsig, base_sha = write_base("Demo", fx.foot_body_glb())
        G = get_character_dir("Demo") / "garments"

        print("[G1] the old clothing edit-chain group of the heels goes, the footwear fit stays")
        F = gs.garment_fsig("Demo", heels)
        res = garments.run_garment("Demo", heels)
        check("G1 footwear fit accepted", (res.get("ok"), res.get("ran")), (True, ["fit"]))
        fit = gs.garment_path("Demo", heels, F, "fit")
        low = gs.garment_path("Demo", heels, F, "low")
        check("G1 fit + low on disk", (fit.is_file(), fit.with_suffix(".json").is_file(), low.is_file()), (True, True, True))
        OLD = "ac8e461a88ec"
        old_files = [touch(G / "images" / f"heels_{OLD}_worn_front.png", b"png"),
                     touch(G / "images" / f"heels_{OLD}_worn_front.json", {"accepted": True}),
                     touch(G / "images" / f"heels_{OLD}_ghost_front.png", b"png"),
                     touch(G / "images" / f"heels_{OLD}_ghost_front.json", {"accepted": True}),
                     touch(G / "prepared" / f"heels_{OLD}.glb"),
                     touch(G / "prepared" / f"heels_{OLD}.json", {"accepted": True}),
                     touch(G / f"heels_{OLD}.glb"),
                     touch(G / f"heels_{OLD}.json", {"accepted": True, "kind": "clothing", "method": "edit_chain",
                                                     "item_id": heels, "fsig": OLD, "base_model_sha256": base_sha,
                                                     "body_id": bsig, "base_signature": bsig, "fit_version": 7}),
                     touch(G / "failed" / f"heels_{OLD}.json", {"step": "fit", "error": "x"})]
        age(old_files + [fit, fit.with_suffix(".json"), low], 3600)
        roots = ocg._garment_roots("Demo")
        check("G1 roots keep F, not the old group", (f"garment:heels_{F}" in roots[0], f"garment:heels_{OLD}" in roots[0]), (True, False))
        report = ag.collect("Demo", explicit=True, reason="smoke G1")
        check("G1 old group gone (9 files)", ([p.exists() for p in old_files], report["deleted_files"]), ([False] * 9, 9))
        check("G1 fit, record, low stay", (fit.is_file(), fit.with_suffix(".json").is_file(), low.is_file()), (True, True, True))

        print("[G2] world shoe sources: the stale ssig folder, aged dot entries, a vanished item's folder")
        stale = fs.source_dir(heels, "000000000000")
        touch(stale / "upscaled.png", b"png")
        aged = [touch(fs.item_dir(heels) / ".x.tmp" / "part", b"x"), touch(fs.item_dir(heels) / ".staging" / "raw.glb", b"x")]
        age([p.parent for p in aged] + aged, 2 * 24 * 3600)
        fresh = touch(fs.item_dir(heels) / ".y.tmp" / "part", b"x")
        gone_item = fs.root() / "item_gone" / "aaaaaaaaaaaa"
        touch(gone_item / "upscaled.png", b"png")
        dry = fs.collect(dry_run=True)
        check("G2 dry run lists, deletes nothing", (sorted(dry["removed"]), stale.is_dir(), gone_item.is_dir(), aged[0].exists()),
              (sorted([str(stale), str(aged[0].parent), str(aged[1].parent), str(fs.root() / "item_gone")]), True, True, True))
        done = fs.collect()
        check("G2 collect removes them", (sorted(done["removed"]) == sorted(dry["removed"]), stale.exists(), aged[0].exists(), aged[1].exists(), (fs.root() / "item_gone").exists()),
              (True, False, False, False, False))
        check("G2 S, current.json, the fresh .tmp stay", (src.is_dir(), (src / "prepared.glb").is_file(), fresh.exists()), (True, True, True))
        check("G2 roots named", done["roots"] >= 1, True)

        print("[G3] item delete → footwear/<item>/ and every holder's fits go")
        inv_routes.delete_item_route(heels)
        check("G3 item gone", inventory.get_item(heels), None)
        check("G3 footwear folder gone", fs.item_dir(heels).exists(), False)
        check("G3 no heels garment file of Demo", sorted(p.name for p in G.rglob(f"heels_*")), [])

        print("[G4] a footwear body fit on a live outfit body is kept without a base fit file")
        person("Mira")
        pumps, PS, psrc = shoe_item("pumps", (120, 20, 40), "Mira")
        mbsig, mbase_sha = write_base("Mira", fx.foot_body_glb())
        cdir = get_character_dir("Mira")
        M, R = cdir / "model3d", cdir / "model_refs"
        T1 = "tex111111111111"
        B1 = base_body.outfit_body_id(T1)
        pieces = dict((get_character_profile("Mira") or {}).get("equipped_pieces") or {})
        check("G4 Mira wears the pumps in feet", pieces.get("feet"), pumps)
        variant, token = mesh_variant("Mira", pieces), mesh_items_token("Mira", pieces)
        sig = mesh_signature(pieces, [], "Mira", variant, token)
        manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": variant, "mesh_token": token,
                    "texture_signature": T1, "base_signature": mbsig}
        for k in ("tpose", "tpose_back"):
            touch(R / f"{k}_{sig}.png", b"png"); touch(R / f"{k}_{sig}.json", manifest)
        touch(M / f"{sig}.glb"); touch(M / f"{sig}.json", {"pieces": pieces, "items": [], "mesh_variant": variant, "mesh_token": token,
                                                            "base_signature": mbsig, "base_model_sha256": mbase_sha, "texture_signature": T1,
                                                            "outfit_body_mode": "mesh", "body_id": B1, "body_sha256": "x", "rig": "mixamo"})
        tm = {"base_signature": mbsig, "texture_signature": T1}
        touch(R / "texture" / f"tpose_{T1}.png"); touch(R / "texture" / f"tpose_{T1}.json", tm)
        touch(M / "texture" / f"{T1}.glb"); touch(M / "texture" / f"{T1}.json", tm)
        rec = {"outfit_body": {"body_id": B1, "mode": "mesh", "texture_signature": T1, "base_signature": mbsig}}
        touch(R / f"tpose_{B1}.png"); touch(R / f"tpose_{B1}.json", rec)
        touch(M / f"{B1}.glb"); touch(M / f"{B1}.json", {**rec, "rig": "mixamo"})
        PF = gs.garment_fsig("Mira", pumps)
        bodyfit = touch(gs.garment_path("Mira", pumps, PF, "fit", body=B1))
        touch(bodyfit.with_suffix(".json"), {"accepted": True, "kind": "footwear", "method": "shoe", "item_id": pumps,
                                            "fsig": PF, "ssig": PS, "body_id": B1, "base_signature": mbsig, "fit_version": 4})
        check("G4 no base fit file", gs.garment_path("Mira", pumps, PF, "fit").exists(), False)
        age([bodyfit, bodyfit.with_suffix(".json")], 3600)
        analysis = ag.analyse("Mira", explicit=True)
        node = next((n for n in analysis.nodes if n.kind == "body_fit" and n.parents.get("item_id") == pumps), None)
        check("G4 body fit node reachable", (node is not None, node.reachable if node else None, node.reason if node else None),
              (True, True, "fit of a kept garment on a live body"))
        report = ag.collect("Mira", explicit=True, reason="smoke G4")
        check("G4 body fit kept", (bodyfit.is_file(), bodyfit.with_suffix(".json").is_file()), (True, True))
        check("G4 source of the pumps kept by the body fit", (fs.collect()["removed"], psrc.is_dir()), ([], True))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
