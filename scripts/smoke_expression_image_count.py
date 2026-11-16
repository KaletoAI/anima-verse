"""The count on "Clear rendered expression images (N images)" (Ruling A110 phase 5), by hand:

Character "demo" has outfits/ with a.png + a.json, b.webp + b.json, notes.txt → 2 images
(sidecars and other files are not images). Character "solo" has no outfits folder → 0.
  GET  /poses/expression-images/count  → {images: 2, characters: 1}
  POST /poses/expression-images/clear  → {images_deleted: 2} — the SAME number the button showed
       (before this change the clear counted image + sidecar files: 4), and the folder keeps only notes.txt.

Usage: ./.venv/bin/python scripts/smoke_expression_image_count.py   (no server; temp storage)
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp(prefix="expr-count-"))
from app.core import paths  # noqa: E402

paths.init(str(tmp))
from app.core import expression_regen  # noqa: E402
import app.models.character as character_model  # noqa: E402
from app.routes import poses as poses_route  # noqa: E402

outfits = tmp / "characters" / "demo" / "outfits"
outfits.mkdir(parents=True)
for name in ("a.png", "a.json", "b.webp", "b.json", "notes.txt"):
    (outfits / name).write_bytes(b"x")
(tmp / "characters" / "solo").mkdir(parents=True)
character_model.list_available_characters = lambda: ["demo", "solo"]

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    fails += not ok


check("count per character", (expression_regen.count_expression_images("demo"),
                              expression_regen.count_expression_images("solo")), (2, 0))
check("count route", poses_route.count_expression_images_route({}), {"images": 2, "characters": 1})
check("clear route reports images", poses_route.clear_expression_images({}), {"images_deleted": 2})
check("folder after clear", sorted(p.name for p in outfits.iterdir()), ["notes.txt"])
print("FAILED" if fails else "OK")
sys.exit(1 if fails else 0)
