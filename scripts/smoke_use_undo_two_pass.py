"""Smoke: Undo of a "Use this" checks every kept copy before it touches a file — a damaged copy refuses the undo
with the group untouched, never half-restored (A198, review 05 #15).

Usage:
    ./.venv/bin/python scripts/smoke_use_undo_two_pass.py

No server, no world DB: ``garment_use_undo.state`` / ``undo_dir`` / ``_read_manifest`` and the store root are
stubbed onto a temp folder. Manifest in this order: ``a.png`` made since (sha None -> to remove), ``b.png`` kept
(copy intact, target differs -> to restore), ``c.png`` kept but its copy DAMAGED (sha differs). By hand:
  -> UndoUnavailable "damaged"; a.png still there, b.png still the NEW bytes (pre-fix e846d7d02: a.png removed and
     b.png restored before the damage was found).
"""
import hashlib
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_mesh, garment_use_undo as gu  # noqa: E402
from app.core import garment_store as gs  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


def sha(b):
    return hashlib.sha256(b).hexdigest()


with tempfile.TemporaryDirectory(prefix="a198-undo-") as tmp:
    root, folder = Path(tmp) / "garments", Path(tmp) / "snap"
    root.mkdir()
    folder.mkdir()
    (root / "a.png").write_bytes(b"made since")
    (root / "b.png").write_bytes(b"NEW")
    (folder / "b.png").write_bytes(b"OLD")
    (root / "c.png").write_bytes(b"NEW-C")
    (folder / "c.png").write_bytes(b"DAMAGED")
    manifest = {"files": {"a.png": None, "b.png": sha(b"OLD"), "c.png": sha(b"OLD-C")}}
    gu.state = lambda c, i, f: {"available": True, "step": "ghost", "view": "front", "attempt": 1}
    gu.undo_dir = lambda c, i, f: folder
    gu._read_manifest = lambda f: manifest
    gs._root = lambda c: root

    @contextmanager
    def lock(c, i):
        yield
    garment_mesh.mesh_lock = lock
    gu._mesh_attempts = lambda c, i, f: []
    try:
        gu.undo("Demo", "item_x", "0123456789ab")
        check("refused", False, "undone")
    except gu.UndoUnavailable as e:
        check("refused as damaged", "damaged" in str(e), e)
    check("a.png untouched", (root / "a.png").is_file())
    check("b.png untouched (the new bytes)", (root / "b.png").read_bytes() == b"NEW", (root / "b.png").read_bytes())

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
