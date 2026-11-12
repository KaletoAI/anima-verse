#!/usr/bin/env python3
"""The item mode ``outfit_piece.mesh_mode`` replaces the ``own_mesh`` flag
(plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 2;
spec ``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md``,
"The model" and builder-check ruling 4).

Usage:
    ./.venv/bin/python scripts/smoke_mesh_mode_item.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no GPU, no server. Every expectation is
derived by hand below from the plan's Global Constraints ("Kind default (spec
Q2): slots exactly ``feet`` → own mesh; ``outer`` in slots, or both ``top``
and ``bottom`` → in the body; everything else → painted") and Task 2's
Interfaces block.

[1] default_mesh_mode — the kind default:
    ["feet"] -> "own_mesh" (exactly feet); ["outer"] -> "in_body" (outer);
    ["top", "bottom"] -> "in_body" (both top and bottom); ["top"] ->
    "painted"; ["legs", "feet"] -> "painted" (feet, but not alone);
    ["head"] -> "painted". MESH_MODES == ("own_mesh", "painted", "in_body").
    mesh_mode_of: None for a non-outfit-piece (a tool, a hair garment, None).
[2] add_item stores the mode:
    Boots {"slots": ["feet"]} -> outfit_piece.mesh_mode "own_mesh" (the kind
    default), no "own_mesh" key; garment_kind_of -> "footwear" (own mesh,
    feet alone). Coat {"slots": ["outer"]} -> "in_body"; garment_kind_of None
    (in the body is no own mesh). Blouse {"slots": ["top"], "mesh_mode":
    "own_mesh"} -> "own_mesh", garment_kind_of "clothing". Tee {"slots":
    ["top"], "own_mesh": True} -> "painted" (the input flag is ignored: the
    top default), no "own_mesh" key, garment_kind_of None.
[3] update_item:
    Blouse {"outfit_piece": {"slots": ["top"]}} -> keeps "own_mesh" (the
    update does not name the mode). {"slots": ["top"], "mesh_mode": "bogus"}
    -> "painted" (the top default). {"slots": ["top"], "own_mesh": True} ->
    still "painted", no "own_mesh" key written. An unrelated update
    ({"name": "silk blouse"}) keeps "painted".
    Legacy: a Vest stored RAW (SQL into ``items.pieces``) as {"slots":
    ["top"], "own_mesh": true} — written before the mode existed. An
    update_item of its name drops the flag (no carry-through since Task 3:
    the boot migration ``figure_migration`` judged every stored flag into
    the mode) and writes NO "mesh_mode"; an outfit_piece update without a
    mode (slots ["top"]) still writes neither; mesh_mode_of(vest) ==
    "painted" (the top default), garment_kind_of None.
[4] The wanted figure (Task 6 replaced the interim base_body.outfit_body_mode,
    which is gone): its shape is meshed iff a worn piece has mode "in_body";
    no profile key is read. meshed = (in_body, shape not plain); Demo is on
    the base-body pipeline (off it every piece is painted).
    Demo's profile carries outfit_body_mode "mesh" and wears Shirt (top,
    painted) + Trousers (bottom, painted) -> ([], False) (was "retexture").
    Equip the Coat (outer, in_body) -> ([coat], True) (was "mesh").
    pieces={"outer": coat} -> ([coat], True), pieces={"top": shirt} -> ([],
    False), pieces={} -> ([], False). Coat updated to mesh_mode "painted" ->
    ([], False); back to "in_body" -> ([coat], True).
[5] Code and template:
    no dict anywhere in shared/templates/character/base-character.json has
    "key" == "outfit_body_mode" or a key "outfit_body_mode"; no section id
    "outfit_body" (the Outfit bodies section "outfit_bodies" stays).
    The FLAG is read nowhere in app/ but the boot migration
    ``app/core/figure_migration.py`` (Task 3): the lines of
    ``git grep --untracked -n own_mesh -- app`` that name it as a key —
    ``"own_mesh"`` / ``'own_mesh'`` in quotes or ``.own_mesh`` — other than
    the mode constant ``OWN_MESH, PAINTED, IN_BODY = "own_mesh", …`` of
    garment_set.py, are all in app/core/figure_migration.py. (A bare
    ``git grep -c own_mesh`` cannot be the check: ``own_mesh`` is also the
    name of the mode value, so docstrings and identifiers about own-mesh
    pieces keep it.) Fails on the old code: the same scan at 136313bb (the
    task's BASE) names garment_set.py and outfit_options.py
    (``piece.get("own_mesh")``), and 136313bb's garment_set.py has no
    ``def default_mesh_mode``. model3d_pipeline has no after_mode_switch.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "136313bb"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


_KEY_READ = re.compile(r"""["']own_mesh["']|\.own_mesh\b""")
_MODE_CONSTANT = 'OWN_MESH, PAINTED, IN_BODY = "own_mesh", "painted", "in_body"'


def flag_readers(rev=None):
    """Files under app/ whose lines name ``own_mesh`` as a key (block [5])."""
    cmd = ["git", "grep"] + ([] if rev else ["--untracked"]) + ["-n", "own_mesh"] + ([rev] if rev else []) + ["--", "app"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout
    files = set()
    for line in out.splitlines():
        path, _, text = line.split(":", 2) if not rev else line.split(":", 3)[1:]
        if _MODE_CONSTANT in text or not _KEY_READ.search(text):
            continue
        files.add(path)
    return sorted(files)


def template_names_mode(node):
    if isinstance(node, dict):
        if node.get("key") == "outfit_body_mode" or "outfit_body_mode" in node or node.get("id") == "outfit_body":
            return True
        return any(template_names_mode(v) for v in node.values())
    if isinstance(node, list):
        return any(template_names_mode(v) for v in node)
    return False


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mesh-mode-item-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import garment_set

        print("[1] kind default")
        if not hasattr(garment_set, "default_mesh_mode"):
            check("garment_set.default_mesh_mode exists", False, True)
            print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
            return 1
        d = garment_set.default_mesh_mode
        check("feet", d(["feet"]), "own_mesh")
        check("outer", d(["outer"]), "in_body")
        check("top + bottom", d(["top", "bottom"]), "in_body")
        check("top", d(["top"]), "painted")
        check("legs + feet", d(["legs", "feet"]), "painted")
        check("head", d(["head"]), "painted")
        check("MESH_MODES", garment_set.MESH_MODES, ("own_mesh", "painted", "in_body"))
        check("constants", (garment_set.OWN_MESH, garment_set.PAINTED, garment_set.IN_BODY),
              ("own_mesh", "painted", "in_body"))
        check("mode of a tool", garment_set.mesh_mode_of({"category": "tool"}), None)
        check("mode of a hair garment", garment_set.mesh_mode_of({"category": "garment", "garment": {"kind": "hair"}}),
              None)
        check("mode of None", garment_set.mesh_mode_of(None), None)

        from app.models import inventory

        def add(name, op):
            return inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a plain {name}",
                                      outfit_piece=op)["id"]

        def piece(item_id):
            return inventory.get_item(item_id).get("outfit_piece") or {}

        def kind(item_id):
            return garment_set.garment_kind_of(inventory.get_item(item_id))

        print("[2] add_item")
        boots = add("Boots", {"slots": ["feet"]})
        check("boots mode", piece(boots).get("mesh_mode"), "own_mesh")
        check("boots: no own_mesh key", "own_mesh" in piece(boots), False)
        check("boots kind", kind(boots), "footwear")
        coat = add("Coat", {"slots": ["outer"]})
        check("coat mode", piece(coat).get("mesh_mode"), "in_body")
        check("coat kind", kind(coat), None)
        blouse = add("Blouse", {"slots": ["top"], "mesh_mode": "own_mesh"})
        check("blouse mode", piece(blouse).get("mesh_mode"), "own_mesh")
        check("blouse kind", kind(blouse), "clothing")
        tee = add("Tee", {"slots": ["top"], "own_mesh": True})
        check("tee: input flag ignored -> top default", piece(tee).get("mesh_mode"), "painted")
        check("tee: no own_mesh key", "own_mesh" in piece(tee), False)
        check("tee kind", kind(tee), None)

        print("[3] update_item")
        inventory.update_item(blouse, {"outfit_piece": {"slots": ["top"]}})
        check("no mode named -> kept", piece(blouse).get("mesh_mode"), "own_mesh")
        inventory.update_item(blouse, {"outfit_piece": {"slots": ["top"], "mesh_mode": "bogus"}})
        check("bogus -> top default", piece(blouse).get("mesh_mode"), "painted")
        inventory.update_item(blouse, {"outfit_piece": {"slots": ["top"], "own_mesh": True}})
        check("input own_mesh alone -> mode unchanged", piece(blouse).get("mesh_mode"), "painted")
        check("input own_mesh not written", "own_mesh" in piece(blouse), False)
        inventory.update_item(blouse, {"name": "silk blouse"})
        check("unrelated update keeps the mode", piece(blouse).get("mesh_mode"), "painted")

        vest = add("Vest", {"slots": ["top"]})
        raw = {k: v for k, v in piece(vest).items() if k != "mesh_mode"}
        raw["own_mesh"] = True
        with db.transaction() as conn:
            conn.execute("UPDATE items SET pieces=? WHERE id=?", (json.dumps(raw), vest))
        from app.core.motion_item_cache import invalidate
        invalidate()
        check("legacy fixture stored raw", (piece(vest).get("own_mesh"), "mesh_mode" in piece(vest)), (True, False))
        inventory.update_item(vest, {"name": "Old vest"})
        check("legacy: name update drops own_mesh", "own_mesh" in piece(vest), False)
        check("legacy: name update writes no mode", "mesh_mode" in piece(vest), False)
        check("legacy: name stored", inventory.get_item(vest).get("name"), "Old vest")
        inventory.update_item(vest, {"outfit_piece": {"slots": ["top"]}})
        check("legacy: piece update writes no own_mesh", "own_mesh" in piece(vest), False)
        check("legacy: piece update writes no mode", "mesh_mode" in piece(vest), False)
        check("legacy: mode meanwhile = top default", garment_set.mesh_mode_of(inventory.get_item(vest)), "painted")
        check("legacy: kind", kind(vest), None)

        print("[4] the wanted figure's shape follows the worn modes")
        from app.core import base_body, figure
        from app.models.character import get_character_profile, save_character_profile
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "outfit_body_mode": "mesh"}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo (the figure is a pipeline notion)", base_body.set_pipeline("Demo", True), True)
        shirt = add("Shirt", {"slots": ["top"]})
        trousers = add("Trousers", {"slots": ["bottom"]})
        check("shirt/trousers painted", (piece(shirt).get("mesh_mode"), piece(trousers).get("mesh_mode")),
              ("painted", "painted"))
        for item in (shirt, trousers, coat):
            check(f"inventory {item}", inventory.add_to_inventory("Demo", item), True)
        for item in (shirt, trousers):
            check(f"equip {item}", inventory.equip_piece("Demo", item, source="smoke")["status"], "ok")
        def meshed(**kw):
            """(in-body pieces, shape meshed) of the wanted figure."""
            fig = figure.wanted_figure("Demo", **kw)
            return list(fig.in_body), not figure.is_plain(fig.shape)

        check("the per-character mode is gone", hasattr(base_body, "outfit_body_mode"), False)
        check("profile key still says mesh", get_character_profile("Demo").get("outfit_body_mode"), "mesh")
        check("painted only -> plain body", meshed(), ([], False))
        check("equip coat", inventory.equip_piece("Demo", coat, source="smoke")["status"], "ok")
        check("coat worn -> a shape", meshed(), ([coat], True))
        check("coat worn (profile passed) -> a shape", meshed(profile=get_character_profile("Demo")), ([coat], True))
        check("pieces outer coat -> a shape", meshed(pieces={"outer": coat}), ([coat], True))
        check("pieces top shirt -> plain body", meshed(pieces={"top": shirt}), ([], False))
        check("pieces {} -> plain body", meshed(pieces={}), ([], False))
        inventory.update_item(coat, {"outfit_piece": {"slots": ["outer"], "mesh_mode": "painted"}})
        check("coat painted -> plain body", meshed(), ([], False))
        inventory.update_item(coat, {"outfit_piece": {"slots": ["outer"], "mesh_mode": "in_body"}})
        check("coat in the body again -> a shape", meshed(), ([coat], True))

    print("[5] code and template")
    template = json.loads((ROOT / "shared/templates/character/base-character.json").read_text(encoding="utf-8"))
    check("template names no outfit_body_mode / outfit_body section", template_names_mode(template), False)
    check("outfit bodies section stays",
          any(s.get("id") == "outfit_bodies" for s in template.get("sections") or []), True)
    check("own_mesh key read only in figure_migration.py", flag_readers(), ["app/core/figure_migration.py"])
    from app.core import model3d_pipeline
    check("after_mode_switch gone", hasattr(model3d_pipeline, "after_mode_switch"), False)
    base_readers = flag_readers(BASE)
    check(f"old code {BASE}: garment_set + outfit_options read the flag",
          {"app/core/garment_set.py", "app/core/outfit_options.py"} <= set(base_readers), True)
    base_set = subprocess.run(["git", "show", f"{BASE}:app/core/garment_set.py"], cwd=ROOT,
                              capture_output=True, text=True).stdout
    check(f"old code {BASE}: garment_set read", bool(base_set), True)
    check(f"old code {BASE}: no default_mesh_mode", "def default_mesh_mode" in base_set, False)

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
