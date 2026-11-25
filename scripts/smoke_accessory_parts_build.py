"""Smoke: a host builds its linked parts (plan-anhaenger Task 4, design G) — the geometry inputs, the build and its
store, the graft, the figure steps (one mesh step per part) and the review-focus cases "part image replaced" and
"part deleted".

Usage: ./.venv/bin/python scripts/smoke_accessory_parts_build.py   (no server; a temp world, a temp shared library,
       the puppet rig ``shared/models/rig/puppet.glb`` as the plain body, monkeypatched base / character dir)

The part mesh: a box 30 × 40 × 5 mm stored as ``jewellery/item_p/<psig>/raw.glb`` with ``record.json {accepted: true}``
under the psig of the part's image (``accessory_pendant.current_psig``). The part's own size is 30 mm (charm block),
its mount flat. Hosts: belt ``item_a`` (buckle → item_p) and belt ``item_b`` (buckle → item_p), both ``band.layer: body``
(nothing under them).

Expected, by hand from the plan's interfaces:

[1] ``geometry_inputs`` of item_a with the part ready: ``parts == [["buckle", 0, "item_p", <psig>, 30.0, 0.0, "flat",
    0.0, False]]`` (size from the part, at_deg 0 for a buckle, drop 0, no flip).
[2] the same without the mesh: no ``parts`` key, and the asig equals that of the same belt without a buckle.
[3] ``build`` → current; the record's ``parts[0].item == "item_p"``; the npz holds ``P0V``; ``graft_accessory`` → a node
    ``garment_accessory_item_a_p0`` whose extras say ``part: buckle`` and ``part_item: item_p``.
[4] both hosts worn, the part's mesh missing → ``_accessory_steps`` plans exactly ONE ``pendant`` step, item_id
    ``item_p``, manual, 1 job, its label naming both hosts ("Copper Belt", "Second Belt").
[4b] item_a current (built before the mesh existed), its part missing → ``pendant`` (item_p) then ``accessory``
    (item_a, manual == ``PART_MANUAL``). A worn host without links (item_c, current) gets no ``accessory`` step.
[4c] a ``pendant`` step for item_p whose job fails (``accessory_pendant.run`` → failed "x") → ``_run_pendant`` names
    the failure; ``_item_jobs(steps, "pieces", "item_a") == 0`` (the part step is no piece step); the host's part row
    carries the failure, no row is keyed by the part.
[4d] earrings E with style drop, current, own drop mesh missing → ``pendant`` (item_id E) then ``accessory`` (E,
    manual) — as before part items.
[4e] the buckle's mesh refused / failed / load-blocked / running (a record written by hand, ``_RUNNING``) → each
    part row's reason on the BELT names neither a chain nor a pendant (review finding: a belt row read "the chain is
    shown without it").
[5] the part's image replaced → its state ``missing`` (new psig), item_a's state ``due`` with the part's reason
    "Linked buckle not built yet — Build mesh spends 1 hub job", and no job is started.
[6] the part deleted (``delete_item``) → ``part_states[0].state == "gone"``; the build runs and its record carries no
    parts.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_parts_build_")
SHARED = Path(tempfile.mkdtemp(prefix="smoke_parts_build_shared_"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_parts_build_clips_")
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import db  # noqa: E402

db.init_schema()
import numpy as np  # noqa: E402
import app.models.inventory as inv  # noqa: E402

inv._get_shared_dir = lambda: SHARED
import app.models.character as mc  # noqa: E402
from app.core import (accessory_build as ab, accessory_parts as parts, accessory_pendant as ap,  # noqa: E402
                      figure_build as fb, glb_mesh, model_geometry)

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


PUPPET = (ROOT / "shared/models/rig/puppet.glb").read_bytes()
cdir = Path(TMP) / "char"
(cdir / "model3d").mkdir(parents=True)
(cdir / "model3d" / "base1.glb").write_bytes(PUPPET)
store = Path(TMP) / "store"
store.mkdir()
ab.store_dir = lambda _c: store
ab._current_base = lambda _c, _p: ("base1", "SHA1")
mc.get_character_dir = lambda _c: cdir
model_geometry.record_matches = lambda rec, sha, **_k: rec.get("base_model_sha256") == sha
model_geometry.stamp_on = lambda *a, **k: {}


def set_image(item_id, data):
    d = Path(TMP) / "items" / item_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "image.png").write_bytes(data)
    inv.set_item_image(item_id, "image.png")


def box_glb():
    V = np.array([[sx * 0.015, sy * 0.020, sz * 0.0025] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return glb_mesh.static_glb(V, F, np.zeros((8, 2)))


def store_mesh(item_id):
    psig = ap.current_psig(item_id)
    d = ap.pendant_dir(item_id, psig)
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw.glb").write_bytes(box_glb())
    (d / "record.json").write_text(json.dumps({"accepted": True, "psig": psig, "hub_jobs": 1}))
    return psig


inv.add_item("Oak Buckle", category="outfit_piece", item_id="item_p", prompt_fragment="a copper oak-leaf buckle",
             outfit_piece={"slots": [], "jewellery": {"kind": "charm"}})
set_image("item_p", b"part-image-1")
BELT = {"kind": "belt", "band": {"layer": "body"}, "buckle": {"item": "item_p"}}
inv.add_item("Copper Belt", category="outfit_piece", item_id="item_a", prompt_fragment="copper belt",
             outfit_piece={"slots": ["outer"], "mesh_mode": "accessory", "jewellery": BELT})
inv.add_item("Second Belt", category="outfit_piece", item_id="item_b", prompt_fragment="black belt",
             outfit_piece={"slots": ["outer"], "mesh_mode": "accessory", "jewellery": BELT})
inv.add_item("Plain Belt", category="outfit_piece", item_id="item_c", prompt_fragment="plain belt",
             outfit_piece={"slots": ["outer"], "mesh_mode": "accessory",
                           "jewellery": {"kind": "belt", "band": {"layer": "body"}}})
spec_a = ab.accessory_spec_size  # keep a reference so the import is used
from app.core import accessory_spec  # noqa: E402

SPEC_A = accessory_spec.of_item(inv.get_item("item_a"))
SPEC_C = accessory_spec.of_item(inv.get_item("item_c"))

# [2] before the mesh exists
st = ab.accessory_state("Puppet", "item_a", profile={})
check("[2] part missing", [p["state"] for p in st["parts"]], ["missing"])
check("[2] no parts key", "parts" in ab.geometry_inputs(SPEC_A, parts.ready_inputs(st["parts"]), st["context"]), False)
check("[2] asig as without a buckle", ab.asig(SPEC_A, [], st["context"]), ab.asig(SPEC_C, [], st["context"]))

# [4b] item_a built before the mesh existed → current; then the part is missing
pre = ab.build("Puppet", "item_a", profile={})
check("[4b] built without the part", (pre["state"], "parts" in (pre["record"] or {})), ("current", False))
ab.build("Puppet", "item_c", profile={})
steps = fb._accessory_steps("Puppet", ["item_a", "item_c"], {})
check("[4b] pendant(item_p) then accessory(item_a, manual)",
      [(s.name, s.item_id, s.manual) for s in steps],
      [("pendant", "item_p", fb.PART_MANUAL), ("accessory", "item_a", fb.PART_MANUAL)])

# [4] two worn hosts, one part
steps = fb._accessory_steps("Puppet", ["item_a", "item_b"], {})
pend = [s for s in steps if s.name == "pendant"]
check("[4] one pendant step", [(s.item_id, s.jobs, bool(s.manual)) for s in pend], [("item_p", 1, True)])
check("[4] label names both hosts", "Copper Belt" in pend[0].label and "Second Belt" in pend[0].label, True)
print("       " + pend[0].label)

# [4c]
ap_run = ap.run
ap.run = lambda _i: {"state": "failed", "reason": ap.REASON_FAILED.format(error="x")}
try:
    out = fb._run_pendant("Puppet", pend[0])
except Exception as e:  # noqa: BLE001
    out = str(e)
check("[4c] the failure is named", "x" in str(out), True)
ap.run = ap_run
check("[4c] no piece jobs for the host", fb._item_jobs(steps, "pieces", "item_a"), 0)

# [4e] role-neutral reasons on a belt
psig0 = ap.current_psig("item_p")
d0 = ap.pendant_dir("item_p", psig0)
d0.mkdir(parents=True, exist_ok=True)
seen = {}
for failure in ("gate", "backend", "load"):
    (d0 / "record.json").write_text(json.dumps({"accepted": False, "failure": failure, "error": "x"}))
    row = parts.part_states(SPEC_A)[0]
    seen[row["state"] + ":" + failure] = row["reason"]
(d0 / "record.json").unlink()
ap._RUNNING.add("item_p")
row = parts.part_states(SPEC_A)[0]
seen[row["state"]] = row["reason"]
ap._RUNNING.discard("item_p")
check("[4e] states", sorted(seen), ["failed:backend", "missing:load", "refused:gate", "running"])
check("[4e] no chain / pendant words on a belt row",
      {k: v for k, v in seen.items() if "chain" in v.lower() or "pendant" in v.lower()}, {})
for k, v in sorted(seen.items()):
    print(f"       {k}: {v}")

# [1] / [3] the mesh exists
psig = store_mesh("item_p")
st = ab.accessory_state("Puppet", "item_a", profile={})
check("[1] parts input", ab.geometry_inputs(SPEC_A, parts.ready_inputs(st["parts"]), st["context"]).get("parts"),
      [["buckle", 0, "item_p", psig, 30.0, 0.0, "flat", 0.0, False]])
check("[1] state due with the part reason", (st["state"], st["reason"]), ("due", ab.REASON_PART))
built = ab.build("Puppet", "item_a", profile={})
rec = built["record"] or {}
check("[3] current", built["state"], "current")
check("[3] record parts", [(p["item"], p["role"]) for p in rec.get("parts") or []], [("item_p", "buckle")])
check("[3] part errors", rec.get("part_errors"), {})
with np.load(ab.npz_path("Puppet", "item_a", rec)) as z:
    check("[3] npz P0V", "P0V" in z.files, True)
out = ab.graft_accessory(PUPPET, "Puppet", "item_a", rec, rec["asig"])
gl = glb_mesh._parse(out, "x")["gltf"]
node = [n for n in gl["nodes"] if n.get("name") == "garment_accessory_item_a_p0"]
check("[3] graft node", len(node), 1)
check("[3] node extras", {k: ((node[0].get("extras") or {}).get("garment") or {}).get(k) for k in ("part", "part_item")},
      {"part": "buckle", "part_item": "item_p"})
row = ab.part_rows(built, SPEC_A, rec)
check("[3] part row on the figure", [(r["item"], r["state"], r["on_figure"]) for r in row],
      [("item_p", "ready", True)])
m = rec["parts"][0]["metrics"]
print(f"       depth {m.get('depth_mm')} mm, size {m.get('size_mm')} mm, rest gap {m['poses']['rest']['gap_min_mm']} mm")
check("[4c] no figure note keyed by the part", any(r["item"] == "item_a" for r in row), False)

# [4d] earrings with their own drop
inv.add_item("Drops", category="outfit_piece", item_id="item_e", prompt_fragment="drop earrings",
             outfit_piece={"slots": ["head"], "mesh_mode": "accessory",
                           "jewellery": {"kind": "earrings", "earring": {"style": "drop"}}})
set_image("item_e", b"earring-image")
_acc = fb._accessory_step
fb._accessory_step = lambda c, i, p: None if i == "item_e" else _acc(c, i, p)
steps = fb._accessory_steps("Puppet", ["item_e"], {})
check("[4d] drop then earrings (manual)", [(s.name, s.item_id, bool(s.manual)) for s in steps],
      [("pendant", "item_e", True), ("accessory", "item_e", True)])
fb._accessory_step = _acc

# [5] the part's image replaced
started = []
ap.start = lambda i: started.append(i) or True
set_image("item_p", b"part-image-2")
st = ab.accessory_state("Puppet", "item_a", profile={})
check("[5] part missing again", [p["state"] for p in st["parts"]], ["missing"])
check("[5] host due with the part's reason", (st["state"], st["reason"]),
      ("due", "Linked buckle not built yet — Build mesh spends 1 hub job"))
check("[5] no job started", started, [])

# [6] the part deleted
inv.delete_item("item_p")
st = ab.accessory_state("Puppet", "item_a", profile={})
check("[6] gone", [p["state"] for p in st["parts"]], ["gone"])
print("       " + st["parts"][0]["reason"])
b6 = ab.build("Puppet", "item_a", profile={})
check("[6] built without it", (b6["state"], (b6["record"] or {}).get("parts")), ("current", None))

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
