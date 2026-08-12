#!/usr/bin/env python3
"""Smoke run for the FULL location export AND import: 3D models, props and
room items travel inside the ZIP and arrive remapped (Seamless World, E9
Tasks 1 + 2).

Runs against a THROWAWAY storage directory — never touches a real world.

Seed (all files are dummy bytes, nothing is generated):
  * Location "Inn" via add_location() with two rooms ("Taproom", "Cellar").
    add_location also appends the reserved ground room, so the location ends
    up with three rooms; room 1 = "Taproom".
    The location is placed at pos_x/pos_z = 12.5/-3.25 with yaw_deg = 42.0,
    so "the import lands unplaced" is a real assertion and not a tautology.
  * storage/locations/<loc_id>/model3d/ gets
        building_1.glb, building_1.json,
        room_<r1>_1.glb, room_<r1>_1.json,
        room___ground___1.glb, room___ground___1.json,
        selection.json = {"building": {"full": "building_1.glb"},
                          "room_<r1>": {"full": "room_<r1>_1.glb"},
                          "room___ground__": {"full": "room___ground___1.glb"}}
    -> 7 files, so the manifest must report model3d_file_count == 7.
    The ground room gets a model on purpose: its id is RESERVED, so the
    import must leave both the id and that filename alone.
  * One prop via create_prop(name="Chair"); create_prop writes sidecar.json,
    the smoke adds model_1.glb -> the prop dir holds exactly 2 files.
    The prop is placed in room 1:
        layout.props = [{"prop_id": <pid>, "at": [0.5, 0.5], "yaw": 0}]
  * One world item via _save_items([...]) plus a dummy bild.png in its item
    dir, placed in room 1 via add_item_to_room().

Expectations, derived by hand from the seed above:
  files/model3d/<rel>      — one entry per file under model3d/, so
                             building_1.glb and selection.json are both there.
  props/<pid>/<rel>        — the WHOLE prop dir, i.e. model_1.glb AND
                             sidecar.json (without the sidecar the prop has no
                             dims on the far side).
  db/items.json            — the referenced world item, character-export shape.
  item_files/<item_id>/bild.png
  manifest.version         == 1 (MANIFEST_VERSION is unchanged — the new keys
                             are purely additive).
  manifest.model3d_file_count == 7   (the seven files listed above)
  manifest.prop_ids        == [<pid>] (exactly the one referenced prop)
  manifest.embedded_items  == [<item_id>]
  The gallery contract is untouched: no gallery files were seeded, so
  manifest.files stays [].

Import expectations (Task 2), derived by hand from the same seed. The ZIP is
re-imported into the SAME storage — that stands in for a target world that
already owns the prop:

  [4] Import #1 — the prop exists here already
      import always mints a NEW location id and NEW room ids (room_id_map) —
      with ONE exception, the reserved ground room, which maps to itself —
      but the model3d files and selection.json are named after the OLD room
      ids, so the remap is what this task is about:
        pos_x / pos_z  -> None   (placement is reset; the user places the
                                  copy in the map editor — without this the
                                  copy lands exactly ON the original)
        yaw_deg        -> 0.0    the seeded 42.0 must NOT travel. It reads as
                                  0.0 rather than None because world.py
                                  backfills yaw_deg from its column for every
                                  location dict (see the comment there) —
                                  0.0 IS "no rotation".
        building_1.glb            unchanged (building* is not room-scoped)
        room_<r1_new>_1.glb       present, room_<r1_old>_1.glb gone
        selection.json            key "room_<r1_old>" -> "room_<r1_new>" and
                                  its filename value remapped with it
        __ground__                still there, under its own id, and its
                                  model file/selection entry keep their name
                                  (a self-mapped id is a no-op for the remap)
        model3d_files  == 7      (the seven seeded files)
        props_existing == [pid]  never overwritten
        props_imported == []     nothing to install
        props_missing  == []
        items_imported == []     the item id already exists -> not duplicated
        the prop placement still names the SAME prop id (prop ids are global,
        they are not remapped)

  [5] Import #2 — prop deleted first: props_imported == [pid], and the prop
      directory comes back byte-identical (model_1.glb + sidecar.json).

  [6] Import #3 — ZIP rewritten without its props/ members AND the prop
      deleted: props_missing == [pid]. This is the case the export can
      produce on its own (a placement whose prop has no directory on disk is
      skipped silently on export) — it must be visible, never swallowed.

  [7] An OLD v1 ZIP (manifest + db/location.json + files/gallery/ only, none
      of the new directories) must still import cleanly: model3d_files == 0,
      props_imported == [], items_imported == [], the gallery file arrives,
      and the prop it references — still deleted from [6] — is reported in
      props_missing instead of crashing.

  [8] preview_import_zip names the bundle contents from the manifest:
      "Inn (3 rooms, 7 model files, 1 props)", and falls back to zeros for
      the old ZIP.

  [9] A ZIP whose props/ directory carries an id the prop store would refuse
      ("Bad Prop!") does not count as a delivered dependency: nothing is
      installed under that name, and the placement referencing it lands in
      props_missing.

 [10] A CLONE export (db/location.json carrying template_location_id, which
      an export writes verbatim) becomes a STANDALONE copy. The marker is
      dropped, so:
        _owner_id(new_id) == new_id      the model3d files written under the
                                         new id are the ones actually served;
                                         with the marker they would be looked
                                         up under the SOURCE world's template
        cleanup_orphan_clones() keeps it — a clone without a position counts
                                         as off-map and is deleted, and this
                                         import is unplaced by design
      The template id used here is the seeded location, so it really exists
      in this storage — that is the case where _resolve_clones would merge a
      foreign template over the fresh rooms.

 [11] The RESPONSE SHAPE the UI reads. POST /api/content/import answers
      {status, result: <importer dict>} — props_missing sits under `result`,
      NOT at the top level. Asserted against the real route function.

Usage:  ./.venv/bin/python scripts/smoke_content_location_full.py
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="content-location-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="content-location-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.content_io import (  # noqa: E402
    export_location_to_zip, import_location_from_zip, preview_import_zip)
from app.core.location_model3d import _model_dir, _owner_id  # noqa: E402
from app.core.props import _prop_dir, create_prop, delete_prop  # noqa: E402
from app.models.inventory import _save_items, add_item_to_room  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    get_location_by_id)

FAILURES = []
CHECKED = 0


def read_bytes(p: Path):
    """Bytes of `p`, or None when it does not exist — a missing file must
    show up as a failed check, not as a traceback that hides the rest."""
    return p.read_bytes() if p.is_file() else None


def read_json(p: Path):
    """Parsed JSON of `p`, or {} when it is missing/unreadable (see above)."""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# --- Seed -----------------------------------------------------------------

loc = add_location(
    "Inn", "A cozy roadside inn.",
    rooms=[
        {"name": "Taproom", "description": "The common room."},
        {"name": "Cellar", "description": "Barrels and dust."},
    ],
)
loc_id = loc["id"]
room1_id = loc["rooms"][0]["id"]
print(f"Location {loc_id}, room 1 {room1_id}, {len(loc['rooms'])} rooms")

# 3D models: building + one room model, each with its JSON sidecar, plus the
# selection that says which tier is served.
mdir = _model_dir(_owner_id(loc_id), create=True)
(mdir / "building_1.glb").write_bytes(b"GLB-building")
(mdir / "building_1.json").write_text(json.dumps({"rotation": 0}), encoding="utf-8")
(mdir / f"room_{room1_id}_1.glb").write_bytes(b"GLB-room")
(mdir / f"room_{room1_id}_1.json").write_text(json.dumps({"rotation": 0}), encoding="utf-8")
# The ground room carries a model too — its id is reserved and must survive the
# import unchanged, which makes its filename a no-op for the remap.
(mdir / f"room_{GROUND_ROOM_ID}_1.glb").write_bytes(b"GLB-ground")
(mdir / f"room_{GROUND_ROOM_ID}_1.json").write_text(json.dumps({"rotation": 0}), encoding="utf-8")
(mdir / "selection.json").write_text(json.dumps({
    "building": {"full": "building_1.glb"},
    f"room_{room1_id}": {"full": f"room_{room1_id}_1.glb"},
    f"room_{GROUND_ROOM_ID}": {"full": f"room_{GROUND_ROOM_ID}_1.glb"},
}), encoding="utf-8")

# Prop + placement in room 1
prop = create_prop(name="Chair", category="furniture", width_m=0.5,
                   depth_m=0.5, height_m=1.0)
prop_id = prop["id"]
(_prop_dir(prop_id, create=True) / "model_1.glb").write_bytes(b"GLB-prop")

data = _load_world_data()
for entry in data.get("locations", []):
    if entry.get("id") != loc_id:
        continue
    # Placed on the map — the import must NOT inherit this, or the copy
    # lands exactly on top of the original.
    entry["pos_x"] = 12.5
    entry["pos_z"] = -3.25
    entry["yaw_deg"] = 42.0
    for room in entry.get("rooms", []):
        if room.get("id") == room1_id:
            room.setdefault("layout", {})["props"] = [
                {"prop_id": prop_id, "at": [0.5, 0.5], "yaw": 0},
            ]
_save_world_data(data)

# World item + image + room placement
item_id = "mug_of_ale"
_save_items([{
    "id": item_id,
    "name": "Mug of Ale",
    "category": "consumable",
    "prompt_fragment": "a wooden mug of ale",
}])
from app.models.inventory import _get_item_dir  # noqa: E402
(_get_item_dir(item_id) / "bild.png").write_bytes(b"PNG-item")
check("item placed in room", add_item_to_room(loc_id, room1_id, item_id), True)

# --- Export ---------------------------------------------------------------

print("\n[1] export_location_to_zip — ZIP layout")
blob = export_location_to_zip(loc_id)
zf = zipfile.ZipFile(io.BytesIO(blob))
names = set(zf.namelist())

check("model3d building im ZIP", "files/model3d/building_1.glb" in names, True)
check("model3d building sidecar im ZIP", "files/model3d/building_1.json" in names, True)
check("model3d room im ZIP", f"files/model3d/room_{room1_id}_1.glb" in names, True)
check("model3d ground-room im ZIP",
      f"files/model3d/room_{GROUND_ROOM_ID}_1.glb" in names, True)
check("model3d selection im ZIP", "files/model3d/selection.json" in names, True)
check("prop dir im ZIP", f"props/{prop_id}/model_1.glb" in names, True)
check("prop sidecar im ZIP", f"props/{prop_id}/sidecar.json" in names, True)
check("items.json im ZIP", "db/items.json" in names, True)
check("item files im ZIP", f"item_files/{item_id}/bild.png" in names, True)
check("location.json bleibt im ZIP", "db/location.json" in names, True)

print("\n[2] manifest")
manifest = json.loads(zf.read("manifest.json"))
check("manifest version bleibt 1", manifest["version"], 1)
check("manifest type", manifest["type"], "location")
check("manifest model3d_file_count", manifest["model3d_file_count"], 7)
check("manifest prop_ids", manifest["prop_ids"], [prop_id])
check("manifest embedded_items", manifest["embedded_items"], [item_id])
check("manifest files (keine Galerie geseedet)", manifest["files"], [])

print("\n[3] Inhalte kommen unveraendert an")
check("building glb bytes", zf.read("files/model3d/building_1.glb"), b"GLB-building")
check("prop glb bytes", zf.read(f"props/{prop_id}/model_1.glb"), b"GLB-prop")
item_rows = json.loads(zf.read("db/items.json"))
check("items.json enthaelt genau ein Item", len(item_rows), 1)
check("item id", item_rows[0]["id"], item_id)
check("item name", item_rows[0]["name"], "Mug of Ale")
check("kein Runtime-Key _shared", "_shared" in item_rows[0], False)
zf.close()

# --- Round-trip (Task 2) --------------------------------------------------

print("\n[4] Import in DIESELBE Welt — Remap, unplatziert, Prop existiert schon")
res = import_location_from_zip(blob)
new_id = res["location_id"]
loc2 = get_location_by_id(new_id)
check("neue Location-id", new_id != loc_id, True)
check("import ist unplatziert (pos_x)", loc2.get("pos_x"), None)
check("import ist unplatziert (pos_z)", loc2.get("pos_z"), None)
check("yaw nicht mitgereist", loc2.get("yaw_deg"), 0.0)

md = STORAGE / "locations" / new_id / "model3d"
r1_new = loc2["rooms"][0]["id"]          # Raum-Reihenfolge bleibt erhalten
check("Raum 1 hat eine neue id", r1_new != room1_id, True)
check("Raumzahl unveraendert", len(loc2["rooms"]), 3)
check("Ground-Room ist noch da",
      any(r.get("id") == GROUND_ROOM_ID for r in loc2["rooms"]), True)
check("Ground-Room behaelt ihre reservierte id",
      loc2["rooms"][2]["id"], GROUND_ROOM_ID)
check("Ground-Room-Modell behaelt seinen Namen",
      read_bytes(md / f"room_{GROUND_ROOM_ID}_1.glb"), b"GLB-ground")
check("building GLB da", (md / "building_1.glb").exists(), True)
check("building sidecar da", (md / "building_1.json").exists(), True)
check("building bytes unveraendert", read_bytes(md / "building_1.glb"), b"GLB-building")
check("room GLB umbenannt", (md / f"room_{r1_new}_1.glb").exists(), True)
check("room sidecar umbenannt", (md / f"room_{r1_new}_1.json").exists(), True)
check("alte room-Datei weg", (md / f"room_{room1_id}_1.glb").exists(), False)

sel = read_json(md / "selection.json")
check("selection stem remapped", f"room_{r1_new}" in sel, True)
check("selection alter stem weg", f"room_{room1_id}" in sel, False)
check("selection filename remapped", (sel.get(f"room_{r1_new}") or {}).get("full"),
      f"room_{r1_new}_1.glb")
check("selection building unangetastet", (sel.get("building") or {}).get("full"),
      "building_1.glb")
check("selection ground-room unangetastet",
      (sel.get(f"room_{GROUND_ROOM_ID}") or {}).get("full"),
      f"room_{GROUND_ROOM_ID}_1.glb")

check("model3d_files gezaehlt", res["model3d_files"], 7)
check("prop existierte schon", res["props_existing"], [prop_id])
check("nichts neu installiert", res["props_imported"], [])
check("keine Prop fehlt", res["props_missing"], [])
check("prop placement zeigt weiter auf sie",
      loc2["rooms"][0]["layout"]["props"][0]["prop_id"], prop_id)
check("item nicht doppelt angelegt", res["items_imported"], [])

print("\n[5] Import in eine Welt OHNE die Prop — sie wird mitinstalliert")
check("prop geloescht", delete_prop(prop_id), True)
res2 = import_location_from_zip(blob)
check("prop neu installiert", res2["props_imported"], [prop_id])
check("nichts als existierend gemeldet", res2["props_existing"], [])
check("keine Prop fehlt", res2["props_missing"], [])
pdir = _prop_dir(prop_id)
check("prop glb wiederhergestellt", read_bytes(pdir / "model_1.glb"), b"GLB-prop")
check("prop sidecar wiederhergestellt", (pdir / "sidecar.json").exists(), True)

print("\n[6] ZIP ohne props/ + Prop geloescht — props_missing statt Stille")
src = zipfile.ZipFile(io.BytesIO(blob))
strip_buf = io.BytesIO()
with zipfile.ZipFile(strip_buf, "w", zipfile.ZIP_DEFLATED) as out:
    for m in src.namelist():
        if not m.startswith("props/"):
            out.writestr(m, src.read(m))
src.close()
check("prop erneut geloescht", delete_prop(prop_id), True)
res3 = import_location_from_zip(strip_buf.getvalue())
check("fehlende Prop gemeldet", res3["props_missing"], [prop_id])
check("nichts installiert", res3["props_imported"], [])
check("nichts existierte", res3["props_existing"], [])

print("\n[7] ALTES v1-ZIP ohne die neuen Verzeichnisse laeuft sauber durch")
old_loc = {
    "id": "oldloc01",
    "name": "Old Inn",
    "description": "An export from before E9.",
    "pos_x": 5.0, "pos_z": 6.0, "yaw_deg": 90.0,
    "rooms": [{
        "id": "oldroom1", "name": "Taproom", "description": "",
        "layout": {"props": [{"prop_id": prop_id, "at": [0.5, 0.5], "yaw": 0}]},
    }],
}
old_buf = io.BytesIO()
with zipfile.ZipFile(old_buf, "w", zipfile.ZIP_DEFLATED) as out:
    out.writestr("db/location.json", json.dumps(old_loc, ensure_ascii=False))
    out.writestr("files/gallery/room.png", b"PNG-gallery")
    out.writestr("manifest.json", json.dumps({
        "version": 1, "type": "location", "location_id": "oldloc01",
        "location_name": "Old Inn", "room_count": 1, "image_count": 1,
        "exported_at": "2026-01-01T00:00:00Z", "files": ["gallery/room.png"],
    }, ensure_ascii=False))
old_blob = old_buf.getvalue()
res4 = import_location_from_zip(old_blob)
check("alt-ZIP importiert", res4["status"], "success")
check("alt-ZIP: keine model3d-Dateien", res4["model3d_files"], 0)
check("alt-ZIP: nichts gebundelt", res4["props_imported"], [])
check("alt-ZIP: fehlende Prop gemeldet statt Crash", res4["props_missing"], [prop_id])
check("alt-ZIP: keine Items", res4["items_imported"], [])
check("alt-ZIP: Galerie kam an", res4["files_imported"], 1)
check("alt-ZIP: unplatziert", get_location_by_id(res4["location_id"]).get("pos_x"), None)

print("\n[8] preview_import_zip nennt die Bundle-Bestandteile")
prev = preview_import_zip(blob)
check("preview type", prev["type"], "location")
check("preview name mit Zaehlern", prev["elements"][0]["name"],
      "Inn (3 rooms, 7 model files, 1 props)")
prev_old = preview_import_zip(old_blob)
check("preview alt-ZIP mit Defaults", prev_old["elements"][0]["name"],
      "Old Inn (1 rooms, 0 model files, 0 props)")

print("\n[9] props/<ungueltige id>/ zaehlt NICHT als geliefert")
bad_pid = "Bad Prop!"                     # safe_prop_id() lehnt das ab
bad_loc = {
    "id": "badloc01", "name": "Bad Inn", "description": "",
    "rooms": [{
        "id": "badroom1", "name": "Taproom", "description": "",
        "layout": {"props": [{"prop_id": bad_pid, "at": [0.5, 0.5], "yaw": 0}]},
    }],
}
bad_buf = io.BytesIO()
with zipfile.ZipFile(bad_buf, "w", zipfile.ZIP_DEFLATED) as out:
    out.writestr("db/location.json", json.dumps(bad_loc, ensure_ascii=False))
    out.writestr(f"props/{bad_pid}/model_1.glb", b"GLB-bad")
    out.writestr("manifest.json", json.dumps({
        "version": 1, "type": "location", "location_id": "badloc01",
        "location_name": "Bad Inn", "room_count": 1, "image_count": 0,
        "exported_at": "2026-01-01T00:00:00Z", "files": [],
        "model3d_file_count": 0, "prop_ids": [bad_pid], "embedded_items": [],
    }, ensure_ascii=False))
res5 = import_location_from_zip(bad_buf.getvalue())
check("ungueltige id nicht installiert", res5["props_imported"], [])
check("ungueltige id nicht als existierend gemeldet", res5["props_existing"], [])
check("ungueltige id landet in props_missing", res5["props_missing"], [bad_pid])
check("kein Verzeichnis unter dem rohen Namen angelegt",
      (STORAGE / "props" / bad_pid).exists(), False)

print("\n[10] Klon-Export wird zu einer eigenstaendigen Kopie")
csrc = zipfile.ZipFile(io.BytesIO(blob))
clone_loc = json.loads(csrc.read("db/location.json"))
clone_loc["template_location_id"] = loc_id       # Template existiert hier wirklich
clone_buf = io.BytesIO()
with zipfile.ZipFile(clone_buf, "w", zipfile.ZIP_DEFLATED) as out:
    for m in csrc.namelist():
        out.writestr(m, json.dumps(clone_loc, ensure_ascii=False)
                     if m == "db/location.json" else csrc.read(m))
csrc.close()
res6 = import_location_from_zip(clone_buf.getvalue())
cid = res6["location_id"]
loc6 = get_location_by_id(cid)
check("Klon-Marker ist weg", "template_location_id" in loc6, False)
check("Modelle werden unter der NEUEN id gesucht", _owner_id(cid), cid)
c_r1 = loc6["rooms"][0]["id"]
check("Raum-Remap ueberlebt", c_r1 not in (room1_id, ""), True)
check("Raum-Modell liegt unter der neuen Raum-id",
      read_bytes(_model_dir(_owner_id(cid)) / f"room_{c_r1}_1.glb"), b"GLB-room")
check("Ground-Room auch hier reserviert",
      any(r.get("id") == GROUND_ROOM_ID for r in loc6["rooms"]), True)
from app.models.world import cleanup_orphan_clones  # noqa: E402
cleanup_orphan_clones()
check("Klon-Aufraeumer loescht den Import NICHT",
      (get_location_by_id(cid) or {}).get("id"), cid)

print("\n[11] Antwort-Shape von POST /api/content/import")
check("prop fuer den Shape-Test geloescht", delete_prop(prop_id), True)
from fastapi import UploadFile  # noqa: E402
from app.routes.content_packs import import_selected  # noqa: E402
resp = asyncio.run(import_selected(
    file=UploadFile(file=io.BytesIO(strip_buf.getvalue()), filename="loc.zip"),
    selected_ids="", overwrite=False, mode="full", intro=""))
check("Antwort-Keys", sorted(resp.keys()), ["result", "status"])
check("props_missing NICHT auf oberster Ebene", "props_missing" in resp, False)
check("props_missing unter result (das liest die UI)",
      resp["result"]["props_missing"], [prop_id])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("OK")
