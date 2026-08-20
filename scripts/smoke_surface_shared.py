#!/usr/bin/env python3
"""Smoke: the surface-texture library lives in shared/, once for all worlds.

Usage:
    ./.venv/bin/python scripts/smoke_surface_shared.py

Runs WITHOUT the server. Both roots are throwaway: the storage dir AND the
shared dir — ``paths.get_shared_dir`` is redirected before the module is
touched, because the real one points into the repo and this smoke writes.
Expectations are derived BY HAND from the E5 Task 4 rules, not recorded:

  [1] ``_dir()`` resolves to <shared>/surface_textures and NOT under the
      storage dir. Reading does not create it — a missing directory is the
      normal empty-library state (list_textures -> [], library_kinds ->
      set(), texture_file -> None, all with the directory still absent).

  [2] The stored functions work unchanged on the new root: save_uploaded
      writes <kind>_<ts>.jpg + sidecar and selects it; a second upload of
      the same kind adds a version and takes the selection over; select
      switches back; set_blend/get_blends and set_kind_meta round-trip; the
      client list carries {kind, name, url, size_m}. The url stays
      /assets/surface-textures/<file> — the client contract is untouched.

  [3] Switching the world (a second paths.init) shows the SAME library:
      list_textures is byte-identical, because storage no longer takes part
      in the path.

  [4] migrate_world_dirs_once moves a leftover world folder over. Fixture:
      the world holds grass_1780000000.jpg + .json, sand.jpg and a
      selection.json; the shared library ALREADY has sand.jpg (other bytes)
      and a selection.json (written by [2]). Expected: moved 2 (the grass
      pair), kept_in_world 2 — shared sand.jpg keeps its own bytes and the
      shared selection.json keeps its own entries, because the shared file
      wins and the registry JSONs are moved as files, not merged. The world
      folder SURVIVES with exactly those two leftovers in it. After deleting
      them the rerun moves nothing, returns {} and removes the now empty
      directory; a third run returns {} as well (no directory left).

  [6] The sweep covers EVERY world, not the open one (finding B9). Fixture:
      the active world alpha has no folder left at all, beta holds
      moss_1780000100.jpg + its sidecar, gamma holds moss_1780000100.jpg
      (other bytes) and slate_1780000200.jpg. Worlds are visited in sorted
      order, so beta hands its moss over first and gamma's collides:
      expected moved 3, kept_in_world 1, and the two folders named in
      "worlds" (alpha never appears — it has nothing). The shared moss
      carries BETA's bytes, beta's emptied folder is gone, gamma's survives
      with the one leftover, the collision is logged once, and beta's
      world.db stub is untouched — the sweep moves files out of
      surface_textures/ and nothing else. A rerun therefore still reports
      moved 0 / kept 1 for gamma.

  [5] migrate_kind_meta_once is idempotent BY CONTENT, without a world flag
      — that is the point: the same shared file is now visited by every
      world's boot. State at this point: files for dark_stone, grass and
      sand, a "coast" composition, and a kinds.json holding the complete
      dark_stone entry from [2] plus the fixture entries
      {"old_kind": {"subject": …}, "custom": {"name": …}}. Six known kinds,
      and dark_stone is complete -> 5 touched, 1 subject renamed,
      4 descriptions seeded (grass, sand, coast, custom) and 4 names seeded
      (grass, sand, coast, old_kind). The SECOND run returns {} and leaves
      the file's mtime alone, and so does a run from a different world.

  [7] SEASON SLOTS (E2c, 2026-08-20). A kind may hold ONE active version per
      season beside its seasonless default; rooms and terrain keep naming
      nothing but the kind. The split lives in ``selection.json``, which
      already answers "which version is active" — a season only makes the
      question more precise. Fixture: the shipped calendar (4 seasons × 30
      days -> season starts 0/30/60/90) plus a hand-picked instant, day 35 =
      day 5 of summer, day 95 = day 5 of winter, both at noon
      ((D-1) × 86400 + 43200 s). Two versions of a kind ``moss2``:
        seasonless only        -> stored as the BARE STRING it always was
        + winter slot          -> {"": <summer file>, "winter": <winter file>}
                                  (the season lowercased on the way in)
        summer                 -> the seasonless default (the fallback)
        winter                 -> the winter file, in the CLIENT list too —
                                  which says nothing about seasons at all
        admin_list             -> each version names the slots it holds, and
                                  `active` is the one rendering right now
        clearing the slot      -> back to the bare string, back to the default
        an unknown season name -> never matches (packs travel as strings)
        deleting a version     -> every slot pointing at it goes with it
      INERTNESS: an untagged library answers byte-identically in every season.
"""
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="surface-clips-")

