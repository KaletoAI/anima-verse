#!/usr/bin/env python3
"""The artefact GC keeps every OWNED hairstyle's and garment's files, not only the worn ones (Ruling A59b,
``outfit_cache_gc._garment_roots`` — the one keep set every sweep and collect reads).

Usage:
    ./.venv/bin/python scripts/smoke_owned_garments_gc.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server. Stubs: ``garment_assembly.schedule`` (nothing is assembled) and the image service (an
empty namespace — no backend is probed). Fingerprints (fsig / hsig / ssig) are computed by the real
``garment_store`` functions — the same ones the GC calls.

THE RULE (A59b). A hairstyle is a garment of kind hair the character OWNS (``garment_hair.hairstyles``: ``owner`` =
the character, carried by nobody — never in the inventory); several are owned, one is worn. Before A59b the keep
set took only the equipped mesh pieces (the WORN hairstyle) and the held own-mesh outfit pieces
(``garment_set.held_clothing``) — an unworn hairstyle was "item not held": its fits, strand records, attempts, body
fits and HairDeck / HAAR job folders were orphans for every collect (the daily sweep, every delete hook). Now every
owned hairstyle is a root like the worn one: per item the CURRENT fsig group, the fit served on the current base
(``accepted_fit``, R11) and per method the newest accepted fit (on the current base and at all); its HairDeck / HAAR
job folder of the current hsig / ssig or named by a kept fit (``inputs.hsig`` / ``inputs.ssig``). Everything else of
the item stays prunable: an older accepted fit of the same method, a job folder no kept fit names. The files of an
item that no longer exists are pruned (a deleted item keeps nothing).

FIXTURE (S = 12-hex signatures; everything under characters/Demo/garments/, every file's mtime 2 days old unless
said — the daily sweep's 10-minute grace never holds)
  Demo: human on the base-body pipeline; base refs tpose_<bsig>.png / tpose_back_<bsig>.png, base model
  model3d/<bsig>.glb (sha = BASE). Outfit body ob00000001: model3d/ob00000001.{glb,json} (record: body_id, the
  current base signature, built_for the worn signature W) and the worn outfit's sidecar model3d/W.json naming
  body_id ob00000001 — so the body is reachable ("named by a live outfit model") and its fits are judged by
  their garment group alone.
  H1 = create_hairstyle(Demo, "medium blonde hair", "hairdeck") -> hair_demo (the first: WORN).
  H2 = create_hairstyle(Demo, "long braided hair", "haar") -> hair_demo_2 (owned, NOT worn).
  H3 = create_hairstyle(Demo, "short red hair", "hairdeck") -> hair_demo_3, its files written, then the ITEM is
       deleted (``inventory.delete_item``) — its files are left behind.
  dress: outfit piece {slots [top], own_mesh}, in Demo's inventory, NOT worn (equipped_pieces {}).
  Files:
    H1  raw/H1_<hsig1>/record.json; H1_F1.{glb,json} (accepted on BASE, method hairdeck, inputs.hsig hsig1);
        bodies/ob00000001/H1_F1.glb                                                         -> kept (worn)
    H2  KEPT (14 files):
        raw/H2_<ssig2>/{record.json, s1/demo_strands.npy, s1/demo_head.obj, s1/tile.png}     current HAAR job (4)
        H2_F2.{glb,json,strands.json,strands.npz}, low/H2_F2.glb (record accepted False)      current fsig (5)
        failed/H2_F2.json, attempts/H2_F2.{glb,json}, attempts/prev/H2_F2.glb                 its attempts (4) ...
        bodies/ob00000001/H2_F2.{glb,json}                                                    ... body fit (2)
        H2_A.{glb,json,strands.json}, low/H2_A.glb (A = a2a2…, accepted on BASE, method haar, mtime 1 day:
             the newest accepted HAAR fit = the served one while F2 is not accepted)              (4)
        H2_D.{glb,json} (D = d2d2…, accepted on BASE, method hairdeck, inputs.hsig e2e2…: the newest accepted
             HairDeck fit — switching the method back costs nothing) + raw/H2_e2e2…/record.json (the job a kept
             fit names)                                                                           (3)
        = 4 + 5 + 4 + 2 + 4 + 3 = 22 files (the list in ``h2_keep``).
    H2  STALE (removed): H2_O.{glb,json}, low/H2_O.glb (O = b2b2…, accepted on BASE, method haar, mtime 3 days:
        an OLDER accepted fit of the same method) and raw/H2_c2c2…/{record.json, s1/old_strands.npy} (the job only
        that stale fit names) — 5 files.
    H3  (deleted item, removed): H3_f3f3….{glb,json}, raw/H3_a3a3…/record.json — 3 files.
    dress (owned, unworn; KEPT): dress_FC.{glb,json} (accepted on BASE), images/dress_FC_worn_front.{png,json},
        bodies/ob00000001/dress_FC.glb — 5 files.
    garments/notes.txt — no item's name, never judged.

EXPECTED, BY HAND
[0] The roots: worn_hair_id H1; hairstyles(Demo) = [H1, H2] after H3's delete; ``_garment_roots`` items contain
    H1, H2 and dress, not H3; hair items {H1, H2}.
[1] The judgement (explicit dry run): the orphan keys are EXACTLY {garment:H2_O, hairdeck:H2_c2c2…,
    garment:H3_f3f3…, hairdeck:H3_a3a3…}; reasons — H2_O "no owned garment uses this fingerprint", H2's old job
    "older HairDeck job", H3's job "item not owned". ``verify_cache`` stale_signatures = the same four keys.
[2..4] Each run starts from the same fixture (restored byte- and mtime-exact):
    [2] the daily sweep (``artefact_graph.sweep_all``, grace on), [3] a delete hook (``collect_quietly(Demo,
    "outfit set deleted")``), [4] the cache dialog's purge (``purge_stale`` asked for the four stale keys AND
    garment:H2_F2, hairdeck:H2_<ssig2>, garment:dress_FC — the three kept are skipped: skipped 3).
    After each: deleted_files 8 (5 stale of H2 + 3 of H3); every H2 keep file, every dress file, every H1 file and
    notes.txt byte-identical (sha256); the 5 stale H2 files and the 3 H3 files gone; A59's own enumeration
    ``hairstyle_delete.item_paths(Demo, H2)`` afterwards = its list before minus raw/H2_c2c2… and the three H2_O
    files (the enumeration and the GC agree on what "belongs to the hairstyle" means).
[5] Fails on the old code (``outfit_cache_gc`` as of commit 11d83a2038ac, the base of A59b, loaded from git, its
    ``_garment_roots`` swapped in): the explicit dry run's orphans then include garment:H2_F2, garment:H2_A,
    garment:H2_D, bodyfit:ob00000001:H2_F2, hairdeck:H2_<ssig2> and hairdeck:H2_e2e2… (the job's reason
    "item not owned" — the judge is today's, only the keep set is old) — every file of the unworn hairstyle
    would go; the dress (owned, unworn) is NOT an orphan there either (owned
    garments were kept before A59b already: ``held_clothing`` reads the inventory).
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The commit A59b starts from — the old ``_garment_roots`` (only worn hair kept).
OLD_COMMIT = "11d83a2038acc2d9e2e0f8b88cc5fc7097477cd0"

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400]
          + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def write(path: Path, data: str = "", age_s: float = 2 * 86400) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data or f"{path.name}-bytes")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def hashes(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def old_module(tmp: Path):
    """``outfit_cache_gc`` as of OLD_COMMIT, loaded from git."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/outfit_cache_gc.py"],
                            capture_output=True, text=True, check=True).stdout
    path = tmp / "old_outfit_cache_gc.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("old_outfit_cache_gc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="owned-garments-gc-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        world_cfg = paths.get_config_path()
        world_cfg.write_text(json.dumps({"packages": {"enabled": "human"},
                                         "base_body": {"hairstyle_default_mode": "hairdeck"}}))
        from app.core import config
        config.load(world_cfg, instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)

        from app.core import (artefact_graph, base_body, garment_assembly, garment_hair, garment_store as gs,
                              hairstyle_delete, outfit_cache_gc as ocg)
        from app.core.model_refs import current_outfit_state
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()   # no backend is probed

        check("create Demo", save_character_profile("Demo", {
            "template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
            "model_pipeline": "base_body", "character_appearance": "slender",
            "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                           "hair": {"length": "medium", "color": "blonde"}}}, create_new=True), True)
        char = get_character_dir("Demo")
        bsig = base_body.base_signature("Demo")
        write(char / "model_refs" / f"tpose_{bsig}.png", "front")
        write(char / "model_refs" / f"tpose_back_{bsig}.png", "back")
        write(char / "model3d" / f"{bsig}.glb", "model-1")
        base = base_body.current_base("Demo")
        check("on the pipeline with a base model", bool(base and base[0] == bsig and base[1]), True)
        sha = base[1] if base else ""

        h1 = garment_hair.create_hairstyle("Demo", "medium blonde hair", "hairdeck")
        h2 = garment_hair.create_hairstyle("Demo", "long braided hair", "haar")
        h3 = garment_hair.create_hairstyle("Demo", "short red hair", "hairdeck")
        check("ids", (h1, h2, h3), ("hair_demo", "hair_demo_2", "hair_demo_3"))
        check("H1 worn", garment_hair.worn_hair_id("Demo"), h1)
        inventory.add_item(name="Dress", category="outfit_piece", item_id="dress", prompt_fragment="a red dress",
                           outfit_piece={"slots": ["top"], "covers": [], "outfit_types": ["casual"],
                                         "mesh_mode": "own_mesh"})
        check("dress held", inventory.add_to_inventory("Demo", "dress"), True)
        check("dress not worn", inventory.get_equipped_pieces("Demo"), {})

        g = char / "garments"
        notes = write(g / "notes.txt")

        def rec(**fields):
            return json.dumps(fields)
        # H1 — the worn hairstyle.
        hsig1 = gs.garment_hsig("Demo", h1)
        f1 = gs.garment_fsig("Demo", h1)
        h1_files = [write(g / f"raw/{h1}_{hsig1}/record.json", "{}"),
                    write(g / f"{h1}_{f1}.glb"),
                    write(g / f"{h1}_{f1}.json", rec(accepted=True, base_model_sha256=sha, method="hairdeck",
                                                     inputs={"hsig": hsig1})),
                    write(g / f"bodies/ob00000001/{h1}_{f1}.glb")]
        # H2 — owned, not worn (HAAR). The job folder first: its seeds enter the fsig (``haar_served_seed``).
        ssig2 = gs.garment_ssig("Demo", h2)
        job = g / f"raw/{h2}_{ssig2}"
        h2_job = [write(job / "record.json", "{}"), write(job / "s1/demo_strands.npy"),
                  write(job / "s1/demo_head.obj"), write(job / "s1/tile.png")]
        f2 = gs.garment_fsig("Demo", h2)
        A, D, O, OLD_JOB, HD_JOB = "a2a2a2a2a2a2", "d2d2d2d2d2d2", "b2b2b2b2b2b2", "c2c2c2c2c2c2", "e2e2e2e2e2e2"
        check("distinct signatures", len({f2, A, D, O}), 4)
        h2_keep = h2_job + [
            *[write(g / f"{h2}_{f2}.{s}") for s in ("glb", "strands.json", "strands.npz")],
            write(g / f"{h2}_{f2}.json", rec(accepted=False, method="haar", inputs={"ssig": ssig2})),
            write(g / f"low/{h2}_{f2}.glb"),
            write(g / f"failed/{h2}_{f2}.json", rec(step="fit", error="refused")),
            write(g / f"attempts/{h2}_{f2}.glb"), write(g / f"attempts/{h2}_{f2}.json", "{}"),
            write(g / f"attempts/prev/{h2}_{f2}.glb"),
            write(g / f"bodies/ob00000001/{h2}_{f2}.glb"), write(g / f"bodies/ob00000001/{h2}_{f2}.json", "{}"),
            write(g / f"{h2}_{A}.glb", age_s=86400),
            write(g / f"{h2}_{A}.json", rec(accepted=True, base_model_sha256=sha, method="haar",
                                            inputs={"ssig": ssig2}), age_s=86400),
            write(g / f"{h2}_{A}.strands.json", age_s=86400), write(g / f"low/{h2}_{A}.glb", age_s=86400),
            write(g / f"{h2}_{D}.glb"),
            write(g / f"{h2}_{D}.json", rec(accepted=True, base_model_sha256=sha, method="hairdeck",
                                            inputs={"hsig": HD_JOB})),
            write(g / f"raw/{h2}_{HD_JOB}/record.json", "{}")]
        check("H2 keep files", len(h2_keep), 22)
        h2_stale = [write(g / f"{h2}_{O}.glb", age_s=3 * 86400),
                    write(g / f"{h2}_{O}.json", rec(accepted=True, base_model_sha256=sha, method="haar",
                                                    inputs={"ssig": OLD_JOB}), age_s=3 * 86400),
                    write(g / f"low/{h2}_{O}.glb", age_s=3 * 86400),
                    write(g / f"raw/{h2}_{OLD_JOB}/record.json", "{}"),
                    write(g / f"raw/{h2}_{OLD_JOB}/s1/old_strands.npy")]
        # H3 — its item deleted, its files left behind.
        h3_files = [write(g / f"{h3}_f3f3f3f3f3f3.glb"), write(g / f"{h3}_f3f3f3f3f3f3.json", "{}"),
                    write(g / f"raw/{h3}_a3a3a3a3a3a3/record.json", "{}")]
        check("H3 item deleted", inventory.delete_item(h3), True)
        # The dress — owned, not worn.
        fc = gs.garment_fsig("Demo", "dress")
        dress_files = [write(g / f"dress_{fc}.glb"),
                       write(g / f"dress_{fc}.json", rec(accepted=True, base_model_sha256=sha)),
                       write(g / f"images/dress_{fc}_worn_front.png"),
                       write(g / f"images/dress_{fc}_worn_front.json", rec(accepted=True)),
                       write(g / f"bodies/ob00000001/dress_{fc}.glb")]
        # The outfit body the worn outfit stands on.
        worn = current_outfit_state("Demo")[2]
        write(char / "model3d" / "ob00000001.glb", "body")
        write(char / "model3d" / "ob00000001.json", json.dumps({"outfit_body": {
            "body_id": "ob00000001", "base_signature": bsig, "built_for": worn}}))
        write(char / "model3d" / f"{worn}.json", json.dumps({"body_id": "ob00000001", "pieces": {}, "items": []}))
        keep_files = h1_files + h2_keep + dress_files + [notes]
        keep_hashes = hashes(keep_files)
        gone_files = h2_stale + h3_files
        item_paths_before = sorted(str(p) for p in hairstyle_delete.item_paths("Demo", h2))
        snapshot = root / "snapshot"
        for name in ("garments", "model3d", "model_refs"):
            shutil.copytree(char / name, snapshot / name, symlinks=True)

        def restore():
            for name in ("garments", "model3d", "model_refs"):
                shutil.rmtree(char / name)
                shutil.copytree(snapshot / name, char / name, symlinks=True)

        stale_keys = {f"garment:{h2}_{O}", f"hairdeck:{h2}_{OLD_JOB}",
                      f"garment:{h3}_f3f3f3f3f3f3", f"hairdeck:{h3}_a3a3a3a3a3a3"}

        print("[0] the roots")
        check("hairstyles owned", [i["id"] for i in garment_hair.hairstyles("Demo")], [h1, h2])
        roots = ocg._garment_roots("Demo")
        check("roots computable", roots is not None, True)
        if roots is not None:
            check("kept items", sorted(roots[1]), sorted([h1, h2, "dress"]))
            check("hair items", sorted(roots[2]), [h1, h2])
            check("H2 current fsig kept", f"garment:{h2}_{f2}" in roots[0], True)
            check("H2 served fit kept", f"garment:{h2}_{A}" in roots[0], True)
            check("H2 other method's fit kept", f"garment:{h2}_{D}" in roots[0], True)
            check("H2 older accepted fit not kept", f"garment:{h2}_{O}" in roots[0], False)

        print("[1] the judgement")
        dry = artefact_graph.collect("Demo", dry_run=True, explicit=True, reason="smoke")
        orphans = {e["key"]: e["reason"] for e in dry["orphans"]}
        check("orphan keys", set(orphans), stale_keys)
        check("reason older accepted fit", orphans.get(f"garment:{h2}_{O}"), "no owned garment uses this fingerprint")
        check("reason older job", orphans.get(f"hairdeck:{h2}_{OLD_JOB}"), "older HairDeck job")
        check("reason deleted item's job", orphans.get(f"hairdeck:{h3}_a3a3a3a3a3a3"), "item not owned")
        report = ocg.verify_cache("Demo")
        check("verify_cache stale", set(report["stale_signatures"]), stale_keys)

        def after(label, deleted):
            check(f"{label}: deleted files", deleted, len(gone_files))
            changed = sorted(p for p, h in keep_hashes.items()
                             if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest() != h)
            check(f"{label}: owned files byte-identical", changed, [])
            check(f"{label}: stale files gone", [str(p) for p in gone_files if p.exists()], [])
            want = sorted(set(item_paths_before) - {str(g / f"raw/{h2}_{OLD_JOB}")}
                          - {str(p) for p in h2_stale[:3]})
            check(f"{label}: item_paths(H2) minus the stale ones",
                  sorted(str(p) for p in hairstyle_delete.item_paths("Demo", h2)), want)

        print("[2] the daily sweep")
        totals = artefact_graph.sweep_all()
        after("daily sweep", totals["deleted_files"])
        restore()
        print("[3] a delete hook (collect_quietly)")
        result = artefact_graph.collect_quietly("Demo", "outfit set deleted") or {}
        after("hook", result.get("deleted_files"))
        restore()
        print("[4] the cache dialog's purge")
        purged = ocg.purge_stale("Demo", stale_keys | {f"garment:{h2}_{f2}", f"hairdeck:{h2}_{ssig2}",
                                                       f"garment:dress_{fc}"})
        check("purge skipped the kept keys", purged["skipped"], 3)
        after("purge", purged["deleted_files"])
        restore()

        print(f"[5] fails on the old code ({OLD_COMMIT[:12]})")
        new_roots = ocg._garment_roots
        try:
            ocg._garment_roots = old_module(root)._garment_roots
            dry = artefact_graph.collect("Demo", dry_run=True, explicit=True, reason="smoke old")
        finally:
            ocg._garment_roots = new_roots
        old_orphans = {e["key"]: e["reason"] for e in dry["orphans"]}
        unworn = {f"garment:{h2}_{f2}", f"garment:{h2}_{A}", f"garment:{h2}_{D}",
                  f"bodyfit:ob00000001:{h2}_{f2}", f"hairdeck:{h2}_{ssig2}", f"hairdeck:{h2}_{HD_JOB}"}
        check("old: every node of the unworn hairstyle is an orphan", sorted(unworn - set(old_orphans)), [])
        check("old: its job not kept", old_orphans.get(f"hairdeck:{h2}_{ssig2}"), "item not owned")
        check("old: the owned unworn dress kept", [k for k in old_orphans if "dress" in k], [])

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
