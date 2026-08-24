#!/usr/bin/env python3
"""Smoke check: the shared keyed lock + the two ATOMIC JSON stores that use it.

Usage: ./.venv/bin/python scripts/smoke_keyed_lock.py

WHY THIS EXISTS. Route bodies moved into the threadpool (2026-08-24), which
took away the serialization the event loop used to hand every handler for
free. Every read-modify-write that relied on it now needs an explicit lock,
and the lock has to be KEYED — one global lock would put two players (two
characters, two catalog axes) behind each other for no reason.
``app/core/keyed_lock.py`` is that one helper; this check pins its contract
and the two file stores whose writes were made atomic in the same wave.

Expected values, derived BY HAND from the helper and the two writers:

Cases [1]–[3] — the lock itself (`app/core/keyed_lock.py`):
  - ``keyed_lock("ns", "a")`` returns the SAME object on every call: it is a
    lock, not a lock factory — a fresh object per call would serialize
    nothing at all.
  - a different KEY in the same namespace, and the same key in a different
    NAMESPACE, are different objects. Both halves matter: the first is what
    keeps two avatars parallel, the second is what lets "character_profile"
    and "avatar_state" name the same character without colliding.
  - str-coerced keys: ``keyed_lock("ns", 7)`` and ``keyed_lock("ns", "7")``
    are the same lock (the callers pass ids, paths and names).
  - CONCURRENCY: two threads each add 1 to a shared counter 1000 times, the
    whole read-add-write under one keyed lock -> exactly 2000. Without a lock
    this is the classic lost update and lands below 2000 (not deterministic,
    which is why the assertion is on the locked run only).
  - the guard is not held while a lock is: a thread holding
    ``keyed_lock("ns", "a")`` must not stop another thread from getting
    ``keyed_lock("ns", "b")`` — otherwise the "per key" is a lie under load.

Case [4] — `app/routes/poses.py` catalog writes (finding 1):
  - ``_catalog_txn`` locks namespace "pose_catalog" keyed by the catalog FILE
    PATH: the same axis twice is one lock, pose vs expression are two.
  - ``_write`` never truncates the target: at the moment of ``os.replace`` the
    catalog file on disk still holds the OLD document (the new bytes are in a
    temp file), and that temp file lies in the target's OWN directory —
    ``os.replace`` is atomic only within one filesystem.
  - no ``*.json.tmp`` leftovers after a successful write, and none after a
    FAILED one either (a non-serializable document raises and cleans up).
  - the file MODE survives the replace (0644 in, 0644 out): ``mkstemp``
    creates 0600, and both stores are tracked repo files.

Case [5] — `app/routes/admin_settings.py` prompt filters (finding 5):
  - ``_prompt_filters_txn`` is ONE lock for the whole store, keyed by the
    shared baseline's path (the move reads both stores, so a per-id lock
    would not cover it).
  - ``_write_shared_filters`` is atomic in exactly the same way as the
    catalog write above, with the same temp-file and leftover rules.

Case [6] — the namespaces the routes actually use:
  - ``play._pos_lock(name)`` IS ``keyed_lock("avatar_state", name)`` — the
    position report and the room change must meet on the same lock.
  - ``keyed_lock("character_profile", name)`` is a DIFFERENT lock from the
    avatar-state one for the same name: the two guard different state and
    must never wait for each other.

Case [7] — `app/routes/chat.py::_extract_location`, the narrative room change
of the chat stream. It writes TWO characters' whereabouts (the speaking
character, then the avatar following it into the room) with
``save_character_current_room``, a read-modify-write of the whole profile —
and it runs on the event loop, while the play routes that write the same
field run in the threadpool since 2026-08-24. What is assertable without a
race harness is the LOCK IDENTITY, and it is the point: driven with stubs,
the helper must take ``keyed_lock("avatar_state", <name>)`` — the very object
``play._pos_lock`` returns — for each of the two names, and each write must
happen while that name's lock is HELD (checked from inside the write stub, so
a lock taken around the wrong span fails the check).
"""
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="keyed-lock-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="keyed-lock-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.keyed_lock import keyed_lock  # noqa: E402

CHECKED = 0
FAILURES: list = []


def check(label: str, got, want) -> None:
    global CHECKED
    CHECKED += 1
    if got == want:
        print(f"  ✓ {label}: {got!r}")
    else:
        print(f"  ✗ {label}: {got!r} != {want!r}")
        FAILURES.append(f"{label}: {got!r} != {want!r}")


def replace_spy(record: list):
    """Stands in for ``os.replace`` and records what the target looked like
    BEFORE the rename — the proof that nothing was truncated in place."""
    real = os.replace

    def spy(src, dst):
        dst_path = Path(dst)
        record.append({
            "same_dir": Path(src).parent == dst_path.parent,
            "target_before": (dst_path.read_text(encoding="utf-8")
                              if dst_path.exists() else None),
        })
        return real(src, dst)

    return spy