SHARED = Path(tempfile.mkdtemp(prefix="surface-shared-"))
# One throwaway WORLDS ROOT with two worlds in it — the boot sweep of [6]
# walks the parent of the active storage dir, so the worlds have to be
# siblings the way worlds/<name> is, not two unrelated temp directories.
WORLDS = Path(tempfile.mkdtemp(prefix="surface-worlds-"))
WORLD_A = WORLDS / "alpha"
WORLD_B = WORLDS / "beta"
WORLD_A.mkdir()
WORLD_B.mkdir()

from app.core import paths  # noqa: E402

# The real shared dir is the repo — never let a smoke write there.
paths.get_shared_dir = lambda: SHARED  # type: ignore[assignment]
paths.init(WORLD_A)

from app.core import surface_textures as st  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"stub-a" * 4
JPEG2 = b"\xff\xd8\xff\xe0" + b"stub-b" * 4

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


print("[1] the library lives under shared, and reading creates nothing")
check("_dir() is <shared>/surface_textures", st._dir(),
      SHARED / "surface_textures")
check("not under the storage dir", str(st._dir()).startswith(str(WORLD_A)),
      False)
check("empty list", st.list_textures(), [])
check("no kinds", st.library_kinds(), set())
check("no active file", st.texture_file("grass"), None)
check("directory still absent after the read paths", st._dir().exists(), False)

print("[2] upload / select / kinds / blends run unchanged")
up = st.save_uploaded("dark_stone", JPEG)
check("upload ok", up.get("ok"), True)
first = up.get("filename", "")
check("file name is <kind>_<ts>.jpg", first.startswith("dark_stone_")
      and first.endswith(".jpg"), True)
check("file landed in shared", (st._dir() / first).is_file(), True)
check("sidecar next to it",
      json.loads((st._dir() / first).with_suffix(".json")
                 .read_text()).get("source"), "uploaded")
time.sleep(1.1)   # the version stamp is unix SECONDS
second = st.save_uploaded("dark_stone", JPEG2).get("filename", "")
check("a second upload is a new version", second != first, True)
check("...and takes the selection", (st.texture_file("dark_stone") or
                                     Path("")).name, second)
check("select switches back", st.select_texture("dark_stone", first), True)
check("...and it holds", (st.texture_file("dark_stone") or Path("")).name,
      first)
st.set_kind_meta("dark_stone", name="Dark stone", description="rough basalt")
check("name round-trips", st.kind_name("dark_stone"), "Dark stone")
check("description round-trips", st.surface_description("dark_stone"),
      "rough basalt")
st.set_blend("coast", {"toward": "water",
                       "zones": [{"kind": "sand", "until": 0.4},
                                 {"kind": "neighbor"}]})
check("blend stored", (st.get_blends().get("coast") or {}).get("toward"),
      "water")
listed = st.list_textures()
check("two entries (texture + composition)", len(listed), 2)
entry = next(e for e in listed if e["kind"] == "dark_stone")
check("client url is the unchanged contract", entry["url"],
      f"/assets/surface-textures/{first}")
check("default size_m", entry["size_m"], st.DEFAULT_SIZE_M)
check("name travels with it", entry["name"], "Dark stone")

print("[3] another world sees the SAME library")
before = json.dumps(st.list_textures(), sort_keys=True)
paths.init(WORLD_B)
check("storage really changed", paths.get_storage_dir(), WORLD_B.resolve())
check("path unchanged", st._dir(), SHARED / "surface_textures")
check("identical listing", json.dumps(st.list_textures(), sort_keys=True),
      before)
paths.init(WORLD_A)

print("[4] the one-time move of a leftover world folder")
check("nothing to move yet", st.migrate_world_dirs_once(), {})
old = WORLD_A.resolve() / "surface_textures"
old.mkdir(parents=True, exist_ok=True)
(old / "grass_1780000000.jpg").write_bytes(JPEG)
(old / "grass_1780000000.json").write_text(
    json.dumps({"created_at": "2026-06-01T00:00:00+00:00",
                "source": "uploaded"}), encoding="utf-8")
(old / "sand.jpg").write_bytes(b"\xff\xd8\xff\xe0world-copy")
(old / "selection.json").write_text(json.dumps({"grass": "grass_1780000000.jpg"}),
                                    encoding="utf-8")
