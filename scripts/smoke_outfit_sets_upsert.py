#!/usr/bin/env python3
"""Smoke: saving outfit sets never deletes a set by absence; a delete is explicit.

Usage:  ./.venv/bin/python scripts/smoke_outfit_sets_upsert.py

Needs no server and no real world: `paths.init` points at a throwaway
directory BEFORE any world-DB module is imported, `db.init_schema()` builds an
empty world.db there.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

The writers live in `app/models/character.py`. Before this fix the one write
helper (`_save_outfits_file`) read every stored id of the character and ran
`DELETE` for each id missing from the list it was handed — so a writer
holding a list read BEFORE another writer added a set removed that set, and
`add_character_outfit` (an unlocked read of the whole list, then a write of
the whole list) wrote every OTHER set back as it had read it. The rule now:
a save upserts exactly the sets it is given, `delete_character_outfit` is the
only removal.

Seed: character "demo" with two sets created through `add_character_outfit`
— "Day" (id D) and "Night" (id N).

A) A STALE LIST. Writer 1 reads the list ([D, N]). Writer 2 then adds
   "Late" (id L). Writer 1 renames D to "Day 2" in its stale copy and calls
   `save_character_outfits(demo, [D', N])`.
     ids afterwards                -> {D, N, L}   (L is not in writer 1's
                                                   list; the old helper
                                                   deleted it: {D, N})
     name of D                     -> "Day 2"
     name of L                     -> "Late"

B) A RACING `add_character_outfit`. Writer 1 updates D (`name` "Day 3").
   The first time it reads the list, writer 2 (another thread) renames N to
   "Night 2" via `add_character_outfit` and adds "Extra" (id X).
   With the profile lock writer 2 waits until writer 1 is done; without it,
   writer 2 lands inside writer 1's window. Either way writer 1 writes only D:
     name of D -> "Day 3"
     name of N -> "Night 2"        (old code: "Night" — its stale copy)
     X present -> True             (old code: deleted by absence)

C) NAMELESS SETS. `_next_outfit_name` picks the first free "Outfit<k>",
   k = 1, 2, ... The table is emptied, one nameless set is added ("Outfit1",
   id O), then ONE new nameless set (id "nameless") is saved: the free name
   among stored + given is "Outfit2" (the old code looked only at the given
   list and picked "Outfit1" again — and deleted O by absence).

D) `update_outfit_image(demo, O, "d.png")` -> True, O's image is "d.png",
   the "nameless" row is byte-for-byte as before; an unknown id -> False.

E) AN EXPLICIT DELETE. `delete_character_outfit(demo, "nameless")` -> True
   and the ids are the previous ones minus "nameless", nothing else; a second
   delete -> False; the ids stay the same.

F) A LEGACY ROW (meta without `locations`, the pre-migration shape that
   `_migrate_outfits` rebuilds on read) keeps its STORED id on every read —
   two reads give the same id "legacy01". Saves upsert by id, so a fresh
   random id per read would add a copy instead of replacing the row.
"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths  # noqa: E402

STORAGE = tempfile.TemporaryDirectory(prefix="outfit-upsert-smoke-")
paths.init(STORAGE.name)
paths.init_instance(Path(STORAGE.name) / "instance")

from app.core import db  # noqa: E402
import app.models.character as character  # noqa: E402
from app.models.character import (  # noqa: E402
    add_character_outfit, delete_character_outfit, get_character_outfits,
    save_character_outfits, save_character_profile, update_outfit_image)

FAILS = []


def check(label, got, expected):
    ok = got == expected
    if not ok:
        FAILS.append(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")


def by_id():
    return {o["id"]: o for o in get_character_outfits("demo")}


def rows():
    conn = db.get_connection()
    return {r[0]: tuple(r) for r in conn.execute(
        "SELECT * FROM outfits_sets WHERE character_name='demo'")}


def main():
    db.init_schema()
    assert save_character_profile("demo", {"character_name": "demo", "language": "en"},
                                  create_new=True)
    d = add_character_outfit("demo", {"name": "Day", "pieces": []})
    n = add_character_outfit("demo", {"name": "Night", "pieces": []})

    print("A) a stale list")
    stale = get_character_outfits("demo")
    late = add_character_outfit("demo", {"name": "Late", "pieces": []})
    for o in stale:
        if o["id"] == d:
            o["name"] = "Day 2"
    check("save returns True", save_character_outfits("demo", stale), True)
    check("ids", set(by_id()), {d, n, late})
    check("name of D", by_id()[d]["name"], "Day 2")
    check("name of L", by_id().get(late, {}).get("name"), "Late")

    print("B) a racing add_character_outfit")
    real_get = character.get_character_outfits
    extra = {}
    fired = []

    def writer2():
        add_character_outfit("demo", {"id": n, "name": "Night 2"})
        extra["id"] = add_character_outfit("demo", {"name": "Extra", "pieces": []})

    def racing_get(name):
        result = real_get(name)
        if not fired:
            fired.append(1)
            t = threading.Thread(target=writer2)
            t.start()
            # Without the lock writer 2 finishes inside this window; with it,
            # it blocks until writer 1 returns, and this join times out.
            t.join(0.5)
            extra["thread"] = t
        return result

    character.get_character_outfits = racing_get
    try:
        add_character_outfit("demo", {"id": d, "name": "Day 3"})
    finally:
        character.get_character_outfits = real_get
    extra["thread"].join(10)
    now = by_id()
    check("name of D", now[d]["name"], "Day 3")
    check("name of N", now[n]["name"], "Night 2")
    check("X present", extra.get("id") in now, True)

    print("C) nameless sets")
    conn = db.get_connection()
    conn.execute("DELETE FROM outfits_sets")
    conn.commit()
    first = add_character_outfit("demo", {"name": "", "pieces": []})
    check("first nameless set", by_id()[first]["name"], "Outfit1")
    check("save of one nameless set",
          save_character_outfits("demo", [{"id": "nameless", "name": "", "pieces": [], "locations": []}]), True)
    check("its name", by_id()["nameless"]["name"], "Outfit2")
    check("ids", set(by_id()), {first, "nameless"})

    print("D) update_outfit_image writes only its set")
    before = rows()
    check("update_outfit_image", update_outfit_image("demo", first, "d.png"), True)
    after = rows()
    check("image of the set", by_id()[first]["image"], "d.png")
    check("the other row unchanged", after["nameless"], before["nameless"])
    check("unknown set", update_outfit_image("demo", "absent", "x.png"), False)

    print("E) an explicit delete")
    ids_before = set(by_id())
    check("delete returns True", delete_character_outfit("demo", "nameless"), True)
    check("ids", set(by_id()), ids_before - {"nameless"})
    check("second delete", delete_character_outfit("demo", "nameless"), False)
    check("ids unchanged", set(by_id()), ids_before - {"nameless"})

    print("F) a legacy row keeps its stored id")
    conn.execute("INSERT INTO outfits_sets (id, character_name, name, pieces, image, meta, created_at) "
                 "VALUES ('legacy01', 'demo', 'Old', '[]', '', '{}', '2026-01-01T00:00:00+00:00')")
    conn.commit()
    first_read = sorted(by_id())
    check("first read", "legacy01" in first_read, True)
    check("second read", sorted(by_id()), first_read)


if __name__ == "__main__":
    try:
        main()
    finally:
        for connection in db._connections.values():
            connection.close()
        STORAGE.cleanup()
    if FAILS:
        print(f"FAILED ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("all checks passed")
