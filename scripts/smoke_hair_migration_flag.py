"""Smoke: the one-time hair migration never re-runs on a migrated world because one flag read failed, and never runs
on a world of the hairstyle era (A198, review 07 #1).

Usage:
    ./.venv/bin/python scripts/smoke_hair_migration_flag.py

No server, no world DB: ``world.get_world_setting`` and the character list are stubbed. By hand:
  [1] the flag read fails (strict raises "database is locked") -> the migration raises, no character is listed
      (pre-fix e846d7d02: the non-strict read swallowed it, returned "" and the migration ran — deleting hair)
  [2] HAIR_FLAG unset, HAIRSTYLE_FLAG set -> None, no character listed
  [3] both unset -> the migration goes on (the character list is asked)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import figure_migration, hair_migration  # noqa: E402
import app.models.character as character  # noqa: E402
import app.models.world as world  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


listed = []


class Stop(Exception):
    pass


def names(**k):
    listed.append(1)
    raise Stop()


character.list_available_characters = names
store = {}


def setting(key, default="", *, strict=False):
    if store.get("fail"):
        if strict:
            raise RuntimeError("database is locked")
        return default
    return store.get(key, default)


world.get_world_setting = setting
store["fail"] = True
try:
    hair_migration.delete_all_hair_once()
    check("[1] a failed flag read stops the migration", False, "ran")
except Stop:
    check("[1] a failed flag read stops the migration", False, "listed the characters")
except RuntimeError:
    check("[1] a failed flag read stops the migration", listed == [], listed)
store.clear()
store[figure_migration.HAIRSTYLE_FLAG] = "1"
check("[2] hairstyle era -> None", hair_migration.delete_all_hair_once() is None and listed == [], listed)
store.clear()
try:
    hair_migration.delete_all_hair_once()
except Stop:
    pass
check("[3] unmigrated -> goes on", listed == [1], listed)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