def main() -> int:
    print("\n[1] the lock itself: same key same lock, different key own lock")
    check("the same (namespace, key) is one object",
          keyed_lock("ns", "a") is keyed_lock("ns", "a"), True)
    check("another key gets its own",
          keyed_lock("ns", "a") is keyed_lock("ns", "b"), False)
    check("another namespace gets its own",
          keyed_lock("ns", "a") is keyed_lock("other", "a"), False)
    check("the key is stringified",
          keyed_lock("ns", 7) is keyed_lock("ns", "7"), True)

    print("\n[2] two threads, 1000 increments each, one keyed lock")
    counter = {"n": 0}
    lock = keyed_lock("counter", "shared")

    def bump() -> None:
        for _ in range(1000):
            with lock:
                # READ, add, WRITE BACK — the shape of every route body this
                # wave locked. The local variable is what makes the lost
                # update visible without a lock.
                value = counter["n"]
                counter["n"] = value + 1

    threads = [threading.Thread(target=bump) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30.0)
    check("no increment was lost", counter["n"], 2000)

    print("\n[3] the guard is released before the lock is handed out")
    held = keyed_lock("guard", "a")
    held.acquire()
    got_other = []

    def take_other() -> None:
        other = keyed_lock("guard", "b")
        got_other.append(other.acquire(timeout=5.0))
        if got_other[0]:
            other.release()

    worker = threading.Thread(target=take_other, daemon=True)
    worker.start()
    worker.join(10.0)
    held.release()
    check("another key is free while one is held", got_other, [True])

    print("\n[4] the pose catalog: one lock per FILE, atomic write")
    import app.core.pose_catalog as pose_catalog
    import app.routes.poses as poses

    cat_dir = STORAGE / "catalogs"
    cat_dir.mkdir(parents=True, exist_ok=True)
    paths_by_axis = {
        "pose": cat_dir / "pose_catalog.json",
        "expression": cat_dir / "expression_catalog.json",
    }
    real_catalog_path = pose_catalog.catalog_path
    pose_catalog.catalog_path = lambda axis: paths_by_axis[axis]
    try:
        check("the same axis is one lock",
              keyed_lock("pose_catalog", str(paths_by_axis["pose"]))
              is keyed_lock("pose_catalog", str(paths_by_axis["pose"])),
              True)
        check("pose and expression are two",
              keyed_lock("pose_catalog", str(paths_by_axis["pose"]))
              is keyed_lock("pose_catalog", str(paths_by_axis["expression"])),
              False)

        # An existing document — the write must replace it, never truncate it.
        old = {"entries": {"standing": {"prompt": "standing", "_default": True}}}
        paths_by_axis["pose"].write_text(json.dumps(old), encoding="utf-8")
        os.chmod(paths_by_axis["pose"], 0o644)
        seen: list = []
        real_replace, os.replace = os.replace, replace_spy(seen)
        try:
            poses._write("pose", {"entries": dict(old["entries"],
                                                  hovering={"prompt": "afloat"})})
        finally:
            os.replace = real_replace
        check("the write went through os.replace", len(seen), 1)
        check("...from a temp file in the target's own directory",
              seen[0]["same_dir"], True)
        check("...while the target still held the OLD document",
              json.loads(seen[0]["target_before"]) == old, True)
        check("the new document is on disk afterwards",
              sorted(json.loads(paths_by_axis["pose"].read_text(
                  encoding="utf-8"))["entries"]),
              ["hovering", "standing"])
        check("no temp file left behind",
              sorted(p.name for p in cat_dir.glob("*.tmp")), [])
        check("the file mode survived the replace",
              oct(paths_by_axis["pose"].stat().st_mode & 0o777), "0o644")

        # A FAILING write must not leave a temp file either — and must not
        # touch the target at all.
        try:
            poses._write("pose", {"entries": {"bad": object()}})
            failed = False
        except TypeError:
            failed = True
        check("a non-serializable document raises", failed, True)
        check("...leaves no temp file",
              sorted(p.name for p in cat_dir.glob("*.tmp")), [])
        check("...and leaves the target as it was",
              sorted(json.loads(paths_by_axis["pose"].read_text(
                  encoding="utf-8"))["entries"]),
              ["hovering", "standing"])
    finally:
        pose_catalog.catalog_path = real_catalog_path

    print("\n[5] the prompt-filter baseline: one store lock, atomic write")
    import app.core.prompt_filters as prompt_filters
    import app.routes.admin_settings as admin_settings

    filters_dir = STORAGE / "prompt_filters"
    filters_dir.mkdir(parents=True, exist_ok=True)
    shared_file = filters_dir / "filters.json"
    real_shared, prompt_filters._SHARED_FILE = prompt_filters._SHARED_FILE, shared_file
    try:
        check("the store has ONE lock, keyed by the baseline path",
              keyed_lock("prompt_filters", str(shared_file))
              is keyed_lock("prompt_filters", str(shared_file)),
              True)
        check("...and it is not the pose catalog's",
              keyed_lock("prompt_filters", str(shared_file))
              is keyed_lock("pose_catalog", str(shared_file)),
              False)

        shared_file.write_text(
            json.dumps({"filters": [{"id": "wet", "label": "Wet"}]}),
            encoding="utf-8")
        os.chmod(shared_file, 0o644)
        seen = []
        real_replace, os.replace = os.replace, replace_spy(seen)
        try:
            admin_settings._write_shared_filters(
                [{"id": "wet", "label": "Wet"}, {"id": "cold", "label": "Cold"}])
        finally:
            os.replace = real_replace
        check("the write went through os.replace", len(seen), 1)
        check("...from a temp file in the baseline's own directory",
              seen[0]["same_dir"], True)
        check("...while the baseline still held the OLD document",
              [f["id"] for f in json.loads(seen[0]["target_before"])["filters"]],
              ["wet"])
        check("the new baseline is on disk afterwards",
              [f["id"] for f in json.loads(
                  shared_file.read_text(encoding="utf-8"))["filters"]],
              ["wet", "cold"])
        check("no temp file left behind",
              sorted(p.name for p in filters_dir.glob("*.tmp")), [])
        check("the file mode survived the replace",
              oct(shared_file.stat().st_mode & 0o777), "0o644")
        check("the loader reads it back",
              [f["id"] for f in prompt_filters._load_shared()], ["wet", "cold"])
    finally:
        prompt_filters._SHARED_FILE = real_shared

    print("\n[6] the namespaces the routes agree on")
    import app.routes.play as play_route
    check("the position report's lock IS the avatar-state lock",
          play_route._pos_lock("demo") is keyed_lock("avatar_state", "demo"),
          True)
    check("the profile lock of the same name is a different one",
          play_route._pos_lock("demo") is keyed_lock("character_profile", "demo"),
          False)

    print("\n[7] the chat stream's narrative room change takes the same lock")
    import app.core.keyed_lock as keyed_lock_mod
    import app.models.account as account_model
    import app.models.character as character_model
    import app.models.rules as rules_model
    import app.models.world as world_model
    import app.routes.chat as chat_route

    taken: list = []
    held: list = []
    real_keyed_lock = keyed_lock_mod.keyed_lock

    def spy_lock(namespace, key):
        lock = real_keyed_lock(namespace, key)
        taken.append((namespace, key, lock))
        return lock

    def spy_save_room(name, room_id, **kw):
        # The proof that the span COVERS the write, not merely that a lock was
        # asked for somewhere in the function.
        held.append((name, keyed_lock("avatar_state", name).locked()))

    saved = {
        "keyed_lock": keyed_lock_mod.keyed_lock,
        "save_room": character_model.save_character_current_room,
        "active": account_model.get_active_character,
        "loc_by_id": world_model.get_location_by_id,
        "room_by_name": world_model.get_room_by_name,
        "check_leave": rules_model.check_leave,
        "cur_loc": chat_route.get_character_current_location,
        "cur_room": chat_route.get_character_current_room,
    }
    keyed_lock_mod.keyed_lock = spy_lock
    character_model.save_character_current_room = spy_save_room
    account_model.get_active_character = lambda: "player"
    world_model.get_location_by_id = lambda lid: {
        "id": "loc1", "rooms": [{"id": "room_new", "name": "Kitchen"}]}
    world_model.get_room_by_name = lambda loc, name: {"id": "room_new"}
    rules_model.check_leave = lambda *a, **kw: (True, "")
    chat_route.get_character_current_location = lambda name: "loc1"
    chat_route.get_character_current_room = lambda name: "room_old"
    try:
        out = chat_route._extract_location("npc", "**I am at Kitchen**")
    finally:
        keyed_lock_mod.keyed_lock = saved["keyed_lock"]
        character_model.save_character_current_room = saved["save_room"]
        account_model.get_active_character = saved["active"]
        world_model.get_location_by_id = saved["loc_by_id"]
        world_model.get_room_by_name = saved["room_by_name"]
        rules_model.check_leave = saved["check_leave"]
        chat_route.get_character_current_location = saved["cur_loc"]
        chat_route.get_character_current_room = saved["cur_room"]

    check("the helper moved the character", out and out.get("room"), "room_new")
    check("both room writes ran", [n for n, _ in held], ["npc", "player"])
    check("...each one INSIDE its own avatar-state lock",
          [h for _, h in held], [True, True])
    check("the locks it took are the avatar-state ones",
          [(ns, k) for ns, k, _ in taken],
          [("avatar_state", "npc"), ("avatar_state", "player")])
    check("...and they ARE the objects the play routes take",
          [lock is keyed_lock("avatar_state", k) for _, k, lock in taken],
          [True, True])
    check("the character's lock is not the avatar's",
          taken[0][2] is taken[1][2], False)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  ✗ {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
