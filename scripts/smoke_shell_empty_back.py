"""Smoke: a shell piece whose drafted back is EMPTY (nothing shows from behind, so no ghost back is made by design)
can be fitted — ``garment_shell.shell_views`` reads the back as an empty ghost mask over the base back instead of
asking for a ghost back that will never come (A198, review 06B #2).

Usage:
    ./.venv/bin/python scripts/smoke_shell_empty_back.py

No server, no world DB, no rembg: the file lookups and mask readers ``shell_views`` calls are stubbed onto a temp
folder holding only a ghost FRONT (4 x 3 px, white). Derived by hand:
  [1] skipped back (``skipped_view`` -> EMPTY_BACK): views {front, back}; back body_mask = the base back's flat mask
      (stub: 3 x 4 all True), ghost_mask all False (3 x 4), image zeros (3 x 4 x 3, uint8); front from the ghost.
  [2] back NOT skipped and no ghost back -> MissingInput "The ghost back image is missing" (unchanged).
Pre-fix (e846d7d02): [1] raises MissingInput too.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import base_body, garment_images as gi, garment_shell as gsh, garment_source  # noqa: E402
from app.core import garment_store as gs, model_refs, shell_base_views  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


with tempfile.TemporaryDirectory(prefix="a198-shell-back-") as tmp:
    root = Path(tmp)
    Image.new("RGB", (4, 3), "white").save(root / "ghost_front.png")
    (root / "base.png").write_bytes(b"x")
    gs.garment_path = lambda c, i, f, part, step="", view="", **k: root / f"{step}_{view}.png"
    model_refs.find_ref_image = lambda c, kind, bsig: root / "base.png"
    model_refs.get_model_refs_dir = lambda c: root
    shell_base_views.base_for = lambda c, i, view, bsig, path, make=False: (path,)
    body = np.ones((3, 4), bool)
    garment_source.fit_masks = lambda *a, **k: (body, body, None)
    garment_source._flat_mask = lambda path, refs: (body, (4, 3))
    gi._mask = lambda path, size: np.ones((size[1], size[0]), bool)

    gi.skipped_view = lambda c, i, f, step, view: gi.EMPTY_BACK if view == "back" else None
    try:
        out = gsh.shell_views("Demo", "item_x", "0123456789ab", "bsig")
        back = out["back"]
        check("[1] front and back", sorted(out) == ["back", "front"], sorted(out))
        check("[1] back body mask = base back", np.array_equal(back["body_mask"], body))
        check("[1] back ghost mask empty", back["ghost_mask"].shape == (3, 4) and not back["ghost_mask"].any())
        check("[1] back image zeros", back["image"].shape == (3, 4, 3) and back["image"].dtype == np.uint8
              and not back["image"].any())
        check("[1] front from the ghost", out["front"]["image"].shape == (3, 4, 3) and out["front"]["image"].all())
    except base_body.MissingInput as exc:
        check("[1] empty back is fittable", False, exc)

    gi.skipped_view = lambda *a: None
    try:
        gsh.shell_views("Demo", "item_x", "0123456789ab", "bsig")
        check("[2] missing ghost back refused", False, "no error")
    except base_body.MissingInput as exc:
        check("[2] missing ghost back refused", "ghost back" in str(exc), exc)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
