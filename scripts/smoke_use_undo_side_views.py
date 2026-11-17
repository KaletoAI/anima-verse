"""Smoke: the "Use this" Undo snapshot of a drafted FRONT keeps every view ``_publish`` drops — the back AND a shell
piece's left/right (A185 side views; A198, review 05 #1).

Usage:
    ./.venv/bin/python scripts/smoke_use_undo_side_views.py

No server, no world DB. ``garment_use_undo._later_views`` on the clothing kind. Derived by hand:
``garment_images._publish`` on a new front of a drafted step drops, for every view in ``DRAFTED_VIEWS``
(back, left, right), that step and its later steps (``inclusive=True``). For the worn step of clothing
(order worn, ghost, cutout; worn's back is "draft") the snapshot must therefore name
front, back, left, right -> [worn, ghost, cutout] each. A ghost front (no draft) names only front -> [ghost, cutout].

Pre-fix proof: at e846d7d02 the worn front mapping had only front + back (left/right missing).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_clothing, garment_use_undo  # noqa: E402
from app.core.garment_images import DRAFTED_VIEWS  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


order = ("worn", "ghost", "cutout")
check("DRAFTED_VIEWS back/left/right", tuple(DRAFTED_VIEWS) == ("back", "left", "right"), DRAFTED_VIEWS)
check("worn's back is drafted", (garment_clothing.EDIT_STEPS.get("worn") or {}).get("back") == "draft",
      garment_clothing.EDIT_STEPS.get("worn"))
got = garment_use_undo._later_views(garment_clothing, order, "worn", "front")
want = {v: ["worn", "ghost", "cutout"] for v in ("front", "back", "left", "right")}
check("worn front: front, back, left, right -> worn..cutout", got == want, got)
got = garment_use_undo._later_views(garment_clothing, order, "ghost", "front")
check("ghost front: only front -> ghost, cutout", got == {"front": ["ghost", "cutout"]}, got)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
