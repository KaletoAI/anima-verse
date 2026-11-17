"""A177: a face cleanup of the CURRENT version that found nothing to change ("skipped", e.g. eyes not found)
counts as current; the base Run all then does not plan the cleanup again after every run (Gelina,
2026-11-17: ``face_cleanup {status: skipped, version: 5, reapplied: true}`` was listed due forever).

Hand-derived expectations (``model3d.face_cleanup_state``, switch on, humanoid, mesher bytes retained):
  * skipped, version == VERSION              -> can_reapply False (already run at this version)
  * skipped, no version ("disabled" record)  -> can_reapply True  (never ran; switch is on now)
  * skipped, version == VERSION - 1          -> can_reapply True  (older algorithm)
  * applied, version == VERSION              -> can_reapply False (unchanged rule)
Fails on 485b51e63 (the first case answered True).

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_skipped_current.py
"""
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
from app.core import face_cleanup, model3d  # noqa: E402

root = tmp / "m3d"
(root / "unrigged" / "mesher").mkdir(parents=True)
sig = "basesig"
(root / "unrigged" / f"{sig}.glb").write_bytes(b"x")
(root / "unrigged" / "mesher" / f"{sig}.glb").write_bytes(b"x")
model3d.get_model3d_dir = lambda name: root
model3d.get_model3d_options = lambda name: {"face_cleanup": True, "face_before_rig": True}
model3d.required_rig = lambda name: "mixamo"

V = face_cleanup.VERSION
fails = 0
for record, want in (({"status": "skipped", "version": V, "reapplied": True}, False),
                     ({"status": "skipped", "reason": "disabled for this character"}, True),
                     ({"status": "skipped", "version": V - 1}, True),
                     ({"status": "applied", "version": V}, False)):
    (root / "unrigged" / f"{sig}.json").write_text(json.dumps({"face_cleanup": record}))
    got = model3d.face_cleanup_state("X", sig)["can_reapply"]
    ok = got == want
    fails += not ok
    print("OK  " if ok else "FAIL", record, "can_reapply", got, "want", want)
print("FAILED" if fails else "ALL OK")
sys.exit(1 if fails else 0)
