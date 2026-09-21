#!/usr/bin/env python3
"""Smoke run for the ITEM-ID FILTER on the import paths (review SEC-1).

Runs against a THROWAWAY storage directory — never touches a real world, and
writes nothing outside two temp directories.

THE HOLE THIS CLOSES. An item id travelled from the ``db/items.json`` of an
UPLOADED ZIP straight into ``storage/items/<id>`` — ``_get_item_dir`` did
``mkdir(parents=True)`` on it, and ``_restore_item_files`` then did
``shutil.rmtree(dst_dir)`` followed by a ``write_bytes`` per member. An id of
``../../plugins/installed/evil`` therefore deleted an arbitrary directory and
wrote arbitrary files anywhere the server user can reach; a
``plugins/installed/<id>/plugin.yaml`` is loaded as CODE on the next skill
reload. Props went through ``safe_prop_id``, character names through the
traversal check in ``character_io``, location ids are server-generated — the
item id was the one that had no filter at all.

The policy, hand-derived so it accepts every id the app itself mints and
rejects every shape that can leave its directory: ``[A-Za-z0-9][A-Za-z0-9_-]*``,
at most 128 characters. ``add_item`` slugifies to ``item_<lowercase>``
(``_slugify_item_id``) and ``_validate_item_id`` already demanded
``^[a-z][a-z0-9_]*$``; the 42 ids of the shared library (``shared/items/
items.json``) all match that, the longest is 13 characters. Letters, digits,
underscore and dash are allowed (the same set as ``props.safe_prop_id``, which
the neighbouring import path uses), upper case is tolerated so an older
import is not rejected over its case, and there is NO dot at all — so ``..``
cannot even be spelled.

Expected:

  [1] ``safe_item_id`` / ``require_item_id``: every legitimate shape passes
      unchanged, every crafted one raises. An id the filter would CHANGE is
      rejected, never silently renamed — a renamed item would break the
      outfit/room references that travel with it.
  [2] ``_get_item_dir`` / ``_get_shared_item_dir`` raise on a crafted id and
      create NO directory for it.
  [3] END TO END: a single-item ZIP whose id is ``../../pwned`` and which
      carries ``files/../../pwned/plugin.yaml`` is refused with a ValueError
      (the routes answer that with a 400), and afterwards nothing exists
      outside ``<storage>/items`` — specifically not the sentinel directory
      the id points at, which is seeded with a file first so that an rmtree
      would be visible.
  [4] A legitimate item ZIP still imports: same id, its file lands in
      ``<storage>/items/<id>/``.
  [5] The bundle path and the embedded-items path (location/character packs)
      refuse the same id, and refuse it BEFORE writing any of the pack's
      good items — the pack is rejected as a whole.

Usage:  ./.venv/bin/python scripts/smoke_item_id_safety.py
"""
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="item-id-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="item-id-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.content_io import (  # noqa: E402
    import_bundle_from_zip, import_item_from_zip, restore_embedded_items)
