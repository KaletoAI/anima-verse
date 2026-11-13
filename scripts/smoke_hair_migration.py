#!/usr/bin/env python3
"""One-time boot migration "the hair a character no longer uses goes"
(app/core/hair_migration.py + config._migrate_removed_hair_methods; spec
docs/superpowers/specs/2026-11-11-hair-from-body-design.md § Design 6, plan
2026-11-11-hair-from-body Task 3 + coordinator correction: an explicit HairDeck
character keeps its HairDeck hair).

Usage:
    ./.venv/bin/python scripts/smoke_hair_migration.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's
``human`` package — no real world, no hub, no server process. Every garment
file is synthetic bytes; only names and JSON records matter.
``garment_assembly.schedule`` is a recorder (no build thread).

Fixture (written BEFORE the first config load):
  instance config: image_generation.routing {hair_source_mesh: ["X"],
    hair_views_mesh: ["Y"], mesh_garment: ["Z"]};
  world config: packages human, base_body.hair_method "edit_chain".
  Ana (pipeline on; hair item ``hair_ana`` made by ensure_hair_item while her
    profile said hairdeck, then the profile set to hair_method "subtract",
    hair_subtract_shape "shell", hair_shell_mm 2, outfit_imagegen
    {hair_source_mesh_workflow "X*", mesh_workflow "keep*"}); a second own
    hair item ``hair_ana_2`` (not worn); an own-mesh dress ``dress_a``.
    Files: A1 = HairDeck group f1 (fit + record method hairdeck + low +
    bodies/ob12345678 fit) + job folder raw/hair_ana_abcabcabcabc/ (record,
    beard_free.png, hair_seed42.glb); A2 = edit-chain group e1 (images
    haired/ghost/cutout front, raw GLB, prepared GLB, fit + record without
    method, low, failed step "mesh"); A3 = subtract group 5b (prepared + json,
    fit + record method subtract); A4 = hair_ana_2 fit group 22 + job folder;
    SRC = source/hair_ana_c0c0c0c0c0c0/ (haired.glb, record.json,
    haired_front_cut.png); ASM = model3d/assembled/aaaa1111.glb/.json and
    assembled/low/aaaa1111.glb/.json, sidecar garments {hair_ana, dress_a};
    KEEP_A = dress_a fit dd + record + low + worn image + prepared + its fit on
    ob12345678, and model3d/assembled/bbbb2222.glb/.json (garments {dress_a}).
  Bea (profile hair_method "hairdeck" — explicit; hair_subtract_shape "cut";
    hair item ``hair_bea`` worn). Files: B_CUR = current fsig group (fit +
    record method hairdeck + low) + job folder raw/hair_bea_<hsig>/; B_OLD =
    older HairDeck group 0b (fit + record method hairdeck, low); B_UND = group
    0d with only low/hair_bea_0d0d0d0d0d0d.glb (method cannot be told);
    B_EC = edit-chain group e1 (images haired front png/json, fit + record
    without method, low, bodies/ob12345678 fit + record without method);
    B_SUB = subtract group 5b (prepared + json, fit + record method
    subtract); B_SRC = source/hair_bea_c0c0c0c0c0c0/haired.glb; B_ASM =
    model3d/assembled/cccc3333.glb/.json (garments {hair_bea}).
  Cy (no hair_method, no hair item, a dress fit) — nothing of his changes.
  Orphan: hair item ``hair_ghost`` owned by "Nobody" (no such character).

EXPECTED, BY HAND FROM THE SPEC § Design 6 AND THE CORRECTION
[1] Config, in memory after load: routing keeps only mesh_garment of the three;
    base_body.hair_method "body". config.migrate_file persists it: the
    instance config.json routing has neither hair key, the world config.json has
    no base_body.hair_method (pruned: "body" is the default), and both layer
    dirs hold a .config-history snapshot. _migrate_removed_hair_methods on the
    migrated dict -> False (idempotent).
[2] Proof the migration is new work: at 8f4f306c (the start of Task 3)
    app/core/hair_migration.py does not exist and config.py names no
    _migrate_removed_hair_methods; the GC rules that judge garment groups are
    unchanged since 8f4f306c — byte-identical there and at c7f0a002 (the
    last commit before plan 2026-11-12-unified-worn-pieces Task 11b, which
    made ``_garment_roots`` keep the groups of BOTH open / closed states of a
    closable piece — more kept, never less; the dry run below checks the work
    tree):
    artefact_graph ``scan`` (node kinds, "unknown" = source/), ``_hair_hsig``,
    ``_judge``'s garments block ("# 5. Garments" up to "# 6. Temp work
    folders.") and outfit_cache_gc ``_garment_roots`` (the whole two files
    changed since for other chains: 27248e39 the ref prefixes, plan
    2026-11-12-unified-worn-pieces Task 5 the body/texture rules) — and a
    dry-run collect(explicit) here keeps
    Bea's B_EC and B_SUB groups (the GC keeps the newest fit of EVERY method a
    record names) and never lists source/ — without the migration they stay.
[3] delete_all_hair_once() -> characters Ana: method body, items deleted
    [hair_ana, hair_ana_2], kept ""; Bea: method hairdeck, kept hair_bea, items
    []; Cy: untouched. orphans [hair_ghost].
    Ana: walk of model3d/ model_refs/ garments/ = KEEP_A exactly (every A*, SRC
    and ASM file gone; no path contains "hair_"); profile: no
    hair_subtract_shape / hair_shell_mm / hair_method, outfit_imagegen
    {mesh_workflow "keep*"}, equipped_mesh_pieces without "hair"; both items
    gone. KEEP_A bytes identical (sha256 before == after).
    Bea: walk = B_CUR + job + B_OLD + B_UND + B_ASM exactly, bytes identical;
    profile hair_method "hairdeck", no hair_subtract_shape, hair worn =
    hair_bea, item exists.
    Cy: walk + profile identical. world_kv HAIR_FLAG == "1".
    garment_assembly.schedule asked for Ana only (her hair slot was emptied).
[4] Second call -> None; every walk unchanged; no schedule call.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The commit Task 3 started from — the old code of the proof in [2].
BASELINE = "8f4f306c"
#: The rules compared with BASELINE: the commit before Task 11b changed ``_garment_roots`` (see [2]).
RULES_AT = "c7f0a002"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def gc_garment_rules(rev):
    """The GC's garment-group rules (module docstring [2]) as source text, at
    ``rev`` (None = the work tree); a part missing is None."""
    import ast

    def text(path):
        return (ROOT / path).read_text() if rev is None else git("show", f"{rev}:{path}").stdout

    def function(src, name):
        node = next((n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name), None)
        return ast.get_source_segment(src, node) if node else None

    def block(src, start, end):
        i = src.find(start)
        j = src.find(end, i) if i >= 0 else -1
        return src[i:j] if j > i else None
    ag_src, ocg_src = text("app/core/artefact_graph.py"), text("app/core/outfit_cache_gc.py")
    return {"artefact_graph.scan": function(ag_src, "scan"),
            "artefact_graph._hair_hsig": function(ag_src, "_hair_hsig"),
            "artefact_graph._judge garments": block(ag_src, "    # 5. Garments", "    # 6. Temp work folders."),
            "outfit_cache_gc._garment_roots": function(ocg_src, "_garment_roots")}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-migration-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        inst_cfg = root / "inst" / "config.json"
        inst_cfg.write_text(json.dumps({"image_generation": {"routing": {
            "hair_source_mesh": ["X"], "hair_views_mesh": ["Y"], "mesh_garment": ["Z"]}}}))
        world_cfg = paths.get_config_path()
        world_cfg.write_text(json.dumps({"packages": {"enabled": "human"},
                                         "base_body": {"hair_method": "edit_chain"}}))
        from app.core import config
        config.load(world_cfg, instance_path=inst_cfg)

        # --- [1] config ---------------------------------------------------------------------------
        print("[1] config: removed hair occasions and world method")
        routing = config.get("image_generation.routing") or {}
        check("[1] routing in memory", sorted(k for k in routing if k in ("hair_source_mesh", "hair_views_mesh",
                                                                          "mesh_garment")), ["mesh_garment"])
        check("[1] world hair_method in memory", config.get("base_body.hair_method"), "body")
        config.migrate_file(world_cfg, inst_cfg)
        on_disk = json.loads(inst_cfg.read_text())
        check("[1] instance file routing", sorted(k for k in (on_disk.get("image_generation") or {})
                                                  .get("routing", {}) if k.startswith("hair_")
                                                  or k == "mesh_garment"), ["mesh_garment"])
        check("[1] world file hair_method", (json.loads(world_cfg.read_text()).get("base_body") or {})
              .get("hair_method"), None)
        check("[1] backups", [bool(list((d / config.CONFIG_HISTORY_DIRNAME).glob("*")))
                              for d in (inst_cfg.parent, world_cfg.parent)], [True, True])
        again = {"image_generation": {"routing": {"mesh_garment": ["Z"]}}, "base_body": {"hair_method": "body"}}
        check("[1] idempotent", config._migrate_removed_hair_methods(again), False)
        check("[1] hairdeck world value stays", (config._migrate_removed_hair_methods(
            {"base_body": {"hair_method": "hairdeck"}})), False)

        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import artefact_graph as ag, base_body, garment_assembly, garment_hair, garment_store as gs
        from app.core import hair_migration as hm
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.models.world import get_world_setting
        scheduled = []
        garment_assembly.schedule = lambda name, signature=None: scheduled.append(name) or True

        def make(char: str, method: str):
            human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                     "character_appearance": "slender, wavy hair", "hair_method": method,
                     "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}
            assert save_character_profile(char, human, create_new=True)
            touch(get_character_images_dir(char) / f"{char}_1.png", b"\x89PNG" + char.encode() * 8)
            prof = get_character_profile(char)
            prof["profile_image"] = f"{char}_1.png"
            assert save_character_profile(char, prof)
            bsig = base_body.base_signature(char)
            R = get_character_dir(char) / "model_refs"
            for view in ("tpose", "tpose_back"):
                touch(R / f"{view}_{bsig}.png", b"png" + view.encode())
                touch(R / f"{view}_{bsig}.json", {"base_signature": bsig})
            return get_character_dir(char)

        def dress(char: str, item_id: str):
            op = {"slots": ["outer"], "covers": [], "outfit_types": ["casual"], "mesh_mode": "own_mesh"}
            inventory.add_item(name=item_id, category="outfit_piece", item_id=item_id, prompt_fragment="a dress",
                               outfit_piece=op)
            inventory.add_to_inventory(char, item_id)
            G = get_character_dir(char) / "garments"
            rec = {"accepted": True, "item_id": item_id, "fsig": "dddddddddddd", "kind": "clothing"}
            return [touch(G / f"{item_id}_dddddddddddd.glb", b"DRESS-FIT" + char.encode()),
                    touch(G / f"{item_id}_dddddddddddd.json", rec),
                    touch(G / "low" / f"{item_id}_dddddddddddd.glb", b"DRESS-LOW"),
                    touch(G / "images" / f"{item_id}_dddddddddddd_worn_front.png", b"WORN"),
                    touch(G / "images" / f"{item_id}_dddddddddddd_worn_front.json", {"accepted": True}),
                    touch(G / "prepared" / f"{item_id}_dddddddddddd.glb", b"DRESS-PREP"),
                    touch(G / "bodies" / "ob12345678" / f"{item_id}_dddddddddddd.glb", b"DRESS-OB"),
                    touch(G / "bodies" / "ob12345678" / f"{item_id}_dddddddddddd.json", rec)]

        def hair_fit(G: Path, item: str, fsig: str, record: dict):
            return [touch(G / f"{item}_{fsig}.glb", f"FIT-{item}-{fsig}".encode()),
                    touch(G / f"{item}_{fsig}.json", {"accepted": True, "item_id": item, "fsig": fsig, **record}),
                    touch(G / "low" / f"{item}_{fsig}.glb", b"LOW")]

        # Ana --------------------------------------------------------------------------------------
        A = make("Ana", "hairdeck")
        assert garment_hair.ensure_hair_item("Ana") == "hair_ana"
        inventory.add_item(name="Hair", category="garment", owner="Ana", item_id="hair_ana_2",
                           garment={"kind": "hair", "slot": "hair", "body_slot": "hair"},
                           transferable=False, portable=False)
        G = A / "garments"
        f1 = gs.garment_fsig("Ana", "hair_ana")
        hair_files = hair_fit(G, "hair_ana", f1, {"method": "hairdeck", "inputs": {"hsig": "abcabcabcabc"}})
        hair_files += [touch(G / "bodies" / "ob12345678" / f"hair_ana_{f1}.glb"),
                       touch(G / "bodies" / "ob12345678" / f"hair_ana_{f1}.json",
                             {"accepted": True, "method": "hairdeck"})]
        job = G / "raw" / "hair_ana_abcabcabcabc"
        hair_files += [touch(job / "record.json", {"accepted": True}), touch(job / "beard_free.png"),
                       touch(job / "hair_seed42.glb")]
        for step in ("haired", "ghost", "cutout"):
            hair_files += [touch(G / "images" / f"hair_ana_e1e1e1e1e1e1_{step}_front.png"),
                           touch(G / "images" / f"hair_ana_e1e1e1e1e1e1_{step}_front.json", {"accepted": True})]
        hair_files += hair_fit(G, "hair_ana", "e1e1e1e1e1e1", {})
        hair_files += [touch(G / "raw" / "hair_ana_e1e1e1e1e1e1.glb"),
                       touch(G / "prepared" / "hair_ana_e1e1e1e1e1e1.glb"),
                       touch(G / "failed" / "hair_ana_e1e1e1e1e1e1.json", {"step": "mesh", "error": "x"})]
        hair_files += hair_fit(G, "hair_ana", "5b5b5b5b5b5b", {"method": "subtract"})
        hair_files += [touch(G / "prepared" / "hair_ana_5b5b5b5b5b5b.glb"),
                       touch(G / "prepared" / "hair_ana_5b5b5b5b5b5b.json", {"accepted": True})]
        hair_files += hair_fit(G, "hair_ana_2", "222222222222", {"method": "hairdeck"})
        hair_files += [touch(G / "raw" / "hair_ana_2_abcabcabcabc" / "record.json", {})]
        src = G / "source" / "hair_ana_c0c0c0c0c0c0"
        hair_files += [touch(src / "haired.glb"), touch(src / "record.json", {"accepted": True}),
                       touch(src / "haired_front_cut.png")]
        M = A / "model3d" / "assembled"
        both = {"garments": {"hair_ana": {"kind": "hair"}, "dress_a": {"kind": "clothing"}}}
        hair_files += [touch(M / "aaaa1111.glb"), touch(M / "aaaa1111.json", both),
                       touch(M / "low" / "aaaa1111.glb"), touch(M / "low" / "aaaa1111.json", both)]
        keep_a = dress("Ana", "dress_a") + [touch(M / "bbbb2222.glb", b"ASM-DRESS"),
                                            touch(M / "bbbb2222.json", {"garments": {"dress_a": {}}})]
        prof = get_character_profile("Ana")
        prof.update(hair_method="subtract", hair_subtract_shape="shell", hair_shell_mm=2,
                    outfit_imagegen={"hair_source_mesh_workflow": "X*", "mesh_workflow": "keep*"})
        assert save_character_profile("Ana", prof)
        check("[0] Ana wears hair_ana", inventory.get_equipped_mesh_pieces("Ana").get("hair"), "hair_ana")

        # Bea --------------------------------------------------------------------------------------
        B = make("Bea", "hairdeck")
        assert garment_hair.ensure_hair_item("Bea") == "hair_bea"
        G = B / "garments"
        fb, hb = gs.garment_fsig("Bea", "hair_bea"), gs.garment_hsig("Bea", "hair_bea")
        keep_b = hair_fit(G, "hair_bea", fb, {"method": "hairdeck", "inputs": {"hsig": hb}})
        keep_b += [touch(gs.hairdeck_dir("Bea", "hair_bea", hb) / "record.json", {"accepted": True, "seed": 42}),
                   touch(gs.hairdeck_dir("Bea", "hair_bea", hb) / "hair_seed42.glb", b"SEED42")]
        keep_b += hair_fit(G, "hair_bea", "0b0b0b0b0b0b", {"method": "hairdeck"})
        keep_b += [touch(G / "low" / "hair_bea_0d0d0d0d0d0d.glb", b"UNDECIDED")]
        keep_b += [touch(B / "model3d" / "assembled" / "cccc3333.glb", b"ASM-BEA"),
                   touch(B / "model3d" / "assembled" / "cccc3333.json", {"garments": {"hair_bea": {}}})]
        gone_b = [touch(G / "images" / "hair_bea_e1e1e1e1e1e1_haired_front.png"),
                  touch(G / "images" / "hair_bea_e1e1e1e1e1e1_haired_front.json", {"accepted": True})]
        gone_b += hair_fit(G, "hair_bea", "e1e1e1e1e1e1", {})
        gone_b += [touch(G / "bodies" / "ob12345678" / "hair_bea_e1e1e1e1e1e1.glb"),
                   touch(G / "bodies" / "ob12345678" / "hair_bea_e1e1e1e1e1e1.json", {"accepted": True})]
        gone_b += hair_fit(G, "hair_bea", "5b5b5b5b5b5b", {"method": "subtract"})
        gone_b += [touch(G / "prepared" / "hair_bea_5b5b5b5b5b5b.glb"),
                   touch(G / "prepared" / "hair_bea_5b5b5b5b5b5b.json", {"accepted": True})]
        gone_b += [touch(G / "source" / "hair_bea_c0c0c0c0c0c0" / "haired.glb")]
        prof = get_character_profile("Bea")
        prof["hair_subtract_shape"] = "cut"
        assert save_character_profile("Bea", prof)

        # Cy + orphan ------------------------------------------------------------------------------
        make("Cy", "")
        keep_c = dress("Cy", "dress_c")
        inventory.add_item(name="Hair", category="garment", owner="Nobody", item_id="hair_ghost",
                           garment={"kind": "hair", "slot": "hair", "body_slot": "hair"})

        def walk(char):
            cdir = get_character_dir(char)
            return {p.relative_to(cdir).as_posix() for d in ag.ROOT_DIRS if (cdir / d).is_dir()
                    for p in (cdir / d).rglob("*") if p.is_file()}

        def rel(char, files):
            return {p.relative_to(get_character_dir(char)).as_posix() for p in files}

        def shas(files):
            return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

        base_refs = {char: {p for p in walk(char) if p.startswith("model_refs/")} for char in ("Ana", "Bea", "Cy")}
        before_a, before_b, before_c = shas(keep_a), shas(keep_b), shas(keep_c)
        walk_c, prof_c = walk("Cy"), get_character_profile("Cy")
        check("[0] fixture: Ana walk", walk("Ana"), rel("Ana", hair_files + keep_a) | base_refs["Ana"])
        check("[0] fixture: Bea walk", walk("Bea"), rel("Bea", keep_b + gone_b) | base_refs["Bea"])

        # --- [2] proof ---------------------------------------------------------------------------
        print(f"[2] at {BASELINE} nothing removed these files")
        check(f"[2] {BASELINE}: no hair_migration.py",
              git("cat-file", "-e", f"{BASELINE}:app/core/hair_migration.py").returncode != 0, True)
        old_cfg = git("show", f"{BASELINE}:app/core/config.py").stdout
        check(f"[2] {BASELINE}: config.py readable, no hair config migration",
              ("_apply_file_migrations" in old_cfg, "_migrate_removed_hair_methods" in old_cfg), (True, False))
        old_rules, now_rules = gc_garment_rules(BASELINE), gc_garment_rules(RULES_AT)
        check(f"[2] GC garment rules unchanged from {BASELINE} to {RULES_AT}",
              {k: (old_rules[k] is not None, old_rules[k] == now_rules[k]) for k in old_rules},
              {k: (True, True) for k in old_rules})
        dry = ag.collect("Bea", dry_run=True, explicit=True)
        listed = {e["key"] for e in dry["orphans"]}
        check("[2] plain GC keeps Bea's edit-chain + subtract fits",
              sorted(k for k in ("garment:hair_bea_e1e1e1e1e1e1", "garment:hair_bea_5b5b5b5b5b5b") if k in listed),
              [])
        check("[2] plain GC: source/ is unknown, never deleted",
              any(p.startswith("garments/source/") for p in dry["unknown"]), True)

        # --- [3] the migration -------------------------------------------------------------------
        print("[3] delete_all_hair_once")
        scheduled.clear()  # the fixture's equip_mesh_piece calls asked for builds too
        out = hm.delete_all_hair_once()
        by = {r["character"]: r for r in (out or {}).get("characters", [])}
        check("[3] Ana result", {k: by.get("Ana", {}).get(k) for k in ("method", "kept", "items", "failed")},
              {"method": "body", "kept": "", "items": ["hair_ana", "hair_ana_2"], "failed": []})
        check("[3] Bea result", {k: by.get("Bea", {}).get(k) for k in ("method", "kept", "items", "failed")},
              {"method": "hairdeck", "kept": "hair_bea", "items": [], "failed": []})
        check("[3] Cy untouched", {k: by.get("Cy", {}).get(k) for k in ("items", "dropped", "files")},
              {"items": [], "dropped": [], "files": 0})
        check("[3] orphans", (out or {}).get("orphans"), ["hair_ghost"])
        check("[3] Ana walk", walk("Ana"), rel("Ana", keep_a) | base_refs["Ana"])
        check("[3] Ana: no hair path", sorted(p for p in walk("Ana") if "hair_" in p), [])
        check("[3] Ana: kept bytes identical", shas(keep_a), before_a)
        prof = get_character_profile("Ana")
        check("[3] Ana profile", ({k for k in ("hair_subtract_shape", "hair_shell_mm", "hair_method") if k in prof},
                                  prof.get("outfit_imagegen"), "hair" in (prof.get("equipped_mesh_pieces") or {})),
              (set(), {"mesh_workflow": "keep*"}, False))
        check("[3] Ana items gone", [inventory.get_item(i) for i in ("hair_ana", "hair_ana_2")], [None, None])
        check("[3] Bea walk", walk("Bea"), rel("Bea", keep_b) | base_refs["Bea"])
        check("[3] Bea: kept bytes identical", shas(keep_b), before_b)
        prof = get_character_profile("Bea")
        check("[3] Bea profile", (prof.get("hair_method"), "hair_subtract_shape" in prof,
                                  inventory.get_equipped_mesh_pieces("Bea").get("hair"),
                                  bool(inventory.get_item("hair_bea"))), ("hairdeck", False, "hair_bea", True))
        check("[3] Cy walk + bytes + profile", (walk("Cy"), shas(keep_c), get_character_profile("Cy")),
              (walk_c, before_c, prof_c))
        check("[3] orphan item gone", inventory.get_item("hair_ghost"), None)
        check("[3] flag", get_world_setting(hm.HAIR_FLAG), "1")
        check("[3] assembly rebuild asked for", scheduled, ["Ana"])

        # --- [4] second call ---------------------------------------------------------------------
        print("[4] a second call is a no-op")
        walks = {c: walk(c) for c in ("Ana", "Bea", "Cy")}
        check("[4] returns None", hm.delete_all_hair_once(), None)
        check("[4] walks unchanged", {c: walk(c) for c in walks}, walks)
        check("[4] no schedule call", scheduled, ["Ana"])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
