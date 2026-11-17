"""Smoke: the plain body served dressed (Ruling A119) drops the attached part a worn piece covers (A168 item 1).

Usage:
    ./.venv/bin/python scripts/smoke_assembly_hides_covered_part.py

No server, no world DB: one fake package slot with a separate mesh part, ``covered_by: [bottom, underwear_bottom]``,
rig groups ``g_chain`` + ``g_bone``; items are fakes. Expected values derived by hand from the rule
(``body_slots.is_slot_exposed``: a closed piece ON or ``covers``-ing a slot of ``covered_by`` hides it; the mesh mode
plays no part; a piece worn open covers nothing):

  A trousers on ``bottom`` (own mesh)                        -> covered -> ["g_bone", "g_chain"]
  B a shirt on ``top`` only                                  -> exposed -> []
  C a dress on ``top`` that ``covers: [underwear_bottom]``    -> covered -> ["g_bone", "g_chain"]
  D underwear on ``underwear_bottom`` in mode in_body         -> covered -> ["g_bone", "g_chain"]
  E trousers on ``bottom`` worn open                          -> exposed -> []
  F no pieces                                                 -> []   (``_hidden_parts``: nothing worn)

GLB: two mesh nodes, the second marked ``extras.attached_part = "g_chain"``; dropping ["g_bone", "g_chain"] leaves
exactly one node with a mesh ("body"), the part node keeps its place without mesh/skin. ``_current`` is False when the
sidecar's ``hidden_parts`` differs from the wanted list (a stored assembly from before this fix carries none).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke-a168-")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp
from app.core import paths  # noqa: E402

paths.init(_tmp)

from app.core import fit_attempts, garment_assembly, outfit_renderer  # noqa: E402
import app.plugins.registry as registry  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")
    print(("ok   " if got == want else "FAIL ") + label)


slot = SimpleNamespace(id="lower", mesh_part=SimpleNamespace(switch="part"), covered_by=["bottom", "underwear_bottom"],
                       rigs=[SimpleNamespace(id="g_chain"), SimpleNamespace(id="g_bone")])
registry.packages = lambda: [SimpleNamespace(body_slots=[slot])]
ITEMS = {
    "trousers": {"outfit_piece": {"slots": ["bottom"], "covers": [], "mesh_mode": "own_mesh"}},
    "shirt": {"outfit_piece": {"slots": ["top"], "covers": ["underwear_top"], "mesh_mode": "template"}},
    "dress": {"outfit_piece": {"slots": ["top"], "covers": ["underwear_bottom"], "mesh_mode": "painted"}},
    "under": {"outfit_piece": {"slots": ["underwear_bottom"], "covers": [], "mesh_mode": "in_body"}},
}
outfit_renderer._get_item = lambda iid: ITEMS.get(iid)
import app.core.outfit_options as outfit_options  # noqa: E402

_real_states = outfit_options.piece_states
outfit_options.piece_states = lambda profile, worn: {i: profile.get("_open", {}).get(i, "closed") for i in worn.values()}

both = ["g_bone", "g_chain"]
check("A trousers on bottom", fit_attempts.covered_part_groups_of({"bottom": "trousers"}, {}), both)
check("B shirt on top", fit_attempts.covered_part_groups_of({"top": "shirt"}, {}), [])
check("C dress covers underwear_bottom", fit_attempts.covered_part_groups_of({"top": "dress"}, {}), both)
check("D underwear in_body", fit_attempts.covered_part_groups_of({"underwear_bottom": "under"}, {}), both)
check("E trousers worn open", fit_attempts.covered_part_groups_of({"bottom": "trousers"},
                                                                  {"_open": {"trousers": outfit_options.OPEN}}), [])
check("F nothing worn", garment_assembly._hidden_parts("nobody", {"pieces": {}}), [])

# GLB: drop the part node's mesh.
from app.core.glb_mesh import pack_glb  # noqa: E402
from app.core.model_validate import parse_glb  # noqa: E402

gltf = {"asset": {"version": "2.0"}, "scenes": [{"nodes": [0, 1]}], "scene": 0,
        "nodes": [{"name": "body", "mesh": 0}, {"name": "Part", "mesh": 1, "extras": {"attached_part": "g_chain"}}],
        "meshes": [{"primitives": []}, {"primitives": []}], "buffers": [{"byteLength": 4}]}
blob = pack_glb(gltf, b"\0\0\0\0")
out = parse_glb(fit_attempts.without_covered_parts(blob, both))["gltf"]
check("GLB meshes left", [n["name"] for n in out["nodes"] if "mesh" in n], ["body"])
check("GLB part node kept", [n["name"] for n in out["nodes"]], ["body", "Part"])

d = Path(_tmp)
bare, assembled = d / "s.glb", d / "assembled" / "s.glb"
assembled.parent.mkdir()
bare.write_bytes(b"x")
bare.with_suffix(".json").write_text("{}")
assembled.write_bytes(b"y")
assembled.with_suffix(".json").write_text(json.dumps({"bare_revision": garment_assembly.bare_revision(bare),
                                                      "garments": {}}))
check("_current old sidecar, nothing hidden", garment_assembly._current(assembled, bare, {}, []), True)
check("_current old sidecar, part hidden now", garment_assembly._current(assembled, bare, {}, both), False)

outfit_options.piece_states = _real_states
if failures:
    print("\n".join(failures))
    sys.exit(1)
print("all ok")
