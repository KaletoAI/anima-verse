#!/usr/bin/env python3
"""Smoke: the hair meshes get their own routing — occasion ``hair_views_mesh``
for the hair views method (stored value ``edit_chain``), a per-character glob
for ``hair_source_mesh`` (subtract method), the one-time chain seed and the
Image-tab match fields.

Usage:  ./.venv/bin/python scripts/smoke_hair_views_mesh_route.py

User decision 2026-11-10: the hair views method's mesh ran on the shared
``mesh_garment`` occasion and could not be routed or overridden apart from the
clothing. No server, no network, no world DB: temp storage + temp instance,
fake backends in a real BackendPool, the chain rules through routing's test
seam ``_rules``, the character profile through a patched
``get_character_profile``, the image service through a recorder.

EXPECTED VALUES, DERIVED BY HAND FROM THE TASK BRIEF
[1] Catalog. get_occasion("hair_views_mesh") carries
      (media, category, rig, character_scoped, char_spec_field, char_spec_fallback)
      == ("mesh", "img2mesh", "none", True, "hair_views_mesh_workflow", "")
    and label "3D mesh — hair from views", covers "Hair tab: hair views method".
    get_occasion("hair_source_mesh") now is character-scoped on
      "hair_source_mesh_workflow", fallback "" (label unchanged).
    mesh_garment stays world-only (character_scoped False).
    hair_views_mesh sits right after mesh_garment in the catalog order.
[2] The mesh step picks its occasion by kind: garment_mesh.mesh_occasion
      "hair" -> "hair_views_mesh", "clothing" -> "mesh_garment".
    garment_mesh._attempt with the recorder service (it raises after
    recording, so nothing past the call runs): kind "hair" asks
    occasion "hair_views_mesh", kind "clothing" asks "mesh_garment"; both with
    character_name "Kira".
[3] Routing. Pool: "Trellis-A" and "Trellis-B" (mesh/img2mesh, cost 0, both
    up). Rules: hair_views_mesh ["Trellis-A"], mesh_garment ["Trellis-A"],
    hair_source_mesh ["Trellis-A"]. Kira's outfit_imagegen:
      hair_views_mesh_workflow "Trellis-B", hair_source_mesh_workflow "Trellis-B".
    chain_for("hair_views_mesh", "Kira") ==
      [("Trellis-B", "character", 0), ("Trellis-A", "rule", 1)]
    resolve_image_route("hair_views_mesh", character "Kira") -> Trellis-B,
      position 0 (the character glob runs first).
    resolve_image_route("mesh_garment", character "Kira") -> Trellis-A,
      position 1 (a world-only occasion reads no character glob).
    chain_for("hair_source_mesh", "Kira") ==
      [("Trellis-B", "character", 0), ("Trellis-A", "rule", 1)]
      and resolves to Trellis-B, position 0.
    Without the globs (character "Nobody"): both resolve to Trellis-A, position 1.
    The hair_views field is read by no other occasion:
      chain_for("hair_mesh", "Kira") == [] (no rule, no hair_mesh_workflow).
[4] Migration config._migrate_hair_mesh_routing:
    a. {mesh_garment: ["G1", "G2"]} -> hair_views_mesh == ["G1", "G2"], True;
       an independent copy (appending to it leaves mesh_garment at 2 entries);
       a second run -> False, nothing changes.
    b. {mesh_garment: ["G"], hair_views_mesh: ["X"]} -> False, ["X"] kept.
    c. {photo: ["P"]} (no source) -> False, routing exactly {photo: ["P"]};
       no image_generation at all -> False.
    d. Registered after the garment seed in _apply_file_migrations:
       {mesh_humanoid: ["U"]} -> mesh_garment ["U"] AND hair_views_mesh ["U"]
       (the garment seed runs first, the hair seed copies its result).
[5] Image-tab fields. character_ops.IMAGEGEN_MATCH_FIELDS ends with
      "hair_mesh_workflow", "hair_views_mesh_workflow", "hair_source_mesh_workflow".
    The template base-character.json section "image_3d" lists slot keys
      mesh_workflow, hair_mesh_workflow, hair_views_mesh_workflow,
      hair_source_mesh_workflow — the three hair keys each visible_when
      {"feature": "humanoid"}.
    routes.characters._image_match_chains (rules of [3]) has
      "hair_views_mesh_workflow" -> [{occasion hair_views_mesh, chain ["Trellis-A"]}]
      "hair_source_mesh_workflow" -> [{occasion hair_source_mesh, chain ["Trellis-A"]}].
"""
import atexit
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scratch(prefix):
    p = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, p, ignore_errors=True)
    return p


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("hvm-clips-")
os.environ["ANIMATION_RIG_FILE"] = str(Path(_scratch("hvm-rig-")) / "reference.fbx")
from app.core import paths  # noqa: E402
paths.init(_scratch("hvm-storage-"))
paths.init_instance(_scratch("hvm-instance-"))

