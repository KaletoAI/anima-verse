#!/usr/bin/env python3
"""Switching a piece off its own mesh warns what the cleanup will remove and what switching back costs (Ruling A63,
``artefact_graph.own_mesh_files`` behind ``GET /inventory/items/{item}/own-mesh-files``).

Usage:
    ./.venv/bin/python scripts/smoke_own_mesh_switch_warning.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server. Stubs: ``garment_assembly.schedule`` (nothing is assembled) and the image service (an
empty namespace — no backend is probed). Fingerprints (fsig / ssig) come from the real ``garment_store`` /
``footwear_source`` functions — the ones the cleanup calls.

THE RULE (A63). The cleanup is unchanged: an own-mesh outfit piece switched to ``painted`` / ``in_body`` is no
own-mesh kind any more, ``outfit_cache_gc._garment_roots`` keeps nothing of it, and its nodes go at the next collect
(footwear: its world shoe source too, at the next daily sweep). The count names exactly what the cleanup KEEPS now
and drops then; what is unreachable already is not counted (it goes whatever the mode). The cost K is
``garments.run_estimate`` forced from the chain's first step, summed over the characters for clothing (each makes
its own chain), the largest one for footwear (the shoe source is made once per item; the fit is CPU work).

FIXTURE (sizes in bytes; a record is JSON padded with spaces to its size; every file 2 days old)
  Demo and Bea: humans on the base-body pipeline, each with base refs + a base model (sha BASE_D / BASE_B).
  Demo's worn outfit sidecar names outfit body ob00000001 (record: current base, built_for the worn signature), so
  that body is live and a fit on it is judged by its garment group alone.
  dress: outfit piece {slots [top], own_mesh} (not closable: no ``outer`` slot), held by Demo AND Bea, worn by
    nobody. FD / FB = garment_fsig(Demo / Bea, dress).
    Demo KEPT: dress_FD.glb 400000, dress_FD.json 1000 (accepted on BASE_D), images/dress_FD_worn_front.png 300000,
               images/dress_FD_worn_front.json 1000, bodies/ob00000001/dress_FD.glb 250000      = 5 files, 952000
    Demo STALE: dress_OLD.glb 7000 + dress_OLD.json 1000 (OLD = 0a0a…, accepted False: neither current, served nor
               newest accepted)                                                                   = 2 files, 8000
    Bea  KEPT: dress_FB.glb 48000, dress_FB.json 1000 (accepted on BASE_B)                      = 2 files, 49000
  shoes: outfit piece {slots [feet], own_mesh} = footwear, held by Demo; item image 1024×1024 (>= MIN_SIDE, so the
    source step costs 0). S = current_ssig(shoes) (seed 0, no current.json); FS = garment_fsig(Demo, shoes).
    Demo KEPT: shoes_FS.glb 100000, shoes_FS.json 1000 (accepted on BASE_D, kind footwear, ssig S)
                                                                                                  = 2 files, 101000
    world KEPT: footwear/shoes/S/{record.json 1000, raw.glb 500000, prepared.glb 400000}         = 3 files, 901000
    world STALE: footwear/shoes/5a5a…/record.json 1000 (an ssig nobody names)
  tee:   outfit piece {slots [top], own_mesh}, held by Demo, NO files.
  scarf: outfit piece {slots [neck], painted}, held by Demo, old own-mesh files scarf_0b0b….{glb 5000, json 1000}
    left from before (unreachable already: a painted piece is no own-mesh kind).

EXPECTED, BY HAND
  HUB_JOBS clothing:edit_chain = worn 2 + ghost 2 + cutout 2 + mesh 1 + fit 0 = 7 per character;
  footwear:shoe = source 0 (image 1024 px) + empty 1 + cutout 0 + mesh 1 + insole 0 + fit 0 = 2.
[1] dress: files 5 + 2 = 7, bytes 952000 + 49000 = 1001000, hub_jobs 7 + 7 = 14, characters Bea (2, 49000, 7) and
    Demo (5, 952000, 7), world 0 files; mode own_mesh, kind clothing.
[2] shoes: files 2 + 3 = 5, bytes 101000 + 901000 = 1002000, hub_jobs max(2) = 2, characters Demo (2, 101000, 2),
    world 3 files 901000; kind footwear.
[3] tee: files 0, characters [] (no confirmation). scarf (painted): files 0, hub_jobs 0, mode painted, kind "" —
    painted ↔ in_body drops no own-mesh file (its old files are prunable already). Unknown item → LookupError; the
    route answers 404.
[4] The cleanup agrees. Before the switch, an explicit dry run per character lists none of the counted dress / shoes
    files and lists the 2 stale dress_OLD files (and the scarf's 2 old files); ``footwear_source.collect(dry_run)``
    removes only the stale ssig folder. After ``update_item(dress / shoes, mesh_mode painted)``: Demo's dry-run
    orphan files of dress = the 5 counted + the 2 stale, Bea's = her 2; Demo's orphans of shoes = its 2;
    ``own_mesh_files`` of both says 0 files. The footwear dry run alone still keeps ssig S — Demo's accepted shoe
    fit record names it until the character collect removes it; the daily sweep (``sweep_all``: characters first,
    then the shoe sources) therefore deletes dress 7 + Bea 2 + shoes 2 + scarf 2 + the whole footwear/shoes folder
    4 (3 counted + 1 stale) = 17 files, every counted file among them.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400]
          + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def write(path: Path, size: int, data: str = "") -> Path:
    """``data`` (a record) or filler, padded with spaces to exactly ``size`` bytes; 2 days old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (data or "x").encode("utf-8")
    assert len(body) <= size, (path, len(body), size)
    path.write_bytes(body + b" " * (size - len(body)))
    stamp = time.time() - 2 * 86400
    os.utime(path, (stamp, stamp))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="own-mesh-switch-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        world_cfg = paths.get_config_path()
        world_cfg.write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(world_cfg, instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)

        from fastapi import HTTPException
        from PIL import Image
        from app.core import artefact_graph, base_body, footwear_source, garment_assembly, garment_store as gs
        from app.core.model_refs import current_outfit_state
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        from app.routes.inventory import get_item_own_mesh_files_route
        garment_assembly.schedule = lambda *a, **k: False
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()   # no backend is probed

        sha = {}
        for name, hair in (("Demo", "blonde"), ("Bea", "red")):
            check(f"create {name}", save_character_profile(name, {
                "template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                "model_pipeline": "base_body", "character_appearance": "slender",
                "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                               "hair": {"length": "medium", "color": hair}}}, create_new=True), True)
            char = get_character_dir(name)
            bsig = base_body.base_signature(name)
            write(char / "model_refs" / f"tpose_{bsig}.png", 10, "front")
            write(char / "model_refs" / f"tpose_back_{bsig}.png", 10, "back")
            write(char / "model3d" / f"{bsig}.glb", 20, f"model-{name}")
            base = base_body.current_base(name)
            check(f"{name} on the pipeline with a base model", bool(base and base[0] == bsig and base[1]), True)
            sha[name] = base[1] if base else ""

        def piece(item_id, slots, mode):
            inventory.add_item(name=item_id.title(), category="outfit_piece", item_id=item_id,
                               prompt_fragment=f"a plain {item_id}",
                               outfit_piece={"slots": slots, "covers": [], "outfit_types": ["casual"],
                                             "mesh_mode": mode})
        piece("dress", ["top"], "own_mesh")
        piece("shoes", ["feet"], "own_mesh")
        piece("tee", ["top"], "own_mesh")
        piece("scarf", ["neck"], "painted")
        img_dir = root / "world" / "items" / "shoes"
        img_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 1024), (90, 60, 30)).save(img_dir / "shoe.png")
        inventory.update_item("shoes", {"image": "shoe.png"})
        for name, item_id in (("Demo", "dress"), ("Bea", "dress"), ("Demo", "shoes"), ("Demo", "tee"),
                              ("Demo", "scarf")):
            check(f"{name} holds {item_id}", inventory.add_to_inventory(name, item_id), True)
        check("nothing worn", inventory.get_equipped_pieces("Demo"), {})

        def rec(**fields):
            return json.dumps(fields)
        demo, bea = get_character_dir("Demo") / "garments", get_character_dir("Bea") / "garments"
        fd, fb = gs.garment_fsig("Demo", "dress"), gs.garment_fsig("Bea", "dress")
        OLD = "0a0a0a0a0a0a"
        dress_demo = [write(demo / f"dress_{fd}.glb", 400000),
                      write(demo / f"dress_{fd}.json", 1000, rec(accepted=True, base_model_sha256=sha["Demo"])),
                      write(demo / f"images/dress_{fd}_worn_front.png", 300000),
                      write(demo / f"images/dress_{fd}_worn_front.json", 1000, rec(accepted=True)),
                      write(demo / f"bodies/ob00000001/dress_{fd}.glb", 250000)]
        dress_stale = [write(demo / f"dress_{OLD}.glb", 7000),
                       write(demo / f"dress_{OLD}.json", 1000, rec(accepted=False))]
        dress_bea = [write(bea / f"dress_{fb}.glb", 48000),
                     write(bea / f"dress_{fb}.json", 1000, rec(accepted=True, base_model_sha256=sha["Bea"]))]
        s = footwear_source.current_ssig("shoes")
        fs = gs.garment_fsig("Demo", "shoes")
        shoes_demo = [write(demo / f"shoes_{fs}.glb", 100000),
                      write(demo / f"shoes_{fs}.json", 1000, rec(accepted=True, base_model_sha256=sha["Demo"],
                                                                 kind="footwear", ssig=s))]
        world = footwear_source.item_dir("shoes")
        shoes_world = [write(world / s / "record.json", 1000, "{}"), write(world / s / "raw.glb", 500000),
                       write(world / s / "prepared.glb", 400000)]
        world_stale = write(world / "5a5a5a5a5a5a" / "record.json", 1000, "{}")
        scarf_old = [write(demo / "scarf_0b0b0b0b0b0b.glb", 5000), write(demo / "scarf_0b0b0b0b0b0b.json", 1000, "{}")]
        # The outfit body the worn outfit stands on (live: named by the worn outfit's sidecar).
        worn = current_outfit_state("Demo")[2]
        char = get_character_dir("Demo")
        bsig = base_body.base_signature("Demo")
        write(char / "model3d" / "ob00000001.glb", 10, "body")
        write(char / "model3d" / "ob00000001.json", 400, json.dumps({"outfit_body": {
            "body_id": "ob00000001", "base_signature": bsig, "built_for": worn}}))
        write(char / "model3d" / f"{worn}.json", 200, json.dumps({"body_id": "ob00000001", "pieces": {}, "items": []}))
        check("fixture sizes", (sum(p.stat().st_size for p in dress_demo), sum(p.stat().st_size for p in dress_bea),
                                sum(p.stat().st_size for p in shoes_demo + shoes_world)), (952000, 49000, 1002000))

        print("[1] dress — clothing held by two characters")
        got = artefact_graph.own_mesh_files("dress")
        check("dress files / bytes / hub jobs", (got["files"], got["bytes"], got["hub_jobs"]), (7, 1001000, 14))
        check("dress per character", sorted((c["name"], c["files"], c["bytes"], c["hub_jobs"])
                                            for c in got["characters"]),
              [("Bea", 2, 49000, 7), ("Demo", 5, 952000, 7)])
        check("dress mode / kind / world", (got["mode"], got["kind"], got["world"]),
              ("own_mesh", "clothing", {"files": 0, "bytes": 0}))
        check("dress note names the chain", all("worn 2 + ghost 2 + cutout 2 + mesh 1" in c["note"]
                                                for c in got["characters"]), True)

        print("[2] shoes — footwear with its world shoe source")
        got = artefact_graph.own_mesh_files("shoes")
        check("shoes files / bytes / hub jobs", (got["files"], got["bytes"], got["hub_jobs"]), (5, 1002000, 2))
        check("shoes per character", [(c["name"], c["files"], c["bytes"], c["hub_jobs"]) for c in got["characters"]],
              [("Demo", 2, 101000, 2)])
        check("shoes world / kind", (got["world"], got["kind"]), ({"files": 3, "bytes": 901000}, "footwear"))

        print("[3] nothing to confirm")
        got = artefact_graph.own_mesh_files("tee")
        check("tee: no files", (got["files"], got["characters"]), (0, []))
        got = artefact_graph.own_mesh_files("scarf")
        check("scarf (painted): nothing kept as an own mesh",
              (got["files"], got["hub_jobs"], got["mode"], got["kind"]), (0, 0, "painted", ""))
        try:
            artefact_graph.own_mesh_files("nope")
            check("unknown item raises", False, True)
        except LookupError:
            check("unknown item raises", True, True)
        try:
            get_item_own_mesh_files_route("nope")
            check("route 404", None, 404)
        except HTTPException as e:
            check("route 404", e.status_code, 404)
        check("route answers the same", get_item_own_mesh_files_route("dress")["files"], 7)

        print("[4] the cleanup agrees")

        def orphan_files(name, item_id):
            dry = artefact_graph.collect(name, dry_run=True, explicit=True, reason="smoke")
            keys = {e["key"] for e in dry["orphans"]}
            nodes = artefact_graph.scan(name)[0]
            return sorted(str(p) for n in nodes if n.key in keys and n.parents.get("item_id") == item_id
                          for p in n.files)

        def paths(ps):
            return sorted(str(p) for p in ps)
        check("before: Demo's dress orphans = only the stale ones", orphan_files("Demo", "dress"), paths(dress_stale))
        check("before: Bea's dress orphans", orphan_files("Bea", "dress"), [])
        check("before: Demo's shoe orphans", orphan_files("Demo", "shoes"), [])
        check("before: Demo's scarf orphans = its old files", orphan_files("Demo", "scarf"), paths(scarf_old))
        check("before: footwear dry run removes only the stale ssig",
              footwear_source.collect(dry_run=True)["removed"], [str(world_stale.parent)])
        for item_id in ("dress", "shoes"):
            item = inventory.get_item(item_id)
            inventory.update_item(item_id, {"outfit_piece": {**item["outfit_piece"], "mesh_mode": "painted"}})
        check("after: Demo's dress orphans = counted + stale", orphan_files("Demo", "dress"),
              paths(dress_demo + dress_stale))
        check("after: Bea's dress orphans = counted", orphan_files("Bea", "dress"), paths(dress_bea))
        check("after: Demo's shoe orphans = counted", orphan_files("Demo", "shoes"), paths(shoes_demo))
        check("after: nothing left to confirm", (artefact_graph.own_mesh_files("dress")["files"],
                                                 artefact_graph.own_mesh_files("shoes")["files"]), (0, 0))
        # The shoe source stays while a character's accepted footwear fit names its ssig; the daily sweep collects
        # the characters first, then the shoe sources — so one sweep removes both.
        check("after: footwear dry run still keeps the named ssig (the fit record exists)",
              footwear_source.collect(dry_run=True)["removed"], [str(world_stale.parent)])
        world_files = [p for p in world.rglob("*") if p.is_file()]
        check("after: the item folder = counted + stale", paths(world_files), paths(shoes_world + [world_stale]))
        totals = artefact_graph.sweep_all()
        check("daily sweep deletes 7 + 2 + 2 + 2 + 4 files", totals["deleted_files"], 17)
        counted = dress_demo + dress_bea + shoes_demo + shoes_world
        check("every counted file gone", [str(p) for p in counted if p.exists()], [])
        check("the shoe source folder gone", world.exists(), False)

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
