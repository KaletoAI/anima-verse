"""Smoke: a HAAR fit on an OUTFIT body leaves the seed folder's tile (the base fit's picture in the variants panel)
alone (A198, review 05 #10).

Usage:
    ./.venv/bin/python scripts/smoke_haar_tile_outfit_body.py

No server, no world DB, no hub: ``garments._fit_haar_seeds``' inputs are stubbed onto a temp folder holding seed 42
with a tile ``b"BASE-TILE"``; the fit itself refuses (ValueError "no strands"). By hand:
  [1] on_base=False -> the tile file stays b"BASE-TILE", the entry names it (HAAR_TILE), error "no strands"
      (pre-fix e846d7d02: ``_haar_tile`` with result None deleted it -> tile None, file gone)
  [2] on_base=True  -> the refused base fit drops the tile (the base's own picture is gone): tile None, file gone
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_hair, garments, refit_pool, strand_file  # noqa: E402
from app.core import garment_store as gs  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


with tempfile.TemporaryDirectory(prefix="a198-haar-") as tmp:
    folder = Path(tmp)
    gs.haar_dir = lambda c, i, s: folder
    gs.haar_seed_dir = lambda f, seed: Path(f) / f"s{seed}"
    garments._hair_of = lambda c, i: ({}, "")
    garment_hair.hair_length_class = lambda c, profile=None, text="": "long"
    garments._haar_colour = lambda c, i, p: {"linear": [0.1, 0.1, 0.1]}
    garment_hair.hair_cut = lambda settings: None
    strand_file.read_strand_job = lambda d: {"head_V": [0], "head_F": [0], "strands": [], "strands_path": str(d)}
    garments._sha = lambda p: "S"

    def refuse(*a, **k):
        raise ValueError("no strands")
    refit_pool.run = refuse
    tile = folder / "s42" / garments.HAAR_TILE
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"BASE-TILE")
    out = garments._fit_haar_seeds("Demo", "hair_x", "0123456789ab", [42], b"RIGGED", {}, on_base=False)
    e = out[42]
    check("[1] outfit body: tile kept", (tile.is_file() and tile.read_bytes() == b"BASE-TILE", e["tile"], e["error"])
          == (True, garments.HAAR_TILE, "no strands"), (tile.is_file(), e))
    garments._haar_cut_source = lambda folder, seed, result: None
    out = garments._fit_haar_seeds("Demo", "hair_x", "0123456789ab", [42], b"RIGGED", {}, on_base=True)
    check("[2] base: a refused fit drops its tile", (tile.is_file(), out[42]["tile"]) == (False, None),
          (tile.is_file(), out[42]))

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
