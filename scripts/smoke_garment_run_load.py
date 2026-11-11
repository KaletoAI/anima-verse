#!/usr/bin/env python3
"""The edit chain's load is ``retry_later``, never a failure record
(app/core/garments.py ``_run_locked``; spec docs/superpowers/specs/
2026-11-11-improvements-figure-pipeline-design.md § 5.5, anti-goal A6).

Usage:
    ./.venv/bin/python scripts/smoke_garment_run_load.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no world, no hub, no GPU, no server. The fixture
and the stubs are those of scripts/smoke_garment_clothing_images.py: Demo on
the base-body pipeline, the base views written as the BASE canvas, item D =
"Green Dress" (own_mesh, worn by Demo), ``character.run_rembg`` stubbed, the
renderer ``expression_regen.render_character_image`` and the image service
replaced per case. ``garment_source.ensure_current`` and ``run_edit_step``
up to the render call are REAL.

Every expectation is derived by hand from ``_run_locked``'s rules:

[L1] The renderer raises ``BackendBusyError`` on the worn front (the first
     view the clothing ``worn`` step renders) -> run_garment ->
     {ok False, step "worn", retry_later True}; the in-memory status
     ``garment_store.status(Demo, D)["failed"]`` carries the text (the
     Wardrobe shows it); nothing is persisted: ``garments.cached_failure``
     None, ``garment_store.chain_failure`` None.
[L2] ``MediaGenerationDisabled`` -> the same.
[L3] A ``GateRefused`` (every attempt of the worn front refused) -> no
     ``retry_later`` key, and the failure IS persisted: ``cached_failure``
     is a record with step "worn" and ``chain_failure`` the same (unchanged
     behaviour).
[L4] The failure record cleared, the cut-outs of both views in place, the
     mesher (``get_image_service().generate_mesh``) raises
     ``BackendBusyError`` inside ``garment_mesh.generate``'s attempt — which
     re-raises it as ``MeshAttemptFailed`` chained to the cause — ->
     run_garment(steps "mesh") -> {ok False, step "mesh", retry_later True},
     ``cached_failure`` None; ``garment_mesh.generate`` made exactly one
     attempt (no second attempt after an outright failure).

Fails on 193321cf: [L1] ``cached_failure`` is a record with step "worn"
(and the result has no ``retry_later``).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_garment_clothing_images import BASE, FRAGMENT, png, rembg_stub  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-run-load-") as tmp:
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

        from app.core import base_body, expression_regen, garment_assembly, garment_images, garments
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.imagegen.base import BackendBusyError, MediaGenerationDisabled
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        charmod.run_rembg = rembg_stub

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        did = inventory.add_item(name="Green Dress", category="outfit_piece", prompt_fragment=FRAGMENT,
                                 outfit_piece={"slots": ["top", "bottom"], "covers": ["legs"],
                                               "outfit_types": ["casual"], "own_mesh": True})["id"]
        check("inventory dress", inventory.add_to_inventory("Demo", did), True)
        check("equip dress", inventory.equip_piece("Demo", did, source="smoke")["status"], "ok")
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png(BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
        fsig = gs.garment_fsig("Demo", did)
        base = base_body.current_base("Demo")
        check("on the pipeline", base is not None, True)
        base_sha = base[1] if base else ""

        renders = []
        mode = {"raise": None}

        def renderer(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            renders.append((g["step"], g["view"], g["attempt"]))
            raise mode["raise"]

        expression_regen.render_character_image = renderer

        def persisted():
            return (garments.cached_failure("Demo", did),
                    gs.chain_failure("Demo", did, fsig, base_model_sha=base_sha))

        def failed_text():
            return ((gs.status("Demo", did)["failed"] or {}).get("step"),
                    (gs.status("Demo", did)["failed"] or {}).get("error"))

        print("[L1] BackendBusyError on the worn front")
        mode["raise"] = BackendBusyError("gpu busy")
        res = garments.run_garment("Demo", did)
        check("result", (res.get("ok"), res.get("fsig"), res.get("step"), res.get("retry_later")),
              (False, fsig, "worn", True))
        check("one render attempted", renders, [("worn", "front", 1)])
        check("status shows the text", failed_text(), ("worn", "gpu busy"))
        check("nothing persisted", persisted(), (None, None))
        check("no run left in flight", gs.status("Demo", did)["running_step"], None)

        print("[L2] MediaGenerationDisabled on the worn front")
        del renders[:]
        mode["raise"] = MediaGenerationDisabled("Media generation is disabled for this world")
        res = garments.run_garment("Demo", did)
        check("result", (res.get("ok"), res.get("step"), res.get("retry_later")), (False, "worn", True))
        check("status shows the text", failed_text(), ("worn", "Media generation is disabled for this world"))
        check("nothing persisted", persisted(), (None, None))

        print("[L3] a gate refusal is persisted as before")
        del renders[:]
        mode["raise"] = garment_images.GateRefused(
            "worn", "front", [{"attempt": 1, "ok": False, "reasons": ["nothing put on"]},
                              {"attempt": 2, "ok": False, "reasons": ["nothing put on"]}])
        res = garments.run_garment("Demo", did)
        check("result", (res.get("ok"), res.get("step"), "retry_later" in res), (False, "worn", False))
        cached, chain = persisted()
        check("cached_failure records the worn step", (cached or {}).get("step"), "worn")
        check("…the same record the store reads", (chain or {}).get("step"), "worn")

        print("[L4] BackendBusyError inside the mesh attempt")
        gs.clear_failure("Demo", did, fsig)
        check("record cleared", persisted(), (None, None))
        for v in gs.GARMENT_VIEWS:
            cut = gs.garment_path("Demo", did, fsig, "image", step="cutout", view=v)
            cut.parent.mkdir(parents=True, exist_ok=True)
            cut.write_bytes(png(BASE))
            gs.write_record(cut.with_suffix(".json"), {"accepted": True})
        meshes = []

        class BusyService:
            def generate_mesh(self, **kw):
                meshes.append(kw.get("occasion"))
                raise BackendBusyError("mesher busy")

        service.get_image_service = lambda: BusyService()
        res = garments.run_garment("Demo", did, steps="mesh")
        check("result", (res.get("ok"), res.get("step"), res.get("retry_later")), (False, "mesh", True))
        check("one mesh attempt", meshes, ["mesh_garment"])
        check("status shows the text", failed_text(), ("mesh", "mesher busy"))
        check("nothing persisted", persisted(), (None, None))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
