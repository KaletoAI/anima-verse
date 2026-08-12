#!/usr/bin/env python3
"""Smoke run for the standalone PROP export/import plus COLLECTION packs
(Seamless World, E9 Tasks 3 + 4).

Runs against a THROWAWAY storage directory — never touches a real world.

Part 1: the prop round-trip (Task 3). Part 2: collection packs (Task 4) —
builder, preview and the generic install dispatch, seeded on top of part 1.

Seed (all files are dummy bytes, nothing is generated):
  * ONE prop via create_prop(name="Oak Chair", category="seating",
    width_m=0.5, depth_m=0.5, height_m=0.9). create_prop writes sidecar.json;
    the smoke adds the four files a real prop carries:
        model_1.glb   (mesh bytes)
        model_1.json  (per-mesh sidecar)
        selection.json ({"model": {"full": "model_1.glb"}})
        source.png    (the product-shot render)
    -> the prop dir holds exactly 5 files.

Expectations, derived by hand from that seed:

  [1] export_prop_to_zip(pid) namelist, sorted:
        files/model_1.glb, files/model_1.json, files/selection.json,
        files/sidecar.json, files/source.png, manifest.json
      i.e. the WHOLE props/<pid>/ directory under files/, nothing else.
      manifest.version   == 1
      manifest.type      == "prop"
      manifest.prop_id   == pid
      manifest.prop_name == "Oak Chair"
      manifest.files     == the five relative names, sorted
      manifest.exported_at is set.

  [2] preview_import_zip(zip) — the prop still exists here:
      type "prop", ONE element {kind: "prop", id: pid, name: "Oak Chair",
      exists: True}. multi == False.

  [3] delete_prop(pid) + import_prop_from_zip(zip):
      the id is KEPT (room placements reference it — a renamed prop would
      arrive orphaned), so prop_id == pid. The directory comes back
      byte-identical: all five files with their seeded bytes.
      get_prop(pid)["name"] == "Oak Chair", and the dims survive
      (0.5 / 0.5 / 0.9) — they live in the sidecar, which travels.

  [4] SECOND import without overwrite → {"status": "exists", "prop_id": pid}
      and NOTHING changes: a file the smoke overwrites in between
      (model_1.glb := b"LOCAL") keeps its local bytes.

  [5] Same ZIP with overwrite=True → the folder is REPLACED: model_1.glb is
      the exported byte string again, and a file that only exists locally
      (stray.txt) is gone.

  [6] preview after [3]: exists == True (the prop is back).

  [7] Every rejection happens BEFORE the first byte on disk changes, so a
      broken ZIP never costs the prop that is already there:
        * manifest with an invalid prop id ("../evil")      → ValueError
        * ZIP without files/sidecar.json                    → ValueError
        * ZIP with an intact directory but a CRC-corrupt member
          (mesh stored uncompressed, bytes flipped)         → ValueError
        * the same with a DEFLATED member (what the exporter writes) whose
          compressed bytes are zeroed — fails inside zlib, not as an
          OSError                                           → ValueError
      each of them a ValueError, never BadZipFile/zlib.error — the route maps
      those to 400, anything else would be a 500.
      after each of them the prop directory is still byte-identical to the
      export. A ZIP with a traversal member (files/../evil.txt) writes
      nothing outside the prop dir (Zip-Slip guard).

  [8] The marketplace dispatchers know the type: SUPPORTED_TYPES contains
      "prop", _dispatch_install("prop", zip) installs it, and
      _dispatch_install_selected(..., overwrite=True) replaces it.
      _export_zip_for("prop", pid) yields the same manifest type.

Part 2 — collections (Task 4). Additional seed: ONE location "Old Mill" via
add_location(rooms=[{"name": "Mill floor"}]); the prop of part 1 is back in
place (byte-identical to the export, see [5]/[8]).

  [9] export_collection_to_zip("Testpaket", [location, prop]) —
      manifest.version == 1, type "collection", name "Testpaket",
      contents == [{"type": "location", "name": "Old Mill",
                    "file": "packs/location-old-mill.zip"},
                   {"type": "prop", "name": "Oak Chair",
                    "file": "packs/prop-oak-chair.zip"}]
      i.e. the slug is "<type>-<name>" and the names come out of each SUB
      manifest (location_name / prop_name), not out of the request.
      namelist, sorted: manifest.json + the two packs/*.zip — nothing else.
      Every sub-ZIP carries its own manifest of the declared type, and the
      prop pack is byte-identical to export_prop_to_zip(PID).
      This is exactly the shape `_install_collection` consumes and
      scripts/make_collection_pack.py writes.

 [10] Twice the SAME prop in one collection → the slug is numbered instead of
      colliding: packs/prop-oak-chair.zip + packs/prop-oak-chair-2.zip, both
      members really in the ZIP.

 [11] Rejections, before a single byte is packed:
        empty entries                   → ValueError
        type "skill_package" / "collection" / "" → ValueError (export_zip_for
                                          only knows the content types)
        an id that does not exist       → ValueError (from the sub exporter)

 [12] preview_import_zip(collection) — type "collection", multi True, two
      elements whose `id` is the ZIP-internal FILE path (that is what the
      selection filter matches on), name from the manifest, exists False
      (a collection never claims to know what its sub-packs will do).

 [13] Install through the marketplace path: delete the location AND the prop,
      then _install_collection(blob) → installed 2, failed 0, both results
      "success". The location is back under its own name (a location import
      always mints a NEW id, so it is matched by name) and the prop directory
      is byte-identical to the export again.

 [14] The generic dispatch, everything already present:
      _dispatch_install_selected(blob, selected_ids=None, overwrite=False)
      → the location arrives a SECOND time as "Old Mill (2)" (imports never
      overwrite, they mint a new id), the prop reports "exists" — the shape
      import_prop_from_zip returns instead of raising — so:
        installed 1, failed 1, statuses ["success", "exists"].
      Nothing aborts: the entry after a non-success entry still runs.

 [15] Selection filter: _dispatch_install_selected(blob,
      selected_ids={"packs/prop-oak-chair.zip"}) → exactly ONE result (the
      prop), and the number of "Old Mill*" locations is unchanged. An empty
      selection means all (that is [14]).

 [16] A contents entry whose file is not in the ZIP → "skipped", and the
      other entry still installs. Both install paths run through ONE
      implementation, so the marketplace path keeps its guard: a ZIP whose
      manifest claims another type is rejected, never walked.

 [17] The route POST /api/content/collection/export answers a ZIP:
      media_type "application/zip", Content-Disposition
      `attachment; filename="collection_testpaket.zip"`, and the body is a
      collection manifest with the two entries. An entry of type
      "skill_package" is rejected with HTTP 400.

 [18] A collection whose only entry is already there installs NOTHING, and the
      result says so: results ["exists"], installed 0, failed 1, top-level
      status "failed" — the flag the import dialog branches on so a run in
      which nothing landed cannot read as a green "Imported". (The dialog's
      own branch is TypeScript; it is covered by tsc + review, not here.)

 [19] A collection carrying a `skill_package` entry never runs its code: the
      entry is "skipped" with a reason naming the executable code, the
      harmless entry beside it still runs, and neither plugins/installed/ nor
      the storage dir gains anything. Both install paths are checked — a
      collection is installed with ONE click and has no trust gate, so the
      only safe place for executable packages is their own install.

 [20] The overwrite flag reaches the SUB-packs. A local change inside the prop
      directory plus a second install with overwrite=True → the prop answers
      "success" and its directory is the exported one again, instead of the
      "exists" of case [14]. Both entry points carry the flag: the generic
      dispatch and the marketplace path (_install_collection). The LOCATION
      keeps duplicating either way — its importer knows no overwrite at all
      and always mints a new id, so the "Old Mill" count still grows by one.

Usage:  ./.venv/bin/python scripts/smoke_content_prop_collection.py
"""
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="content-prop-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="content-prop-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    shown = repr(actual)
    if len(shown) > 160:
        shown = shown[:157] + "…"
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {shown}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