from app.models.inventory import (  # noqa: E402
    _get_item_dir, _get_shared_item_dir, list_items, require_item_id,
    safe_item_id)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def raises(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError:
        print(f"  ✓ {label}: ValueError")
        return
    except Exception as e:                                 # noqa: BLE001
        print(f"  ✗ {label}: {type(e).__name__} — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no exception — expected ValueError")
    FAILURES.append(label)


GOOD = ["item_lantern", "item_0bdbf9e0", "a", "A7", "item-with-dash",
        "Item_Mixed_Case", "x" * 128]
BAD = ["", "   ", "..", "../x", "../../plugins/installed/evil", "a/b",
       "a\\b", "/etc/passwd", "/abs", ".hidden", "item.ext", "-lead",
       "_lead", "x" * 129, "a b", "nul\x00byte", "ünïcode"]

print("\n[1] the filter itself")
for iid in GOOD:
    check(f"accepted unchanged: {iid[:20]!r}"
          + ("…" if len(iid) > 20 else ""), safe_item_id(iid), iid)
for iid in BAD:
    check(f"rejected: {iid[:32]!r}", safe_item_id(iid), "")
    raises(f"require_item_id raises for {iid[:32]!r}",
           lambda i=iid: require_item_id(i))

print("\n[2] the directory helpers refuse a crafted id and create nothing")
before = sorted(p.name for p in (STORAGE / "items").glob("*")) \
    if (STORAGE / "items").exists() else []
raises("_get_item_dir('../../pwned')",
       lambda: _get_item_dir("../../pwned"))
raises("_get_shared_item_dir('../../pwned')",
       lambda: _get_shared_item_dir("../../pwned"))
after = sorted(p.name for p in (STORAGE / "items").glob("*")) \
    if (STORAGE / "items").exists() else []
check("no directory was created on the way", after, before)
check("…and nothing landed beside the storage root",
      (STORAGE.parent / "pwned").exists(), False)


def item_zip(item_id, *, kind="item", members=None, rows=None):
    buf = io.BytesIO()
    rows = rows if rows is not None else [{
        "id": item_id, "name": "Crafted", "category": "tool",
        "description": "", "rarity": "common"}]
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"version": 1, "type": kind, "item_id": item_id, "scope": "world"}))
        zf.writestr("db/items.json", json.dumps(rows))
        for name, data in (members or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


print("\n[3] a crafted single-item ZIP is refused, and touches nothing")
SENTINEL = STORAGE / "sentinel"
SENTINEL.mkdir(parents=True, exist_ok=True)
(SENTINEL / "keep.txt").write_text("do not delete me", encoding="utf-8")
EVIL_ID = "../sentinel"
evil = item_zip(EVIL_ID, members={
    "files/../sentinel/plugin.yaml": b"id: evil\n",
    "files/../sentinel/skill.py": b"import os\n",
})
raises("import_item_from_zip refuses it",
       lambda: import_item_from_zip(evil, target="world"))
check("the sentinel directory is untouched",
      (SENTINEL / "keep.txt").read_text(encoding="utf-8"), "do not delete me")
check("…and no file was written into it",
      sorted(p.name for p in SENTINEL.iterdir()), ["keep.txt"])
check("no item row was created", [i["id"] for i in list_items()], [])

# The same with a traversal that leaves the storage root entirely.
ESCAPE = STORAGE.parent / "item-id-smoke-escape"
ESCAPE.mkdir(parents=True, exist_ok=True)
raises("…and one that leaves the storage root",
       lambda: import_item_from_zip(
           item_zip(f"../../{ESCAPE.name}",
                    members={f"files/../../{ESCAPE.name}/x.txt": b"x"}),
           target="world"))
check("that directory is untouched too",
      sorted(p.name for p in ESCAPE.iterdir()), [])

print("\n[4] a legitimate item ZIP still imports")
ok_zip = item_zip("item_lantern",
                  members={"files/item_lantern/image.png": b"PNG"})
res = import_item_from_zip(ok_zip, target="world")
check("imported under its own id", res["item_id"], "item_lantern")
check("the row is there", [i["id"] for i in list_items()], ["item_lantern"])
check("the file landed in the item directory",
      (STORAGE / "items" / "item_lantern" / "image.png").read_bytes(), b"PNG")

print("\n[5] bundle and embedded items refuse the same id, as a whole")
bundle = item_zip("item_ok_two", kind="item_bundle", rows=[
    {"id": "item_ok_two", "name": "Fine", "category": "tool"},
    {"id": "../sentinel", "name": "Crafted", "category": "tool"}])
raises("import_bundle_from_zip refuses the bundle",
       lambda: import_bundle_from_zip(bundle, target="world"))
check("…and none of its items was written",
      [i["id"] for i in list_items()], ["item_lantern"])

embedded = io.BytesIO()
with zipfile.ZipFile(embedded, "w") as zf:
    zf.writestr("db/items.json", json.dumps([
        {"id": "item_ok_three", "name": "Fine", "category": "tool"},
        {"id": "../sentinel", "name": "Crafted", "category": "tool"}]))
    zf.writestr("item_files/../sentinel/x.txt", b"x")
zf_embedded = zipfile.ZipFile(io.BytesIO(embedded.getvalue()))
raises("restore_embedded_items refuses the pack",
       lambda: restore_embedded_items(zf_embedded))
check("…and wrote none of its items",
      [i["id"] for i in list_items()], ["item_lantern"])
check("the sentinel survived all of it",
      sorted(p.name for p in SENTINEL.iterdir()), ["keep.txt"])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