from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.imagegen import occasions as occ  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name):
        super().__init__(name, "http://localhost", 0.0, "fake", "FAKE_HVM_")
        self.MEDIA_TYPE = "mesh"
        self.category = "img2mesh"
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = True

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"x"]


RULES = {}
routing._rules = lambda occasion: list(RULES.get(occasion, []))
PROFILES = {"Kira": {"outfit_imagegen": {"hair_views_mesh_workflow": "Trellis-B",
                                         "hair_source_mesh_workflow": "Trellis-B"}}}


def part1():
    print("[1] catalog")
    ids = occ.occasion_ids()
    check("hair_views_mesh in catalog", "hair_views_mesh" in ids, True)
    if "hair_views_mesh" not in ids:
        return
    o = occ.get_occasion("hair_views_mesh")
    check("hair_views_mesh values",
          (o["media"], o["category"], o["rig"], o["character_scoped"], o["char_spec_field"],
           o["char_spec_fallback"]),
          ("mesh", "img2mesh", "none", True, "hair_views_mesh_workflow", ""))
    check("hair_views_mesh label/covers", (o["label"], o["covers"]),
          ("3D mesh — hair from views", "Hair tab: hair views method"))
    s = occ.get_occasion("hair_source_mesh")
    check("hair_source_mesh scope",
          (s["character_scoped"], s["char_spec_field"], s["char_spec_fallback"]),
          (True, "hair_source_mesh_workflow", ""))
    check("mesh_garment world-only", occ.get_occasion("mesh_garment")["character_scoped"], False)
    check("order: right after mesh_garment", ids[ids.index("mesh_garment") + 1], "hair_views_mesh")


class _Recorded(Exception):
    pass


class Recorder:
    def __init__(self):
        self.calls = []

    def generate_mesh(self, **kw):
        self.calls.append(kw)
        raise _Recorded()


def part2():
    print("[2] the mesh step picks its occasion by kind")
    from app.core import garment_mesh as gm
    check("hair", gm.mesh_occasion("hair"), "hair_views_mesh")
    check("clothing", gm.mesh_occasion("clothing"), "mesh_garment")
    rec = Recorder()
    work = Path(_scratch("hvm-work-"))
    cut = {"front": work / "f.png", "back": work / "b.png"}
    with patch("app.imagegen.service.get_image_service", return_value=rec):
        for kind in ("hair", "clothing"):
            try:
                gm._attempt("Kira", kind, cut, work / "raw.glb", work / "cand.glb", 1)
            except _Recorded:
                pass
    check("asked occasions", [c.get("occasion") for c in rec.calls],
          ["hair_views_mesh", "mesh_garment"])
    check("character_name", [c.get("character_name") for c in rec.calls], ["Kira", "Kira"])


