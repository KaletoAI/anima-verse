"""A177: a shell piece's fit (mesh mode "Shell from the body") reads due when one of its piece-only (ghost) views
was replaced after the shell was made — the shell's inputs are those views, not a prepared mesh.

Hand-derived (``garments._fit_state``, everything else held current by stubs: same body, current fit version,
same fit settings):
  * ghost front/back bytes equal to the recorded shas            -> "accepted"
  * ghost back replaced (other bytes)                             -> "outdated"
  * ghost front replaced                                          -> "outdated"
  * record without ghost shas (older record) and replaced views   -> "accepted" (left alone)
  * shell_version older than garment_shell.SHELL_VERSION          -> "stale" (unchanged rule, checked first)
Fails on 485b51e63 (the replaced-view cases answered "accepted").

Usage: ./.venv/bin/python scripts/smoke_shell_inputs_due.py
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = Path(tempfile.mkdtemp())
os.environ["STORAGE_DIR"] = str(tmp)
from app.core import paths  # noqa: E402
paths.init(str(tmp))
from app.core import garment_fit, garment_shell, garments  # noqa: E402
from app.core import garment_store as gs  # noqa: E402
from app.core import model_geometry  # noqa: E402

fit = tmp / "fit.glb"
fit.write_bytes(b"glb")
ghost = {"front": tmp / "ghost_front.png", "back": tmp / "ghost_back.png"}
gs.garment_path = lambda c, i, f, kind, **kw: fit if kind == "fit" else tmp / f"{kind}.bin"
garments._image = lambda c, i, f, step, view, attempt=0: ghost[view]
model_geometry.record_matches = lambda record, sha: True
garment_fit.expected_fit_version = lambda record: record.get("fit_version")
garments._settings_changed = lambda *a, **k: False


def sha(b):
    return hashlib.sha256(b).hexdigest()


def state(front, back, record_shas=True, version=garment_shell.SHELL_VERSION):
    ghost["front"].write_bytes(front)
    ghost["back"].write_bytes(back)
    inputs = {"mesh_shape": "shell", "shell_version": version}
    if record_shas:
        inputs.update(ghost_front_sha256=sha(b"F1"), ghost_back_sha256=sha(b"B1"))
    fit.with_suffix(".json").write_text(json.dumps({"accepted": True, "kind": "clothing", "fit_version": 1,
                                                    "inputs": inputs}))
    return garments._fit_state("X", "item", "fsig", "basesha")


fails = 0
for label, got, want in (("views unchanged", state(b"F1", b"B1"), "accepted"),
                         ("back replaced", state(b"F1", b"B2"), "outdated"),
                         ("front replaced", state(b"F2", b"B1"), "outdated"),
                         ("record without shas", state(b"F2", b"B2", record_shas=False), "accepted"),
                         ("older shell version", state(b"F2", b"B2", version=garment_shell.SHELL_VERSION - 1),
                          "stale")):
    ok = got == want
    fails += not ok
    print("OK  " if ok else "FAIL", label, got, "want", want)
print("FAILED" if fails else "ALL OK")
sys.exit(1 if fails else 0)
