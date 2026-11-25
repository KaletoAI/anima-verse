"""A covered extension part keys the template drape over it (plan anatomy, task 7: the key part, no Blender).

Usage: ./.venv/bin/python scripts/smoke_drape_body_collider.py

Fixture package ``pkgd`` (temporary world, template human-roleplay = piece wardrobe):
  slot ``lower`` covered_by [bottom, underwear_bottom], mesh part switch ``switch``:
    G  hide_under [underwear_bottom], drape_collider {inflate 0.003} (no radius: the part itself), chain bone PkgdG
    Y  a part-only group (applies_to attributes.switch [on]) WITHOUT drape_collider
  slot ``upper`` covered_by [top, underwear_top]:
    T  hide_under [underwear_top], drape_collider {inflate 0.002, radius 0.0045}, chain bones PkgdT1 -> PkgdT2
Items: TR template trousers (bottom), SL template briefs (underwear_bottom), TL template top (top).

Hand derivation (``body_colliders``: a group with ``drape_collider``, ``cover_state`` over ``lower`` + the piece is
COVERED, and the piece itself touches the group's ``covered_by``; token
``body:<g>:<inflate>:<radius or ->`` joined by "," plus ``:v1``):
  K1 a figure whose package declares no drape_collider (the same fixture without the key), TL alone:
     ``under_tokens`` equals BASE d0bae1f34's (the old module run on the same fixture).
  K2 TR alone: G covered (bottom is in covered_by, not in hide_under), TR touches bottom -> "body:G:0.003:-:v1";
     T exposed (nothing on top) -> only G. Entry {group G, inflate 0.003, radius None, bones [mixamorig:PkgdG]}.
  K3 TR over SL (lower [SL]): G hidden (SL fully on a hide_under slot) -> no body token.
  K4 TL with TR under it (lower [TR]): G covered, but TL touches neither bottom nor underwear_bottom -> G not
     in the token; T covered by TL -> "body:T:0.002:0.0045:v1" only.
  K5 TL alone: T covered -> "body:T:0.002:0.0045:v1"; the entry's bones = the LAST bone of each chain
     [mixamorig:PkgdT2].
  K6 the group set follows the stored base variant: base_meta mesh_variant "|mesh:pkgd.lower=on" -> groups G and
     Y apply, only G has a collider -> token G only; mesh_variant "" -> Y gone, G still (G does not hang on the
     switch) -> token G; Y never.
  K7 ``garment_template_cut.sig_of`` keys the cut by the same tokens: TR's cut sig differs with and without the
     ``drape_collider`` declaration.
"""
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "d0bae1f34"
FAILS = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def manifest(colliders=True):
    attrs = {"switch": {"type": "select", "options": ["off", "on"]}}
    g = {"id": "G", "op": "appendage_chain", "chains": [[{"bone": "mixamorig:PkgdG", "parent": "Hips"}]],
         "hide_under": ["underwear_bottom"]}
    y = {"id": "Y", "op": "attached_part_bone", "chains": [[{"bone": "mixamorig:PkgdY", "parent": "Hips"}]],
         "applies_to": {"attributes.switch": ["on"]}}
    t = {"id": "T", "op": "appendage_chain",
         "chains": [[{"bone": "mixamorig:PkgdT1", "parent": "Spine2"}, {"bone": "mixamorig:PkgdT2", "parent": "mixamorig:PkgdT1"}]],
         "hide_under": ["underwear_top"]}
    if colliders:
        g["drape_collider"] = {"inflate": 0.003}
        t["drape_collider"] = {"inflate": 0.002, "radius": 0.0045}
    return {"name": "Pkgd", "apply_to": "*", "body_slots": [
        {"id": "lower", "covered_by": ["bottom", "underwear_bottom"], "attributes": attrs, "rigs": [g, y],
         "mesh_part": {"switch": "switch", "rigs": {"G": {"params": {}, "attribute_params": {}}}}},
        {"id": "upper", "covered_by": ["top", "underwear_top"], "rigs": [t]}]}


