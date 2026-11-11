#!/usr/bin/env python3
"""Footwear refit on a body change, a refused refit, freshness texts and the boot sweep — plan
2026-11-10-footwear-rigid-shoes Task 25 (P4), ``garments.after_base_model`` / ``garment_refit`` /
``garment_footwear.info`` / ``model_overview``.

Usage:
    ./.venv/bin/python scripts/smoke_footwear_refit.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` first) with the ``human`` package copied in;
no hub, no GPU, no Blender, no server. Stubs: ``service.get_image_service`` RAISES on any call (every service
method would go through it — 0 service calls is the whole point), ``model_refs.trigger_now`` and
``model_refs.schedule_outfit_render`` are recorders (a texture job), ``garment_assembly.schedule`` a recorder,
``refine.decimate_to`` a copy, ``footwear_fit.fit_pair`` counted. Fixture as in ``smoke_footwear_fit_step.py``:
character Demo (base-body pipeline on), item ``heels`` (own mesh, feet) with the closed flat clog of
``_footwear_fixtures.clog`` as its finished shoe source (every item step accepted — only the fit is ever run),
worn through ``inventory.equip_piece``; the base model =
``_footwear_fixtures.foot_body_glb()`` (sha B0), the rigid box foot the clog's cut gates pass.

[R1] Body change. The first run fits heels on B0 (accepted, 1 fit call). The base bytes are replaced by the same
     geometry re-exported (sha B1 ≠ B0): ``fit_state`` "stale", info freshness "Body changed — refit pending".
     ``after_base_model(Demo)`` → True; the FIFO runs the heels item ONCE, fit only: fit calls 2 in total, the
     service stub never reached, ``trigger_now`` / ``schedule_outfit_render`` not called; the record is accepted on
     B1 (``base_model_sha256`` B1, ``fit_version`` = ``FIT_VERSION["footwear"]``) and carries
     ``refitted.from_body_sha256`` = B0; ``fit_state`` "accepted"; info freshness "Refitted from the previous
     base". A refused SOURCE is never queued: with the heels' ``empty`` step recorded refused and the base changed
     once more (B1'), ``after_base_model`` → False, no fit call, ``cached_failure(Demo, heels)`` names ``empty``;
     the step restored.
[R2] Refused refit. A width cap of 1.00 on the wide-foot base (``foot_body_glb(0.10)``, sha B2) → the run is
     refused by ``slim_needed`` (fit_step [P7]'s hand value 0.2209 > 0.18). ``resolve_mesh_items(Demo, {feet:
     heels})`` → heels in ``missing`` with the gate text ("slim_needed …"), ``effective`` [], no
     ``MESH_ITEM_PAINTED`` warning, ``trigger_now`` not called; info: status "refused", freshness "Fit refused on
     this body: slim_needed …". The cap reset (None) and the base back on B1 → ``after_base_model`` refits
     (accepted again, refitted.from_body_sha256 = B2? no — the record under the fsig was last ACCEPTED on B1,
     the refusal never overwrote it: from_body_sha256 stays B0 … see below) — checked: after the cap reset the
     accepted record is still the B1 one (the refusal is a failure record beside it), ``fit_state`` "accepted".
[R3] Boot sweep. ``FIT_VERSION["footwear"]`` bumped by one (monkeypatched). The footwear fsig CARRIES the fit
     version (K2), so the current fsig F' ≠ F has no fit at all while the accepted F fit is of the older version:
     ``garment_refit.outdated_footwear_fits(Demo)`` = [(heels, F, F')] (``outdated_fits`` lists nothing — F is not
     the current fsig), ``sweep([Demo], pause=0)`` → {Demo: [heels]}, fit calls +1, 0 service calls, the record under
     F' has the bumped ``fit_version`` and is accepted on B1 (no ``refitted``: the body did not change); a second
     sweep → {} (nothing outdated). Restored afterwards (F current again, its fit accepted).
[R4] Overview: ``model_overview._garment_steps`` on a footwear entry with ``fit_state`` "accepted" / "stale" shows
     "fit accepted" / "fit stale" in the row detail (the Footwear step of the outfit model).
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


def png_bytes(colour) -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (64, 64), colour).save(buf, format="PNG")
    return buf.getvalue()


def repack(glb: bytes, *, generator: str) -> bytes:
    from app.core import glb_mesh
    parsed = glb_mesh._parse(glb, "Test")
    gltf = json.loads(json.dumps(parsed["gltf"]))
    gltf["asset"]["generator"] = generator
    return glb_mesh.pack_glb(gltf, parsed["bin"])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-refit-") as tmp:
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
        from app.core import (base_body, footwear_insole, footwear_source as fs, garment_assembly, garment_fit,
                              garment_footwear as gf, garment_refit, garment_store as gs, garments, glb_mesh,
                              model_overview, model_refs)
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        SERVICE, TEXTURE, SCHEDULED, FIT_CALLS = [], [], [], []

        def no_service(*a, **k):
            SERVICE.append("image_service")
            raise RuntimeError("a refit must never reach the image service")
        service.get_image_service = no_service
        model_refs.trigger_now = lambda *a, **k: TEXTURE.append(("trigger_now", a, k)) or False
        model_refs.schedule_outfit_render = lambda *a, **k: TEXTURE.append(("schedule_outfit_render", a, k))
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append(name) or True

        def decimate(src, target, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate
        from app.core import footwear_fit
        real_fit_pair = footwear_fit.fit_pair

        def counting_fit_pair(*a, **k):
            FIT_CALLS.append(1)
            return real_fit_pair(*a, **k)
        footwear_fit.fit_pair = counting_fit_pair

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        def shoe_item(item_id, colour):
            iid = inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                     prompt_fragment=f"black {item_id}",
                                     outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "own_mesh": True})["id"]
            folder = inventory._get_item_dir(iid, create=True)
            (folder / "image.png").write_bytes(png_bytes(colour))
            check(f"{iid} image", inventory.set_item_image(iid, "image.png"), True)
            inventory.add_to_inventory("Demo", iid)
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True, exist_ok=True)
            for n, c in (("upscaled.png", (1, 1, 1)), ("empty.png", (2, 2, 2)), ("cutout.png", (3, 3, 3))):
                (d / n).write_bytes(png_bytes(c))
            P, F = fx.clog()
            prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
            (d / "raw.glb").write_bytes(prepared)
            (d / "prepared.glb").write_bytes(prepared)
            insole = footwear_insole.analyse(prepared)
            gs.write_record(d / "insole.json", insole)
            steps = {s: {"accepted": True, "gates": {}, "backend": "", "routing": {}, "created_at": "x"}
                     for s in fs.ITEM_STEPS}
            steps["insole"]["version"] = footwear_insole.INSOLE_VERSION
            gs.write_record(d / "record.json", {"steps": steps})
            return iid, d
        heels, src = shoe_item("heels", (20, 20, 20))
        from app.models.character import get_character_profile
        check("Demo wears heels", inventory.equip_piece("Demo", heels, source="smoke")["status"], "ok")
        check("worn garments = [heels]", garments._worn_garments("Demo", get_character_profile("Demo") or {}), [heels])

        mdir = get_character_dir("Demo") / "model3d"
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")

        def write_base(data: bytes) -> str:
            (mdir / f"{bsig}.glb").write_bytes(data)
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            (mdir / "unrigged" / f"{bsig}.glb").write_bytes(data)
            return hashlib.sha256(data).hexdigest()
        base_glb = fx.foot_body_glb()
        B0 = write_base(base_glb)
        check("current base B0", base_body.current_base("Demo"), (bsig, B0))

        def wait_idle(timeout=120.0):
            t0 = time.time()
            while time.time() - t0 < timeout:
                state = garments.queue_state("Demo")
                if state["queue_running"] is None and not state["queue"]:
                    return True
                time.sleep(0.05)
            return False

        print("[R1] body change → after_base_model refits, fit only, 0 service calls")
        F = gs.garment_fsig("Demo", heels)
        res = garments.run_garment("Demo", heels)
        check("R1 first fit", (res.get("ok"), res.get("ran")), (True, ["fit"]))
        check("R1 fit calls 1", len(FIT_CALLS), 1)
        B1 = write_base(repack(base_glb, generator="another export"))
        check("R1 B1 != B0", B1 != B0, True)
        check("R1 stale", gf.fit_state("Demo", heels, F, B1), "stale")
        info = gf.info("Demo", heels, profile=get_character_profile("Demo") or {})
        check("R1 freshness before", (info["steps"]["fit"]["status"], info["steps"]["fit"]["freshness"]["reason"]),
              ("stale", "Body changed — refit pending"))
        TEXTURE.clear()   # equip_piece scheduled an outfit render at setup: not the refit's doing
        queued = garments.after_base_model("Demo")
        check("R1 after_base_model queued", queued, True)
        check("R1 queue idle again", wait_idle(), True)
        check("R1 fit calls 2 (one refit)", len(FIT_CALLS), 2)
        check("R1 0 service calls, no texture job", (SERVICE, TEXTURE), ([], []))
        rec = gs.read_record(gs.garment_path("Demo", heels, F, "fit").with_suffix(".json"))
        check("R1 record on B1, current fit version", (rec.get("accepted"), rec.get("base_model_sha256"), rec.get("fit_version")),
              (True, B1, garment_fit.FIT_VERSION["footwear"]))
        check("R1 refitted.from_body_sha256 = B0", (rec.get("refitted") or {}).get("from_body_sha256"), B0)
        check("R1 accepted now", gf.fit_state("Demo", heels, F, B1), "accepted")
        info = gf.info("Demo", heels, profile=get_character_profile("Demo") or {})
        check("R1 freshness after", (info["steps"]["fit"]["status"], info["steps"]["fit"]["freshness"]["reason"]),
              ("accepted", "Refitted from the previous base"))
        # a refused SOURCE is never queued by the trigger
        steps_rec = gs.read_record(src / "record.json")
        good_empty = dict(steps_rec["steps"]["empty"])
        steps_rec["steps"]["empty"] = {**good_empty, "accepted": False, "failure": fs.GATE,
                                       "error": "empty shoe refused — single_share 0.5 < 0.98"}
        gs.write_record(src / "record.json", steps_rec)
        write_base(repack(base_glb, generator="a third export"))
        n1 = len(FIT_CALLS)
        check("R1 refused source: cached_failure names empty", (garments.cached_failure("Demo", heels) or {}).get("step"), "empty")
        check("R1 refused source: after_base_model queues nothing", garments.after_base_model("Demo"), False)
        check("R1 refused source: no fit call", len(FIT_CALLS), n1)
        steps_rec["steps"]["empty"] = good_empty
        gs.write_record(src / "record.json", steps_rec)
        B1 = write_base(repack(base_glb, generator="another export"))
        check("R1 back on B1 accepted", gf.fit_state("Demo", heels, F, B1), "accepted")

        print("[R2] a refused refit: width cap 1.00 on the wide foot")
        B2 = write_base(fx.foot_body_glb(0.10))
        check("R2 cap set", gf.set_width_cap("Demo", heels, 1.00), True)
        F2 = gs.garment_fsig("Demo", heels)
        check("R2 fsig changed with the cap", F2 != F, True)
        TEXTURE.clear()
        res = garments.run_garment("Demo", heels)
        check("R2 refused by slim_needed", (res.get("ok"), res.get("step"), str(res.get("error") or "").startswith("fit refused — slim_needed")),
              (False, "fit", True))
        d = base_body.resolve_mesh_items("Demo", {"feet": heels})
        check("R2 heels missing with the gate", (d.get("effective"), list(d.get("missing") or {}),
                                                  "slim_needed" in str((d.get("missing") or {}).get(heels))), ([], [heels], True))
        check("R2 no MESH_ITEM_PAINTED, no texture job", ([w for w in d.get("warnings") or [] if "stays painted" in w], TEXTURE), ([], []))
        info = gf.info("Demo", heels, profile=get_character_profile("Demo") or {})
        check("R2 freshness refused", (info["steps"]["fit"]["status"], info["steps"]["fit"]["freshness"]["reason"].startswith("Fit refused on this body: slim_needed")),
              ("refused", True))
        check("R2 cap reset", gf.set_width_cap("Demo", heels, None), True)
        check("R2 fsig back", gs.garment_fsig("Demo", heels), F)
        info = gf.info("Demo", heels, profile=get_character_profile("Demo") or {})
        check("R2 after the reset: the cap-1.00 refusal is not shown beside the accepted fit",
              (info["steps"]["fit"]["status"], info["failed"]), ("accepted", None))
        write_base(repack(base_glb, generator="another export"))
        check("R2 back on B1: accepted (the refusal never overwrote the B1 record)", gf.fit_state("Demo", heels, F, B1), "accepted")

        print("[R3] boot sweep after a FIT_VERSION bump")
        old_version = garment_fit.FIT_VERSION["footwear"]
        garment_fit.FIT_VERSION["footwear"] = old_version + 1
        try:
            check("R3 stale by version (the F fit)", gf.fit_state("Demo", heels, F, B1), "stale")
            Fn = gs.garment_fsig("Demo", heels)
            check("R3 the current fsig carries the version", (Fn != F, gf.fit_state("Demo", heels, Fn, B1)), (True, "missing"))
            check("R3 outdated_fits lists nothing (F is not current)", garment_refit.outdated_fits("Demo"), [])
            check("R3 outdated_footwear_fits", garment_refit.outdated_footwear_fits("Demo"), [(heels, F, Fn)])
            n0 = len(FIT_CALLS)
            done = garment_refit.sweep(["Demo"], pause=0)
            check("R3 sweep refits heels", done, {"Demo": [heels]})
            check("R3 one fit call, 0 service calls", (len(FIT_CALLS) - n0, SERVICE), (1, []))
            rec = gs.read_record(gs.garment_path("Demo", heels, Fn, "fit").with_suffix(".json"))
            check("R3 record under F': bumped version, on B1, not 'refitted'", (rec.get("fit_version"), rec.get("base_model_sha256"), rec.get("refitted")), (old_version + 1, B1, None))
            check("R3 accepted under F'", gf.fit_state("Demo", heels, Fn, B1), "accepted")
            check("R3 second sweep nothing", garment_refit.sweep(["Demo"], pause=0), {})
        finally:
            garment_fit.FIT_VERSION["footwear"] = old_version

        print("[R4] overview row")
        rows = model_overview._garment_steps([{"item_id": heels, "name": "Heels", "kind": "footwear", "method": "shoe",
                                               "fsig": F, "current_fsig": F, "served": True, "fit_state": "accepted",
                                               "lift_m": 0.05, "cut_stats": {"removed_faces": 1, "bisected_faces": 2, "new_vertices": 3}}], [])
        check("R4 'fit accepted' in the Footwear row", ("Footwear", "fit accepted" in rows[0]["detail"]), (rows[0]["label"], True))
        rows = model_overview._garment_steps([{"item_id": heels, "name": "Heels", "kind": "footwear", "method": "shoe",
                                               "fsig": F, "current_fsig": F, "served": True, "fit_state": "stale"}], [])
        check("R4 'fit stale' in the row", "fit stale" in rows[0]["detail"], True)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