from app.core.content_io import (export_prop_to_zip,  # noqa: E402
                                 import_prop_from_zip, preview_import_zip)
from app.core.props import (_prop_dir, create_prop, delete_prop,  # noqa: E402
                            get_prop)

# ── Seed ────────────────────────────────────────────────────────────────

prop = create_prop(name="Oak Chair", category="seating",
                   width_m=0.5, depth_m=0.5, height_m=0.9)
PID = prop["id"]
PROP_DIR = _prop_dir(PID)
SEED_FILES = {
    "model_1.glb": b"GLB-prop-mesh",
    "model_1.json": json.dumps({"created_at": "2026-08-10T00:00:00Z",
                                "format": "glb", "tier": "full"}).encode(),
    "selection.json": json.dumps({"model": {"full": "model_1.glb"}}).encode(),
    "source.png": b"PNG-product-shot",
}
for name, blob in SEED_FILES.items():
    (PROP_DIR / name).write_bytes(blob)

ALL_NAMES = sorted(list(SEED_FILES) + ["sidecar.json"])


def dir_snapshot() -> dict:
    d = _prop_dir(PID)
    if not d or not d.is_dir():
        return {}
    return {p.relative_to(d).as_posix(): p.read_bytes()
            for p in sorted(d.rglob("*")) if p.is_file()}