def main():
    with tempfile.TemporaryDirectory(prefix="drape-body-") as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "rig.fbx")
        from app.core import config, db
        db.init_schema()
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "pkgd"}}))
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        import yaml
        from app.plugins.loader import discover_packages

        def load(colliders):
            plugins = root / ("plugins_on" if colliders else "plugins_off")
            (plugins / "pkgd").mkdir(parents=True, exist_ok=True)
            (plugins / "pkgd" / "plugin.yaml").write_text(yaml.safe_dump(manifest(colliders)))
            discover_packages(plugins, force=True)
        from app.core import body_slots, garment_store, garment_template as gt
        from app.models import inventory
        import app.models.character as character

        def piece(name, slots, kind, **params):
            return {"id": name, "name": name, "category": "outfit_piece",
                    "outfit_piece": {"slots": list(slots), "covers": [], "partially_covers": [], "mesh_mode": "template",
                                     "template": {"params": {**gt.kind_defaults(kind), "kind": kind, **params}}}}
        items = {"TR": piece("TR", ["bottom"], "trousers"), "SL": piece("SL", ["underwear_bottom"], "briefs"),
                 "TL": piece("TL", ["top"], "top", length_m=0.6)}
        inventory.get_item = lambda item_id, *a, **k: items.get(str(item_id))
        body_slots.piece_slots_for_character = lambda *a, **k: list(inventory.VALID_PIECE_SLOTS)
        pic = root / "pic.png"
        pic.write_bytes(b"picture")
        profile = {"template": "human-roleplay", "body_slots": {"lower": {"switch": "on"}}, "equipped_pieces": {}}
        character.get_character_profile = lambda name, *a, **k: dict(profile)
        meta = {"mesh_variant": "|mesh:pkgd.lower=on"}

        def patch(mod):
            mod.texture_sources = lambda c, i: {"front": str(pic), "back": str(pic), "source": "cutout"}
            if hasattr(mod, "base_meta_for"):
                mod.base_meta_for = lambda c, sha: dict(meta)
        patch(gt)
        garment_store.accepted_fit = lambda *a, **k: None

        def body(item_id, lower):
            return [t for t in gt.under_tokens("Smoke", item_id, gt.params_of(items[item_id]), base_sha="b1",
                                               lower=list(lower), item=items[item_id]) if t.startswith("body:")]
        # K1 against BASE (package without the key)
        load(False)
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:app/core/garment_template.py"],
                             capture_output=True, text=True, check=True).stdout
        old = types.ModuleType("gt_base")
        old.__file__ = str(ROOT / "app/core/garment_template.py")
        exec(compile(src, old.__file__, "exec"), old.__dict__)
        patch(old)
        for item_id, lower in (("TL", []), ("TR", []), ("TR", ["SL"])):
            new_t = gt.under_tokens("Smoke", item_id, gt.params_of(items[item_id]), base_sha="b1", lower=lower,
                                    item=items[item_id])
            old_t = old.under_tokens("Smoke", item_id, old.params_of(items[item_id]), base_sha="b1", lower=lower,
                                     item=items[item_id])
            check(new_t == old_t, f"K1 {item_id} over {lower}: under_tokens == BASE ({new_t})")
        load(True)
        k2 = body("TR", [])
        check(k2 == ["body:G:0.003:-:v1"], f"K2 TR alone: {k2}")
        entries = gt.body_colliders("Smoke", "TR", [], base_meta=meta)
        check(entries == [{"group": "G", "inflate": 0.003, "radius": None, "bones": ["mixamorig:PkgdG"]}],
              f"K2 entry {entries}")
        check(body("TR", ["SL"]) == [], f"K3 TR over SL: hidden, no token ({body('TR', ['SL'])})")
        k4 = body("TL", ["TR"])
        check(k4 == ["body:T:0.002:0.0045:v1"], f"K4 TL with TR under it: {k4}")
        k5 = gt.body_colliders("Smoke", "TL", [], base_meta=meta)
        check(body("TL", []) == ["body:T:0.002:0.0045:v1"]
              and k5 == [{"group": "T", "inflate": 0.002, "radius": 0.0045, "bones": ["mixamorig:PkgdT2"]}],
              f"K5 TL alone: {body('TL', [])} {k5}")
        from app.core import extension_rig
        on = [g["id"] for g in extension_rig.rig_groups_for("Smoke", profile, mesh_variant=meta["mesh_variant"])]
        off = [g["id"] for g in extension_rig.rig_groups_for("Smoke", profile, mesh_variant="")]
        meta_off = {"mesh_variant": ""}
        check("Y" in on and "Y" not in off and "G" in off
              and [e["group"] for e in gt.body_colliders("Smoke", "TR", [], base_meta=meta)] == ["G"]
              and [e["group"] for e in gt.body_colliders("Smoke", "TR", [], base_meta=meta_off)] == ["G"],
              f"K6 groups on {on} / off {off}: token G both times, Y never")
        from app.core import garment_template_cut as cut
        with_sig = cut.sig_of("Smoke", "TR", gt.params_of(items["TR"]), base_sha="b1", lower=[], item=items["TR"])[0]
        load(False)
        without_sig = cut.sig_of("Smoke", "TR", gt.params_of(items["TR"]), base_sha="b1", lower=[], item=items["TR"])[0]
        check(with_sig and without_sig and with_sig != without_sig, f"K7 cut sig follows the token ({with_sig} vs {without_sig})")
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
