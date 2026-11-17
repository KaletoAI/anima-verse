"""A185 — "Side views for the shell": left / right piece-only views for a shell piece.

Usage: ./.venv/bin/python scripts/smoke_shell_side_views.py   (no server, no world DB)

Expected values derived by hand from the A185 design (2026-11-17):
[S1] setting: ``shell_sides`` is True only for a stored True (default off); ``normalise`` carries it; ``validate``
     takes a bool and refuses 1 / "on"; it is a shell-only key (``SHELL_SETTING_KEYS``).
[S2] views: ``GARMENT_VIEWS`` stays (front, back) — the fingerprint's ``base_images`` hashes those only, so no stored
     group ages; ``IMAGE_VIEWS`` adds left, right; ``garment_path`` names ``…_ghost_left.png``.
[S3] prompts: a side ghost is the class text + "Seen from the side, facing left/right; the side view stays a side
     view." (+ the stance line for a waistband piece); the front has no side line. A worn side is no edit: it is
     drafted from the worn front like the back (ValueError naming the view); the side draft uses the base draft's
     side sentence.
[S4] order + needs: worn (front, back, left, right) — the sides after the front they are drafted from; ghost
     (back, front, left, right); the cut-out never has sides. A worn side needs the worn front (draft); a ghost side
     its worn side (source). A new worn front re-drafts back, left and right.
[S5] the merge rule (``side_view_ok``): seen by the side at normal·view >= 0.5 and not seen frontally (>= 0.6) by
     the front or back.
       N=(1,0,0) side-on: side facing 1.0, front 0 -> True
       N=(0.6,0,0.8): side 0.6 but the front sees it at 0.8 -> False (front/back win)
       N=(0.8,0,-0.6) (the front cannot see it) seen by the back at 0.6 -> False; the back occluded too -> True
       N=(0.45,0,0.89): side 0.45 < 0.5 -> False
       N=(0.85,0,0.53): side 0.85, front 0.53 < 0.6 -> True
       not seen by the side -> False
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile  # noqa: E402

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_a185_"))   # before any world-DB module (garment_path names a dir)
import numpy as np  # noqa: E402

from app.core import garment_clothing as gc  # noqa: E402
from app.core import garment_fit_settings as fs  # noqa: E402
from app.core import garment_shell as gsh  # noqa: E402
from app.core import garment_store as gst  # noqa: E402
from app.core import garments  # noqa: E402

failed = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: got {got!r} want {want!r}")
    if not ok:
        failed.append(name)


# [S1]
check("[S1] default off", (gsh.shell_sides_choice(None), gsh.shell_sides_choice({}), fs.defaults()["shell_sides"]),
      (False, False, False))
check("[S1] only True", (gsh.shell_sides_choice({"shell_sides": True}), gsh.shell_sides_choice({"shell_sides": 1}),
                         gsh.shell_sides_choice({"shell_sides": "on"})), (True, False, False))
check("[S1] normalise", fs.normalise({"shell_sides": True})["shell_sides"], True)
check("[S1] validate bool", fs.validate({"shell_sides": True}), {"shell_sides": True})
for bad in (1, "on", None):
    try:
        fs.validate({"shell_sides": bad})
        check(f"[S1] validate refuses {bad!r}", "accepted", "ValueError")
    except ValueError:
        check(f"[S1] validate refuses {bad!r}", "ValueError", "ValueError")
check("[S1] shell-only key", "shell_sides" in gsh.SHELL_SETTING_KEYS, True)

# [S2]
check("[S2] GARMENT_VIEWS", gst.GARMENT_VIEWS, ("front", "back"))
check("[S2] IMAGE_VIEWS", gst.IMAGE_VIEWS, ("front", "back", "left", "right"))
p = gst.garment_path("Demo", "item_x", "0123456789ab", "image", step="ghost", view="left")
check("[S2] path", p.name, "item_x_0123456789ab_ghost_left.png")

# [S3]
plain = gc.GHOST_PLAIN
check("[S3] plain left", gc.ghost_prompt({"ghost_text": "plain"}, "left"),
      plain + " Seen from the side, facing left; the side view stays a side view.")
check("[S3] plain right", gc.ghost_prompt({"ghost_text": "plain"}, "right"),
      plain + " Seen from the side, facing right; the side view stays a side view.")
check("[S3] waistband right", gc.ghost_prompt({"ghost_text": "waistband"}, "right"),
      gc.GHOST_WAISTBAND + " Seen from the side, facing right; the side view stays a side view. "
      + "The legs stay apart at exactly the same angle as in the image.")
check("[S3] front has no side line", gc.ghost_prompt({"ghost_text": "plain"}, "front"), plain)
try:
    gc.edit_prompt("Demo", "worn", "left", profile={})
    check("[S3] worn left is drafted", "rendered", "ValueError")
except ValueError as e:
    check("[S3] worn left is drafted", "drafted" in str(e) and "left" in str(e), True)
from app.core import base_body  # noqa: E402
check("[S3] side draft sentence", base_body.DRAFT_PROMPTS["left"].startswith(
    "The same person turned to a strict left side profile view"), True)

# [S4]
four = ("front", "back", "left", "right")
check("[S4] worn order", garments._view_order("clothing", "worn", four), ("front", "back", "left", "right"))
check("[S4] ghost order", garments._view_order("clothing", "ghost", four), ("back", "front", "left", "right"))
check("[S4] cutout order", garments._view_order("clothing", "cutout", four), ("front", "back"))
check("[S4] no sides", garments._view_order("clothing", "ghost"), ("back", "front"))
check("[S4] worn left needs", garments.view_needs("clothing", "worn", "left"),
      [("worn", "front", garments.NEEDS_DRAFT)])
check("[S4] ghost right needs", garments.view_needs("clothing", "ghost", "right"),
      [("worn", "right", garments.NEEDS_SOURCE)])
check("[S4] follow-ups", [v for _s, v, _w in garments._follow_ups("clothing", "worn", "front", four)],
      ["back", "left", "right"])
check("[S4] follow-ups without sides", [v for _s, v, _w in garments._follow_ups("clothing", "worn", "front")],
      ["back"])

# [S5]
def one(n, seen_s=True, seen_f=True, seen_b=True):
    n = np.asarray(n, float)
    return bool(gsh.side_view_ok([seen_s], [n[0]], [seen_f], [n[2]], [seen_b], [-n[2]])[0])


check("[S5] side-on", one((1, 0, 0)), True)
check("[S5] front frontal wins", one((0.6, 0, 0.8)), False)
check("[S5] back frontal wins", one((0.8, 0, -0.6), seen_f=False), False)
check("[S5] back occluded", one((0.8, 0, -0.6), seen_f=False, seen_b=False), True)
check("[S5] grazing side", one((0.45, 0, 0.89)), False)
check("[S5] front only grazes", one((0.85, 0, 0.53)), True)
check("[S5] side does not see", one((1, 0, 0), seen_s=False), False)
check("[S5] thresholds", (gsh.SIDE_FACING_MIN, gsh.FRONTAL_MIN), (0.5, 0.6))

print("all pass" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