print("[1] export_prop_to_zip — the whole prop directory + manifest")
blob = export_prop_to_zip(PID)
zf = zipfile.ZipFile(io.BytesIO(blob))
names = sorted(zf.namelist())
check("namelist", names, [f"files/{n}" for n in ALL_NAMES] + ["manifest.json"])
manifest = json.loads(zf.read("manifest.json"))
check("manifest.version", manifest["version"], 1)
check("manifest.type", manifest["type"], "prop")
check("manifest.prop_id", manifest["prop_id"], PID)
check("manifest.prop_name", manifest["prop_name"], "Oak Chair")
check("manifest.files", manifest["files"], ALL_NAMES)
check("manifest.exported_at is set", bool(manifest.get("exported_at")), True)
check("the mesh bytes travel",
      zf.read("files/model_1.glb"), SEED_FILES["model_1.glb"])
zf.close()
EXPORTED = dir_snapshot()

print("\n[2] preview_import_zip — one element, flagged as existing")
prev = preview_import_zip(blob)
check("type", prev["type"], "prop")
check("multi", prev["multi"], False)
check("elements", prev["elements"],
      [{"kind": "prop", "id": PID, "name": "Oak Chair", "exists": True}])

print("\n[3] delete + import — the id is kept, the folder comes back")
check("prop deleted", delete_prop(PID), True)
check("directory gone", (_prop_dir(PID) or Path("/nonexistent")).is_dir(), False)
res = import_prop_from_zip(blob)
check("status", res["status"], "success")
check("prop_id kept", res["prop_id"], PID)
check("directory identical", dir_snapshot(), EXPORTED)
back = get_prop(PID)
check("name", (back or {}).get("name"), "Oak Chair")
check("dims survive",
      [(back or {}).get("width_m"), (back or {}).get("depth_m"),
       (back or {}).get("height_m")], [0.5, 0.5, 0.9])

print("\n[4] second import without overwrite — reported, nothing touched")
(_prop_dir(PID) / "model_1.glb").write_bytes(b"LOCAL")
(_prop_dir(PID) / "stray.txt").write_bytes(b"local-only")
res2 = import_prop_from_zip(blob)
check("status", res2["status"], "exists")
check("prop_id", res2["prop_id"], PID)
check("local mesh untouched",
      (_prop_dir(PID) / "model_1.glb").read_bytes(), b"LOCAL")
check("local-only file untouched",
      (_prop_dir(PID) / "stray.txt").exists(), True)

print("\n[5] import with overwrite=True — the folder is REPLACED")
res3 = import_prop_from_zip(blob, overwrite=True)
check("status", res3["status"], "success")
check("directory identical to the export", dir_snapshot(), EXPORTED)
check("local-only file gone", (_prop_dir(PID) / "stray.txt").exists(), False)

print("\n[6] preview after re-import — exists again")
check("exists", preview_import_zip(blob)["elements"][0]["exists"], True)


def _rewrite(manifest_patch: dict = None, extra: dict = None) -> bytes:
    """Rebuild the export ZIP with a patched manifest / extra members."""
    src = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for member in src.namelist():
            if member == "manifest.json":
                m = json.loads(src.read(member))
                m.update(manifest_patch or {})
                dst.writestr(member, json.dumps(m))
            else:
                dst.writestr(member, src.read(member))
        for name, data in (extra or {}).items():
            dst.writestr(name, data)
    src.close()
    return out.getvalue()


