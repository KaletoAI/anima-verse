"""A pose that requires its group exposed waits under clothing; a covered group with a drape collider rests in its
bind pose; the ``exposed:`` / ``covered:`` condition atoms (plan anatomy, tasks 5 and 6).

Usage: ./.venv/bin/python scripts/smoke_cover_pose_gate.py

Fixture package ``pkgc`` (temporary world), slot ``lower`` covered_by [bottom, underwear_bottom] with
  X: rest_max_deg 90, poses.raised {rest_deg 80, girth 1.2, requires: exposed}, drape_collider {inflate .003},
     hide_under [underwear_bottom], no clothing_lift_default;
  Z: poses.raised {rest_deg 80, girth 1.2} (no requires, no drape_collider);
  Y: a part-only group (applies_to attributes.switch: [on]) of the slot's mesh part (the switch on = the part is
     active; ``rig_groups_for`` drops Y under clothing because the part is off there).
Items: jeans (slots [bottom]), briefs (slots [underwear_bottom]), both motion_damping 1. The state ``s1`` names
``{X: raised, Z: raised}`` (``collect_bone_poses`` patched).

Hand derivation (``cover_state`` rule, motion layers of ``motion_payload``):
  M1 nude, raised active: X exposed -> rest_deg = clamp(80 + 0*90, +-90) = 80, girth = 1 * 1.2 = 1.2, no held.
  M2 jeans only: X covered (bottom in covered_by, not in hide_under) -> the pose is skipped: rest_deg 0,
     girth 1.0; X has a drape collider, so H4 zeroes gain = max_deg = gravity = 0;
     held = {X: {pose raised, state covered, by [jeans]}}.
  M3 jeans + briefs: X hidden -> skipped, rest_deg 0; H4 does not apply, gain = 1.0 * damping 1 = 1.0;
     held.state hidden, by [briefs, jeans].
  M4 free-text wardrobe dressed, no pieces: covered (never hidden) -> as M2 with by [].
  M5 apply_clothing False, jeans on: as M1 (the base preview sees no clothing).
  M6 Z (no requires), jeans on: the pose applies, rest_deg 80; no H4 (no drape collider).
  M7 rev: the fixture WITH the new fields, nude, no active state, gives the rev of BASE d0bae1f34 with the
     manifest WITHOUT them (same groups, no held, declarations without the three keys = BASE's asdict).
  M8 jeans on, switch on: "Y" not in the payload groups — as at BASE (the part-only group falls away under
     clothing; nothing to move or gate).
Atoms (task 6, ``prompt_filters`` conditions):
  A1 condition "exposed:X" holds nude, not under jeans.
  A2 "not covered:X" behaves as A1.
  A3 a character without group X (no template: no slot applies): "exposed:X" is false.
  A4 Y under jeans: "covered:Y" true, nude false (``rig_groups_unclothed`` lists Y: the part is active).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "d0bae1f34"
FAILS = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def manifest(new_fields=True):
    attrs = {"switch": {"type": "select", "options": ["off", "on"]}}
    x = {"id": "X", "op": "appendage_chain", "chains": [[{"bone": "mixamorig:PkgcX", "parent": "Hips"}]],
         "rest_max_deg": 90, "poses": {"raised": {"rest_deg": 80, "girth": 1.2}}}
    if new_fields:
        x["poses"]["raised"]["requires"] = "exposed"
        x["drape_collider"] = {"inflate": 0.003}
        x["hide_under"] = ["underwear_bottom"]
    z = {"id": "Z", "op": "appendage_chain", "chains": [[{"bone": "mixamorig:PkgcZ", "parent": "Hips"}]],
         "poses": {"raised": {"rest_deg": 80, "girth": 1.2}}}
    y = {"id": "Y", "op": "attached_part_bone", "chains": [[{"bone": "mixamorig:PkgcY", "parent": "Hips"}]],
         "applies_to": {"attributes.switch": ["on"]}}
    return {"name": "Pkgc", "apply_to": "*", "body_slots": [
        {"id": "lower", "covered_by": ["bottom", "underwear_bottom"], "attributes": attrs, "rigs": [x, z, y],
         "mesh_part": {"switch": "switch", "rigs": {"X": {"params": {}, "attribute_params": {}}}}}]}


REV_SCRIPT = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.core import paths
root = Path(sys.argv[2])
paths.init(root / "w"); paths.init_instance(root / "instance")
from app.core import config, db
db.init_schema()
paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "pkgc"}}))
config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
from app.plugins.loader import discover_packages
discover_packages(Path(sys.argv[3]), force=True)
from app.core import prompt_filters
prompt_filters.collect_bone_poses = lambda *a, **k: []
from app.core.extension_rig import motion_payload
print(json.dumps(motion_payload("Smoke", {"template": "human-roleplay",
                                          "body_slots": {"lower": {"switch": "off"}}})["rev"]))
'''


def rev_of(tree, root, new_fields):
    import yaml
    plugins = root / f"plugins_{'new' if new_fields else 'old'}_{tree.name}"
    (plugins / "pkgc").mkdir(parents=True)
    (plugins / "pkgc" / "plugin.yaml").write_text(yaml.safe_dump(manifest(new_fields)))
    work = root / f"rev_{plugins.name}"
    out = subprocess.run([sys.executable, "-c", REV_SCRIPT, str(tree), str(work), str(plugins)],
                         capture_output=True, text=True)
    lines = out.stdout.strip().splitlines()
    return lines[-1] if out.returncode == 0 and lines else f"error: {out.stderr.strip()[-300:]}"


def main():
    with tempfile.TemporaryDirectory(prefix="cover-pose-") as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "rig.fbx")
        from app.core import config, db
        db.init_schema()
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "pkgc"}}))
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        import yaml
        from app.plugins.loader import discover_packages
        package = root / "plugins" / "pkgc"
        package.mkdir(parents=True)
        (package / "plugin.yaml").write_text(yaml.safe_dump(manifest()))
        discover_packages(root / "plugins", force=True)
        from app.models import inventory
        inventory.add_item("Jeans", category="outfit_piece", item_id="jeans",
                           outfit_piece={"slots": ["bottom"], "motion_damping": 1})
        inventory.add_item("Briefs", category="outfit_piece", item_id="briefs",
                           outfit_piece={"slots": ["underwear_bottom"], "motion_damping": 1})
        from app.core import prompt_filters, outfit_renderer
        prompt_filters.collect_bone_poses = lambda *a, **k: [{"id": "s1", "bone_pose": {"X": "raised", "Z": "raised"}}]
        from app.core.extension_rig import motion_payload

        def prof(pieces=None, switch="off", **extra):
            return {"template": "human-roleplay", "equipped_pieces": pieces or {},
                    "body_slots": {"lower": {"switch": switch}}, **extra}

        def near(a, b):
            return abs(a - b) < 1e-9
        m1 = motion_payload("Smoke", prof())
        x = m1["groups"]["X"]
        check(near(x["rest_deg"], 80) and near(x["girth"], 1.2) and "held" not in m1, "M1 nude: raised applies, no held")
        m2 = motion_payload("Smoke", prof({"bottom": "jeans"}))
        x = m2["groups"]["X"]
        check(near(x["rest_deg"], 0) and near(x["girth"], 1.0), "M2 jeans: pose skipped (rest 0, girth 1)")
        check(x["gain"] == 0 and x["max_deg"] == 0 and x["gravity"] == 0 and x["translate"] == 0 and x["spill"] == 0
              and x["sag_max_deg"] == 0 and x["spill_max_deg"] == 0, "M2 H4: the covered collider group rests")
        check(m2.get("held") == {"X": {"pose": "raised", "state": "covered", "by": ["jeans"]}},
              f"M2 held {m2.get('held')}")
        m3 = motion_payload("Smoke", prof({"bottom": "jeans", "underwear_bottom": "briefs"}))
        x = m3["groups"]["X"]
        check(near(x["rest_deg"], 0) and near(x["gain"], 1.0), "M3 hidden: pose skipped, no H4 (gain 1.0)")
        check(m3.get("held") == {"X": {"pose": "raised", "state": "hidden", "by": ["briefs", "jeans"]}},
              f"M3 held {m3.get('held')}")
        real_free = outfit_renderer.is_free_text_wardrobe
        outfit_renderer.is_free_text_wardrobe = lambda p: True
        try:
            m4 = motion_payload("Smoke", prof(outfit_worn=True, outfit_description="plain clothes"))
        finally:
            outfit_renderer.is_free_text_wardrobe = real_free
        x = m4["groups"]["X"]
        check(near(x["rest_deg"], 0) and x["gain"] == 0
              and m4.get("held") == {"X": {"pose": "raised", "state": "covered", "by": []}},
              f"M4 free text dressed: as M2, by [] ({m4.get('held')})")
        m5 = motion_payload("Smoke", prof({"bottom": "jeans"}), apply_clothing=False)
        x = m5["groups"]["X"]
        check(near(x["rest_deg"], 80) and near(x["girth"], 1.2) and "held" not in m5, "M5 apply_clothing False: as M1")
        check(near(m2["groups"]["Z"]["rest_deg"], 80) and near(m2["groups"]["Z"]["girth"], 1.2)
              and m2["groups"]["Z"]["gain"] > 0, "M6 Z without requires: the pose applies under jeans, no H4")
        m8 = motion_payload("Smoke", prof({"bottom": "jeans"}, switch="on"))
        check("Y" not in m8["groups"] and "Y" in motion_payload("Smoke", prof(switch="on"))["groups"],
              "M8 the part-only group falls away under jeans (as at BASE), present nude")
        # A1-A4 condition atoms.
        from app.core.prompt_filters import _triggered_filters

        def evaluate_condition(condition, name, profile):
            # One state with ``condition``: does it trigger (the atom path every state condition takes)?
            return bool(list(_triggered_filters(name, "", profile, _definitions=[{"id": "", "condition": condition}])))
        check(evaluate_condition("exposed:X", "Smoke", profile=prof())
              and not evaluate_condition("exposed:X", "Smoke", profile=prof({"bottom": "jeans"})),
              "A1 exposed:X nude yes, under jeans no")
        check(evaluate_condition("not covered:X", "Smoke", profile=prof())
              and not evaluate_condition("not covered:X", "Smoke", profile=prof({"bottom": "jeans"})),
              "A2 not covered:X as A1")
        check(not evaluate_condition("exposed:X", "Smoke", profile={"template": ""}),
              "A3 a character without X: exposed:X false")
        check(evaluate_condition("covered:Y", "Smoke", profile=prof({"bottom": "jeans"}, switch="on"))
              and not evaluate_condition("covered:Y", "Smoke", profile=prof(switch="on")),
              "A4 covered:Y under jeans true (rig_groups_unclothed), nude false")
        # M7 rev against BASE.
        base_tree = root / "base_tree"
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "-q", str(base_tree), BASE], check=True)
        try:
            new_rev = rev_of(ROOT, root, True)
            base_rev = rev_of(base_tree, root, False)
        finally:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(base_tree)], check=False)
        print("  revs:", new_rev, base_rev)
        check(new_rev == base_rev and not new_rev.startswith("error"), "M7 rev with the new fields == BASE without them")
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
