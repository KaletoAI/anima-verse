#!/usr/bin/env python3
"""The two listers the ``fit_refit`` improvement adds to the boot sweep
(spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.2):
``garment_refit.outdated_footwear_sources`` with the sweep's insole
re-analysis, and ``outfit_bodies.stale_posture_bodies``.

Usage:
    ./.venv/bin/python scripts/smoke_fit_refit_listers.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server. The
fixture is scripts/smoke_footwear_refit.py's: character Demo on the pipeline,
item ``heels`` (own mesh, feet) worn, with the closed flat clog of
``_footwear_fixtures.clog`` as its finished shoe source (every item step
accepted) and the base model ``_footwear_fixtures.foot_body_glb()``; the
insole analysis (``footwear_source._step_insole`` → ``footwear_insole``) and
the footwear FIT are REAL. Stubs: ``service.get_image_service`` RAISES on
any call, ``model_refs.trigger_now`` / ``schedule_outfit_render`` and
``garment_assembly.schedule`` are recorders, ``refine.decimate_to`` a copy.
For the stale posture body: a stored body ``model3d/ob12345678.glb`` with a
sidecar that has no posture record (``stale_reason`` "missing"), the
character in mesh mode; ``match_posture`` / ``refit_body`` /
``rebuild_worn_on`` are recorders, the first writing the posture record.

Derived by hand from the listers' rules (versions read from the constants,
never pinned):

[R1] mesh done, the insole record's ``version`` = INSOLE_VERSION - 1 →
     ``outdated_footwear_sources(Demo) == [heels]``; after
     ``run_source(heels, steps=["insole"], force=True)`` → [] and the record
     reads the current version (the real analysis on the clog, accepted).
[R2] mesh NOT done (the mesh step dropped from the record while the insole
     is old) → [] — a source without its mesh is ``garment_fill``'s.
[R3] ``stale_posture_bodies(Demo)`` lists the fixture body; in retexture
     mode it lists nothing; ``match_stale_postures`` (recorders) returns the
     body, calls match → refit → rebuild once each, and the lister is empty
     afterwards (the recorder wrote the record).
[R4] The insole old again: ``refit_character(Demo)`` → [heels] with the
     service stub never called; the insole record is current again and a fit
     record under the current fsig is accepted (``garment_footwear.fit_state``
     "accepted", ``fit_version`` = FIT_VERSION["footwear"]); a second
     ``refit_character`` → [] (nothing outdated).

Fails on 193321cf: AttributeError — module garment_refit has no attribute
``outdated_footwear_sources``.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png_bytes(colour) -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (64, 64), colour).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fit-refit-listers-") as tmp:
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
                              garment_footwear as gf, garment_refit, garment_store as gs, glb_mesh, model3d,
                              model_refs, outfit_bodies)
        from app.core import outfit_body_posture as posture
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        SERVICE = []

        def no_service(*a, **k):
            SERVICE.append("image_service")
            raise RuntimeError("a refit must never reach the image service")
        service.get_image_service = no_service
        model_refs.trigger_now = lambda *a, **k: False
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: True

        def decimate(src, target, dst, **kw):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        heels = inventory.add_item(name="Heels", category="outfit_piece", item_id="heels",
                                   prompt_fragment="black heels",
                                   outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "own_mesh": True})["id"]
        folder = inventory._get_item_dir(heels, create=True)
        (folder / "image.png").write_bytes(png_bytes((20, 20, 20)))
        check("heels image", inventory.set_item_image(heels, "image.png"), True)
        inventory.add_to_inventory("Demo", heels)
        ssig = fs.current_ssig(heels)
        src = fs.source_dir(heels, ssig)
        src.mkdir(parents=True, exist_ok=True)
        for n, c in (("upscaled.png", (1, 1, 1)), ("empty.png", (2, 2, 2)), ("cutout.png", (3, 3, 3))):
            (src / n).write_bytes(png_bytes(c))
        P, F = fx.clog()
        prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
        (src / "raw.glb").write_bytes(prepared)
        (src / "prepared.glb").write_bytes(prepared)
        gs.write_record(src / "insole.json", footwear_insole.analyse(prepared))

        def write_steps(insole_version, *, mesh=True):
            steps = {s: {"accepted": True, "gates": {}, "backend": "", "routing": {}, "created_at": "x"}
                     for s in fs.ITEM_STEPS}
            steps["insole"]["version"] = insole_version
            if not mesh:
                steps.pop("mesh")
            gs.write_record(src / "record.json", {"steps": steps})

        old_version = footwear_insole.INSOLE_VERSION - 1
        write_steps(old_version)
        check("Demo wears heels", inventory.equip_piece("Demo", heels, source="smoke")["status"], "ok")

        mdir = get_character_dir("Demo") / "model3d"
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        base_glb = fx.foot_body_glb()
        (mdir / f"{bsig}.glb").write_bytes(base_glb)
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        (mdir / "unrigged" / f"{bsig}.glb").write_bytes(base_glb)
        B0 = hashlib.sha256(base_glb).hexdigest()
        check("current base", base_body.current_base("Demo"), (bsig, B0))

        def insole_version():
            return fs.step_record(heels, ssig, "insole").get("version")

        print("[R1] an outdated insole analysis is listed, the re-analysis clears it")
        check("listed", garment_refit.outdated_footwear_sources("Demo"), [heels])
        res = fs.run_source(heels, steps=["insole"], force=True)
        check("re-analysed", (res.get("ok"), res.get("ran")), (True, ["insole"]))
        check("record current", insole_version(), footwear_insole.INSOLE_VERSION)
        check("not listed any more", garment_refit.outdated_footwear_sources("Demo"), [])

        print("[R2] a source without its mesh is not this lister's")
        write_steps(old_version, mesh=False)
        check("not listed", garment_refit.outdated_footwear_sources("Demo"), [])
        write_steps(old_version)
        check("listed again with the mesh", garment_refit.outdated_footwear_sources("Demo"), [heels])

        print("[R3] stale posture bodies")
        bid = "ob12345678"
        parent = {"body_id": bid, "mode": "mesh", "version": 1, "base_signature": bsig}
        body_path = mdir / f"{bid}.glb"
        body_path.write_bytes(base_glb)
        model3d._publish_sidecar(body_path, {"rig": "mixamo", "outfit_body": parent, "signature": bid})
        check("retexture mode: nothing", outfit_bodies.stale_posture_bodies("Demo"), [])
        profile = get_character_profile("Demo")
        profile["outfit_body_mode"] = base_body.MESH_MODE
        check("mesh mode on", save_character_profile("Demo", profile), True)
        check("the stored body is stale (missing)", posture.is_stale("Demo", bid), True)
        check("listed", outfit_bodies.stale_posture_bodies("Demo"), [bid])
        calls = []

        def match_posture(name, body_id):
            calls.append(("match", body_id))
            meta = model3d._read_sidecar(body_path)
            meta["blender"] = {"posture_match": {"version": posture.POSTURE_MATCH_VERSION, "status": "applied",
                                                 "base_sha256": B0}}
            model3d._publish_sidecar(body_path, meta)
            return {"ok": True, "changed": True}

        with patch.object(outfit_bodies, "match_posture", match_posture), \
             patch.object(outfit_bodies, "refit_body", lambda name, body_id: calls.append(("refit", body_id)) or {}), \
             patch.object(outfit_bodies, "rebuild_worn_on", lambda name, body_id: calls.append(("rebuild", body_id)) or True):
            check("match_stale_postures returns the body", outfit_bodies.match_stale_postures("Demo"), [bid])
        check("match → refit → rebuild once each", calls, [("match", bid), ("refit", bid), ("rebuild", bid)])
        check("empty afterwards", outfit_bodies.stale_posture_bodies("Demo"), [])
        check("no service call", SERVICE, [])

        print("[R4] refit_character re-analyses the insole and fits, CPU only")
        fsig = gs.garment_fsig("Demo", heels)
        check("no fit yet", gf.fit_state("Demo", heels, fsig, B0), "missing")
        check("listed before", garment_refit.outdated_footwear_sources("Demo"), [heels])
        done = garment_refit.refit_character("Demo")
        check("refit_character → [heels]", done, [heels])
        check("insole record current", insole_version(), footwear_insole.INSOLE_VERSION)
        record = gs.read_record(gs.garment_path("Demo", heels, fsig, "fit").with_suffix(".json"))
        check("fit accepted on the base at the current fit version",
              (gf.fit_state("Demo", heels, fsig, B0), record.get("fit_version"), record.get("base_model_sha256")),
              ("accepted", garment_fit.FIT_VERSION["footwear"], B0))
        check("the service stub was never called", SERVICE, [])
        check("nothing left", (garment_refit.outdated_footwear_sources("Demo"), garment_refit.refit_character("Demo")),
              ([], []))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
