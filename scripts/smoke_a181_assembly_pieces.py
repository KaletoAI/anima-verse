"""A181 — a draped template's sparse shape keys no longer leave the figure bare, and a failed garment assembly
is the Build's error.

Usage: ./.venv/bin/python scripts/smoke_a181_assembly_pieces.py

Live symptom (Kai, 2026-11-17): Build → "Assemble the figure done", the figure stayed naked. The garment
assembly ran in the background and failed for every tier with "Sparse geometry accessors are unsupported": the
T-shirt template drape (Blender export) stores its pose shapes as sparse morph targets. The Build never saw it.

Expected values, derived by hand from glTF 2.0 § 3.6.2.3 (sparse accessors):

a) A VEC3 float accessor, count 4, no bufferView (base = zeros), sparse count 2, indices [1, 3] (u16), values
   [(1, 0, 0), (0, 2, 0)] → dense [[0,0,0], [1,0,0], [0,0,0], [0,2,0]].
b) The same sparse part over a bufferView base [(5,5,5)] * 4 → [[5,5,5], [1,0,0], [5,5,5], [0,2,0]].
c) Old code (pinned 9d56c428e) raises ValueError on a) — the live failure.
d) ``figure_build._run_assemble`` with a garment assembly that fails with "boom" returns
   ``ASSEMBLY_FAILED.format(error="boom")`` = "Pieces not put on — the garment assembly failed: boom";
   a manual run (explicit=True) schedules with retry=True, an automatic one with retry=False.
e) ``garment_assembly.schedule(retry=True)`` drops a failure memo of unchanged inputs (it would otherwise
   return False without a build): after it the memo for the key is gone.
"""
import os
import struct
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="a181-")
os.environ["STORAGE_DIR"] = TMP
from app.core import paths  # noqa: E402
paths.init(TMP)

import numpy as np  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILS.append(label)


def parsed(with_base: bool):
    base = struct.pack("<12f", *([5.0] * 12))
    idx = struct.pack("<2H", 1, 3)
    vals = struct.pack("<6f", 1, 0, 0, 0, 2, 0)
    binary = (base if with_base else b"") + idx + vals
    off = len(base) if with_base else 0
    views = ([{"buffer": 0, "byteOffset": 0, "byteLength": len(base)}] if with_base else []) + [
        {"buffer": 0, "byteOffset": off, "byteLength": 4},
        {"buffer": 0, "byteOffset": off + 4, "byteLength": 24}]
    first = 1 if with_base else 0
    acc = {"componentType": 5126, "type": "VEC3", "count": 4,
           "sparse": {"count": 2, "indices": {"bufferView": first, "componentType": 5123},
                      "values": {"bufferView": first + 1}}}
    if with_base:
        acc["bufferView"] = 0
    return {"gltf": {"accessors": [acc], "bufferViews": views}, "bin": binary}


from app.core import glb_mesh  # noqa: E402

print("a) sparse over zeros")
check("dense", glb_mesh.accessor_array(parsed(False), 0).tolist(),
      [[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 2, 0]])
print("b) sparse over a bufferView base")
check("dense", glb_mesh.accessor_array(parsed(True), 0).tolist(),
      [[5, 5, 5], [1, 0, 0], [5, 5, 5], [0, 2, 0]])

print("c) old code refuses (pinned 9d56c428e)")
old = subprocess.run(["git", "show", "9d56c428e:app/core/glb_mesh.py"], cwd=ROOT, capture_output=True, text=True)
if old.returncode == 0:
    mod = types.ModuleType("old_glb_mesh")
    sys.modules["old_glb_mesh"] = mod
    exec(compile(old.stdout, "old_glb_mesh.py", "exec"), mod.__dict__)
    try:
        mod.accessor_array(parsed(False), 0)
        check("old raises", "no error", "ValueError")
    except ValueError as e:
        check("old raises", str(e), "Sparse geometry accessors are unsupported")
else:
    print("  (pinned commit not available — skipped)")

print("d) the assembly step reports a failed garment assembly")
from app.core import base_body, figure_build, garment_assembly, model3d  # noqa: E402

wanted = types.SimpleNamespace(signature="sigA")
figure_build._now = lambda c: ({}, wanted, wanted, [])
model3d.ensure_covered_variant = lambda c: None
base_body.ensure_figure_views = lambda c, s: None
base_body.clear_assemble_refusal = lambda c, s: None
figure_build._outfit_model = lambda c, s: ""
calls = []
garment_assembly._input_key = lambda c, s: "inputs-1"


def fake_schedule(c, s=None, *, retry=False):
    calls.append(retry)
    garment_assembly._failed[(c, s)] = "inputs-1"
    garment_assembly._errors[(c, s)] = "boom"
    return True


real_schedule = garment_assembly.schedule
garment_assembly.schedule = fake_schedule
check("manual", figure_build._run_assemble("Kai", figure_build.Step("assemble", "x", 0), True),
      "Pieces not put on — the garment assembly failed: boom")
check("automatic", figure_build._run_assemble("Kai", figure_build.Step("assemble", "x", 0), False),
      "Pieces not put on — the garment assembly failed: boom")
check("retry flags", calls, [True, False])
garment_assembly._failed.clear()
garment_assembly._errors.clear()
check("no memo -> no failure", garment_assembly.failure("Kai", "sigA"), "")

print("e) schedule(retry=True) drops the memo")
garment_assembly.schedule = real_schedule
garment_assembly._failed[("Kai", "sigA")] = "inputs-1"
garment_assembly._errors[("Kai", "sigA")] = "boom"
garment_assembly._wanted_for = lambda *a, **k: []
model3d.get_model3d_dir = lambda c: Path(TMP) / "m"
garment_assembly.schedule("Kai", "sigA", retry=True)
check("memo gone", ("Kai", "sigA") in garment_assembly._failed, False)

print()
print("ALL OK" if not FAILS else f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