(st._dir(create=True) / "sand.jpg").write_bytes(b"\xff\xd8\xff\xe0shared-wins")
stats = st.migrate_world_dirs_once()
check("moved", stats.get("moved"), 2)
check("kept in the world", stats.get("kept_in_world"), 2)
check("grass arrived", (st._dir() / "grass_1780000000.jpg").is_file(), True)
check("...and left the world", (old / "grass_1780000000.jpg").exists(), False)
check("its sidecar came along", (st._dir() / "grass_1780000000.json").is_file(),
      True)
check("the shared file wins", (st._dir() / "sand.jpg").read_bytes(),
      b"\xff\xd8\xff\xe0shared-wins")
check("the world copy stays put", (old / "sand.jpg").is_file(), True)
check("...so the old folder survives as evidence", old.is_dir(), True)
# The registry JSONs are files like any other: the shared selection.json is
# NOT replaced by the world's, so dark_stone keeps the version [2] picked.
check("the shared selection is untouched",
      (st.texture_file("dark_stone") or Path("")).name, first)
check("the world selection.json stayed behind",
      (old / "selection.json").is_file(), True)
check("grass is active as its newest version",
      (st.texture_file("grass") or Path("")).name, "grass_1780000000.jpg")
(old / "sand.jpg").unlink()
(old / "selection.json").unlink()
check("a rerun with nothing left to move", st.migrate_world_dirs_once(), {})
check("...and the empty folder is gone", old.exists(), False)
check("a third run has nothing to do", st.migrate_world_dirs_once(), {})

print("[5] kind-meta migration: idempotent by content, no world flag")
kinds_file = st._dir() / "kinds.json"
fixture = json.loads(kinds_file.read_text(encoding="utf-8"))
fixture["old_kind"] = {"subject": "worn wooden planks"}
fixture["custom"] = {"name": "Custom stuff"}
kinds_file.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
stats = st.migrate_kind_meta_once()
check("kinds touched", stats.get("kinds"), 5)
check("subject renamed", stats.get("subject_renamed"), 1)
check("descriptions seeded", stats.get("description_seeded"), 4)
check("names seeded", stats.get("name_seeded"), 4)
meta = json.loads(kinds_file.read_text(encoding="utf-8"))
check("subject key is gone", "subject" in meta["old_kind"], False)
check("the old subject survives as description",
      meta["old_kind"].get("description"), "worn wooden planks")
check("the curated wording is written out",
      meta["grass"].get("description"), st.SURFACE_SUBJECTS["grass"])
check("dark_stone kept its edited description",
      meta["dark_stone"].get("description"), "rough basalt")
mtime = kinds_file.stat().st_mtime
check("second run is a no-op", st.migrate_kind_meta_once(), {})
check("...and did not rewrite the file", kinds_file.stat().st_mtime, mtime)
paths.init(WORLD_B)
check("a second world's boot is a no-op too", st.migrate_kind_meta_once(), {})
paths.init(WORLD_A)

print("[6] the boot sweep covers every world, not just the open one")
# The active world (alpha) has nothing left to hand over — that is exactly the
# B9 case: booting into a world without an old folder used to migrate nothing.
check("alpha has no folder any more",
      (WORLD_A / "surface_textures").exists(), False)
beta_dir = WORLD_B / "surface_textures"
gamma_dir = WORLDS / "gamma" / "surface_textures"
beta_dir.mkdir(parents=True)
gamma_dir.mkdir(parents=True)
(beta_dir / "moss_1780000100.jpg").write_bytes(JPEG)
(beta_dir / "moss_1780000100.json").write_text(
    json.dumps({"created_at": "2026-06-02T00:00:00+00:00", "source": "uploaded"}),
    encoding="utf-8")
(gamma_dir / "moss_1780000100.jpg").write_bytes(JPEG2)
(gamma_dir / "slate_1780000200.jpg").write_bytes(JPEG2)
# A stub for the ONE file a sweep must never touch.
(WORLD_B / "world.db").write_bytes(b"SQLite format 3\x00stub")