print("\n[7] every rejection happens before the first byte on disk changes")
try:
    import_prop_from_zip(_rewrite({"prop_id": "../evil"}))
    check("invalid prop id raises", "no error", "ValueError")
except ValueError as e:
    check("invalid prop id raises ValueError", True, True)
    print(f"       message: {e}")
try:
    stripped = io.BytesIO()
    src_zip = zipfile.ZipFile(io.BytesIO(blob))
    with zipfile.ZipFile(stripped, "w", zipfile.ZIP_DEFLATED) as dst_zip:
        for m in src_zip.namelist():
            if m != "files/sidecar.json":
                dst_zip.writestr(m, src_zip.read(m))
    src_zip.close()
    import_prop_from_zip(stripped.getvalue(), overwrite=True)
    check("a ZIP without sidecar.json raises", "no error", "ValueError")
except ValueError as e:
    check("a ZIP without sidecar.json raises ValueError", True, True)
    print(f"       message: {e}")
check("and the existing prop survived it", dir_snapshot(), EXPORTED)

# A ZIP whose central directory is intact but whose PAYLOAD is corrupt: the
# mesh member is re-stored UNCOMPRESSED and its bytes are flipped afterwards,
# so the CRC check fires inside zf.read(). The old prop must survive that —
# reading happens before the overwrite deletes anything.
src_zip = zipfile.ZipFile(io.BytesIO(blob))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as dst_zip:
    for m in src_zip.namelist():
        dst_zip.writestr(m, src_zip.read(m), zipfile.ZIP_STORED)
src_zip.close()
corrupt = buf.getvalue().replace(b"GLB-prop-mesh", b"XXX-prop-mesh")
check("the corruption really changed the archive", corrupt != buf.getvalue(), True)
try:
    import_prop_from_zip(corrupt, overwrite=True)
    check("a corrupt member raises", "no error", "ValueError")
except ValueError as e:
    check("a corrupt member raises ValueError (route maps it to 400)", True, True)
    print(f"       message: {e}")
check("the existing prop survived the corrupt archive", dir_snapshot(), EXPORTED)

# The same again for the format the EXPORTER actually emits: ZIP_DEFLATED.
# A deflate member fails inside zlib (zlib.error) or runs out of stream
# (EOFError) — neither is an OSError, so the mapping to ValueError has to name
# them explicitly or the route answers 500 instead of 400. The compressed
# bytes are replaced in place (same length, all offsets stay valid) by zeros,
# which is never a valid deflate stream.
def _deflated_member_zeroed(zip_bytes: bytes, member: str):
    zi = zipfile.ZipFile(io.BytesIO(zip_bytes))
    info = zi.getinfo(member)
    zi.close()
    off = info.header_offset
    name_len = int.from_bytes(zip_bytes[off + 26:off + 28], "little")
    extra_len = int.from_bytes(zip_bytes[off + 28:off + 30], "little")
    start = off + 30 + name_len + extra_len
    end = start + info.compress_size
    return (zip_bytes[:start] + b"\x00" * info.compress_size + zip_bytes[end:],
            info.compress_type)


broken, ctype = _deflated_member_zeroed(blob, "files/model_1.glb")
check("the export really deflates its members", ctype, zipfile.ZIP_DEFLATED)
try:
    import_prop_from_zip(broken, overwrite=True)
    check("a corrupt DEFLATED member raises", "no error", "ValueError")
except ValueError as e:
    check("a corrupt DEFLATED member raises ValueError too", True, True)
    print(f"       message: {e}")
check("the existing prop survived the deflate corruption",
      dir_snapshot(), EXPORTED)

outside = STORAGE / "evil.txt"
import_prop_from_zip(_rewrite(extra={"files/../evil.txt": b"pwned"}),
                     overwrite=True)
check("traversal member written outside the prop dir", outside.exists(), False)
check("directory still the exported one", dir_snapshot(), EXPORTED)

print("\n[8] marketplace dispatchers know the type")
from app.routes.content_packs import (SUPPORTED_TYPES,  # noqa: E402
                                      _dispatch_install,
                                      _dispatch_install_selected,
                                      _export_zip_for)
check("SUPPORTED_TYPES", "prop" in SUPPORTED_TYPES, True)
check("_export_zip_for type",
      json.loads(zipfile.ZipFile(io.BytesIO(_export_zip_for("prop", PID)))
                 .read("manifest.json"))["type"], "prop")
