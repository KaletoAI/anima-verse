#!/usr/bin/env python3
"""``garments.run_estimate`` — the hub cost of a plain garment run before it
runs (app/core/garments.py; spec docs/superpowers/specs/
2026-11-11-improvements-figure-pipeline-design.md § 6.1 / § 6.5).

Usage:
    ./.venv/bin/python scripts/smoke_garment_run_estimate.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no world, no hub, no GPU, no server. The records
are written by hand with ``garment_store.write_record`` (an image final +
``{accepted: True}``; a prepared mesh the same; the footwear source record's
``steps`` entries + their output files); ``garment_source.find_source`` is
patched where named. Nothing renders: the estimate only READS the step state
(``garments._done``).

Every number is derived by hand from the first-attempt table ``garments.HUB_JOBS``
(clothing worn 3 + ghost 2 + cutout 0 + mesh 1 + fit 0; hair edit chain
haired 2 + ghost 2 + cutout 0 + mesh 1 + fit 0; HairDeck hairdeck 1 + fit 0;
subtract haired 2 + mesh_source 1 + cut 0 + fit 0; footwear source (1 below
MIN_SIDE 1024, else 0) + empty 1 + cutout 0 + mesh 1 + insole 0 + fit 0):

[E1] Clothing D (own-mesh dress worn by Demo), nothing cached -> steps all 5,
     hub_jobs 3 + 2 + 0 + 1 + 0 = 6, note "worn 3 + ghost 2 + mesh 1",
     refit False.
[E2] worn + ghost + cutout accepted for both views (the ghost pair agrees:
     hem_t 0.65 front and back, |Δ| 0 <= 0.02) -> steps [mesh, fit],
     hub_jobs 1, note "mesh 1".
[E3] The prepared mesh accepted too, the fit missing -> steps ["fit"],
     hub_jobs 0, note "no hub job".
[E4] Hair H (ensure_hair_item), nothing cached, the world method patched per
     case: edit_chain -> 5 (haired 2 + ghost 2 + mesh 1, steps 5); hairdeck
     -> 1 (steps [hairdeck, fit]); subtract -> 3 (haired 2 + mesh_source 1,
     steps 4).
[E5] Footwear S (feet piece, own_mesh): item image 800 px (longer side <
     1024: the source step upscales) -> 1 + 1 + 0 + 1 + 0 + 0 = 3, steps all
     6; a 1200 px image -> 2 (the source step is free); source..mesh done
     under the current ssig (records + files by hand) and the insole missing
     -> steps [insole, fit], 0.
[E6] A second dress E with no images of its own; ``find_source`` patched to
     answer a source -> hub_jobs 0, refit True, steps all 5, the note names
     the full cost: "refit from the previous base; up to 6 if the refit is
     refused".
[E7] An unknown item -> hub_jobs None, the ValueError's text as the note; a
     character off the pipeline -> None, note "… is not on the base-body
     pipeline".

Fails on 193321cf: AttributeError — module ``garments`` has no attribute
``run_estimate``.
"""
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png_bytes(size: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (20, 20, 20)).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-run-estimate-") as tmp:
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

        from app.core import base_body, footwear_source, garment_assembly, garment_hair, garment_source, garments
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import save_character_profile
        garment_assembly.schedule = lambda *a, **k: False

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        check("create Off", save_character_profile("Off", dict(human), create_new=True), True)

        def dress(name):
            iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a green {name.lower()}",
                                     outfit_piece={"slots": ["top", "bottom"], "covers": ["legs"],
                                                   "outfit_types": ["casual"], "own_mesh": True})["id"]
            check(f"inventory {name}", inventory.add_to_inventory("Demo", iid), True)
            return iid

        did = dress("Dress")
        check("equip dress", inventory.equip_piece("Demo", did, source="smoke")["status"], "ok")

        def estimate(item):
            return garments.run_estimate("Demo", item)

        def brief(est):
            return (est["steps"], est["hub_jobs"], est["note"], est["refit"])

        print("[E1] clothing, nothing cached")
        check("full chain", brief(estimate(did)),
              (["worn", "ghost", "cutout", "mesh", "fit"], 6, "worn 3 + ghost 2 + mesh 1", False))

        print("[E2] worn + ghost + cutout accepted")
        fsig = gs.garment_fsig("Demo", did)
        for step in ("worn", "ghost", "cutout"):
            for view in gs.GARMENT_VIEWS:
                path = gs.garment_path("Demo", did, fsig, "image", step=step, view=view)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png_bytes(16))
                gs.write_record(path.with_suffix(".json"),
                                {"accepted": True, "attempt": 1, "gates": {"first": {"ok": True, "hem_t": 0.65}}})
        check("mesh + fit left", brief(estimate(did)), (["mesh", "fit"], 1, "mesh 1", False))

        print("[E3] prepared mesh accepted, fit missing")
        prepared = gs.garment_path("Demo", did, fsig, "prepared")
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_bytes(b"glb")
        gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
        check("fit left", brief(estimate(did)), (["fit"], 0, "no hub job", False))

        print("[E4] hair per method")
        hid = garment_hair.ensure_hair_item("Demo")
        with patch.object(garment_hair, "world_hair_method", return_value="edit_chain"):
            check("edit chain", brief(estimate(hid)),
                  (["haired", "ghost", "cutout", "mesh", "fit"], 5, "haired 2 + ghost 2 + mesh 1", False))
        with patch.object(garment_hair, "world_hair_method", return_value="hairdeck"):
            check("hairdeck", brief(estimate(hid)), (["hairdeck", "fit"], 1, "hairdeck 1", False))
        with patch.object(garment_hair, "world_hair_method", return_value="subtract"):
            check("subtract", brief(estimate(hid)),
                  (["haired", "mesh_source", "cut", "fit"], 3, "haired 2 + mesh_source 1", False))

        print("[E5] footwear")
        sid = inventory.add_item(name="Shoes", category="outfit_piece", prompt_fragment="black shoes",
                                 outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "own_mesh": True})["id"]
        check("inventory shoes", inventory.add_to_inventory("Demo", sid), True)
        folder = inventory._get_item_dir(sid, create=True)
        (folder / "image.png").write_bytes(png_bytes(800))
        check("shoes image set", inventory.set_item_image(sid, "image.png"), True)
        check("800 px: the source upscales", brief(estimate(sid)),
              (["source", "empty", "cutout", "mesh", "insole", "fit"], 3, "source 1 + empty 1 + mesh 1", False))
        (folder / "image.png").write_bytes(png_bytes(1200))
        check("1200 px: the source is free", brief(estimate(sid)),
              (["source", "empty", "cutout", "mesh", "insole", "fit"], 2, "empty 1 + mesh 1", False))
        ssig = footwear_source.current_ssig(sid)
        sdir = footwear_source.source_dir(sid, ssig)
        sdir.mkdir(parents=True, exist_ok=True)
        steps = {}
        for step in ("source", "empty", "cutout", "mesh"):
            for name in footwear_source._STEP_FILES[step]:
                (sdir / name).write_bytes(b"x")
            steps[step] = {"accepted": True, "gates": {}}
        gs.write_record(sdir / "record.json", {"steps": steps})
        check("source..mesh done, insole missing", brief(estimate(sid)), (["insole", "fit"], 0, "no hub job", False))

        print("[E6] a refit source")
        eid = dress("Evening Dress")
        with patch.object(garment_source, "find_source", return_value={"fsig": "abcdefabcdef", "bsig": "old"}):
            est = estimate(eid)
        check("refit", (est["steps"], est["hub_jobs"], est["refit"]),
              (["worn", "ghost", "cutout", "mesh", "fit"], 0, True))
        check("note names the full cost", est["note"],
              "refit from the previous base; up to 6 if the refit is refused")
        check("without a source the same piece costs 6", brief(estimate(eid)),
              (["worn", "ghost", "cutout", "mesh", "fit"], 6, "worn 3 + ghost 2 + mesh 1", False))

        print("[E7] unknown item / off the pipeline")
        est = garments.run_estimate("Demo", "no_such_item")
        check("unknown item", (est["steps"], est["hub_jobs"], "no garment" in est["note"], est["refit"]),
              ([], None, True, False))
        check("inventory Off", inventory.add_to_inventory("Off", did), True)
        est = garments.run_estimate("Off", did)
        check("off the pipeline", (est["hub_jobs"], est["note"]), (None, "Off is not on the base-body pipeline"))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
