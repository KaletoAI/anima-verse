#!/usr/bin/env python3
"""Smoke: "Delete all" of a garment keeps the files of an outfit body that is being fitted (review 05#14).

Usage:  ./.venv/bin/python scripts/smoke_mesh_delete_body_fit_lock.py

No world DB: ``paths.init(<tmp>)`` first; the item check, the cost estimate and the stored-group scan are replaced
by stubs, so only ``delete_all``'s own loop runs against real files in a temp ``garments/``.

Files (one group): ``g/a_prepared.glb`` (base body), ``bodies/ob00000001/a_fit.glb`` and
``bodies/ob00000002/a_fit.glb``. Another thread holds ``keyed_lock("garment_body_fit", "demo:ob00000001")`` while
``delete_all`` runs. Expected, by hand: 2 files deleted (the base one and ob00000002's), ``kept`` names exactly
``bodies/ob00000001/a_fit.glb``; that file still exists. On 69aeeba75 all 3 go and there is no ``kept``.
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="smoke_md_")
from app.core import paths  # noqa: E402
paths.init(TMP)

from app.core import garment_mesh, garment_mesh_delete as md, garment_store as gs  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402

root = Path(TMP) / "garments"
files = [root / "g" / "a_prepared.glb", root / "bodies" / "ob00000001" / "a_fit.glb",
         root / "bodies" / "ob00000002" / "a_fit.glb"]
for f in files:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
gs.garments_dir = lambda name: root
md._clothing_item = lambda *a: None
md._estimate = lambda *a, **k: {}
md._groups = lambda *a: {"f": list(files)}
md._undo_snapshots = lambda *a: []
garment_mesh.running_job = lambda *a, **k: None

held, release = threading.Event(), threading.Event()


def holder():
    with keyed_lock("garment_body_fit", "demo:ob00000001"):
        held.set()
        release.wait(10)


t = threading.Thread(target=holder)
t.start()
held.wait(10)
try:
    out = md.delete_all("demo", "a")
finally:
    release.set()
    t.join()
ok = (out["deleted"]["meshes"] == 2 and out.get("kept") == ["bodies/ob00000001/a_fit.glb (its body is being fitted)"]
      and files[1].is_file() and not files[0].exists() and not files[2].exists())
print(out)
print("all passed" if ok else "FAILED")
sys.exit(0 if ok else 1)