check("prop deleted for the install test", delete_prop(PID), True)
check("_dispatch_install installs", _dispatch_install("prop", blob)["status"],
      "success")
check("_dispatch_install answers 'exists' on the second run",
      _dispatch_install("prop", blob)["status"], "exists")
(_prop_dir(PID) / "model_1.glb").write_bytes(b"LOCAL")
check("_dispatch_install_selected without overwrite",
      _dispatch_install_selected(blob, selected_ids=None,
                                 overwrite=False)["status"], "exists")
check("_dispatch_install_selected passes overwrite through",
      _dispatch_install_selected(blob, selected_ids=None,
                                 overwrite=True)["status"], "success")
check("overwrite really replaced the folder", dir_snapshot(), EXPORTED)


# ── Part 2: collection packs (E9 Task 4) ────────────────────────────────

import asyncio  # noqa: E402
from app.core.content_io import export_collection_to_zip  # noqa: E402
from app.models.world import (add_location, delete_location,  # noqa: E402
                              list_locations)

MILL = add_location("Old Mill", "A mill by the river.",
                    rooms=[{"name": "Mill floor", "description": "Sacks."}])
LOC_ID = MILL["id"]
PROP_PACK = export_prop_to_zip(PID)


def mill_count() -> int:
    """How many locations carry the seeded name (copies get a '(n)' suffix)."""
    return sum(1 for l in list_locations()
               if (l.get("name") or "").startswith("Old Mill"))


print("\n[9] export_collection_to_zip — one ZIP holding two ordinary packs")
coll = export_collection_to_zip("Testpaket", [
    {"type": "location", "id": LOC_ID},
    {"type": "prop", "id": PID},
])
czf = zipfile.ZipFile(io.BytesIO(coll))
cman = json.loads(czf.read("manifest.json"))
check("manifest.version", cman["version"], 1)
check("manifest.type", cman["type"], "collection")
check("manifest.name", cman["name"], "Testpaket")
check("contents length", len(cman["contents"]), 2)
check("contents", cman["contents"], [
    {"type": "location", "name": "Old Mill", "file": "packs/location-old-mill.zip"},
    {"type": "prop", "name": "Oak Chair", "file": "packs/prop-oak-chair.zip"},
])
check("namelist", sorted(czf.namelist()),
      ["manifest.json", "packs/location-old-mill.zip", "packs/prop-oak-chair.zip"])
for entry in cman["contents"]:
    sub = json.loads(zipfile.ZipFile(io.BytesIO(czf.read(entry["file"])))
                     .read("manifest.json"))
    check(f"sub manifest type of {entry['file']}", sub["type"], entry["type"])
check("the prop pack travels byte-identical",
      czf.read("packs/prop-oak-chair.zip"), PROP_PACK)
czf.close()

print("\n[10] a slug collision is numbered, never overwritten")
twice = export_collection_to_zip("Doppelt", [
    {"type": "prop", "id": PID},
    {"type": "prop", "id": PID},
])
tzf = zipfile.ZipFile(io.BytesIO(twice))
tman = json.loads(tzf.read("manifest.json"))
check("files", [e["file"] for e in tman["contents"]],
      ["packs/prop-oak-chair.zip", "packs/prop-oak-chair-2.zip"])
check("both members really in the ZIP", sorted(tzf.namelist()),
      ["manifest.json", "packs/prop-oak-chair-2.zip", "packs/prop-oak-chair.zip"])
tzf.close()

print("\n[11] rejections happen before anything is packed")
for label, entries in (
    ("empty entries", []),
    ("skill_package", [{"type": "skill_package", "id": "x"}]),
    ("nested collection", [{"type": "collection", "id": "x"}]),
    ("empty type", [{"type": "", "id": "x"}]),
    ("unknown prop id", [{"type": "prop", "id": "no_such_prop"}]),
):
    try:
        export_collection_to_zip("Nope", entries)
        check(f"{label} raises", "no error", "ValueError")
    except ValueError as e:
        check(f"{label} raises ValueError", True, True)
        print(f"       message: {e}")

