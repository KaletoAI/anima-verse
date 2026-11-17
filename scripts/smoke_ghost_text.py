"""Smoke: the piece-only (ghost) prompt per piece class (A183, user decision 2026-11-17).

Usage: ./.venv/bin/python scripts/smoke_ghost_text.py

The expected texts are written out by hand below from the user's decision, not taken from the code:
- a piece with a collar, sleeves and hem (default: a ``top`` / ``outer`` slot) gets the full text of Ruling A57;
- a waistband piece (a bottom slot, no upper one) keeps the waistband variant and the stance line;
- every other piece (a bra on ``underwear_top``, a belt on ``neck``…) gets only the first sentence — the text of the
  user's hub jobs ae52d455 (bra back) and fb597ef6 (opera gloves back);
- a back view adds the side line after the text, before the stance;
- the stored ``ghost_text`` choice wins over the slots (Glut's bra is slotted ``top`` + ``underwear_top``, the opera
  gloves ``outer`` — both are set to ``plain`` by hand).
Pure: no storage, no world, no server.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.garment_clothing import ghost_prompt, ghost_text_class  # noqa: E402
from app.models.inventory import _clean_ghost_text  # noqa: E402

FIRST = ("Remove the person completely, leaving only the clothes in the exact same position, pose, and shape "
         "as if worn by an invisible mannequin.")
COLLAR = FIRST + (" Reconstruct the inside of the collar, sleeves, and hem naturally, and fill in the background "
                  "behind the removed body parts seamlessly.")
WAIST = FIRST + (" Reconstruct the inside of the waistband and the leg openings naturally, and fill in the "
                 "background behind the removed body parts seamlessly.")
SIDE = " Seen from behind; the back view stays a back view."
STANCE = " The legs stay apart at exactly the same angle as in the image."

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}:\n  got  {got!r}\n  want {want!r}")
    else:
        print(f"ok  {label}")


CASES = [
    ("t-shirt", {"slots": ["top"]}, "collar", COLLAR, COLLAR + SIDE),
    ("dress", {"slots": ["bottom", "top"]}, "collar", COLLAR, COLLAR + SIDE),
    ("coat", {"slots": ["outer"]}, "collar", COLLAR, COLLAR + SIDE),
    ("jeans", {"slots": ["bottom"]}, "waistband", WAIST + STANCE, WAIST + SIDE + STANCE),
    ("briefs", {"slots": ["bottom", "underwear_bottom"]}, "waistband", WAIST + STANCE, WAIST + SIDE + STANCE),
    ("stockings (legs: a bottom slot)", {"slots": ["legs"]}, "waistband", WAIST + STANCE, WAIST + SIDE + STANCE),
    ("bra on underwear_top", {"slots": ["underwear_top"]}, "plain", FIRST, FIRST + SIDE),
    ("choker", {"slots": ["neck"]}, "plain", FIRST, FIRST + SIDE),
    ("earrings", {"slots": ["head"]}, "plain", FIRST, FIRST + SIDE),
    ("no slots", {}, "plain", FIRST, FIRST + SIDE),
    ("Glut's bra (top + underwear_top) set plain", {"slots": ["top", "underwear_top"], "ghost_text": "plain"},
     "plain", FIRST, FIRST + SIDE),
    ("Glut's opera gloves (outer) set plain", {"slots": ["outer"], "ghost_text": "plain"}, "plain", FIRST,
     FIRST + SIDE),
    ("a bra with a stale value is auto", {"slots": ["top"], "ghost_text": "bogus"}, "collar", COLLAR,
     COLLAR + SIDE),
    ("a bodysuit set waistband", {"slots": ["top"], "ghost_text": "waistband"}, "waistband", WAIST + STANCE,
     WAIST + SIDE + STANCE),
]
for label, piece, cls, front, back in CASES:
    check(f"{label}: class", ghost_text_class(piece), cls)
    check(f"{label}: front", ghost_prompt(piece, "front"), front)
    check(f"{label}: back", ghost_prompt(piece, "back"), back)

check("clean: plain kept", _clean_ghost_text("plain"), "plain")
check("clean: auto is no key", _clean_ghost_text("auto"), None)
check("clean: junk is no key", _clean_ghost_text(3), None)

if failures:
    print("\n".join(failures))
    sys.exit(1)
print("all ghost texts as derived by hand")
