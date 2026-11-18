"""Smoke: "Delete all meshes" also removes the piece's "Use this" Undo snapshots (they hold mesh copies an Undo would
bring back) and the preview counts them (A198, review 05 #13).

Usage:
    ./.venv/bin/python scripts/smoke_delete_all_undo_snapshot.py

No server, no world DB: the store root, the piece check, the locks and the estimate are stubbed onto a temp folder
with ``attempts/use/item_x_0123456789ab/`` (3 files: manifest + raw + prepared copy), a
``….pending`` of another fsig (1 file) and ``item_xy_0123456789ab/`` of ANOTHER item (1 file). By hand:
  [1] preview: meshes 4 (3 + 1; the other item's snapshot not counted)
  [2] delete_all: meshes 4; both snapshots of item_x gone, item_xy's kept
Pre-fix (e846d7d02): preview 0, delete_all 0, both snapshots still there.
"""
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_mesh, garment_mesh_delete as gmd  # noqa: E402
from app.core import garment_store as gs  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


with tempfile.TemporaryDirectory(prefix="a198-delete-") as tmp:
    root = Path(tmp) / "garments"
    use = root / "attempts" / "use"
    a = use / "item_x_0123456789ab"
    b = use / "item_x_abcdefabcdef.pending"
    other = use / "item_xy_0123456789ab"
    for d, n in ((a, 3), (b, 1), (other, 1)):
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"f{i}").write_bytes(b"x")
    gs._root = lambda c: root
    gs.garments_dir = lambda c: root
    gs._garment_kind = lambda i: "clothing"
    gs.GARMENT_STEPS = {"clothing": ("worn",)}
    gmd._clothing_item = lambda c, i: None
    gmd._groups = lambda c, i: {}
    gmd._estimate = lambda c, i, s="": {}

    class Lock:
        def __init__(self, c, i):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False
    gmd._RunLock = Lock

    @contextmanager
    def mlock(c, i):
        yield
    garment_mesh.mesh_lock = mlock
    check("[1] preview counts the snapshots", gmd.preview("Demo", "item_x")["files"]["meshes"] == 4,
          gmd.preview("Demo", "item_x")["files"])
    out = gmd.delete_all("Demo", "item_x")
    check("[2] delete_all counts them", out["deleted"]["meshes"] == 4, out)
    check("[2] item_x's snapshots gone, item_xy's kept", (a.exists(), b.exists(), other.exists()) == (False, False, True),
          (a.exists(), b.exists(), other.exists()))

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