print("\n[12] preview_import_zip knows the collection type")
cprev = preview_import_zip(coll)
check("type", cprev["type"], "collection")
check("multi", cprev["multi"], True)
check("elements", cprev["elements"], [
    {"kind": "location", "id": "packs/location-old-mill.zip",
     "name": "Old Mill", "exists": False},
    {"kind": "prop", "id": "packs/prop-oak-chair.zip",
     "name": "Oak Chair", "exists": False},
])

print("\n[13] _install_collection — both sub-packs land")
check("location deleted", delete_location(LOC_ID), True)
check("prop deleted", delete_prop(PID), True)
from app.routes.content_packs import _install_collection  # noqa: E402
inst = _install_collection(coll)
check("installed", inst["installed"], 2)
check("failed", inst["failed"], 0)
check("statuses", [r["status"] for r in inst["results"]], ["success", "success"])
check("collection_name", inst["collection_name"], "Testpaket")
check("the location is back", mill_count(), 1)
check("the prop directory is back byte-identical", dir_snapshot(), EXPORTED)

print("\n[14] the generic dispatch — per-entry status, never an abort")
sel_all = _dispatch_install_selected(coll, selected_ids=None, overwrite=False)
check("installed", sel_all["installed"], 1)
check("failed", sel_all["failed"], 1)
check("statuses", [r["status"] for r in sel_all["results"]], ["success", "exists"])
check("types", [r["type"] for r in sel_all["results"]], ["location", "prop"])
check("the location arrived a second time", mill_count(), 2)

print("\n[15] the selection filter picks single entries")
sel_one = _dispatch_install_selected(
    coll, selected_ids={"packs/prop-oak-chair.zip"}, overwrite=False)
check("one result only", len(sel_one["results"]), 1)
check("and it is the prop", sel_one["results"][0]["type"], "prop")
check("no further location was created", mill_count(), 2)

print("\n[16] a contents entry without its file is skipped, the rest installs")
broken_coll = io.BytesIO()
src_coll = zipfile.ZipFile(io.BytesIO(coll))
with zipfile.ZipFile(broken_coll, "w", zipfile.ZIP_DEFLATED) as dst_coll:
    for m in src_coll.namelist():
        if m == "packs/location-old-mill.zip":
            continue                       # the entry stays in the manifest
        dst_coll.writestr(m, src_coll.read(m))
src_coll.close()
sel_broken = _dispatch_install_selected(broken_coll.getvalue(),
                                        selected_ids=None, overwrite=False)
check("statuses", [r["status"] for r in sel_broken["results"]],
      ["skipped", "exists"])
check("still no new location", mill_count(), 2)

# Both install paths share ONE implementation, so the marketplace path keeps
# its own guard: a ZIP that claims a different type is never walked as one.
mislabeled = io.BytesIO()
src_coll = zipfile.ZipFile(io.BytesIO(coll))
with zipfile.ZipFile(mislabeled, "w", zipfile.ZIP_DEFLATED) as dst_coll:
    for m in src_coll.namelist():
        if m == "manifest.json":
            wrong = json.loads(src_coll.read(m))
            wrong["type"] = "prop"
            dst_coll.writestr(m, json.dumps(wrong))
        else:
            dst_coll.writestr(m, src_coll.read(m))
src_coll.close()
try:
    _install_collection(mislabeled.getvalue())
    check("a manifest that is not a collection raises", "no error", "ValueError")
except ValueError as e:
    check("a manifest that is not a collection raises ValueError", True, True)
    print(f"       message: {e}")

