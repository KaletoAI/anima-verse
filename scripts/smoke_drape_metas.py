"""Smoke: garment_template.drape_metas lists only drape RECORDS, by name, before anything is read.

Usage:
    ./.venv/bin/python scripts/smoke_drape_metas.py

Spec (by hand): a drape record is ``<item>_<tsig>.json`` where tsig = the first 12 hex digits of an md5
(``garment_template._md5``). In a templates folder holding, for item ``item_a``:

    item_a_0123456789ab.json          record                         -> listed
    item_a_0123456789ab.glb           the drape mesh (not .json)     -> not listed
    item_a_0123456789ab.islands.json  the cut's islands (megabytes)  -> NOT listed (the 2026-11-23 freeze:
                                      cut_stand_in parsed every one of them on each figure poll)
    item_a_copy_fedcba987654.json     record of item "item_a_copy"   -> NOT listed for item_a
    item_a_notahexsig12.json          no tsig                        -> not listed

the expected list for item_a is exactly ["item_a_0123456789ab.json"], and for item_a_copy exactly
["item_a_copy_fedcba987654.json"]. cut_stand_in and bust_shaping's stand-in read only what it lists.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="smoke_drape_metas_"))
from app.core import paths  # noqa: E402
paths.init(str(tmp))

from app.core import garment_template  # noqa: E402

folder = tmp / "templates"
folder.mkdir()
for name in ("item_a_0123456789ab.json", "item_a_0123456789ab.glb", "item_a_0123456789ab.islands.json",
             "item_a_copy_fedcba987654.json", "item_a_notahexsig12.json"):
    (folder / name).write_text("{}", encoding="utf-8")
garment_template.templates_dir = lambda _c: folder

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f" (want {want})"))


check("item_a", sorted(p.name for p in garment_template.drape_metas("demo", "item_a")),
      ["item_a_0123456789ab.json"])
check("item_a_copy", sorted(p.name for p in garment_template.drape_metas("demo", "item_a_copy")),
      ["item_a_copy_fedcba987654.json"])
garment_template.templates_dir = lambda _c: tmp / "none"
check("missing folder", garment_template.drape_metas("demo", "item_a"), [])

print("FAILED" if fails else "ALL OK")
sys.exit(1 if fails else 0)
