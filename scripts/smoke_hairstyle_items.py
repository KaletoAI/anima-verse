#!/usr/bin/env python3
"""Hairstyles as items (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 13, decisions D1-D5):
the boot migration ``figure_migration.migrate_hairstyles_once``, the figure keys of a worn hairstyle
(``garment_hair.shape_hair`` / ``hair_style_id`` -> ``figure.WornSets``), an outfit set that wears a hairstyle
and the refusal of HAAR.

Usage:
    ./.venv/bin/python scripts/smoke_hairstyle_items.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no server. ``figure_build.request`` is a recorder throughout (nothing is built);
``model_refs.get_auto_kinds`` answers {} (no 2D reference render is armed, only the Build timer).
The old-code proof runs the code of commit 8ffa6e64 (the task base) from ``git archive`` in a subprocess on the
same storage, BEFORE the migration.

Fixture (written before the migration, the way a world from before hairstyles stores it):
  world config: packages human, base_body.hair_method "body" (the old world setting);
  world_kv ``migrated_hair_methods`` "1" (the hair migration of Task 3 ran);
  Kai (human-roleplay, male, 30, 180 cm): hair slot {length short, color black}, appearance "athletic, wavy
    hair with a side parting, grey eyes", profile hair_method "body", hair_colour "#112233" — no hair item;
    his stored base set: model_refs/<kind>_<bsig>.png + .json for the four views (the front's sidecar
    names base_identity and the prompt_fingerprint + front prompt the OLD code computes) and
    model3d/<bsig>.glb + .json (base, rig mixamo);
  Ana (female, 30, 168 cm): hair slot {length long, color blonde}, appearance "slender", profile
    hair_method "hairdeck", hair_forward_m 0.004, an owned hair item ``hair_ana`` (garment {kind hair, slot
    hair, body_slot hair}, no mode) worn;
  Bom (male): no hair slot values, appearance "tall" — bald.

EXPECTED, BY HAND FROM THE BRIEF (D1-D5) AND THE HUMAN MANIFEST
[1] Migration. The world config in memory: no base_body.hair_method, hairstyle_default_mode "body";
    config.migrate_file persists it — the world file keeps no base_body (pruned: "body" is the default).
    Kai's hair text T = the slot fragment "{length} {color} hair" -> "short black hair" + the appearance's
    hair clause (clauses "athletic" / "wavy hair with a side parting" / "grey eyes"):
        T = "short black hair, wavy hair with a side parting"
    migrate_hairstyles_once() -> {"Ana": "hair_ana", "Kai": <new id>} (Bom: no hair text, no hairstyle);
    a second call -> None. Kai owns ONE hairstyle: name "Short black hair, wavy hair with a side parting"
    (T, capital first letter, 48 characters: not cut), garment {kind hair, slot hair, body_slot hair,
    mesh_mode body, description T, hair_colour "#112233"}, prompt_fragment T; worn
    (equipped_mesh_pieces.hair) and the plain body's (base_hairstyle); the profile has no hair_method and no
    hair_colour. Ana: hair_ana extended in place to {kind hair, slot hair, body_slot hair, mesh_mode hairdeck,
    description "long blonde hair", hair_forward_m 0.004} (no second item), worn, plain; no hair_method /
    hair_forward_m left in the profile.
    No rebuild — byte for byte against the OLD code (8ffa6e64) on the pre-migration storage: base_identity
    (Kai, Ana) equal, prompt_fingerprint equal (the old code with today's base texts of Ruling A74a, which
    changed them on its own; the plain body's hair text is the one the old code rendered
    the base with: Kai T, Ana "" — HairDeck hair had a bald base), base_body.hair_text equal; Kai's base
    files (every file under model_refs/ and model3d/) unchanged (sha256), the stored base's prompts current
    (base_prompts_freshness "current"); wanted_figure(Kai): shape = bsig, hair "body", hair_style "".
[2] A second ``body`` hairstyle S = create_hairstyle(Kai, "short black hair", "body") is NOT worn (only
    the first one is). wear_hairstyle(Kai, S) -> True, one Build request ("outfit_change"). Worn sets:
    hair_in_body True, hair_shape "short black hair" (S's text differs from the plain body's T),
    hair_style S. wanted shape = shape_key_of({**plain inputs, "hair": "short black hair"}) where the plain
    inputs are shape_inputs of the same sets with hair_shape "" — != bsig. Wearing the first again -> shape
    bsig, hair_style "".
[3] A ``hairdeck`` hairstyle D (text "long braided hair") worn on Kai's haired plain body: hair_in_body
    False, hair_item D, hair_shape "bald", hair_style D; wanted shape = shape_key_of({**plain inputs (these
    sets), "hair": "bald"}), wanted hair "hairdeck". Delivered (nothing built: no bald shape stored, no fit):
    shape bsig, hair "body" (the plain body shows its own hair meanwhile), hair_style "".
[4] An outfit set {pieces [shirt], hairstyle S} (add_character_outfit stores ``hairstyle``) applied through
    the inventory route's body (_apply_outfit_set_route_sync) while Kai wears D and no shirt: the shirt is
    worn, equipped_mesh_pieces.hair = S, ``figure_build.request`` called ONCE ("outfit_change") and the Build
    debounce timer the piece change armed is disarmed (no ``(Kai, BUILD_TIMER)`` timer left). Applied again
    (nothing changes): no further request. The preview route's payload names hairstyle S.
[5] create_hairstyle(Kai, "a bun", "bogus") -> ValueError "hair mode must be one of"; nothing created.
    GET /characters/Kai/hairstyles (get_character_hairstyles): keys {hairstyles, default_mode "body", modes
    ["hairdeck", "haar", "body"] (HAIR_MODES), built_modes ["hairdeck", "haar", "body"] (BUILT_MODES, HAAR
    built since strand-hair Task 13), pipeline, auto_build (Task UI4), appearance_hair_text (Ruling A54)};
    three entries,
    the worn S first, each {id, name, description, mode, worn, plain, freshness, wear, due (Task UI4)}; the first
    hairstyle plain + "current", S "missing" (its body shape is made by a Build), D (HairDeck, no fit) "missing".
    Ruling A54 — the standard text the New-hairstyle dialog opens with: Kai's ``appearance_hair_text`` is T (his
    Appearance is unchanged by the hairstyles); Bom's is "" (bald), and create_hairstyle(Bom, "") is the
    ValueError "No hair set — describe the hairstyle, or fill in the hair in Appearance" the dialog shows as a
    hint before Create.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The task base — the code that stored every base body the migration must not touch.
OLD_COMMIT = "8ffa6e64"

FAILS = []

OLD_PROBE = r'''
import json, os, sys
from pathlib import Path
from app.core import paths
paths.init(Path(os.environ["STORAGE_DIR"]))
paths.init_instance(Path(os.environ["INSTANCE_DIR"]))
from app.core import config
config.load(paths.get_config_path(), instance_path=Path(os.environ["INSTANCE_DIR"]) / "config.json")
from app.plugins.loader import discover_packages
discover_packages(Path(sys.argv[1]), force=True)
from app.core import base_body
# Ruling A74a (2026-11-14) changed the base texts on its own — not part of the hairstyle migration: the old
# code gets today's texts (the negative's default head included, bound when the function was defined), so
# the proof compares only what the migration touches.
for key, value in json.loads(os.environ["A74A_TEXTS"]).items():
    setattr(base_body, key, value)
base_body.base_negative.__kwdefaults__["head"] = base_body.BASE_NEGATIVE
out = {}
for name in sys.argv[2:]:
    out[name] = {"identity": base_body.base_identity(name), "fingerprint": base_body.prompt_fingerprint(name),
                 "hair": base_body.hair_text(name), "front": base_body.base_prompt(name, "front")[0]}
print("RESULT " + json.dumps(out))
'''


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, prefix=""):
    try:
        fn()
    except exc as e:
        check(label, str(e).startswith(prefix), True)
        return
    except Exception as e:  # noqa: BLE001 — reported as a failure
        check(label, f"{type(e).__name__}: {e}", exc.__name__)
        return
    check(label, "no exception", exc.__name__)


def tree_hashes(*dirs: Path) -> dict:
    out = {}
    for d in dirs:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def old_code(root: Path, names) -> dict:
    """The OLD_COMMIT code's base identity / fingerprint / hair text, run on this storage."""
    old = root / "old"
    old.mkdir()
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", OLD_COMMIT, "app", "plugins/human", "shared",
                              ":(exclude)shared/items", ":(exclude)shared/models/clips", ":(exclude)shared/terrain",
                              ":(exclude)shared/surface_textures", ":(exclude)shared/bench",
                              ":(exclude)shared/test-vectors"], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(old)], input=archive, check=True)
    from app.core import base_body
    a74a = {"BASE_BLOCK_HEAD": "", **{key: getattr(base_body, key) for key in (
        "BODY_TEXT", "BODY_NEGATIVE", "BASE_NEGATIVE", "HAIRED_BASE_NEGATIVE", "DRAFT_NEGATIVE",
        "HAIRED_DRAFT_NEGATIVE")}}
    # Ruling A111: the old code is fed the body text the stored bases were made with — the fingerprint form.
    a74a["BODY_TEXT"] = base_body.BODY_TEXT_FINGERPRINT
    run = subprocess.run([sys.executable, "-c", OLD_PROBE, str(root / "plugins"), *names], cwd=str(old),
                         capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(old), "A74A_TEXTS": json.dumps(a74a)})
    line = next((ln for ln in run.stdout.splitlines() if ln.startswith("RESULT ")), "")
    if not line:
        print(run.stdout[-2000:], run.stderr[-3000:])
        raise RuntimeError(f"old-code probe at {OLD_COMMIT} failed")
    return json.loads(line[len("RESULT "):])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairstyle-items-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        world_cfg = paths.get_config_path()
        world_cfg.write_text(json.dumps({"packages": {"enabled": "human"}, "base_body": {"hair_method": "body"}}))
        from app.core import config
        config.load(world_cfg, instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)

        from app.core import base_body, figure, figure_build, figure_migration, garment_hair, model_refs
        from app.core.hair_migration import HAIR_FLAG
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import (add_character_outfit, get_character_dir, get_character_profile,
                                          save_character_profile)
        from app.models.world import set_world_setting
        requests = []
        figure_build.request = lambda name, trigger: requests.append((name, trigger)) or True
        model_refs.get_auto_kinds = lambda name: {}
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, **kw: path   # no Blender for the stub GLBs
        # No image service: a HairDeck fsig asks the pool for its backend params — a stub without a pool (nothing
        # is loaded or probed), as in scripts/smoke_hair_in_body.py.
        import types
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()

        human = {"template": "human-roleplay", "age": 30}
        check("create Kai", save_character_profile("Kai", {
            **human, "gender": "male", "height": 180,
            "character_appearance": "athletic, wavy hair with a side parting, grey eyes",
            "body_slots": {"hair": {"length": "short", "color": "black"}},
            "hair_method": "body", "hair_colour": "#112233"}, create_new=True), True)
        check("create Ana", save_character_profile("Ana", {
            **human, "gender": "female", "height": 168, "character_appearance": "slender",
            "body_slots": {"hair": {"length": "long", "color": "blonde"}},
            "hair_method": "hairdeck", "hair_forward_m": 0.004}, create_new=True), True)
        check("create Bom", save_character_profile("Bom", {
            **human, "gender": "male", "height": 175, "character_appearance": "tall"}, create_new=True), True)
        inventory.add_item(name="Hair", category="garment", owner="Ana", item_id="hair_ana",
                           garment={"kind": "hair", "slot": "hair", "body_slot": "hair"},
                           prompt_fragment="long blonde hair", transferable=False, portable=False)
        with keyed_lock("character_profile", "Ana"):
            ana = get_character_profile("Ana")
            ana["equipped_mesh_pieces"] = {"hair": "hair_ana"}
            check("Ana wears hair_ana", save_character_profile("Ana", ana), True)
        set_world_setting(HAIR_FLAG, "1")

        print(f"[0] old code ({OLD_COMMIT}) on the storage before the migration")
        old = old_code(root, ["Kai", "Ana"])
        T = "short black hair, wavy hair with a side parting"
        check("old hair texts", (old["Kai"]["hair"], old["Ana"]["hair"]), (T, ""))
        bsig = base_body.base_signature("Kai")
        check("bsig is the old identity", bsig, old["Kai"]["identity"])
        refs = model_refs.get_model_refs_dir("Kai")
        refs.mkdir(parents=True, exist_ok=True)
        for view in base_body.BASE_VIEWS:
            kind = base_body._kind(view)
            (refs / f"{kind}_{bsig}.png").write_bytes(f"png-{view}".encode())
            meta = {"base_signature": bsig, "created_at": "2026-11-12T10:00:00Z"}
            if view == "front":
                meta.update(base_identity=bsig, prompt_fingerprint=old["Kai"]["fingerprint"],
                            prompt=old["Kai"]["front"])
            (refs / f"{kind}_{bsig}.json").write_text(json.dumps(meta))
        mdir = get_character_dir("Kai") / "model3d"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / f"{bsig}.glb").write_bytes(b"glb-Kai")
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        before = tree_hashes(refs, mdir)
        check("Kai base ready", (base_body.base_model_info("Kai") or {}).get("status"), "ready")

        # --- [1] ---------------------------------------------------------------------------------------------
        print("[1] migration")
        check("world method in memory", (config.get("base_body.hair_method"),
                                         config.get("base_body.hairstyle_default_mode")), (None, "body"))
        config.migrate_file(world_cfg, root / "instance" / "config.json")
        check("world file base_body", json.loads(world_cfg.read_text()).get("base_body"), None)
        result = figure_migration.migrate_hairstyles_once()
        kai_id = (result or {}).get("Kai", "")
        check("result", result, {"Ana": "hair_ana", "Kai": kai_id})
        check("Kai got a new id", bool(kai_id) and kai_id != "hair_ana", True)
        check("second call", figure_migration.migrate_hairstyles_once(), None)
        check("Kai owns one hairstyle", [h["id"] for h in garment_hair.hairstyles("Kai")], [kai_id])
        item = inventory.get_item(kai_id) or {}
        check("Kai item", (item.get("name"), item.get("garment"), item.get("prompt_fragment")),
              ("Short black hair, wavy hair with a side parting",
               {"kind": "hair", "slot": "hair", "body_slot": "hair", "mesh_mode": "body", "description": T,
                "hair_colour": "#112233"}, T))
        kai = get_character_profile("Kai")
        check("Kai worn + plain, legacy keys gone",
              ((kai.get("equipped_mesh_pieces") or {}).get("hair"), kai.get("base_hairstyle"),
               "hair_method" in kai, "hair_colour" in kai), (kai_id, kai_id, False, False))
        check("Ana item extended", (inventory.get_item("hair_ana") or {}).get("garment"),
              {"kind": "hair", "slot": "hair", "body_slot": "hair", "mesh_mode": "hairdeck",
               "description": "long blonde hair", "hair_forward_m": 0.004})
        check("Ana one hairstyle", [h["id"] for h in garment_hair.hairstyles("Ana")], ["hair_ana"])
        ana = get_character_profile("Ana")
        check("Ana worn + plain, legacy keys gone",
              ((ana.get("equipped_mesh_pieces") or {}).get("hair"), ana.get("base_hairstyle"),
               "hair_method" in ana, "hair_forward_m" in ana), ("hair_ana", "hair_ana", False, False))
        check("Bom none", garment_hair.hairstyles("Bom"), [])
        for name in ("Kai", "Ana"):
            check(f"{name} identity = old", base_body.base_identity(name), old[name]["identity"])
            check(f"{name} prompt_fingerprint = old", base_body.prompt_fingerprint(name), old[name]["fingerprint"])
            check(f"{name} hair text = old", base_body.hair_text(name), old[name]["hair"])
        check("Kai base files untouched", tree_hashes(refs, mdir), before)
        check("Kai bsig unchanged", base_body.base_signature("Kai"), bsig)
        check("stored base prompts current", base_body.base_prompts_freshness("Kai").get("state"), "current")
        wanted = figure.wanted_figure("Kai")
        check("wanted = the plain body", (wanted.shape, wanted.hair, wanted.hair_style), (bsig, "body", ""))

        def plain_inputs(sets):
            return figure.shape_inputs("Kai", replace(sets, hair_shape=""), bsig=bsig, profile=kai_profile(),
                                       variant=figure.predicted_variant("Kai", sets, [], profile=kai_profile()))

        def kai_profile():
            return get_character_profile("Kai")

        # --- [2] ---------------------------------------------------------------------------------------------
        print("[2] a second body hairstyle")
        second = garment_hair.create_hairstyle("Kai", "short black hair", "body")
        check("not worn", garment_hair.worn_hair_id("Kai"), kai_id)
        check("wear it", garment_hair.wear_hairstyle("Kai", second), True)
        check("one Build request", requests, [("Kai", "outfit_change")])
        sets = figure.worn_sets("Kai")
        check("sets", (sets.hair_in_body, sets.hair_shape, sets.hair_style), (True, "short black hair", second))
        wanted = figure.wanted_figure("Kai")
        want = figure.shape_key_of({**plain_inputs(sets), "hair": "short black hair"})
        check("shape key with its text", (wanted.shape, wanted.shape != bsig, wanted.hair_style),
              (want, True, second))
        check("its inputs carry the text", figure.shape_inputs(
            "Kai", sets, bsig=bsig, variant=figure.predicted_variant("Kai", sets, [], profile=kai_profile()),
            profile=kai_profile()).get("hair"), "short black hair")
        garment_hair.wear_hairstyle("Kai", kai_id)
        wanted = figure.wanted_figure("Kai")
        check("the first again: bsig", (wanted.shape, wanted.hair_style), (bsig, ""))

        # --- [3] ---------------------------------------------------------------------------------------------
        print("[3] a HairDeck hairstyle on the haired plain body")
        deck = garment_hair.create_hairstyle("Kai", "long braided hair", "hairdeck")
        garment_hair.wear_hairstyle("Kai", deck)
        sets = figure.worn_sets("Kai")
        check("sets", (sets.hair_in_body, sets.hair_item, sets.hair_shape, sets.hair_style),
              (False, deck, "bald", deck))
        wanted = figure.wanted_figure("Kai")
        check("wanted: the bald shape", (wanted.shape, wanted.hair, wanted.hair_style),
              (figure.shape_key_of({**plain_inputs(sets), "hair": "bald"}), "hairdeck", deck))
        figure.invalidate()
        delivered = figure.delivered_figure("Kai")
        check("delivered meanwhile", (delivered.shape, delivered.hair, delivered.hair_style), (bsig, "body", ""))

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] an outfit set wears its hairstyle")
        shirt = inventory.add_item(name="Shirt", category="outfit_piece", item_id="shirt_kai",
                                   prompt_fragment="a white shirt",
                                   outfit_piece={"slots": ["top"], "covers": [], "outfit_types": ["casual"]})["id"]
        inventory.add_to_inventory("Kai", shirt)
        oid = add_character_outfit("Kai", {"name": "Evening", "pieces": [shirt], "hairstyle": second})
        from app.routes import inventory as inventory_routes
        check("preview names the hairstyle",
              inventory_routes.preview_outfit_set_route("Kai", oid).get("hairstyle"), second)
        requests.clear()
        out = inventory_routes._apply_outfit_set_route_sync("Kai", {"outfit_id": oid})
        kai = kai_profile()
        check("applied", (out.get("status"), (kai.get("equipped_pieces") or {}).get("top"),
                          (kai.get("equipped_mesh_pieces") or {}).get("hair")), ("ok", shirt, second))
        check("ONE Build request", requests, [("Kai", "outfit_change")])
        check("no Build timer left", ("Kai", model_refs.BUILD_TIMER) in model_refs._pending_timers, False)
        inventory_routes._apply_outfit_set_route_sync("Kai", {"outfit_id": oid})
        check("applied again: no request", requests, [("Kai", "outfit_change")])

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] an unknown mode and the list")
        raises("unknown mode refused", lambda: garment_hair.create_hairstyle("Kai", "a bun", "bogus"), ValueError,
               "hair mode must be one of")
        check("nothing created", len(garment_hair.hairstyles("Kai")), 3)
        from app.routes.characters import get_character_hairstyles
        payload = get_character_hairstyles("Kai")
        check("payload keys", (sorted(payload), payload.get("default_mode"), payload.get("modes"),
                               payload.get("built_modes")),
              (["appearance_hair_text", "auto_build", "built_modes", "default_mode", "hairstyles", "modes",
                "pipeline"], "body", ["hairdeck", "haar", "body"], ["hairdeck", "haar", "body"]))
        rows = payload.get("hairstyles") or []
        check("entry keys", [sorted(r) for r in rows][:1],
              [["description", "due", "freshness", "id", "mode", "name", "plain", "wear", "worn"]])
        check("standard text (A54)", payload.get("appearance_hair_text"), T)
        check("bald: no standard text (A54)", get_character_hairstyles("Bom").get("appearance_hair_text"), "")
        raises("bald: the hint's message", lambda: garment_hair.create_hairstyle("Bom", "", ""), ValueError,
               "No hair set — describe the hairstyle, or fill in the hair in Appearance")
        check("rows", [(r["id"], r["mode"], r["worn"], r["plain"], r["freshness"]["state"]) for r in rows],
              [(second, "body", True, False, "missing"),
               *sorted([(kai_id, "body", False, True, "current"), (deck, "hairdeck", False, False, "missing")])])

    print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