class _FakeRequest:
    """Minimal stand-in — the route only awaits `request.json()`."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


print("\n[17] POST /api/content/collection/export answers a ZIP")
from fastapi import HTTPException  # noqa: E402
from app.routes.content_packs import export_collection_route  # noqa: E402
LOC2_ID = next(l["id"] for l in list_locations()
               if (l.get("name") or "").startswith("Old Mill"))
resp = asyncio.run(export_collection_route(_FakeRequest({
    "name": "Testpaket",
    "entries": [{"type": "location", "id": LOC2_ID}, {"type": "prop", "id": PID}],
})))
check("media_type", resp.media_type, "application/zip")
check("Content-Disposition", resp.headers.get("content-disposition"),
      'attachment; filename="collection_testpaket.zip"')
rman = json.loads(zipfile.ZipFile(io.BytesIO(resp.body)).read("manifest.json"))
check("body is a collection manifest", rman["type"], "collection")
check("with both entries", [e["type"] for e in rman["contents"]],
      ["location", "prop"])
try:
    asyncio.run(export_collection_route(_FakeRequest({
        "name": "Nope", "entries": [{"type": "skill_package", "id": "x"}]})))
    check("skill_package is rejected", "no error", "HTTP 400")
except HTTPException as e:
    check("skill_package is rejected with 400", e.status_code, 400)
    print(f"       detail: {e.detail}")


print("\n[18] a run in which nothing landed says so")
only_prop = export_collection_to_zip("Nur der Stuhl", [{"type": "prop", "id": PID}])
nothing = _dispatch_install_selected(only_prop, selected_ids=None, overwrite=False)
check("the only entry already exists",
      [r["status"] for r in nothing["results"]], ["exists"])
check("installed", nothing["installed"], 0)
check("failed", nothing["failed"], 1)
check("top-level status", nothing["status"], "failed")

print("\n[19] a skill_package inside a collection is never installed")
CODE_ZIP = io.BytesIO()
with zipfile.ZipFile(CODE_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("manifest.json", json.dumps({"version": 1, "type": "skill_package",
                                            "package_id": "evil"}))
    z.writestr("plugin.yaml", "id: evil\n")
code_coll = io.BytesIO()
with zipfile.ZipFile(code_coll, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("manifest.json", json.dumps({
        "version": 1, "type": "collection", "name": "Trojaner",
        "contents": [
            {"type": "skill_package", "name": "Evil", "file": "packs/evil.zip"},
            {"type": "prop", "name": "Oak Chair", "file": "packs/prop-oak-chair.zip"},
        ],
    }))
    z.writestr("packs/evil.zip", CODE_ZIP.getvalue(), zipfile.ZIP_STORED)
    z.writestr("packs/prop-oak-chair.zip", PROP_PACK, zipfile.ZIP_STORED)
from app.core.paths import get_storage_dir  # noqa: E402
INSTALLED_DIR = Path(__file__).resolve().parents[1] / "plugins" / "installed" / "evil"
for blob_in, label in ((code_coll.getvalue(), "generic dispatch"),
                       (code_coll.getvalue(), "marketplace path")):
    res_code = (_dispatch_install_selected(blob_in, selected_ids=None, overwrite=False)
                if label == "generic dispatch" else _install_collection(blob_in))
    check(f"{label}: the code entry is skipped",
          res_code["results"][0]["status"], "skipped")
    check(f"{label}: with a reason naming the code",
          "executable code" in (res_code["results"][0].get("error") or ""), True)
    check(f"{label}: the harmless entry still runs",
          res_code["results"][1]["status"], "exists")
check("nothing was written to plugins/installed", INSTALLED_DIR.exists(), False)
check("and nothing to the throwaway storage either",
      (get_storage_dir() / "plugins").exists(), False)

print("\n[20] overwrite reaches the sub-packs — the second install UPDATES")
# A local file the export does not have: without overwrite the prop reports
# "exists" and stays untouched (case [4]/[14]), with overwrite it is replaced.
(_prop_dir(PID) / "stray2.txt").write_text("local", encoding="utf-8")
mills_before = mill_count()
upd = _dispatch_install_selected(coll, selected_ids=None, overwrite=True)
check("the prop is updated instead of 'exists'",
      [r["status"] for r in upd["results"]], ["success", "success"])
check("installed", upd["installed"], 2)
check("failed", upd["failed"], 0)
check("the prop directory is the exported one again", dir_snapshot(), EXPORTED)
check("the local-only file is gone",
      (_prop_dir(PID) / "stray2.txt").exists(), False)
# The location importer knows no overwrite — it always mints a new id, so a
# collection containing a location duplicates it with the flag as well.
check("the location duplicates anyway (no overwrite concept there)",
      mill_count(), mills_before + 1)

# The marketplace path carries the flag too.
(_prop_dir(PID) / "stray3.txt").write_text("local", encoding="utf-8")
mp = _install_collection(coll, overwrite=True)
check("marketplace path: the prop is updated",
      [r["status"] for r in mp["results"]], ["success", "success"])
check("marketplace path: the prop directory is restored",
      dir_snapshot(), EXPORTED)
check("marketplace path: the location duplicates as well",
      mill_count(), mills_before + 2)

# ── Summary ─────────────────────────────────────────────────────────────

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("OK")