class _Capture(logging.Handler):
    """Collect the collision warnings of this run."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


cap = _Capture()
st.logger.addHandler(cap)
try:
    stats = st.migrate_world_dirs_once()
finally:
    st.logger.removeHandler(cap)
check("moved across both worlds", stats.get("moved"), 3)
check("one collision kept in its world", stats.get("kept_in_world"), 1)
check("the folders it touched", stats.get("worlds"),
      [str(beta_dir), str(gamma_dir)])
check("beta's moss arrived", (st._dir() / "moss_1780000100.jpg").read_bytes(),
      JPEG)
check("...with its sidecar", (st._dir() / "moss_1780000100.json").is_file(),
      True)
check("gamma's slate arrived too",
      (st._dir() / "slate_1780000200.jpg").is_file(), True)
check("beta's emptied folder is gone", beta_dir.exists(), False)
check("gamma keeps the colliding copy", (gamma_dir / "moss_1780000100.jpg")
      .read_bytes(), JPEG2)
check("the collision was logged once",
      sum("moss_1780000100.jpg" in m for m in cap.messages), 1)
check("beta's world.db was not touched", (WORLD_B / "world.db").read_bytes(),
      b"SQLite format 3\x00stub")
stats = st.migrate_world_dirs_once()
check("a rerun still reports gamma's leftover",
      (stats.get("moved"), stats.get("kept_in_world")), (0, 1))

print("[7] SEASON slots: one kind, one version per season (E2c)")
# Fixture (the smoke has no world clock): the shipped calendar — 4 seasons ×
# 30 days, season starts 0/30/60/90 — and a hand-picked instant. Day-of-year
# 35 is day 5 of SUMMER, 95 is day 5 of WINTER; a GameTime counts whole
# seconds from Year 1 Day 1 00:00, so day D at noon is (D-1) × 86400 + 43200.
from app.core import game_time as gt  # noqa: E402
from app.core import timeutils as tu  # noqa: E402


def set_season(day_of_year):
    gt._CALENDAR_CACHE = gt.Calendar.default()
    now = gt.GameTime((day_of_year - 1) * gt.DAY_SECONDS + 12 * 3600)
    tu.game_time = lambda: now
    return gt.Calendar.default().seasons[now.parts().season_index].key


check("day 95 is winter", set_season(95), "winter")
check("day 35 is summer", set_season(35), "summer")

summer_moss = st.save_uploaded("moss2", JPEG).get("filename", "")
time.sleep(1.1)   # the version stamp is unix SECONDS
winter_moss = st.save_uploaded("moss2", JPEG2).get("filename", "")
# Two uploads: the second one took the seasonless selection (rule of [2]).
check("the newest upload is the default pick",
      (st.texture_file("moss2") or Path("")).name, winter_moss)
check("select puts the first one back", st.select_texture("moss2", summer_moss),
      True)
sel_plain = json.loads((st._dir() / "selection.json").read_text())["moss2"]
check("a seasonless kind is still stored as a BARE STRING", sel_plain,
      summer_moss)
# Now the winter slot. Stored shape becomes the dict — and ONLY now.
check("select for a season", st.select_texture("moss2", winter_moss, "Winter"),
      True)
check("...stored as slots, the season lowercased",
      json.loads((st._dir() / "selection.json").read_text())["moss2"],
      {"": summer_moss, "winter": winter_moss})
check("summer still resolves to the seasonless default (fallback)",
      (st.texture_file("moss2") or Path("")).name, summer_moss)
set_season(95)
check("winter resolves to the winter version",
      (st.texture_file("moss2") or Path("")).name, winter_moss)
check("...and the CLIENT list carries that url, nothing about seasons",
      next(e for e in st.list_textures() if e["kind"] == "moss2")["url"],
      f"/assets/surface-textures/{winter_moss}")
listed = next(g for g in st.admin_list() if g["kind"] == "moss2")
check("the admin strip says which slots each version holds",
      {v["filename"]: v["seasons"] for v in listed["versions"]},
      {winter_moss: ["winter"], summer_moss: [""]})
check("...and which one renders right now",
      [v["filename"] for v in listed["versions"] if v["active"]],
      [winter_moss])
check("clearing the winter slot falls back to the default",
      (st.select_texture("moss2", "", "Winter"),
       (st.texture_file("moss2") or Path("")).name),
      (True, summer_moss))
check("...and the file is a bare string again",
      json.loads((st._dir() / "selection.json").read_text())["moss2"],
      summer_moss)
# A season NAME this world does not have never matches — packs travel as
# strings, and an unknown season is inert, not an error.
st.select_texture("moss2", winter_moss, "Monsoon")
check("an unknown season name simply never wins",
      (st.texture_file("moss2") or Path("")).name, summer_moss)
# Deleting a version sweeps EVERY slot that pointed at it.
st.select_texture("moss2", winter_moss, "Winter")
st.delete_texture("moss2", winter_moss)
check("deleting a version drops its season slot too",
      json.loads((st._dir() / "selection.json").read_text())["moss2"],
      summer_moss)
check("...and the kind keeps rendering its default",
      (st.texture_file("moss2") or Path("")).name, summer_moss)
# INERTNESS: a library nobody tagged answers the same in every season.
set_season(35)
before = json.dumps(st.list_textures(), sort_keys=True)
set_season(95)
check("an untagged library is byte-identical across seasons",
      json.dumps(st.list_textures(), sort_keys=True), before)

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