def part3():
    print("[3] routing: the character glob is position 0")
    pool = BackendPool([Fake("Trellis-A"), Fake("Trellis-B")])
    RULES.clear()
    RULES.update({"hair_views_mesh": ["Trellis-A"], "mesh_garment": ["Trellis-A"],
                  "hair_source_mesh": ["Trellis-A"]})
    with patch("app.models.character.get_character_profile",
               side_effect=lambda name: PROFILES.get(name, {})):
        for oid in ("hair_views_mesh", "hair_source_mesh"):
            check(f"{oid} chain", routing.chain_for(oid, "Kira"),
                  [("Trellis-B", "character", 0), ("Trellis-A", "rule", 1)])
            r = routing.resolve_image_route(oid, character="Kira", pool=pool)
            check(f"{oid} Kira", (r.backend.name if r.backend else None, r.position),
                  ("Trellis-B", 0))
            r = routing.resolve_image_route(oid, character="Nobody", pool=pool)
            check(f"{oid} without glob", (r.backend.name if r.backend else None, r.position),
                  ("Trellis-A", 1))
        r = routing.resolve_image_route("mesh_garment", character="Kira", pool=pool)
        check("mesh_garment reads no glob", (r.backend.name if r.backend else None, r.position),
              ("Trellis-A", 1))
        check("hair_mesh ignores the field", routing.chain_for("hair_mesh", "Kira"), [])


def part4():
    print("[4] migration")
    from app.core import config
    mig = getattr(config, "_migrate_hair_mesh_routing", None)
    if mig is None:
        check("_migrate_hair_mesh_routing exists", False, True)
        return
    cfg = {"image_generation": {"routing": {"mesh_garment": ["G1", "G2"]}}}
    check("a seeds", mig(cfg), True)
    r = cfg["image_generation"]["routing"]
    check("a copy", r.get("hair_views_mesh"), ["G1", "G2"])
    r["hair_views_mesh"].append("Z")
    check("a independent", r["mesh_garment"], ["G1", "G2"])
    snapshot = copy.deepcopy(cfg)
    check("a second run", mig(cfg), False)
    check("a unchanged", cfg, snapshot)
    cfg = {"image_generation": {"routing": {"mesh_garment": ["G"], "hair_views_mesh": ["X"]}}}
    check("b existing kept", (mig(cfg), cfg["image_generation"]["routing"]["hair_views_mesh"]),
          (False, ["X"]))
    cfg = {"image_generation": {"routing": {"photo": ["P"]}}}
    check("c no source", (mig(cfg), cfg["image_generation"]["routing"]), (False, {"photo": ["P"]}))
    check("c no image_generation", mig({}), False)
    cfg = {"image_generation": {"routing": {"mesh_humanoid": ["U"]}}}
    config._apply_file_migrations(cfg)
    r = cfg["image_generation"]["routing"]
    check("d file migrations", (r.get("mesh_garment"), r.get("hair_views_mesh")), (["U"], ["U"]))


def part5():
    print("[5] Image-tab fields")
    from app.core import character_ops
    check("match fields tail", character_ops.IMAGEGEN_MATCH_FIELDS[-3:],
          ("hair_mesh_workflow", "hair_views_mesh_workflow", "hair_source_mesh_workflow"))
    tpl = json.loads((Path(__file__).resolve().parent.parent
                      / "shared/templates/character/base-character.json").read_text(encoding="utf-8"))
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("id") == "image_3d":
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(tpl)
    keys = found[0].get("slot_keys", []) if found else []
    check("slot keys", [k["key"] if isinstance(k, dict) else k for k in keys],
          ["mesh_workflow", "hair_mesh_workflow", "hair_views_mesh_workflow",
           "hair_source_mesh_workflow"])
    check("hair keys humanoid only",
          [k.get("visible_when") for k in keys if isinstance(k, dict)],
          [{"feature": "humanoid"}] * 3)
    RULES.clear()
    RULES.update({"hair_views_mesh": ["Trellis-A"], "hair_source_mesh": ["Trellis-A"]})
    from app.routes import characters as rc
    with patch("app.imagegen.routing._rules", side_effect=lambda o: list(RULES.get(o, []))):
        chains = rc._image_match_chains()
    for field, oid in (("hair_views_mesh_workflow", "hair_views_mesh"),
                       ("hair_source_mesh_workflow", "hair_source_mesh")):
        check(f"{field} rows",
              [(r["occasion"], r["chain"]) for r in chains.get(field, [])], [(oid, ["Trellis-A"])])


def main():
    for part in (part1, part2, part3, part4, part5):
        try:
            part()
        except Exception as e:  # noqa: BLE001 — a crash is a failed part, the others still run
            check(f"{part.__name__} raised", repr(e), "no exception")
    if FAILS:
        print(f"\n{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
