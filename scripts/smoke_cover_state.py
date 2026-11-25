"""One cover rule for an extension group under clothing: ``extension_rig.cover_state`` /
``cover_state_for`` (exposed / covered / hidden), the manifest fields behind it, and its
equivalence with the two rules it replaces.

Usage: ./.venv/bin/python scripts/smoke_cover_state.py

THE RULE (``cover_state``), every slot name compared after ``strip().lower()``:
  1. For every piece in ``pieces`` whose id is not in ``open_ids``: ON = the slots it occupies (its keys in
     ``pieces`` and its ``outfit_piece.slots``); FULL = ON plus ``covers``; PART = ``partially_covers``.
  2. No piece touches a slot of ``covered_by`` (full or part)               -> exposed
  3. A piece without ``outfit_piece.exposed_detail: true`` sits ON a slot of a DECLARED ``hide_under``
     (without the key: covers a ``covered_by`` slot FULLY, the rule before ``hide_under``) -> hidden
  3b. For a group with ``drape_collider``: a piece without ``exposed_detail`` covers a ``covered_by`` slot FULLY
     in a mesh mode outside ``garment_set.BODY_COLLIDER_MODES`` (template, in_body; the default mode is in_body)
                                                                             -> hidden
  4. otherwise                                                               -> covered

Fixtures: G = {covered_by [bottom, underwear_bottom], hide_under [underwear_bottom]},
T = {covered_by [top, underwear_top, outer], hide_under [underwear_top]},
D = {covered_by [bottom, underwear_bottom]} (no hide_under).

Hand-derived expectations:
  C1  G, {}                                      exposed  (rule 2: nothing worn)
  C2  G, {bottom: jeans}                         covered  (bottom in covered_by, not in hide_under -> rule 4)
  C3  G, {bottom: jeans, underwear_bottom: briefs}  hidden (briefs fully on underwear_bottom -> rule 3)
  C4  G, {underwear_bottom: briefs(exposed_detail)} covered (rule 3 excepts exposed_detail -> rule 4)
  C5  G, {top: dress(covers [underwear_bottom])} covered  (a ``covers`` of a declared hide_under slot is not ON it
      -> not rule 3; it touches covered_by -> rule 4)
  C5b D, {top: dress(covers [underwear_bottom])} hidden   (no declared hide_under -> a FULL cover hides, rule 3)
  C5c G, {bottom: jeans_c(covers [underwear_bottom])} covered (the world's trousers: on bottom, cover the underwear
      slot from outside -> rule 4); + {underwear_bottom: briefs} -> hidden (briefs ON underwear_bottom, rule 3)
  C6  G, {top: longshirt(partially_covers [bottom])} covered (part touches covered_by -> not rule 2; no full hit)
  C7  G, {top: shirt(partially_covers [underwear_bottom])} covered (a part cover is never rule 3)
  C8  T, {top: shirt} covered; T, {top, underwear_top: bra} hidden; T, {outer: jacket(covers [underwear_top])}
      covered (covers, not on -> rule 4)
  C9  G, {bottom: jeans}, open_ids {jeans}       exposed  (an open piece is skipped in rule 1)
  C10 D, {bottom: jeans}                         hidden   (hide_under = covered_by -> today's rule)
  C11 parse errors (ValueError): hide_under [feet] on covered_by [bottom] (must be a subset, like
      clothing_lift_default); drape_collider inflate .02 (> .01); drape_collider radius 0 (< .002);
      poses.raised.requires "covered" (only "exposed"); a region hide_under outside covered_by.
      Not an error: pieces_of([a, b], {a: slots [top], b: slots [top]}) -> {top: a} (smaller id wins).
  C12 spelling: G' = {covered_by [Bottom, UNDERWEAR_BOTTOM], hide_under [" underwear_bottom"]}:
      {BOTTOM: jeans} covered, {bottom: jeans, Underwear_Bottom: briefs} hidden — after strip().lower()
      the same inputs as C2 / C3.
  C13 free text (``cover_state_for``): a free-text wardrobe with outfit_worn true and no pieces -> covered,
      outfit_worn false -> exposed, a group with empty covered_by -> exposed. Counter-check:
      ``cover_state(G, {}, {})`` of the same situation is exposed, so the free-text rule lives in the wrapper only.
  C15 mesh mode (rule 3b): GC = G + drape_collider, TC = T + drape_collider.
      GC {bottom: jeans shell} hidden, own_mesh hidden, accessory hidden; template covered; in_body covered;
      no mesh_mode (default in_body) covered. G (no drape_collider) {bottom: jeans shell} covered (3b needs the
      collider). GC {bottom: shell + exposed_detail} covered (3b excepts it). GC {top: longshirt shell
      (partially_covers [bottom])} covered (3b needs a FULL cover). TC {top: bandeau shell} hidden — the shell top
      of a figure without underwear (no collider for the tips), as on the covered variant before the plan.
  C14 open (``cover_state_for``): equipped_pieces {bottom: jeans}, jeans stored open -> exposed (C9 via
      ``outfit_renderer.covering_pieces``).

EQUIVALENCE (plan task 2) against the old rules at BASE d0bae1f34 (the commit before this plan; never HEAD):
  For all 2^6 assignments of one piece to each of {top, underwear_top, outer, bottom, underwear_bottom, feet},
  without partial covers and open pieces, for groups WITHOUT hide_under:
    hides_exposed_detail(new) == hides_exposed_detail(BASE)               64/64
    (cover_state != exposed) == (not is_slot_exposed at BASE)             64/64
  Partial-cover cases where they MUST differ (plan Review Focus 1):
    P1 exposed_only G region, {top: shirt(partially_covers [bottom])}: BASE hides_exposed_detail True
       (a partial cover counted fully there), new False (covered, never hidden).
    P2 part slot covered_by [bottom, underwear_bottom], same outfit: BASE is_slot_exposed True (the part showed),
       new covered (the part is hidden in the assembly).
  channels_sig: a fixture region with and without ``hide_under`` gives the same ``wanted_channels`` sig, equal to
  the sig BASE computes (hide_under is taken out of the hashed blob).
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import types
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "d0bae1f34"

FAILS = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def item(iid, slots, **piece):
    return {"id": iid, "outfit_piece": {"slots": list(slots), **piece}}


def base_source(rel):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:{rel}"], check=True,
                          capture_output=True, text=True).stdout


def base_functions(rel, names, extra_globals=None):
    """The top-level functions ``names`` of ``rel`` at BASE, executed in a fresh namespace."""
    tree = ast.parse(base_source(rel))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    module = ast.Module(body=nodes, type_ignores=[])
    import typing
    ns = {name: getattr(typing, name) for name in ("Any", "Dict", "List", "Optional", "Set", "Tuple", "Iterable")}
    ns.update(extra_globals or {})
    exec(compile(module, f"<{BASE}:{rel}>", "exec"), ns)
    return ns


def main():
    with tempfile.TemporaryDirectory(prefix="cover-state-") as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "w")
        paths.init_instance(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "rig.fbx")
        from app.core import extension_rig as er

        G = {"covered_by": ["bottom", "underwear_bottom"], "hide_under": ["underwear_bottom"]}
        T = {"covered_by": ["top", "underwear_top", "outer"], "hide_under": ["underwear_top"]}
        D = {"covered_by": ["bottom", "underwear_bottom"]}
        items = {
            "jeans": item("jeans", ["bottom"]),
            "briefs": item("briefs", ["underwear_bottom"]),
            "briefs_x": item("briefs_x", ["underwear_bottom"], exposed_detail=True),
            "dress": item("dress", ["top"], covers=["underwear_bottom"]),
            "longshirt": item("longshirt", ["top"], partially_covers=["bottom"]),
            "shirt_p": item("shirt_p", ["top"], partially_covers=["underwear_bottom"]),
            "shirt": item("shirt", ["top"]),
            "bra": item("bra", ["underwear_top"]),
            "jacket": item("jacket", ["outer"], covers=["underwear_top"]),
            "jeans_c": item("jeans_c", ["bottom"], covers=["underwear_bottom"]),
            "jeans_shell": item("jeans_shell", ["bottom"], mesh_mode="shell"),
            "jeans_own": item("jeans_own", ["bottom"], mesh_mode="own_mesh"),
            "jeans_acc": item("jeans_acc", ["bottom"], mesh_mode="accessory"),
            "jeans_tpl": item("jeans_tpl", ["bottom"], mesh_mode="template"),
            "jeans_body": item("jeans_body", ["bottom"], mesh_mode="in_body"),
            "jeans_shell_x": item("jeans_shell_x", ["bottom"], mesh_mode="shell", exposed_detail=True),
            "longshirt_shell": item("longshirt_shell", ["top"], mesh_mode="shell", partially_covers=["bottom"]),
            "bandeau_shell": item("bandeau_shell", ["top"], mesh_mode="shell"),
        }
        cs = er.cover_state
        check(cs(G, {}, items) == er.EXPOSED, "C1 nothing worn -> exposed")
        check(cs(G, {"bottom": "jeans"}, items) == er.COVERED, "C2 trousers without underwear -> covered")
        check(cs(G, {"bottom": "jeans", "underwear_bottom": "briefs"}, items) == er.HIDDEN,
              "C3 trousers + underwear -> hidden")
        check(cs(G, {"underwear_bottom": "briefs_x"}, items) == er.COVERED, "C4 exposed_detail underwear -> covered")
        check(cs(G, {"top": "dress"}, items) == er.COVERED, "C5 covers of a declared hide_under slot -> covered")
        check(cs(D, {"top": "dress"}, items) == er.HIDDEN, "C5b no declared hide_under: covers hides as before")
        check(cs(G, {"bottom": "jeans_c"}, items) == er.COVERED, "C5c trousers covering the underwear slot -> covered")
        check(cs(G, {"bottom": "jeans_c", "underwear_bottom": "briefs"}, items) == er.HIDDEN,
              "C5c same trousers + underwear -> hidden")
        check(cs(G, {"top": "longshirt"}, items) == er.COVERED, "C6 partial cover of bottom -> covered")
        check(cs(G, {"top": "shirt_p"}, items) == er.COVERED, "C7 partial cover of hide_under -> covered, never hidden")
        check(cs(T, {"top": "shirt"}, items) == er.COVERED, "C8a top without underwear -> covered")
        check(cs(T, {"top": "shirt", "underwear_top": "bra"}, items) == er.HIDDEN, "C8b top + underwear -> hidden")
        check(cs(T, {"outer": "jacket"}, items) == er.COVERED, "C8c jacket covering underwear_top -> covered")
        check(cs(G, {"bottom": "jeans"}, items, open_ids={"jeans"}) == er.EXPOSED, "C9 open piece -> exposed")
        check(cs(D, {"bottom": "jeans"}, items) == er.HIDDEN, "C10 no hide_under -> covered_by -> hidden")

        # C15 mesh modes without a body collider.
        GC = {**G, "drape_collider": {"inflate": 0.003, "radius": None}}
        TC = {**T, "drape_collider": {"inflate": 0.002, "radius": 0.0045}}
        for iid, want in (("jeans_shell", er.HIDDEN), ("jeans_own", er.HIDDEN), ("jeans_acc", er.HIDDEN),
                          ("jeans_tpl", er.COVERED), ("jeans_body", er.COVERED), ("jeans", er.COVERED),
                          ("jeans_shell_x", er.COVERED)):
            check(cs(GC, {"bottom": iid}, items) == want, f"C15 GC {iid} -> {want}")
        check(cs(G, {"bottom": "jeans_shell"}, items) == er.COVERED, "C15 G (no drape_collider) shell -> covered")
        check(cs(GC, {"top": "longshirt_shell"}, items) == er.COVERED, "C15 GC partial shell -> covered")
        check(cs(TC, {"top": "bandeau_shell"}, items) == er.HIDDEN, "C15 TC shell top -> hidden")
        check(cs(TC, {"top": "shirt"}, items) == er.COVERED, "C15 TC in-body top -> covered")

        # C11 parse errors.
        from app.plugins.registry import RegionSpec, RigSpec
        rig = {"id": "g", "op": "appendage_chain", "chains": [[{"bone": "SmokeBone", "parent": "Hips"}]]}

        def rejects(raw, label, covered_by=("bottom",)):
            try:
                RigSpec.parse(raw, covered_by=list(covered_by))
            except ValueError:
                check(True, f"C11 {label} rejected")
            else:
                check(False, f"C11 {label} rejected")
        rejects({**rig, "hide_under": ["feet"]}, "hide_under outside covered_by")
        rejects({**rig, "drape_collider": {"inflate": 0.02}}, "drape_collider inflate .02")
        rejects({**rig, "drape_collider": {"inflate": 0.002, "radius": 0}}, "drape_collider radius 0")
        rejects({**rig, "drape_collider": {"radius": 0.004}}, "drape_collider without inflate")
        rejects({**rig, "poses": {"raised": {"rest_deg": 80, "requires": "covered"}}}, "requires covered")
        ok = RigSpec.parse({**rig, "hide_under": [" Bottom "], "drape_collider": {"inflate": 0.003},
                            "poses": {"raised": {"rest_deg": 80, "requires": "exposed"}}},
                           covered_by=["bottom", "underwear_bottom"])
        check(ok.hide_under == ["bottom"] and ok.drape_collider == {"inflate": 0.003, "radius": None}
              and ok.pose_requires == {"raised": "exposed"} and ok.poses == {"raised": {"rest_deg": 80.0}},
              "C11 valid fields parse; requires leaves poses numeric only")
        region = {"id": "r", "kind": "channel", "bone": "Hips", "offset": [0, 0, 0], "axis": [0, 1, 0],
                  "depth": .05, "radius": .01, "cone_deg": 20, "funnel": .01, "accepts": {"ops": ["attached_part"]}}
        try:
            RegionSpec.parse({**region, "hide_under": ["feet"]}, {}, [], covered_by=["bottom"])
        except ValueError:
            check(True, "C11 region hide_under outside covered_by rejected")
        else:
            check(False, "C11 region hide_under outside covered_by rejected")
        check(RegionSpec.parse({**region, "hide_under": ["Bottom"]}, {}, [], covered_by=["bottom"]).hide_under
              == ["bottom"], "C11 region hide_under parses")
        check(er.pieces_of(["b", "a"], {"a": item("a", ["top"]), "b": item("b", ["Top"])}) == {"top": "a"},
              "C11 pieces_of: a slot two pieces claim goes to the smaller id")

        # C12 spelling.
        G2 = {"covered_by": ["Bottom", "UNDERWEAR_BOTTOM"], "hide_under": [" underwear_bottom"]}
        check(cs(G2, {"BOTTOM": "jeans"}, items) == er.COVERED, "C12 mixed case -> covered (as C2)")
        check(cs(G2, {"bottom": "jeans", "Underwear_Bottom": "briefs"}, items) == er.HIDDEN,
              "C12 mixed case -> hidden (as C3)")

        # C13 free text, C14 open pieces (cover_state_for).
        from app.core import outfit_renderer, outfit_options
        real_free = outfit_renderer.is_free_text_wardrobe
        outfit_renderer.is_free_text_wardrobe = lambda profile: (profile or {}).get("template") == "free"
        try:
            worn = {"template": "free", "outfit_worn": True, "outfit_description": "a coat"}
            check(er.cover_state_for(G, worn, items=items) == er.COVERED, "C13 free text worn -> covered")
            check(er.cover_state_for(G, {**worn, "outfit_worn": "false"}, items=items) == er.EXPOSED,
                  "C13 free text undressed -> exposed")
            check(er.cover_state_for({"covered_by": []}, worn, items=items) == er.EXPOSED,
                  "C13 no covered_by -> exposed")
            check(cs(G, {}, items) == er.EXPOSED, "C13 counter-check: cover_state alone sees nothing worn")
        finally:
            outfit_renderer.is_free_text_wardrobe = real_free
        real_states = outfit_options.piece_states
        outfit_options.piece_states = lambda profile, pieces=None: {"jeans": outfit_options.OPEN}
        try:
            prof = {"template": "", "equipped_pieces": {"bottom": "jeans"}}
            check(er.cover_state_for(G, prof, items=items) == er.EXPOSED, "C14 open trousers -> exposed")
        finally:
            outfit_options.piece_states = real_states
        check(er.cover_state_for(G, {"template": "", "equipped_pieces": {"bottom": "jeans"}}, items=items)
              == er.COVERED, "C14 closed trousers -> covered")

        # Equivalence with BASE.
        old_er = base_functions("app/core/extension_rig.py", {"piece_covering_slots", "hides_exposed_detail"})
        slots6 = ["top", "underwear_top", "outer", "bottom", "underwear_bottom", "feet"]
        all_items = {f"i_{s}": item(f"i_{s}", [s]) for s in slots6}

        old_bs = base_functions("app/core/body_slots.py", {"is_slot_exposed"})

        def old_is_slot_exposed(covered_by, pieces):
            # BASE body_slots.is_slot_exposed with no open pieces and synthetic items.
            ns = old_bs
            fake = types.ModuleType("fake_outfit_renderer")
            fake.is_free_text_wardrobe = lambda profile: False
            fake.is_outfit_worn = lambda profile: True
            fake.covering_pieces = lambda profile, equipped: dict(equipped)
            fake.collect_covered_slots = lambda equipped: {
                str(c).strip().lower() for iid in equipped.values()
                for c in (all_items.get(iid, {}).get("outfit_piece") or {}).get("covers") or []}
            saved = sys.modules.get("app.core.outfit_renderer")
            sys.modules["app.core.outfit_renderer"] = fake
            try:
                return ns["is_slot_exposed"](types.SimpleNamespace(covered_by=covered_by),
                                             {"equipped_pieces": pieces})
            finally:
                sys.modules["app.core.outfit_renderer"] = saved
        same_hides = same_exposed = 0
        groups = [{"exposed_only": True, "covered_by": ["bottom", "underwear_bottom"]},
                  {"exposed_only": True, "covered_by": ["top", "underwear_top", "outer"]}]
        for mask in product((0, 1), repeat=6):
            pieces = {s: f"i_{s}" for s, on in zip(slots6, mask) if on}
            if er.hides_exposed_detail(groups, pieces, all_items) == old_er["hides_exposed_detail"](
                    groups, pieces, all_items):
                same_hides += 1
            if all((cs(g, pieces, all_items) != er.EXPOSED) == (not old_is_slot_exposed(g["covered_by"], pieces))
                   for g in groups):
                same_exposed += 1
        check(same_hides == 64, f"equivalence: hides_exposed_detail new == BASE ({same_hides}/64)")
        check(same_exposed == 64, f"equivalence: cover_state != exposed == not is_slot_exposed@BASE ({same_exposed}/64)")
        shirt = {"i_shirt": item("i_shirt", ["top"], partially_covers=["bottom"])}
        gx = [{"exposed_only": True, "covered_by": ["bottom", "underwear_bottom"]}]
        check(old_er["hides_exposed_detail"](gx, {"top": "i_shirt"}, shirt) is True
              and er.hides_exposed_detail(gx, {"top": "i_shirt"}, shirt) is False,
              "P1 partial cover: BASE hides the exposed_only group, new keeps it (covered)")
        all_items.update(shirt)
        check(old_is_slot_exposed(["bottom", "underwear_bottom"], {"top": "i_shirt"}) is True
              and cs({"covered_by": ["bottom", "underwear_bottom"]}, {"top": "i_shirt"}, all_items) == er.COVERED,
              "P2 partial cover: BASE leaves the part exposed, new counts it covered")

        # channels_sig with and without hide_under, against BASE.
        check_channels_sig(root)
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        sys.exit(1)
    print("ALL OK")


def check_channels_sig(root):
    """Same sig with and without ``hide_under`` in the manifest, and the BASE sig, for one fixture region."""
    import yaml
    region = {"id": "smoke_channel", "kind": "channel", "bone": "Hips", "offset": [0, 0, 0.01],
              "axis": [0, 1, 0], "depth": 0.05, "radius": 0.01, "cone_deg": 20, "funnel": 0.01,
              "accepts": {"ops": ["attached_part"]}}
    script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.core import paths
paths.init(Path(sys.argv[2]) / "w"); paths.init_instance(Path(sys.argv[2]) / "instance")
from app.core import config, db
db.init_schema()
paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "smoke_pkg"}}))
config.load(paths.get_config_path(), instance_path=Path(sys.argv[2]) / "instance/config.json")
from app.plugins.loader import discover_packages
discover_packages(Path(sys.argv[3]), force=True)
from app.core.collision_channels import wanted_channels
wanted, sig = wanted_channels("Nobody", None, {}, profile={"template": "human-default"})
print(json.dumps([len(wanted), sig]))
'''
    sigs = {}
    base_tree = root / "base_tree"
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "-q", str(base_tree), BASE], check=True)
    try:
        for label, tree, with_hide in (("new", ROOT, False), ("new+hide_under", ROOT, True), ("base", base_tree, False)):
            plugins = root / f"plugins_{label.replace('+', '_')}"
            pkg = plugins / "smoke_pkg"
            pkg.mkdir(parents=True)
            (pkg / "plugin.yaml").write_text(yaml.safe_dump({
                "name": "Smoke", "apply_to": "*", "body_slots": [{
                    "id": "smoke_slot", "covered_by": ["bottom", "underwear_bottom"],
                    "regions": [{**region, **({"hide_under": ["underwear_bottom"]} if with_hide else {})}]}]}))
            out = subprocess.run([sys.executable, "-c", script, str(tree), str(root / f"s_{len(sigs)}"), str(plugins)],
                                 capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            sigs[label] = out.stdout.strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else \
                f"error: {out.stderr.strip()[-300:]}"
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(base_tree)], check=False)
    print("  channels_sig:", json.dumps(sigs))
    check(sigs["new"] == sigs["new+hide_under"] == sigs["base"] and sigs["base"].startswith("[1,"),
          "channels_sig: one wanted channel; with / without hide_under == BASE")


if __name__ == "__main__":
    main()
