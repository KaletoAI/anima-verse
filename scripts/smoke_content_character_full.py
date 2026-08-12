#!/usr/bin/env python3
"""Smoke run for the FULL character export AND import: the generated 3D
models travel inside the ZIP (Seamless World, E9 Task 5).

This is the COMPLETENESS PROOF for characters. Locations needed extra code in
E9 Task 1/2 because their models live OUTSIDE the location record
(``storage/locations/<owner>/model3d/``). Characters do not: every generated
mesh lands under ``<character_dir>/model3d/`` (``model3d.get_model3d_dir``),
and ``export_character_to_zip`` walks the character dir with ``rglob("*")``.
So the claim "characters are already complete" is a claim about a directory
layout — and this smoke is what turns it into a checked fact, including the
resolution tiers (``model3d/low/``), which are a SUBDIRECTORY and would be the
first thing a non-recursive walk would drop.

Runs against a THROWAWAY storage directory — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected BEFORE the app modules are imported, so
the shared clips directory is never read either.

Seed (all files are dummy bytes, nothing is generated):
  * Character "Testina" via save_character_profile(..., create_new=True) —
    without create_new the profile is silently dropped and the export would
    have nothing but an empty directory.
  * <character_dir>/model3d/
        <SIG>.glb        the served mesh
        <SIG>.json       its manifest sidecar (rig/skin metadata — without it
                         the far side has a mesh but no rig information)
        <SIG>.png        the reference render the mesh was built from
        low/<SIG>.glb    the LOD tier (model3d.tier_dir(name, "low"))
    -> 4 files, one of them one level deeper than the rest.
  * <character_dir>/images/portrait.png — an ordinary gallery file, present so
    the model files are proven to arrive ALONGSIDE the existing payload, not
    instead of it.
  * save_character_profile itself writes the soul markdown files the template
    demands — for the default template that is soul/personality.md,
    soul/presence.md and soul/tasks.md. They are seeded by the app, not by
    this script, and are listed explicitly below because "8" would otherwise
    be an unexplained number.

Expectations, derived by hand from the seed above:
  [1] Export
      manifest.version    == 2      (character manifest version, unchanged)
      manifest.character_name == "Testina"
      manifest.files      == the four model paths + images/portrait.png + the
                             three soul files, sorted, POSIX-relative to the
                             character dir. Note the sort order inside
                             model3d/: "low/" sorts BEFORE "<SIG>.glb"
                             because "/" < "o":
          ["images/portrait.png", "model3d/low/<SIG>.glb",
           "model3d/<SIG>.glb", "model3d/<SIG>.json", "model3d/<SIG>.png",
           "soul/personality.md", "soul/presence.md", "soul/tasks.md"]
      ZIP members         == "files/<rel>" for each of those eight, and the
                             bytes are byte-identical to the seed.
      db/characters.json  contains the one seeded row (the profile has to
                             travel with the files — a mesh without its
                             character row is unusable).
  [2] Import with overwrite=True into the SAME storage, after the whole
      model3d directory was deleted:
      files_imported      == 8      (all eight files, none skipped)
      every seeded file is back on disk with its original bytes, INCLUDING
      low/<SIG>.glb — the tier subdirectory is recreated, not flattened.
      find_model3d_serving_tier(name, "low") resolves to that file, i.e. the
      model store finds the imported tier, not just the raw bytes. It returns
      (path, match, tier); tier == "low" is the load-bearing part — a missing
      tier would silently fall back to "full".
  [3] Import into a SECOND, empty storage (a different world): the character
      arrives with its models from nothing but the ZIP. This is the case the
      export exists for; step 2 alone could pass on leftovers.

Usage:  ./.venv/bin/python scripts/smoke_content_character_full.py
"""
import io
import json
import os
import sys
import shutil
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="content-character-smoke-"))
STORAGE_B = Path(tempfile.mkdtemp(prefix="content-character-smoke-b-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="content-character-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.character_io import (  # noqa: E402
    export_character_to_zip, import_character_from_zip)
from app.core.model3d import (  # noqa: E402
    LOW_TIER, find_model3d_serving_tier, get_model3d_dir, tier_dir)
from app.models.character import (  # noqa: E402
    get_character_dir, get_character_profile, save_character_profile)

NAME = "Testina"
SIG = "outfit-abc123"

FAILURES = []
CHECKED = 0


def read_bytes(p: Path):
    """Bytes of `p`, or None when it does not exist — a missing file must
    show up as a failed check, not as a traceback that hides the rest."""
    return p.read_bytes() if p.is_file() else None


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# --- Seed -----------------------------------------------------------------

# create_new=True is mandatory: save_character_profile drops writes for unknown
# names otherwise, and the export would silently carry no DB row.
save_character_profile(NAME, {
    "name": NAME,
    "description": "A test character.",
    "height": 170,
}, create_new=True)

char_dir = get_character_dir(NAME, create=True)
mdir = get_model3d_dir(NAME)
mdir.mkdir(parents=True, exist_ok=True)
(mdir / f"{SIG}.glb").write_bytes(b"GLB-full")
# The sidecar carries the outfit combination the mesh stands for (`pieces` /
# `items`, read by outfit_cache_gc.read_manifest). It is seeded in the real
# shape because the serving lookup below needs it: the smoke's character wears
# nothing, so the mesh is found as the NEAREST combination — a sidecar without
# `pieces` would make it invisible to the store even though the bytes are there.
(mdir / f"{SIG}.json").write_text(
    json.dumps({"mesh_rig": "mixamo", "signature": SIG,
                "pieces": {}, "items": []}), encoding="utf-8")
(mdir / f"{SIG}.png").write_bytes(b"PNG-reference")
low_dir = tier_dir(NAME, LOW_TIER)
low_dir.mkdir(parents=True, exist_ok=True)
(low_dir / f"{SIG}.glb").write_bytes(b"GLB-low")

img_dir = char_dir / "images"
img_dir.mkdir(parents=True, exist_ok=True)
(img_dir / "portrait.png").write_bytes(b"PNG-portrait")

# Sorted as the export sorts them: "model3d/low/…" comes before
# "model3d/<SIG>.glb" because "/" sorts before "o". The soul/*.md files are
# written by save_character_profile from the character template.
EXPECTED_FILES = [
    "images/portrait.png",
    f"model3d/low/{SIG}.glb",
    f"model3d/{SIG}.glb",
    f"model3d/{SIG}.json",
    f"model3d/{SIG}.png",
    "soul/personality.md",
    "soul/presence.md",
    "soul/tasks.md",
]
SEED_BYTES = {
    "images/portrait.png": b"PNG-portrait",
    f"model3d/{SIG}.glb": b"GLB-full",
    f"model3d/{SIG}.png": b"PNG-reference",
    f"model3d/low/{SIG}.glb": b"GLB-low",
}

print(f"Storage {STORAGE}\nCharacter dir {char_dir}")

# --- [1] Export -----------------------------------------------------------

print("\n[1] Export bundles the model files")
blob = export_character_to_zip(NAME)
zf = zipfile.ZipFile(io.BytesIO(blob))
names = sorted(zf.namelist())
manifest = json.loads(zf.read("manifest.json"))

check("manifest.version", manifest["version"], 2)
check("manifest.character_name", manifest["character_name"], NAME)
check("manifest.files lists model3d incl. the low tier",
      manifest["files"], EXPECTED_FILES)
check("ZIP members for every file",
      [n for n in names if n.startswith("files/")],
      [f"files/{rel}" for rel in EXPECTED_FILES])
for rel, expected in SEED_BYTES.items():
    check(f"bytes travel: {rel}", zf.read(f"files/{rel}"), expected)
check("the mesh sidecar travels parsed",
      json.loads(zf.read(f"files/model3d/{SIG}.json"))["mesh_rig"], "mixamo")
check("db/characters.json is in the bundle", "db/characters.json" in names, True)
char_rows = json.loads(zf.read("db/characters.json"))
check("the DB row belongs to the character",
      [r["name"] for r in char_rows], [NAME])
zf.close()

# --- [2] Re-import into the same storage ----------------------------------

print("\n[2] Re-import with overwrite=True restores the files")
shutil.rmtree(mdir)
check("model3d dir exists before the import", mdir.exists(), False)

res = import_character_from_zip(blob, overwrite=True)
check("status", res["status"], "success")
check("character", res["character"], NAME)
check("overwritten", res["overwritten"], True)
check("files_imported", res["files_imported"], len(EXPECTED_FILES))

mdir_after = get_model3d_dir(NAME)
for rel, expected in SEED_BYTES.items():
    check(f"back on disk: {rel}", read_bytes(char_dir / rel), expected)
check("the sidecar is back too",
      json.loads((mdir_after / f"{SIG}.json").read_text(encoding="utf-8"))["signature"],
      SIG)
low_path, _low_match, low_tier = find_model3d_serving_tier(NAME, LOW_TIER)
check("the model store finds the imported low tier",
      (low_path.name if low_path else None, low_tier, read_bytes(low_path)),
      (f"{SIG}.glb", LOW_TIER, b"GLB-low"))
check("the profile survived the wipe+restore",
      (get_character_profile(NAME) or {}).get("height"), 170)

# --- [3] Import into a second, empty storage ------------------------------

print("\n[3] Import into a foreign (empty) world")
paths.init(STORAGE_B)
# db.get_connection() caches one connection per THREAD, opened against the
# storage that was active at the time — switching the storage dir inside one
# process therefore has to drop that cache, or the "second world" would keep
# writing into the first one's world.db.
for _c in list(db._connections.values()):
    _c.close()
db._connections.clear()
db.init_schema()
check("character dir exists in the second storage",
      get_character_dir(NAME).exists(), False)

res_b = import_character_from_zip(blob)
check("status", res_b["status"], "success")
check("overwritten", res_b["overwritten"], False)
check("files_imported", res_b["files_imported"], len(EXPECTED_FILES))

char_dir_b = get_character_dir(NAME)
check("the new dir is really the second storage",
      str(char_dir_b).startswith(str(STORAGE_B)), True)
for rel, expected in SEED_BYTES.items():
    check(f"arrived in the foreign world: {rel}",
          read_bytes(char_dir_b / rel), expected)
low_path_b, _low_match_b, low_tier_b = find_model3d_serving_tier(NAME, LOW_TIER)
check("low tier resolves in the foreign world",
      (low_path_b.name if low_path_b else None, low_tier_b,
       read_bytes(low_path_b)), (f"{SIG}.glb", LOW_TIER, b"GLB-low"))
check("the profile arrived", (get_character_profile(NAME) or {}).get("height"), 170)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("OK")
