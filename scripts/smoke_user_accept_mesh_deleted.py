"""Smoke: a USER-accepted clothing fit stays served when its mesh in use was deleted, and is voided only by another
stored mesh (A198, review 05 #2; ``garment_store.user_accept_holds``).

Usage:
    ./.venv/bin/python scripts/smoke_user_accept_mesh_deleted.py

No server, no world DB: ``garment_store.garment_path`` is pointed at a temp file (the rule is about that one path).
Derived by hand from the rule "a user's acceptance is bound to the mesh it saw; deleting the mesh in use keeps the fit
served until the next fit" (``garment_mesh_delete`` docstring):
  [1] prepared mesh present, sha == recorded prepared_sha256 -> holds (True)
  [2] prepared mesh present, other bytes                     -> void (False)
  [3] prepared mesh deleted                                  -> holds (True)   (pre-fix: False — sha "" != recorded)
  [4] record without user_accepted                           -> True whatever the file

Pre-fix proof: at e846d7d02 case [3] returns False (``file_sha256`` of a missing path is "").
"""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_fit, garment_store as gs  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


with tempfile.TemporaryDirectory(prefix="a198-accept-") as tmp:
    prepared = Path(tmp) / "item_x_0123456789ab.glb"
    gs.garment_path = lambda *a, **k: prepared   # the one path the rule reads
    data = b"mesh the user saw"
    prepared.write_bytes(data)
    record = {"kind": "clothing", "item_id": "item_x", "fsig": "0123456789ab", "body_id": "",
              "fit_version": garment_fit.FIT_VERSION["clothing"], "user_accepted": {"at": "x"},
              "inputs": {"prepared_sha256": hashlib.sha256(data).hexdigest()}}
    check("[1] same mesh -> holds", gs.user_accept_holds(record, "Demo") is True)
    prepared.write_bytes(b"another mesh, regenerated")
    check("[2] replaced mesh -> void", gs.user_accept_holds(record, "Demo") is False)
    prepared.unlink()
    check("[3] deleted mesh -> holds", gs.user_accept_holds(record, "Demo") is True)
    plain = {k: v for k, v in record.items() if k != "user_accepted"}
    check("[4] no user acceptance -> True", gs.user_accept_holds(plain, "Demo") is True)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
